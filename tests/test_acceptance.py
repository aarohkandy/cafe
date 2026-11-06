"""cafe/pm/acceptance.py (BRIEF 5.3): every check is shown to pass and to fail, and the whole command runs on the CI fixture.

The unit tests build the `run` dicts the checks read from synthetic report.json files, so each failure is exact. The integration fixture runs
`acceptance.run` for real on missions/ci_fixture.yaml over the synthetic CAFE_DATA of tests/fixtures/ci_env: the budget names are monkeypatched
to `ci`, runs go through `cli.main` in this process instead of a child process, the stage-3 LES adapter is the stand-in test_pipeline uses
(ingest, hangar, stage 1, windows, refit, stage 1b, emulator and report are real), and the receipts are stubbed (their own tests cover them).
"""
import contextlib
import copy
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time

import numpy as np
import pytest
import yaml

from cafe.pm import __main__ as cli, acceptance as acc, budget, config, pipeline, receipts
from cafe.pm.env import ocean as ocean_mod
from tests.fixtures.fakes import fake_module
from tests.test_pipeline import Rows, small_budget

ROOT = config.ROOT
RUN_ONE = acc.run_one                                          # (the CI fixture below replaces acc.run_one for the rest of the module)
MISSION = str(ROOT / "missions" / "ci_fixture.yaml")
SHA = "0123456789abcdef0123456789abcdef01234567"


@pytest.fixture(autouse=True)
def committed_clean_checkout(monkeypatch):
    """A golden written here records a commit and a clean tree, as one written from a clean checkout does."""
    monkeypatch.setattr(acc, "git_sha", lambda: SHA)
    monkeypatch.setattr(acc, "_dirty", lambda: False)


# ---------------------------------------------------------------------------------------------------------------- synthetic reports

def stat(verdict, k, n, conf=0.9):
    return dict(verdict=verdict, k_fail=dict(value=k), n=dict(value=n), p_fail=dict(value=k / n, uncertainty=dict(conf=conf)))


def report(seed=7, **over):
    """The part of a report.json the acceptance checks read, plus the run-specific fields they must ignore."""
    r = dict(run="quick", mission=dict(name="m", seed=dict(value=seed)),
             vehicles={"gl": dict(stat("GO", 1, 40), cls="glider", platform="slocum"), "usv": dict(stat("NO-GO", 30, 40), cls="usv", platform="saildrone")},
             links={"rf": stat("MARGINAL", 10, 40)},
             stage3=dict(cpu_fallback=True, label="CPU fallback: XLB-JAX <coarse>", backend="xlb-jax-cpu"),
             machine=dict(wall_s=dict(stage1=12.0), git_sha=["abc"], versions=dict(numpy="2"), machine=dict(host="h", cpus=8), plan=dict(n_max=40)),
             emulator=dict(design=dict(variants=1)),
             receipts=[dict(id="stage1b:output:res.pkl", stage="stage1b", sha256="aa"), dict(id="stage3:output:windows.json", stage="stage3", sha256="bb")])
    r["stage3"]["vehicles"] = dict(gl=[dict(coefficients=dict(cd=1.0))])
    r["stage3"]["refit"] = dict(gl=dict(used=False))
    r["vehicles"]["gl"]["fix"] = dict(found=False)
    r.update(over)
    return r


def run_dict(tmp_path, rep, name="quick", rc=0, wall_s=60.0, limit_s=1200.0, gpus=0, seed=None, label_in_page=True, plan_cpu=None):
    """What acceptance.run_one returns, with plan.json and index.html on disk for the label check."""
    d = tmp_path / name
    (d / "report").mkdir(parents=True, exist_ok=True)
    cpu = gpus == 0 if plan_cpu is None else plan_cpu
    (d / "plan.json").write_text(json.dumps(dict(les=dict(cpu_fallback=cpu))))
    (d / "report" / "index.html").write_text("<p>CPU fallback: XLB-JAX &lt;coarse&gt;</p>" if label_in_page else "<p>nothing</p>")
    if rep is not None:
        (d / "report" / "report.json").write_text(json.dumps(rep))
    return dict(name=name, budget="quick", gpus=gpus, seed=seed, dir=d, log=tmp_path / f"{name}.log", rc=rc, wall_s=wall_s, limit_s=limit_s, report=rep)


# ---------------------------------------------------------------------------------------------------------------- run timing and exit

def test_a_run_that_exits_0_with_a_report_inside_its_limit_passes(tmp_path):
    r = acc.check_run(run_dict(tmp_path, report(), wall_s=600.0))
    assert r["ok"] and r["name"] == "run_quick" and "10.0 min of the 20 min limit" in r["detail"] and r["values"]["wall_s"] == 600.0


def test_a_run_over_its_time_limit_fails_and_says_by_how_much(tmp_path):
    r = acc.check_run(run_dict(tmp_path, report(), wall_s=1300.0))
    assert not r["ok"] and "took 21.7 min, over the 20 min limit of --budget quick" in r["detail"]


def test_a_failed_or_killed_run_fails_with_its_log_and_a_missing_report_fails(tmp_path):
    r = acc.check_run(run_dict(tmp_path, None, rc=1))
    assert not r["ok"] and "exit code 1" in r["detail"] and "quick.log" in r["detail"] and "killed at" not in r["detail"]
    assert "killed at the time limit" in acc.check_run(run_dict(tmp_path, None, rc=124, wall_s=2400.0))["detail"]
    r = acc.check_run(run_dict(tmp_path, None, rc=0))
    assert not r["ok"] and "no report/report.json" in r["detail"]


def test_the_wall_clock_limits_are_the_budgets(monkeypatch, tmp_path):
    out = tmp_path / "o"
    monkeypatch.setattr(acc, "_execute", lambda argv, env, log, timeout: (time.sleep(0.05), 0)[1])
    monkeypatch.setitem(budget.BUDGET_S, "ci", 0.01)
    r = acc.run_one(MISSION, "quick", "ci", 0, out)
    assert r["limit_s"] == 0.01 and r["wall_s"] >= 0.05 and not acc.check_run(r)["ok"]
    assert dict(acc.RUNS) == dict(quick=("quick", 0), overnight=("overnight", 0), gpu=("4h", 1))
    assert [budget.BUDGET_S[b] for b, _ in acc.RUNS.values()] == [20 * 60, 10 * 3600, 4 * 3600]


def test_run_one_starts_clean_names_the_run_and_reads_its_report(monkeypatch, tmp_path):
    out, seen = tmp_path / "o", []
    (out / "quick").mkdir(parents=True)
    (out / acc.MARKER).write_text("")                                                                  # acceptance's own earlier run (M-12 of round 10)
    (out / "quick" / "stale.txt").write_text("from an earlier run")

    def execute(argv, env, log, timeout):
        seen.append((argv, log, timeout))
        if argv[0] == "fetch":
            return 0
        assert [p.name for p in (out / "quick").iterdir()] == ["emulator_table"]                   # the stale file is gone; its own table dir only
        (out / "quick" / "report").mkdir(parents=True)
        (out / "quick" / "report" / "report.json").write_text(json.dumps(report()))
        return 0
    monkeypatch.setattr(acc, "_execute", execute)
    r = acc.run_one(MISSION, "quick", "quick", 0, out, seed=5)
    assert seen[0] == (["fetch", "--mission", MISSION, "--out", str(out / "quick_fetch"), "--fresh"], out / "quick_fetch.log", None)       # M-25: fetch first
    argv, log, timeout = seen[1]
    assert argv == ["run", "--mission", MISSION, "--budget", "quick", "--gpus", "0", "--out", str(out / "quick"), "--fresh", "--seed", "5",
                    "--emulator-table", str(out / "quick" / "emulator_table" / "train.parquet")]
    assert log == out / "quick.log" and timeout == 2 * 1200 and r["report"] == report() and r["rc"] == 0 and r["seed"] == 5
    acc.run_one(MISSION, "quick", "4h", 1, out)
    assert "--seed" not in seen[3][0] and seen[3][0][3:7] == ["--budget", "4h", "--gpus", "1"] and seen[3][2] == 2 * 4 * 3600


def test_execute_runs_the_cli_in_a_child_process_and_kills_it_at_the_timeout(tmp_path):
    assert acc._execute(["validate", "--mission", MISSION], dict(os.environ), tmp_path / "v.log", 300.0) == 0
    assert "ci_fixture" in (tmp_path / "v.log").read_text() and "valid" in (tmp_path / "v.log").read_text()
    assert acc._execute(["validate", "--mission", MISSION], dict(os.environ), tmp_path / "t.log", 0.01) == 124


# ---------------------------------------------------------------------------------------------------------------- the CPU-fallback label

def test_the_overnight_run_on_cpu_must_label_its_les_windows_as_the_fallback(tmp_path):
    r = acc.check_label(run_dict(tmp_path, report(), name="overnight"))
    assert r["ok"] and r["name"] == "cpu_fallback_overnight" and "xlb-jax-cpu" in r["detail"]


def test_a_cpu_run_whose_plan_report_or_page_do_not_say_cpu_fallback_fails(tmp_path):
    bad = acc.check_label(run_dict(tmp_path, report(), name="a", plan_cpu=False))
    assert not bad["ok"] and bad["values"]["plan_cpu_fallback"] is False
    gpu_report = report(stage3=dict(cpu_fallback=False, label="GPU LES windows", backend="xlb-warp"))
    bad = acc.check_label(run_dict(tmp_path, gpu_report, name="b"))
    assert not bad["ok"] and bad["values"]["report_cpu_fallback"] is False and bad["values"]["label_says_cpu"] is False
    bad = acc.check_label(run_dict(tmp_path, report(), name="c", label_in_page=False))
    assert not bad["ok"] and bad["values"]["label_in_page"] is False
    assert "no report" in acc.check_label(run_dict(tmp_path, None, name="d"))["detail"]


def test_a_gpu_run_must_take_the_gpu_path_and_a_cpu_label_there_fails(tmp_path):
    gpu_report = report(stage3=dict(cpu_fallback=False, label="GPU LES windows", backend="xlb-warp"))
    d = run_dict(tmp_path, gpu_report, name="4h", gpus=1, label_in_page=False)
    (d["dir"] / "report" / "index.html").write_text("<p>GPU LES windows</p>")
    r = acc.check_label(d)
    assert r["ok"] and r["name"] == "gpu_path_4h"
    assert not acc.check_label(run_dict(tmp_path, report(), name="4h", gpus=1))["ok"]


# ---------------------------------------------------------------------------------------------------------------- golden diff

def test_the_summary_keeps_verdicts_counts_and_what_the_interval_needs():
    s = acc.summary(report())
    assert s == dict(mission="m", seed=7, vehicles={"gl": dict(verdict="GO", k_fail=1, n=40, p_fail=0.025, conf=0.9, cls="glider", platform="slocum"),
                                                      "usv": dict(verdict="NO-GO", k_fail=30, n=40, p_fail=0.75, conf=0.9, cls="usv", platform="saildrone")},
                     links={"rf": dict(verdict="MARGINAL", k_fail=10, n=40, p_fail=0.25, conf=0.9)})
    assert "machine" not in s and "wall_s" not in json.dumps(s)


def test_the_same_summary_has_no_differences_and_a_p_fail_inside_the_golden_interval_passes():
    g = acc.summary(report())
    assert acc.diff(g, copy.deepcopy(g)) == []
    new = copy.deepcopy(g)
    new["links"]["rf"].update(k_fail=14, p_fail=0.35)                                # 14 of 40 against 10 of 40: Newcombe's interval holds 0
    assert acc.diff(g, new) == []


def test_a_changed_verdict_string_is_a_difference():
    g = acc.summary(report())
    new = copy.deepcopy(g)
    new["vehicles"]["usv"]["verdict"] = "MARGINAL"
    assert acc.diff(g, new) == ["vehicles usv: verdict 'NO-GO' in the reference, 'MARGINAL' now"]


def moved(g, kind, k, k_fail):
    """A deep copy of summary `g` with entry `k` at `k_fail` failures."""
    new = copy.deepcopy(g)
    e = new[kind][k]
    e.update(k_fail=k_fail, p_fail=k_fail / e["n"])
    return new


def test_a_p_fail_whose_difference_interval_excludes_0_is_a_difference():
    g = acc.summary(report())
    (msg,) = acc.diff(g, moved(g, "links", "rf", 30))
    assert msg.startswith("links rf: P(fail) 0.7500 now against 0.2500 in the reference (30 of 40 and 10 of 40)") and "98.33% Newcombe interval" in msg
    assert msg.endswith("excludes 0")
    assert len(acc.diff(g, moved(g, "links", "rf", 0))) == 1


def test_equal_counts_pass_and_the_extremes_all_pass_against_all_fail_do_not():
    g = acc.summary(report(links={"rf": stat("GO", 0, 40)}))
    assert acc.diff(g, copy.deepcopy(g)) == []
    assert len(acc.diff(g, moved(g, "links", "rf", 40))) == 1
    assert len(acc.diff(moved(g, "links", "rf", 40), g)) == 1


def test_the_difference_is_judged_the_same_way_round_either_way():
    g = acc.summary(report())
    for k in range(0, 41):
        assert bool(acc.diff(g, moved(g, "links", "rf", k))) == bool(acc.diff(moved(g, "links", "rf", k), g))


def summ(entries, n=32):
    """A summary with links only: {id: (verdict, k_fail)}."""
    return dict(mission="m", seed=7, vehicles={}, links={i: dict(verdict=v, k_fail=k, n=n, p_fail=k / n, conf=0.9) for i, (v, k) in entries.items()})


def test_4_of_32_against_1_of_32_is_consistent_and_0_of_32_against_16_of_32_is_not():
    assert acc.diff(summ({"uas": ("MARGINAL", 4)}), summ({"uas": ("MARGINAL", 1)})) == []
    verdict, msg = acc.diff(summ({"uas": ("GO", 0)}), summ({"uas": ("MARGINAL", 16)}))
    assert "links uas: P(fail) 0.5000 now against 0.0000 in the reference (16 of 32 and 0 of 32)" in msg and "95.00% Newcombe interval" in msg
    assert "undecided in both, but the 95% intervals on P(fail)" in verdict and "do not overlap" in verdict


def uas_report(verdict, k, seed=7):
    return report(seed=seed, links={}, vehicles={"uas": dict(stat(verdict, k, 32), cls="uas", platform="quad")})


NAMED = "vehicles uas: MARGINAL -> GO, undecided in both at n = 32"


def test_a_verdict_change_that_is_undecided_in_both_runs_passes_and_is_named(tmp_path):
    r = acc.check_other_seed(run_dict(tmp_path, uas_report("MARGINAL", 4)), run_dict(tmp_path, uas_report("GO", 1, seed=8), name="c", seed=8))
    assert r["ok"] and NAMED in r["detail"] and r["values"]["notes"] == [NAMED]
    assert "seed 8" in r["detail"] and "family-wise 95 % over 1 compared" in r["detail"]


def test_the_golden_diff_allows_and_names_the_same_change_and_still_checks_the_rest(tmp_path):
    g = tmp_path / "g.json"
    acc.check_golden(run_dict(tmp_path, uas_report("MARGINAL", 4)), g, MISSION, True)
    ok = acc.check_golden(run_dict(tmp_path, uas_report("GO", 1)), g, MISSION, False)
    assert ok["ok"] and NAMED in ok["detail"] and ok["values"]["notes"] == [NAMED] and ok["values"]["problems"] == []
    bad = acc.check_golden(run_dict(tmp_path, uas_report("NO-GO", 30)), g, MISSION, False)
    assert not bad["ok"] and "P(fail) 0.9375 now against 0.1250" in bad["detail"]


def test_a_verdict_change_fails_when_either_run_has_it_decided():
    decided_go, decided_nogo, undecided = ("GO", 0), ("NO-GO", 30), ("MARGINAL", 1)
    for a, b in ((decided_go, ("MARGINAL", 0)), (("MARGINAL", 0), decided_go), (decided_nogo, ("MARGINAL", 30)), (("MARGINAL", 30), decided_nogo)):
        bad = acc.diff(summ({"x": a}, n=40), summ({"x": b}, n=40))
        assert bad == [f"links x: verdict {a[0]!r} in the reference, {b[0]!r} now"], (a, b)
    assert acc.diff(summ({"x": undecided}, n=40), summ({"x": ("GO", 1)}, n=40)) == []
    # a MARGINAL whose whole interval is between 0.10 and 0.40 (40 of 200) is decided too: it may not turn GO at 30 of 200 (a P(fail) Newcombe accepts)
    (msg,) = acc.diff(summ({"x": ("MARGINAL", 40)}, n=200), summ({"x": ("GO", 30)}, n=200))
    assert msg == "links x: verdict 'MARGINAL' in the reference, 'GO' now"
    assert acc.compare(summ({"x": undecided}, n=40), summ({"x": ("GO", 1)}, n=40)) == ([], ["links x: MARGINAL -> GO, undecided in both at n = 40"])


def test_the_help_text_states_the_comparison_rule(capsys):
    with pytest.raises(SystemExit):
        cli.main(["acceptance", "--help"])
    out = " ".join(capsys.readouterr().out.split())
    assert "Newcombe" in out and "family-wise 95 % (Bonferroni" in out and "undecided in both is allowed and named" in out


def test_the_family_wise_level_is_split_over_the_entries_compared():
    one, four = {"a": ("MARGINAL", 1)}, {k: ("MARGINAL", 1) for k in "abcd"}
    # 8 of 32 against 1 of 32: the lower end of the difference is +0.046 at 95 %, -0.009 at 98.75 %
    new_one, new_four = {"a": ("MARGINAL", 8)}, {k: ("MARGINAL", 8) for k in "abcd"}
    (msg,) = acc.diff(summ(one), summ(new_one))
    assert "95.00% Newcombe interval" in msg
    assert acc.diff(summ(four), summ(new_four)) == []
    assert acc.diff(summ(four), summ({**new_four, "a": ("MARGINAL", 16)})) != []                                   # a bigger move still fails among four
    only_vehicles = acc.summary(report(links={}))
    assert acc._entries(only_vehicles, only_vehicles) == 2 and acc._entries(summ(four), summ(one)) == 1


def test_counts_of_members_vehicles_and_links_class_platform_and_mission_must_match_exactly():
    g = acc.summary(report())
    new = copy.deepcopy(g)
    new["vehicles"]["gl"]["n"] = 41
    new["vehicles"]["gl"]["cls"] = "usv"
    new["vehicles"]["gl"]["platform"] = "other"
    msgs = acc.diff(g, new)
    assert [m.split(":")[0] for m in msgs] == ["vehicles gl"] * 3 and any("n 40" in m for m in msgs) and any("cls" in m for m in msgs)
    gone = copy.deepcopy(g)
    del gone["vehicles"]["usv"]
    gone["links"]["extra"] = gone["links"]["rf"]
    msgs = acc.diff(g, gone)
    assert len(msgs) == 2 and "vehicles: ['gl', 'usv'] in the reference, ['gl'] now" in msgs[0] and msgs[1].startswith("links: ")
    other = copy.deepcopy(g)
    other["mission"], other["seed"] = "x", 8
    assert [m.split(":")[0] for m in acc.diff(g, other)] == ["mission", "seed"]
    assert [m.split(":")[0] for m in acc.diff(g, other, seed=False)] == ["mission"]


def test_a_missing_golden_fails_and_names_the_command_that_writes_it(tmp_path):
    r = acc.check_golden(run_dict(tmp_path, report()), tmp_path / "golden" / "g.json", "missions/tepex_c_demo.yaml", False)
    assert not r["ok"] and r["values"]["missing"] and "no golden file at" in r["detail"]
    assert "python -m cafe.pm acceptance --mission missions/tepex_c_demo.yaml --gpus 0 --update-golden" in r["detail"]
    assert not (tmp_path / "golden").exists()


def test_update_golden_records_the_run_and_the_code_it_came_from_but_never_passes(tmp_path):
    g = tmp_path / "golden" / "g.json"
    r = acc.check_golden(run_dict(tmp_path, report()), g, MISSION, True)
    assert not r["ok"] and r["values"]["updated"] and "UPDATED" in r["detail"] and "not compared" in r["detail"]
    rec = json.loads(g.read_text())
    assert rec["schema"] == 1 and rec["summary"] == acc.summary(report()) and rec["source"]["budget"] == "quick" and rec["source"]["gpus"] == 0
    assert len(rec["source"]["code_digest"]) == 64 and rec["source"]["git_sha"] and rec["source"]["date"].endswith("+00:00")
    assert rec["command"].endswith("--update-golden") and "wall_s" not in g.read_text()


def test_the_golden_it_wrote_passes_and_a_changed_verdict_or_p_fail_then_fails(tmp_path):
    g = tmp_path / "g.json"
    acc.check_golden(run_dict(tmp_path, report()), g, MISSION, True)
    ok = acc.check_golden(run_dict(tmp_path, report(run="other", machine={})), g, MISSION, False)
    assert ok["ok"] and "3 verdicts and P(fail) agree with g.json" in ok["detail"]
    flipped = report(vehicles={"gl": report()["vehicles"]["gl"], "usv": dict(stat("MARGINAL", 30, 40), cls="usv", platform="saildrone")})
    bad = acc.check_golden(run_dict(tmp_path, flipped), g, MISSION, False)
    assert not bad["ok"] and "verdict 'NO-GO' in the reference, 'MARGINAL' now" in bad["detail"]
    shifted = report(links={"rf": stat("MARGINAL", 30, 40)})
    bad = acc.check_golden(run_dict(tmp_path, shifted), g, MISSION, False)
    assert not bad["ok"] and "links rf: P(fail) 0.7500 now against 0.2500" in bad["detail"]


def test_many_golden_problems_are_listed_with_a_count_and_a_run_without_a_report_fails(tmp_path):
    g = tmp_path / "g.json"
    acc.check_golden(run_dict(tmp_path, report()), g, MISSION, True)
    wild = report(vehicles={"gl": dict(stat("NO-GO", 40, 50), cls="usv", platform="x"), "usv": dict(stat("GO", 0, 50), cls="glider", platform="y")},
                  links={"rf": stat("GO", 0, 50)})
    bad = acc.check_golden(run_dict(tmp_path, wild), g, MISSION, False)
    assert not bad["ok"] and "(+" in bad["detail"] and len(bad["values"]["problems"]) > 6
    none = acc.check_golden(run_dict(tmp_path, None), g, MISSION, False)
    assert not none["ok"] and "no report" in none["detail"]


# ---------------------------------------------------------------------------------------------------------------- reproducibility

def test_normalize_removes_the_run_specific_fields_and_the_run_directory_path(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    ra = report(run="a", note=f"see {a}/ledger.json")
    other = dict(wall_s=dict(stage1=99.0), git_sha=["def"], versions={}, machine=dict(host="z"), plan=dict(n_max=40))
    rb = report(run="b", note=f"see {b}/ledger.json", machine=other)
    assert acc.normalize(ra, a) == acc.normalize(rb, b)
    n = acc.normalize(ra, a)
    assert n["machine"] == dict(plan=dict(n_max=40)) and "run" not in n and n["note"] == "see <run>/ledger.json"
    assert "run" in ra and "wall_s" in ra["machine"]                                    # the input is not modified


def test_normalize_drops_only_the_query_time_and_the_run_directory_and_keeps_stage3_the_emulator_and_the_fixes(tmp_path):
    rec = [dict(id="stage1b:output:res.pkl", stage="stage1b", sha256="aa"), dict(id=acc.HOLDOUT, stage="emulator", sha256="cc"),
           dict(id=acc.CREDIBILITY, stage="report", sha256="dd")]
    emu = dict(vehicles=dict(glider=dict(trained=True, acceptance=dict(query_ms=3.0, query_ok=True)), usv=dict(trained=False)))
    n = acc.normalize(report(emulator=emu, receipts=rec), tmp_path)
    assert n["stage3"]["vehicles"] == dict(gl=[dict(coefficients=dict(cd=1.0))]) and n["vehicles"]["gl"]["fix"] == dict(found=False)
    assert n["emulator"]["vehicles"] == dict(glider=dict(trained=True, acceptance=dict(query_ok=True)), usv=dict(trained=False))
    assert n["receipts"] == [rec[0], dict(id=acc.HOLDOUT, stage="emulator"), dict(id=acc.CREDIBILITY, stage="report")]      # no credibility.json here
    assert n["vehicles"]["gl"]["verdict"] == "GO" and n["vehicles"]["usv"]["p_fail"]["value"] == 0.75 and n["links"]["rf"]["verdict"] == "MARGINAL"
    assert acc.normalize(dict(mission={}), tmp_path) == dict(mission={})


def test_normalize_hashes_credibility_json_without_its_run_directory(tmp_path):
    rec = [dict(id=acc.CREDIBILITY, stage="report", sha256="dd")]
    shas = []
    for name, body in (("a", "x"), ("b", "x"), ("c", "y")):
        d = tmp_path / name
        (d / "report").mkdir(parents=True)
        (d / "report" / "credibility.json").write_text(json.dumps(dict(run=name, evidence=f"{d}/ledger.json", text=body)))
        shas.append(acc.normalize(report(receipts=rec), d)["receipts"][0]["sha256"])
    assert shas[0] == shas[1] != shas[2] and len(shas[0]) == 64


def test_every_run_gets_its_own_copy_of_the_pristine_emulator_table(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(acc, "_execute", lambda argv, env, log, timeout: seen.append(argv) or (0 if argv[0] == "fetch" else 1))
    table = tmp_path / "pristine.parquet"
    table.write_bytes(b"rows")
    for name in ("quick", "quick_same"):
        acc.run_one(MISSION, name, "quick", 0, tmp_path / "o", table=table)
    seen[:] = [a for a in seen if a[0] == "run"]
    own = [pathlib.Path(a[a.index("--emulator-table") + 1]) for a in seen]
    assert own[0] != own[1] and all(p.name == "train.parquet" and p.read_bytes() == b"rows" for p in own)
    acc.run_one(MISSION, "quick_seed", "quick", 0, tmp_path / "o")                       # no shared table yet: its own path, empty
    fresh = pathlib.Path(seen[-1][seen[-1].index("--emulator-table") + 1])
    assert fresh.parent.is_dir() and not fresh.exists() and fresh.parent.parent.name == "quick_seed"


def test_identical_reports_pass_the_same_seed_check_and_a_changed_number_fails_it(tmp_path):
    a = run_dict(tmp_path, report(run="a"), name="quick")
    other = dict(wall_s=dict(stage1=99.0), git_sha=["z"], versions={}, machine={}, plan=dict(n_max=40))
    b = run_dict(tmp_path, report(run="b", machine=other), name="quick_same")
    r = acc.check_same_seed(a, b)
    assert r["ok"] and r["values"]["differing"] == 0
    b["report"]["vehicles"]["gl"]["p_fail"]["value"] = 0.026
    r = acc.check_same_seed(a, b)
    assert not r["ok"] and "1 fields differ: vehicles.gl.p_fail.value: 0.025 != 0.026" in r["detail"]


def test_the_delta_names_missing_keys_and_list_lengths():
    assert list(acc._delta(dict(a=1, b=[1, 2]), dict(a=1, b=[1, 2, 3], c=0))) == ["b: [1, 2] != [1, 2, 3]", "c: <absent> != 0"]
    assert list(acc._delta(dict(a=[dict(x=1)]), dict(a=[dict(x=2)]))) == ["a[0].x: 1 != 2"]


def test_same_seed_and_other_seed_fail_without_both_reports(tmp_path):
    a, none = run_dict(tmp_path, report()), run_dict(tmp_path, None, name="x")
    assert not acc.check_same_seed(a, none)["ok"] and not acc.check_same_seed(none, a)["ok"]
    assert not acc.check_other_seed(a, none)["ok"] and not acc.check_other_seed(none, a)["ok"]


def test_a_different_seed_passes_when_verdicts_hold_and_p_fail_stays_in_the_first_runs_interval(tmp_path):
    a = run_dict(tmp_path, report(seed=7))
    near = {"gl": dict(stat("GO", 2, 40), cls="glider", platform="slocum"), "usv": dict(stat("NO-GO", 28, 40), cls="usv", platform="saildrone")}
    c = run_dict(tmp_path, report(seed=8, vehicles=near,
                                  links={"rf": stat("MARGINAL", 12, 40)}), name="quick_seed", seed=8)
    r = acc.check_other_seed(a, c)
    assert r["ok"] and "seed 8" in r["detail"] and "seed 7" in r["detail"]


def test_a_different_seed_fails_when_a_verdict_changes_or_p_fail_leaves_the_interval(tmp_path):
    a = run_dict(tmp_path, report(seed=7))
    changed = {"gl": report()["vehicles"]["gl"], "usv": dict(stat("MARGINAL", 30, 40), cls="usv", platform="saildrone")}
    flipped = run_dict(tmp_path, report(seed=8, vehicles=changed), name="c", seed=8)
    bad = acc.check_other_seed(a, flipped)
    assert not bad["ok"] and "verdict 'NO-GO' in the reference, 'MARGINAL' now" in bad["detail"]
    far = run_dict(tmp_path, report(seed=8, links={"rf": stat("MARGINAL", 30, 40)}), name="d", seed=8)
    bad = acc.check_other_seed(a, far)
    assert not bad["ok"] and "links rf: P(fail) 0.7500 now against 0.2500" in bad["detail"]


# ---------------------------------------------------------------------------------------------------------------- the broken configuration

def fake_receipts(monkeypatch, broken_rows, broken_rc, base_rc=0, calls=None):
    def run(slow=False, only=None, broken=None, out=None, log=print):
        (calls if calls is not None else []).append(dict(only=only, broken=broken, out=out))
        log("receipts table")
        return (broken_rows, broken_rc) if broken else ([], base_rc)
    monkeypatch.setattr(receipts, "run", run)


def row(module, kind="fail", id_="x"):
    return dict(id=id_, module=module, kind=kind)


def test_a_broken_config_that_fails_a_wave_direction_receipt_passes_the_check(monkeypatch, tmp_path):
    calls = []
    fake_receipts(monkeypatch, [row(acc.WAVE_MODULE, id_="pm.env.wave_direction:3"), row("pm.stage3.lbm"), row(acc.WAVE_MODULE, "pass")], 0, calls=calls)
    r = acc.check_broken(tmp_path)
    assert r["ok"] and r["values"]["caught"] == ["pm.env.wave_direction:3"] and "wave_direction.yaml" in r["detail"]
    assert calls[0]["broken"] == acc.BROKEN and calls[0]["out"] == tmp_path / "receipts_broken.json"
    assert calls[1] == dict(only=[acc.WAVE_MODULE], broken=None, out=tmp_path / "receipts_wave_direction.json")
    assert "receipts table" in (tmp_path / "receipts_broken.log").read_text()


def test_a_broken_config_that_fails_no_receipt_fails_the_check(monkeypatch, tmp_path):
    fake_receipts(monkeypatch, [row(acc.WAVE_MODULE, "pass")], 1)
    r = acc.check_broken(tmp_path)
    assert not r["ok"] and r["detail"] == "the broken configuration failed no receipt"


def test_a_failure_elsewhere_cannot_stand_in_for_the_wave_direction_receipts(monkeypatch, tmp_path):
    fake_receipts(monkeypatch, [row("pm.stage3.lbm"), row("pm.dtmb5415")], 0)
    r = acc.check_broken(tmp_path)
    assert not r["ok"] and "no wave-direction receipt failed" in r["detail"]


def test_wave_direction_receipts_that_fail_without_the_broken_config_prove_nothing(monkeypatch, tmp_path):
    fake_receipts(monkeypatch, [row(acc.WAVE_MODULE)], 0, base_rc=1)
    r = acc.check_broken(tmp_path)
    assert not r["ok"] and "even without the broken configuration" in r["detail"]


def test_a_missing_broken_file_fails_the_check(monkeypatch, tmp_path):
    monkeypatch.setattr(acc, "BROKEN", tmp_path / "nope.yaml")
    r = acc.check_broken(tmp_path)
    assert not r["ok"] and "no such file" in r["detail"]


def test_the_real_broken_configuration_fails_a_wave_direction_receipt_and_the_good_one_does_not(monkeypatch, tmp_path):
    real = receipts.run
    monkeypatch.setattr(receipts, "run", lambda *a, **k: real(*a, **dict(k, only=[acc.WAVE_MODULE])))
    r = acc.check_broken(tmp_path)
    assert r["ok"] and r["values"]["exit_code"] == 0 and r["values"]["baseline_exit_code"] == 0 and r["values"]["caught"]


# ---------------------------------------------------------------------------------------------------------------- orchestration

class Fake:
    """acceptance.run_one replaced: records what was run and returns passing synthetic runs (seed + 1 for the other seed)."""

    def __init__(self, tmp_path, monkeypatch, **bad):
        self.calls, self.bad, self.tmp = [], bad, tmp_path
        monkeypatch.setattr(acc, "run_one", self.run_one)
        monkeypatch.setattr(receipts, "run", lambda *a, **k: ([row(acc.WAVE_MODULE)], 0) if k.get("broken") else ([], 0))

    def run_one(self, mission, name, b, g, out, seed=None, table=None):
        self.calls.append((name, b, g, seed))
        gpu = g > 0
        label = "GPU LES windows" if gpu else "CPU fallback: XLB-JAX <coarse>"
        rep = self.bad.get(name, report(seed=seed or 7, stage3=dict(cpu_fallback=not gpu, label=label, backend="b")))
        d = run_dict(self.tmp / name, rep, name=name, gpus=g, seed=seed, limit_s=budget.BUDGET_S[b], wall_s=self.bad.get("wall", 1.0))
        (d["dir"] / "report" / "index.html").write_text(f"<p>{'GPU LES windows' if gpu else 'CPU fallback: XLB-JAX &lt;coarse&gt;'}</p>")
        d["budget"] = b
        return d


def golden_for(tmp_path):
    g = tmp_path / "g.json"
    acc.check_golden(run_dict(tmp_path / "w", report()), g, MISSION, True)
    return g


def test_run_orders_the_runs_and_gives_the_other_seed_plus_one(monkeypatch, tmp_path):
    f, log = Fake(tmp_path, monkeypatch), []
    rows, rc = acc.run(MISSION, 1, tmp_path / "o", golden_for(tmp_path), log=log.append)
    assert f.calls == [("quick", "quick", 0, None), ("quick_same", "quick", 0, None), ("quick_seed", "quick", 0, 20230302),
                       ("overnight", "overnight", 0, None), ("4h", "4h", 1, None)]
    assert [r["name"] for r in rows] == ["run_quick", "golden_diff", "run_quick_same", "same_seed", "run_quick_seed", "other_seed", "broken_config",
                                         "run_overnight", "cpu_fallback_overnight", "run_4h", "gpu_path_4h"]
    assert rc == 0 and all(r["ok"] for r in rows)
    assert log[0] == "run quick: --budget quick --gpus 0, limit 20 min" and "run quick_seed: --budget quick --gpus 0 --seed 20230302, limit 20 min" in log
    assert any(m.startswith("PASS  run_quick:") for m in log)


def test_l0_a_mission_inside_a_run_directory_acceptance_removes_is_refused_before_anything_is_deleted(monkeypatch, tmp_path):
    """Round 9, M-12 sibling: run_one removed out/<name> and out/<name>_fetch before its subprocesses read --mission, so `acceptance --mission
    <out>/quick/mission.yaml` deleted its own mission and failed with 'file not found'; and a mission in a later run's directory would have gone after hours."""
    out = tmp_path / "o"
    monkeypatch.setattr(acc, "_execute", lambda *a, **k: pytest.fail("a subprocess started"))
    for sub in ("quick", "quick_fetch"):
        m = out / sub / "mission.yaml"
        m.parent.mkdir(parents=True)
        shutil.copy(MISSION, m)
        with pytest.raises(config.ConfigError, match=rf"inside {m.parent}, which acceptance removes"):
            acc.run_one(str(m), "quick", "ci", 0, out)
        assert m.exists()
    last = out / "4h" / "mission.yaml"
    last.parent.mkdir()
    shutil.copy(MISSION, last)
    f = Fake(tmp_path, monkeypatch)
    with pytest.raises(config.ConfigError, match="inside .*4h"):
        acc.run(str(last), 0, out, golden_for(tmp_path), log=lambda s: None)
    assert f.calls == [] and last.exists() and (out / "quick" / "mission.yaml").exists()                # nothing ran, nothing removed
    for fine in (MISSION, str(out / "mission.yaml"), str(out / "quick_other" / "mission.yaml"), str(out.parent / "o2" / "quick" / "mission.yaml")):
        acc.refuse_wiped_mission(fine, out, acc.RUN_NAMES)                                              # a prefix of the name or of the path is not inside it


def user_runs(out, *names, extra=()):
    """A directory a user keeps results in: out/<name>/report.json for each name, and the files of `extra`."""
    for n in names:
        (out / n).mkdir(parents=True)
        (out / n / "report.json").write_text(f"{n}: a result that took hours")
    for e in extra:
        (out / e).write_text("mine")


@pytest.mark.parametrize("held", ["quick", "quick_fetch", "quick.log", "quick_fetch.log", "plan.json", "checkpoints"])
def test_r10_m12_run_one_refuses_an_out_that_holds_somebody_elses_run_and_removes_nothing(monkeypatch, tmp_path, held):
    """Round 10, M-12: `--out runs` removed the user's runs/quick (and wrote over quick.log). Both rmtree sites (out/<name>, out/<name>_fetch), both logs and an
    out that is itself a run are refused when acceptance has not marked the directory, before any subprocess starts."""
    out = tmp_path / "o"
    out.mkdir()
    (out / held).mkdir() if held in ("quick", "quick_fetch", "checkpoints") else (out / held).write_text("mine")
    (out / "overnight").mkdir()
    (out / "overnight" / "report.json").write_text("ten hours")
    monkeypatch.setattr(acc, "_execute", lambda *a, **k: pytest.fail("a subprocess started"))
    with pytest.raises(config.ConfigError, match=rf"--out .* holds {held}\b"):
        acc.run_one(MISSION, "quick", "ci", 0, out)
    assert (out / held).exists() and (out / "overnight" / "report.json").read_text() == "ten hours" and not (out / acc.MARKER).exists()
    if held == "quick":
        user_runs(tmp_path / "p", "quick")                                                             # and its files, not only the directory
        with pytest.raises(config.ConfigError):
            acc.run_one(MISSION, "quick", "ci", 0, tmp_path / "p")
        assert (tmp_path / "p" / "quick" / "report.json").read_text() == "quick: a result that took hours"


def test_r10_m12_run_refuses_before_the_first_run_when_only_a_later_run_name_is_taken(monkeypatch, tmp_path):
    """`run` asks for every name at once: the user's overnight result is protected before the quick run starts, not after it."""
    out = tmp_path / "o"
    user_runs(out, "overnight", "4h", extra=("quick_seed.log",))
    f = Fake(tmp_path, monkeypatch)
    with pytest.raises(config.ConfigError) as e:
        acc.run(MISSION, 1, out, golden_for(tmp_path), log=lambda s: None)
    assert "holds quick_seed.log, overnight, 4h," in str(e.value)
    assert f.calls == [] and (out / "overnight" / "report.json").is_file() and (out / "4h" / "report.json").is_file() and not (out / acc.MARKER).exists()


def test_r10_m12_a_first_run_marks_the_directory_and_a_rerun_replaces_only_its_own_runs(monkeypatch, tmp_path):
    out = tmp_path / "fresh" / "nested"                                                                # does not exist yet
    monkeypatch.setattr(acc, "_execute", lambda argv, env, log, timeout: 0)
    acc.run_one(MISSION, "quick", "ci", 0, out)
    assert (out / acc.MARKER).is_file() and (out / "quick" / "emulator_table").is_dir()
    (out / "quick" / "stale.txt").write_text("this run's own leftovers")
    (out / "quick_fetch").mkdir()
    (out / "quick_fetch" / "stale.txt").write_text("this run's own leftovers")
    acc.run_one(MISSION, "quick", "ci", 0, out)                                                        # the rerun: replaced, no refusal
    assert [p.name for p in (out / "quick").iterdir()] == ["emulator_table"] and not (out / "quick_fetch").exists()
    empty = tmp_path / "empty"
    empty.mkdir()
    acc.run_one(MISSION, "quick", "ci", 0, empty)                                                      # an empty directory is claimed
    assert (empty / acc.MARKER).is_file()


def test_r10_m12_a_directory_with_other_files_is_claimed_but_the_other_files_stay(monkeypatch, tmp_path):
    out = tmp_path / "o"
    user_runs(out, "mine", "overnight_old", extra=("notes.txt",))
    monkeypatch.setattr(acc, "_execute", lambda argv, env, log, timeout: 0)
    acc.run_one(MISSION, "quick", "ci", 0, out)
    assert (out / "notes.txt").read_text() == "mine" and (out / "mine" / "report.json").is_file() and (out / "overnight_old" / "report.json").is_file()


def test_r10_m12_a_run_killed_after_the_mark_is_rerunnable(monkeypatch, tmp_path):
    """The marker is written before the first rmtree: an interrupted first run leaves a directory the second run accepts."""
    out = tmp_path / "o"

    def killed(argv, env, log, timeout):
        (out / "quick").mkdir(exist_ok=True)
        (out / "quick" / "half.txt").write_text("half a run")
        raise KeyboardInterrupt
    monkeypatch.setattr(acc, "_execute", killed)
    with pytest.raises(KeyboardInterrupt):
        acc.run_one(MISSION, "quick", "ci", 0, out)
    monkeypatch.setattr(acc, "_execute", lambda argv, env, log, timeout: 0)
    acc.run_one(MISSION, "quick", "ci", 0, out)
    assert not (out / "quick" / "half.txt").exists() and (out / acc.MARKER).is_file()


@pytest.mark.parametrize("own", acc.OWN_FILES)
def test_r10_m12_an_out_from_before_the_marker_is_claimed_not_refused(monkeypatch, tmp_path, own):
    """`make acceptance` after an upgrade: runs/acceptance holds an earlier acceptance run (quick, its logs, a file only `run` writes) and no marker.
    It is marked and replaced, not refused with exit 2 (the owner would have had to touch the marker by hand before the 11 h run)."""
    out = tmp_path / "runs" / "acceptance"
    user_runs(out, "quick", "overnight", extra=(own, "quick.log"))
    monkeypatch.setattr(acc, "_execute", lambda argv, env, log, timeout: 0)
    acc.run_one(MISSION, "quick", "ci", 0, out)
    assert (out / acc.MARKER).is_file() and not (out / "quick" / "report.json").exists() and (out / own).is_file()


@pytest.mark.parametrize("itself", ["plan.json", "checkpoints"])
def test_r10_m12_an_out_that_is_itself_a_run_is_refused_even_with_an_acceptance_file(monkeypatch, tmp_path, itself):
    out = tmp_path / "o"
    user_runs(out, "quick", extra=("acceptance.json",))
    (out / itself).mkdir() if itself == "checkpoints" else (out / itself).write_text("mine")
    monkeypatch.setattr(acc, "_execute", lambda *a, **k: pytest.fail("a subprocess started"))
    with pytest.raises(config.ConfigError, match=rf"holds quick, {itself}"):
        acc.run_one(MISSION, "quick", "ci", 0, out)
    assert (out / "quick" / "report.json").is_file() and not (out / acc.MARKER).exists()


def test_r10_m12_the_mission_refusal_still_comes_first(monkeypatch, tmp_path):
    out = tmp_path / "o"
    user_runs(out, "quick")
    m = out / "quick" / "mission.yaml"
    shutil.copy(MISSION, m)
    with pytest.raises(config.ConfigError, match="which acceptance removes before it runs"):
        acc.run_one(str(m), "quick", "ci", 0, out)


def test_l0_run_names_are_every_directory_run_makes(monkeypatch, tmp_path):
    f = Fake(tmp_path, monkeypatch)
    acc.run(MISSION, 1, tmp_path / "o", golden_for(tmp_path), log=lambda s: None)
    assert [c[0] for c in f.calls] == list(acc.RUN_NAMES)


def test_with_no_gpu_there_is_no_4h_run(monkeypatch, tmp_path):
    f = Fake(tmp_path, monkeypatch)
    rows, rc = acc.run(MISSION, 0, tmp_path / "o", golden_for(tmp_path), log=lambda s: None)
    assert rc == 0 and all(r["ok"] for r in rows) and [c[0] for c in f.calls] == ["quick", "quick_same", "quick_seed", "overnight"]
    assert not any("4h" in r["name"] or "gpu" in r["name"] for r in rows)


def test_skip_overnight_never_passes_and_runs_no_overnight(monkeypatch, tmp_path):
    f = Fake(tmp_path, monkeypatch)
    rows, rc = acc.run(MISSION, 0, tmp_path / "o", golden_for(tmp_path), skip_overnight=True, log=lambda s: None)
    by = {r["name"]: r for r in rows}
    assert rc == 1 and [r["name"] for r in rows if not r["ok"]] == ["run_overnight"] and "overnight not run" in by["run_overnight"]["detail"]
    assert "overnight" not in [c[0] for c in f.calls] and "cpu_fallback_overnight" not in by


def test_one_failing_check_makes_the_exit_code_1_and_the_table_says_which(monkeypatch, tmp_path):
    f = Fake(tmp_path, monkeypatch, wall=99999.0)
    rows, rc = acc.run(MISSION, 0, tmp_path / "o", golden_for(tmp_path), log=lambda s: None)
    assert rc == 1 and not next(r for r in rows if r["name"] == "run_quick")["ok"]
    text = acc.table(rows)
    assert text.startswith("acceptance: FAIL (") and "FAIL  run_quick" in text and "over the 20 min limit" in text
    assert len(f.calls) == 4


def test_main_writes_acceptance_json_and_the_text_table_and_returns_the_exit_code(monkeypatch, tmp_path, capsys):
    rows = [dict(name="run_quick", ok=True, detail="fine", values=dict(wall_s=1.5)), dict(name="golden_diff", ok=False, detail="no golden", values={})]
    seen = []
    monkeypatch.setattr(acc, "run", lambda *a, **k: (seen.append((a, k)), (rows, 1))[1])
    out = tmp_path / "o"
    assert cli.main(["acceptance", "--mission", MISSION, "--gpus", "1", "--out", str(out), "--update-golden", "--skip-overnight"]) == 1
    assert seen[0][0] == (MISSION, 1, out, acc.GOLDEN, True, True)
    j = json.loads((out / "acceptance.json").read_text())
    assert j["ok"] is False and j["gpus"] == 1 and j["skip_overnight"] is True and j["checks"] == rows and len(j["code_digest"]) == 64 and j["git_sha"]
    text = (out / "acceptance.txt").read_text()
    assert text.startswith("acceptance: FAIL (1 of 2 checks pass)\nPASS  run_quick") and "FAIL  golden_diff" in text
    assert capsys.readouterr().out.endswith(f"table: {out / 'acceptance.json'}\n")
    monkeypatch.setattr(acc, "run", lambda *a, **k: ([rows[0]], 0))
    assert cli.main(["acceptance", "--mission", MISSION, "--out", str(out), "--golden", str(tmp_path / "g.json")]) == 0
    assert json.loads((out / "acceptance.json").read_text())["ok"] is True and "PASS" in (out / "acceptance.txt").read_text()


# ---------------------------------------------------------------------------------------------------------------- the seed mechanism

def test_the_run_command_passes_its_seed_to_the_pipeline(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(pipeline, "run", lambda *a, **k: (seen.append(k), type("Ctx", (), {"run_dir": tmp_path})())[1])
    assert cli.main(["run", "--mission", MISSION, "--out", str(tmp_path), "--seed", "11"]) == 0
    assert seen[0]["seed"] == 11
    assert cli.main(["run", "--mission", MISSION, "--out", str(tmp_path)]) == 0 and seen[1]["seed"] is None
    with pytest.raises(SystemExit):
        cli.main(["plan", "--mission", MISSION, "--seed", "1"])


def test_a_seed_override_reaches_the_mission_the_plan_and_the_resume_hash(tmp_path):
    base = pipeline.Context(MISSION, "ci", 0, tmp_path / "a", lambda s: None)
    over = pipeline.Context(MISSION, "ci", 0, tmp_path / "b", lambda s: None, seed=99)
    same = pipeline.Context(MISSION, "ci", 0, tmp_path / "c", lambda s: None, seed=base.mission["seed"])
    assert base.mission["seed"] == 20230301 and over.mission["seed"] == 99 and "seed_override" not in base.plan and over.plan["seed_override"] == 99
    assert over.hash != base.hash and same.hash == base.hash


def test_the_run_directory_copy_of_the_mission_carries_the_overridden_seed(monkeypatch, tmp_path):
    src = tmp_path / "m.yaml"
    src.write_text(pathlib.Path(MISSION).read_text().replace("seed: 20230301", "seed: 20230301   # the demo's seed"))
    monkeypatch.setattr(pipeline, "FUNCS", {})
    monkeypatch.setattr(pipeline, "STAGES", [])
    pipeline.run(src, "ci", 0, tmp_path / "r", log=lambda s: None, seed=5)
    assert config.load_mission(tmp_path / "r" / "mission.yaml")["seed"] == 5
    assert json.loads((tmp_path / "r" / "plan.json").read_text())["seed_override"] == 5
    pipeline.run(src, "ci", 0, tmp_path / "s", log=lambda s: None)
    assert (tmp_path / "s" / "mission.yaml").read_bytes() == src.read_bytes() and "seed_override" not in json.loads((tmp_path / "s" / "plan.json").read_text())


# ---------------------------------------------------------------------------------------------------------------- bin/run_premission

def test_run_premission_is_executable_and_runs_the_run_command_from_the_repo_root(tmp_path):
    script = ROOT / "bin" / "run_premission"
    assert os.access(script, os.X_OK) and script.read_text().startswith("#!/bin/sh\n")
    env = dict(os.environ, PATH=os.path.dirname(sys.executable) + os.pathsep + os.environ.get("PATH", ""))
    p = subprocess.run([str(script), "--help"], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=300)
    assert p.returncode == 0 and p.stdout.startswith("usage: python -m cafe.pm run") and "--seed" in p.stdout
    p = subprocess.run([str(script), "--mission", "missions/nope.yaml"], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=300)
    assert p.returncode == 2 and "error:" in p.stderr


# ---------------------------------------------------------------------------------------------------------------- the whole command on the CI fixture

@pytest.fixture(scope="module")
def ci(ci_env, tmp_path_factory):
    """acceptance.run for real on the CI mission without its UAS (its slowest Stage-1 batch; every other part stays), no emulator variant runs and
    gpus = 0: a quick, a repeat and a seed + 1 run (the overnight run is a copy of the quick one)."""
    mp = pytest.MonkeyPatch()
    try:
        yield from _ci(mp, ci_env, tmp_path_factory)
    finally:
        mp.undo()


def _ci(mp, ci_env, tmp_path_factory):
    for m in (pipeline, ocean_mod):
        mp.setattr(m, "DATA", ci_env.data)
    mp.setenv("CAFE_DATA", str(ci_env.data))
    out = tmp_path_factory.mktemp("acc")
    # the session-wide ci_env tree also holds the table other modules' real runs append to; acceptance's "pristine shared table" is its own, empty, so
    # that a run that gets no copy of it (the noisy third run) and one that does (quick, quick_same) start alike whichever test ran before
    mp.setenv("CAFE_EMULATOR_TABLE", str(out / "pristine_shared" / "train.parquet"))
    mp.setattr(budget, "plan", small_budget(budget.plan))
    fake_module(mp, "cafe.pm.stage3.pipeline_windows", run=Rows().run)
    mp.setattr(acc, "RUNS", dict(quick=("ci", 0), overnight=("ci", 0), gpu=("ci", 1)))
    m = yaml.safe_load(pathlib.Path(MISSION).read_text())
    m["vehicles"] = [v for v in m["vehicles"] if v["id"] != "uas"]
    m["links"] = [lk for lk in m["links"] if "uas" not in (lk["a"], lk["b"])]
    (out / "ci_no_uas.yaml").write_text(yaml.safe_dump(m))
    mission = str(out / "ci_no_uas.yaml")
    mp.setattr(receipts, "run", lambda *a, **k: ([row(acc.WAVE_MODULE)], 0) if k.get("broken") else ([], 0))
    done = {}

    def in_process(argv, env, log, timeout):
        if argv[0] == "fetch":                                                                         # the data is the synthetic CAFE_DATA: nothing to fetch
            return 0
        out = pathlib.Path(argv[argv.index("--out") + 1])
        key = (argv[argv.index("--gpus") + 1], argv[argv.index("--seed") + 1] if "--seed" in argv else None)
        if out.name == "overnight":                                                                      # same inputs as quick: not run twice
            shutil.copytree(done[("0", None)], out, dirs_exist_ok=True)                                 # run_one made its emulator_table dir
            return 0
        with open(log, "w") as f, contextlib.redirect_stdout(f):
            rc = cli.main(argv)
        done.setdefault(key, out)
        return rc
    mp.setattr(acc, "_execute", in_process)
    runs = {}
    run_one = acc.run_one
    mp.setattr(acc, "run_one", lambda *a, **k: runs.setdefault(a[1], run_one(*a, **k)))
    rows, rc = acc.run(mission, 0, out / "o", out / "golden" / "g.json", log=lambda s: None)
    yield type("CI", (), dict(rows={r["name"]: r for r in rows}, rc=rc, runs=runs, out=out, mp=mp, run_one=run_one, mission=mission))


def test_on_the_ci_fixture_every_run_finishes_and_the_missing_golden_is_reported(ci):
    assert ci.rc == 1
    for n in ("run_quick", "run_quick_same", "run_quick_seed", "run_overnight", "cpu_fallback_overnight", "broken_config"):
        assert ci.rows[n]["ok"], ci.rows[n]
    assert not ci.rows["golden_diff"]["ok"] and "--update-golden" in ci.rows["golden_diff"]["detail"]
    assert set(ci.rows) == {"run_quick", "golden_diff", "run_quick_same", "same_seed", "run_quick_seed", "other_seed", "broken_config", "run_overnight",
                            "cpu_fallback_overnight"}


def test_the_seed_plus_one_run_used_that_seed_and_the_report_carries_the_cpu_fallback_label(ci):
    q, o = ci.runs["quick"], ci.runs["quick_seed"]
    assert q["report"]["mission"]["seed"]["value"] == 20230301 and o["report"]["mission"]["seed"]["value"] == 20230302
    assert json.loads((o["dir"] / "plan.json").read_text())["seed_override"] == 20230302 and config.load_mission(o["dir"] / "mission.yaml")["seed"] == 20230302
    assert q["report"]["stage3"]["cpu_fallback"] and q["report"]["stage3"]["label"].startswith("CPU fallback") and "uas" not in q["report"]["vehicles"]
    assert ci.rows["other_seed"]["ok"] or ci.rows["other_seed"]["values"]["problems"]      # with a handful of members a verdict may legitimately move


def test_a_real_repeat_of_the_quick_run_is_identical_and_a_noisy_stage_is_caught(ci):
    q, same = ci.runs["quick"], ci.runs["quick_same"]
    assert ci.rows["same_seed"]["ok"], ci.rows["same_seed"]
    assert q["dir"] != same["dir"] and q["report"]["run"] != same["report"]["run"]
    real = pipeline.s_report

    def noisy(ctx, L):
        real(ctx, L)
        p = ctx.path("report", "report.json")
        rep = json.loads(p.read_text())
        v = next(iter(rep["vehicles"].values()))
        v["p_fail"]["value"] += float(np.random.default_rng().random()) * 1e-6
        p.write_text(json.dumps(rep, indent=1, allow_nan=False))
    ci.mp.setitem(pipeline.FUNCS, "report", noisy)
    try:
        third = ci.run_one(ci.mission, "quick_noisy", "ci", 0, ci.out / "o")
    finally:
        ci.mp.setitem(pipeline.FUNCS, "report", real)
    bad = acc.check_same_seed(q, third)
    assert not bad["ok"] and "p_fail.value" in bad["detail"]


def test_the_golden_written_from_a_real_report_passes_and_a_changed_verdict_or_p_fail_fails(ci, tmp_path):
    q = ci.runs["quick"]
    g = tmp_path / "g.json"
    assert not acc.check_golden(q, g, MISSION, True)["ok"]
    ok = acc.check_golden(q, g, MISSION, False)
    assert ok["ok"], ok
    vid = next(iter(json.loads(g.read_text())["summary"]["vehicles"]))
    sure = copy.deepcopy(q)                                                  # the CI fixture has too few members to decide anything: make one vehicle decided
    e = sure["report"]["vehicles"][vid]
    e.update(verdict="GO")
    e["k_fail"]["value"], e["n"]["value"], e["p_fail"]["value"] = 0, 1000, 0.0
    assert not acc.check_golden(sure, g, MISSION, True)["ok"] and acc.check_golden(sure, g, MISSION, False)["ok"]
    rec = json.loads(g.read_text())
    flipped = copy.deepcopy(rec)
    flipped["summary"]["vehicles"][vid]["verdict"] = "NO-GO"
    g.write_text(json.dumps(flipped))
    bad = acc.check_golden(sure, g, MISSION, False)
    assert not bad["ok"] and f"vehicles {vid}: verdict" in bad["detail"]
    g.write_text(json.dumps(rec))
    far = copy.deepcopy(sure)
    far["report"]["vehicles"][vid]["p_fail"]["value"] = 1.0
    far["report"]["vehicles"][vid]["k_fail"]["value"] = 1000
    bad = acc.check_golden(far, g, MISSION, False)
    assert not bad["ok"] and f"vehicles {vid}: P(fail) 1.0000 now against 0.0000" in bad["detail"]


# ---------------------------------------------------------------------------------------------------------------- review round 1 (M-33)

def test_undecided_verdicts_may_move_only_while_their_intervals_overlap():
    """M-33: a verdict undecided in both runs could change however far apart the two P(fail) were; now their stopper-level intervals must overlap."""
    near = acc.compare(summ({"x": ("MARGINAL", 4)}), summ({"x": ("GO", 1)}))                  # 0.125 and 0.031 at n = 32
    assert near == ([], ["links x: MARGINAL -> GO, undecided in both at n = 32"])
    lo, hi, _ = acc.intervals.interval(3, 32, acc.sequential.STOP_CONF)
    lo2, hi2, _ = acc.intervals.interval(15, 32, acc.sequential.STOP_CONF)
    assert hi < lo2 and acc._decided(dict(k_fail=3, n=32)) is False and acc._decided(dict(k_fail=15, n=32)) is False       # undecided both, and apart
    bad, notes = acc.compare(summ({"x": ("GO", 3)}), summ({"x": ("MARGINAL", 15)}))
    assert notes == [] and any("verdict 'GO' in the reference, 'MARGINAL' now; undecided in both, but the 95% intervals on P(fail), "
                               f"{lo:.3f} to {hi:.3f} and {lo2:.3f} to {hi2:.3f}, do not overlap" in b for b in bad)


def test_r9_m17_a_link_that_turns_not_exercised_or_back_is_a_problem_even_when_both_runs_are_undecided():
    """M-17: GO at 0 of 32 is undecided (the 95 % upper bound is 0.107), so GO -> NOT EXERCISED passed as a named note; it is not sampling noise."""
    go, nx = summ({"x": ("GO", 0)}), summ({"x": ("NOT EXERCISED", 0)})
    assert acc._decided(dict(k_fail=0, n=32)) is False
    assert acc.compare(go, nx) == (["links x: verdict 'GO' in the reference, 'NOT EXERCISED' now"], [])
    assert acc.compare(nx, go) == (["links x: verdict 'NOT EXERCISED' in the reference, 'GO' now"], [])
    assert acc.compare(nx, nx) == ([], [])                                                       # the same verdict twice is no change
    assert acc.compare(summ({"x": ("MARGINAL", 4)}), summ({"x": ("GO", 1)}))[0] == []         # the undecided rule for the other verdicts is as before


def test_the_overlap_rule_is_symmetric():
    a, b = summ({"x": ("GO", 3)}), summ({"x": ("MARGINAL", 15)})
    assert len(acc.diff(a, b)) == len(acc.diff(b, a)) == 2                                    # the verdict and the P(fail) difference
    assert acc.compare(a, a) == ([], [])


GOOD = dict(git_sha=SHA, dirty=False, code_digest="d" * 64, reviewed_run=dict(name="quick", report_sha256="e" * 64))


@pytest.mark.parametrize("change, words", [
    (dict(git_sha="none"), "git_sha 'none' is not a commit"),
    (dict(git_sha="abc123"), "git_sha 'abc123' is not a commit"),
    (dict(code_digest=""), "no code_digest"),
    (dict(dirty=True), "made from a checkout with uncommitted changes"),
    (dict(reviewed_run={}), "no reviewed_run"),
    (dict(reviewed_run=dict(name="quick")), "no reviewed_run")])
def test_a_golden_without_provenance_says_what_is_missing(change, words):
    assert acc.provenance_problems(GOOD) == []
    assert any(words in p for p in acc.provenance_problems(dict(GOOD, **change)))


def test_a_golden_made_where_it_is_unknown_whether_the_tree_was_clean_has_no_provenance():
    """M-31: through ./pm.sh the checkout has no .git, `dirty: null` was written and accepted."""
    bad = acc.provenance_problems(dict(GOOD, dirty=None))
    assert len(bad) == 1 and "cannot tell whether the checkout was clean" in bad[0] and "$CAFE_GIT_DIRTY" in bad[0]


@pytest.mark.parametrize("flag, dirty, problems", [("1", True, 1), ("0", False, 0), (None, None, 1)])
def test_without_a_git_checkout_the_golden_reads_pm_shs_dirty_flag(monkeypatch, tmp_path, flag, dirty, problems):
    """M-31: `_dirty` had its own `git status` and never read $CAFE_GIT_DIRTY, which pm.sh sets for exactly this case."""
    monkeypatch.undo()
    monkeypatch.setattr(acc, "git_sha", lambda: SHA)
    monkeypatch.setattr(acc.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess([], 128, "", "not a git repository"))        # no .git
    monkeypatch.delenv("CAFE_GIT_DIRTY", raising=False)
    if flag is not None:
        monkeypatch.setenv("CAFE_GIT_DIRTY", flag)
    g = tmp_path / "g.json"
    acc.check_golden(run_dict(tmp_path, report()), g, MISSION, True)
    src = json.loads(g.read_text())["source"]
    assert src["dirty"] is dirty and len(acc.provenance_problems(src)) == problems
    assert acc.check_golden(run_dict(tmp_path, report()), g, MISSION, False)["ok"] is (problems == 0)


def test_an_unprovenanced_golden_fails_and_names_the_command_that_writes_a_new_one(tmp_path):
    g = tmp_path / "g.json"
    acc.check_golden(run_dict(tmp_path, report()), g, MISSION, True)
    assert acc.check_golden(run_dict(tmp_path, report()), g, MISSION, False)["ok"]
    rec = json.loads(g.read_text())
    rec["source"].update(git_sha="none")
    del rec["source"]["reviewed_run"]
    g.write_text(json.dumps(rec))
    r = acc.check_golden(run_dict(tmp_path, report()), g, MISSION, False)
    assert not r["ok"] and "has no provenance (git_sha 'none' is not a commit; no reviewed_run" in r["detail"] and "on a clean checkout" in r["detail"]
    assert f"python -m cafe.pm acceptance --mission {MISSION} --gpus 0 --update-golden" in r["detail"] and len(r["values"]["provenance"]) == 2
    del rec["source"]
    g.write_text(json.dumps(rec))
    assert "git_sha None is not a commit" in acc.check_golden(run_dict(tmp_path, report()), g, MISSION, False)["detail"]


def test_a_golden_records_its_commit_and_the_reviewed_run_by_hash(tmp_path):
    g = tmp_path / "g.json"
    rd = run_dict(tmp_path, report(), name="quick_rev")
    acc.check_golden(rd, g, MISSION, True)
    src = json.loads(g.read_text())["source"]
    assert src["git_sha"] == SHA and src["dirty"] is False and src["reviewed_run"] == dict(name="quick_rev", report_sha256=acc.hashlib.sha256(
        (rd["dir"] / "report" / "report.json").read_bytes()).hexdigest())
    assert acc.provenance_problems(src) == []


def test_dirty_is_true_false_or_unknown(monkeypatch, tmp_path):
    monkeypatch.undo()
    monkeypatch.delenv("CAFE_GIT_DIRTY", raising=False)
    calls = iter([subprocess.CompletedProcess([], rc, out, "") for rc, out in ((0, " M x.py\n"), (0, ""), (128, ""))])
    monkeypatch.setattr(acc.subprocess, "run", lambda *a, **k: next(calls))
    assert (acc._dirty(), acc._dirty(), acc._dirty()) == (True, False, None)

    def boom(*a, **k):
        raise OSError("no git")
    monkeypatch.setattr(acc.subprocess, "run", boom)
    assert acc._dirty() is None


def test_the_golden_in_the_repo_has_the_shape_the_comparison_reads():
    g = json.loads(acc.GOLDEN.read_text())
    assert g["schema"] == 1 and "source" in g and acc.compare(g["summary"], g["summary"]) == ([], [])


# ---------------------------------------------------------------------------------------------------------------- review round 2, batch D

def fetched(tmp_path, monkeypatch, frc=0, cold=False, wall=0.2, ingest_s=6.0):
    """acceptance.run_one with `_execute` replaced: fetch (writes an ingest ledger when `cold`, exits `frc`) and run (writes a report and an ingest ledger)."""
    out = tmp_path / "o"

    def ledger(d, notes, wall_s):
        (d / "checkpoints" / "ingest").mkdir(parents=True)
        (d / "checkpoints" / "ingest" / "ledger.json").write_text(json.dumps(dict(notes=notes, wall_s=wall_s)))

    def execute(argv, env, log, timeout):
        d = pathlib.Path(argv[argv.index("--out") + 1])
        if argv[0] == "fetch":
            time.sleep(wall)
            ledger(d, ["cold fetch: 315 parts, 522 s"] if cold else [], 522.0 if cold else 5.0)
            return frc
        (d / "report").mkdir(parents=True)
        (d / "report" / "report.json").write_text(json.dumps(report()))
        ledger(d, [], ingest_s)
        return 0
    monkeypatch.setattr(acc, "_execute", execute)
    return RUN_ONE(MISSION, "quick", "quick", 0, out)


def test_the_limit_times_the_run_after_a_fetch_and_the_row_says_what_the_fetch_cost(monkeypatch, tmp_path):
    """M-25: the 20-minute limit was compared with a wall that included a 522 s cold download no budget share covers."""
    r = fetched(tmp_path, monkeypatch, cold=True)
    assert (r["rc"] == 0
            and r["fetch_rc"] == 0
            and r["cold_fetch"] is True
            and r["ingest_s"] == 6.0
            and r["fetch_wall_s"] >= 0.2
            and r["wall_s"] < r["fetch_wall_s"] + 5)
    row = acc.check_run(dict(r, wall_s=700.0, fetch_wall_s=522.0))
    assert (row["ok"]
            and "11.7 min of the 20 min limit" in row["detail"]
            and "ingest 6 s, fetch 522 s, neither counted against --budget; cold fetch: yes" in row["detail"])
    assert row["values"]["cold_fetch"] is True and row["values"]["ingest_s"] == 6.0
    warm = fetched(tmp_path / "w", monkeypatch)
    assert warm["cold_fetch"] is False and "cold fetch: no" in acc.check_run(warm)["detail"]
    assert acc.check_run(dict(r, wall_s=1300.0))["ok"] is False                                          # the run itself is still held to the limit


def test_a_failed_fetch_fails_the_run_row_naming_the_fetch_command_and_starts_no_run(monkeypatch, tmp_path):
    r = fetched(tmp_path, monkeypatch, frc=2)
    assert (r["rc"] == 2
            and r["report"] is None
            and r["wall_s"] == 0.0
            and r["log"].name == "quick_fetch.log"
            and not (tmp_path / "o" / "quick" / "report").exists())
    row = acc.check_run(r)
    assert (not row["ok"]
            and "fetch exit code 2" in row["detail"]
            and f"python -m cafe.pm fetch --mission {MISSION}" in row["detail"]
            and "CAFE_OFFLINE=1" in row["detail"])
    assert "no report" not in row["detail"]
