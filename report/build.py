"""Fill template.html from the real run outputs: python3 build.py receipts.json curve.json tepex.json > report.html"""
import json, sys

receipts, curve, tepex = (json.load(open(p)) for p in sys.argv[1:4])
# Roddy 1990 drift tests (via Budak 2023 Table 6) as Y', N' x 1e3, same nondimensionalization as receipts.py
L, U, rho = 4.356, 6.5 * 0.514444, 998.2
q = 0.5 * rho * U ** 2
roddy = [[b, Y / (q * L ** 2) * 1e3, N / (q * L ** 3) * 1e3]
         for b, (Y, N) in {4.07: (45.43, 429.81), 8.00: (155.58, 737.14), 12.03: (350.65, 977.97)}.items()]
hl = [r for r in receipts if r["group"] == "Hull lift" and r["claim"].startswith("SUBOFF") and r.get("kind") != "context"
      and "drift" in r["claim"]]
if not hl:
    sys.exit('build.py: receipts.json has no SUBOFF drift rows to quote: need receipts with group "Hull lift", a claim starting '
             '"SUBOFF" and containing "drift", and kind other than "context" (re-run receipts.py with the hull-lift study done)')
errs = [abs(r["value"] / r["reference"] - 1) * 100 for r in hl]
before = [abs(r["value"] / r["reference"] - 1) * 100 for r in receipts if "WITHOUT hull lift" in r["claim"]]
if not before:
    sys.exit('build.py: receipts.json has no row whose claim contains "WITHOUT hull lift" (the side force before this round); '
             "re-run receipts.py with the hull-lift study done")
data = dict(
    receipts=receipts, curve=curve["curve"], cfd_angles=curve["angles"], roddy=roddy, tepex=tepex,
    stats=[["%RECEIPTS%", "validation receipts pass"],
           [f"{min(errs):.0f}–{max(errs):.0f} %", "error in SUBOFF side force and yaw moment, 4–12° drift, grid-converged"],
           [f"{min(before):.0f}–{max(before):.0f} % low", "the same side force before this round"],
           ["hourly", "WRF wind, 25 h of UWIN-CM installed"]])
html = open(sys.argv[0].replace("build.py", "template.html")).read()
# "<" escaped so no string in the data can close the <script> it is embedded in
print(html.replace("/*DATA*/null", json.dumps(data, separators=(",", ":")).replace("<", "\\u003c")))
