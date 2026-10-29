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
from cafe.pm.env.protocol import AnalyticEnv
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
    assert np.all(v[3:15, 10:] > 0)
    best = pol.twa[v[4:12].argmax(1)]
    assert np.all(best > 55) and np.all(best < 130)                            # fastest on a beam to broad reach
    assert np.all(np.diff(v[:11, 40]) > 0)                                     # more wind, more speed (to 10 m/s, beam reach)
    assert v[6, 72] < v[6, 40]                                                 # dead downwind is slower than a beam reach


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
    assert kd[4, 40] == 1.0 and kd[25, 20] < 0.9
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
    assert np.isclose(pol.f[..., 0].max(), P["stw_cap_ms"]) and np.all(pol.f[20:, 40:60, 0] <= P["stw_cap_ms"] + 1e-9)


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
    assert np.all(s.fac < 0.8) and np.all(s.fac > 0.55)                        # the prior: about -30 %


def test_vpp_bias_draw():
    b = usv.draw_vpp_bias(P, 20000, seed=1)
    assert np.isclose(b.mean(), -0.30, atol=0.002) and np.isclose(b.std(), 0.03, atol=0.002)
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


def test_wing_stall_sustained_in_light_air_only():
    s = sim(AnalyticEnv(wind=(-1.0, 0.0)), m=2)
    s.run(2 * HR, 60.0)
    assert 0.5 <= first_h(s, "wing_stall") < 0.6                               # stall_sustain_s = 30 min
    brisk = sim(AnalyticEnv(wind=(-6.0, 0.0)), m=2)
    brisk.run(2 * HR, 60.0)
    assert not brisk.fail["wing_stall"].any()


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


def failed(res):
    return {c for c, e in res.items() if e["ok"] is False}


def test_receipts_pass_and_are_numbers_not_stubs():
    res = run_receipts()
    assert failed(res) == set(), failed(res)
    checked = [e for e in res.values() if e["ok"] is not None]
    assert len(checked) >= 15 and len([e for e in res.values() if e.get("kind") == "context"]) == 3
    mean = res["mean SOG / U at 5.4 m/s (VMG routing, all bearings, prior bias)"]
    assert 0.8 * 0.178 < mean["value"] < 1.2 * 0.178
    assert 2.6 < res["best-heading still-water speed at 12 m/s (CALIBRATED: appendage_cda_m2)"]["value"] < 3.2
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
    assert "best-heading still-water speed at 12 m/s (CALIBRATED: appendage_cda_m2)" in bad
    assert "still-water VPP + current / current-coupled SOG (6 m/s wind, 0.5 m/s current with it)" in bad


def test_receipt_fails_when_the_wing_is_ten_times_too_big(fresh_tables):
    bad = failed(run_receipts({**P, "wing_area_m2": 60.0}))
    assert "best-heading still-water speed at 12 m/s (CALIBRATED: appendage_cda_m2)" in bad
    assert "mean SOG / U at 5.4 m/s (VMG routing, all bearings, prior bias)" in bad


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
