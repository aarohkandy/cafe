"""cafe.pm.whatif: mission changes, training rows, the per-class emulators, the flip search and the what-if answer.

Stage 1 runs for real on a fake environment where the answer is known (a storm current that stops 20 h into the window, so that deploying
24 h later avoids it); the emulators are fitted on tables fabricated from the same rule, which is test data only.
"""
import copy
import re

import numpy as np
import pandas as pd
import pytest

from cafe.pm import Tagged, budget, config, stage1, whatif
from cafe.pm.config import ConfigError
from cafe.pm.env.environment import OutsideData
from cafe.pm.env.protocol import AnalyticEnv
from tests.fixtures import pm_run

ROOT = config.ROOT
CI = config.load_mission(ROOT / "missions" / "ci_fixture.yaml")
DEMO = config.load_mission(ROOT / "missions" / "tepex_c_demo.yaml")
UTC = lambda s: config.utc(s).timestamp()
T0 = UTC(CI["window"]["start"])
GL = "glider_eq"


class StormEnv(AnalyticEnv):
    """A 0.6 m/s eastward current until `t_end`, calm after; the glider (0.25 m/s) cannot hold station in it."""

    def __init__(self, t_end, speed=0.6, **kw):
        super().__init__(current=(speed, 0.0), **kw)
        self.t_end = t_end

    def current(self, lon, lat, z, t):
        v = super().current(lon, lat, z, t).value
        return Tagged(v * np.broadcast_to(np.asarray(t, float) < self.t_end, v.shape[:-1])[..., None], "storm", 0.0, "assumed")


def storm_mission(hours=60):
    """One station-keeping glider deployed at the start of a 60 h window; no links."""
    m = copy.deepcopy(CI)
    m["window"]["end"] = whatif._iso(T0 + 3600.0 * hours)
    m["vehicles"] = [v for v in m["vehicles"] if v["id"] == GL]
    m["links"] = []
    return m


STORM = storm_mission()
ENV = StormEnv(T0 + 20 * 3600.0)
PRI = stage1.priors_for(STORM)
TRACK = (np.linspace(T0, T0 + 60 * 3600.0, 24), np.full(24, -165.5), np.zeros(24))          # where the glider sits: on station


def plan_for(m, batch=16):
    p = budget.plan("ci", 0, m, thr={}, vehicle_classes=stage1._classes(m))
    p.update(batch=batch, n_max=batch, n_min=batch)
    return p


def storm_table(n=140, seed=0, noise=0.02):
    """Glider rows made from the storm rule with the same feature code the product uses: P(fail) is high when a storm current is on the track."""
    rng = np.random.default_rng(seed)
    rows = []
    for _ in range(n):
        mod = dict(shift_h=45.0 * rng.uniform() ** 2, dlon=rng.uniform(-1, 1), dlat=rng.uniform(-1, 1))             # denser near the base mission
        m2 = whatif.apply(STORM, {GL: mod})
        f = {**whatif.params(m2, GL, "glider"), **whatif.env_stats(ENV, *whatif.shift_track(TRACK, mod, m2))}
        p = float(np.clip((0.85 if f["cur_p90"] > 0.3 else 0.03) + rng.normal(0, noise), 0.0, 1.0))
        rows.append(dict(f, p_fail=p, t_fail_h=20.0 if p > 0.5 else 60.0, mode_station_lost=p, cls="glider", n_members=512, fidelity=0, vehicle=GL))
    return pd.DataFrame(rows)


@pytest.fixture(scope="module")
def storm_em(tmp_path_factory):
    em, info = whatif.fit_class(storm_table(), "glider", tmp_path_factory.mktemp("em") / "train.parquet")
    assert em is not None, info
    return em, info


# ---------------------------------------------------------------------------------------------------------------- mission changes

def test_a_later_deploy_moves_the_deploy_time_and_nothing_else():
    m = whatif.apply(CI, {GL: dict(shift_h=6)})
    assert whatif.vehicle(m, GL)["deploy"]["time"] == "2023-03-02T00:00:00Z" and whatif.vehicle(CI, GL)["deploy"]["time"] == "2023-03-01T18:00:00Z"
    assert m["window"] == CI["window"] and whatif.vehicle(m, "usv")["deploy"] == whatif.vehicle(CI, "usv")["deploy"]


@pytest.mark.parametrize("h", [-6, 36, 35.5])
def test_a_deploy_outside_the_window_is_refused_naming_the_vehicle(h):
    with pytest.raises(whatif.Invalid, match=re.escape(f"{GL}: deploying {h:+g} h gives") + ".* outside the window"):
        whatif.apply(CI, {GL: dict(shift_h=h)})


def test_a_move_carries_the_station_the_waypoints_and_a_uas_moves_its_ship():
    m = whatif.apply(CI, {GL: dict(dlon=-0.5, dlat=0.5), "usv": dict(dlon=0.5), "uas": dict(dlat=-0.25)})
    g, u = whatif.vehicle(m, GL), whatif.vehicle(m, "usv")
    assert (g["deploy"]["lon"], g["deploy"]["lat"]) == (-166.0, 0.5) and (g["task"]["lon"], g["task"]["lat"]) == (-166.0, 0.5)
    assert u["task"]["waypoints"] == [[-164.5, -1.0], [-164.5, 1.0]] and (m["ship"]["lon"], m["ship"]["lat"]) == (-165.0, -0.25)
    assert whatif.vehicle(m, "glider_1n")["deploy"]["lon"] == -165.0 and "waypoints" not in g["task"]
    two = whatif.apply(CI, {"uas": dict(dlat=-0.25), "glider_1n": dict()})
    assert two["ship"]["lat"] == -0.25


def test_a_move_out_of_the_box_is_refused():
    with pytest.raises(whatif.Invalid, match=r"outside the mission box"):
        whatif.apply(CI, {GL: dict(dlon=-1.5)})
    with pytest.raises(whatif.Invalid, match=r"outside the mission box"):
        whatif.apply(CI, {"uas": dict(dlat=2.0)})


def test_a_uas_shift_moves_its_sorties_through_the_day_and_a_lower_duty_spaces_them():
    m = whatif.apply(CI, {"uas": dict(shift_h=-6.5, duty=0.5)})
    s = whatif.vehicle(m, "uas")["sorties"]
    assert s["local_solar_time"] == "07:30" and s["every_days"] == 2.0
    assert whatif.apply(CI, {"uas": dict(shift_h=12)})["vehicles"][3]["sorties"]["local_solar_time"] == "02:00"       # wraps past midnight


def test_a_lower_duty_shortens_a_glider_dive_and_a_usv_has_none():
    assert whatif.vehicle(whatif.apply(CI, {GL: dict(duty=0.5)}), GL)["task"]["dive_depth_m"] == 475.0
    with pytest.raises(whatif.Invalid, match="usv: the task has no duty cycle"):
        whatif.apply(CI, {"usv": dict(duty=0.5)})
    m = copy.deepcopy(CI)
    del whatif.vehicle(m, "glider_1n")["task"]["dive_depth_m"]
    with pytest.raises(whatif.Invalid, match="glider_1n: the task has no duty cycle"):
        whatif.apply(m, {"glider_1n": dict(duty=0.5)})


def test_dropping_a_vehicle_takes_its_links_and_an_unknown_vehicle_is_refused():
    m = whatif.apply(CI, drop=[GL])
    assert [v["id"] for v in m["vehicles"]] == ["glider_1n", "usv", "uas"] and [k["id"] for k in m["links"]] == ["usv-uas-rf", "usv-shore-iridium"]
    assert whatif.apply(CI, {GL: dict(shift_h=6)}, drop=[GL])["vehicles"][0]["id"] == "glider_1n"            # a change to a dropped vehicle is moot
    for bad in (dict(drop=["nope"]), dict(mods={"nope": dict(shift_h=1)})):
        with pytest.raises(ConfigError, match="no vehicle 'nope'"):
            whatif.apply(CI, **bad)
    assert CI["links"] and len(CI["vehicles"]) == 4                                                              # the input is never modified


def test_solo_keeps_one_vehicle_and_no_links():
    m = whatif.solo(CI, "usv")
    assert [v["id"] for v in m["vehicles"]] == ["usv"] and m["links"] == [] and len(CI["vehicles"]) == 4


def test_a_change_in_words():
    v = whatif.vehicle(CI, GL)
    assert whatif.describe(dict(shift_h=24), v) == "deploy 24 h later" and whatif.describe(dict(shift_h=-6), v) == "deploy 6 h earlier"
    assert whatif.describe(dict(dlon=-0.5, dlat=1.0), v) == "move 0.5 deg west and move 1 deg north"
    assert whatif.describe(dict(dlon=1.0, dlat=-1.0), None) == "move 1 deg east and move 1 deg south"
    assert whatif.describe(dict(duty=0.75), v) == "dive 25 % shallower (950 m to 712.5 m)" and whatif.describe(dict(duty=0.75), None) == "dive 25 % shallower"
    u = whatif.vehicle(CI, "uas")
    assert whatif.describe(dict(shift_h=6, duty=0.5), u) == "launch the sorties 6 h later and fly sorties every 2 d instead of 1"
    assert whatif.describe({}, v) == "no change"


@pytest.mark.parametrize("text,h", [("48h", 48.0), ("-6h", -6.0), ("+6H", 6.0), ("2d", 48.0), ("0.5 h", 0.5)])
def test_shift_forms(text, h):
    assert whatif.parse_shift(text) == h


@pytest.mark.parametrize("text,d", [("1deg W", (-1.0, 0.0)), ("0.5deg north", (0.0, 0.5)), ("2 deg e", (2.0, 0.0)), ("1°S", (0.0, -1.0)),
                                    ("3 SOUTH", (0.0, -3.0))])
def test_move_forms(text, d):
    assert whatif.parse_move(text) == d


@pytest.mark.parametrize("fn,text", [(whatif.parse_shift, "soon"), (whatif.parse_shift, "48"), (whatif.parse_move, "1deg up"), (whatif.parse_move, "west")])
def test_a_bad_form_is_a_config_error_that_gives_an_example(fn, text):
    with pytest.raises(ConfigError, match=r"expected .*e\.g\. "):
        fn(text)


# ---------------------------------------------------------------------------------------------------------------- features and rows

def test_environment_statistics_are_mean_and_p90_of_speed():
    env = AnalyticEnv(wind=(3.0, 4.0), hs=2.5, current=(0.3, 0.4))
    s = whatif.env_stats(env, np.full(5, T0), np.full(5, -165.0), np.zeros(5))
    assert s["hs_mean"] == s["hs_p90"] == 2.5 and s["cur_mean"] == pytest.approx(0.5)
    assert s["wind_mean"] == pytest.approx(5.0) and set(s) == {f"{a}_{b}" for a in ("wind", "hs", "cur") for b in ("mean", "p90")}
    ramp = StormEnv(T0 + 5 * 3600.0, speed=1.0)                                  # half of the 10 samples are in the storm
    c = whatif.env_stats(ramp, T0 + 3600.0 * np.arange(10), np.zeros(10), np.zeros(10))
    assert c["cur_mean"] == pytest.approx(0.5) and c["cur_p90"] == pytest.approx(1.0)


def test_parameters_per_class():
    g = whatif.params(CI, GL, "glider")
    assert g == dict(deploy_h=0.0, lon=-165.5, lat=0.0, dive_depth_m=950.0, radius_km=5.0, lost_after_h=12.0)
    s = whatif.params(whatif.apply(CI, {GL: dict(shift_h=6, dlon=-1.0)}), GL, "glider")
    assert (s["deploy_h"], s["lon"]) == (6.0, -166.5)
    d = whatif.params(CI, "glider_1n", "glider")
    assert d["radius_km"] == 0.0 and d["lost_after_h"] == 0.0 and d["dive_depth_m"] == 500.0                      # drift mode: no station
    assert whatif.params(CI, "usv", "usv") == dict(deploy_h=0.0, lon=-165.0, lat=-1.0, track_tolerance_km=20.0, becalmed_after_h=6.0)
    u = whatif.params(CI, "uas", "uas")
    assert u == dict(deploy_h=7.0, lon=-165.0, lat=0.0, every_days=1.0, duration_min=20.0, max_mean_wind_ms=12.0)        # first sortie 01Z on 03-02
    assert whatif.params(whatif.apply(CI, {"uas": dict(shift_h=12.0)}), "uas", "uas")["deploy_h"] == 19.0
    short = copy.deepcopy(CI)
    short["window"]["end"] = "2023-03-01T20:00:00Z"
    assert whatif.params(short, "uas", "uas")["deploy_h"] == 0.0                                                    # no sortie fits: nothing to offset
    over = copy.deepcopy(DEMO)                                                       # a box over the dateline: longitudes are continuous about its centre
    assert whatif.params(over, "glider_eq", "glider")["lon"] == 190.0 and whatif.params(over, "usv", "usv")["lon"] == 195.0               # -170 and -165


def test_the_uas_track_is_the_ship_at_the_middle_of_each_sortie():
    t, lon, lat = whatif.uas_track(CI, "uas")
    assert list(t) == [UTC("2023-03-02T01:10:00Z"), UTC("2023-03-03T01:10:00Z")] and set(lon) == {-165.0} and set(lat) == {0.0}
    short = copy.deepcopy(CI)
    short["window"]["end"] = "2023-03-01T20:00:00Z"
    t, _, _ = whatif.uas_track(short, "uas")
    assert list(t) == [(T0 + UTC("2023-03-01T20:00:00Z")) / 2]


def test_a_shifted_track_is_later_moved_and_cut_at_the_window_end():
    t, lon, lat = whatif.shift_track(TRACK, dict(shift_h=24, dlon=0.5, dlat=-0.5), STORM)
    assert t[0] == TRACK[0][0] + 24 * 3600.0 and t.max() <= T0 + 60 * 3600.0 and len(t) < 24
    assert set(lon) == {-165.0} and set(lat) == {-0.5}
    t, _, _ = whatif.shift_track(TRACK, dict(shift_h=61), STORM)
    assert len(t) == 1 and t[0] == TRACK[0][-1] + 61 * 3600.0                                                    # all cut: the last point is kept
    assert len(whatif.shift_track(TRACK, {}, STORM)[0]) == 24


def test_targets_from_a_stage1_result():
    res, _ = pm_run.make_res(seed=1, fail_frac=0.4, M=48)
    r = res["vehicles"]["glider_eq"]
    t = whatif.targets(r)
    f = stage1.failed(r)
    assert t["p_fail"] == pytest.approx(f.mean()) and t["mode_station_lost"] == pytest.approx(f.mean())
    first = np.nanmin(np.array([np.asarray(x, float) for x in r["first"].values()]), 0)
    assert t["t_fail_h"] == pytest.approx(np.median((first[f] - r["t"][0]) / 3600.0))
    ok = whatif.targets(res["vehicles"]["glider_2n"])
    assert ok["p_fail"] == 0.0 and ok["t_fail_h"] == pytest.approx((r["t"][-1] - r["t"][0]) / 3600.0)  # none failed: right-censored at the exposure
    u = whatif.targets(res["vehicles"]["uas"])
    assert u["mode_gust_front"] > 0 and u["mode_battery"] == 0.0


META = dict(run_id="r1", mission="demo", git_sha="abc", code_digest="def")


def synthetic_rows(variant="base", fid=None):
    res, _ = pm_run.make_res(seed=1, fail_frac=0.4, M=48)
    return whatif.vehicle_rows(DEMO, res, AnalyticEnv(wind=(3.0, 4.0), hs=2.0, current=(0.1, 0.0)), fid or {}, META, variant)


def test_one_row_per_vehicle_with_features_targets_and_metadata():
    rows = synthetic_rows(fid={"glider_eq": 1})
    assert [r["vehicle"] for r in rows] == ["glider_eq", "glider_2n", "usv", "uas"] and [r["cls"] for r in rows] == ["glider", "glider", "usv", "uas"]
    g, u = rows[0], rows[3]
    assert g["fidelity"] == 1 and rows[1]["fidelity"] == 0 and g["n_members"] == 48 and g["key"] == "r1|glider_eq|base"
    assert g["run_id"] == "r1" and g["mission"] == "demo" and g["git_sha"] == "abc" and g["code_digest"] == "def" and g["variant"] == "base"
    assert g["wind_mean"] == pytest.approx(5.0) and g["hs_p90"] == 2.0 and g["cur_mean"] == pytest.approx(0.1)
    assert g["dive_depth_m"] == 950.0 and u["every_days"] == 1.0 and "dive_depth_m" not in u
    assert 0.0 < g["p_fail"] < 1.0 and g["mode_station_lost"] == g["p_fail"]


def test_rows_append_and_a_rerun_replaces_its_own_rows(tmp_path):
    path = tmp_path / "emulator" / "train.parquet"
    a, used = whatif.add_rows(path, synthetic_rows())
    assert used == str(path) and len(a) == 4 and path.is_file()
    b, _ = whatif.add_rows(path, synthetic_rows("v0"))
    assert len(b) == 8 and sorted(b["variant"].unique()) == ["base", "v0"]
    other = [dict(r, run_id="r2", key=r["key"].replace("r1", "r2")) for r in synthetic_rows()]
    assert len(whatif.add_rows(path, other)[0]) == 12                                                           # another run adds
    again, _ = whatif.add_rows(path, synthetic_rows())
    assert len(again) == 12 and again["run_id"].tolist().count("r1") == 8                                         # the same run replaces its rows


def test_without_pyarrow_the_table_is_a_csv(tmp_path, monkeypatch):
    monkeypatch.setattr("importlib.util.find_spec", lambda name: None)
    _, used = whatif.add_rows(tmp_path / "t.parquet", synthetic_rows())
    assert used == str(tmp_path / "t.csv") and (tmp_path / "t.csv").is_file()


# ---------------------------------------------------------------------------------------------------------------- training design

def test_the_design_is_reproducible_valid_and_gives_each_vehicle_its_own_points():
    d = whatif.design(CI, 4, 7)
    assert d == whatif.design(CI, 4, 7) and d != whatif.design(CI, 4, 8) and len(d) == 4
    assert whatif.design(CI, 0, 7) == []
    for mods in d:
        assert set(mods) == {v["id"] for v in CI["vehicles"]}
        whatif.apply(CI, mods)                                                                                   # every variant is a valid mission
    shifts = {(k, vid): d[k][vid]["shift_h"] for k in range(4) for vid in d[k]}
    assert len({round(s, 6) for s in shifts.values()}) > 8
    assert all(-12.0 <= d[k]["uas"]["shift_h"] <= 12.0 for k in range(4)) and all(d[k]["usv"]["duty"] == 1.0 for k in range(4))
    assert any(d[k][GL]["duty"] < 1.0 for k in range(4)) and all(d[k][GL]["shift_h"] >= 0.0 for k in range(4))        # deployed at the start: only later


def test_a_variant_that_does_not_fit_is_shrunk_and_finally_dropped():
    big = dict(shift_h=1000.0, dlon=-3.0, dlat=0.0, duty=0.8)
    assert whatif._fits(CI, GL, big) == dict(shift_h=0.0, dlon=0.0, dlat=0.0, duty=1.0)
    fits = whatif._fits(CI, GL, dict(shift_h=40.0, dlon=0.0, dlat=0.0, duty=1.0))
    assert fits["shift_h"] == 20.0


# ---------------------------------------------------------------------------------------------------------------- fit and score

def test_too_few_rows_say_how_many_there_are_and_how_many_are_needed(tmp_path):
    em, info = whatif.fit_class(storm_table(30), "glider", tmp_path / "t.parquet")
    assert em is None and info["trained"] is False and info["rows"] == 30 and "30 glider rows" in info["reason"] and "100 are needed" in info["reason"]
    em, info = whatif.fit_class(storm_table(30), "usv", tmp_path / "t.parquet")
    assert info["rows"] == 0 and "0 usv rows" in info["reason"]


def test_rows_with_no_failures_have_nothing_to_learn(tmp_path):
    df = storm_table(120)
    df["p_fail"] = 0.0
    em, info = whatif.fit_class(df, "glider", tmp_path / "t.parquet")
    assert em is None and info["reason"] == "P(fail) is 0.000 in all 120 glider rows: nothing to learn"


def test_rows_with_missing_features_are_left_out(tmp_path):
    df = storm_table(110)
    df.loc[:15, "wind_mean"] = np.nan
    em, info = whatif.fit_class(df, "glider", tmp_path / "t.parquet")
    assert em is None and info["rows"] == 94


def test_a_trained_emulator_reports_its_holdout_and_acceptance(storm_em):
    em, info = storm_em
    assert info["trained"] and info["cls"] == "glider" and info["rows"] == 140 and info["n_test"] == 28 and info["n_train"] == 112
    assert info["nominal"] == 0.9 and set(info["rmse"]) == {"p_fail", "t_fail_h", "mode_station_lost"} and info["rmse"]["p_fail"] < 0.15
    assert 0.0 < info["coverage"]["p_fail"] <= 1.0 and info["query_ms"] > 0 and info["noise_floor_rmse"] == pytest.approx(0.0, abs=0.02)
    assert info["rmse_debiased"] == pytest.approx(np.sqrt(max(info["rmse"]["p_fail"] ** 2 - info["noise_floor_rmse"] ** 2, 0.0)))
    assert info["acceptance"]["query_ok"] and em.features == whatif.BASE + whatif.TASK["glider"] and em.targets[:2] == ["p_fail", "t_fail_h"]
    assert info["threshold"] == em.threshold and info["multi_fidelity"] is False


def test_acceptance_is_judged_against_the_briefs_limits(tmp_path, monkeypatch):
    df = storm_table(140)
    monkeypatch.setattr(whatif, "LIMITS", dict(rmse=1e-9, coverage=1e-9, query_ms=1e-9))
    _, info = whatif.fit_class(df, "glider", tmp_path / "t.parquet")
    assert info["trained"] and info["acceptance"] == dict(rmse_ok=False, coverage_ok=False, query_ok=False)


def test_a_deliberately_bad_emulator_misses_the_rmse_acceptance(tmp_path):
    df = storm_table(140)
    df["p_fail"] = np.random.default_rng(3).uniform(0, 1, len(df))                                              # no relation to any feature
    em, info = whatif.fit_class(df, "glider", tmp_path / "t.parquet")
    assert info["trained"] and info["rmse"]["p_fail"] > 0.2 and info["acceptance"]["rmse_ok"] is False
    assert info["noise_floor_rmse"] > 0.0


def test_train_fits_each_class_from_the_stored_table(tmp_path):
    out = whatif.train(tmp_path / "none.parquet", ["glider", "usv", "glider"])
    assert set(out) == {"glider", "usv"} and all(e is None and not i["trained"] and "0 " in i["reason"] for e, i in out.values())
    path = tmp_path / "train.parquet"
    whatif.add_rows(path, [dict(r, key=f"k{i}", run_id="r") for i, r in enumerate(storm_table(120).to_dict("records"))])
    out = whatif.train(path, ["glider", "usv"])
    assert out["glider"][0] is not None and out["glider"][1]["trained"] and out["usv"][0] is None


# ---------------------------------------------------------------------------------------------------------------- the flip search

def test_candidates_are_single_changes_in_cost_order():
    c = whatif.candidates(CI, GL)
    assert [x["cost"] for x in c] == sorted(x["cost"] for x in c) and len(c) == 8 + 8 + 2
    assert {x["change"] for x in c} >= {"deploy 6 h later", "deploy 48 h earlier", "move 0.5 deg west", "move 1 deg north",
                                        "dive 25 % shallower (950 m to 712.5 m)"}
    assert next(x for x in c if x["change"] == "deploy 24 h later")["cost"] == 4.0 and next(x for x in c if x["change"] == "move 1 deg east")["cost"] == 2.0
    assert len(whatif.candidates(CI, "usv")) == 16 and len(whatif.candidates(CI, "uas")) == 18
    assert all(len(x["mod"]) == 1 for x in c)


def test_emulate_says_why_it_cannot_answer(storm_em):
    em, _ = storm_em
    assert whatif.emulate(em, {})["status"] == "no_track"                                                       # features missing
    assert whatif.predict(None, STORM, GL, "glider", TRACK, {}, ENV) == dict(status="no_emulator")
    assert whatif.predict(em, STORM, GL, "glider", None, {}, ENV) == dict(status="no_track")
    far = whatif.predict(em, whatif.apply(STORM, {GL: dict(duty=0.5)}), GL, "glider", TRACK, dict(duty=0.5), ENV)
    assert far["status"] == "out_of_range" and far["distance"] > far["threshold"]
    ok = whatif.predict(em, STORM, GL, "glider", TRACK, {}, ENV)
    assert ok["status"] == "ok" and ok["verdict"] == "NO-GO" and ok["p_fail"] > 0.6 and ok["lo"] <= ok["p_fail"] <= ok["hi"]
    assert ok["distance"] <= ok["threshold"]


def test_the_emulated_flip_search_finds_the_24_h_shift_that_avoids_the_storm(storm_em):
    em, _ = storm_em
    flips, spent = whatif.flip_search(STORM, {GL: dict(verdict="NO-GO", p_fail=0.9)}, {GL: TRACK}, ENV, {"glider": (em, {})}, plan_for(STORM), *PRI, None, 5,
                                      100.0, lambda *_: None)
    f = flips[GL]
    assert spent == 0.0 and f["found"] and f["emulator"] and f["target"] == "GO or MARGINAL"
    b = f["best"]
    assert b["change"] == "deploy 24 h later" and b["method"] == "EMULATED" and b["verdict"] == "GO" and b["p_fail"] < 0.1 and b["cost"] == 4.0
    assert b["distance"] <= b["threshold"] and b["lo"] <= b["p_fail"] <= b["hi"]
    by = {t["change"]: t for t in f["tried"]}
    assert len(f["tried"]) == 18 and by["deploy 12 h later"]["verdict"] == "NO-GO" and by["deploy 6 h later"]["verdict"] == "NO-GO"
    assert by["deploy 6 h earlier"]["method"] == "not evaluated" and "outside the window" in by["deploy 6 h earlier"]["reason"]
    assert by["deploy 48 h later"]["verdict"] == "GO" and by["dive 25 % shallower (950 m to 712.5 m)"]["reason"] == "out of range"
    assert by["move 0.5 deg east"]["method"] == "EMULATED"


def test_a_marginal_vehicle_must_reach_go_and_a_go_vehicle_is_left_alone(storm_em):
    em, _ = storm_em
    marg = {GL: dict(verdict="MARGINAL", p_fail=0.2), "other": dict(verdict="GO", p_fail=0.0)}
    flips, _ = whatif.flip_search(STORM, marg, {GL: TRACK}, ENV, {"glider": (em, {})}, plan_for(STORM), *PRI, None, 5, 100.0, lambda *_: None)
    assert set(flips) == {GL} and flips[GL]["target"] == "GO" and flips[GL]["best"]["change"] == "deploy 24 h later"


def test_stage_1_answers_what_the_emulator_cannot_and_finds_the_same_flip(monkeypatch):
    """No emulator: the cheapest candidates are run in Stage 1 (one batch of the base run's members) until one flips the verdict."""
    monkeypatch.setattr(whatif, "FALLBACK_K", 20)
    plan = plan_for(STORM)
    pri, marg = stage1.priors_for(STORM)
    log = []
    flips, spent = whatif.flip_search(STORM, {GL: dict(verdict="NO-GO", p_fail=1.0)}, {GL: TRACK}, ENV, {}, plan, pri, marg, None, 5, 1e6, log.append)
    f = flips[GL]
    assert f["found"] and not f["emulator"] and spent > 0.0
    b = f["best"]
    assert b["method"] == "Stage 1" and b["n"] == 16 and b["change"] in ("deploy 24 h later", "deploy 12 h later") and b["verdict"] in ("GO", "MARGINAL")
    ran = [t for t in f["tried"] if t["method"] == "Stage 1"]
    assert ran and ran[-1] is b and all(t["verdict"] == "NO-GO" for t in ran[:-1]) and log[0].startswith(f"flip search {GL}: {b['change']} (Stage 1)")
    assert [t["cost"] for t in ran] == sorted(t["cost"] for t in ran)                                             # nearest first


def test_stage_1_stops_after_k_candidates_and_when_the_budget_is_spent(monkeypatch):
    plan = plan_for(STORM)
    pri, marg = stage1.priors_for(STORM)
    base = {GL: dict(verdict="NO-GO", p_fail=1.0)}
    flips, _ = whatif.flip_search(STORM, base, {GL: TRACK}, ENV, {}, plan, pri, marg, None, 5, 1e6, lambda *_: None)
    f = flips[GL]
    assert len([t for t in f["tried"] if t["method"] == "Stage 1"]) == whatif.FALLBACK_K == 3 and not f["found"]
    assert f["best"] is None
    flips, spent = whatif.flip_search(STORM, base, {GL: TRACK}, ENV, {}, plan, pri, marg, None, 5, 0.0, log := [].append)
    t = flips[GL]["tried"]
    assert spent == 0.0 and not [x for x in t if x["method"] == "Stage 1"] and any("the emulator budget is spent" in x["reason"] for x in t) and log


def test_stage_1_runs_only_what_the_emulator_left(storm_em, monkeypatch):
    """The emulator answers the candidates in range; the out-of-range duty candidate is not enough to need Stage 1 when it already found a flip."""
    em, _ = storm_em
    pri, marg = stage1.priors_for(STORM)
    monkeypatch.setattr(whatif, "measure", lambda *a, **k: pytest.fail("Stage 1 must not run when the emulator found a flip"))
    flips, spent = whatif.flip_search(STORM, {GL: dict(verdict="NO-GO", p_fail=1.0)}, {GL: TRACK}, ENV, {"glider": (em, {})}, plan_for(STORM), pri, marg, None,
                                      5, 1e6,
                                      lambda *_: None)
    assert flips[GL]["found"] and spent == 0.0


def test_a_uas_flip_is_answered_without_a_median_track(tmp_path):
    """UAS rows use the ship and the sortie times, so no track is needed. The emulator here is fabricated to dislike late sorties."""
    rng = np.random.default_rng(1)
    rows = []
    for _ in range(120):
        mod = dict(shift_h=rng.uniform(-12, 12), dlon=rng.uniform(-0.5, 0.5), dlat=rng.uniform(-0.5, 0.5), duty=rng.uniform(0.5, 1.0))
        m2 = whatif.apply(CI, {"uas": mod})
        f = {**whatif.params(m2, "uas", "uas"), **whatif.env_stats(AnalyticEnv(), *whatif.uas_track(m2, "uas"))}
        p = float(np.clip(0.8 - 0.1 * (f["deploy_h"] - 7.0) + rng.normal(0, 0.02), 0, 1))
        rows.append(dict(f, p_fail=p, t_fail_h=10.0, cls="uas", n_members=512))
    em, info = whatif.fit_class(pd.DataFrame(rows), "uas", tmp_path / "t.parquet")
    assert em is not None
    flips, _ = whatif.flip_search(CI, {"uas": dict(verdict="NO-GO", p_fail=0.8)}, {}, AnalyticEnv(), {"uas": (em, info)}, plan_for(CI), {}, {}, None, 5, 0.0,
                                  lambda *_: None)
    b = flips["uas"]["best"]
    assert b["method"] == "EMULATED" and b["change"].startswith("launch the sorties") and b["change"].endswith("h later") and b["verdict"] != "NO-GO"


def test_measure_is_one_batch_of_one_vehicle_on_the_base_members():
    pri, marg = stage1.priors_for(STORM)
    a = whatif.measure(STORM, GL, ENV, plan_for(STORM, 8), pri, marg, None, 5)
    # 7 of 8 lose station: the eighth member draws the weakest current (0.69 x 0.6 m/s); the SDE moves position only, so it no longer adds speed
    assert a["n"] == 8 and a["p_fail"] >= 0.75 and a["verdict"] == "NO-GO" and a["lo"] > 0.5
    assert whatif.measure(STORM, GL, ENV, plan_for(STORM, 8), pri, marg, None, 5, n=4)["n"] == 4
    later = whatif.measure(whatif.apply(STORM, {GL: dict(shift_h=24)}), GL, ENV, plan_for(STORM), pri, marg, None, 5)
    assert later["p_fail"] == 0.0 and later["verdict"] == "GO"                                                    # the planted flip, measured


# ---------------------------------------------------------------------------------------------------------------- a change that leaves the environment data

class EdgeEnv(StormEnv):
    """The same storm in a box that ends at 165.3 W: a query east of it raises OutsideData, as GriddedEnv does outside its cache."""

    def wind(self, lon, lat, z, t):
        if np.any(np.asarray(lon) > -165.3):
            raise OutsideData("wind: (-164.50, 0.00) at 2023-03-01 18:00Z is outside the cached data")
        return super().wind(lon, lat, z, t)


def test_a_change_whose_track_leaves_the_data_is_invalid_not_a_crash(storm_em):
    em, _ = storm_em
    m2 = whatif.apply(STORM, {GL: dict(dlon=0.4)})  # the deploy point itself is inside the mission box
    with pytest.raises(whatif.Invalid, match=f"{GL}: the changed track leaves the environment data .*outside the cached data"):
        whatif.predict(em, m2, GL, "glider", TRACK, dict(dlon=0.4), EdgeEnv(T0 + 20 * 3600.0))
    assert whatif.predict(em, STORM, GL, "glider", TRACK, dict(shift_h=24.0), EdgeEnv(T0 + 20 * 3600.0))["status"] in ("ok", "out_of_range")


def test_the_flip_search_marks_a_candidate_that_leaves_the_data_and_goes_on(storm_em):
    em, _ = storm_em
    pri, marg = stage1.priors_for(STORM)
    flips, _ = whatif.flip_search(STORM, {GL: dict(verdict="NO-GO", p_fail=0.9)}, {GL: TRACK}, EdgeEnv(T0 + 20 * 3600.0), {"glider": (em, {})},
                                  plan_for(STORM), pri, marg, None, 5, 1e6, lambda *_: None)
    f = flips[GL]
    off = [t for t in f["tried"] if "leaves the environment data" in t["reason"]]
    assert off and all(t["method"] == "not evaluated" and "p_fail" not in t for t in off) and any("east" in t["change"] for t in off)
    assert f["found"] and f["best"]["method"] == "EMULATED"                                                       # the 24 h shift stays inside the data


def test_stage_1_that_leaves_the_data_is_a_reason_on_the_candidate_and_costs_nothing(monkeypatch):
    def refuse(*a, **k):
        raise OutsideData("wind: (-171.20, 0.90) is outside the cached data")
    monkeypatch.setattr(stage1, "run_batch", refuse)
    pri, marg = stage1.priors_for(STORM)
    with pytest.raises(whatif.Invalid, match="the changed mission leaves the environment data"):
        whatif.measure(STORM, GL, ENV, plan_for(STORM, 8), pri, marg, None, 5)
    base = {GL: dict(verdict="NO-GO", p_fail=1.0)}
    flips, spent = whatif.flip_search(STORM, base, {GL: TRACK}, ENV, {}, plan_for(STORM), pri, marg, None, 5, 1e6, lambda *_: None)
    t = flips[GL]["tried"]
    assert spent == 0.0 and not flips[GL]["found"] and [x for x in t if "Stage 1 not run: " + GL in x["reason"]]
    assert all(x["method"] == "not evaluated" for x in t)


def test_the_flip_search_charges_each_stage_1_fallback_at_the_planners_cost_not_the_clock(monkeypatch):
    plan = plan_for(STORM)
    cost = budget.batch_cost_s(plan, [GL])
    pri, marg = stage1.priors_for(STORM)
    monkeypatch.setattr(whatif, "measure", lambda *a, **k: dict(p_fail=1.0, lo=0.9, hi=1.0, verdict="NO-GO", n=16))
    clock = iter(range(0, 10 ** 6, 1000))                                                                          # a clock that jumps 1000 s per reading
    monkeypatch.setattr(whatif.time, "time", lambda: next(clock))
    base = {GL: dict(verdict="NO-GO", p_fail=1.0)}
    flips, spent = whatif.flip_search(STORM, base, {GL: TRACK}, ENV, {}, plan, pri, marg, None, 5, 10 * cost, lambda *_: None)
    assert spent == whatif.FALLBACK_K * cost and len([t for t in flips[GL]["tried"] if t["method"] == "Stage 1"]) == 3
    flips, spent = whatif.flip_search(STORM, base, {GL: TRACK}, ENV, {}, plan, pri, marg, None, 5, 2.5 * cost, lambda *_: None)
    assert spent == 2 * cost  # a third would pass the budget: the same on a slow machine


# ---------------------------------------------------------------------------------------------------------------- the what-if answer

BASE = {GL: dict(verdict="NO-GO", p_fail=1.0)}


def ask(ops, ems, base=BASE, tracks=None, plan=None, **kw):
    return whatif.answer(STORM, ops, base, {GL: TRACK} if tracks is None else tracks, ENV, ems, plan or plan_for(STORM), None, None, **kw)


def test_an_emulated_what_if_carries_the_distance_and_the_interval(storm_em):
    em, info = storm_em
    r = ask(dict(shift_h=24.0), {"glider": (em, info)})["vehicles"][GL]
    assert r["method"] == "EMULATED" and r["verdict"] == "GO" and r["p_fail"] < 0.1 and r["lo"] <= r["p_fail"] <= r["hi"] and r["distance"] <= r["threshold"]
    assert r["base"] == BASE[GL]
    now = ask(dict(shift_h=6.0), {"glider": (em, info)})["vehicles"][GL]
    assert now["method"] == "EMULATED" and now["verdict"] == "NO-GO"


def test_the_what_if_falls_back_to_stage_1_out_of_range_and_says_why(storm_em):
    em, info = storm_em
    r = ask(dict(shift_h=24.0, dlon=-0.5), {"glider": (em, info)}, tracks={})["vehicles"][GL]
    assert r["method"] == "Stage 1" and r["why"] == "no track" and r["n"] == 16 and r["verdict"] == "GO" and r["p_fail"] == 0.0
    r = ask(dict(shift_h=24.0), {})["vehicles"][GL]
    assert r["method"] == "Stage 1" and r["why"] == "no emulator" and r["verdict"] == "GO" and r["lo"] == 0.0 and r["hi"] < 0.2
    far = whatif.apply(STORM, {GL: dict(shift_h=24.0)})
    far_ops = dict(shift_h=24.0)
    far_plan = plan_for(far)
    em2 = copy.copy(em)
    em2.threshold = 0.0
    out = ask(far_ops, {"glider": (em2, info)}, plan=far_plan)["vehicles"][GL]
    assert out["why"] == "out of range" and out["method"] == "Stage 1"


def test_a_vehicle_without_a_baseline_is_measured_first():
    r = ask(dict(shift_h=24.0), {}, base={})["vehicles"][GL]
    assert r["base"]["verdict"] == "NO-GO" and r["base"]["p_fail"] >= 0.9 and r["verdict"] == "GO"


def test_dropping_a_vehicle_needs_no_run_and_names_the_links_that_go():
    m = copy.deepcopy(CI)
    r = whatif.answer(m, dict(drop=["glider_eq"]), {}, {}, ENV, {}, plan_for(m), None, None)
    assert r["dropped"] == ["glider_eq"] and r["links_removed"] == ["glider_eq-ship-acoustic"]
    assert r["vehicles"] == {}                                                                                    # nothing else changed: nothing to run


def test_a_change_can_be_limited_to_named_vehicles():
    m = whatif.apply(CI, drop=["uas"])                                  # a mission with a glider and a USV; only the glider is shifted
    base = {"usv": dict(verdict="GO", p_fail=0.0), GL: dict(verdict="GO", p_fail=0.0)}
    r = whatif.answer(m, dict(shift_h=6.0), base, {GL: TRACK}, ENV, {}, plan_for(m), None, None, only=[GL])
    assert set(r["vehicles"]) == {GL} and r["vehicles"][GL]["method"] == "Stage 1" and r["links_removed"] == []
    with pytest.raises(whatif.Invalid, match="no vehicle 'nope'"):
        ask(dict(shift_h=1.0), {}, only=["nope"])
    with pytest.raises(whatif.Invalid, match="outside the window"):
        ask(dict(shift_h=-6.0), {})


# ---------------------------------------------------------------------------------------------------------------- the training table the pipeline fits on

def test_with_rows_adds_replaces_by_key_and_copes_with_an_empty_side():
    df = pd.DataFrame([dict(key="a", v=1), dict(key="b", v=2)])
    assert whatif.with_rows(df, []) is df
    out = whatif.with_rows(df, [dict(key="b", v=20), dict(key="c", v=3)])
    assert out.to_dict("records") == [dict(key="a", v=1), dict(key="b", v=20), dict(key="c", v=3)]
    assert whatif.with_rows(pd.DataFrame(columns=["key", "v"]), [dict(key="x", v=9)]).to_dict("records") == [dict(key="x", v=9)]
    assert list(whatif.with_rows(pd.DataFrame([dict(v=1)]), [dict(key="x", v=9)])["v"]) == [1, 9]                                  # a table with no keys


def test_snapshot_copies_the_table_without_the_runs_own_rows_and_an_absent_table_is_an_empty_one(tmp_path):
    empty, out = whatif.snapshot(tmp_path / "none.parquet", tmp_path / "s" / "train_input", "r1")
    assert len(empty) == 0 and out.exists() and len(whatif.read_table(out)) == 0
    whatif.add_rows(tmp_path / "t.parquet", [dict(key="r1|a", run_id="r1", cls="glider"), dict(key="r2|a", run_id="r2", cls="glider")])
    df, out = whatif.snapshot(tmp_path / "t.parquet", tmp_path / "s" / "train_input", "r1")
    assert list(df["key"]) == ["r2|a"] and list(whatif.read_table(out)["key"]) == ["r2|a"]
    assert len(whatif.read_table(tmp_path / "t.parquet")) == 2                                      # the shared table itself is not touched
