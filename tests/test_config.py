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


def test_fmt_box_says_the_wrap_the_pad_and_the_hemisphere_and_the_refusals_use_it(tmp_path):
    """Round 9 M-14: the box in a refusal was the dict repr. One helper, used by the config refusals (ship and point) and the what-if one."""
    assert config.fmt_box(dict(lon_min=165.0, lon_max=-165.0, lat_min=-5.0, lat_max=5.0, pad_deg=2.0)) == \
        "lon 165 E to 165 W (across the antimeridian), lat -5 to 5, pad 2 deg"
    assert config.fmt_box(dict(lon_min=-170.0, lon_max=-160.5, lat_min=0.0, lat_max=7.5)) == "lon 170 W to 160.5 W, lat 0 to 7.5"
    assert config.fmt_box(dict(lon_min=10.0, lon_max=20.0, lat_min=-5.0, lat_max=5.0)) == "lon 10 E to 20 E, lat -5 to 5"
    d = yaml.safe_load((config.ROOT / "missions" / "ci_fixture.yaml").read_text())
    d["ship"]["lon"] = 100.0
    with pytest.raises(ConfigError) as e:
        load_mission(write(tmp_path, d))
    assert "lon_min" not in str(e.value) and "{" not in str(e.value) and "outside the mission box (lon 166.5 W to 163.5 W, lat -1.5 to 1.5" in str(e.value)
    e2 = copy.deepcopy(d)
    e2["ship"]["lon"] = -165.0
    vehicle(e2, "glider_eq")["deploy"]["lon"] = 100.0
    with pytest.raises(ConfigError) as e:
        load_mission(write(tmp_path, e2))
    assert "lon_min" not in str(e.value) and "{" not in str(e.value) and "outside the mission box (lon " in str(e.value)


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
    ("r9_m13_two_identical_waypoints", lambda d: vehicle(d, "usv")["task"].update(waypoints=[[-165.0, 0.0], [-165.0, 0.0]]),
     r"vehicles/usv/task/waypoints/1: \[-165.0, 0.0\] is the same point as waypoints/0; a leg of zero length"),
    ("r9_m13_a_repeated_last_waypoint", lambda d: vehicle(d, "usv")["task"].update(waypoints=[[-165.0, -1.0], [-165.0, 1.0], [-165.0, 1.0]]),
     r"vehicles/usv/task/waypoints/2: \[-165.0, 1.0\] is the same point as waypoints/1"),
    ("r9_m20_equal_box_longitudes", lambda d: d["box"].update(lon_min=-165.0, lon_max=-165.0),
     r"box.lon_min and box.lon_max are both -165.0: the box has no width"),
    ("r9_m33_gofs_path_without_zarr", lambda d: d["environment"]["ocean"].update(path="/data/ocean/my_gofs"),
     r"environment/ocean/path: '/data/ocean/my_gofs' does not end in .zarr; the GOFS fetch writes <name>.zarr"),
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
     r"ids must be unique across vehicles, links, ship and shore; 'usv' is used by vehicles/usv and ship"),
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
    with pytest.raises(ConfigError, match=r"m.yaml: box lat .*, lon .*: the box \(with its pad of 2 deg\) crosses 0 deg E; the GLBy ocean fetch cannot"):
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


# ---- review round 8: M-18 (the bounds of the ship block), M-39 (the YAML slips that were refused with a number the user never typed)

R8_M18 = [
    ("antenna 1000 m", lambda d: d["ship"].update(antenna_height_m=1000), r"ship/antenna_height_m"),
    ("antenna 100.5 m", lambda d: d["ship"].update(antenna_height_m=100.5), r"ship/antenna_height_m"),
    ("antenna 0 m", lambda d: d["ship"].update(antenna_height_m=0), r"ship/antenna_height_m"),
    ("antenna 0.1 m", lambda d: d["ship"].update(antenna_height_m=0.1), r"ship/antenna_height_m"),
    ("transducer 20000 m", lambda d: d["ship"].update(transducer_depth_m=20000), r"ship/transducer_depth_m"),
    ("transducer 100.5 m", lambda d: d["ship"].update(transducer_depth_m=100.5), r"ship/transducer_depth_m"),
    ("transducer -1 m", lambda d: d["ship"].update(transducer_depth_m=-1), r"ship/transducer_depth_m"),
]


@pytest.mark.parametrize("what,fn,msg", R8_M18, ids=[c[0] for c in R8_M18])
def test_r8_m18_the_ship_antenna_and_transducer_are_bounded_on_both_sides_and_named(tmp_path, what, fn, msg):
    with pytest.raises(ConfigError, match=msg):
        load_mission(edit(tmp_path, fn))


def test_r8_m18_the_edges_of_the_ship_bounds_and_the_shipped_missions_load(tmp_path):
    for lo, hi in ((0.5, 0.0), (100.0, 100.0)):
        load_mission(edit(tmp_path, lambda d, lo=lo, hi=hi: d["ship"].update(antenna_height_m=lo, transducer_depth_m=hi)))
    for f in (config.ROOT / "missions").glob("*.yaml"):
        load_mission(f)


def unquoted(tmp_path, old, new):
    """The demo text with `old` replaced by `new` (the way a lab user types it), written out."""
    text = DEMO.read_text()
    assert text.count(old) == 1
    p = tmp_path / "u.yaml"
    p.write_text(text.replace(old, new))
    return p


LINK = "{id: glider_eq-ship-acoustic, a: glider_eq, b: "
TIME = 'local_solar_time: "14:00"'
R8_M39 = [
    (TIME, "local_solar_time: 14:00",
     r'sorties/local_solar_time: YAML reads an unquoted HH:MM as a number \(840 = 14:00 as minutes\); put it in quotes, e.g. "14:00"'),
    (TIME, "local_solar_time: 14:00:00", r"sorties/local_solar_time: YAML reads an unquoted time as the number 50400; put it in quotes"),
    (LINK + "ship", LINK + "no", r"links/\d/b: YAML reads an unquoted no/yes/on/off as false; put it in quotes"),
    ("radius_km: 5.0", 'radius_km: "5"', r"task/radius_km: the number is written in a form YAML reads as text \('5'\); write 5"),   # 5e0 is a number since L0
    ("radius_km: 5.0", "radius_km: five", r"task/radius_km: 'five' is not of type 'number'"),
]


@pytest.mark.parametrize("old,new,msg", R8_M39, ids=["hhmm", "hhmmss", "no", "quoted", "text"])
def test_r8_m39_an_unquoted_time_a_no_and_a_quoted_number_say_why(tmp_path, old, new, msg):
    with pytest.raises(ConfigError, match=msg):
        load_mission(unquoted(tmp_path, old, new))


def test_r8_m39_the_quoted_forms_load(tmp_path):
    load_mission(unquoted(tmp_path, "radius_km: 5.0", "radius_km: 5"))
    load_mission(unquoted(tmp_path, 'local_solar_time: "14:00"', 'local_solar_time: "09:30"'))
    assert config._yaml(unquoted(tmp_path, 'local_solar_time: "14:00"', "local_solar_time: 14:00"))["vehicles"][3]["sorties"]["local_solar_time"] == 840


# ---- review round 8 (K batch)

def test_r8_m42_lost_after_h_of_zero_is_refused_naming_above_0(tmp_path):
    """D-9: `minimum: 0` in place of `exclusiveMinimum: 0` left every test green; DECISIONS 387 says 'above 0'."""
    with pytest.raises(ConfigError, match=r"vehicles/\d/task/lost_after_h"):
        load_mission(edit(tmp_path, lambda d: vehicle(d, "glider_eq")["task"].update(lost_after_h=0)))


def test_r8_m16_a_defaults_leaf_needs_a_source_or_an_assumed_why_but_not_an_entry_source():
    ok = dict(defaults=dict(a=dict(value=1.0, unit="dB", assumed=True, why="w"), b=2.0))
    assert config.table_provenance(ok) == []
    assert config.table_provenance(dict(defaults=dict(a=dict(value=1.0, unit="dB")))) == ["defaults.a"]
    assert config.table_provenance(dict(modems=dict(m=dict(bands=dict(x=dict(value=1)))))) == ["modems.m.source", "modems.m.bands.x"]


def test_r8_m22_json_object_refuses_damage_and_other_json(tmp_path):
    p = tmp_path / "x.json"
    p.write_text('{"a": 1}')
    assert config.json_object(p) == {"a": 1}
    for text, why in (('{"a": 1, "b', "Unterminated"), ("[]", "it holds list"), ("null", "it holds NoneType")):
        p.write_text(text)
        with pytest.raises(ConfigError, match=rf"x.json: not a JSON object .*{why}.*run it again \(--fresh\)"):
            config.json_object(p)
    p.write_bytes(b"\xff\xfe")
    with pytest.raises(ConfigError, match="not a JSON object"):
        config.json_object(p)
    with pytest.raises(ConfigError, match="not a JSON object"):
        config.json_object(tmp_path / "missing.json")


# ---- review round 8, M-25: an empty platform file is left to the class loader (and `hangar`) to name; a list is refused here
def test_r8_m25_an_empty_platform_file_loads_as_nothing_and_a_scalar_document_is_refused(tmp_path):
    empty = tmp_path / "empty.yaml"
    empty.write_text("# a failed copy\n")
    assert config.load_platform(str(empty)) == {}
    scalar = tmp_path / "scalar.yaml"
    scalar.write_text("42\n")
    with pytest.raises(ConfigError, match=r"expected a mapping of platform parameters \(the file is empty or not a mapping\)"):
        config.load_platform(str(scalar))
    with pytest.raises(ConfigError, match=r"the file is empty or not a mapping\); a platform file has `params:`"):
        config.platform_doc(str(empty))


# ---- review round 8, lead item L0: one YAML reader for every file

def test_r8_l0_an_exponent_without_a_dot_is_a_number_in_every_file_and_the_hint_names_a_spelling_that_loads(tmp_path):
    """YAML 1.1 reads 1e-6, 5e0 and 1e+7 as text; M-11's hint said 'use 1e-6', which a platform file then refused as a string."""
    from cafe.pm.physics import HINTS, uas
    from cafe.pm.stats import sampling
    f = tmp_path / "n.yaml"
    f.write_text("a: 1e-6\nb: 5e0\nc: 1e+7\nd: -2E3\ne: 1_0e1\nf: '1e-6'\ng: 1.0e-6\nh: 1e\ni: e5\nj: 1e-6x\n")
    got = config.read_yaml(f)
    assert [got[k] for k in "abcdeg"] == [1e-6, 5.0, 1e7, -2000.0, 100.0, 1e-6] and all(type(got[k]) is float for k in "abcdeg")
    assert got["f"] == "1e-6" and got["h"] == "1e" and got["i"] == "e5" and got["j"] == "1e-6x"                   # text stays text
    plat = (config.ROOT / "platforms" / "quad_uas.yaml").read_text()
    assert "{value: 0.10, unit: ohm" in plat
    q = tmp_path / "q.yaml"
    q.write_text(plat.replace("{value: 0.10, unit: ohm", "{value: 1e-6, unit: ohm"))
    assert uas.load_platform(str(q))["battery"]["r_int_ohm"] == 1e-6                                       # refused as '1e-6' before
    assert "1e-6" in HINTS["r_int_ohm"]
    pt = tmp_path / "p.yaml"
    pt.write_text((config.ROOT / "config" / "perturbations.yaml").read_text().replace("  lo: -0.35\n  hi: -0.30\n", "  lo: -3.5e-1\n  hi: -3e-1\n", 1))
    assert sampling.load_perturbations(pt)["usv_vpp_bias_brief"]["hi"] == -0.30 and sampling.to_marginals(sampling.load_perturbations(pt))
    m = load_mission(unquoted(tmp_path, "radius_km: 5.0", "radius_km: 5e0"))
    assert any(v.get("task", {}).get("radius_km") == 5.0 for v in m["vehicles"])


def test_r8_l0_no_module_reads_yaml_but_through_config_read_yaml():
    """The sampling priors, the sub-grid assumptions, the credibility report and the conventions overlay read YAML with plain safe_load: a repeated key
    (the later block won) or a leading-zero number passed there and was refused by config._yaml in another stage."""
    pattern = re.compile(r"yaml\.(safe_)?load\(|__import__\(.yaml.\)")
    hits = [str(f.relative_to(config.ROOT)) for f in (config.ROOT / "cafe" / "pm").rglob("*.py") if f.name != "config.py" and pattern.search(f.read_text())]
    assert hits == []


DUP = "usv_vpp_bias:\n  dist: uniform\n  lo: -0.5\n  hi: 0.5\n  value: 0.0\n  unit: x\n  citation: c\n  kind: prior\n"


def test_r8_l0_a_repeated_key_or_an_octal_looking_number_is_refused_by_every_reader(tmp_path):
    from cafe.pm import credibility, dtmb5415
    from cafe.pm.env import conventions, subgrid
    from cafe.pm.stats import sampling
    pert = tmp_path / "perturbations.yaml"
    pert.write_text((config.ROOT / "config" / "perturbations.yaml").read_text() + DUP)
    with pytest.raises(ConfigError, match="duplicate key 'usv_vpp_bias'"):
        sampling.load_perturbations(pert)
    with pytest.raises(ConfigError, match="duplicate key 'usv_vpp_bias'"):
        config._yaml(pert)                                                         # as before: the two readers agree now
    octal = tmp_path / "o.yaml"
    octal.write_text("dtmb5415.u_D_rel:\n  value: 010\n")
    with pytest.raises(ConfigError, match="010 is read as octal 8"):
        dtmb5415.assumed("u_D_rel", octal)
    assump = tmp_path / "assumptions.yaml"
    twice_x = "subgrid.x:\n  value: 1\n  unit: m\n  why: w\n  replace_with: r\nsubgrid.x:\n  value: 2\n"
    assump.write_text((config.ROOT / "config" / "assumptions.yaml").read_text() + twice_x)
    with pytest.raises(ConfigError, match="duplicate key 'subgrid.x'"):
        config.read_yaml(assump)
    twice = tmp_path / "twice.yaml"
    twice.write_text("dtmb5415.u_D_rel:\n  value: 0.01\ndtmb5415.u_D_rel:\n  value: 0.02\n")
    with pytest.raises(ConfigError, match="duplicate key 'dtmb5415.u_D_rel'"):
        dtmb5415.assumed("u_D_rel", twice)
    overlay = tmp_path / "overlay.yaml"
    overlay.write_text("waves:\n  direction_convention: umwm\nwaves:\n  direction_convention: compass_from\n")
    conventions._overlay_wave_convention.cache_clear()
    with pytest.raises(ConfigError, match="duplicate key 'waves'"):
        conventions._overlay_wave_convention(str(overlay))
    root = tmp_path / "root"
    (root / "config").mkdir(parents=True)
    (root / "config" / "assumptions.yaml").write_text(assump.read_text())
    (root / "config" / "perturbations.yaml").write_text(pert.read_text())
    with pytest.raises(ConfigError, match="duplicate key"):
        credibility.assumed_inputs(root=root, run=None)
    sub = tmp_path / "cfg"
    sub.mkdir()
    (sub / "assumptions.yaml").write_text(assump.read_text())
    old = subgrid._CFG_DIR
    subgrid._assumptions.cache_clear()
    try:
        subgrid._CFG_DIR = sub
        with pytest.raises(ConfigError, match="duplicate key 'subgrid.x'"):
            subgrid._assumptions()
    finally:
        subgrid._CFG_DIR = old
        subgrid._assumptions.cache_clear()


# ---------------------------------------------------------------------------------------------------------------- round 9, batch A

def test_r9_m13_a_section_may_return_to_an_earlier_waypoint_and_a_station_task_keeps_its_waypoints(tmp_path):
    load_mission(edit(tmp_path, lambda d: vehicle(d, "usv")["task"].update(waypoints=[[-165.0, -1.0], [-165.0, 1.0], [-165.0, -1.0]])))
    load_mission(edit(tmp_path, lambda d: vehicle(d, "glider_2n")["task"].update(waypoints=[[-165.0, 1.0], [-165.0, 1.0]])))      # drift ignores them


def test_r9_m20_a_box_across_the_dateline_is_not_empty_and_the_equal_longitudes_message_is_the_one_a_user_sees(tmp_path):
    assert load_mission(DEMO)["box"]["lon_min"] > load_mission(DEMO)["box"]["lon_max"]
    with pytest.raises(ConfigError, match=r"m.yaml: box.lon_min and box.lon_max are both 165.0: the box has no width and nothing fits in it;"):
        load_mission(edit(tmp_path, lambda d: d["box"].update(lon_max=165.0)))


def test_r9_m33_a_gofs_path_ending_in_zarr_loads_and_so_does_no_path(tmp_path):
    for path in ("/data/ocean/my_gofs.zarr", "/data/ocean/gofs_run.v2.zarr"):
        m = load_mission(edit(tmp_path, lambda d, path=path: d["environment"]["ocean"].update(path=path)))
        assert m["environment"]["ocean"]["path"] == path
    assert "path" not in load_mission(DEMO)["environment"]["ocean"]


def test_r9_m2_a_yaml_alias_is_unshared_at_load_and_the_mission_hash_does_not_move(tmp_path):
    d = doc()
    eq, two = vehicle(d, "glider_eq"), vehicle(d, "glider_2n")
    eq["task"] = dict(eq["task"], dive_depth_m=500.0)                          # a depth both glider platforms dive
    two["deploy"], two["task"] = eq["deploy"], eq["task"]                      # one dict in two places: safe_dump writes an anchor and an alias
    p = write(tmp_path, d)
    assert "&id" in p.read_text() and "*id" in p.read_text()
    m = load_mission(p)
    a, b = vehicle(m, "glider_eq"), vehicle(m, "glider_2n")
    assert a["deploy"] == b["deploy"] and a["deploy"] is not b["deploy"] and a["task"] is not b["task"]
    plain = copy.deepcopy(d)
    plain["vehicles"] = [dict(v, deploy=dict(v["deploy"]), task=dict(v["task"])) if "deploy" in v else v for v in plain["vehicles"]]
    assert "&id" not in write(tmp_path, plain, "plain.yaml").read_text()
    other = load_mission(tmp_path / "plain.yaml")
    assert config.digest({k: v for k, v in m.items() if k != "_path"}) == config.digest({k: v for k, v in other.items() if k != "_path"})
    walk, seen = [m], []
    while walk:                                                                  # no list or mapping appears twice anywhere in the mission
        n = walk.pop()
        if isinstance(n, (dict, list)):
            seen.append(id(n))
            walk += list(n.values()) if isinstance(n, dict) else n
    assert len(seen) == len(set(seen))


def test_r9_m1_a_platform_given_as_a_path_resolves_to_that_path_and_a_name_to_platforms():
    f = config.ROOT / "platforms" / "seaglider.yaml"
    assert config.platform_path("seaglider") == f and config.platform_path(str(f)) == f and config.platform_path(f) == f
    assert config.platform_path("platforms/seaglider.yaml") == pathlib.Path("platforms/seaglider.yaml")      # a path is kept as it is given
    assert config.platform_path("mine.yml") == pathlib.Path("mine.yml")
    assert config.platform_path("x.v2") == config.PLATFORMS / "x.v2.yaml"                                    # a dotted name is not a suffix
    assert load_platform(str(f)) == load_platform("seaglider")


def test_r9_m14_a_box_in_a_message_is_words_not_a_dict(tmp_path):
    assert config.fmt_box(dict(lon_min=165.0, lon_max=-165.0, lat_min=-5.0, lat_max=5.0, pad_deg=2.0)) == \
        "lon 165 E to 165 W (across the antimeridian), lat -5 to 5, pad 2 deg"
    assert config.fmt_box(dict(lon_min=10.5, lon_max=20.0, lat_min=-5.0, lat_max=5.5)) == "lon 10.5 E to 20 E, lat -5 to 5.5"
    with pytest.raises(ConfigError) as e:
        load_mission(edit(tmp_path, lambda d: d["ship"].update(lon=100.0)))
    assert "outside the mission box (lon 165 E to 165 W (across the antimeridian), lat -5 to 5, pad 2 deg)" in str(e.value)
    with pytest.raises(ConfigError) as e:
        load_mission(edit(tmp_path, lambda d: vehicle(d, "glider_eq")["deploy"].update(lon=100.0)))
    assert "{" not in str(e.value) and "lon_min" not in str(e.value)


def test_l0_write_json_replaces_a_file_whole_or_not_at_all(tmp_path, monkeypatch):
    """Round 9, M-4 sibling: the writer of every slow-run receipt. A write cut short leaves the old file; none is left behind as a temporary afterwards."""
    f = tmp_path / "r.json"
    config.write_json(f, {"a": 1}, indent=1)
    assert config.json_object(f) == {"a": 1} and not (tmp_path / "r.json.tmp").exists()
    orig = pathlib.Path.write_text

    def cut(self, text, *a, **k):
        orig(self, text[:3], *a, **k)
        raise OSError("killed")
    monkeypatch.setattr(pathlib.Path, "write_text", cut)
    with pytest.raises(OSError, match="killed"):
        config.write_json(f, {"a": 2})
    assert config.json_object(f) == {"a": 1}
    monkeypatch.undo()
    config.write_json(f, {"b": float("nan")}, default=float, allow_nan=True)
    assert config.plate_re_problem("p.json", dict(re=9.8e5)) == "p.json is at Re_L 9.8e+05, below the 1e+06 the comparison needs (rerun it)"
    assert config.plate_re_problem("p.json", dict(re=config.PLATE_RE_MIN)) is None


def test_stored_receipt_problem_is_one_rule_for_the_sha_and_the_plate_re_and_asks_the_sha_first():
    """DECISIONS 527: what the stage-3 gate and the credibility page both ask of a stored slow receipt."""
    p = "p.json"
    assert config.stored_receipt_problem(p, dict(re=1e6), "now") == "p.json was stored without a code sha (rerun it)"
    assert config.stored_receipt_problem(p, dict(re=1e6, code_sha="old"), "now") == "p.json was stored by different code (rerun it)"
    assert config.stored_receipt_problem(p, dict(re=1e6, code_sha="now"), "now", plate=True) is None
    low = dict(re=9.8e5, code_sha="now")
    assert config.stored_receipt_problem(p, low, "now", plate=True) == config.plate_re_problem(p, low)
    assert config.stored_receipt_problem(p, low, "now") is None                                   # only a plate is judged by Re_L
    assert config.stored_receipt_problem(p, dict(low, code_sha="old"), "now", plate=True) == "p.json was stored by different code (rerun it)"


# ---------------------------------------------------------------------------------------------------------------- review round 10, M-8

@pytest.mark.parametrize("lat_min, lat_max, words", [(88.0, 89.9, r"reaches 91.9 deg latitude, beyond \+-90"),
                                                   (-89.9, -88.0, r"reaches -91.9 deg latitude, beyond \+-90"),
                                                   (80.0, 88.5, r"reaches 90.5 deg latitude, beyond \+-90"),             # round 11, M-24: just past the limit,
                                                   (-88.5, -80.0, r"reaches -90.5 deg latitude, beyond \+-90")])
def test_r10_m8_a_padded_box_beyond_90_degrees_latitude_is_refused_at_validation(tmp_path, lat_min, lat_max, words):
    with pytest.raises(ConfigError, match=rf"m.yaml: box lat .*, lon .*: the box with its pad of 2 deg {words}.*box.pad_deg"):
        load_mission(edit(tmp_path, lambda d: d["box"].update(lat_min=lat_min, lat_max=lat_max)))


def test_r10_m8_a_box_that_the_pad_makes_a_full_circle_is_refused_where_it_used_to_become_a_thin_strip(tmp_path):
    """lon -179.9 .. 179.9 with a pad of 2 is 363.8 deg wide; box360 took that modulo 360 and fetched 3.8 deg."""
    with pytest.raises(ConfigError, match=r"m.yaml: box lat .*, lon -181.9 to 181.9: the box is 363.8 deg wide with its pad of 2 deg, a full circle or more"):
        load_mission(edit(tmp_path, lambda d: d["box"].update(lon_min=-179.9, lon_max=179.9)))
    with pytest.raises(ConfigError, match=r"is 360 deg wide with its pad of 10 deg"):
        load_mission(edit(tmp_path, lambda d: d["box"].update(lon_min=-170.0, lon_max=170.0, pad_deg=10.0)))


def test_r10_m8_the_demo_a_box_reaching_exactly_90_degrees_and_a_wide_box_that_fits_still_load(tmp_path):
    load_mission(DEMO)
    load_mission(edit(tmp_path, lambda d: d["box"].update(lat_min=-88.0, lat_max=88.0)))                  # -90 and 90 exactly are fine
    load_mission(edit(tmp_path, lambda d: d["box"].update(lon_min=165.0, lon_max=-165.0, pad_deg=2.0)))   # the dateline box: 30 + 4 deg


# ---------------------------------------------------------------------------------------------------------------- review round 11, M-14, M-15

@pytest.mark.parametrize("i, field, value, kind", [(3, "radio", "rfd900x", "iridium"), (3, "modem", "benthos_atm960_mf", "iridium"),
                                                   (1, "radio", "rfd900x", "acoustic"), (0, "modem", "benthos_atm960_mf", "rf"),
                                                   (1, "radio", "nonsense", "acoustic")])
def test_r11_m15_a_link_field_its_kind_never_reads_is_refused(tmp_path, i, field, value, kind):
    """`radio: rfd900x` on the Iridium link and `modem` on the rf link printed 'valid' and were ignored (row 154: a key that is accepted must be read)."""
    with pytest.raises(ConfigError, match=f"links/{doc()['links'][i]['id']}/{field}: a {kind} link does not read '{field}'"):
        load_mission(edit(tmp_path, lambda d: d["links"][i].update({field: value})))


@pytest.mark.parametrize("name, ok", [("Benthos_ATM960", True), ("BENTHOS_ATM960_MF", True), ("benthos_atm960_Lf", True), ("whoi_micromodem_Long_10K", True),
                                      ("whoi_micromodem", False), ("benthos_atm960_xx", False)])
def test_r11_m14_the_loader_accepts_exactly_the_modem_names_stage_1_resolves(tmp_path, name, ok):
    """`modem: Benthos_ATM960` loaded and ended stage 1 in KeyError 'Benthos_ATM960'; `whoi_micromodem` (no MF band) in KeyError 'MF'."""
    from cafe.pm.physics import comms
    resolved = comms.resolve_modem(name)
    assert (resolved is not None) == ok
    if ok:
        key, band = resolved
        assert band in comms._yaml("modems.yaml")["modems"][key]["bands"]
        assert load_mission(edit(tmp_path, lambda d: d["links"][1].update(modem=name)))["links"][1]["modem"] == name
    else:
        with pytest.raises(ConfigError, match=r"links/glider_eq-ship-acoustic/modem: '" + name + "' is not in platforms/modems.yaml"):
            load_mission(edit(tmp_path, lambda d: d["links"][1].update(modem=name)))


def test_r11_m14_a_bare_key_means_its_default_band_and_a_modem_with_none_says_which_bands_it_has(tmp_path):
    from cafe.pm.physics import comms
    assert comms.resolve_modem("benthos_atm960") == ("benthos_atm960", "MF") == comms.resolve_modem("Benthos_ATM960_mf")
    with pytest.raises(ConfigError, match=r"the modem has the bands \['long_10k', 'short_25k'\] and none is its default"):
        load_mission(edit(tmp_path, lambda d: d["links"][1].update(modem="whoi_micromodem")))


# ---------------------------------------------------------------------------------------------------------------- review round 11, M-25 (siblings)

def a_platform_file(tmp_path, name, fn):
    """platforms/<name>.yaml copied to tmp_path and changed by `fn`; its path is what a mission's `platform:` may name."""
    d = yaml.safe_load((config.PLATFORMS / f"{name}.yaml").read_text())
    fn(d)
    p = tmp_path / f"{name}_odd.yaml"
    p.write_text(yaml.safe_dump(d))
    return p


@pytest.mark.parametrize("vid, name, change", [("glider_eq", "seaglider", lambda d: d.update(params=5)),
                                               ("glider_eq", "seaglider", lambda d: d.update(mission_defaults=[1])),
                                               ("glider_eq", "seaglider", lambda d: d.update(kind=["seaglider"])),
                                               ("usv", "saildrone_explorer", lambda d: d.update(params=[1]))])
def test_r11_m25_a_platform_file_of_the_wrong_shape_is_a_config_error_not_a_traceback(tmp_path, vid, name, change):
    """The glider and USV loaders met a section that is not a mapping with an AttributeError (`.items()`) and an unhashable `kind` with a TypeError, and
    `validate` ended in a traceback for a platform file named by its path. They answer with a ValueError now (`physics.check_shape`), which
    `_check_platform` turns into the ConfigError."""
    p = a_platform_file(tmp_path, name, change)
    with pytest.raises(ConfigError, match=rf"vehicles/{vid}/platform: .* does not load as a (glider|usv) platform \(ValueError: "):
        load_mission(edit(tmp_path, lambda d: vehicle(d, vid).update(platform=str(p))))


@pytest.mark.parametrize("error", [TypeError("unhashable type: 'list'"), AttributeError("'int' object has no attribute 'items'")])
def test_r11_m25_a_class_loader_that_raises_a_type_or_attribute_error_is_a_config_error_too(monkeypatch, error):
    """Defence for a loader that does not check its shape: the tuple of `_check_platform` still holds both (no shipped loader raises them now)."""
    from cafe.pm.physics import glider

    def odd(name):
        raise error

    monkeypatch.setattr(glider, "load_platform", odd)
    with pytest.raises(ConfigError, match=rf"vehicles/glider_\w+/platform: 'seaglider' does not load as a glider platform \({type(error).__name__}: "):
        load_mission(DEMO)


def test_r11_m25_a_class_loader_that_raises_a_key_error_is_a_config_error_too(tmp_path, monkeypatch):
    """No file of the shipped layout is known to make the class loaders raise KeyError (each key is checked before it is read), so the member of the tuple
    is held by a loader that does."""
    from cafe.pm.physics import glider

    def lacking(name):
        raise KeyError("rating_m")

    monkeypatch.setattr(glider, "load_platform", lacking)
    with pytest.raises(ConfigError, match=r"vehicles/glider_\w+/platform: 'seaglider' does not load as a glider platform \(KeyError: 'rating_m'\)"):
        load_mission(DEMO)


# ---------------------------------------------------------------------------------------------------------------- review round 12, M-2

@pytest.mark.parametrize("bad,msg", [
    ("usv", r"ids must be unique across vehicles, links, ship and shore; 'usv' is used by vehicles/usv and links/usv"),
    ("ship", r"'ship' is used by ship and links/ship"),
    ("shore", r"'shore' is used by shore and links/shore"),
    ("", r"links/0/id: .*does not match"),
    ('a"b', r"links/0/id: .*does not match"),
    ("<b>", r"links/0/id: .*does not match"),
], ids=["vehicle", "ship", "shore", "empty", "quote", "markup"])
def test_r12_m2_a_link_id_that_is_a_vehicle_the_ship_or_the_shore_or_is_no_name_is_refused(tmp_path, bad, msg):
    """A link called `usv` took the vehicle's row in the Verdicts table (the report merged the two dicts) and every check still passed."""
    with pytest.raises(ConfigError, match=msg):
        load_mission(edit(tmp_path, lambda d: d["links"][0].update(id=bad)))


@pytest.mark.parametrize("which", ["ship", "shore"])
@pytest.mark.parametrize("bad", ["", 'a"b', "<i>", "a b"])
def test_r12_m2_the_ship_and_shore_ids_have_the_vehicle_id_pattern(tmp_path, which, bad):
    with pytest.raises(ConfigError, match=rf"{which}/id: .*does not match"):
        load_mission(edit(tmp_path, lambda d: d[which].update(id=bad)))


@pytest.mark.parametrize("field,put", [
    ("vehicle id", lambda d: d["vehicles"][0].update(id="usv2\n")),
    ("name", lambda d: d.update(name="demo\n")),
    ("window start", lambda d: d["window"].update(start="2023-03-01T12:00:00Z\n")),
    ("local_solar_time", lambda d: next(v for v in d["vehicles"] if v["id"] == "uas")["sorties"].update(local_solar_time="14:00\n")),
])
def test_r12_m2_a_pattern_of_the_mission_schema_does_not_let_a_final_newline_through(tmp_path, field, put):
    """`$` matches before a final newline in Python's re (which jsonschema uses), and a YAML block scalar ends in one: `usv\\n` passed as an id,
    `demo\\n` as the mission name (a directory name), and a time or an HH:MM with one passed the schema. The schema writes the end as `(?![\\s\\S])`,
    which ECMA-262 has too."""
    with pytest.raises(ConfigError, match="does not match"):
        load_mission(edit(tmp_path, put))


def test_r12_m2_the_shipped_missions_use_no_id_twice(tmp_path):
    for f in sorted((config.ROOT / "missions").glob("*.yaml")):
        m = load_mission(f)
        ids = [v["id"] for v in m["vehicles"]] + [m[k]["id"] for k in ("ship", "shore")] + [lk["id"] for lk in m["links"]]
        assert len(ids) == len(set(ids)), f


# ---------------------------------------------------------------------------------------------------------------- review round 12, M-24

def test_r12_m24_the_refusals_of_the_padded_box_label_the_edges_south_north_west_east_not_print_a_bare_tuple(tmp_path):
    """The tuple (south, north, west, east) read as lon first: lon -10..10, lat -5..5 and a pad of 2 printed "box (-7.0, 7.0, -12.0, 12.0)"."""
    def box(**kw):
        return lambda d: d["box"].update(dict(lon_min=-10.0, lon_max=10.0, lat_min=-5.0, lat_max=5.0, pad_deg=2.0) | kw)
    with pytest.raises(ConfigError, match=r"m.yaml: box lat -7 to 7, lon -12 to 12: the box \(with its pad of 2 deg\) crosses 0 deg E"):
        load_mission(edit(tmp_path, box()))
    with pytest.raises(ConfigError, match=r"m.yaml: box lat 83 to 91, lon -12 to 12: the box with its pad of 2 deg reaches 91 deg latitude"):
        load_mission(edit(tmp_path, box(lat_min=85.0, lat_max=89.0)))
    with pytest.raises(ConfigError, match=r"m.yaml: box lat -7 to 7, lon -181 to 181: the box is 362 deg wide"):
        load_mission(edit(tmp_path, box(lon_min=-179.0, lon_max=179.0)))


# ---- review round 13: M-22 (a long instance in a schema message, deep YAML) and M-14 (a symlink kept a symlink)

def test_r13_m22_a_65_vehicle_list_is_one_short_line_that_names_the_limit(tmp_path):
    """jsonschema's message repeats `repr(instance)`: 65 vehicles gave a ConfigError of 15,040 characters, 3,000 of 694,992."""
    d = doc()
    d["vehicles"] = [dict(id=f"v{i}", platform="slocum") for i in range(65)]
    with pytest.raises(ConfigError) as e:
        load_mission(write(tmp_path, d))
    msg = str(e.value)
    assert len(msg) < 1000 and "vehicles: has 65 items; at most 64 are allowed" in msg and "v64" not in msg


def test_r13_m22_a_long_wrong_value_is_cut_but_keeps_the_field_and_the_reason(tmp_path):
    d = doc()
    d["name"] = "x" * 5000
    with pytest.raises(ConfigError) as e:
        load_mission(write(tmp_path, d))
    msg = str(e.value)
    assert len(msg) < 1000 and "name: " in msg and "..." in msg and "is too long" in msg
    assert config._short("short", "x") == "short" and config._short("y" * 400, 1).endswith("...") and len(config._short("y" * 400, 1)) == 303


def test_r13_m22_yaml_nested_hundreds_deep_is_a_config_error_not_a_recursion_error(tmp_path):
    p = tmp_path / "deep.yaml"
    p.write_text("a: " + "[" * 3000 + "]" * 3000 + "\n")
    with pytest.raises(ConfigError, match=r"deep.yaml: nested too deeply to read"):
        config.read_yaml(p)
    j = tmp_path / "deep.json"
    j.write_text("[" * 100000 + "]" * 100000)
    with pytest.raises(ConfigError, match="not a JSON object"):
        config.json_object(j)


def test_r13_m14_write_json_replaces_the_file_a_symlink_points_to_and_leaves_the_link(tmp_path):
    real, link = tmp_path / "real.json", tmp_path / "sl.json"
    real.write_text("{}")
    link.symlink_to(real)
    config.write_json(link, {"a": 1})
    assert link.is_symlink() and config.json_object(real) == {"a": 1} and config.json_object(link) == {"a": 1} and not list(tmp_path.glob("*.tmp"))


def test_r13_sweep_write_text_is_the_one_atomic_writer_and_write_json_can_end_a_line(tmp_path, cut_writes):
    """Round 13 (M-17 sibling sweep, batches A and B's need): the golden, the audit records and the run's reports need a trailing newline and a write
    that leaves the old file when cut. `write_json`'s default bytes stay as they were (the ingest manifests are hashed); `end` adds the newline;
    a cut leaves no temporary behind; a symlink is followed."""
    f = tmp_path / "r.json"
    config.write_json(f, {"a": 1}, indent=1)
    assert f.read_bytes() == b'{\n "a": 1\n}'
    config.write_json(f, {"a": 1}, indent=1, end="\n")
    before = f.read_bytes()
    assert before == b'{\n "a": 1\n}\n'
    link = tmp_path / "sl.json"
    link.symlink_to(f)
    config.write_text(link, "x\n")
    assert link.is_symlink() and f.read_text() == "x\n"
    config.write_text(f, before.decode())
    cut_writes()
    for write in (lambda: config.write_text(f, "new"), lambda: config.write_json(f, {"a": 2}, end="\n")):
        with pytest.raises(OSError, match="killed"):
            write()
        assert f.read_bytes() == before and not list(tmp_path.glob("*.tmp"))
