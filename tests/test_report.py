"""The report stage: traceability of every number, the verdict statements, the degraded paths, and that a broken report is caught."""
import copy
import datetime as dt
import json
import re

import numpy as np
import pytest
import yaml

from cafe.pm import budget, config, report, stage1
from cafe.pm.env.protocol import AnalyticEnv
from cafe.pm.stats import intervals
from tests.fixtures import pm_run


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    """No stored receipts: the credibility page reads CAFE_DATA, which must not be the real /data."""
    monkeypatch.setenv("CAFE_DATA", str(tmp_path / "data"))


@pytest.fixture
def run(tmp_path):
    d = tmp_path / "run"
    d.mkdir()
    return d


def load(run):
    return json.loads((run / "report" / "report.json").read_text())


def walk(o, path=""):
    """Independent of report._walk: yield (path, node) for number nodes, fail on a number outside one."""
    if isinstance(o, dict) and ("values" in o or isinstance(o.get("value", ""), (int, float, type(None)))):
        yield path, o
    elif isinstance(o, dict):
        for k, v in o.items():
            yield from walk(v, f"{path}.{k}")
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from walk(v, f"{path}[{i}]")
    else:
        assert isinstance(o, (str, bool, type(None))), f"{path}: bare number {o!r}"


@pytest.fixture
def full(run):
    m, plan = pm_run.make_run(run, thr={"stage1": {"glider": {"s_per_batch_day": 5.0, "s_per_member_day": 0.01, "measured": "2026-10-28", "host": "h"}}})
    paths = report.write(run, m, plan)
    return run, m, plan, paths, load(run)


def test_files_and_traceability(full):
    run, m, plan, paths, rep = full
    assert [p.name for p in paths] == ["index.html", "report.json", "credibility.html", "credibility.json"]
    assert all(p.is_file() and p.parent == run / "report" for p in paths)
    assert report.check_traceability(rep) == [] and rep["traceability_problems"] == []
    rows = {r["id"]: r for r in rep["receipts"]}
    nodes = list(walk(rep))
    assert len(nodes) > 150
    for path, n in nodes:
        for k in ("unit", "stage", "source", "uncertainty", "receipt", "ledger"):
            assert k in n, (path, k)
        assert n["stage"] and n["source"] and n["receipt"] in rows, path
        r = rows[n["receipt"]]
        assert r["ok"] and r["ledger"] == n["ledger"], path
        if r["stage"] != "report":
            assert (run / n["ledger"]).is_file(), path


def test_receipts_are_real_ledger_entries(full):
    run, _, _, _, rep = full
    kinds = set()
    for r in rep["receipts"]:
        kinds.add(r["kind"])
        if r["stage"] == "report":
            continue
        led = json.loads((run / r["ledger"]).read_text())
        if r["kind"] == "check":
            assert r["name"] in [c["name"] for c in led["checks"]]
        elif r["kind"] == "output":
            assert r["sha256"] in [o["sha256"] for o in led["outputs"]]
        else:
            assert r["sha256"] == led["config_hash"]
    assert kinds == {"check", "output", "config"}


def test_verdicts_match_the_ensemble(full):
    run, _, _, _, rep = full
    top = json.loads((run / "stage1b" / "summary.json").read_text())
    for vid, e in top["summary"]["vehicles"].items():
        v, d = e["verdict"], rep["vehicles"][vid]
        assert d["verdict"] == v["verdict"] == intervals.verdict(e["k_fail"], e["n"])["verdict"]
        assert d["p_fail"]["value"] == pytest.approx(e["k_fail"] / e["n"])
        assert (d["p_fail"]["uncertainty"]["lo"], d["p_fail"]["uncertainty"]["hi"]) == pytest.approx((v["fail_lo"], v["fail_hi"]))
        assert d["p_fail"]["uncertainty"]["kind"] == f"{v['method']} interval"
        assert (d["n"]["value"], d["k_fail"]["value"]) == (e["n"], e["k_fail"])
        assert d["dominant_mode"] == e["dominant"]
        for t, key in ((d["first_fail"], "first_fail_t"), (d["median_fail"], "median_fail_t")):
            assert (t is None) == (e[key] is None)
            if t:
                assert t["utc"] == dt.datetime.fromtimestamp(e[key], dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
        assert d["sensitivity"]["param"] == e["sensitivity"]["param"]
    uas = rep["vehicles"]["uas"]
    assert uas["verdict"] == "NO-GO" and uas["dominant_mode"] == "gust_front" and uas["first_fail"]["utc"].endswith("Z")
    assert rep["vehicles"]["glider_2n"]["verdict"] == "GO" and rep["vehicles"]["glider_2n"]["first_fail"] is None
    assert rep["vehicles"]["usv"]["sensitivity"]["param"] is not None and rep["vehicles"]["usv"]["sensitivity"]["s1"]["value"] > 0


def test_not_certifiable_below_n_certify(full):
    rep = full[4]
    for d in [*rep["vehicles"].values(), *rep["links"].values()]:
        assert d["n"]["value"] == 48 < d["n_certify"]["value"] == 73
        assert "cannot be certified at n = 48" in d["certify_statement"] and "73 members" in d["certify_statement"]
    assert "3/n" in rep["vehicles"]["glider_2n"]["note"]


def test_certifiable_at_large_n(run):
    m, plan = pm_run.make_run(run, M=80)
    report.write(run, m, plan)
    rep = load(run)
    assert all(d["certify_statement"] is None for d in rep["vehicles"].values())
    assert "cannot be certified" not in (run / "report" / "index.html").read_text()


def test_links(full):
    rep = full[4]
    assert set(rep["links"]) == {"usv-uas-rf", "glider_eq-ship-acoustic", "usv-shore-iridium"}
    assert rep["links"]["usv-shore-iridium"]["margin_db_median"] is None
    assert rep["links"]["glider_eq-ship-acoustic"]["margin_db_median"]["unit"] == "dB"
    assert rep["links"]["usv-uas-rf"]["method"].startswith("two-ray")


def test_refit_changed_the_verdict(full):
    rep = full[4]
    g = rep["vehicles"]["glider_eq"]
    assert g["verdict_stage1"] != g["verdict"] and g["changed_by_refit"]
    assert not rep["vehicles"]["uas"]["changed_by_refit"]
    assert "after the stage-3 refit" in (full[0] / "report" / "index.html").read_text()


def test_map(full):
    run, _, _, _, rep = full
    mp = rep["map"]
    assert mp["available"] and mp["box"]["values"] == [165.0, -165.0, -5.0, 5.0]
    assert mp["ship"]["values"] == [-165.0, 0.0] and mp["vehicles"]["uas"]["deploy"] is None
    g = mp["vehicles"]["usv"]
    assert 1 <= len(g["median"]["values"]) <= 120 and all(-180 <= p[0] < 180 and -90 <= p[1] <= 90 for p in g["median"]["values"])
    assert g["median"]["uncertainty"]["kind"] == "ensemble spread"
    assert any(x["failed"] and x["label"].endswith("(failed)") for x in g["members"]) and any(not x["failed"] for x in g["members"])
    assert [w["label"] for w in mp["windows"]["glider_eq"]] == ["W1", "W2"]
    h = (run / "report" / "index.html").read_text()
    assert h.count("<svg") == 1 and h.count("<polyline") >= 4 * 3 and "memfail" in h and "stage-3 window W1" in h


def test_environment_without_env(full):
    env = full[4]["environment"]
    assert env["available"] is False and "not given an Environment" in env["how"]
    q = {v: d["quantity"] for v, d in env["forcing_at_windows"].items()}
    assert q["glider_eq"] == "surface current speed" and q["usv"] == "significant wave height" and q["uas"] == "10 m wind speed"
    w = env["forcing_at_windows"]["glider_eq"]["windows"][0]["forcing"]
    assert w["value"] == 8.0 and w["unit"] == "m/s" and w["basis"] == "failed members"


def test_environment_queried_with_env(run):
    m, plan = pm_run.make_run(run)
    report.write(run, m, plan, env=AnalyticEnv(wind=(3.0, 4.0), hs=2.5, current=(0.3, 0.4)))
    env = load(run)["environment"]
    assert env["available"] and "AnalyticEnv" in env["how"]
    for d in env["vehicles"].values():
        assert np.allclose(d["wind10"]["values"], 5.0) and np.allclose(d["hs"]["values"], 2.5) and np.allclose(d["current"]["values"], 0.5)
        assert d["wind10"]["source"].startswith("analytic") and d["wind10"]["uncertainty"] == 0.0 and len(d["t"]["values"]) <= 24
    assert report.check_traceability(load(run)) == []


def test_stage3_and_refit(full):
    run, _, _, _, rep = full
    s = rep["stage3"]
    assert s["available"] and s["cpu_fallback"] and s["label"].startswith("CPU fallback")
    h = (run / "report" / "index.html").read_text()
    assert f'<div class=warn><p class=big>{s["label"][:30]}' in h
    ge = s["vehicles"]["glider_eq"]
    assert [w["used_in_refit"] for w in ge] == [True, True] and ge[0]["not_used_because"] is None
    assert s["refit"]["glider_eq"]["used"] and s["refit"]["glider_eq"]["drag"]["mean"]["value"] > 1.0
    uas = s["vehicles"]["uas"]
    assert [w["ok"] for w in uas] == [True, False]
    assert uas[1]["not_used_because"] == "failed self-checks: mach_max"
    assert "no window passed" in uas[0]["not_used_because"] and s["refit"]["uas"]["failed_checks"] == ["mach_max"]
    assert s["vehicles"]["glider_2n"][0]["not_used_because"] == "budget ci: no refit"
    assert s["vehicles"]["usv"][0]["not_used_because"] == "no refit entry for this vehicle" and "usv" not in s["refit"]
    inf = next(c for c in ge[0]["checks"] if c["name"] == "nest_shift_count")
    assert inf["limit"]["value"] is None and inf["note"] == "whole-cell shifts"
    assert ge[0]["t"]["utc"].endswith("Z") and ge[0]["coefficients"]["cd"]["value"] == 1.05


def test_gpu_plan_has_no_fallback_banner(run):
    m, _ = pm_run.make_run(run)
    plan = budget.plan("quick", 1, m, thr={}, vehicle_classes=stage1._classes(m))
    report.write(run, m, plan)
    rep, h = load(run), (run / "report" / "index.html").read_text()
    assert not rep["stage3"]["cpu_fallback"] and rep["stage3"]["label"] == "GPU LES windows"
    assert "<div class=warn><p class=big>" not in h and "<p class=big>GPU LES windows</p>" in h


def test_stage3_files_missing(run):
    m, plan = pm_run.make_run(run, stage3=False, refit=False, emulator=False)
    report.write(run, m, plan)
    rep = load(run)
    assert rep["stage3"]["available"] is False and "stage3/windows.json is not in the run directory" in rep["stage3"]["reason"]
    assert rep["emulator"] == {"available": False, "reason": "emulator/holdout.json is not in the run directory", "vehicles": {}}
    h = (run / "report" / "index.html").read_text()
    assert "stage3/windows.json is not in the run directory" in h and "emulator/holdout.json is not in the run directory" in h


def test_windows_without_refit_file(run):
    m, plan = pm_run.make_run(run, refit=False)
    report.write(run, m, plan)
    w = load(run)["stage3"]["vehicles"]["glider_eq"][0]
    assert w["not_used_because"] == "refit/refit.json is not in the run directory" and not w["used_in_refit"]


def test_emulator(full):
    em = full[4]["emulator"]
    assert em["available"]
    g = em["vehicles"]["glider_eq"]
    assert g["trained"] and g["rmse"]["p_fail"]["value"] == 0.04 and g["coverage"]["p_fail"]["value"] == 0.9 and g["nominal"]["value"] == 0.9
    assert g["n_train"]["value"] == 38 and g["n_test"]["value"] == 10
    assert em["vehicles"]["usv"] == {"trained": False, "reason": "48 members, 0 failures: nothing to learn"}
    assert "not trained. 48 members, 0 failures" in (full[0] / "report" / "index.html").read_text()


def test_machine_and_budget(full):
    run, m, plan, _, rep = full
    mb = rep["machine"]
    assert mb["describe"] == budget.describe(plan)
    assert mb["member_costs"]["glider_eq"]["measured"] and mb["member_costs"]["glider_eq"]["source"].startswith("measured")
    assert not mb["member_costs"]["usv"]["measured"] and mb["member_costs"]["usv"]["source"].startswith("NOT MEASURED")
    assert "NOT MEASURED" in (run / "report" / "index.html").read_text()
    assert set(mb["wall_s"]) == set(report.STAGES[:-1]) and all(n["unit"] == "s" for n in mb["wall_s"].values())
    assert mb["git_sha"] == ["abc1234"] and mb["versions"]["python"] and mb["machine"]["cpus"]["unit"] == "cores"
    assert mb["plan"]["n_max"]["value"] == plan["n_max"] and mb["plan"]["budget_s"]["unit"] == "s"


def test_assumed_inputs_are_all_listed_and_linked(full):
    run, _, _, _, rep = full
    cred = json.loads((run / "report" / "credibility.json").read_text())
    ids = {i["id"] for i in cred["assumed_inputs"]}
    for k in yaml.safe_load((config.CONFIG / "assumptions.yaml").read_text()):
        assert f"assumptions.yaml:{k}" in ids
    a = rep["assumed_inputs"]
    assert {i["id"] for i in a["items"]} == ids and a["total"]["value"] == len(ids) and sum(n["value"] for n in a["by_file"].values()) == len(ids)
    ch = (run / "report" / "credibility.html").read_text()
    for i in a["items"]:
        assert f"id='{i['href'].split('#')[1]}'" in ch
    d = rep["vehicles"]["usv"]
    assert d["assumed_platform_inputs"]["value"] > 20 and d["assumed_anchor"] == "credibility.html#plat-saildrone_explorer"
    assert "id='plat-saildrone_explorer'" in ch
    assert [f["name"] for f in a["factors"]][0] == "Data pedigree" and len(a["factors"]) == 9


def test_html_is_static_and_agrees_with_the_json(full):
    run, _, _, _, rep = full
    h = (run / "report" / "index.html").read_text()
    assert report.check_rendered(rep, h) == []
    assert 'name="viewport"' in h and "prefers-color-scheme:dark" in h and "var(--bg)" in h
    assert not re.search(r"<script|<link|@import|(src|href)=[\"']?https?:", h)
    assert str(run) not in (run / "report" / "report.json").read_text()
    for d in rep["vehicles"].values():
        assert f"<span class=\"badge {d['verdict'].lower().replace('-', '')}\">{d['verdict']}</span>" in h
    for n in (rep["vehicles"]["uas"]["p_fail"], rep["vehicles"]["usv"]["n"]):
        assert f'href="#{report._rid(n["receipt"])}"' in h and f"id='{report._rid(n['receipt'])}'" in h
        assert f'href="../{n["ledger"]}"' in h
    broken = h.replace(report._txt(rep["vehicles"]["uas"]["p_fail"]), "0")
    assert any("vehicles.uas.p_fail" in p for p in report.check_rendered(rep, broken))


def test_same_inputs_same_report(full):
    run, m, plan, _, _ = full
    a = (run / "report" / "report.json").read_bytes()
    report.write(run, m, plan)
    assert (run / "report" / "report.json").read_bytes() == a


# ---------------------------------------------------------------------------------------------------------- broken on purpose

def test_traceability_catches_a_missing_receipt(full):
    rep = copy.deepcopy(full[4])
    del rep["vehicles"]["usv"]["p_fail"]["receipt"]
    bad = report.check_traceability(rep)
    assert len(bad) == 1 and bad[0].startswith("vehicles.usv.p_fail: missing ['receipt']")


@pytest.mark.parametrize("key", ["stage", "source", "ledger", "unit", "uncertainty"])
def test_traceability_catches_each_missing_field(full, key):
    rep = copy.deepcopy(full[4])
    del rep["links"]["usv-uas-rf"]["frac_p10"][key]
    assert any(p.startswith("links.usv-uas-rf.frac_p10: missing") and key in p for p in report.check_traceability(rep))


def test_traceability_catches_an_empty_source(full):
    rep = copy.deepcopy(full[4])
    rep["vehicles"]["uas"]["n"]["source"] = ""
    assert report.check_traceability(rep) == ["vehicles.uas.n: missing ['source']"]


def test_traceability_catches_a_bare_number(full):
    rep = copy.deepcopy(full[4])
    rep["vehicles"]["uas"]["p_fail_rounded"] = 0.7
    rep["stage3"]["extra"] = [1, 2.5]
    bad = report.check_traceability(rep)
    assert "vehicles.uas.p_fail_rounded: the number 0.7 is outside a traced value node" in bad
    assert "stage3.extra[0]: the number 1 is outside a traced value node" in bad and len(bad) == 3


def test_traceability_ignores_booleans(full):
    rep = copy.deepcopy(full[4])
    rep["vehicles"]["uas"]["flag"] = True
    assert report.check_traceability(rep) == []


def test_traceability_catches_an_unknown_receipt_and_a_wrong_ledger(full):
    rep = copy.deepcopy(full[4])
    rep["vehicles"]["uas"]["n"]["receipt"] = "stage1b:check:does_not_exist"
    rep["vehicles"]["usv"]["n"]["ledger"] = "checkpoints/stage1/ledger.json"
    bad = report.check_traceability(rep)
    assert "vehicles.uas.n: receipt 'stage1b:check:does_not_exist' is not a row of the receipts table" in bad
    assert any(p.startswith("vehicles.usv.n: ledger 'checkpoints/stage1/ledger.json' is not the ledger of receipt") for p in bad)


def test_traceability_catches_a_failed_check(full):
    rep = copy.deepcopy(full[4])
    rid = rep["vehicles"]["uas"]["n"]["receipt"]
    next(r for r in rep["receipts"] if r["id"] == rid)["ok"] = False
    assert any("vehicles.uas.n: receipt" in p and "missing or its check failed" in p for p in report.check_traceability(rep))


def test_a_run_without_ledgers_is_flagged_not_hidden(run):
    m, plan = pm_run.make_run(run, ledgers=False)
    report.write(run, m, plan)
    rep, h = load(run), (run / "report" / "index.html").read_text()
    assert rep["traceability_problems"] and all("missing or its check failed" in p for p in rep["traceability_problems"])
    assert "Traceability problems" in h and "MISSING OR FAILED" in h
    assert rep["map"] == {"available": False, "reason": "stage1b/res.pkl does not match the sha-256 in the stage1b ledger, so it was not loaded"}
    assert rep["machine"]["machine"] is None and rep["machine"]["git_sha"] == [] and "unknown" in h


def test_a_changed_failure_in_a_ledger_is_flagged(full):
    run, m, plan, _, _ = full
    p = run / "checkpoints" / "stage1b" / "ledger.json"
    d = json.loads(p.read_text())
    d["checks"][0]["ok"] = False
    p.write_text(json.dumps(d))
    report.write(run, m, plan)
    rep = load(run)
    assert rep["traceability_problems"] and all("lhs_stratified_batch1" in p for p in rep["traceability_problems"])


# ---------------------------------------------------------------------------------------------------------- degraded inputs

def test_res_pkl_not_loaded_when_its_hash_differs(full):
    run, m, plan, _, _ = full
    with open(run / "stage1b" / "res.pkl", "ab") as f:
        f.write(b"x")
    report.write(run, m, plan)
    rep = load(run)
    assert rep["map"]["available"] is False and "does not match the sha-256" in rep["map"]["reason"]
    assert rep["environment"]["available"] is False
    assert "Map not drawn" in (run / "report" / "index.html").read_text()


def test_res_pkl_missing(run):
    m, plan = pm_run.make_run(run, res=False)
    report.write(run, m, plan, env=AnalyticEnv())
    rep = load(run)
    assert rep["map"] == {"available": False, "reason": "stage1b/res.pkl is not in the run directory"}
    assert rep["environment"]["available"] is False and "no track to query" in rep["environment"]["how"]


def test_summary_only_run_without_ship(run):
    m, plan = pm_run.make_run(run, summary_only=True)
    m = {k: v for k, v in m.items() if k != "ship"}
    report.write(run, m, plan)
    rep = load(run)
    assert rep["map"]["available"] is False and rep["environment"]["forcing_at_windows"] == {} and rep["stage3"]["available"] is False
    assert rep["mission"]["data_consumed"]["inputs"] == [] and "none recorded" in (run / "report" / "index.html").read_text()


def test_map_without_ship_and_windows(run):
    m, plan = pm_run.make_run(run)
    m = {k: v for k, v in m.items() if k != "ship"}
    (run / "windows" / "windows.json").write_text("{}")
    report.write(run, m, plan)
    mp = load(run)["map"]
    assert mp["ship"] is None and mp["windows"] == {}


def test_a_run_with_no_stage1b_summary_is_refused(tmp_path):
    with pytest.raises(FileNotFoundError, match="stage1b/summary.json is not in the run directory; run the stage1b stage first"):
        report.write(tmp_path, {}, {})


def test_stage1b_that_is_a_copy_of_stage1(run):
    m, plan = pm_run.make_run(run, stage1b_differs=False)
    report.write(run, m, plan)
    rep = load(run)
    assert not any(d["changed_by_refit"] for d in rep["vehicles"].values())


# ---------------------------------------------------------------------------------------------------------- helpers

def test_scalar_cleaning():
    assert report._f(np.float64("inf")) is None and report._f(np.float32(2.5)) == 2.5 and report._f(3) == 3 and report._f(None) is None
    assert report._pts(np.array([np.nan]), np.array([np.nan])) == []
    assert report._pts(np.array([190.0, 191.0]), np.array([0.0, 1.0])) == [[-170.0, 0.0], [-169.0, 1.0]]
    assert report._unwrap(np.array([-170.0]), 180.0)[0] == 190.0
    assert report.tnum(None, {}, "") is None
    assert report._failed(dict(fail={}, lon=np.zeros((3, 5)))).shape == (5,)
