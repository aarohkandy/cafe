"""Round 19, batch C: the what-if and the command line. One test (or a few) for each finding; each is to fail on the code of 51eb433 (or on its mutant) and
pass with the fix (review/round_19/handbacks/c.md lists the runs). M-10 a `plan.json` with a bad number is the "damaged or incomplete" message, not a traceback
or a silent answer; M-15 the refusal of a duty names the number it refused; M-16 (A-2) the edges of the what-if baseline-from-flags guard in `flip_search`."""
import numpy as np
import pytest

from cafe.pm import __main__ as cli, budget, config, stage1, whatif
from tests.test_cli import wi, whatif_args  # noqa: F401  (wi is a fixture)
from tests.test_round16_report import data_dir  # noqa: F401  (autouse)
from tests.test_round17_a import edit_json
from tests.test_round18_a import Env3D, fake_runs
from tests.test_whatif import ENV, GL, STORM, TRACK, plan_for

pytestmark = pytest.mark.usefixtures("emulator_speed_not_tested")
BOX = config.load_mission(config.ROOT / "missions" / "tepex_c_demo.yaml")["box"]


# ---- M-10: the three sizes of a plan.json are checked where they are read -----------------------------------------------------------------------------

@pytest.mark.parametrize("edit", [dict(batch=0), dict(batch=-8), dict(batch="32"), dict(batch=32.5), dict(batch=True), dict(n_min=500, n_max=10),
                                  dict(n_min=0), dict(n_min=None), dict(n_max="72"), dict(n_max=12.0)])
def test_m10_a_plan_json_with_a_bad_size_is_the_damaged_file_message_and_nothing_is_answered(wi, capsys, edit):  # noqa: F811
    """Each was a ZeroDivisionError from `stage1.wave`, a TypeError, or (n_min above n_max) an answer on member counts the run never had: rc 0."""
    edit_json(wi.run / "plan.json", lambda d: d.update(edit))
    assert cli.main(whatif_args(wi, "--shift", "6h")) == 2
    err = capsys.readouterr().err
    assert err.startswith("error: ") and "damaged or incomplete (ValueError: plan.json has batch " in err and "Traceback" not in err
    assert "run it again (--fresh)" in err and not wi.seen                                         # the same message a missing key gives


def test_m10_the_sizes_a_real_plan_has_are_read_as_they_were(wi):  # noqa: F811
    for sizes in (dict(batch=24, n_min=24, n_max=48), dict(batch=1, n_min=1, n_max=1), dict(batch=32, n_min=32, n_max=32)):      # round 21: n_max <= 64 (quick)
        edit_json(wi.run / "plan.json", lambda d, sizes=sizes: d.update(sizes))
        assert cli.main(whatif_args(wi, "--shift", "6h")) == 0
        assert {k: wi.seen["plan"][k] for k in sizes} == sizes


# ---- M-15: the duty of the refusal is the duty that was refused ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("duty,shown", [(1.0000001, "1.0000001"), (1.00000000001, "1.00000000001"), (1.5, "1.5"), (0.0, "0"), (-0.25, "-0.25"),
                                        (float("nan"), "nan"), (float("inf"), "inf")])
def test_m15_a_duty_that_is_refused_is_printed_so_that_it_differs_from_one(duty, shown):
    """`:g` printed 1.0000001 as 'duty 1 needs ... at most 1'."""
    with pytest.raises(whatif.Invalid) as e:
        whatif._numbers("v", dict(shift_h=0, dlon=0, dlat=0, duty=duty), BOX)
    assert str(e.value) == (f"v: the change shift_h 0, dlon 0, dlat 0, duty {shown} needs finite numbers and a duty above 0 and at most 1")
    assert whatif._numbers("v", dict(duty=1.0), BOX)[3] == 1.0                                       # the largest allowed one is not refused


# ---- M-16 (A-2): the baseline of a Stage-1 row, at the edges of its guard --------------------------------------------------------------------------------

WHOLE = set(range(12)) | set(range(32, 46))        # 26 of 64 fail; the first 32 of them: 12 (MARGINAL)


def search(monkeypatch, flags, share=10.0, cand_fail=range(11)):
    """flip_search of the STORM glider (batch 32, no emulator) with `flags` as the base run's failure flags.
    -> (the glider's entry, the Stage-1 calls, cost)."""
    calls = fake_runs(monkeypatch, WHOLE, set(cand_fail))
    plan = plan_for(STORM, 32)
    cost = budget.batch_cost_s(plan, [GL])
    given = None if flags is None else {GL: np.asarray(flags, bool)}
    flips, _ = whatif.flip_search(STORM, {GL: dict(verdict="NO-GO", p_fail=26 / 64, n=64)}, {GL: TRACK}, ENV, {}, plan, *stage1.priors_for(STORM), None, 5,
                                  share * cost, lambda *_: None, given)
    return flips[GL], calls, cost


def flags_of(n):
    return [i in WHOLE for i in range(n)]


def test_a2_w3a_flags_of_exactly_a_batch_are_a_baseline_and_nothing_is_run_for_it(monkeypatch):
    """`len(flags) > batch` sent a base run with exactly one batch of flags to the measured baseline (a Stage-1 run it did not need)."""
    f, calls, _ = search(monkeypatch, flags_of(32))
    assert f["base_same"]["source"] == whatif.BASE_SAME_FLAGS and f["base_same"]["n"] == 32 and f["base_same"]["p_fail"] == 12 / 32
    assert all(not base for base, _ in calls)                                                       # no run of the unchanged mission


def test_a2_w3b_flags_of_fewer_than_a_batch_are_not_the_batchs_members_and_the_baseline_is_measured(monkeypatch):
    """`len(flags) >= 1` took 10 flags as the baseline of a batch of 32: 'on the same 10 members', for candidates that are run on 32."""
    for n in (1, 10, 31):
        f, calls, cost = search(monkeypatch, flags_of(n))
        assert f["base_same"]["source"] == whatif.BASE_SAME_RUN and f["base_same"]["n"] == 32, n
        assert calls[0] == (True, list(range(32))), n                                                # the baseline is the first batch run


def test_a2_f10_the_members_of_a_baseline_from_flags_are_the_batchs_and_not_the_whole_runs(monkeypatch):
    """`n=len(flags)` printed 'on the same 64 members' for a P(fail) of the first 32."""
    f, calls, _ = search(monkeypatch, flags_of(64))
    assert f["base_same"]["n"] == 32 and f["base_same"]["p_fail"] == 12 / 32 and f["base_same"]["source"] == whatif.BASE_SAME_FLAGS
    assert f["base_same"]["n"] != 64 and calls and all(not base for base, _ in calls)


def test_a2_w6a_a_share_of_exactly_the_baselines_cost_runs_the_baseline(monkeypatch):
    """`used + cost < share` refused a baseline that fits the share to the second."""
    f, calls, cost = search(monkeypatch, None, share=1.0)
    assert f["base_same"] is not None and f["base_same"]["source"] == whatif.BASE_SAME_RUN and calls[0] == (True, list(range(32)))
    f, calls, _ = search(monkeypatch, None, share=0.999)                                                          # a hair short: no baseline, no run
    assert f["base_same"] is None and calls == []


def uas_search(monkeypatch, flags, emulated_fix=False):
    """flip_search of the CI mission's UAS in a 3-D wind with a measure() that records its calls: the base mission is the one that is `ci`."""
    ci = config.load_mission(config.ROOT / "missions" / "ci_fixture.yaml")
    seen = []

    def measure(mission, vid, e, plan, pri, marg, scales, seed, n=None, members=None):
        seen.append(mission is ci)
        base = mission is ci
        return dict(p_fail=0.3 if base else 0.05, lo=0.2, hi=0.4, verdict="MARGINAL" if base else "GO", n=16)
    monkeypatch.setattr(whatif, "measure", measure)
    if emulated_fix:                                                                                  # the emulator answers every candidate with a fix
        monkeypatch.setattr(whatif, "predict", lambda *a, **k: dict(status="ok", p_fail=0.02, lo=0.0, hi=0.1, verdict="GO", distance=0.5, threshold=1.9))
    plan = plan_for(ci, 4)
    cost = budget.batch_cost_s(plan, ["uas"])
    given = None if flags is None else {"uas": np.asarray(flags, bool)}
    flips, _ = whatif.flip_search(ci, {"uas": dict(verdict="NO-GO", p_fail=0.8)}, {}, Env3D(), {}, plan, {}, {}, None, 5, 10 * cost, lambda *_: None, given)
    return flips["uas"], seen


def test_a2_w4_a_uas_in_a_3d_wind_does_not_take_the_base_runs_flags_for_its_baseline(monkeypatch):
    """The base run's flags are of its 3-D wind, a UAS row is flown in the 10 m profile (the code comment, DECISIONS 952): the baseline is measured."""
    f, seen = uas_search(monkeypatch, [False] * 16)                                                  # flags of a full batch (4) and more, all passing
    assert seen[0] is True and f["base_2d"]["source"] == whatif.BASE_SAME_RUN and f["base_2d"]["p_fail"] == 0.3
    assert f["base_same"] is f["base_2d"] and f["target_same"] == "GO"


def test_a2_w7_a_uas_in_a_3d_wind_measures_its_baseline_though_no_stage_1_row_is_run(monkeypatch):
    """With an emulated fix no Stage-1 row is run, but the answer of a UAS states its 2-D baseline: `elif run_s1` alone left it empty."""
    f, seen = uas_search(monkeypatch, None, emulated_fix=True)
    assert f["best"]["method"] == "EMULATED" and seen == [True]                                      # the baseline, and no candidate
    assert f["base_2d"] is not None and f["base_2d"]["source"] == whatif.BASE_SAME_RUN and f["base_2d"]["verdict"] == "MARGINAL"
