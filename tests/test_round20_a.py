"""Round 20, batch A: an acoustic link's margin is the lower of Bellhop's two directions, so it does not depend on which end is named first (M-1); the two
tests of round 19's claims that mutants survived (M-10: S1e, the union of two UAS sortie grids; S1g, a member required at one moment is not 'never
required')."""
import types

import numpy as np
import pytest

from cafe.pm import stage1
from cafe.pm.physics import comms
from tests.test_round19_a import LK_UU, both_orders, uas_pair
from tests.test_stage1 import MISSION, TGRID, acoustic_scene, flat_env, km_north, link, merged

KM = 3.5                                       # the glider (1 m deep) and the ship's transducer (5 m): a Thorp margin of +4.07 dB, inside the +-6 dB band
THORP = float(comms.acoustic_margin(np.hypot(KM * 1e3, 4.0), wind=6.0))


def scene(monkeypatch, tl_low_first, tl_high_first, glider_depth=1.0):
    """The glider `glider_depth` m down 3.5 km from the ship (transducer 5 m), `always` judged; Bellhop is a fake whose excess over the isovelocity
    column is `tl_low_first` dB when the shallower transducer sends and `tl_high_first` when the deeper one does (the real one differs by up to
    17.8 dB between the two). Returns the (a = glider, b = ship) and the (a = ship, b = glider) results and the recorded (tx, rx) of every run."""
    calls = []

    def fake(r, f, z, c, tx, rx, wd):
        calls.append((tx, rx))
        return 20 * np.log10(r) + ((tl_low_first if tx < rx else tl_high_first) if c[-1] != c[0] else 0.0)
    monkeypatch.setattr(comms, "bellhop_available", lambda: True)
    monkeypatch.setattr(comms, "_run_bellhop", fake)
    out, _ = acoustic_scene(M=2, far=(0, 0))
    out["glider_eq"]["lat"][:] = km_north(KM)
    out["glider_eq"]["depth"][:] = glider_depth
    env = flat_env(2)
    env.env.sound_speed = lambda lon, lat, z, t: types.SimpleNamespace(value=1500.0 - 0.02 * np.asarray(z, float))
    lk = link("glider_eq-ship-acoustic", when="always")
    ship = MISSION["ship"]["id"]
    res = [stage1.evaluate_link(x, out, MISSION, env, 2, 3, [0, 1]) for x in (lk, dict(lk, a=ship, b="glider_eq"))]
    return res[0], res[1], calls


def test_the_margin_of_an_acoustic_link_does_not_depend_on_which_end_is_named_first(monkeypatch):
    """Before: (a = glider) ran Bellhop with tx 1 m, rx 5 m and (a = ship) with the two swapped, and the fake's two answers differ by 6 dB."""
    assert 0 < THORP <= 6.0
    r, rev, calls = scene(monkeypatch, THORP - 2.0, THORP + 2.0)           # margins +2 (shallow sends) and -2 (deep sends) around zero
    assert np.array_equal(r["margin_db"], rev["margin_db"]) and np.array_equal(r["frac"], rev["frac"])
    assert np.array_equal(r["success"], rev["success"])
    assert np.allclose(r["margin_db"][np.isfinite(r["margin_db"])], -2.0, atol=1e-3)                   # the lower of the two
    assert r["frac"].tolist() == [0.0, 0.0] and not r["success"].any()                                  # before: one order passed (frac 1.0), one failed
    assert sorted(set(calls)) == [(1.0, 5.0), (5.0, 1.0), (5.0, 5.0)]                    # round 21, M-4: and the run with both ends at least 5 m deep


@pytest.mark.parametrize("low_first,high_first", [(7.0, 3.0), (3.0, 7.0), (5.0, 5.0)])
def test_the_margin_is_the_lower_of_the_two_directions_whichever_sends_the_larger_loss(monkeypatch, low_first, high_first):
    r, rev, _ = scene(monkeypatch, low_first, high_first)
    assert np.allclose(r["margin_db"][np.isfinite(r["margin_db"])], THORP - max(low_first, high_first), atol=1e-3)
    assert np.array_equal(r["margin_db"], rev["margin_db"], equal_nan=True)


def test_the_label_says_the_refined_margin_is_the_lower_of_the_two_directions_only_where_bellhop_ran(monkeypatch):
    r, rev, _ = scene(monkeypatch, 7.0, 3.0)
    for x in (r, rev):
        assert x["method"] == ("Thorp/Stojanovic budget on the slant range, Bellhop on 434 of 434 needed in-range samples, "
                               "each member on one pair of transducer depths, not one per sample "  # round 21, M-3 and M-4; the depth sentence: round 22, M-3
                               "(the lowest of 3 runs: as named, swapped, both ends at least 5 m deep)")
    monkeypatch.setattr(comms, "bellhop_available", lambda: False)                          # no Bellhop: the Thorp number, no claim about two directions
    out, _ = acoustic_scene(M=2, far=(0, 0))
    out["glider_eq"]["lat"][:] = km_north(KM)
    out["glider_eq"]["depth"][:] = 1.0
    x = stage1.evaluate_link(link("glider_eq-ship-acoustic", when="always"), out, MISSION, flat_env(2), 2, 3, [0, 1])
    assert "lowest of" not in x["method"]


def test_two_equal_transducer_depths_are_one_bellhop_run_and_the_same_margin(monkeypatch):
    """A glider at 5 m beside the ship's 5 m transducer: the two directions are the same run, so Bellhop runs for the profile and the isovelocity column
    only (2 calls per member and evaluation, not 4)."""
    r, rev, calls = scene(monkeypatch, 7.0, 3.0, glider_depth=5.0)
    assert len(calls) == 8 and set(calls) == {(5.0, 5.0)} and np.array_equal(r["margin_db"], rev["margin_db"], equal_nan=True)   # 2 evaluations x 2 members x 2
    clipped = []
    env = flat_env(1)
    env.env.depth = lambda lon, lat: types.SimpleNamespace(value=np.array([4000.0]))
    env.env.sound_speed = lambda lon, lat, z, t: types.SimpleNamespace(value=1500.0 - 0.02 * np.asarray(z, float))
    monkeypatch.setattr(comms, "_run_bellhop", lambda r, f, z, c, tx, rx, wd: clipped.append((tx, rx)) or 20 * np.log10(r))
    stage1._bellhop_member(env, "benthos_atm960", "MF", -165.0, 0.0, TGRID[0], 0.2, 1.0, np.array([4500.0]), np.zeros(1), np.array([6.0]))
    assert clipped == [(1.0, 1.0)] * 2 + [(5.0, 5.0)] * 2  # 0.2 m is clipped to the 1 m floor, equal to the other: (1, 1) and, round 21 M-4, the 5 m run


def test_a_direction_bellhop_gives_no_number_for_does_not_hide_the_other(monkeypatch):
    """`np.fmin`: a NaN in one direction keeps the other's margin (Bellhop's own failure is an exception, so this is the guard on a non-finite TL)."""
    def fake(r, f, z, c, tx, rx, wd):
        return np.full(np.shape(r), np.nan) if tx < rx else 20 * np.log10(r) + (7.0 if c[-1] != c[0] else 0.0)
    monkeypatch.setattr(comms, "bellhop_available", lambda: True)
    monkeypatch.setattr(comms, "_run_bellhop", fake)
    env = flat_env(1)
    env.env.depth = lambda lon, lat: types.SimpleNamespace(value=np.array([4000.0]))
    env.env.sound_speed = lambda lon, lat, z, t: types.SimpleNamespace(value=1500.0 - 0.02 * np.asarray(z, float))
    m = stage1._bellhop_member(env, "benthos_atm960", "MF", -165.0, 0.0, TGRID[0], 1.0, 5.0, np.array([4500.0]), np.zeros(1), np.array([6.0]))
    assert m is not None and np.isfinite(m.margin).all()


# ---------------------------------------------------------------- S1e: the time axis of a link between two UAS is the union of both sortie grids
def test_s1e_a_link_between_two_uas_is_judged_on_the_union_of_their_sortie_grids_when_the_grids_are_out_of_phase():
    """u1 flies on its 30 s grid from t0 for 20 samples, u2 on a grid 15 s later for 20 samples. Both are up from t0 + 15 s to t0 + 600 s: 19 of u1's
    samples (30 ... 570 s) and 20 of u2's (15 ... 585 s) are moments of both, 39 in the union. Only u1's grid (the mutant that unions the first end alone):
    19, and u2 first: 20."""
    t0 = TGRID[0] + 6 * 3600.0
    out = uas_pair((), (), m=2)
    for name, shift in (("u1", 0.0), ("u2", 15.0)):
        tf = t0 + shift + np.arange(0.0, 1201.0, 30.0)
        lat = np.full((tf.size, 2), 0.0 if name == "u1" else km_north(1.0))
        out[name]["fine"] = dict(t=tf, lon=np.full(lat.shape, -165.0), lat=lat, alt=np.full(lat.shape, 40.0), depth=np.zeros(lat.shape),
                                 airborne=np.broadcast_to((np.arange(tf.size) < 20)[:, None], lat.shape).copy())
    r, rev = both_orders(LK_UU, out, 2)
    union = np.union1d(TGRID, np.union1d(out["u1"]["fine"]["t"], out["u2"]["fine"]["t"]))
    assert np.array_equal(r["t"], union) and np.array_equal(rev["t"], union)                                     # before (u1 only): no u2 sample
    assert r["need_count"].tolist() == rev["need_count"].tolist() == [39, 39]


# ---------------------------------------------------------------- S1g: 'never required' is no required moment at all, not one
def test_s1g_a_member_required_at_exactly_one_moment_is_not_counted_as_never_required():
    names = list(stage1.priors_for(MISSION)[1])

    def count(counts):
        res = merged({}, {})
        res["links"]["usv-uas-rf"]["need_count"] = np.asarray(counts)
        return stage1.summarize(res, names, MISSION, 73)["links"]["usv-uas-rf"]["n_never_required"]
    assert count([1] * 10 + [0] * 14) == 14                                                                   # before (`<= 1`): 24
    assert count(np.ones(24, int)) == 0
    assert count([2] * 10 + [1] * 4 + [0] * 10) == 10
