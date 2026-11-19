"""Round 22 material (read only; needs numpy and the two runs' res.pkl, no cafe import): the two runs' stage-1 result files compared value by value.
usage: python3 review/round_22/q23_pkl.py <run_a_dir> <run_b_dir>      (a run dir holds stage1/res.pkl and stage1b/res.pkl; the standard unpickler reads them,
they hold dicts, numpy arrays, strings and numbers only)
Prints, per file: the number of leaves (arrays and scalars) in each, the keys present in one only (with shape, dtype and the number of NaN), the leaves that differ
(path, shapes, the largest absolute difference where both are numeric) and the number of leaves that are equal (an array is equal when it has the same shape and
dtype kind and `np.array_equal(.., equal_nan=True)` is true; a float array is also compared as bytes, so a -0.0 against a 0.0 is counted apart)."""
import pickle
import sys

import numpy as np


def leaves(x, p=""):
    if isinstance(x, dict):
        for k, v in x.items():
            yield from leaves(v, f"{p}/{k}")
    elif isinstance(x, (list, tuple)):
        for i, v in enumerate(x):
            yield from leaves(v, f"{p}[{i}]")
    else:
        yield p, x


def same(a, b):
    a2, b2 = np.asarray(a), np.asarray(b)
    if a2.shape != b2.shape or a2.dtype.kind != b2.dtype.kind:
        return False, "shape or dtype kind"
    if a2.dtype.kind in "fiub":
        if not np.array_equal(a2, b2, equal_nan=True):
            return False, "values"
        if a2.dtype.kind == "f" and a2.tobytes() != b2.tobytes():
            return False, "bytes (a -0.0 or a NaN payload)"
        return True, ""
    return bool((a2 == b2).all()), "values"


def main(a, b):
    for f in ("stage1/res.pkl", "stage1b/res.pkl"):
        x = dict(leaves(pickle.load(open(f"{a}/{f}", "rb"))))
        y = dict(leaves(pickle.load(open(f"{b}/{f}", "rb"))))
        both = [k for k in x if k in y]
        eq, ne = [], []
        for k in both:
            ok, why = same(x[k], y[k])
            (eq if ok else ne).append((k, why))
        print(f"== {f}: {len(x)} and {len(y)} leaves; {len(eq)} equal, {len(ne)} differ, {len([k for k in x if k not in y])} only in a, {len([k for k in y if k not in x])} only in b")
        for k, why in ne:
            u, v = np.asarray(x[k]), np.asarray(y[k])
            d = float(np.nanmax(np.abs(u.astype(float) - v.astype(float)))) if u.shape == v.shape and u.dtype.kind in "fiub" else None
            print(f"  differs: {k} ({why}) shapes {u.shape} {v.shape}, largest absolute difference {d}")
        for k in x:
            if k not in y:
                print(f"  only in a: {k}")
        for k in y:
            if k not in x:
                v = np.asarray(y[k])
                nan = int(np.isnan(v).sum()) if v.dtype.kind == "f" else None
                print(f"  only in b: {k} shape {v.shape} dtype {v.dtype} NaN {nan} of {v.size}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
