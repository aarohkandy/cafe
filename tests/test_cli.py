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

from cafe.pm import __main__ as cli, audit, config, pipeline, whatif
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

    def run(mission, budget, gpus, out, resume=True, stop_after=None, log=print, seed=None, emulator_table=None):
        seen.append(dict(mission=mission, budget=budget, gpus=gpus, out=out, resume=resume, stop_after=stop_after, **({} if seed is None else dict(seed=seed)),
                         **({} if emulator_table is None else dict(emulator_table=emulator_table))))
        return type("Ctx", (), {"run_dir": out})()
    monkeypatch.setattr(pipeline, "run", run)
    return seen


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
    out = tmp_path / "run"
    assert cli.main(["fetch", "--mission", MISSION, "--out", str(out)]) == 0
    assert "ingest: done in" in capsys.readouterr().out
    assert sorted(p.name for p in (out / "checkpoints").iterdir()) == ["ingest"]
    assert json.loads((out / "checkpoints" / "ingest" / "ledger.json").read_text())["ok"]
    assert (out / "ingest" / "priors_fitted.json").is_file() and (out / "plan.json").is_file() and (out / "mission.yaml").is_file()


def test_report_rerenders_a_finished_run(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(pipeline, "DATA", tmp_path / "nodata")
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
