"""Stage 1: the Monte-Carlo ensemble over every vehicle and link of a mission, vectorized over members.

Members run in batches. Each batch is its own Latin hypercube (McKay et al. 1979) over the perturbation priors
(config/perturbations.yaml), antithetic on the two dominant forcing errors, and every vehicle in member m sees the
same perturbed environment (common random numbers: `env.perturb.PerturbedEnv`, seeds keyed by member only). After
each batch the stopping rule (`stats.sequential.ensemble_stop`) is asked about every vehicle and link; the ensemble
stops when all are decided or the planner's n_max is reached. Below 73 members (budget quick) nothing can certify
P(fail) < 5 % and the verdict says so.

    run(mission, env, plan, ledger) -> dict(vehicles={id: result}, links={id: result}, tracks, X, U, members)
"""
from __future__ import annotations

import datetime as dt, time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import numpy as np
from numpy.typing import NDArray

from .config import load_platform, utc
from .env import conventions as cv, subgrid
from .env.perturb import PerturbedEnv
from .physics import comms, glider, uas, usv
from .stats import intervals, sampling, sensitivity, sequential

if TYPE_CHECKING:
    from .ledger import Ledger

FORCING = ["wind_speed_bias", "wind_direction_bias", "current_speed_scale", "current_direction_bias", "hs_scale", "tp_bias"]
ANTITHETIC = ("wind_speed_bias", "current_speed_scale")
REC_S = 600.0                         # positions kept every 10 min for links, reports and windows
DT_VEHICLE = 60.0                     # glider and USV step [s]; the ocean SDE's Euler-Maruyama step is the same


def platform_kind(name: str) -> str:
    return load_platform(name).get("kind") or name


def _classes(mission: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for v in mission["vehicles"]:
        k = str(platform_kind(v["platform"])).lower()
        out[v["id"]] = "uas" if "base" in v else ("usv" if "sail" in k or "usv" in k else "glider")
    return out


def priors_for(mission: dict[str, Any], fitted: dict[str, Any] | None = None) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
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


def _record_grid(h: dict[str, Any], init: dict[str, Any]) -> dict[str, NDArray[Any]]:
    """The records links, reports and windows read: the deploy state `init`, then the state after every REC_S / DT_VEHICLE-th step
    of the one-per-step history `h`, so the grid is t0 + k REC_S for k = 0, 1, ... (the same alignment as the UAS and link grids)."""
    n = int(REC_S // DT_VEHICLE)
    return {k: np.concatenate([np.asarray(x)[None], np.asarray(h[k])[n - 1::n]]) for k, x in init.items()}


def _run_glider(v: dict[str, Any], P: dict[str, Any], env: Any, M: int, X: dict[str, NDArray[Any]], t0: float, T: float,
                drag: float | NDArray[Any] = 1.0, windage: NDArray[Any] | None = None) -> dict[str, Any]:
    task = v["task"]
    mis: dict[str, Any] = dict(mode=task["mode"], dive_depth_m=task.get("dive_depth_m", P.get("mission_defaults", {}).get("dive_depth_m", 500.0)))
    if task["mode"] == "station":
        mis.update(station=(task["lon"], task["lat"]), station_tol_m=1e3 * task.get("radius_km", 5.0), lost_hours=task.get("lost_after_h", 6.0))
    if task.get("waypoints"):
        mis["waypoints"] = [tuple(p) for p in task["waypoints"]]
    d = v["deploy"]
    sim = glider.GliderSim(P, M, env, d["lon"], d["lat"], t0, mis,
                           perturb=dict(speed_scale=X["glider_speed_scale"] * drag ** -0.5, battery_scale=X["battery_capacity_scale"],
                                        density_bias=np.zeros(M), **({} if windage is None else dict(windage=windage))))
    h = sim.run(T - t0, dt=DT_VEHICLE)
    start = dict(t=t0, lon=np.full(M, d["lon"]), lat=np.full(M, d["lat"]))
    g = _record_grid(dict(h, surfaced=h["phase"] == 3), dict(start, depth=np.zeros(M), surfaced=np.ones(M, bool)))
    return dict(**g, fail=h["fail"], first=h["first"], sim=sim, antenna_m=P["antenna_height_m"])


def _run_usv(v: dict[str, Any], P: dict[str, Any], env: Any, M: int, X: dict[str, NDArray[Any]], t0: float, T: float,
             drag: float | NDArray[Any] = 1.0) -> dict[str, Any]:
    task = dict(v["task"])
    task["waypoints"] = [tuple(p) for p in task.get("waypoints", [])]
    d = v["deploy"]
    sim = usv.USVSim(P, M, env, (d["lon"], d["lat"]), t0, task, perturb=dict(vpp_bias=(1 + X["usv_vpp_bias"]) * drag ** -0.5 - 1))
    h = sim.run(T - t0, dt=DT_VEHICLE, record_s=DT_VEHICLE)
    g = _record_grid(h, dict(t=t0, lon=np.full(M, d["lon"]), lat=np.full(M, d["lat"])))
    return dict(**g, depth=np.zeros_like(g["lon"]), surfaced=np.ones_like(g["lon"], bool),
                fail=sim.fail, first=sim.first, sim=sim, antenna_m=P["rf_antenna_height_m"])


def launch_times(sorties: dict[str, Any], lon: float, t0: float, T: float, duration_s: float) -> NDArray[np.float64]:
    """Sortie launches [s UTC] at `local_solar_time` (UTC + lon/15 h) every `every_days`, each one ending inside [t0, T]."""
    hh, mm = (int(x) for x in sorties["local_solar_time"].split(":"))
    off = (hh + mm / 60 - lon / 15.0) * 3600.0
    day0 = np.floor(t0 / 86400.0) * 86400.0 - 86400.0
    every = 86400.0 * float(sorties.get("every_days", 1))                                    # seconds between launches
    ts = day0 + off + every * np.arange(int((T - day0) / every) + 3)
    return np.asarray(ts[(ts >= t0) & (ts + duration_s <= T)], float)


def _fewest_boxes(args: tuple[int, int, float, float, float, float, float, float], M: int) -> NDArray[Any]:
    """Mann series from the fewest boxes that hold M non-overlapping segments (a box costs ~2 s; members sharing one are
    separated by >= U x duration along it, uncorrelated per the subgrid receipts). The capacity check runs before any box
    is built, so trying 1, 2, 4, ... boxes costs nothing."""
    for nb in range(1, M):
        try:
            series: NDArray[Any] = subgrid.turbulence_members(*args, n_boxes=nb).value
            return series
        except ValueError:
            pass
    last: NDArray[Any] = subgrid.turbulence_members(*args, n_boxes=M).value
    return last


def _uas_forcing(env: Any, mission: dict[str, Any], origin: tuple[float, float], ts: NDArray[Any], P: dict[str, Any], M: int, seed: int, members: list[int],
                 stress_scale: NDArray[Any] | None = None) -> tuple[list[NDArray[Any] | None], Callable[[Any], NDArray[Any]] | None]:
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
    turbs: list[NDArray[Any] | None] = [None] * len(ts)
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
    gust: Callable[[Any], NDArray[Any]] | None = None
    if sw.get("gust_fronts") and sl is not None and len(ts):
        hours = np.arange(np.floor(ts[0] / 3600) * 3600 - 3600, ts[-1] + 7200, 3600.0)
        lo, la = np.full(hours.size, lon), np.full(hours.size, lat)
        rain = np.asarray(env._w("rain_mm_h", lo, la, hours), float)
        wto = cv.to_deg(np.asarray(env.u10(lo, la, hours), float))
        air = env.air(lo, la, hours)
        te = subgrid.theta_e(air["T2"].value, air["q2"].value, air["psfc"].value)
        ev = subgrid.gust_fronts(sampling.member_seed(seed, members[0], "uas/gust"), rain, hours, M, theta_e_K=te, wind_to_deg=wto)

        def front(t: Any) -> NDArray[Any]:
            g = subgrid.gust_perturbation(ev, np.asarray(t, float))[0].value
            return np.concatenate([g, np.zeros(g.shape[:-1] + (1,))], -1)
        gust = front
    return turbs, gust


def _uas_radio(P: dict[str, Any]) -> dict[str, Any]:
    """The platform's RF radio as a comms.rf_margin radio dict: the first block of quad_uas.yaml `radio` with a transmit power
    (rfd900x), its band centre, power and sensitivity, and antenna gains and losses from platforms/radios.yaml's entry of the same
    name (rfd900x if there is none)."""
    name = next(k for k, v in P["radio"].items() if isinstance(v, dict) and "tx_power_dbm" in v)
    r = P["radio"][name]
    base = comms._yaml("radios.yaml")["radios"]
    return dict(base.get(name, base["rfd900x"]), center_mhz=float(np.mean(r["freq_mhz"])), tx_dbm=r["tx_power_dbm"], rx_sens_dbm=r["rx_sensitivity_dbm"])


def _uas_links(env: Any, mission: dict[str, Any], origin: tuple[float, float], ts: NDArray[Any], P: dict[str, Any],
               M: int) -> list[Callable[[float, NDArray[Any]], NDArray[np.bool_]]]:
    """One `link(t, pos_rel (M, 3)) -> lost (M,)` hook per sortie for uas.fly_sortie: the UAS-to-ship RF budget
    (comms.rf_margin: the platform's radio, the mission's ship antenna height, the UAS antenna at deck + altitude + its height above
    the body, each member's Hs at the ship from `env`), lost where the margin is below 0 dB (or beyond the radio horizon). Hs is read
    on a 30 s grid per sortie, once, and interpolated."""
    so, ra = P["sortie"], P["radio"]
    radio = _uas_radio(P)
    hr = float(mission["ship"].get("antenna_height_m", ra["ship_antenna_height_m"]))
    out: list[Callable[[float, NDArray[Any]], NDArray[np.bool_]]] = []
    for t0 in ts:
        tg = t0 + np.arange(0.0, so["duration_s"] * so["hard_stop_factor"] + 61.0, 30.0)

        def full(v: float, n: int = tg.size) -> NDArray[Any]:
            return np.full((M, n), v)

        hs = np.nan_to_num(np.asarray(env.waves(full(origin[0]), full(origin[1]), np.broadcast_to(tg, (M, tg.size)))["Hs"].value, float))

        def link(t: float, rel: NDArray[Any], tg: NDArray[Any] = tg, hs: NDArray[Any] = hs) -> NDArray[np.bool_]:
            j = int(np.clip(np.searchsorted(tg, t) - 1, 0, tg.size - 2))
            w = float(np.clip((t - tg[j]) / (tg[j + 1] - tg[j]), 0.0, 1.0))
            ht = so["deck_height_m"] + rel[:, 2] + ra["uas_antenna_height_above_body_m"]
            return comms.rf_margin(np.hypot(rel[:, 0], rel[:, 1]), ht, hr, (1 - w) * hs[:, j] + w * hs[:, j + 1], radio) < 0.0
        out.append(link)
    return out


def _run_uas(v: dict[str, Any], P: dict[str, Any], env: Any, M: int, X: dict[str, NDArray[Any]], t0: float, T: float, mission: dict[str, Any], seed: int,
             members: list[int], drag: float | NDArray[Any] = 1.0) -> dict[str, Any]:
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


def refit_drag(scales: dict[str, Any] | None, vid: str, seed: int, members: list[int]) -> float | NDArray[np.float64]:
    """Per-member drag multiplier from the stage-3 refit (lognormal around its mean with its sigma), 1 when not refit.
    Speed follows drag^-1/2 at fixed propulsive/buoyancy force (drag ~ v^2) for the glider and USV; the UAS takes it directly."""
    r = (scales or {}).get(vid, {}).get("drag")
    if not r:
        return 1.0
    z = np.array([sampling.member_rng(seed, m, f"refit/{vid}").standard_normal() for m in members])
    s = np.sqrt(np.log1p((r["sigma"] / r["mean"]) ** 2))                    # lognormal with the refit's mean and sigma
    return np.asarray(r["mean"] * np.exp(s * z - 0.5 * s ** 2), float)


def run_batch(mission: dict[str, Any], env: Any, members: list[int], seed: int, pri: dict[str, dict[str, Any]], marg: dict[str, dict[str, Any]],
              scales: dict[str, Any] | None = None) -> dict[str, Any]:
    """One batch: LHS over the priors, the perturbed environment, every vehicle, every link; `scales` are the stage-3
    refit multipliers per vehicle id (stage 1b)."""
    M = len(members)
    U, X = sampling.lhs(M, marg, np.random.SeedSequence([seed, members[0]]), antithetic=tuple(a for a in ANTITHETIC if a in marg))
    t0, T = utc(mission["window"]["start"]).timestamp(), utc(mission["window"]["end"]).timestamp()
    sde = dict(t0=t0, t1=T, dt=DT_VEHICLE) if subgrid.switch(mission.get("environment", {}), "ocean_sde") else None
    penv = PerturbedEnv(env, {k: X[k] for k in FORCING if k in X}, members, seed, pri, sde=sde)
    cls = _classes(mission)
    out: dict[str, dict[str, Any]] = {}
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


def _pos(node: str, out: dict[str, Any], mission: dict[str, Any], t: NDArray[Any]) -> tuple[NDArray[Any], NDArray[Any], NDArray[Any], NDArray[Any]]:
    """(lon, lat, height above sea [m], depth [m]) of a vehicle/ship at times t (n,), shape (n, M)."""
    if node == mission.get("ship", {}).get("id"):
        s = mission["ship"]
        M = next(iter(out.values()))["lon"].shape[1]

        def f(v: float) -> NDArray[Any]:
            return np.full((len(t), M), float(v))

        return f(s["lon"]), f(s["lat"]), f(s.get("antenna_height_m", 10.0)), f(s.get("transducer_depth_m", 5.0))
    r = out[node]

    def g(a: NDArray[Any]) -> NDArray[Any]:
        return np.stack([np.interp(t, r["t"], a[:, m]) for m in range(a.shape[1])], 1)

    h = r.get("alt", np.zeros_like(r["lon"]))
    return g(r["lon"]), g(r["lat"]), g(h) + r["antenna_m"], g(r["depth"])


def _dist(a: tuple[NDArray[Any], ...], b: tuple[NDArray[Any], ...]) -> NDArray[Any]:
    k = np.pi / 180
    x = (np.mod(b[0] - a[0] + 180, 360) - 180) * k * np.cos(0.5 * (a[1] + b[1]) * k)
    return np.asarray(6.371e6 * np.hypot(x, (b[1] - a[1]) * k))


SSP_DEPTHS_M = np.array([0.0, 10.0, 25.0, 50.0, 75.0, 100.0, 150.0, 200.0, 300.0, 400.0, 500.0, 700.0, 1000.0, 1500.0, 2000.0, 3000.0, 4000.0])


def _mid(a: tuple[NDArray[Any], ...], b: tuple[NDArray[Any], ...], k: int, m: int) -> tuple[float, float]:
    """(lon, lat) midway between the two ends of sample k of member m (longitude across the dateline the short way)."""
    return float(a[0][k, m] + 0.5 * (np.mod(b[0][k, m] - a[0][k, m] + 180.0, 360.0) - 180.0)), float(0.5 * (a[1][k, m] + b[1][k, m]))


def _bellhop_member(env: Any, modem: str, band: str, lon: float, lat: float, t: float, tx: float, rx: float, d: NDArray[Any], dz: NDArray[Any],
                    wind: NDArray[Any]) -> NDArray[Any] | None:
    """Bellhop-refined margins for one member's ambiguous samples `d` [m] (horizontal), on the sound-speed profile of `env` at the link midpoint
    and the sample in the middle of them, in the water depth `env.depth` gives there (transducers clipped inside it). None where the
    environment has no profile, no depth or no finite sound speed there: the caller keeps the Thorp margin and says so."""
    if getattr(env, "ocean", True) is None:
        return None
    wd = float(np.ravel(np.asarray(env.depth(lon, lat).value, float))[0])
    if not np.isfinite(wd) or wd < 10.0:
        return None
    z = -np.append(SSP_DEPTHS_M[SSP_DEPTHS_M < wd], wd)
    c = np.ravel(np.asarray(env.sound_speed(np.full(z.size, lon), np.full(z.size, lat), z, np.full(z.size, t)).value, float))
    if not np.all(np.isfinite(c)):
        return None
    out = comms.acoustic_link(d, modem, band, wind, ssp=(z, c), tx_depth=float(np.clip(tx, 1.0, wd - 1.0)), rx_depth=float(np.clip(rx, 1.0, wd - 1.0)),
                              water_depth=wd, dz=dz)
    return np.asarray(out["margin"].value, float)


def _acoustic(modem: str, band: str, d: NDArray[Any], dz: NDArray[Any], wind: NDArray[Any], need: NDArray[np.bool_], A: tuple[NDArray[Any], ...],
              B: tuple[NDArray[Any], ...], t: NDArray[Any], env: Any) -> tuple[NDArray[Any], str]:
    """Acoustic margin (n, M) on the slant path hypot(d, dz) and the method label. The Thorp budget decides every sample outside the
    ambiguity band; the needed samples inside it (|margin| <= modems.yaml ambiguous_db) are re-done with Bellhop, member by member, on the
    GOFS sound-speed profile at the midpoint of the member's middle ambiguous sample and that sample's transducer depths
    (ponytail: one profile and depth pair per member and link, not per sample; per-sample runs cost ~0.2 s each, upgrade if a link's profile
    changes along the track). Without Bellhop, or where the environment has no profile there, those samples keep the Thorp margin and the
    label says so."""
    res = comms.acoustic_link(d, modem, band, wind, dz=dz)
    margin = np.array(res["margin"].value, float)
    lab = res.get("label") or res.get("method")
    label = lab if isinstance(lab, str) else str(np.unique(np.asarray(lab))[0])
    amb = np.broadcast_to(np.asarray(res.get("ambiguous", False)), margin.shape) & need
    if not amb.any():
        return margin, label
    if not comms.bellhop_available():
        return margin, f"{comms.THORP_ONLY_LABEL} ({int(amb.sum())} ambiguous samples)"
    done = 0
    for m in map(int, np.flatnonzero(amb.any(0))):
        i = np.flatnonzero(amb[:, m])
        k = int(i[i.size // 2])
        lon, lat = _mid(A, B, k, m)
        r = _bellhop_member(env, modem, band, lon, lat, float(t[k]), float(A[3][k, m]), float(B[3][k, m]), d[i, m], dz[i, m], wind[i, m])
        if r is not None:
            margin[i, m], done = r, done + i.size
    base = f"Thorp/Stojanovic budget on the slant range, Bellhop on {done} of {int(amb.sum())} ambiguous samples"
    return margin, base + ("" if done == amb.sum() else "; the rest Thorp only (no sound-speed profile or depth there)")


def evaluate_link(lk: dict[str, Any], out: dict[str, Any], mission: dict[str, Any], env: Any, M: int, seed: int, members: list[int]) -> dict[str, Any]:
    """Per member: the fraction of the required moments the link worked, against required_fraction.

    `margin_db` is NaN wherever it is not a link budget: not needed, an unknown position, beyond the radio horizon (RF: the NO_LINK_DB clip) or
    beyond comms.valid_range_m (acoustic: Thorp extrapolated), and always for Iridium (a session success, not a margin). `n_invalid` counts the
    needed samples that were beyond the horizon / out of range, per member, so a summary can say how often the geometry alone decided."""
    t0, T = utc(mission["window"]["start"]).timestamp(), utc(mission["window"]["end"]).timestamp()
    t = np.arange(t0, T + 1, REC_S)
    a, b = lk["a"], lk["b"]
    invalid_kind: str | None = None
    if lk["kind"] == "iridium":
        n = len(t)
        rng = np.random.default_rng(sampling.member_seed(seed, members[0], f"iridium/{lk['id']}"))
        ok = np.stack([comms.iridium_session(340, rng, M)[0] for _ in range(n)])
        need = np.ones((n, M), bool)
        method = "Iridium SBD availability/latency model (no range dependence)"
        margin = np.full((n, M), np.nan)
        valid = np.zeros((n, M), bool)
        margin_kind = "none: Iridium reports a success fraction, not a margin"
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
        need &= np.isfinite(d)                                                  # an unknown position is not a moment the link was required
        lonA, latA = A[0], A[1]
        tt = np.broadcast_to(t[:, None], lonA.shape)                         # each member at its own position
        wind = np.hypot(*np.moveaxis(np.asarray(env.env.u10(lonA, latA, tt), float), -1, 0))
        if lk["kind"] == "rf":
            hs = np.asarray(env.waves(lonA.T, latA.T, tt.T)["Hs"].value, float).T     # the member's own Hs perturbation (members first)
            margin = comms.rf_margin(d, A[2], B[2], np.nan_to_num(hs), lk["radio"])
            valid = margin != comms.NO_LINK_DB
            method = f"two-ray + 4/3-earth horizon, {lk['radio']} (Ament sea roughness, modelled)"
            margin_kind, invalid_kind = "RF link margin, dB", "beyond_horizon"
        else:
            reg = comms._yaml("modems.yaml")["modems"]                        # "<modem>_<band>" as named in modems.yaml
            modem, band = next(((k, bd) for k, v in reg.items() for bd in v["bands"] if lk["modem"].lower() == f"{k}_{bd}".lower()), (lk["modem"], "MF"))
            dz = np.abs(A[3] - B[3])
            margin, method = _acoustic(modem, band, d, dz, wind, need, A, B, t, env)
            valid = np.hypot(d, dz) <= comms.valid_range_m(modem, band)
            margin_kind, invalid_kind = "acoustic link margin, dB", "out_of_range"
        ok = margin > 0
    frac = np.where(need.sum(0) > 0, (ok & need).sum(0) / np.maximum(need.sum(0), 1), 1.0)
    n_invalid = (need & ~valid).sum(0) if invalid_kind else np.zeros(M, int)
    return dict(frac=frac, success=frac >= lk["required_fraction"], margin_db=np.where(need & valid, margin, np.nan), n_invalid=n_invalid,
                need_count=need.sum(0), method=method, margin_kind=margin_kind, invalid_kind=invalid_kind, t=t)


def merge(batches: list[dict[str, Any]]) -> dict[str, Any]:
    """Concatenate batch results along the member axis."""
    def cat(xs: list[NDArray[Any]]) -> NDArray[Any]:
        return np.concatenate(xs, axis=-1 if np.ndim(xs[0]) > 1 else 0)
    out: dict[str, Any] = dict(U=np.concatenate([b["U"] for b in batches]), X={k: np.concatenate([b["X"][k] for b in batches]) for k in batches[0]["X"]},
               vehicles={}, links={})
    for vid in batches[0]["vehicles"]:
        r0 = batches[0]["vehicles"][vid]
        r: dict[str, Any] = {k: cat([b["vehicles"][vid][k] for b in batches]) for k in ("lon", "lat", "depth")}
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
        for k in ("need_count", "n_invalid"):
            if k in l0:
                out["links"][lid][k] = cat([b["links"][lid][k] for b in batches])
        for k in ("margin_kind", "invalid_kind"):
            if k in l0:
                out["links"][lid][k] = l0[k]
    return out


def failed(r: dict[str, Any]) -> NDArray[np.bool_]:
    return np.logical_or.reduce([np.asarray(v, bool) for v in r["fail"].values()]) if r["fail"] else np.zeros(r["lon"].shape[1], bool)


def summarize(res: dict[str, Any], names: list[str], mission: dict[str, Any], n_certify: int) -> dict[str, Any]:
    """Verdict, dominant failure mode, first time, sensitivity for every vehicle and link."""
    U = res["U"]
    out: dict[str, dict[str, Any]] = dict(vehicles={}, links={})
    for vid, r in res["vehicles"].items():
        f = failed(r)
        n = len(f)
        v = intervals.verdict(int(f.sum()), n)
        modes = {k: int(np.sum(x)) for k, x in r["fail"].items()}
        dom = max(modes, key=lambda k: modes[k]) if any(modes.values()) else None
        first = r["first"][dom] if dom else np.empty(0)
        t_first = float(np.nanmin(first)) if dom and np.any(np.isfinite(first)) else None
        t_med = float(np.nanmedian(first)) if dom and np.any(np.isfinite(first)) else None
        sens: tuple[str | None, dict[str, float], float | None] = (sensitivity.dominant(names, U, f.astype(float)) if 0 < f.sum() < n and n >= 16
                                                                  else (None, {}, None))
        out["vehicles"][vid] = dict(cls=r["class"], n=n, k_fail=int(f.sum()), verdict=v, modes=modes, dominant=dom,
                                    first_fail_t=t_first, median_fail_t=t_med, sensitivity=dict(param=sens[0], S1=sens[1], noise_floor=sens[2]))
    for lid, r in res["links"].items():
        f = ~np.asarray(r["success"], bool)
        n = len(f)
        sens = sensitivity.dominant(names, U, f.astype(float)) if 0 < f.sum() < n and n >= 16 else (None, {}, None)
        kind, need = r.get("invalid_kind"), float(np.sum(r.get("need_count", 0)))
        bad = float(np.sum(r["n_invalid"])) / need if kind and need else None          # of the needed samples, how many the geometry alone decided
        out["links"][lid] = dict(n=n, k_fail=int(f.sum()), verdict=intervals.verdict(int(f.sum()), n), method=r["method"],
                                 frac_median=float(np.median(r["frac"])), frac_p10=float(np.percentile(r["frac"], 10)),
                                 margin_db_median=float(np.nanmedian(r["margin_db"])) if np.any(np.isfinite(r["margin_db"])) else None,
                                 margin_kind=r.get("margin_kind"), frac_beyond_horizon=bad if kind == "beyond_horizon" else None,
                                 frac_out_of_range=bad if kind == "out_of_range" else None,
                                 sensitivity=dict(param=sens[0], S1=sens[1], noise_floor=sens[2]))
    return out


BRIEF_PRIOR = "usv_vpp_bias_brief"


def sensitivity_case(mission: dict[str, Any], env: Any, prior: str = BRIEF_PRIOR, n: int = 32, fitted: dict[str, Any] | None = None,
                     scales: dict[str, Any] | None = None) -> dict[str, list[dict[str, Any]]]:
    """The USV ensemble again with `usv_vpp_bias` drawn from perturbations.yaml's `prior` instead (default: the brief's literal -30 to -35 %,
    which `priors_for` never samples). Same seed, members 0..n-1 as one batch, every other input drawn from the run's own hypercube columns,
    the USV vehicles only; -> {vehicle id: [dict(case, k_fail, n, verdict, note)]}, the shape of report.SENSITIVITY."""
    pri, marg = priors_for(mission, fitted)
    marg["usv_vpp_bias"] = sampling.to_marginals(pri, [prior])[prior]
    usvs = [v for v in mission["vehicles"] if _classes(mission)[v["id"]] == "usv"]
    b = run_batch(dict(mission, vehicles=usvs, links=[]), env, list(range(n)), int(mission["seed"]), pri, marg, scales)
    res = merge([b])
    e = pri[prior]
    case = f"usv_vpp_bias uniform [{e['lo']}, {e['hi']}] ({prior})"
    return {vid: [dict(case=case, k_fail=int(failed(r).sum()), n=n, verdict=intervals.verdict(int(failed(r).sum()), n)["verdict"],
                       note=str(e.get("note", e["citation"])))] for vid, r in res["vehicles"].items()}


def main(argv: list[str] | None = None) -> int:
    """python -m cafe.pm.stage1 --mission M --run DIR [--prior usv_vpp_bias_brief] [--members 32]: store sensitivity_case's result in
    DIR/stage1b/sensitivity_cases.json (replacing the entries of the same case), for the report to show next to the verdict. DIR is a finished
    run of M (its ingest cache, fitted priors and refit multipliers are used)."""
    import argparse, json, pathlib
    from . import pipeline
    ap = argparse.ArgumentParser(prog="python -m cafe.pm.stage1", description=main.__doc__)
    ap.add_argument("--mission", required=True)
    ap.add_argument("--run", required=True)
    ap.add_argument("--prior", default=BRIEF_PRIOR)
    ap.add_argument("--members", type=int, default=32)
    a = ap.parse_args(argv)
    rd = pathlib.Path(a.run)
    ctx = pipeline.Context(a.mission, "quick", 0, rd)
    fp, rp = rd / "ingest" / "priors_fitted.json", rd / "refit" / "refit.json"
    scales = {k: v for k, v in json.loads(rp.read_text()).items() if v["used"]} if rp.is_file() else None
    new = sensitivity_case(ctx.mission, ctx.env, a.prior, a.members, json.loads(fp.read_text()) if fp.is_file() else None, scales or None)
    out = rd / "stage1b" / "sensitivity_cases.json"
    old = json.loads(out.read_text()) if out.is_file() else {}
    for vid, cases in new.items():
        old[vid] = [c for c in old.get(vid, []) if c["case"] != cases[0]["case"]] + cases
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(old, indent=1, sort_keys=True))
    print(f"{out}: " + ", ".join(f"{v} {c[0]['k_fail']} of {c[0]['n']} {c[0]['verdict']}" for v, c in new.items()))
    return 0


def run(mission: dict[str, Any], env: Any, plan: dict[str, Any], ledger: Ledger | None = None, log: Callable[[str], None] = print,
        scales: dict[str, Any] | None = None, fitted: dict[str, Any] | None = None) -> dict[str, Any]:
    pri, marg = priors_for(mission, fitted)
    names = list(marg)
    seed = int(mission["seed"])
    batch, n_max, n_min = plan["batch"], plan["n_max"], plan["n_min"]
    batches: list[dict[str, Any]] = []
    done = False
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
        stops: list[bool] = []
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


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
