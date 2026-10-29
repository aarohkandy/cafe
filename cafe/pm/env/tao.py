"""TAO/TRITON moorings inside the box: scripted download (cached, SHA-256 in a manifest), wind/SST series, and the
mooring-vs-model comparison that fits the wind prior (BRIEF 5.2 data validation).

    fetch_tao(box, t0, t1, out_dir)     -> manifest path; the 10-min WIND, SST, AIRT, RH files of every mooring in the box
    verify(out_dir)                     -> number of files whose SHA-256 matches the manifest (ValueError listing the ones that do not)
    load_tao(out_dir)                   -> {mooring: {lat, lon, wind, sst, airt, rh}} with QC-good samples only
    wind_to_10m(speed, z)               -> neutral wind at 10 m from a wind at height z (log profile), or COARE with `air`
    compare(wrf, tao)                   -> per mooring and pooled: speed bias/RMSE, vector RMSE, direction bias/RMSE, SST bias/RMSE
    waves_available(out_dir)            -> False (with a warning saying why) when no mooring in the box reports waves

Source: NDBC's THREDDS copy of the OceanSITES TAO/TRITON files, https://dods.ndbc.noaa.gov/thredds/catalog/oceansites/DATA/
(OS_<mooring>_<deployment>-<date>_<D|R>_<VAR>_<10min|hourly>.nc; D delayed-mode, R recovered/real-time). QC flags are those of the
OceanSITES Data Format Reference Manual: 1 good, 2 probably good, 3 potentially correctable, 5 value changed. Delayed-mode files carry
5 on every calibrated sample (checked on T0N165E WIND: 50863 of 51027 samples are 5), so D keeps {1, 2, 5}; real-time R winds are all 3
and are dropped, R temperatures and humidity keep {1, 2}. Found because the PMEL ERDDAP (pmelTao*) only serves daily means for
2023, tao_flux_absolute on data.pmel.noaa.gov ends in 2021-09, and PMEL's own data-delivery pages are a JavaScript form with no
file URL. The winds are 10-minute means at 4 m (HEIGHT), SST at 1 m depth. The files have no wave variables.

Height adjustment, method="log": the neutral logarithmic profile u(z) = (u*/kappa) ln(z/z0), kappa = 0.4, with the COARE 3.5
sea-state-free roughness z0 = alpha u*^2/g + 0.11 nu/u*, alpha = 0.0017 U10n - 0.005 (floored at 0, U10n capped at 19 m/s;
Edson et al. 2013, J. Phys. Oceanogr. 43, 1589; 0.11 nu/u* from Smith 1988, J. Geophys. Res. 93, 15467), nu = 1.5e-5 m2/s,
solved with u* and U10n by fixed point. It lifts the measured wind as if the air were neutral; the equatorial boundary layer
is usually unstable, so it overstates the 4 -> 10 m shear by 2-3 % at 6 m/s (measured against COARE, see receipts).
method="coare" uses cafe.pm.env.coare (imported only then) with the mooring's own air temperature, humidity and SST, which
includes stability; compare()'s default "auto" uses it for moorings that report all three and "log" for the rest.
"""
import datetime as dt, importlib, json, os, pathlib, re, warnings
import xml.etree.ElementTree as ET        # the catalogs come from NOAA over verified TLS; expat >= 2.4.1 is safe against entity expansion

import numpy as np
from numpy.typing import ArrayLike, NDArray

from typing import Any

from . import conventions as cv, remote
from .hycom import box360

BASE = "https://dods.ndbc.noaa.gov/thredds"
CATALOG = "/catalog/oceansites/DATA/"
FILES = "/fileServer/"
VARS = ("WIND", "SST", "AIRT", "RH")
# file code -> (NetCDF variables, the variable whose _QC applies). RELH is in percent although its units attribute says '1' (2023 means: 78-87)
NC = dict(WIND=(("UWND", "VWND"), "WSPD"), SST=(("SST",), "SST"), AIRT=(("AIRT",), "AIRT"), RH=(("RELH",), "RELH"))
WAVE_VARS = ("WAVE", "WAVES", "HS", "SWH", "WVHT", "HSIG", "WVPD", "WDIR_WAVE")
NS = {"c": "http://www.unidata.ucar.edu/namespaces/thredds/InvCatalog/v1.0", "x": "http://www.w3.org/1999/xlink"}
MOORING = re.compile(r"^T(\d+)([NS])(\d+)([EW])$")
FILE = re.compile(r"^OS_(?P<m>T\w+?)_(?P<dep>[A-Z]+\d+[A-Z]?)-(?P<date>\d{8})_(?P<mode>[DR])_(?P<var>[A-Z]+)_(?P<res>\w+)\.nc$")
GOOD = dict(D=(1, 2, 5), R=(1, 2))      # OceanSITES QC flags: 1 good, 2 probably good, 5 value changed (= calibrated, in delayed mode)
KAPPA, NU_AIR, G = 0.4, 1.5e-5, 9.80665
CH1, CH2, UMAX = 0.0017, -0.0050, 19.0                  # Edson et al. 2013 Charnock slope/intercept and the wind above which alpha stops growing
HALF_BIN_S, MIN_IN_BIN = 1800.0, 3
Arr = NDArray[np.floating[Any]]


def _get(url: str) -> bytes:
    with remote._open(url) as r:
        return r.read()


def _list(url: str) -> ET.Element:
    return ET.fromstring(_get(url))


def mooring_position(name: str) -> tuple[float, float]:
    """(lat, lon east in 0..360) from an OceanSITES TAO name such as T2S165E or T0N170W."""
    m = MOORING.match(name)
    if not m:
        raise ValueError(f"{name!r} is not a TAO/TRITON mooring name like T0N165E")
    lat, lon = int(m[1]) * (1 if m[2] == "N" else -1), int(m[3]) % 360
    return float(lat), float(lon if m[4] == "E" else (360 - lon) % 360)


def moorings(box: Any, base: str = BASE) -> list[tuple[str, float, float]]:
    """The TAO/TRITON moorings of the catalog that lie inside the box: [(name, lat, lon)], sorted."""
    s, n, w, e = box360(box)
    out: list[tuple[str, float, float]] = []
    for ref in _list(base + CATALOG + "catalog.xml").iter("{%s}catalogRef" % NS["c"]):
        name = ref.get("{%s}title" % NS["x"]) or ""
        if not MOORING.match(name):
            continue
        lat, lon = mooring_position(name)
        lon_w = lon + 360.0 if lon < w - 1e-9 else lon
        if s <= lat <= n and w <= lon_w <= e:
            out.append((name, lat, lon))
    return sorted(out)


def _files(name: str, base: str) -> list[dict[str, Any]]:
    """Dataset entries of one mooring's catalog that parse as OceanSITES TAO files: dicts of the FILE groups + file/url."""
    out: list[dict[str, Any]] = []
    for ds in _list(f"{base}{CATALOG}{name}/catalog.xml").iter("{%s}dataset" % NS["c"]):
        m = FILE.match(ds.get("name") or "")
        if m:
            out.append(dict(m.groupdict(), file=ds.get("name"), url=base + FILES + (ds.get("urlPath") or "")))
    return out


def _candidates(files: list[dict[str, Any]], t0: float, t1: float) -> list[dict[str, Any]]:
    """Files of the deployment in the water at t0 (latest start <= t0, and the ones within 10 days before it, which are its A/B
    twins) and every later deployment that starts before t1: the only ones that can overlap [t0, t1]."""

    def day(f: dict[str, Any]) -> float:
        return dt.datetime.strptime(f["date"], "%Y%m%d").replace(tzinfo=dt.timezone.utc).timestamp()

    before = [day(f) for f in files if day(f) <= t0]
    lo = (max(before) - 10 * 86400) if before else -np.inf
    return [f for f in files if lo <= day(f) <= t1]


def _coverage(path: Any) -> tuple[float, float]:
    """(first, last) TIME of a file as epoch seconds."""
    import xarray as xr
    with xr.open_dataset(path) as ds:
        t = ds.TIME.values.astype("datetime64[s]").astype("int64").astype("float64")
    return float(t[0]), float(t[-1])


def fetch_tao(box: Any, t0: Any, t1: Any, out_dir: Any, base: str = BASE, variables: tuple[str, ...] = VARS, res: str = "10min") -> pathlib.Path:
    """Download the `variables` files (resolution `res`) of every TAO/TRITON mooring in `box` whose deployment can overlap
    t0..t1 (epoch seconds, ISO strings or datetimes) into out_dir/<mooring>/, resumable (remote.download), hash every file,
    pick per mooring and variable the file with the most QC-good samples in the window (delayed-mode before real-time on a
    tie), look for wave variables, and write out_dir/manifest.json. Returns its path."""
    from .hycom import epoch
    t0, t1 = epoch(t0), epoch(t1)
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    mpath = out / "manifest.json"
    old = json.loads(mpath.read_text())["files"] if mpath.exists() else {}
    man: dict[str, Any] = dict(source=base + CATALOG, box=list(box360(box)), t0=t0, t1=t1, files={}, selected={}, waves=dict(checked=0, matches=[]))
    for name, lat, lon in moorings(box, base):
        listing = _files(name, base)
        man["waves"]["checked"] += len(listing)
        man["waves"]["matches"] += [f["file"] for f in listing if f["var"] in WAVE_VARS]
        for var in variables:
            best: tuple[tuple[int, bool], str] | None = None
            for f in (f for f in _candidates(listing, t0, t1) if f["var"] == var and f["res"] == res):
                key = f"{name}/{f['file']}"
                p = out / key
                p.parent.mkdir(exist_ok=True)
                remote.download(f["url"], p, old.get(key, {}).get("sha256"))
                a, b = _coverage(p)
                man["files"][key] = dict(mooring=name, var=var, mode=f["mode"], deployment=f["dep"], url=f["url"], bytes=p.stat().st_size,
                                         sha256=remote.sha256(p), time_start=a, time_end=b)
                score = (len(_series(p, var, f["mode"], t0, t1)["t"]), f["mode"] == "D")
                if score[0] and (best is None or score > best[0]):
                    best = (score, key)
            if best:
                man["selected"].setdefault(name, {})[var] = best[1]
        man["selected"].setdefault(name, {})
        man.setdefault("positions", {})[name] = [lat, lon]
    tmp = pathlib.Path(str(mpath) + ".tmp")
    tmp.write_text(json.dumps(man, indent=1, sort_keys=True))
    os.replace(tmp, mpath)
    return mpath


def verify(out_dir: Any) -> int:
    """Re-hash every file in out_dir/manifest.json. Returns how many matched; ValueError lists the missing/changed ones."""
    out = pathlib.Path(out_dir)
    man = json.loads((out / "manifest.json").read_text())
    bad = [k for k, r in man["files"].items() if not (out / k).exists() or remote.sha256(out / k) != r["sha256"]]
    if bad:
        raise ValueError(f"{len(bad)} of {len(man['files'])} TAO files differ from the manifest SHA-256 (or are missing): {bad[:5]}; "
                         "delete them and rerun fetch_tao")
    return len(man["files"])


def _series(path: Any, var: str, mode: str, t0: float, t1: float) -> dict[str, Any]:
    """{t [epoch s], z [m], <NetCDF variable>: values} for the QC-good samples (GOOD[mode]) in [t0, t1]; var is the file code (NC)."""
    import xarray as xr
    names, qc_of = NC[var]
    with xr.open_dataset(path) as ds:
        t = ds.TIME.values.astype("datetime64[s]").astype("int64").astype("float64")
        vals = {n: ds[n].values.reshape(len(t), -1)[:, 0].astype(float) for n in names}
        q = ds[qc_of + "_QC"].values.reshape(len(t), -1)[:, 0] if qc_of + "_QC" in ds else np.ones(len(t))
        z = float(ds["HEIGHT" if "HEIGHT" in ds else "DEPTH"].values.reshape(-1)[0])
    ok = (t >= t0) & (t <= t1) & np.isin(q, GOOD[mode]) & np.all([np.isfinite(v) for v in vals.values()], axis=0)
    return dict(t=t[ok], z=z, **{n: v[ok] for n, v in vals.items()})


def load_tao(out_dir: Any, t0: Any = None, t1: Any = None) -> dict[str, dict[str, Any]]:
    """{mooring: dict(lat, lon, wind=dict(t, u, v, z), sst=dict(t, value [K], z), airt=dict(t, value [K], z), rh=dict(t, value [0..1], z))}
    from the files fetch_tao selected; verifies the SHA-256 of every file it reads. Variables a mooring lacks are absent."""
    out = pathlib.Path(out_dir)
    man = json.loads((out / "manifest.json").read_text())
    verify(out)
    a, b = (man["t0"] if t0 is None else t0), (man["t1"] if t1 is None else t1)
    res: dict[str, dict[str, Any]] = {}
    for name, sel in man["selected"].items():
        r: dict[str, Any] = dict(lat=man["positions"][name][0], lon=man["positions"][name][1])
        for var, key in sel.items():
            s = _series(out / key, var, man["files"][key]["mode"], a, b)
            if var == "WIND":
                r["wind"] = dict(t=s["t"], u=s["UWND"], v=s["VWND"], z=s["z"])
            else:
                x = s[NC[var][0][0]]
                r[var.lower()] = dict(t=s["t"], value=x + 273.15 if var in ("SST", "AIRT") else 0.01 * x if var == "RH" else x, z=s["z"])
        res[name] = r
    return res


def waves_available(out_dir: Any) -> bool:
    """True if any mooring in the box lists a wave variable. False (and a warning saying so) for TAO/TRITON, which measure
    wind, air and sea temperature, humidity, pressure, rain, radiation and subsurface T/S/currents but not waves."""
    w = json.loads((pathlib.Path(out_dir) / "manifest.json").read_text())["waves"]
    if not w["matches"]:
        warnings.warn(f"no wave data: none of the {w['checked']} TAO/TRITON files listed for the moorings in the box has a wave variable "
                      f"({', '.join(WAVE_VARS)}); compare UMWM swh against altimeter or WW3 instead", UserWarning, stacklevel=2)
    return bool(w["matches"])


# ------------------------------------------------------------------ wind at 10 m


def _z0(ust: Arr, u10n: Arr) -> Arr:
    """Roughness length [m] of the open sea: Charnock alpha(U10n) u*^2/g plus the smooth-flow term (Edson et al. 2013; Smith 1988)."""
    return np.maximum(CH1 * np.minimum(u10n, UMAX) + CH2, 0.0) * ust ** 2 / G + 0.11 * NU_AIR / np.maximum(ust, 1e-4)


def cd10n(u10n: Any) -> Any:
    """Neutral 10-m drag coefficient (kappa / ln(10/z0))^2 of this roughness law at neutral 10-m wind u10n [m/s]."""
    u10n = np.asarray(u10n, float)
    z0 = np.full(u10n.shape, 1e-4)
    for _ in range(30):
        z0 = _z0(KAPPA * u10n / np.log(10.0 / z0), u10n)
    return (KAPPA / np.log(10.0 / z0)) ** 2


def wind_to_10m(speed: ArrayLike, z: ArrayLike, method: str = "log", air: dict[str, Any] | None = None) -> Arr:
    """Wind speed at 10 m from a speed at height z [m]: neutral log profile ('log', default) or COARE ('coare'; `air` =
    dict(t [K, air temperature at z], rh [0..1], sst [K], p [Pa], lat [deg]) broadcast against speed). See the module docstring."""
    speed, z = np.asarray(speed, float), np.asarray(z, float)
    if method == "log":
        z0 = np.full(np.broadcast(speed, z).shape, 1e-4)
        for _ in range(20):                                          # u*, U10n and z0 depend on each other: fixed point
            ust = KAPPA * speed / np.log(z / z0)
            z0 = _z0(ust, ust / KAPPA * np.log(10.0 / z0))
        ust = KAPPA * speed / np.log(z / z0)
        log10: Arr = ust / KAPPA * np.log(10.0 / z0)
        return log10
    if method != "coare":
        raise ValueError(f"method must be 'log' or 'coare', not {method!r}")
    if air is None:
        raise ValueError("method='coare' needs air=dict(t, rh, sst, p, lat) (the mooring's own AIRT, RH, SST)")
    coare = importlib.import_module("cafe.pm.env.coare")
    q = coare.qair(air["t"] - 273.15, air["p"], air["rh"])
    res = coare.coare35(speed, z, air["t"], z, q, z, air["p"], air["sst"], 0.0, 370.0, air["lat"], jcool=0)
    prof: Arr = coare.profile(res, 10.0)
    return prof


# ------------------------------------------------------------------ mooring vs model


def _bin(t: ArrayLike, v: ArrayLike, tt: Arr, half: float = HALF_BIN_S, need: int = MIN_IN_BIN) -> Arr:
    """Mean of v over [tt - half, tt + half) for each tt; NaN when fewer than `need` valid samples fall in it."""
    t, v = np.asarray(t, float), np.asarray(v, float)
    o = np.argsort(t)
    t, v = t[o], v[o]
    lo, hi = np.searchsorted(t, tt - half, "left"), np.searchsorted(t, tt + half, "left")
    ok = np.isfinite(v)
    cs, cn = np.r_[0.0, np.cumsum(np.where(ok, v, 0.0))], np.r_[0, np.cumsum(ok)]
    n = cn[hi] - cn[lo]
    return np.where(n >= need, (cs[hi] - cs[lo]) / np.maximum(n, 1), np.nan)


def _wrap(d: ArrayLike) -> Arr:
    return (np.asarray(d, float) + 180.0) % 360.0 - 180.0


def _stats(wv: Arr, tv: Arr, wsst: Arr | None = None, tsst: Arr | None = None, min_speed: float = 1.0) -> dict[str, Any]:
    """wv, tv: (n, 2) model and mooring (east, north) at 10 m; wsst, tsst [K]. Differences are model minus mooring."""
    ok = np.isfinite(wv).all(1) & np.isfinite(tv).all(1)
    ws, ts = cv.speed(wv[ok]), cv.speed(tv[ok])
    dv = wv[ok] - tv[ok]
    fast = (ws >= min_speed) & (ts >= min_speed)
    dd = _wrap(cv.from_deg(wv[ok][fast]) - cv.from_deg(tv[ok][fast]))
    out = dict(n=int(ok.sum()), speed_bias=float(np.mean(ws - ts)) if ok.any() else np.nan,
               speed_rmse=float(np.sqrt(np.mean((ws - ts) ** 2))) if ok.any() else np.nan,
               vector_rmse=float(np.sqrt(np.mean(np.sum(dv ** 2, 1)))) if ok.any() else np.nan,
               dir_n=int(fast.sum()), dir_bias_deg=float(np.mean(dd)) if fast.any() else np.nan,
               dir_rmse_deg=float(np.sqrt(np.mean(dd ** 2))) if fast.any() else np.nan, sst_n=0, sst_bias=np.nan, sst_rmse=np.nan)
    if wsst is not None and tsst is not None:
        m = np.isfinite(wsst) & np.isfinite(tsst)
        if m.any():
            d = wsst[m] - tsst[m]
            out.update(sst_n=int(m.sum()), sst_bias=float(d.mean()), sst_rmse=float(np.sqrt(np.mean(d ** 2))))
    return out


def compare(wrf: dict[str, Any], tao: dict[str, Any], method: str = "auto") -> dict[str, dict[str, Any]]:
    """Model minus mooring, per mooring and pooled ('ALL'), for the moorings in both.
    wrf: {mooring: dict(t [epoch s], wind10 (n, 2) east/north at 10 m, sst [K] optional (n,))}; tao: load_tao output.
    The mooring winds are lifted to 10 m (wind_to_10m; 'coare' with the mooring's air temperature, humidity and SST at the wind
    times, 'log' neutral, 'auto' = coare where the mooring reports airt, rh and sst, else log), then the vector mean of the 10-min
    samples within +-30 min of each model time is taken (>= 3 samples).
    speed_bias/speed_rmse [m/s], vector_rmse [m/s] (RMS of |model - mooring| vectors), dir_bias_deg/dir_rmse_deg (meteorological
    direction FROM, model minus mooring, signed, wrapped to +-180; only where both speeds >= 1 m/s), sst_bias/sst_rmse [K]."""
    res: dict[str, dict[str, Any]] = {}
    pooled: dict[str, list[Any]] = dict(w=[], t=[], ws=[], ts=[])
    for name in sorted(set(wrf) & set(tao)):
        m, w = tao[name], wrf[name]
        if "wind" not in m:
            continue
        t, sp = m["wind"]["t"], np.hypot(m["wind"]["u"], m["wind"]["v"])
        air: dict[str, Any] | None = None
        use = method == "coare" or (method == "auto" and all(k in m for k in ("airt", "rh", "sst")))
        if use:
            air = {k: np.interp(t, m[v]["t"], m[v]["value"]) for k, v in (("t", "airt"), ("rh", "rh"), ("sst", "sst"))}
            air.update(p=101000.0, lat=m["lat"])
        s10 = wind_to_10m(sp, m["wind"]["z"], "coare" if use else "log", air)
        k = np.where(sp > 0, s10 / np.where(sp > 0, sp, 1.0), 1.0)
        tt = np.asarray(w["t"], float)
        tv = np.column_stack([_bin(t, m["wind"]["u"] * k, tt), _bin(t, m["wind"]["v"] * k, tt)])
        wsst = np.asarray(w["sst"], float) if w.get("sst") is not None else None
        tsst = _bin(m["sst"]["t"], m["sst"]["value"], tt) if "sst" in m else None
        res[name] = _stats(np.asarray(w["wind10"], float), tv, wsst, tsst)
        pooled["w"].append(np.asarray(w["wind10"], float)); pooled["t"].append(tv)
        pooled["ws"].append(wsst if wsst is not None and tsst is not None else np.full(len(tt), np.nan))
        pooled["ts"].append(tsst if tsst is not None else np.full(len(tt), np.nan))
    if res:
        res["ALL"] = _stats(np.concatenate(pooled["w"]), np.concatenate(pooled["t"]), np.concatenate(pooled["ws"]), np.concatenate(pooled["ts"]))
    return res


# ------------------------------------------------------------------ receipts


def receipts(out_dir: Any = None) -> bool:
    """(1) the roughness law behind the neutral wind lift vs COARE 3.5's own drag coefficient, (2) the lift's size, with the
    stability-aware COARE lift for context, (3) compare() recovers a known speed/direction/SST error injected into a copy of a
    series, (4) with out_dir (a real download): every file's SHA-256 matches its manifest entry."""
    from cafe.receipts import bracket, context, receipt
    g = "TAO / TRITON moorings"
    coare = importlib.import_module("cafe.pm.env.coare")
    u = np.array([3.0, 6.0, 9.0, 12.0])
    ones = np.ones(4)
    q = coare.qair(28.0, 101000.0, 0.98)                       # saturated-ish air at the sea temperature: close to neutral
    res = coare.coare35(u, 4.0 * ones, 301.15 * ones, 4.0 * ones, q * ones, 4.0 * ones, 101000.0 * ones, 301.15 * ones, 0.0, 370.0, 0.0, jcool=0)
    receipt(g, "neutral 10 m drag coefficient of the wind-lift roughness law vs COARE 3.5 Cdn10 at COARE's U10n (max relative difference, 3-12 m/s)",
            float(np.max(np.abs(cd10n(res["u10n"]) / res["Cdn10"] - 1))), 0.0, 0.05, "", "Edson et al. 2013 via cafe.pm.env.coare", rel=False)
    bracket(g, "neutral drag coefficient at 10 m/s", float(cd10n(10.0)) * 1e3, 1.0, 1.4, "1e-3",
            "Edson et al. 2013 Fig. 6 (COARE 3.5 Cdn10 ~ 1.2e-3 at 10 m/s)")
    lift = float(wind_to_10m(6.0, 4.0)) / 6.0
    bracket(g, "wind lift 4 m -> 10 m at 6 m/s, neutral", lift, 1.05, 1.11, "", "ln(10/z0) / ln(4/z0) with z0 ~ 4e-5 m")
    q8 = coare.qair(28.0, 101000.0, 0.8)

    def one(v: float) -> Arr:
        return np.array([v])

    r8 = coare.coare35(one(6.0), one(4.0), one(301.15), one(4.0), q8, one(4.0), one(101000.0), one(301.15), 0.0, 370.0, 0.0, jcool=0)
    context(g, "wind lift 4 m -> 10 m at 6 m/s: COARE with 80 % humidity and no air-sea temperature difference (unstable) vs the neutral lift",
            float(coare.profile(r8, 10.0)[0] / coare.profile(r8, 4.0)[0]), lift, "", "cafe.pm.env.coare: stability makes the shear 2-3 % smaller")
    t = np.arange(0, 6 * 3600, 600.0)
    ang = np.radians(40.0 + 20.0 * np.sin(t / 5000.0))
    sp = 6.0 + 2.0 * np.cos(t / 4000.0)
    series: dict[str, Any] = dict(lat=0.0, lon=180.0, wind=dict(t=t, u=-sp * np.sin(ang), v=-sp * np.cos(ang), z=10.0),
                                  sst=dict(t=t, value=301.0 + 0 * t, z=1.0))
    tt = np.arange(3600.0, 5 * 3600, 3600.0)
    truth = np.column_stack([_bin(t, series["wind"]["u"], tt), _bin(t, series["wind"]["v"], tt)])
    rot = np.radians(10.0)
    model = 1.1 * np.column_stack([truth[:, 0] * np.cos(rot) + truth[:, 1] * np.sin(rot), -truth[:, 0] * np.sin(rot) + truth[:, 1] * np.cos(rot)])
    r = compare({"M": dict(t=tt, wind10=model, sst=np.full(len(tt), 301.4))}, {"M": series})["M"]
    receipt(g, "compare(): speed bias recovered from a model that is 10 % faster", r["speed_bias"], 0.1 * float(np.mean(cv.speed(truth))), 1e-6, "m/s",
            "injected", rel=True)
    receipt(g, "compare(): direction bias recovered from a model rotated 10 deg clockwise (wind from)", r["dir_bias_deg"], 10.0, 1e-3, "deg",
            "injected", rel=True)
    receipt(g, "compare(): SST bias recovered from a model 0.4 K warm", r["sst_bias"], 0.4, 1e-6, "K", "injected", rel=True)
    if out_dir is not None:
        n = verify(out_dir)
        receipt(g, f"TAO files whose SHA-256 differs from the manifest (of {n})", 0.0, 0.0, 0.0, "", "manifest.json written at download", rel=False)
    return True


if __name__ == "__main__":
    receipts()
