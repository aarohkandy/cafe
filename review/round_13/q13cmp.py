"""Compare two demo run directories (read only): file bytes, json leaves, res.pkl arrays.

usage: python q13cmp.py A B   (run names under /data/runs)

The first line it prints is how many emulator variants each run ran (`emulator/design.json`). The emulator stage kills before a variant once the variants
have spent its wall-clock share (DECISIONS 288), so the count follows the machine's speed (round 13, look-ahead L2, P-R13L2-1). When the two counts differ, the
leaves of the emulator, flip and hold-out figures that moved are listed apart, as "load-dependent", and are not in the count of leaves that differ.
"""
import hashlib
import json
import pickle
import re
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

R = Path("/data/runs")

PROV = re.compile(r"/(ref|path|sha256|tree_sha256|code_digest|config_hash|git_sha|started|wall_s)$")
# what moves with the number of variants run, inside a file that is not itself the emulator's: report.json's emulator node, the flip fixes and the variant timing
LOAD_LEAF = re.compile(r"^/emulator/|/fix/|^/machine/timing/variants/")


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


def variants_run(root):
    """(variants run, variants planned, the kill's reason or None) from `emulator/design.json`; None for a run without one."""
    p = Path(root) / "emulator" / "design.json"
    if not p.is_file():
        return None
    d = json.loads(p.read_text())
    return len(d["variants"]), d["planned_variants"], (d.get("killed") or {}).get("reason")


def counts_differ(va, vb):
    """True when the two runs did not run the same emulator variants: a different number, a different killed state, or one without a design.json
    (an older run, or one where the emulator stage did not run: its emulator figures are not comparable to a run that has them)."""
    if va is None or vb is None:
        return (va is None) != (vb is None)
    return va[0] != vb[0] or bool(va[2]) != bool(vb[2])


def variant_line(a, b, va, vb):
    def show(v):
        return "no emulator/design.json" if v is None else f"{v[0]} of {v[1]} run" + (f" ({v[2]})" if v[2] else "")
    why = "one run has no emulator/design.json" if (va is None) != (vb is None) else "a kill at the stage share"
    verdict = (f"COUNT DIFFERS: the emulator, flip and hold-out figures below are load-dependent ({why}), not code"
               if counts_differ(va, vb) else "same count")
    return f"## variants run: {a} {show(va)}; {b} {show(vb)}; {verdict}"


def load_dependent(f, group):
    """True for a leaf group that moves with the number of variants run: any leaf of a file under `emulator/`, or a leaf of another file that LOAD_LEAF names."""
    return f.startswith("emulator/") or bool(LOAD_LEAF.search(group))


def compare_json(ra, rb, fa, fb, load):
    """Print the json leaves that differ and return (those that are not load-dependent, those that are; the second is 0 unless `load`)."""
    tot_d = tot_ld = 0
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
        grp, lgrp = defaultdict(list), defaultdict(list)
        prov = 0
        for k in diff:
            g = re.sub(r"/\d+", "/#", k)
            if f.startswith("checkpoints/") and PROV.search(g):
                prov += 1
            elif load and load_dependent(f, g):
                lgrp[g].append(k)
            else:
                grp[g].append(k)
        tot_d += len(diff) - sum(len(v) for v in lgrp.values())
        tot_ld += sum(len(v) for v in lgrp.values())
        if prov:
            print(f"     {prov:5d} provenance leaves (refs, paths, input and output shas, code_digest, config_hash, git_sha, started, wall_s)")
        for tag, groups in (("", grp), ("[load-dependent] ", lgrp)):
            for g, ks in sorted(groups.items(), key=lambda t: -len(t[1])):
                k0 = ks[0]
                va = str(da.get(k0, "<absent>"))[:110]
                vb = str(db.get(k0, "<absent>"))[:110]
                print(f"     {len(ks):5d} x {tag}{g}   e.g. {k0}: {va!r} -> {vb!r}")
    return tot_d, tot_ld


def arrs(o, pre=""):
    if isinstance(o, dict):
        for k, v in o.items():
            yield from arrs(v, f"{pre}/{k}")
    elif isinstance(o, (list, tuple)):
        for i, v in enumerate(o):
            yield from arrs(v, f"{pre}/{i}")
    else:
        yield pre, o


def compare_pkl(ra, rb, fa, fb):
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


def main(a, b, root=R):
    ra, rb = root / a, root / b
    va, vb = variants_run(ra), variants_run(rb)
    print(variant_line(a, b, va, vb))
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
    tot_d, tot_ld = compare_json(ra, rb, fa, fb, counts_differ(va, vb))
    print(f"## total json leaves differing: {tot_d}" + (f" (and {tot_ld} load-dependent: the variant counts differ)" if tot_ld else ""))
    compare_pkl(ra, rb, fa, fb)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
