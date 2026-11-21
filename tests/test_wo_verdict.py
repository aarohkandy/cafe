"""Work order step 5, the verdict-level fixes: one regression test each (see review/workorder/handbacks/verdict.md)."""
import json
import pickle                      # res.pkl is the pipeline's own checkpoint, written into this test's temporary run directory and read back from there

import numpy as np
import pytest

from cafe.pm import ledger, pipeline, report
from cafe.pm.env import ocean as ocean_mod
from tests.fixtures import pm_run
from tests.test_credibility import factors
from tests.test_report import edit_json, plain, stat_block
from tests.test_pipeline import T0, check_of, ctx_for, run_stage, track_res


@pytest.fixture
def rrun(tmp_path, monkeypatch):
    """A run directory for the report, with no stored receipts and no model-receipts table (what tests/test_report.py's autouse fixture does)."""
    monkeypatch.setenv("CAFE_DATA", str(tmp_path / "data"))
    monkeypatch.setattr(report, "RECEIPTS", tmp_path / "model_receipts.json")
    d = tmp_path / "run"
    d.mkdir()
    return d


@pytest.fixture
def pdata(ci_env, monkeypatch):
    """pipeline and env.ocean read the synthetic tree of ci_env (what tests/test_pipeline.py's module fixture does)."""
    monkeypatch.setattr(pipeline, "DATA", ci_env.data)
    monkeypatch.setattr(ocean_mod, "DATA", ci_env.data)
    monkeypatch.setenv("CAFE_DATA", str(ci_env.data))
    return ci_env


# ---------------------------------------------------------------------------------------------------------------- 6: a missing stage ledger

def test_a_missing_stage_ledger_is_a_problem_and_the_chain_is_not_called_clean(tmp_path, monkeypatch):
    monkeypatch.setenv("CAFE_DATA", str(tmp_path / "data"))
    run = tmp_path / "run"
    run.mkdir()
    pm_run.make_run(run)
    f = factors(run)
    assert f["verification"]["level"] == 2 and f["ms_management"]["level"] == 3
    assert any("ledger chain audits clean" in e["what"] for e in f["verification"]["evidence"])
    (run / "checkpoints" / "emulator" / "ledger.json").unlink()                # the last stage before the report: no later ledger lists it as an input
    f = factors(run)
    assert f["verification"]["level"] == 1 and "stage emulator: no ledger" in " ".join(f["verification"]["missing"])
    assert not any("ledger chain audits clean" in e["what"] for e in f["verification"]["evidence"])
    assert f["ms_management"]["level"] < 3 and not any("ledger chain audits clean" in e["what"] for e in f["ms_management"]["evidence"])


# ---------------------------------------------------------------------------------------------------------------- 7: s_windows and the strict environment

def left_res(t, cls, out_from, out_lon, members_out=(2, 3)):
    """Four members in the box; those of `members_out` fail by `left_data`: their records from `out_from` on are finite and at `out_lon` (outside the box)."""
    res = track_res(t, 4, [(-165.0, 0.0)] * 4, {}, cls)
    gone = np.zeros(4, bool)
    gone[list(members_out)] = True
    for m in members_out:
        res["lon"][out_from:, m] = out_lon
    res["fail"] = {"left_data": gone}
    res["first"] = {"left_data": np.where(gone, t[out_from], np.nan)}
    return res


@pytest.mark.parametrize("cls", ["glider", "usv", "uas"])
def test_windows_do_not_query_the_strict_environment_at_the_records_a_member_left_the_data(tmp_path, pdata, cls):
    t = T0 + 600.0 * np.arange(217)
    ctx = ctx_for(tmp_path / "r")
    ctx.plan["les"]["windows_per_vehicle"] = 2
    out_lon = ctx.env.bounds[0] - 5.0                                                          # west of the cached box, finite
    with open(ctx.path("stage1", "res.pkl"), "wb") as fh:
        pickle.dump(dict(vehicles={"v": left_res(t, cls, 100, out_lon)}), fh)
    assert ctx.env.strict
    run_stage(pipeline.s_windows, ctx, "windows")                                              # raised OutsideData before the fix
    ws = json.loads((ctx.run_dir / "windows" / "windows.json").read_text())["v"]
    assert ws and all(w["lon"] == -165.0 and w["t"] < t[100] for w in ws)                      # from the failed members' records inside the data
    assert all(w["basis"] == pipeline.BASIS[True] and w["failed_at"] == [float(t[100])] * 2 for w in ws)


def test_windows_of_failed_members_that_were_never_inside_the_data_fall_back_to_all_members(tmp_path, pdata):
    t = T0 + 600.0 * np.arange(217)
    ctx = ctx_for(tmp_path / "r")
    ctx.plan["les"]["windows_per_vehicle"] = 2
    out_lon = ctx.env.bounds[0] - 5.0
    with open(ctx.path("stage1", "res.pkl"), "wb") as fh:
        pickle.dump(dict(vehicles={"v": left_res(t, "uas", 0, out_lon)}), fh)
    d = run_stage(pipeline.s_windows, ctx, "windows")
    ws = json.loads((ctx.run_dir / "windows" / "windows.json").read_text())["v"]
    assert len(ws) == 2 and check_of(d, "every_vehicle_has_a_window")["ok"]                    # not [] (a vehicle that failed has a window)
    assert all(w["basis"] == pipeline.BASIS[False] and w["failed_at"] == [] and w["lon"] == -165.0 for w in ws)


def test_a_vehicle_with_every_record_outside_the_data_has_no_window_and_the_check_says_so(tmp_path, pdata):
    t = T0 + 600.0 * np.arange(217)
    ctx = ctx_for(tmp_path / "r")
    out_lon = ctx.env.bounds[0] - 5.0
    with open(ctx.path("stage1", "res.pkl"), "wb") as fh:
        pickle.dump(dict(vehicles={"v": left_res(t, "uas", 0, out_lon, members_out=(0, 1, 2, 3))}), fh)
    with pytest.raises(ledger.StageFailed, match="every_vehicle_has_a_window"):
        run_stage(pipeline.s_windows, ctx, "windows")
    assert json.loads((ctx.run_dir / "windows" / "windows.json").read_text())["v"] == []


# ---------------------------------------------------------------------------------------------------------------- 5: the Stokes drift uncertainty

def test_the_stokes_drift_source_says_the_uncertainty_is_a_median_absolute_error_and_the_number_is_unchanged(ci_full):
    lon, lat = float(ci_full.lou.x[12]), float(ci_full.lau.x[9])
    s = ci_full.waves(lon, lat, ci_full.tw.x[12])["stokes0"]
    assert "median absolute speed error" in s.source and "used as the 1-sigma uncertainty, an assumption" in s.source and "leave-one-out" in s.source
    assert np.allclose(s.uncertainty, ci_full.subgrid.fit["corrected_loo_median_speed_err"] * np.abs(s.value))      # the stored error, not rescaled


# ------------------------------------------------------------------------------------------------------------- 4: the receipt of the seed and the plan values

def test_the_seed_and_the_plan_values_carry_the_hash_of_their_own_file_not_the_ingest_config_hash(rrun):
    m, plan = pm_run.make_run(rrun)
    report.write(rrun, m, plan)
    rep = json.loads((rrun / "report" / "report.json").read_text())
    rows = {r["id"]: r for r in rep["receipts"]}
    seed = rep["mission"]["seed"]
    assert seed["receipt"] == "report:input:mission.yaml" and seed["stage"] == "mission"                      # the printed stage cell is unchanged
    assert rows[seed["receipt"]]["sha256"] == report.sha256(rrun / "mission.yaml")
    box = rep["mission"]["box"]
    assert box["receipt"].startswith("ingest:config:") and box["stage"] == "mission"                          # a mission vehicle value: inside the ingest hash
    p = rep["machine"]["plan"]
    assert p and all(v["receipt"] == "report:input:plan.json" and v["stage"] == "plan" for v in p.values())
    assert rows["report:input:plan.json"]["sha256"] == report.sha256(rrun / "plan.json")
    assert all(r["ok"] and r["ledger"] == "checkpoints/report/ledger.json" for k, r in rows.items() if k.startswith("report:input:"))
    assert rep["traceability_problems"] == [] and report.check_traceability(rep) == []


def test_a_run_file_receipt_for_a_file_that_is_not_there_is_a_missing_row_that_the_traceability_check_flags(rrun):
    tr = report.Trace(rrun)
    ref = tr.run_file_ref("plan.json", "plan")
    assert ref == dict(stage="plan", ledger="checkpoints/report/ledger.json", receipt="report:missing-input:plan.json")
    row = tr.rows[ref["receipt"]]
    assert (row["kind"], row["ok"], row["state"]) == ("missing", False, "not_run")
    node = report.num(1, "s", ref, "plan.json x")
    assert any("is missing or its check failed" in b for b in report.check_traceability(dict(x=node, receipts=list(tr.rows.values()))))


# ---------------------------------------------------------------------------------------------------------------- 1: "needs 73 members" with failures

def test_the_member_count_to_certify_is_a_least_number_because_each_failure_raises_it():
    d = stat_block(1, 512)                                                    # one failure: 73 members are not enough (110 are), and the card said "needs 73"
    assert d["n_certify"]["value"] == 73
    assert "certifying P(fail) < 5 % needs at least 73 members, two-sided 95 % Wilson bound)" in plain(report._stat_html(d))
    d = stat_block(0, 48)
    assert "cannot be certified at n = 48: at least 73 members (two-sided 95 % Wilson bound) are needed" in d["certify_statement"]


# ---------------------------------------------------------------------------------------------------------------- 2: the USV card and a current

def test_the_usv_pages_do_not_say_the_current_is_westward_or_that_it_turns_a_beam_reach_into_a_close_hauled_course(rrun):
    m, plan = pm_run.make_run(rrun)
    edit_json(rrun / "stage1b" / "summary.json", lambda d: d["summary"]["vehicles"]["usv"].update(
        speed=dict(ratio_median=0.107, sog_ms_median=0.55, u10_ms_median=5.1, calibration_ratio=0.96 / 5.4)))
    report.write(rrun, m, plan)
    for name in ("index.html", "credibility.html"):
        t = plain((rrun / "report" / name).read_text())
        assert "westward" not in t and "close-hauled" not in t, name
    t = plain((rrun / "report" / "index.html").read_text())
    assert report.USV_RATIO_NOTE in t and "a possible double penalty that is not established" in t
    assert "the mission's current may then lower the speed ratio again" in plain((rrun / "report" / "credibility.html").read_text())
