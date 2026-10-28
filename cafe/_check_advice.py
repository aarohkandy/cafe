"""Self-check for round 4: wind error widens away from a frozen snapshot, and every failure type comes with its margin
and fix. Offline (CAFE_OCEAN=0), a few minutes:  ./run.sh python -m cafe._check_advice"""
import os
os.environ["CAFE_OCEAN"] = "0"
import numpy as np
from cafe import geom, mission as M, vehicle

assert M.wind_sigma(0) == M.SIG["wind"] and M.wind_sigma(3) > M.wind_sigma(1) > M.wind_sigma(0)
assert M.wind_sigma(100) == np.hypot(M.SIG["wind"], M.SIG["wind_cap"]), "growth must saturate"


def build(key, kind, **kw):
    s = geom.SAMPLES[key]
    return vehicle.build(kind, s["make"](), dict(s["spec"], kind=kind, **kw))


quad, boat, sub = build("quad", "uav", battery_wh=1.0), build("quad", "uav"), build("torpedo", "uuv")
sub.limits["rated_depth_m"] = 10.0
hull = build("wigley", "usv", design_category="D")
LA, LO = 10.0, -95.0
m = dict(t0="2023-03-07T20:00", max_hours=0.12, samples=9, drones=[        # 3 h after the lone 17:00 snapshot
    dict(id="flat", vehicle=quad, start=[LA, LO, 2], legs=[dict(type="goto", to=[LA + 0.02, LO, 20])]),
    dict(id="far", vehicle=boat, start=[LA, LO + 0.001, 2], legs=[dict(type="goto", to=[LA + 0.3, LO, 20])]),
    dict(id="deep", vehicle=sub, start=[LA - 0.01, LO, 2], legs=[dict(type="goto", to=[LA - 0.01, LO + 0.004, 60])]),
    dict(id="skiff", vehicle=hull, start=[LA + 0.01, LO, 0], legs=[dict(type="hold", minutes=3)])],
    links=[dict(a="flat", b="far", max_m=50)])
w = M.World(m)
sig = M.wind_sigma(w.E.wind_lag_h(np.array([3 * 3600.0])))
assert w.E.frozen and sig > 2.0 and any("one snapshot" in x and "widened" in x for x in w.warnings), (w.E.frozen, sig, w.warnings)
assert abs(np.abs(w.wind_bias(0.0)).max() - np.abs(w.z_w).max() * M.wind_sigma(w.E.wind_lag_h(w.jitter))[np.abs(w.z_w).max(1).argmax()]) < 1e-9
r = M.run(m)
# (the skiff capsizes in this sea before the sea-state rule is reached, so that one is checked on the rule's own reason)
sea = M._advice(w.drones[3], np.array(["seas over design category D limit (0.3 m Hs)"] * 9, dtype=object), 1.0, 0.15, m)
print("skiff", *sea, sep="\n   ")
assert sea and sea[0].startswith("sea state: Hs") and "category" in sea[0], sea
need = dict(flat="battery", far="time", deep="depth")
for k, text in need.items():
    adv = r["drones"][k]["advice"]
    print(k, r["drones"][k]["verdict"], [x["reason"] for x in r["drones"][k]["reasons"]], *adv, sep="\n   ")
    assert any(a.startswith(text) and any(c.isdigit() for c in a) for a in adv), f"{k}: no {text} advice in {adv}"
print("link", *r["links"][0]["advice"], sep="\n   ")
assert r["links"][0]["advice"], "a failed range requirement must say by how much"
print("warnings", *r["warnings"], sep="\n   ")
assert any("no ocean current" in x for x in r["warnings"])
print("advice ok")
