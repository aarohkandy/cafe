"""Live sessions: YOUR fleet code drives the drones, the simulator supplies physics and weather.

    create  -> World with one run per drone (no Monte Carlo) and an "external" leg per drone
    step    -> set each drone's target (lat, lon, depth/altitude, optional speed), advance N seconds
    state   -> where everything is, battery, local current/wind, and every range requirement

The built-in autopilots fly to the targets (like a GUIDED-mode autopilot would), so your code is tested
at the level it actually works: deciding where each drone should be.
"""
import threading, time, uuid
import numpy as np

from cafe import dyn
from cafe.mission import World, TICK, z_to_down

SESSIONS = {}
LOCK = threading.Lock()
MAX_SESSIONS = 4
MAX_DRONES = 12
IDLE_S = 3600


def create(body, load_vehicle):
    with LOCK:
        for sid in [k for k, s in SESSIONS.items() if time.time() - s["used"] > IDLE_S]:
            SESSIONS.pop(sid)
        if len(SESSIONS) >= MAX_SESSIONS:
            raise ValueError("too many live sessions open; end one first")
    if not (1 <= len(body.get("drones") or []) <= MAX_DRONES):
        raise ValueError(f"a live session takes 1 to {MAX_DRONES} drones")
    from cafe import env as envm
    import datetime as dt
    t0 = dt.datetime.fromisoformat(body["t0"])
    avail = envm.hours_after(t0)
    mission = dict(t0=body["t0"], max_hours=max(1.0, min(48.0, avail - 1)), samples=1, seed=body.get("seed", 0), links=body.get("links", []),
                   drones=[dict(id=x["id"], vehicle=load_vehicle(x["design"]), start=x["start"],
                                legs=[{"type": "external"}]) for x in body["drones"]])
    w = World(mission, B=1)
    sid = uuid.uuid4().hex          # the id is the only key to the session: keep it unguessable
    with LOCK:
        SESSIONS[sid] = dict(world=w, used=time.time(), lock=threading.Lock())
    return sid, state(w)


def get(sid):
    s = SESSIONS.get(sid)
    if s is None:
        raise KeyError(sid)
    s["used"] = time.time()
    return s


def step(sid, seconds, targets):
    s = get(sid)
    w = s["world"]
    if not (0 < seconds <= 600):
        raise ValueError("step between 0 and 600 seconds at a time")
    if not isinstance(targets or {}, dict):
        raise ValueError("targets must be {drone_id: {lat, lon, z, speed}}")
    with s["lock"]:
        new = {}                          # check every target first: a bad one changes nothing
        for did, tg in (targets or {}).items():
            d = w.by_id.get(did)
            if d is None:
                raise ValueError(f"no drone {did!r} in this session")
            try:
                lat, lon, z = float(tg["lat"]), float(tg["lon"]), float(tg.get("z", 0))
                speed = None if tg.get("speed") is None else float(tg["speed"])
            except (KeyError, TypeError, ValueError):
                raise ValueError(f"{did}: target needs numeric lat, lon (and optional z, speed)")
            if not all(np.isfinite([lat, lon, z])) or not (-90 <= lat <= 90):
                raise ValueError(f"{did}: target is not a real position")
            if speed is not None and not (0 < speed <= float(np.max(d.ap.v_max))):
                raise ValueError(f"{did}: speed must be above 0 and at most {float(np.max(d.ap.v_max)):.2f} m/s")
            if d.veh.kind != "usv" and z < 0:
                raise ValueError(f"{did}: z is {'depth' if d.veh.kind == 'uuv' else 'altitude'} and must be >= 0")
            if d.veh.kind != "uav" and w.E.surface(lat, lon, w.t)["land"].any():
                raise ValueError(f"{did}: target is on land")
            n, e = w.frame.to_ne(lat, lon)
            p = np.array([n, e, d.st.p[0, 2] if d.veh.kind == "usv" else z_to_down(d.veh.kind, z)])
            new[did] = (p, speed)
        for did, (p, speed) in new.items():
            leg = w.by_id[did].legs[0]
            leg["_p"], leg["_speed"] = p, speed
        for _ in range(int(round(seconds / TICK))):
            w.tick()
        return state(w)


def state(w):
    out = dict(t=round(w.t, 2), drones={}, links=[])
    for d in w.drones:
        lat, lon = w.frame.to_ll(d.st.p[:, 0], d.st.p[:, 1])
        R = dyn.quat_to_R(d.st.q)[0]
        v = R @ d.st.v[0]
        eul = np.degrees(dyn.quat_to_euler(d.st.q)[0])
        e = d.env
        flow = e["wind_ne"][0] if d.veh.kind == "uav" else e["current_ne"][0]
        out["drones"][d.id] = dict(
            lat=float(lat[0]), lon=float(lon[0]), z=float(-d.st.p[0, 2]) if d.veh.kind != "uuv" else float(d.st.p[0, 2]),
            z_meaning="depth (m)" if d.veh.kind == "uuv" else "altitude (m)", heading_deg=float(eul[2] % 360),
            ground_speed=float(np.hypot(v[0], v[1])), vertical_speed=float(-v[2]),
            battery_left=float(1 - d.st.energy_wh[0] / d.veh.battery_wh), alive=bool(d.st.alive[0]),
            failure=str(d.fail[0]) or None, flow_ne=[float(x) for x in flow],
            flow_kind="wind" if d.veh.kind == "uav" else "current")
    for lk in w.links:
        e = lk.a.st.p[0] - lk.b.st.p[0]
        dist = float(np.linalg.norm(e[:2] if lk.horizontal else e))
        out["links"].append(dict(a=lk.a.id, b=lk.b.id, distance_m=dist, max_m=lk.max_m, in_range=dist <= lk.max_m))
    return out


def end(sid):
    with LOCK:
        SESSIONS.pop(sid, None)
