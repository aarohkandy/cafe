"""Stage 1: the Monte-Carlo ensemble over every vehicle and link of a mission, vectorized over members.

Members run in batches. Each batch is its own Latin hypercube (McKay et al. 1979) over the perturbation priors
(config/perturbations.yaml), antithetic on the two dominant forcing errors, and every vehicle in member m sees the
same perturbed environment (common random numbers: `env.perturb.PerturbedEnv`, seeds keyed by member only). After
each batch the stopping rule (`stats.sequential.ensemble_stop`) is asked about every vehicle and link; the ensemble
stops when all are decided or the planner's n_max is reached. Below 73 members (budget quick) nothing can certify
P(fail) < 5 % and the verdict says so.

Every core of the machine is used (`cafe.pm.par`): inside a batch each glider and USV is a task and each UAS sortie is one, and when one batch
does not fill the workers several batches run at once. The batches are still merged and judged by the stopping rule in member order, so a
run gives the same members and the same bits on any number of workers.

    run(mission, env, plan, ledger) -> dict(vehicles={id: result}, links={id: result}, tracks, X, U, members)
"""
from __future__ import annotations

import concurrent.futures as cf, datetime as dt, time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import numpy as np
from numpy.typing import NDArray

from . import budget, par
from .config import load_platform, platform_class, utc
from .env import conventions as cv, subgrid
from .env.environment import OutsideData
from .env.perturb import PerturbedEnv
from .physics import comms, glider, uas, usv
from .stats import intervals, sampling, sensitivity, sequential

if TYPE_CHECKING:
    from .ledger import Ledger

FORCING = ["wind_speed_bias", "wind_direction_bias", "current_speed_scale", "current_direction_bias", "hs_scale", "tp_bias"]
ANTITHETIC = ("wind_speed_bias", "current_speed_scale")
REC_S = 600.0                         # positions kept every 10 min for links, reports and windows
FINE_S = 30.0                         # the UAS sorties are also kept (and their links judged) every 30 s: a sortie spans only 1 to 2 of the 10 min records
DT_VEHICLE = 60.0                     # glider and USV step [s]; the ocean SDE's Euler-Maruyama step is the same


# per class, besides FORCING
ACTS = dict(glider=("glider_speed_scale", "battery_capacity_scale"), usv=("usv_vpp_bias",), uas=("bulk_stress_scale", "battery_capacity_scale"))
SENS_MIN_N = 16                       # fewest members the first-order indices are computed from (stats.sensitivity: EASI harmonics vs member count)


SUBGRID_SWITCHES = ("turbulence", "gust_fronts", "warm_layer", "rain_lens", "ocean_sde")


def subgrid_switches(mission: dict[str, Any]) -> dict[str, dict[str, bool]]:
    """The five `environment.subgrid` switches as the run reads them (`subgrid.switch`: on unless the mission says false): {name: {on, defaulted}},
    `defaulted` where the mission left the key out."""
    env = mission.get("environment", {})
    return {k: dict(on=subgrid.switch(env, k), defaulted=k not in env.get("subgrid", {})) for k in SUBGRID_SWITCHES}


def _classes(mission: dict[str, Any]) -> dict[str, str]:
    return {v["id"]: platform_class(v) for v in mission["vehicles"]}


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


def _record_grid(h: dict[str, Any], init: dict[str, Any], dt: float = DT_VEHICLE) -> dict[str, NDArray[Any]]:
    """The records links, reports and windows read: the deploy state `init`, then the state after every REC_S / dt-th step
    of the one-per-step history `h`, so the grid is t0 + k REC_S for k = 0, 1, ... (the same alignment as the UAS and link grids).
    A run too short for a step has an empty 1-D history: the deploy state alone."""
    n = int(REC_S // dt)
    out = {}
    for k, x in init.items():
        x, a = np.asarray(x), np.asarray(h[k])
        out[k] = np.concatenate([x[None], a[n - 1::n] if a.size else np.empty((0, *x.shape), a.dtype)])
    return out


def _no_heading(h: dict[str, Any], M: int) -> dict[str, NDArray[Any]]:
    """The deploy-state entry of the bow heading for `_record_grid` (round 7, M-27): unknown (NaN) at t0; none when the history holds no heading."""
    return dict(heading=np.full(M, np.nan)) if "heading" in h else {}


def path_speed(lon: NDArray[Any], lat: NDArray[Any], t: NDArray[Any]) -> NDArray[np.float64]:
    """Each member's speed over ground [m/s] from its stored records ((records, members) lon and lat [deg], t (records,) [s]): the sum of the
    segment lengths (equirectangular on the sphere of radius usv.R_E, across the dateline the short way) over the time those segments span;
    a segment with a non-finite end is left out of both. NaN for a member with no segment. The one definition of speed over ground:
    the report's reach map, the speed block of the USV summary and the calibration run (usv.mean_sog) all use it."""
    lon, lat = np.asarray(lon, float), np.asarray(lat, float)
    k = np.pi / 180.0 * usv.R_E
    dx = (np.mod(np.diff(lon, axis=0) + 180.0, 360.0) - 180.0) * k * np.cos(np.radians(0.5 * (lat[1:] + lat[:-1])))
    step, dt_ = np.hypot(dx, np.diff(lat, axis=0) * k), np.diff(np.asarray(t, float))[:, None]
    ok = np.isfinite(step)
    num, den = np.where(ok, step, 0.0).sum(0), np.where(ok, dt_, 0.0).sum(0)
    return np.where(den > 0, num / np.where(den > 0, den, 1.0), np.nan)


def _run_glider(v: dict[str, Any], P: dict[str, Any], env: Any, M: int, X: dict[str, NDArray[Any]], t0: float, T: float,
                drag: float | NDArray[Any] = 1.0, windage: NDArray[Any] | None = None) -> dict[str, Any]:
    task = v["task"]
    mis: dict[str, Any] = dict(mode=task["mode"], dive_depth_m=task.get("dive_depth_m", P.get("mission_defaults", {}).get("dive_depth_m", 500.0)))
    if task["mode"] == "station":
        mis.update(station=(task["lon"], task["lat"]), station_tol_m=1e3 * task.get("radius_km", 5.0), lost_hours=task.get("lost_after_h", 6.0))
    if task.get("waypoints"):
        mis["waypoints"] = [tuple(p) for p in task["waypoints"]]
    if "heading_to" in task:
        mis["heading_to"] = task["heading_to"]                                  # the compass heading a drift glider swims on (GliderSim defaults to 0)
    d = v["deploy"]
    sim = glider.GliderSim(P, M, env, d["lon"], d["lat"], t0, mis,
                           perturb=dict(speed_scale=X["glider_speed_scale"] * drag ** -0.5, battery_scale=X["battery_capacity_scale"],
                                        density_bias=np.zeros(M), **({} if windage is None else dict(windage=windage))))
    h = sim.run(T - t0, dt=DT_VEHICLE)
    start = dict(t=t0, lon=np.full(M, d["lon"]), lat=np.full(M, d["lat"]))
    g = _record_grid(dict(h, surfaced=h["phase"] == 3), dict(start, depth=np.zeros(M), surfaced=np.ones(M, bool), **_no_heading(h, M)))
    if task["mode"] == "station":                                               # the largest excursion from the station [km]
        far = _dist((g["lon"], g["lat"]), (np.full_like(g["lon"], task["lon"]), np.full_like(g["lat"], task["lat"]))).max(0) / 1e3
        margin, what = far, "maximum distance from the station"
    else:                                                                       # the battery energy left above the reserve, as a fraction of the usable pack
        margin, what = 1.0 - sim.E / (sim.cap * (1.0 - P["reserve_frac"])), "battery energy margin"
    return dict(**g, fail=h["fail"], first=h["first"], sim=sim, antenna_m=P["antenna_height_m"], margin=margin, margin_name=what)


def _run_usv(v: dict[str, Any], P: dict[str, Any], env: Any, M: int, X: dict[str, NDArray[Any]], t0: float, T: float,
             drag: float | NDArray[Any] = 1.0) -> dict[str, Any]:
    task = dict(v["task"])
    task["waypoints"] = [tuple(p) for p in task.get("waypoints", [])]
    if task["mode"] == "station":                                               # the station and its radius, as the glider's task gives them
        task["station"] = (task["lon"], task["lat"])
        if "radius_km" in task:
            task.setdefault("track_tolerance_km", task["radius_km"])
    d = v["deploy"]
    sim = usv.USVSim(P, M, env, (d["lon"], d["lat"]), t0, task, perturb=dict(vpp_bias=(1 + X["usv_vpp_bias"]) * drag ** -0.5 - 1))
    h = sim.run(T - t0, dt=DT_VEHICLE, record_s=DT_VEHICLE)
    g = _record_grid(h, dict(t=t0, lon=np.full(M, d["lon"]), lat=np.full(M, d["lat"]), **_no_heading(h, M)))
    k = slice(None, None, int(3600 // REC_S))                                                          # hourly, as the wind is
    lon, lat = g["lon"][k].T, g["lat"][k].T
    tt = np.broadcast_to(g["t"][k], lon.shape)
    wind = {name: np.hypot(*np.moveaxis(np.asarray(env.wind(lon, lat, z, tt).value, float), -1, 0)).mean(1)
            for name, z in (("u10", 10.0), ("anem", P["anemometer_m"]))}
    return dict(**g, depth=np.zeros_like(g["lon"]), surfaced=np.ones_like(g["lon"], bool),
                fail=sim.fail, first=sim.first, sim=sim, antenna_m=P["rf_antenna_height_m"],
                sog_ms=path_speed(g["lon"], g["lat"], g["t"]), stw_ms=np.mean(h["stw"], 0) if len(h["stw"]) else np.full(M, np.nan),
                u10_ms=wind["u10"], wind_anem_ms=wind["anem"],
                margin=sim.xte_max / 1e3, margin_name="maximum distance from the station" if sim.mode == "station" else "maximum cross-track error")


def launch_times(sorties: dict[str, Any], lon: float, t0: float, T: float, duration_s: float) -> NDArray[np.float64]:
    """Sortie launches [s UTC] at `local_solar_time` (UTC + lon/15 h) every `every_days`, each one ending inside [t0, T]. The schedule starts at
    the first daily slot at or after t0 (a sub-daily period fills the window from t0), so a period of 2 d launches on the first day, not
    on the day the epoch happens to put it."""
    hh, mm = (int(x) for x in sorties["local_solar_time"].split(":"))
    off = (hh + mm / 60 - lon / 15.0) * 3600.0
    every = 86400.0 * float(sorties.get("every_days", 1))                                    # seconds between launches
    slot = off + 86400.0 * np.ceil((t0 - off) / 86400.0)                                     # first daily slot at or after t0
    first = slot - every * np.floor((slot - t0) / every)
    ts = first + every * np.arange(int((T - first) / every) + 2)
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


def _uas_hours(env: Any, ts: NDArray[Any]) -> tuple[NDArray[Any], int]:
    """The hours the gust fronts are drawn on (the look-back hour to two hours past the last launch) that lie inside the environment's time span, and how many
    fell outside it: a sortie in the first or last hour of the window would otherwise read an hour the data does not have (OutsideData). An hour outside
    the data has no rain to drive an event, so it gets none; `rain_hourly` itself stays strict."""
    hours = np.arange(np.floor(ts[0] / 3600) * 3600 - 3600, ts[-1] + 7200, 3600.0)
    b = getattr(env, "bounds", None)
    keep = np.ones(hours.size, bool) if b is None else (hours >= b[4]) & (hours <= b[5])
    return hours[keep], int((~keep).sum())


def _uas_forcing(env: Any, mission: dict[str, Any], origin: tuple[float, float], ts: NDArray[Any], P: dict[str, Any], M: int, seed: int, members: list[int],
                 stress_scale: NDArray[Any] | None = None,
                 used: dict[str, int] | None = None, only: int | None = None) -> tuple[list[NDArray[Any] | None], Callable[[Any], NDArray[Any]] | None]:
    """Per-sortie Mann turbulence (M, n, 3) and one gust-front event set for the window, from the surface layer at the ship.
    None where the mission switches them off or the environment has no surface layer (analytic test envs).
    stress_scale (M,): the member's bulk-stress multiplier. sigma_u = 2.5 u* and u*^2 is the stress, so a member's series is
    scaled by sqrt(stress_scale) (the Obukhov length and the mean wind profile are not recomputed: the wind priors perturb those).
    The gust-front rate uses theta_e from the ship's T2, Q2 and PSFC (subgrid.theta_e), so the cold-pool rate factor works.
    used: filled with {stream: seed} of every random stream drawn here (keyed by the batch's first member, so they depend on the batch size).
    only: the turbulence of sortie `only` alone (the others None), for a task that flies that one; the gust fronts still span every launch."""
    sw, sl = mission.get("environment", {}).get("subgrid", {}), getattr(env, "subgrid", None)
    lon, lat = origin
    so = P["sortie"]
    z = so["deck_height_m"] + float(np.mean(so["levels_m"]))
    amp = 1.0 if stress_scale is None else np.sqrt(np.asarray(stress_scale, float))[:, None, None]
    used = {} if used is None else used

    def stream(name: str) -> int:
        used[name] = sampling.member_seed(seed, members[0], name)
        return used[name]
    turbs: list[NDArray[Any] | None] = [None] * len(ts)
    if sw.get("turbulence") and sl is not None:
        for i, t in enumerate(ts):
            if only is not None and i != only:
                continue
            s = sl.surface_layer(env, np.array([lon]), np.array([lat]), np.array([t]))
            w = np.asarray(env.wind(np.full(M, lon), np.full(M, lat), z, t).value, float)          # (M, 2): one point per member
            U = float(np.hypot(w[:, 0], w[:, 1]).mean())                                           # Mann advection speed
            args = (stream(f"uas/turb/{i}"), M, float(s["ustar"].value[0]), float(s["L"].value[0]), z,
                    max(U, 1.0), so["duration_s"] * so["hard_stop_factor"] + 60.0, uas.DT_ENV)
            g = _fewest_boxes(args, M) * amp
            wdir = cv.to_deg(-np.asarray(env.u10(np.array([lon]), np.array([lat]), np.array([t])), float).reshape(2))   # wind FROM
            turbs[i] = subgrid.gust_enu(g, wdir)
    gust: Callable[[Any], NDArray[Any]] | None = None
    if sw.get("gust_fronts") and sl is not None and len(ts):
        hours, _ = _uas_hours(env, ts)
        lo, la = np.full(hours.size, lon), np.full(hours.size, lat)
        rain = np.asarray(env.rain_hourly(lo, la, hours), float)                                  # the hour's own mean rate (row 252 smooths it)
        wto = cv.to_deg(np.asarray(env.u10(lo, la, hours), float))
        air = env.air(lo, la, hours)
        te = subgrid.theta_e(air["T2"].value, air["q2"].value, air["psfc"].value)
        ev = subgrid.gust_fronts(stream("uas/gust"), rain, hours, M, theta_e_K=te, wind_to_deg=wto)

        def front(t: Any) -> NDArray[Any]:
            g = subgrid.gust_perturbation(ev, np.asarray(t, float))[0].value
            return np.concatenate([g, np.zeros(g.shape[:-1] + (1,))], -1)
        gust = front
    return turbs, gust


def fill_hs(hs: NDArray[Any], lon: NDArray[Any], lat: NDArray[Any], what: str) -> tuple[NDArray[np.float64], int]:
    """Wave heights (M, n) with every non-finite one (UMWM's sea mask) replaced by the same member's last finite Hs along time, else the next one:
    a masked cell is not a glass-calm sea (Hs 0 is the deepest two-ray null). -> (filled, number replaced). A member with no finite Hs at all has
    no sea to read: OutsideData naming its position (lon, lat (M,))."""
    hs = np.asarray(hs, float)
    ok = np.isfinite(hs)
    if ok.all():
        return hs, 0
    if not ok.any(1).all():
        m = int(np.flatnonzero(~ok.any(1))[0])
        raise OutsideData(f"{what}: member {m} has no wave height (Hs non-finite on the whole track, e.g. the UMWM sea mask) at ({lon[m]:.3f}, {lat[m]:.3f})")
    k = np.arange(hs.shape[1])
    fw = np.maximum.accumulate(np.where(ok, k, -1), axis=1)
    bw = np.minimum.accumulate(np.where(ok, k, hs.shape[1])[:, ::-1], axis=1)[:, ::-1]
    return np.take_along_axis(hs, np.where(fw >= 0, fw, bw), 1), int((~ok).sum())


def _uas_radio(P: dict[str, Any]) -> dict[str, Any]:
    """The platform's RF radio as a comms.rf_margin radio dict: the first block of quad_uas.yaml `radio` with a transmit power
    (rfd900x), its band centre, power and sensitivity, and antenna gains and losses from platforms/radios.yaml's entry of the same
    name (rfd900x if there is none)."""
    name = next(k for k, v in P["radio"].items() if isinstance(v, dict) and "tx_power_dbm" in v)
    r = P["radio"][name]
    base = comms._yaml("radios.yaml")["radios"]
    return dict(base.get(name, base["rfd900x"]), center_mhz=float(np.mean(r["freq_mhz"])), tx_dbm=r["tx_power_dbm"], rx_sens_dbm=r["rx_sensitivity_dbm"])


def ship_antenna_m(mission: dict[str, Any], radio: dict[str, Any] | None = None) -> float:
    """The ship's RF antenna height [m]: the mission's, else the UAS platform's `radio.ship_antenna_height_m` (10 m without a UAS platform). The one fallback
    of the sortie hook and the mission-level link (round 8, M-17: the link used a literal 10 and ignored the platform's listed assumed input)."""
    return float(mission["ship"].get("antenna_height_m", (radio or {}).get("ship_antenna_height_m", 10.0)))


def _uas_links(env: Any, mission: dict[str, Any], origin: tuple[float, float], ts: NDArray[Any], P: dict[str, Any],
               M: int, filled: list[int] | None = None) -> list[Callable[[float, NDArray[Any]], NDArray[np.bool_]]]:
    """One `link(t, pos_rel (M, 3)) -> lost (M,)` hook per sortie for uas.fly_sortie: the UAS-to-ship RF budget
    (comms.rf_margin: the platform's radio, the mission's ship antenna height, the UAS antenna at deck + altitude + its height above
    the body, each member's Hs at the ship from `env`), lost where the margin is below 0 dB (or beyond the radio horizon). Hs is read
    on a 30 s grid per sortie, once, and interpolated; a non-finite Hs is the member's last finite one (fill_hs), and `filled` gets the count per sortie."""
    so, ra = P["sortie"], P["radio"]
    radio = _uas_radio(P)
    hr = ship_antenna_m(mission, ra)
    out: list[Callable[[float, NDArray[Any]], NDArray[np.bool_]]] = []
    for t0 in ts:
        tg = t0 + np.arange(0.0, so["duration_s"] * so["hard_stop_factor"] + 61.0, 30.0)

        def full(v: float, n: int = tg.size) -> NDArray[Any]:
            return np.full((M, n), v)

        hs, n_fill = fill_hs(env.waves(full(origin[0]), full(origin[1]), np.broadcast_to(tg, (M, tg.size)))["Hs"].value, full(origin[0])[:, 0],
                             full(origin[1])[:, 0], f"UAS link at the ship, sortie {t0:.0f}")
        if filled is not None:
            filled.append(n_fill)

        def link(t: float, rel: NDArray[Any], tg: NDArray[Any] = tg, hs: NDArray[Any] = hs) -> NDArray[np.bool_]:
            j = int(np.clip(np.searchsorted(tg, t) - 1, 0, tg.size - 2))
            w = float(np.clip((t - tg[j]) / (tg[j + 1] - tg[j]), 0.0, 1.0))
            ht = so["deck_height_m"] + rel[:, 2] + ra["uas_antenna_height_above_body_m"]
            return comms.rf_margin(np.hypot(rel[:, 0], rel[:, 1]), ht, hr, (1 - w) * hs[:, j] + w * hs[:, j + 1], radio) < 0.0
        out.append(link)
    return out


def _uas_setup(v: dict[str, Any], P: dict[str, Any], mission: dict[str, Any], t0: float, T: float) -> tuple[dict[str, Any], tuple[float, float], NDArray[Any]]:
    """The platform with the mission's sortie and launch rules applied, the ship's position and the launch times."""
    ship = mission["ship"]
    origin = (float(ship["lon"]), float(ship["lat"]))
    P = dict(P, sortie=dict(P["sortie"]), launch_rule=dict(P["launch_rule"]))
    so, lr = P["sortie"], v.get("launch_rules", {})
    so["duration_s"] = 60.0 * float(v["sorties"].get("duration_min", so["duration_s"] / 60.0))
    so["levels_m"] = [float(a) for a in v["sorties"].get("altitudes_m", so["levels_m"])]
    rename = {"max_mean_wind_ms": "max_mean_wind_ms", "no_gust_front_within_min": "gust_lookahead_min"}       # mission key -> platform key
    P["launch_rule"].update({rename[a]: float(x) for a, x in lr.items() if a in rename})
    return P, origin, launch_times(v["sorties"], origin[0], t0, T, so["duration_s"] * so["hard_stop_factor"])


def _uas_sortie(i: int, v: dict[str, Any], P: dict[str, Any], env: Any, M: int, X: dict[str, NDArray[Any]], t0: float, T: float, mission: dict[str, Any],
                seed: int, members: list[int], drag: float | NDArray[Any]) -> tuple[dict[str, Any], dict[str, int], int, tuple[int, int] | None]:
    """Sortie i of `_run_uas`, a task: -> (fly_sortie's result, {stream: seed} it drew, wave heights fill_hs replaced, (wind points answered
    from 3-D, wind points asked) while it flew, None for an environment that does not count them)."""
    P, origin, ts = _uas_setup(v, P, mission, t0, T)
    used: dict[str, int] = {}
    sw = {k: x["on"] for k, x in subgrid_switches(mission).items()}                           # a switch the mission left out is on (round 5, M-7)
    mission = dict(mission, environment=dict(mission.get("environment", {}), subgrid=sw))
    turbs, gust = _uas_forcing(env, mission, origin, ts, P, M, seed, members, X.get("bulk_stress_scale"), used, only=i)
    filled: list[int] = []
    link = _uas_links(env, mission, origin, ts[i:i + 1], P, M, filled)[0]
    base = getattr(env, "env", env)
    asked, from3d = getattr(base, "wind_points", None), getattr(base, "wind3d_points", 0)
    s = uas.fly_sortie(env, lambda t: np.zeros(2), float(ts[i]), M=M, origin=origin, plat=P, turb=turbs[i], gust=gust,
                       scale=dict(battery=X["battery_capacity_scale"], drag=drag * np.ones(M)), link=link)
    return s, used, sum(filled), None if asked is None else (int(base.wind3d_points - from3d), int(base.wind_points - asked))


def _run_uas(v: dict[str, Any], P: dict[str, Any], env: Any, M: int, X: dict[str, NDArray[Any]], t0: float, T: float, mission: dict[str, Any], seed: int,
             members: list[int], drag: float | NDArray[Any] = 1.0, used: dict[str, int] | None = None) -> dict[str, Any]:
    """Daily flux-profile sorties from the ship (on station): fly_mission per sortie, each a task of its own (`_uas_sortie`), then the 10-min
    grid the links read."""
    Q, origin, ts = _uas_setup(v, P, mission, t0, T)
    gusts = len(ts) and subgrid_switches(mission)["gust_fronts"]["on"] and getattr(env, "subgrid", None) is not None
    n_off = _uas_hours(env, ts)[1] if gusts else 0
    futs = [par.submit(_uas_sortie, i, v, P, env, M, X, t0, T, mission, seed, members, drag) for i in range(len(ts))]
    P, so = Q, Q["sortie"]
    done = [f.result() for f in futs]
    sorties = [d[0] for d in done]
    got: dict[str, int] = {}
    for d in done:
        got.update(d[1])
    if used is not None:                                                                   # the streams in the order one process draws them
        used.update(sorted(got.items(), key=lambda kv: kv[0] == "uas/gust"))
    hs_filled = sum(d[2] for d in done)
    base = getattr(env, "env", env)                                                       # the gridded environment counts the wind points it answers from 3-D
    wind3d = None if getattr(base, "wind_points", None) is None else (sum(d[3][0] for d in done), sum(d[3][1] for d in done))
    def on_grid(tt: NDArray[Any]) -> tuple[NDArray[Any], NDArray[Any], NDArray[Any], NDArray[np.bool_]]:
        """(east, north, altitude above the deck, airborne), each (len(tt), M), from the sorties' own tracks; on the ground where not flying."""
        east, north, alt = (np.zeros((len(tt), M)) for _ in range(3))
        air = np.zeros((len(tt), M), bool)
        for s in sorties:
            tr = s["track"]
            if not tr["t"].size:
                continue
            ta = s["t_launch"] + tr["t"]
            for m in range(M):
                up = tr["phase"][m] < uas.DONE
                inside = (tt >= ta[0]) & (tt <= ta[-1])
                fly = inside & (np.interp(tt, ta, up.astype(float)) > 0.5)
                for arr, j in ((east, 0), (north, 1), (alt, 2)):
                    arr[fly, m] = np.interp(tt[fly], ta, tr["pos_rel"][m, :, j])
                air[fly, m] = True
        return east, north, alt, air
    t = np.arange(t0, T + 1, REC_S)
    east, north, alt, air = on_grid(t)
    lon, lat = uas.lonlat(origin, east, north)
    # a window per launch, the same for every batch
    tf = np.concatenate([tl + np.arange(0.0, so["duration_s"] * so["hard_stop_factor"] + 1.0, FINE_S) for tl in ts]) if len(ts) else np.empty(0)
    fine = None
    if tf.size:                                                                    # the sorties on a 30 s grid: a 20 min sortie is 1 to 2 of the 10 min records
        fe, fn, fa, fair = on_grid(tf)
        flon, flat = uas.lonlat(origin, fe, fn)
        fine = dict(t=tf, lon=flon, lat=flat, alt=fa + so["deck_height_m"], depth=np.zeros_like(flon), airborne=fair)
    n_flown = np.sum([~s["scrubbed"] for s in sorties], 0) if sorties else np.zeros(M, int)
    fail = {k: np.any([s["flags"][k] for s in sorties], 0) if sorties else np.zeros(M, bool) for k in uas.FLAGS}
    first = {k: np.fmin.reduce(np.stack([np.asarray(s["t_first"][k], float) + s["t_launch"] for s in sorties]), 0) if sorties else np.full(M, np.nan)
             for k in uas.FLAGS}                                                   # float64: epoch seconds do not fit float32 (128 s apart)
    fail["no_sortie_flown"] = n_flown == 0                                         # every launch scrubbed: no flux profiles at all
    first["no_sortie_flown"] = np.where(n_flown == 0, T, np.nan)
    soc = np.where(np.stack([s["scrubbed"] for s in sorties]), np.inf, np.stack([s["soc_end"] for s in sorties])).min(0) if sorties else np.full(M, np.inf)
    prof: dict[str, Any] = {}
    if sorties and all("wp_done" in s and "n_wp" in s for s in sorties):                  # the share of the pattern each flown sortie reached, the lowest one
        share = np.where(np.stack([s["scrubbed"] for s in sorties]), np.inf, np.stack([np.asarray(s["wp_done"], float) / s["n_wp"] for s in sorties])).min(0)
        prof = dict(profile_margin=np.where(np.isfinite(share), share, np.nan), profile_margin_name="fraction of the flux profile delivered (lowest sortie)")
    return dict(**prof, t=t, lon=lon, lat=lat, alt=alt + so["deck_height_m"], depth=np.zeros_like(lon), airborne=air, surfaced=np.ones_like(air), fine=fine,
                fail=fail, first=first, antenna_m=P["radio"]["uas_antenna_height_above_body_m"],
                margin=np.where(np.isfinite(soc), soc - P["battery"]["reserve_frac"], np.nan), margin_name="battery reserve margin",
                scrubbed=np.sum([s["scrubbed"] for s in sorties], 0) if sorties else np.zeros(M, int), wind3d=wind3d,
                sorties=[dict(t_launch=s["t_launch"], scrubbed=s["scrubbed"], wind_ms=s["launch"]["wind_ms"], energy_wh=s["energy_wh"],
                              soc_end=s["soc_end"], max_tilt_deg=s["max_tilt_deg"], sat_s=s["sat_s"], demand_ratio_max=s["demand_ratio_max"],
                              **({"wp_done": s["wp_done"]} if "wp_done" in s else {}))              # the waypoints reached; an older sortie result has none
                         for s in sorties],
                **({"n_wp": int(sorties[0]["n_wp"])} if sorties and "n_wp" in sorties[0] else {}), hs_filled=hs_filled,
                **({"hours_dropped": n_off} if n_off else {}))


def refit_drag(scales: dict[str, Any] | None, vid: str, seed: int, members: list[int]) -> float | NDArray[np.float64]:
    """Per-member drag multiplier from the stage-3 refit (lognormal around its mean with its sigma), 1 when not refit.
    Speed follows drag^-1/2 at fixed propulsive/buoyancy force (drag ~ v^2) for the glider and USV; the UAS takes it directly."""
    r = (scales or {}).get(vid, {}).get("drag")
    if not r:
        return 1.0
    z = np.array([sampling.member_rng(seed, m, f"refit/{vid}").standard_normal() for m in members])
    s = np.sqrt(np.log1p((r["sigma"] / r["mean"]) ** 2))                    # lognormal with the refit's mean and sigma
    return np.asarray(r["mean"] * np.exp(s * z - 0.5 * s ** 2), float)


def _vehicle(kind: str, v: dict[str, Any], env: Any, M: int, X: dict[str, NDArray[Any]], T: float, drag: float | NDArray[Any], seed: int,
             members: list[int]) -> tuple[dict[str, Any], float]:
    """One glider or USV of a batch, a task: -> (its result, less the simulator, which holds the environment; its wall time [s])."""
    a = time.time()
    load_platform(v["platform"])
    start = utc(v["deploy"]["time"]).timestamp()
    if kind == "glider":
        r = _run_glider(v, glider.load_platform(v["platform"]), env, M, X, start, T, drag, windage=subgrid.windage_fraction(seed, members))
    else:
        r = _run_usv(v, usv.load_platform(v["platform"]), env, M, X, start, T, drag)
    r.pop("sim", None)
    return r, time.time() - a


def run_batch(mission: dict[str, Any], env: Any, members: list[int], seed: int, pri: dict[str, dict[str, Any]], marg: dict[str, dict[str, Any]],
              scales: dict[str, Any] | None = None, X: dict[str, NDArray[Any]] | None = None) -> dict[str, Any]:
    """One batch: LHS over the priors, the perturbed environment, every vehicle, every link; `scales` are the stage-3
    refit multipliers per vehicle id (stage 1b). `X` ({name: (M,)} for every name in `marg`): these draws instead of the LHS (a paired
    sensitivity case); U is then their quantiles. Besides the vehicles and links the result holds `seeds[vehicle][stream]`: the seed of every
    batch-keyed random stream the run drew (UAS turbulence and gusts, Iridium), the same for every vehicle. A vehicle with a record outside
    the environment's cached box (a lenient environment holds the edge value there) fails with mode `left_data`, first at that record."""
    M = len(members)
    if X is None:
        U, X = sampling.lhs(M, marg, np.random.SeedSequence([seed, members[0]]), antithetic=tuple(a for a in ANTITHETIC if a in marg))
    else:
        X = {k: np.asarray(x, float) for k, x in X.items()}
        if any(len(X[k]) != M for k in marg):
            raise ValueError(f"X must hold {M} values for each of {sorted(marg)}")
        U = np.column_stack([sampling.marginal(m).cdf(X[k]) for k, m in marg.items()])
    t0, T = utc(mission["window"]["start"]).timestamp(), utc(mission["window"]["end"]).timestamp()
    sde = dict(t0=t0, t1=T, dt=DT_VEHICLE) if subgrid.switch(mission.get("environment", {}), "ocean_sde") else None
    penv = PerturbedEnv(env, {k: X[k] for k in FORCING if k in X}, members, seed, pri, sde=sde, window=(t0, T))
    cls = _classes(mission)
    used: dict[str, int] = {}
    out: dict[str, dict[str, Any]] = {}
    futs = {v["id"]: par.submit(_vehicle, cls[v["id"]], v, penv, M, X, T, refit_drag(scales, v["id"], seed, members), seed, members)
            for v in mission["vehicles"] if cls[v["id"]] != "uas"}                # submitted first: _run_uas waits for its sorties
    for v in mission["vehicles"]:
        if cls[v["id"]] == "uas":
            a = time.time()
            r = _run_uas(v, uas.load_platform(v["platform"]), penv, M, X, t0, T, mission, seed, members, refit_drag(scales, v["id"], seed, members), used)
            wall = time.time() - a
        else:
            r, wall = futs[v["id"]].result()
        out[v["id"]] = r
        r["class"] = cls[v["id"]]
        r["wall_s"] = wall
        _left_data(r, env)
    links = {lk["id"]: evaluate_link(lk, out, mission, penv, M, seed, members, used) for lk in mission["links"]}
    return dict(U=U, X=X, vehicles=out, links=links, seeds={vid: dict(used) for vid in out})


def _left_data(r: dict[str, Any], env: Any) -> None:
    """Fail mode `left_data` for a member with a record outside the environment's cached box or hours (`env.inside`), first at that record. Added
    only for an environment that has a box; the pipeline runs it lenient (edge values there) and reports the mode."""
    inside = getattr(env, "inside", None)
    if inside is None:
        return
    lon, lat = np.asarray(r["lon"], float), np.asarray(r["lat"], float)
    out = np.isfinite(lon) & np.isfinite(lat) & ~np.asarray(inside(lon, lat, np.asarray(r["t"], float)[:, None]), bool)
    r["fail"]["left_data"] = out.any(0)
    r["first"]["left_data"] = np.where(out.any(0), np.asarray(r["t"], float)[out.argmax(0)], np.nan)


def _pos(node: str, out: dict[str, Any], mission: dict[str, Any], t: NDArray[Any],
         radio: dict[str, Any] | None = None) -> tuple[NDArray[Any], NDArray[Any], NDArray[Any], NDArray[Any]]:
    """(lon, lat, height above sea [m], depth [m]) of a vehicle/ship at times t (n,), shape (n, M). `radio`: the UAS platform's radio group, the ship
    antenna's default height (ship_antenna_m)."""
    if node == mission.get("ship", {}).get("id"):
        s = mission["ship"]
        M = next(iter(out.values()))["lon"].shape[1]

        def f(v: float) -> NDArray[Any]:
            return np.full((len(t), M), float(v))

        return f(s["lon"]), f(s["lat"]), f(ship_antenna_m(mission, radio)), f(s.get("transducer_depth_m", 5.0))
    r = out[node].get("fine") or out[node]  # a UAS: its 30 s sortie grid (on the deck between sorties), not the 10 min records

    def g(a: NDArray[Any]) -> NDArray[Any]:
        return np.stack([np.interp(t, r["t"], a[:, m]) for m in range(a.shape[1])], 1)

    h = r.get("alt", np.zeros_like(r["lon"]))
    return g(r["lon"]), g(r["lat"]), g(h) + out[node]["antenna_m"], g(r["depth"])


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


def _surfaced(out: dict[str, Any], a: str, b: str, t: NDArray[Any]) -> NDArray[np.bool_]:
    """(len(t), M): the glider end of a link (a, else b) is on the surface at t (its record interpolated, more than half surfaced)."""
    g = a if out.get(a, {}).get("class") == "glider" else b
    return np.stack([np.interp(t, out[g]["t"], out[g]["surfaced"][:, m].astype(float)) > 0.5 for m in range(out[g]["surfaced"].shape[1])], 1)


def evaluate_link(lk: dict[str, Any], out: dict[str, Any], mission: dict[str, Any], env: Any, M: int, seed: int, members: list[int],
                  used: dict[str, int] | None = None) -> dict[str, Any]:
    """Per member: the fraction of the required moments the link worked, against required_fraction. A moment before an end vehicle's deploy time
    is not required. `when: surfacing` follows the glider end (RF, acoustic and Iridium alike: an antenna on a glider works at the surface only) and
    `uas_airborne` the UAS end, whichever way round the link names them.
    `used`: filled with the seed of the Iridium stream.

    `margin_db` is NaN wherever it is not a link budget: not needed, an unknown position, beyond the radio horizon (RF: the NO_LINK_DB clip) or
    beyond comms.valid_range_m (acoustic: Thorp extrapolated), and always for Iridium (a session success, not a margin). `n_invalid` counts the
    needed samples that were beyond the horizon / out of range, per member, so a summary can say how often the geometry alone decided."""
    t0, T = utc(mission["window"]["start"]).timestamp(), utc(mission["window"]["end"]).timestamp()
    t = np.arange(t0, T + 1, REC_S)
    a, b = lk["a"], lk["b"]
    uas_end = next((x for x in (a, b) if out.get(x, {}).get("class") == "uas"), None)
    fine = out[uas_end].get("fine") if uas_end and lk["kind"] != "iridium" and lk["when"] == "uas_airborne" else None
    if fine is not None:                                                        # a sortie is judged every FINE_S, the rest of the window every REC_S
        t = np.union1d(t, fine["t"])
    live = np.ones((len(t), M), bool)
    for x in (a, b):                                                            # before a vehicle's deploy time its position is the deploy point
        if x in out:
            live &= (t >= out[x]["t"][0])[:, None]
    invalid_kind: str | None = None
    hs_filled = 0
    if lk["kind"] == "iridium":
        n = len(t)
        stream = f"iridium/{lk['id']}"
        if used is not None:
            used[stream] = sampling.member_seed(seed, members[0], stream)
        rng = np.random.default_rng(sampling.member_seed(seed, members[0], stream))
        ok = np.stack([comms.iridium_session(340, rng, M)[0] for _ in range(n)])
        need = live & _surfaced(out, a, b, t) if lk["when"] == "surfacing" else live.copy()                  # an antenna on a glider works only at the surface
        method = "Iridium SBD availability/latency model (no range dependence)"
        margin = np.full((n, M), np.nan)
        valid = np.zeros((n, M), bool)
        margin_kind = "none: Iridium reports a success fraction, not a margin"
    else:
        uas_v = next((v for v in mission["vehicles"] if out.get(v["id"], {}).get("class") == "uas"), None)
        radio = uas.load_platform(uas_v["platform"])["radio"] if uas_v and "antenna_height_m" not in mission["ship"] else None
        A, B = _pos(a, out, mission, t, radio), _pos(b, out, mission, t, radio)
        d = np.maximum(_dist(A, B), 1.0)
        if lk["when"] == "surfacing":
            need = _surfaced(out, a, b, t)
        elif lk["when"] == "uas_airborne":
            if fine is not None:  # sample and hold: a flag is the latest sample's, for FINE_S after it; no sortie, no flight
                i = np.searchsorted(fine["t"], t, side="right") - 1
                need = fine["airborne"][np.maximum(i, 0)] & ((i >= 0) & (t - fine["t"][np.maximum(i, 0)] < FINE_S))[:, None]
            else:
                u = a if out.get(a, {}).get("class") == "uas" else b
                need = np.stack([np.interp(t, out[u]["t"], out[u]["airborne"][:, m].astype(float)) > 0.5 for m in range(M)], 1)
        else:
            need = np.ones((len(t), M), bool)
        need &= live & np.isfinite(d)                                           # an unknown position is not a moment the link was required
        lonA, latA = A[0], A[1]
        tt = np.broadcast_to(t[:, None], lonA.shape)                         # each member at its own position
        if lk["kind"] == "rf":
            hs = np.asarray(env.waves(lonA.T, latA.T, tt.T)["Hs"].value, float)         # the member's own Hs perturbation (members first)
            hs = np.where(np.isfinite(lonA.T) & np.isfinite(latA.T), hs, 0.0)           # an unknown position is no moment the link was required
            hs, hs_filled = fill_hs(hs, lonA[0], latA[0], f"link {lk['id']}")
            margin = comms.rf_margin(d, A[2], B[2], hs.T, lk["radio"])
            valid = margin != comms.NO_LINK_DB
            method = f"two-ray over a 4/3-radius earth with divergence (Kerr), {lk['radio']} (Ament sea roughness, modelled)"
            margin_kind, invalid_kind = "RF link margin, dB", "beyond_horizon"
        else:
            reg = comms._yaml("modems.yaml")["modems"]                        # "<modem>_<band>" as named in modems.yaml
            modem, band = next(((k, bd) for k, v in reg.items() for bd in v["bands"] if lk["modem"].lower() == f"{k}_{bd}".lower()), (lk["modem"], "MF"))
            dz = np.abs(A[3] - B[3])
            wind = np.hypot(*np.moveaxis(np.asarray(env.wind(lonA.T, latA.T, 10.0, tt.T).value, float), -1, 0)).T          # the member's own wind, as for Hs
            margin, method = _acoustic(modem, band, d, dz, wind, need, A, B, t, env)
            valid = np.hypot(d, dz) <= comms.valid_range_m(modem, band)
            margin_kind, invalid_kind = "acoustic link margin, dB", "out_of_range"
        ok = margin > 0
    dist = np.full(M, np.nan) if lk["kind"] == "iridium" else np.array([np.median(d[need[:, m], m]) if need[:, m].any() else np.nan for m in range(M)])
    frac = np.where(need.sum(0) > 0, (ok & need).sum(0) / np.maximum(need.sum(0), 1), 1.0)
    n_invalid = (need & ~valid).sum(0) if invalid_kind else np.zeros(M, int)
    return dict(frac=frac, success=frac >= lk["required_fraction"], margin_db=np.where(need & valid, margin, np.nan), n_invalid=n_invalid,
                need_count=need.sum(0), dist_m=dist, method=method, margin_kind=margin_kind, invalid_kind=invalid_kind, t=t, hs_filled=hs_filled)


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
        for k in ("alt", "airborne", "surfaced", "heading", "sog_ms", "stw_ms", "u10_ms", "wind_anem_ms", "margin", "profile_margin"):
            if k in r0:
                r[k] = cat([b["vehicles"][vid][k] for b in batches])
        for k in ("margin_name", "profile_margin_name"):
            if k in r0:
                r[k] = r0[k]
        if r0.get("fine") is not None:                       # the same sortie windows in every batch: only the members differ
            r["fine"] = dict(t=r0["fine"]["t"], **{k: cat([b["vehicles"][vid]["fine"][k] for b in batches]) for k in r0["fine"] if k != "t"})
        r["fail"] = {f: np.concatenate([b["vehicles"][vid]["fail"][f] for b in batches]) for f in r0["fail"]}
        r["first"] = {f: np.concatenate([b["vehicles"][vid]["first"][f] for b in batches]) for f in r0["first"]}
        r["class"], r["antenna_m"] = r0["class"], r0["antenna_m"]
        if "scrubbed" in r0:
            r["scrubbed"] = np.concatenate([b["vehicles"][vid]["scrubbed"] for b in batches])
        if "sorties" in r0:                                   # sortie i of every batch is the same launch: its per-member arrays join along the members
            r["sorties"] = [dict(t_launch=so["t_launch"],
                                 **{k: np.concatenate([b["vehicles"][vid]["sorties"][i][k] for b in batches]) for k in so if k != "t_launch"})
                            for i, so in enumerate(r0["sorties"])]
        for k in ("n_wp", "hs_filled", "hours_dropped"):      # the pattern length and dropped hours repeat in every batch; the filled Hs samples add up
            if k in r0:
                r[k] = r0[k] if k != "hs_filled" else sum(b["vehicles"][vid][k] for b in batches)
        if r0.get("wind3d") is not None:
            r["wind3d"] = tuple(int(sum(b["vehicles"][vid]["wind3d"][i] for b in batches)) for i in (0, 1))
        out["vehicles"][vid] = r
    for lid in batches[0]["links"]:
        l0 = batches[0]["links"][lid]
        out["links"][lid] = dict(frac=cat([b["links"][lid]["frac"] for b in batches]), success=cat([b["links"][lid]["success"] for b in batches]),
                                 margin_db=cat([b["links"][lid]["margin_db"] for b in batches]), method=l0["method"], t=l0["t"])
        for k in ("need_count", "n_invalid", "dist_m"):
            if k in l0:
                out["links"][lid][k] = cat([b["links"][lid][k] for b in batches])
        for k in ("margin_kind", "invalid_kind"):
            if k in l0:
                out["links"][lid][k] = l0[k]
        out["links"][lid]["hs_filled"] = sum(b["links"][lid].get("hs_filled", 0) for b in batches)
    if "seeds" in batches[0]:
        out["seeds"] = {vid: {st: [b["seeds"][vid][st] for b in batches] for st in sd} for vid, sd in batches[0]["seeds"].items()}
    return out


def failed(r: dict[str, Any]) -> NDArray[np.bool_]:
    return np.logical_or.reduce([np.asarray(v, bool) for v in r["fail"].values()]) if r["fail"] else np.zeros(r["lon"].shape[1], bool)


def _sensitivity(names: list[str], U: NDArray[Any], f: NDArray[np.bool_], acting: set[str], margin: NDArray[Any] | None, quantity: str) -> dict[str, Any]:
    """The "most sensitive to" entry of a vehicle or a link: dict(param, S1, noise_floor, case, quantity, text). `f` (n,) marks the members that failed.
    The indices are first-order EASI (stats.sensitivity) over the columns that can act on it (`acting`: the forcing errors and the class's own), so a
    column that cannot act does not set the noise floor. They are taken on `margin` (n,), the continuous quantity named `quantity`, when the simulator
    gave one; else on the 0/1 failure indicator, which carries too little for three failures or fewer (EASI on k ones saturates at its own
    permutation floor), so there the minority's hypercube ranks are given instead. case: ranked / nothing_above_floor (an index was computed and none
    clears the floor) / too_few (no index: fewer than SENS_MIN_N members, or too few failures or successes on the indicator) / all_pass / all_fail."""
    n, k = len(f), int(f.sum())
    out: dict[str, Any] = dict(param=None, S1={}, noise_floor=None, quantity=quantity)
    if k == 0:
        return dict(out, case="all_pass", text="No member failed, so there is no failure to attribute to a parameter.")
    if k == n:
        return dict(out, case="all_fail", text="Every member failed, so there is no passing member to compare with and no parameter to blame.")
    if n < SENS_MIN_N:
        return dict(out, case="too_few", text=f"Only {n} members: at least {SENS_MIN_N} are needed to rank the parameters.")
    cols = [i for i, nm in enumerate(names) if nm in acting]
    nm, Ux = [names[i] for i in cols], U[:, cols]
    row = np.ones(n, bool) if margin is None else np.isfinite(margin)
    if margin is None or row.sum() < SENS_MIN_N:
        y, row, out["quantity"] = f.astype(float), np.ones(n, bool), "failure indicator"
        if min(k, n - k) < 3:
            few = f if k < n - k else ~f
            ranks = "; ".join(f"{p} {', '.join(map(str, rk))}" for p, rk in sensitivity.extreme_ranks(nm, Ux, few))
            return dict(out, case="too_few", text=f"Only {int(few.sum())} of {n} members {'failed' if few is f else 'passed'}, too few to rank the parameters; "
                                                  f"their ranks among the {n} draws (0 is the lowest value) are {ranks}.")
    else:
        y = np.asarray(margin, float)
    param, s1, floor = sensitivity.dominant(nm, Ux[row], y[row])
    out.update(param=param, S1=s1, noise_floor=floor)
    if param is not None:
        by = f" by {s1[param] - floor:.3f}" if round(s1[param], 2) == round(floor, 2) else ""                  # agree to two places: say how far apart they are
        return dict(out, case="ranked", text=f"{param} has the largest first-order index (S1 {s1[param]:.3f}) for the {out['quantity']}, "
                                             f"above the {floor:.3f} that unrelated outcomes reach at this member count{by}.")
    top = max(s1, key=lambda p: s1[p])
    return dict(out, case="nothing_above_floor", text=f"No parameter clears the noise floor for the {out['quantity']} (largest S1 {s1[top]:.3f}, {top}; "
                                                      f"floor {floor:.3f}): the sample cannot rank them, which is not the same as none mattering.")


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
        # each failed member's earliest failure, in any mode
        firsts = [np.where(np.asarray(x, bool), np.asarray(r["first"][k], float), np.nan) for k, x in r["fail"].items()]
        first = np.fmin.reduce(firsts)[f] if dom else np.empty(0)
        t_first = float(np.nanmin(first)) if np.any(np.isfinite(first)) else None
        t_med = float(np.nanmedian(first)) if np.any(np.isfinite(first)) else None
        key = "profile_margin" if dom == "profile_incomplete" and "profile_margin" in r else "margin"          # the margin that belongs to the dominant mode
        sens = _sensitivity(names, U, f, set(FORCING) | set(ACTS[r["class"]]), r.get(key), r.get(f"{key}_name", "failure indicator"))
        out["vehicles"][vid] = dict(cls=r["class"], n=n, k_fail=int(f.sum()), verdict=v, modes=modes, dominant=dom,
                                    first_fail_t=t_first, median_fail_t=t_med, sensitivity=sens)
        if "sog_ms" in r:
            out["vehicles"][vid]["speed"] = _speed(r, next(v["platform"] for v in mission["vehicles"] if v["id"] == vid))
        if r.get("sorties") and "sat_s" in r["sorties"][0]:
            sat, ratio = (np.concatenate([np.asarray(so[k], float)[~np.asarray(so["scrubbed"], bool)] for so in r["sorties"]])
                          for k in ("sat_s", "demand_ratio_max"))
            if sat.size:
                out["vehicles"][vid]["authority"] = dict(clamp_s_median=float(np.median(sat)), clamp_s_max=float(sat.max()),
                                                         demand_ratio_median=float(np.median(ratio)), demand_ratio_max=float(ratio.max()))
        if r.get("n_wp") and r.get("sorties") and "wp_done" in r["sorties"][0]:       # the flux profile each flown sortie delivered
            wp = np.concatenate([np.asarray(so["wp_done"], float)[~np.asarray(so["scrubbed"], bool)] for so in r["sorties"]])
            if wp.size:
                out["vehicles"][vid]["profile"] = dict(wp_done_median=float(np.median(wp)), n_wp=int(r["n_wp"]), complete_share=float(np.mean(wp >= r["n_wp"])))
        if r.get("wind3d") and r["wind3d"][1]:
            out["vehicles"][vid]["wind3d_fraction"] = r["wind3d"][0] / r["wind3d"][1]      # the share of the sorties' wind points the 3-D fields answered
    lk_ends = {lk["id"]: lk for lk in mission["links"]}
    out["subgrid_switches"] = subgrid_switches(mission)
    for lid, r in res["links"].items():
        f = ~np.asarray(r["success"], bool)
        n = len(f)
        ends = {res["vehicles"][e]["class"] for e in (lk_ends[lid]["a"], lk_ends[lid]["b"]) if e in res["vehicles"]}
        sens = _sensitivity(names, U, f, set(FORCING) | {c for k in ends for c in ACTS[k]}, np.asarray(r["frac"], float),
                            "fraction of the required moments the link worked")
        kind, need = r.get("invalid_kind"), float(np.sum(r.get("need_count", 0)))
        nc = int(np.median(r["need_count"])) if "need_count" in r else None            # required samples per member: what the required fraction is resolved on
        rf = lk_ends[lid]["required_fraction"]
        bad = float(np.sum(r["n_invalid"])) / need if kind and need else None          # of the needed samples, how many the geometry alone decided
        out["links"][lid] = dict(n=n, k_fail=int(f.sum()), verdict=intervals.verdict(int(f.sum()), n), method=r["method"],
                                 frac_median=float(np.median(r["frac"])), frac_p10=float(np.percentile(r["frac"], 10)),
                                 margin_db_median=float(np.nanmedian(r["margin_db"])) if np.any(np.isfinite(r["margin_db"])) else None,
                                 margin_kind=r.get("margin_kind"), frac_beyond_horizon=bad if kind == "beyond_horizon" else None,
                                 frac_out_of_range=bad if kind == "out_of_range" else None,
                                 distance_km_median=float(np.nanmedian(r["dist_m"])) / 1e3 if np.any(np.isfinite(r.get("dist_m", np.nan))) else None,
                                 need_count_median=nc, granularity_ok=None if nc is None else nc > 0 and (rf >= 1.0 or 1.0 / nc <= 1.0 - rf + 1e-12),
                                 sensitivity=sens)
    tests = [e["sensitivity"] for k in ("vehicles", "links") for e in out[k].values() if e["sensitivity"]["noise_floor"] is not None]  # a permutation test each
    for t in tests:
        if t["case"] == "ranked":
            t["text"] = (t["text"].rstrip(".") + f" (one in twenty unrelated outcomes would also clear it, and the report makes {len(tests)} such "
                         f"test{'s' if len(tests) != 1 else ''}).")
    return out


def _requantile(new: dict[str, Any], old: dict[str, Any], x: NDArray[Any]) -> NDArray[Any]:
    """Values of marginal `new` at the quantiles that `x` has under marginal `old`."""
    return np.asarray(sampling.marginal(new).ppf(sampling.marginal(old).cdf(np.asarray(x, float))), float)


def _speed(r: dict[str, Any], platform: str) -> dict[str, Any]:
    """USV speed against wind per member: mean speed over ground (path length / time since deploy), the mean wind along the track at 10 m and at
    the anemometer height, and the ratios; `calibration_ratio` is Chiodi et al.'s mean SOG / wind (at the anemometer height) the VPP bias is
    calibrated to, in a scenario without current, in uniform wind, sailing to a station (usv.mean_sog), which the mission is not."""
    sog, u10, wa = (np.asarray(r[k], float) for k in ("sog_ms", "u10_ms", "wind_anem_ms"))
    P = usv.load_platform(platform)
    stw = {} if "stw_ms" not in r else dict(stw_ms=np.asarray(r["stw_ms"], float).tolist(), stw_ms_median=float(np.median(r["stw_ms"])))   # an old run: none
    return dict(**stw, sog_ms=sog.tolist(), u10_ms=u10.tolist(), wind_anem_ms=wa.tolist(), ratio=(sog / u10).tolist(), ratio_anem=(sog / wa).tolist(),
                sog_ms_median=float(np.median(sog)), u10_ms_median=float(np.median(u10)), ratio_median=float(np.median(sog / u10)),
                ratio_anem_median=float(np.median(sog / wa)), calibration_ratio=float(P["chiodi_mean_sog_ms"] / P["chiodi_mean_wind_ms"]))


BRIEF_PRIOR = "usv_vpp_bias_brief"


def sensitivity_case(mission: dict[str, Any], env: Any, prior: str = BRIEF_PRIOR, n: int = 32, fitted: dict[str, Any] | None = None,
                     scales: dict[str, Any] | None = None, X: dict[str, NDArray[Any]] | None = None) -> dict[str, list[dict[str, Any]]]:
    """The USV ensemble again with `usv_vpp_bias` drawn from perturbations.yaml's `prior` instead (default: the brief's literal -30 to -35 %,
    which `priors_for` never samples). Same seed, members 0..n-1 as one batch, the USV vehicles only; -> {vehicle id: [dict(case, k_fail, n,
    verdict, note)]}, the shape of report.SENSITIVITY. With `X` (the run's own hypercube, `res["X"]`; n is then its length) the case is paired:
    every column stays as the run drew it, and only `usv_vpp_bias` is replaced, by the new prior's value at the same quantile, so the members
    that flip are the effect of the prior alone. Without it the case draws its own n-point hypercube (a different sample from the run's)."""
    pri, marg = priors_for(mission, fitted)
    new = sampling.to_marginals(pri, [prior])[prior]
    usvs = [v for v in mission["vehicles"] if _classes(mission)[v["id"]] == "usv"]
    if X is not None:
        n = len(X["usv_vpp_bias"])
        X = dict({k: np.asarray(x, float) for k, x in X.items() if k in marg}, usv_vpp_bias=_requantile(new, marg["usv_vpp_bias"], X["usv_vpp_bias"]))
    marg["usv_vpp_bias"] = new
    b = run_batch(dict(mission, vehicles=usvs, links=[]), env, list(range(n)), int(mission["seed"]), pri, marg, scales, X)
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


def task_counts(mission: dict[str, Any]) -> dict[str, int]:
    """{vehicle id: the tasks one batch makes of it}: 1 for a glider or USV, one per sortie for a UAS (at least 1: its setup still runs)."""
    t0, T = utc(mission["window"]["start"]).timestamp(), utc(mission["window"]["end"]).timestamp()
    cls = _classes(mission)
    return {v["id"]: max(1, len(_uas_setup(v, uas.load_platform(v["platform"]), mission, t0, T)[2])) if cls[v["id"]] == "uas" else 1
            for v in mission["vehicles"]}


def wave(n: int, batch: int, n_min: int, n_max: int, at_once: int) -> int:
    """How many batches to run at once with n members done: those n_min still needs (the stopping rule cannot stop before it), or `at_once`
    (budget.batches_at_once: as many as keep the workers busy), never past n_max and at least one."""
    left = -(-(n_max - n) // batch)
    return max(1, min(left, max(-(-(n_min - n) // batch), at_once)))


def run(mission: dict[str, Any], env: Any, plan: dict[str, Any], ledger: Ledger | None = None, log: Callable[[str], None] = print,
        scales: dict[str, Any] | None = None, fitted: dict[str, Any] | None = None) -> dict[str, Any]:
    pri, marg = priors_for(mission, fitted)
    names = list(marg)
    seed = int(mission["seed"])
    batch, n_max, n_min = plan["batch"], plan["n_max"], plan["n_min"]
    batches: list[dict[str, Any]] = []
    done = False
    n = 0

    def go(members: list[int]) -> dict[str, Any]:
        return run_batch(mission, env, members, seed, pri, marg, scales)
    with par.Pool(par.workers()), cf.ThreadPoolExecutor(par.width()) as threads:
        if par.width() > 1:
            env = par.adopt(env)                                          # the pipeline's is adopted already: then this costs nothing
        at_once = budget.batches_at_once(dict(plan, workers=par.width(), tasks=plan.get("tasks") or task_counts(mission)))
        while not done:
            k = wave(n, batch, n_min, n_max, at_once)
            blocks = [list(range(n + j * batch, n + (j + 1) * batch)) for j in range(k)]
            for b in (threads.map(go, blocks) if par.width() > 1 else map(go, blocks)):   # in member order; one worker: one batch at a time
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
                if done:                                                          # a batch run ahead of the stop is dropped, as if never run
                    break
    n_fill = sum(r.get("hs_filled", 0) for r in (*res["vehicles"].values(), *res["links"].values()))
    if ledger is not None and n_fill:
        ledger.note(f"{n_fill} non-finite wave-height samples (UMWM sea mask) on the UAS and RF link tracks were replaced by the same member's last finite Hs "
                    "(next one at the start); Hs 0 would be a glass-calm sea, the deepest two-ray null")
    if ledger is not None and (n_off := max((r.get("hours_dropped", 0) for r in res["vehicles"].values()), default=0)):
        ledger.note(f"{n_off} hourly steps of the UAS gust-front forcing lie outside the ingested time span (a sortie within an hour of the window's "
                    "start or end) and carry no events: rain is not known there")
    summ = summarize(res, names, mission, intervals.n_certify())
    return dict(res=res, summary=summ, names=names, priors={k: marg[k] for k in names}, n=len(res["U"]),
                certify=len(res["U"]) >= intervals.n_certify(), n_certify=intervals.n_certify(),
                t0=dt.datetime.fromtimestamp(utc(mission["window"]["start"]).timestamp(), dt.timezone.utc).isoformat())


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
