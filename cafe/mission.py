"""Missions: legs per drone, one shared clock for all drones, Monte Carlo over what we don't know,
and a verdict per drone in plain language.

mission = {
  "t0": "2023-03-07T17:00",                         # UTC, must be inside the weather data (WRF_DIR)
  "drones": [{"id": "sub", "vehicle": <Vehicle>, "start": [lat, lon, z],
              "legs": [{"type": "goto", "to": [lat, lon, z]},
                       {"type": "hold", "minutes": 30, "tol_m": 10},
                       {"type": "follow", "target": "boat", "offset": [0, 0, 20], "minutes": 20, "tol_m": 5},
                       {"type": "goto", "to": "start"}]}],
  "max_hours": 6, "reserve": 0.15, "samples": 24, "seed": 0}
z: altitude (m, up) for quads, depth (m, down) for subs, ignored for boats. Follow offsets are
(north, east, up) metres from the leader.
"""
import datetime as dt, time
import numpy as np

from cafe import ctrl, dyn, env as envm
from cafe.vehicle import RHO, G

EARTH = 6371000.0
TOL = dict(uav=3.0, usv=10.0, uuv=10.0)            # default arrive / hold tolerance (m)
PHYS_DT = dict(uav=0.01, usv=0.02, uuv=0.02)
TICK = 0.02
# Monte Carlo spreads (1 sigma). Weather-model errors are generic reanalysis-scale assumptions, stated in the UI.
# When the weather files carry no ocean currents, a random current with current_unknown sigma per component is
# drawn instead of assuming slack water (tropical surface currents are routinely several tenths of a m/s).
SIG = dict(wind=1.5, current=0.10, current_unknown=0.25, t_jitter_h=0.5, thrust=0.07, battery=0.03, drag_cfd=0.10, drag_est=0.30)
SEA_LIMIT_HS = dict(D=0.3, C=2.0, B=4.0, A=99.0)   # EU RCD 2013/53/EU design categories


class Frame:
    """Local tangent plane at the mission origin (equirectangular; fine for < ~200 km)."""

    def __init__(self, lat0, lon0):
        self.lat0, self.lon0, self.k = lat0, lon0, np.cos(np.radians(lat0))

    def to_ne(self, lat, lon):
        return np.radians(lat - self.lat0) * EARTH, np.radians(((lon - self.lon0 + 180) % 360) - 180) * EARTH * self.k

    def to_ll(self, n, e):
        return self.lat0 + np.degrees(n / EARTH), self.lon0 + np.degrees(e / (EARTH * self.k))


def z_to_down(kind, z):
    return {"uav": -float(z), "uuv": float(z), "usv": 0.0}[kind]


class Drone:
    def __init__(self, spec, frame, B, rng):
        self.id, self.veh = spec["id"], spec["vehicle"]
        v = self.veh
        k = v.kind
        n, e = frame.to_ne(spec["start"][0], spec["start"][1])
        self.start = np.array([n, e, z_to_down(k, spec["start"][2] if len(spec["start"]) > 2 else 0)])
        # spread of the coefficient that dominates: free-surface resistance for boats, the CFD drag table
        # otherwise; model-form error (10 % CFD, 30 % estimate) combined with the measured mesh uncertainty
        if v.resistance is not None:
            drag_sig = float(np.hypot(SIG["drag_cfd"], v.limits.get("resistance_gci", 0.0)))
        elif v.sources.get("drag") == "cfd":
            drag_sig = float(np.hypot(SIG["drag_cfd"], max(c[3] for c in v.drag.values())))
        else:
            drag_sig = SIG["drag_est"]
        # mean-preserving lognormal: E[scale] = 1
        self.scale = dict(drag=np.r_[1.0, np.exp(rng.normal(-drag_sig ** 2 / 2, drag_sig, B - 1))],
                          thrust=np.r_[1.0, np.clip(rng.normal(1, SIG["thrust"], B - 1), 0.7, 1.2)],
                          battery=np.r_[1.0, np.clip(rng.normal(1, SIG["battery"], B - 1), 0.85, 1.1)])
        self.dyn = dyn.Dynamics(v, B, self.scale)
        self.ap = ctrl.Autopilot(v, self.dyn, B)
        if spec.get("speed"):
            self.ap.v_cruise[:] = float(spec["speed"])
        self.st = dyn.State(B, len(v.actuators), p=self.start)
        if k == "usv":
            self.st.p[:, 2] = _float_depth(v)
        self.glider = self.ap.fam == "glider"
        self.legs = [dict(l) for l in spec["legs"]]
        if self.glider:
            # saw-tooth band: from top_m to the deepest depth any leg asks for (or dive_m)
            deep = [l["to"][2] for l in self.legs if l["type"] == "goto" and l["to"] != "start" and len(l["to"]) > 2]
            top = float(spec.get("top_m", 5.0))
            bottom = float(spec.get("dive_m", max(deep) if deep else 100.0))
            # a surface waypoint (z = 0) or a band thinner than 20 m would stall the saw-tooth: never allow it
            self.ap.set_band(top, max(bottom, top + 20.0))
        for l in self.legs:
            if l["type"] == "goto":
                l["_p"] = self.start.copy() if l["to"] == "start" else np.array(
                    [*frame.to_ne(l["to"][0], l["to"][1]), z_to_down(k, l["to"][2] if len(l["to"]) > 2 else 0)])
                if k == "usv":
                    l["_p"][2] = self.st.p[0, 2]
            if l["type"] == "external":
                l["_p"] = self.start.copy()
            l.setdefault("_tol_default", "tol_m" not in l)
            l.setdefault("tol_m", TOL[k] if not self.glider else 50.0)   # a glider arrives within a yo cycle
        self.leg = np.zeros(B, int)
        self.leg_t0 = np.zeros(B)
        self.hold_at = self.st.p.copy()
        # gliders are slow: step every 3 outer ticks (0.06 s) -- an exact multiple of TICK, or the glider's
        # clock would drift from everyone else's and corrupt every distance between drones
        self.tick_every = 3 if self.glider else 1
        self.dt = TICK * self.tick_every if self.glider else PHYS_DT[k]
        self.n_sub = 1 if self.glider else max(1, int(round(TICK / self.dt)))
        self.err = [[] for _ in self.legs]       # per leg: (B,) errors at 1 Hz during hold/follow
        self.arrive = np.full((len(self.legs), B), np.nan)
        self.fail = np.full(B, "", dtype=object)
        self.max_depth = np.zeros(B); self.max_roll = np.zeros(B); self.sat = np.zeros(B)
        self.track = []
        fmin = ctrl.fin_min_speed(v)
        self.loiter_r = 0.0
        if k == "uuv" and ctrl.family(v) == "steered":
            self.v_loiter = max(self.ap.v_floor, 0.5 * self.ap.v_cruise[0])
            self.loiter_r = max(3 * v.length, self.v_loiter ** 2 / 0.15)   # ~0.15 m/s2 lateral accel at speed
            for l in self.legs:      # it can't stop on a point, so "arrived" = circling it within its turn radius
                if l["type"] in ("goto", "hold") and l.pop("_tol_default", False):
                    l["tol_m"] = max(l["tol_m"], 1.2 * self.loiter_r)
        for l in self.legs:
            l.pop("_tol_default", None)

    @property
    def done(self):
        return self.leg >= len(self.legs)


def _float_depth(v):
    """Initial CoG depth for a boat: hull keel at its hydrostatic draft (NED z of CoG)."""
    c, n, a = v.panels
    # bisection on the vertical position until panel buoyancy == weight (calm water)
    lo, hi = c[:, 2].min() - 1, c[:, 2].max() + 1
    calm = envm.Waves(0.0, 1.0, 0.0)
    d = dyn.Dynamics(v, 1)
    for _ in range(50):
        z = (lo + hi) / 2
        st = dyn.State(1, len(v.actuators), p=[0, 0, z])
        F, _, _ = d.panel_forces(st, np.eye(3)[None], calm, 0.0)
        lo, hi = (z, hi) if -F[0, 2] < v.mass * G else (lo, z)
    return (lo + hi) / 2


class World:
    """Every drone on one clock in one environment. run() drives it to the end for a batch prediction;
    a live session (cafe.live) steps it a few seconds at a time while outside code sets the targets."""

    def __init__(self, mission, B=None):
        self.t_wall = time.time()
        self.mission = mission
        B = self.B = B or mission.get("samples", 24)
        rng = self.rng = np.random.default_rng(mission.get("seed", 0))
        t0 = dt.datetime.fromisoformat(mission["t0"])
        specs = mission["drones"]
        self.frame = frame = Frame(specs[0]["start"][0], specs[0]["start"][1])
        self.drones = drones = [Drone(s, frame, B, rng) for s in specs]
        self.by_id = {d.id: d for d in drones}
        self.max_s = mission.get("max_hours", 6) * 3600
        # environment window covering every point mentioned, plus margin for jitter and drift
        pts = [s["start"] for s in specs] + [l["to"] for s in specs for l in s["legs"] if l["type"] == "goto" and l["to"] != "start"]
        pad = float(mission.get("area_pad_deg", 0.3))
        box = ((min(p[0] for p in pts) - pad, max(p[0] for p in pts) + pad), (min(p[1] for p in pts) - pad, max(p[1] for p in pts) + pad))
        try:      # one hour of lead so start-time jitter can look earlier
            self.E = envm.Env(t0 - dt.timedelta(hours=1), self.max_s / 3600 + 2, *box)
        except ValueError:
            self.E = envm.Env(t0, self.max_s / 3600 + 1, *box)
        lead = (t0 - self.E.t0).total_seconds()        # Env starts on the hour; keep the mission's minutes
        E = self.E
        self.jitter = np.clip(np.r_[0, rng.normal(0, SIG["t_jitter_h"] * 3600, B - 1)] + lead, 0, None)
        self.bias_w = np.r_[[[0, 0]], rng.normal(0, SIG["wind"], (B - 1, 2))]
        self.bias_c = np.r_[[[0, 0]], rng.normal(0, SIG["current"] if E.has_current else SIG["current_unknown"], (B - 1, 2))]
        self.gusts = {s["id"]: envm.Gusts(int(rng.integers(1 << 30)), B) for s in specs}   # one process per drone
        # sea state per drone per sample, from the local wind (or wave model) at launch
        for d in drones:
            e = self.sample_env(d, 0.0)
            e2 = dict(e, u10=np.hypot(*(e["wind10_ne"] + self.bias_w).T))
            hs, tp = envm.sea_state(e2)
            heading = (e["wave_to"] if e.get("wave_to") is not None else
                       np.arctan2(e["wind10_ne"][:, 1] + self.bias_w[:, 1], e["wind10_ne"][:, 0] + self.bias_w[:, 0]))
            d.waves = envm.Waves.stack([envm.Waves(hs[b], tp[b], heading[b], n=24, seed=int(rng.integers(1 << 30))) for b in range(B)])
            d.hs = hs
            if np.any(e["land"]):
                raise ValueError(f"{d.id} starts on land")
            if d.veh.kind != "uav":
                for l in d.legs:
                    if l["type"] == "goto" and l["to"] != "start" and E.surface(*l["to"][:2], 0.0)["land"].any():
                        raise ValueError(f"{d.id}: goto point {l['to'][0]:.4f}, {l['to'][1]:.4f} is on land")
            d.env = e
            d.env_t = 0.0
            d.deep_limit = 0.5 * G * np.max(tp) ** 2 / (2 * np.pi) + d.veh.length   # half the longest wavelength
        self.links = [Link(l, self.by_id, B) for l in mission.get("links", [])]
        self.t, self.next_rec = 0.0, 0.0

    def sample_env(self, d, t):
        lat, lon = self.frame.to_ll(d.st.p[:, 0], d.st.p[:, 1])
        z_up = -d.st.p[:, 2]
        e = self.E.at(lat, lon, np.clip(t + self.jitter, 0, None), z_up)
        e["wind_ne"] = e["wind_ne"] + self.bias_w * (e["wind_ne"].shape[0] > 0)
        e["current_ne"] = e["current_ne"] + self.bias_c * np.exp(-np.maximum(-z_up, 0) / envm.CURRENT_EFOLD_M)[:, None]
        return e

    @property
    def finished(self):
        return self.t >= self.max_s or all(d.done.all() or not d.st.alive.any() for d in self.drones)

    def tick(self):
        B, t = self.B, self.t
        for d in self.drones:
            if d.tick_every > 1 and int(round(t / TICK)) % d.tick_every:
                continue
            if t - d.env_t >= 1.0:
                d.env, d.env_t = self.sample_env(d, t), t
            e = d.env
            k = d.veh.kind
            for _ in range(d.n_sub):
                tt = d.st.t
                flow = np.zeros((B, 3)); acc = None
                if k == "uav":
                    w = np.column_stack([e["wind_ne"], np.zeros(B)])
                    sp = np.linalg.norm(w, axis=1)
                    # W20 (20 ft) from U10 by the same log profile (~0.95 U10 over the sea)
                    g = self.gusts[d.id].step(d.dt, -d.st.p[:, 2], np.hypot(*e["wind10_ne"].T) * 0.95, sp)
                    along = w / np.maximum(sp, 1e-6)[:, None]
                    cross = np.column_stack([-along[:, 1], along[:, 0], np.zeros(B)])
                    flow = w + g[:, :1] * along + g[:, 1:2] * cross + np.column_stack([np.zeros((B, 2)), -g[:, 2]])
                else:
                    flow[:, :2] = e["current_ne"]
                    orb, oacc = d.waves.orbital(d.st.p[:, None, 0], d.st.p[:, None, 1], -d.st.p[:, None, 2], tt)
                    flow += orb[:, 0] * [1, 1, -1]          # (N, E, Up) -> NED
                    acc = oacc[:, 0] * [1, 1, -1]
                tgt, v_cap, yaw = _targets(d, self.by_id, B)
                v_des, dist = d.ap.velocity_cmd(d.st.p, tgt, v_cap)
                cmd = d.ap(d.st, v_des, flow, d.dt)
                deep = k == "uuv" and d.st.p[:, 2].min() > d.deep_limit
                envd = dict(flow_ned=flow, wind_ned=np.column_stack([e["wind_ne"], np.zeros(B)]), rho_air=e["rho_air"])
                if acc is not None and not deep:
                    envd["flow_acc_ned"] = acc
                parked = d.done
                if parked.any():
                    keep = (d.st.p.copy(), d.st.v.copy(), d.st.w.copy(), d.st.q.copy(), d.st.energy_wh.copy())
                d.dyn.step(d.st, cmd, envd, d.dt, None if deep else d.waves)
                if parked.any():
                    # finished drones are recovered/landed: frozen where they finished, no more battery use
                    for arr, old in zip((d.st.p, d.st.v, d.st.w, d.st.q, d.st.energy_wh), keep):
                        arr[parked] = old[parked]
                d.sat += (np.abs(cmd).max(1) > 0.98) * d.dt
                _advance_legs(d, dist, B, self.by_id)
            _limits(d)
        self.t = t = t + TICK
        if t >= self.next_rec:
            for d in self.drones:
                lat, lon = self.frame.to_ll(d.st.p[:, 0], d.st.p[:, 1])
                eul = np.degrees(dyn.quat_to_euler(d.st.q))
                d.track.append(dict(t=round(t, 1), lat=lat[:8].round(6).tolist(), lon=lon[:8].round(6).tolist(),
                                    z=(-d.st.p[:8, 2]).round(2).tolist(), roll=eul[:8, 0].round(1).tolist(),
                                    pitch=eul[:8, 1].round(1).tolist(), yaw=eul[:8, 2].round(1).tolist(),
                                    wh=d.st.energy_wh[:8].round(2).tolist(), leg=d.leg[:8].tolist(),
                                    wind=np.round(d.env["wind_ne"][0], 2).tolist(),
                                    current=np.round(d.env["current_ne"][0], 3).tolist()))
            for lk in self.links:
                lk.record(t)
            self.next_rec += 1.0

    def result(self):
        out = dict(t_sim=self.t, wall_s=time.time() - self.t_wall, samples=self.B, env=self.E.sources, env_frozen=self.E.frozen,
                   drones={d.id: _summary(d, self.mission, self.t) for d in self.drones})
        out["links"] = [lk.summary() for lk in self.links]
        out["fleet"] = _fleet(out, self.drones, self.links, self.mission)
        return out


def run(mission, B=None, progress=None):
    w = World(mission, B)
    while not w.finished:
        w.tick()
        if progress and abs(w.t - round(w.t)) < TICK / 2 and int(round(w.t)) % 60 == 0:
            progress(w.t / w.max_s)
    return w.result()


class Link:
    """A requirement that two drones stay within max_m of each other. Distance is 3-D (slant range) by default,
    which is what acoustic modems and radios care about; "horizontal" only if asked. Evaluated from from_min to
    until_min (default: the whole mission), but not while either drone is done or flying its planned return
    home. Time before the pair first meets counts as out of range, so arriving late can't score 100 %."""

    def __init__(self, spec, by_id, B):
        self.a, self.b = by_id[spec["a"]], by_id[spec["b"]]
        self.spec = dict(spec)
        self.max_m = float(spec["max_m"])
        self.need = float(spec.get("need", 0.95))
        self.horizontal = spec.get("mode", "3d") == "horizontal"
        self.from_s = 60 * float(spec.get("from_min", 0))
        self.until_s = 60 * float(spec["until_min"]) if spec.get("until_min") not in (None, "") else np.inf
        self.B = B
        self.t, self.d = [], []
        self.acquired = np.full(B, np.nan)
        self.n_in = np.zeros(B); self.n_eval = np.zeros(B)
        self.outage = np.zeros(B); self.longest = np.zeros(B); self.max_sep = np.zeros(B)

    def record(self, t):
        e = self.a.st.p - self.b.st.p
        if self.horizontal:
            e = e[:, :2]
        d = np.linalg.norm(e, axis=1)
        ok = d <= self.max_m
        # only while both drones are on task: done, or flying the planned return home, doesn't count
        active = ~(self.a.done | self.b.done | _returning(self.a) | _returning(self.b)) & (self.from_s <= t <= self.until_s)
        newly = np.isnan(self.acquired) & ok & active
        self.acquired[newly] = t
        ev = active
        self.n_eval += ev
        self.n_in += ev & ok
        self.outage = np.where(ev & ~ok, self.outage + 1, np.where(ev, 0, self.outage))
        self.longest = np.maximum(self.longest, self.outage)
        self.max_sep = np.where(ev, np.maximum(self.max_sep, d), self.max_sep)
        self.t.append(t); self.d.append(d)

    def success(self):
        frac = np.where(self.n_eval > 0, self.n_in / np.maximum(self.n_eval, 1), 0.0)
        return ~np.isnan(self.acquired) & (frac >= self.need), frac



    def summary(self):
        ok, frac = self.success()
        D = np.array(self.d) if self.d else np.zeros((0, self.B))
        step = max(1, len(self.t) // 600)               # the timeline the UI draws: <= ~600 points
        mc = slice(1, None) if self.B > 1 else slice(None)
        p, lo, hi = _rate(ok[mc])
        return dict(a=self.a.id, b=self.b.id, max_m=self.max_m, need=self.need,
                    mode="horizontal" if self.horizontal else "3d", from_min=self.from_s / 60,
                    until_min=None if np.isinf(self.until_s) else self.until_s / 60,
                    verdict=_verdict(p, lo), p_success=p, p_interval=[lo, hi], nominal_ok=bool(ok[0]),
                    in_range_p50=float(np.median(frac[mc])), in_range_p10=float(np.percentile(frac[mc], 10)),
                    longest_outage_s_p50=float(np.median(self.longest[mc])), longest_outage_s_p90=float(np.percentile(self.longest[mc], 90)),
                    max_sep_m_p50=float(np.median(self.max_sep[mc])), never_acquired=float(np.isnan(self.acquired[mc]).mean()),
                    acquired_min_p50=float(np.nanmedian(self.acquired[mc]) / 60) if (~np.isnan(self.acquired[mc])).any() else None,
                    timeline=dict(t=[round(x) for x in self.t[::step]], nominal=D[::step, 0].round(1).tolist(),
                                  p10=np.percentile(D[::step, mc], 10, axis=1).round(1).tolist() if len(D) else [],
                                  p90=np.percentile(D[::step, mc], 90, axis=1).round(1).tolist() if len(D) else []))


def _returning(d):
    """Per sample: is this drone flying its final 'come back' leg?"""
    out = np.zeros(d.leg.shape, bool)
    for i, l in enumerate(d.legs):
        if l["type"] == "goto" and l.get("to") == "start" and i == len(d.legs) - 1:
            out |= d.leg == i
    return out


def _rate(ok):
    """Success rate with a 90 % Wilson interval."""
    n, k = len(ok), int(np.sum(ok))
    p = k / max(n, 1)
    z = 1.645
    c = (p + z * z / (2 * n)) / (1 + z * z / n)
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return p, max(0.0, c - h), min(1.0, c + h)


def _runs_needed(p, most=64):
    """Fewest runs at pass rate p whose Wilson lower bound reaches 0.75 (what GO needs); None if not within `most`."""
    for n in range(2, most + 1):
        if _rate(np.arange(n) < round(p * n))[1] >= 0.75:
            return n
    return None


def _verdict(p, lo):
    return "GO" if (p >= 0.9 and lo >= 0.75) else "MARGINAL" if p >= 0.6 else "NO-GO"


def _fleet(out, drones, links, mission):
    """The question that matters: in what share of runs does EVERY drone do its job AND every link hold?"""
    B = drones[0].st.p.shape[0]
    ok = np.ones(B, bool)
    why = np.full(B, "", dtype=object)
    for d in drones:
        s = d._ok
        why = np.where(ok & ~s, f"{d.id}: " + d._why, why)
        ok &= s
    for lk in links:
        s, frac = lk.success()
        msg = np.where(np.isnan(lk.acquired), f"{lk.a.id}-{lk.b.id} never got within {lk.max_m:.0f} m",
                       f"{lk.a.id}-{lk.b.id} in range only part of the time")
        why = np.where(ok & ~s, msg, why)
        ok &= s
    mc = slice(1, None) if B > 1 else slice(None)
    p, lo, hi = _rate(ok[mc])
    r, c = np.unique(why[mc][~ok[mc]], return_counts=True)
    order = np.argsort(-c)
    return dict(verdict=_verdict(p, lo), p_success=p, p_interval=[lo, hi], runs=len(ok[mc]),
                reasons=[dict(reason=str(r[i]), share=float(c[i] / len(ok[mc]))) for i in order])


def _targets(d, by_id, B):
    """Where each sample of this drone is trying to be right now, and how fast it may go."""
    tgt = d.hold_at.copy()
    v_cap = d.ap.v_cruise * 0.5
    for i, l in enumerate(d.legs):
        on = d.leg == i
        if not on.any():
            continue
        if l["type"] == "goto":
            tgt[on] = l["_p"]; v_cap[on] = d.ap.v_cruise[on]
        elif l["type"] == "hold":
            v_cap[on] = d.ap.v_cruise[on]
        elif l["type"] == "external":
            tgt[on] = l["_p"]; v_cap[on] = l.get("_speed") or d.ap.v_cruise[on]
        elif l["type"] == "follow":
            lead = by_id[l["target"]]
            off = np.array(l.get("offset", [0, 0, 0]), float)
            tgt[on] = lead.st.p[on] + [off[0], off[1], -off[2]]
            if d.veh.kind == "uav":
                tgt[on, 2] = np.minimum(tgt[on, 2], -2.0)
            v_cap[on] = d.ap.v_max
    if d.loiter_r:
        # a finned sub can't hover: below its fin control speed it floats up. Loiter on a circle instead.
        # also when a goto point is (nearly) straight above or below: spiral to its depth instead of stalling
        holding = np.array([d.leg[b] >= len(d.legs) or d.legs[d.leg[b]]["type"] == "hold" or
                            (d.legs[d.leg[b]]["type"] == "goto" and abs(tgt[b, 2] - d.st.p[b, 2]) > d.legs[d.leg[b]]["tol_m"] / 2)
                            for b in range(B)])
        if holding.any():
            e = tgt[holding] - d.st.p[holding]
            r = np.linalg.norm(e[:, :2], axis=1)
            if (r < 3 * d.loiter_r).any():
                tang = np.column_stack([-e[:, 1], e[:, 0]]) / np.maximum(r, 1e-6)[:, None]
                aim = d.st.p[holding, :2] + tang * d.loiter_r + e[:, :2] * (1 - d.loiter_r / np.maximum(r, 1e-6))[:, None]
                near = r < 3 * d.loiter_r
                idx = np.where(holding)[0][near]
                tgt[idx, :2] = aim[near]
                v_cap[idx] = d.v_loiter
    return tgt, v_cap, None


def _advance_legs(d, dist, B, by_id):
    t = d.st.t
    live = d.st.alive
    leg0 = d.leg.copy()          # a leg finishing this step must not let the next one finish on stale distance
    for i, l in enumerate(d.legs):
        on = (leg0 == i) & live
        if not on.any():
            continue
        if l["type"] == "external":
            continue
        fin = on & (dist < l["tol_m"]) if l["type"] == "goto" else on & (t - d.leg_t0 >= l["minutes"] * 60)
        if fin.any():
            d.arrive[i, fin] = t
            if l["type"] == "goto":
                d.hold_at[fin] = d.st.p[fin]
            d.leg[fin] += 1; d.leg_t0[fin] = t
    if abs(t - round(t)) < d.dt / 2:      # hold/follow errors at ~1 Hz, after 30 s settle
        for i, l in enumerate(d.legs):
            if l["type"] not in ("hold", "follow"):
                continue
            # the TRUE error to where the drone should be, not to the guidance aim point (a loitering sub's
            # aim point moves around the circle)
            if l["type"] == "hold":
                goal = d.hold_at
            else:
                off = np.array(l.get("offset", [0, 0, 0]), float)
                goal = by_id[l["target"]].st.p + [off[0], off[1], -off[2]]
            e = d.st.p - goal
            if d.veh.kind == "usv" or d.glider:     # a glider's own saw-tooth isn't a position error
                e[:, 2] = 0
            d.err[i].append(np.where((d.leg == i) & (t - d.leg_t0 > 30), np.linalg.norm(e, axis=1), np.nan))


def _limits(d):
    st, v = d.st, d.veh
    if d.done.all():
        return
    eul = dyn.quat_to_euler(st.q)
    d.max_roll = np.maximum(d.max_roll, np.abs(np.degrees(eul[:, 0])))
    d.max_depth = np.maximum(d.max_depth, st.p[:, 2])
    first = lambda mask, why: d.fail.__setitem__(mask & (d.fail == ""), why)
    if v.kind == "uav":
        first(st.p[:, 2] >= 0, "hit the water")
    if v.kind == "usv" and (v.limits.get("gm_m") or 1) <= 0:
        first(np.ones_like(d.fail, bool), "statically unstable (GM <= 0: centre of gravity too high)")
    if v.kind != "uav" and isinstance(d.env, dict) and d.env.get("land") is not None:
        aground = np.asarray(d.env["land"], bool)
        first(aground, "ran aground (reached land)")
        st.alive &= ~aground
    if v.kind == "usv":
        capsized = d.max_roll > 70
        first(capsized, "capsized")
        st.alive &= ~capsized
    floor = d.env.get("floor") if isinstance(d.env, dict) else None
    if v.kind == "uuv" and floor is not None:
        first(st.p[:, 2] > floor - 2.0, f"hit the seafloor (about {np.nanmin(floor):.0f} m deep here)")
    crush, rated = v.limits.get("crush_depth_m"), v.limits.get("rated_depth_m")
    if v.kind == "uuv" and crush:
        first(st.p[:, 2] > crush, f"went below predicted collapse depth ({crush:.0f} m)")
    if v.kind == "uuv" and rated:
        first(st.p[:, 2] > rated, f"went below rated depth ({rated:.0f} m = collapse / 1.5)")
    first(st.energy_wh >= v.battery_wh * d.dyn.battery_scale, "battery empty")


def _summary(d, mission, t_end):
    v, B = d.veh, d.st.p.shape[0]
    reserve = mission.get("reserve", 0.15)
    cap = v.battery_wh * d.dyn.battery_scale
    left = 1 - d.st.energy_wh / cap
    ok = (d.fail == "") & d.done
    why = np.where(d.fail != "", d.fail, "")
    why = np.where((why == "") & ~d.done, "ran out of time", why)
    low = (why == "") & (left < reserve)
    why = np.where(low, f"under {reserve:.0%} battery reserve", why)
    legs = []
    for i, l in enumerate(d.legs):
        info = dict(type=l["type"], tol_m=l["tol_m"])
        reached = ~np.isnan(d.arrive[i])
        info["completed"] = float(reached.mean())
        if l["type"] == "goto":
            info["eta_min_p50"] = float(np.nanmedian(d.arrive[i]) / 60) if reached.any() else None
        if l["type"] in ("hold", "follow") and d.err[i]:
            e = np.array(d.err[i])
            per = np.array([np.nanpercentile(e[:, b], 95) if np.isfinite(e[:, b]).any() else np.nan for b in range(B)])
            info["err95_m_p50"] = float(np.nanmedian(per)) if np.isfinite(per).any() else None
            info["err95_m_nominal"] = float(per[0]) if np.isfinite(per[0]) else None
            bad = np.nan_to_num(per, nan=np.inf) > l["tol_m"]
            why = np.where((why == "") & bad, f"{l['type']} error over {l['tol_m']:.0f} m", why)
        legs.append(info)
    if v.kind == "usv":
        cat = v.limits.get("design_category", "C")
        rough = d.hs > SEA_LIMIT_HS[cat]
        why = np.where((why == "") & rough, f"seas over design category {cat} limit ({SEA_LIMIT_HS[cat]} m Hs)", why)
    success = why == ""
    d._ok = success
    d._why = np.where(why == "", "", why)
    # sample 0 is the unperturbed nominal run: shown, not counted. The rest estimate P(success) with a 90 %
    # Wilson interval, and GO needs the interval's lower end at 0.75 or better, not just a lucky point estimate.
    mc = success[1:] if B > 1 else success
    n, k = len(mc), int(mc.sum())
    p, lo_ci, hi_ci = _rate(mc)
    verdict = _verdict(p, lo_ci)
    reasons, counts = np.unique(why[1:][~mc] if B > 1 else why[~success], return_counts=True)
    order = np.argsort(-counts)
    if verdict == "MARGINAL" and p >= 0.9:
        # every (or nearly every) run passed, but too few runs to be 90 % sure; say so instead of a bare flag
        need = _runs_needed(p)
        reasons = np.append(reasons, f"only {n} runs: {k} passed, too few to be sure" +
                            (f"; at this pass rate it takes about {need} runs" if need else ""))
        counts = np.append(counts, 0); order = np.r_[len(counts) - 1, order]
    return dict(
        verdict=verdict, p_success=p, p_interval=[lo_ci, hi_ci], runs=n, nominal_ok=bool(success[0]),
        nominal_reason=str(why[0]),
        reasons=[dict(reason=str(reasons[i]), share=float(counts[i] / n)) for i in order],
        legs=legs, battery_left_p50=float(np.median(left)), battery_left_p10=float(np.percentile(left, 10)),
        energy_wh_p50=float(np.median(d.st.energy_wh)), max_depth_m=float(np.max(d.max_depth)) if v.kind == "uuv" else None,
        max_roll_deg_p50=float(np.median(d.max_roll)), hs_p50=float(np.median(d.hs)),
        cruise_mps=float(d.ap.v_cruise[0]), max_mps=float(d.ap.v_max),
        saturated_frac=float(np.median(d.sat) / max(t_end, 1)),
        sources=v.sources, track=d.track)


if __name__ == "__main__":
    # python -m cafe.mission /work/missions/<id>   (mission.json written by the app)
    import json, pathlib, sys, traceback
    from cafe import hangar
    d = pathlib.Path(sys.argv[1])
    m = json.loads((d / "mission.json").read_text())
    status = lambda **kw: (d / "status.json").write_text(json.dumps(dict(updated=time.time(), **kw)))
    try:
        designs = d.parent.parent / "designs"
        for x in m["drones"]:
            x["vehicle"] = hangar.load_vehicle(designs / x["design"])
        status(state="running", progress=0.0, step="simulating")
        r = run(m, progress=lambda f: status(state="running", progress=round(f, 3), step="simulating"))
        for x in m["drones"]:
            x.pop("vehicle")
        (d / "result.json").write_text(json.dumps(r, default=hangar._j))
        status(state="done", progress=1.0)
    except Exception as e:
        traceback.print_exc()
        status(state="failed", error=f"{type(e).__name__}: {e}")
