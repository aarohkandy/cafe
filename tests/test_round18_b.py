"""Round 18, batch B: the error band of the two-ray -1 reflection by pair of antenna heights (M-3: the text of L23 and the docstring of `two_ray_curved_db`) and
the tests of the surviving mutants of the inside-the-horizon interpolation of `smooth_earth_diffraction_db` (M-16, A-1). The references are written here from
the Fresnel coefficient and from ITU-R P.452's interpolation (the helpers of tests/test_round17_d.py), never from the code under test."""
import math

import numpy as np
import pytest
import yaml

from cafe.pm import config, credibility as cr
from cafe.pm.physics import comms as c, glider, usv
from tests.test_round17_d import fresnel_loss_db, ref_beyond

F915 = 915e6
LAM = c.C0 / F915
A_KM = c.A_EFF / 1e3


def doc_of(fn):
    return " ".join(fn.__doc__.split())


def l23():
    return {x["id"]: x for x in cr.LIMITATIONS}["L23"]["text"]


# ---------------------------------------------------------------------------------------------------------------- M-3: the band is of the pair
# (higher antenna, lower antenna) -> model loss minus the Fresnel loss, minimum / median / maximum [dB], as the docstring of two_ray_curved_db prints them to
# 0.1 dB. ONE range for every row: d = 300 m to the pair's radio horizon or 12 km, whichever is nearer, 400 points (measured on orca: Hs 0, 915 MHz,
# eps_c 72.8 - j118.9). The round 18 first draft gave the 15 m rows from 300 m and the others from 200 m, and "within 3.3 dB" was then false.
PAIR_BAND = {
    (15.0, 2.2): (-3.3, -0.4, 0.2),
    (15.0, 0.5): (-2.9, 1.3, 2.2),
    (15.0, 0.3): (1.2, 5.1, 6.0),
    (15.0, 0.1): (11.4, 15.1, 16.0),
    (0.5, 0.3): (9.0, 9.3, 9.3),
    (0.3, 0.3): (11.3, 11.4, 11.4),
    (0.5, 0.5): (6.4, 6.7, 6.7),
    (2.2, 0.3): (5.5, 6.2, 6.2),
    (2.2, 0.5): (1.8, 2.6, 2.7),
    (2.2, 2.2): (-2.4, -1.2, 1.6),
}
BOUND_PAIRS = [(15.0, 2.2), (15.0, 0.5), (2.2, 0.5), (2.2, 2.2)]            # "0.5 m or 2.2 m with a 2.2 m or 15 m partner"
BOTH_LOW = [(0.5, 0.3), (0.3, 0.3), (0.5, 0.5)]                                # "both ends 0.5 m or lower"
SLOCUM_PARTNER_2_2_OR_MORE = [(15.0, 0.3), (2.2, 0.3)]


def band(hr, ht, d0=300.0):
    """The model's loss minus the Fresnel loss from d0 to the pair's radio horizon or 12 km (the nearer), 400 points: (minimum, median, maximum)."""
    d = np.linspace(d0, min(float(c.radio_horizon_km(ht, hr)) * 1e3, 12e3), 400)
    diff = c.two_ray_loss_db(d, ht, hr, 0.0, F915) - fresnel_loss_db(d, ht, hr)
    return float(diff.min()), float(np.median(diff)), float(diff.max())


@pytest.mark.parametrize("pair", sorted(PAIR_BAND, key=lambda k: (-k[0], -k[1])))
def test_r18_m3_the_docstring_figures_of_every_pair_are_the_measured_ones(pair):
    """Round 17 measured the band with a 15 m partner only and wrote it as a property of the low antenna: two gliders are 6 to 11 dB off, not 5."""
    got, printed = band(*pair), PAIR_BAND[pair]
    for g, p in zip(got, printed, strict=True):
        assert abs(g - p) <= 0.1, (pair, got)
    assert f"{printed[0]:+.1f} / {printed[1]:+.1f} / {printed[2]:+.1f}" in doc_of(c.two_ray_curved_db), pair


def test_r18_m3_the_bound_sentences_are_true_over_the_stated_range():
    """L23 and the docstring: 'within 3.3 dB and at worst understates the loss' for 0.5 m and 2.2 m with a 2.2 m or 15 m partner; '6 to 11 dB' when both
    ends are 0.5 m or lower; 'about 5 dB (1 to 6 dB)' for the Slocum with a partner of 2.2 m or more; '11 to 16 dB' at 0.1 m. All over 300 m to the horizon
    or 12 km, the range the texts state. A bound that its own figures exceed is the fault this finding was about."""
    mins, maxs = zip(*(band(*pair)[::2] for pair in BOUND_PAIRS), strict=True)
    assert -3.35 < min(mins) < -3.25 and max(abs(m) for m in mins + maxs) < 3.35                # 3.3 dB: the worst is 2.2 m with a 15 m partner
    assert sorted(round(-m, 1) for m in mins if m < 0.0) == [2.4, 2.9, 3.3]                    # understated by 2.4, 2.9 and 3.3 dB; the 2.2 / 0.5 pair is over
    lows, highs = zip(*(band(*pair)[::2] for pair in BOTH_LOW), strict=True)
    assert round(min(lows)) == 6 and round(max(highs)) == 11
    lows, highs = zip(*(band(*pair)[::2] for pair in SLOCUM_PARTNER_2_2_OR_MORE), strict=True)
    assert round(min(lows)) == 1 and round(max(highs)) == 6 and 5.0 <= band(2.2, 0.3)[1] <= 6.5
    assert round(band(15.0, 0.1)[0]) == 11 and round(band(15.0, 0.1)[2]) == 16
    doc = doc_of(c.two_ray_curved_db)                                             # the round 18 addendum (DECISIONS 991): L23 prints each pair's own figures
    for text in ("6 to 11 dB for two gliders", "about 1 to 6 dB for the Slocum", "11 to 16 dB at 0.1 m"):
        assert text in doc, text
    assert "within 3.3 dB" not in doc and "within 3.3 dB" not in l23()           # the pooled bound was wrong for 0.5 m with a 2.2 m partner


def test_r18_m3_below_300_m_is_said_not_to_be_stated_and_the_200_m_figures_are_the_measured_ones():
    """Both texts say nothing is stated nearer than 300 m, and print what 200 m gives: 0.5 m with a 15 m partner -5.0 dB at the minimum (the 3.3 dB bound does
    not hold there), 0.3 m with a 15 m partner -0.6 dB, and a +31.9 dB maximum at one null for 2.2 m with a 15 m partner."""
    assert round(band(15.0, 0.5, 200.0)[0], 1) == -5.0 < -3.3
    assert round(band(15.0, 0.3, 200.0)[0], 1) == -0.6
    assert round(band(15.0, 2.2, 200.0)[2], 1) == 31.9
    doc = doc_of(c.two_ray_curved_db)
    for text in ("Below 300 m none of this is stated", "understated by up to 5.0 dB", "by up to 0.6 dB", "+31.9 dB at one null"):
        assert text in doc, text
    assert "nearer than 300 m none of this is stated (from 200 m, 0.5 m with a 15 m partner is understated by up to 5.0 dB)" in l23()
    assert "from 300 m to the pair's radio horizon or 12 km" in l23() and "300 m to the pair's radio horizon or to 12 km" in doc


def test_r18_m3_the_shipped_antennas_are_the_ones_the_pairs_name():
    """0.3 m is the Slocum's, 0.5 m the Seaglider's, 2.2 m the USV's whip; the loader accepts an RF link between two gliders (the premise of 6 to 11 dB)."""
    assert glider.load_platform("slocum")["antenna_height_m"] == 0.3 and glider.load_platform("seaglider")["antenna_height_m"] == 0.5
    assert usv.load_platform("saildrone_explorer")["rf_antenna_height_m"] == 2.2


def test_r18_m3_the_loader_accepts_an_rf_link_whose_two_ends_are_gliders(tmp_path):
    m = yaml.safe_load((config.ROOT / "missions" / "tepex_c_demo.yaml").read_text())
    m["links"].append(dict(id="gg-rf", a="glider_eq", b="glider_2n", kind="rf", radio="rfd900x", when="surfacing", required_fraction=0.5))
    f = tmp_path / "gg.yaml"
    f.write_text(yaml.safe_dump(m))
    assert {lk["id"] for lk in config.load_mission(f)["links"]} >= {"gg-rf"}


def test_r18_m3_l23_states_the_band_by_pair_and_drops_never_too_high_and_not_affected():
    t = l23()
    assert t.startswith("RF links to a low antenna, an antenna below 0.5 m or the USV's 2.2 m whip:")
    assert "antenna below 0.5 m" in t and "the error is of the pair of heights and has no one direction" in t
    assert "margin too low" in t and "margin too high" in t and "MARGINAL or NO-GO" in t and "is not measured and no band is stated for it" in t
    for gone in ("never too high", "not affected", "are not affected", "is conservative", "a margin there is conservative", "above 0.5 m and", "within 3.3 dB",
                 "at worst understates"):
        assert gone not in t, gone
    x = {x["id"]: x for x in cr.LIMITATIONS}["L23"]
    assert x["factors"] == ["validation"] and all((cr.ROOT / w).is_file() for w in x["where"])
    assert [y["id"] for y in cr.LIMITATIONS][-2:] == ["L22", "L23"]


def test_r18_m3_l23_medians_are_those_of_the_pairs_it_names():
    import re
    for pair in ((0.5, 0.5), (0.3, 0.5), (0.3, 0.3)):
        m = re.search(rf"(?<![\d.]){pair[0]:g} m \([^)]*\) with {pair[1]:g} m \([^)]*\) [+-][\d.]+ to [+-][\d.]+ dB \(median ([+-][\d.]+)\)", l23())
        assert m and abs(float(m.group(1)) - band(pair[1], pair[0])[1]) <= 0.1, pair


def test_r18_m3_the_docstring_has_no_conservative_for_all_and_no_unaffected_shipped_antenna():
    doc = doc_of(c.two_ray_curved_db)
    for gone in ("are not affected", "(the conservative direction", "12 to 16 dB at 0.1 m", "at worst UNDERSTATES the loss: by 2.9 dB"):
        assert gone not in doc, gone
    assert "never too high, over this range for the pairs 0.1 / 15, 0.3 / 15" in doc  # 'never too high' is said of the pairs whose minimum is positive only
    for text in ("LOW ANTENNAS", "both ends low", "the PAIR of heights", "11 to 16 dB at 0.1 m", "UNDERSTATED", "the USV's whip",
                 "about 1 to 6 dB for the Slocum with a partner of 2.2 m or 15 m", "6 to 11 dB for two gliders"):
        assert text in doc, text


# ------------------------------------------------------------------------------------- M-16, A-1: the interpolation inside the radio horizon
def ref_inside(d_m, ht, hr, f_hz=F915):
    """ITU-R P.452's line-of-sight interpolation of the P.526 smooth-earth diffraction loss (scalar): a_em = 500 (d / (sqrt ht + sqrt hr))^2 km,
    c = (ht - hr) / (ht + hr), m = 250 d^2 / (a (ht + hr)), b = 2 sqrt((m + 1) / 3m) cos[pi/3 + arccos(3c/2 sqrt(3m / (m + 1)^3)) / 3], d1 = d (1 + b) / 2,
    d2 = d - d1, h_se = [(ht - 500 d1^2 / a) d2 + (hr - 500 d2^2 / a) d1] / d, h_req = 17.456 sqrt(d1 d2 lambda / d); the loss is (1 - h_se / h_req) times
    the diffraction loss over a_em, 0 for h_se > h_req and never negative; beyond d_los = sqrt(2 a) (sqrt ht + sqrt hr) (heights in km) the diffraction loss
    over the 4/3 earth, never negative. Returns the loss and the factor (1 - h_se / h_req) (None beyond the horizon)."""
    d, lam, f_mhz = d_m / 1e3, c.C0 / f_hz, f_hz / 1e6
    d_los = math.sqrt(2.0 * A_KM) * (math.sqrt(ht / 1e3) + math.sqrt(hr / 1e3))
    if d >= d_los:
        return max(ref_beyond(A_KM, d, f_mhz, ht, hr, 72.8, 6.05), 0.0), None
    cc = (ht - hr) / (ht + hr)
    m = 250.0 * d * d / A_KM / (ht + hr)
    b = 2.0 * math.sqrt((m + 1.0) / 3.0 / m) * math.cos(math.pi / 3.0 + math.acos(max(-1.0, min(1.0, 1.5 * cc * math.sqrt(3.0 * m / (m + 1.0) ** 3)))) / 3.0)
    d1 = 0.5 * d * (1.0 + b)
    d2 = d - d1
    h_se = ((ht - 500.0 * d1 * d1 / A_KM) * d2 + (hr - 500.0 * d2 * d2 / A_KM) * d1) / d
    h_req = 17.456 * math.sqrt(d1 * d2 * lam / d)
    if h_se > h_req:
        return 0.0, 1.0 - h_se / h_req
    a_em = 500.0 * (d / (math.sqrt(ht) + math.sqrt(hr))) ** 2
    return (1.0 - h_se / h_req) * max(ref_beyond(a_em, d, f_mhz, ht, hr, 72.8, 6.05), 0.0), 1.0 - h_se / h_req


def d_los_m(ht, hr):
    return 1e3 * math.sqrt(2.0 * A_KM) * (math.sqrt(ht / 1e3) + math.sqrt(hr / 1e3))


PAIRS = [(2.2, 18.1), (10.0, 18.1), (2.2, 108.1), (0.3, 2.2), (2.2, 8.0)]


@pytest.mark.parametrize("fraction", [0.3, 0.6, 0.9, 0.998])
@pytest.mark.parametrize("pair", PAIRS)
def test_r18_m16_a1_inside_the_horizon_the_loss_is_the_p452_interpolation_to_1e_9_db(pair, fraction):
    """`250.0` read `249.0` and `17.456` read `17.5` and neither moved a test: the five-pair Fock tolerance is 2.8 dB."""
    d = fraction * d_los_m(*pair)
    want, _ = ref_inside(d, *pair)
    assert float(c.smooth_earth_diffraction_db(d, *pair, F915)) == pytest.approx(want, abs=1e-9)


def test_r18_m16_a1_the_inside_branch_is_not_all_zero_for_the_pairs_pinned():
    """Guards the test above: at 0.9 of the horizon every pair has a loss of 14 dB or more, so a constant cannot hide in the zero of `h_se > h_req`."""
    assert all(ref_inside(0.9 * d_los_m(*p), *p)[0] > 14.0 for p in PAIRS)


@pytest.mark.parametrize("fraction", [1.002, 1.004, 1.02, 1.3])
@pytest.mark.parametrize("pair", PAIRS)
def test_r18_m16_a1_just_beyond_the_horizon_is_the_diffraction_field_and_the_horizon_is_sqrt_2a_times_the_heights(pair, fraction):
    """`np.sqrt(2.0 * a_km)` read `2.01` and the `hr` term of `d_los` read `1.01 hr`: either moves the switch by 0.5 %, and within that distance the inside
    formula gives another number (0.01 to 0.1 dB) than the diffraction field does."""
    d = fraction * d_los_m(*pair)
    want, factor = ref_inside(d, *pair)
    assert factor is None
    assert float(c.smooth_earth_diffraction_db(d, *pair, F915)) == pytest.approx(want, abs=1e-9)


@pytest.mark.parametrize("pair", PAIRS)
def test_r18_m16_a1_the_switch_is_at_the_horizon_and_the_two_sides_differ_by_what_the_formulas_say(pair):
    d = d_los_m(*pair)
    lo, hi = 0.9995 * d, 1.0005 * d
    assert ref_inside(lo, *pair)[1] is not None and ref_inside(hi, *pair)[1] is None
    for x in (lo, hi):
        assert float(c.smooth_earth_diffraction_db(x, *pair, F915)) == pytest.approx(ref_inside(x, *pair)[0], abs=1e-9)


@pytest.mark.parametrize("d", [8.0, 10.0, 14.0])
def test_r18_m16_a1_a_diffraction_gain_inside_the_horizon_gives_a_loss_of_zero_not_a_negative_one(d):
    """The `np.maximum(..., 0.0)` around the a_em diffraction removed: for two 0.3 m antennas 8 to 14 m apart the formula over a_em is a gain of 3 to 8 dB
    and the factor (1 - h_se / h_req) is positive, so the product was a negative loss. Both premises are asserted from the reference, then the result."""
    a_em = 500.0 * (d / 1e3 / (2.0 * math.sqrt(0.3))) ** 2
    assert ref_beyond(a_em, d / 1e3, 915.0, 0.3, 0.3, 72.8, 6.05) < -1.0
    assert ref_inside(d, 0.3, 0.3)[1] > 0.2
    got = float(c.smooth_earth_diffraction_db(d, 0.3, 0.3, F915))
    assert got == 0.0 and ref_inside(d, 0.3, 0.3)[0] == 0.0
