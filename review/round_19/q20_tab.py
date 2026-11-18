"""Round 19 material (read only): the emulator table input of two runs, q20 against q19, and what the shared table holds now.
usage (orca, through bin/pmx.sh): python review/round_19/q20_tab.py"""
import json
import pandas as pd

R = "/data/runs/"
a = pd.read_parquet(R + "q20/emulator/train_input.parquet")
b = pd.read_parquet(R + "q19/emulator/train_input.parquet")
print("rows", len(a), len(b), "columns equal", list(a.columns) == list(b.columns))
for n in ("design.json", "holdout.json"):
    pass
da = json.load(open(R + "q20/emulator/design.json"))
db = json.load(open(R + "q19/emulator/design.json"))
for k in ("train_input_rows", "rows_added", "table_rows", "killed", "variants_run"):
    print(k, da.get(k), db.get(k))
key = [c for c in a.columns if c not in ("run_id", "git_sha", "code_digest")]
m = a.reset_index(drop=True).copy()
n = b.reset_index(drop=True).copy()
diff_rows = [i for i in range(min(len(m), len(n))) if not m.loc[i, key].astype(str).equals(n.loc[i, key].astype(str))]
print("rows differing in a column other than run_id, git_sha, code_digest:", len(diff_rows))
ida = [i for i in range(min(len(m), len(n))) if tuple(m.loc[i, ["run_id", "git_sha", "code_digest"]]) != tuple(n.loc[i, ["run_id", "git_sha", "code_digest"]])]
print("rows differing in run_id, git_sha or code_digest:", len(ida))
print("q20 identities", m.groupby(["run_id", "git_sha"]).size().to_dict())
print("q19 identities", n.groupby(["run_id", "git_sha"]).size().to_dict())
t = pd.read_parquet("/data/emulator/train.parquet")
print("shared table now", len(t), t.groupby(["run_id", "git_sha"]).size().to_dict() if "run_id" in t else "")
