"""Reproducibility (BRIEF 5.3: same seed -> identical report.json), on the CI mission through the real pipeline.

Two runs with the same seed, each in its own run directory with its own copy of one emulator table, must give the same report.json once the
timings, paths, host, git sha and library versions are removed, and the same bytes in every hashed file the receipts name (two exceptions that
`comparable` spells out: `emulator/holdout.json` holds the measured query time BRIEF 2.7 asks for, and `report/credibility.json` names its run
directory). Stage 3 is the stand-in of tests/test_pipeline.py in one pair of runs and the real LES windows, FEA and priced free-surface case in
the other. The module has its own fixtures so that no patch of another module's fixtures (a stand-in stage 3 held until the end of
test_pipeline) can stand in for the real one.
"""
import hashlib
import json
import shutil
import sys
import types

import pytest

import cafe.pm.stage3 as stage3_pkg
import cafe.pm.stage3.pipeline_windows as real_windows
from cafe.pm import budget, config, pipeline
from cafe.pm.env import ocean as ocean_mod
from tests.fixtures.fakes import fake_module
from tests.test_pipeline import Rows, quiet, read_ledger, seed_table, small_budget

MISSION_PATH = config.ROOT / "missions" / "ci_fixture.yaml"


@pytest.fixture(scope="module")
def data(ci_env):
    """pipeline and env.ocean read the synthetic tree of ci_env."""
    mp = pytest.MonkeyPatch()
    mp.setattr(pipeline, "DATA", ci_env.data)
    mp.setattr(ocean_mod, "DATA", ci_env.data)
    mp.setenv("CAFE_DATA", str(ci_env.data))
    yield ci_env
    mp.undo()


TIMING = ("run", "machine.wall_s", "machine.git_sha", "machine.versions", "machine.machine")        # what differs between runs of the same code and seed


def _drop(node, path):
    head, _, rest = path.partition(".")
    if rest and isinstance(node.get(head), dict):
        _drop(node[head], rest)
    elif not rest:
        node.pop(head, None)


def comparable(run):
    """report.json of `run` without timings, paths, host, git sha and library versions (and nothing else): the text of the file with the run directory
    replaced, the timing fields removed. Two same-seed runs must give the same text."""
    text = (run / "report" / "report.json").read_text()
    for p in (run.resolve(), run):
        text = text.replace(str(p), "<run>")
    rep = json.loads(text)
    for p in TIMING:
        _drop(rep, p)
    for e in rep["emulator"]["vehicles"].values():  # the one measured quantity the emulator stage reports (BRIEF 2.7: query < 10 ms)
        if e.get("trained"):
            e["acceptance"].pop("query_ms")
    rep["receipts"] = {r["id"]: dict(r, sha256="<holdout.json holds query_ms>") if r["id"] == "emulator:output:holdout.json" else r for r in rep["receipts"]}
    cred = (run / "report" / "credibility.json").read_text()  # it names the run directory (its evidence, and its own "run": the directory's name)
    for p in (run.resolve(), run):
        cred = cred.replace(str(p), "<run>")
    cred = json.loads(cred)
    cred.pop("run")
    rep["receipts"]["report:output:credibility.json"]["sha256"] = hashlib.sha256(json.dumps(cred, sort_keys=True).encode()).hexdigest()
    return rep


def make_twins(root):
    """The CI mission twice with the same seed, each in its own run directory with its own copy of the same emulator table (140 glider rows, so
    the emulator is really trained)."""
    seed_table(root / "start.parquet")
    out = {}
    for name in ("a", "b"):
        (root / f"table_{name}").mkdir()
        shutil.copy(root / "start.parquet", root / f"table_{name}" / "train.parquet")                  # a private copy of one file, same name, own directory
        out[name] = pipeline.run(MISSION_PATH, "ci", 0, root / name, log=quiet, emulator_table=root / f"table_{name}" / "train.parquet")
    return types.SimpleNamespace(root=root, ctx=out)


def differences(a, b, path=""):
    """Where two JSON-like trees differ: ["path: a != b", ...] (the first few characters of each)."""
    if isinstance(a, dict) and isinstance(b, dict):
        return [d for k in sorted(a.keys() | b.keys()) for d in differences(a.get(k, "<absent>"), b.get(k, "<absent>"), f"{path}.{k}" if path else k)]
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        return [d for i, (x, y) in enumerate(zip(a, b, strict=True)) for d in differences(x, y, f"{path}[{i}]")]
    return [] if a == b else [f"{path}: {str(a)[:60]} != {str(b)[:60]}"]


@pytest.fixture(scope="module")
def twin_runs(data, tmp_path_factory):
    """Stage 3 is the stand-in of tests/test_pipeline.py. The CI budget is 10 times longer (the plan then has an emulator share for two variant runs)."""
    mp = pytest.MonkeyPatch()
    try:
        mp.setattr(budget, "plan", small_budget(budget.plan))
        mp.setitem(budget.BUDGET_S, "ci", 6000)
        fake_module(mp, "cafe.pm.stage3.pipeline_windows", run=Rows().run)
        return make_twins(tmp_path_factory.mktemp("twin"))
    finally:
        mp.undo()


@pytest.fixture(scope="module")
def real_twins(data, tmp_path_factory):
    """Stage 3 for real: every LES window (CPU lattice Boltzmann), the glider's FEA in a child process, the free-surface case priced and left out.
    The budget is 10 times the CI one and the LBM rate 2000 cell-updates/s, so each window is a few 10^5 cell-steps (the coarsest the rules allow)
    in a slice of minutes: the safety kill cannot fire, whatever the load of the machine the test runs on."""
    mp = pytest.MonkeyPatch()
    try:
        mp.setattr(budget, "plan", small_budget(budget.plan))
        mp.setitem(budget.BUDGET_S, "ci", 6000)
        mp.setattr(budget, "lbm_rate", lambda thr, gpus: (2000.0, "xlb-jax-cpu", "test: a rate low enough for toy windows"))
        mp.setitem(sys.modules, "cafe.pm.stage3.pipeline_windows", real_windows)                  # whatever another module left in its place
        mp.setattr(stage3_pkg, "pipeline_windows", real_windows)
        return make_twins(tmp_path_factory.mktemp("real_twin"))
    finally:
        mp.undo()


def test_two_runs_with_the_same_seed_make_the_same_report_json(twin_runs):
    t = twin_runs
    a, b = (comparable(t.ctx[n].run_dir) for n in ("a", "b"))
    assert differences(a, b) == [] and json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    assert a["emulator"]["available"] and any(v["trained"] for v in a["emulator"]["vehicles"].values())          # the emulator was fitted, not skipped
    assert a["emulator"]["design"]["variants"]["value"] == t.ctx["a"].plan["emulator"]["variants_no_refit"] >= 1


def test_the_emulator_files_of_two_same_seed_runs_are_identical(twin_runs):
    a, b = (twin_runs.ctx[n].run_dir / "emulator" for n in ("a", "b"))
    for f in ("flip.json", "design.json"):
        assert (a / f).read_bytes() == (b / f).read_bytes(), f                      # the very bytes the report's receipts hash
    ha, hb = (json.loads((d / "holdout.json").read_text()) for d in (a, b))
    for h in (ha, hb):
        for e in h.values():
            e.pop("query_ms", None)                                                    # measured: BRIEF 2.7 asks for it
            e.get("acceptance", {}).pop("query_ok", None)
    assert differences(ha, hb) == []


def test_the_plan_json_of_a_run_holds_every_size_the_stages_used(twin_runs):
    for ctx in twin_runs.ctx.values():
        plan = json.loads((ctx.run_dir / "plan.json").read_text())
        assert plan["stage3"]["cell_steps_per_part"] and plan["stage3"]["share_s"] == pytest.approx(0.3 * 6000) and plan["stage3"]["fs"]["cases"] == 1
        d = json.loads((ctx.run_dir / "emulator" / "design.json").read_text())
        assert d["planned_variants"] == plan["emulator"]["variants_no_refit"] == len(d["variants"]) and d["killed"] is None
        assert all(sk["reason"].startswith("the variant leaves the environment data") for sk in d["skipped"])        # a skipped vehicle is a stated reason


def test_the_hashed_outputs_of_the_stages_carry_no_timing(twin_runs):
    for ctx in twin_runs.ctx.values():
        for rel in ("emulator/design.json", "stage3/windows.json"):
            text = (ctx.run_dir / rel).read_text()
            assert "wall_s" not in text and "seconds" not in text, rel
        assert b"wall_s" not in (ctx.run_dir / "stage1" / "res.pkl").read_bytes()


def test_the_emulator_input_is_the_table_as_it_was_and_a_ledger_input(twin_runs):
    from cafe.pm import whatif
    a, b = (twin_runs.ctx[n] for n in ("a", "b"))
    la, lb = (read_ledger(c.run_dir, "emulator") for c in (a, b))
    ia, ib = ([i for i in led["inputs"] if i["ref"].endswith("train_input.parquet")] for led in (la, lb))
    file_sha = hashlib.sha256((a.run_dir / "emulator" / "train_input.parquet").read_bytes()).hexdigest()
    assert len(ia) == len(ib) == 1 and ia[0]["sha256"] == ib[0]["sha256"] == file_sha
    assert ia[0]["rows"] == 140
    own = whatif.read_table(twin_runs.root / "table_a" / "train.parquet")  # this run's rows came after the fit
    added = json.loads((a.run_dir / "emulator" / "design.json").read_text())["rows_added"]
    assert added >= 4 and len(own) == 140 + added and own["run_id"].eq("seed").sum() == 140
    assert whatif.read_table(twin_runs.root / "start.parquet")["run_id"].eq("seed").all()  # and the start copy was never touched


@pytest.mark.slow
def test_two_runs_with_the_same_seed_make_the_same_report_json_with_the_real_stage_3(real_twins):
    t = real_twins
    a, b = (comparable(t.ctx[n].run_dir) for n in ("a", "b"))
    assert differences(a, b) == [] and json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    rows = json.loads((t.ctx["a"].run_dir / "stage3" / "windows.json").read_text())
    flat = [r for rs in rows.values() for r in rs]
    assert len(flat) == 6 and {r["part"] for r in flat} == {"body", "hull", "wing", "hull_fs"}
    ran = [r for r in flat if r["part"] != "hull_fs"]
    assert not any("killed" in " ".join(r["reasons"]) or (r["resolution"] or {}).get("cut_reason") for r in ran)                        # nothing was killed
    assert sum(r["cd"] is not None for r in ran) >= 3  # the windows really ran
    assert any(r["fea"]["run"] for r in ran)  # the glider hull's FEA ran
    assert all("timing" not in r for r in flat) and a["stage3"]["vehicles"]
    sizes = json.loads((t.ctx["a"].run_dir / "plan.json").read_text())["stage3"]["cell_steps_per_part"]
    assert {r["resolution"]["cell_steps_budget_plan"] for r in ran if r["part"] == "body" and r["fluid"] == "water"} == {sizes["glider"]}
