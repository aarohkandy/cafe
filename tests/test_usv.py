"""cafe.pm.physics.usv: the VPP, the wave table, the Stage-1 simulator, and receipts that must be able to fail."""
import pathlib
import time

import numpy as np
import pytest
import yaml
from hypothesis import assume, given, settings, strategies as st

from cafe import receipts as R
from cafe.pm import Tagged
from cafe.pm.env import conventions as cv
from cafe.pm.env import perturb, subgrid
from cafe.pm.env.protocol import AnalyticEnv
from cafe.pm.stats.sampling import load_perturbations
from cafe.pm.physics import usv

P = usv.load_platform()
G = usv.G
HR = 3600.0
fin = dict(allow_nan=False, allow_infinity=False)


class DriftEnv(AnalyticEnv):
    """AnalyticEnv with a Stokes drift and a record of the heights the vehicle asked for."""

    def __init__(self, stokes=(0.0, 0.0), **kw):
        super().__init__(**kw)
        self.stokes, self.zs = np.asarray(stokes, float), []

    def wind(self, lon, lat, z, t):
        self.zs.append(("wind", z))
        return super().wind(lon, lat, z, t)

    def current(self, lon, lat, z, t):
        self.zs.append(("current", z))
        return super().current(lon, lat, z, t)

    def waves(self, lon, lat, t):
        w = super().waves(lon, lat, t)
        w["stokes0"] = Tagged(np.broadcast_to(self.stokes, np.shape(w["Hs"].value) + (2,)).copy(), "test", 0.0, "assumed")
        return w


def sim(env, wps=((-165.0, -1.0), (-165.0, 1.0)), m=4, start=None, bias=-0.3, **mission):
    mis = dict(mode="section", waypoints=list(wps))
    mis.update(mission)
    return usv.USVSim(P, m, env, start or wps[0], 0.0, mis, perturb=dict(vpp_bias=np.full(m, bias)))


def ia(deg):
    """Column of the polar at the true wind angle `deg` (the angle axis is not uniform since round 8, M-8: 0.5 deg between 10 and 20)."""
    return int(np.searchsorted(usv.tables(P)[0].twa, deg))


def wind_to(speed, to_deg):
    return cv.vec_from_to(speed, to_deg)


@pytest.fixture
def fresh_tables(monkeypatch):
    """A private table cache so a deliberately broken physics never leaks into other tests."""
    monkeypatch.setattr(usv, "_CACHE", {})


# ------------------------------------------------------------------ platform file

def test_every_number_has_a_source_or_an_assumption():
    raw = yaml.safe_load(pathlib.Path(usv.PLATFORMS / "saildrone_explorer.yaml").read_text())
    for block in ("params", "mission_defaults"):
        for k, leaf in raw[block].items():
            assert "unit" in leaf and (leaf.get("source") or (leaf.get("assumed") is True and leaf.get("why"))), k
    for k in ("rf_antenna_height_m", "iridium_antenna_height_m", "radio_900mhz", "radio_2g4", "iridium_link"):
        assert k in P
    radios = yaml.safe_load((usv.PLATFORMS / "radios.yaml").read_text())
    assert P["radio_900mhz"] in radios["radios"] and P["radio_2g4"] in radios["radios"] and "sbd" in radios["iridium"]
    assert radios["radios"][P["radio_900mhz"]]["center_mhz"] == 915.0 and radios["radios"][P["radio_2g4"]]["center_mhz"] > 2400.0


def test_brief_numbers():
    assert (P["loa_m"], P["wing_span_m"], P["keel_depth_m"], P["anemometer_m"], P["stw_cap_ms"]) == (7.0, 5.0, 2.5, 5.2, 3.3)
    chiodi = (P["chiodi_mean_sog_ms"], P["chiodi_mean_wind_ms"], P["chiodi_max_sog_ms"], P["chiodi_max_wind_ms"])
    assert chiodi == (0.96, 5.4, 2.9, 12.0)


@pytest.mark.parametrize("edit,msg", [
    (lambda p: p["params"]["loa_m"].pop("unit"), "need value and unit"),
    (lambda p: p["params"]["loa_m"].pop("source"), "need a source"),
    (lambda p: p["params"]["lwl_m"].pop("why"), "need a source"),
    (lambda p: p["params"]["loa_m"].update(value="seven"), "is a string"),
    (lambda p: p["mission_defaults"]["wp_radius_m"].pop("why"), "mission_defaults.wp_radius_m"),
])
def test_loader_refuses_incomplete_leaves(tmp_path, edit, msg):
    raw = yaml.safe_load((usv.PLATFORMS / "saildrone_explorer.yaml").read_text())
    edit(raw)
    f = tmp_path / "bad.yaml"
    f.write_text(yaml.safe_dump(raw))
    with pytest.raises(ValueError, match=msg):
        usv.load_platform(str(f))


# ------------------------------------------------------------------ closed forms and property tests

def test_ittc57_value():
    assert np.isclose(usv.cf_ittc57(1e7), 0.075 / 25.0, rtol=1e-12)
    assert np.isclose(usv.cf_ittc57(1e9), 0.075 / 49.0, rtol=1e-12)


@given(st.floats(1e5, 1e9, **fin), st.floats(1.01, 5.0, **fin))
def test_friction_falls_with_reynolds(re, k):
    assert usv.cf_ittc57(re * k) < usv.cf_ittc57(re)


def test_helmbold_limits():
    assert np.isclose(usv.helmbold(1e6), 2 * np.pi, rtol=1e-5)               # infinite span: thin-airfoil 2 pi
    assert np.isclose(usv.helmbold(1e-3), np.pi * 1e-3 / 2, rtol=1e-3)        # vanishing aspect ratio: pi AR / 2 (Jones)


@given(st.floats(0.1, 20, **fin), st.floats(1.01, 3.0, **fin))
def test_helmbold_monotone(ar, k):
    assert usv.helmbold(ar) < usv.helmbold(ar * k) < 2 * np.pi


def test_wing_slope_is_below_the_section_slope():
    ar = P["wing_span_m"] ** 2 / P["wing_area_m2"]
    a = usv.wing_slope(P)
    assert a < P["wing_cl_alpha_2d"] and np.isclose(a, 6.3 / (1 + 6.3 / (np.pi * 0.85 * ar)))


def test_wing_polar_shape():
    s = P["wing_stall_deg"]
    cl_s, cd_s = usv.wing_polar(P, s)
    cl_a, cd_a = usv.wing_polar(P, s + 1e-9)                                   # continuous at stall
    assert np.isclose(cl_s, cl_a, atol=1e-6) and np.isclose(cd_s, cd_a, atol=1e-6)
    assert np.isclose(cl_s, usv.wing_slope(P) * np.radians(s))
    assert usv.wing_polar(P, 25.0)[0] < cl_s                                   # lift collapses past stall
    cl90, cd90 = usv.wing_polar(P, 90.0)
    ar = P["wing_span_m"] ** 2 / P["wing_area_m2"]
    assert abs(cl90) < 1e-9 and np.isclose(cd90, 1.11 + 0.018 * ar)            # normal flat plate: C_Dmax, no lift
    cl0, cd0 = usv.wing_polar(P, 0.0)
    assert cl0 == 0.0 and np.isclose(cd0, P["wing_cd0"])
    trim = usv.wing_polar(P, P["wing_trim_deg"])[0]
    assert 0.6 < trim < cl_s                                                   # trimmed below stall, doing useful work


@given(st.floats(-90, 90, **fin))
def test_wing_polar_symmetry(a):
    cl, cd = usv.wing_polar(P, a)
    cln, cdn = usv.wing_polar(P, -a)
    assert np.isclose(cl, -cln) and np.isclose(cd, cdn) and cd >= P["wing_cd0"] - 1e-12


@given(st.floats(0.05, 3.2, **fin), st.floats(0.0, 1.0, **fin))
def test_hull_resistance_rises_with_speed_and_heel(v, phi):
    assert usv.hull_resistance(P, v + 0.1, phi) > usv.hull_resistance(P, v, phi) > 0
    assert usv.hull_resistance(P, v, phi + 0.1) > usv.hull_resistance(P, v, phi)


def test_hull_resistance_scale():
    # at the cap the hull body is a few hundred newtons, friction-dominated (Fr = 0.41)
    r = usv.hull_resistance(P, 3.3, 0.0)
    assert 100 < r < 400
    fr = 3.3 / np.sqrt(G * P["lwl_m"])
    assert 0.35 < fr < 0.45


@given(st.floats(-5, 5, **fin), st.floats(-5, 5, **fin), st.floats(-5, 5, **fin), st.floats(-5, 5, **fin))
def test_apparent_wind_is_wind_minus_boat_velocity(wx, wy, vx, vy):
    ax, ay = usv._apparent(wx, wy, vx, vy)
    assert np.isclose(ax, wx - vx) and np.isclose(ay, wy - vy)
    assert usv._apparent(wx, wy, 0.0, 0.0) == (wx, wy)


@given(st.floats(-3, 3, **fin), st.floats(-3, 3, **fin), st.floats(0, 1, **fin), st.floats(0, 1, **fin))
def test_lin_reproduces_linear_functions(a, b, u, v):
    ax = (np.linspace(0, 4, 5), np.linspace(-1, 1, 9))
    X, Y = np.meshgrid(*ax, indexing="ij")
    tab = np.stack([a * X + b * Y + 1.0, X - Y], -1)                           # trailing field axis
    x, y = u * 4, -1 + 2 * v
    out = usv._lin(tab, ax, (x, y))
    assert np.allclose(out, [a * x + b * y + 1.0, x - y])
    assert np.allclose(usv._lin(tab, ax, (x + 100, y - 100)), usv._lin(tab, ax, (4.0, -1.0)))     # clamped, not extrapolated
    assert usv._lin(tab[..., 0], ax, (np.full((3, 2), x), np.full((3, 2), y))).shape == (3, 2)


# ------------------------------------------------------------------ the VPP

def run_tw(wind_to_deg, speed, heading, current=(0.0, 0.0)):
    return usv.through_water(P, wind_to(speed, wind_to_deg), np.array(current), heading)


def test_polar_is_physically_ordered():
    pol, _ = usv.tables(P)
    v = pol.f[..., 0]
    assert np.all(v >= 0) and np.all(v <= P["stw_cap_ms"] + 1e-9)
    assert np.all(v[0] == 0)                                                   # no wind, no speed
    assert np.all(v[:, 0] == 0)                                                # head to wind: in irons
    assert np.all(v[3:15, ia(25.0):] > 0)
    best = pol.twa[v[4:12].argmax(1)]
    assert np.all(best > 55) and np.all(best < 130)                            # fastest on a beam to broad reach
    assert np.all(np.diff(v[:11, ia(100.0)]) > 0)                                     # more wind, more speed (to 10 m/s, beam reach)
    assert v[6, ia(180.0)] < v[6, ia(100.0)]                                                 # dead downwind is slower than a beam reach


def test_leeway_is_to_leeward_and_small():
    # wind blows toward the west: from the east = starboard
    r = run_tw(270.0, 6.0, 0.0)
    assert 0.0 < r["stw"] < 3.3 and r["leeway_deg"] < 0 and r["track_to"] > 355.0 and r["track_to"] < 360.0
    r2 = run_tw(90.0, 6.0, 0.0)                                                # from the west = port: mirror image
    assert np.isclose(r2["stw"], r["stw"]) and np.isclose(r2["leeway_deg"], -r["leeway_deg"]) and 0 < r2["track_to"] < 5
    # a beam reach heels little: the lift points forward
    assert abs(r["leeway_deg"]) < 5.0 and r["heel_deg"] > 1.0
    # close-hauled in a fresh breeze: the side force heels it
    close = run_tw(180.0, 12.0, 45.0)
    assert 8.0 < close["heel_deg"] < 25.0 and abs(close["leeway_deg"]) > abs(r["leeway_deg"])


@given(st.floats(0, 360, **fin), st.floats(0.5, 20, **fin), st.floats(0, 360, **fin))
@settings(max_examples=40, deadline=None)
def test_mirror_symmetry(wind_from, speed, heading):
    assume(abs(np.sin(np.radians(wind_from - heading))) > 1e-6)                # wind exactly on the axis is its own mirror image
    w = cv.vec_from_from(speed, wind_from)
    wm = cv.vec_from_from(speed, 2 * heading - wind_from)                      # wind reflected about the boat's axis
    a, b = usv.through_water(P, w, np.zeros(2), heading), usv.through_water(P, wm, np.zeros(2), heading)
    assert np.isclose(a["stw"], b["stw"], atol=1e-9) and np.isclose(a["leeway_deg"], -b["leeway_deg"], atol=1e-9)
    assert np.isclose(a["heel_deg"], b["heel_deg"], atol=1e-9)


@given(st.floats(10, 170, **fin), st.floats(2, 14, **fin))
@settings(max_examples=40, deadline=None)
def test_forces_balance_at_the_root(twa, tws):
    r = run_tw(180.0, tws, twa)                                                # wind from the north, heading `twa` off it
    if r["stw"] > 0.3:
        assert r["resid"] < 0.05 and r["yaw_resid"] < 0.05


def test_heel_and_depower():
    pol, _ = usv.tables(P)
    heel, kd = pol.f[..., 2], pol.f[..., 6]
    assert np.all(heel <= P["heel_target_deg"] + 3.0)                          # the controller holds heel near its target
    # light air: full wing; gale close-hauled: depowered
    assert kd[4, ia(100.0)] == 1.0 and kd[25, ia(50.0)] < 0.9
    # heel follows from the moment balance Delta g GM sin(phi) = M_heel: half the GM, about twice the heel
    wind = wind_to(7.0, 180.0)
    h1 = usv.through_water(P, wind, np.zeros(2), 45.0)["heel_deg"]
    h2 = usv.through_water({**P, "gm_m": 0.6}, wind, np.zeros(2), 45.0)["heel_deg"]
    assert 4.0 < h1 < 20.0 and 1.7 < h2 / h1 < 2.4


def test_current_enters_the_apparent_wind():
    still = run_tw(270.0, 6.0, 0.0)
    withw = run_tw(270.0, 6.0, 0.0, current=(-0.5, 0.0))                       # current toward the west, with the wind
    against = run_tw(270.0, 6.0, 0.0, current=(0.5, 0.0))
    assert withw["stw"] < still["stw"] < against["stw"]                        # relative wind is 5.5, 6, 6.5 m/s
    pol, _ = usv.tables(P)
    tab = usv.through_water_table(P, pol, wind_to(6.0, 270.0), np.array([-0.5, 0.0]), 0.0)
    assert np.isclose(withw["stw"], tab["stw"], atol=0.02)


@given(st.floats(0, 360, **fin), st.floats(0.5, 14, **fin), st.floats(0, 360, **fin), st.floats(0, 0.9, **fin),
       st.floats(0, 360, **fin))
@settings(max_examples=40, deadline=None)
def test_table_equals_direct_coupled_solve(wind_from, speed, heading, cspeed, cdir):
    pol, _ = usv.tables(P)
    w, c = cv.vec_from_from(speed, wind_from), cv.vec_from_to(cspeed, cdir)
    gam = (cv.from_deg(w - c) - heading + 180.0) % 360.0 - 180.0
    # the cliff at the edge of the no-go zone is not interpolable
    assume(abs(gam) > 45.0)
    a, b = usv.through_water(P, w, c, heading), usv.through_water_table(P, pol, w, c, heading)
    assert np.isclose(a["stw"], b["stw"], atol=0.08)
    if a["stw"] > 0.5 and b["stw"] > 0.5:
        assert abs((a["track_to"] - b["track_to"] + 180) % 360 - 180) < 1.5


def test_superposition_is_wrong_in_the_direction_sun_et_al_report():
    stw_r, sog_r = usv.superposition_ratio(P, 6.0, 0.5)
    assert stw_r > sog_r > 1.02                                                # still-water + current overpredicts
    assert usv.superposition_ratio(P, 4.0, 0.8)[0] > 1.2
    assert usv.superposition_ratio(P, 6.0, 0.5, against=True)[1] < 1.0         # and under-predicts for a current against the wind
    assert np.isclose(usv.superposition_ratio(P, 6.0, 0.0)[0], 1.0)


def test_cap_applies_to_the_biggest_gale():
    pol, _ = usv.tables(P)
    assert np.isclose(pol.f[..., 0].max(), P["stw_cap_ms"]) and np.all(pol.f[20:, ia(100.0):ia(150.0), 0] <= P["stw_cap_ms"] + 1e-9)


# ------------------------------------------------------------------ tables and cache

def test_tables_are_cached_in_memory_and_on_disk(tmp_path, fresh_tables):
    a = usv.tables(P)
    assert usv.tables(P) is a
    b = usv.tables(P, tmp_path / "cache")                                      # key already in memory
    assert b is a and not (tmp_path / "cache").exists()
    usv._CACHE.clear()
    c = usv.tables(P, tmp_path / "cache")                                      # built and written
    files = list((tmp_path / "cache").glob("usv_tables_*.npz"))
    assert len(files) == 1
    usv._CACHE.clear()
    d = usv.tables(P, tmp_path / "cache")                                      # read back
    for x, y in zip(c + a, d + c, strict=True):
        for u, v in zip(x, y, strict=True):
            assert np.array_equal(u, v)
    assert usv._digest(P) != usv._digest({**P, "gm_m": 1.3}) and usv._digest(P) == usv._digest({**P, "kind": "other"})


# ------------------------------------------------------------------ waves

def test_strip_theory_follows_long_waves_with_the_right_signs():
    k = 0.3 ** 2 / G
    z, th, raw = usv._strip(P, 0.3, 180.0, 0.0)                                # head seas
    assert np.isclose(z, 1.0, atol=0.03) and np.isclose(th, -1j * k, rtol=0.03)
    # following seas: opposite wave slope seen from the hull
    z2, th2, _ = usv._strip(P, 0.3, 0.0, 0.0)
    assert np.isclose(z2, 1.0, atol=0.03) and np.isclose(th2, 1j * k, rtol=0.03)
    z3, th3, _ = usv._strip(P, 0.3, 90.0, 0.0)                                 # beam seas: no pitch excitation
    assert abs(th3) < 0.05 * k
    assert raw < 1.0                                                           # long waves: no added resistance to speak of


@given(st.floats(0.3, 4.0, **fin), st.floats(0, 180, **fin), st.floats(0, 3.5, **fin))
@settings(max_examples=60, deadline=None)
def test_added_resistance_is_never_negative(w, chi, u):
    assert usv._strip(P, w, chi, u)[2] >= 0.0


def test_added_resistance_head_following_and_scaling():
    _, wt = usv.tables(P)
    head = usv.added_resistance(P, wt, 2.0, 7.0, 180.0, 2.0)
    assert head > 0
    assert usv.added_resistance(P, wt, 2.0, 7.0, 0.0, 2.0) == 0.0 and usv.added_resistance(P, wt, 2.0, 7.0, 90.0, 2.0) == 0.0
    assert np.isclose(usv.added_resistance(P, wt, 4.0, 7.0, 180.0, 2.0), 4 * head)                 # quadratic in Hs
    # short seas hurt
    assert usv.added_resistance(P, wt, 2.0, 5.0, 180.0, 2.0) > head > usv.added_resistance(P, wt, 2.0, 12.0, 180.0, 2.0)
    assert np.isclose(usv.added_resistance(P, wt, 2.0, 7.0, -180.0, 2.0), head)                     # symmetric in the sign of chi
    # newtons: a few percent of the sail force, not a stopper
    assert 1.0 < head < 400.0
    z, th, raw = usv._strip(P, 1.5, 180.0, 2.0)
    assert raw > usv._strip(P, 0.3, 180.0, 2.0)[2]                             # short waves radiate more than long ones


@given(st.floats(3.0, 20.0, **fin))
def test_bretschneider_variance_is_hs_squared_over_16(tp):
    w = np.geomspace(0.1, 12.0, 20000)
    assert np.isclose(np.trapezoid(usv._bretschneider(w, tp), w), 1.0 / 16.0, rtol=0.01)


def test_roll_response():
    s = usv.roll_sigma_deg
    assert s(P, 0.0, 8.0, 90.0) == 0.0 and s(P, 3.0, 8.0, 0.0) < 1e-9          # no waves, or waves along the hull: no roll
    assert np.isclose(s(P, 4.0, 8.0, 90.0), 2 * s(P, 2.0, 8.0, 90.0))
    wn = np.sqrt(G * P["gm_m"]) / P["kxx_roll_m"]
    assert s(P, 2.0, 2 * np.pi / wn, 90.0) > 3 * s(P, 2.0, 20.0, 90.0)         # resonance
    slope = (2 * np.pi / 20.0) ** 2 / G * 2.0 / 4.0
    assert np.isclose(s(P, 2.0, 20.0, 90.0), np.degrees(slope), rtol=0.1)       # long swell: the hull follows the slope


# ------------------------------------------------------------------ the simulator

def test_construction_errors_and_defaults():
    env = AnalyticEnv()
    with pytest.raises(ValueError, match="mode"):
        usv.USVSim(P, 2, env, (0.0, 0.0), 0.0, dict(mode="drift"))
    with pytest.raises(ValueError, match="needs waypoints"):
        usv.USVSim(P, 2, env, (0.0, 0.0), 0.0, dict(mode="section", waypoints=[]))
    s = usv.USVSim(P, 3, env, (0.0, 0.0), 0.0, dict(mode="section", waypoints=[(1.0, 1.0)]))
    assert s.mode == "station" and s.md["becalmed_after_h"] == 6.0 and s.md["track_tolerance_km"] == 20.0
    assert s.lon.shape == (3,) and set(s.fail) == set(usv.FAILS)
    assert np.all(s.fac < 0.8) and np.all(s.fac > 0.7)                         # the calibrated prior: about -24 %


def test_vpp_bias_draw():
    b = usv.draw_vpp_bias(P, 20000, seed=1)
    assert np.isclose(b.mean(), -0.2422, atol=0.001) and np.isclose(b.std(), 0.0082, atol=0.001)
    assert np.array_equal(usv.draw_vpp_bias(P, 5, seed=3), usv.draw_vpp_bias(P, 5, seed=3))
    assert not np.array_equal(usv.draw_vpp_bias(P, 5, seed=3), usv.draw_vpp_bias(P, 5, seed=4))
    a = usv.USVSim(P, 4, AnalyticEnv(), (0.0, 0.0), 0.0, dict(mode="station", station=(0.0, 1.0), seed=7))
    b2 = usv.USVSim(P, 4, AnalyticEnv(), (0.0, 0.0), 0.0, dict(mode="station", station=(0.0, 1.0), seed=7))
    c = usv.USVSim(P, 4, AnalyticEnv(), (0.0, 0.0), 0.0, dict(mode="station", station=(0.0, 1.0), seed=8))
    assert np.array_equal(a.fac, b2.fac) and not np.array_equal(a.fac, c.fac)
    wide = usv.draw_vpp_bias({**P, "vpp_bias_sd": 5.0}, 2000)
    assert wide.min() == -0.9 and wide.max() == 0.5                            # clipped to a sane range


def test_beam_reach_sails_straight_with_leeway_to_the_right_side():
    env = DriftEnv(wind=(-6.0, 0.0), hs=1.0)
    s = sim(env, wps=((-165.0, -1.0), (-165.0, 1.0)), m=3)
    s.run(6 * HR, 60.0)
    assert np.all(s.n_tacks == 0) and np.all(s.lat > -0.85)
    assert np.all(np.abs((s.hd + 180.0) % 360.0 - 180.0) < 15.0)               # northward, within 15 deg of the leg
    assert ("wind", P["anemometer_m"]) in env.zs and ("current", P["current_z_m"]) in env.zs
    assert 0.8 < s.stw.mean() < 1.5 and np.all(s.stw <= 0.7 * 3.3 + 1e-9)    # 1.5 m/s in the polar x the 0.7 prior


def test_upwind_tacks_and_stays_out_of_irons():
    env = AnalyticEnv(wind=(0.0, -6.0), hs=1.0)                                # wind from the north, going north
    s = sim(env, m=4)
    for _ in range(48 * 60):
        s.step(60.0)
        assert np.all(s.vmax >= 0)
    assert np.all(s.n_tacks >= 3)
    assert np.all(s.lat > -0.9) and np.all(s.path_m > 80e3)                    # makes ground to windward
    heading_off_wind = np.abs((s.hd - 0.0 + 180.0) % 360.0 - 180.0)            # wind from 0 deg: angle off the bow = |heading|
    assert np.all(heading_off_wind > 25.0)                                     # never sails in irons
    _, _, xte, _ = s._geom()
    assert np.all(np.abs(xte) < (s.md["corridor_km"] + 3.0) * 1e3)             # held in the corridor


def test_downwind_gybes_to_make_vmg():
    s = sim(AnalyticEnv(wind=(0.0, 6.0), hs=1.0), m=2)                         # wind from the south, going north
    s.run(24 * HR, 60.0)
    assert np.all(s.n_tacks >= 1) and np.all(s.lat > -0.85)
    # the wind blows toward 0 deg: dead downwind is heading 0
    off = np.abs((s.hd + 180.0) % 360.0 - 180.0)
    assert np.all(off > 15.0)                                                  # never dead downwind


def test_bias_scales_speed_and_the_cap_holds():
    env = AnalyticEnv(wind=(-6.0, 0.0), hs=0.0)
    a, b = sim(env, m=2, bias=-0.3), sim(env, m=2, bias=-0.6)
    a.step(60.0), b.step(60.0)
    assert np.allclose(b.stw, a.stw * 0.4 / 0.7, rtol=1e-6)
    g = sim(AnalyticEnv(wind=(-16.0, 0.0), hs=0.0), m=2, bias=0.5)
    g.run(HR, 60.0)
    assert np.all(g.stw <= 3.3 + 1e-9) and np.allclose(g.stw, 3.3)


def test_ground_velocity_is_through_water_plus_current_plus_stokes():
    t = 6 * HR
    # no wind relative to the water
    pure = sim(DriftEnv(wind=(0.3, 0.0), current=(0.3, 0.0)), wps=((-165.0, 0.0), (-160.0, 0.0)), m=1)
    pure.run(t, 60.0)
    de = np.radians(pure.lon[0] + 165.0) * usv.R_E
    assert np.isclose(de, 0.3 * t, rtol=0.02) and abs(pure.lat[0]) < 0.01 and np.isclose(pure.sog[0], 0.3, atol=0.02)
    stokes = sim(DriftEnv(stokes=(0.0, 0.1), wind=(0.0, 0.0)), wps=((-165.0, 0.0), (-160.0, 0.0)), m=1, mode="station",
                 station=(-165.0, 0.0))
    stokes.run(t, 60.0)
    assert np.isclose(np.radians(stokes.lat[0]) * usv.R_E, 0.1 * t, rtol=0.02)


def test_dateline_and_distance():
    m = usv.USVSim._met(np.array([179.9]), np.array([0.0]), np.array([-179.9]), np.array([0.0]))
    assert np.isclose(m[0, 0], np.radians(0.2) * usv.R_E) and abs(m[0, 1]) < 1e-9
    back = usv.USVSim._met(np.array([-179.9]), np.array([0.0]), np.array([179.9]), np.array([0.0]))
    assert np.isclose(back[0, 0], -m[0, 0])
    s = sim(DriftEnv(wind=(2.0, 0.0), current=(2.0, 0.0)), wps=((179.95, 0.0), (-179.0, 0.0)), m=1, start=(179.99, 0.0))
    # almost no relative wind: pure drift east across the dateline
    s.run(HR, 60.0)
    assert -180.0 <= s.lon[0] < 0 and np.isclose(s.lon[0], -180 + (179.99 + np.degrees(2.0 * 3600 / usv.R_E) - 180.0), atol=0.01)


def test_waypoints_arrival_repeat_and_station():
    env = AnalyticEnv(wind=(-8.0, 0.0), hs=0.5)
    s = sim(env, wps=((-165.0, 0.0), (-165.0, 0.2)), m=2, start=(-165.0, 0.0))
    s.run(10 * HR, 60.0)
    # first waypoint passed, then the end
    assert np.all(s.idx == 1) and np.all(np.isfinite(s.arrived)) and np.all(s.arrived > 0)
    r = sim(env, wps=((-165.0, 0.0), (-165.0, 0.2)), m=2, start=(-165.0, 0.0), repeat=True)
    seen = set()
    for _ in range(24 * 60):
        r.step(60.0)
        seen |= set(r.idx.tolist())
    assert seen == {0, 1} and np.all(np.isnan(r.arrived))
    st_ = sim(env, wps=(), m=2, start=(-165.0, 0.3), mode="station", station=(-165.0, 0.0))
    st_.run(24 * HR, 60.0)
    assert np.all(np.isfinite(st_.arrived))
    assert np.all(np.hypot(*usv.USVSim._met(st_.lon, st_.lat, -165.0, 0.0).T) < 20e3)


def test_section_mode_geometry():
    s = sim(AnalyticEnv(), wps=((-165.0, -1.0), (-165.0, 1.0)), m=2, start=(-164.9, -0.5))
    s.idx[:], s.leg_lon[:], s.leg_lat[:] = 1, -165.0, -1.0                    # on the northbound leg
    dist, uhat, xte, nl = s._geom()
    assert np.allclose(nl, [[-1.0, 0.0]] * 2, atol=1e-6)                       # left of a northbound leg is west
    # east of the line: negative
    assert np.allclose(xte, -np.radians(0.1) * usv.R_E * np.cos(np.radians(-0.75)), rtol=1e-3)
    assert np.allclose(dist, np.hypot(np.radians(0.1) * usv.R_E, np.radians(1.5) * usv.R_E), rtol=2e-3)
    assert np.all(uhat[:, 1] > 0.9) and np.allclose(np.hypot(uhat[:, 0], uhat[:, 1]), 1.0)


# ------------------------------------------------------------------ failure flags

def first_h(s, name):
    return float(np.nanmin(s.first[name])) / HR if s.fail[name].any() else None


def test_becalmed_needs_n_hours_and_a_current():
    stn = dict(mode="station", station=(-165.0, -1.0), start=(-165.0, -1.0))
    calm = sim(AnalyticEnv(wind=(-0.5, 0.0), current=(0.5, 0.0)), m=3, **stn)
    calm.run(12 * HR, 300.0)
    assert np.all(calm.fail["becalmed"]) and 6.0 <= first_h(calm, "becalmed") < 6.2
    s2 = sim(AnalyticEnv(wind=(-0.5, 0.0), current=(0.5, 0.0)), m=1, becalmed_after_h=2.0, **stn)
    s2.run(4 * HR, 300.0)
    assert 2.0 <= first_h(s2, "becalmed") < 2.2                                # the mission value overrides the default
    brisk = sim(AnalyticEnv(wind=(-8.0, 0.0), current=(0.5, 0.0)), m=3)
    brisk.run(12 * HR, 300.0)
    assert not brisk.fail["becalmed"].any()
    nocur = sim(AnalyticEnv(wind=(-0.5, 0.0)), m=3)
    nocur.run(12 * HR, 300.0)
    assert not nocur.fail["becalmed"].any()                                    # light air alone is not becalmed: nothing to stem


def with_sde(env, m, seconds, dt):
    """`env` under the ocean SDE only (no forcing error): m members, steps of dt over `seconds`."""
    pri = load_perturbations()
    pri["current_speed_scale"]["value"] = pri["current_direction_bias"]["value"] = 0.0
    return perturb.PerturbedEnv(env, {}, list(range(m)), 5, pri, sde=dict(t0=0.0, t1=seconds, dt=dt))


def test_spurs2_still_sweeps_and_becalms_with_the_ocean_sde_on():
    """The SDE moves the position, not the current the USV senses: the noisy |current| must not reset the becalmed counter."""
    env = with_sde(AnalyticEnv(wind=(-0.2, 0.0), current=(0.9, 0.0), hs=0.5), 16, 24 * HR, 300.0)
    s = sim(env, m=16, mode="station", station=(-125.0, 10.0), start=(-125.0, 10.0))
    s.run(24 * HR, 300.0)
    assert np.all(s.fail["becalmed"]) and np.all(s.fail["swept_off_track"]) and 6.0 <= first_h(s, "becalmed") < 12.0


def test_the_sde_moves_the_position_by_a_random_walk_and_leaves_every_steering_input_alone():
    m, n, dt = 400, 200, 60.0
    base = AnalyticEnv(wind=(-6.0, 0.0), hs=1.0)
    off, on = sim(base, m=m), sim(with_sde(base, m, n * dt, dt), m=m)
    d = on.env.sde_displacement(on.lon, on.lat, 0.0)
    off.step(dt)
    on.step(dt)
    for k in ("hd", "stw", "sog", "vmax", "path_m"):
        assert np.array_equal(getattr(off, k), getattr(on, k)), k                                    # steering, speeds and failure inputs: identical
    assert all(np.array_equal(off.acc[k], on.acc[k]) for k in off.acc)
    got = np.stack([np.radians(on.lon - off.lon) * np.cos(np.radians(on.lat)), np.radians(on.lat - off.lat)], -1) * usv.R_E
    assert np.allclose(got, d, atol=1e-2) and d.std() > 10.0                                           # position differs by exactly the step's displacement
    for _ in range(n - 1):
        off.step(dt)
        on.step(dt)
    dx = (np.radians(on.lon - off.lon) * np.cos(np.radians(on.lat)) * usv.R_E)
    var = 2 * float(subgrid.sde_diffusivity(-1.0)[0]) * n * dt
    assert np.isclose(dx.var(), var, rtol=0.3) and abs(dx.mean()) < 4 * np.sqrt(var / m)             # a random walk of variance 2Kt, no mean drift


def test_becalmed_counter_resets_when_the_wind_comes_back():
    class Gusty(AnalyticEnv):
        def wind(self, lon, lat, z, t):
            w = super().wind(lon, lat, z, t)
            return Tagged(w.value * (0.05 if (t // (3 * HR)) % 2 == 0 else 1.0), "t", 0.0, "assumed")
    s = sim(Gusty(wind=(-8.0, 0.0), current=(0.5, 0.0)), m=1)
    s.run(24 * HR, 300.0)
    assert not s.fail["becalmed"].any()                                        # 3 h lulls never add up to 6 h


def test_swept_off_track_station_and_section():
    cur = AnalyticEnv(wind=(-0.2, 0.0), current=(0.9, 0.0), hs=0.5)
    st_ = sim(cur, m=3, mode="station", station=(-125.0, 10.0), start=(-125.0, 10.0))
    st_.run(12 * HR, 300.0)
    assert 20e3 / 0.9 / HR < first_h(st_, "swept_off_track") < 8.0             # 20 km at about 0.9 m/s
    sec = sim(AnalyticEnv(wind=(-4.0, 0.0), current=(0.9, 0.0), hs=0.5), m=2)
    sec.run(12 * HR, 300.0)
    assert sec.fail["swept_off_track"].all()                                   # cross-track current beats a 4 m/s beam wind
    ok = sim(AnalyticEnv(wind=(-6.0, 0.0), hs=0.5), m=2)
    ok.run(12 * HR, 300.0)
    assert not ok.fail["swept_off_track"].any()


def test_capsize_proxy_needs_wind_and_steep_beam_seas():
    # steep beam seas (waves go west, vehicle north)
    gale = sim(AnalyticEnv(wind=(-14.0, 0.0), hs=5.0, tp=5.0, wave_to=270.0), m=2)
    gale.run(HR, 60.0)
    assert gale.fail["capsize_proxy"].all() and first_h(gale, "capsize_proxy") <= 0.02
    # waves from the north: along the hull
    head = sim(AnalyticEnv(wind=(-14.0, 0.0), hs=5.0, tp=5.0, wave_to=180.0), m=2)
    head.run(HR, 60.0)
    assert not head.fail["capsize_proxy"].any()
    calm = sim(AnalyticEnv(wind=(-6.0, 0.0), hs=1.0, tp=8.0, wave_to=270.0), m=2)
    calm.run(HR, 60.0)
    assert not calm.fail["capsize_proxy"].any()


def test_wing_stall_calm_sustained_in_light_air_only():
    s = sim(AnalyticEnv(wind=(-1.0, 0.0)), m=2)
    s.run(2 * HR, 60.0)
    assert 0.5 <= first_h(s, "wing_stall_calm") < 0.6                          # calm_sustain_s = 30 min
    brisk = sim(AnalyticEnv(wind=(-6.0, 0.0)), m=2)
    brisk.run(2 * HR, 60.0)
    assert not brisk.fail["wing_stall_calm"].any()
    longer = sim(AnalyticEnv(wind=(-1.0, 0.0)), m=2, calm_sustain_s=3 * HR)    # the calm clause has its own clock
    longer.run(2 * HR, 60.0)
    assert not longer.fail["wing_stall_calm"].any()


def test_the_bow_cone_clause_has_its_own_angle_and_mode():
    """Review round 3, M-8: the cone clause used wing_stall_deg, the wing's stall angle of attack; it has min_awa_deg now, and fires as wing_stall_angle."""
    tight = usv.USVSim(dict(P, min_awa_deg=180.0), 2, AnalyticEnv(wind=(-6.0, 0.0)), (-165.0, -1.0), 0.0,
                       dict(mode="section", waypoints=[(-165.0, -1.0), (-165.0, 1.0)]), perturb=dict(vpp_bias=np.full(2, -0.3)))
    tight.run(2 * HR, 60.0)
    assert tight.fail["wing_stall_angle"].all() and not tight.fail["wing_stall_calm"].any() and 0.5 <= first_h(tight, "wing_stall_angle") < 0.6
    off = usv.USVSim(dict(P, min_awa_deg=0.0), 2, AnalyticEnv(wind=(-6.0, 0.0)), (-165.0, -1.0), 0.0,
                     dict(mode="section", waypoints=[(-165.0, -1.0), (-165.0, 1.0)]), perturb=dict(vpp_bias=np.full(2, -0.3)))
    off.run(2 * HR, 60.0)
    assert not off.fail["wing_stall_angle"].any()
    assert "wing_stall" not in usv.FAILS and {"wing_stall_calm", "wing_stall_angle"} <= set(usv.FAILS)
    assert P["min_awa_deg"] == 15.0 and P["wing_stall_deg"] == 15.0 and 0.0 < usv.load_platform()["mission_defaults"]["calm_sustain_s"] == 1800.0


def test_a_boat_that_cannot_move_in_still_water_is_becalmed_in_a_zero_current():
    """Review round 3, M-8: `vmax < speed(current)` was `0 < 0` with no wind and no current, so the dead calm was a wing stall and never becalmed."""
    dead = sim(AnalyticEnv(wind=(0.0, 0.0), current=(0.0, 0.0)), m=2)
    dead.run(24 * HR, 600.0)
    assert dead.fail["becalmed"].all() and dead.fail["wing_stall_calm"].all()
    assert first_h(dead, "becalmed") == pytest.approx(P["mission_defaults"]["becalmed_after_h"], abs=0.2)
    drifting = sim(AnalyticEnv(wind=(0.0, 0.0), current=(0.01, 0.0)), m=2)
    drifting.run(24 * HR, 600.0)
    assert drifting.fail["becalmed"].all()
    brisk = sim(AnalyticEnv(wind=(-6.0, 0.0), current=(0.0, 0.0)), m=2)
    brisk.run(24 * HR, 600.0)
    assert not brisk.fail["becalmed"].any()


def test_battery_drains_at_night_and_charges_by_day():
    n = sim(AnalyticEnv(wind=(-6.0, 0.0), swdown=0.0), m=2)
    n.run(60 * HR, 600.0)
    t_empty = P["battery_wh"] / P["hotel_w"]
    assert t_empty - 0.2 <= first_h(n, "battery") <= t_empty + 0.3 and np.all(n.soc_wh == 0.0)
    d = sim(AnalyticEnv(wind=(-6.0, 0.0), swdown=800.0), m=2)
    d.run(60 * HR, 600.0)
    assert not d.fail["battery"].any() and np.all(d.soc_wh == P["battery_wh"])                 # +320 W - 80 W, clipped at full
    assert np.isclose(sim(AnalyticEnv(), m=1).soc_wh[0], P["soc0"] * P["battery_wh"])


def test_waves_slow_the_boat_in_head_seas_only():
    # travelling south toward a northbound boat
    head = sim(AnalyticEnv(wind=(-6.0, 0.0), hs=4.0, tp=5.0, wave_to=180.0), m=1)
    calm = sim(AnalyticEnv(wind=(-6.0, 0.0), hs=0.0, tp=5.0, wave_to=180.0), m=1)
    follow = sim(AnalyticEnv(wind=(-6.0, 0.0), hs=4.0, tp=5.0, wave_to=0.0), m=1)
    hd = np.array([[0.0]])
    c = lambda s_: dict(tws=np.array([6.0]), wfrom=np.array([90.0]), hs=np.array([s_.env.hs]), tp=np.array([5.0]),
                        wdir=np.array([s_.env.wave_to]))
    v = [s_._eval(hd, c(s_))["v"][0, 0] for s_ in (head, calm, follow)]
    assert v[0] < v[1] and np.isclose(v[2], v[1])
    chi = head._eval(hd, c(head))["chi"][0, 0]
    assert np.isclose(chi, 180.0) and np.isclose(follow._eval(hd, c(follow))["chi"][0, 0], 0.0)


def test_history_and_record_interval():
    s = sim(AnalyticEnv(wind=(-6.0, 0.0)), m=3)
    h = s.run(5 * HR, 300.0, record_s=HR)
    assert h["lon"].shape == (5, 3) and h["t"].shape == (5,) and np.all(np.diff(h["t"]) >= HR) and h["t"][-1] <= 5 * HR
    assert set(h["first"]) == set(usv.FAILS) and h["n_tacks"].shape == (3,) and h["soc_wh"].shape == (5, 3)


def test_deterministic_for_a_seed():
    def go(seed):
        s = usv.USVSim(P, 6, AnalyticEnv(wind=(0.0, -6.0), hs=1.0), (-165.0, -1.0), 0.0,
                       dict(mode="section", waypoints=[(-165.0, -1.0), (-165.0, 1.0)], seed=seed))
        s.run(12 * HR, 120.0)
        return s.lat.copy(), s.fac.copy()
    a, b, c = go(1), go(1), go(2)
    assert np.array_equal(a[0], b[0]) and not np.array_equal(a[1], c[1]) and not np.array_equal(a[0], c[0])


def test_256_members_one_day_is_fast():
    env = AnalyticEnv(wind=(-6.0, 1.0), current=(0.3, 0.1), hs=1.5, tp=9.0, wave_to=270.0)
    s = usv.USVSim(P, 256, env, (-165.0, -1.0), 0.0, dict(mode="section", waypoints=[(-165.0, -1.0), (-165.0, 1.0)], repeat=True))
    t = time.time()
    s.run(86400.0, 60.0)
    # 7 days measured at ~18 s on 2 CPUs, so 1 day is ~3 s
    assert time.time() - t < 15.0


# ------------------------------------------------------------------ receipts, and the ways they must fail

def run_receipts(P_=None):
    """Run usv.receipts and return {claim: entry} for the group, restoring the shared list."""
    saved = list(R.OUT)
    R.OUT.clear()
    try:
        usv.receipts(P_)
        return {e["claim"]: e for e in R.OUT if e["group"] == "usv"}
    finally:
        R.OUT[:] = saved


MEAN_ROW = "mean SOG / U at 5.4 m/s (VMG routing, all bearings, prior bias; CALIBRATED: vpp_bias_mean)"
POLAR_ROW = "best-heading still-water speed at 12 m/s, polar without the VPP bias (CALIBRATED: appendage_cda_m2; not what Stage 1 flies)"
FLOWN_ROW = "best-heading speed at 12 m/s as Stage 1 flies it (polar x (1 + vpp_bias_mean))"


def failed(res):
    return {c for c, e in res.items() if e["ok"] is False}


def test_receipts_pass_and_are_numbers_not_stubs():
    res = run_receipts()
    assert failed(res) == set(), failed(res)
    checked = [e for e in res.values() if e["ok"] is not None]
    assert len(checked) >= 15 and len([e for e in res.values() if e.get("kind") == "context"]) == 3
    mean = res[MEAN_ROW]
    assert 0.8 * 0.178 < mean["value"] < 1.2 * 0.178
    assert 2.6 < res[POLAR_ROW]["value"] < 3.2
    assert res["SPURS-2: becalmed first fires (h)"]["value"] >= 6.0 - 1e-6


def test_receipt_fails_when_current_is_added_after_the_solve(fresh_tables, monkeypatch):
    orig = usv.through_water
    monkeypatch.setattr(usv, "through_water", lambda p, w, c, h: orig(p, w, 0.0 * np.asarray(c), h))
    bad = failed(run_receipts())
    assert "still-water VPP + current / current-coupled SOG (6 m/s wind, 0.5 m/s current with it)" in bad


def test_receipt_fails_when_the_current_sign_is_flipped(fresh_tables, monkeypatch):
    orig = usv.through_water
    monkeypatch.setattr(usv, "through_water", lambda p, w, c, h: orig(p, w, -np.asarray(c), h))
    bad = failed(run_receipts())
    assert "still-water VPP + current / current-coupled SOG (6 m/s wind, 0.5 m/s current with it)" in bad


def test_receipt_fails_when_the_apparent_wind_sign_is_flipped(fresh_tables, monkeypatch):
    monkeypatch.setattr(usv, "_apparent", lambda wx, wy, vx, vy: (wx + vx, wy + vy))
    bad = failed(run_receipts())
    assert "apparent wind speed = |true wind - boat velocity| (max relative error over 9 states)" in bad
    assert POLAR_ROW in bad
    assert "still-water VPP + current / current-coupled SOG (6 m/s wind, 0.5 m/s current with it)" in bad


def test_receipt_fails_when_the_wing_is_ten_times_too_big(fresh_tables):
    bad = failed(run_receipts({**P, "wing_area_m2": 60.0}))
    assert POLAR_ROW in bad
    assert MEAN_ROW in bad


def test_spurs2_receipts_fail_when_the_current_is_in_cm_per_s(fresh_tables, monkeypatch):
    orig = AnalyticEnv.current
    monkeypatch.setattr(AnalyticEnv, "current",
                        lambda self, lon, lat, z, t: Tagged(0.01 * orig(self, lon, lat, z, t).value, "x", 0.0, "assumed"))
    bad = failed(run_receipts())
    assert {"SPURS-2: swept_off_track first fires (h)", "SPURS-2: becalmed first fires (h)",
            "SPURS-2: fraction of members that fail both ways"} <= bad


def test_receipt_fails_when_the_hull_speed_cap_is_wrong(fresh_tables):
    # feet read as metres
    assert "hull speed 1.34 sqrt(LOA ft) kn vs the 3.3 m/s cap" in failed(run_receipts({**P, "loa_m": 7.0 * 0.3048}))
    bad = failed(run_receipts({**P, "stw_cap_ms": 4.5}))
    assert "hull speed 1.34 sqrt(LOA ft) kn vs the 3.3 m/s cap" in bad


def test_receipt_fails_for_the_wrong_friction_line(fresh_tables, monkeypatch):
    monkeypatch.setattr(usv, "cf_ittc57", lambda re: 0.075 / (np.log(re) - 2.0) ** 2)                # ln instead of log10
    assert "ITTC-1957 C_F at Re = 1e7" in failed(run_receipts())


def test_receipt_fails_when_head_and_following_seas_are_swapped(fresh_tables, monkeypatch):
    orig = usv._strip
    monkeypatch.setattr(usv, "_strip", lambda p, w, chi, u: orig(p, w, 180.0 - np.asarray(chi), u))
    assert "strip theory, long head waves: pitch / (-i k), bow down positive" in failed(run_receipts())


def test_receipt_fails_for_a_wrong_spectrum(fresh_tables, monkeypatch):
    orig = usv._bretschneider
    monkeypatch.setattr(usv, "_bretschneider", lambda w, tp: 1.5 * orig(w, tp))
    assert "Bretschneider m0 = Hs^2 / 16 (Hs = 1)" in failed(run_receipts())


def test_receipt_fails_for_a_wrong_table(fresh_tables, monkeypatch):
    monkeypatch.setattr(usv, "through_water_table", lambda p, pl, w, c, h: usv.through_water(p, w, 0.0 * np.asarray(c), h))
    assert "Stage-1 table == direct current-coupled solve (max |dV|)" in failed(run_receipts())


# ------------------------------------------------------------------ M-2: the VPP bias prior is calibrated to Chiodi, not the brief's still-water factor

def prior(name="usv_vpp_bias"):
    from cafe.pm.stats import sampling
    return sampling.load_perturbations()[name]


def test_the_prior_mean_reproduces_chiodis_sog_ratio_and_the_brief_value_does_not():
    """The VPP solves the current inside the polar, so the still-water -30..-35 % double counts: its mean gives 0.158 against Chiodi's 0.1778 (-10.9 %)."""
    u, want = P["chiodi_mean_wind_ms"], P["chiodi_mean_sog_ms"] / P["chiodi_mean_wind_ms"]
    e = prior()
    assert abs(usv.mean_sog(P, u, bias=0.5 * (e["lo"] + e["hi"])) / u / want - 1.0) < 0.01
    assert abs(usv.mean_sog(P, u) / u / want - 1.0) < 0.01                                       # the platform's own default draw mean too
    b = prior("usv_vpp_bias_brief")
    assert usv.mean_sog(P, u, bias=0.5 * (b["lo"] + b["hi"])) / u / want - 1.0 < -0.10          # kept as a sensitivity case, and it does not reproduce it


def test_the_prior_spread_is_suns_30_to_35_percent_as_a_speed_factor():
    e = prior()
    assert e["dist"] == "uniform" and 0.5 * (e["lo"] + e["hi"]) == pytest.approx(-0.2422, abs=1e-4)           # centred on the calibrated bias
    assert e["hi"] - e["lo"] == pytest.approx(1 / 1.30 - 1 / 1.35, abs=1e-4)                              # width of Sun's range as a speed factor
    assert P["vpp_bias_sd"] == pytest.approx((e["hi"] - e["lo"]) / np.sqrt(12.0), abs=2e-4)
    assert prior("usv_vpp_bias_brief")["dist"] == "uniform" and (prior("usv_vpp_bias_brief")["lo"], prior("usv_vpp_bias_brief")["hi"]) == (-0.35, -0.30)


# ------------------------------------------------------------------------------------------------------------ review round 2, M-2

def test_the_calibration_ratio_holds_on_a_section_without_current_and_a_westward_set_against_the_trades_is_what_lowers_it():
    """M-2: the mission USV makes 0.10 to 0.12 of the wind speed over the ground against the 0.178 the VPP bias is calibrated to. Diagnosed on the demo
    (6 d, mission wind and current, 1 CPU): the calibration scenario gives 0.178; the mission wind field and the track-holding section with no current
    give 0.185; waves 0.180; the current 0.120, and all of that from its westward component (a meridional-only current leaves 0.178). The model is not
    at fault: the speed polar is a function of the wind relative to the water, the current enters once. Same decomposition on a uniform wind (5.4 m/s
    from the east at the anemometer, section along 165 W, 24 h): without current the calibration is reproduced within its band; a 0.3 m/s set toward
    the west, the way the trades blow, costs at least 8 % of the path speed; one of 0.3 m/s along the track (north) does not lower it."""
    from cafe.pm.env.protocol import AnalyticEnv
    P = usv.load_platform()
    task = dict(mode="section", waypoints=[(-165.0, -1.0), (-165.0, 1.0)], repeat=True, track_tolerance_km=20.0, becalmed_after_h=6.0)

    def ratio(cur):
        env = AnalyticEnv(wind=usv._wind_at_anemometer(P, P["chiodi_mean_wind_ms"], 90.0), current=cur, hs=0.0)
        sim = usv.USVSim(P, 1, env, (-165.0, -1.0), 0.0, task, perturb=dict(vpp_bias=np.array([P["vpp_bias_mean"]])))
        sim.run(24 * 3600.0, 60.0)
        return float(sim.path_m[0] / (24 * 3600.0) / P["chiodi_mean_wind_ms"])

    calib = P["chiodi_mean_sog_ms"] / P["chiodi_mean_wind_ms"]
    none, west, north = ratio((0.0, 0.0)), ratio((-0.3, 0.0)), ratio((0.0, 0.3))
    assert abs(none / calib - 1.0) < P["chiodi_band"]
    assert west < 0.92 * none
    assert north > none


# ------------------------------------------------------------------------------------------------------------ review round 4, M-5

class HoleEnv(AnalyticEnv):
    """A land block in the ocean store: no finite wind or current for the members in `holes`."""

    def __init__(self, holes=(), field="current", **kw):
        super().__init__(**kw)
        self.holes, self.field = list(holes), field

    def _hole(self, v):
        v = np.array(v, float)
        v[self.holes] = np.nan
        return Tagged(v, "test", 0.0, "assumed")

    def current(self, lon, lat, z, t):
        v = super().current(lon, lat, z, t)
        return self._hole(v.value) if self.field == "current" else v

    def wind(self, lon, lat, z, t):
        v = super().wind(lon, lat, z, t)
        return self._hole(v.value) if self.field == "wind" else v


def test_a_non_finite_current_is_a_labelled_failure_for_that_member_and_the_run_goes_on():
    """M-5: a NaN current (a cell of the ocean store that is all land) raised IndexError (np.floor(NaN).astype(int)) in the table lookup and killed Stage 1;
    now the member fails with `no_current_data` at the first step, the step uses a zero vector for it, and the others are exactly as without the hole."""
    clean = sim(HoleEnv(wind=(-6.0, 0.0), current=(0.1, 0.0)), m=4)
    holed = sim(HoleEnv(holes=[1], wind=(-6.0, 0.0), current=(0.1, 0.0)), m=4)
    hc, hh, hz = clean.run(3 * HR, 60.0), holed.run(3 * HR, 60.0), sim(HoleEnv(wind=(-6.0, 0.0)), m=4).run(3 * HR, 60.0)
    assert hh["fail"]["no_current_data"].tolist() == [False, True, False, False] and hh["first"]["no_current_data"][1] == 60.0  # step end (M-27)
    assert np.isnan(hh["first"]["no_current_data"][[0, 2, 3]]).all() and not hc["fail"]["no_current_data"].any()
    assert np.isfinite(hh["lon"]).all() and np.isfinite(hh["lat"]).all()
    assert all(np.array_equal(hh["fail"][k][[0, 2, 3]], hc["fail"][k][[0, 2, 3]]) for k in usv.FAILS if k != "no_current_data")      # no other mode
    assert np.array_equal(hh["lon"][:, [0, 2, 3]], hc["lon"][:, [0, 2, 3]]) and np.array_equal(hh["lat"][:, [0, 2, 3]], hc["lat"][:, [0, 2, 3]])
    assert np.array_equal(hh["lon"][:, 1], hz["lon"][:, 1]) and not np.array_equal(hh["lon"][:, 1], hc["lon"][:, 1])         # it ran on a zero current


def test_a_current_that_is_nan_everywhere_fails_every_member_the_way_the_gliders_no_flight_does():
    s = sim(AnalyticEnv(wind=(-6.0, 0.0), current=(np.nan, 0.0)), m=4)
    h = s.run(HR, 60.0)                                                           # IndexError before the fix
    assert h["fail"]["no_current_data"].all() and np.all(h["first"]["no_current_data"] == 60.0) and np.isfinite(h["lon"]).all()
    zero = sim(AnalyticEnv(wind=(-6.0, 0.0)), m=4).run(HR, 60.0)                  # the step runs on a zero current: the same track and the same other modes
    assert np.array_equal(h["lon"], zero["lon"]) and all(np.array_equal(h["fail"][k], zero["fail"][k]) for k in usv.FAILS if k != "no_current_data")


def test_a_non_finite_wind_vector_is_the_same_labelled_failure():
    h = sim(HoleEnv(holes=[0, 3], field="wind", wind=(-6.0, 0.0)), m=4).run(HR, 60.0)
    assert h["fail"]["no_current_data"].tolist() == [True, False, False, True] and np.isfinite(h["lat"]).all()


# ---- review round 5, M-1: a run never steps past the time it was asked for ---------------------------------------------------
def test_run_stops_at_the_last_whole_step_inside_the_time_it_was_given():
    """M-1: 170 s at dt 60 was int(round(2.83)) = 3 steps, ending 10 s past the window; a deploy time with seconds then left the data."""
    s = sim(AnalyticEnv())
    h = s.run(170.0, record_s=60.0)
    assert len(h["t"]) == 2 and h["t"][-1] <= 170.0 and s.t <= 170.0
    assert [len(sim(AnalyticEnv()).run(x, record_s=60.0)["t"]) for x in (180.0, 179.9999999999)] == [3, 3]


# ---- review round 6, M-1: a wave state that is not a number is a labelled failure, not a NaN position or an IndexError -----------------------------
@pytest.mark.parametrize("kw", [dict(hs=np.nan), dict(tp=np.nan), dict(hs=np.nan, tp=np.nan), dict(wave_to=np.nan)], ids=["hs", "tp", "hs-tp", "direction"])
def test_a_wave_state_that_is_not_a_number_fails_every_member_from_the_first_step_and_the_run_goes_on(kw):
    """M-1: Hs NaN alone gave NaN positions and no flag (a pass); Tp NaN gave an IndexError out of `_lin` (the UMWM sea mask makes all of them NaN together)."""
    h = sim(AnalyticEnv(wind=(-6.0, 0.0), **kw), m=4).run(3 * HR, 60.0)
    assert h["fail"]["no_current_data"].all() and np.all(h["first"]["no_current_data"] == 60.0)
    assert np.isfinite(h["lon"]).all() and np.isfinite(h["lat"]).all()
    tp0 = float(usv.tables(P)[1].tp[0])                                                    # the step runs on Hs 0, Tp the table's first, direction 0
    calm = sim(AnalyticEnv(wind=(-6.0, 0.0), hs=0.0, tp=tp0, wave_to=0.0), m=4).run(3 * HR, 60.0)
    assert np.array_equal(h["lon"], calm["lon"]) and all(np.array_equal(h["fail"][k], calm["fail"][k]) for k in usv.FAILS if k != "no_current_data")


def test_a_stokes_drift_that_is_not_a_number_is_the_same_failure():
    h = sim(DriftEnv(stokes=(np.nan, 0.1), wind=(-6.0, 0.0)), m=2).run(HR, 60.0)
    assert h["fail"]["no_current_data"].all() and np.isfinite(h["lon"]).all() and np.isfinite(h["lat"]).all()


# ---- review round 6, M-10: a platform leaf the model divides by or takes a log of has a range --------------------------------------------------
def usv_file(tmp_path, group, key, value):
    raw = yaml.safe_load((usv.PLATFORMS / "saildrone_explorer.yaml").read_text())
    raw[group][key]["value"] = value
    f = tmp_path / "saildrone_explorer.yaml"
    f.write_text(yaml.safe_dump(raw))
    return str(f)


@pytest.mark.parametrize("group,key,value", [
    ("mission_defaults", "cap_cycles", 0.0), ("mission_defaults", "cap_cycles", -1.0), ("mission_defaults", "cap_cycles", 0.5),
    ("params", "rudder_area_m2", 0.0), ("params", "rudder_area_m2", -1.0), ("params", "rudder_span_m", 0.0), ("params", "rudder_span_m", -1.0),
    ("params", "rudder_t_c", 0.0), ("params", "rudder_x_m", 0.0), ("params", "stw_cap_ms", 1e12), ("params", "stw_cap_ms", 51.0),
    ("params", "stw_cap_ms", 3.6)])
def test_the_usv_loader_refuses_a_leaf_the_simulator_would_divide_by_or_take_a_log_of(tmp_path, group, key, value):
    with pytest.raises(ValueError, match=rf"saildrone_explorer\.yaml:{group}\.{key}: .* must be a finite number"):
        usv.load_platform(usv_file(tmp_path, group, key, value))


def test_the_usv_loader_still_takes_the_shipped_values_and_the_stated_edges(tmp_path):
    assert usv.load_platform()["stw_cap_ms"] == 3.3
    assert usv.load_platform(usv_file(tmp_path, "params", "stw_cap_ms", usv.WAVE_U_MAX))["stw_cap_ms"] == usv.WAVE_U_MAX
    assert usv.load_platform(usv_file(tmp_path, "mission_defaults", "cap_cycles", 1.0))["mission_defaults"]["cap_cycles"] == 1.0


def test_every_leaf_of_the_usv_table_that_may_take_any_value_is_one_the_model_only_adds_or_multiplies():
    """M-10: a new `any` leaf must be a conscious choice (the others were `any` while the model divided by them)."""
    assert {k for k, v in usv.REQUIRED.items() if v == "any"} == {"wing_ce_x_m", "keel_x_m", "vpp_bias_mean", "current_z_m"}
    assert usv.MISSION_REQUIRED["cap_cycles"] != "any"


# ---- review round 6, M-26: the unit conversions and the becalmed rule are pinned away from the equator ---------------------------------------------
def test_met_scales_east_west_metres_by_the_cosine_of_the_mean_latitude_and_leaves_a_meridian_alone():
    """M-26: `_met` without cos(lat) survived every test (all of them were at latitude 0): at 60 N a degree of longitude is half the equatorial length."""
    one = np.radians(1.0) * usv.R_E
    east = usv.USVSim._met(np.array([-165.0]), np.array([60.0]), np.array([-164.0]), np.array([60.0]))
    assert east[0, 0] == pytest.approx(0.5 * one, rel=1e-9) and abs(east[0, 1]) < 1e-9
    north = usv.USVSim._met(np.array([-165.0]), np.array([60.0]), np.array([-165.0]), np.array([61.0]))
    assert north[0, 1] == pytest.approx(one, rel=1e-9) and abs(north[0, 0]) < 1e-9
    slant = usv.USVSim._met(np.array([-165.0]), np.array([59.0]), np.array([-164.0]), np.array([61.0]))        # the cosine is of the MEAN latitude (60 N)
    assert slant[0, 0] == pytest.approx(0.5 * one, rel=1e-9)


def test_a_section_leg_east_west_at_60_north_has_the_waypoint_distance_and_cross_track_error_of_its_true_length():
    s = sim(AnalyticEnv(), wps=((-165.0, 60.0), (-164.0, 60.0)), m=1, start=(-165.0, 60.0))
    half = 0.5 * np.radians(1.0) * usv.R_E
    s.idx[:] = 1                                                                          # the active waypoint is the leg's far end
    dist, uhat, xte, _ = s._geom()
    assert dist[0] == pytest.approx(half, rel=1e-9) and uhat[0] == pytest.approx([1.0, 0.0]) and abs(xte[0]) < 1e-6
    s.lat = s.lat + np.degrees(1000.0 / usv.R_E)                                          # 1 km north of the leg: the error is 1 km, whatever the latitude
    assert abs(s._geom()[2][0]) == pytest.approx(1000.0, rel=1e-6)
    s.lon = s.lon + 0.5                                                                   # half-way along the leg: a quarter degree of this latitude is left
    assert s._geom()[0][0] == pytest.approx(0.25 * np.radians(1.0) * usv.R_E, rel=1e-3)


def becalmed_after(wind, current, hours=2.0):
    s = sim(AnalyticEnv(wind=(-wind, 0.0), current=(current, 0.0)), m=1, bias=0.0, mode="station", station=(-165.0, -1.0), start=(-165.0, -1.0),
            becalmed_after_h=hours)
    s.run((hours + 1.0) * HR, 60.0)
    return s


def test_becalmed_is_a_best_speed_below_the_current_not_below_half_of_it():
    """M-26: `vmax <= 0.5 * speed(current)` survived: the best through-water speed here is 0.62 of the current (becalmed) and 1.15 of it (not)."""
    slow, fast = becalmed_after(3.0, 2.0), becalmed_after(3.0, 0.8)
    assert 0.55 < slow.vmax[0] / 2.0 < 0.9 and fast.vmax[0] / 0.8 > 1.1                                  # the pair is where the mutant and the rule disagree
    assert slow.fail["becalmed"].all() and 2.0 <= first_h(slow, "becalmed") < 2.1
    assert not fast.fail["becalmed"].any()


# ---- review round 7, M-35: a file without its top-level blocks is a ValueError naming the file and the blocks, not a KeyError
def test_r7_m35_the_usv_loader_names_the_file_and_the_missing_blocks(tmp_path):
    f = tmp_path / "typo.yaml"
    f.write_text("kind: saildrone_usv\nmass_kg: 52\n")
    with pytest.raises(ValueError, match=r"typo\.yaml: missing \['params', 'mission_defaults'\]; add them \(see platforms/saildrone_explorer\.yaml"):
        usv.load_platform(str(f))


# ---- review round 7, M-16: a non-finite shortwave value or start position is a labelled failure, not a NaN battery
class SwEnv(AnalyticEnv):
    """AnalyticEnv whose shortwave is NaN from `t_bad` on (a hole in the WRF radiation field); wind, current and waves stay finite."""

    def __init__(self, t_bad=HR, **kw):
        super().__init__(**kw)
        self.t_bad = t_bad

    def air(self, lon, lat, t):
        a = super().air(lon, lat, t)
        if t >= self.t_bad:
            a["swdown"] = Tagged(np.full(np.shape(a["swdown"].value), np.nan), "test", 0.0, "assumed")
        return a


def test_r7_m16_a_non_finite_shortwave_flags_no_current_data_and_the_battery_state_stays_finite_and_still_runs_down():
    """NaN before: `np.clip` of NaN is NaN and `NaN <= 0` is False, so soc_wh was NaN for good and `battery` never fired."""
    s = sim(SwEnv(wind=(-6.0, 0.0), swdown=0.0), m=3)
    s.run(60 * HR, 600.0)
    assert np.isfinite(s.soc_wh).all() and s.fail["no_current_data"].all() and 1.0 <= first_h(s, "no_current_data") <= 1.3
    t_empty = P["battery_wh"] / P["hotel_w"]
    assert s.fail["battery"].all() and t_empty - 0.2 <= first_h(s, "battery") <= t_empty + 0.3                  # 0 W of sun: the hotel load alone
    clean = sim(AnalyticEnv(wind=(-6.0, 0.0), swdown=0.0), m=3)
    clean.run(60 * HR, 600.0)
    assert not clean.fail["no_current_data"].any() and first_h(clean, "battery") == pytest.approx(first_h(s, "battery"), abs=1e-9)


def test_r7_m16_a_non_finite_start_position_is_flagged_at_t0_and_the_run_stays_finite():
    s = sim(AnalyticEnv(wind=(-6.0, 0.0)), m=3, start=(np.array([-165.0, np.nan, -165.0]), np.array([-1.0, -1.0, np.nan])))
    assert s.fail["no_current_data"].tolist() == [False, True, True] and s.first["no_current_data"][1:].tolist() == [0.0, 0.0]
    h = s.run(HR, 60.0)
    assert np.isfinite(h["lon"]).all() and np.isfinite(h["lat"]).all() and np.isnan(h["first"]["no_current_data"][0])


# ---- review round 7, M-20: wind above the polar is a failure, not a pass
def test_r7_m20_a_wind_above_the_polar_fails_every_member_after_stall_sustain_s_and_a_wind_inside_it_is_unchanged():
    def run(wind):
        s = sim(AnalyticEnv(wind=(-wind, 0.0), hs=2.0), m=3, bias=0.0, mode="station", station=(-165.0, -1.0), start=(-165.0, -1.0))
        s.run(HR, 60.0)
        return s
    out, ok = run(40.0), run(25.0)
    assert out.fail["capsize_proxy"].all() and P["mission_defaults"]["stall_sustain_s"] / HR <= first_h(out, "capsize_proxy") < 0.6
    assert not ok.fail["capsize_proxy"].any() and ok.acc["wind_out"].max() == 0.0


# ---- review round 7, M-18: the 4-DOF fixed point is converged at the shipped N_IT
def test_r7_m18_the_polar_at_the_shipped_iteration_count_is_converged_everywhere_including_storm_winds(monkeypatch):
    """N_IT 24 left 58 cells (TWS 27 to 30 m/s) off the converged answer by more than 0.01 m/s, the worst by 1.55 m/s; 48 and 200 agree to 0.03."""
    shipped = usv._build_polar(P).f[..., 0]
    monkeypatch.setattr(usv, "N_IT", 200)
    ref = usv._build_polar(P).f[..., 0]
    assert np.abs(shipped - ref).max() < 0.03 and usv.N_IT == 200
    monkeypatch.setattr(usv, "N_IT", 24)
    old = usv._build_polar(P).f[..., 0]
    assert (np.abs(old - ref) > 0.01).sum() > 50 and np.abs(old - ref).max() > 1.0                                  # the test can see the defect


def test_r7_m18_the_table_cache_key_follows_the_iteration_count(monkeypatch):
    a = usv._digest(P)
    monkeypatch.setattr(usv, "N_IT", usv.N_IT + 1)
    assert usv._digest(P) != a


# ---- review round 7, M-4: the 12 m/s receipt is two rows, the polar the 12 m/s fit was made on and the model Stage 1 flies
def test_r7_m4_the_12_ms_receipt_has_a_row_for_the_unflown_polar_and_one_for_the_model_stage_1_flies():
    res = run_receipts()
    pol = usv.tables(P)[0]
    top = float(pol.f[int(np.argmin(np.abs(pol.tws - P["chiodi_max_wind_ms"]))), :, 0].max())
    fit, flown = res[POLAR_ROW], res[FLOWN_ROW]
    assert fit["value"] == pytest.approx(top, rel=1e-9) and fit["tol"] == 0.10 and fit["ok"]
    assert flown["value"] == pytest.approx(top * (1.0 + P["vpp_bias_mean"]), rel=1e-9) and flown["tol"] == P["chiodi_band"] and flown["ok"]
    assert flown["value"] < 0.8 * P["chiodi_max_sog_ms"] and flown["reference"] == P["chiodi_max_sog_ms"]            # 24 % under, inside the 25 % band
    assert "no single bias" in flown["source"] and "CALIBRATED: vpp_bias_mean" in MEAN_ROW


def test_r7_m4_the_flown_row_follows_the_bias(fresh_tables):
    flown = run_receipts({**P, "vpp_bias_mean": -0.40})[FLOWN_ROW]                                                  # a bigger bias: the row follows it
    assert not flown["ok"] and flown["value"] < 0.65 * P["chiodi_max_sog_ms"]


def P_why(key):
    leaf = yaml.safe_load((usv.PLATFORMS / "saildrone_explorer.yaml").read_text())["params"][key]
    return leaf.get("why") or leaf["source"]


def test_r7_m4_the_platform_header_says_what_is_fitted_to_what():
    text = (usv.PLATFORMS / "saildrone_explorer.yaml").read_text()
    head = text[:text.index("kind: wing_sail_usv")]
    assert "closure" in head and "5.4 m/s mean, the 3.3 m/s cap" not in head and "24 % under" in head
    assert "closure" in P_why("vpp_bias_mean") and "without the VPP bias" in P_why("appendage_cda_m2")


# ---- review round 7, M-19: added resistance is linearised about the calm speed; the numbers that statement rests on are pinned
def test_r7_m19_in_short_steep_head_seas_the_first_order_speed_is_credited_with_what_the_boat_cannot_make():
    pol, wt = usv.tables(P)
    v0, _, _, k, *_ = usv._lin(pol.f, (pol.tws, pol.twa), (6.0, 90.0))
    assert v0 == pytest.approx(1.554, abs=2e-3) and k == pytest.approx(131.8, abs=0.5)                         # TWS 6 m/s, TWA 90 deg, still water
    r = usv.added_resistance(P, wt, 2.0, 6.0, 180.0, np.array([0.0, 0.5, 1.0, v0]))                            # Hs 2 m, Tp 6 s, head seas
    assert r == pytest.approx([312.6, 207.9, 155.6, 129.3], abs=0.5) and np.all(np.diff(r) < 0)                  # largest at rest
    s = sim(AnalyticEnv(wind=(-6.0, 0.0), hs=2.0, tp=6.0, wave_to=180.0), m=1, bias=0.0)
    e = s._eval(np.array([[0.0]]), dict(wfrom=np.array([90.0]), tws=np.array([6.0]), hs=np.array([2.0]), tp=np.array([6.0]), wdir=np.array([180.0])))
    assert float(e["v"][0, 0]) == pytest.approx(v0 - r[-1] / k, abs=1e-6) and float(e["v"][0, 0]) == pytest.approx(0.573, abs=3e-3)


# ---- review round 8, M-8: the Stage-1 table and the direct solve agree at random states, not only at five hand-picked ones
GAP_ROW = "Stage-1 table == direct solve at 2000 seeded random states: fraction with |dV| > 0.2 m/s"


def test_r8_m8_the_random_state_receipt_row_exists_and_the_refined_polar_passes_it():
    row, pol = run_receipts()[GAP_ROW], usv.tables(P)[0]
    assert row["ok"] and row["tol"] == 0.0025 and row["value"] == pytest.approx(float(np.mean(usv.table_gap(P, pol) > 0.2)))
    assert row["value"] < 0.002                                                       # 2 of the 2000 states (0.45 % of states at 2.5 deg spacing)
    cone = pol.twa[(pol.twa >= 10.0) & (pol.twa <= 20.0)]
    assert np.diff(cone).max() == 0.5 and np.diff(pol.twa).max() == 2.5 and np.all(np.diff(pol.twa) > 0)


def test_r8_m8_the_2_5_degree_axis_fails_the_random_state_row(fresh_tables, monkeypatch):
    monkeypatch.setattr(usv, "TWA", np.arange(0.0, 180.01, 2.5))
    row = run_receipts()[GAP_ROW]
    assert not row["ok"] and row["value"] > 0.0025                                                   # 8 of 2000 = 0.4 %


def test_r8_m8_lin_interpolates_on_a_non_uniform_axis_and_clamps():
    ax = (np.array([0.0, 1.0, 1.5, 4.0]),)
    tab = 3.0 * ax[0] + 1.0
    x = np.array([-1.0, 0.25, 1.25, 2.75, 9.0])
    assert np.allclose(usv._lin(tab, ax, (x,)), 3.0 * np.clip(x, 0.0, 4.0) + 1.0)


# ---- review round 8, M-12: a cap that is not a multiple of the 0.05 m/s search step
@pytest.mark.parametrize("cap", [3.33, 3.37, 0.04])
def test_r8_m12_a_cap_off_the_search_grid_gives_a_polar_no_faster_than_the_cap(cap, fresh_tables):
    pol = usv.tables({**P, "stw_cap_ms": cap})[0]
    assert pol.f[..., 0].max() <= cap + 1e-9 and pol.f[..., 0].max() > 0.9 * cap      # the receipt's own bound (3.3303 > 3.33 before)


def test_r8_m12_the_shipped_cap_is_a_multiple_of_the_step():
    assert P["stw_cap_ms"] / (int(round(P["stw_cap_ms"] / usv.DV))) == pytest.approx(usv.DV, rel=1e-14)


# ---- review round 8, M-36: the on-disk table key follows the code
def test_r8_m36_the_table_cache_key_follows_the_source_of_the_module(monkeypatch):
    a = usv._digest(P)
    assert usv._digest(P) == a
    monkeypatch.setattr(pathlib.Path, "read_bytes", lambda self: b"another version of usv.py")
    assert usv._digest(P) != a


# ---- review round 8, M-43: terms that move published outputs and no test noticed (mutants named in each docstring)
def test_r8_m43_the_tack_penalty_keeps_an_upwind_station_run_to_tens_of_tacks():
    """`pen` -> 0.0 gave 261 tacks in 24 h (27 with it); the old test asked for at least 3."""
    km55 = 55e3 / 111320.0
    mis = dict(mode="station", station=(-165.0, -1.0 + km55))
    s = usv.USVSim(P, 8, AnalyticEnv(wind=(0.0, -6.0), hs=1.0), (-165.0, -1.0), 0.0, mis, perturb=dict(vpp_bias=np.full(8, -0.3)))
    s.run(24 * HR, 60.0)
    assert 3 <= s.n_tacks.max() <= 60


def test_r8_m43_a_tack_slows_the_boat_by_the_stated_fraction():
    """`tack_speed_frac` -> 1.0: the first tack step of two otherwise identical boats has speeds in the ratio of the fractions."""
    env = AnalyticEnv(wind=(0.0, -6.0), hs=1.0)
    mis, pb = dict(mode="station", station=(-165.0, 0.5)), dict(vpp_bias=np.array([-0.3]))
    mk = lambda f: usv.USVSim({**P, "tack_speed_frac": f}, 1, env, (-165.0, -1.0), 0.0, mis, perturb=pb)
    a, b = mk(1.0), mk(0.5)
    for _ in range(1500):
        a.step(60.0), b.step(60.0)
        if a.n_tacks[0] > 0:
            break
    assert a.n_tacks[0] == b.n_tacks[0] == 1 and b.stw[0] == pytest.approx(0.5 * a.stw[0], rel=1e-9) and a.stw[0] > 0.3


def test_r8_m43_the_keel_and_rudder_see_twice_the_geometric_aspect_ratio_and_the_leeway_follows():
    """`ar = 2 span^2 / area` -> `span^2 / area` (free-surface image doubles the aspect ratio); leeway at 6 m/s true wind on the beam is 0.683 deg."""
    assert usv._foil(P, "keel")[1] == pytest.approx(2.0 * P["keel_span_m"] ** 2 / P["keel_area_m2"]) == pytest.approx(6.3)
    assert usv._foil(P, "rudder")[1] == pytest.approx(6.0) and usv._foil(P, "keel")[2] == pytest.approx(4.5975, abs=1e-3)
    assert usv.through_water(P, np.array([-6.0, 0.0]), np.zeros(2), np.array([0.0]))["leeway_deg"][0] == pytest.approx(-0.6829, abs=2e-3)


def test_r8_m43_the_heading_is_held_for_the_length_of_a_tack_even_when_a_replan_falls_inside_it():
    """`self.hd = np.where(free, ...)` -> always: the branch is dead with the shipped numbers (replan 300 s, tack 120 s), so it is driven directly here."""
    s = sim(AnalyticEnv(wind=(0.0, -6.0), hs=1.0), m=1)
    s.hd[:] = 123.0
    s.tack_until[:] = s.t + 100.0
    s.t_plan = -np.inf
    s.step(60.0)
    assert s.hd[0] == 123.0
    s.tack_until[:] = -np.inf
    s.t_plan = -np.inf
    s.step(60.0)
    assert s.hd[0] != 123.0


# ---- review round 9: M-27 (one stamp time for every flag of a step), M-13 (a repeated waypoint), M-22 (the mission defaults the model indexes)
def test_r9_m27_no_current_data_is_stamped_at_the_end_of_the_step_whatever_the_hole_and_the_start_flag_stays_t0():
    """Before: a wind hole gave `first` = t (60 s short of the insolation hole's value in the same step), the insolation hole t + dt."""
    dt = 60.0
    wind = sim(HoleEnv(holes=[1], field="wind", wind=(-6.0, 0.0)), m=3, start=(-165.0, -1.0))
    sw = sim(SwEnv(t_bad=0.0, wind=(-6.0, 0.0)), m=3)
    wave = sim(AnalyticEnv(wind=(-6.0, 0.0), hs=np.nan), m=3)
    for s in (wind, sw, wave):
        s.step(dt)
    assert wind.first["no_current_data"][1] == dt and sw.first["no_current_data"].tolist() == [dt] * 3 and wave.first["no_current_data"].tolist() == [dt] * 3
    s = sim(AnalyticEnv(wind=(-6.0, 0.0)), m=2, start=(np.array([-165.0, np.nan]), np.array([-1.0, -1.0])))
    assert s.first["no_current_data"].tolist()[1] == 0.0  # a start position that is not finite: t0, on purpose (DECISIONS 356)
    s.step(dt)
    s.step(dt)
    assert s.first["no_current_data"][1] == 0.0                                                # and a later hole does not move it


def test_r9_m13_a_repeated_waypoint_is_one_waypoint_and_a_section_of_one_point_is_the_station():
    """Before: `[A, A]` was a section with a zero-length leg (cross-track error 0, becalmed only) and `[A, B, B]` had a leg of length zero at its end."""
    A, B = (-165.0, 0.0), (-165.0, 0.5)
    env = AnalyticEnv(wind=(-6.0, 0.0), current=(0.0, 0.6))
    twice = sim(env, wps=(A, A), m=2, start=A)
    station = usv.USVSim(P, 2, env, A, 0.0, dict(mode="station", station=A), perturb=dict(vpp_bias=np.full(2, -0.3)))
    assert twice.mode == "station" and len(twice.wps) == 1
    h, hs = twice.run(6 * HR, 60.0), station.run(6 * HR, 60.0)
    assert all(np.array_equal(h[k], hs[k]) for k in ("lon", "lat")) and all(np.array_equal(h["fail"][k], hs["fail"][k]) for k in usv.FAILS)
    assert np.array_equal(twice.xte_max, station.xte_max) and twice.xte_max.max() > 0.0  # the distance from the point, as the station's track test sees it
    ab, abb = sim(env, wps=(A, B), m=2), sim(env, wps=(A, B, B), m=2)
    assert abb.mode == "section" and abb.wps.tolist() == ab.wps.tolist() == [list(A), list(B)]
    assert sim(env, wps=(A, A, B, B, A), m=2).wps.tolist() == [list(A), list(B), list(A)]  # only a repeat next to its twin goes: A, B, A is a different section
    assert np.array_equal(abb.run(3 * HR, 60.0)["lon"], ab.run(3 * HR, 60.0)["lon"])


MISSION_KEYS = ["becalmed_after_h", "calm_sustain_s", "track_tolerance_km", "corridor_km", "wp_radius_m", "roll_limit_deg", "stall_sustain_s", "cap_cycles"]


@pytest.mark.parametrize("key", MISSION_KEYS)
def test_r9_m22_a_platform_without_a_mission_default_the_model_indexes_is_refused_at_load_naming_it(tmp_path, key):
    """Before: it loaded, and `run` died in `USVSim.step` with a bare KeyError."""
    raw = yaml.safe_load((usv.PLATFORMS / "saildrone_explorer.yaml").read_text())
    del raw["mission_defaults"][key]
    f = tmp_path / "boat.yaml"
    f.write_text(yaml.safe_dump(raw))
    with pytest.raises(ValueError, match=rf"boat\.yaml:mission_defaults: missing \['{key}'\]; add them"):
        usv.load_platform(str(f))


def test_r9_m22_the_table_names_exactly_the_mission_keys_of_the_shipped_file():
    shipped = yaml.safe_load((usv.PLATFORMS / "saildrone_explorer.yaml").read_text())["mission_defaults"]
    assert sorted(usv.MISSION_REQUIRED) == sorted(MISSION_KEYS) == sorted(shipped)


def test_r9_a_repeating_section_whose_last_point_is_its_first_has_no_wrap_leg_of_length_zero():
    """Before: `[A, B, A]` with `repeat` had the leg A -> A at its wrap (cross-track error 0, a capture at once); now it is `[A, B]` going round."""
    A, B = (-165.0, 0.0), (-165.0, 0.5)
    env = AnalyticEnv(wind=(-6.0, 0.0), current=(0.0, 0.0))
    closed, open_ = sim(env, wps=(A, B, A), m=2, repeat=True), sim(env, wps=(A, B), m=2, repeat=True)
    assert closed.wps.tolist() == open_.wps.tolist() == [list(A), list(B)]
    assert sim(env, wps=(A, B, A), m=2).wps.tolist() == [list(A), list(B), list(A)]               # not repeating: the return to A is the last leg
    assert sim(env, wps=(A, A), m=2, repeat=True).mode == "station"
    assert np.array_equal(closed.run(3 * HR, 60.0)["lon"], open_.run(3 * HR, 60.0)["lon"])


@pytest.mark.parametrize("key,bad", [("becalmed_after_h", 0.0), ("calm_sustain_s", -1.0), ("track_tolerance_km", 0.0), ("track_tolerance_km", 1000.5),
                                     ("corridor_km", -5.0), ("wp_radius_m", 0.0), ("roll_limit_deg", 0.0), ("roll_limit_deg", 181.0),
                                     ("stall_sustain_s", -1.0)])
def test_r9_a_mission_default_out_of_its_range_is_refused_at_load_naming_it(tmp_path, key, bad):
    """Before: the keys were kind 'any' (finite), so a negative corridor_km loaded."""
    raw = yaml.safe_load((usv.PLATFORMS / "saildrone_explorer.yaml").read_text())
    raw["mission_defaults"][key]["value"] = bad
    f = tmp_path / "boat.yaml"
    f.write_text(yaml.safe_dump(raw))
    with pytest.raises(ValueError, match=rf"boat\.yaml:mission_defaults\.{key}: "):
        usv.load_platform(str(f))


# ---- review round 10, M-10: a calm is only a calm
def test_r10_m10_in_a_calm_the_bow_cone_is_not_counted_so_wing_stall_angle_needs_an_apparent_wind_of_trim_min_aws_ms():
    """In a calm (apparent wind under trim_min_aws_ms) the polar's apparent wind angle is the sign of a zero, and wing_stall_angle was counted beside
    wing_stall_calm for some wind directions (DECISIONS 217: a calm is a calm): 0.5 m/s blowing toward 210 deg, 0.3 m/s toward 180 deg, for a boat
    bound north. Above trim_min_aws_ms the cone still counts."""
    for speed, to_deg in ((0.5, 210.0), (0.3, 180.0)):
        calm = sim(AnalyticEnv(wind=tuple(wind_to(speed, to_deg))), m=2)
        calm.run(2 * HR, 60.0)
        assert calm.fail["wing_stall_calm"].all() and not calm.fail["wing_stall_angle"].any() and calm.acc["wing_stall_angle"].max() == 0.0
        assert 0.5 <= first_h(calm, "wing_stall_calm") < 0.6
    brisk = usv.USVSim(dict(P, min_awa_deg=180.0), 2, AnalyticEnv(wind=(-6.0, 0.0)), (-165.0, -1.0), 0.0,
                       dict(mode="section", waypoints=[(-165.0, -1.0), (-165.0, 1.0)]), perturb=dict(vpp_bias=np.full(2, -0.3)))
    brisk.run(2 * HR, 60.0)
    assert brisk.fail["wing_stall_angle"].all() and not brisk.fail["wing_stall_calm"].any()


# ---- review round 10, M-13: where the polar is stalled or not balanced, over the whole 0 to 30 m/s table
def test_r10_m13_every_cell_that_moves_is_balanced_and_the_stalled_cells_are_counted_per_wind_angle():
    """The polar keeps V, not the residual of the balance. Over the whole table every cell with V above 0.2 m/s balances to 2.1e-4; the cells with
    V = 0 (no positive-speed root: DECISIONS 358) are counted, and so is the lowest wind speed at which each wind angle stalls after moving."""
    m = usv.stall_map(P)
    assert m["cells"] == 2759 == m["v0_cells"] + m["weak_cells"] + m["moving_cells"]
    assert m["max_resid_moving"] < 5e-4 and m["v0_cells"] == 658 and m["weak_cells"] == 56
    assert m["unbalanced_weak"] == 12                                      # roots next to a stall; 8 of them at TWS 1 m/s, TWA 14.5 to 18
    on = m["stall_onset"]
    assert (on[15.0], on[30.0], on[45.0]) == (17.0, 26.0, 30.0) and max(on) == 45.0 and len(on) == 22        # upwind and close-reach only
    best = usv.tables(P)[0].f[..., 0].max(1)
    assert best[14] > 0.98 * P["stw_cap_ms"] and (best[15:] >= P["stw_cap_ms"] - 1e-9).all()        # the best heading is at the cap from 15 m/s


# ---- review round 10, M-17: the added-resistance table ends at the speed cap's limit
def test_r10_m17_the_speed_cap_cannot_pass_the_top_of_the_added_resistance_table(tmp_path):
    assert usv._build_waves(P).u[-1] == usv.WAVE_U_MAX and usv.load_platform()["stw_cap_ms"] <= usv.WAVE_U_MAX
    assert usv.load_platform(usv_file(tmp_path, "params", "stw_cap_ms", usv.WAVE_U_MAX))["stw_cap_ms"] == usv.WAVE_U_MAX
    with pytest.raises(ValueError, match=r"stw_cap_ms: 4.0 must be a finite number .*at most 3.5"):
        usv.load_platform(usv_file(tmp_path, "params", "stw_cap_ms", 4.0))
