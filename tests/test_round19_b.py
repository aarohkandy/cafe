"""Round 19, batch B: the link card's antenna-pair lookup (M-2; round 21, M-2: the card computes the pair's band live, so the tests of the row
lookup, its tolerance and the nearest-row sentences were replaced, see tests/test_round21_b.py), the sea state of its figures (M-3), the fix line of an older
`flip.json` (M-4),
`same_members.measured` (M-13) and the tests of surviving mutants of the fix line (A-3) and the credibility lines (A-4). One regression test per fix, each
seen to fail on 51eb433 (M-2 to M-4, M-13) or to kill the mutation it names (A-3, A-4: the reviewer's mutants were written against the code they read; each
test was run against the equivalent mutation of the fixed code, see the hand-back).
The references are written here from the Fresnel coefficient, never from the code under test (the helpers of tests/test_round17_d.py and test_round18_b.py)."""
import numpy as np
import pytest

from cafe.pm import config, credibility as cr, report, whatif
from cafe.pm.physics import ANTENNA_MIN_M, comms, uas, usv
from tests.test_credibility import _Facts, vrow
from tests.test_round16_report import data_dir  # noqa: F401  (autouse)
from tests.test_round17_a import usv_fix
from tests.test_round17_d import F915
from tests.test_round18_a import NO_GO_RUN, flip_report
from tests.test_round18_x import card
from tests.test_round22_b import figs

ROOT = config.ROOT
DEMO = config.load_mission(ROOT / "missions" / "tepex_c_demo.yaml")


def l23():
    return {x["id"]: x for x in cr.LIMITATIONS}["L23"]["text"]


# ------------------------------------------------------------------------------------------------------------------------------- M-2: the lookup

@pytest.mark.parametrize("h, row", [(0.30000000000000004, "0.3 m with 15 m"), (0.3000001, "0.3 m with 15 m"), (0.5000001, "0.5 m with 15 m"),
                                    (0.4999999, "0.5 m with 15 m")])
def test_m2_a_height_a_rounding_off_a_row_is_that_row(h, row, monkeypatch):
    """0.5000001 m printed no card at all (the step at 0.5 m behind an exact match), 0.30000000000000004 and 0.4999999 m printed 'not among those measured'
    for a pair the table has: the antenna and its error are the row's to a fraction of a decibel."""
    note = card(h, 15.0, monkeypatch)
    assert note and f"({row})" in note and figs(h, 15.0) in note and "not among those measured" not in note


def test_m2_a_height_off_a_row_is_printed_as_it_is_and_with_its_own_live_figures(monkeypatch):
    """Round 21, M-2: the card no longer reads a height as the nearest row ('read as the measured 0.3 m with 15 m', which needed a 0.001 m tolerance): it prints
    the height it has and the band of that pair, computed (round 22: its median and counts, the independent reference's for 0.3004 m)."""
    note = card(0.3004, 15.0, monkeypatch)
    assert f"for this pair of heights (0.3004 m with 15 m): {figs(0.3004, 15.0)}" in note and "read as" not in note
    assert "for this pair of heights (0.3 m with 15 m)" in card(0.3, 15.0, monkeypatch)


def test_m2_a_height_just_above_0_5_m_or_off_a_row_is_not_silence_and_not_another_pairs_figures(monkeypatch):
    """0.51 m (a lab's CAD height for the Seaglider's assumed 0.5 m) printed nothing, and 0.3 m beside 0.52 m was 'not among those measured'. Round 21, M-2:
    every one of them prints its own live figures (the band of that pair, from `rfband.pair_band`, which tests/test_round21_b.py holds to the independent
    reference), no sentence about a nearest row, and no height is a cliff: 0.55 m, 2.3 m and 5 m print too."""
    for a, b in ((0.51, 15.0), (0.3, 0.52), (0.302, 0.5), (0.55, 15.0), (0.5501, 15.0), (2.3, 15.0), (5.0, 15.0), (0.105, 15.0), (0.4, 15.0), (0.45, 15.0)):
        note = card(a, b, monkeypatch)
        assert note and "not among those measured" not in note and "nearest measured pair" not in note and "envelope" not in note, (a, b)
        assert f"for this pair of heights ({min(a, b):g} m with {max(a, b):g} m): {figs(a, b)}" in note, (a, b, note)
        assert note.endswith("(CREDIBILITY, limitation L23).")


def test_m2_a_ship_without_a_height_is_the_height_stage_1_used_and_not_no_single_height(monkeypatch):
    """`stage1.ship_antenna_m` is 10 m for a mission without `ship.antenna_height_m`; the card said 'ship (no single height)' (and a mutant that read it as 15 m
    would have printed a band). With a UAS in the mission the fallback is its platform's `radio.ship_antenna_height_m` (as `evaluate_link` picks it), and the
    mission's own height wins over both."""
    mission = dict(vehicles=[dict(id="g", platform="seaglider")], ship=dict(id="ship"))
    lk = dict(kind="rf", when="uas_airborne", a="g", b="ship")
    note = report._low_antenna_note(lk, mission)
    assert "no single height" not in note and f"for this pair of heights (0.5 m with 10 m): {figs(0.5, 10.0)}" in note
    with_uas = dict(mission, vehicles=[*mission["vehicles"], dict(id="u", platform="quad_uas", base="ship")])
    assert "(0.5 m with 10 m)" in report._low_antenna_note(lk, with_uas)                                    # the platform file's own 10 m
    monkeypatch.setattr(uas, "load_platform", lambda *a: dict(radio=dict(ship_antenna_height_m=15.0)))
    note = report._low_antenna_note(lk, with_uas)                                                           # a UAS platform that says 15 m: the measured pair
    assert figs(0.5, 15.0) in note and "(0.5 m with 15 m)" in note
    assert "(0.5 m with 0.52 m)" in report._low_antenna_note(lk, dict(with_uas, ship=dict(id="ship", antenna_height_m=0.52)))


def test_m2_the_demos_heights_l23_names_are_the_platform_files_heights():
    """PE11: the names of 0.3 m and 0.5 m swapped, every figure right. Round 23, S-8: L23 names no platform for the ten generic pairs (they print for every
    mission) and names the demo's USV whip and ship mast only in the paragraph of the demo's UAS pairs; those two heights are tied to the files they name."""
    assert usv.load_platform("saildrone_explorer")["rf_antenna_height_m"] == 2.2 and ANTENNA_MIN_M == 0.1
    assert DEMO["ship"]["antenna_height_m"] == 15.0
    assert "the demo's USV whip (2.2 m) and ship mast (15 m)" in l23() and not hasattr(cr, "LOW_ANTENNA_NAMES")
    for gone in ("the Slocum", "the Seaglider", "the ship's mast", "the USV's whip", "the lowest height a platform file allows"):
        assert gone not in l23(), gone


# ------------------------------------------------------------------------------------------------------------------------------- M-3: Hs 0

def fresnel_hs(d, ht, hr, hs, f_hz=F915, eps_r=72.8, sigma=6.05):
    """The flat-earth Fresnel two-ray of tests/test_round17_d.py with the sea's roughness on the reflection coefficient: rho = exp[-2 (2 pi s sin psi / lam)^2],
    s = Hs / 4 (Ament 1953), written here."""
    lam = comms.C0 / f_hz
    eps = eps_r - 1j * 60.0 * sigma * lam
    r1, r2 = np.hypot(d, ht - hr), np.hypot(d, ht + hr)
    psi = np.arctan2(ht + hr, d)
    root = np.sqrt(eps - np.cos(psi) ** 2)
    refl = (eps * np.sin(psi) - root) / (eps * np.sin(psi) + root)
    rho = np.exp(-2.0 * (2.0 * np.pi * (hs / 4.0) * np.sin(psi) / lam) ** 2)
    field = np.abs(1.0 + rho * refl * (r1 / r2) * np.exp(-2j * np.pi * (r2 - r1) / lam))
    return 20.0 * np.log10(4.0 * np.pi * r1 / lam) - 20.0 * np.log10(field)


def band_hs(hr, ht, hs):
    d = np.linspace(300.0, min(float(comms.radio_horizon_km(ht, hr)) * 1e3, 12e3), 400)
    diff = comms.two_ray_loss_db(d, ht, hr, hs, F915) - fresnel_hs(d, ht, hr, hs)
    return float(diff.min()), float(np.median(diff)), float(diff.max())


def test_m3_the_card_says_the_figures_are_for_hs_0(monkeypatch):
    """The card printed the table as 'its loss minus the Fresnel loss is +11.4 to +16.0 dB' with no sea state; at Hs 2 m the 0.1 m pair's minimum is +6.1."""
    for h in (0.1, 0.3, 0.5):
        note = card(h, 15.0, monkeypatch)
        assert ("against a Fresnel two-ray at Hs 0 (a calm sea) at 915 MHz, over 400 evenly spaced ranges from 300 m to the pair's radio horizon or 12 km, "
                "the model's loss minus the Fresnel loss is described by its median and by how many of the sampled ranges are more than 3 dB off" in note), h
        assert "at a wave height of 1 to 3 m" not in note and "these figures are different" not in note, h        # round 23, S-4: the head names Hs 0
        assert note.endswith("nearer than 300 m this is not stated (CREDIBILITY, limitation L23).")


def test_m3_l23_prints_the_hs_1_to_3_figures_of_the_15_m_pairs_to_0_1_db():
    for pair, by_hs in cr.LOW_ANTENNA_HS_BAND.items():
        assert pair in comms.LOW_ANTENNA_PAIR_BAND and sorted(by_hs) == [1, 2, 3]
        for hs, printed in by_hs.items():
            got = band_hs(pair[1], pair[0], float(hs))
            assert all(abs(g - p) <= 0.1 for g, p in zip(got, printed, strict=True)), (pair, hs, got, printed)
            assert f"at Hs {hs} m {printed[0]:+.1f} to {printed[2]:+.1f} dB (median {printed[1]:+.1f})" in l23()
    assert all(abs(g - p) <= 0.1 for g, p in zip(band_hs(15.0, 0.5, 0.0), comms.LOW_ANTENNA_PAIR_BAND[(0.5, 15.0)], strict=True))      # Hs 0 is the table
    assert "(measured; the other pairs were not measured above Hs 0)" in l23()


# ------------------------------------------------------------------------------------------------------------------------------- M-4: older flip.json

OLD_SAME = dict(verdict="MARGINAL", p_fail=0.375, lo=0.23, hi=0.55, n=32)


def test_m4_an_older_flip_json_whose_same_members_verdict_differs_from_the_whole_runs_prints_the_same_members_verdict(tmp_path):
    """A round-17 flip.json (`base_same`, no `target_same`) printed 'P(fail) 0.375 on the same 32 members ... NO-GO to GO': the MARGINAL baseline's P(fail)
    beside the whole run's verdict, the pair round 18 M-1 closed for new files."""
    rep, t, run = flip_report(tmp_path, base_same=OLD_SAME, **NO_GO_RUN)
    assert rep["vehicles"]["usv"]["fix"]["target_same"] is None
    assert ("deploy 6 h later: P(fail) 0.375 on the same 32 members becomes 0 (0 to 0.14, Wilson interval (Stage 1)), "
            "MARGINAL (whole run: NO-GO) to GO (Stage 1, n = 16 members)") in t and "NO-GO to GO" not in t
    assert "What would fix it (GO or MARGINAL): " in t                                    # no target_same: the whole run's target, and the page says so
    assert ("A Stage-1 row is judged against the whole run's target, GO or MARGINAL: this file, made by an older round, does not record the target of the "
            "rows' own members.") in t and "A Stage-1 row is a fix when" not in t
    assert rep["traceability_problems"] == [] and report.check_rendered(rep, (run / "report" / "index.html").read_text()) == []


def test_m4_an_older_flip_json_whose_two_verdicts_agree_prints_one_badge(tmp_path):
    _, t, _ = flip_report(tmp_path, base_same=dict(OLD_SAME, verdict="NO-GO"), **NO_GO_RUN)
    assert "NO-GO to GO (Stage 1, n = 16 members)" in t and "whole run:" not in t


# ------------------------------------------------------------------------------------------------------------------------------- M-13: measured

@pytest.mark.parametrize("source, shown, measured", [(whatif.BASE_SAME_FLAGS, whatif.BASE_SAME_FLAGS, False),
                                                      (whatif.BASE_SAME_RUN, whatif.BASE_SAME_RUN, True),
                                                      ('<b>weird</b> & "x"', '<b>weird</b> & "x"', None), ("", "", None),
                                                      (5, None, None), (["a"], None, None), ({"a": 1}, None, None), (None, None, None)])
def test_m13_measured_is_from_the_two_phrases_and_anything_else_is_not_known(tmp_path, source, shown, measured):
    """`measured` was `source == BASE_SAME_RUN`: an unknown phrase was False (not run), and a non-string `source` put a number or a list in the report and
    made `report --run` fail its ledger check."""
    rep, _, run = flip_report(tmp_path, base_same=dict(OLD_SAME, source=source), n=64)
    sm = rep["vehicles"]["usv"]["fix"]["same_members"]
    assert sm["available"] is True and sm["source"] == shown and sm["measured"] is measured
    assert rep["traceability_problems"] == [] and report.check_rendered(rep, (run / "report" / "index.html").read_text()) == []


def test_m13_a_baseline_that_was_not_run_is_not_measured_whatever_the_source(tmp_path):
    rep, _, _ = flip_report(tmp_path, base_same=None, n=64)
    sm = rep["vehicles"]["usv"]["fix"]["same_members"]
    assert sm["available"] is False and sm["measured"] is False and sm["source"] is None


# ------------------------------------------------------------------------------------------------------------------------------- A-3: the fix line

EMULATED = dict(change="launch 6 h later", mod=dict(shift_h=6.0), cost=1.0, method="EMULATED", reason="", p_fail=0.04, lo=0.01, hi=0.09, verdict="GO",
                distance=0.8, threshold=1.9)
STAGE1 = dict(change="deploy 6 h later", mod=dict(shift_h=6.0), cost=1.0, method="Stage 1", reason="", p_fail=0.0, lo=0.0, hi=0.14, verdict="GO", n=16)
SAME = dict(verdict="MARGINAL", p_fail=0.125, lo=0.03, hi=0.3, n=32)


def test_a3_fh8_an_emulated_best_row_is_beside_the_whole_runs_p_fail_not_the_same_members(tmp_path):
    """FH8: with `sm` read for an EMULATED best row the line said 'P(fail) 0.125 on the same 32 members' beside an answer the emulator gave for the whole
    run."""
    rep, t, _ = flip_report(tmp_path, best=EMULATED, tried=[STAGE1, EMULATED], base_same=SAME, target_same="GO", n=64)
    assert rep["vehicles"]["usv"]["fix"]["best"]["method"] == "EMULATED"
    assert ("launch 6 h later: P(fail) 0.18 becomes 0.04 (0.01 to 0.09, conformal 90 % interval (emulator)), "
            "MARGINAL to GO (EMULATED, training-set distance 0.8 z-scored of 1.9 z-scored).") in t
    assert "whole run:" not in t.split("The Stage-1 rows are compared")[0]


def test_a3_fh6_the_whole_run_is_named_with_its_member_count_when_the_baseline_was_not_run(tmp_path):
    _, t, _ = flip_report(tmp_path, base_same=None, n=64)
    assert "deploy 6 h later: P(fail) 0.18 on the whole run of 64 members becomes 0 " in t
    _, t, _ = flip_report(tmp_path / "n", base_same=None, n=None)
    assert "deploy 6 h later: P(fail) 0.18 on the whole run becomes 0 " in t


def test_a3_fh9_the_interval_of_the_same_members_p_fail_is_its_own_lo_and_hi(tmp_path):
    rep, _, _ = flip_report(tmp_path, base_same=OLD_SAME, n=64)
    u = rep["vehicles"]["usv"]["fix"]["same_members"]["p_fail"]["uncertainty"]
    assert (u["lo"], u["hi"], u["kind"]) == (0.23, 0.55, "Wilson interval (Stage 1)")


def test_a3_fh10_a_row_is_the_baseline_when_its_interval_holds_the_baseline_it_was_judged_against(tmp_path):
    """A Stage-1 row's baseline is the same-members one (0.125), an emulated row's is the whole run's (0.18): the flag is tested against each."""
    holds_same, holds_whole = dict(STAGE1, lo=0.1, hi=0.15), dict(STAGE1, lo=0.17, hi=0.2)
    rep, _, _ = usv_fix(tmp_path, best=holds_same, tried=[holds_same, holds_whole], base_same=SAME, target_same="GO", n=64)
    assert [x["same_as_baseline"] for x in rep["vehicles"]["usv"]["fix"]["tried"]] == [True, False]
    em_whole, em_same = dict(EMULATED, lo=0.17, hi=0.2), dict(EMULATED, lo=0.1, hi=0.15)
    rep, _, _ = usv_fix(tmp_path / "em", best=em_whole, tried=[em_whole, em_same], base_same=SAME, target_same="GO", n=64)
    assert [x["same_as_baseline"] for x in rep["vehicles"]["usv"]["fix"]["tried"]] == [True, False]


def test_a3_sm9_a_flip_json_without_base_same_says_nothing_of_a_same_members_baseline(tmp_path):
    rep, t, _ = flip_report(tmp_path)
    assert rep["vehicles"]["usv"]["fix"]["same_members"] is None
    assert "was not run on the Stage-1 rows' members" not in t and "on the whole run" not in t and "on the same" not in t


# ------------------------------------------------------------------------------------------------------------------------------- A-4: credibility

def test_a4_k4_the_validated_count_is_over_the_judged_rows():
    """K4: counted over every row with all terms, a row that is not judged but carries a `validated` of True raised the count above the judged rows'."""
    not_judged = dict(vrow(3), not_judged="not judged: the finest grid has not converged")
    lvl, ev, _ = cr._validation(_Facts([vrow(0), vrow(1), vrow(2), not_judged]))
    assert lvl == 2 and "of the 3 judged, 3 with |E| <= U_val and 3 with U_val below 50% of the reference" in ev[0]["what"]


def test_a4_k7b_a_row_whose_uval_is_half_the_reference_blocks_level_3_beside_four_others_that_pass():
    wide = cr._row("w", "c", "s", 1.0, 1.0, (0.6, 0.6, 0.6), "")
    assert wide["validated"] and not wide["informative"]
    lvl, _, miss = cr._validation(_Facts([vrow(i) for i in range(4)] + [wide]))
    assert lvl == 2 and "U_val is 50% of the reference or more in ['w']: an uncertainty that wide cannot validate it" in " ".join(miss)
    assert cr._validation(_Facts([vrow(i) for i in range(4)]))[0] == 3


def test_a4_k12a_a_value_fitted_from_data_is_counted_neither_used_nor_unused():
    items = [dict(kind="assumed", file="a.yaml", used=True), dict(kind="assumed", file="a.yaml", used=False), dict(kind="fitted", file="a.yaml", used=True),
             dict(kind="fitted", file="b.yaml", used=False), dict(kind="prior", file="b.yaml", used=True)]
    assert cr.used_counts(items) == ({"a.yaml": 1, "b.yaml": 1}, {"a.yaml": 1})
