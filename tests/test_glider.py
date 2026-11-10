"""cafe.pm.physics.glider: steady flight, kinematics, platform files, receipts (and that each receipt can fail)."""

import sys
import time

import numpy as np
import pytest
import gsw
import yaml
from hypothesis import given, settings, strategies as st

from cafe.pm import Tagged
from cafe.pm.env import perturb, subgrid
from cafe.pm.env.protocol import AnalyticEnv
from cafe.pm.stats.sampling import load_perturbations
from cafe.pm.physics import glider as g
from cafe.pm.physics import usv

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


@pytest.mark.parametrize("name", ["seaglider", "slocum"])
@pytest.mark.parametrize("value", ["no_such_modem", "benthos_atm960"])
def test_r14_l0_a_glider_file_with_a_modem_name_that_no_code_reads_is_refused_whatever_the_name(tmp_path, name, value):
    """`acoustic_modem: no_such_modem` loaded, and so did a real name: both changed no result (a link's modem is named in the mission). It is refused at load
    with the fix, and the shipped files no longer carry it."""
    raw = yaml.safe_load((g.PLATFORMS / f"{name}.yaml").read_text())
    assert "acoustic_modem" not in raw["params"] and "acoustic_modem" not in g.load_platform(name)
    raw["params"]["acoustic_modem"] = {"value": value, "unit": "-", "source": "a test"}
    f = tmp_path / "old.yaml"
    f.write_text(yaml.safe_dump(raw))
    with pytest.raises(ValueError, match=r"old\.yaml:params\.acoustic_modem: no code reads it .*modems\.yaml.*delete it"):
        g.load_platform(str(f))


def test_loader_accepts_a_good_file(tmp_path):
    """Review round 5, M-4: the old version loaded a stub with one invented parameter; a file now has to hold everything the model reads, so the
    good file is the shipped slocum.yaml with a parameter and a mission default added."""
    raw = yaml.safe_load((g.PLATFORMS / "slocum.yaml").read_text())
    raw["params"]["x"] = {"value": 2.0, "unit": "m", "assumed": True, "why": "because"}
    raw["mission_defaults"]["y"] = {"value": 1.0, "unit": "m", "source": "s"}
    f = tmp_path / "ok.yaml"
    f.write_text(yaml.safe_dump(raw))
    assert g.load_platform(str(f)) == {**SL, "x": 2.0, "mission_defaults": {**SL["mission_defaults"], "y": 1.0}}


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


def test_the_sde_moves_the_glider_position_by_a_random_walk_and_leaves_steering_and_the_dac_alone():
    M, steps, dt = 300, 720, 60.0
    pri = load_perturbations()
    pri["current_speed_scale"]["value"] = pri["current_direction_bias"]["value"] = 0.0
    base = env(0.1, 0.05)
    on_env = perturb.PerturbedEnv(base, {}, list(range(M)), 5, pri, sde=dict(t0=0.0, t1=steps * dt, dt=dt))
    off, on = sim(M=M, e=base), sim(M=M, e=on_env)
    off.run(steps * dt, dt)
    on.run(steps * dt, dt)
    for k in ("heading", "depth", "dac", "gd", "dr", "phase", "E"):
        assert np.allclose(getattr(off, k), getattr(on, k), rtol=1e-3, atol=1e-9), k      # state driven by the current never sees the SDE (gsw p(lat) differs)
    mx, my = g.metres_per_deg(0.0)
    d = np.stack([(on.lon - off.lon) * mx, (on.lat - off.lat) * my], -1)
    var = 2 * float(subgrid.sde_diffusivity(0.0)[0]) * steps * dt
    assert np.allclose(d.var(0), var, rtol=0.3) and np.all(np.abs(d.mean(0)) < 4 * np.sqrt(var / M))  # surface and subsurface both: a random walk of 2Kt


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


def test_a_per_member_windage_replaces_the_platforms_on_the_surface_phase():
    shallow = AnalyticEnv(wind=(10.0, 0.0), current=(0.0, 0.0), depth=40.0, rho=1025.0)
    s = sim(e=shallow, lon=10.0, M=3, windage=np.array([0.018, 0.02, 0.023]))
    s.run(DAY)
    drift = (s.lon - 10.0) * g.metres_per_deg(0.0)[0] / (10.0 * DAY)
    assert np.allclose(drift, [0.018, 0.02, 0.023], rtol=0.05) and drift[2] > drift[0]
    d = sim(e=shallow, lon=10.0, M=2)
    assert np.allclose(d.windage, SG["windage"])                                                    # without the perturbation: the platform's value


# ---- review round 5, M-1: a run never steps past the time it was asked for -------------------------------------------------
def test_run_stops_at_the_last_whole_step_inside_the_time_it_was_given():
    """M-1: 170 s at dt 60 was int(round(2.83)) = 3 steps, ending 10 s past the window; a deploy time with seconds then left the data."""
    h = sim().run(170.0)
    assert len(h["t"]) == 2 and h["t"][-1] <= 170.0
    assert [len(sim().run(x)["t"]) for x in (180.0, 179.9999999999, 59.0)] == [3, 3, 0]                    # a whole number of steps is unchanged


# ---- review round 6, M-10: a platform leaf the model divides by, exponentiates or integrates has a stated range -------------------------------------
def glider_file(tmp_path, kind, key, value):
    raw = yaml.safe_load((g.PLATFORMS / f"{kind}.yaml").read_text())
    raw["params"][key]["value"] = value
    f = tmp_path / f"{kind}.yaml"
    f.write_text(yaml.safe_dump(raw))
    return str(f)


@pytest.mark.parametrize("kind,key,value", [
    ("seaglider", "hd_s", -1.0), ("seaglider", "hd_s", 0.5), ("seaglider", "abs_compress", 0.0), ("seaglider", "abs_compress", -1.0),
    ("seaglider", "abs_compress", 1e12), ("seaglider", "therm_expan", 0.0), ("seaglider", "therm_expan", 1e12), ("seaglider", "temp_ref", 1e12),
    ("seaglider", "temp_ref", -1e12), ("seaglider", "t_deep_c", 1e12), ("seaglider", "gravity", 1e12), ("seaglider", "gravity", 0.0),
    ("seaglider", "apogee_overshoot", 1e12), ("seaglider", "apogee_overshoot", -1.0),
    ("slocum", "gravity", 1e12), ("slocum", "t_deep_c", 1e12), ("slocum", "apogee_overshoot", 1e12)])
def test_the_glider_loader_refuses_a_leaf_the_simulator_would_divide_by_or_exponentiate(tmp_path, kind, key, value):
    with pytest.raises(ValueError, match=rf"{kind}\.yaml:params\.{key}: .* must be a finite number"):
        g.load_platform(glider_file(tmp_path, kind, key, value))


def test_the_glider_loader_names_the_limit_and_still_takes_the_shipped_files(tmp_path):
    assert SG["hd_s"] == -0.25 and SL["gravity"] == 9.81
    with pytest.raises(ValueError, match=r"slocum\.yaml:params\.gravity: 1000000000000\.0 must be a finite number above 0 and at most 20"):
        g.load_platform(glider_file(tmp_path, "slocum", "gravity", 1e12))


def test_every_leaf_of_the_glider_tables_that_may_take_any_value_is_one_the_model_only_adds():
    """M-10: a new `any` leaf must be a conscious choice."""
    assert {k for t in g.REQUIRED.values() for k, v in t.items() if v == "any"} == {"vbd_min_cc"}


# ---- review round 7, M-35: a file without its top-level blocks is a ValueError naming the file and the blocks, not a KeyError
def test_r7_m35_the_glider_loader_names_the_file_and_the_missing_blocks(tmp_path):
    f = tmp_path / "typo.yaml"
    f.write_text("kind: seaglider\nmass_kg: 52\n")
    with pytest.raises(ValueError, match=r"typo\.yaml: missing \['params', 'mission_defaults'\]; add them \(see platforms/seaglider\.yaml"):
        g.load_platform(str(f))
    f.write_text("params: {}\nmission_defaults: {}\n")
    with pytest.raises(ValueError, match=r"typo\.yaml: missing \['kind'\]"):
        g.load_platform(str(f))


# ---- review round 8: M-13, M-14, M-28 and the glider terms of M-43 -----------------------------------------------------
def test_r8_m13_a_member_with_no_environment_at_its_start_does_not_remove_the_ballast_shift_of_the_others():
    both, hole = sim(P=SL, M=2, lon=np.array([180.0, 180.0])), sim(P=SL, M=2, lon=np.array([180.0, np.nan]))
    assert both.ballast_kg < -0.1 and hole.ballast_kg == pytest.approx(both.ballast_kg)                       # 0.0 before
    assert hole.vbd_dive[0] == both.vbd_dive[0] and hole.vbd_climb[0] == both.vbd_climb[0]
    assert sim(P=SL, M=1, lon=np.array([np.nan])).ballast_kg == 0.0                                          # none finite: no shift, no crash


class NoWind(Strat):
    def wind(self, lon, lat, z, t):
        return Tagged(np.full(np.shape(lon) + (2,), np.nan), "hole", 0.0, "assumed")


def test_r8_m14_a_hole_in_the_wind_at_a_surfacing_is_no_current_data_not_a_flight_model_failure():
    def modes(e):
        s = sim(M=8, e=e, mission=dict(mode="drift", heading_to=90.0))
        s.run(0.3 * DAY)
        return {k: int(v.sum()) for k, v in s.fail.items() if v.any()}, s
    assert modes(NoWind(wind=(0.0, 0.0), current=(0.0, 0.0), current_profile=uni))[0] == {"no_current_data": 8}     # {'no_flight': 8} before
    clean, s = modes(env())
    assert clean == {} and np.isfinite(s.lon).all() and g.FAILS[-1] == "no_current_data"


def test_r8_m28_a_negative_or_zero_dive_depth_is_refused_naming_the_field():
    for bad in (-50.0, 0.0, float("nan")):
        with pytest.raises(ValueError, match=r"dive_depth_m must be > 0, got"):
            sim(mission=dict(mode="drift", dive_depth_m=bad))


def test_r8_m43_the_battery_flag_fires_at_the_reserve_not_at_empty():
    """`reserve_frac` removed from the flag: the fire time is a few percent early, which the old rel=0.2 comparison could not see (the factor is 0.10)."""
    s = sim(battery_scale=np.array([0.02]))
    for _ in range(20000):
        s.step(60.0)
        if s.fail["battery"][0]:
            break
    assert s.fail["battery"][0] and (1.0 - SG["reserve_frac"]) < s.E[0] / s.cap[0] < (1.0 - SG["reserve_frac"]) + 0.02


def test_r8_m43_the_pilot_ballast_trigger_margin_is_the_whole_vbd_delta():
    """`d` halved in the trigger: a delta of 1.2 x the smaller room to a pump limit needs a shift, 0.6 x does not."""
    s0 = sim(mission=dict(mode="drift", vbd_delta_cc=0.0))
    lo, hi = SG["vbd_min_cc"], SG["vbd_min_cc"] + SG["vbd_range_cc"]
    room = min(s0.vbd_dive[0] - lo, hi - s0.vbd_climb[0])
    assert room > 1.0 and s0.ballast_kg == 0.0
    assert sim(mission=dict(mode="drift", vbd_delta_cc=1.2 * room)).ballast_kg != 0.0
    assert sim(mission=dict(mode="drift", vbd_delta_cc=0.9 * room)).ballast_kg == 0.0


def test_r8_m43_the_steering_reference_speed_is_that_at_mid_depth():
    """`k = 5` -> the surface: the reference speed differs by the density and temperature change over 500 m."""
    s = sim(mission=dict(mode="drift", dive_depth_m=500.0), lat=10.0)
    rho, p, T = s._state(np.full(1, 250.0))
    sd = g.flight(s.P, rho, p, T, s.vbd_dive, -s.P["pitch_deg"])
    sa = g.flight(s.P, rho, p, T, s.vbd_climb, s.P["pitch_deg"])
    uh = lambda r: float(r.speed[0] * np.cos(np.radians(r.glide_deg[0])))
    assert s.uh_ref[0] == pytest.approx(0.5 * (uh(sd) + uh(sa)), rel=1e-9)
    rho0, p0, T0 = s._state(np.zeros(1))
    sd0 = g.flight(s.P, rho0, p0, T0, s.vbd_dive, -s.P["pitch_deg"])
    assert abs(float(sd0.speed[0]) - float(sd.speed[0])) > 1e-4                                          # the test can tell the two depths apart


def test_r8_m43_a_member_with_half_the_speed_scale_descends_at_half_the_rate():
    s = sim(M=2, speed_scale=np.array([1.0, 0.5]))
    s.step(60.0)
    assert s.depth[0] > 0.1 and s.depth[1] == pytest.approx(0.5 * s.depth[0], rel=1e-9)


def surface_minutes(P):
    s = sim(P=P, mission=dict(mode="drift", heading_to=90.0))
    h = s.run(1.2 * DAY)
    ph = h["phase"][:, 0]
    first = int(np.argmax(ph == g.ASC))
    end = first + int(np.argmax(ph[first:] == g.SURF))
    return int(np.argmax(ph[end:] != g.SURF))


def test_r8_m43_the_surfacing_time_includes_the_data_bytes_over_the_iridium_rate():
    """`bytes_per_dive / iridium_Bps` removed from `surf_s`: 50 000 B at 200 B/s is 250 s of a surfacing of 490 s."""
    base, big = surface_minutes(SG), surface_minutes({**SG, "bytes_per_dive": 2 * SG["bytes_per_dive"]})
    assert big - base == pytest.approx(SG["bytes_per_dive"] / SG["iridium_Bps"] / 60.0, abs=1.01)


def test_r8_m43_the_attitude_energy_of_a_dive_is_in_the_battery_account():
    """`attitude_J_per_dive` removed from `comm_J`: two boats that differ only in it differ by exactly that at the first surfacing."""
    a, b = sim(), sim(P={**SG, "attitude_J_per_dive": SG["attitude_J_per_dive"] + 1.0e5})
    for _ in range(3000):
        a.step(60.0), b.step(60.0)
        if a.phase[0] == g.SURF and a.t > 3600.0:
            break
    assert a.phase[0] == g.SURF and b.E[0] - a.E[0] == pytest.approx(1.0e5, rel=1e-9)


def test_r8_m43_the_stall_speed_floors_the_glider_speed():
    """`u_min_ms` -> 0: with the floor at 0.05 m/s, a state flying at 0.044 m/s is no steady solution and one at 0.135 m/s is."""
    n = float(g.neutral_vbd_cc(SG, 1027.0, 0.0, 15.0))
    Q = {**SG, "u_min_ms": 0.05}
    slow, fast = (g.seaglider_steady(1027.0, 0.0, 15.0, n + e, SG["pitch_deg"], Q) for e in (10.0, 60.0))
    assert not slow.ok and slow.speed == 0.0 and fast.ok and fast.speed == pytest.approx(0.1352, abs=1e-3)
    assert g.seaglider_steady(1027.0, 0.0, 15.0, n + 10.0, SG["pitch_deg"], SG).speed == pytest.approx(0.0444, abs=1e-3)


def test_r8_m43_the_slocum_flies_only_with_buoyancy_in_the_direction_of_its_pitch():
    n = float(g.neutral_vbd_cc(SL, 1027.0, 0.0, 0.0))
    up, down = (g.slocum_steady(1027.0, 0.0, 0.0, n + e, pitch, SL) for e, pitch in ((+150.0, 26.0), (-150.0, -26.0)))
    assert up.ok and down.ok and up.glide_deg > 0 > down.glide_deg
    assert not g.slocum_steady(1027.0, 0.0, 0.0, n - 150.0, 26.0, SL).ok and not g.slocum_steady(1027.0, 0.0, 0.0, n + 150.0, -26.0, SL).ok
    assert down.glide_deg == pytest.approx(-up.glide_deg) and down.speed == pytest.approx(up.speed)
    assert down.alpha_deg == pytest.approx(-up.alpha_deg)                                                                  # alpha follows the pitch's sign
    assert g.slocum_steady(1027.0, 0.0, 0.0, n + 150.0, 59.0, SL).ok                                                      # the tabulated pitch range
    assert not g.slocum_steady(1027.0, 0.0, 0.0, n + 150.0, 61.0, SL).ok
    assert not g.slocum_steady(1027.0, 0.0, 0.0, n + 150.0, 0.04, SL).ok


def test_r8_m43_a_waypoint_inside_the_capture_radius_is_taken_and_one_outside_is_not():
    """The advance rule's radius halved: a waypoint at 0.75 radius is taken at the first dive, one at 1.25 radius is not."""
    r = SG["mission_defaults"]["wp_radius_m"]
    mx, _ = g.metres_per_deg(0.0)
    def idx(frac):
        s = sim(M=1, mission=dict(mode="section", waypoints=[(180.0 - frac * r / float(mx), 0.0), (178.0, 0.0)]), lon=179.0 + 1.0)
        s.step(60.0)
        return int(s.wp_idx[0])
    assert idx(0.75) == 1 and idx(1.25) == 0


# ---- review round 9: M-13 (a repeated waypoint), M-22 (the mission defaults the model indexes)
def test_r9_m13_a_repeated_waypoint_is_one_waypoint():
    """Before: `[A, A]` was two waypoints, so `wp` counted 1 on arrival and a leg of length zero sat at the end of `[A, B, B]`."""
    A, B = (180.2, 0.0), (180.2, 0.2)
    one, two = (sim(e=env(), M=2, mission=dict(mode="section", waypoints=w, wp_radius_m=2000.0)) for w in ([A], [A, A]))
    assert two.wps.tolist() == one.wps.tolist() == [list(A)]
    ab, abb = (sim(e=env(), M=2, mission=dict(mode="section", waypoints=w, wp_radius_m=2000.0)) for w in ([A, B], [A, A, B, B]))
    assert abb.wps.tolist() == ab.wps.tolist() == [list(A), list(B)]
    ha, hb = ab.run(4 * DAY), abb.run(4 * DAY)
    assert np.array_equal(ha["wp"], hb["wp"]) and np.array_equal(ha["lon"], hb["lon"]) and abb.done.all()
    aba = sim(e=env(), mission=dict(mode="section", waypoints=[A, B, A], wp_radius_m=2000.0))
    assert aba.wps.tolist() == [list(A), list(B), list(A)]  # not a repeat of its twin


@pytest.mark.parametrize("kind", ["seaglider", "slocum"])
@pytest.mark.parametrize("key", ["dive_depth_m", "station_tol_m", "lost_hours", "wp_radius_m", "unreach_hours"])
def test_r9_m22_a_platform_without_a_mission_default_the_model_indexes_is_refused_at_load_naming_it(tmp_path, kind, key):
    """Before: it loaded, and `run` died with a bare KeyError at the first step that read the key (the dive depth at construction, in every mode)."""
    raw = yaml.safe_load((g.PLATFORMS / f"{kind}.yaml").read_text())
    del raw["mission_defaults"][key]
    f = tmp_path / "glider.yaml"
    f.write_text(yaml.safe_dump(raw))
    with pytest.raises(ValueError, match=rf"glider\.yaml:mission_defaults: missing \['{key}'\]; add them \(see platforms/{kind}\.yaml"):
        g.load_platform(str(f))


def test_r9_m22_the_glider_table_names_exactly_the_mission_keys_of_the_shipped_files():
    for kind in ("seaglider", "slocum"):
        assert sorted(g.MISSION_REQUIRED) == sorted(yaml.safe_load((g.PLATFORMS / f"{kind}.yaml").read_text())["mission_defaults"])


# ---- review round 9, batch C leftovers: a hole in the density, the SST or the depth is `no_current_data`, not a vehicle failure -----------------------------
class HoleNorth(Strat):
    """A masked cell: NaN density / SST / depth from `lat_hole` north (`what` names which)."""

    def __init__(self, what, lat_hole=0.0, **kw):
        super().__init__(**kw)
        self.what, self.lat_hole = what, lat_hole

    def _gap(self, v, lat):
        return Tagged(np.where(np.asarray(lat, float) > self.lat_hole, np.nan, v.value), "hole", 0.0, "assumed")

    def density(self, lon, lat, z, t):
        v = super().density(lon, lat, z, t)
        return self._gap(v, np.broadcast_to(lat, v.value.shape)) if self.what == "density" else v

    def sst(self, lon, lat, t):
        v = super().sst(lon, lat, t)
        return self._gap(v, np.broadcast_to(lat, v.value.shape)) if self.what == "sst" else v

    def depth(self, lon, lat):
        v = super().depth(lon, lat)
        return self._gap(v, np.broadcast_to(lat, v.value.shape)) if self.what == "depth" else v


def failed_by(P, what, lat_hole, seconds):
    s = sim(P=P, M=2, e=HoleNorth(what, lat_hole, wind=(0.0, 0.0), current=(0.0, 0.0), current_profile=uni), mission=dict(mode="drift", heading_to=0.0))
    s.run(seconds)
    assert np.isfinite([s.lon, s.lat, s.depth, s.E]).all()                                        # a labelled failure, never a NaN vehicle
    return {k: int(v.sum()) for k, v in s.fail.items() if v.any()}


@pytest.mark.parametrize("what,P", [("density", SG), ("density", SL), ("sst", SG)])
def test_r9_a_hole_in_the_density_or_sst_met_in_flight_is_no_current_data_not_no_flight(what, P):
    """Before: {'no_flight': 2} (the flight model had no density to work with). The slocum model does not read the SST: see the next test."""
    assert failed_by(P, what, 0.005, 0.5 * DAY) == {"no_current_data": 2}


def test_r9_an_sst_hole_under_a_slocum_that_does_not_read_it_is_no_failure():
    assert failed_by(SL, "sst", 0.005, 0.5 * DAY) == {}


def test_r9_a_hole_in_the_depth_at_the_start_of_a_dive_is_no_current_data_not_seafloor():
    """Before: {'seafloor': 2}. A depth of 0 on land is still the sea floor (the protocol), only a depth that is not a number is a hole."""
    assert failed_by(SG, "depth", -1.0, 0.1 * DAY) == {"no_current_data": 2}


def test_r9_a_hole_in_the_depth_met_under_water_is_flagged_where_the_seafloor_test_could_not_see_it():
    """Before: {} (`depth >= NaN` is False, and the next dive start is hours away): the sea-floor test was off over the hole and nothing said so."""
    assert failed_by(SG, "depth", 0.003, 1800.0) == {"no_current_data": 2}


@pytest.mark.parametrize("kind", ["seaglider", "slocum"])
@pytest.mark.parametrize("key,bad", [("station_tol_m", 0.0), ("lost_hours", -1.0), ("wp_radius_m", 0.0), ("unreach_hours", -1.0)])
def test_r9_a_mission_default_out_of_its_range_is_refused_at_load_naming_it(tmp_path, kind, key, bad):
    """Before: the keys were kind 'any' (finite), so a capture radius of 0 (never reached) or negative hours loaded."""
    raw = yaml.safe_load((g.PLATFORMS / f"{kind}.yaml").read_text())
    raw["mission_defaults"][key]["value"] = bad
    f = tmp_path / "glider.yaml"
    f.write_text(yaml.safe_dump(raw))
    with pytest.raises(ValueError, match=rf"glider\.yaml:mission_defaults\.{key}: "):
        g.load_platform(str(f))


# ---- review round 11, M-12: the apogee overshoot is apogee_overshoot x w x pump_time, whatever dt --------------------------------------------
def apogee_overshoot_m(pump_s, dt, overshoot=0.5, kind=SG):
    """Depth gained between reaching the dive depth and the end of the apogee pump, and the last descent speed."""
    s = sim(P=dict(kind, pump_time_s=pump_s, apogee_overshoot=overshoot), mission=dict(mode="drift", heading_to=90.0, dive_depth_m=300.0))
    while s.phase[0] != g.APO:
        s.step(dt)
    d0 = s.depth[0]
    assert d0 == pytest.approx(300.0)
    while s.phase[0] == g.APO:
        s.step(dt)
    return s.depth[0] - d0, s.w_last[0]


@pytest.mark.parametrize("pump_s,dt", [(120.0, 60.0), (100.0, 60.0), (150.0, 60.0), (120.0, 300.0), (120.0, 120.0), (90.0, 45.0)])
def test_r11_m12_the_apogee_overshoot_is_half_the_descent_speed_times_the_pump_time_for_any_step(pump_s, dt):
    over, w = apogee_overshoot_m(pump_s, dt)
    assert w > 0.01 and over == pytest.approx(0.5 * w * pump_s, rel=1e-9)


def test_r11_m12_a_zero_overshoot_leaves_the_depth_and_a_slocum_follows_the_same_rule():
    assert apogee_overshoot_m(120.0, 60.0, overshoot=0.0)[0] == 0.0
    over, w = apogee_overshoot_m(150.0, 300.0, kind=SL)
    assert over == pytest.approx(0.5 * w * 150.0, rel=1e-9)


# ---- review round 11, M-28: details the module's tests passed without ----------------------------------------------------------------------
def test_r11_m28_a_good_dive_resets_the_stuck_clock_so_alternating_dives_never_flag_an_unreachable_waypoint():
    """The reset to 0.0 replaced by the old value passed every test: a section glider that loses ground only every other dive then flagged
    `waypoint_unreachable` for a total, not a run, of lost time."""
    s = sim(mission=dict(mode="section", waypoints=[(181.0, 0.0)]))
    s.step(60.0)                                                      # the first dive: nothing to compare with
    assert s.stuck_s[0] == 0.0
    limit = s.md["unreach_hours"] * 3600.0
    one = np.array([True])
    s.stuck_s[:] = 0.9 * limit
    s.d_prev[:] = 1e12                                                # the last dive started far away: this one gained ground
    s._begin_dive(one)
    assert s.stuck_s[0] == 0.0
    s.d_prev[:] = 0.0                                                 # the next one lost ground over a cycle of 0.2 limit
    s.t_prev_dive[:] = s.t - 0.2 * limit
    s._begin_dive(one)
    assert s.stuck_s[0] == pytest.approx(0.2 * limit) and not s.fail["waypoint_unreachable"][0]
    s.d_prev[:] = 0.0
    s.t_prev_dive[:] = s.t - 0.9 * limit
    s._begin_dive(one)
    assert s.stuck_s[0] == pytest.approx(1.1 * limit) and s.fail["waypoint_unreachable"][0]       # consecutive losses still add up to it


def test_r11_batch_b_advancing_to_the_next_waypoint_forgets_the_distance_to_the_last_one():
    """`d_prev[adv] = nan` removed passed every test: after the glider reaches a waypoint, the distance left to the NEXT one was compared with the
    distance it had to the one it just reached (small), so that dive counted as lost ground and the stuck clock ran."""
    s = sim(mission=dict(mode="section", waypoints=[(180.0, 0.0), (181.0, 0.0)]))
    s.step(60.0)
    one = np.array([True])
    s.wp_idx[:] = 0                                                   # on the first waypoint, which is where the glider is
    s.d_prev[:] = 0.0
    s.t_prev_dive[:] = s.t - 3600.0
    s._begin_dive(one)
    assert s.wp_idx[0] == 1
    assert s.stuck_s[0] == 0.0                                        # the new leg is not "lost ground" against the old one


def test_r11_batch_b_the_station_clock_runs_outside_the_tolerance_and_a_return_resets_it():
    """`out_s` reset to its old value passed every test: two short excursions counted as one long one and flagged `station_lost`."""
    s = sim(mission=dict(mode="station", station=(180.0, 0.0)))
    s.step(60.0)
    s.out_s[:] = 0.9 * s.md["lost_hours"] * 3600.0                    # an excursion that has ended: the glider is back on the station
    s.step(60.0)
    assert s.out_s[0] == 0.0 and not s.fail["station_lost"][0]
    s.lon[:] = -179.0                                                 # a degree east of the station, far beyond the tolerance
    s.step(60.0)
    assert s.out_s[0] == pytest.approx(60.0)


def test_r11_m28_the_surfacing_charges_the_comms_and_the_pump_that_empties_the_bladder_at_the_surface():
    s = sim(mission=dict(mode="drift", heading_to=90.0, dive_depth_m=200.0))
    e_prev, ph_prev = 0.0, s.phase[0]
    for _ in range(3000):
        s.step(60.0)
        if ph_prev == g.ASC and s.phase[0] == g.SURF:
            break
        e_prev, ph_prev = s.E[0], s.phase[0]
    assert s.phase[0] == g.SURF
    dV = s.vbd_climb[0] - s.vbd_dive[0]
    pump = float(g.pump_energy_J(dV, 0.0, SG["pump_eta"]))
    assert pump > 10.0                                                # a term of tens of joules: the mutant that drops it moves E by that
    assert s.E[0] - e_prev == pytest.approx(SG["hotel_W"] * 60.0 + s.comm_J + pump, rel=1e-9)



# ---- review round 11, M-25 (needed by batch A): a section that is not a mapping, a `kind` that is not a name -----------------------------------------------
@pytest.mark.parametrize("name, mod, change, said", [
    ("seaglider", g, lambda d: d.update(params=5), r"glider\.yaml:params: expected a mapping .*got int"),
    ("seaglider", g, lambda d: d.update(mission_defaults=[1]), r"glider\.yaml:mission_defaults: expected a mapping .*got list"),
    ("seaglider", g, lambda d: d.update(kind=["seaglider"]), r"glider\.yaml:kind: \['seaglider'\] must be a name"),
    ("saildrone_explorer", usv, lambda d: d.update(params=[1]), r"usv\.yaml:params: expected a mapping .*got list"),
    ("saildrone_explorer", usv, lambda d: d.update(mission_defaults="x"), r"usv\.yaml:mission_defaults: expected a mapping .*got str"),
    ("saildrone_explorer", usv, lambda d: d.update(kind=3), r"usv\.yaml:kind: 3 must be a name")])
def test_r11_m25_a_platform_file_of_the_wrong_shape_is_a_value_error_from_the_class_loader(tmp_path, name, mod, change, said):
    """Both loaders met `params: 5` with an AttributeError (`.items()`) and an unhashable `kind` with a TypeError; the callers caught them (round 11,
    M-25), but a direct caller (stage 1, report) met the raw error. `uas.load_platform` has always answered with ValueError."""
    raw = yaml.safe_load((g.PLATFORMS / f"{name}.yaml").read_text())
    change(raw)
    f = tmp_path / ("glider.yaml" if mod is g else "usv.yaml")
    f.write_text(yaml.safe_dump(raw))
    with pytest.raises(ValueError, match=said):
        mod.load_platform(str(f))
