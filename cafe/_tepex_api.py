"""TEPEX-style deployment checks through the deployed API, on real HYCOM/WW3 + WRF data.

  A "chain"  : glider surveys 2 km north at 5-100 m; the boat stays over it (acoustic modem, 1 km);
               the quad flies 30 m over the boat for 20 min and comes home (radio, 300 m). Expected: workable.
  B "too far": same glider deployed 8 km from a boat that holds station; 2 km modem range. Expected: NO-GO
               on the link, with the separation as the reason.
"""
import json, os, sys, time, urllib.request

BASE = os.environ.get("CAFE_API", "http://100.108.213.121:8740")


def call(method, url, body=None):
    req = urllib.request.Request(BASE + url, data=json.dumps(body).encode() if body else None, method=method,
                                 headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


T0 = sys.argv[1] if len(sys.argv) > 1 else "2023-03-07T17:00"
SUB = sys.argv[2] if len(sys.argv) > 2 else "sample-petrel"      # the underwater drone
BOAT = sys.argv[3] if len(sys.argv) > 3 else "sample-tern"
LA, LO = 10.0, -95.0
chain = dict(name="TEPEX chain", t0=T0, max_hours=2.0, samples=16, drones=[
    dict(id="petrel", design=SUB, start=[LA, LO, 5], legs=[dict(type="goto", to=[LA + 0.018, LO, 100])]),
    dict(id="tern", design=BOAT, start=[LA - 0.002, LO, 0],
         legs=[dict(type="follow", target="petrel", offset=[0, 0, 0], minutes=110, tol_m=300)]),
    dict(id="gnat", design="sample-quad", start=[LA - 0.002, LO + 0.0005, 2],
         legs=[dict(type="follow", target="tern", offset=[0, 0, 30], minutes=20, tol_m=10), dict(type="goto", to="start")])],
    links=[dict(a="petrel", b="tern", max_m=1000, mode="horizontal", need=0.9),
           dict(a="tern", b="gnat", max_m=300, mode="3d", need=0.95, until_min=22)])
far = dict(name="TEPEX too far", t0=T0, max_hours=1.0, samples=16, drones=[
    dict(id="petrel", design=SUB, start=[LA + 0.072, LO, 5], legs=[dict(type="goto", to=[LA + 0.09, LO, 100])]),
    dict(id="tern", design=BOAT, start=[LA, LO, 0], legs=[dict(type="hold", minutes=55, tol_m=50)])],
    links=[dict(a="petrel", b="tern", max_m=2000, mode="horizontal", need=0.9)])

ids = {k: call("POST", "/api/missions", m)["id"] for k, m in (("chain", chain), ("far", far))}
print("submitted", ids, flush=True)
done = {}
while len(done) < len(ids):
    time.sleep(20)
    for k, i in ids.items():
        if k in done:
            continue
        r = call("GET", f"/api/missions/{i}")
        st = r["status"]
        if st.get("state") in ("done", "failed"):
            done[k] = r
            print(f"\n== {k} ({i}): {st.get('state')}  {st.get('error', '')}")
            res = r.get("result") or {}
            print("env:", res.get("env"))
            print("fleet:", res.get("fleet"))
            for d, x in (res.get("drones") or {}).items():
                f2 = lambda v, n=2: "-" if v is None else f"{v:.{n}f}"
                print(f"  {d:7s} {x['verdict']:9s} p={x['p_success']:.2f} reasons={[(y['reason'], round(y['share'], 2)) for y in x['reasons'][:2]]} "
                      f"battery left p50={f2(x.get('battery_left_p50'))} max depth={f2(x.get('max_depth_m'), 0)} m cruise={f2(x.get('cruise_mps'))}")
                for l in x["legs"]:
                    print(f"           leg {l['type']}: completed {l.get('completed')}, eta p50 {f2(l.get('eta_min_p50'), 1)} min, err95 p50 {f2(l.get('err95_m_p50'), 1)} m")
            for lk in res.get("links") or []:
                print(f"  link {lk['a']}-{lk['b']} <= {lk['max_m']} m: {lk['verdict']} p={lk['p_success']:.2f} in range p50={lk['in_range_p50']:.3f} "
                      f"longest outage p90={lk['longest_outage_s_p90']:.0f} s max sep p50={lk['max_sep_m_p50']:.0f} m")
print("\nview:", {k: f"{BASE}/?mission={i}#plan" for k, i in ids.items()})
