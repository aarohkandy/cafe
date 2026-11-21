"""Work order step 3, the glider: a CPU RANS case (`body_rans`, stage3/rans.py) for each glider whose LES body window is planned out, priced by the plan
(budget.rans_plan, `stage3.glider.rans.*`), queued after the sea-pressure FEA and before the free-surface cases, one row per vehicle, and fed to the refit
when no LES body row passes (pipeline.s_refit). No OpenFOAM here but in the one slow test: the child's solver is a stand-in that returns what two_grid
returns."""
import json
import math
import pathlib
import subprocess
import tempfile

import numpy as np
import pytest

from cafe import cfd
from cafe.pm import budget, credibility as cr, pipeline, report, vv
from cafe.pm.stage3 import pipeline_windows as pw, rans, refit
from tests import test_credibility as tc, test_pipeline as tp, test_stage3 as ts
from tests.fixtures import pm_run
from tests.test_report import load, plain
from tests.test_stage3 import VEHICLES, WIN, FakeL, cheap, fake_ctx, planned_ctx

clean_receipts, fresh_fs, no_wall_receipt = ts.clean_receipts, ts.fresh_fs, ts.no_wall_receipt                 # the fixtures of tests/test_stage3.py
data, sens = tp.data, tp.sens                                              # of test_pipeline.py (the ci_fixture tree s_stage1b reads)
needs_data = pytest.mark.usefixtures("data")

OUT = dict(runs=False, skip_reason="not run: the physical lattice viscosity is out of reach", reachable=False)
RS: dict = {}                                                                     # what the stand-in solver returns and records; reset for each test


@pytest.fixture(autouse=True)
def fresh_rans():
    RS.clear()
    RS.update(drag=0.2467, drag_coarse=0.2582, std=0.0019, cells=1_283_595, coarse_cells=316_022, failed=0, coarse_failed=0, gci=0.085, runner=None,
              calls=[], spawned=[])


def fake_two_grid(stl, label, speed, wd, log=print):
    """Stands in for rans.two_grid (OpenFOAM): checks that the stage handed it a real STL and returns the shape two_grid returns."""
    assert pathlib.Path(stl).stat().st_size > 1000 and cfd.dvec(label) is not None
    RS["calls"].append(dict(stl=stl, label=label, speed=speed))
    return dict(rho=1025.0, speed=speed, label=label, cells=RS["cells"], coarse_cells=RS["coarse_cells"], failed_checks=RS["failed"],
                coarse_failed_checks=RS["coarse_failed"], drag=RS["drag"], drag_coarse=RS["drag_coarse"], drag_std=RS["std"], gci=RS["gci"],
                refinement_ratio=0.0, iterations=600, seconds=12.5, levels=dict(rans.LEVELS), iterations_cap=rans.ITERS)


def spawn(cmd, **kw):
    """The children in this process: the RANS child with the stand-in solver (or RS["runner"]), an exception being what a crashing child's exit 1 is."""
    if "cafe.pm.stage3.rans" not in cmd:
        return ts.in_process_fea(cmd, **kw)
    RS["spawned"].append(dict(kw, cmd=cmd))
    try:
        return subprocess.CompletedProcess(cmd, rans.run_child(cmd[-3], cmd[-2], runner=RS["runner"] or fake_two_grid), "", "")
    except Exception as e:                                                      # (a child's traceback ends with the exception)
        return subprocess.CompletedProcess(cmd, 1, "", f"Traceback (most recent call last):\n{type(e).__name__}: {e}\n")


@pytest.fixture
def rans_env(monkeypatch):
    cheap(monkeypatch)
    monkeypatch.setattr(pw, "_spawn", spawn)
    monkeypatch.setattr(pw.W, "run_window", lambda *a, **k: pytest.fail("a window the plan skipped was run"))


def rans_ctx(tmp, share=5000.0):
    """One glider whose LES part is planned out and a stage-3 share of `share` s (no FEA hold: the FEA says "not planned" and starts no child)."""
    return planned_ctx(tmp, dict({"g/body": dict(OUT)}), share)


def body_rans(rows):
    return [r for r in rows if r["part"] == "body_rans"]


def test_t1_a_glider_whose_les_part_is_planned_out_gets_one_rans_row_with_a_label_a_drag_and_no_lift(no_wall_receipt, rans_env):
    """Before: no part `body_rans` (the CPU fallback was "not run"), so no row and no child."""
    L = FakeL()
    windows = [WIN, dict(WIN, t=WIN["t"] + 3600.0), dict(WIN, t=WIN["t"] + 7200.0)]
    rows = pw.run(rans_ctx(no_wall_receipt), {"g": windows}, L)["g"]
    assert [r["part"] for r in rows] == ["body", "body", "body", "body_rans"] and len(RS["calls"]) == 1             # one case per vehicle, not one per window
    r = rows[3]
    assert r["ok"] and r["reasons"] == [] and r["label"] == rans.LABEL == "RANS (OpenFOAM simpleFoam, k-omega SST), CPU, two-grid GCI"
    assert (r["t"], r["lon"], r["lat"]) == (WIN["t"], WIN["lon"], WIN["lat"])                                          # the first window
    assert r["cl"] is None and r["cl_spread"] is None and r["cl_hangar"] is None and r["cd_hangar"] > 0 and r["fluid"] == "water"
    q = 0.5 * 1025.0 * RS["calls"][0]["speed"] ** 2 * r["ref_area"]
    assert r["cd"] == pytest.approx(RS["drag"] / q) and r["cd_spread"] == pytest.approx(math.hypot(RS["gci"] * r["cd"], RS["std"] / q))
    assert r["gci"] == RS["gci"] and r["refinement_ratio"] == pytest.approx((RS["cells"] / RS["coarse_cells"]) ** (1 / 3)) and r["refinement_ratio"] > 1.3
    assert r["added_resistance"] == pytest.approx(r["cd"] / r["cd_hangar"] - 1.0) and r["resolution"]["cells_fine"] == RS["cells"]
    assert [c["name"] for c in r["checks"]] == ["rans_gci", "rans_refinement_ratio", "rans_iterative_scatter", "rans_mesh_checks"]
    assert all(c["ok"] and c["note"] for c in r["checks"]) and r["timing"]["rans_s"] == 12.5
    assert L.checks["every_window_attempted"] == (True, 4, 4) and L.checks["no_row_claims_ok_with_a_failing_check"][0]
    assert L.checks["every_failed_window_states_a_reason"][0]
    assert [r["part"] for r in rows if not r["ok"]] == ["body", "body", "body"]                                          # the LES rows are as they were


def test_t2_the_child_gets_a_real_closed_stl_the_flow_label_and_speed_of_the_window_and_a_watchdog(no_wall_receipt, rans_env):
    pw.run(rans_ctx(no_wall_receipt), {"g": [WIN]}, FakeL())
    (call,), (spawned,) = RS["calls"], RS["spawned"]
    assert spawned["cmd"][2] == "cafe.pm.stage3.rans" and spawned["start_new_session"] and float(spawned["cmd"][-1]) < 1e9      # killed at the stage deadline
    row = body_rans(pw.run(rans_ctx(no_wall_receipt / "2"), {"g": [WIN]}, FakeL())["g"])[0]
    vb = np.asarray(row["velocity_body_ms"])
    unit = cfd.dvec(call["label"])
    assert call["speed"] == pytest.approx(np.linalg.norm(vb)) and np.dot(unit, vb / np.linalg.norm(vb)) > math.cos(math.radians(0.01))
    assert row["resolution"]["flow_label"] == call["label"] and call["label"].startswith("x-z")                              # a descending glider


def test_t3_the_label_of_the_flow_direction_takes_the_sign_of_the_vertical_component_and_refuses_what_it_cannot_carry():
    assert rans.flow_label([0.13, 0.0, 0.012]) == ("x+z5.27", pytest.approx(math.hypot(0.13, 0.012)))
    assert rans.flow_label([0.13, 0.0, -0.012])[0] == "x-z5.27" and rans.flow_label([0.1, 0.0, 0.0])[0] == "x+z0.00"
    for bad in ([-0.1, 0.0, 0.0], [0.0, 0.0, 0.1], [0.1, 0.01, 0.0], [0.0, 0.0, 0.0], [math.nan, 0.0, 0.0]):
        with pytest.raises(ValueError, match="not a forward motion"):
            rans.flow_label(bad)
    assert all(cfd.dvec(rans.flow_label([1.0, 0.0, z])[0]) is not None for z in (-5.0, -0.2, 0.0, 0.2, 5.0))


COARSE_12 = int(1_283_595 / 1.2 ** 3)                                                                              # a coarse grid 1.2 times coarser in length
FAILS = [("rans_mesh_checks", dict(failed=1), "checkMesh failed 1 mesh check(s) (fine grid 1, coarse grid 0)"),
         ("rans_mesh_checks", dict(coarse_failed=2), "checkMesh failed 2 mesh check(s) (fine grid 0, coarse grid 2)"),
         ("rans_gci", dict(gci=0.11), "grid-convergence index 11% is above 10%"),
         ("rans_gci", dict(gci=math.nan), "no grid-convergence index"),
         ("rans_refinement_ratio", dict(coarse_cells=COARSE_12), f"refinement ratio r = 1.20 (cells 1,283,595 / {COARSE_12:,}) is below 1.3"),
         ("rans_refinement_ratio", dict(cells=0), "refinement ratio unknown (no cell counts)"),
         ("rans_iterative_scatter", dict(std=0.03 * 0.2467), "the drag still wanders by 3.0% over the last 20 % of iterations (limit 2%): not converged"),
         ("rans_iterative_scatter", dict(std=None), "the solver reported no force history")]


@pytest.mark.parametrize("name, change, reason", FAILS)
def test_t4_each_check_can_fail_alone_and_says_why_in_one_sentence(no_wall_receipt, rans_env, name, change, reason):
    RS.update(change)
    L = FakeL()
    r = body_rans(pw.run(rans_ctx(no_wall_receipt), {"g": [WIN]}, L)["g"])[0]
    assert [c["name"] for c in r["checks"] if not c["ok"]] == [name] and not r["ok"]
    assert len(r["reasons"]) == 1 and r["reasons"][0].startswith(reason) and r["cd"] > 0 and r["cd_spread"] > 0
    assert L.checks["every_failed_window_states_a_reason"][0] and L.checks["no_row_claims_ok_with_a_failing_check"][0]


def test_t4b_a_row_with_several_failures_has_a_sentence_for_each():
    r = dict(cells=100, coarse_cells=99, failed_checks=3, coarse_failed_checks=0)
    f = rans.row_fields(dict(r, rho=1025.0, speed=0.13, drag=0.25, gci=0.5, drag_std=0.1), 0.0707, 0.3)
    assert [c["name"] for c in f["checks"] if not c["ok"]] == [c["name"] for c in f["checks"]]
    assert len(rans.reasons(f["checks"], r)) == 4 and f["cd_spread"] == pytest.approx(math.hypot(0.5 * f["cd"], 0.1 / (0.5 * 1025.0 * 0.13 ** 2 * 0.0707)))


@pytest.mark.parametrize("bad, why", [(dict(drag=-1.0), "RANS window failed: the RANS run returned a non-physical drag (-1.0 N)"),
                                      (dict(drag=math.nan), "RANS window failed: the RANS run returned a non-physical drag (nan N)")])
def test_t5_a_nonsense_result_is_a_row_that_says_so(no_wall_receipt, rans_env, bad, why):
    RS.update(bad)
    r = body_rans(pw.run(rans_ctx(no_wall_receipt), {"g": [WIN]}, FakeL())["g"])[0]
    assert not r["ok"] and r["error"] == why and r["reasons"] == [why] and r["cd"] is None and r["label"] == rans.LABEL and r["part"] == "body_rans"


def test_t6_a_child_that_fails_is_killed_or_cannot_start_is_a_row_that_says_so_and_the_stage_does_not_raise(no_wall_receipt, rans_env, monkeypatch):
    def boom(stl, label, speed, wd, log=print):
        raise RuntimeError("simpleFoam diverged")

    def late(cmd, **k):
        raise subprocess.TimeoutExpired(cmd, 1.0)

    def no_python(cmd, **k):
        raise OSError("no such interpreter")

    def exits(rc):
        return lambda cmd, **k: subprocess.CompletedProcess(cmd, rc, "", "")

    def go():
        return body_rans(pw.run(rans_ctx(no_wall_receipt), {"g": [WIN]}, FakeL())["g"])[0]
    RS["runner"] = boom
    r = go()
    assert r["error"] == "RANS run failed (1): RuntimeError: simpleFoam diverged" and not r["ok"] and r["reasons"] == [r["error"]] and r["cd"] is None
    RS["runner"] = None
    monkeypatch.setattr(pw, "_spawn", exits(0))                                                                  # exit 0 and no file
    assert go()["error"] == "RANS run failed (0): no message"
    monkeypatch.setattr(pw, "_spawn", exits(-9))
    assert go()["error"] == "RANS run failed (-9): killed by SIGKILL before its deadline (out of memory or an outside kill, not the watchdog)"
    monkeypatch.setattr(pw, "_killed_at_deadline", lambda rc, armed_s, started: True)
    assert go()["error"] == "RANS run failed (-9): killed by its watchdog at the deadline"
    monkeypatch.setattr(pw, "_spawn", late)
    assert go()["error"].startswith("RANS run killed at its deadline after ") and go()["reasons"]
    monkeypatch.setattr(pw, "_spawn", no_python)
    assert go()["error"] == "RANS window failed: no such interpreter"


def test_t7_a_window_the_deadline_has_passed_is_not_started_and_the_job_directory_goes_away(no_wall_receipt, rans_env, monkeypatch):
    jobs = pathlib.Path(no_wall_receipt) / "tmp"
    jobs.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(jobs))
    ctx = rans_ctx(no_wall_receipt)
    pw.run(ctx, {"g": [WIN]}, FakeL())
    assert list(jobs.iterdir()) == [] and len(RS["calls"]) == 1                                                  # the case ran, and nothing of it is left
    a = pw.assumptions()
    P, veh = pw._glider_vehicle_for(ctx, "g", "seaglider", a, clip=False)
    case = pw.glider_case(ctx, WIN, P, veh, a, None)
    vb = case["R"] @ (case["v"] - case["u_env"])
    label, speed = rans.flow_label(vb)
    r = pw._rans_work(pw._base(ctx, WIN, "body_rans"), veh, case, speed, label, 867.0, pw.time.perf_counter() - 1.0, pw.time.perf_counter())
    assert r["error"].startswith("RANS window killed before it started") and list(jobs.iterdir()) == [] and len(RS["calls"]) == 1


def test_t8_a_case_that_does_not_fit_the_share_is_a_row_with_the_gate_sentence_and_starts_no_child(no_wall_receipt, rans_env):
    L = FakeL()
    r = body_rans(pw.run(rans_ctx(no_wall_receipt, share=1000.0), {"g": [WIN]}, L)["g"])[0]
    why = ("RANS window not run: estimated 14 min x 1.25 margin = 18 min (two grids, 600 iterations) against 16.7 min left of the 17 min stage-3 share "
           "after the FEA and the free-surface cases; it would fit --budget overnight (16667 min of stage 3 in that plan)")
    assert not r["ok"] and r["error"] == why and r["reasons"] == [why] and r["cd"] is None and RS["spawned"] == [] and r["label"] == rans.LABEL
    assert r["resolution"]["left_s"] == 1000.0 and r["resolution"]["estimated_s"] == 867.0 and L.checks["every_window_attempted"][0]
    assert pw._rans_gate(pw.assumptions(), rans_ctx(no_wall_receipt), 1083.75, 0.0) == (True, "", 1083.75)             # exactly margin x estimate fits
    assert not pw._rans_gate(pw.assumptions(), rans_ctx(no_wall_receipt), 1083.7, 0.0)[0]
    quick = body_rans(pw.run(rans_ctx(no_wall_receipt, share=0.0), {"g": [WIN]}, FakeL())["g"])[0]
    assert not quick["ok"] and "against 0.0 min left of the 0 min stage-3 share" in quick["error"]


def test_t9_with_no_wall_clock_budget_the_case_runs_with_no_deadline_and_a_failing_kinematics_is_a_row_that_says_so(no_wall_receipt, rans_env, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    ctx = rans_ctx(no_wall_receipt)
    a, st = pw.assumptions(), dict(rans_queued=0.0, queued=0.0, deadline=None)
    with ThreadPoolExecutor(1) as pool:
        r = pw._rans_submit(pool, ctx, "g", WIN, "seaglider", None, a, st, dict(rans=dict(share_s=None))).result()
    spawned = RS["spawned"][0]                                                                                         # no share, no deadline
    assert r["ok"] and float(spawned["cmd"][-1]) == 1e9 and spawned["timeout"] is None and st["rans_queued"] == 0.0
    monkeypatch.setattr(pw, "glider_case", lambda *a, **k: (_ for _ in ()).throw(ValueError("the glider has no steady flight")))
    bad = body_rans(pw.run(rans_ctx(no_wall_receipt / "2"), {"g": [WIN]}, FakeL())["g"])[0]
    assert not bad["ok"] and bad["error"] == "the glider has no steady flight" and bad["reasons"] == [bad["error"]] and len(RS["calls"]) == 1


def test_t10_the_rans_case_runs_before_the_free_surface_case_and_leaves_its_seconds_whole(no_wall_receipt, rans_env, monkeypatch):
    """Two gliders and a USV on a share that holds the free-surface case and one RANS case. The RANS gate must not count the free-surface seconds as
    its own: against the whole share both gliders' cases would pass (the queue runs them first) and the free-surface case would then be refused."""
    monkeypatch.setenv("CAFE_NPROC", "6")
    order, real = [], pw._spawn
    monkeypatch.setattr(pw, "_spawn", lambda cmd, **kw: (order.append("rans" if "cafe.pm.stage3.rans" in cmd else "fs"), real(cmd, **kw))[1])
    ctx = fake_ctx(no_wall_receipt, vehicles=[VEHICLES[0], VEHICLES[1], VEHICLES[2]], classes=dict(g="glider", g2="glider", u="usv"), rate=2000.0)
    a = pw.assumptions()
    fs_need = budget.fs_plan(ctx.classes, 1, a, None)["need_s"]
    one = a["glider.rans.est_s"] * a["glider.rans.margin"]
    ctx.plan.update(shares=dict(stage3=1.0), budget_s=fs_need + one + 60.0)
    ctx.plan["les"]["windows"] = {k: dict(OUT) for k in ("g/body", "g2/body", "u/hull", "u/wing")}
    rows = pw.run(ctx, {"g": [WIN], "g2": [WIN], "u": [WIN]}, FakeL())
    assert order == ["rans", "fs"] and len(RS["calls"]) == 1
    assert body_rans(rows["g"])[0]["ok"] and not body_rans(rows["g2"])[0]["ok"] and "RANS window not run" in body_rans(rows["g2"])[0]["error"]
    assert rows["u"][-1]["part"] == "hull_fs" and rows["u"][-1]["ok"] and rows["u"][-1]["cd"] is not None
    assert budget.stage3_plan(ctx.plan, ctx.classes, a)["rans"]["fit"] == 1 and budget.stage3_plan(ctx.plan, ctx.classes, a)["fs"]["fit"] == 1


def test_t11_a_usv_a_uas_and_a_glider_planned_for_a_gpu_get_no_rans_row(no_wall_receipt, rans_env):
    ctx = fake_ctx(no_wall_receipt, vehicles=[VEHICLES[0], VEHICLES[2], VEHICLES[3]], classes=dict(g="glider", u="usv", q="uas"), rate=2000.0)
    ctx.plan.update(shares=dict(stage3=1.0), budget_s=1e6)
    ctx.plan["les"]["windows"] = {k: dict(OUT) for k in ("g/body", "u/hull", "u/wing", "q/body")}
    rows = pw.run(ctx, {v: [WIN] for v in ("g", "u", "q")}, FakeL())
    assert [v for v, rs in rows.items() if body_rans(rs)] == ["g"] and len(RS["calls"]) == 1
    gpu = rans_ctx(no_wall_receipt / "gpu")
    gpu.plan["les"]["cpu_fallback"] = False
    assert body_rans(pw.run(gpu, {"g": [WIN]}, FakeL())["g"]) == [] and len(RS["calls"]) == 1


MISSION = dict(window=dict(start="2023-03-01T12:00:00Z", end="2023-03-07T12:00:00Z"))
CL2 = dict(glider_eq="glider", glider_2n="glider", usv="usv", uas="uas")


def test_t12_the_plan_prices_the_rans_cases_after_the_fea_and_the_free_surface_cases_and_the_shares_still_sum_as_before(monkeypatch):
    monkeypatch.setenv("CAFE_NPROC", "6")
    a, B = budget.stage3_assumptions(), budget.BUDGET_S["overnight"]
    p = budget.plan("overnight", 0, MISSION, thr={}, vehicle_classes=CL2)
    s = budget.stage3_plan(p, CL2, a)
    need, hold = a["glider.rans.est_s"] * a["glider.rans.margin"], p["les"]["fea_hold_s"]
    assert s["rans"]["cases"] == 2 and s["rans"]["vehicles"] == ["glider_eq", "glider_2n"] and s["rans"]["fit"] == 2 and s["rans"]["need_s"] == need
    assert s["fs"]["fit"] >= 1 and hold == 2 * a["fea_min_s"]
    used = s["fs"]["fit"] * s["fs"]["need_s"] + hold + s["rans"]["fit"] * need
    assert used <= p["shares"]["stage3"] * B + 1e-6 and p["shares"]["stage3"] * B == pytest.approx(used)               # the share is what the three claim
    assert sum(p["shares"].values()) == pytest.approx(sum(budget.SHARE.values())) and p["shares"]["stage1"] >= budget.SHARE["stage1"] - 1e-12
    assert s["rans"]["share_s"] == pytest.approx(p["shares"]["stage3"] * B - hold - s["fs"]["fit"] * s["fs"]["need_s"])
    # a share that holds one of the two: one is planned, the other's seconds went to stage 1
    left = B * budget.SHARE["stage3"] - hold - s["fs"]["fit"] * s["fs"]["need_s"]
    one = left / 1.5 / a["glider.rans.margin"]                                                                       # 1.5 cases in the share left
    monkeypatch.setattr(budget, "stage3_assumptions", lambda: dict(a, **{"glider.rans.est_s": one}))
    q = budget.plan("overnight", 0, MISSION, thr={}, vehicle_classes=CL2)
    t = budget.stage3_plan(q, CL2, dict(a, **{"glider.rans.est_s": one}))
    assert t["rans"]["fit"] == 1 and t["rans"]["cases"] == 2 and q["shares"]["stage1"] > p["shares"]["stage1"]
    assert sum(q["shares"].values()) == pytest.approx(sum(budget.SHARE.values()))
    assert q["shares"]["stage3"] * B == pytest.approx(t["fs"]["fit"] * t["fs"]["need_s"] + hold + one * 1.25)


def test_t13_what_the_plan_keeps_is_what_the_run_prices_over_a_sweep_of_estimates(monkeypatch):
    """`stage3_plan` reads the share back as (kept / budget) x budget, a few 1e-13 s away from `kept`: the cases the plan priced must still fit."""
    monkeypatch.setenv("CAFE_NPROC", "6")
    a, B = budget.stage3_assumptions(), budget.BUDGET_S["overnight"]
    refused = []
    for i in range(150):
        b = dict(a, **{"glider.rans.est_s": 600.0 + 2.93 * i})
        monkeypatch.setattr(budget, "stage3_assumptions", lambda b=b: b)
        p = budget.plan("overnight", 0, MISSION, thr={}, vehicle_classes=CL2)
        s = budget.stage3_plan(p, CL2, b)
        fs_s = s["fs"]["fit"] * s["fs"]["need_s"]
        want = budget.rans_plan(CL2, p["les"]["windows"], b, budget.SHARE["stage3"] * B - fs_s - p["les"]["fea_hold_s"])
        total = sum(p["shares"].values())
        if s["rans"]["fit"] != want["fit"] or total != pytest.approx(sum(budget.SHARE.values())) or p["shares"]["stage1"] < budget.SHARE["stage1"] - 1e-12:
            refused.append(b["glider.rans.est_s"])
        assert s["rans"]["fit"] * s["rans"]["need_s"] + fs_s + p["les"]["fea_hold_s"] <= p["shares"]["stage3"] * B + 1e-6
    assert not refused


def test_t14_no_rans_case_is_planned_on_a_gpu_or_when_the_les_window_runs_or_for_a_vehicle_that_is_no_glider(monkeypatch):
    monkeypatch.setenv("CAFE_NPROC", "6")
    a = budget.stage3_assumptions()
    gpu = budget.plan("overnight", 1, MISSION, thr={}, vehicle_classes=CL2)
    assert budget.stage3_plan(gpu, CL2, a)["rans"] is None and budget.rans_plan(CL2, {}, a, None) is None
    runs = {f"{v}/body": dict(runs=True) for v in ("glider_eq", "glider_2n")}
    assert budget.rans_plan(CL2, runs, a, None) is None and budget.rans_vehicles(CL2, runs, True) == []
    out = {"glider_eq/body": dict(runs=False), "glider_2n/body": dict(runs=True), "usv/hull": dict(runs=False), "uas/body": dict(runs=False)}
    assert budget.rans_vehicles(CL2, out, True) == ["glider_eq"] and budget.rans_vehicles(CL2, out, False) == []
    plan = budget.rans_plan(CL2, out, a, None)
    assert plan["fit"] == plan["cases"] == 1 and plan["share_s"] is None
    assert budget.rans_plan(CL2, out, a, -5.0)["fit"] == 0
    assert budget.rans_plan(CL2, out, a, plan["need_s"] - 1e-7)["fit"] == 1                                          # a microsecond of rounding is allowed
    assert budget.rans_plan(CL2, out, a, plan["need_s"] - 1e-3)["fit"] == 0


def test_t15_the_plan_label_and_notes_drop_only_the_refit_claim_when_a_case_fits_and_keep_the_old_text_when_none_does(monkeypatch):
    monkeypatch.setenv("CAFE_NPROC", "6")
    a = budget.stage3_assumptions()
    p = budget.plan("overnight", 0, MISSION, thr={}, vehicle_classes=CL2)
    assert budget.stage3_plan(p, CL2, a)["rans"]["fit"] == 2
    assert p["les"]["label"].startswith("CPU fallback") and p["les"]["label"].endswith("sub-grid stays uncalibrated") and "refit" not in p["les"]["label"]
    assert any(n.endswith("went to stage 1; the sub-grid layer stays uncalibrated") for n in p["notes"])
    assert budget.stage3_plan(p, CL2, a)["les"]["note"] == "no LES coefficients exist on this machine; sub-grid stays uncalibrated"
    q = budget.plan("quick", 0, MISSION, thr={}, vehicle_classes=CL2)                                              # no case fits 20 min
    assert budget.stage3_plan(q, CL2, a)["rans"]["fit"] == 0
    assert q["les"]["label"].startswith("CPU fallback") and q["les"]["label"].endswith("sub-grid and refit stay uncalibrated")
    assert any(n.endswith("went to stage 1; the sub-grid layer and the refit stay uncalibrated") for n in q["notes"])
    assert budget.stage3_plan(q, CL2, a)["les"]["note"] == "no LES coefficients exist on this machine; sub-grid and refit stay uncalibrated"


@pytest.fixture
def cred_run(tmp_path, monkeypatch):
    monkeypatch.setenv("CAFE_DATA", str(tmp_path / "data"))
    d = tmp_path / "run"
    d.mkdir()
    pm_run.make_run(d)
    return d


def test_t16_the_two_new_assumptions_are_the_gliders_and_each_has_its_value_unit_why_and_replacement(cred_run):
    got = cr.config.assumptions()
    for k, v in (("est_s", 867.0), ("margin", 1.25)):
        e = got[f"stage3.glider.rans.{k}"]
        assert e["value"] == v and {"unit", "why", "replace_with"} <= set(e) and e["why"] and e["replace_with"]
    assert "rans_g4" in got["stage3.glider.rans.est_s"]["why"] and "2026-11-20" in got["stage3.glider.rans.est_s"]["why"]
    keys = {"stage3.glider.rans.est_s", "stage3.glider.rans.margin"}
    assert keys <= tc.used_of(tc.only(cred_run, {"glider_eq"}), "config/assumptions.yaml")
    assert keys.isdisjoint(tc.used_of(tc.only(cred_run, {"uas"}), "config/assumptions.yaml"))
    assert keys.isdisjoint(tc.used_of(tc.only(cred_run, {"usv"}), "config/assumptions.yaml"))


# ---------------------------------------------------------------------------------------------------- the refit

def rans_row(cd=0.373, hangar=0.301, spread=0.04, **kw):
    return dict(tp.stage3_row(cd=cd, hangar=hangar, spread=spread), part="body_rans", cl=None, cl_spread=None, cl_hangar=None, **kw)


def test_t17_a_passing_rans_row_alone_sets_the_gliders_multiplier_with_one_window(tmp_path):
    """Before: `main` was "body" for a glider, so the row was discarded and the glider kept the analytic coefficients."""
    les = dict(tp.stage3_row(ok=False), part="body")
    out = tp.refit_run(tmp_path, {"glider_eq": [les, rans_row()]})[0]["glider_eq"]
    assert out["used"] and out["part"] == "body_rans" and out["drag"]["windows"] == 1 and out["drag"]["mean"] == pytest.approx(0.373 / 0.301)
    assert out["drag"]["sigma_statistical"] == pytest.approx(0.04 / 0.301)
    assert out["drag"]["sigma"] > out["drag"]["sigma_statistical"]                                                   # the floors apply to one window
    assert out["drag"]["sigma_between"] > 0.0 and "lift" not in out and out["body_not_used"] == dict(
        reason="no LES body window passed its checks: the RANS window (body_rans) sets the multiplier")


def test_t18_a_passing_les_body_row_wins_and_the_two_are_never_pooled(tmp_path):
    out = tp.refit_run(tmp_path, {"glider_eq": [dict(tp.stage3_row(cd=1.1), part="body"), rans_row()]})[0]["glider_eq"]
    assert out["used"] and out["part"] == "body" and out["drag"]["windows"] == 1 and out["drag"]["mean"] == pytest.approx(1.1)
    assert out["body_rans_not_used"]["drag"]["mean"] == pytest.approx(0.373 / 0.301) and "not pooled" in out["body_rans_not_used"]["reason"]


def test_t19_a_failing_rans_row_leaves_the_glider_on_the_analytic_coefficients_and_says_which_checks_failed(tmp_path):
    bad = dict(rans_row(ok=False), checks=[pm_run.check_row("rans_gci", 0.2, 0.1, False), pm_run.check_row("rans_mesh_checks", 0.0, 0.0, True)])
    out = tp.refit_run(tmp_path, {"glider_eq": [dict(tp.stage3_row(ok=False), part="body"), bad]})[0]["glider_eq"]
    assert out["used"] is False and out["failed_checks"] == ["mach_max", "rans_gci"] and out["reason"].startswith("no body window passed")
    assert out["body_rans_not_used"] == dict(reason="no window of this part passed its checks")
    no_rans = tp.refit_run(tmp_path / "2", {"glider_eq": [dict(tp.stage3_row(ok=False), part="body")]})[0]["glider_eq"]
    assert no_rans["used"] is False and "body_rans_not_used" not in no_rans                                          # no RANS row: as it was


@needs_data
def test_t20_stage_1b_reruns_stage_1_with_the_refit_of_a_glider_that_has_only_a_rans_row(tmp_path, monkeypatch, sens):
    """Before: refit.json said the glider was not used, so stage 1b was a copy of stage 1 (`refit_iterations_performed` 0)."""
    ctx = tp.ctx_for(tmp_path / "r")
    tp.stage1_files(ctx)
    ctx.plan["refit_iterations"] = 2
    ctx.path("stage3", "windows.json").write_text(json.dumps({"glider_eq": [dict(tp.stage3_row(ok=False), part="body"), rans_row()]}))
    tp.run_stage(pipeline.s_refit, ctx, "refit")
    seen, fake = [], tp.summaries(ctx, {"glider_eq": "NO-GO"}, {"glider_eq": "GO"})
    monkeypatch.setattr(pipeline, "_stage1", lambda c, L, name, scales=None, extra=None: (seen.append((scales, extra)), fake(c, L, name, scales, extra))[1])
    d = tp.run_stage(pipeline.s_stage1b, ctx, "stage1b")
    (scales, extra), = seen
    assert extra == dict(refit_iterations_performed=1) and list(scales) == ["glider_eq"] and scales["glider_eq"]["part"] == "body_rans"
    assert "copied" not in " ".join(d["notes"]) and not (ctx.run_dir / "stage1b" / "res.pkl").exists()


def test_t21_the_row_the_stage_writes_feeds_the_refit_with_drag_over_hangar_and_no_lift(no_wall_receipt, rans_env):
    """The stage's own row, through refit.refit (no lift key: a row with a lift hangar value and no lift would raise) and s_refit."""
    r = body_rans(pw.run(rans_ctx(no_wall_receipt), {"g": [WIN]}, FakeL())["g"])[0]
    assert r["cl_hangar"] is None and "lift" not in refit.refit([r])
    out = tp.refit_run(no_wall_receipt / "refit", {"glider_eq": [r]})[0]["glider_eq"]
    assert out["used"] and out["part"] == "body_rans" and out["drag"]["mean"] == pytest.approx(r["cd"] / r["cd_hangar"]) and out["drag"]["windows"] == 1
    assert "lift" not in out and out["floor"]["between_window_frac"] > 0 and out["drag"]["sigma_between"] > 0


# ---------------------------------------------------------------------------------------------------- the child and the reader of the force history

def write_forces(case, fx, fy, fz):
    d = pathlib.Path(case) / "postProcessing" / "forces" / "0"
    d.mkdir(parents=True)
    for kind in ("force", "moment"):
        rows = ["# header"] + [f"{i} ({a} {b} {c}) (0 0 0) ({a} {b} {c})" for i, (a, b, c) in enumerate(zip(fx, fy, fz, strict=True), 1)]
        (d / f"{kind}.dat").write_text("\n".join(rows) + "\n")


def test_t22_the_scatter_is_the_std_of_the_drag_not_the_norm_of_the_force_std_and_survives_the_shrink(tmp_path):
    n, label = 500, "x-z5.00"
    i = np.arange(n)
    fx, fy, fz = -0.25 + 0 * i, 0 * i, 0.1 + 0.02 * np.sin(0.7 * i)                       # a lift that wanders by 0.02 N and a drag that hardly does
    write_forces(tmp_path / "case", fx, fy, fz)
    (tmp_path / "case" / "processor0").mkdir()
    (tmp_path / "case" / "constant" / "polyMesh").mkdir(parents=True)
    cfd._shrink(tmp_path / "case")                                                           # cfd._shrink keeps postProcessing: the history is read after it
    mean, std = rans.drag_history(tmp_path / "case", label)
    drag = -(np.stack([fx, fy, fz], 1) @ cfd.dvec(label))
    assert mean == pytest.approx(drag[-100:].mean()) and std == pytest.approx(drag[-100:].std()) and std / mean < 0.01
    force_std = np.stack([fx, fy, fz], 1)[-100:].std(0)
    assert np.linalg.norm(force_std) / mean > 0.04                                           # the old figure would have failed a settled case twice over
    assert rans.drag_history(tmp_path / "none", label) is None
    d = tmp_path / "bad" / "postProcessing" / "forces" / "0"
    d.mkdir(parents=True)
    (d / "force.dat").write_text("0 (a b c) (0 0 0) (0 0 0)\n")
    (d / "moment.dat").write_text("0 (0 0 0) (0 0 0) (0 0 0)\n")
    assert rans.drag_history(tmp_path / "bad", label) is None


def fake_external(calls, drags, fails):
    """cafe.cfd.external stood in: writes a case with a force history (and a mesh to shrink) and returns what the real one does for one direction."""
    def external(stl, case, fluid="water", speed=1.5, dirs=(), level_offset=0, cofr=(0, 0, 0), iters=1500, pressure_dir="+x", log=print):
        (label,) = dirs
        calls.append(dict(stl=stl, case=pathlib.Path(case), fluid=fluid, speed=speed, label=label, level_offset=level_offset, iters=iters))
        d = drags[level_offset]
        f = -d * cfd.dvec(label)
        write_forces(case, np.full(300, f[0]), np.full(300, f[1]), f[2] + 0.001 * np.sin(np.arange(300)))
        (pathlib.Path(case) / "processor0").mkdir()
        return dict(fluid=fluid, rho=1025.0, nu=1.19e-6, speed=speed, L=1.8, level=6 + level_offset, mesh=dict(cells=[316_022, 1_283_595][level_offset],
                    failed_checks=fails[level_offset]), seconds=20.0,
                    dirs={label: dict(force=f.tolist(), force_std=[0.0, 0.0, 0.0], iters=600, seconds=10.0 + level_offset)})
    return external


def test_t23_two_grid_runs_the_two_levels_with_the_iterations_the_probe_measured_and_gives_the_gci_and_both_meshes_checks(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(cfd, "external", fake_external(calls, {0: 0.2582, 1: 0.2467}, {0: 1, 1: 0}))
    r = rans.two_grid("body.stl", "x-z5.29", 0.1352, tmp_path)
    assert [(c["case"].name, c["level_offset"], c["iters"], c["label"], c["fluid"], c["speed"]) for c in calls] == [
        ("coarse", 0, 600, "x-z5.29", "water", 0.1352), ("fine", 1, 600, "x-z5.29", "water", 0.1352)]
    assert rans.LEVELS == {"coarse": 0, "fine": 1} and rans.ITERS == 600
    rr = vv.refinement_ratio(1_283_595, 316_022)
    assert r["drag"] == pytest.approx(0.2467) and r["drag_coarse"] == pytest.approx(0.2582) and r["refinement_ratio"] == pytest.approx(rr)
    assert r["gci"] == pytest.approx(cfd.gci(0.2467, 0.2582, ratio=rr)) and 0.08 < r["gci"] < 0.1                       # the probe's figure for these drags
    assert (r["cells"], r["coarse_cells"], r["failed_checks"], r["coarse_failed_checks"]) == (1_283_595, 316_022, 0, 1) and r["seconds"] == 40.0
    assert 0 < r["drag_std"] < 0.001 and r["iterations"] == 600 and r["levels"] == rans.LEVELS and r["iterations_cap"] == 600
    assert not (tmp_path / "coarse" / "processor0").exists() and not (tmp_path / "fine" / "processor0").exists()            # each case was shrunk
    json.dumps(r)
    monkeypatch.setattr(cfd, "external", fake_external([], {0: -0.1, 1: 0.2}, {0: 0, 1: 0}))
    with pytest.raises(ValueError, match="the coarse grid's drag along x-z5.29 is not positive"):
        rans.two_grid("body.stl", "x-z5.29", 0.1352, tmp_path / "2")


@pytest.mark.slow
def test_t24_the_real_openfoam_meshes_the_unioned_glider_at_toy_size_and_its_force_history_is_read(tmp_path, monkeypatch):
    """cafe.cfd.external on the stage's own STL of the default Seaglider, level offset -2, 30 iterations: the plumbing end to end (the numbers are not
    converged and are not checked): a force and the mesh's failed checks come back, and `drag_history` reads the real postProcessing of the case."""
    monkeypatch.setattr(cfd, "NPROC", 2)
    a = pw.assumptions()
    veh = pw.glider_vehicle(pw.glider.load_platform("seaglider"), a, "seaglider", 500.0)
    assert rans.write_stl(veh, tmp_path / "g.stl") == pytest.approx(1.8, rel=0.01)
    label = "x-z5.29"
    r = cfd.external(str(tmp_path / "g.stl"), tmp_path / "case", "water", 0.1352, (label,), level_offset=-2, iters=30, log=lambda *x: None)
    assert r["mesh"]["cells"] > 1000 and r["mesh"]["failed_checks"] >= 0 and np.isfinite(r["dirs"][label]["force"]).all()
    cfd._shrink(tmp_path / "case")
    mean, std = rans.drag_history(tmp_path / "case", label)
    assert math.isfinite(mean) and std >= 0.0


# ---------------------------------------------------------------------------------------------------- the report

def test_t25_the_report_shows_a_body_rans_row_beside_the_les_rows_of_its_window_and_its_traceability_holds(tmp_path, monkeypatch):
    orig = pm_run.stage3_rows

    def with_rans(ids, wins):
        rows = orig(ids, wins)
        first = rows["glider_eq"][0]
        rows["glider_eq"].append(dict(first, part="body_rans", ok=True, cd=0.373, cd_spread=0.03, cd_hangar=0.301, cl=None, cl_hangar=None,
                                      label=rans.LABEL, checks=[pm_run.check_row("rans_gci", 0.085, 0.1, True),
                                                                pm_run.check_row("rans_mesh_checks", 0.0, 0.0, True)]))
        return rows
    monkeypatch.setattr(pm_run, "stage3_rows", with_rans)
    run = tmp_path / "run"
    m, plan = pm_run.make_run(run)
    report.write(run, m, plan)
    rep = load(run)
    mine = [w for w in rep["stage3"]["vehicles"]["glider_eq"] if w["label"].endswith("body_rans")]
    assert len(mine) == 1 and mine[0]["label"] == "W1 body_rans" and mine[0]["coefficients"]["cd"]["value"] == 0.373 and "cl" not in mine[0]["coefficients"]
    assert [c["name"] for c in mine[0]["checks"]] == ["rans_gci", "rans_mesh_checks"] and report.check_traceability(rep) == []
    assert "W1 body_rans" in plain((run / "report" / "index.html").read_text())
