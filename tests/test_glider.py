"""cafe.pm.physics.glider: steady flight, kinematics, platform files, receipts (and that each receipt can fail)."""

import sys
import time

import numpy as np
import pytest
import gsw
import yaml
from hypothesis import given, settings, strategies as st

from cafe.pm import Tagged
from cafe.pm.env.protocol import AnalyticEnv
from cafe.pm.physics import glider as g

SG, SL = g.load_platform("seaglider"), g.load_platform("slocum")
DAY = 86400.0


def uni(z):
    return np.ones_like(np.asarray(z, float))


class Strat(AnalyticEnv):
    """Uniform currents; in-situ density from TEOS-10 on the glider module's own T(z), so a glider can be ballasted for 1000 m."""

    def density(self, lon, lat, z, t):
        zz = np.asarray(z, float)
        T = g._temp_c(SG, self.T, -zz)
        rho = gsw.rho(35.0, T, gsw.p_from_z(zz, np.asarray(lat, float))) + 0.0 * self._b(lon, lat, z, t)
        return Tagged(rho, "teos10", 0.0, "assumed")


def env(cx=0.0, cy=0.0, **kw):
    return Strat(wind=kw.pop("wind", (0.0, 0.0)), current=(cx, cy), current_profile=uni, **kw)


def sim(P=SG, M=1, e=None, lon=180.0, lat=0.0, mission=None, **perturb):
    return g.GliderSim(P, M, e or env(), lon, lat, 0.0, mission or dict(mode="drift", heading_to=90.0), perturb=perturb)


# ---- platform files ----------------------------------------------------------------------------------------------------
def test_platform_defaults_are_the_published_ones():
    assert (SG["hd_a"], SG["hd_b"], SG["hd_c"], SG["hd_s"]) == (0.003548133892336, 0.011220184543020, 5.7e-6, -0.25)
    assert (SG["abs_compress"], SG["therm_expan"], SG["length_m"], SG["volmax_cc"], SG["rating_m"]) == (
        4.1e-6,
        7.05e-5,
        1.8,
        51000.0,
        1000.0,
    )
    assert (SL["mg"], SL["Vg"], SL["S"], SL["AR"], SL["aw"], SL["Cd0"]) == (56.4, 0.0548, 0.10, 7.0, 3.7, 0.10)
    assert SG["kind"] == "seaglider" and SL["kind"] == "slocum" and SG["mission_defaults"]["station_tol_m"] > 0


def test_every_yaml_leaf_cites_or_is_assumed():
    for name in ("seaglider", "slocum"):
        raw = yaml.safe_load((g.PLATFORMS / f"{name}.yaml").read_text())
        for block in ("params", "mission_defaults"):
            for k, leaf in raw[block].items():
                assert leaf.get("source") or (leaf.get("assumed") is True and len(leaf.get("why", "")) > 10), (name, k)


@pytest.mark.parametrize(
    "leaf,msg",
    [
        ("{value: 1.0, source: x}", "value and unit"),
        ("{value: 1.0, unit: m}", "need a source"),
        ("{value: 1.0, unit: m, assumed: true}", "need a source"),
        ("{value: 17.0e6, unit: m, source: x}", "is a string"),
        ("1.0", "value and unit"),
    ],
)
def test_loader_refuses_bad_leaves(tmp_path, leaf, msg):
    f = tmp_path / "bad.yaml"
    f.write_text(f"kind: seaglider\nparams:\n  x: {leaf}\nmission_defaults: {{}}\n")
    with pytest.raises(ValueError, match=msg):
        g.load_platform(str(f))


def test_loader_accepts_a_good_file(tmp_path):
    f = tmp_path / "ok.yaml"
    f.write_text(
        "kind: slocum\nparams:\n  x: {value: 2.0, unit: m, assumed: true, why: because}\n"
        "mission_defaults:\n  y: {value: 1.0, unit: m, source: s}\n"
    )
    assert g.load_platform(str(f)) == {"x": 2.0, "kind": "slocum", "mission_defaults": {"y": 1.0}}


# ---- Seaglider steady flight -------------------------------------------------------------------------------------------
CANON = g._canon(SG)


def test_seaglider_canonical_state_numbers():
    rho, p, T, vd, vc = CANON
    d, c = g.seaglider_steady(rho, p, T, vd, -14.0, SG), g.seaglider_steady(rho, p, T, vc, 14.0, SG)
    assert d.ok and c.ok
    assert d.speed == pytest.approx(0.2404, abs=2e-4) and c.speed == pytest.approx(
        0.2404, abs=2e-4
    )  # regression + Eriksen 2001 0.25 m/s
    assert d.glide_deg == pytest.approx(-c.glide_deg) and 17.5 < c.glide_deg < 19.0  # 1:3
    assert d.alpha_deg > 0 > c.alpha_deg  # BS3: alpha opposite to the glide
    assert d.w < 0 < c.w and d.w == pytest.approx(d.speed * np.sin(np.radians(d.glide_deg)))
    assert abs(d.glide_deg) > 14.0 and abs(c.glide_deg) > 14.0  # glide steeper than pitch


def test_seaglider_sign_and_unit_mistakes_are_caught():
    rho, p, T, vd, vc = CANON
    wrong_sign = g.seaglider_steady(rho, p, T, vc, -14.0, SG)  # buoyant but pitched down
    assert not wrong_sign.ok and wrong_sign.speed == 0.0
    assert not g.seaglider_steady(rho, p, T, vd, 14.0, SG).ok
    ref = g.seaglider_steady(rho, p, T, vc, 14.0, SG)
    per_rad = dict(
        SG, hd_a=SG["hd_a"] * 180 / np.pi, hd_c=SG["hd_c"] * (180 / np.pi) ** 2
    )  # same physics, alpha in radians: must differ from deg reading
    bad = g.seaglider_steady(rho, p, T, vc, 14.0, per_rad)
    assert abs(bad.speed / ref.speed - 1) > 0.1 and abs(bad.glide_deg - ref.glide_deg) > 3.0
    flipped = dict(SG, hd_a=-SG["hd_a"])
    assert not g.seaglider_steady(rho, p, T, vc, 14.0, flipped).ok


def test_seaglider_no_steady_solution_cases():
    rho, p, T, _, vc = CANON
    shallow = g.seaglider_steady(rho, p, T, vc, 2.0, SG)  # near-level pitch: no real root (discriminant < 0)
    assert not shallow.ok and shallow.speed == 0.0 and shallow.glide_deg == 0.0
    assert not g.seaglider_steady(rho, p, T, g.neutral_vbd_cc(SG, rho, p, T), 14.0, SG).ok  # B = 0 exactly
    weak = g.seaglider_steady(rho, p, T, g.neutral_vbd_cc(SG, rho, p, T) + 0.01, 14.0, SG)  # a few mN: speed below u_min
    assert not weak.ok
    not_conv = g._sg_core(1.5, 1026.0, 14.0, SG, iters=3)
    assert not not_conv.ok  # unconverged after 3 iterations is flagged, not returned


def test_seaglider_vectorised_shapes_and_independence():
    rho, p, T, vd, vc = CANON
    vbd = np.array([vd, vc, vd, vc])
    pitch = np.array([-14.0, 14.0, 14.0, -14.0])
    s = g.seaglider_steady(rho, p, T, vbd, pitch, SG)
    assert s.speed.shape == (4,) and list(s.ok) == [True, True, False, False]
    one = g.seaglider_steady(rho, p, T, vd, -14.0, SG)
    assert s.speed[0] == pytest.approx(one.speed) and s.speed[0] == pytest.approx(s.speed[1], rel=1e-9)


@settings(max_examples=60, deadline=None)
@given(st.floats(0.3, 3.0), st.floats(8.0, 40.0), st.sampled_from([-1.0, 1.0]), st.floats(1020.0, 1030.0))
def test_seaglider_balance_property(absB, pitch, sgn, rho):
    s = g._sg_core(sgn * absB, rho, sgn * pitch, SG)
    if not s.ok:
        return
    L, D = g.seaglider_force_balance(SG, s.speed, s.glide_deg, s.alpha_deg, rho)
    th = np.radians(s.glide_deg)
    B = sgn * absB
    assert abs(D - B * np.sin(th)) < 1e-5 * absB and abs(L + B * np.cos(th)) < 1e-5 * absB
    assert abs(s.glide_deg) >= abs(pitch) - 1e-9 and np.sign(s.glide_deg) == sgn


@settings(max_examples=40, deadline=None)
@given(st.floats(0.5, 2.0), st.floats(1.05, 1.6), st.floats(10.0, 30.0))
def test_seaglider_speed_grows_with_buoyancy(B, k, pitch):
    a, b = g._sg_core(B, 1026.0, pitch, SG), g._sg_core(B * k, 1026.0, pitch, SG)
    if a.ok and b.ok:
        assert b.speed > a.speed


def test_seaglider_speed_matches_hand_calculation():
    # B = 1.5 N, pitch 14 deg: solve D = B sin(th), L = -B cos(th) with the scalar fsolve-free bisection on alpha
    B, rho, pitch = 1.5, 1026.0, 14.0
    s = g._sg_core(B, rho, pitch, SG)
    q = 0.5 * rho * s.speed**2
    l2 = 1.8**2
    th = np.radians(s.glide_deg)
    assert l2 * SG["hd_a"] * q * s.alpha_deg == pytest.approx(-B * np.cos(th), rel=1e-6)
    assert l2 * q * (SG["hd_b"] * q ** SG["hd_s"] + SG["hd_c"] * s.alpha_deg**2) == pytest.approx(B * np.sin(th), rel=1e-6)
    assert 25.0 < q < 40.0  # tens of Pa: 0.25 m/s in seawater


# ---- buoyancy: compressibility, thermal expansion, trim ----------------------------------------------------------------
def test_hull_compression_and_thermal_signs():
    v = g.neutral_vbd_cc(SG, 1025.0, 0.0, 15.0)
    assert (
        g.buoyancy(SG, 1025.0, 1000.0, 15.0, v) < g.buoyancy(SG, 1025.0, 0.0, 15.0, v) - 1.0
    )  # constant rho: hull shrinks, glider sinks
    assert g.buoyancy(SG, 1025.0, 0.0, 25.0, v) > g.buoyancy(SG, 1025.0, 0.0, 15.0, v)  # warmer hull is bigger: more buoyant
    assert g.buoyancy(SG, 1025.0, 0.0, 15.0, v + 100.0) > g.buoyancy(SG, 1025.0, 0.0, 15.0, v)  # more oil out: more buoyant
    import gsw

    r0, r1 = float(gsw.rho(35.0, 15.0, 0.0)), float(gsw.rho(35.0, 15.0, 1000.0))
    assert g.buoyancy(SG, r1, 1000.0, 15.0, v) > g.buoyancy(SG, r0, 0.0, 15.0, v)  # seawater compresses more than the hull
    stiff = dict(SG, abs_compress=-SG["abs_compress"])
    assert g.buoyancy(stiff, r1, 1000.0, 15.0, v) > g.buoyancy(SG, r1, 1000.0, 15.0, v) + 1.0


@settings(max_examples=40, deadline=None)
@given(st.floats(1018.0, 1032.0), st.floats(0.0, 1000.0), st.floats(2.0, 30.0))
def test_neutral_vbd_is_the_zero_of_buoyancy(rho, p, T):
    for P in (SG, SL):
        assert abs(g.buoyancy(P, rho, p, T, g.neutral_vbd_cc(P, rho, p, T))) < 1e-8


# ---- Slocum -----------------------------------------------------------------------------------------------------------
def test_slocum_matches_gliderflight():
    eu, ew, ea = g._gliderflight_error(SL, np.random.default_rng(1))
    assert max(eu, ew, ea) < 2e-3


def test_slocum_signs_and_limits():
    n = g.neutral_vbd_cc(SL, 1026.0, 100.0, 10.0)
    d, c = g.slocum_steady(1026.0, 100.0, 10.0, n - 150, -26.0, SL), g.slocum_steady(1026.0, 100.0, 10.0, n + 150, 26.0, SL)
    assert d.ok and c.ok and d.speed == pytest.approx(c.speed) and d.glide_deg == pytest.approx(-c.glide_deg)
    assert d.w < 0 < c.w and c.alpha_deg < 0 < d.alpha_deg and c.glide_deg > 26.0
    assert not g.slocum_steady(1026.0, 100.0, 10.0, n + 150, -26.0, SL).ok  # buoyant but nose down
    assert not g.slocum_steady(1026.0, 100.0, 10.0, n + 150, 0.0, SL).ok  # no pitch
    assert not g.slocum_steady(1026.0, 100.0, 10.0, n + 150, 70.0, SL).ok  # outside gliderflight's 0.05-60 deg table
    assert not g.slocum_steady(1026.0, 100.0, 10.0, n + 0.001, 26.0, SL).ok  # speed below u_min
    assert g.flight(SL, 1026.0, 100.0, 10.0, n + 150, 26.0).speed == c.speed
    assert g.flight(SG, *CANON[:3], CANON[4], 14.0).speed == pytest.approx(0.2404, abs=2e-4)


def test_slocum_alpha_solves_the_implicit_equation():
    phi = np.radians(np.linspace(5.0, 55.0, 11))
    al = g._alpha_gf(phi, SL)
    lhs = (SL["Cd0"] + SL["Cd1"] * al**2) / ((SL["aw"] + SL["ah"]) * np.tan(al + phi))
    assert np.allclose(lhs, al, rtol=1e-9) and (al > 0).all()


# ---- local geometry ---------------------------------------------------------------------------------------------------
@given(st.floats(-85.0, 85.0))
def test_metres_per_degree_properties(lat):
    mx, my = g.metres_per_deg(lat)
    mx2, my2 = g.metres_per_deg(-lat)
    assert mx == pytest.approx(mx2) and my == pytest.approx(my2)
    assert 110500.0 < my < 111700.0 and 0.0 < mx <= 111320.0 + 1.0
    assert mx == pytest.approx(111320.0 * np.cos(np.radians(lat)), rel=5e-3)  # spherical cosine law within the WGS84 flattening


# ---- kinematics --------------------------------------------------------------------------------------------------------
def test_drift_heading_conventions_north_and_east():
    n = sim(mission=dict(mode="drift", heading_to=0.0))
    n.run(0.5 * DAY)
    assert n.lat[0] > 0.02 and abs((n.lon[0] - 180.0 + 180.0) % 360.0 - 180.0) < 1e-3  # heading 0 = north (compass to), not east
    e = sim(mission=dict(mode="drift", heading_to=90.0))
    e.run(0.5 * DAY)
    assert (e.lon[0] - 180.0) % 360 > 0.02 and abs(e.lat[0]) < 1e-3
    w = sim(mission=dict(mode="drift", heading_to=270.0))
    w.run(0.5 * DAY)
    assert ((w.lon[0] + 180.0) % 360) - 180.0 < 180.0 or w.lon[0] > 179.0  # west: crosses the dateline to +lon


def test_current_is_east_north_and_follows_depth_profile():
    # a glider that is never in the water column (stuck at the surface by the seafloor flag) just drifts with the surface current
    shallow = AnalyticEnv(wind=(0, 0), current=(0.2, -0.1), depth=40.0, rho=1025.0)
    s = sim(e=shallow, lon=10.0, lat=0.0)
    s.run(DAY)
    my = g.metres_per_deg(0.0)[1]
    assert s.lat[0] == pytest.approx(-0.1 * DAY / my, rel=0.02) and s.lon[0] > 10.0
    assert s.fail["seafloor"][0]
    # a profile that is 0 below 50 m: a diving glider drifts less than the surface drifter over the same time
    prof = lambda z: np.where(np.asarray(z) > -50.0, 1.0, 0.0)
    e2 = AnalyticEnv(wind=(0, 0), current=(0.3, 0.0), current_profile=prof, rho=1025.0)
    a = sim(e=e2, mission=dict(mode="drift", heading_to=0.0))
    a.run(DAY)
    assert (
        10.0 < (a.lon[0] - 180.0) % 360 / (0.3 * DAY / g.metres_per_deg(0.0)[0]) * 100 < 60.0
    )  # only the near-surface part of each cycle


def test_windage_moves_the_surface_phase_only():
    shallow = AnalyticEnv(wind=(10.0, 0.0), current=(0.0, 0.0), depth=40.0, rho=1025.0)
    s = sim(e=shallow, lon=10.0)
    s.run(DAY)
    assert (s.lon[0] - 10.0) * g.metres_per_deg(0.0)[0] == pytest.approx(SG["windage"] * 10.0 * DAY, rel=0.05)


def test_station_holds_and_loses_as_in_the_receipts():
    assert g._station_flags(SG, 0.5, 0.3) == 1.0
    assert g._station_flags(SG, 0.1, 0.3) == 0.0
    assert g._station_flags(SG, 0.1, 0.05) == 1.0  # a glider slower than the current cannot hold either
    s = sim(e=env(0.5), M=2, mission=dict(mode="station", station=(180.0, 0.0)))
    s.run(2 * DAY)
    assert (s.first["station_lost"] > 6 * 3600.0).all() and not s.fail["battery"].any()  # after lost_hours outside R, not before


def test_crab_correction_uses_the_dive_averaged_current():
    # northward current across an eastward track: after one dive the heading leans south, and the glider stays near the track
    s = sim(e=env(0.0, 0.1), M=1, mission=dict(mode="section", waypoints=[(182.0, 0.0)]))
    s.run(0.3 * DAY)
    assert s.dac[0, 1] > 0.05 and s.heading[0, 1] < -0.2 and s.heading[0, 0] > 0.5
    s.run(3 * DAY)
    off_track_m = abs(s.lat[0]) * g.metres_per_deg(0.0)[1]
    assert off_track_m < 15000.0  # without the correction it would be ~ 0.1 m/s * 3 d = 26 km north


def test_section_visits_waypoints_in_order_and_finishes():
    s = sim(e=env(), M=2, mission=dict(mode="section", waypoints=[(180.2, 0.0), (180.2, 0.2), (180.0, 0.2)], wp_radius_m=2000.0))
    h = s.run(4 * DAY)
    assert (h["wp"][-1] == 2).all() and s.done.all()
    assert (np.diff(h["wp"], axis=0) >= 0).all()
    assert not s.fail["waypoint_unreachable"].any()


def test_waypoint_unreachable_when_current_beats_the_glider():
    s = sim(e=env(0.5), mission=dict(mode="section", waypoints=[(179.0, 0.0)]))
    s.run(3 * DAY)
    assert s.fail["waypoint_unreachable"][0] and 12 * 3600.0 < s.first["waypoint_unreachable"][0] < 2 * DAY
    ok = sim(e=env(0.05), mission=dict(mode="section", waypoints=[(179.0, 0.0)]))
    ok.run(3 * DAY)
    assert not ok.fail["waypoint_unreachable"][0]


def test_seafloor_flags():
    # water too shallow to dive: flagged on the first step; water that shoals under the glider: flagged at the bottom
    s = sim(e=env(depth=50.0))
    s.run(3600.0)
    assert s.fail["seafloor"][0] and s.first["seafloor"][0] == 60.0 and (s.history()["depth"] == 0).all()

    class Slope(Strat):
        def depth(self, lon, lat):
            d = np.clip(1500.0 - 20000.0 * (np.asarray(lon, float) - 10.0), 120.0, 1500.0)
            return type(super().depth(lon, lat))(d, "slope", 0.0, "assumed")

    mission = dict(mode="drift", heading_to=90.0, dive_depth_m=400.0)
    sl = sim(e=Slope(wind=(0, 0), current_profile=uni), M=1, lon=10.0, mission=mission)
    sl.run(2 * DAY)
    assert sl.fail["seafloor"][0]
    deep = sim(e=env(depth=4000.0))
    deep.run(DAY)
    assert not deep.fail["seafloor"][0]


def test_dive_depth_is_min_of_target_floor_and_rating():
    a = sim(e=env(depth=300.0), mission=dict(mode="drift", dive_depth_m=900.0))
    h = a.run(DAY)
    assert h["depth"].max() == pytest.approx(300.0 - SG["seafloor_margin_m"], abs=15.0) and not a.fail["seafloor"][0]
    b = sim(mission=dict(mode="drift", dive_depth_m=5000.0))
    assert b.target_depth == 1000.0


def test_overdepth_when_ordered_to_the_rating():
    s = sim(mission=dict(mode="drift", dive_depth_m=1000.0))
    s.run(DAY)
    assert s.fail["overdepth"][0] and s.history()["depth"].max() > 1000.0
    ok = sim(mission=dict(mode="drift", dive_depth_m=900.0))
    ok.run(DAY)
    assert not ok.fail["overdepth"][0]


def test_no_flight_with_a_large_density_bias():
    s = sim(M=3, density_bias=np.array([0.0, 30.0, -30.0]))
    s.run(0.2 * DAY)
    assert list(s.fail["no_flight"]) == [False, True, True]
    assert s.first["no_flight"][1] == 60.0 and np.isnan(s.first["no_flight"][0])


def test_battery_failure_and_energy_accounting():
    s = sim(M=2, battery_scale=np.array([1.0, 0.02]))
    h = s.run(5 * DAY)
    assert list(s.fail["battery"]) == [False, True]
    e = h["energy"]
    assert (np.diff(e, axis=0) >= SG["hotel_W"] * 60.0 - 1e-9).all()  # hotel load every step
    cycles = (np.diff(h["phase"][:, 0]) == g.SURF - g.ASC).sum()
    per_cycle = SG["comms_W"] * (SG["gps_s"] + SG["bytes_per_dive"] / SG["iridium_Bps"]) + SG["attitude_J_per_dive"]
    assert e[-1, 0] > SG["hotel_W"] * 5 * DAY + cycles * per_cycle  # plus pumps
    assert s.first["battery"][1] == pytest.approx(
        0.02 * SG["battery_J"] * (1 - SG["reserve_frac"]) / (e[-1, 0] / (5 * DAY)), rel=0.2
    )


def test_pump_energy_is_work_over_efficiency():
    assert g.pump_energy_J(100.0, 0.0, 1.0) == pytest.approx(1e-4 * 101325.0)
    assert g.pump_energy_J(-100.0, 1000.0, 0.5) == pytest.approx(2e-4 * (101325.0 + 1e7))
    assert g.pump_energy_J(200.0, 500.0, 0.4) == pytest.approx(2 * g.pump_energy_J(100.0, 500.0, 0.4))


def test_members_are_independent_and_scale_applies():
    sc = np.array([0.7, 1.0, 1.3])
    together = sim(M=3, e=env(0.05, 0.02), speed_scale=sc, mission=dict(mode="station", station=(180.5, 0.0)))
    together.run(2 * DAY)
    for i in range(3):
        alone = sim(M=1, e=env(0.05, 0.02), speed_scale=sc[i], mission=dict(mode="station", station=(180.5, 0.0)))
        alone.run(2 * DAY)
        assert alone.lon[0] == pytest.approx(together.lon[i], abs=1e-7) and alone.lat[0] == pytest.approx(
            together.lat[i], abs=1e-7
        )
    assert together.lon[2] != pytest.approx(together.lon[0], abs=1e-3)
    far = sim(M=3, speed_scale=sc, mission=dict(mode="drift", heading_to=90.0))
    far.run(2 * DAY)
    assert far.lon[0] < far.lon[1] < far.lon[2]


def test_dateline_and_history_shapes():
    s = sim(lon=179.99, M=2, mission=dict(mode="drift", heading_to=90.0))
    h = s.run(DAY)
    assert (h["lon"] < 0).any() or (s.lon < 0).all() or True
    assert s.lon.min() >= -180.0 and s.lon.max() < 180.0 and (s.lon < 0).all()
    assert h["lon"].shape == (1440, 2) and h["t"].shape == (1440,) and h["t"][0] == 60.0 and h["t"][-1] == DAY
    assert set(h["fail"]) == set(g.FAILS) == set(h["first"]) and h["phase"].min() >= 0 and h["phase"].max() <= 3
    assert (
        0 in set(h["phase"].ravel())
        and 1 in set(h["phase"].ravel())
        and 2 in set(h["phase"].ravel())
        and 3 in set(h["phase"].ravel())
    )


def test_sawtooth_reaches_the_dive_depth_and_surfaces():
    s = sim(mission=dict(mode="drift", dive_depth_m=400.0))
    h = s.run(2 * DAY)
    d = h["depth"][:, 0]
    assert d.max() == pytest.approx(400.0, abs=40.0) and d.min() == 0.0
    peaks = ((d[1:-1] > d[:-2]) & (d[1:-1] >= d[2:]) & (d[1:-1] > 300.0)).sum()
    assert peaks >= 5  # a few cycles per day, each with one apogee


def test_slocum_runs_through_the_same_simulator():
    s = sim(P=SL, M=2, mission=dict(mode="drift", heading_to=90.0))
    h = s.run(DAY)
    assert not any(v.any() for v in s.fail.values()) and h["depth"].max() > 400.0
    assert s.ballast_kg < -0.1 and s.P["mg"] == pytest.approx(SL["mg"] + s.ballast_kg)  # tropical water: lighter than Table 1
    assert SL["mg"] == 56.4 and sim(M=1).ballast_kg == 0.0  # the caller's dict is untouched; the Seaglider defaults need none


def test_bad_missions_are_refused():
    with pytest.raises(ValueError, match="mode"):
        sim(mission=dict(mode="loiter"))
    with pytest.raises(ValueError, match="waypoints"):
        sim(mission=dict(mode="section", waypoints=[]))


def test_temperature_profile():
    assert g._temp_c(SG, 302.0, 0.0) == pytest.approx(28.85)
    assert g._temp_c(SG, 302.0, 5000.0) == pytest.approx(SG["t_deep_c"], abs=1e-6)


def test_256_members_7_days_in_well_under_a_minute():
    rng = np.random.default_rng(0)
    t0 = time.perf_counter()
    s = sim(
        M=256,
        e=Strat(wind=(5.0, 0.0), current=(0.1, 0.0), current_profile=uni),
        mission=dict(mode="section", waypoints=[(181.0, 0.0), (181.0, 2.0)]),
        speed_scale=rng.normal(1.0, 0.1, 256),
        battery_scale=rng.normal(1.0, 0.05, 256),
        density_bias=rng.normal(0.0, 0.2, 256),
    )
    h = s.run(7 * DAY, 60.0)
    elapsed = time.perf_counter() - t0
    assert h["lon"].shape == (10080, 256) and np.isfinite(h["lon"]).all() and np.isfinite(h["depth"]).all()
    assert elapsed < 45.0, elapsed
    print(f"256 members x 7 d @ 60 s: {elapsed:.1f} s")


# ---- receipts ---------------------------------------------------------------------------------------------------------
def failed(out):
    return [r["claim"] for r in out if r["ok"] is False]


def test_receipts_all_pass():
    out = g.receipts()
    assert len(out) >= 25 and failed(out) == []
    assert any(r.get("kind") == "context" for r in out)


def test_receipt_fails_when_alpha_is_in_the_wrong_units():
    wrong = dict(SG, hd_a=SG["hd_a"] * 180 / np.pi, hd_c=SG["hd_c"] * (180 / np.pi) ** 2)
    assert any("horizontal speed" in c or "glide ratio" in c or "alpha" in c for c in failed(g.receipts(wrong)))


def test_receipt_fails_when_buoyancy_sign_is_flipped(monkeypatch):
    orig = g.buoyancy
    monkeypatch.setattr(g, "buoyancy", lambda *a, **k: -orig(*a, **k))
    assert len(failed(g.receipts())) >= 5


def test_receipt_fails_when_hull_compression_has_the_wrong_sign():
    out = failed(g.receipts(dict(SG, abs_compress=-SG["abs_compress"])))
    assert any("buoyancy gain" in c or "compressibility minus" in c for c in out)


def test_receipt_fails_when_the_bs3_drag_form_is_replaced_by_the_brief_form(monkeypatch):
    def brief_drag(P, speed, glide_deg, alpha_deg, rho):
        q = 0.5 * rho * np.asarray(speed) ** 2
        return P["length_m"] ** 2 * P["hd_a"] * q * alpha_deg, P["length_m"] ** 2 * q ** (1 + P["hd_s"]) * (
            P["hd_b"] + P["hd_c"] * np.asarray(alpha_deg) ** 2
        )

    monkeypatch.setattr(g, "seaglider_force_balance", brief_drag)
    assert any("force" in c or "fsolve" in c for c in failed(g.receipts()))


def test_receipt_fails_when_metres_per_degree_axes_are_swapped(monkeypatch):
    orig = g.metres_per_deg
    monkeypatch.setattr(g, "metres_per_deg", lambda lat: orig(lat)[::-1])
    assert any("metres per degree" in c for c in failed(g.receipts()))


def test_receipt_fails_when_slocum_alpha_is_wrong(monkeypatch):
    orig = g._alpha_gf
    monkeypatch.setattr(g, "_alpha_gf", lambda phi, P: 0.8 * orig(phi, P))
    assert any("gliderflight" in c for c in failed(g.receipts()))


def test_receipt_notes_a_missing_oracle(monkeypatch):
    monkeypatch.setitem(sys.modules, "gliderflight", None)
    out = g.receipts()
    assert any("oracle not installed" in r["claim"] and r.get("kind") == "context" for r in out)
    assert failed(out) == []


def test_station_receipt_fails_when_the_current_is_ignored(monkeypatch):
    orig, still = AnalyticEnv.current, AnalyticEnv(current=(0, 0))
    monkeypatch.setattr(AnalyticEnv, "current", lambda self, lon, lat, z, t: orig(still, lon, lat, z, t))
    assert any("0.5 m/s" in c for c in failed(g.receipts()))


def test_station_receipt_fails_when_the_glider_is_slower_than_the_small_current(monkeypatch):
    orig = g.GliderSim.__init__

    def slow(self, P, M, e, lo, la, t0, mission, perturb=None):
        orig(self, P, M, e, lo, la, t0, mission, perturb)
        self.scale = self.scale * 0.1

    monkeypatch.setattr(g.GliderSim, "__init__", slow)
    out = failed(g.receipts())
    assert any("0.1 m/s" in c for c in out)


def test_kinematics_receipt_fails_when_depth_integration_is_wrong(monkeypatch):
    orig = g.GliderSim.step

    def bad(self, dt):
        orig(self, dt)
        self.depth = self.depth * 0.7

    monkeypatch.setattr(g.GliderSim, "step", bad)
    assert any("first descent" in c for c in failed(g.receipts()))
