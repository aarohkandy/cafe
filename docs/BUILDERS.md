# Rules for anyone (human or agent) adding to cafe/pm

- Read first: `docs/BRIEF.md` (the corrections table at the top overrides the brief), `cafe/pm/__init__.py`
  (conventions + `Tagged`), `cafe/pm/env/protocol.py` (the Environment interface + `AnalyticEnv` for tests),
  `cafe/pm/env/conventions.py` (the only place angles become vectors).
- Run everything on homebase, never the laptop: `PM_CPUS=2 PM_MEM=6g ./pm.sh python -m pytest tests/test_x.py`.
  `./pm.sh` rsyncs this checkout to `~/work/cafe/pm` and runs in the `cafe-pm` image (all of requirements-pm.txt).
  Data written under `/data` in the container lands in `~/work/cafe/pmdata` on homebase. Never run `./sync.sh`,
  never touch `~/work/cafe/src`, `~/services`, or the `cafe` / `cafe-worker` containers (the live app).
- Vectorize over ensemble members (leading axis M). No per-member Python loops in anything Stage 1 calls per step.
- Every model constant: a citation in the docstring (author, year, table/equation). A number you cannot source goes
  in `config/assumptions.yaml` (key, value, unit, why, what would replace it) and is read from there.
- Receipts: each module exposes `receipts()` that calls `cafe.receipts.receipt / bracket / context` (see
  `cafe/receipts.py`) for every published reference it reproduces. Each receipt must be able to fail: add a pytest
  that breaks the physics (sign flip, wrong unit, wrong convention) and asserts the receipt then fails.
- Tests: 100 % line coverage of your own modules (`--cov=cafe.pm.<pkg>.<mod> --cov-report=term-missing`), at least
  one `hypothesis` property test per transform/interpolation, and tests that fail on sign/unit/convention errors.
- Banned anywhere outside `tests/fixtures/broken/`: TODO, FIXME, XXX, NotImplementedError, "placeholder",
  `pytest.skip`, `xfail`, commented-out code. Missing optional hardware/binaries -> a clear labelled fallback
  path that is itself tested, never a skip.
- `ruff check` clean, `mypy` (pyproject config) clean, public functions type-annotated.
- Style: match `cafe/` — compact numpy, short docstrings that say what and why, no frameworks, no class where a
  function will do. Do not edit files outside your listed scope; if a shared file must change, say so in your report.
- Do not commit. End with a report: files, what each receipt measured (numbers), coverage %, anything you could not
  do and why, and every decision you made that the brief did not dictate (for DECISIONS.md).
