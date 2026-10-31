"""`python -m cafe.pm acceptance --mission M --gpus N --out DIR [--golden FILE] [--update-golden] [--skip-overnight]`: BRIEF 5.3 and 0.1.

Every run is a fresh `python -m cafe.pm run` in its own process and its own run directory under DIR (`quick`, `quick_same`, `quick_seed`,
`overnight`, and `4h` when N >= 1), timed by the wall clock against `budget.BUDGET_S`: quick 20 min, overnight 10 h, 4h 4 h. The checks:

    run_<name>        the run exits 0, writes report/report.json, and finishes within its budget (a run is killed at twice the limit)
    cpu_fallback      overnight on CPU: plan.json, report.json and index.html all say the LES windows are the CPU fallback (4h: they say the GPU path)
    golden_diff       the quick run against the golden file (default tests/golden/tepex_c_demo_quick.json), see `summary`/`compare`
    same_seed         a second quick run with the same seed gives an identical report.json once the run-specific fields (see `normalize`) and
                      the run directory's path are removed. Run-specific: the run name, wall times, git sha, host and versions, the emulator's measured
                      query time (BRIEF 2.7 asks for it; it is the one measured value in a hashed file, emulator/holdout.json), and the run directory's
                      name inside report/credibility.json. Every run starts from its own copy of the same emulator table, and every amount of work is
                      sized at plan time, so everything else (verdicts, P(fail), tracks, stage 3, the emulator, the fixes, every other hash) must match.
    other_seed        a quick run with seed + 1, compared with the first by the rules below
    broken_config     receipts.run(broken=tests/fixtures/broken/wave_direction.yaml) exits 0 (a receipt failed), and the failed receipt is one of the
                      wave-direction receipts, which pass without the broken configuration; other stored failures cannot satisfy it

The golden keeps, per vehicle and link: verdict, k_fail, n, P(fail) and the interval's confidence, plus class and platform; and the mission name and
seed. Two estimates from independent runs (the golden's, or the first run's, against the new one) are compared like this: the mission name, the seed
(not for other_seed), class, platform, n and the set of vehicles and links must match exactly. A verdict must be identical wherever either run has it
decided, that is wherever `stats.intervals.decided_region` at the stopper's confidence (`stats.sequential.STOP_CONF`) puts the whole P(fail) interval
inside GO, MARGINAL (0.10 to 0.40) or NO-GO; a verdict that changes while undecided in both runs is allowed and named in the row's detail
("uas: MARGINAL -> GO, undecided in both at n = 32"), because at a quick budget a vehicle near a threshold cannot be decided. P(fail) is judged
by Newcombe's (1998, Stat. Med. 17:873, method 10) hybrid
Wilson-score interval for the difference of the two proportions, `intervals.newcombe_diff`, which must contain 0 at a family-wise 95 %: Bonferroni over the
vehicles and links compared, so each entry is judged at 1 - 0.05 / entries. (A new estimate inside the 90 % interval of an independent one fails about a
quarter of the time even when nothing is wrong.) The same-seed check is exact equality and is unchanged. Timings, the
git sha, dates, the host and paths are not in the golden. A missing golden is a FAIL that names the command writing it. `--update-golden` rewrites it
from the quick run (with the git sha and code digest it came from) and that check then FAILs ("updated, not compared"), so a gate cannot be passed by
overwriting its reference. `--skip-overnight` is for rehearsals: the overnight check FAILs with "overnight not run". Exit 0 only if every check passes.
DIR/acceptance.json and DIR/acceptance.txt hold the result.
"""
from __future__ import annotations

import argparse, datetime as dt, hashlib, html, json, os, pathlib, shutil, subprocess, sys, time
from collections.abc import Callable, Iterator
from typing import Any

from . import budget, config, pipeline, receipts
from .ledger import git_sha
from .stats import intervals, sequential

ROOT = pathlib.Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "tests" / "golden" / "tepex_c_demo_quick.json"
BROKEN = ROOT / "tests" / "fixtures" / "broken" / "wave_direction.yaml"
WAVE_MODULE = "pm.env.wave_direction"
RUNS: dict[str, tuple[str, int]] = dict(quick=("quick", 0), overnight=("overnight", 0), gpu=("4h", 1))      # role -> (budget, gpus)
VOLATILE = ("run", "machine.wall_s", "machine.git_sha", "machine.versions", "machine.machine")   # report.json paths that differ between identical runs
HOLDOUT, CREDIBILITY = "emulator:output:holdout.json", "report:output:credibility.json"            # receipts whose files hold a timing / the run's name
KILL_AT = 2.0                                                                                          # a run is killed at this multiple of its limit
EPS = 1e-9
FAMILY_ALPHA = 0.05                                                                                    # family-wise error of the P(fail) comparisons


def _execute(argv: list[str], env: dict[str, str], log: pathlib.Path, timeout: float) -> int:
    """`python -m cafe.pm *argv` from the repo root, output to `log`; -> exit code (124 when killed at `timeout`, as timeout(1) does)."""
    with open(log, "w") as f:
        try:
            return subprocess.run([sys.executable, "-m", "cafe.pm", *argv], cwd=ROOT, env=env, stdout=f, stderr=subprocess.STDOUT, timeout=timeout).returncode
        except subprocess.TimeoutExpired:
            return 124


def run_one(mission: str, name: str, budget_name: str, gpus: int, out: pathlib.Path, seed: int | None = None,
            table: pathlib.Path | None = None) -> dict[str, Any]:
    """A fresh run in out/name with its own emulator table out/name/emulator_table/train.parquet: a copy of `table` (the pristine shared table),
    or none yet when `table` is None, so no run sees another's rows and none appends to the shared table.
    -> {name, budget, gpus, seed, dir, log, rc, wall_s, limit_s, report (report.json or None)}."""
    d = out / name
    shutil.rmtree(d, ignore_errors=True)
    out.mkdir(parents=True, exist_ok=True)
    argv = ["run", "--mission", str(pathlib.Path(mission).resolve()), "--budget", budget_name, "--gpus", str(gpus), "--out", str(d.resolve()), "--fresh"]
    argv += [] if seed is None else ["--seed", str(seed)]
    own = d / "emulator_table" / "train.parquet"
    own.parent.mkdir(parents=True)
    if table is not None:
        shutil.copyfile(table, own)
    argv += ["--emulator-table", str(own.resolve())]
    limit = budget.BUDGET_S[budget_name]
    t = time.monotonic()
    rc = _execute(argv, dict(os.environ), out / f"{name}.log", KILL_AT * limit)
    wall = time.monotonic() - t
    rj = d / "report" / "report.json"
    return dict(name=name, budget=budget_name, gpus=gpus, seed=seed, dir=d, log=out / f"{name}.log", rc=rc, wall_s=wall, limit_s=limit,
                report=json.loads(rj.read_text()) if rj.is_file() else None)


def _row(name: str, ok: bool, detail: str, **values: Any) -> dict[str, Any]:
    return dict(name=name, ok=bool(ok), detail=detail, values=values)


def check_run(r: dict[str, Any]) -> dict[str, Any]:
    """Exit 0, a report, and the wall-clock limit."""
    why = []
    if r["rc"] != 0:
        why.append(f"exit code {r['rc']}" + (" (killed at the time limit)" if r["rc"] == 124 else "") + f", see {r['log']}")
    elif r["report"] is None:
        why.append(f"no report/report.json in {r['dir']}")
    if r["wall_s"] > r["limit_s"]:
        why.append(f"took {r['wall_s'] / 60:.1f} min, over the {r['limit_s'] / 60:.0f} min limit of --budget {r['budget']}")
    ok_text = f"--budget {r['budget']} --gpus {r['gpus']}: {r['wall_s'] / 60:.1f} min of the {r['limit_s'] / 60:.0f} min limit"
    return _row(f"run_{r['name']}", not why, "; ".join(why) or ok_text,
                budget=r["budget"], gpus=r["gpus"], wall_s=r["wall_s"], limit_s=r["limit_s"], rc=r["rc"])


def check_label(r: dict[str, Any]) -> dict[str, Any]:
    """plan.json, report.json and index.html agree that the LES windows are the CPU fallback (no GPU) or the GPU path (GPU)."""
    want_cpu = r["gpus"] == 0
    name = f"cpu_fallback_{r['name']}" if want_cpu else f"gpu_path_{r['name']}"
    if r["report"] is None:
        return _row(name, False, "no report to read the LES label from")
    s = r["report"]["stage3"]
    plan = json.loads((r["dir"] / "plan.json").read_text())["les"]
    page = (r["dir"] / "report" / "index.html").read_text()
    got = dict(plan_cpu_fallback=plan["cpu_fallback"], report_cpu_fallback=s["cpu_fallback"], label_in_page=html.escape(s["label"]) in page,
               label_says_cpu=s["label"].startswith("CPU fallback"))
    ok = got["plan_cpu_fallback"] is want_cpu and got["report_cpu_fallback"] is want_cpu and got["label_in_page"] and got["label_says_cpu"] is want_cpu
    return _row(name, ok, f"{s['backend']}: {s['label'][:90]}" if ok else f"expected {'the CPU fallback' if want_cpu else 'the GPU path'}, got {got}", **got)


def summary(rep: dict[str, Any]) -> dict[str, Any]:
    """What the golden keeps of a report.json."""
    def stat(e: dict[str, Any]) -> dict[str, Any]:
        return dict(verdict=e["verdict"], k_fail=int(e["k_fail"]["value"]), n=int(e["n"]["value"]), p_fail=e["p_fail"]["value"],
                    conf=e["p_fail"]["uncertainty"]["conf"])
    return dict(mission=rep["mission"]["name"], seed=rep["mission"]["seed"]["value"],
                vehicles={k: dict(stat(v), cls=v["cls"], platform=v["platform"]) for k, v in rep["vehicles"].items()},
                links={k: stat(v) for k, v in rep["links"].items()})


def _entries(ref: dict[str, Any], new: dict[str, Any]) -> int:
    """How many vehicles and links both summaries have: the family of P(fail) comparisons."""
    return sum(len(ref[kind].keys() & new[kind].keys()) for kind in ("vehicles", "links"))


def _decided(e: dict[str, Any]) -> bool:
    return intervals.decided_region(e["k_fail"], e["n"], sequential.STOP_CONF) is not None


def compare(ref: dict[str, Any], new: dict[str, Any], seed: bool = True) -> tuple[list[str], list[str]]:
    """(problems, notes) of `new` against `ref` (both from `summary`): the exact fields must match; a verdict must match wherever either run has it
    decided (a change undecided in both is a note, not a problem); and Newcombe's interval for the difference of the two P(fail), at 1 - FAMILY_ALPHA / m
    for the m entries compared (Bonferroni), must contain 0. seed=False leaves the mission seed out (the other_seed check)."""
    bad = [f"{f}: {ref[f]!r} in the reference, {new[f]!r} now" for f in ("mission", "seed") if ref[f] != new[f] and (seed or f != "seed")]
    notes: list[str] = []
    conf = 1 - FAMILY_ALPHA / max(_entries(ref, new), 1)
    for kind in ("vehicles", "links"):
        a, b = ref[kind], new[kind]
        if a.keys() != b.keys():
            bad.append(f"{kind}: {sorted(a)} in the reference, {sorted(b)} now")
        for k in sorted(a.keys() & b.keys()):
            g, r = a[k], b[k]
            bad += [f"{kind} {k}: {f} {g.get(f)!r} in the reference, {r.get(f)!r} now" for f in ("cls", "platform", "n") if g.get(f) != r.get(f)]
            if g.get("verdict") != r.get("verdict"):
                if _decided(g) or _decided(r):
                    bad.append(f"{kind} {k}: verdict {g.get('verdict')!r} in the reference, {r.get('verdict')!r} now")
                else:
                    notes.append(f"{kind} {k}: {g['verdict']} -> {r['verdict']}, undecided in both at n = {g['n']}")
            lo, hi = intervals.newcombe_diff(r["k_fail"], r["n"], g["k_fail"], g["n"], conf)
            if not lo - EPS <= 0 <= hi + EPS:
                bad.append(f"{kind} {k}: P(fail) {r['p_fail']:.4f} now against {g['p_fail']:.4f} in the reference ({r['k_fail']} of {r['n']} and "
                           f"{g['k_fail']} of {g['n']}): the {conf:.2%} Newcombe interval for their difference, {lo:.4f} to {hi:.4f}, excludes 0")
    return bad, notes


def diff(ref: dict[str, Any], new: dict[str, Any], seed: bool = True) -> list[str]:
    """The problems of `compare`."""
    return compare(ref, new, seed)[0]


def _allowed(notes: list[str]) -> str:
    return "; undecided in both, allowed to differ: " + "; ".join(notes) if notes else ""


def _golden_record(r: dict[str, Any], mission: str) -> dict[str, Any]:
    return dict(schema=1, command=f"python -m cafe.pm acceptance --mission {mission} --gpus {r['gpus']} --update-golden",
                source=dict(git_sha=git_sha(), code_digest=pipeline.code_digest(), date=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                            budget=r["budget"], gpus=r["gpus"]),
                summary=summary(r["report"]))


def check_golden(r: dict[str, Any], golden: pathlib.Path, mission: str, update: bool) -> dict[str, Any]:
    cmd = f"python -m cafe.pm acceptance --mission {mission} --gpus {r['gpus']} --update-golden"
    if r["report"] is None:
        return _row("golden_diff", False, "the quick run wrote no report to compare")
    if update:
        golden.parent.mkdir(parents=True, exist_ok=True)
        golden.write_text(json.dumps(_golden_record(r, mission), indent=1, allow_nan=False) + "\n")
        return _row("golden_diff", False, f"golden {golden} UPDATED from this run, not compared: rerun without --update-golden to check against it",
                    updated=True)
    if not golden.is_file():
        return _row("golden_diff", False, f"no golden file at {golden}: write it from a quick run you have reviewed with `{cmd}`", missing=True)
    g = json.loads(golden.read_text())
    bad, notes = compare(g["summary"], summary(r["report"]))
    n = len(g["summary"]["vehicles"]) + len(g["summary"]["links"])
    return _row("golden_diff", not bad, ("; ".join(bad[:6]) + (f" (+{len(bad) - 6} more)" if len(bad) > 6 else "") if bad else
                f"{n} verdicts and P(fail) agree with {golden.name} (git {g['source']['git_sha'][:10]})") + _allowed(notes),
                problems=bad, notes=notes, golden=str(golden))


def _drop(rep: dict[str, Any], path: str) -> None:
    *head, last = path.split(".")
    node = rep
    for k in head:
        node = node.get(k, {})
    node.pop(last, None)


def normalize(rep: dict[str, Any], run_dir: pathlib.Path) -> dict[str, Any]:
    """report.json without the fields that legitimately differ between two identical runs: VOLATILE, each trained emulator's query time, the
    sha-256 of holdout.json (it holds that time), and the run directory's path; credibility.json's sha-256 is replaced by that of the file without
    the run directory (its path and its own "run" field), or dropped when the file is not there."""
    def unrun(text: str) -> str:
        return text.replace(str(run_dir.resolve()), "<run>").replace(str(run_dir), "<run>")
    out: dict[str, Any] = json.loads(unrun(json.dumps(rep)))
    for p in VOLATILE:
        _drop(out, p)
    for e in out.get("emulator", {}).get("vehicles", {}).values():
        e.get("acceptance", {}).pop("query_ms", None)
    cred = run_dir / "report" / "credibility.json"
    for r in out.get("receipts", []):
        if r.get("id") == HOLDOUT or (r.get("id") == CREDIBILITY and not cred.is_file()):
            r.pop("sha256", None)
        elif r.get("id") == CREDIBILITY:
            c = json.loads(unrun(cred.read_text()))
            c.pop("run", None)
            r["sha256"] = hashlib.sha256(json.dumps(c, sort_keys=True).encode()).hexdigest()
    return out


def _delta(a: Any, b: Any, path: str = "") -> Iterator[str]:
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(a.keys() | b.keys()):
            yield from _delta(a.get(k, "<absent>"), b.get(k, "<absent>"), f"{path}.{k}" if path else k)
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for i, (x, y) in enumerate(zip(a, b, strict=True)):
            yield from _delta(x, y, f"{path}[{i}]")
    elif a != b:
        yield f"{path}: {str(a)[:50]} != {str(b)[:50]}"


def check_same_seed(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    if a["report"] is None or b["report"] is None:
        return _row("same_seed", False, "a quick run wrote no report to compare")
    bad = list(_delta(normalize(a["report"], a["dir"]), normalize(b["report"], b["dir"])))
    return _row("same_seed", not bad, f"{len(bad)} fields differ: " + "; ".join(bad[:4]) if bad else "report.json identical (run-specific fields removed)",
                differing=len(bad), fields=bad[:20])


def check_other_seed(a: dict[str, Any], c: dict[str, Any]) -> dict[str, Any]:
    if a["report"] is None or c["report"] is None:
        return _row("other_seed", False, "a quick run wrote no report to compare")
    ref = summary(a["report"])
    bad, notes = compare(ref, summary(c["report"]), seed=False)
    ok_text = (f"seed {c['seed']}: every decided verdict unchanged, every P(fail) consistent with the seed {ref['seed']} run "
               f"(Newcombe, family-wise 95 % over {_entries(ref, summary(c['report']))} compared)")
    return _row("other_seed", not bad, ("; ".join(bad[:4]) if bad else ok_text) + _allowed(notes), problems=bad, notes=notes)


def check_broken(out: pathlib.Path) -> dict[str, Any]:
    """The broken configuration must fail a wave-direction receipt (receipts.run's exit code is 0 then), which the same receipts pass without it."""
    lines: list[str] = []
    try:
        rows, rc = receipts.run(broken=BROKEN, out=out / "receipts_broken.json", log=lines.append)
        _, base_rc = receipts.run(only=[WAVE_MODULE], out=out / "receipts_wave_direction.json", log=lines.append)
    except FileNotFoundError as e:
        return _row("broken_config", False, str(e))
    (out / "receipts_broken.log").write_text("\n".join(lines) + "\n")
    caught = [r["id"] for r in rows if r["kind"] == "fail" and r["module"] == WAVE_MODULE]
    ok = rc == 0 and bool(caught) and base_rc == 0
    why = ("the broken configuration failed no receipt" if rc != 0
           else "no wave-direction receipt failed under the broken configuration (other receipts did)" if not caught
           else "the wave-direction receipts fail even without the broken configuration")
    return _row("broken_config", ok, f"{len(caught)} wave-direction receipts fail under {BROKEN.name}: {', '.join(caught[:3])}" if ok else why,
                caught=caught, exit_code=rc, baseline_exit_code=base_rc)


def run(mission: str, gpus: int, out: pathlib.Path, golden: pathlib.Path = GOLDEN, update_golden: bool = False, skip_overnight: bool = False,
        log: Callable[[str], None] = print) -> tuple[list[dict[str, Any]], int]:
    """-> (check rows, exit code)."""
    seed = int(config.load_mission(mission)["seed"])
    out.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []

    def step(r: dict[str, Any]) -> dict[str, Any]:
        rows.append(r)
        log(f"{'PASS' if r['ok'] else 'FAIL'}  {r['name']}: {r['detail']}")
        return r

    def fresh(name: str, role: str, s: int | None = None) -> dict[str, Any]:
        b, g = RUNS[role]
        log(f"run {name}: --budget {b} --gpus {g}" + (f" --seed {s}" if s is not None else "") + f", limit {budget.BUDGET_S[b] / 60:.0f} min")
        return run_one(mission, name, b, g, out, s, pristine)
    shared, pristine = pipeline.emulator_table(), None
    if shared.is_file():                                                                             # one copy, taken before any run
        pristine = out / "emulator_table.parquet"
        shutil.copyfile(shared, pristine)
    q = fresh("quick", "quick")
    step(check_run(q))
    step(check_golden(q, golden, mission, update_golden))
    same, other = fresh("quick_same", "quick"), fresh("quick_seed", "quick", seed + 1)
    step(check_run(same))
    step(check_same_seed(q, same))
    step(check_run(other))
    step(check_other_seed(q, other))
    step(check_broken(out))
    if skip_overnight:
        step(_row("run_overnight", False, "overnight not run (--skip-overnight is for rehearsals and never passes)"))
    else:
        o = fresh("overnight", "overnight")
        step(check_run(o))
        step(check_label(o))
    if gpus >= 1:
        g4 = fresh("4h", "gpu")
        step(check_run(g4))
        step(check_label(g4))
    return rows, 0 if all(r["ok"] for r in rows) else 1


def table(rows: list[dict[str, Any]]) -> str:
    head = f"acceptance: {'PASS' if all(r['ok'] for r in rows) else 'FAIL'} ({sum(r['ok'] for r in rows)} of {len(rows)} checks pass)"
    return "\n".join([head, *(f"{'PASS' if r['ok'] else 'FAIL'}  {r['name']:<22s}{r['detail']}" for r in rows)])


def main(a: argparse.Namespace) -> int:
    out = pathlib.Path(a.out)
    started = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    rows, rc = run(a.mission, a.gpus, out, pathlib.Path(a.golden), a.update_golden, a.skip_overnight)
    text = table(rows)
    out.mkdir(parents=True, exist_ok=True)
    (out / "acceptance.txt").write_text(text + "\n")
    done = dict(mission=a.mission, gpus=a.gpus, ok=rc == 0, started=started, finished=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                git_sha=git_sha(), code_digest=pipeline.code_digest(), skip_overnight=a.skip_overnight, checks=rows)
    (out / "acceptance.json").write_text(json.dumps(done, indent=1, default=str, allow_nan=False))
    print(text)
    print(f"table: {out / 'acceptance.json'}")
    return rc
