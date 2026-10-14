"""HTTP API + static UI. Long work runs as subprocesses that write status files, so the API stays
responsive and jobs survive a restart.

    uvicorn cafe.app:app --host 0.0.0.0 --port 8000
"""
import datetime as dt, json, math, os, pathlib, re, shutil, subprocess, sys, threading, time, uuid
import numpy as np
import trimesh
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from cafe import geom, shapes, env as envm

SHAPE_SAMPLES = {     # TEPEX-style examples built from simplified shapes (validation hulls come from geom.SAMPLES)
    "petrel": ("glider", dict(name="Petrel", kind="uuv", power_w=30, battery_wh=1000, hotel_w=0.6, buoyancy_cc=400,
                              material="al6061", wall_mm=7.0, structure="shell", note="example buoyancy glider (Slocum class)")),
    "tern": ("monohull", dict(name="Tern", kind="usv", mass=150, power_w=600, battery_wh=3000, hotel_w=25, prop_d=0.10,
                              material="gfrp", wall_mm=5.0, structure="shell", design_category="C",
                              note="example 2.5 m electric workboat USV")),
}

WORK = pathlib.Path(os.environ.get("CAFE_WORK", "/work"))
DESIGNS, MISSIONS = WORK / "designs", WORK / "missions"
STATIC = pathlib.Path(__file__).parent / "static"
KINDS = ("uuv", "usv", "uav")
app = FastAPI(title="cafe")


@app.exception_handler(ValueError)
def _bad_input(request, e):
    # the simulator raises ValueError for anything it can't honestly do with the input; that is the
    # caller's 400, not our 500
    return JSONResponse(status_code=400, content=dict(detail=str(e)))


def _read(p, default=None):
    try:
        return json.loads(pathlib.Path(p).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:24] or "drone"


# Jobs (characterizations, missions, emulations) are run by cafe.worker in its own container; the API only
# writes their files with state "queued", so restarting the API never kills a running job.


@app.on_event("startup")
def _startup():
    DESIGNS.mkdir(parents=True, exist_ok=True)
    MISSIONS.mkdir(parents=True, exist_ok=True)
    EMU.mkdir(parents=True, exist_ok=True)
    for key, (shape, spec) in SHAPE_SAMPLES.items():
        d = DESIGNS / f"sample-{key}"
        if not d.exists():
            _make_shape_design(d, shape, shapes.defaults(shape), dict(spec, sample=True))
    for key, s in geom.SAMPLES.items():
        d = DESIGNS / f"sample-{key}"
        if not d.exists():
            d.mkdir()
            s["make"]().export(d / "mesh.stl")
            spec = dict(s["spec"], kind=s["kind"], sample=True, units="m")
            (d / "spec.json").write_text(json.dumps(spec))
            (d / "status.json").write_text(json.dumps(dict(state="queued", step="waiting", progress=0.0, updated=time.time())))


# ------------------------------------------------------------------ designs

def _design_summary(d):
    spec = _read(d / "spec.json", {})
    st = _read(d / "status.json", {})
    res = _read(d / "result.json", {})
    perf = res.get("performance") or res.get("estimates") or {}
    return dict(id=d.name, name=spec.get("name", d.name), kind=spec.get("kind"), sample=spec.get("sample", False), shape=spec.get("shape"),
                status=st.get("state"), step=st.get("step"), progress=st.get("progress", 0),
                mass=spec.get("mass"), power_w=spec.get("power_w"), battery_wh=spec.get("battery_wh"),
                cruise=perf.get("cruise"), vmax=perf.get("vmax"), errors=res.get("errors") or st.get("errors"),
                warnings=res.get("warnings", []))


@app.get("/api/designs")
def list_designs():
    out = []
    for d in sorted(DESIGNS.glob("*")):
        if not (d / "spec.json").exists():
            continue
        try:   # one damaged record must not take the whole hangar down
            out.append(json.loads(json.dumps(_design_summary(d), allow_nan=False)))
        except (ValueError, TypeError):
            out.append(dict(id=d.name, name=d.name, status="failed", errors=["this design's files are damaged"]))
    return out


SPEC_FIELDS = dict(mass=float, power_w=float, battery_wh=float, hotel_w=float, prop_d=float, wall_mm=float,
                   rotors=int, wheelbase=float, appendage_factor=float, cells=int, buoyancy_cc=float, dive_m=float,
                   top_m=float, fin_area=float, rudder_area=float, mass_travel=float, pump_s=float, skeg_area=float)
SPEC_CHOICES = dict(structure=("shell", "solid"), design_category=("A", "B", "C", "D"), layout=("torpedo", "glider", "vectored6"),
                    units=("auto", "mm", "cm", "m", "in"), forward=("+x", "-x", "+y", "-y", "+z", "-z"),
                    up=("+x", "-x", "+y", "-y", "+z", "-z"), kind=KINDS)
SPEC_TEXT = ("name", "note")


def clean_spec(s, need):
    """The trust boundary for a design spec: known keys only, numbers finite and positive (hotel load and
    top depth may be 0), choices from their lists. Anything else is a 400, never a crash mid-characterization."""
    if not isinstance(s, dict):
        raise HTTPException(400, "spec must be a JSON object")
    from cafe import fea
    out = {}
    for k, v in s.items():
        if v in (None, ""):
            continue
        if k in SPEC_FIELDS:
            if isinstance(v, bool) or not isinstance(v, (int, float, str)):
                raise HTTPException(400, f"{k} must be a number")
            try:
                v = SPEC_FIELDS[k](float(v))
            except (ValueError, OverflowError):
                raise HTTPException(400, f"{k} must be a number")
            if not math.isfinite(v) or v < 0 or (v == 0 and k not in ("hotel_w", "top_m")):
                raise HTTPException(400, f"{k} must be a finite number above 0" + (" (or 0)" if k in ("hotel_w", "top_m") else ""))
        elif k in SPEC_CHOICES:
            if v not in SPEC_CHOICES[k]:
                raise HTTPException(400, f"{k} must be one of {', '.join(SPEC_CHOICES[k])}")
        elif k == "material":
            if v not in fea.MATERIALS:
                raise HTTPException(400, f"material must be one of {', '.join(fea.MATERIALS)}")
        elif k in SPEC_TEXT:
            v = str(v)[:200]
        elif k == "cog":
            if not (isinstance(v, list) and len(v) == 3 and all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in v)):
                raise HTTPException(400, "cog must be [x, y, z] in metres")
        elif k == "inertia":
            a = np.asarray(v, float) if isinstance(v, list) else None
            if a is None or a.shape != (3, 3) or not np.isfinite(a).all() or (np.diag(a) <= 0).any():
                raise HTTPException(400, "inertia must be a 3x3 matrix (kg m^2) with a positive diagonal")
        else:
            raise HTTPException(400, f"unknown spec field {k!r}")
        out[k] = v
    for k in need:
        if not out.get(k):
            raise HTTPException(400, f"{k} is required and must be positive")
    if out.get("rotors") is not None and not (3 <= out["rotors"] <= 12):
        raise HTTPException(400, "rotors must be 3 to 12")
    return out


@app.post("/api/designs")
async def create_design(mesh: UploadFile = File(...), spec: str = Form(...)):
    try:
        s = json.loads(spec, parse_constant=lambda c: (_ for _ in ()).throw(ValueError(c)))   # no NaN/Infinity
    except ValueError as e:
        raise HTTPException(400, f"spec must be plain JSON with finite numbers ({e})")
    if not isinstance(s, dict) or s.get("kind") not in KINDS:
        raise HTTPException(400, "kind must be one of uuv (under water), usv (on water), uav (over water)")
    s = clean_spec(s, ("mass", "power_w", "battery_wh"))
    suffix = pathlib.Path(mesh.filename or "m.stl").suffix.lower()
    if suffix not in (".stl", ".obj", ".ply", ".off", ".glb", ".gltf", ".step", ".stp", ".iges", ".igs", ".3mf"):
        raise HTTPException(400, f"can't read {suffix} files; use STL, OBJ, PLY, glTF, 3MF or STEP")
    did = f"{_slug(s.get('name', 'drone'))}-{uuid.uuid4().hex[:6]}"
    d = DESIGNS / did
    d.mkdir(parents=True)
    raw = d / f"upload{suffix}"
    raw.write_bytes(await mesh.read())
    try:
        m = geom.load(raw, s.get("units", "auto"), s.get("forward", "+x"), s.get("up", "+z"), s["kind"])
    except Exception as e:
        shutil.rmtree(d)
        raise HTTPException(400, f"couldn't read the model: {e}")
    m.export(d / "mesh.stl")
    if m.metadata.get("units_assumed"):
        s["units_assumed"] = m.metadata["units_assumed"]
    (d / "spec.json").write_text(json.dumps(s))
    (d / "status.json").write_text(json.dumps(dict(state="queued", step="waiting", progress=0.0, updated=time.time())))
    return _design_summary(d) | dict(extents=m.extents.round(4).tolist(), units_assumed=s.get("units_assumed"))


def _make_shape_design(d, shape, dims, spec):
    """Build a design from a simplified shape: mesh + structural parts + spec (with the shape's hints)."""
    m, parts, hints = shapes.build(shape, dims)
    d.mkdir(parents=True)
    m.export(d / "mesh.stl")
    for name, pm in parts.items():
        pm.export(d / f"part_{name}.stl")
    spec = dict(spec, **hints, shape=shape, dims=dims, kind=shapes.PARAMS[shape]["kind"], units="m")
    if spec.get("mass") in (None, "") and shapes.PARAMS[shape]["kind"] == "uuv":
        spec["mass"] = round(geom.RHO_SEA * m.volume, 2)          # trimmed neutral, as subs and gliders are
    (d / "spec.json").write_text(json.dumps(spec))
    (d / "status.json").write_text(json.dumps(dict(state="queued", step="waiting", progress=0.0, updated=time.time())))
    return d


@app.get("/api/shapes")
def list_shapes():
    return {k: dict(kind=v["kind"], label=v["label"], params={p: dict(label=a[0], default=a[1], min=a[2], max=a[3])
                                                               for p, a in v["params"].items()})
            for k, v in shapes.PARAMS.items()}


@app.post("/api/designs/shape")
def create_shape_design(body: dict):
    shape, dims = body.get("shape"), body.get("dims") or {}
    if shape not in shapes.PARAMS:
        raise HTTPException(400, f"shape must be one of {', '.join(shapes.PARAMS)}")
    if not isinstance(dims, dict) or any(isinstance(v, bool) for v in dims.values()):
        raise HTTPException(400, "dimensions must be numbers (metres)")
    try:
        dims = {k: float(dims.get(k, shapes.PARAMS[shape]["params"][k][1])) for k in shapes.PARAMS[shape]["params"]}
    except (TypeError, ValueError):
        raise HTTPException(400, "dimensions must be numbers (metres)")
    errs = shapes.check(shape, dims)
    if errs:
        raise HTTPException(400, "; ".join(errs))
    spec = dict(body.get("spec") or {}) if isinstance(body.get("spec") or {}, dict) else None
    if spec is None:
        raise HTTPException(400, "spec must be a JSON object")
    for k in ("units", "forward", "up"):                  # meaningless for a shape (it is built in metres, nose +x)
        spec.pop(k, None)
    decided = [k for k in ("kind", "layout", "cog", "inertia") if spec.get(k) not in (None, "")]
    if decided:
        raise HTTPException(400, f"{', '.join(decided)} come from the shape; for your own values, upload a model file")
    need = ("power_w", "battery_wh") if shapes.PARAMS[shape]["kind"] == "uuv" else ("mass", "power_w", "battery_wh")
    spec = clean_spec(spec, need)
    did = f"{_slug(spec.get('name', shape))}-{uuid.uuid4().hex[:6]}"
    try:
        d = _make_shape_design(DESIGNS / did, shape, dims, spec)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _design_summary(d)


def _design_dir(did):
    if not ID_OK.match(did) or did in (".", ".."):
        raise HTTPException(404, "no such design")
    d = DESIGNS / did
    if not (d / "spec.json").exists():
        raise HTTPException(404, "no such design")
    return d


@app.get("/api/designs/{did}")
def get_design(did: str):
    d = _design_dir(did)
    log = (d / "log.txt").read_text().splitlines()[-40:] if (d / "log.txt").exists() else []
    res = _read(d / "result.json", {})
    return _design_summary(d) | dict(spec=_read(d / "spec.json"), result=res, log=log)


@app.delete("/api/designs/{did}")
def delete_design(did: str):
    d = _design_dir(did)
    if (_read(d / "status.json") or {}).get("state") == "running":
        raise HTTPException(409, "this design is being characterized right now; wait for it to finish")
    shutil.rmtree(d)
    return {"deleted": did}


@app.post("/api/designs/{did}/rerun")
def rerun_design(did: str):
    d = _design_dir(did)
    (d / "status.json").write_text(json.dumps(dict(state="queued", step="waiting", progress=0.0, updated=time.time())))
    return _design_summary(d)


@app.get("/api/designs/{did}/mesh")
def design_mesh(did: str, case: str = ""):
    """Display mesh (FLU metres) plus FEA von Mises per vertex for one load case (default: the worst)."""
    d = _design_dir(did)
    res = _read(d / "result.json", {}) or {}
    cases = (res.get("fea") or {}).get("cases") or []
    if not case and cases:
        case = min(cases, key=lambda c: c.get("safety_factor") or 1e9).get("key", "")
    if case and not ID_OK.match(case):
        raise HTTPException(400, "bad case")
    f = d / f"fea_{case}.npz"
    if f.exists():
        z = np.load(f)
        return dict(vertices=np.round(z["nodes"], 5).ravel().tolist(), faces=z["faces"].ravel().tolist(),
                    vm=np.round(z["vm"] / 1e6, 3).tolist())
    m = trimesh.load(d / "mesh.stl", force="mesh")
    return dict(vertices=np.round(m.vertices, 5).ravel().tolist(), faces=m.faces.ravel().tolist(), vm=None)


# ------------------------------------------------------------------ environment

@app.get("/api/env/coverage")
def coverage():
    cat = envm.catalog()
    if not cat:
        return dict(hours=0)
    lat, lon, *_ = envm.grid()
    hours = sorted(cat)
    # contiguous spans, so the UI can show gaps honestly
    spans, start = [], hours[0]
    for a, b in zip(hours, hours[1:] + [None]):
        if b is None or (b - a) > dt.timedelta(hours=1):
            spans.append([start.isoformat(), a.isoformat()]); start = b
    return dict(hours=len(hours), first=hours[0].isoformat(), last=hours[-1].isoformat(), spans=spans,
                lat=[float(lat.min()), float(lat.max())], lon=[float(lon.min()), float(lon.max())],
                source=f"WRF output, {len(set(p for p, _ in cat.values()))} file(s)")


@app.get("/api/env/field")
def env_field(t: str, lat0: float, lat1: float, lon0: float, lon1: float, n: int = 14):
    """A coarse grid of wind (10 m) and surface current for drawing barbs/arrows on the chart."""
    if not (2 <= n <= 60) or not all(map(math.isfinite, (lat0, lat1, lon0, lon1))):
        raise HTTPException(400, "n must be 2..60 and the box finite")
    t0 = dt.datetime.fromisoformat(t)
    try:
        E = envm.Env(t0, 0, (lat0, lat1), (lon0, lon1), pad_deg=0.1)
    except ValueError as e:
        raise HTTPException(400, str(e))
    la = np.linspace(lat0, lat1, n); lo = np.linspace(lon0, lon1, n)
    LA, LO = np.meshgrid(la, lo, indexing="ij")
    s = E.at(LA.ravel(), LO.ravel(), np.zeros(LA.size), np.full(LA.size, 10.0))
    hs, tp = envm.sea_state(s)
    return dict(sources=E.sources, data_time=E.data_time.isoformat(), frozen=E.frozen,
                lat=LA.ravel().round(4).tolist(), lon=LO.ravel().round(4).tolist(),
                wind=np.round(s["wind10_ne"], 2).tolist(), current=np.round(s["current_ne"], 3).tolist(),
                hs=np.round(hs, 2).tolist(), land=s["land"].tolist())


# ------------------------------------------------------------------ reachability

@app.get("/api/reach")
def reach_map(design: str, lat: float, lon: float, t: str, hours: float = 24, z: float = 0, round_trip: bool = False):
    """Where this design can get to from (lat, lon) within `hours`, in the weather at time t."""
    from cafe import hangar, reach as rmod
    d = _design_dir(design)
    if (_read(d / "status.json") or {}).get("state") != "done":
        raise HTTPException(400, "design isn't characterized yet")
    if not (0 < hours <= 240) or not all(map(math.isfinite, (lat, lon, z))):
        raise HTTPException(400, "hours must be in (0, 240] and the point finite")
    veh = hangar.load_vehicle(d)
    rated = veh.limits.get("rated_depth_m")
    if veh.kind == "uuv" and rated and abs(z) > rated:
        raise HTTPException(400, f"{abs(z):.0f} m is below this design's rated depth ({rated:.0f} m)")
    zu = {"uuv": -abs(z), "usv": 0.0, "uav": abs(z) or 30.0}[veh.kind]
    span = 3.8
    try:
        E = envm.Env(dt.datetime.fromisoformat(t), 1, (lat - span, lat + span), (lon - span, lon + span), pad_deg=0.2)
        out = rmod.reach(veh, E, lat, lon, hours, zu, round_trip=round_trip)
        nan2none = lambda g: [[None if (x is None or x != x) else x for x in row] for row in g]
        if not E.has_current and veh.kind != "uav":
            pess = rmod.reach(veh, E, lat, lon, hours, zu, round_trip=round_trip, adverse=0.25)
            out["pessimistic_hours"] = nan2none(pess["hours"])
            out["note"] = ("these weather files have no ocean currents. Solid: reachable in slack water. "
                           "Hatched: still reachable with 0.25 m/s of current against you.")
    except ValueError as e:
        raise HTTPException(400, str(e))
    out["sources"] = E.sources
    out["hours"] = nan2none(out["hours"])
    if E.frozen:
        out["warning"] = (f"the weather files hold one snapshot ({E.data_time:%Y-%m-%d %H:%M} UTC); it is held fixed "
                          f"for all {hours:g} h, so treat long-range answers as rough")
    return out


# ------------------------------------------------------------------ missions

ID_OK = re.compile(r"^[A-Za-z0-9_-][A-Za-z0-9._-]{0,63}$")      # no leading dot: never ".", "..", or hidden files


def _point(v, what):
    """[lat, lon] or [lat, lon, z]: finite numbers, lat in [-90, 90]."""
    if not (isinstance(v, list) and 2 <= len(v) <= 3 and all(isinstance(x, (int, float)) and not isinstance(x, bool)
                                                              and math.isfinite(x) for x in v) and -90 <= v[0] <= 90):
        raise HTTPException(400, f"{what} must be [lat, lon] or [lat, lon, z] with finite numbers")


def check_fleet(body):
    """Shared by missions and emulations: every reference must resolve, and every follow chain must
    end at a drone that is actually going somewhere (no self-follow, no A->B->A loops)."""
    drones = body.get("drones") or []
    if not drones or not isinstance(drones, list) or not all(isinstance(x, dict) for x in drones):
        raise HTTPException(400, "add at least one drone")
    ids = [x.get("id") for x in drones]
    if any(not isinstance(i, str) or not ID_OK.match(i) for i in ids) or len(set(ids)) != len(ids):
        raise HTTPException(400, "drone names must be unique and use only letters, digits, . _ -")
    follows = {}
    for x in drones:
        if not isinstance(x.get("design"), str) or not ID_OK.match(x["design"]) or x["design"] in (".", ".."):
            raise HTTPException(400, f"{x['id']}: bad design id")
        st = (_read(DESIGNS / x["design"] / "status.json") or {}).get("state")
        if st != "done":
            raise HTTPException(400, f"{x['id']}: design isn't characterized yet ({st or 'missing'})")
        _point(x.get("start"), f"{x['id']}: start")
        legs = x.get("legs")
        if not isinstance(legs, list) or not legs:
            raise HTTPException(400, f"{x['id']}: needs at least one leg")
        for l in legs:
            if not isinstance(l, dict) or l.get("type") not in ("goto", "hold", "follow"):
                raise HTTPException(400, f"{x['id']}: each leg is goto, hold or follow")
            if l["type"] in ("hold", "follow") and not (isinstance(l.get("minutes"), (int, float)) and 0 < l["minutes"] <= 24 * 60):
                raise HTTPException(400, f"{x['id']}: {l['type']} needs minutes between 0 and 1440")
            if l["type"] == "goto" and l.get("to") != "start":
                _point(l.get("to"), f"{x['id']}: goto point")
            if l["type"] == "follow":
                if l.get("target") not in ids:
                    raise HTTPException(400, f"{x['id']} follows '{l.get('target')}', which isn't in this mission")
                if l["target"] == x["id"]:
                    raise HTTPException(400, f"{x['id']} can't follow itself")
                follows.setdefault(x["id"], set()).add(l["target"])
    leaders = {x["id"] for x in drones if any(l["type"] != "follow" for l in x["legs"])}
    for start in follows:                       # every chain must reach a drone with a real task
        seen, frontier = set(), {start}
        while frontier:
            seen |= frontier
            frontier = set().union(*(follows.get(f, set()) for f in frontier)) - seen
        if not (seen - {start}) & leaders and start not in leaders:
            raise HTTPException(400, f"{start} only follows drones that only follow each other; someone has to lead")
    for lk in body.get("links") or []:
        if not isinstance(lk, dict) or lk.get("a") not in ids or lk.get("b") not in ids or lk["a"] == lk["b"]:
            raise HTTPException(400, "each link joins two different drones of this mission")
        try:
            mx, need = float(lk.get("max_m")), float(lk.get("need", 0.95))
        except (TypeError, ValueError):
            raise HTTPException(400, f"link {lk['a']}-{lk['b']}: max_m must be a number")
        if not (math.isfinite(mx) and mx > 0) or not (0 < need <= 1):
            raise HTTPException(400, f"link {lk['a']}-{lk['b']}: max_m > 0 and need in (0, 1]")
        if lk.get("mode", "horizontal") not in ("horizontal", "3d"):
            raise HTTPException(400, "link mode is horizontal or 3d")
    mh, ns = body.get("max_hours", 6), body.get("samples", 24)
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (mh, ns)) or not (0 < mh <= 48) or not (1 <= ns <= 64):
        raise HTTPException(400, "max_hours must be in (0, 48] and samples in [1, 64]")
    return drones


@app.post("/api/missions")
def create_mission(body: dict):
    drones = check_fleet(body)
    mid = uuid.uuid4().hex[:8]
    d = MISSIONS / mid
    d.mkdir(parents=True)
    (d / "mission.json").write_text(json.dumps(body))
    (d / "status.json").write_text(json.dumps(dict(state="queued", progress=0.0, updated=time.time())))
    return dict(id=mid)


@app.get("/api/missions")
def list_missions():
    out = []
    for d in sorted(MISSIONS.glob("*"), key=lambda p: -p.stat().st_mtime)[:30]:
        m = _read(d / "mission.json", {})
        st = _read(d / "status.json", {})
        out.append(dict(id=d.name, name=m.get("name"), t0=m.get("t0"), state=st.get("state"),
                        drones=[x.get("id") for x in m.get("drones", [])]))
    return out


@app.get("/api/missions/{mid}")
def get_mission(mid: str):
    if not ID_OK.match(mid):
        raise HTTPException(404, "no such mission")
    d = MISSIONS / mid
    if not d.exists():
        raise HTTPException(404, "no such mission")
    return dict(id=mid, mission=_read(d / "mission.json"), status=_read(d / "status.json"),
                result=_read(d / "result.json"))


# ------------------------------------------------------------------ emulator (ArduPilot SITL in the loop)

EMU = WORK / "emulations"


@app.post("/api/emulations")
def create_emulation(body: dict):
    """Fly a planned mission with the real autopilot firmware. Body: a mission (same shape as
    /api/missions) or {"mission": "<id>"} to re-fly one already simulated."""
    if body.get("mission"):
        if not isinstance(body["mission"], str) or not ID_OK.match(body["mission"]):
            raise HTTPException(404, "no such mission")
        src = _read(MISSIONS / body["mission"] / "mission.json")
        if not src:
            raise HTTPException(404, "no such mission")
        body = src
    check_fleet(body)
    busy = [d for d in EMU.glob("*") if (_read(d / "status.json") or {}).get("state") in ("running", "queued")]
    if busy:
        raise HTTPException(409, "an emulation is already running (they share UDP/TCP ports); wait for it")
    eid = uuid.uuid4().hex[:8]
    d = EMU / eid
    d.mkdir(parents=True)
    (d / "emulation.json").write_text(json.dumps(body))
    (d / "status.json").write_text(json.dumps(dict(state="queued", step="waiting", progress=0.0, updated=time.time())))
    return dict(id=eid)


@app.get("/api/emulations/{eid}")
def get_emulation(eid: str):
    if not ID_OK.match(eid):
        raise HTTPException(404, "no such emulation")
    d = EMU / eid
    if not d.exists():
        raise HTTPException(404, "no such emulation")
    log = (d / "log.txt").read_text().splitlines()[-30:] if (d / "log.txt").exists() else []
    return dict(id=eid, mission=_read(d / "emulation.json"), status=_read(d / "status.json"), result=_read(d / "result.json"), log=log)


# ------------------------------------------------------------------ live sessions: your code drives the drones

@app.post("/api/live")
def live_create(body: dict):
    from cafe import hangar, live
    drones = body.get("drones") or []
    if not drones:
        raise HTTPException(400, "add at least one drone")
    for x in drones:
        if not ID_OK.match(str(x.get("id", ""))) or not ID_OK.match(str(x.get("design", ""))):
            raise HTTPException(400, "each drone needs an id and a design id")
        if (_read(DESIGNS / x["design"] / "status.json") or {}).get("state") != "done":
            raise HTTPException(400, f"{x['id']}: design isn't characterized yet")
        if not (isinstance(x.get("start"), list) and len(x["start"]) >= 2 and all(isinstance(v, (int, float)) and math.isfinite(v) for v in x["start"])):
            raise HTTPException(400, f"{x['id']}: start must be [lat, lon, z]")
    check_fleet(dict(body, drones=[dict(x, legs=[{"type": "hold", "minutes": 1}]) for x in drones]))
    try:
        sid, st = live.create(body, lambda did: hangar.load_vehicle(DESIGNS / did))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return dict(id=sid, state=st)


@app.post("/api/live/{sid}/step")
def live_step(sid: str, body: dict):
    from cafe import live
    try:
        return live.step(sid, float(body.get("seconds", 10)), body.get("targets") or {})
    except KeyError:
        raise HTTPException(404, "no such live session (sessions end after an hour idle or an API restart)")
    except (ValueError, TypeError) as e:
        raise HTTPException(400, str(e))


@app.get("/api/live/{sid}")
def live_get(sid: str):
    from cafe import live
    try:
        return live.state(live.get(sid)["world"])
    except KeyError:
        raise HTTPException(404, "no such live session")


@app.delete("/api/live/{sid}")
def live_end(sid: str):
    from cafe import live
    live.end(sid)
    return {"ended": sid}


# ------------------------------------------------------------------ receipts & static

@app.get("/api/receipts")
def receipts():
    return _read(WORK / "runs" / "receipts.json", [])


@app.get("/")
def index():
    from fastapi.responses import HTMLResponse
    v = str(int(max((STATIC / f).stat().st_mtime for f in ("app.js", "style.css"))))
    return HTMLResponse((STATIC / "index.html").read_text().replace("__V__", v), headers={"Cache-Control": "no-cache"})


app.mount("/static", StaticFiles(directory=STATIC), name="static")
