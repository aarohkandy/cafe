"""cafe.pm.config: every refusal names the file and field, and each kind of bad mission is rejected."""
import copy
import pathlib
import re

import pytest
import yaml

from cafe.pm import config
from cafe.pm.config import ConfigError, load_mission, load_platform

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
    (mutate_section_without_waypoints, "mode 'section' needs waypoints"),
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
