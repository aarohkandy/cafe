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
    (mutate_station_without_point, "mode 'station' needs lon and lat of the station"),
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
    ("acoustic link ending at the shore", lambda d: d["links"][1].update(a="shore", b="ship"),
     r"links/glider_eq-ship-acoustic: the shore has no position; only iridium links can end at the shore, not acoustic"),
    ("rf link ending at the shore", lambda d: d["links"][0].update(b="shore"), r"links/usv-uas-rf: the shore has no position; .* not rf"),
    ("duplicate link id", lambda d: d["links"].append(dict(d["links"][0])), r"link ids \['usv-uas-rf'\] appear more than once; give each link its own id"),
    ("swapped latitude box", lambda d: d["box"].update(lat_min=5.0, lat_max=-5.0), r"box.lat_min \(5.0\) must be below box.lat_max \(-5.0\); swap them"),
    ("equal latitudes", lambda d: d["box"].update(lat_min=1.0, lat_max=1.0), r"box.lat_min \(1.0\) must be below box.lat_max \(1.0\)"),
    ("overlapping sorties", lambda d: vehicle(d, "uas")["sorties"].update(every_days=0.02),
     r"vehicles/uas/sorties/every_days: 0.02 d is shorter than duration_min x the platform's hard_stop_factor \(32 min\).*at least 0.0222"),
    ("absurd sortie period", lambda d: vehicle(d, "uas")["sorties"].update(every_days=1e-6), r"sorties/every_days: 1e-06 is less than the minimum of 0.01"),
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


def test_a_sortie_period_just_above_the_overlap_limit_and_an_iridium_link_to_the_shore_load(tmp_path):
    m = load_mission(edit(tmp_path, lambda d: vehicle(d, "uas")["sorties"].update(every_days=0.023, duration_min=20)))
    assert vehicle(m, "uas")["sorties"]["every_days"] == 0.023
    load_mission(edit(tmp_path, lambda d: vehicle(d, "uas")["sorties"].pop("every_days")))                       # the default period is one day
    assert any(lk["kind"] == "iridium" and "shore" in (lk["a"], lk["b"]) for lk in load_mission(DEMO)["links"])


# Review round 3 (M-1, M-3, M-15..M-18, M-20)
def _cli(tmp_path, fn, capsys):
    from cafe.pm import __main__ as cli
    rc = cli.main(["validate", "--mission", str(edit(tmp_path, fn))])
    return rc, capsys.readouterr().err


ROUND3 = [
    ("M-1 drift without heading_to", lambda d: vehicle(d, "glider_2n")["task"].pop("heading_to"),
     r"vehicles/glider_2n/task: drift needs heading_to, the compass heading the glider swims on"),
    ("M-1 heading_to out of range", lambda d: vehicle(d, "glider_2n")["task"].update(heading_to=361), r"heading_to"),
    ("M-3 usv drift", lambda d: vehicle(d, "usv")["task"].update(mode="drift", heading_to=0.0),
     r"vehicles/usv/task/mode: 'drift' is not a mode a usv flies; use one of \['station', 'section'\]"),
    ("M-3 uas with a task", lambda d: vehicle(d, "uas").update(task=dict(mode="station")), r"vehicles/uas/task: a UAS flies sorties and takes no task"),
    ("M-15 feb 30", lambda d: d["window"].update(end="2023-02-30T12:00:00Z"), r"window/end: '2023-02-30T12:00:00Z' is not a calendar time"),
    ("M-15 hour 24", lambda d: d["window"].update(end="2023-03-07T24:00:00Z"), r"window/end: .*not a calendar time"),
    ("M-15 month 13", lambda d: vehicle(d, "glider_eq")["deploy"].update(time="2023-13-01T12:00:00Z"),
     r"vehicles/glider_eq/deploy/time: .*not a calendar time"),
    ("M-16 radius_kms", lambda d: vehicle(d, "glider_eq")["task"].update(radius_kms=3), r"vehicles/\d/task: .*radius_kms"),
    ("M-16 every_day", lambda d: vehicle(d, "uas")["sorties"].update(every_day=2), r"vehicles/\d/sorties: .*every_day"),
    ("M-16 launch_rules typo", lambda d: vehicle(d, "uas")["launch_rules"].update(max_wind=3), r"vehicles/\d/launch_rules: .*max_wind"),
    ("M-16 shore typo", lambda d: d["shore"].update(lon=1), r"^error: .*\n\s+shore: .*lon"),
    ("M-16 sorties on a glider", lambda d: vehicle(d, "glider_eq").update(sorties=dict(local_solar_time="14:00", duration_min=20)),
     r"vehicles/glider_eq/sorties: only a UAS"),
    ("M-17 glider platform on a UAS", lambda d: vehicle(d, "uas").update(platform="seaglider"),
     r"vehicles/uas/platform: 'seaglider' is a glider platform file, but the vehicle has `base`.*quad_uas"),
    ("M-17 uas platform on a glider", lambda d: vehicle(d, "glider_eq").update(platform="quad_uas"),
     r"vehicles/glider_eq/platform: 'quad_uas' is a uas platform file, but the vehicle has no `base`"),
    ("M-17 acoustic with a UAS", lambda d: d["links"][1].update(a="uas", when="always"),
     r"links/glider_eq-ship-acoustic: an acoustic link cannot end at a UAS"),
    ("M-18 deploy 30 s before the end", lambda d: vehicle(d, "usv")["deploy"].update(time="2023-03-07T11:59:30Z"),
     r"vehicles/usv/deploy/time: .*less than 10 min before window.end.*by 2023-03-07T11:50:00Z"),
]


@pytest.mark.parametrize("what,fn,msg", ROUND3, ids=[c[0] for c in ROUND3])
def test_round3_refusals_name_the_field_and_exit_2_through_validate(tmp_path, capsys, what, fn, msg):
    rc, err = _cli(tmp_path, fn, capsys)
    assert rc == 2 and err.startswith("error: ") and re.search(msg, err, re.S), err


def test_round3_good_variants_load(tmp_path):
    load_mission(edit(tmp_path, lambda d: vehicle(d, "glider_2n")["task"].update(heading_to=360)))
    load_mission(edit(tmp_path, lambda d: vehicle(d, "usv")["task"].update(mode="station", lon=-165.0, lat=0.0, radius_km=5.0)))
    load_mission(edit(tmp_path, lambda d: vehicle(d, "usv")["deploy"].update(time="2023-03-07T11:50:00Z")))                # exactly one record before the end
    assert vehicle(load_mission(DEMO), "glider_2n")["task"]["heading_to"] == 0.0


def test_platform_class_is_the_one_rule():
    vs = [dict(platform="seaglider"), dict(platform="slocum"), dict(platform="saildrone_explorer"), dict(platform="quad_uas", base="s")]
    assert [config.platform_class(v) for v in vs] == ["glider", "glider", "usv", "uas"]
    assert config.MODES == {"glider": ("station", "section", "drift"), "usv": ("station", "section"), "uas": ()}


def test_a_platform_that_does_not_load_with_its_class_loader_is_a_config_error(tmp_path):
    bad = tmp_path / "odd_usv.yaml"
    bad.write_text("kind: wing_sail_usv\nsomething: {value: 1}\n")
    with pytest.raises(ConfigError, match=r"vehicles/usv/platform: .* does not load as a usv platform"):
        load_mission(edit(tmp_path, lambda d: vehicle(d, "usv").update(platform=str(bad))))


def test_the_schema_has_no_default_that_the_code_ignores():
    import json

    from cafe.pm import pipeline
    text = (config.SCHEMAS / "mission.json").read_text()
    assert '"default"' not in text
    assert json.loads(text)["properties"]["box"]["properties"]["pad_deg"]["maximum"] == pipeline.MAX_PAD_DEG


def test_every_shipped_mission_and_fixture_still_loads():
    for f in sorted((config.ROOT / "missions").glob("*.yaml")):
        load_mission(f)


# Review round 4 (M-11, M-13, M-14, M-15)
def _glider_link(d, kind, when, **kw):
    d["links"].append(dict(id="gl-x", a="glider_eq", b="shore" if kind == "iridium" else "usv", kind=kind, required_fraction=0.9, **kw))
    if when:
        d["links"][-1]["when"] = when


GLIDER_RADIO = r"links/gl-x/when: a glider's radio and Iridium antenna work only at the surface"
ROUND4 = [
    ("M-11 glider iridium always", lambda d: _glider_link(d, "iridium", "always"),
     r"links/gl-x/when: a glider's radio and Iridium antenna work only at the surface: use when: surfacing"),
    ("M-11 glider iridium no when", lambda d: _glider_link(d, "iridium", None), GLIDER_RADIO),
    ("M-11 glider rf always", lambda d: _glider_link(d, "rf", "always", radio="rfd900x"), GLIDER_RADIO),
    ("M-11 uas-glider rf airborne",
     lambda d: d["links"].append(dict(id="gl-x", a="uas", b="glider_eq", kind="rf", radio="rfd900x", when="uas_airborne", required_fraction=0.9)),
     GLIDER_RADIO),
    ("M-13 no launch fits", lambda d: d["window"].update(end="2023-03-01T13:00:00Z"),
     r"vehicles/uas/sorties: no launch fits in the window \(local_solar_time 14:00 at lon -165 is 01:00Z, a launch needs 32 min before window.end\)"),
    ("M-14 ship = vehicle", lambda d: d["ship"].update(id="usv"),
     r"ids must be unique across vehicles, ship and shore; 'usv' is used by vehicles/usv and ship"),
    ("M-14 shore = vehicle", lambda d: d["shore"].update(id="glider_eq"), r"'glider_eq' is used by vehicles/glider_eq and shore"),
    ("M-14 shore = ship", lambda d: d["shore"].update(id="ship"), r"'ship' is used by ship and shore"),
    ("M-15 1000 m", lambda d: vehicle(d, "uas")["sorties"].update(altitudes_m=[10, 1000]),
     r"sorties/altitudes_m: 1000: the stored WRF levels end at about 400 m; the wind above that is not known"),
]


@pytest.mark.parametrize("what,fn,msg", ROUND4, ids=[c[0] for c in ROUND4])
def test_round4_refusals_name_the_field_and_the_fix(tmp_path, what, fn, msg):
    with pytest.raises(ConfigError, match=msg):
        load_mission(edit(tmp_path, fn))


def test_round4_good_variants_load(tmp_path):
    for kind, kw in (("iridium", {}), ("rf", dict(radio="rfd900x"))):                          # a glider's radio and Iridium work when it surfaces
        m = load_mission(edit(tmp_path, lambda d, kind=kind, kw=kw: _glider_link(d, kind, "surfacing", **kw)))
        assert m["links"][-1]["when"] == "surfacing"
    load_mission(edit(tmp_path, lambda d: vehicle(d, "uas")["sorties"].update(altitudes_m=[10, 400])))             # the top stored level itself is allowed
    load_mission(edit(tmp_path, lambda d: d["window"].update(end="2023-03-02T02:00:00Z")))                         # the 01:00Z launch (and 32 min) fits
    with pytest.raises(ConfigError, match=r"links/usv-shore-iridium/when: an iridium link"):                       # surfacing needs a glider at one end
        load_mission(edit(tmp_path, lambda d: d["links"][3].update(when="surfacing")))


# (path in the demo document, the slash path the message must name); a string step picks the list item with that id
NONFINITE = [(("box", "pad_deg"),) * 2, (("ship", "antenna_height_m"),) * 2, (("ship", "transducer_depth_m"),) * 2,
             *[((("vehicles", v, *rest),) * 2) for v, rest in (("glider_eq", ("task", "radius_km")), ("glider_eq", ("task", "lost_after_h")),
                                                             ("glider_eq", ("task", "dive_depth_m")), ("glider_2n", ("task", "heading_to")),
                                                             ("usv", ("task", "track_tolerance_km")), ("usv", ("task", "becalmed_after_h")),
                                                             ("uas", ("sorties", "every_days")), ("uas", ("launch_rules", "max_mean_wind_ms")),
                                                             ("uas", ("sorties", "altitudes_m", 0)))],
             (("links", "usv-uas-rf", "required_fraction"),) * 2]


@pytest.mark.parametrize("val", [float("nan"), float("inf")], ids=["nan", "inf"])
@pytest.mark.parametrize("keys,named", NONFINITE, ids=["/".join(map(str, k)) for k, _ in NONFINITE])
def test_r5_m3_a_non_finite_number_is_refused_naming_the_field(tmp_path, keys, named, val):
    d = doc()
    cur = d
    for k in keys[:-1]:
        cur = next(x for x in cur if x["id"] == k) if isinstance(cur, list) and isinstance(k, str) else cur[k]
    cur[keys[-1]] = val
    with pytest.raises(ConfigError, match=re.escape("/".join(map(str, named))) + r": .* is not a finite number"):
        load_mission(write(tmp_path, d))


@pytest.mark.parametrize("which", ["lat", "lon"])
def test_r5_m17_a_station_without_lon_or_lat_is_a_config_error(tmp_path, which):
    with pytest.raises(ConfigError, match=r"vehicles/glider_eq/task: mode 'station' needs lon and lat"):
        load_mission(edit(tmp_path, lambda d: vehicle(d, "glider_eq")["task"].pop(which)))


def test_r5_m18_a_duplicate_key_is_refused_with_its_line(tmp_path):
    p = tmp_path / "m.yaml"
    p.write_text(DEMO.read_text() + "verdict: {go: 0.5, nogo: 0.1}\n")
    line = len(DEMO.read_text().splitlines()) + 1
    with pytest.raises(ConfigError, match=rf"m.yaml: line {line}: duplicate key 'verdict'; a later value would silently replace"):
        load_mission(p)


def test_r5_m18_a_leading_zero_number_is_refused_not_read_as_octal(tmp_path):
    p = tmp_path / "m.yaml"
    p.write_text(DEMO.read_text().replace("seed: 20230301", "seed: 010"))
    with pytest.raises(ConfigError, match=r"line \d+: 010 is read as octal 8; write 8, or quote it for a string"):
        load_mission(p)
    p.write_text(DEMO.read_text().replace("seed: 20230301", "seed: 0"))                  # a plain zero, a quoted string and a decimal float are fine
    assert load_mission(p)["seed"] == 0


def test_r5_m18_a_merge_key_is_not_a_duplicate_and_the_shipped_files_load(tmp_path):
    p = tmp_path / "x.yaml"
    p.write_text("a: &a {k: 1}\nb: {<<: *a, k: 2}\n")
    assert config._yaml(p)["b"] == {"k": 2}
    for f in [*(config.ROOT / "missions").glob("*.yaml"), *config.PLATFORMS.glob("*.yaml"), *config.CONFIG.glob("*.yaml")]:
        assert config._yaml(f) is not None


# ---- review round 6: M-9, M-11, M-24

R6_M9 = [
    ("negative max wind", lambda d: vehicle(d, "uas")["launch_rules"].update(max_mean_wind_ms=-5), r"vehicles/\d/launch_rules/max_mean_wind_ms"),
    ("zero max wind", lambda d: vehicle(d, "uas")["launch_rules"].update(max_mean_wind_ms=0), r"vehicles/\d/launch_rules/max_mean_wind_ms"),
    ("negative gust-front window", lambda d: vehicle(d, "uas")["launch_rules"].update(no_gust_front_within_min=-1),
     r"vehicles/\d/launch_rules/no_gust_front_within_min"),
    ("dive 1e6 m", lambda d: vehicle(d, "glider_eq")["task"].update(dive_depth_m=1e6), r"vehicles/\d/task/dive_depth_m"),
    ("dive 1 mm", lambda d: vehicle(d, "glider_eq")["task"].update(dive_depth_m=0.001), r"vehicles/\d/task/dive_depth_m"),
    ("radius 1e-9 km", lambda d: vehicle(d, "glider_eq")["task"].update(radius_km=1e-9), r"vehicles/\d/task/radius_km"),
    ("radius 1e9 km", lambda d: vehicle(d, "glider_eq")["task"].update(radius_km=1e9), r"vehicles/\d/task/radius_km"),
    ("duplicate altitudes", lambda d: vehicle(d, "uas")["sorties"].update(altitudes_m=[2, 2, 2]), r"vehicles/\d/sorties/altitudes_m"),
    ("unsorted altitudes", lambda d: vehicle(d, "uas")["sorties"].update(altitudes_m=[100, 10]),
     r"vehicles/uas/sorties/altitudes_m: \[100, 10\] does not rise"),
    ("dive 20 m on the Seaglider", lambda d: vehicle(d, "glider_eq")["task"].update(dive_depth_m=20.0),
     r"vehicles/glider_eq/task/dive_depth_m: 20 m is outside what the seaglider 'seaglider' dives: min_dive_m 30 m to rating_m 1000 m"),
    ("dive below the rating", lambda d: vehicle(d, "glider_eq")["task"].update(dive_depth_m=1500.0),
     r"task/dive_depth_m: 1500 m is outside .* rating_m 1000 m"),
]


@pytest.mark.parametrize("what,fn,msg", R6_M9, ids=[c[0] for c in R6_M9])
def test_r6_m9_numbers_that_cannot_be_right_are_refused_naming_the_field(tmp_path, what, fn, msg):
    with pytest.raises(ConfigError, match=msg):
        load_mission(edit(tmp_path, fn))


def test_r6_m9_the_edges_of_the_ranges_and_the_shipped_missions_still_load(tmp_path):
    def fn(d):
        vehicle(d, "glider_eq")["task"].update(dive_depth_m=30.0, radius_km=1000.0, lost_after_h=720.0)
        vehicle(d, "glider_2n")["task"].update(dive_depth_m=1000.0)
        vehicle(d, "uas")["launch_rules"].update(max_mean_wind_ms=60, no_gust_front_within_min=0)
        vehicle(d, "uas")["sorties"].update(altitudes_m=[2, 10, 400])
    load_mission(edit(tmp_path, fn))
    for f in (config.ROOT / "missions").glob("*.yaml"):
        load_mission(f)


def test_r6_m11_a_lab_hycom_store_without_a_path_is_refused_at_validation(tmp_path):
    with pytest.raises(ConfigError, match=r"m.yaml: environment/ocean: source 'lab_hycom' needs a path to the lab's ingested HYCOM store; add path: <store>"):
        load_mission(edit(tmp_path, lambda d: d["environment"].update(ocean=dict(source="lab_hycom"))))
    with pytest.raises(ConfigError, match=r"environment/ocean/temperature_kind: it belongs to the lab's HYCOM .*remove it"):
        load_mission(edit(tmp_path, lambda d: d["environment"]["ocean"].update(temperature_kind="in_situ")))
    m = load_mission(edit(tmp_path, lambda d: d["environment"].update(ocean=dict(source="lab_hycom", path="/data/lab.zarr", temperature_kind="potential"))))
    assert m["environment"]["ocean"]["path"] == "/data/lab.zarr"


def test_r6_m24_an_unquoted_timestamp_and_an_empty_value_say_how_to_fix_them(tmp_path):
    p = tmp_path / "t.yaml"
    p.write_text(DEMO.read_text().replace('start: "2023-03-01T12:00:00Z"', "start: 2023-03-01T12:00:00Z"))
    with pytest.raises(ConfigError, match=r'window/start: an unquoted timestamp is read by YAML as a time; put it in quotes, e.g. "2023-03-01T12:00:00Z"') as e:
        load_mission(p)
    assert "datetime" not in str(e.value)
    p.write_text(re.sub(r"description: >\n(  .*\n)+", "description:\n", DEMO.read_text()))
    with pytest.raises(ConfigError, match=r"description: is empty; give it a value or remove the key"):
        load_mission(p)


# ---- review round 7: M-1, M-32, M-33, M-34, M-47 (the bounds of M-9)

def test_r7_m1_a_mission_loaded_only_to_be_read_leaves_the_verdict_cut_offs_alone(tmp_path):
    load_mission(edit(tmp_path, lambda d: d["verdict"].update(go=0.8, nogo=0.5)))
    assert (I.P_FAIL_GO, I.P_FAIL_NOGO) == (pytest.approx(0.2), 0.5)
    load_mission(DEMO, set_verdict=False)
    assert (I.P_FAIL_GO, I.P_FAIL_NOGO) == (pytest.approx(0.2), 0.5)                    # still the first mission's
    load_mission(DEMO)
    assert (I.P_FAIL_GO, I.P_FAIL_NOGO) == (0.10, 0.40)


def prime(d, lo=-15.0, hi=15.0, at=-5.0):
    """The reviewer's prime.yaml: the demo with its box across the prime meridian and everything inside it."""
    d["box"].update(lon_min=lo, lon_max=hi)
    d["ship"].update(lon=at)
    for v in d["vehicles"]:
        if "deploy" in v:
            v["deploy"]["lon"] = at
        t = v.get("task", {})
        if "lon" in t:
            t["lon"] = at
        if "waypoints" in t:
            t["waypoints"] = [[at, -1.0], [at, 1.0]]


def test_r7_m32_a_box_across_0_deg_e_is_refused_at_validation_naming_the_box(tmp_path):
    with pytest.raises(ConfigError, match=r"m.yaml: box \(.*\): the box \(with its pad of 2 deg\) crosses 0 deg E; the GLBy ocean fetch cannot cross it"):
        load_mission(edit(tmp_path, prime))
    load_mission(edit(tmp_path, lambda d: prime(d, 2.0, 10.0, 5.0)))          # pad 2: the west edge is 0
    load_mission(DEMO)                                                                  # the dateline box is one request


def test_r7_m33_a_mission_name_is_at_most_64_characters_and_its_paths_can_be_made(tmp_path):
    with pytest.raises(ConfigError, match=r"name: .*too long"):
        load_mission(edit(tmp_path, lambda d: d.update(name="a" * 65)))
    m = load_mission(edit(tmp_path, lambda d: d.update(name="a" * 64)))
    for part in (m["name"], f"gofs_{m['name']}.zarr"):
        (tmp_path / "cache" / part).mkdir(parents=True)


def test_r7_m34_a_mission_file_that_is_not_utf8_text_is_a_config_error(tmp_path):
    p = tmp_path / "bin.yaml"
    p.write_bytes(bytes(range(256)))
    with pytest.raises(ConfigError, match=r"bin.yaml: not a UTF-8 text file \(invalid start byte at byte 128\); the mission and platform files are UTF-8 YAML"):
        load_mission(p)
    with pytest.raises(ConfigError, match=r"bin.yaml: not a UTF-8 text file"):
        load_platform(p)
    with pytest.raises(ConfigError, match=r"cannot be read"):
        load_mission(tmp_path)                                                          # a directory exists but cannot be read as a file


R7_M47 = [
    ("max wind 61", lambda d: vehicle(d, "uas")["launch_rules"].update(max_mean_wind_ms=61), r"vehicles/\d/launch_rules/max_mean_wind_ms"),
    ("lost after 721 h", lambda d: vehicle(d, "glider_eq")["task"].update(lost_after_h=721), r"vehicles/\d/task/lost_after_h"),
    ("lost after -5 h", lambda d: vehicle(d, "glider_eq")["task"].update(lost_after_h=-5), r"vehicles/\d/task/lost_after_h"),
    ("track tolerance 1001 km", lambda d: vehicle(d, "usv")["task"].update(track_tolerance_km=1001), r"vehicles/\d/task/track_tolerance_km"),
    ("gust-front window 1441 min", lambda d: vehicle(d, "uas")["launch_rules"].update(no_gust_front_within_min=1441),
     r"vehicles/\d/launch_rules/no_gust_front_within_min"),
]


@pytest.mark.parametrize("what,fn,msg", R7_M47, ids=[c[0] for c in R7_M47])
def test_r7_m47_the_other_bounds_of_r6_m9_are_each_refused_naming_their_field(tmp_path, what, fn, msg):
    with pytest.raises(ConfigError, match=msg):
        load_mission(edit(tmp_path, fn))
