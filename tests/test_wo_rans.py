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


def fake_two_grid(stl, label, speed, wd, levels=rans.LEVELS, log=print):
    """Stands in for rans.two_grid (OpenFOAM): checks that the stage handed it a real STL and returns the shape two_grid returns."""
    assert pathlib.Path(stl).stat().st_size > 1000 and cfd.dvec(label) is not None
    RS["calls"].append(dict(stl=stl, label=label, speed=speed, levels=dict(levels)))
    return dict(rho=1025.0, speed=speed, label=label, cells=RS["cells"], coarse_cells=RS["coarse_cells"], failed_checks=RS["failed"],
                coarse_failed_checks=RS["coarse_failed"], drag=RS["drag"], drag_coarse=RS["drag_coarse"], drag_std=RS["std"], gci=RS["gci"],
                refinement_ratio=0.0, iterations=600, seconds=12.5, levels=dict(levels), iterations_cap=rans.ITERS)


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
    monkeypatch.setattr(pw, "profile_rans_s", lambda ctx: {"quick": 100.0, "overnight": 1e6})                 # (the fake plans have no mission to plan with)
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
    assert all(c["ok"] and c["note"] for c in r["checks"]) and r["timing"]["rans_s"] == 12.5 and "model-form" in r["checks"][0]["note"]
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
    def boom(stl, label, speed, wd, levels=None, log=print):
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
           "after the FEA hold and the RANS cases queued before it; it would fit --budget overnight (16667 min of stage 3 in that plan)")
    assert not r["ok"] and r["error"] == why and r["reasons"] == [why] and r["cd"] is None and RS["spawned"] == [] and r["label"] == rans.LABEL
    assert r["resolution"]["left_s"] == 1000.0 and r["resolution"]["estimated_s"] == 867.0 and L.checks["every_window_attempted"][0]
    # exactly margin x estimate fits
    assert pw._rans_gate(pw.assumptions(), rans_ctx(no_wall_receipt), 1083.75, 0.0, "glider") == (True, "", 1083.75)
    assert not pw._rans_gate(pw.assumptions(), rans_ctx(no_wall_receipt), 1083.7, 0.0, "glider")[0]
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


def slow_boat(monkeypatch, stw=0.58986, lee=-7.86, heel=4.21):
    """The USV's polar stood in at the first demo window's state (usv_rans.md): through-water speed, leeway and heel."""
    monkeypatch.setattr(pw.usv, "through_water", lambda P, wind, cur, heading: dict(
        stw=np.float64(stw), track_to=np.float64(70.0), leeway_deg=np.float64(lee), heel_deg=np.float64(heel), kd=np.float64(1.0)))


def hull_rans(rows):
    return [r for r in rows if r["part"] == "hull_rans"]


def test_t10_the_rans_cases_are_priced_in_queue_order_a_refused_glider_is_followed_by_the_usv_that_fits_and_the_free_surface_case_goes_last(
        no_wall_receipt, rans_env, monkeypatch):
    """Two gliders and a USV on a share of one glider case plus the USV's 570 s: glider 1 runs, glider 2 is refused with the gate sentence, the USV runs
    (its price is what is left), then the free-surface case is refused. Before: the free-surface case was priced first and the USV had no case."""
    monkeypatch.setenv("CAFE_NPROC", "6")
    slow_boat(monkeypatch)
    order, real = [], pw._spawn
    monkeypatch.setattr(pw, "_spawn", lambda cmd, **kw: (order.append("rans" if "cafe.pm.stage3.rans" in cmd else "fs"), real(cmd, **kw))[1])
    ctx = fake_ctx(no_wall_receipt, vehicles=[VEHICLES[0], VEHICLES[1], VEHICLES[2]], classes=dict(g="glider", g2="glider", u="usv"), rate=2000.0)
    a = pw.assumptions()
    one, usv_need = a["glider.rans.est_s"] * a["glider.rans.margin"], a["usv.rans.est_s"] * a["usv.rans.margin"]
    ctx.plan.update(shares=dict(stage3=1.0), budget_s=one + usv_need + 60.0)
    ctx.plan["les"]["windows"] = {k: dict(OUT) for k in ("g/body", "g2/body", "u/hull", "u/wing")}
    rows = pw.run(ctx, {"g": [WIN], "g2": [WIN], "u": [WIN]}, FakeL())
    assert order == ["rans", "rans"] and [c["levels"] for c in RS["calls"]] == [rans.LEVELS, rans.HULL_LEVELS]
    assert body_rans(rows["g"])[0]["ok"] and not body_rans(rows["g2"])[0]["ok"] and "RANS window not run" in body_rans(rows["g2"])[0]["error"]
    assert hull_rans(rows["u"])[0]["ok"] and rows["u"][-1]["part"] == "hull_fs" and not rows["u"][-1]["ok"] and "free-surface" in rows["u"][-1]["error"]
    s = budget.stage3_plan(ctx.plan, ctx.classes, a)
    assert s["rans"]["fit"] == 2 and s["rans"]["fitted"] == ["g", "u"] and s["fs"]["fit"] == 0


def test_t11_a_usv_gets_a_hull_rans_row_a_uas_and_a_gpu_glider_get_none_and_a_fast_boat_is_refused_by_the_validity_gate(no_wall_receipt, rans_env, monkeypatch):
    slow_boat(monkeypatch)
    ctx = fake_ctx(no_wall_receipt, vehicles=[VEHICLES[0], VEHICLES[2], VEHICLES[3]], classes=dict(g="glider", u="usv", q="uas"), rate=2000.0)
    ctx.plan.update(shares=dict(stage3=1.0), budget_s=1e6)
    ctx.plan["les"]["windows"] = {k: dict(OUT) for k in ("g/body", "u/hull", "u/wing", "q/body")}
    rows = pw.run(ctx, {v: [WIN] for v in ("g", "u", "q")}, FakeL())
    assert [v for v, rs in rows.items() if body_rans(rs)] == ["g"] and [v for v, rs in rows.items() if hull_rans(rs)] == ["u"] and len(RS["calls"]) == 2
    gpu = rans_ctx(no_wall_receipt / "gpu")
    gpu.plan["les"]["cpu_fallback"] = False
    assert body_rans(pw.run(gpu, {"g": [WIN]}, FakeL())["g"]) == [] and len(RS["calls"]) == 2


MISSION = dict(window=dict(start="2023-03-01T12:00:00Z", end="2023-03-07T12:00:00Z"))
CL2 = dict(glider_eq="glider", glider_2n="glider", usv="usv", uas="uas")


def test_t12_the_plan_prices_the_fea_then_the_rans_cases_then_the_free_surface_cases_and_the_shares_still_sum_as_before(monkeypatch):
    monkeypatch.setenv("CAFE_NPROC", "6")
    a, B = budget.stage3_assumptions(), budget.BUDGET_S["overnight"]
    p = budget.plan("overnight", 0, MISSION, thr={}, vehicle_classes=CL2)
    s = budget.stage3_plan(p, CL2, a)
    need, usv_need, hold = a["glider.rans.est_s"] * a["glider.rans.margin"], a["usv.rans.est_s"] * a["usv.rans.margin"], p["les"]["fea_hold_s"]
    assert s["rans"]["cases"] == 3 and s["rans"]["vehicles"] == ["glider_eq", "glider_2n", "usv"] and s["rans"]["fit"] == 3
    assert s["rans"]["need_s"] == dict(glider_eq=need, glider_2n=need, usv=usv_need) and s["rans"]["held_s"] == pytest.approx(2 * need + usv_need)
    assert hold == 2 * a["fea_min_s"] and s["fs"]["fit"] == 0                                    # the free-surface case no longer fits beside the three
    used = s["fs"]["fit"] * s["fs"]["need_s"] + hold + s["rans"]["held_s"]
    assert used <= p["shares"]["stage3"] * B + 1e-6 and p["shares"]["stage3"] * B == pytest.approx(used)               # the share is what the three claim
    assert sum(p["shares"].values()) == pytest.approx(sum(budget.SHARE.values())) and p["shares"]["stage1"] >= budget.SHARE["stage1"] - 1e-12
    assert s["rans"]["share_s"] == pytest.approx(p["shares"]["stage3"] * B - hold)                                       # priced on what the FEAs leave
    # a share that holds the first glider's case and the USV's but not the second glider's: the USV's case still claims its seconds
    left = B * budget.SHARE["stage3"] - hold
    # 1.5 glider cases in what is left once the USV's is set aside
    n = (left - usv_need) / 1.5
    monkeypatch.setattr(budget, "stage3_assumptions", lambda: dict(a, **{"glider.rans.est_s": n / 1.25}))
    q = budget.plan("overnight", 0, MISSION, thr={}, vehicle_classes=CL2)
    t = budget.stage3_plan(q, CL2, dict(a, **{"glider.rans.est_s": n / 1.25}))
    assert t["rans"]["fitted"] == ["glider_eq", "usv"] and t["rans"]["cases"] == 3
    assert sum(q["shares"].values()) == pytest.approx(sum(budget.SHARE.values()))
    assert q["shares"]["stage3"] * B == pytest.approx(t["fs"]["fit"] * t["fs"]["need_s"] + hold + n + usv_need)


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
        want = budget.rans_plan(CL2, p["les"]["windows"], b, budget.SHARE["stage3"] * B - p["les"]["fea_hold_s"])
        total = sum(p["shares"].values())
        if (s["rans"]["fitted"] != want["fitted"] or total != pytest.approx(sum(budget.SHARE.values()))
                or p["shares"]["stage1"] < budget.SHARE["stage1"] - 1e-12):
            refused.append(b["glider.rans.est_s"])
        assert s["rans"]["held_s"] + fs_s + p["les"]["fea_hold_s"] <= p["shares"]["stage3"] * B + 1e-6
    assert not refused


def test_t14_no_rans_case_is_planned_on_a_gpu_or_when_the_les_window_runs_or_for_a_uas(monkeypatch):
    monkeypatch.setenv("CAFE_NPROC", "6")
    a = budget.stage3_assumptions()
    gpu = budget.plan("overnight", 1, MISSION, thr={}, vehicle_classes=CL2)
    assert budget.stage3_plan(gpu, CL2, a)["rans"] is None and budget.rans_plan(CL2, {}, a, None) is None
    runs = {f"{v}/{part}": dict(runs=True) for v, part in (("glider_eq", "body"), ("glider_2n", "body"), ("usv", "hull"))}
    assert budget.rans_plan(CL2, runs, a, None) is None and budget.rans_vehicles(CL2, runs, True) == []
    out = {"glider_eq/body": dict(runs=False), "glider_2n/body": dict(runs=True), "usv/hull": dict(runs=False), "uas/body": dict(runs=False)}
    assert budget.rans_vehicles(CL2, out, True) == ["glider_eq", "usv"] and budget.rans_vehicles(CL2, out, False) == []
    plan = budget.rans_plan(CL2, out, a, None)
    need, usv_need = plan["need_s"]["glider_eq"], plan["need_s"]["usv"]
    assert plan["fit"] == plan["cases"] == 2 and plan["share_s"] is None and plan["held_s"] == need + usv_need
    assert budget.rans_plan(CL2, out, a, -5.0)["fit"] == 0
    assert budget.rans_plan(CL2, out, a, need + usv_need - 1e-7)["fit"] == 2                                         # a microsecond of rounding is allowed
    assert budget.rans_plan(CL2, out, a, need + usv_need - 1e-3)["fitted"] == ["glider_eq"]


def test_t15_the_plan_label_and_notes_say_the_refit_holds_only_where_the_case_passes_when_one_fits_and_keep_the_old_text_when_none_does(monkeypatch):
    monkeypatch.setenv("CAFE_NPROC", "6")
    a = budget.stage3_assumptions()
    p = budget.plan("overnight", 0, MISSION, thr={}, vehicle_classes=CL2)
    assert budget.stage3_plan(p, CL2, a)["rans"]["fit"] == 3
    both = budget.RANS_REFIT + budget.RANS_USV
    assert p["les"]["label"].startswith("CPU fallback") and p["les"]["label"].endswith("sub-grid stays uncalibrated; " + both)
    assert budget.RANS_REFIT == "the drag refit of a glider or USV comes only from its CPU RANS case, where it fits and passes its checks"       # a promise
    assert budget.RANS_USV == " (the USV's case is its bare hull: it scales the hull's viscous term at the window's speed)"
    assert any(n.endswith("went to stage 1; the sub-grid layer stays uncalibrated; " + both) for n in p["notes"])
    assert budget.stage3_plan(p, CL2, a)["les"]["note"] == "no LES coefficients exist on this machine; sub-grid stays uncalibrated; " + both
    g = dict(glider_eq="glider")                                                                                   # no USV: no USV clause
    pg = budget.plan("overnight", 0, MISSION, thr={}, vehicle_classes=g)
    assert pg["les"]["label"].endswith("sub-grid stays uncalibrated; " + budget.RANS_REFIT) and budget.stage3_plan(pg, g,
    a)["les"]["note"].endswith(budget.RANS_REFIT)
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
        return dict(fluid=fluid, rho=1025.0, nu=1.19e-6, speed=speed, L=1.8, level=6 + level_offset, mesh=dict(cells={0: 316_022, 1: 1_283_595, 2:
        5_000_000}[level_offset],
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


def test_t26_hull_and_wing_that_do_not_union_into_a_closed_solid_are_a_row_that_says_so(no_wall_receipt, rans_env, monkeypatch):
    import trimesh
    monkeypatch.setattr(trimesh.boolean, "union", lambda meshes, engine=None: trimesh.Trimesh(vertices=[[0, 0, 0], [1, 0, 0], [0, 1, 0]], faces=[[0, 1, 2]]))
    r = body_rans(pw.run(rans_ctx(no_wall_receipt), {"g": [WIN]}, FakeL())["g"])[0]
    assert not r["ok"] and r["error"] == "RANS window failed: the hull and wing do not union into a closed solid" and RS["calls"] == []


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


# ---- the skeptic pass

def test_t27_the_rans_child_is_killed_at_its_own_priced_seconds_not_at_the_stage_deadline(no_wall_receipt, rans_env):
    """Before: the watchdog was the whole stage deadline (about 5000 s here), so a case that overran its estimate took the free-surface cases' seconds."""
    pw.run(rans_ctx(no_wall_receipt, share=5000.0), {"g": [WIN]}, FakeL())
    one = pw.assumptions()["glider.rans.est_s"] * pw.assumptions()["glider.rans.margin"]
    (spawned,) = RS["spawned"]
    assert 1000.0 < float(spawned["cmd"][-1]) <= one and spawned["timeout"] == pytest.approx(float(spawned["cmd"][-1]) + pw.FS_GRACE_S)


def test_t28_the_rans_advice_is_priced_on_the_rans_seconds_and_the_free_surface_advice_leaves_them_out(monkeypatch):
    """Before: `profile_stage3_s` held the RANS seconds beside the free-surface ones, so with two RANS cases queued the RANS advice named overnight (whose
    stage 3 holds 2 RANS cases and a free-surface one) for a third."""
    from types import SimpleNamespace
    from cafe.pm import config, stage1
    monkeypatch.setenv("CAFE_NPROC", "6")
    m = config.load_mission("missions/tepex_c_demo.yaml")
    plan = dict(gpus=0, workers=6, mem_gb=None, env_gb=None, les={}, shares=dict(stage3=0.1), budget_s=1000.0)
    ctx = SimpleNamespace(mission=m, classes=stage1._classes(m), plan=plan)
    a = budget.stage3_assumptions()
    one = a["glider.rans.est_s"] * a["glider.rans.margin"]
    r, f = pw.profile_rans_s(ctx), pw.profile_stage3_s(ctx)
    usv_need = a["usv.rans.est_s"] * a["usv.rans.margin"]
    assert r["quick"] == 0.0 and r["4h"] == pytest.approx(2 * one + usv_need) and r["overnight"] == pytest.approx(2 * one + usv_need)
    ov = budget.stage3_plan(budget.plan("overnight", 0, m, vehicle_classes=ctx.classes, workers=6), ctx.classes, a)["fs"]
    assert f["quick"] == 0.0 and f["4h"] == 0.0 and f["overnight"] == pytest.approx(ov["fit"] * ov["need_s"], abs=1e-3)      # the free-surface cases' alone
    why = pw._rans_gate(a, ctx, 0.0, 2 * one, "glider")[1]
    assert why.endswith("no --budget profile's plan holds it (the largest plan gives 46 min of stage 3)")
    assert pw._rans_gate(a, ctx, 0.0, 0.0, "glider")[1].endswith("it would fit --budget 4h (46 min of stage 3 in that plan)")


def test_t29_the_free_surface_advice_is_not_charged_the_rans_cases_queued_before_it(no_wall_receipt, rans_env, monkeypatch):
    seen, gate = [], pw._fs_gate
    monkeypatch.setattr(pw, "_fs_gate", lambda est, a, ctx, left, queued: (seen.append(queued), gate(est, a, ctx, left, queued))[1])
    ctx = fake_ctx(no_wall_receipt, vehicles=[VEHICLES[0], VEHICLES[2]], classes=dict(g="glider", u="usv"), rate=2000.0)
    a = pw.assumptions()
    fs_need = budget.fs_plan(ctx.classes, 1, a, None)["need_s"]
    ctx.plan.update(shares=dict(stage3=1.0), budget_s=fs_need + a["glider.rans.est_s"] * a["glider.rans.margin"] + 60.0)
    ctx.plan["les"]["windows"] = {k: dict(OUT) for k in ("g/body", "u/hull", "u/wing")}
    rows = pw.run(ctx, {"g": [WIN], "u": [WIN]}, FakeL())
    # both RANS cases ran, not in the FS queue
    assert body_rans(rows["g"])[0]["ok"] and hull_rans(rows["u"])[0]["ok"] and len(RS["calls"]) == 2 and seen == [0.0]


@pytest.mark.parametrize("exc", [ImportError("no manifold backend"), AssertionError("area"), TypeError("odd"), IndexError("empty")])
def test_t30_any_error_in_preparing_the_rans_child_is_a_row_not_a_lost_stage(no_wall_receipt, rans_env, monkeypatch, exc):
    """Before: only OSError, ValueError, KeyError, RuntimeError and TypeError were caught; the rest came out of the future and lost the whole stage 3."""
    def broken(*a, **k):
        raise exc
    monkeypatch.setattr(pw.rans, "write_stl", broken)
    r = body_rans(pw.run(rans_ctx(no_wall_receipt), {"g": [WIN]}, FakeL())["g"])[0]
    assert not r["ok"] and r["error"] == f"RANS window failed: {exc}" and r["reasons"] == [r["error"]] and RS["calls"] == []


def test_t31_a_passing_rans_or_free_surface_row_is_not_a_passing_les_window_in_the_subgrid_note(tmp_path):
    for part in ("body_rans", "hull_fs"):
        L = FakeL()
        assert pw.recalibrate_subgrid(fake_ctx(tmp_path), {"g": [ts._row_ok(True, part=part)]}, L) is None
        assert L.notes == ["sub-grid layer uncalibrated: no LES window passed its self-checks; stage3/subgrid_calibration.json was not written"]
        assert L.checks["subgrid_calibration_written_only_from_passed_windows"][0]
    L = FakeL()
    assert pw.recalibrate_subgrid(fake_ctx(tmp_path), {"g": [ts._row_ok(True), ts._row_ok(True, part="body_rans")]}, L) is None
    assert L.notes[0].startswith("sub-grid layer uncalibrated: 1 window(s) passed but none carries a resolved inflow-turbulence series")


# ---------------------------------------------------------------------------------------------------- the USV's bare hull (`hull_rans`)

def usv_ctx(tmp):
    return fake_ctx(tmp, vehicles=[VEHICLES[2]], classes=dict(u="usv"), rate=2000.0)


def usv_args():
    a = pw.assumptions()
    P = pw.usv.load_platform("saildrone_explorer")
    return a, P, pw.usv_vehicle(P, a, "saildrone_explorer", "hull_rans")


def test_t32_the_bare_hull_vehicle_is_the_ellipsoid_alone_and_its_stl_is_one_closed_solid(tmp_path):
    """Before: `hull_rans` fell to the wing branch of `usv_vehicle` (a plate)."""
    import trimesh
    a, P, veh = usv_args()
    assert len(veh.shapes) == 1 and veh.shapes[0]["type"] == "ellipsoid" and tuple(veh.shapes[0]["radii"]) == (3.25, 0.6, 0.45)
    assert veh.ref_area == pytest.approx(math.pi * 0.6 * 0.45, rel=1e-12) and veh.fluid == "water" and veh.extra["part"] == "hull_rans"
    assert rans.write_stl(veh, tmp_path / "h.stl") == pytest.approx(6.5)
    m = trimesh.load(tmp_path / "h.stl")
    assert m.is_watertight and len(m.faces) == 1280 and m.extents.tolist() == pytest.approx([6.5, 1.2, 0.9])
    assert len(pw.usv_vehicle(P, a, "saildrone_explorer", "hull").shapes) == 2                                         # the LES hull keeps its keel


def test_t33_the_bare_hull_case_is_the_viscous_term_at_the_solvers_reynolds_number_and_its_share_is_taken_at_the_windows_leeway_and_heel(
        no_wall_receipt, monkeypatch):
    slow_boat(monkeypatch)
    a, P, veh = usv_args()
    ctx = usv_ctx(no_wall_receipt)
    c = pw.usv_case(ctx, WIN, P, veh, a, 70.0, "hull_rans")
    assert c["cd_h"] == pytest.approx(0.08891, abs=1e-4) and c["residuary_share"] == pytest.approx(0.00095, abs=1e-4)
    # the share at the window's own leeway (7.86 deg) and heel (4.21 deg): the keel's induced drag is in the whole, so it is below the 0.30 of zero leeway
    rho, st, heel = P["rho_water"], 0.58986, math.radians(4.21)
    r_plat = (0.5 * rho * st ** 2 * P["wetted_area_m2"] * float(pw.usv.cf_ittc57(st * P["lwl_m"] / P["nu_water"])) * (1.0 + P["form_factor_k"])
              * (1.0 + P["heel_resist_c"] * heel ** 2))
    r_tot = float(np.asarray(pw.usv._forces(P, np.float64(st), np.float64(math.radians(7.86)), np.float64(heel), np.float64(1.0),
                                            *[np.float64(0.0)] * 5)["d"]))
    assert c["drag_share"] == pytest.approx(r_plat / r_tot, rel=1e-9) and c["drag_share"] == pytest.approx(0.2296, abs=2e-4)
    for text in ("RANS solver's Reynolds number (3.22e+06; the window's is 4.46e+06)", "no keel, rudder, appendage or residuary term",
                 "the polar's, before the stage-1 speed bias", "leeway -7.9 deg and heel 4.2 deg not simulated", "the rudder's induced drag left out"):
        assert text in c["src"]
    assert "2.5 x" in c["wetted_area_note"] and "fully submerged ellipsoid of draft 0.45 m with no keel" in c["wetted_area_note"]
    monkeypatch.setattr(pw, "_keel_drag", lambda P, stw: 1e6)                                                          # no keel term in the reference
    assert pw.usv_case(ctx, WIN, P, veh, a, 70.0, "hull_rans")["cd_h"] == c["cd_h"]
    slow_boat(monkeypatch, lee=0.0, heel=0.0)
    # zero leeway and heel: the keel's profile drag only
    assert pw.usv_case(ctx, WIN, P, veh, a, 70.0, "hull_rans")["drag_share"] == pytest.approx(0.2999, abs=1e-3)


def test_t34_a_usv_has_a_rans_case_when_its_les_hull_is_planned_out_whatever_its_wing_does():
    cl = dict(usv="usv")
    assert budget.rans_vehicles(cl, {"usv/hull": dict(runs=False), "usv/wing": dict(runs=True)}, True) == ["usv"]
    assert budget.rans_vehicles(cl, {"usv/hull": dict(runs=True), "usv/wing": dict(runs=False)}, True) == []
    assert budget.RANS_PARTS == {"glider": "body_rans", "usv": "hull_rans"}


def test_t35_the_cases_are_priced_per_class_each_claiming_its_seconds_in_queue_order():
    a = budget.stage3_assumptions()
    out = {f"{v}/{p}": dict(runs=False) for v, p in (("glider_eq", "body"), ("glider_2n", "body"), ("usv", "hull"))}
    g, u = 1083.75, 570.0
    r = budget.rans_plan(CL2, out, a, None)
    assert r["fit"] == 3 and r["need_s"] == dict(glider_eq=g, glider_2n=g, usv=u) and r["held_s"] == 2 * g + u
    r = budget.rans_plan(CL2, out, a, 2 * g + u - 1.0)
    assert r["fitted"] == ["glider_eq", "glider_2n"] and r["held_s"] == 2 * g
    r = budget.rans_plan(CL2, out, a, g + u)
    # glider_2n is refused, the USV still fits
    assert r["fitted"] == ["glider_eq", "usv"] and r["held_s"] == g + u
    assert budget.rans_plan(CL2, out, a, -5.0)["fit"] == 0


def test_t36_plan_and_stage3_plan_agree_on_the_queue_order_fea_rans_free_surface(monkeypatch):
    a, B = budget.stage3_assumptions(), budget.BUDGET_S
    for cores in ("2", "6"):
        monkeypatch.setenv("CAFE_NPROC", cores)
        for name in ("4h", "overnight"):
            p = budget.plan(name, 0, MISSION, thr={}, vehicle_classes=CL2)
            s = budget.stage3_plan(p, CL2, a)
            hold = p["les"]["fea_hold_s"]
            assert s["rans"]["share_s"] == pytest.approx(p["shares"]["stage3"] * B[name] - hold)
            used = hold + s["rans"]["held_s"] + (0.0 if s["fs"] is None else s["fs"]["fit"] * s["fs"]["need_s"])
            assert p["shares"]["stage3"] * B[name] == pytest.approx(used)
            want = budget.rans_plan(CL2, p["les"]["windows"], a, budget.SHARE["stage3"] * B[name] - hold)
            assert s["rans"]["fitted"] == want["fitted"] and s["rans"]["held_s"] == want["held_s"]
    monkeypatch.setenv("CAFE_NPROC", "6")
    ov = budget.stage3_plan(budget.plan("overnight", 0, MISSION, thr={}, vehicle_classes=CL2), CL2, a)
    # the free-surface case no longer fits there
    assert ov["fs"]["fit"] == 0 and ov["rans"]["fit"] == 3
    one = dict(g1="glider", u1="usv")
    p1 = budget.plan("overnight", 0, MISSION, thr={}, vehicle_classes=one)
    # beside one glider and the USV it still does
    assert budget.stage3_plan(p1, one, a)["fs"]["fit"] == 1


def test_t37_the_stage_runs_the_usv_case_on_the_bare_hull_along_x_at_the_through_water_speed(no_wall_receipt, rans_env, monkeypatch):
    """Before: `_rans_submit` took the glider path for every RANS class and a USV was an error row."""
    slow_boat(monkeypatch)
    ctx = usv_ctx(no_wall_receipt)
    ctx.plan["les"]["windows"] = {k: dict(OUT) for k in ("u/hull", "u/wing")}
    ctx.plan.update(shares=dict(stage3=1.0), budget_s=1e5)
    L = FakeL()
    rows = pw.run(ctx, {"u": [WIN]}, L)["u"]
    (call,), (spawned,) = RS["calls"], RS["spawned"]
    r = hull_rans(rows)[0]
    assert call["label"] == "+x" and call["levels"] == rans.HULL_LEVELS and call["speed"] == pytest.approx(np.linalg.norm(r["velocity_body_ms"]), abs=1e-9)
    assert call["speed"] == pytest.approx(0.58986, abs=1e-9) and float(spawned["cmd"][-1]) <= 570.0
    assert r["label"] == rans.HULL_LABEL and r["cl_hangar"] is None and r["ok"] and 0.22 < r["drag_share"] < 0.24 and r["residuary_share"] < 0.01
    assert r["fea"]["reason"].startswith("no structural model: the platform yaml has no hull or wing structure")
    assert len(r["checks"]) == 4 and r["resolution"]["level_offsets"] == rans.HULL_LEVELS and r["part"] == "hull_rans"
    assert L.checks["every_window_attempted"][0] and L.checks["no_row_claims_ok_with_a_failing_check"][0]


def test_t38_a_window_whose_wave_making_the_case_would_leave_out_is_refused_and_starts_no_child(no_wall_receipt, rans_env, monkeypatch):
    def go(stw):
        slow_boat(monkeypatch, stw=stw)
        ctx = usv_ctx(no_wall_receipt)
        ctx.plan["les"]["windows"] = {k: dict(OUT) for k in ("u/hull", "u/wing")}
        ctx.plan.update(shares=dict(stage3=1.0), budget_s=1e5)
        return hull_rans(pw.run(ctx, {"u": [WIN]}, FakeL())["u"])[0]
    r = go(1.2)
    assert not r["ok"] and r["error"].startswith("RANS window not run: the model's wave-making (residuary) term is ") and r["reasons"] == [r["error"]]
    assert "above the 1% a case with no free surface may leave out (stage3.usv.rans.residuary_share_max)" in r["error"] and RS["calls"] == []
    assert go(1.0)["ok"] and len(RS["calls"]) == 1


def test_t39_two_grid_takes_its_levels_and_the_child_passes_the_jobs(tmp_path, monkeypatch):
    """Before: `two_grid` had no `levels` argument (TypeError) and the job carried none."""
    calls = []
    monkeypatch.setattr(cfd, "external", fake_external(calls, {1: 0.2582, 2: 0.2467}, {1: 0, 2: 0}))
    r = rans.two_grid("h.stl", "+x", 0.59, tmp_path, levels=rans.HULL_LEVELS)
    assert [(c["case"].name, c["level_offset"]) for c in calls] == [("coarse", 1), ("fine", 2)] and r["levels"] == {"coarse": 1, "fine": 2}
    seen = []
    job, out = tmp_path / "job.json", tmp_path / "out.json"
    job.write_text(json.dumps(dict(stl="h.stl", label="+x", speed=0.59, levels=rans.HULL_LEVELS)))
    rans.run_child(str(job), str(out), runner=lambda stl, label, speed, wd, levels: (seen.append(levels), dict(drag=1.0))[1])
    assert seen == [rans.HULL_LEVELS] and rans.HULL_LEVELS == {"coarse": 1, "fine": 2}


# ---------------------------------------------------------------------------------------------------- the refit of the USV's bare hull

def hull_row(**kw):
    """The first fin1 window's case: ratio 0.8627 on the hull's viscous term, which is 0.3 of the model's whole drag (a round share for exact checks)."""
    return dict(tp.stage3_row(cd=0.8627, hangar=1.0, spread=0.0509), part="hull_rans", cl=None, cl_spread=None, cl_hangar=None, drag_share=0.3,
    added_resistance=0.8627 - 1.0, **kw)


def test_t40_a_row_that_measured_the_hull_alone_scales_the_fit_after_the_pooling_so_the_floors_stay_the_hulls(tmp_path):
    """Before: no scoping (the multiplier was 0.8627 on the whole boat) and `hull_rans` was no part the refit knew. The sigma floors (between-window
    0.10 and discretisation 0.05 of the mean) are those of the measured ratio, not of the scoped whole: scoping the input would have given 0.108."""
    un = refit.refit([hull_row()])["drag"]
    out = tp.refit_run(tmp_path, {"usv": [hull_row(), dict(tp.stage3_row(cd=3.0), part="wing")]})[0]["usv"]
    d, s = out["drag"], 0.3
    assert d["mean"] == pytest.approx(1 + s * (0.8627 - 1), abs=1e-12) and d["change_vs_hangar"] == pytest.approx(s * (0.8627 - 1), abs=1e-12)
    for k in ("sigma", "sigma_statistical", "sigma_between", "sigma_discretisation", "tau"):
        assert d[k] == pytest.approx(s * un[k], abs=1e-12)
    assert d["sigma_statistical"] == pytest.approx(s * 0.0509, abs=1e-12) and un["sigma"] == pytest.approx(0.109, abs=2e-3) and d["sigma"] < 0.04
    assert out["added_resistance"]["mean"] == pytest.approx(s * (0.8627 - 1), abs=1e-12) and out["drag_share"] == s
    assert out["hull_ratio"] == pytest.approx(0.8627)
    plain_ratio = tp.refit_run(tmp_path / "2", {"usv": [dict(hull_row(), part="body_rans")]})[0]["usv"]                   # no scoping for a whole-boat row
    assert plain_ratio["drag"]["mean"] == pytest.approx(0.8627)


def test_t41_the_bare_hull_row_sets_the_usv_multiplier_and_the_box_keel_parts_do_not(tmp_path):
    rows = {"usv": [dict(tp.stage3_row(cd=1.3), part="hull"), dict(tp.stage3_row(cd=2.0), part="hull_fs"), hull_row()]}
    u = tp.refit_run(tmp_path, rows)[0]["usv"]
    assert u["used"] and u["part"] == "hull_rans" and u["drag"]["mean"] == pytest.approx(1 + 0.3 * (0.8627 - 1))
    assert u["reason"].startswith("bare-hull RANS (no keel, no free surface, no leeway or heel): cd / cd_hangar 0.863 on the hull's viscous term, which is 30%")
    assert "1 + 0.300 x (0.863 - 1)" in u["reason"] and u["reason"].endswith("Stage 1 applies this factor at each speed it sails")
    assert u["hull_not_used"]["reason"] == pipeline.BOX_KEEL == u["hull_fs_not_used"]["reason"]
    # a row without a usable share is no measurement
    for bad in (None, 0.0, 1.5, math.nan, "0.3"):
        row = dict(hull_row(), drag_share=bad)
        out = tp.refit_run(tmp_path / f"b{bad}", {"usv": [row]})[0]["usv"]
        assert out["used"] is False and out["reason"].startswith("no hull_rans window passed")
    gone = {k: v for k, v in hull_row().items() if k != "drag_share"}
    assert tp.refit_run(tmp_path / "gone", {"usv": [gone]})[0]["usv"]["used"] is False


@needs_data
def test_t42_stage_1b_reruns_stage_1_with_the_usvs_scaled_multiplier(tmp_path, monkeypatch, sens):
    ctx = tp.ctx_for(tmp_path / "r")
    tp.stage1_files(ctx)
    ctx.plan["refit_iterations"] = 2
    ctx.path("stage3", "windows.json").write_text(json.dumps({"usv": [hull_row()]}))
    tp.run_stage(pipeline.s_refit, ctx, "refit")
    seen, fake = [], tp.summaries(ctx, {"usv": "NO-GO"}, {"usv": "GO"})
    monkeypatch.setattr(pipeline, "_stage1", lambda c, L, name, scales=None, extra=None: (seen.append((scales, extra)), fake(c, L, name, scales, extra))[1])
    tp.run_stage(pipeline.s_stage1b, ctx, "stage1b")
    (scales, extra), = seen
    assert extra == dict(refit_iterations_performed=1) and list(scales) == ["usv"] and scales["usv"]["part"] == "hull_rans"
    assert scales["usv"]["drag"]["mean"] == pytest.approx(1 + 0.3 * (0.8627 - 1))


def test_t43_the_report_prints_the_usv_sentence_only_where_the_usvs_cfd_is_yes(tmp_path, monkeypatch):
    def run_with(usv_used, part="hull_rans"):
        orig = pm_run.stage3_rows

        def rows(ids, wins):
            r = orig(ids, wins)
            r["usv"] = [dict(w, part="hull_rans", ok=True, drag_share=0.3) for w in r["usv"][:1]] if usv_used else r["usv"]
            return r
        monkeypatch.setattr(pm_run, "stage3_rows", rows)
        run = tmp_path / ("a" if usv_used and part == "hull_rans" else "b" if not usv_used else "c")
        m, plan = pm_run.make_run(run)
        rf = json.loads((run / "refit" / "refit.json").read_text())
        rf["usv"] = dict(used=usv_used, part=part, drag=dict(mean=0.97, sigma=0.03, change_vs_hangar=-0.03), reason="bare-hull RANS: scoped")
        (run / "refit" / "refit.json").write_text(json.dumps(rf))
        report.write(run, m, plan)
        return load(run)
    yes, no, old = run_with(True), run_with(False), run_with(True, "hull_fs")
    assert report.CONTRIB_USV not in old["contribution"]["statements"]            # a refit through the box-keel free-surface part: the sentence would be false
    assert report.CONTRIB_USV in yes["contribution"]["statements"] and report.CONTRIB_USV not in no["contribution"]["statements"]
    assert report.CONTRIB_USV.startswith("The USV's CFD is its bare hull as an ellipsoid with no keel, no waves, no leeway and no heel: it scales the hull's")
    assert report.check_traceability(yes) == [] and report.check_traceability(no) == []
    assert report.check_rendered(yes, (tmp_path / "a" / "report" / "index.html").read_text()) == []


def test_t44_the_credibility_limitation_names_the_usvs_bare_hull():
    l15 = next(x for x in cr.LIMITATIONS if x["id"] == "L15")["text"]
    assert "a glider's hull and wing or a USV's bare hull with no keel or waves (which scales the hull's viscous term at the window's speed)" in l15


def test_t45_the_usv_assumptions_carry_value_unit_why_and_replacement_and_are_the_usvs(cred_run):
    got = cr.config.assumptions()
    for k, v in (("est_s", 456.0), ("margin", 1.25), ("residuary_share_max", 0.01)):
        e = got[f"stage3.usv.rans.{k}"]
        assert e["value"] == v and {"unit", "why", "replace_with"} <= set(e) and e["why"] and e["replace_with"]
        assert cr.config_scope("config/assumptions.yaml", f"stage3.usv.rans.{k}") == "usv"
    assert "usvr_4" in got["stage3.usv.rans.est_s"]["why"] and "2026-11-23" in got["stage3.usv.rans.est_s"]["why"]
    keys = {f"stage3.usv.rans.{k}" for k in ("est_s", "margin", "residuary_share_max")}
    assert keys <= tc.used_of(tc.only(cred_run, {"usv"}), "config/assumptions.yaml")
    assert keys.isdisjoint(tc.used_of(tc.only(cred_run, {"glider_eq"}), "config/assumptions.yaml"))


def test_t46_a_passing_free_surface_row_beside_a_used_bare_hull_refit_is_not_labelled_used_and_says_why(tmp_path, monkeypatch):
    """Before: any ok row of a used vehicle read "used in the refit", so a passing `hull_fs` row beside a used `hull_rans` refit would have."""
    orig = pm_run.stage3_rows

    def rows(ids, wins):
        r = orig(ids, wins)
        first = r["usv"][0]
        r["usv"] = [dict(first, part="hull_rans", ok=True, drag_share=0.3), dict(first, part="hull_fs", ok=True)]
        return r
    monkeypatch.setattr(pm_run, "stage3_rows", rows)
    run = tmp_path / "run"
    m, plan = pm_run.make_run(run)
    rf = json.loads((run / "refit" / "refit.json").read_text())
    rf["usv"] = dict(used=True, part="hull_rans", drag=dict(mean=0.97, sigma=0.03, change_vs_hangar=-0.03), reason="bare-hull RANS: scoped",
                     hull_fs_not_used=dict(reason=pipeline.BOX_KEEL))
    (run / "refit" / "refit.json").write_text(json.dumps(rf))
    report.write(run, m, plan)
    rep = load(run)
    by = {w["label"].split()[-1]: w for w in rep["stage3"]["vehicles"]["usv"]}
    assert by["hull_rans"]["used_in_refit"] is True and by["hull_fs"]["used_in_refit"] is False
    assert by["hull_fs"]["not_used_because"] == pipeline.BOX_KEEL and report.check_traceability(rep) == []
    assert report.check_rendered(rep, (run / "report" / "index.html").read_text()) == []
    page = plain((run / "report" / "index.html").read_text())
    assert "not used in the refit: " + pipeline.BOX_KEEL in page
