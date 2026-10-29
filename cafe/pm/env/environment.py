"""The gridded Environment: WRF + UMWM (+ restart spectra) from orca, ocean from GOFS 3.1 or the lab's HYCOM, all from
the Zarr cache `cafe.pm.env.orca.ingest` and `cafe.pm.env.hycom` write. Implements `protocol.Environment`.

Everything for the mission box is loaded into memory once (6 days x 130 x 313 x 16 WRF fields is ~0.4 GB); every
query is vectorized multilinear interpolation (`grid.interp`): linear in time across the hourly files, bilinear in
space, linear in depth for the ocean. Wind below the first WRF mass level (~21 m), and at hours without 3-D fields,
comes from U10 through the COARE 3.5 stability-corrected profile; above it, log-linear between mass levels.

Each value is a `Tagged` carrying its source and its 1-sigma uncertainty from config/perturbations.yaml (priors until
the TAO comparison overwrites the wind and SST ones, see cafe.pm.env.tao).
"""
import datetime as dt, pathlib

import numpy as np

from .. import Tagged
from . import conventions as cv
from .grid import Axis, interp

EPOCH = np.datetime64("1970-01-01T00:00:00", "s")


def seconds(t64):
    return (np.asarray(t64, "datetime64[s]") - EPOCH).astype("int64").astype(float)


def to_seconds(t):
    """datetime (aware or naive UTC) or ISO string -> float seconds since epoch."""
    if isinstance(t, str):
        t = dt.datetime.fromisoformat(t.replace("Z", "+00:00"))
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    return t.timestamp()


class OutsideData(ValueError):
    pass


class GriddedEnv:
    def __init__(self, cache, sigmas, ocean=None, subgrid=None, strict=True):
        import xarray as xr
        cache = pathlib.Path(cache)
        self.cache, self.sig, self.strict = cache, sigmas, strict
        w = xr.open_zarr(cache / "orca" / "wrf.zarr").load()
        u = xr.open_zarr(cache / "orca" / "umwm.zarr").load()
        self.wrf_src = f"WRF {w.attrs.get('TITLE', '').strip()} 12 km hourly ({w.attrs.get('source', '')})"
        self.umwm_src = f"UMWM hourly ({u.attrs.get('source', '')})"
        self.tw = Axis(seconds(w.time.values), "time")
        self.law, self.low = Axis(w.lat.values, "lat"), Axis(w.lon.values, "lon")
        self.W = {k: w[k].values.astype("f8") for k in w.data_vars if w[k].dims == ("time", "lat", "lon")}
        self.Wstatic = {k: w[k].values.astype("f8") for k in w.data_vars if w[k].dims == ("lat", "lon")}
        rain = self.W["RAINNC"] + self.W["RAINC"]
        self.W["rain_mm_h"] = np.maximum(np.diff(rain, axis=0, prepend=rain[:1]) / np.diff(self.tw.x, prepend=self.tw.x[0] - 3600)[:, None, None] * 3600, 0.0)
        self.tu, self.lau, self.lou = Axis(seconds(u.time.values), "time"), Axis(u.lat.values, "lat"), Axis(u.lon.values, "lon")
        sea = u["seamask"].values > 0
        self.U = {k: np.where(sea, u[k].values.astype("f8"), np.nan) for k in u.data_vars if u[k].dims == ("time", "lat", "lon")}
        self.depth_umwm = np.where(sea, u["depth"].values.astype("f8"), 0.0)
        # UMWM angles are math radians toward: unwrap through unit vectors so interpolation never averages 350 and 10 deg
        for k in ("dwd", "mwd", "wdir"):
            th = self.U.pop(k)
            self.U[k + "_e"], self.U[k + "_n"] = np.cos(th), np.sin(th)
        self.w3 = None
        p3 = cache / "orca" / "wrf3d.zarr"
        if p3.exists():
            d3 = xr.open_zarr(p3).load()
            self.w3 = dict(t=seconds(d3.time.values), U=d3.U3.values.astype("f8"), V=d3.V3.values.astype("f8"),
                           Z=d3.Z3.values.astype("f8"))
        self.spec = None
        ps = cache / "orca" / "umwmspec.zarr"
        if ps.exists():
            s = xr.open_zarr(ps).load()
            self.spec = dict(t=seconds(s.time.values), F=s.F.values, k=s.k.values, lon=s.plon.values, lat=s.plat.values,
                             f=s.f.values, th=s.th.values)
        self.ocean = ocean
        self.subgrid = subgrid
        lo = self.low.x
        self.bounds = tuple(round(float(x), 3) for x in (cv.wrap360(lo[0] + 180) - 180, cv.wrap360(lo[-1] + 180) - 180,
                                                         self.law.x[0], self.law.x[-1], self.tw.x[0], self.tw.x[-1]))

    # ------------------------------------------------------------ helpers

    def _check(self, inside, what, lon, lat, t):
        if self.strict and not np.all(inside):
            bad = ~np.broadcast_to(inside, np.broadcast(lon, lat, t).shape)
            i = np.flatnonzero(bad)[0]
            L, A, T = (np.broadcast_to(np.asarray(x, float), bad.shape).ravel()[i] for x in (lon, lat, t))
            raise OutsideData(f"{what}: ({L:.3f}, {A:.3f}) at {dt.datetime.fromtimestamp(T, dt.timezone.utc):%Y-%m-%d %H:%M}Z "
                              f"is outside the ingested data (box {self.bounds[:4]}, "
                              f"{dt.datetime.fromtimestamp(self.bounds[4], dt.timezone.utc):%Y-%m-%d %H}Z.."
                              f"{dt.datetime.fromtimestamp(self.bounds[5], dt.timezone.utc):%Y-%m-%d %H}Z); "
                              "re-run `cafe fetch` with a larger box or window")

    def _w(self, k, lon, lat, t):
        v, ins = interp(self.W[k], [self.tw, self.law, self.low], [t, lat, cv.wrap360(lon)])
        self._check(ins, f"WRF {k}", lon, lat, t)
        return v

    def _u(self, k, lon, lat, t):
        v, ins = interp(self.U[k], [self.tu, self.lau, self.lou], [t, lat, cv.wrap360(lon)])
        self._check(ins, f"UMWM {k}", lon, lat, t)
        return v

    def inside(self, lon, lat, t=None):
        x = cv.wrap360(np.asarray(lon, float))
        ok = (x >= self.low.x[0]) & (x <= self.low.x[-1]) & (np.asarray(lat) >= self.law.x[0]) & (np.asarray(lat) <= self.law.x[-1])
        if t is not None:
            ok &= (np.asarray(t) >= self.tw.x[0]) & (np.asarray(t) <= self.tw.x[-1])
        return ok

    # ------------------------------------------------------------ atmosphere

    def u10(self, lon, lat, t):
        ue, ve = cv.rotate_grid_to_earth(self._w("U10", lon, lat, t), self._w("V10", lon, lat, t),
                                         interp(self.Wstatic["COSALPHA"], [self.law, self.low], [lat, cv.wrap360(lon)])[0],
                                         interp(self.Wstatic["SINALPHA"], [self.law, self.low], [lat, cv.wrap360(lon)])[0])
        return np.stack([ue, ve], -1)

    def air(self, lon, lat, t):
        s = self.sig
        tag = lambda k, unit_sig=None: Tagged(self._w(k, lon, lat, t), f"{self.wrf_src} {k}", unit_sig)
        a = dict(T2=tag("T2", s["t2_k"]), q2=tag("Q2", s["q2_frac"]), psfc=tag("PSFC", s["psfc_pa"]), swdown=tag("SWDOWN", s["swdown_frac"]),
                 glw=tag("GLW", s["glw_wm2"]), rain=Tagged(self._w("rain_mm_h", lon, lat, t), f"{self.wrf_src} d(RAINNC+RAINC)/dt", None),
                 ustar_wrf=tag("UST", None), pblh=tag("PBLH", None))
        if self.subgrid is not None:
            a.update(self.subgrid.surface_layer(self, lon, lat, t))
        return a

    def wind(self, lon, lat, z, t):
        z = np.asarray(z, float)
        u10 = self.u10(lon, lat, t)
        src = f"{self.wrf_src} U10/V10 (earth-relative)"
        if self.subgrid is not None:
            ratio, psrc = self.subgrid.profile_ratio(self, lon, lat, z, t)
        else:
            ratio = np.log(np.maximum(z, 0.1) / 2e-4) / np.log(10.0 / 2e-4)
            psrc = "neutral log profile, z0 = 2e-4 m (no COARE stability: subgrid disabled)"
        v = u10 * np.asarray(ratio)[..., None]
        if self.w3 is not None:
            up = self._wind3d(lon, lat, z, t)
            if up is not None:
                use = np.isfinite(up[..., 0])
                v = np.where(use[..., None], up, v)
                src += "; above 21 m in sortie hours: WRF 3-D U/V log-linear in z"
        return Tagged(v, f"{src}; below the first level: {psrc}", self.sig["wind_ms"], "data")

    def _wind3d(self, lon, lat, z, t):
        """3-D WRF wind (east, north) where z is above the first mass level and t is within an ingested 3-D hour pair, else NaN. U3/V3 are
        grid-relative like U10, so they go through the same COSALPHA/SINALPHA rotation before the vertical interpolation."""
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
            for kk, ww in ((k, 1 - w), (k + 1, w)):
                zc = np.stack([interp(Z[kk, l], [self.law, self.low], [latq[m], cv.wrap360(lonq[m])])[0] for l in range(Z.shape[1])], -1)
                uc = np.stack([interp(self.w3["U"][kk, l], [self.law, self.low], [latq[m], cv.wrap360(lonq[m])])[0] for l in range(Z.shape[1])], -1)
                vc = np.stack([interp(self.w3["V"][kk, l], [self.law, self.low], [latq[m], cv.wrap360(lonq[m])])[0] for l in range(Z.shape[1])], -1)
                uc, vc = cv.rotate_grid_to_earth(uc, vc, ca, sa)             # grid-relative -> earth, like U10 (the 3-D fields are grid-relative too)
                lz = np.log(np.maximum(zc, 1.0))
                q = np.log(np.maximum(zq[m], 1.0))
                j = np.clip(np.sum(lz < q[:, None], axis=1) - 1, 0, lz.shape[1] - 2)
                r = np.arange(len(j))
                a = np.clip((q - lz[r, j]) / (lz[r, j + 1] - lz[r, j]), 0, 1)
                vals.append(ww[:, None] * np.stack([uc[r, j] + a * (uc[r, j + 1] - uc[r, j]), vc[r, j] + a * (vc[r, j + 1] - vc[r, j])], -1))
                below = zq[m] < zc[:, 0]
                vals[-1][below] = np.nan
            out[m] = vals[0] + vals[1]
        return out

    # ------------------------------------------------------------ waves

    def waves(self, lon, lat, t):
        s, src = self.sig, self.umwm_src
        d = lambda k: cv.math_rad_to_compass_to(np.arctan2(self._u(k + "_n", lon, lat, t), self._u(k + "_e", lon, lat, t)))
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

    def restart_spectrum(self, lon, lat, t, max_km=40.0, max_h=3.0):
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

    def current(self, lon, lat, z, t):
        if self.ocean is None:
            raise OutsideData("no ocean source loaded: run `cafe fetch` (GOFS 3.1 by default) or point ocean.source at the lab's HYCOM")
        v = self.ocean.current(lon, lat, z, t)
        if self.subgrid is not None:
            v = self.subgrid.current_extra(self, v, lon, lat, z, t)
        return v

    def density(self, lon, lat, z, t):
        v = self.ocean.density(lon, lat, z, t)
        return self.subgrid.density_extra(self, v, lon, lat, z, t) if self.subgrid is not None else v

    def sound_speed(self, lon, lat, z, t):
        return self.ocean.sound_speed(lon, lat, z, t)

    def depth(self, lon, lat):
        if self.ocean is not None and hasattr(self.ocean, "bathymetry"):
            return self.ocean.bathymetry(lon, lat)
        v, ins = interp(self.depth_umwm, [self.lau, self.lou], [lat, cv.wrap360(lon)])
        return Tagged(v, "UMWM depth (12 km)", None)

    def sst(self, lon, lat, t):
        v = Tagged(self._w("SST", lon, lat, t), f"{self.wrf_src} SST (frozen at 2023-03-01: SST_UPDATE=0)", self.sig["sst_k"])
        return self.subgrid.sst_extra(self, v, lon, lat, t) if self.subgrid is not None else v
