"""Credibility report: levels come from evidence, missing evidence is level 0 with a stated gap, V&V 20 rows, limitations, assumed inputs."""
import json
import math
import sys

import pytest
import yaml

import cafe.pm
from cafe.pm import credibility as cr
from cafe.pm import dtmb5415
from tests.fixtures import pm_run

REAL = cr.ROOT


@pytest.fixture
def data(tmp_path, monkeypatch):
    d = tmp_path / "data"
    monkeypatch.setenv("CAFE_DATA", str(d))
    return d


@pytest.fixture
def run(tmp_path, data):
    d = tmp_path / "run"
    d.mkdir()
    pm_run.make_run(d)
    return d


def factors(run, root=REAL, data=None):
    return {f["factor"]: f for f in cr.build(run, root, data)["factors"]}


def fake_root(tmp_path, sourced=0, assumed=0, recalled=0, assumed_pert=False, docs=(), tests=True, pyproject=True, builders=True):
    """A repo root with chosen platform provenance, to drive each level of the input-pedigree and uncertainty rules."""
    r = tmp_path / "root"
    (r / "platforms").mkdir(parents=True)
    (r / "config").mkdir()
    (r / "docs").mkdir()
    (r / "cafe" / "schemas").mkdir(parents=True)
    leaves = {f"s{i}": dict(value=1, unit="m", source="datasheet") for i in range(sourced)}
    leaves.update({f"a{i}": dict(value=1, unit="m", assumed=True, why="guess") for i in range(assumed)})
    leaves.update({f"r{i}": dict(value=1, unit="m", source="Smith (recalled)") for i in range(recalled)})
    for name in ("seaglider", "slocum", "saildrone_explorer", "quad_uas"):
        (r / "platforms" / f"{name}.yaml").write_text(yaml.safe_dump({"params": leaves}))
    (r / "config" / "assumptions.yaml").write_text(yaml.safe_dump({"x.y": dict(value=1, unit="m", why="w", replace_with="z")}))
    pert = dict(value=1, unit="m", citation="paper")
    perts = {"p": dict(pert, kind="prior"), **({"q": dict(pert, kind="assumed")} if assumed_pert else {})}
    (r / "config" / "perturbations.yaml").write_text(yaml.safe_dump(perts))
    for n in ("wrfout.json", "umwmout.json"):
        (r / "cafe" / "schemas" / n).write_text("{}")
    for d in docs:
        (r / "docs" / d).write_text("x")
    if builders:
        (r / "docs" / "BUILDERS.md").write_text("rules")
    if tests:
        (r / "tests").mkdir()
        (r / "tests" / "test_x.py").write_text("")
    (r / "pyproject.toml").write_text("[tool.ruff]\n" if pyproject else "")
    return r


def edit(path, fn):
    d = json.loads(path.read_text())
    fn(d)
    path.write_text(json.dumps(d))


# ---------------------------------------------------------------------------------------------------------- the factor table

def test_nine_factors_each_with_a_rule_evidence_and_gaps(run):
    f = factors(run)
    assert list(f) == [k for k, _ in cr.FACTORS] and len(f) == 9
    for x in f.values():
        assert 0 <= x["level"] <= x["evidence_level"] <= 4 and x["rule"] and (x["evidence"] or x["missing"])
        assert x["level"] <= 2 or not x["limitations"]
        for e in x["evidence"]:
            assert e["file"] and e["what"]
    assert max(x["level"] for x in f.values()) <= 3


def test_levels_of_the_synthetic_run(run):
    f = factors(run)
    assert f["data_pedigree"]["level"] == 2 and "TAO" in " ".join(f["data_pedigree"]["missing"])
    assert f["verification"]["level"] == 2 and "grid-convergence" in " ".join(f["verification"]["missing"])
    assert f["validation"]["level"] == 0 and any("not run: DTMB 5415" in m for m in f["validation"]["missing"])
    assert f["input_pedigree"]["level"] in (1, 2) and f["input_pedigree"]["evidence"][0]["file"].startswith("platforms/")
    assert f["uncertainty"]["level"] == 2 and f["uncertainty"]["evidence_level"] == 2
    assert f["robustness"]["evidence_level"] == 2
    assert f["use_history"]["level"] == 0 and "docs/USE_HISTORY.md" in f["use_history"]["missing"][0]
    assert f["ms_management"]["level"] == 3 and f["people"]["level"] == 0


def test_no_ledgers_no_evidence_level_zero_and_says_what_is_missing(tmp_path, data):
    d = tmp_path / "bare"
    d.mkdir()
    f = factors(d)
    for k in ("data_pedigree", "verification", "uncertainty", "robustness", "ms_management", "validation", "input_pedigree"):
        assert f[k]["level"] == 0 and f[k]["evidence"] == [] and f[k]["missing"], k
    assert "no ingest ledger" in f["data_pedigree"]["missing"][0]
    assert "mission.yaml is missing" in f["input_pedigree"]["missing"][0]


def test_ingest_ledger_without_inputs_or_with_failed_check(run):
    p = run / "checkpoints" / "ingest" / "ledger.json"
    edit(p, lambda d: d.update(inputs=[]))
    f = factors(run)["data_pedigree"]
    assert f["level"] == 0 and "lists no inputs" in f["missing"][0]
    edit(p, lambda d: d.update(inputs=[dict(ref="r", sha256=None)], checks=[dict(name="c", ok=False, value=1, limit=0, note="")]))
    f = factors(run)["data_pedigree"]
    assert f["level"] == 1 and "failed or absent (['c'])" in f["missing"][0]


def test_tao_comparison_lifts_data_pedigree(run):
    (run / "ingest").mkdir(exist_ok=True)
    (run / "ingest" / "tao_compare.json").write_text("{}")
    f = factors(run)["data_pedigree"]
    assert f["evidence_level"] == f["level"] == 3 and not any("TAO" in m for m in f["missing"])


def test_tampered_output_breaks_verification(run):
    (run / "stage1" / "summary.json").write_text("{}")
    f = factors(run)
    assert f["verification"]["level"] == 1 and "changed since the stage ran" in f["verification"]["missing"][0]
    assert f["ms_management"]["level"] == 2


def test_verification_without_tests(run, tmp_path):
    f = factors(run, fake_root(tmp_path, sourced=3, tests=False))["verification"]
    assert f["level"] == 1 and "no test files" in f["missing"][0]


def test_ms_management_needs_a_git_sha_and_seeds(tmp_path, data):
    a = tmp_path / "a"
    a.mkdir()
    pm_run.make_run(a, git="none")
    f = factors(a)["ms_management"]
    assert f["level"] == 1 and "lacks a git sha" in f["missing"][0]
    b = tmp_path / "b"
    b.mkdir()
    pm_run.make_run(b)
    edit(b / "checkpoints" / "stage1" / "ledger.json", lambda d: d.update(seeds={}))
    assert factors(b)["ms_management"]["level"] == 1
    assert factors(b, fake_root(tmp_path, 1, builders=False), None)["ms_management"]["level"] == 1


def test_ms_management_level_three_needs_the_process_files(run, tmp_path):
    assert factors(run)["ms_management"]["level"] == 3
    r = fake_root(tmp_path, 1, builders=False)
    assert factors(run, r)["ms_management"]["level"] == 2
    assert factors(run, fake_root(tmp_path / "x", 1, pyproject=False))["ms_management"]["level"] == 2


def test_input_pedigree_levels(run, tmp_path):
    def lvl(root):
        x = factors(run, root)["input_pedigree"]
        return x["evidence_level"], x["level"]
    assert lvl(fake_root(tmp_path / "a", sourced=1, assumed=9))[0] == 1
    assert lvl(fake_root(tmp_path / "b", sourced=6, assumed=4))[0] == 2
    assert lvl(fake_root(tmp_path / "c", sourced=9, assumed=1))[0] == 3
    assert lvl(fake_root(tmp_path / "d", sourced=9, assumed=1, assumed_pert=True))[0] == 2
    assert lvl(fake_root(tmp_path / "e", sourced=3, recalled=7))[0] == 1
    assert lvl(fake_root(tmp_path / "f", sourced=10)) == (3, 2)                   # level 3 on evidence, capped by L05 / L06 / L11
    x = factors(run, fake_root(tmp_path / "g", sourced=10))["input_pedigree"]
    assert x["capped_by"] == ["L01", "L05", "L06", "L11"] and "perturbation prior(s) of kind assumed" not in " ".join(x["missing"])
    assert "['q']" in " ".join(factors(run, fake_root(tmp_path / "h", sourced=10, assumed_pert=True))["input_pedigree"]["missing"])


def test_uncertainty_levels(tmp_path, data):
    ok = tmp_path / "ok"
    ok.mkdir()
    pm_run.make_run(ok, M=80)
    clean = fake_root(tmp_path, sourced=3)
    assert factors(ok, clean)["uncertainty"]["evidence_level"] == 3
    assert factors(ok, fake_root(tmp_path / "w", sourced=3, assumed_pert=True))["uncertainty"]["evidence_level"] == 2
    short = tmp_path / "short"
    short.mkdir()
    pm_run.make_run(short)
    u = factors(short, clean)["uncertainty"]
    assert u["evidence_level"] == 2 and "n below n_certify" in " ".join(u["missing"])
    edit(short / "checkpoints" / "stage1b" / "ledger.json", lambda d: d.update(checks=[]))
    u = factors(short, clean)["uncertainty"]
    assert u["evidence_level"] == 1 and "stratification" in " ".join(u["missing"])
    failed = [dict(name="lhs_stratified_batch1", ok=False, value=1, limit=0, note="")]
    edit(short / "checkpoints" / "stage1b" / "ledger.json", lambda d: d.update(checks=failed))
    assert factors(short, clean)["uncertainty"]["evidence_level"] == 1


def test_robustness_levels(tmp_path, data):
    a = tmp_path / "a"
    a.mkdir()
    pm_run.make_run(a, stage1b_differs=False)
    r = factors(a)["robustness"]
    assert r["evidence_level"] == 3 and r["level"] == 2 and r["capped_by"] == ["L10"]
    b = tmp_path / "b"
    b.mkdir()
    pm_run.make_run(b)                                              # the refit changed glider_eq's verdict
    r = factors(b)["robustness"]
    miss = r["missing"][0]                                          # which other verdicts change follows the fixture's random stream
    assert r["evidence_level"] == 2 and miss.startswith("verdicts changed by the refit: [") and "'glider_eq'" in miss
    (b / "refit" / "refit.json").write_text("{}")
    edit(b / "stage1b" / "summary.json", lambda d: [e["sensitivity"].update(param=None) for e in d["summary"]["vehicles"].values()])
    edit(b / "stage1b" / "summary.json", lambda d: [e["sensitivity"].update(param=None) for e in d["summary"]["links"].values()])
    r = factors(b)["robustness"]
    assert r["evidence_level"] == 1 and "no first-order sensitivity" in r["missing"][0]
    assert "no vehicle was refit" in r["missing"][1]


def test_use_history_and_people_come_only_from_a_record(run, tmp_path):
    r = fake_root(tmp_path, sourced=1, docs=("USE_HISTORY.md", "QUALIFICATIONS.md"))
    f = factors(run, r)
    assert f["use_history"]["level"] == 1 and f["people"]["level"] == 1 and f["use_history"]["missing"] == []
    assert factors(run, fake_root(tmp_path / "n", sourced=1))["people"]["level"] == 0


# ---------------------------------------------------------------------------------------------------------- V&V 20

def write_dtmb(data, frs=("0.10", "0.20", "0.28", "0.41"), bias=1.005):
    root = data / "dtmb5415"
    root.mkdir(parents=True)
    for grid, k, cells in (("coarse", 1.02, 1.0e6), ("fine", bias, 8.0e6)):
        speeds = {fr: dict(cells=cells, ct=dtmb5415.CT_REF[float(fr)] * k, ct_std=1e-6) for fr in frs}
        (root / f"run_{grid}.json").write_text(json.dumps(dict(grid=grid, speeds=speeds)))


def test_dtmb_rows_follow_asme_vv20(data):
    write_dtmb(data, frs=("0.10", "0.28"))
    rows = {r["id"]: r for r in cr.vv20_rows(data)}
    r = rows["dtmb5415:Fr0.28"]
    assert r["status"] == "run" and r["E"] == pytest.approx(r["S"] - r["D"]) and r["D"] == dtmb5415.CT_REF[0.28]
    assert r["u_val"] == pytest.approx(math.sqrt(r["u_num"] ** 2 + r["u_input"] ** 2 + r["u_D"] ** 2))
    assert r["validated"] is True and r["ratio"] == pytest.approx(abs(r["E"]) / r["u_val"])
    assert rows["dtmb5415:Fr0.20"]["status"] == "not run" and "no coarse+fine run for this speed" in rows["dtmb5415:Fr0.20"]["note"]
    assert rows["dtmb5415:Fr0.20"]["E"] is None and rows["dtmb5415:Fr0.20"]["validated"] is None


def test_a_wrong_model_is_not_validated(data):
    write_dtmb(data, bias=1.3)
    rows = [r for r in cr.vv20_rows(data) if r["id"].startswith("dtmb")]
    assert all(r["validated"] is False and r["ratio"] > 1 for r in rows)


def test_all_four_dtmb_rows_validated_gives_level_three_capped_to_two(run, data):
    write_dtmb(data)
    f = factors(run)
    assert f["validation"]["evidence_level"] == 3 and f["validation"]["level"] == 2 and f["validation"]["capped_by"]
    assert f["verification"]["evidence_level"] == 3


def test_validation_with_a_failing_row_stays_at_two(run, data):
    write_dtmb(data)
    write_dtmb_bad = json.loads((data / "dtmb5415" / "run_fine.json").read_text())
    write_dtmb_bad["speeds"]["0.41"]["ct"] *= 1.5
    (data / "dtmb5415" / "run_fine.json").write_text(json.dumps(write_dtmb_bad))
    v = factors(run)["validation"]
    assert v["evidence_level"] == 2 and "fewer than four complete comparisons, or one with |E| > U_val" in v["missing"][0]


def test_stored_stage3_receipts_have_e_but_no_u_val(data):
    rec = data / "receipts"
    rec.mkdir(parents=True)
    (rec / "nest_sphere_100.json").write_text(json.dumps(dict(cd=1.2, d=16, shape=[14, 8, 8])))
    (rec / "lbm_sphere_100.json").write_text(json.dumps(dict(cd=1.5, ref=1.087, d=12)))
    (rec / "lbm_sphere_1000.json").write_text(json.dumps(dict(cd=0.6, ref=0.47)))
    (rec / "wm_flat_plate.json").write_text(json.dumps(dict(cf=0.0035, ittc=0.0030, re=1e6, err=0.17)))
    (rec / "wm_channel.json").write_text(json.dumps(dict(cf=0.0066, cf_dean=0.0062, err=0.06)))
    rows = {r["id"]: r for r in cr.vv20_rows(data)}
    from cafe.pm.stage3 import lbm
    n = rows["nest_sphere:Re100"]
    assert n["D"] == pytest.approx(lbm.morrison(100.0)) and n["E"] == pytest.approx(1.2 - lbm.morrison(100.0)) and "d = 16 cells" in n["note"]
    assert rows["lbm_sphere:Re100"]["D"] == 1.087 and rows["lbm_sphere:Re100"]["E"] == pytest.approx(1.5 - 1.087)
    assert rows["wallmodel:wm_flat_plate"]["E"] == pytest.approx(0.0005) and rows["wallmodel:wm_channel"]["D"] == 0.0062
    for k in ("nest_sphere:Re100", "lbm_sphere:Re1000", "wallmodel:wm_channel"):
        assert rows[k]["status"] == "run" and rows[k]["u_val"] is None and rows[k]["validated"] is None
    for k in ("nest_sphere:Re1000", "nest_sphere:Re1e4", "lbm_sphere:Re1e4"):
        assert rows[k]["status"] == "not run" and rows[k]["note"].startswith("not run:")


def test_only_stored_rows_without_uncertainty_give_validation_level_one(run, data):
    rec = data / "receipts"
    rec.mkdir(parents=True)
    (rec / "lbm_sphere_100.json").write_text(json.dumps(dict(cd=1.5, ref=1.087)))
    v = factors(run)["validation"]
    assert v["level"] == 1 and "no comparison stored U_num, U_input and U_D" in v["missing"][0]


def test_row_arithmetic_edge_cases():
    z = cr._row("a", "c", "s", 1.0, 1.0, (0.0, 0.0, 0.0), "")
    assert z["ratio"] == 0.0 and z["validated"] is True
    inf = cr._row("a", "c", "s", 2.0, 1.0, (0.0, 0.0, 0.0), "")
    assert inf["ratio"] == math.inf and inf["validated"] is False
    assert cr._clean({"x": [math.inf, math.nan, 1.0, "s", (2, 3.0)]}) == {"x": [None, None, 1.0, "s", [2, 3.0]]}


def test_dtmb_not_importable_is_listed_as_not_run(data, monkeypatch):
    monkeypatch.setitem(sys.modules, "cafe.pm.dtmb5415", None)
    monkeypatch.delattr(cafe.pm, "dtmb5415", raising=False)
    rows = cr._dtmb_rows(data)
    assert len(rows) == 1 and rows[0]["status"] == "not run" and "cannot be imported" in rows[0]["note"]


# ---------------------------------------------------------------------------------------------------------- limitations and assumed inputs

LIMITS = ["acoustic 4 km MF range is true by construction", "the USV 12 m/s point is a fit", "the Sun et al. magnitude is 8–26 % vs the published 30–35 %",
          "the Cd receipt is a closure", "several citations were recalled, not re-read", "the glider T(z) profile is assumed",
          "turbulence σ_v/σ_u and σ_w/σ_u are low", "LBM sphere drag is not met on CPU", "the wall model is not validated",
          "the SITL return/landing is unreliable", "the UAS propulsion curve is parametric",
          "GCI values stored before the r = (N_f/N_c)^(1/3) fix were understated"]


def test_limitations_are_listed_verbatim_and_point_at_real_files():
    assert [x["text"] for x in cr.LIMITATIONS] == LIMITS
    names = {k for k, _ in cr.FACTORS}
    for x in cr.LIMITATIONS:
        assert set(x["factors"]) <= names and x["where"]
        for w in x["where"]:
            assert (REAL / w).is_file(), w


def count_assumed(node):
    if not isinstance(node, dict):
        return 0
    return int(bool(node.get("assumed"))) + sum(count_assumed(x) for x in node.values())


def test_every_assumed_input_is_listed(run):
    cred = cr.build(run)
    ids = {i["id"]: i for i in cred["assumed_inputs"]}
    for k in yaml.safe_load((REAL / "config" / "assumptions.yaml").read_text()):
        assert ids[f"assumptions.yaml:{k}"]["kind"] == "assumed"
    for k, e in yaml.safe_load((REAL / "config" / "perturbations.yaml").read_text()).items():
        want = "assumed" if e["kind"] == "assumed" or "ASSUMED" in e["citation"] else "prior"
        assert ids[f"perturbations.yaml:{k}"]["kind"] == want
    assert ids["perturbations.yaml:battery_capacity_scale"]["kind"] == "assumed" and ids["perturbations.yaml:wind_speed_bias"]["kind"] == "prior"
    for f in sorted((REAL / "platforms").glob("*.yaml")):
        n = count_assumed(yaml.safe_load(f.read_text()))
        found = sum(1 for i in cred["assumed_inputs"] if i["file"] == f"platforms/{f.name}")
        assert found == n, f.name
    assert ids["saildrone_explorer.yaml:params.appendage_cda_m2"]["why"].startswith("drag area")
    assert "modems.yaml:modems.benthos_atm960" in ids and len({i["anchor"] for i in cred["assumed_inputs"]}) == len(cred["assumed_inputs"])


def test_platform_items_count_recalled_citations():
    its = cr.platform_items()
    assert sum(i["recalled"] for i in its) >= 10 and sum(i["assumed"] for i in its) > 100
    assert all(i["assumed"] or i["sourced"] or i["path"] for i in its)


# ---------------------------------------------------------------------------------------------------------- the files

def test_write_produces_valid_json_and_a_static_html_page(run, data):
    write_dtmb(data)
    paths = cr.write(run)
    assert [p.name for p in paths] == ["credibility.html", "credibility.json"]
    c = json.loads(paths[1].read_text())
    assert c["schema"] == "cafe.pm.credibility/1" and c["run"] == "run" and len(c["factors"]) == 9 and "NASA-STD-7009B" in c["note"]
    h = paths[0].read_text()
    for _, name in cr.FACTORS:
        assert name.replace("&", "&amp;") in h
    for x in cr.LIMITATIONS:
        assert x["text"] in h
    assert "ASME V&amp;V 20" in h and "not run" in h and "Back to the mission report" in h and "prefers-color-scheme:dark" in h
    assert "capped at 2 by" in h and "never awarded" in h
    assert 'name="viewport"' in h and "<script" not in h
    assert not (set(c["platform_assumed_counts"]) - {p.stem for p in (REAL / "platforms").glob("*.yaml")})


def test_the_page_shows_vv_rows_with_and_without_uncertainty(run, data):
    write_dtmb(data, frs=("0.28",))
    (data / "receipts").mkdir()
    (data / "receipts" / "lbm_sphere_100.json").write_text(json.dumps(dict(cd=1.5, ref=1.087)))
    cr.write(run)
    h = (run / "report" / "credibility.html").read_text()
    assert "not assessable (U_val not stored)" in h and "<td>yes<td>" in h
