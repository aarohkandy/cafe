"""The Environment interface every Stage-1 vehicle model is written against, and an analytic implementation for tests.

All methods are vectorized: lon, lat, z, t broadcast against each other (typically shape (M,) for M ensemble members).
Vectors come back with a trailing axis of 2 (east, north) or 3 (east, north, up).

    wind(lon, lat, z, t)      -> Tagged (..., 2) m/s at height z (m above MSL)
    current(lon, lat, z, t)   -> Tagged (..., 2) m/s at height z (negative = below the surface)
    waves(lon, lat, t)        -> dict of Tagged: Hs [m], Tp [s], dir_to [deg], Tm [s], mdir_to [deg], mss [-], stokes0 (..., 2) [m/s]
    density(lon, lat, z, t)   -> Tagged kg/m^3 (seawater for z <= 0)
    sound_speed(lon, lat, z, t) -> Tagged m/s
    depth(lon, lat)           -> Tagged m, positive, water depth at the point (0 on land)
    sst(lon, lat, t)          -> Tagged K
    air(lon, lat, t)          -> dict of Tagged: T2 [K], q2 [kg/kg], psfc [Pa], swdown [W/m2], glw [W/m2], rain [mm/h], ustar [m/s], L [m]
    bounds                    -> (lon_min, lon_max, lat_min, lat_max, t_min, t_max); lon in [-180, 180)
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

import numpy as np
from numpy.typing import ArrayLike, NDArray

from .. import Tagged


class Environment(Protocol):
    @property
    def bounds(self) -> tuple[float, ...]: ...

    def wind(self, lon: ArrayLike, lat: ArrayLike, z: ArrayLike, t: ArrayLike) -> Tagged: ...
    def current(self, lon: ArrayLike, lat: ArrayLike, z: ArrayLike, t: ArrayLike) -> Tagged: ...
    def waves(self, lon: ArrayLike, lat: ArrayLike, t: ArrayLike) -> dict[str, Tagged]: ...
    def density(self, lon: ArrayLike, lat: ArrayLike, z: ArrayLike, t: ArrayLike) -> Tagged: ...
    def sound_speed(self, lon: ArrayLike, lat: ArrayLike, z: ArrayLike, t: ArrayLike) -> Tagged: ...
    def depth(self, lon: ArrayLike, lat: ArrayLike) -> Tagged: ...
    def sst(self, lon: ArrayLike, lat: ArrayLike, t: ArrayLike) -> Tagged: ...
    def air(self, lon: ArrayLike, lat: ArrayLike, t: ArrayLike) -> dict[str, Tagged]: ...


class AnalyticEnv:
    """Uniform (or simply varying) fields for unit tests: every value is a constructor argument.

    current_profile(z) multiplies the surface current (default 1 above `ml_depth`, linear to 0 at 1000 m).
    """

    def __init__(self, wind: ArrayLike = (5.0, 0.0), current: ArrayLike = (0.0, 0.0), hs: float = 1.0, tp: float = 8.0, wave_to: float = 90.0,
                 depth: float = 4000.0, rho: float = 1024.0, c: float = 1540.0, sst: float = 302.0, rain: float = 0.0, swdown: float = 0.0,
                 current_profile: Callable[[Any], Any] | None = None,
                 bounds: tuple[float, ...] = (-180.0, 180.0, -90.0, 90.0, -1e12, 1e12)):
        self.u10, self.cur = np.asarray(wind, float), np.asarray(current, float)
        self.hs, self.tp, self.wave_to, self.h = hs, tp, wave_to, depth
        self.rho, self.c, self.T, self.rain, self.sw = rho, c, sst, rain, swdown
        self.profile = current_profile or (lambda z: np.clip(1.0 + np.minimum(np.asarray(z, float), 0) / 1000.0, 0, 1))
        self.bounds = bounds

    @staticmethod
    def _b(*a: ArrayLike) -> NDArray[np.float64]:
        return np.broadcast_arrays(*[np.asarray(x, float) for x in a])[0]

    def wind(self, lon: ArrayLike, lat: ArrayLike, z: ArrayLike, t: ArrayLike) -> Tagged:
        s = self._b(lon, lat, z, t)
        zz = np.maximum(np.broadcast_to(np.asarray(z, float), s.shape), 0.1)
        f = np.log(zz / 2e-4) / np.log(10.0 / 2e-4)                   # neutral log profile, z0 = 0.2 mm
        return Tagged(f[..., None] * self.u10, "analytic", 0.0, "assumed")

    def current(self, lon: ArrayLike, lat: ArrayLike, z: ArrayLike, t: ArrayLike) -> Tagged:
        s = self._b(lon, lat, z, t)
        p = self.profile(np.broadcast_to(np.asarray(z, float), s.shape))
        return Tagged(p[..., None] * self.cur, "analytic", 0.0, "assumed")

    def waves(self, lon: ArrayLike, lat: ArrayLike, t: ArrayLike) -> dict[str, Tagged]:
        s = self._b(lon, lat, t)

        def k(v: float) -> Tagged:
            return Tagged(np.full(s.shape, v, float), "analytic", 0.0, "assumed")
        return dict(Hs=k(self.hs), Tp=k(self.tp), dir_to=k(self.wave_to), Tm=k(0.8 * self.tp),
                    mdir_to=k(self.wave_to), mss=k(0.01), stokes0=Tagged(np.zeros(s.shape + (2,)), "analytic", 0.0, "assumed"))

    def density(self, lon: ArrayLike, lat: ArrayLike, z: ArrayLike, t: ArrayLike) -> Tagged:
        return Tagged(np.full(self._b(lon, lat, z, t).shape, self.rho), "analytic", 0.0, "assumed")

    def sound_speed(self, lon: ArrayLike, lat: ArrayLike, z: ArrayLike, t: ArrayLike) -> Tagged:
        return Tagged(np.full(self._b(lon, lat, z, t).shape, self.c), "analytic", 0.0, "assumed")

    def depth(self, lon: ArrayLike, lat: ArrayLike) -> Tagged:
        return Tagged(np.full(self._b(lon, lat).shape, self.h), "analytic", 0.0, "assumed")

    def sst(self, lon: ArrayLike, lat: ArrayLike, t: ArrayLike) -> Tagged:
        return Tagged(np.full(self._b(lon, lat, t).shape, self.T), "analytic", 0.0, "assumed")

    def air(self, lon: ArrayLike, lat: ArrayLike, t: ArrayLike) -> dict[str, Tagged]:
        s = self._b(lon, lat, t).shape

        def k(v: float) -> Tagged:
            return Tagged(np.full(s, v, float), "analytic", 0.0, "assumed")

        u = float(np.hypot(*self.u10))
        return dict(T2=k(self.T - 1.0), q2=k(0.018), psfc=k(101000.0), swdown=k(self.sw), glw=k(410.0),
                    rain=k(self.rain), ustar=k(0.035 * u + 0.01), L=k(-200.0))
