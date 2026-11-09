"""Compare two demo run directories (read only): file bytes, json leaves, res.pkl arrays.

usage: python q13cmp.py A B   (run names under /data/runs)
"""
import hashlib
import json
import pickle
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

R = Path("/data/runs")
a, b = sys.argv[1], sys.argv[2]
ra, rb = R / a, R / b
SHOW = int(sys.argv[3]) if len(sys.argv) > 3 else 6


PROV = re.compile(r"/(ref|path|sha256|tree_sha256|code_digest|config_hash|git_sha|started|wall_s)$")


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()[:12]


def files(root):
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())


def flat(o, pre=""):
    if isinstance(o, dict):
        for k, v in o.items():
            yield from flat(v, f"{pre}/{k}")
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from flat(v, f"{pre}/{i}")
    else:
        yield pre, o


def same(x, y):
    if isinstance(x, float) and isinstance(y, float):
        return x == y or (x != x and y != y)
    return x == y and type(x) is type(y)


fa, fb = files(ra), files(rb)
print(f"## files: {a} {len(fa)}, {b} {len(fb)}; only in {a}: {sorted(set(fa) - set(fb))}; only in {b}: {sorted(set(fb) - set(fa))}")
print("## byte identity (sha-256 first 12)")
for f in sorted(set(fa) & set(fb)):
    if f.endswith((".pkl", ".parquet")):
        print(f"  {f}: {sha(ra / f)} {sha(rb / f)} {'SAME' if sha(ra / f) == sha(rb / f) else 'differs'}")
        continue
    s1, s2 = sha(ra / f), sha(rb / f)
    print(f"  {f}: {'SAME' if s1 == s2 else 'differs'}")

print("## json leaves")
tot_d = 0
for f in sorted(set(fa) & set(fb)):
    if not f.endswith(".json") or sha(ra / f) == sha(rb / f):
        continue
    try:
        ja, jb = json.loads((ra / f).read_text()), json.loads((rb / f).read_text())
    except Exception as e:
        print(f"  {f}: unreadable {e}")
        continue
    da, db = dict(flat(ja)), dict(flat(jb))
    keys = sorted(set(da) | set(db))
    diff = [k for k in keys if k not in da or k not in db or not same(da[k], db[k])]
    print(f"  {f}: {len(da)} vs {len(db)} leaves, {len(diff)} differ")
    tot_d += len(diff)
    grp = defaultdict(list)
    prov = 0
    for k in diff:
        g = re.sub(r"/\d+", "/#", k)
        if f.startswith("checkpoints/") and PROV.search(g):
            prov += 1
            continue
        grp[g].append(k)
    if prov:
        print(f"     {prov:5d} provenance leaves (refs, paths, input and output shas, code_digest, config_hash, git_sha, started, wall_s)")
    for g, ks in sorted(grp.items(), key=lambda t: -len(t[1])):
        k0 = ks[0]
        va = str(da.get(k0, "<absent>"))[:110]
        vb = str(db.get(k0, "<absent>"))[:110]
        print(f"     {len(ks):5d} x {g}   e.g. {k0}: {va!r} -> {vb!r}")
print(f"## total json leaves differing: {tot_d}")


def arrs(o, pre=""):
    if isinstance(o, dict):
        for k, v in o.items():
            yield from arrs(v, f"{pre}/{k}")
    elif isinstance(o, (list, tuple)):
        for i, v in enumerate(o):
            yield from arrs(v, f"{pre}/{i}")
    else:
        yield pre, o


for pk in ("stage1/res.pkl", "stage1b/res.pkl"):
    if pk not in fa or pk not in fb:
        print(f"## {pk} missing")
        continue
    # safe: pickles are res.pkl files our own runs wrote under /data/runs on orca, never a foreign file
    A = dict(arrs(pickle.load(open(ra / pk, "rb"))))
    B = dict(arrs(pickle.load(open(rb / pk, "rb"))))
    print(f"## {pk}: {len(A)} vs {len(B)} entries; only in a {len(set(A) - set(B))}; only in b {len(set(B) - set(A))}")
    nd = 0
    for k in sorted(set(A) & set(B)):
        x, y = A[k], B[k]
        if isinstance(x, np.ndarray) and isinstance(y, np.ndarray):
            if x.shape != y.shape or x.dtype != y.dtype:
                print(f"   {k}: shape/dtype {x.shape} {x.dtype} vs {y.shape} {y.dtype}")
                nd += 1
                continue
            if x.dtype.kind in "fc":
                eq = (x == y) | (np.isnan(x) & np.isnan(y))
            else:
                eq = x == y
            if not eq.all():
                nd += 1
                d = np.abs(x[~eq].astype(float) - y[~eq].astype(float)) if x.dtype.kind in "fiub" else None
                print(f"   {k}: {int((~eq).sum())} of {x.size} differ" + (f", max abs {np.nanmax(d):.3g}" if d is not None else ""))
        else:
            if not same(x, y):
                try:
                    if np.array_equal(np.asarray(x), np.asarray(y)):
                        continue
                except Exception:
                    pass
                nd += 1
                print(f"   {k}: {str(x)[:80]!r} vs {str(y)[:80]!r}")
    print(f"   arrays/leaves differing: {nd}")
