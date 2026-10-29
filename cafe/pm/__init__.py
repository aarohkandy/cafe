"""cafe.pm — the TEPEX-C pre-mission pipeline: ingest -> hangar -> stage1 -> windows -> stage3 -> refit -> report.

Conventions every module in this package follows (tests in tests/test_conventions.py hold them):
- SI units. Time is float seconds since 1970-01-01 UTC (`T`); `t` arguments are that.
- Horizontal vectors are (east, north) components in the last axis, never speed + direction.
- Direction scalars are degrees clockwise from north and say which way: `*_from` (wind, meteorological) or `*_to`
  (waves, currents, vehicle heading). `cafe.pm.env.conventions` converts; nothing else does trig on directions.
- z is metres, positive up, 0 at mean sea level; depths are positive numbers named `depth`.
- Every environment value is a `Tagged`: the value, where it came from, and its 1-sigma uncertainty (same shape as
  value, or a scalar), so provenance reaches the report.
"""
from typing import Any, NamedTuple


class Tagged(NamedTuple):
    value: Any
    source: str           # e.g. "WRF wrfout_d01 U10/V10 (bilinear, linear in time)"
    uncertainty: Any      # 1-sigma, same units as value; a scalar, an array, or None when it is exact
    kind: str = "data"    # "data" (read from a file), "modelled" (cafe's model, not in any file), "assumed" (a prior)
