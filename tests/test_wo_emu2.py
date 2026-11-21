"""Work order step 4, the emulator again: on a reach budget the emulator's share is its own plus the seconds of the stage-1 and stage-1b shares
that the plan does not price, so a refit does not starve it (on1: 99 variants ran in 7,200 s, 1,800 s would have run 25); the plan's note no
longer says 'will not train' for a plan that trains. Each test failed on the code of 40f04c5 and passes with the change
(review/workorder/handbacks/emu2.md lists the jobs)."""
import json

import pytest

from cafe.pm import budget, config, pipeline, report, stage1
from tests.fixtures import pm_run
from tests.test_pipeline import (  # noqa: F401  (data, fake_stage1 and table are fixtures)
    cheap_plan, data, fake_stage1, run_stage, synthetic_ctx, table)
from tests.test_report import plain, run  # noqa: F401  (run is a fixture)

pytestmark = pytest.mark.usefixtures("data", "emulator_speed_not_tested")

DEMO = config.load_mission(budget.ROOT / "missions" / "tepex_c_demo.yaml")


def demo_plan(name):
    return budget.plan(name, 0, DEMO, vehicle_classes=stage1._classes(DEMO), workers=6, mem_gb=48.0)


def old_share(p, free):
    return p["budget_s"] * (p["shares"]["emulator"] + (p["shares"]["stage1b"] if free else 0.0))


def test_at_overnight_a_refit_leaves_the_emulator_the_variants_that_reach_100_points():
    p = demo_plan("overnight")
    e = budget.emulator_plan(p)
    assert e["max_variants"] == 119 and e["variants_refit"] == 119 and e["variants_no_refit"] == 119            # the refit count alone reaches the cap
    assert e["trains"] and (e["variants_refit"] + 1) >= budget.EMULATOR_MIN_POINTS and min(e["points_per_scope"].values()) == 120
    assert int(budget.TRAIN_FRAC * old_share(p, False) // e["variant_s"]) < 119                                  # the old share: about 25 variants
    four = budget.emulator_plan(demo_plan("4h"))
    assert four["variants_refit"] == four["max_variants"] and four["trains"]


def test_the_reach_share_is_the_own_share_plus_the_unpriced_seconds_of_stages_1_and_1b():
    p = demo_plan("overnight")
    B, sh, s1 = p["budget_s"], p["shares"], p["stage1_s"]
    assert budget.STAGE1_PRICED == 5.0
    assert budget.emulator_share_s(p, False) == pytest.approx(B * (sh["emulator"] + sh["stage1"] + sh["stage1b"]) - 2 * 5.0 * s1)      # stage 1 and its rerun
    assert budget.emulator_share_s(p, True) == pytest.approx(B * (sh["emulator"] + sh["stage1"] + sh["stage1b"]) - 5.0 * s1)           # stage 1b was a copy
    assert budget.emulator_share_s(p, False) > 4 * old_share(p, False) and budget.emulator_share_s(p, True) > old_share(p, True)
    over = dict(p, stage1_s=B)                                                      # stage 1 priced over its share: never below the old value
    for free in (False, True):
        assert budget.emulator_share_s(over, free) == pytest.approx(old_share(p, free))


@pytest.mark.parametrize("name", ["ci", "quick"])
def test_the_other_budgets_keep_the_old_share(name):
    p = demo_plan(name)
    assert name not in budget.EMULATOR_REACH
    for free in (False, True):
        assert budget.emulator_share_s(p, free) == old_share(p, free) == budget.emulator_own_share_s(p, free)
    assert budget.emulator_share_s(dict(p, stage1_s=1e9), False) == old_share(p, False)                      # the stage-1 estimate is not read


@pytest.mark.parametrize("name", ["4h", "overnight"])
def test_the_four_planned_stage_seconds_fit_the_budget(name):
    p = demo_plan(name)
    B, sh, s1 = p["budget_s"], p["shares"], p["stage1_s"]
    assert B * sh["stage1"] >= budget.STAGE1_PRICED * s1                                                        # the floor does not bind here
    refit = budget.STAGE1_PRICED * s1 + B * sh["stage3"] + budget.STAGE1_PRICED * s1 + budget.emulator_share_s(p, False)
    copy = budget.STAGE1_PRICED * s1 + B * sh["stage3"] + 0.0 + budget.emulator_share_s(p, True)
    total = sum(sh.values()) * B                                                                                # 0.95 of the budget: 5 % stays slack
    assert total < B and refit == pytest.approx(total) and copy == pytest.approx(total)


def test_the_plans_note_does_not_say_will_not_train_when_it_trains_and_still_does_at_quick():
    e = budget.emulator_plan(demo_plan("overnight"))
    assert e["trains"] and "will not train" not in e["note"] and "100 are needed" in e["note"] and e["note"].startswith("this budget gives 120 distinct points")
    cheap_thr = dict(stage1={c: dict(s_per_batch_day=0.01, s_per_member_day=0.001, measured="t", host="h") for c in ("glider", "usv", "uas")})
    cheap = budget.emulator_plan(budget.plan("quick", 1, DEMO, thr=cheap_thr, vehicle_classes=stage1._classes(DEMO)))
    assert not cheap["trains"] and "the emulator will not train from this run alone" in cheap["note"]


def test_a_refit_run_on_a_reach_budget_says_what_its_share_is_made_of(tmp_path, table, fake_stage1):  # noqa: F811
    ctx = cheap_plan(synthetic_ctx(tmp_path, 48, "refit"), 100.0)                                              # glider_eq was refit
    ctx.plan.update(budget="overnight", stage1_s=0.5)
    d = run_stage(pipeline.s_emulator, ctx, "emulator")
    design = json.loads((ctx.run_dir / "emulator" / "design.json").read_text())
    assert design["share_s"] == pytest.approx(60.0) and design["stage1_unpriced"] and not design["stage1b_free"]          # 5 + 100 x 0.6 - 2 x 5 x 0.5
    note = next(n for n in d["notes"] if n.startswith("emulator share "))
    assert note.startswith("emulator share 60 s (its own share and the seconds of stages 1 and 1b the plan does not price):")
    assert "since no vehicle was refit" not in note and "stage 1b reran" not in note
    free = cheap_plan(synthetic_ctx(tmp_path, 48, "free", unused_refit=True), 100.0)                           # nothing refit: stage 1b was a copy
    free.plan.update(budget="overnight", stage1_s=0.5)
    d = run_stage(pipeline.s_emulator, free, "emulator")
    assert json.loads((free.run_dir / "emulator" / "design.json").read_text())["share_s"] == pytest.approx(62.5)               # 5 + 100 x 0.6 - 5 x 0.5
    assert any(n.startswith("emulator share 62 s (its own share and the seconds of stages 1 and 1b the plan does not price):") for n in d["notes"])


def test_the_report_says_the_same_of_the_share(run):
    m, plan = pm_run.make_run(run)
    p = run / "emulator" / "design.json"
    d = json.loads(p.read_text())
    d.update(stage1_unpriced=True)
    p.write_text(json.dumps(d))
    report.write(run, m, plan)
    t = plain((run / "report" / "index.html").read_text())
    assert "against the emulator share 120 s, of which 84 s is for them (its own share and the seconds of stages 1 and 1b the plan does not price);" in t
    assert "since no vehicle was refit" not in t
