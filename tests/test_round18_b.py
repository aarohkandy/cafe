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
# (higher antenna, lower antenna, first distance [m], last distance [m] or None for the pair's radio horizon) -> model loss minus the Fresnel loss, minimum /
# median / maximum [dB], as the docstring of two_ray_curved_db prints them to 0.1 dB (measured on orca: Hs 0, 915 MHz, 400 points, eps_c 72.8 - j118.9)
PAIR_BAND = {
    (15.0, 2.2, 300.0, 12e3): (-3.3, -0.4, 0.2),
    (15.0, 0.5, 300.0, 12e3): (-2.9, 1.3, 2.2),
    (15.0, 0.3, 300.0, 12e3): (1.2, 5.1, 6.0),
    (15.0, 0.1, 300.0, 12e3): (11.4, 15.1, 16.0),
    (0.5, 0.3, 200.0, None): (9.0, 9.3, 9.3),
    (0.3, 0.3, 200.0, None): (11.1, 11.4, 11.4),
    (0.5, 0.5, 200.0, None): (6.3, 6.7, 6.7),
    (2.2, 0.3, 200.0, None): (5.1, 6.2, 6.2),
    (2.2, 0.5, 200.0, None): (1.4, 2.6, 2.7),
    (2.2, 2.2, 200.0, 12e3): (-3.0, -1.2, 1.6),
}


def band(hr, ht, d0, d1):
    """The model's loss minus the Fresnel loss over d0 to d1 (the pair's radio horizon when d1 is None), 400 points: (minimum, median, maximum)."""
    d1 = float(c.radio_horizon_km(ht, hr)) * 1e3 if d1 is None else d1
    d = np.linspace(d0, d1, 400)
    diff = c.two_ray_loss_db(d, ht, hr, 0.0, F915) - fresnel_loss_db(d, ht, hr)
    return float(diff.min()), float(np.median(diff)), float(diff.max())


@pytest.mark.parametrize("pair", sorted(PAIR_BAND, key=lambda k: (-k[0], -k[1])))
def test_r18_m3_the_docstring_figures_of_every_pair_are_the_measured_ones(pair):
    """Round 17 measured the band with a 15 m partner only and wrote it as a property of the low antenna: two gliders are 6 to 11 dB off, not 5."""
    got, printed = band(*pair), PAIR_BAND[pair]
    for g, p in zip(got, printed, strict=True):
        assert abs(g - p) <= 0.1, (pair, got)
    assert f"{printed[0]:+.1f} / {printed[1]:+.1f} / {printed[2]:+.1f}" in doc_of(c.two_ray_curved_db), pair


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


def test_r18_m3_both_ends_low_is_overstated_everywhere_and_the_sign_flips_at_0_5_to_2_2_m():
    """The statements of L23 and the docstring, from the same numbers: below 0.5 m (both ends 0.5 m or lower) the loss is overstated at every distance, 6 to
    11 dB; for 0.5 m and 2.2 m with a 2.2 m or 15 m partner it is understated at the minimum, by 3.3 dB at worst (300 m start)."""
    for pair in ((0.5, 0.3), (0.3, 0.3), (0.5, 0.5)):
        lo, med, hi = band(*pair, 200.0, None)
        assert lo > 6.0 and hi < 11.5 and 6.5 < med < 11.5, (pair, lo, med, hi)
    for pair, d0 in (((15.0, 2.2), 300.0), ((15.0, 0.5), 300.0), ((2.2, 2.2), 200.0)):
        lo = band(*pair, d0, 12e3)[0]
        assert -3.4 < lo < 0.0, (pair, lo)                                   # the margin is too high somewhere, by 3.3 dB at worst


def test_r18_m3_l23_states_the_band_by_pair_and_drops_never_too_high_and_not_affected():
    t = l23()
    assert t.startswith("RF links to a low antenna, an antenna below 0.5 m or the USV's 2.2 m whip:")
    assert "antenna below 0.5 m" in t and t.count("6 to 11 dB") == 1 and "both ends are 0.5 m or lower" in t
    assert "(7 dB for two Seagliders, 9 dB for a Seaglider with a Slocum, 11 dB for two Slocums)" in t
    assert "11 to 16 dB at 0.1 m" in t and "can be too high" in t and "MARGINAL or NO-GO" in t
    for gone in ("never too high", "not affected", "are not affected", "is conservative", "a margin there is conservative", "above 0.5 m and"):
        assert gone not in t, gone
    x = {x["id"]: x for x in cr.LIMITATIONS}["L23"]
    assert x["factors"] == ["validation"] and all((cr.ROOT / w).is_file() for w in x["where"])
    assert [y["id"] for y in cr.LIMITATIONS][-2:] == ["L22", "L23"]


def test_r18_m3_l23_medians_are_those_of_the_pairs_it_names():
    for pair, word in (((0.5, 0.5), "7 dB for two Seagliders"), ((0.5, 0.3), "9 dB for a Seaglider with a Slocum"), ((0.3, 0.3), "11 dB for two Slocums")):
        assert round(band(*pair, 200.0, None)[1]) == int(word.split()[0]), pair
        assert word in l23()


def test_r18_m3_the_docstring_has_no_conservative_for_all_and_no_unaffected_shipped_antenna():
    doc = doc_of(c.two_ray_curved_db)
    for gone in ("never too high", "are not affected", "(the conservative direction", "12 to 16 dB at 0.1 m"):
        assert gone not in doc, gone
    for text in ("LOW ANTENNAS", "both ends low", "the PAIR of heights", "11 to 16 dB at 0.1 m", "UNDERSTATES the loss", "the USV's 2.2 m whip",
                 "about 5 dB for an RF link to the Slocum's 0.3 m antenna from a partner of 2.2 m or more", "by 6 to 11 dB when both ends are 0.5 m or lower"):
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
