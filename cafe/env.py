"""Environment from WRF output: wind, air, and (when the run was coupled) ocean currents and waves.

Reads any folder of wrfout files (WRF_DIR), each holding one or more times, on any WRF projection; hourly
surface-only wrfsfc files (UWIN-CM) work too, since every field used here is a surface field.
Fields are cut to the mission box, rotated from grid to earth axes (COSALPHA/SINALPHA), resampled to a
regular lat/lon grid if the projection is curvilinear, and interpolated linearly in space and time.

Ocean fields come from the coupler variables (UE_ESMF/VE_ESMF currents, HS_UMWM wave height) when a
run actually filled them; an uncoupled run leaves them all zero, which is detected per mission box and
reported, never silently treated as "calm, slack water".
"""
import datetime as dt, glob, os, pathlib
import numpy as np
import netCDF4
from scipy.interpolate import RegularGridInterpolator, griddata

WRF_DIR = pathlib.Path(os.environ.get("WRF_DIR", "/work/wrf"))
G = 9.81
KAPPA = 0.4
CHARNOCK = 0.011
RHO_SEA = 1025.0
CURRENT_EFOLD_M = 75.0   # ponytail: surface current decays e^(-d/75m) with depth; a 3-D ocean model replaces it


def _times(ds):
    return [dt.datetime.strptime(b"".join(t).decode(), "%Y-%m-%d_%H:%M:%S") for t in ds["Times"][:]]


_CAT = {}


def catalog(root=None):
    """{datetime: (path, time index)} for every time in every wrfout/wrfsfc file. Later files win duplicates."""
    root = pathlib.Path(root or WRF_DIR)
    files = sorted(f for pat in ("wrfout_*", "wrfsfc_*") for f in glob.glob(str(root / "**" / pat), recursive=True)
                   if not f.endswith(".part"))
    key = (str(root), tuple((f, os.path.getmtime(f)) for f in files))
    if key not in _CAT:
        out = {}
        for f in files:
            try:
                with netCDF4.Dataset(f) as ds:
                    for k, t in enumerate(_times(ds)):
                        out[t] = (f, k)
            except (OSError, KeyError, ValueError):
                continue          # half-downloaded or not netCDF: skip, don't crash the app
        _CAT.clear()
        _CAT[key] = dict(sorted(out.items()))
    return _CAT[key]


def hours_after(t0, root=None, cap=48.0):
    """How long a mission starting at t0 can run on the weather on disk: the contiguous hourly run from t0's
    hour, or `cap` when t0 sits on a lone snapshot (held constant, see Env)."""
    cat = catalog(root)
    t = t0.replace(minute=0, second=0, microsecond=0)
    if t not in cat:
        return 0.0
    if not any(u != t and abs((u - t).total_seconds()) <= 3 * 3600 for u in cat):
        return cap
    n = 0
    while t + dt.timedelta(hours=n + 1) in cat:
        n += 1
    return min(float(n), cap)


_GRID = {}


def grid(root=None):
    """(lat2d, lon2d, landmask2d, cosalpha, sinalpha, map_proj) of the first file."""
    cat = catalog(root)
    if not cat:
        raise ValueError(f"no wrfout files in {root or WRF_DIR}")
    f = next(iter(cat.values()))[0]
    if f not in _GRID:
        with netCDF4.Dataset(f) as ds:
            g = lambda n, d=None: ds[n][0].astype(float) if n in ds.variables else d
            lat, lon = g("XLAT"), g("XLONG")
            if "LANDMASK" in ds.variables:
                land = g("LANDMASK").astype(bool)
            elif "XLAND" in ds.variables:
                land = g("XLAND") == 1
            else:                                  # surface-only files: land-use category, water = ISWATER (16 USGS)
                lu = g("LU_INDEX")
                land = (lu != getattr(ds, "ISWATER", 16)) & (lu != getattr(ds, "ISLAKE", -1))
            _GRID.clear()
            _GRID[f] = (lat, lon, land, g("COSALPHA", np.ones_like(lat)), g("SINALPHA", np.zeros_like(lat)),
                        int(getattr(ds, "MAP_PROJ", 0)))
    return _GRID[f]


def lon360(lon):
    return np.mod(lon, 360.0)


class Env:
    """Fields cut to a lat/lon box and time window, interpolated linearly in space and time."""
    FIELDS = ("U10", "V10", "UST", "T2", "PSFC", "UE_ESMF", "VE_ESMF", "HS_UMWM")

    def __init__(self, t0, hours, lat_range, lon_range, root=None, pad_deg=0.5):
        cat = catalog(root)
        if not cat:
            raise ValueError("no weather data on the server yet (add wrfout files)")
        lat2, lon2, land2, ca, sa, proj = grid(root)
        lo2 = lon360(lon2)
        lo, hi = sorted(lon360(np.array(lon_range, float)))
        # the whole requested area must lie inside the weather domain: never extrapolate weather
        if not (lat2.min() <= min(lat_range) and max(lat_range) <= lat2.max() and lo2.min() <= lo and hi <= lo2.max()):
            raise ValueError(f"this area is outside the weather data ({lat2.min():.1f}..{lat2.max():.1f} N, "
                             f"{lon2.min():.1f}..{lon2.max():.1f} E)")
        la0, la1 = min(lat_range) - pad_deg, max(lat_range) + pad_deg
        box = (lat2 >= la0) & (lat2 <= la1) & (lo2 >= lo - pad_deg) & (lo2 <= hi + pad_deg)
        if box.sum() < 4:
            raise ValueError(f"mission area is outside the weather model domain "
                             f"({lat2.min():.1f}..{lat2.max():.1f} N, {lon2.min():.1f}..{lon2.max():.1f} E)")
        jj, ii = np.where(box)
        self.j, self.i = slice(jj.min(), jj.max() + 1), slice(ii.min(), ii.max() + 1)
        sub = lambda a: a[self.j, self.i]
        rect = proj in (3, 6)          # Mercator / lat-lon: rows are latitudes, columns longitudes
        if rect:
            self.lat, self.lon = sub(lat2)[:, 0], sub(lo2)[0, :]
            regrid = lambda a: a
        else:
            step = max(np.median(np.abs(np.diff(sub(lat2)[:, 0]))), 0.02)
            self.lat = np.arange(la0, la1 + step, step)
            self.lon = np.arange(lo - pad_deg, hi + pad_deg + step, step)
            LA, LO = np.meshgrid(self.lat, self.lon, indexing="ij")
            pts = np.column_stack([sub(lat2).ravel(), sub(lo2).ravel()])
            regrid = lambda a: griddata(pts, a.ravel(), (LA, LO), method="linear")
        self.land = regrid(sub(land2).astype(float)) > 0.5
        cosa, sina = sub(ca), sub(sa)
        hours_on_disk = sorted(cat)
        t0 = t0.replace(minute=0, second=0, microsecond=0)
        want = [t0 + dt.timedelta(hours=h) for h in range(int(np.ceil(hours)) + 2)]
        have = [t for t in want if t in cat]
        self.frozen = False
        near = min(hours_on_disk, key=lambda t: abs((t - t0).total_seconds()))
        lone = not any(t != near and abs((t - near).total_seconds()) <= 3 * 3600 for t in hours_on_disk)
        if len(have) < len(want) and lone:
            # an isolated snapshot (no other time within 3 h of it): hold it constant for the whole mission,
            # and say so everywhere
            have, self.frozen = [near], True
            self.snapshot_offset_h = (t0 - near).total_seconds() / 3600
            if abs(self.snapshot_offset_h) > 6:
                raise ValueError(f"the nearest weather on disk is {near:%Y-%m-%d %H:%M} UTC, "
                                 f"{abs(self.snapshot_offset_h):.0f} h from this mission; add weather for the mission time")
        elif not have:
            raise ValueError(f"no weather data for {t0:%Y-%m-%d %H:%M} UTC (on disk: {len(hours_on_disk)} hours between "
                             f"{hours_on_disk[0]:%Y-%m-%d %H}h and {hours_on_disk[-1]:%Y-%m-%d %H}h)")
        elif len(have) < len(want):
            missing = [t for t in want if t not in cat]
            raise ValueError(f"weather data stops at {missing[0]:%Y-%m-%d %H:%M} UTC; shorten the mission or add files")
        if len(have) == 1:
            self.frozen = True
        self.t0, self.data_time = t0, have[0]
        data = {k: [] for k in self.FIELDS}
        for t in have:
            path, k = cat[t]
            with netCDF4.Dataset(path) as ds:
                for name in self.FIELDS:
                    v = ds[name][k][self.j, self.i] if name in ds.variables else np.zeros(cosa.shape)
                    data[name].append(np.ma.filled(np.asarray(v, float), np.nan))
        # grid-relative -> earth-relative vectors
        for u, v in (("U10", "V10"), ("UE_ESMF", "VE_ESMF")):
            U, V = np.array(data[u]), np.array(data[v])
            data[u], data[v] = U * cosa - V * sina, V * cosa + U * sina
        present = lambda name: bool(np.nanmax(np.abs(np.array(data[name]))) > 0)
        self.has_current = present("UE_ESMF") or present("VE_ESMF")
        self.has_waves = present("HS_UMWM")
        self.sources = dict(
            wind="WRF 10 m wind" + (f" (one snapshot at {have[0]:%Y-%m-%d %H:%M} UTC, held constant in time)" if self.frozen else ""),
            current="coupled ocean model (WRF coupler)" if self.has_current else "not in the weather files: assumed 0 with uncertainty",
            waves="wave model (UMWM) height" if self.has_waves else "estimated from local wind (fully developed sea)")
        # public ocean data when the weather run had no ocean (CAFE_OCEAN=0 turns this off)
        self._hy = self._ww = None
        if os.environ.get("CAFE_OCEAN", "1") != "0":
            from cafe import ocean
            lat_r, lon_r = (float(self.lat.min()), float(self.lat.max())), (float(self.lon.min()), float(self.lon.max()))
            if not self.has_current:
                try:
                    c = ocean.currents(t0, hours, lat_r, lon_r)
                    ax = (c["t_s"] if len(c["t_s"]) > 1 else np.r_[c["t_s"], c["t_s"] + 1e9], c["depth"], c["lat"], c["lon"])
                    rep = (lambda a: a) if len(c["t_s"]) > 1 else (lambda a: np.concatenate([a, a]))
                    self._hy = {k: RegularGridInterpolator(ax, rep(np.nan_to_num(c[k])), bounds_error=False, fill_value=None) for k in ("u", "v")}
                    self._hy_dmax = float(c["depth"][-1])
                    self._floor = RegularGridInterpolator((c["lat"], c["lon"]), np.nan_to_num(c["floor"], nan=1e4), method="nearest",
                                                          bounds_error=False, fill_value=1e4)
                    self.has_current = True
                    self.sources["current"] = "HYCOM GOFS 3.1 ocean analysis (3-D, 1/12 deg, 3-hourly)"
                except Exception as e:
                    self.sources["current"] += f" (HYCOM unavailable: {type(e).__name__})"
            if not self.has_waves:
                try:
                    w = ocean.waves(t0, hours, lat_r, lon_r)
                    ax = (w["t_s"] if len(w["t_s"]) > 1 else np.r_[w["t_s"], w["t_s"] + 1e9], w["lat"], w["lon"])
                    rep = (lambda a: a) if len(w["t_s"]) > 1 else (lambda a: np.concatenate([a, a]))
                    rad = np.radians(w["dir_from"])        # interpolate direction as a vector, not an angle
                    self._ww = {k: RegularGridInterpolator(ax, rep(np.nan_to_num(a)), bounds_error=False, fill_value=None)
                                for k, a in (("hs", w["hs"]), ("tp", w["tp"]), ("dn", np.cos(rad)), ("de", np.sin(rad)))}
                    self.has_waves = True
                    self.sources["waves"] = "NOAA WAVEWATCH III (0.5 deg, hourly)"
                except Exception as e:
                    self.sources["waves"] += f" (WAVEWATCH III unavailable: {type(e).__name__})"
        th = np.arange(len(have)) * 3600.0
        if len(th) == 1:
            th = np.array([0.0, 1e9]); data = {k: [v[0], v[0]] for k, v in data.items()}
        self._f = {k: RegularGridInterpolator((th, self.lat, self.lon), np.array([regrid(a) for a in v]),
                                              bounds_error=False, fill_value=None) for k, v in data.items()}
        self._land = RegularGridInterpolator((self.lat, self.lon), self.land.astype(float), method="nearest",
                                             bounds_error=False, fill_value=1.0)

    def surface(self, lat, lon, t_s):
        """Raw fields at points; t_s = seconds after t0. Vectorized over points. Points that drift past the
        loaded box get the nearest edge value (held, never linearly extrapolated)."""
        p = np.column_stack(np.broadcast_arrays(t_s, lat, lon360(np.asarray(lon, float))))
        p[:, 1] = np.clip(p[:, 1], self.lat.min(), self.lat.max())
        p[:, 2] = np.clip(p[:, 2], self.lon.min(), self.lon.max())
        out = {k: f(p) for k, f in self._f.items()}
        out["land"] = self._land(p[:, 1:]) > 0.5
        return out

    def at(self, lat, lon, t_s, z_up):
        """Wind (NE, m/s) at height z_up>0, current (NE) at depth z_up<0, air & water density, wave height."""
        s = self.surface(lat, lon, t_s)
        z = np.asarray(z_up, float)
        u10 = np.hypot(s["U10"], s["V10"])
        ust = np.maximum(s["UST"], 1e-3)
        z0 = CHARNOCK * ust ** 2 / G + 0.11 * 1.5e-5 / ust          # Charnock + smooth-flow term
        h = np.clip(z, 0.5, 200.0)                                   # ponytail: surface layer only; WRF 3-D above 200 m
        scale = np.log(h / z0) / np.log(10.0 / z0)
        wind = np.column_stack([s["V10"], s["U10"]]) * scale[..., None]     # (north, east)
        pts = np.column_stack(np.broadcast_arrays(t_s, lat, lon360(np.asarray(lon, float))))
        pts[:, 1] = np.clip(pts[:, 1], self.lat.min(), self.lat.max())
        pts[:, 2] = np.clip(pts[:, 2], self.lon.min(), self.lon.max())
        if self._hy is not None:
            depth = np.clip(np.maximum(-z, 0), 0, self._hy_dmax)
            q = np.column_stack([pts[:, 0], depth, pts[:, 1], pts[:, 2]])
            current = np.column_stack([self._hy["v"](q), self._hy["u"](q)])
            floor = self._floor(pts[:, 1:])
        else:
            current = np.column_stack([np.nan_to_num(s["VE_ESMF"]), np.nan_to_num(s["UE_ESMF"])])
            current *= np.exp(-np.maximum(-z, 0) / CURRENT_EFOLD_M)[..., None]
            floor = None
        rho_air = s["PSFC"] / (287.05 * s["T2"])
        hs = tp = wdir = None
        if self._ww is not None:
            hs, tp = np.maximum(self._ww["hs"](pts), 0), np.maximum(self._ww["tp"](pts), 1.0)
            wdir = np.arctan2(-self._ww["de"](pts), -self._ww["dn"](pts))    # direction waves travel TOWARD
        elif self.has_waves:
            hs = np.nan_to_num(s["HS_UMWM"])
        return dict(wind_ne=wind, current_ne=current, u10=u10, ust=ust, rho_air=rho_air, rho_water=RHO_SEA,
                    land=s["land"], wind10_ne=np.column_stack([s["V10"], s["U10"]]), hs=hs, tp=tp, wave_to=wdir, floor=floor)


# ------------------------------------------------------------------ waves

def pm_sea(u10):
    """Fully developed Pierson-Moskowitz sea from 10 m wind: (Hs, Tp). Conservative upper bound —
    real seas are often fetch/duration limited (smaller)."""
    u195 = u10 * 1.026   # 10 m -> 19.5 m (Stewart, Intro. Phys. Oceanography eq. 16.28ff)
    hs = 0.21 * u195 ** 2 / G
    tp = 2 * np.pi * u195 / (0.877 * G)
    return hs, tp


def jonswap(f, hs, tp, gamma=3.3):
    """One-sided JONSWAP S(f) [m^2/Hz], normalized so 4*sqrt(m0) = hs."""
    fp = 1 / tp
    sig = np.where(f <= fp, 0.07, 0.09)
    s = f ** -5 * np.exp(-1.25 * (f / fp) ** -4) * gamma ** np.exp(-((f - fp) ** 2) / (2 * sig ** 2 * fp ** 2))
    m0 = np.trapezoid(s, f)
    return s * (hs / 4) ** 2 / m0


def sea_state(sample):
    """(Hs, Tp) from an Env.at() sample: the wave model's Hs when the run had one (Tp = 4.5 sqrt(Hs), the
    middle of DNV-RP-C205's JONSWAP range 3.6-5), otherwise a fully developed sea from the local wind."""
    if sample.get("hs") is not None:
        hs = np.maximum(sample["hs"], 0.0)
        if sample.get("tp") is not None:
            return hs, np.maximum(sample["tp"], 1.0)
        return hs, np.maximum(4.5 * np.sqrt(hs), 1.0)
    return pm_sea(sample["u10"])


class Waves:
    """Random-phase linear deep-water wind sea, one component per frequency, directions drawn from
    a cos^2 spreading about the wind. z positive up, 0 = mean surface. Local NED-horizontal x=N, y=E."""

    def __init__(self, hs, tp, heading_to_rad, n=40, seed=0):
        rng = np.random.default_rng(seed)
        self.hs, self.tp = hs, tp
        f = np.linspace(0.6 / tp, 3.5 / tp, n)
        df = f[1] - f[0]
        f = f + rng.uniform(-0.5, 0.5, n) * df   # jitter so the record never repeats
        self.a = (np.sqrt(2 * jonswap(f, hs, tp) * df) * hs / (4 * np.sqrt(np.sum(jonswap(f, hs, tp) * df)))
                  if hs >= 1e-3 else np.zeros(n))
        self.w = 2 * np.pi * f
        self.k = self.w ** 2 / G
        # cos^2 spreading via rejection sampling
        th = []
        while len(th) < n:
            c = rng.uniform(-np.pi / 2, np.pi / 2, 4 * n)
            th += list(c[rng.uniform(0, 1, 4 * n) < np.cos(c) ** 2])
        d = heading_to_rad + np.array(th[:n])
        self.cx, self.cy = np.cos(d), np.sin(d)
        self.ph = rng.uniform(0, 2 * np.pi, n)

    @staticmethod
    def stack(waves):
        """One object whose components carry a leading sample axis: arrays (B,1,K)."""
        w = Waves.__new__(Waves)
        for k in ("a", "w", "k", "ph", "cx", "cy"):
            setattr(w, k, np.stack([getattr(x, k) for x in waves])[:, None, :])
        w.hs = np.array([x.hs for x in waves]); w.tp = np.array([x.tp for x in waves])
        return w

    def _phase(self, x, y, t):
        x, y, t = (np.asarray(v, float)[..., None] for v in (x, y, t))
        return self.k * (x * self.cx + y * self.cy) - self.w * t + self.ph

    def eta(self, x, y, t):
        return np.sum(self.a * np.cos(self._phase(x, y, t)), -1)

    def pressure(self, x, y, z, t, rho=RHO_SEA):
        """Total gauge pressure at points; 0 above the instantaneous surface. Below the mean surface:
        hydrostatic + linear dynamic pressure; between mean surface and crest: hydrostatic to the
        local elevation (simple stretching)."""
        z = np.asarray(z, float)
        th = self._phase(x, y, t)
        eta = np.sum(self.a * np.cos(th), -1)
        dyn = rho * G * np.sum(self.a * np.exp(self.k * np.minimum(z, 0)[..., None]) * np.cos(th), -1)
        p = np.where(z < 0, -rho * G * z + dyn, rho * G * (eta - z))
        return np.where(z < eta, p, 0.0), eta

    def fields(self, x, y, z, t, rho=RHO_SEA):
        """Surface elevation above (x,y) and linear dynamic pressure at depth z (for z<0)."""
        th = self._phase(x, y, t).astype(np.float32)
        ac = self.a * np.cos(th)                                   # shared by elevation and pressure
        eta = ac.sum(-1)
        decay = np.exp((self.k * np.minimum(np.asarray(z, np.float32), 0)[..., None]).astype(np.float32))
        return eta.astype(float), rho * G * (ac * decay).sum(-1).astype(float)

    def orbital(self, x, y, z, t):
        """Fluid velocity and acceleration (N, E, Up) at points below the surface."""
        th = self._phase(x, y, t)
        e = self.a * self.w * np.exp(self.k * np.minimum(np.asarray(z, float), 0)[..., None])
        uh, w = e * np.cos(th), e * np.sin(th)
        ah, aw = e * self.w * np.sin(th), -e * self.w * np.cos(th)
        vel = np.stack([np.sum(uh * self.cx, -1), np.sum(uh * self.cy, -1), np.sum(w, -1)], -1)
        acc = np.stack([np.sum(ah * self.cx, -1), np.sum(ah * self.cy, -1), np.sum(aw, -1)], -1)
        return vel, acc


# ------------------------------------------------------------------ gusts

class Gusts:
    """Dryden low-altitude turbulence (MIL-HDBK-1797), each axis as a first-order Gauss-Markov
    process with the Dryden variance and time constant L/V. Batched: one independent process per sample.
    ponytail: v,w Dryden filters are 2nd order; 1st order keeps the variance and correlation time right."""

    def __init__(self, seed=0, B=1):
        self.rng = np.random.default_rng(seed)
        self.g = np.zeros((B, 3))

    @staticmethod
    def params(alt_m, w20):
        h = np.clip(alt_m, 3.0, 300.0) / 0.3048                           # feet
        k = 0.177 + 0.000823 * h
        sw = 0.1 * np.asarray(w20, float)
        su = sw / k ** 0.4
        lu = h / k ** 1.2 * 0.3048
        return np.stack([su, su, sw], -1), np.stack([lu, lu, h * 0.3048], -1)

    def step(self, dt_s, alt_m, w20, airspeed):
        sig, L = self.params(alt_m, w20)
        tau = L / np.maximum(airspeed, 1.0)[..., None] if np.ndim(airspeed) else L / max(airspeed, 1.0)
        phi = np.exp(-dt_s / tau)
        self.g = phi * self.g + sig * np.sqrt(1 - phi ** 2) * self.rng.standard_normal(self.g.shape)
        return self.g      # (B, 3): along-wind, cross-wind, vertical


if __name__ == "__main__":
    # waves: realized record must reproduce Hs and the spectral peak
    hs, tp = pm_sea(12.0)
    assert abs(hs - 0.21 * (12 * 1.026) ** 2 / G) < 1e-9 and 8 < tp < 10, (hs, tp)
    wv = Waves(hs, tp, 0.0, n=60, seed=1)
    t = np.arange(0, 3600 * 3, 0.5)
    eta = wv.eta(0.0, 0.0, t)
    hs_rec = 4 * eta.std()
    assert abs(hs_rec / hs - 1) < 0.1, (hs_rec, hs)
    p, e = wv.pressure(0, 0, np.array([-200.0]), 0.0)
    assert abs(p[0] / (RHO_SEA * G * 200) - 1) < 1e-3   # deep: hydrostatic only
    p, e = wv.pressure(np.zeros(len(t[:200])), 0, np.full(200, -0.01), t[:200])
    assert np.all((p > 0) == (e > -0.01)), "pressure must vanish above the surface"
    # gusts: stationary std matches the Dryden sigma
    gs = Gusts(3)
    rec = np.array([gs.step(0.05, 30.0, 10.0, 8.0)[0] for _ in range(200000)])
    sig, _ = Gusts.params(30.0, 10.0)
    assert np.allclose(rec.std(0) / sig, 1, atol=0.1), (rec.std(0), sig)
    print("waves/gusts ok", hs, tp, hs_rec, sig)
    if catalog():
        cat = catalog()
        t0 = list(cat)[0]
        lat2, lon2, *_ = grid()
        jj, ii = lat2.shape[0] // 2, lat2.shape[1] // 3
        la, lo = float(lat2[jj, ii]), float(lon2[jj, ii])
        env = Env(t0, 3, (la - 0.5, la + 0.5), (lo - 0.5, lo + 0.5))
        s = env.at(np.array([la]), np.array([lo]), np.array([0.0]), np.array([10.0]))
        with netCDF4.Dataset(cat[t0][0]) as w:   # independent read at the same grid point
            u = float(w["U10"][cat[t0][1], jj, ii]); v = float(w["V10"][cat[t0][1], jj, ii])
            ca = float(w["COSALPHA"][0, jj, ii]) if "COSALPHA" in w.variables else 1.0
            sa = float(w["SINALPHA"][0, jj, ii]) if "SINALPHA" in w.variables else 0.0
        ue, vn = u * ca - v * sa, v * ca + u * sa
        assert abs(s["wind10_ne"][0, 0] - vn) < 0.05 and abs(s["wind10_ne"][0, 1] - ue) < 0.05, (s["wind10_ne"], vn, ue)
        assert 1.0 < s["rho_air"][0] < 1.3
        print("env ok", t0, len(cat), "times;", env.sources, s["wind_ne"], s["current_ne"], s["rho_air"])
