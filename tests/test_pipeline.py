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
import re
import shutil
import time
import types

import numpy as np
import pytest
import yaml

from cafe.pm import audit, budget, config, ledger, par, pipeline, report, stage1
from cafe.pm.audit import STAGES
from cafe.pm.env import ocean as ocean_mod, orca, surface, tao
from cafe.pm.env.environment import GriddedEnv
from cafe.pm.env.protocol import AnalyticEnv
from cafe.pm.physics import glider, uas, usv
from cafe.pm.stats import sampling
from tests.fixtures import pm_run
from tests.fixtures.ci_env import make as fx
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


def ctx_for(run_dir, budget_name="ci", mission=MISSION_PATH, gpus=0, log=quiet, record=True):
    """A Context, with the record ingest leaves of the surface layer it reads (ingest/derived.digest.json) when the cache has one, so that a test of a
    later stage does not have to run ingest first. A test of the check itself writes the record with a real ingest instead."""
    ctx = pipeline.Context(mission, budget_name, gpus, run_dir, log)
    store = ctx.cache / "derived.zarr"
    if record and store.is_dir() and not (ctx.run_dir / "ingest" / surface.DIGEST).exists():
        ctx.path("ingest", surface.DIGEST).write_text(json.dumps(dict(built_from=None, store_sha256=surface.store_sha256(store))))
    return ctx


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
             "platforms/p.yaml": "v: 1\n", "platforms/notes.txt": "n", "cafe/other/z.py": "z = 1\n", "cafe/schemas/s.json": "{}\n",
             "docs/readme.md": "r", "cafe/pm/__pycache__/a.py": "junk"}
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
             ("platforms/p.yaml", "v: 2\n"), ("cafe/other/z.py", "z = 2\n"),        # cafe/other: the pipeline imports cafe.cfd, cafe.fea, ... too
             ("cafe/schemas/s.json", '{"units": "m/s"}\n'))                           # the schemas are the contract ingest and load_mission read (M-32)
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
    for rel in ("docs/readme.md", "platforms/notes.txt", "cafe/pm/__pycache__/a.py", "cafe/pm/__pycache__/new.py", "platforms/sub/q.yaml", "cafe/site/page.py",
                "cafe/other/notes.txt", "tests/test_x.py"):
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("changed")
        assert pipeline.code_digest() == base, rel
    (tmp_path / "cafe" / "new_module.py").write_text("n = 1\n")
    assert pipeline.code_digest() != base                                                                   # a new module anywhere under cafe/ counts
    (tmp_path / "cafe" / "new_module.py").unlink()
    assert pipeline.code_digest() == base
    (tmp_path / "cafe" / "schemas" / "notes.txt").write_text("not a schema")
    assert pipeline.code_digest() == base
    (tmp_path / "cafe" / "schemas" / "mission2.json").write_text("{}")
    assert pipeline.code_digest() != base                                                                   # a new schema counts
    (tmp_path / "cafe" / "schemas" / "mission2.json").unlink()
    assert pipeline.code_digest() == base
    (tmp_path / "platforms" / "n.yaml").write_text("v: 1\n")
    added = pipeline.code_digest()
    assert added != base
    (tmp_path / "platforms" / "n.yaml").rename(tmp_path / "platforms" / "m.yaml")
    assert pipeline.code_digest() not in (base, added)                                                       # same bytes, other name


def test_code_digest_covers_every_installed_library_version_and_the_python_minor_but_not_its_patch(tmp_path, monkeypatch):
    """Round 3 M-22: a new gsw, smt, xlb or statsmodels left every ledger "up to date"; the digest named only jax, numpy and scipy."""
    code_tree(tmp_path)
    monkeypatch.setattr(pipeline, "__file__", str(tmp_path / "cafe" / "pm" / "pipeline.py"))
    v = dict(ledger.versions(), python="3.12.4")
    monkeypatch.setattr(ledger, "versions", lambda: dict(v))
    base = pipeline.code_digest()
    for lib in ledger.LIBS:
        monkeypatch.setattr(ledger, "versions", lambda lib=lib: dict(v, **{lib: "0.0.1"}))
        assert pipeline.code_digest() != base, lib
    monkeypatch.setattr(ledger, "versions", lambda: dict(v, python="3.12.9"))
    assert pipeline.code_digest() == base                                                                    # the patch level is not part of it
    monkeypatch.setattr(ledger, "versions", lambda: dict(v, python="3.13.0"))
    assert pipeline.code_digest() != base
    monkeypatch.setattr(ledger, "versions", lambda: dict(v, xlb=None))                                       # a library that is not installed is left out
    assert pipeline.code_digest() != base
    monkeypatch.setattr(ledger, "versions", lambda: dict(v, newlib=None))
    assert pipeline.code_digest() == base


def test_the_resume_hash_does_not_depend_on_how_the_mission_path_is_spelled(tmp_path):
    """Round 3 M-21: the mission dict carried `_path` as typed, so ./m.yaml, an absolute path and a path through .. hashed differently."""
    d = tmp_path / "sub"
    d.mkdir()
    m = d / "m.yaml"
    m.write_text(MISSION_PATH.read_text())
    a = ctx_for(tmp_path / "r", mission=m)
    b = ctx_for(tmp_path / "r", mission=d / ".." / "sub" / "m.yaml")
    c = ctx_for(tmp_path / "r", mission=str(m))
    assert a.mission["_path"] != b.mission["_path"] and a.hash == b.hash == c.hash


def test_a_changed_cafe_module_outside_cafe_pm_reruns_the_stages(tmp_path, monkeypatch):
    """`--resume` reused stage-3 output made by an older cafe/fea.py or cafe/cfd.py: the module is in the resume hash now."""
    code_tree(tmp_path)
    monkeypatch.setattr(pipeline, "__file__", str(tmp_path / "cafe" / "pm" / "pipeline.py"))
    a = ctx_for(tmp_path / "r").hash
    (tmp_path / "cafe" / "other" / "z.py").write_text("z = 2\n")
    assert ctx_for(tmp_path / "r").hash != a


# ---------------------------------------------------------------------------------------------------------------- context

def test_context_plans_the_budget_for_the_vehicle_classes(tmp_path, data):
    ctx = ctx_for(tmp_path / "r", record=False)
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
    ctx = ctx_for(tmp_path / "r", record=False)
    p = ctx.path("x", "y", "z.json")
    assert p == tmp_path / "r" / "x" / "y" / "z.json" and p.parent.is_dir() and not p.exists()


def test_context_env_is_built_once_from_the_cache_the_ocean_and_the_surface_layer(tmp_path, data):
    ctx = ctx_for(tmp_path / "r")
    env = ctx.env
    assert env is ctx.env and isinstance(env, GriddedEnv) and env.ocean is not None and env.subgrid is not None
    assert bool(env.inside(-165.0 % 360, 0.0)) and not bool(env.inside(-100.0 % 360, 0.0))


def test_ocean_is_opened_for_the_mission_box_plus_its_pad(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(ocean_mod, "open_ocean", lambda spec, cache, name, box, **kw: seen.append((spec, cache, name, box, kw)) or "OCEAN")
    ctx = ctx_for(tmp_path / "r")
    assert pipeline.ocean(ctx) == "OCEAN"
    (spec, cache, name, box, kw), = seen
    assert (spec, cache, name, box) == ({"source": "gofs31"}, ctx.cache, "ci_fixture", (-2.0, 2.0, -167.0, -163.0))   # (S, N, W, E), 0.5 degree pad
    assert kw["fetch_bathy"] is False and set(kw["umwm"]) == {"lon", "lat", "depth"}      # offline: no download; UMWM's depth rides along for the last fallback


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
        assert d["ok"] and d["stage"] == st and d["config_hash"] == ctx.stage_hash(st) and d["error"] is None   # round 5 M-15: the emulator's carries its plan
        refs = [i["ref"] for i in d["inputs"]]
        assert (str(prev) in refs) if prev else not refs
        assert [pathlib.Path(o["path"]).name for o in d["outputs"]] == ["out.txt"]
        prev = run / "checkpoints" / st / "ledger.json"
    assert audit.ledger_problems(run) == []


def test_a_corrupt_training_table_stops_the_run_before_the_first_stage_and_fetch_does_not_read_it(tmp_path, monkeypatch):
    """Round 4 M-23: the emulator stage read the shared table after stages 1 to 3 and 1b; the run now reads it once at the start."""
    calls = []
    stub_stages(monkeypatch, calls)
    t = tmp_path / "train.parquet"
    t.write_bytes(b"not parquet")
    with pytest.raises(config.ConfigError, match=f"training table {t} cannot be read"):
        go(tmp_path / "run", emulator_table=t)
    assert calls == [] and not (tmp_path / "run" / "checkpoints").exists()
    go(tmp_path / "f", stop_after="ingest", emulator_table=t)                                           # fetch needs no table
    assert calls == ["ingest"]
    t.unlink()
    go(tmp_path / "run2", emulator_table=t)                                                             # an absent table is a new one
    assert calls[1:] == STAGES


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
    with pytest.raises(ledger.StageFailed, match=r"stage stage1: self-checks failed: boom \(ledger: "):
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
    ctx = ctx_for(tmp_path / "r")        # load_mission loads each platform at validation: the mission is read before the file is broken
    for mod in (config, glider, usv):
        monkeypatch.setattr(mod, "PLATFORMS", plat)
    monkeypatch.setattr(uas, "PLATFORM", plat / "quad_uas.yaml")
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
    run_stage(pipeline.s_ingest, ctx_for(tmp_path / "warm"), "ingest")  # the fixture's surface layer was built without a key: this ingest rebuilds it once
    monkeypatch.setattr(orca, "ingest", boom)
    monkeypatch.setattr(surface, "build", boom)
    log = []
    ctx = ctx_for(tmp_path / "r", log=log.append)
    d = run_stage(pipeline.s_ingest, ctx, "ingest")
    man = data.cache / "orca" / "manifest.json"
    assert log == [f"ingest: orca cache {man.parent} covers the window, the box and the 3-D hours"]              # everything else was cached: nothing fetched
    c = check_of(d, "orca_hours_cover_window")
    assert c["ok"] and c["value"] == 37 == c["limit"] and check_of(d, "ocean_source_covers_box")["note"].startswith("{'source': 'gofs31'}: tightest is ")
    first = d["inputs"][0]
    assert first["ref"].startswith("https://orca.") and first["sha256"] is None and first["kind"] == "remote"
    outs = {pathlib.Path(o["path"]).name: o["sha256"] for o in d["outputs"]}
    assert set(outs) == {"manifest.json", "tao_compare.json", "priors_fitted.json", "env_sigmas_fitted.json", "derived.digest.json"}
    assert outs["manifest.json"] == ledger.sha256(man)
    store = next(i for i in d["inputs"] if i["ref"].endswith("derived.zarr"))
    recorded = json.loads((tmp_path / "r" / "ingest" / surface.DIGEST).read_text())["store_sha256"]
    assert store["sha256"] == surface.store_sha256(data.cache / "derived.zarr") == recorded
    assert not [n for n in d["notes"] if n.startswith("cold fetch") or "pad_deg" in n]  # warm cache and a pad the mission sets: nothing to say


def test_the_offline_note_says_to_unset_the_variable_unless_another_command_is_named(tmp_path, data_copy):
    """Round 4 M-22: the note named `fetch` as the command to run, which for `fetch` is the command that was just run."""
    shutil.rmtree(data_copy / "cache" / "ci_fixture" / "orca")
    shutil.rmtree(data_copy / "ocean")
    with pytest.raises(ledger.StageFailed) as e:
        run_stage(pipeline.s_ingest, ctx_for(tmp_path / "r"), "ingest")
    notes = {c["name"]: c["note"] for c in read_ledger(tmp_path / "r", "ingest")["checks"] if not c["ok"]}
    again = f"unset CAFE_OFFLINE and run `python -m cafe.pm fetch --mission {MISSION_PATH}`"
    assert f"CAFE_OFFLINE is set, so nothing is downloaded: {again}" in notes["orca_present"]
    assert "orca_present: the orca WRF/UMWM cache for the window is not cached" in str(e.value)
    ctx = ctx_for(tmp_path / "h")
    with ledger.Ledger(ctx.run_dir, "ingest", ctx.hash) as L:
        pipeline._need(ctx, L, "x", "the thing", lambda: False, boom, hint="python -m cafe.pm ingest-ocean --mission M")
        assert L.d["checks"][0]["note"].endswith("so nothing is downloaded: run `python -m cafe.pm ingest-ocean --mission M`")
        L.d["checks"].clear()


def test_ingest_fetches_when_the_manifest_is_missing_or_does_not_cover_the_window(tmp_path, data_copy, monkeypatch):
    monkeypatch.delenv("CAFE_OFFLINE")                                              # fetching is allowed; the (fake) orca fetch is what runs
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


def test_a_cold_fetch_is_noted_with_its_parts_and_seconds_and_does_not_count_against_the_budget(tmp_path, data_copy, monkeypatch):
    monkeypatch.delenv("CAFE_OFFLINE")
    man = data_copy / "cache" / "ci_fixture" / "orca" / "manifest.json"
    saved = man.read_text()
    man.unlink()

    def fake_ingest(t0, t1, box, out, hours3d=(), threads=8, spectra=True, log=print):
        log("ingest: 315 parts, 15 cached, fetching 300 with 8 threads")
        log("  300/300 parts, 5 s")
        man.write_text(saved)
    monkeypatch.setattr(orca, "ingest", fake_ingest)
    d = run_stage(pipeline.s_ingest, ctx_for(tmp_path / "r"), "ingest")
    cold = [n for n in d["notes"] if n.startswith("cold fetch")]
    assert len(cold) == 1 and re.fullmatch(r"cold fetch: 300 parts, \d+ s \(the network step; --budget does not count it\)", cold[0])


def test_a_fetch_that_logs_nothing_is_noted_by_name(tmp_path, monkeypatch):
    monkeypatch.delenv("CAFE_OFFLINE", raising=False)
    ctx = ctx_for(tmp_path / "r")
    have = []
    with ledger.Ledger(ctx.run_dir, "ingest", ctx.hash) as L:
        assert pipeline._need(ctx, L, "thing", "the thing", lambda: bool(have), lambda: have.append(1))
        assert pipeline._need(ctx, L, "thing2", "the other", lambda: True, boom)                                  # cached: no fetch, no note
    assert len(L.d["notes"]) == 1 and re.fullmatch(r"cold fetch: the thing, \d+ s \(the network step; --budget does not count it\)", L.d["notes"][0])


def test_the_box_pad_is_the_missions_or_sized_from_the_window_and_the_ledger_says_which(tmp_path, data_copy):
    m = config.load_mission(MISSION_PATH)
    assert pipeline.padding(m) == 0.5 and pipeline.ocean_box(m) == (-2.0, 2.0, -167.0, -163.0)
    unset = dict(m, box={k: v for k, v in m["box"].items() if k != "pad_deg"})
    assert pipeline.padding(unset) == 1.0  # 1.5 d x 0.5 m/s = 0.58 deg, rounded up to a half degree
    assert pipeline.ocean_box(unset) == (-2.5, 2.5, -167.5, -162.5)
    six = dict(unset, window=dict(start="2023-03-01T00:00:00Z", end="2023-03-07T00:00:00Z"))
    assert pipeline.padding(six) == 2.5 and pipeline.padding(dict(six, box=dict(six["box"], pad_deg=2.0))) == 2.0         # the demo window: 2.3 deg -> 2.5
    month = dict(unset, window=dict(start="2023-03-01T00:00:00Z", end="2023-03-31T00:00:00Z"))
    assert pipeline.padding(month) == pipeline.MAX_PAD_DEG == 10.0                                              # capped at the schema's maximum
    import yaml
    raw = yaml.safe_load(MISSION_PATH.read_text())
    del raw["box"]["pad_deg"]
    (tmp_path / "m.yaml").write_text(yaml.safe_dump(raw))
    with pytest.raises(ledger.StageFailed):  # the cache was cut to the 0.5 deg box: offline, nothing can be fetched
        run_stage(pipeline.s_ingest, ctx_for(tmp_path / "r", mission=tmp_path / "m.yaml"), "ingest")
    notes = read_ledger(tmp_path / "r", "ingest")["notes"]
    assert notes[0].startswith("box.pad_deg is not set by the mission: sized 1 deg from the window (1.5 d) x 0.5 m/s") and "set pad_deg" in notes[0]


def test_ingest_keeps_the_derived_layer_it_built_and_rebuilds_it_when_the_cache_or_the_code_changes(tmp_path, data_copy, monkeypatch):
    """Round 4 M-2: the layer was rebuilt only when its layout number changed, so an edited orca cache or code kept the old one (18 h to 2.4 d older than
    the cache beside it in the demo). It is built from a key over the cache files and the code, and a second ingest of the same inputs keeps it."""
    store = data_copy / "cache" / "ci_fixture" / "derived.zarr"
    attrs = lambda: json.loads((store / "zarr.json").read_text())["attributes"]                       # noqa: E731
    (store.parent / surface.DIGEST).unlink(missing_ok=True)  # an earlier test may have left the copied layer current
    logs = []

    def ingest(name):
        c = ctx_for(tmp_path / name, log=logs.append)
        run_stage(pipeline.s_ingest, c, "ingest")
        return c, (store / "zarr.json").stat().st_mtime_ns, attrs()["built_from"]
    c, t1, key1 = ingest("a")
    assert key1 and json.loads((c.cache / surface.DIGEST).read_text()) == dict(built_from=key1, store_sha256=surface.store_sha256(store))
    assert any(m.startswith("surface layer: COARE on 37 hours") for m in logs)
    logs.clear()
    _, t2, key2 = ingest("b")
    assert (t2, key2) == (t1, key1) and not any(m.startswith("surface layer:") for m in logs)           # same inputs, same code: not rebuilt
    real_digest = pipeline.code_digest
    monkeypatch.setattr(pipeline, "code_digest", lambda: "an edited module")
    _, t3, key3 = ingest("c")
    assert t3 > t2 and key3 != key1 and any(m.startswith("surface layer: COARE") for m in logs)         # a code edit rebuilds it
    monkeypatch.setattr(pipeline, "code_digest", real_digest)
    man = data_copy / "cache" / "ci_fixture" / "orca" / "manifest.json"
    man.write_text(man.read_text().replace('"hours": 37', '"hours": 37, "refetched": true'))
    _, t4, key4 = ingest("d")
    assert t4 > t3 and key4 not in (key1, key3)                                                          # so does a changed cache file


def test_a_store_edited_after_ingest_fails_the_stage_that_reads_it_and_the_next_ingest_rebuilds_it(tmp_path, data_copy, monkeypatch):
    """Round 4 M-2, the reviewer's tamper run: u* x 3 in the stored layer left the ledger ok and the check list clean (the layer was in no hash)."""
    import zarr
    store = data_copy / "cache" / "ci_fixture" / "derived.zarr"
    run_stage(pipeline.s_ingest, ctx_for(tmp_path / "r"), "ingest")
    good = surface.store_sha256(store)
    clean = zarr.open_group(store, mode="r")["ustar"][:].mean()
    g = zarr.open_group(store, mode="r+")
    g["ustar"][:] = 3.0 * g["ustar"][:]
    monkeypatch.setattr(stage1, "run", fake_run({}))
    ctx = pipeline.Context(MISSION_PATH, "ci", 0, tmp_path / "r", quiet)                                  # the record is the one ingest wrote
    ctx._env = types.SimpleNamespace(subgrid=object())                                                   # an environment that reads the layer
    with pytest.raises(ledger.StageFailed, match="derived_unchanged"):
        run_stage(pipeline.s_stage1, ctx, "stage1")
    c = check_of(read_ledger(tmp_path / "r", "stage1"), "derived_unchanged")
    assert not c["ok"] and c["limit"] == good and c["value"] == surface.store_sha256(store) != good and "rerun" in c["note"]
    c = ctx_for(tmp_path / "n")                                                                         # a rerun of ingest finds it changed and rebuilds it
    run_stage(pipeline.s_ingest, c, "ingest")
    assert surface.store_sha256(store) == json.loads((c.cache / surface.DIGEST).read_text())["store_sha256"]
    assert zarr.open_group(store, mode="r")["ustar"][:].mean() == pytest.approx(clean)


def test_without_ingests_record_the_stage_that_reads_the_surface_layer_fails_its_check(tmp_path, monkeypatch):
    """Without ingest's record there is nothing to compare the store with, which is a failed check, not a pass; an environment with no layer has none."""
    monkeypatch.setattr(stage1, "run", fake_run({}))
    ctx = pipeline.Context(MISSION_PATH, "ci", 0, tmp_path / "r", quiet)
    ctx._env = types.SimpleNamespace(subgrid=object())
    with pytest.raises(ledger.StageFailed, match="derived_unchanged: .*derived.digest.json is missing"):
        run_stage(pipeline.s_stage1, ctx, "stage1")
    ctx._env = "ENV"  # an environment with no layer (the analytic ones) has no check
    L = ledger.Ledger(tmp_path / "y", "s", "h")
    pipeline._derived_unchanged(ctx, L)
    assert L.d["checks"] == [] and L.d["inputs"] == []


def test_a_derived_store_that_does_not_span_the_window_is_refused_not_clipped(tmp_path, data_copy):
    """Round 4 M-2 (3): `Axis.locate` clips a query outside the axis to its edge, so a window edited past the stored hours was served the last stored hour."""
    ctx = ctx_for(tmp_path / "ok")
    assert pipeline._derived_span_problem(ctx.cache, ctx.window_s()) is None and ctx.env.subgrid is not None
    t0, t1 = ctx.window_s()
    assert pipeline._derived_span_problem(ctx.cache, (t0, t1 + 3600.0)) is None                           # one hour is the step of the fields
    early = pipeline._derived_span_problem(ctx.cache, (t0 - 7200.0, t1))
    assert early.startswith("its hours span 2023-03-01 18:00 to 2023-03-03 06:00 UTC, the mission window is 2023-03-01 16:00")
    raw = yaml.safe_load(MISSION_PATH.read_text())
    raw["window"]["end"] = "2023-03-04T06:00:00Z"
    (tmp_path / "m.yaml").write_text(yaml.safe_dump(raw))
    longer = ctx_for(tmp_path / "long", mission=tmp_path / "m.yaml")
    with pytest.raises(config.ConfigError, match=r"/derived\.zarr: its hours span 2023-03-01 18:00 to 2023-03-03 06:00 UTC, the mission window is "
                                                 r"2023-03-01 18:00 to 2023-03-04 06:00 UTC; rerun `python -m cafe.pm fetch --mission .*m\.yaml` to rebuild"):
        assert longer.env is None


def test_ingest_builds_the_derived_surface_layer_when_it_is_missing(tmp_path, data_copy):
    """The first ingest of a mission has no derived.zarr: the stage has to build it from the gridded fields (surface.build takes an env without
    a surface layer) and hand every later stage an env that has one."""
    shutil.rmtree(data_copy / "cache" / "ci_fixture" / "derived.zarr")
    ctx = ctx_for(tmp_path / "r")
    run_stage(pipeline.s_ingest, ctx, "ingest")
    assert (ctx.cache / "derived.zarr").is_dir() and ctx.env.subgrid is not None


def test_ingest_fails_when_the_ocean_store_is_missing_or_the_cache_has_too_few_hours(tmp_path, data, data_copy):
    shutil.rmtree(data_copy / "ocean")
    with pytest.raises(ledger.StageFailed, match="ocean_store_present"):
        run_stage(pipeline.s_ingest, ctx_for(tmp_path / "a"), "ingest")
    assert not check_of(read_ledger(tmp_path / "a", "ingest"), "ocean_store_present")["ok"]
    shutil.copytree(data.data / "ocean", data_copy / "ocean")                                                  # the store is back; now the orca cache is short
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


def test_sortie_hours_are_the_launch_hour_to_the_hour_after_the_hard_stop_as_naive_utc():
    v = next(x for x in config.load_mission(MISSION_PATH)["vehicles"] if x["id"] == "uas")
    got = pipeline._sortie_hours(v, -165.0, config.utc("2023-03-01T18:00:00Z"), config.utc("2023-03-03T06:00:00Z"))
    assert got == [dt.datetime(2023, 3, 2, 1), dt.datetime(2023, 3, 2, 2), dt.datetime(2023, 3, 3, 1), dt.datetime(2023, 3, 3, 2)]
    late = dict(v, sorties=dict(v["sorties"], local_solar_time="14:50"))                                           # 01:50 UTC, hard stop 32 min later: 02:22
    one_night = pipeline._sortie_hours(late, -165.0, config.utc("2023-03-01T18:00:00Z"), config.utc("2023-03-02T06:00:00Z"))
    assert one_night == [dt.datetime(2023, 3, 2, 1), dt.datetime(2023, 3, 2, 2), dt.datetime(2023, 3, 2, 3)]  # a launch at :50 reads three hours (it read two)
    plain = dict(v, sorties={"local_solar_time": "14:00"})
    # duration_min defaults to 20
    assert len(pipeline._sortie_hours(plain, -165.0, config.utc("2023-03-01T18:00:00Z"), config.utc("2023-03-03T06:00:00Z"))) == 4


def test_a_long_sortie_reads_every_hour_to_its_hard_stop(monkeypatch):
    """90 min x the platform's hard_stop_factor (1.6) = 144 min from 01:00 reaches 03:24: the hours 01, 02, 03 and 04 hold its 3-D fields."""
    v = next(x for x in config.load_mission(MISSION_PATH)["vehicles"] if x["id"] == "uas")
    long = dict(v, sorties=dict(v["sorties"], duration_min=90))
    got = pipeline._sortie_hours(long, -165.0, config.utc("2023-03-01T18:00:00Z"), config.utc("2023-03-03T06:00:00Z"))
    assert got == [dt.datetime(2023, 3, d, h) for d in (2, 3) for h in (1, 2, 3, 4)]
    monkeypatch.setattr(config, "load_platform", lambda name: {"sortie": {"hard_stop_factor": {"value": 1.0}}})   # no hard-stop stretch: 01:00 + 90 min
    one = pipeline._sortie_hours(long, -165.0, config.utc("2023-03-01T18:00:00Z"), config.utc("2023-03-02T06:00:00Z"))
    assert one == [dt.datetime(2023, 3, 2, h) for h in (1, 2, 3)]


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
    assert set(fit) == {"wind_speed_bias", "wind_direction_bias", "wind_speed_noise", "wind_direction_noise"}
    s, w = fit["wind_speed_bias"], fit["wind_direction_bias"]
    hourly = (np.sqrt(a["speed_rmse"] ** 2 - a["speed_bias"] ** 2), np.sqrt(a["dir_rmse_deg"] ** 2 - a["dir_bias_deg"] ** 2))
    # the persistent part is part of the hourly misfit, never more
    assert s["mean"] == pytest.approx(-a["speed_bias"]) and 0.0 <= s["value"] <= hourly[0] + 1e-9
    assert s["unit"] == "m/s"
    assert w["mean"] == pytest.approx(-a["dir_bias_deg"]) and 0.0 <= w["value"] <= hourly[1] + 1e-9
    assert w["unit"] == "deg"
    assert s["dist"] == w["dist"] == "normal" and s["kind"] == w["kind"] == "data" and "2 moorings" in s["citation"] and "persistent part only" in s["citation"]
    sn, wn = fit["wind_speed_noise"], fit["wind_direction_noise"]
    assert sn["unit"] == "m/s" and wn["unit"] == "deg" and sn["dist"] == "normal" and sn["value"] > 0 and wn["value"] > 0
    assert sn["tau_h"] >= 0 and wn["tau_h"] >= 0
    assert "AR(1)" in sn["citation"] and sn["kind"] == "data"
    assert "2023-03-01T18:00:00Z..2023-03-03T06:00:00Z" in s["citation"]
    c = check_of(d, "tao_moorings_compared")
    assert c["ok"] and c["value"] == 2 and c["limit"] == 1 and len(d["notes"]) == 2 and d["notes"][0].startswith("env sigmas fitted")
    assert d["notes"][1].startswith("wind error split: speed persistent ") and "short-lived" in d["notes"][1] and "direction persistent " in d["notes"][1]
    assert any(i["ref"].endswith("tao/manifest.json") and i["sha256"] for i in d["inputs"])
    assert {pathlib.Path(o["path"]).name for o in d["outputs"]} == {"tao_compare.json", "priors_fitted.json", "env_sigmas_fitted.json"}


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
    ctx = ctx_for(tmp_path / "r", record=False)
    d = tao_stage(ctx, ctx.env.tw.x[0], ctx.env.tw.x[-1])
    assert d["notes"] == [f"no TAO/TRITON download at {data_copy / 'tao'}: wind priors stay the perturbations.yaml defaults (run `make fetch`)"]
    assert d["checks"] == [] and d["outputs"] == [] and d["inputs"] == [] and not (ctx.run_dir / "ingest").exists()


def test_a_negative_variance_from_rounding_gives_a_zero_spread(tmp_path, data, monkeypatch):
    """With the per-mooring series unavailable the pooled hourly misfit stands (one persistent error, no split); its rounding can go negative."""
    ctx, t0, t1 = tao_ctx(tmp_path)
    monkeypatch.setattr(pipeline, "_wind_residuals", lambda wrf, moor: {})
    monkeypatch.setattr(tao, "compare", lambda wrf, moor: {"M": {}, "ALL": dict(speed_bias=0.5, speed_rmse=0.5 - 1e-12, dir_bias_deg=2.0,
                                                                                      dir_rmse_deg=1.0, sst_rmse=float("nan"))})
    tao_stage(ctx, t0, t1)
    fit = json.loads((ctx.run_dir / "ingest" / "priors_fitted.json").read_text())
    assert fit["wind_speed_bias"]["value"] == 0.0 and fit["wind_direction_bias"]["value"] == 0.0 and fit["wind_speed_bias"]["mean"] == -0.5
    assert set(fit) == {"wind_speed_bias", "wind_direction_bias"} and "fewer than 2 moorings" in fit["wind_speed_bias"]["citation"]  # no noise without a split


def test_with_fewer_than_two_moorings_the_whole_hourly_misfit_is_the_persistent_error(tmp_path, data, monkeypatch):
    ctx, t0, t1 = tao_ctx(tmp_path)
    real = pipeline._wind_residuals
    monkeypatch.setattr(pipeline, "_wind_residuals", lambda wrf, moor: dict(list(real(wrf, moor).items())[:1]))
    tao_stage(ctx, t0, t1)
    a = json.loads((ctx.run_dir / "ingest" / "tao_compare.json").read_text())["ALL"]
    fit = json.loads((ctx.run_dir / "ingest" / "priors_fitted.json").read_text())
    assert fit["wind_speed_bias"]["value"] == pytest.approx(np.sqrt(a["speed_rmse"] ** 2 - a["speed_bias"] ** 2)) and "wind_speed_noise" not in fit


def tao_inputs(ctx, t0, t1):
    moor = tao.load_tao(pipeline.DATA / "tao", t0, t1)
    hours = np.arange(t0, t1 + 1, 3600.0)
    wrf = {}
    for name, m in moor.items():
        lo, la = np.full(hours.size, float(m["lon"])), np.full(hours.size, float(m["lat"]))
        wrf[name] = dict(t=hours, wind10=ctx.env.u10(lo, la, hours), sst=ctx.env.sst(lo, la, hours).value)
    return wrf, moor


def test_the_hourly_residual_series_are_the_ones_tao_compare_summarises(tmp_path, data):
    """`_wind_residuals` repeats compare's lift and binning to keep the hourly series: its means and RMS must be compare's per-mooring numbers."""
    ctx, t0, t1 = tao_ctx(tmp_path)
    wrf, moor = tao_inputs(ctx, t0, t1)
    res, cmp = pipeline._wind_residuals(wrf, moor), tao.compare(wrf, moor)
    assert set(res) == {"T0N165W", "T2S165W"}
    for name, r in res.items():
        sp, dr = r[:, 0], r[:, 1]
        assert np.isfinite(sp).sum() == cmp[name]["n"] and np.isfinite(dr).sum() == cmp[name]["dir_n"] > 0
        assert np.nanmean(sp) == pytest.approx(cmp[name]["speed_bias"]) and np.sqrt(np.nanmean(sp ** 2)) == pytest.approx(cmp[name]["speed_rmse"])
        assert np.nanmean(dr) == pytest.approx(cmp[name]["dir_bias_deg"]) and np.sqrt(np.nanmean(dr ** 2)) == pytest.approx(cmp[name]["dir_rmse_deg"])
    log = {k: dict(v) for k, v in moor.items()}
    for v in log.values():
        for k in ("airt", "rh", "sst"):
            v.pop(k, None)                                                                    # the neutral-log lift branch
    assert set(pipeline._wind_residuals(wrf, log)) == set(res) and "wind" not in pipeline._wind_residuals(wrf, {"T0N165W": {"lon": 0, "lat": 0}})
    wrf["T0N165W"]["wind10"] = wrf["T0N165W"]["wind10"] * 0  # a zero model wind: no direction where either speed is below 1 m/s
    assert np.isnan(pipeline._wind_residuals(wrf, moor)["T0N165W"][:, 1]).all()


def ar1_moorings(rng, n_moor=120, n_t=500, persistent=0.9, noise=1.4, tau=6.0, gaps=0.05):
    """Moorings with a known persistent error each (sd `persistent`) and AR(1) noise (sd `noise`, e-folding time `tau` hours), hourly, with gaps."""
    phi = np.exp(-1.0 / tau)
    out = {}
    for i in range(n_moor):
        e = np.empty(n_t)
        e[0] = rng.normal(0, noise)
        w = rng.normal(0, noise * np.sqrt(1 - phi ** 2), n_t)
        for t in range(1, n_t):
            e[t] = phi * e[t - 1] + w[t]
        x = 0.3 + rng.normal(0, persistent) + e
        x[rng.random(n_t) < gaps] = np.nan
        out[f"m{i}"] = x
    return out


def test_the_wind_error_fit_recovers_a_known_persistent_and_short_lived_split_within_20_percent():
    got = pipeline.fit_wind_error(ar1_moorings(np.random.default_rng(7)))
    assert got["persistent"] == pytest.approx(0.9, rel=0.2) and got["noise"] == pytest.approx(1.4, rel=0.2) and got["tau_h"] == pytest.approx(6.0, rel=0.2)
    assert got["moorings"] == 120
    total = np.sqrt(0.9 ** 2 + 1.4 ** 2)                                                           # the old fit held this whole hourly sd fixed per member
    assert got["persistent"] < 0.7 * total


def test_a_different_split_is_recovered_too_and_white_noise_has_no_memory():
    a = pipeline.fit_wind_error(ar1_moorings(np.random.default_rng(11), persistent=0.3, noise=2.0, tau=12.0))
    assert a["persistent"] == pytest.approx(0.3, rel=0.2) and a["noise"] == pytest.approx(2.0, rel=0.2) and a["tau_h"] == pytest.approx(12.0, rel=0.2)
    w = pipeline.fit_wind_error({k: np.random.default_rng(i).normal(0, 1.0, 400) + 0.5 for i, k in enumerate("abcdefghijkl")})   # same mean, white
    assert w["persistent"] < 0.15 and w["noise"] == pytest.approx(1.0, rel=0.1) and w["tau_h"] < 0.5


def test_no_persistent_error_floors_the_spread_at_zero_and_keeps_only_the_uncertainty_of_the_mean():
    """Near-identical means: the dispersion of the means is below its sampling variance, so that difference is floored at 0 and what is left
    is the variance of the fitted mean, var(means) / k: tiny here, but not 0."""
    ramp = np.sin(np.arange(60) / 5.0)
    got = pipeline.fit_wind_error({"a": ramp, "b": ramp + 1e-9, "c": ramp - 1e-9})
    assert 0.0 < got["persistent"] == pytest.approx(np.sqrt(1e-18 / 3), rel=1e-3) and got["noise"] > 0.5


def test_the_persistent_sd_is_never_zero_when_the_moorings_disagree_so_stage_1_gets_no_nan_members():
    # q3 at f78e7ef: 11 moorings whose mean spread was below its sampling variance gave persistent 0.0, scipy's norm(scale=0).ppf gave NaN wind
    # biases for every member and a glider integrated NaN wind into a NaN position. Persistent is now the predictive sd (spread + var of the mean).
    rng = np.random.default_rng(3)
    s = {f"m{i}": rng.normal(0.0, 2.0, 100) + 0.01 * i for i in range(11)}                      # spread of the means far below 2/sqrt(100)
    got = pipeline.fit_wind_error(s)
    means = np.array([np.nanmean(x) for x in s.values()])
    assert got["persistent"] >= np.sqrt(np.var(means, ddof=1) / 11) > 0
    marg = sampling.to_marginals({"wind_speed_bias": dict(dist="normal", mean=-0.6, value=got["persistent"])})
    assert np.isfinite(sampling.lhs(32, marg, 0)[1]["wind_speed_bias"]).all()


def test_fewer_than_two_moorings_with_three_samples_gives_no_split():
    assert pipeline.fit_wind_error({"a": np.arange(10.0)}) is None
    assert pipeline.fit_wind_error({"a": np.arange(10.0), "b": np.array([1.0, np.nan, np.nan, 2.0])}) is None
    assert pipeline.fit_wind_error({}) is None
    const = pipeline.fit_wind_error({"a": np.ones(5), "b": 2 * np.ones(5)})                      # no variation at all: no autocorrelation to speak of
    assert const["tau_h"] == 0.0 and const["rho"] == 0.0 and const["noise"] == 0.0


def test_moorings_outside_the_grid_fail_the_stage_through_its_self_check(tmp_path, data):
    """tao.compare returns {} when no mooring is inside the grid, so there is no `ALL` entry. The stage must then fail through its
    own `tao_moorings_compared` check (a clear StageFailed) and not die on the missing key."""
    ctx, t0, t1 = tao_ctx(tmp_path)
    ctx._env = types.SimpleNamespace(inside=lambda lon, lat: False)
    with pytest.raises(ledger.StageFailed, match="tao_moorings_compared"):
        tao_stage(ctx, t0, t1)
    c = check_of(read_ledger(ctx.run_dir, "ingest"), "tao_moorings_compared")
    assert (c["ok"], c["value"]) == (False, 0)


def test_the_tao_fit_also_sets_the_sst_and_t2_sigmas_that_the_environment_is_tagged_with(tmp_path, data):
    ctx, t0, t1 = tao_ctx(tmp_path)
    prior = (ctx.env.sig["sst_k"], ctx.env.sig["t2_k"])
    d = tao_stage(ctx, t0, t1)
    assert ctx._env is None                                                                                   # rebuilt with the fit on next use
    cmp = json.loads((ctx.run_dir / "ingest" / "tao_compare.json").read_text())
    fit = json.loads((ctx.run_dir / "ingest" / "env_sigmas_fitted.json").read_text())
    assert fit["sst_k"] == pytest.approx(cmp["ALL"]["sst_rmse"]) and fit["sst_k"] != prior[0] and 0.0 < fit["t2_k"] != prior[1]
    # T2: pooled RMSE of WRF T2 against the AIRT of the moorings that report it (T0N165W only), computed independently
    hours = np.arange(t0, t1 + 1, 3600.0)
    m = tao.load_tao(pipeline.DATA / "tao", t0, t1)["T0N165W"]
    lo, la = np.full(hours.size, m["lon"]), np.full(hours.size, m["lat"])
    r = ctx.env.air(lo, la, hours)["T2"].value - tao._bin(m["airt"]["t"], m["airt"]["value"], hours)
    assert fit["t2_k"] == pytest.approx(np.sqrt(np.mean(r[np.isfinite(r)] ** 2)))
    assert d["notes"][0].startswith("env sigmas fitted") and "sst_k" in d["notes"][0] and "t2_k" in d["notes"][0]
    e = ctx.env
    assert e.sig["sst_k"] == fit["sst_k"] and e.sig["t2_k"] == fit["t2_k"] and e.sig["q2_frac"] == config.env_sigmas()["q2_frac"]
    lon, lat = np.array([195.0]), np.array([0.0])
    assert e.sst(lon, lat, t0).uncertainty == fit["sst_k"] and e.air(lon, lat, t0)["T2"].uncertainty == fit["t2_k"]


def test_without_sst_or_air_temperature_in_the_moorings_the_sigmas_stay_the_assumptions(tmp_path, data, monkeypatch):
    real_cmp, real_load = tao.compare, tao.load_tao
    monkeypatch.setattr(tao, "compare", lambda w, m: (lambda r: {**r, "ALL": {**r["ALL"], "sst_rmse": float("nan")}})(real_cmp(w, m)))
    monkeypatch.setattr(tao, "load_tao", lambda *a, **k: {n: {x: y for x, y in v.items() if x != "airt"} for n, v in real_load(*a, **k).items()})
    ctx, t0, t1 = tao_ctx(tmp_path)
    d = tao_stage(ctx, t0, t1)
    assert not (ctx.run_dir / "ingest" / "env_sigmas_fitted.json").exists() and "none" in d["notes"][0]
    assert ctx.env.sig["sst_k"] == config.env_sigmas()["sst_k"] and ctx.env.sig["t2_k"] == config.env_sigmas()["t2_k"]


def test_the_assumptions_text_for_the_sigmas_the_tao_fit_replaces_says_what_the_code_does():
    a = config.assumptions()
    for k in ("env.sigma.t2_k", "env.sigma.sst_k"):
        assert "env_sigmas_fitted.json" in a[k]["why"] and "pipeline._tao" in a[k]["why"]


def test_the_umwm_depth_fallback_is_reachable_from_the_pipeline(tmp_path, data_copy, monkeypatch):
    shutil.rmtree(data_copy / "bathy")
    monkeypatch.setattr(ocean_mod.bathy, "from_gofs", boom)                                                  # GEBCO is gone and the GOFS floor fails
    b = pipeline.ocean(ctx_for(tmp_path / "r")).bathy
    assert b.source == "UMWM depth" and [t.split(":")[0] for t in b.tried] == ["gebco", "gofs"]
    assert float(b(195.0, 0.0).value) == pytest.approx(float(fx.seafloor(195.0, 0.0)), rel=1e-6)
    assert pipeline._umwm_depth(tmp_path / "no_cache") is None


def test_the_mission_switches_reach_the_surface_layer_the_environment_is_built_with(tmp_path, data):
    text = MISSION_PATH.read_text()
    off = tmp_path / "off.yaml"
    off.write_text(text.replace("warm_layer: true, rain_lens: true", "warm_layer: false, rain_lens: false"))
    bare = tmp_path / "bare.yaml"
    bare.write_text(text.replace("subgrid: {turbulence: true, gust_fronts: true, warm_layer: true, rain_lens: true, ocean_sde: true}", "subgrid: {}"))
    for path, warm, lens in ((MISSION_PATH, True, True), (off, False, False), (bare, True, True)):
        sl = ctx_for(tmp_path / path.stem, mission=path).env.subgrid
        assert sl.warm_layer is warm and sl.cfg["rain_lens"]["enabled"] is lens, path.name


# ---------------------------------------------------------------------------------------------------------------- stage 1 wrapper

def fake_run(captured, n=None, **over):
    """stage1.run replaced by a result of the real shape: one Latin-hypercube batch of the mission's priors (the draws the CRN check regenerates),
    two vehicles with one failure mode and one link. `over` replaces keys of the returned dict."""
    def run(mission, env, plan, ledger_, log=print, scales=None, fitted=None):
        captured.update(mission=mission, env=env, plan=plan, ledger=ledger_, scales=scales, fitted=fitted)
        k = plan["batch"] if n is None else n
        marg = stage1.priors_for(mission)[1]
        U, X = sampling.lhs(k, marg, np.random.SeedSequence([int(mission["seed"]), 0]), antithetic=tuple(a for a in stage1.ANTITHETIC if a in marg))
        fail = {"mode": np.arange(k) % 4 == 0}
        streams = ("uas/turb/0", "uas/gust", *(f"iridium/{lk['id']}" for lk in mission["links"] if lk["kind"] == "iridium"))
        seeds = {vid: {st: sampling.member_seed(int(mission["seed"]), 0, st) for st in streams} for vid in ("v", "w")}     # what run_batch used: batch keyed
        res = dict(U=U, X=X, links={"l": dict(success=np.arange(k) % 3 != 0)}, seeds=seeds,
                   vehicles={"v": dict(lon=np.zeros((2, k)), sim=object(), antenna_m=1.0, fail=fail), "w": dict(lon=np.zeros((2, k)), fail=fail)})
        return dict(dict(res=res, summary={"vehicles": {}}, names=list(marg), priors=marg, n=k, certify=k >= 73, n_certify=73), **over)
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
    assert d["notes"][0].startswith("16 members in ") and "certify possible: False (n_certify 73)" in d["notes"][0]
    summary = json.loads((ctx.run_dir / "stage1" / "summary.json").read_text())
    assert "res" not in summary and summary["n"] == 16 and summary["names"] == list(stage1.priors_for(ctx.mission)[1])
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
    first = np.array([t[fail[m]] if m in fail else np.nan for m in range(M)])
    return {"class": cls, "t": t, "lon": lon, "lat": lat, "fail": {"mode": np.array([m in fail for m in range(M)])}, "first": {"mode": first}}


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
        assert len(ws) == 3 and all(w["basis"] == pipeline.BASIS[False] and w["failed_at"] == [] and w["lon"] == -165.0 and w["lat"] == 0.0 for w in ws)
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
    assert {w["basis"] for w in wins["clean"]} == {pipeline.BASIS[False]} and {w["basis"] for w in wins["failed"]} == {pipeline.BASIS[True]}
    # round 3 M-10: the numbers are the analysis field at the failed members' tracks, and the page must not say they are what the failed members met
    assert "analysis-field" in pipeline.BASIS[True] and "before the member perturbations" in pipeline.BASIS[True]
    assert all(w["failed_at"] == [float(t[120]), float(t[120])] for w in wins["failed"]) and all(w["failed_at"] == [] for w in wins["clean"])
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


def test_a_calibrating_run_leaves_the_tracked_config_alone_and_later_stages_read_its_own_file(tmp_path, monkeypatch):
    """Round 3 M-23: stage 3 rewrote config/subgrid.json, which code_digest hashes: the next `run` found every stage out of date, stage 1 reran with the new
    calibration and the tree was left dirty. The calibration is now stage3/subgrid_calibration.json (a hashed output); stages after stage 3 read it."""
    from cafe.pm.env import subgrid
    from cafe.pm.stage3 import pipeline_windows as pw
    shipped = subgrid._CFG_DIR / "subgrid.json"
    before, digest = shipped.read_bytes(), pipeline.code_digest()
    ctx = ctx_for(tmp_path / "r")
    ctx.path("windows", "windows.json").write_text(json.dumps({"usv": [dict(t=1.0, stress=2.0, lon=-165.0, lat=0.0, basis="b")]}))
    cal = dict(subgrid.load_config()["calibration"], sigma_u_over_ustar=2.9)
    monkeypatch.setattr(subgrid, "recalibrate", lambda series: dict(calibration=cal, uncertainty=dict(sigma_u_over_ustar=0.2, length_scale_factor=0.1),
                                                                    windows=[dict(label="w")], skipped=[]))

    def run(c, w, L):
        pw.recalibrate_subgrid(c, {"usv": [dict(stage3_row(), part="hull", t=1.0, inflow_series=dict(u=[1.0], dt=1.0, U=6.0, ustar=0.3, z=10.0))]}, L)
        return {"usv": [stage3_row()]}
    fake_module(monkeypatch, "cafe.pm.stage3.pipeline_windows", run=run, recalibrate_subgrid=pw.recalibrate_subgrid)
    d = run_stage(pipeline.s_stage3, ctx, "stage3")
    assert [pathlib.Path(o["path"]).name for o in d["outputs"]] == ["windows.json", "subgrid_calibration.json"]
    assert shipped.read_bytes() == before and pipeline.code_digest() == digest and ledger.done(ctx.run_dir, "stage3", ctx.hash)      # resume: up to date
    # stage 3 itself ran on the shipped one
    assert subgrid.load_config()["calibration"]["source_run"] is None
    with ledger.Ledger(ctx.run_dir, "refit", ctx.hash) as L:
        pipeline.use_run_calibration(ctx, L)
    assert subgrid.load_config()["calibration"]["sigma_u_over_ustar"] == 2.9 and L.d["inputs"][0]["ref"].endswith("stage3/subgrid_calibration.json")
    # a new Context starts from the shipped one
    ctx2 = ctx_for(tmp_path / "r")
    assert subgrid.load_config()["calibration"]["source_run"] is None and ctx2.hash == ctx.hash


def test_without_a_calibration_file_the_stages_after_stage_3_use_the_shipped_one(tmp_path):
    from cafe.pm.env import subgrid
    ctx = ctx_for(tmp_path / "r")
    subgrid.use_calibration(dict(source_run="leftover"))
    with ledger.Ledger(ctx.run_dir, "refit", ctx.hash) as L:
        pipeline.use_run_calibration(ctx, L)
    assert subgrid.load_config()["calibration"]["source_run"] is None and L.d["inputs"] == []


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
    assert u["used"] and u["drag"]["windows"] == 1 and u["drag"]["mean"] == pytest.approx(1.3)
    assert u["drag"]["sigma_statistical"] == pytest.approx(0.05)
    assert u["drag"]["sigma"] > u["drag"]["sigma_statistical"]                                  # the floors add to the standard error
    assert u["drag"]["change_vs_hangar"] == pytest.approx(0.3)
    g = out["glider_eq"]
    why = "no body window passed its stage-3 self-checks; Stage 1 keeps the baseline model coefficients (analytic; no Hangar CFD run)"
    assert g == dict(used=False, reason=why, failed_checks=["mach_max", "wall_model"])
    assert out["uas"]["used"] is False and out["uas"]["failed_checks"] == [] and check_of(d, "refit_uses_only_windows_that_passed")["ok"]


def test_a_usv_wing_is_pooled_apart_from_its_hull_and_never_scales_stage1(tmp_path):
    rows = {"usv": [dict(stage3_row(cd=1.3), part="hull"), dict(stage3_row(cd=3.0), part="wing")]}
    u = refit_run(tmp_path, rows)[0]["usv"]
    assert u["used"] and u["part"] == "hull" and u["drag"]["windows"] == 1 and u["drag"]["mean"] == pytest.approx(1.3)
    assert u["wing_not_used"]["drag"]["mean"] == pytest.approx(3.0) and "no multiplier" in u["wing_not_used"]["reason"]
    rows = {"usv": [dict(stage3_row(cd=3.0), part="wing"), dict(stage3_row(ok=False), part="hull")]}
    u = refit_run(tmp_path / "2", rows)[0]["usv"]
    assert u["used"] is False and u["reason"].startswith("no hull window passed")                  # a passing wing cannot stand in for the hull


def test_a_passing_hull_fs_window_sets_the_usv_multiplier_ahead_of_the_viscous_hull(tmp_path):
    """Stage 1's multiplier scales the whole through-water resistance (speed ~ drag^-1/2 at fixed force), so the windows that include the
    free surface's wave-making set it; the viscous `hull` and the `wing` are reported apart."""
    rows = {"usv": [dict(stage3_row(cd=1.3), part="hull"), dict(stage3_row(cd=2.0, spread=0.1), part="hull_fs"), dict(stage3_row(cd=3.0), part="wing")]}
    u = refit_run(tmp_path, rows)[0]["usv"]
    assert u["used"] and u["part"] == "hull_fs" and u["drag"]["windows"] == 1 and u["drag"]["mean"] == pytest.approx(2.0)
    assert u["drag"]["sigma_statistical"] == pytest.approx(0.1) and u["drag"]["sigma"] > u["drag"]["sigma_statistical"]
    assert u["drag"]["change_vs_hangar"] == pytest.approx(1.0)
    assert u["hull_not_used"]["drag"]["mean"] == pytest.approx(1.3) and "hull_fs windows" in u["hull_not_used"]["reason"]
    assert u["wing_not_used"]["drag"]["mean"] == pytest.approx(3.0) and "no multiplier" in u["wing_not_used"]["reason"]
    two = {"usv": [dict(stage3_row(cd=1.8, spread=0.1), part="hull_fs"), dict(stage3_row(cd=2.2, spread=0.1), part="hull_fs"),
                   dict(stage3_row(cd=1.3), part="hull")]}
    assert refit_run(tmp_path / "2", two)[0]["usv"]["drag"]["windows"] == 2                      # every passing hull_fs window is pooled


def test_without_a_passing_hull_fs_window_the_viscous_hull_still_sets_the_usv_multiplier(tmp_path):
    bad_fs = dict(stage3_row(ok=False, cd=9.0, checks=[pm_run.check_row("fs_refinement_ratio", 1.15, 1.3, False)]), part="hull_fs")
    rows = {"usv": [dict(stage3_row(cd=1.3), part="hull"), bad_fs]}
    u = refit_run(tmp_path, rows)[0]["usv"]
    assert u["used"] and u["part"] == "hull" and u["drag"]["mean"] == pytest.approx(1.3)           # the failed free-surface row (cd 9) is not used
    assert u["hull_fs_not_used"]["reason"].startswith("no hull_fs window passed") and "drag" not in u["hull_fs_not_used"]
    both_bad = {"usv": [dict(stage3_row(ok=False), part="hull"), bad_fs]}
    u2 = refit_run(tmp_path / "2", both_bad)[0]["usv"]
    assert u2["used"] is False and u2["reason"].startswith("no hull window passed") and u2["failed_checks"] == ["fs_refinement_ratio", "mach_max"]
    only_fs = {"usv": [bad_fs]}
    assert refit_run(tmp_path / "3", only_fs)[0]["usv"]["reason"].startswith("no hull_fs window passed")
    ci = refit_run(tmp_path / "4", rows, refit_iterations=0)[0]["usv"]
    assert ci == dict(used=False, reason="budget ci: no refit")


def test_the_refit_multiplier_is_the_pooled_ratio_to_each_windows_own_hangar_value(tmp_path):
    """Each row carries the coefficient the vehicle's Stage-1 model implies at that window's speed (`cd_hangar`), so two windows that
    both read 1.0 times their own hangar value give a multiplier of 1.0 even though their hangar values differ."""
    rows = {"usv": [stage3_row(cd=1.0, hangar=1.0, spread=0.05), stage3_row(cd=1.4, hangar=1.4, spread=0.07)]}
    out, _ = refit_run(tmp_path, rows)
    assert out["usv"]["used"] and out["usv"]["drag"]["windows"] == 2
    assert out["usv"]["drag"]["mean"] == pytest.approx(1.0, abs=1e-9) and out["usv"]["drag"]["change_vs_hangar"] == pytest.approx(0.0, abs=1e-9)


STAGE1_X = {"usv_vpp_bias": np.linspace(-0.2, 0.2, 8), "wind_speed_bias": np.linspace(-1.0, 1.0, 8)}


def stage1_files(ctx):
    ctx.path("stage1", "res.pkl").write_bytes(pickle.dumps(dict(X=STAGE1_X, vehicles={})))
    ctx.path("stage1", "summary.json").write_text('{"n": 8}')


SENS_CASE = {"usv": [dict(case="usv_vpp_bias uniform [-0.35, -0.3] (usv_vpp_bias_brief)", k_fail=30, n=32, verdict="NO-GO", note="brief")]}
SENS_NOTE = "sensitivity case (brief VPP bias, same members and inputs, only usv_vpp_bias replaced): usv 30 of 32 NO-GO"


@pytest.fixture
def sens(monkeypatch):
    """stage1.sensitivity_case stood in by a fixed result; -> the list of calls (mission vehicle ids, prior, n, scales, X)."""
    calls = []

    def fake(mission, env, prior, n, fitted, scales, X=None):
        calls.append(([v["id"] for v in mission["vehicles"]], prior, n, scales, X))
        return SENS_CASE
    monkeypatch.setattr(pipeline.stage1, "sensitivity_case", fake)
    return calls


def test_stage1b_is_a_copy_of_stage1_when_no_vehicle_was_refit(tmp_path, monkeypatch, sens):
    ctx = ctx_for(tmp_path / "r")
    stage1_files(ctx)
    ctx.path("refit", "refit.json").write_text(json.dumps({"usv": dict(used=False, reason="x"), "uas": dict(used=False, reason="y")}))
    monkeypatch.setattr(pipeline, "_stage1", boom)
    d = run_stage(pipeline.s_stage1b, ctx, "stage1b")
    assert d["notes"][0] == SENS_NOTE and len(d["notes"]) == 2          # round 6 M-17: the copy note now also says the sensitivity case ran (test below)
    assert d["notes"][1].startswith("no vehicle was refit: stage 1b is stage 1 (copied, not rerun)")
    assert (ctx.run_dir / "stage1b" / "res.pkl").read_bytes() == (ctx.run_dir / "stage1" / "res.pkl").read_bytes()
    # stage 1's summary plus the passes done
    assert json.loads((ctx.run_dir / "stage1b" / "summary.json").read_text()) == dict(n=8, refit_iterations_performed=0)
    assert [pathlib.Path(o["path"]).name for o in d["outputs"]] == ["sensitivity_cases.json", "res.pkl", "summary.json"]
    assert d["inputs"][0]["ref"].endswith("refit/refit.json") and d["inputs"][1]["ref"].endswith("stage1/res.pkl")
    c = check_of(d, "refit_iterations_within_cap")
    assert c["ok"] and c["value"] == 0 and c["limit"] == 0 and "single pass" in c["note"]  # the ci budget allows none and none was done


def test_stage1b_stores_the_usv_verdict_under_the_briefs_vpp_bias_where_the_report_reads_it(tmp_path, monkeypatch, sens):
    ctx = ctx_for(tmp_path / "r")
    stage1_files(ctx)
    entry = dict(used=True, drag=dict(mean=1.3, sigma=0.05, windows=1))
    ctx.plan["refit_iterations"] = 2
    ctx.path("refit", "refit.json").write_text(json.dumps({"usv": entry, "uas": dict(used=False, reason="y")}))
    monkeypatch.setattr(pipeline, "_stage1", summaries(ctx, {"usv": "NO-GO", "uas": "GO"}))
    run_stage(pipeline.s_stage1b, ctx, "stage1b")
    (ids, prior, n, scales, X), = sens                                                         # the run's own hypercube, its n: a paired comparison (M-15)
    assert ids == [v["id"] for v in ctx.mission["vehicles"]] and prior == pipeline.stage1.BRIEF_PRIOR and scales == {"usv": entry}
    assert n == 8 and set(X) == set(STAGE1_X) and all(np.array_equal(X[k], STAGE1_X[k]) for k in X)
    assert json.loads((ctx.run_dir / "stage1b" / report.SENSITIVITY).read_text()) == SENS_CASE


def test_a_mission_without_a_usv_runs_no_sensitivity_case(tmp_path, monkeypatch, sens):
    ctx = ctx_for(tmp_path / "r")
    ctx.mission = dict(ctx.mission, vehicles=[v for v in ctx.mission["vehicles"] if pipeline.stage1._classes(ctx.mission)[v["id"]] != "usv"])
    stage1_files(ctx)
    ctx.path("refit", "refit.json").write_text(json.dumps({}))
    monkeypatch.setattr(pipeline, "_stage1", boom)
    d = run_stage(pipeline.s_stage1b, ctx, "stage1b")
    assert sens == [] and not (ctx.run_dir / "stage1b" / report.SENSITIVITY).exists() and SENS_NOTE not in d["notes"]


def summaries(ctx, was, now=None):
    """stage 1's summary.json with the verdicts `was`; the stand-in for _stage1 writes stage 1b's with `now`."""
    def doc(v):
        return json.dumps({"summary": {"vehicles": {k: {"verdict": x} for k, x in v.items()}}})
    ctx.path("stage1", "summary.json").write_text(doc(was))

    def fake(c, L, name, scales=None, extra=None):
        c.path("stage1b", "summary.json").write_text(doc(now or was))
    return fake


def test_stage1b_reruns_stage1_with_the_multipliers_of_the_vehicles_that_were_refit(tmp_path, monkeypatch, sens):
    ctx = ctx_for(tmp_path / "r")
    entry = dict(used=True, drag=dict(mean=1.3, sigma=0.05, windows=1))
    stage1_files(ctx)
    ctx.plan["refit_iterations"] = 2
    ctx.path("refit", "refit.json").write_text(json.dumps({"usv": entry, "uas": dict(used=False, reason="y")}))
    seen = []
    inner = summaries(ctx, {"usv": "NO-GO", "uas": "GO"})

    def spy(c, L, name, scales=None, extra=None):
        seen.append((c, name, scales, extra))
        inner(c, L, name, scales, extra)
    monkeypatch.setattr(pipeline, "_stage1", spy)
    d = run_stage(pipeline.s_stage1b, ctx, "stage1b")
    assert seen == [(ctx, "stage1b", {"usv": entry}, dict(refit_iterations_performed=1))] and d["notes"] == [SENS_NOTE]
    c = check_of(d, "stage1b_same_vehicles_as_stage1")
    assert c["ok"] and c["value"] == 0 and c["note"] == "verdict changes after the refit: none (converged after one rerun)"
    c = check_of(d, "refit_iterations_within_cap")
    assert c["ok"] and c["value"] == 1 and c["limit"] == 2                                      # one pass done of the two the plan allows


def test_stage1b_lists_the_verdict_changes_the_refit_made(tmp_path, monkeypatch, sens):
    ctx = ctx_for(tmp_path / "r")
    stage1_files(ctx)
    ctx.plan["refit_iterations"] = 2
    ctx.path("refit", "refit.json").write_text(json.dumps({"usv": dict(used=True, drag=dict(mean=1.3, sigma=0.05, windows=1)), "uas": dict(used=False)}))
    monkeypatch.setattr(pipeline, "_stage1", summaries(ctx, {"usv": "NO-GO", "uas": "GO"}, {"usv": "MARGINAL", "uas": "GO"}))
    c = check_of(run_stage(pipeline.s_stage1b, ctx, "stage1b"), "stage1b_same_vehicles_as_stage1")
    assert c["ok"] and c["value"] == 1 and c["note"] == "verdict changes after the refit: usv: NO-GO -> MARGINAL"


def test_stage1b_fails_when_the_rerun_has_other_vehicles_than_stage_1(tmp_path, monkeypatch, sens):
    ctx = ctx_for(tmp_path / "r")
    stage1_files(ctx)
    ctx.plan["refit_iterations"] = 2
    ctx.path("refit", "refit.json").write_text(json.dumps({"usv": dict(used=True, drag=dict(mean=1.3, sigma=0.05, windows=1))}))
    monkeypatch.setattr(pipeline, "_stage1", summaries(ctx, {"usv": "NO-GO", "uas": "GO"}, {"usv": "NO-GO"}))
    with pytest.raises(ledger.StageFailed, match="stage1b_same_vehicles_as_stage1"):
        run_stage(pipeline.s_stage1b, ctx, "stage1b")


def test_a_refit_pass_the_plan_does_not_allow_fails_the_stage(tmp_path, monkeypatch, sens):
    """The cap check compared two constants (2 and 2) and could not fail. It now compares the passes performed with the cap: the ci plan allows none."""
    ctx = ctx_for(tmp_path / "r")
    stage1_files(ctx)
    assert ctx.plan["refit_iterations"] == 0 and ctx.plan["refit_iterations_max"] == 0                  # budget ci
    ctx.path("refit", "refit.json").write_text(json.dumps({"usv": dict(used=True, drag=dict(mean=1.3, sigma=0.05, windows=1)), "uas": dict(used=False)}))
    monkeypatch.setattr(pipeline, "_stage1", summaries(ctx, {"usv": "NO-GO", "uas": "GO"}))
    with pytest.raises(ledger.StageFailed, match="refit_iterations_within_cap"):
        run_stage(pipeline.s_stage1b, ctx, "stage1b")
    c = check_of(read_ledger(ctx.run_dir, "stage1b"), "refit_iterations_within_cap")
    assert not c["ok"] and (c["value"], c["limit"]) == (1, 0)


def test_the_refit_module_caps_the_passes_whatever_the_plan_says(tmp_path, monkeypatch, sens):
    from cafe.pm.stage3 import refit
    ctx = ctx_for(tmp_path / "r")
    stage1_files(ctx)
    ctx.plan["refit_iterations"] = 5
    ctx.path("refit", "refit.json").write_text(json.dumps({}))
    d = run_stage(pipeline.s_stage1b, ctx, "stage1b")
    c = check_of(d, "refit_iterations_within_cap")
    assert c["ok"] and c["limit"] == refit.MAX_ITER == min(5, refit.MAX_ITER)


def test_the_plan_names_the_refit_cap_and_the_stage_1b_summary_the_passes_done(tmp_path):
    ctx = ctx_for(tmp_path / "r", "quick")
    assert ctx.plan["refit_iterations_max"] == ctx.plan["refit_iterations"] == 2


# ---------------------------------------------------------------------------------------------------------------- emulator

def set_stage1_wall(run, wall_s):
    p = run / "checkpoints" / "stage1" / "ledger.json"
    d = json.loads(p.read_text())
    p.write_text(json.dumps(dict(d, wall_s=wall_s)))


def synthetic_ctx(tmp_path, M, name="synthetic", unused_refit=False, stage1_wall=0.0):
    """The synthetic run of tests/fixtures/pm_run on the TEPEX mission with the analytic environment; `unused_refit`: no vehicle was refit;
    `stage1_wall`: the seconds the stage-1 ledger says it took (0: unknown, so the planner's cost estimate is used)."""
    run = tmp_path / name
    pm_run.make_run(run, M=M)
    set_stage1_wall(run, stage1_wall)
    if unused_refit:
        ref = json.loads((run / "refit" / "refit.json").read_text())
        (run / "refit" / "refit.json").write_text(json.dumps({k: dict(v, used=False) for k, v in ref.items()}))
    ctx = pipeline.Context(ROOT / "missions" / "tepex_c_demo.yaml", "quick", 0, run, quiet)
    ctx._env = AnalyticEnv(wind=(4.0, 3.0), hs=1.5, current=(0.2, 0.0))
    return ctx


def cheap_plan(ctx, budget_s=100.0):
    """One second per vehicle per mission day and nothing per member: a batch of the four vehicles costs 4 s x days; `days` = 1."""
    ctx.plan.update(budget_s=budget_s, days=1.0, batch=16)
    ctx.plan["member_cost"] = {v: dict(s_per_batch_day=1.0, s_per_member_day=0.0, source="test") for v in ctx.plan["member_cost"]}
    return ctx


@pytest.fixture
def table(tmp_path, monkeypatch):
    """The training table in a private CAFE_DATA, never the shared tree."""
    d = tmp_path / "caf_data"
    monkeypatch.setattr(pipeline, "DATA", d)
    return d / "emulator" / "train.parquet"


@pytest.fixture
def fake_stage1(monkeypatch):
    """stage1.run_batch replaced by the synthetic ensemble of tests/fixtures/pm_run; a vehicle the variant changed has no failures, so every
    change 'fixes' it. -> the list of (vehicles run, members) it was called with."""
    names = list(stage1.priors_for(config.load_mission(ROOT / "missions" / "tepex_c_demo.yaml"))[1])
    calls = []

    def run_batch(mission, env, members, seed, pri, marg, scales=None):
        calls.append(([v["id"] for v in mission["vehicles"]], list(members)))
        b = pm_run._batch(np.random.default_rng(len(calls)), len(members), names, 0.4)
        for v in mission["vehicles"]:
            if v != next(x for x in pm_run.mission()["vehicles"] if x["id"] == v["id"]):
                for f in b["vehicles"][v["id"]]["fail"].values():
                    f[:] = False
        return b
    monkeypatch.setattr(stage1, "run_batch", run_batch)
    return calls


def seed_table(path, n=140, bad=False, seed=0):
    """Glider rows made by tests/test_whatif.storm_table (or pure noise when `bad`): test data, as the pipeline never trains on synthetic rows."""
    from cafe.pm import whatif
    from tests import test_whatif
    df = test_whatif.storm_table(n, seed)
    if bad:
        df["p_fail"] = np.random.default_rng(3).uniform(0, 1, n)
    whatif.add_rows(path, [dict(r, key=f"seed{i}", run_id="seed", mission="seed", variant="seed", n_members=512, code_digest=pipeline.code_digest())
                           for i, r in enumerate(df.to_dict("records"))])


def test_every_run_appends_one_row_per_vehicle_and_a_rerun_replaces_them(tmp_path, table, fake_stage1):
    from cafe.pm import whatif
    a = synthetic_ctx(tmp_path, 48, "a")
    cheap_plan(a, 10.0)                                                                                       # no budget for variants: the rows of the run only
    run_stage(pipeline.s_emulator, a, "emulator")
    df = whatif.read_table(table)
    assert len(df) == 4 and sorted(df["vehicle"]) == ["glider_2n", "glider_eq", "uas", "usv"] and set(df["variant"]) == {"base"} and fake_stage1 == []
    g = df[df["vehicle"] == "glider_eq"].iloc[0]
    assert g["fidelity"] == 1 and g["n_members"] == 48 and g["mission"] == "tepex_c_demo" and g["git_sha"] and len(g["code_digest"]) == 64
    assert df[df["vehicle"] == "usv"].iloc[0]["fidelity"] == 0                                                # only glider_eq was refit
    run_stage(pipeline.s_emulator, a, "emulator")
    assert len(whatif.read_table(table)) == 4                                                                  # same run: replaced, not doubled
    b = synthetic_ctx(tmp_path, 48, "b")
    cheap_plan(b, 10.0)
    run_stage(pipeline.s_emulator, b, "emulator")
    df = whatif.read_table(table)
    assert len(df) == 4 and df["run_id"].nunique() == 1      # the same mission again (any directory) replaces its rows


def test_the_variant_runs_stay_inside_the_emulator_share(tmp_path, table, fake_stage1):
    """Share = 5 % of the budget plus stage 1b's 15 % when nothing was refit; 70 % of it for variants; a variant costs 4 s here."""
    from cafe.pm import whatif
    ctx = cheap_plan(synthetic_ctx(tmp_path, 48, unused_refit=True), 100.0)                                    # share 20 s -> 14 s -> 3 variants
    d = run_stage(pipeline.s_emulator, ctx, "emulator")
    design = json.loads((ctx.run_dir / "emulator" / "design.json").read_text())
    est = budget.batch_cost_s(ctx.plan)
    assert est == 4.0 and design["share_s"] == 20.0 and design["stage1b_free"] and len(design["variants"]) == 3
    assert len(design["variants"]) * est <= whatif.TRAIN_FRAC * design["share_s"]
    assert design["variant_s"] == est and design["variant_s_source"].startswith("the planner's estimate")
    assert design["rows_added"] == 4 * 4 and design["table_rows"] == 16 and design["planned_variants"] == 3
    assert design["spent_s"] == 3 * est                                                                        # charged at the plan's cost, not the clock
    # round 3 M-4: every variant runs its own members, not the baseline's that every variant used to share; round 7 M-7: and none stage 1b used (48 here)
    assert [c[1] for c in fake_stage1][:3] == [list(range(16 * (3 + k), 16 * (4 + k))) for k in range(3)]
    assert [c[0] for c in fake_stage1][:3] == [["glider_eq", "glider_2n", "usv", "uas"]] * 3
    assert check_of(d, "emulator_rows_appended")["value"] == 16 and "emulator_variants_within_share" not in [c["name"] for c in d["checks"]]   # round 5 M-13
    assert any("3 variant run(s) of 4 s each (the planner's estimate" in n for n in d["notes"]) and any("stage 1b's share included" in n for n in d["notes"])
    refit = cheap_plan(synthetic_ctx(tmp_path, 48, "refit"), 100.0)                                            # glider_eq was refit: share 5 s -> none
    run_stage(pipeline.s_emulator, refit, "emulator")
    d2 = json.loads((refit.run_dir / "emulator" / "design.json").read_text())
    assert d2["share_s"] == 5.0 and d2["variants"] == [] and not d2["stage1b_free"] and d2["rows_added"] == 4


def test_a_measured_stage_1_wall_time_does_not_size_the_variants(tmp_path, table, fake_stage1):
    """Variants are priced by the planner (4 s a batch here), whatever stage 1 happened to take: 24 s or 96 s of it give the same three variants."""
    designs = []
    for name, wall in (("fast", 24.0), ("slow", 96.0)):
        ctx = cheap_plan(synthetic_ctx(tmp_path, 48, name, unused_refit=True, stage1_wall=wall), 100.0)
        run_stage(pipeline.s_emulator, ctx, "emulator")
        designs.append(json.loads((ctx.run_dir / "emulator" / "design.json").read_text()))
    assert [d["variant_s"] for d in designs] == [4.0, 4.0] and [len(d["variants"]) for d in designs] == [3, 3]
    assert [v["mods"] for v in designs[0]["variants"]] == [v["mods"] for v in designs[1]["variants"]]


def test_the_emulator_sizes_are_in_plan_json_before_any_stage_runs(tmp_path):
    ctx = ctx_for(tmp_path / "r")
    plan = json.loads(json.dumps(ctx.plan, default=ledger._jsonable))
    assert plan["emulator"] == json.loads(json.dumps(budget.emulator_plan(ctx.plan))) and plan["emulator"]["max_variants"] == budget.EMULATOR_VARIANTS["ci"]
    st = plan["stage3"]
    assert st == json.loads(json.dumps(budget.stage3_plan(ctx.plan, ctx.classes, budget.stage3_assumptions()), default=ledger._jsonable))
    assert set(st["cell_steps_per_part"]) == {"glider", "usv", "uas"} and st["fs"]["cases"] == 1
    # M-8: on CPU no LES window runs, so stage 3 keeps only what its free-surface case fits of the 0.3 x 600 s (the rest went to stage 1)
    assert st["share_s"] == pytest.approx(plan["shares"]["stage3"] * 600) and st["share_s"] < 0.3 * 600 and plan["shares"]["stage1"] > budget.SHARE["stage1"]


def test_variant_count_is_capped_by_the_budget_name_and_the_clock_is_only_a_kill_at_the_whole_share(tmp_path, table, fake_stage1, monkeypatch):
    ctx = cheap_plan(synthetic_ctx(tmp_path, 48, unused_refit=True), 10_000.0)
    ctx.plan["budget"] = "ci"
    run_stage(pipeline.s_emulator, ctx, "emulator")
    design = json.loads((ctx.run_dir / "emulator" / "design.json").read_text())
    assert len(design["variants"]) == budget.EMULATOR_VARIANTS["ci"] == 2 and design["killed"] is None
    ctx = cheap_plan(synthetic_ctx(tmp_path, 48, "slow", unused_refit=True), 100.0)
    clock = iter([0.0] + [1e6] * 400)  # the stage starts its clock, then the whole share is gone
    monkeypatch.setattr(pipeline.time, "perf_counter", lambda: next(clock))
    d = run_stage(pipeline.s_emulator, ctx, "emulator")
    design = json.loads((ctx.run_dir / "emulator" / "design.json").read_text())
    assert design["variants"] == [] and design["planned_variants"] == 3 and design["killed"]["at_variant"] == 0
    assert design["killed"]["reason"].startswith("killed: the variant runs spent the emulator stage's whole wall-clock share (20 s) before variant v0 of 3")
    assert any(n.startswith("killed:") for n in d["notes"])


def test_the_emulator_is_not_trained_on_a_few_rows_and_the_stage_still_passes(tmp_path, table, fake_stage1):
    ctx = cheap_plan(synthetic_ctx(tmp_path, 48))
    d = run_stage(pipeline.s_emulator, ctx, "emulator")
    out = json.loads((ctx.run_dir / "emulator" / "holdout.json").read_text())
    assert set(out) == {"glider_eq", "glider_2n", "usv", "uas"} and all(not v["trained"] for v in out.values())
    assert out["glider_eq"]["reason"].startswith("2 glider rows in the training table") and out["glider_eq"]["rows"] == 2
    assert out["usv"]["cls"] == "usv" and out["glider_eq"] == out["glider_2n"]
    assert [c["name"] for c in d["checks"]] == ["emulator_rows_appended"] and all(c["ok"] for c in d["checks"])
    assert any("not trained (trained: false)" in n and "glider" in n for n in d["notes"]) and len([n for n in d["notes"] if "not trained" in n]) == 3
    flip = json.loads((ctx.run_dir / "emulator" / "flip.json").read_text())["vehicles"]
    assert set(flip) == {"usv", "uas"}                                                                         # the two vehicles that are not GO


def test_the_flip_search_of_the_stage_falls_back_to_stage_1_and_finds_a_change(tmp_path, table, fake_stage1):
    ctx = cheap_plan(synthetic_ctx(tmp_path, 48))
    d = run_stage(pipeline.s_emulator, ctx, "emulator")
    flip = json.loads((ctx.run_dir / "emulator" / "flip.json").read_text())["vehicles"]
    u = flip["uas"]
    assert u["found"] and not u["emulator"] and u["best"]["method"] == "Stage 1" and u["best"]["verdict"] == "GO" and u["best"]["n"] == 16
    assert u["verdict"] == "NO-GO"
    assert [t["change"] for t in u["tried"] if t["method"] == "Stage 1"][0] == u["best"]["change"]
    assert any("flip search: 2 of 2 non-GO vehicles flip" in n for n in d["notes"])
    assert len(fake_stage1) >= 2


def test_a_trained_emulator_is_scored_and_held_to_the_briefs_acceptance(tmp_path, table, fake_stage1, monkeypatch):
    from cafe.pm import whatif
    seed_table(table)
    monkeypatch.setattr(whatif, "LIMITS", dict(rmse=0.05, coverage=0.5, query_ms=1e9))     # coverage on 28 test rows is too coarse to pin to +-5 %
    ctx = cheap_plan(synthetic_ctx(tmp_path, 48))
    d = run_stage(pipeline.s_emulator, ctx, "emulator")
    out = json.loads((ctx.run_dir / "emulator" / "holdout.json").read_text())
    g = out["glider_eq"]
    assert g["trained"] and g["cls"] == "glider" and g["rows"] == 142 and g["n_test"] == 28 and g["rmse"]["p_fail"] <= 0.05 and not out["usv"]["trained"]
    assert out["glider_2n"] == g and g["acceptance"] == dict(rmse_ok=True, coverage_ok=True, query_ok=True)
    assert g["used"] is True and g["unused_reason"] is None
    assert not [c for c in d["checks"] if c["name"].startswith(("emulator_rmse", "emulator_coverage", "emulator_query"))]
    notes = [n for n in d["notes"] if n.startswith("emulator glider: BRIEF 2.7")]
    assert [n.split(":")[1].strip() for n in notes] == ["BRIEF 2.7 RMSE met", "BRIEF 2.7 coverage met", "BRIEF 2.7 query time met"]
    assert "Monte-Carlo noise" in notes[0]


def test_a_trained_emulator_that_misses_the_acceptance_is_noted_not_used_and_does_not_fail_the_stage(tmp_path, table, fake_stage1):
    """Follow-up to round 4 M-3: the BRIEF 2.7 gates are a statistical draw on 28 held-out points; a miss used to abort the run after stages 1 to 3."""
    seed_table(table, bad=True)                                                                          # pure noise: the RMSE gate is missed by a wide margin
    ctx = cheap_plan(synthetic_ctx(tmp_path, 48))
    d = run_stage(pipeline.s_emulator, ctx, "emulator")                                                  # no StageFailed
    assert not [c for c in d["checks"] if c["name"].startswith(("emulator_rmse", "emulator_coverage", "emulator_query"))]
    assert all(c["ok"] for c in d["checks"]) and {"emulator_training_points_glider", "emulator_range_guard_glider"} <= {c["name"] for c in d["checks"]}
    rm = next(n for n in d["notes"] if n.startswith("emulator glider: BRIEF 2.7 RMSE"))
    assert rm.startswith("emulator glider: BRIEF 2.7 RMSE MISSED: 0.") and "against the limit 0.05" in rm
    cov = next(n for n in d["notes"] if n.startswith("emulator glider: BRIEF 2.7 coverage "))
    assert "misses this by chance with probability" in cov and "held-out points" in cov
    why = "the glider emulator missed BRIEF 2.7 acceptance (RMSE"
    assert any(n.startswith(f"emulator glider not used for answers: {why}") and n.endswith("so Stage 1 answers") for n in d["notes"])
    g = json.loads((ctx.run_dir / "emulator" / "holdout.json").read_text())["glider_eq"]
    assert g["trained"] and g["used"] is False and g["unused_reason"].startswith(why) and g["acceptance"]["rmse_ok"] is False
    flip = json.loads((ctx.run_dir / "emulator" / "flip.json").read_text())["vehicles"]
    assert flip and all(not f["emulator"] for f in flip.values())                                          # Stage 1 answered the flip search
    hold = json.loads((ctx.run_dir / "emulator" / "holdout.json").read_text())
    assert all(t["reason"].startswith(hold[vid]["unused_reason"]) for vid, f in flip.items() for t in f["tried"] if not t["invalid"])  # holdout.json's reason
    assert len(fake_stage1) >= 2


def test_a_missed_coverage_gate_alone_completes_the_run_with_a_note_that_gives_the_chance_of_missing_it(tmp_path, table, fake_stage1, monkeypatch):
    from cafe.pm import whatif
    seed_table(table)
    monkeypatch.setattr(whatif, "LIMITS", dict(rmse=0.5, coverage=0.0, query_ms=1e9))     # coverage must be exactly nominal: missed by any hold-out
    ctx = cheap_plan(synthetic_ctx(tmp_path, 48))
    d = run_stage(pipeline.s_emulator, ctx, "emulator")
    assert not [c for c in d["checks"] if c["name"].startswith("emulator_coverage")]
    n = next(n for n in d["notes"] if n.startswith("emulator glider: BRIEF 2.7 coverage MISSED: "))
    assert re.fullmatch(r"emulator glider: BRIEF 2\.7 coverage MISSED: 0\.\d{3} against 0\.90 \+- 0\.0; a calibrated emulator misses this by chance with "
                        r"probability 1\.000 on 28 held-out points", n), n
    g = json.loads((ctx.run_dir / "emulator" / "holdout.json").read_text())["glider_eq"]
    assert g["used"] is False and "(coverage)" in g["unused_reason"]


def holdout_rows(ctx, vid="glider_eq"):
    return json.loads((ctx.run_dir / "emulator" / "holdout.json").read_text())[vid]["rows"]


def test_the_emulator_trains_on_the_table_as_the_stage_found_it_and_this_runs_rows_come_after(tmp_path, table, fake_stage1):
    from cafe.pm import whatif
    seed_table(table)
    start = whatif.read_table(table)
    a = cheap_plan(synthetic_ctx(tmp_path, 48, "a"), 10.0)  # no budget for variants: the two glider rows of the run
    run_stage(pipeline.s_emulator, a, "emulator")
    snap = whatif.read_table(a.run_dir / "emulator" / "train_input.parquet")
    assert snap.equals(start) and holdout_rows(a) == 142                                                       # 140 from the table + glider_eq + glider_2n
    assert len(whatif.read_table(table)) == 144                                                                # appended after the fit
    run_stage(pipeline.s_emulator, a, "emulator")  # the same run again: its own rows are not training data
    assert len(whatif.read_table(a.run_dir / "emulator" / "train_input.parquet")) == 140 and holdout_rows(a) == 142
    assert len(whatif.read_table(table)) == 144                                                                # replaced, not doubled
    b = cheap_plan(synthetic_ctx(tmp_path, 48, "b"), 10.0)                                                     # another run on the table as it is now
    run_stage(pipeline.s_emulator, b, "emulator")
    assert len(whatif.read_table(b.run_dir / "emulator" / "train_input.parquet")) == 144       # a's four rows are in the snapshot ...
    assert holdout_rows(b) == 142                                                              # ... and b's rows (same mission, same keys) replace them


def test_a_row_another_run_appends_while_the_stage_runs_does_not_reach_this_runs_emulator(tmp_path, table, fake_stage1, monkeypatch):
    from cafe.pm import whatif
    seed_table(table)
    other = dict(whatif.read_table(table).iloc[0].to_dict(), key="other|glider|base", run_id="other")
    real, seen = whatif.train, []

    def train(tab, classes, path=None, df=None, **kw):
        whatif.add_rows(table, [other])                                                                       # a concurrent run finishes right now
        seen.append(len(df))
        return real(tab, classes, path, df, **kw)
    monkeypatch.setattr(whatif, "train", train)
    ctx = cheap_plan(synthetic_ctx(tmp_path, 48), 10.0)
    run_stage(pipeline.s_emulator, ctx, "emulator")
    assert seen == [144] and "other|glider|base" in set(whatif.read_table(table)["key"]) and holdout_rows(ctx) == 142       # 140 + the run's four rows, not 145


def test_the_emulator_table_is_the_option_then_the_environment_then_the_shared_data_tree(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "DATA", tmp_path / "d")
    monkeypatch.delenv("CAFE_EMULATOR_TABLE", raising=False)
    shared = tmp_path / "d" / "emulator" / "train.parquet"
    assert pipeline.emulator_table() == shared and ctx_for(tmp_path / "r").table == shared
    monkeypatch.setenv("CAFE_EMULATOR_TABLE", str(tmp_path / "env.parquet"))
    assert pipeline.emulator_table() == tmp_path / "env.parquet" and ctx_for(tmp_path / "r").table == tmp_path / "env.parquet"
    ctx = pipeline.Context(MISSION_PATH, "ci", 0, tmp_path / "r", quiet, emulator_table=tmp_path / "opt.parquet")
    assert ctx.table == tmp_path / "opt.parquet" and pipeline.emulator_table("x.parquet") == pathlib.Path("x.parquet")


def test_a_fetch_leaves_the_ingest_ledger_current_for_the_run_of_the_same_budget(tmp_path):
    """The resume hash names the budget; fetch hashes with the one it was given, so `run` after `fetch` (and `fetch` after `run`) keeps ingest up to date."""
    pipeline.run(MISSION_PATH, "ci", 0, tmp_path / "r", stop_after="ingest", log=quiet)
    again = ctx_for(tmp_path / "r")
    assert ledger.done(again.run_dir, "ingest", again.hash) is not None
    assert ctx_for(tmp_path / "r2", budget_name=None).hash != again.hash                                         # but no budget at all is its own hash


def test_a_context_without_a_budget_plans_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(budget, "plan", lambda *a, **k: pytest.fail("no budget, no plan"))
    ctx = ctx_for(tmp_path / "r", budget_name=None)
    assert ctx.plan == {} and ctx.mission["name"] == "ci_fixture" and ctx.classes["usv"] == "usv"


def test_run_to_ingest_plans_nothing_and_writes_no_plan_file(tmp_path, monkeypatch):
    seen = []
    real = pipeline.Context

    def spy(mission, budget_name, *a, **k):
        seen.append((budget_name, k.get("hash_budget")))
        return real(mission, budget_name, *a, **k)
    monkeypatch.setattr(pipeline, "Context", spy)
    pipeline.run(MISSION_PATH, "quick", 0, tmp_path / "r", stop_after="ingest", log=quiet)
    assert seen == [(None, "quick")] and not (tmp_path / "r" / "plan.json").exists() and (tmp_path / "r" / "checkpoints" / "ingest" / "ledger.json").is_file()


def test_the_planner_is_given_the_gpu_memory_it_must_guard(tmp_path):
    ctx = pipeline.Context(MISSION_PATH, "quick", 1, tmp_path / "r", quiet, gpu_mem_gb=16.0)
    assert ctx.plan["les"]["gpu_mem_gb"] == 16.0 and ctx.plan["les"]["max_cells"] > 0
    assert "gpu_mem_gb" not in pipeline.Context(MISSION_PATH, "quick", 1, tmp_path / "r2", quiet).plan["les"]


def test_a_variant_that_leaves_the_environment_is_skipped_with_its_reason_and_never_crashes_the_run(tmp_path, table, fake_stage1, monkeypatch):
    from cafe.pm import whatif
    from cafe.pm.env.environment import OutsideData
    inner, base = stage1.run_batch, pm_run.mission()["vehicles"]

    def run_batch(mission, *a, **k):
        moved = [v["id"] for v in mission["vehicles"] if v != next(x for x in base if x["id"] == v["id"])]
        if "glider_eq" in moved:
            raise OutsideData("wind: (-171.20, 0.90) at 2023-03-02 06:00Z is outside the cached data")
        b = inner(mission, *a, **k)
        ids = {v["id"] for v in mission["vehicles"]}
        return dict(b, vehicles={k: v for k, v in b["vehicles"].items() if k in ids})  # the real run_batch returns this mission's vehicles
    monkeypatch.setattr(stage1, "run_batch", run_batch)
    ctx = cheap_plan(synthetic_ctx(tmp_path, 48, unused_refit=True), 100.0)                                    # three variants
    d = run_stage(pipeline.s_emulator, ctx, "emulator")                                                        # the same run used to raise
    design = json.loads((ctx.run_dir / "emulator" / "design.json").read_text())
    assert len(design["variants"]) == 3 and design["skipped"] and all(s["vehicle"] == "glider_eq" for s in design["skipped"])
    assert all("leaves the environment data: wind: (-171.20, 0.90)" in s["reason"] for s in design["skipped"])
    kept = [v for v in design["variants"] if v["skipped"]]
    assert kept and all("glider_eq" not in v["vehicles"] and "usv" in v["vehicles"] for v in kept)  # the other vehicles of that variant kept their rows
    df = whatif.read_table(table)
    n_skipped = len(design["skipped"])
    assert design["rows_added"] == 4 * 4 - n_skipped == len(df) and check_of(d, "emulator_rows_appended")["ok"]
    assert sum(1 for n in d["notes"] if "skipped for glider_eq" in n) == n_skipped


def test_the_flip_search_on_the_ci_mission_does_not_crash_when_a_moved_track_leaves_the_cache(tmp_path):
    """The CI cache ends at 167 W. A glider track 0.2 degree inside it, moved 0.5 or 1 degree west, is outside: GriddedEnv refuses (strict), which used
    to end the run in the flip search's emulator query. Now each such candidate is a reason; the others are answered."""
    from cafe.pm import whatif
    from cafe.pm.env.environment import OutsideData
    from tests import test_whatif
    ctx = ctx_for(tmp_path / "r")
    em, _ = whatif.fit_class(test_whatif.storm_table(), "glider", tmp_path / "t.parquet")
    trk = (np.linspace(T0, T1, 24), np.full(24, -166.8), np.zeros(24))
    with pytest.raises(OutsideData):
        whatif.env_stats(ctx.env, *whatif.shift_track(trk, dict(dlon=-0.5), ctx.mission))                      # what the flip search used to run into
    pri, marg = stage1.priors_for(ctx.mission)
    flips, _ = whatif.flip_search(ctx.mission, {"glider_eq": dict(verdict="NO-GO", p_fail=0.9)}, {"glider_eq": trk}, ctx.env, {"glider": (em, {})}, ctx.plan,
                                  pri, marg, None, int(ctx.mission["seed"]), 1e6, quiet)
    tried = flips["glider_eq"]["tried"]
    west = [t for t in tried if "west" in t["change"] and "leaves the environment data" in t["reason"]]
    assert {t["change"] for t in west} == {"move 0.5 deg west", "move 1 deg west"} and all(t["method"] == "not evaluated" for t in west)
    assert any(t["method"] == "EMULATED" or t["reason"] for t in tried if t not in west)                       # the rest were still tried


def test_a_variant_of_the_ci_mission_past_the_cache_edge_is_skipped_for_that_glider_only(tmp_path):
    """The mission box is widened to 168 W and the glider deployed at 166.9 W, 0.1 degree inside the cache; a variant 0.5 degree west deploys it outside."""
    from cafe.pm import whatif
    from cafe.pm.env.environment import OutsideData
    m = yaml.safe_load(MISSION_PATH.read_text())
    m["box"]["lon_min"] = -168.0
    m["vehicles"] = [v for v in m["vehicles"] if v["id"] != "uas"]
    m["links"] = [lk for lk in m["links"] if "uas" not in (lk["a"], lk["b"])]
    m["vehicles"][0]["deploy"]["lon"] = m["vehicles"][0]["task"]["lon"] = -166.9
    (tmp_path / "m.yaml").write_text(yaml.safe_dump(m))
    ctx = ctx_for(tmp_path / "r", mission=tmp_path / "m.yaml")
    pri, marg = stage1.priors_for(ctx.mission)
    members, seed = [0, 1, 2, 3], int(ctx.mission["seed"])
    mv = whatif.apply(ctx.mission, {"glider_eq": dict(dlon=-0.5)})
    with pytest.raises(OutsideData):
        stage1.run_batch(mv, ctx.env, members, seed, pri, marg, None)                                         # what the emulator stage used to do
    meta = dict(run_id="r", mission="ci", git_sha="x", code_digest="y")
    rows, skipped = whatif.run_variant(mv, ctx.env, members, seed, pri, marg, None, {}, meta, "v0")
    assert list(skipped) == ["glider_eq"] and skipped["glider_eq"].startswith("the variant leaves the environment data: ")
    assert sorted(r["vehicle"] for r in rows) == ["glider_1n", "usv"] and {r["variant"] for r in rows} == {"v0"}
    rows, skipped = whatif.run_variant(ctx.mission, ctx.env, members, seed, pri, marg, None, {}, meta, "base")        # the unmoved mission runs whole
    assert skipped == {} and sorted(r["vehicle"] for r in rows) == ["glider_1n", "glider_eq", "usv"]


def test_the_stage_learns_from_what_the_table_already_holds(tmp_path, table, fake_stage1, monkeypatch):
    """With a trained glider emulator the glider candidates are answered by it (EMULATED) and Stage 1 is not run for them."""
    from cafe.pm import whatif
    seed_table(table)
    monkeypatch.setattr(whatif, "LIMITS", dict(rmse=0.05, coverage=0.5, query_ms=1e9))
    ctx = cheap_plan(synthetic_ctx(tmp_path, 48))
    summ = json.loads((ctx.run_dir / "stage1b" / "summary.json").read_text())
    summ["summary"]["vehicles"]["glider_eq"]["verdict"] = dict(summ["summary"]["vehicles"]["glider_eq"]["verdict"], verdict="NO-GO", p_fail=0.9)
    (ctx.run_dir / "stage1b" / "summary.json").write_text(json.dumps(summ))
    run_stage(pipeline.s_emulator, ctx, "emulator")
    g = json.loads((ctx.run_dir / "emulator" / "flip.json").read_text())["vehicles"]["glider_eq"]
    assert g["emulator"] and any(t["method"] == "EMULATED" for t in g["tried"])
    assert all(t["method"] != "Stage 1" for t in g["tried"]) or not g["found"]


def test_the_hold_out_is_rechecked_on_members_no_training_row_used(tmp_path, table, fake_stage1, monkeypatch):
    """Round 3 M-4: every variant runs members of its own and the hold-out's fresh-draw check runs blocks after the variants'; round 7 M-7: all of them
    after the 48 members stage 1b used."""
    from cafe.pm import whatif
    seed_table(table, n=100)                                         # 100 rows + this run's glider rows: just enough distinct points to train
    monkeypatch.setattr(whatif, "LIMITS", dict(rmse=0.05, coverage=0.5, query_ms=1e9))
    ctx = cheap_plan(synthetic_ctx(tmp_path, 48, unused_refit=True), 100.0)                  # share 20 s: three variants
    d = run_stage(pipeline.s_emulator, ctx, "emulator")
    design = json.loads((ctx.run_dir / "emulator" / "design.json").read_text())
    n_var = len(design["variants"])
    h = json.loads((ctx.run_dir / "emulator" / "holdout.json").read_text())["glider_eq"]
    assert h["trained"] and "its own members" in h["draws"] and n_var >= 1
    runs = [c[1] for c in fake_stage1]
    variants, later = runs[:n_var], runs[n_var:]
    assert variants == [list(range(16 * (3 + k), 16 * (4 + k))) for k in range(n_var)]
    fresh_blocks = [m for m in later if m[0] >= 16 * (3 + n_var)]
    assert len(fresh_blocks) == h["fresh_points"] and len({m[0] for m in fresh_blocks}) == len(fresh_blocks)         # each fresh draw its own unused block
    assert h["fresh_points"] == 0 or (h["rmse_gate"] >= h["rmse_debiased"] and h["rmse_gate"] >= h["rmse_fresh_debiased"])
    note = next(n for n in d["notes"] if n.startswith("emulator glider: BRIEF 2.7 RMSE"))
    assert ("point(s) re-run on fresh members:" in note) == bool(h["fresh_points"])
    assert ("only the in-sample score is judged" in note) == (not h["fresh_points"])
    assert h["fresh_points"] >= 1, "no variant row landed in the hold-out: the fresh-draw wiring is not exercised"


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
        fitted=j("ingest", "priors_fitted.json"), ledger_report=read_ledger(run, "report"), ledger_emulator=read_ledger(run, "emulator"))


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


def test_every_stage_that_reads_the_surface_layer_recorded_that_it_was_unchanged_since_ingest(ci_runs):
    """Round 4 M-2, on the real run: windows, stage 1, 1b and the emulator each compare the store with ingest's record and list that record as an input."""
    rec = ci_runs.run / "ingest" / surface.DIGEST
    for st in ("stage1", "windows", "stage1b", "emulator"):
        d = read_ledger(ci_runs.run, st)
        c = check_of(d, "derived_unchanged")
        assert c["ok"] and c["value"] == c["limit"] == json.loads(rec.read_text())["store_sha256"], st
        assert any(i["ref"] == str(rec) for i in d["inputs"]), st
    assert audit.ledger_problems(ci_runs.run) == []


def test_stage1_ran_with_the_tao_fitted_priors_and_one_stratified_batch(ci_runs):
    f = ci_runs.first
    s = f.summary1
    assert s["n"] == 8 and s["certify"] is False and s["priors"]["wind_speed_bias"]["mean"] == pytest.approx(f.fitted["wind_speed_bias"]["mean"])
    assert s["priors"]["wind_speed_bias"]["sd"] == pytest.approx(f.fitted["wind_speed_bias"]["value"]) and s["priors"]["wind_speed_bias"]["sd"] < 2.0
    assert s["names"] == stage1.FORCING + ["glider_speed_scale", "usv_vpp_bias", "bulk_stress_scale", "battery_capacity_scale"]
    assert set(s["summary"]["vehicles"]) == set(CLASSES)
    assert len(s["summary"]["links"]) == 3
    assert any(i["ref"].endswith("ingest/priors_fitted.json") for i in f.ledger1["inputs"]) and f.ledger1["seeds"] == {"mission": 20230301}
    c = check_of(f.ledger1, "lhs_stratified_batch1")
    assert c["ok"] and c["limit"] == pytest.approx(1 / 8)
    assert [x["name"] for x in f.ledger1["checks"]] == ["derived_unchanged", "lhs_stratified_batch1", "ensemble_size", "sampled_marginals_match_priors",
                                                         "common_random_numbers",
                                                         "members_inside_data", "wilson_matches_statsmodels", "failure_modes_recorded"]
    assert any("8 members in" in n for n in f.ledger1["notes"])


def reject(name):
    raise ValueError(f"non-standard JSON constant {name}")


def test_every_json_file_a_run_wrote_parses_as_strict_json(ci_runs):
    """M-30: windows.json held `"limit": Infinity`, tao_compare.json `"sst_bias": NaN`; jq and JSON.parse reject both."""
    files = sorted(ci_runs.run.rglob("*.json"))
    assert {"tao_compare.json", "priors_fitted.json", "plan.json", "windows.json", "report.json"} <= {f.name for f in files} and len(files) >= 20
    for f in files:
        json.loads(f.read_text(), parse_constant=reject)


def test_stage_1b_says_how_many_refit_passes_it_made_and_the_plan_names_the_cap(ci_runs):
    assert ci_runs.first.summary1b["refit_iterations_performed"] == 0                                                       # no window passed: stage 1 copied
    assert json.loads((ci_runs.run / "stage1b" / "summary.json").read_text())["refit_iterations_performed"] == 1          # the second run refit the usv
    assert json.loads((ci_runs.run / "plan.json").read_text())["refit_iterations_max"] == 2
    assert check_of(read_ledger(ci_runs.run, "stage1b"), "refit_iterations_within_cap")["value"] == 1


def test_stage1_results_carry_the_platform_antennas_the_classes_and_no_simulator_objects(ci_runs):
    res = pickle.loads(ci_runs.first.res1)
    # tail masts, the RF whip, the UAS whip
    assert {k: v["antenna_m"] for k, v in res["vehicles"].items()} == {"glider_eq": 0.5, "glider_1n": 0.3, "usv": 2.2, "uas": 0.1}
    assert {k: v["class"] for k, v in res["vehicles"].items()} == CLASSES and all("sim" not in v for v in res["vehicles"].values())
    assert res["U"].shape == (8, 10) and set(res["X"]) == set(ci_runs.first.summary1["names"])
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
        assert len(ws) == 1 and ws[0]["basis"] == pipeline.BASIS[bool(f.summary1["summary"]["vehicles"][vid]["k_fail"])]
        assert T0 <= ws[0]["t"] <= T1 and np.isfinite(ws[0]["stress"])
        assert set(ws[0]) == {"t", "stress", "lon", "lat", "basis", "criterion", "records", "failed_at"}
        k = f.summary1["summary"]["vehicles"][vid]["k_fail"]
        assert (len(ws[0]["failed_at"]) == k or vid == "uas") and ws[0]["failed_at"] == sorted(ws[0]["failed_at"])
    assert any(w[0]["basis"] == pipeline.BASIS[True] for w in f.windows.values())                                           # the USV fails in this mission


def test_no_passing_window_means_no_refit_and_stage1b_is_a_copy(ci_runs):
    f = ci_runs.first
    assert ci_runs.rows.calls[0] == f.windows
    assert set(f.refit) == set(CLASSES)
    for r in f.refit.values():
        assert r["used"] is False and "window passed its stage-3" in r["reason"] and r["failed_checks"] == ["mach_max"]
    sens_note, copied = f.ledger1b["notes"]
    assert f.res1b == f.res1 and f.summary1b == dict(f.summary1, refit_iterations_performed=0)
    assert copied.startswith("no vehicle was refit: stage 1b is stage 1 (copied, not rerun); the sensitivity case reran the USV in ")
    assert copied.endswith(" s, not charged to any share")
    assert re.fullmatch(r"sensitivity case \(brief VPP bias, same members and inputs, only usv_vpp_bias replaced\): usv \d+ of 8 (GO|MARGINAL|NO-GO)",
                        sens_note)
    outs = {pathlib.Path(o["path"]).name: o["sha256"] for o in f.ledger1b["outputs"]}
    assert set(outs) == {"res.pkl", "summary.json", report.SENSITIVITY} and outs["res.pkl"] == hashlib.sha256(f.res1).hexdigest()


def test_the_emulator_stage_adds_rows_for_the_run_and_is_not_trained_yet(ci_runs):
    from cafe.pm import whatif
    f = ci_runs.first
    assert set(f.holdout) == set(CLASSES)
    for vid, h in f.holdout.items():
        assert h["trained"] is False and h["cls"] == CLASSES[vid]
        assert h["reason"].endswith(f"{whatif.MIN_ROWS} are needed (a 20 % hold-out must score 90 % coverage)")
    df = whatif.read_table(pipeline.DATA / "emulator" / "train.parquet")
    assert set(df["vehicle"]) == set(CLASSES) and (df["n_members"] == 8).all() and set(df["mission"]) == {"ci_fixture"}
    assert np.isfinite(df[whatif.BASE]).all().all()
    assert any("not trained (trained: false)" in n for n in f.ledger_emulator["notes"]) and all(c["ok"] for c in f.ledger_emulator["checks"])


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
    assert any(n.endswith("certify possible: False (n_certify 73)") for n in d["notes"]) and "copied" not in " ".join(d["notes"])
    sens = json.loads((run / "stage1b" / "sensitivity_cases.json").read_text())                  # the brief's VPP bias, next to the calibrated verdict
    assert list(sens) == ["usv"] and sens["usv"][0]["n"] == 8 and "usv_vpp_bias_brief" in sens["usv"][0]["case"]
    assert any(n.startswith("sensitivity case (brief VPP bias, same members and inputs, only usv_vpp_bias replaced): usv ") for n in d["notes"])
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


# ---------------------------------------------------------------------------------------------------------------- batch C: review round 1

def test_every_ledger_of_a_run_carries_the_dirty_flag_and_the_code_digest_of_the_context(tmp_path, monkeypatch):
    stub_stages(monkeypatch, [])
    ctx = go(tmp_path / "run")
    for st in STAGES:
        d = read_ledger(tmp_path / "run", st)
        assert d["code_digest"] == ctx.code_digest == pipeline.code_digest() and d["git_dirty"] in (True, False, None)


def test_the_hangar_ledger_says_that_no_cfd_ran_and_what_the_baseline_coefficients_are(tmp_path):
    d = run_stage(pipeline.s_hangar, ctx_for(tmp_path / "r"), "hangar")
    assert len(d["notes"]) == 1 and d["notes"][0].startswith("no Hangar CFD run: the baseline model coefficients are analytic")
    assert "GCI" in d["notes"][0] and not any("Hangar coefficient" in n for n in d["notes"])


# ---- M-14: the orca cache is only reused for the box and 3-D hours it was cut for

def manifest(**over):
    return dict(dict(t0="2023-03-01 18:00:00", t1="2023-03-03 06:00:00", box=[-167.0, -163.0, -2.0, 2.0],
                     hours3d=["2023-03-02_01:00:00", "2023-03-02_02:00:00", "2023-03-03_01:00:00", "2023-03-03_02:00:00"]), **over)


WANT = ((-167.0, -163.0, -2.0, 2.0), [dt.datetime(2023, 3, 2, 1), dt.datetime(2023, 3, 2, 2), dt.datetime(2023, 3, 3, 1)])


@pytest.mark.parametrize("over,covers", [
    ({}, True),
    (dict(box=[-168.0, -162.0, -3.0, 3.0]), True),                                      # a wider cut contains the box
    (dict(box=[-167.0, -163.0, -2.0, 1.99]), False), (dict(box=[-167.0, -163.0, -1.99, 2.0]), False),
    (dict(box=[-166.9, -163.0, -2.0, 2.0]), False), (dict(box=[-167.0, -163.1, -2.0, 2.0]), False),
    (dict(box=None), False),                                                            # written before the box was recorded: it cannot say
    (dict(hours3d=["2023-03-02_01:00:00"]), False), (dict(hours3d=[]), False),
    (dict(t1="2023-03-03 05:00:00"), False),
])
def test_an_orca_cache_is_reused_only_when_it_covers_the_window_the_box_and_the_3d_hours(over, covers):
    d = manifest(**over)
    assert pipeline._orca_covers(d, config.utc("2023-03-01T18:00:00Z"), config.utc("2023-03-03T06:00:00Z"), *WANT) is covers


def test_an_orca_manifest_with_no_3d_hours_key_covers_only_a_mission_without_uas_sorties():
    d = manifest()
    del d["hours3d"]
    t0, t1 = config.utc("2023-03-01T18:00:00Z"), config.utc("2023-03-03T06:00:00Z")
    assert pipeline._orca_covers(d, t0, t1, WANT[0], []) and not pipeline._orca_covers(d, t0, t1, *WANT)


@pytest.mark.parametrize("damage", ["box", "no_box", "hours3d"])
def test_ingest_refetches_a_cache_cut_for_another_box_or_other_3d_hours(tmp_path, data_copy, monkeypatch, damage):
    monkeypatch.delenv("CAFE_OFFLINE")
    man = data_copy / "cache" / "ci_fixture" / "orca" / "manifest.json"
    saved = json.loads(man.read_text())
    assert saved["box"] == [-167.0, -163.0, -2.0, 2.0] and saved["hours3d"]            # the fixture records both, as orca.ingest does
    bad = dict(saved)
    if damage == "box":
        bad["box"] = [-166.0, -164.0, -1.0, 1.0]
    elif damage == "no_box":
        del bad["box"]
    else:
        bad["hours3d"] = saved["hours3d"][:1]
    man.write_text(json.dumps(bad))
    calls = []

    def fake_ingest(t0, t1, box, out, hours3d=(), threads=8, spectra=True, log=print):
        calls.append(box)
        man.write_text(json.dumps(saved))
    monkeypatch.setattr(orca, "ingest", fake_ingest)
    run_stage(pipeline.s_ingest, ctx_for(tmp_path / "r"), "ingest")
    assert calls == [(-167.0, -163.0, -2.0, 2.0)]


# ---- M-1 (pipeline side) and M-12: the ingest self-checks

def ingest_checks(ctx, oc="real"):
    """Run the ingest self-checks alone on ctx's environment; -> the ledger (a failed check does not raise here)."""
    oc = pipeline.ocean(ctx) if oc == "real" else oc
    try:
        with ledger.Ledger(ctx.run_dir, "ingest", ctx.hash) as L:
            pipeline._ingest_checks(ctx, L, oc, pipeline.ocean_box(ctx.mission))
    except ledger.StageFailed:
        pass
    return read_ledger(ctx.run_dir, "ingest")


def failing(d):
    return sorted(c["name"] for c in d["checks"] if not c["ok"])


def test_the_ingest_checks_all_pass_on_the_fixture_and_record_numbers(tmp_path):
    d = ingest_checks(ctx_for(tmp_path / "r"))
    assert failing(d) == [] and [c["name"] for c in d["checks"]] == [
        "ocean_source_covers_box", "mission_points_inside_cached_grids", "time_axes_hourly_gap_free", "no_nan_in_sea_cells", "spectrum_peak_period_vs_file",
        "spectrum_direction_vs_file", "spectrum_mss_vs_file", "coare_ustar_vs_umwm_ust", "ocean_temperature_kind_flag", "direction_round_trip"]
    c = {x["name"]: x for x in d["checks"]}
    assert c["ocean_source_covers_box"]["value"] >= -pipeline.OCEAN_SNAP_DEG and "tightest is " in c["ocean_source_covers_box"]["note"]
    assert c["spectrum_peak_period_vs_file"]["value"] <= pipeline.TP_LIMIT and c["spectrum_direction_vs_file"]["value"] <= pipeline.DIR_LIMIT_DEG
    note = c["spectrum_mss_vs_file"]["note"]
    assert c["spectrum_mss_vs_file"]["value"] <= pipeline.MSS_LIMIT and "of the points" in note and "Hs is forced" in note
    assert c["no_nan_in_sea_cells"]["value"] == 0 and c["ocean_temperature_kind_flag"]["value"] == "in_situ"
    assert c["coare_ustar_vs_umwm_ust"]["value"] is not None and "within 20 %" in c["coare_ustar_vs_umwm_ust"]["note"]
    assert set(c["direction_round_trip"]["value"]) == {"wind_ms", "wave_deg", "current_ms"}
    assert c["mission_points_inside_cached_grids"]["note"].endswith(" points")


def test_the_ocean_store_must_cover_the_box_and_every_waypoint_and_deploy_point(tmp_path, monkeypatch):
    ctx = ctx_for(tmp_path / "r")
    monkeypatch.setattr(pipeline, "mission_points", lambda m: [("usv waypoint 7", -150.0, 0.0), ("glider_eq deploy", -165.5, 0.0)])
    d = ingest_checks(ctx)
    c = check_of(d, "ocean_source_covers_box")
    assert not c["ok"] and c["value"] < -10 and "tightest is usv waypoint 7" in c["note"] and c["limit"] == -pipeline.OCEAN_SNAP_DEG
    assert "mission_points_inside_cached_grids" in failing(d) and "usv waypoint 7" in check_of(d, "mission_points_inside_cached_grids")["note"]


def test_a_missing_ocean_store_fails_the_covers_check_and_the_flag_check(tmp_path):
    d = ingest_checks(ctx_for(tmp_path / "r"), oc=None)
    c = check_of(d, "ocean_source_covers_box")
    assert not c["ok"] and c["value"] is None and c["note"].endswith("no ocean store")
    assert not check_of(d, "ocean_temperature_kind_flag")["ok"] and check_of(d, "direction_round_trip")["value"]["current_ms"] is None


def test_ocean_margins_are_the_distance_each_requirement_sits_inside_the_store():
    ds = types.SimpleNamespace(lat=types.SimpleNamespace(values=np.array([-2.0, 0.0, 2.0])), lon=types.SimpleNamespace(values=np.array([193.0, 195.0, 197.0])))
    got = dict(pipeline.ocean_margins(ds, (-1.5, 1.5, -166.0, -164.0), [("p", -165.0, 0.5), ("edge", -163.0, 2.0)]))
    assert got == {"box south edge": 0.5, "box north edge": 0.5, "box west edge": 1.0, "box east edge": 1.0, "p": 1.5, "edge": 0.0}
    assert dict(pipeline.ocean_margins(ds, (-2.5, 1.5, -166.0, -164.0), []))["box south edge"] == -0.5


def test_mission_points_are_the_ship_deploy_points_waypoints_and_stations():
    pts = dict((lab, (lo, la)) for lab, lo, la in pipeline.mission_points(config.load_mission(MISSION_PATH)))
    assert pts == {"ship": (-165.0, 0.0), "glider_eq deploy": (-165.5, 0.0), "glider_eq station": (-165.5, 0.0), "glider_1n deploy": (-165.0, 1.0),
                   "usv deploy": (-165.0, -1.0), "usv waypoint 0": (-165.0, -1.0), "usv waypoint 1": (-165.0, 1.0)}
    assert pipeline.mission_points(dict(vehicles=[dict(id="a")])) == []


def test_a_time_axis_with_a_gap_fails_the_ingest(tmp_path):
    ctx = ctx_for(tmp_path / "r")
    ctx.env.tu.x = ctx.env.tu.x.copy()
    ctx.env.tu.x[5:8] += 600.0                                                                 # a late stretch of three hours; the sampled hours are untouched
    c = check_of(ingest_checks(ctx), "time_axes_hourly_gap_free")
    assert not c["ok"] and c["value"] == pytest.approx(600.0)


def test_a_nan_in_a_sea_cell_or_in_a_wrf_field_fails_the_ingest(tmp_path):
    ctx = ctx_for(tmp_path / "r")
    ctx.env.U["mwp"][2][ctx.env.sea] = np.nan
    n = int(ctx.env.sea.sum())
    c = check_of(ingest_checks(ctx), "no_nan_in_sea_cells")
    assert not c["ok"] and c["value"] == n
    ctx = ctx_for(tmp_path / "r2")
    ctx.env.W["T2"][0, 0, 0] = np.nan
    assert check_of(ingest_checks(ctx), "no_nan_in_sea_cells")["value"] == 1


def spectrum_check(tmp_path, monkeypatch, wrap, name):
    """ingest_checks with spectrum_from_params replaced by `wrap(real_result)`; -> the ledger check `name`."""
    from cafe.pm.env import waves
    real = waves.spectrum_from_params
    monkeypatch.setattr(waves, "spectrum_from_params", lambda *a, **k: wrap(real(*a, **k)))
    return check_of(ingest_checks(ctx_for(tmp_path / "r")), name)


def test_a_synthesised_spectrum_whose_peak_is_at_the_wrong_period_fails_the_ingest(tmp_path, monkeypatch):
    c = spectrum_check(tmp_path, monkeypatch, lambda E: np.roll(E, 3, axis=-2), "spectrum_peak_period_vs_file")      # three frequency bins: 1.1225^3 = 1.41 x
    assert not c["ok"] and 0.25 < c["value"] < 0.45 and c["limit"] == pipeline.TP_LIMIT


def test_a_synthesised_spectrum_with_the_wrong_mean_direction_fails_the_ingest(tmp_path, monkeypatch):
    c = spectrum_check(tmp_path, monkeypatch, lambda E: np.roll(E, 4, axis=-1), "spectrum_direction_vs_file")        # four direction bins = 45 degrees
    assert not c["ok"] and c["value"] == pytest.approx(45.0, abs=0.5) and c["limit"] == pipeline.DIR_LIMIT_DEG


def test_a_synthesised_spectrum_with_the_wrong_slope_variance_fails_the_ingest(tmp_path, monkeypatch):
    c = spectrum_check(tmp_path, monkeypatch, lambda E: 3.0 * E, "spectrum_mss_vs_file")  # slope variance x3 (Hs x1.7 is not what is tested)
    assert not c["ok"] and c["value"] > pipeline.MSS_LIMIT and "clipped" in c["note"]


def test_the_spectrum_checks_pass_on_the_unchanged_synthesis_and_report_their_numbers(tmp_path):
    d = ingest_checks(ctx_for(tmp_path / "r"))
    for name in ("spectrum_peak_period_vs_file", "spectrum_direction_vs_file", "spectrum_mss_vs_file"):
        c = check_of(d, name)
        assert c["ok"] and c["value"] is not None and c["value"] <= c["limit"] and "sampled sea points" in c["note"], name


def test_a_file_with_no_usable_peak_period_fails_the_spectrum_checks_with_no_number(tmp_path):
    ctx = ctx_for(tmp_path / "r")
    ctx.env.U["dwp"][:] = np.nan                                                               # no period: no spectrum, no number
    d = ingest_checks(ctx)
    for name in ("spectrum_peak_period_vs_file", "spectrum_direction_vs_file", "spectrum_mss_vs_file"):
        c = check_of(d, name)
        assert not c["ok"] and c["value"] is None, name


def test_a_file_with_no_swh_in_any_sea_cell_fails_the_spectrum_checks_instead_of_passing_them(tmp_path):
    ctx = ctx_for(tmp_path / "r")
    ctx.env.U["swh"][:] = 0.0
    assert not check_of(ingest_checks(ctx), "spectrum_peak_period_vs_file")["ok"]


def test_coare_ustar_is_compared_with_umwm_ust_and_the_agreement_is_logged(tmp_path):
    ctx = ctx_for(tmp_path / "r")
    n, med, frac = pipeline._ustar_agreement(ctx.env)
    assert n > 100 and 0 <= frac <= 1 and med >= 0
    c = check_of(ingest_checks(ctx), "coare_ustar_vs_umwm_ust")
    assert c["ok"] and c["value"] == pytest.approx(frac, abs=1e-4) and f"{n} sampled sea points" in c["note"]
    ctx.env.U["ust"][:] = 0.0                                                                   # no usable ust at all: there is nothing to compare
    c = check_of(ingest_checks(ctx), "coare_ustar_vs_umwm_ust")
    assert not c["ok"] and c["value"] is None


@pytest.mark.parametrize("source,kind,ok", [("gofs31", "in_situ", True), ("gofs31", "potential", False), ("lab_hycom", "potential", True),
                                            ("lab_hycom", "in_situ", True)])
def test_the_temperature_kind_flag_must_be_in_situ_for_gofs_and_a_known_kind_for_the_labs_hycom(tmp_path, source, kind, ok):
    ctx = ctx_for(tmp_path / "r")
    oc = pipeline.ocean(ctx)
    oc.ds.attrs["temperature_kind"] = kind
    ctx.mission["environment"]["ocean"] = dict(source=source, path=str(oc.path))
    assert check_of(ingest_checks(ctx, oc), "ocean_temperature_kind_flag")["ok"] is ok


def test_a_broken_direction_convention_fails_the_round_trip(tmp_path, monkeypatch):
    ctx = ctx_for(tmp_path / "r")
    real = pipeline.cv.compass_to_to_math_rad
    monkeypatch.setattr(pipeline.cv, "compass_to_to_math_rad", lambda deg: real(deg) + 0.01)
    c = check_of(ingest_checks(ctx), "direction_round_trip")
    assert not c["ok"] and c["value"]["wave_deg"] == pytest.approx(np.degrees(0.01), rel=1e-6) and c["value"]["wind_ms"] < 1e-9
    monkeypatch.undo()
    monkeypatch.setattr(pipeline.cv, "vec_from_to", lambda s, d: np.zeros(np.shape(s) + (2,)))
    assert check_of(ingest_checks(ctx_for(tmp_path / "r2")), "direction_round_trip")["value"]["wind_ms"] > 1.0


# ---- M-3 and M-12: windows

def airborne_res(t, M, cls, air, tracks=None):
    r = track_res(t, M, tracks or [(-165.0, 0.0)] * M, {}, cls)
    r["airborne"] = air
    return r


def test_a_uas_window_is_chosen_only_among_the_records_where_a_selected_member_is_airborne(tmp_path, data):
    """q1: the strongest 10 m wind of the whole window was at 05:00 local, 15 h after a landing; the LES then ran a flight that never happened."""
    t = T0 + 600.0 * np.arange(217)
    ref = stress_of(ctx_for(tmp_path / "x").env, "uas", np.full(t.size, -165.0), np.full(t.size, 0.0), t)
    best = int(np.argmax(ref))
    air = np.zeros((t.size, 4), bool)
    air[(t >= t[best] + 6 * 3600) & (t < t[best] + 7 * 3600)] = True                           # flies only an hour, six hours after the wind peak
    assert not air[best].any()
    ctx = window_ctx(tmp_path, {"u": airborne_res(t, 4, "uas", air)}, K=1)
    d = run_stage(pipeline.s_windows, ctx, "windows")
    w = json.loads((ctx.run_dir / "windows" / "windows.json").read_text())["u"][0]
    inside = np.flatnonzero(air.any(1))
    assert w["records"] == "airborne records" and w["t"] != t[best] and int(round((w["t"] - T0) / 600.0)) in inside
    assert w["stress"] == pytest.approx(ref[inside].max()) and w["criterion"] == pipeline.CRITERION["uas"] == "10 m wind speed [m/s] of the analysis field"
    assert check_of(d, "windows_are_the_argmax")["ok"]


def test_a_uas_that_never_flew_falls_back_to_all_records_and_says_so(tmp_path, data):
    t = T0 + 600.0 * np.arange(60)
    ctx = window_ctx(tmp_path, {"u": airborne_res(t, 3, "uas", np.zeros((t.size, 3), bool))}, K=1)
    d = run_stage(pipeline.s_windows, ctx, "windows")
    w = json.loads((ctx.run_dir / "windows" / "windows.json").read_text())["u"][0]
    assert w["records"] == "all records (no selected member is airborne at any record)" and any("no selected member is airborne" in n for n in d["notes"])


def test_the_airborne_mask_follows_the_selected_members_and_leaves_other_classes_alone(tmp_path, data):
    t = T0 + 600.0 * np.arange(217)
    tracks = [(-165.0, 0.0), (-165.0, 0.0), (-164.0, 1.0), (-164.0, 1.0)]
    air = np.zeros((t.size, 4), bool)
    air[:, :2] = True                                                                           # members 0 and 1 are always up, 2 and 3 never
    failed = track_res(t, 4, tracks, {2: 200, 3: 200}, "uas")                                   # the failed members (2, 3) are the selected ones
    failed["airborne"] = air
    glider = track_res(t, 4, tracks, {}, "glider")
    glider["airborne"] = np.zeros((t.size, 4), bool)                                            # a glider has no sorties: the mask is a UAS rule
    ctx = window_ctx(tmp_path, {"failed": failed, "g": glider}, K=1)
    run_stage(pipeline.s_windows, ctx, "windows")
    wins = json.loads((ctx.run_dir / "windows" / "windows.json").read_text())
    assert wins["failed"][0]["records"].startswith("all records (no selected member") and wins["g"][0]["records"] == "all records"
    assert wins["g"][0]["criterion"] == pipeline.CRITERION["glider"] == "surface current speed [m/s] of the analysis field"


def test_the_position_of_an_airborne_window_is_the_median_of_the_airborne_members_only(tmp_path, data):
    t = T0 + 600.0 * np.arange(60)
    air = np.zeros((t.size, 4), bool)
    air[:, 2:] = True
    ctx = window_ctx(tmp_path, {"u": airborne_res(t, 4, "uas", air, [(-165.0, 0.0), (-165.0, 0.0), (-164.0, 1.0), (-164.0, 1.0)])}, K=1)
    run_stage(pipeline.s_windows, ctx, "windows")
    w = json.loads((ctx.run_dir / "windows" / "windows.json").read_text())["u"][0]
    assert (w["lon"], w["lat"]) == (-164.0, 1.0)


def rows_at(t, idx, stress):
    return [dict(t=float(t[i]), stress=float(stress[i])) for i in idx]


def test_window_problems_accepts_the_greedy_argmax_and_names_every_way_it_can_be_wrong():
    t = 3600.0 * np.arange(0, 40, 1.0)
    w = np.sin(t / 7000.0) + 2.0
    order = [int(i) for i in np.argsort(-w)]
    picks = []
    for i in order:
        if all(abs(t[i] - t[j]) >= 6 * 3600 for j in picks):
            picks.append(i)
        if len(picks) == 3:
            break
    assert pipeline.window_problems(t, w, rows_at(t, picks, w), 3) == []
    worse = [p for p in range(len(t)) if p not in picks and all(abs(t[p] - t[j]) >= 6 * 3600 for j in picks[:1])]
    bad = pipeline.window_problems(t, w, rows_at(t, [worse[0]] + picks[1:], w), 3)
    assert any("window 0" in b and "not the strongest" in b for b in bad)
    wrong = rows_at(t, picks, w)
    wrong[1]["stress"] += 1.0
    assert any("window 1: stress" in b for b in pipeline.window_problems(t, w, wrong, 3))
    assert any("only 2 of 3 windows chosen" in b for b in pipeline.window_problems(t, w, rows_at(t, picks[:2], w), 3))
    near = [picks[0], picks[0] + 1]
    assert any("window 1" in b for b in pipeline.window_problems(t, w, rows_at(t, near, w), 2))              # inside the 6 h separation


def test_windows_that_are_not_the_argmax_fail_the_stage(tmp_path, data, monkeypatch):
    t = T0 + 600.0 * np.arange(217)
    ctx = window_ctx(tmp_path, {"u": track_res(t, 2, [(-165.0, 0.0)] * 2, {}, "uas")}, K=2)
    seen = []
    monkeypatch.setattr(pipeline, "window_problems", lambda t_, worst, rows, k: seen.append((len(rows), k)) or ["window 0 is not the strongest"])
    with pytest.raises(ledger.StageFailed, match="windows_are_the_argmax"):
        run_stage(pipeline.s_windows, ctx, "windows")
    c = check_of(read_ledger(ctx.run_dir, "windows"), "windows_are_the_argmax")
    assert not c["ok"] and c["value"] == 1 and c["note"] == "u: window 0 is not the strongest" and seen == [(2, 2)]


# ---- M-12: stage 1 and stage 1b self-checks

def stage1_ledger(tmp_path, monkeypatch, plan=None, **over):
    got = {}
    monkeypatch.setattr(stage1, "run", fake_run(got, **over))
    ctx = ctx_for(tmp_path / "r")
    ctx._env = "ENV"
    ctx.plan.update(dict(batch=16, n_max=16), **(plan or {}))
    try:
        run_stage(pipeline.s_stage1, ctx, "stage1")
    except ledger.StageFailed:
        pass
    return read_ledger(ctx.run_dir, "stage1")


def test_the_stage1_checks_pass_on_a_consistent_ensemble_and_record_what_they_compared(tmp_path, monkeypatch):
    d = stage1_ledger(tmp_path, monkeypatch)
    assert failing(d) == []
    c = {x["name"]: x for x in d["checks"]}
    assert c["ensemble_size"]["value"] == 16 and c["ensemble_size"]["limit"] == 73
    assert c["sampled_marginals_match_priors"]["value"] <= c["sampled_marginals_match_priors"]["limit"] == pytest.approx(1 / 16)
    assert c["wilson_matches_statsmodels"]["value"] <= 1e-9 and "mode" in c["failure_modes_recorded"]["note"] and c["failure_modes_recorded"]["value"] == 2


def test_an_ensemble_below_73_is_only_acceptable_when_the_budget_cannot_reach_it(tmp_path, monkeypatch):
    d = stage1_ledger(tmp_path, monkeypatch, plan=dict(n_max=256))
    assert failing(d) == ["ensemble_size"]
    d = stage1_ledger(tmp_path / "ok", monkeypatch, plan=dict(n_max=64))
    assert "ensemble_size" not in failing(d)


def test_sampled_columns_that_do_not_follow_their_priors_fail_the_stage(tmp_path, monkeypatch):
    got = {}
    run = fake_run(got)

    def skewed(*a, **k):
        r = run(*a, **k)
        name = next(iter(r["res"]["X"]))
        r["res"]["X"][name] = np.full_like(r["res"]["X"][name], r["res"]["X"][name].min())
        return r
    monkeypatch.setattr(stage1, "run", skewed)
    ctx = ctx_for(tmp_path / "r")
    ctx._env = "ENV"
    ctx.plan["batch"] = 16
    with pytest.raises(ledger.StageFailed, match="sampled_marginals_match_priors"):
        run_stage(pipeline.s_stage1, ctx, "stage1")
    d = read_ledger(ctx.run_dir, "stage1")
    assert "common_random_numbers" in failing(d)                                                 # and they are not the draws of the seed either


def edited_res(monkeypatch, edit, tmp_path, plan=None):
    """stage1.run replaced by fake_run whose res is changed by `edit(res)`; -> the stage-1 ledger."""
    run = fake_run({})

    def edited(*a, **k):
        r = run(*a, **k)
        edit(r["res"])
        return r
    monkeypatch.setattr(stage1, "run", edited)
    ctx = ctx_for(tmp_path / "r")
    ctx._env = "ENV"
    ctx.plan.update(dict(batch=16, n_max=16), **(plan or {}))
    try:
        run_stage(pipeline.s_stage1, ctx, "stage1")
    except ledger.StageFailed:
        pass
    return read_ledger(ctx.run_dir, "stage1")


def test_the_crn_check_compares_the_stream_seeds_stage_1_used_and_passes_when_they_are_the_same_for_every_vehicle(tmp_path, monkeypatch):
    d = stage1_ledger(tmp_path, monkeypatch)
    c = check_of(d, "common_random_numbers")
    assert c["ok"] and c["value"] is True and "member_seed(seed, first member of a batch, stream)" in c["note"] and "batch size, 16 here" in c["note"]
    assert "every vehicle draws the same stream values per member" not in c["note"]                    # the old note claimed what the check did not test


def test_a_per_vehicle_stream_seed_fails_the_crn_check(tmp_path, monkeypatch):
    """The old check drew one stream once per 'vehicle' with identical arguments, so a vehicle-keyed seed in run_batch passed it."""
    def per_vehicle(res):
        res["seeds"]["w"]["uas/gust"] = sampling.member_seed(20230301, 0, "w/uas/gust")
    c = check_of(edited_res(monkeypatch, per_vehicle, tmp_path), "common_random_numbers")
    assert not c["ok"] and c["note"] == "w's stream seeds differ from v's"


def test_a_stream_seed_that_is_not_the_first_members_of_a_batch_fails_the_crn_check(tmp_path, monkeypatch):
    def wrong(res):
        for vid in res["seeds"]:
            res["seeds"][vid]["uas/gust"] = sampling.member_seed(20230301, 5, "uas/gust")             # member 5 is not the first of a batch of 16
    c = check_of(edited_res(monkeypatch, wrong, tmp_path), "common_random_numbers")
    assert not c["ok"] and "is not member_seed(seed, first member of a batch, stream)" in c["note"]


def test_every_batchs_first_member_is_an_allowed_stream_seed(tmp_path):
    """Two batches of 16 (n = 32): the merged result may carry the seed of either batch's first member, or both; n = 16 has only member 0."""
    ctx = ctx_for(tmp_path / "r")
    m = lambda f: sampling.member_seed(20230301, f, "uas/gust")
    res = lambda *firsts: dict(seeds={v: {"uas/gust": list(map(m, firsts))} for v in ("a", "b")})
    assert pipeline._stream_seed_problems(ctx, res(0, 16), 20230301, 16, 32) == [] and pipeline._stream_seed_problems(ctx, res(16), 20230301, 16, 32) == []
    assert pipeline._stream_seed_problems(ctx, res(0, 8), 20230301, 16, 32) != []                          # 8 is not the first member of a batch of 16
    assert pipeline._stream_seed_problems(ctx, res(16), 20230301, 16, 16) != []                            # a single batch has only member 0
    assert pipeline._stream_seed_problems(ctx, res(8), 20230301, 8, 32) == []                              # but batches of 8 do
    assert pipeline._stream_seed_problems(ctx, res(24), 20230301, 8, 32) == []


def test_seeds_are_compared_as_exact_python_ints_whatever_container_they_come_in():
    big = sampling.member_seed(20230301, 0, "uas/gust")
    assert big > 2 ** 63                                                                                  # numpy floats or int64 would round or wrap it
    assert pipeline._seed_list(big) == pipeline._seed_list(np.uint64(big)) == pipeline._seed_list(np.array([big], dtype=np.uint64)) == [big]
    assert pipeline._seed_list((big, 7, big)) == [7, big] and pipeline._seed_list({big}) == [big]


def test_a_mission_with_random_streams_whose_stage_1_returned_no_seeds_fails_the_crn_check(tmp_path, monkeypatch):
    c = check_of(edited_res(monkeypatch, lambda res: res.pop("seeds"), tmp_path), "common_random_numbers")
    assert not c["ok"] and "returned no stream seeds" in c["note"]


def test_a_mission_without_a_uas_or_iridium_link_has_no_streams_to_compare(tmp_path, monkeypatch):
    run = fake_run({})
    monkeypatch.setattr(stage1, "run", lambda *a, **k: (lambda r: (r["res"].pop("seeds"), r)[1])(run(*a, **k)))
    ctx = ctx_for(tmp_path / "r")
    ctx._env = "ENV"
    ctx.classes = {k: "glider" for k in ctx.classes}
    ctx.mission["links"] = [lk for lk in ctx.mission["links"] if lk["kind"] != "iridium"]
    ctx.plan.update(batch=16, n_max=16)
    run_stage(pipeline.s_stage1, ctx, "stage1")
    assert check_of(read_ledger(ctx.run_dir, "stage1"), "common_random_numbers")["ok"]


def left_env(limit=5.0):
    """An environment whose box ends at lon `limit` and which cannot raise (the lenient one)."""
    return types.SimpleNamespace(inside=lambda lon, lat, t: np.asarray(lon) < limit, lenient=lambda: __import__("contextlib").nullcontext())


def test_members_that_left_the_box_and_were_flagged_degrade_the_verdict_not_the_stage(tmp_path, monkeypatch):
    def leave(res):
        res["vehicles"]["v"].update(lat=np.zeros((2, 16)), t=np.array([0.0, 3600.0]))
        res["vehicles"]["v"]["lon"][1, [2, 7]] = 9.0                                                    # members 2 and 7 end outside
        res["vehicles"]["v"]["fail"] = dict(res["vehicles"]["v"]["fail"], left_data=np.isin(np.arange(16), [2, 7]))
        res["vehicles"]["w"].update(lat=np.zeros((2, 16)), t=np.array([0.0, 3600.0]))
        res["vehicles"]["w"]["fail"] = dict(res["vehicles"]["w"]["fail"], left_data=np.zeros(16, bool))
    run = fake_run({})
    monkeypatch.setattr(stage1, "run", lambda *a, **k: (lambda r: (leave(r["res"]), r)[1])(run(*a, **k)))
    ctx = ctx_for(tmp_path / "r")
    ctx._env = left_env()
    ctx.plan.update(batch=16, n_max=16)
    d = run_stage(pipeline.s_stage1, ctx, "stage1")
    c = check_of(d, "members_inside_data")
    assert c["ok"] and c["value"] == pytest.approx(1 - 2 / 32) and c["limit"] == 1.0
    assert "2 of 32 vehicle-members have a record outside the downloaded box, 2 are flagged left_data, 0 left unflagged" in c["note"]
    assert "widen box / pad_deg" in c["note"]


def test_a_member_that_left_the_box_without_being_flagged_fails_the_stage(tmp_path, monkeypatch):
    def leave(res):
        for vid in ("v", "w"):
            res["vehicles"][vid].update(lat=np.zeros((2, 16)), t=np.array([0.0, 3600.0]))
        res["vehicles"]["v"]["lon"][1, 3] = 9.0                                                         # outside, and nothing flagged it
    run = fake_run({})
    monkeypatch.setattr(stage1, "run", lambda *a, **k: (lambda r: (leave(r["res"]), r)[1])(run(*a, **k)))
    ctx = ctx_for(tmp_path / "r")
    ctx._env = left_env()
    ctx.plan.update(batch=16, n_max=16)
    with pytest.raises(ledger.StageFailed, match="members_inside_data"):
        run_stage(pipeline.s_stage1, ctx, "stage1")
    c = check_of(read_ledger(ctx.run_dir, "stage1"), "members_inside_data")
    assert not c["ok"] and "1 left unflagged" in c["note"] and c["value"] == pytest.approx(1 - 1 / 32)


def test_non_finite_positions_are_not_outside_the_box(tmp_path, monkeypatch):
    def gone(res):
        for vid in ("v", "w"):
            res["vehicles"][vid].update(lat=np.zeros((2, 16)), t=np.array([0.0, 3600.0]), lon=np.full((2, 16), np.nan))
    run = fake_run({})
    monkeypatch.setattr(stage1, "run", lambda *a, **k: (lambda r: (gone(r["res"]), r)[1])(run(*a, **k)))
    ctx = ctx_for(tmp_path / "r")
    ctx._env = left_env()
    ctx.plan.update(batch=16, n_max=16)
    assert check_of(run_stage(pipeline.s_stage1, ctx, "stage1"), "members_inside_data")["value"] == 1.0


def test_stage_1_runs_inside_the_lenient_environment_and_strictness_comes_back(tmp_path, monkeypatch):
    seen = []
    run = fake_run({})

    def probe(mission, env, *a, **k):
        seen.append(env.strict)
        r = run(mission, env, *a, **k)
        for v in r["res"]["vehicles"].values():
            v.update(lon=np.full((2, 16), -165.0), lat=np.zeros((2, 16)), t=np.array([T0, T0 + 3600.0]))        # inside the ci box
        return r
    monkeypatch.setattr(stage1, "run", probe)
    ctx = ctx_for(tmp_path / "r")
    ctx.plan.update(batch=16, n_max=16)
    assert ctx.env.strict
    run_stage(pipeline.s_stage1, ctx, "stage1")
    assert seen == [False] and ctx.env.strict  # real GriddedEnv: no OutsideData inside the run, strict outside


def test_the_real_environment_flags_a_track_that_leaves_the_ci_box(tmp_path):
    ctx = ctx_for(tmp_path / "r")
    lon = np.tile(np.array([[-165.0], [-165.0], [-150.0]]), (1, 3))
    lon[:, 1] = -165.0  # member 1 never leaves; members 0 and 2 end 15 degrees east of the box
    lon[2, 2] = -165.0
    v = dict(lon=lon, lat=np.zeros_like(lon), t=np.array([T0, T0 + 3600.0, T0 + 7200.0]), fail={"left_data": np.array([True, False, False])})
    L = ledger.Ledger(ctx.run_dir, "stage1", ctx.hash)
    with L:
        pipeline._members_inside_data(ctx, L, dict(vehicles={"a": v}))
    c = check_of(L.d, "members_inside_data")
    assert c["ok"] and c["value"] == pytest.approx(1 - 1 / 3) and "1 of 3 vehicle-members have a record outside" in c["note"]
    L = ledger.Ledger(ctx.run_dir, "stage1b", ctx.hash)
    with pytest.raises(ledger.StageFailed):
        with L:
            pipeline._members_inside_data(ctx, L, dict(vehicles={"a": dict(v, fail={})}))                   # no left_data mode recorded at all


def test_a_wilson_interval_that_disagrees_with_statsmodels_fails_the_stage(tmp_path, monkeypatch):
    from cafe.pm.stats import intervals
    real = intervals.interval
    monkeypatch.setattr(intervals, "interval", lambda k, n, conf=0.95: (real(k, n, conf)[0] + 0.001, real(k, n, conf)[1], "wilson"))
    c = check_of(stage1_ledger(tmp_path, monkeypatch), "wilson_matches_statsmodels")
    assert not c["ok"] and c["value"] == pytest.approx(0.001, abs=1e-9)


def test_a_vehicle_with_no_recorded_failure_mode_fails_the_stage(tmp_path, monkeypatch):
    run = fake_run({})

    def no_modes(*a, **k):
        r = run(*a, **k)
        r["res"]["vehicles"]["w"]["fail"] = {}
        return r
    monkeypatch.setattr(stage1, "run", no_modes)
    ctx = ctx_for(tmp_path / "r")
    ctx._env = "ENV"
    ctx.plan["batch"] = 16
    with pytest.raises(ledger.StageFailed):
        run_stage(pipeline.s_stage1, ctx, "stage1")
    assert failing(read_ledger(ctx.run_dir, "stage1")) == ["failure_modes_recorded"]


# ---- M-12 and the lead's addition (3): refit

def sphere_study(tmp_path, monkeypatch, runs=((100, 20), (100, 40))):
    from cafe.pm.stage3 import nest
    d = tmp_path / "receipts"
    d.mkdir()
    for tag, n in runs:
        (d / f"nest_sphere_{tag}_d{n}.json").write_text(json.dumps(dict(d=n, cd=1.0 + 1.0 / n)))
    monkeypatch.setattr(nest, "SLOW_DIR", d)
    return d


def test_the_stored_sphere_grid_study_is_a_ledger_input_of_the_refit_and_a_change_reruns_it(tmp_path, monkeypatch):
    d = sphere_study(tmp_path, monkeypatch)
    out, led = refit_run(tmp_path, {"usv": [stage3_row()]})
    ins = {pathlib.Path(i["ref"]).name: i for i in led["inputs"] if pathlib.Path(i["ref"]).name.startswith("nest_sphere")}
    assert set(ins) == {"nest_sphere_100_d20.json", "nest_sphere_100_d40.json"} and all(len(i["sha256"]) == 64 for i in ins.values())
    first = ins["nest_sphere_100_d20.json"]
    assert first["sha256"] == ledger.sha256(d / "nest_sphere_100_d20.json") and "discretisation floor" in first["kind"]
    assert out["usv"]["drag"]["sigma_discretisation"] > 0
    ctx = ctx_for(tmp_path / "r")
    assert ledger.done(ctx.run_dir, "refit", ctx.hash) is not None
    (d / "nest_sphere_100_d40.json").write_text(json.dumps(dict(d=40, cd=1.5)))                    # the stored grid changed
    assert ledger.done(ctx.run_dir, "refit", ctx.hash) is None


def test_without_a_stored_sphere_study_the_refit_has_no_such_input(tmp_path, monkeypatch):
    sphere_study(tmp_path, monkeypatch, runs=())
    assert not [i for i in refit_run(tmp_path, {"usv": [stage3_row()]})[1]["inputs"] if pathlib.Path(i["ref"]).name.startswith("nest_sphere")]


def test_the_refit_ledger_records_the_multiplier(tmp_path, monkeypatch):
    sphere_study(tmp_path, monkeypatch, runs=())
    out, d = refit_run(tmp_path, {"usv": [stage3_row(cd=1.3)], "uas": []})
    assert "refit_iterations_within_cap" not in [c["name"] for c in d["checks"]]                 # the passes are counted in stage 1b, where they are made
    assert len(d["notes"]) == 1 and d["notes"][0].startswith("usv: drag multiplier 1.300 (change vs baseline model +30.0%, sigma ")


# ---- M-12: emulator

def test_a_trained_emulator_also_records_its_training_points_and_refuses_a_far_mission(tmp_path, table, fake_stage1, monkeypatch):
    from cafe.pm import whatif
    seed_table(table)
    monkeypatch.setattr(whatif, "LIMITS", dict(rmse=0.05, coverage=0.5, query_ms=1e9))
    ctx = cheap_plan(synthetic_ctx(tmp_path, 48))
    d = run_stage(pipeline.s_emulator, ctx, "emulator")
    pts = check_of(d, "emulator_training_points_glider")
    assert pts["ok"] and pts["limit"] == whatif.MIN_ROWS and pts["value"] >= whatif.MIN_ROWS
    g = check_of(d, "emulator_range_guard_glider")
    assert g["ok"] and g["value"] <= g["limit"] and "1e6 units" in g["note"]


def test_an_emulator_that_answers_a_mission_far_outside_its_training_rows_fails_the_stage(tmp_path, table, fake_stage1, monkeypatch):
    from cafe.pm import emulator, whatif
    seed_table(table)
    monkeypatch.setattr(whatif, "LIMITS", dict(rmse=0.05, coverage=0.5, query_ms=1e9))
    real = emulator.Emulator.query
    monkeypatch.setattr(emulator.Emulator, "query", lambda self, x, alpha=0.1: dict(real(self, x, alpha), status="ok"))
    ctx = cheap_plan(synthetic_ctx(tmp_path, 48))
    with pytest.raises(ledger.StageFailed, match="emulator_range_guard_glider"):
        run_stage(pipeline.s_emulator, ctx, "emulator")


# ---------------------------------------------------------------------------------------------------------------- review round 5: M-20

def test_a_box_with_no_sea_cells_fails_the_ustar_check_by_name_and_does_not_raise(tmp_path):
    """M-20: with no sea node to sample, env.grid.interp was asked for zero points and ingest ended in 'cannot reshape array of size 0'."""
    ctx = ctx_for(tmp_path / "r")
    ctx.env.sea[:] = False
    assert pipeline._ustar_agreement(ctx.env)[0] == 0
    c = check_of(ingest_checks(ctx), "coare_ustar_vs_umwm_ust")
    assert not c["ok"] and c["value"] is None and c["note"] == "no sea nodes of the UMWM grid inside the box: widen the box or check the ocean mask"


# ---------------------------------------------------------------------------------------------------------------- round 5: M-6, M-10, M-13, M-15

@pytest.fixture(autouse=True)
def memory_unknown(monkeypatch):
    """The demo mission's 9 GB environment would be refused by `plan` in the small containers these tests run in (M-6); the memory model has its own
    tests below and in test_budget.py, which set the memory they need."""
    monkeypatch.setattr(par, "memory_gb", lambda: None)


def test_the_persistent_wind_prior_gets_a_95_percent_upper_bound_above_its_point_estimate():
    """M-10: 11 moorings with equal means have a point estimate near the floor; the 95 % bound on the spread is more than twice as large."""
    eq = pipeline.fit_wind_error({k: np.random.default_rng(i).normal(0, 1.0, 400) + 0.5 for i, k in enumerate("abcdefghijk")})
    assert eq["persistent_hi95"] > eq["persistent"] > 0 and eq["persistent_hi95"] > 2 * eq["persistent"]
    assert eq["moorings"] == 11


def test_the_upper_bound_of_the_persistent_spread_covers_a_known_spread_in_nine_of_ten_fits():
    fits = [pipeline.fit_wind_error(ar1_moorings(np.random.default_rng(100 + i), n_moor=11, n_t=300, persistent=0.5)) for i in range(30)]
    hits = [f["persistent_hi95"] >= 0.5 for f in fits]
    assert sum(hits) >= 27


def test_tao_writes_value_hi95_beside_the_persistent_value_with_its_citation(tmp_path, data):
    ctx, t0, t1 = tao_ctx(tmp_path)
    tao_stage(ctx, t0, t1)
    fit = json.loads((ctx.run_dir / "ingest" / "priors_fitted.json").read_text())
    for k in ("wind_speed_bias", "wind_direction_bias"):
        assert fit[k]["value_hi95"] > fit[k]["value"] and fit[k]["citation_hi95"] == "95 % upper bound of the between-mooring variance, 1 degrees of freedom"
    assert "value_hi95" not in fit["wind_speed_noise"]


def test_the_emulator_ledger_has_the_planned_and_measured_variant_seconds_and_no_self_comparing_check(tmp_path, table, fake_stage1):
    """M-13: the old check compared `len(variants) x est` with the share, which the sizing guarantees; the ledger now says planned, measured and the share."""
    ctx = cheap_plan(synthetic_ctx(tmp_path, 48, unused_refit=True), 100.0)
    d = run_stage(pipeline.s_emulator, ctx, "emulator")
    design = json.loads((ctx.run_dir / "emulator" / "design.json").read_text())
    assert "emulator_variants_within_share" not in [c["name"] for c in d["checks"]]
    assert any(n.startswith("variant runs: planned 12 s (3 x 4 s), measured ") and "emulator share 20 s" in n and "lower bound" in n for n in d["notes"])
    assert d["variant_planned_s"] == 4.0 and len(d["variant_wall_s"]) == 3 and all(w >= 0 for w in d["variant_wall_s"])
    # round 6 M-17: stage 1b is not "a copy" when its sensitivity case ran; the share note says why stage 1b's share is in it
    assert any("(stage 1b's share included, since no vehicle was refit)" in n for n in d["notes"]) and not any("which was a copy" in n for n in d["notes"])
    assert design["variant_planned_s"] == 4.0 and "variant_wall_s" not in design and "wall_s" not in json.dumps(design)       # DECISIONS 139: no timing


def test_a_resume_under_another_worker_count_reruns_the_emulator_and_reuses_stage_1(tmp_path, monkeypatch):
    """M-15: the demo plans 1 emulator variant on 1 worker and 6 on 8; the hash of the stages before the emulator does not move, the emulator's does."""
    demo = ROOT / "missions" / "tepex_c_demo.yaml"
    monkeypatch.setenv("CAFE_WORKERS", "1")
    a = ctx_for(tmp_path / "a", "quick", demo)
    monkeypatch.setenv("CAFE_WORKERS", "8")
    b = ctx_for(tmp_path / "b", "quick", demo)
    assert a.plan["workers"] == 1 and b.plan["workers"] == 8 and a.plan["emulator"]["variants_no_refit"] != b.plan["emulator"]["variants_no_refit"]
    assert a.hash == b.hash and [a.stage_hash(n) == b.stage_hash(n) for n in STAGES] == [True] * STAGES.index("emulator") + [False] * 2
    calls = []
    stub_stages(monkeypatch, calls)
    run = tmp_path / "run"
    monkeypatch.setenv("CAFE_WORKERS", "1")
    pipeline.run(demo, "quick", 0, run, log=lambda s: None)
    assert calls == STAGES
    del calls[:]
    pipeline.run(demo, "quick", 0, run, log=lambda s: None)
    assert calls == []                                                                                     # the same count: everything up to date
    monkeypatch.setenv("CAFE_WORKERS", "8")
    pipeline.run(demo, "quick", 0, run, log=lambda s: None)
    assert calls == ["emulator", "report"]                                                                 # stage 1 and 1b are reused


def test_the_workers_of_a_run_are_the_cpus_cut_to_what_the_memory_holds_and_every_stage_sees_that_count(tmp_path, monkeypatch):
    """M-6: a 1 GB container holds one worker besides the 0.08 GB environment of the CI window (its 4 x 4 deg box, 1.5 days: M-2 of round 6);
    the pool, `par.workers()` in the stages and the plan agree."""
    monkeypatch.delenv("CAFE_WORKERS")
    monkeypatch.setattr(par, "memory_gb", lambda: 1.0)
    monkeypatch.setattr(par.os, "sched_getaffinity", lambda pid: set(range(8)))
    real = pathlib.Path.read_text
    monkeypatch.setattr(pathlib.Path, "read_text", lambda self, *a, **k: real(self, *a, **k) if str(self) != "/sys/fs/cgroup/cpu.max" else "max 100000")
    seen, log = [], []
    stub_stages(monkeypatch, [])
    stub = pipeline.FUNCS["ingest"]
    monkeypatch.setitem(pipeline.FUNCS, "ingest", lambda ctx, L: (seen.append((par.workers(), par.width())), stub(ctx, L)))
    ctx = go(tmp_path / "run", log)
    plan = json.loads((tmp_path / "run" / "plan.json").read_text())
    assert (plan["workers_by_cpu"], plan["workers_by_memory"], plan["workers"], ctx.plan["workers"]) == (8, 1, 1, 1) and plan["mem_gb"] == 1.0
    assert plan["env_gb"] == pytest.approx(0.0756, abs=1e-4) and seen == [(1, 1)] and any(m.startswith("workers: 1 ") for m in log)
    assert "capped from 8 by memory" in log[0] and par.workers() == 8                                      # and the cap is gone after the run


# ---- review round 6, M-5: no usable wind direction at the moorings leaves the configured priors alone ----------------------------------------------
@pytest.mark.parametrize("calm", [True, False], ids=["no-direction-at-all", "only-the-mean-is-nan"])
def test_a_comparison_without_a_usable_wind_direction_writes_no_direction_prior_and_stage1_accepts_the_fit(tmp_path, data, monkeypatch, calm):
    """M-5: a calm WRF (or moorings without a direction channel) wrote `wind_direction_bias: {mean: null, value: null}` and stage 1 died with a TypeError."""
    ctx, t0, t1 = tao_ctx(tmp_path)
    real_cmp, real_res = tao.compare, pipeline._wind_residuals
    nan = float("nan")
    nan_dir = {"dir_bias_deg": nan, **({"dir_rmse_deg": nan} if calm else {})}

    def compare(wrf, moor):
        out = real_cmp(wrf, moor)
        return {**out, "ALL": {**out["ALL"], **nan_dir}}
    monkeypatch.setattr(tao, "compare", compare)
    if calm:
        monkeypatch.setattr(pipeline, "_wind_residuals",
                            lambda wrf, moor: {k: np.column_stack([v[:, 0], np.full(len(v), nan)]) for k, v in real_res(wrf, moor).items()})
    d = tao_stage(ctx, t0, t1)
    fit = json.loads((ctx.run_dir / "ingest" / "priors_fitted.json").read_text())
    assert set(fit) >= {"wind_speed_bias", "wind_speed_noise"} and not [k for k in fit if k.startswith("wind_direction")]
    assert any("no usable wind direction at the moorings (dir_n " in n and "stay the perturbations.yaml priors" in n for n in d["notes"])
    nums = [x for e in fit.values() for x in e.values() if isinstance(x, (int, float)) and not isinstance(x, bool)]   # no null and no NaN in any prior
    assert all(np.isfinite(x) for x in nums) and not [k for e in fit.values() for k, x in e.items() if x is None]
    assert np.isfinite(fit["wind_speed_bias"]["mean"])
    pri, marg = stage1.priors_for(ctx.mission, fit)                                  # the TypeError of `np.isfinite(None)` before
    assert marg["wind_direction_bias"]["sd"] == pri["wind_direction_bias"]["value"] and marg["wind_speed_bias"]["mean"] == fit["wind_speed_bias"]["mean"]


# ---- review round 6, M-8: a truncated or empty cache JSON is repaired by a fetch or named, never a JSONDecodeError

def test_r6_m8_an_empty_or_truncated_orca_manifest_is_fetched_again_and_says_so(tmp_path, data_copy, monkeypatch):
    monkeypatch.delenv("CAFE_OFFLINE")
    man = data_copy / "cache" / "ci_fixture" / "orca" / "manifest.json"
    saved = man.read_text()
    calls, logged = [], []

    def fake_ingest(t0, t1, box, out, hours3d=(), threads=8, spectra=True, log=print):
        calls.append(box)
        man.write_text(saved)
    monkeypatch.setattr(orca, "ingest", fake_ingest)
    for damage in ("", saved[:40]):
        calls.clear()
        man.write_text(damage)
        run_stage(pipeline.s_ingest, ctx_for(tmp_path / f"r{len(damage)}", log=logged.append), "ingest")
        assert len(calls) == 1
    assert any("orca manifest" in x and "unreadable" in x and "fetching again" in x for x in logged)


def test_r6_m8_an_unreadable_orca_manifest_offline_fails_the_check_naming_the_command(tmp_path, data_copy):
    (data_copy / "cache" / "ci_fixture" / "orca" / "manifest.json").write_text("")
    with pytest.raises(ledger.StageFailed, match="orca_present"):
        run_stage(pipeline.s_ingest, ctx_for(tmp_path / "r"), "ingest")
    notes = {c["name"]: c["note"] for c in read_ledger(tmp_path / "r", "ingest")["checks"] if not c["ok"]}
    assert "python -m cafe.pm fetch --mission" in notes["orca_present"]


def test_r6_m8_an_empty_or_truncated_tao_manifest_is_not_cached(data_copy):
    tdir = data_copy / "tao"
    mp = tdir / "manifest.json"
    m = config.load_mission(MISSION_PATH)
    box, t0, t1 = pipeline.ocean_box(m), config.utc(m["window"]["start"]).timestamp(), config.utc(m["window"]["end"]).timestamp()
    saved = mp.read_text()
    assert pipeline._tao_cached(tdir, box, t0, t1) is True
    for damage in ("", saved[:30]):
        mp.write_text(damage)
        assert pipeline._tao_cached(tdir, box, t0, t1) is False


def test_r6_m8_a_corrupt_umwm_zarr_json_is_a_config_error_naming_the_file_and_the_fix(data_copy):
    cache = data_copy / "cache" / "ci_fixture"
    (cache / "orca" / "umwm.zarr" / "zarr.json").write_text("{garbage")
    with pytest.raises(config.ConfigError, match=rf"cache file {cache}/orca/umwm.zarr cannot be read .*delete {cache}/orca and run `python -m cafe.pm fetch"):
        pipeline._umwm_depth(cache)


def test_the_stage_1b_copy_note_and_ledger_say_how_long_the_sensitivity_case_ran(tmp_path, monkeypatch, sens):
    """Round 6 M-17: the ledger called stage 1b a copy although it had run a 30 s USV case that no share was charged."""
    ctx = ctx_for(tmp_path / "r")
    stage1_files(ctx)
    ctx.path("refit", "refit.json").write_text(json.dumps({"usv": dict(used=False, reason="x")}))
    ticks = iter([100.0, 130.0])
    monkeypatch.setattr(pipeline, "time", types.SimpleNamespace(time=time.time, perf_counter=lambda: next(ticks)))           # only this module's clock
    d = run_stage(pipeline.s_stage1b, ctx, "stage1b")
    assert d["sensitivity_wall_s"] == 30.0
    assert d["notes"][1] == ("no vehicle was refit: stage 1b is stage 1 (copied, not rerun); the sensitivity case reran the USV in 30 s, "
                             "not charged to any share")
    ctx2 = ctx_for(tmp_path / "r2")                                                           # no USV: no case ran, the note is the old one
    ctx2.mission = dict(ctx2.mission, vehicles=[v for v in ctx2.mission["vehicles"] if pipeline.stage1._classes(ctx2.mission)[v["id"]] != "usv"])
    stage1_files(ctx2)
    ctx2.path("refit", "refit.json").write_text(json.dumps({}))
    d2 = run_stage(pipeline.s_stage1b, ctx2, "stage1b")
    assert "sensitivity_wall_s" not in d2 and d2["notes"] == ["no vehicle was refit: stage 1b is stage 1 (copied, not rerun)"]


def test_the_plan_is_made_again_at_the_end_of_the_ingest_with_the_stores_it_put_on_disk(tmp_path, data_copy, monkeypatch):
    """M-2: the plan was made once, before the ingest, so a cold-cache run had no disk floor; a store the ingest wrote that is larger than the
    model now changes the memory term, plan.json and the worker count."""
    monkeypatch.delenv("CAFE_WORKERS")
    monkeypatch.setattr(par, "_limit", None)
    monkeypatch.setattr(par, "memory_gb", lambda: 3.0)
    monkeypatch.setattr(par.os, "sched_getaffinity", lambda pid: set(range(8)))
    real = pathlib.Path.read_text
    monkeypatch.setattr(pathlib.Path, "read_text", lambda self, *a, **k: real(self, *a, **k) if str(self) != "/sys/fs/cgroup/cpu.max" else "max 100000")
    log = []
    ctx = ctx_for(tmp_path / "r", log=log.append)
    assert ctx.plan["workers"] == 3 and ctx.plan["workers_by_memory"] == 3 and ctx.plan["env_gb"] == pytest.approx(0.0756, abs=1e-4)
    cold = json.loads(json.dumps(ctx.plan))
    (ctx.cache / "orca" / "big.zarr").mkdir()
    with open(ctx.cache / "orca" / "big.zarr" / "0", "wb") as f:
        f.truncate(2 * 10 ** 9)                                                                  # what a larger box's download leaves on disk
    run_stage(pipeline.s_ingest, ctx, "ingest")
    assert ctx.plan["env_gb"] >= 2.0 and ctx.plan["workers_by_memory"] == 1 and ctx.plan["workers"] == 1 and ctx.plan != cold
    assert json.loads((tmp_path / "r" / "plan.json").read_text())["workers"] == 1 and par.workers() == 1
    assert any("the plan changed now that the cache is on disk: environment 0.1 GB -> " in m and "workers 3 -> 1" in m for m in log)
    quiet_again = len(log)
    assert ctx.replan() is False and len(log) == quiet_again                                     # nothing changed: nothing printed
    assert pipeline.Context(MISSION_PATH, "ci", 0, tmp_path / "r2").plan == ctx.plan             # a resume (warm cache) plans the same
    (ctx.cache / "orca" / "big.zarr" / "0").write_bytes(b"")
    with open(ctx.cache / "orca" / "big.zarr" / "0", "wb") as f:
        f.truncate(5 * 10 ** 9)
    with pytest.raises(budget.PlanError, match="needs about 5 GB for the environment"):
        ctx.replan()                                                                             # no longer fits: the refusal names the sizes
    bare = pipeline.Context(MISSION_PATH, None, 0, tmp_path / "f", log.append)
    assert bare.replan() is False and bare.plan == {}


def test_a_plan_made_again_without_a_memory_figure_prints_unknown(tmp_path, monkeypatch):
    monkeypatch.setattr(par, "memory_gb", lambda: None)
    ctx = ctx_for(tmp_path / "r")
    assert ctx.plan["env_gb"] is None and ctx.replan() is False
    assert pipeline._gb(None) == "unknown" and pipeline._gb(2.25) == "2.2 GB"


def test_cafe_offline_reads_1_true_yes_on_as_offline_and_0_false_no_off_as_online_and_nothing_else(monkeypatch):
    """M-23: `false` and `no` turned offline mode on (anything but '' and '0' did)."""
    monkeypatch.delenv("CAFE_OFFLINE")
    assert pipeline._offline() is False
    for v in ("", "0", "false", "False", "NO", "off"):
        monkeypatch.setenv("CAFE_OFFLINE", v)
        assert pipeline._offline() is False, v
    for v in ("1", "true", "TRUE", "yes", "On"):
        monkeypatch.setenv("CAFE_OFFLINE", v)
        assert pipeline._offline() is True, v
    monkeypatch.setenv("CAFE_OFFLINE", "maybe")
    with pytest.raises(config.ConfigError, match="CAFE_OFFLINE='maybe' is not 0 or 1; set CAFE_OFFLINE=1 to download nothing, or 0 or unset it"):
        pipeline._offline()


def test_r7_m1_a_context_keeps_the_missions_own_verdict_cut_offs_after_it_plans(tmp_path, monkeypatch):
    from cafe.pm.stats import intervals
    for name in ("P_FAIL_GO", "P_FAIL_NOGO", "LO_SUCCESS_GO"):
        monkeypatch.setattr(intervals, name, getattr(intervals, name))
    p = tmp_path / "m.yaml"
    p.write_text((ROOT / "missions" / "tepex_c_demo.yaml").read_text().replace("verdict: {go: 0.9, nogo: 0.6}", "verdict: {go: 0.8, nogo: 0.5}"))
    pipeline.Context(p, "quick", 0, tmp_path / "r", quiet)
    assert (intervals.P_FAIL_GO, intervals.P_FAIL_NOGO) == (pytest.approx(0.2), 0.5)


def test_r7_m32_ocean_box_across_0_deg_e_is_a_config_error_for_a_mission_loaded_without_validation():
    m = yaml.safe_load((ROOT / "missions" / "tepex_c_demo.yaml").read_text())
    m["box"].update(lon_min=-15.0, lon_max=15.0)
    with pytest.raises(config.ConfigError, match=r"crosses 0 deg E; the GLBy ocean fetch cannot cross it: move the box east or west of 0 deg, or split"):
        pipeline.ocean_box(m)
    assert pipeline.ocean_box(yaml.safe_load((ROOT / "missions" / "tepex_c_demo.yaml").read_text()))[2:] == (163.0, -163.0)


# ---------------------------------------------------------------------------------------------------------------- review round 7: M-7, M-14, M-22

@pytest.mark.parametrize("M,batch,budget_s,n_variants", [(48, 16, 100.0, 3), (96, 32, 40.0, 1), (256, 64, 40.0, 1)])
def test_no_variant_and_no_fresh_draw_reuses_a_member_stage_1b_used(tmp_path, table, fake_stage1, monkeypatch, M, batch, budget_s, n_variants):
    """Round 7 M-7: variant 0 ran members `batch` .. 2 x batch - 1, the very hypercube and noise streams of stage 1's second batch (the base row's
    ensemble is all M members); the fresh-draw blocks started at (variants + 2) x batch, inside a longer ensemble (4h: M 256, batch 64, one variant)."""
    from cafe.pm import whatif
    seed_table(table, n=100)
    monkeypatch.setattr(whatif, "LIMITS", dict(rmse=0.05, coverage=0.5, query_ms=1e9))
    ctx = cheap_plan(synthetic_ctx(tmp_path, M, unused_refit=True), budget_s)
    ctx.plan["batch"] = batch
    run_stage(pipeline.s_emulator, ctx, "emulator")
    assert len(json.loads((ctx.run_dir / "emulator" / "design.json").read_text())["variants"]) == n_variants
    runs = [c[1] for c in fake_stage1]
    variants, later = runs[:n_variants], [m for m in runs[n_variants:] if m != list(range(batch))]       # the flip search's fallback uses the base members
    assert variants[0][0] == -(-M // batch) * batch
    blocks = [set(m) for m in variants + later]
    assert all(len(b) == batch for b in blocks) and not set().union(*blocks) & set(range(M)) and sum(map(len, blocks)) == len(set().union(*blocks))


def test_a_calibration_without_a_refit_sizes_the_variants_for_the_emulators_own_share(tmp_path, table, fake_stage1):
    """Round 7 M-14: with stage3/subgrid_calibration.json and no refit stage 1b reran, so the share is the emulator's own 5 % (5 s here), but the count
    was the one sized for the share with stage 1b's added (3 variants), which only the wall clock then cut short."""
    from cafe.pm.env import subgrid
    ctx = cheap_plan(synthetic_ctx(tmp_path, 48, unused_refit=True), 100.0)
    ctx.path("stage3", "subgrid_calibration.json").parent.mkdir(exist_ok=True)
    ctx.path("stage3", "subgrid_calibration.json").write_text(json.dumps(dict(source_run="t")))
    try:
        run_stage(pipeline.s_emulator, ctx, "emulator")
    finally:
        subgrid.use_calibration(None)
    d = json.loads((ctx.run_dir / "emulator" / "design.json").read_text())
    sizes = budget.emulator_plan(ctx.plan)
    assert d["share_s"] == 5.0 and not d["stage1b_free"] and d["planned_variants"] == sizes["variants_refit"] == 0 != sizes["variants_no_refit"]
    assert d["variants"] == [] and d["killed"] is None


def ensemble_note(tmp_path, monkeypatch, **plan):
    d = stage1_ledger(tmp_path, monkeypatch, plan=plan)
    return next(c for c in d["checks"] if c["name"] == "ensemble_size")["note"]


def test_the_ensemble_size_note_names_the_profile_that_caps_the_ensemble_and_the_share_when_it_is_the_share(tmp_path, monkeypatch):
    """Round 7 M-22: q7 (quick) planned 64 members from the table constant `N_MAX`, used 13 % of its share, and the note blamed 'the budget'."""
    note = ensemble_note(tmp_path / "a", monkeypatch, budget="quick", n_max=64, stage1_share_s=900.0)
    assert "because the quick budget profile caps the ensemble at 64 members (budget.N_MAX); the stage-1 share (900 s) would have allowed more: " \
           "use --budget 4h to certify" in note
    note = ensemble_note(tmp_path / "b", monkeypatch, budget="quick", n_max=32, stage1_share_s=40.0)
    assert "because the stage-1 share (40 s) caps the ensemble at 32 members: use a longer --budget" in note and "profile" not in note


# ---- review round 7: M-2 (a missing or old-layout derived layer is a failed check), M-12 (a lab store must cover the window, whatever its cadence)

def test_r7_m2_a_missing_or_old_layout_derived_layer_fails_derived_unchanged_instead_of_running_on_the_neutral_profile(tmp_path, data_copy):
    store = data_copy / "cache" / "ci_fixture" / "derived.zarr"
    ctx = ctx_for(tmp_path / "r")                                                                  # the record ingest leaves is there
    assert ctx.env.subgrid is not None
    pipeline._derived_unchanged(ctx, L := ledger.Ledger(tmp_path / "ok", "s", "h"))
    assert [c["ok"] for c in L.d["checks"]] == [True]
    z = json.loads((store / "zarr.json").read_text())
    z["attributes"]["layout_version"] = surface.LAYOUT_VERSION + 1                                 # another layout
    (store / "zarr.json").write_text(json.dumps(z))
    for how in ("old layout", "missing"):
        if how == "missing":
            shutil.rmtree(store)
        fresh = pipeline.Context(MISSION_PATH, "ci", 0, tmp_path / "r", quiet)                      # a new context builds its env from what is on disk now
        L = ledger.Ledger(tmp_path / how.replace(" ", "_"), "s", "h")
        pipeline._derived_unchanged(fresh, L)
        c = check_of(L.d, "derived_unchanged")
        assert fresh.env.subgrid is None and not c["ok"], how
        assert "is missing or has another layout" in c["note"] and "python -m cafe.pm fetch --mission" in c["note"], how
    with pytest.raises(ledger.StageFailed, match="derived_unchanged: .*is missing or has another layout"):
        with ledger.Ledger(tmp_path / "stage", "stage1", "h") as L:                                   # the check fails the stage that would read the layer
            pipeline._derived_unchanged(fresh, L)
    fresh._env = "ENV"                                                                              # an analytic environment still records nothing
    pipeline._derived_unchanged(fresh, L := ledger.Ledger(tmp_path / "y", "s", "h"))
    assert L.d["checks"] == []


def test_r7_m2_a_truncated_chunk_of_the_derived_layer_stops_the_context_with_a_config_error(tmp_path, data_copy):
    chunk = next(p for p in sorted((data_copy / "cache" / "ci_fixture" / "derived.zarr" / "ustar").rglob("*")) if p.is_file() and p.name != "zarr.json")
    chunk.write_bytes(b"x")
    ctx = pipeline.Context(MISSION_PATH, "ci", 0, tmp_path / "r", quiet)
    with pytest.raises(config.ConfigError, match=r"derived surface layer .*derived\.zarr cannot be read .*delete .* and run `python -m cafe\.pm fetch"):
        assert ctx.env is None


def _lab_mission(tmp_path, store):
    raw = yaml.safe_load(MISSION_PATH.read_text())
    raw["environment"]["ocean"] = dict(source="lab_hycom", path=str(store))
    (tmp_path / "lab.yaml").write_text(yaml.safe_dump(raw))
    return tmp_path / "lab.yaml"


def _cadence_store(src, dst, idx):
    """The CI ocean store cut to the time steps `idx` (the lab's own cadence), written the way ingest_lab_hycom writes a store."""
    from cafe.pm.env import hycom
    ds = hycom.open_store(src).load()
    hycom.write_store((hycom._std(ds.isel(time=slice(i, i + 1))) for i in idx), dst, "in_situ", dict(source=f"lab HYCOM {dst.name}"))
    return dst


def test_r7_m12_a_six_hourly_lab_store_covers_the_window_and_is_cached_while_gofs_still_wants_every_step(tmp_path, data):
    from cafe.pm.env import hycom
    store6 = _cadence_store(data.ocean_store, tmp_path / "lab6.zarr", range(0, 13, 2))               # 18Z, 00Z, ... 06Z: 6-hourly over the 36 h window
    box = (-2.0, 2.0, -167.0, -163.0)
    window = (T0, T1)
    steps = hycom.gofs_steps(T0, T1)
    assert pipeline._ocean_cached(store6, box, steps, window)                                        # False before: the 3-hourly steps are not all in it
    assert not pipeline._ocean_cached(store6, box, steps)                                            # GOFS: membership of the steps, unchanged
    assert pipeline._ocean_cached(data.ocean_store, box, steps, window) and pipeline._ocean_cached(data.ocean_store, box, steps)
    assert not pipeline._ocean_cached(store6, box, steps, (T0 - 7200.0, T1))
    assert not pipeline._ocean_cached(store6, box, steps, (T0, T1 + 7200.0))
    assert pipeline._ocean_cached(store6, box, steps, (T0 + 3600.0, T1 - 3600.0))                    # a window inside the span: interpolated in time
    t = hycom.open_store(store6).time.values
    assert pipeline._ocean_time_problem(t, window) is None
    assert pipeline._ocean_time_problem(t, (T0 - 7200.0, T1)).endswith("the store starts 2.0 h after the window start")
    assert pipeline._ocean_time_problem(t, (T0, T1 + 5400.0)).endswith("the store ends 1.5 h before the window end")
    both = pipeline._ocean_time_problem(t, (T0 - 3600.0, T1 + 3600.0))
    assert "starts 1.0 h after the window start and ends 1.0 h before the window end" in both and "2023-03-01 18:00 to 2023-03-03 06:00 UTC" in both


def test_r7_m12_ingest_accepts_a_six_hourly_lab_store_and_a_store_that_ends_early_fails_naming_the_edge(tmp_path, data_copy):
    ok = _cadence_store(data_copy / "ocean" / "gofs_ci_fixture.zarr", data_copy / "ocean" / "lab6.zarr", range(0, 13, 2))
    d = run_stage(pipeline.s_ingest, ctx_for(tmp_path / "a", mission=_lab_mission(tmp_path, ok)), "ingest")
    assert check_of(d, "ocean_store_present")["ok"]
    short = _cadence_store(data_copy / "ocean" / "gofs_ci_fixture.zarr", data_copy / "ocean" / "lab_short.zarr", range(0, 5, 2))
    with pytest.raises(ledger.StageFailed, match="ocean_store_present"):
        run_stage(pipeline.s_ingest, ctx_for(tmp_path / "b", mission=_lab_mission(tmp_path, short)), "ingest")
    note = check_of(read_ledger(tmp_path / "b", "ingest"), "ocean_store_present")["note"]
    assert "lab_short.zarr" in note and "its times span 2023-03-01 18:00 to 2023-03-02 06:00 UTC" in note
    assert "the store ends 24.0 h before the window end" in note


# ---- review round 8: M-4 (the contents of the ocean store), M-23 (a cut checkpoint ledger), M-35 (Bellhop in the code digest)

def _ocean_store_of(data_copy):
    return data_copy / "ocean" / "gofs_ci_fixture.zarr"


def test_r8_m4_a_changed_ocean_store_is_not_up_to_date_and_the_audit_names_it(tmp_path, data_copy):
    """Resume and the audit compared the store's own manifest attribute, written at assembly: 9 m/s written into `water_u` afterwards was 'up to date'."""
    import zarr
    store = _ocean_store_of(data_copy)
    ctx = ctx_for(tmp_path / "r")
    d = run_stage(pipeline.s_ingest, ctx, "ingest")
    rec = next(i for i in d["inputs"] if i["ref"] == str(store))
    assert rec["tree_sha256"] == ledger.tree_sha256(store) and rec["sha256"] != rec["tree_sha256"]
    c = check_of(d, "ocean_store_nan_mask")
    assert c["ok"] and c["value"] == 0 and c["limit"] == 0
    derived = next(i for i in d["inputs"] if i["ref"].endswith("derived.zarr"))
    assert derived["tree_sha256"] == surface.store_sha256(data_copy / "cache" / "ci_fixture" / "derived.zarr")
    assert ledger.done(ctx.run_dir, "ingest", ctx.hash) is not None
    assert [p for p in audit.ledger_problems(ctx.run_dir) if str(store) in p] == []
    g = zarr.open_group(store, mode="r+")
    g["water_u"][...] = 9.0
    assert ledger.done(ctx.run_dir, "ingest", ctx.hash) is None
    probs = [p for p in audit.ledger_problems(ctx.run_dir) if str(store) in p]
    assert len(probs) == 1 and "changed since the stage ran (tree " in probs[0] and "run `fetch` again" in probs[0]


def test_r8_m4c_the_assembled_orca_stores_are_tree_hashed_inputs_and_a_changed_one_is_not_up_to_date(tmp_path, data_copy):
    """The orca manifest lists the hourly parts, not the assembled wrf.zarr / umwm.zarr: wind x 3 in a store left the ingest 'up to date', the audit clean."""
    orca_dir = data_copy / "cache" / "ci_fixture" / "orca"
    ctx = ctx_for(tmp_path / "r")
    d = run_stage(pipeline.s_ingest, ctx, "ingest")
    got = {pathlib.Path(i["ref"]).name: i for i in d["inputs"] if "tree_sha256" in i and i["ref"].startswith(str(orca_dir))}
    assert set(got) == {n for n in pipeline.ORCA_STORES if (orca_dir / n).is_dir()} and "wrf.zarr" in got and "umwm.zarr" in got
    assert all(i["tree_sha256"] == ledger.tree_sha256(orca_dir / n) for n, i in got.items())
    assert ledger.done(ctx.run_dir, "ingest", ctx.hash) is not None and [p for p in audit.ledger_problems(ctx.run_dir) if "wrf.zarr" in p] == []
    chunk = next(f for f in sorted((orca_dir / "wrf.zarr").rglob("*")) if f.is_file() and f.name != "zarr.json")
    chunk.write_bytes(chunk.read_bytes() + b"\0")
    assert ledger.done(ctx.run_dir, "ingest", ctx.hash) is None
    assert any(str(orca_dir / "wrf.zarr") in p and "(tree " in p for p in audit.ledger_problems(ctx.run_dir))


def test_r8_m4_a_chunk_of_the_ocean_store_deleted_before_the_ingest_fails_the_nan_mask_check_with_the_count(tmp_path, data_copy):
    """A deleted chunk reads as NaN where the sea was: nothing named it (the store is hashed as it is found, so the hash cannot tell)."""
    from cafe.pm.env import hycom
    store = _ocean_store_of(data_copy)
    assert pipeline.ocean_store_nan_mask(hycom.open_store(store)) == 0
    chunk = sorted((store / "water_v").rglob("*"))
    chunk = next(f for f in chunk if f.is_file() and f.name != "zarr.json" and f.name != ".zarray")
    chunk.unlink()
    holes = pipeline.ocean_store_nan_mask(hycom.open_store(store))
    assert holes > 0
    with pytest.raises(ledger.StageFailed, match="ocean_store_nan_mask"):
        run_stage(pipeline.s_ingest, ctx_for(tmp_path / "r"), "ingest")
    c = check_of(read_ledger(tmp_path / "r", "ingest"), "ocean_store_nan_mask")
    assert not c["ok"] and c["value"] == holes and c["limit"] == 0


def test_r8_m23_a_cut_ledger_reruns_its_stage_on_resume_and_the_run_audits_clean(tmp_path, monkeypatch):
    calls = []
    stub_stages(monkeypatch, calls)
    go(tmp_path / "run")
    p = tmp_path / "run" / "checkpoints" / "ingest" / "ledger.json"
    p.write_text(p.read_text()[:200])
    assert any("is not valid JSON" in x for x in audit.ledger_problems(tmp_path / "run"))
    calls.clear()
    go(tmp_path / "run")
    assert calls == STAGES and audit.ledger_problems(tmp_path / "run") == []


def test_r8_m35_installing_bellhop_changes_the_code_digest_and_nothing_else_does(monkeypatch, tmp_path):
    from cafe.pm.physics import comms
    monkeypatch.setattr(comms, "_bellhop_dir", lambda: None)
    before = pipeline.code_digest()
    assert pipeline.code_digest() == before
    (tmp_path / "bellhop.exe").write_bytes(b"build one")
    monkeypatch.setattr(comms, "_bellhop_dir", lambda: str(tmp_path))
    installed = pipeline.code_digest()
    assert installed != before
    (tmp_path / "bellhop.exe").write_bytes(b"build two")
    assert pipeline.code_digest() not in (before, installed)
