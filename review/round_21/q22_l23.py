"""Round 21 material (read only): q22's L23 text and low-antenna card against the code and the documents.
usage (orca, through bin/pmx.sh, from the repo root): python review/round_21/q22_l23.py
Checks: q22's credibility.json limitations against credibility.LIMITATIONS (every id, text equal), L23 against `_l23_text()`, the docs/CREDIBILITY.md row, each of
the ten rows of comms.LOW_ANTENNA_PAIR_BAND and the nine Hs figures of credibility.LOW_ANTENNA_HS_BAND printed in the text, the envelope sentence, and the
usv-uas-rf card of report.json against `report._low_antenna_note` on the demo mission's heights."""
import json
import re

from cafe.pm import credibility as cr
from cafe.pm.physics import comms

R = "/data/runs/"
for run in ("q22", "q21"):
    j = json.load(open(R + run + "/report/credibility.json"))
    code = {x["id"]: x["text"] for x in cr.LIMITATIONS}
    got = {x["id"]: x["text"] for x in j["limitations"]}
    print(run, "limitations", len(got), "in the code", len(code), "ids equal", list(got) == list(code))
    diff = [i for i in code if got.get(i) != code[i]]
    print(run, "limitations whose text differs from credibility.LIMITATIONS:", diff, "(L19 carries this run's fit when there is one)")
t = {x["id"]: x["text"] for x in json.load(open(R + "q22/report/credibility.json"))["limitations"]}["L23"]
print("L23 equals _l23_text():", t == cr._l23_text(), len(t))
doc = open("docs/CREDIBILITY.md").read()
print("L23 inside the CREDIBILITY.md row:", ("| L23 | " + t + " | ") in doc)
for pair in sorted(comms.LOW_ANTENNA_PAIR_BAND):
    f = f"{pair[0]:g} m ({cr.LOW_ANTENNA_NAMES[pair[0]]}) with {pair[1]:g} m ({cr.LOW_ANTENNA_NAMES[pair[1]]}) {cr.pair_figures(pair)}, {cr.pair_effect(pair, True)}"
    print(" pair", pair, "printed:", f in t, "|", cr.pair_figures(pair), "|", cr.pair_effect(pair, True))
n = 0
for (lo, _), by in sorted(cr.LOW_ANTENNA_HS_BAND.items()):
    for h, x in by.items():
        s = f"at Hs {h} m {x[0]:+.1f} to {x[2]:+.1f} dB (median {x[1]:+.1f})"
        n += s in t
        print(" Hs figure", lo, h, s in t, s)
print("Hs figures printed:", n, "of 9")
print("envelope sentence printed:", cr.mid_envelope() in t, "|", cr.mid_envelope())
print("tolerance", cr.LOW_ANTENNA_ROW_TOL_M, "printed:", "within 0.001 m of a listed one" in t)
print("numbers in L23 (count):", len(re.findall(r"[+-]?\d+\.\d", t)))
rj = json.load(open(R + "q22/report/report.json"))
for k, v in rj["links"].items():
    print("link", k, "low_antenna:", (v.get("low_antenna") or "None")[:90], "| granularity", {a: b.get("value") for a, b in v["granularity"].items() if isinstance(b, dict) and "value" in b and a in ("never_required", "members", "needed")})
