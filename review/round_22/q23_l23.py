"""Round 22 material (read only): q23's L23 text and RF link card against the code, the pin and the documents.
usage (orca, through bin/pmx.sh, from the repo root): python review/round_22/q23_l23.py
Checks: q23's credibility.json limitations against credibility.LIMITATIONS (every id, text equal; q22's too, where the text of L23 is the old one), L23 against
`_l23_text()`, the docs/CREDIBILITY.md row, each of the ten `credibility.L23_PAIRS` and four `L23_UAS_PAIRS` printed as the code formats them, each of the ten
against its row of `comms.LOW_ANTENNA_PAIR_BAND` (the largest difference of the three figures), the nine Hs figures of `credibility.LOW_ANTENNA_HS_BAND`, and the
`usv-uas-rf` card of q23's report.json against (a) `report._low_antenna_note` on the demo mission, (b) the literal `USV_UAS_CARD` of tests/test_round20_b.py (read
with `ast`, the test module is not imported), (c) `rfband.pair_band` for the whip and each UAS leg, and (d) the independent Fresnel reference of
tests/test_round18_b.py (`band`; imported where the import works, said otherwise). It ends with the code digest of the tree it runs in against the one
q23's nine ledgers carry (the checkout must be the one q23 ran on, `c58fba0`, or a document commit after it)."""
import ast
import json
import re

from cafe.pm import config, credibility as cr, pipeline, report
from cafe.pm.physics import comms, rfband

R = "/data/runs/"
for run in ("q23", "q22"):
    j = json.load(open(R + run + "/report/credibility.json"))
    code = {x["id"]: x["text"] for x in cr.LIMITATIONS}
    got = {x["id"]: x["text"] for x in j["limitations"]}
    print(run, "limitations", len(got), "in the code", len(code), "ids equal", list(got) == list(code))
    diff = [i for i in code if got.get(i) != code[i]]
    print(run, "limitations whose text differs from credibility.LIMITATIONS:", diff, "(L19 carries this run's fit when there is one; q22 was made with the older L23)")
t = {x["id"]: x["text"] for x in json.load(open(R + "q23/report/credibility.json"))["limitations"]}["L23"]
print("L23 equals _l23_text():", t == cr._l23_text(), len(t))
doc = open("docs/CREDIBILITY.md").read()
print("L23 inside the CREDIBILITY.md row:", ("| L23 | " + t + " | ") in doc)


def named(p):
    return f"{p[0]:g} m ({cr.LOW_ANTENNA_NAMES[p[0]]}) with {p[1]:g} m ({cr.LOW_ANTENNA_NAMES[p[1]]})"


worst = 0.0
for pair in cr.L23_PAIRS:
    b = rfband.pair_band(*pair)
    f = f"{named(pair)} {cr.band_figures(*b[:3])}, {cr.band_effect(b[0], b[2], True)}"
    row = comms.LOW_ANTENNA_PAIR_BAND.get(pair)
    d = max(abs(x - y) for x, y in zip(b[:3], row)) if row else None
    worst = max(worst, d or 0.0)
    print(" pair", pair, "printed:", f in t, "| live", [round(x, 3) for x in b], "| table row", row, "| largest difference", d)
print("largest difference between a printed live figure and its table row:", worst, "dB")
for pair in cr.L23_UAS_PAIRS:
    b = rfband.pair_band(*pair)
    s = f"{named(pair)} {cr.band_figures(*b[:3])} ({round(b[3] * rfband.N_POINTS)} of {rfband.N_POINTS} samples more than {rfband.OFF_DB:g} dB off)"
    print(" UAS pair", pair, "printed:", s in t, "|", s)
n = 0
for (lo, _), by in sorted(cr.LOW_ANTENNA_HS_BAND.items()):
    for h, x in by.items():
        s = f"at Hs {h} m {x[0]:+.1f} to {x[2]:+.1f} dB (median {x[1]:+.1f})"
        n += s in t
        print(" Hs figure", lo, h, s in t, s)
print("Hs figures printed:", n, "of 9")
print("numbers in L23 (count):", len(re.findall(r"[+-]?\d+\.\d", t)))
rj = json.load(open(R + "q23/report/report.json"))
for k, v in rj["links"].items():
    print("link", k, "low_antenna:", (v.get("low_antenna") or "None")[:90], "| granularity",
          {a: b.get("value") for a, b in v["granularity"].items() if isinstance(b, dict) and "value" in b and a in ("never_required", "members", "needed")})
card = rj["links"]["usv-uas-rf"]["low_antenna"]
mission = config.load_mission(R + "q23/mission.yaml")
lk = {x["id"]: x for x in mission["links"]}["usv-uas-rf"]
print("card equals report._low_antenna_note on the run's own mission.yaml:", card == report._low_antenna_note(lk, mission), len(card))
tree = ast.parse(open("tests/test_round20_b.py").read())
pin = [ast.literal_eval(s.value) for s in tree.body if isinstance(s, ast.Assign) and getattr(s.targets[0], "id", "") == "USV_UAS_CARD"][0]
print("card equals the literal USV_UAS_CARD of tests/test_round20_b.py character for character:", card == pin, len(pin))
for h in (18.1, 38.1, 68.1, 108.1):
    b = rfband.pair_band(2.2, h)
    s = f"2.2 m with {h:g} m {cr.band_figures(*b[:3])} ({round(b[3] * rfband.N_POINTS)} of {rfband.N_POINTS} samples are more than {rfband.OFF_DB:g} dB off)"
    print(" card pair", h, "printed:", s in card, "|", s)
try:
    from tests.test_round18_b import band as reference
    for h in (18.1, 38.1, 68.1, 108.1):
        print(" independent reference (tests/test_round18_b.band)", h, [round(float(x), 3) for x in reference(2.2, h)[:3]], "against rfband", [round(x, 3) for x in rfband.pair_band(2.2, h)[:3]])
except Exception as e:  # the reference lives in a test module: say so when it cannot be imported here
    print("independent reference not run:", repr(e)[:200])
led = {s: json.load(open(R + f"q23/checkpoints/{s}/ledger.json")) for s in ("ingest", "hangar", "windows", "stage3", "refit", "stage1", "stage1b", "emulator", "report")}
mine = pipeline.code_digest()
print("code_digest of this tree", mine, "| equal to the ledger's in", [s for s, d in led.items() if d["code_digest"] == mine], "| not equal in",
      [s for s, d in led.items() if d["code_digest"] != mine], "| git_sha of the ledgers", sorted({d["git_sha"] for d in led.values()}), "| git_dirty", sorted({d["git_dirty"] for d in led.values()}))
