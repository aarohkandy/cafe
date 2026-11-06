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

from cafe.pm import acceptance, budget, config, report, stage1
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
    kinds = set()
    for d in [*rep["vehicles"].values(), *rep["links"].values()]:
        assert d["n"]["value"] == 48 < d["n_certify"]["value"] == 73
        if intervals.interval(d["k_fail"]["value"], 48, 0.95)[0] < 0.05:                    # round 5, M-11: only one that leaves 5 % open is told to get more
            assert "cannot be certified at n = 48" in d["certify_statement"] and "73 members" in d["certify_statement"]
            kinds.add("open")
        else:
            assert "excluded by this ensemble" in d["certify_statement"] and "cannot be certified" not in d["certify_statement"]
            kinds.add("excluded")
    assert kinds == {"open", "excluded"}
    assert "3/n" in rep["vehicles"]["glider_2n"]["note"]
    d = rep["vehicles"]["glider_2n"]                                           # M-18: each sentence names the rule its number belongs to
    assert "one-sided" in d["note"] and "two-sided" in d["note"] and "60 members" in d["note"] and "(two-sided 95 % Wilson bound)" in d["certify_statement"]
    assert "certifying P(fail) < 5 % needs 73 members, two-sided 95 % Wilson bound)" in plain((full[0] / "report" / "index.html").read_text())


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
    assert w["value"] == 8.0 and w["unit"] == "m/s" and w["basis"] == pm_run.BASIS[True]


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
    assert "2 candidates evaluated, of 3 candidates that could be: none reaches GO or MARGINAL" in t and "the emulator answered those in its range." in t
    assert "1 candidate evaluated, of 2 candidates that could be: none reaches GO" in t and "1 candidates" not in t      # round 8, M-47
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
    assert "no single change among" not in t and "All 3 candidates: 0 candidates evaluated of 2 candidates that can be evaluated, 1 candidate that cannot" in t


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
    assert "Top sensitivities (Sobol first-order, share of the variance of the 0/1 failure indicator, above the permutation noise floor): <code>" in h
    assert "Top sensitivities: none above the noise floor" in h and "the noise floor at this member count is S1" in h


def test_an_emulator_that_was_not_used_for_answers_says_so_and_an_older_holdout_keeps_the_old_text(run):
    """Follow-up to round 4 M-3: `used: false` in holdout.json adds the line that Stage 1 answered instead, with the reason; no key, no line."""
    m, plan = pm_run.make_run(run)
    h = json.loads((run / "emulator" / "holdout.json").read_text())
    why = "the glider emulator missed BRIEF 2.7 acceptance (coverage), so Stage 1 answers"
    h["glider_eq"].update(cls="glider", rows=140, query_ms=1.5, noise_floor_rmse=0.07, rmse_debiased=0.03, used=False, unused_reason=why,
                          acceptance=dict(rmse_ok=True, coverage_ok=False, query_ok=True), coverage_chance_fail=0.357)
    (run / "emulator" / "holdout.json").write_text(json.dumps(h))
    report.write(run, m, plan)
    rep, html_ = load(run), (run / "report" / "index.html").read_text()
    g = rep["emulator"]["vehicles"]["glider_eq"]
    assert g["used"] is False and g["unused_reason"] == why
    assert f"<b>Not used for answers: Stage 1 answered instead.</b> {why}" in html_ and "<b>MISSED</b>" in html_
    assert report.check_traceability(rep) == [] and report.check_rendered(rep, html_) == []
    h["glider_eq"].pop("used"), h["glider_eq"].pop("unused_reason")
    (run / "emulator" / "holdout.json").write_text(json.dumps(h))
    report.write(run, m, plan)
    assert "Not used for answers" not in (run / "report" / "index.html").read_text()


def test_the_emulator_section_shows_acceptance_the_noise_floor_and_the_training_table(run):
    m, plan = pm_run.make_run(run)
    h = json.loads((run / "emulator" / "holdout.json").read_text())
    h["glider_eq"].update(cls="glider", rows=140, query_ms=1.5, noise_floor_rmse=0.07, rmse_debiased=0.03,
                          acceptance=dict(rmse_ok=False, coverage_ok=True, query_ok=True), coverage_chance_fail=0.42)
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
    assert g["acceptance"]["coverage_chance_fail"]["value"] == 0.42
    assert "a calibrated emulator misses it by chance with probability <span class=n>0.42<a" in html_
    assert "from the planner&#x27;s estimate" in html_
    assert "the share of stage 1b included, since no vehicle was refit" in html_
    assert report.check_traceability(rep) == [] and report.check_rendered(rep, html_) == []


def reach_report(run, env, **kw):
    m, plan = pm_run.make_run(run, **kw)
    report.write(run, m, plan, env=env)
    return load(run), (run / "report" / "index.html").read_text()


def test_the_reach_map_routes_through_the_currents_at_the_deploy_time(run):
    env = AnalyticEnv(current=(0.3, 0.0))
    rep, h = reach_report(run, env)
    r = rep["reach"]
    assert r["available"] and r["horizon"]["value"] == 24.0 and set(r["vehicles"]) == {"glider_eq", "glider_2n", "usv", "uas"}
    g = r["vehicles"]["glider_eq"]
    assert g["available"] and len(g["polygon"]["values"]) == 24 and g["speed"]["value"] == 0.23
    band = 0.3 * float(np.mean(env.profile(np.linspace(-5.0, -950.0, 6))))                # the glider feels the 5 m to dive_depth_m (950 m) mean
    assert 0.1 < band < 0.2 and g["flow_max"]["value"] == pytest.approx(band)
    assert g["max_range_km"]["value"] == pytest.approx((0.23 + g["flow_max"]["value"]) * 86.4, abs=6.0)  # downstream: they add
    lon0 = g["deploy"]["values"][0]
    west = [p for p in g["polygon"]["values"] if p[0] < lon0 - 1e-9]
    assert not west or max(lon0 - p[0] for p in west) < 0.1                                                  # it cannot stem a current stronger than itself
    assert max(p[0] for p in g["polygon"]["values"]) > lon0 + 0.2          # (0.23 + 0.157) m/s downstream for 24 h is 0.30 degrees, less the grid step
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


@pytest.mark.parametrize("shift", ["ulp up", "ulp down", "+1e-11 deg", "-1e-11 deg", "+1e-13 deg", "-1e-13 deg"])
def test_the_reach_polygon_does_not_move_when_a_bearing_changes_in_its_last_bit(monkeypatch, shift):
    """P-3: a cell exactly on a diagonal or an axis has a bearing that is a multiple of 15 degrees, and `ang // 15` flipped on the last bit of arctan2
    (135.00000000000003 is sector 9, 134.99999999999997 sector 8): the same cell, one ulp apart, gave another polygon (a corner moved 0.048 degrees between
    two CPUs). A cell on the north axis can land at 359.99999999999 or at 1e-13 and, rounded after the % 360, at sector 24, which no sector holds. Every cell
    whose bearing is a multiple of 15 degrees is given it moved as `shift` says; the polygon and the range must be those of the unshifted run."""
    from cafe import reach as legacy
    env, v = AnalyticEnv(current=(0.0, 0.0)), dict(deploy=dict(lat=0.0, lon=-170.0, time="2026-01-01T00:00:00Z"))
    ref = dict(stage="s", receipt="r", ledger="l")

    def one() -> dict:
        return report._reach_one(legacy, env, v, "glider", 0.1, 24.0, 0.1, ref, "src", "how", ref)    # at 0.1 m/s 8 sectors end on a diagonal or an axis cell
    want = one()
    real = np.arctan2
    o = np.arange(-20, 21)
    ideal = np.degrees(real(o[None, :] + 0 * o[:, None], o[:, None] + 0 * o[None, :]))           # the bearing of the grid's integer offsets (north = row)
    on = np.abs(ideal / 15.0 - np.round(ideal / 15.0)) < 1e-9
    mult = 15.0 * np.round(ideal / 15.0)
    moved = {"ulp up": lambda m: np.nextafter(np.radians(m), np.inf), "ulp down": lambda m: np.nextafter(np.radians(m), -np.inf)}.get(
        shift, lambda m: np.radians(m + float(shift.split()[0])))

    def shifted(y, x):
        a = real(y, x)
        return np.where(on, moved(mult), a) if np.shape(a) == (41, 41) else a
    monkeypatch.setattr(np, "arctan2", shifted)
    got = one()
    p, q = np.array(want["polygon"]["values"]), np.array(got["polygon"]["values"])
    assert (p != np.array([-170.0, 0.0])).any(1).all()                                   # every one of the 24 sectors holds a cell
    assert q.shape == p.shape == (24, 2) and (q != np.array([-170.0, 0.0])).any(1).all()  # none was lost to sector 24
    assert np.allclose(p, q, rtol=0, atol=1e-9)                                           # the same cells (the bearing itself moves 1e-14 degree)
    assert got["max_range_km"]["value"] == want["max_range_km"]["value"]


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
    assert "Traceability problems" in h and "were not run: " in h and "FAILED OR MISSING" not in h             # a stage with no ledger was not run
    assert {r["state"] for r in rep["receipts"] if not r["ok"]} == {"not_run"}
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
    assert "Model receipts (pm.physics.usv): 1 receipt passed, 1 receipt failed. Failing: usv speed band." in t and "Model receipts (pm.physics.glider)" in t
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
    assert r["ok"] is False and r["state"] == "fail" and r["got"] == "0 of 6 windows passed their self-checks (6 ran and failed)"
    assert {r["id"]: r for r in rep["receipts"]}["windows:output:windows.json"]["ok"] is True      # the windows stage's own output has no quality bit
    assert rep["traceability_problems"] == [] and "receipts below failed a check and are marked FAILED" in h
    assert "stage3:output:windows.json" in plain(h) and "were not run" not in h


def test_the_banner_says_provenance_not_pass(full):
    run, _, _, _, rep = full
    h = (run / "report" / "index.html").read_text()
    assert "A link is provenance, not a pass." in h and "passing ledger receipt" not in h and "failed a check" not in h


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
            "verdict rule: GO when P(fail) is at most 0.1 and the 90 % Wilson upper bound on P(fail) is at most 0.25 (looser than 1 - go); "
            "NO-GO when P(fail) is above 0.4; MARGINAL between.") in t


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
    # round 3 M-1: a drift glider has no criterion to agree with
    assert rows["glider_eq"]["observed"] == "GO" and rows["glider_eq"]["agrees"] is False and rows["glider_2n"]["agrees"] is None
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
    why = "sub-grid layer uncalibrated: no LES window passed its self-checks; stage3/subgrid_calibration.json was not written"
    monkeypatch.setattr(credibility_mod, "subgrid_uncalibrated", lambda *a, **k: why)
    report.write(run, m, plan)
    rep, h = load(run), (run / "report" / "index.html").read_text()
    own = {k: v for k, v in rep["subgrid"].items() if k not in ("source", "switches")}                     # `switches` is round 5, M-7's
    assert own == dict(calibrated=False, statement=why) and f"<p class=warn>{html.escape(why)}</p>" in h
    assert json.loads((run / "report" / "credibility.json").read_text())["limitations"][12] == dict(
        credibility_mod.SUBGRID_LIMITATION, text=why)
    monkeypatch.setattr(credibility_mod, "subgrid_uncalibrated", lambda *a, **k: None)
    report.write(run, m, plan)
    rep, h = load(run), (run / "report" / "index.html").read_text()
    own = {k: v for k, v in rep["subgrid"].items() if k not in ("source", "switches")}
    assert own == dict(calibrated=True, statement=None) and "sub-grid layer uncalibrated" not in h


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


def test_r9_m24_a_window_that_diverged_is_called_diverged_not_cut_at_the_time_limit(run):
    """The statement and the state line said 'cut at the time limit' for every cut window; a window that blew up in its last chunk (or before) was not
    cut by the clock. The row's resolution says which (`diverged`, written by the stage with `cut_reason`)."""
    m, plan = pm_run.make_run(run)
    row = dict(CUT, cd=None, cl=None, cd_spread=None, timing=None, checks=[], reasons=["diverged: the flow went non-finite or past Mach 1 inside a chunk"],
               resolution=dict(cells_per_delta=0.6, nu_floored=True, run_steps=None, planned_steps=4300, diverged=True,
                               cut_reason="diverged: the flow went non-finite or past Mach 1 inside a chunk"))
    windows(run, "glider_eq", row)
    windows(run, "glider_2n", dict(row, resolution=dict(row["resolution"], diverged=False)))
    report.write(run, m, plan)
    rep, t = load(run), plain((run / "report" / "index.html").read_text())
    d, k = rep["stage3"]["vehicles"]["glider_eq"][0], rep["stage3"]["vehicles"]["glider_2n"][0]
    assert d["diverged"] is True and d["cut_statement"] == report.DIVERGED_STATEMENT and "time limit" not in d["cut_statement"]
    assert k["diverged"] is False and k["cut_statement"] == report.CUT_STATEMENT
    assert "diverged and was cut" in t and "window diverged (the flow went non-finite or past Mach 1) before its planned steps were done" in t
    assert report.check_traceability(rep) == [] and report.check_rendered(rep, (run / "report" / "index.html").read_text()) == []


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
    assert ("Speed over ground / mean 10 m wind along the track: median of the per-member ratios 0.107; median speed over ground 0.55 m/s over median wind "
            "5.1 m/s (the quotient of two medians is not the median ratio)") in t
    assert "a scenario that differs from the mission (no current, uniform wind, sailing to a station)" in t
    assert report.USV_RATIO_NOTE in t and "a possible double penalty that is not established" in t       # B's M-2 finding, stated beside the numbers
    assert rep["vehicles"]["glider_eq"]["speed_ratio"] is None
    row = next(r for r in rep["sanity"]["rows"] if r["id"] == "usv")
    assert "0.107" in row["detail"] and "0.178" in row["detail"] and rep["traceability_problems"] == []
    assert report.check_rendered(rep, (run / "report" / "index.html").read_text()) == []


def test_the_uas_block_says_attitude_exceedance_cannot_fire_and_prints_the_authority_numbers(run):
    """M-28: the clamp (35 deg) is below the exceedance (42 deg), so the mode cannot fire. (The note's older wording, 'a battery verdict below about 12 m/s',
    is kept for a summary without the profile count; round 4's M-1 made the verdict rest on the battery and on finishing the profile, round 5's M-26.)"""
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
    assert "3 members left the downloaded data at about" in plain(h) and "widen <code>box</code> or <code>pad_deg</code> and rerun" in h
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


# ---------------------------------------------------------------------------------------------------------- review round 3, batch P

def warn_paragraphs(h):
    return re.findall(r"<p class=warn>(.*?)</p>", h, re.S)


def test_a_table_with_only_stale_rows_gives_a_banner_without_the_word_failed(run):
    """Round 3 M-9: four stale physics receipts (made by other code, no result read) were announced as 'record a failed result'."""
    write_receipts(report.RECEIPTS, MODEL_ROWS, digest="e" * 64)
    m, plan = pm_run.make_run(run, code_digest=DIGEST)
    report.write(run, m, plan)
    rep, h = load(run), (run / "report" / "index.html").read_text()
    st = {r["id"]: r for r in rep["receipts"]}
    assert {st[k]["state"] for k in st if k.startswith("physics:")} == {"stale"} and all(st[k]["ok"] is False for k in st if k.startswith("physics:"))
    assert {r["state"] for r in rep["receipts"] if not r["ok"]} == {"stale"}
    ban = [p for p in warn_paragraphs(h) if "are stale" in p]
    assert len(ban) == 1 and "failed" not in ban[0] and "rerun <code>python -m cafe.pm receipts</code>" in ban[0] and "physics:pm.physics.usv" in ban[0]
    assert "failed a check" not in h and "marked FAILED" not in h and "were not run" not in h
    assert "<td>stale<td>" in h and rep["traceability_problems"] == []


def test_windows_that_were_all_skipped_with_a_reason_are_not_run_and_a_window_that_ran_and_failed_is_failed(run):
    """Round 3 M-9: stage3:output:windows.json read '0 of 6 windows passed their self-checks' for six planned skips."""
    m, plan = pm_run.make_run(run)

    def mark_skipped(d):
        for ws in d.values():
            for w in ws:
                why = "not run: the physical lattice viscosity needs 3e12 cell-updates"
                w.update(ok=False, checks=[], cut=False, error=why, reasons=[why])
    edit_json(run / "stage3" / "windows.json", mark_skipped)
    report.write(run, m, plan)
    rep, h = load(run), (run / "report" / "index.html").read_text()
    r = {r["id"]: r for r in rep["receipts"]}["stage3:output:windows.json"]
    assert (r["ok"], r["state"], r["got"]) == (False, "not_run", "0 of 6 windows ran: each was skipped with a stated reason")
    ban = [p for p in warn_paragraphs(h) if "were not run" in p]
    assert len(ban) == 1 and "stage3:output:windows.json" in ban[0] and "failed" not in ban[0] and "failed a check" not in h
    # one window that ran (it has checks) and failed one makes it a failure again
    edit_json(run / "stage3" / "windows.json", lambda d: d["usv"][0].update(checks=[dict(name="mach_max", value=0.4, limit=0.1, ok=False)]))
    report.write(run, m, plan)
    r = {r["id"]: r for r in load(run)["receipts"]}["stage3:output:windows.json"]
    assert (r["state"], r["got"]) == ("fail", "0 of 6 windows passed their self-checks (1 ran and failed)")


def test_the_report_of_a_resumed_run_ignores_an_earlier_attempts_report_ledger(run):
    """Round 3 M-13: machine.wall_s.report and a second git sha came from the report ledger an earlier attempt had left on disk."""
    m, plan = pm_run.make_run(run, git="aaa1111")
    led = json.loads((run / "checkpoints" / "ingest" / "ledger.json").read_text())
    (run / "checkpoints" / "report").mkdir()
    (run / "checkpoints" / "report" / "ledger.json").write_text(json.dumps(dict(led, git_sha="bbb2222", wall_s=4.238)))
    report.write(run, m, plan)
    mach, h = load(run)["machine"], (run / "report" / "index.html").read_text()
    assert mach["git_sha"] == ["aaa1111"] and "report" not in mach["wall_s"]
    assert set(mach["wall_s"]) == {"ingest", "hangar", "stage1", "windows", "stage3", "refit", "stage1b", "emulator"}
    assert "report stage: written after this table" in h and "bbb2222" not in h and "4.238" not in h
    run2 = run.parent / "fresh"
    run2.mkdir()
    m2, plan2 = pm_run.make_run(run2, git="aaa1111")
    report.write(run2, m2, plan2)
    # identical inputs, identical block
    assert load(run2)["machine"]["git_sha"] == mach["git_sha"] and load(run2)["machine"]["wall_s"].keys() == mach["wall_s"].keys()


def test_the_reach_map_speed_is_the_speed_block_speed(run):
    """Round 3 M-7: the page printed a 0.633 m/s speed over ground in the speed block and 0.661 m/s two lines later for the same ensemble."""
    m, plan = pm_run.make_run(run)
    res = pickle.loads((run / "stage1b" / "res.pkl").read_bytes())["vehicles"]["usv"]
    sog = stage1.path_speed(res["lon"], res["lat"], res["t"])
    sog = sog[np.isfinite(sog) & (sog > 0)]
    edit_json(run / "stage1b" / "summary.json", lambda d: d["summary"]["vehicles"]["usv"].update(
        speed=dict(ratio_median=0.12, sog_ms_median=float(np.median(sog)), u10_ms_median=5.3, calibration_ratio=0.178)))
    report.write(run, m, plan, env=AnalyticEnv(current=(0.1, 0.0)))
    rep, t = load(run), plain((run / "report" / "index.html").read_text())
    assert rep["reach"]["vehicles"]["usv"]["speed"]["value"] == pytest.approx(rep["vehicles"]["usv"]["speed_ratio"]["sog"]["value"], rel=1e-12)   # no stw
    assert rep["reach"]["vehicles"]["usv"]["speed_kind"] == "over ground"
    assert report.path_speed(res) == pytest.approx(float(np.median(sog)), rel=1e-12)
    assert "median of the per-member ratios 0.12; median speed over ground" in t and "(the quotient of two medians is not the median ratio)" in t


def test_a_drift_glider_prints_its_heading_and_the_modes_that_can_fail_it_and_its_sanity_row_is_not_an_agreement(run):
    """Round 3 M-1: glider_2n swam due north on a hard-wired heading and the sanity table counted its GO as agreeing with the brief."""
    m, plan = pm_run.make_run(run)
    m["vehicles"][next(i for i, v in enumerate(m["vehicles"]) if v["id"] == "glider_2n")]["task"]["heading_to"] = 270.0
    report.write(run, m, plan)
    rep, t = load(run), plain((run / "report" / "index.html").read_text())
    d = rep["vehicles"]["glider_2n"]["drift"]
    assert d["heading_to"]["value"] == 270.0 and d["heading_to"]["unit"] == "deg" and d["modes"] == "battery, seafloor, overdepth, no flight, left data"
    assert "Task: drift on a fixed heading of 270 deg; failure modes that can occur: battery, seafloor, overdepth, no flight, left data." in t
    assert "GO means only that the battery and depth limits held on that heading" in t
    assert rep["vehicles"]["glider_eq"]["drift"] is None and rep["vehicles"]["usv"]["drift"] is None
    row = next(r for r in rep["sanity"]["rows"] if r["id"] == "glider_2n")
    assert row["agrees"] is None and "no mission criterion" in row["detail"] and "battery and depth limits held" in row["detail"]
    assert "cannot be checked from the verdict" in t
    assert report.check_traceability(rep) == [] and report.check_rendered(rep, (run / "report" / "index.html").read_text()) == []


def test_the_sensitivity_line_prints_the_sentence_stage_1_wrote_for_the_case_that_applies(run):
    """Round 3 M-2: 'no parameter clears the noise floor' was printed for a vehicle with 3 failures, which a reader takes for 'no parameter matters'."""
    m, plan = pm_run.make_run(run)
    txt = ("Only 3 of 32 members failed, too few to rank the parameters; their ranks among the 32 draws (0 is the lowest value) are "
           "battery_capacity_scale 5, 0, 1")
    edit_json(run / "stage1b" / "summary.json", lambda d: d["summary"]["vehicles"]["uas"]["sensitivity"].update(param=None, text=txt, case="too_few"))
    report.write(run, m, plan)
    rep, h = load(run), (run / "report" / "index.html").read_text()
    assert rep["vehicles"]["uas"]["sensitivity"]["text"] == txt and rep["vehicles"]["uas"]["sensitivity"]["case"] == "too_few"
    assert f"Most sensitive to: {txt}.What drives" in plain(h) or f"Most sensitive to: {txt}." in plain(h)
    edit_json(run / "stage1b" / "summary.json", lambda d: d["summary"]["vehicles"]["usv"]["sensitivity"].update(text="the margin ranks vpp."))
    report.write(run, m, plan)
    t = plain((run / "report" / "index.html").read_text())
    assert re.search(r"Most sensitive to: the margin ranks vpp \(exact S1 [0-9.]+ fraction of variance\)\.", t)      # a named parameter keeps its exact index
    edit_json(run / "stage1b" / "summary.json", lambda d: d["summary"]["vehicles"]["glider_2n"]["sensitivity"].pop("text"))
    report.write(run, m, plan)
    # an older summary: the old wording
    assert "Most sensitive to: none (all-pass, all-fail, or fewer than 16 members)." in plain((run / "report" / "index.html").read_text())
    assert report.check_rendered(load(run), (run / "report" / "index.html").read_text()) == []


def test_an_older_summary_without_the_sensitivity_sentence_names_the_parameter_and_its_index(run):
    """The old wording for a ranked outcome: no `text` in the summary, a named parameter, so the line is `<param> (S1 x)`."""
    m, plan = pm_run.make_run(run)
    param = json.loads((run / "stage1b" / "summary.json").read_text())["summary"]["vehicles"]["usv"]["sensitivity"]["param"]
    assert param is not None
    edit_json(run / "stage1b" / "summary.json", lambda d: d["summary"]["vehicles"]["usv"]["sensitivity"].pop("text"))
    report.write(run, m, plan)
    h = (run / "report" / "index.html").read_text()
    assert f"Most sensitive to: <code>{param}</code> (S1 " in h and re.search(rf"Most sensitive to: {param} \(S1 [0-9.]+ fraction of variance\)\.", plain(h))
    assert report.check_rendered(load(run), h) == []


def test_a_platform_file_without_the_limits_or_clocks_the_statements_rest_on_leaves_them_out_and_says_so(run, tmp_path):
    """`load_platform` returns {} for an empty file: the USV's calm-weather clocks and the UAS's tilt limits cannot be read, so the clocks are not
    shown and the attitude statement says it cannot say whether exceedance can fire (it never invents the numbers)."""
    m, plan = pm_run.make_run(run)
    empty = tmp_path / "empty.yaml"
    empty.write_text("# no keys\n")
    mission = yaml.safe_load((run / "mission.yaml").read_text())
    for doc in (m, mission):
        for v in doc["vehicles"]:
            if v["id"] in ("usv", "uas"):
                v["platform"] = str(empty)
    (run / "mission.yaml").write_text(yaml.safe_dump(mission))
    edit_json(run / "stage1b" / "summary.json", lambda d: d["summary"]["vehicles"]["usv"].update(modes=dict(wing_stall_calm=9, becalmed=2)))
    report.write(run, m, plan)
    rep, t = load(run), plain((run / "report" / "index.html").read_text())
    assert rep["vehicles"]["usv"]["usv_modes"] is None and rep["vehicles"]["uas"]["uas_limits"] is None
    assert "The UAS platform's tilt clamp and attitude exceedance could not be read, so this report does not say whether attitude exceedance can fire." in t
    assert report.check_traceability(rep) == [] and report.check_rendered(rep, (run / "report" / "index.html").read_text()) == []


def test_a_link_decided_on_too_few_samples_is_undecided_granularity_and_the_others_print_their_sample_count(run):
    """Round 3 M-5: a 20 min sortie gave 6 to 12 samples per member, so required_fraction 0.95 meant every sample."""
    m, plan = pm_run.make_run(run)
    edit_json(run / "stage1b" / "summary.json", lambda d: (d["summary"]["links"]["usv-uas-rf"].update(need_count_median=12, granularity_ok=False),
                                                           d["summary"]["links"]["glider_eq-ship-acoustic"].update(need_count_median=40, granularity_ok=True)))
    report.write(run, m, plan)
    rep, h = load(run), (run / "report" / "index.html").read_text()
    g, ok = rep["links"]["usv-uas-rf"]["granularity"], rep["links"]["glider_eq-ship-acoustic"]["granularity"]
    assert (g["need_count"]["value"], g["ok"], g["one_sample"]["value"]) == (12, False, pytest.approx(1 / 12))
    assert g["allowed_miss"]["value"] == pytest.approx(0.05)
    assert ok["ok"] is True and ok["need_count"]["value"] == 40 and rep["links"]["usv-shore-iridium"]["granularity"] is None
    t = plain(h)
    assert ("decided on 12 samples (the median number of required samples per member); one missed sample is 0.08333 of them and the mission allows "
            "0.05 to be missed, so this verdict is undecided: granularity") in t
    assert "decided on 40 samples (the median number of required samples per member); one missed sample is 0.025 of them" in t
    assert h.count("undecided: granularity") >= 2
    assert h.count('badge undecided">undecided: granularity') == 2 and report.check_rendered(rep, h) == []     # round 5, M-8: the Verdicts row and the card


def test_the_worst_window_forcing_is_labelled_as_the_analysis_field_and_names_when_the_members_failed(run):
    """Round 3 M-10: 'surface current speed ... (failed members)' was the unperturbed analysis field at their tracks, read as what the members met."""
    m, plan = pm_run.make_run(run)
    edit_json(run / "windows" / "windows.json",
              lambda d: d["glider_eq"][0].update(basis=pm_run.BASIS[True], failed_at=[pm_run.T0 + 7200.0, pm_run.T0 + 3600.0 * 30]))
    report.write(run, m, plan)
    rep, t = load(run), plain((run / "report" / "index.html").read_text())
    w = rep["environment"]["forcing_at_windows"]["glider_eq"]["windows"]
    assert [x["utc"] for x in w[0]["failed_at"]] == ["2023-03-01 14:00:00Z", "2023-03-02 18:00:00Z"] and w[1]["failed_at"] == []
    assert "(analysis-field forcing at the failed members' tracks, before the member perturbations); those members failed at 2023-03-01 14:00:00Z" in t
    assert "each window is the record of the strongest analysis-field forcing; it is not the instant a member failed" in t
    assert "(failed members)" not in t and report.check_traceability(rep) == []
    assert report.check_rendered(rep, (run / "report" / "index.html").read_text()) == []


def test_the_usv_block_states_the_two_calm_clocks_when_either_calm_mode_occurred(run):
    """Round 3 M-8: wing_stall_calm (30 min) and becalmed (6 h) differ on purpose; the page named neither."""
    m, plan = pm_run.make_run(run)
    edit_json(run / "stage1b" / "summary.json", lambda d: d["summary"]["vehicles"]["usv"].update(modes=dict(wing_stall_calm=9, wing_stall_angle=4, becalmed=2)))
    report.write(run, m, plan)
    rep, t = load(run), plain((run / "report" / "index.html").read_text())
    u = rep["vehicles"]["usv"]["usv_modes"]
    assert (u["trim_min_aws"]["value"], u["calm_sustain"]["value"], u["becalmed_after"]["value"]) == (1.5, 30.0, 6.0)
    assert "wing_stall_calm fires when the apparent wind stays below 1.5 m/s for 30 min" in t
    assert "becalmed only after 6 h of being unable to stem the current" in t
    assert "wing_stall_calm: 9" in t and "wing_stall_angle: 4" in t and rep["vehicles"]["glider_eq"]["usv_modes"] is None
    edit_json(run / "stage1b" / "summary.json", lambda d: d["summary"]["vehicles"]["usv"].update(modes=dict(swept_off_track=5)))
    report.write(run, m, plan)
    assert load(run)["vehicles"]["usv"]["usv_modes"] is None
    assert report.check_rendered(load(run), (run / "report" / "index.html").read_text()) == []


def test_the_emulator_section_prints_the_fresh_draw_check_and_the_draws_statement(run):
    """Round 3 M-4: the hold-out was scored against targets that shared the training points' draws; the larger of the two RMSEs is what is judged."""
    m, plan = pm_run.make_run(run)
    h = json.loads((run / "emulator" / "holdout.json").read_text())
    h["glider_eq"].update(cls="glider", rows=140, query_ms=1.5, noise_floor_rmse=0.07, rmse_debiased=0.03,
                          draws="Each variant of a run is run on its own members.",
                          fresh_points=3, fresh_n_members=16, rmse_fresh=0.12, noise_floor_fresh=0.09, rmse_fresh_debiased=0.08,
                          acceptance=dict(rmse_ok=False, coverage_ok=True, query_ok=True))
    (run / "emulator" / "holdout.json").write_text(json.dumps(h))
    report.write(run, m, plan)
    rep, html_ = load(run), (run / "report" / "index.html").read_text()
    f = rep["emulator"]["vehicles"]["glider_eq"]["acceptance"]["fresh"]
    got = (f["points"]["value"], f["n_members"]["value"], f["rmse"]["value"], f["rmse_debiased"]["value"], f["noise_floor"]["value"])
    assert got == (3, 16, 0.12, 0.08, 0.09)
    t = plain(html_)
    assert ("Fresh-draw check: 3 held-out points re-run on 16 members that no training row used; the emulator's RMSE against them 0.12, "
            "0.08 less their own noise 0.09") in t
    assert "judged on the larger of this and the in-sample figure. Each variant of a run is run on its own members." in t
    h["glider_eq"].update(fresh_points=0)
    (run / "emulator" / "holdout.json").write_text(json.dumps(h))
    report.write(run, m, plan)
    assert load(run)["emulator"]["vehicles"]["glider_eq"]["acceptance"]["fresh"] is None
    assert "no held-out point of this run's variants could be re-run" in plain((run / "report" / "index.html").read_text())
    assert report.check_traceability(load(run)) == [] and report.check_rendered(load(run), (run / "report" / "index.html").read_text()) == []


def test_a_fitted_sigma_is_not_counted_as_an_assumed_input_in_the_report(run):
    """Round 3 M-12: the page counted the TAO-fitted sst_k and t2_k among the inputs assumed for this run."""
    m, plan = pm_run.make_run(run)
    report.write(run, m, plan)
    base = load(run)["assumed_inputs"]
    (run / "ingest").mkdir(exist_ok=True)
    (run / "ingest" / "env_sigmas_fitted.json").write_text(json.dumps(dict(sst_k=0.2592, t2_k=1.1908)))
    report.write(run, m, plan)
    a = load(run)["assumed_inputs"]
    assert a["total"]["value"] == base["total"]["value"] - 2
    assert a["by_file"]["config/assumptions.yaml"]["value"] == base["by_file"]["config/assumptions.yaml"]["value"] - 2
    assert sum(i["kind"] == "fitted" for i in a["items"]) == 2 and len(a["items"]) == len(base["items"])
    t = plain((run / "report" / "index.html").read_text())
    assert "(fitted) this run used 0.259 (fitted from the TAO comparison); assumed 0.5" in t


def test_the_report_says_which_sub_grid_calibration_it_used(run):
    """Round 3 M-23: the calibration is the run's own stage3/subgrid_calibration.json when stage 3 wrote one, else the shipped file."""
    m, plan = pm_run.make_run(run)
    report.write(run, m, plan)
    assert load(run)["subgrid"]["source"].startswith("the shipped config/subgrid.json")
    assert "Sub-grid calibration used by the stages after stage 3: the shipped config/subgrid.json" in plain((run / "report" / "index.html").read_text())
    (run / "stage3" / "subgrid_calibration.json").write_text(json.dumps(dict(source_run="stage 3 of this run", sigma_u_over_ustar=2.9)))
    report.write(run, m, plan)
    assert load(run)["subgrid"]["source"] == "this run's stage3/subgrid_calibration.json" and load(run)["subgrid"]["calibrated"] is True


# ---------------------------------------------------------------------------------------------------------- review round 4

def test_the_sensitivity_paragraph_says_which_errors_the_indices_cannot_see(run):
    """Round 4 M-17: the indices rank the sampled columns; the larger per-member random streams are not columns."""
    m, plan = pm_run.make_run(run)
    report.write(run, m, plan)
    t0 = plain((run / "report" / "index.html").read_text())
    sc = load(run)["sensitivity_scope"]
    assert "These indices rank only the sampled columns" in t0 and "per-member random streams" in t0 and sc["wind_sd"] is None and "sd " not in sc["text"]
    fit = {k: dict(dist="normal", value=v, unit=u) for k, v, u in (("wind_speed_bias", 0.113, "m/s"), ("wind_speed_noise", 1.283, "m/s"),
                                                                  ("wind_direction_bias", 2.63, "deg"), ("wind_direction_noise", 22.2, "deg"))}
    (run / "ingest").mkdir(exist_ok=True)
    (run / "ingest" / "priors_fitted.json").write_text(json.dumps(fit))
    report.write(run, m, plan)
    rep, h = load(run), (run / "report" / "index.html").read_text()
    t = plain(h)
    assert "the hourly wind error (sd 1.283 m/s and 22.2 deg, against 0.113 m/s and 2.63 deg for the wind-speed and direction columns)" in t
    assert "per-member random streams" in t and rep["sensitivity_scope"]["wind_sd"]["wind_speed_noise"]["value"] == 1.283
    assert rep["traceability_problems"] == [] and report.check_rendered(rep, h) == []
    (run / "ingest" / "priors_fitted.json").write_text(json.dumps({"wind_speed_bias": fit["wind_speed_bias"]}))          # a partial file: no numbers claimed
    report.write(run, m, plan)
    assert load(run)["sensitivity_scope"]["wind_sd"] is None


def test_a_vehicle_with_no_failure_is_not_blamed_on_a_missing_res_pkl(full):
    """Round 4 M-19: 'which mode failed first is not known (res.pkl is not available)' was printed for a vehicle none of whose members failed."""
    run, _, _, _, rep = full
    g = rep["vehicles"]["glider_2n"]
    assert g["k_fail"]["value"] == 0 and g["res_available"] is True and rep["vehicles"]["uas"]["res_available"] is True
    h = (run / "report" / "index.html").read_text()
    card = h.split("id='v-glider_2n'")[1].split("id='v-")[0]
    assert "no member failed" in plain(card) and "res.pkl" not in card
    d = rep["vehicles"]["usv"]
    assert d["res_available"] and d["k_fail"]["value"] > 0 and "no member failed" not in plain(h.split("id='v-usv'")[1].split("id='v-")[0])


def test_without_res_pkl_a_vehicle_with_no_failure_still_says_res_pkl_is_missing(run):
    m, plan = pm_run.make_run(run, res=False)
    report.write(run, m, plan)
    rep, h = load(run), (run / "report" / "index.html").read_text()
    assert rep["vehicles"]["glider_2n"]["res_available"] is False
    assert "which mode failed first is not known (res.pkl is not available)" in plain(h.split("id='v-glider_2n'")[1].split("id='v-")[0])


def test_the_uas_block_prints_the_waypoints_flown_and_the_new_attitude_wording(run):
    """Round 4 M-1: a timer that ends the profile at 7 of 8 waypoints was invisible; the page prints it and names the profile_incomplete mode."""
    m, plan = pm_run.make_run(run)
    edit_json(run / "stage1b" / "summary.json", lambda d: d["summary"]["vehicles"]["uas"].update(
        profile=dict(wp_done_median=7.0, n_wp=8, complete_share=0.25), modes=dict(profile_incomplete=30, battery=2)))
    report.write(run, m, plan)
    rep, t = load(run), plain((run / "report" / "index.html").read_text())
    p = rep["vehicles"]["uas"]["profile"]
    assert (p["wp_done_median"]["value"], p["n_wp"]["value"], p["complete_share"]["value"]) == (7.0, 8, 0.25)
    assert "Median waypoints flown per sortie: 7 of 8; share of the flown sorties that reached every waypoint: 0.25" in t
    assert "so the UAS verdict rests on the battery and on finishing the profile inside the time limit." in t and "battery alone" not in t
    assert "profile_incomplete: 30" in t and "returned (time limit or battery reserve) before its last pattern waypoint" in t
    assert rep["vehicles"]["glider_eq"]["profile"] is None and rep["traceability_problems"] == []
    assert report.check_rendered(rep, (run / "report" / "index.html").read_text()) == []
    edit_json(run / "stage1b" / "summary.json", lambda d: d["summary"]["vehicles"]["uas"].pop("profile"))        # a summary from before the profile was counted
    report.write(run, m, plan)
    t = plain((run / "report" / "index.html").read_text())
    assert load(run)["vehicles"]["uas"]["profile"] is None and "rests on battery alone below about 12 m/s of wind" in t and "waypoints flown" not in t


def test_no_current_data_is_a_named_failure_mode_on_the_page(run):
    """Round 4 M-5: a missing current is a labelled failure like the glider's no_flight; the mode table says what it is."""
    m, plan = pm_run.make_run(run)
    edit_json(run / "stage1b" / "summary.json", lambda d: d["summary"]["vehicles"]["usv"].update(modes=dict(no_current_data=4)))
    report.write(run, m, plan)
    rep, t = load(run), plain((run / "report" / "index.html").read_text())
    assert rep["vehicles"]["usv"]["mode_notes"] == dict(no_current_data=report.MODE_TEXT["no_current_data"]) and rep["vehicles"]["uas"]["mode_notes"] == {}
    assert "no_current_data: 4" in t and "there was no finite wind, current or wave state at the vehicle's position" in t


def test_the_emulator_section_prints_both_coverage_numbers_with_their_scales(run):
    """Round 4 M-3: the gate reads the calibration-scale coverage; the raw-P number is printed beside it, with why it is lower."""
    m, plan = pm_run.make_run(run)
    h = json.loads((run / "emulator" / "holdout.json").read_text())
    h["glider_eq"].update(coverage=dict(p_fail=0.93), coverage_raw_p=dict(p_fail=0.78))
    (run / "emulator" / "holdout.json").write_text(json.dumps(h))
    report.write(run, m, plan)
    rep, t = load(run), plain((run / "report" / "index.html").read_text())
    g = rep["emulator"]["vehicles"]["glider_eq"]
    assert g["coverage"]["p_fail"]["value"] == 0.93 and g["coverage_raw_p"]["p_fail"]["value"] == 0.78 and rep["traceability_problems"] == []
    assert ("coverage on the calibration scale (clipped logit) 0.93; on the raw P scale 0.78, where a target of exactly 0 or 1 cannot be inside the interval "
            "(nominal 0.9)") in t
    assert report.check_rendered(rep, (run / "report" / "index.html").read_text()) == []
    h["glider_eq"].pop("coverage_raw_p")                                          # an older hold-out file: the old wording
    (run / "emulator" / "holdout.json").write_text(json.dumps(h))
    report.write(run, m, plan)
    assert load(run)["emulator"]["vehicles"]["glider_eq"]["coverage_raw_p"] is None
    assert "p_fail RMSE 0.04, coverage 0.93 (nominal 0.9)" in plain((run / "report" / "index.html").read_text())


def _usv_reach_run(run, stw):
    m, plan = pm_run.make_run(run)
    res = pickle.loads((run / "stage1b" / "res.pkl").read_bytes())["vehicles"]["usv"]
    sog = stage1.path_speed(res["lon"], res["lat"], res["t"])
    sog = float(np.median(sog[np.isfinite(sog) & (sog > 0)]))
    sp = dict(ratio_median=0.12, sog_ms_median=sog, u10_ms_median=5.3, calibration_ratio=0.178)
    edit_json(run / "stage1b" / "summary.json", lambda d: d["summary"]["vehicles"]["usv"].update(speed=dict(sp, stw_ms_median=stw) if stw else sp))
    report.write(run, m, plan, env=AnalyticEnv(current=(0.1, 0.0)))
    return load(run), plain((run / "report" / "index.html").read_text()), sog


def test_the_usv_reach_map_swims_at_the_speed_through_the_water_and_says_so(run):
    """Round 4 M-7: the router adds the current, so it must be given the speed through the water, not the speed over ground, and the label must be true."""
    rep, t, sog = _usv_reach_run(run, 0.72)
    u = rep["reach"]["vehicles"]["usv"]
    assert u["speed"]["value"] == 0.72 != sog and u["speed_kind"] == "through the water" and u["speed"]["stage"].startswith("report (reach map speed")
    assert "median over members of the mean speed through the water of the Stage-1 tracks; the current is added by the router" in u["speed_from"]
    assert "at 0.72 m/s through the water (median over members" in t and rep["traceability_problems"] == []
    assert rep["vehicles"]["usv"]["speed_ratio"]["sog"]["value"] == sog                                      # the speed block keeps speed over ground
    rep, t, sog = _usv_reach_run(run.parent / "old", None)                                                   # an older summary: over ground, said so
    u = rep["reach"]["vehicles"]["usv"]
    assert u["speed"]["value"] == pytest.approx(sog) and u["speed_kind"] == "over ground" and "adds the current a second time" in u["speed_from"]
    assert f"{sog:.4g} m/s over ground" in t and f"{sog:.4g} m/s through the water" not in t


def test_the_glider_reach_current_band_ends_at_the_depth_its_task_dives_to(run):
    """Round 4 M-7: the glider's current was the mean over 5 to 100 m whatever the dive; the band is 5 m to the task's dive_depth_m."""
    seen = []

    class Deep(AnalyticEnv):
        def current(self, lon, lat, z, t):
            if np.size(lon) > 100:
                seen.append(float(z))
            return super().current(lon, lat, z, t)
    m, plan = pm_run.make_run(run)
    report.write(run, m, plan, env=Deep(current=(0.1, 0.0)))
    rep, t = load(run), plain((run / "report" / "index.html").read_text())
    depth = {v["id"]: v["task"]["dive_depth_m"] for v in m["vehicles"] if v["id"].startswith("glider")}
    g = rep["reach"]["vehicles"]
    assert depth == {"glider_eq": 950.0, "glider_2n": 500.0}
    assert g["glider_eq"]["current_band"] == "mean current from 5 m to 950 m" and g["glider_2n"]["current_band"] == "mean current from 5 m to 500 m"
    assert min(seen) == -950.0 and -500.0 in seen and "mean current from 5 m to 950 m" in t and g["usv"]["current_band"] == "current at the surface"


# ---------------------------------------------------------------------------------------------------------- review round 5 (batch S)

def test_a_p_fail_the_ensemble_excludes_is_not_told_to_get_more_members():
    """Round 5 M-11: 'P(fail) < 5 % cannot be certified at n = 64: 73 members are needed' was printed for 60 failures of 64."""
    d = stat_block(60, 64)
    assert "excluded by this ensemble" in d["certify_statement"] and "no number of members certifies it" in d["certify_statement"]
    assert "cannot be certified" not in d["certify_statement"]
    t = plain(report._stat_html(d))
    assert "excluded by this ensemble (lower 95 % bound 0.8" in t and "cannot be certified" not in t
    d = stat_block(0, 64)                                                    # a zero-failure ensemble does leave 5 % open
    assert "cannot be certified at n = 64" in d["certify_statement"] and "73 members" in d["certify_statement"]
    assert "60 members would be needed" not in d["note"] and "weaker statement" in d["note"] and "already below" not in d["note"]
    assert stat_block(2, 80)["certify_statement"] is None                    # n >= n_certify: nothing to say


def test_the_verdict_rule_is_stated_with_its_ties_and_the_wilson_bound_the_go_rule_also_needs(run):
    """Round 5 M-12: the page printed 'GO below 0.1, NO-GO from 0.4', the opposite at both ties and silent on the 0.75 rule."""
    d = stat_block(16, 32)
    assert d["thresholds"]["go_bound"]["value"] == pytest.approx(1 - intervals.LO_SUCCESS_GO) == 0.25
    assert d["thresholds"]["go_bound"]["source"].startswith("stats/intervals.py LO_SUCCESS_GO")
    t = plain(report._stat_html(d))
    assert ("verdict rule: GO when P(fail) is at most 0.1 and the 90 % Wilson upper bound on P(fail) is at most 0.25 (looser than 1 - go); "
            "NO-GO when P(fail) is above 0.4; MARGINAL between.") in t
    assert "GO below" not in t and "NO-GO from" not in t
    assert intervals.verdict(10, 100)["verdict"] == "GO" and intervals.verdict(40, 100)["verdict"] == "MARGINAL"        # the ties the sentence now describes


def test_a_link_that_was_never_required_is_undecided_in_the_verdicts_table_and_once_on_the_card(run):
    """Round 5 M-8: the granularity badge was on the card only, so the headline table said a plain GO for a link that had no moment to fail."""
    m, plan = pm_run.make_run(run)
    set_link_fields(run, **{"usv-uas-rf": dict(need_count_median=0, granularity_ok=False)})
    report.write(run, m, plan)
    rep, h = load(run), (run / "report" / "index.html").read_text()
    row = h[h.index("<a href='#v-usv-uas-rf'>"):].split("</tr>")[0]
    assert "undecided: granularity" in row
    assert h[h.index("<a href='#v-glider_eq-ship-acoustic'>"):].split("</tr>")[0].count("undecided: granularity") == 0
    card = h.split("<div id='v-usv-uas-rf'>")[1].split("<div id='v-")[0]
    assert card.count('<span class="badge undecided">undecided: granularity</span>') == 1      # drawn once, not by the card and again by the badge helper
    t = plain(card)
    assert "Required at no moment in the median member (0 samples): the link was not exercised" in t
    assert report.check_traceability(rep) == [] and report.check_rendered(rep, h) == []


def test_the_top_sensitivities_line_names_the_quantity_the_indices_were_taken_on():
    """Round 5 M-2: 'share of the variance of failure' was printed over indices taken on a battery margin."""
    top = [dict(param="p", s1=dict(value=0.5, unit="fraction of variance", stage="s", source="x", uncertainty=None, receipt="r", ledger="l"))]
    t = plain(report._top3_html(top, None, "fraction of the flux profile delivered (lowest sortie)"))
    assert "share of the variance of the fraction of the flux profile delivered (lowest sortie)," in t and "variance of failure" not in t
    assert "of the 0/1 failure indicator," in plain(report._top3_html(top, None, "failure indicator"))
    assert "of the ranked outcome," in plain(report._top3_html(top)) and "variance of failure" not in report._top3_html(top)


def test_the_page_prints_the_five_subgrid_switches_and_which_the_mission_left_out(run):
    """Round 5 M-7: a mission without `environment.subgrid` flew a UAS without turbulence and gust fronts and the page did not say so."""
    m, plan = pm_run.make_run(run)
    report.write(run, m, plan)
    sw = load(run)["subgrid"]["switches"]
    assert set(sw) == {"turbulence", "gust_fronts", "warm_layer", "rain_lens", "ocean_sde"} and not any(x["defaulted"] for x in sw.values())
    t = plain((run / "report" / "index.html").read_text())
    assert "Sub-grid switches: turbulence on, gust fronts on, warm layer on, rain lens on, ocean SDE on." in t
    edit_json(run / "stage1b" / "summary.json", lambda d: d["summary"]["subgrid_switches"]["gust_fronts"].update(defaulted=True))
    report.write(run, m, plan)
    t = plain((run / "report" / "index.html").read_text())
    assert "gust fronts on (left out of the mission: on by default), warm layer on" in t and "turbulence on, gust" in t
    edit_json(run / "stage1b" / "summary.json", lambda d: d["summary"].pop("subgrid_switches"))                       # a summary from before round 5
    report.write(run, m, plan)
    assert load(run)["subgrid"]["switches"] is None and "Sub-grid switches" not in (run / "report" / "index.html").read_text()


def test_the_wind_prior_line_prints_the_upper_bound_when_the_fit_has_one(run):
    """Round 5 M-10: 0.113 m/s was printed as if known; the fit's 95 % upper bound (`value_hi95`, written by the ingest stage) goes beside it."""
    m, plan = pm_run.make_run(run)
    fit = {k: dict(dist="normal", value=v, unit=u) for k, v, u in (("wind_speed_bias", 0.113, "m/s"), ("wind_speed_noise", 1.283, "m/s"),
                                                                  ("wind_direction_bias", 2.63, "deg"), ("wind_direction_noise", 22.2, "deg"))}
    (run / "ingest").mkdir(exist_ok=True)
    (run / "ingest" / "priors_fitted.json").write_text(json.dumps(fit))
    report.write(run, m, plan)
    assert "95 % upper bound" not in plain((run / "report" / "index.html").read_text()) and load(run)["sensitivity_scope"]["wind_hi95"] == {}   # an older fit
    fit["wind_speed_bias"]["value_hi95"] = 0.49
    (run / "ingest" / "priors_fitted.json").write_text(json.dumps(fit))
    report.write(run, m, plan)
    rep, h = load(run), (run / "report" / "index.html").read_text()
    assert "against 0.113 m/s (95 % upper bound 0.49 m/s) and 2.63 deg for the wind-speed and direction columns" in plain(h)
    assert rep["sensitivity_scope"]["wind_hi95"]["wind_speed_bias"]["value"] == 0.49
    assert rep["traceability_problems"] == [] and report.check_rendered(rep, h) == []


def test_the_machine_block_prints_what_the_planner_charged_next_to_what_the_stages_took(run):
    """Round 5 M-13: the printed plan was 2.05 times low and nothing on the page set it against the ledger."""
    m, plan = pm_run.make_run(run)
    plan["stage1_s_basis"] = "critical path: the longest task or the work over the workers"
    report.write(run, m, plan)
    rep = load(run)
    t = plain((run / "report" / "index.html").read_text())
    s1 = rep["machine"]["timing"]["stage1"]
    assert s1["planned"]["value"] == plan["stage1_s"] and s1["measured"]["value"] == rep["machine"]["wall_s"]["stage1"]["value"]
    assert "variants" not in rep["machine"]["timing"]
    assert f"Stage 1: planned {plan['stage1_s']:.4g} s, measured {s1['measured']['value']:.4g} s (the plan is a lower bound: critical path" in t
    edit_json(run / "checkpoints" / "emulator" / "ledger.json", lambda d: d.update(variant_planned_s=26.34, variant_wall_s=[31.0, 36.0, 33.0, 72.0]))
    report.write(run, m, plan)
    rep, h = load(run), (run / "report" / "index.html").read_text()
    v = rep["machine"]["timing"]["variants"]
    assert (v["runs"]["value"], v["planned"]["value"], v["measured"]["value"]) == (4, pytest.approx(4 * 26.34), 172.0)
    assert "Emulator variant runs: 4 runs, planned 105.4 s, measured 172 s." in plain(h)
    assert rep["traceability_problems"] == [] and report.check_rendered(rep, h) == []
    del plan["stage1_s_basis"]                                               # an older plan without the basis, an older design without the keys
    edit_json(run / "checkpoints" / "emulator" / "ledger.json", lambda d: (d.pop("variant_planned_s"), d.pop("variant_wall_s")))
    report.write(run, m, plan)
    assert set(load(run)["machine"]["timing"]) == {"stage1"} and "the plan is a lower bound" not in (run / "report" / "index.html").read_text()


def test_the_plan_block_says_sitl_is_not_in_the_pipeline_instead_of_a_member_count(run):
    """Round 6 M-3: a 4h plan said '4 members' of ArduCopter SITL that no stage flew."""
    m, plan = pm_run.make_run(run, budget_name="4h")
    report.write(run, m, plan)
    t = plain((run / "report" / "index.html").read_text())
    assert "sitl_members 0 members" in t and "sitl_members 4" not in t
    assert ("ArduCopter SITL is not part of the pipeline; it runs only as the slow receipts (UAS SITL vs our controller, UAS sortie), "
            "so the ensemble is pure physics") in t


def test_a_receipts_table_made_with_only_is_stale_even_when_its_digest_is_current(run):
    """Round 6 M-12: `receipts --only comms` replaced the full table, and the report called it current because only the digest was compared."""
    write_receipts(report.RECEIPTS, MODEL_ROWS)
    meta = report.RECEIPTS.with_name(report.META_NAME)
    m, plan = pm_run.make_run(run, code_digest=DIGEST)
    report.write(run, m, plan)
    assert load(run)["vehicles"]["glider_eq"]["physics"]["status"] == "ok"
    meta.write_text(json.dumps(dict(code_digest=DIGEST, only=["comms"])))
    report.write(run, m, plan)
    p = load(run)["vehicles"]["glider_eq"]["physics"]
    assert p["status"] == report.STALE and "made with --only comms" in p["reason"] and "passed" not in p
    meta.write_text(json.dumps(dict(code_digest=DIGEST, only=None)))                                    # a full table (and an older meta file without the key)
    report.write(run, m, plan)
    assert load(run)["vehicles"]["glider_eq"]["physics"]["status"] == "ok"


def test_a_what_if_candidate_prints_its_interval_and_is_flagged_when_it_contains_the_baseline(run):
    """Round 6 M-13: 9 of 32 (0.28) was listed beside a baseline of 15 of 64 (0.23) as if it were an evaluated change."""
    m, plan = pm_run.make_run(run)
    f = json.loads((run / "emulator" / "flip.json").read_text())
    usv = f["vehicles"]["usv"]
    usv["p_fail"] = 15 / 64
    usv["tried"] = [dict(change="deploy 6 h later", mod=dict(shift_h=6.0), cost=1.0, method="Stage 1", reason="", p_fail=9 / 32, lo=0.1716, hi=0.425,
                         verdict="MARGINAL", n=32),
                    dict(change="deploy 12 h later", mod=dict(shift_h=12.0), cost=2.0, method="Stage 1", reason="", p_fail=0.0, lo=0.0, hi=0.0889,
                         verdict="GO", n=32)]
    usv.update(found=True, best=usv["tried"][0])
    (run / "emulator" / "flip.json").write_text(json.dumps(f))
    report.write(run, m, plan)
    rep, h = load(run), (run / "report" / "index.html").read_text()
    a, b = rep["vehicles"]["usv"]["fix"]["tried"]
    assert a["same_as_baseline"] is True and b["same_as_baseline"] is False
    rows = [plain(r) for r in re.findall(r"<tr><td>deploy (?:6|12) h later.*?</tr>", h)]
    assert "(0.172 to 0.425)" in rows[0] and "not distinguishable from the baseline" in rows[0]
    assert "(0 to 0.0889)" in rows[1] and "not distinguishable" not in rows[1]
    assert "MARGINAL (Stage 1, n = 32 members); not distinguishable from the baseline" in plain(h)               # the 'best' line says it too
    assert report.check_traceability(rep) == [] and report.check_rendered(rep, h) == []


def test_the_machine_block_shows_the_stage_1b_sensitivity_case_seconds_it_charged_to_no_share(run):
    """Round 6 M-17: stage 1b took 30 s of which the report said nothing; its ledger now carries `sensitivity_wall_s` and the block prints it."""
    m, plan = pm_run.make_run(run)
    report.write(run, m, plan)
    assert "stage1b_sensitivity" not in load(run)["machine"]["timing"] and "sensitivity case (the USV again" not in (run / "report" / "index.html").read_text()
    edit_json(run / "checkpoints" / "stage1b" / "ledger.json", lambda d: d.update(sensitivity_wall_s=30.014))
    report.write(run, m, plan)
    rep, h = load(run), (run / "report" / "index.html").read_text()
    sv = rep["machine"]["timing"]["stage1b_sensitivity"]["measured"]
    assert sv["value"] == 30.014 and sv["stage"] == "stage1b"
    assert "Stage 1b sensitivity case (the USV again under the brief's VPP bias): planned none, it is charged to no share; measured 30.01 s" in plain(h)
    assert rep["traceability_problems"] == [] and report.check_rendered(rep, h) == []


# ---- review round 7, M-16 and M-20: the mode text for a missing insolation and for a wind above the polar
def test_r7_m16_m20_the_page_names_a_missing_insolation_and_a_wind_above_the_polar(run):
    m, plan = pm_run.make_run(run)
    edit_json(run / "stage1b" / "summary.json", lambda d: d["summary"]["vehicles"]["usv"].update(modes=dict(no_current_data=4, capsize_proxy=2)))
    report.write(run, m, plan)
    rep, t = load(run), plain((run / "report" / "index.html").read_text())
    notes = rep["vehicles"]["usv"]["mode_notes"]
    assert notes == dict(no_current_data=report.MODE_TEXT["no_current_data"], capsize_proxy=report.MODE_TEXT["capsize_proxy"])
    assert "no finite insolation" in notes["no_current_data"] and "above the polar's top (30 m/s: outside the model, counted as a failure, not a pass)" in t
    assert "there was no finite wind, current or wave state at the vehicle's position" in t                         # round 4's wording is kept


class _Gated(AnalyticEnv):
    """Data only where `keep(lon)`; like GriddedEnv, a query of a point outside it raises OutsideData (round 7, M-11)."""
    keep = staticmethod(lambda lon: lon > 0)

    def inside(self, lon, lat, t=None):
        return self.keep(np.asarray(lon, float))

    def _chk(self, lon):
        from cafe.pm.env.environment import OutsideData
        if not self.keep(np.asarray(lon, float)).all():
            raise OutsideData("outside the ingested data")

    def wind(self, lon, lat, z, t):
        self._chk(lon)
        return super().wind(lon, lat, z, t)

    def waves(self, lon, lat, t):
        self._chk(lon)
        return super().waves(lon, lat, t)

    def current(self, lon, lat, z, t):
        self._chk(lon)
        return super().current(lon, lat, z, t)


def test_the_environment_section_drops_track_points_outside_the_data_and_never_fails_the_report(run):      # round 7, M-11
    class Nowhere(_Gated):
        keep = staticmethod(lambda lon: lon < 0)                                              # the median tracks are on 0..360: 190 and 195
    rep, h = reach_report(run, Nowhere(current=(0.1, 0.0)))
    vs = rep["environment"]["vehicles"]
    assert vs and all(v["available"] is False and "track points are outside the downloaded data" in v["reason"] and "not shown" in v["reason"]
                      for v in vs.values())
    assert "track points are outside the downloaded data" in h and report.check_traceability(rep) == []


def test_the_environment_section_keeps_the_track_points_inside_the_data(run):
    class Half(_Gated):
        keep = staticmethod(lambda lon: lon < 192.5)                                          # glider_eq (190 E) is inside, usv and uas (195 E) are outside
    rep, h = reach_report(run, Half(current=(0.1, 0.0)))
    vs = rep["environment"]["vehicles"]
    assert vs["glider_eq"]["available"] is True and vs["glider_eq"]["dropped"] is None and len(vs["glider_eq"]["wind10"]["values"]) > 0
    assert any(v["available"] is False for k, v in vs.items() if k != "glider_eq")
    assert report.check_traceability(rep) == []


def test_the_environment_section_reports_a_failing_environment_instead_of_failing_the_report(run):
    class Broken(AnalyticEnv):
        def waves(self, lon, lat, t):
            raise RuntimeError("store unreadable")
    rep, _ = reach_report(run, Broken(current=(0.1, 0.0)))
    assert all(v["available"] is False and "RuntimeError: store unreadable" in v["reason"] for v in rep["environment"]["vehicles"].values())


def test_every_verdict_and_link_card_says_what_its_interval_holds(full):      # round 7, M-21
    run, _, _, _, rep = full
    t = plain((run / "report" / "index.html").read_text())
    n_cards = len(rep["vehicles"]) + len(rep["links"])
    assert t.count("is the sampling error of") == n_cards and n_cards >= 7
    assert "at fixed inputs: the fitted priors enter as their point values and the other assumed inputs are not varied beyond their stated priors" in t


def test_the_usv_card_says_the_speed_factor_is_sampled_over_its_range_only_when_the_brief_case_is_stored(run):      # round 7, M-15; round 8, M-20
    m, plan = pm_run.make_run(run)
    report.write(run, m, plan)
    t = plain((run / "report" / "index.html").read_text())
    assert "speed factor is sampled within" not in t
    cases = dict(usv=[dict(case="usv_vpp_bias uniform [-0.35, -0.3] (usv_vpp_bias_brief)", k_fail=30, n=32, verdict="NO-GO", note="brief")],
                 uas=[dict(case="usv_vpp_bias uniform [-0.35, -0.3] (usv_vpp_bias_brief)", k_fail=1, n=32, verdict="GO", note="not a usv")])
    (run / "stage1b" / report.SENSITIVITY).write_text(json.dumps(cases))
    report.write(run, m, plan)
    h = (run / "report" / "index.html").read_text()
    t = plain(h)
    assert t.count("speed factor is sampled within +-1.4 % of the unbiased polar speed (range 2.9 %, sd 0.8 %; +-1.9 % of the speed flown)") == 1
    assert "not an uncertainty of this model); the brief's bias case gives 30 members of 32 members (NO-GO)" in t
    assert report.check_rendered(load(run), h) == [] and load(run)["traceability_problems"] == []


def test_the_rendered_report_repeats_no_noun_and_has_no_unit_doubled_by_its_sentence(full, run):      # round 7, M-41
    t = plain((run / "report" / "index.html").read_text())
    assert re.findall(r"\b([A-Za-z]+) \1\b", t) == [] and "inputs assumed platform" not in t and "inputs inputs" not in t


def test_a_track_half_inside_the_data_keeps_its_inside_points_and_says_how_many_were_dropped(run):      # round 7, M-11
    class Parity(AnalyticEnv):
        def inside(self, lon, lat, t=None):
            return np.arange(np.asarray(lon).size) % 2 == 0
    rep, h = reach_report(run, Parity(current=(0.1, 0.0)))
    d = rep["environment"]["vehicles"]["glider_eq"]
    assert d["available"] is True and len(d["wind10"]["values"]) == len(d["t"]["values"]) > 0
    assert re.fullmatch(r"\d+ of \d+ track points are outside the downloaded data \(more than half of the members left it\): not shown", d["dropped"])
    assert d["dropped"].split(" of ")[0] != "0" and "track points are outside the downloaded data" in plain(h)
    assert report.check_traceability(rep) == []


# ---------------------------------------------------------------------------------------------------------- round 8 (K batch)

@pytest.fixture
def default_thresholds():
    yield
    intervals.set_thresholds(0.9, 0.6)                                       # the module state load_mission sets: restore the demo's


@pytest.mark.parametrize("go,clause", [(0.99, True), (0.9, True), (0.7, False)])
def test_r8_m7_the_rule_sentence_says_when_the_interval_term_is_looser_than_one_minus_go(run, default_thresholds, go, clause):
    m, plan = pm_run.make_run(run)                                                          # (it loads the demo mission, which sets the thresholds)
    intervals.set_thresholds(go, 0.5)
    report.write(run, m, plan)
    t = plain((run / "report" / "index.html").read_text())
    assert ("is at most 0.25 (looser than 1 - go); NO-GO" in t) is clause and ("(looser than 1 - go)" in t) is clause


def test_r8_m47_a_count_of_one_is_not_pluralised(full):
    run = full[0]
    t = plain((run / "report" / "index.html").read_text())
    assert re.findall(r"\b1 (candidates|notches|members)\b", t) == []
    n = lambda v, u: dict(value=v, unit=u, utc=None)
    assert report._txt(n(1, "notches")) == "1 notch" and report._txt(n(2, "notches")) == "2 notches" and report._txt(n(1, "candidates")) == "1 candidate"
    assert report._txt(n(1, "members")) == "1 member" and report._txt(n(1.0, "m/s")) == "1 m/s" and report._txt(n(0, "members")) == "0 members"
    assert report._txt(n(True, "members")) == "True members"
    assert [report._txt(n(1, u)) for u in ("fraction", "-", "")] == ["1", "1", "1"]                  # a unit that is not shown is not rebuilt for 1
    assert [report._txt(n(2, u)) for u in ("fraction", "-", "")] == ["2", "2", "2"]


RUN_FILES = ["stage1b/summary.json", "refit/refit.json", "stage3/windows.json", "windows/windows.json", "emulator/flip.json", "emulator/holdout.json"]


@pytest.mark.parametrize("rel", RUN_FILES)
def test_r8_m22_a_truncated_run_file_is_a_config_error_naming_it(run, rel):
    m, plan = pm_run.make_run(run)
    report.write(run, m, plan)                                                                # a finished run
    p = run / rel
    p.write_text('{"a": 1, "b')
    with pytest.raises(config.ConfigError, match=rf"{p.name}: not a JSON object .*run it again \(--fresh\)"):
        report.write(run, m, plan)


def test_r8_m22_a_run_file_that_is_json_but_not_an_object_is_refused_too(run):
    m, plan = pm_run.make_run(run)
    (run / "stage1b" / "summary.json").write_text("[]")
    with pytest.raises(config.ConfigError, match=r"summary.json: not a JSON object \(it holds list\)"):
        report.write(run, m, plan)


def test_r8_m22_build_reads_the_credibility_file_through_the_checked_reader(run):
    m, plan = pm_run.make_run(run)
    report.write(run, m, plan)                                                                # a finished run
    p = run / "report" / "credibility.json"
    p.write_text('{"a": 1, "b')                                                               # write() rewrites it before build() reads it: call build
    with pytest.raises(config.ConfigError, match=r"credibility.json: not a JSON object .*run it again \(--fresh\)"):
        report.build(run, m, plan)


def test_r8_m47_a_single_candidate_is_all_1_candidate(run):
    m, plan = pm_run.make_run(run)
    f = json.loads((run / "emulator" / "flip.json").read_text())
    usv = f["vehicles"]["usv"]
    usv["tried"] = usv["tried"][:1]
    usv.update(found=False, best=None)
    (run / "emulator" / "flip.json").write_text(json.dumps(f))
    report.write(run, m, plan)
    t = plain((run / "report" / "index.html").read_text())
    assert "All 1 candidate:" in t and "All 1 candidates" not in t


# ---- review round 8, M-14: the mode text covers both vehicle classes and says it is the input, not the flight model
def test_r8_m14_the_no_current_data_text_says_a_hole_in_the_input_not_a_flight_model_failure():
    text = report.MODE_TEXT["no_current_data"]
    assert "no finite wind, current or wave state" in text and "not a failure of the vehicle's flight model" in text


# ---- review round 8, lead item L0: a number node prints its own unit

def test_r8_l0_a_sentence_after_a_number_node_does_not_repeat_the_unit_the_node_prints():
    ref = dict(stage="stage1b", ledger="checkpoints/stage1b/ledger.json", receipt="stage1b:config:x")
    first = dict(left_data=np.array([1.7e9] * 12))
    for n in (12, 1):
        e = dict(k_fail=n, modes=dict(left_data=n))
        h = plain(report._drivers_html(dict(report._drivers(e, dict(vehicles=dict(g=dict(first=first))), "g", ref, "src"), first_fail_mode="left_data")))
        want = "1 member left the downloaded data" if n == 1 else "12 members left the downloaded data"
        assert want in h and "members members" not in h and "member members" not in h, h


@pytest.mark.parametrize("rows,want", [(140, "140 rows of this scope"), (1, "1 row of this scope")])
def test_r8_l0_the_emulator_acceptance_line_says_rows_once(run, rows, want):
    m, plan = pm_run.make_run(run)
    h = json.loads((run / "emulator" / "holdout.json").read_text())
    h["glider_eq"].update(cls="glider", scope="glider/seaglider/144h", rows=rows, query_ms=1.5, noise_floor_rmse=0.07, rmse_debiased=0.03,
                          acceptance=dict(rmse_ok=True, coverage_ok=True, query_ok=True))
    (run / "emulator" / "holdout.json").write_text(json.dumps(h))
    report.write(run, m, plan)
    t = plain((run / "report" / "index.html").read_text())
    assert want in t and "rows rows" not in t and "row rows" not in t


def test_r10_m1_a_holdout_file_without_scopes_still_reads_per_class_and_a_plan_without_scopes_counts_per_class(run):
    """Round 10 M-1: runs made before emulator scopes pooled by class; their files say class, and say nothing of a scope that was not there."""
    m, plan = pm_run.make_run(run)
    h = json.loads((run / "emulator" / "holdout.json").read_text())
    h["glider_eq"].update(cls="glider", rows=140, query_ms=1.5, noise_floor_rmse=0.07, rmse_debiased=0.03,
                          acceptance=dict(rmse_ok=True, coverage_ok=True, query_ok=True))
    h["glider_eq"].pop("scope", None)
    (run / "emulator" / "holdout.json").write_text(json.dumps(h))
    report.write(run, m, plan)
    t = plain((run / "report" / "index.html").read_text())
    assert "(glider emulator)" in t and "140 rows of this class" in t and "of this scope" not in t
    _design(run, planned_variants=2, variants=[dict(variant=f"v{i}", mods={}, vehicles=[], skipped={}) for i in range(2)], skipped=[], killed=None)
    old = dict(plan, vehicle_scopes=None)
    cls = list(plan["vehicle_classes"].values())
    note = report._run_note(json.loads((run / "emulator" / "design.json").read_text()), old)
    assert f"{3 * min(map(cls.count, set(cls)))} points in the smallest emulator scope" in note


def test_r8_l0_every_unit_a_count_of_one_can_carry_is_singular_and_the_rest_are_left_alone():
    n = lambda v, u: dict(value=v, unit=u, utc=None)
    plural = {"candidates": "candidate", "notches": "notch", "members": "member", "rows": "row", "runs": "run", "receipts": "receipt", "inputs": "input",
              "samples": "sample", "cores": "core", "held-out points": "held-out point"}
    for u, s in plural.items():
        assert report._txt(n(1, u)) == f"1 {s}" and report._txt(n(2, u)) == f"2 {u}" and report._txt(n(1.0, u)) == f"1 {s}", u
    others = ["s", "ms", "min", "h", "km", "dB", "m/s", "s/member/day", "s/batch/day", "cell-updates/s", "z-scored", "fraction of variance",
              "fraction of the failed members", "cells per boundary-layer thickness", "s since 1970-01-01T00:00:00Z"]
    for u in others:
        assert report._txt(n(1, u)) == f"1 {u}", u
    assert report._txt(dict(values=[[1, 2]], unit="deg", utc=None)) == "1 value deg" and report._txt(dict(values=[1, 2], unit="-", utc=None)) == "2 values"
    # every unit a number node is built with in the code: either one of the above or no plural noun at all
    import pathlib
    units = set()
    for f in (pathlib.Path(report.__file__).parent).rglob("*.py"):
        units |= set(re.findall(r"\bnum\([^,()]+(?:\([^()]*\))?[^,()]*, *\"([^\"]*)\"", f.read_text()))
    assert units, "the scan found no number node"
    for u in units:
        assert u in plural or u in others or u in ("", "-", "fraction", "dB") or report._singular(u) == u, u


# ---------------------------------------------------------------------------------------------------------- review round 9, batch B

def _not_exercised(run, lid="usv-uas-rf"):
    """The stage-1b summary of a link required at no moment, as stage1.summarize now writes it: the verdict NOT EXERCISED over the same numbers."""
    def go(d):
        e = d["summary"]["links"][lid]
        e.update(need_count_median=0, granularity_ok=False, verdict=dict(e["verdict"], verdict=stage1.NOT_EXERCISED, note=stage1.NOT_EXERCISED_NOTE))
    edit_json(run / "stage1b" / "summary.json", go)


def test_r9_m17_a_not_exercised_link_is_badged_once_in_the_table_and_the_card_and_is_neither_undecided_nor_certifiable(run):
    """M-17: the stage-1 verdict NOT EXERCISED is read by the badge (own class), the undecided logic, the card text and the sanity row, not shown as GO."""
    m, plan = pm_run.make_run(run)
    _not_exercised(run)
    report.write(run, m, plan)
    rep, h = load(run), (run / "report" / "index.html").read_text()
    k = rep["links"]["usv-uas-rf"]
    assert k["verdict"] == "NOT EXERCISED" and k["decided"] is True and k["region"] is None and k["undecided_statement"] is None
    assert k["certify_statement"] is None and "counts nothing" in k["note"]
    assert k["p_fail"]["value"] == 0.0                                             # the stored number is kept, only its reading changes
    row = h[h.index("<a href='#v-usv-uas-rf'>"):].split("</tr>")[0]
    card = h.split("<div id='v-usv-uas-rf'>")[1].split("<div id='v-")[0]
    for part in (row, card):
        assert part.count('<span class="badge notexercised">NOT EXERCISED</span>') == 1
        assert "undecided" not in part and ">GO<" not in part                                    # no second badge for what the verdict already says
    assert "the verdict is NOT EXERCISED, not GO" in plain(card) and "cannot be certified" not in plain(card)
    sn = next(r for r in rep["sanity"]["rows"] if r["id"] == "usv-uas-rf")
    assert sn["observed"] == "NOT EXERCISED" and sn["agrees"] is None and "required at no moment" in sn["detail"]
    assert ".notexercised{" in h or ".notexercised," in h
    assert rep["links"]["glider_eq-ship-acoustic"]["verdict"] != "NOT EXERCISED" and rep["vehicles"]["usv"]["verdict"] != "NOT EXERCISED"
    assert rep["traceability_problems"] == [] and report.check_rendered(rep, h) == []


def test_a_not_exercised_links_card_has_no_certifying_sentence_and_the_other_cards_keep_theirs(run):
    """DECISIONS 526: n_certify is not a target for a NOT EXERCISED link, and `_stat` withholds its certify_statement; the card still said 'certifying P(fail)
    < 5 % needs 73 members'. The number is not in the report.json of such a link either, so that `check_rendered` does not ask the page for it."""
    m, plan = pm_run.make_run(run)
    _not_exercised(run)
    report.write(run, m, plan)
    rep, h = load(run), (run / "report" / "index.html").read_text()
    card = plain(h.split("<div id='v-usv-uas-rf'>")[1].split("<div id='v-")[0])
    assert "certifying" not in card and "Wilson bound)" not in card and re.search(r"\d+ members failed of \d+ members\.", card)   # ends after n
    assert rep["links"]["usv-uas-rf"]["n_certify"] is None
    other = plain(h.split("<div id='v-glider_eq-ship-acoustic'>")[1].split("<div id='v-")[0])
    assert f"certifying P(fail) < 5 % needs {intervals.n_certify()} members, two-sided 95 % Wilson bound)" in other
    assert rep["links"]["glider_eq-ship-acoustic"]["n_certify"]["value"] == intervals.n_certify()
    assert rep["traceability_problems"] == [] and report.check_traceability(rep) == [] and report.check_rendered(rep, h) == []


def test_r9_m17_a_link_with_a_median_need_of_zero_but_failures_keeps_its_graded_verdict_and_the_card_does_not_call_it_not_exercised(run):
    """Adversary: 10 of 24 members need the link and fail, 14 never do (median need 0). The card must not say NOT EXERCISED for it."""
    m, plan = pm_run.make_run(run)
    set_link_fields(run, **{"usv-uas-rf": dict(need_count_median=0, granularity_ok=False)})
    edit_json(run / "stage1b" / "summary.json", lambda d: d["summary"]["links"]["usv-uas-rf"].update(verdict=dict(
        d["summary"]["links"]["usv-uas-rf"]["verdict"], verdict="NO-GO")))
    report.write(run, m, plan)
    card = plain((run / "report" / "index.html").read_text().split("<div id='v-usv-uas-rf'>")[1].split("<div id='v-")[0])
    assert "Required at no moment in the median member (0 samples): the link was not exercised in it" in card
    assert "graded on the outcomes of all members" in card and "NOT EXERCISED" not in card and "counts nothing" not in card


def test_r9_m17_the_credibility_page_reads_the_not_exercised_verdict_as_cannot_be_checked_not_as_a_disagreement(run):
    m, plan = pm_run.make_run(run)
    _not_exercised(run, "usv-shore-iridium")
    row = next(r for r in credibility_mod.build(run, credibility_mod.ROOT)["sanity"]["rows"] if r["id"] == "usv-shore-iridium")
    assert row["observed"] == "NOT EXERCISED" and row["agrees"] is None and "required at no moment" in row["detail"]


def test_r9_m21_the_reach_caption_names_the_24_h_not_the_horizon_and_says_nothing_when_no_reach_is_drawn(run):
    rep, h = reach_report(run, AnalyticEnv(current=(0.3, 0.0)))
    t = plain(h)
    assert "where the vehicle can get to within 24 h of the deploy, in the currents at the deploy time)" in t and "within the horizon" not in t
    rep, h = reach_report(run.parent / "noenv", None)
    assert "Shaded dashed outline" not in plain(h) and "the horizon" not in plain(h)


def test_r9_m14_a_vehicle_no_member_failed_says_so_instead_of_none(run):
    m, plan = pm_run.make_run(run)
    report.write(run, m, plan)
    rep, t = load(run), plain((run / "report" / "index.html").read_text())
    assert rep["vehicles"]["glider_2n"]["dominant_mode"] is None                                       # the stored value stays None
    assert "Dominant failure mode: none (no member failed)" in t and "Dominant failure mode: None" not in t
    assert "Dominant failure mode: station_lost" in t                                                  # a vehicle with failures is as before


def test_r9_m7_the_usv_speed_ratio_is_compared_with_chiodi_at_the_anemometer_height_and_the_10_m_ratio_is_secondary(run):
    m, plan = pm_run.make_run(run)
    edit_json(run / "stage1b" / "summary.json", lambda d: d["summary"]["vehicles"]["usv"].update(
        speed=dict(ratio_median=0.129, ratio_anem_median=0.135, sog_ms_median=0.55, u10_ms_median=5.1, calibration_ratio=0.96 / 5.4)))
    report.write(run, m, plan)
    rep, t = load(run), plain((run / "report" / "index.html").read_text())
    s = rep["vehicles"]["usv"]["speed_ratio"]
    assert (s["ratio"]["value"], s["ratio_anem"]["value"]) == (0.129, 0.135) and s["ratio_anem"]["source"].endswith("speed.ratio_anem_median")
    assert ("Speed over ground / mean wind at the anemometer height along the track (the height of Chiodi et al.'s wind): median of the per-member ratios "
            "0.135; on the 10 m wind 0.129; median speed over ground 0.55 m/s over median 10 m wind 5.1 m/s") in t
    assert "This summary has no ratio at the anemometer height" not in t
    row = next(r for r in rep["sanity"]["rows"] if r["id"] == "usv")
    assert "wind at the anemometer height along the track 0.135" in row["detail"] and "0.129 on the 10 m wind" in row["detail"] and "0.178" in row["detail"]
    assert rep["traceability_problems"] == [] and report.check_rendered(rep, (run / "report" / "index.html").read_text()) == []
    run2 = run.parent / "older"                                                                        # a summary from before round 9: the 10 m ratio, labelled
    m, plan = pm_run.make_run(run2)
    edit_json(run2 / "stage1b" / "summary.json",
              lambda d: d["summary"]["vehicles"]["usv"].update(speed=dict(ratio_median=0.129, sog_ms_median=0.55, u10_ms_median=5.1)))
    report.write(run2, m, plan)
    rep, t = load(run2), plain((run2 / "report" / "index.html").read_text())
    assert rep["vehicles"]["usv"]["speed_ratio"]["ratio_anem"] is None and "median of the per-member ratios 0.129; median speed over ground" in t
    assert "This summary has no ratio at the anemometer height, so the 10 m ratio is shown against Chiodi's" in t
    assert "no ratio at the anemometer height in this summary" in next(r for r in rep["sanity"]["rows"] if r["id"] == "usv")["detail"]


def _design(run, **kw):
    p = run / "emulator" / "design.json"
    edit_json(p, lambda d: d.update(kw))


def test_r9_m10_the_emulator_section_says_what_ran_beside_what_was_planned(run):
    """M-10: the plan said 7 points per class; the run was cut after 4 of 6 variants. Both are printed, the plan labelled, and the plan field is untouched."""
    m, plan = pm_run.make_run(run)
    note = budget.emulator_plan(plan)["note"]
    why = "killed: the variant runs spent the emulator stage's whole wall-clock share (120 s) before variant v4 of 6"
    _design(run, planned_variants=6, variants=[dict(variant=f"v{i}", mods={}, vehicles=[], skipped={}) for i in range(4)],
            skipped=[dict(variant="v1", vehicle="usv", reason="x")], killed=dict(at_variant=4, planned=6, reason=why))
    report.write(run, m, plan)
    rep, t = load(run), plain((run / "report" / "index.html").read_text())
    e = rep["emulator"]
    cls = plan["vehicle_scopes"]
    smallest = min(5 * n - (1 if k.startswith("usv") else 0) for k, n in ((c, list(cls.values()).count(c)) for c in set(cls.values())))
    assert e["plan_note"] == note
    assert e["run_note"] == (f"4 variant runs of the 6 planned and the base mission, {smallest} points in the smallest emulator scope "
                             f"({budget.EMULATOR_MIN_POINTS} are needed); {why}.")
    assert f"Plan: {note}" in t and f"This run: {e['run_note']}" in t and "7 distinct" not in e["run_note"]
    assert report.check_traceability(rep) == [] and report.check_rendered(rep, (run / "report" / "index.html").read_text()) == []
    assert report._run_note(None, plan) is None
    assert report._run_note(dict(variants=[dict()]), None) == "1 variant run and the base mission."                      # no plan, no planned count, no kill


def test_the_run_note_states_the_points_of_the_smallest_scope_from_the_holdout_file_where_it_holds_them(run):
    """P-29: the note counted (variants + 1) x vehicles of this run, so a shared table that already held rows (the emulator trained on 100 points, or the
    reverse) showed a number that was not the one the emulator saw."""
    m, plan = pm_run.make_run(run)
    _design(run, planned_variants=2, variants=[dict(variant=f"v{i}", mods={}, vehicles=[], skipped={}) for i in range(2)], skipped=[], killed=None)
    cls = list(plan["vehicle_scopes"].values())
    own = report._run_note(json.loads((run / "emulator" / "design.json").read_text()), plan)
    assert own == (f"2 variant runs of the 2 planned and the base mission, {3 * min(map(cls.count, set(cls)))} points in the smallest emulator scope "
                   f"({budget.EMULATOR_MIN_POINTS} are needed).")      # this run's own: (2 + 1) x the vehicles of the scope
    edit_json(run / "emulator" / "holdout.json", lambda d: (d["glider_eq"].update(points=131, cls="glider"), d["usv"].update(points=87, cls="usv")))
    report.write(run, m, plan)
    rep, t = load(run), plain((run / "report" / "index.html").read_text())
    want = f"2 variant runs of the 2 planned and the base mission, 87 points in the smallest emulator scope ({budget.EMULATOR_MIN_POINTS} are needed)."
    assert rep["emulator"]["run_note"] == want and f"This run: {want}" in t
    edit_json(run / "emulator" / "holdout.json", lambda d: d["usv"].pop("points"))    # an older file, or no points for a class: this run's own
    report.write(run, m, plan)
    assert load(run)["emulator"]["run_note"] == own
    design = json.loads((run / "emulator" / "design.json").read_text())
    assert report._run_note(design, None, dict(a=dict(points=5))) == (f"2 variant runs of the 2 planned and the base mission, 5 points in the smallest "
                                                                      f"emulator scope ({budget.EMULATOR_MIN_POINTS} are needed).")


def test_r9_m3_a_uas_no_current_data_mode_gets_the_uas_wording_and_the_other_classes_keep_theirs(run):
    m, plan = pm_run.make_run(run)
    edit_json(run / "stage1b" / "summary.json", lambda d: [d["summary"]["vehicles"][v].update(modes=dict(no_current_data=4)) for v in ("usv", "uas")])
    report.write(run, m, plan)
    rep, t = load(run), plain((run / "report" / "index.html").read_text())
    assert rep["vehicles"]["uas"]["mode_notes"] == dict(no_current_data=report.UAS_MODE_TEXT["no_current_data"])
    assert rep["vehicles"]["usv"]["mode_notes"] == dict(no_current_data=report.MODE_TEXT["no_current_data"])
    assert "the wind at the aircraft's position in flight was not finite" in t and "no finite insolation" in t
    edit_json(run / "stage1b" / "summary.json", lambda d: d["summary"]["vehicles"]["uas"].update(modes=dict(profile_incomplete=4)))
    report.write(run, m, plan)
    assert load(run)["vehicles"]["uas"]["mode_notes"] == dict(profile_incomplete=report.MODE_TEXT["profile_incomplete"])


def test_r9_m1_a_platform_given_as_a_path_is_labelled_counted_and_linked_in_the_report(run, tmp_path):
    """The USV block's source was `platforms/<platform>.yaml` with the whole path spliced in, and its count of assumed inputs and its link to the
    credibility table were looked up under the path (0 and a dead anchor)."""
    m, plan = pm_run.make_run(run)
    f = tmp_path / "mine" / "saildrone_explorer.yaml"
    f.parent.mkdir()
    f.write_text((config.PLATFORMS / "saildrone_explorer.yaml").read_text())
    for doc in (m, mission := yaml.safe_load((run / "mission.yaml").read_text())):
        next(v for v in doc["vehicles"] if v["platform"] == "saildrone_explorer")["platform"] = str(f)
    (run / "mission.yaml").write_text(yaml.safe_dump(mission))
    edit_json(run / "stage1b" / "summary.json", lambda d: d["summary"]["vehicles"]["usv"].update(modes=dict(wing_stall_calm=9)))
    report.write(run, m, plan)
    u = load(run)["vehicles"]["usv"]
    assert u["usv_modes"]["trim_min_aws"]["source"] == f"{f} trim_min_aws_ms"
    assert u["assumed_platform_inputs"]["value"] > 20 and u["assumed_anchor"] == f"credibility.html#{credibility_mod.plat_anchor(str(f))}"
    assert f"id='{credibility_mod.plat_anchor(str(f))}'" in (run / "report" / "credibility.html").read_text()
    inside = config.PLATFORMS / "saildrone_explorer.yaml"                                  # in the repo: the same label however it is given
    assert config.platform_display("saildrone_explorer") == "platforms/saildrone_explorer.yaml" == config.platform_display(str(inside))


def test_r9_m9_the_report_says_when_the_rates_are_another_machines_and_only_in_the_volatile_place(run, monkeypatch):
    """throughput.json measured on another CPU count or model: the machine block now says so (report.json machine.machine, which acceptance.VOLATILE
    leaves out of the comparison of two runs, and one note in the HTML). plan.json and the notes stay free of it: two machines must agree on them. The
    warning is the run's own, read from the ingest ledger (round 9, L0), so the report no longer looks at the host that renders it."""
    m, plan = pm_run.make_run(run)
    ing = run / "checkpoints" / "ingest" / "ledger.json"
    edit_json(ing, lambda d: d["machine"].update(warning="throughput.json was measured on bench (8 CPUs); here it is 32 CPUs, not 8"))
    report.write(run, m, plan)
    rep, h = load(run), (run / "report" / "index.html").read_text()
    assert rep["machine"]["machine"]["warning"] == "throughput.json was measured on bench (8 CPUs); here it is 32 CPUs, not 8"
    assert "<b>Note:</b> throughput.json was measured on bench (8 CPUs); here it is 32 CPUs, not 8." in h
    assert "was measured on bench" not in json.dumps(rep["machine"]["notes"]) + (run / "plan.json").read_text()
    edit_json(ing, lambda d: d["machine"].update(warning=None))
    report.write(run, m, plan)
    quiet = load(run)
    assert quiet["machine"]["machine"]["warning"] is None and "<b>Note:</b>" not in (run / "report" / "index.html").read_text()
    assert "machine.machine" in acceptance.VOLATILE                                       # what two runs of one seed on two machines may differ in


def test_l0_the_report_names_the_machine_the_run_was_on_not_the_one_that_renders_it(run, monkeypatch):
    """Round 9, M-9 sibling: `report --run` on a machine other than the run's compared throughput.json with the renderer: a run made on the benchmarked
    box got 'here it is 32 CPUs' when re-rendered on a bigger one, and a run made on another box lost its warning when re-rendered on the benchmarked one."""
    m, plan = pm_run.make_run(run)
    ing = run / "checkpoints" / "ingest" / "ledger.json"
    monkeypatch.setattr(budget, "machine_warning", lambda *a, **k: "THIS HOST IS NOT THE BENCH")           # what the rendering host would say
    edit_json(ing, lambda d: d["machine"].update(warning=None))                                          # the run itself matched its bench
    report.write(run, m, plan)
    assert load(run)["machine"]["machine"]["warning"] is None and "THIS HOST" not in (run / "report" / "index.html").read_text()
    monkeypatch.setattr(budget, "machine_warning", lambda *a, **k: None)                                 # the rendering host matches the bench
    edit_json(ing, lambda d: d["machine"].update(warning="the run was on another machine"))
    report.write(run, m, plan)
    assert load(run)["machine"]["machine"]["warning"] == "the run was on another machine"
    edit_json(ing, lambda d: d["machine"].pop("warning"))                                                # a ledger from before the field: unknown, not a guess
    report.write(run, m, plan)
    assert load(run)["machine"]["machine"]["warning"] is None


def pm_run_page(run, m, plan, **uas_edit):
    edit_json(run / "stage1b" / "summary.json", lambda d: d["summary"]["vehicles"]["uas"].update(**uas_edit))
    report.write(run, m, plan)
    return (run / "report" / "index.html").read_text()


class NanWind(AnalyticEnv):
    """A masked wind store everywhere but within 100 m of the ship at (-165, 0): the launch check at the ship passes, the aircraft meets NaN in flight."""

    def wind(self, lon, lat, z, t):
        v = super().wind(lon, lat, z, t)
        far = np.hypot(np.asarray(lon, float) + 165.0, np.asarray(lat, float)) > 0.001
        return type(v)(np.where(far[..., None], np.nan, np.asarray(v.value, float)), v.source, v.uncertainty, v.kind)


def test_r9_m3_a_uas_member_that_meets_a_nan_wind_is_no_current_data_from_stage_1_to_the_report(run):
    """The flag existed in the physics, but stage 1 and the report had to carry it: fly two real UAS members in a NaN wind, merge, summarise, put the
    summary in a run and read the page. The mode is counted, is the dominant one, and is explained as a hole in the aircraft's wind (not the sea-mask text of
    the surface vehicles); the attitude note no longer says the verdict rests on the battery and the profile alone."""
    from tests.test_stage1 import uas_inputs
    v, P, mission, t0, T, X = uas_inputs()
    r = stage1._run_uas(v, P, NanWind(), 2, X, t0, T, mission, 1, [0, 1])
    assert r["fail"]["no_current_data"].all() and np.isfinite(r["first"]["no_current_data"]).all()
    res = stage1.merge([dict(U=np.zeros((2, 1)), X={"a": np.zeros(2)}, links={}, vehicles={"uas": dict(r, **{"class": "uas"})})])
    s = stage1.summarize(res, ["a"], mission, 2)["vehicles"]["uas"]
    assert s["modes"]["no_current_data"] == 2 and s["dominant"] == "no_current_data" and s["k_fail"] == 2
    m, plan = pm_run.make_run(run)
    edit_json(run / "stage1b" / "summary.json", lambda d: d["summary"]["vehicles"]["uas"].update(modes=s["modes"], dominant=s["dominant"]))
    report.write(run, m, plan)
    rep, t = load(run), plain((run / "report" / "index.html").read_text())
    u = rep["vehicles"]["uas"]
    assert u["dominant_mode"] == "no_current_data" and u["modes"]["no_current_data"]["value"] == 2
    assert u["mode_notes"]["no_current_data"] == report.UAS_MODE_TEXT["no_current_data"] != report.MODE_TEXT["no_current_data"]
    assert "no_current_data: the wind at the aircraft's position in flight was not finite" in t and "a land block" not in t.split("no_current_data:")[1][:300]
    assert "a hole in the input" in t and report.check_traceability(rep) == []
    assert "In this run 2 members also met a wind that was not finite in flight (no_current_data): their verdict rests on a hole in the input" in t
    quiet = plain(pm_run_page(run, m, plan, modes=dict(s["modes"], no_current_data=0), dominant="profile_incomplete"))
    assert "also met a wind that was not finite" not in quiet and "Attitude exceedance cannot fire" in quiet


def test_l1_the_uas_attitude_statement_is_built_from_the_platform_the_vehicle_flies(run, tmp_path):
    """Cluster 6 sibling: the sentence printed '35 deg', '42 deg' and 'below about 12 m/s' for any UAS platform, so a copy of quad_uas.yaml whose exceedance
    is below its clamp still read 'cannot fire'."""
    m, plan = pm_run.make_run(run)
    f = tmp_path / "mine" / "quad_uas.yaml"
    f.parent.mkdir()
    text = (config.PLATFORMS / "quad_uas.yaml").read_text()
    assert "{value: 42.0," in text and "{value: 12.0, unit: m/s, assumed: true,\n     why: \"operating limit" in text
    f.write_text(text.replace("{value: 42.0,", "{value: 30.0,", 1))
    for doc in (m, mission := yaml.safe_load((run / "mission.yaml").read_text())):
        next(v for v in doc["vehicles"] if v["platform"] == "quad_uas")["platform"] = str(f)
    (run / "mission.yaml").write_text(yaml.safe_dump(mission))
    report.write(run, m, plan)
    rep, t = load(run), plain((run / "report" / "index.html").read_text())
    lim = rep["vehicles"]["uas"]["uas_limits"]
    assert (lim["tilt_clamp"]["value"], lim["tilt_exceedance"]["value"], "max_airspeed" in lim) == (35.0, 30.0, False)           # it can fire: no wind named
    assert lim["tilt_exceedance"]["source"] == f"{f} limits.tilt_exceedance_deg"
    assert "Attitude exceedance can fire in this platform (the tilt clamp, 35 deg, is not below the 30 deg exceedance)" in t and "cannot fire" not in t
    assert rep["traceability_problems"] == [] and report.check_rendered(rep, (run / "report" / "index.html").read_text()) == []
    airspeed = "{value: %s, unit: m/s, assumed: true,\n     why: \"operating"
    f.write_text(text.replace(airspeed % "12.0", airspeed % "9.0", 1))
    edit_json(run / "stage1b" / "summary.json", lambda d: d["summary"]["vehicles"]["uas"].pop("profile", None))
    report.write(run, m, plan)
    assert load(run)["vehicles"]["uas"]["uas_limits"]["max_airspeed"]["value"] == 9.0
    t = plain((run / "report" / "index.html").read_text())
    assert "(the tilt clamp, 35 deg, is below the 42 deg exceedance)" in t and "rests on battery alone below about 9 m/s of wind" in t
    assert report.check_rendered(load(run), (run / "report" / "index.html").read_text()) == [] and load(run)["vehicles"]["usv"]["uas_limits"] is None
