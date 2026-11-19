"""Round 21, the merge step (batches A to D and F merged): the cost of M-3 (a sample whose Thorp margin is beyond the Bellhop excess cap is not refined, the
range grid keeps the old spacing), the two leftovers of batch A (the "no sound-speed profile" label, `need_count_median` over the members that needed the link),
`drag_sigma`'s explicit branch and the untrusted negative index, and a quantity that does not vary in the sensitivity ranking."""
import math
import types

import numpy as np
import pytest

from cafe import hangar, mission
from cafe.pm import report, stage1, vv
from cafe.pm.physics import comms
from tests.test_round21_a import ACOUSTIC, NAMES, _partly_needed, _link
from tests.test_round21_b import built, card_of, PARTLY, run  # noqa: F401  (run is a fixture)
from tests.test_stage1 import MISSION, acoustic_scene, flat_env, km_north, link

CAP = comms.BELLHOP_EXCESS_CAP_DB
Z = np.array([0.0, -100.0, -4000.0])
C = np.array([1500.0, 1490.0, 1520.0])


# ---------------------------------------------------------------------------------------------------------------------- the scene: samples at two ranges
def split_scene(monkeypatch, near_km, far_km, n_near=50, cap=None, available=True, wind=6.0):
    """A glider 5 m down (the ship's transducer is at 5 m: dz 0) at `near_km` for the first `n_near` samples and at `far_km` for the rest, a link `always`
    needed at every sample. Bellhop is a fake that records the largest range of every grid it is given and adds 25 dB over the isovelocity run.
    -> (result of `evaluate_link`, the largest range of each grid asked for [m])."""
    grids = []

    def fake(r, f, z, c, tx, rx, wd):
        grids.append(float(np.max(r)))
        return 20 * np.log10(r) + (25.0 if c[-1] != c[0] else 0.0)
    monkeypatch.setattr(comms, "bellhop_available", lambda: available)
    monkeypatch.setattr(comms, "_run_bellhop", fake)
    if cap is not None:
        monkeypatch.setattr(comms, "BELLHOP_EXCESS_CAP_DB", cap)
    out, _ = acoustic_scene(M=1, far=(0,))
    n = out["glider_eq"]["lat"].shape[0]
    lat = np.full(n, km_north(far_km))
    lat[:n_near] = km_north(near_km)
    out["glider_eq"]["lat"][:] = lat[:, None]
    out["glider_eq"]["depth"][:] = 5.0
    env = flat_env(1, wind=wind)
    env.env.sound_speed = lambda lon, lat, z, t: types.SimpleNamespace(value=1500.0 - 0.02 * np.asarray(z, float))
    return stage1.evaluate_link(link(ACOUSTIC, when="always"), out, MISSION, env, 1, 3, [0]), grids


def thorp_of(monkeypatch, km):
    """The Thorp margin of the slant range at `km` as `evaluate_link` itself computes it (nothing refined: the cap is made negative)."""
    r, grids = split_scene(monkeypatch, km, km, cap=-1.0)
    assert not grids
    return float(r["margin_db"][0, 0])


# ---------------------------------------------------------------------------------------------------------------------- item 2 (a): the cap
def test_a_sample_beyond_the_cap_is_left_on_thorp_is_never_asked_of_bellhop_and_the_label_counts_it(monkeypatch):
    """Before this merge step: every needed in-range sample was refined, so a Bellhop run to 25 km (2 s a call, 6 s to 40 km) was made for samples whose Thorp
    margin is 90 dB below a pass, which the excess held within the cap cannot turn into one."""
    r, grids = split_scene(monkeypatch, 3.0, 25.0, n_near=50)
    n = int(r["need_count"][0])
    assert grids and max(grids) < 3.2e3                                                    # no grid reaches the 25 km samples
    far = comms.acoustic_margin(np.hypot(25e3, 0.0), wind=6.0)
    assert far < -CAP and np.allclose(r["margin_db"][50:, 0], far, atol=1e-3) and (r["margin_db"][:50, 0] > far + 50).all()
    head = "Thorp/Stojanovic budget on the slant range, Bellhop on 50 of 50 needed in-range samples; a further "              # 5 m and 5 m: one run
    assert r["method"].startswith(head)
    assert f"; a further {n - 50} needed in-range samples are more than {CAP:g} dB from a pass or a fail on Thorp and keep that margin: " in r["method"]
    assert "the rest Thorp only" not in r["method"] and r["n_invalid"].tolist() == [0]


def test_a_link_whose_every_needed_sample_is_beyond_the_cap_says_bellhop_was_not_run(monkeypatch):
    r, grids = split_scene(monkeypatch, 25.0, 25.0)
    n = int(r["need_count"][0])
    head = f"Thorp/Stojanovic budget on the slant range; Bellhop was not run: all {n} needed in-range samples are more than "
    assert not grids and r["method"].startswith(head)
    assert "60 dB from a pass or a fail on Thorp" in r["method"]


def test_the_cap_edge_is_the_constant_and_a_sample_exactly_at_it_is_refined(monkeypatch):
    """`abs(margin) > BELLHOP_EXCESS_CAP_DB` skips: a margin exactly at the cap is refined (a positive one at the cap can become exactly 0, which is no pass:
    margin > 0), one ulp beyond is not. Both signs."""
    for km in (1.5, 12.0):
        m = thorp_of(monkeypatch, km)
        assert abs(m) < 100.0
        _, at = split_scene(monkeypatch, km, km, cap=abs(m))
        _, past = split_scene(monkeypatch, km, km, cap=float(np.nextafter(abs(m), 0.0)))
        assert at and not past, (km, m)


def test_a_sample_beyond_the_cap_has_the_same_sign_refined_or_not_and_the_cap_is_as_tight_as_it_can_be(monkeypatch):
    """The proof the skip is verdict-neutral, through the real `acoustic_link` with a Thorp margin made exactly linear (200 minus the range) and a Bellhop
    whose excess is each of -1e6, -cap, -cap/2, 0, cap/2, cap and 1e6 dB: every sample beyond the cap (both ways, and 1e-6 beyond it) keeps the sign of
    its Thorp margin (a pass is margin > 0). And the cap is no looser than needed: at the edge itself and 1e-6 inside it, a refined sample can flip."""
    linear = lambda r, modem="x", band="MF", wind=5.0, shipping=0.5, k=1.5, tl_extra=0.0: 200.0 - np.asarray(r, float) - tl_extra          # noqa: E731
    monkeypatch.setattr(comms, "acoustic_margin", linear)
    monkeypatch.setattr(comms, "bellhop_available", lambda: True)
    targets = np.array([-200.0, -100.0, -CAP - 1e-6, -CAP, -CAP + 1e-6, -1.0, 0.0, 1.0, CAP - 1e-6, CAP, CAP + 1e-6, 100.0])
    flips = {}
    for e in (-1e6, -CAP, -CAP / 2, 0.0, CAP / 2, CAP, 1e6):
        monkeypatch.setattr(comms, "_run_bellhop", lambda r, f, z, c, tx, rx, wd, e=e: np.full(len(r), 100.0 + (e if c[-1] != c[0] else 0.0)))
        out = comms.acoustic_link(200.0 - targets, ssp=(Z, C), ambiguous_db=np.inf)
        thorp, refined = np.asarray(out["thorp_margin"], float), np.asarray(out["margin"].value, float)
        np.testing.assert_allclose(thorp, targets, atol=1e-9)
        for t, m in zip(thorp, refined):
            if abs(t) > CAP:
                assert (m > 0) == (t > 0), (t, e, m)
            elif (m > 0) != (t > 0):
                flips[t] = flips.get(t, 0) + 1
    assert CAP in flips and CAP - 1e-6 in flips and -CAP + 1e-6 in flips                                # inside or at the edge a sample can flip
    assert -CAP not in flips and CAP + 1e-6 not in flips and -CAP - 1e-6 not in flips                    # and none beyond it ever does


def test_a_sample_out_of_range_or_with_a_nan_margin_is_neither_refined_nor_beyond_and_adds_nothing_to_the_label(monkeypatch):
    """Out of range (60 km, beyond 10 x the vendor's 4 km) is no candidate; no wind there is a NaN margin: a lost link, which costs no Bellhop run and is not
    'more than 60 dB from a pass' either."""
    r, grids = split_scene(monkeypatch, 60.0, 60.0)
    assert not grids and r["method"] == comms.THORP_DECIDES_LABEL
    r, grids = split_scene(monkeypatch, 3.0, 3.0, wind=math.nan)
    assert not grids and r["method"] == comms.THORP_DECIDES_LABEL and np.isnan(r["margin_db"]).all() and (r["frac"] == 0.0).all()


def test_the_cap_count_is_summed_over_the_batches_of_a_merged_run(monkeypatch):
    a, _ = split_scene(monkeypatch, 3.0, 25.0, n_near=50)
    b, _ = split_scene(monkeypatch, 25.0, 25.0)
    assert a["bellhop"]["beyond"] == int(a["need_count"][0]) - 50
    assert b["bellhop"] == dict(done=0, total=0, capped=0, beyond=int(b["need_count"][0]), runs_lo=None, runs_hi=None)
    res = stage1.merge([dict(U=np.zeros((1, 1)), X={"a": np.zeros(1)}, vehicles={}, links={ACOUSTIC: x}) for x in (a, b)])
    m = res["links"][ACOUSTIC]["method"]
    nb = int(a["need_count"][0]) - 50 + int(b["need_count"][0])
    assert "Bellhop on 50 of 50 needed in-range samples" in m and f"a further {nb} needed in-range samples are more than 60 dB" in m
    only = stage1.merge([dict(U=np.zeros((1, 1)), X={"a": np.zeros(1)}, vehicles={}, links={ACOUSTIC: x}) for x in (b, b)])
    assert f"Bellhop was not run: all {2 * int(b['need_count'][0])} needed in-range samples" in only["links"][ACOUSTIC]["method"]


# ---------------------------------------------------------------------------------------------------------------------- item 2 (b): the range grid
def grid_of(monkeypatch, lo, hi, **kw):
    seen = []
    monkeypatch.setattr(comms, "_run_bellhop", lambda r, f, z, c, tx, rx, wd: seen.append(np.array(r)) or np.zeros(len(r)))
    comms.bellhop_tl(np.linspace(lo, hi, 7), 18.5, Z, C, **kw)
    return seen[0]


@pytest.mark.parametrize("lo, hi, points", [(100.0, 300.0, 48), (100.0, 2450.0, 48), (100.0, 2451.0, 49), (3000.0, 6000.0, 61), (100.0, 20000.0, 399),
                                           (100.0, 40000.0, 799)])
def test_the_range_grid_is_never_coarser_than_50_m_and_never_has_fewer_than_48_points(monkeypatch, lo, hi, points):
    """Before: 48 points over any span, 0.4 to 0.9 km apart over 20 to 40 km (the excess differed from a 100 m grid by up to 17 dB, tropical profile, orca)."""
    g = grid_of(monkeypatch, lo, hi)
    assert comms.BELLHOP_GRID_M == 50.0 and comms.BELLHOP_GRID_POINTS_MIN == 48
    assert len(g) == points and g[0] == lo and g[-1] == hi and np.diff(g).max() <= comms.BELLHOP_GRID_M + 1e-9


def test_an_explicit_n_grid_is_still_what_was_asked_and_the_range_floor_is_100_m(monkeypatch):
    assert len(grid_of(monkeypatch, 100.0, 40000.0, n_grid=48)) == 48 and len(grid_of(monkeypatch, 100.0, 40000.0, n_grid=400)) == 400
    g = grid_of(monkeypatch, 20.0, 5000.0)
    assert g[0] == 100.0 and len(g) == 99 and np.diff(g).max() <= 50.0 + 1e-9


# ---------------------------------------------------------------------------------------------------------------------- item 3: the label
def test_the_label_never_says_there_is_no_profile_when_there_is_one_and_the_link_has_no_needed_sample_in_range(monkeypatch):
    """Bellhop is available and the environment has a profile. The helper is called with none to get the Thorp margin, and for any sample in its band it said
    'Thorp only, no sound-speed profile supplied': here the NEEDED samples (surfaced) are 45 km away, out of range, and the unneeded ones (submerged, 500 m
    down) sit in the band. Before: that sentence was the method of the link."""
    monkeypatch.setattr(comms, "bellhop_available", lambda: True)
    monkeypatch.setattr(comms, "_run_bellhop", lambda *a: pytest.fail("no sample is needed and in range"))
    out, surf = acoustic_scene(M=1, far=(0,))
    lat = np.full(surf.size, km_north(4.5))
    lat[surf] = km_north(45.0)
    out["glider_eq"]["lat"][:] = lat[:, None]
    env = flat_env(1)
    env.env.sound_speed = lambda lon, lat, z, t: types.SimpleNamespace(value=1500.0 - 0.02 * np.asarray(z, float))
    lk = link(ACOUSTIC)                                                                       # `when: surfacing`
    inband = comms.acoustic_link(np.array([4.5e3]), dz=np.array([500.0]))
    assert inband["ambiguous"].all() and inband["label"] == "Thorp only, no sound-speed profile supplied"   # what the helper alone says of the unneeded ones
    r = stage1.evaluate_link(lk, out, MISSION, env, 1, 3, [0])
    assert r["method"] == comms.THORP_DECIDES_LABEL and "no sound-speed profile" not in r["method"]
    assert r["n_invalid"].tolist() == r["need_count"].tolist()


# ---------------------------------------------------------------------------------------------------------------------- item 3: need_count_median
def test_need_count_median_and_granularity_are_over_the_members_that_needed_the_link():
    """Before: a median over all 48 members, 30 of them with 0 needed samples: 0, so `granularity_ok` False and the card said 'Required at no moment in the
    median member: the link was not exercised in it' for a link 18 members needed at 20 samples each."""
    res, need = _partly_needed(18)
    res["links"]["usv-uas-rf"]["need_count"] = np.where(need, np.resize([18, 20, 22], 48), 0)           # 18, 20 or 22 samples, 0 where never needed
    s = _link(res)
    nc = np.asarray(res["links"]["usv-uas-rf"]["need_count"])[need]
    assert s["need_count_median"] == float(np.median(nc)) == 20 and s["granularity_ok"] is True and s["n_needed"] == 18
    assert np.median(res["links"]["usv-uas-rf"]["need_count"]) == 0                                 # what it was
    few, _ = _partly_needed(18)
    few["links"]["usv-uas-rf"]["need_count"] = np.where(need, 5, 0)                                  # 5 needed samples: one missed is 0.2 of them
    t = _link(few)
    assert t["need_count_median"] == 5 and t["granularity_ok"] is False                              # decided on the members that needed it, not on the zeros


def test_need_count_median_of_a_link_no_member_needed_and_of_one_every_member_needed_are_what_they_were():
    none, _ = _partly_needed(0)
    s = _link(none)
    assert s["need_count_median"] == 0 and s["granularity_ok"] is False and s["verdict"]["verdict"] == stage1.NOT_EXERCISED
    full, _ = _partly_needed(48)
    f = _link(full)
    assert f["need_count_median"] == 20 and f["n_needed"] == 48


def test_the_card_says_which_members_the_median_of_required_samples_is_over(run):  # noqa: F811
    rep, h = built(run, {"usv-uas-rf": dict(PARTLY, n_needed=28)})
    said = "Each member's pass fraction is decided on 30 samples (the median number of required samples among the 28 members that needed the link)"
    assert said in card_of(h)
    rep, h = built(run / "all", {"usv-uas-rf": dict(PARTLY, n_never_required=0, n_needed=48)})
    assert "(the median number of required samples per member)" in card_of(h) and "among the 48" not in card_of(h)
    rep, h = built(run / "old", {"usv-uas-rf": PARTLY})                                              # an older summary: no n_needed, all members
    assert "(the median number of required samples per member)" in card_of(h)


# ---------------------------------------------------------------------------------------------------------------------- item 5: drag_sigma
def fake(resistance=None, drag=None, sources=None, **limits):
    return types.SimpleNamespace(resistance=resistance, drag={i: (0, 0, 0, g) for i, g in enumerate(drag or [])}, sources=sources or {}, limits=limits)


EST = mission.SIG["drag_est"]
CFD = dict(sources=dict(drag="cfd"))


@pytest.mark.parametrize("gcis", [[-0.2], [-0.2, 0.05], [0.05, -1e-12], [-5.0], [0.05, float("nan")], [0.05, None], [0.05, 0.31], [0.05, math.inf]])
def test_any_untrusted_index_among_the_directions_gives_the_estimates_spread_exactly_and_the_hangar_says_so(gcis):
    """Before: a negative index went through `hypot` as its magnitude (-0.2 gave 0.224) and, in `worst_gci`, hid behind a larger one."""
    assert mission.drag_sigma(fake(drag=gcis, **CFD)) == EST
    res = dict(cfd=dict(dirs={f"d{i}": dict(gci=g) for i, g in enumerate(gcis)}))
    assert "the spread of an estimate" in hangar.grid_warning(res)                                # whenever the estimate's spread is taken, the hangar says so


def test_a_negative_index_is_untrusted_everywhere_the_one_reader_is_used():
    assert vv.gci_value(-0.2) == math.inf and vv.gci_value(-0.0) == 0.0 and not vv.gci_trusted(-1e-12) and vv.gci_trusted(-0.0)
    assert vv.worst_gci([-0.2, 0.05]) == math.inf and vv.worst_gci([0.05]) == 0.05
    assert mission.drag_sigma(fake(resistance=1, resistance_gci=-0.1)) == EST and mission.drag_sigma(fake(drag=[0.05], lift_gci=-0.1, **CFD)) == EST


def test_the_branch_leaves_the_trusted_numbers_as_they_were():
    for g in (0.0, 0.05, 0.125, 0.25, 0.283, 0.29, 0.3):
        assert mission.drag_sigma(fake(drag=[g], **CFD)) == pytest.approx(min(math.hypot(0.10, g), EST))
    assert mission.drag_sigma(fake(drag=[], **CFD)) == pytest.approx(0.10) and mission.drag_sigma(fake()) == EST                   # no study: an estimate
    assert mission.drag_sigma(fake(drag=[0.3], **CFD)) == EST                                              # trusted at the bound: no warning
    assert hangar.grid_warning(dict(cfd=dict(dirs={"x": dict(gci=0.3)}))) is None


# ---------------------------------------------------------------------------------------------------------------------- item 6: a quantity that does not vary
def ranking(q, n=48, seed=3):
    U = np.random.default_rng(seed).random((n, len(NAMES)))
    f = np.arange(n) % 5 == 0
    return stage1._sensitivity(NAMES, U, f, set(NAMES), q, "fraction of the required moments the link worked")


@pytest.mark.parametrize("value", [1.0, 0.0, 0.1, -3.7, 1e-12, 1e300])
def test_a_quantity_that_is_the_same_in_every_member_is_said_not_to_vary_and_nothing_is_ranked(value):
    """Before (batch F made first_order return zeros for it): 'No parameter clears the noise floor ... (largest S1 0.000, <the first column>; floor 0.000):
    the sample cannot rank them, which is not the same as none mattering', a ranking of zeros."""
    e = ranking(np.full(48, value))
    assert e["case"] == "constant" and e["param"] is None and e["S1"] == {} and e["noise_floor"] is None and "censored" not in e
    assert e["text"].startswith("The fraction of the required moments the link worked is ") and "does not vary" in e["text"] and "48 members" in e["text"]
    assert "S1" not in e["text"] and "floor" not in e["text"] and "rank them" not in e["text"]


def test_a_quantity_that_is_the_same_in_the_rows_that_have_one_is_constant_and_one_that_differs_by_an_ulp_is_not():
    q = np.full(48, 0.5)
    q[::3] = np.nan                                                                                  # a third of the members have no value
    assert ranking(q)["case"] == "constant" and "32 members" in ranking(q)["text"]
    q[1] = np.nextafter(0.5, 1.0)
    assert ranking(q)["case"] != "constant"
    sparse = np.full(48, np.nan)
    sparse[:stage1.SENS_MIN_N - 1] = 0.5                                                  # fewer finite rows than an index needs: the indicator is ranked
    assert ranking(sparse)["case"] != "constant" and ranking(sparse)["quantity"] == "failure indicator"


def test_a_constant_quantity_of_a_link_some_members_never_needed_names_the_members_it_is_read_from():
    res, need = _partly_needed(24)
    res["links"]["usv-uas-rf"]["frac"] = np.where(need, 0.5, 1.0)                                    # every member that needed the link met half its moments
    res["links"]["usv-uas-rf"]["success"] = ~(np.arange(48) % 3 == 0)
    e = _link(res)["sensitivity"]
    assert e["case"] == "constant" and "among the 24 of 48 members that needed the link" in e["text"] and "0.5 in every one of the 24 members" in e["text"]


def test_the_other_cases_come_first_and_keep_their_texts():
    assert ranking(np.full(48, 1.0))["case"] == "constant"
    U = np.random.default_rng(3).random((48, len(NAMES)))
    assert stage1._sensitivity(NAMES, U, np.zeros(48, bool), set(NAMES), np.full(48, 1.0), "q")["case"] == "all_pass"
    assert stage1._sensitivity(NAMES, U, np.ones(48, bool), set(NAMES), np.full(48, 1.0), "q")["case"] == "all_fail"
    assert stage1._sensitivity(NAMES, U[:8], np.arange(8) < 3, set(NAMES), np.full(8, 1.0), "q")["case"] == "too_few"
    assert stage1._sensitivity(NAMES, U, np.arange(48) < 5, set(), np.full(48, 1.0), "q")["case"] == "no_acting_input"


CONSTANT = dict(param=None, S1={}, noise_floor=None, case="constant", quantity="fraction of the required moments the link worked",
                text="The fraction of the required moments the link worked is 1 in every one of the 48 members it is read from, so it does not vary and no "
                     "parameter can explain it: nothing is ranked.")


def test_the_report_reads_a_constant_quantity_as_one_that_does_not_vary_for_a_link_and_for_a_vehicle(run):  # noqa: F811
    """Most sensitive to, the top-3 line and the noise floor: no 'S1 0.000', no 'none above the noise floor', no clause about a tie among some of the rows."""
    rep, h = built(run, sens={"usv-uas-rf": CONSTANT}, vehicle={"uas": dict(CONSTANT, quantity="lowest battery reserve margin")})
    c = card_of(h)
    assert "Most sensitive to: The fraction of the required moments the link worked is 1 in every one of the 48 members it is read from" in c
    assert "Top sensitivities: none, because the ranked outcome does not vary between the members" in c
    for bad in ("none above the noise floor", "the noise floor at this member count", "S1 0.000", "share the same", "a clip or a ceiling", "rank them"):
        assert bad not in c, bad
    u = card_of(h, "uas")
    assert "does not vary between the members" in u and "none above the noise floor" not in u and "S1 0.000" not in u


def test_top3_and_the_sentence_for_the_other_cases_do_not_change():
    assert "none above the noise floor" in report._top3_html([], None, "q", "nothing_above_floor")
    assert "no sampled input acts" in report._top3_html([], None, "q", "no_acting_input")
    assert "does not vary between the members" in report._top3_html([], None, "q", "constant")


def test_a_censored_record_beside_a_constant_case_is_still_printed_so_that_every_node_is_traceable(run):  # noqa: F811
    """Stage 1 writes none beside the other (it returns first), but an edited summary may: the page prints what report.json holds, the check agrees."""
    rep, h = built(run, sens={"usv-uas-rf": dict(CONSTANT, censored=dict(share=1.0, at="max", value=1.0))})
    assert "share the same highest value" in card_of(h)
