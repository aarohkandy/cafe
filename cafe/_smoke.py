import json, sys, time
import numpy as np
from cafe import geom, vehicle, mission, ctrl
V = {}
for key, kind in (("torpedo", "uuv"), ("wigley", "usv"), ("quad", "uav")):
    s = geom.SAMPLES[key]
    t = time.time()
    V[kind] = vehicle.build(kind, s["make"](), s["spec"])
    print(kind, "built", f"{time.time()-t:.1f}s", "cruise", round(ctrl.cruise_speed(V[kind]), 2), "vmax", round(ctrl.max_speed(V[kind]), 2),
          "family", ctrl.family(V[kind]), "panels", None if V[kind].panels is None else len(V[kind].panels[0]))
lat, lon = 21.20, -158.40
m = dict(t0="2018-02-03T14:00", max_hours=float(sys.argv[1]) if len(sys.argv) > 1 else 0.25, samples=int(sys.argv[2]) if len(sys.argv) > 2 else 4, drones=[
    dict(id="sub", vehicle=V["uuv"], start=[lat, lon, 5], legs=[dict(type="goto", to=[lat + 0.0036, lon, 20]), dict(type="hold", minutes=3)]),
    dict(id="boat", vehicle=V["usv"], start=[lat, lon + 0.001, 0], legs=[dict(type="goto", to=[lat, lon + 0.005, 0]), dict(type="goto", to="start")]),
    dict(id="quad", vehicle=V["uav"], start=[lat, lon - 0.001, 2], legs=[dict(type="goto", to=[lat, lon - 0.001, 15]), dict(type="follow", target="boat", offset=[0, 0, 15], minutes=5)]),
])
t = time.time()
r = mission.run(m)
print(f"sim {r['t_sim']:.0f}s in {r['wall_s']:.0f}s wall")
for k, d in r["drones"].items():
    tr = d["track"][-1]
    print(k, d["verdict"], d["p_success"], d["reasons"], json.dumps(d["legs"]), "batt", round(d["battery_left_p50"], 3),
          "end", tr["lat"][0], tr["lon"][0], tr["z"][0], "rpy", tr["roll"][0], tr["pitch"][0], "Hs", round(d["hs_p50"], 2))
    for row in d["track"][::60]:
        print("   ", row["t"], row["lat"][0], row["lon"][0], row["z"][0], row["leg"][0], row["roll"][0], row["pitch"][0], row["yaw"][0])
