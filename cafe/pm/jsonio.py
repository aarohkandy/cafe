"""The one reader of a JSON file or text and the one test for a finite real number, standard library only (round 21, M-9): the live app image has no pyyaml,
so `cafe.pm.vv` (which `vehicle`, `hangar` and `mission` import), `cafe._seed` and the app's own files cannot import `cafe.pm.config`, which does. `config`
re-exports both under the names `config.load_json` and `config.finite_real`, which are the ones the rest of `cafe.pm` uses (`atomic.py` is the same
arrangement for the writer)."""
from __future__ import annotations

import json
import math
import pathlib
from typing import Any


def _json_int(text: str) -> int:
    n = int(text)
    try:
        float(n)
    except OverflowError:
        raise ValueError(f"an integer of {len(text)} characters is too large for a number (about 1.8e308 is the most a float holds)") from None
    return n


def load_json(src: str | bytes | pathlib.Path, **kw: Any) -> Any:
    """THE reader of a JSON file or text that a user can edit or a run wrote (round 21, M-9): `src` is the text (str, bytes) or a `pathlib.Path` of the file
    (OSError as `Path.read_text` gives it). `json.loads` with two failures that were no `ValueError` made one: an integer that does not fit a float (a
    400-digit literal: every later `float(x)`, `math.isfinite(x)` or product of it is an OverflowError, which each reader guarded one function at a time)
    and nesting deep enough to exhaust the stack (a RecursionError) are a `ValueError`, which every wrapper of a stored file already treats as damage.
    NaN, Infinity and -Infinity are read as Python reads them: the project writes a NaN `gci` on purpose (`cfd.gci`), so whether a non-finite float is
    allowed is each use's decision, made by `finite_real`. `kw` go to `json.loads` (an `object_pairs_hook`); `parse_int` is this function's."""
    text = src.read_text() if isinstance(src, pathlib.Path) else src
    try:
        return json.loads(text, parse_int=_json_int, **kw)
    except RecursionError:
        raise ValueError("nested too deeply to be read") from None


def finite_real(v: Any) -> bool:
    """THE test for a finite real number (round 21, M-9; the readers of `_seed`, `vv.gci_value` and `credibility` call it): not a bool, a string, None, NaN or
    infinity, nor an integer too large for a float (json.loads gives a 400-digit literal as an int, and math.isfinite raises OverflowError on it; `load_json`
    refuses one at the file, this is for a value that came by another way)."""
    try:
        return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
    except OverflowError:
        return False
