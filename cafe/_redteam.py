# Replays every red-team case (rounds 1 and 2) through the real HTTP app. Each line must say "rejected"
# (or "ok" for the controls); anything "ACCEPTED (bad!)" or a 500 is a regression.
import json, os
os.environ.setdefault("CAFE_WORK", "/work")
import numpy as np
import urllib.error, urllib.parse, urllib.request
from cafe import app as A, env as envm

BASE = os.environ.get("CAFE_API", "http://100.108.213.121:8740")


class Resp:
    def __init__(self, code, body, ctype):
        self.status_code, self.text, self.headers = code, body.decode(errors="replace"), {"content-type": ctype or ""}

    def json(self):
        return json.loads(self.text)


class Client:      # the deployed API over plain HTTP: tests what users actually hit
    def request(self, method, url, json=None, params=None, content=None, headers=None):
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = content.encode() if isinstance(content, str) else None
        if json is not None:
            data, headers = __import__("json").dumps(json).encode(), {"content-type": "application/json"}
        req = urllib.request.Request(BASE + url, data=data, method=method, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                return Resp(r.status, r.read(), r.headers.get("content-type"))
        except urllib.error.HTTPError as e:
            return Resp(e.code, e.read(), e.headers.get("content-type"))

    get = lambda self, url, **k: self.request("GET", url, **k)
    post = lambda self, url, **k: self.request("POST", url, **k)
    delete = lambda self, url, **k: self.request("DELETE", url, **k)


c = Client()
bad = 0


def expect(name, r, codes=(400, 404, 409, 422)):
    global bad
    ok = r.status_code in codes
    bad += not ok
    detail = r.json().get("detail") if r.headers.get("content-type", "").startswith("application/json") else r.text[:80]
    print(f"{'rejected' if ok else 'ACCEPTED (bad!)' if r.status_code < 400 else 'WRONG STATUS ' + str(r.status_code)}  {name}: {str(detail)[:110]}")


def raw(method, url, body):        # send NaN/Infinity literally, as a careless client would
    return c.request(method, url, content=json.dumps(body, allow_nan=True), headers={"content-type": "application/json"})


cov = c.get("/api/env/coverage").json()
T0 = cov["first"][:16]
LA, LO = 10.0, -95.0
leg = [{"type": "goto", "to": [LA + 0.01, LO, 0]}]
quad = lambda **k: dict(dict(id="q", design="sample-quad", start=[LA, LO, 2], legs=leg), **k)
mission = lambda drones, **k: dict(dict(t0=T0, max_hours=0.5, samples=4, drones=drones), **k)

# ---- round 1
expect("self-follow", c.post("/api/missions", json=mission([quad(legs=[{"type": "follow", "target": "q", "minutes": 2}])])))
expect("follow loop", c.post("/api/missions", json=mission([quad(id="a", legs=[{"type": "follow", "target": "b", "minutes": 2}]),
                                                            quad(id="b", legs=[{"type": "follow", "target": "a", "minutes": 2}])])))
expect("design path traversal", c.post("/api/missions", json=mission([quad(design="../../etc")])))
expect("missing legs", c.post("/api/missions", json=mission([{"id": "q", "design": "sample-quad", "start": [LA, LO, 2]}])))
expect("huge samples", c.post("/api/missions", json=mission([quad()], samples=100000)))
expect("duplicate ids", c.post("/api/missions", json=mission([quad(), quad()])))

# ---- round 2: numbers that aren't
expect("start with NaN", raw("POST", "/api/missions", mission([quad(start=[float("nan"), LO, 2])])))
expect("goto with Infinity", raw("POST", "/api/missions", mission([quad(legs=[{"type": "goto", "to": [float("inf"), LO, 0]}])])))
expect("start latitude 95", c.post("/api/missions", json=mission([quad(start=[95, LO, 2])])))
expect("start as text", c.post("/api/missions", json=mission([quad(start=["x", LO, 2])])))
expect("max_hours as text", c.post("/api/missions", json=mission([quad()], max_hours="abc")))
expect("max_hours as bool", c.post("/api/missions", json=mission([quad()], max_hours=True)))
expect("drones not a list of objects", c.post("/api/missions", json=mission(["q"])))
expect("emulation of mission '..'", c.post("/api/emulations", json={"mission": ".."}))
expect("emulation of mission {}", c.post("/api/emulations", json={"mission": {"x": 1}}))
print(("rejected" if not A.ID_OK.match("..") and not A.ID_OK.match(".hidden") else "ACCEPTED (bad!)"), " ids '..' and '.hidden'")

# ---- round 2: places the data doesn't cover / land
expect("weather field outside the WRF domain", c.get("/api/env/field", params=dict(t=T0, lat0=-60, lat1=-59, lon0=10, lon1=11)))
expect("weather field n=5000", c.get("/api/env/field", params=dict(t=T0, lat0=9.5, lat1=10.5, lon0=-95.5, lon1=-94.5, n=5000)))
expect("reach outside the WRF domain", c.get("/api/reach", params=dict(design="sample-quad", lat=-60, lon=10, t=T0, hours=1)))
expect("reach below the glider's rated depth", c.get("/api/reach", params=dict(design="sample-petrel", lat=LA, lon=LO, t=T0, hours=6, z=5000)))
E = envm.Env(envm.dt.datetime.fromisoformat(T0), 0, (14, 20), (-104, -92), pad_deg=0.1)
g = np.mgrid[14:20:0.25, -104:-92:0.25].reshape(2, -1).T
land = g[E.surface(g[:, 0], g[:, 1], 0.0)["land"]]
if len(land):
    lp = [float(land[0][0]), float(land[0][1])]
    # the API accepts it (it can't know land without loading weather); the RUN must refuse it
    from cafe import mission as M, hangar
    try:
        M.World(dict(t0=T0, max_hours=0.2, samples=1, drones=[dict(id="b", vehicle=hangar.load_vehicle(A.DESIGNS / "sample-wigley"),
                                                                    start=[LA, LO, 0], legs=[{"type": "goto", "to": lp}])]), B=1)
        print("ACCEPTED (bad!)  run with a boat goto on land"); bad += 1
    except ValueError as e:
        print("rejected  run with a boat goto on land:", e)
else:
    print("(no land in the test box; land case skipped)")

# ---- round 2: designs
spec = dict(name="t", power_w=600, battery_wh=3000, mass=150)
shape = lambda s=None, **dims: dict(shape="monohull", dims=dims, spec=dict(spec, **(s or {})))
expect("spec claims to be a sample", c.post("/api/designs/shape", json=shape({"sample": True})))
expect("negative electronics load", c.post("/api/designs/shape", json=shape({"hotel_w": -5})))
expect("unknown material", c.post("/api/designs/shape", json=shape({"material": "unobtainium"})))
expect("unknown spec field", c.post("/api/designs/shape", json=shape({"warp_drive": 9})))
expect("boolean battery", c.post("/api/designs/shape", json=shape({"battery_wh": True})))
expect("boolean dimension", c.post("/api/designs/shape", json=shape(length=True)))
expect("monohull wider than long", c.post("/api/designs/shape", json=shape(length=1.0, beam=0.9)))
expect("quad motors overlapping", c.post("/api/designs/shape", json=dict(shape="quad", dims=dict(wheelbase=0.2, motor_d=0.12, body=0.1), spec=dict(spec, mass=1.5))))
expect("quad motor thinner than its arm", c.post("/api/designs/shape", json=dict(shape="quad", dims=dict(arm_d=0.05, motor_d=0.03), spec=dict(spec, mass=1.5))))
expect("glider chord longer than half the hull", c.post("/api/designs/shape", json=dict(shape="glider", dims=dict(length=0.6, wing_chord=0.5), spec=spec)))
expect("cog with text", c.post("/api/designs/shape", json=shape({"cog": ["a", 0, 0]})))
expect("rotors = 1000", c.post("/api/designs/shape", json=shape({"rotors": 1000})))

# ---- round 2: live sessions
r = c.post("/api/live", json=dict(t0=T0, drones=[quad(), dict(id="b", design="sample-wigley", start=[LA, LO + 0.01, 0])]))
if r.status_code != 200:
    print("WRONG STATUS", r.status_code, "live create (control):", r.text[:200]); bad += 1
else:
    sid = r.json()["id"]
    print(f"ok  live session id is {len(sid)} hex chars (unguessable)")
    base = r.json()["state"]["drones"]
    expect("live target NaN", raw("POST", f"/api/live/{sid}/step", dict(seconds=1, targets={"q": dict(lat=float("nan"), lon=LO)})))
    expect("live speed 1000 m/s", c.post(f"/api/live/{sid}/step", json=dict(seconds=1, targets={"q": dict(lat=LA, lon=LO, speed=1000)})))
    expect("live speed -1", c.post(f"/api/live/{sid}/step", json=dict(seconds=1, targets={"q": dict(lat=LA, lon=LO, speed=-1)})))
    expect("live negative altitude", c.post(f"/api/live/{sid}/step", json=dict(seconds=1, targets={"q": dict(lat=LA, lon=LO, z=-5)})))
    expect("live target as text", c.post(f"/api/live/{sid}/step", json=dict(seconds=1, targets={"q": "north"})))
    expect("live targets as a list", c.post(f"/api/live/{sid}/step", json=dict(seconds=1, targets=[1, 2])))
    # atomic: a good target for q plus a bad one for an unknown drone must change nothing
    expect("live good + unknown drone", c.post(f"/api/live/{sid}/step", json=dict(seconds=1, targets={"q": dict(lat=LA + 0.05, lon=LO, z=30), "zz": dict(lat=LA, lon=LO)})))
    st = c.post(f"/api/live/{sid}/step", json=dict(seconds=5, targets={})).json()["drones"]["q"]
    moved = abs(st["lat"] - base["q"]["lat"]) * 111e3
    print(("ok " if moved < 3 else "ACCEPTED (bad!)") + f"  rejected batch left q's target alone (moved {moved:.1f} m in 5 s)"); bad += moved >= 3
    expect("live unknown session", c.post("/api/live/deadbeef/step", json=dict(seconds=1)), codes=(404,))
    c.delete(f"/api/live/{sid}")
expect("live with 13 drones", c.post("/api/live", json=dict(t0=T0, drones=[quad(id=f"q{i}") for i in range(13)])))

# ---- round 2: physics guards
from cafe import dyn, geom, vehicle
q = geom.SAMPLES["quad"]
vq = vehicle.build("uav", q["make"](), dict(q["spec"], kind="uav"))
d = dyn.Dynamics(vq, 2); s = dyn.State(2, len(vq.actuators), p=[0, 0, -10.0])
s.v[:] = [5.0, 0, 2.0]; s.alive[1] = False
d.step(s, np.zeros((2, len(vq.actuators))), dict(flow_ned=np.zeros((2, 3))), 0.01, None)
print(("ok " if np.allclose(s.v[1], 0) and np.linalg.norm(s.v[0]) > 1 else "ACCEPTED (bad!)") + "  a crashed quad stops; a live one keeps flying")

print(f"\n{bad} regressions")
