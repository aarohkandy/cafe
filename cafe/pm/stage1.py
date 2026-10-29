"""Stage 1: the Monte-Carlo ensemble over every vehicle and link of a mission, vectorized over members.

Members run in batches. Each batch is its own Latin hypercube (McKay et al. 1979) over the perturbation priors
(config/perturbations.yaml), antithetic on the two dominant forcing errors, and every vehicle in member m sees the
same perturbed environment (common random numbers: `env.perturb.PerturbedEnv`, seeds keyed by member only). After
each batch the stopping rule (`stats.sequential.ensemble_stop`) is asked about every vehicle and link; the ensemble
stops when all are decided or the planner's n_max is reached. Below 73 members (budget quick) nothing can certify
P(fail) < 5 % and the verdict says so.

    run(mission, env, plan, ledger) -> dict(vehicles={id: result}, links={id: result}, tracks, X, U, members)
"""
import datetime as dt, time

import numpy as np

from .config import load_platform, utc
from .env import conventions as cv, subgrid
from .env.perturb import PerturbedEnv
from .physics import comms, glider, uas, usv
from .stats import intervals, sampling, sensitivity, sequential

FORCING = ["wind_speed_bias", "wind_direction_bias", "current_speed_scale", "current_direction_bias", "hs_scale", "tp_bias"]
ANTITHETIC = ("wind_speed_bias", "current_speed_scale")
REC_S = 600.0                         # positions kept every 10 min for links, reports and windows
DT_VEHICLE = 60.0                     # glider and USV step [s]; the ocean SDE's Euler-Maruyama step is the same


def platform_kind(name):
    return load_platform(name).get("kind") or name


def _classes(mission):
    out = {}
    for v in mission["vehicles"]:
        k = str(platform_kind(v["platform"])).lower()
        out[v["id"]] = "uas" if "base" in v else ("usv" if "sail" in k or "usv" in k else "glider")
    return out


def priors_for(mission, fitted=None):
    """Stage-1 priors: perturbations.yaml, with the entries the TAO comparison fitted (pipeline ingest) replacing theirs."""
    pri = sampling.load_perturbations()
    pri.update(fitted or {})
    names = list(FORCING)
    cls = set(_classes(mission).values())
    if "glider" in cls:
        names.append("glider_speed_scale")
    if "usv" in cls:
        names.append("usv_vpp_bias")
    if "uas" in cls:
        names.append("bulk_stress_scale")          # scales the surface stress u*^2 behind the Mann turbulence (see _uas_forcing)
    names.append("battery_capacity_scale")
    return pri, sampling.to_marginals(pri, names)


def _run_glider(v, P, env, M, X, t0, T, drag=1.0, windage=None):
    task = v["task"]
    mis = dict(mode=task["mode"], dive_depth_m=task.get("dive_depth_m", P.get("mission_defaults", {}).get("dive_depth_m", 500.0)))
    if task["mode"] == "station":
        mis.update(station=(task["lon"], task["lat"]), station_tol_m=1e3 * task.get("radius_km", 5.0), lost_hours=task.get("lost_after_h", 6.0))
    if task.get("waypoints"):
        mis["waypoints"] = [tuple(p) for p in task["waypoints"]]
    d = v["deploy"]
    sim = glider.GliderSim(P, M, env, d["lon"], d["lat"], t0, mis,
                           perturb=dict(speed_scale=X["glider_speed_scale"] * drag ** -0.5, battery_scale=X["battery_capacity_scale"],
                                        density_bias=np.zeros(M), **({} if windage is None else dict(windage=windage))))
    h = sim.run(T - t0, dt=DT_VEHICLE)
    keep = slice(None, None, int(REC_S // DT_VEHICLE))
    return dict(t=h["t"][keep], lon=h["lon"][keep], lat=h["lat"][keep], depth=h["depth"][keep], surfaced=(h["phase"] == 3)[keep],
                fail=h["fail"], first=h["first"], sim=sim, antenna_m=P["antenna_height_m"])


def _run_usv(v, P, env, M, X, t0, T, drag=1.0):
    task = dict(v["task"])
    task["waypoints"] = [tuple(p) for p in task.get("waypoints", [])]
    d = v["deploy"]
    sim = usv.USVSim(P, M, env, (d["lon"], d["lat"]), t0, task, perturb=dict(vpp_bias=(1 + X["usv_vpp_bias"]) * drag ** -0.5 - 1))
    h = sim.run(T - t0, dt=DT_VEHICLE, record_s=REC_S)
    return dict(t=h["t"], lon=h["lon"], lat=h["lat"], depth=np.zeros_like(h["lon"]), surfaced=np.ones_like(h["lon"], bool),
                fail=sim.fail, first=sim.first, sim=sim, antenna_m=P["rf_antenna_height_m"])


def launch_times(sorties, lon, t0, T, duration_s):
    """Sortie launches [s UTC] at `local_solar_time` (UTC + lon/15 h) every `every_days`, each one ending inside [t0, T]."""
    hh, mm = (int(x) for x in sorties["local_solar_time"].split(":"))
    off = (hh + mm / 60 - lon / 15.0) * 3600.0
    day0 = np.floor(t0 / 86400.0) * 86400.0 - 86400.0
    ts = day0 + off + 86400.0 * float(sorties.get("every_days", 1)) * np.arange(int((T - day0) / 86400.0) + 3)
    return ts[(ts >= t0) & (ts + duration_s <= T)]


def _fewest_boxes(args, M):
    """Mann series from the fewest boxes that hold M non-overlapping segments (a box costs ~2 s; members sharing one are
    separated by >= U x duration along it, uncorrelated per the subgrid receipts). The capacity check runs before any box
    is built, so trying 1, 2, 4, ... boxes costs nothing."""
    for nb in range(1, M):
        try:
            return subgrid.turbulence_members(*args, n_boxes=nb).value
        except ValueError:
            pass
    return subgrid.turbulence_members(*args, n_boxes=M).value


def _uas_forcing(env, mission, origin, ts, P, M, seed, members, stress_scale=None):
    """Per-sortie Mann turbulence (M, n, 3) and one gust-front event set for the window, from the surface layer at the ship.
    None where the mission switches them off or the environment has no surface layer (analytic test envs).
    stress_scale (M,): the member's bulk-stress multiplier. sigma_u = 2.5 u* and u*^2 is the stress, so a member's series is
    scaled by sqrt(stress_scale) (the Obukhov length and the mean wind profile are not recomputed: the wind priors perturb those).
    The gust-front rate uses theta_e from the ship's T2, Q2 and PSFC (subgrid.theta_e), so the cold-pool rate factor works."""
    sw, sl = mission.get("environment", {}).get("subgrid", {}), getattr(env, "subgrid", None)
    lon, lat = origin
    so = P["sortie"]
    z = so["deck_height_m"] + float(np.mean(so["levels_m"]))
    amp = 1.0 if stress_scale is None else np.sqrt(np.asarray(stress_scale, float))[:, None, None]
    turbs = [None] * len(ts)
    if sw.get("turbulence") and sl is not None:
        for i, t in enumerate(ts):
            s = sl.surface_layer(env, np.array([lon]), np.array([lat]), np.array([t]))
            w = np.asarray(env.wind(np.full(M, lon), np.full(M, lat), z, t).value, float)          # (M, 2): one point per member
            U = float(np.hypot(w[:, 0], w[:, 1]).mean())                                           # Mann advection speed
            args = (sampling.member_seed(seed, members[0], f"uas/turb/{i}"), M, float(s["ustar"].value[0]), float(s["L"].value[0]), z,
                    max(U, 1.0), so["duration_s"] * so["hard_stop_factor"] + 60.0, uas.DT_ENV)
            g = _fewest_boxes(args, M) * amp
            wdir = cv.to_deg(-np.asarray(env.u10(np.array([lon]), np.array([lat]), np.array([t])), float).reshape(2))   # wind FROM
            turbs[i] = subgrid.gust_enu(g, wdir)
    gust = None
    if sw.get("gust_fronts") and sl is not None and len(ts):
        hours = np.arange(np.floor(ts[0] / 3600) * 3600 - 3600, ts[-1] + 7200, 3600.0)
        lo, la = np.full(hours.size, lon), np.full(hours.size, lat)
        rain = np.asarray(env._w("rain_mm_h", lo, la, hours), float)
        wto = cv.to_deg(np.asarray(env.u10(lo, la, hours), float))
        air = env.air(lo, la, hours)
        te = subgrid.theta_e(air["T2"].value, air["q2"].value, air["psfc"].value)
        ev = subgrid.gust_fronts(sampling.member_seed(seed, members[0], "uas/gust"), rain, hours, M, theta_e_K=te, wind_to_deg=wto)

        def gust(t):
            g = subgrid.gust_perturbation(ev, np.asarray(t, float))[0].value
            return np.concatenate([g, np.zeros(g.shape[:-1] + (1,))], -1)
    return turbs, gust


def _uas_radio(P):
    """The platform's RF radio as a comms.rf_margin radio dict: the first block of quad_uas.yaml `radio` with a transmit power
    (rfd900x), its band centre, power and sensitivity, and antenna gains and losses from platforms/radios.yaml's entry of the same
    name (rfd900x if there is none)."""
    name = next(k for k, v in P["radio"].items() if isinstance(v, dict) and "tx_power_dbm" in v)
    r = P["radio"][name]
    base = comms._yaml("radios.yaml")["radios"]
    return dict(base.get(name, base["rfd900x"]), center_mhz=float(np.mean(r["freq_mhz"])), tx_dbm=r["tx_power_dbm"], rx_sens_dbm=r["rx_sensitivity_dbm"])


def _uas_links(env, mission, origin, ts, P, M):
    """One `link(t, pos_rel (M, 3)) -> lost (M,)` hook per sortie for uas.fly_sortie: the UAS-to-ship RF budget
    (comms.rf_margin: the platform's radio, the mission's ship antenna height, the UAS antenna at deck + altitude + its height above
    the body, each member's Hs at the ship from `env`), lost where the margin is below 0 dB (or beyond the radio horizon). Hs is read
    on a 30 s grid per sortie, once, and interpolated."""
    so, ra = P["sortie"], P["radio"]
    radio = _uas_radio(P)
    hr = float(mission["ship"].get("antenna_height_m", ra["ship_antenna_height_m"]))
    out = []
    for t0 in ts:
        tg = t0 + np.arange(0.0, so["duration_s"] * so["hard_stop_factor"] + 61.0, 30.0)
        full = lambda v, n=tg.size: np.full((M, n), v)
        hs = np.nan_to_num(np.asarray(env.waves(full(origin[0]), full(origin[1]), np.broadcast_to(tg, (M, tg.size)))["Hs"].value, float))

        def link(t, rel, tg=tg, hs=hs):
            j = int(np.clip(np.searchsorted(tg, t) - 1, 0, tg.size - 2))
            w = float(np.clip((t - tg[j]) / (tg[j + 1] - tg[j]), 0.0, 1.0))
            ht = so["deck_height_m"] + rel[:, 2] + ra["uas_antenna_height_above_body_m"]
            return comms.rf_margin(np.hypot(rel[:, 0], rel[:, 1]), ht, hr, (1 - w) * hs[:, j] + w * hs[:, j + 1], radio) < 0.0
        out.append(link)
    return out


def _run_uas(v, P, env, M, X, t0, T, mission, seed, members, drag=1.0):
    """Daily flux-profile sorties from the ship (on station): fly_mission per sortie, then the 10-min grid the links read."""
    ship = mission["ship"]
    origin = (float(ship["lon"]), float(ship["lat"]))
    P = dict(P, sortie=dict(P["sortie"]), launch_rule=dict(P["launch_rule"]))
    so, lr = P["sortie"], v.get("launch_rules", {})
    so["duration_s"] = 60.0 * float(v["sorties"].get("duration_min", so["duration_s"] / 60.0))
    so["levels_m"] = [float(a) for a in v["sorties"].get("altitudes_m", so["levels_m"])]
    rename = {"max_mean_wind_ms": "max_mean_wind_ms", "no_gust_front_within_min": "gust_lookahead_min"}       # mission key -> platform key
    P["launch_rule"].update({rename[a]: float(x) for a, x in lr.items() if a in rename})
    ts = launch_times(v["sorties"], origin[0], t0, T, so["duration_s"] * so["hard_stop_factor"])
    turbs, gust = _uas_forcing(env, mission, origin, ts, P, M, seed, members, X.get("bulk_stress_scale"))
    links = _uas_links(env, mission, origin, ts, P, M)
    still = lambda t: np.zeros(2)
    sc = dict(battery=X["battery_capacity_scale"], drag=drag * np.ones(M))
    sorties = [uas.fly_sortie(env, still, float(t), M=M, origin=origin, plat=P, turb=tb, gust=gust, scale=sc, link=lk)
               for t, tb, lk in zip(ts, turbs, links, strict=True)]
    t = np.arange(t0, T + 1, REC_S)
    east, north, alt = (np.zeros((len(t), M)) for _ in range(3))
    air = np.zeros((len(t), M), bool)
    for s in sorties:
        tr = s["track"]
        if not tr["t"].size:
            continue
        ta = s["t_launch"] + tr["t"]
        for m in range(M):
            up = tr["phase"][m] < uas.DONE
            inside = (t >= ta[0]) & (t <= ta[-1])
            fly = inside & (np.interp(t, ta, up.astype(float)) > 0.5)
            for arr, j in ((east, 0), (north, 1), (alt, 2)):
                arr[fly, m] = np.interp(t[fly], ta, tr["pos_rel"][m, :, j])
            air[fly, m] = True
    lon, lat = uas.lonlat(origin, east, north)
    n_flown = np.sum([~s["scrubbed"] for s in sorties], 0) if sorties else np.zeros(M, int)
    fail = {k: np.any([s["flags"][k] for s in sorties], 0) if sorties else np.zeros(M, bool) for k in uas.FLAGS}
    first = {k: np.fmin.reduce(np.stack([s["t_first"][k] + s["t_launch"] for s in sorties]), 0) if sorties else np.full(M, np.nan) for k in uas.FLAGS}
    fail["no_sortie_flown"] = n_flown == 0                                         # every launch scrubbed: no flux profiles at all
    first["no_sortie_flown"] = np.where(n_flown == 0, T, np.nan)
    return dict(t=t, lon=lon, lat=lat, alt=alt + so["deck_height_m"], depth=np.zeros_like(lon), airborne=air, surfaced=np.ones_like(air),
                fail=fail, first=first, antenna_m=P["radio"]["uas_antenna_height_above_body_m"],
                scrubbed=np.sum([s["scrubbed"] for s in sorties], 0) if sorties else np.zeros(M, int),
                sorties=[dict(t_launch=s["t_launch"], scrubbed=s["scrubbed"], wind_ms=s["launch"]["wind_ms"], energy_wh=s["energy_wh"],
                              soc_end=s["soc_end"], max_tilt_deg=s["max_tilt_deg"]) for s in sorties])


def refit_drag(scales, vid, seed, members):
    """Per-member drag multiplier from the stage-3 refit (lognormal around its mean with its sigma), 1 when not refit.
    Speed follows drag^-1/2 at fixed propulsive/buoyancy force (drag ~ v^2) for the glider and USV; the UAS takes it directly."""
    r = (scales or {}).get(vid, {}).get("drag")
    if not r:
        return 1.0
    z = np.array([sampling.member_rng(seed, m, f"refit/{vid}").standard_normal() for m in members])
    s = np.sqrt(np.log1p((r["sigma"] / r["mean"]) ** 2))                    # lognormal with the refit's mean and sigma
    return r["mean"] * np.exp(s * z - 0.5 * s ** 2)


def run_batch(mission, env, members, seed, pri, marg, scales=None):
    """One batch: LHS over the priors, the perturbed environment, every vehicle, every link; `scales` are the stage-3
    refit multipliers per vehicle id (stage 1b)."""
    M = len(members)
    U, X = sampling.lhs(M, marg, np.random.SeedSequence([seed, members[0]]), antithetic=tuple(a for a in ANTITHETIC if a in marg))
    t0, T = utc(mission["window"]["start"]).timestamp(), utc(mission["window"]["end"]).timestamp()
    sde = dict(t0=t0, t1=T, dt=DT_VEHICLE) if subgrid.switch(mission.get("environment", {}), "ocean_sde") else None
    penv = PerturbedEnv(env, {k: X[k] for k in FORCING if k in X}, members, seed, pri, sde=sde)
    cls = _classes(mission)
    out = {}
    for v in mission["vehicles"]:
        a = time.time()
        P = load_platform(v["platform"])
        if cls[v["id"]] == "glider":
            P = glider.load_platform(v["platform"])
            out[v["id"]] = _run_glider(v, P, penv, M, X, utc(v["deploy"]["time"]).timestamp(), T, refit_drag(scales, v["id"], seed, members),
                                         windage=subgrid.windage_fraction(seed, members))
        elif cls[v["id"]] == "usv":
            P = usv.load_platform(v["platform"])
            out[v["id"]] = _run_usv(v, P, penv, M, X, utc(v["deploy"]["time"]).timestamp(), T, refit_drag(scales, v["id"], seed, members))
        else:
            P = uas.load_platform(v["platform"])
            out[v["id"]] = _run_uas(v, P, penv, M, X, t0, T, mission, seed, members, refit_drag(scales, v["id"], seed, members))
        out[v["id"]]["class"] = cls[v["id"]]
        out[v["id"]]["wall_s"] = time.time() - a
    links = {lk["id"]: evaluate_link(lk, out, mission, penv, M, seed, members) for lk in mission["links"]}
    return dict(U=U, X=X, vehicles=out, links=links)


def _pos(node, out, mission, t):
    """(lon, lat, height above sea [m], depth [m]) of a vehicle/ship at times t (n,), shape (n, M)."""
    if node == mission.get("ship", {}).get("id"):
        s = mission["ship"]
        M = next(iter(out.values()))["lon"].shape[1]
        f = lambda v: np.full((len(t), M), float(v))
        return f(s["lon"]), f(s["lat"]), f(s.get("antenna_height_m", 10.0)), f(s.get("transducer_depth_m", 5.0))
    r = out[node]
    g = lambda a: np.stack([np.interp(t, r["t"], a[:, m]) for m in range(a.shape[1])], 1)
    h = r.get("alt", np.zeros_like(r["lon"]))
    return g(r["lon"]), g(r["lat"]), g(h) + r["antenna_m"], g(r["depth"])


def _dist(a, b):
    k = np.pi / 180
    x = (np.mod(b[0] - a[0] + 180, 360) - 180) * k * np.cos(0.5 * (a[1] + b[1]) * k)
    return 6.371e6 * np.hypot(x, (b[1] - a[1]) * k)


def evaluate_link(lk, out, mission, env, M, seed, members):
    """Per member: the fraction of the required moments the link worked, against required_fraction."""
    t0, T = utc(mission["window"]["start"]).timestamp(), utc(mission["window"]["end"]).timestamp()
    t = np.arange(t0, T + 1, REC_S)
    a, b = lk["a"], lk["b"]
    if lk["kind"] == "iridium":
        n = len(t)
        rng = np.random.default_rng(sampling.member_seed(seed, members[0], f"iridium/{lk['id']}"))
        ok = np.stack([comms.iridium_session(340, rng, M)[0] for _ in range(n)])
        need = np.ones((n, M), bool)
        method = "Iridium SBD availability/latency model (no range dependence)"
        margin = np.where(ok, 1.0, -1.0)
    else:
        A, B = _pos(a, out, mission, t), _pos(b, out, mission, t)
        d = np.maximum(_dist(A, B), 1.0)
        if lk["when"] == "surfacing":
            need = out[a]["surfaced"].astype(bool) if a in out else out[b]["surfaced"].astype(bool)
            need = np.stack([np.interp(t, out[a if a in out else b]["t"], need[:, m].astype(float)) > 0.5 for m in range(M)], 1)
        elif lk["when"] == "uas_airborne":
            u = a if out.get(a, {}).get("class") == "uas" else b
            need = np.stack([np.interp(t, out[u]["t"], out[u]["airborne"][:, m].astype(float)) > 0.5 for m in range(M)], 1)
        else:
            need = np.ones((len(t), M), bool)
        lonA, latA = A[0], A[1]
        tt = np.broadcast_to(t[:, None], lonA.shape)                         # each member at its own position
        wind = np.hypot(*np.moveaxis(np.asarray(env.env.u10(lonA, latA, tt), float), -1, 0))
        if lk["kind"] == "rf":
            hs = np.asarray(env.waves(lonA.T, latA.T, tt.T)["Hs"].value, float).T     # the member's own Hs perturbation (members first)
            margin = comms.rf_margin(d, A[2], B[2], np.nan_to_num(hs), lk["radio"])
            method = f"two-ray + 4/3-earth horizon, {lk['radio']} (Ament sea roughness, modelled)"
        else:
            reg = comms._yaml("modems.yaml")["modems"]                        # "<modem>_<band>" as named in modems.yaml
            modem, band = next(((k, bd) for k, v in reg.items() for bd in v["bands"] if lk["modem"].lower() == f"{k}_{bd}".lower()), (lk["modem"], "MF"))
            res = comms.acoustic_link(d, modem, band, wind)
            margin = res["margin"].value
            method = res.get("label") or res.get("method")
            if not isinstance(method, str):
                method = str(np.unique(np.asarray(method))[0])
        ok = margin > 0
    frac = np.where(need.sum(0) > 0, (ok & need).sum(0) / np.maximum(need.sum(0), 1), 1.0)
    return dict(frac=frac, success=frac >= lk["required_fraction"], margin_db=np.where(need, margin, np.nan),
                need_count=need.sum(0), method=method, t=t)


def merge(batches):
    """Concatenate batch results along the member axis."""
    def cat(xs):
        return np.concatenate(xs, axis=-1 if np.ndim(xs[0]) > 1 else 0)
    out = dict(U=np.concatenate([b["U"] for b in batches]), X={k: np.concatenate([b["X"][k] for b in batches]) for k in batches[0]["X"]},
               vehicles={}, links={})
    for vid in batches[0]["vehicles"]:
        r0 = batches[0]["vehicles"][vid]
        r = {k: cat([b["vehicles"][vid][k] for b in batches]) for k in ("lon", "lat", "depth")}
        r["t"] = r0["t"]
        for k in ("alt", "airborne", "surfaced"):
            if k in r0:
                r[k] = cat([b["vehicles"][vid][k] for b in batches])
        r["fail"] = {f: np.concatenate([b["vehicles"][vid]["fail"][f] for b in batches]) for f in r0["fail"]}
        r["first"] = {f: np.concatenate([b["vehicles"][vid]["first"][f] for b in batches]) for f in r0["first"]}
        r["class"], r["antenna_m"] = r0["class"], r0["antenna_m"]
        for k in ("scrubbed", "sorties"):
            if k in r0:
                r[k] = r0[k] if k == "sorties" else np.concatenate([b["vehicles"][vid][k] for b in batches])
        out["vehicles"][vid] = r
    for lid in batches[0]["links"]:
        l0 = batches[0]["links"][lid]
        out["links"][lid] = dict(frac=cat([b["links"][lid]["frac"] for b in batches]), success=cat([b["links"][lid]["success"] for b in batches]),
                                 margin_db=cat([b["links"][lid]["margin_db"] for b in batches]), method=l0["method"], t=l0["t"])
    return out


def failed(r):
    return np.logical_or.reduce([np.asarray(v, bool) for v in r["fail"].values()]) if r["fail"] else np.zeros(r["lon"].shape[1], bool)


def summarize(res, names, mission, n_certify):
    """Verdict, dominant failure mode, first time, sensitivity for every vehicle and link."""
    U = res["U"]
    out = dict(vehicles={}, links={})
    for vid, r in res["vehicles"].items():
        f = failed(r)
        n = len(f)
        v = intervals.verdict(int(f.sum()), n)
        modes = {k: int(np.sum(x)) for k, x in r["fail"].items()}
        dom = max(modes, key=lambda k: modes[k]) if any(modes.values()) else None
        first = r["first"][dom] if dom else None
        t_first = float(np.nanmin(first)) if dom and np.any(np.isfinite(first)) else None
        t_med = float(np.nanmedian(first)) if dom and np.any(np.isfinite(first)) else None
        sens = sensitivity.dominant(names, U, f.astype(float)) if 0 < f.sum() < n and n >= 16 else (None, {})
        out["vehicles"][vid] = dict(cls=r["class"], n=n, k_fail=int(f.sum()), verdict=v, modes=modes, dominant=dom,
                                    first_fail_t=t_first, median_fail_t=t_med, sensitivity=dict(param=sens[0], S1=sens[1]))
    for lid, r in res["links"].items():
        f = ~np.asarray(r["success"], bool)
        n = len(f)
        sens = sensitivity.dominant(names, U, f.astype(float)) if 0 < f.sum() < n and n >= 16 else (None, {})
        out["links"][lid] = dict(n=n, k_fail=int(f.sum()), verdict=intervals.verdict(int(f.sum()), n), method=r["method"],
                                 frac_median=float(np.median(r["frac"])), frac_p10=float(np.percentile(r["frac"], 10)),
                                 margin_db_median=float(np.nanmedian(r["margin_db"])) if np.any(np.isfinite(r["margin_db"])) else None,
                                 sensitivity=dict(param=sens[0], S1=sens[1]))
    return out


def run(mission, env, plan, ledger=None, log=print, scales=None, fitted=None):
    pri, marg = priors_for(mission, fitted)
    names = list(marg)
    seed = int(mission["seed"])
    batch, n_max, n_min = plan["batch"], plan["n_max"], plan["n_min"]
    batches, done = [], False
    next_member = 0
    while not done:
        members = list(range(next_member, next_member + batch))
        next_member += batch
        b = run_batch(mission, env, members, seed, pri, marg, scales)
        batches.append(b)
        if ledger is not None:
            rep = sampling.stratification_report(b["U"])
            ledger.check(f"lhs_stratified_batch{len(batches)}", rep["ok"], value=rep["ks_d_max"], limit=rep["ks_bound"],
                         note="each batch is its own Latin hypercube")
        res = merge(batches)
        n = len(res["U"])
        stops = []
        for r in res["vehicles"].values():
            stops.append(sequential.ensemble_stop(int(failed(r).sum()), n, n_min=n_min, n_max=n_max)["stop"])
        for r in res["links"].values():
            stops.append(sequential.ensemble_stop(int((~np.asarray(r["success"], bool)).sum()), n, n_min=n_min, n_max=n_max)["stop"])
        done = all(stops) or n >= n_max
        log(f"stage1: {n} members, {sum(stops)}/{len(stops)} decided; batch wall per vehicle: "
            + ", ".join(f"{k} {r['wall_s']:.0f} s" for k, r in b["vehicles"].items()))
    summ = summarize(res, names, mission, intervals.n_certify())
    return dict(res=res, summary=summ, names=names, priors={k: marg[k] for k in names}, n=len(res["U"]),
                certify=len(res["U"]) >= intervals.n_certify(), n_certify=intervals.n_certify(),
                t0=dt.datetime.fromtimestamp(utc(mission["window"]["start"]).timestamp(), dt.timezone.utc).isoformat())
