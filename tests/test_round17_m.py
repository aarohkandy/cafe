"""Round 17, the merge: what batch B's builder found outside its batch, and the link card's limitation id.
(a) the mission report and the credibility page count the inputs a mission depends on with one function (`credibility.used_counts`);
(b) the USV card prints the becalmed clock the verdict used, and the override table lists the USV's two task keys;
(c) a station task that leaves out `radius_km` and `lost_after_h` gets stage 1's 5 km and 6 h, the documents' defaults (DECISIONS 292, RUNBOOK 4);
(d) the RF link card names limitation L23."""
import copy
import html
import json
import re

import numpy as np
import pytest
import yaml

from cafe.pm import config, credibility as cr, pipeline, report, stage1
from cafe.pm.env.protocol import AnalyticEnv
from cafe.pm.physics import glider, usv
from tests.fixtures import pm_run

REAL = cr.ROOT
DEMO = yaml.safe_load((REAL / "missions" / "tepex_c_demo.yaml").read_text())
REAL_SIM = usv.USVSim                                          # the class itself: a second patch in one test must not wrap the first


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


def edit_json(path, fn):
    d = json.loads(path.read_text())
    fn(d)
    path.write_text(json.dumps(d))


def plain(h):
    return html.unescape(re.sub(r"<[^>]+>", "", re.sub(r"<a class=lk[^>]*>[LR]</a>", "", h)))


def load(run):
    return json.loads((run / "report" / "report.json").read_text())


def vehicle(doc, vid):
    return next(v for v in doc["vehicles"] if v["id"] == vid)


# ---------------------------------------------------------------------------------------------------------- (a) one count of the used inputs

def test_r17_m_a_the_platform_counts_are_the_reports_counts_for_every_platform_in_a_one_uas_mission(run, data):
    """The platforms a mission does not fly, and the radios it does not use, were counted by `platform_assumed_counts` (every assumed row) and left out of the
    report's 'used by this mission' numbers: the two are one function now."""
    mission = yaml.safe_load((run / "mission.yaml").read_text())
    mission["vehicles"] = [v for v in mission["vehicles"] if v["id"] == "uas"]
    mission["links"] = []
    (run / "mission.yaml").write_text(yaml.safe_dump(mission))
    c = cr.build(run, REAL, data)
    used, rest = cr.used_counts(c["assumed_inputs"])
    a = report._assumed(c, dict(stage="credibility", ledger="l", receipt="r"))
    assert {f: n["value"] for f, n in a["by_file"].items()} == used and {f: n["value"] for f, n in a["not_used_by_file"].items()} == rest
    assert c["platform_assumed_counts"] == {s: used.get(f"platforms/{s}.yaml", 0) for s in c["platform_assumed_counts"]}
    got = c["platform_assumed_counts"]
    assert got["quad_uas"] == 39 and got["radios"] == 4                                         # the UAS's own radio only; 43 listed, 4 replaced
    assert [got[s] for s in ("seaglider", "slocum", "saildrone_explorer", "modems")] == [0, 0, 0, 0]


def test_r17_m_a_the_report_prints_the_credibility_pages_count_for_every_vehicle(run, data):
    m, plan = pm_run.make_run(run)
    report.write(run, m, plan)
    rep, c = load(run), json.loads((run / "report" / "credibility.json").read_text())
    by_file = {f: n["value"] for f, n in rep["assumed_inputs"]["by_file"].items()}
    assert by_file == cr.used_counts(c["assumed_inputs"])[0]
    for v in rep["vehicles"].values():
        stem = cr.platform_key(v["platform"])
        assert v["assumed_platform_inputs"]["value"] == c["platform_assumed_counts"][stem] == by_file[f"platforms/{stem}.yaml"], v["platform"]
    assert {v["platform"]: v["assumed_platform_inputs"]["value"] for v in rep["vehicles"].values()} == dict(
        seaglider=16, slocum=21, saildrone_explorer=57, quad_uas=39)
    t = plain((run / "report" / "index.html").read_text())
    assert t.count("Depends on 16 inputs (assumed platform values)") == 1 and t.count("Depends on 57 inputs (assumed platform values)") == 1


def test_r17_m_a_the_hangars_count_is_the_files_and_differs_from_the_missions_by_the_rows_the_mission_replaces(run, data):
    """`hangar.json` keeps the number of assumed items of each platform FILE (`pipeline._assumed`, which said it agreed with credibility.json by construction):
    the credibility count is that minus the assumed rows the mission replaces."""
    c = cr.build(run, REAL, data)
    replaced = cr.mission_replaced(DEMO)
    for vid, stem in (("glider_eq", "seaglider"), ("glider_2n", "slocum"), ("usv", "saildrone_explorer"), ("uas", "quad_uas")):
        items = pipeline.provenance(yaml.safe_load((REAL / "platforms" / f"{stem}.yaml").read_text()))
        gone = sum(1 for i in items if i["assumed"] and (stem, i["path"]) in replaced)
        assert pipeline._assumed(yaml.safe_load((REAL / "platforms" / f"{stem}.yaml").read_text())) == len(
            [i for i in items if i["assumed"]]) == c["platform_assumed_counts"][stem] + gone, vid
    assert [c["platform_assumed_counts"][s] for s in ("seaglider", "slocum", "quad_uas")] == [16, 21, 39]
    assert "agree by construction" not in pipeline._assumed.__doc__ and "FILE's count" in pipeline._assumed.__doc__


# ---------------------------------------------------------------------------------------------------------- (b) what a USV task replaces

class Stop(Exception):
    pass


def usv_md(monkeypatch, task):
    """The mission defaults `USVSim` ends up with for the task `_run_usv` hands it (the model's own merge of the task over the platform's)."""
    seen: list[dict] = []

    def fake(P, M, env, start, t0, mission, **kw):
        seen.append(REAL_SIM(P, 1, AnalyticEnv(), start, 0.0, mission).md)
        raise Stop

    monkeypatch.setattr(usv, "USVSim", fake)
    v = dict(platform="saildrone_explorer", task=task, deploy=dict(lon=-170.0, lat=0.0))
    with pytest.raises(Stop):
        stage1._run_usv(v, usv.load_platform("saildrone_explorer"), None, 1, dict(usv_vpp_bias=np.zeros(1), solar_yield_scale=np.ones(1)), 0.0, 3600.0)
    return seen[0]


def usv_changed(md):
    P = usv.load_platform("saildrone_explorer")["mission_defaults"]
    return {f"mission_defaults.{k}" for k in P if md[k] != P[k]}


def test_r17_m_b_the_override_table_of_a_usv_is_what_stage_1_and_the_model_replace(monkeypatch):
    own = dict(becalmed_after_h=9.0, track_tolerance_km=15.0)
    section = dict(mode="section", waypoints=[[-170.0, 0.0], [-169.0, 0.0]], **own)
    md = usv_md(monkeypatch, section)
    assert usv_changed(md) == set(cr.MISSION_OVERRIDES["usv"]) and (md["becalmed_after_h"], md["track_tolerance_km"]) == (9.0, 15.0)
    assert {k: v[0] for k, v in cr.vehicle_replaced(DEMO, dict(task=section), "usv").items()} == {
        "mission_defaults.becalmed_after_h": "9.0 h", "mission_defaults.track_tolerance_km": "15.0 km"}
    station = dict(mode="station", lon=-170.0, lat=0.0, radius_km=7.0)                          # a station's radius is its track tolerance unless given
    assert usv_md(monkeypatch, station)["track_tolerance_km"] == 7.0
    assert {k: v[0] for k, v in cr.vehicle_replaced(DEMO, dict(task=station), "usv").items()} == {"mission_defaults.track_tolerance_km": "7.0 km"}
    both = dict(station, track_tolerance_km=12.0)
    assert usv_md(monkeypatch, both)["track_tolerance_km"] == 12.0
    assert cr.vehicle_replaced(DEMO, dict(task=both), "usv")["mission_defaults.track_tolerance_km"][0] == "12.0 km"
    bare = dict(mode="section", waypoints=[[-170.0, 0.0], [-169.0, 0.0]], radius_km=7.0)       # a section task ignores radius_km: the platform's 20 km stays
    assert usv_changed(usv_md(monkeypatch, bare)) == set() and cr.vehicle_replaced(DEMO, dict(task=bare), "usv") == {}
    assert usv_changed(usv_md(monkeypatch, dict(mode="station", lon=-170.0, lat=0.0))) == set()


def test_r17_m_b_a_key_the_mission_schema_lets_a_usv_task_name_is_in_the_table_or_is_no_platform_default():
    """A task key added to the schema that `USVSim` would merge over a platform default has to be listed here, or this fails."""
    schema = json.loads((REAL / "cafe" / "schemas" / "mission.json").read_text())
    task = schema["properties"]["vehicles"]["items"]["properties"]["task"]["properties"]
    platform = usv.load_platform("saildrone_explorer")["mission_defaults"]
    assert {f"mission_defaults.{k}" for k in task if k in platform} == set(cr.MISSION_OVERRIDES["usv"])


def test_r17_m_b_the_demo_lists_the_usvs_two_task_values_as_not_used_and_counts_the_rest(run, data):
    c = cr.build(run, REAL, data)
    by = {i["id"]: i for i in c["assumed_inputs"]}
    a, t = by["saildrone_explorer.yaml:mission_defaults.becalmed_after_h"], by["saildrone_explorer.yaml:mission_defaults.track_tolerance_km"]
    assert (a["used"], a["mission_value"], t["used"], t["mission_value"]) == (False, "6.0 h", False, "20.0 km")
    assert a["not_used"] == "the mission sets its own value (6.0 h) and the verdicts use that"
    assert by["saildrone_explorer.yaml:mission_defaults.calm_sustain_s"]["used"] is True and c["platform_assumed_counts"]["saildrone_explorer"] == 57
    mission = yaml.safe_load((run / "mission.yaml").read_text())
    del next(v for v in mission["vehicles"] if v["id"] == "usv")["task"]["becalmed_after_h"]
    (run / "mission.yaml").write_text(yaml.safe_dump(mission))                                  # the platform's 6 h is now what the verdict reads
    again = {i["id"]: i for i in cr.build(run, REAL, data)["assumed_inputs"]}
    assert again[a["id"]]["used"] is True and "not_used" not in again[a["id"]] and again[t["id"]]["used"] is False


def test_r17_m_b_the_usv_card_prints_the_becalmed_clock_the_verdict_used(run):
    m, plan = pm_run.make_run(run)
    modes = lambda d: d["summary"]["vehicles"]["usv"].update(modes=dict(wing_stall_calm=9, becalmed=2))      # noqa: E731
    edit_json(run / "stage1b" / "summary.json", modes)
    mission = yaml.safe_load((run / "mission.yaml").read_text())
    for doc in (m, mission):
        vehicle(doc, "usv")["task"]["becalmed_after_h"] = 9.0                                   # the platform's file says 6 h
    (run / "mission.yaml").write_text(yaml.safe_dump(mission))
    report.write(run, m, plan)
    u = load(run)["vehicles"]["usv"]["usv_modes"]
    assert u["becalmed_after"]["value"] == 9.0 and u["becalmed_after"]["source"] == "mission.yaml vehicles.usv.task.becalmed_after_h"
    assert (u["trim_min_aws"]["value"], u["calm_sustain"]["value"]) == (1.5, 30.0)                  # the model's own, no task key replaces them
    t = plain((run / "report" / "index.html").read_text())
    assert "becalmed only after 9 h of being unable to stem the current" in t and "becalmed only after 6 h" not in t
    assert load(run)["traceability_problems"] == []
    for doc in (m, mission):
        del vehicle(doc, "usv")["task"]["becalmed_after_h"]
    (run / "mission.yaml").write_text(yaml.safe_dump(mission))
    report.write(run, m, plan)
    u = load(run)["vehicles"]["usv"]["usv_modes"]
    src = u["becalmed_after"]["source"]
    assert u["becalmed_after"]["value"] == 6.0 and src.endswith("becalmed_after_h") and "mission.yaml" not in src


# ---------------------------------------------------------------------------------------------------------- (c) a station task's own defaults

def mis_of(monkeypatch, task, P):
    seen: list[dict] = []

    def fake(P_, M, env, lon, lat, t0, mis, **kw):
        seen.append(mis)
        raise Stop

    monkeypatch.setattr(glider, "GliderSim", fake)
    v = dict(platform="seaglider", task=task, deploy=dict(lon=-170.0, lat=0.0))
    with pytest.raises(Stop):
        stage1._run_glider(v, P, None, 1, dict(glider_speed_scale=np.ones(1), battery_capacity_scale=np.ones(1)), 0.0, 3600.0)
    return seen[0]


def test_r17_m_c_a_station_task_without_radius_or_lost_after_gets_5_km_and_6_h_whatever_the_platform_file_says(monkeypatch):
    """Decided, not a defect: DECISIONS 292 and RUNBOOK 4 give the task's defaults as `radius_km` 5 and `lost_after_h` 6 (the mission is where the lab states
    its tolerance, QUESTIONS_FOR_LAB 5), so the platform file's `station_tol_m` and `lost_hours` are never read in any mode and the pages say which was used."""
    P = copy.deepcopy(glider.load_platform("seaglider"))
    P["mission_defaults"]["station_tol_m"], P["mission_defaults"]["lost_hours"] = 8000.0, 9.0
    mis = mis_of(monkeypatch, dict(mode="station", lon=-170.0, lat=0.0), P)
    assert (mis["station_tol_m"], mis["lost_hours"]) == (5000.0, 6.0)
    got = cr.vehicle_replaced(DEMO, dict(task=dict(mode="station", lon=-170.0, lat=0.0)), "glider")
    assert got["mission_defaults.station_tol_m"][1] == "stage 1 sets its own value (5.0 km, as task.radius_km is not set) and the verdicts use that"
    assert got["mission_defaults.lost_hours"][1] == "stage 1 sets its own value (6.0 h, as task.lost_after_h is not set) and the verdicts use that"
    runbook = (REAL / "docs" / "RUNBOOK.md").read_text()
    assert "`radius_km`, default 5, and `lost_after_h`, default 6" in runbook                      # the documented defaults are the code's
    assert "radius_km, default 5, and lost_after_h, default 6" in (REAL / "cafe" / "pm" / "config.py").read_text()


def test_r17_m_c_the_report_says_which_station_value_was_used_when_the_task_gives_none(run):
    m, plan = pm_run.make_run(run)
    mission = yaml.safe_load((run / "mission.yaml").read_text())
    for doc in (m, mission):
        for k in ("radius_km", "lost_after_h"):
            del vehicle(doc, "glider_eq")["task"][k]
    (run / "mission.yaml").write_text(yaml.safe_dump(mission))
    report.write(run, m, plan)
    byid = {i["id"]: i for i in load(run)["assumed_inputs"]["items"]}
    assert byid["seaglider.yaml:mission_defaults.station_tol_m"]["used"] is False
    assert byid["seaglider.yaml:mission_defaults.station_tol_m"]["not_used"].startswith("stage 1 sets its own value (5.0 km")
    assert byid["seaglider.yaml:mission_defaults.lost_hours"]["not_used"].startswith("stage 1 sets its own value (6.0 h")
    assert "(assumed, stage 1 sets its own value (6.0 h, as task.lost_after_h is not set) and the verdicts use that)" in plain(
        (run / "report" / "index.html").read_text())


# ---------------------------------------------------------------------------------------------------------- (d) the link card names L23

def test_r17_m_d_the_low_antenna_sentence_of_the_link_card_names_the_limitation_row():
    demo = config.load_mission(REAL / "missions" / "tepex_c_demo.yaml")
    note = report._low_antenna_note(dict(id="x", kind="rf", when="uas_airborne", a="glider_2n", b="usv"), demo)
    assert note and note.endswith("(CREDIBILITY, limitation L23).")
    assert "L23" in {x["id"] for x in cr.LIMITATIONS} and "antenna below 0.5 m" in {x["id"]: x for x in cr.LIMITATIONS}["L23"]["text"]
