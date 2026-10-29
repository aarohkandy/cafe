"""A miniature orca tree with analytic values, and the matching schemas.

    python tests/fixtures/orca/make_fixtures.py OUTDIR      # writes OUTDIR/{orca,schemas}

Layout (the same file names orca.py builds, hours 00..06 of 2023-03-05, restarts at 00 and 06):
    wrfout_d01_<stamp>               NETCDF4 (HDF5, chunked + zlib), 8 x 12 Mercator-like grid, lon 170..192 (crosses the
                                     dateline: XLONG is stored -180..180), lat -7..7 (crosses the equator), 9 levels
    output/umwmout_<stamp>.nc        NETCDF3_CLASSIC, Time unlimited, 6 x 10 grid, lon 170..188 (stored 0..360), NaN on land
    restart/umwmrst_<stamp>.nc       CDF-1, one spectrum per sea node of the UMWM grid, lon stored -180..180

Every value is a dyadic rational, exactly representable in float32, so tests compare bit for bit.
"""
import datetime as dt
import json
import pathlib
import shutil
import sys

import netCDF4
import numpy as np

REAL = pathlib.Path(__file__).resolve().parents[3] / "cafe" / "schemas"
G = 9.81
T0 = dt.datetime(2023, 3, 5, 0)
HOURS = list(range(7))
RST_HOURS = (0, 6)

NY, NX, NZ = 8, 12, 9                                    # WRF mass points
WLAT = np.arange(NY) * 2.0 - 7.0
WLON360 = 170.0 + 2.0 * np.arange(NX)
WLON = np.where(WLON360 >= 180, WLON360 - 360, WLON360)  # as WRF stores it
WLAND = {(2, 5), (2, 6), (6, 0)}                         # (j, i) land cells

UNY, UNX, NTH, NF = 6, 10, 4, 3                          # UMWM grid, restart directions and frequencies
ULAT = np.arange(UNY) * 2.0 - 5.0
ULON = 170.0 + 2.0 * np.arange(UNX)
ULAND = {(0, 0), (0, 1), (2, 4), (2, 5), (3, 5), (4, 8), (5, 9)}
SEAMASK = np.array([[0 if (j, i) in ULAND else 1 for i in range(UNX)] for j in range(UNY)], dtype="i4")
SEA = np.flatnonzero(SEAMASK.ravel())                    # restart point x -> flat UMWM node

WRF2D = ["U10", "V10", "T2", "Q2", "PSFC", "SST", "TSK", "HFX", "LH", "QFX", "RAINNC", "RAINC", "SWDOWN", "GLW", "UST", "PBLH"]
WRFSTATIC = ["LANDMASK", "HGT", "COSALPHA", "SINALPHA"]
UMWM2D = ["swh", "mwp", "mwd", "dwp", "dwd", "mss", "wspd", "wdir", "ust", "cd", "dcp", "dcg", "mwl", "dwl"]


def stamp(h):
    return (T0 + dt.timedelta(hours=h)).strftime("%Y-%m-%d_%H:00:00")


def _ramp(n, h, lat, lon360):
    return (n * 1000 + h * 100 + lon360 * 0.125 + lat * 0.0625).astype("f4")


def wrf2d(name, h):
    """(NY, NX) field `name` at hour h: n*1000 + 100*h + lon/8 + lat/16 (lon unwrapped to 0..360)."""
    return _ramp(WRF2D.index(name) + 1, h, WLAT[:, None], WLON360[None, :])


def wrf_static(name):
    la, lo = WLAT[:, None] + 0 * WLON360[None, :], WLON360[None, :] + 0 * WLAT[:, None]
    if name == "XLAT":
        return la.astype("f4")
    if name == "XLONG":
        return (lo - 360 * (lo >= 180)).astype("f4")
    if name == "LANDMASK":
        return np.array([[1.0 if (j, i) in WLAND else 0.0 for i in range(NX)] for j in range(NY)], dtype="f4")
    return _ramp(100 + WRFSTATIC.index(name), 0, la, lo)


def _kji(nk, nj, ni):
    return np.arange(nk)[:, None, None], np.arange(nj)[None, :, None], np.arange(ni)[None, None, :]


def wrf_u(h):                                            # (NZ, NY, NX+1): i'^2 + 10 k + 100 j + h
    k, j, i = _kji(NZ, NY, NX + 1)
    return (i ** 2 + 10 * k + 100 * j + h).astype("f4")


def wrf_v(h):                                            # (NZ, NY+1, NX): j'^2 + 10 k + 100 i + h
    k, j, i = _kji(NZ, NY + 1, NX)
    return (j ** 2 + 10 * k + 100 * i + h).astype("f4")


def wrf_zw(h):                                           # (NZ+1, NY, 1) w-level height, m: 10 k^2 + j / 2 + h
    return 10.0 * np.arange(NZ + 1)[:, None, None] ** 2 + 0.5 * np.arange(NY)[None, :, None] + h


def wrf_t(h):                                            # (NZ, NY, NX): k + i / 2 + h
    k, j, i = _kji(NZ, NY, NX)
    return (k + 0.5 * i + h + 0 * j).astype("f4")


def umwm2d(name, h):
    """(UNY, UNX) field at hour h, NaN on land."""
    a = _ramp(UMWM2D.index(name) + 1, h, ULAT[:, None], ULON[None, :])
    return np.where(SEAMASK == 1, a, np.float32("nan")).astype("f4")


def umwm_static(name):
    lo, la = ULON[None, :] + 0 * ULAT[:, None], ULAT[:, None] + 0 * ULON[None, :]
    depth = np.where(SEAMASK == 1, 4000.0 - lo, 0.0).astype("f4")
    return dict(lon=lo.astype("f4"), lat=la.astype("f4"), seamask=SEAMASK, depth=depth)[name]


def rst_points(sea=SEA):
    """lon (stored -180..180), lat of the restart points."""
    lon = np.tile(ULON, UNY)[sea]
    return (lon - 360 * (lon >= 180)).astype("f4"), np.repeat(ULAT, UNX)[sea].astype("f4")


def rst_arrays(h, sea=SEA):
    n = len(sea)
    x = np.arange(n, dtype="f4")
    lon, lat = rst_points(sea)
    return dict(lon=lon, lat=lat, frequency=np.array([0.0625, 0.125, 0.25], "f4"), theta=(np.arange(NTH) * 0.5).astype("f4"),
                ust=(0.0625 * x + h).astype("f4"),
                wavenumber=(0.5 * x[:, None] + np.arange(NF)[None, :] + h).astype("f4"),
                F=(x[:, None, None] + 0.25 * np.arange(NTH)[None, :, None] + 0.0625 * np.arange(NF)[None, None, :]
                   + 1000 * h).astype("f4"))


def sizes(sea=SEA):
    return dict(Time=1, DateStrLen=19, west_east=NX, west_east_stag=NX + 1, south_north=NY, south_north_stag=NY + 1,
                bottom_top=NZ, bottom_top_stag=NZ + 1, y=UNY, x=len(sea), f=NF, th=NTH)


def small_schema(kind, sea=SEA):
    """The real schema with shapes of this fixture grid (units, dtypes and dim names untouched)."""
    s = json.loads((REAL / f"{kind}.json").read_text())
    sz = sizes(sea)
    if kind == "umwmout":
        sz["x"] = UNX
    for v in s["variables"].values():
        v["shape"] = [sz[d] for d in v["dims"]]
    if "dims" in s:
        s["dims"] = {d: sz.get(d, n) if d != "Time" else 0 for d, n in s["dims"].items()}
    return s


def write_schemas(out, sea=SEA):
    out = pathlib.Path(out)
    out.mkdir(parents=True, exist_ok=True)
    for k in ("wrfout", "umwmout", "umwmrst"):
        (out / f"{k}.json").write_text(json.dumps(small_schema(k, sea), indent=1))


def _put(nc, name, spec, data, dims=None, units=None, dtype=None, **kw):
    dims = dims or spec["dims"]
    v = nc.createVariable(name, dtype or {"float32": "f4", "|S1": "S1"}.get(spec["dtype"], spec["dtype"]), dims, **kw)
    u = (units or {}).get(name, spec["units"])
    if u != "" or name in ("LANDMASK", "COSALPHA", "SINALPHA"):
        v.units = u
    v[...] = data
    return v


def write_wrf(path, h, times=None, units=None, dims=None, attrs=None, dtypes=None):
    """One wrfout file. Overrides to make a drifted file: units={var: str}, dims={var: tuple}, attrs={name: value},
    dtypes={var: 'f8'}, times='<stamp>'."""
    sch = small_schema("wrfout")
    dims, dtypes = dims or {}, dtypes or {}
    with netCDF4.Dataset(path, "w", format="NETCDF4") as nc:
        for d, n in sizes().items():
            if d in ("x", "y", "f", "th"):
                continue
            nc.createDimension(d, None if d == "Time" else n)
        for k, val in {**sch["global_attrs"], **(attrs or {})}.items():
            nc.setncattr(k, np.float32(val) if isinstance(val, float) else np.int32(val) if isinstance(val, int) else val)
        data = {k: wrf2d(k, h) for k in WRF2D}
        data.update({k: wrf_static(k) for k in ("XLAT", "XLONG", *WRFSTATIC)})
        zw = wrf_zw(h) * np.ones((1, 1, NX))
        data.update(U=wrf_u(h), V=wrf_v(h), PH=(0.25 * G * zw).astype("f4"), PHB=(0.75 * G * zw).astype("f4"), T=wrf_t(h))
        for k, spec in sch["variables"].items():
            if k == "Times":
                v = nc.createVariable("Times", "S1", ("Time", "DateStrLen"))
                v[0, :] = np.frombuffer((times or stamp(h)).encode(), "S1")
                continue
            a = data[k][None]
            if k in dims:                                   # a drifted file: a 2-D field with its axes swapped
                a = a.transpose(0, 2, 1)
            _put(nc, k, spec, a, dims.get(k), units, dtypes.get(k), zlib=True, complevel=4)


def write_umwm(path, h, units=None, fmt="NETCDF3_CLASSIC"):
    sch = small_schema("umwmout")
    with netCDF4.Dataset(path, "w", format=fmt) as nc:
        for d, n in (("Time", None), ("y", UNY), ("x", UNX), ("f", NF), ("th", NTH)):
            nc.createDimension(d, n)
        for k, spec in sch["variables"].items():
            a = umwm2d(k, h) if k in UMWM2D else umwm_static(k)
            _put(nc, k, spec, a[None], units=units)


def write_rst(path, h, sea=SEA, units=None, fmt="NETCDF3_CLASSIC"):
    sch = small_schema("umwmrst", sea)
    arr = rst_arrays(h, sea)
    with netCDF4.Dataset(path, "w", format=fmt) as nc:
        for d, n in (("x", len(sea)), ("f", NF), ("th", NTH)):
            nc.createDimension(d, n)
        for k, spec in sch["variables"].items():
            _put(nc, k, spec, arr[k], units=units)


def write_tree(root, hours=HOURS, rst_hours=RST_HOURS):
    """The whole mini orca tree under `root` and its schemas under root/../schemas; returns the schema dir."""
    root = pathlib.Path(root)
    (root / "output").mkdir(parents=True, exist_ok=True)
    (root / "restart").mkdir(exist_ok=True)
    for h in hours:
        write_wrf(root / f"wrfout_d01_{stamp(h)}", h)
        write_umwm(root / "output" / f"umwmout_{stamp(h)}.nc", h)
    for h in rst_hours:
        write_rst(root / "restart" / f"umwmrst_{stamp(h)}.nc", h)
    write_schemas(root.parent / "schemas")
    return root.parent / "schemas"


if __name__ == "__main__":
    out = pathlib.Path(sys.argv[1])
    shutil.rmtree(out, ignore_errors=True)
    write_tree(out / "orca")
