"""Round 21, batch B: the RF band of any pair of heights (M-2: `physics/rfband.py`, the link card, L23), the render check that cannot disagree with its printer
(M-6), the NOT EXERCISED invariant (M-7), the link statistics over the members that needed the link (M-1, the report part) and `credibility.real_ok` through
`config.finite_real` (M-9, this file only). One regression test per fix, each seen to fail on 7599881 (the hand-back says which job did which). The references
are written in tests/test_round17_d.py and test_round18_b.py from the Fresnel coefficient, never from the code under test."""
import itertools
import json
import re

import numpy as np
import pytest

from cafe.pm import config, credibility as cr, report
from cafe.pm.physics import comms, glider, rfband, uas, usv
from tests.fixtures import pm_run
from tests.test_report import _not_exercised, data_dir, edit_json, load, plain, set_link_fields  # noqa: F401  (data_dir is autouse)
from tests.test_round17_d import F915, fresnel_loss_db
from tests.test_round18_b import band
from tests.test_round22_b import figs

ROOT = config.ROOT
DEMO = config.load_mission(ROOT / "missions" / "tepex_c_demo.yaml")
FIGURE = re.compile(r"median [+-]\d+\.\d dB, at (?:\d+ of 400 sampled ranges|none of the 400)")
L23_END = "(CREDIBILITY, limitation L23)."


def l23():
    return {x["id"]: x for x in cr.LIMITATIONS}["L23"]["text"]


@pytest.fixture
def run(tmp_path):
    d = tmp_path / "run"
    d.mkdir()
    return d


# ---------------------------------------------------------------------------------------------------------------------------------- M-2: rfband

# The merged findings' own figures (review/round_21/merged.md M-2, the verifier's `v2.py` on orca): lower end / partner -> minimum, median, maximum [dB] and the
# share of the 400 samples more than 3 dB off, in per cent (as the merge printed it, rounded).
VERIFIER = {(2.3, 10.0): (-3.4, -0.7, 0.4, 1), (3.0, 15.0): (-2.6, -0.1, 5.7, 0), (4.0, 15.0): (-4.8, 0.2, 15.7, 1), (5.0, 10.0): (-2.0, 0.0, 17.1, 1),
            (5.0, 15.0): (-5.3, 0.3, 13.0, 2), (10.0, 15.0): (-5.7, 0.3, 30.6, 4), (18.0, 15.0): (-7.3, 0.1, 26.0, 6), (18.0, 10.0): (-6.8, 0.2, 25.9, None),
            (30.0, 10.0): (-7.4, -0.1, 32.5, 8), (60.0, 15.0): (-11.1, -0.9, 39.9, 16), (108.0, 15.0): (-13.2, -1.5, 43.8, 26)}


@pytest.mark.parametrize("pair", sorted(VERIFIER))
def test_m2_the_live_band_reproduces_the_verifiers_figures_to_0_1_db(pair):
    """Before: no `rfband` (ImportError). The band the card prints for any pair is the one the merge measured for these eleven pairs, above the 2.2 m of the
    table."""
    lo, med, hi, share, *_ = rfband.pair_band(*pair)
    want = VERIFIER[pair]
    assert all(abs(g - w) <= 0.1 for g, w in zip((lo, med, hi), want[:3], strict=True)), (pair, lo, med, hi)
    assert want[3] is None or abs(100 * share - want[3]) <= 1.0, (pair, share)


@pytest.mark.parametrize("pair", sorted(comms.LOW_ANTENNA_PAIR_BAND))
def test_m2_the_live_band_equals_the_ten_measured_rows_to_0_1_db_and_prints_their_digits(pair):
    """Round 18's own test (tests/test_round18_x.py) holds the table to a recomputation; the card now prints the live figure, so the live figure is held to the
    table, and to its printed digits (the docstring, L23 and PHYSICS 12.1 print the table's)."""
    live = rfband.pair_band(*pair)[:3]
    for got, printed in zip(live, comms.LOW_ANTENNA_PAIR_BAND[pair], strict=True):
        assert abs(got - printed) <= 0.1 and f"{got:+.1f}" == f"{printed:+.1f}", (pair, live)


GRID = [0.1, 0.11, 0.3, 0.5, 0.55, 1.0, 2.2, 2.3, 5.0, 10.0, 15.0, 18.1, 30.0, 60.0, 108.1, 400.1, 1000.0]


@pytest.mark.parametrize("pair", list(itertools.combinations_with_replacement(GRID, 2)))
def test_m2_the_live_band_is_the_independent_references_to_1e_9_db_for_any_pair_and_either_order(pair):
    """`band` of tests/test_round18_b.py is written from the published Fresnel formulas (tests/test_round17_d.py), not from `rfband`: 17 heights from 0.1 to
    1000 m, every pair of them, both orders of the arguments, equal to 1e-9 dB; the share is the fraction of the 400 samples whose |difference| is over 3 dB."""
    lo, hi = pair
    want = band(hi, lo)
    d = np.linspace(300.0, min(float(comms.radio_horizon_km(lo, hi)) * 1e3, 12e3), 400)
    diff = comms.two_ray_loss_db(d, lo, hi, 0.0, F915) - fresnel_loss_db(d, lo, hi)
    for got in (rfband.pair_band(lo, hi), rfband.pair_band(hi, lo)):
        assert got[:3] == pytest.approx(want, abs=1e-9) and got[3] == float(np.mean(np.abs(diff) > 3.0)) and np.isfinite(got).all()


def test_m2_the_frequency_is_the_links_own_and_the_fresnel_reference_follows_it():
    """The card used 915 MHz for every radio; `xbee_pro_24` is at 2440 MHz. The band at f is the model minus the independent Fresnel two-ray at f."""
    d = np.linspace(300.0, min(float(comms.radio_horizon_km(2.2, 18.1)) * 1e3, 12e3), 400)
    diff = comms.two_ray_loss_db(d, 2.2, 18.1, 0.0, 2440e6) - fresnel_loss_db(d, 2.2, 18.1, 2440e6)
    got = rfband.pair_band(2.2, 18.1, 2440e6)
    assert got[:3] == pytest.approx((diff.min(), np.median(diff), diff.max()), abs=1e-9)
    assert abs(got[2] - rfband.pair_band(2.2, 18.1)[2]) > 1.0


def test_m2_the_range_and_the_samples_are_300_m_to_the_horizon_or_12_km_in_400_points(monkeypatch):
    seen = []

    def spy(d, ht, hr, hs, f_hz):
        seen.append((np.asarray(d), hs))
        return fresnel_loss_db(d, ht, hr, f_hz)
    monkeypatch.setattr(comms, "two_ray_loss_db", spy)
    rfband.pair_band(0.1, 0.1)                                              # horizon 2.6 km: the nearer end
    rfband.pair_band(10.0, 15.0)                                            # horizon 31 km: the 12 km cap
    for (d, hs), top in zip(seen, (float(comms.radio_horizon_km(0.1, 0.1)) * 1e3, 12e3), strict=True):
        assert len(d) == 400 and d[0] == 300.0 and d[-1] == top and hs == 0.0 and top < 12e3 + 1 and d[1] - d[0] == pytest.approx((top - 300.0) / 399)
    assert seen[0][1] == 0.0 and float(comms.radio_horizon_km(0.1, 0.1)) * 1e3 < 12e3 < float(comms.radio_horizon_km(10.0, 15.0)) * 1e3


def test_m2_a_share_counts_the_samples_strictly_more_than_3_db_off(monkeypatch):
    """A model that is the Fresnel two-ray plus a constant: the band is that constant, and the share is 0 just inside 3 dB and 1 just beyond it."""
    for shift, want, signs in ((2.9999, 0.0, (0, 0)), (3.0001, 1.0, (400, 0)), (-2.9999, 0.0, (0, 0)), (-3.0001, 1.0, (0, 400)), (0.0, 0.0, (0, 0))):
        monkeypatch.setattr(comms, "two_ray_loss_db", lambda d, ht, hr, hs, f_hz, s=shift: fresnel_loss_db(d, ht, hr, f_hz) + s)
        lo, med, hi, share, over, under = rfband.pair_band(2.2, 15.0)
        assert (lo, med, hi) == pytest.approx((shift,) * 3, abs=1e-9) and share == want and (over, under) == signs, shift


@pytest.mark.parametrize("h", [0.0999999, 0.0, -1.0, 1000.0001, float("nan"), float("inf"), -float("inf"), True, False, 10 ** 400, "3", None, [3.0]])
def test_m2_a_height_outside_0_1_to_1000_m_or_not_a_number_is_a_value_error_at_either_end(h):
    assert not rfband.valid_height(h)
    for a, b in ((h, 2.2), (2.2, h)):
        with pytest.raises(ValueError, match="rfband.pair_band"):
            rfband.pair_band(a, b)


@pytest.mark.parametrize("h", [0.1, 1000.0, 1, 1000, 2.2, np.float64(15.0)])
def test_m2_the_domain_includes_its_two_ends_and_integers(h):
    assert rfband.valid_height(h) and np.isfinite(rfband.pair_band(h, 2.2)).all() and rfband.MIN_HEIGHT_M == 0.1 and rfband.MAX_HEIGHT_M == 1000.0


@pytest.mark.parametrize("f", [0.0, -915e6, float("nan"), float("inf")])
def test_m2_a_frequency_that_is_not_positive_and_finite_is_a_value_error(f):
    with pytest.raises(ValueError, match="frequency"):
        rfband.pair_band(2.2, 15.0, f)


def test_m2_a_band_that_is_not_finite_is_a_value_error_and_never_a_figure(monkeypatch):
    monkeypatch.setattr(comms, "two_ray_loss_db", lambda d, ht, hr, hs, f_hz: np.full(np.shape(d), np.nan))
    with pytest.raises(ValueError, match="is not finite"):
        rfband.pair_band(2.2, 15.0)


def test_m2_every_height_the_loaders_allow_has_a_finite_band_for_every_partner():
    """The card never meets the ValueError above for a height `valid_height` admits: 80 heights from 0.1 to 1000 m (geometric), against six partners."""
    hs = np.geomspace(0.1, 1000.0, 80)
    for partner in (0.1, 0.3, 2.2, 15.0, 108.1, 1000.0):
        for h in hs:
            assert np.isfinite(rfband.pair_band(float(h), partner)).all(), (h, partner)


# ----------------------------------------------------------------------------------------------------------------- M-2: the card, for every height and end


def mission_of(monkeypatch, ends, ship=None, uas_sorties=None):
    """A mission and its patched loaders. `ends`: id -> (class, spec): a glider's or a USV's antenna height [m], or for a UAS (levels [m above the deck], deck
    [m], antenna above the body [m]); `ship`: the ship's `antenna_height_m` (None leaves it out); `uas_sorties`: the mission's own `sorties.altitudes_m`."""
    vehicles = []
    for vid, (cls, _) in ends.items():
        v = dict(id=vid, platform="p_" + vid)
        if cls == "uas" and uas_sorties is not None:
            v["sorties"] = dict(altitudes_m=uas_sorties)
        vehicles.append(v)
    mission = dict(vehicles=vehicles, ship=dict(id="ship", **({} if ship is None else dict(antenna_height_m=ship))))
    spec_of = {"p_" + vid: spec for vid, (_, spec) in ends.items()}
    monkeypatch.setattr(report, "_classes", lambda m: {vid: cls for vid, (cls, _) in ends.items()})
    monkeypatch.setattr(glider, "load_platform", lambda p: dict(antenna_height_m=spec_of[p]))
    monkeypatch.setattr(usv, "load_platform", lambda p: dict(rf_antenna_height_m=spec_of[p]))
    monkeypatch.setattr(uas, "load_platform", lambda p: dict(sortie=dict(levels_m=spec_of[p][0], deck_height_m=spec_of[p][1]),
                                                              radio=dict(uas_antenna_height_above_body_m=spec_of[p][2], ship_antenna_height_m=10.0)))
    return mission


def note_of(monkeypatch, a, b, ship=None, when="uas_airborne", **kw):
    """The card of an RF link between ends `a` and `b` (each (id, (class, spec)) or "ship")."""
    ends = dict(x for x in (a, b) if x != "ship")
    mission = mission_of(monkeypatch, ends, ship=ship, **kw)
    return report._low_antenna_note(dict(id="x", kind="rf", when=when, a="ship" if a == "ship" else a[0], b="ship" if b == "ship" else b[0]), mission)


def has_figure(note):
    """The card of an RF link, with the band of every pair it names: a figure, the L23 sentence, and none of the sentences of the table that was."""
    return (note is not None and FIGURE.search(note) is not None and note.endswith(L23_END) and "not among those measured" not in note
            and "no error band is stated" not in note and "nearest measured pair" not in note and "envelope" not in note)


HEIGHTS = [0.1, 0.11, 0.3, 0.5, 0.5000001, 0.55, 1.0, 2.2, 2.2000001, 2.3, 3.0, 5.0, 10.0, 15.0, 18.1, 30.0, 60.0, 100.0, 108.1, 120.0, 400.1, 1000.0]


def test_m2_no_height_is_silent_two_gliders_and_a_glider_with_a_ship_over_the_whole_grid(monkeypatch):
    """The cliff of rounds 17 to 20 (0.5, 0.55, 2.2 m, above 2.2 m): 22 heights from 0.1 to 1000 m (the cliffs' own values and their neighbours, and 120 m),
    every pair of them, as two glider-class ends and as a glider-class end with the ship's `antenna_height_m`: each card exists, has a figure for its pair,
    and the figure is the independent reference's to 0.1 dB. Before: None for every pair with no end of 2.2 m or lower, and for every pair with a UAS."""
    for h1, h2 in itertools.product(HEIGHTS, HEIGHTS):
        for kind in ("glider", "ship"):
            b = ("b", ("glider", h2)) if kind == "glider" else "ship"
            note = note_of(monkeypatch, ("a", ("glider", h1)), b, ship=h2)
            assert has_figure(note), (h1, h2, kind, note)
            assert f"for this pair of heights ({min(h1, h2):g} m with {max(h1, h2):g} m): {figs(min(h1, h2), max(h1, h2))}" in note, (h1, h2)


@pytest.mark.parametrize("levels, deck, ant", [([10.0, 30.0, 60.0, 100.0], 8.0, 0.1), ([10.0], 8.0, 0.1), ([0.1], 0.0, 0.0), ([80.0, 350.0], 8.0, 0.1),
                                                ([10.0, 25.0, 50.0, 80.0], 8.0, 0.1)])
@pytest.mark.parametrize("partner", [("usv", 2.2), ("glider", 0.3), ("glider", 0.5), ("glider", 15.0), ("uas", None)])
def test_m2_a_uas_end_prints_the_band_of_each_of_its_legs_with_every_partner(monkeypatch, levels, deck, ant, partner):
    """Before: 'no single height', 'not among those measured', no figure. A UAS is taken at deck + level + the antenna above the body, the heights stage 1 gives
    the link; the sentence names the heights it flew and each pair's median and counts are the independent reference's (no extreme over the pairs)."""
    cls, h = partner
    other = ("b", ("uas", (levels, deck, ant))) if cls == "uas" else ("b", (cls, h))
    note = note_of(monkeypatch, ("u", ("uas", (levels, deck, ant))), other)
    legs = sorted({deck + a + ant for a in levels})
    assert has_figure(note), note
    assert f"u (flown at {', '.join(f'{x:g}' for x in legs)} m)" in note and "the climbs between the legs pass other heights, which are not computed" in note
    pairs = sorted({tuple(sorted(p)) for p in itertools.product(legs, legs if cls == "uas" else [h])})
    for lo_h, hi_h in pairs:
        one = f"for this pair of heights ({lo_h:g} m with {hi_h:g} m): {figs(lo_h, hi_h)}"      # the form for a single pair
        many = f"{lo_h:g} m with {hi_h:g} m {figs(lo_h, hi_h)}"
        assert (one if len(pairs) == 1 else many) in note, (lo_h, hi_h)
    assert "over these pairs" not in note and ("by pair of heights" in note) == (len(pairs) > 1) and ("for this pair of heights" in note) == (len(pairs) == 1)


def test_m2_the_mission_levels_win_over_the_platforms_and_both_over_the_fallback(monkeypatch):
    mine = note_of(monkeypatch, ("u", ("uas", ([10.0, 25.0, 50.0, 80.0], 8.0, 0.1))), ("g", ("glider", 0.3)), uas_sorties=[12.0, 40.0])
    assert "u (flown at 20.1, 48.1 m)" in mine
    platform = note_of(monkeypatch, ("u", ("uas", ([10.0, 25.0, 50.0, 80.0], 8.0, 0.1))), ("g", ("glider", 0.3)))
    assert "u (flown at 18.1, 33.1, 58.1, 88.1 m)" in platform


@pytest.mark.parametrize("levels", [[], None, "x", [float("nan")], [-50.0], [5000.0], [10 ** 400], [True]],
                         ids=["empty", "none", "string", "nan", "below the sea", "5 km", "huge int", "bool"])
def test_m2_a_uas_whose_levels_cannot_be_used_gets_the_two_assumed_heights_and_says_so(monkeypatch, levels):
    """The fix for 'no single height' and no figure: the card says it, and prints the band for 18.1 and 108.1 m (the demo's lowest and highest leg), ASSUMED.
    Round 22: one sentence for every cause, unreadable or outside the band's heights (it said 'its flight levels could not be read' for a level of -50 m)."""
    note = note_of(monkeypatch, ("u", ("uas", (levels, 8.0, 0.1))), ("g", ("glider", 2.2)))
    assert has_figure(note), note
    assert "u (no usable height (unreadable, or outside 0.1 to 1000 m): 18.1 and 108.1 m assumed)" in note
    for h in (18.1, 108.1):
        assert f"2.2 m with {h:g} m {figs(2.2, h)}" in note


def test_m2_a_uas_whose_platform_file_cannot_be_read_gets_the_same(monkeypatch):
    mission = mission_of(monkeypatch, {"u": ("uas", ([10.0], 8.0, 0.1)), "g": ("glider", 0.3)})
    for err in (KeyError("radio"), ValueError("no such platform"), FileNotFoundError("gone"), OverflowError("too large"), TypeError("x")):
        def broken(p, err=err):
            raise err
        monkeypatch.setattr(uas, "load_platform", broken)
        note = report._low_antenna_note(dict(kind="rf", when="uas_airborne", a="u", b="g"), mission)
        assert has_figure(note) and "u (no usable height (unreadable, or outside 0.1 to 1000 m): 18.1 and 108.1 m assumed)" in note, err


@pytest.mark.parametrize("who", ["shore", "nobody"])
def test_m2_an_end_that_is_no_vehicle_and_not_the_ship_gets_reference_heights_and_says_so(monkeypatch, who):
    """A shore or an id the mission does not have: before, 'no single height' and no figure. Now four reference heights, ASSUMED, each with its band."""
    mission = mission_of(monkeypatch, {"g": ("glider", 0.3)}, ship=15.0)
    note = report._low_antenna_note(dict(kind="rf", when="uas_airborne", a="g", b=who), mission)
    assert has_figure(note), note
    assert f"{who} (no usable height (unreadable, or outside 0.1 to 1000 m): 0.1, 2.2, 15, 108.1 m assumed)" in note and "g (0.3 m)" in note
    for h in (0.1, 2.2, 15.0, 108.1):
        assert f"{min(h, 0.3):g} m with {max(h, 0.3):g} m {figs(0.3, h)}" in note, h
    assert "g (0.3 m)" in note and "An end of this RF link has an antenna below 0.5 m: g (0.3 m)." in note        # the known end is still told about


def test_m2_two_unreadable_ends_print_the_ten_pairs_of_the_four_reference_heights(monkeypatch):
    mission = mission_of(monkeypatch, {}, ship=15.0)
    note = report._low_antenna_note(dict(kind="rf", when="uas_airborne", a="shore", b="elsewhere"), mission)
    assert has_figure(note) and note.startswith("The antennas of this RF link: shore (no usable height")
    assert len(re.findall(r"median [+-]\d", note)) == 10                                                      # {0.1, 2.2, 15, 108.1} squared, each pair once


@pytest.mark.parametrize("h", [0.05, 0.0, -2.0, 1000.5, 5000.0, float("nan"), float("inf"), 10 ** 400, True, "2.2", None])
@pytest.mark.parametrize("cls", ["glider", "usv"])
def test_m2_a_platform_height_outside_the_bands_domain_is_an_unreadable_end_never_silence_or_a_traceback(monkeypatch, h, cls):
    """A platform height of 0.05 m (below the loader's minimum), NaN, 10**400 (OverflowError in `float`) or a string: the end gets the reference heights."""
    note = note_of(monkeypatch, ("g", (cls, h)), ("p", ("glider", 15.0)))
    assert has_figure(note), (h, note)
    assert "g (no usable height (unreadable, or outside 0.1 to 1000 m): 0.1, 2.2, 15, 108.1 m assumed)" in note


@pytest.mark.parametrize("ship_h", [0.05, 1001.0, float("nan"), 10 ** 400, "tall", None])
def test_m2_a_ship_height_outside_the_domain_is_unreadable_too(monkeypatch, ship_h):
    mission = mission_of(monkeypatch, {"g": ("glider", 0.3)})
    mission["ship"]["antenna_height_m"] = ship_h
    note = report._low_antenna_note(dict(kind="rf", when="uas_airborne", a="g", b="ship"), mission)
    assert has_figure(note) and "ship (no usable height" in note


def test_m2_a_ship_without_a_height_is_10_m_or_the_uas_platforms_and_the_missions_wins(monkeypatch):
    note = note_of(monkeypatch, ("g", ("glider", 0.3)), "ship")
    assert f"for this pair of heights (0.3 m with 10 m): {figs(0.3, 10.0)}" in note
    mission = mission_of(monkeypatch, {"g": ("glider", 0.3), "u": ("uas", ([10.0], 8.0, 0.1))})
    monkeypatch.setattr(uas, "load_platform", lambda p: dict(sortie=dict(levels_m=[10.0], deck_height_m=8.0),
                                                              radio=dict(uas_antenna_height_above_body_m=0.1, ship_antenna_height_m=22.0)))
    assert "(0.3 m with 22 m)" in report._low_antenna_note(dict(kind="rf", when="uas_airborne", a="g", b="ship"), mission)
    mission["ship"]["antenna_height_m"] = 30.0
    assert "(0.3 m with 30 m)" in report._low_antenna_note(dict(kind="rf", when="uas_airborne", a="g", b="ship"), mission)


def test_m2_the_link_with_the_ship_and_the_uas_prints_the_ships_15_m_against_each_leg():
    """The UAS-ship link of a mission (the demo has the UAS-USV one): the ship's 15 m mast against the four legs."""
    note = report._low_antenna_note(dict(kind="rf", when="uas_airborne", a="ship", b="uas"), DEMO)
    assert has_figure(note) and note.startswith("The antennas of this RF link: ship (15 m), uas (flown at 18.1, 38.1, 68.1, 108.1 m).")
    for h in (18.1, 38.1, 68.1, 108.1):
        assert f"{min(h, 15.0):g} m with {max(h, 15.0):g} m {figs(15.0, h)}" in note, h


def test_m2_the_start_sentences_and_their_boundaries_at_0_5_m(monkeypatch):
    """The three starts rounds 17 and 18 pinned; the boundary is exact (0.5 m, one ulp either side) and a UAS end can be the low one."""
    both = note_of(monkeypatch, ("a", ("glider", 0.5)), ("b", ("glider", 0.3)))
    assert both.startswith("Both ends of this RF link have an antenna of 0.5 m or lower: a (0.5 m), b (0.3 m).")
    below = note_of(monkeypatch, ("a", ("glider", float(np.nextafter(0.5, 0)))), ("b", ("glider", 5.0)))
    assert below.startswith("An end of this RF link has an antenna below 0.5 m: a (0.5 m).") and "b (5 m)" not in below.split(" The two-ray")[0]
    at = note_of(monkeypatch, ("a", ("glider", 0.5)), ("b", ("glider", 5.0)))
    assert at.startswith("An end of this RF link has an antenna of 0.5 m: a (0.5 m).")
    above = note_of(monkeypatch, ("a", ("glider", float(np.nextafter(0.5, 1)))), ("b", ("glider", 5.0)))
    assert above.startswith("The antennas of this RF link: a (0.5 m), b (5 m).")
    plain_ = note_of(monkeypatch, ("a", ("glider", 3.0)), ("b", ("glider", 5.0)))
    assert plain_.startswith("The antennas of this RF link: a (3 m), b (5 m).")
    low_uas = note_of(monkeypatch, ("u", ("uas", ([0.1], 0.0, 0.0))), ("g", ("glider", 0.3)))                    # a UAS leg at 0.1 m: the platform's least
    assert low_uas.startswith("Both ends of this RF link have an antenna of 0.5 m or lower: u (flown at 0.1 m), g (0.3 m).")
    low_a = note_of(monkeypatch, ("u", ("uas", ([0.3, 30.0], 0.0, 0.0))), ("g", ("glider", 5.0)))
    assert low_a.startswith("An end of this RF link has an antenna below 0.5 m: u (flown at 0.3, 30 m).")
    at_uas = note_of(monkeypatch, ("u", ("uas", ([0.5, 30.0], 0.0, 0.0))), ("g", ("glider", 5.0)))
    assert at_uas.startswith("An end of this RF link has an antenna of 0.5 m: u (flown at 0.5, 30 m).")


def test_m2_a_link_that_is_not_rf_has_no_card_and_the_clause_about_legs_is_for_a_uas_only(monkeypatch):
    for kind in ("acoustic", "iridium"):
        assert report._low_antenna_note(dict(kind=kind, a="glider_eq", b="glider_2n"), DEMO) is None
    assert "the climbs between the legs" not in note_of(monkeypatch, ("a", ("glider", 0.3)), ("b", ("glider", 15.0)))
    assert "over these pairs" not in note_of(monkeypatch, ("a", ("glider", 0.3)), ("b", ("glider", 15.0)))


def test_m2_the_radio_of_the_link_sets_the_frequency_and_an_unknown_radio_is_refused(monkeypatch):
    mission = mission_of(monkeypatch, {"a": ("glider", 0.3), "b": ("glider", 15.0)})
    lk = dict(id="l", kind="rf", when="uas_airborne", a="a", b="b")
    default, rfd, xbee = (report._low_antenna_note(dict(lk, **extra), mission) for extra in ({}, dict(radio="rfd900x"), dict(radio="xbee_pro_24")))
    assert default == rfd and "at 915 MHz" in default and "at 2440 MHz" in xbee
    assert f"for this pair of heights (0.3 m with 15 m): {figs(0.3, 15.0, 2440e6)}" in xbee and xbee != default
    with pytest.raises(config.ConfigError, match=r"link 'l': radio 'nope' is not in platforms/radios.yaml"):
        report._low_antenna_note(dict(lk, radio="nope"), mission)
    with pytest.raises(config.ConfigError, match="radio"):
        report._low_antenna_note(dict(lk, radio=None), mission)


def test_m2_the_demos_cards_are_the_one_text_q23_shows_and_report_json_traces_it(tmp_path):
    """What a demo run q23 shows for `usv-uas-rf` (q22: no `low_antenna` text); no other link of the demo has one."""
    run = tmp_path / "run"
    m, plan = pm_run.make_run(run)
    report.write(run, m, plan)
    rep = load(run)
    h = (run / "report" / "index.html").read_text()
    assert [lid for lid, k in rep["links"].items() if k["low_antenna"]] == ["usv-uas-rf"]
    assert rep["links"]["usv-uas-rf"]["low_antenna"] == report._low_antenna_note(next(lk for lk in m["links"] if lk["id"] == "usv-uas-rf"), m)
    assert report.check_traceability(rep) == [] and report.check_rendered(rep, h) == []


# ------------------------------------------------------------------------------------------------------------------------- M-2: L23


def test_m2_l23_prints_the_live_figures_of_its_pairs_and_no_edge_of_a_table():
    """Round 22, M-1: the figures are the median and the counts (tests/test_round22_b.py holds every pair's text to the independent reference); the ten pairs of
    the table are still held to it (the table's medians, to 0.1 dB, in tests/test_round18_x.py), and no edge of a table is back."""
    t = l23()
    assert sorted(cr.L23_PAIRS) == sorted(comms.LOW_ANTENNA_PAIR_BAND) and sorted(cr.L23_UAS_PAIRS) == [(2.2, 18.1), (2.2, 108.1), (15.0, 18.1), (15.0, 108.1)]
    for pair in (*cr.L23_PAIRS, *cr.L23_UAS_PAIRS):
        assert figs(*pair) in t and cr.pair_figures(pair) == figs(*pair), pair
    assert t.startswith("RF links, from an antenna below 0.5 m or one of 2.2 m to a UAS at 108 m:")
    assert "The card of every RF link computes the same figures for the link's own pair of heights, for any heights from 0.1 m to 1000 m" in t
    for gone in ("for none above that", "0.55 to 2.2 m", "envelope", "is not measured and no band is stated for it", "is read as that one",
                 "within 0.05 m of a listed"):
        assert gone not in t, gone
    assert t.endswith("; nearer than 300 m none of this is stated")
    for name in ("LOW_ANTENNA_ROW_TOL_M", "LOW_ANTENNA_MID_RANGE_M", "LOW_ANTENNA_MID_PARTNER_M", "LOW_ANTENNA_MID_BAND", "mid_envelope", "pair_effect"):
        assert not hasattr(cr, name), name
    for name in ("RF_NEAR_ANTENNA_M", "_nearest_row", "_end_antenna_m"):
        assert not hasattr(report, name), name


def test_m2_l23_gives_the_demos_uas_pairs_and_what_the_demo_card_says_agrees():
    t = l23()
    for pair in cr.L23_UAS_PAIRS:
        assert f"{pair[0]:g} m with {pair[1]:g} m {figs(*pair)}" in t, pair
        card = report._low_antenna_note(next(lk for lk in DEMO["links"] if lk["id"] == "usv-uas-rf") | dict(a="usv" if pair[0] == 2.2 else "ship"), DEMO)
        assert f"{pair[0]:g} m with {pair[1]:g} m {figs(*pair)}" in card


# ------------------------------------------------------------------------------------------------------------------------- M-6: the render check


def card_of(h, lid="usv-uas-rf"):
    return plain(h.split(f"<div id='v-{lid}'>")[1].split("<div id='v-")[0])


@pytest.mark.parametrize("partly, none", [("usv-uas-rf", "glider_eq-ship-acoustic"), ("glider_eq-ship-acoustic", "usv-uas-rf")])
def test_m6_a_not_exercised_link_beside_a_partly_needed_one_passes_the_runs_own_check_in_both_orders(run, partly, none):
    """Reviewers A and C: `links.<id>.granularity.needed: '0 members' is not in the HTML`, exit 1 of `report --run`. Before this fix the print of the
    all-members sentence had no `needed` in it and `check_rendered` asked for it."""
    m, plan = pm_run.make_run(run)
    _not_exercised(run, none)
    edit_json(run / "stage1b" / "summary.json",
              lambda d: d["summary"]["links"][none].update(k_fail=0, verdict=dict(d["summary"]["links"][none]["verdict"], p_fail=0.0, k_fail=0)))
    n = json.loads((run / "stage1b" / "summary.json").read_text())["summary"]["links"][none]["n"]
    set_link_fields(run, **{none: dict(n_never_required=n), partly: dict(need_count_median=30, granularity_ok=True, n_never_required=20)})
    report.write(run, m, plan)
    rep, h = load(run), (run / "report" / "index.html").read_text()
    assert report.check_traceability(rep) == [] and report.check_rendered(rep, h) == []
    assert report.self_checks(run) == dict(report_traceable=[], report_html_matches_json=[])
    assert f"no member needed it (0 members out of {n} members)." in card_of(h, none)
    assert "counts as a pass in the P(fail) above" in card_of(h, partly) and "0 members out of" not in card_of(h, partly)
    assert rep["links"][none]["granularity"]["needed"]["value"] == 0


def test_m6_a_dropped_print_is_still_found_whatever_the_link(run):
    """The omission is what the printer says, not a blanket: a count the printer prints and the page lacks is a problem, and a count of 0 turned into 3 in the
    JSON is printed by the printer and therefore asked for (round 20's own test, on the first link instead of the second)."""
    m, plan = pm_run.make_run(run)
    set_link_fields(run, **{"usv-uas-rf": dict(need_count_median=30, granularity_ok=True, n_never_required=20),
                            "glider_eq-ship-acoustic": dict(need_count_median=30, granularity_ok=True, n_never_required=0)})
    report.write(run, m, plan)
    rep, h = load(run), (run / "report" / "index.html").read_text()
    assert report.check_rendered(rep, h) == []
    gone = h.replace("20 members", "21 members", 1)
    assert [b for b in report.check_rendered(rep, gone) if "usv-uas-rf.granularity.never_required" in b]
    lone = json.loads(json.dumps(rep))
    lone["links"]["glider_eq-ship-acoustic"]["granularity"]["never_required"]["value"] = 3
    assert [b for b in report.check_rendered(lone, h) if "glider_eq-ship-acoustic.granularity.never_required" in b]


def test_m6_the_omitted_paths_are_the_printers_and_nothing_else():
    """`_omitted` runs the conditional printer over the report's own nodes: a link whose count is 0 leaves out its three counts, a link with a count leaves out
    none, an older link (no counts) leaves out none (there is no node to leave out), and a rep that is not a report leaves out none."""
    def node(v):
        return dict(value=v, unit="members", stage="s", source="x", uncertainty=None, receipt="r", ledger="l")

    def gran(never, n, needed):
        return dict(never_required=node(never), members=node(n), needed=node(needed))
    rep = dict(links={"a": dict(granularity=gran(0, 8, 8), k_fail=node(0)), "b": dict(granularity=gran(3, 8, 5), k_fail=node(1)),
                      "c": dict(granularity=dict(never_required=None, members=None, needed=None)), "d": dict(granularity=None), "e": {}})
    assert report._omitted(rep) == {f"links.a.granularity.{k}" for k in ("never_required", "members", "needed")}
    assert report._omitted({}) == set() and report._omitted(dict(links=None)) == set() and report._omitted(dict(links={"z": "text"})) == set()
    assert report._PATHS == {} and report._OMITTED == []                                            # nothing is left behind
    report._omit(None, node(1))                                                                      # a node that is in no report has no path
    assert report._OMITTED == []


def test_m6_the_sentence_for_a_link_needed_in_no_member_and_the_one_for_no_failure_count():
    """`_never_required_html`: where nobody needed it the count of the members that needed it is printed (0 members out of n members); with no failure count
    (a direct call) the sentence still says how many needed it and does not say 'no member needed it'."""
    def node(v, unit="members"):
        return dict(value=v, unit=unit, stage="s", source="x", uncertainty=None, receipt="r", ledger="l")
    g = dict(never_required=node(8), members=node(8), needed=node(0))
    assert plain(report._never_required_html(g, node(0))) == ("The link was required at no moment in 8 members, out of 8 members: in each of those it "
                                                              "passes by default (a pass fraction of 1.0); no member needed it (0 members out of 8 members).")
    g = dict(never_required=node(3), members=node(8), needed=node(5))
    assert plain(report._never_required_html(g, None)) == ("The link was required at no moment in 3 members, out of 8 members: in each of those it passes by "
                                                           "default (a pass fraction of 1.0); 5 members needed it.")
    assert "counts as a pass in the P(fail) above; 1 member failed of the 5 members that needed the link." in plain(report._never_required_html(g, node(1)))


# -------------------------------------------------------------------------------------------------------------------- M-7: NOT EXERCISED iff nobody needed it


def summary_of(**link):
    e = dict(k_fail=0, n=48, verdict=dict(verdict="GO"), sensitivity=dict(param=None, S1={}))
    e.update(link)
    return dict(summary=dict(vehicles={}, links=dict(a=e)))


def refused(s, match):
    with pytest.raises(config.ConfigError, match=match) as err:
        cr.check_summary(s)
    assert "the summary was edited or is damaged; run it again (--fresh)" in str(err.value) and "summary.links.a:" in str(err.value)


@pytest.mark.parametrize("fields", [dict(n_never_required=48), dict(n_needed=0), dict(n_never_required=48, n_needed=0)], ids=["count", "needed", "both"])
def test_m7_a_link_nobody_needed_under_a_go_verdict_is_refused(fields):
    """Reviewer C's first summary: the all-members count with the verdict GO printed two contradictory cards with green checks."""
    refused(summary_of(**fields), r"the verdict is GO but 0 of its n 48 members needed the link \(NOT EXERCISED if and only if none did\)")


@pytest.mark.parametrize("fields", [dict(n_never_required=0), dict(n_needed=48), dict(n_never_required=20, n_needed=28), dict(n_never_required=47)],
                         ids=["no count of never", "needed", "both", "one needed"])
def test_m7_a_not_exercised_link_that_somebody_needed_is_refused(fields):
    s = summary_of(**fields)
    s["summary"]["links"]["a"]["verdict"] = dict(verdict="NOT EXERCISED")
    refused(s, r"the verdict is NOT EXERCISED but \d+ of its n 48 members needed the link")


@pytest.mark.parametrize("verdict, fields", [("NOT EXERCISED", dict(n_never_required=48)), ("NOT EXERCISED", dict(n_needed=0)),
                                             ("NOT EXERCISED", dict(n_needed=0, n_never_required=48)), ("GO", dict(n_never_required=0)),
                                             ("GO", dict(n_needed=1, n_never_required=47)), ("NO-GO", dict(n_needed=48)), ("NOT EXERCISED", {}), ("GO", {}),
                                             ("NOT EXERCISED", dict(n_never_required=None, n_needed=None))])
def test_m7_the_consistent_summaries_and_an_older_one_without_the_counts_pass(verdict, fields):
    s = summary_of(**fields)
    s["summary"]["links"]["a"]["verdict"] = dict(verdict=verdict)
    cr.check_summary(s)


def test_m7_a_hand_built_entry_without_a_verdict_or_with_a_verdict_that_is_no_dict_is_not_asked(monkeypatch):
    for verdict in (None, "GO", 3, []):
        s = summary_of(n_never_required=48)
        s["summary"]["links"]["a"]["verdict"] = verdict
        cr.check_summary(s)                                                                         # nothing to compare the count with
    s = summary_of(n_never_required=48)
    del s["summary"]["links"]["a"]["verdict"]
    cr.check_summary(s)


@pytest.mark.parametrize("needed, never", [(49, None), (-1, None), (1.5, None), (True, None), ("3", None), (float("nan"), None), (10 ** 400, None), ([3], None),
                                           (20, 20), (30, 20), (0, 47)])
def test_m7_n_needed_that_is_not_a_count_of_the_members_or_does_not_add_up_is_refused(needed, never):
    refused(summary_of(n_needed=needed, n_never_required=never),
            r"n_needed .* is not a count \(an integer, 0 <= n_needed <= n, n_needed \+ n_never_required = n\)")


def test_m7_n_needed_that_adds_up_is_accepted_at_both_bounds():
    for needed, never in ((0, 48), (48, 0), (28, 20), (48, None)):
        s = summary_of(n_needed=needed, n_never_required=never)
        s["summary"]["links"]["a"]["verdict"] = dict(verdict="NOT EXERCISED" if needed == 0 else "GO")
        cr.check_summary(s)


def test_m7_the_vehicles_are_not_asked_for_link_counts_and_the_invariant_reaches_report_write(run):
    """A vehicle entry has no `n_needed`; and the invariant is checked on the way into the report, with the link named, before anything is printed."""
    cr.check_summary(dict(summary=dict(vehicles=dict(v=dict(k_fail=1, n=4, n_needed=99, verdict=dict(verdict="NOT EXERCISED"))), links={})))
    m, plan = pm_run.make_run(run)
    n = json.loads((run / "stage1b" / "summary.json").read_text())["summary"]["links"]["usv-uas-rf"]["n"]
    set_link_fields(run, **{"usv-uas-rf": dict(n_never_required=n)})                                  # verdict still GO
    with pytest.raises(config.ConfigError, match=r"summary\.links\.usv-uas-rf: the verdict is GO but 0 of its n"):
        report.write(run, m, plan)


# -----------------------------------------------------------------------------------------------------------------  M-1: the statistics over the needed members


def censored(share=0.75, at="max", value=1.0):
    return dict(share=share, at=at, value=value)


def set_link_sens(run, lid, **fields):
    def go(d):
        d["summary"]["links"][lid]["sensitivity"].update(fields)
    edit_json(run / "stage1b" / "summary.json", go)


def built(run, per_link=None, sens=None, vehicle=None):
    m, plan = pm_run.make_run(run)
    for lid, fields in (per_link or {}).items():
        set_link_fields(run, **{lid: fields})
    for lid, fields in (sens or {}).items():
        set_link_sens(run, lid, **fields)
    for vid, fields in (vehicle or {}).items():
        edit_json(run / "stage1b" / "summary.json", lambda d, v=vid, f=fields: d["summary"]["vehicles"][v]["sensitivity"].update(f))
    report.write(run, m, plan)
    rep, h = load(run), (run / "report" / "index.html").read_text()
    assert report.check_traceability(rep) == [] and report.check_rendered(rep, h) == []
    return rep, h


PARTLY = dict(need_count_median=30, granularity_ok=True, n_never_required=20)
RANKED = dict(param="hs_scale", S1={"hs_scale": 0.9}, noise_floor=0.1, text=None)             # the old wording of the line: `<code>hs_scale</code> (S1 0.9)`


def test_m1_a_link_whose_statistics_stage_1_took_over_the_needed_members_says_so_on_both_lines(run):
    """Before: the card gave 'median ... 10th percentile' and 'Most sensitive to' with no word of which members they are about, and read `needed` as
    n - n_never_required. With `n_needed` in the summary (batch A) the pass fraction and the ranking are of those members and the card says so."""
    rep, h = built(run, {"usv-uas-rf": dict(PARTLY, n_needed=28)}, sens={"usv-uas-rf": RANKED})
    g = rep["links"]["usv-uas-rf"]["granularity"]
    assert g["needed"]["value"] == 28 and g["needed"]["source"] == "stage1b/summary.json summary.links.usv-uas-rf.n_needed" and g["on_needed"] is True
    c = card_of(h)
    assert "Fraction of required moments met (in the 28 members that needed the link): median" in c
    assert re.search(r"Most sensitive to: .*hs_scale.*, ranked over the 28 members that needed the link\.", c)


@pytest.mark.parametrize("fields, why", [(PARTLY, "an older summary: no n_needed"), (dict(PARTLY, n_never_required=0, n_needed=48), "every member needed it"),
                                          (dict(n_needed=0, n_never_required=48), "nobody needed it")])
def test_m1_no_scope_where_the_statistics_are_over_all_members_or_there_is_no_subset(run, fields, why):
    """An older summary's pass fraction and sensitivity were taken over all the members and must not be described as taken over the needed ones."""
    per = {"usv-uas-rf": fields}
    if fields.get("n_needed") == 0:
        m, plan = pm_run.make_run(run)
        _not_exercised(run)
        set_link_fields(run, **per)
        report.write(run, m, plan)
        h = (run / "report" / "index.html").read_text()
    else:
        _, h = built(run, per, sens={"usv-uas-rf": dict(param="hs_scale", S1={"hs_scale": 0.9}, noise_floor=0.1, text=None)})
    assert "that needed the link)" not in card_of(h) and "ranked over the" not in card_of(h), why


def test_m1_the_derived_needed_of_an_older_summary_keeps_its_source_and_has_no_on_needed_key(run):
    """`on_needed` is a key only where stage 1 ranked over some of the members: a link every member needed adds no leaf to report.json (q22's four links)."""
    rep, _ = built(run, {"usv-uas-rf": PARTLY})
    g = rep["links"]["usv-uas-rf"]["granularity"]
    assert g["needed"]["source"].endswith(".n (less n_never_required)") and "on_needed" not in g
    rep, _ = built(run / "b", {"usv-uas-rf": dict(need_count_median=30, granularity_ok=True)})            # no count at all: no counts, nothing derived
    g = rep["links"]["usv-uas-rf"]["granularity"]
    assert g["needed"] is None and "on_needed" not in g and g["members"] is None
    for fields in (dict(PARTLY, n_never_required=0, n_needed=48), dict(PARTLY, n_needed=20, n_never_required=28)):          # all needed; the other way round
        rep, _ = built(run / f"c{fields['n_needed']}", {"usv-uas-rf": fields})
        assert ("on_needed" in rep["links"]["usv-uas-rf"]["granularity"]) is (fields["n_needed"] == 20)


def test_m1_a_ranked_quantity_with_more_than_half_its_rows_at_one_extreme_prints_one_clause_for_a_link_and_for_a_vehicle(run):
    """The clause was the USV's state of charge alone (round 20, M-12); it is now printed from the record stage 1 made, for any quantity of any card."""
    rep, h = built(run, sens={"usv-uas-rf": dict(RANKED, quantity="fraction of required moments met", censored=censored(0.75, "max", 1.0))},
                   vehicle={"uas": dict(RANKED, param="wind_speed_bias", S1={"wind_speed_bias": 0.9}, quantity="profile share",
                                         censored=censored(0.625, "min", 0.0))})
    link, uas_card = card_of(h, "usv-uas-rf"), card_of(h, "uas")
    assert ("(0.75 of the ranked members share the same highest value of the fraction of required moments met, 1: a clip or a ceiling, so this index rests on "
            "the other members and on a tie among these)") in link
    assert ("(0.625 of the ranked members share the same lowest value of the profile share, 0: a clip or a ceiling, so this index rests on the other members "
            "and on a tie among these)") in uas_card
    node = rep["links"]["usv-uas-rf"]["sensitivity"]["censored"]
    assert node["share"]["value"] == 0.75 and node["at"] == "max" and node["value"]["value"] == 1.0
    own = built(run / "own")[1].count("share the same")    # the fixture's own acoustic link has a real record of stage 1 (batch A: 0.56 of its ranked
    assert own == 1 and h.count("share the same") == own + 2             # members at 0.97) on the merged tree; no other card, no second clause on these two


def test_m1_no_clause_without_a_record_and_the_older_usv_clause_only_without_one(run):
    rep, h = built(run)
    assert "censored" not in rep["links"]["usv-uas-rf"]["sensitivity"] and "censored" not in rep["vehicles"]["usv"]["sensitivity"]
    assert all("share the same" not in card_of(h, v) for v in rep["vehicles"]) and "share the same" not in card_of(h, "usv-uas-rf")
    # the fixture's acoustic link carries a real record (batch A: the share of its ranked members at one pass fraction) and prints its clause, once
    assert h.count("share the same") == 1 and "share the same" in card_of(h, "glider_eq-ship-acoustic")


def test_m1_a_summary_with_a_record_does_not_also_print_round_20s_clause_for_the_usv(run):
    """Round 20's USV clause (more than half the members with an empty pack) is only for a summary with no record: with one the generic clause is the one."""
    def energy(d):
        v = d["summary"]["vehicles"]["usv"]
        v["energy"] = dict(soc_min_median=0.0, soc_min_p10=0.0, soc_min_lowest=0.0, n_empty=v["n"])
        v["sensitivity"].update(quantity=report.QUANTITY["energy_margin"])
    m, plan = pm_run.make_run(run)
    edit_json(run / "stage1b" / "summary.json", energy)
    report.write(run, m, plan)
    old = card_of((run / "report" / "index.html").read_text(), "usv")
    assert "ended with an empty pack" in old and "share the same" not in old
    edit_json(run / "stage1b" / "summary.json", lambda d: d["summary"]["vehicles"]["usv"]["sensitivity"].update(censored=censored(1.0, "min", 0.0)))
    report.write(run, m, plan)
    new = card_of((run / "report" / "index.html").read_text(), "usv")
    assert "ended with an empty pack" not in new and "share the same lowest value of the lowest state of charge" in new


@pytest.mark.parametrize("bad", [dict(share=0.0, at="max", value=1.0), dict(share=1.5, at="max", value=1.0), dict(share=-0.2, at="max", value=1.0),
                                 dict(share=float("nan"), at="max", value=1.0), dict(share=True, at="max", value=1.0), dict(share="0.8", at="max", value=1.0),
                                 dict(share=10 ** 400, at="max", value=1.0), dict(share=0.8, at="mid", value=1.0), dict(share=0.8, at=None, value=1.0),
                                 dict(share=0.8, at="max", value=float("nan")), dict(share=0.8, at="max", value=None), dict(share=0.8, at="max"),
                                 dict(at="max", value=1.0), "max", 3, [0.8, "max", 1.0], {}])
@pytest.mark.parametrize("where", ["links", "vehicles"])
def test_m1_a_censored_record_that_is_not_one_is_refused_for_a_link_and_a_vehicle(bad, where):
    s = summary_of()
    s["summary"]["links"]["a"]["sensitivity"]["censored"] = bad
    if where == "vehicles":
        s["summary"]["vehicles"]["a"] = s["summary"]["links"].pop("a")
    with pytest.raises(config.ConfigError, match=rf"summary\.{where}\.a: sensitivity.censored .* is not a share in \(0, 1\]") as err:
        cr.check_summary(s)
    assert "edited or is damaged" in str(err.value)


@pytest.mark.parametrize("good", [dict(share=1.0, at="min", value=0), dict(share=0.51, at="max", value=1.0), dict(share=1e-9, at="min", value=-3.5)])
def test_m1_a_censored_record_is_accepted_for_any_share_in_0_1_and_either_end(good):
    s = summary_of()
    s["summary"]["links"]["a"]["sensitivity"]["censored"] = good
    cr.check_summary(s)
    for no_sens in (None, 3, []):                                                                    # an entry whose sensitivity is no dict has no record
        s["summary"]["links"]["a"]["sensitivity"] = no_sens
        cr.check_summary(s)


def test_m1_the_bellhop_spread_is_a_traced_node_printed_only_where_stage_1_measured_one(run):
    """`bellhop_spread_db_median` (batch A): a float where Bellhop ran, None where it did not, absent in an older summary (q22's). Printed beside the margin."""
    rep, h = built(run, {"glider_eq-ship-acoustic": dict(margin_kind="acoustic link margin, dB", bellhop_spread_db_median=3.25)})
    node = rep["links"]["glider_eq-ship-acoustic"]["bellhop_spread_db_median"]
    assert node["value"] == 3.25 and node["unit"] == "dB" and node["source"].endswith("glider_eq-ship-acoustic.bellhop_spread_db_median")
    assert "; the Bellhop runs of one sample differ by 3.25 dB (median over the refined samples)" in card_of(h, "glider_eq-ship-acoustic")
    for fields in (dict(bellhop_spread_db_median=None), dict()):
        rep, h = built(run / "b", {"glider_eq-ship-acoustic": fields})
        assert "bellhop_spread_db_median" not in rep["links"]["glider_eq-ship-acoustic"] and "the Bellhop runs" not in h
    rep, h = built(run / "c", {"glider_eq-ship-acoustic": dict(bellhop_spread_db_median=0.0)})
    assert "differ by 0 dB" in card_of(h, "glider_eq-ship-acoustic")                                  # zero is a measurement, not an absence


# ------------------------------------------------------------------------------------------------------------------------- M-9: real_ok / conf_ok


@pytest.mark.parametrize("x, ok", [(1, True), (0, True), (-3, True), (0.5, True), (1e308, True), (10 ** 308, True), (True, False), (False, False),
                                    (None, False), ("1", False), (float("nan"), False), (float("inf"), False), (-float("inf"), False), (10 ** 400, False),
                                    (-10 ** 400, False), ([1], False), (1j, False)])
def test_m9_real_ok_is_the_finite_real_test_and_an_oversized_integer_is_false_not_an_overflow(x, ok):
    """Before: OverflowError on 10**400 (`math.isfinite` of an int too large for a float): `report --run` was a traceback where RUNBOOK 280 promises exit 2."""
    assert cr.real_ok(x) is ok and cr.real_ok(x) == config.finite_real(x)


@pytest.mark.parametrize("c, ok", [(0.5, True), (0.95, True), (1e-9, True), (0.999999, True), (0, False), (1, False), (0.0, False), (1.0, False),
                                    (-0.1, False), (1.1, False), (True, False), (None, False), ("0.9", False), (float("nan"), False), (float("inf"), False),
                                    (10 ** 400, False), (-10 ** 400, False)])
def test_m9_conf_ok_is_a_finite_real_strictly_between_0_and_1(c, ok):
    assert cr.conf_ok(c) is ok


def test_m9_real_ok_delegates_to_the_one_test(monkeypatch):
    monkeypatch.setattr(config, "finite_real", lambda v: v == "sentinel")
    assert cr.real_ok("sentinel") is True and cr.real_ok(1.0) is False


def test_m9_a_damaged_verdict_with_an_oversized_integer_is_the_damaged_summary_message_not_a_traceback(run):
    """In memory (nothing read it from a file: `_stat` of an entry) it is the damaged-summary message. Through a file, since the merge (batch D's `load_json`),
    the integer is refused at the reader, before `report` sees a verdict: a ConfigError naming the file, not a traceback either."""
    entry = lambda **v: dict(n=48, k_fail=0, verdict=dict(verdict="GO", p_fail=0.1, fail_lo=0.0, fail_hi=0.3, conf=0.9, **v))      # noqa: E731
    with pytest.raises(config.ConfigError, match=r"verdict\.p_fail is not a finite number: the summary was edited or is damaged"):
        report._stat(dict(entry(), verdict=dict(entry()["verdict"], p_fail=10 ** 400)), {}, "x")
    with pytest.raises(config.ConfigError, match=r"verdict\.conf is"):
        report._stat(dict(entry(), verdict=dict(entry()["verdict"], conf=10 ** 400)), {}, "x")
    m, plan = pm_run.make_run(run)
    edit_json(run / "stage1b" / "summary.json", lambda d: d["summary"]["links"]["usv-uas-rf"]["verdict"].update(p_fail=10 ** 400))
    with pytest.raises(config.ConfigError, match=r"summary\.json: not a JSON object \(an integer of 401 characters is too large for a number"):
        report.write(run, m, plan)
