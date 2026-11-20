"""Round 22, batch C (M-5): `config._yaml`, the one YAML reader, refuses a NaN, an infinity and an integer too big for a float anywhere in the document, so
`platforms/radios.yaml`, `platforms/modems.yaml`, `config/assumptions.yaml` and every other YAML the code loads are covered by construction (before, only the
mission and the four vehicle platform files were: `tx_dbm: .inf` in radios.yaml gave an RF link GO and `hangar --platform radios` said "provenance OK").

The tests are generated from the shipped files (a new file or a new number is covered the day it is added) and from the source (a new raw YAML load fails the
enumeration until it is classified)."""
import ast
import functools
import pathlib
import re

import pytest
import yaml

from cafe import fea
from cafe.pm import __main__ as cli, config
from cafe.pm.physics import comms

ROOT = pathlib.Path(__file__).resolve().parents[1]
SHIPPED = sorted([*(ROOT / "platforms").glob("*.yaml"), *(ROOT / "config").glob("*.yaml"), *(ROOT / "missions").glob("*.yaml")])
BAD = {"nan": float("nan"), "inf": float("inf"), "-inf": float("-inf"), "big": 10 ** 400}


# ---------------------------------------------------------------------------------------------------------------- every numeric leaf of every file
def _leaves(node, where=""):
    """(where, container, key) of every number (a bool is not one) in a document, `where` named as `config._finite` names it: keys joined by `/`, a list
    item that is a mapping with an `id` by its id."""
    items = node.items() if isinstance(node, dict) else enumerate(node) if isinstance(node, list) else ()
    for k, v in items:
        name = v["id"] if isinstance(node, list) and isinstance(v, dict) and "id" in v else k
        here = f"{where}/{name}".lstrip("/")
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            yield here, node, k
        else:
            yield from _leaves(v, here)


@functools.lru_cache(None)
def _clean(path):
    return config._yaml(path)


def test_the_shipped_files_are_what_the_generated_tests_see():
    """The names the parametrized tests below run over: a file removed or added shows here, and every one has numeric leaves (a file with none would pass
    the generated test without testing anything)."""
    assert [f.name for f in SHIPPED if f.parent.name == "platforms"] == ["modems.yaml", "quad_uas.yaml", "radios.yaml", "saildrone_explorer.yaml",
                                                                       "seaglider.yaml", "slocum.yaml"]
    assert {f.name for f in SHIPPED if f.parent.name == "config"} == {"assumptions.yaml", "perturbations.yaml"}
    for f in SHIPPED:
        assert sum(1 for _ in _leaves(_clean(f))) > 0, f


@pytest.mark.parametrize("bad", list(BAD))
@pytest.mark.parametrize("path", SHIPPED, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_every_numeric_leaf_of_every_shipped_yaml_set_to_a_non_finite_or_oversized_number_is_refused_naming_the_file_and_the_key(path, bad, tmp_path):
    """For EVERY numeric leaf (not a sample of them): the file with that one leaf replaced is refused by `config._yaml` with a ConfigError that names the
    file and the leaf's key and says what the number is; never read, never an OverflowError. The unedited copy loads and equals the shipped file."""
    doc = config._yaml(path)
    p = tmp_path / path.name

    def dump():
        p.write_text(yaml.dump(doc, Dumper=config._Dumper, sort_keys=False))
    dump()
    assert config._yaml(p) == doc                                                          # the dump is faithful: only the edited leaf can be the cause
    what = "an integer of 401 digits" if bad == "big" else repr(BAD[bad])
    leaves = list(_leaves(doc))
    assert leaves
    for where, container, key in leaves:
        old, container[key] = container[key], BAD[bad]
        dump()
        with pytest.raises(config.ConfigError) as e:
            config._yaml(p)
        assert str(e.value).startswith(f"{p}: {where}: {what} is not a finite number"), (where, str(e.value))
        container[key] = old


# ---------------------------------------------------------------------------------------------------------------- the reviewer's case
def _radios_with(tmp_path, monkeypatch, text):
    d = tmp_path / "platforms"
    d.mkdir()
    (d / "radios.yaml").write_text(text)
    monkeypatch.setattr(comms, "PLATFORMS", d)
    comms._yaml.cache_clear()
    return d / "radios.yaml"


@pytest.mark.parametrize("bad", [".inf", "-.inf", ".nan", "1" + "0" * 400])
def test_tx_dbm_inf_in_radios_yaml_is_refused_where_it_gave_an_rf_link_go_and_provenance_ok(tmp_path, monkeypatch, capsys, bad):
    """Round 22, D-1: `tx_dbm: .inf` made `rf_margin` +inf (a link that always passes) and `hangar --platform radios` print "provenance OK". Now the table is
    refused by the reader, in the link model and in the lab's own check."""
    text = (config.PLATFORMS / "radios.yaml").read_text()
    assert text.count("    tx_dbm: 30.0\n") == 2
    p = _radios_with(tmp_path, monkeypatch, text.replace("    tx_dbm: 30.0\n", f"    tx_dbm: {bad}\n", 1))
    try:
        with pytest.raises(config.ConfigError, match=r"radios/rfd900x/tx_dbm: .* is not a finite number"):
            comms.rf_margin(1000.0, 2.0, 2.0, 0.0)
        assert cli.main(["hangar", "--platform", str(p)]) == 2
        out = capsys.readouterr()
        assert "provenance OK" not in out.out
        assert f"error: {p}: radios/rfd900x/tx_dbm: " in out.err and "is not a finite number" in out.err
    finally:
        comms._yaml.cache_clear()


def test_the_unedited_copy_of_radios_yaml_is_still_go_and_provenance_ok(tmp_path, monkeypatch, capsys):
    """The other side of the guard: the shipped table, copied, loads as it did and the check says OK."""
    p = _radios_with(tmp_path, monkeypatch, (config.PLATFORMS / "radios.yaml").read_text())
    try:
        assert comms.rf_margin(1000.0, 2.0, 2.0, 0.0) is not None
        assert cli.main(["hangar", "--platform", str(p)]) == 0
        assert "provenance OK" in capsys.readouterr().out
    finally:
        comms._yaml.cache_clear()


# ---------------------------------------------------------------------------------------------------------------- the spellings and the edge
@pytest.mark.parametrize("spelling", [".inf", ".Inf", ".INF", "+.inf", "-.inf", "-.INF", ".nan", ".NaN", ".NAN", "1e400", "-1e400", "1.0e+999", "!!float .inf",
                                      "!!float inf", "!!float nan", "1" + "0" * 309, "-1" + "0" * 309, "1" + "0" * 400, "0x" + "f" * 300,
                                      "1_" + "0_" * 400 + "0"])
def test_every_spelling_of_a_non_finite_or_oversized_number_is_refused_in_a_nested_list_of_any_yaml_file(tmp_path, spelling):
    """Not only the spellings `yaml.dump` writes: the ones a person types, in a list in a list in a mapping (the walk's index naming), by `config._yaml`."""
    p = tmp_path / "t.yaml"
    p.write_text(f"a:\n  b: [[1, {spelling}], 2]\n")
    with pytest.raises(config.ConfigError, match=r"t\.yaml: a/b/0/1: .* is not a finite number"):
        config._yaml(p)


@pytest.mark.parametrize("spelling, expected", [("1" + "0" * 308, 10 ** 308), ("-1" + "0" * 308, -10 ** 308), ("1e308", 1e308),
                                                ("-0.0", 0.0), ("5e-324", 5e-324), ("0", 0), ("true", True), ('"nan"', "nan"), ('".inf"', ".inf"),
                                                ("null", None), ("1.0e999", "1.0e999")])
def test_the_largest_number_that_fits_a_float_zero_a_bool_a_quoted_word_and_null_still_load(tmp_path, spelling, expected):
    """The bound sits where a float stops: 10**308 is a number, 10**309 (above) is refused. A bool, a quoted `nan`, an empty value and `1.0e999` (YAML 1.1 wants
    a sign in the exponent of a float with a dot, so that is text: a TypeError at the first sum, not a number) are not numbers: the schema, or the loader
    that reads them, decides those."""
    p = tmp_path / "t.yaml"
    p.write_text(f"a:\n  b: [[1, {spelling}], 2]\n")
    got = config._yaml(p)["a"]["b"][0][1]
    assert got == expected and type(got) is type(expected)


# ---------------------------------------------------------------------------------------------------------------- the shipped files hold no non-finite number
def test_no_shipped_yaml_needs_a_non_finite_number_so_refusing_them_everywhere_loses_nothing():
    """The class closes in one reader, which is only safe if no shipped file means infinity: none has `.nan` or `.inf` as a value (the YAML spellings, any
    case, signed or not), and every one loads."""
    for f in SHIPPED:
        assert re.search(r"(?<![\w.])[-+]?\.(inf|nan)\b", f.read_text(), re.I) is None, f
        assert config._yaml(f) is not None


# ---------------------------------------------------------------------------------------------------------------- the enumeration of readers
RAW_YAML_MODULE = {
    "cafe/pm/config.py": "`_load` is the one loader (`_yaml` = `read_yaml`: duplicate keys, octal, aliases, nesting, and now every number checked)",
    "cafe/pm/pipeline.py": "`yaml.dump` of the mission copy a run keeps (it writes a document it has just loaded through `_yaml`; no load)",
}
# A module that reads a YAML file's text by its own code. A new one must be listed with the reason it cannot give the reader a number it would refuse.
OWN_TEXT_READER = {
    "cafe/fea.py": "`hull_elements_along` reads one key of assumptions.yaml by line (the live app image has no pyyaml) and accepts only a plain decimal whole "
                   "number from 1 to MAX_ELEMENTS_ALONG: `.inf`, `.nan` and a 400-digit integer are refused by its grammar (test below)",
}
SCRIPT_DIRS = ("cafe", "lab", "bench", "bin")


def _py_files():
    return sorted(f for d in SCRIPT_DIRS for f in (ROOT / d).rglob("*.py"))


def test_no_module_but_config_loads_yaml_and_the_modules_that_import_it_are_the_listed_ones():
    """Every `import yaml` in `cafe/`, `lab/`, `bench/` and `bin/` (the Python files), and every use of the module's attributes: only `config.py` loads, and the
    one other importer only dumps. A new module that imports pyyaml, or one that calls any attribute of it other than `dump`, fails until classified."""
    importers, loads = {}, []
    for f in _py_files():
        rel = f.relative_to(ROOT).as_posix()
        tree = ast.parse(f.read_text())
        for n in ast.walk(tree):
            if isinstance(n, ast.Import) and any(a.name.split(".")[0] in ("yaml", "ruamel") for a in n.names):
                importers[rel] = n.lineno
            if isinstance(n, ast.ImportFrom) and (n.module or "").split(".")[0] in ("yaml", "ruamel"):
                importers[rel] = n.lineno
                loads.append(f"{rel}:{n.lineno}: from yaml import")
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "__import__" and n.args and isinstance(n.args[0], ast.Constant) \
                    and n.args[0].value == "yaml":
                importers[rel] = n.lineno
            if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "yaml" and rel != "cafe/pm/config.py" and n.attr != "dump":
                loads.append(f"{rel}:{n.lineno}: yaml.{n.attr}")
    assert sorted(importers) == sorted(RAW_YAML_MODULE), importers
    assert loads == []


def test_a_yaml_text_is_read_by_no_code_of_ours_but_the_listed_reader():
    """The same enumeration for a reader that does not use pyyaml at all: a call of `read_text`, `read_bytes` or `open` on an expression that names a YAML file
    (`ASSUMPTIONS`, `PERTURBATIONS`, or a text with `yaml` in it) is a reader of ours; the one there is (`fea.hull_elements_along`) is listed."""
    hits = set()
    for f in _py_files():
        for n in ast.walk(ast.parse(f.read_text())):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in ("read_text", "read_bytes", "open"):
                src = ast.unparse(n.func.value)
                if "yaml" in src.lower() or src in ("ASSUMPTIONS", "PERTURBATIONS"):
                    hits.add(f.relative_to(ROOT).as_posix())
    assert sorted(hits) == sorted(OWN_TEXT_READER), hits


@pytest.mark.parametrize("value", [".inf", "-.inf", ".nan", "1" + "0" * 400, "1e400", "0x10", "7.5", "-3", "0"])
def test_the_one_hand_reader_of_assumptions_yaml_refuses_what_config_yaml_refuses(tmp_path, monkeypatch, value):
    """The only YAML reader that is not `config._yaml` returns a whole number from 1 to 500 or raises ValueError: no non-finite number, no oversized integer
    and no float gets through it."""
    p = tmp_path / "assumptions.yaml"
    p.write_text(f"stage3.fea_elements_along:\n  value: {value}\n  unit: elements\n")
    monkeypatch.setattr(fea, "ASSUMPTIONS", p)
    with pytest.raises(ValueError, match="stage3.fea_elements_along"):
        fea.hull_elements_along()
    p.write_text("stage3.fea_elements_along:\n  value: 70\n  unit: elements\n")
    assert fea.hull_elements_along() == 70
