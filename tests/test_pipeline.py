"""cafe/pm/pipeline.py: the checkpoint chain and resume, every stage function, and the whole pipeline on the CI fixture.

Stage 3 is the one stage that is replaced (`pipeline_windows.run` returns rows in the contract shape); ingest, hangar, stage 1, windows,
refit, stage 1b, the emulator and the report run for real on the synthetic CAFE_DATA tree of tests/fixtures/ci_env. CAFE_DATA is that tree
for the whole module (pipeline.DATA and env.ocean.DATA are patched), never the real /data.
"""
import datetime as dt
import hashlib
import json
import pathlib
import pickle                      # res.pkl is the pipeline's own checkpoint, written into this test's temporary run directory and read back from there
import shutil
import types

import numpy as np
import pytest
import yaml

from cafe.pm import audit, budget, config, ledger, pipeline, report, stage1
from cafe.pm.audit import STAGES
from cafe.pm.env import ocean as ocean_mod, orca, surface, tao
from cafe.pm.env.environment import GriddedEnv
from cafe.pm.env.protocol import AnalyticEnv
from cafe.pm.physics import glider, uas, usv
from tests.fixtures import pm_run
from tests.fixtures.fakes import fake_module

ROOT = config.ROOT
MISSION_PATH = ROOT / "missions" / "ci_fixture.yaml"
UTC = lambda s: config.utc(s).timestamp()
T0, T1 = UTC("2023-03-01T18:00:00Z"), UTC("2023-03-03T06:00:00Z")
CLASSES = {"glider_eq": "glider", "glider_1n": "glider", "usv": "usv", "uas": "uas"}


@pytest.fixture(scope="module")
def data(ci_env):
    """pipeline and env.ocean read the synthetic tree of ci_env for every test of this module."""
    mp = pytest.MonkeyPatch()
    mp.setattr(pipeline, "DATA", ci_env.data)
    mp.setattr(ocean_mod, "DATA", ci_env.data)
    mp.setenv("CAFE_DATA", str(ci_env.data))
    yield ci_env
    mp.undo()


pytestmark = pytest.mark.usefixtures("data")


@pytest.fixture
def data_copy(data, tmp_path, monkeypatch):
    """A private copy of the tree (10 MB) that a test may break."""
    d = tmp_path / "data"
    shutil.copytree(data.data, d)
    monkeypatch.setattr(pipeline, "DATA", d)
    monkeypatch.setattr(ocean_mod, "DATA", d)
    return d


def quiet(_):
    return None


def ctx_for(run_dir, budget_name="ci", mission=MISSION_PATH, gpus=0, log=quiet):
    return pipeline.Context(mission, budget_name, gpus, run_dir, log)


def run_stage(fn, ctx, name, *args):
    """Run one stage function inside its own ledger, as pipeline.run does; -> the ledger dict."""
    with ledger.Ledger(ctx.run_dir, name, ctx.hash) as L:
        fn(ctx, L, *args)
    return L.d


def read_ledger(run, name):
    return json.loads((pathlib.Path(run) / "checkpoints" / name / "ledger.json").read_text())


def check_of(d, name):
    return next(c for c in d["checks"] if c["name"] == name)


# ---------------------------------------------------------------------------------------------------------------- code digest

def code_tree(root):
    files = {"cafe/pm/pipeline.py": "p = 1\n", "cafe/pm/a.py": "a = 1\n", "cafe/pm/sub/b.py": "b = 2\n", "config/c.yaml": "k: 1\n", "config/d/e.json": "{}\n",
             "platforms/p.yaml": "v: 1\n", "platforms/notes.txt": "n", "cafe/other/z.py": "z = 1\n", "docs/readme.md": "r", "cafe/pm/__pycache__/a.py": "junk"}
    for rel, text in files.items():
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)


def test_code_digest_is_a_stable_sha256_of_the_real_tree():
    d = pipeline.code_digest()
    assert len(d) == 64 and int(d, 16) >= 0 and d == pipeline.code_digest()


def test_code_digest_changes_when_pipeline_code_config_or_a_platform_file_changes(tmp_path, monkeypatch):
    code_tree(tmp_path)
    monkeypatch.setattr(pipeline, "__file__", str(tmp_path / "cafe" / "pm" / "pipeline.py"))
    base = pipeline.code_digest()
    edits = (("cafe/pm/sub/b.py", "b = 3\n"), ("cafe/pm/a.py", "a = 1  \n"), ("config/c.yaml", "k: 2\n"), ("config/d/e.json", "{ }\n"),
             ("platforms/p.yaml", "v: 2\n"))
    for rel, new in edits:
        f = tmp_path / rel
        old = f.read_text()
        f.write_text(new)
        assert pipeline.code_digest() != base, rel
        f.write_text(old)
        assert pipeline.code_digest() == base, rel                                                           # and back


def test_code_digest_sees_added_and_renamed_files_but_not_files_outside_its_scope(tmp_path, monkeypatch):
    code_tree(tmp_path)
    monkeypatch.setattr(pipeline, "__file__", str(tmp_path / "cafe" / "pm" / "pipeline.py"))
    base = pipeline.code_digest()
    for rel in ("cafe/other/z.py", "docs/readme.md", "platforms/notes.txt", "cafe/pm/__pycache__/a.py", "cafe/pm/__pycache__/new.py", "platforms/sub/q.yaml"):
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("changed")
        assert pipeline.code_digest() == base, rel
    (tmp_path / "platforms" / "n.yaml").write_text("v: 1\n")
    added = pipeline.code_digest()
    assert added != base
    (tmp_path / "platforms" / "n.yaml").rename(tmp_path / "platforms" / "m.yaml")
    assert pipeline.code_digest() not in (base, added)                                                       # same bytes, other name


# ---------------------------------------------------------------------------------------------------------------- context

def test_context_plans_the_budget_for_the_vehicle_classes(tmp_path, data):
    ctx = ctx_for(tmp_path / "r")
    assert ctx.classes == CLASSES and ctx.mission["name"] == "ci_fixture" and ctx.run_dir == tmp_path / "r" and ctx.mission_path == MISSION_PATH
    assert ctx.plan["budget"] == "ci" and (ctx.plan["n_max"], ctx.plan["n_min"], ctx.plan["batch"]) == (16, 8, 16)
    assert set(ctx.plan["member_cost"]) == set(CLASSES)
    assert ctx.cache == data.cache and not (tmp_path / "r").exists()                                         # nothing is created until a stage writes


def test_context_hash_covers_mission_budget_gpus_and_code(tmp_path, monkeypatch):
    m = tmp_path / "m.yaml"
    m.write_text(MISSION_PATH.read_text())
    base = ctx_for(tmp_path / "a", mission=m).hash
    assert ctx_for(tmp_path / "b", mission=m).hash == base                                                   # the run directory is not part of it
    assert ctx_for(tmp_path / "a", "quick", mission=m).hash != base and ctx_for(tmp_path / "a", gpus=1, mission=m).hash != base
    m.write_text(m.read_text().replace("seed: 20230301", "seed: 7"))
    assert ctx_for(tmp_path / "a", mission=m).hash != base
    m.write_text(MISSION_PATH.read_text())
    monkeypatch.setattr(pipeline, "code_digest", lambda: "other code")
    assert ctx_for(tmp_path / "a", mission=m).hash != base


def test_context_path_creates_the_parents_and_nothing_else(tmp_path):
    ctx = ctx_for(tmp_path / "r")
    p = ctx.path("x", "y", "z.json")
    assert p == tmp_path / "r" / "x" / "y" / "z.json" and p.parent.is_dir() and not p.exists()


def test_context_env_is_built_once_from_the_cache_the_ocean_and_the_surface_layer(tmp_path, data):
    ctx = ctx_for(tmp_path / "r")
    env = ctx.env
    assert env is ctx.env and isinstance(env, GriddedEnv) and env.ocean is not None and env.subgrid is not None
    assert bool(env.inside(-165.0 % 360, 0.0)) and not bool(env.inside(-100.0 % 360, 0.0))


def test_ocean_is_opened_for_the_mission_box_plus_its_pad(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(ocean_mod, "open_ocean", lambda spec, cache, name, box: seen.append((spec, cache, name, box)) or "OCEAN")
    ctx = ctx_for(tmp_path / "r")
    assert pipeline.ocean(ctx) == "OCEAN"
    assert seen == [({"source": "gofs31"}, ctx.cache, "ci_fixture", (-2.0, 2.0, -167.0, -163.0))]          # (south, north, west, east), 0.5 degree pad


def test_dump_writes_numpy_and_datetimes_as_json(tmp_path):
    p = pipeline._dump({"a": np.arange(3), "t": dt.datetime(2023, 3, 1, 18), "x": 1.5}, tmp_path / "o.json")
    assert p == tmp_path / "o.json" and json.loads(p.read_text()) == {"a": [0, 1, 2], "t": "2023-03-01T18:00:00", "x": 1.5}


# ---------------------------------------------------------------------------------------------------------------- run: chain and resume

def stub_stages(monkeypatch, calls, fail=None, raise_in=None):
    """Nine stages that each write one file and record their call; `fail` makes one stage's self-check fail, `raise_in` makes one raise."""
    def make(name):
        def f(ctx, L):
            calls.append(name)
            if raise_in == name:
                raise RuntimeError("disk full")
            p = ctx.path(name, "out.txt")
            p.write_text(f"{name} call {len(calls)}\n")
            L.output(p)
            if fail == name:
                L.check("boom", False, value=1, limit=0)
        return f
    monkeypatch.setattr(pipeline, "FUNCS", {n: make(n) for n in STAGES})


def go(run, log=None, **kw):
    return pipeline.run(MISSION_PATH, kw.pop("budget_name", "ci"), kw.pop("gpus", 0), run, log=(log if log is not None else []).append, **kw)


def test_a_fresh_run_writes_the_plan_the_mission_and_one_chained_ledger_per_stage(tmp_path, monkeypatch):
    calls, log = [], []
    stub_stages(monkeypatch, calls)
    ctx = go(tmp_path / "run", log)
    run = tmp_path / "run"
    assert calls == STAGES and ctx.run_dir == run and (run / "mission.yaml").read_bytes() == MISSION_PATH.read_bytes()
    plan = json.loads((run / "plan.json").read_text())
    assert plan["budget"] == "ci" and plan["n_max"] == ctx.plan["n_max"] and log[0] == budget.describe(ctx.plan)
    assert [m.split(":")[0] for m in log if "done in" in m] == STAGES
    prev = None
    for st in STAGES:
        d = read_ledger(run, st)
        assert d["ok"] and d["stage"] == st and d["config_hash"] == ctx.hash and d["error"] is None
        refs = [i["ref"] for i in d["inputs"]]
        assert (str(prev) in refs) if prev else not refs
        assert [pathlib.Path(o["path"]).name for o in d["outputs"]] == ["out.txt"]
        prev = run / "checkpoints" / st / "ledger.json"
    assert audit.ledger_problems(run) == []


def test_resume_skips_every_clean_stage(tmp_path, monkeypatch):
    calls, log = [], []
    stub_stages(monkeypatch, calls)
    go(tmp_path / "run")
    calls.clear()
    before = {st: (tmp_path / "run" / "checkpoints" / st / "ledger.json").read_bytes() for st in STAGES}
    go(tmp_path / "run", log)
    assert calls == []
    assert [m for m in log if "up to date" in m] == [f"{st}: up to date (ledger {tmp_path / 'run' / 'checkpoints' / st / 'ledger.json'})" for st in STAGES]
    assert before == {st: (tmp_path / "run" / "checkpoints" / st / "ledger.json").read_bytes() for st in STAGES}


def test_fresh_reruns_everything(tmp_path, monkeypatch):
    calls = []
    stub_stages(monkeypatch, calls)
    go(tmp_path / "run")
    calls.clear()
    go(tmp_path / "run", resume=False)
    assert calls == STAGES
    assert audit.ledger_problems(tmp_path / "run") == []


def test_a_tampered_output_reruns_that_stage_and_not_the_ones_before_it(tmp_path, monkeypatch):
    calls = []
    stub_stages(monkeypatch, calls)
    go(tmp_path / "run")
    calls.clear()
    (tmp_path / "run" / "stage1" / "out.txt").write_text("tampered\n")
    go(tmp_path / "run")
    assert calls[0] == "stage1" and "ingest" not in calls and "hangar" not in calls
    assert (tmp_path / "run" / "stage1" / "out.txt").read_text().startswith("stage1 call")


def test_a_missing_output_reruns_its_stage(tmp_path, monkeypatch):
    calls = []
    stub_stages(monkeypatch, calls)
    go(tmp_path / "run")
    calls.clear()
    (tmp_path / "run" / "windows" / "out.txt").unlink()
    go(tmp_path / "run")
    assert calls[0] == "windows" and "stage1" not in calls


def test_stages_after_a_rerun_stage_run_again_so_the_chain_stays_valid(tmp_path, monkeypatch):
    """A stage that reruns writes a new ledger; the next stage recorded the old one as its input. Skipping it leaves a run that
    `make audit` rejects (`input ... changed since the stage ran`), and its products no longer follow from their inputs."""
    calls = []
    stub_stages(monkeypatch, calls)
    go(tmp_path / "run")
    calls.clear()
    (tmp_path / "run" / "hangar" / "out.txt").write_text("tampered\n")
    go(tmp_path / "run")
    assert calls == STAGES[1:]
    assert audit.ledger_problems(tmp_path / "run") == []


@pytest.mark.parametrize("what", ["code", "budget", "gpus", "mission"])
def test_a_change_of_code_budget_gpus_or_mission_reruns_every_stage(tmp_path, monkeypatch, what):
    calls = []
    stub_stages(monkeypatch, calls)
    m = tmp_path / "m.yaml"
    m.write_text(MISSION_PATH.read_text())

    def again(**kw):
        pipeline.run(m, kw.get("budget_name", "ci"), kw.get("gpus", 0), tmp_path / "run", log=quiet)
    again()
    calls.clear()
    again()
    assert calls == []
    if what == "code":
        monkeypatch.setattr(pipeline, "code_digest", lambda: "edited")
    elif what == "mission":
        m.write_text(m.read_text().replace("go: 0.9", "go: 0.95"))
    again(**({"budget_name": "quick"} if what == "budget" else {"gpus": 1} if what == "gpus" else {}))
    assert calls == STAGES


def test_a_failed_self_check_stops_the_run_and_the_stage_is_redone_on_resume(tmp_path, monkeypatch):
    calls, log = [], []
    stub_stages(monkeypatch, calls, fail="stage1")
    with pytest.raises(ledger.StageFailed, match="stage stage1: self-checks failed: \\['boom'\\]"):
        go(tmp_path / "run")
    assert calls == ["ingest", "hangar", "stage1"] and read_ledger(tmp_path / "run", "stage1")["ok"] is False
    assert not (tmp_path / "run" / "checkpoints" / "windows").exists()
    calls.clear()
    stub_stages(monkeypatch, calls)
    go(tmp_path / "run", log)
    assert calls == STAGES[2:] and [m.split(":")[0] for m in log if "up to date" in m] == ["ingest", "hangar"]
    assert audit.ledger_problems(tmp_path / "run") == []


def test_a_stage_that_raises_is_recorded_in_its_ledger(tmp_path, monkeypatch):
    calls = []
    stub_stages(monkeypatch, calls, raise_in="hangar")
    with pytest.raises(RuntimeError, match="disk full"):
        go(tmp_path / "run")
    d = read_ledger(tmp_path / "run", "hangar")
    assert d["ok"] is False and d["error"] == "RuntimeError: disk full" and calls == ["ingest", "hangar"]


def test_stop_after_ends_the_run_there_and_a_later_run_continues(tmp_path, monkeypatch):
    calls, log = [], []
    stub_stages(monkeypatch, calls)
    go(tmp_path / "run", stop_after="hangar")
    assert calls == ["ingest", "hangar"] and not (tmp_path / "run" / "checkpoints" / "stage1").exists()
    calls.clear()
    go(tmp_path / "run", log)
    assert calls == STAGES[2:] and [m.split(":")[0] for m in log if "up to date" in m] == ["ingest", "hangar"]
    calls.clear()
    go(tmp_path / "run", stop_after="ingest")
    assert calls == []


# ---------------------------------------------------------------------------------------------------------------- hangar

def assumed_leaves(node):
    if isinstance(node, dict):
        return int(node.get("assumed") is True) if "value" in node else sum(assumed_leaves(v) for v in node.values())
    return 0


def test_hangar_lists_every_platform_file_with_its_number_of_assumed_values(tmp_path):
    ctx = ctx_for(tmp_path / "r")
    d = run_stage(pipeline.s_hangar, ctx, "hangar")
    rows = json.loads((tmp_path / "r" / "hangar" / "hangar.json").read_text())
    assert set(rows) == set(CLASSES)
    for vid, platform in (("glider_eq", "seaglider"), ("glider_1n", "slocum"), ("usv", "saildrone_explorer"), ("uas", "quad_uas")):
        f = ROOT / "platforms" / f"{platform}.yaml"
        assert rows[vid] == dict(platform=platform, cls=CLASSES[vid], file=str(f), assumed=assumed_leaves(yaml.safe_load(f.read_text())))
        assert check_of(d, f"provenance_{platform}")["ok"] and any(i["ref"] == str(f) and len(i["sha256"]) == 64 for i in d["inputs"])
    assert rows["uas"]["assumed"] > 10 and [pathlib.Path(o["path"]).name for o in d["outputs"]] == ["hangar.json"]


def test_hangar_fails_on_a_platform_number_without_provenance(tmp_path, monkeypatch):
    plat = tmp_path / "platforms"
    shutil.copytree(ROOT / "platforms", plat)
    f = plat / "slocum.yaml"
    leaf = "antenna_height_m: {value: 0.3,      unit: m,        assumed: "
    f.write_text(f.read_text().replace(leaf + "true", leaf + "false"))
    assert "assumed: false" in f.read_text()
    for mod in (config, glider, usv):
        monkeypatch.setattr(mod, "PLATFORMS", plat)
    monkeypatch.setattr(uas, "PLATFORM", plat / "quad_uas.yaml")
    ctx = ctx_for(tmp_path / "r")
    with pytest.raises(ledger.StageFailed, match="provenance_slocum"):
        run_stage(pipeline.s_hangar, ctx, "hangar")
    d = read_ledger(tmp_path / "r", "hangar")
    bad = check_of(d, "provenance_slocum")
    assert not bad["ok"] and "antenna_height_m" in bad["note"] and "need a source" in bad["note"]
    assert all(check_of(d, f"provenance_{p}")["ok"] for p in ("seaglider", "saildrone_explorer", "quad_uas")) and d["ok"] is False
    assert json.loads((tmp_path / "r" / "hangar" / "hangar.json").read_text())["glider_1n"]["assumed"] == f.read_text().count("assumed: true")


# ---------------------------------------------------------------------------------------------------------------- ingest

def boom(*a, **k):
    raise AssertionError("the cache covers the window: nothing may be fetched")


def test_ingest_uses_a_cache_that_covers_the_window_then_validates_against_the_moorings(tmp_path, data, monkeypatch):
    monkeypatch.setattr(orca, "ingest", boom)
    monkeypatch.setattr(surface, "build", boom)
    log = []
    ctx = ctx_for(tmp_path / "r", log=log.append)
    d = run_stage(pipeline.s_ingest, ctx, "ingest")
    man = data.cache / "orca" / "manifest.json"
    assert log == [f"ingest: orca cache {man.parent} covers the window"]
    c = check_of(d, "orca_hours_cover_window")
    assert c["ok"] and c["value"] == 37 == c["limit"] and check_of(d, "ocean_source_covers_box")["note"] == "{'source': 'gofs31'}"
    first = d["inputs"][0]
    assert first["ref"].startswith("https://orca.") and first["sha256"] is None and first["kind"] == "remote"
    outs = {pathlib.Path(o["path"]).name: o["sha256"] for o in d["outputs"]}
    assert set(outs) == {"manifest.json", "tao_compare.json", "priors_fitted.json"} and outs["manifest.json"] == ledger.sha256(man)


def test_ingest_fetches_when_the_manifest_is_missing_or_does_not_cover_the_window(tmp_path, data_copy, monkeypatch):
    cache = data_copy / "cache" / "ci_fixture" / "orca"
    man = cache / "manifest.json"
    saved = man.read_text()
    calls = []

    def fake_ingest(t0, t1, box, out, hours3d=(), threads=8, spectra=True, log=print):
        calls.append(dict(t0=t0, t1=t1, box=box, out=out, hours3d=list(hours3d)))
        man.write_text(saved)
    monkeypatch.setattr(orca, "ingest", fake_ingest)
    for damage in (lambda: man.unlink(), lambda: man.write_text(saved.replace('"t1": "2023-03-03 06:00:00"', '"t1": "2023-03-03 05:00:00"')),
                   lambda: man.write_text(saved.replace('"t0": "2023-03-01 18:00:00"', '"t0": "2023-03-01 19:00:00"'))):
        calls.clear()
        man.write_text(saved)
        damage()
        run_stage(pipeline.s_ingest, ctx_for(tmp_path / "r"), "ingest")
        assert len(calls) == 1
        c = calls[0]
        assert c["t0"] == dt.datetime(2023, 3, 1, 18) and c["t1"] == dt.datetime(2023, 3, 3, 6) and c["t0"].tzinfo is None
        # (lon_min, lon_max, lat_min, lat_max) plus the 0.5 degree pad
        assert c["box"] == (-167.0, -163.0, -2.0, 2.0) and c["out"] == cache
        # each sortie hour and the next
        assert c["hours3d"] == [dt.datetime(2023, 3, 2, 1), dt.datetime(2023, 3, 2, 2), dt.datetime(2023, 3, 3, 1), dt.datetime(2023, 3, 3, 2)]


def test_ingest_builds_the_derived_surface_layer_when_it_is_missing(tmp_path, data_copy):
    """The first ingest of a mission has no derived.zarr: the stage has to build it from the gridded fields (surface.build takes an env without
    a surface layer) and hand every later stage an env that has one."""
    shutil.rmtree(data_copy / "cache" / "ci_fixture" / "derived.zarr")
    ctx = ctx_for(tmp_path / "r")
    run_stage(pipeline.s_ingest, ctx, "ingest")
    assert (ctx.cache / "derived.zarr").is_dir() and ctx.env.subgrid is not None


def test_ingest_fails_when_the_ocean_store_is_missing_or_the_cache_has_too_few_hours(tmp_path, data_copy):
    shutil.rmtree(data_copy / "ocean")
    with pytest.raises(ledger.StageFailed, match="ocean_source_covers_box"):
        run_stage(pipeline.s_ingest, ctx_for(tmp_path / "a"), "ingest")
    assert not check_of(read_ledger(tmp_path / "a", "ingest"), "ocean_source_covers_box")["ok"]
    man = data_copy / "cache" / "ci_fixture" / "orca" / "manifest.json"
    man.write_text(man.read_text().replace('"hours": 37', '"hours": 30'))
    with pytest.raises(ledger.StageFailed, match="orca_hours_cover_window"):
        run_stage(pipeline.s_ingest, ctx_for(tmp_path / "b"), "ingest")
    c = check_of(read_ledger(tmp_path / "b", "ingest"), "orca_hours_cover_window")
    assert (c["ok"], c["value"], c["limit"]) == (False, 30, 37)


@pytest.mark.parametrize("t0,t1,covers", [("2023-03-01 18:00:00", "2023-03-03 06:00:00", True), ("2023-03-01T18:00:00Z", "2023-03-03T06:00:00Z", True),
                                          ("2023-03-01 17:00:00", "2023-03-03 07:00:00", True), ("2023-03-01 18:00:01", "2023-03-03 06:00:00", False),
                                          ("2023-03-01 18:00:00", "2023-03-03 05:59:59", False)])
def test_a_cache_covers_the_window_when_it_spans_it(t0, t1, covers):
    assert pipeline._covers(dict(t0=t0, t1=t1), config.utc("2023-03-01T18:00:00Z"), config.utc("2023-03-03T06:00:00Z")) is covers


def test_sortie_hours_are_the_launch_hour_and_the_next_as_naive_utc():
    v = next(x for x in config.load_mission(MISSION_PATH)["vehicles"] if x["id"] == "uas")
    got = pipeline._sortie_hours(v, -165.0, config.utc("2023-03-01T18:00:00Z"), config.utc("2023-03-03T06:00:00Z"))
    assert got == [dt.datetime(2023, 3, 2, 1), dt.datetime(2023, 3, 2, 2), dt.datetime(2023, 3, 3, 1), dt.datetime(2023, 3, 3, 2)]
    late = dict(v, sorties=dict(v["sorties"], local_solar_time="14:50"))                                           # 01:50 UTC
    one_night = pipeline._sortie_hours(late, -165.0, config.utc("2023-03-01T18:00:00Z"), config.utc("2023-03-02T06:00:00Z"))
    assert one_night == [dt.datetime(2023, 3, 2, 1), dt.datetime(2023, 3, 2, 2)]
    plain = dict(v, sorties={"local_solar_time": "14:00"})
    # duration_min defaults to 20
    assert len(pipeline._sortie_hours(plain, -165.0, config.utc("2023-03-01T18:00:00Z"), config.utc("2023-03-03T06:00:00Z"))) == 4


# ---------------------------------------------------------------------------------------------------------------- TAO validation

def tao_ctx(tmp_path):
    ctx = ctx_for(tmp_path / "r", log=quiet)
    return ctx, ctx.env.tw.x[0], ctx.env.tw.x[-1]


def tao_stage(ctx, t0, t1):
    with ledger.Ledger(ctx.run_dir, "ingest", ctx.hash) as L:
        pipeline._tao(ctx, L, t0, t1)
    return L.d


def test_tao_writes_the_comparison_and_the_fitted_wind_priors(tmp_path, data):
    ctx, t0, t1 = tao_ctx(tmp_path)
    d = tao_stage(ctx, t0, t1)
    cmp = json.loads((ctx.run_dir / "ingest" / "tao_compare.json").read_text())
    fit = json.loads((ctx.run_dir / "ingest" / "priors_fitted.json").read_text())
    a = cmp["ALL"]
    # WRF reads high against the 3 % low moorings
    assert set(cmp) == {"T0N165W", "T2S165W", "ALL"} and a["n"] == 74 and a["speed_bias"] > 0
    s, w = fit["wind_speed_bias"], fit["wind_direction_bias"]
    assert s["mean"] == pytest.approx(-a["speed_bias"]) and s["value"] == pytest.approx(np.sqrt(a["speed_rmse"] ** 2 - a["speed_bias"] ** 2))
    assert s["unit"] == "m/s"
    assert w["mean"] == pytest.approx(-a["dir_bias_deg"]) and w["value"] == pytest.approx(np.sqrt(a["dir_rmse_deg"] ** 2 - a["dir_bias_deg"] ** 2))
    assert w["unit"] == "deg"
    assert s["dist"] == w["dist"] == "normal" and s["kind"] == w["kind"] == "data" and "2 moorings" in s["citation"]
    assert "2023-03-01T18:00:00Z..2023-03-03T06:00:00Z" in s["citation"]
    c = check_of(d, "tao_moorings_compared")
    assert c["ok"] and c["value"] == 2 and c["limit"] == 1 and d["notes"] == []
    assert any(i["ref"].endswith("tao/manifest.json") and i["sha256"] for i in d["inputs"])
    assert {pathlib.Path(o["path"]).name for o in d["outputs"]} == {"tao_compare.json", "priors_fitted.json"}


def test_the_fitted_wind_prior_removes_the_model_bias_and_stage1_accepts_it(tmp_path, data):
    ctx, t0, t1 = tao_ctx(tmp_path)
    tao_stage(ctx, t0, t1)
    a = json.loads((ctx.run_dir / "ingest" / "tao_compare.json").read_text())["ALL"]
    fit = json.loads((ctx.run_dir / "ingest" / "priors_fitted.json").read_text())
    assert a["speed_bias"] + fit["wind_speed_bias"]["mean"] == pytest.approx(0.0)                                      # model + prior mean = mooring
    pri, marg = stage1.priors_for(ctx.mission, fit)
    assert marg["wind_speed_bias"] == dict(dist="normal", mean=fit["wind_speed_bias"]["mean"], sd=fit["wind_speed_bias"]["value"])
    # the data are tighter than the 2 m/s prior
    assert marg["wind_direction_bias"]["mean"] == fit["wind_direction_bias"]["mean"] and marg["wind_speed_bias"]["sd"] < 2.0


def test_without_a_tao_download_the_default_priors_stand_and_the_ledger_says_so(tmp_path, data_copy):
    shutil.rmtree(data_copy / "tao")
    ctx = ctx_for(tmp_path / "r")
    d = tao_stage(ctx, ctx.env.tw.x[0], ctx.env.tw.x[-1])
    assert d["notes"] == [f"no TAO/TRITON download at {data_copy / 'tao'}: wind priors stay the perturbations.yaml defaults (run `make fetch`)"]
    assert d["checks"] == [] and d["outputs"] == [] and d["inputs"] == [] and not (ctx.run_dir / "ingest").exists()


def test_a_negative_variance_from_rounding_gives_a_zero_spread(tmp_path, data, monkeypatch):
    ctx, t0, t1 = tao_ctx(tmp_path)
    monkeypatch.setattr(tao, "compare", lambda wrf, moor: {"M": {}, "ALL": dict(speed_bias=0.5, speed_rmse=0.5 - 1e-12, dir_bias_deg=2.0, dir_rmse_deg=1.0)})
    tao_stage(ctx, t0, t1)
    fit = json.loads((ctx.run_dir / "ingest" / "priors_fitted.json").read_text())
    assert fit["wind_speed_bias"]["value"] == 0.0 and fit["wind_direction_bias"]["value"] == 0.0 and fit["wind_speed_bias"]["mean"] == -0.5


def test_moorings_outside_the_grid_fail_the_stage_through_its_self_check(tmp_path, data):
    """tao.compare returns {} when no mooring is inside the grid, so there is no `ALL` entry. The stage must then fail through its
    own `tao_moorings_compared` check (a clear StageFailed) and not die on the missing key."""
    ctx, t0, t1 = tao_ctx(tmp_path)
    ctx._env = types.SimpleNamespace(inside=lambda lon, lat: False)
    with pytest.raises(ledger.StageFailed, match="tao_moorings_compared"):
        tao_stage(ctx, t0, t1)
    c = check_of(read_ledger(ctx.run_dir, "ingest"), "tao_moorings_compared")
    assert (c["ok"], c["value"]) == (False, 0)


# ---------------------------------------------------------------------------------------------------------------- stage 1 wrapper

def fake_run(captured, n=8):
    def run(mission, env, plan, ledger_, log=print, scales=None, fitted=None):
        captured.update(mission=mission, env=env, plan=plan, ledger=ledger_, scales=scales, fitted=fitted)
        res = dict(U=np.zeros((n, 2)), vehicles={"v": dict(lon=np.zeros((2, n)), sim=object(), antenna_m=1.0), "w": dict(lon=np.zeros((2, n)))})
        return dict(res=res, summary={"vehicles": {}}, names=["a", "b"], n=n, certify=False, n_certify=73)
    return run


def test_stage1_wrapper_reads_the_fitted_priors_and_keeps_the_big_arrays_out_of_the_summary(tmp_path, monkeypatch):
    got = {}
    monkeypatch.setattr(stage1, "run", fake_run(got))
    ctx = ctx_for(tmp_path / "r")
    ctx._env = "ENV"
    ctx.path("ingest", "priors_fitted.json").write_text(json.dumps({"wind_speed_bias": {"mean": -0.3}}))
    d = run_stage(pipeline.s_stage1, ctx, "stage1")
    assert got["fitted"] == {"wind_speed_bias": {"mean": -0.3}} and got["scales"] is None and got["env"] == "ENV" and got["plan"] is ctx.plan
    assert got["mission"] is ctx.mission
    assert any(i["ref"].endswith("priors_fitted.json") and i["sha256"] for i in d["inputs"]) and d["seeds"] == {"mission": 20230301}
    assert d["notes"][0].startswith("8 members in ") and "certify possible: False (n_certify 73)" in d["notes"][0]
    summary = json.loads((ctx.run_dir / "stage1" / "summary.json").read_text())
    assert "res" not in summary and summary["n"] == 8 and summary["names"] == ["a", "b"]
    res = pickle.loads((ctx.run_dir / "stage1" / "res.pkl").read_bytes())
    assert "sim" not in res["vehicles"]["v"] and res["vehicles"]["v"]["antenna_m"] == 1.0
    assert [pathlib.Path(o["path"]).name for o in d["outputs"]] == ["res.pkl", "summary.json"]


def test_stage1_wrapper_without_fitted_priors_passes_none(tmp_path, monkeypatch):
    got = {}
    monkeypatch.setattr(stage1, "run", fake_run(got))
    ctx = ctx_for(tmp_path / "r")
    ctx._env = "ENV"
    d = run_stage(pipeline.s_stage1, ctx, "stage1")
    assert got["fitted"] is None and not any("priors_fitted" in i["ref"] for i in d["inputs"])


# ---------------------------------------------------------------------------------------------------------------- windows

def track_res(t, M, tracks, fail, cls):
    lon = np.stack([np.full(t.size, x[0]) for x in tracks], 1)
    lat = np.stack([np.full(t.size, x[1]) for x in tracks], 1)
    for m, k in fail.items():
        lon[k:, m] = np.nan
        lat[k:, m] = np.nan
    return {"class": cls, "t": t, "lon": lon, "lat": lat, "fail": {"mode": np.array([m in fail for m in range(M)])}}


def stress_of(env, cls, lon, lat, t):
    z = np.zeros_like(lon)
    if cls == "glider":
        return np.hypot(*np.moveaxis(np.asarray(env.current(lon, lat, z, t).value), -1, 0))
    if cls == "usv":
        return np.nan_to_num(env.waves(lon, lat, t)["Hs"].value)
    return np.hypot(*np.moveaxis(np.asarray(env.u10(lon, lat, t)), -1, 0))


def window_ctx(tmp_path, res, K=3):
    ctx = ctx_for(tmp_path / "r")
    ctx.plan["les"]["windows_per_vehicle"] = K
    with open(ctx.path("stage1", "res.pkl"), "wb") as f:
        pickle.dump(dict(vehicles=res), f)
    return ctx


def test_windows_pick_the_strongest_forcing_per_class_at_least_6_h_apart(tmp_path, data):
    t = T0 + 600.0 * np.arange(217)
    still = [(-165.0, 0.0)] * 4
    res = {"g": track_res(t, 4, still, {}, "glider"), "s": track_res(t, 4, still, {}, "usv"), "u": track_res(t, 4, still, {}, "uas")}
    ctx = window_ctx(tmp_path, res)
    d = run_stage(pipeline.s_windows, ctx, "windows")
    wins = json.loads((ctx.run_dir / "windows" / "windows.json").read_text())
    assert d["inputs"][0]["ref"].endswith("stage1/res.pkl") and d["inputs"][0]["sha256"] and check_of(d, "every_vehicle_has_a_window")["value"] == 9
    for vid, cls in (("g", "glider"), ("s", "usv"), ("u", "uas")):
        ws, env = wins[vid], ctx.env
        ref = stress_of(env, cls, np.full(t.size, -165.0), np.full(t.size, 0.0), t)
        assert len(ws) == 3 and all(w["basis"] == "all members" and w["lon"] == -165.0 and w["lat"] == 0.0 for w in ws)
        assert ws[0]["t"] == t[int(np.argmax(ref))] and ws[0]["stress"] == pytest.approx(ref.max())
        assert [w["stress"] for w in ws] == sorted((w["stress"] for w in ws), reverse=True)
        assert all(w["stress"] == pytest.approx(ref[int(round((w["t"] - T0) / 600.0))]) for w in ws)
        assert all(abs(a["t"] - b["t"]) >= 6 * 3600 for i, a in enumerate(ws) for b in ws[:i])
        # greedy: anything stronger is within 6 h of an earlier pick
        for j, w in enumerate(ws):
            stronger = t[ref > w["stress"] + 1e-12]
            assert all(any(abs(x - e["t"]) < 6 * 3600 for e in ws[:j]) for x in stronger)
    stresses = {v: wins[v][0]["stress"] for v in wins}
    # a current, a wave height and a wind speed are different numbers
    assert len({round(x, 6) for x in stresses.values()}) == 3


def test_windows_of_a_vehicle_that_failed_come_from_the_members_that_failed(tmp_path, data):
    t = T0 + 600.0 * np.arange(217)
    tracks = [(-165.0, 0.0), (-165.0, 0.0), (-164.0, 1.0), (-164.0, 1.0)]
    ok = track_res(t, 4, tracks, {}, "uas")
    failed = track_res(t, 4, tracks, {2: 120, 3: 120}, "uas")                                                       # members 2 and 3 stop reporting after 20 h
    ctx = window_ctx(tmp_path, {"clean": ok, "failed": failed})
    run_stage(pipeline.s_windows, ctx, "windows")
    wins = json.loads((ctx.run_dir / "windows" / "windows.json").read_text())
    assert {w["basis"] for w in wins["clean"]} == {"all members"} and {w["basis"] for w in wins["failed"]} == {"failed members"}
    assert all(w["t"] < t[120] for w in wins["failed"]) and all(w["lon"] == -164.0 and w["lat"] == 1.0 for w in wins["failed"])
    ref = stress_of(ctx.env, "uas", np.full(121, -164.0), np.full(121, 1.0), t[:121])
    assert wins["failed"][0]["stress"] == pytest.approx(ref.max()) and wins["failed"][0]["t"] == t[int(np.argmax(ref))]
    # all members: the median over every member's position
    assert wins["clean"][0]["lon"] == -164.5 and wins["clean"][0]["lat"] == 0.5


def test_fewer_records_than_windows_gives_fewer_windows(tmp_path, data):
    t = T0 + 600.0 * np.arange(10)                                                                                   # 90 minutes: one 6 h window fits
    ctx = window_ctx(tmp_path, {"u": track_res(t, 2, [(-165.0, 0.0)] * 2, {}, "uas")}, K=3)
    run_stage(pipeline.s_windows, ctx, "windows")
    assert len(json.loads((ctx.run_dir / "windows" / "windows.json").read_text())["u"]) == 1


def test_a_vehicle_with_no_finite_position_fails_the_window_check(tmp_path, data):
    t = T0 + 600.0 * np.arange(20)
    res = {"u": track_res(t, 2, [(-165.0, 0.0)] * 2, {}, "uas"), "lost": track_res(t, 2, [(-165.0, 0.0)] * 2, {0: 0, 1: 0}, "uas")}
    ctx = window_ctx(tmp_path, res)
    with pytest.raises(ledger.StageFailed, match="every_vehicle_has_a_window"):
        run_stage(pipeline.s_windows, ctx, "windows")
    wins = json.loads((ctx.run_dir / "windows" / "windows.json").read_text())
    assert wins["lost"] == [] and len(wins["u"]) == 1


# ---------------------------------------------------------------------------------------------------------------- stage 3, refit, stage 1b

def stage3_row(ok=True, cd=1.3, hangar=1.0, spread=0.05, checks=None):
    return dict(ok=ok, cd=cd, cd_spread=spread, cd_hangar=hangar, cl=None, checks=checks or [pm_run.check_row("mach_max", 0.05, 0.1, ok)])


def test_stage3_hands_the_windows_to_the_adapter_and_stores_its_rows(tmp_path, monkeypatch):
    ctx = ctx_for(tmp_path / "r")
    wins = {"usv": [dict(t=1.0, stress=2.0, lon=-165.0, lat=0.0, basis="all members")]}
    ctx.path("windows", "windows.json").write_text(json.dumps(wins))
    seen = []

    def run(c, w, L):
        seen.append((c, w, L))
        return {"usv": [stage3_row()]}
    fake_module(monkeypatch, "cafe.pm.stage3.pipeline_windows", run=run)
    d = run_stage(pipeline.s_stage3, ctx, "stage3")
    assert seen[0][0] is ctx and seen[0][1] == wins and isinstance(seen[0][2], ledger.Ledger)
    assert json.loads((ctx.run_dir / "stage3" / "windows.json").read_text()) == {"usv": [stage3_row()]}
    assert d["inputs"][0]["ref"].endswith("windows/windows.json") and d["inputs"][0]["sha256"]
    assert [pathlib.Path(o["path"]).name for o in d["outputs"]] == ["windows.json"]


def refit_run(tmp_path, rows, refit_iterations=2):
    ctx = ctx_for(tmp_path / "r")
    ctx.plan["refit_iterations"] = refit_iterations
    ctx.path("stage3", "windows.json").write_text(json.dumps(rows))
    d = run_stage(pipeline.s_refit, ctx, "refit")
    return json.loads((ctx.run_dir / "refit" / "refit.json").read_text()), d


def test_the_ci_budget_never_refits(tmp_path):
    out, d = refit_run(tmp_path, {"usv": [stage3_row()]}, refit_iterations=0)
    assert out == {"usv": dict(used=False, reason="budget ci: no refit")} and check_of(d, "refit_uses_only_windows_that_passed")["ok"]


def test_the_refit_uses_only_the_windows_that_passed_their_self_checks(tmp_path):
    bad = stage3_row(ok=False, cd=9.0, checks=[pm_run.check_row("mach_max", 0.4, 0.1, False), pm_run.check_row("courant_max", 0.1, 0.3, True)])
    walled = stage3_row(ok=False, checks=[pm_run.check_row("wall_model", 3.0, 1.0, False)])
    out, d = refit_run(tmp_path, {"usv": [stage3_row(cd=1.3), bad], "glider_eq": [bad, walled], "uas": []})
    u = out["usv"]
    assert u["used"] and u["drag"]["windows"] == 1 and u["drag"]["mean"] == pytest.approx(1.3) and u["drag"]["sigma"] == pytest.approx(0.05)
    assert u["drag"]["change_vs_hangar"] == pytest.approx(0.3)
    g = out["glider_eq"]
    why = "no window passed its stage-3 self-checks; Stage 1 keeps the Hangar coefficients"
    assert g == dict(used=False, reason=why, failed_checks=["mach_max", "wall_model"])
    assert out["uas"]["used"] is False and out["uas"]["failed_checks"] == [] and check_of(d, "refit_uses_only_windows_that_passed")["ok"]


def test_the_refit_multiplier_is_the_pooled_ratio_to_each_windows_own_hangar_value(tmp_path):
    """Each row carries the coefficient the vehicle's Stage-1 model implies at that window's speed (`cd_hangar`), so two windows that
    both read 1.0 times their own hangar value give a multiplier of 1.0 even though their hangar values differ."""
    rows = {"usv": [stage3_row(cd=1.0, hangar=1.0, spread=0.05), stage3_row(cd=1.4, hangar=1.4, spread=0.07)]}
    out, _ = refit_run(tmp_path, rows)
    assert out["usv"]["used"] and out["usv"]["drag"]["windows"] == 2
    assert out["usv"]["drag"]["mean"] == pytest.approx(1.0, abs=1e-9) and out["usv"]["drag"]["change_vs_hangar"] == pytest.approx(0.0, abs=1e-9)


def stage1_files(ctx):
    ctx.path("stage1", "res.pkl").write_bytes(b"pickled arrays")
    ctx.path("stage1", "summary.json").write_text('{"n": 8}')


def test_stage1b_is_a_copy_of_stage1_when_no_vehicle_was_refit(tmp_path, monkeypatch):
    ctx = ctx_for(tmp_path / "r")
    stage1_files(ctx)
    ctx.path("refit", "refit.json").write_text(json.dumps({"usv": dict(used=False, reason="x"), "uas": dict(used=False, reason="y")}))
    monkeypatch.setattr(pipeline, "_stage1", boom)
    d = run_stage(pipeline.s_stage1b, ctx, "stage1b")
    assert d["notes"] == ["no vehicle was refit: stage 1b is stage 1 (copied, not rerun)"]
    for f in ("res.pkl", "summary.json"):
        assert (ctx.run_dir / "stage1b" / f).read_bytes() == (ctx.run_dir / "stage1" / f).read_bytes()
    assert [pathlib.Path(o["path"]).name for o in d["outputs"]] == ["res.pkl", "summary.json"] and d["inputs"][0]["ref"].endswith("refit/refit.json")


def test_stage1b_reruns_stage1_with_the_multipliers_of_the_vehicles_that_were_refit(tmp_path, monkeypatch):
    ctx = ctx_for(tmp_path / "r")
    entry = dict(used=True, drag=dict(mean=1.3, sigma=0.05, windows=1))
    ctx.path("refit", "refit.json").write_text(json.dumps({"usv": entry, "uas": dict(used=False, reason="y")}))
    seen = []
    monkeypatch.setattr(pipeline, "_stage1", lambda c, L, name, scales=None: seen.append((c, name, scales)))
    d = run_stage(pipeline.s_stage1b, ctx, "stage1b")
    assert seen == [(ctx, "stage1b", {"usv": entry})] and d["notes"] == []


# ---------------------------------------------------------------------------------------------------------------- emulator

def synthetic_ctx(tmp_path, M):
    run = tmp_path / "synthetic"
    pm_run.make_run(run, M=M)
    ctx = pipeline.Context(ROOT / "missions" / "tepex_c_demo.yaml", "quick", 0, run, quiet)
    return ctx


def test_the_emulator_has_nothing_to_learn_from_a_handful_of_members_or_from_no_failures(tmp_path):
    ctx = synthetic_ctx(tmp_path, 16)
    run_stage(pipeline.s_emulator, ctx, "emulator")
    out = json.loads((ctx.run_dir / "emulator" / "holdout.json").read_text())
    res = pickle.loads((ctx.run_dir / "stage1b" / "res.pkl").read_bytes())
    assert set(out) == set(res["vehicles"]) and all(not v["trained"] for v in out.values())
    for vid, r in res["vehicles"].items():
        assert out[vid]["reason"] == f"{2 * (16 // 2)} members, {int(stage1.failed(r).sum())} failures: nothing to learn"


def test_the_emulator_trains_on_the_vehicles_whose_members_both_fail_and_succeed(tmp_path):
    ctx = synthetic_ctx(tmp_path, 48)
    d = run_stage(pipeline.s_emulator, ctx, "emulator")
    out = json.loads((ctx.run_dir / "emulator" / "holdout.json").read_text())
    res = pickle.loads((ctx.run_dir / "stage1b" / "res.pkl").read_bytes())
    k = {vid: int(stage1.failed(r).sum()) for vid, r in res["vehicles"].items()}
    assert d["inputs"][0]["ref"].endswith("stage1b/res.pkl") and d["inputs"][0]["sha256"]
    for vid, n_fail in k.items():
        if 0 < n_fail < 48:
            assert out[vid]["trained"] and out[vid]["n_test"] == 10 and out[vid]["n_train"] > 20 and 0.0 <= out[vid]["rmse"]["p_fail"] <= 1.0
            assert 0.0 <= out[vid]["coverage"]["p_fail"] <= 1.0
        else:
            assert out[vid] == dict(trained=False, reason=f"48 members, {n_fail} failures: nothing to learn")
    assert any(v["trained"] for v in out.values()) and any(not v["trained"] for v in out.values())


# ---------------------------------------------------------------------------------------------------------------- report

def report_ctx(tmp_path):
    run = tmp_path / "synthetic"
    pm_run.make_run(run, M=48)
    ctx = pipeline.Context(ROOT / "missions" / "tepex_c_demo.yaml", "quick", 0, run, quiet)
    ctx._env = AnalyticEnv()
    return ctx


def test_the_report_stage_reads_every_stage_product_and_checks_traceability(tmp_path, monkeypatch):
    monkeypatch.setenv("CAFE_DATA", str(tmp_path / "nodata"))
    ctx = report_ctx(tmp_path)
    d = run_stage(pipeline.s_report, ctx, "report")
    refs = {pathlib.Path(i["ref"]).relative_to(ctx.run_dir).as_posix() for i in d["inputs"]}
    assert {"stage1b/summary.json", "refit/refit.json", "stage3/windows.json", "windows/windows.json", "emulator/holdout.json"} <= refs
    assert all(i["sha256"] for i in d["inputs"])
    names = {pathlib.Path(o["path"]).relative_to(ctx.run_dir).as_posix() for o in d["outputs"]}
    assert {"report/index.html", "report/report.json"} <= names
    for n in ("report_traceable", "report_html_matches_json"):
        c = check_of(d, n)
        assert c["ok"] and c["value"] == 0 and c["limit"] == 0 and c["note"] == ""


@pytest.mark.parametrize("which,name", [("check_traceability", "report_traceable"), ("check_rendered", "report_html_matches_json")])
def test_a_report_that_does_not_trace_or_does_not_match_its_json_fails_the_stage(tmp_path, monkeypatch, which, name):
    monkeypatch.setenv("CAFE_DATA", str(tmp_path / "nodata"))
    ctx = report_ctx(tmp_path)
    monkeypatch.setattr(report, which, lambda *a: [f"problem {i}" for i in range(7)])
    with pytest.raises(ledger.StageFailed, match=name):
        run_stage(pipeline.s_report, ctx, "report")
    c = check_of(read_ledger(ctx.run_dir, "report"), name)
    assert (c["ok"], c["value"], c["limit"]) == (False, 7, 0) and c["note"] == "; ".join(f"problem {i}" for i in range(5))        # the first five


# ---------------------------------------------------------------------------------------------------------------- the whole pipeline

class Rows:
    """The contract of pipeline_windows.run: what it is called with and which rows it returns (a mutable policy so one fixture serves both runs)."""

    def __init__(self):
        self.passing, self.calls = set(), []

    def run(self, ctx, wins, L):
        self.calls.append(json.loads(json.dumps(wins)))
        def row(vid):
            ok = vid in self.passing
            return stage3_row(ok=ok, cd=1.3, checks=[pm_run.check_row("mach_max", 0.05 if ok else 0.4, 0.1, ok)])
        return {vid: [row(vid) for _ in ws] for vid, ws in wins.items()}


def small_budget(orig):
    def plan(name, gpus, mission, **kw):
        p = orig(name, gpus, mission, **kw)
        p.update(n_max=8, n_min=8, batch=8, refit_iterations=2)                                                      # one batch of 8 members, refit allowed
        return p
    return plan


def snapshot(run):
    """What the first run left, copied out before the second run overwrites its stages."""
    j = lambda *p: json.loads((run.joinpath(*p)).read_text())
    return types.SimpleNamespace(
        problems=audit.ledger_problems(run), refit=j("refit", "refit.json"), windows=j("windows", "windows.json"), holdout=j("emulator", "holdout.json"),
        summary1=j("stage1", "summary.json"), summary1b=j("stage1b", "summary.json"), res1=(run / "stage1" / "res.pkl").read_bytes(),
        res1b=(run / "stage1b" / "res.pkl").read_bytes(), ledger1b=read_ledger(run, "stage1b"), ledger1=read_ledger(run, "stage1"),
        fitted=j("ingest", "priors_fitted.json"), ledger_report=read_ledger(run, "report"))


@pytest.fixture(scope="module")
def ci_runs(data, tmp_path_factory):
    """The CI mission through the real pipeline twice, in one directory: first with no window passing its self-checks (stage 1b is a copy of
    stage 1), then with the USV window passing (stage 1b reruns with the refit drag). The second run resumes: ingest, hangar and stage 1 are kept
    and every later ledger is removed so the stages after them run again."""
    run = tmp_path_factory.mktemp("pm") / "run"
    mp = pytest.MonkeyPatch()
    mp.setattr(budget, "plan", small_budget(budget.plan))
    rows = Rows()
    fake_module(mp, "cafe.pm.stage3.pipeline_windows", run=rows.run)
    log1, log2 = [], []
    pipeline.run(MISSION_PATH, "ci", 0, run, log=log1.append)
    first = snapshot(run)
    rows.passing = {"usv"}
    for st in STAGES[STAGES.index("windows"):]:
        shutil.rmtree(run / "checkpoints" / st)
    pipeline.run(MISSION_PATH, "ci", 0, run, log=log2.append)
    yield types.SimpleNamespace(run=run, first=first, log1=log1, log2=log2, rows=rows)
    mp.undo()


def load_res(run, stage):
    return pickle.loads((run / stage / "res.pkl").read_bytes())


def test_the_first_run_makes_a_clean_chain_of_nine_ledgers(ci_runs):
    f = ci_runs.first
    assert f.problems == [] and [m.split(":")[0] for m in ci_runs.log1 if "done in" in m] == STAGES and not any("up to date" in m for m in ci_runs.log1)
    assert ci_runs.log1[0].startswith("budget ci (10 min), 0 GPU(s), 1.50 mission days") and "stage 1: 8..8 members in batches of 8" in ci_runs.log1[0]


def test_stage1_ran_with_the_tao_fitted_priors_and_one_stratified_batch(ci_runs):
    f = ci_runs.first
    s = f.summary1
    assert s["n"] == 8 and s["certify"] is False and s["priors"]["wind_speed_bias"]["mean"] == pytest.approx(f.fitted["wind_speed_bias"]["mean"])
    assert s["priors"]["wind_speed_bias"]["sd"] == pytest.approx(f.fitted["wind_speed_bias"]["value"]) and s["priors"]["wind_speed_bias"]["sd"] < 2.0
    assert s["names"] == stage1.FORCING + ["glider_speed_scale", "usv_vpp_bias", "battery_capacity_scale"] and set(s["summary"]["vehicles"]) == set(CLASSES)
    assert len(s["summary"]["links"]) == 3
    assert any(i["ref"].endswith("ingest/priors_fitted.json") for i in f.ledger1["inputs"]) and f.ledger1["seeds"] == {"mission": 20230301}
    c = check_of(f.ledger1, "lhs_stratified_batch1")
    assert c["ok"] and c["limit"] == pytest.approx(1 / 8)
    assert [x["name"] for x in f.ledger1["checks"]] == ["lhs_stratified_batch1"] and any("8 members in" in n for n in f.ledger1["notes"])


def test_stage1_results_carry_the_platform_antennas_the_classes_and_no_simulator_objects(ci_runs):
    res = pickle.loads(ci_runs.first.res1)
    # tail masts, the RF whip, the UAS whip
    assert {k: v["antenna_m"] for k, v in res["vehicles"].items()} == {"glider_eq": 0.5, "glider_1n": 0.3, "usv": 2.2, "uas": 0.1}
    assert {k: v["class"] for k, v in res["vehicles"].items()} == CLASSES and all("sim" not in v for v in res["vehicles"].values())
    assert res["U"].shape == (8, 9) and set(res["X"]) == set(ci_runs.first.summary1["names"])
    assert res["vehicles"]["uas"]["fail"].keys() >= {"no_sortie_flown", "battery_reserve"} and "station_lost" in res["vehicles"]["glider_eq"]["fail"]
    assert "swept_off_track" in res["vehicles"]["usv"]["fail"]
    assert all(v["lon"].shape == v["lat"].shape and v["lon"].shape[1] == 8 for v in res["vehicles"].values())
    methods = {k: v["method"] for k, v in res["links"].items()}
    assert "two-ray" in methods["usv-uas-rf"] and "Thorp" in methods["glider_eq-ship-acoustic"] and methods["usv-shore-iridium"].startswith("Iridium")
    # the section runs out of the quadrotor's radio horizon; Iridium has no range
    assert res["links"]["usv-uas-rf"]["success"].sum() == 0 and res["links"]["usv-shore-iridium"]["success"].all()


def test_windows_name_the_members_they_came_from(ci_runs):
    f = ci_runs.first
    for vid, ws in f.windows.items():
        assert len(ws) == 1 and ws[0]["basis"] == ("failed members" if f.summary1["summary"]["vehicles"][vid]["k_fail"] else "all members")
        assert T0 <= ws[0]["t"] <= T1 and set(ws[0]) == {"t", "stress", "lon", "lat", "basis"} and np.isfinite(ws[0]["stress"])
    assert any(w[0]["basis"] == "failed members" for w in f.windows.values())                                           # the USV fails in this mission


def test_no_passing_window_means_no_refit_and_stage1b_is_a_copy(ci_runs):
    f = ci_runs.first
    assert ci_runs.rows.calls[0] == f.windows
    assert set(f.refit) == set(CLASSES)
    for r in f.refit.values():
        assert r["used"] is False and r["reason"].startswith("no window passed") and r["failed_checks"] == ["mach_max"]
    assert f.res1b == f.res1 and f.summary1b == f.summary1 and f.ledger1b["notes"] == ["no vehicle was refit: stage 1b is stage 1 (copied, not rerun)"]
    outs = {pathlib.Path(o["path"]).name: o["sha256"] for o in f.ledger1b["outputs"]}
    assert set(outs) == {"res.pkl", "summary.json"} and outs["res.pkl"] == hashlib.sha256(f.res1).hexdigest()


def test_the_emulator_has_nothing_to_learn_from_eight_members(ci_runs):
    f = ci_runs.first
    for vid, h in f.holdout.items():
        assert h == dict(trained=False, reason=f"8 members, {f.summary1['summary']['vehicles'][vid]['k_fail']} failures: nothing to learn")


def test_the_report_of_the_first_run_traces_to_its_ledgers(ci_runs):
    for n in ("report_traceable", "report_html_matches_json"):
        assert check_of(ci_runs.first.ledger_report, n)["ok"]


def test_the_second_run_resumes_ingest_hangar_and_stage1_and_redoes_the_rest(ci_runs):
    assert [m.split(":")[0] for m in ci_runs.log2 if "up to date" in m] == ["ingest", "hangar", "stage1"]
    assert [m.split(":")[0] for m in ci_runs.log2 if "done in" in m] == STAGES[3:]
    assert audit.ledger_problems(ci_runs.run) == [] and (ci_runs.run / "report" / "index.html").stat().st_size > 1000


def test_a_passing_window_is_refit_and_the_usv_is_rerun_with_its_drag(ci_runs):
    run = ci_runs.run
    ref = json.loads((run / "refit" / "refit.json").read_text())
    assert ref["usv"]["used"] and ref["usv"]["drag"]["mean"] == pytest.approx(1.3) and ref["usv"]["drag"]["windows"] == 1
    assert all(not ref[v]["used"] for v in ("glider_eq", "glider_1n", "uas"))
    d = read_ledger(run, "stage1b")
    assert d["notes"][0].endswith("certify possible: False (n_certify 73)") and "copied" not in " ".join(d["notes"])
    assert check_of(d, "lhs_stratified_batch1")["ok"]
    assert any(i["ref"].endswith("refit/refit.json") for i in d["inputs"]) and d["seeds"] == {"mission": 20230301}
    one, two = load_res(run, "stage1"), load_res(run, "stage1b")
    assert not np.array_equal(one["vehicles"]["usv"]["lon"], two["vehicles"]["usv"]["lon"], equal_nan=True)


def path_km(r):
    k = np.pi / 180
    dx = np.diff(r["lon"], axis=0) * np.cos(np.radians(r["lat"][:-1]))
    return np.nansum(np.hypot(dx, np.diff(r["lat"], axis=0)), axis=0) * k * 6371.0


def test_more_drag_slows_the_usv_and_leaves_the_other_vehicles_exactly_as_they_were(ci_runs):
    one, two = load_res(ci_runs.run, "stage1"), load_res(ci_runs.run, "stage1b")
    # the same hypercube: stage 1b differs only by the refit
    assert np.array_equal(one["U"], two["U"]) and all(np.array_equal(one["X"][k], two["X"][k]) for k in one["X"])
    for vid in ("glider_eq", "glider_1n", "uas"):
        a, b = one["vehicles"][vid], two["vehicles"][vid]
        assert all(np.array_equal(a[k], b[k], equal_nan=True) for k in ("lon", "lat", "depth", "surfaced"))
        assert all(np.array_equal(a["fail"][k], b["fail"][k]) for k in a["fail"]), vid
    ratio = np.median(path_km(two["vehicles"]["usv"])) / np.median(path_km(one["vehicles"]["usv"]))
    # speed follows drag^-1/2: 1.3^-0.5 = 0.877
    assert 0.8 < ratio < 0.97


def test_the_second_report_and_the_audit_follow_the_final_stage_1b(ci_runs):
    run = ci_runs.run
    rep = json.loads((run / "report" / "report.json").read_text())
    d = read_ledger(run, "report")
    assert all(check_of(d, n)["ok"] for n in ("report_traceable", "report_html_matches_json")) and rep["vehicles"]["usv"] is not None
    assert json.loads((run / "emulator" / "holdout.json").read_text()).keys() == set(CLASSES)


def test_rerunning_a_finished_pipeline_changes_nothing(ci_runs):
    run, log = ci_runs.run, []
    before = {st: (run / "checkpoints" / st / "ledger.json").read_bytes() for st in STAGES}
    pipeline.run(MISSION_PATH, "ci", 0, run, log=log.append)
    assert [m.split(":")[0] for m in log if "up to date" in m] == STAGES and not any("done in" in m for m in log)
    assert before == {st: (run / "checkpoints" / st / "ledger.json").read_bytes() for st in STAGES}
