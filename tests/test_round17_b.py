"""Round 17, batch B: the credibility page (M-2: a platform input the mission replaces, or that its task mode never reads, is listed and not counted as used;
M-5: the limitation row for an RF link to a low antenna)."""
import copy
import html
import json
import re

import numpy as np
import pytest
import yaml

from cafe.pm import credibility as cr, report, stage1
from cafe.pm.physics import glider, uas
from tests.fixtures import pm_run
from tests.test_glider import sim as glider_sim
from tests.test_round22_b import figs

REAL = cr.ROOT
DEMO = yaml.safe_load((REAL / "missions" / "tepex_c_demo.yaml").read_text())
UAS_ROWS = {"sortie.levels_m", "sortie.duration_s", "launch_rule.max_mean_wind_ms", "launch_rule.gust_lookahead_min", "radio.ship_antenna_height_m"}
MODE_ROWS = {"mission_defaults." + k for k in ("station_tol_m", "lost_hours", "wp_radius_m", "unreach_hours")}


@pytest.fixture
def data(tmp_path, monkeypatch):
    d = tmp_path / "data"
    monkeypatch.setenv("CAFE_DATA", str(d))
    return d


@pytest.fixture
def run(tmp_path, data, monkeypatch):
    monkeypatch.setattr(report, "RECEIPTS", tmp_path / "model_receipts.json")
    d = tmp_path / "run"
    d.mkdir()
    pm_run.make_run(d)
    return d


def row(c, ident):
    return next(i for i in c["assumed_inputs"] if i["id"] == ident)


def mission(**edits):
    m = copy.deepcopy(DEMO)
    for k, v in edits.items():
        m[k] = v
    return m


# ---------------------------------------------------------------------------------------------------------- M-2: what the mission replaces

def test_r17_m2_the_demo_replaces_the_uas_inputs_and_the_gliders_station_and_waypoint_keys():
    got = cr.mission_replaced(DEMO)
    assert {p for k, p in got if k == "quad_uas"} == UAS_ROWS
    assert {p for k, p in got if k == "seaglider"} == {"mission_defaults." + k for k in
                                                       ("dive_depth_m", "station_tol_m", "lost_hours", "wp_radius_m", "unreach_hours")}
    assert {p for k, p in got if k == "slocum"} == {"mission_defaults.dive_depth_m"} | MODE_ROWS
    assert {p for k, p in got if k == "saildrone_explorer"} == {"mission_defaults.becalmed_after_h", "mission_defaults.track_tolerance_km"}     # the merge
    assert not [k for k, _ in got if k not in ("quad_uas", "seaglider", "slocum", "saildrone_explorer")]
    assert got["seaglider", "mission_defaults.lost_hours"] == ("12.0 h", "the mission sets its own value (12.0 h) and the verdicts use that")
    assert got["seaglider", "mission_defaults.dive_depth_m"][0] == "950.0 m" and got["slocum", "mission_defaults.dive_depth_m"][0] == "500.0 m"
    assert got["quad_uas", "radio.ship_antenna_height_m"][0] == "15.0 m" and got["quad_uas", "launch_rule.gust_lookahead_min"][0] == "30 min"
    assert got["quad_uas", "sortie.levels_m"][0] == "[10, 30, 60, 100] m"
    assert got["slocum", "mission_defaults.lost_hours"] == ("", "a drift task never reads it")
    assert got["seaglider", "mission_defaults.unreach_hours"] == ("", "a station task never reads it")


def test_r17_m2_the_five_rows_the_review_names_are_listed_not_used_and_say_what_the_verdicts_use(run, data):
    c = cr.build(run, REAL, data)
    for ident, val in (("quad_uas.yaml:sortie.levels_m", "[10, 30, 60, 100] m"), ("quad_uas.yaml:launch_rule.gust_lookahead_min", "30 min"),
                       ("quad_uas.yaml:radio.ship_antenna_height_m", "15.0 m"), ("seaglider.yaml:mission_defaults.lost_hours", "12.0 h"),
                       ("seaglider.yaml:mission_defaults.dive_depth_m", "950.0 m")):
        r = row(c, ident)
        assert r["used"] is False and r["mission_value"] == val and r["not_used"] == f"the mission sets its own value ({val}) and the verdicts use that", ident
        assert cr.not_used_note(r) == r["not_used"]
    assert row(c, "slocum.yaml:mission_defaults.lost_hours")["mission_value"] is None            # a drift task: no mission value, the key is not read
    assert row(c, "slocum.yaml:mission_defaults.lost_hours")["not_used"] == "a drift task never reads it"
    assert row(c, "quad_uas.yaml:sortie.leg_speed_ms")["used"] is True and "not_used" not in row(c, "quad_uas.yaml:sortie.leg_speed_ms")
    assert row(c, "saildrone_explorer.yaml:mission_defaults.becalmed_after_h")["used"] is False     # the card prints the task's (the merge)
    assert row(c, "saildrone_explorer.yaml:mission_defaults.calm_sustain_s")["used"] is True        # no task key replaces the other clocks
    page = html.unescape(cr._render(c))
    assert "assumed (the mission sets its own value (12.0 h) and the verdicts use that)" in page
    cr.write(run)                                                                          # the JSON still serialises with the new fields
    assert row(json.loads((run / "report" / "credibility.json").read_text()), "seaglider.yaml:mission_defaults.lost_hours")["mission_value"] == "12.0 h"


def test_r17_m2_the_counts_leave_out_what_the_mission_replaces_but_keep_the_rows(run, data):
    c = cr.build(run, REAL, data)
    items = c["assumed_inputs"]
    off = [i for i in items if "not_used" in i]
    assert len(off) == 16 and {i["kind"] for i in off} == {"assumed"}     # 4 + 5 + 5 + 2 (the USV's) assumed; duration_s is sourced
    for stem in ("quad_uas", "seaglider", "slocum", "saildrone_explorer"):
        every = [i for i in items if i["file"] == f"platforms/{stem}.yaml"]
        assert c["platform_assumed_counts"][stem] == len(every) - sum("not_used" in i for i in every)
    assert c["platform_assumed_counts"] == {s: n for s, n in c["platform_assumed_counts"].items()} and c["platform_assumed_counts"]["saildrone_explorer"] > 20
    ped = next(f for f in c["factors"] if f["factor"] == "input_pedigree")["evidence"][0]["what"]
    f = cr.Facts(run, REAL, data)
    its = [i for i in f.items if f.item_used(i["key"], i["path"]) and (i["assumed"] or i["sourced"])]
    assert ped.startswith(f"{sum(1 for i in its if i['sourced'] and not i['assumed'] and not i['recalled'])} of {len(its)} platform inputs sourced")
    assert (f.items[0]["key"], f.items[0]["path"]) not in f.replaced and not f.item_used("quad_uas", "sortie.levels_m")


def test_r17_m2_an_input_stays_used_while_one_vehicle_flying_the_platform_reads_it():
    m = mission()
    second = copy.deepcopy(next(v for v in m["vehicles"] if v["id"] == "glider_eq"))
    second["id"] = "glider_ws"
    del second["task"]["dive_depth_m"]
    del second["task"]["lost_after_h"]
    m["vehicles"].append(second)
    got = cr.mission_replaced(m)
    assert ("seaglider", "mission_defaults.dive_depth_m") not in got                                  # the second vehicle reads the platform's 500 m
    assert got["seaglider", "mission_defaults.lost_hours"][0] == "12.0 h; 6.0 h"                      # stage 1's own 6 h for the one that gives none
    assert got["seaglider", "mission_defaults.station_tol_m"][0] == "5.0 km" and "stage 1 sets its own value (6.0 h, as task.lost_after_h is not set)" in \
        got["seaglider", "mission_defaults.lost_hours"][1]


def test_r17_m2_a_mission_that_cannot_be_read_replaces_nothing():
    assert cr.mission_replaced(None) == {} and cr.mission_replaced(dict(DEMO, vehicles=[dict(platform="no_such_platform", task=dict(mode="drift"))])) == {}
    assert cr.mission_replaced(dict(DEMO, vehicles=[3])) == {} and cr.mission_replaced(dict(DEMO, vehicles=[dict(id="x")])) == {}
    sec = mission()
    sec["vehicles"][0]["task"] = dict(mode="section", waypoints=[[-170.0, 0.0], [-169.0, 0.0]])
    got = cr.mission_replaced(sec)                                                         # a section task reads wp_radius_m and unreach_hours
    assert {p: v for (k, p), v in got.items() if k == "seaglider"} == {"mission_defaults.station_tol_m": ("", "a section task never reads it"),
                                                                         "mission_defaults.lost_hours": ("", "a section task never reads it")}
    assert cr.vehicle_replaced(DEMO, dict(task=dict(mode="nonsense")), "glider") == {}


def test_r17_m2_the_mission_report_says_why_an_input_is_not_used(run):
    m, plan = pm_run.make_run(run)
    report.write(run, m, plan)
    rep = json.loads((run / "report" / "report.json").read_text())["assumed_inputs"]
    byid = {i["id"]: i for i in rep["items"]}
    assert byid["seaglider.yaml:mission_defaults.lost_hours"]["not_used"] == "the mission sets its own value (12.0 h) and the verdicts use that"
    assert "not_used" not in byid["quad_uas.yaml:sortie.leg_speed_ms"] and byid["quad_uas.yaml:sortie.levels_m"]["used"] is False
    text = html.unescape(re.sub(r"<[^>]+>", "", (run / "report" / "index.html").read_text()))
    assert "(assumed, the mission sets its own value (12.0 h) and the verdicts use that)" in text
    assert "seaglider.yaml:mission_defaults.lost_hours</code></a> (assumed, platform not used" not in (run / "report" / "index.html").read_text()


# ---------------------------------------------------------------------------------------------------------- the table is what stage 1 does

def uas_vehicle():
    return next(v for v in DEMO["vehicles"] if v["id"] == "uas")


def test_r17_m2_every_uas_entry_is_what_stage_1_replaces_and_nothing_else_is():
    """`stage1._uas_setup` applied to a vehicle that sets every mission key: the platform leaves that change are exactly the table's."""
    P = uas.load_platform("quad_uas")
    v = copy.deepcopy(uas_vehicle())
    v["sorties"].update(duration_min=17, altitudes_m=[11, 31])
    v["launch_rules"] = dict(max_mean_wind_ms=9.0, no_gust_front_within_min=7)
    Q, _, _ = stage1._uas_setup(v, P, DEMO, 0.0, 6 * 86400.0)
    changed = {f"{g}.{k}" for g in ("sortie", "launch_rule") for k in P[g] if Q[g][k] != P[g][k]}
    assert changed == {p for p in cr.MISSION_OVERRIDES["uas"] if not p.startswith("radio.")} == UAS_ROWS - {"radio.ship_antenna_height_m"}
    assert (Q["sortie"]["duration_s"], Q["sortie"]["levels_m"], Q["launch_rule"]["max_mean_wind_ms"], Q["launch_rule"]["gust_lookahead_min"]) == (
        1020.0, [11.0, 31.0], 9.0, 7.0)
    assert cr.vehicle_replaced(DEMO | dict(vehicles=[v]), v, "uas")["sortie.duration_s"][0] == "17 min"
    base = copy.deepcopy(DEMO)
    for k in ("duration_min", "altitudes_m"):
        base["vehicles"][3]["sorties"].pop(k, None)
    assert "sortie.levels_m" not in cr.vehicle_replaced(base, base["vehicles"][3], "uas")          # a mission key left out is the platform's


def test_r17_m2_the_ships_antenna_is_the_missions_else_the_platforms():
    ra = uas.load_platform("quad_uas")["radio"]
    assert stage1.ship_antenna_m(DEMO, ra) == 15.0 and cr.vehicle_replaced(DEMO, uas_vehicle(), "uas")["radio.ship_antenna_height_m"][0] == "15.0 m"
    bare = copy.deepcopy(DEMO)
    del bare["ship"]["antenna_height_m"]
    assert stage1.ship_antenna_m(bare, ra) == ra["ship_antenna_height_m"] == 10.0
    assert "radio.ship_antenna_height_m" not in cr.vehicle_replaced(bare, uas_vehicle(), "uas")


class Stop(Exception):
    pass


def mis_of(monkeypatch, task, platform="seaglider"):
    """The `mis` dict `_run_glider` hands to GliderSim for this task."""
    seen: list[dict] = []

    def fake(P, M, env, lon, lat, t0, mis, **kw):
        seen.append(mis)
        raise Stop

    monkeypatch.setattr(glider, "GliderSim", fake)
    v = dict(platform=platform, task=task, deploy=dict(lon=-170.0, lat=0.0))
    with pytest.raises(Stop):
        stage1._run_glider(v, glider.load_platform(platform), None, 1, dict(glider_speed_scale=np.ones(1), battery_capacity_scale=np.ones(1)), 0.0, 3600.0)
    return seen[0]


def test_r17_m2_the_glider_entries_are_what_run_glider_hands_the_model(monkeypatch):
    st = dict(mode="station", lon=-170.0, lat=0.0, radius_km=7.0, lost_after_h=9.0, dive_depth_m=600.0)
    full = mis_of(monkeypatch, st)
    assert (full["dive_depth_m"], full["station_tol_m"], full["lost_hours"]) == (600.0, 7000.0, 9.0)
    bare = mis_of(monkeypatch, dict(mode="station", lon=-170.0, lat=0.0))                      # nothing set: stage 1's own 5 km and 6 h, not the platform's
    tab = cr.MISSION_OVERRIDES["glider"]
    assert (bare["station_tol_m"], bare["lost_hours"]) == (1e3 * tab["mission_defaults.station_tol_m"][1], tab["mission_defaults.lost_hours"][1])
    assert bare["dive_depth_m"] == glider.load_platform("seaglider")["mission_defaults"]["dive_depth_m"]
    drift = mis_of(monkeypatch, dict(mode="drift"), "slocum")
    assert "station_tol_m" not in drift and "lost_hours" not in drift
    assert {k: v[0] for k, v in cr.vehicle_replaced(DEMO, dict(task=st), "glider").items()} == {
        "mission_defaults.dive_depth_m": "600.0 m", "mission_defaults.station_tol_m": "7.0 km", "mission_defaults.lost_hours": "9.0 h",
        "mission_defaults.wp_radius_m": "", "mission_defaults.unreach_hours": ""}
    assert {k: v[0] for k, v in cr.vehicle_replaced(DEMO, dict(task=dict(mode="station", lon=0.0, lat=0.0)), "glider").items()} == {
        "mission_defaults.station_tol_m": "5.0 km", "mission_defaults.lost_hours": "6.0 h", "mission_defaults.wp_radius_m": "",
        "mission_defaults.unreach_hours": ""}


class Reads(dict):
    """A mission-defaults dict that records the keys the model reads."""
    got: set = set()

    def __getitem__(self, k):
        self.got.add(k)
        return super().__getitem__(k)


@pytest.mark.parametrize("mode, task", [("station", dict(mode="station", station=(180.0, 0.0))),
                                        ("section", dict(mode="section", waypoints=[(180.0, 0.0), (180.0, 1.0)])), ("drift", dict(mode="drift"))])
def test_r17_m2_each_task_mode_reads_exactly_the_keys_the_table_says(mode, task):
    s = glider_sim(mission=task)
    s.md = Reads(s.md)
    Reads.got = set()
    s.run(3 * 3600.0, dt=60.0)
    assert Reads.got & {"station_tol_m", "lost_hours", "wp_radius_m", "unreach_hours"} == set(cr.GLIDER_MODE_KEYS[mode])
    assert "dive_depth_m" not in cr.GLIDER_MODE_ONLY and set(cr.GLIDER_MODE_KEYS) == set(glider.MODES)


# ---------------------------------------------------------------------------------------------------------- M-5: the limitation row

def test_r17_m5_a_limitation_names_the_low_antenna_loss_and_bears_on_validation_only():
    x = {l["id"]: l for l in cr.LIMITATIONS}["L23"]
    assert [l["id"] for l in cr.LIMITATIONS][-2:] == ["L22", "L23"]
    # round 18, M-3: the text is by pair of heights (tests/test_round18_b.py)
    assert x["text"].startswith("RF links, from an antenna below 0.5 m or the USV's 2.2 m whip to a UAS at 108 m:")      # round 21, M-2: every RF link
    assert f"0.3 m (the Slocum) with 2.2 m (the USV's whip) {figs(0.3, 2.2)}" in x["text"]   # round 18 addendum: by pair (round 22: median and counts)
    assert "overstated" in x["text"]
    assert x["factors"] == ["validation"]
    assert all((REAL / w).is_file() for w in x["where"])
    assert yaml.safe_load((REAL / "platforms" / "slocum.yaml").read_text())["params"]["antenna_height_m"]["value"] == 0.3


def test_r17_m5_the_validation_factor_cites_l23_and_no_level_moves(run, data):
    c = cr.build(run, REAL, data)
    assert "L23" in [x["id"] for x in c["limitations"]] and len(c["limitations"]) == len(cr.LIMITATIONS) + 1            # plus L13, built at run time
    val = next(f for f in c["factors"] if f["factor"] == "validation")
    assert "L23" in val["limitations"] and val["level"] <= 2
    other = next(f for f in c["factors"] if f["factor"] == "uncertainty")
    assert "L23" not in other["limitations"]
