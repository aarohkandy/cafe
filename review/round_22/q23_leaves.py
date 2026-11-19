"""Round 22 material (read only, no dependencies beyond the standard library): the json leaves that differ between two runs.
usage: python3 review/round_22/q23_leaves.py <run_a_dir> <run_b_dir> [file ...]   (default: the summaries, flip, credibility, report and the ledgers)
Prints, per file, the number of leaves in each run, the leaves that differ (path, a, b) and the keys present in one only."""
import json
import sys


def leaves(x, p=""):
    if isinstance(x, dict):
        for k, v in x.items():
            yield from leaves(v, f"{p}/{k}")
    elif isinstance(x, list):
        for i, v in enumerate(x):
            yield from leaves(v, f"{p}[{i}]")
    else:
        yield p, x


FILES = ["stage1/summary.json", "stage1b/summary.json", "emulator/flip.json", "report/report.json", "report/credibility.json", "ingest/derived.digest.json"] + [
    f"checkpoints/{s}/ledger.json" for s in ("ingest", "hangar", "windows", "stage3", "refit", "stage1", "stage1b", "emulator", "report")]


def main(a, b, files):
    for f in files:
        x = dict(leaves(json.load(open(f"{a}/{f}"))))
        y = dict(leaves(json.load(open(f"{b}/{f}"))))
        d = [(k, x[k], y[k]) for k in x if k in y and x[k] != y[k]]
        print(f"== {f}: {len(x)} and {len(y)} leaves, {len(d)} differ, {len([k for k in x if k not in y])} only in a, {len([k for k in y if k not in x])} only in b")
        for k, u, v in d:
            print(f"  {k}\n    a: {str(u)[:300]}\n    b: {str(v)[:300]}")
        for k in x:
            if k not in y:
                print(f"  only in a: {k} = {str(x[k])[:200]}")
        for k in y:
            if k not in x:
                print(f"  only in b: {k} = {str(y[k])[:200]}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3:] or FILES)
