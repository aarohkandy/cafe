"""Round 19, batch A: a link with two glider (or two UAS) ends is required only while EVERY such end is up (M-1), the acting columns of a link with a UAS end
and of the UAS profile share (M-5), and the length of the turbulence series of a hard-stop flight (M-16, A-9)."""
import copy

import numpy as np
import pytest

from cafe.pm import config, credibility, stage1
from cafe.pm.env.protocol import AnalyticEnv
from cafe.pm.physics import uas
from cafe.pm.stats import sampling
from tests.test_stage1 import LK, MISSION, TGRID, flat_env, km_north, merged, track

M = 3
N = TGRID.size
RF = dict(id="g-g-rf", a="g1", b="g2", kind="rf", radio="rfd900x", when="surfacing", required_fraction=0.9)
IRIDIUM = dict(LK["usv-shore-iridium"], id="g-g-iridium", a="g1", b="g2", when="surfacing")
ACOUSTIC = dict(LK["glider_eq-ship-acoustic"], id="g-g-acoustic", a="g1", b="g2", when="surfacing")


def gliders(s1, s2, m=M):
    """Two gliders 2 km apart; each on the surface at the records `s1` and `s2` (index arrays) and at 100 m depth otherwise."""
    out = {}
    for name, idx, lat, ant in (("g1", s1, 0.0, 0.5), ("g2", s2, km_north(2.0), 0.3)):
        surf = np.zeros(N, bool)
        surf[list(idx)] = True
        out[name] = track(-165.0, lat, m, surfaced=surf, antenna=ant, cls="glider", depth=np.where(surf, 0.0, 100.0))
    return out


def run(lk, out, m=M):
    return stage1.evaluate_link(lk, out, MISSION, flat_env(m), m, 3, list(range(m)))


def both_orders(lk, out, m=M):
    return run(lk, out, m), run(dict(lk, a=lk["b"], b=lk["a"]), out, m)


# ---------------------------------------------------------------- M-1: two glider ends
@pytest.mark.parametrize("lk", [RF, IRIDIUM, ACOUSTIC], ids=["rf", "iridium", "acoustic"])
def test_r19_m1_a_link_between_two_gliders_is_required_only_while_both_are_on_the_surface_whichever_is_named_first(lk):
    """The one-glider rule (`_surfaced` took the first glider named and ignored the other): g1 is up at records 0 to 59, g2 at 30 to 89: both are up at 30."""
    out = gliders(range(0, 60), range(30, 90))
    r, rev = both_orders(lk, out)
    assert r["need_count"].tolist() == rev["need_count"].tolist() == [30] * M                                  # before: 60
    assert np.array_equal(r["frac"], rev["frac"]) and np.array_equal(r["success"], rev["success"])
    assert np.isnan(r["margin_db"][:30]).all() and np.isnan(r["margin_db"][60:]).all()                        # no budget while either is under water


def test_r19_m1_the_rf_verdict_of_a_glider_at_depth_is_not_a_finite_margin_and_no_order_passes_vacuously():
    """Reviewer B's scene: g1 always up, g2 never up. Before: g1 first needed all 217 records and g2 first none (a pass by default), and the margin of the
    submerged g2 was a number."""
    out = gliders(range(N), ())
    r, rev = both_orders(RF, out)
    assert r["need_count"].tolist() == rev["need_count"].tolist() == [0] * M
    assert np.isnan(r["margin_db"]).all() and np.isnan(rev["margin_db"]).all() and N == 217


def test_r19_m1_a_link_with_one_glider_end_is_unchanged():
    out = gliders(range(0, 60), ())
    out["ship_like"] = track(-165.0, km_north(1.0), M, antenna=2.2, cls="usv")
    lk = dict(RF, b="ship_like")
    r, rev = both_orders(lk, out)
    assert r["need_count"].tolist() == rev["need_count"].tolist() == [60] * M


def test_r19_m1_a_link_that_is_required_while_a_vehicle_is_up_names_the_run_it_has_none_of():
    """No glider (no UAS) among the ends of a link built by hand: a ConfigError that says so, not a KeyError and not a link that was 'never required'."""
    out = {"usv": track(-165.0, 0.0, M, antenna=2.2, cls="usv")}
    ship = MISSION["ship"]["id"]
    with pytest.raises(stage1.ConfigError, match="neither end is a glider"):
        run(dict(RF, a=ship, b="usv"), out)
    with pytest.raises(stage1.ConfigError, match="neither end is a uas"):
        run(dict(LK_UU, a=ship, b="usv"), out)


def uas_pair(a_air, b_air, fine=False, m=2):
    air = lambda idx: np.isin(np.arange(N), list(idx))
    out = {}
    for name, idx, lat in (("u1", a_air, 0.0), ("u2", b_air, km_north(1.0))):
        out[name] = track(-165.0, lat, m, airborne=air(idx), alt=40.0, antenna=0.1, cls="uas", surfaced=True)
    if fine:                                                                                    # each on its 30 s grid, the second airborne for 21 samples
        tf = TGRID[0] + 6 * 3600.0 + np.arange(0.0, 1201.0, 30.0)
        for name, k in (("u1", tf.size), ("u2", 21)):
            lat = np.full((tf.size, m), 0.0 if name == "u1" else km_north(1.0))
            out[name]["fine"] = dict(t=tf, lon=np.full(lat.shape, -165.0), lat=lat, alt=np.full(lat.shape, 40.0), depth=np.zeros(lat.shape),
                                     airborne=np.broadcast_to((np.arange(tf.size) < k)[:, None], lat.shape).copy())
    return out


LK_UU = dict(id="u-u-rf", a="u1", b="u2", kind="rf", radio="rfd900x", when="uas_airborne", required_fraction=0.95)


def test_r19_m1_a_link_between_two_uas_is_required_only_while_both_fly():
    r, rev = both_orders(LK_UU, uas_pair(range(10, 110), range(60, 160)), 2)
    assert r["need_count"].tolist() == rev["need_count"].tolist() == [50, 50]                                  # before: 100, the first-named UAS's flight alone
    r, rev = both_orders(LK_UU, uas_pair(range(10, 110), range(60, 160), fine=True), 2)
    assert r["need_count"].tolist() == rev["need_count"].tolist() == [21, 21] and np.array_equal(r["t"], rev["t"])   # the sortie grids: u2 flies 21 of u1's 41


def test_r19_m1_the_summary_counts_the_members_that_never_needed_the_link():
    """A member with no required moment has frac 1.0 and passes, so 'never required' reads as 'worked': the count is what a page can say."""
    names = list(stage1.priors_for(MISSION)[1])

    def link(counts):
        res = merged({}, {})
        res["links"]["usv-uas-rf"]["need_count"] = np.asarray(counts)
        return stage1.summarize(res, names, MISSION, 73)["links"]["usv-uas-rf"]
    assert link([30] * 10 + [0] * 14)["n_never_required"] == 14
    assert link(np.full(24, 30))["n_never_required"] == 0
    assert link(np.zeros(24, int))["n_never_required"] == 24
    assert stage1.summarize(merged({}, {}), names, MISSION, 73)["links"]["usv-uas-rf"]["n_never_required"] is None     # a batch without the counts says so


# ---------------------------------------------------------------- M-5: acting columns of a link with a UAS end and of the UAS profile share
CLS = dict(glider_eq="glider", usv="usv", uas="uas")


def test_r19_m5_the_battery_size_acts_on_the_links_of_a_uas_and_nothing_else_about_the_tables_moves():
    rf = LK["usv-uas-rf"]
    assert "battery_capacity_scale" in stage1.link_acts(rf, CLS) and "battery_capacity_scale" in stage1.link_acts(dict(rf, a="uas", b="usv"), CLS)
    assert stage1.link_acts(rf, CLS) == set(stage1.FORCING) | {"usv_vpp_bias", "bulk_stress_scale", "battery_capacity_scale"}
    assert "battery_capacity_scale" not in stage1.link_acts(dict(rf, a="glider_eq", b="ship"), CLS)                  # a glider's track ignores its battery
    assert "battery_capacity_scale" not in stage1.link_acts(dict(rf, b="shore"), CLS)
    assert stage1.TRACK_ACTS["uas"] == ("wind_speed_bias", "wind_direction_bias", "bulk_stress_scale", "battery_capacity_scale")
    assert stage1.ACTS == dict(glider=("glider_speed_scale", "battery_capacity_scale"), usv=("usv_vpp_bias", "solar_yield_scale"),         # `used by` of the
                               uas=("bulk_stress_scale", "battery_capacity_scale"))                                                       # credibility page
    assert credibility.CLASS_PRIORS["battery_capacity_scale"] == "glider|uas"


def test_r19_m5_the_profile_share_lists_the_wind_direction_beside_the_other_columns_that_only_act_at_the_battery_limit():
    row = ("uas", "profile_margin")
    assert "wind_direction_bias" in stage1.UNSEEN[row] and "wind_direction_bias" in stage1.ACTING[row]
    assert set(stage1.UNSEEN[row]) == {"bulk_stress_scale", "battery_capacity_scale", "hs_scale", "wind_direction_bias"}
    assert set(stage1.ACTING[row]) == {"wind_speed_bias"} | set(stage1.UNSEEN[row])
    assert "wind_direction_bias" in stage1.SENS_ACTS["uas"]


def test_r19_m5_the_battery_size_moves_the_moments_a_uas_link_requires_and_the_link_table_lists_it():
    """The 18 h window of reviewer B: the sortie is battery-limited, so the share of the flux pattern it delivers (a step) and with it the required moments
    of `usv-uas-rf` change with the battery scale, which was in no `link_acts`."""
    mission = dict(MISSION, vehicles=[v for v in MISSION["vehicles"] if v["id"] in ("usv", "uas")], links=[LK["usv-uas-rf"]],
                   window=dict(start="2023-03-01T18:00:00Z", end="2023-03-02T12:00:00Z"))
    pri, marg = stage1.priors_for(MISSION)
    env = AnalyticEnv(wind=(-6.0, 2.0), current=(0.15, -0.1), hs=1.0)
    need = []
    for scale in (0.70, 1.00):
        X = {k: np.full(2, float(sampling.marginal(m).ppf(0.5))) for k, m in marg.items()}
        X["battery_capacity_scale"] = np.full(2, scale)
        need.append(int(stage1.run_batch(mission, env, [0, 1], 11, pri, marg, X=X)["links"]["usv-uas-rf"]["need_count"][0]))
    assert need[0] < need[1]                                                                                  # before: 39 against 48
    assert "battery_capacity_scale" in stage1.link_acts(LK["usv-uas-rf"], CLS)


# ---------------------------------------------------------------- M-16 (A-9): the turbulence series of a hard-stop flight
def test_r19_a9_the_turbulence_series_of_a_sortie_covers_its_hard_stop_not_only_its_nominal_duration(ci_full, monkeypatch):
    P = copy.deepcopy(uas.load_platform("quad_uas"))
    so = P["sortie"]
    assert so["hard_stop_factor"] > 1.0
    seen = []
    real = stage1._fewest_boxes
    monkeypatch.setattr(stage1, "_fewest_boxes", lambda args, M: (seen.append(args[6]), real(args, M))[1])
    t = np.array([config.utc("2023-03-02T01:00:00Z").timestamp()])
    stage1._uas_forcing(ci_full, dict(environment=dict(subgrid=dict(turbulence=True))), (-165.0, 0.0), t, P, 2, 5, [0, 1])
    assert seen == [uas.sortie_t_max(so) + 60.0] and seen[0] > so["duration_s"] + 60.0                           # the mutant: duration_s + 60 s
