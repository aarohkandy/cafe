"""Review round 5, M-4: a platform file with a parameter missing, NaN or unphysical is refused at load time, naming the file and the field."""
import pathlib
import re

import numpy as np
import pytest
import yaml

from cafe.pm import __main__ as cli
from cafe.pm.config import ConfigError, load_mission
from cafe.pm.physics import glider, uas, usv, check_params

ROOT = pathlib.Path(__file__).resolve().parents[1]
CI_MISSION = ROOT / "missions" / "ci_fixture.yaml"
LOADERS = {"seaglider": glider, "slocum": glider, "saildrone_explorer": usv, "quad_uas": uas}


def copy_of(tmp_path, name, edit):
    raw = yaml.safe_load((ROOT / "platforms" / f"{name}.yaml").read_text())
    edit(raw)
    f = tmp_path / f"{name}.yaml"
    f.write_text(yaml.safe_dump(raw))
    return str(f)


# the same three defects in every class: the key gone, NaN, and a value the model cannot fly with
CASES = [
    ("seaglider", lambda r: r["params"].pop("mass_kg"), r"seaglider\.yaml:params: missing \['mass_kg'\]; add them \(see platforms/seaglider\.yaml"),
    ("seaglider", lambda r: r["params"]["battery_J"].update(value=float("nan")), r"params\.battery_J: nan must be a finite number above 0"),
    ("seaglider", lambda r: r["params"]["mass_kg"].update(value=0.0), r"params\.mass_kg: 0\.0 must be a finite number above 0"),
    ("seaglider", lambda r: r["params"]["reserve_frac"].update(value=1.5), r"params\.reserve_frac: 1\.5 must be a finite number from 0 up to"),
    ("seaglider", lambda r: r["params"]["hd_b"].update(value=-1.0), r"params\.hd_b: -1\.0 must be a finite number above 0"),
    ("seaglider", lambda r: r["params"]["rating_m"].update(value=float("nan")), r"params\.rating_m: nan must be a finite number above 0"),
    ("seaglider", lambda r: r["params"]["hd_s"].update(value=float("inf")), r"params\.hd_s: inf must be a finite number"),
    ("seaglider", lambda r: r["params"].update(zzz={"value": float("nan"), "unit": "m", "assumed": True, "why": "w"}), r"params\.zzz: nan must be a finite"),
    ("seaglider", lambda r: r.update(kind="torpedo"), r"kind: 'torpedo' is not a glider kind"),
    ("seaglider", lambda r: r["mission_defaults"]["station_tol_m"].update(value=float("nan")), r"mission_defaults\.station_tol_m: nan"),
    ("slocum", lambda r: r["params"].pop("mg"), r"slocum\.yaml:params: missing \['mg'\]"),
    ("slocum", lambda r: r["params"]["Vg"].update(value=0.0), r"params\.Vg: 0\.0 must be a finite number above 0"),
    ("saildrone_explorer", lambda r: r["params"].pop("mass_kg"), r"saildrone_explorer\.yaml:params: missing \['mass_kg'\]"),
    ("saildrone_explorer", lambda r: r["params"]["lwl_m"].update(value=0.0), r"params\.lwl_m: 0\.0 must be a finite number above 0"),
    ("saildrone_explorer", lambda r: r["params"]["battery_wh"].update(value=float("nan")), r"params\.battery_wh: nan must be"),
    ("saildrone_explorer", lambda r: r["params"]["soc0"].update(value=1.2), r"params\.soc0: 1\.2 must be a finite number from 0 to 1"),
    ("quad_uas", lambda r: r["airframe"].pop("mass_kg"), r"quad_uas\.yaml:airframe: missing \['mass_kg'\]"),
    ("quad_uas", lambda r: r.pop("battery"), r"quad_uas\.yaml: missing \['battery'\]"),
    ("quad_uas", lambda r: r["battery"]["energy_wh"].update(value=float("nan")), r"battery\.energy_wh: nan must be a finite number above 0"),
    ("quad_uas", lambda r: r["airframe"]["inertia_kgm2"].update(value=[0.0025, 0.0, 0.0043]), r"airframe\.inertia_kgm2: .* must be a finite number above 0"),
    ("quad_uas", lambda r: r["battery"]["ocv_soc"].update(value=[0.0, float("nan"), 1.0]), r"battery\.ocv_soc: .* must be a finite number from 0 to 1"),
    ("quad_uas", lambda r: r["battery"]["reserve_frac"].update(value=1.0), r"battery\.reserve_frac: 1\.0 must be a finite number from 0 up to"),
]


@pytest.mark.parametrize("name,edit,msg", CASES, ids=[f"{c[0]}-{i}" for i, c in enumerate(CASES)])
def test_a_platform_with_a_missing_nan_or_unphysical_parameter_is_refused_naming_file_and_field(tmp_path, name, edit, msg):
    path = copy_of(tmp_path, name, edit)
    with pytest.raises(ValueError, match=msg):
        LOADERS[name].load_platform(path)


def test_the_shipped_platform_files_satisfy_their_loaders():
    for name, mod in LOADERS.items():
        assert mod.load_platform(name)


def test_check_params_kinds_and_non_numbers():
    # round 8, M-26: a list for a number is refused (b was [1.0, 2.0])
    check_params(dict(a="other", b="pos", c="any", d="nonneg"), dict(a="text", b=2.0, c=-3.0, d=0.0, e="free text", f=True), "x.yaml:p", "r")
    for bad in (True, "1.0", [], [1.0, float("inf")], float("nan"), 0.0, -1.0):
        with pytest.raises(ValueError, match=r"x\.yaml:p\.b: .* must be a finite number above 0"):
            check_params(dict(b="pos"), dict(b=bad), "x.yaml:p", "r")
    with pytest.raises(ValueError, match=r"x\.yaml:p: missing \['b'\]; add them \(see platforms/r\.yaml for the layout\)"):
        check_params(dict(b="pos"), {}, "x.yaml:p", "r")


def test_a_mission_naming_a_platform_without_mass_is_a_config_error_and_the_hangar_fails_naming_the_field(tmp_path, capsys):
    path = copy_of(tmp_path, "seaglider", lambda r: r["params"].pop("mass_kg"))
    d = yaml.safe_load(CI_MISSION.read_text())
    next(v for v in d["vehicles"] if v["id"] == "glider_eq")["platform"] = path
    m = tmp_path / "m.yaml"
    m.write_text(yaml.safe_dump(d))
    with pytest.raises(ConfigError, match=r"vehicles/glider_eq/platform: .* does not load as a glider platform .*missing \['mass_kg'\]"):
        load_mission(m)
    assert cli.main(["hangar", "--platform", path]) == 1
    out = capsys.readouterr().out
    assert "provenance FAILED" in out and "missing ['mass_kg']" in out


def test_every_parameter_the_models_read_is_in_a_table():
    """The tables cannot go stale: each flat `P["key"]` literal of the glider and USV modules (and of stage 1 and the stage-3 windows, which read the
    same files) is in a REQUIRED or OPTIONAL table, and each group and key the UAS model unpacks is in uas.REQUIRED."""
    src = lambda *p: (ROOT / "cafe" / "pm" / pathlib.Path(*p)).read_text()
    lit = lambda text: set(re.findall(r'\bP\["(\w+)"\](?!\[)', text)) - {"kind", "mission_defaults"} - set(uas.REQUIRED)
    seen = {"glider": set().union(*(set(t) for t in glider.REQUIRED.values())) | set(glider.OPTIONAL), "usv": set(usv.REQUIRED) | set(usv.OPTIONAL)}
    assert lit(src("physics", "glider.py")) <= seen["glider"], lit(src("physics", "glider.py")) - seen["glider"]
    assert lit(src("physics", "usv.py")) <= seen["usv"], lit(src("physics", "usv.py")) - seen["usv"]
    both = seen["glider"] | seen["usv"]
    for other in (("stage1.py",), ("stage3", "pipeline_windows.py")):
        assert lit(src(*other)) <= both, lit(src(*other)) - both
    for kind, table in glider.REQUIRED.items():
        raw = yaml.safe_load((ROOT / "platforms" / f"{kind}.yaml").read_text())["params"]
        assert set(table) <= set(raw), set(table) - set(raw)
    raw = yaml.safe_load((ROOT / "platforms" / "saildrone_explorer.yaml").read_text())["params"]
    assert set(usv.REQUIRED) <= set(raw) and set(raw) <= set(usv.REQUIRED) | set(usv.OPTIONAL), "a key of the shipped USV file is in neither table"
    quad = yaml.safe_load((ROOT / "platforms" / "quad_uas.yaml").read_text())
    for g, table in uas.REQUIRED.items():
        assert set(table) <= set(quad[g]), (g, set(table) - set(quad[g]))
    # the UAS groups: every `X["key"]` of derive() and launch_check() with X one of the unpacked group names
    import inspect
    names = dict(af="airframe", ro="rotor", ae="aero", ba="battery", li="limits", co="controller", fa="failure")
    body = inspect.getsource(uas.derive)
    for var, group in names.items():
        for key in re.findall(rf'\b{var}\["(\w+)"\]', body):
            assert key in uas.REQUIRED[group], (group, key)
    for key in re.findall(r'\blr\["(\w+)"\]', inspect.getsource(uas.launch_check)):
        assert key in uas.REQUIRED["launch_rule"], key


@pytest.mark.parametrize("mod,name", [(glider, "seaglider"), (usv, "saildrone_explorer"), (uas, "quad_uas")])
def test_a_platform_file_with_a_repeated_key_is_refused_like_a_mission(tmp_path, mod, name):
    """Round 5 integration of M-18: the platform loaders read with yaml.safe_load, so a repeated key in a platform file silently kept the later value
    (a mission refused it). They read through config's loader now: the repeated key and its line are named."""
    text = (ROOT / "platforms" / f"{name}.yaml").read_text()
    first = next(ln for ln in text.splitlines() if re.match(r"^[a-z_]+:", ln))
    p = tmp_path / f"{name}.yaml"
    p.write_text(text + "\n" + first + "\n")
    with pytest.raises(ConfigError, match=rf"duplicate key '{first.split(':')[0]}'"):
        mod.load_platform(str(p))


def test_the_radio_table_is_read_with_the_same_loader(tmp_path, monkeypatch):
    from cafe.pm.physics import comms
    (tmp_path / "radios.yaml").write_text("a: 1\na: 2\n")
    monkeypatch.setattr(comms, "PLATFORMS", tmp_path)
    comms._yaml.cache_clear()
    try:
        with pytest.raises(ConfigError, match=r"line 2: duplicate key 'a'"):
            comms._yaml("radios.yaml")
    finally:
        comms._yaml.cache_clear()


# ---- review round 8: M-11 (r_int 0), M-26 (arrays and lists), M-28 (angles and mass), M-25 (an empty file)
CASES_R8 = [
    ("quad_uas", lambda r: r["battery"]["r_int_ohm"].update(value=0.0), r"battery\.r_int_ohm: 0\.0 must be a finite number above 0; an ideal pack .* use 1e-6"),
    ("quad_uas", lambda r: r["battery"]["ocv_soc"].update(value=[1.0, 0.8, 0.5, 0.2, 0.1, 0.0]), r"battery\.ocv_soc: .* strictly increasing"),
    ("quad_uas", lambda r: r["battery"]["ocv_soc"].update(value=[0.0, 0.1, 0.1, 0.5, 0.9, 1.0]), r"battery\.ocv_soc: .* strictly increasing"),
    ("quad_uas", lambda r: (r["battery"]["ocv_soc"].update(value=[0.5]), r["battery"]["ocv_cell_v"].update(value=[3.7])),
     r"battery\.ocv_soc: .* at least two states of charge"),
    ("quad_uas", lambda r: r["battery"]["ocv_cell_v"].update(value=[3.0, 3.45, 3.6, 3.78, 4.02]), r"battery\.ocv_cell_v: 5 values for 6 states of charge"),
    ("quad_uas", lambda r: r["airframe"]["inertia_kgm2"].update(value=[0.0025, 0.0025]),
     r"airframe\.inertia_kgm2: .* must be a finite number above 0 in every place of a list of 3"),
    ("quad_uas", lambda r: r["airframe"]["mass_kg"].update(value=[0.77, 0.8]), r"airframe\.mass_kg: .* must be a number, got a list"),
    ("saildrone_explorer", lambda r: r["params"]["mass_kg"].update(value=[750.0, 760.0]), r"params\.mass_kg: .* must be a number, got a list"),
    ("saildrone_explorer", lambda r: r["params"]["mass_kg"].update(value=1e300), r"params\.mass_kg: 1e\+300 must be a finite number from 1 to 100000"),
    ("saildrone_explorer", lambda r: r["params"]["wing_stall_deg"].update(value=120.0),
     r"params\.wing_stall_deg: 120\.0 must be a finite number above 0 and below 90"),
    ("saildrone_explorer", lambda r: r["params"]["wing_stall_deg"].update(value=0.0), r"params\.wing_stall_deg: 0\.0 must be .* above 0 and below 90"),
    ("saildrone_explorer", lambda r: r["params"]["heel_target_deg"].update(value=-5.0), r"params\.heel_target_deg: -5\.0 must be .* above 0 and below 90"),
    ("saildrone_explorer", lambda r: r["params"]["wing_stall_deg"].update(value=90.0), r"params\.wing_stall_deg: 90\.0 must be"),
    ("saildrone_explorer", lambda r: r["params"]["heel_target_deg"].update(value=120.0), r"params\.heel_target_deg: 120\.0 must be"),
    ("saildrone_explorer", lambda r: r["params"]["heel_target_deg"].update(value=90.0), r"params\.heel_target_deg: 90\.0 must be"),
    ("saildrone_explorer", lambda r: r["params"]["min_awa_deg"].update(value=400.0), r"params\.min_awa_deg: 400\.0 must be a finite number from 0 to 180"),
    ("saildrone_explorer", lambda r: r["params"]["wing_trim_deg"].update(value=200.0), r"params\.wing_trim_deg: 200\.0 must be"),
    ("saildrone_explorer", lambda r: r["params"]["keel_stall_deg"].update(value=200.0), r"params\.keel_stall_deg: 200\.0 must be"),
    ("seaglider", lambda r: r["params"]["battery_J"].update(value=[1.0e7, 1.1e7]), r"params\.battery_J: .* must be a number, got a list"),
]


@pytest.mark.parametrize("name,edit,msg", CASES_R8, ids=[f"{c[0]}-{i}" for i, c in enumerate(CASES_R8)])
def test_r8_a_list_for_a_number_a_bad_table_and_an_out_of_range_angle_are_refused_naming_the_leaf(tmp_path, name, edit, msg):
    path = copy_of(tmp_path, name, edit)
    with pytest.raises(ValueError, match=msg):
        LOADERS[name].load_platform(path)


def test_r8_m11_a_one_micro_ohm_pack_flies_with_finite_state():
    P = uas.load_platform()
    P["battery"]["r_int_ohm"] = 1e-6
    prm = uas.derive(P, 2)
    soc, qah, ewh, volt, cur = uas._batt(prm, np.ones(2), np.zeros(2), np.zeros(2), np.full(2, 120.0), 1.0)
    assert np.isfinite([soc, qah, ewh, volt, cur]).all() and 0.99 < float(soc[0]) < 1.0
    assert float(cur[0]) == pytest.approx(120.0 / float(volt[0]), rel=2e-2)          # float32: the sqrt cancels at 1e-6 ohm


@pytest.mark.parametrize("name", ["saildrone_explorer", "seaglider", "quad_uas"])
@pytest.mark.parametrize("text", ["", "# only a comment\n"], ids=["empty", "comment"])
def test_r8_m25_an_empty_or_comment_only_platform_file_is_one_named_refusal_for_every_class_and_the_hangar(tmp_path, capsys, name, text):
    f = tmp_path / f"{name}.yaml"
    f.write_text(text)
    with pytest.raises(ValueError, match=r"expected a mapping of platform parameters \(the file is empty or not a mapping\); a platform file has `params:`"):
        LOADERS[name].load_platform(str(f))
    assert cli.main(["hangar", "--platform", str(f)]) == 1
    assert "provenance FAILED" in capsys.readouterr().out


# ---- review round 8, L1: the platform numbers that had only 'pos'/'nonneg' (an angle past 90 degrees, a fractional cell count, a 1e12 kg glider)
def _leaf(group, key, value):
    return lambda r: (r[group] if group else r["params"])[key].update(value=value)


CASES_R8_L1 = [
    ("seaglider", _leaf(None, "pitch_deg", 120.0), "params.pitch_deg", "above 0 and below 90"),
    ("seaglider", _leaf(None, "pitch_deg", 1e6), "params.pitch_deg", "above 0 and below 90"),
    ("slocum", _leaf(None, "pitch_deg", 120.0), "params.pitch_deg", "above 0 and below 90"),
    ("seaglider", _leaf(None, "mass_kg", 1e12), "params.mass_kg", "at most 1e4"),
    ("slocum", _leaf(None, "mg", 1e12), "params.mg", "at most 1e4"),
    ("seaglider", _leaf(None, "rating_m", 1e7), "params.rating_m", "at most 11000"),
    ("seaglider", _leaf(None, "length_m", 1e6), "params.length_m", "at most 20"),
    ("seaglider", _leaf(None, "windage", 5.0), "params.windage", "at most 0.2"),
    ("slocum", _leaf(None, "windage", 5.0), "params.windage", "at most 0.2"),
    ("seaglider", _leaf(None, "reserve_frac", 0.99), "params.reserve_frac", "at most 0.5"),
    ("quad_uas", _leaf("battery", "cells", 2.5), "battery.cells", "a whole number from 1 to 24"),
    ("quad_uas", _leaf("battery", "cells", 1e6), "battery.cells", "a whole number from 1 to 24"),
    ("quad_uas", _leaf("battery", "cells", 0), "battery.cells", "a whole number from 1 to 24"),
    ("quad_uas", _leaf("airframe", "mass_kg", 1e9), "airframe.mass_kg", "at most 100"),
    ("quad_uas", _leaf("battery", "energy_wh", 1e12), "battery.energy_wh", "at most 1e4"),
    ("quad_uas", _leaf("battery", "v_nom_cell", 1000.0), "battery.v_nom_cell", "from 1 to 5"),
    ("quad_uas", _leaf("battery", "peukert_exponent", 50.0), "battery.peukert_exponent", "from 1 to 2"),
    ("quad_uas", _leaf("battery", "peukert_exponent", 0.5), "battery.peukert_exponent", "from 1 to 2"),
    ("quad_uas", _leaf("battery", "reserve_frac", 0.99), "battery.reserve_frac", "at most 0.5"),
    ("quad_uas", _leaf("limits", "max_tilt_deg", 120.0), "limits.max_tilt_deg", "above 0 and below 90"),
    ("quad_uas", _leaf("limits", "tilt_exceedance_deg", 120.0), "limits.tilt_exceedance_deg", "above 0 and below 90"),
    ("saildrone_explorer", _leaf(None, "loa_m", 1e6), "params.loa_m", "at most 100"),
    ("saildrone_explorer", _leaf(None, "wing_area_m2", 1e9), "params.wing_area_m2", "at most 100"),
    ("saildrone_explorer", _leaf(None, "gm_m", 1e6), "params.gm_m", "at most 10"),
    ("saildrone_explorer", _leaf(None, "rf_antenna_height_m", 1e6), "params.rf_antenna_height_m", "at most 50"),
    ("saildrone_explorer", _leaf(None, "battery_wh", 1e12), "params.battery_wh", "at most 1e6"),
    ("saildrone_explorer", _leaf(None, "wind_height_m", 1e6), "params.wind_height_m", "at most 50"),
    ("saildrone_explorer", _leaf(None, "hotel_w", 1e9), "params.hotel_w", "at most 1e4"),
    ("saildrone_explorer", _leaf(None, "kyy_frac", 1e3), "params.kyy_frac", "from 0.05 to 1"),
    ("saildrone_explorer", _leaf(None, "kyy_frac", 0.0), "params.kyy_frac", "from 0.05 to 1"),
]


@pytest.mark.parametrize("name,edit,field,bound", CASES_R8_L1, ids=[f"{c[0]}-{c[2]}-{i}" for i, c in enumerate(CASES_R8_L1)])
def test_r8_l1_an_implausible_platform_number_is_refused_naming_the_field_and_its_bound(tmp_path, name, edit, field, bound):
    path = copy_of(tmp_path, name, edit)
    with pytest.raises(ValueError, match=rf"{re.escape(field)}: .* must be a finite number .*{re.escape(bound)}"):
        LOADERS[name].load_platform(path)


@pytest.mark.parametrize("name,edit", [
    ("quad_uas", _leaf("battery", "cells", 24)), ("quad_uas", _leaf("battery", "cells", 1)), ("quad_uas", _leaf("battery", "cells", 4.0)),
    ("seaglider", _leaf(None, "pitch_deg", 89.0)), ("saildrone_explorer", _leaf(None, "kyy_frac", 1.0)),
    ("quad_uas", _leaf("battery", "peukert_exponent", 1.0)),
], ids=["cells24", "cells1", "cells4.0", "pitch89", "kyy1", "peukert1"])
def test_r8_l1_the_bound_itself_and_a_whole_number_written_with_a_dot_load(tmp_path, name, edit):
    LOADERS[name].load_platform(copy_of(tmp_path, name, edit))


def test_r8_l1_every_angle_in_a_shipped_platform_file_has_a_bounded_kind():
    """The class: a key whose unit is degrees must not be left at 'pos'/'nonneg'/'any' (a pitch of 120 degrees flips the sign of the glide)."""
    tables = {"seaglider": glider.REQUIRED["seaglider"], "slocum": glider.REQUIRED["slocum"], "saildrone_explorer": usv.REQUIRED}
    for name, table in tables.items():
        raw = yaml.safe_load((ROOT / "platforms" / f"{name}.yaml").read_text())
        for k, leaf in raw["params"].items():
            if leaf["unit"] == "deg" and k in table:
                assert table[k] not in ("pos", "nonneg", "any"), f"{name}.params.{k} is an angle with kind {table[k]!r}"
    raw = yaml.safe_load((ROOT / "platforms" / "quad_uas.yaml").read_text())
    for g, table in uas.REQUIRED.items():
        for k, leaf in raw[g].items():
            if isinstance(leaf, dict) and leaf.get("unit") == "deg" and k in table:
                assert table[k] not in ("pos", "nonneg", "any"), f"quad_uas.{g}.{k} is an angle with kind {table[k]!r}"


# ---- review round 9, M-22: the mission defaults the models index are required by their loaders
def test_r9_m22_every_mission_default_the_models_and_their_readers_index_is_in_a_loader_table():
    """The class: a `md["key"]` that no table requires is a KeyError hours into a run on a hand-edited file. Read from the source, like the P[...] test."""
    src = lambda *p: (ROOT / "cafe" / "pm" / pathlib.Path(*p)).read_text()
    md = lambda text: set(re.findall(r'\bmd\["(\w+)"\]', text)) - {"station", "waypoints"}  # the mission's own geometry, which config.load_mission requires
    assert md(src("physics", "glider.py")) <= set(glider.MISSION_REQUIRED), md(src("physics", "glider.py")) - set(glider.MISSION_REQUIRED)
    assert md(src("physics", "usv.py")) <= set(usv.MISSION_REQUIRED), md(src("physics", "usv.py")) - set(usv.MISSION_REQUIRED)
    both = set(glider.MISSION_REQUIRED) | set(usv.MISSION_REQUIRED)
    for other in (("report.py",), ("stage1.py",), ("stage3", "pipeline_windows.py")):  # readers of the platform's own: P["mission_defaults"]["key"]
        text = src(*other)
        keys = set(re.findall(r'mission_defaults"\]\["(\w+)"\]', text)) | set(re.findall(r'"mission_defaults",\s*"(\w+)"', text))
        assert keys <= both, (other, keys - both)
    for name, mod in (("seaglider", glider), ("slocum", glider), ("saildrone_explorer", usv)):
        raw = yaml.safe_load((ROOT / "platforms" / f"{name}.yaml").read_text())["mission_defaults"]
        assert set(mod.MISSION_REQUIRED) == set(raw), (name, set(mod.MISSION_REQUIRED) ^ set(raw))


@pytest.mark.parametrize("name", ["seaglider", "slocum", "saildrone_explorer", "quad_uas"])
def test_r9_m1_every_class_loader_resolves_a_platform_reference_by_config_platform_path(tmp_path, monkeypatch, name):
    """glider and usv took any dotted name for a path (`foo.v2` -> not found) and uas looked beside its own constant: one rule now, config.platform_path.
    A copy named <name>.v2.yaml in the platforms directory is the name `<name>.v2`; a file ending in .yml is a path."""
    plat = tmp_path / "platforms"
    plat.mkdir()
    (plat / f"{name}.v2.yaml").write_text((ROOT / "platforms" / f"{name}.yaml").read_text())
    monkeypatch.setattr("cafe.pm.config.PLATFORMS", plat)
    want = LOADERS[name].load_platform(str(ROOT / "platforms" / f"{name}.yaml"))
    assert LOADERS[name].load_platform(f"{name}.v2") == want
    yml = tmp_path / "mine.yml"
    yml.write_text((plat / f"{name}.v2.yaml").read_text())
    assert LOADERS[name].load_platform(str(yml)) == want
