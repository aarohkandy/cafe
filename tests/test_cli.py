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

from cafe.pm import __main__ as cli, config, pipeline
from cafe.pm.env import ocean as ocean_mod
from tests.fixtures import pm_run
from tests.fixtures.fakes import fake_module

MISSION = str(config.ROOT / "missions" / "ci_fixture.yaml")


@pytest.fixture
def calls(monkeypatch):
    """pipeline.run replaced by a recorder that returns an object with a run_dir, as the real one does."""
    seen = []

    def run(mission, budget, gpus, out, resume=True, stop_after=None, log=print):
        seen.append(dict(mission=mission, budget=budget, gpus=gpus, out=out, resume=resume, stop_after=stop_after))
        return type("Ctx", (), {"run_dir": out})()
    monkeypatch.setattr(pipeline, "run", run)
    return seen


def test_validate_reports_the_vehicles_and_links_of_a_valid_mission(capsys):
    assert cli.main(["validate", "--mission", MISSION]) == 0
    assert capsys.readouterr().out == f"{MISSION}: valid (4 vehicles, 3 links)\n"


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
    assert cli.main(["plan", "--mission", MISSION, "--budget", "4h", "--gpus", "2"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("budget 4h (240 min), 2 GPU(s), 1.50 mission days") and "stage 1: 73..256 members in batches of 64" in out
    assert "xlb-warp" in out and all(f"  {v}: " in out for v in ("glider_eq", "glider_1n", "usv", "uas"))


def test_plan_defaults_to_the_quick_budget_on_no_gpu(capsys):
    assert cli.main(["plan", "--mission", MISSION]) == 0
    assert capsys.readouterr().out.startswith("budget quick (20 min), 0 GPU(s)")


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
    assert cli.main(["run", "--mission", MISSION, "--budget", "4h", "--gpus", "1"]) == 0
    out = pathlib.Path("runs/ci_fixture/4h")
    assert calls == [dict(mission=MISSION, budget="4h", gpus=1, out=out, resume=True, stop_after=None)]
    assert capsys.readouterr().out == f"report: {out / 'report' / 'index.html'}\n"


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
    out = tmp_path / "run"
    assert cli.main(["fetch", "--mission", MISSION, "--out", str(out)]) == 0
    assert "ingest: done in" in capsys.readouterr().out
    assert sorted(p.name for p in (out / "checkpoints").iterdir()) == ["ingest"]
    assert json.loads((out / "checkpoints" / "ingest" / "ledger.json").read_text())["ok"]
    assert (out / "ingest" / "priors_fitted.json").is_file() and (out / "plan.json").is_file() and (out / "mission.yaml").is_file()


def test_report_rerenders_a_finished_run(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("CAFE_DATA", str(tmp_path / "nodata"))
    run = tmp_path / "run"
    pm_run.make_run(run)
    assert cli.main(["report", "--run", str(run)]) == 0
    printed = capsys.readouterr().out.split()
    assert printed[0] == str(run / "report" / "index.html") and printed[1] == str(run / "report" / "report.json") and len(printed) == 4
    assert all(pathlib.Path(p).is_file() for p in printed)


def test_report_of_a_directory_that_is_not_a_run_exits_2(tmp_path, capsys):
    assert cli.main(["report", "--run", str(tmp_path)]) == 2
    assert "mission.yaml: file not found" in capsys.readouterr().err
    shutil.copy(MISSION, tmp_path / "mission.yaml")
    with pytest.raises(FileNotFoundError, match="plan.json"):
        cli.main(["report", "--run", str(tmp_path)])


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
