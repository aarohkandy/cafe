"""Round 22, batch D (M-6, M-7, M-9).

M-6: `vehicle.build` and `vehicle.hull_lift` refuse a force, moment or viscous vector of a direction that is not three finite numbers with a ValueError that
names the direction and the field (a null item is the NaN `hangar` writes as null; it was an unnamed TypeError, and a bare NaN built a silent NaN drag).
`app.js` shows a missing stored number as a dash wherever it multiplies it before `fmt` (a null times 100 is 0): the lint test below holds that for every
`fmt(` and `Math.round(` call of the file; the formatters themselves were run in Node (the hand-back has the output: no browser, no JS runner in the suite).
M-7: a plane with no coarse force at its last angle has no grid index, so `hull_lift` gives inf (never the 0.0 of a converged grid), and `drag_sigma` gives an
estimate's spread.
M-9: the live step answers 400 for a number it cannot use (a bool, text, NaN, inf, an integer too large for a float) in a target's lat, lon, z or speed and in
`seconds`, by `jsonio.finite_real` like `_point`; `check_fleet` refuses `minutes: true`.
Each test fails on the tree at 7a1aaa9 and passes with the fix."""
import ast
import itertools
import json
import math
import pathlib
import re
import subprocess
import sys
import threading
import time
import types
from collections import Counter

import numpy as np
import pytest

from cafe import cfd, geom, live, mission, vehicle

NAN, INF = float("nan"), float("inf")
ROOT = pathlib.Path(__file__).parent.parent
REAL = pathlib.Path(__file__).parent / "fixtures" / "cfd_real"
H, EST = mission.SIG["drag_cfd"], mission.SIG["drag_est"]
FIELDS = ("force", "moment", "viscous")


def sample(name):
    s = geom.SAMPLES[name]
    return s["kind"], s["make"](), s["spec"]


def quad_external():
    return json.loads((REAL / "quad.external.json").read_text())


# ---------------------------------------------------------------------------------------------------------- M-6: a vector that is not three finite numbers
BAD_ITEMS = [None, NAN, INF, -INF, 10 ** 400, -(10 ** 400), "x"]
BAD_IDS = ["null", "nan", "inf", "-inf", "10**400", "-10**400", "text"]


@pytest.mark.parametrize("key", FIELDS)
@pytest.mark.parametrize("at", [0, 1, 2])
@pytest.mark.parametrize("bad", BAD_ITEMS, ids=BAD_IDS)
def test_m6_one_bad_item_of_a_vector_is_refused_naming_the_direction_and_the_field(key, at, bad):
    v = [1.0, 2.0, 3.0]
    v[at] = bad
    with pytest.raises(ValueError) as e:
        vehicle._vec3({key: v}, key, "-z")
    assert "direction -z" in str(e.value) and f"`{key}`" in str(e.value)


@pytest.mark.parametrize("bad", [None, [], [1.0, 2.0], [1.0, 2.0, 3.0, 4.0], 1.0, [[1.0, 2.0, 3.0]], "abc", {}, [None, None, None]],
                         ids=["none", "empty", "two", "four", "scalar", "2d", "text", "dict", "all null"])
def test_m6_a_vector_of_another_shape_is_refused_too(bad):
    with pytest.raises(ValueError, match=r"direction \+x: `force` is not three finite numbers"):
        vehicle._vec3({"force": bad}, "force", "+x")


@pytest.mark.parametrize("good", [[1, 2, 3], (1.0, -2.5, 0.0), np.array([1.0, 2.0, 3.0], np.float32), np.array([1, 2, 3]), [1e308, -1e308, 0]],
                         ids=["ints", "tuple", "float32", "int array", "huge but finite"])
def test_m6_a_vector_of_three_finite_numbers_of_any_kind_is_returned_as_floats(good):
    a = vehicle._vec3({"moment": good}, "moment", "+x")
    assert a.dtype == float and a.shape == (3,) and np.array_equal(a, np.asarray(good, float))


@pytest.mark.parametrize("d", list(cfd.DIRS))
@pytest.mark.parametrize("key", FIELDS)
def test_m6_build_refuses_a_null_or_nan_item_of_any_direction_and_field_by_name(d, key):
    """Before: a null in `force`, `moment` or `viscous` was `TypeError: unsupported operand type(s) for *: 'float' and 'NoneType'`, and a NaN built a silent
    NaN drag table."""
    kind, mesh, spec = sample("quad")
    for bad in (None, NAN):
        res = quad_external()
        res["dirs"][d][key][1] = bad
        with pytest.raises(ValueError) as e:
            vehicle.build(kind, mesh, spec, {"cfd": res})
        assert f"direction {d}" in str(e.value) and f"`{key}`" in str(e.value)


def test_m6_build_of_the_real_results_is_unchanged():
    """Every real force, moment and viscous vector of the repo's results is three finite numbers: nothing is refused that was built before."""
    for file in ("quad.external.json", "torpedo.external.json"):
        res = json.loads((REAL / file).read_text())
        for d, r in res["dirs"].items():
            for key in FIELDS:
                assert np.array_equal(vehicle._vec3(r, key, d), np.asarray(r[key], float))
    kind, mesh, spec = sample("quad")
    v = vehicle.build(kind, mesh, spec, {"cfd": quad_external()})
    assert v.sources["drag"] == "cfd" and len(v.drag) == 6 and all(np.isfinite(c[0]).all() and np.isfinite(c[1]).all() for c in v.drag.values())


def incidence(alphas=(5.0, 10.0), planes=("+y", "+z"), drop=(), how="force_coarse"):
    """The shape `cfd.characterize_incidence` returns, with arbitrary numbers; `drop` lists the directions whose coarse force is missing (`how` says how)."""
    rng = np.random.default_rng(0)
    labels = ["+x", *planes, *(f"x{p}{a:g}" for p in planes for a in alphas)]
    dirs = {lab: dict(force=list(rng.normal(size=3)), moment=list(rng.normal(size=3)), force_coarse=list(rng.normal(size=3)),
                      moment_coarse=list(rng.normal(size=3))) for lab in labels}
    for lab in drop:
        if how == "null":
            dirs[lab]["force_coarse"][1] = None
        else:
            del dirs[lab][how]
    return dict(rho=1025.0, speed=1.5, L=1.0, alphas=list(alphas), planes=list(planes), dirs=dirs)


@pytest.mark.parametrize("lab, key", [("x+y5", "force"), ("+x", "moment"), ("+z", "force"), ("x+z10", "moment")])
def test_m6_hull_lift_refuses_a_null_fine_force_or_moment_by_name(lab, key):
    inc = incidence()
    inc["dirs"][lab][key][2] = None
    with pytest.raises(ValueError) as e:
        vehicle.hull_lift(inc, np.zeros(3), np.zeros((3, 3)))
    assert f"direction {lab}" in str(e.value) and f"`{key}`" in str(e.value)


# ---------------------------------------------------------------------------------------------------------- M-7: no coarse force is no index
def test_m7_a_plane_with_no_coarse_force_at_its_last_angle_gives_inf_whichever_directions_are_missing(monkeypatch):
    """For 1 to 3 angles, every non-empty subset of the directions of the study, three ways of having no coarse force (the key `force_coarse`, the key
    `moment_coarse`, a null item): the index is inf exactly when a direction that the last angle of a plane reads is in the subset, and the worst finite
    index otherwise (0.2 here). Before: 0.2 for every one of them (a plane without a coarse force was skipped, and the default of `worst_gci` is 0.0)."""
    monkeypatch.setattr(cfd, "gci", lambda *a, **k: 0.2)
    planes = ("+y", "+z")
    n_inf = n_fin = 0
    for n in (1, 2, 3):
        alphas = (5.0, 10.0, 15.0)[:n]
        labels = ["+x", *planes, *(f"x{p}{a:g}" for p in planes for a in alphas)]
        read = {"+x", *planes, *(f"x{p}{alphas[-1]:g}" for p in planes)}
        for how in ("force_coarse", "moment_coarse", "null"):
            for size in range(len(labels) + 1):
                for drop in itertools.combinations(labels, size):
                    _, g = vehicle.hull_lift(incidence(alphas, planes, drop, how), np.zeros(3), np.zeros((3, 3)))
                    if set(drop) & read:
                        assert g == INF, (n, how, drop)
                        n_inf += 1
                    else:
                        assert g == 0.2, (n, how, drop)
                        n_fin += 1
    assert n_inf > 1000 and n_fin > 20


def test_m7_one_plane_alone_and_no_plane_at_all(monkeypatch):
    monkeypatch.setattr(cfd, "gci", lambda *a, **k: 0.2)
    for p in ("+y", "+z"):
        assert vehicle.hull_lift(incidence(planes=(p,)), np.zeros(3), np.zeros((3, 3)))[1] == 0.2
        assert vehicle.hull_lift(incidence(planes=(p,), drop=(f"x{p}10",)), np.zeros(3), np.zeros((3, 3)))[1] == INF
    out, g = vehicle.hull_lift(incidence(planes=()), np.zeros(3), np.zeros((3, 3)))
    assert out == {} and g == 0.0                                    # 0.0 means no plane at all: `build` stores no `lift_gci` for it


def test_m7_the_vehicles_lift_index_and_drag_spread_follow(monkeypatch):
    """End to end on the real quad result: a complete incidence study with an index of 0.2 gives `hypot(0.10, 0.2)`; one whose last angle has no coarse force
    in a plane has no index, so the spread is an estimate's (0.30), not the 0.10 of a converged grid."""
    monkeypatch.setattr(cfd, "gci", lambda *a, **k: 0.2)
    kind, mesh, spec = sample("quad")
    ext = quad_external()
    inc = dict(incidence(), rho=ext["rho"], speed=ext["speed"])
    v = vehicle.build(kind, mesh, spec, {"cfd": ext, "cfd_aoa": inc})
    assert v.limits["lift_gci"] == 0.2 and mission.drag_sigma(v) == pytest.approx(math.hypot(H, 0.2)) and math.hypot(H, 0.2) < EST
    del inc["dirs"]["x+z10"]["force_coarse"]
    v = vehicle.build(kind, mesh, spec, {"cfd": ext, "cfd_aoa": inc})
    assert v.limits["lift_gci"] == INF and mission.drag_sigma(v) == EST
    for old in (0.0, 0.05):                                            # what the missing index was taken for: a converged grid, a good one
        assert math.hypot(H, old) < EST


def test_m7_the_lift_index_is_read_by_the_spread_and_written_by_no_file():
    """`v.limits` is a vehicle's, read by `mission.drag_sigma`: `hangar` writes its own `hangar["limits"]` dict (rated depth, crush depth, glide band) and never
    a `lift_gci`, so an inf of it cannot become a bare `Infinity` in a result file. A module that names `lift_gci` is one of these two."""
    named = sorted(p.name for p in (ROOT / "cafe").glob("*.py") if "lift_gci" in p.read_text())
    assert named == ["mission.py", "vehicle.py"]


# ---------------------------------------------------------------------------------------------------------- M-9: the live step and check_fleet
class World:
    """Just enough of a `World` for `live.step` with a UAV: the target check, the leg it sets and the ticks."""

    def __init__(self):
        self.ticks = 0
        self.frame = types.SimpleNamespace(to_ne=lambda lat, lon: (lat, lon))
        self.drone = types.SimpleNamespace(veh=types.SimpleNamespace(kind="uav"), ap=types.SimpleNamespace(v_max=np.array([5.0])),
                                           st=types.SimpleNamespace(p=np.zeros((1, 3))), legs=[{}])
        self.by_id = {"a": self.drone}

    def tick(self):
        self.ticks += 1


@pytest.fixture
def session(monkeypatch):
    w = World()
    monkeypatch.setitem(live.SESSIONS, "sid", dict(world=w, used=time.time(), lock=threading.Lock()))
    monkeypatch.setattr(live, "state", lambda world: "state")
    return w


def app():
    from cafe import app as a
    return a


def refused(fn, *args, **kw):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:
        fn(*args, **kw)
    assert e.value.status_code == 400
    return e.value.detail


NOT_NUMBERS = [10 ** 400, -(10 ** 400), True, False, "1.5", NAN, INF, -INF, [1.0], {}]
NOT_NUMBER_IDS = ["10**400", "-10**400", "true", "false", "text", "nan", "inf", "-inf", "list", "dict"]
GOOD = dict(lat=10, lon=-95.5, z=3, speed=1)


@pytest.mark.parametrize("field", ["lat", "lon", "z", "speed"])
@pytest.mark.parametrize("bad", NOT_NUMBERS, ids=NOT_NUMBER_IDS)
def test_m9_the_live_step_refuses_a_target_number_it_cannot_use_with_a_400_and_changes_nothing(session, field, bad):
    """Before: 10**400 was an OverflowError (a 500), `true` was 1.0, and "1.5" was 1.5."""
    detail = refused(app().live_step, "sid", dict(seconds=1, targets={"a": dict(GOOD, **{field: bad})}))
    assert "target needs numeric lat, lon" in detail
    assert session.ticks == 0 and session.drone.legs == [{}]


@pytest.mark.parametrize("field", ["lat", "lon", "z"])
def test_m9_a_missing_or_null_lat_lon_or_z_is_the_same_400(session, field):
    body = dict(GOOD, **{field: None})
    assert "target needs numeric lat, lon" in refused(app().live_step, "sid", dict(seconds=1, targets={"a": body}))
    del body[field]
    if field != "z":                                                    # z is optional (0)
        assert "target needs numeric lat, lon" in refused(app().live_step, "sid", dict(seconds=1, targets={"a": body}))
    else:
        assert app().live_step("sid", dict(seconds=1, targets={"a": body})) == "state"


@pytest.mark.parametrize("bad", NOT_NUMBERS + [None], ids=NOT_NUMBER_IDS + ["null"])
def test_m9_the_seconds_of_a_step_are_a_number_in_the_same_sense(session, bad):
    assert "seconds must be a number" in refused(app().live_step, "sid", dict(seconds=bad, targets={"a": GOOD}))
    assert session.ticks == 0


@pytest.mark.parametrize("bad", ["nope", 7, None, [1], "10"], ids=["text", "int", "none", "list", "text number"])
def test_m9_a_target_that_is_no_object_is_the_same_400(session, bad):
    assert "target needs numeric lat, lon" in refused(app().live_step, "sid", dict(seconds=1, targets={"a": bad}))


def test_m9_numbers_that_were_accepted_still_are(session):
    """Ints, floats, a missing z and speed, the poles, and an `int` for `seconds`; the targets are set as floats."""
    a = app()
    assert a.live_step("sid", dict(seconds=2, targets={"a": GOOD})) == "state"
    assert session.ticks == int(round(2 / mission.TICK)) and session.drone.legs[0]["_speed"] == 1.0 and isinstance(session.drone.legs[0]["_speed"], float)
    session.ticks = 0
    for lat in (90, -90, 90.0, 0, -0.0):
        assert a.live_step("sid", dict(seconds=1.5, targets={"a": dict(lat=lat, lon=0)})) == "state"
    assert session.drone.legs[0]["_speed"] is None
    assert a.live_step("sid", dict(seconds=1)) == "state" and a.live_step("sid", dict(targets={"a": GOOD})) == "state"      # no targets; the default 10 s


@pytest.mark.parametrize("lat", [90.0000001, -90.0000001, 91, 1e300], ids=str)
def test_m9_a_latitude_beyond_the_poles_is_still_not_a_real_position(session, lat):
    assert "not a real position" in refused(app().live_step, "sid", dict(seconds=1, targets={"a": dict(lat=lat, lon=0)}))


@pytest.mark.parametrize("speed, ok", [(5.0, True), (np.nextafter(5.0, 6.0), False), (0, False), (-1, False), (1e-9, True)], ids=str)
def test_m9_the_speed_bound_is_where_it_was(session, speed, ok):
    body = dict(seconds=1, targets={"a": dict(lat=1, lon=1, speed=speed)})
    if ok:
        assert app().live_step("sid", body) == "state"
    else:
        assert "speed must be above 0 and at most" in refused(app().live_step, "sid", body)


@pytest.fixture
def fleet(tmp_path, monkeypatch):
    a = app()
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "status.json").write_text('{"state": "done"}')
    monkeypatch.setattr(a, "DESIGNS", tmp_path)
    drone = lambda i, **leg: dict(id=i, design="d", start=[1.0, 2.0, 3.0], legs=[dict(type="hold", minutes=5, **leg)])      # noqa: E731
    return a, lambda minutes, kind="hold": dict(drones=[dict(drone("a"), legs=[dict(type=kind, minutes=minutes, target="b")]), drone("b")])


@pytest.mark.parametrize("kind", ["hold", "follow"])
@pytest.mark.parametrize("bad", [True, False, NAN, INF, -INF, 0, -1, 1441, 1440.0001, 10 ** 400, "5", None, [5]],
                         ids=["true", "false", "nan", "inf", "-inf", "0", "-1", "1441", "1440.0001", "10**400", "text", "null", "list"])
def test_m9_check_fleet_refuses_minutes_that_is_no_number_in_the_range(fleet, kind, bad):
    """Before: `minutes: true` was one minute (`isinstance(True, int)`, `0 < True <= 1440`)."""
    a, make = fleet
    assert "needs minutes between 0 and 1440" in refused(a.check_fleet, make(bad, kind))


@pytest.mark.parametrize("kind", ["hold", "follow"])
@pytest.mark.parametrize("ok", [1, 0.5, 1440, 1440.0, 1e-9, np.nextafter(0.0, 1.0)], ids=str)
def test_m9_check_fleet_still_takes_the_minutes_it_took(fleet, kind, ok):
    a, make = fleet
    assert a.check_fleet(make(ok, kind))


# ---------------------------------------------------------------------------------------------------------- M-9: every number the request handlers read
FLOAT_CALLS = {
    ("cafe/app.py", "clean_spec"): (["float(v)"], "a spec field: bool and non-number types refused first, OverflowError caught, finite test after"),
    ("cafe/app.py", "create_shape_design"): (["float(dims.get(k, shapes.PARAMS[shape]['params'][k][1]))"],
                                            "a bool refused first, OverflowError caught, `shapes.check` bounds it"),
    ("cafe/app.py", "coverage"): (["float(lat.min())", "float(lat.max())", "float(lon.min())", "float(lon.max())"], "the weather catalogue, not a request"),
    ("cafe/app.py", "live_step"): (["float(seconds)"], "after `finite_real(seconds)`"),
    ("cafe/live.py", "create"): (["float(hours)"], "after the bool, type and range test of `hours`"),
    ("cafe/live.py", "step"): (["float(lat)", "float(lon)", "float(z)", "float(speed)", "float(np.max(d.ap.v_max))", "float(np.max(d.ap.v_max))"],
                               "the four after `finite_real`; the drone's own top speed twice"),
    ("cafe/live.py", "state"): (["float(np.linalg.norm(e[:2] if lk.horizontal else e))", "float(lat[0])", "float(lon[0])", "float(eul[2] % 360)",
                                "float(np.hypot(v[0], v[1]))", "float(-v[2])", "float(1 - d.st.energy_wh[0] / d.veh.battery_wh)", "float(-d.st.p[0, 2])",
                                "float(d.st.p[0, 2])", "float(x)"], "the simulator's own state, not a request"),
}


def float_calls():
    found = {}
    for rel in ("cafe/app.py", "cafe/live.py"):
        for fn in ast.walk(ast.parse((ROOT / rel).read_text())):
            if isinstance(fn, ast.FunctionDef):
                calls = [ast.unparse(n) for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "float"]
                if calls:
                    found[(rel, fn.name)] = calls
    return found


def test_every_float_of_the_request_handlers_is_one_that_is_listed_with_what_checks_it():
    """An enumeration test: a new `float(` in `cafe/app.py` or `cafe/live.py` fails until it is listed with its reason (round 22, M-9: the class is the number
    that a request carries and a handler converts)."""
    found = float_calls()
    assert {k: Counter(v) for k, v in found.items()} == {k: Counter(c) for k, (c, _) in FLOAT_CALLS.items()}, found
    assert all(why for _, why in FLOAT_CALLS.values())


def test_the_live_modules_import_without_yaml_or_jsonschema():
    """`cafe/live.py` takes `finite_real` from `cafe.pm.jsonio`, never from `cafe.pm.config` (the live app image has no pyyaml, which `config` imports)."""
    code = ("import sys; sys.modules['yaml'] = None; sys.modules['jsonschema'] = None; "
            "import cafe.live, cafe.app; assert 'cafe.pm.config' not in sys.modules")
    r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-800:]
    tree = ast.parse((ROOT / "cafe/live.py").read_text())
    assert any(isinstance(n, ast.ImportFrom) and n.module == "cafe.pm.jsonio" for n in ast.walk(tree))
    assert not any(isinstance(n, ast.ImportFrom) and n.module in ("cafe.pm.config", "cafe.pm") for n in ast.walk(tree))


# ---------------------------------------------------------------------------------------------------------- M-6: app.js
APP_JS = (ROOT / "cafe/static/app.js").read_text()


def first_args(call):
    """The first argument of every `call(` in app.js (up to the top-level comma or the closing bracket)."""
    out = []
    for m in re.finditer(rf"\b{re.escape(call)}\(", APP_JS):
        i = j = m.end()
        depth = 0
        while True:
            c = APP_JS[j]
            if c in "([{":
                depth += 1
            elif c in ")]}":
                if depth == 0:
                    break
                depth -= 1
            elif c == "," and depth == 0:
                break
            j += 1
        out.append(APP_JS[i:j])
    return out


ARITHMETIC = re.compile(r"[*/]|^\s*[-+]|Math\.")
UNGUARDED_FMT = {      # arithmetic in the first argument of `fmt(` that does not carry `?? NaN`, and why it cannot be a stored null read as 0
    "(Math.atan2(-we, -wn) * 180 / Math.PI + 360) % 360": "the wind of /api/env/field, a live response whose encoder refuses NaN (not a stored result)",
    "Math.hypot(cn, ce)": "the current of /api/env/field, as above",
    "lk.never_acquired * 100": "only reached when `lk.never_acquired > 0`, which null and NaN are not",
    "gci * 100": "only reached when `gci == null` is false (`gciText`)",
    "+U": "the key of an object (a speed written as text), not a stored number",
}
ROUND = {      # every `Math.round(` of app.js: none of them reads a number of a stored result
    "kt / 5": "a wind-barb tick count from /api/env/field",
    "l.need * 100": "the editor's own input value",
    "(st.progress || 0) * 100": "a job's progress, defaulted to 0 by `|| 0`",
    "d.progress * 100": "a design summary's progress (the strict encoder refuses NaN), a bar width",
}


def test_every_number_app_js_multiplies_before_formatting_reads_a_missing_one_as_a_dash():
    """An enumeration test: a null of a stored result times 100 is 0 (JS coerces it), so `fmt(x * 100)` printed 0 for a number that was missing, while
    `fmt(x)` prints a dash for null, undefined and NaN. Every `fmt(` whose first argument is arithmetic carries `?? NaN` (a NaN times 100 is NaN, a dash), or is
    listed above with the reason it never sees a stored null; a new one fails until it is. The `Math.round(` calls likewise. The formatters themselves were
    run in Node, as the hand-back says; this is a text test, not a run in a browser."""
    unguarded = {a.strip() for a in first_args("fmt") if ARITHMETIC.search(a) and "?? NaN" not in a}
    assert unguarded == set(UNGUARDED_FMT), unguarded ^ set(UNGUARDED_FMT)
    assert {a.strip() for a in first_args("Math.round")} == set(ROUND)
    assert re.search(r"const fmt = \(x, d = 1\) => x == null \|\| Number\.isNaN\(x\) \? \"—\" : Number\(x\)\.toFixed\(d\);", APP_JS)
