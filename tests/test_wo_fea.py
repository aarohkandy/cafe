"""Work order step 2: the pressure-hull FEA of a glider whose LES part is planned out runs from the sea pressure alone (stage3/pipeline_windows.py
`_sea_pressure_fea`), first in the one-worker queue, with its seconds held by the plan (budget.plan `les.fea_hold_s`), and the report prints its
utilisation beside the verdict (report.py `_hull_fea`)."""
import subprocess

import pytest

from cafe.pm import budget, report
from cafe.pm.stage3 import pipeline_windows as pw
from tests.fixtures import pm_run
from tests.test_report import load, plain
from tests import test_stage3 as ts
from tests.test_stage3 import VEHICLES, WIN, FakeL, cheap, fake_ctx, planned_ctx, untimed

clean_receipts, fresh_fs, no_wall_receipt = ts.clean_receipts, ts.fresh_fs, ts.no_wall_receipt                 # the fixtures of tests/test_stage3.py

OUT = {"g/body": dict(runs=False, skip_reason="not run: the physical lattice viscosity is out of reach", reachable=False)}
CANNED = dict(utilization=2.5, stress_utilization=0.6, buckling_utilization=2.5, knockdown=0.5, vm_p99=1.0, safety_factor=1.0, buckling_factor=0.8,
              buckling_lobes=2, buckling_follower_correction=1.1, elements=10, nodes=10, min_element_quality=0.7, hydrostatic_pa=5.0e6)


def out_ctx(tmp, share=2000.0, hold=1.0):
    """One glider whose LES part is planned out, a stage-3 share of `share` s and `hold` s of it held for the FEA (cheap() sets fea_min_s to 1 s)."""
    ctx = planned_ctx(tmp, dict(OUT), share)
    ctx.plan["les"]["fea_hold_s"] = hold
    return ctx


@pytest.fixture
def canned(monkeypatch):
    """The FEA with no ccx: records what the hull FEA was given and returns a fixed result."""
    seen = []

    def fake(vehicle, points, pressure, workdir=None, h=None, buckle=False):
        seen.append(dict(vehicle=vehicle, points=points, pressure=pressure, buckle=buckle))
        return dict(CANNED)
    monkeypatch.setattr(pw.W, "fea_window", fake)
    return seen


def spy(monkeypatch):
    """The order in which the children start ("fea", "fs"); call after cheap()."""
    order, real = [], pw._spawn

    def spawn(cmd, **kw):
        order.append("fea" if "--fea" in cmd else "fs")
        return real(cmd, **kw)
    monkeypatch.setattr(pw, "_spawn", spawn)
    return order


def test_t1_a_glider_whose_les_part_is_planned_out_gets_the_hull_fea_from_the_sea_pressure(no_wall_receipt, monkeypatch):
    """Before: the row's fea was the not-run reason "the window did not run" (stage 3 called the FEA only inside a LES window). A real FEA of the toy mesh."""
    cheap(monkeypatch)
    monkeypatch.setattr(pw.W, "run_window", lambda *a, **k: pytest.fail("a window the plan skipped was run"))
    r = pw.run(out_ctx(no_wall_receipt), {"g": [WIN]}, FakeL())["g"][0]
    assert r["fea"]["run"] and r["fea"]["utilization"] > 0 and r["fea"]["load"] == "sea pressure only" and r["fea"]["depth_m"] == 500.0
    assert r["fea"]["buckling_utilization"] > 0 and r["fea"]["stress_utilization"] > 0 and "seconds" not in r["fea"]
    assert not r["ok"] and r["error"] == OUT["g/body"]["skip_reason"] and r["cd"] is None                  # the LES row itself is as it was


def test_t2_the_depth_is_the_order_or_the_rating_whichever_is_shallower_and_the_load_is_the_sea_pressure_alone(no_wall_receipt, monkeypatch, canned):
    cheap(monkeypatch)
    ctx = out_ctx(no_wall_receipt)
    ctx.mission = dict(vehicles=[dict(VEHICLES[0], task=dict(dive_depth_m=1500.0))])                         # seaglider.yaml rating_m is 1000
    r = pw.run(ctx, {"g": [WIN]}, FakeL())["g"][0]
    assert len(canned) == 1 and canned[0]["buckle"] and canned[0]["vehicle"].depth == 1000.0 and r["fea"]["depth_m"] == 1000.0
    assert canned[0]["pressure"].shape == (1,) and not canned[0]["pressure"].any()                         # no wall pressure: fea_window adds rho g depth
    assert pw._glider_vehicle_for(ctx, "g", "seaglider", pw.assumptions(), clip=False)[1].depth == 1500.0   # an LES row keeps the order as written
    assert pw._glider_vehicle_for(ctx, "g", "seaglider", pw.assumptions(), clip=True)[1].depth == 1000.0
    ctx.mission = dict(vehicles=[dict(VEHICLES[0], task=dict(dive_depth_m=300.0))])
    assert pw._glider_vehicle_for(ctx, "g", "seaglider", pw.assumptions(), clip=True)[1].depth == 300.0


def test_t3_one_fea_serves_every_window_of_the_glider(no_wall_receipt, monkeypatch, canned):
    cheap(monkeypatch)
    order = spy(monkeypatch)
    rows = pw.run(out_ctx(no_wall_receipt), {"g": [WIN, dict(WIN, t=WIN["t"] + 3600.0)]}, FakeL())["g"]
    assert order == ["fea"] and len(canned) == 1
    assert rows[0]["fea"] == rows[1]["fea"] and rows[0]["fea"]["run"] and rows[0]["fea"] is not rows[1]["fea"]
    assert rows[0]["timing"]["fea_s"] == rows[1]["timing"]["fea_s"] > 0.0


def test_t4_the_fea_starts_before_the_free_surface_case_and_is_counted_against_its_queue(no_wall_receipt, monkeypatch, canned):
    cheap(monkeypatch)
    order, lefts, gate = spy(monkeypatch), [], pw._fs_gate
    monkeypatch.setattr(pw, "_fs_gate", lambda est, a, ctx, left, queued: (lefts.append((left, queued)), gate(est, a, ctx, left, queued))[1])
    ctx = fake_ctx(no_wall_receipt, vehicles=[VEHICLES[0], VEHICLES[2]], classes=dict(g="glider", u="usv"), rate=2000.0)
    need = budget.fs_plan(ctx.classes, 1, pw.assumptions(), None)["need_s"]
    ctx.plan.update(shares=dict(stage3=1.0), budget_s=need + 61.0)
    ctx.plan["les"].update(windows={"g/body": OUT["g/body"], "u/hull": dict(OUT["g/body"]), "u/wing": dict(OUT["g/body"])}, fea_hold_s=1.0)
    rows = pw.run(ctx, {"g": [WIN], "u": [WIN]}, FakeL())
    assert order == ["fea", "fs"] and rows["g"][0]["fea"]["run"]
    assert lefts == [(pytest.approx(need + 60.0), 1.0)]                                                    # the share left is the share less the FEA's second
    assert rows["u"][-1]["part"] == "hull_fs" and rows["u"][-1]["ok"] and rows["u"][-1]["cd"] is not None


def test_t4b_a_plan_that_held_less_than_the_least_fea_time_says_not_planned_and_starts_no_child(no_wall_receipt, monkeypatch, canned):
    cheap(monkeypatch)
    order = spy(monkeypatch)
    r = pw.run(out_ctx(no_wall_receipt, hold=0.5), {"g": [WIN]}, FakeL())["g"][0]
    assert order == [] and canned == []
    why = "not planned: the FEA reserve is 0.5 s of a 2000.0 s slice, below stage3.fea_min_s (1.0 s): use a larger --budget"
    assert r["fea"] == dict(run=False, reason=why)


def test_t4c_a_run_with_no_wall_clock_budget_runs_the_fea_and_a_stage_with_no_share_keeps_its_reason(no_wall_receipt, monkeypatch, canned):
    cheap(monkeypatch)
    ctx = fake_ctx(no_wall_receipt, vehicles=VEHICLES[:1], classes=dict(g="glider"), rate=2000.0)
    ctx.plan["les"]["windows"] = dict(OUT)
    assert pw.run(ctx, {"g": [WIN]}, FakeL())["g"][0]["fea"]["load"] == "sea pressure only"
    none = out_ctx(no_wall_receipt, share=0.0)
    none.plan["shares"] = dict(stage3=0.0)
    assert pw.run(none, {"g": [WIN]}, FakeL())["g"][0]["fea"] == dict(run=False, reason="the window did not run") and len(canned) == 1


def test_t5_a_failed_fea_child_is_a_row_that_says_so_and_the_stage_does_not_raise(no_wall_receipt, monkeypatch):
    cheap(monkeypatch)
    monkeypatch.setattr(pw, "_spawn", lambda cmd, **k: subprocess.CompletedProcess(cmd, 1, "", "boom: ccx died\n"))
    rows = pw.run(out_ctx(no_wall_receipt), {"g": [WIN]}, FakeL())["g"]
    assert rows[0]["fea"] == dict(run=False, reason="FEA failed: boom: ccx died")

    def no_ccx(cmd, **k):
        raise OSError("no ccx")
    monkeypatch.setattr(pw, "_spawn", no_ccx)
    assert pw.run(out_ctx(no_wall_receipt), {"g": [WIN]}, FakeL())["g"][0]["fea"] == dict(run=False, reason="FEA failed: no ccx")


def test_t6_guard_the_rows_that_are_not_sea_pressure_ones_are_as_they_were(no_wall_receipt, monkeypatch):
    """Passes before the change as well: a LES-loaded FEA carries no `load` word, and a USV row has no structural model."""
    cheap(monkeypatch)
    f = pw.run(planned_ctx(no_wall_receipt, {}, 2000.0), {"g": [WIN]}, FakeL())["g"][0]["fea"]
    assert f["run"] and "load" not in f and "depth_m" not in f
    cheap(monkeypatch)
    u = pw.run(fake_ctx(no_wall_receipt, budget=2e6), {"u": [WIN]}, FakeL())["u"]
    assert u[-1]["part"] == "hull_fs" and all(r["fea"]["reason"].startswith("no structural model") and "load" not in r["fea"] for r in u)


def test_t7_the_fea_seconds_are_in_timing_and_not_in_the_hashed_rows(no_wall_receipt, monkeypatch, canned):
    cheap(monkeypatch)
    rows = pw.run(out_ctx(no_wall_receipt), {"g": [WIN]}, FakeL())
    t = rows["g"][0]["timing"]
    assert t["fea_s"] > 0.0 and t["fea_seconds"] > 0.0 and "seconds" not in rows["g"][0]["fea"]
    assert "fea_seconds" not in str(untimed(rows)) and "fea_s'" not in str(untimed(rows))


def test_t8_the_report_prints_the_sea_pressure_utilisation_beside_the_verdict_of_a_glider_that_has_one(tmp_path, monkeypatch):
    orig = pm_run.stage3_rows

    def with_fea(ids, wins):
        rows = orig(ids, wins)
        rows["glider_eq"][0]["fea"] = dict(run=False, reason="the window did not run")
        rows["glider_eq"][1]["fea"] = dict(run=True, load="sea pressure only", depth_m=950.0, utilization=2.87, stress_utilization=0.58,
                                           buckling_utilization=2.87)
        rows["glider_2n"][0]["fea"] = dict(run=True, utilization=0.5, stress_utilization=0.3, buckling_utilization=0.5)      # a LES-loaded one: no word
        return rows
    monkeypatch.setattr(pm_run, "stage3_rows", with_fea)
    run = tmp_path / "run"
    m, plan = pm_run.make_run(run)
    report.write(run, m, plan)
    rep = load(run)
    f = rep["vehicles"]["glider_eq"]["hull_fea"]
    assert f["load"] == "sea pressure only" and [f[k]["value"] for k in ("depth_m", "utilization", "stress_utilization", "buckling_utilization")] == \
        [950.0, 2.87, 0.58, 2.87]
    for k in ("depth_m", "utilization", "stress_utilization", "buckling_utilization"):
        assert f[k]["source"] == f"stage3/windows.json glider_eq[1].fea.{k}" and f[k]["receipt"] and f[k]["ledger"] and f[k]["stage"] == "stage3"
    assert rep["vehicles"]["glider_2n"]["hull_fea"] is None and rep["vehicles"]["usv"]["hull_fea"] is None and rep["vehicles"]["uas"]["hull_fea"] is None
    text = plain((run / "report" / "index.html").read_text())
    assert text.count("Hull FEA (sea pressure only)") == 1
    assert ("Hull FEA (sea pressure only) at 950 m: utilisation 2.87 (stress 0.58, buckling 2.87); above 1 the hull yields or buckles.") in text
    assert report.check_traceability(rep) == []
    gone = tmp_path / "none"                                                                              # no stage-3 file: no line, no error
    m, plan = pm_run.make_run(gone, stage3=False, refit=False)
    report.write(gone, m, plan)
    assert load(gone)["vehicles"]["glider_eq"]["hull_fea"] is None and "Hull FEA" not in plain((gone / "report" / "index.html").read_text())


MISSION = dict(window=dict(start="2023-03-01T12:00:00Z", end="2023-03-07T12:00:00Z"))
CLASSES = dict(glider_eq="glider", usv="usv", uas="uas")


def test_t9_the_plan_holds_the_fea_seconds_ahead_of_the_free_surface_cases_and_the_run_and_the_plan_agree(monkeypatch):
    monkeypatch.setenv("CAFE_NPROC", "6")
    a = budget.stage3_assumptions()
    p = budget.plan("overnight", 0, MISSION, thr={}, vehicle_classes=CLASSES)
    s3 = budget.SHARE["stage3"] * budget.BUDGET_S["overnight"]
    fs0 = budget.fs_plan(CLASSES, p["les"]["windows_per_vehicle"], a, s3)
    assert not p["les"]["windows"]["glider_eq/body"]["runs"] and fs0["fit"] >= 1
    assert p["les"]["fea_hold_s"] == a["fea_min_s"] and budget.fea_planned_out(CLASSES, p["les"]["windows"]) == ["glider_eq"]
    assert p["shares"]["stage3"] * p["budget_s"] >= fs0["fit"] * fs0["need_s"] + a["fea_min_s"]              # the share holds the cases and the FEA
    s = budget.stage3_plan(p, CLASSES, a)
    assert s["fea"]["hold_s"] == a["fea_min_s"] and s["fs"]["fit"] == fs0["fit"]                              # no case the run's gate would refuse
    # a share too small for the FEA and the cases: nothing held, the shares are what they were
    monkeypatch.setattr(budget, "stage3_assumptions", lambda: dict(a, fea_min_s=1e9))
    q = budget.plan("overnight", 0, MISSION, thr={}, vehicle_classes=CLASSES)
    assert q["les"]["fea_hold_s"] == 0.0 and q["shares"]["stage3"] * q["budget_s"] == pytest.approx(fs0["fit"] * fs0["need_s"])
    assert budget.stage3_plan(q, CLASSES, dict(a, fea_min_s=1e9))["fea"]["hold_s"] == 0.0
    monkeypatch.undo()                                                                    # two cores: no free-surface case fits the whole share
    monkeypatch.setenv("CAFE_NPROC", "2")
    two = budget.plan("overnight", 0, MISSION, thr={}, vehicle_classes=CLASSES)
    assert budget.fs_plan(CLASSES, 3, a, s3)["fit"] == 0 and two["les"]["fea_hold_s"] == a["fea_min_s"]
    assert two["shares"]["stage3"] * two["budget_s"] == pytest.approx(a["fea_min_s"]) and budget.stage3_plan(two, CLASSES, a)["fs"]["fit"] == 0


def test_t10_a_profile_gives_the_free_surface_cases_the_stage_3_seconds_less_the_ones_the_plan_holds_for_the_fea(monkeypatch):
    """Before the fix to `profile_stage3_s` (job wo_fea_t3: test_review_round_6_m14 read 1282.2 s for 4h) the advice "it would fit --budget 4h" counted
    the FEA's seconds as the free-surface cases'."""
    from types import SimpleNamespace
    from cafe.pm import config, stage1
    monkeypatch.setenv("CAFE_NPROC", "6")
    m = config.load_mission("missions/tepex_c_demo.yaml")
    ctx = SimpleNamespace(mission=m, classes=stage1._classes(m), plan=dict(gpus=0, workers=6, mem_gb=None, env_gb=None, les={}))
    a = budget.stage3_assumptions()
    s = pw.profile_stage3_s(ctx)
    fs0 = budget.fs_plan(ctx.classes, budget.WINDOWS["overnight"], a, budget.SHARE["stage3"] * budget.BUDGET_S["overnight"])
    assert s["quick"] == 0.0 and s["4h"] == 0.0 and s["overnight"] == pytest.approx(fs0["fit"] * fs0["need_s"], abs=1e-3)


def test_t11_the_run_gate_runs_the_free_surface_case_the_plan_says_fits_when_the_share_is_exactly_the_cases_and_the_hold(monkeypatch):
    """The plan keeps `kept = fit * need_s + hold`; the run's share is `(kept / budget_s) * budget_s`, which can be a few 1e-13 s below `kept`, and the
    gate's left is that share less the hold. Before the gate allowed a microsecond (`_fs_gate`, as `stage3_plan`'s `fit` does) the case the plan said
    fits was refused for about one total in twenty."""
    from types import SimpleNamespace
    monkeypatch.setattr(pw.freesurface, "fitting_budget", lambda *args: "a larger --budget")
    monkeypatch.setattr(pw, "profile_stage3_s", lambda ctx: {})
    a = budget.stage3_assumptions()
    ctx = SimpleNamespace(plan=dict(shares=dict(stage3=0.1), budget_s=1.0))
    B, below, refused = budget.BUDGET_S["overnight"], 0, []
    for i in range(2000):
        est = dict(total_s=5000.0 + 2.173 * i, cells=dict(fine=1), iters=1, cores=1, rate=1.0)
        need_s = est["total_s"] * a["fs.margin"]
        hold = a["fea_min_s"] * (1 + i % 2)
        left = (((need_s + hold) / B) * B) - hold
        below += left < need_s
        if not pw._fs_gate(est, a, ctx, left, hold)[0]:
            refused.append(est["total_s"])
    assert below > 0 and not refused                       # the sweep does reach the band, and the gate runs every case in it
