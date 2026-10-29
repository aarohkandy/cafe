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
    assert "no single change among the 3 candidates reaches GO or MARGINAL" in h and "the emulator answered those in its range." in h
    assert "no single change among the 2 candidates reaches GO" in h and "no emulator is trained yet, so only a few were run in Stage 1." in h


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
        e = (top["vehicles"].get(vid) or top["links"][vid])["sensitivity"]["S1"]
        want = sorted(e.items(), key=lambda kv: -kv[1])[:3]
        assert [t["param"] for t in d["top3"]] == [k for k, _ in want] and [t["s1"]["value"] for t in d["top3"]] == [v for _, v in want]
        assert all(t["s1"]["unit"] == "fraction of variance" and t["s1"]["stage"] == "stage1b" for t in d["top3"])
    assert len(rep["vehicles"]["usv"]["top3"]) == 3 and rep["vehicles"]["glider_2n"]["top3"] == []
    h = (run / "report" / "index.html").read_text()
    assert "Top sensitivities (Sobol first-order, share of the variance of failure): <code>" in h and "Top sensitivities: none" in h


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
    assert r["vehicles"]["usv"]["max_range_km"]["value"] > g["max_range_km"]["value"] * 2 and r["vehicles"]["usv"]["speed"]["value"] == 1.4
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
