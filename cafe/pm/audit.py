"""`make audit`: the run proves itself and the repo carries no unfinished work.

    python -m cafe.pm.audit [run_dir ...] [--code-only | --ledgers-only]

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
and a clean checkout has no docs/mutation.json yet).

    python -m cafe.pm.audit --mutation-record     (called by `make mutation`: writes docs/mutation.json from mutants/mutmut-cicd-stats.json)
"""
from __future__ import annotations

import ast, datetime as dt, hashlib, importlib.metadata, json, pathlib, re, subprocess, sys, tomllib
from typing import Any

from .env.remote import sha256

ROOT = pathlib.Path(__file__).resolve().parents[2]
STAGES = ["ingest", "hangar", "stage1", "windows", "stage3", "refit", "stage1b", "emulator", "report"]
BANNED = re.compile(r"\b(TODO|FIXME|XXX|NotImplementedError)\b|\bplaceholder\b|pytest\.skip|mark\.skip|skipif|xfail|\bskip\(")
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


def _resolve(ref: str, run_dir: pathlib.Path) -> pathlib.Path:
    """Where a path a ledger recorded is now. A run that was moved or copied keeps its absolute paths from the machine it ran on, so a path
    that goes through a directory named like the audited run is looked up under the audited run first, else where it was recorded."""
    p = pathlib.Path(ref)
    for i in range(len(p.parts) - 1, -1, -1):
        if p.parts[i] == run_dir.name:
            q = run_dir.joinpath(*p.parts[i + 1:])
            if q.exists():
                return q
            break
    return p


def _store_attr(d: pathlib.Path, key: str) -> Any:
    """A zarr store's group attribute (zarr 3 `zarr.json`, zarr 2 `.zattrs`), or None."""
    for name, path in (("zarr.json", ("attributes",)), (".zattrs", ())):
        f = d / name
        if f.is_file():
            node: Any = json.loads(f.read_text())
            for k in path:
                node = node.get(k, {})
            return node.get(key)
    return None


def _dir_problems(run: str, st: str, f: pathlib.Path, recorded: str) -> list[str]:
    """A directory input: a zarr store carries the sha256 of the parts manifest it was assembled from, which is what the ledger recorded."""
    have = _store_attr(f, "manifest_sha256")
    if have is not None and have != recorded:
        return [f"{run}: stage {st}: input {f} changed since the stage ran (store manifest {str(have)[:12]}, ledger {recorded[:12]})"]
    return []


def _orca_problems(run: str, st: str, man: pathlib.Path) -> list[str]:
    """The orca cache manifest names the sha256 of every per-hour part: re-hash the parts that are still there."""
    out: list[str] = []
    for name, sha in json.loads(man.read_text()).get("parts", {}).items():
        part = man.parent / "hours" / name
        if part.is_file() and sha256(part) != sha:
            out.append(f"{run}: stage {st}: orca part {part} changed since the cache was assembled")
    return out


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
        d = json.loads(p.read_text())
        if not d.get("ok"):
            out.append(f"{run_dir.name}: stage {st}: ok=false ({d.get('error')})")
        for c in d.get("checks", []):
            if not c["ok"]:
                out.append(f"{run_dir.name}: stage {st}: self-check {c['name']} failed (value {c.get('value')}, limit {c.get('limit')})")
        for i in d.get("inputs", []):
            f = _resolve(i["ref"], run_dir)
            if i.get("sha256") and f.is_dir():
                out += _dir_problems(run_dir.name, st, f, i["sha256"])
            elif i.get("sha256") and f.is_file() and sha256(f) != i["sha256"]:
                out.append(f"{run_dir.name}: stage {st}: input {f} changed since the stage ran")
            if f.name == "manifest.json" and f.is_file() and "parts" in json.loads(f.read_text()):
                out += _orca_problems(run_dir.name, st, f)
        for o in d.get("outputs", []):
            f = _resolve(o["path"], run_dir)
            if not f.is_file():
                out.append(f"{run_dir.name}: stage {st}: output {f} is missing")
            elif sha256(f) != o["sha256"]:
                out.append(f"{run_dir.name}: stage {st}: output {f} changed since the stage ran")
        if prev is not None and prev.resolve() not in {_resolve(i["ref"], run_dir).resolve() for i in d.get("inputs", [])}:
            out.append(f"{run_dir.name}: stage {st}: does not record the {STAGES[STAGES.index(st) - 1]} ledger as an input (chain broken)")
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


def _run(cmd: list[str]) -> tuple[int, str]:
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr)[-4000:]


def coverage_problems(cov_json: str | pathlib.Path) -> list[str]:
    d = json.loads(pathlib.Path(cov_json).read_text())
    out: list[str] = []
    for pref, gate in GATES.items():
        tot = cov = 0
        for f, v in d["files"].items():
            if f.startswith(pref + "/") or f == pref:
                tot += v["summary"]["num_statements"]
                cov += v["summary"]["covered_lines"]
        pct = 100.0 * cov / tot if tot else 100.0
        if pct + 1e-9 < gate:
            out.append(f"coverage {pref}: {pct:.1f} % < {gate:.0f} %")
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
    counts = json.loads((root / MUTATION_STATS).read_text())
    rec: dict[str, Any] = {k: counts[k] for k in ("killed", "survived", "timeout", "no_tests", "suspicious", "skipped", "segfault", "total")}
    rec.update(score=round(mutation_score(rec), 4), code_digest=mutation_digest(root), tests=mutation_tests(root), sources=MUTATED,
               date=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), mutmut=importlib.metadata.version("mutmut"))
    return rec


def mutation_problems(root: pathlib.Path = ROOT) -> list[str]:
    """Missing, stale or too-low stored mutation result; each message names the command that refreshes it."""
    path = root / MUTATION_FILE
    if not path.is_file():
        return [f"mutation: no stored result at {MUTATION_FILE}: run {MUTATION_CMD}"]
    rec = json.loads(path.read_text())
    if rec.get("code_digest") != mutation_digest(root):
        return [f"mutation: the stored result ({rec.get('date')}) was made by different physics/stats code or tests: run {MUTATION_CMD}"]
    score = mutation_score(rec)                        # recomputed from the counts: an edited `score` field proves nothing
    if score + 1e-9 < MUTATION_MIN:
        return [f"mutation: {rec['killed']}/{rec['total']} mutants killed = {score:.1%} < {MUTATION_MIN:.0%}: add tests, then {MUTATION_CMD}"]
    return []


def main(argv: list[str]) -> int:
    if "--mutation-record" in argv:
        (ROOT / MUTATION_FILE).write_text(json.dumps(mutation_record(ROOT), indent=1) + "\n")
        print(f"wrote {MUTATION_FILE}")
        return 0
    ledgers_only = "--ledgers-only" in argv
    code_only = "--code-only" in argv or ledgers_only
    runs = [a for a in argv if not a.startswith("--")]
    problems: list[str] = []
    for r in runs:
        problems += ledger_problems(r)
    if not ledgers_only:
        problems += banned()
        problems += mutation_problems(ROOT)
    if not code_only:
        rc, out = _run(["ruff", "check"])
        if rc:
            problems.append("ruff:\n" + out)
        rc, out = _run(["mypy"])
        if rc:
            problems.append("mypy:\n" + out)
        rc, out = _run([sys.executable, "-m", "pytest", "-q", "-m", "not network", "--cov=cafe/pm", "--cov-report=json:coverage.json"])
        if rc:
            problems.append("pytest:\n" + out)
        if (ROOT / "coverage.json").exists():
            problems += coverage_problems(ROOT / "coverage.json")
    for p in problems:
        print("AUDIT FAIL:", p)
    print(f"audit: {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
