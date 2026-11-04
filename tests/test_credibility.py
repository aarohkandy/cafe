"""Credibility report: levels come from evidence, missing evidence is level 0 with a stated gap, V&V 20 rows, limitations, assumed inputs."""
import html
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


def write_tao(run, speed_rmse=1.46, dir_rmse=12.0, moorings=("T0N165E", "T2S170W")):
    (run / "ingest").mkdir(exist_ok=True)
    pooled = dict(speed_rmse=speed_rmse, speed_bias=0.62, dir_rmse_deg=dir_rmse, dir_bias_deg=-3.0, sst_bias=-0.11)
    (run / "ingest" / "tao_compare.json").write_text(json.dumps(dict({m: dict(pooled) for m in moorings}, ALL=pooled)))


def test_tao_comparison_lifts_data_pedigree(run):
    write_tao(run)
    f = factors(run)["data_pedigree"]
    assert f["evidence_level"] == f["level"] == 3 and not any("TAO" in m for m in f["missing"])


def test_the_mooring_comparison_shows_its_numbers_and_says_it_also_sets_the_wind_priors(run):
    """M-17: level 3 read 'strong: checked against an independent reference' whatever the numbers were."""
    write_tao(run)
    f = factors(run)["data_pedigree"]
    ev = " ".join(x["what"] for x in f["evidence"])
    assert ("2 TAO/TRITON moorings" in ev
            and "speed RMSE 1.46 m/s (bias +0.62)" in ev
            and "direction RMSE 12.0 deg" in ev
            and "fits the Stage-1 wind priors" in ev)
    assert f["level_text"] == "strong: compared with moorings (the comparison also sets the wind priors)" and "independent" not in f["level_text"]
    assert "not independent of the run" in f["rule"]
    assert "compared with moorings" in cr._render(cr.build(run, REAL))


@pytest.mark.parametrize("kw", [dict(speed_rmse=2.5), dict(dir_rmse=24.8), dict(dir_rmse=math.nan)])
def test_a_mooring_comparison_with_a_large_error_does_not_earn_level_three(run, kw):
    write_tao(run, **kw)
    f = factors(run)["data_pedigree"]
    assert f["evidence_level"] == f["level"] == 2 and "stays at 2" in " ".join(f["missing"])
    assert f["level_text"] == cr.LEVELS[2]


def test_a_comparison_with_no_pooled_numbers_is_not_a_comparison(run):
    (run / "ingest").mkdir(exist_ok=True)
    (run / "ingest" / "tao_compare.json").write_text("{}")
    f = factors(run)["data_pedigree"]
    assert f["level"] == 2 and "with pooled numbers" in " ".join(f["missing"])


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
    t = factors(run)["ms_management"]["level_text"]                # M-20: only self-checks stand behind level 3
    assert "audited by the tool" in t and "independent reference" not in t      # round 7, M-23
    assert "`make audit` runs ruff; this report only checks that it is configured" in t and "not run by the audit" not in t      # round 8, M-46
    r = fake_root(tmp_path, 1, builders=False)
    assert factors(run, r)["ms_management"]["level"] == 2 and factors(run, r)["ms_management"]["level_text"] == cr.LEVELS[2]
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


def test_a_copied_stage_1b_takes_its_latin_hypercube_checks_from_stage_1(tmp_path, data):
    """M-16: stage 1b is a copy whenever no window passes; its ledger has no LHS check, but the stage-1 ledger that ran the ensemble does."""
    d = tmp_path / "copy"
    d.mkdir()
    pm_run.make_run(d)
    clean = fake_root(tmp_path, sourced=3)
    edit(d / "checkpoints" / "stage1b" / "ledger.json", lambda x: x.update(checks=[], notes=["no vehicle was refit: stage 1b is stage 1 (copied, not rerun)"]))
    u = factors(d, clean)["uncertainty"]
    assert u["evidence_level"] >= 2 and any("passed" in e["what"] and e["file"] == "run:checkpoints/stage1/ledger.json" for e in u["evidence"])
    edit(d / "checkpoints" / "stage1" / "ledger.json", lambda x: x.update(checks=[dict(name="lhs_stratified_batch1", ok=False, value=1, limit=0, note="")]))
    u = factors(d, clean)["uncertainty"]
    assert u["evidence_level"] == 1 and "in the stage1 ledger (stage 1b is a copy of it)" in " ".join(u["missing"])
    edit(d / "checkpoints" / "stage1b" / "ledger.json", lambda x: x.update(notes=[]))          # not a copy: stage 1b's own (absent) checks decide
    assert "in the stage1b ledger" in " ".join(factors(d, clean)["uncertainty"]["missing"])


def test_robustness_levels(tmp_path, data):
    a = tmp_path / "a"
    a.mkdir()
    pm_run.make_run(a, stage1b_differs=False)
    r = factors(a)["robustness"]
    assert r["evidence_level"] == 3 and r["level"] == 2 and r["capped_by"][0] == "L10"
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

def write_dtmb(data, frs=("0.10", "0.20", "0.28", "0.41"), bias=1.005, recipe=dtmb5415.RECIPE):
    root = data / "dtmb5415"
    root.mkdir(parents=True)
    for grid, k, cells in (("coarse", 1.02, 1.0e6), ("fine", bias, 8.0e6)):
        speeds = {fr: dict(cells=cells, ct=dtmb5415.CT_REF[float(fr)] * k, ct_std=1e-6, **({"converged": True} if grid == "fine" else {})) for fr in frs}
        d = dict(grid=grid, speeds=speeds)      # (round 8, M-10: a finest grid with no `converged` record is not judged, and the real files always have it)
        (root / f"run_{grid}.json").write_text(json.dumps(d if recipe is None else dict(d, recipe=recipe)))


def test_dtmb_rows_follow_asme_vv20(data):
    write_dtmb(data, frs=("0.10", "0.28"))
    rows = {r["id"]: r for r in cr.vv20_rows(data)}
    r = rows["dtmb5415:Fr0.28"]
    assert r["status"] == "run" and r["E"] == pytest.approx(r["S"] - r["D"]) and r["D"] == dtmb5415.CT_REF[0.28]
    assert r["u_val"] == pytest.approx(math.sqrt(r["u_num"] ** 2 + r["u_input"] ** 2 + r["u_D"] ** 2))
    assert r["validated"] is True and r["ratio"] == pytest.approx(abs(r["E"]) / r["u_val"])
    assert rows["dtmb5415:Fr0.20"]["status"] == "not run" and "no coarse+fine run for this speed" in rows["dtmb5415:Fr0.20"]["note"]
    assert rows["dtmb5415:Fr0.20"]["E"] is None and rows["dtmb5415:Fr0.20"]["validated"] is None


def test_files_of_another_recipe_are_not_rows_and_say_why_so_validation_reads_none(run, data):
    """M-3: the discarded v3 run files (no recipe stamp) lifted Validation to 2 and showed 'validated' at an uncertainty as large as C_T."""
    write_dtmb(data, recipe=None)
    rows = [r for r in cr.vv20_rows(data) if r["id"].startswith("dtmb")]
    assert len(rows) == 4 and all(r["status"] == "not run" and r["S"] is None and r["validated"] is None for r in rows)
    note = rows[0]["note"]
    assert note.startswith("not run: run_") and all(f"run_{g}.json was made by recipe None, not pout-lts01-parts-v4" in note for g in ("coarse", "fine"))
    f = factors(run)
    assert f["validation"]["level"] == 0 and f["validation"]["evidence"] == [] and any("recipe None" in m for m in f["validation"]["missing"])
    assert f["verification"]["evidence_level"] == 2 and "grid-convergence" in " ".join(f["verification"]["missing"])
    other = data.parent / "other"
    write_dtmb(other, recipe="old-recipe")
    assert "run_coarse.json was made by recipe old-recipe, not pout-lts01-parts-v4" in cr.vv20_rows(other)[0]["note"]


def test_an_uncertainty_as_wide_as_the_reference_cannot_validate_it(run, data):
    """M-3: U_val must be below half the reference for a row to count toward Validation level 3."""
    wide = cr._row("a", "c", "s", 1.0, 1.0, (0.6, 0.6, 0.6), "")
    assert wide["validated"] is True and wide["informative"] is False and wide["u_frac"] == pytest.approx(math.sqrt(3 * 0.36))
    narrow = cr._row("a", "c", "s", 1.0, 1.0, (0.1, 0.1, 0.1), "")
    assert narrow["informative"] is True and cr._row("a", "c", "s", 1.0, 0.0, (0.1, 0.1, 0.1), "")["informative"] is False
    f = cr.Facts(run, REAL, data)
    f.vv = [dict(narrow, id=f"n{i}", status="run") for i in range(3)] + [dict(wide, id="w", status="run")]
    lvl, ev, miss = cr._validation(f)
    assert lvl == 2 and "U_val is 50% of the reference or more in ['w']" in " ".join(miss) and "with U_val below 50% of the reference" in ev[0]["what"]
    f.vv[3] = dict(narrow, id="n3", status="run")
    assert cr._validation(f)[0] == 3
    c = cr._render(dict(cr.build(run, REAL, data), vv20=[dict(wide, id="w", case="c", status="run", note="")]))
    assert "yes (U_val is 104% of the reference: too wide to validate it)" in c


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
    (rec / "nest_sphere_100_d8.json").write_text(json.dumps(dict(cd=1.6, d=8, shape=[7, 4, 4])))
    (rec / "nest_sphere_100_d16.json").write_text(json.dumps(dict(cd=1.2, d=16, shape=[14, 8, 8])))               # stage 3 stores one file per resolution
    (rec / "nest_sphere_100_d12.json").write_text(json.dumps(dict(cd=1.4, d=12, shape=[10, 6, 6])))
    (rec / "lbm_sphere_100.json").write_text(json.dumps(dict(cd=1.5, ref=1.087, d=12)))
    (rec / "lbm_sphere_1000.json").write_text(json.dumps(dict(cd=0.6, ref=0.47)))
    (rec / "wm_flat_plate.json").write_text(json.dumps(dict(cf=0.0035, ittc=0.0030, re=1e6, err=0.17)))
    (rec / "wm_channel.json").write_text(json.dumps(dict(cf=0.0066, cf_dean=0.0062, err=0.06)))
    rows = {r["id"]: r for r in cr.vv20_rows(data)}
    from cafe.pm.stage3 import lbm
    n = rows["nest_sphere:Re100"]
    assert n["D"] == pytest.approx(lbm.morrison(100.0)) and n["E"] == pytest.approx(1.2 - lbm.morrison(100.0))
    assert "d = 16 cells (d = 8 and 12 also stored)" in n["note"]
    # round 3 M-11: the row used to read "nest_sphere_100.json is not stored"
    assert n["source"].endswith("nest_sphere_100_d16.json")
    assert rows["lbm_sphere:Re100"]["D"] == 1.087 and rows["lbm_sphere:Re100"]["E"] == pytest.approx(1.5 - 1.087)
    assert rows["wallmodel:wm_flat_plate"]["E"] == pytest.approx(0.0005) and rows["wallmodel:wm_channel"]["D"] == 0.0062
    for k in ("nest_sphere:Re100", "lbm_sphere:Re1000", "wallmodel:wm_channel"):
        assert rows[k]["status"] == "run" and rows[k]["u_val"] is None and rows[k]["validated"] is None
    for k in ("nest_sphere:Re1000", "nest_sphere:Re1e4", "lbm_sphere:Re1e4"):
        assert rows[k]["status"] == "not run" and rows[k]["note"].startswith("not run:")
    assert rows["nest_sphere:Re1000"]["note"] == f"not run: no nest_sphere_1000_d*.json under {rec}"
    assert rows["lbm_sphere:Re1e4"]["note"] == "not run: lbm_sphere_1e4.json is not stored"


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
# round 2 (docs/CREDIBILITY.md has the same sentences; L13 is the run-time sub-grid limitation and sits between L12 and L14)
LIMITS2 = ["the wind prior's persistent and short-lived parts are split from the TAO moorings over this window: an estimate of the order, not a measurement",
           "no LES window can reach the lattice viscosity floor on a CPU, so none is run and the sub-grid layer and the drag refit stay uncalibrated; "
           "no GPU run exists",
           "the refit is a single pass: stage 1 is rerun once with the refitted multipliers, not looped until the verdicts stop changing",
           "UAS attitude exceedance cannot fire in this controller model (tilt clamp 35 deg, exceedance 42 deg)",
           "the USV speed prior is calibrated in a scenario without current, and the mission's westward current then lowers the speed ratio again; "
           "whether Chiodi et al.'s 0.178 already includes currents is not known, so a double penalty is possible and not established",
           "the persistent wind-speed prior is a boundary moment estimate from the TAO moorings of one regime, not a measured spread: in the evidence run "
           "q5 11 moorings over 6 days gave 0.113 m/s, with a 95 % upper bound of about 0.5 m/s (the literature prior was 2.0 m/s), and regime-to-regime "
           "bias outside the window is not sampled"]


def test_limitations_are_listed_verbatim_and_point_at_real_files():
    assert [x["text"] for x in cr.LIMITATIONS][:12] == LIMITS
    assert [x["id"] for x in cr.LIMITATIONS][12:] == ["L14", "L15", "L16", "L17", "L18", "L19", "L20"] and [x["text"] for x in cr.LIMITATIONS][12:-1] == LIMITS2
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
        assert html.escape(x["text"]) in h                                   # (an apostrophe is written as an entity)
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


# ---------------------------------------------------------------------------------------------------------- review round 1, batch D

PERTS = {"n": dict(dist="normal", mean=1.5, value=2.0, unit="m/s", citation="c", kind="prior"),
         "l": dict(dist="lognormal", median=1.0, value=0.3, unit="x", citation="c", kind="prior"),
         "u": dict(dist="uniform", lo=-0.35, hi=-0.3, value=0.0, unit="x", citation="c", kind="prior"),
         "f": dict(dist="fixed", mean=100000.0, value=0.0, unit="m", citation="c", kind="prior"),
         "w": dict(dist="weird", mean=3, value=4, unit="x", citation="ASSUMED guess", kind="assumed")}


def perturbation_items(root, run=None):
    return {i["id"].split(":", 1)[1]: i for i in cr.assumed_inputs(root, run) if i["file"] == "config/perturbations.yaml"}


def test_each_prior_is_printed_as_the_distribution_that_is_drawn_not_as_its_spread_field(tmp_path):
    """M-24: current_correlation_length printed 0.0 (its mean is 1e5) and usv_vpp_bias 0.0 (it is uniform on [-0.35, -0.30]): `value` is the spread."""
    r = fake_root(tmp_path)
    (r / "config" / "perturbations.yaml").write_text(yaml.safe_dump(PERTS))
    it = perturbation_items(r)
    assert it["n"]["value"] == "normal(mean 1.5, sigma 2.0)" and it["l"]["value"] == "lognormal(median 1.0, sigma 0.3)"
    assert it["u"]["value"] == "uniform [-0.35, -0.3]" and it["f"]["value"] == "fixed at 100000.0 (a setting, not sampled)"
    assert it["w"]["value"] == "{'dist': 'weird', 'mean': 3, 'value': 4}" and it["w"]["kind"] == "assumed" and it["n"]["kind"] == "prior"


def test_the_real_priors_print_their_distribution(run):
    it = perturbation_items(REAL, run)
    spec = yaml.safe_load((REAL / "config" / "perturbations.yaml").read_text())
    assert it["current_correlation_length"]["value"] == "fixed at 100000.0 (a setting, not sampled)"
    for k, e in spec.items():
        assert it[k]["value"] == cr.dist_text(e) and it[k]["value"] != "0.0", k
    assert "drew" not in it["wind_speed_bias"]["value"]                                                    # the synthetic run drew the yaml's own prior


def test_a_fitted_prior_shows_what_the_run_drew_and_an_unchanged_one_does_not(run, tmp_path):
    r = fake_root(tmp_path)
    (r / "config" / "perturbations.yaml").write_text(yaml.safe_dump(PERTS))
    same = {"l": dict(dist="lognormal", median=1.0, sigma=0.3), "u": dict(dist="uniform", lo=-0.35, hi=-0.3)}
    edit(run / "stage1b" / "summary.json", lambda d: d.update(priors=dict(same, n=dict(dist="normal", mean=-0.616, sd=1.328))))
    it = perturbation_items(r, run)
    assert it["n"]["value"] == "normal(mean 1.5, sigma 2.0); this run drew normal(mean -0.616, sigma 1.328) (fitted)"
    assert it["l"]["value"] == "lognormal(median 1.0, sigma 0.3)" and it["u"]["value"] == "uniform [-0.35, -0.3]" and it["f"]["value"].startswith("fixed at")
    moved = dict(u=dict(dist="uniform", lo=-0.1, hi=0.0), l=dict(dist="lognormal", median=2.0, sigma=0.3))
    edit(run / "stage1b" / "summary.json", lambda d: d.update(priors=moved))
    it = perturbation_items(r, run)
    assert it["u"]["value"].endswith("; this run drew uniform [-0.1, 0.0] (fitted)")
    assert it["l"]["value"].endswith("; this run drew lognormal(median 2.0, sigma 0.3) (fitted)")
    assert cr._used(dict(dist="other", x=1)) == "{'dist': 'other', 'x': 1}"


def test_the_priors_come_from_stage_1b_else_stage_1_else_none(run, tmp_path):
    assert cr.run_priors(None) == {} and cr.run_priors(tmp_path / "empty") == {}
    s1b = json.loads((run / "stage1b" / "summary.json").read_text())["priors"]
    assert cr.run_priors(run) == s1b and "wind_speed_bias" in s1b
    (run / "stage1b" / "summary.json").unlink()
    assert cr.run_priors(run) == json.loads((run / "stage1" / "summary.json").read_text())["priors"]


def test_a_fitted_sigma_is_listed_as_fitted_with_both_values_and_is_not_an_assumed_input(run, data):
    """Round 3 M-12: the TAO fit replaces env.sigma.sst_k and t2_k (Context.env), but the page listed 0.5 K and 1.0 K as this run's assumed inputs."""
    def sig(c):
        return {i["id"].split(":")[1]: i for i in c["assumed_inputs"] if i["id"].startswith("assumptions.yaml:env.sigma.")}
    base = cr.build(run, REAL, data)
    assert {i["kind"] for i in sig(base).values()} == {"assumed"} and sig(base)["env.sigma.sst_k"]["value"] == "0.5"
    (run / "ingest").mkdir(exist_ok=True)
    (run / "ingest" / "env_sigmas_fitted.json").write_text(json.dumps(dict(sst_k=0.2592, t2_k=1.1908)))
    c = cr.build(run, REAL, data)
    s = sig(c)
    assert s["env.sigma.sst_k"]["kind"] == "fitted" and s["env.sigma.sst_k"]["value"] == "this run used 0.259 (fitted from the TAO comparison); assumed 0.5"
    assert s["env.sigma.t2_k"]["kind"] == "fitted" and "this run used 1.19" in s["env.sigma.t2_k"]["value"] and "assumed 1.0" in s["env.sigma.t2_k"]["value"]
    assert s["env.sigma.q2_frac"]["kind"] == "assumed" and len(c["assumed_inputs"]) == len(base["assumed_inputs"])         # only the two are re-labelled
    n = lambda cc: sum(i["kind"] == "assumed" for i in cc["assumed_inputs"])
    assert n(c) == n(base) - 2


def test_the_credibility_json_lists_the_priors_the_run_drew(run, data):
    edit(run / "stage1b" / "summary.json", lambda d: d["priors"].update(wind_speed_bias=dict(dist="normal", mean=-0.616, sd=1.328)))
    c = cr.build(run, REAL, data)
    wsb = next(i for i in c["assumed_inputs"] if i["id"] == "perturbations.yaml:wind_speed_bias")
    assert wsb["value"].endswith("; this run drew normal(mean -0.616, sigma 1.328) (fitted)")


def test_the_sanity_block_compares_each_verdict_with_the_briefs_expected_outcome(run, data):
    """M-30: the credibility report had no row comparing the outcome with BRIEF section 6."""
    c = cr.build(run, REAL, data)
    sn = c["sanity"]
    rows = {r["id"]: r for r in sn["rows"]}
    assert sn["mission"] == "tepex_c_demo" and "It applies to that mission only" in sn["note"] and "sanity check and not as a target" in sn["note"]
    # glider_2n's acoustic link is in the table but not in this run, so it has no row
    assert set(rows) == {"glider_eq", "glider_2n", "usv", "uas", "usv-uas-rf", "usv-shore-iridium", "glider_eq-ship-acoustic"}
    s = json.loads((run / "stage1b" / "summary.json").read_text())["summary"]
    for k, r in rows.items():
        e = (s["vehicles"] | s["links"])[k]
        assert r["observed"] == e["verdict"]["verdict"] and (r["k_fail"], r["n"]) == (e["k_fail"], e["n"]), k
    assert rows["glider_eq"]["observed"] == "GO" and rows["glider_eq"]["agrees"] is False                  # the brief expects MARGINAL or NO-GO at a station
    # round 3 M-1: glider_2n is a drift glider on a fixed heading; its GO is not agreement with anything the mission asks
    assert rows["glider_2n"]["observed"] == "GO" and rows["glider_2n"]["agrees"] is None and "no mission criterion" in rows["glider_2n"]["detail"]
    assert rows["usv"]["agrees"] == (rows["usv"]["observed"] in ("MARGINAL", "GO"))
    assert rows["uas"]["agrees"] is None and rows["uas"]["allowed"] is None and rows["glider_eq-ship-acoustic"]["agrees"] is None
    assert rows["usv-uas-rf"]["agrees"] is True


def acoustic(run, **fields):
    edit(run / "stage1b" / "summary.json", lambda d: d["summary"]["links"]["glider_eq-ship-acoustic"].update(fields))


@pytest.mark.parametrize("verdict,fields,agrees,words", [
    ("NO-GO", dict(distance_km_median=555.0), True, "median distance to the ship 555 km, beyond 3 km"),
    ("GO", dict(distance_km_median=555.0), False, "beyond 3 km"),
    ("GO", dict(distance_km_median=1.2), True, "within 3 km"),
    ("NO-GO", dict(distance_km_median=1.2), False, "within 3 km"),
    ("NO-GO", dict(frac_out_of_range=0.9), True, "out of the modem's range, beyond 3 km"),
    ("NO-GO", dict(frac_out_of_range=0.1), None, "holds no ship distance"),
    ("NO-GO", dict(), None, "holds no ship distance")])
def test_the_acoustic_sanity_row_reads_the_runs_ship_distance(run, data, verdict, fields, agrees, words):
    """M-18: the row said 'the distance is not in the verdict' though the run holds it."""
    acoustic(run, **fields)
    edit(run / "stage1b" / "summary.json", lambda d: d["summary"]["links"]["glider_eq-ship-acoustic"]["verdict"].update(verdict=verdict))
    row = next(r for r in cr.build(run, REAL, data)["sanity"]["rows"] if r["id"] == "glider_eq-ship-acoustic")
    assert row["agrees"] is agrees and words in row["detail"] and "NO-GO beyond it" in row["expected"]


def test_a_station_glider_still_has_a_checked_sanity_row_and_only_a_drift_one_is_exempt(run, data):
    """Round 3 M-1: the exemption follows task.mode in the run's mission, not the vehicle id."""
    assert next(r for r in cr.build(run, REAL, data)["sanity"]["rows"] if r["id"] == "glider_eq")["agrees"] is False
    m = (run / "mission.yaml").read_text()
    assert m.count("mode: drift") == 1
    (run / "mission.yaml").write_text(m.replace("mode: drift", "mode: station"))                         # no longer a drift glider: back to being compared
    assert next(r for r in cr.build(run, REAL, data)["sanity"]["rows"] if r["id"] == "glider_2n")["agrees"] is True


def test_the_usv_sanity_row_prints_the_speed_ratio_beside_chiodis(run, data):
    edit(run / "stage1b" / "summary.json", lambda d: d["summary"]["vehicles"]["usv"].update(speed=dict(ratio_median=0.107)))
    c = cr.build(run, REAL, data)
    row = next(r for r in c["sanity"]["rows"] if r["id"] == "usv")
    assert "0.107" in row["detail"] and "0.178" in row["detail"] and "no current, uniform wind, sailing to a station" in row["detail"]
    assert "double penalty" in row["detail"]
    cr.write(run)
    assert "sailing to a station" in (run / "report" / "credibility.html").read_text()


def test_another_mission_gets_no_sanity_block_and_the_page_shows_it_only_for_the_demo(run, data):
    cr.write(run)
    h = (run / "report" / "credibility.html").read_text()
    assert "Sanity check against the brief (tepex_c_demo only)" in h and "cannot be checked from the verdict" in h and "<b>NO</b>" in h
    assert "the run holds no ship distance for this link" in h
    (run / "mission.yaml").write_text((run / "mission.yaml").read_text().replace("name: tepex_c_demo", "name: other"))
    assert cr.build(run, REAL, data)["sanity"] is None
    cr.write(run)
    assert "Sanity check" not in (run / "report" / "credibility.html").read_text()
    (run / "mission.yaml").unlink()
    assert cr.build(run, REAL, data)["sanity"] is None


def test_without_a_stage_1b_summary_there_is_nothing_to_compare(tmp_path, data):
    run = tmp_path / "bare"
    run.mkdir()
    shutil_copy = (REAL / "missions" / "tepex_c_demo.yaml").read_text()
    (run / "mission.yaml").write_text(shutil_copy)
    assert cr.build(run, REAL, data)["sanity"] is None


def subgrid_root(tmp_path, source_run):
    r = tmp_path / "sg"
    (r / "config").mkdir(parents=True)
    (r / "config" / "subgrid.json").write_text(json.dumps(dict(calibration=dict(source_run=source_run))))
    return r


def test_the_sub_grid_layer_is_uncalibrated_when_the_stage_3_ledger_says_so_or_the_config_has_no_source_run(run, tmp_path):
    none, calibrated = subgrid_root(tmp_path / "a", None), subgrid_root(tmp_path / "b", "run_x")
    assert cr.subgrid_uncalibrated(run, calibrated) is None
    why = cr.subgrid_uncalibrated(run, none)
    assert why.startswith("sub-grid layer uncalibrated: config/subgrid.json calibration.source_run is null") and "defaults" in why
    edit(run / "checkpoints" / "stage3" / "ledger.json", lambda d: d.update(notes=["other", "sub-grid layer uncalibrated: no LES window passed"]))
    assert cr.subgrid_uncalibrated(run, calibrated) == "sub-grid layer uncalibrated: no LES window passed"      # the ledger's own reason wins
    assert cr.subgrid_uncalibrated(run, none) == "sub-grid layer uncalibrated: no LES window passed"
    assert cr.subgrid_uncalibrated(run, tmp_path / "missing") == "sub-grid layer uncalibrated: no LES window passed"
    assert "source_run is null" in cr.subgrid_uncalibrated(run / "nope", tmp_path / "missing")                 # no ledger and no config: nothing calibrated it


def test_a_run_that_wrote_its_own_calibration_is_calibrated_even_though_the_tracked_config_is_not(run, tmp_path):
    """Round 3 M-23: stage 3 no longer writes config/subgrid.json; its calibration is stage3/subgrid_calibration.json."""
    none = subgrid_root(tmp_path / "a", None)
    assert "source_run is null" in cr.subgrid_uncalibrated(run, none)
    (run / "stage3" / "subgrid_calibration.json").write_text(json.dumps(dict(source_run="stage 3 of this run", sigma_u_over_ustar=2.5)))
    assert cr.subgrid_uncalibrated(run, none) is None
    (run / "stage3" / "subgrid_calibration.json").write_text(json.dumps(dict(source_run=None)))
    assert "source_run is null" in cr.subgrid_uncalibrated(run, none)


def test_an_uncalibrated_sub_grid_layer_is_a_limitation_that_caps_validation_and_uncertainty(run, data, monkeypatch):
    why = "sub-grid layer uncalibrated: no LES window passed"
    monkeypatch.setattr(cr, "subgrid_uncalibrated", lambda *a, **k: why)
    c = cr.build(run, REAL, data)
    assert c["limitations"][12] == dict(cr.SUBGRID_LIMITATION, text=why) and len(c["limitations"]) == len(cr.LIMITATIONS) + 1
    assert [x["id"] for x in c["limitations"]][11:14] == ["L12", "L13", "L14"]
    f = {x["factor"]: x for x in c["factors"]}
    assert "L13" in f["validation"]["limitations"] and "L13" in f["uncertainty"]["limitations"] and "L13" not in f["people"]["limitations"]
    assert why in cr._render(c)
    monkeypatch.setattr(cr, "subgrid_uncalibrated", lambda *a, **k: None)
    assert cr.build(run, REAL, data)["limitations"] == cr.LIMITATIONS


# ---------------------------------------------------------------------------------------------------------- review round 5 (batch S)

def test_the_wind_prior_limitation_names_the_upper_bound_and_the_one_regime_and_lowers_no_cap():
    """Round 5 M-10: L19. Both factors it bears on were already capped at 2 by other limitations, so it moves no level."""
    x = next(x for x in cr.LIMITATIONS if x["id"] == "L19")
    assert "95 % upper bound" in x["text"] and "one regime" in x["text"] and "regime-to-regime bias" in x["text"] and x["where"] == ["cafe/pm/pipeline.py"]
    others = {f for y in cr.LIMITATIONS if y["id"] != "L19" for f in y["factors"]}
    assert set(x["factors"]) <= others


def test_only_an_ensemble_that_leaves_5_percent_open_counts_as_short_of_n_certify(tmp_path):
    """Round 5 M-11: the Uncertainty factor listed '8 verdict(s) have n below n_certify' for NO-GO ensembles no number of members could certify."""
    run = tmp_path / "run"
    run.mkdir()
    pm_run.make_run(run, M=48)
    clean = fake_root(tmp_path / "root", sourced=3)
    def only_failing(d):
        for e in (*d["summary"]["vehicles"].values(), *d["summary"]["links"].values()):
            e["k_fail"] = 40                                                                                     # 40 of 48 failed: lower bound 0.7, excluded
    edit(run / "stage1b" / "summary.json", only_failing)
    u = factors(run, clean)["uncertainty"]
    assert not any("n below n_certify" in m for m in u["missing"]) and u["evidence_level"] == 3
    edit(run / "stage1b" / "summary.json", lambda d: d["summary"]["vehicles"]["usv"].update(k_fail=0))
    u = factors(run, clean)["uncertainty"]
    assert u["evidence_level"] == 2 and "1 verdict(s) have n below n_certify" in " ".join(u["missing"])             # a zero-failure ensemble does


# ---------------------------------------------------------------------------------------------------------- review round 6 (batch S)

def test_the_single_height_uas_turbulence_is_a_listed_limitation_that_moves_no_level():
    """Round 6 M-18: L20. The Mann box of a sortie is made at one height (stage1 `z = deck + mean(levels)`) and used on every leg."""
    x = next(x for x in cr.LIMITATIONS if x["id"] == "L20")
    assert x["text"].startswith("UAS turbulence is generated at one height for all legs") and x["where"] == ["cafe/pm/stage1.py", "cafe/pm/env/subgrid.py"]
    assert "z = so[\"deck_height_m\"] + float(np.mean(so[\"levels_m\"]))" in (REAL / "cafe/pm/stage1.py").read_text()          # the claim is the code's
    others = {f for y in cr.LIMITATIONS if y["id"] != "L20" for f in y["factors"]}
    assert set(x["factors"]) <= others
    assert "Credibility limitation L20" in (REAL / "docs/PHYSICS.md").read_text()


def test_the_reach_table_lists_every_limitation_that_caps_each_factor():
    """Round 6 integration: L19 (round 5) caps validation and uncertainty but the "What the current build can reach" table of docs/CREDIBILITY.md
    never listed it; nothing compared that table with the code. Each row's "Caps from" is the code's limitations of that factor, L13 included."""
    import pathlib, re
    doc = (pathlib.Path(cr.ROOT) / "docs" / "CREDIBILITY.md").read_text()
    table = doc.split("### What the current build can reach")[1].split("This table is derived")[0]
    rows = {m[0].strip(): m[1].strip() for m in re.findall(r"^\| ([^|]+) \| ([^|]+) \|", table, re.M) if m[0].strip() not in ("Factor", "---")}
    names = {"Verification": "verification", "Validation": "validation", "Input pedigree": "input_pedigree", "Uncertainty characterization": "uncertainty",
             "Results robustness": "robustness"}
    lims = cr.LIMITATIONS + [cr.SUBGRID_LIMITATION]
    for row, fac in names.items():
        want = sorted(lim["id"] for lim in lims if fac in lim["factors"])
        assert rows[row].split(", ") == want, (row, rows[row], want)
    assert set(names) | {"Data pedigree", "Use history", "M&S management", "People qualifications"} == set(rows)
    assert {f for lim in lims for f in lim["factors"]} <= set(names.values())


# ---------------------------------------------------------------------------------------------------------- round 7 (M-5, M-15, M-23)

def write_dtmb3(data, converged, drift=0.0075):
    """Three grids per speed with the medium value off the line (the grid sequence oscillates); `converged` is {fr: finest grid converged}."""
    root = data / "dtmb5415"
    root.mkdir(parents=True)
    for grid, k, cells in (("coarse", 1.010, 1.0e6), ("medium", 0.995, 3.0e6), ("fine", 1.005, 8.0e6)):
        speeds = {fr: dict(cells=cells, ct=dtmb5415.CT_REF[float(fr)] * k, ct_std=1e-6, **({"converged": c, "drift": drift} if grid == "fine" else {}))
                  for fr, c in converged.items()}
        (root / f"run_{grid}.json").write_text(json.dumps(dict(grid=grid, recipe=dtmb5415.RECIPE, speeds=speeds)))


CONV = {"0.10": True, "0.20": False, "0.28": False, "0.41": False}


def test_an_unconverged_finest_grid_leaves_the_row_not_judged_and_the_note_names_the_grid_sequence(data):      # round 7, M-5
    write_dtmb3(data, CONV)
    rows = {r["id"]: r for r in cr.vv20_rows(data)}
    ok = rows["dtmb5415:Fr0.10"]
    assert ok["validated"] is True and "oscillating" in ok["note"] and "Fs = 3, p = 2 assumed" in ok["note"] and "not converged" not in ok["note"]
    for fr in ("0.20", "0.28", "0.41"):
        r = rows[f"dtmb5415:Fr{fr}"]
        assert r["validated"] is None and r["not_judged"].startswith("not judged")
        assert "finest grid not converged (iterative drift 0.0075 (limit 0.005))" in r["note"]
        assert "oscillating" in r["note"]


def test_validation_three_counts_only_rows_whose_finest_grid_converged(run, data):
    write_dtmb3(data, {k: True for k in CONV})
    assert factors(run)["validation"]["evidence_level"] == 3                              # four converged rows, all inside U_val
    for p in (data / "dtmb5415").iterdir():
        p.unlink()
    (data / "dtmb5415").rmdir()
    write_dtmb3(data, CONV)
    v = factors(run)["validation"]
    assert v["evidence_level"] == 2 and "3 not judged (finest grid not converged)" in v["evidence"][0]["what"]
    assert any("not judged because the finest grid has not converged" in m for m in v["missing"])


def test_the_table_header_says_both_informative_thresholds_and_verification_names_the_fallback(run, data):
    write_dtmb3(data, {k: True for k in CONV})
    c = cr.build(run, REAL, data)
    h = cr._render(c)
    assert "counts toward Validation 3 if U_val / D &lt; 0.5 (credibility)" in h and "the DTMB receipts require &le; 0.10" in h
    assert any("rest on the Fs = 3, p = 2 fallback" in m for m in {f["factor"]: f for f in c["factors"]}["verification"]["missing"])
    c2 = cr.build(run, REAL, data)
    c2["vv20"][0]["not_judged"] = "not judged: the finest grid has not converged"
    c2["vv20"][0]["validated"] = None
    assert "not judged: the finest grid has not converged" in cr._render(c2)


def sens_run(tmp_path, ranked):
    """A run whose every ensemble has a permutation test at the noise floor and `ranked` of them a named parameter; no refit."""
    d = tmp_path / "s"
    d.mkdir(parents=True)
    pm_run.make_run(d)
    (d / "refit" / "refit.json").write_text("{}")
    def put(s):
        es = [*s["summary"]["vehicles"].values(), *s["summary"]["links"].values()]
        for i, e in enumerate(es):
            e["sensitivity"].update(param="x" if i < ranked else None, noise_floor=0.118)
    edit(d / "stage1b" / "summary.json", put)
    return d


def test_one_sensitivity_among_many_tests_is_not_clearly_above_chance(tmp_path, data):      # round 7, M-23
    r = factors(sens_run(tmp_path, 1))["robustness"]
    assert r["evidence_level"] == 1 and any("none stands clearly above chance" in e["what"] for e in r["evidence"])
    assert "no first-order sensitivity" not in " ".join(r["missing"]) and any("do not stand clearly above chance" in m for m in r["missing"])
    assert factors(sens_run(tmp_path / "y", 3))["robustness"]["evidence_level"] == 2           # three of seven: a 0.3 % chance by luck


def test_a_refit_alone_earns_robustness_two_as_the_printed_rule_says(tmp_path, data):
    d = sens_run(tmp_path, 0)
    assert "or a refit reran" in cr.RULES["robustness"] and "clearly above chance" in cr.RULES["robustness"]
    (d / "refit" / "refit.json").write_text(json.dumps({"glider_eq": {"used": True}}))
    assert factors(d)["robustness"]["evidence_level"] == 2


def test_the_usv_speed_prior_width_is_not_an_uncertainty_of_the_model(run, data):      # round 7, M-15
    assert "not an uncertainty of this model" in yaml.safe_load((REAL / "config" / "perturbations.yaml").read_text())["usv_vpp_bias"]["citation"]
    u = factors(run)["uncertainty"]
    # round 8, M-20: the figure is computed from the prior
    assert any("sampled within +-1.4 % of the unbiased polar speed" in e["what"] and "usv_vpp_bias_brief" in e["what"] for e in u["evidence"])


# ---------------------------------------------------------------------------------------------------------- round 8 (K batch)

def ingest_check(run, **kw):
    chk = dict(name="coare_ustar_vs_umwm_ust", ok=True, value=0.9876, limit=None, note="") | kw
    edit(run / "checkpoints" / "ingest" / "ledger.json", lambda d: d["checks"].append(chk))


def test_r8_m1_data_pedigree_two_needs_the_brief_ninety_percent_ustar_agreement(run):
    d = run / "checkpoints" / "ingest" / "ledger.json"
    ingest_check(run)
    assert factors(run)["data_pedigree"]["level"] == 2                                      # q8's 0.9876
    edit(d, lambda x: x.update(checks=[c for c in x["checks"] if c["name"] != "coare_ustar_vs_umwm_ust"]))
    ingest_check(run, value=0.5)
    f = factors(run)["data_pedigree"]
    assert f["level"] == 1 and any("only 50.0 % of the sea points have COARE u* within 20 % of UMWM ust" in m and "asks 90%" in m for m in f["missing"])
    write_tao(run)
    assert factors(run)["data_pedigree"]["level"] == 1                  # a mooring comparison cannot lift a level the forcing check holds down
    edit(d, lambda x: x.update(checks=[c for c in x["checks"] if c["name"] != "coare_ustar_vs_umwm_ust"]))
    assert factors(run)["data_pedigree"]["level"] == 3                                       # no record (an older ledger): not held down


def test_r8_m1_a_failed_physical_range_check_or_an_unrecorded_fraction_holds_data_pedigree_at_one(run):
    ingest_check(run, value=None)
    assert "no fraction recorded" in " ".join(factors(run)["data_pedigree"]["missing"]) and factors(run)["data_pedigree"]["level"] == 1
    bad = [dict(name="forcing_in_physical_range", ok=False, value=1, limit=0, note="U10")]
    edit(run / "checkpoints" / "ingest" / "ledger.json", lambda d: d.update(checks=bad))
    f = factors(run)["data_pedigree"]
    assert f["level"] == 1 and "forcing_in_physical_range" in f["missing"][0]


def vrow(i, judged=True):
    r = cr._row(f"r{i}", "c", "s", 1.0, 1.0, (0.01, 0.01, 0.01), "")
    return r if judged else dict(r, validated=None, not_judged="not judged: the finest grid has not converged")


class _Facts:
    def __init__(self, rows):
        self.vv = rows

    def ev(self, what, f):
        return dict(file=f, what=what)


def test_r8_m42_validation_three_counts_four_judged_rows_beside_a_row_not_judged():
    assert cr._validation(_Facts([vrow(i) for i in range(4)] + [vrow(9, judged=False)]))[0] == 3        # D-7: `judged = list(full)` gave 2
    assert cr._validation(_Facts([vrow(i) for i in range(3)] + [vrow(9, judged=False)]))[0] == 2


def sens_many(tmp_path, ranked, tests, entries):
    """A run whose stage-1b summary has `entries` ensembles, `tests` of them with a permutation floor and the first `ranked` with a named parameter."""
    d = sens_run(tmp_path, 0)
    def put(s):
        vs = s["summary"]["links"]
        first = next(iter(vs.values()))
        for i in range(entries - len(s["summary"]["vehicles"]) - len(vs)):
            vs[f"extra{i}"] = json.loads(json.dumps(first))
        for i, e in enumerate([*s["summary"]["vehicles"].values(), *vs.values()]):
            e["sensitivity"].update(param="x" if i < ranked else None, noise_floor=0.118 if i < tests else None)
    edit(d / "stage1b" / "summary.json", put)
    return d


@pytest.mark.parametrize("ranked,tests,entries,level", [(1, 3, 7, 1), (2, 5, 7, 2), (2, 2, 10, 2), (1, 7, 7, 1), (3, 7, 7, 2)],
                         ids=["14-percent-by-luck", "2-of-5-is-2-percent", "10-entries-2-floors", "1-of-7", "3-of-7"])
def test_r8_m42_the_robustness_rule_is_the_five_percent_level_over_the_tests_that_exist(tmp_path, data, ranked, tests, entries, level):
    """D-2: `luck < 0.15` (1 of 3 is 14 %), the 10 % level (2 of 5 is 8 % by luck) and `tests = len(allv)` (2 of 10 entries is 8.6 %) each survived."""
    assert factors(sens_many(tmp_path, ranked, tests, entries))["robustness"]["evidence_level"] == level


def test_r8_m21_ranked_parameters_without_any_permutation_floor_are_not_clearly_above_chance(tmp_path, data):
    r = factors(sens_many(tmp_path, 1, 0, 7))["robustness"]
    assert r["evidence_level"] == 1 and any("without a permutation floor are not counted" in e["what"] for e in r["evidence"])


def test_r8_m10_the_note_lists_the_cause_of_a_finest_grid_that_is_not_converged(data):
    write_dtmb3(data, {"0.10": True, "0.20": True, "0.28": True, "0.41": True})
    def cases(d):
        d["speeds"]["0.20"].update(converged=False, drift=0.001, drift_parts=0.001, scatter=0.5, iters=3000)
        d["speeds"]["0.28"].update(converged=False, drift=0.001, drift_parts=0.002, scatter=0.001, iters=500)
        d["speeds"]["0.41"].pop("converged")
    edit(data / "dtmb5415" / "run_fine.json", cases)
    rows = {r["id"]: r for r in cr.vv20_rows(data)}
    a, b, c = rows["dtmb5415:Fr0.20"], rows["dtmb5415:Fr0.28"], rows["dtmb5415:Fr0.41"]
    assert "finest grid not converged (scatter 0.5 (limit 0.02))" in a["note"] and "drift 0.001 >" not in a["note"] and a["validated"] is None
    assert "(fewer than 1000 iterations)" in b["note"] and b["not_judged"].startswith("not judged")
    assert "finest grid not converged (no convergence record)" in c["note"] and c["validated"] is None and c["not_judged"]      # was judged: validated True
    assert rows["dtmb5415:Fr0.10"]["validated"] is True


def test_r8_m16_the_two_modem_defaults_are_assumed_inputs_with_the_same_numbers(data):
    ids = {i["id"]: i for i in cr.assumed_inputs(REAL)}
    for k, v in (("anchor_margin_db", "3.0"), ("valid_range_factor", "10.0")):
        assert ids[f"modems.yaml:defaults.{k}"]["value"] == v and ids[f"modems.yaml:defaults.{k}"]["why"]
    from cafe.pm.physics import comms
    assert comms.acoustic_margin(4000.0, "benthos_atm960", "MF") == pytest.approx(3.0, abs=1e-9) and comms.valid_range_m("benthos_atm960", "MF") == 40000.0


def test_r8_m20_the_usv_speed_sampling_sentence_is_computed_from_the_prior(run, data, tmp_path, monkeypatch):
    u = factors(run)["uncertainty"]
    what = next(e["what"] for e in u["evidence"] if "usv_vpp_bias_brief" in e["what"])
    assert "within +-1.4 % of the unbiased polar speed" in what and "+-1.9 % of the speed flown" in what and "sampled over 1.4 % only" not in what
    perts = yaml.safe_load((REAL / "config" / "perturbations.yaml").read_text())
    perts["usv_vpp_bias"].update(lo=-0.30, hi=-0.20)
    (tmp_path / "perts.yaml").write_text(yaml.safe_dump(perts))
    monkeypatch.setattr(cr.sampling, "PERTURBATIONS", tmp_path / "perts.yaml")
    what = next(e["what"] for e in factors(run)["uncertainty"]["evidence"] if "usv_vpp_bias_brief" in e["what"])
    assert "within +-5.0 % of the unbiased polar speed" in what and "1.4 %" not in what and "+-6.7 % of the speed flown" in what


def test_r8_m45_verification_two_says_it_does_not_run_or_read_the_tests(run):
    v = factors(run)["verification"]
    assert v["level"] == 2 and "does not run or read the tests" in v["level_text"] and "their results are not read here" in v["evidence"][1]["what"]


def test_r8_m46_the_management_text_no_longer_says_the_audit_does_not_run_ruff(run):
    m = factors(run)["ms_management"]
    assert m["level"] == 3 and "not run by the audit" not in m["level_text"] and "`make audit` runs ruff" in m["level_text"]
    assert "ruff configured (not run by the audit)" not in (REAL / "docs" / "CREDIBILITY.md").read_text()


@pytest.mark.parametrize("name", ["summary.json", "refit.json", "tao_compare.json", "env_sigmas_fitted.json"])
def test_r8_m22_a_truncated_run_json_is_a_config_error_naming_the_file(tmp_path, name):
    p = tmp_path / name
    p.write_text('{"a": 1, "b')
    with pytest.raises(cr.config.ConfigError, match=rf"{name}: not a JSON object .*run it again"):
        cr._json(p)
    p.write_text("[]")
    with pytest.raises(cr.config.ConfigError, match="it holds list"):
        cr._json(p)


def test_r8_m1_both_ingest_checks_present_and_passing_keep_level_two_and_absent_ones_are_accepted(run):
    d = run / "checkpoints" / "ingest" / "ledger.json"
    both = [dict(name="forcing_in_physical_range", ok=True, value=0, limit=0, note=""),
            dict(name="coare_ustar_vs_umwm_ust", ok=True, value=0.90, limit=None, note="")]
    edit(d, lambda x: x["checks"].extend(both))
    assert factors(run)["data_pedigree"]["level"] == 2                                       # 0.90 is the brief's floor, inclusive
    edit(d, lambda x: x["checks"].__setitem__(-1, dict(both[1], value=0.8999)))
    assert factors(run)["data_pedigree"]["level"] == 1
