"""Round 17, batch A: what the what-if and the report print. One test (or a few) for each finding; each was seen to fail on the code of round 16 and to pass
with the fix (review/round_17/handbacks/r17_handback_A.md lists the runs). M-1 a Stage-1 candidate is compared with the unchanged mission on its own members;
M-3 the glider surfaced share is "of the run"; M-5 the link-card sentence for an RF link to a low antenna; M-7 the UAS levels note; M-19 (A-1) the two
mutants of round 16's hull-depth note that no test killed."""
import copy
import html
import json
import re

import numpy as np
import pytest

from cafe.pm import __main__ as cli, budget, config, pipeline, report, stage1, whatif
from cafe.pm.physics import uas
from tests.fixtures import pm_run
from tests.test_cli import wi, whatif_args  # noqa: F401  (wi is a fixture)
from tests.test_pipeline import cheap_plan, fake_stage1, run_stage, synthetic_ctx, table  # noqa: F401  (fake_stage1 and table are fixtures)
from tests.test_round16_report import data_dir, full  # noqa: F401  (autouse and a fixture)
from tests.test_whatif import ENV, GL, GSC, STORM, TRACK, plan_for, storm_em  # noqa: F401  (storm_em is a fixture)

pytestmark = pytest.mark.usefixtures("emulator_speed_not_tested")
DEMO = config.load_mission(config.ROOT / "missions" / "tepex_c_demo.yaml")


def plain(h):
    return html.unescape(re.sub(r"<[^>]+>", "", re.sub(r"<a class=lk[^>]*>[LR]</a>", "", h)))


# ---- M-1: the baseline of a Stage-1 row is the unchanged mission on the row's members ------------------------------------------------------------------

BASE_FAIL = set(range(5)) | set(range(40, 50))        # 15 of the 64 members of the report's run, 5 of the first 32
CAND_FAIL = set(range(4))                              # a changed mission: 4 of the first 32


def fake_batch(monkeypatch, base_fail=BASE_FAIL, cand_fail=CAND_FAIL):
    """Stage 1 on a fake: the unchanged STORM mission fails the members in `base_fail`, a changed one those in `cand_fail`. -> the members of each call."""
    calls = []

    def run_batch(mission, e, members, seed, pri, marg, scales):
        calls.append(list(members))
        fail = np.isin(members, sorted(base_fail if mission["vehicles"] == STORM["vehicles"] else cand_fail))
        return dict(vehicles={v["id"]: dict(fail=dict(x=fail), lon=np.zeros((2, len(members))), **{"class": "glider"}) for v in mission["vehicles"]})
    monkeypatch.setattr(stage1, "run_batch", run_batch)
    return calls


BASE = {GL: dict(verdict="NO-GO", p_fail=15 / 64, n=64)}


def test_m1_the_flip_search_measures_the_unchanged_mission_on_the_members_of_its_stage_1_rows(monkeypatch):
    calls = fake_batch(monkeypatch)
    plan = plan_for(STORM, 32)
    cost = budget.batch_cost_s(plan, [GL])
    flips, spent = whatif.flip_search(STORM, BASE, {GL: TRACK}, ENV, {}, plan, *stage1.priors_for(STORM), None, 5, 10 * cost, lambda *_: None)
    f = flips[GL]
    rows = [t for t in f["tried"] if t["method"] == "Stage 1"]
    assert rows and all(t["p_fail"] == 4 / 32 and t["n"] == 32 for t in rows)
    assert f["p_fail"] == 15 / 64 and f["n"] == 64                                              # the whole run's, and how many members it is of
    assert (f["base_same"]["p_fail"], f["base_same"]["n"]) == (5 / 32, 32) and f["base_2d"] is None       # the same members as the rows: 5 of 32, not 15 of 64
    assert spent == (len(rows) + 1) * cost and calls[-1] == list(range(32))                       # the baseline is a batch, charged as one


def test_m1_a_share_that_covers_no_batch_leaves_the_baseline_unmeasured_and_says_so(monkeypatch):
    """Round 18, M-1: the baseline is measured first (the rows are judged by its verdict), so it is the share that covers no batch that leaves it unmeasured."""
    fake_batch(monkeypatch)
    plan = plan_for(STORM, 32)
    cost = budget.batch_cost_s(plan, [GL])
    flips, spent = whatif.flip_search(STORM, BASE, {GL: TRACK}, ENV, {}, plan, *stage1.priors_for(STORM), None, 5, 0.9 * cost, lambda *_: None)
    assert flips[GL]["base_same"] is None and spent == 0.0 and "base_same" in flips[GL]      # the key is there: a report of this round says "not measured"


def test_m1_the_base_runs_own_first_batch_is_the_baseline_at_no_cost_and_needs_no_share(monkeypatch):
    calls = fake_batch(monkeypatch)
    plan = plan_for(STORM, 32)
    cost = budget.batch_cost_s(plan, [GL])
    flags = {GL: np.isin(np.arange(64), sorted(BASE_FAIL))}                                      # 15 of the 64 members, 5 of the first 32
    flips, spent = whatif.flip_search(STORM, BASE, {GL: TRACK}, ENV, {}, plan, *stage1.priors_for(STORM), None, 5, 1.5 * cost, lambda *_: None, flags)
    f = flips[GL]
    assert (f["base_same"]["p_fail"], f["base_same"]["n"]) == (5 / 32, 32) and f["base_same"]["verdict"] in ("GO", "MARGINAL", "NO-GO")
    assert spent == cost and len(calls) == 1 and calls[0] == list(range(32))                     # only the one candidate ran; the baseline was read
    flips, _ = whatif.flip_search(STORM, BASE, {GL: TRACK}, ENV, {}, plan, *stage1.priors_for(STORM), None, 5, 10 * cost, lambda *_: None,
                                  {GL: flags[GL][:8]})                                           # fewer flags than a batch: measured, as without them
    assert flips[GL]["base_same"]["n"] == 32 and (flips[GL]["base_same"]["p_fail"] == 5 / 32)


def test_m1_the_pipeline_hands_the_base_runs_failure_flags_to_the_flip_search(tmp_path, table, fake_stage1, monkeypatch):  # noqa: F811
    seen, real = {}, whatif.flip_search
    monkeypatch.setattr(whatif, "flip_search", lambda *a, **k: (seen.update(a=a, k=k), real(*a, **k))[1])
    ctx = cheap_plan(synthetic_ctx(tmp_path, 48))
    run_stage(pipeline.s_emulator, ctx, "emulator")
    import pickle
    res = pickle.loads((ctx.run_dir / "stage1b" / "res.pkl").read_bytes())
    flags = seen["a"][-1]
    assert set(flags) == set(res["vehicles"]) and all(np.array_equal(flags[v], stage1.failed(r)) and len(flags[v]) == 48 for v, r in res["vehicles"].items())
    flip = json.loads((ctx.run_dir / "emulator" / "flip.json").read_text())["vehicles"]["usv"]
    first = stage1.failed(res["vehicles"]["usv"])[:ctx.plan["batch"]]
    assert flip["base_same"]["n"] == ctx.plan["batch"] and flip["base_same"]["p_fail"] == float(first.mean()) and flip["n"] == 48


def test_m1_an_emulated_answer_needs_no_baseline_run(storm_em, monkeypatch):  # noqa: F811
    calls = fake_batch(monkeypatch)
    em, info = storm_em
    flips, _ = whatif.flip_search(STORM, {GL: dict(verdict="NO-GO", p_fail=0.9, n=64)}, {GL: TRACK}, ENV, {GSC: (em, info)}, plan_for(STORM, 32),
                                  *stage1.priors_for(STORM), None, 5, 1e6, lambda *_: None)
    assert flips[GL]["best"]["method"] == "EMULATED" and flips[GL]["base_same"] is None and calls == []


def test_m1_measure_runs_n_members_in_the_blocks_of_the_sequential_run(monkeypatch):
    """Each block of the sequential run is its own Latin hypercube keyed by its first member: 20 members at a batch of 8 are 0-7, 8-15, 16-19, not one draw."""
    calls = fake_batch(monkeypatch)
    r = whatif.measure(STORM, GL, ENV, plan_for(STORM, 8), *stage1.priors_for(STORM), None, 5, n=20)
    assert calls == [list(range(8)), list(range(8, 16)), list(range(16, 20))] and r["n"] == 20
    calls.clear()
    whatif.measure(STORM, GL, ENV, plan_for(STORM, 8), *stage1.priors_for(STORM), None, 5, members=list(range(48, 56)))
    assert calls == [list(range(48, 56))]                                                         # named members are one batch, as before


def ask(monkeypatch, n_answer, base=BASE):
    """whatif.answer for a deploy shift of STORM's glider answered in Stage 1 with `n_answer` members (the sequential run itself is replaced)."""
    monkeypatch.setattr(whatif, "_stage1", lambda *a, **k: dict(p_fail=4 / n_answer, lo=0.0, hi=0.3, verdict="MARGINAL", n=n_answer))
    return whatif.answer(STORM, dict(shift_h=24.0), base, {GL: TRACK}, ENV, {}, plan_for(STORM, 32), None, None)["vehicles"][GL]


def test_m1_the_cli_answer_compares_with_the_baseline_on_its_own_members(monkeypatch):
    calls = fake_batch(monkeypatch)
    r = ask(monkeypatch, 32)
    assert r["method"] == "Stage 1" and r["n"] == 32 and (r["base"]["p_fail"], r["base"]["n"]) == (5 / 32, 32)
    assert r["base_run"] == BASE[GL] and calls == [list(range(32))]                              # the report's own is kept, to be said beside
    calls.clear()
    r = ask(monkeypatch, 64, base={GL: dict(BASE[GL], n=96)})                                    # a longer sequential answer: the same blocks as it ran
    assert (r["base"]["p_fail"], r["base"]["n"]) == (15 / 64, 64) and calls == [list(range(32)), list(range(32, 64))]


def test_m1_an_answer_of_the_bases_own_size_or_a_base_of_unknown_size_runs_nothing_more(monkeypatch):
    calls = fake_batch(monkeypatch)
    r = ask(monkeypatch, 64)
    assert r["base"] == BASE[GL] and r["base_run"] is None and calls == []
    r = ask(monkeypatch, 32, base={GL: dict(verdict="NO-GO", p_fail=0.9)})                        # a summary without n: nothing to compare the size with
    assert r["base"] == dict(verdict="NO-GO", p_fail=0.9) and r["base_run"] is None and calls == []


def test_m1_the_whatif_command_says_which_baseline_it_prints_and_which_is_the_reports(wi, capsys, monkeypatch):  # noqa: F811
    r = dict(base=dict(verdict="MARGINAL", p_fail=0.156, n=32), base_run=dict(verdict="NO-GO", p_fail=0.234, n=64), method="Stage 1", why="no emulator",
             p_fail=0.125, lo=0.1, hi=0.2, verdict="MARGINAL", n=32)
    monkeypatch.setattr(whatif, "answer", lambda *a, **k: dict(vehicles={"glider_eq": r}, dropped=[], links_removed=[]))
    cli.main(whatif_args(wi, "--shift", "6h"))
    out = capsys.readouterr().out.splitlines()
    assert out[1] == "glider_eq: MARGINAL (P(fail) 0.156) -> MARGINAL (P(fail) 0.125) (0.100 to 0.200)  [Stage 1, n = 32 (no emulator)]"
    assert out[2] == ("  note: glider_eq the baseline shown above is the unchanged mission on the same 32 members as the answer; the report's own "
                      "baseline, of the whole run's 64 members, is NO-GO (P(fail) 0.234).")
    monkeypatch.setattr(whatif, "answer", lambda *a, **k: dict(vehicles={"glider_eq": dict(r, base_run=None)}, dropped=[], links_removed=[]))
    cli.main(whatif_args(wi, "--shift", "6h"))
    assert len(capsys.readouterr().out.splitlines()) == 2


def edit_json(p, fn):
    d = json.loads(p.read_text())
    fn(d)
    p.write_text(json.dumps(d))


def usv_fix(tmp_path, **flip):
    """The synthetic run of tests/fixtures/pm_run with `flip` merged into the USV's entry of flip.json (its best row is a Stage-1 row of n = 16)."""
    run = tmp_path / "run"
    m, plan = pm_run.make_run(run)
    edit_json(run / "emulator" / "flip.json", lambda d: d["vehicles"]["usv"].update(flip))
    report.write(run, m, plan)
    rep = json.loads((run / "report" / "report.json").read_text())
    return rep, plain((run / "report" / "index.html").read_text()), run


def test_m1_the_fix_line_of_a_stage_1_row_is_against_the_baseline_on_its_own_members(tmp_path, data_dir):  # noqa: F811
    rep, t, run = usv_fix(tmp_path, n=64, base_same=dict(verdict="MARGINAL", p_fail=0.125, lo=0.03, hi=0.3, n=16))
    f = rep["vehicles"]["usv"]["fix"]
    assert f["same_members"]["p_fail"]["value"] == 0.125 and f["same_members"]["n_rows"]["value"] == 16 and f["same_members"]["n"]["value"] == 64
    assert "deploy 6 h later: P(fail) 0.125 on the same 16 members becomes 0 " in t and "P(fail) 0.18 becomes" not in t
    assert "compared with the unchanged mission on their own members: MARGINAL P(fail) 0.125 on 16 members. The whole run's P(fail) 0.18, of 64 members." in t
    assert f["best"]["same_as_baseline"] is True and f["tried"][0]["same_as_baseline"] is True       # the row's 0 to 0.14 holds 0.125; the old test used 0.18
    assert rep["traceability_problems"] == [] and report.check_rendered(rep, (run / "report" / "index.html").read_text()) == []


def test_m1_a_baseline_that_was_not_run_is_said_and_the_whole_runs_is_named_as_of_more_members(tmp_path, data_dir):  # noqa: F811
    rep, t, run = usv_fix(tmp_path, n=64, base_same=None)
    assert rep["vehicles"]["usv"]["fix"]["same_members"]["measured"] is False
    assert "deploy 6 h later: P(fail) 0.18 on the whole run of 64 members becomes 0 " in t
    assert "The unchanged mission was not run on the Stage-1 rows' members (this vehicle's share of the Stage-1 budget was spent)" in t
    assert "compared below with the whole run's P(fail) 0.18, of 64 members, which is not of the row's members" in t
    assert rep["traceability_problems"] == [] and report.check_rendered(rep, (run / "report" / "index.html").read_text()) == []


def test_m1_a_flip_json_of_an_earlier_round_renders_as_it_did(tmp_path, data_dir):  # noqa: F811
    rep, t, _ = usv_fix(tmp_path)
    assert rep["vehicles"]["usv"]["fix"]["same_members"] is None and "deploy 6 h later: P(fail) 0.18 becomes 0 " in t and "on their own members" not in t
    rep, t, _ = usv_fix(tmp_path / "e", **{})
    assert rep["vehicles"]["uas"]["fix"]["same_members"] is None                                     # an emulated answer has no Stage-1 row to compare


def test_m1_a_uas_row_is_against_the_baseline_under_the_same_wind_model_and_that_is_printed_once(tmp_path, data_dir):  # noqa: F811
    run = tmp_path / "run"
    m, plan = pm_run.make_run(run)
    same = dict(verdict="NO-GO", p_fail=0.66, lo=0.5, hi=0.8, n=16)
    edit_json(run / "emulator" / "flip.json", lambda d: d["vehicles"]["usv"].update(n=64, base_same=same))      # another vehicle prints the same shape of node
    edit_json(run / "emulator" / "flip.json", lambda d: d["vehicles"]["uas"].update(
        wind_model="UAS what-if answers use the 10 m scaled profile for the candidate and the baseline.", base_2d=same, base_same=same, n=64,
        tried=[dict(t, method="Stage 1", n=16) if t["method"] == "EMULATED" else t for t in d["vehicles"]["uas"]["tried"]],
        best=dict(d["vehicles"]["uas"]["best"], method="Stage 1", n=16)))
    report.write(run, m, plan)
    t = plain((run / "report" / "index.html").read_text())
    assert t.count("The baseline under the same model: NO-GO P(fail) 0.66.") == 1
    assert ("compared with the unchanged mission on their own members: NO-GO P(fail) 0.66 on 16 members. "
            "The whole run's P(fail) 0.7, of 64 members.") in t                                     # (the page prints each node)
    rep = json.loads((run / "report" / "report.json").read_text())
    assert rep["traceability_problems"] == [] and report.check_rendered(rep, (run / "report" / "index.html").read_text()) == []
    assert "P(fail) 0.66 on the same 16 members becomes" in t


# ---- M-3: "of the run", not "of the window" -------------------------------------------------------------------------------------------------------------

def test_m3_the_glider_surfaced_share_is_of_the_run_and_not_of_the_window(full):  # noqa: F811
    run, rep, _ = full
    t = plain((run / "report" / "index.html").read_text())
    assert "it surfaced 0.1111 of the run (the mean over all records and members, not the share of this window)" in t
    sentence = "A glider sees this surface current only while it is at the surface: it surfaced "
    assert t.count(sentence) == 2 and t.count("of the run (the mean over all records and members, not the share of this window); its station loss") == 2
    assert "of the window (mean over members)" not in t and "of the window" not in re.search(r"A glider sees this surface current.*?not this value", t).group(0)
    assert rep["environment"]["forcing_at_windows"]["glider_eq"]["surfaced"]["source"].endswith("(mean over records and members)")   # the number is the same


# ---- M-7: the UAS levels note says where the wind, the antenna and the turbulence box are taken -------------------------------------------------------------

def test_m7_the_levels_note_puts_the_wind_and_the_antenna_at_the_legs_and_the_turbulence_box_at_the_mean_leg_as_stage_1_does(ci_full, monkeypatch):
    P = copy.deepcopy(uas.load_platform("quad_uas"))
    levels = [10.0, 30.0, 60.0, 100.0]
    P["sortie"]["levels_m"] = levels
    seen = []
    real = stage1._fewest_boxes
    monkeypatch.setattr(stage1, "_fewest_boxes", lambda args, M: (seen.append(args[4]), real(args, M))[1])
    t = np.array([config.utc("2023-03-02T01:00:00Z").timestamp()])
    stage1._uas_forcing(ci_full, dict(environment=dict(subgrid=dict(turbulence=True))), (-165.0, 0.0), t, P, 2, 5, [0, 1])
    deck = P["sortie"]["deck_height_m"]
    assert seen == [deck + 50.0]                                                                  # the code: one box at the deck plus the mean leg
    note = report._uas_levels_note(dict(platform="quad_uas", sorties=dict(altitudes_m=levels)))
    assert "so the legs are flown at 18, 38, 68, 108 m above the sea; the wind and the radio antenna height are taken there, and the turbulence box " \
           f"at the one height of the mean leg, {seen[0]:g} m (limitation L20)." in note
    assert "the turbulence box are taken there" not in note
    assert "UAS turbulence is generated at one height for all legs" in next(x for x in report.credibility.LIMITATIONS if x["id"] == "L20")["text"]


# ---- M-5: the link card says so when an RF link has an end below 0.5 m ---------------------------------------------------------------------------------

def rf(a, b, kind="rf"):
    return dict(id="x", kind=kind, a=a, b=b)


def test_m5_an_rf_link_to_the_slocums_0_3_m_antenna_gets_the_sentence_and_the_others_do_not():
    note = report._low_antenna_note(rf("glider_2n", "usv"), DEMO)
    assert note and note.startswith("An end of this RF link has an antenna below 0.5 m: glider_2n (0.3 m).") and "conservative" in note
    assert report._low_antenna_note(rf("usv", "uas"), DEMO) is None                               # 2.2 m and an airborne antenna
    for kind in ("iridium", "acoustic"):
        assert report._low_antenna_note(rf("glider_2n", "usv", kind), DEMO) is None
    assert report._low_antenna_note(rf("ship", "usv"), DEMO) is None                              # the ship is no vehicle: the mission schema's floor is 0.5 m
    # the seaglider's antenna is 0.5 m: not below it, but with the 2.2 m whip the model can understate the loss: the round 18 sentence of that case (M-3)
    assert report._low_antenna_note(rf("glider_eq", "usv"), DEMO).startswith("An end of this RF link has an antenna of 0.5 m: glider_eq (0.5 m).")


def test_m5_the_card_of_such_a_link_prints_it_and_the_report_is_still_traceable(tmp_path, data_dir):  # noqa: F811
    run = tmp_path / "run"
    m, plan = pm_run.make_run(run)
    lid = next(k["id"] for k in m["links"] if k["kind"] == "rf")
    m = copy.deepcopy(m)
    next(k for k in m["links"] if k["id"] == lid).update(a="glider_2n")
    report.write(run, m, plan)
    rep = json.loads((run / "report" / "report.json").read_text())
    t = plain((run / "report" / "index.html").read_text())
    assert rep["links"][lid]["low_antenna"].startswith("An end of this RF link has an antenna below 0.5 m: glider_2n (0.3 m).")
    assert t.count("An end of this RF link has an antenna below 0.5 m") == 1 and rep["traceability_problems"] == []
    assert all(k["low_antenna"] is None for i, k in rep["links"].items() if i != lid)


# ---- M-19 (A-1): the two mutants of round 16's hull-depth note that every test let live -----------------------------------------------------------------

def test_a1_the_depth_in_the_note_is_the_lesser_of_the_dive_depth_and_the_platforms_rating():
    from cafe.pm.physics import glider
    rating = glider.load_platform("seaglider")["rating_m"]
    assert rating == 1000.0
    note = report.hull_depth_note("seaglider", 1500.0)
    assert note and "the glider could not fly 1000 m (" in note and "1500" not in note             # `depth = float(depth_m)` says 1500
    assert "could not fly 950 m" in report.hull_depth_note("seaglider", 950.0)                    # within the rating the order itself is flown


def test_a1_a_dive_candidate_carries_the_depth_it_would_fly_not_the_depth_it_is_a_change_of():
    notes = {c["change"]: c["hull_note"] for c in whatif.candidates(DEMO, "glider_eq") if "duty" in c["mod"]}
    n = next(v for k, v in notes.items() if "712.5 m" in k)
    assert "could not fly 712.5 m (" in n and "950" not in n                                       # without `* c["mod"]["duty"]` the note says 950 m
    n = next(v for k, v in notes.items() if "475 m" in k)
    assert "could not fly 475 m (" in n
