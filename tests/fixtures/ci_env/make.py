"""A synthetic, analytic CAFE_DATA tree for CI and for the environment tests: no orca, no HYCOM, no network.

    python -m tests.fixtures.ci_env.make DIR [MISSION]      # default MISSION: missions/ci_fixture.yaml
    make(DIR)                                              # from a test; returns a namespace of paths

The mission file decides the box, the pad and the window (36 h, hourly); everything else is a closed-form function of
(lon, lat, t) defined in this file, so a test can compare what GriddedEnv returns with the exact value. Nothing is random
except the TAO sensor noise (fixed seed). Output, in exactly the layout the real ingest writes:

    cache/<mission>/orca/{wrf.zarr, wrf3d.zarr, umwm.zarr, umwmspec.zarr, manifest.json}   cafe.pm.env.orca.assemble
    cache/<mission>/derived.zarr                                                              cafe.pm.env.surface.build
    ocean/gofs_<mission>.zarr                                                                 cafe.pm.env.hycom.write_store
    bathy/gebco2026_<s>_<n>_<w>_<e>.npz                                                       a bathy.fetch_gebco cache
    tao/manifest.json + <mooring>/OS_*.nc                                                     what tao.load_tao reads

Fields (lon in degrees east 0..360, lat in degrees north, t in seconds since 1970; x = lon - 195):
- Wind10 (earth = grid relative, the grid is Mercator): trade winds from the east, u = -5 + 0.4 x + 0.1 lat + 0.4 d(t), v = -0.5 lat +
  0.05 x - 0.3 d(t), d = cos(2 pi (local solar hour - 4) / 24), the early-morning maximum. The wave direction toward is atan2(v, u),
  which sits on the +-pi branch cut of the UMWM angle along the equator.
- Rain: a Gaussian footprint (sigma 1 degree) centred on the north-east corner (196.5E, 1.5N), 30 mm in three hours from 2023-03-01
  23Z, accumulated in RAINNC (70 %) and RAINC (30 %) on top of a constant base, as WRF does. Peak rate 10 mm/h.
- Waves: JONSWAP fetch-limited growth (Hasselmann et al. 1973, eqs. 4.1-4.2) with fetch 450 km at 197E growing 90 km per degree
  westward: Hs = 1.6e-3 U sqrt(F / g), f_p = 3.5 (g / U) (g F / U^2)^-0.33. The spectrum is JONSWAP (gamma 3.3) scaled to Hs on the
  discrete bins, times cos^12 spreading downwind. mwd is dwd + 0.1 rad. The restart spectra are the same spectrum written as
  F(th, f) on the wavenumber plane every 6 h, so hs_from_restart(F) equals swh at those points and times.
- Ocean: T = 4.5 + 23.9 * (1 - tanh((z - 140) / 45)) / 2 - 0.15 lat + 0.1 x (in situ, degC), S = 34.55 + 0.75 exp(-((z - 120) / 160)^2) +
  0.05 x - 0.1 lat, u = (-0.5 exp(-z / 40) + exp(-((z - 100) / 40)^2)) exp(-(lat / 1.5)^2) + 0.02 days since 2023-03-01 18Z,
  v = 0.04 lat exp(-z / 150), surf_el = 0.3 + 0.05 lat; z is depth in metres, positive down. rho and c come from the real TEOS-10 writer.
- Land: an atoll at (196.8125E, 1.8125S), radius 0.15 degree: UMWM seamask 0, WRF LANDMASK 1, an all-NaN ocean column, a wet-to-100-m
  neighbour column, and positive elevation in the bathymetry. Seafloor 5000 + 50 x + 80 lat metres elsewhere.
"""
import datetime as dt, hashlib, json, pathlib, shutil, sys, types

import numpy as np

from cafe.pm import stage1
from cafe.pm.config import env_sigmas, load_mission, utc
from cafe.pm.env import hycom, orca, remote, tao

ROOT = pathlib.Path(__file__).resolve().parents[3]
MISSION = ROOT / "missions" / "ci_fixture.yaml"
MARKER = ".ci_env_fixture"
G = 9.81
DX = 0.125                                         # grid step [deg], exact in float32 (12 km is 0.108)
LON0 = 195.0
T_REF = utc("2023-03-01T18:00:00Z").timestamp()
ATOLL = (196.8125, -1.8125, 0.15)                  # lon, lat, radius [deg]
RAIN_CENTER, RAIN_SIGMA, RAIN_MM = (196.5, 1.5), 1.0, 30.0
RAIN_T0, RAIN_S = utc("2023-03-01T23:00:00Z").timestamp(), 3 * 3600.0
RAIN_BASE = dict(RAINNC=40.0, RAINC=6.0)           # mm already accumulated before the window
RAIN_SPLIT = dict(RAINNC=0.7, RAINC=0.3)
FETCH0_KM, FETCH_SLOPE_KM, FETCH_LON = 450.0, 90.0, 197.0
Z3 = np.array([21.0, 60.0, 94.0, 129.0, 168.0, 212.0, 262.0, 318.0])        # the first 8 WRF mass-level heights [m]
Z0_3D = 2e-4                                       # roughness of the 3-D wind profile (same as the neutral profile in GriddedEnv)
FREQ = 0.0313 * (2.0 / 0.0313) ** (np.arange(37) / 36.0)                      # UMWM frequency(f), 0.0313-2.0 Hz log-spaced
THETA = -np.pi + 2 * np.pi * (np.arange(32) + 0.5) / 32                      # UMWM theta(th), math radians toward
DF = FREQ * np.gradient(np.log(FREQ))
DTH = 2 * np.pi / THETA.size
SPREAD_S = 6                                       # cos^(2 s) spreading
OLAT, OLON = np.arange(-2.5, 2.5001, 0.25), np.arange(192.5, 197.5001, 0.25)
ODEPTH = np.array([0.0, 5, 10, 20, 30, 40, 50, 60, 80, 100, 120, 150, 200, 300, 500, 700, 1000])
SHALLOW_LEVELS = 10                                # the neighbour column of the atoll is wet at the first 10 levels (to 100 m)
BATHY_STEP = 0.05
MOORINGS = {"T0N165W": ("WIND", "SST", "AIRT", "RH"), "T2S165W": ("WIND", "SST")}
NOISE_SEED = 20230301


# ---------------------------------------------------------------------------------------------------------------- atmosphere

def lst(lon, t):
    """Local solar hour 0..24 at east longitude `lon` for epoch seconds `t`."""
    return (np.asarray(t, float) / 3600.0 + np.asarray(lon, float) / 15.0) % 24.0


def _diurnal(lon, t, peak_hour):
    return np.cos(2 * np.pi * (lst(lon, t) - peak_hour) / 24.0)


def wind10(lon, lat, t):
    """(u, v) 10 m wind [m/s], east and north, earth-relative."""
    lon, lat = np.asarray(lon, float), np.asarray(lat, float)
    x, d = lon - LON0, _diurnal(lon, t, 4.0)
    return -5.0 + 0.40 * x + 0.10 * lat + 0.40 * d, -0.50 * lat + 0.05 * x - 0.30 * d


def wind3d(lon, lat, t, z):
    """(u, v) at height z [m] above the first mass level: the neutral log profile through the 10 m wind."""
    u, v = wind10(lon, lat, t)
    r = np.log(np.asarray(z, float) / Z0_3D) / np.log(10.0 / Z0_3D)
    return u * r, v * r


def drag_coefficient(speed):
    """Large & Pond (1981) neutral 10 m drag coefficient, used for both WRF UST and UMWM ust/cd."""
    return (0.8 + 0.065 * np.asarray(speed, float)) * 1e-3


def rain_footprint(lon, lat):
    """Rain accumulated at a point over the whole burst [mm]."""
    d2 = (np.asarray(lon, float) - RAIN_CENTER[0]) ** 2 + (np.asarray(lat, float) - RAIN_CENTER[1]) ** 2
    return RAIN_MM * np.exp(-d2 / (2 * RAIN_SIGMA ** 2))


def rain_ramp(t):
    return np.clip((np.asarray(t, float) - RAIN_T0) / RAIN_S, 0.0, 1.0)


def rain_accum(lon, lat, t, name="RAINNC"):
    """WRF's accumulated rain `name` [mm] at epoch time t."""
    return RAIN_BASE[name] + RAIN_SPLIT[name] * rain_footprint(lon, lat) * rain_ramp(t)


def rain_rate(lon, lat, t):
    """What GriddedEnv derives: the backward difference of RAINNC + RAINC over the previous hour [mm/h] (0 at the first hour)."""
    return (rain_footprint(lon, lat) * (rain_ramp(t) - rain_ramp(np.asarray(t, float) - 3600.0))).astype(float)


def _cloud(lon, lat, t):
    """0..1: how much the rain burst darkens, cools and moistens a point (a triangle in time, the rain footprint in space)."""
    bump = np.clip(1.0 - np.abs(np.asarray(t, float) - RAIN_T0 - 0.5 * RAIN_S) / (4 * 3600.0), 0.0, 1.0)
    return rain_footprint(lon, lat) / RAIN_MM * bump


def is_land(lon, lat):
    return np.hypot(np.asarray(lon, float) - ATOLL[0], np.asarray(lat, float) - ATOLL[1]) < ATOLL[2]


def wrf2d(lon, lat, t):
    """The sixteen 2-D WRF fields of orca.WRF2D at epoch time t on broadcast lon/lat arrays."""
    lon, lat = np.broadcast_arrays(np.asarray(lon, float), np.asarray(lat, float))
    u, v = wind10(lon, lat, t)
    sp, h, c = np.hypot(u, v), lst(lon, t), _cloud(lon, lat, t)
    dec = np.radians(-7.5)                                          # solar declination in early March
    cosz = np.sin(np.radians(lat)) * np.sin(dec) + np.cos(np.radians(lat)) * np.cos(dec) * np.cos(2 * np.pi * (h - 12.0) / 24.0)
    sst = 273.15 + ocean(0.0, lat, lon, T_REF)[0]                  # frozen: WRF runs with SST_UPDATE = 0
    lh = 90.0 + 8.0 * sp
    out = dict(U10=u, V10=v, T2=299.65 + 0.4 * _diurnal(lon, t, 14.0) - 0.1 * lat - 0.05 * (lon - LON0) - 1.0 * c,
               Q2=0.0170 - 0.0004 * lat + 0.00005 * (lon - LON0) + 0.0005 * c,
               PSFC=101000.0 + 40.0 * np.cos(4 * np.pi * (h - 10.0) / 24.0) - 10.0 * lat, SST=sst, TSK=sst, HFX=8.0 + 0.8 * sp, LH=lh,
               QFX=lh / 2.5e6, RAINNC=rain_accum(lon, lat, t, "RAINNC"), RAINC=rain_accum(lon, lat, t, "RAINC"),
               SWDOWN=1000.0 * np.maximum(cosz, 0.0) * (1.0 - 0.5 * c), GLW=410.0 + 20.0 * c,
               UST=np.sqrt(drag_coefficient(sp)) * sp, PBLH=600.0 + 120.0 * _diurnal(lon, t, 14.0))
    return {k: np.asarray(out[k]).astype("f4") for k in orca.WRF2D}


# ---------------------------------------------------------------------------------------------------------------- waves

def sea_state(lon, lat, t):
    """Fetch-limited JONSWAP sea under the local wind: dict(U, hs, fp, tp, theta [math rad toward, = downwind])."""
    u, v = wind10(lon, lat, t)
    sp = np.hypot(u, v)
    fetch = 1e3 * (FETCH0_KM + FETCH_SLOPE_KM * (FETCH_LON - np.asarray(lon, float)))
    hs = 1.6e-3 * sp * np.sqrt(fetch / G)
    fp = 3.5 * (G / sp) * (G * fetch / sp ** 2) ** -0.33
    return dict(U=sp, hs=hs, fp=fp, tp=1.0 / fp, theta=np.arctan2(v, u))


def jonswap(hs, fp, gamma=3.3):
    """E(f) [m2/Hz] on FREQ, shape (..., 37), scaled so that 4 sqrt(sum E df) = hs on the discrete bins."""
    fp = np.asarray(fp, float)[..., None]
    sig = np.where(FREQ <= fp, 0.07, 0.09)
    s = FREQ ** -5 * np.exp(-1.25 * (fp / FREQ) ** 4) * gamma ** np.exp(-((FREQ - fp) ** 2) / (2 * sig ** 2 * fp ** 2))
    return s * (np.asarray(hs, float)[..., None] / 4.0) ** 2 / np.sum(s * DF, -1, keepdims=True)


def spreading(theta_m):
    """D(theta) on THETA, shape (..., 32): cos^(2 SPREAD_S) around theta_m [math rad], sum D dtheta = 1."""
    d = np.cos(0.5 * (THETA - np.asarray(theta_m, float)[..., None])) ** (2 * SPREAD_S)
    return d / (np.sum(d, -1, keepdims=True) * DTH)


def spectral_moments(e1):
    """From E(f): m0, T01 = m0 / m1, mean square slope (2 pi)^4 m4 / g^2, and the Stokes drift speed at the surface
    16 pi^3 / g sum f^3 E df (all directions summed)."""
    m0, m1 = np.sum(e1 * DF, -1), np.sum(FREQ * e1 * DF, -1)
    return dict(m0=m0, tm=m0 / m1, mss=(2 * np.pi) ** 4 / G ** 2 * np.sum(FREQ ** 4 * e1 * DF, -1),
                stokes=16 * np.pi ** 3 / G * np.sum(FREQ ** 3 * e1 * DF, -1))


def umwm2d(lon, lat, t):
    """The fourteen 2-D UMWM fields of orca.UMWM2D at epoch time t (NaN on land is applied by the caller)."""
    ss = sea_state(lon, lat, t)
    mo = spectral_moments(jonswap(ss["hs"], ss["fp"]))
    cd = drag_coefficient(ss["U"])
    out = dict(swh=ss["hs"], mwp=mo["tm"], mwd=ss["theta"] + 0.1, dwp=ss["tp"], dwd=ss["theta"], mss=mo["mss"], wspd=ss["U"],
               wdir=ss["theta"], ust=np.sqrt(cd) * ss["U"], cd=cd, dcp=G * ss["tp"] / (2 * np.pi), dcg=G * ss["tp"] / (4 * np.pi),
               mwl=G * mo["tm"] ** 2 / (2 * np.pi), dwl=G * ss["tp"] ** 2 / (2 * np.pi))
    return {k: np.asarray(out[k]).astype("f4") for k in orca.UMWM2D}


def restart_fields(lon, lat, t):
    """UMWM restart F(th, f) [m4/rad] and wavenumber k(f) for K points: shapes (K, 32, 37) and (K, 37), float32. E = F k dk/df,
    so F = E / (k dk/df) with the file's own k(f) (deep water), the exact inverse of waves.spectrum_from_restart."""
    ss = sea_state(lon, lat, t)
    e = spreading(ss["theta"])[:, :, None] * jonswap(ss["hs"], ss["fp"])[:, None, :]
    k = np.broadcast_to((2 * np.pi * FREQ) ** 2 / G, (e.shape[0], FREQ.size))
    dkdf = k * np.gradient(np.log(k), axis=-1) / DF
    return (e / (k * dkdf)[:, None, :]).astype("f4"), k.astype("f4")


def stokes_surface(lon, lat, t):
    """(east, north) Stokes surface drift of the fixture spectrum, 16 pi^3 / g int f^3 E d df dtheta."""
    ss = sea_state(lon, lat, t)
    s = spectral_moments(jonswap(ss["hs"], ss["fp"]))["stokes"]
    d = spreading(ss["theta"])
    return s * np.sum(d * np.cos(THETA), -1) * DTH, s * np.sum(d * np.sin(THETA), -1) * DTH


# ---------------------------------------------------------------------------------------------------------------- ocean

def ocean(z, lat, lon, t):
    """(T in situ [degC], S [psu], u, v [m/s]) at depth z [m, positive down]."""
    z, lat, lon = (np.asarray(a, float) for a in (z, lat, lon))
    x = lon - LON0
    temp = 4.5 + 23.9 * 0.5 * (1.0 - np.tanh((z - 140.0) / 45.0)) - 0.15 * lat + 0.1 * x
    sal = 34.55 + 0.75 * np.exp(-(((z - 120.0) / 160.0) ** 2)) + 0.05 * x - 0.1 * lat
    u = (-0.5 * np.exp(-z / 40.0) + np.exp(-(((z - 100.0) / 40.0) ** 2))) * np.exp(-((lat / 1.5) ** 2)) + 0.02 * (np.asarray(t, float) - T_REF) / 86400.0
    v = 0.04 * lat * np.exp(-z / 150.0)
    return temp, sal, u, v


def surf_el(lat):
    return 0.3 + 0.05 * np.asarray(lat, float)


def seafloor(lon, lat):
    """Water depth [m, positive down]; negative on the atoll (elevation positive)."""
    lon, lat = np.asarray(lon, float), np.asarray(lat, float)
    r = np.hypot(lon - ATOLL[0], lat - ATOLL[1])
    return np.where(r < ATOLL[2], -2.0, (5000.0 + 50.0 * (lon - LON0) + 80.0 * lat) * np.clip((r - ATOLL[2]) / 0.5, 0.04, 1.0))


# ---------------------------------------------------------------------------------------------------------------- writers

def _hours(m):
    t0, t1 = utc(m["window"]["start"]).replace(tzinfo=None), utc(m["window"]["end"]).replace(tzinfo=None)
    return orca.hours(t0, t1)


def _epoch(t):
    return t.replace(tzinfo=dt.timezone.utc).timestamp()


def _mission_box(m):
    """(lon_min, lon_max, lat_min, lat_max) the pipeline's ingest asks orca for: the mission box plus its pad."""
    b = m["box"]
    p = b.get("pad_deg", 0.0)
    return b["lon_min"] - p, b["lon_max"] + p, b["lat_min"] - p, b["lat_max"] + p


def _grids(m):
    """wg, ug: what orca.wrf_grid / orca.umwm_grid return for the box, cut from a parent grid of step DX with box_index."""
    lat = np.arange(-10.0, 10.0 + 1e-9, DX)
    lon360 = np.arange(170.0, 230.0 + 1e-9, DX)
    lon180 = np.where(lon360 >= 180.0, lon360 - 360.0, lon360)                  # WRF stores -180..180
    j0, j1, i0, i1 = orca.box_index(lat, lon180, _mission_box(m))
    la, lo = np.meshgrid(lat[j0:j1], lon360[i0:i1], indexing="ij")
    land = is_land(lo, la)
    static = dict(XLAT=la.astype("f4"), XLONG=(lo - 360.0 * (lo >= 180.0)).astype("f4"), LANDMASK=land.astype("f4"), HGT=np.zeros(la.shape, "f4"),
                  COSALPHA=np.ones(la.shape, "f4"), SINALPHA=np.zeros(la.shape, "f4"))
    attrs = orca.schema("wrfout")["global_attrs"]
    wg = dict(j=(j0, j1), i=(i0, i1), attrs=attrs, **static)
    depth = np.where(land, 0.0, np.maximum(seafloor(lo, la), 0.0))
    ug = dict(j=(j0, j1), i=(i0, i1), lat=la, lon=lo, seamask=(~land).astype("i4"), depth=depth.astype("f4"))
    return wg, ug


def _spec_points(ug):
    """The restart sea points kept by orca.spec_points: every SPEC_STRIDE-th node of the UMWM box in each direction (x ascending)."""
    gj, gi = np.meshgrid(np.arange(ug["lat"].shape[0]), np.arange(ug["lat"].shape[1]), indexing="ij")
    j, i = np.nonzero((gj % orca.SPEC_STRIDE == 0) & (gi % orca.SPEC_STRIDE == 0) & (ug["seamask"] > 0))
    lon = ug["lon"][j, i]
    return dict(x=np.arange(len(j)), lon=lon - 360.0 * (lon >= 180.0), lat=ug["lat"][j, i], f=FREQ, th=THETA)


def _hours3d(m, ts):
    """The hours orca.ingest reads in 3-D: the hour of every UAS sortie launch and the next one (pipeline._sortie_hours)."""
    t0, t1 = _epoch(ts[0]), _epoch(ts[-1])
    cls = stage1._classes(m)
    out = set()
    for v in m["vehicles"]:
        if cls[v["id"]] == "uas":
            for t in stage1.launch_times(v["sorties"], m["ship"]["lon"], t0, t1, 60.0 * v["sorties"].get("duration_min", 20)):
                h = dt.datetime.fromtimestamp(np.floor(t / 3600) * 3600, dt.timezone.utc).replace(tzinfo=None)
                out |= {h, h + dt.timedelta(hours=1)}
    return sorted(out)


def write_orca(out, m):
    """orca/ with the per-hour npz files orca.ingest would have cached, then the real orca.assemble."""
    out = pathlib.Path(out)
    (out / "hours").mkdir(parents=True)
    ts = _hours(m)
    wg, ug = _grids(m)
    la, lo = wg["XLAT"].astype(float), wg["XLONG"].astype(float) % 360.0
    land = ug["seamask"] == 0
    h3 = _hours3d(m, ts)
    pts = _spec_points(ug)
    for t in ts:
        s, te = orca.stamp(t), _epoch(t)
        w = dict(wrf2d(lo, la, te), _bytes=np.int64(0))
        if t in h3:
            u, v = wind3d(lo[None], la[None], te, Z3[:, None, None])
            w.update(U3=u.astype("f4"), V3=v.astype("f4"), Z3=np.broadcast_to(Z3[:, None, None], u.shape).astype("f4"),
                     TH3=(299.4 + 0.0005 * Z3[:, None, None] - 0.1 * la[None]).astype("f4"))
        np.savez(out / "hours" / f"wrf_{s}.npz", **w)
        np.savez(out / "hours" / f"umwm_{s}.npz", **{k: np.where(land, np.nan, a).astype("f4") for k, a in umwm2d(ug["lon"], ug["lat"], te).items()})
        if t.hour % 6 == 0:
            F, K = restart_fields(orca.lon360(pts["lon"]), pts["lat"], te)
            np.savez(out / "hours" / f"spec_{s}.npz", F=F, k=K)
    man = orca.assemble(out, ts, wg, ug, pts, [orca.stamp(t) for t in h3])
    shutil.rmtree(out / "hours")                                    # per-hour parts are only the ingest's resume cache
    return man


def write_ocean(path, m):
    """ocean/gofs_<mission>.zarr through hycom.write_store (TEOS-10 rho and c are added by the real writer)."""
    t0, t1 = _epoch(_hours(m)[0]), _epoch(_hours(m)[-1])
    steps = np.arange(np.floor(t0 / hycom.STEP_S) * hycom.STEP_S, np.ceil(t1 / hycom.STEP_S) * hycom.STEP_S + 1, hycom.STEP_S)
    import xarray as xr
    jl, il = int(np.argmin(np.abs(OLAT - ATOLL[1]))), int(np.argmin(np.abs(OLON - ATOLL[0])))      # nearest ocean node to the atoll

    def one(t):
        z, la, lo = ODEPTH[:, None, None], OLAT[None, :, None], OLON[None, None, :]
        T, S, U, V = (np.broadcast_to(a, (ODEPTH.size, OLAT.size, OLON.size)).copy() for a in ocean(z, la, lo, t))
        e = np.broadcast_to(surf_el(OLAT)[:, None], (OLAT.size, OLON.size)).copy()
        for a in (T, S, U, V):
            a[:, jl, il] = np.nan
            a[SHALLOW_LEVELS:, jl, il + 1] = np.nan
        e[jl, il] = np.nan
        ds = xr.Dataset({k: (("time", "depth", "lat", "lon"), a[None]) for k, a in (("water_temp", T), ("salinity", S), ("water_u", U), ("water_v", V))},
                        coords=dict(time=("time", [t]), depth=("depth", ODEPTH), lat=("lat", OLAT), lon=("lon", OLON)))
        ds["surf_el"] = (("time", "lat", "lon"), e[None])
        return hycom._std(ds)
    attrs = dict(source="synthetic GOFS 3.1 subset (tests/fixtures/ci_env/make.py)", manifest_sha256=hashlib.sha256(b"ci_env").hexdigest(),
                 box=json.dumps([float(OLAT[0]), float(OLAT[-1]), float(OLON[0]), float(OLON[-1])]))
    return hycom.write_store((one(t) for t in steps), path, "in_situ", attrs)


def write_bathy(directory, m):
    """A fetch_gebco-format cache for the box ocean() asks bathy.choose for, so no download is tried. The doi field says it is synthetic."""
    b = m["box"]
    p = b.get("pad_deg", 0.0)
    s, n, w, e = hycom.box360((b["lat_min"] - p, b["lat_max"] + p, b["lon_min"] - p, b["lon_max"] + p))
    lon = np.arange(w - 0.25, e + 0.25 + 1e-9, BATHY_STEP)
    lat = np.arange(s - 0.25, n + 0.25 + 1e-9, BATHY_STEP)
    elev = np.ascontiguousarray(np.round(-seafloor(lon[None, :], lat[:, None])).astype("<i2"))
    attrs = dict(url="synthetic", remote_bytes=0, title="synthetic ci_env bathymetry", doi="synthetic ci_env fixture, not GEBCO", box=[s, n, w, e],
                 resolution_deg=BATHY_STEP, sha256=hashlib.sha256(elev.tobytes()).hexdigest(), bytes_read=0)
    path = pathlib.Path(directory) / f"gebco2026_{s:g}_{n:g}_{w:g}_{e:g}.npz"
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, lon=lon, lat=lat, elevation=elev, attrs=json.dumps(attrs))
    return path


def write_tao(directory, m):
    """tao/manifest.json and OceanSITES-style 10-minute files for two moorings, as tao.load_tao reads them: the wind is the fixture wind
    scaled to the 4 m sensor height, 3 % low with 0.25 m/s of noise, a few samples flagged bad; SST at 1 m; air temperature and humidity."""
    import xarray as xr
    d = pathlib.Path(directory)
    rng = np.random.default_rng(NOISE_SEED)
    t0, t1 = _epoch(_hours(m)[0]) - 3600.0, _epoch(_hours(m)[-1]) + 3600.0
    t = np.arange(t0, t1 + 1, 600.0)
    tt = (t * 1e9).astype("int64").astype("datetime64[ns]")
    man = dict(source="synthetic ci_env fixture", box=list(hycom.box360((-2.0, 2.0, 193.0, 197.0))), t0=t0, t1=t1, files={}, selected={}, positions={},
               waves=dict(checked=len(MOORINGS), matches=[]))
    for name, variables in MOORINGS.items():
        lat, lon = tao.mooring_position(name)
        u, v = wind10(lon, lat, t)
        lift = np.log(4.0 / 1e-4) / np.log(10.0 / 1e-4)
        u4, v4 = 0.97 * lift * u + rng.normal(0, 0.25, t.size), 0.97 * lift * v + rng.normal(0, 0.25, t.size)
        qc = np.ones(t.size, "i1")
        qc[::97] = 4
        u4[::97] = 99.0
        c = _cloud(lon, lat, t)
        sst = ocean(1.0, lat, lon, t)[0] + rng.normal(0, 0.05, t.size)
        cols = dict(WIND=(dict(UWND=u4, VWND=v4), "WSPD", "HEIGHT", 4.0), SST=(dict(SST=sst), "SST", "DEPTH", 1.0),
                    AIRT=(dict(AIRT=299.65 + 0.4 * _diurnal(lon, t, 14.0) - 1.0 * c - 273.15), "AIRT", "HEIGHT", 3.0),
                    RH=(dict(RELH=80.0 + 5.0 * c + rng.normal(0, 0.5, t.size)), "RELH", "HEIGHT", 3.0))
        man["selected"][name], man["positions"][name] = {}, [lat, lon]
        for var in variables:
            vals, qcof, hname, h = cols[var]
            fn = f"OS_{name}_DEP0001-20230101_D_{var}_10min.nc"
            (d / name).mkdir(parents=True, exist_ok=True)
            data = {**{k: ("TIME", a.astype("f4")) for k, a in vals.items()}, qcof + "_QC": ("TIME", qc), hname: ((), np.float32(h))}
            ds = xr.Dataset(data, coords=dict(TIME=("TIME", tt)))
            ds.to_netcdf(d / name / fn)
            key = f"{name}/{fn}"
            man["files"][key] = dict(mooring=name, var=var, mode="D", deployment="DEP0001", url="synthetic", bytes=(d / key).stat().st_size,
                                     sha256=remote.sha256(d / key), time_start=t0, time_end=t1)
            man["selected"][name][var] = key
    (d / "manifest.json").write_text(json.dumps(man, indent=1, sort_keys=True))
    return d / "manifest.json"


def make(target, mission=MISSION, log=lambda *a: None):
    """Write the whole tree under `target` and return a namespace(data, cache, mission, mission_path, ocean_store, hours, size_mb).
    `target` must be empty or carry the marker this function leaves, so a real CAFE_DATA is never overwritten."""
    from cafe.pm.env import surface
    from cafe.pm.env.environment import GriddedEnv
    target = pathlib.Path(target)
    if target.exists() and any(target.iterdir()) and not (target / MARKER).exists():
        raise ValueError(f"{target} is not empty and is not a ci_env fixture: refusing to write synthetic data into it")
    m = load_mission(mission)
    for sub in ("cache", "ocean", "bathy", "tao"):
        shutil.rmtree(target / sub, ignore_errors=True)
    target.mkdir(parents=True, exist_ok=True)
    (target / MARKER).write_text("synthetic data written by tests/fixtures/ci_env/make.py\n")
    cache = target / "cache" / m["name"]
    write_orca(cache / "orca", m)
    store = write_ocean(target / "ocean" / f"gofs_{m['name']}.zarr", m)
    write_bathy(target / "bathy", m)
    write_tao(target / "tao", m)
    surface.build(GriddedEnv(cache, env_sigmas()), cache, log=log)
    mb = sum(f.stat().st_size for f in target.rglob("*") if f.is_file()) / 1e6
    return types.SimpleNamespace(data=target, cache=cache, mission=m, mission_path=pathlib.Path(mission), ocean_store=store,
                                 hours=np.array([_epoch(t) for t in _hours(m)]), size_mb=mb)


if __name__ == "__main__":
    r = make(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else MISSION, log=print)
    print(f"ci_env fixture for {r.mission['name']}: {r.data} ({r.size_mb:.1f} MB)")
