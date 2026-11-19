"""Round 21 material (read only): the emulator table input of two runs, q22 against q21, and what the shared table holds now.
usage (orca, through bin/pmx.sh): python review/round_21/q22_tab.py"""
import json
import pandas as pd

R = "/data/runs/"
a = pd.read_parquet(R + "q22/emulator/train_input.parquet")
b = pd.read_parquet(R + "q21/emulator/train_input.parquet")
print("rows", len(a), len(b), "columns equal", list(a.columns) == list(b.columns))
da = json.load(open(R + "q22/emulator/design.json"))
db = json.load(open(R + "q21/emulator/design.json"))
for k in ("train_input_rows", "rows_added", "table_rows", "killed", "variants_run"):
    print(k, da.get(k), db.get(k))
key = [c for c in a.columns if c not in ("run_id", "git_sha", "code_digest")]
m = a.reset_index(drop=True).copy()
n = b.reset_index(drop=True).copy()
diff_rows = [i for i in range(min(len(m), len(n))) if not m.loc[i, key].astype(str).equals(n.loc[i, key].astype(str))]
print("rows differing in a column other than run_id, git_sha, code_digest:", len(diff_rows))
ida = [i for i in range(min(len(m), len(n))) if tuple(m.loc[i, ["run_id", "git_sha", "code_digest"]]) != tuple(n.loc[i, ["run_id", "git_sha", "code_digest"]])]
print("rows differing in run_id, git_sha or code_digest:", len(ida))
print("q22 identities", m.groupby(["run_id", "git_sha"]).size().to_dict())
print("q21 identities", n.groupby(["run_id", "git_sha"]).size().to_dict())
t = pd.read_parquet("/data/emulator/train.parquet")
print("shared table now", len(t), t.groupby(["run_id", "git_sha"]).size().to_dict() if "run_id" in t else "")
# the rows by position can differ only because the shared table moved on (q21's own rows replace an older group): compare the groups as sets
only_a = m[~m["run_id"].isin(n["run_id"])]
only_b = n[~n["run_id"].isin(m["run_id"])]
print("run ids only in q22's input", only_a["run_id"].unique().tolist(), len(only_a), "and only in q21's", only_b["run_id"].unique().tolist(), len(only_b))
common_a = m[m["run_id"].isin(n["run_id"])].reset_index(drop=True)
common_b = n[n["run_id"].isin(m["run_id"])].reset_index(drop=True)
print("rows of the run ids both inputs hold:", len(common_a), len(common_b), "equal in every cell:", common_a.astype(str).equals(common_b.astype(str)))
sa = only_a[key].astype(str).apply(tuple, axis=1)
sb = only_b[key].astype(str).apply(tuple, axis=1)
print("the new rows against the rows they replaced, as sets of rows (ids ignored): equal", set(sa) == set(sb), "| in both", len(set(sa) & set(sb)), "| only q22's", len(set(sa) - set(sb)), "| only q21's", len(set(sb) - set(sa)))
if len(only_a) == len(only_b):
    x = only_a.reset_index(drop=True)
    y = only_b.reset_index(drop=True)
    cols = [c for c in key if not x[c].astype(str).equals(y[c].astype(str))]
    print("columns that differ by position in those rows:", cols)
    for c in cols[:12]:
        try:
            print(" ", c, "max abs diff", float((x[c].astype(float) - y[c].astype(float)).abs().max()))
        except (TypeError, ValueError):
            print(" ", c, "not numeric")
