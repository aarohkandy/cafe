"""cafe.pm.config: every refusal names the file and field, and each kind of bad mission is rejected."""
import copy
import pathlib
import re

import pytest
import yaml

from cafe.pm import config
from cafe.pm.config import ConfigError, load_mission, load_platform
from cafe.pm.stats import intervals as I

DEMO = config.ROOT / "missions" / "tepex_c_demo.yaml"


def doc():
    return yaml.safe_load(DEMO.read_text())


def write(tmp_path, d, name="m.yaml"):
    p = tmp_path / name
    p.write_text(yaml.safe_dump(d))
    return p


def vehicle(d, vid):
    return next(v for v in d["vehicles"] if v["id"] == vid)


def test_demo_mission_loads(tmp_path):
    m = load_mission(DEMO)
    assert m["name"] == "tepex_c_demo" and len(m["vehicles"]) == 4 and m["_path"] == str(DEMO)
    assert config.utc(m["window"]["start"]).isoformat() == "2023-03-01T12:00:00+00:00"


def test_missing_and_malformed_files_name_the_path(tmp_path):
    with pytest.raises(ConfigError, match="nope.yaml: file not found"):
        load_mission(tmp_path / "nope.yaml")
    bad = tmp_path / "bad.yaml"
    bad.write_text("a: [unclosed")
    with pytest.raises(ConfigError, match=r"bad.yaml: not valid YAML"):
        load_mission(bad)


def test_schema_problems_are_listed_with_their_field_path(tmp_path):
    d = doc()
    d["window"]["start"] = "yesterday"
    d["unknown_key"] = 1
    with pytest.raises(ConfigError) as e:
        load_mission(write(tmp_path, d))
    msg = str(e.value)
    assert "problem(s) against cafe/schemas/mission.json" in msg and "window/start" in msg and "unknown_key" in msg


def test_schema_error_list_is_capped_at_twelve(tmp_path):
    d = doc()
    d["vehicles"] = [dict(id=f"v{i}") for i in range(20)]               # each one is missing `platform`
    with pytest.raises(ConfigError) as e:
        load_mission(write(tmp_path, d))
    lines = str(e.value).splitlines()
    assert int(re.search(r"(\d+) problem", lines[0]).group(1)) >= 20 and len(lines) == 13 and all(x.startswith("  vehicles/") for x in lines[1:])


def mutate_window(d):
    d["window"]["end"] = d["window"]["start"]


def mutate_duplicate_id(d):
    d["vehicles"][1]["id"] = d["vehicles"][0]["id"]


def mutate_base(d):
    vehicle(d, "uas")["base"] = "not_the_ship"


def mutate_deploy_time(d):
    vehicle(d, "glider_eq")["deploy"]["time"] = "2023-03-10T00:00:00Z"


def mutate_deploy_outside_box(d):
    vehicle(d, "glider_eq")["deploy"]["lon"] = 100.0


def mutate_waypoint_outside_box(d):
    vehicle(d, "usv")["task"]["waypoints"] = [[-165.0, -1.0], [-165.0, 40.0]]


def mutate_station_outside_box(d):
    vehicle(d, "glider_eq")["task"]["lat"] = 40.0


def mutate_platform(d):
    vehicle(d, "glider_eq")["platform"] = "no_such_platform"


def mutate_station_without_point(d):
    del vehicle(d, "glider_eq")["task"]["lon"], vehicle(d, "glider_eq")["task"]["lat"]


def mutate_section_without_waypoints(d):
    del vehicle(d, "usv")["task"]["waypoints"]


def mutate_section_with_empty_waypoints(d):
    vehicle(d, "usv")["task"]["waypoints"] = []


def mutate_link_end(d):
    d["links"][0]["a"] = "ghost"


def mutate_rf_without_radio(d):
    del d["links"][0]["radio"]


def mutate_acoustic_without_modem(d):
    del d["links"][1]["modem"]


def mutate_verdict(d):
    d["verdict"] = dict(go=0.5, nogo=0.5)


BAD = [
    (mutate_window, "window.end .* is not after window.start"),
    (mutate_duplicate_id, r"vehicle ids \['glider_eq'\] appear more than once"),
    (mutate_base, "vehicles/uas/base: 'not_the_ship' is not the ship's id"),
    (mutate_deploy_time, r"vehicles/glider_eq/deploy/time: 2023-03-10T00:00:00Z is outside the window"),
    (mutate_deploy_outside_box, r"point \(100.0, 0.0\) is outside the mission box"),
    (mutate_waypoint_outside_box, r"point \(-165.0, 40.0\) is outside the mission box"),
    (mutate_station_outside_box, r"point \(-170.0, 40.0\) is outside the mission box"),
    (mutate_platform, "platform 'no_such_platform': no file .*available: .*seaglider"),
    (mutate_station_without_point, "mode 'station' needs lon, lat and radius_km"),
    (mutate_section_without_waypoints, "mode 'section' needs at least two waypoints"),
    (mutate_section_with_empty_waypoints, r"vehicles/2/task/waypoints: \[\] should be non-empty"),
    (mutate_link_end, "links/usv-uas-rf/a: 'ghost' is not a vehicle, the ship or the shore"),
    (mutate_rf_without_radio, "a rf link needs 'radio'"),
    (mutate_acoustic_without_modem, "a acoustic link needs 'modem'"),
    (mutate_verdict, r"verdict.nogo \(0.5\) must be below verdict.go \(0.5\)"),
]


@pytest.mark.parametrize("mutate,pattern", BAD, ids=[m.__name__ for m, _ in BAD])
def test_each_kind_of_bad_mission_is_rejected_with_the_fix(tmp_path, mutate, pattern):
    d = doc()
    mutate(d)
    path = write(tmp_path, d)
    with pytest.raises(ConfigError, match=pattern) as e:
        load_mission(path)
    assert str(path) in str(e.value) or "platform 'no_such_platform'" in str(e.value)


def test_box_across_the_dateline_accepts_both_sides_and_rejects_the_middle(tmp_path):
    d = doc()
    for lon in (-170.0, 170.0, 179.0, -179.0):
        e = copy.deepcopy(d)
        vehicle(e, "glider_eq")["deploy"]["lon"] = lon
        vehicle(e, "glider_eq")["task"]["lon"] = lon
        e["box"].update(lon_min=165.0, lon_max=-165.0)
        assert load_mission(write(tmp_path, e))["vehicles"][0]["deploy"]["lon"] == lon
    e = copy.deepcopy(d)
    vehicle(e, "glider_eq")["deploy"]["lon"] = 0.0
    with pytest.raises(ConfigError, match="outside the mission box"):
        load_mission(write(tmp_path, e))


def test_in_box_plain_and_wrapped():
    b = dict(lon_min=10.0, lon_max=20.0, lat_min=-5.0, lat_max=5.0)
    assert config._in_box(15.0, 0.0, b) and not config._in_box(25.0, 0.0, b) and not config._in_box(15.0, 6.0, b)
    w = dict(lon_min=165.0, lon_max=-165.0, lat_min=-5.0, lat_max=5.0)
    assert config._in_box(-170.0, 0.0, w) and config._in_box(180.0, 5.0, w) and not config._in_box(-100.0, 0.0, w)


def test_load_platform_by_name_by_path_and_errors(tmp_path):
    assert load_platform("seaglider")["kind"] == "seaglider" and load_platform("seaglider")["params"]["length_m"]["value"] == 1.8
    custom = tmp_path / "mine.yaml"
    custom.write_text("mass_kg: 3\n")
    assert load_platform(str(custom)) == {"mass_kg": 3}
    with pytest.raises(ConfigError, match=r"platform 'zzz': no file .*zzz.yaml; available: \[.*'seaglider'"):
        load_platform("zzz")
    listy = tmp_path / "list.yml"
    listy.write_text("- 1\n- 2\n")
    with pytest.raises(ConfigError, match="expected a mapping of platform parameters"):
        load_platform(str(listy))


def test_assumptions_and_env_sigmas(monkeypatch, tmp_path):
    a = config.assumptions()
    assert a and all("value" in v for k, v in a.items() if k.startswith("env.sigma."))
    s = config.env_sigmas()
    pri = yaml.safe_load((config.CONFIG / "perturbations.yaml").read_text())
    assert s["wind_ms"] == pri["wind_speed_bias"]["value"] and s["hs_frac"] == pri["hs_scale"]["value"] and s["tp_s"] == pri["tp_bias"]["value"]
    assert {"t2_k", "sst_k"} <= set(s)
    monkeypatch.setattr(config, "CONFIG", tmp_path)
    assert config.assumptions() == {}


def test_digest_ignores_key_order_and_sees_values():
    assert config.digest({"a": 1, "b": [1, 2]}) == config.digest({"b": [1, 2], "a": 1})
    assert config.digest({"a": 1}) != config.digest({"a": 2})
    assert len(config.digest({})) == 64 and config.digest({"p": pathlib.Path("x")}) == config.digest({"p": "x"})


# ---- review round 1, batch A: M-11 (keys that do nothing), M-27 (validation gaps) -------------------------------------------------------
@pytest.fixture(autouse=True)
def _restore_thresholds(monkeypatch):
    """load_mission sets the verdict thresholds of cafe.pm.stats.intervals; put them back after each test."""
    for name in ("P_FAIL_GO", "P_FAIL_NOGO", "LO_SUCCESS_GO"):
        monkeypatch.setattr(I, name, getattr(I, name))


def edit(tmp_path, fn):
    d = doc()
    fn(d)
    return write(tmp_path, d)


def test_the_demo_gives_the_default_thresholds_exactly():
    load_mission(DEMO)
    assert (I.P_FAIL_GO, I.P_FAIL_NOGO, I.LO_SUCCESS_GO) == (0.10, 0.40, 0.75)


def test_verdict_thresholds_in_the_mission_reach_the_verdict(tmp_path):
    """M-11: verdict.go / verdict.nogo were checked for order and then ignored."""
    assert I.verdict(1, 32)["verdict"] == "GO"
    load_mission(edit(tmp_path, lambda d: d.update(verdict=dict(go=0.99, nogo=0.9))))
    assert (I.P_FAIL_GO, I.P_FAIL_NOGO) == (0.01, 0.1)
    assert I.verdict(1, 32)["verdict"] == "MARGINAL" and I.verdict(4, 32)["verdict"] == "NO-GO" and I.verdict_from_p(0.05) == "MARGINAL"
    assert I.interval_region(0, 100) is None


def test_a_go_below_the_lower_bound_rule_can_still_be_reached(tmp_path):
    load_mission(edit(tmp_path, lambda d: d.update(verdict=dict(go=0.7, nogo=0.3))))
    assert I.LO_SUCCESS_GO == 0.7 and I.P_FAIL_GO == pytest.approx(0.3)


@pytest.mark.parametrize("verdict", [dict(go=5, nogo=-3), dict(go=0.9, nogo=0.9), dict(go=0.5, nogo=0.6), dict(go=1.2, nogo=0.5), dict(go=0.9, nogo=0),
                                     dict(go=0.9, nogo=0.6, extra=1)])
def test_verdict_thresholds_are_range_checked(tmp_path, verdict):
    with pytest.raises(ConfigError, match=r"verdict"):
        load_mission(edit(tmp_path, lambda d: d.update(verdict=verdict)))


def test_set_thresholds_refuses_what_the_schema_would():
    with pytest.raises(ValueError, match="0 < nogo < go <= 1"):
        I.set_thresholds(0.5, 0.5)
    I.set_thresholds(1.0, 0.5)
    assert I.P_FAIL_GO == 0.0


@pytest.mark.parametrize("block,val,key", [("atmosphere", dict(source="local_wrf"), "source"), ("atmosphere", dict(source="orca_uwincm", path="/x"), "path"),
                                           ("waves", dict(source="local_umwm"), "source"), ("waves", dict(source="orca_umwm", path="/x"), "path"),
                                           ("waves", dict(source="orca_umwm", restart_spectra=False), "restart_spectra"),
                                           ("waves", dict(source="orca_umwm", restart_spectra=True), "restart_spectra")])
def test_environment_keys_nothing_reads_are_refused_with_the_working_route(tmp_path, block, val, key):
    p = edit(tmp_path, lambda d: d["environment"].update({block: val}))
    with pytest.raises(ConfigError, match=rf"m\.yaml: environment/{block}/{key}: .*CAFE_ORCA"):
        load_mission(p)


def test_the_schema_refuses_them_too(tmp_path):
    d = doc()
    d["environment"]["waves"]["restart_spectra"] = True
    d["environment"]["atmosphere"] = dict(source="local_wrf", path="/x")
    with pytest.raises(ConfigError) as e:
        config.validate(d, "mission.json", "m.yaml")
    assert "restart_spectra" in str(e.value) and "environment/atmosphere" in str(e.value)


def test_sortie_patterns_that_are_not_flown_are_refused(tmp_path):
    for pat in ("hover", "transect"):
        with pytest.raises(ConfigError, match=r"vehicles/uas/sorties/pattern: only 'flux_profile'"):
            load_mission(edit(tmp_path, lambda d, pat=pat: vehicle(d, "uas")["sorties"].update(pattern=pat)))
    load_mission(edit(tmp_path, lambda d: vehicle(d, "uas")["sorties"].pop("pattern")))


def test_the_ship_modem_key_nothing_reads_is_refused(tmp_path):
    """The modem a link uses is the link's own `modem`; ship.modem was accepted and read by nothing."""
    with pytest.raises(ConfigError, match=r"ship: Additional properties are not allowed \('modem' was unexpected\)"):
        load_mission(edit(tmp_path, lambda d: d["ship"].update(modem="benthos_atm960_mf")))


def test_the_shipped_missions_use_no_key_that_does_nothing():
    for name in ("tepex_c_demo", "ci_fixture"):
        m = load_mission(config.ROOT / "missions" / f"{name}.yaml")
        assert set(m["environment"]["waves"]) == set(m["environment"]["atmosphere"]) == {"source"}


# M-27: each of these was accepted and crashed (or silently ran) deeper in the pipeline
CASES = [
    ("ship outside the box", lambda d: d["ship"].update(lon=100.0), r"ship \(100.0, 0.0\) is outside the mission box"),
    ("link to itself", lambda d: d["links"][0].update(b="usv"), r"links/usv-uas-rf: a link from 'usv' to itself"),
    ("unknown radio", lambda d: d["links"][0].update(radio="rfd9000"), r"links/usv-uas-rf/radio: 'rfd9000' is not in platforms/radios.yaml"),
    ("unknown modem", lambda d: d["links"][1].update(modem="benthos_atm960_xx"),
     r"links/glider_eq-ship-acoustic/modem: 'benthos_atm960_xx' is not in platforms/modems.yaml"),
    ("airborne without a UAS", lambda d: d["links"][0].update(b="glider_eq"), r"links/usv-uas-rf/when: uas_airborne needs the UAS"),
    ("surfacing without a glider", lambda d: d["links"][1].update(a="usv"), r"links/glider_eq-ship-acoustic/when: surfacing needs a glider"),
    ("surfacing between ship and shore", lambda d: d["links"][1].update(a="shore", b="ship"), r"surfacing needs a glider"),
    ("rf with no when", lambda d: d["links"][0].pop("when"), r"links/usv-uas-rf/when: a rf link needs when"),
    ("iridium when surfacing", lambda d: d["links"][3].update(when="surfacing"), r"links/usv-shore-iridium/when: an iridium link"),
    ("hour 25", lambda d: vehicle(d, "uas")["sorties"].update(local_solar_time="25:99"), r"vehicles/\d/sorties/local_solar_time"),
    ("minute 60", lambda d: vehicle(d, "uas")["sorties"].update(local_solar_time="12:60"), r"local_solar_time"),
    ("no altitudes", lambda d: vehicle(d, "uas")["sorties"].update(altitudes_m=[]), r"vehicles/\d/sorties/altitudes_m"),
    ("required fraction 0", lambda d: d["links"][0].update(required_fraction=0), r"links/0/required_fraction"),
    ("one-point section", lambda d: vehicle(d, "usv")["task"].update(waypoints=[[-165.0, 0.0]]),
     r"vehicles/usv/task: mode 'section' needs at least two waypoints"),
]


@pytest.mark.parametrize("what,fn,msg", CASES, ids=[c[0] for c in CASES])
def test_validation_gaps_are_refused_with_the_field_and_the_fix(tmp_path, what, fn, msg):
    with pytest.raises(ConfigError, match=msg):
        load_mission(edit(tmp_path, fn))


def test_good_variants_of_the_checked_fields_still_load(tmp_path):
    def fn(d):
        d["links"][1].update(modem="benthos_atm960", when="always")                       # a registry key without a band; surfacing is optional
        d["links"][0].update(radio="rfd900x_fast", required_fraction=0.01)
        vehicle(d, "uas")["sorties"].update(local_solar_time="00:00", altitudes_m=[10])
        d["links"][3].pop("when")
    m = load_mission(edit(tmp_path, fn))
    assert m["links"][1]["modem"] == "benthos_atm960"
    load_mission(edit(tmp_path, lambda d: vehicle(d, "uas")["sorties"].update(local_solar_time="23:59")))


def test_a_mission_that_is_not_a_mapping_is_refused_by_the_schema_not_crashed_on(tmp_path):
    p = tmp_path / "list.yaml"
    p.write_text("[1, 2]")
    with pytest.raises(ConfigError, match=r"list.yaml: 1 problem\(s\) against cafe/schemas/mission.json"):
        load_mission(p)
    odd = doc()
    odd["environment"]["waves"] = "orca_umwm"
    odd["vehicles"][3]["sorties"] = 3
    with pytest.raises(ConfigError, match="problem"):
        load_mission(write(tmp_path, odd))
