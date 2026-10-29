"""Ingest the UWIN-CM run on orca (WRF + UMWM, hourly) for a mission box, by byte range, into a local Zarr cache.

    ingest(t0, t1, box, out)   ->  out/wrf.zarr, out/wrf3d.zarr, out/umwm.zarr, out/umwmspec.zarr, out/manifest.json

Directory listing on orca is 403, so filenames are built from the hour: `wrfout_d01_YYYY-MM-DD_HH:00:00`,
`output/umwmout_YYYY-MM-DD_HH:00:00.nc`, `restart/umwmrst_YYYY-MM-DD_HH:00:00.nc` (00/06/12/18 Z only).
Each hour is extracted to `out/hours/<kind>_<stamp>.npz` first, so an interrupted ingest resumes where it stopped;
the Zarr stores are assembled from those once every hour is present. Only the box (mission waypoints +- pad) is read:
~4 MB per 2-D WRF field per hour, ~80 MB per 3-D field (whole-column quarter-domain chunks), ~0.8 MB per UMWM field.

3-D WRF (U, V, PH, PHB, T, lowest NZ3 levels) is read only for the hours in `hours3d` (the UAS sorties): below the
first mass level (~21 m) and at every other hour wind comes from U10 through the COARE profile.
"""
import concurrent.futures as cf, datetime as dt, json, os, pathlib, time

import numpy as np

from . import remote

BASE = os.environ.get("CAFE_ORCA", "https://orca.atmos.washington.edu/data/temp/model/run_2023mar_waves_v4")
WRF2D = ["U10", "V10", "T2", "Q2", "PSFC", "SST", "TSK", "HFX", "LH", "QFX", "RAINNC", "RAINC", "SWDOWN", "GLW",
         "UST", "PBLH"]
WRFSTATIC = ["XLAT", "XLONG", "LANDMASK", "HGT", "COSALPHA", "SINALPHA"]
WRF3D = ["U", "V", "PH", "PHB", "T"]
NZ3 = 8                                    # mass levels kept: ~21 to ~400 m
UMWM2D = ["swh", "mwp", "mwd", "dwp", "dwd", "mss", "wspd", "wdir", "ust", "cd", "dcp", "dcg", "mwl", "dwl"]
UMWMSTATIC = ["lon", "lat", "seamask", "depth"]
SPEC_STRIDE = 3                            # keep every 3rd restart sea point in each direction (36 km)
SCHEMAS = pathlib.Path(__file__).resolve().parents[2] / "schemas"


def schema(kind):
    """cafe/schemas/<kind>.json, or <kind>.json from the directory in $CAFE_SCHEMAS (tests with a small grid)."""
    return json.loads((pathlib.Path(os.environ.get("CAFE_SCHEMAS") or SCHEMAS) / f"{kind}.json").read_text())


def schema_errors(kind, actual, url):
    """Compare {var: dict(dims, dtype, units, shape)} read from a file against cafe/schemas/<kind>.json."""
    want = schema(kind)["variables"]
    errs = []
    for k, a in actual.items():
        w = want.get(k)
        if w is None:
            errs.append(f"{k}: not in cafe/schemas/{kind}.json")
            continue
        for f in ("dims", "dtype", "units", "shape"):
            if f in a and a[f] != w[f]:
                errs.append(f"{k}.{f} = {a[f]!r}, schema says {w[f]!r}")
    if errs:
        raise ValueError(f"{url}: does not match cafe/schemas/{kind}.json (the reader would misread it):\n  " + "\n  ".join(errs))


def _h5meta(f, names):
    out = {}
    for k in names:
        v = f[k]
        u = v.attrs.get("units", b"")
        out[k] = dict(dims=[v.dims[i][0].name.split("/")[-1] for i in range(v.ndim)], dtype=str(v.dtype),
                      units=u.decode() if isinstance(u, bytes) else str(u), shape=list(v.shape))
    return out


def _cdfmeta(hdr, names):
    return {k: dict(dims=hdr[2][k]["dims"], dtype=hdr[2][k]["dtype"].lstrip(">"), units=str(hdr[2][k]["attrs"].get("units", "")),
                    shape=hdr[2][k]["shape"]) for k in names}


def stamp(t):
    return t.strftime("%Y-%m-%d_%H:00:00")


def hours(t0, t1):
    n = int((t1 - t0).total_seconds() // 3600)
    return [t0 + dt.timedelta(hours=k) for k in range(n + 1)]


def urls(t):
    s = stamp(t)
    return dict(wrf=f"{BASE}/wrfout_d01_{s}", umwm=f"{BASE}/output/umwmout_{s}.nc", rst=f"{BASE}/restart/umwmrst_{s}.nc")


def lon360(x):
    return np.mod(x, 360.0)


def _span(mask):
    idx = np.flatnonzero(mask)
    if not idx.size:
        raise ValueError("the mission box is outside the model domain")
    return int(idx[0]), int(idx[-1]) + 1


def box_index(lat1d, lon1d, box):
    """(j0, j1, i0, i1) covering box = (lon_min, lon_max, lat_min, lat_max) on separable 1-D axes; lon in any range."""
    lo, hi, la, lb = box
    lo, hi = lon360(lo), lon360(hi)
    L = lon360(lon1d)
    inlon = (L >= lo) & (L <= hi) if lo <= hi else (L >= lo) | (L <= hi)
    j0, j1 = _span((lat1d >= la) & (lat1d <= lb))
    i0, i1 = _span(inlon)
    return max(j0 - 1, 0), min(j1 + 1, len(lat1d)), max(i0 - 1, 0), min(i1 + 1, len(lon1d))


def _wrf_attrs(f):
    a = {k: f.attrs[k] for k in ("MAP_PROJ", "CEN_LAT", "CEN_LON", "STAND_LON", "TRUELAT1", "DX", "DT", "SST_UPDATE",
                                 "SF_OCEAN_PHYSICS", "SIMULATION_START_DATE", "TITLE")}
    return {k: (v.decode() if isinstance(v, bytes) else v.item() if hasattr(v, "item") else v) for k, v in a.items()}


def wrf_grid(t, box):
    import h5py
    with h5py.File(remote.RemoteFile(urls(t)["wrf"]), "r") as f:
        schema_errors("wrfout", _h5meta(f, WRFSTATIC + WRF2D + WRF3D), urls(t)["wrf"])
        want = schema("wrfout")["global_attrs"]
        got = _wrf_attrs(f)
        bad = {k: (got[k], want[k]) for k in got if k in want and got[k] != want[k]}
        if bad:
            raise ValueError(f"{urls(t)['wrf']}: global attributes differ from cafe/schemas/wrfout.json (got, schema): {bad}")
        lat, lon = f["XLAT"][0, :, 0], f["XLONG"][0, 0, :]
        j0, j1, i0, i1 = box_index(lat, lon, box)
        out = {k: f[k][0, j0:j1, i0:i1] for k in WRFSTATIC}
        return dict(j=(j0, j1), i=(i0, i1), attrs=_wrf_attrs(f), **out)


def wrf_hour(t, g, three_d=False):
    """One hour of WRF in the box: 2-D fields, and (three_d) destaggered U, V and mass-level heights, theta."""
    import h5py
    (j0, j1), (i0, i1) = g["j"], g["i"]
    rf = remote.RemoteFile(urls(t)["wrf"])
    with h5py.File(rf, "r") as f:
        schema_errors("wrfout", _h5meta(f, WRF2D + (WRF3D if three_d else [])), urls(t)["wrf"])
        times = f["Times"][0].tobytes().decode()
        if times != stamp(t):
            raise ValueError(f"{urls(t)['wrf']}: Times is {times}, expected {stamp(t)}")
        out = {k: f[k][0, j0:j1, i0:i1] for k in WRF2D}
        if three_d:
            u = f["U"][0, :NZ3, j0:j1, i0:i1 + 1]
            v = f["V"][0, :NZ3, j0:j1 + 1, i0:i1]
            ph = f["PH"][0, :NZ3 + 1, j0:j1, i0:i1] + f["PHB"][0, :NZ3 + 1, j0:j1, i0:i1]
            out["U3"] = 0.5 * (u[..., 1:] + u[..., :-1])                 # destagger x
            out["V3"] = 0.5 * (v[:, 1:] + v[:, :-1])                     # destagger y
            zw = ph / 9.81
            out["Z3"] = 0.5 * (zw[1:] + zw[:-1])                         # mass-level height above MSL, m
            out["TH3"] = f["T"][0, :NZ3, j0:j1, i0:i1] + 300.0           # potential temperature, K
    out["_bytes"] = np.int64(rf.fetched)
    return out


def umwm_grid(t, box, hdr=None):
    u = urls(t)["umwm"]
    hdr = hdr or remote.cdf1_header(u)
    schema_errors("umwmout", _cdfmeta(hdr, UMWM2D + UMWMSTATIC), u)
    lat = remote.cdf1_read(u, "lat", hdr)[:, 0]
    lon = remote.cdf1_read(u, "lon", hdr)[0, :]
    j0, j1, i0, i1 = box_index(lat, lon, box)
    out = {k: remote.cdf1_read(u, k, hdr, rows=(j0, j1))[:, i0:i1] for k in UMWMSTATIC}
    return dict(j=(j0, j1), i=(i0, i1), hdr=hdr, **out)


def umwm_hour(t, g):
    u = urls(t)["umwm"]
    hdr = remote.cdf1_header(u)
    schema_errors("umwmout", _cdfmeta(hdr, UMWM2D), u)
    (j0, j1), (i0, i1) = g["j"], g["i"]
    return {k: remote.cdf1_read(u, k, hdr, rows=(j0, j1))[:, i0:i1] for k in UMWM2D}


def spec_points(t, ug, stride=SPEC_STRIDE):
    """Sea-point indices of the restart file inside the UMWM box `ug`, thinned to every `stride`-th grid row/column.

    Restart points carry their own lon/lat; each is matched to the nearest node of the output grid's 1-D axes."""
    u = urls(t)["rst"]
    hdr = remote.cdf1_header(u)
    schema_errors("umwmrst", _cdfmeta(hdr, ["F", "wavenumber", "lon", "lat", "frequency", "theta"]), u)
    lon, lat = lon360(remote.cdf1_read(u, "lon", hdr)), remote.cdf1_read(u, "lat", hdr)
    la, lo = ug["lat"][:, 0], lon360(ug["lon"][0, :])
    gj = np.clip(np.searchsorted(la, lat), 1, len(la) - 1)
    gj -= (lat - la[gj - 1]) < (la[gj] - lat)
    gi = np.clip(np.searchsorted(lo, lon), 1, len(lo) - 1)
    gi -= (lon - lo[gi - 1]) < (lo[gi] - lon)
    near = (np.abs(la[gj] - lat) < 0.06) & (np.abs(lo[gi] - lon) < 0.06)   # inside the box, on a node (spacing ~0.11 deg)
    keep = np.flatnonzero(near & (gj % stride == 0) & (gi % stride == 0))
    if not keep.size:
        raise ValueError(f"{u}: no restart sea points inside the box")
    return dict(x=keep, lon=lon[keep], lat=lat[keep], hdr=hdr, f=remote.cdf1_read(u, "frequency", hdr),
                th=remote.cdf1_read(u, "theta", hdr))


def runs(idx, gap=1):
    """Cover sorted indices with (start, stop) spans, merging neighbours closer than `gap` (gap=1: exact runs)."""
    if not len(idx):
        return []
    br = np.flatnonzero(np.diff(idx) > gap)
    starts = np.r_[idx[0], idx[br + 1]]
    stops = np.r_[idx[br], idx[-1]] + 1
    return list(zip(starts.tolist(), stops.tolist(), strict=True))


def spec_hour(t, pts):
    u = urls(t)["rst"]
    hdr = remote.cdf1_header(u)
    schema_errors("umwmrst", _cdfmeta(hdr, ["F", "wavenumber", "lon", "lat"]), u)
    if hdr[0]["x"] != pts["hdr"][0]["x"]:
        raise ValueError(f"{u}: {hdr[0]['x']} sea points, the first restart had {pts['hdr'][0]['x']}")
    F, K = [], []
    x = pts["x"]
    for a, b in runs(x, gap=64):                                         # one byte range per box row, thinned after
        sel = x[(x >= a) & (x < b)] - a
        F.append(remote.cdf1_read(u, "F", hdr, rows=(a, b))[sel])
        K.append(remote.cdf1_read(u, "wavenumber", hdr, rows=(a, b))[sel])
    return dict(F=np.concatenate(F), k=np.concatenate(K))


def _save(path, d):
    tmp = path.with_name(path.name + ".tmp.npz")
    np.savez(tmp, **d)
    os.replace(tmp, path)


def ingest(t0, t1, box, out, hours3d=(), threads=8, spectra=True, log=print):
    """Fetch every hour t0..t1 for `box` into `out`. Returns the manifest (also written to out/manifest.json)."""
    out = pathlib.Path(out)
    (out / "hours").mkdir(parents=True, exist_ok=True)
    ts = hours(t0, t1)
    if not ts:
        raise ValueError(f"t1 {t1} is before t0 {t0}")
    wg = wrf_grid(ts[0], box)
    ug = umwm_grid(ts[0], box)
    h3 = {stamp(t) for t in hours3d}
    jobs = []
    for t in ts:
        s = stamp(t)
        jobs.append((out / "hours" / f"wrf_{s}.npz", lambda t=t, s=s: wrf_hour(t, wg, s in h3)))
        jobs.append((out / "hours" / f"umwm_{s}.npz", lambda t=t: umwm_hour(t, ug)))
    pts = None
    if spectra:
        rst = [t for t in ts if t.hour % 6 == 0]
        if not rst:
            raise ValueError(f"no restart hour (00/06/12/18 Z) in {ts[0]} .. {ts[-1]}; spectra=False skips the spectra")
        pts = spec_points(rst[0], ug)
        jobs += [(out / "hours" / f"spec_{stamp(t)}.npz", lambda t=t: spec_hour(t, pts)) for t in rst]
    todo = [(p, f) for p, f in jobs if not p.exists()]
    log(f"ingest: {len(jobs)} parts, {len(jobs) - len(todo)} cached, fetching {len(todo)} with {threads} threads")
    t_start, done = time.time(), 0
    with cf.ThreadPoolExecutor(threads) as ex:
        fut = {ex.submit(f): p for p, f in todo}
        for fu in cf.as_completed(fut):
            _save(fut[fu], fu.result())
            done += 1
            if done % 20 == 0 or done == len(todo):
                log(f"  {done}/{len(todo)} parts, {time.time() - t_start:.0f} s")
    return assemble(out, ts, wg, ug, pts, sorted(h3))


def assemble(out, ts, wg, ug, pts, h3):
    import xarray as xr
    out = pathlib.Path(out)
    tt = np.array([np.datetime64(t.replace(tzinfo=None), "s") for t in ts])
    lat_w, lon_w = wg["XLAT"][:, 0].astype("f8"), lon360(wg["XLONG"][0, :]).astype("f8")
    W = [np.load(out / "hours" / f"wrf_{stamp(t)}.npz") for t in ts]
    ds = xr.Dataset({k: (("time", "lat", "lon"), np.stack([w[k] for w in W])) for k in WRF2D},
                    coords=dict(time=tt, lat=lat_w, lon=lon_w))
    for k in WRFSTATIC[2:]:
        ds[k] = (("lat", "lon"), wg[k])
    ds.attrs.update({k: str(v) for k, v in wg["attrs"].items()})
    ds.attrs["source"] = BASE
    ds.to_zarr(out / "wrf.zarr", mode="w")
    if h3:
        T3 = [t for t in ts if stamp(t) in h3]
        W3 = [np.load(out / "hours" / f"wrf_{stamp(t)}.npz") for t in T3]
        t3 = np.array([np.datetime64(t.replace(tzinfo=None), "s") for t in T3])
        d3 = xr.Dataset({k: (("time", "lev", "lat", "lon"), np.stack([w[k] for w in W3])) for k in ("U3", "V3", "Z3", "TH3")},
                        coords=dict(time=t3, lat=lat_w, lon=lon_w))
        d3.to_zarr(out / "wrf3d.zarr", mode="w")
    U = [np.load(out / "hours" / f"umwm_{stamp(t)}.npz") for t in ts]
    lat_u, lon_u = ug["lat"][:, 0].astype("f8"), lon360(ug["lon"][0, :]).astype("f8")
    du = xr.Dataset({k: (("time", "lat", "lon"), np.stack([u[k] for u in U])) for k in UMWM2D},
                    coords=dict(time=tt, lat=lat_u, lon=lon_u))
    du["seamask"] = (("lat", "lon"), ug["seamask"])
    du["depth"] = (("lat", "lon"), ug["depth"])
    du.attrs["source"] = BASE
    du.to_zarr(out / "umwm.zarr", mode="w")
    if pts is not None:
        ST = [t for t in ts if t.hour % 6 == 0]
        S = [np.load(out / "hours" / f"spec_{stamp(t)}.npz") for t in ST]
        sp = xr.Dataset(dict(F=(("time", "point", "th", "f"), np.stack([s["F"] for s in S])),
                             k=(("time", "point", "f"), np.stack([s["k"] for s in S])),
                             plon=(("point",), lon360(pts["lon"]).astype("f8")), plat=(("point",), pts["lat"].astype("f8"))),
                        coords=dict(time=np.array([np.datetime64(t.replace(tzinfo=None), "s") for t in ST]),
                                    f=pts["f"].astype("f8"), th=pts["th"].astype("f8")))
        sp.attrs.update(source=BASE, units_F="m^4 rad^-1 (wavenumber spectrum)", stride=SPEC_STRIDE)
        sp.to_zarr(out / "umwmspec.zarr", mode="w")
    parts = sorted((out / "hours").glob("*.npz"))
    man = dict(base=BASE, t0=str(ts[0]), t1=str(ts[-1]), hours=len(ts), hours3d=h3, wrf_index=dict(j=wg["j"], i=wg["i"]),
               umwm_index=dict(j=ug["j"], i=ug["i"]), wrf_attrs=wg["attrs"],
               parts={p.name: remote.sha256(p) for p in parts},
               bytes_fetched=int(sum(int(w["_bytes"]) for w in W)))
    (out / "manifest.json").write_text(json.dumps(man, indent=1, default=str))
    return man
