"""`make audit`: the run proves itself and the repo carries no unfinished work.

    python -m cafe.pm.audit [run_dir ...] [--code-only | --ledgers-only | --pytest-done]

1. Ledgers: every stage of every run dir has checkpoints/<stage>/ledger.json with ok=true and zero failed checks; every
   input and output still hashes to what the ledger recorded; each stage's inputs include the previous stage's
   ledger (the chain), so a rerun of one stage without the ones after it is caught.
2. Banned patterns outside tests/fixtures/broken/: TODO, FIXME, XXX, NotImplementedError, placeholder, pytest skip /
   xfail markers, and commented-out code (a comment line that parses as a Python statement).
   The scan covers code and config (see `SCAN` for the exact list); the static app's HTML and vendored libraries and the prose documents
   are outside it, DECISIONS 205.
3. ruff, mypy, pytest with coverage gates (cafe/pm >= 90 %, cafe/pm/physics, stats, env = 100 %).
4. Mutation testing (BRIEF 5.3: >= 85 % of mutants killed on cafe/pm/physics and cafe/pm/stats). It takes hours, so it is a slow
   receipt: `make mutation` runs mutmut and stores docs/mutation.json (counts, score, a digest of the mutated code and of the tests
   that kill the mutants, date, mutmut version). The audit only reads that file and fails if it is missing, was made by different
   code or tests, or scores < 0.85, naming the command that refreshes it.
Exit 0 only if all pass; prints every failure. `--code-only` skips ruff, mypy and pytest; `--ledgers-only` checks only the ledgers of the run dirs
given (what `make ci` ends with, on the run it just made: the mutation record and the banned-token scan are the business of `make audit`,
and a clean checkout has no docs/mutation.json yet). `--pytest-done` is the whole audit except running pytest: for a suite run elsewhere in pieces
(`bin/proot_suite.sh --cov` on orca, which writes coverage.json), it still runs ruff, mypy and the scans and gates, and fails if coverage.json is missing or
older than the newest file under cafe/pm, so it cannot pass without tests having run on this code. It takes no other option.

    python -m cafe.pm.audit --mutation-record     (called by `make mutation`: writes docs/mutation.json from mutants/mutmut-cicd-stats.json)
"""
from __future__ import annotations

import ast, datetime as dt, hashlib, importlib.metadata, json, pathlib, platform, re, subprocess, sys, tomllib
from typing import Any

from .env.remote import sha256, tree_sha256
from .ledger import RUN_ROOT_FILES, STAGES, hashed, resolve, run_roots, shared_diff

ROOT = pathlib.Path(__file__).resolve().parents[2]
BANNED = re.compile(r"\b(TODO|FIXME|XXX|NotImplementedError)\b|\bplaceholder\b|pytest\.skip|mark\.skip|skipif|xfail|\bskip\("
                    r"|\bassert\b.*\bor True\s*$")                                          # the last: an assert that cannot fail
# The older `cafe/` modules the pipeline imports, directly (cfd, fea, emulator, reach, receipts, planner) or through them. Their banned-token scan is
# cheap and covers all of them; ruff covers the five that pass it (`planner` has 14 loop-closure findings in numerical code that this round does not
# touch). mypy --strict and the coverage gates are not asked of them: they are pre-mission app code, run through the pipeline and their own receipts.
IMPORTED = [f"cafe/{m}.py" for m in ("cfd", "ctrl", "dyn", "emulator", "env", "fea", "geom", "hangar", "mission", "ocean", "planner", "reach", "receipts",
                                     "shapes", "vehicle")]
# Scope (DECISIONS 205): BRIEF 5.5's `cafe/` is read as code and config. Outside the scan: cafe/static/index.html (its `placeholder="..."` form-field
# attributes), cafe/static/vendor/ (third-party three.js, Leaflet), the app's own modules the pipeline does not import, lab/, report/, and the prose
# documents other than RUNBOOK. cafe/static/app.js is scanned, with the DOM property `.placeholder` removed from a line before matching (JS_DOM_PLACEHOLDER).
SCAN = ["cafe/pm", *IMPORTED, "cafe/static/app.js", "tests", "bench", "platforms", "missions", "config", "docs/RUNBOOK.md", "Makefile"]
JS_DOM_PLACEHOLDER = re.compile(r"\.placeholder\b")
EXEMPT = ["tests/fixtures/broken/", "cafe/pm/audit.py", "tests/test_audit.py", "docs/BRIEF.md", "review/"]
GATES = {"cafe/pm": 90.0, "cafe/pm/physics": 100.0, "cafe/pm/stats": 100.0, "cafe/pm/env": 100.0}
MUTATED = ["cafe/pm/physics", "cafe/pm/stats"]
MUTATION_MIN = 0.85
MUTATION_FILE = "docs/mutation.json"
MUTATION_STATS = "mutants/mutmut-cicd-stats.json"
MUTATION_CMD = "`make mutation` (hours; from a laptop `./pm.sh make mutation`, then `./pm.sh --pull docs/mutation.json`)"


class _Unreadable(ValueError):
    """A JSON file the audit has to read is damaged; the message names it. `ledger_problems` turns it into a problem line, not a traceback."""


def _read_json(f: pathlib.Path) -> dict[str, Any]:
    """The JSON object in `f`; a truncated or foreign file (a killed or full-disk write) is `_Unreadable`."""
    try:
        d = json.loads(f.read_text())
        if not isinstance(d, dict):
            raise ValueError("not a JSON object")
    except (ValueError, OSError) as e:
        raise _Unreadable(f"{f} is not valid JSON ({e})") from e
    return d


def _store_attr(d: pathlib.Path, key: str) -> Any:
    """A zarr store's group attribute (zarr 3 `zarr.json`, zarr 2 `.zattrs`), or None."""
    for name, path in (("zarr.json", ("attributes",)), (".zattrs", ())):
        f = d / name
        if f.is_file():
            node: Any = _read_json(f)
            for k in path:
                node = node.get(k, {})
            return node.get(key)
    return None


def _dir_problems(run: str, st: str, f: pathlib.Path, recorded: str | None, tree: str | None = None) -> list[str]:
    """A directory input: a zarr store carries the sha256 of the parts manifest it was assembled from, which is what the ledger recorded; and,
    when the ledger holds `tree_sha256`, the hash over every file of the store is recomputed (a changed value or a deleted chunk changes it, the
    manifest attribute does not). The older derived surface layer ledgers have only that hash, in `recorded`."""
    have = _store_attr(f, "manifest_sha256")
    if recorded and have is not None and have != recorded and f.name != "derived.zarr":
        return [f"{run}: stage {st}: input {f} changed since the stage ran (store manifest {str(have)[:12]}, ledger {recorded[:12]})"]
    if tree is not None:
        now = tree_sha256(f)
        return [] if now == tree else [f"{run}: stage {st}: input {f} changed since the stage ran (tree {now[:12]} against ledger {tree[:12]}): "
                                       "delete it and run `fetch` again"]
    if recorded and f.name == "derived.zarr":  # an older ledger: the surface layer has no manifest, the ledger recorded the hash of every file
        return [] if tree_sha256(f) == recorded else [f"{run}: stage {st}: input {f} (the derived surface layer) changed since the stage ran"]
    return []


def _orca_problems(run: str, st: str, man: pathlib.Path) -> list[str]:
    """The orca cache manifest names the sha256 of every per-hour part: re-hash the parts that are still there."""
    out: list[str] = []
    for name, sha in _read_json(man).get("parts", {}).items():
        part = man.parent / "hours" / name
        if part.is_file() and sha256(part) != sha:
            out.append(f"{run}: stage {st}: orca part {part} changed since the cache was assembled")
    return out


def _same_place(run_dir: pathlib.Path, d: dict[str, Any]) -> bool:
    """True when ledger `d` was written on this machine (its `machine.host`) in `run_dir` itself (a place `run_roots` found in its outputs): the run was
    not copied, so what it recorded outside the run is still where it was."""
    if (d.get("machine") or {}).get("host") != platform.node():
        return False
    return any(pathlib.Path(*r).resolve() == run_dir.resolve() for r in run_roots(d))


def _shared_problems(run: str, st: str, snap: pathlib.Path, shared: pathlib.Path, here: bool) -> list[str]:
    """`snap` is the copy of a shared cache manifest the stage used (`Ledger.snapshot`; `shared` is where it came from). The shared manifest is no part
    of the check: it is rewritten when a later run grows the cache (a wider box or window, another 3-D hour) and a window outside the cached one replaces
    it, which changes nothing the run read. What the run read is the files the copy names, so each of them still has to lie in the cache directory with the
    hash the copy has (`ledger.shared_diff`; `done` asks `ledger.shared_changes`, its union). Where the cache directory is not there, `here` (the run
    is on the machine and in the place it was made: `_same_place`) makes that a problem, a deleted or moved cache; a copied run has nothing to compare
    with, and says so on stderr. A part a later ingest refetched, which the live manifest vouches for, is a note on stderr too (round 11, M-8)."""
    root = shared.parent
    if not root.is_dir():
        if here:
            return [f"{run}: stage {st}: cache directory {root} is missing (the stage read {snap.name} from it); run `fetch` again"]
        print(f"note: {run}: stage {st}: cache directory {root} is not here; the files {snap.name} names were not compared", file=sys.stderr)
        return []
    out: list[str] = []
    changes, rewrites = shared_diff(_read_json(snap), root)
    for f, was, new in rewrites:                                    # round 11, M-8: refetched by a later ingest, as the cache's manifest says: a note
        print(f"note: {run}: stage {st}: input {f}: the part this run read was refetched by a later ingest (the cache manifest lists the new bytes, "
              f"sha256 {new[:12]} against {was[:12]} in {snap.name}); this run can no longer be re-checked against it", file=sys.stderr)
    for f, sha, now in changes:
        out.append(f"{run}: stage {st}: input {f} is missing (the stage read it, {snap.name} lists it); run `fetch` again" if now is None else
                   f"{run}: stage {st}: input {f} changed since the stage ran (sha256 {now[:12]} against {sha[:12]} in {snap.name}): "
                   "the cache file was edited, or rebuilt by a later run")
    return out


DERIVED_RECORD = "derived.digest.json"        # what `surface.build` writes beside the store and ingest copies into the run: {built_from, store_sha256}


def _rebuilt_by_a_later_run(run_dir: pathlib.Path, f: pathlib.Path, i: dict[str, Any]) -> bool:
    """True when the shared store `f` (ledger input `i`) holds other bytes than this run read because a later run wrote it again, which it does whole and in
    place: nothing the earlier run made changed (its own outputs are hashed on their own, its stages checked the derived layer when they ran). What tells a
    rebuild from damage is what the run or the store itself kept; with none of it the answer is False, and the changed bytes are a problem.
    - the derived surface layer: the key it was built from (`built_from`) against the one `<run>/ingest/derived.digest.json` recorded. The key holds the code
      digest, so any code change followed by a run in the same data directory rebuilds it;
    - the ocean store (`hycom.fetch_gofs`): its own `manifest_sha256`, which only a fetch writes, against the one the ledger recorded (a ledger with the tree
      hash only; an older one keeps the manifest line);
    - the four orca stores (`orca.assemble`): the shared manifest, which it rewrites after them, against the copy this run kept (`ingest/orca_manifest.json`).
    A store with the same key and other bytes is damaged, and is not this."""
    try:
        if f.name == "derived.zarr":
            mine, now = _read_json(run_dir / "ingest" / DERIVED_RECORD).get("built_from"), _store_attr(f, "built_from")
            return isinstance(mine, str) and isinstance(now, str) and mine != now
        if not i.get("tree_sha256"):
            return False
        if (recorded := i.get("sha256")) and (have := _store_attr(f, "manifest_sha256")) is not None:
            return bool(have != recorded)
        kept, shared = run_dir / "ingest" / "orca_manifest.json", f.parent / "manifest.json"
        return kept.is_file() and shared.is_file() and sha256(kept) != sha256(shared)
    except _Unreadable:
        return False


def _stage_problems(run_dir: pathlib.Path, st: str, d: dict[str, Any], prev: pathlib.Path | None, out: list[str]) -> None:
    """The problems of one stage's ledger `d`, appended to `out`. A ledger that is valid JSON of the wrong shape raises KeyError, TypeError
    or AttributeError here, which `ledger_problems` turns into a problem line."""
    if not d.get("ok"):
        out.append(f"{run_dir.name}: stage {st}: ok=false ({d.get('error')})")
    for c in d.get("checks", []):
        if not c["ok"]:
            out.append(f"{run_dir.name}: stage {st}: self-check {c['name']} failed (value {c.get('value')}, limit {c.get('limit')})")
    roots = run_roots(d)
    for i in d.get("inputs", []):
        f = resolve(i["ref"], run_dir, roots)
        try:
            if hashed(i) and not f.exists():                       # `done` re-runs the stage for the same reason
                out.append(f"{run_dir.name}: stage {st}: input {f} is missing (the stage read it); restore it, or run `fetch` / the stage again")
            elif (i.get("sha256") or i.get("tree_sha256")) and f.is_dir():
                changed = _dir_problems(run_dir.name, st, f, i.get("sha256"), i.get("tree_sha256"))
                if changed and _rebuilt_by_a_later_run(run_dir, f, i):      # not damage, and not a problem of this run: said once, on stderr, as P-39's note
                    print(f"note: {run_dir.name}: stage {st}: input {f}: the bytes this run read were replaced by a later fetch, and this run can no longer be "
                          "re-checked against them (what the run made is checked by its own ledgers)", file=sys.stderr)
                else:
                    out += changed
            elif i.get("sha256") and f.is_file() and sha256(f) != i["sha256"]:
                out.append(f"{run_dir.name}: stage {st}: input {f} changed since the stage ran")
            if i.get("shared") and f.is_file():                      # a copy of a shared cache manifest: the files it names, not the shared one
                out += _shared_problems(run_dir.name, st, f, pathlib.Path(i["shared"]), _same_place(run_dir, d))
            elif f.name == "manifest.json" and f.is_file() and "parts" in _read_json(f):
                out += _orca_problems(run_dir.name, st, f)
        except _Unreadable as e:                                    # the sha256 line above already said a damaged file changed
            out.append(f"{run_dir.name}: stage {st}: input {e}; delete it and run `fetch` again")
    for o in d.get("outputs", []):
        f = resolve(o["path"], run_dir, roots)
        if not f.is_file():
            out.append(f"{run_dir.name}: stage {st}: output {f} is missing")
        elif sha256(f) != o["sha256"]:
            out.append(f"{run_dir.name}: stage {st}: output {f} changed since the stage ran")
    if prev is not None and prev.resolve() not in {resolve(i["ref"], run_dir, roots).resolve() for i in d.get("inputs", [])}:
        out.append(f"{run_dir.name}: stage {st}: does not record the {STAGES[STAGES.index(st) - 1]} ledger as an input (chain broken)")


def ledger_problems(run_dir: str | pathlib.Path) -> list[str]:
    run_dir = pathlib.Path(run_dir)
    out: list[str] = []
    prev: pathlib.Path | None = None
    for st in STAGES:
        p = run_dir / "checkpoints" / st / "ledger.json"
        if not p.exists():
            out.append(f"{run_dir.name}: stage {st}: no ledger")
            prev = None
            continue
        try:
            d = _read_json(p)
        except _Unreadable as e:
            out.append(f"{run_dir.name}: stage {st}: {e}; delete it and run the stage again")
            prev = None
            continue
        try:
            _stage_problems(run_dir, st, d, prev, out)
        except (KeyError, TypeError, AttributeError) as e:          # valid JSON of the wrong shape (a hand edit, other code): a line, not a traceback
            out.append(f"{run_dir.name}: stage {st}: ledger {p} is damaged or incomplete ({type(e).__name__}: {e}); delete it and run the stage again")
            prev = None
            continue
        prev = p
    return out


def _commented_code(line: str) -> bool:
    s = line.strip()
    if not s.startswith("#") or s.startswith("#!") or s.startswith("# -*-"):
        return False
    body = s.lstrip("#").strip()
    if body.startswith(("--", "==", "..")):                          # section rulers, with or without a title
        return False
    if len(body) < 6 or body.endswith(":") and " " not in body or re.match(r"^[A-Za-z ,.'\-]+$", body):
        return False
    if not re.search(r"[A-Za-z]", body) or not re.search(r"[=(\[]|^(import|from|return|def|class|for|if|while|print)\b", body):
        return False
    try:
        tree = ast.parse(body)
    except SyntaxError:
        return False
    return bool(tree.body) and not all(isinstance(n, ast.Expr) and isinstance(getattr(n, "value", None), ast.Name) for n in tree.body)


def banned(root: pathlib.Path = ROOT) -> list[str]:
    hits: list[str] = []
    files: list[pathlib.Path] = []
    for s in SCAN:
        p = root / s
        files += [p] if p.is_file() else [f for f in p.rglob("*") if f.is_file() and f.suffix in (".py", ".yaml", ".yml", ".json", ".md", ".sh", "")]
    for f in files:
        rel = str(f.relative_to(root))
        if any(rel.startswith(e) for e in EXEMPT) or "__pycache__" in rel:
            continue
        try:
            lines = f.read_text().splitlines()
        except UnicodeDecodeError:
            continue
        for n, line in enumerate(lines, 1):
            if BANNED.search(JS_DOM_PLACEHOLDER.sub("", line) if f.suffix == ".js" else line):
                hits.append(f"{rel}:{n}: banned pattern: {line.strip()[:100]}")
            elif f.suffix == ".py" and _commented_code(line):
                hits.append(f"{rel}:{n}: commented-out code: {line.strip()[:100]}")
    return hits


LOG = "audit.log"                      # every step's whole output: the printed problem keeps only its last 4000 characters (CI uploads this file)


def _run(cmd: list[str]) -> tuple[int, str]:
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    with open(ROOT / LOG, "a") as f:
        f.write(f"$ {' '.join(cmd)}\n{r.stdout}{r.stderr}\nrc={r.returncode}\n")
    return r.returncode, (r.stdout + r.stderr)[-4000:]


def coverage_problems(cov_json: str | pathlib.Path) -> list[str]:
    """The gates of `GATES` against coverage.json. A package gate of 100 % names the files and lines it misses (from `missing_lines`), so a gate
    that differs between machines (a branch that runs only with Bellhop installed) says where."""
    try:
        d = _read_json(pathlib.Path(cov_json))
        return _coverage_gates(d)
    except (_Unreadable, KeyError, TypeError, AttributeError) as e:         # a truncated or foreign file is a failed gate, not a traceback
        return [f"coverage: {cov_json} is damaged or incomplete ({type(e).__name__}: {e}); run the suite with coverage again"]


def _coverage_gates(d: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for pref, gate in GATES.items():
        tot = cov = 0
        miss: list[str] = []
        for f, v in d["files"].items():
            if f.startswith(pref + "/") or f == pref:
                tot += v["summary"]["num_statements"]
                cov += v["summary"]["covered_lines"]
                if v.get("missing_lines"):
                    miss.append(f"{f[len(pref) + 1:] or f}: {', '.join(map(str, v['missing_lines']))}")
        pct = 100.0 * cov / tot if tot else 100.0
        if pct + 1e-9 < gate:
            out.append(f"coverage {pref}: {pct:.1f} % < {gate:.0f} %" + (f" ({'; '.join(miss)})" if gate >= 100.0 and miss else ""))
    return out


def mutation_tests(root: pathlib.Path = ROOT) -> list[str]:
    """The test files mutmut runs against each mutant: `pytest_add_cli_args_test_selection` of [tool.mutmut] in pyproject.toml."""
    tests: list[str] = tomllib.loads((root / "pyproject.toml").read_text())["tool"]["mutmut"]["pytest_add_cli_args_test_selection"]
    return tests


def mutation_digest(root: pathlib.Path = ROOT) -> str:
    """sha256 over the mutated code (cafe/pm/physics, cafe/pm/stats) and the tests that kill its mutants (those files and tests/conftest.py)."""
    files = [f for d in MUTATED for f in (root / d).rglob("*.py") if "__pycache__" not in f.parts]
    files += [root / t for t in mutation_tests(root)] + [root / "tests" / "conftest.py"]
    h = hashlib.sha256()
    for f in sorted(set(files)):
        h.update(str(f.relative_to(root)).encode() + b"\0" + f.read_bytes())
    return h.hexdigest()


def mutation_score(r: dict[str, int]) -> float:
    """killed / total over every mutant mutmut generated. Survivors, timeouts, mutants no test reaches and suspicious ones all count against it."""
    return r["killed"] / r["total"] if r["total"] else 0.0


def mutation_record(root: pathlib.Path = ROOT) -> dict[str, Any]:
    """The result `make mutation` stores, from the counts `mutmut export-cicd-stats` wrote to mutants/mutmut-cicd-stats.json."""
    counts = _read_json(root / MUTATION_STATS)
    rec: dict[str, Any] = {k: counts[k] for k in ("killed", "survived", "timeout", "no_tests", "suspicious", "skipped", "segfault", "total")}
    rec.update(score=round(mutation_score(rec), 4), code_digest=mutation_digest(root), tests=mutation_tests(root), sources=MUTATED,
               date=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), mutmut=importlib.metadata.version("mutmut"))
    return rec


def mutation_problems(root: pathlib.Path = ROOT) -> list[str]:
    """Missing, stale or too-low stored mutation result; each message names the command that refreshes it."""
    path = root / MUTATION_FILE
    if not path.is_file():
        return [f"mutation: no stored result at {MUTATION_FILE}: run {MUTATION_CMD}"]
    # a truncated or foreign file is a failed gate, not a traceback
    damaged = "mutation: " + MUTATION_FILE + " is damaged or incomplete ({}: {}): run " + MUTATION_CMD
    try:
        rec = _read_json(path)
    except _Unreadable as e:
        return [damaged.format(type(e).__name__, e)]
    if rec.get("code_digest") != mutation_digest(root):
        return [f"mutation: the stored result ({rec.get('date')}) was made by different physics/stats code or tests: run {MUTATION_CMD}"]
    try:
        score = mutation_score(rec)                    # recomputed from the counts: an edited `score` field proves nothing
    except (KeyError, TypeError) as e:
        return [damaged.format(type(e).__name__, e)]
    if score + 1e-9 < MUTATION_MIN:
        return [f"mutation: {rec['killed']}/{rec['total']} mutants killed = {score:.1%} < {MUTATION_MIN:.0%}: add tests, then {MUTATION_CMD}"]
    return []


OPTIONS = ("--code-only", "--ledgers-only", "--mutation-record", "--pytest-done", "--pytest-receipt")
# The real-time tests (ArduCopter and its fake firmware bind sockets and wait on the wall clock): they fail under parallel load, so they run alone in the
# second pass. The same seven that pyproject.toml deselects for mutmut (tests/test_config_docs.py holds the two lists equal). The last two measure the
# emulator's query time against BRIEF 2.7's 10 ms: beside parallel workers they read the load, not the code (round 8 M-5).
SERIAL_TESTS = ("tests/test_uas.py::test_scrambled_motor_order_fails_the_sitl_receipts", "tests/test_uas.py::test_lockstep_machinery_answers_every_frame_once",
                "tests/test_uas.py::test_an_autopilot_that_never_arms_is_reported_and_fails_the_sitl_receipts",
                "tests/test_uas.py::test_an_autopilot_that_never_speaks_mavlink_is_reported", "tests/test_uas.py::test_a_firmware_that_dies_is_reported",
                "tests/test_emulator.py::test_query_under_10_ms_and_format", "tests/test_emulator.py::test_receipts_pass_and_fail_when_calibration_is_wrong")


def pytest_passes(workers: int) -> list[list[str]]:
    """The audit's test step as two pytest runs under one coverage record: the suite spread over `workers` processes by file, then the real-time
    tests alone with --cov-append (the whole suite serially took 180+ min on a 4-CPU hosted runner)."""
    base = [sys.executable, "-m", "pytest", "-q", "-m", "not network", "--cov=cafe/pm"]
    return [base + ["-n", str(workers), "--dist", "loadfile", "--cov-report="] + [f"--deselect={t}" for t in SERIAL_TESTS],
            base + ["--cov-append", "--cov-report=json:coverage.json", *SERIAL_TESTS]]


def root_files_unrecorded(run_dir: str | pathlib.Path) -> bool:
    """True for a run whose report ledger exists and names neither `mission.yaml` nor `plan.json` as an input: made before round 11, so an edit of either is
    not seen by `ledger_problems` (the report refuses a verdict that its cut-offs do not give, which covers the mission file)."""
    try:
        d = _read_json(pathlib.Path(run_dir) / "checkpoints" / "report" / "ledger.json")
        return not any(isinstance(i, dict) and i.get("ref") in RUN_ROOT_FILES for i in d.get("inputs", []))
    except (_Unreadable, TypeError):  # no or damaged ledger, or `inputs` not a list: `ledger_problems` says so
        return False


PYTEST_RECEIPT = "coverage.receipt.json"        # beside coverage.json: {code_digest, coverage_sha256, suite_ok, date}, written only for a suite that passed


# all the code the suite imports (cafe/receipts.py, cafe/mission.py, bench/throughput.py ...), the tests, and the data files it reads
SUITE_DIRS = ("cafe", "bench", "tests", "platforms", "config", "missions")
SUITE_FILES = ("pyproject.toml",)                                                  # addopts, markers, the coverage and mutmut configuration


def suite_digest(root: pathlib.Path = ROOT) -> str:
    """sha256 over everything the suite measures or reads that is not a document: every file under `SUITE_DIRS` (all of cafe/ and bench/, not only
    cafe/pm: the suite imports cafe.receipts, cafe.mission and bench.throughput; the tests; the platform, config and mission yaml; the schemas, the
    golden and the fixtures) and `SUITE_FILES` (pyproject.toml), by path and content, so that a file edited after the run is seen whatever its
    modification time says (rsync -a sets it back; round 11, M-10). Bytecode and `.DS_Store` do not count. The documents, `bin/` and the Makefile are not
    in it (look-ahead L0: the first version hashed the `.py` files only, and a platform or mission file edited after a green suite passed `--pytest-done`;
    its second version named only five directories, and an edit of cafe/receipts.py, cafe/mission.py, bench/throughput.py or pyproject.toml still did)."""
    h = hashlib.sha256()
    files = [f for d in SUITE_DIRS if (root / d).is_dir() for f in (root / d).rglob("*")] + [root / n for n in SUITE_FILES]
    for f in sorted(f for f in files if f.is_file() and "__pycache__" not in f.parts and f.name != ".DS_Store" and f.suffix != ".pyc"):
        h.update(str(f.relative_to(root)).encode() + b"\0" + f.read_bytes())
    return h.hexdigest()


def write_pytest_receipt(root: pathlib.Path = ROOT) -> dict[str, Any]:
    """The receipt that the suite passed on the code as it is now: the digest of that code and the sha256 of the coverage.json written with it.
    bin/proot_suite.sh writes it when every job passed; after a suite run by hand the person who saw it pass writes it
    (`python -m cafe.pm.audit --pytest-receipt`)."""
    rec: dict[str, Any] = dict(code_digest=suite_digest(root), coverage_sha256=sha256(root / "coverage.json"), suite_ok=True,
                               date=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"))
    (root / PYTEST_RECEIPT).write_text(json.dumps(rec, indent=1) + "\n")
    return rec


def coverage_stale(root: pathlib.Path = ROOT) -> list[str]:
    """Problems with coverage.json as the receipt that pytest ran on this code: absent; no receipt that the suite passed (`coverage json` writes the file
    whether the tests passed or not); a receipt for other code (a source or test file differs in content, whatever its modification time) or for another
    coverage.json."""
    cov = root / "coverage.json"
    if not cov.is_file():
        return ["pytest-done: no coverage.json: run the suite with coverage first (bin/proot_suite.sh <dir> <K> <tag> --cov)"]
    try:
        rec = _read_json(root / PYTEST_RECEIPT) if (root / PYTEST_RECEIPT).is_file() else None
    except _Unreadable as e:
        return [f"pytest-done: {e}; run the suite again"]
    if rec is None:
        return [f"pytest-done: no {PYTEST_RECEIPT}: nothing says the suite passed (bin/proot_suite.sh writes it when every job passes; after a suite you ran "
                "by hand and saw pass, `python -m cafe.pm.audit --pytest-receipt`)"]
    if rec.get("suite_ok") is not True:
        return [f"pytest-done: {PYTEST_RECEIPT} does not say the suite passed"]
    if rec.get("code_digest") != suite_digest(root):
        return ["pytest-done: a file under cafe, bench, tests, platforms, config or missions, or pyproject.toml, differs from what the suite ran on "
                "(the receipt's digest): "
                "the tests did not run on this code"]
    if rec.get("coverage_sha256") != sha256(cov):
        return ["pytest-done: coverage.json is not the one the suite's receipt was written for"]
    return []


def main(argv: list[str]) -> int:
    bad = [a for a in argv if a.startswith("--") and a not in OPTIONS]
    if bad:
        print(f"error: unknown option {bad[0]} ({', '.join(OPTIONS)})")
        return 2
    for a in argv:
        if not a.startswith("--") and not pathlib.Path(a).is_dir():
            print(f"error: {a} is not a run directory (the run directories are runs/quick, runs/overnight, runs/4h)")
            return 2
    if "--pytest-done" in argv and any(a.startswith("--") and a != "--pytest-done" for a in argv):
        print("error: --pytest-done takes no other option (it is the whole audit except pytest)")
        return 2
    if "--pytest-receipt" in argv:
        if argv != ["--pytest-receipt"]:
            print("error: --pytest-receipt takes no other option or run directory")
            return 2
        if not (ROOT / "coverage.json").is_file():
            print("error: no coverage.json: run the suite with coverage first, and write the receipt only for a suite you saw pass")
            return 2
        write_pytest_receipt(ROOT)
        print(f"wrote {PYTEST_RECEIPT}")
        return 0
    if "--mutation-record" in argv:
        try:
            rec = mutation_record(ROOT)
        except (_Unreadable, KeyError, TypeError, OSError) as e:           # mutmut's counts are missing, truncated or not what it writes
            print(f"error: {MUTATION_STATS} cannot be used ({type(e).__name__}: {e}): run `make mutation`")
            return 2
        (ROOT / MUTATION_FILE).write_text(json.dumps(rec, indent=1) + "\n")
        print(f"wrote {MUTATION_FILE}")
        return 0
    ledgers_only = "--ledgers-only" in argv
    code_only = "--code-only" in argv or ledgers_only
    pytest_done = "--pytest-done" in argv
    runs = [a for a in argv if not a.startswith("--")]
    problems: list[str] = []
    for r in runs:
        problems += ledger_problems(r)
        if root_files_unrecorded(r):
            print(f"note: {r}: the report ledger records neither mission.yaml nor plan.json (a run from before round 11): an edit of either is not seen here")
    if not ledgers_only:
        problems += banned()
        problems += mutation_problems(ROOT)
    if not code_only:
        (ROOT / LOG).write_text("")
        rc, out = _run(["ruff", "check"])
        if rc:
            problems.append("ruff:\n" + out)
        rc, out = _run(["mypy"])
        if rc:
            problems.append("mypy:\n" + out)
        if pytest_done:
            problems += coverage_stale(ROOT)
        else:
            from . import par
            for cmd in pytest_passes(par.workers()):
                rc, out = _run(cmd)
                if rc:
                    problems.append("pytest:\n" + out)
        if (ROOT / "coverage.json").exists():
            problems += coverage_problems(ROOT / "coverage.json")
    for p in problems:
        print("AUDIT FAIL:", p)
    if not code_only:
        print(f"the whole output of ruff and mypy{'' if pytest_done else ' and pytest'} is in {LOG}")
    print(f"audit: {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
