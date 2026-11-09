"""`python -m cafe.pm acceptance --mission M --gpus N --out DIR [--golden FILE] [--update-golden [--golden-mission NAME]] [--skip-overnight]`: BRIEF 5.3, 0.1.

Every run is a fresh `python -m cafe.pm run` in its own process and its own run directory under DIR (`quick`, `quick_same`, `quick_seed`,
`overnight`, and `4h` when N >= 1), timed by the wall clock against `budget.BUDGET_S`: quick 20 min, overnight 10 h, 4h 4 h. The limit counts the compute
stages with a warm cache: a `python -m cafe.pm fetch` of the same mission runs first (a few seconds when the cache is warm; a cold network fetch is the
separate step of RUNBOOK 4, whose duration depends on the lab's link, not on `--budget`) and only the `run` after it is timed. The checks:

    run_<name>        the fetch and the run exit 0, the run writes report/report.json and finishes within its budget (a run is killed at twice the
                      limit); the row shows the run's wall, the ingest wall and whether the fetch was cold
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
(not for other_seed), class, platform, the set of vehicles and links, and n (not for other_seed: the stopping rule ends a vehicle at 32 members under one seed
and at 64 under another, and Newcombe's interval takes the two n) must match exactly. A verdict must be identical wherever either run has it
decided, that is wherever `stats.intervals.decided_region` at the stopper's confidence (`stats.sequential.STOP_CONF`) puts the whole P(fail) interval
inside GO, MARGINAL (0.10 to 0.40) or NO-GO. The rule for the verdicts that are undecided in both runs (a vehicle near a threshold at a quick budget
cannot be decided): such a verdict may differ, but only within the interval logic. It is allowed when the two runs' P(fail) intervals at the stopper's
confidence overlap, and then it is named in the row's detail ("uas: MARGINAL -> GO, undecided in both at n = 32"); when they do not overlap the two runs
disagree about P(fail) itself and it is a problem, decided or not. A verdict decided in either run must be identical. A link's verdict NOT EXERCISED
(stage 1: required at no sample) is no estimate of P(fail), so it must be identical in both runs whatever the intervals say (round 9, M-17). P(fail) is judged
by Newcombe's (1998, Stat. Med. 17:873, method 10) hybrid
Wilson-score interval for the difference of the two proportions, `intervals.newcombe_diff`, which must contain 0 at a family-wise 95 %: Bonferroni over the
vehicles and links compared, so each entry is judged at 1 - 0.05 / entries. (A new estimate inside the 90 % interval of an independent one fails about a
quarter of the time even when nothing is wrong.) The golden is a same-seed comparison, not an independent one: there the counts are the run's own, so each
k_fail may differ by at most `SAME_SEED_K_TOL` (1) member, and each entry's `p_fail` must be its own k_fail / n and its `conf` the same in both (round 11,
M-4); Newcombe is for `other_seed`. The `same_seed` check is exact equality and is unchanged. Timings, the
dates, the host and paths are not in the golden. The golden is a regression snapshot of this tool's own output from a quick run someone reviewed, not
an independent expectation: it can say the tool still does what it did, never that what it did is right (docs/BRIEF.md section 6 holds the independent
expectation, and the credibility report compares the run with it). Its `source` is its provenance: the git sha it was made from (a commit, from a
checkout that was clean), the code digest, and the reviewed run (the run's name and the sha-256 of its report.json); a golden without that is a FAIL
that names the command writing a new one. A missing golden is a FAIL that names the command writing it, and so is one that is not JSON, not an object, or whose
`summary` is missing or of the wrong structure (`shape_problems`: a problem line that names the key, never a traceback). `--update-golden` rewrites it
from the quick run and that check then FAILs ("updated, not compared"), so a gate cannot be passed by overwriting its reference.
`--update-golden` refuses to overwrite a golden of another mission, or a file that is not a golden, unless `--golden-mission NAME` names this run's
mission (round 12, M-33); the first write, with no file, needs nothing.
`--skip-overnight` is for rehearsals: the overnight check FAILs with "overnight not run". Exit 0 only if every check passes.
DIR/acceptance.json and DIR/acceptance.txt hold the result.
"""
from __future__ import annotations

import argparse, datetime as dt, hashlib, html, json, os, pathlib, re, shlex, shutil, subprocess, sys, time
from collections.abc import Callable, Iterator
from typing import Any

from . import budget, config, credibility, pipeline, receipts
from .ledger import git_dirty, git_sha
from .stage1 import NOT_EXERCISED
from .stats import intervals, sequential

ROOT = pathlib.Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "tests" / "golden" / "tepex_c_demo_quick.json"
BROKEN = ROOT / "tests" / "fixtures" / "broken" / "wave_direction.yaml"
WAVE_MODULE = "pm.env.wave_direction"
RUNS: dict[str, tuple[str, int]] = dict(quick=("quick", 0), overnight=("overnight", 0), gpu=("4h", 1))      # role -> (budget, gpus)
VOLATILE = ("run", "machine.wall_s", "machine.git_sha", "machine.versions", "machine.machine",   # report.json paths that differ between identical runs
            # the measured side of planned/measured (round 5, M-13; round 6, M-17)
            "machine.timing.stage1.measured", "machine.timing.variants.measured", "machine.timing.stage1b_sensitivity.measured",
            "machine.timing.total")                                              # (round 12, M-9: the sum of the walls, and its ratio to the budget)
HOLDOUT, CREDIBILITY = "emulator:output:holdout.json", "report:output:credibility.json"            # receipts whose files hold a timing / the run's name
KILL_AT = 2.0                                                                                          # a run is killed at this multiple of its limit
EPS = 1e-9
FAMILY_ALPHA = 0.05                                                                                    # family-wise error of the P(fail) comparisons


def _execute(argv: list[str], env: dict[str, str], log: pathlib.Path, timeout: float | None) -> int:
    """`python -m cafe.pm *argv` from the repo root, output to `log`; -> exit code (124 when killed at `timeout`, as timeout(1) does)."""
    with open(log, "w") as f:
        try:
            return subprocess.run([sys.executable, "-m", "cafe.pm", *argv], cwd=ROOT, env=env, stdout=f, stderr=subprocess.STDOUT, timeout=timeout).returncode
        except subprocess.TimeoutExpired:
            return 124


RUN_NAMES = ("quick", "quick_same", "quick_seed", "overnight", "4h")                                   # the run directories `run` makes in --out


def refuse_wiped_mission(mission: str, out: pathlib.Path, names: tuple[str, ...]) -> None:
    """ConfigError when `mission` lies inside out/<name> or out/<name>_fetch for a name in `names`: `run_one` removes both before its subprocesses read
    the mission, so a run's own mission.yaml would be gone (and fetch would say `file not found`). `run` asks for every run name at once, so a mission
    in the directory of the last run is refused before the first one starts, not after hours (round 9, M-12 sibling)."""
    m = pathlib.Path(mission).resolve()
    for n in names:
        for d in (out / n, out / f"{n}_fetch"):
            if m.is_relative_to(d.resolve()):
                raise config.ConfigError(f"--mission {mission} is inside {d}, which acceptance removes before it runs; copy the mission out of {out} "
                                         "(a run's own copy is <run dir>/mission.yaml)")


MARKER = ".cafe_acceptance"                                                                            # in --out: acceptance claimed the directory
OWN_FILES = ("acceptance.json", "acceptance.txt", "emulator_table.parquet", "receipts_broken.json", "receipts_wave_direction.json",
             "receipts_broken.log")                                                                    # names only `run` writes into --out


def claim_out(out: pathlib.Path, names: tuple[str, ...]) -> None:
    """Acceptance removes only what it made itself (round 10, M-12). `out` is marked on first use, before anything is removed, so a run killed half-way
    is rerunnable. An unmarked `out` that already holds out/<name>, out/<name>_fetch or either log for a name in `names` (or is itself a run: plan.json,
    checkpoints/) is somebody's: ConfigError, nothing touched. `run_one` calls it for the one site that deletes, `run` for every name before hour one.
    An unmarked `out` that holds one of OWN_FILES and is not itself a run was made by an acceptance run from before the marker existed (the Makefile's
    runs/acceptance after an upgrade): it is marked and replaced as before, so `make acceptance` needs no hand step."""
    if (out / MARKER).is_file():
        return
    itself = [out / "plan.json", out / "checkpoints"]
    mine = [p for n in names for p in (out / n, out / f"{n}_fetch", out / f"{n}.log", out / f"{n}_fetch.log")] + itself
    held = [p.name for p in mine if os.path.lexists(p)]
    earlier = any((out / f).is_file() for f in OWN_FILES) and not any(os.path.lexists(p) for p in itself)
    if held and not earlier:
        raise config.ConfigError(f"--out {out} holds {', '.join(held)}, and acceptance replaces those on every run; use an empty directory or a new one "
                                 f"(`make acceptance` uses runs/acceptance), or move them away and acceptance will mark {out} as its own")
    out.mkdir(parents=True, exist_ok=True)
    (out / MARKER).write_text("made by `python -m cafe.pm acceptance`; the runs in this directory are replaced on every run\n")


def run_one(mission: str, name: str, budget_name: str, gpus: int, out: pathlib.Path, seed: int | None = None,
            table: pathlib.Path | None = None) -> dict[str, Any]:
    """A fresh run in out/name with its own emulator table out/name/emulator_table/train.parquet: a copy of `table` (the pristine shared table),
    or none yet when `table` is None, so no run sees another's rows and none appends to the shared table.
    `fetch` runs first, into out/<name>_fetch; only `run` is timed. -> {name, mission, budget, gpus, seed, dir, log, rc, wall_s, limit_s, report (report.json
    or None), fetch_rc, fetch_wall_s, cold_fetch (the fetch's ingest ledger says it downloaded), ingest_s (the run's own ingest stage)}."""
    refuse_wiped_mission(mission, out, (name,))
    claim_out(out, (name,))
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
    fd = out / f"{name}_fetch"
    shutil.rmtree(fd, ignore_errors=True)
    t = time.monotonic()
    frc = _execute(["fetch", "--mission", str(pathlib.Path(mission).resolve()), "--out", str(fd.resolve()), "--fresh"], dict(os.environ),
                   out / f"{name}_fetch.log", None)
    fetch_wall = time.monotonic() - t
    base = dict(name=name, mission=mission, budget=budget_name, gpus=gpus, seed=seed, dir=d, limit_s=limit, fetch_rc=frc, fetch_wall_s=fetch_wall,
                cold_fetch=any(str(n).startswith("cold fetch") for n in (_ledger(fd) or {}).get("notes", [])))
    if frc != 0:                                                                                       # nothing to time: the run would start from a cold cache
        return dict(base, log=out / f"{name}_fetch.log", rc=frc, wall_s=0.0, ingest_s=None, report=None)
    t = time.monotonic()
    rc = _execute(argv, dict(os.environ), out / f"{name}.log", KILL_AT * limit)
    wall = time.monotonic() - t
    rj = d / "report" / "report.json"
    return dict(base, log=out / f"{name}.log", rc=rc, wall_s=wall, ingest_s=(_ledger(d) or {}).get("wall_s"),
                report=json.loads(rj.read_text()) if rj.is_file() else None)


def _ledger(run: pathlib.Path) -> dict[str, Any] | None:
    """The ingest ledger of a run directory, or None."""
    p = run / "checkpoints" / "ingest" / "ledger.json"
    return json.loads(p.read_text()) if p.is_file() else None


def _row(name: str, ok: bool, detail: str, **values: Any) -> dict[str, Any]:
    return dict(name=name, ok=bool(ok), detail=detail, values=values)


def check_run(r: dict[str, Any]) -> dict[str, Any]:
    """Exit 0, a report, and the wall-clock limit."""
    why = []
    if r.get("fetch_rc"):
        why.append(f"fetch exit code {r['fetch_rc']}: the run needs a warm cache, so run `python -m cafe.pm fetch --mission {r['mission']}` first "
                   f"(RUNBOOK 4; with CAFE_OFFLINE=1 a cold cache cannot be filled), see {r['log']}")
    elif r["rc"] != 0:
        why.append(f"exit code {r['rc']}" + (" (killed at the time limit)" if r["rc"] == 124 else "") + f", see {r['log']}")
    elif r["report"] is None:
        why.append(f"no report/report.json in {r['dir']}")
    if r["wall_s"] > r["limit_s"]:
        why.append(f"took {r['wall_s'] / 60:.1f} min, over the {r['limit_s'] / 60:.0f} min limit of --budget {r['budget']}")
    ok_text = f"--budget {r['budget']} --gpus {r['gpus']}: {r['wall_s'] / 60:.1f} min of the {r['limit_s'] / 60:.0f} min limit"
    if "fetch_wall_s" in r:                                                                              # (an older run dict has none of these)
        ing = "" if r.get("ingest_s") is None else f"ingest {r['ingest_s']:.0f} s, "
        ok_text += f" ({ing}fetch {r['fetch_wall_s']:.0f} s, neither counted against --budget; cold fetch: {'yes' if r['cold_fetch'] else 'no'})"
    return _row(f"run_{r['name']}", not why, "; ".join(why) or ok_text, budget=r["budget"], gpus=r["gpus"], wall_s=r["wall_s"], limit_s=r["limit_s"],
                rc=r["rc"], fetch_wall_s=r.get("fetch_wall_s"), ingest_s=r.get("ingest_s"), cold_fetch=r.get("cold_fetch"))


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


def _interval(e: dict[str, Any]) -> tuple[float, float]:
    lo, hi, _ = intervals.interval(e["k_fail"], e["n"], sequential.STOP_CONF)
    return lo, hi


SAME_SEED_K_TOL = 1             # members: one seed on one code is one set of members, but another machine's rounding may move one that sits on a limit


def _same_seed_problems(kind: str, name: str, g: dict[str, Any], r: dict[str, Any]) -> list[str]:
    """Two summaries from the same seed (the golden against a new run) must agree member for member, not within a sampling interval: k_fail within
    SAME_SEED_K_TOL, and each summary's `p_fail` the ratio of its own counts and the same `conf`, so an edited golden cannot be passed by a run that
    reproduces the old counts (round 11, M-4)."""
    bad = [f"{kind} {name}: k_fail {r['k_fail']} of {r['n']} now against {g['k_fail']} in the reference: the same seed gives the same members "
           f"(at most {SAME_SEED_K_TOL} may differ across machines)"] if abs(r["k_fail"] - g["k_fail"]) > SAME_SEED_K_TOL else []
    for who, e in (("the reference", g), ("now", r)):
        if abs(e["p_fail"] - e["k_fail"] / e["n"]) > EPS:
            bad.append(f"{kind} {name}: p_fail {e['p_fail']!r} {who} is not k_fail / n = {e['k_fail']} / {e['n']}")
    if g["conf"] != r["conf"]:
        bad.append(f"{kind} {name}: conf {g['conf']!r} in the reference, {r['conf']!r} now")
    return bad


def _damage(e: dict[str, Any], who: str) -> list[str]:
    """What an entry of a summary lacks of the numbers `compare` reads (the count, `p_fail`, `conf`): the one list of the reference's and the new entry's
    problems, so that an edited golden is a problem line whatever field was damaged (look-ahead L0, twice)."""
    bad = [] if credibility.counts_ok(e.get("k_fail"), e.get("n")) else [
        f"k_fail {e.get('k_fail')!r} of n {e.get('n')!r} {who} is not a count (integers, n >= 1, 0 <= k_fail <= n)"]
    if not credibility.real_ok(e.get("p_fail")):
        bad.append(f"p_fail {e.get('p_fail')!r} {who} is not a finite number")
    if not credibility.conf_ok(e.get("conf")):
        bad.append(f"conf {e.get('conf')!r} {who} is not a number with 0 < conf < 1")
    return bad


def shape_problems(s: Any, who: str) -> list[str]:
    """What a summary lacks of the structure `compare` walks (`summary` makes it; a golden is read from a file that anyone can edit): an object with the
    mission and the seed, and `vehicles` and `links` that are objects of objects. One line per damaged key, naming it. This is the one test of the shape
    for every reader of a golden (round 12, P-R11L0-4): `compare` calls it on both sides before it reads a key, `check_golden` through `compare`."""
    if s is None:
        return [f"summary {who} is missing"]
    if not isinstance(s, dict):
        return [f"summary {who} is {type(s).__name__}, not an object"]
    bad = [f"summary {who} has no {f!r}" for f in ("mission", "seed") if f not in s]
    for kind in ("vehicles", "links"):
        if not isinstance(s.get(kind), dict):
            bad.append(f"summary {who}: {kind!r} is {'missing' if kind not in s else type(s[kind]).__name__ + ', not an object'}")
        else:
            bad += [f"summary {who}: {kind} {k!r} is {type(e).__name__}, not an object" for k, e in s[kind].items() if not isinstance(e, dict)]
    return bad


def compare(ref: Any, new: Any, seed: bool = True) -> tuple[list[str], list[str]]:
    """(problems, notes) of `new` against `ref` (both from `summary`): the exact fields must match; a verdict must match wherever either run has it
    decided; a change undecided in both is a note when the two runs' STOP_CONF intervals on P(fail) overlap and a problem when they do not; and
    Newcombe's interval for the difference of the two P(fail), at 1 - FAMILY_ALPHA / m
    for the m entries compared (Bonferroni), must contain 0. seed=False leaves the mission seed out (the other_seed check). A summary whose structure is
    damaged (`shape_problems`) is a list of those problems and nothing else."""
    if shaped := shape_problems(ref, "in the reference") + shape_problems(new, "now"):
        return shaped, []
    bad = [f"{f}: {ref[f]!r} in the reference, {new[f]!r} now" for f in ("mission", "seed") if ref[f] != new[f] and (seed or f != "seed")]
    notes: list[str] = []
    conf = 1 - FAMILY_ALPHA / max(_entries(ref, new), 1)
    for kind in ("vehicles", "links"):
        a, b = ref[kind], new[kind]
        if a.keys() != b.keys():
            bad.append(f"{kind}: {sorted(a)} in the reference, {sorted(b)} now")
        for k in sorted(a.keys() & b.keys()):
            g, r = a[k], b[k]
            exact = ("cls", "platform", "n") if seed else ("cls", "platform")       # round 12, M-32: n depends on the data (the stopping rule)
            bad += [f"{kind} {k}: {f} {g.get(f)!r} in the reference, {r.get(f)!r} now" for f in exact if g.get(f) != r.get(f)]
            notcount = [f"{kind} {k}: {what}" for who, e in (("in the reference", g), ("now", r)) for what in _damage(e, who)]
            if notcount:                                  # an edited golden (n = 0, a p_fail of None, no conf): a problem line, not a traceback (look-ahead L0)
                bad += notcount
                continue
            if g.get("verdict") != r.get("verdict"):
                (glo, ghi), (rlo, rhi) = _interval(g), _interval(r)
                if _decided(g) or _decided(r) or NOT_EXERCISED in (g.get("verdict"), r.get("verdict")):           # round 9, M-17: not a matter of sampling
                    bad.append(f"{kind} {k}: verdict {g.get('verdict')!r} in the reference, {r.get('verdict')!r} now")
                elif glo > rhi or rlo > ghi:
                    bad.append(f"{kind} {k}: verdict {g['verdict']!r} in the reference, {r['verdict']!r} now; "
                               f"undecided in both, but the {sequential.STOP_CONF:.0%} "
                               f"intervals on P(fail), {glo:.3f} to {ghi:.3f} and {rlo:.3f} to {rhi:.3f}, do not overlap")
                else:
                    at = f"n = {g['n']}" if g["n"] == r["n"] else f"n = {g['n']} and {r['n']}"
                    notes.append(f"{kind} {k}: {g['verdict']} -> {r['verdict']}, undecided in both at {at}")
            if seed:                                                    # round 11, M-4: one seed, one code: the counts are the run's own, not a draw
                bad += _same_seed_problems(kind, k, g, r)
                continue
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


_dirty = git_dirty                                      # the checkout's `git status`, else $CAFE_GIT_DIRTY (pm.sh sets it for a copy without .git), else None


def provenance_problems(source: Any) -> list[str]:
    """What a golden's `source` lacks to say where it came from: a commit, the code digest, a checkout known to be clean (unknown is a problem too),
    the reviewed run. A `source` that is not an object lacks all of it."""
    if not isinstance(source, dict):
        return [f"source is {type(source).__name__}, not an object"]
    bad = []
    if not re.fullmatch(r"[0-9a-f]{40}", str(source.get("git_sha", ""))):
        bad.append(f"git_sha {source.get('git_sha')!r} is not a commit")
    if not source.get("code_digest"):
        bad.append("no code_digest")
    if source.get("dirty") is True:
        bad.append("made from a checkout with uncommitted changes, so its git sha does not describe the code")
    elif source.get("dirty") is None:
        bad.append("cannot tell whether the checkout was clean (no .git and no $CAFE_GIT_DIRTY): run it from a git checkout or through ./pm.sh")
    run = source.get("reviewed_run") or {}
    if not isinstance(run, dict) or not (run.get("name") and run.get("report_sha256")):
        bad.append("no reviewed_run (the name of the run it was made from and the sha-256 of its report.json)")
    return bad


def _base_command(mission: str, gpus: int) -> str:
    """The one copy of the command that writes a golden: `update_command` prints it and adds `--out` and the golden flags after it, `_golden_record`
    stores it as it is, without the directory, which belongs to one machine (round 13, M-7, M-11)."""
    return f"python -m cafe.pm acceptance --mission {shlex.quote(mission)} --gpus {gpus} --update-golden"


def _write_atomic(p: pathlib.Path, text: str) -> None:
    """`text` in `p` through a sibling temporary and os.replace, through a symlink to the file it names: a write cut short (disk full, killed) leaves the
    old file, never half of a new one that reads as "not a golden file" (round 13, M-17)."""
    p = p.resolve()
    tmp = p.with_name(p.name + ".tmp")
    try:
        tmp.write_text(text)
        os.replace(tmp, p)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _golden_record(r: dict[str, Any], mission: str) -> dict[str, Any]:
    report = hashlib.sha256((r["dir"] / "report" / "report.json").read_bytes()).hexdigest()
    return dict(schema=1, command=_base_command(mission, r["gpus"]),
                source=dict(git_sha=git_sha(), dirty=_dirty(), code_digest=pipeline.code_digest(), reviewed_run=dict(name=r["dir"].name, report_sha256=report),
                            date=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), budget=r["budget"], gpus=r["gpus"]),
                summary=summary(r["report"]))


def golden_refusal(golden: pathlib.Path, name: str, allowed: str | None = None) -> str | None:
    """Why `--update-golden` may not write `golden` for the mission `name`, or None. A golden that is there must be one for the same mission: a file that
    is not a golden (unreadable, not an object, no summary.mission) or one for another mission is somebody's reference, and one `--update-golden` from
    the CI fixture would replace the demo's. `allowed` is the mission named by `--golden-mission`: it lets that mission replace the file. What no flag
    can mend comes first and is checked for `allowed` too: the path is not a file (a directory), it sits below something that is not a directory, or
    the directory that receives it is not writable, so the write would fail after the first long run (round 13, M-17). The first write, with no file,
    is otherwise always allowed (round 12, M-33)."""
    where = golden.parent
    while not where.exists():                                       # the nearest directory that is there: the one mkdir and the write start from
        where = where.parent
    if golden.exists() and not golden.is_file():
        return f"{golden} is not a file: not written, name a file with `--golden`"
    if not where.is_dir() or not os.access(where, os.W_OK | os.X_OK):
        return f"{where} is not a directory this user can write to, so {golden} cannot be written: not written, name a file with `--golden`"
    if not golden.exists():
        return None
    try:
        had = json.loads(golden.read_text())["summary"]["mission"]
    except (OSError, ValueError, KeyError, TypeError):
        had = None
    had = had if isinstance(had, str) else None                                                  # {"summary": {"mission": 5}} is no golden either
    if had == name or allowed == name:
        return None
    what = "is not a golden file (no summary.mission)" if had is None else f"is the golden of mission {had!r}"
    return (f"{golden} {what} and this run is mission {name!r}: not overwritten. To replace it with this mission's golden "
            f"add `--golden-mission {shlex.quote(name)}`, or name another file with `--golden`")


def update_command(golden: pathlib.Path, mission: str, gpus: int, name: str, out: pathlib.Path) -> str:
    """The command that writes `golden` from a quick run of `mission` (whose report names itself `name`), as the messages that ask for a new golden print it. It
    carries what `acceptance` needs to be accepted at all, after the base command (the old prefix is unchanged): `--out`, required by the parser, a
    fresh sibling of `out` (the directory of the run being judged, which holds runs the new command would replace), then what
    `--update-golden` needs: `--golden` when the file is not the default one, `--golden-mission` when `golden_refusal` would refuse the write (the file is
    damaged, or the golden of another mission) and the flag mends it. The same test as the refusal's, so the advice cannot be refused, and every word
    that is ours to choose is shlex-quoted, so it pastes as one command whatever the paths and the name hold
    (look-ahead L0 after round 12, M-33; `--out`, round 13, M-11)."""
    fresh = out.parent / ((out.name or "acceptance") + "_golden")
    return (_base_command(mission, gpus) + f" --out {shlex.quote(str(fresh))}" + (f" --golden {shlex.quote(str(golden))}" if golden != GOLDEN else "")
            + (f" --golden-mission {shlex.quote(name)}" if golden_refusal(golden, name) and not golden_refusal(golden, name, name) else ""))


def check_golden(r: dict[str, Any], golden: pathlib.Path, mission: str, update: bool, golden_mission: str | None = None) -> dict[str, Any]:
    if r["report"] is None:
        return _row("golden_diff", False, "the quick run wrote no report to compare")
    cmd = update_command(golden, mission, r["gpus"], r["report"]["mission"]["name"], r["dir"].parent)
    if update:
        if why := golden_refusal(golden, r["report"]["mission"]["name"], golden_mission):
            return _row("golden_diff", False, f"golden NOT updated: {why}", updated=False, refused=True, golden=str(golden))
        golden.resolve().parent.mkdir(parents=True, exist_ok=True)
        _write_atomic(golden, json.dumps(_golden_record(r, mission), indent=1, allow_nan=False) + "\n")
        return _row("golden_diff", False, f"golden {golden} UPDATED from this run, not compared: rerun without --update-golden to check against it",
                    updated=True)
    if golden.exists() and not golden.is_file():                       # a directory: no command can write it, and `cmd` would be refused too
        return _row("golden_diff", False, f"golden {golden} is not a file: name a file with `--golden`", golden=str(golden))
    if not golden.is_file():
        return _row("golden_diff", False, f"no golden file at {golden}: write it from a quick run you have reviewed with `{cmd}`", missing=True)
    try:
        g = json.loads(golden.read_text())
    except (OSError, ValueError) as e:                                 # not JSON, not UTF-8, unreadable: a problem line naming the file, not a traceback
        return _row("golden_diff", False, f"golden {golden.name} cannot be read as JSON ({type(e).__name__}: {str(e)[:100]}): write a new one from a quick "
                                          f"run you have reviewed with `{cmd}`", problems=[str(e)[:100]], golden=str(golden))
    if not isinstance(g, dict):
        return _row("golden_diff", False, f"golden {golden.name} is {type(g).__name__}, not an object: write a new one from a quick run you have "
                                          f"reviewed with `{cmd}`", problems=["not an object"], golden=str(golden))
    prov = provenance_problems(g.get("source", {}))
    if prov:
        return _row("golden_diff", False, f"golden {golden.name} has no provenance ({'; '.join(prov)}): write a new one from a quick run you have reviewed, "
                                          f"on a clean checkout, with `{cmd}`", provenance=prov, golden=str(golden))
    bad, notes = compare(g.get("summary"), summary(r["report"]))
    n = 0 if bad else len(g["summary"]["vehicles"]) + len(g["summary"]["links"])
    return _row("golden_diff", not bad, ("; ".join(bad[:6]) + (f" (+{len(bad) - 6} more)" if len(bad) > 6 else "") if bad else
                f"{n} verdicts and P(fail) agree with {golden.name} (git {g['source']['git_sha'][:10]})") + _allowed(notes),
                problems=bad, notes=notes, golden=str(golden))


def _drop(rep: dict[str, Any], path: str) -> None:
    *head, last = path.split(".")
    node = rep
    for k in head:
        node = node.get(k, {})
    node.pop(last, None)


def _each_str(o: Any, f: Callable[[str], str]) -> Any:
    """`o` (parsed JSON) with `f` applied to every string, dict keys included."""
    if isinstance(o, dict):
        return {(f(k) if isinstance(k, str) else k): _each_str(v, f) for k, v in o.items()}
    if isinstance(o, list):
        return [_each_str(v, f) for v in o]
    return f(o) if isinstance(o, str) else o


def normalize(rep: dict[str, Any], run_dir: pathlib.Path) -> dict[str, Any]:
    """report.json without the fields that legitimately differ between two identical runs: VOLATILE, each trained emulator's query time, the
    sha-256 of holdout.json (it holds that time), and the run directory's path; credibility.json's sha-256 is replaced by that of the file without
    the run directory (its path and its own "run" field), or dropped when the file is not there."""
    def unrun(text: str) -> str:               # on parsed strings, not on JSON text, which escapes a non-ASCII letter, a quote and a backslash in the path
        return text.replace(str(run_dir.resolve()), "<run>").replace(str(run_dir), "<run>")
    out: dict[str, Any] = _each_str(rep, unrun)
    for p in VOLATILE:
        _drop(out, p)
    for e in out.get("emulator", {}).get("vehicles", {}).values():
        e.get("acceptance", {}).pop("query_ms", None)
    cred = run_dir / "report" / "credibility.json"
    for r in out.get("receipts", []):
        if r.get("id") == HOLDOUT or (r.get("id") == CREDIBILITY and not cred.is_file()):
            r.pop("sha256", None)
        elif r.get("id") == CREDIBILITY:
            c = _each_str(json.loads(cred.read_text()), unrun)
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
        return _row("broken_config", False, config.os_error_text(e))
    (out / "receipts_broken.log").write_text("\n".join(lines) + "\n")
    caught = [r["id"] for r in rows if r["kind"] == "fail" and r["module"] == WAVE_MODULE]
    ok = rc == 0 and bool(caught) and base_rc == 0
    why = ("the broken configuration failed no receipt" if rc != 0
           else "no wave-direction receipt failed under the broken configuration (other receipts did)" if not caught
           else "the wave-direction receipts fail even without the broken configuration")
    return _row("broken_config", ok, f"{len(caught)} wave-direction receipts fail under {BROKEN.name}: {', '.join(caught[:3])}" if ok else why,
                caught=caught, exit_code=rc, baseline_exit_code=base_rc)


def run(mission: str, gpus: int, out: pathlib.Path, golden: pathlib.Path = GOLDEN, update_golden: bool = False, skip_overnight: bool = False,
        log: Callable[[str], None] = print, golden_mission: str | None = None) -> tuple[list[dict[str, Any]], int]:
    """-> (check rows, exit code). `golden_mission`: the mission `--golden-mission` lets replace a golden of another mission."""
    spec = config.load_mission(mission)
    seed = int(spec["seed"])
    if update_golden and (why := golden_refusal(golden, spec["name"], golden_mission)):          # before hours of runs, not after (check_golden holds it too)
        row = _row("golden_diff", False, f"golden NOT updated, and no run started: {why}", updated=False, refused=True, golden=str(golden))
        log(f"FAIL  {row['name']}: {row['detail']}")
        return [row], 1
    refuse_wiped_mission(mission, out, RUN_NAMES)
    claim_out(out, RUN_NAMES)
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
    step(check_golden(q, golden, mission, update_golden, golden_mission))
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
    rows, rc = run(a.mission, a.gpus, out, pathlib.Path(a.golden), a.update_golden, a.skip_overnight, golden_mission=getattr(a, "golden_mission", None))
    text = table(rows)
    out.mkdir(parents=True, exist_ok=True)
    _write_atomic(out / "acceptance.txt", text + "\n")
    done = dict(mission=a.mission, gpus=a.gpus, ok=rc == 0, started=started, finished=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                git_sha=git_sha(), code_digest=pipeline.code_digest(), skip_overnight=a.skip_overnight, checks=rows)
    _write_atomic(out / "acceptance.json", json.dumps(done, indent=1, default=str, allow_nan=False))
    print(text)
    print(f"table: {out / 'acceptance.json'}")
    return rc
