"""Round 23, batch D (M-8, M-9 per OD-4).

M-8: a fleet body whose `drones`, `links`, `t0` or `samples` has the wrong shape is a 400 from `live_create`, `check_fleet` (so `create_mission` and
`create_emulation`) and `live.create`, never the AttributeError, TypeError or KeyError of reading inside it; `samples` is a whole number.
M-9 (D-4 only): `budget.plan` refuses a NaN, infinite, negative or non-number leaf of the throughput table that it multiplies by, with a PlanError that names
the leaf. The stage-1 costs may be 0 (`make bench` writes 0 for a slope it did not resolve), a rate and a sortie length may not.
Each test fails on the tree at f62defd and passes with the fix."""
import math
import types

import pytest

from cafe import live
from cafe.pm import budget
from cafe.pm.budget import PlanError

NAN, INF = float("nan"), float("inf")


def app():
    from cafe import app as a
    return a


def refused(fn, *args, **kw):
    """The HTTPException a handler raises for a body it refuses (status 400); any other exception is the failure."""
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:
        fn(*args, **kw)
    assert e.value.status_code == 400
    return e.value.detail


@pytest.fixture
def fleet(tmp_path, monkeypatch):
    """A valid fleet body (two drones, one finished design) and the app with its designs there; `live.create` is a stub that records what it was given."""
    a = app()
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "status.json").write_text('{"state": "done"}')
    monkeypatch.setattr(a, "DESIGNS", tmp_path)
    got = []
    monkeypatch.setattr(live, "create", lambda body, load: (got.append(body), ("sid", {}))[1])
    drone = lambda i: dict(id=i, design="d", start=[1.0, 2.0, 3.0], legs=[dict(type="hold", minutes=5)])      # noqa: E731
    good = dict(t0="2023-03-07T17:00:00", drones=[drone("a"), drone("b")])
    return a, good, got


# ---------------------------------------------------------------------------------------------------------- M-8: the shapes of a fleet body
BAD_DRONES = ["abc", "", 5, 0, True, {"a": 1}, {}, [], [1], ["a"], [[]], [None], None]
BAD_LINKS = [5, 0, True, False, "abc", "", {"a": 1}, {}]
BAD_T0 = [5, 0, True, None, ["2023-03-07T17:00:00"], {"a": 1}]
BAD_SAMPLES = [2.5, 24.0, 1.0, True, False, "24", None, [24], 0, -1, 65, 64.5, NAN, INF, 10 ** 400]
HANDLERS = ["check_fleet", "create_mission", "create_emulation", "live_create"]


@pytest.mark.parametrize("handler", HANDLERS)
@pytest.mark.parametrize("bad", BAD_DRONES, ids=repr)
def test_m8_drones_that_are_not_a_list_of_objects_is_a_400(fleet, handler, bad):
    """Before: `{"drones": "abc"}` and `[1]` were an AttributeError in `live_create` (`x.get`), `5` a TypeError (not iterable)."""
    a, good, _ = fleet
    refused(getattr(a, handler), dict(good, drones=bad))


@pytest.mark.parametrize("handler", HANDLERS)
@pytest.mark.parametrize("bad", BAD_LINKS, ids=repr)
def test_m8_links_that_is_not_a_list_is_a_400(fleet, handler, bad):
    """Before: `5` and `true` were a TypeError (not iterable), `{"a": 1}` iterated its keys into the per-link check, and `false`, `0` and `""` were no links."""
    a, good, _ = fleet
    assert refused(getattr(a, handler), dict(good, links=bad)) == "links must be a list"


@pytest.mark.parametrize("handler", HANDLERS)
@pytest.mark.parametrize("bad", [[5], ["a"], [[]], [None], [{"a": "a", "b": "b"}, 7]], ids=repr)
def test_m8_a_link_that_is_no_object_is_still_a_400(fleet, handler, bad):
    a, good, _ = fleet
    refused(getattr(a, handler), dict(good, links=bad))


@pytest.mark.parametrize("handler", HANDLERS)
@pytest.mark.parametrize("bad", BAD_T0, ids=repr)
def test_m8_a_t0_that_is_not_a_string_is_a_400(fleet, handler, bad):
    """Before: a missing `t0` was a KeyError in `live.create`, a number a TypeError; both a 500 (the global handler takes ValueError only)."""
    a, good, _ = fleet
    assert refused(getattr(a, handler), dict(good, t0=bad)) == "t0 must be a date-time string"


def test_m8_a_missing_t0_is_a_400_for_a_live_session_and_not_for_a_fleet_check(fleet):
    """A live session reads `t0` at once; a mission body is checked for its fleet and its `t0` is read by the worker (the bodies the suite sends have none)."""
    a, good, _ = fleet
    body = {k: v for k, v in good.items() if k != "t0"}
    assert refused(a.live_create, body) == "t0 must be a date-time string"
    assert a.check_fleet(body) == body["drones"]


@pytest.mark.parametrize("handler", ["check_fleet", "create_mission", "create_emulation", "live_create"])
@pytest.mark.parametrize("bad", BAD_SAMPLES, ids=repr)
def test_m8_samples_that_is_not_a_whole_number_in_1_to_64_is_a_400(fleet, handler, bad):
    """Before: `2.5`, `24.0` and `64.5` passed `1 <= ns <= 64`; the worker then failed on them after the job was queued."""
    a, good, _ = fleet
    assert "samples a whole number in [1, 64]" in refused(getattr(a, handler), dict(good, samples=bad))


@pytest.mark.parametrize("ok", [1, 2, 24, 63, 64])
def test_m8_samples_that_were_accepted_still_are_and_the_edges_are_where_they_were(fleet, ok):
    a, good, _ = fleet
    assert a.check_fleet(dict(good, samples=ok)) == good["drones"]
    assert a.live_create(dict(good, samples=ok)) == dict(id="sid", state={})


@pytest.mark.parametrize("bad", [0, -1, 48.0001, NAN, INF, True, "6", None], ids=repr)
def test_m8_max_hours_is_where_it_was(fleet, bad):
    a, good, _ = fleet
    refused(a.check_fleet, dict(good, max_hours=bad))
    for ok in (1e-9, 6, 48, 48.0):
        assert a.check_fleet(dict(good, max_hours=ok))


def test_m8_a_valid_body_is_not_refused_by_any_handler_and_live_create_hands_it_on_whole(fleet):
    a, good, got = fleet
    body = dict(good, links=[dict(a="a", b="b", max_m=100.0)], samples=8, max_hours=6)
    assert a.check_fleet(body) == body["drones"]
    assert a.live_create(body) == dict(id="sid", state={}) and got == [body]
    for links in ([], None):                                           # no links: an empty list, or the key absent / null as before
        assert a.check_fleet(dict(good, links=links)) and a.live_create(dict(good, links=links)) == dict(id="sid", state={})
    assert a.check_fleet(good) and a.live_create(good)


def test_m8_a_bad_body_reaches_nothing_behind_the_guard(fleet):
    """`live_create` read `x.get` of every drone before any type test: the guard comes first, so no design file is read and `live.create` is not called."""
    a, good, got = fleet
    refused(a.live_create, dict(good, drones=[1]))
    refused(a.live_create, dict(good, links=5))
    assert got == []


# ---------------------------------------------------------------------------------------------------------- M-8: live.create itself
@pytest.fixture
def world(monkeypatch):
    """`live.create` with the environment and the world stubbed: it returns once the shape is accepted."""
    from cafe import env as envm
    monkeypatch.setattr(live, "SESSIONS", {})
    monkeypatch.setattr(envm, "hours_after", lambda t0: 100.0)
    monkeypatch.setattr(live, "World", lambda mission, B: types.SimpleNamespace(mission=mission))
    monkeypatch.setattr(live, "state", lambda w: "state")
    return lambda body: live.create(body, lambda did: did)


GOOD_LIVE = dict(t0="2023-03-07T17:00:00", drones=[dict(id="a", design="d", start=[1.0, 2.0, 3.0])])


@pytest.mark.parametrize("bad", ["abc", 5, {"a": 1}, [1], ["a"], None, [dict(id="a", design="d", start=[1, 2]), 7]], ids=repr)
def test_m8_live_create_of_the_module_refuses_drones_that_are_no_list_of_objects_with_a_valueerror(world, bad):
    """Before: `len(5)` was a TypeError and `x["id"]` of a str a TypeError, neither a ValueError."""
    with pytest.raises(ValueError, match="drones must be a list of objects"):
        world(dict(GOOD_LIVE, drones=bad))


@pytest.mark.parametrize("bad", [5, True, "abc", {"a": 1}, [5], ["a"], [[]]], ids=repr)
def test_m8_live_create_of_the_module_refuses_links_that_are_no_list_of_objects(world, bad):
    with pytest.raises(ValueError, match="links a list of objects"):
        world(dict(GOOD_LIVE, links=bad))


@pytest.mark.parametrize("bad", [5, None, ["x"], {"a": 1}, True], ids=repr)
def test_m8_live_create_of_the_module_refuses_a_missing_or_wrong_t0(world, bad):
    with pytest.raises(ValueError, match="t0 a date-time string"):
        world(dict(GOOD_LIVE, t0=bad))
    with pytest.raises(ValueError, match="t0 a date-time string"):
        world({k: v for k, v in GOOD_LIVE.items() if k != "t0"})


def test_m8_live_create_of_the_module_takes_what_it_took(world):
    for links in (None, [], [dict(a="a", b="b", max_m=1.0)]):
        sid, st = world(dict(GOOD_LIVE, links=links) if links is not None else GOOD_LIVE)
        assert st == "state" and live.SESSIONS[sid]["world"].mission["links"] == (links or [])
    with pytest.raises(ValueError, match="takes 1 to"):
        world(dict(GOOD_LIVE, drones=[]))
    with pytest.raises(ValueError, match="takes 1 to"):
        world(dict(GOOD_LIVE, drones=[dict(id=str(i), design="d", start=[0, 0]) for i in range(live.MAX_DRONES + 1)]))


# ---------------------------------------------------------------------------------------------------------- M-9: the throughput table
MISSION = dict(window=dict(start="2023-03-01T12:00:00Z", end="2023-03-07T12:00:00Z"))          # 6 days
CLASSES = dict(glider_eq="glider", usv="usv", uas="uas")
COSTS = ("s_per_batch_day", "s_per_member_day")


def table(cls="glider", key="s_per_batch_day", value=1.0, **extra):
    """A throughput table with the stage-1 costs of three classes at (1.0 s per batch day, 0.05 s per member day), `cls`.`key` set to `value`."""
    t = {"stage1": {c: dict(s_per_batch_day=1.0, s_per_member_day=0.05, measured="2026-10-29", host="h", load_1min=0.5) for c in CLASSES.values()}}
    t["stage1"][cls][key] = value
    t.update(extra)
    return t


def plan(t, gpus=0):
    return budget.plan("quick", gpus, MISSION, thr=t, vehicle_classes=CLASSES, workers=1, mem_gb=64)


NOT_COSTS = [NAN, INF, -INF, -1, -1e-300, True, False, "5", None, [1.0], 10 ** 400, -(10 ** 400)]
NOT_RATES = NOT_COSTS + [0, 0.0, -0.0]


@pytest.mark.parametrize("key", COSTS)
@pytest.mark.parametrize("cls", ["glider", "usv", "uas"])
@pytest.mark.parametrize("bad", NOT_COSTS, ids=repr)
def test_m9_a_stage_1_cost_that_is_not_a_finite_number_of_at_least_0_is_a_plan_error_naming_it(cls, key, bad):
    """Before: a NaN was a plan of half the members and a NaN `stage1_s` (glider) or a bare ValueError (usv, uas); 0, -1 and -inf were a cheaper plan."""
    with pytest.raises(PlanError) as e:
        plan(table(cls, key, bad))
    assert f"stage1.{cls}.{key} is {bad!r}" in str(e.value) and "finite number of at least 0" in str(e.value) and "make bench" in str(e.value)


@pytest.mark.parametrize("key", COSTS)
@pytest.mark.parametrize("cls", ["glider", "usv", "uas"])
@pytest.mark.parametrize("ok", [0, 0.0, 1e-300, 1, 3.5], ids=repr)
def test_m9_a_stage_1_cost_of_0_or_more_is_still_a_plan(cls, key, ok):
    """0 is what `make bench` writes for a slope it did not resolve (`slope_resolved: false`) and for no environment call time: not an error."""
    p = plan(table(cls, key, ok))
    assert p["member_cost"][dict(glider="glider_eq").get(cls, cls)][key] == ok and math.isfinite(p["stage1_s"])


def test_m9_the_leaves_the_plan_uses_are_the_leaves_it_checks_and_a_class_that_is_not_run_is_not_read():
    """The table is read where the plan multiplies by it, so a bad leaf of a class the mission does not fly is not in the way."""
    p = budget.plan("quick", 0, MISSION, thr=table("uas", "s_per_batch_day", NAN), vehicle_classes=dict(g="glider"), workers=1, mem_gb=64)
    assert list(p["member_cost"]) == ["g"]


@pytest.mark.parametrize("bad", NOT_RATES, ids=repr)
def test_m9_a_rate_that_is_not_a_finite_number_above_0_is_a_plan_error_naming_it_cpu_and_gpu(bad):
    for gpus, key in ((0, "jax-lbm-d3q19-cpu"), (1, "jax-lbm-d3q19-gpu")):
        t = table(**{key: dict(per_device=bad, measured="d", device="x")})
        with pytest.raises(PlanError) as e:
            plan(t, gpus)
        assert f"{key}.per_device is {bad!r}" in str(e.value) and "finite number above 0" in str(e.value)
        with pytest.raises(PlanError):
            budget.lbm_rate(t, gpus)


@pytest.mark.parametrize("ok", [1e-300, 1, 7.5e6, 1e300, 3], ids=repr)
def test_m9_a_rate_above_0_is_still_a_plan(ok):
    for gpus, key in ((0, "jax-lbm-d3q19-cpu"), (1, "jax-lbm-d3q19-gpu")):
        t = table(**{key: dict(per_device=ok, measured="d", device="x")})
        assert budget.lbm_rate(t, gpus)[0] == ok * max(gpus, 1) and plan(t, gpus)["les"]["rate"] == ok * max(gpus, 1)


def test_m9_a_rate_the_other_backend_is_not_asked_for_is_not_read():
    """A GPU plan does not read the CPU rate and a CPU plan does not read the GPU rate."""
    bad, ok = dict(per_device=NAN, measured="d", device="x"), dict(per_device=1e6, measured="d", device="x")
    assert plan(table(**{"jax-lbm-d3q19-cpu": bad, "jax-lbm-d3q19-gpu": ok}), 1)["les"]["backend"] == "native-jax-gpu"
    assert plan(table(**{"jax-lbm-d3q19-gpu": bad, "jax-lbm-d3q19-cpu": ok}), 0)["les"]["backend"] == "native-jax-cpu"


@pytest.mark.parametrize("name", ["sortie_min", "mission_days"])
@pytest.mark.parametrize("bad", [v for v in NOT_RATES if v is not None], ids=repr)         # None is an absent figure, not a bad one
def test_m9_the_benchmarks_sortie_minutes_and_days_are_finite_and_above_0_or_absent(name, bad):
    """Before: a NaN `sortie_min` gave a NaN factor that no test compared (`abs(nan - 1) > 1e-9` is False): the UAS cost was silently not scaled."""
    e = dict(sortie_min=120.0, mission_days=6.0)
    e[name] = bad
    with pytest.raises(PlanError) as e2:
        budget.bench_sortie_rate(e)
    assert f"a stage1 entry's {name} is {bad!r}" in str(e2.value)
    assert budget.bench_sortie_rate(dict(sortie_min=120.0, mission_days=1e-300)) == 120.0 / 1e-300
    assert budget.bench_sortie_rate(dict(sortie_min=1e-300, mission_days=6.0)) == 1e-300 / 6.0
    assert budget.bench_sortie_rate({}) is None and budget.bench_sortie_rate(dict(mission_days=6.0)) is None


def test_m9_a_bad_sortie_minutes_reaches_the_plan_of_a_mission_with_sorties():
    from cafe.pm import config, stage1
    m = config.load_mission(config.ROOT / "missions" / "tepex_c_demo.yaml")
    t = dict(budget.throughput(), stage1={k: dict(v) for k, v in budget.throughput()["stage1"].items()})
    t["stage1"]["uas"]["sortie_min"] = NAN
    with pytest.raises(PlanError, match="sortie_min is nan"):
        budget.plan("quick", 0, m, thr=t, vehicle_classes=stage1._classes(m), workers=6)


def test_m9_the_shipped_table_is_a_plan():
    """The tracked config/throughput.json passes every check above."""
    from cafe.pm import config, stage1
    m = config.load_mission(config.ROOT / "missions" / "tepex_c_demo.yaml")
    for gpus in (0, 1):
        assert budget.plan("quick", gpus, m, vehicle_classes=stage1._classes(m), workers=6)["n_max"] > 0
