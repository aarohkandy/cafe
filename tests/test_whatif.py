"""cafe.pm.whatif: mission changes, training rows, the per-class emulators, the flip search and the what-if answer.

Stage 1 runs for real on a fake environment where the answer is known (a storm current that stops 20 h into the window, so that deploying
24 h later avoids it); the emulators are fitted on tables fabricated from the same rule, which is test data only.
"""
import copy
import math
import re
import threading
import time

import numpy as np
import pandas as pd
import pytest

from cafe.pm import Tagged, budget, config, par, stage1, whatif
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


def synthetic_rows(variant="base", fid=None, meta=META):
    res, _ = pm_run.make_res(seed=1, fail_frac=0.4, M=48)
    return whatif.vehicle_rows(DEMO, res, AnalyticEnv(wind=(3.0, 4.0), hs=2.0, current=(0.1, 0.0)), fid or {}, meta, variant)


def test_one_row_per_vehicle_with_features_targets_and_metadata():
    rows = synthetic_rows(fid={"glider_eq": 1})
    assert [r["vehicle"] for r in rows] == ["glider_eq", "glider_2n", "usv", "uas"] and [r["cls"] for r in rows] == ["glider", "glider", "usv", "uas"]
    g, u = rows[0], rows[3]
    assert g["fidelity"] == 1 and rows[1]["fidelity"] == 0 and g["n_members"] == 48 and g["key"] == whatif.row_key(g)
    assert g["run_id"] == "r1" and g["mission"] == "demo" and g["git_sha"] == "abc" and g["code_digest"] == "def" and g["variant"] == "base"
    assert g["wind_mean"] == pytest.approx(5.0) and g["hs_p90"] == 2.0 and g["cur_mean"] == pytest.approx(0.1)
    assert g["dive_depth_m"] == 950.0 and u["every_days"] == 1.0 and "dive_depth_m" not in u
    assert 0.0 < g["p_fail"] < 1.0 and g["mode_station_lost"] == g["p_fail"]


def test_rows_append_and_a_rerun_of_the_same_mission_replaces_its_rows_whichever_directory_it_ran_in(tmp_path):
    """M-8: the key held the run directory, so every rerun of one mission counted as new data with identical features."""
    path = tmp_path / "emulator" / "train.parquet"
    a, used = whatif.add_rows(path, synthetic_rows())
    assert used == str(path) and len(a) == 4 and path.is_file()
    b, _ = whatif.add_rows(path, synthetic_rows("v0"))
    assert len(b) == 8 and sorted(b["variant"].unique()) == ["base", "v0"]
    rerun = synthetic_rows(meta=dict(META, run_id="r2", git_sha="new", code_digest="newer"))
    again, _ = whatif.add_rows(path, rerun)
    assert len(again) == 8 and again[again["variant"] == "base"]["run_id"].tolist() == ["r2"] * 4
    assert again[again["variant"] == "v0"]["run_id"].tolist() == ["r1"] * 4
    other_mission, _ = whatif.add_rows(path, synthetic_rows(meta=dict(META, mission="other")))
    assert len(other_mission) == 12


def test_a_row_key_ignores_the_run_and_the_code_and_follows_the_mission_vehicle_variant_and_features():
    r = synthetic_rows()[0]
    key = whatif.row_key(r)
    assert len(key) == 16 and int(key, 16) >= 0 and whatif.row_key(dict(r, run_id="r9", git_sha="z", code_digest="z", p_fail=0.123)) == key
    assert whatif.row_key(dict(r, lon=r["lon"] + 1e-12)) == key                                           # 9 significant digits
    for change in (dict(mission="other"), dict(vehicle="glider_2n"), dict(variant="v0"), dict(lon=r["lon"] + 1e-3), dict(dive_depth_m=r["dive_depth_m"] + 1)):
        assert whatif.row_key(dict(r, **change)) != key, change


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
    ds = {d[k]["uas"]["duty"] for k in range(4)}
    assert ds <= {1.0, 0.5} and len({whatif.vehicle(whatif.apply(CI, d[k]), "uas")["sorties"]["every_days"] for k in range(4)}) <= 2   # M-24: whole-day periods


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
    # on 28 held-out points the +-0.05 gate passes 24, 25 or 26 hits; a calibrated emulator (hits ~ Binomial(28, 0.9)) misses it the rest of the time
    passes = sum(math.comb(28, k) * 0.9 ** k * 0.1 ** (28 - k) for k in (24, 25, 26))
    assert info["coverage_chance_fail"] == pytest.approx(1 - passes, rel=1e-9) and 0.3 < info["coverage_chance_fail"] < 0.5


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
    whatif.add_rows(path, [dict(r, key=f"k{i}", run_id="r", code_digest="d1") for i, r in enumerate(storm_table(120).to_dict("records"))])
    out = whatif.train(path, ["glider", "usv"], code_digest="d1")
    assert out["glider"][0] is not None and out["glider"][1]["trained"] and out["usv"][0] is None
    out = whatif.train(path, ["glider"], code_digest="d2")
    assert out["glider"][0] is None and out["glider"][1]["stale_rows"] == 120 and "; 120 rows made by other code are left out" in out["glider"][1]["reason"]


def test_train_defaults_to_the_digest_of_this_checkouts_code(tmp_path):
    from cafe.pm import pipeline
    df = storm_table(120).assign(code_digest=pipeline.code_digest())
    assert whatif.train(tmp_path / "none.parquet", ["glider"], df=df)["glider"][1]["trained"]
    assert not whatif.train(tmp_path / "none.parquet", ["glider"], df=df.assign(code_digest="superseded"))["glider"][1]["trained"]


def test_replicates_of_one_mission_do_not_reach_the_row_gate(tmp_path):
    """M-8: 25 reruns of the demo reached 100 rows with one design point."""
    df = pd.concat([storm_table(30)] * 5, ignore_index=True)
    em, info = whatif.fit_class(df, "glider", tmp_path / "t.parquet")
    assert em is None and info["rows"] == 150 and info["points"] == 30
    assert info["reason"] == ("150 glider rows in the training table, 100 are needed (a 20 % hold-out must score 90 % coverage); "
                              "only 30 of them are distinct feature points")


def test_rows_made_by_other_code_stay_in_the_table_but_are_not_trained_on(tmp_path):
    """M-8: rows from superseded physics were trained on; the table keeps them, the fit leaves them out."""
    df = storm_table(140).assign(code_digest="old")
    df.loc[:119, "code_digest"] = "new"
    em, info = whatif.fit_class(df, "glider", tmp_path / "t.parquet", "new")
    assert em is not None and info["trained"]
    assert info["rows"] == 120 and info["stale_rows"] == 20 and info["points"] == 120
    em, info = whatif.fit_class(df.iloc[:30], "glider", tmp_path / "t.parquet", "new")
    assert em is None and info["reason"].startswith("30 glider rows in the training table, 100 are needed")
    em, info = whatif.fit_class(df.iloc[120:], "glider", tmp_path / "t.parquet", "new")
    assert em is None and info["rows"] == 0 and info["stale_rows"] == 20 and "; 20 rows made by other code are left out" in info["reason"]
    em, info = whatif.fit_class(df.drop(columns="code_digest"), "glider", tmp_path / "t.parquet", "new")
    assert em is None and info["rows"] == 0 and info["stale_rows"] == 140                             # no digest: not shown to be current
    em, info = whatif.fit_class(df.drop(columns="code_digest"), "glider", tmp_path / "t.parquet")
    assert info["rows"] == 140 and info["stale_rows"] == 0


# ---------------------------------------------------------------------------------------------------------------- the flip search

def test_candidates_are_single_changes_in_cost_order():
    c = whatif.candidates(CI, GL)
    assert [x["cost"] for x in c] == sorted(x["cost"] for x in c) and len(c) == 8 + 8 + 2
    assert {x["change"] for x in c} >= {"deploy 6 h later", "deploy 48 h earlier", "move 0.5 deg west", "move 1 deg north",
                                        "dive 25 % shallower (950 m to 712.5 m)"}
    assert next(x for x in c if x["change"] == "deploy 24 h later")["cost"] == 4.0 and next(x for x in c if x["change"] == "move 1 deg east")["cost"] == 2.0
    assert len(whatif.candidates(CI, "usv")) == 16 and len(whatif.candidates(CI, "uas")) == 14
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
    first = whatif.params(CI, "uas", "uas")["deploy_h"]                                   # P(fail) 0.8 at the baseline, 0.2 six hours later
    for _ in range(120):
        mod = dict(shift_h=rng.uniform(-12, 12), dlon=rng.uniform(-0.5, 0.5), dlat=rng.uniform(-0.5, 0.5), duty=float(rng.choice([1.0, 0.5])))
        m2 = whatif.apply(CI, {"uas": mod})
        f = {**whatif.params(m2, "uas", "uas"), **whatif.env_stats(AnalyticEnv(), *whatif.uas_track(m2, "uas"))}
        p = float(np.clip(0.8 - 0.1 * (f["deploy_h"] - first) + rng.normal(0, 0.02), 0, 1))
        rows.append(dict(f, p_fail=p, t_fail_h=10.0, cls="uas", n_members=512))
    em, info = whatif.fit_class(pd.DataFrame(rows), "uas", tmp_path / "t.parquet")
    assert em is not None
    flips, _ = whatif.flip_search(CI, {"uas": dict(verdict="NO-GO", p_fail=0.8)}, {}, AnalyticEnv(), {"uas": (em, info)}, plan_for(CI), {}, {}, None, 5, 0.0,
                                  lambda *_: None)
    b = flips["uas"]["best"]
    assert b["method"] == "EMULATED" and b["verdict"] != "NO-GO" and b["change"] == "launch the sorties 6 h later"
    # M-24: a whole day is the same time of day, not a candidate
    assert not [t for t in flips["uas"]["tried"] if "24 h" in t["change"] or "48 h" in t["change"]]


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
    # past the data: it can never be evaluated
    assert all(x["invalid"] for x in t if "Stage 1 not run: " + GL in x["reason"]) and flips[GL]["evaluated"] == 0


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


def two_glider_mission(hours=60):
    m = copy.deepcopy(CI)
    m["window"]["end"] = whatif._iso(T0 + 3600.0 * hours)
    m["vehicles"] = [v for v in m["vehicles"] if v["id"] in ("glider_eq", "glider_1n")]
    m["links"] = []
    return m


def test_the_stage_1_budget_is_split_over_the_vehicles_not_spent_on_the_first(monkeypatch):
    """M-6: glider_eq spent the whole share, so the vehicles after it got no Stage-1 fallback and were reported as 'nothing flips it'."""
    m = two_glider_mission()
    plan = plan_for(m)
    cost = budget.batch_cost_s(plan, ["glider_eq"])
    assert budget.batch_cost_s(plan, ["glider_1n"]) == cost
    pri, marg = stage1.priors_for(m)
    monkeypatch.setattr(whatif, "measure", lambda *a, **k: dict(p_fail=1.0, lo=0.9, hi=1.0, verdict="NO-GO", n=16))
    base = {v: dict(verdict="NO-GO", p_fail=1.0) for v in ("glider_eq", "glider_1n")}
    log = []
    flips, spent = whatif.flip_search(m, base, {}, ENV, {}, plan, pri, marg, None, 5, 2.5 * cost, log.append)
    assert [flips[v]["evaluated"] for v in base] == [1, 1] and spent == 2 * cost
    for v in base:
        f = flips[v]
        assert sum(t["method"] == "Stage 1" for t in f["tried"]) == 1
        assert any("this vehicle's share of the emulator budget is spent" in t["reason"] for t in f["tried"])
    assert log[-1] == f"flip search glider_1n: nothing flips it among the 1 evaluated of {flips['glider_1n']['candidates']} candidates"
    flips, spent = whatif.flip_search(m, base, {}, ENV, {}, plan, pri, marg, None, 5, 0.9 * cost, lambda *_: None)
    assert [flips[v]["evaluated"] for v in base] == [0, 0] and spent == 0.0                                 # neither gets what it cannot afford
    only = {"glider_eq": base["glider_eq"], "glider_1n": dict(verdict="GO", p_fail=0.0)}
    flips, spent = whatif.flip_search(m, only, {}, ENV, {}, plan, pri, marg, None, 5, 2.5 * cost, lambda *_: None)
    assert list(flips) == ["glider_eq"] and flips["glider_eq"]["evaluated"] == 2 and spent == 2 * cost       # a GO vehicle takes no share


def test_the_search_counts_what_was_evaluated_and_what_could_never_be(monkeypatch):
    """M-6: the report counted every candidate, the 'earlier' ones that fall before the window included, and never said how many were run."""
    pri, marg = stage1.priors_for(STORM)
    plan = plan_for(STORM)
    flips, _ = whatif.flip_search(STORM, {GL: dict(verdict="NO-GO", p_fail=1.0)}, {GL: TRACK}, ENV, {}, plan, pri, marg, None, 5, 1e6, lambda *_: None)
    f = flips[GL]
    invalid = [t for t in f["tried"] if t["invalid"]]
    assert f["evaluated"] == 3 and f["invalid"] == len(invalid) > 0 and f["candidates"] == len(f["tried"]) - len(invalid)
    assert all(t["method"] == "not evaluated" and "outside the window" in t["reason"] for t in invalid)
    assert not any(t["invalid"] for t in f["tried"] if t["method"] != "not evaluated")
    assert f["evaluated"] <= f["candidates"]


def test_a_search_with_nothing_run_says_so_in_its_log_line(monkeypatch):
    pri, marg = stage1.priors_for(STORM)
    log = []
    flips, _ = whatif.flip_search(STORM, {GL: dict(verdict="NO-GO", p_fail=1.0)}, {GL: TRACK}, ENV, {}, plan_for(STORM), pri, marg, None, 5, 0.0, log.append)
    f = flips[GL]
    assert f["evaluated"] == 0 and log == [f"flip search {GL}: nothing flips it among the 0 evaluated of {f['candidates']} candidates"]


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


MISSED = "the glider emulator missed BRIEF 2.7 acceptance (coverage), so Stage 1 answers"


def test_an_emulator_that_missed_the_acceptance_does_not_answer_the_what_if_and_stage_1_does(storm_em):
    """Follow-up to round 4 M-3: `used: False` in the class's info means no emulator for the answer, and the reason names the gate."""
    em, info = storm_em
    missed = dict(info, used=False, unused_reason=MISSED)
    r = ask(dict(shift_h=24.0), {"glider": (em, missed)})["vehicles"][GL]
    assert r["method"] == "Stage 1" and r["why"] == MISSED and r["verdict"] == "GO" and r["n"] == 16
    assert ask(dict(shift_h=24.0), {"glider": (em, dict(info, used=True))})["vehicles"][GL]["method"] == "EMULATED"
    assert ask(dict(shift_h=24.0), {"glider": (em, info)})["vehicles"][GL]["method"] == "EMULATED"          # an info without the key (older code) still answers


def test_an_emulator_that_missed_the_acceptance_does_not_answer_the_flip_search_and_stage_1_does(storm_em, monkeypatch):
    em, info = storm_em
    monkeypatch.setattr(whatif, "FALLBACK_K", 20)
    pri, marg = stage1.priors_for(STORM)
    ems = {"glider": (em, dict(info, used=False, unused_reason=MISSED))}
    flips, spent = whatif.flip_search(STORM, {GL: dict(verdict="NO-GO", p_fail=1.0)}, {GL: TRACK}, ENV, ems, plan_for(STORM), pri, marg, None, 5, 1e6,
                                      lambda *_: None)
    f = flips[GL]
    assert f["found"] and not f["emulator"] and spent > 0.0 and f["best"]["method"] == "Stage 1"
    assert not [t for t in f["tried"] if t["method"] == "EMULATED"] and MISSED in {t["reason"].split(";")[0] for t in f["tried"]}


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


# ---------------------------------------------------------------------------------------------------------------- review round 2, batch D

def test_the_emulator_gate_is_the_budgets_minimum_not_a_number_of_its_own(monkeypatch):
    """M-7: the gate and the planner that sizes the variants read one constant. Never lowered to make a run train."""
    import importlib
    assert whatif.MIN_ROWS == budget.EMULATOR_MIN_POINTS == 100
    monkeypatch.setattr(budget, "EMULATOR_MIN_POINTS", 7)
    try:
        assert importlib.reload(whatif).MIN_ROWS == 7
    finally:
        monkeypatch.undo()
        importlib.reload(whatif)
    assert whatif.MIN_ROWS == 100


@pytest.mark.parametrize("h", [24.0, -24.0, 48.0, 72.0])
def test_a_uas_shift_by_whole_days_is_refused_as_the_same_launch_time(h):
    """M-24: shifts of +-24 and +-48 h left local_solar_time unchanged: four of 16 candidates were the baseline, evaluated and priced as changes."""
    with pytest.raises(whatif.Invalid, match=r"uas: launching \+?-?\d+ h later is a whole number of days, the same launch time of day"):
        whatif.apply(CI, {"uas": dict(shift_h=h)})
    assert whatif.apply(CI, {"uas": dict(shift_h=25.0)})["vehicles"][3]["sorties"]["local_solar_time"] != CI["vehicles"][3]["sorties"]["local_solar_time"]
    assert whatif.apply(CI, {GL: dict(shift_h=24.0)})                                    # a glider deploys 24 h later: a real change


def test_the_uas_candidates_leave_out_whole_day_shifts_and_the_others_keep_them():
    uas = [c["change"] for c in whatif.candidates(CI, "uas")]
    assert not [c for c in uas if "24 h" in c or "48 h" in c] and "launch the sorties 12 h later" in uas
    for c in whatif.candidates(CI, "uas"):
        whatif.apply(CI, {"uas": c["mod"]})                                              # none of them is invalid for being the baseline
    assert "deploy 48 h earlier" in [c["change"] for c in whatif.candidates(CI, GL)]


def test_a_lower_uas_duty_rounds_the_period_up_to_whole_days_and_says_so():
    """M-24: every 1.3333 d launched at 08:59Z, 16:59Z, 00:59Z, not at the mission's time of day."""
    m = whatif.apply(CI, {"uas": dict(duty=0.75)})
    assert whatif.vehicle(m, "uas")["sorties"]["every_days"] == 2.0
    v = whatif.vehicle(CI, "uas")
    assert whatif.describe(dict(duty=0.75), v) == "fly sorties every 2 d instead of 1 (rounded up to whole days)"
    assert whatif.describe(dict(duty=0.5), v) == "fly sorties every 2 d instead of 1"
    assert [c["change"] for c in whatif.candidates(CI, "uas") if "sorties every" in c["change"]] == [
        "fly sorties every 2 d instead of 1 (rounded up to whole days)", "fly sorties every 2 d instead of 1"]
    assert whatif._duty_days(0.5, 0.75) == pytest.approx(2 / 3) and whatif._duty_days(1.0, 1.0) == 1.0 and whatif._duty_days(3.0, 0.75) == 4.0


class Env3D(AnalyticEnv):
    """An environment with the 3-D wind switch (GriddedEnv.use_3d), recording its state at every Stage-1 batch."""

    def __init__(self):
        super().__init__()
        self.use_3d = True
        self.seen = []


def stub_batch(monkeypatch, env, p_fail=1.0):
    def run_batch(mission, e, members, seed, pri, marg, scales):
        env.seen.append(getattr(e, "use_3d", None))
        n = len(members)
        fail = np.arange(n) < round(p_fail * n)
        return dict(vehicles={v["id"]: dict(fail=dict(x=fail), lon=np.zeros((2, n)), **{"class": "uas"}) for v in mission["vehicles"]})
    monkeypatch.setattr(stage1, "run_batch", run_batch)


def test_a_uas_measure_runs_without_the_3d_wind_and_restores_it(monkeypatch):
    """M-6: the baseline sorties fly in ingested 3-D hours, a shifted one does not: both sides of a UAS comparison use the 10 m profile."""
    env = Env3D()
    stub_batch(monkeypatch, env)
    pri, marg = stage1.priors_for(CI)
    whatif.measure(CI, "uas", env, plan_for(CI, 4), pri, marg, None, 5)
    whatif.measure(CI, GL, env, plan_for(CI, 4), pri, marg, None, 5)
    assert env.seen == [False, True] and env.use_3d is True                      # only the UAS run is 10 m profile; the state is restored
    with whatif.wind_2d(AnalyticEnv(), "uas"):                                    # an environment without the switch is left alone
        pass
    with pytest.raises(RuntimeError), whatif.wind_2d(env, "uas"):
        assert env.use_3d is False
        raise RuntimeError("boom")
    assert env.use_3d is True


def test_the_variants_with_a_uas_run_in_the_10_m_profile_and_those_without_do_not(monkeypatch):
    env = Env3D()
    stub_batch(monkeypatch, env)
    monkeypatch.setattr(whatif, "vehicle_rows", lambda *a, **k: [])
    pri, marg = stage1.priors_for(CI)
    whatif.run_variant(CI, env, [0, 1], 5, pri, marg, None, {}, {}, "v0")
    whatif.run_variant(STORM, env, [0, 1], 5, pri, marg, None, {}, {}, "v1")
    assert env.seen == [False, True] and env.use_3d is True


def test_the_uas_flip_search_measures_its_baseline_as_it_measures_the_candidates(monkeypatch):
    env = Env3D()
    stub_batch(monkeypatch, env, p_fail=0.75)
    plan = plan_for(CI, 4)
    cost = budget.batch_cost_s(plan, ["uas"])
    base = {"uas": dict(verdict="NO-GO", p_fail=0.8)}
    flips, spent = whatif.flip_search(CI, base, {}, env, {}, plan, {}, {}, None, 5, 10 * cost, lambda *_: None)
    f = flips["uas"]
    assert f["wind_model"] == whatif.WIND_MODEL_2D and f["base_2d"]["p_fail"] == 0.75 and f["base_2d"]["verdict"] == "NO-GO"
    assert env.seen and not any(env.seen) and env.use_3d is True and spent == (whatif.FALLBACK_K + 1) * cost
    # the candidates come first: a share that covers only them leaves the baseline unmeasured, and the statement stays
    env.seen.clear()
    flips, spent = whatif.flip_search(CI, base, {}, env, {}, plan, {}, {}, None, 5, 3.5 * cost, lambda *_: None)
    assert flips["uas"]["base_2d"] is None and flips["uas"]["wind_model"] == whatif.WIND_MODEL_2D and spent == 3 * cost
    flips, _ = whatif.flip_search(CI, base, {}, AnalyticEnv(), {}, plan, {}, {}, None, 5, 10 * cost, lambda *_: None)      # no switch: no claim
    assert flips["uas"]["wind_model"] is None and flips["uas"]["base_2d"] is None


def test_a_baseline_that_leaves_the_data_is_no_number_not_a_crash(monkeypatch):
    env = Env3D()
    stub_batch(monkeypatch, env)
    plan = plan_for(CI, 4)
    n = {"k": 0}
    real = whatif.measure

    def measure(*a, **k):
        n["k"] += 1
        if n["k"] > whatif.FALLBACK_K:                                                    # the baseline comes after the candidates
            raise whatif.Invalid("uas: the changed mission leaves the environment data")
        return real(*a, **k)
    monkeypatch.setattr(whatif, "measure", measure)
    flips, _ = whatif.flip_search(CI, {"uas": dict(verdict="NO-GO", p_fail=0.8)}, {}, env, {}, plan, {}, {}, None, 5, 100 * budget.batch_cost_s(plan, ["uas"]),
                                  lambda *_: None)
    assert flips["uas"]["base_2d"] is None and flips["uas"]["wind_model"] == whatif.WIND_MODEL_2D


def test_the_stage_1_fallback_answer_of_a_uas_runs_in_the_10_m_profile(monkeypatch):
    env = Env3D()
    seen = []
    monkeypatch.setattr(stage1, "run", lambda *a, **k: (seen.append(env.use_3d), dict(summary=dict(vehicles=dict(uas=dict(
        verdict=dict(p_fail=0.1, fail_lo=0.0, fail_hi=0.2, verdict="MARGINAL"), n=16)))))[1])
    assert whatif._stage1(CI, "uas", env, plan_for(CI), None, None)["verdict"] == "MARGINAL" and seen == [False] and env.use_3d is True


def test_a_variant_that_leaves_the_data_is_rerun_one_vehicle_at_a_time_and_the_others_keep_their_rows(monkeypatch):
    env = Env3D()

    def run_batch(mission, e, members, seed, pri, marg, scales):
        env.seen.append(e.use_3d)
        if len(mission["vehicles"]) > 1 or mission["vehicles"][0]["id"] == "usv":
            raise OutsideData("wind: outside the cached data")
        return dict(vehicles={mission["vehicles"][0]["id"]: None})
    monkeypatch.setattr(stage1, "run_batch", run_batch)
    monkeypatch.setattr(whatif, "vehicle_rows", lambda m, res, *a: [dict(vehicle=v) for v in res["vehicles"]])
    pri, marg = stage1.priors_for(CI)
    rows, skipped = whatif.run_variant(CI, env, [0, 1], 5, pri, marg, None, {}, {}, "v0")
    assert {r["vehicle"] for r in rows} == {v["id"] for v in CI["vehicles"]} - {"usv"} and list(skipped) == ["usv"]
    assert "the variant leaves the environment data" in skipped["usv"] and env.use_3d is True
    assert env.seen[0] is False and False in env.seen and True in env.seen          # the UAS alone ran without the 3-D wind, the glider with it


def test_a_variant_rerun_one_vehicle_at_a_time_runs_the_others_at_once_on_workers_in_mission_order(monkeypatch):
    """On 8 workers the quick demo's two variants that left the data took 102 s each, one solo batch after another; the solo batches of the
    vehicles other than the UAS are independent and now run at once (the UAS first and alone: wind_2d switches the shared environment)."""
    env, lock, live, peak = Env3D(), threading.Lock(), [0], [0]

    def run_batch(mission, e, members, seed, pri, marg, scales):
        if len(mission["vehicles"]) > 1:
            raise OutsideData("wind: outside the cached data")
        with lock:
            live[0] += 1
            peak[0] = max(peak[0], live[0])
        time.sleep(0.2)
        with lock:
            live[0] -= 1
        return dict(vehicles={mission["vehicles"][0]["id"]: None})
    monkeypatch.setattr(stage1, "run_batch", run_batch)
    monkeypatch.setattr(whatif, "vehicle_rows", lambda m, res, *a: [dict(vehicle=v) for v in res["vehicles"]])
    pri, marg = stage1.priors_for(CI)
    with par.Pool(2):
        rows, skipped = whatif.run_variant(CI, env, [0, 1], 5, pri, marg, None, {}, {}, "v0")
    assert [r["vehicle"] for r in rows] == [v["id"] for v in CI["vehicles"]] and not skipped and peak[0] == 2 and env.use_3d is True


# ---------------------------------------------------------------------------------------------------------------- review round 3: M-4

FEATS = whatif.BASE + whatif.TASK["glider"]


def known_p_table(n=140, seed=0, members=16, shift=None):
    """Glider rows whose true P(fail) is the storm rule of `storm_table` (noise-free), observed as Binomial(members, p) / members with a fresh draw per row.
    `shift(df)` adds a smooth, deterministic function of the features to the observed value: what a draw shared by every training point looks like, since
    the same members give the same error at the same mission. -> (observed table, {feature key: true p})."""
    truth = storm_table(n, seed, noise=0.0)
    p = truth["p_fail"].to_numpy()
    rng = np.random.default_rng(100 + seed)
    obs = truth.assign(p_fail=rng.binomial(members, p) / members, n_members=members)
    if shift is not None:
        obs["p_fail"] = np.clip(obs["p_fail"] + shift(obs), 0.0, 1.0)
    return obs, {tuple(np.round(r, 9)): q for r, q in zip(truth[FEATS].to_numpy(), p, strict=True)}


def fresh_binomial(truth, members=16, seed=7):
    """A `fresh` draw: P(fail) of the same mission again on members nobody used, i.e. an independent Binomial(members, p_true) / members."""
    rng = np.random.default_rng(seed)
    return lambda row: (float(rng.binomial(members, truth[tuple(np.round(row[FEATS].to_numpy(float), 9))]) / members), members)


def test_with_independent_noise_the_debiased_rmse_is_the_error_against_the_truth_and_the_fresh_check_agrees(tmp_path):
    obs, truth = known_p_table()
    em, info = whatif.fit_class(obs, "glider", tmp_path / "t.parquet", fresh=fresh_binomial(truth))
    assert em is not None and info["fresh_points"] == 3 and info["fresh_n_members"] == 16
    new = storm_table(300, 99, noise=0.0)                                               # the error against the true P(fail) on missions the emulator never saw
    err = float(np.sqrt(np.mean((em.predict(new[em.features])["p_fail"]["value"] - new["p_fail"].to_numpy()) ** 2)))
    assert info["rmse_debiased"] == pytest.approx(err, abs=0.02)
    assert abs(info["rmse_fresh_debiased"] - info["rmse_debiased"]) < 0.08 and info["rmse_gate"] == max(info["rmse_debiased"], info["rmse_fresh_debiased"])
    assert info["acceptance"]["rmse_ok"] == bool(info["rmse_gate"] <= whatif.LIMITS["rmse"]) and "its own members" in info["draws"]


def test_when_the_training_targets_share_their_draws_the_fresh_check_reads_larger_than_the_in_sample_score(tmp_path):
    """Round 3 M-4: every variant ran members 0..batch-1, so the targets carry the same error at the same mission: smooth in the features, which the
    emulator learns, so the in-sample hold-out under-reads the error against the true P(fail). A re-draw on fresh members shows it."""
    shared = lambda d: 0.25 * (d["deploy_h"] / 45.0 - 0.5)                               # the error the shared members make, a smooth function of the mission
    # many members, so the targets' own noise is small beside the shared error
    obs, truth = known_p_table(members=256, shift=shared)
    em, info = whatif.fit_class(obs, "glider", tmp_path / "t.parquet", fresh=fresh_binomial(truth, members=256))
    assert info["fresh_points"] == 3
    assert info["rmse_fresh_debiased"] > info["rmse_debiased"] + 0.04, (info["rmse_fresh_debiased"], info["rmse_debiased"])
    assert info["rmse_gate"] == info["rmse_fresh_debiased"]
    ok = whatif.fit_class(obs, "glider", tmp_path / "t2.parquet")[1]
    # without the check, only the in-sample score is judged
    assert ok["fresh_points"] == 0 and "rmse_fresh_debiased" not in ok and ok["rmse_gate"] == ok["rmse_debiased"]


def test_the_coverage_gate_reads_the_calibration_scale_and_the_raw_p_number_is_reported_beside_it(tmp_path):
    """Round 4 M-3: about a quarter of 16-member P(fail) values are exactly 0 or 1, which no sigmoid interval contains, so the raw-P coverage of a
    calibrated emulator reads 0.71 here and the old gate (|coverage - 0.90| <= 0.05) rejected it; the conformal guarantee is on the clipped logit."""
    obs, _ = known_p_table()
    assert obs["p_fail"].isin([0.0, 1.0]).mean() > 0.2
    em, info = whatif.fit_class(obs, "glider", tmp_path / "t.parquet")
    raw = info["coverage_raw_p"]["p_fail"]
    assert set(info["coverage_raw_p"]) == {"p_fail"} and raw < 0.8 and info["coverage"]["p_fail"] > raw + 0.1
    assert abs(raw - info["nominal"]) > whatif.LIMITS["coverage"]                                       # the number the old gate used would have failed it
    assert info["acceptance"]["coverage_ok"] is True and abs(info["coverage"]["p_fail"] - info["nominal"]) <= whatif.LIMITS["coverage"]
    assert em.holdout["coverage_raw_p"] == info["coverage_raw_p"]


@pytest.mark.parametrize("content", [b"this is not parquet", b""], ids=["garbage", "zero bytes"])
def test_snapshot_of_a_corrupt_shared_table_is_a_config_error_naming_the_file_and_leaves_it_alone(tmp_path, content):
    """Round 4 M-23: the call raised pyarrow's ArrowInvalid; an absent table is still an empty one (test above)."""
    from cafe.pm.config import ConfigError
    t = tmp_path / "train.parquet"
    t.write_bytes(content)
    with pytest.raises(ConfigError, match=f"training table {t} cannot be read"):
        whatif.snapshot(t, tmp_path / "s" / "train_input", "r1")
    with pytest.raises(ConfigError, match="cannot be read"):
        whatif.train(t, ["glider"])
    assert t.read_bytes() == content


def test_the_fresh_check_skips_rows_it_cannot_re_run_and_stops_at_three(tmp_path):
    obs, truth = known_p_table()
    seen = []

    def fresh(row):
        seen.append(row["deploy_h"])
        return None if len(seen) % 2 else (0.5, 16)                                         # every other held-out point is a row of another run
    _, info = whatif.fit_class(obs, "glider", tmp_path / "t.parquet", fresh=fresh)
    assert info["fresh_points"] == 3 and len(seen) == 6 and len(set(seen)) == 6              # one call per distinct held-out point, the rest never asked
    _, none = whatif.fit_class(obs, "glider", tmp_path / "t.parquet", fresh=lambda row: None)
    assert none["fresh_points"] == 0 and none["rmse_gate"] == none["rmse_debiased"]


def test_measure_runs_the_members_it_is_given(monkeypatch):
    got = []
    monkeypatch.setattr(stage1, "run_batch", lambda m, e, members, *a: got.append(list(members)) or (_ for _ in ()).throw(OutsideData("x")))
    plan = plan_for(STORM, 16)
    with pytest.raises(whatif.Invalid):
        whatif.measure(STORM, GL, ENV, plan, *PRI, None, 7, members=list(range(48, 64)))
    with pytest.raises(whatif.Invalid):
        whatif.measure(STORM, GL, ENV, plan, *PRI, None, 7)
    assert got == [list(range(48, 64)), list(range(16))]                                  # the base run's members when none are named


# ---------------------------------------------------------------------------------------------------------------- review round 5: M-1

def test_a_variant_shifted_by_a_fraction_of_a_minute_keeps_its_glider_and_usv_rows(ci_full):
    """M-1: on a window ending on the hour a deploy shifted by 8.8344 h (the q5 design's variant 3) steps a multiple of 10 steps and ends 3 s past the
    data: the batch raised OutsideData and the glider and the USV were skipped as 'leaving the data' (2 of the q5 design's 28 rows)."""
    m = whatif.apply(CI, {v: dict(shift_h=8.8344) for v in ("glider_eq", "usv")}, drop=["uas", "glider_1n"])
    pri, marg = stage1.priors_for(m)
    rows, skipped = whatif.run_variant(m, ci_full, [0, 1], 5, pri, marg, None, {}, {}, "v3")
    assert not skipped and {r["vehicle"] for r in rows} == {"glider_eq", "usv"}


# ---------------------------------------------------------------------------------------------------------------- review round 5, batch W

def test_a_whole_day_shift_answers_the_vehicles_it_can_and_names_the_uas_as_unchanged():
    """M-14: the RUNBOOK's first example (`--shift 48h`) aborted on the UAS's refusal before any vehicle was answered."""
    m = whatif.apply(CI, drop=["usv", "glider_1n"])
    base = {GL: dict(verdict="GO", p_fail=0.0), "uas": dict(verdict="GO", p_fail=0.0)}
    r = whatif.answer(m, dict(shift_h=24.0), base, {GL: TRACK}, ENV, {}, plan_for(m), None, None)
    assert set(r["vehicles"]) == {GL} and r["unchanged"] == {"uas": "launching +24 h later keeps the same launch time of day: nothing changes"}
    with pytest.raises(whatif.Invalid, match="whole number of days"):
        whatif.apply(m, {"uas": dict(shift_h=24.0)})                                      # a direct caller is still refused (row 195)
    only = whatif.answer(m, dict(shift_h=48.0), base, {}, ENV, {}, plan_for(m), None, None, only=["uas"])
    assert only["vehicles"] == {} and list(only["unchanged"]) == ["uas"]


def test_a_whole_day_shift_with_a_move_moves_the_uas_ship_and_still_says_the_shift_changes_nothing():
    m = whatif.apply(CI, drop=["usv", "glider_1n", GL])
    r = whatif.answer(m, dict(shift_h=24.0, dlon=0.1), {"uas": dict(verdict="GO", p_fail=0.0)}, {}, ENV, {}, plan_for(m), None, None)
    assert list(r["vehicles"]) == ["uas"] and r["vehicles"]["uas"]["method"] == "Stage 1" and "uas" in r["unchanged"]


ADDER = """
import sys, time, pathlib
import pandas as pd
from cafe.pm import whatif
table, go, tag = sys.argv[1:]
while not pathlib.Path(go).exists():
    time.sleep(0.01)
for i in range(12):
    whatif.add_rows(table, [dict(key=f"{tag}{i}", x=float(i), pad="p" * 400_000)])
"""


def test_three_processes_adding_rows_to_one_table_lose_none_and_never_corrupt_it(tmp_path):
    """M-6: `add_rows` was an unlocked read-modify-write over one fixed temporary name: concurrent runs lost rows, met a half-written file
    (ConfigError "cannot be read") or renamed each other's temporary (FileNotFoundError)."""
    import subprocess, sys
    table, go = tmp_path / "train.parquet", tmp_path / "go"
    env = dict(__import__("os").environ, PYTHONPATH=str(ROOT))
    procs = [subprocess.Popen([sys.executable, "-c", ADDER, str(table), str(go), tag], cwd=ROOT, env=env, stderr=subprocess.PIPE, text=True) for tag in "abc"]
    go.write_text("")                                                                       # all three start adding at once
    errs = [p.communicate(timeout=600)[1] for p in procs]
    assert [p.returncode for p in procs] == [0, 0, 0], errs
    df = pd.read_parquet(table)
    assert len(df) == 36 and df["key"].nunique() == 36
    assert sorted(f.name for f in tmp_path.iterdir()) == ["go", "train.parquet", "train.parquet.lock"]        # no temporary left
