"""Round 18, batch A: the what-if and the report. One test (or a few) for each finding; each was seen to fail on the code of d69be8f and to pass with the fix
(review/round_18/handbacks/r18_handback_A.md lists the runs). M-1 a Stage-1 row's target and badge are against the verdict of the unchanged mission on the row's
own members; M-3 (the link card) the sentence for two low antennas; M-5 `whatif` takes its members from the run's plan.json; M-6 the links a what-if does not
rerun and a header that says what was done; M-7 a UAS shift is bounded by the window; M-16 (A-5) a low end that is the link's `b`."""
import copy
import re

import numpy as np
import pytest

from cafe.pm import __main__ as cli, budget, config, pipeline, report, stage1, whatif
from cafe.pm.env.protocol import AnalyticEnv
from tests.test_cli import wi, whatif_args  # noqa: F401  (wi is a fixture)
from tests.test_round16_report import data_dir  # noqa: F401  (autouse)
from tests.test_round17_a import edit_json, rf, usv_fix
from tests.test_round17_d import F915, fresnel_loss_db
from tests.test_whatif import ENV, GL, GSC, TRACK, STORM, plan_for, storm_em  # noqa: F401  (storm_em is a fixture)

pytestmark = pytest.mark.usefixtures("emulator_speed_not_tested")
DEMO = config.load_mission(config.ROOT / "missions" / "tepex_c_demo.yaml")


# ---- M-1: a Stage-1 row is a fix against the verdict of the unchanged mission on its own members --------------------------------------------------------

WHOLE = set(range(12)) | set(range(32, 46))        # the whole run: 26 of 64 fail (NO-GO), 12 of its first 32 (MARGINAL)
GO_FIRST = set(range(2)) | set(range(32, 56))      # 26 of 64 (NO-GO), but only 2 of the first 32 (GO)


def fake_runs(monkeypatch, base_fail, cand_fail):
    """Stage 1 on a fake: the unchanged STORM mission fails the members of `base_fail`, a changed one those of `cand_fail`.
    -> [(is it the unchanged mission, its members)]."""
    calls = []

    def run_batch(mission, e, members, seed, pri, marg, scales):
        base = mission["vehicles"] == STORM["vehicles"]
        calls.append((base, list(members)))
        fail = np.isin(members, sorted(base_fail if base else cand_fail))
        return dict(vehicles={v["id"]: dict(fail=dict(x=fail), lon=np.zeros((2, len(members))), **{"class": "glider"}) for v in mission["vehicles"]})
    monkeypatch.setattr(stage1, "run_batch", run_batch)
    return calls


def search(base_fail, flags=True, share=10.0):
    plan = plan_for(STORM, 32)
    cost = budget.batch_cost_s(plan, [GL])
    whole = {GL: dict(verdict="NO-GO", p_fail=26 / 64, n=64)}
    given = {GL: np.isin(np.arange(64), sorted(base_fail))} if flags else None
    return whatif.flip_search(STORM, whole, {GL: TRACK}, ENV, {}, plan, *stage1.priors_for(STORM), None, 5, share * cost, lambda *_: None, given), cost


def test_m1_a_row_that_leaves_the_verdict_where_it_was_on_its_own_members_is_no_fix_though_the_whole_run_was_no_go(monkeypatch):
    """The whole run is NO-GO (26 of 64) and its first 32 are MARGINAL (12 of 32): a candidate at 11 of 32 is MARGINAL on the members it is compared on. It was
    accepted as a fix (target GO or MARGINAL, from the whole run) and printed 'NO-GO to MARGINAL' for a change of 12 failures to 11."""
    calls = fake_runs(monkeypatch, WHOLE, set(range(11)))
    (flips, spent), cost = search(WHOLE)
    f = flips[GL]
    assert f["verdict"] == "NO-GO" and f["target"] == "GO or MARGINAL"                           # the whole run's, for the emulated rows
    assert f["base_same"]["verdict"] == "MARGINAL" and f["base_same"]["p_fail"] == 12 / 32 and f["target_same"] == "GO"
    rows = [t for t in f["tried"] if t["method"] == "Stage 1"]
    assert len(rows) == whatif.FALLBACK_K and all(t["verdict"] == "MARGINAL" and t["p_fail"] == 11 / 32 for t in rows)
    assert not f["found"] and f["best"] is None and spent == len(rows) * cost and len(calls) == len(rows)


def test_m1_a_row_that_reaches_the_target_of_its_own_members_is_the_fix_and_stops_the_search(monkeypatch):
    calls = fake_runs(monkeypatch, WHOLE, set(range(2)))
    (flips, spent), cost = search(WHOLE)
    f = flips[GL]
    assert f["found"] and f["best"]["method"] == "Stage 1" and f["best"]["verdict"] == "GO" and f["best"]["p_fail"] == 2 / 32
    assert f["verdict"] == "NO-GO" and f["target_same"] == "GO"                       # the whole run's verdict stays the run's; the target is the members'
    assert len([t for t in f["tried"] if t["method"] == "Stage 1"]) == 1 and spent == cost and len(calls) == 1
    calls = fake_runs(monkeypatch, WHOLE, set(range(4)))                                        # MARGINAL, which the old target (GO or MARGINAL) took for a fix
    (flips, _), _ = search(WHOLE)
    assert not flips[GL]["found"]


def test_m1_without_the_base_runs_flags_the_baseline_is_measured_first_and_its_verdict_is_the_target(monkeypatch):
    calls = fake_runs(monkeypatch, WHOLE, set(range(11)))
    (flips, spent), cost = search(WHOLE, flags=False)
    f = flips[GL]
    assert calls[0] == (True, list(range(32))) and all(not base for base, _ in calls[1:])      # the baseline is the first batch run: the rows are judged by it
    assert f["base_same"]["verdict"] == "MARGINAL" and f["target_same"] == "GO" and not f["found"]
    assert spent == (whatif.FALLBACK_K + 1) * cost
    calls = fake_runs(monkeypatch, WHOLE, set(range(2)))
    (flips, spent), cost = search(WHOLE, flags=False)
    assert flips[GL]["found"] and spent == 2 * cost                                              # the baseline and the one candidate


def test_m1_a_share_that_covers_not_even_the_baseline_runs_nothing_and_judges_by_the_whole_runs_target(monkeypatch):
    calls = fake_runs(monkeypatch, WHOLE, set(range(2)))
    (flips, spent), _ = search(WHOLE, flags=False, share=0.9)
    f = flips[GL]
    assert calls == [] and spent == 0.0 and f["base_same"] is None and f["target_same"] is None and "target_same" in f      # the key is there: "not measured"
    assert not f["found"] and any("share of the emulator budget is spent" in t["reason"] for t in f["tried"])


def test_m1_a_baseline_that_is_go_on_its_members_leaves_nothing_to_fix_and_no_stage_1_row_is_run(monkeypatch):
    calls = fake_runs(monkeypatch, GO_FIRST, set(range(2)))
    (flips, spent), _ = search(GO_FIRST)
    f = flips[GL]
    assert f["base_same"]["verdict"] == "GO" and f["target_same"] == "" and f["target"] == "GO or MARGINAL"
    assert calls == [] and spent == 0.0 and not f["found"] and f["evaluated"] == 0
    assert any("Stage 1 not run: the unchanged mission is already GO on the candidates' own members" in t["reason"] for t in f["tried"])
    assert whatif._better_than("NO-GO") == ("GO", "MARGINAL") and whatif._better_than("MARGINAL") == ("GO",) and whatif._better_than("GO") == ()


def test_m1_an_emulated_row_keeps_the_whole_runs_target(storm_em, monkeypatch):  # noqa: F811
    calls = fake_runs(monkeypatch, WHOLE, set(range(2)))
    em, info = storm_em
    flips, _ = whatif.flip_search(STORM, {GL: dict(verdict="NO-GO", p_fail=26 / 64, n=64)}, {GL: TRACK}, ENV, {GSC: (em, info)}, plan_for(STORM, 32),
                                  *stage1.priors_for(STORM), None, 5, 1e6, lambda *_: None, {GL: np.isin(np.arange(64), sorted(WHOLE))})
    f = flips[GL]
    assert f["best"]["method"] == "EMULATED" and f["target"] == "GO or MARGINAL" and f["target_same"] is None and f["base_same"] is None and calls == []


class Env3D(AnalyticEnv):
    use_3d = True


def test_m1_a_uas_in_a_3d_wind_is_judged_by_its_baseline_under_the_same_wind_model(monkeypatch):
    """A UAS row is flown in the 10 m profile and its base run in the 3-D wind: the baseline that counts is the measured one, and so is its verdict."""
    ci = config.load_mission(config.ROOT / "missions" / "ci_fixture.yaml")
    env, seen = Env3D(), []

    def measure(mission, vid, e, plan, pri, marg, scales, seed, n=None, members=None):
        seen.append(mission is ci)
        base = mission is ci
        return dict(p_fail=0.3 if base else 0.05, lo=0.2, hi=0.4, verdict="MARGINAL" if base else "GO", n=16)
    monkeypatch.setattr(whatif, "measure", measure)
    plan = plan_for(ci, 4)
    cost = budget.batch_cost_s(plan, ["uas"])
    flips, spent = whatif.flip_search(ci, {"uas": dict(verdict="NO-GO", p_fail=0.8)}, {}, env, {}, plan, {}, {}, None, 5, 10 * cost, lambda *_: None)
    f = flips["uas"]
    assert seen[0] is True and f["base_2d"]["verdict"] == "MARGINAL" and f["target"] == "GO or MARGINAL" and f["target_same"] == "GO"
    assert f["found"] and f["best"]["verdict"] == "GO" and spent == 2 * cost                       # the baseline first, then the one row that reaches GO


def flip_report(tmp_path, **flip):
    """The synthetic run's USV fix section with `flip` merged into its flip.json entry. -> (report.json, the USV's fix text, the run directory)."""
    rep, t, run = usv_fix(tmp_path, **flip)
    starts = [m.start() for m in re.finditer(r"What would fix it \(", t)] + [len(t)]
    return rep, next(t[a:b] for a, b in zip(starts, starts[1:], strict=False) if "deploy 6 h later" in t[a:b]), run


NO_GO_RUN = dict(verdict="NO-GO", p_fail=0.45, target="GO or MARGINAL", n=64)


def test_m1_the_fix_line_pairs_the_same_members_verdict_with_the_same_members_p_fail_and_names_the_whole_runs(tmp_path):
    rep, t, run = flip_report(tmp_path, target_same="GO", base_same=dict(verdict="MARGINAL", p_fail=0.375, lo=0.23, hi=0.55, n=32), **NO_GO_RUN)
    f = rep["vehicles"]["usv"]["fix"]
    assert f["target_same"] == "GO" and f["target"] == "GO or MARGINAL" and f["same_members"]["verdict"] == "MARGINAL"
    assert ("deploy 6 h later: P(fail) 0.375 on the same 32 members becomes 0 (0 to 0.14, Wilson interval (Stage 1)), "
            "MARGINAL (whole run: NO-GO) to GO (Stage 1, n = 16 members)") in t
    assert "NO-GO to GO" not in t and "What would fix it (GO): " in t                                # the target the row was judged against
    assert "A Stage-1 row is a fix when it reaches GO (the whole run's target is GO or MARGINAL)." in t
    assert rep["traceability_problems"] == [] and report.check_rendered(rep, (run / "report" / "index.html").read_text()) == []


def test_m1_the_pair_is_one_verdict_when_the_two_bases_agree_and_the_page_says_when_a_baseline_cannot_be_fixed_against(tmp_path):
    _, t, _ = flip_report(tmp_path, verdict="MARGINAL", p_fail=0.18, target="GO", target_same="GO", n=64,
                          base_same=dict(verdict="MARGINAL", p_fail=0.125, lo=0.03, hi=0.3, n=32))
    assert "MARGINAL to GO (Stage 1, n = 16 members)" in t and "whole run:" not in t and "(the whole run's target is" not in t and "reaches GO." in t
    rep, t, run = flip_report(tmp_path / "go", best=None, found=False, target_same="", base_same=dict(verdict="GO", p_fail=0.0625, lo=0.0, hi=0.2, n=32),
                              **NO_GO_RUN)
    assert "The unchanged mission is already GO on those members, so no Stage-1 row can be a fix (the whole run's target is GO or MARGINAL)." in t
    assert "none reaches GO or MARGINAL" in t and report.check_rendered(rep, (run / "report" / "index.html").read_text()) == []


def test_m1_a_flip_json_without_target_same_renders_with_the_whole_runs_verdict_as_it_did(tmp_path):
    rep, t, _ = flip_report(tmp_path, base_same=dict(verdict="NO-GO", p_fail=0.125, lo=0.03, hi=0.3, n=32), n=64)       # round 17's flip.json: no target_same
    assert rep["vehicles"]["usv"]["fix"]["target_same"] is None
    assert "P(fail) 0.125 on the same 32 members becomes 0 " in t and "MARGINAL to GO (Stage 1, n = 16 members)" in t and "whole run:" not in t
    assert "What would fix it (GO): " in t and "A Stage-1 row is a fix when" not in t


def test_m1_every_fix_says_that_a_vehicles_links_are_not_rerun_for_its_change(tmp_path):
    _, t, _ = usv_fix(tmp_path)
    assert t.count("A change is tried on this vehicle alone: the links that end at it are not rerun for it, so a link's verdict above is of the mission as it "
                   "stands.") == 2                                                              # the quadrotor's and the USV's


# ---- M-3 (the link card): two low antennas ---------------------------------------------------------------------------------------------------------------

def two_gliders(a, b):
    m = copy.deepcopy(DEMO)
    for vid, platform in (("glider_eq", a), ("glider_2n", b)):
        next(v for v in m["vehicles"] if v["id"] == vid)["platform"] = platform
    return m


def test_m3_two_low_ends_get_the_sentence_of_the_pair_with_its_larger_figure_and_the_verdict_it_can_move():
    for a, b, ends in (("seaglider", "slocum", "glider_eq (0.5 m), glider_2n (0.3 m)"), ("slocum", "slocum", "glider_eq (0.3 m), glider_2n (0.3 m)"),
                       ("seaglider", "seaglider", "glider_eq (0.5 m), glider_2n (0.5 m)")):          # the last: no end is below 0.5 m, both are at it
        note = report._low_antenna_note(rf("glider_eq", "glider_2n"), two_gliders(a, b))
        assert note and note.startswith(f"Both ends of this RF link have an antenna of 0.5 m or lower: {ends}."), (a, b, note)
        assert "by 6 to 11 dB" in note and "this margin is too low" in note and "MARGINAL or NO-GO" in note
        assert "a Seaglider with a Slocum about 9 dB, two Slocums about 11, two Seagliders about 7" in note and "too high" not in note
        assert note.endswith("(CREDIBILITY, limitation L23).")
        assert "conservative" not in note and "partner" not in note


def test_m3_one_low_end_keeps_its_sentence_and_says_which_partner_its_band_is_for():
    note = report._low_antenna_note(rf("glider_2n", "usv"), DEMO)
    assert note.startswith("An end of this RF link has an antenna below 0.5 m: glider_2n (0.3 m).") and "with a partner of 2.2 m or more" in note
    assert "about 5 dB at 0.3 m (1 to 6) and 11 to 16 dB at 0.1 m" in note and "this margin is too low" in note
    assert "conservative" not in note and "too high" not in note and "both" not in note.lower() and "6 to 11" not in note
    assert report._low_antenna_note(rf("glider_eq", "usv"), DEMO) is None                           # a 0.5 m Seaglider with the 2.2 m whip: neither case
    assert report._low_antenna_note(rf("glider_eq", "uas"), DEMO) is None
    assert report._low_antenna_note(rf("glider_eq", "glider_2n", "acoustic"), two_gliders("slocum", "slocum")) is None


def test_m3_the_figure_of_the_pair_sentence_is_what_the_model_gives_against_a_fresnel_two_ray():
    """'About 6 to 11 dB' for two low ends: model minus a flat-earth Fresnel two-ray (eps_c 72.8 - j118.9, 915 MHz, Hs 0), 200 m to the radio horizon,
    400 points: written in tests/test_round17_d.py from the published formulas. Measured here (min / median / max): the pairs (0.5, 0.5) +6.3 / +6.7 /
    +6.7 dB, (0.5, 0.3) +9.0 / +9.3 / +9.3 and (0.3, 0.3) +11.1 / +11.4 / +11.4; each band is widened by 0.4 dB. A flat-earth two-ray has no surface
    wave: the figure is a bound."""
    from cafe.pm.physics import comms
    medians = []
    for (ht, hr), (lo, hi) in {(0.5, 0.5): (5.9, 7.1), (0.5, 0.3): (8.6, 9.7), (0.3, 0.3): (10.7, 11.8)}.items():
        d = np.linspace(200.0, np.sqrt(2.0 * comms.A_EFF) * (np.sqrt(ht) + np.sqrt(hr)), 400)          # to the radio horizon: beyond it the model is diffracted
        diff = comms.two_ray_loss_db(d, ht, hr, 0.0, F915) - fresnel_loss_db(d, ht, hr)
        assert lo <= diff.min() and diff.max() <= hi, (ht, hr, diff.min(), np.median(diff), diff.max())
        medians.append(np.median(diff))
    assert 6.0 <= min(medians) and max(medians) <= 11.5                                         # the sentence's "6 to 11" is those figures, rounded


# ---- M-16 (A-5): the low end is the link's b -------------------------------------------------------------------------------------------------------------

def test_a5_a_link_whose_low_end_is_its_second_gets_the_sentence_too():
    """`(lk["a"],)` for `(lk["a"], lk["b"])` survived: every link of round 17's tests had its low end as `a`."""
    for a, b in (("usv", "glider_2n"), ("glider_2n", "usv")):
        note = report._low_antenna_note(rf(a, b), DEMO)
        assert note and note.startswith("An end of this RF link has an antenna below 0.5 m: glider_2n (0.3 m).")
    assert report._low_antenna_note(rf("uas", "glider_2n"), DEMO).startswith("An end of this RF link has an antenna below 0.5 m: glider_2n (0.3 m).")


# ---- M-5: whatif takes the members of its Stage-1 fallback from the run's plan.json ------------------------------------------------------------------------

def test_m5_a_budget_that_is_not_the_runs_is_refused_naming_both(wi, capsys):  # noqa: F811
    assert cli.main(whatif_args(wi, "--shift", "6h", "--budget", "ci")) == 2
    err = capsys.readouterr().err
    assert err.startswith("error: --budget ci: the run ") and "was made with --budget quick" in err and "draws its members from that plan" in err
    assert not wi.seen                                                                              # nothing was answered


def test_m5_the_ensemble_of_the_fallback_is_the_runs_own_and_not_this_machines_plan_for_the_budget(wi):  # noqa: F811
    edit_json(wi.run / "plan.json", lambda d: d.update(batch=24, n_min=24, n_max=72))
    assert cli.main(whatif_args(wi, "--shift", "6h")) == 0
    p = wi.seen["plan"]
    assert (p["batch"], p["n_min"], p["n_max"], p["budget"]) == (24, 24, 72, "quick")
    assert cli.main(whatif_args(wi, "--shift", "6h", "--budget", "quick")) == 0                    # the run's own budget, spelled out, is accepted
    assert wi.seen["plan"]["batch"] == 24


def test_m5_a_run_made_with_another_budget_is_answered_with_that_budgets_plan(wi):  # noqa: F811
    edit_json(wi.run / "plan.json", lambda d: d.update(budget="ci"))
    assert cli.main(whatif_args(wi, "--shift", "6h")) == 0 and wi.seen["plan"]["budget"] == "ci"   # no --budget needed for the run RUNBOOK invites to rerun
    assert cli.main(whatif_args(wi, "--shift", "6h", "--budget", "ci")) == 0


def test_m5_a_directory_with_no_plan_keeps_the_budget_of_the_command_line_and_defaults_to_quick(wi, tmp_path, capsys):  # noqa: F811
    none = str(tmp_path / "none")
    assert cli.main(["whatif", "--mission", str(config.ROOT / "missions" / "tepex_c_demo.yaml"), "--run", none, "--shift", "6h"]) == 0
    assert wi.seen["plan"]["budget"] == "quick" and "at the quick budget" in capsys.readouterr().out
    assert cli.main(["whatif", "--mission", str(config.ROOT / "missions" / "tepex_c_demo.yaml"), "--run", none, "--shift", "6h", "--budget", "ci"]) == 0
    assert wi.seen["plan"]["budget"] == "ci"


def test_m5_a_damaged_plan_json_is_the_damaged_file_message_not_a_traceback(wi, capsys):  # noqa: F811
    (wi.run / "plan.json").write_text("[1]")
    assert cli.main(whatif_args(wi, "--shift", "6h")) == 2
    assert "plan.json: not a JSON object" in capsys.readouterr().err
    (wi.run / "plan.json").write_text("{}")
    assert cli.main(whatif_args(wi, "--shift", "6h")) == 2
    assert "damaged or incomplete (KeyError: 'budget')" in capsys.readouterr().err
    (wi.run / "plan.json").write_text('{"budget": "quick"}')
    assert cli.main(whatif_args(wi, "--shift", "6h")) == 2
    assert "damaged or incomplete (KeyError: 'batch')" in capsys.readouterr().err


def test_m5_the_budget_flag_has_no_default_and_the_help_says_whose_it_is():
    a = cli.build_parser().parse_args(["whatif", "--mission", "m.yaml", "--shift", "6h"])
    assert a.budget is None
    text = " ".join(cli.build_parser()._subparsers._group_actions[0].choices["whatif"].format_help().split())
    assert "the budget the run was made with" in text and "a different budget is refused" in text


# ---- M-6: the links a what-if does not rerun, and a header that says what was done -----------------------------------------------------------------------

def ask(monkeypatch, ops, only=None, drop=()):
    monkeypatch.setattr(whatif, "_stage1", lambda *a, **k: dict(p_fail=0.2, lo=0.1, hi=0.3, verdict="MARGINAL", n=32))
    base = {v["id"]: dict(verdict="NO-GO", p_fail=0.9) for v in DEMO["vehicles"]}               # no n: the answer is not re-measured on its members
    return whatif.answer(DEMO, dict(ops, drop=list(drop)), base, {}, ENV, {}, plan_for(DEMO, 32), None, None, only=only)


def test_m6_the_answer_names_the_links_that_end_at_a_changed_vehicle_and_were_not_rerun(monkeypatch):
    ans = ask(monkeypatch, dict(dlat=0.5), only=["usv"])
    assert ans["links_not_rerun"] == ["usv-uas-rf", "usv-shore-iridium"] and ans["links_removed"] == []
    ans = ask(monkeypatch, dict(shift_h=6.0), only=["glider_eq"])
    assert ans["links_not_rerun"] == ["glider_eq-ship-acoustic"]


def test_m6_a_move_of_the_ship_takes_every_link_that_ends_at_it(monkeypatch):
    ans = ask(monkeypatch, dict(dlat=0.5), only=["uas"])                             # the UAS moves with its ship: the acoustic links end at the ship
    assert ans["links_not_rerun"] == ["usv-uas-rf", "glider_eq-ship-acoustic", "glider_2n-ship-acoustic"]
    ans = ask(monkeypatch, dict(shift_h=6.0), only=["uas"])                                       # a launch shift moves no ship: only the UAS's own link
    assert ans["links_not_rerun"] == ["usv-uas-rf"]


def test_m6_a_link_of_a_dropped_vehicle_is_removed_and_not_also_not_rerun(monkeypatch):
    ans = ask(monkeypatch, dict(shift_h=6.0), only=["uas", "glider_eq"], drop=["usv"])
    assert ans["links_removed"] == ["usv-uas-rf", "usv-shore-iridium"] and ans["links_not_rerun"] == ["glider_eq-ship-acoustic"]
    ans = ask(monkeypatch, dict(), drop=["usv"])
    assert ans["links_not_rerun"] == []


def test_m6_the_command_prints_one_note_line_after_the_vehicle_lines(wi, capsys, monkeypatch):  # noqa: F811
    r = dict(base=dict(verdict="NO-GO", p_fail=0.7), method="Stage 1", why="no emulator", p_fail=0.5, lo=0.3, hi=0.7, verdict="NO-GO", n=32)
    monkeypatch.setattr(whatif, "answer", lambda *a, **k: dict(vehicles={"usv": r}, dropped=[], links_removed=[],
                                                              links_not_rerun=["usv-uas-rf", "usv-shore-iridium"]))
    cli.main(whatif_args(wi, "--move", "0.5deg north", "--vehicle", "usv"))
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "whatif tepex_c_demo: +0 deg lon, +0.5 deg lat" and out[1].startswith("usv: NO-GO")
    assert out[2] == "  note: links not rerun (their verdicts are the report's, of the unchanged mission): usv-uas-rf, usv-shore-iridium" and len(out) == 3
    monkeypatch.setattr(whatif, "answer", lambda *a, **k: dict(vehicles={"usv": r}, dropped=[], links_removed=[], links_not_rerun=[]))
    cli.main(whatif_args(wi, "--move", "0.5deg north", "--vehicle", "usv"))
    assert len(capsys.readouterr().out.splitlines()) == 2                                          # none to say: no line


def test_m6_a_shift_or_move_that_reached_no_vehicle_is_not_echoed_as_done(wi, capsys, monkeypatch):  # noqa: F811
    """`--shift 6h --drop usv --vehicle usv` printed 'whatif m: +6 h; drop usv' and then only the dropped line: the shift went to no vehicle."""
    monkeypatch.undo()                                                                              # the real whatif.answer and an empty training table
    monkeypatch.setattr(pipeline, "DATA", wi.data)
    monkeypatch.setattr(pipeline.Context, "env", property(lambda self: AnalyticEnv()))
    assert cli.main(whatif_args(wi, "--shift", "6h", "--drop", "usv", "--vehicle", "usv")) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "whatif tepex_c_demo: (the shift applied to no vehicle); drop usv"
    assert cli.main(whatif_args(wi, "--shift", "6h", "--move", "1deg W", "--drop", "uas", "--vehicle", "uas")) == 0
    assert capsys.readouterr().out.splitlines()[0] == "whatif tepex_c_demo: (the shift applied to no vehicle); (the move applied to no vehicle); drop uas"


def test_m6_a_shift_that_reached_a_vehicle_is_echoed(wi, capsys, monkeypatch):  # noqa: F811
    r = dict(base=dict(verdict="NO-GO", p_fail=0.7), method="Stage 1", why="no emulator", p_fail=0.5, lo=0.3, hi=0.7, verdict="NO-GO", n=32)
    monkeypatch.setattr(whatif, "answer", lambda *a, **k: dict(vehicles={"usv": r}, dropped=["uas"], links_removed=[]))
    cli.main(whatif_args(wi, "--shift", "6h", "--drop", "uas"))
    assert capsys.readouterr().out.splitlines()[0] == "whatif tepex_c_demo: +6 h; drop uas"
    monkeypatch.setattr(whatif, "answer", lambda *a, **k: dict(vehicles={}, dropped=[], links_removed=[], unchanged={"uas": "launching +24 h later ..."}))
    cli.main(whatif_args(wi, "--shift", "24h", "--vehicle", "uas"))                  # a UAS whole-day shift reached it, and it says nothing changes
    assert capsys.readouterr().out.splitlines()[0] == "whatif tepex_c_demo: +24 h"
    r2 = dict(r, ship="the ship moved with uas: +0 deg lon, +0.5 deg lat")
    monkeypatch.setattr(whatif, "answer", lambda *a, **k: dict(vehicles={"usv": r2}, dropped=[], links_removed=[]))
    cli.main(whatif_args(wi, "--shift", "6h", "--move", "0.5deg N", "--vehicle", "uas"))     # the vehicle there only moved with the ship: it took no shift
    assert capsys.readouterr().out.splitlines()[0] == "whatif tepex_c_demo: (the shift applied to no vehicle); +0 deg lon, +0.5 deg lat"


# ---- M-7: a UAS shift is bounded by the window like every other vehicle's -------------------------------------------------------------------------------

@pytest.mark.parametrize("h", [1e20, 1e300, 99999999999999999999.0, -1e20, 144.5, -145.0])
def test_m7_a_uas_launch_shift_longer_than_the_window_is_refused(h):
    """6 days of window: `shift_h=1e20` gave a launch time of day that was the float residue of 1e20 * 60 modulo 1440 (06:00); 1e300 gave 17:44."""
    with pytest.raises(whatif.Invalid, match=r"uas: launching .* later is more than the window's 144 h, outside the window 2023-03-01"):
        whatif.apply(DEMO, {"uas": dict(shift_h=h)})


def test_m7_a_shift_inside_the_window_is_taken_and_the_whole_day_refusal_comes_first():
    for h in (6.0, 25.0, -6.0, 143.0):
        m = whatif.apply(DEMO, {"uas": dict(shift_h=h)})
        assert m["vehicles"][-1]["sorties"]["local_solar_time"] != DEMO["vehicles"][-1]["sorties"]["local_solar_time"]
    with pytest.raises(whatif.Invalid, match="a whole number of days"):
        whatif.apply(DEMO, {"uas": dict(shift_h=144.0)})                                  # exactly the window, and whole days: the older refusal says so
    with pytest.raises(whatif.Invalid, match="a whole number of days"):
        whatif.apply(DEMO, {"uas": dict(shift_h=48.0)})
    with pytest.raises(whatif.Invalid, match="outside the window"):                                  # the USV's own refusal is the model of the wording
        whatif.apply(DEMO, {"usv": dict(shift_h=1e20)})


def test_m7_the_command_line_spelling_is_refused_as_a_bad_input(monkeypatch):
    monkeypatch.setattr(whatif, "_stage1", lambda *a, **k: pytest.fail("a refused change is not run"))
    with pytest.raises(whatif.Invalid, match="outside the window"):
        whatif.answer(DEMO, dict(shift_h=whatif.parse_shift("99999999999999999999h")), {}, {}, ENV, {}, plan_for(DEMO, 32), None, None, only=["uas"])
