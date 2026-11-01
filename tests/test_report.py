"""The report stage: traceability of every number, the verdict statements, the degraded paths, and that a broken report is caught."""
import copy
import datetime as dt
import html
import json
import pickle
import re

import numpy as np
import pytest
import yaml

from cafe.pm import budget, config, report, stage1
from cafe.pm import credibility as credibility_mod
from cafe.pm.env.protocol import AnalyticEnv
from cafe.pm.stats import intervals
from tests.fixtures import pm_run


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    """No stored receipts: the credibility page reads CAFE_DATA, which must not be the real /data; and no model-receipts table unless a test writes one."""
    monkeypatch.setenv("CAFE_DATA", str(tmp_path / "data"))
    monkeypatch.setattr(report, "RECEIPTS", tmp_path / "model_receipts.json")


@pytest.fixture
def run(tmp_path):
    d = tmp_path / "run"
    d.mkdir()
    return d


def plain(h):
    """The page as text: tags and the L / R links of the numbers removed."""
    return html.unescape(re.sub(r"<[^>]+>", "", re.sub(r"<a class=lk[^>]*>[LR]</a>", "", h)))


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
    e = rep["emulator"]
    assert (e["available"], e["reason"], e["vehicles"]) == (False, "emulator/holdout.json is not in the run directory", {})
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


def stat_block(k, n):
    """report._stat on an ensemble of k failures in n members."""
    ref = dict(stage="stage1b", receipt="r", ledger="l")
    return report._stat(dict(n=n, k_fail=k, verdict=intervals.verdict(k, n)), ref, "src")


@pytest.mark.parametrize("k, n, region", [(0, 40, "GO"), (30, 40, "NO-GO"), (0, 100, "GO"), (80, 100, "NO-GO"), (40, 200, "MARGINAL")])
def test_a_verdict_whose_95_interval_is_inside_a_range_is_decided(k, n, region):
    d = stat_block(k, n)
    assert d["decided"] is True and d["region"] == region and d["undecided_statement"] is None
    assert report._undecided_badge(d) == ""


@pytest.mark.parametrize("k, n, words", [
    (4, 32, "spans the GO threshold of 0.1, so more members (a larger --budget) would decide it"),
    (0, 32, "spans the GO threshold of 0.1,"),
    (16, 32, "spans the NO-GO threshold of 0.4, so more members (a larger --budget) would decide it"),
    (1, 5, "spans the GO threshold of 0.1 and the NO-GO threshold of 0.4, so more members")])
def test_an_undecided_verdict_says_which_threshold_its_interval_spans_and_that_more_members_decide_it(k, n, words):
    d = stat_block(k, n)
    lo, hi, _ = intervals.interval(k, n, 0.95)
    assert d["decided"] is False and d["region"] is None and intervals.decided_region(k, n, 0.95) is None
    assert d["undecided_statement"].startswith(f"At the 95% level the stopper uses to decide whether more members are needed, the interval on P(fail), "
                                               f"{lo:.4g} to {hi:.4g}, ") and words in d["undecided_statement"]
    assert f"undecided at n = {n}" in report._undecided_badge(d) and 'class="badge undecided"' in report._undecided_badge(d)


def check_decided(rep, h):
    """decided / region agree with intervals.decided_region at 95 %; an undecided verdict has its sentence and badge in the page, a decided one neither."""
    both = {**rep["vehicles"], **rep["links"]}
    for name, d in both.items():
        region = intervals.decided_region(d["k_fail"]["value"], d["n"]["value"], 0.95)
        assert d["region"] == region and d["decided"] is (region is not None), name
        assert (d["undecided_statement"] is None) == d["decided"], name
        assert d["decided"] or html.escape(d["undecided_statement"]) in h, name
    n_undecided = sum(not d["decided"] for d in both.values())
    assert h.count('class="badge undecided"') == 2 * n_undecided          # the card heading and the verdicts table
    return n_undecided


def test_decided_and_region_are_in_the_json_and_the_badge_is_in_the_html_for_exactly_the_undecided(full, tmp_path):
    run, _, _, _, rep = full
    assert check_decided(rep, (run / "report" / "index.html").read_text()) > 0
    assert f'undecided at n = {rep["vehicles"]["uas"]["n"]["value"]}</span>' in (run / "report" / "index.html").read_text()


def test_a_run_with_80_members_is_decided_where_the_interval_allows(run):
    m, plan = pm_run.make_run(run, M=80)
    report.write(run, m, plan)
    rep = load(run)
    check_decided(rep, (run / "report" / "index.html").read_text())
    assert any(d["decided"] for d in {**rep["vehicles"], **rep["links"]}.values())


def test_same_inputs_same_report(full):
    run, m, plan, _, _ = full
    a = (run / "report" / "report.json").read_bytes()
    report.write(run, m, plan)
    assert (run / "report" / "report.json").read_bytes() == a


# ---------------------------------------------------------------------------------------------------------- what would fix it, sensitivities, reach

def test_what_would_fix_it_for_each_vehicle_that_is_not_go(full):
    run, _, _, _, rep = full
    u = rep["vehicles"]["uas"]["fix"]
    assert u["available"] and u["needed"] and u["found"] and u["target"] == "GO or MARGINAL" and u["emulator_trained"] and u["verdict_before"] == "NO-GO"
    b = u["best"]
    assert b["change"] == "launch the sorties 6 h later" and b["method"] == "EMULATED" and b["verdict"] == "GO"
    assert b["p_fail"]["value"] == 0.04 and b["p_fail"]["uncertainty"] == dict(kind="conformal 90 % interval (emulator)", lo=0.01, hi=0.09)
    assert b["distance"]["value"] == 0.8 and b["threshold"]["value"] == 1.9 and b["n"] is None and b["cost"]["unit"] == "notches"
    assert [t["method"] for t in u["tried"]] == ["EMULATED", "not evaluated", "EMULATED"] and u["tried"][1]["p_fail"] is None
    assert u["tried"][1]["reason"] == "out of range"
    v = rep["vehicles"]["usv"]["fix"]
    assert v["best"]["method"] == "Stage 1" and v["best"]["n"]["value"] == 16 and v["best"]["p_fail"]["uncertainty"]["kind"] == "Wilson interval (Stage 1)"
    assert v["best"]["distance"] is None and not v["emulator_trained"]
    assert rep["vehicles"]["glider_eq"]["fix"] == dict(available=True, needed=False)
    h = (run / "report" / "index.html").read_text()
    assert "What would fix it (GO or MARGINAL): <b>launch the sorties 6 h later</b>" in h and "EMULATED, training-set distance" in h
    assert "Stage 1, n = " in h and "What would fix it: nothing needed, the verdict is GO." in h and "All 3 candidates" in h
    assert "out of range; Stage 1 not run" in h
    assert report.check_traceability(rep) == [] and report.check_rendered(rep, h) == []


def test_what_would_fix_it_when_nothing_flips_the_verdict(run):
    m, plan = pm_run.make_run(run)
    f = json.loads((run / "emulator" / "flip.json").read_text())
    f["vehicles"]["uas"].update(found=False, best=None)
    f["vehicles"]["usv"].update(found=False, best=None)
    (run / "emulator" / "flip.json").write_text(json.dumps(f))
    report.write(run, m, plan)
    rep, h = load(run), (run / "report" / "index.html").read_text()
    assert rep["vehicles"]["uas"]["fix"]["best"] is None and report.check_traceability(rep) == []
    t = plain(h)
    assert "none of the 2 candidates evaluated (of 3 candidates) reaches GO or MARGINAL" in t and "the emulator answered those in its range." in t
    assert "none of the 1 candidates evaluated (of 2 candidates) reaches GO" in t
    assert "no emulator is trained yet, so only the nearest few were run in Stage 1." in t
    assert "no single change" not in t


def test_what_would_fix_it_says_not_searched_when_no_candidate_was_evaluated(run):
    """M-6: 'no single change reaches GO' was printed for a vehicle whose candidates were all 'not evaluated'; it must say nothing was tried."""
    m, plan = pm_run.make_run(run)
    f = json.loads((run / "emulator" / "flip.json").read_text())
    usv = f["vehicles"]["usv"]
    usv["tried"] = [dict(t, method="not evaluated", reason="no emulator; Stage 1 not run: this vehicle's share of the emulator budget is spent")
                    for t in usv["tried"]] + [dict(change="deploy 24 h earlier", mod=dict(shift_h=-24.0), cost=4.0, method="not evaluated", invalid=True,
                                                   reason="deploying -24 h gives a time outside the window")]
    usv.update(found=False, best=None)
    (run / "emulator" / "flip.json").write_text(json.dumps(f))
    report.write(run, m, plan)
    rep, t = load(run), plain((run / "report" / "index.html").read_text())
    fix = rep["vehicles"]["usv"]["fix"]
    assert (fix["evaluated"]["value"], fix["candidates"]["value"], fix["invalid"]["value"]) == (0, 2, 1) and report.check_traceability(rep) == []
    assert "not searched: none of the 2 candidates could be evaluated" in t and "so this is not a finding that nothing helps" in t
    assert "no single change among" not in t and "All 3 candidates: 0 candidates evaluated of 2 candidates that can be evaluated, 1 candidates that cannot" in t


def test_what_would_fix_it_without_the_flip_file(run):
    m, plan = pm_run.make_run(run, flip=False)
    report.write(run, m, plan)
    rep, h = load(run), (run / "report" / "index.html").read_text()
    assert rep["vehicles"]["uas"]["fix"] == dict(available=False, reason="emulator/flip.json is not in the run directory")
    assert "What would fix it: not available. emulator/flip.json is not in the run directory" in h
    assert rep["emulator"]["design"] is None


def test_top_three_sensitivities_by_sobol_first_order_index(full):
    run, _, _, _, rep = full
    top = json.loads((run / "stage1b" / "summary.json").read_text())["summary"]
    for vid, d in {**rep["vehicles"], **rep["links"]}.items():
        sens = (top["vehicles"].get(vid) or top["links"][vid])["sensitivity"]
        want = [(k, v) for k, v in sorted(sens["S1"].items(), key=lambda kv: -kv[1])[:3] if v > (sens.get("noise_floor") or 0.0)]
        assert [t["param"] for t in d["top3"]] == [k for k, _ in want] and [t["s1"]["value"] for t in d["top3"]] == [v for _, v in want]
        assert all(t["s1"]["unit"] == "fraction of variance" and t["s1"]["stage"] == "stage1b" for t in d["top3"])
        assert (d["sensitivity"]["param"] is None) == (not d["top3"])                # named only when it clears the noise floor
    u = rep["vehicles"]["usv"]
    assert u["top3"][0]["param"] == u["sensitivity"]["param"] and u["sensitivity"]["noise_floor"]["value"] > 0 and rep["vehicles"]["glider_2n"]["top3"] == []
    h = (run / "report" / "index.html").read_text()
    assert "Top sensitivities (Sobol first-order, share of the variance of failure, above the permutation noise floor): <code>" in h
    assert "Top sensitivities: none above the noise floor" in h and "the noise floor at this member count is S1" in h


def test_the_emulator_section_shows_acceptance_the_noise_floor_and_the_training_table(run):
    m, plan = pm_run.make_run(run)
    h = json.loads((run / "emulator" / "holdout.json").read_text())
    h["glider_eq"].update(cls="glider", rows=140, query_ms=1.5, noise_floor_rmse=0.07, rmse_debiased=0.03,
                          acceptance=dict(rmse_ok=False, coverage_ok=True, query_ok=True))
    h["glider_eq"]["rmse"]["t_fail_h"], h["glider_eq"]["coverage"]["t_fail_h"] = 3.0, 0.88
    h["usv"] = dict(trained=False, reason="2 usv rows in the training table, 100 are needed", rows=2)
    (run / "emulator" / "holdout.json").write_text(json.dumps(h))
    report.write(run, m, plan)
    rep, html_ = load(run), (run / "report" / "index.html").read_text()
    e = rep["emulator"]
    g = e["vehicles"]["glider_eq"]
    assert g["acceptance"]["rmse_ok"] is False and g["acceptance"]["noise_floor_rmse"]["value"] == 0.07
    assert g["acceptance"]["rmse_debiased"]["value"] == 0.03 and g["acceptance"]["limits"]["rmse"]["value"] == 0.05
    assert g["acceptance"]["limits"]["query_ms"]["unit"] == "ms" and g["acceptance"]["rows"]["value"] == 140 and g["rmse"]["t_fail_h"]["unit"] == "h"
    assert e["vehicles"]["usv"]["rows"]["value"] == 2 and e["design"]["variants"]["value"] == 1 and e["design"]["variant"]["value"] == 77.0
    assert e["design"]["spent"]["value"] == 60.0
    assert e["design"]["stage1b_free"]
    assert "(glider emulator)" in html_ and "<b>MISSED</b>" in html_ and "Training table /data/emulator/train.parquet" in html_
    assert "from the planner&#x27;s estimate" in html_
    assert "including stage 1b" in html_
    assert report.check_traceability(rep) == [] and report.check_rendered(rep, html_) == []


def reach_report(run, env, **kw):
    m, plan = pm_run.make_run(run, **kw)
    report.write(run, m, plan, env=env)
    return load(run), (run / "report" / "index.html").read_text()


def test_the_reach_map_routes_through_the_currents_at_the_deploy_time(run):
    rep, h = reach_report(run, AnalyticEnv(current=(0.3, 0.0)))
    r = rep["reach"]
    assert r["available"] and r["horizon"]["value"] == 24.0 and set(r["vehicles"]) == {"glider_eq", "glider_2n", "usv", "uas"}
    g = r["vehicles"]["glider_eq"]
    assert g["available"] and len(g["polygon"]["values"]) == 24 and g["speed"]["value"] == 0.23
    assert 0.27 < g["flow_max"]["value"] < 0.3                                                         # the glider feels the 5-100 m mean
    assert g["max_range_km"]["value"] == pytest.approx((0.23 + g["flow_max"]["value"]) * 86.4, abs=6.0)  # downstream: they add
    lon0 = g["deploy"]["values"][0]
    west = [p for p in g["polygon"]["values"] if p[0] < lon0 - 1e-9]
    assert not west or max(lon0 - p[0] for p in west) < 0.1                                                  # it cannot stem a current stronger than itself
    assert max(p[0] for p in g["polygon"]["values"]) > lon0 + 0.3
    u = r["vehicles"]["usv"]                                    # M-19: the USV is routed at the Stage-1 ensemble's median path speed, not the assumed 1.4 m/s
    res = pickle.loads((run / "stage1b" / "res.pkl").read_bytes())["vehicles"]["usv"]
    assert u["speed"]["value"] == report.path_speed(res) and u["speed"]["value"] != 1.4 and "Stage-1 ensemble" in u["speed_from"]
    assert u["speed"]["stage"].startswith("report (reach map speed") and u["speed"]["receipt"].startswith("stage1b:") and g["speed_from"].startswith("assumed")
    assert u["max_range_km"]["value"] > g["max_range_km"]["value"] * 2
    assert not r["vehicles"]["uas"]["available"] and "flies its sorties from the ship" in r["vehicles"]["uas"]["reason"]
    assert report.check_traceability(rep) == [] and report.check_rendered(rep, h) == []
    assert h.count("<polygon") == 3 and "reach within 24 h of the deploy" in h and "Reach map: fastest routes within" in h and "outline" in h
    assert g["polygon"]["receipt"].startswith("ingest:") and g["polygon"]["stage"].startswith("report (reach map")


def test_the_reach_map_says_why_it_was_not_computed(run):
    rep, h = reach_report(run, None)
    assert rep["reach"] == dict(available=False, vehicles={}, reason="The report was not given an Environment, so there are no currents to route through.")
    assert "Reach map not drawn: The report was not given an Environment" in h and "<polygon" not in h


class Cur(AnalyticEnv):
    """Currents from a function of (lon, lat); everything else analytic."""

    def __init__(self, fn, **kw):
        super().__init__(**kw)
        self.fn = fn

    def current(self, lon, lat, z, t):
        from cafe.pm import Tagged
        return Tagged(self.fn(np.asarray(lon, float), np.asarray(lat, float)), "test", 0.0, "assumed")


def test_reach_explains_a_deploy_on_land_a_failing_environment_and_missing_currents(run):
    rep, _ = reach_report(run, AnalyticEnv(depth=0.0))
    assert all(r["reason"].endswith("the deploy point is on land or has no current data") for k, r in rep["reach"]["vehicles"].items() if k != "uas")
    rep, h = reach_report(run, Cur(lambda lo, la: np.full(lo.shape + (2,), np.nan)))
    assert not rep["reach"]["vehicles"]["usv"]["available"] and "no current data" in rep["reach"]["vehicles"]["usv"]["reason"]
    assert "not drawn. ValueError" in h

    class Broken(AnalyticEnv):
        def current(self, lon, *a):
            if np.size(lon) > 100:                                      # the reach grid; the environment section's 24 points still work
                raise RuntimeError("ocean store unreadable")
            return super().current(lon, *a)
    rep, h = reach_report(run, Broken())
    assert rep["reach"]["vehicles"]["glider_eq"]["reason"] == "RuntimeError: ocean store unreadable" and report.check_traceability(rep) == []


def test_unknown_water_blocks_the_route_like_land(run):
    """Currents are known only west of the deploy meridian: nothing east of it is reachable."""
    def fn(lo, la):
        v = np.zeros(lo.shape + (2,))
        v[lo > -170.0 + 1e-9] = np.nan
        return v
    rep, _ = reach_report(run, Cur(fn))
    g = rep["reach"]["vehicles"]["glider_eq"]                           # deployed on the meridian itself
    lons = [p[0] for p in g["polygon"]["values"]]
    assert max(lons) <= -170.0 + 1e-6 and min(lons) < -170.0 - 0.1


def test_the_reach_grid_is_not_queried_outside_the_ingested_data(run):
    """Like GriddedEnv, the environment answers `inside` and would raise outside its data: the route is cut at the edge instead."""
    class Boxed(AnalyticEnv):
        queried: list = []

        def inside(self, lon, lat, t=None):
            x = np.asarray(lon)
            return (np.abs(x + 170.0) < 0.1) | (np.abs(x + 165.0) < 0.1)                  # data around the two meridians the vehicles sit on

        def current(self, lon, lat, z, t):
            self.queried.append(np.asarray(lon))
            return super().current(lon, lat, z, t)
    env = Boxed(current=(0.0, 0.0))
    rep, _ = reach_report(run, env, emulator=False)
    grid = [x for x in env.queried if x.size > 100]
    assert grid and all(env.inside(x, 0.0).all() for x in grid)
    g = rep["reach"]["vehicles"]["glider_eq"]
    lons = [p[0] for p in g["polygon"]["values"]]
    assert g["available"] and max(lons) <= -169.9 + 1e-6 and min(lons) >= -170.1 - 1e-6


def test_the_reach_map_is_drawn_only_with_a_map(run):
    m, plan = pm_run.make_run(run, res=False)
    report.write(run, m, plan, env=AnalyticEnv(current=(0.3, 0.0)))
    rep, h = load(run), (run / "report" / "index.html").read_text()
    assert rep["map"]["available"] is False and rep["reach"]["available"] and "Map not drawn" in h and "<polygon" not in h


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
    assert "Traceability problems" in h and "FAILED OR MISSING" in h
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


def test_the_sensitivity_line_says_why_no_parameter_is_named():
    assert report._sens_html(dict(param=None, computed=False)) == "none (all-pass, all-fail, or fewer than 16 members)"
    ref = dict(stage="stage1", receipt="r1", ledger="l1")
    floor = report.num(0.25, "fraction of variance", ref, "stage1")
    assert report._sens_html(dict(param=None, computed=True, noise_floor=floor)).startswith("no parameter clears the noise floor (S1 ")


# ---------------------------------------------------------------------------------------------------------- review round 1, batch D

DIGEST = "d" * 64                      # the code digest of the run and of the receipts table, in the tests where they agree


def write_receipts(path, rows, digest=DIGEST):
    """The model-receipts table and, beside it, receipts.meta.json (what receipts.run writes) with the code digest that made it; digest None: no meta file."""
    path.write_text(json.dumps([dict(id=f"{m}/{n}", module=m, name=n, value=1.0, ok=ok, kind=k, source="s", note="") for m, n, k, ok in rows]))
    if digest is not None:
        path.with_name(report.META_NAME).write_text(json.dumps(dict(code_digest=digest, git_sha="abc", made_at="2026-10-31T00:00:00+00:00")))


MODEL_ROWS = [("pm.physics.glider", "glider a", "pass", True), ("pm.physics.glider", "glider b", "pass", True),
              ("pm.physics.glider", "glider c", "context", None),
              ("pm.physics.usv", "usv speed band", "fail", False), ("pm.physics.usv", "usv ok", "pass", True),
              ("pm.physics.uas", "uas a", "pass", True), ("pm.physics.uas.slow", "sitl landing", "fail", False),
              ("pm.physics.comms", "comms a", "pass", True), ("pm.env.waves", "waves", "pass", True)]


def test_each_verdict_cites_the_model_receipt_group_of_its_class_with_pass_and_fail_counts(run, tmp_path):
    """M-1: no verdict cited a model receipt; now glider, usv, uas and the links each cite their group of runs/receipts.json."""
    write_receipts(report.RECEIPTS, MODEL_ROWS)
    m, plan = pm_run.make_run(run, code_digest=DIGEST)
    report.write(run, m, plan)
    rep, rows = load(run), {r["id"]: r for r in load(run)["receipts"]}
    g, u, a = (rep["vehicles"][v]["physics"] for v in ("glider_eq", "usv", "uas"))
    # context rows are not counted
    assert (g["group"], g["status"], g["passed"]["value"], g["failed"]["value"], g["failures"]) == ("pm.physics.glider", "ok", 2, 0, [])
    assert (u["status"], u["passed"]["value"], u["failed"]["value"], u["failures"]) == ("FAILED", 1, 1, ["usv speed band"])
    assert (a["status"], a["passed"]["value"], a["failures"]) == ("FAILED", 1, ["sitl landing"])      # the group includes its .slow rows
    assert rep["links"]["usv-uas-rf"]["physics"]["group"] == "pm.physics.comms" and rep["links"]["usv-uas-rf"]["physics"]["status"] == "ok"
    r = rows["physics:pm.physics.usv"]
    assert (r["kind"], r["ok"], r["ledger"], r["got"]) == ("physics", False, "runs/receipts.json", "1 pass, 1 fail")
    assert r["sha256"] == report.sha256(report.RECEIPTS)
    assert u["passed"]["receipt"] == r["id"] and u["passed"]["ledger"] == "runs/receipts.json" and rows["physics:pm.physics.glider"]["ok"]
    assert rep["traceability_problems"] == []                                               # a failed model receipt is shown, it does not break provenance
    t = plain((run / "report" / "index.html").read_text())
    assert "Model receipts (pm.physics.usv): 1 receipts pass, 1 receipts fail. Failing: usv speed band." in t and "Model receipts (pm.physics.glider)" in t
    assert report.check_rendered(rep, (run / "report" / "index.html").read_text()) == []


def test_a_missing_or_unusable_receipts_table_says_not_run_and_is_never_ok(run, tmp_path):
    m, plan = pm_run.make_run(run)
    report.write(run, m, plan)
    rep = load(run)
    for p in [*(v["physics"] for v in rep["vehicles"].values()), *(k["physics"] for k in rep["links"].values())]:
        assert p["status"] == "not run" and "runs/receipts.json is not there" in p["reason"] and "passed" not in p
    assert not [r for r in rep["receipts"] if r["kind"] == "physics"]
    assert "Model receipts (pm.physics.usv): not run. runs/receipts.json is not there" in plain((run / "report" / "index.html").read_text())
    report.RECEIPTS.write_text("{not json")
    report.write(run, m, plan)
    assert "is not valid JSON" in load(run)["vehicles"]["usv"]["physics"]["reason"]
    write_receipts(report.RECEIPTS, [("pm.physics.glider", "glider a", "pass", True)])
    m, plan = pm_run.make_run(run, code_digest=DIGEST)
    report.write(run, m, plan)
    rep = load(run)
    assert rep["vehicles"]["usv"]["physics"]["reason"] == "no receipt of group pm.physics.usv in runs/receipts.json"
    assert rep["vehicles"]["glider_eq"]["physics"]["status"] == "ok"


def stage3_all_failed(run):
    p = run / "stage3" / "windows.json"
    d = json.loads(p.read_text())
    for ws in d.values():
        for w in ws:
            w["ok"] = False
    p.write_text(json.dumps(d))


def test_the_stage3_output_receipt_is_ok_only_if_some_window_passed(run):
    """M-1: the receipt of windows.json read 'ok' while 6 of 6 windows failed."""
    m, plan = pm_run.make_run(run)
    report.write(run, m, plan)
    r = {r["id"]: r for r in load(run)["receipts"]}["stage3:output:windows.json"]
    assert r["ok"] is True and r["got"] == "5 of 6 windows passed their self-checks"        # the fixture's one failing window does not fail the output
    stage3_all_failed(run)
    report.write(run, m, plan)
    rep, h = load(run), (run / "report" / "index.html").read_text()
    r = {r["id"]: r for r in rep["receipts"]}["stage3:output:windows.json"]
    assert r["ok"] is False and r["got"] == "0 of 6 windows passed their self-checks"
    assert {r["id"]: r for r in rep["receipts"]}["windows:output:windows.json"]["ok"] is True      # the windows stage's own output has no quality bit
    assert rep["traceability_problems"] == [] and "FAILED OR MISSING" in h
    assert "record a failed result" in h and "stage3:output:windows.json" in plain(h)


def test_the_banner_says_provenance_not_pass(full):
    run, _, _, _, rep = full
    h = (run / "report" / "index.html").read_text()
    assert "A link is provenance, not a pass." in h and "passing ledger receipt" not in h and "record a failed result" not in h


def test_a_failed_ledger_check_is_still_a_traceability_problem_but_a_failed_output_is_not(full):
    rep = copy.deepcopy(full[4])
    rows = {r["id"]: r for r in rep["receipts"]}
    out = next(r for r in rep["receipts"] if r["kind"] == "output")
    out["ok"] = False
    assert report.check_traceability(rep) == []
    chk = next(r for r in rep["receipts"] if r["kind"] == "check")
    chk["ok"] = False
    assert report.check_traceability(rep) and rows[chk["id"]] is chk


def test_the_stopping_interval_and_the_thresholds_are_traced_nodes_the_sentences_restate():
    """M-18: the 95 % interval, the thresholds were only inside strings; the printed 90 % interval sat next to a sentence about another level."""
    d = stat_block(16, 32)
    lo, hi, method = intervals.interval(16, 32, 0.95)
    si = d["stop_interval"]
    assert (si["lo"]["value"], si["hi"]["value"]) == (lo, hi) and si["lo"]["uncertainty"] == dict(kind=f"{method} interval bound", conf=0.95)
    assert si["lo"]["receipt"] == "r" and si["hi"]["unit"] == "fraction" and d["p_fail"]["uncertainty"]["conf"] == 0.9
    assert (d["thresholds"]["go"]["value"], d["thresholds"]["nogo"]["value"]) == (intervals.P_FAIL_GO, intervals.P_FAIL_NOGO)
    assert f"{lo:.4g} to {hi:.4g}" in d["undecided_statement"] and "95% level the stopper uses" in d["undecided_statement"]


def test_the_page_labels_both_intervals_with_their_level(full):
    run, _, _, _, rep = full
    t = plain((run / "report" / "index.html").read_text())
    d = rep["vehicles"]["usv"]
    u = d["p_fail"]["uncertainty"]
    assert f"{u['conf']:.0%} {u['kind']} {u['lo']:.3g} to {u['hi']:.3g} (the verdict's own level)" in t
    si = d["stop_interval"]
    kind = si["lo"]["uncertainty"]["kind"].replace(" bound", "")
    assert (f"Stopping rule: the 95% {kind} on P(fail) is {si['lo']['value']:.4g} to {si['hi']['value']:.4g}; "
            "verdict thresholds: GO below 0.1, NO-GO from 0.4.") in t


def test_check_rendered_matches_whole_numeric_tokens():
    """M-18: '0 members' was found inside '10 members', so any zero was 'in the page'."""
    rep = dict(a=dict(value=0, unit="members"), b=dict(value=0.25, unit="fraction"))
    assert report.check_rendered(rep, "<span class=n>0 members</span><span class=n>0.25</span>") == []
    bad = report.check_rendered(rep, "<span class=n>10 members</span><span class=n>0.255</span>")
    assert [b.split(":")[0] for b in bad] == ["a", "b"]
    assert report.check_rendered(rep, "<b>-0 members</b> x0.25 0.25.5")[0].startswith("a:")
    assert report.check_rendered(rep, "0 members, 0.25 .") == []


def stage3_with_a_window_not_run(run, msg):
    p = run / "stage3" / "windows.json"
    d = json.loads(p.read_text())
    d["usv"].append(dict(ok=False, error=msg, checks=[]))
    p.write_text(json.dumps(d))


def test_a_window_that_was_not_run_shows_its_reason_not_an_empty_list(run):
    """M-21: the page said 'failed its self-checks: .' for the USV hull window, which has no checks and an error."""
    m, plan = pm_run.make_run(run)
    msg = "free-surface window not run: estimated 94 min against 6.0 min left; it would fit --budget overnight"
    stage3_with_a_window_not_run(run, msg)
    report.write(run, m, plan)
    rep, h = load(run), (run / "report" / "index.html").read_text()
    w = rep["stage3"]["vehicles"]["usv"][1]
    assert w["error"] == msg and w["not_used_because"] == msg and w["checks"] == [] and w["ok"] is False
    t = plain(h)
    assert f"W2 did not run; not used in the refit: {msg}. Reason: {msg}" in t and "failed self-checks: ." not in t
    assert rep["stage3"]["vehicles"]["glider_eq"][0]["error"] is None


def test_a_failed_window_names_its_failed_checks_and_its_error_when_it_has_both(run):
    m, plan = pm_run.make_run(run)
    p = run / "stage3" / "windows.json"
    d = json.loads(p.read_text())
    d["usv"].append(dict(ok=False, error="boom", checks=[pm_run.check_row("mach_max", 0.4, 0.1, False)]))
    d["usv"].append(dict(ok=False, checks=[]))
    p.write_text(json.dumps(d))
    report.write(run, m, plan)
    w = load(run)["stage3"]["vehicles"]["usv"]
    assert w[1]["not_used_because"] == "failed self-checks: mach_max; boom" and "failed its self-checks" in plain((run / "report" / "index.html").read_text())
    assert w[2]["not_used_because"] == "no check or error recorded"
    assert "failed with no check recorded" in plain((run / "report" / "index.html").read_text())


def test_the_flip_search_time_is_called_a_planned_charge_and_no_wall_time_is_in_the_hashed_design(full):
    """M-22: 'the flip search ran 228.2 s of Stage 1' was a planned charge. The measured stage time is not put next to it: report.json is hashed and a
    clock reading would differ between identical runs (the measured times are under machine.wall_s)."""
    run, _, _, _, rep = full
    d = rep["emulator"]["design"]
    t = plain((run / "report" / "index.html").read_text())
    assert "stage_wall" not in d and d["train_budget"]["value"] == 84.0
    assert "the flip search ran" not in t and "the flip search was charged 3 s of planned Stage-1 cost (a planned charge, not a measurement" in t
    assert "were charged 60 s of planned cost against the emulator share 120 s, of which 84 s is for them" in t
    assert "No variant run fitted" not in t


def test_the_report_says_no_emulator_can_be_trained_when_no_variant_fitted(run):
    m, plan = pm_run.make_run(run)
    p = run / "emulator" / "design.json"
    d = json.loads(p.read_text())
    d.update(variants=[], spent_s=0.0, variant_s=561.8)
    p.write_text(json.dumps(d))
    report.write(run, m, plan)
    t = plain((run / "report" / "index.html").read_text())
    assert "No variant run fitted: one costs 561.8 s, more than the 84 s they may use, so this run added only its own rows" in t
    assert "no emulator can be trained from it at this budget" in t and report.check_rendered(load(run), (run / "report" / "index.html").read_text()) == []


def test_the_first_failure_mode_and_the_mode_shares_say_what_drives_a_failure(full):
    """M-30: only the dominant mode was printed; now the mode of the earliest failure and each mode's share of the failed members."""
    run, _, _, _, rep = full
    res = pickle.loads((run / "stage1b" / "res.pkl").read_bytes())
    u = rep["vehicles"]["uas"]
    first = res["vehicles"]["uas"]["first"]
    want = min(first, key=lambda k: np.nanmin(first[k]) if np.isfinite(first[k]).any() else np.inf)
    assert u["first_fail_mode"] == want == "gust_front" and rep["vehicles"]["glider_2n"]["first_fail_mode"] is None
    k = u["k_fail"]["value"]
    assert set(u["mode_shares"]) == {"gust_front", "battery"} and u["mode_shares"]["gust_front"]["value"] == pytest.approx(1.0) and k > 0
    assert u["mode_shares"]["battery"]["value"] == 0.0 and rep["vehicles"]["glider_2n"]["mode_shares"] == {}
    t = plain((run / "report" / "index.html").read_text())
    assert ("What drives the failures: the first failure was by gust_front; share of the failed members by mode (a member can fail in several): "
            "gust_front 1 fraction") in t


def test_without_res_pkl_the_first_failure_mode_is_not_known(run):
    m, plan = pm_run.make_run(run, res=False)
    report.write(run, m, plan)
    u = load(run)["vehicles"]["uas"]
    assert u["first_fail_mode"] is None and u["mode_shares"]["gust_front"]["value"] > 0
    assert "which mode failed first is not known (res.pkl is not available)" in plain((run / "report" / "index.html").read_text())


def test_the_earliest_failure_decides_the_first_mode():
    r = dict(first=dict(becalmed=np.array([np.nan, 50.0]), swept_off_track=np.array([40.0, np.nan]), wing_stall=np.full(2, np.nan)))
    assert report._first_mode(r) == "swept_off_track"
    assert report._first_mode(dict(first=dict(becalmed=np.full(3, np.nan)))) is None


def test_the_sanity_block_compares_the_demo_missions_verdicts_with_the_brief(full):
    run, _, _, _, rep = full
    sn = rep["sanity"]
    rows = {r["id"]: r for r in sn["rows"]}
    assert sn["applies"] and sn["mission"] == "tepex_c_demo" and "It applies to that mission only" in sn["note"]
    assert rows["glider_eq"]["observed"] == "GO" and rows["glider_eq"]["agrees"] is False and rows["glider_2n"]["agrees"] is True
    assert rows["uas"]["agrees"] is None and rows["usv-uas-rf"]["agrees"] is True and rows["glider_eq-ship-acoustic"]["agrees"] is None
    assert rows["usv"]["p_fail"]["value"] == rep["vehicles"]["usv"]["p_fail"]["value"] and rep["traceability_problems"] == []
    h = (run / "report" / "index.html").read_text()
    assert "<h2>Sanity check against the brief</h2>" in h and "cannot be checked from the verdict" in h and "<b>NO</b>" in h
    assert report.check_rendered(rep, h) == []


def test_another_mission_has_no_sanity_block(run):
    m, plan = pm_run.make_run(run)
    text = (run / "mission.yaml").read_text().replace("name: tepex_c_demo", "name: other")
    (run / "mission.yaml").write_text(text)
    report.write(run, dict(m, name="other"), plan)
    rep = load(run)
    assert rep["sanity"] == dict(applies=False, reason="BRIEF section 6 states an expected outcome for the demo mission only; this mission has none.")
    assert "has none." in (run / "report" / "index.html").read_text()


def test_a_stored_sensitivity_case_is_shown_next_to_the_verdict_and_nothing_is_computed(run):
    m, plan = pm_run.make_run(run)
    report.write(run, m, plan)
    assert all(v["cases"] == [] for v in load(run)["vehicles"].values()) and not [r for r in load(run)["receipts"] if "sensitivity" in r["id"]]
    cases = dict(usv=[dict(case="usv_vpp_bias uniform [-0.35, -0.30] (BRIEF 2.5)", k_fail=31, n=32, verdict="NO-GO", note="still-water VPP minus 30 to 35 %")])
    (run / "stage1b" / report.SENSITIVITY).write_text(json.dumps(cases))
    report.write(run, m, plan)
    rep, t = load(run), plain((run / "report" / "index.html").read_text())
    c = rep["vehicles"]["usv"]["cases"][0]
    assert (c["verdict"], c["k_fail"]["value"], c["n"]["value"], c["p_fail"]["value"]) == ("NO-GO", 31, 32, 31 / 32) and c["p_fail"]["unit"] == "fraction"
    assert c["p_fail"]["receipt"].startswith("stage1b:") and rep["vehicles"]["glider_eq"]["cases"] == [] and rep["traceability_problems"] == []
    assert ("Sensitivity cases (a separate sample whose member count differs from the verdict's" in t
            and c["paired"] is False
            and "usv_vpp_bias uniform [-0.35, -0.30] (BRIEF 2.5)" in t)
    assert report.check_rendered(rep, (run / "report" / "index.html").read_text()) == []


def test_the_report_says_when_the_sub_grid_layer_is_uncalibrated_and_why(run, monkeypatch):
    """Batch E: the sub-grid layer stays at its defaults until a passed LES window recalibrates it; the report says so, with the reason."""
    m, plan = pm_run.make_run(run)
    why = "sub-grid layer uncalibrated: no LES window passed its self-checks; config/subgrid.json was not written"
    monkeypatch.setattr(credibility_mod, "subgrid_uncalibrated", lambda *a, **k: why)
    report.write(run, m, plan)
    rep, h = load(run), (run / "report" / "index.html").read_text()
    assert rep["subgrid"] == dict(calibrated=False, statement=why) and f"<p class=warn>{html.escape(why)}</p>" in h
    assert json.loads((run / "report" / "credibility.json").read_text())["limitations"][12] == dict(
        credibility_mod.SUBGRID_LIMITATION, text=why)
    monkeypatch.setattr(credibility_mod, "subgrid_uncalibrated", lambda *a, **k: None)
    report.write(run, m, plan)
    rep, h = load(run), (run / "report" / "index.html").read_text()
    assert rep["subgrid"] == dict(calibrated=True, statement=None) and "sub-grid layer uncalibrated" not in h


def test_a_link_without_a_margin_prints_n_a_never_a_number(full):
    """Iridium has no margin (a session success), and a link with no valid budget sample has none: the median margin is None, shown as n/a."""
    run, _, _, _, rep = full
    ir = rep["links"]["usv-shore-iridium"]
    assert ir["margin_db_median"] is None and ir["margin_kind"] is None and ir["frac_beyond_horizon"] is None and ir["frac_out_of_range"] is None
    assert rep["links"]["usv-uas-rf"]["margin_db_median"]["unit"] == "dB"
    t = plain((run / "report" / "index.html").read_text())
    assert "median margin n/a.Most sensitive to" in t[t.index("Method: Iridium"):]


def set_link_fields(run, **per_link):
    p = run / "stage1b" / "summary.json"
    d = json.loads(p.read_text())
    for lid, fields in per_link.items():
        d["summary"]["links"][lid].update(fields)
    p.write_text(json.dumps(d))


def test_the_geometry_decided_share_of_a_link_is_shown_in_its_card_and_in_the_verdicts_table(run):
    m, plan = pm_run.make_run(run)
    set_link_fields(run, **{"usv-uas-rf": dict(margin_kind="RF link margin, dB", frac_beyond_horizon=0.25),
                            "glider_eq-ship-acoustic": dict(margin_kind="acoustic link margin, dB", frac_out_of_range=0.0, margin_db_median=None),
                            "usv-shore-iridium": dict(margin_kind="none: Iridium reports a success fraction, not a margin")})
    report.write(run, m, plan)
    rep, h = load(run), (run / "report" / "index.html").read_text()
    rf, ac, ir = (rep["links"][k] for k in ("usv-uas-rf", "glider_eq-ship-acoustic", "usv-shore-iridium"))
    assert rf["frac_beyond_horizon"]["value"] == 0.25 and rf["frac_out_of_range"] is None
    assert rf["frac_beyond_horizon"]["unit"] == "fraction of the needed samples"
    assert ac["frac_out_of_range"]["value"] == 0.0 and ac["margin_db_median"] is None and ir["frac_beyond_horizon"] is None
    t = plain(h)
    assert "(RF link margin, dB); beyond the radio horizon at 0.25 fraction of the needed samples, where no margin is computed" in t
    assert "median margin n/a (acoustic link margin, dB); out of the acoustic model's range at 0 fraction of the needed samples" in t
    iridium = t.split("Method: Iridium")[1].split("Most sensitive")[0]
    assert "(none: Iridium reports a success fraction, not a margin)" in iridium and "beyond the radio horizon" not in iridium
    assert "<th>Beyond radio horizon or out of acoustic range</tr>" in h
    assert report.check_traceability(rep) == [] and report.check_rendered(rep, h) == []
    row = h[h.index("<a href='#v-usv-uas-rf'>"):].split("</tr>")[0]
    assert "0.25" in row and "<td>n/a</tr>" not in row
    assert h[h.index("<a href='#v-usv'>"):].split("</tr>")[0].endswith("<td>n/a")


# ---------------------------------------------------------------------------------------------------------- review round 2, batch D

def edit_json(p, fn):
    d = json.loads(p.read_text())
    fn(d)
    p.write_text(json.dumps(d))


def windows(run, vid, *ws):
    edit_json(run / "stage3" / "windows.json", lambda d: d.__setitem__(vid, list(ws)))


def test_a_receipts_table_made_by_other_code_is_stale_and_never_a_pass(run):
    """M-4: verdicts cited a table two days older than the code, with no digest; the page still said 25 receipts pass."""
    write_receipts(report.RECEIPTS, MODEL_ROWS, digest="e" * 64)                                    # made by other code
    m, plan = pm_run.make_run(run, code_digest=DIGEST)
    report.write(run, m, plan)
    rep, rows = load(run), {r["id"]: r for r in load(run)["receipts"]}
    p = rep["vehicles"]["usv"]["physics"]
    assert (p["status"] == "stale: made by other code"
            and "passed" not in p
            and p["failures"] == []
            and "eeeeeeeeeeee" in p["reason"]
            and "dddddddddddd" in p["reason"])
    assert rows["physics:pm.physics.usv"]["ok"] is False and rows["physics:pm.physics.glider"]["ok"] is False
    t = plain((run / "report" / "index.html").read_text())
    assert "Model receipts (pm.physics.glider): stale: made by other code. runs/receipts.json was made by code eeeeeeeeeeee" in t
    assert "pass, 0 fail" not in t.split("Model receipts (pm.physics.glider)")[1][:200]
    assert rep["traceability_problems"] == []                                                           # shown as stale, not a broken provenance


def test_a_receipts_table_without_a_meta_file_or_a_run_without_a_digest_is_stale(run):
    write_receipts(report.RECEIPTS, MODEL_ROWS, digest=None)
    m, plan = pm_run.make_run(run, code_digest=DIGEST)
    report.write(run, m, plan)
    p = load(run)["vehicles"]["glider_eq"]["physics"]
    assert p["status"] == report.STALE and "no readable receipts.meta.json" in p["reason"]
    report.RECEIPTS.with_name(report.META_NAME).write_text("{not json")
    report.write(run, m, plan)
    assert load(run)["vehicles"]["glider_eq"]["physics"]["status"] == report.STALE
    write_receipts(report.RECEIPTS, MODEL_ROWS)
    m, plan = pm_run.make_run(run)                                                                      # ledgers without a code digest
    report.write(run, m, plan)
    assert load(run)["vehicles"]["glider_eq"]["physics"]["status"] == report.STALE
    m, plan = pm_run.make_run(run, code_digest=DIGEST)
    report.write(run, m, plan)
    assert load(run)["vehicles"]["glider_eq"]["physics"]["status"] == "ok"


CUT = dict(ok=False, cut=True, cut_reason="cut at the time limit: its wall-clock slice (54 s) was spent, 4300 steps were planned", reasons=[
    "cut at the time limit: its wall-clock slice (54 s) was spent, 4300 steps were planned"],
    checks=[dict(name="mach_max", value=0.4, limit=0.1, ok=False)], cd=1.962, cd_spread=0.3, cl=0.1,
    resolution=dict(cells_per_delta=0.6, nu_floored=True, run_steps=3500),
    timing=dict(machine_dependent=dict(cd=1.962, cd_spread=0.3, cl=0.1, run_steps=3500, cells_per_s=3.5e6, checks=[dict(name="mach_max", value=0.4)])))
# (the pipeline moves `timing` out of windows.json into the ledger, so the real file never holds it; the report must not read it or the numbers above)


def test_a_window_cut_at_the_time_limit_withholds_its_numbers_so_two_cut_points_give_one_report(run, tmp_path):
    """M-5: the cut falls at a chunk boundary decided by the clock; its coefficients must not reach a hashed report."""
    out = []
    for steps, cd in ((3500, 1.962), (3200, 1.7)):
        d = tmp_path / f"r{steps}"
        d.mkdir()
        m, plan = pm_run.make_run(d)
        md = dict(CUT["timing"]["machine_dependent"], cd=cd, run_steps=steps)
        windows(d, "glider_eq", dict(CUT, resolution=dict(CUT["resolution"], run_steps=steps), cd=cd, timing=dict(machine_dependent=md)))
        report.write(d, m, plan)
        rep = load(d)
        out.append(rep["stage3"]["vehicles"]["glider_eq"])
        t = plain((d / "report" / "index.html").read_text())
        assert "window cut at the time limit: its coefficients are withheld" in t and "was cut at the time limit" in t
        assert "1.962" not in t and "3500" not in t and "1.7 " not in t and rep["traceability_problems"] == []
        assert report.check_rendered(rep, (d / "report" / "index.html").read_text()) == []
    assert out[0] == out[1] and out[0][0]["coefficients"] == {} and out[0][0]["checks"] == [] and out[0][0]["cut"] is True


def test_a_window_check_with_a_null_value_and_limit_prints_na_not_a_crash(run):
    """M-30: the pipeline writes strict JSON, so a check without a finite value or limit (hangar_reference_comparable) arrives as null."""
    m, plan = pm_run.make_run(run)
    windows(run, "glider_2n", dict(ok=False, reasons=["not comparable"], checks=[dict(name="hangar_reference_comparable", value=None, limit=None, ok=False,
                                                                                   note="no like-for-like reference")]))
    report.write(run, m, plan)
    rep = load(run)
    c = rep["stage3"]["vehicles"]["glider_2n"][0]["checks"][0]
    assert c["value"]["value"] is None and c["limit"]["value"] is None and rep["traceability_problems"] == []
    assert "n/a" in plain((run / "report" / "index.html").read_text())


def test_a_cut_row_as_the_stage_writes_it_gives_the_same_report_as_one_that_still_carries_the_numbers(run, tmp_path):
    """Integration: batch E's cut row has cd and cl None, run_steps None and the reason text; the report prints it as cut, with nothing to withhold."""
    out = []
    for name, row in (("old", CUT), ("real", dict(CUT, cd=None, cl=None, cd_spread=None, timing=None, checks=[],
                                                  resolution=dict(cells_per_delta=0.6, nu_floored=True, run_steps=None, planned_steps=4300,
                                                                  cut_reason=CUT["cut_reason"])))):
        d = tmp_path / name
        d.mkdir()
        m, plan = pm_run.make_run(d)
        windows(d, "glider_eq", row)
        report.write(d, m, plan)
        out.append(load(d)["stage3"]["vehicles"]["glider_eq"][0])
    for w in out:
        assert w["cut"] is True and w["ok"] is False and w["coefficients"] == {} and w["checks"] == [] and w["cells_per_delta"] is None
        assert w["cut_statement"] == report.CUT_STATEMENT and w["reasons"] == CUT["reasons"]


def test_a_killed_window_that_passes_every_check_says_it_was_cut_not_that_nothing_was_recorded(run):
    """M-9: a window with all checks ok and `cut` has ok False, no failed check and no error: the page said 'no check or error recorded'."""
    m, plan = pm_run.make_run(run)
    windows(run, "glider_2n", dict(ok=False, cut=True, reasons=[], checks=[dict(name="mach_max", value=0.05, limit=0.1, ok=True)]))
    report.write(run, m, plan)
    w = load(run)["stage3"]["vehicles"]["glider_2n"][0]
    assert w["not_used_because"] == "cut at the time limit" and w["cut_statement"] == report.CUT_STATEMENT


def test_the_windows_reasons_resolution_and_raised_viscosity_are_on_the_page(run):
    """M-9: windows.json `reasons` (kill, 0.6 cells per boundary-layer thickness, raised viscosity) were never rendered."""
    m, plan = pm_run.make_run(run)
    why = ["resolution below the rule: 0.6 cells per boundary-layer thickness at dx = 0.0952 m (BRIEF 2.6: 5-10)",
           "viscosity raised to the stability floor (lattice 0.0001 instead of 3.7e-06): Reynolds number distorted at this dx"]
    windows(run, "glider_2n", dict(ok=False, reasons=why, checks=[dict(name="viscosity_floor", value=1e-4, limit=3.7e-6, ok=False)],
                                   resolution=dict(cells_per_delta=0.6, nu_floored=True, nu_lat=1e-4)),
            dict(ok=False, reasons=why[:1], checks=[dict(name="mach_max", value=0.05, limit=0.1, ok=True)],
                 resolution=dict(cells_per_delta=0.6, nu_floored=False)))
    report.write(run, m, plan)
    rep, h = load(run), (run / "report" / "index.html").read_text()
    a, b = rep["stage3"]["vehicles"]["glider_2n"]
    assert a["reasons"] == why and why[0] in a["not_used_because"] and why[1] in a["not_used_because"] and a["nu_raised"] is True
    assert b["not_used_because"] == why[0] and b["nu_raised"] is False and b["cells_per_delta"]["value"] == 0.6      # a window with only a resolution reason
    t = plain(h)
    assert (why[0] in t
            and why[1] in t
            and "Cells per boundary-layer thickness: 0.6 cells per boundary-layer thickness (BRIEF 2.6: 5 to 10); lattice viscosity raised: yes" in t)
    assert report.check_rendered(rep, h) == [] and rep["traceability_problems"] == []


def test_the_report_prints_the_planners_les_reach_and_the_skip_reason(run):
    """M-8: a window that cannot reach the physical viscosity on this machine is said so on the page."""
    m, plan = pm_run.make_run(run)
    plan["stage3"] = dict(les=dict(reachable=False, note="no LES coefficients exist on this machine; sub-grid and refit stay uncalibrated", windows={
        "glider_eq/body": dict(reachable=False, runs=False, skip_reason="not run: needs 1.1e13 cell-updates, this machine does 2e9", need_cell_updates=1.1e13),
        "usv/hull": dict(reachable=True, runs=True, skip_reason=None)}))
    report.write(run, m, plan)
    rep, t = load(run), plain((run / "report" / "index.html").read_text())
    r = rep["stage3"]["reach"]
    assert r["note"].startswith("no LES coefficients exist on this machine") and [w["window"] for w in r["windows"]] == ["glider_eq/body", "usv/hull"]
    assert "no LES coefficients exist on this machine; sub-grid and refit stay uncalibrated" in t
    assert ("LES window glider_eq/body: does not reach the physical lattice viscosity in its slice of the budget; not run. "
            "not run: needs 1.1e13 cell-updates") in t
    assert "LES window usv/hull" not in t and rep["traceability_problems"] == []                      # reachable and run: nothing to say
    assert report._les_reach({}) == dict(note=None, windows=[])


def test_the_real_stage3_plan_has_the_shape_the_report_reads(run):
    m, plan = pm_run.make_run(run)
    plan["stage3"] = budget.stage3_plan(plan, stage1._classes(m), budget.stage3_assumptions())
    report.write(run, m, plan)
    rep = load(run)
    assert rep["stage3"]["reach"]["windows"] and all(set(w) == {"window", "reachable", "runs", "reason"} for w in rep["stage3"]["reach"]["windows"])
    assert rep["traceability_problems"] == [] and report.check_rendered(rep, (run / "report" / "index.html").read_text()) == []


def test_the_emulator_section_repeats_the_plans_statement_that_it_cannot_train(run):
    """M-7: 'this budget gives N points per class, 100 are needed' is in plan.json before the run and again in the report's emulator section."""
    m, plan = pm_run.make_run(run)
    note = budget.emulator_plan(plan)["note"]
    assert not budget.emulator_plan(plan)["trains"]
    report.write(run, m, plan)
    rep, t = load(run), plain((run / "report" / "index.html").read_text())
    assert rep["emulator"]["plan_note"] == note and note in t.split("Emulator")[-1]
    m, plan = pm_run.make_run(run, emulator=False)
    report.write(run, m, plan)
    assert load(run)["emulator"]["plan_note"] == note and note in plain((run / "report" / "index.html").read_text())
    assert report._emulator(None, None, report.Trace(run), None)["plan_note"] is None                    # no plan given: nothing to repeat


def test_the_page_says_the_ingest_is_not_counted_against_the_budget(run):
    """M-25: a 522 s cold fetch was read as part of a 20-minute run."""
    m, plan = pm_run.make_run(run)
    report.write(run, m, plan)
    t = plain((run / "report" / "index.html").read_text())
    assert "it is not counted against --budget (a download over the network is a separate step, RUNBOOK 4" in t
    assert report.check_rendered(load(run), (run / "report" / "index.html").read_text()) == []
    bare = run.parent / "bare"
    bare.mkdir()
    m, plan = pm_run.make_run(bare, ledgers=False)
    report.write(bare, m, plan)
    assert "not counted against --budget" not in (bare / "report" / "index.html").read_text()


def test_a_plan_that_can_train_the_emulator_adds_no_note(run, monkeypatch):
    m, plan = pm_run.make_run(run)
    monkeypatch.setattr(budget, "emulator_plan", lambda p: dict(trains=True, note="unused"))
    report.write(run, m, plan)
    assert load(run)["emulator"]["plan_note"] is None and "unused" not in (run / "report" / "index.html").read_text()


def test_a_uas_flip_search_says_which_wind_model_both_sides_used(run):
    """M-6: a shifted sortie flew in hours with no 3-D wind, so the candidate differed from the baseline partly through the wind model."""
    m, plan = pm_run.make_run(run)
    edit_json(run / "emulator" / "flip.json", lambda d: d["vehicles"]["uas"].update(
        wind_model="UAS what-if answers use the 10 m scaled profile for the candidate and the baseline.",
        base_2d=dict(verdict="NO-GO", p_fail=0.66, lo=0.5, hi=0.8)))
    edit_json(run / "stage1b" / "summary.json", lambda d: d["summary"]["vehicles"]["uas"].update(wind3d_fraction=0.25))
    report.write(run, m, plan)
    rep, t = load(run), plain((run / "report" / "index.html").read_text())
    f = rep["vehicles"]["uas"]["fix"]
    assert f["wind_model"].startswith("UAS what-if answers use the 10 m scaled profile") and f["base_2d"]["p_fail"]["value"] == 0.66
    assert "for the candidate and the baseline. The baseline under the same model: NO-GO P(fail) 0.66." in t   # (the sentence, then the number)
    assert rep["vehicles"]["uas"]["wind3d"]["value"] == 0.25 and "Sortie records flown in the WRF 3-D wind field: 0.25" in t
    assert rep["vehicles"]["usv"]["wind3d"] is None and rep["traceability_problems"] == []
    assert report.check_rendered(rep, (run / "report" / "index.html").read_text()) == []


def test_the_usv_block_prints_its_speed_ratio_next_to_chiodis_and_the_sanity_row_repeats_it(run):
    """M-2: the mission-level ratio (0.107 to 0.12) was nowhere on the page next to the 0.178 the prior is calibrated to."""
    m, plan = pm_run.make_run(run)
    edit_json(run / "stage1b" / "summary.json", lambda d: d["summary"]["vehicles"]["usv"].update(
        speed=dict(ratio_median=0.107, sog_ms_median=0.55, u10_ms_median=5.1, calibration_ratio=0.96 / 5.4)))
    report.write(run, m, plan)
    rep, t = load(run), plain((run / "report" / "index.html").read_text())
    s = rep["vehicles"]["usv"]["speed_ratio"]
    assert (s["ratio"]["value"], s["sog"]["value"], s["u10"]["value"]) == (0.107, 0.55, 5.1) and s["chiodi"]["value"] == pytest.approx(0.96 / 5.4)
    assert "Speed over ground / mean 10 m wind along the track: 0.107 (median over members; 0.55 m/s over 5.1 m/s)" in t
    assert "a scenario that differs from the mission (no current, uniform wind, sailing to a station)" in t
    assert report.USV_RATIO_NOTE in t and "a possible double penalty that is not established" in t       # B's M-2 finding, stated beside the numbers
    assert rep["vehicles"]["glider_eq"]["speed_ratio"] is None
    row = next(r for r in rep["sanity"]["rows"] if r["id"] == "usv")
    assert "0.107" in row["detail"] and "0.178" in row["detail"] and rep["traceability_problems"] == []
    assert report.check_rendered(rep, (run / "report" / "index.html").read_text()) == []


def test_the_uas_block_says_attitude_exceedance_cannot_fire_and_prints_the_authority_numbers(run):
    """M-28: the clamp (35 deg) is below the exceedance (42 deg): the UAS verdict is a battery verdict below about 12 m/s of wind."""
    m, plan = pm_run.make_run(run)
    edit_json(run / "stage1b" / "summary.json", lambda d: d["summary"]["vehicles"]["uas"].update(
        authority=dict(clamp_s_median=12.0, clamp_s_max=80.0, demand_ratio_median=1.3, demand_ratio_max=2.5)))
    report.write(run, m, plan)
    rep, t = load(run), plain((run / "report" / "index.html").read_text())
    a = rep["vehicles"]["uas"]["authority"]
    assert (a["clamp_s_median"]["value"], a["demand_ratio_max"]["value"]) == (12.0, 2.5)
    assert "Attitude exceedance cannot fire in this controller model (the tilt clamp, 35 deg, is below the 42 deg exceedance)" in t
    assert "the UAS verdict rests on battery alone below about 12 m/s of wind" in t
    assert "Horizontal-force demand beyond the lean-angle clamp: 12 s per sortie (median; largest 80 s)" in t
    assert rep["vehicles"]["usv"]["authority"] is None and "cannot fire" not in plain(json.dumps(rep["vehicles"]["usv"]["speed_ratio"] or ""))
    assert rep["traceability_problems"] == [] and report.check_rendered(rep, (run / "report" / "index.html").read_text()) == []


def test_the_acoustic_sanity_row_carries_the_ships_distance_to_the_page(run):
    m, plan = pm_run.make_run(run)
    set_link_fields(run, **{"glider_eq-ship-acoustic": dict(distance_km_median=555.0)})
    edit_json(run / "stage1b" / "summary.json", lambda d: d["summary"]["links"]["glider_eq-ship-acoustic"]["verdict"].update(verdict="NO-GO"))
    report.write(run, m, plan)
    rep, t = load(run), plain((run / "report" / "index.html").read_text())
    row = next(r for r in rep["sanity"]["rows"] if r["id"] == "glider_eq-ship-acoustic")
    assert (row["agrees"] is True
            and row["detail"] == "median distance to the ship 555 km, beyond 3 km"
            and "median distance to the ship 555 km, beyond 3 km" in t)


def test_a_sensitivity_case_of_the_verdicts_own_n_is_a_paired_comparison(run):
    """M-15: the 'brief prior' case (n = 32) was printed as 'the same ensemble' beside a verdict of n = 16."""
    m, plan = pm_run.make_run(run)
    n = json.loads((run / "stage1b" / "summary.json").read_text())["summary"]["vehicles"]["usv"]["n"]
    (run / "stage1b" / report.SENSITIVITY).write_text(json.dumps(dict(usv=[dict(case="usv_vpp_bias brief", k_fail=40, n=n, verdict="NO-GO")])))
    report.write(run, m, plan)
    c, t = load(run)["vehicles"]["usv"]["cases"][0], plain((run / "report" / "index.html").read_text())
    assert c["paired"] is True and "same members and same other inputs; only the named input replaced" in t and "separate sample" not in t


def test_left_data_members_get_a_sentence_with_the_time_and_the_fix():
    """M-11: members that left the downloaded data are failed members with their own mode; the page says what to widen."""
    ref = dict(stage="stage1b", ledger="checkpoints/stage1b/ledger.json", receipt="stage1b:config:x")
    e = dict(k_fail=3, modes=dict(left_data=3, swept_off_track=1))
    first = dict(left_data=np.array([np.nan, 1.7e9, 1.7e9 + 3600, np.nan]), swept_off_track=np.array([np.nan, np.nan, np.nan, 1.8e9]))
    res = dict(vehicles=dict(g=dict(first=first)))
    d = report._drivers(e, res, "g", ref, "src")
    assert d["left_data"]["members"]["value"] == 3 and d["left_data"]["first"]["value"] == 1.7e9 and set(d["mode_shares"]) == {"left_data", "swept_off_track"}
    h = report._drivers_html(dict(d, first_fail_mode="left_data"))
    assert "members left the downloaded data at about" in h and "widen <code>box</code> or <code>pad_deg</code> and rerun" in h
    assert report._drivers(e, None, "g", ref, "src")["left_data"]["first"] is None
    assert report._drivers(dict(k_fail=1, modes=dict(battery=1)), res, "g", ref, "src")["left_data"] is None
    assert "left the downloaded data" not in report._drivers_html(report._drivers(dict(k_fail=1, modes=dict(battery=1)), None, "g", ref, "src"))


def track(speed, n=6, dt_s=600.0, lat0=0.0, lon0=-165.0, members=3):
    t = 1.7e9 + dt_s * np.arange(n)
    lat = np.tile(lat0 + np.degrees(speed * dt_s * np.arange(n) / 6.371e6)[:, None], (1, members))
    return dict(t=t, lat=lat, lon=np.full((n, members), lon0))


def test_path_speed_is_the_median_over_members_of_distance_over_reported_time():
    """M-19: the reach map flew the USV at an assumed 1.4 m/s where the ensemble makes 0.63."""
    r = track(0.63)
    assert report.path_speed(r) == pytest.approx(0.63, rel=0.01)
    r["lat"][3:, 1] = np.nan                                                   # a failed member stops reporting: its speed is over the time it reported
    r["lon"][3:, 1] = np.nan
    assert report.path_speed(r) == pytest.approx(0.63, rel=0.01)
    east = dict(t=np.arange(4) * 600.0, lat=np.zeros((4, 1)), lon=np.array([[179.9995], [-179.9995], [179.9995], [-179.9995]]))
    assert report.path_speed(east) == pytest.approx(111.2e3 * 0.001 / 600.0, rel=0.01)       # across the dateline, not 360 degrees
    assert report.path_speed(track(0.0)) is None
    assert report.path_speed(dict(t=np.arange(3) * 1.0, lat=np.full((3, 2), np.nan), lon=np.full((3, 2), np.nan))) is None


def test_the_reach_map_keeps_the_assumed_usv_speed_without_a_stage_1_track(run):
    rep, _ = reach_report(run, AnalyticEnv(current=(0.3, 0.0)), res=False)
    u = rep["reach"]["vehicles"]["usv"]
    assert (u["speed"]["value"] == 1.4
            and u["speed_from"] == "assumed, config/assumptions.yaml reach.speed_ms.usv"
            and u["speed"]["receipt"].startswith("ingest:"))
