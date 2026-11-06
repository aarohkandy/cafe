"""python -m cafe.pm: argument handling, what each command calls, what it prints, and exit code 2 on a ConfigError.

pipeline.run is replaced where the test is about the arguments it receives; `fetch` and `report` also run for real on the CI fixture
and on a synthetic run directory.
"""
import json
import pathlib
import runpy
import shutil
import sys

import pytest
import yaml

from cafe.pm import __main__ as cli, audit, budget, config, ledger, par, pipeline, whatif
from cafe.pm.env import ocean as ocean_mod
from cafe.pm.env.protocol import AnalyticEnv
from cafe.pm.physics import glider
from tests.fixtures import pm_run
from tests.fixtures.fakes import fake_module

MISSION = str(config.ROOT / "missions" / "ci_fixture.yaml")


@pytest.fixture
def calls(monkeypatch):
    """pipeline.run replaced by a recorder that returns an object with a run_dir, as the real one does."""
    seen = []

    def run(mission, budget, gpus, out, resume=True, stop_after=None, log=print, seed=None, emulator_table=None, gpu_mem_gb=None):
        seen.append(dict(mission=mission, budget=budget, gpus=gpus, out=out, resume=resume, stop_after=stop_after, **({} if seed is None else dict(seed=seed)),
                         **({} if emulator_table is None else dict(emulator_table=emulator_table)),
                         **({} if gpu_mem_gb is None else dict(gpu_mem_gb=gpu_mem_gb))))
        return type("Ctx", (), {"run_dir": out})()
    monkeypatch.setattr(pipeline, "run", run)
    return seen


def _roomy():
    """`par.memory_gb` answers 64 GB while a test of this module runs, and the real function afterwards. A test's own `monkeypatch` is set up before this
    (the autouse fixtures of conftest.py ask for it) and so is torn down after it: if the test patched `par.memory_gb` too, that patch puts back what it saw,
    which is this fixture's answer, for every later test of the process (test_par.py's memory test saw 64.0 once the shares of bin/proot_suite.sh ran
    test_cli.py first). So what is left behind forwards to the real function once the test is over."""
    real, over = par.memory_gb, []
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(par, "memory_gb", lambda: real() if over else 64.0)
        try:
            yield
        finally:
            over.append(True)


@pytest.fixture(autouse=True)
def roomy_machine():
    """Review round 8, M-6: the CLI tests reach the planner as a side effect and must not depend on the memory of the machine they run on (the stage-1
    model needs about 9 GB for the demo window). Its own MonkeyPatch, so a test that calls `monkeypatch.undo()` keeps it; the tests of the refusal itself
    patch `par.memory_gb` to the value they are about."""
    yield from _roomy()


def test_ingest_ocean_writes_the_lab_hycom_into_the_store_the_mission_names_and_refuses_a_gofs_mission(monkeypatch, tmp_path, capsys):
    import yaml
    from cafe.pm.env import hycom
    seen = []
    monkeypatch.setattr(hycom, "ingest_lab_hycom", lambda *a: seen.append(a) or pathlib.Path(a[2]))
    m = yaml.safe_load(pathlib.Path(MISSION).read_text())
    m["environment"]["ocean"] = dict(source="lab_hycom", path=str(tmp_path / "lab.zarr"), temperature_kind="potential")
    (tmp_path / "lab.yaml").write_text(yaml.safe_dump(m))
    assert cli.main(["ingest-ocean", "--mission", str(tmp_path / "lab.yaml"), "--path", "/lab/hycom"]) == 0
    assert seen == [("/lab/hycom", pipeline.ocean_box(m), str(tmp_path / "lab.zarr"), "potential", None)]          # the mission's kind when none is given
    assert f"ocean store: {tmp_path / 'lab.zarr'}" in capsys.readouterr().out
    assert cli.main(["ingest-ocean", "--mission", str(tmp_path / "lab.yaml"), "--path", "/x", "--temperature-kind", "in_situ", "--grid", "/g"]) == 0
    assert seen[-1][3:] == ("in_situ", "/g")
    assert cli.main(["ingest-ocean", "--mission", MISSION, "--path", "/lab/hycom"]) == 2                                # a GOFS mission: nothing written
    assert "set it to {source: lab_hycom" in capsys.readouterr().err and len(seen) == 2


def test_validate_reports_the_vehicles_and_links_of_a_valid_mission(capsys):
    assert cli.main(["validate", "--mission", MISSION]) == 0
    assert capsys.readouterr().out == f"{MISSION}: valid (4 vehicles, 3 links)\n"


def test_r8_l0_validate_counts_one_vehicle_in_the_singular(tmp_path, capsys):
    one = tmp_path / "one.yaml"
    d = yaml.safe_load(pathlib.Path(MISSION).read_text())
    d["vehicles"], d["links"] = d["vehicles"][:1], []
    one.write_text(yaml.safe_dump(d))
    assert cli.main(["validate", "--mission", str(one)]) == 0
    assert capsys.readouterr().out == f"{one}: valid (1 vehicle, 0 links)\n"


def test_a_mission_that_fails_validation_exits_2_with_the_reason_on_stderr(tmp_path, capsys):
    bad = tmp_path / "bad.yaml"
    bad.write_text(pathlib.Path(MISSION).read_text().replace('end: "2023-03-03T06:00:00Z"', 'end: "2023-02-01T06:00:00Z"'))
    assert cli.main(["validate", "--mission", str(bad)]) == 2
    out, err = capsys.readouterr()
    assert out == "" and err.startswith("error: ") and "window.end" in err and "swap them" in err
    assert cli.main(["validate", "--mission", str(tmp_path / "missing.yaml")]) == 2
    assert "file not found" in capsys.readouterr().err
    (tmp_path / "broken.yaml").write_text("a: [1, 2\n")
    assert cli.main(["validate", "--mission", str(tmp_path / "broken.yaml")]) == 2
    assert "not valid YAML" in capsys.readouterr().err


def test_plan_prints_what_the_budget_buys(capsys):
    assert cli.main(["plan", "--mission", MISSION, "--budget", "4h", "--gpus", "2", "--assume-gpu"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("budget 4h (240 min), 2 GPU(s), 1.50 mission days") and "stage 1: 73..256 members in batches of 64" in out
    assert "xlb-warp" in out and all(f"  {v}: " in out for v in ("glider_eq", "glider_1n", "usv", "uas"))


def test_plan_defaults_to_the_quick_budget_on_no_gpu(capsys):
    assert cli.main(["plan", "--mission", MISSION]) == 0
    assert capsys.readouterr().out.startswith("budget quick (20 min), 0 GPU(s)")


def test_a_gpu_that_is_not_there_is_refused_by_run_and_labelled_by_plan(calls, tmp_path, monkeypatch, capsys):
    """Round 3 M-19: `plan --gpus 1` on a machine with no nvidia-smi exited 0 and halved stage 1 for a GPU that was not there, and a `run` would have run the
    LES windows on the CPU. Now `run` refuses it (exit 2, naming the flag), `plan` says first that the numbers are projected, and --assume-gpu is
    the way out."""
    monkeypatch.setattr(pipeline, "gpu_visible", lambda: False)
    assert cli.main(["run", "--mission", MISSION, "--out", str(tmp_path / "o"), "--gpus", "1"]) == 2
    out, err = capsys.readouterr()
    assert out == "" and calls == [] and err.startswith("error: --gpus 1 but no GPU is visible")
    assert "--gpus all" in err and "--gpus 0" in err and "--assume-gpu" in err
    assert cli.main(["plan", "--mission", MISSION, "--gpus", "1"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("no GPU found on this machine: the 1 GPU(s) below are projected from published benchmarks")
    assert "budget quick (20 min), 1 GPU(s)" in out
    assert cli.main(["plan", "--mission", MISSION, "--gpus", "1", "--assume-gpu"]) == 0
    assert capsys.readouterr().out.startswith("budget quick (20 min), 1 GPU(s)")                              # today's behaviour
    assert cli.main(["run", "--mission", MISSION, "--out", str(tmp_path / "o"), "--gpus", "1", "--assume-gpu"]) == 0 and calls[-1]["gpus"] == 1
    capsys.readouterr()
    # no GPU asked, none looked for
    assert cli.main(["plan", "--mission", MISSION]) == 0 and capsys.readouterr().out.startswith("budget quick (20 min), 0 GPU(s)")
    assert cli.main(["run", "--mission", MISSION, "--out", str(tmp_path / "o")]) == 0 and calls[-1]["gpus"] == 0
    capsys.readouterr()
    monkeypatch.setattr(pipeline, "gpu_visible", lambda: True)                                                 # a visible GPU: no label, no refusal
    assert cli.main(["plan", "--mission", MISSION, "--gpus", "1"]) == 0 and capsys.readouterr().out.startswith("budget quick (20 min), 1 GPU(s)")
    monkeypatch.setattr(pipeline, "gpu_memory_gb", lambda: None)
    assert cli.main(["run", "--mission", MISSION, "--out", str(tmp_path / "o"), "--gpus", "1"]) == 0 and calls[-1]["gpus"] == 1


def test_gpu_visible_needs_a_cuda_device_or_nvidia_smi(monkeypatch):
    import shutil
    from cafe.pm.stage3 import lbm
    monkeypatch.setattr(lbm, "pick_backend", lambda: "jax")
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert pipeline.gpu_visible() is False
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/nvidia-smi" if name == "nvidia-smi" else None)
    assert pipeline.gpu_visible() is True
    monkeypatch.setattr(shutil, "which", lambda name: None)
    monkeypatch.setattr(lbm, "pick_backend", lambda: "warp")
    assert pipeline.gpu_visible() is True


def test_promote_calibration_copies_a_runs_calibration_into_the_tracked_config(tmp_path, monkeypatch, capsys):
    from cafe.pm.env import subgrid
    cfg = tmp_path / "subgrid.json"
    cfg.write_text((subgrid._CFG_DIR / "subgrid.json").read_text())
    monkeypatch.setattr(subgrid, "_CFG_DIR", tmp_path)
    run = tmp_path / "quick"
    (run / "stage3").mkdir(parents=True)
    (run / "checkpoints" / "stage3").mkdir(parents=True)
    (run / "checkpoints" / "stage3" / "ledger.json").write_text("{}")
    (run / "stage3" / "subgrid_calibration.json").write_text(json.dumps(dict(subgrid.load_config(cfg)["calibration"], source_run="x", sigma_u_over_ustar=2.9)))
    assert cli.main(["promote-calibration", "--run", str(run)]) == 0
    assert f"{run.resolve()} (promoted" in capsys.readouterr().out and json.loads(cfg.read_text())["calibration"]["sigma_u_over_ustar"] == 2.9
    assert cli.main(["promote-calibration", "--run", str(tmp_path / "none")]) == 2
    assert "did not calibrate the sub-grid layer" in capsys.readouterr().err


BAD_ARGS = [["plan", "--mission", MISSION, "--budget", "weekend"], ["fetch", "--mission", MISSION, "--budget", "ci"], ["run"], ["report"], []]


@pytest.mark.parametrize("argv", BAD_ARGS)
def test_bad_arguments_are_refused_by_argparse(argv, capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(argv)
    assert e.value.code == 2 and "usage:" in capsys.readouterr().err


def test_a_plan_for_an_invalid_mission_exits_2(tmp_path, capsys):
    assert cli.main(["plan", "--mission", str(tmp_path / "nope.yaml")]) == 2
    assert "file not found" in capsys.readouterr().err


def test_run_calls_the_pipeline_with_its_budget_gpus_and_default_directory(calls, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(pipeline, "gpu_memory_gb", lambda: None)                                                      # no nvidia-smi answer: nothing to guard
    assert cli.main(["run", "--mission", MISSION, "--budget", "4h", "--gpus", "1", "--assume-gpu"]) == 0
    out = pathlib.Path("runs/ci_fixture/4h")
    assert calls == [dict(mission=MISSION, budget="4h", gpus=1, out=out, resume=True, stop_after=None)]
    assert capsys.readouterr().out == f"report: {out / 'report' / 'index.html'}\n"


def test_run_passes_the_emulator_table_and_documents_what_it_is_for(calls, tmp_path, capsys):
    assert cli.main(["run", "--mission", MISSION, "--out", str(tmp_path / "o"), "--emulator-table", str(tmp_path / "t.parquet")]) == 0
    assert calls[0]["emulator_table"] == str(tmp_path / "t.parquet")
    assert cli.main(["run", "--mission", MISSION, "--out", str(tmp_path / "o")]) == 0 and "emulator_table" not in calls[1]          # default: the shared table
    with pytest.raises(SystemExit):
        cli.main(["run", "--help"])
    out = " ".join(capsys.readouterr().out.split())
    assert "--emulator-table FILE" in out and "$CAFE_EMULATOR_TABLE" in out and "give every run its own copy of that file" in out
    assert "depends only on the table it started from" in out
    with pytest.raises(SystemExit):
        cli.main(["fetch", "--mission", MISSION, "--emulator-table", "x"])                 # only `run` trains an emulator


def test_run_defaults_to_the_quick_budget_and_fresh_ignores_the_checkpoints(calls, tmp_path, capsys):
    assert cli.main(["run", "--mission", MISSION, "--out", str(tmp_path / "o"), "--fresh"]) == 0
    assert calls == [dict(mission=MISSION, budget="quick", gpus=0, out=tmp_path / "o", resume=False, stop_after=None)]
    assert capsys.readouterr().out == f"report: {tmp_path / 'o' / 'report' / 'index.html'}\n"


def test_fetch_runs_only_the_ingest_stage_and_prints_no_report(calls, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["fetch", "--mission", MISSION]) == 0
    assert calls == [dict(mission=MISSION, budget="quick", gpus=0, out=pathlib.Path("runs/ci_fixture/quick"), resume=True, stop_after="ingest")]
    assert capsys.readouterr().out == ""
    assert cli.main(["fetch", "--mission", MISSION, "--out", str(tmp_path / "f"), "--fresh"]) == 0
    assert calls[1]["out"] == tmp_path / "f" and calls[1]["resume"] is False and calls[1]["stop_after"] == "ingest"


def test_a_config_error_raised_inside_the_pipeline_exits_2(monkeypatch, tmp_path, capsys):
    def refuse(*a, **k):
        raise config.ConfigError("platforms/x.yaml: field value is missing; add it")
    monkeypatch.setattr(pipeline, "run", refuse)
    assert cli.main(["run", "--mission", MISSION, "--out", str(tmp_path / "o")]) == 2
    assert capsys.readouterr().err == "error: platforms/x.yaml: field value is missing; add it\n"


def test_run_of_an_invalid_mission_never_reaches_the_pipeline(calls, tmp_path, capsys):
    assert cli.main(["run", "--mission", str(tmp_path / "nope.yaml")]) == 2 and calls == []


def test_fetch_ingests_the_ci_fixture_for_real(tmp_path, ci_env, monkeypatch, capsys):
    monkeypatch.setattr(pipeline, "DATA", ci_env.data)
    monkeypatch.setattr(ocean_mod, "DATA", ci_env.data)
    monkeypatch.setattr(budget, "plan", lambda *a, **k: pytest.fail("fetch must not plan a budget"))
    out = tmp_path / "run"
    assert cli.main(["fetch", "--mission", MISSION, "--out", str(out)]) == 0
    assert "ingest: done in" in capsys.readouterr().out
    assert sorted(p.name for p in (out / "checkpoints").iterdir()) == ["ingest"]
    assert json.loads((out / "checkpoints" / "ingest" / "ledger.json").read_text())["ok"]
    assert (out / "ingest" / "priors_fitted.json").is_file() and (out / "mission.yaml").is_file()
    assert not (out / "plan.json").exists()  # fetch plans nothing (M-13): no budget is needed to download


def test_report_rerenders_a_finished_run(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(pipeline, "DATA", tmp_path / "nodata")
    run = tmp_path / "run"
    pm_run.make_run(run)
    assert cli.main(["report", "--run", str(run)]) == 0
    printed = capsys.readouterr().out.split()
    assert printed[0] == str(run / "report" / "index.html") and printed[1] == str(run / "report" / "report.json") and len(printed) == 4
    assert all(pathlib.Path(p).is_file() for p in printed)


def report_ledger_over_other_bytes(run):
    """The report stage's ledger as if the stage had written different bytes than a re-render does (what a changed code or cache does)."""
    assert cli.main(["report", "--run", str(run)]) == 0                                      # no report ledger yet: nothing to bring up to date
    index = run / "report" / "index.html"
    index.write_text(index.read_text() + "<!-- as the stage wrote it -->")
    with ledger.Ledger(run, "report", "cfg") as L:
        L.input(run / "checkpoints" / "emulator" / "ledger.json")
        for p in ("index.html", "report.json", "credibility.html", "credibility.json"):
            L.output(run / "report" / p)
    return run / "checkpoints" / "report" / "ledger.json"


def test_r9_m16_report_run_leaves_the_report_ledger_matching_what_it_wrote(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(pipeline, "DATA", tmp_path / "nodata")
    run = tmp_path / "run"
    pm_run.make_run(run)
    led = report_ledger_over_other_bytes(run)
    capsys.readouterr()
    assert cli.main(["report", "--run", str(run)]) == 0
    probs = [p for p in audit.ledger_problems(run) if "stage report" in p]
    assert probs == []                                                           # was 1 x "output .../report/index.html changed since the stage ran"
    d = json.loads(led.read_text())
    assert len(d["notes"]) == 1 and d["notes"][0].startswith("re-rendered by report --run (git_sha ") and "code_digest " in d["notes"][0]


def test_r9_m16_a_re_render_that_fails_a_report_check_exits_1_and_leaves_the_ledger_alone(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(pipeline, "DATA", tmp_path / "nodata")
    run = tmp_path / "run"
    pm_run.make_run(run)
    led = report_ledger_over_other_bytes(run)
    before = led.read_bytes()
    capsys.readouterr()
    monkeypatch.setattr(cli.report, "check_rendered", lambda rep, h: ["vehicles.uas.p_fail: '0.5' is not in the HTML"])
    assert cli.main(["report", "--run", str(run)]) == 1
    out, err = capsys.readouterr()
    assert out == "" and "re-rendered report fails report_html_matches_json: vehicles.uas.p_fail" in err and "audit" in err
    assert led.read_bytes() == before


def test_report_of_a_directory_that_is_not_a_run_exits_2(tmp_path, capsys):
    assert cli.main(["report", "--run", str(tmp_path)]) == 2
    assert "mission.yaml: file not found" in capsys.readouterr().err
    shutil.copy(MISSION, tmp_path / "mission.yaml")
    assert cli.main(["report", "--run", str(tmp_path)]) == 2                    # was a FileNotFoundError traceback (review round 5, M-19)
    assert "no plan.json; this is not a finished run directory" in capsys.readouterr().err


def test_receipts_forwards_its_options_and_returns_the_runs_exit_code(monkeypatch):
    got = []

    def run(slow, only, broken, out):
        got.append((slow, only, broken, out))
        return "table", 7
    fake_module(monkeypatch, "cafe.pm.receipts", run=run)
    assert cli.main(["receipts"]) == 7
    assert cli.main(["receipts", "--slow", "--only", "glider,usv", "--broken", "b.yaml", "--json", "o.json"]) == 7
    assert got == [(False, None, None, None), (True, ["glider", "usv"], "b.yaml", "o.json")]


def test_python_dash_m_runs_main_and_exits_with_its_code(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["cafe.pm", "validate", "--mission", MISSION])
    with pytest.raises(SystemExit) as e:
        runpy.run_module("cafe.pm", run_name="__main__")
    assert e.value.code == 0 and "valid (4 vehicles, 3 links)" in capsys.readouterr().out
    monkeypatch.setattr(sys, "argv", ["cafe.pm", "validate", "--mission", MISSION + ".missing"])
    with pytest.raises(SystemExit) as e:
        runpy.run_module("cafe.pm", run_name="__main__")
    assert e.value.code == 2


# ---------------------------------------------------------------------------------------------------------------- report --open

def test_report_opens_in_a_browser_when_there_is_a_display_and_otherwise_prints_the_path(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(pipeline, "DATA", tmp_path / "nodata")
    run = tmp_path / "run"
    pm_run.make_run(run)
    opened = []
    monkeypatch.setattr(cli.webbrowser, "open", lambda url: opened.append(url) or True)
    monkeypatch.setattr(cli, "_has_display", lambda: True)
    assert cli.main(["report", "--run", str(run), "--open"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert opened == [(run / "report" / "index.html").resolve().as_uri()] and out[-1] == f"opened {run / 'report' / 'index.html'}"
    monkeypatch.setattr(cli, "_has_display", lambda: False)
    assert cli.main(["report", "--run", str(run), "--open"]) == 0
    assert capsys.readouterr().out.splitlines()[-1] == f"no display to open it on: {run / 'report' / 'index.html'}" and len(opened) == 1
    monkeypatch.setattr(cli, "_has_display", lambda: True)
    monkeypatch.setattr(cli.webbrowser, "open", lambda url: False)                                            # no usable browser
    assert cli.main(["report", "--run", str(run), "--open"]) == 0
    assert capsys.readouterr().out.splitlines()[-1].startswith("no display to open it on")
    assert cli.main(["report", "--run", str(run)]) == 0
    assert "opened" not in capsys.readouterr().out


@pytest.mark.parametrize("platform,env,want", [("darwin", {}, True), ("win32", {}, True), ("linux", {}, False), ("linux", {"DISPLAY": ":0"}, True),
                                               ("linux", {"WAYLAND_DISPLAY": "wayland-0"}, True)])
def test_a_display_is_assumed_on_mac_and_windows_and_looked_for_elsewhere(monkeypatch, platform, env, want):
    monkeypatch.setattr(sys, "platform", platform)
    for k in ("DISPLAY", "WAYLAND_DISPLAY"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    assert cli._has_display() is want


def test_report_routes_the_reach_map_through_the_environment_when_the_cache_exists(tmp_path, capsys, monkeypatch):
    data = tmp_path / "data"
    (data / "cache" / "tepex_c_demo").mkdir(parents=True)
    monkeypatch.setattr(pipeline, "DATA", data)
    monkeypatch.setattr(pipeline.Context, "env", property(lambda self: AnalyticEnv(current=(0.2, 0.0))))
    run = tmp_path / "run"
    pm_run.make_run(run)
    assert cli.main(["report", "--run", str(run)]) == 0
    rep = json.loads((run / "report" / "report.json").read_text())
    assert rep["reach"]["available"] and rep["environment"]["available"] and rep["reach"]["vehicles"]["usv"]["available"]
    capsys.readouterr()

    def boom(self):
        raise OSError("zarr store is corrupt")
    monkeypatch.setattr(pipeline.Context, "env", property(boom))
    assert cli.main(["report", "--run", str(run)]) == 0
    out, err = capsys.readouterr()
    assert "note: environment not loaded (OSError: zarr store is corrupt)" in err and out.split()[0] == str(run / "report" / "index.html")
    assert json.loads((run / "report" / "report.json").read_text())["reach"]["available"] is False


# ---------------------------------------------------------------------------------------------------------------- audit and hangar

def test_audit_forwards_its_runs_and_flag_and_returns_its_exit_code(monkeypatch):
    got = []
    monkeypatch.setattr(audit, "main", lambda argv: got.append(argv) or 5)
    assert cli.main(["audit"]) == 5 and cli.main(["audit", "runs/a", "runs/b", "--code-only"]) == 5
    assert got == [[], ["runs/a", "runs/b", "--code-only"]]


@pytest.mark.parametrize("name,cls", [("seaglider", "glider"), ("slocum", "glider"), ("saildrone_explorer", "usv"), ("quad_uas", "uas")])
def test_hangar_checks_provenance_and_lists_what_stage_1_takes_from_the_platform(name, cls, capsys):
    assert cli.main(["hangar", "--platform", name]) == 0
    out = capsys.readouterr().out.splitlines()
    n_assumed = pipeline._assumed(config.load_platform(name))
    assert out[0].startswith(f"{name} ({cls}): provenance OK, {n_assumed} of ") and out[0].endswith("values assumed") and n_assumed > 0
    assert len(out) == 1 + int(out[0].split(" of ")[1].split()[0]) and all(line.startswith("  ") and " = " in line for line in out[1:])
    assert any("[source: " in line for line in out) and any("[ASSUMED: " in line for line in out)


def test_hangar_prints_each_value_with_its_unit_and_source(capsys):
    cli.main(["hangar", "--platform", "seaglider"])
    line = next(x for x in capsys.readouterr().out.splitlines() if x.lstrip().startswith("params.battery_J"))
    assert line.startswith("  params.battery_J = 17000000.0 J  [source: Kongsberg Seaglider product specification")


def test_hangar_reports_a_platform_without_provenance_and_an_unknown_platform(capsys, monkeypatch):
    def refuse(name):
        raise ValueError("seaglider.yaml:params.x: need a source, or assumed: true with a why")
    monkeypatch.setattr(glider, "load_platform", refuse)
    assert cli.main(["hangar", "--platform", "seaglider"]) == 1
    assert capsys.readouterr().out == "seaglider (glider): provenance FAILED: seaglider.yaml:params.x: need a source, or assumed: true with a why\n"
    assert cli.main(["hangar", "--platform", "no_such_boat"]) == 2
    assert "platform 'no_such_boat': no file" in capsys.readouterr().err


# ---------------------------------------------------------------------------------------------------------------- whatif

DEMO = str(config.ROOT / "missions" / "tepex_c_demo.yaml")


@pytest.fixture
def wi(tmp_path, monkeypatch):
    """A finished synthetic run of the TEPEX mission, an environment cache directory, the analytic environment, and whatif.answer recorded."""
    data = tmp_path / "data"
    (data / "cache" / "tepex_c_demo").mkdir(parents=True)
    monkeypatch.setattr(pipeline, "DATA", data)
    monkeypatch.setattr(pipeline.Context, "env", property(lambda self: AnalyticEnv()))
    fast = {c: dict(s_per_batch_day=1.0, s_per_member_day=0.01, measured="test", host="test") for c in ("glider", "usv", "uas")}
    monkeypatch.setattr(budget, "throughput", lambda path=budget.THROUGHPUT: dict(stage1=fast))   # the plan must not depend on the shipped throughput.json
    run = tmp_path / "run"
    pm_run.make_run(run)
    seen = {}

    def answer(mission, ops, base, tracks, env, ems, plan, fitted, scales, only=None):
        seen.update(ops=ops, base=base, tracks=tracks, ems=ems, plan=plan, fitted=fitted, scales=scales, only=only)
        emu = dict(base=dict(verdict="MARGINAL", p_fail=0.18), method="EMULATED", p_fail=0.04, lo=0.01, hi=0.09, verdict="GO", distance=0.8, threshold=1.9)
        s1 = dict(base=dict(verdict="NO-GO", p_fail=0.7), method="Stage 1", why="out of range", p_fail=0.5, lo=0.3, hi=0.7, verdict="NO-GO", n=32)
        return dict(vehicles={"usv": emu, "uas": s1,
                              "glider_eq": dict(base=dict(verdict="GO", p_fail=0.0), method="unchanged", p_fail=0.0, verdict="GO")},
                    dropped=ops["drop"], links_removed=["glider_2n-ship-acoustic"] if ops["drop"] else [])
    monkeypatch.setattr(whatif, "answer", answer)
    return types_ns(run=run, seen=seen, data=data)


def types_ns(**kw):
    import types
    return types.SimpleNamespace(**kw)


def whatif_args(wi, *more):
    return ["whatif", "--mission", DEMO, "--run", str(wi.run), *more]


def test_whatif_parses_each_argument_form(wi, capsys):
    assert cli.main(whatif_args(wi, "--shift", "48h")) == 0
    assert wi.seen["ops"] == dict(shift_h=48.0, dlon=0.0, dlat=0.0, drop=[]) and wi.seen["only"] is None
    cli.main(whatif_args(wi, "--shift=-6h", "--shift", "1d"))                                              # a negative value needs the = form
    assert wi.seen["ops"]["shift_h"] == 18.0
    cli.main(whatif_args(wi, "--move", "1deg W"))
    assert wi.seen["ops"] == dict(shift_h=0.0, dlon=-1.0, dlat=0.0, drop=[])
    cli.main(whatif_args(wi, "--move", "1deg W", "--move", "0.5deg north", "--move", "0.25 deg e"))
    assert (wi.seen["ops"]["dlon"], wi.seen["ops"]["dlat"]) == (-0.75, 0.5)
    cli.main(whatif_args(wi, "--drop", "glider_2n", "--drop", "usv", "--vehicle", "uas", "--vehicle", "usv", "--budget", "ci"))
    assert wi.seen["ops"]["drop"] == ["glider_2n", "usv"] and wi.seen["only"] == ["uas", "usv"] and wi.seen["plan"]["budget"] == "ci"
    cli.main(whatif_args(wi, "--shift", "6h", "--move", "1deg S", "--drop", "uas"))
    assert wi.seen["ops"] == dict(shift_h=6.0, dlon=0.0, dlat=-1.0, drop=["uas"])


def test_whatif_prints_the_verdict_with_its_badge_distance_or_stage_1_n(wi, capsys):
    assert cli.main(whatif_args(wi, "--shift", "6h", "--move", "1deg W", "--drop", "glider_2n")) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "whatif tepex_c_demo: +6 h; -1 deg lon, +0 deg lat; drop glider_2n"
    assert out[1] == "usv: MARGINAL (P(fail) 0.180) -> GO (P(fail) 0.040) (0.010 to 0.090)  [EMULATED, training-set distance 0.80 of limit 1.90]"
    assert out[2] == "uas: NO-GO (P(fail) 0.700) -> NO-GO (P(fail) 0.500) (0.300 to 0.700)  [Stage 1, n = 32 (out of range)]"
    assert out[3] == "glider_eq: GO (P(fail) 0.000) -> GO (P(fail) 0.000)  [unchanged]"
    assert out[4] == "dropped glider_2n; links removed: glider_2n-ship-acoustic. Other vehicles are unaffected: Stage-1 vehicles do not interact."


def test_whatif_without_links_removed_says_none(wi, capsys, monkeypatch):
    monkeypatch.setattr(whatif, "answer", lambda *a, **k: dict(vehicles={}, dropped=["usv"], links_removed=[]))
    cli.main(whatif_args(wi, "--drop", "usv"))
    assert "links removed: none." in capsys.readouterr().out


def test_whatif_takes_the_baseline_the_tracks_and_the_refit_from_the_run(wi):
    cli.main(whatif_args(wi, "--shift", "6h"))
    s = wi.seen
    summ = json.loads((wi.run / "stage1b" / "summary.json").read_text())["summary"]["vehicles"]
    assert s["base"] == {k: v["verdict"] for k, v in summ.items()} and set(s["tracks"]) == {"glider_eq", "glider_2n", "usv"}
    assert set(s["scales"]) == {"glider_eq"} and s["fitted"] is None and s["ems"].keys() == {"glider", "usv", "uas"}
    assert all(t[0].shape == t[1].shape == t[2].shape and len(t[0]) > 0 for t in s["tracks"].values()) and not s["ems"]["glider"][1]["trained"]
    (wi.run / "ingest").mkdir(exist_ok=True)
    (wi.run / "ingest" / "priors_fitted.json").write_text(json.dumps({"wind_speed_bias": {"dist": "normal", "mean": 0.1, "value": 1.0}}))
    (wi.run / "refit" / "refit.json").unlink()
    cli.main(whatif_args(wi, "--shift", "6h"))
    assert wi.seen["fitted"] == {"wind_speed_bias": {"dist": "normal", "mean": 0.1, "value": 1.0}} and wi.seen["scales"] is None


def test_whatif_without_a_finished_run_says_so_and_runs_everything_in_stage_1(wi, capsys, tmp_path):
    assert cli.main(["whatif", "--mission", DEMO, "--run", str(tmp_path / "none"), "--shift", "6h", "--budget", "ci"]) == 0
    assert wi.seen["base"] == {} and wi.seen["tracks"] == {} and wi.seen["scales"] is None
    note = f"note: no finished run at {tmp_path / 'none'}: the baseline and every changed vehicle are run in Stage 1 at the ci budget"
    assert note in capsys.readouterr().out


def test_whatif_does_not_trust_a_res_pkl_that_changed(wi, capsys):
    with open(wi.run / "stage1b" / "res.pkl", "ab") as f:
        f.write(b"x")
    assert cli.main(whatif_args(wi, "--shift", "6h")) == 0
    assert wi.seen["tracks"] == {} and "note: stage1b/res.pkl does not match the sha-256" in capsys.readouterr().out and wi.seen["base"]


def test_whatif_defaults_to_the_runs_directory_of_the_mission(wi, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    cli.main(["whatif", "--mission", DEMO, "--shift", "6h"])
    assert "note: no finished run at runs/tepex_c_demo/quick" in capsys.readouterr().out


def test_whatif_refuses_what_it_cannot_do(wi, tmp_path, capsys):
    assert cli.main(whatif_args(wi)) == 2
    assert capsys.readouterr().err == "error: whatif needs at least one of --shift, --move, --drop\n"
    assert cli.main(whatif_args(wi, "--shift", "soon")) == 2 and "--shift 'soon': expected a number and h or d" in capsys.readouterr().err
    assert cli.main(whatif_args(wi, "--move", "1deg up")) == 2 and "--move '1deg up': expected" in capsys.readouterr().err
    import shutil
    shutil.rmtree(wi.data / "cache")
    assert cli.main(whatif_args(wi, "--shift", "6h")) == 2
    err = capsys.readouterr().err
    assert "no environment cache at" in err and "fetch --mission" in err


def test_whatif_with_the_real_engine_drops_a_vehicle_and_reports_the_links(wi, monkeypatch, capsys):
    monkeypatch.undo()                                            # the real whatif.answer and an empty training table
    monkeypatch.setattr(pipeline, "DATA", wi.data)
    monkeypatch.setattr(pipeline.Context, "env", property(lambda self: AnalyticEnv()))
    assert cli.main(whatif_args(wi, "--drop", "glider_2n")) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "whatif tepex_c_demo: drop glider_2n"
    assert out[1] == "dropped glider_2n; links removed: glider_2n-ship-acoustic. Other vehicles are unaffected: Stage-1 vehicles do not interact."
    assert cli.main(whatif_args(wi, "--drop", "nobody")) == 2 and "no vehicle 'nobody'" in capsys.readouterr().err


# ---- review round 2, M-13 and M-33

def test_a_plan_the_budget_cannot_run_exits_2_with_the_refusal_text_and_no_traceback(monkeypatch, capsys):
    """`plan --budget ci` on the demo used to end in a PlanError traceback (exit 1); a bad mission already gave `error: ...` and exit 2."""
    def refuse(*a, **k):
        raise budget.PlanError("--budget ci: stage 1 needs 502 s for even one batch of 4 members but its share is 270 s: short by 232 s. Use a longer --budget")
    monkeypatch.setattr(budget, "plan", refuse)
    assert cli.main(["plan", "--mission", MISSION, "--budget", "ci"]) == 2
    out, err = capsys.readouterr()
    assert out == "" and err.startswith("error: --budget ci: stage 1 needs 502 s") and "Traceback" not in err
    monkeypatch.setattr(pipeline, "run", refuse)
    assert cli.main(["run", "--mission", MISSION, "--budget", "ci"]) == 2 and capsys.readouterr().err.startswith("error: --budget ci: stage 1 needs")


def long_mission(tmp_path):
    import yaml
    m = yaml.safe_load(pathlib.Path(MISSION).read_text())
    m["window"]["end"] = "2023-04-30T06:00:00Z"                                                 # 60 days
    (tmp_path / "long.yaml").write_text(yaml.safe_dump(m))
    return str(tmp_path / "long.yaml")


def test_the_real_planner_refusal_of_a_long_window_is_an_error_line_not_a_traceback(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(par, "memory_gb", lambda: None)                                        # the time refusal; the memory one is the next test
    assert cli.main(["plan", "--mission", long_mission(tmp_path), "--budget", "ci"]) == 2
    assert capsys.readouterr().err.startswith("error: --budget ci: stage 1 needs ")


def test_plan_applies_the_memory_model_of_run(tmp_path, capsys, monkeypatch):
    """Round 5 integration of M-6: `run` planned with the memory limit and `plan` without it, so `plan` printed a plan that `run` then refused."""
    monkeypatch.setattr(par, "memory_gb", lambda: 1.0)                                         # the 60-day CI box needs about 3 GB (row 309: by area)
    assert cli.main(["plan", "--mission", long_mission(tmp_path), "--budget", "ci"]) == 2
    err = capsys.readouterr().err
    assert err.startswith("error: stage 1 needs about ") and "60-day window" in err and "1 GB is available" in err


def test_fetch_of_a_mission_no_budget_can_run_still_reaches_ingest(tmp_path, monkeypatch):
    """A 60-day mission plans at no budget the planner offers; fetch used to plan the quick one before downloading, and now plans nothing."""
    import yaml
    from cafe.pm import ledger
    m = yaml.safe_load(pathlib.Path(MISSION).read_text())
    m["window"]["end"] = "2023-04-30T06:00:00Z"                                                 # 60 days
    (tmp_path / "long.yaml").write_text(yaml.safe_dump(m))
    monkeypatch.setattr(pipeline, "DATA", tmp_path / "data")
    monkeypatch.setattr(ocean_mod, "DATA", tmp_path / "data")
    monkeypatch.setenv("CAFE_OFFLINE", "1")
    with pytest.raises(budget.PlanError):                                                          # what fetch used to hit, before any download
        pipeline.Context(tmp_path / "long.yaml", "ci", 0, tmp_path / "x")
    with pytest.raises(ledger.StageFailed, match="orca_present"):  # the ingest stage ran (and found nothing cached): no PlanError
        pipeline.run(tmp_path / "long.yaml", "quick", 0, tmp_path / "r", stop_after="ingest", log=lambda _: None)


def test_a_failed_stage_self_check_prints_an_error_line_with_the_note_and_exits_1_without_a_traceback(tmp_path, monkeypatch, capsys):
    """Round 4 M-22: a stage whose self-check fails used to end in a Python traceback; the one thing to do (the offline note) was only in the ledger,
    and for `fetch` the note named `fetch` itself."""
    monkeypatch.setattr(pipeline, "DATA", tmp_path / "data")
    monkeypatch.setattr(ocean_mod, "DATA", tmp_path / "data")
    monkeypatch.setenv("CAFE_OFFLINE", "1")
    assert cli.main(["fetch", "--mission", MISSION, "--out", str(tmp_path / "r")]) == 1
    err = capsys.readouterr().err
    assert err.startswith("error: stage ingest: self-checks failed: orca_present: the orca WRF/UMWM cache for the window is not cached and CAFE_OFFLINE is set")
    assert f"unset CAFE_OFFLINE and run `python -m cafe.pm fetch --mission {MISSION}`" in err and "and 1 more (ledger: " in err and "Traceback" not in err
    assert err.count("\n") == 1 and (tmp_path / "r" / "checkpoints" / "ingest" / "ledger.json").is_file()


def test_a_corrupt_training_table_stops_the_run_before_any_stage_with_exit_2(tmp_path, monkeypatch, capsys):
    """Round 4 M-23: the emulator stage used to read the table after stages 1 to 3 and 1b, and die with ArrowInvalid."""
    monkeypatch.setattr(pipeline, "DATA", tmp_path / "data")
    monkeypatch.setattr(ocean_mod, "DATA", tmp_path / "data")
    t = tmp_path / "train.parquet"
    t.write_bytes(b"")
    assert cli.main(["run", "--mission", MISSION, "--budget", "ci", "--out", str(tmp_path / "r"), "--emulator-table", str(t)]) == 2
    err = capsys.readouterr().err
    assert err.startswith(f"error: training table {t} cannot be read") and not (tmp_path / "r" / "checkpoints").exists()


@pytest.mark.parametrize("bad", ["-5", "x", "1.5"])
def test_a_seed_that_numpy_would_refuse_is_refused_by_argparse(bad, capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["run", "--mission", MISSION, "--seed", bad])
    assert e.value.code == 2 and "argument --seed" in capsys.readouterr().err


def test_a_zero_seed_is_a_seed(calls, tmp_path):
    assert cli.main(["run", "--mission", MISSION, "--out", str(tmp_path / "o"), "--seed", "0"]) == 0 and calls[0]["seed"] == 0


def test_gpu_memory_is_passed_to_the_planner_given_or_asked_from_nvidia_smi(calls, tmp_path, monkeypatch, capsys):
    out = str(tmp_path / "o")
    monkeypatch.setattr(pipeline, "gpu_memory_gb", lambda: 24.0)
    assert cli.main(["run", "--mission", MISSION, "--out", out, "--gpus", "1", "--assume-gpu"]) == 0 and calls[-1]["gpu_mem_gb"] == 24.0           # asked
    # given wins
    assert cli.main(["run", "--mission", MISSION, "--out", out, "--gpus", "1", "--gpu-mem-gb", "16", "--assume-gpu"]) == 0 and calls[-1]["gpu_mem_gb"] == 16.0
    assert cli.main(["run", "--mission", MISSION, "--out", out]) == 0 and "gpu_mem_gb" not in calls[-1]                              # no GPU: nothing to guard
    seen = []
    real = budget.plan
    monkeypatch.setattr(budget, "plan", lambda *a, **k: seen.append(k.get("gpu_mem_gb")) or real(*a, **k))
    assert cli.main(["plan", "--mission", MISSION, "--gpus", "1", "--gpu-mem-gb", "40", "--assume-gpu"]) == 0 and seen == [40.0]
    assert "max_cells" not in capsys.readouterr().err


def test_nvidia_smi_memory_is_read_in_gb_and_a_missing_or_garbled_answer_is_none(monkeypatch):
    import subprocess
    from types import SimpleNamespace
    ans = {}
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: ans["r"] if "r" in ans else (_ for _ in ()).throw(FileNotFoundError("nvidia-smi")))
    assert pipeline.gpu_memory_gb() is None                                                               # no nvidia-smi
    ans["r"] = SimpleNamespace(returncode=0, stdout="81920\n81920\n")
    assert pipeline.gpu_memory_gb() == 80.0                                                               # MiB -> GB, the first device
    ans["r"] = SimpleNamespace(returncode=9, stdout="")
    assert pipeline.gpu_memory_gb() is None
    ans["r"] = SimpleNamespace(returncode=0, stdout="")
    assert pipeline.gpu_memory_gb() is None
    ans["r"] = SimpleNamespace(returncode=0, stdout="N/A\n")
    assert pipeline.gpu_memory_gb() is None


def test_whatif_prints_the_uas_that_a_whole_day_shift_leaves_unchanged(wi, capsys, monkeypatch):
    """M-14: the line is printed next to the answers for the other vehicles."""
    why = "launching +48 h later keeps the same launch time of day: nothing changes"
    monkeypatch.setattr(whatif, "answer", lambda *a, **k: dict(vehicles={}, dropped=[], links_removed=[], unchanged={"uas": why}))
    assert cli.main(whatif_args(wi, "--shift", "48h")) == 0
    assert f"uas: unchanged ({why})" in capsys.readouterr().out.splitlines()


# ---- review round 6, M-22: hangar on the radio and modem tables

@pytest.mark.parametrize("name,label", [("radios", "radio table"), ("modems", "modem table")])
def test_r6_m22_hangar_checks_the_radio_and_modem_tables_as_tables(name, label, capsys):
    assert cli.main(["hangar", "--platform", name]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith(f"{name} ({label}): provenance OK, ") and "(uas)" not in out[0] and len(out) == 1 + int(out[0].split(" of ")[1].split()[0])


def test_r6_m22_a_radio_table_number_without_a_source_fails_naming_the_leaf_and_an_unknown_platform_marks_the_tables(tmp_path, capsys):
    text = (config.PLATFORMS / "radios.yaml").read_text()
    line = next(x for x in text.splitlines() if x.lstrip().startswith("gt_dbi: {value: 2.0"))
    bad = text.replace(line, "    gt_dbi: {value: 2.0, unit: dBi}", 1)
    assert bad != text
    (tmp_path / "radios.yaml").write_text(bad)
    assert cli.main(["hangar", "--platform", str(tmp_path / "radios.yaml")]) == 1
    out = capsys.readouterr().out
    assert "(radio table): provenance FAILED" in out and "radios.rfd900x.gt_dbi" in out
    (tmp_path / "modems.yaml").write_text((config.PLATFORMS / "modems.yaml").read_text().replace("    source:", "    sourc:", 1))
    assert cli.main(["hangar", "--platform", str(tmp_path / "modems.yaml")]) == 1
    out = capsys.readouterr().out
    assert "(modem table): provenance FAILED" in out and "modems.benthos_atm960.source" in out
    assert cli.main(["hangar", "--platform", "no_such_boat"]) == 2
    assert "'modems (table)'" in capsys.readouterr().err


# ---- review round 7, M-34: a corrupt file is an `error:` line and exit 2

def test_r7_m34_a_mission_that_is_not_utf8_text_ends_in_an_error_line(tmp_path, capsys):
    p = tmp_path / "bin.yaml"
    p.write_bytes(bytes(range(256)))
    assert cli.main(["validate", "--mission", str(p)]) == 2
    assert "error: " in capsys.readouterr().err


@pytest.mark.parametrize("text", ["[]", "{", "\xff\xfe"], ids=["array", "truncated", "not utf-8"])
def test_r7_m34_a_plan_json_that_is_not_a_json_object_ends_in_an_error_line(tmp_path, capsys, text):
    (tmp_path / "mission.yaml").write_text((config.ROOT / "missions" / "tepex_c_demo.yaml").read_text())
    (tmp_path / "plan.json").write_bytes(text.encode("latin-1"))
    assert cli.main(["report", "--run", str(tmp_path)]) == 2
    err = capsys.readouterr().err
    assert err.startswith("error: ") and "plan.json: not a JSON object" in err and "Traceback" not in err


# ---- review round 7, M-35: hangar on a glider or USV file without its top-level blocks
@pytest.mark.parametrize("kind", ["seaglider", "saildrone_usv"])
def test_r7_m35_hangar_on_a_file_without_params_prints_provenance_failed_and_exits_1(kind, tmp_path, capsys):
    f = tmp_path / "boat.yaml"
    f.write_text(f"kind: {kind}\nmass_kg: 52\n")
    assert cli.main(["hangar", "--platform", str(f)]) == 1
    out = capsys.readouterr().out
    assert "provenance FAILED: boat.yaml: missing ['params', 'mission_defaults']" in out


# ---- review round 8: M-3 (whatif against another mission than the run's), M-6 (report needs no stage-1 memory), M-52 (audit --ledgers-only)

def test_r8_m3_whatif_refuses_a_mission_that_is_not_the_one_the_run_was_made_from(wi, tmp_path, capsys):
    import yaml
    m = yaml.safe_load(pathlib.Path(DEMO).read_text())
    next(v for v in m["vehicles"] if v["id"] == "glider_eq")["deploy"]["lat"] = -2.0
    edited = tmp_path / "edited.yaml"
    edited.write_text(yaml.safe_dump(m))
    assert cli.main(["whatif", "--mission", str(edited), "--run", str(wi.run), "--shift", "6h"]) == 2
    out, err = capsys.readouterr()
    assert out == "" and not wi.seen                                                              # no before -> after pair, no answer asked for
    assert f"is not the mission run {wi.run} was made from (differs in: vehicles)" in err and f"--mission {wi.run / 'mission.yaml'}" in err
    assert cli.main(whatif_args(wi, "--shift", "6h")) == 0 and "->" in capsys.readouterr().out    # the run's own mission is the same file


def test_r8_m3_a_seed_alone_is_a_note_and_a_run_without_its_mission_copy_is_as_before(wi, tmp_path, capsys):
    import yaml
    m = yaml.safe_load(pathlib.Path(DEMO).read_text())
    m["seed"] = 12345
    seeded = tmp_path / "seeded.yaml"
    seeded.write_text(yaml.safe_dump(m))
    old = yaml.safe_load((wi.run / "mission.yaml").read_text()).get("seed")
    assert cli.main(["whatif", "--mission", str(seeded), "--run", str(wi.run), "--shift", "6h"]) == 0
    assert f"note: the run used seed {old}, this file says 12345; the what-if draws use 12345" in capsys.readouterr().out
    (wi.run / "mission.yaml").unlink()
    m["vehicles"][0]["deploy"]["lat"] = -2.0
    seeded.write_text(yaml.safe_dump(m))
    assert cli.main(["whatif", "--mission", str(seeded), "--run", str(wi.run), "--shift", "6h"]) == 0          # nothing to compare with


def test_r8_m6_report_of_a_finished_run_needs_no_memory_for_stage_1(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(pipeline, "DATA", tmp_path / "nodata")
    monkeypatch.setattr(par, "memory_gb", lambda: 2.0)                                       # the planner's model needs about 9 GB for the demo window
    run = tmp_path / "run"
    pm_run.make_run(run)
    assert cli.main(["report", "--run", str(run)]) == 0
    assert capsys.readouterr().out.split()[0] == str(run / "report" / "index.html")
    assert cli.main(["plan", "--mission", DEMO]) == 2 and "2 GB is available" in capsys.readouterr().err         # the planner's refusal itself is unchanged


def test_r8_m52_audit_forwards_ledgers_only_like_code_only(monkeypatch):
    got = []
    monkeypatch.setattr(audit, "main", lambda argv: got.append(argv) or 0)
    assert cli.main(["audit", "--ledgers-only", "runs/a"]) == 0 and cli.main(["audit", "runs/b", "--code-only", "--ledgers-only"]) == 0
    assert got == [["runs/a", "--ledgers-only"], ["runs/b", "--code-only", "--ledgers-only"]]


# ---- review round 8 (K batch)

@pytest.fixture
def default_thresholds():
    yield
    from cafe.pm.stats import intervals
    intervals.set_thresholds(0.9, 0.6)                                                       # load_mission sets module state; leave the demo's


def mission_with_go(tmp_path, go):
    import yaml
    d = yaml.safe_load(pathlib.Path(MISSION).read_text())
    d["verdict"] = dict(d.get("verdict") or {}, go=go, nogo=0.5)
    p = tmp_path / f"go{go}.yaml"
    p.write_text(yaml.safe_dump(d))
    return str(p)


@pytest.mark.parametrize("go,n0", [(0.99, 9), (0.9, 9)])
def test_r8_m7_validate_says_how_few_members_without_a_failure_are_go_when_go_is_above_the_interval_term(tmp_path, capsys, default_thresholds, go, n0):
    assert cli.main(["validate", "--mission", mission_with_go(tmp_path, go)]) == 0
    out, err = capsys.readouterr()
    assert out.endswith("links)\n") and f"{n0} members without a failure are GO" in err
    assert f"note: verdict.go {go:g}: GO needs the point estimate of P(success) >= {go:g} and the 90 % Wilson lower bound on success >= 0.75" in err
    assert "(DECISIONS 68)" in err
    assert "the stopper uses the 95 % bound against" in err


def test_r8_m7_validate_prints_no_note_when_go_is_not_above_the_interval_term(tmp_path, capsys, default_thresholds):
    assert cli.main(["validate", "--mission", mission_with_go(tmp_path, 0.7)]) == 0
    assert capsys.readouterr().err == ""


def test_r8_m16_hangar_modems_counts_the_two_assumed_defaults(capsys):
    assert cli.main(["hangar", "--platform", "modems"]) == 0
    out = capsys.readouterr().out
    assert out.splitlines()[0] == "modems (modem table): provenance OK, 2 of 2 values assumed"
    assert "defaults.anchor_margin_db = 3.0 dB  [ASSUMED: " in out and "defaults.valid_range_factor = 10.0 -  [ASSUMED: " in out


def test_r8_m16_a_modem_default_without_a_source_or_an_assumed_why_fails_naming_it(tmp_path, capsys):
    (tmp_path / "modems.yaml").write_text((config.PLATFORMS / "modems.yaml").read_text().replace("assumed: true, why:", "why:", 1))
    assert cli.main(["hangar", "--platform", str(tmp_path / "modems.yaml")]) == 1
    assert "table numbers without a source or an assumed+why: ['defaults.anchor_margin_db']" in capsys.readouterr().out


CUTS = ["stage1b/summary.json", "refit/refit.json", "ingest/priors_fitted.json", "ingest/tao_compare.json", "stage3/windows.json", "windows/windows.json",
        "emulator/flip.json", "checkpoints/ingest/ledger.json"]


@pytest.mark.parametrize("rel", CUTS)
@pytest.mark.parametrize("text", ['{"a": 1, "b', "[]"], ids=["truncated", "array"])
def test_r8_m22_report_of_a_run_with_a_damaged_json_file_ends_in_an_error_line(tmp_path, capsys, monkeypatch, rel, text):
    monkeypatch.setattr(pipeline, "DATA", tmp_path / "nodata")
    run = tmp_path / "run"
    pm_run.make_run(run)
    assert cli.main(["report", "--run", str(run)]) == 0                                       # a finished run
    capsys.readouterr()
    (run / rel).parent.mkdir(parents=True, exist_ok=True)
    (run / rel).write_text(text)
    assert cli.main(["report", "--run", str(run)]) == 2
    err = capsys.readouterr().err
    assert err.startswith("error: ") and f"{pathlib.Path(rel).name}: not a JSON object" in err and "Traceback" not in err


def test_r8_merge_the_roomy_machine_is_not_undone_by_a_tests_own_monkeypatch_undo(monkeypatch):
    """C's autouse `roomy_machine` is what lets K's and every other batch's CLI tests reach the planner on a small machine; the tests that call
    `monkeypatch.undo()` (the whatif ones) must keep it, and a test of the refusal itself still gets the memory it patches in."""
    assert par.memory_gb() == 64.0
    monkeypatch.setattr(par, "memory_gb", lambda: 2.0)
    assert par.memory_gb() == 2.0
    monkeypatch.undo()
    assert par.memory_gb() == 64.0


def test_the_roomy_machine_leaves_the_real_memory_function_behind_even_when_the_test_patched_it_too(monkeypatch):
    """Round 9 (orca-go): the test's monkeypatch is torn down after the fixture and put `par.memory_gb` back to the fixture's 64 GB answer."""
    monkeypatch.setattr(par, "memory_gb", lambda: 7.0)                     # stands for the real function this fixture finds
    fixture = _roomy()
    next(fixture)
    assert par.memory_gb() == 64.0
    test_patch = pytest.MonkeyPatch()
    test_patch.setattr(par, "memory_gb", lambda: 2.0)                      # the test patches it on top of the fixture ...
    fixture.close()                                                        # ... the fixture is torn down first ...
    test_patch.undo()                                                      # ... and the test's patch puts back what it saw
    assert par.memory_gb() == 7.0


# ---------------------------------------------------------------------------------------------------------------- round 9, batch A

@pytest.mark.parametrize("bad", ["nan", "inf", "-5", "0"])
def test_r9_m11_a_gpu_memory_that_is_not_a_positive_number_is_an_error_line_and_exit_2_not_a_traceback(bad, capsys):
    assert cli.main(["plan", "--mission", MISSION, "--gpus", "1", "--gpu-mem-gb", bad, "--assume-gpu"]) == 2
    err = capsys.readouterr().err
    assert err.startswith("error: --gpu-mem-gb ") and "must be a positive number of GB" in err and "Traceback" not in err
    assert cli.main(["plan", "--mission", MISSION, "--gpu-mem-gb", bad]) == 2                                                # no GPUs asked: still refused


def test_r9_m9_plan_prints_the_other_machine_warning_after_the_plan_and_not_inside_it(monkeypatch, capsys):
    import os
    here = dict(budget.throughput(), machine=dict(id="elsewhere", cpu=budget.cpu_model(), cpus=(os.cpu_count() or 1) + 1, measured="2026-11-01"))
    monkeypatch.setattr(budget, "throughput", lambda *a, **k: here)
    assert cli.main(["plan", "--mission", MISSION]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[-1].startswith("note: throughput.json was measured on elsewhere (") and "make bench" in lines[-1]
    assert not [x for x in lines[:-1] if "measured on elsewhere" in x]
    here["machine"]["cpus"] = os.cpu_count() or 1
    assert cli.main(["plan", "--mission", MISSION]) == 0
    assert "throughput.json was measured" not in capsys.readouterr().out


@pytest.mark.parametrize("machine", [["homebase"], "homebase", {"cpus": "8", "cpu": 3}])
def test_r9_m9_a_throughput_file_with_a_malformed_machine_block_still_plans(machine, monkeypatch, capsys):
    bad = dict(budget.throughput(), machine=machine)
    monkeypatch.setattr(budget, "throughput", lambda *a, **k: bad)
    assert cli.main(["plan", "--mission", MISSION]) == 0
    out = capsys.readouterr()
    assert "throughput.json was measured" not in out.out and "Traceback" not in out.err
