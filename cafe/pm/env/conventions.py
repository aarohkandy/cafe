"""Direction conventions. The only place in cafe.pm that turns angles into vectors or back.

Compass: degrees clockwise from north. `from` = where it comes from (meteorological wind), `to` = where it goes.
Math: radians counter-clockwise from +x (east on the WRF/UMWM Mercator grid, whose COSALPHA is 1 to float precision).
UMWM `theta`, `wdir`, `mwd`, `dwd`: math convention, radians, direction waves travel toward, 0 = grid +x.

`waves.direction_convention` says how a wave-direction source reports its angles. It defaults to `umwm` (the line above).
A source that reports compass bearings the waves come FROM (WW3, most buoys) sets `compass_from`. It is read from the yaml
overlay named by $CAFE_PM_OVERLAY (unset: the default), e.g. `receipts --broken tests/fixtures/broken/wave_direction.yaml`,
which deliberately gives UMWM data the WW3 convention to show the receipts fail.
"""
from __future__ import annotations

import functools, os
from typing import Any

import numpy as np
from numpy.typing import ArrayLike, NDArray

F = NDArray[np.float64]

OVERLAY_ENV = "CAFE_PM_OVERLAY"
WAVE_CONVENTIONS = ("umwm", "compass_from")


@functools.lru_cache(maxsize=None)
def _overlay_wave_convention(path: str) -> str:
    import yaml
    with open(path) as fh:
        c = ((yaml.safe_load(fh) or {}).get("waves") or {}).get("direction_convention", "umwm")
    if c not in WAVE_CONVENTIONS:
        raise ValueError(f"{path}: waves.direction_convention is {c!r}, expected one of {WAVE_CONVENTIONS}")
    return str(c)


def wave_direction_convention() -> str:
    """`umwm` unless the overlay named by $CAFE_PM_OVERLAY sets waves.direction_convention."""
    path = os.environ.get(OVERLAY_ENV)
    return _overlay_wave_convention(path) if path else "umwm"


def wrap360(deg: ArrayLike) -> F:
    return np.mod(deg, 360.0)


def vec_from_to(speed: ArrayLike, to_deg: ArrayLike) -> F:
    """(east, north) of a vector of magnitude `speed` heading `to_deg` (compass)."""
    r = np.radians(to_deg)
    return np.stack([speed * np.sin(r), speed * np.cos(r)], axis=-1)


def vec_from_from(speed: ArrayLike, from_deg: ArrayLike) -> F:
    """(east, north) of a wind blowing from `from_deg` (compass)."""
    return vec_from_to(speed, np.asarray(from_deg) + 180.0)


def to_deg(v: ArrayLike) -> F:
    """Compass direction a vector (east, north) points toward."""
    v = np.asarray(v)
    return wrap360(np.degrees(np.arctan2(v[..., 0], v[..., 1])))


def from_deg(v: ArrayLike) -> F:
    """Compass direction a vector (east, north) comes from (meteorological)."""
    return wrap360(to_deg(v) + 180.0)


def speed(v: ArrayLike) -> F:
    out: F = np.hypot(np.asarray(v)[..., 0], np.asarray(v)[..., 1])
    return out


def math_rad_to_compass_to(theta: ArrayLike) -> F:
    """A wave-direction angle (radians) -> compass degrees toward. Default (`umwm`): radians CCW from grid +x = east, toward.
    `compass_from`: radians clockwise from north, the direction the waves come from (WW3, buoys)."""
    if wave_direction_convention() == "compass_from":
        return wrap360(np.degrees(theta) + 180.0)
    return wrap360(90.0 - np.degrees(theta))


def compass_to_to_math_rad(deg: ArrayLike) -> F:
    """Inverse of `math_rad_to_compass_to` under the same convention."""
    if wave_direction_convention() == "compass_from":
        return np.radians(np.asarray(deg) - 180.0)
    return np.radians(90.0 - np.asarray(deg))


def rotate_grid_to_earth(u: Any, v: Any, cosalpha: Any, sinalpha: Any) -> tuple[Any, Any]:
    """WRF grid-relative (u, v) -> earth (east, north), as wrf-python uvmet does: ue = u cos a - v sin a, ve = v cos a + u sin a."""
    return u * cosalpha - v * sinalpha, v * cosalpha + u * sinalpha
