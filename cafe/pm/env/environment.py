"""The gridded Environment: WRF + UMWM (+ restart spectra) from orca, ocean from GOFS 3.1 or the lab's HYCOM, all from
the Zarr cache `cafe.pm.env.orca.ingest` and `cafe.pm.env.hycom` write. Implements `protocol.Environment`.

Everything for the mission box is loaded into memory once (the WRF fields alone are 6 days x 130 x 313 x 16 x 8 bytes = 0.76 GB in float64;
with UMWM and the ocean the demo's environment is about 9 GB in memory, DECISIONS 267/270, measured); every
query is vectorized multilinear interpolation (`grid.interp`): linear in time across the hourly files, bilinear in
space, linear in depth for the ocean. Wind below the first WRF mass level (~21 m), and at hours without 3-D fields,
comes from U10 through the COARE 3.5 stability-corrected profile; above it, log-linear between mass levels.

Each value is a `Tagged` carrying its source and its 1-sigma uncertainty from config/perturbations.yaml (priors until
the TAO comparison overwrites the wind and SST ones, see cafe.pm.env.tao).
"""
from __future__ import annotations

import contextlib, datetime as dt, functools, pathlib
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

import numpy as np
from numpy.typing import ArrayLike, NDArray

from .. import Tagged
from . import conventions as cv
from .grid import Axis, interp

if TYPE_CHECKING:
    from .ocean import Ocean
    from .surface import SurfaceLayer

EPOCH = np.datetime64("1970-01-01T00:00:00", "s")


def seconds(t64: ArrayLike) -> NDArray[np.float64]:
    return (np.asarray(t64, "datetime64[s]") - EPOCH).astype("int64").astype(float)


def to_seconds(t: dt.datetime | str) -> float:
    """datetime (aware or naive UTC) or ISO string -> float seconds since epoch."""
    if isinstance(t, str):
        t = dt.datetime.fromisoformat(t.replace("Z", "+00:00"))
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    return t.timestamp()


class OutsideData(ValueError):
    pass


def rain_rate_nodes(accum: Any, t: Any) -> Any:
    """Rain rate [mm/h] at each hourly node from the accumulation (time first): the mean of the rates of the two intervals the node joins (the first
    and the last node take the one interval they touch), floored at 0. Linear interpolation between the nodes then integrates to the accumulation
    in total, not hour by hour (an hour of X mm/h reads X/2 at its two end nodes), and puts an hour of rain at the middle of that hour; `rain_hourly` gives
    the exact mean rate of an hour; a backward difference stored at the end of the hour would centre it half an hour late."""
    r = np.maximum(np.diff(accum, axis=0) / np.diff(t)[:, None, None] * 3600.0, 0.0)               # mm/h over each interval (k, k+1)
    return np.concatenate([r[:1], 0.5 * (r[:-1] + r[1:]), r[-1:]]) if len(r) else np.zeros_like(accum)


class GriddedEnv:
    def __init__(self, cache: Any, sigmas: dict[str, Any], ocean: Ocean | None = None, subgrid: SurfaceLayer | None = None, strict: bool = True):
        import xarray as xr
        cache = pathlib.Path(cache)
        self.cache, self.sig, self.strict = cache, sigmas, strict
        self.use_3d = True                                                # False: wind above the first level is always the U10 profile (what-if comparisons)
        self.wind_points = self.wind3d_points = 0                         # wind() points asked for / answered from the 3-D fields (stage 1 reads the deltas)
        def load(store: pathlib.Path) -> Any:
            try:
                return xr.open_zarr(store).load()
            except Exception as e:                                        # noqa: BLE001  any unreadable chunk or metadata file is the same advice
                from ..config import ConfigError
                raise ConfigError(f"environment cache file {store} cannot be read ({type(e).__name__}: {e}); delete {cache / 'orca'} and run "
                                  f"`python -m cafe.pm fetch --mission ...` again: only that part is downloaded again") from e

        def axis(x: Any, name: str, store: str) -> Axis:
            try:
                return Axis(x, name)
            except ValueError as e:                                       # a repeated, reversed or empty coordinate: the same advice as an unreadable file
                from ..config import ConfigError
                raise ConfigError(f"environment cache file {cache / 'orca' / store}: {e} (a repeated or reversed value); delete "
                                  f"{cache / 'orca'} and run `python -m cafe.pm fetch --mission ...` again: only that part is downloaded again") from e

        w = load(cache / "orca" / "wrf.zarr")
        u = load(cache / "orca" / "umwm.zarr")
        self.wrf_src = f"WRF {w.attrs.get('TITLE', '').strip()} 12 km hourly ({w.attrs.get('source', '')})"
        self.umwm_src = f"UMWM hourly ({u.attrs.get('source', '')})"
        self.tw = axis(seconds(w.time.values), "time", "wrf.zarr")
        self.law, self.low = axis(w.lat.values, "lat", "wrf.zarr"), axis(w.lon.values, "lon", "wrf.zarr")
        self.W = {k: w[k].values.astype("f8") for k in w.data_vars if w[k].dims == ("time", "lat", "lon")}
        self.Wstatic = {k: w[k].values.astype("f8") for k in w.data_vars if w[k].dims == ("lat", "lon")}
        rain = self.W["RAINNC"] + self.W["RAINC"]
        self.W["rain_mm_h"] = rain_rate_nodes(rain, self.tw.x)
        self.tu = axis(seconds(u.time.values), "time", "umwm.zarr")
        self.lau, self.lou = axis(u.lat.values, "lat", "umwm.zarr"), axis(u.lon.values, "lon", "umwm.zarr")
        sea = u["seamask"].values > 0
        self.sea = sea                                                    # UMWM sea nodes (lat, lon): ingest's NaN-in-sea-cells check reads it
        self.U = {k: np.where(sea, u[k].values.astype("f8"), np.nan) for k in u.data_vars if u[k].dims == ("time", "lat", "lon")}
        self.depth_umwm = np.where(sea, u["depth"].values.astype("f8"), 0.0)
        # UMWM angles are math radians toward: unwrap through unit vectors so interpolation never averages 350 and 10 deg
        for k in ("dwd", "mwd", "wdir"):
            th = self.U.pop(k)
            self.U[k + "_e"], self.U[k + "_n"] = np.cos(th), np.sin(th)
        self.w3: dict[str, Any] | None = None
        p3 = cache / "orca" / "wrf3d.zarr"
        if p3.exists():
            d3 = load(p3)
            self.w3 = dict(t=seconds(d3.time.values), U=d3.U3.values.astype("f8"), V=d3.V3.values.astype("f8"),
                           Z=d3.Z3.values.astype("f8"))
        self.spec: dict[str, Any] | None = None
        ps = cache / "orca" / "umwmspec.zarr"
        if ps.exists():
            s = load(ps)
            self.spec = dict(t=seconds(s.time.values), F=s.F.values, k=s.k.values, lon=s.plon.values, lat=s.plat.values,
                             f=s.f.values, th=s.th.values)
        self.ocean = ocean
        self.subgrid = subgrid
        lo = self.low.x
        self.bounds = tuple(round(float(x), 3) for x in (cv.wrap360(lo[0] + 180) - 180, cv.wrap360(lo[-1] + 180) - 180,
                                                         self.law.x[0], self.law.x[-1], self.tw.x[0], self.tw.x[-1]))

    # ------------------------------------------------------------ helpers

    @contextlib.contextmanager
    def lenient(self) -> Iterator[GriddedEnv]:
        """Inside the block a query outside the cached box returns the edge value instead of raising (`inside` still says so); the caller
        records who left. The previous strictness is restored on exit."""
        was, self.strict = self.strict, False
        try:
            yield self
        finally:
            self.strict = was

    def _check(self, inside: Any, what: str, lon: Any, lat: Any, t: Any, bounds: tuple[float, ...] | None = None) -> None:
        if self.strict and not np.all(inside):
            bounds = bounds or self.bounds
            bad = ~np.broadcast_to(inside, np.broadcast(lon, lat, t).shape)
            i = np.flatnonzero(bad)[0]
            L, A, T = (np.broadcast_to(np.asarray(x, float), bad.shape).ravel()[i] for x in (lon, lat, t))
            raise OutsideData(f"{what}: ({L:.3f}, {A:.3f}) at {dt.datetime.fromtimestamp(T, dt.timezone.utc):%Y-%m-%d %H:%M:%S}Z "
                              f"is outside the ingested data (box {bounds[:4]}, "
                              f"{dt.datetime.fromtimestamp(bounds[4], dt.timezone.utc):%Y-%m-%d %H:%M:%S}Z.."
                              f"{dt.datetime.fromtimestamp(bounds[5], dt.timezone.utc):%Y-%m-%d %H:%M:%S}Z); "
                              "re-run `cafe fetch` with a larger box or window")

    def _w(self, k: str, lon: Any, lat: Any, t: Any) -> Any:
        v, ins = interp(self.W[k], [self.tw, self.law, self.low], [t, lat, cv.wrap360(lon)])
        self._check(ins, f"WRF {k}", lon, lat, t)
        return v

    @functools.cached_property
    def _rain_acc(self) -> Any:
        return self.W["RAINNC"] + self.W["RAINC"]

    def rain_hourly(self, lon: Any, lat: Any, hours: Any) -> Any:
        """Mean rain rate [mm/h] over [t, t + 1 h) for each `hours` entry t, from the accumulation RAINNC + RAINC (piecewise linear in time, so
        this is the hour's exact mean whatever the alignment), floored at 0. An hour that runs past the end of the data is read to the end of it
        (a mean over the part that exists). What a gust front needs; `rain_mm_h` is the smoothed node rate the rain lens uses (row 252)."""
        t, la, lo = np.asarray(hours, float), np.asarray(lat, float), cv.wrap360(lon)
        t1 = np.minimum(t + 3600.0, self.tw.x[-1])
        a0, i0 = interp(self._rain_acc, [self.tw, self.law, self.low], [t, la, lo])
        a1, _ = interp(self._rain_acc, [self.tw, self.law, self.low], [t1, la, lo])
        self._check(i0, "WRF rain_hourly", lon, lat, t)
        span = np.maximum(t1 - t, 1.0)
        return np.where(t1 > t, np.maximum(a1 - a0, 0.0) / span * 3600.0, 0.0)

    def _u(self, k: str, lon: Any, lat: Any, t: Any) -> Any:
        v, ins = interp(self.U[k], [self.tu, self.lau, self.lou], [t, lat, cv.wrap360(lon)])
        self._check(ins, f"UMWM {k}", lon, lat, t)
        return v

    def inside(self, lon: Any, lat: Any, t: Any = None) -> Any:
        x = cv.wrap360(np.asarray(lon, float))
        ok = (x >= self.low.x[0]) & (x <= self.low.x[-1]) & (np.asarray(lat) >= self.law.x[0]) & (np.asarray(lat) <= self.law.x[-1])
        if t is not None:
            ok &= (np.asarray(t) >= self.tw.x[0]) & (np.asarray(t) <= self.tw.x[-1])
        b = self._bathy_bounds()
        if b is not None:                                            # the bathymetry grid can be smaller than the WRF box
            ok &= (x >= b[0]) & (x <= b[1]) & (np.asarray(lat) >= b[2]) & (np.asarray(lat) <= b[3])
        if self.ocean is not None and hasattr(self.ocean, "inside"):                    # and so can the ocean store, in space and in time: Ocean holds its edge
            ok &= self.ocean.inside(lon, lat, t)                                         # value outside it
        return ok

    def _ocean_check(self, what: str, lon: Any, lat: Any, t: Any) -> None:
        """A strict environment refuses an ocean query outside the store's lat, lon and time axes (a lenient one holds the edge; `inside` says so)."""
        if self.ocean is not None and hasattr(self.ocean, "inside"):
            self._check(self.ocean.inside(lon, lat, t), what, lon, lat, t, self.ocean.bounds())

    def _bathy_bounds(self) -> tuple[float, float, float, float] | None:
        """(lon0, lon1 in 0..360, lat0, lat1) of the ocean's bathymetry grid, or None without one."""
        bathy = getattr(self.ocean, "bathy", None)
        return getattr(bathy, "bounds", None)

    # ------------------------------------------------------------ atmosphere

    def u10(self, lon: Any, lat: Any, t: Any) -> Any:
        ue, ve = cv.rotate_grid_to_earth(self._w("U10", lon, lat, t), self._w("V10", lon, lat, t),
                                         interp(self.Wstatic["COSALPHA"], [self.law, self.low], [lat, cv.wrap360(lon)])[0],
                                         interp(self.Wstatic["SINALPHA"], [self.law, self.low], [lat, cv.wrap360(lon)])[0])
        return np.stack([ue, ve], -1)

    def air(self, lon: Any, lat: Any, t: Any) -> dict[str, Tagged]:
        s = self.sig

        def tag(k: str, unit_sig: Any = None) -> Tagged:
            return Tagged(self._w(k, lon, lat, t), f"{self.wrf_src} {k}", unit_sig)

        a = dict(T2=tag("T2", s["t2_k"]), q2=tag("Q2", s["q2_frac"]), psfc=tag("PSFC", s["psfc_pa"]), swdown=tag("SWDOWN", s["swdown_frac"]),
                 glw=tag("GLW", s["glw_wm2"]), rain=Tagged(self._w("rain_mm_h", lon, lat, t), f"{self.wrf_src} d(RAINNC+RAINC)/dt", None),
                 ustar_wrf=tag("UST", None), pblh=tag("PBLH", None))
        if self.subgrid is not None:
            a.update(self.subgrid.surface_layer(self, lon, lat, t))
        return a

    def wind(self, lon: Any, lat: Any, z: Any, t: Any) -> Tagged:
        z = np.asarray(z, float)
        u10 = self.u10(lon, lat, t)
        src = f"{self.wrf_src} U10/V10 (earth-relative)"
        if self.subgrid is not None:
            ratio, psrc = self.subgrid.profile_ratio(self, lon, lat, z, t)
        else:
            ratio = np.log(np.maximum(z, 0.1) / 2e-4) / np.log(10.0 / 2e-4)
            psrc = "neutral log profile, z0 = 2e-4 m (no COARE stability: subgrid disabled)"
        v = u10 * np.asarray(ratio)[..., None]
        used = 0
        if self.w3 is not None and self.use_3d:
            up = self._wind3d(lon, lat, z, t)
            if up is not None:
                use = np.isfinite(up[..., 0])
                v = np.where(use[..., None], up, v)
                used = int(use.sum())
        self.wind_points += v.size // 2
        self.wind3d_points += used
        if used:
            src += "; above 21 m in sortie hours: WRF 3-D U/V log-linear in z"
        else:
            why = "use_3d is off" if not self.use_3d else "no 3-D fields" if self.w3 is None else "no ingested 3-D hour here"
            src += f"; 3-D WRF U/V not used ({why})"
        return Tagged(v, f"{src}; below the first level: {psrc}", self.sig["wind_ms"], "data")

    def _wind3d(self, lon: Any, lat: Any, z: Any, t: Any) -> Any:
        """3-D WRF wind (east, north) where z is between the first and the top stored mass level and t is within an ingested 3-D hour pair, else NaN. U3/V3 are
        grid-relative like U10, so they go through the same COSALPHA/SINALPHA rotation before the vertical interpolation."""
        assert self.w3 is not None
        T, Z = self.w3["t"], self.w3["Z"]
        t = np.broadcast_to(np.asarray(t, float), np.broadcast(lon, lat, z, t).shape)
        i = np.searchsorted(T, t, side="right") - 1
        ok = (i >= 0) & (i < len(T) - 1)
        ok &= np.take(np.diff(T, append=np.inf), np.clip(i, 0, len(T) - 1)) <= 3600.0 + 1e-6
        if not ok.any():
            return None
        out = np.full(t.shape + (2,), np.nan)
        lonq, latq, zq = (np.broadcast_to(np.asarray(x, float), t.shape) for x in (lon, lat, z))
        for k in np.unique(i[ok]):
            m = ok & (i == k)
            w = (t[m] - T[k]) / (T[k + 1] - T[k])
            ca, sa = (interp(self.Wstatic[a], [self.law, self.low], [latq[m], cv.wrap360(lonq[m])])[0][:, None] for a in ("COSALPHA", "SINALPHA"))
            vals = []
            at = [latq[m], cv.wrap360(lonq[m])]
            for kk, ww in ((k, 1 - w), (k + 1, w)):
                zc, uc, vc = (np.ascontiguousarray(interp(F[kk], [self.law, self.low], at)[0].T) for F in (Z, self.w3["U"], self.w3["V"]))   # (n, levels)
                uc, vc = cv.rotate_grid_to_earth(uc, vc, ca, sa)             # grid-relative -> earth, like U10 (the 3-D fields are grid-relative too)
                lz = np.log(np.maximum(zc, 1.0))
                q = np.log(np.maximum(zq[m], 1.0))
                j = np.clip(np.sum(lz < q[:, None], axis=1) - 1, 0, lz.shape[1] - 2)
                r = np.arange(len(j))
                a = (q - lz[r, j]) / (lz[r, j + 1] - lz[r, j])
                above = a > 1.0 + 1e-9                                   # higher than the top stored level: not known, not extrapolated
                a = np.clip(a, 0, 1)
                vals.append(ww[:, None] * np.stack([uc[r, j] + a * (uc[r, j + 1] - uc[r, j]), vc[r, j] + a * (vc[r, j + 1] - vc[r, j])], -1))
                below = (zq[m] < zc[:, 0]) | above
                vals[-1][below] = np.nan
            out[m] = vals[0] + vals[1]
        return out

    # ------------------------------------------------------------ waves

    def waves(self, lon: Any, lat: Any, t: Any) -> dict[str, Tagged]:
        s, src = self.sig, self.umwm_src

        def d(k: str) -> Any:
            return cv.math_rad_to_compass_to(np.arctan2(self._u(k + "_n", lon, lat, t), self._u(k + "_e", lon, lat, t)))

        hs = self._u("swh", lon, lat, t)
        tm = self._u("mwp", lon, lat, t)
        out = dict(Hs=Tagged(hs, f"{src} swh", s["hs_frac"] * hs), Tp=Tagged(self._u("dwp", lon, lat, t), f"{src} dwp", s["tp_s"]),
                   dir_to=Tagged(d("dwd"), f"{src} dwd (math rad toward -> compass toward)", s["wave_dir_deg"]),
                   Tm=Tagged(tm, f"{src} mwp", s["tp_s"]), mdir_to=Tagged(d("mwd"), f"{src} mwd", s["wave_dir_deg"]),
                   mss=Tagged(self._u("mss", lon, lat, t), f"{src} mss", None),
                   cp=Tagged(self._u("dcp", lon, lat, t), f"{src} dcp", None),
                   ustar_umwm=Tagged(self._u("ust", lon, lat, t), f"{src} ust", None))
        if self.subgrid is not None:
            out["stokes0"] = self.subgrid.stokes_surface(self, out, lon, lat, t)
        else:
            out["stokes0"] = Tagged(np.zeros(np.shape(hs) + (2,)), "Stokes drift off (subgrid disabled)", None, "assumed")
        return out

    def restart_spectrum(self, lon: Any, lat: Any, t: Any, max_km: float = 40.0, max_h: float = 3.0) -> dict[str, Any] | None:
        """The nearest ingested real UMWM spectrum (F(k, theta) per sea point) or None if none within max_km / max_h."""
        if self.spec is None:
            return None
        S = self.spec
        it = int(np.argmin(np.abs(S["t"] - float(t))))
        if abs(S["t"][it] - float(t)) > max_h * 3600:
            return None
        dx = (cv.wrap360(S["lon"] - float(lon) + 180) - 180) * np.cos(np.radians(float(lat))) * 111.2
        dy = (S["lat"] - float(lat)) * 111.2
        ip = int(np.argmin(dx ** 2 + dy ** 2))
        if np.hypot(dx[ip], dy[ip]) > max_km:
            return None
        return dict(F=S["F"][it, ip], k=S["k"][it, ip], f=S["f"], th=S["th"], lon=S["lon"][ip], lat=S["lat"][ip], t=S["t"][it],
                    source=f"{self.umwm_src} restart spectrum, point ({S['lon'][ip]:.2f}, {S['lat'][ip]:.2f})")

    # ------------------------------------------------------------ ocean

    def current(self, lon: Any, lat: Any, z: Any, t: Any) -> Tagged:
        if self.ocean is None:
            raise OutsideData("no ocean source loaded: run `cafe fetch` (GOFS 3.1 by default) or point ocean.source at the lab's HYCOM")
        self._ocean_check("ocean current", lon, lat, t)
        v = self.ocean.current(lon, lat, z, t)
        if self.subgrid is not None:
            v = self.subgrid.current_extra(self, v, lon, lat, z, t)
        return v

    def density(self, lon: Any, lat: Any, z: Any, t: Any) -> Tagged:
        assert self.ocean is not None
        self._ocean_check("ocean density", lon, lat, t)
        v = self.ocean.density(lon, lat, z, t)
        return self.subgrid.density_extra(self, v, lon, lat, z, t) if self.subgrid is not None else v

    def sound_speed(self, lon: Any, lat: Any, z: Any, t: Any) -> Tagged:
        assert self.ocean is not None
        self._ocean_check("ocean sound speed", lon, lat, t)
        return self.ocean.sound_speed(lon, lat, z, t)

    def depth(self, lon: Any, lat: Any) -> Tagged:
        if self.ocean is not None and hasattr(self.ocean, "bathymetry"):
            b = self._bathy_bounds()
            if b is not None and not self.strict:                    # lenient: hold the edge depth; `inside` records the member as left_data
                lon, lat = np.clip(cv.wrap360(np.asarray(lon, float)), b[0], b[1]), np.clip(np.asarray(lat, float), b[2], b[3])
            return self.ocean.bathymetry(lon, lat)
        v, ins = interp(self.depth_umwm, [self.lau, self.lou], [lat, cv.wrap360(lon)])
        return Tagged(v, "UMWM depth (12 km)", None)

    def sst(self, lon: Any, lat: Any, t: Any) -> Tagged:
        v = Tagged(self._w("SST", lon, lat, t), f"{self.wrf_src} SST (frozen at 2023-03-01: SST_UPDATE=0)", self.sig["sst_k"])
        return self.subgrid.sst_extra(self, v, lon, lat, t) if self.subgrid is not None else v
