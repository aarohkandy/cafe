"""Shared by the vehicle models: the check of a platform file's parameters against the table of what its model reads (`REQUIRED` in glider, usv, uas),
and the waypoint list a USV or glider is given."""

from typing import Any, Callable

import numpy as np

# kind -> (what the message says the value must be, test on the finite array); "other" (a name, a flag) only has to be present
_RULES: dict[str, tuple[str, Callable[[Any], Any]]] = {
    "pos": ("above 0", lambda a: a > 0),
    "nonneg": ("0 or above", lambda a: a >= 0),
    "frac": ("from 0 up to, not including, 1", lambda a: (a >= 0) & (a < 1)),
    "unit": ("from 0 to 1", lambda a: (a >= 0) & (a <= 1)),
    "any": ("", lambda a: np.ones(np.shape(a), bool)),
    "nonzero": ("other than 0", lambda a: a != 0),
    "ge1": ("1 or above", lambda a: a >= 1),
    "angle90": ("above 0 and below 90 degrees", lambda a: (a > 0) & (a < 90)),                       # round 8, M-28: an angle of attack or a heel
}


HINTS = {"r_int_ohm": "an ideal pack has no solution for the current at constant power; use 1e-6 for a near-ideal one"}          # round 8, M-11


def _rule(kind: str) -> tuple[str, Callable[[Any], Any]]:
    """The rule of a table kind: a name of `_RULES`, `<name><=max` (the same with a stated maximum), `range:lo:hi` (inclusive) or
    `list[n]:<kind>` (a one-dimensional list, of exactly n numbers when n is given, each of the kind; round 8, M-26)."""
    if kind.startswith("list"):
        n, _, inner = kind[4:].partition(":")
        what, ok = _rule(inner)
        return f"{what} in every place of a list{' of ' + n if n else ''}", lambda a: ok(a) & (np.ndim(a) == 1) & (np.size(a) == int(n or np.size(a)))
    if kind.startswith(("range:", "int:")):          # `int:lo:hi` is the same with a whole number (a count of cells; round 8, L1)
        lo, hi = (float(x) for x in kind.partition(":")[2].split(":"))
        whole = kind.startswith("int:")
        return f"{'a whole number ' if whole else ''}from {lo:g} to {hi:g}", lambda a: (a >= lo) & (a <= hi) & (a == np.floor(a) if whole else True)
    name, _, mx = kind.partition("<=")
    what, ok = _RULES[name]
    return (f"{what} and at most {mx}", lambda a: ok(a) & (a <= float(mx))) if mx else (what, ok)


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
    or outside its kind (`pos` > 0, `nonneg` >= 0, `frac` [0, 1), `unit` [0, 1], `any` signed, `nonzero`, `ge1`, `angle90` (0, 90);
    `<name><=max` adds a maximum, `range:lo:hi` is a closed interval, `int:lo:hi` the same for a whole number,
    `list[n]:<kind>` a list; `other` only has to exist). A listed value is a
    single number unless its kind says `list`: a list for a number is refused (round 8, M-26). Numbers the table does not list must still be
    finite. `ref` names the shipped platform file that shows the layout."""
    if missing := [k for k in table if k not in vals]:
        raise ValueError(f"{where}: missing {missing}; add them (see platforms/{ref}.yaml for the layout)")
    for k, v in vals.items():
        kind, a = table.get(k, "any"), _numeric(v)
        if kind == "other" or (a is None and k not in table):
            continue
        what, ok = _rule(kind)
        if a is None or a.size == 0 or not np.isfinite(a).all() or not np.all(ok(a)):
            raise ValueError(f"{where}.{k}: {v!r} must be a finite number{' ' + what if what else ''}{'; ' + HINTS[k] if k in HINTS else ''}")
        if a.ndim and not kind.startswith("list"):
            raise ValueError(f"{where}.{k}: {v!r} must be a number, got a list; give one value")


def check_shape(raw: dict[str, Any], name: str) -> None:
    """Raise ValueError when a glider or USV platform file's `params` or `mission_defaults` is not a mapping, or its `kind` is not a name. Both loaders
    read them as mappings (`.items()`, `in REQUIRED`), and the raw AttributeError or TypeError ended `validate`, stage 1 and `hangar` in a traceback
    (round 11, M-25); `uas.load_platform` has always answered with a ValueError."""
    for k in ("params", "mission_defaults"):
        if not isinstance(raw[k], dict):
            raise ValueError(f"{name}:{k}: expected a mapping of parameters, got {type(raw[k]).__name__}; each parameter has a `value`, a `unit` and a "
                             f"`source` (or `assumed: true` with a `why`)")
    if not isinstance(raw["kind"], str):
        raise ValueError(f"{name}:kind: {raw['kind']!r} must be a name (a string)")


def drop_repeats(wps: Any, cyclic: bool = False) -> Any:
    """The waypoints (n, 2) with every point that equals the one before it removed (round 9, M-13). A leg of length zero has no direction: the USV's
    cross-track error of it is 0 whatever the boat does, so a section of `[A, A]` ran with its track test off. `cyclic`: the list is flown round and
    round, so a last point equal to the first is the same point twice and goes too (its wrap leg has length zero)."""
    w = np.asarray(wps, float).reshape(-1, 2)
    w = w[np.r_[True, np.any(w[1:] != w[:-1], axis=1)]] if len(w) else w
    return w[:-1] if cyclic and len(w) > 1 and np.all(w[-1] == w[0]) else w
