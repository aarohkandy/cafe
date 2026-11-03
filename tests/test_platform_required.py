"""Review round 5, M-4: a platform file with a parameter missing, NaN or unphysical is refused at load time, naming the file and the field."""
import pathlib
import re

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
    check_params(dict(a="other", b="pos", c="any", d="nonneg"), dict(a="text", b=[1.0, 2.0], c=-3.0, d=0.0, e="free text", f=True), "x.yaml:p", "r")
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
