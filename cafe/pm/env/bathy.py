"""Bathymetry for seafloor-contact / grounding checks and shallow-water wave checks: depth(lon, lat) -> Tagged.

Fallback order (first that works wins; what failed is kept in `Bathymetry.tried` and so reaches the report):
  1. GEBCO_2026 15 arc-second (BODC/GEBCO; 'elevation' [m, positive up], depth = -elevation, 0 on land), cut to the box without
     downloading the 7.5 GB global file: the file on CEDA is an uncompressed, contiguous int16 NetCDF-4, so one box row is one HTTP
     byte range (about 8 kB for the 34 deg TEPEX-C box); `fetch_gebco` asks for the rows in parallel, hashes the result and caches
     it as a small .npz. GEBCO's own download app has no scriptable interface and its OPeNDAP link (data.ceda.ac.uk "extract subset")
     is a human page; NOAA's ERDDAP only hosts GEBCO_2020.
  2. HYCOM GOFS grid (the Zarr store of cafe.pm.env.hycom): depth of the deepest valid level, so the floor is that level or up to
     one level spacing deeper, and never reported below 5000 m. 0.08 x 0.04 deg.
  3. UMWM `depth` (12 km), supplied by the caller from the umwmout file (cafe.pm.env.orca).
Each answer says in `source` which one it is and how coarse it is.

GEBCO: GEBCO Bathymetric Compilation Group 2026, The GEBCO_2026 Grid, doi:10.5285/4f68d5c7-45eb-f999-e063-7086abc036fa (file attribute).
The 1-sigma uncertainties in ASSUMED are not published numbers; they are read from config/assumptions.yaml (bathy.*: value,
unit, why, what replaces it): GEBCO deep-ocean depth from satellite-predicted bathymetry is good to a few percent, GOFS is
the grid-level quantization (a uniform distribution over the level spacing, computed, not assumed), UMWM unknown.
"""
import concurrent.futures as cf, hashlib, json, os, pathlib
from typing import Any

import numpy as np

from .. import Tagged
from ..config import assumptions as _assumptions
from . import remote
from .hycom import box360, open_store

GEBCO_URL = "https://dap.ceda.ac.uk/bodc/gebco/global/gebco_2026/ice_surface_elevation/netcdf/GEBCO_2026.nc"
GEBCO_RES_DEG = 1.0 / 240.0                          # 15 arc-seconds
ASSUMED = {k: _assumptions()[f"bathy.{k}"]["value"] for k in ("gebco_rel_sigma", "umwm_rel_sigma")}   # unsourced: config/assumptions.yaml
ORDER = ("gebco", "gofs", "umwm")
M_PER_DEG = 111_195.0                               # mean Earth radius 6371.0088 km (IUGG)


class Bathymetry:
    """Callable `b(lon, lat) -> Tagged` of water depth [m, positive down, 0 on land], bilinear in a regular lon/lat grid
    (lon any convention, taken mod 360; the grid lies inside 0..360). `sigma` is a function of depth or an array like depth.
    Attributes: source, resolution_m, tried (sources that failed before this one), bounds (lon_min, lon_max, lat_min, lat_max)."""

    def __init__(self, lon: Any, lat: Any, depth: Any, source: str, resolution_m: float, sigma: Any, tried: tuple[str, ...] = ()):
        from scipy.interpolate import RegularGridInterpolator
        self.lon, self.lat = np.asarray(lon, float), np.asarray(lat, float)
        self.depth = np.clip(np.nan_to_num(np.asarray(depth, float), nan=0.0), 0.0, None)
        self.source, self.resolution_m, self.tried = source, float(resolution_m), tuple(tried)
        self.bounds = (float(self.lon[0]), float(self.lon[-1]), float(self.lat[0]), float(self.lat[-1]))

        def grid(a: Any) -> Any:
            return RegularGridInterpolator((self.lat, self.lon), a, bounds_error=False, fill_value=np.nan)
        self._depth = grid(self.depth)
        if callable(sigma) or np.ndim(sigma) == 0:                   # a function of depth, or one constant
            self._sigma = sigma if callable(sigma) else (lambda d, v=float(sigma): np.full_like(d, v))
        else:                                                        # a grid of its own
            self._sigma = grid(np.asarray(sigma, float))

    def __call__(self, lon: Any, lat: Any) -> Tagged:
        pts = np.stack(np.broadcast_arrays(np.asarray(lat, float), np.mod(np.asarray(lon, float), 360.0)), axis=-1)
        d = self._depth(pts.reshape(-1, 2)).reshape(pts.shape[:-1])
        if np.isnan(d).any():
            raise ValueError(f"{int(np.isnan(d).sum())} point(s) outside the {self.source} grid: lon {self.bounds[0]:.3f}..{self.bounds[1]:.3f} "
                             f"(0..360), lat {self.bounds[2]:.3f}..{self.bounds[3]:.3f}")
        sig = self._sigma(pts.reshape(-1, 2)).reshape(d.shape) if hasattr(self._sigma, "grid") else self._sigma(d)
        return Tagged(d, f"{self.source} ({self.resolution_m / 1000:.2f} km, bilinear)", sig, "data")


# ------------------------------------------------------------------ 1. GEBCO by byte range


def _rows(url: str, base: int, ncols: int, j: Any, i0: int, i1: int, dtype: Any, workers: int) -> np.ndarray:
    """Rows j, columns i0..i1 (exclusive) of a contiguous raster of `dtype` at byte `base` of the file, one range request per row."""
    size = np.dtype(dtype).itemsize

    def one(r: Any) -> np.ndarray:
        a = base + (int(r) * ncols + i0) * size
        with remote._open(url, a, a + (i1 - i0) * size - 1, timeout=120) as resp:
            raw = resp.read()
        if len(raw) != (i1 - i0) * size:
            raise ConnectionError(f"{url}: short read on row {r} ({len(raw)} of {(i1 - i0) * size} bytes)")
        return np.frombuffer(raw, dtype)
    with cf.ThreadPoolExecutor(workers) as ex:
        return np.stack(list(ex.map(one, j)))


def fetch_gebco(box: Any, out_path: Any, url: str = GEBCO_URL, workers: int = 16) -> pathlib.Path:
    """GEBCO elevation for `box` (south, north, west, east; any lon convention) -> out_path (.npz: lon 0..360 ascending, contiguous
    across the dateline, lat ascending, elevation int16 [lat, lon] positive up, attrs json with url, remote size, bytes read and the
    SHA-256 of the raster). Reads only the box: HDF5 metadata through RemoteFile, then the raster by per-row byte ranges when the
    file stores it contiguous and uncompressed, by h5py slices through RemoteFile otherwise. The file's longitudes are -180..180, so
    a box across 180 is read as two column runs (lon >= 0 and lon < 0) and joined."""
    import h5py
    s, n, w, e = box360(box)
    f = remote.RemoteFile(url)
    h = h5py.File(f, "r")
    lon180, lat = h["lon"][:].astype(float), h["lat"][:].astype(float)
    dset = h["elevation"]
    j = np.where((lat >= s - GEBCO_RES_DEG) & (lat <= n + GEBCO_RES_DEG))[0]
    lon0 = np.mod(lon180, 360.0)
    want = np.where((lon0 >= w - GEBCO_RES_DEG) & (lon0 <= e + GEBCO_RES_DEG))[0]
    if len(j) == 0 or len(want) == 0:
        raise ValueError(f"{url} has no grid points inside the box {box}")
    pieces, cols = [], []
    for run in (want[lon180[want] >= 0], want[lon180[want] < 0]):
        if len(run) == 0:
            continue
        i0, i1 = int(run.min()), int(run.max()) + 1
        if dset.chunks is None and dset.compression is None:
            a = _rows(url, dset.id.get_offset(), dset.shape[1], j, i0, i1, dset.dtype, workers)
        else:
            a = dset[j[0]:j[-1] + 1, i0:i1]
        pieces.append(a.astype("<i2"))
        cols.append(lon0[i0:i1])
    lons, elev = np.concatenate(cols), np.concatenate(pieces, axis=1)
    o = np.argsort(lons)
    lons, elev = lons[o], np.ascontiguousarray(elev[:, o])

    def text(v: Any) -> str:
        return v.decode() if isinstance(v, bytes) else str(v)

    attrs = dict(url=url, remote_bytes=f.n, title=text(h.attrs.get("title", "")), doi=text(h.attrs.get("id", "")),
                 box=[s, n, w, e], resolution_deg=GEBCO_RES_DEG, sha256=hashlib.sha256(elev.tobytes()).hexdigest(), bytes_read=f.fetched + elev.nbytes)
    out = pathlib.Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".part.npz")
    np.savez_compressed(tmp, lon=lons, lat=lat[j], elevation=elev, attrs=json.dumps(attrs))
    os.replace(tmp, out)
    return out


def from_gebco(path: Any) -> Bathymetry:
    """Bathymetry from a fetch_gebco cache. Verifies the stored SHA-256 of the raster."""
    z = np.load(path)
    attrs = json.loads(str(z["attrs"]))
    if hashlib.sha256(np.ascontiguousarray(z["elevation"]).tobytes()).hexdigest() != attrs["sha256"]:
        raise ValueError(f"{path}: raster SHA-256 differs from the one recorded at download; delete it and refetch")
    return Bathymetry(z["lon"], z["lat"], -z["elevation"].astype(float), f"GEBCO_2026 15 arc-second ({attrs['doi'] or 'doi n/a'})",
                      GEBCO_RES_DEG * M_PER_DEG, lambda d: ASSUMED["gebco_rel_sigma"] * d)


# ------------------------------------------------------------------ 2. GOFS floor, 3. UMWM


def from_gofs(store: Any) -> Bathymetry:
    """Depth of the deepest valid level at each node of a hycom Zarr store (any time); 0 where no level is valid (land). Capped by
    the deepest level (5000 m for GOFS). sigma is the quantization of the floor into [level, next level): spacing / sqrt(12)."""
    ds = open_store(store)
    wet = np.isfinite(ds.water_temp.values).any(axis=0)                   # (depth, lat, lon)
    z = ds.depth.values.astype(float)
    k = np.where(wet.any(0), wet.shape[0] - 1 - np.argmax(wet[::-1], axis=0), -1)
    depth = np.where(k >= 0, z[np.maximum(k, 0)], 0.0)
    sig = np.where(k >= 0, np.diff(z, append=z[-1])[np.maximum(k, 0)] / np.sqrt(12.0), 0.0)
    res = max(np.diff(ds.lon.values).max(), np.diff(ds.lat.values).max()) * M_PER_DEG
    return Bathymetry(ds.lon.values, ds.lat.values, depth, "HYCOM GOFS 3.1 deepest valid level (the floor is at or below it)", res, sig)


def from_umwm(lon: Any, lat: Any, depth: Any) -> Bathymetry:
    """UMWM `depth` [m] on a regular lon/lat grid: lon (nx,), lat (ny,), depth (ny, nx), ascending, inside 0..360 after mod; 12 km."""
    return Bathymetry(np.mod(np.asarray(lon, float), 360.0), lat, depth, "UMWM depth", 12_000.0, lambda d: ASSUMED["umwm_rel_sigma"] * d)


def cache_path(box: Any, cache_dir: Any) -> pathlib.Path:
    """Where `choose` keeps the GEBCO cut for `box`: cache_dir/gebco2026_<south>_<north>_<west>_<east>.npz."""
    s, n, w, e = box360(box)
    return pathlib.Path(cache_dir) / f"gebco2026_{s:g}_{n:g}_{w:g}_{e:g}.npz"


def choose(box: Any, cache_dir: Any, gofs: Any = None, umwm: Any = None, fetch: bool = True, url: str = GEBCO_URL) -> Bathymetry:
    """First of GEBCO -> GOFS -> UMWM that works. cache_dir/gebco2026_<box>.npz is reused, else fetched when `fetch`; gofs: the
    Zarr path; umwm: dict(lon=, lat=, depth=). Raises LookupError listing every failure when none works."""
    cache = cache_path(box, cache_dir)
    tried: list[str] = []
    for name in ORDER:
        try:
            if name == "gebco":
                if not cache.exists():
                    if not fetch:
                        raise FileNotFoundError(f"{cache} not cached and fetch=False")
                    fetch_gebco(box, cache, url)
                b = from_gebco(cache)
            elif name == "gofs":
                if gofs is None:
                    raise FileNotFoundError("no GOFS store given")
                b = from_gofs(gofs)
            else:
                if umwm is None:
                    raise FileNotFoundError("no UMWM depth given")
                b = from_umwm(**umwm)
            b.tried = tuple(tried)
            return b
        except Exception as ex:                                             # any failure of one source selects the next
            tried.append(f"{name}: {type(ex).__name__}: {ex}")
    raise LookupError("no bathymetry source worked:\n" + "\n".join(tried))


def receipts(cache: Any = None, url: str | None = None) -> bool:
    """(1) bilinear depth is exact for a linear field, (2) with `cache` (a fetch_gebco .npz): its raster still has the hash recorded at
    download and a node of it reads back as -elevation, (3) with `url` too: a small window of the remote file read by the per-row
    byte-range path equals the same window read the slow, independent way (h5py hyperslab through RemoteFile)."""
    from cafe.receipts import receipt
    g = "Bathymetry"
    lons, lats = np.arange(170.0, 180.0), np.arange(0.0, 6.0)
    lin = Bathymetry(lons, lats, 3.0 * (lons[None] - 170.0) + 7.0 * lats[:, None], "linear", 1.0, 0.0)
    xs, ys = 171.0 + 7.0 * np.linspace(0.013, 0.987, 20), 0.5 + 4.0 * np.linspace(0.021, 0.979, 20)
    receipt(g, "bilinear depth in a linear field vs the analytic value at 20 off-node points (max abs error)",
            float(np.max(np.abs(lin(xs, ys).value - (3.0 * (xs - 170.0) + 7.0 * ys)))), 0.0, 1e-9, "m",
            "bilinear interpolation is exact for f = a x + b y", rel=False)
    if cache is not None:
        b = from_gebco(cache)                                           # raises if the raster hash changed
        z = np.load(cache)
        j, i = np.unravel_index(np.argmin(z["elevation"]), z["elevation"].shape)           # the deepest node: ocean, so a sign error shows
        got = float(b(z["lon"][i], z["lat"][j]).value)
        receipt(g, "GEBCO cache: depth at its deepest node vs -elevation of that node", got, float(max(-int(z["elevation"][j, i]), 0)), 1e-9, "m",
                "GEBCO_2026 elevation positive up; raster SHA-256 matched the one recorded at download", rel=False)
        if url is not None:
            import h5py
            meta = json.loads(str(z["attrs"]))
            lo, la = float(z["lon"][i]), float(z["lat"][j])
            small = fetch_gebco((la, la + 11 * GEBCO_RES_DEG, lo, lo + 11 * GEBCO_RES_DEG), pathlib.Path(cache).with_name("window_check.npz"), url)
            w = np.load(small)
            h = h5py.File(remote.RemoteFile(url), "r")
            lon180, lat = h["lon"][:], h["lat"][:]
            jj = np.array([int(np.argmin(abs(lat - y))) for y in w["lat"]])
            ii = np.array([int(np.argmin(abs(lon180 - ((x + 180.0) % 360.0 - 180.0)))) for x in w["lon"]])
            ref = h["elevation"][jj.min():jj.max() + 1, ii.min():ii.max() + 1]
            receipt(g, f"GEBCO per-row byte-range read vs h5py hyperslab, {w['elevation'].size} cells (max abs difference)",
                    float(np.abs(w["elevation"].astype(float) - ref).max()), 0.0, 0.0, "m", f"{meta['url']}", rel=False)
    return True
