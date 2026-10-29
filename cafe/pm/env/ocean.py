"""The ocean behind GriddedEnv: currents, density, sound speed, temperature and bathymetry from the Zarr store
`cafe.pm.env.hycom` writes (GOFS 3.1 by default, or the lab's HYCOM through `hycom.ingest_lab_hycom`, same layout).

    open_ocean(spec, cache) -> Ocean      spec: the mission's environment.ocean ({source: gofs31 | lab_hycom, path?})

Query convention is the Environment protocol's: z in metres, positive UP (0 at the surface, -950 at a glider's apogee),
lon in any convention, t in seconds since 1970. The store is (time, depth positive down, lat, lon 0..360); fields are
loaded lazily, one variable at a time, as float32 (one variable over the TEPEX-C box is ~1.2 GB). Interpolation is
`grid.interp`: linear in time (3-hourly GOFS), depth, lat and lon; below-seafloor levels are NaN and dropped.
Uncertainties are not set here: the Stage-1 priors (current speed/direction) perturb the current in env.perturb.
"""
from __future__ import annotations

import os, pathlib
from typing import Any

import numpy as np

from .. import Tagged
from . import bathy, conventions as cv, hycom
from .grid import Axis, interp

DATA = pathlib.Path(os.environ.get("CAFE_DATA", "/data"))


def store_path(spec: dict[str, Any], mission_name: str | None) -> pathlib.Path:
    """Where the mission's ocean store is: the spec's `path` (lab HYCOM, already ingested) or DATA/ocean/gofs_<mission>.zarr."""
    if spec.get("path"):
        return pathlib.Path(spec["path"])
    if spec.get("source", "gofs31") != "gofs31":
        raise ValueError(f"ocean source {spec.get('source')!r} needs a `path` (run `hycom.ingest_lab_hycom` first)")
    return DATA / "ocean" / f"gofs_{mission_name}.zarr"


class Ocean:
    def __init__(self, path: Any, bathymetry: bathy.Bathymetry | None = None):
        self.path = pathlib.Path(path)
        self.ds = hycom.open_store(self.path)
        a = self.ds.attrs
        self.src = f"{a.get('source', 'HYCOM')} ({self.path.name}, manifest sha256 {str(a.get('manifest_sha256', '?'))[:12]})"
        self.axes = [Axis(self.ds.time.values, "time"), Axis(self.ds.depth.values, "depth"), Axis(self.ds.lat.values, "lat"),
                     Axis(self.ds.lon.values, "lon")]
        self.f: dict[str, Any] = {}
        self.bathy = bathymetry

    def _field(self, name: str) -> Any:
        if name not in self.f:
            self.f[name] = self.ds[name].values.astype("f4")
        return self.f[name]

    def _at(self, name: str, lon: Any, lat: Any, z: Any, t: Any) -> Any:
        v, _ = interp(self._field(name), self.axes, [t, -np.asarray(z, float), lat, cv.wrap360(lon)])
        return v

    def current(self, lon: Any, lat: Any, z: Any, t: Any) -> Tagged:
        u, v = self._at("water_u", lon, lat, z, t), self._at("water_v", lon, lat, z, t)
        return Tagged(np.stack([u, v], -1), f"{self.src} total current (east, north)", None, "modelled")

    def density(self, lon: Any, lat: Any, z: Any, t: Any) -> Tagged:
        return Tagged(self._at("rho", lon, lat, z, t), f"{self.src} in-situ density, TEOS-10 from T/S", None, "modelled")

    def sound_speed(self, lon: Any, lat: Any, z: Any, t: Any) -> Tagged:
        return Tagged(self._at("c", lon, lat, z, t), f"{self.src} sound speed, TEOS-10 from T/S", None, "modelled")

    def temperature(self, lon: Any, lat: Any, z: Any, t: Any) -> Tagged:
        return Tagged(self._at("water_temp", lon, lat, z, t), f"{self.src} in-situ temperature [degC]", None, "modelled")

    def bathymetry(self, lon: Any, lat: Any) -> Tagged:
        assert self.bathy is not None
        return self.bathy(lon, lat)


def open_ocean(spec: dict[str, Any], cache: Any, mission_name: str | None = None, box: tuple[float, ...] | None = None, fetch_bathy: bool = True,
               umwm: dict[str, Any] | None = None, gebco_url: str | None = None) -> Ocean | None:
    """The mission's Ocean, with bathymetry from GEBCO (cached under DATA/bathy), else the store's deepest level, else `umwm`
    (dict(lon, lat, depth) from the umwmout file, see bathy.from_umwm). gebco_url: where a missing GEBCO cut is fetched from."""
    path = store_path(spec, mission_name or pathlib.Path(cache).name)
    if not path.exists():
        return None
    ds = hycom.open_store(path)
    b = box or tuple(float(x) for x in (ds.lat.values[0], ds.lat.values[-1], ds.lon.values[0], ds.lon.values[-1]))
    return Ocean(path, bathy.choose(b, DATA / "bathy", gofs=path, umwm=umwm, fetch=fetch_bathy, url=gebco_url or bathy.GEBCO_URL))
