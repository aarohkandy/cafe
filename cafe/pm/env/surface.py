"""The modelled surface layer between the 12 km / 1 h files and a vehicle, precomputed once per mission cache.

    build(env, cache)  -> cache/derived.zarr (COARE 3.5 u*, z0, L, gf; warm-layer dT, depth; hours since rain;
                          parametric-spectrum Stokes surface drift) and the fit-vs-real-spectrum statistics
    SurfaceLayer(cache) -> the `subgrid` hook GriddedEnv calls (profile_ratio, surface_layer, stokes_surface,
                          current_extra, density_extra, sst_extra)

What is modelled here (every value is Tagged kind="modelled"; none of it is in the files):
- Wind below the first WRF level: COARE 3.5 (Edson et al. 2013) stability-corrected profile from U10, T2, Q2, PSFC,
  SST, SWDOWN, GLW, PBLH, with UMWM dcp as c_p and swh as H_s (wave-age / sea-state roughness).
- Diurnal warm layer (Fairall et al. 1996, NOAA COARE reference code): WRF's SST is frozen at 1 March, so the
  near-surface water is SST + dT_warm. It changes near-surface density and the surface-trapped jet proxy.
- Surface-trapped diurnal jet (TEPEX-C's own hypothesis, BRIEF 2.2): amplitude midpoint of config/subgrid.json's
  [u_min, u_max] x min(dT_warm / dT_ref, 1) along the wind, inside the warm layer; its half-range is the uncertainty.
- Rain fresh lens (Iyer & Drushka 2021): top 0.5 m, from rain rate, wind and time since the rain.
- Stokes surface drift: integrated from the DHH/JONSWAP spectrum fitted to UMWM's integrated parameters; at the
  6-hourly restart times the same integral over the REAL spectrum is the check on that fit (recorded by `build`).
Seawater expansion/contraction coefficients are TEOS-10 (gsw.alpha, gsw.beta) at the box's mean surface state.
"""
import json, pathlib

import numpy as np

from .. import Tagged
from . import coare, subgrid, waves
from . import conventions as cv
from .grid import Axis, interp

STRIDE = 3                                   # Stokes field on every 3rd UMWM node (36 km), same as the restart thinning


def _coare_grid(env, ti):
    """COARE 3.5 on the WRF grid at hour index ti."""
    W = env.W
    u10 = np.hypot(W["U10"][ti], W["V10"][ti])
    lat2 = np.broadcast_to(env.law.x[:, None], u10.shape)
    L2, A2 = np.meshgrid(env.low.x, env.law.x)
    cp, _ = interp(env.U["dcp"][min(ti, len(env.tu.x) - 1)], [env.lau, env.lou], [A2, L2])
    hs, _ = interp(env.U["swh"][min(ti, len(env.tu.x) - 1)], [env.lau, env.lou], [A2, L2])
    return coare.coare35(np.maximum(u10, 0.1), 10.0, W["T2"][ti], 2.0, W["Q2"][ti], 2.0, W["PSFC"][ti],      # SI: K, kg/kg, Pa
                         W["SST"][ti], W["SWDOWN"][ti], W["GLW"][ti], lat2, zi=np.maximum(W["PBLH"][ti], 100.0),
                         cp=cp, sigH=hs, rain=W["rain_mm_h"][ti])


def build(env, cache, log=print):
    import xarray as xr
    cache = pathlib.Path(cache)
    nt = len(env.tw.x)
    keys = ("ustar", "z0", "L", "gf")
    C = {k: np.empty((nt,) + env.W["U10"].shape[1:]) for k in keys}
    for ti in range(nt):
        r = _coare_grid(env, ti)
        for k in keys:
            C[k][ti] = r[k]
    W = env.W
    u10 = np.hypot(W["U10"], W["V10"])
    lon2 = np.broadcast_to(env.low.x[None, :], u10.shape[1:])
    lat2 = np.broadcast_to(env.law.x[:, None], u10.shape[1:])
    mv = lambda a: np.moveaxis(a, 0, -1)
    wl = coare.warm_layer(env.tw.x, mv(W["SWDOWN"]), mv(np.maximum(u10, 0.1)), mv(W["T2"]), mv(W["Q2"]),
                          mv(W["PSFC"]), mv(W["SST"]), mv(W["GLW"]), lat2, lon2,
                          zi=np.maximum(W["PBLH"], 100.0).mean(0), rain=mv(W["rain_mm_h"]))   # zi: per-cell mean PBLH (weak dependence)
    dT, dz = np.moveaxis(wl["dT_warm"], -1, 0), np.moveaxis(wl["dz_warm"], -1, 0)
    rain = W["rain_mm_h"]
    since = np.zeros_like(rain)
    trig = subgrid.assumption("subgrid.rain_lens.trigger_mm_h")
    since[0] = np.where(rain[0] > trig, 0.0, 1e9)                       # no rain seen yet: effectively never; set before the loop uses it
    for ti in range(1, nt):
        since[ti] = np.where(rain[ti] > trig, 0.0, since[ti - 1] + (env.tw.x[ti] - env.tw.x[ti - 1]))
    # Stokes surface drift from the parametric spectrum on a coarse UMWM grid
    js, is_ = np.arange(0, len(env.lau.x), STRIDE), np.arange(0, len(env.lou.x), STRIDE)
    th = waves.theta_compass(env.spec["th"]) if env.spec is not None else np.arange(5.625, 360, 11.25)
    f = env.spec["f"] if env.spec is not None else 0.0313 * 1.12246 ** np.arange(37)
    St = np.zeros((len(env.tu.x), len(js), len(is_), 2))
    for ti in range(len(env.tu.x)):
        g = lambda k, ti=ti: env.U[k][ti][np.ix_(js, is_)]
        dto = cv.math_rad_to_compass_to(np.arctan2(g("dwd_n"), g("dwd_e")))
        ok = np.isfinite(g("swh")) & (g("swh") > 1e-3)
        E = waves.spectrum_from_params(np.where(ok, g("swh"), 0.1), np.where(ok, g("dwp"), 8.0), np.where(ok, dto, 0.0),
                                       np.where(ok, g("mss"), 0.01), np.where(ok, g("wspd"), 5.0), f, th)
        St[ti] = np.where(ok[..., None], waves.stokes_profile(E, f, th, 0.0), np.nan)
    fit = None
    if env.spec is not None:
        St, fit = _correct_with_real(env, St, js, is_)
    ds = xr.Dataset({k: (("time", "lat", "lon"), C[k]) for k in keys}, coords=dict(time=env.tw.x, lat=env.law.x, lon=env.low.x))
    ds["dT_warm"] = (("time", "lat", "lon"), dT)
    ds["dz_warm"] = (("time", "lat", "lon"), dz)
    ds["since_rain_s"] = (("time", "lat", "lon"), since)
    ds["stokes_e"] = (("time_u", "lat_s", "lon_s"), St[..., 0])
    ds["stokes_n"] = (("time_u", "lat_s", "lon_s"), St[..., 1])
    ds = ds.assign_coords(time_u=env.tu.x, lat_s=env.lau.x[js], lon_s=env.lou.x[is_])
    ds.attrs["stokes_fit_check"] = json.dumps(fit)
    ds.to_zarr(cache / "derived.zarr", mode="w")
    log(f"surface layer: COARE on {nt} hours, warm layer max dT {np.nanmax(dT):.2f} K, Stokes fit check {fit}")
    return fit


def _real_stokes(env, it, js, is_):
    """Stokes surface drift from the REAL restart spectrum at restart time index `it`, on the (js, is_) coarse grid
    (the restart points were thinned on the same every-3rd-node lattice, so they land on it)."""
    S = env.spec
    E = waves.spectrum_from_restart(S["F"][it], S["k"][it], S["f"], S["th"])
    s = waves.stokes_profile(E, S["f"], waves.theta_compass(S["th"]), 0.0)
    R = np.full((len(js), len(is_), 2), np.nan)
    j = np.searchsorted(env.lau.x[js], S["lat"] - 1e-3)
    i = np.searchsorted(env.lou.x[is_], cv.wrap360(S["lon"]) - 1e-3)
    ok = (j < len(js)) & (i < len(is_))
    ok[ok] &= (np.abs(env.lau.x[js][j[ok]] - S["lat"][ok]) < 0.06) & (np.abs(env.lou.x[is_][i[ok]] - cv.wrap360(S["lon"][ok])) < 0.06)
    R[j[ok], i[ok]] = s[ok]
    return R


def _correct_with_real(env, St, js, is_):
    """Bias-correct the hourly parametric Stokes field with the real 6-hourly spectra.

    At each restart time the complex ratio c = (real_e + i real_n) / (fit_e + i fit_n) per node carries the speed error
    and the rotation; c is interpolated linearly in time (held beyond the first/last restart) and applied to every hour.
    The honest error estimate is leave-one-out: each interior restart is predicted from the corrections at its
    neighbours (12 h apart, twice the interpolation span actually used) and compared with its real spectrum."""
    S = env.spec
    T = [it for it, t in enumerate(S["t"]) if env.tu.x[0] <= t <= env.tu.x[-1]]
    hour = {it: int(np.argmin(np.abs(env.tu.x - S["t"][it]))) for it in T}
    z = lambda a: a[..., 0] + 1j * a[..., 1]
    real = {it: z(_real_stokes(env, it, js, is_)) for it in T}
    fitz = {it: z(St[hour[it]]) for it in T}
    good = lambda a, b: np.isfinite(a) & np.isfinite(b) & (np.abs(b) > 1e-4)
    C = {it: np.where(good(real[it], fitz[it]), real[it] / np.where(good(real[it], fitz[it]), fitz[it], 1.0), np.nan) for it in T}
    raw = [np.nanmedian(np.abs(np.abs(fitz[it]) / np.abs(real[it]) - 1)) for it in T]
    loo, ang = [], []
    for a, b, c in zip(T[:-2], T[1:-1], T[2:], strict=True):
        w = (S["t"][b] - S["t"][a]) / (S["t"][c] - S["t"][a])
        pred = ((1 - w) * C[a] + w * C[c]) * fitz[b]
        ok = good(real[b], pred)
        loo.append(np.median(np.abs(np.abs(pred[ok]) / np.abs(real[b][ok]) - 1)))
        ang.append(np.median(np.abs(np.degrees(np.angle(pred[ok] / real[b][ok])))))
    Ct = np.array([C[it] for it in T])
    tt = np.array([S["t"][it] for it in T])
    out = np.empty_like(St)
    for h, t in enumerate(env.tu.x):
        k = int(np.clip(np.searchsorted(tt, t) - 1, 0, len(tt) - 2))
        w = float(np.clip((t - tt[k]) / (tt[k + 1] - tt[k]), 0.0, 1.0))
        c = (1 - w) * Ct[k] + w * Ct[k + 1]
        c = np.where(np.isfinite(c), c, 1.0)                        # no real spectrum at this node: keep the fit
        v = c * z(St[h])
        out[h] = np.stack([v.real, v.imag], -1)
    return out, dict(n_restart_times=len(T), fit_only_median_speed_err=float(np.median(raw)),
                     corrected_loo_median_speed_err=float(np.median(loo)), corrected_loo_median_dir_err_deg=float(np.median(ang)))


class SurfaceLayer:
    def __init__(self, cache):
        import gsw
        import xarray as xr
        d = xr.open_zarr(pathlib.Path(cache) / "derived.zarr").load()
        self.t, self.la, self.lo = Axis(d.time.values, "time"), Axis(d.lat.values, "lat"), Axis(d.lon.values, "lon")
        self.D = {k: d[k].values for k in ("ustar", "z0", "L", "gf", "dT_warm", "dz_warm", "since_rain_s")}
        self.D["logz0"], self.D["invL"] = np.log(self.D.pop("z0")), 1.0 / self.D.pop("L")
        self.ts, self.las, self.los = Axis(d.time_u.values), Axis(d.lat_s.values), Axis(d.lon_s.values)
        self.S = (d.stokes_e.values, d.stokes_n.values)
        self.fit = json.loads(d.attrs.get("stokes_fit_check", "null"))
        self.cfg = subgrid.load_config()
        j = self.cfg["ocean"]["diurnal_jet"]
        self.jet_mid, self.jet_half = 0.5 * (j["u_min"] + j["u_max"]), 0.5 * (j["u_max"] - j["u_min"])
        self.jet_ref = subgrid.assumption("subgrid.diurnal_jet.dT_ref_K")
        self.alpha, self.beta = float(gsw.alpha(35.0, 28.0, 0.0)), float(gsw.beta(35.0, 28.0, 0.0))

    def _g(self, k, lon, lat, t):
        return interp(self.D[k], [self.t, self.la, self.lo], [t, lat, cv.wrap360(lon)])[0]

    def coare_at(self, lon, lat, t):
        return dict(ustar=self._g("ustar", lon, lat, t), z0=np.exp(self._g("logz0", lon, lat, t)),
                    L=1.0 / np.where(np.abs(il := self._g("invL", lon, lat, t)) < 1e-9, 1e-9, il), gf=self._g("gf", lon, lat, t))

    def profile_ratio(self, env, lon, lat, z, t):
        r = self.coare_at(lon, lat, t)
        num = coare.profile(r, np.asarray(z, float))
        den = coare.profile(r, 10.0)
        return np.where(den > 1e-6, num / np.where(den > 1e-6, den, 1.0), 1.0), "COARE 3.5 stability-corrected profile (modelled)"

    def surface_layer(self, env, lon, lat, t):
        r = self.coare_at(lon, lat, t)
        return dict(ustar=Tagged(r["ustar"], "COARE 3.5 from WRF + UMWM (modelled)", None, "modelled"),
                    L=Tagged(r["L"], "COARE 3.5 Obukhov length (modelled)", None, "modelled"),
                    dT_warm=Tagged(self._g("dT_warm", lon, lat, t), "COARE warm layer (Fairall 1996; modelled: WRF SST is frozen)", None, "modelled"))

    def stokes_surface(self, env, out, lon, lat, t):
        e = interp(self.S[0], [self.ts, self.las, self.los], [t, lat, cv.wrap360(lon)])[0]
        n = interp(self.S[1], [self.ts, self.las, self.los], [t, lat, cv.wrap360(lon)])[0]
        v = np.stack([e, n], -1)
        if self.fit is None:
            return Tagged(v, "Stokes surface drift from the spectrum fitted to UMWM swh/dwp/dwd/mss (modelled)", 0.4 * np.abs(v), "modelled")
        e = self.fit["corrected_loo_median_speed_err"]
        return Tagged(v, "Stokes surface drift: fitted spectrum corrected by the 6-hourly real UMWM spectra "
                         f"(leave-one-out median speed error {100 * e:.0f} %, fit alone {100 * self.fit['fit_only_median_speed_err']:.0f} %)",
                      e * np.abs(v), "modelled")

    def _warm(self, lon, lat, z, t):
        dT, dz = self._g("dT_warm", lon, lat, t), self._g("dz_warm", lon, lat, t)
        z = np.asarray(z, float)
        return dT * np.clip(1.0 + z / np.maximum(dz, 1e-3), 0.0, 1.0), dT    # linear from dT at 0 to 0 at -dz

    def current_extra(self, env, v, lon, lat, z, t):
        dTz, dT0 = self._warm(lon, lat, z, t)
        w = env.u10(lon, lat, t)
        sp = np.hypot(w[..., 0], w[..., 1])[..., None]
        unit = np.divide(w, sp, out=np.zeros_like(w), where=sp > 0)
        frac = np.clip(np.where(dT0 > 0, dTz / np.where(dT0 > 0, dT0, 1.0), 0.0) * np.minimum(dT0 / self.jet_ref, 1.0), 0, 1)[..., None]
        jet = self.jet_mid * frac * unit
        return Tagged(v.value + jet, v.source + "; + diurnal surface jet proxy (TEPEX-C hypothesis, modelled)",
                      v.uncertainty, "modelled" if np.any(frac > 0) else v.kind)

    def _lens(self, env, lon, lat, z, t):
        rain = env._w("rain_mm_h", lon, lat, t)
        u10 = np.hypot(*np.moveaxis(env.u10(lon, lat, t), -1, 0))
        return subgrid.rain_lens(rain, u10, self._g("since_rain_s", lon, lat, t), np.minimum(np.asarray(z, float), 0.0), self.cfg)

    def density_extra(self, env, v, lon, lat, z, t):
        dTz, _ = self._warm(lon, lat, z, t)
        lens = self._lens(env, lon, lat, z, t)
        # rain_lens dS is the freshening (+0.5 psu), so it lowers the density: less salt, lighter
        drho = v.value * (-self.alpha * (dTz + lens["dT"].value) - self.beta * lens["dS"].value)
        return Tagged(v.value + drho, v.source + "; + warm layer and rain lens (TEOS-10 alpha/beta; modelled)", v.uncertainty, v.kind)

    def sst_extra(self, env, v, lon, lat, t):
        dT = self._g("dT_warm", lon, lat, t)
        return Tagged(v.value + dT, v.source + " + COARE warm layer dT (modelled)", v.uncertainty, "modelled")
