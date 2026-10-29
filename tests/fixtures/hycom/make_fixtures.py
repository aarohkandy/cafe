"""Synthetic ocean fixtures for cafe.pm.env.hycom (no network): one GOFS-style subset and the same T/S/u/v re-encoded as lab files.

    python -m tests.fixtures.hycom.make_fixtures OUT_DIR      # or make(OUT_DIR) from a test

make() writes into OUT_DIR and returns a dict of paths:
    gofs_parts/   NCSS-style netCDF parts (int16 scale/offset like the real server) + manifest.json   <- the "GOFS subset"
    gofs_zarr     the store assemble_gofs makes from those parts; the truth every lab file below must reproduce
    zlevel_dir/   per-snapshot netCDF on z-levels (other variable names, lon in -180..180, temperature_kind attribute)
    layered_dir/  per-snapshot netCDF on hybrid layers (thknss in Pa, no temperature_kind attribute)
    archv_dir/    archv.2023_060_12 / _15 / _18 .a/.b pairs + regional.grid .a/.b (HYCOM binary archive)
    grid          stem of regional.grid;  box, depth, steps

Grid: 7 lat (step 0.04) x 9 lon (step 0.08, 179.84..180.48, i.e. across the dateline), 10 depths, 3 three-hourly times from
2023-03-01 12Z. One all-land column (j=0, i=0) and one shallow column (j=3, i=4, wet down to 100 m).

Layering used for the lab files: each z-level z_k becomes a thin layer A_k centred exactly on z_k (half-thickness h_k = a quarter
of the closest level gap) and a filler layer F_k between A_k and A_k+1; below a column's seafloor the layers have thickness 0 and
copy the last value (as vanished HYCOM layers do). Reading it back to z-levels therefore returns the GOFS values to float32.
The C-grid velocities are built so that the reader's destaggering ((u(i) + u(i+1)) / 2, then + the barotropic part) returns the
GOFS T-point values exactly except in the last column / row, where HYCOM has no neighbour.
"""
import datetime as dt, hashlib, json, pathlib, sys
from typing import Any

import numpy as np

DEPTH = np.array([0.0, 10, 25, 50, 100, 150, 300, 600, 1000, 1500])
LAT = np.round(-0.12 + 0.04 * np.arange(7), 4)
LON = np.round(179.84 + 0.08 * np.arange(9), 4)
T0 = dt.datetime(2023, 3, 1, 12, tzinfo=dt.timezone.utc).timestamp()
STEPS = T0 + 3 * 3600.0 * np.arange(3)
BOX = (-0.12, 0.12, 179.84, 180.48)
LAND, SHALLOW, SHALLOW_N = (0, 0), (3, 4), 5          # (j, i); SHALLOW is wet at depth indices 0..4
HUGE = np.float32(2.0 ** 100)
ONEM = 9806.0


def _ncss_part(path, names, arr, times, enc, dims3d=True):
    """One NCSS-style part: names -> arrays (t, [z,] lat, lon), int16-packed with scale_factor/add_offset, CF time in hours."""
    import xarray as xr
    th = (times - dt.datetime(2000, 1, 1, tzinfo=dt.timezone.utc).timestamp()) / 3600.0
    ds = xr.Dataset(coords=dict(time=("time", th, dict(units="hours since 2000-01-01 00:00:00", calendar="standard")),
                                lat=("lat", LAT.astype(np.float32)), lon=("lon", LON.astype(np.float32))))
    if dims3d:
        ds = ds.assign_coords(depth=("depth", DEPTH, dict(units="m", positive="down")))
    for n in names:
        ds[n] = ((("time", "depth", "lat", "lon") if dims3d else ("time", "lat", "lon")), arr[n].astype(np.float32))
    e = {n: dict(dtype="int16", scale_factor=np.float32(enc[n][0]), add_offset=np.float32(enc[n][1]), _FillValue=np.int16(-30000)) for n in names}
    ds.to_netcdf(path, encoding=e)


def _fields(nt):
    """Analytic T (in situ), S, u, v [t, z, lat, lon] and ssh [t, lat, lon]; NaN on land and under the seafloor."""
    t, z, la, lo = np.meshgrid(np.arange(nt), DEPTH, LAT, LON, indexing="ij")
    T = 29.0 - 24.0 * (1 - np.exp(-z / 300.0)) + 0.8 * np.sin(8 * la) + 0.05 * t
    S = 34.6 + 0.8 * (1 - np.exp(-z / 200.0)) + 0.2 * (lo - 180.0)
    U = 0.8 * np.exp(-((z - 120.0) / 60.0) ** 2) - 0.3 * np.exp(-z / 30.0) + 0.1 * np.sin(5 * la + 3 * (lo - 180)) + 0.02 * t
    V = 0.15 * np.cos(4 * la - 2 * (lo - 180.0)) * np.exp(-z / 400.0)
    E = 0.2 * np.sin(6 * (LON - 180.0))[None, None, :] * np.cos(5 * LAT)[None, :, None] + 0.01 * np.arange(nt)[:, None, None]
    E = np.broadcast_to(E, (nt, len(LAT), len(LON))).copy()
    dead = np.zeros(T.shape, bool)
    dead[:, :, LAND[0], LAND[1]] = True
    dead[:, SHALLOW_N:, SHALLOW[0], SHALLOW[1]] = True
    for a in (T, S, U, V):
        a[dead] = np.nan
    E[:, LAND[0], LAND[1]] = np.nan
    return dict(water_temp=T, salinity=S, water_u=U, water_v=V), E


def _write_gofs(out):
    from cafe.pm.env import hycom
    pdir = out / "gofs_parts"
    pdir.mkdir(parents=True)
    f, e = _fields(3)
    man = dict(box=list(BOX), dataset="synthetic GOFS 3.1 subset", parts={})
    for d, names, enc in (("ts3z", ("water_temp", "salinity"), dict(water_temp=(0.001, 20.0), salinity=(0.001, 20.0))),
                          ("uv3z", ("water_u", "water_v"), dict(water_u=(0.001, 0.0), water_v=(0.001, 0.0))),
                          ("ssh", ("surf_el",), dict(surf_el=(0.001, 0.0)))):
        for sl in (slice(0, 2), slice(2, 3)):                 # two parts per dataset, as fetch_gofs cuts them
            tt = STEPS[sl]
            fn = f"{d}_{int(tt[0])}_{int(tt[-1])}.nc"
            arr = {n: (e[sl] if n == "surf_el" else f[n][sl]) for n in names}
            _ncss_part(pdir / fn, names, arr, tt, enc, dims3d=d != "ssh")
            man["parts"][fn] = dict(dataset=d, server="ncss", bytes=(pdir / fn).stat().st_size, sha256=hashlib.sha256((pdir / fn).read_bytes()).hexdigest(),
                                    t_start=float(tt[0]), t_end=float(tt[-1]), seconds=0.1, n_steps=len(tt))
    (pdir / "manifest.json").write_text(json.dumps(man, indent=1))
    return hycom.assemble_gofs(pdir, STEPS, out / "gofs.zarr"), pdir


def _levels():
    """Layer top/bottom per layer (A_0, F_0, A_1, F_1, ...) for the 10 z-levels."""
    L = len(DEPTH)
    gap = np.diff(DEPTH)
    h = np.array([0.25 * min(gap[k - 1] if k else np.inf, gap[k] if k < L - 1 else np.inf) for k in range(L)])
    lo = np.maximum(DEPTH - h, 0.0)
    hi = np.where(np.arange(L) == 0, 2 * h, DEPTH + h)
    edges = []
    for k in range(L):
        edges.append((lo[k], hi[k]))
        if k < L - 1:
            edges.append((hi[k], lo[k + 1]))
    return np.array(edges)


def _layers(truth):
    """(K, lat, lon) layer arrays for one variable at one time, truth (z, lat, lon); dp (K, lat, lon) metres."""
    edges = _levels()
    K, L = len(edges), len(DEPTH)
    thick = edges[:, 1] - edges[:, 0]
    val, dp = np.zeros((K,) + truth.shape[1:]), np.zeros((K,) + truth.shape[1:])
    nvalid = np.isfinite(truth).sum(0)
    for k in range(K):
        a = k // 2
        v = truth[a] if k % 2 == 0 else 0.5 * (truth[a] + truth[min(a + 1, L - 1)])
        keep = (k <= 2 * (nvalid - 1)) & (nvalid > 0)
        last = np.take_along_axis(truth, np.maximum(nvalid - 1, 0)[None], 0)[0]
        val[k] = np.where(keep, np.where(np.isfinite(v), v, last), np.nan_to_num(last))
        dp[k] = np.where(keep, thick[k], 0.0)
    return np.nan_to_num(val), dp


def _lon180(lon):
    return (lon + 180.0) % 360.0 - 180.0


def _snapshot_nc(path, i, f, e, layered):
    import xarray as xr
    ts = np.array([np.datetime64(dt.datetime.fromtimestamp(STEPS[i], dt.timezone.utc).replace(tzinfo=None), "ns")])
    lon = _lon180(LON)
    ds = xr.Dataset(coords=dict(time=("time", ts), lat=("lat", LAT), lon=("lon", lon)))
    if layered:
        parts = {n: _layers(f[n][i]) for n in f}
        dp = parts["water_temp"][1]
        ds["thknss"] = (("time", "layer", "lat", "lon"), (dp * ONEM).astype("f4")[None], dict(units="Pa"))
        for out, src, unit in (("temperature", "water_temp", "degC"), ("salinity", "salinity", "psu"),
                               ("u-velocity", "water_u", "m/s"), ("v-velocity", "water_v", "m/s")):
            ds[out] = (("time", "layer", "lat", "lon"), parts[src][0].astype("f4")[None], dict(units=unit))
    else:
        ds = ds.assign_coords(depth=("depth", DEPTH, dict(units="m", positive="down")))
        for out, src, unit in (("temp", "water_temp", "degC"), ("salt", "salinity", "psu"), ("u", "water_u", "m/s"), ("v", "water_v", "m/s")):
            ds[out] = (("time", "depth", "lat", "lon"), f[src][i].astype("f4")[None], dict(units=unit))
        ds["ssh"] = (("time", "lat", "lon"), e[i].astype("f4")[None], dict(units="m"))
        ds.attrs["temperature_kind"] = "in_situ"
    ds.to_netcdf(path)


def _rec_a(arr, idm, jdm):
    flat = np.asarray(arr, "f4").reshape(-1)
    pad = -flat.size % 4096
    return np.concatenate([flat, np.zeros(pad, "f4")]).astype(">f4").tobytes()     # concatenate makes native order: cast after


def write_ab(stem, records, idm, jdm, header_lines=()):
    """records: [(name, k, dens, 2-D array (jdm, idm), day)] -> stem.a / stem.b in HYCOM archv layout."""
    stem = pathlib.Path(stem)
    b = ["HYCOM archive file", "synthetic fixture for cafe.pm.env.hycom (tests/fixtures/hycom/make_fixtures.py)", "expt 93.0 (synthetic)", "",
         "   22    'iversn' = hycom version number x10", "  930    'iexpt ' = experiment number x10", "    3    'yrflag' = days in year flag",
         f"{idm:5d}    'idm   ' = longitudinal array size", f"{jdm:5d}    'jdm   ' = latitudinal  array size", *header_lines,
         "field       time step  model day  k  dens        min              max"]
    blob = b""
    for name, k, dens, arr, day in records:
        a = np.asarray(arr, "f4")
        ok = a[a < HUGE]
        b.append(f"{name:<8}= {0:11d}{day:11.3f}{k:3d}{dens:7.3f}{(ok.min() if ok.size else 0.0):16.7E}{(ok.max() if ok.size else 0.0):16.7E}")
        blob += _rec_a(a, idm, jdm)
    stem.with_name(stem.name + ".b").write_text("\n".join(b) + "\n")
    stem.with_name(stem.name + ".a").write_bytes(blob)


def _stagger(total, axis):
    """C-grid values whose T-point average (u(i) + u(i+1)) / 2 along `axis` reproduces `total` except in the last column/row."""
    n = total.shape[axis]
    st_i = np.take(total, 0, axis=axis)
    out = [st_i]
    for i in range(n - 1):
        st_i = 2 * np.take(total, i, axis=axis) - st_i
        out.append(st_i)
    return np.stack(out, axis=axis)


def _write_archv(out, f, e):
    d = out / "archv_dir"
    d.mkdir()
    jdm, idm = len(LAT), len(LON)
    plon = np.tile(_lon180(LON), (jdm, 1))
    plat = np.tile(LAT[:, None], (1, idm))
    grid = (("plon", plon), ("plat", plat), ("qlon", plon + 0.04), ("pang", np.zeros_like(plon)))
    (d / "regional.grid.a").write_bytes(b"".join(_rec_a(a, idm, jdm) for _, a in grid))
    lines = [f"{idm:5d}    'idm   ' = longitudinal array size", f"{jdm:5d}    'jdm   ' = latitudinal  array size",
             "    0    'mapflg' = map flag (-1=unknown,0=mercator,1=latlon,2=polar)"]
    for n, a in grid:
        lines.append(f"{n}:  min,max =  {a.min():12.5f}{a.max():12.5f}")
    (d / "regional.grid.b").write_text("\n".join(lines) + "\n")
    edges = _levels()
    bt_u, bt_v = 0.02 * np.cos(3 * LAT)[:, None] * np.ones((1, idm)), 0.01 * np.sin(2 * (LON - 180))[None] * np.ones((jdm, 1))
    for i in range(3):
        day = (dt.datetime.fromtimestamp(STEPS[i], dt.timezone.utc) - dt.datetime(1900, 12, 31, tzinfo=dt.timezone.utc)).total_seconds() / 86400.0
        parts = {n: _layers(f[n][i]) for n in f}
        ssh = np.where(np.isnan(e[i]), HUGE, e[i] * 9.806)
        recs = [("montg1", 1, 25.0, np.zeros((jdm, idm)), day), ("srfhgt", 0, 0.0, ssh, day), ("surflx", 0, 0.0, np.zeros((jdm, idm)), day),
                ("u_btrop", 0, 0.0, bt_u, day), ("v_btrop", 0, 0.0, bt_v, day)]
        for k in range(len(edges)):
            ust = _stagger(parts["water_u"][0][k].astype(float), 1) - bt_u
            vst = _stagger(parts["water_v"][0][k].astype(float), 0) - bt_v
            dens = 20.0 + 0.01 * k
            recs += [("u-vel.", k + 1, dens, ust, day), ("v-vel.", k + 1, dens, vst, day), ("thknss", k + 1, dens, parts["water_temp"][1][k] * ONEM, day),
                     ("temp", k + 1, dens, parts["water_temp"][0][k], day), ("salin", k + 1, dens, parts["salinity"][0][k], day)]
        t = dt.datetime.fromtimestamp(STEPS[i], dt.timezone.utc)
        write_ab(d / f"archv.{t:%Y}_{t.timetuple().tm_yday:03d}_{t:%H}", recs, idm, jdm)
    return d


def make(out: str | pathlib.Path) -> dict[str, Any]:
    """Write every fixture under `out` (must not exist yet or be empty) and return the paths."""
    out = pathlib.Path(out)
    out.mkdir(parents=True, exist_ok=True)
    zarr, parts = _write_gofs(out)
    from cafe.pm.env import hycom
    ds = hycom.open_store(zarr)
    f = {n: ds[n].values.astype(float) for n in ("water_temp", "salinity", "water_u", "water_v")}
    e = ds["surf_el"].values.astype(float)
    # the store's lon is sorted ascending 0..360, which for this grid is the same order as LON
    for name, layered in (("zlevel_dir", False), ("layered_dir", True)):
        (out / name).mkdir()
        for i in range(3):
            _snapshot_nc(out / name / f"snap_{i}.nc", i, f, e, layered)
    arch = _write_archv(out, f, e)
    return dict(box=BOX, depth=DEPTH, steps=STEPS, gofs_parts=parts, gofs_zarr=zarr, zlevel_dir=out / "zlevel_dir",
                layered_dir=out / "layered_dir", archv_dir=arch, grid=arch / "regional.grid")


if __name__ == "__main__":
    print(make(sys.argv[1]))
