"""Round 18 addendum (item 2): fold the four `probe_<vehicle>.json` files that `probe_acting.py` wrote on orca into `review/round_18x/demo_probe.json`
(what tests/test_round18_x.py holds `stage1.ACTING` to): per vehicle, per quantity, per column, the largest absolute change of the quantity at each of the five
quantiles (over the members) and the quantity's own spread over the base members.

    python review/round_18x/summarize_probe.py <dir with probe_*.json> > review/round_18x/demo_probe.json
"""
import json
import pathlib
import sys

QS = ["0.05", "0.25", "0.5", "0.75", "0.95"]
out = dict(mission="missions/tepex_c_demo.yaml", environment="the demo's gridded cache (GOFS 3.1 ocean, WRF and UMWM), read from a private copy on orca",
           priors="the q19 run's ingest/priors_fitted.json", quantiles=[float(q) for q in QS], vehicles={})
for f in sorted(pathlib.Path(sys.argv[1]).glob("probe_*.json")):
    d = json.loads(f.read_text())
    quantities = {k: dict(base_sd=d["base"][k]["sd"], base_range=[d["base"][k]["lo"], d["base"][k]["hi"]],
                          max_abs={col: [d["moves"][col][q][k]["max_abs"] for q in QS] for col in d["moves"]})
                  for k in d["base"] if not k.startswith("_")}
    out["vehicles"][d["vehicle"]] = dict(cls=d["cls"], members=d["members"], base_member_index=d["base_idx"], quantities=quantities)
print(json.dumps(out, indent=1, sort_keys=True))
