"""HYCOM ocean for the pre-mission pipeline: GOFS 3.1 fetch -> Zarr, lab HYCOM readers (netCDF, archv .a/.b), TEOS-10.

    fetch_gofs(box, t0, t1, out_dir)        GOFS 3.1 GLBy0.08 expt_93.0 subset -> <out_dir>/gofs_tepex_c.zarr (+ manifest)
    ingest_lab_hycom(path, box, out_zarr)   lab HYCOM (per-snapshot netCDF or archv .a/.b) -> the same Zarr layout
    open_store(zarr)                        the store with time as float seconds since 1970 (refuses a store with no temperature_kind)
    teos10(sp, t, depth, lat, lon, kind)    p, SA, CT, rho, c from practical salinity and in-situ/potential temperature
    layers_to_z(values, dp, z)              hybrid layers -> fixed depths (linear between layer mid-points)
    read_lab_netcdf(path) / read_archv(stem, grid)   the two lab readers (read_b, read_a, read_grid underneath)
    check_node(store, nodes)                a store value vs the same node fetched from NCSS (needs the network); receipts()

Store layout (written once, read many; never stream per Monte-Carlo member): dims (time, depth, lat, lon); time float64
seconds since 1970-01-01 UTC; depth metres positive down; lat degrees north; **lon in [0, 360)** (GLBy's own convention),
because the TEPEX box crosses 180 deg and [-180, 180) would split it; the Environment layer takes lon mod 360. The one exception is a lab
store whose box lies within a grid step of 0 E (`box360` refuses a box across it, but the points that bracket it can lie across): its axis is
continuous with the box, so the neighbour across the seam is below 0 or above 360 (`_sub`), never wrapped back into a hole.
Everything that reads the store's lon takes the query into the axis's own frame (`conventions.wrap_about`).
Variables water_temp [degC, as the source wrote it], salinity [PSU], water_u / water_v [m/s east/north], surf_el [m],
rho [kg/m3 in situ, TEOS-10], c [m/s, TEOS-10]; NaN under the seafloor. Attribute temperature_kind says what
water_temp is; there is no default (hycom.org: GLBy writes in-situ, only the old GLBa wrote potential).

References: IOC/SCOR/IAPSO 2010, TEOS-10 manual (GSW toolbox, McDougall & Barker 2011 for the check values);
GOFS 3.1 GLBy0.08: hycom.org/dataserver/gofs-3pt1/analysis; HYCOM archive format: Bleck 2002 (Ocean Modelling 4) and
the HYCOM users guide (onem = 9806 Pa per metre, thref = 1e-3 m3/kg); xhycom docs (xhycom.readthedocs.io) for
thknss/9806 and the de-staggering of the C-grid velocities onto T-points; xhycom "Working with HYCOM data"
(xhycom.readthedocs.io/en/latest/analysis.html): an instantaneous archv stores the baroclinic velocity, total = u-vel. + u_btrop,
thknss [Pa] / 9806 = m, srfhgt [m2/s2] / 9.806 = m; NERSC abfile.py (github.com/nansencenter/NERSC-HYCOM-CICE, pythonlibs/abfile):
.b = 4 text lines, the 'iversn' 'iexpt' 'yrflag' 'idm' 'jdm' items, one column-heading line, then `%-9s=%11d%11.2f%3d%7.3f%16.7E%16.7E`
records; .a records padded to ((idm*jdm+4095)//4096)*4096 big-endian float32 words, values above 2**99 are land / no data;
regional.grid.b lists `plon:  min,max = a b` lines in record order.
"""
import concurrent.futures as cf, datetime as dt, functools, itertools, json, os, pathlib, re, shutil, subprocess, sys, threading, time
import urllib.parse, urllib.request
from collections.abc import Callable, Iterable, Iterator
from typing import Any

import numpy as np
from numpy.typing import NDArray

from . import conventions as cv, remote
from .environment import seconds

Box = tuple[float, float, float, float]
NCSS = "https://ncss.hycom.org/thredds/ncss/grid/GLBy0.08/expt_93.0"
DODS = "https://tds.hycom.org/thredds/dodsC/GLBy0.08/expt_93.0"
DATASETS = {"ts3z": ("water_temp", "salinity"), "uv3z": ("water_u", "water_v"), "ssh": ("surf_el",)}
VARS = ("water_temp", "salinity", "water_u", "water_v", "surf_el")
GOFS_DEPTHS = np.array([0, 2, 4, 6, 8, 10, 12, 15, 20, 25, 30, 35, 40, 45, 50, 60, 70, 80, 90, 100, 125, 150, 200, 250, 300, 350,
                        400, 500, 600, 700, 800, 900, 1000, 1250, 1500, 2000, 2500, 3000, 4000, 5000], float)
STEP_S = 3 * 3600.0                      # GOFS 3.1 analysis is 3-hourly
HYCOM_EPOCH = dt.datetime(2000, 1, 1, tzinfo=dt.timezone.utc).timestamp()
KINDS = ("in_situ", "potential")
ONEM = 9806.0                            # Pa per metre of seawater (HYCOM users guide)
THREF_ONEM = 9.806                       # thref * onem = 1e-3 m3/kg * 9806 Pa/m: srfhgt [m2/s2] -> sea surface height [m]
HUGE = 2.0 ** 100                        # HYCOM's "no data" in .a files
TEPEX_C_BOX = (-5.0, 5.0, 165.0, -165.0)          # (south, north, west, east), lon in any convention
SOCKET_S = 3600                          # NCSS can be silent for minutes while it works (measured 2026-10-29: 120-200 s before the first
                                         # byte for a 2-step request), so the child waits; the parent's deadline_s is the hard limit

# ------------------------------------------------------------------ boxes and times


def epoch(t: Any) -> float:
    """float seconds since 1970 from a float, a datetime (naive = UTC) or an ISO string."""
    if isinstance(t, str):
        t = dt.datetime.fromisoformat(t.replace("Z", "+00:00"))
    if isinstance(t, dt.datetime):
        return (t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)).timestamp()
    return float(t)


def box360(box: Any) -> Box:
    """(south, north, west, east) with west in [0, 360) and east = west + span. Refuses a box across 0 E / 360 E, which
    one GLBy request cannot cover (split it in two)."""
    s, n, w, e = (float(x) for x in box)
    if s >= n:
        raise ValueError(f"box south {s} must be below north {n}")
    if e - w > 360.0 + 1e-9:                                             # round 10, M-3 sibling: modulo 360 it would become a thin strip, fetched silently
        raise ValueError(f"box {cv.box_words(box)} is {e - w:g} degrees wide, more than the whole circle")
    span = (e - w) % 360.0 or 360.0
    w = w % 360.0
    if w + span > 360.0 + 1e-9:
        raise ValueError(f"box {cv.box_words(box)} crosses 0/360 E; GLBy longitudes start at 0, so fetch it as two boxes")
    return s, n, w, w + span


def padded(box: Any, pad: float = 2.0) -> Box:
    """The box grown by `pad` degrees on every side (latitude clipped to GLBy's -80..90)."""
    s, n, w, e = box360(box)
    return max(s - pad, -80.0), min(n + pad, 90.0), w - pad, e + pad


def gofs_steps(t0: Any, t1: Any) -> np.ndarray:
    """The 3-hourly GOFS times (epoch s, anchored on 00Z) that cover [t0, t1]: the last step at or before t0 to the first at or after t1, so the
    store spans the window (Ocean interpolates in time, and a window edge between two steps needs both). An aligned window gives its own steps."""
    return np.arange(np.floor(epoch(t0) / STEP_S) * STEP_S, np.ceil(epoch(t1) / STEP_S) * STEP_S + 1, STEP_S)


def _iso(t: float) -> str:
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ncss_url(dataset: str, names: tuple[str, ...], box: Box, ta: float, tb: float, base: str = NCSS) -> str:
    """THREDDS NetcdfSubset URL for `names` in the (0..360) box between epoch times ta and tb, all 40 depths."""
    s, n, w, e = box
    q = [("var", v) for v in names] + [("north", f"{n:.4f}"), ("south", f"{s:.4f}"), ("west", f"{w:.4f}"), ("east", f"{e:.4f}"),
                                       ("time_start", _iso(ta)), ("time_end", _iso(tb)), ("accept", "netcdf4")]
    year = dt.datetime.fromtimestamp(ta, dt.timezone.utc).year
    return f"{base}/{dataset}/{year}?" + urllib.parse.urlencode(q)


# ------------------------------------------------------------------ TEOS-10


def kind_of(kind: Any) -> str:
    """'in_situ' | 'potential'. Never guessed: None (or anything else) is an error that says how to fix it."""
    if kind not in KINDS:
        raise ValueError(f"temperature_kind is {kind!r}; it must be 'in_situ' or 'potential' and is never guessed. Pass "
                         "temperature_kind=... (GOFS 3.1 GLBy writes in-situ; ask the lab what their HYCOM writes) or set the "
                         "'temperature_kind' attribute on the file/store.")
    return str(kind)


def teos10(sp: Any, t: Any, depth: Any, lat: Any, lon: Any, kind: Any) -> dict[str, Any]:
    """-> dict(p [dbar], SA [g/kg], CT [degC], rho [kg/m3], c [m/s]). depth positive down [m]; broadcasts.
    in_situ: CT = gsw.CT_from_t(SA, t, p); potential (referenced to 0 dbar): CT = gsw.CT_from_pt(SA, t)."""
    import gsw
    kind_of(kind)
    p = gsw.p_from_z(-np.asarray(depth, float), lat)
    sa = gsw.SA_from_SP(sp, p, lon, lat)
    ct = gsw.CT_from_t(sa, t, p) if kind == "in_situ" else gsw.CT_from_pt(sa, t)
    return dict(p=p, SA=sa, CT=ct, rho=gsw.rho(sa, ct, p), c=gsw.sound_speed(sa, ct, p))


def add_teos(ds: Any, kind: str) -> Any:
    """ds (time, depth, lat, lon) + rho, c as float32. Cell-by-cell, no averaging."""
    r = teos10(ds.salinity.values, ds.water_temp.values, ds.depth.values[None, :, None, None],
               ds.lat.values[None, None, :, None], ds.lon.values[None, None, None, :], kind)
    for k, u, nm in (("rho", "kg m-3", "in-situ density, TEOS-10"), ("c", "m s-1", "sound speed, TEOS-10")):
        ds[k] = (("time", "depth", "lat", "lon"), r["rho" if k == "rho" else "c"].astype("f4"), dict(units=u, long_name=nm))
    return ds


# ------------------------------------------------------------------ the Zarr store


def _std(ds: Any, wrap: bool = True) -> Any:
    """A dataset with exactly the store's variables (surf_el, which has no depth, NaN if absent), float32, lon in [0, 360) (`wrap` False: as given,
    for a lon `_sub` has put in the frame of a box that touches 0 E), sorted, time in epoch s."""
    import xarray as xr
    lon = np.round(ds.lon.values.astype("float64"), 5)
    ds = ds.assign_coords(lon=np.mod(lon, 360.0) if wrap else lon, lat=np.round(ds.lat.values.astype("float64"), 5))
    ds = ds.sortby("lon").sortby("lat")                # float64 decimals, not float32 noise: a query at 179.84 must be inside a grid that starts there
    out = xr.Dataset(coords=dict(time=("time", ds.time.values.astype("float64"), dict(units="seconds since 1970-01-01T00:00:00Z")),
                                 depth=("depth", ds.depth.values.astype("float64"), dict(units="m", positive="down")),
                                 lat=("lat", ds.lat.values.astype("float64"), dict(units="degrees_north")),
                                 lon=("lon", ds.lon.values.astype("float64"), dict(units="degrees_east"))))
    shape = (ds.sizes["time"], ds.sizes["depth"], ds.sizes["lat"], ds.sizes["lon"])
    for v in VARS:
        d3 = v == "surf_el"
        dims = ("time", "lat", "lon") if d3 else ("time", "depth", "lat", "lon")
        a = ds[v].transpose(*dims).values if v in ds else np.full(shape[:1] + shape[2:] if d3 else shape, np.nan)
        out[v] = (dims, a.astype("f4"))
    return out


def _append(zarr_path: Any, ds: Any, first: bool, attrs: dict[str, Any]) -> None:
    chunks = (1, min(10, ds.sizes["depth"]), -(-ds.sizes["lat"] // 2), -(-ds.sizes["lon"] // 2))
    ds.attrs.update(attrs)                      # every append rewrites the group attributes, so every append carries them
    if first:
        enc = {v: dict(chunks=chunks[:1] + chunks[2:] if v == "surf_el" else chunks) for v in (*VARS, "rho", "c")}
        ds.to_zarr(zarr_path, mode="w", encoding=enc, consolidated=False)
    else:
        ds.to_zarr(zarr_path, mode="a", append_dim="time", consolidated=False)


def refuse_overlap(out_zarr: Any, source: Any) -> None:
    """Raise a ConfigError when the store `out_zarr` (or its `.tmp` sibling) is `source` or holds it. `write_store` removes the old store and the
    temporary with rmtree, so such a store would delete the data it was made from. A store that merely lies inside a source directory deletes nothing
    (the lab's files are read from the directory itself, not recursively, and each one is checked on its own against the store), so it is accepted. The
    paths are resolved first (symlinks, `..`)."""
    from ..config import ConfigError
    o, s = pathlib.Path(out_zarr).resolve(), pathlib.Path(source).resolve()
    for q in (o, o.with_name(o.name + ".tmp")):
        if q == s or q in s.parents:
            raise ConfigError(f"the store {out_zarr} and its source {source} are the same directory, or the store holds the source: "
                              "writing the store would delete the source. Name a store path of its own")


ZARR_MARKS = ("zarr.json", ".zgroup", ".zarray", ".zattrs")


def _chunks_dir(c: pathlib.Path) -> bool:
    """`c` is the chunk directory of a Zarr 3 array: it holds chunk keys (whole numbers, one per grid axis) and nothing else. A variable named `c` in a
    group (the sound speed of the ocean store) is a directory too, but it holds a `zarr.json` (v3) or a `.zarray` (v2) or its own chunk directory `c`.
    A Zarr 2 variable `c` whose metadata is lost holds chunk files named `0.0.0.0`: those have dots, so they are not chunk keys of a Zarr 3 array."""
    return c.is_dir() and any(c.iterdir()) and all(re.fullmatch(r"[0-9]+", q.name) for q in c.iterdir())


def _is_array(q: pathlib.Path) -> bool:
    """`q` is one Zarr array: v2 metadata, v3 metadata that says array, or (metadata lost) a chunk directory."""
    try:
        meta = json.loads((q / "zarr.json").read_text()).get("node_type") if (q / "zarr.json").is_file() else None
    except (OSError, ValueError, AttributeError):
        meta = None
    return (q / ".zarray").exists() or meta == "array" or (meta is None and _chunks_dir(q / "c"))


def looks_like_zarr(d: pathlib.Path) -> bool:
    """True when the directory `d` is a Zarr store, or the remains of one: a mark file in `d` itself (the group's metadata), or one of its subdirectories
    is an array of the store (its variables; a store that lost its top `zarr.json`, or all its metadata, still has them, and is the thing `unreadable`
    says to write again). A directory that holds other stores is not one: each of them is a group, not an array, so replacing it would delete them."""
    return any((d / m).exists() for m in ZARR_MARKS) or any(_is_array(c) for c in d.iterdir() if c.is_dir())


def write_store(steps: Any, out_zarr: Any, kind: Any, attrs: dict[str, Any]) -> pathlib.Path:
    """steps: iterable of standardized one-time datasets (see _std). Adds rho/c, writes atomically (tmp dir, then rename). An existing `out_zarr` is
    replaced only when it is empty or `looks_like_zarr` (a damaged store too, so ingest-ocean can repair it): any other directory is refused first."""
    from ..config import ConfigError
    kind_of(kind)
    out = pathlib.Path(out_zarr)
    if out.is_dir() and any(out.iterdir()) and not looks_like_zarr(out):
        raise ConfigError(f"{out} exists, is not empty and holds no Zarr metadata or chunks: it would be deleted to make room for the store. "
                          "Move it away or name another path")
    tmp = out.with_name(out.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    n = 0
    for ds in steps:
        meta = dict(attrs, temperature_kind=kind, lon_convention="0..360 degrees east (continuous with the box where it touches 0 E)",
                    depth_convention="metres, positive down", time_convention="float seconds since 1970-01-01 UTC; open with decode_times=False")
        _append(tmp, add_teos(ds, kind), n == 0, meta)
        n += 1
    if n == 0:
        raise ValueError("no time steps to write")
    shutil.rmtree(out, ignore_errors=True)
    os.replace(tmp, out)
    return out


def unreadable(path: Any, e: Exception, lab: bool | None = None) -> Exception:
    """The ConfigError for a store (or a chunk of it) that cannot be read: it names the store itself and the repair. lab: the store is the lab's HYCOM,
    which the pipeline cannot download again (deleting it would destroy the only copy); None: by the name, `gofs*` is the one the pipeline fetched."""
    from ..config import ConfigError
    p = pathlib.Path(path)
    if lab is None:
        lab = not p.name.startswith("gofs")
    fix = (f"restore {p} from the lab's source (`python -m cafe.pm ingest-ocean --mission ... --path DIR --temperature-kind K` writes it); "
           "the pipeline cannot download it" if lab else
           f"delete {p} and run `python -m cafe.pm fetch --mission ...` again: only that part is downloaded again")
    return ConfigError(f"environment cache file {p} cannot be read ({type(e).__name__}: {e}); {fix}")


def open_store(path: Any, cache: bool = True, lab: bool | None = None) -> Any:
    """The Zarr store, time as float seconds. Refuses a store without a valid temperature_kind attribute. cache False: xarray keeps no copy of a
    variable it has read (env.ocean.Ocean keeps its own float32 one, and xarray's would be a second copy of every field, pickled into each worker).
    lab: see `unreadable`."""
    import xarray as xr
    try:
        ds = (xr.open_zarr(path, decode_times=False, consolidated=False) if cache else
              xr.open_dataset(path, engine="zarr", decode_times=False, consolidated=False, cache=False))      # open_zarr has no `cache`
    except Exception as e:                                                # noqa: BLE001  a missing or unreadable store is one advice
        raise unreadable(path, e, lab) from e
    kind_of(ds.attrs.get("temperature_kind"))
    return ds


# ------------------------------------------------------------------ fetching GOFS (hard deadlines, resumable, hashed)


class FetchError(RuntimeError):
    """Some parts could not be fetched from any server; the finished parts are kept, so rerunning resumes."""


def _child(args: list[Any], deadline: float) -> None:
    """Run `python -m cafe.pm.env.hycom <args>` and kill it after `deadline` s (a hung HTTP/OPeNDAP read cannot be interrupted
    from inside the process; cafe/ocean.py learned this from tds.hycom.org, which accepts a connection and never answers).
    TimeoutError: no answer in time. RuntimeError: the child failed."""
    try:
        r = subprocess.run([sys.executable, "-m", "cafe.pm.env.hycom", *map(str, args)], capture_output=True, text=True,
                           timeout=deadline, cwd=remote.ROOT)
    except subprocess.TimeoutExpired:
        raise TimeoutError(f"no answer within {deadline:.0f} s") from None
    if r.returncode:
        raise RuntimeError((r.stderr.strip().splitlines() or [f"exit {r.returncode}"])[-1][:300])


def _child_ncss(url: str, out: str) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "cafe-premission"})
    part = out + ".part"
    with urllib.request.urlopen(req, context=remote.context(), timeout=SOCKET_S) as r, open(part, "wb") as f:
        shutil.copyfileobj(r, f, 1 << 20)
    with open(part, "rb") as f:
        head = f.read(200)
    if not (head.startswith(b"\x89HDF") or head.startswith(b"CDF")):
        raise ValueError("server answered with something that is not NetCDF: " + head.decode(errors="replace")[:150])
    os.replace(part, out)


def _child_dods(url: str, names: str, ta: float | str, tb: float | str, s: float | str, n: float | str, w: float | str, e: float | str, out: str) -> None:
    """OPeNDAP read of the same box into a NetCDF part with the NCSS names (time in hours since 2000-01-01)."""
    import netCDF4
    ds = netCDF4.Dataset(url)
    th = np.asarray(ds["time"][:], float)
    lat, lon = np.asarray(ds["lat"][:], float), np.asarray(ds["lon"][:], float)
    k = np.where((th * 3600 + HYCOM_EPOCH >= float(ta) - 1) & (th * 3600 + HYCOM_EPOCH <= float(tb) + 1))[0]
    j = np.where((lat >= float(s) - 0.05) & (lat <= float(n) + 0.05))[0]
    i = np.where((lon >= float(w) - 0.05) & (lon <= float(e) + 0.05))[0]
    if not (len(k) and len(j) and len(i)):
        raise ValueError("OPeNDAP dataset has no data for this box/time")
    out_ds = netCDF4.Dataset(out + ".part", "w")
    has_depth = any(ds[v].ndim == 4 for v in names.split(","))
    axes = [("time", th[k])] + ([("depth", np.asarray(ds["depth"][:], float))] if has_depth else []) + [("lat", lat[j]), ("lon", lon[i])]
    for nm, arr in axes:                            # the ssh dataset has no depth axis
        out_ds.createDimension(nm, len(arr))
        out_ds.createVariable(nm, "f8", (nm,))[:] = arr
    out_ds["time"].units = "hours since 2000-01-01 00:00:00"
    for nm in names.split(","):
        v = ds[nm]
        dims = ("time", "lat", "lon") if v.ndim == 3 else ("time", "depth", "lat", "lon")
        o = out_ds.createVariable(nm, "f4", dims, zlib=True, fill_value=np.float32(np.nan))
        for n_, kk in enumerate(k):                 # one time step per read: a 4-step read failed with "DAP failure" on tds.hycom.org
            sl = (kk,) + ((slice(None),) if v.ndim == 4 else ()) + (slice(j[0], j[-1] + 1), slice(i[0], i[-1] + 1))
            o[n_] = np.ma.filled(v[sl].astype("f4"), np.nan)
    out_ds.close()
    os.replace(out + ".part", out)


def _sha(path: str | pathlib.Path) -> str:
    return remote.sha256(path)


def _write_json(path: Any, obj: Any) -> None:
    """`obj` as JSON in `path` through `config.write_json`, the one writer (a temporary and os.replace; round 13, M-14)."""
    from ..config import write_json
    write_json(pathlib.Path(path), obj, indent=1, sort_keys=True)


def _chunks(steps: Iterable[float], n: int) -> list[list[float]]:
    """Lists of at most n consecutive steps that do not span a calendar year (each GLBy file is one year)."""
    out: list[list[float]] = []
    cur: list[float] = []
    for t in steps:
        if cur and (len(cur) == n or dt.datetime.fromtimestamp(t, dt.timezone.utc).year != dt.datetime.fromtimestamp(cur[0], dt.timezone.utc).year):
            out.append(cur)
            cur = []
        cur.append(t)
    return out + [cur] if cur else out


def fetch_gofs(box: Any, t0: Any, t1: Any, out_dir: Any, *, chunk_steps: int = 1, deadline_s: float = 1500.0, servers: tuple[str, ...] = ("ncss", "opendap"),
               workers: int = 3, tries: int = 2, ncss: str = NCSS, dods: str = DODS, name: str = "gofs_tepex_c", keep_parts: bool = True,
               log: Callable[[str], None] = print) -> pathlib.Path:
    """GOFS 3.1 GLBy0.08 expt_93.0 water_temp/salinity/water_u/water_v/surf_el for `box` (south, north, west, east; any lon
    convention, pad it yourself: see padded()) and t0..t1 (the 3-hourly steps that cover it, see gofs_steps) -> <out_dir>/<name>.zarr.

    The request list is cut by time into `chunk_steps`-step parts per dataset (default one 3-hourly step) so one hung request loses
    only its part; every request runs in a child killed after `deadline_s`. Measured on 2026-10-29 for the 14 x 34 deg, 40-level box:
    NCSS answers one step of water_temp + salinity in 193 s at best, not at all within 600 s at worst, and a 2-step request is cut by
    the server with HTTP 500 after 302 s; OPeNDAP takes 310-335 s per step of two variables, in parallel too, and a 4-step read failed
    with "DAP failure". Hence one step per request, and the order of `servers` is the caller's call.
    A part is fetched from `servers` in order ('ncss' = ncss.hycom.org NetcdfSubset, 'opendap' = tds.hycom.org), `tries` times each;
    the server that answered, bytes, seconds and SHA-256 go in <out_dir>/<name>.parts/manifest.json, with the box the parts were cut to.
    Rerunning skips parts whose file hash matches the manifest, unless the box differs from the manifest's: then every part is fetched again.
    Parts that fail on every server raise FetchError after all the others finished. Returns the Zarr path."""
    box = box360(box)
    steps = gofs_steps(t0, t1)
    if len(steps) == 0:
        raise ValueError("no 3-hourly GOFS step between t0 and t1")
    out_dir = pathlib.Path(out_dir)
    pdir = out_dir / f"{name}.parts"
    pdir.mkdir(parents=True, exist_ok=True)
    mpath = pdir / "manifest.json"
    man = json.loads(mpath.read_text()) if mpath.exists() else {}
    lock = threading.Lock()
    jobs = [(d, c) for d in DATASETS for c in _chunks(steps, chunk_steps)]
    if man.get("parts") and man.get("box") != list(box):             # parts cut to another box are not this box's: a part is reused by name and hash only
        log(f"the ocean parts were cut to {man.get('box')}, this fetch asks for {list(box)}: all {len(jobs)} parts are fetched again")
        man["parts"] = {}
    man.update(box=list(box), t0=float(steps[0]), t1=float(steps[-1]), dataset="GOFS 3.1 GLBy0.08 expt_93.0", parts=man.get("parts", {}))

    def one(job: tuple[str, list[float]]) -> str | None:
        d, c = job
        fn = f"{d}_{_iso(c[0]).replace(':', '')}_{_iso(c[-1]).replace(':', '')}.nc"
        path = pdir / fn
        rec = man["parts"].get(fn)
        if rec and path.exists() and _sha(path) == rec["sha256"]:
            return None
        errs: list[str] = []
        for srv in servers:
            for _ in range(tries):
                t = time.time()
                try:
                    if srv == "ncss":
                        _child(["_ncss", ncss_url(d, DATASETS[d], box, c[0], c[-1], ncss), path], deadline_s)
                    else:
                        _child(["_dods", f"{dods}/{d}/{dt.datetime.fromtimestamp(c[0], dt.timezone.utc).year}", ",".join(DATASETS[d]),
                                c[0], c[-1], *box, path], deadline_s)
                except (TimeoutError, RuntimeError) as ex:
                    errs.append(f"{srv}: {ex}")
                    continue
                with lock:
                    man["parts"][fn] = dict(dataset=d, server=srv, bytes=path.stat().st_size, sha256=_sha(path), t_start=c[0], t_end=c[-1],
                                            seconds=round(time.time() - t, 1), n_steps=len(c), failed_first=errs)
                    _write_json(mpath, man)
                return None
        return f"{fn}: " + "; ".join(errs)

    with cf.ThreadPoolExecutor(workers) as ex:
        failed = [r for r in ex.map(one, jobs) if r]
    if failed:
        raise FetchError(f"{len(failed)} of {len(jobs)} parts failed on every server (finished parts kept; rerun to resume):\n" + "\n".join(failed))
    _write_json(mpath, man)
    out = assemble_gofs(pdir, steps, out_dir / f"{name}.zarr")
    if not keep_parts:
        for f in pdir.glob("*.nc"):
            f.unlink()
    return out


def assemble_gofs(pdir: Any, steps: Any, out_zarr: Any) -> pathlib.Path:
    """The parts in `pdir` (checked against manifest.json hashes) -> Zarr with rho and c. One time step in memory at a time."""
    import xarray as xr
    pdir = pathlib.Path(pdir)
    refuse_overlap(out_zarr, pdir)                                           # the parts are hours of download; the store replaces its predecessor with rmtree
    man = json.loads((pdir / "manifest.json").read_text())
    for fn, rec in man["parts"].items():
        if _sha(pdir / fn) != rec["sha256"]:
            raise ValueError(f"{pdir / fn}: SHA-256 differs from the manifest; delete it and rerun fetch_gofs to fetch that part again")
    opened: dict[str, Any] = {}
    bad: dict[str, str] = {}
    for fn in man["parts"]:
        try:
            a = xr.open_dataset(pdir / fn)
            if a.sizes.get("time", 0) == 0:
                raise ValueError("no time step in it")
            opened[fn] = a.assign_coords(lat=np.round(a.lat.values.astype("float64"), 4), lon=np.round(a.lon.values.astype("float64"), 4))
        except Exception as e:                                        # noqa: BLE001  netCDF4 raises OSError, RuntimeError, ValueError ...
            bad[fn] = f"{type(e).__name__}: {e}"
    if bad:                                                           # a part recorded by its hash is never fetched again: take each one and its entry out
        for fn in bad:
            (pdir / fn).unlink(missing_ok=True)
            del man["parts"][fn]
        _write_json(pdir / "manifest.json", man)
        one = len(bad) == 1
        raise FetchError("; ".join(f"the part {fn} was unusable ({why})" for fn, why in bad.items())
                         + f"; {'it has' if one else 'they have'} been removed: rerun fetch to download {'it' if one else 'them'} again")
    per = {}
    for d in DATASETS:
        names = sorted(fn for fn, r in man["parts"].items() if r["dataset"] == d)
        if not names:
            raise ValueError(f"no {d} parts in {pdir}")
        try:                                                          # join="exact": parts of different boxes never become NaN holes (the outer default did)
            a = xr.concat([opened[fn] for fn in names], dim="time", join="exact").sortby("time")
        except ValueError as e:
            raise ValueError(f"the {d} parts in {pdir} were cut to different boxes ({e}); delete {pdir} and run fetch again") from e
        per[d] = a.isel(time=~a.indexes["time"].duplicated())
    joined = xr.merge([per[d] for d in DATASETS], join="inner", compat="override")
    t = seconds(joined.time.values)
    missing = sorted(set(map(float, steps)) - set(map(float, t)))
    if missing:
        raise ValueError(f"{len(missing)} GOFS steps are missing from the parts (first {_iso(missing[0])}); rerun fetch_gofs")
    joined = joined.assign_coords(time=t).sel(time=steps)
    used = {r["server"] for r in man["parts"].values()}
    attrs = dict(source=man["dataset"], served_by=json.dumps(sorted(used)), manifest_sha256=_sha(pdir / "manifest.json"),
                 box=json.dumps(man["box"]), url_ncss=NCSS, url_opendap=DODS)
    return write_store((_std(joined.isel(time=slice(i, i + 1)).load()) for i in range(joined.sizes["time"])),
                       out_zarr, "in_situ", attrs)


# ------------------------------------------------------------------ hybrid layers -> z-levels


def layers_to_z(values: Any, dp: Any, z: Any) -> np.ndarray:
    """Layered field -> fixed depths. values, dp: (K, ...) with dp the layer thickness in metres (>= 0, 0 = vanished layer);
    z: (L,) depths [m]. Linear between layer mid-points, constant above the first and below the last valid mid-point, NaN
    below the seafloor (sum of dp) and where no layer has data. Returns (L, ...).
    (Same piecewise-linear-in-mid-point idea as HYCOM's own z-level interpolation; xhycom offers conservative or linear.)"""
    values = np.asarray(values, float)
    dp = np.nan_to_num(np.asarray(dp, float), nan=0.0).clip(min=0.0)
    top = np.cumsum(dp, axis=0) - dp
    valid = (dp > 1e-6) & np.isfinite(values)
    mid = np.where(valid, top + dp / 2, np.inf)
    order = np.argsort(mid, axis=0, kind="stable")
    mid, val = np.take_along_axis(mid, order, 0), np.take_along_axis(np.where(valid, values, 0.0), order, 0)
    nv, bottom = valid.sum(0), dp.sum(0)
    out = []
    for zt in np.asarray(z, float):
        idx = (mid < zt).sum(0)
        k1, k0 = np.minimum(idx, np.maximum(nv - 1, 0))[None], np.maximum(idx - 1, 0)[None]
        z0, z1 = (np.nan_to_num(np.take_along_axis(mid, k, 0)[0], posinf=0.0) for k in (k0, k1))
        v0, v1 = np.take_along_axis(val, k0, 0)[0], np.take_along_axis(val, k1, 0)[0]
        w = ((zt - z0) / np.where(z1 > z0, z1 - z0, 1.0)).clip(0, 1) * (z1 > z0)
        out.append(np.where((nv > 0) & (zt <= bottom + 1e-6), v0 + w * (v1 - v0), np.nan))
    return np.stack(out)


# ------------------------------------------------------------------ lab reader (a): per-snapshot netCDF

ALIASES = dict(temp=("water_temp", "temperature", "temp", "thetao"), salt=("salinity", "salin", "salt", "so"),
               u=("water_u", "u-velocity", "u_velocity", "u", "uo"), v=("water_v", "v-velocity", "v_velocity", "v", "vo"),
               ssh=("surf_el", "ssh", "zos"), dp=("thknss", "dp", "layer_thickness"))
DIMS = dict(time=("time", "MT", "Time", "t"), z=("depth", "Depth", "lev", "z", "layer", "Layer", "k"),
            lat=("lat", "latitude", "Latitude"), lon=("lon", "longitude", "Longitude"))
Z_NAMES = ("depth", "Depth", "lev", "z")
PA_UNITS = ("pa", "pascal")


def describe(ds: Any) -> dict[str, Any]:
    """The dict hycom_netcdf.json validates: dims, variables (dims, units), global attributes (strings only)."""
    return dict(dims={k: int(v) for k, v in ds.sizes.items()},
                variables={k: dict(dims=list(v.dims), units=str(v.attrs.get("units", "")) or None) for k, v in {**ds.data_vars, **ds.coords}.items()},
                attrs={k: str(v) for k, v in ds.attrs.items()})


def _schema(name: str) -> dict[str, Any]:
    d: dict[str, Any] = json.loads((remote.ROOT / "cafe" / "schemas" / name).read_text())
    return d


def validate_netcdf(ds: Any) -> None:
    """Raise ValueError listing every way `ds` does not meet cafe/schemas/hycom_netcdf.json."""
    import jsonschema
    errs = sorted(jsonschema.Draft202012Validator(_schema("hycom_netcdf.json")).iter_errors(describe(ds)), key=lambda e: list(e.path))
    if errs:
        raise ValueError("not a readable lab HYCOM netCDF (cafe/schemas/hycom_netcdf.json):\n" + "\n".join(
            f"  {'/'.join(map(str, e.path)) or '(file)'}: {e.message[:200]}" for e in errs))


def _pick(ds: Any, key: str) -> str | None:
    for n in ALIASES[key]:
        if n in ds.variables:
            return n
    return None


def _dim(v: Any, key: str) -> str | None:
    ds = [d for d in v.dims if d in DIMS[key]]
    return ds[0] if ds else None


def read_lab_netcdf(path: Any, temperature_kind: Any = None, depth: Any = None) -> tuple[Any, str]:
    """One per-snapshot lab HYCOM netCDF -> (standardized dataset, temperature_kind); cafe/schemas/hycom_netcdf.json says what is
    assumed. z-level files (a 1-D depth coordinate in metres, positive down, in any order) keep their own levels unless `depth` is given;
    layered files (a thickness variable thknss/dp in Pa or m) go to `depth` (default GOFS_DEPTHS) with layers_to_z.
    Velocities are total (not baroclinic), on T-points, east/north. The kind comes from the argument, else the file's
    temperature_kind attribute (global or on the temperature variable), else it is an error."""
    import xarray as xr
    ds = xr.open_dataset(path)
    validate_netcdf(ds)
    tn = _pick(ds, "temp")
    kind = kind_of(temperature_kind or ds.attrs.get("temperature_kind") or ds[tn].attrs.get("temperature_kind"))
    dim = {k: _dim(ds[tn], k) for k in DIMS}
    if None in dim.values():
        raise ValueError(f"{path}: {tn} has dims {ds[tn].dims}; needs one each of time {DIMS['time']}, vertical {DIMS['z']}, "
                         f"lat {DIMS['lat']}, lon {DIMS['lon']} (curvilinear 2-D lat/lon files must be regridded to lon/lat first: xhycom.regrid)")
    if not np.issubdtype(ds[dim["time"]].dtype, np.datetime64):
        raise ValueError(f"{path}: the time coordinate must be decodable (CF units such as 'hours since 2000-01-01')")
    nm = {k: _pick(ds, k) for k in ALIASES}
    order = (dim["time"], dim["z"], dim["lat"], dim["lon"])
    layered = nm["dp"] is not None
    if layered:
        dpv = ds[nm["dp"]].transpose(*order).values.astype(float)
        dpv = dpv / ONEM if str(ds[nm["dp"]].attrs["units"]).lower() in PA_UNITS else dpv
        depth = GOFS_DEPTHS if depth is None else depth
    else:
        ds = ds.sortby(dim["z"])                    # _to_levels searches zc ascending: a file that lists the deepest level first read as all NaN
        zc = ds[dim["z"]].values.astype(float)
        if (zc < 0).any():
            raise ValueError(f"{path}: depth must be positive down (found negative values); flip it before ingest")
        depth = zc if depth is None else depth
    depth = np.asarray(depth, float)
    res = xr.Dataset(coords=dict(time=seconds(ds[dim["time"]].values),
                                 depth=depth, lat=ds[dim["lat"]].values, lon=ds[dim["lon"]].values))
    for k, n in (("temp", "water_temp"), ("salt", "salinity"), ("u", "water_u"), ("v", "water_v")):
        a = ds[nm[k]].transpose(*order).values.astype(float)
        a = np.stack([layers_to_z(a[i], dpv[i], depth) if layered else _to_levels(a[i], zc, depth) for i in range(a.shape[0])])
        res[n] = (("time", "depth", "lat", "lon"), a)
    if nm["ssh"]:
        res["surf_el"] = (("time", "lat", "lon"), ds[nm["ssh"]].transpose(dim["time"], dim["lat"], dim["lon"]).values.astype(float))
    return res, kind


def _to_levels(a: NDArray[Any], zc: NDArray[Any], depth: NDArray[Any]) -> NDArray[Any]:
    """z-level profile (Z, ...) on depths zc -> `depth`: exact where the levels coincide, linear between, NaN outside."""
    flat = a.reshape(a.shape[0], -1)
    out = np.full((len(depth), flat.shape[1]), np.nan)
    for i, zt in enumerate(depth):
        j = np.searchsorted(zc, zt - 1e-6)
        if j < len(zc) and abs(zc[j] - zt) < 1e-6:
            out[i] = flat[j]
        elif 0 < j < len(zc):
            out[i] = flat[j - 1] + (zt - zc[j - 1]) / (zc[j] - zc[j - 1]) * (flat[j] - flat[j - 1])
    return out.reshape((len(depth),) + a.shape[1:])


# ------------------------------------------------------------------ lab reader (b): archv .a/.b


def read_b(path: Any) -> dict[str, Any]:
    """Parse a HYCOM .b file -> dict(header={name: number}, idm, jdm, fields=[{name, step, day, k, dens, min, max}]).
    Header lines look like `   17  'iversn' = hycom version number x10`; the field table follows the line starting
    `field` with one `name = step day k dens min max` line per record of the .a file, in file order. Validated against
    cafe/schemas/hycom_ab.json."""
    import jsonschema
    header: dict[str, Any] = {}
    fields: list[dict[str, Any]] = []
    table = False
    for ln in pathlib.Path(path).read_text().splitlines():
        if table and "=" in ln:
            name, rest = ln.split("=", 1)
            f = rest.split()
            if len(f) == 6:
                fields.append(dict(name=name.strip(), step=int(f[0]), day=float(f[1]), k=int(f[2]), dens=float(f[3]), min=float(f[4]), max=float(f[5])))
        elif ln.strip().startswith("field"):
            table = True
        else:
            m = re.match(r"\s*([-+0-9.eE]+)\s+'(\w+)\s*'\s*=", ln)
            if m:
                header[m.group(2)] = float(m.group(1)) if "." in m.group(1) else int(m.group(1))
    doc = dict(header=header, idm=header.get("idm"), jdm=header.get("jdm"), fields=fields)
    errs = sorted(jsonschema.Draft202012Validator(_schema("hycom_ab.json")).iter_errors(doc), key=lambda e: list(e.path))
    if errs:
        raise ValueError(f"{path} is not a HYCOM archv .b file (cafe/schemas/hycom_ab.json): " + "; ".join(e.message[:150] for e in errs[:3]))
    return doc


def read_a(path: Any, doc: dict[str, Any], idx: int) -> NDArray[Any]:
    """Record `idx` of the .a file as (jdm, idm) float32 with HYCOM's 2**100 'no data' as NaN. Each record is idm*jdm
    big-endian float32 words padded up to a multiple of 4096 words."""
    n = doc["idm"] * doc["jdm"]
    rec = -(-n // 4096) * 4096
    size = pathlib.Path(path).stat().st_size
    if size != rec * 4 * len(doc["fields"]):
        raise ValueError(f"{path}: {size} bytes, but the .b lists {len(doc['fields'])} records of {rec} words = {rec * 4 * len(doc['fields'])} bytes")
    a = np.fromfile(path, ">f4", count=n, offset=idx * rec * 4).astype("f4").reshape(doc["jdm"], doc["idm"])
    return np.where(a > 0.5 * HUGE, np.nan, a)


def read_grid(path: Any) -> dict[str, NDArray[Any]]:
    """regional.grid.a/.b -> dict(plon, plat, pang), each (jdm, idm). Record order is the order of the `name: min,max` lines.
    Refuses curvilinear grids (lon varying with j, or lat with i)."""
    b = pathlib.Path(str(path) + ".b").read_text().splitlines()
    names = [m.group(1) for m in (re.match(r"\s*(\w+):\s+min,max\s*=", ln) for ln in b) if m]
    dims = {m.group(2): int(m.group(1)) for m in (re.match(r"\s*(\d+)\s+'(\w+)\s*'", ln) for ln in b) if m}
    doc = dict(idm=dims["idm"], jdm=dims["jdm"], fields=names)
    g = {n: read_a(str(path) + ".a", doc, i) for i, n in enumerate(names) if n in ("plon", "plat", "pang")}
    if not {"plon", "plat"} <= set(g):
        raise ValueError(f"{path}.b has no plon/plat records")
    if not (np.allclose(g["plat"], g["plat"][:, :1], atol=1e-4) and np.allclose(g["plon"], g["plon"][:1], atol=1e-4)):
        raise ValueError("curvilinear lab grid (lon varies with j or lat with i): regrid it to lon/lat first (xhycom.regrid)")
    g.setdefault("pang", np.zeros_like(g["plon"]))
    return g


def model_day_to_epoch(day: float, yrflag: int) -> float:
    """HYCOM model day -> epoch seconds. Only yrflag 3 (real calendar, day 1.0 = 1901-01-01 00:00 UTC) is implemented."""
    if yrflag != 3:
        raise ValueError(f"yrflag {yrflag} (not the real calendar) is not supported; pass time=<epoch seconds> to override")
    return (dt.datetime(1900, 12, 31, tzinfo=dt.timezone.utc) + dt.timedelta(days=float(day))).timestamp()


def destagger(u: NDArray[Any], v: NDArray[Any]) -> tuple[NDArray[Any], NDArray[Any]]:
    """C-grid u (west face) and v (south face) -> T-points, (jdm, idm): T(i) = (u(i) + u(i+1)) / 2; the last column / row
    has no neighbour and becomes NaN (as in xhycom)."""
    ut, vt = np.full_like(u, np.nan), np.full_like(v, np.nan)
    ut[:, :-1] = 0.5 * (u[:, :-1] + u[:, 1:])
    vt[:-1] = 0.5 * (v[:-1] + v[1:])
    return ut, vt


def read_archv(path: Any, grid: Any, temperature_kind: Any = None, depth: Any = None, box: Any = None, time: Any = None) -> tuple[Any, str]:
    """One archv .a/.b (path = the stem) -> (standardized dataset with one time, temperature_kind) on `depth` (default
    GOFS_DEPTHS). `grid` = stem of regional.grid. Records are read one at a time and cut to `box` (lon/lat +-0.5 deg) at once.
    Total velocity = baroclinic `u-vel.` + barotropic `u_btrop` (HYCOM stores them separately), destaggered to T-points and
    rotated to east/north with pang; thknss [Pa] / 9806 = layer thickness [m]; srfhgt [m2/s2] / 9.806 = sea surface height [m]."""
    import xarray as xr
    kind = kind_of(temperature_kind)
    depth = GOFS_DEPTHS if depth is None else np.asarray(depth, float)
    doc = read_b(str(path) + ".b")
    g = read_grid(grid)
    if g["plon"].shape != (doc["jdm"], doc["idm"]):
        raise ValueError(f"{path} is {doc['idm']}x{doc['jdm']} but the grid is {g['plon'].shape[1]}x{g['plon'].shape[0]}")
    index = {(f["name"], f["k"]): i for i, f in enumerate(doc["fields"])}

    def rec(name: str, k: int = 0) -> NDArray[Any]:
        if (name, k) not in index:
            raise ValueError(f"{path}.b has no '{name}' record for layer {k}")
        return read_a(str(path) + ".a", doc, index[(name, k)])
    lon, lat = np.mod(g["plon"][0], 360.0), g["plat"][:, 0]
    jj, ii = np.arange(len(lat)), np.arange(len(lon))
    if box is not None:
        s, n, w, e = box360(box)
        ll = cv.wrap_about(lon, 0.5 * (w + e))                # the frame of the box, as `_sub` cuts in: a neighbour across 0 E is below 0 or above 360
        jj = np.flatnonzero(((lat >= s - 0.5) & (lat <= n + 0.5)) | _cut(lat, s, n))          # 0.5 deg around the box, and the bracket `_sub` will ask for
        ii = np.flatnonzero(((ll >= w - 0.5) & (ll <= e + 0.5)) | _cut(ll, w, e))             # of a grid coarser than that
        if len(ii) == 0 or len(jj) == 0:
            raise ValueError(f"{path}: the grid has no points inside the box ({cv.box_words(box)})")
    sel, ang = np.ix_(jj, ii), np.radians(g["pang"])
    has_bt = ("u_btrop", 0) in index
    kdm = max(f["k"] for f in doc["fields"] if f["name"] == "thknss")
    got: dict[str, list[Any]] = {n: [] for n in ("temp", "salin", "u", "v", "dp")}
    for k in range(1, kdm + 1):
        u, v = rec("u-vel.", k), rec("v-vel.", k)
        if has_bt:
            u, v = u + rec("u_btrop"), v + rec("v_btrop")
        ut, vt = destagger(u, v)
        ue, vn = cv.rotate_grid_to_earth(ut, vt, np.cos(ang), np.sin(ang))
        got["u"].append(ue[sel]); got["v"].append(vn[sel])
        got["temp"].append(rec("temp", k)[sel]); got["salin"].append(rec("salin", k)[sel]); got["dp"].append(rec("thknss", k)[sel] / ONEM)
    dp = np.stack(got["dp"])
    t = time if time is not None else model_day_to_epoch(doc["fields"][0]["day"], doc["header"].get("yrflag", 3))
    ds = xr.Dataset(coords=dict(time=[float(t)], depth=depth, lat=lat[jj], lon=lon[ii]))
    for out, src in (("water_temp", "temp"), ("salinity", "salin"), ("water_u", "u"), ("water_v", "v")):
        ds[out] = (("time", "depth", "lat", "lon"), layers_to_z(np.stack(got[src]), dp, depth)[None])
    if ("srfhgt", 0) in index:
        ds["surf_el"] = (("time", "lat", "lon"), (rec("srfhgt")[sel] / THREF_ONEM)[None])
    return ds, kind


# ------------------------------------------------------------------ ingest


def _cut(pos: Any, lo: float, hi: float, pad: float = 0.1) -> Any:
    """Mask of the points of `pos` inside [lo - pad, hi + pad] and, so that the store always brackets the box whatever the grid (the ingest check wants
    an edge within `pad` of the box edge), the nearest point beyond an edge when the nearest kept one lies more than `pad` inside it, or when none is
    kept (a grid coarser than the box): then both neighbours, or nothing when the grid does not reach both sides. `pos` is in one frame with
    `lo`, `hi` (`_sub` puts the longitudes there)."""
    keep = (pos >= lo - pad) & (pos <= hi + pad)
    mid = 0.5 * (lo + hi)
    near, far = np.flatnonzero(~keep & (pos < mid)), np.flatnonzero(~keep & (pos >= mid))
    below, above = (near[np.argmax(pos[near])] if len(near) else None), (far[np.argmin(pos[far])] if len(far) else None)
    if not keep.any():
        if below is not None and above is not None:
            keep[[below, above]] = True
        return keep
    add_below, add_above = pos[keep].min() > lo + pad, pos[keep].max() < hi - pad
    if below is not None and add_below:
        keep[below] = True
    if above is not None and add_above:
        keep[above] = True
    return keep


def _sub(ds: Any, box: Any) -> Any:
    """Cut a dataset to the box, padded by 0.1 deg, plus the nearest point beyond an edge where the grid is too coarse for the pad to reach it
    (`_cut`). The longitudes come back in the box's frame (`box360`'s west and east): the file's own convention does not matter, a box across the
    dateline stays continuous, and a neighbour across 0 E (a box within a grid step of it) is below 0 or above 360 instead of wrapped into a hole."""
    s, n, w, e = box360(box)
    lon = cv.wrap_about(ds.lon.values, 0.5 * (w + e))
    ds = ds.assign_coords(lon=lon).isel(lon=np.flatnonzero(_cut(lon, w, e))).sortby("lat")
    ds = ds.isel(lat=np.flatnonzero(_cut(ds.lat.values, s, n)))
    if ds.sizes["lon"] == 0 or ds.sizes["lat"] == 0:
        raise ValueError(f"no lab-HYCOM points inside the box ({cv.box_words(box)})")
    return ds


def _snapshot_times(label: pathlib.Path) -> list[float]:
    """The epoch seconds of the time steps of one lab snapshot (a netCDF file or an archv stem), read without its fields; [] when they cannot be
    read, which the reader then reports by name."""
    import xarray as xr
    try:
        if label.suffix == ".nc":
            with xr.open_dataset(label) as ds:
                tc = _dim(ds[_pick(ds, "temp") or ""], "time") or ""
                return [float(t) for t in seconds(ds[tc].values)] if np.issubdtype(ds[tc].dtype, np.datetime64) else []
        doc = read_b(str(label) + ".b")
        return [model_day_to_epoch(doc["fields"][0]["day"], doc["header"].get("yrflag", 3))]
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return []


def ingest_lab_hycom(path: Any, box: Any, out_zarr: Any, temperature_kind: Any = None, grid: Any = None, depth: Any = None) -> pathlib.Path:
    """Lab HYCOM -> the GOFS Zarr layout (ocean.source: lab_hycom). `path`: a per-snapshot .nc, a directory of them, an archv
    .a or .b file (or the common stem), or a directory of archv files. archv needs `grid` (the regional.grid stem; default:
    next to the files). temperature_kind ('in_situ'/'potential') is required unless every netCDF carries the attribute; it is
    never guessed. When a real lab file arrives this is the whole step:
        python -c "from cafe.pm.env.hycom import ingest_lab_hycom as i; i('PATH', (-7, 7, 163, -163), 'lab.zarr', 'in_situ')"."""
    p = pathlib.Path(path)
    refuse_overlap(out_zarr, p)                                              # before any read: the ingest ends by removing the old store
    reads: list[Callable[[], tuple[Any, str]]]
    files = (sorted(p.glob("*.nc")) or sorted(p.glob("archv*.b"))) if p.is_dir() else [p]
    if not files:
        raise ValueError(f"{p} holds no *.nc and no archv*.b files")
    for f in files:                                                          # a snapshot linked into the store goes with it: resolve() sees the target
        refuse_overlap(out_zarr, f)
    if all(f.suffix == ".nc" for f in files):
        reads, labels = [functools.partial(read_lab_netcdf, f, temperature_kind, depth) for f in files], files
    else:
        stems = [f.with_suffix("") if f.suffix in (".a", ".b") else f for f in files]
        gstem = pathlib.Path(grid) if grid else stems[0].parent / "regional.grid"
        for x, e in itertools.product((*stems, gstem), (".a", ".b")):               # the .a/.b pairs and the grid files, each possibly a link into the store
            refuse_overlap(out_zarr, str(x) + e)
        reads, labels = [functools.partial(read_archv, s, gstem, temperature_kind, depth, box) for s in stems], stems
    times = [_snapshot_times(lab) for lab in labels]
    order = sorted(range(len(labels)), key=lambda i: (min(times[i], default=np.inf), i))        # by time, not by name (snap_10 sorts before snap_9)
    reads, labels, times = [reads[i] for i in order], [labels[i] for i in order], [times[i] for i in order]
    seen: dict[float, Any] = {}
    for lab, ts in zip(labels, times, strict=True):
        for t in ts:
            if t in seen:
                raise ValueError(f"{seen[t].name} and {lab.name} are the same time ({_iso(t)} UTC); remove one")
            seen[t] = lab
    kinds: list[str] = []

    def steps() -> Iterator[Any]:
        from ..config import ConfigError
        for rd, label in zip(reads, labels, strict=True):
            ds, kind = rd()
            kinds.append(kind)
            if kind != kinds[0]:
                raise ValueError(f"files disagree about temperature_kind: {sorted(set(kinds))}")
            out = _std(_sub(ds, box), wrap=False)
            for v in ("water_temp", "salinity", "water_u", "water_v"):          # a store of NaN is no ocean: the failure would show far away, in Axis or Ocean
                for t, empty in zip(out.time.values, np.isnan(out[v].values).all(axis=(1, 2, 3)), strict=True):
                    if empty:
                        raise ConfigError(f"{label}: every value of {v} is NaN after reading (time {_iso(float(t))}; "
                                          "check the depth axis and the variable names)")
            yield out
    it = steps()
    first = next(it)
    return write_store(itertools.chain([first], it), out_zarr, kinds[0], dict(source=f"lab HYCOM {p}", box=json.dumps(list(box360(box)))))


# ------------------------------------------------------------------ read-back check against the server


def check_node(store: Any, nodes: Any, ncss: str = NCSS, deadline_s: float = 300.0, work: Any = None) -> float:
    """Read-back receipt: for each (it, iz, ij, ii) node of the store, fetch water_temp at that node from the NCSS server and
    return the largest |server - store| [degC]. A node masked (NaN) on both sides agrees; masked on one side only, it is `inf`: callers
    compare the result with a tolerance, never `== 0`. Needs the network (or a server standing in for it)."""
    import xarray as xr
    ds = open_store(store)
    work = pathlib.Path(work or pathlib.Path(store).parent)
    work.mkdir(parents=True, exist_ok=True)
    worst = 0.0
    for it, iz, ij, ii in nodes:
        t, z, la, lo = (float(ds[k].values[i]) for k, i in (("time", it), ("depth", iz), ("lat", ij), ("lon", ii)))
        f = work / f"check_{it}_{iz}_{ij}_{ii}.nc"
        _child(["_ncss", ncss_url("ts3z", ("water_temp",), (la - 0.01, la + 0.01, lo - 0.02, lo + 0.02), t, t, ncss) + f"&vertCoord={z}", f], deadline_s)
        got = np.atleast_1d(xr.open_dataset(f).water_temp.squeeze().values)
        want = float(ds.water_temp.isel(time=it, depth=iz, lat=ij, lon=ii).values)
        none = bool(np.isnan(got).all())                       # no value at all (or an empty answer): a masked node, e.g. below the sea floor
        if none and np.isnan(want):                            # masked on both sides: they agree
            continue
        # one side masked, the other not, is the largest disagreement there is: max(0, nan) would keep 0.0 and pass the check (round 10, M-20)
        worst = max(worst, np.inf if none or np.isnan(want) else abs(float(np.nanmean(got)) - want))
    return worst


# ------------------------------------------------------------------ receipts


def _worst_abs(a: Any, b: Any, rel: bool = False, skip: Any = None) -> tuple[float, int]:
    """Largest |a - b| (or |a / b - 1|) over the cells finite on both sides, and how many cells that is. A cell finite on one side only is
    the largest disagreement there is, as in `check_node` (M-20): the result is `inf`, never the maximum over the survivors (round 10, LB1).
    skip: cells not compared at all (the destaggered edge of an archv current, which the reader drops on purpose)."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    keep = np.ones(a.shape, bool) if skip is None else ~skip
    ok = np.isfinite(a) & np.isfinite(b) & keep
    if ((np.isfinite(a) != np.isfinite(b)) & keep).any():
        return np.inf, int(ok.sum())
    return float(np.max(np.abs(a[ok] / b[ok] - 1) if rel else np.abs(a[ok] - b[ok]))), int(ok.sum())


def receipts() -> bool:
    """TEOS-10 check values (GSW toolbox's own check cast), in-situ vs potential at depth, and both lab readers against the
    GOFS-layout store they were encoded from (synthetic fixture, tests/fixtures/hycom)."""
    import gsw, tempfile
    from cafe.receipts import bracket, receipt
    cvals = np.load(pathlib.Path(gsw.__file__).parent / "tests" / "gsw_cv_v3_0.npz")
    sp, t, p, lat, lon = (cvals[k] for k in ("SP_chck_cast", "t_chck_cast", "p_chck_cast", "lat_chck_cast", "long_chck_cast"))
    r = teos10(sp, t, -gsw.z_from_p(p, lat[None]), lat[None], lon[None], "in_situ")
    g = "Ocean (HYCOM / TEOS-10)"
    src = "GSW check cast (gsw_cv_v3_0.npz; McDougall & Barker 2011): SP, t, p -> rho, sound speed"
    for name, got, want, tol in (("in-situ density", r["rho"], cvals["rho"], 2e-7), ("sound speed", r["c"], cvals["sound_speed"], 2e-7)):
        err, n = _worst_abs(got, want, rel=True)
        receipt(g, f"{name} from SP, in-situ t, depth vs GSW check values: max relative error over {n} points", err, 0.0, tol, "", src, rel=False)
    # 1000 m, equatorial Pacific: in situ is warmer than potential by the adiabatic lapse (~0.1 K); reading in-situ as potential
    # makes the water that much too warm and the density ~0.01 kg/m3 too small
    ins, pot = teos10(35.0, 4.4, 1000.0, 0.0, 180.0, "in_situ"), teos10(35.0, 4.4, 1000.0, 0.0, 180.0, "potential")
    bracket(g, "same 4.4 degC read as potential instead of in situ at 1000 m: conservative temperature too warm by", pot["CT"] - ins["CT"],
            0.05, 0.15, "K", "adiabatic lapse ~1e-4 K/dbar x 1000 dbar (Fofonoff & Millard 1983, UNESCO Tech. Pap. Mar. Sci. 44)")
    bracket(g, "same: density too small by", ins["rho"] - pot["rho"], 0.005, 0.05, "kg/m3", "alpha ~ 1.5e-4 /K x 1030 kg/m3 x ~0.1 K")
    sys.path.insert(0, str(remote.ROOT))
    from tests.fixtures.hycom import make_fixtures as mk
    with tempfile.TemporaryDirectory() as d:
        fx = mk.make(pathlib.Path(d))
        want = open_store(fx["gofs_zarr"])
        for lbl, path, extra in (("per-snapshot netCDF, hybrid layers", fx["layered_dir"], {}), ("archv .a/.b", fx["archv_dir"], dict(grid=fx["grid"]))):
            out = pathlib.Path(d) / f"{lbl[:4]}.zarr"
            ingest_lab_hycom(path, fx["box"], out, "in_situ", depth=fx["depth"], **extra)
            got = open_store(out)
            for v in ("water_temp", "salinity", "water_u", "water_v", "rho", "c"):
                a, b = want[v].values, got[v].values
                edge = np.zeros(a.shape, bool)                  # archv: the C-grid currents lose their last column and row
                if "grid" in extra and v in ("water_u", "water_v"):
                    edge[..., -1], edge[..., -1, :] = True, True
                err, n = _worst_abs(a, b, skip=edge)
                receipt(g, f"lab HYCOM {lbl} -> store: {v} vs the GOFS values it was encoded from, max abs error over {n} cells",
                        err, 0.0, 5e-5, "", "float32 re-encoding round trip; archv water_u, water_v: the destaggered last column/row is not compared",
                        rel=False)
    return True


if __name__ == "__main__" and sys.argv[1:2] == ["_ncss"]:
    _child_ncss(*sys.argv[2:])
elif __name__ == "__main__" and sys.argv[1:2] == ["_dods"]:
    _child_dods(*sys.argv[2:])
elif __name__ == "__main__":
    receipts()
