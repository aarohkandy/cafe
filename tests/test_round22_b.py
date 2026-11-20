"""Round 22, batch B: the RF band printed as the sampling's own statistics and nothing more (M-1: the median and two signed counts of the 400 sampled ranges, no
extreme, no limit; `rfband.pair_band`, `credibility.band_effect` / `band_figures` / `SAMPLING_NOTE`, the card, L23), the card held to the heights stage 1 gives
the link for its `when` (M-4: `report._end_heights` against `stage1._pos`), and the strict count at exactly 3 dB (M-12, the mutant `rb_off`). The references are
written from the published Fresnel formulas (tests/test_round17_d.py) and the sentences are written out here, never taken from the code under test."""
import itertools
import re

import numpy as np
import pytest

from cafe.pm import config, credibility as cr, report, stage1
from cafe.pm.physics import comms, rfband
from tests.test_round17_d import F915, fresnel_loss_db

ROOT = config.ROOT
DEMO = config.load_mission(ROOT / "missions" / "tepex_c_demo.yaml")
HEIGHTS = [0.1, 0.3, 0.5, 1.0, 2.2, 5.0, 10.0, 15.0, 30.0, 60.0, 108.1, 200.0, 400.0, 1000.0]         # the 14 heights of the verifier's 105 pairs
DEMO_HEIGHTS = [0.11, 0.55, 18.1, 38.1, 68.1]                                                         # and five the demo and the cliffs of rounds 17 to 20 use
PAIRS_105 = list(itertools.combinations_with_replacement(HEIGHTS, 2))
PAIRS = list(itertools.combinations_with_replacement(HEIGHTS + DEMO_HEIGHTS, 2))
FREQS = (915e6, 2440e6)
BANNED_WORDS = re.compile(r"bound|up to|at most|everywhere|minimum|maximum", re.I)                 # a limit, or an extreme of a sampled grid


def ref_diff(h1, h2, n=400, f_hz=F915):
    """The model's loss minus the independent Fresnel loss at `n` evenly spaced ranges from 300 m to the pair's radio horizon or 12 km."""
    lo, hi = sorted((h1, h2))
    d = np.linspace(300.0, min(float(comms.radio_horizon_km(lo, hi)) * 1e3, 12e3), n)
    return comms.two_ray_loss_db(d, lo, hi, 0.0, f_hz) - fresnel_loss_db(d, lo, hi, f_hz)


def counts_sentence(over, under):
    """`credibility.band_effect`, written out: the loss overstated (the margin too low) at `over` of the 400 sampled ranges, understated at `under`."""
    if over and under:
        return (f"at {over} of 400 sampled ranges the loss is overstated by more than 3 dB (the margin is too low there) and at {under} understated by "
                "more than 3 dB (the margin is too high there)")
    if over:
        return (f"at {over} of 400 sampled ranges the loss is overstated by more than 3 dB (the margin is too low there), at none is it understated by "
                "more than 3 dB")
    if under:
        return (f"at {under} of 400 sampled ranges the loss is understated by more than 3 dB (the margin is too high there), at none is it overstated by "
                "more than 3 dB")
    return "at none of the 400 sampled ranges is the loss more than 3 dB off"


def figs(h1, h2, f_hz=F915):
    """What the card and L23 print for a pair of heights, from the independent reference."""
    x = ref_diff(h1, h2, 400, f_hz)
    return f"median {float(np.median(x)):+.1f} dB, " + counts_sentence(int(np.sum(x > 3.0)), int(np.sum(x < -3.0)))


NOTE = ("These are figures of the 400 sampled ranges, not of the worst case: at an interference null the model's error is larger than the median, and a "
        "finer sampling of the ranges can find a larger one")


# ----------------------------------------------------------------------------------------------------------------------------------------------- M-1


@pytest.mark.parametrize("f_hz", FREQS)
def test_m1_the_counts_and_the_median_are_the_independent_references_for_105_pairs_and_each_count_is_from_0_to_400(f_hz):
    """`pair_band` gains the two signed counts: strictly more than 3 dB over, strictly more than 3 dB under, of the 400 samples. Over the verifier's 105
    pairs of heights (0.1 to 1000 m), both orders, at both radio frequencies of `radios.yaml`: they are the reference's counts, their sum is the share the
    function already returned, and the median is the reference's. Before: a 4-tuple."""
    for h1, h2 in PAIRS_105:
        x = ref_diff(h1, h2, 400, f_hz)
        want = (int(np.sum(x > 3.0)), int(np.sum(x < -3.0)))
        for got in (rfband.pair_band(h1, h2, f_hz), rfband.pair_band(h2, h1, f_hz)):
            assert len(got) == 6 and got[4:] == want and all(isinstance(n, int) and 0 <= n <= 400 for n in got[4:]), (h1, h2, got)
            assert got[3] == (want[0] + want[1]) / 400 and got[1] == pytest.approx(float(np.median(x)), abs=1e-9), (h1, h2)
            assert got[0] == pytest.approx(float(x.min()), abs=1e-9) and got[2] == pytest.approx(float(x.max()), abs=1e-9)


def test_m12_the_counts_are_strict_at_exactly_3_db_and_each_sign_is_its_own_count(monkeypatch):
    """The mutant `rb_off` (`>` for `>=` at exactly 3 dB survived round 21's tests, which shift the whole band by 2.9999 and 3.0001): one sample at exactly
    +3.0 and one at exactly -3.0 are in neither count, one just beyond either is in its own, and the share is their sum over 400."""
    x = np.zeros(rfband.N_POINTS)
    x[:6] = [3.0, -3.0, 3.0000001, -3.0000001, 3.0000001, 100.0]
    monkeypatch.setattr(comms, "two_ray_loss_db", lambda d, ht, hr, hs, f_hz: x)
    monkeypatch.setattr(rfband, "fresnel_loss_db", lambda d, ht, hr, f_hz: np.zeros_like(d))
    lo, med, hi, share, over, under = rfband.pair_band(2.2, 15.0)
    assert (over, under) == (3, 1) and share == 4 / 400 and (lo, med, hi) == (-3.0000001, 0.0, 100.0)
    x[:6] = [3.0, -3.0, 0.0, 0.0, 0.0, 0.0]
    assert rfband.pair_band(2.2, 15.0)[3:] == (0.0, 0, 0)


@pytest.mark.parametrize("over, under", [(0, 0), (1, 0), (0, 1), (1, 1), (400, 0), (0, 400), (399, 1), (1, 399), (200, 200), (17, 23)])
def test_m1_the_words_follow_the_counts_for_every_combination(over, under):
    """Over only, under only, both, neither: the sentence of `band_effect` is decided by the two counts and by nothing else, and `band_figures` is the median
    and that sentence."""
    assert cr.band_effect(over, under) == counts_sentence(over, under)
    assert cr.band_figures(-1.94, over, under) == "median -1.9 dB, " + counts_sentence(over, under)
    assert cr.band_figures(0.04, over, under).startswith("median +0.0 dB, ")


def test_m1_the_note_that_these_are_not_the_worst_case_is_the_one_sentence():
    assert cr.SAMPLING_NOTE == NOTE


def card_of(monkeypatch, h1, h2, **kw):
    from tests.test_round21_b import note_of
    return note_of(monkeypatch, ("a", ("glider", h1)), ("b", ("glider", h2)), **kw)


def test_m1_the_card_of_every_pair_of_the_grid_prints_the_median_and_the_counts_and_says_it_is_not_the_worst_case_and_no_limit_word(monkeypatch):
    """Before: the card printed 'minimum to maximum dB', 'up to', 'overstated everywhere' and the extremes of the extremes. For the 105 pairs of the verifier
    (two glider-class ends of those heights): the card has its pair's figures as the independent reference gives them, the note, none of the words that call a
    sampled extreme a limit, and no 'x to y dB' range of any two signed figures."""
    for h1, h2 in PAIRS_105:
        note = card_of(monkeypatch, h1, h2)
        lo, hi = sorted((h1, h2))
        assert f"for this pair of heights ({lo:g} m with {hi:g} m): {figs(lo, hi)}. {NOTE}; " in note, (h1, h2)
        assert not BANNED_WORDS.search(note) and not re.search(r"[+-]\d+\.\d to [+-]\d+\.\d dB", note) and "over these pairs" not in note, (h1, h2, note)
        assert len(re.findall(r"median [+-]\d", note)) == 1 and note.endswith("nearer than 300 m this is not stated (CREDIBILITY, limitation L23).")


def test_m1_a_card_for_several_pairs_prints_each_pairs_figures_once_and_no_figure_over_them(monkeypatch):
    from tests.test_round21_b import note_of
    note = note_of(monkeypatch, ("u", ("uas", ([10.0, 100.0], 8.0, 0.1))), ("g", ("glider", 15.0)))
    assert f"by pair of heights: 15 m with 18.1 m {figs(15.0, 18.1)}; 15 m with 108.1 m {figs(15.0, 108.1)}. {NOTE}; " in note
    assert len(re.findall(r"median [+-]\d", note)) == 2 and not BANNED_WORDS.search(note)


def test_m1_l23_prints_the_same_figures_for_its_pairs_and_no_limit_word_and_none_of_the_clauses_that_were_extremes_of_a_grid():
    """L23 is one text: every pair it names has the median and the counts of the independent reference, the note is in it, and no 'up to', 'bound', 'minimum',
    'maximum', 'at most', 'everywhere', no stability-to-0.01-m sentence and no '5.0 dB from 200 m' clause (each a 400-point extreme; the figures of the 400
    samples moved by 4 to 54 dB at a finer sampling)."""
    t = {x["id"]: x for x in cr.LIMITATIONS}["L23"]["text"]
    assert not BANNED_WORDS.search(t), BANNED_WORDS.search(t)
    for pair in (*cr.L23_PAIRS, *cr.L23_UAS_PAIRS):
        assert f"{pair[0]:g} m ({cr.LOW_ANTENNA_NAMES[pair[0]]}) with {pair[1]:g} m ({cr.LOW_ANTENNA_NAMES[pair[1]]}) {figs(*pair)}" in t, pair
    assert NOTE in t and t.startswith("RF links, from an antenna below 0.5 m or the USV's 2.2 m whip to a UAS at 108 m:")
    assert "0.01 m" not in t and "5.0 dB" not in t and "from 200 m" not in t and "It grows with the heights" not in t
    assert not re.search(r"[+-]\d+\.\d to [+-]\d+\.\d dB \(median", t.split("at Hs 1 m")[0])                  # the Hs 0 pairs have no range
    assert t.endswith("nearer than 300 m none of this is stated")


@pytest.fixture(scope="module")
def sweep():
    """{(pair, f): the 400-point and the 40,000-point statistics of the independent reference}: the median, the counts over and under, max |difference|."""
    def stats(x):
        return float(np.median(x)), int(np.sum(x > 3.0)), int(np.sum(x < -3.0)), float(np.abs(x).max())
    return {(p, f): (stats(ref_diff(*p, 400, f)), stats(ref_diff(*p, 40000, f))) for p in PAIRS for f in FREQS}


def test_m1_what_is_printed_is_what_a_hundred_times_finer_sampling_gives_over_the_grid(sweep):
    """The claim of the card: the median and the counts are the sampling's to a tolerance, which the extremes are not. Over 190 pairs of heights (the verifier's
    105 and the demo's) at 915 and 2440 MHz: the printed median is within 0.6 dB of the median at 40,000 sampled ranges (measured on orca: at most 0.59 dB), and
    each count over 400 is within 0.05 of the share of 40,000 (measured: 0.030 over, 0.046 under); the largest |difference| at 40,000 is larger than the printed
    median for every pair, as the note says (that a finer sampling can find a larger one is the next test)."""
    for (p, f), (s400, s40k) in sweep.items():
        assert abs(s400[0] - s40k[0]) <= 0.6, (p, f, s400, s40k)
        assert abs(s400[1] / 400 - s40k[1] / 40000) <= 0.05 and abs(s400[2] / 400 - s40k[2] / 40000) <= 0.05, (p, f, s400, s40k)
        assert s40k[3] > abs(s400[0]), (p, f)


def test_m1_the_extremes_are_the_samplings_not_the_models(sweep):
    """Why they are not printed: there are pairs whose largest |difference| at 40,000 sampled ranges is more than 5 dB beyond that of the 400 (the claim the
    note and the deleted 'bound' rested on is false, and this stays true when the sampling is refined)."""
    assert max(s40k[3] - s400[3] for s400, s40k in sweep.values()) > 5.0


def test_m1_the_hs_1_to_3_figures_l23_prints_are_the_same_at_40000_sampled_ranges_as_at_400():
    """The nine figures of `LOW_ANTENNA_HS_BAND` print a range (the lowest to the highest of the 400): unlike the Hs 0 extremes they are not nulls (the sea's
    roughness takes the nulls out of both curves): the same to 0.1 dB at 40,000 sampled ranges (measured on orca: to 0.01 dB)."""
    from tests.test_round19_b import band_hs, fresnel_hs                        # (imported here: tests/test_round19_b.py imports `figs` from this file)
    for pair, by_hs in cr.LOW_ANTENNA_HS_BAND.items():
        for hs, printed in by_hs.items():
            d = np.linspace(300.0, min(float(comms.radio_horizon_km(pair[0], pair[1])) * 1e3, 12e3), 40000)
            x = comms.two_ray_loss_db(d, pair[0], pair[1], float(hs), F915) - fresnel_hs(d, pair[0], pair[1], float(hs))
            got = (float(x.min()), float(np.median(x)), float(x.max()))
            assert all(abs(g - p) <= 0.1 for g, p in zip(got, printed, strict=True)), (pair, hs, got, printed)
            assert all(abs(g - p) <= 0.1 for g, p in zip(band_hs(pair[1], pair[0], float(hs)), printed, strict=True))


# ----------------------------------------------------------------------------------------------------------------------------------------------- M-4

WHENS = ("always", "surfacing", "uas_airborne")                    # every `when` the mission schema allows on an RF link (config.py)
UAS = [([10.0, 30.0, 60.0, 100.0], 8.0, 0.1), ([10.0], 8.0, 0.1), ([80.0, 350.0], 8.0, 0.1), ([0.0, 25.0], 5.0, 0.2), ([0.1], 0.0, 0.1)]


def stage1_heights(end, spec, mission, when):
    """The set of heights [m] stage 1 gives the antenna of `end` at the samples where the link is required, from `stage1._pos` and the same masks
    `evaluate_link` uses, on a synthetic record: a UAS on the deck, at each level, on the deck again; a glider, a USV or the ship at its one height."""
    cls, val = spec
    t = np.arange(3) * 600.0
    z = np.zeros((3, 1))
    need = np.ones_like(z, bool)
    if cls == "ship":                                                # `_pos` reads the ship from the mission and takes M from any vehicle
        out = {"x": dict(lon=z)}
        mission = dict(mission, ship=dict(mission["ship"], lon=0.0, lat=0.0))
    elif cls == "uas":
        levels, deck, ant = val
        alt, air = [deck], [False]
        for a in levels:
            alt += [deck + a, deck]                                 # the records: `alt` is the deck + the level in flight and the deck on the ground
            air += [True, False]
        t = np.arange(len(alt)) * 60.0
        z = np.zeros((len(t), 1))
        fine = dict(t=t, lon=z, lat=z, alt=np.array(alt)[:, None], depth=z, airborne=np.array(air)[:, None])
        out = {end: {"class": "uas", "t": t, "lon": z, "lat": z, "alt": fine["alt"], "depth": z, "airborne": fine["airborne"], "antenna_m": ant, "fine": fine}}
        need = stage1._airborne(out, end, t) if when == "uas_airborne" else np.ones_like(z, bool)
    else:
        out = {end: {"class": cls, "t": t, "lon": z, "lat": z, "depth": z, "surfaced": np.ones((3, 1), bool), "antenna_m": val}}
    return {round(float(x), 9) for x in stage1._pos(end, out, mission, t)[2][need]}


@pytest.mark.parametrize("when", WHENS)
@pytest.mark.parametrize("spec", [("uas", s) for s in UAS] + [("glider", 0.3), ("usv", 2.2), ("ship", None)], ids=lambda s: str(s[0]) + str(s[1])[:12])
def test_m4_the_heights_the_card_computes_are_the_heights_stage_1_gives_the_link_for_its_when(monkeypatch, when, spec):
    """For every `when` and every end type: `report._end_heights` (the heights the card prints the band of) is the set of heights `stage1._pos` gives the end at
    the samples the link is required at: a UAS end `when: always` or `surfacing` sits on the deck (deck + the antenna's height above the body) between and
    after its sorties as well as at each level; `uas_airborne` is the legs only. Before: the legs for every `when`."""
    from tests.test_round21_b import mission_of
    cls, val = spec
    ends = {"u": ("uas", val)} if cls == "uas" else ({"e": (cls, val)} if cls != "ship" else {})
    mission = mission_of(monkeypatch, ends, ship=15.0)
    end = "ship" if cls == "ship" else next(iter(ends))
    want = stage1_heights(end, spec, mission, when)
    got, read, text = report._end_heights(end, mission, report._classes(mission), when)
    assert read and {round(h, 9) for h in got} == want, (when, spec, got, want)
    if cls == "uas":
        legs = sorted({round(val[1] + a + val[2], 9) for a in val[0]})
        assert text == (f"flown at {', '.join(f'{h:g}' for h in legs)} m" if when == "uas_airborne" else
                        f"on the deck at {val[1] + val[2]:g} m, flown at {', '.join(f'{h:g}' for h in legs)} m")


def test_m4_the_card_of_a_link_always_required_prints_the_deck_pair_and_the_demos_airborne_link_does_not(monkeypatch):
    """The demo's `usv-uas-rf` is `uas_airborne`: legs only (its text is pinned in tests/test_round20_b.py). The same link `when: always` (or with a
    glider at the other end `surfacing`) has the UAS on the deck at 8.1 m (deck 8 + antenna 0.1): the pair of the whip with the deck is on the card."""
    lk = next(lk for lk in DEMO["links"] if lk["id"] == "usv-uas-rf")
    assert lk["when"] == "uas_airborne"
    air = report._low_antenna_note(lk, DEMO)
    assert "on the deck" not in air and "uas (flown at 18.1, 38.1, 68.1, 108.1 m)" in air and "2.2 m with 8.1 m" not in air
    for when in ("always", "surfacing"):
        note = report._low_antenna_note(dict(lk, when=when), DEMO)
        assert "uas (on the deck at 8.1 m, flown at 18.1, 38.1, 68.1, 108.1 m)" in note, when
        for h in (8.1, 18.1, 38.1, 68.1, 108.1):
            assert f"2.2 m with {h:g} m {figs(2.2, h)}" in note, (when, h)
        assert len(re.findall(r"median [+-]\d", note)) == 5 and not BANNED_WORDS.search(note)


def test_m4_a_deck_height_the_band_does_not_cover_is_the_unreadable_end_and_never_a_traceback(monkeypatch):
    """A UAS with deck 0 and an antenna 0 above the body is at 0 m on the ground: below the band's domain (0.1 m): the card says what it says for any height it
    cannot use (reference heights, assumed) when the link is required on the deck, and prints the legs when it is `uas_airborne`."""
    from tests.test_round21_b import has_figure, note_of
    spec = ("uas", ([10.0], 0.0, 0.0))
    for when, usable in (("always", False), ("surfacing", False), ("uas_airborne", True)):
        note = note_of(monkeypatch, ("u", spec), ("g", ("glider", 2.2)), when=when)
        assert has_figure(note), (when, note)
        assert ("u (flown at 10 m)" in note) == usable and ("no single height" in note) == (not usable), (when, note)
