"""Stage 1 orchestration (cafe/pm/stage1.py): launch schedule, priors, per-member draws, link evaluation, merge, summary, stopping loop.

Vehicle physics is replaced by small fakes where a test is about wiring (what a vehicle model is handed, what comes back); the
real models run against the CI fixture in test_pipeline.py.
"""
import types

import numpy as np
import pytest
from hypothesis import given, settings, strategies as st

from cafe.pm import Tagged, config, ledger, stage1
from cafe.pm.env.environment import OutsideData
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
P_USV = usv.load_platform("saildrone_explorer")


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


@pytest.mark.parametrize("every", [0.5, 0.25, 0.1])
def test_sub_daily_schedules_fill_the_whole_window(every):
    """M-4: the slot count was in days and then multiplied by every_days, so 0.5 d launched only for 4.5 of the 6 days (last launch at 03-05 13:00)."""
    t0, t1 = UTC("2023-03-01T12:00:00Z"), UTC("2023-03-07T12:00:00Z")
    ts = stage1.launch_times({"local_solar_time": "14:00", "every_days": every}, -165.0, t0, t1, 1920.0)
    period = 86400.0 * every
    assert np.allclose(np.diff(ts), period) and ts[0] - t0 < period and t1 - 1920.0 - ts[-1] < period
    assert len(ts) in (int(6 / every), int(6 / every) - 1)


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
    odd = {"vehicles": [{"id": "a", "platform": "quad_uas", "base": "ship"}, {"id": "b", "platform": "quad_uas"}]}
    assert stage1._classes(odd) == {"a": "uas", "b": "glider"}                                       # `base` decides, not the platform
    nokind = tmp_path / "bare.yaml"
    nokind.write_text("params: {}\n")
    assert stage1._classes({"vehicles": [{"id": "c", "platform": str(nokind)}]}) == {"c": "glider"}      # no `kind` key: the name stands in


def test_the_class_rule_is_the_one_in_config(monkeypatch):
    """Review round 3, M-17: stage 1 had its own copy of the rule that config.platform_class now holds once."""
    monkeypatch.setattr(stage1, "platform_class", lambda v: "usv" if v["id"] == "b" else "uas")
    assert stage1._classes({"vehicles": [{"id": "a", "platform": "seaglider"}, {"id": "b", "platform": "seaglider"}]}) == {"a": "uas", "b": "usv"}


def test_priors_follow_the_vehicle_classes_and_the_perturbation_file():
    pri, marg = stage1.priors_for(MISSION)
    assert list(marg) == stage1.FORCING + ["glider_speed_scale", "usv_vpp_bias", "bulk_stress_scale", "battery_capacity_scale"]
    assert marg["wind_speed_bias"] == dict(dist="normal", mean=0.0, sd=pri["wind_speed_bias"]["value"])
    assert marg["current_speed_scale"]["dist"] == "lognormal"
    uas_only = {"vehicles": [{"id": "u", "platform": "quad_uas", "base": "ship"}]}
    assert list(stage1.priors_for(uas_only)[1]) == stage1.FORCING + ["bulk_stress_scale", "battery_capacity_scale"]
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


def test_refit_drag_is_lognormal_with_its_mean_at_the_refit_mean():
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
    def fly_sortie(env, ship, t_launch, *, M, origin, plat, turb, gust, scale, link):
        calls.append(dict(t_launch=t_launch, origin=origin, plat=plat, turb=turb, gust=gust, scale=scale, ship=ship(0.0), link=link))
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
                    max_tilt_deg=np.array([7.0, 8.0]), sat_s=np.array([0.0, 12.0]), demand_ratio_max=np.array([1.0, 1.4]))
    return fly_sortie


def test_uas_sorties_are_gridded_every_10_minutes_while_airborne_and_flags_roll_up(monkeypatch):
    calls = []
    monkeypatch.setattr(stage1.uas, "fly_sortie", sortie_stub(calls))
    v, P, mission, t0, T, X = uas_inputs(window=("2023-03-01T18:00:00Z", "2023-03-03T06:00:00Z"))
    r = stage1._run_uas(v, P, AnalyticEnv(), 2, X, t0, T, mission, 1, [0, 1], drag=1.25)
    assert [c["t_launch"] for c in calls] == [UTC("2023-03-02T01:00:00Z"), UTC("2023-03-03T01:00:00Z")]
    c = calls[0]
    assert c["origin"] == (-165.0, 0.0) and c["turb"] is None and c["gust"] is None and np.all(c["ship"] == 0.0)    # the ship sits still
    assert all(callable(x["link"]) for x in calls)                                                      # every sortie is flown with the RF link hook
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
                    scrubbed=np.ones(M, bool), launch=dict(wind_ms=np.zeros(M)), energy_wh=np.zeros(M), soc_end=np.ones(M), max_tilt_deg=np.zeros(M),
                    sat_s=np.zeros(M), demand_ratio_max=np.ones(M))
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
        self.t0 = a[5] if len(a) == 7 else a[4]                 # GliderSim(P, M, env, lon, lat, t0, mis) / USVSim(P, M, env, start, t0, task)
        self.fail, self.first = {"mode": np.array([True, False])}, {"mode": np.array([42.0, np.nan])}
        self.path_m = np.array([3600.0, 7200.0])
        # glider energy; USV cross-track
        self.E, self.cap, self.xte_max, self.mode = np.array([1e5, 2e5]), np.array([4e5, 4e5]), np.array([1e3, 2e3]), "section"

    def run(self, duration, dt, record_s=None):
        """One record per step, the state after it (t0 + dt, t0 + 2 dt, ...), as the real simulators give."""
        FakeSim.last += ((duration, dt, record_s),)
        z = np.tile((np.arange(int(round(duration / dt))) + 1.0)[:, None] * dt, (1, 2))
        return dict(t=self.t0 + z[:, 0], lon=z + 1, lat=z + 2, depth=z + 3, phase=np.where(z % 1200 == 0, 3, 1), stw=np.full(z.shape, 0.5), fail=self.fail,
                    first=self.first)


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
    assert r["t"].tolist() == list(1000.0 + np.arange(0.0, 7201.0, 600.0)) and r["lon"].shape == (13, 2)          # t0 + 600 k: deploy state, then every 10 min
    assert r["lon"][:3, 0].tolist() == [-165.5, 601.0, 1201.0] and r["lat"][0].tolist() == [0.0, 0.0] and r["depth"][0].tolist() == [0.0, 0.0]
    assert r["surfaced"].dtype == bool and r["surfaced"][:3, 0].tolist() == [True, False, True]                    # phase 3 is surfaced
    assert r["antenna_m"] == P["antenna_height_m"] == 0.5 and r["first"]["mode"][0] == 42.0 and r["fail"]["mode"].tolist() == [True, False]
    far = stage1._dist((r["lon"], r["lat"]), (np.full_like(r["lon"], -165.5), np.full_like(r["lat"], 0.0))).max(0) / 1e3
    assert r["margin_name"] == "maximum distance from the station" and np.allclose(r["margin"], far) and far.min() > 1000.0  # M-2: a station glider's margin


def test_glider_and_usv_records_start_at_the_deploy_state_on_the_t0_plus_600_k_grid():
    """M-28: the records were the state after each 60 s step, so t0 + 60 + 600 k, with the deploy state missing."""
    t0, T = 1_000_000.0, 1_000_000.0 + 3600.0
    env = AnalyticEnv(wind=(-5.0, 0.0))
    g = next(x for x in MISSION["vehicles"] if x["id"] == "glider_eq")
    X = {"glider_speed_scale": np.ones(2), "battery_capacity_scale": np.ones(2), "usv_vpp_bias": np.full(2, -0.24)}
    rg = stage1._run_glider(g, glider.load_platform("seaglider"), env, 2, X, t0, T)
    u = next(x for x in MISSION["vehicles"] if x["id"] == "usv")
    ru = stage1._run_usv(u, usv.load_platform("saildrone_explorer"), env, 2, X, t0, T)
    for r, d in ((rg, g["deploy"]), (ru, u["deploy"])):
        assert r["t"].tolist() == (t0 + 600.0 * np.arange(7)).tolist()
        assert r["lon"].shape == r["lat"].shape == r["depth"].shape == r["surfaced"].shape == (7, 2)
        assert np.all(r["lon"][0] == d["lon"]) and np.all(r["lat"][0] == d["lat"]) and np.all(r["depth"][0] == 0.0) and r["surfaced"][0].all()
        assert np.any(r["lon"][1] != r["lon"][0]) or np.any(r["lat"][1] != r["lat"][0])                    # and then it moves


def test_glider_drift_task_has_no_station_and_takes_the_default_dive_depth(monkeypatch):
    monkeypatch.setattr(stage1.glider, "GliderSim", FakeSim)
    P, X = glider.load_platform("slocum"), {"glider_speed_scale": np.ones(2), "battery_capacity_scale": np.ones(2)}
    deploy = dict(time="2023-03-01T18:00:00Z", lon=-165.0, lat=1.0)
    v = dict(id="g", platform="slocum", deploy=deploy, task=dict(mode="drift", waypoints=[[-165.0, 1.0], [-164.0, 1.0]]))
    r = stage1._run_glider(v, P, None, 2, X, 0.0, 3600.0)
    mis = FakeSim.last[0][6]
    assert mis == dict(mode="drift", dive_depth_m=P["mission_defaults"].get("dive_depth_m", 500.0), waypoints=[(-165.0, 1.0), (-164.0, 1.0)])
    assert np.allclose(FakeSim.last[1]["perturb"]["speed_scale"], 1.0) and r["antenna_m"] == P["antenna_height_m"] == 0.3
    assert r["margin_name"] == "battery energy margin" and np.allclose(r["margin"], 1.0 - np.array([1e5, 2e5]) / (4e5 * (1.0 - P["reserve_frac"])))      # M-2
    stage1._run_glider(dict(v, task=dict(v["task"], heading_to=270.0)), P, None, 2, X, 0.0, 3600.0)
    assert FakeSim.last[0][6]["heading_to"] == 270.0                                                         # M-1: the task's heading reaches the simulator


def test_usv_waypoints_become_tuples_and_the_drag_scales_the_vpp(monkeypatch):
    monkeypatch.setattr(stage1.usv, "USVSim", FakeSim)
    v = next(x for x in MISSION["vehicles"] if x["id"] == "usv")
    P, X = usv.load_platform("saildrone_explorer"), {"usv_vpp_bias": np.array([0.1, -0.2])}
    r = stage1._run_usv(v, P, AnalyticEnv(wind=(-5.0, 0.0)), 2, X, 0.0, 7200.0, drag=np.array([4.0, 1.0]))
    args, kw = FakeSim.last[0], FakeSim.last[1]
    start, task = args[3], args[5]
    assert start == (-165.0, -1.0) and task["waypoints"] == [(-165.0, -1.0), (-165.0, 1.0)] and task["mode"] == "section"
    assert v["task"]["waypoints"] == [[-165.0, -1.0], [-165.0, 1.0]]
    assert np.allclose(kw["perturb"]["vpp_bias"], [(1.1) * 0.5 - 1, -0.2]) and FakeSim.last[2] == (7200.0, 60.0, stage1.DT_VEHICLE)
    assert r["antenna_m"] == P["rf_antenna_height_m"] == 2.2 and r["surfaced"].all() and np.all(r["depth"] == 0.0) and r["fail"]["mode"][0]
    assert r["t"].tolist() == list(np.arange(0.0, 7201.0, 600.0)) and r["lon"].shape == (13, 2) and r["lon"][:2, 0].tolist() == [-165.0, 601.0]
    assert r["margin_name"] == "maximum cross-track error" and r["margin"].tolist() == [1.0, 2.0]               # M-2: the sim's largest |xte|, in km
    task_less = dict(v, task=dict(mode="station", lon=-165.0, lat=0.0))
    stage1._run_usv(task_less, P, AnalyticEnv(), 2, X, 0.0, 600.0)
    assert FakeSim.last[0][5]["waypoints"] == []


# ---------------------------------------------------------------------------------------------------------------- run_batch wiring

def spy_vehicle_models(monkeypatch):
    seen = {}

    def record(kind, v, env, M, X, t0, T, drag, rest=(), windage=None):
        seen[v["id"]] = dict(kind=kind, env=env, M=M, X=X, t0=t0, T=T, rest=rest, drag=drag, windage=windage)
        z = np.zeros((3, M))
        return dict(lon=z, lat=z, depth=z, t=np.arange(3.0), fail={}, first={})
    monkeypatch.setattr(stage1, "_run_glider", lambda v, P, env, M, X, t0, T, drag=1.0, windage=None:
                        record("glider", v, env, M, X, t0, T, drag, windage=windage))
    monkeypatch.setattr(stage1, "_run_usv", lambda v, P, env, M, X, t0, T, drag=1.0: record("usv", v, env, M, X, t0, T, drag))

    def run_uas(v, P, env, M, X, t0, T, mission, seed, members, drag=1.0, used=None):
        return record("uas", v, env, M, X, t0, T, drag, (mission, seed, members))
    monkeypatch.setattr(stage1, "_run_uas", run_uas)
    links = {}

    def evaluate_link(lk, out, mission, env, M, seed, members, used=None):
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
    base.wind = lambda lon, lat, z, t: Tagged(np.asarray(base.u10(lon, lat, t), float), "flat", 0.0, "assumed")          # 10 m wind = u10
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
    assert np.isnan(r["margin_db"]).all() and r["n_invalid"].tolist() == [0] * 4 and r["invalid_kind"] is None          # M-19: a success flag is not a margin
    assert "Iridium" in r["margin_kind"] and np.array_equal(r["success"], r["frac"] >= 0.95)
    far = {"usv": track(-100.0, 40.0, 4)}
    # position is not an input
    assert np.array_equal(stage1.evaluate_link(LK["usv-shore-iridium"], far, MISSION, flat_env(4), 4, 3, [0, 1, 2, 3])["frac"], r["frac"])


def test_iridium_draws_are_seeded_by_mission_seed_first_member_and_link(monkeypatch):
    monkeypatch.setattr(stage1.comms, "iridium_session", lambda n, rng, M: (rng.random(M) < 0.5, None))
    out = {"usv": track(-165.0, -1.0, 4)}
    lk = LK["usv-shore-iridium"]
    ev = lambda lk=lk, seed=3, members=(0, 1, 2, 3): stage1.evaluate_link(lk, out, MISSION, flat_env(4), 4, seed, list(members))["frac"]
    base = ev()
    assert np.array_equal(base, ev()) and 0.3 < base.mean() < 0.7
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
    assert r["need_count"].tolist() == [100] * 3 and np.isnan(r["margin_db"][~air]).all()
    assert np.isfinite(r["margin_db"][air]).sum(0).tolist() == [100, 95, 94]                                 # a margin only where there is a budget
    assert r["frac"].tolist() == [1.0, 0.95, 0.94]                                                          # 0, 5, 6 of 100 moments out of range
    assert r["success"].tolist() == [True, True, False]                                                     # required_fraction 0.95 is inclusive
    assert (r["margin_db"][10, 0] > 20.0) and np.isnan(r["margin_db"][10, 1])                      # 1 km closes with margin; 100 km is no budget at all
    assert r["n_invalid"].tolist() == [0, 5, 6] and r["invalid_kind"] == "beyond_horizon" and r["margin_kind"] == "RF link margin, dB"
    assert np.nanmin(r["margin_db"]) > comms.NO_LINK_DB                                                      # M-19: the -200 dB clip is never a margin
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
    assert r["margin_db"][50, 0] > 0 and np.isnan(r["margin_db"][0, 2]) and r["margin_db"][59, 2] > 0         # 60 km is beyond the budget's valid range
    assert r["n_invalid"].tolist() == [0, 0, 40] and r["invalid_kind"] == "out_of_range"
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
    res = lambda d, modem, band, wind, dz: dict(margin=types.SimpleNamespace(value=np.full(np.shape(d), 5.0)), method=per_element, label="")
    monkeypatch.setattr(stage1.comms, "acoustic_link", res)
    r = stage1.evaluate_link(LK["glider_eq-ship-acoustic"], out, MISSION, flat_env(1), 1, 3, [0])
    assert isinstance(r["method"], str) and "bellhop" in r["method"] and r["success"].all()


def test_a_nan_position_is_not_a_moment_the_link_was_required():
    """M-19: rf_margin(d = nan) scored -200 (the horizon test is False for nan), so a vehicle with no position failed every link."""
    out, _ = rf_scene(M=2, bad_samples=(0, 0))
    out["usv"]["lat"][20:30, 1] = np.nan
    r = stage1.evaluate_link(LK["usv-uas-rf"], out, MISSION, flat_env(2), 2, 3, [0, 1])
    assert r["need_count"].tolist() == [100, 90] and r["frac"].tolist() == [1.0, 1.0] and r["n_invalid"].tolist() == [0, 0]
    assert np.isnan(r["margin_db"][20:30, 1]).all()


def test_the_link_summary_says_how_often_the_geometry_alone_decided_and_never_a_clip_value_as_a_margin():
    out, _ = rf_scene()
    res = stage1.merge([dict(U=np.zeros((3, 1)), X={"a": np.zeros(3)}, vehicles={}, links={
        "usv-uas-rf": stage1.evaluate_link(LK["usv-uas-rf"], out, MISSION, flat_env(3), 3, 3, [0, 1, 2])})])
    s = stage1.summarize(res, ["a"], MISSION, 73)["links"]["usv-uas-rf"]
    assert s["frac_beyond_horizon"] == pytest.approx(11 / 300) and s["frac_out_of_range"] is None and s["margin_kind"] == "RF link margin, dB"
    assert s["margin_db_median"] > 20.0                                                                    # of the samples that have a budget
    out, _ = acoustic_scene()
    ac = stage1.merge([dict(U=np.zeros((3, 1)), X={"a": np.zeros(3)}, vehicles={}, links={
        "glider_eq-ship-acoustic": stage1.evaluate_link(LK["glider_eq-ship-acoustic"], out, MISSION, flat_env(3), 3, 3, [0, 1, 2])})])
    a = stage1.summarize(ac, ["a"], MISSION, 73)["links"]["glider_eq-ship-acoustic"]
    assert a["frac_out_of_range"] == pytest.approx(40 / 180) and a["frac_beyond_horizon"] is None and a["margin_db_median"] > 0
    ir = stage1.merge([dict(U=np.zeros((4, 1)), X={"a": np.zeros(4)}, vehicles={}, links={
        "usv-shore-iridium": stage1.evaluate_link(LK["usv-shore-iridium"], {"usv": track(-165.0, -1.0, 4)}, MISSION, flat_env(4), 4, 3, [0, 1, 2, 3])})])
    i = stage1.summarize(ir, ["a"], MISSION, 73)["links"]["usv-shore-iridium"]
    assert i["margin_db_median"] is None and i["frac_beyond_horizon"] is None and i["frac_out_of_range"] is None and i["frac_median"] > 0.9


# ------------------------------------------------------------------------------------------------------------ M-13: Bellhop for the ambiguous acoustic links

def bellhop_scene(monkeypatch, km=4.5, depth=300.0, available=True):
    """A glider `depth` m down, `km` km from the ship, `always` judged, in a column whose sound speed rises with depth; Bellhop is a fake
    that records what it was given and adds 7 dB over the isovelocity column. Returns (result, recorded calls, thorp margin of the same slant path)."""
    calls = []

    def fake(r, f, z, c, tx, rx, wd):
        calls.append(dict(z=np.asarray(z), c=np.asarray(c), tx=tx, rx=rx, wd=wd))
        return 20 * np.log10(r) + (7.0 if c[-1] != c[0] else 0.0)
    monkeypatch.setattr(comms, "bellhop_available", lambda: available)
    monkeypatch.setattr(comms, "_run_bellhop", fake)
    out, _ = acoustic_scene(M=1, far=(0,))
    out["glider_eq"]["lat"][:] = km_north(km)
    out["glider_eq"]["depth"][:] = depth
    env = flat_env(1)
    env.env.sound_speed = lambda lon, lat, z, t: types.SimpleNamespace(value=1500.0 - 0.02 * np.asarray(z, float))
    r = stage1.evaluate_link(link("glider_eq-ship-acoustic", when="always"), out, MISSION, env, 1, 3, [0])
    thorp = comms.acoustic_margin(np.hypot(km * 1e3, depth - 5.0), wind=6.0)
    return r, calls, float(thorp)


def test_an_ambiguous_acoustic_link_is_refined_with_bellhop_on_the_gofs_profile_at_the_slant_range(monkeypatch):
    r, calls, thorp = bellhop_scene(monkeypatch)
    assert abs(thorp) <= 6.0                                                                              # engineered to sit in the ambiguity band
    assert np.allclose(r["margin_db"], thorp - 7.0, atol=0.3)                                             # slant range + Bellhop excess, every sample
    assert r["method"].startswith("Thorp/Stojanovic budget on the slant range, Bellhop on ") and "of" in r["method"] and "Thorp only" not in r["method"]
    assert len(calls) == 2 and {(c["tx"], c["rx"], c["wd"]) for c in calls} == {(300.0, 5.0, 4000.0)}     # glider depth, ship transducer, the env's water depth
    assert calls[0]["z"][0] == 0.0 and calls[0]["z"][-1] == -4000.0 and calls[0]["c"][-1] > calls[0]["c"][0]  # the profile reached Bellhop, to the sea floor


def test_the_acoustic_range_includes_depth(monkeypatch):
    shallow, _, t0 = bellhop_scene(monkeypatch, km=3.0, depth=5.0)
    deep, _, t1 = bellhop_scene(monkeypatch, km=3.0, depth=2500.0)
    assert t1 < t0 - 1.0 and np.nanmax(deep["margin_db"]) < np.nanmin(shallow["margin_db"])         # 2.5 km of water between the ends is path to cross


def test_without_bellhop_or_a_profile_the_ambiguous_link_keeps_the_thorp_margin_and_says_so(monkeypatch):
    r, calls, thorp = bellhop_scene(monkeypatch, available=False)
    assert not calls and np.allclose(r["margin_db"], thorp, atol=0.3) and r["method"].startswith(comms.THORP_ONLY_LABEL)
    out, _ = acoustic_scene(M=1, far=(0,))
    out["glider_eq"]["lat"][:] = km_north(4.5)
    out["glider_eq"]["depth"][:] = 300.0
    monkeypatch.setattr(comms, "bellhop_available", lambda: True)
    env = flat_env(1)
    env.env.ocean = None                                                                    # a mission with no ocean store: no sound-speed profile
    r = stage1.evaluate_link(link("glider_eq-ship-acoustic", when="always"), out, MISSION, env, 1, 3, [0])
    thorp = comms.acoustic_margin(np.hypot(4500.0, 295.0), wind=6.0)
    assert "Bellhop on 0 of" in r["method"] and "Thorp only" in r["method"] and np.allclose(r["margin_db"], thorp, atol=0.3)


def test_a_clear_acoustic_link_never_reaches_bellhop(monkeypatch):
    r, calls, thorp = bellhop_scene(monkeypatch, km=1.0, depth=5.0)
    assert not calls and abs(thorp) > 6.0 and "Bellhop" not in r["method"]


def test_where_the_environment_has_no_profile_or_depth_the_member_stays_thorp():
    env = flat_env(1)
    env.env.depth = lambda lon, lat: types.SimpleNamespace(value=np.array([np.nan]))
    assert stage1._bellhop_member(env, "benthos_atm960", "MF", -165.0, 0.0, T0, 5.0, 5.0, np.array([4500.0]), np.zeros(1), np.array([6.0])) is None
    env.env.depth = lambda lon, lat: types.SimpleNamespace(value=np.array([4000.0]))
    env.env.sound_speed = lambda lon, lat, z, t: types.SimpleNamespace(value=np.full(np.shape(z), np.nan))
    assert stage1._bellhop_member(env, "benthos_atm960", "MF", -165.0, 0.0, T0, 5.0, 5.0, np.array([4500.0]), np.zeros(1), np.array([6.0])) is None


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
    assert u["modes"] == dict(mode_a=10, mode_b=24) and u["dominant"] == "mode_b" and u["median_fail_t"] == pytest.approx(511.5)
    assert u["first_fail_t"] == 100.0                      # M-23: mode_a's members fail earlier than mode_b's 500; the first failure is over all failed members
    g = s["vehicles"]["uas"]
    assert g["k_fail"] == 0 and g["dominant"] is None and g["first_fail_t"] is None and g["median_fail_t"] is None
    assert g["sensitivity"] == dict(param=None, S1={}, noise_floor=None, case="all_pass", quantity="failure indicator",
                                    text="No member failed, so there is no failure to attribute to a parameter.")
    assert "73" in g["verdict"]["note"]                                                                              # 24 members cannot certify
    h = s["vehicles"]["glider_eq"]
    # driven by U[:, 0]
    assert 0 < h["k_fail"] < 24 and h["sensitivity"]["param"] == names[0] and set(h["sensitivity"]["S1"]) == set(stage1.FORCING) | set(stage1.ACTS["glider"])


def test_first_and_median_failure_are_over_every_failed_member_not_the_dominant_modes_members():
    """M-23: mode A in 3 members (first at 400 s), mode B in 2 others (100 s): A is dominant, the first failure is 100 s, the median over the 5 is 400 s."""
    res = merged({"usv": 0.0})
    u = res["vehicles"]["usv"]
    u["fail"] = dict(mode_a=np.arange(24) < 3, mode_b=(np.arange(24) >= 3) & (np.arange(24) < 5))
    u["first"] = dict(mode_a=np.where(np.arange(24) < 3, 400.0 + np.arange(24), np.nan), mode_b=np.where(u["fail"]["mode_b"], 100.0 + np.arange(24), np.nan))
    s = stage1.summarize(res, list(stage1.priors_for(MISSION)[1]), MISSION, 73)["vehicles"]["usv"]
    assert s["dominant"] == "mode_a" and s["k_fail"] == 5 and s["first_fail_t"] == 103.0 and s["median_fail_t"] == 400.0


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
    assert r["summary"]["vehicles"]["usv"]["verdict"]["verdict"] == "GO" and "73" in r["summary"]["vehicles"]["usv"]["verdict"]["note"]


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
    assert set(r["summary"]) == {"vehicles", "links", "subgrid_switches"}                                      # subgrid_switches: round 5, M-7
    assert set(r["summary"]["vehicles"]) == {"glider_eq", "usv", "uas"} and set(r["summary"]["links"]) == set(LK)
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


# ------------------------------------------------------------------------------------------------------- SDE, windage, stress, theta_e, link

def test_the_ocean_sde_is_on_for_the_whole_window_at_the_vehicle_step_unless_the_mission_switches_it_off(monkeypatch):
    seen, _ = spy_vehicle_models(monkeypatch)
    pri, marg = stage1.priors_for(MISSION)
    stage1.run_batch(MISSION, AnalyticEnv(), [0, 1], 11, pri, marg)
    sde = seen["usv"]["env"].sde
    assert sde.dt == stage1.DT_VEHICLE == 60.0 and sde.t0 == T0 and sde.n * sde.dt >= T1 - T0 and sde.xi.shape[0] == 2
    for env in ({"subgrid": {"ocean_sde": False}},):
        off = stage1.run_batch(dict(MISSION, environment=dict(MISSION["environment"], **env)), AnalyticEnv(), [0, 1], 11, pri, marg)
        assert seen["usv"]["env"].sde is None and off["U"].shape[0] == 2
    absent = dict(MISSION["environment"], subgrid={})                                                      # a mission that does not say: on
    stage1.run_batch(dict(MISSION, environment=absent), AnalyticEnv(), [0, 1], 11, pri, marg)
    assert seen["usv"]["env"].sde is not None


def test_gliders_get_the_brief_windage_per_member_and_the_usv_gets_none(monkeypatch):
    seen, _ = spy_vehicle_models(monkeypatch)
    pri, marg = stage1.priors_for(MISSION)
    members = [4, 5, 6, 7]
    stage1.run_batch(MISSION, AnalyticEnv(), members, 11, pri, marg)
    w = seen["glider_eq"]["windage"]
    assert np.array_equal(w, stage1.subgrid.windage_fraction(11, members)) and np.array_equal(seen["glider_1n"]["windage"], w)
    assert w.min() >= 0.018 and w.max() <= 0.023 and seen["usv"]["windage"] is None                      # the VPP carries the USV's hull windage


def test_glider_windage_reaches_the_simulator(monkeypatch):
    monkeypatch.setattr(stage1.glider, "GliderSim", FakeSim)
    v = next(x for x in MISSION["vehicles"] if x["id"] == "glider_eq")
    X = {"glider_speed_scale": np.ones(2), "battery_capacity_scale": np.ones(2)}
    P = glider.load_platform("seaglider")
    stage1._run_glider(v, P, "ENV", 2, X, 0.0, 600.0, windage=np.array([0.019, 0.022]))
    assert np.array_equal(FakeSim.last[1]["perturb"]["windage"], [0.019, 0.022])
    stage1._run_glider(v, P, "ENV", 2, X, 0.0, 600.0)
    assert "windage" not in FakeSim.last[1]["perturb"]


def test_the_bulk_stress_prior_is_sampled_only_when_a_uas_flies():
    pri, marg = stage1.priors_for(MISSION)
    assert marg["bulk_stress_scale"] == dict(dist="lognormal", median=1.0, sigma=0.30)                      # BRIEF 2.5: +-30 %
    no_uas = dict(MISSION, vehicles=[v for v in MISSION["vehicles"] if "base" not in v], links=[])
    assert "bulk_stress_scale" not in stage1.priors_for(no_uas)[1]


def test_a_members_bulk_stress_scales_its_turbulence_by_the_square_root_since_sigma_u_is_2_5_ustar(ci_full):
    P, M, origin = uas_plat(), 3, (-165.0, 0.0)
    ts = np.array([UTC("2023-03-02T01:00:00Z")])
    mission = dict(environment=dict(subgrid=dict(turbulence=True)))
    plain, _ = stage1._uas_forcing(ci_full, mission, origin, ts, P, M, 5, [0, 1, 2])
    scaled, _ = stage1._uas_forcing(ci_full, mission, origin, ts, P, M, 5, [0, 1, 2], stress_scale=np.array([1.0, 4.0, 0.25]))
    ratio = np.sqrt((scaled[0] ** 2).mean((1, 2)) / (plain[0] ** 2).mean((1, 2)))
    assert np.allclose(ratio, [1.0, 2.0, 0.5]) and np.allclose(scaled[0][0], plain[0][0])


def test_run_uas_hands_the_members_stress_to_the_forcing(monkeypatch):
    got = {}
    monkeypatch.setattr(stage1, "_uas_forcing", lambda *a, **k: got.update(a=a, k=k) or ([None], None))
    monkeypatch.setattr(stage1.uas, "fly_sortie", sortie_stub([]))
    v, P, mission, t0, T, X = uas_inputs(window=("2023-03-01T18:00:00Z", "2023-03-02T12:00:00Z"))
    X["bulk_stress_scale"] = np.array([0.8, 1.3])
    stage1._run_uas(v, P, AnalyticEnv(), 2, X, t0, T, mission, 1, [0, 1])
    assert np.array_equal(got["a"][8], [0.8, 1.3])
    del X["bulk_stress_scale"]
    stage1._run_uas(v, P, AnalyticEnv(), 2, X, t0, T, mission, 1, [0, 1])
    assert got["a"][8] is None


class Shifted:
    """ci_full with the 2 m air temperature moved by dT."""

    def __init__(self, env, dT):
        self.env, self.dT = env, dT

    def __getattr__(self, k):
        return getattr(self.env, k)

    def air(self, lon, lat, t):
        a = dict(self.env.air(lon, lat, t))
        a["T2"] = a["T2"]._replace(value=a["T2"].value + self.dT)
        return a


def gust_events(env, monkeypatch, M=300):
    """The keyword arguments gust_fronts was called with and the events it returned, for one sortie at the ship."""
    seen = []
    orig = stage1.subgrid.gust_fronts

    def spy(*a, **k):
        seen.append((k, orig(*a, **k)))
        return seen[-1][1]
    monkeypatch.setattr(stage1.subgrid, "gust_fronts", spy)
    stage1._uas_forcing(env, dict(environment=dict(subgrid=dict(gust_fronts=True))), (-165.0, 0.0), np.array([UTC("2023-03-02T01:00:00Z")]),
                        uas_plat(), M, 5, list(range(M)))
    return seen[0]


def test_gust_fronts_get_theta_e_from_the_ships_T2_Q2_and_PSFC(ci_full, monkeypatch):
    k, _ = gust_events(ci_full, monkeypatch, M=4)
    hours = np.arange(np.floor(UTC("2023-03-02T01:00:00Z") / 3600) * 3600 - 3600, UTC("2023-03-02T01:00:00Z") + 7200, 3600.0)
    a = ci_full.air(np.full(hours.size, -165.0), np.zeros(hours.size), hours)
    assert np.allclose(k["theta_e_K"], stage1.subgrid.theta_e(a["T2"].value, a["q2"].value, a["psfc"].value)) and np.all(k["theta_e_K"] > 300.0)


def test_a_higher_theta_e_gives_more_gust_fronts(ci_full, monkeypatch):
    n = {}
    for name, dT in (("cold", -20.0), ("warm", 0.0)):
        k, ev = gust_events(Shifted(ci_full, dT), monkeypatch, M=400)
        n[name] = (ev.member.size, float(np.mean(k["theta_e_K"])))
    assert n["cold"][1] < 335.0 < n["warm"][1] and n["warm"][0] > 5 * n["cold"][0] > 0                      # below theta_e_lo only the background rate is left
    lo, hi = (stage1.subgrid.gust_rate(2.0, th) for th in (330.0, 360.0))
    assert hi > lo                                                                                          # the rate factor itself


def test_the_uas_radio_is_the_platforms_with_the_antenna_terms_of_radios_yaml():
    r = stage1._uas_radio(uas_plat())
    assert r["center_mhz"] == 915.0 and r["tx_dbm"] == 30.0 and r["rx_sens_dbm"] == -121.0 and r["gt_dbi"] == 2.0 and r["misc_loss_db"] == 3.0
    other = dict(uas_plat(), radio=dict(uas_plat()["radio"], link_2g4=dict(uas_plat()["radio"]["link_2g4"], tx_power_dbm=27.0)))
    other["radio"] = {"link_2g4": other["radio"]["link_2g4"], **{k: v for k, v in other["radio"].items() if k != "rfd900x"}}
    q = stage1._uas_radio(other)                                                                            # unknown to radios.yaml: rfd900x's antennas
    assert q["center_mhz"] == pytest.approx(2441.75) and q["tx_dbm"] == 27.0 and q["gt_dbi"] == 2.0


def link_hook(M=3, hs=1.0, ship_h=15.0):
    mission = dict(MISSION, ship=dict(MISSION["ship"], antenna_height_m=ship_h))
    ts = np.array([UTC("2023-03-02T01:00:00Z")])
    return stage1._uas_links(AnalyticEnv(hs=hs), mission, (-165.0, 0.0), ts, uas_plat(), M)[0], ts[0]


def test_the_uas_link_is_lost_beyond_the_radio_horizon_and_held_while_close():
    hook, t = link_hook()
    close = np.array([[300.0, 0.0, 30.0], [0.0, 1500.0, 100.0], [-3000.0, 1000.0, 60.0]])
    far = np.array([[120e3, 0.0, 100.0], [0.0, -150e3, 50.0], [200e3, 100e3, 100.0]])
    assert not hook(t + 100.0, close).any() and hook(t + 100.0, far).all()
    mixed = np.vstack([close[:1], far[:1], close[2:]])
    assert hook(t + 100.0, mixed).tolist() == [False, True, False]
    assert hook(t + 1e5, close).shape == (3,) and not hook(t - 50.0, close).any()                          # outside the Hs grid: held at its ends


def test_the_uas_link_budget_uses_the_ships_mast_the_uas_altitude_and_the_hs_at_the_ship(monkeypatch):
    seen = []
    orig = stage1.comms.rf_margin
    monkeypatch.setattr(stage1.comms, "rf_margin", lambda *a: seen.append(a) or orig(*a))
    hook, t = link_hook(M=2, hs=2.5, ship_h=22.0)
    hook(t + 60.0, np.array([[400.0, 300.0, 40.0], [0.0, 0.0, 0.0]]))
    d, ht, hr, hs, radio = seen[0]
    P = uas_plat()
    assert np.allclose(d, [500.0, 0.0]) and np.allclose(ht, P["sortie"]["deck_height_m"] + np.array([40.0, 0.0]) + 0.1) and hr == 22.0
    assert np.allclose(hs, 2.5) and radio["tx_dbm"] == 30.0
    hook2, t2 = link_hook(M=1)
    hook2(t2, np.zeros((1, 3)))
    assert seen[1][2] == 15.0                                                                              # the mission's ship antenna (15 m)


def test_a_lost_link_sets_the_lost_link_flag_in_stage1(monkeypatch):
    def fly(env, ship, t_launch, *, M, origin, plat, turb, gust, scale, link):
        far = np.zeros((M, 3))
        far[:, 0] = 150e3
        lost = link(t_launch + 10.0, far)
        flags = {k: np.zeros(M, bool) for k in uas.FLAGS}
        flags["lost_link"] = lost
        first = {k: np.full(M, np.nan) for k in uas.FLAGS}
        t = np.arange(0.0, 601.0, 60.0)
        return dict(t_launch=t_launch, track=dict(t=t, pos_rel=np.zeros((M, t.size, 3)), phase=np.zeros((M, t.size))), flags=flags, t_first=first,
                    scrubbed=np.zeros(M, bool), launch=dict(wind_ms=np.zeros(M)), energy_wh=np.zeros(M), soc_end=np.ones(M), max_tilt_deg=np.zeros(M),
                    sat_s=np.zeros(M), demand_ratio_max=np.ones(M))
    monkeypatch.setattr(stage1.uas, "fly_sortie", fly)
    v, P, mission, t0, T, X = uas_inputs()
    r = stage1._run_uas(v, P, AnalyticEnv(), 2, X, t0, T, mission, 1, [0, 1])
    assert r["fail"]["lost_link"].all()


# ------------------------------------------------------------------------------------------------------------ M-2: the brief's USV prior as a stored sensitivit

def test_the_brief_prior_is_a_named_case_that_the_ensemble_never_samples():
    pri, marg = stage1.priors_for(MISSION)
    assert stage1.BRIEF_PRIOR in pri and stage1.BRIEF_PRIOR not in marg
    assert (marg["usv_vpp_bias"]["lo"], marg["usv_vpp_bias"]["hi"]) == (pri["usv_vpp_bias"]["lo"], pri["usv_vpp_bias"]["hi"])
    assert marg["usv_vpp_bias"]["hi"] < -0.2
    assert (pri[stage1.BRIEF_PRIOR]["lo"], pri[stage1.BRIEF_PRIOR]["hi"]) == (-0.35, -0.30)


def test_the_sensitivity_case_reruns_only_the_usv_with_the_brief_prior_and_everything_else_as_drawn(monkeypatch):
    seen = {}

    def run_batch(mission, env, members, seed, pri, marg, scales=None, X=None):
        seen.update(vehicles=[v["id"] for v in mission["vehicles"]], links=mission["links"], members=members, seed=seed, marg=marg, scales=scales)
        f = np.arange(len(members)) < 31
        return dict(U=np.zeros((len(members), 1)), X={}, links={}, vehicles={"usv": dict(
            t=np.zeros(1), lon=np.zeros((1, len(members))), lat=np.zeros((1, len(members))), depth=np.zeros((1, len(members))), fail={"becalmed": f},
            first={"becalmed": np.where(f, 1.0, np.nan)}, **{"class": "usv", "antenna_m": 1.0})})
    monkeypatch.setattr(stage1, "run_batch", run_batch)
    out = stage1.sensitivity_case(MISSION, "ENV", scales={"usv": {"drag": 1}})
    own = stage1.priors_for(MISSION)[1]
    assert seen["vehicles"] == ["usv"] and seen["links"] == [] and seen["members"] == list(range(32)) and seen["seed"] == MISSION["seed"]
    assert seen["scales"] == {"usv": {"drag": 1}}
    assert seen["marg"]["usv_vpp_bias"] == dict(dist="uniform", lo=-0.35, hi=-0.30) and {k: v for k, v in seen["marg"].items() if k != "usv_vpp_bias"} == \
        {k: v for k, v in own.items() if k != "usv_vpp_bias"}
    (c,) = out["usv"]
    assert (c["k_fail"], c["n"], c["verdict"]) == (31, 32, "NO-GO") and c["case"] == "usv_vpp_bias uniform [-0.35, -0.3] (usv_vpp_bias_brief)"
    assert c["note"].startswith("the brief's still-water factor")


def test_the_sensitivity_command_stores_the_case_where_the_report_reads_it(tmp_path, monkeypatch):
    import json
    from cafe.pm import pipeline
    monkeypatch.setattr(pipeline, "Context", lambda mission, budget, gpus, run: types.SimpleNamespace(mission=MISSION, env="ENV"))
    got = {}

    def case(mission, env, prior, n, fitted, scales):
        got.update(prior=prior, n=n, fitted=fitted, scales=scales)
        return {"usv": [dict(case="c", k_fail=1, n=n, verdict="MARGINAL", note="")]}
    monkeypatch.setattr(stage1, "sensitivity_case", case)
    (tmp_path / "stage1b").mkdir()
    old = [dict(case="c", k_fail=9, n=9, verdict="x", note=""), dict(case="other", k_fail=0, n=1, verdict="GO", note="")]
    (tmp_path / "stage1b" / "sensitivity_cases.json").write_text(json.dumps({"usv": old}))
    (tmp_path / "ingest").mkdir()
    (tmp_path / "ingest" / "priors_fitted.json").write_text(json.dumps({"p": 1}))
    (tmp_path / "refit").mkdir()
    (tmp_path / "refit" / "refit.json").write_text(json.dumps({"usv": dict(used=True, drag=3), "g": dict(used=False)}))
    assert stage1.main(["--mission", "m.yaml", "--run", str(tmp_path)]) == 0
    assert got == dict(prior=stage1.BRIEF_PRIOR, n=32, fitted={"p": 1}, scales={"usv": dict(used=True, drag=3)})
    stored = json.loads((tmp_path / "stage1b" / "sensitivity_cases.json").read_text())
    assert [c["case"] for c in stored["usv"]] == ["other", "c"] and stored["usv"][1]["k_fail"] == 1             # the same case is replaced, others kept
    assert stage1.main(["--mission", "m.yaml", "--run", str(tmp_path / "new"), "--members", "8"]) == 0
    assert got["n"] == 8 and got["fitted"] is None and got["scales"] is None


# ------------------------------------------------------------------------------------------------------------ review round 2 (batch B)

def test_usv_speed_over_ground_and_wind_along_the_track_are_stored_per_member_and_summarised(monkeypatch):
    """M-2: speed over ground, the mean 10 m and anemometer-height wind along the track, their ratios and Chiodi's calibration ratio. Review round 3,
    M-7: the speed is the displacement of the stored records (path_speed), not the simulator's path_m, which leaves out the ocean SDE's steps."""
    v = next(x for x in MISSION["vehicles"] if x["id"] == "usv")
    P = usv.load_platform("saildrone_explorer")

    class Walker(FakeSim):
        """Member 0 walks north at 0.5 m/s, member 1 at 1.0 m/s, every step recorded; path_m is deliberately wrong (the SDE-blind number)."""
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self.path_m, self.start = np.array([9e9, 9e9]), a[3]

        def run(self, duration, dt, record_s=None):
            n = int(round(duration / dt))
            lat = self.start[1] + np.degrees(np.outer(np.arange(1, n + 1) * dt, [0.5, 1.0]) / usv.R_E)
            stw = np.stack([np.linspace(0.4, 1.0, n), np.linspace(1.0, 1.6, n)], 1)                      # through the water: means 0.7 and 1.3
            return dict(t=self.t0 + dt * np.arange(1, n + 1), lon=np.full((n, 2), self.start[0]), lat=lat, stw=stw, fail=self.fail, first=self.first)
    monkeypatch.setattr(stage1.usv, "USVSim", Walker)
    r = stage1._run_usv(v, P, AnalyticEnv(wind=(-5.0, 0.0)), 2, {"usv_vpp_bias": np.zeros(2)}, 0.0, 7200.0)
    assert np.allclose(r["sog_ms"], [0.5, 1.0]) and np.allclose(r["u10_ms"], 5.0)                                  # not path_m / T (9e9 here)
    assert np.allclose(r["wind_anem_ms"], 5.0 * np.log(P["anemometer_m"] / 2e-4) / np.log(10.0 / 2e-4))
    res = stage1.merge([dict(U=np.zeros((2, 1)), X={"a": np.zeros(2)}, links={}, vehicles={"usv": dict(r, **{"class": "usv"})})] * 2)
    assert res["vehicles"]["usv"]["sog_ms"].tolist() == pytest.approx([0.5, 1.0, 0.5, 1.0])
    sp = stage1.summarize(res, ["a"], MISSION, 73)["vehicles"]["usv"]["speed"]
    assert sp["sog_ms"] == pytest.approx([0.5, 1.0, 0.5, 1.0]) and sp["ratio"] == pytest.approx([0.1, 0.2, 0.1, 0.2])
    assert sp["ratio_median"] == pytest.approx(0.15)
    assert sp["sog_ms_median"] == pytest.approx(0.75) and sp["u10_ms_median"] == 5.0 and sp["calibration_ratio"] == pytest.approx(0.96 / 5.4)
    assert sp["ratio_anem_median"] == pytest.approx(0.75 / r["wind_anem_ms"][0])
    assert r["stw_ms"] == pytest.approx([0.7, 1.3]) and sp["stw_ms"] == pytest.approx([0.7, 1.3, 0.7, 1.3])  # round 4, M-7: mean speed through the water
    assert sp["stw_ms_median"] == pytest.approx(1.0) and sp["stw_ms_median"] != pytest.approx(sp["sog_ms_median"])    # beside the speed over ground
    old = {k: v for k, v in res["vehicles"]["usv"].items() if k != "stw_ms"}
    assert "stw_ms" not in stage1.summarize(dict(res, vehicles={"usv": old}), ["a"], MISSION, 73)["vehicles"]["usv"]["speed"]       # an older run has none


def test_uas_sortie_arrays_join_along_the_members_and_the_clamp_diagnostics_are_summarised():
    """M-28: the sorties of a merged run keep every batch's members (they were the first batch's only), and the summary says how long the horizontal-force
    demand was beyond the lean-angle clamp and by how much."""
    def batch(sat, ratio, scrubbed):
        so = dict(t_launch=5.0, sat_s=np.array(sat), demand_ratio_max=np.array(ratio), scrubbed=np.array(scrubbed))
        r = dict(synth_batch([0, 1])["vehicles"]["uas"], sorties=[so])
        return dict(U=np.zeros((2, 1)), X={"a": np.zeros(2)}, links={}, vehicles={"uas": r})
    res = stage1.merge([batch([10.0, 30.0], [1.5, 2.0], [False, False]), batch([50.0, 999.0], [3.0, 9.0], [False, True])])
    (so,) = res["vehicles"]["uas"]["sorties"]
    assert so["t_launch"] == 5.0 and so["sat_s"].tolist() == [10.0, 30.0, 50.0, 999.0] and so["scrubbed"].tolist() == [False, False, False, True]
    a = stage1.summarize(res, ["a"], MISSION, 73)["vehicles"]["uas"]["authority"]
    assert a == dict(clamp_s_median=30.0, clamp_s_max=50.0, demand_ratio_median=2.0, demand_ratio_max=3.0)       # the scrubbed member never flew: left out


def test_the_fraction_of_sortie_wind_points_answered_from_the_3d_fields_is_counted_and_summed_over_batches(monkeypatch):
    """M-6: stage 1 says how much of a UAS's wind came from the 3-D fields; the gridded environment counts the points it answers."""
    env = AnalyticEnv()
    env.wind_points, env.wind3d_points = 7, 3                                         # whatever was asked before the sorties does not count
    inner = sortie_stub([])

    def fly(env_, *a, **k):
        env.wind_points += 100
        env.wind3d_points += 25
        return dict(inner(env_, *a, **k), sat_s=np.zeros(2), demand_ratio_max=np.ones(2))
    monkeypatch.setattr(stage1.uas, "fly_sortie", fly)
    v, P, mission, t0, T, X = uas_inputs(window=("2023-03-01T18:00:00Z", "2023-03-03T06:00:00Z"))
    r = stage1._run_uas(v, P, env, 2, X, t0, T, mission, 1, [0, 1])
    assert r["wind3d"] == (50, 200)                                                     # two sorties
    none = stage1._run_uas(v, P, AnalyticEnv(), 2, X, t0, T, mission, 1, [0, 1])
    assert none["wind3d"] is None                                                       # an environment without 3-D fields does not count
    res = stage1.merge([dict(U=np.zeros((2, 1)), X={"a": np.zeros(2)}, links={}, vehicles={"uas": dict(r, **{"class": "uas"})})] * 2)
    assert res["vehicles"]["uas"]["wind3d"] == (100, 400)
    assert stage1.summarize(res, ["a"], MISSION, 73)["vehicles"]["uas"]["wind3d_fraction"] == 0.25
    plain = stage1.merge([dict(U=np.zeros((2, 1)), X={"a": np.zeros(2)}, links={}, vehicles={"uas": dict(none, **{"class": "uas"})})])
    assert "wind3d_fraction" not in stage1.summarize(plain, ["a"], MISSION, 73)["vehicles"]["uas"]


def surfacing_scene(M=2):
    out, surf = acoustic_scene(M=M, far=(0,) * M)
    out["usv"] = track(-165.0, 0.0, M, antenna=2.2)                                    # a USV that is always on the surface
    out["glider_eq"]["lat"][:] = km_north(2.0)
    return out, surf


def test_a_surfacing_link_follows_the_glider_end_whichever_end_names_it_first():
    """M-10: `a: usv, b: glider_eq, when: surfacing` was required at every record (the USV is always surfaced); with the glider first it was 60."""
    out, surf = surfacing_scene()
    lk = dict(LK["glider_eq-ship-acoustic"], b="usv")
    first = stage1.evaluate_link(dict(lk, a="glider_eq"), out, MISSION, flat_env(2), 2, 3, [0, 1])
    second = stage1.evaluate_link(dict(lk, a="usv", b="glider_eq"), out, MISSION, flat_env(2), 2, 3, [0, 1])
    assert first["need_count"].tolist() == second["need_count"].tolist() == [int(surf.sum())] * 2
    assert np.array_equal(first["success"], second["success"]) and np.allclose(first["margin_db"], second["margin_db"], equal_nan=True)


def test_moments_before_a_vehicles_deploy_time_are_not_required():
    """M-22: record grids start at the vehicle's own deploy time and the link grid at the window's; the clamped first value counted as needed."""
    k = 48                                                                              # deployed 8 h after the window opens
    out, _ = surfacing_scene(M=1)
    cut = {key: out["usv"][key][k:] for key in ("lon", "lat", "depth", "surfaced")}
    late = {"usv": dict(out["usv"], t=TGRID[k:], **cut)}
    assert stage1.evaluate_link(LK["usv-shore-iridium"], late, MISSION, flat_env(1), 1, 3, [0])["need_count"].tolist() == [TGRID.size - k]
    assert stage1.evaluate_link(LK["usv-shore-iridium"], out, MISSION, flat_env(1), 1, 3, [0])["need_count"].tolist() == [TGRID.size]
    always = dict(LK["glider_eq-ship-acoustic"], a="usv", b="ship", when="always")
    assert stage1.evaluate_link(always, late, MISSION, flat_env(1), 1, 3, [0])["need_count"].tolist() == [TGRID.size - k]
    assert stage1.evaluate_link(always, out, MISSION, flat_env(1), 1, 3, [0])["need_count"].tolist() == [TGRID.size]


def test_acoustic_wind_noise_uses_the_members_perturbed_wind():
    """M-20: the noise term read the unperturbed wind; a member whose wind error is +14 m/s must be as noisy as a 20 m/s day."""
    out, _ = acoustic_scene(M=2, far=(0, 0))
    for m in (0, 1):
        out["glider_eq"]["lat"][:, m] = km_north(4.0)
    base = AnalyticEnv(hs=1.0)
    base.u10 = lambda lon, lat, t: np.stack([np.full(np.shape(t), 6.0), np.zeros(np.shape(t))], -1)
    base.wind = lambda lon, lat, z, t: Tagged(np.asarray(base.u10(lon, lat, t), float), "flat", 0.0, "assumed")
    pen = PerturbedEnv(base, {"wind_speed_bias": np.array([0.0, 14.0])}, [0, 1], 3, stage1.priors_for(MISSION)[0])
    lk = LK["glider_eq-ship-acoustic"]
    r = stage1.evaluate_link(lk, out, MISSION, pen, 2, 3, [0, 1])
    gale = stage1.evaluate_link(lk, out, MISSION, flat_env(2, wind=20.0), 2, 3, [0, 1])
    calm = stage1.evaluate_link(lk, out, MISSION, flat_env(2, wind=6.0), 2, 3, [0, 1])
    assert np.allclose(r["margin_db"][:, 0], calm["margin_db"][:, 0], equal_nan=True)
    assert np.allclose(r["margin_db"][:, 1], gale["margin_db"][:, 1], equal_nan=True)
    assert np.nanmax(r["margin_db"][:, 1]) < np.nanmin(r["margin_db"][:, 0])


def test_a_link_reports_the_median_distance_of_its_needed_moments():
    """M-18: the summary holds the distance the link was judged at, so a sanity row can say 'beyond 3 km'."""
    out, surf = acoustic_scene(M=3, far=(0, 0, 40))
    r = stage1.evaluate_link(LK["glider_eq-ship-acoustic"], out, MISSION, flat_env(3), 3, 3, [0, 1, 2])
    assert r["dist_m"] == pytest.approx([2000.0, 2000.0, 60e3], rel=0.01)                      # member 2: 40 of 60 needed moments at 60 km, 20 at 2 km
    assert np.isnan(stage1.evaluate_link(LK["usv-shore-iridium"], {"usv": track(-165.0, 0.0, 3)}, MISSION, flat_env(3), 3, 3, [0, 1, 2])["dist_m"]).all()
    res = stage1.merge([dict(U=np.zeros((3, 1)), X={"a": np.zeros(3)}, vehicles={}, links={"glider_eq-ship-acoustic": r})])
    km = stage1.summarize(res, ["a"], MISSION, 73)["links"]["glider_eq-ship-acoustic"]["distance_km_median"]
    assert km == pytest.approx(np.nanmedian(r["dist_m"]) / 1e3)
    no = stage1.evaluate_link(LK["usv-shore-iridium"], {"usv": track(-165.0, 0.0, 3)}, MISSION, flat_env(3), 3, 3, [0, 1, 2])
    res = stage1.merge([dict(U=np.zeros((3, 1)), X={"a": np.zeros(3)}, vehicles={}, links={"usv-shore-iridium": no})])
    assert stage1.summarize(res, ["a"], MISSION, 73)["links"]["usv-shore-iridium"]["distance_km_median"] is None


class Box:
    """An environment with a box: positions east of -165.5 are outside it. Lenient or not, `inside` says which."""
    bounds = AnalyticEnv().bounds

    def inside(self, lon, lat, t=None):
        return np.asarray(lon) < -165.5


def test_a_record_outside_the_environments_box_is_the_fail_mode_left_data_at_that_record():
    """M-11: a member that drifts out of the cached data failed the whole batch with OutsideData; it is now a failed member with the time it left."""
    t = np.arange(5) * 600.0
    lon = np.full((5, 3), -166.0)
    lon[2:, 1] = -165.0                                                                   # member 1 leaves at the third record and stays out
    lon[4, 2] = -165.0                                                                    # member 2 is out at the last one only
    r = dict(t=t, lon=lon, lat=np.zeros((5, 3)), fail={"becalmed": np.zeros(3, bool)}, first={"becalmed": np.full(3, np.nan)})
    stage1._left_data(r, Box())
    assert r["fail"]["left_data"].tolist() == [False, True, True] and r["first"]["left_data"][1:].tolist() == [1200.0, 2400.0]
    assert np.isnan(r["first"]["left_data"][0])
    assert r["fail"]["becalmed"].tolist() == [False] * 3 and stage1.failed(r).tolist() == [False, True, True]
    nan = dict(t=t, lon=np.where(lon > -165.9, np.nan, lon), lat=np.zeros((5, 3)), fail={}, first={})
    stage1._left_data(nan, Box())
    assert not nan["fail"]["left_data"].any()                                           # an unknown position is not a position outside the box
    plain = dict(t=t, lon=lon, lat=np.zeros((5, 3)), fail={}, first={})
    stage1._left_data(plain, AnalyticEnv())
    assert plain["fail"] == {}                                                           # an environment without a box has no mode to add


def test_run_batch_flags_left_data_for_every_vehicle_and_returns_the_stream_seeds(monkeypatch):
    """M-11 and M-12 through run_batch: the mode is on every vehicle's result, and `seeds[vehicle][stream]` holds the seeds the run drew."""
    spy_vehicle_models(monkeypatch)

    def link(lk, out, mission, env, M, seed, members, used=None):
        used["iridium/x"] = 5
        return dict(id=lk["id"])
    monkeypatch.setattr(stage1, "evaluate_link", link)
    pri, marg = stage1.priors_for(MISSION)
    env = AnalyticEnv()
    env.inside = lambda lon, lat, t=None: np.zeros(np.shape(lon), bool)
    b = stage1.run_batch(MISSION, env, [4, 5, 6, 7], 11, pri, marg)
    assert all(v["fail"]["left_data"].all() and v["first"]["left_data"].tolist() == [0.0] * 4 for v in b["vehicles"].values())
    assert set(b["seeds"]) == set(b["vehicles"]) and all(s == {"iridium/x": 5} for s in b["seeds"].values())
    one = synth_batch([0, 1, 2, 3])
    two = stage1.merge([dict(one, seeds={v: {"iridium/x": 5} for v in one["vehicles"]}), dict(one, seeds={v: {"iridium/x": 6} for v in one["vehicles"]})])
    assert set(two["seeds"]) == set(one["vehicles"]) and all(s == {"iridium/x": [5, 6]} for s in two["seeds"].values())
    assert "seeds" not in stage1.merge([one])


def test_the_stream_seeds_are_the_ones_the_forcing_and_the_iridium_link_drew(ci_full):
    """M-12: `used` collects {stream: seed} where the seeds are made: UAS turbulence per sortie, the gust set, the Iridium sessions."""
    P, M, origin = uas_plat(), 2, (-165.0, 0.0)
    ts = np.array([UTC("2023-03-02T01:00:00Z"), UTC("2023-03-03T01:00:00Z")])
    used = {}
    stage1._uas_forcing(ci_full, dict(environment=dict(subgrid=dict(turbulence=True, gust_fronts=True))), origin, ts, P, M, 5, [4, 5], used=used)
    assert used == {name: sampling.member_seed(5, 4, name) for name in ("uas/turb/0", "uas/turb/1", "uas/gust")}
    used = {}
    stage1.evaluate_link(LK["usv-shore-iridium"], {"usv": track(-165.0, -1.0, 2)}, MISSION, flat_env(2), 2, 7, [4, 5], used)
    assert used == {"iridium/usv-shore-iridium": sampling.member_seed(7, 4, "iridium/usv-shore-iridium")}


def test_a_given_hypercube_replaces_the_lhs_draw_and_its_uniforms_are_the_quantiles(monkeypatch):
    """M-15: run_batch(X=...) runs the columns it is given."""
    spy_vehicle_models(monkeypatch)
    pri, marg = stage1.priors_for(MISSION)
    _, X = sampling.lhs(4, marg, np.random.SeedSequence([11, 4]))
    b = stage1.run_batch(MISSION, AnalyticEnv(), [4, 5, 6, 7], 11, pri, marg, None, X)
    assert all(np.array_equal(b["X"][k], X[k]) for k in marg) and b["U"].shape == (4, len(marg))
    assert np.allclose(b["U"], sampling.lhs(4, marg, np.random.SeedSequence([11, 4]))[0])
    with pytest.raises(ValueError, match="must hold 3 values"):
        stage1.run_batch(MISSION, AnalyticEnv(), [4, 5, 6], 11, pri, marg, None, X)


def test_the_sensitivity_case_given_the_runs_hypercube_changes_only_the_vpp_bias_at_the_same_quantile(monkeypatch):
    """M-15: the case was a different n = 32 sample from the verdict beside it; with the run's own X it is paired."""
    seen = {}

    def run_batch(mission, env, members, seed, pri, marg, scales=None, X=None):
        seen.update(members=members, X=X, marg=marg)
        f = np.zeros(len(members), bool)
        return dict(U=np.zeros((len(members), 1)), X={}, links={}, vehicles={"usv": dict(
            t=np.zeros(1), lon=np.zeros((1, len(members))), lat=np.zeros((1, len(members))), depth=np.zeros((1, len(members))), fail={"becalmed": f},
            first={"becalmed": np.full(len(members), np.nan)}, **{"class": "usv", "antenna_m": 1.0})})
    monkeypatch.setattr(stage1, "run_batch", run_batch)
    pri, marg = stage1.priors_for(MISSION)
    _, X = sampling.lhs(16, marg, np.random.SeedSequence([MISSION["seed"], 0]))
    out = stage1.sensitivity_case(MISSION, "ENV", n=99, X=dict(X, extra=np.zeros(16)))
    assert seen["members"] == list(range(16)) and out["usv"][0]["n"] == 16 and set(seen["X"]) == set(marg)
    assert all(np.array_equal(seen["X"][k], X[k]) for k in marg if k != "usv_vpp_bias")
    lo, hi = marg["usv_vpp_bias"]["lo"], marg["usv_vpp_bias"]["hi"]
    q = (X["usv_vpp_bias"] - lo) / (hi - lo)
    assert np.allclose(seen["X"]["usv_vpp_bias"], -0.35 + 0.05 * q) and seen["X"]["usv_vpp_bias"].min() >= -0.35 and seen["X"]["usv_vpp_bias"].max() <= -0.30
    assert seen["marg"]["usv_vpp_bias"] == dict(dist="uniform", lo=-0.35, hi=-0.30)


@pytest.mark.parametrize("every, first_day", [(2, "2023-03-02"), (3, "2023-03-02"), (1.5, "2023-03-02")])
def test_a_period_over_one_day_starts_at_the_first_daily_slot_not_where_the_epoch_puts_it(every, first_day):
    """M-24: every_days: 2 first launched on 03-03 (skipping the 03-02 slot) because the phase came from the epoch day."""
    t0, t1 = UTC("2023-03-01T12:00:00Z"), UTC("2023-03-12T12:00:00Z")
    ts = stage1.launch_times({"local_solar_time": "14:00", "every_days": every}, -165.0, t0, t1, 1920.0)
    assert ts[0] == UTC(f"{first_day}T01:00:00Z") and np.allclose(np.diff(ts), 86400.0 * every)


# ------------------------------------------------------------------------------------------------------------ review round 3 (batch S)

def test_a_drift_glider_swims_on_the_heading_of_its_task():
    """M-1: _run_glider never passed the task's heading_to, so every drift glider swam due north."""
    from tests.test_glider import env as strat_env
    P = glider.load_platform("slocum")
    X = {"glider_speed_scale": np.ones(2), "battery_capacity_scale": np.ones(2)}

    def go(heading):
        v = dict(id="g", platform="slocum", deploy=dict(time="2023-03-01T18:00:00Z", lon=-165.0, lat=1.0),
                 task=dict(mode="drift", heading_to=heading, dive_depth_m=200.0))
        return stage1._run_glider(v, P, strat_env(), 2, X, 0.0, 4 * 3600.0)
    east, north = go(90.0), go(0.0)
    de = np.median(east["lon"][-1] + 165.0) * 111.195 * np.cos(np.radians(1.0))
    dn = np.median(north["lat"][-1] - 1.0) * 111.195
    assert de > 1.0 and abs(np.median(east["lat"][-1] - 1.0) * 111.195) < 0.2 * de                      # east: kilometres of longitude, hardly any latitude
    assert dn > 1.0 and abs(np.median(north["lon"][-1] + 165.0) * 111.195) < 0.2 * dn


def test_a_usv_station_task_runs_and_is_swept_off_at_its_radius():
    """M-3 (1): a USV `task.mode: station` died in USVSim with KeyError 'station'; radius_km is the swept-off-track distance."""
    def go(radius):
        v = dict(id="u", platform="saildrone_explorer", deploy=dict(time="2023-03-01T18:00:00Z", lon=-165.0, lat=0.0),
                 task=dict(mode="station", lon=-165.0, lat=0.0, radius_km=radius))
        env = AnalyticEnv(wind=(-0.2, 0.0), current=(0.9, 0.0), hs=0.5)                                  # SPURS-2: a light wind against a strong current
        return stage1._run_usv(v, usv.load_platform("saildrone_explorer"), env, 4, {"usv_vpp_bias": np.full(4, -0.24)}, 0.0, 6 * 3600.0)
    tight, wide = go(1.0), go(100.0)
    assert tight["fail"]["swept_off_track"].all() and not wide["fail"]["swept_off_track"].any()
    assert wide["margin_name"] == "maximum distance from the station" and 10.0 < wide["margin"].min() and wide["margin"].max() < 25.0  # 0.9 m/s for 6 h = 19 km
    assert tight["first"]["swept_off_track"].max() < 3 * 3600.0


def test_a_run_too_short_for_a_step_has_one_record_the_deploy_state():
    """M-18: T - t0 = 30 s runs no step; the empty 1-D history crashed the concatenation (ValueError: arrays must have the same number of dimensions)."""
    from tests.test_glider import env as strat_env
    t0 = UTC("2023-03-01T18:00:00Z")
    v = next(x for x in MISSION["vehicles"] if x["id"] == "glider_eq")
    gx = {"glider_speed_scale": np.ones(2), "battery_capacity_scale": np.ones(2)}
    rg = stage1._run_glider(v, glider.load_platform("seaglider"), strat_env(), 2, gx, t0, t0 + 30.0)
    u = next(x for x in MISSION["vehicles"] if x["id"] == "usv")
    ru = stage1._run_usv(u, usv.load_platform("saildrone_explorer"), AnalyticEnv(wind=(-5.0, 0.0)), 2, {"usv_vpp_bias": np.full(2, -0.24)}, t0, t0 + 30.0)
    for r, d in ((rg, v["deploy"]), (ru, u["deploy"])):
        assert r["t"].tolist() == [t0] and r["lon"].shape == r["lat"].shape == r["depth"].shape == r["surfaced"].shape == (1, 2)
        assert np.all(r["lon"] == d["lon"]) and np.all(r["lat"] == d["lat"]) and r["surfaced"].all() and not any(x.any() for x in r["fail"].values())
    assert np.isnan(ru["sog_ms"]).all() and np.isnan(ru["stw_ms"]).all()                                  # no segment, no speed


def test_path_speed_is_the_sum_of_the_segments_over_the_time_they_span():
    """M-7: one definition of speed over ground: member 0 walks north, 1 zigzags (the path counts, the displacement does not), 2 has a lost record,
    3 crosses the dateline, 4 never moves."""
    k = np.radians(1.0) * usv.R_E / 600.0                                                               # m/s for 1 degree of latitude per 600 s record
    lat = np.zeros((5, 5))
    lat[:, 0] = 0.01 * np.arange(5)
    lat[:, 1] = 0.01 * (np.arange(5) % 2)
    lat[:, 2] = 0.01 * np.arange(5)
    lon = np.zeros((5, 5))
    lon[:, 3] = 179.98 + 0.01 * np.arange(5)
    lon[:, 3] = (lon[:, 3] + 180.0) % 360.0 - 180.0
    lat[2, 2] = np.nan
    v = stage1.path_speed(lon, lat, 600.0 * np.arange(5))
    assert v[:2] == pytest.approx([0.01 * k] * 2) and v[2] == pytest.approx(0.01 * k) and v[3] == pytest.approx(0.01 * k) and v[4] == 0.0
    assert np.isnan(stage1.path_speed(lon[:1], lat[:1], np.zeros(1))).all()                             # one record: no segment, no speed
    assert stage1.path_speed(lon, lat, 600.0 * np.arange(5)).shape == (5,)


def test_the_calibration_run_measures_speed_the_way_the_mission_does(monkeypatch):
    """M-7: usv.mean_sog read path_m (blind to the ocean SDE's steps, which the stored records contain); it now takes path_speed of the 10-min records."""
    from cafe.pm.env import protocol

    class Stirred(AnalyticEnv):
        def sde_displacement(self, lon, lat, t):
            return np.tile([100.0, 0.0], (np.size(lon), 1))  # 100 m east per step, on top of the ~120 m the boat sails

    plain = usv.mean_sog(P_USV, 5.4, hours=3.0, nb=8)
    monkeypatch.setattr(protocol, "AnalyticEnv", Stirred)
    assert usv.mean_sog(P_USV, 5.4, hours=3.0, nb=8) > 1.08 * plain


def acting_names(cls="glider"):
    return [n for n in stage1.priors_for(MISSION)[1] if n in set(stage1.FORCING) | set(stage1.ACTS[cls])]


def draw(n=32, seed=0):
    names = list(stage1.priors_for(MISSION)[1])
    return names, np.random.default_rng(seed).random((n, len(names)))


@pytest.mark.parametrize("k", [1, 2, 3])
def test_a_parameter_that_drives_the_margin_is_found_whatever_few_members_failed(k):
    """M-2: EASI on the 0/1 failure indicator saturated at its own permutation floor for 3 failures or fewer (a perfectly known driver was not
    detected: 0, 0 and 16 of 20 draws at k = 1, 2, 3); on the continuous margin the driver is found in at least 18 of 20."""
    hit = 0
    for seed in range(20):
        names, U = draw(32, seed)
        margin = U[:, names.index("battery_capacity_scale")] + 0.02 * np.random.default_rng(100 + seed).standard_normal(32)
        f = np.argsort(margin)[:k]
        e = stage1._sensitivity(names, U, np.isin(np.arange(32), f), set(names), margin, "battery energy margin")
        hit += e["param"] == "battery_capacity_scale"
    assert hit >= 18


def test_sensitivity_says_which_of_five_cases_applies_and_what_was_ranked():
    names, U = draw(32, 3)
    j = names.index("hs_scale")
    margin = U[:, j]
    act = set(names)
    e = stage1._sensitivity(names, U, U[:, j] < 0.3, act, margin, "maximum cross-track error")
    assert (e["case"], e["param"], e["quantity"]) == ("ranked", "hs_scale", "maximum cross-track error")
    assert e["text"].startswith("hs_scale has the largest first-order index (S1 ") and "maximum cross-track error" in e["text"]
    assert e["text"].endswith("member count.")
    assert e["noise_floor"] > 0 and e["S1"]["hs_scale"] > e["noise_floor"]
    # nothing clears the floor: an unrelated margin
    e = stage1._sensitivity(names, U, U[:, 0] < 0.3, act, np.random.default_rng(1).random(32), "battery energy margin")
    assert (e["case"], e["param"]) == ("nothing_above_floor", None) and "No parameter clears the noise floor for the battery energy margin" in e["text"]
    assert e["S1"] and "not the same as none mattering" in e["text"]
    # no failure / no success / too few members
    assert stage1._sensitivity(names, U, np.zeros(32, bool), act, margin, "q")["case"] == "all_pass"
    e = stage1._sensitivity(names, U, np.ones(32, bool), act, margin, "q")
    assert e["case"] == "all_fail" and e["param"] is None and e["S1"] == {} and e["noise_floor"] is None and e["text"].startswith("Every member failed")
    e = stage1._sensitivity(names, U[:8], np.arange(8) < 3, act, None, "q")
    assert e["case"] == "too_few" and "Only 8 members" in e["text"] and "16" in e["text"]


def test_with_no_margin_the_indicator_is_ranked_and_three_failures_or_fewer_give_the_hypercube_ranks():
    """M-2: the indicator is the fallback; with fewer than 3 failures (or successes) the entry says so and prints the ranks of the minority
    members for the three most extreme parameters instead of 'no parameter clears the floor'."""
    names, U = draw(32, 5)
    j = names.index("battery_capacity_scale")
    low = np.argsort(U[:, j])[:2]
    e = stage1._sensitivity(names, U, np.isin(np.arange(32), low), set(names), None, "battery reserve margin")
    assert e["case"] == "too_few" and e["quantity"] == "failure indicator" and e["param"] is None and e["S1"] == {}
    assert e["text"].startswith("Only 2 of 32 members failed, too few to rank the parameters; "
                                "their ranks among the 32 draws (0 is the lowest value) are battery_capacity_scale 0, 1;")
    survivors = stage1._sensitivity(names, U, ~np.isin(np.arange(32), low), set(names), None, "x")
    assert survivors["case"] == "too_few" and survivors["text"].startswith("Only 2 of 32 members passed")
    f = U[:, j] < 0.25
    e = stage1._sensitivity(names, U, f, set(names), None, "x")
    assert e["case"] == "ranked" and e["param"] == "battery_capacity_scale" and e["quantity"] == "failure indicator"
    margin = np.where(np.arange(32) < 12, np.nan, U[:, j])                                  # members without a margin (no flown sortie) leave the ranking
    e = stage1._sensitivity(names, U, f, set(names), margin, "battery reserve margin")
    assert e["case"] == "ranked" and e["quantity"] == "battery reserve margin"
    e = stage1._sensitivity(names, U, f, set(names), np.where(np.arange(32) < 20, np.nan, 1.0), "battery reserve margin")  # 12 finite: too few for an index
    assert e["quantity"] == "failure indicator"


def test_a_column_that_cannot_act_on_the_class_is_not_ranked_and_does_not_set_the_floor():
    """M-2: glider_speed_scale cannot act on a UAS (its S1 was equal to the real driver's and to the floor); the indices come from the acting columns only."""
    names, U = draw(32, 7)
    margin = U[:, names.index("battery_capacity_scale")]
    f = margin < 0.2
    uas_e = stage1._sensitivity(names, U, f, set(stage1.FORCING) | set(stage1.ACTS["uas"]), margin, "battery reserve margin")
    assert set(uas_e["S1"]) == set(stage1.FORCING) | set(stage1.ACTS["uas"]) and "glider_speed_scale" not in uas_e["S1"] and "usv_vpp_bias" not in uas_e["S1"]
    assert set(stage1.ACTS) == {"glider", "usv", "uas"} and "battery_capacity_scale" not in stage1.ACTS["usv"]
    wide = stage1._sensitivity(names, U, f, set(names), margin, "x")
    assert wide["noise_floor"] >= uas_e["noise_floor"]                                                   # more columns, no lower family-wise floor


def test_the_summary_ranks_the_margin_the_simulator_stored_and_only_the_columns_of_the_class():
    names = list(stage1.priors_for(MISSION)[1])
    res = merged({"glider_eq": 0.25, "usv": 0.25}, {"usv-uas-rf": 0.25, "glider_eq-ship-acoustic": 0.25})
    for vid, q in (("glider_eq", "maximum distance from the station"), ("usv", "maximum cross-track error")):
        r = res["vehicles"][vid]
        r["margin"], r["margin_name"] = -res["U"][:, 0].copy(), q
    s = stage1.summarize(res, names, MISSION, 73)
    g, u = s["vehicles"]["glider_eq"]["sensitivity"], s["vehicles"]["usv"]["sensitivity"]
    assert g["quantity"] == "maximum distance from the station" and g["param"] == names[0] and "usv_vpp_bias" not in g["S1"] and "glider_speed_scale" in g["S1"]
    assert u["quantity"] == "maximum cross-track error" and "glider_speed_scale" not in u["S1"] and "usv_vpp_bias" in u["S1"]
    assert "battery_capacity_scale" not in u["S1"]
    assert s["vehicles"]["uas"]["sensitivity"]["case"] == "all_pass" and s["vehicles"]["uas"]["sensitivity"]["quantity"] == "failure indicator"
    rf = s["links"]["usv-uas-rf"]["sensitivity"]                                                         # the ends are a USV and a UAS
    assert rf["quantity"] == "fraction of the required moments the link worked" and rf["param"] == names[0]
    assert {"usv_vpp_bias", "bulk_stress_scale", "battery_capacity_scale"} <= set(rf["S1"]) and "glider_speed_scale" not in rf["S1"]
    ac = s["links"]["glider_eq-ship-acoustic"]["sensitivity"]                                           # a glider and the ship
    assert "glider_speed_scale" in ac["S1"] and "usv_vpp_bias" not in ac["S1"] and "bulk_stress_scale" not in ac["S1"]
    assert s["links"]["usv-shore-iridium"]["sensitivity"]["case"] == "all_pass"


def test_margins_and_the_30_s_sortie_grid_join_along_the_members():
    a, b = synth_batch(list(range(0, 8))), synth_batch(list(range(8, 16)))
    for batch in (a, b):
        r = batch["vehicles"]["uas"]
        r["margin"], r["margin_name"] = np.arange(8.0), "battery reserve margin"
        r["fine"] = dict(t=np.arange(3.0), lon=np.zeros((3, 8)), lat=np.ones((3, 8)), alt=np.zeros((3, 8)), depth=np.zeros((3, 8)),
                         airborne=np.ones((3, 8), bool))
    r = stage1.merge([a, b])["vehicles"]["uas"]
    assert r["margin"].shape == (16,) and r["margin_name"] == "battery reserve margin" and "margin" not in stage1.merge([a, b])["vehicles"]["usv"]
    assert r["fine"]["t"].tolist() == [0.0, 1.0, 2.0] and all(r["fine"][k].shape == (3, 16) for k in ("lon", "lat", "alt", "depth", "airborne"))


def test_the_sorties_are_also_kept_on_a_30_s_grid_over_each_launch_window_and_the_margin_is_the_lowest_charge_over_the_reserve(monkeypatch):
    """M-5 / M-2: a 20 min sortie is only 1 to 2 of the 10 min records; `fine` holds the same sortie every 30 s for the links to be judged on."""
    calls = []
    monkeypatch.setattr(stage1.uas, "fly_sortie", sortie_stub(calls))
    v, P, mission, t0, T, X = uas_inputs(window=("2023-03-01T18:00:00Z", "2023-03-03T06:00:00Z"))
    r = stage1._run_uas(v, P, AnalyticEnv(), 2, X, t0, T, mission, 1, [0, 1])
    dur = 60.0 * v["sorties"]["duration_min"] * P["sortie"]["hard_stop_factor"]
    f = r["fine"]
    want = np.concatenate([UTC(x) + np.arange(0.0, dur + 1.0, stage1.FINE_S) for x in ("2023-03-02T01:00:00Z", "2023-03-03T01:00:00Z")])
    assert f["t"].tolist() == want.tolist() and f["lon"].shape == f["airborne"].shape == (want.size, 2)
    k = int(np.flatnonzero(f["t"] == UTC("2023-03-02T01:00:00Z") + 600.0)[0])
    nw = want.size // 2                                                                                  # samples per launch window (hard_stop_factor x 20 min)
    assert f["airborne"][:41, 0].all() and not f["airborne"][41:nw, 0].any() and f["airborne"][nw:nw + 41, 0].all()  # the stub flies 1200 s: 41 samples of 30 s
    assert np.allclose(f["alt"][k, 0], 25.0 + P["sortie"]["deck_height_m"]) and f["lon"][k, 0] > f["lon"][0, 0]
    assert r["airborne"].sum(0)[0] == 2 * 3 and r["margin_name"] == "battery reserve margin"             # the 10-min records are as before: 3 per sortie
    reserve = P["battery"]["reserve_frac"]
    assert r["margin"].tolist() == pytest.approx([0.5 - reserve, 0.6 - reserve])  # member 1 is scrubbed on the second sortie: its first counts
    v, P, mission, t0, T, X = uas_inputs(window=("2023-03-01T18:00:00Z", "2023-03-01T19:00:00Z"))
    none = stage1._run_uas(v, P, AnalyticEnv(), 2, X, t0, T, mission, 1, [0, 1])
    assert none["fine"] is None and np.isnan(none["margin"]).all()


def test_a_sortie_failure_time_is_epoch_seconds_in_double_precision(monkeypatch):
    """M-6: float32 epoch seconds are 128 s apart (the q3 report printed one instant for the first and the median failure)."""
    base = sortie_stub([])

    def fly(*a, **k):
        r = base(*a, **k)
        r["t_first"] = {n: x.astype(np.float32) for n, x in r["t_first"].items()}
        return r
    monkeypatch.setattr(stage1.uas, "fly_sortie", fly)
    v, P, mission, t0, T, X = uas_inputs()
    r = stage1._run_uas(v, P, AnalyticEnv(), 2, X, t0, T, mission, 1, [0, 1])
    t_launch = UTC("2023-03-02T01:00:00Z")
    got = r["first"]["attitude_exceedance"]
    # (a float32 compares equal to the rounded sum, hence the dtype and float())
    assert t_launch % 128 != 0 and got.dtype == np.float64 and float(got[1]) == t_launch + 300.0


def test_a_uas_link_is_judged_every_30_s_in_flight_so_one_bad_sample_passes_at_95_percent():
    """M-5: 6 to 12 samples per member made 0.95 mean 'every sample'; a 20 min sortie on the 30 s grid is 41 samples and one lost sample (2.4 %) is allowed."""
    out, _ = rf_scene(M=2, bad_samples=(0, 0))
    tf = T0 + 6 * 3600.0 + np.arange(0.0, 1201.0, 30.0)
    lat = np.zeros((tf.size, 2))
    lat[10, 1] = km_north(100.0)  # member 1: the UAS is beyond the horizon at one sample only
    zero = np.zeros_like(lat)
    out["uas"]["fine"] = dict(t=tf, lon=zero - 165.0, lat=lat, alt=zero + 40.0, depth=zero, airborne=np.ones(lat.shape, bool))
    r = stage1.evaluate_link(LK["usv-uas-rf"], out, MISSION, flat_env(2), 2, 3, [0, 1])
    assert r["need_count"].tolist() == [41, 41] and r["t"].size == TGRID.size + 41 - 3  # the sortie's 3 samples on the 10 min grid are the same instants
    assert r["frac"].tolist() == [1.0, 40 / 41] and r["success"].tolist() == [True, True] and r["n_invalid"].tolist() == [0, 1]
    two = {**out, "uas": dict(out["uas"], fine=dict(out["uas"]["fine"], lat=lat + np.where(np.arange(tf.size) % 5 == 0, km_north(100.0), 0.0)[:, None]))}
    assert not stage1.evaluate_link(LK["usv-uas-rf"], two, MISSION, flat_env(2), 2, 3, [0, 1])["success"].any()


def test_the_link_summary_gives_the_required_samples_and_whether_the_fraction_can_be_resolved_on_them():
    """M-5: need_count_median (int) and granularity_ok = 1 / need_count_median <= 1 - required_fraction; a link needed at no sample is not decided either."""
    names = list(stage1.priors_for(MISSION)[1])
    rf = LK["usv-uas-rf"]["required_fraction"]
    assert rf == 0.95
    res = merged({}, {})
    out = {}
    for n, rfrac in ((9, None), (20, None), (21, None), (0, None), (20, 1.0)):
        res["links"]["usv-uas-rf"]["need_count"] = np.full(24, n)
        m = MISSION if rfrac is None else dict(MISSION, links=[dict(lk, required_fraction=rfrac) if lk["id"] == "usv-uas-rf" else lk
                                                               for lk in MISSION["links"]])
        out[(n, rfrac)] = stage1.summarize(res, names, m, 73)["links"]["usv-uas-rf"]
    assert [(e["need_count_median"], e["granularity_ok"]) for e in out.values()] == [(9, False), (20, True), (21, True), (0, False), (20, True)]
    assert isinstance(out[(9, None)]["need_count_median"], int) and out[(9, None)]["granularity_ok"] is False
    odd = merged({}, {})
    odd["links"]["usv-uas-rf"]["need_count"] = np.arange(24) % 2 * 10 + 10                                # median 15: 1/15 > 0.05
    assert stage1.summarize(odd, names, MISSION, 73)["links"]["usv-uas-rf"]["need_count_median"] == 15
    assert stage1.summarize(odd, names, MISSION, 73)["links"]["usv-uas-rf"]["granularity_ok"] is False
    assert stage1.summarize(merged({}, {}), names, MISSION, 73)["links"]["usv-uas-rf"]["need_count_median"] is None        # a batch without the counts says so


# ------------------------------------------------------------------------------------------------------------ review round 4 (batch V)

class NanHsEnv(AnalyticEnv):
    """AnalyticEnv whose Hs is NaN where `nan_when(t)` holds (UMWM's sea mask)."""

    def __init__(self, nan_when, **kw):
        super().__init__(**kw)
        self.nan_when = nan_when

    def waves(self, lon, lat, t):
        w = super().waves(lon, lat, t)
        return dict(w, Hs=Tagged(np.where(self.nan_when(np.asarray(t, float)), np.nan, w["Hs"].value), "test", 0.0, "assumed"))


def test_fill_hs_takes_the_last_finite_value_of_the_member_then_the_next_and_counts():
    """M-10: a NaN Hs was nan_to_num'ed to 0, the glass-calm sea and the deepest two-ray null; now it is the member's neighbour along time."""
    n = np.nan
    hs = np.array([[n, 1.0, n, n, 2.0, n], [0.5] * 6, [3.0, n, 4.0, 5.0, n, n]])
    got, k = stage1.fill_hs(hs, np.full(3, -165.0), np.zeros(3), "x")
    assert got.tolist() == [[1.0, 1.0, 1.0, 1.0, 2.0, 2.0], [0.5] * 6, [3.0, 3.0, 4.0, 5.0, 5.0, 5.0]] and k == 7
    same, k0 = stage1.fill_hs(hs[1:2], np.zeros(1), np.zeros(1), "x")
    assert same is not None and k0 == 0 and same.tolist() == [[0.5] * 6]
    with pytest.raises(OutsideData, match=r"link a: member 1 has no wave height .* at \(-164\.500, 1\.250\)"):
        stage1.fill_hs(np.array([[1.0, n], [n, n]]), np.array([-165.0, -164.5]), np.array([0.0, 1.25]), "link a")


def test_the_uas_link_reads_the_neighbouring_hs_where_the_sea_mask_gave_nan_and_counts_the_samples(monkeypatch):
    seen = []
    orig = stage1.comms.rf_margin
    monkeypatch.setattr(stage1.comms, "rf_margin", lambda *a: seen.append(a) or orig(*a))
    t0 = UTC("2023-03-02T01:00:00Z")
    mission, filled = dict(MISSION), []
    env = NanHsEnv(lambda t: t < t0 + 100.0, hs=2.0)                                       # the first four 30 s samples (0, 30, 60, 90 s) are masked
    hook = stage1._uas_links(env, mission, (-165.0, 0.0), np.array([t0]), uas_plat(), 3, filled)[0]
    hook(t0 + 10.0, np.array([[300.0, 0.0, 30.0]] * 3))
    assert np.allclose(seen[0][3], 2.0) and filled == [12]                                    # Hs 0 (nan_to_num) before the fix
    with pytest.raises(OutsideData, match="UAS link at the ship.*member 0 has no wave height.*-165.000, 0.000"):
        stage1._uas_links(AnalyticEnv(hs=np.nan), mission, (-165.0, 0.0), np.array([t0]), uas_plat(), 2)


def test_the_rf_link_fills_a_masked_hs_from_the_members_neighbouring_record_and_counts_them():
    out, air = rf_scene(M=2, bad_samples=(0, 0))
    pri, _ = stage1.priors_for(MISSION)

    def run(env):
        base = env
        base.u10 = lambda lon, lat, t: np.stack([np.full(np.shape(t), 6.0), np.zeros(np.shape(t))], -1)
        return stage1.evaluate_link(LK["usv-uas-rf"], out, MISSION, PerturbedEnv(base, {}, [0, 1], 3, pri), 2, 3, [0, 1])
    masked = run(NanHsEnv(lambda t: (t >= TGRID[10]) & (t <= TGRID[14]), hs=2.0))
    clear, glass = run(AnalyticEnv(hs=2.0)), run(AnalyticEnv(hs=0.0))
    assert masked["hs_filled"] == 10 and clear["hs_filled"] == 0
    assert np.allclose(masked["margin_db"], clear["margin_db"], equal_nan=True)               # the 2 m sea of the neighbouring record, not a calm one
    assert np.abs(glass["margin_db"][10:15] - clear["margin_db"][10:15]).max() > 0.1          # the test can tell the two apart
    assert "Kerr" in masked["method"] and "divergence" in masked["method"] and "4/3-radius" in masked["method"]
    with pytest.raises(OutsideData, match="link usv-uas-rf: member 0 has no wave height"):
        run(NanHsEnv(lambda t: np.ones(np.shape(t), bool)))


def test_run_writes_the_filled_hs_samples_into_the_ledger(monkeypatch, tmp_path):
    def run_batch(mission, env, members, seed, pri, marg, scales=None):
        b = synth_batch(members, seed=seed)
        b["vehicles"]["uas"]["hs_filled"] = 3
        b["links"]["usv-uas-rf"]["hs_filled"] = 4
        return b
    monkeypatch.setattr(stage1, "run_batch", run_batch)
    r, log, L = drive(tmp_path, dict(batch=8, n_max=16, n_min=8))
    assert r["n"] == 16 and r["res"]["vehicles"]["uas"]["hs_filled"] == 6 and r["res"]["links"]["usv-uas-rf"]["hs_filled"] == 8
    assert any("14 non-finite wave-height samples" in x for x in L.d["notes"])
    monkeypatch.setattr(stage1, "run_batch", lambda mission, env, members, seed, pri, marg, scales=None: synth_batch(members, seed=seed))
    assert not any("non-finite" in x for x in drive(tmp_path / "quiet", dict(batch=8, n_max=8, n_min=8))[2].d["notes"])


def test_a_nan_current_is_a_labelled_failure_through_run_batch_and_the_summary():
    """M-5: an all-NaN current (a land block of the ocean store) was an IndexError out of the USV step and ended Stage 1."""
    v = next(x for x in MISSION["vehicles"] if x["id"] == "usv")
    mission = dict(MISSION, vehicles=[v], links=[])
    pri, marg = stage1.priors_for(mission)
    b = stage1.run_batch(mission, AnalyticEnv(wind=(-5.0, 0.0), current=(np.nan, 0.0)), [0, 1], 11, pri, marg)
    r = b["vehicles"]["usv"]
    assert r["fail"]["no_current_data"].all() and np.isfinite(r["lon"]).all() and np.isfinite(r["stw_ms"]).all()
    modes = stage1.summarize(stage1.merge([b]), list(marg), mission, 73)["vehicles"]["usv"]["modes"]
    assert modes["no_current_data"] == 2


def test_stage1_keeps_the_speed_through_the_water_of_a_real_usv_run():
    """M-7 (1): stw_ms is the member's mean over the steps; at a steady wind it is the polar speed, with no current it equals the speed over ground."""
    v = next(x for x in MISSION["vehicles"] if x["id"] == "usv")
    r = stage1._run_usv(v, usv.load_platform("saildrone_explorer"), AnalyticEnv(wind=(-6.0, 0.0), hs=0.0), 2,
                        {"usv_vpp_bias": np.full(2, -0.24)}, T0, T0 + 6 * 3600.0)
    assert r["stw_ms"].shape == (2,) and np.all((r["stw_ms"] > 0.3) & (r["stw_ms"] < 3.3)) and np.allclose(r["stw_ms"], r["sog_ms"], rtol=0.08)


def uas_profile_stub(calls, wp):
    """sortie_stub whose sorties also report how much of an 8-waypoint pattern member m flew (wp[sortie][m]) and flag profile_incomplete below 8."""
    base = sortie_stub(calls)

    def fly_sortie(*a, **k):
        r = base(*a, **k)
        w = np.array(wp[len(calls) - 1])
        r["wp_done"], r["n_wp"] = w, 8
        r["flags"]["profile_incomplete"] = w < 8
        r["t_first"]["profile_incomplete"] = np.where(w < 8, 1100.0, np.nan)
        return r
    return fly_sortie


def test_the_profile_each_flown_sortie_delivered_is_kept_merged_and_summarised(monkeypatch):
    """M-1: wp_done per member and sortie, n_wp; summary vehicles[uas].profile = median waypoints flown, the pattern length, the share of flown sorties that
    reached every waypoint (scrubbed ones are not flown); profile_incomplete is a mode like the others."""
    calls = []
    monkeypatch.setattr(stage1.uas, "fly_sortie", uas_profile_stub(calls, [[8, 6], [7, 5]]))
    v, P, mission, t0, T, X = uas_inputs(window=("2023-03-01T18:00:00Z", "2023-03-03T06:00:00Z"))
    r = stage1._run_uas(v, P, AnalyticEnv(), 2, X, t0, T, mission, 1, [0, 1])
    assert r["n_wp"] == 8 and [s["wp_done"].tolist() for s in r["sorties"]] == [[8, 6], [7, 5]] and r["scrubbed"].tolist() == [0, 1]
    first = r["first"]["profile_incomplete"] - [UTC("2023-03-03T01:00:00Z"), UTC("2023-03-02T01:00:00Z")]  # member 0: 2nd launch, 1: 1st
    assert r["fail"]["profile_incomplete"].tolist() == [True, True] and np.allclose(first, 1100.0)
    res = stage1.merge([dict(U=np.zeros((2, 1)), X={"a": np.zeros(2)}, links={}, vehicles={"uas": dict(r, **{"class": "uas"})})] * 2)
    assert res["vehicles"]["uas"]["n_wp"] == 8 and [s["wp_done"].tolist() for s in res["vehicles"]["uas"]["sorties"]] == [[8, 6, 8, 6], [7, 5, 7, 5]]
    sm = stage1.summarize(res, ["a"], MISSION, 73)["vehicles"]["uas"]
    assert sm["profile"] == dict(wp_done_median=7.0, n_wp=8, complete_share=pytest.approx(2 / 6)) and sm["modes"]["profile_incomplete"] == 4   # flown: 8, 6, 7


def test_an_older_uas_result_without_wp_done_has_no_profile_block(monkeypatch):
    monkeypatch.setattr(stage1.uas, "fly_sortie", sortie_stub([]))
    v, P, mission, t0, T, X = uas_inputs()
    r = stage1._run_uas(v, P, AnalyticEnv(), 2, X, t0, T, mission, 1, [0, 1])
    assert "n_wp" not in r and all("wp_done" not in s for s in r["sorties"])
    res = stage1.merge([dict(U=np.zeros((2, 1)), X={"a": np.zeros(2)}, links={}, vehicles={"uas": dict(r, **{"class": "uas"})})])
    assert "profile" not in stage1.summarize(res, ["a"], MISSION, 73)["vehicles"]["uas"]
    allscrubbed = dict(r, n_wp=8, sorties=[dict(s, wp_done=np.zeros(2, int), scrubbed=np.ones(2, bool)) for s in r["sorties"]])
    res = stage1.merge([dict(U=np.zeros((2, 1)), X={"a": np.zeros(2)}, links={}, vehicles={"uas": dict(allscrubbed, **{"class": "uas"})})])
    assert "profile" not in stage1.summarize(res, ["a"], MISSION, 73)["vehicles"]["uas"]               # nothing flown, nothing to say


def glider_iridium(when, surfaced_at=(10, 50), M=3):
    surf = np.zeros(TGRID.size, bool)
    surf[list(surfaced_at)] = True
    out = {"glider_eq": track(-165.0, 0.0, M, surfaced=surf, cls="glider", depth=np.where(surf, 0.0, 500.0), antenna=0.5)}
    return dict(LK["usv-shore-iridium"], id="g-shore", a="glider_eq", b="shore", when=when), out


def test_an_iridium_link_to_a_glider_is_required_only_while_the_glider_is_surfaced():
    """M-11: Iridium took `need = live` and so scored a glider that never surfaced as a link that worked at every record."""
    lk, out = glider_iridium("surfacing")
    r = stage1.evaluate_link(lk, out, MISSION, flat_env(3), 3, 3, [0, 1, 2])
    assert r["need_count"].tolist() == [2, 2, 2] and r["method"].startswith("Iridium SBD")
    never = stage1.evaluate_link(lk, glider_iridium("surfacing", surfaced_at=())[1], MISSION, flat_env(3), 3, 3, [0, 1, 2])
    assert never["need_count"].tolist() == [0, 0, 0] and never["frac"].tolist() == [1.0] * 3
    always = stage1.evaluate_link(dict(lk, when="always"), out, MISSION, flat_env(3), 3, 3, [0, 1, 2])
    assert always["need_count"].tolist() == [TGRID.size] * 3                                       # still every moment for a vehicle that is not a glider
    swapped = stage1.evaluate_link(dict(lk, a="shore", b="glider_eq"), out, MISSION, flat_env(3), 3, 3, [0, 1, 2])
    assert swapped["need_count"].tolist() == [2, 2, 2]


# ---------------------------------------------------------------------------------------------------------------- review round 5: M-1, M-9

@pytest.mark.parametrize("cls,run", [("glider_eq", "_run_glider"), ("usv", "_run_usv")])
@pytest.mark.parametrize("sec", [20.0, 30.0, 50.0])
def test_a_deploy_time_with_seconds_does_not_leave_the_data(ci_full, cls, run, sec):
    """M-1: the step count was rounded, so with the window ending on the hour a deploy at hh:00:20 or hh:00:30 stepped up to 30 s past the end (the last
    record, a multiple of 10 steps, was then outside the data) and every member failed `left_data`; the emulator design lost those variants."""
    v = next(x for x in MISSION["vehicles"] if x["id"] == cls)
    M, T = 4, float(ci_full.tw.x[-1])
    X = {"glider_speed_scale": np.ones(M), "battery_capacity_scale": np.ones(M), "usv_vpp_bias": np.full(M, -0.24)}
    P = glider.load_platform("seaglider") if cls == "glider_eq" else usv.load_platform("saildrone_explorer")
    with ci_full.lenient():
        r = getattr(stage1, run)(v, P, ci_full, M, X, T - 4 * 3600.0 + sec, T)
        stage1._left_data(r, ci_full)
    assert r["t"][-1] <= T and not r["fail"]["left_data"].any()


def test_gust_fronts_are_drawn_from_the_rain_of_each_hour_not_from_the_smoothed_node_rate(ci_full, monkeypatch):
    """M-9: the gust-front draw read rain_mm_h (the hourly node values, half of an hour's rain at each end node) as the rate of the hour that starts at
    the node: the 10 mm/h burst of 23Z..02Z read 0, 5, 10, 10, 5, 0, so rain fell into the hour after it stopped and the first hour got half."""
    from tests.fixtures.ci_env import make as fx
    seen = []
    real = stage1.subgrid.gust_fronts

    def spy(seed, rain, hours, *a, **k):
        seen.append((np.asarray(rain), np.asarray(hours)))
        return real(seed, rain, hours, *a, **k)
    monkeypatch.setattr(stage1.subgrid, "gust_fronts", spy)
    foot = fx.rain_footprint(ci_full.low.x[None, :], ci_full.law.x[:, None])
    j, i = np.unravel_index(np.argmax(foot), foot.shape)
    origin = (float(ci_full.low.x[i]) - 360.0, float(ci_full.law.x[j]))
    mission = dict(environment=dict(subgrid=dict(gust_fronts=True)))
    stage1._uas_forcing(ci_full, mission, origin, np.array([fx.RAIN_T0]), uas_plat(), 2, 1, [0, 1])
    rain, hours = seen[0]
    assert hours[0] == fx.RAIN_T0 - 3600.0
    assert rain.tolist() == pytest.approx([0.0, 10.0, 10.0], rel=1e-3)                          # the hours 22Z, 23Z, 00Z; the nodes gave [0, 5, 10]


# ---------------------------------------------------------------------------------------------------------------- review round 5 (batch S)

def profile_stub(per_sortie, n_wp=10, scrubbed=None):
    """sortie_stub plus what the real fly_sortie returns for the pattern: wp_done (M,) of the sortie being flown and n_wp; `scrubbed` replaces the stub's."""
    calls = []
    base = sortie_stub(calls)

    def fly(*a, **k):
        r = base(*a, **k)
        r.update(wp_done=per_sortie[len(calls) - 1], n_wp=n_wp)
        return r if scrubbed is None else dict(r, scrubbed=np.asarray(scrubbed))
    return fly


def test_the_uas_profile_margin_is_the_lowest_share_of_the_pattern_over_the_flown_sorties(monkeypatch):
    """M-2: stage 1 stored only the battery margin, so a UAS that failed `profile_incomplete` in 55 of 55 members was ranked on its battery."""
    v, P, mission, t0, T, X = uas_inputs(window=("2023-03-01T18:00:00Z", "2023-03-03T06:00:00Z"))
    fly_args = (v, P, AnalyticEnv(), 2, X, t0, T, mission, 1, [0, 1])
    # sortie 2: member 1 is scrubbed (the stub does that), so its 2 of 10 does not count
    monkeypatch.setattr(stage1.uas, "fly_sortie", profile_stub([np.array([8, 5]), np.array([10, 2])]))
    r = stage1._run_uas(*fly_args)
    assert r["profile_margin"].tolist() == [0.8, 0.5] and r["profile_margin_name"] == "fraction of the flux profile delivered (lowest sortie)"
    assert r["margin_name"] == "battery reserve margin"                      # the battery margin is still stored beside it
    monkeypatch.setattr(stage1.uas, "fly_sortie", sortie_stub([]))
    assert "profile_margin" not in stage1._run_uas(*fly_args)                 # a sortie result without wp_done (an older fly_sortie) gives none
    monkeypatch.setattr(stage1.uas, "fly_sortie", profile_stub([np.array([8, 5])] * 2, scrubbed=[True, True]))
    assert np.isnan(stage1._run_uas(*fly_args)["profile_margin"]).all()       # no flown sortie: no margin


def test_the_profile_margin_joins_along_the_members_like_the_battery_margin():
    a, b = synth_batch(list(range(0, 8))), synth_batch(list(range(8, 16)))
    for batch in (a, b):
        batch["vehicles"]["uas"].update(profile_margin=np.arange(8.0) / 8, profile_margin_name="q")
    r = stage1.merge([a, b])["vehicles"]["uas"]
    assert r["profile_margin"].shape == (16,) and r["profile_margin_name"] == "q" and "profile_margin" not in stage1.merge([a, b])["vehicles"]["usv"]


def uas_profile_ensemble(dominant):
    """24 members; the UAS fails by `dominant`, both margins stored: the battery margin follows battery_capacity_scale, the profile margin bulk_stress_scale."""
    names = list(stage1.priors_for(MISSION)[1])
    res = merged({})
    n, r = 24, res["vehicles"]["uas"]
    prof = 1.0 - res["U"][:, names.index("bulk_stress_scale")]
    f = prof < 0.5
    r["fail"] = {m: f if m == dominant else np.zeros(n, bool) for m in ("battery_reserve", "profile_incomplete")}
    r["first"] = {m: np.where(f, 100.0, np.nan) if m == dominant else np.full(n, np.nan) for m in r["fail"]}
    r["margin"], r["margin_name"] = res["U"][:, names.index("battery_capacity_scale")].copy(), "battery reserve margin"
    r["profile_margin"], r["profile_margin_name"] = prof, "fraction of the flux profile delivered (lowest sortie)"
    return names, res


def test_a_uas_that_fails_by_an_incomplete_profile_ranks_the_profile_not_the_battery():
    names, res = uas_profile_ensemble("profile_incomplete")
    s = stage1.summarize(res, names, MISSION, 73)["vehicles"]["uas"]["sensitivity"]
    assert s["quantity"] == "fraction of the flux profile delivered (lowest sortie)" and s["case"] == "ranked" and s["param"] == "bulk_stress_scale"
    assert "for the fraction of the flux profile delivered" in s["text"] and "battery" not in s["text"]
    names, res = uas_profile_ensemble("battery_reserve")                     # a battery failure keeps ranking the battery margin
    s = stage1.summarize(res, names, MISSION, 73)["vehicles"]["uas"]["sensitivity"]
    assert s["quantity"] == "battery reserve margin"


def test_a_ranked_sentence_says_how_many_unrelated_outcomes_would_clear_the_floor_and_how_many_such_tests_the_report_makes():
    names = list(stage1.priors_for(MISSION)[1])
    res = merged({"glider_eq": 0.25, "usv": 0.25}, {"usv-uas-rf": 0.25, "glider_eq-ship-acoustic": 0.25})
    for vid, q in (("glider_eq", "maximum distance from the station"), ("usv", "maximum cross-track error")):
        res["vehicles"][vid]["margin"], res["vehicles"][vid]["margin_name"] = -res["U"][:, 0].copy(), q
    s = stage1.summarize(res, names, MISSION, 73)
    tests = [e["sensitivity"] for k in ("vehicles", "links") for e in s[k].values() if e["sensitivity"]["noise_floor"] is not None]
    ranked = [t for t in tests if t["case"] == "ranked"]
    assert ranked and len(tests) >= 4
    for t in ranked:
        assert t["text"].endswith(f"(one in twenty unrelated outcomes would also clear it, and the report makes {len(tests)} such tests).")
    assert all("one in twenty" not in t["text"] for t in tests if t["case"] != "ranked")


def test_a_mission_that_leaves_out_environment_subgrid_flies_the_uas_with_turbulence_and_gust_fronts(ci_full, monkeypatch):
    """M-7: `stage1` read those two switches with no default, so a smaller mission than the demo flew a laminar UAS and said nothing."""
    monkeypatch.setattr(stage1.uas, "fly_sortie", sortie_stub([]))
    v, P, mission, t0, T, X = uas_inputs(window=("2023-03-01T18:00:00Z", "2023-03-02T12:00:00Z"))
    bare = {k: x for k, x in mission.items() if k != "environment"}
    for m, want in ((bare, ["uas/gust", "uas/turb/0"]), (dict(mission, environment={}), ["uas/gust", "uas/turb/0"]),
                    (dict(mission, environment=dict(subgrid=dict(turbulence=False, gust_fronts=False))), [])):
        used = {}
        stage1._run_uas(v, P, ci_full, 2, X, t0, T, m, 1, [0, 1], used=used)
        assert sorted(used) == want, m.get("environment")


def test_the_summary_says_which_of_the_five_switches_the_mission_left_out():
    names = list(stage1.priors_for(MISSION)[1])
    s = stage1.summarize(merged({}), names, MISSION, 73)["subgrid_switches"]
    assert list(s) == ["turbulence", "gust_fronts", "warm_layer", "rain_lens", "ocean_sde"] and all(x == dict(on=True, defaulted=False) for x in s.values())
    odd = dict(MISSION, environment=dict(MISSION["environment"], subgrid=dict(rain_lens=False, ocean_sde=True)))
    s = stage1.summarize(merged({}), names, odd, 73)["subgrid_switches"]
    assert s["rain_lens"] == dict(on=False, defaulted=False) and s["ocean_sde"] == dict(on=True, defaulted=False)
    assert all(s[k] == dict(on=True, defaulted=True) for k in ("turbulence", "gust_fronts", "warm_layer"))
    bare = stage1.subgrid_switches({k: x for k, x in MISSION.items() if k != "environment"})
    assert all(x == dict(on=True, defaulted=True) for x in bare.values())
