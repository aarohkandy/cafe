"""Stage 1 orchestration (cafe/pm/stage1.py): launch schedule, priors, per-member draws, link evaluation, merge, summary, stopping loop.

Vehicle physics is replaced by small fakes where a test is about wiring (what a vehicle model is handed, what comes back); the
real models run against the CI fixture in test_pipeline.py.
"""
import types

import numpy as np
import pytest
from hypothesis import given, settings, strategies as st

from cafe.pm import config, ledger, stage1
from cafe.pm.env.perturb import PerturbedEnv
from cafe.pm.env.protocol import AnalyticEnv
from cafe.pm.physics import comms, glider, uas, usv
from cafe.pm.stats import intervals, sampling

MISSION = config.load_mission(config.ROOT / "missions" / "ci_fixture.yaml")
UTC = lambda s: config.utc(s).timestamp()
T0, T1 = UTC(MISSION["window"]["start"]), UTC(MISSION["window"]["end"])
SORT = {"local_solar_time": "14:00", "every_days": 1}
TGRID = np.arange(T0, T1 + 1, stage1.REC_S)
LK = {lk["id"]: lk for lk in MISSION["links"]}


# ---------------------------------------------------------------------------------------------------------------- launch times

def test_launches_are_at_14_local_solar_time_of_the_longitude():
    ts = stage1.launch_times(SORT, -165.0, T0, T1, 1920.0)               # 14:00 at 165 W is 25:00 UTC
    assert list(ts) == [UTC("2023-03-02T01:00:00Z"), UTC("2023-03-03T01:00:00Z")]
    assert list(stage1.launch_times(SORT, 165.0, T0, T1, 1920.0)) == [UTC("2023-03-02T03:00:00Z"), UTC("2023-03-03T03:00:00Z")]   # east: 11 h earlier
    assert list(stage1.launch_times({"local_solar_time": "14:30"}, 0.0, T0, T1, 60.0)) == [UTC("2023-03-02T14:30:00Z")]   # every_days defaults to 1


def test_every_days_spaces_the_launches():
    ts = stage1.launch_times({"local_solar_time": "09:00", "every_days": 3}, 10.0, T0, T0 + 12 * 86400.0, 600.0)
    assert len(ts) == 4 and np.allclose(np.diff(ts), 3 * 86400.0)
    assert np.allclose((ts / 3600.0 + 10.0 / 15.0) % 24.0, 9.0)


def test_a_launch_must_end_inside_the_window_and_may_touch_both_ends():
    t = UTC("2023-03-02T01:00:00Z")
    assert list(stage1.launch_times(SORT, -165.0, t, t + 600.0, 600.0)) == [t]                       # starts at t0, ends exactly at T
    assert stage1.launch_times(SORT, -165.0, t, t + 599.0, 600.0).size == 0                            # would end one second after T
    assert stage1.launch_times(SORT, -165.0, t + 1.0, t + 9000.0, 600.0).size == 0                    # starts one second before t0
    assert list(stage1.launch_times(SORT, -165.0, T0, T1, 1920.0 + 3600.0 * 5))[-1] == UTC("2023-03-02T01:00:00Z")   # the second one cannot finish


@settings(max_examples=60, deadline=None)
@given(hh=st.integers(0, 23), mm=st.sampled_from([0, 15, 30, 45]), lon=st.integers(-720, 720).map(lambda k: k / 4.0),
       t0=st.integers(0, 40_000).map(lambda h: 3600.0 * h), span=st.integers(1, 120).map(lambda h: 3600.0 * h), dur=st.sampled_from([60.0, 1200.0, 1920.0]))
def test_launch_times_are_complete_and_exactly_at_local_solar_time(hh, mm, lon, t0, span, dur):
    """Every instant of the day cycle that falls in [t0, T - dur] is returned, and nothing else."""
    T = t0 + span
    ts = stage1.launch_times({"local_solar_time": f"{hh:02d}:{mm:02d}"}, lon, t0, T, dur)
    off = int(round((hh + mm / 60.0 - lon / 15.0) * 3600.0))
    first = -(-(int(t0) - off) // 86400)                                    # ceil
    last = (int(T - dur) - off) // 86400
    want = [off + 86400 * k for k in range(first, last + 1)]
    assert [int(round(x)) for x in ts] == want


# ---------------------------------------------------------------------------------------------------------------- classes, priors

def test_vehicle_classes_follow_the_platform_and_the_base(tmp_path):
    assert stage1._classes(MISSION) == {"glider_eq": "glider", "glider_1n": "glider", "usv": "usv", "uas": "uas"}
    assert stage1.platform_kind("saildrone_explorer") == "wing_sail_usv" and stage1.platform_kind("seaglider") == "seaglider"
    odd = {"vehicles": [{"id": "a", "platform": "quad_uas", "base": "ship"}, {"id": "b", "platform": "quad_uas"}]}
    assert stage1._classes(odd) == {"a": "uas", "b": "glider"}                                       # `base` decides, not the platform
    nokind = tmp_path / "bare.yaml"
    nokind.write_text("params: {}\n")
    assert stage1.platform_kind(str(nokind)) == str(nokind)                                          # no `kind` key: the name stands in


def test_priors_follow_the_vehicle_classes_and_the_perturbation_file():
    pri, marg = stage1.priors_for(MISSION)
    assert list(marg) == stage1.FORCING + ["glider_speed_scale", "usv_vpp_bias", "battery_capacity_scale"]
    assert marg["wind_speed_bias"] == dict(dist="normal", mean=0.0, sd=pri["wind_speed_bias"]["value"])
    assert marg["current_speed_scale"]["dist"] == "lognormal"
    uas_only = {"vehicles": [{"id": "u", "platform": "quad_uas", "base": "ship"}]}
    assert list(stage1.priors_for(uas_only)[1]) == stage1.FORCING + ["battery_capacity_scale"]
    glider_only = {"vehicles": [{"id": "g", "platform": "seaglider"}]}
    assert list(stage1.priors_for(glider_only)[1]) == stage1.FORCING + ["glider_speed_scale", "battery_capacity_scale"]


def test_fitted_tao_priors_replace_the_defaults_and_nothing_else():
    base = stage1.priors_for(MISSION)
    fit = dict(wind_speed_bias=dict(dist="normal", mean=-0.4, value=1.2, unit="m/s", citation="TAO fit", kind="data"))
    pri, marg = stage1.priors_for(MISSION, fit)
    assert marg["wind_speed_bias"] == dict(dist="normal", mean=-0.4, sd=1.2) and pri["wind_speed_bias"]["kind"] == "data"
    assert {k: v for k, v in marg.items() if k != "wind_speed_bias"} == {k: v for k, v in base[1].items() if k != "wind_speed_bias"}
    assert stage1.priors_for(MISSION)[1]["wind_speed_bias"]["sd"] == base[0]["wind_speed_bias"]["value"]        # the file is not mutated


# ---------------------------------------------------------------------------------------------------------------- refit draws

SCALES = {"usv": {"drag": {"mean": 1.3, "sigma": 0.2}}}


def test_drag_is_one_when_the_vehicle_was_not_refit():
    for sc in (None, {}, {"other": SCALES["usv"]}, {"usv": {"lift": {"mean": 2.0}}}):
        assert stage1.refit_drag(sc, "usv", 7, [0, 1, 2]) == 1.0


def test_refit_drag_is_lognormal_with_its_median_at_the_refit_mean():
    d = stage1.refit_drag(SCALES, "usv", 7, list(range(4000)))
    z = np.log(d / 1.3)
    assert d.shape == (4000,) and (d > 0).all()
    assert abs(z.mean()) < 5 * (0.2 / 1.3) / np.sqrt(4000) and z.std() == pytest.approx(0.2 / 1.3, rel=0.05)
    assert np.all(stage1.refit_drag({"usv": {"drag": {"mean": 1.3, "sigma": 0.0}}}, "usv", 7, [0, 1, 2]) == 1.3)


def test_the_same_member_gets_the_same_drag_in_any_batch_and_any_vehicle_stream_is_separate():
    a = stage1.refit_drag(SCALES, "usv", 7, [0, 1, 2, 3])
    b = stage1.refit_drag(SCALES, "usv", 7, [3, 9, 1])
    assert b[0] == a[3] and b[2] == a[1]
    both = {"usv": SCALES["usv"], "glider_eq": SCALES["usv"]}
    assert stage1.refit_drag(both, "glider_eq", 7, [0, 1, 2, 3])[0] != a[0]                          # another vehicle draws from its own stream
    assert stage1.refit_drag(SCALES, "usv", 8, [0])[0] != a[0]                                       # and another mission seed from its own


# ---------------------------------------------------------------------------------------------------------------- Mann boxes

def capacity_fake(cap, calls):
    def turbulence_members(*args, n_boxes=None):
        calls.append(n_boxes)
        if n_boxes * cap < args[1]:
            raise ValueError(f"capacity {n_boxes * cap} < {args[1]} members")
        return types.SimpleNamespace(value=("series", n_boxes))
    return turbulence_members


def ascending_to(calls, top):
    return calls[0] == 1 and calls[-1] == top and calls == sorted(set(calls))


def test_fewest_boxes_tries_ascending_counts_and_stops_at_the_first_that_fits(monkeypatch):
    calls = []
    monkeypatch.setattr(stage1.subgrid, "turbulence_members", capacity_fake(3, calls))
    assert stage1._fewest_boxes((11, 10), 10) == ("series", 4) and ascending_to(calls, 4)


def test_fewest_boxes_never_exceeds_one_box_per_member_and_reraises_there(monkeypatch):
    calls = []
    monkeypatch.setattr(stage1.subgrid, "turbulence_members", capacity_fake(1, calls))
    assert stage1._fewest_boxes((11, 6), 6) == ("series", 6) and ascending_to(calls, 6)
    calls.clear()
    monkeypatch.setattr(stage1.subgrid, "turbulence_members", capacity_fake(0, calls))
    with pytest.raises(ValueError, match="capacity"):
        stage1._fewest_boxes((11, 5), 5)
    assert ascending_to(calls, 5)
    calls.clear()
    with pytest.raises(ValueError, match="capacity"):
        stage1._fewest_boxes((11, 1), 1)
    assert calls == [1]


@pytest.mark.parametrize("M,cap", [(10, 3), (5, 2), (7, 2), (9, 4), (8, 1), (3, 5)])
def test_fewest_boxes_is_the_smallest_box_count_that_fits(monkeypatch, M, cap):
    """The capacity check is free (it runs before any box is built), so the docstring's `fewest boxes` can be exact:
    doubling builds 4 boxes where 3 hold the members (each extra box is ~2 s)."""
    monkeypatch.setattr(stage1.subgrid, "turbulence_members", capacity_fake(cap, []))
    assert stage1._fewest_boxes((11, M), M)[1] == -(-M // cap)


# ---------------------------------------------------------------------------------------------------------------- UAS forcing

def uas_plat():
    return uas.load_platform("quad_uas")


def test_turbulence_and_gusts_are_off_when_the_mission_switches_them_off_or_the_env_has_no_surface_layer(ci_full):
    P, ts = uas_plat(), np.array([T0 + 8 * 3600.0, T0 + 32 * 3600.0])
    origin = (-165.0, 0.0)
    on = dict(environment=dict(subgrid=dict(turbulence=True, gust_fronts=True)))
    for env, mission in ((AnalyticEnv(), on),                                                             # no surface layer on the env
                         (ci_full, dict(environment=dict(subgrid=dict(turbulence=False, gust_fronts=False)))),
                         (ci_full, dict(environment=dict(subgrid={}))),
                         (ci_full, dict(environment={}))):
        turbs, gust = stage1._uas_forcing(env, mission, origin, ts, P, 2, 1, [0, 1])
        assert turbs == [None, None] and gust is None


def test_gust_fronts_alone_need_at_least_one_sortie(ci_full):
    mission = dict(environment=dict(subgrid=dict(gust_fronts=True)))
    turbs, gust = stage1._uas_forcing(ci_full, mission, (-165.0, 0.0), np.array([]), uas_plat(), 2, 1, [0, 1])
    assert turbs == [] and gust is None


def test_mann_turbulence_and_gust_fronts_are_per_member_deterministic_and_seeded_by_the_first_member(ci_full):
    P, M, origin = uas_plat(), 2, (-165.0, 0.0)
    ts = np.array([UTC("2023-03-02T01:00:00Z")])
    mission = dict(environment=dict(subgrid=dict(turbulence=True, gust_fronts=True)))
    turbs, gust = stage1._uas_forcing(ci_full, mission, origin, ts, P, M, 5, [0, 1])
    need = P["sortie"]["duration_s"] * P["sortie"]["hard_stop_factor"] + 60.0
    assert len(turbs) == 1 and turbs[0].shape[0] == M and turbs[0].shape[2] == 3 and turbs[0].shape[1] * uas.DT_ENV >= need
    assert np.isfinite(turbs[0]).all() and not np.allclose(turbs[0][0], turbs[0][1])                  # members are not copies of each other
    again, gust2 = stage1._uas_forcing(ci_full, mission, origin, ts, P, M, 5, [0, 1])
    assert np.array_equal(turbs[0], again[0])
    other, _ = stage1._uas_forcing(ci_full, mission, origin, ts, P, M, 5, [2, 3])
    assert not np.allclose(turbs[0], other[0])                                                        # a different first member is a different draw
    for t in (UTC("2023-03-02T01:00:00Z"), UTC("2023-03-02T00:00:00Z")):
        g = gust(t)
        assert g.shape == (M, 3) and np.isfinite(g).all() and np.all(g[:, 2] == 0.0)                  # horizontal gust, no vertical component
        assert np.array_equal(g, gust2(t))


# ---------------------------------------------------------------------------------------------------------------- UAS sorties

def uas_inputs(M=2, window=("2023-03-01T18:00:00Z", "2023-03-02T12:00:00Z")):
    v = next(x for x in MISSION["vehicles"] if x["id"] == "uas")
    mission = dict(MISSION, window=dict(start=window[0], end=window[1]))
    return v, uas_plat(), mission, UTC(window[0]), UTC(window[1]), {"battery_capacity_scale": np.full(M, 0.9)}


def test_a_window_with_no_launch_is_a_failure_of_every_member():
    v, P, mission, t0, T, X = uas_inputs(window=("2023-03-01T18:00:00Z", "2023-03-01T19:00:00Z"))
    r = stage1._run_uas(v, P, AnalyticEnv(), 2, X, t0, T, mission, 1, [0, 1])
    assert r["sorties"] == [] and r["scrubbed"].tolist() == [0, 0] and r["t"][0] == t0 and r["t"][-1] <= T
    assert r["fail"]["no_sortie_flown"].all() and not any(r["fail"][k].any() for k in uas.FLAGS)
    assert np.all(r["first"]["no_sortie_flown"] == T) and all(np.isnan(r["first"][k]).all() for k in uas.FLAGS)
    assert not r["airborne"].any() and np.allclose(r["lon"], -165.0) and np.allclose(r["lat"], 0.0)
    assert np.allclose(r["alt"], P["sortie"]["deck_height_m"]) and r["antenna_m"] == P["radio"]["uas_antenna_height_above_body_m"] == 0.1


def sortie_stub(calls, t_first_att=300.0):
    """fly_sortie replacement: member 0 flies east at 10 m/s for 20 min; member 1 goes DONE after 600 s and is scrubbed on the second sortie."""
    def fly_sortie(env, ship, t_launch, *, M, origin, plat, turb, gust, scale):
        calls.append(dict(t_launch=t_launch, origin=origin, plat=plat, turb=turb, gust=gust, scale=scale, ship=ship(0.0)))
        t = np.arange(0.0, 1201.0, 60.0)
        rel = np.zeros((M, t.size, 3))
        rel[:, :, 0] = 10.0 * t
        rel[:, :, 2] = 25.0
        phase = np.zeros((M, t.size))
        phase[1, t > 600.0] = uas.DONE
        flags = {k: np.zeros(M, bool) for k in uas.FLAGS}
        first = {k: np.full(M, np.nan) for k in uas.FLAGS}
        flags["attitude_exceedance"][1] = True
        first["attitude_exceedance"][1] = t_first_att
        return dict(t_launch=t_launch, track=dict(t=t, pos_rel=rel, phase=phase), flags=flags, t_first=first, scrubbed=np.array([False, len(calls) > 1]),
                    launch=dict(wind_ms=np.array([4.0, 5.0])), energy_wh=np.array([10.0, 11.0]), soc_end=np.array([0.5, 0.6]),
                    max_tilt_deg=np.array([7.0, 8.0]))
    return fly_sortie


def test_uas_sorties_are_gridded_every_10_minutes_while_airborne_and_flags_roll_up(monkeypatch):
    calls = []
    monkeypatch.setattr(stage1.uas, "fly_sortie", sortie_stub(calls))
    v, P, mission, t0, T, X = uas_inputs(window=("2023-03-01T18:00:00Z", "2023-03-03T06:00:00Z"))
    r = stage1._run_uas(v, P, AnalyticEnv(), 2, X, t0, T, mission, 1, [0, 1], drag=1.25)
    assert [c["t_launch"] for c in calls] == [UTC("2023-03-02T01:00:00Z"), UTC("2023-03-03T01:00:00Z")]
    c = calls[0]
    assert c["origin"] == (-165.0, 0.0) and c["turb"] is None and c["gust"] is None and np.all(c["ship"] == 0.0)    # the ship sits still
    assert c["plat"]["sortie"]["duration_s"] == 1200.0 and c["plat"]["sortie"]["levels_m"] == [10.0, 30.0, 60.0, 100.0]
    assert c["plat"]["launch_rule"]["max_mean_wind_ms"] == 12.0 and c["plat"]["launch_rule"]["gust_lookahead_min"] == 30.0   # no_gust_front_within_min
    assert uas_plat()["sortie"]["duration_s"] == 1200.0 and P["launch_rule"]["gust_lookahead_min"] == 15.0         # the caller's platform dict is untouched
    assert np.allclose(c["scale"]["drag"], 1.25) and np.allclose(c["scale"]["battery"], 0.9)
    k = int((UTC("2023-03-02T01:00:00Z") - t0) // 600)
    assert r["airborne"][k:k + 3, 0].tolist() == [True] * 3 and r["airborne"][k - 1, 0] == False and r["airborne"][k + 3, 0] == False   # noqa: E712
    assert r["airborne"][k:k + 3, 1].tolist() == [True, True, False]                                  # DONE after 600 s
    east = 6000.0 * np.arange(3)
    lon, lat = uas.lonlat((-165.0, 0.0), east, np.zeros(3))
    assert np.allclose(r["lon"][k:k + 3, 0], lon) and np.allclose(r["lat"][k:k + 3, 0], lat)
    assert np.allclose(r["alt"][k:k + 3, 0], 25.0 + P["sortie"]["deck_height_m"]) and r["alt"][k - 1, 0] == P["sortie"]["deck_height_m"]
    assert r["scrubbed"].tolist() == [0, 1] and r["fail"]["no_sortie_flown"].tolist() == [False, False]       # member 1 flew the first one
    assert r["fail"]["attitude_exceedance"].tolist() == [False, True]
    assert r["first"]["attitude_exceedance"][1] == UTC("2023-03-02T01:00:00Z") + 300.0 and np.isnan(r["first"]["attitude_exceedance"][0])
    assert [s["t_launch"] for s in r["sorties"]] == [c["t_launch"] for c in calls] and r["sorties"][0]["wind_ms"].tolist() == [4.0, 5.0]


def test_a_member_scrubbed_on_every_sortie_has_no_flux_profile(monkeypatch):
    monkeypatch.setattr(stage1.uas, "fly_sortie", lambda *a, **k: dict(sortie_stub([])(*a, **k), scrubbed=np.array([False, True])))
    v, P, mission, t0, T, X = uas_inputs()
    r = stage1._run_uas(v, P, AnalyticEnv(), 2, X, t0, T, mission, 1, [0, 1])
    assert r["fail"]["no_sortie_flown"].tolist() == [False, True] and r["first"]["no_sortie_flown"][1] == T and np.isnan(r["first"]["no_sortie_flown"][0])


def test_a_sortie_with_no_track_leaves_the_grid_alone(monkeypatch):
    def empty(env, ship, t_launch, *, M, **kw):
        z = np.zeros(M, bool)
        return dict(t_launch=t_launch, track=dict(t=np.zeros(0)), flags={k: z for k in uas.FLAGS}, t_first={k: np.full(M, np.nan) for k in uas.FLAGS},
                    scrubbed=np.ones(M, bool), launch=dict(wind_ms=np.zeros(M)), energy_wh=np.zeros(M), soc_end=np.ones(M), max_tilt_deg=np.zeros(M))
    monkeypatch.setattr(stage1.uas, "fly_sortie", empty)
    v, P, mission, t0, T, X = uas_inputs()
    r = stage1._run_uas(v, P, AnalyticEnv(), 2, X, t0, T, mission, 1, [0, 1])
    assert not r["airborne"].any() and r["fail"]["no_sortie_flown"].all() and r["scrubbed"].tolist() == [1, 1]


# ---------------------------------------------------------------------------------------------------------------- glider / USV wiring

class FakeSim:
    """Stands in for GliderSim / USVSim: records its constructor arguments, returns a 1-minute history of `n` steps."""
    last = None

    def __init__(self, *a, **k):
        FakeSim.last = (a, k)
        self.fail, self.first = {"mode": np.array([True, False])}, {"mode": np.array([42.0, np.nan])}

    def run(self, duration, dt, record_s=None):
        FakeSim.last += ((duration, dt, record_s),)
        n = int(duration // dt) + 1
        t = np.arange(n) * dt
        z = np.tile(t[:, None], (1, 2))
        return dict(t=t, lon=z + 1, lat=z + 2, depth=z + 3, phase=np.where(z % 1200 == 0, 3, 1), fail=self.fail, first=self.first)


def test_glider_station_task_reaches_the_sim_with_its_tolerances_and_the_refit_speed(monkeypatch):
    monkeypatch.setattr(stage1.glider, "GliderSim", FakeSim)
    v = next(x for x in MISSION["vehicles"] if x["id"] == "glider_eq")
    P, X = glider.load_platform("seaglider"), {"glider_speed_scale": np.array([1.0, 1.1]), "battery_capacity_scale": np.array([0.9, 1.0])}
    r = stage1._run_glider(v, P, "ENV", 2, X, 1000.0, 1000.0 + 7200.0, drag=np.array([4.0, 1.0]))
    (P_, M, env, lon, lat, t0, mis), kw, run_args = FakeSim.last
    assert (M, env, lon, lat, t0) == (2, "ENV", -165.5, 0.0, 1000.0)
    assert mis == dict(mode="station", dive_depth_m=950.0, station=(-165.5, 0.0), station_tol_m=5000.0, lost_hours=12.0)
    # drag 4 halves the speed
    assert np.allclose(kw["perturb"]["speed_scale"], [0.5, 1.1]) and np.allclose(kw["perturb"]["battery_scale"], X["battery_capacity_scale"])
    assert np.all(kw["perturb"]["density_bias"] == 0.0) and run_args == (7200.0, 60.0, None)
    assert r["t"].tolist() == list(np.arange(0.0, 7201.0, 600.0)) and r["lon"].shape == (13, 2)                      # kept every 10 minutes
    assert r["surfaced"].dtype == bool and r["surfaced"][:3, 0].tolist() == [True, False, True]                    # phase 3 is surfaced
    assert r["antenna_m"] == P["antenna_height_m"] == 0.5 and r["first"]["mode"][0] == 42.0 and r["fail"]["mode"].tolist() == [True, False]


def test_glider_drift_task_has_no_station_and_takes_the_default_dive_depth(monkeypatch):
    monkeypatch.setattr(stage1.glider, "GliderSim", FakeSim)
    P, X = glider.load_platform("slocum"), {"glider_speed_scale": np.ones(2), "battery_capacity_scale": np.ones(2)}
    deploy = dict(time="2023-03-01T18:00:00Z", lon=-165.0, lat=1.0)
    v = dict(id="g", platform="slocum", deploy=deploy, task=dict(mode="drift", waypoints=[[-165.0, 1.0], [-164.0, 1.0]]))
    r = stage1._run_glider(v, P, None, 2, X, 0.0, 3600.0)
    mis = FakeSim.last[0][6]
    assert mis == dict(mode="drift", dive_depth_m=P["mission_defaults"].get("dive_depth_m", 500.0), waypoints=[(-165.0, 1.0), (-164.0, 1.0)])
    assert np.allclose(FakeSim.last[1]["perturb"]["speed_scale"], 1.0) and r["antenna_m"] == P["antenna_height_m"] == 0.3


def test_usv_waypoints_become_tuples_and_the_drag_scales_the_vpp(monkeypatch):
    monkeypatch.setattr(stage1.usv, "USVSim", FakeSim)
    v = next(x for x in MISSION["vehicles"] if x["id"] == "usv")
    P, X = usv.load_platform("saildrone_explorer"), {"usv_vpp_bias": np.array([0.1, -0.2])}
    r = stage1._run_usv(v, P, "ENV", 2, X, 0.0, 7200.0, drag=np.array([4.0, 1.0]))
    args, kw = FakeSim.last[0], FakeSim.last[1]
    start, task = args[3], args[5]
    assert start == (-165.0, -1.0) and task["waypoints"] == [(-165.0, -1.0), (-165.0, 1.0)] and task["mode"] == "section"
    assert v["task"]["waypoints"] == [[-165.0, -1.0], [-165.0, 1.0]]
    assert np.allclose(kw["perturb"]["vpp_bias"], [(1.1) * 0.5 - 1, -0.2]) and FakeSim.last[2] == (7200.0, 60.0, stage1.REC_S)
    assert r["antenna_m"] == P["rf_antenna_height_m"] == 2.2 and r["surfaced"].all() and np.all(r["depth"] == 0.0) and r["fail"]["mode"][0]
    task_less = dict(v, task=dict(mode="station"))
    stage1._run_usv(task_less, P, "ENV", 2, X, 0.0, 600.0)
    assert FakeSim.last[0][5]["waypoints"] == []


# ---------------------------------------------------------------------------------------------------------------- run_batch wiring

def spy_vehicle_models(monkeypatch):
    seen = {}

    def record(kind, v, env, M, X, t0, T, drag, rest=()):
        seen[v["id"]] = dict(kind=kind, env=env, M=M, X=X, t0=t0, T=T, rest=rest, drag=drag)
        z = np.zeros((3, M))
        return dict(lon=z, lat=z, depth=z, t=np.arange(3.0), fail={}, first={})
    monkeypatch.setattr(stage1, "_run_glider", lambda v, P, env, M, X, t0, T, drag=1.0: record("glider", v, env, M, X, t0, T, drag))
    monkeypatch.setattr(stage1, "_run_usv", lambda v, P, env, M, X, t0, T, drag=1.0: record("usv", v, env, M, X, t0, T, drag))

    def run_uas(v, P, env, M, X, t0, T, mission, seed, members, drag=1.0):
        return record("uas", v, env, M, X, t0, T, drag, (mission, seed, members))
    monkeypatch.setattr(stage1, "_run_uas", run_uas)
    links = {}

    def evaluate_link(lk, out, mission, env, M, seed, members):
        links[lk["id"]] = (env, out, M, members)
        return dict(id=lk["id"])
    monkeypatch.setattr(stage1, "evaluate_link", evaluate_link)
    return seen, links


def test_every_vehicle_and_link_of_a_member_sees_one_perturbed_environment(monkeypatch):
    seen, links = spy_vehicle_models(monkeypatch)
    pri, marg = stage1.priors_for(MISSION)
    scales = {"usv": {"drag": {"mean": 1.3, "sigma": 0.2}}}
    base = AnalyticEnv()
    b = stage1.run_batch(MISSION, base, [4, 5, 6, 7], 11, pri, marg, scales)
    envs = {v["env"] for v in seen.values()} | {e for e, *_ in links.values()}
    assert len(envs) == 1 and isinstance(envs.pop(), PerturbedEnv) and set(seen) == {"glider_eq", "glider_1n", "usv", "uas"} and set(links) == set(LK)
    assert set(b["links"]) == set(LK) and b["U"].shape == (4, len(marg)) and set(b["X"]) == set(marg)
    assert {s["kind"] for s in seen.values()} == {"glider", "usv", "uas"} and all(s["M"] == 4 for s in seen.values())
    assert seen["glider_eq"]["t0"] == seen["glider_1n"]["t0"] == UTC("2023-03-01T18:00:00Z") and seen["usv"]["T"] == T1 and seen["uas"]["t0"] == T0
    # only the refit vehicle is scaled
    assert seen["usv"]["drag"].shape == (4,) and seen["glider_eq"]["drag"] == 1.0 and seen["uas"]["drag"] == 1.0
    assert np.array_equal(seen["usv"]["drag"], stage1.refit_drag(scales, "usv", 11, [4, 5, 6, 7]))
    assert seen["uas"]["rest"][1:] == (11, [4, 5, 6, 7]) and all(b["vehicles"][k]["wall_s"] >= 0 for k in seen)
    assert {b["vehicles"][k]["class"] for k in seen} == {"glider", "usv", "uas"}
    penv = next(iter(seen.values()))["env"]
    # only forcing errors perturb the environment
    assert set(penv.X) == set(stage1.FORCING)


def test_a_member_sees_the_same_random_field_whatever_batch_it_is_in(monkeypatch):
    seen, _ = spy_vehicle_models(monkeypatch)
    pri, marg = stage1.priors_for(MISSION)
    stage1.run_batch(MISSION, AnalyticEnv(), [0, 1, 2, 3], 11, pri, marg)
    first = seen["usv"]["env"]
    stage1.run_batch(MISSION, AnalyticEnv(), [2, 3, 4, 5], 11, pri, marg)
    second = seen["usv"]["env"]
    for f in ("fs", "fd"):
        a, b = getattr(first, f), getattr(second, f)
        assert np.array_equal(a.k[2], b.k[0]) and np.array_equal(a.ph[2], b.ph[0]) and np.array_equal(a.k[3], b.k[1])
        # different member, different field
        assert not np.array_equal(a.k[1], b.k[1])
    lon = lat = np.array([[-165.0, -164.9]] * 4)
    assert np.allclose(first.fs(lon, lat)[2], second.fs(lon, lat)[0])


def test_a_batch_draws_antithetic_pairs_and_is_reproducible(monkeypatch):
    """Same members, seed and priors: identical draws, so stage 1b reruns a batch and differs only by the refit; the dominant forcing errors are antithetic."""
    spy_vehicle_models(monkeypatch)
    pri, marg = stage1.priors_for(MISSION)
    a = stage1.run_batch(MISSION, AnalyticEnv(), list(range(8)), 11, pri, marg)
    b = stage1.run_batch(MISSION, AnalyticEnv(), list(range(8)), 11, pri, marg)
    assert np.array_equal(a["U"], b["U"]) and all(np.array_equal(a["X"][k], b["X"][k]) for k in marg)
    assert np.allclose(a["U"][:4, 0] + a["U"][4:, 0], 1.0) and np.allclose(a["X"]["wind_speed_bias"][:4], -a["X"]["wind_speed_bias"][4:])
    assert np.allclose(a["X"]["current_speed_scale"][:4] * a["X"]["current_speed_scale"][4:], 1.0)                                  # lognormal: reciprocal
    # the others are not paired
    assert not np.allclose(a["U"][:, 2] + a["U"][::-1, 2], 1.0)
    c = stage1.run_batch(MISSION, AnalyticEnv(), list(range(8, 16)), 11, pri, marg)
    # each batch is its own hypercube
    assert not np.array_equal(a["U"], c["U"])


# ---------------------------------------------------------------------------------------------------------------- links

def track(lon, lat, M, *, surfaced=True, airborne=None, antenna=1.0, alt=0.0, cls="usv", depth=0.0):
    """A vehicle record on the 10-min grid: (n, M) arrays from scalars or (n,) series."""
    n = TGRID.size
    f = lambda x: np.broadcast_to(np.asarray(x, float).reshape(-1, 1) if np.ndim(x) else np.full((1, 1), float(x)), (n, M)).copy()
    r = dict(t=TGRID, lon=f(lon), lat=f(lat), depth=f(depth), surfaced=np.broadcast_to(np.asarray(surfaced).reshape(-1, 1), (n, M)).copy(), antenna_m=antenna,
             **{"class": cls})
    if airborne is not None:
        r.update(airborne=np.broadcast_to(np.asarray(airborne).reshape(-1, 1), (n, M)).copy(), alt=f(alt))
    return r


def flat_env(M, wind=6.0, hs=1.0, u10=None):
    """A PerturbedEnv with no perturbation over an analytic base whose 10 m wind is `wind` (or u10(lon, lat, t) -> (..., 2))."""
    base = AnalyticEnv(hs=hs)
    base.u10 = u10 or (lambda lon, lat, t: np.stack([np.full(np.shape(t), wind), np.zeros(np.shape(t))], -1))
    return PerturbedEnv(base, {}, list(range(M)), 3, stage1.priors_for(MISSION)[0])


def km_north(km):
    return km / 111.195                                                                                     # degrees of latitude (6371 km sphere)


def link(i, **kw):
    return dict(LK[i], **kw)


def test_iridium_has_no_range_dependence_and_works_for_a_fraction_of_every_moment_of_the_window():
    out = {"usv": track(-165.0, -1.0, 4)}
    r = stage1.evaluate_link(LK["usv-shore-iridium"], out, MISSION, flat_env(4), 4, 3, [0, 1, 2, 3])
    assert r["method"].startswith("Iridium SBD") and r["t"].tolist() == TGRID.tolist() and r["need_count"].tolist() == [TGRID.size] * 4
    assert r["frac"].shape == (4,) and np.all((r["frac"] > 0.9) & (r["frac"] <= 1.0))                      # 5 % per attempt, three attempts
    assert set(np.unique(r["margin_db"])) <= {-1.0, 1.0} and np.array_equal(r["success"], r["frac"] >= 0.95)
    far = {"usv": track(-100.0, 40.0, 4)}
    # position is not an input
    assert np.array_equal(stage1.evaluate_link(LK["usv-shore-iridium"], far, MISSION, flat_env(4), 4, 3, [0, 1, 2, 3])["frac"], r["frac"])


def test_iridium_draws_are_seeded_by_mission_seed_first_member_and_link(monkeypatch):
    monkeypatch.setattr(stage1.comms, "iridium_session", lambda n, rng, M: (rng.random(M) < 0.5, None))
    out = {"usv": track(-165.0, -1.0, 4)}
    lk = LK["usv-shore-iridium"]
    ev = lambda lk=lk, seed=3, members=(0, 1, 2, 3): stage1.evaluate_link(lk, out, MISSION, flat_env(4), 4, seed, list(members))["margin_db"]
    base = ev()
    assert np.array_equal(base, ev()) and 0.3 < (base > 0).mean() < 0.7
    assert not np.array_equal(base, ev(seed=4)) and not np.array_equal(base, ev(members=(8, 9, 10, 11)))
    assert not np.array_equal(base, ev(lk=dict(lk, id="other")))
    # only the first member keys the stream
    assert np.array_equal(base, ev(members=(0, 9, 10, 11)))


def rf_scene(M=3, bad_samples=(0, 5, 6)):
    """USV 1 km north of the ship's longitude with the UAS airborne for samples 10..109; each member has bad_samples[m] of those out of range."""
    n = TGRID.size
    air = np.zeros(n, bool)
    air[10:110] = True
    lat_usv = np.full((n, M), km_north(1.0))
    for m, k in enumerate(bad_samples):
        lat_usv[10:10 + k, m] = km_north(100.0)                                                             # far beyond the radio horizon
    usv_r = track(-165.0, 0.0, M, antenna=2.2)
    usv_r["lat"] = lat_usv
    uas_r = track(-165.0, 0.0, M, airborne=air, alt=40.0, antenna=0.1, cls="uas", surfaced=True)
    return {"usv": usv_r, "uas": uas_r}, air


def test_rf_link_closes_in_range_fails_beyond_the_horizon_and_is_judged_only_while_the_uas_is_up():
    out, air = rf_scene()
    r = stage1.evaluate_link(LK["usv-uas-rf"], out, MISSION, flat_env(3), 3, 3, [0, 1, 2])
    assert r["need_count"].tolist() == [100] * 3 and np.isnan(r["margin_db"][~air]).all() and np.isfinite(r["margin_db"][air]).all()
    assert r["frac"].tolist() == [1.0, 0.95, 0.94]                                                          # 0, 5, 6 of 100 moments out of range
    assert r["success"].tolist() == [True, True, False]                                                     # required_fraction 0.95 is inclusive
    assert (r["margin_db"][10, 0] > 20.0) and r["margin_db"][10, 1] == comms.NO_LINK_DB                      # 1 km closes with margin; 100 km is NO_LINK
    assert "two-ray" in r["method"] and "rfd900x" in r["method"]
    swapped = stage1.evaluate_link(dict(LK["usv-uas-rf"], a="uas", b="usv"), out, MISSION, flat_env(3), 3, 3, [0, 1, 2])
    assert swapped["need_count"].tolist() == [100] * 3 and swapped["frac"].tolist() == r["frac"].tolist()   # either end can be the UAS


def test_rf_antenna_heights_are_the_platform_antennas_plus_the_flight_altitude():
    """At 17 km the 4/3-earth horizon decides: a 2.2 m whip and a UAS at 40 m reach 32 km; the same whip and a UAS at 3.9 m (horizon 14 km) do not."""
    for alt, closes in ((40.0, True), (3.9, False)):
        out, _ = rf_scene(M=1, bad_samples=(0,))
        out["usv"]["lat"][:] = km_north(17.0)
        out["uas"]["alt"][:] = alt
        r = stage1.evaluate_link(LK["usv-uas-rf"], out, MISSION, flat_env(1), 1, 3, [0])
        assert bool(r["success"][0]) is closes


def test_rf_margin_follows_the_members_significant_wave_height():
    """hs_scale is a forcing error of every member (FORCING): a 3 m sea roughens the surface reflection and a 0.2 m sea does not, at 300 m range,
    so two members with the same geometry and different hs_scale must not get the same RF margin."""
    base = AnalyticEnv(hs=1.0)
    base.u10 = lambda lon, lat, t: np.stack([np.full(np.shape(t), 6.0), np.zeros(np.shape(t))], -1)
    pri, marg = stage1.priors_for(MISSION)
    penv = PerturbedEnv(base, {"hs_scale": np.array([0.2, 3.0])}, [0, 1], 3, pri)
    out, _ = rf_scene(M=2, bad_samples=(0, 0))
    out["usv"]["lat"] = np.broadcast_to(km_north(np.linspace(0.2, 1.0, TGRID.size))[:, None], (TGRID.size, 2)).copy()
    r = stage1.evaluate_link(LK["usv-uas-rf"], out, MISSION, penv, 2, 3, [0, 1])
    air = out["uas"]["airborne"][:, 0]
    assert not np.allclose(r["margin_db"][air, 0], r["margin_db"][air, 1])


def acoustic_scene(M=3, far=(0, 0, 40)):
    """Glider surfaced for samples 0..59, at 2 km from the ship except `far[m]` of them at 60 km."""
    n = TGRID.size
    surf = np.zeros(n, bool)
    surf[:60] = True
    lat = np.full((n, M), km_north(2.0))
    for m, k in enumerate(far):
        lat[:k, m] = km_north(60.0)
    g = track(-165.0, 0.0, M, surfaced=surf, antenna=0.5, cls="glider", depth=np.where(surf, 0.0, 500.0))
    g["lat"] = lat
    return {"glider_eq": g}, surf


def test_acoustic_link_is_judged_while_the_glider_is_surfaced_and_fails_out_of_range():
    out, surf = acoustic_scene()
    lk = LK["glider_eq-ship-acoustic"]
    r = stage1.evaluate_link(lk, out, MISSION, flat_env(3), 3, 3, [0, 1, 2])
    assert r["need_count"].tolist() == [60] * 3 and np.isnan(r["margin_db"][~surf]).all()
    # 2 km closes, 60 km does not (ATM-960 MF reaches ~4 km)
    assert r["margin_db"][50, 0] > 0 and r["margin_db"][0, 2] < 0 and r["margin_db"][59, 2] > 0
    assert r["frac"].tolist() == [1.0, 1.0, pytest.approx(20 / 60)] and r["success"].tolist() == [True, True, False]
    assert "Thorp" in r["method"]
    rev = stage1.evaluate_link(dict(lk, a="ship", b="glider_eq"), out, MISSION, flat_env(3), 3, 3, [0, 1, 2])
    assert np.array_equal(rev["success"], r["success"]) and np.array_equal(rev["need_count"], r["need_count"])    # the ship end is not a vehicle


def test_acoustic_noise_follows_the_wind():
    out, _ = acoustic_scene(M=1, far=(0,))
    out["glider_eq"]["lat"][:] = km_north(4.0)
    calm = stage1.evaluate_link(LK["glider_eq-ship-acoustic"], out, MISSION, flat_env(1, wind=2.0), 1, 3, [0])
    gale = stage1.evaluate_link(LK["glider_eq-ship-acoustic"], out, MISSION, flat_env(1, wind=20.0), 1, 3, [0])
    assert np.nanmax(gale["margin_db"]) < np.nanmin(calm["margin_db"])                                      # wind noise eats margin in the MF band


def test_acoustic_noise_is_read_at_each_members_own_position():
    """Two members 4 km from the ship, one east of it in a 2 m/s wind and one west of it in a 20 m/s wind: their margins must differ."""
    out, _ = acoustic_scene(M=2, far=(0, 0))
    out["glider_eq"]["lat"][:] = 0.0
    out["glider_eq"]["lon"] = np.stack([np.full(TGRID.size, -165.0 + km_north(4.0)), np.full(TGRID.size, -165.0 - km_north(4.0))], 1)
    env = flat_env(2, u10=lambda lon, lat, t: np.stack([np.where(np.asarray(lon) > -165.0, 2.0, 20.0), np.zeros(np.shape(t))], -1))
    r =stage1.evaluate_link(LK["glider_eq-ship-acoustic"], out, MISSION, env, 2, 3, [0, 1])
    s = out["glider_eq"]["surfaced"][:, 0]
    assert np.nanmin(r["margin_db"][s, 0]) > np.nanmax(r["margin_db"][s, 1])


def test_acoustic_modem_name_may_carry_a_band_and_defaults_to_mf():
    out, _ = acoustic_scene(M=1, far=(0,))
    names = ("benthos_atm960_mf", "benthos_atm960", "benthos_atm960_LF", "benthos_atm960_hf")
    got = {m: stage1.evaluate_link(link("glider_eq-ship-acoustic", modem=m), out, MISSION, flat_env(1), 1, 3, [0]) for m in names}
    assert np.allclose(got["benthos_atm960"]["margin_db"], got["benthos_atm960_mf"]["margin_db"], equal_nan=True)
    assert not np.allclose(got["benthos_atm960_LF"]["margin_db"], got["benthos_atm960_mf"]["margin_db"], equal_nan=True)
    assert not np.allclose(got["benthos_atm960_hf"]["margin_db"], got["benthos_atm960_mf"]["margin_db"], equal_nan=True)


def test_a_modem_band_named_in_modems_yaml_can_be_chosen_by_a_link():
    """modems.yaml gives the WHOI Micro-Modem the bands long_10k and short_25k; the link parser knows only the LF/MF/HF suffixes, so a link
    `modem: whoi_micromodem_long_10k` is read as a modem of that whole name in the MF band and raises KeyError."""
    out, _ = acoustic_scene(M=1, far=(0,))
    r = stage1.evaluate_link(link("glider_eq-ship-acoustic", modem="whoi_micromodem_long_10k"), out, MISSION, flat_env(1), 1, 3, [0])
    assert np.isfinite(r["margin_db"][0, 0])


def test_the_method_of_an_acoustic_link_is_a_string_even_when_comms_returns_one_per_element(monkeypatch):
    out, _ = acoustic_scene(M=1, far=(0,))
    per_element = np.array(["bellhop", "bellhop"], dtype=object)
    res = lambda d, modem, band, wind: dict(margin=types.SimpleNamespace(value=np.full(np.shape(d), 5.0)), method=per_element, label="")
    monkeypatch.setattr(stage1.comms, "acoustic_link", res)
    r = stage1.evaluate_link(LK["glider_eq-ship-acoustic"], out, MISSION, flat_env(1), 1, 3, [0])
    assert isinstance(r["method"], str) and "bellhop" in r["method"] and r["success"].all()


def test_always_links_are_judged_at_every_moment_and_a_link_never_needed_counts_as_working():
    out, _ = rf_scene(M=2, bad_samples=(0, 0))
    r = stage1.evaluate_link(link("usv-uas-rf", when="always"), out, MISSION, flat_env(2), 2, 3, [0, 1])
    assert r["need_count"].tolist() == [TGRID.size] * 2 and np.isfinite(r["margin_db"]).all()
    never = dict(out["uas"], airborne=np.zeros_like(out["uas"]["airborne"]))
    r = stage1.evaluate_link(LK["usv-uas-rf"], {"usv": out["usv"], "uas": never}, MISSION, flat_env(2), 2, 3, [0, 1])
    assert r["need_count"].tolist() == [0, 0] and r["frac"].tolist() == [1.0, 1.0] and r["success"].all() and np.isnan(r["margin_db"]).all()


def test_position_of_the_ship_comes_from_the_mission_and_vehicles_carry_their_antenna():
    out = {"v": dict(track(-164.0, 1.0, 2, antenna=0.5, depth=30.0), alt=np.full((TGRID.size, 2), 10.0))}
    t = TGRID[:3]
    lon, lat, h, d = stage1._pos("v", out, MISSION, t)
    assert lon.shape == (3, 2) and np.all(lon == -164.0) and np.all(h == 10.5) and np.all(d == 30.0)
    lon, lat, h, d = stage1._pos("ship", out, MISSION, t)
    assert np.all(lon == -165.0) and np.all(lat == 0.0) and np.all(h == 15.0) and np.all(d == 5.0)
    bare = dict(MISSION, ship=dict(id="ship", lon=-165.0, lat=0.0))
    assert np.all(stage1._pos("ship", out, bare, t)[2] == 10.0) and np.all(stage1._pos("ship", out, bare, t)[3] == 5.0)    # defaults


def test_distance_is_the_great_circle_on_a_6371_km_sphere_and_wraps_the_dateline():
    a, b = (np.array([-165.0]), np.array([0.0])), (np.array([-165.0]), np.array([1.0]))
    assert stage1._dist(a, b)[0] == pytest.approx(111_194.9, rel=1e-4)
    assert stage1._dist((np.array([179.5]), np.array([0.0])), (np.array([-179.5]), np.array([0.0])))[0] == pytest.approx(111_194.9, rel=1e-4)
    # longitude shrinks with the cosine of the latitude
    assert stage1._dist((np.array([-165.0]), np.array([60.0])), (np.array([-164.0]), np.array([60.0])))[0] == pytest.approx(111_194.9 / 2, rel=1e-3)


# ---------------------------------------------------------------------------------------------------------------- merge, summarize

def synth_batch(members, p_fail=None, link_fail=None, names=None, ids=("glider_eq", "usv", "uas"), seed=11):
    """A batch in run_batch's shape built from a real LHS: member m of vehicle v fails when U[m, 0] < p_fail[v]."""
    M = len(members)
    pri, marg = stage1.priors_for(MISSION)
    U, X = sampling.lhs(M, marg, np.random.SeedSequence([seed, members[0]]), antithetic=("wind_speed_bias", "current_speed_scale"))
    t = np.arange(4) * 600.0
    vehicles = {}
    for vid in ids:
        f = U[:, 0] < (p_fail or {}).get(vid, 0.0)
        z = np.full((4, M), float(members[0]))
        r = dict(t=t, lon=z, lat=z + 1, depth=z * 0, surfaced=np.ones((4, M), bool), antenna_m=1.5, fail=dict(mode_a=f, mode_b=np.zeros(M, bool)),
                 first=dict(mode_a=np.where(f, 100.0 + np.arange(M), np.nan), mode_b=np.full(M, np.nan)), wall_s=1.0)
        r["class"] = "uas" if vid == "uas" else "usv" if vid == "usv" else "glider"
        if vid == "uas":
            r.update(alt=z * 0, airborne=np.zeros((4, M), bool), scrubbed=np.arange(M), sorties=[dict(t_launch=members[0])])
        vehicles[vid] = r
    links = {}
    for lid in LK:
        ok = U[:, 0] >= (link_fail or {}).get(lid, 0.0)
        links[lid] = dict(frac=np.where(ok, 1.0, 0.5), success=ok, margin_db=np.where(ok, 3.0, -3.0) * np.ones((4, M)), method=f"m-{lid}", t=t)
    return dict(U=U, X=X, vehicles=vehicles, links=links)


def test_merge_concatenates_along_members_and_keeps_per_vehicle_constants():
    a, b = synth_batch(list(range(0, 8))), synth_batch(list(range(8, 16)))
    m = stage1.merge([a, b])
    assert m["U"].shape == (16, a["U"].shape[1]) and all(v.shape == (16,) for v in m["X"].values())
    assert np.array_equal(m["U"][8:], b["U"]) and np.array_equal(m["X"]["hs_scale"][:8], a["X"]["hs_scale"])
    v = m["vehicles"]["usv"]
    assert v["lon"].shape == (4, 16) and np.all(v["lon"][:, :8] == 0.0) and np.all(v["lon"][:, 8:] == 8.0)          # members on the last axis
    assert v["t"] is a["vehicles"]["usv"]["t"] and v["class"] == "usv" and v["antenna_m"] == 1.5
    assert v["fail"]["mode_a"].shape == (16,) and v["first"]["mode_b"].shape == (16,) and "alt" not in v and "scrubbed" not in v
    u = m["vehicles"]["uas"]
    assert u["alt"].shape == u["airborne"].shape == (4, 16) and u["scrubbed"].tolist() == list(range(8)) * 2
    assert u["sorties"] == [dict(t_launch=0)]                                                                        # the first batch's sortie list
    lk = m["links"]["usv-uas-rf"]
    assert lk["frac"].shape == lk["success"].shape == (16,) and lk["margin_db"].shape == (4, 16) and lk["method"] == "m-usv-uas-rf"
    assert lk["t"] is a["links"]["usv-uas-rf"]["t"]


def test_failed_is_any_mode_and_empty_without_modes():
    r = dict(lon=np.zeros((3, 4)), fail=dict(a=np.array([1, 0, 0, 0], bool), b=np.array([0, 0, 1, 0], bool)))
    assert stage1.failed(r).tolist() == [True, False, True, False]
    assert stage1.failed(dict(lon=np.zeros((3, 4)), fail={})).tolist() == [False] * 4


def merged(p_fail, link_fail=None, n=24):
    return stage1.merge([synth_batch(list(range(i, i + 8)), p_fail, link_fail) for i in range(0, n, 8)])


def test_summary_verdicts_dominant_mode_and_first_failure_time():
    res = merged({"usv": 1.0, "uas": 0.0, "glider_eq": 0.25})
    names = list(stage1.priors_for(MISSION)[1])
    # the usv also fails in a second mode more often than in the first
    res["vehicles"]["usv"]["fail"]["mode_b"] = np.ones(24, bool)
    res["vehicles"]["usv"]["first"]["mode_b"] = 500.0 + np.arange(24.0)
    s = stage1.summarize(res, names, MISSION, intervals.n_certify())
    u = s["vehicles"]["usv"]
    assert u["cls"] == "usv" and u["n"] == 24 and u["k_fail"] == 24 and u["verdict"]["verdict"] == "NO-GO" and u["modes"] == dict(mode_a=24, mode_b=24)
    assert u["dominant"] == "mode_a" and u["first_fail_t"] == 100.0 and u["median_fail_t"] == pytest.approx(103.5)           # tie: the first mode named
    res["vehicles"]["usv"]["fail"]["mode_a"] = np.arange(24) < 10
    u = stage1.summarize(res, names, MISSION, 73)["vehicles"]["usv"]
    assert u["modes"] == dict(mode_a=10, mode_b=24) and u["dominant"] == "mode_b" and u["first_fail_t"] == 500.0 and u["median_fail_t"] == pytest.approx(511.5)
    g = s["vehicles"]["uas"]
    assert g["k_fail"] == 0 and g["dominant"] is None and g["first_fail_t"] is None and g["median_fail_t"] is None
    assert g["sensitivity"] == dict(param=None, S1={})
    assert "73 members" in g["verdict"]["note"]                                                                              # 24 members cannot certify
    h = s["vehicles"]["glider_eq"]
    assert 0 < h["k_fail"] < 24 and h["sensitivity"]["param"] == names[0] and set(h["sensitivity"]["S1"]) == set(names)       # driven by U[:, 0]


def test_summary_of_the_links():
    res = merged({}, {"usv-uas-rf": 0.25})
    names = list(stage1.priors_for(MISSION)[1])
    s = stage1.summarize(res, names, MISSION, 73)["links"]
    rf = s["usv-uas-rf"]
    assert rf["n"] == 24 and 0 < rf["k_fail"] < 24 and rf["method"] == "m-usv-uas-rf" and rf["frac_p10"] == 0.5 and rf["frac_median"] == 1.0
    assert rf["margin_db_median"] == 3.0 and rf["sensitivity"]["param"] == names[0]
    assert s["usv-shore-iridium"]["k_fail"] == 0 and s["glider_eq-ship-acoustic"]["k_fail"] == 0 and s["usv-shore-iridium"]["sensitivity"]["param"] is None
    res["links"]["usv-uas-rf"]["margin_db"][:] = np.nan
    assert stage1.summarize(res, names, MISSION, 73)["links"]["usv-uas-rf"]["margin_db_median"] is None


# ---------------------------------------------------------------------------------------------------------------- the stopping loop

@pytest.fixture
def batches(monkeypatch):
    """stage1.run_batch replaced by synth_batch with per-vehicle / per-link failure fractions; records (members, marg, scales) per call."""
    cfg = types.SimpleNamespace(p_fail={}, link_fail={}, calls=[])

    def run_batch(mission, env, members, seed, pri, marg, scales=None):
        cfg.calls.append((list(members), marg, scales, seed))
        return synth_batch(members, cfg.p_fail, cfg.link_fail, seed=seed)
    monkeypatch.setattr(stage1, "run_batch", run_batch)
    return cfg


def decided_all(cfg):
    cfg.p_fail = {"glider_eq": 1.0, "usv": 1.0, "uas": 1.0}
    cfg.link_fail = {lid: 1.1 for lid in LK}                                                            # every member fails every link


def drive(tmp_path, plan, **kw):
    log = []
    with ledger.Ledger(tmp_path, "stage1", "h") as L:
        r = stage1.run(MISSION, None, plan, L, log=log.append, **kw)
    return r, log, L


def test_the_ensemble_stops_as_soon_as_every_vehicle_and_link_is_decided(batches, tmp_path):
    decided_all(batches)
    r, log, L = drive(tmp_path, dict(batch=8, n_max=64, n_min=8))
    assert r["n"] == 8 and len(batches.calls) == 1 and "6/6 decided" in log[0]


def test_one_undecided_vehicle_keeps_the_ensemble_running_to_n_max(batches, tmp_path):
    decided_all(batches)
    batches.p_fail["usv"] = 0.3
    r, log, _ = drive(tmp_path, dict(batch=8, n_max=24, n_min=8))
    assert r["n"] == 24 and [c[0] for c in batches.calls] == [list(range(0, 8)), list(range(8, 16)), list(range(16, 24))]    # consecutive, disjoint members
    # n_max counts every stop as decided
    assert "5/6 decided" in log[0] and "5/6 decided" in log[1] and "6/6 decided" in log[2]


def test_one_undecided_link_keeps_the_ensemble_running_too(batches, tmp_path):
    decided_all(batches)
    batches.link_fail["usv-uas-rf"] = 0.3
    assert drive(tmp_path, dict(batch=8, n_max=16, n_min=8))[0]["n"] == 16


def test_nothing_is_decided_before_n_min(batches, tmp_path):
    decided_all(batches)
    assert drive(tmp_path, dict(batch=8, n_max=64, n_min=16))[0]["n"] == 16


def test_n_max_ends_the_ensemble_when_no_failures_leave_the_verdict_open(batches, tmp_path):
    r, log, _ = drive(tmp_path, dict(batch=8, n_max=16, n_min=8))
    assert r["n"] == 16 and not r["certify"] and r["n_certify"] == 73
    assert r["summary"]["vehicles"]["usv"]["verdict"]["verdict"] == "GO" and "73 members" in r["summary"]["vehicles"]["usv"]["verdict"]["note"]


def test_a_big_enough_ensemble_can_certify(batches, tmp_path):
    r, _, _ = drive(tmp_path, dict(batch=40, n_max=80, n_min=80))
    assert r["n"] == 80 and r["certify"] is True


def test_run_hands_the_priors_scales_and_seed_to_every_batch_and_returns_the_bookkeeping(batches, tmp_path):
    decided_all(batches)
    fit = dict(wind_speed_bias=dict(dist="normal", mean=-0.4, value=1.7, unit="m/s", citation="fit", kind="data"))
    sc = {"usv": {"drag": {"mean": 1.2, "sigma": 0.1}}}
    r, log, L = drive(tmp_path, dict(batch=8, n_max=8, n_min=8), scales=sc, fitted=fit)
    members, marg, scales, seed = batches.calls[0]
    assert marg["wind_speed_bias"] == dict(dist="normal", mean=-0.4, sd=1.7) and scales is sc and seed == MISSION["seed"]
    assert r["names"] == list(marg) and r["priors"] == marg and r["t0"] == "2023-03-01T18:00:00+00:00"
    assert set(r["summary"]) == {"vehicles", "links"} and set(r["summary"]["vehicles"]) == {"glider_eq", "usv", "uas"} and set(r["summary"]["links"]) == set(LK)
    assert r["res"]["U"].shape == (8, len(marg)) and "usv 1 s" in log[0]
    checks = {c["name"]: c for c in L.d["checks"]}
    assert list(checks) == ["lhs_stratified_batch1"] and checks["lhs_stratified_batch1"]["ok"]
    assert checks["lhs_stratified_batch1"]["limit"] == pytest.approx(1 / 8)


def test_each_batch_gets_its_own_stratification_check(batches, tmp_path):
    r, _, L = drive(tmp_path, dict(batch=8, n_max=24, n_min=8))
    assert [c["name"] for c in L.d["checks"]] == ["lhs_stratified_batch1", "lhs_stratified_batch2", "lhs_stratified_batch3"] and L.ok


def test_run_without_a_ledger_still_runs(batches):
    decided_all(batches)
    assert stage1.run(MISSION, None, dict(batch=8, n_max=8, n_min=8), log=lambda s: None)["n"] == 8
