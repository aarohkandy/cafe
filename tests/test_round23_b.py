"""Round 23, batch B: the sentences of the report, the credibility page and the RF documents that were absolutes or grid figures printed as limits, now deleted
(M-1 the Iridium 'cannot miss ... by chance', M-2 the sampling note's worst-case hedge and the card's 'these figures are different', M-4 'up to 7.6 dB' and
'about 8 dB' and 34.7, M-5 the platform names of the ten generic pairs, the '-0.0' median, S-12, S-14 to S-17, S-33, S-40). Each test says what the page must
not say over the whole domain of its input (a constant text is one assertion; a text built from numbers is a grid), never a sentence taken from the code under
test."""
import itertools
import pathlib
import re

import numpy as np
import pytest

from cafe.pm import config, credibility as cr, report
from cafe.pm.physics import comms
from tests.test_round21_b import HEIGHTS, note_of

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOCS = ("docs/CREDIBILITY.md", "docs/PHYSICS.md", "QUESTIONS_FOR_LAB.md")


def flat(path):
    return " ".join((ROOT / path).read_text().split())


def l23():
    return {x["id"]: x for x in cr.LIMITATIONS}["L23"]["text"]


# ------------------------------------------------------------------------------------------------------------------------------------------------- M-1

@pytest.mark.parametrize("required_fraction", [0.1, 0.5, 0.95, 1.0])
def test_m1_the_iridium_note_is_one_text_for_every_link_and_makes_no_claim_about_a_member_missing_by_chance(required_fraction):
    """The note is a constant printed for every Iridium link whatever its required fraction, p_success or attempts: it must not say a member cannot miss the
    required fraction (it can: 10.5 % of members miss one of 865 moments at 0.05^3 per sample, and every one at a required fraction of 1.0)."""
    page = report._iridium_html({"method": "Iridium SBD x", "required_fraction": required_fraction})
    assert page == f"<p class=warn>{report.IRIDIUM_NOTE}</p>"
    for word in ("cannot", "by chance", "never", "hundreds", "1e-90", "impossible"):
        assert word not in report.IRIDIUM_NOTE, word
    assert "restates assumed numbers" in report.IRIDIUM_NOTE and "no evidence about the real service" in report.IRIDIUM_NOTE
    assert report._iridium_html({"method": "two-ray over a 4/3-radius earth", "required_fraction": required_fraction}) == ""


def test_m1_physics_does_not_say_a_member_cannot_miss_5_percent_of_865_samples():
    t = flat("docs/PHYSICS.md")
    assert "cannot miss 5 %" not in t and "1e-90" not in t and "by chance (P(fail)" not in t


# ------------------------------------------------------------------------------------------------------------------------------------------------- M-2

CARD_GONE = ("worst", "larger", "finer", "null", "different", "wave height of 1 to 3 m")


def test_m2_the_sampling_note_is_one_clause_and_names_no_worst_case():
    assert cr.SAMPLING_NOTE == f"These are figures of the {cr.rfband.N_POINTS} sampled ranges" == "These are figures of the 400 sampled ranges"


def test_m2_no_rf_card_over_the_height_grid_says_worst_case_larger_finer_null_or_different(monkeypatch):
    """Every pair of the 22 heights of tests/test_round21_b.py (0.1 to 1,000 m), as two glider-class ends: the card says it is of the 400 sampled ranges and
    none of the words of the deleted hedge (a card for a pair with no null must not warn of one), and nothing about a wave height."""
    for h1, h2 in itertools.combinations_with_replacement(HEIGHTS, 2):
        note = note_of(monkeypatch, ("a", ("glider", h1)), ("b", ("glider", h2)))
        assert "400 sampled ranges" in note and note.endswith("nearer than 300 m this is not stated (CREDIBILITY, limitation L23)."), (h1, h2)
        for word in CARD_GONE:
            assert word not in note, (h1, h2, word)


def test_m2_the_demo_card_and_l23_say_hs_0_in_their_heads_and_l23_has_no_hedge():
    t = l23()
    for word in ("worst", "larger than the median", "finer", "null", "does not stop at any height", "these figures are different"):
        assert word not in t, word
    assert "Hs 0" in t and "These are figures of the 400 sampled ranges" in t


def test_m2_the_documents_do_not_say_the_extremes_keep_growing_or_name_the_stability_figures():
    for path in (*DOCS, "cafe/pm/credibility.py"):
        t = flat(path)
        for gone in ("not of the worst case", "keep growing as the sampling", "a finer sampling of the ranges can find", "at most 0.59 dB", "0.046 of 400",
                     "takes the nulls out of both curves"):
            assert gone not in t, (path, gone)
    doc = " ".join(str(comms.two_ray_curved_db.__doc__).split()) + " ".join(str(comms.two_ray_loss_db.__doc__).split())
    for gone in ("at most 0.52 dB", "up to 5.2 dB", "up to 54.1 dB", "26 dB (29)", "20 dB (34)", "0.8 dB (1.0)", "with Hs 1 m 2.4 dB", "every 5 cm"):
        assert gone not in doc, gone


# ------------------------------------------------------------------------------------------------------------------------------------------------- M-4

def test_m4_no_document_or_docstring_prints_7_6_or_about_8_db_or_34_7_as_a_limit():
    docstring = " ".join(str(comms.two_ray_curved_db.__doc__).split())
    for name, text in [*((p, flat(p)) for p in DOCS), ("comms docstring", docstring)]:
        for gone in ("up to 7.6", "7.6 dB", "within about 8 dB", "34.7", "7.5 dB lower"):
            assert gone not in text, (name, gone)
    for name, text in [("PHYSICS", flat(DOCS[1])), ("comms docstring", docstring)]:
        assert "on that one grid, the Fresnel margin is 7.4 dB lower to 23.6 dB higher" in text, name
    assert "in either direction" in flat(DOCS[0]) and "in either direction" in flat(DOCS[2])


# ------------------------------------------------------------------------------------------------------------------------------------------------- M-5

def test_m5_a_median_that_rounds_to_zero_prints_plus_zero_never_minus_zero():
    """Over every median from -30 to +30 dB in steps of 0.01 (and 0.0, -0.0, +-0.04999, +-0.05): the text is the one-decimal rounding with a '+' or '-', and
    never '-0.0'; for every other median it is exactly what the format printed before round 23."""
    for med in [*np.round(np.arange(-3000, 3001) * 0.01, 2), -0.0, 0.04999, -0.04999, 0.05, -0.05, 0.0499999999, -0.0499999999]:
        text = cr.band_figures(float(med), 0, 0)
        assert "median -0.0" not in text, med
        old = f"median {float(med):+.1f} dB, "
        assert text.startswith("median +0.0 dB, " if old == "median -0.0 dB, " else old), (med, text)


def test_m5_l23_names_no_platform_for_a_generic_pair_and_the_demos_for_its_own_and_says_the_ament_factor():
    t = l23()
    assert not hasattr(cr, "LOW_ANTENNA_NAMES")
    for gone in ("the Slocum", "the Seaglider", "the ship's mast", "the USV's whip", "the lowest height a platform file allows", "(its highest)"):
        assert gone not in t, gone
    assert "0.3 m with 0.3 m median" in t and "the demo's USV whip (2.2 m) and ship mast (15 m)" in t and "108.1 m median" in t
    assert "the same Fresnel two-ray (with the Ament roughness factor in its reflection coefficient) at a wave height of 1, 2 and 3 m" in t


def test_m5_the_l23_cell_of_credibility_md_is_the_text_the_code_prints():
    assert f"| L23 | {l23()} |" in (ROOT / "docs/CREDIBILITY.md").read_text()


def test_m5_end_heights_docstring_says_the_records_hold_the_deck_height():
    doc = " ".join(str(report._end_heights.__doc__).split())
    assert "has `alt` 0 in its records" not in doc and "deck height as its `alt`" in doc
    assert "alt + so[\"deck_height_m\"]" in (ROOT / "cafe/pm/stage1.py").read_text()                  # what the docstring says


# ------------------------------------------------------------------------------------------------------------------------------------------------- S-lines

def test_s12_the_certify_statement_of_an_excluded_p_fail_says_the_bound_and_not_that_no_number_of_members_certifies_it():
    from tests.test_report import stat_block
    for k in (40, 60, 64):                                                  # P(fail) 0.63 and above: the lower 95 % bound is above 5 %
        d = stat_block(k, 64)
        assert d["n_certify"] is None
        assert d["certify_statement"].startswith("P(fail) < 5 % is excluded by this ensemble (lower 95 % bound ") and d["certify_statement"].endswith(").")
        assert "no number" not in d["certify_statement"] and "certifies" not in d["certify_statement"]


@pytest.mark.parametrize("clamp, exc", [(35.0, 42.0), (0.1, 0.2), (89.8, 89.9), (10.0, 89.9), (35.0, 35.0), (42.0, 35.0), (89.9, 0.1)])
def test_s14_the_attitude_statement_says_what_the_controller_does_and_draws_no_conclusion_on_the_verdict(monkeypatch, clamp, exc):
    """For a clamp below the exceedance: the controller clamps the commanded tilt at the clamp (a statement of the code path, uas.py), and nothing more: no
    'cannot fire' and no 'so the verdict rests on' (the achieved tilt is not proved to stay under the clamp for every wind; skeptic pass); for a clamp equal to
    or above it: 'can fire' and no clamp sentence (the equal case is the boundary)."""
    monkeypatch.setattr(report, "_n", lambda n: f"{n['value']:g} deg")
    t = report._attitude_note(dict(tilt_clamp=dict(value=clamp), tilt_exceedance=dict(value=exc)))
    assert "cannot" not in t
    if clamp < exc:
        assert t == f"The controller clamps the commanded tilt at {clamp:g} deg, below the {exc:g} deg attitude exceedance."
    else:
        assert t.startswith("Attitude exceedance can fire in this platform") and "clamps" not in t


def test_s15_l17_says_what_the_controller_clamps_and_not_that_the_mode_cannot_fire():
    x = {x["id"]: x for x in cr.LIMITATIONS}["L17"]
    assert x["text"] == ("in the shipped quad_uas.yaml the UAS controller clamps the commanded tilt at 35 deg, "
                         "below the 42 deg of attitude exceedance") and "cannot" not in x["text"]
    li = config.load_platform("quad_uas")["limits"]
    assert li["max_tilt_deg"]["value"] == 35.0 and li["tilt_exceedance_deg"]["value"] == 42.0
    row = next(l for l in (ROOT / DOCS[0]).read_text().splitlines() if l.startswith("| L17 |"))
    assert "so the UAS verdict" not in row and "the mode fired in 0 members (q5:" in row                  # the measurement, not the inference (skeptic pass)
    for path in (DOCS[0], DOCS[1]):
        assert "it cannot fire in this controller model" not in flat(path) and "attitude exceedance cannot fire" not in flat(path).lower(), path


def test_s16_s17_the_plan_block_has_no_pure_physics_and_no_lower_bound_prefix():
    src = (ROOT / "cafe/pm/report.py").read_text()
    assert "pure physics" not in src and "the plan is a lower bound" not in src


def test_s33_s40_the_documents_do_not_say_the_uncertainty_factor_cannot_reach_3_or_in_exactly_those_sea_states():
    t = flat(DOCS[0])
    for gone in ("cannot reach 3", "in exactly those sea states", "no number of members certifies", "no member count decides"):
        assert gone not in t, gone
    assert "no member count decides" not in " ".join(cr.RULES.values())
    assert "no number of members certifies" not in flat("docs/PHYSICS.md")


def test_the_rules_text_is_the_documents_text():
    """`test_config_docs.py` holds each rule verbatim in CREDIBILITY.md; the deleted clause is gone from both."""
    t = (ROOT / DOCS[0]).read_text().replace("\\|", "|")
    assert cr.RULES["uncertainty"] in t
    assert re.search(r"a link with the verdict NOT EXERCISED is none\) has n >= n_certify", cr.RULES["uncertainty"])
