"""Shared check of a platform file's parameters against the table of what its model reads (`REQUIRED` in glider, usv, uas)."""

from typing import Any, Callable

import numpy as np

# kind -> (what the message says the value must be, test on the finite array); "other" (a name, a flag) only has to be present
_RULES: dict[str, tuple[str, Callable[[Any], Any]]] = {
    "pos": ("above 0", lambda a: a > 0),
    "nonneg": ("0 or above", lambda a: a >= 0),
    "frac": ("from 0 up to, not including, 1", lambda a: (a >= 0) & (a < 1)),
    "unit": ("from 0 to 1", lambda a: (a >= 0) & (a <= 1)),
    "any": ("", lambda a: np.ones(np.shape(a), bool)),
}


def _numeric(v: Any) -> Any:
    """`v` as a float array (a scalar or a list of numbers), or None for a string, a flag or anything else."""
    if isinstance(v, (str, bool)):
        return None
    try:
        return np.asarray(v, float)
    except (TypeError, ValueError):
        return None


def check_params(table: dict[str, str], vals: dict[str, Any], where: str, ref: str) -> None:
    """Raise ValueError naming the file part `where`, the field and the fix when a key of `table` is missing, or when a numeric value is NaN, infinite
    or outside its kind (`pos` > 0, `nonneg` >= 0, `frac` [0, 1), `unit` [0, 1], `any` signed; `other` only has to exist). Numbers the table does not
    list must still be finite. `ref` names the shipped platform file that shows the layout."""
    if missing := [k for k in table if k not in vals]:
        raise ValueError(f"{where}: missing {missing}; add them (see platforms/{ref}.yaml for the layout)")
    for k, v in vals.items():
        kind, a = table.get(k, "any"), _numeric(v)
        if kind == "other" or (a is None and k not in table):
            continue
        what, ok = _RULES[kind]
        if a is None or a.size == 0 or not np.isfinite(a).all() or not np.all(ok(a)):
            raise ValueError(f"{where}.{k}: {v!r} must be a finite number{' ' + what if what else ''}")
