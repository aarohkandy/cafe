"""Round 21, batch A: stage 1 and Bellhop. M-1 (a link's statistics are about the members that needed it, and a quantity most of whose rows are one value says
so), M-3 (every needed in-range sample is refined, not only those within +-6 dB of 0), M-4 (the margin is the lowest of a stated set of runs and the set's
spread is kept), M-10 (the Bellhop excess is held at an assumed bound)."""
import types

import numpy as np
import pytest

from cafe.pm import stage1
from cafe.pm.physics import comms
from tests.test_stage1 import LK, MISSION, TGRID, acoustic_scene, flat_env, km_north, link, merged

NAMES = list(stage1.priors_for(MISSION)[1])
RF = "usv-uas-rf"
ACOUSTIC = "glider_eq-ship-acoustic"
Z = np.array([0.0, -100.0, -4000.0])
C = np.array([1500.0, 1490.0, 1520.0])


def _col(res, name):
    return res["U"][:, NAMES.index(name)].copy()


def _partly_needed(n_need, n=48, fail_below=0.9):
    """48 members of the RF link: the `n_need` members with the lowest wind_speed_bias draw needed it (the rest have need_count 0 and frac 1.0 by default);
    among those, the pass fraction falls with hs_scale alone. Reviewer C's construction (round 21, C-1)."""
    res = merged({}, {}, n=n)
    w, h = _col(res, "wind_speed_bias"), _col(res, "hs_scale")
    need = np.argsort(np.argsort(w)) < n_need
    lk = res["links"][RF]
    lk["need_count"] = np.where(need, 20, 0)
    lk["frac"] = np.where(need, 1.0 - 0.5 * h, 1.0)
    lk["success"] = lk["frac"] >= fail_below
    return res, need


def _link(res):
    return stage1.summarize(res, NAMES, MISSION, 73)["links"][RF]


# ---------------------------------------------------------------- M-1
def test_m1_the_sensitivity_and_the_pass_fraction_of_a_link_are_those_of_the_members_that_needed_it():
    """Before: all 48 members were ranked, the 30 that never needed the link carrying 1.0, so wind_speed_bias (which decides who needed it) outranked
    hs_scale, which decides who failed, and frac_median was 1.0, a fraction no member that needed the link reached."""
    res, need = _partly_needed(18)
    s = _link(res)
    sens = s["sensitivity"]
    assert sens["case"] == "ranked" and sens["param"] == "hs_scale" and sens["S1"]["hs_scale"] > 0.9 and sens["S1"]["wind_speed_bias"] < 0.5
    assert s["frac_median"] == pytest.approx(float(np.median(res["links"][RF]["frac"][need]))) and s["frac_median"] < 0.9
    assert s["frac_p10"] == pytest.approx(float(np.percentile(res["links"][RF]["frac"][need], 10)))
    assert s["n_needed"] == 18 and s["n_never_required"] == 30 and s["n"] == 48
    assert "among the 18 of 48 members that needed the link" in sens["text"]
    assert s["k_fail"] == int((~res["links"][RF]["success"]).sum()) and s["verdict"]["verdict"] != stage1.NOT_EXERCISED  # the verdict stays on all members


def test_m1_fewer_than_sens_min_n_needed_members_is_too_few_and_the_text_says_how_many_needed_it():
    res, _ = _partly_needed(stage1.SENS_MIN_N - 1)
    sens = _link(res)["sensitivity"]
    assert sens["case"] == "too_few" and sens["param"] is None
    assert sens["text"] == f"The link was needed in only {stage1.SENS_MIN_N - 1} of 48 members: at least {stage1.SENS_MIN_N} are needed to rank the parameters."
    ok, _ = _partly_needed(stage1.SENS_MIN_N)                                                                          # the boundary: 16 needed members rank
    assert _link(ok)["sensitivity"]["case"] == "ranked"


def test_m1_every_needed_member_failing_says_so_and_a_link_no_member_needed_keeps_the_all_member_values():
    res, need = _partly_needed(20)
    res["links"][RF]["success"] = ~need  # every needed member fails, the others pass
    sens = _link(res)["sensitivity"]
    assert sens["case"] == "all_fail" and sens["text"].startswith("Every member that needed the link failed")
    res, _ = _partly_needed(0)
    s = _link(res)
    assert s["n_needed"] == 0 and s["n_never_required"] == 48 and s["verdict"]["verdict"] == stage1.NOT_EXERCISED
    assert s["frac_median"] == float(np.median(res["links"][RF]["frac"])) == 1.0 and s["sensitivity"]["case"] in ("all_pass", "all_fail")


def test_m1_a_link_every_member_needed_and_a_result_without_need_count_give_what_they_gave_before():
    """With no member excluded the subset is the whole: the texts do not mention a subset, and a summary without `need_count` has `n_needed` None."""
    res = merged({}, {RF: 0.25}, n=48)
    old = _link(res)
    assert old["n_needed"] is None and old["n_never_required"] is None and "needed the link" not in old["sensitivity"]["text"]
    res["links"][RF]["need_count"] = np.full(48, 20)
    new = _link(res)
    assert new["n_needed"] == 48 and new["n_never_required"] == 0
    for k in ("frac_median", "frac_p10", "sensitivity", "k_fail", "verdict"):
        assert new[k] == old[k]


@pytest.mark.parametrize("values,at,share,value", [
    ([1.0] * 5 + [0.2, 0.3, 0.4, 0.5, 0.6], None, None, None),  # exactly half of 10 at the maximum: not censored
    ([1.0] * 6 + [0.2, 0.3, 0.4, 0.5, 0.6], "max", 6 / 11, 1.0),                                                       # one more than half
    ([0.0] * 6 + [0.2, 0.3, 0.4, 0.5, 0.6], "min", 6 / 11, 0.0),
    ([0.5] * 11, "max", 1.0, 0.5),                                                                                      # all equal: at the maximum, whole share
    ([0.0] * 4 + [1.0] * 6 + [0.5], "max", 6 / 11, 1.0),  # both ends hold values: the larger share wins
    ([0.0] * 6 + [1.0] * 4 + [0.5], "min", 6 / 11, 0.0),
])
def test_m1_a_ranked_quantity_with_more_than_half_its_rows_at_its_minimum_or_maximum_records_it(values, at, share, value):
    c = stage1._censored(np.array(values))
    if at is None:
        assert c is None
    else:
        assert c == dict(share=pytest.approx(share), at=at, value=value)


def test_m1_censored_is_recorded_by_the_sensitivity_of_any_quantity_and_only_where_an_index_was_computed():
    n = 48
    U = np.random.default_rng(3).random((n, len(NAMES)))
    f = U[:, 0] < 0.3
    q = np.minimum(1.0, 1.4 * U[:, 0])                                                                               # the members that did not fail sit at 1.0
    q = np.where(f, q, 1.0)
    e = stage1._sensitivity(NAMES, U, f, set(NAMES), q, "demo quantity")
    assert e["case"] in ("ranked", "nothing_above_floor") and e["censored"] == dict(share=pytest.approx(float(np.mean(q == 1.0))), at="max", value=1.0)
    assert "censored" not in stage1._sensitivity(NAMES, U, f, set(NAMES), U[:, 0], "demo quantity")                  # a continuous quantity: nothing to say
    nan = np.where(np.arange(n) % 2 == 0, np.nan, q)                                    # half the rows have no value: the share is of the rest
    assert stage1._sensitivity(NAMES, U, f, set(NAMES), nan, "demo quantity")["censored"]["share"] == pytest.approx(float(np.mean(q[1::2] == 1.0)))
    assert "censored" not in stage1._sensitivity(NAMES, U, f, set(NAMES), None, "demo quantity")  # the 0/1 indicator is mostly zeros by nature
    assert "censored" not in stage1._sensitivity(NAMES, U, np.zeros(n, bool), set(NAMES), q, "demo quantity")        # no failure: no index computed
    assert "censored" not in stage1._sensitivity(NAMES, U[:8], f[:8], set(NAMES), q[:8], "demo quantity")            # too few members: none


def test_m1_a_link_with_most_needed_members_at_a_pass_fraction_of_one_records_the_censoring_in_its_summary():
    res, need = _partly_needed(24)
    lk = res["links"][RF]
    lk["frac"] = np.where(need & (_col(res, "hs_scale") > 0.7), 1.0 - 0.5 * _col(res, "hs_scale"), 1.0)                # most needed members pass at 1.0 exactly
    lk["success"] = lk["frac"] >= 0.9
    n1 = int(((lk["frac"] == 1.0) & need).sum())
    assert 2 * n1 > 24
    cens = _link(res)["sensitivity"]["censored"]
    assert cens["at"] == "max" and cens["value"] == 1.0 and cens["share"] == pytest.approx(n1 / 24)                    # of the needed members, not of the 48


def test_m1_nothing_above_the_floor_among_the_needed_members_says_which_members_were_ranked():
    res, need = _partly_needed(20)
    res["links"][RF]["frac"] = np.where(need, np.random.default_rng(7).random(48) * 0.5 + 0.5, 1.0)                   # unrelated to every column
    res["links"][RF]["success"] = res["links"][RF]["frac"] >= 0.9
    sens = _link(res)["sensitivity"]
    assert sens["case"] == "nothing_above_floor"
    assert "for the fraction of the required moments the link worked among the 20 of 48 members that needed the link (" in sens["text"]


def test_m1_a_synthetic_batch_without_acoustic_bookkeeping_has_no_spread_key():
    res = merged({}, {})
    assert "bellhop_spread_db_median" not in stage1.summarize(res, NAMES, MISSION, 73)["links"][RF]


# ---------------------------------------------------------------- the scene: a glider `depth` m down km km from the ship (transducer 5 m), `always` judged
def scene(monkeypatch, km=1.5, depth=5.0, excess=lambda tx, rx: 0.0, available=True, wind=6.0, M=1, lk=None):
    """Bellhop is a fake that records (tx, rx, profile run?) and adds `excess(tx, rx)` dB over the isovelocity run. -> (result, calls, thorp margin of the
    slant path of the first sample)."""
    calls = []

    def fake(r, f, z, c, tx, rx, wd):
        calls.append((float(tx), float(rx), bool(c[-1] != c[0])))
        return 20 * np.log10(r) + (excess(tx, rx) if c[-1] != c[0] else 0.0)
    monkeypatch.setattr(comms, "bellhop_available", lambda: available)
    monkeypatch.setattr(comms, "_run_bellhop", fake)
    out, _ = acoustic_scene(M=M, far=(0,) * M)
    out["glider_eq"]["lat"][:] = km_north(km)
    out["glider_eq"]["depth"][:] = depth
    env = flat_env(M, wind=wind)
    env.env.sound_speed = lambda lon, lat, z, t: types.SimpleNamespace(value=1500.0 - 0.02 * np.asarray(z, float))
    r = stage1.evaluate_link(lk or link(ACOUSTIC, when="always"), out, MISSION, env, M, 3, list(range(M)))
    return r, calls, float(comms.acoustic_margin(np.hypot(km * 1e3, np.mean(depth) - 5.0), wind=wind))


# ---------------------------------------------------------------- M-3
def test_m3_a_needed_in_range_sample_far_outside_the_band_is_refined_and_a_thorp_pass_can_become_a_fail(monkeypatch):
    """Before: a sample whose Thorp margin was above +6 dB never reached Bellhop, so this link passed at 25 dB where Bellhop's own 40 dB of excess fails it."""
    r, calls, thorp = scene(monkeypatch, km=1.5, excess=lambda tx, rx: 40.0)
    assert thorp > 6.0 + 10.0                                                                                          # well outside the +-6 dB band
    assert calls and np.allclose(r["margin_db"], thorp - 40.0, atol=1e-3) and r["frac"].tolist() == [0.0] and not r["success"].any()
    n = int(r["need_count"][0])
    assert r["method"].startswith(f"Thorp/Stojanovic budget on the slant range, Bellhop on {n} of {n} needed in-range samples")
    assert "the rest Thorp only" not in r["method"]


def test_m3_a_thorp_fail_far_below_the_band_is_refined_too_and_a_gain_can_pass_it(monkeypatch):
    r, calls, thorp = scene(monkeypatch, km=12.0, excess=lambda tx, rx: -30.0)
    assert thorp < -6.0 - 10.0 and calls
    assert np.allclose(r["margin_db"], thorp + 30.0, atol=1e-3)


def test_m3_only_needed_samples_in_range_reach_bellhop(monkeypatch):
    far, calls, _ = scene(monkeypatch, km=45.0)  # beyond 10 x the vendor's 4 km: out of range
    assert not calls and far["n_invalid"].tolist() == far["need_count"].tolist() and "Bellhop" not in far["method"]
    near, calls, _ = scene(monkeypatch, km=17.0)                  # in range and within 60 dB of a pass or a fail (round 21 merge: 39 km is beyond)
    assert calls and near["n_invalid"].tolist() == [0]
    beyond, calls, _ = scene(monkeypatch, km=39.0)                  # in range but 100 dB below a pass: Thorp decides it, and the label says Bellhop was not run
    assert not calls and beyond["n_invalid"].tolist() == [0] and "Bellhop was not run" in beyond["method"]
    # a link `when: surfacing`: the 40 samples the glider is submerged are not needed and are not refined; the 60 surfaced ones are
    out, _ = acoustic_scene(M=1, far=(0,))
    out["glider_eq"]["lat"][:] = km_north(2.0)
    env = flat_env(1)
    env.env.sound_speed = lambda lon, lat, z, t: types.SimpleNamespace(value=1500.0 - 0.02 * np.asarray(z, float))
    r = stage1.evaluate_link(LK[ACOUSTIC], out, MISSION, env, 1, 3, [0])
    assert r["need_count"].tolist() == [60] and "Bellhop on 60 of 60 needed in-range samples" in r["method"]


def test_m3_without_bellhop_every_needed_in_range_sample_within_the_cap_is_counted_not_only_those_in_the_old_6_db_band(monkeypatch):
    """Round 22, M-2: this was `test_m3_the_band_stays_where_bellhop_is_not_available`, which pinned "(N ambiguous samples)" for a Thorp margin inside +-6 dB
    and "Thorp budget decides every link" for +18 dB: a link Bellhop would have refined, said to be decided by Thorp."""
    r, calls, thorp = scene(monkeypatch, km=4.5, depth=300.0, available=False)                                          # Thorp margin inside +-6 dB
    n = int(r["need_count"][0])
    tail = f"{n} needed in-range samples that Bellhop would refine keep their Thorp margin"
    assert not calls and r["method"] == f"{comms.THORP_ONLY_LABEL}: {tail}"
    r, calls, thorp = scene(monkeypatch, km=1.5, available=False)                                                       # +18 dB: refined too
    assert not calls and r["method"] == f"{comms.THORP_ONLY_LABEL}: {int(r['need_count'][0])} " + tail.split(" ", 1)[1]


def test_m3_the_helper_keeps_its_own_band_for_its_other_callers(monkeypatch):
    seen = []
    monkeypatch.setattr(comms, "bellhop_available", lambda: True)
    monkeypatch.setattr(comms, "_run_bellhop", lambda r, f, z, c, tx, rx, wd: seen.append(1) or 20 * np.log10(r))
    out = comms.acoustic_link(np.array([1.5e3, 4.5e3]), ssp=(Z, C))
    assert out["ambiguous"].tolist() == [False, True] and len(seen) == 2 and out["method"].tolist() == ["thorp", "bellhop"]
    assert comms.acoustic_link(np.array([1.5e3, 4.5e3]), ssp=(Z, C), ambiguous_db=np.inf)["ambiguous"].tolist() == [True, True]


def test_m3_the_transducer_depths_of_a_member_are_the_median_of_its_refined_samples_not_those_of_the_middle_one(monkeypatch):
    """A link `when: always` to a glider that dives spans its whole cycle: one depth pair stands for all of its samples, and the median is a statement about
    them where the middle sample is an accident (here an excursion to 300 m at exactly the middle one)."""
    out, _ = acoustic_scene(M=1, far=(0,))
    n = TGRID.size
    depth = np.full(n, 5.0)
    depth[n // 2] = 300.0
    calls = []
    monkeypatch.setattr(comms, "bellhop_available", lambda: True)
    monkeypatch.setattr(comms, "_run_bellhop", lambda r, f, z, c, tx, rx, wd: calls.append((tx, rx)) or 20 * np.log10(r))
    out["glider_eq"]["lat"][:] = km_north(3.0)
    out["glider_eq"]["depth"][:, 0] = depth
    env = flat_env(1)
    env.env.sound_speed = lambda lon, lat, z, t: types.SimpleNamespace(value=1500.0 - 0.02 * np.asarray(z, float))
    stage1.evaluate_link(link(ACOUSTIC, when="always"), out, MISSION, env, 1, 3, [0])
    assert set(calls) == {(5.0, 5.0)}  # median 5 m, ship 5 m: one run, not (300, 5)


def test_m3_a_depth_that_is_not_a_number_is_no_range_and_is_not_refined(monkeypatch):
    """`valid` is False for a NaN slant range, so a sample with no depth is out of range and never reaches Bellhop with a NaN depth."""
    out, _ = acoustic_scene(M=1, far=(0,))
    out["glider_eq"]["lat"][:] = km_north(3.0)
    out["glider_eq"]["depth"][:] = np.nan
    calls = []
    monkeypatch.setattr(comms, "bellhop_available", lambda: True)
    monkeypatch.setattr(comms, "_run_bellhop", lambda r, f, z, c, tx, rx, wd: calls.append(1) or 20 * np.log10(r))
    env = flat_env(1)
    env.env.sound_speed = lambda lon, lat, z, t: types.SimpleNamespace(value=1500.0 - 0.02 * np.asarray(z, float))
    r = stage1.evaluate_link(link(ACOUSTIC, when="always"), out, MISSION, env, 1, 3, [0])
    assert not calls and r["n_invalid"].tolist() == r["need_count"].tolist() and np.isnan(r["margin_db"]).all()


# ---------------------------------------------------------------- M-4
@pytest.mark.parametrize("tx,rx,expected", [
    (1.0, 1.0, [(1.0, 1.0), (5.0, 5.0)]),  # two surfaced gliders: (1, 1) and the 5 m run
    (5.0, 5.0, [(5.0, 5.0)]),                                                                                          # equal and deep: one run
    (7.0, 7.0, [(7.0, 7.0)]),
    (1.0, 5.0, [(1.0, 5.0), (5.0, 1.0), (5.0, 5.0)]),
    (5.0, 1.0, [(5.0, 1.0), (1.0, 5.0), (5.0, 5.0)]),
    (1.0, 300.0, [(1.0, 300.0), (300.0, 1.0), (5.0, 300.0)]),
    (300.0, 1.0, [(300.0, 1.0), (1.0, 300.0), (300.0, 5.0)]),
    (5.0, 300.0, [(5.0, 300.0), (300.0, 5.0)]),  # both ends at least 5 m: as named and swapped
    (4.999, 5.0, [(4.999, 5.0), (5.0, 4.999), (5.0, 5.0)]),                                                            # just under the floor
    (10.0, 30.0, [(10.0, 30.0), (30.0, 10.0)]),
])
def test_m4_the_run_set_is_as_named_swapped_and_both_ends_floored_each_pair_once(tx, rx, expected):
    assert stage1._run_set(tx, rx) == expected
    assert comms.BELLHOP_MIN_DEPTH_M == 5.0


def member(monkeypatch, tx, rx, excess, wd=4000.0, d=4500.0):
    """`_bellhop_member` on a column over `wd` m of water; Bellhop a fake whose excess is `excess(tx, rx)`. -> (the _Refined, the (tx, rx) of every run, d)."""
    calls = []

    def fake(r, f, z, c, p, q, w):
        calls.append((float(p), float(q)))
        return 20 * np.log10(r) + (excess(p, q) if c[-1] != c[0] else 0.0)
    monkeypatch.setattr(comms, "bellhop_available", lambda: True)
    monkeypatch.setattr(comms, "_run_bellhop", fake)
    env = flat_env(1)
    env.env.depth = lambda lon, lat: types.SimpleNamespace(value=np.array([wd]))
    env.env.sound_speed = lambda lon, lat, z, t: types.SimpleNamespace(value=1500.0 - 0.02 * np.asarray(z, float))
    d = np.array([d])
    return stage1._bellhop_member(env, "benthos_atm960", "MF", -165.0, 0.0, TGRID[0], tx, rx, d, np.zeros(1), np.array([6.0])), calls, d


def thorp_of(d):
    return float(comms.acoustic_margin(d, wind=6.0)[0])


def test_m4_two_equal_shallow_depths_run_the_set_and_the_margin_is_the_lowest(monkeypatch):
    """Before: (1, 1) was the only run, and Bellhop gives 12 to 34 dB too little loss there (round 21, B-1's own measurement on made-up profiles)."""
    ex = lambda p, q: 0.0 if p < 5.0 else 25.0  # the non-converged shallow run is the optimistic one
    r, calls, d = member(monkeypatch, 1.0, 1.0, ex)
    assert sorted(set(calls)) == [(1.0, 1.0), (5.0, 5.0)] and len(calls) == 4 and r.runs == 2  # two runs, each the profile and the isovelocity column
    assert r.margin[0] == pytest.approx(thorp_of(d) - 25.0) and r.spread[0] == pytest.approx(25.0)


def test_m4_the_lowest_margin_wins_whichever_run_of_the_set_it_is(monkeypatch):
    base = {(1.0, 5.0): 10.0, (5.0, 1.0): 10.0, (5.0, 5.0): 10.0}
    for winner in base:  # each of the three is the lowest margin once
        loss = {**base, winner: 31.0}
        r, _, d = member(monkeypatch, 1.0, 5.0, lambda p, q, loss=loss: loss[(p, q)])
        assert r.margin[0] == pytest.approx(thorp_of(d) - 31.0) and r.spread[0] == pytest.approx(21.0) and r.runs == 3
    r, _, d = member(monkeypatch, 1.0, 5.0, lambda p, q: {(1.0, 5.0): 4.0, (5.0, 1.0): 12.0, (5.0, 5.0): 9.0}[(p, q)])
    assert r.margin[0] == pytest.approx(thorp_of(d) - 12.0) and r.spread[0] == pytest.approx(8.0)


def test_m4_a_single_run_has_no_spread_and_a_run_that_gives_no_number_does_not_hide_the_others(monkeypatch):
    r, calls, d = member(monkeypatch, 5.0, 5.0, lambda p, q: 7.0)
    assert r.runs == 1 and len(calls) == 2 and np.isnan(r.spread).all() and r.margin[0] == pytest.approx(thorp_of(d) - 7.0)
    r, _, d = member(monkeypatch, 1.0, 5.0, lambda p, q: np.nan if (p, q) == (1.0, 5.0) else 7.0)  # one NaN: the other two decide, and give a spread
    assert np.isfinite(r.margin).all() and r.margin[0] == pytest.approx(thorp_of(d) - 7.0) and r.spread[0] == pytest.approx(0.0)
    r, _, d = member(monkeypatch, 1.0, 5.0, lambda p, q: 7.0 if (p, q) == (5.0, 5.0) else np.nan)                       # only one number: no spread
    assert r.margin[0] == pytest.approx(thorp_of(d) - 7.0) and np.isnan(r.spread).all()
    r, _, d = member(monkeypatch, 1.0, 5.0, lambda p, q: np.nan)
    assert np.isnan(r.margin).all() and np.isnan(r.spread).all()


def test_m4_the_floor_runs_inside_shallow_water_and_the_clip_comes_first(monkeypatch):
    r, calls, _ = member(monkeypatch, 0.2, 0.2, lambda p, q: 0.0, wd=12.0)  # 0.2 m is clipped to 1 m, then floored to 5
    assert sorted(set(calls)) == [(1.0, 1.0), (5.0, 5.0)]
    r, calls, _ = member(monkeypatch, 50.0, 50.0, lambda p, q: 0.0, wd=12.0)  # clipped to wd - 1 = 11 m: deeper than the floor, one run
    assert set(calls) == {(11.0, 11.0)} and r.runs == 1


def test_m4_the_label_names_the_set_only_where_more_than_one_run_was_made(monkeypatch):
    two, _, _ = scene(monkeypatch, km=3.0, depth=1.0)                                                           # glider 1 m, ship 5 m: three runs
    n = int(two["need_count"][0])
    assert two["method"] == (f"Thorp/Stojanovic budget on the slant range, Bellhop on {n} of {n} needed in-range samples"
                             ", each member on one pair of transducer depths, not one per sample "
                             "(the lowest of 3 runs: as named, swapped, both ends at least 5 m deep)")
    one, _, _ = scene(monkeypatch, km=3.0, depth=5.0)                                                           # equal 5 m ends: one run
    assert "lowest of" not in one["method"] and "Bellhop on" in one["method"] and "of" in one["method"]
    # no profile (the environment has no ocean): Bellhop is available and refines nothing, so the words are absent (round 21, A-3's mutant)
    out, _ = acoustic_scene(M=1, far=(0,))
    out["glider_eq"]["lat"][:] = km_north(3.0)
    out["glider_eq"]["depth"][:] = 1.0
    env = flat_env(1)
    env.env.ocean = None
    r = stage1.evaluate_link(link(ACOUSTIC, when="always"), out, MISSION, env, 1, 3, [0])
    assert "Bellhop on 0 of" in r["method"] and "lowest of" not in r["method"] and "the rest Thorp only" in r["method"]


def test_m4_the_spread_is_per_sample_and_the_summary_keeps_its_median(monkeypatch):
    r, _, _ = scene(monkeypatch, km=3.0, depth=1.0, excess=lambda tx, rx: {(1.0, 5.0): 4.0, (5.0, 1.0): 12.0, (5.0, 5.0): 9.0}[(tx, rx)])
    sp = r["bellhop_spread_db"]
    assert sp.shape == r["margin_db"].shape and np.allclose(sp[r["need_count"][0] > 0 and np.isfinite(sp)], 8.0)
    res = stage1.merge([dict(U=np.zeros((1, 1)), X={"a": np.zeros(1)}, vehicles={}, links={ACOUSTIC: r})])
    s = stage1.summarize(res, ["a"], MISSION, 73)["links"][ACOUSTIC]
    assert s["bellhop_spread_db_median"] == pytest.approx(8.0)
    one, _, _ = scene(monkeypatch, km=3.0, depth=5.0)                                                           # one run per member: no spread to state
    res = stage1.merge([dict(U=np.zeros((1, 1)), X={"a": np.zeros(1)}, vehicles={}, links={ACOUSTIC: one})])
    assert stage1.summarize(res, ["a"], MISSION, 73)["links"][ACOUSTIC]["bellhop_spread_db_median"] is None
    off, _, _ = scene(monkeypatch, km=3.0, depth=1.0, available=False)                                           # no Bellhop at all: none either
    res = stage1.merge([dict(U=np.zeros((1, 1)), X={"a": np.zeros(1)}, vehicles={}, links={ACOUSTIC: off})])
    assert stage1.summarize(res, ["a"], MISSION, 73)["links"][ACOUSTIC]["bellhop_spread_db_median"] is None


def test_m4_the_margin_of_a_link_does_not_depend_on_which_end_is_named_first_for_two_gliders_at_one_metre(monkeypatch):
    """The sibling of round 20's M-1 that the lower-of-two rule did not reach: two equal depths have no second direction. The set still makes the margin
    the same in both orders (they are the same run set) and at least as low as the 5 m run."""
    ex = lambda p, q: 0.0 if p < 5.0 and q < 5.0 else 25.0  # the non-converged (1, 5) and (5, 1) are not the issue here
    a, _, thorp = scene(monkeypatch, km=3.0, depth=1.0, excess=ex)
    b, _, _ = scene(monkeypatch, km=3.0, depth=1.0, excess=ex, lk=dict(link(ACOUSTIC, when="always"), a="ship", b="glider_eq"))
    assert np.array_equal(a["margin_db"], b["margin_db"], equal_nan=True) and np.array_equal(a["bellhop_spread_db"], b["bellhop_spread_db"], equal_nan=True)
    assert np.allclose(a["margin_db"][np.isfinite(a["margin_db"])], thorp - 25.0, atol=1e-3)


def test_m3_a_member_with_no_profile_there_keeps_its_thorp_margin_and_the_label_counts_only_the_refined_ones(monkeypatch):
    out, _ = acoustic_scene(M=2, far=(0, 0))
    out["glider_eq"]["lat"][:] = km_north(3.0)
    out["glider_eq"]["depth"][:] = 5.0
    out["glider_eq"]["lon"][:, 1] += 0.01                                             # member 1, 1 km east, is where the environment has no depth
    monkeypatch.setattr(comms, "bellhop_available", lambda: True)
    monkeypatch.setattr(comms, "_run_bellhop", lambda r, f, z, c, tx, rx, wd: 20 * np.log10(r) + (30.0 if c[-1] != c[0] else 0.0))
    env = flat_env(2)
    env.env.sound_speed = lambda lon, lat, z, t: types.SimpleNamespace(value=1500.0 - 0.02 * np.asarray(z, float))
    env.env.depth = lambda lon, lat: types.SimpleNamespace(value=np.array([4000.0 if lon < -164.999 else np.nan]))
    r = stage1.evaluate_link(link(ACOUSTIC, when="always"), out, MISSION, env, 2, 3, [0, 1])
    n = int(r["need_count"][0])
    assert r["method"].startswith(f"Thorp/Stojanovic budget on the slant range, Bellhop on {n} of {2 * n} needed in-range samples")
    assert r["method"].endswith("; the rest Thorp only (no sound-speed profile or depth there)")
    d = r["margin_db"]
    thorp = comms.acoustic_margin(np.hypot(np.array([3.0e3, np.hypot(3.0e3, 1.1e3)]), 0.0), wind=6.0)
    assert np.allclose(d[:, 0], thorp[0] - 30.0, atol=0.5) and np.allclose(d[:, 1], thorp[1], atol=0.5)


# ---------------------------------------------------------------- the label of a merged run describes all its members
def test_the_method_of_a_merged_run_counts_every_batch_and_the_runs_of_every_member(monkeypatch):
    a, _, _ = scene(monkeypatch, km=3.0, depth=1.0)                                                              # three runs per member
    b, _, _ = scene(monkeypatch, km=3.0, depth=5.0)                                                              # one
    na, nb = int(a["need_count"][0]), int(b["need_count"][0])
    res = stage1.merge([dict(U=np.zeros((1, 1)), X={"a": np.zeros(1)}, vehicles={}, links={ACOUSTIC: x}) for x in (a, b)])
    m = res["links"][ACOUSTIC]["method"]
    assert f"Bellhop on {na + nb} of {na + nb} needed in-range samples" in m
    assert "(the lowest of 1 to 3 runs: as named, swapped, both ends at least 5 m deep)" in m
    # a batch with no refined sample beside one with: the label is that of the members that ran
    far, _, _ = scene(monkeypatch, km=45.0)
    res = stage1.merge([dict(U=np.zeros((1, 1)), X={"a": np.zeros(1)}, vehicles={}, links={ACOUSTIC: x}) for x in (far, a)])
    assert res["links"][ACOUSTIC]["method"] == a["method"] and res["links"][ACOUSTIC]["bellhop_spread_db"].shape[1] == 2
    # two members' sets of different sizes
    both = dict(a, bellhop=dict(done=1, total=1, capped=0, beyond=0, runs_lo=2, runs_hi=2, ran=True), method="x")
    two = dict(a, bellhop=dict(done=1, total=1, capped=0, beyond=0, runs_lo=3, runs_hi=3, ran=True), method="y")
    res = stage1.merge([dict(U=np.zeros((1, 1)), X={"a": np.zeros(1)}, vehicles={}, links={ACOUSTIC: x}) for x in (both, two)])
    assert "(the lowest of 2 to 3 runs:" in res["links"][ACOUSTIC]["method"] and "Bellhop on 2 of 2 needed" in res["links"][ACOUSTIC]["method"]
    part = stage1._bellhop_label(dict(done=1, total=2, capped=0, beyond=0, runs_lo=None, runs_hi=None, ran=True))
    assert part.endswith("; the rest Thorp only (no sound-speed profile or depth there)")


# ---------------------------------------------------------------- M-10
def fixed(profile_tl, iso_tl):
    """A Bellhop whose TL is a constant: `profile_tl` for the profile run and `iso_tl` for the isovelocity column."""
    return lambda r, f, z, c, tx, rx, wd: np.full(np.shape(r), profile_tl if c[-1] != c[0] else iso_tl)


@pytest.mark.parametrize("excess,margin_excess,capped", [
    (59.99, 59.99, False), (60.0, 60.0, False), (60.01, 60.0, True),                                                      # the bound itself is not capped
    (-59.99, -59.99, False), (-60.0, -60.0, False), (-60.01, -60.0, True),
    (540.0, 60.0, True), (-540.0, -60.0, True), (0.0, 0.0, False),
])
def test_m10_the_bellhop_excess_is_held_within_the_assumed_bound_and_the_sample_is_counted(monkeypatch, excess, margin_excess, capped):
    monkeypatch.setattr(comms, "bellhop_available", lambda: True)
    monkeypatch.setattr(comms, "_run_bellhop", fixed(100.0 + excess, 100.0))
    out = comms.acoustic_link(np.array([4.5e3]), ssp=(Z, C), ambiguous_db=np.inf)
    thorp = float(out["thorp_margin"][0])
    assert out["margin"].value[0] == pytest.approx(thorp - margin_excess) and out["capped"].tolist() == [capped]
    assert comms.BELLHOP_EXCESS_CAP_DB == 60.0


def test_m10_a_field_of_zero_is_a_margin_of_thorp_less_60_db_not_less_540_and_the_label_counts_it(monkeypatch):
    """Before: the zero field was a TL of 600 dB, an excess of about 540 and a margin of about -540."""
    r, calls, thorp = scene(monkeypatch, km=3.0, depth=5.0, excess=lambda tx, rx: 540.0)
    assert thorp > -100 and np.allclose(r["margin_db"], thorp - 60.0, atol=1e-3)
    n = int(r["need_count"][0])
    assert f"; {n} of them held at the assumed 60 dB bound on the Bellhop excess (no ray reached the receiver, or almost none)" in r["method"]
    ok, _, _ = scene(monkeypatch, km=3.0, depth=5.0, excess=lambda tx, rx: 20.0)
    assert "held at" not in ok["method"]
    # a sample counts once however many runs of the set hit the bound
    two, _, _ = scene(monkeypatch, km=3.0, depth=1.0, excess=lambda tx, rx: 540.0)
    assert f"; {int(two['need_count'][0])} of them held" in two["method"]
