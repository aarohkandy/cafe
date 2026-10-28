"""Emulator: real ArduPilot firmware (SITL) flying our physics, through ArduPilot's JSON backend.

    python -m cafe.emulator /work/emulations/<id>     (emulation.json written by the app)

Per drone: our 6-DOF (same vehicle model, same weather-model wind/current/waves as fast mode) answers
SITL's servo packets in lockstep on UDP 9002+10*i; a MAVLink runner flies every leg in GUIDED mode,
so the firmware's own navigation, position and attitude controllers do the flying.

Bring your own firmware: anything that speaks the ArduPilot JSON SITL protocol (servo packet in,
JSON state out — libraries/SITL/examples/JSON/readme.md) can take a drone's place: run with
"external": true for that drone and point the firmware at UDP 9002+10*i of this host.
"""
import datetime as dt, json, os, pathlib, select, socket, struct, subprocess, sys, threading, time, traceback
import numpy as np

from cafe import dyn, env as envm, ctrl
from cafe.mission import Frame, z_to_down, _float_depth
from cafe.vehicle import G, prop_perf

SITL_DIR = pathlib.Path(os.environ.get("CAFE_WORK", "/work")) / "sitl"
FIRMWARE = {"uav": ("arducopter", ["copter.parm", "copter-X.parm"]),
            "usv": ("ardurover", ["rover.parm", "motorboat.parm", "rover-skid.parm"]),
            "uuv": ("ardusub", ["sub.parm"])}
GUIDED = {"uav": 4, "usv": 15, "uuv": 4}
SPEEDUP = 2


def firmware_params(veh, cruise):
    """Tell the autopilot what it is flying, from the hangar's model (what a builder would tune)."""
    k = veh.kind
    p = {"SIM_RATE_HZ": 400, "ARMING_CHECK": 0, "BATT_MONITOR": 4}
    if k == "uav":
        a = veh.actuators[0]
        hover = veh.mass * G / (4 * a.tmax)                 # thrust fraction at hover (ArduPilot's units)
        p.update(FRAME_CLASS=1, FRAME_TYPE=1, MOT_PWM_MIN=1000, MOT_PWM_MAX=2000,
                 MOT_SPIN_ARM=0.02, MOT_SPIN_MIN=0.03, MOT_SPIN_MAX=1.0,   # full PWM range = our full motor speed
                 MOT_THST_EXPO=0.98,                        # our props: thrust ~ (motor speed)^2 ~ pwm^2
                 MOT_THST_HOVER=round(float(hover), 3), MOT_HOVER_LEARN=2,
                 MOT_BAT_VOLT_MAX=4.2 * veh.cells, MOT_BAT_VOLT_MIN=3.3 * veh.cells,
                 WPNAV_SPEED=int(min(cruise, 15) * 100), WPNAV_RADIUS=200,
                 SCHED_LOOP_RATE=200)    # the IMU (= our physics, 400 Hz) must run >= 1.8x the main loop
    elif k == "usv":
        thr = _cruise_throttle(veh, cruise)
        p.update(FRAME_CLASS=2, SERVO1_FUNCTION=73, SERVO3_FUNCTION=74, CRUISE_SPEED=round(cruise, 2),
                 CRUISE_THROTTLE=int(np.clip(thr * 100, 5, 100)), WP_RADIUS=3)
    else:
        p.update(FRAME_CONFIG=1, WPNAV_SPEED=int(cruise * 100))
    return p


def _cruise_throttle(veh, V):
    us = np.linspace(0, 1, 501)
    fwd = [a for a in veh.actuators if a.kind == "prop" and a.dir[0] > 0.5]
    T = sum(prop_perf(a.fluid, a.D, a.wmax / (2 * np.pi), a.rev, us, V)[0] for a in fwd)
    D = -dyn.Dynamics(veh, 1).drag(np.array([[V, 0.0, 0.0]]))[0][0, 0]
    return float(us[np.argmax(T >= D)]) if (T >= D).any() else 1.0


def pwm_to_cmd(kind, pwm, n):
    pwm = np.asarray(pwm, float)
    if kind == "uav":
        return np.clip((pwm[:n] - 1000) / 1000, 0, 1)
    if kind == "usv":                                      # skid: SERVO1 ThrottleLeft (port), SERVO3 ThrottleRight
        out = np.zeros(n)                                  # props first; skegs etc. are passive
        out[:2] = np.clip((pwm[[0, 2]] - 1500) / 400, -1, 1)
        return out
    out = (pwm[:n] - 1500) / 400                            # ArduSub: +-400 us, 25 us deadband (SIM_Submarine.cpp)
    out[np.abs(pwm[:n] - 1500) < 25] = 0
    return np.clip(out, -1, 1)


def free_instance(taken):
    """First SITL instance number whose ports (TCP 5760/5762/5763 + 10I, UDP 9002/9003 + 10I) are all free.
    A killed SITL leaves its listening sockets in TIME_WAIT for a while; never assume they're gone."""
    for I in range(0, 40):
        if I in taken:
            continue
        socks = []
        try:
            for port, kind in ((5760, socket.SOCK_STREAM), (5762, socket.SOCK_STREAM), (5763, socket.SOCK_STREAM),
                               (9002, socket.SOCK_DGRAM), (9003, socket.SOCK_DGRAM)):
                sk = socket.socket(socket.AF_INET, kind)
                socks.append(sk)
                sk.bind(("0.0.0.0", port + 10 * I))
            return I
        except OSError:
            continue
        finally:
            for sk in socks:
                sk.close()
    raise RuntimeError("no free SITL instance ports")


class Sim:
    """One drone's physics, answering one SITL instance."""

    def __init__(self, i, spec, veh, frame, E, t_offset):
        self.i, self.id, self.veh, self.kind = i, spec["id"], veh, veh.kind     # i = SITL instance number
        self.dyn = dyn.Dynamics(veh, 1)
        n, e = frame.to_ne(spec["start"][0], spec["start"][1])
        z = z_to_down(self.kind, spec["start"][2] if len(spec["start"]) > 2 else 0)
        self.st = dyn.State(1, len(veh.actuators), p=[n, e, z])
        if self.kind == "usv":
            self.st.p[:, 2] = _float_depth(veh)
        self.home = self.st.p[0].copy()
        self.deck = self.kind == "uav"                      # quads start on a launch deck at their start height
        self.frame, self.E, self.t_offset = frame, E, t_offset
        self.env, self.env_t = None, -1e9
        e0 = self._sample()
        hs, tp = (float(x[0]) for x in envm.sea_state(e0))
        heading = np.arctan2(e0["wind10_ne"][0, 1], e0["wind10_ne"][0, 0])
        self.waves = envm.Waves.stack([envm.Waves(float(hs), float(tp), float(heading), n=24, seed=i)])
        self.gust = envm.Gusts(100 + i, 1)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("0.0.0.0", 9002 + 10 * i))
        self.track, self.next_rec, self.last_fc = [], 0.0, -1
        self.lock = threading.Lock()

    def _sample(self):
        lat, lon = self.frame.to_ll(self.st.p[:, 0], self.st.p[:, 1])
        return self.E.at(lat, lon, np.array([self.st.t + self.t_offset]), -self.st.p[:, 2])

    def step(self, pwm, dt_s):
        k, st = self.kind, self.st
        if st.t - self.env_t >= 1.0:
            self.env, self.env_t = self._sample(), st.t
        e = self.env
        flow = np.zeros((1, 3)); acc = None
        if k == "uav":
            w = np.column_stack([e["wind_ne"], [[0.0]]])
            sp = float(np.linalg.norm(w))
            g = self.gust.step(dt_s, -st.p[:, 2], np.hypot(*e["wind10_ne"].T) * 0.95, np.array([sp]))[0]
            flow = w + np.array([[0, 0, -g[2]]]) + g[0] * w / max(sp, 1e-6)
        else:
            flow[:, :2] = e["current_ne"]
            orb, oacc = self.waves.orbital(st.p[:, None, 0], st.p[:, None, 1], -st.p[:, None, 2], st.t)
            flow += orb[:, 0] * [1, 1, -1]; acc = oacc[:, 0] * [1, 1, -1]
        cmd = pwm_to_cmd(k, pwm, len(self.veh.actuators))[None]
        envd = dict(flow_ned=flow, wind_ned=np.column_stack([e["wind_ne"], [[0.0]]]), rho_air=e["rho_air"])
        if acc is not None:
            envd["flow_acc_ned"] = acc
        with self.lock:
            out = self.dyn.step(st, cmd, envd, dt_s, None if k == "uav" else self.waves)
            self.last_power = float(out["power"][0])
            if self.deck:                                   # resting on the deck until it lifts off
                on = st.p[0, 2] >= self.home[2] and np.hypot(*(st.p[0, :2] - self.home[:2])) < 3
                if on:
                    st.p[0, 2] = self.home[2]; st.v[:] = 0; st.w[:] = 0
                    yaw = dyn.quat_to_euler(st.q)[0, 2]
                    st.q[:] = dyn.euler_to_quat(0.0, 0.0, yaw)
                    st.accel_body[:] = [0, 0, -G]
                    st.alive[:] = True
                elif st.p[0, 2] < self.home[2] - 1:
                    self.deck = False                       # airborne: the sea is the only floor now
        if st.t >= self.next_rec:
            self.record()
            self.next_rec += 1.0

    def record(self):
        st = self.st
        lat, lon = self.frame.to_ll(st.p[:, 0], st.p[:, 1])
        eul = np.degrees(dyn.quat_to_euler(st.q))[0]
        self.track.append(dict(t=round(st.t, 1), lat=[round(float(lat[0]), 7)], lon=[round(float(lon[0]), 7)],
                               z=[round(float(-st.p[0, 2]), 2)], roll=[round(float(eul[0]), 1)],
                               pitch=[round(float(eul[1]), 1)], yaw=[round(float(eul[2]), 1)],
                               wh=[round(float(st.energy_wh[0]), 2)], leg=[0],
                               wind=np.round(self.env["wind_ne"][0], 2).tolist(),
                               current=np.round(self.env["current_ne"][0], 3).tolist()))

    def reply(self):
        st = self.st
        R = dyn.quat_to_R(st.q)[0]
        soc = max(0.0, 1 - st.energy_wh[0] / self.veh.battery_wh)
        volt = self.veh.cells * (3.5 + 0.7 * soc)
        rel = st.p[0] - [self.home[0], self.home[1], 0.0] if self.kind == "uuv" else st.p[0] - self.home
        # field order matters to SITL's parser: "velocity" must come before anything containing it
        return (json.dumps(dict(timestamp=st.t, imu=dict(gyro=st.w[0].tolist(), accel_body=st.accel_body[0].tolist()),
                                position=rel.tolist(), quaternion=st.q[0].tolist(), velocity=(R @ st.v[0]).tolist(),
                                battery=dict(voltage=volt, current=self.last_power / volt))) + "\n").encode()

    last_power = 0.0

    def serve_once(self):
        data, addr = self.sock.recvfrom(256)
        if len(data) == 40:
            magic, rate, fc, *pwm = struct.unpack("<HHI16H", data)
            ok = magic == 18458
        elif len(data) == 72:
            magic, rate, fc, *pwm = struct.unpack("<HHI32H", data)
            ok = magic == 29569
        else:
            return
        if not ok:
            return
        if fc != self.last_fc:                       # a repeated frame (lost reply) is answered, not re-stepped
            self.step(pwm, 1.0 / max(rate, 50))
            self.last_fc = fc
        self.sock.sendto(self.reply(), addr)


class Runner(threading.Thread):
    """Flies one drone's legs through MAVLink, GUIDED mode, using the firmware's own controllers."""

    def __init__(self, i, spec, sim, sims, frame, log, max_s):
        super().__init__(daemon=True)
        self.i, self.spec, self.sim, self.sims, self.frame, self.log, self.max_s = i, spec, sim, sims, frame, log, max_s
        self.legs_done, self.status, self.messages = [], "starting", []
        self.armed, self.mode = False, None

    def run(self):
        from pymavlink import mavutil
        k = self.sim.kind
        try:
            m = mavutil.mavlink_connection(f"tcp:127.0.0.1:{5760 + 10 * self.i}", source_system=250, retries=200)
            m.wait_heartbeat(timeout=120)
            self.m = m
            m.mav.request_data_stream_send(m.target_system, m.target_component, mavutil.mavlink.MAV_DATA_STREAM_ALL, 4, 1)
            self._wait_sim(20)                              # GPS lock + EKF settle (sim time)
            mav = mavutil.mavlink
            # every step is verified against what the autopilot reports, and retried; its messages are kept
            self._until(lambda: self.mode == GUIDED[k], 60, "switch to GUIDED", lambda: m.mav.command_long_send(
                m.target_system, m.target_component, mav.MAV_CMD_DO_SET_MODE, 0, mav.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED,
                GUIDED[k], 0, 0, 0, 0, 0))
            # force: SITL's simulated-sensor calibration checks are not the question being asked here
            self._until(lambda: self.armed, 60, "arm", lambda: m.mav.command_long_send(
                m.target_system, m.target_component, mav.MAV_CMD_COMPONENT_ARM_DISARM, 0, 1, 21196, 0, 0, 0, 0, 0))
            if k == "uav":
                h0 = -self.sim.st.p[0, 2]
                self._until(lambda: -self.sim.st.p[0, 2] > h0 + 3, 40, "take off", lambda: m.mav.command_long_send(
                    m.target_system, m.target_component, mav.MAV_CMD_NAV_TAKEOFF, 0, 0, 0, 0, 0, 0, 0, 10))
            self.status = "flying"
            t_leg0 = self.sim.st.t
            for li, leg in enumerate(self.spec["legs"]):
                self.status = f"leg {li + 1}: {leg['type']}"
                tol = leg.get("tol_m", 3 if k == "uav" else 10)
                t0 = self.sim.st.t
                while self.sim.st.t < self.max_s:
                    tgt, done_by_time = self._goal(leg)
                    self._send(tgt)
                    err = np.linalg.norm((self.sim.st.p[0] - tgt)[:2 if k == "usv" else 3])
                    if leg["type"] == "goto" and err < tol:
                        break
                    if done_by_time and self.sim.st.t - t0 >= leg["minutes"] * 60:
                        break
                    if leg["type"] in ("hold", "follow") and self.sim.st.t - t0 > 30:
                        self.sim.errors.setdefault(li, []).append(float(err))
                    if not self.sim.st.alive[0]:
                        raise RuntimeError("lost the vehicle (battery empty or touched the water)")
                    self._wait_sim(0.5)
                else:
                    raise RuntimeError(f"ran out of time on leg {li + 1}")
                self.legs_done.append(dict(leg=li, t_min=(self.sim.st.t - t_leg0) / 60))
            self.status = "done"
        except Exception as e:
            self.status = f"failed: {e}"
            self.log(f"{self.spec['id']}: {e}")
        finally:
            self.messages = getattr(self, "messages", [])

    def _goal(self, leg):   # (not "_target": threading.Thread owns that name)
        if leg["type"] == "goto":
            if leg["to"] == "start":
                return self.sim.home.copy(), False
            n, e = self.frame.to_ne(leg["to"][0], leg["to"][1])
            return np.array([n, e, z_to_down(self.sim.kind, leg["to"][2] if len(leg["to"]) > 2 else 0)]), False
        if leg["type"] == "hold":
            if not hasattr(self, "_hold") or self._hold_leg is not leg:
                self._hold, self._hold_leg = self.sim.st.p[0].copy(), leg
            return self._hold, True
        lead = self.sims[leg["target"]]
        off = np.array(leg.get("offset", [0, 0, 0]), float)
        p = lead.st.p[0] + [off[0], off[1], -off[2]]
        return p, True

    def _send(self, p):
        lat, lon = self.frame.to_ll(np.array([p[0]]), np.array([p[1]]))
        alt = -p[2] - (-self.sim.home[2] if self.sim.kind == "uav" else 0.0)   # relative to home altitude
        self.m.mav.set_position_target_global_int_send(
            0, self.m.target_system, self.m.target_component, 6,      # MAV_FRAME_GLOBAL_RELATIVE_ALT_INT
            0b0000111111111000, int(lat[0] * 1e7), int(lon[0] * 1e7), float(alt), 0, 0, 0, 0, 0, 0, 0, 0)
        self._drain()

    armed, mode = False, None

    def _until(self, cond, sim_s, what, action):
        t_end = self.sim.st.t + sim_s
        while not cond():
            if self.sim.st.t > t_end:
                last = "; ".join(x["text"] for x in self.messages[-3:]) or "no reply"
                raise RuntimeError(f"autopilot would not {what} (it said: {last})")
            action()
            self._wait_sim(2)

    def _wait_sim(self, seconds):
        t_end = self.sim.st.t + seconds
        while self.sim.st.t < t_end:
            time.sleep(0.02)
            self._drain()

    def _drain(self):
        while (msg := self.m.recv_match(blocking=False)) is not None:
            ty = msg.get_type()
            if ty == "HEARTBEAT" and msg.get_srcSystem() == self.m.target_system:
                self.armed = bool(msg.base_mode & 128); self.mode = msg.custom_mode
            elif ty == "STATUSTEXT":
                self.messages.append(dict(t=round(self.sim.st.t, 1), text=msg.text))
            elif ty == "COMMAND_ACK" and msg.result not in (0, 5):    # 0 accepted, 5 in progress
                self.messages.append(dict(t=round(self.sim.st.t, 1), text=f"command {msg.command} refused ({msg.result})"))


def run(d):
    d = pathlib.Path(d)
    spec = json.loads((d / "emulation.json").read_text())
    log = lambda s: (print(s, flush=True), open(d / "log.txt", "a").write(s + "\n"))
    status = lambda **kw: (d / "status.json").write_text(json.dumps(dict(updated=time.time(), **kw)))
    from cafe import hangar
    designs = d.parent.parent / "designs"
    drones = spec["drones"]
    t0 = dt.datetime.fromisoformat(spec["t0"])
    max_s = spec.get("max_hours", 1) * 3600
    frame = Frame(drones[0]["start"][0], drones[0]["start"][1])
    lats = [x["start"][0] for x in drones] + [l["to"][0] for x in drones for l in x["legs"] if l["type"] == "goto" and l["to"] != "start"]
    lons = [x["start"][1] for x in drones] + [l["to"][1] for x in drones for l in x["legs"] if l["type"] == "goto" and l["to"] != "start"]
    status(state="running", step="fetching ocean data", progress=0.0)
    E = envm.Env(t0, max_s / 3600 + 1, (min(lats) - 0.2, max(lats) + 0.2), (min(lons) - 0.2, max(lons) + 0.2))
    sims, procs, runners = {}, [], []
    try:
        for i, x in enumerate(drones):
            veh = hangar.load_vehicle(designs / x["design"])
            if veh.kind == "uuv" and ctrl.family(veh) != "holonomic":
                raise ValueError(f"{x['id']}: ArduSub flies thruster-only frames; this sub steers with fins, "
                                 "so it can only be checked in fast mode")
            inst = free_instance({s.i for s in sims.values()})
            sim = Sim(inst, x, veh, frame, E, 0.0)
            sim.errors = {}
            sims[x["id"]] = sim
            if not x.get("external"):
                binary, parms = FIRMWARE[veh.kind]
                i = inst
                work = d / f"sitl{i}"; work.mkdir(exist_ok=True)
                pf = work / "cafe.parm"
                pf.write_text("".join(f"{k} {v}\n" for k, v in firmware_params(veh, ctrl.cruise_speed(veh)).items()))
                defaults = ",".join([str(SITL_DIR / p) for p in parms] + [str(pf)])
                lat, lon = frame.to_ll(np.array([sim.home[0]]), np.array([sim.home[1]]))
                alt = -sim.home[2] if veh.kind == "uav" else 0.0
                cmd = [str(SITL_DIR / binary), "-w", "--model", "JSON:127.0.0.1", "-I", str(i), "--sysid", str(i + 1),
                       "--home", f"{lat[0]:.7f},{lon[0]:.7f},{alt:.2f},0", "--defaults", defaults, "--speedup", str(SPEEDUP)]
                procs.append(subprocess.Popen(cmd, cwd=work, stdout=open(work / "sitl.out", "w"), stderr=subprocess.STDOUT))
                log(f"{x['id']}: {binary} instance {i} (MAVLink tcp {5760 + 10 * i}, QGC tcp {5762 + 10 * i}, physics udp {9002 + 10 * i})")
            else:
                log(f"{x['id']}: waiting for external firmware on udp {9002 + 10 * i}")
        status(state="running", step="booting autopilots", progress=0.0)
        stop = threading.Event()

        crash = []

        def physics():
            socks = {s.sock: s for s in sims.values()}
            try:
                while not stop.is_set():
                    ready, _, _ = select.select(list(socks), [], [], 0.5)
                    for sk in ready:
                        socks[sk].serve_once()
            except Exception as e:                          # a dead physics thread must end the run, not hang it
                crash.append(f"physics: {type(e).__name__}: {e}")
                traceback.print_exc()
        th = threading.Thread(target=physics, daemon=True); th.start()
        for x in drones:
            r = Runner(sims[x["id"]].i, x, sims[x["id"]], sims, frame, log, max_s)
            r.start(); runners.append(r)
        while any(r.is_alive() for r in runners):
            if crash:
                raise RuntimeError(crash[0])
            t_sim = min(s.st.t for s in sims.values())
            status(state="running", step=", ".join(f"{r.spec['id']}: {r.status}" for r in runners), progress=min(t_sim / max_s, 1),
                   live={k: s.track[-1] for k, s in sims.items() if s.track})
            time.sleep(1)
        stop.set()
        res = dict(mode="emulator", firmware={x["id"]: FIRMWARE[sims[x["id"]].kind][0] for x in drones}, drones={})
        for r in runners:
            s = r.sim
            ok = r.status == "done"
            left = 1 - s.st.energy_wh[0] / s.veh.battery_wh
            errs = {li: float(np.percentile(v, 95)) for li, v in s.errors.items() if v}
            bad_hold = [li for li, e in errs.items() if e > r.spec["legs"][li].get("tol_m", 3 if s.kind == "uav" else 10)]
            reason = r.status if not ok else (f"hold/follow error over tolerance on leg {bad_hold[0] + 1}" if bad_hold
                                              else "under the battery reserve" if left < spec.get("reserve", 0.15) else "")
            res["drones"][r.spec["id"]] = dict(
                verdict="GO" if not reason else "NO-GO", p_success=1.0 if not reason else 0.0,
                reasons=[dict(reason=reason, share=1.0)] if reason else [], legs_done=r.legs_done, err95_m=errs,
                battery_left_p50=float(left), battery_left_p10=float(left), track=s.track, autopilot_messages=r.messages[-50:])
        (d / "result.json").write_text(json.dumps(res, default=float))
        status(state="done", progress=1.0)
    except Exception as e:
        traceback.print_exc()
        status(state="failed", error=f"{type(e).__name__}: {e}")
    finally:
        for p in procs:
            p.terminate()


if __name__ == "__main__":
    run(sys.argv[1])
