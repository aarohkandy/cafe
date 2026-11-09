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
from cafe.pm.stage1 import NOT_EXERCISED
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
    from cafe.pm.stage3 import lbm
    rec, sha = data / "receipts", dict(code_sha=lbm.physics_sha())        # DECISIONS 527: the page counts a receipt as stage 3 does: the current sha
    rec.mkdir(parents=True)
    (rec / "nest_sphere_100_d8.json").write_text(json.dumps(dict(cd=1.6, d=8, shape=[7, 4, 4], **sha)))
    (rec / "nest_sphere_100_d16.json").write_text(json.dumps(dict(cd=1.2, d=16, shape=[14, 8, 8], **sha)))       # stage 3 stores one file per resolution
    (rec / "nest_sphere_100_d12.json").write_text(json.dumps(dict(cd=1.4, d=12, shape=[10, 6, 6], **sha)))
    (rec / "lbm_sphere_100.json").write_text(json.dumps(dict(cd=1.5, ref=1.087, d=12, **sha)))
    (rec / "lbm_sphere_1000.json").write_text(json.dumps(dict(cd=0.6, ref=0.47, **sha)))
    (rec / "wm_flat_plate.json").write_text(json.dumps(dict(cf=0.0035, ittc=0.0030, re=1e6, err=0.17, yfrac=0.1, **sha)))
    (rec / "wm_channel.json").write_text(json.dumps(dict(cf=0.0066, cf_dean=0.0062, err=0.06, **sha)))
    rows = {r["id"]: r for r in cr.vv20_rows(data)}
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


@pytest.mark.parametrize("name, body, want", [
    ("wm_flat_plate.json", dict(code_sha="x"), "lacks a finite number for err, cf, re, ittc, yfrac"),
    ("wm_flat_plate.json", dict(cf=None, ittc=0.003, err=0.1, re=1e6, yfrac=0.1), "lacks a finite number for cf "),
    ("wm_channel.json", dict(cf="abc", cf_dean=0.0062, err=0.06), "lacks a finite number for cf"),
    ("wm_channel.json", dict(cf=0.0066, cf_dean=True, err=0.06), "lacks a finite number for cf_dean"),
    ("wm_channel.json", dict(cf=float("nan"), cf_dean=0.0062, err=0.06), "lacks a finite number for cf "),
    ("wm_channel.json", "[1, 2]", "is unreadable (rerun it)"),
    ("wm_flat_plate.json", "{not json", "is unreadable (rerun it)"),
    ("lbm_sphere_100.json", dict(ref=1.0), "lacks a finite number for cd"),
    ("lbm_sphere_100.json", dict(cd=1.5, ref="x"), "lacks a finite number for ref"),
    ("nest_sphere_100_d8.json", dict(d=8), "lacks a finite number for cd"),
])
def test_r9_m4_a_stored_receipt_with_a_missing_or_non_numeric_field_is_a_not_run_row_not_a_crash(data, name, body, want):
    """M-4: float(d["cf"]) raised KeyError, TypeError or ValueError out of vv20_rows, and so out of the credibility page of the whole run."""
    rec = data / "receipts"
    rec.mkdir(parents=True)
    (rec / name).write_text(body if isinstance(body, str) else json.dumps(body))
    rows = {r["source"].rsplit("/", 1)[-1]: r for r in cr.vv20_rows(data)}
    r = rows[name]
    assert r["status"] == "not run" and r["S"] is None and r["note"].startswith("not run:") and want in r["note"] and name in r["note"]
    good = rec / "wm_channel.json"
    if name != "wm_channel.json":                                  # a good neighbour is still a row
        from cafe.pm.stage3 import lbm
        good.write_text(json.dumps(dict(cf=0.0066, cf_dean=0.0062, err=0.06, code_sha=lbm.physics_sha())))
        assert next(x for x in cr.vv20_rows(data) if x["id"] == "wallmodel:wm_channel")["status"] == "run"


def test_r9_m7_the_usv_sanity_row_compares_chiodi_with_the_anemometer_height_ratio_and_labels_the_fallback(run, data):
    edit(run / "stage1b" / "summary.json", lambda d: d["summary"]["vehicles"]["usv"].update(speed=dict(ratio_median=0.129, ratio_anem_median=0.135)))
    row = next(r for r in cr.build(run, REAL, data)["sanity"]["rows"] if r["id"] == "usv")
    assert row["detail"].startswith("speed over ground / mean wind at the anemometer height along the track 0.135 (median of the per-member ratios; "
                                    "0.129 on the 10 m wind) against Chiodi et al.'s 0.178 (at the anemometer height)")
    assert "double penalty" in row["detail"]
    edit(run / "stage1b" / "summary.json", lambda d: d["summary"]["vehicles"]["usv"].update(speed=dict(ratio_median=0.129)))
    row = next(r for r in cr.build(run, REAL, data)["sanity"]["rows"] if r["id"] == "usv")
    assert row["detail"].startswith("speed over ground / mean 10 m wind along the track 0.129")
    assert "part of the gap is the difference of the wind heights" in row["detail"]


def test_only_stored_rows_without_uncertainty_give_validation_level_one(run, data):
    from cafe.pm.stage3 import lbm
    rec = data / "receipts"
    rec.mkdir(parents=True)
    (rec / "lbm_sphere_100.json").write_text(json.dumps(dict(cd=1.5, ref=1.087, code_sha=lbm.physics_sha())))
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


def test_r12_m34_an_input_with_no_value_key_does_not_print_the_value_none(run, data):
    """Round 12, M-34: the two modem entries carry their figures in the `assumed` text and have no `value`; the page printed "(assumed) None"."""
    out = []
    cr._prov(dict(modems=dict(m=dict(assumed="source level 190 dB re 1 uPa at 1 m", unit="dB"), k=dict(value=None, assumed="x"),
                              n=dict(value=3.5, unit="m", source="a paper"))), "", "platforms/modems.yaml", out)
    got = {i["path"]: i["value"] for i in out}
    assert got == {"modems.m": "n/a (see why)", "modems.k": "None", "modems.n": "3.5"}          # an explicit null stays what it is
    items = cr.build(run, REAL, data)["assumed_inputs"]
    ids = {i["id"]: i for i in items}
    assert ids["modems.yaml:modems.benthos_atm960"]["value"] == "n/a (see why)" and not [i["id"] for i in items if i["value"] == "None"]
    assert "(assumed) None" not in html.unescape(cr.write(run)[0].read_text())


def test_r12_m6_the_assumed_count_is_of_the_platforms_the_mission_uses_not_of_the_catalogue(run, data):
    """Round 12, M-6: a one-UAS mission counted the sea-vehicle platforms, radios and modems it does not use, and said "verdicts depend on them"."""
    from cafe.pm import report
    mission = yaml.safe_load((run / "mission.yaml").read_text())
    mission["vehicles"] = [v for v in mission["vehicles"] if v["id"] == "uas"]
    mission["links"] = []
    (run / "mission.yaml").write_text(yaml.safe_dump(mission))
    c = cr.build(run, REAL, data)
    by_file = lambda used: {f: sum(1 for i in c["assumed_inputs"] if i["file"] == f and i["used"] is used and i["kind"] != "fitted")
                            for f in sorted({i["file"] for i in c["assumed_inputs"]})}
    used, unused = {f: n for f, n in by_file(True).items() if n}, {f: n for f, n in by_file(False).items() if n}
    assert "platforms/quad_uas.yaml" in used and "config/assumptions.yaml" in used
    platforms = {f"platforms/{s}.yaml" for s in ("saildrone_explorer", "seaglider", "slocum", "modems", "radios")}      # radios: all but rfd900x
    assert set(unused) == platforms | {"config/assumptions.yaml", "config/perturbations.yaml"}
    assert used["platforms/radios.yaml"] == 3                                  # the UAS's own radio (rfd900x), whatever the links say (round 13, M-2)
    assert len(c["assumed_inputs"]) > sum(used.values())                                   # the page still lists the whole catalogue
    a = report._assumed(c, dict(stage="credibility", ledger="l", receipt="r"))
    assert a["total"]["value"] == sum(used.values()) and a["catalogue"]["value"] == sum(used.values()) + sum(unused.values())
    assert {f: n["value"] for f, n in a["by_file"].items()} == used and {f: n["value"] for f, n in a["not_used_by_file"].items()} == unused
    page = report._assumed_html(a)
    assert "of the" in page and "in the catalogue are used by this mission" in page and "platform not used by this mission" in page
    assert "(platform not used by this mission)" in html.unescape(cr._render(c))


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
    from cafe.pm.stage3 import lbm
    (data / "receipts" / "lbm_sphere_100.json").write_text(json.dumps(dict(cd=1.5, ref=1.087, code_sha=lbm.physics_sha())))
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


def test_a_station_glider_still_has_a_checked_sanity_row_and_only_a_drift_one_is_exempt(run, data, monkeypatch):
    """Round 3 M-1: the exemption follows task.mode in the run's mission, not the vehicle id. (A mission with a changed task is no longer the demo, look-ahead
    L0 after round 12, M-5, so the edited mission below is taken for it by hand: the subject here is the exemption, not the identity.)"""
    assert next(r for r in cr.build(run, REAL, data)["sanity"]["rows"] if r["id"] == "glider_eq")["agrees"] is False
    m = (run / "mission.yaml").read_text()
    assert m.count("mode: drift") == 1
    (run / "mission.yaml").write_text(m.replace("mode: drift", "mode: station"))                         # no longer a drift glider: back to being compared
    monkeypatch.setattr(cr, "is_the_demo", lambda mission: True)
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


def test_r12_m5_a_copy_of_the_demo_with_its_name_but_another_window_or_fleet_gets_no_sanity_block(run, data):
    """Round 12, M-5: the expected outcome was keyed on the mission name, so a 24 h copy of the demo was told "glider_eq expected MARGINAL or NO-GO" and
    was shown the demo's window end. The window, box and vehicle ids must be the demo's too."""
    text = (run / "mission.yaml").read_text()
    assert cr.build(run, REAL, data)["sanity"]["mission"] == "tepex_c_demo" and cr.is_the_demo(yaml.safe_load(text))
    for old, new in (('end: "2023-03-07T12:00:00Z"', 'end: "2023-03-02T12:00:00Z"'), ("lat_max: 5.0", "lat_max: 4.0"), ("id: uas", "id: uas2")):
        assert old in text, old
        (run / "mission.yaml").write_text(text.replace(old, new, 1))
        assert not cr.is_the_demo(yaml.safe_load(text.replace(old, new, 1))), old
        assert cr.build(run, REAL, data)["sanity"] is None, old
    (run / "mission.yaml").write_text(text)
    assert cr.build(run, REAL, data)["sanity"] is not None and not cr.is_the_demo({}) and not cr.is_the_demo(dict(name="other"))


def test_r12_m5_the_usv_sentence_names_the_window_end_the_identity_forces():
    """Round 12, M-5: the USV expectation text says "the demo window ends 7 March 12Z" as a literal; it is true wherever it is shown only because
    DEMO_DIGEST holds that end (it covers the whole mission, the window with it). If one changes, so must the other."""
    end = yaml.safe_load((REAL / "missions" / "tepex_c_demo.yaml").read_text())["window"]["end"]
    assert end == "2023-03-07T12:00:00Z" and "ends 7 March 12Z" in cr.EXPECTED["tepex_c_demo"]["usv"]["text"]


def demo_mission():
    return yaml.safe_load((REAL / "missions" / "tepex_c_demo.yaml").read_text())


def test_r12_l0_m5_the_digest_is_the_shipped_demos_and_ignores_only_the_seed_the_description_and_the_order_of_keys(run, data):
    """Look-ahead L0 after round 12, M-5: the identity was the name, window, box and vehicle ids, the fields a variant is least likely to change."""
    m = demo_mission()
    assert cr.mission_digest(m) == cr.DEMO_DIGEST["tepex_c_demo"], (
        f"missions/tepex_c_demo.yaml changed: check cr.EXPECTED (BRIEF section 6) still describes it, then set DEMO_DIGEST to {cr.mission_digest(m)}")
    assert cr.is_the_demo(m) and cr.is_the_demo(dict(m, seed=5, description="another")) and cr.is_the_demo(dict(reversed(list(m.items()))))
    assert not cr.is_the_demo(dict(m, name="other")) and not cr.is_the_demo({}) and not cr.is_the_demo(dict(name=["tepex_c_demo"]))
    assert not cr.is_the_demo({"name": "tepex_c_demo", 1: "a", "b": 2})                       # keys that cannot be sorted: not the demo, and no TypeError
    (run / "mission.yaml").write_text(yaml.safe_dump(dict(m, seed=5), sort_keys=False))         # what `run --seed 5` leaves in the run directory
    assert cr.build(run, REAL, data)["sanity"]["mission"] == "tepex_c_demo"


def test_r12_l0_m5_a_copy_with_the_demos_name_window_box_and_vehicle_ids_but_anything_else_changed_gets_no_sanity_block(run, data):
    """Look-ahead L0 after round 12, M-5: the demo with the ship moved to 150 W, the USV on another platform and only the Iridium link kept had the demo's
    window, box and ids, so it was told what BRIEF section 6 expects of the demo and shown "disagrees" wherever its verdicts differed."""
    def edit_ship(m):
        m["ship"]["lon"] = -150.0

    def edit_platform(m):
        next(v for v in m["vehicles"] if v["id"] == "usv")["platform"] = "slocum"

    def edit_links(m):
        m["links"] = [lk for lk in m["links"] if lk["kind"] == "iridium"]

    def edit_task(m):
        next(v for v in m["vehicles"] if v["id"] == "glider_eq")["task"]["mode"] = "drift"

    def edit_link_field(m):
        next(lk for lk in m["links"] if lk["kind"] == "rf")["radio"] = "xbee_pro_24"

    def edit_cutoff(m):
        m["verdict"]["go"] = 0.8

    def edit_environment(m):
        m["environment"]["subgrid"]["rain_lens"] = False

    def edit_deploy(m):
        next(v for v in m["vehicles"] if v["id"] == "glider_2n")["deploy"]["lat"] = 1.0
    base = demo_mission()
    assert cr.build(run, REAL, data)["sanity"] is not None
    for edit in (edit_ship, edit_platform, edit_links, edit_task, edit_link_field, edit_cutoff, edit_environment, edit_deploy):
        m = demo_mission()
        edit(m)
        assert m != base, edit.__name__
        (run / "mission.yaml").write_text(yaml.safe_dump(m, sort_keys=False))
        assert not cr.is_the_demo(m) and cr.build(run, REAL, data)["sanity"] is None, edit.__name__


def link_used(run, data, links):
    """{item id: used} for the radios.yaml and modems.yaml inputs of the demo with only `links` kept (each a link of the demo, or a changed copy of one)."""
    m = demo_mission()
    m["links"] = links
    (run / "mission.yaml").write_text(yaml.safe_dump(m, sort_keys=False))
    c = cr.build(run, REAL, data)
    return {i["id"]: i["used"] for i in c["assumed_inputs"] if i["file"] in ("platforms/radios.yaml", "platforms/modems.yaml")}, c


def demo_link(kind, **over):
    return dict(next(lk for lk in demo_mission()["links"] if lk["kind"] == kind), **over)


def used_ids(used, prefix):
    return {k.split(":", 1)[1] for k, u in used.items() if u and k.startswith(prefix)}


UAS_RADIO = {f"radios.rfd900x.{k}" for k in ("gt_dbi", "gr_dbi", "misc_loss_db")}


def test_r12_l0_m6_an_iridium_only_mission_uses_the_sbd_inputs_and_nothing_else_of_radios_and_modems_but_its_uas_radio(run, data):
    """Look-ahead L0 after round 12, M-6: `tables` knew only rf and acoustic, so the Iridium link's own assumptions (iridium.sbd.p_success decides its verdict)
    were "platform not used by this mission" and left out of "verdicts depend on them"; and every other radio and modem sat in the count beside them."""
    from cafe.pm import report
    used, c = link_used(run, data, [demo_link("iridium")])
    sbd = {f"iridium.sbd.{k}" for k in ("p_success", "max_attempts", "fail_cost_s", "session_setup_median_s", "session_setup_sigma")}
    assert used_ids(used, "radios.yaml") == sbd | UAS_RADIO and used_ids(used, "modems.yaml") == set()      # the demo's UAS reads rfd900x (M-2)
    assert {k for k, u in used.items() if not u} >= {"radios.yaml:iridium.rudics.p_success", "radios.yaml:radios.xbee_pro_24.gt_dbi",
                                                     "modems.yaml:modems.benthos_atm960"}
    a = report._assumed(c, dict(stage="credibility", ledger="l", receipt="r"))
    n_used = sum(1 for i in c["assumed_inputs"] if i["used"] and i["kind"] != "fitted")
    assert a["total"]["value"] == n_used and a["catalogue"]["value"] > n_used
    assert a["by_file"]["platforms/radios.yaml"]["value"] == len(sbd) + 3 and a["not_used_by_file"]["platforms/radios.yaml"]["value"] > 0
    assert "platforms/modems.yaml" in a["not_used_by_file"] and "platforms/modems.yaml" not in a["by_file"]


def test_r12_l0_m6_the_demo_counts_the_radio_and_modem_it_flies_not_every_one_in_the_files(run, data):
    used, c = link_used(run, data, demo_mission()["links"])
    assert used_ids(used, "radios.yaml") == {f"radios.rfd900x.{k}" for k in ("gt_dbi", "gr_dbi", "misc_loss_db")} | \
        {f"iridium.sbd.{k}" for k in ("p_success", "max_attempts", "fail_cost_s", "session_setup_median_s", "session_setup_sigma")}
    assert used_ids(used, "modems.yaml") == {"defaults.anchor_margin_db", "defaults.valid_range_factor", "modems.benthos_atm960"}
    assert used["modems.yaml:modems.whoi_micromodem"] is False and used["radios.yaml:radios.xbee_pro_24.gt_dbi"] is False


def test_r12_l0_m6_a_modem_that_takes_its_anchor_from_another_counts_that_one_too_and_an_acoustic_link_reads_the_defaults(run, data):
    used, _ = link_used(run, data, [demo_link("acoustic", modem="whoi_micromodem_long_10k")])
    assert used_ids(used, "modems.yaml") == {"defaults.anchor_margin_db", "defaults.valid_range_factor", "modems.whoi_micromodem", "modems.benthos_atm960"}
    assert used_ids(used, "radios.yaml") == UAS_RADIO                                                  # the demo's UAS, with no rf link
    used, _ = link_used(run, data, [demo_link("acoustic", modem="Benthos_ATM960_HF")])             # any case, as the loader reads it
    assert "modems.benthos_atm960" in used_ids(used, "modems.yaml") and "modems.whoi_micromodem" not in used_ids(used, "modems.yaml")
    bad = [demo_link("acoustic", modem="no_such_modem"), demo_link("rf", radio="no_such_radio")]                     # a mission that cannot run: no crash
    used, _ = link_used(run, data, bad)
    assert used_ids(used, "radios.yaml") == UAS_RADIO and used_ids(used, "modems.yaml") == {"defaults.anchor_margin_db", "defaults.valid_range_factor"}


def test_r12_l0_m6_the_input_pedigree_counts_the_same_inputs_as_the_assumed_count(run, data):
    """The pedigree rule read `Facts.used` too, by file: with an rf link it counted all 19 radios.yaml inputs. One predicate (`Facts.item_used`) now."""
    link_used(run, data, [demo_link("iridium")])
    f = cr.Facts(run, REAL, data)
    by_file = [i for i in f.items if i["key"] in f.used and (i["assumed"] or i["sourced"])]
    by_entry = [i for i in f.items if f.item_used(i["key"], i["path"]) and (i["assumed"] or i["sourced"])]
    assert len(by_entry) < len(by_file)
    ev = next(x for x in cr.build(run, REAL, data)["factors"] if x["factor"] == "input_pedigree")["evidence"][0]["what"]
    assert ev.startswith(f"{sum(1 for i in by_entry if i['sourced'] and not i['assumed'] and not i['recalled'])} of {len(by_entry)} platform inputs sourced")


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


def test_a_link_that_was_not_exercised_is_not_short_of_n_certify(tmp_path):
    """Round 9, DECISIONS 526: a link no member needed (NOT EXERCISED, k_fail 0) has P(fail) 0 that counts nothing and no member count decides it, yet it was
    listed among the 'verdict(s) have n below n_certify' and held the Uncertainty factor at level 2. A zero-failure vehicle still counts (the test above)."""
    run = tmp_path / "run"
    run.mkdir()
    pm_run.make_run(run, M=48)
    clean = fake_root(tmp_path / "root", sourced=3)

    def one_link_not_exercised(d):
        for e in (*d["summary"]["vehicles"].values(), *d["summary"]["links"].values()):
            e["k_fail"] = 40                                                                                    # 40 of 48 failed: excluded, so not short
        lk = next(iter(d["summary"]["links"].values()))
        lk.update(k_fail=0, verdict=dict(lk["verdict"], verdict=NOT_EXERCISED))
    edit(run / "stage1b" / "summary.json", one_link_not_exercised)
    u = factors(run, clean)["uncertainty"]
    assert not any("n below n_certify" in m for m in u["missing"]) and u["evidence_level"] == 3
    edit(run / "stage1b" / "summary.json", lambda d: next(iter(d["summary"]["links"].values())).update(verdict=dict(
        next(iter(d["summary"]["links"].values()))["verdict"], verdict="GO")))                                    # the same link graded GO is short
    u = factors(run, clean)["uncertainty"]
    assert u["evidence_level"] == 2 and "1 verdict(s) have n below n_certify" in " ".join(u["missing"])


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


def test_r8_merge_the_ustar_floor_is_the_pipelines_and_there_is_no_second_copy(run, monkeypatch):
    from cafe.pm import pipeline
    d = run / "checkpoints" / "ingest" / "ledger.json"

    def record(value):
        edit(d, lambda x: x.update(checks=[c for c in x["checks"] if c["name"] != "coare_ustar_vs_umwm_ust"]))
        ingest_check(run, value=value)
        return factors(run)["data_pedigree"]
    assert not hasattr(cr, "USTAR_AGREE_MIN")
    assert record(0.89996)["level"] == 1                                                     # E's ledger no longer rounds this up to 0.9
    assert record(0.6)["level"] == 1
    monkeypatch.setattr(pipeline, "USTAR_AGREE_FRACTION", 0.5)                               # the one constant moves both sides
    assert record(0.6)["level"] == 2
    assert any("asks 50%" in m for m in record(0.4)["missing"])


def test_r9_m1_a_platform_given_as_a_path_is_counted_and_keyed_whether_it_is_in_platforms_or_not(run, data, tmp_path, monkeypatch):
    """`platform: /somewhere/saildrone_explorer.yaml`: the credibility page matched platforms by stem under platforms/, so the file was 'not used' and its
    assumed inputs were nowhere. A path into platforms/ is the platform of that name; a file elsewhere is keyed by the path as given (its stem is not its
    own: a directory of copies has a seaglider.yaml each), listed with its own assumed inputs, and has its own anchor."""
    other = tmp_path / "elsewhere"
    other.mkdir()
    (other / "saildrone_explorer.yaml").write_text((REAL / "platforms" / "saildrone_explorer.yaml").read_text())
    path = str(other / "saildrone_explorer.yaml")
    mission = yaml.safe_load((run / "mission.yaml").read_text())
    usv = next(v for v in mission["vehicles"] if v["platform"] == "saildrone_explorer")
    usv["platform"] = path
    (run / "mission.yaml").write_text(yaml.safe_dump(mission))
    c = cr.build(run, REAL, data)
    n = c["platform_assumed_counts"]["saildrone_explorer"]
    assert n > 20 and c["platform_assumed_counts"][path] == n
    assert {i["file"] for i in c["assumed_inputs"]} >= {"platforms/saildrone_explorer.yaml", path}
    ped = next(f for f in c["factors"] if f["factor"] == "input_pedigree")
    assert path in ped["evidence"][0]["file"] and "no platform file" not in " ".join(ped["missing"])
    assert f"id='{cr.plat_anchor(path)}'" in cr._render(c)
    inside = str(REAL / "platforms" / "slocum.yaml")                                       # a path into platforms/ is the platform of that stem
    assert cr.platform_key(inside) == cr.platform_key("slocum") == "slocum" and cr.platform_key(path) == path
    monkeypatch.chdir(REAL)
    assert cr.platform_key("platforms/slocum.yaml") == "slocum"


GOOD_PLATE = dict(err=0.1, cf=0.0035, re=1e6, ittc=0.003, yfrac=0.1, code_sha="x")
GOOD_CHANNEL = dict(err=0.06, cf=0.0066, cf_dean=0.0062, code_sha="x")


@pytest.mark.parametrize("name, body", [
    ("wm_flat_plate", GOOD_PLATE), ("wm_flat_plate", {k: v for k, v in GOOD_PLATE.items() if k != "yfrac"}),
    ("wm_flat_plate", dict(GOOD_PLATE, re=None)), ("wm_flat_plate", dict(GOOD_PLATE, err="x")), ("wm_flat_plate", dict(GOOD_PLATE, cf=10 ** 400)),
    ("wm_channel", GOOD_CHANNEL), ("wm_channel", {k: v for k, v in GOOD_CHANNEL.items() if k != "err"}), ("wm_channel", dict(GOOD_CHANNEL, cf_dean=10 ** 400)),
])
def test_r9_m4_the_credibility_page_and_stage_3_read_a_stored_wall_model_receipt_by_one_rule(data, name, body):
    """stage 3 refused a receipt without `yfrac` or `err` and the page drew a row from it (it checked only cf and the reference); a 400-digit integer
    was an OverflowError there. The page now asks for the fields stage 3 asks for, by the same test."""
    from cafe.pm.stage3 import lbm, wallmodel
    rec = data / "receipts"
    rec.mkdir(parents=True)
    (rec / f"{name}.json").write_text(json.dumps(dict(body, code_sha=lbm.physics_sha())))      # the current sha: the sha rule has its own test (DECISIONS 527)
    fields = wallmodel.PLATE_FIELDS if name == "wm_flat_plate" else wallmodel.CHANNEL_FIELDS
    counts = wallmodel._read_receipt(rec / f"{name}.json", fields) is not None
    assert counts == (next(r for r in cr.vv20_rows(data) if r["id"] == f"wallmodel:{name}")["status"] == "run")
    assert counts == (body in (GOOD_PLATE, GOOD_CHANNEL))


def test_r9_m15_the_ustar_finding_names_the_band_the_ingest_check_used(run, monkeypatch):
    """The ingest check judges COARE u* against UMWM ust within pipeline.USTAR_AGREE_BAND; the page spelled '20 %' by hand beside it."""
    monkeypatch.setattr(cr.pipeline, "USTAR_AGREE_BAND", 0.35)
    ingest_check(run, value=0.5)
    f = factors(run)["data_pedigree"]
    assert any("have COARE u* within 35 % of UMWM ust" in m for m in f["missing"]) and not any("within 20 %" in m for m in f["missing"])


def test_l0_the_page_refuses_a_plate_receipt_below_the_minimum_re_as_stage_3_does(data, run, monkeypatch):
    """Round 9, M-23 sibling: stage 3 refused a plate at Re_L 9.8e5 (ITTC-57 is a turbulent correlation) and the page drew a C_f-vs-ITTC row from it, which
    also lifted Validation from 0 to 1. Both read the file through config.plate_re_problem now; at the limit itself it counts."""
    from cafe.pm.stage3 import lbm, wallmodel
    rec = data / "receipts"
    rec.mkdir(parents=True)
    monkeypatch.setattr(wallmodel, "SLOW_DIR", rec)
    plate = dict(cf=0.0040, re=9.8e5, ittc=0.0041, err=0.025, yfrac=0.95, code_sha=lbm.physics_sha())
    (rec / "wm_flat_plate.json").write_text(json.dumps(plate))
    (rec / "wm_channel.json").write_text(json.dumps(dict(GOOD_CHANNEL, code_sha=lbm.physics_sha())))
    gate = wallmodel.stale_wall_receipts()
    assert gate == ["wm_flat_plate.json is at Re_L 9.8e+05, below the 1e+06 the comparison needs (rerun it)"]
    rows = {r["id"]: r for r in cr.vv20_rows(data)}
    assert rows["wallmodel:wm_flat_plate"]["status"] == "not run" and rows["wallmodel:wm_flat_plate"]["note"] == f"not run: {gate[0]}"
    assert rows["wallmodel:wm_flat_plate"]["S"] is None and rows["wallmodel:wm_channel"]["status"] == "run"
    (rec / "wm_channel.json").unlink()
    assert factors(run)["validation"]["level"] == 0                                               # the refused plate is the only comparison: none ran
    (rec / "wm_flat_plate.json").write_text(json.dumps(dict(plate, re=wallmodel.PLATE_RE_MIN)))
    assert next(r for r in cr.vv20_rows(data) if r["id"] == "wallmodel:wm_flat_plate")["status"] == "run"
    assert wallmodel.stale_wall_receipts() == ["wm_channel.json is not stored"]


@pytest.mark.parametrize("damage", ['{"grid": "coarse", "recipe": "x", "speeds": {"0.28": {"ct": 0.00', "[]", '{"recipe": "x"}'])
def test_l0_a_damaged_dtmb_run_file_is_a_not_run_row_that_names_it_not_a_traceback(run, data, damage):
    """Round 9, M-4 sibling: json.loads(...).get in dtmb5415 stopped Facts, so the report stage, `report --run` and the page, on a file `run_grid` left
    cut short."""
    write_dtmb(data)
    (data / "dtmb5415" / "run_coarse.json").write_text(damage)
    rows = [r for r in cr.vv20_rows(data) if r["id"].startswith("dtmb")]
    assert len(rows) == 4 and all(r["status"] == "not run" and "run_coarse.json is unreadable (rerun the grid)" in r["note"] for r in rows)
    assert factors(run)["validation"]["level"] == 0


@pytest.mark.parametrize("sha, want", [
    (None, "was stored without a code sha (rerun it)"), ("OLDCODE", "was stored by different code (rerun it)"), ("current", None)])
def test_r9_the_page_counts_a_stored_receipt_only_when_the_current_code_made_it_as_stage_3_does(data, run, monkeypatch, sha, want):
    """DECISIONS 527 (502 left it as the owner's call): stage 3 refuses a receipt with no `code_sha` or another code's, and the credibility page drew a row
    from it, against 464's claim that it never shows one stage 3 refuses. Every kind of stored receipt on the page (wall-model plate and channel, XLB sphere,
    native sphere grids) is now a "not run" row with the gate's phrase, one rule (`config.stored_receipt_problem`), and is no comparison that ran."""
    from cafe.pm.stage3 import lbm, wallmodel
    rec = data / "receipts"
    rec.mkdir(parents=True)
    monkeypatch.setattr(wallmodel, "SLOW_DIR", rec)
    sha = lbm.physics_sha() if sha == "current" else sha
    body = {} if sha is None else dict(code_sha=sha)
    files = {"wm_flat_plate.json": dict(cf=0.0040, re=1e6, ittc=0.0041, err=0.025, yfrac=0.95), "wm_channel.json": dict(GOOD_CHANNEL),
             "lbm_sphere_100.json": dict(cd=1.5, ref=1.087), "nest_sphere_100_d16.json": dict(cd=1.2, d=16), "nest_sphere_100_d8.json": dict(cd=1.6, d=8)}
    for name, d in files.items():
        d.pop("code_sha", None)
        (rec / name).write_text(json.dumps(dict(d, **body)))
    rows = {r["id"]: r for r in cr.vv20_rows(data)}
    ids = ("wallmodel:wm_flat_plate", "wallmodel:wm_channel", "lbm_sphere:Re100", "nest_sphere:Re100")
    if want is None:
        assert all(rows[i]["status"] == "run" for i in ids) and wallmodel.stale_wall_receipts() == []
        return
    for i, name in zip(ids, ("wm_flat_plate.json", "wm_channel.json", "lbm_sphere_100.json", "nest_sphere_100_d8.json"), strict=True):
        assert rows[i]["status"] == "not run" and rows[i]["S"] is None and rows[i]["note"] == f"not run: {name} {want}"    # the study names its first grid
    assert wallmodel.stale_wall_receipts() == [f"wm_flat_plate.json {want}", f"wm_channel.json {want}"]            # the gate's phrases, word for word
    assert [rows[i]["note"] for i in ids[:2]] == [f"not run: {p}" for p in wallmodel.stale_wall_receipts()]
    assert factors(run)["validation"]["level"] == 0                                                              # nothing ran
    from cafe import receipts as rcp
    rcp.OUT.clear()                                                                          # lbm.result_row, the sphere gate, refuses the same two
    lbm.result_row("g", "sphere", dict(cd=1.5, ref=1.087, **body), "cd", "ref", 0.10, "cmd", "eta", "src")
    tail = "STORED WITHOUT A CODE SHA (legacy or transcribed)" if sha is None else "STORED BY DIFFERENT CODE"
    assert rcp.OUT[-1]["ok"] is False and rcp.OUT[-1]["claim"].endswith(tail)
    rcp.OUT.clear()


def test_r9_one_stale_grid_of_the_native_sphere_study_refuses_its_row_as_the_gate_does(data):
    """`nest.sphere_receipts` gives a study with any grid made by other code the verdict 'stored by different code'; the page's row shows the finest grid
    but is a "not run" row too, naming the grid."""
    from cafe.pm.stage3 import lbm
    rec = data / "receipts"
    rec.mkdir(parents=True)
    now = lbm.physics_sha()
    (rec / "nest_sphere_100_d8.json").write_text(json.dumps(dict(cd=1.6, d=8, code_sha="OLDCODE")))
    (rec / "nest_sphere_100_d16.json").write_text(json.dumps(dict(cd=1.2, d=16, code_sha=now)))
    r = next(x for x in cr.vv20_rows(data) if x["id"] == "nest_sphere:Re100")
    assert r["status"] == "not run" and r["note"] == "not run: nest_sphere_100_d8.json was stored by different code (rerun it)"
    (rec / "nest_sphere_100_d8.json").write_text(json.dumps(dict(cd=1.6, d=8, code_sha=now)))
    assert next(x for x in cr.vv20_rows(data) if x["id"] == "nest_sphere:Re100")["status"] == "run"


# the gate: lbm.result_row fails an XLB run without a number for ref; nest.stored_grids counts a grid only with a positive d and a text sha
@pytest.mark.parametrize("files, status, want", [
    ({"lbm_sphere_100.json": dict(cd=1.087)}, "not run", "lbm_sphere_100.json lacks a finite number for ref"),
    ({"lbm_sphere_100.json": dict(cd=1.087, ref=1.087)}, "run", "d = ? cells"),
    ({"nest_sphere_100_d8.json": dict(cd=1.09)}, "not run", "nest_sphere_100_d8.json lacks a finite number for d"),
    ({"nest_sphere_100_d8.json": dict(cd=1.09, d=0)}, "not run", "nest_sphere_100_d8.json is no grid of the study"),
    ({"nest_sphere_100_d8.json": dict(cd=1.09, d=8, code_sha=["x"])}, "not run", "nest_sphere_100_d8.json is no grid of the study"),
    ({"nest_sphere_100_d8.json": dict(cd=1.09, d=8, ref="x")}, "run", "d = 8 cells"),                                       # the gate never reads a grid's ref
    ({"nest_sphere_100_d8.json": dict(cd=1.09, d=8), "nest_sphere_100_d16.json": dict(cd=1.01, d=8, code_sha="OLD")}, "run",   # d16 repeats d = 8:
     "left out as the gate leaves them out: nest_sphere_100_d16.json"),                                                    # so its stale sha refuses nothing
    ({"nest_sphere_100_d8_prev.json": dict(cd=1.09, d=8)}, "not run", "not run: no nest_sphere_100_d*.json under"),    # only a rerun kept beside a grid
])
def test_p27_the_page_reads_a_sphere_receipt_through_the_gates_readers_so_it_shows_what_the_gate_counts(data, monkeypatch, files, status, want):
    """P-27: the page re-derived the gate's rule for the sphere receipts and differed from it on files stage 3 leaves out or fails: an XLB run without a
    `ref` (the gate fails it; the page fell back on Morrison), a grid without a `d` or with d = 0 (the gate counts none; the page showed `d = ? cells`),
    a grid with a stray `ref` (the gate never reads it; the page refused the row) or one whose `d` repeats an earlier grid's (the gate leaves it out; the
    page let its stale sha refuse the row). A row is "run" exactly when the gate counts a result, and shows the gate's number."""
    from cafe import receipts as rcp
    from cafe.pm.stage3 import lbm, nest
    rec = data / "receipts"
    rec.mkdir(parents=True)
    monkeypatch.setattr(nest, "SLOW_DIR", rec)
    for name, body in files.items():
        (rec / name).write_text(json.dumps(dict({"code_sha": lbm.physics_sha()}, **body)))
    rows = {r["id"]: r for r in cr.vv20_rows(data)}
    if any(n.startswith("lbm") for n in files):
        rcp.OUT.clear()
        lbm.result_row("g", "x", lbm.read_stored(rec / "lbm_sphere_100.json"), "cd", "ref", 0.10, "cmd", "eta", "src")
        assert (rows["lbm_sphere:Re100"]["status"] == "run") == bool(rcp.OUT[-1]["ok"])                       # the gate passes it, or fails it, with the page
        rcp.OUT.clear()
        row = rows["lbm_sphere:Re100"]
    else:
        counted, _ = nest.stored_grids("100")
        row = rows["nest_sphere:Re100"]
        assert (row["status"] == "run") == bool(counted)
        if counted:
            assert row["S"] == counted[-1]["cd"] and row["D"] == pytest.approx(lbm.morrison(100.0))              # the finest counted grid, against Morrison
    assert row["status"] == status and want in row["note"]


# ---------------------------------------------------------------------------------------------------------------- review round 11, M-1, M-5

@pytest.mark.parametrize("key", ["speed_rmse", "dir_rmse_deg", "speed_bias", "dir_bias_deg", "sst_bias"])
def test_r11_m1_a_pooled_mooring_comparison_with_a_null_number_keeps_level_two_and_says_what_is_missing(run, key):
    """The pipeline writes a non-finite float as null (no direction pair at 1 m/s or more, no SST pair); `float(None)` ended a finished run in a traceback."""
    write_tao(run)
    p = run / "ingest" / "tao_compare.json"
    d = json.loads(p.read_text())
    d["ALL"][key] = None
    p.write_text(json.dumps(d))
    f = factors(run)["data_pedigree"]
    ev = " ".join(x["what"] for x in f["evidence"])
    if key in ("speed_rmse", "dir_rmse_deg"):
        assert f["level"] == 2 and "no usable wind" in " ".join(f["missing"]) and "stays at 2" in " ".join(f["missing"])
    else:
        assert f["level"] == 3                                                  # a bias that is not there does not hold the error comparison down
    assert "none" in ev and "nan" not in ev


@pytest.mark.parametrize("k, n", [(3, 0), (65, 64), (-1, 64), (1.5, 64), (True, 64), (None, 64), (3, None)])
def test_r11_m5_a_stored_ensemble_whose_counts_are_not_counts_is_a_config_error(run, k, n):
    p = run / "stage1b" / "summary.json"
    d = json.loads(p.read_text())
    d["summary"]["vehicles"]["usv"].update(k_fail=k, n=n)
    p.write_text(json.dumps(d))
    with pytest.raises(cr.config.ConfigError, match="not a count.*run it again"):
        cr.build(run, REAL)


def test_r11_m6_a_calm_sea_holds_data_pedigree_at_one_by_an_explicit_rule_and_a_mooring_comparison_cannot_lift_it(run):
    """The ingest passes a zero-wind window with no u* fraction (value None); row 393 said a ledger without the check is not held down, which is not this."""
    ingest_check(run, value=None, note="all 40 sampled sea points have UMWM ust at or below 0.001 m/s (a calm): the u* agreement is not assessable")
    write_tao(run)
    f = factors(run)["data_pedigree"]
    assert f["level"] == 1 and any("was not assessable (all 40 sampled sea points have UMWM ust at or below 0.001 m/s (a calm)" in m for m in f["missing"])


# ---- review round 13: M-2 (the UAS lost-link radio), M-3 (config/ items are not all used by every mission)

def only(run, keep, links=()):
    """The demo's run with only the vehicles `keep` and the links `links` in its mission.yaml; -> the built report."""
    m = demo_mission()
    m["vehicles"] = [v for v in m["vehicles"] if v["id"] in keep]
    m["links"] = list(links)
    (run / "mission.yaml").write_text(yaml.safe_dump(m, sort_keys=False))
    return cr.build(run, REAL, run.parent / "data")


def used_of(c, file):
    return {i["id"].split(":", 1)[1] for i in c["assumed_inputs"] if i["file"] == file and i["used"]}


def test_r13_m2_a_uas_mission_with_no_rf_link_still_counts_the_radio_its_lost_link_hook_reads(run, data):
    """`stage1._uas_radio` reads radios.yaml `rfd900x` (gt_dbi, gr_dbi, misc_loss_db, all assumed) for every UAS sortie; the rule looked only at the links."""
    assert used_of(only(run, {"uas"}), "platforms/radios.yaml") == UAS_RADIO
    assert used_of(only(run, {"glider_eq"}), "platforms/radios.yaml") == set()                       # no UAS, no link: no radio
    xbee = {f"radios.xbee_pro_24.{k}" for k in ("gt_dbi", "gr_dbi", "misc_loss_db")}
    got = used_of(only(run, {"uas"}, [demo_link("rf", radio="xbee_pro_24")]), "platforms/radios.yaml")
    assert got == UAS_RADIO | xbee                                                                   # the link's radio and the hook's, both
    f = cr.Facts(run, REAL, data)
    assert ("radios", "rfd900x") in f.read and "radios" in f.used
    ev = next(x for x in only(run, {"uas"})["factors"] if x["factor"] == "input_pedigree")["evidence"][0]["what"]
    assert "platform inputs sourced" in ev


def test_r13_m2_the_lost_link_hook_and_the_report_choose_the_radio_in_one_place():
    from cafe.pm import stage1
    from cafe.pm.physics import comms
    from cafe.pm.physics import uas
    P = uas.load_platform("quad_uas")
    assert comms.uas_radio_names(P) == ("rfd900x", "rfd900x") and comms.uas_radio_names(cr.config.load_platform("quad_uas")) == ("rfd900x", "rfd900x")
    r = stage1._uas_radio(P)
    base = comms._yaml("radios.yaml")["radios"]["rfd900x"]
    assert (r["gt_dbi"], r["gr_dbi"], r["misc_loss_db"], r["cable_loss_db"]) == (base["gt_dbi"], base["gr_dbi"], base["misc_loss_db"], base["cable_loss_db"])
    xb = dict(radio=dict(P["radio"], mine=dict(tx_power_dbm=20.0)))
    assert comms.uas_radio_names(xb) == ("rfd900x", "rfd900x")                                       # the first block with a transmit power wins
    first = dict(radio=dict(xbee_pro_24=dict(tx_power_dbm=18.0), rfd900x=dict(tx_power_dbm=27.0)))
    assert comms.uas_radio_names(first) == ("xbee_pro_24", "xbee_pro_24")
    assert comms.uas_radio_names(dict(radio=dict(other=dict(tx_power_dbm=1.0)))) == ("other", "rfd900x")      # no entry of that name: radios.yaml's rfd900x
    assert comms.uas_radio_names(dict(radio=dict(pa=dict(note="no power")))) == ("rfd900x", "rfd900x")
    assert comms.uas_radio_names({}) == ("rfd900x", "rfd900x")                                       # no radio block: no StopIteration


def test_r13_m3_a_one_uas_mission_counts_no_other_class_stage_3_key_and_no_dtmb_key_as_used(run, data):
    c = only(run, {"uas"})
    cfg = used_of(c, "config/assumptions.yaml")
    assert "stage3.uas.arm_length_m" in cfg and "stage3.nominal.uas" in cfg and "stage3.window_s" in cfg and "subgrid.diurnal_jet.dT_ref_K" in cfg
    assert cfg.isdisjoint({"stage3.slocum.length_m", "stage3.glider.hull_diameter_m", "stage3.usv.hull_draft_m", "stage3.nominal.glider",
                           "stage3.nominal.usv_hull", "stage3.nominal.usv_wing", "dtmb5415.u_D_rel", "dtmb5415.u_S_rel", "dtmb5415.u_nu_rel"})
    pert = used_of(c, "config/perturbations.yaml")
    assert "bulk_stress_scale" in pert and "wind_speed_bias" in pert and pert.isdisjoint({"glider_speed_scale", "usv_vpp_bias", "usv_vpp_bias_brief"})
    unused = {i["id"]: cr.not_used_note(i) for i in c["assumed_inputs"] if not i["used"] and i["file"].startswith("config/")}
    assert unused["assumptions.yaml:dtmb5415.u_D_rel"] == "read only by the DTMB validation study, not by a verdict"
    assert unused["assumptions.yaml:stage3.slocum.length_m"] == "vehicle class not flown by this mission"
    assert "(vehicle class not flown by this mission)" in html.unescape(cr._render(c))
    assert cr.not_used_note(dict(id="quad_uas.yaml:radio.x", file="platforms/quad_uas.yaml")) == "platform not used by this mission"


def test_r13_m3_a_slocum_key_is_used_only_by_a_slocum_and_a_glider_key_by_any_glider(run, data):
    slocum = next(v["id"] for v in demo_mission()["vehicles"] if v["platform"] == "slocum")
    seaglider = next(v["id"] for v in demo_mission()["vehicles"] if v["platform"] == "seaglider")
    with_slocum, with_sea = used_of(only(run, {slocum}), "config/assumptions.yaml"), used_of(only(run, {seaglider}), "config/assumptions.yaml")
    assert "stage3.slocum.length_m" in with_slocum and "stage3.slocum.length_m" not in with_sea
    assert {"stage3.glider.wing_x_frac", "stage3.nominal.glider"} <= with_slocum & with_sea              # both are gliders


def test_r13_m3_the_demo_flies_every_class_so_only_the_three_dtmb_keys_are_not_used(run, data):
    c = cr.build(run, REAL, data)
    unused = {i["id"] for i in c["assumed_inputs"] if not i["used"] and i["file"].startswith("config/")}
    assert unused == {"assumptions.yaml:dtmb5415.u_D_rel", "assumptions.yaml:dtmb5415.u_S_rel", "assumptions.yaml:dtmb5415.u_nu_rel"}


def test_r13_m3_every_stage_3_key_of_assumptions_yaml_maps_to_a_class_or_to_every_mission():
    """A key added for one class must be given its class here, or it counts as used by missions that never fly that class."""
    keys = [k for k in cr.config.assumptions() if k.startswith("stage3.")]
    every = {"window_s", "box_bodies", "cells_per_delta", "min_cells_across", "min_flow_throughs", "spinup", "min_window_s",
             "refit.between_window_frac", "refit.discretisation_frac", "chunk_steps", "compile_s_guess", "les_margin",
             "min_cells_thin_part", "nu_lat_floor", "skip_factor"}
    per_class = {k for k in keys if cr.config_scope("config/assumptions.yaml", k)}
    assert {k.removeprefix("stage3.") for k in keys if k not in per_class} == every
    assert {cr.config_scope("config/assumptions.yaml", k) for k in per_class} == {"glider", "seaglider", "slocum", "usv", "uas"}
    assert len(per_class) == 28 and cr.config_scope("config/assumptions.yaml", "stage3.nominal.usv_wing") == "usv"
    assert cr.config_scope("config/assumptions.yaml", "dtmb5415.u_nu_rel") == "-" and cr.config_scope("config/assumptions.yaml", "waves.swell_age") == ""
    assert cr.config_scope("config/perturbations.yaml", "bulk_stress_scale") == "uas" and cr.config_scope("config/perturbations.yaml", "tp_bias") == ""


def test_r13_a_config_keys_of_one_class_outside_the_stage_3_class_prefix_are_scoped_to_it(run, data):
    """The adversary of batch A: `reach.speed_ms.<class>`, the FEA keys (glider only: `budget.FEA_CLASSES`) and `stage3.fs.*` (the USV's free-surface
    case) are read per class and counted as used by every mission; the reach map has no UAS, and the Seaglider alone reads three `stage3.glider.*`."""
    scope = lambda k: cr.config_scope("assumptions.yaml", k)
    assert (scope("reach.speed_ms.glider"), scope("reach.speed_ms.usv"), scope("reach.horizon_h"), scope("reach.fluid_allowance_ms")) == \
        ("glider", "usv", "glider|usv", "glider|usv")
    assert {scope(f"stage3.{k}") for k in ("fea_min_s", "fea_elements_along", "fea_reserve_frac")} == {"glider"}
    assert {scope(f"stage3.fs.{k}") for k in ("margin", "cost_factor", "mesh_s_per_cell", "snappy_cell_factor")} == {"usv"}
    assert {scope(f"stage3.glider.{k}") for k in ("hull_diameter_m", "wing_span_m", "wing_chord_m")} == {"seaglider"}
    assert scope("stage3.glider.wing_x_frac") == "glider" and scope("stage3.slocum.length_m") == "slocum"
    uas, sea, slo = (used_of(only(run, {v}), "config/assumptions.yaml") for v in ("uas", "glider_eq", "glider_2n"))
    assert used_of(only(run, {"usv"}), "config/assumptions.yaml") >= {"reach.speed_ms.usv", "stage3.fs.margin", "reach.horizon_h"}
    assert uas.isdisjoint({"reach.speed_ms.usv", "reach.speed_ms.glider", "reach.horizon_h", "reach.fluid_allowance_ms", "stage3.fea_min_s",
                           "stage3.fea_elements_along", "stage3.fea_reserve_frac", "stage3.fs.margin", "stage3.fs.cost_factor"})
    assert {"reach.speed_ms.glider", "stage3.fea_min_s", "stage3.glider.wing_span_m", "reach.horizon_h"} <= sea
    assert sea.isdisjoint({"reach.speed_ms.usv", "stage3.fs.margin"}) and "stage3.glider.wing_span_m" not in slo and "stage3.slocum.length_m" in slo


def test_r13_a_a_glider_of_another_kind_than_seaglider_reads_the_slocum_geometry_keys(run, data, tmp_path):
    """`pipeline_windows.glider_vehicle` takes the Seaglider branch for `kind: seaglider` and the `stage3.slocum.*` branch for every other glider."""
    other = tmp_path / "spray.yaml"
    other.write_text((REAL / "platforms" / "slocum.yaml").read_text().replace("kind: slocum", "kind: spray_glider", 1))
    assert "kind: spray_glider" in other.read_text()
    m = demo_mission()
    m["vehicles"] = [dict(next(v for v in m["vehicles"] if v["id"] == "glider_2n"), platform=str(other))]
    assert cr.flown_classes(m) == {"glider", "slocum"}
    assert cr.flown_classes(demo_mission()) == {"glider", "seaglider", "slocum", "usv", "uas"}
    m["links"] = []
    (run / "mission.yaml").write_text(yaml.safe_dump(m, sort_keys=False))
    cfg = used_of(cr.build(run, REAL, data), "config/assumptions.yaml")
    assert "stage3.slocum.length_m" in cfg and "stage3.glider.wing_span_m" not in cfg


def test_r13_m3_a_mission_whose_vehicles_cannot_be_read_counts_every_class_but_never_the_dtmb_keys(run, data):
    m = demo_mission()
    m["vehicles"][0]["platform"] = "no_such_platform"
    (run / "mission.yaml").write_text(yaml.safe_dump(m, sort_keys=False))
    f = cr.Facts(run, REAL, data)
    used = lambda key: f.config_used("config/assumptions.yaml", key)
    assert f.flown is None and used("stage3.slocum.length_m") and not used("dtmb5415.u_D_rel")
    (run / "mission.yaml").unlink()
    assert cr.Facts(run, REAL, data).flown is None


def test_r13_sweep_a_cut_write_leaves_the_old_credibility_json(tmp_path, monkeypatch, cut_writes):
    """Round 13, M-17 sibling: report/credibility.json is read back by the report, `receipts` and the audit; written in place, a cut left three characters."""
    monkeypatch.setattr(cr, "build", lambda run: {"a": 1})
    monkeypatch.setattr(cr, "_render", lambda c: "<p>x</p>")
    cr.write(tmp_path)
    f = tmp_path / "report" / "credibility.json"
    before = f.read_bytes()
    assert json.loads(before) == {"a": 1}
    monkeypatch.setattr(cr, "build", lambda run: {"a": 2})
    cut_writes()
    with pytest.raises(OSError, match="killed"):
        cr.write(tmp_path)
    assert f.read_bytes() == before and not list(f.parent.glob("*.tmp"))
