# Round 22, batch E hand-back (M-10, the grep tests of the JSON sweep)

Branch `r22-e`, cut at 7a1aaa9, one commit on top (`9ec52b7`). Only `tests/test_round21_e.py` changed (no product code, no document).

## What changed and why

The two round-21 grep tests (`raw_json_calls`, `isfinite_uses`, walking `cafe/` only and matching four spellings) are one AST checker, `scan_source`, over every Python file of the repository.

- **What is a site**, by what is imported and accessed, through any alias (`import x as y`, `a = json`, `d = json.decoder`, walrus and annotated assignment, `from somewhere import json`, `import json.decoder`, `from json import decoder`):
  - json (also simplejson, orjson, ujson, rapidjson): `load`, `loads`, `JSONDecoder` accessed or imported by name (`from json import loads as p`, `from json import *`), a response's `.json()`.
  - `math.isfinite` and `numpy.isfinite`, accessed or imported.
  - the dynamic spellings: `getattr(m, ...)` (any non-literal name, or a literal in the family's list), `vars(m)`, `m.__dict__`, `__import__("json")`, `importlib.import_module("json")` (also `from importlib import import_module as imp`), and an import by a computed name (group `dynamic`).
- **What is walked**: every `*.py` under the repository root and every extensionless file with a python shebang, except directories starting with a dot, `tests/` (feeds hostile documents on purpose), `review/` (probes and merge scripts, never imported) and `mutants/` (mutmut's generated copy). `NOT_WALKED` carries the reason of each. Walked today: `cafe/` (82 files), `lab/check.py`, `bench/throughput.py`, `report/build.py`. `bin/` has no Python (all `sh`; a python-shebang file there would be walked). A new top-level directory with Python in it fails `test_the_walk_covers_...` until it is classified. Shell, Makefile, Dockerfile and workflow text is grepped too (`json.loads`, `JSONDecoder`, `isfinite`): none today.
- **Allow-lists** (`RAW_JSON`, `RAW_ISFINITE`, `RAW_NP_ISFINITE`, `RAW_DYNAMIC`): file, exact count, reason. A new site, a moved-out site, or one fewer all fail, and the failure message names `file:line what` of the sites. Today: json 20 sites in 12 files (the old 8 + `cafe/_redteam.py` 6, `lab/check.py` 3, `bench/throughput.py` 2, `report/build.py` 1), math 34 in 17 (unchanged), numpy 146 in 34 (new group), dynamic 4 in 3.
- **Self-tests**: 55 sources the checker must find, with the exact count (every spelling A and D named: `import math as m`, `from json import loads`, `getattr(json, "loads")`, `__import__("json")`, `json.JSONDecoder().decode`, `np.isfinite` of a document's scalar, plus aliases, star imports, `.json()`), and 12 it must leave alone (`json.dumps`, `getattr(json, "dumps")`, `math.isnan`, a string, a relative `from .json import loads`, `json=` keyword). A tmp-tree test shows a raw site in a new top-level directory, in `lab/`, in an extensionless `bin/tool` and in a root `setup.py` is found, and `tests/`, `review/`, `mutants/`, `.venv/` are not.

## Evidence

- **Before** (old checker on each of the 55 self-test sources, run on the laptop with the old functions copied over): the old checker gets 41 of the 55 wrong, including every one of the reviewers' probes (`import math as m`, `getattr(json, ...)`, `__import__("json")`, `JSONDecoder`, `np.isfinite`, `from json import *`); the 10 it gets right are controls (`json.loads`, `json.load`, `import json as j`, `from json import loads [as p]`, `math.isfinite` and its from-import, `map(math.isfinite, xs)`, `f = math.isfinite`). The old walk also saw 8 of the 20 json sites.
- **After**: orca job `r22e_2`, `bin/pmx.sh python -m pytest -q -q -p no:cacheprovider tests/test_round21_e.py` on `pm_r22e` (2 CPUs): rc=0, 213 passed (counted on the progress lines only). Job `r22e_1` (before the last four self-tests): rc=0, 208. `ruff check cafe/pm tests` clean; `audit.banned()` has no hit in the file.
- **Mutants of the checker** (a scratch script, 15 one-line mutants: no `__dict__`, no `vars`, no importers, no walrus, no annotated assignment, `getattr` any name, `getattr` computed only, no `.json()`, no relative-import guard, no star, no from-submodule alias, no computed-import group, no `as` alias, only math, from-import root): all killed. Two survivors found and closed: the relative-import guard (added the `from .json import loads` negative) and `raw_decode` (dead: removed from the list; `json.JSONDecoder()` is flagged first).

## Hunks for the merge step (files of other batches or owned by nobody; I did not edit them)

1. **`bench/throughput.py` lines 20 and 204** (both `json.loads(OUT.read_text())`): convert to `load_json`, which the file's own `from cafe import atomic` shows it can import:
   `from cafe.pm.jsonio import load_json  # noqa: E402` after line 13, and `data = load_json(OUT.read_text()) if OUT.exists() else {}` at both. Then delete the `bench/throughput.py` entry of `RAW_JSON` (2 sites go to 0). Safe either way today; the entry says "SHOULD BE CONVERTED".
2. **`cafe/hangar.py` line 45** (`check`, `not isinstance(v, (int, float)) or not np.isfinite(v) or v <= 0`): a spec number is read by `load_json`, so an integer up to 10**308 passes the reader, and `np.isfinite(2**64)` is a TypeError (numpy 2.0.2 on the laptop; not run on orca): a design job with such a mass fails with a traceback text, no wrong number. Fix: `not finite_real(v) or v <= 0` (`finite_real` refuses a bool and an oversized integer, so the message is the same), importing `finite_real` from `cafe.pm.jsonio` beside `load_json` (line 13). Then delete the `cafe/hangar.py` entry of `RAW_NP_ISFINITE`. Batch D lists hangar.py "only if M-7 needs it"; if D edits it, this goes in the same hunk.
3. **`cafe/live.py` line 76**: batch D's M-9 catches the OverflowError of the `float()` a few lines above; once it does, nothing for this entry (the `np.isfinite` is then of floats). No count change.
4. **Counts will move.** `RAW_NP_ISFINITE` counts files that batches A (stage1.py 21), B (report.py 11, rfband.py 1), C (config.py, in `RAW_JSON`/`RAW_ISFINITE`) and D (app.py, live.py, vehicle.py) edit. If a batch adds or drops an `np.isfinite` or `math.isfinite`, the merge step must run the test and edit the count; the failure prints `file:line what` for each file that differs. That is the intended cost of an exact count; the alternative (a ceiling) lets a new raw site in.

## Siblings found, not fixed (outside this batch's files and the finding)

- `math.isnan` / `math.isinf` of an oversized integer are an OverflowError as `math.isfinite` is; not in M-10's rule. Sites: `credibility.py` 3, `dtmb5415.py` 1, `vv.py` 1, `stage3/pipeline_windows.py` 1 (grep counts, not read one by one). Adding them to the rule is one set entry (`SITE_NAMES`) and an allow-list; not done, because the lead's steer says to add nothing merged.md does not name.
- JavaScript (`JSON.parse`, `isFinite`, `Number.isFinite` in `cafe/static/app.js`) is outside a Python AST checker; batch D owns app.js.
- YAML: `config._yaml` is the one reader (batch C's test).

## Claims left on the output, and what holds each

- "No raw JSON read / `math.isfinite` / `numpy.isfinite` / computed import in any Python file outside `tests/`, `review/`, `mutants/` except the listed ones, with these counts": the four group tests (`test_every_raw_json_read_and_finite_test_in_any_python_file_...[json|math|numpy|dynamic]`) over the whole tree, and the tmp-tree test for the walk.
- "The checker finds spelling S": one self-test per S (55) and per non-spelling (12).
- Not held by any test: the REASON of an entry. A reason is read from the site (I traced the scalar ones: `app.py` 145, `shapes.py` 44, `sampling.py` 58, `hangar.py` 45, `live.py` 76, `stage1.py` 657, `pipeline.py` 1008, `cfd.py` 489; the other numpy entries say "arrays and floats made in this process" from reading the grep lines of each site, not from tracing every caller). If a reason is wrong the count still holds and the site stays visible.
- The checker reads spelling, not data flow: a module passed as an argument, kept in a dict or taken from `sys.modules` is not followed (stated in the test's comment).

## For batch G

- DECISIONS 1049 (amend in place): replace "A second grep test fails on a new `math.isfinite` until it is listed in `RAW_ISFINITE`" with: one AST checker (`tests/test_round21_e.py::scan_source`) walks every Python file of the repository except `tests/`, `review/`, `mutants/`, finds json reads, `math.isfinite`, `numpy.isfinite` and computed imports through any alias and the dynamic spellings, and four allow-lists carry file, exact count and reason (json 20 sites in 12 files, `math.isfinite` 34 in 17, `numpy.isfinite` 146 in 34, computed imports 4 in 3 at the time of writing; re-count after the merge). The sentence "78 sites in 30 files" stays true for `cafe/`; the scripts outside it (`lab/check.py`, `bench/throughput.py`, `report/build.py`) are covered by the same test since round 22 and are raw by reason (hunk 1 converts the bench).
- DECISIONS 1056 and CHANGELOG: "the two grep tests" is now "the AST checker and its four allow-lists"; test names changed (`test_no_raw_json_load_is_left_in_cafe_outside_the_allow_list` and `test_every_scalar_math_isfinite_in_cafe_is_one_that_is_listed_with_its_reason` are one parametrized `test_every_raw_json_read_and_finite_test_in_any_python_file_of_the_repository_is_one_that_is_listed_with_its_reason_and_count`). No assertion was weakened: every old allow-list entry is unchanged and the old counts still hold.
- No new decision needs the owner.
- PROBLEMS: the reasons of the allow-list are read, not tested; the checker does not follow data flow; `math.isnan` / `math.isinf` are outside the rule.

## Expected q23 versus q22

Nothing: tests only.

## Not verified

The full suite, the gate and coverage (nothing in `cafe/pm` changed); the file under mutation testing (it is a test); the hangar TypeError was shown with numpy 2.0.2 on the laptop, not on orca; the checker was run over the tree on the laptop (Python 3.9) for the counts and on orca (3.12) for the tests, and the two agree (the job passed with the same counts).

## Leftovers

Orca: `~/cafe-worker/cafe/pm_r22e` (synced code), `~/cafe-worker/cafe/pmdata/r22e_lint.sh`, logs `r22e_1.log` and `r22e_2.log` in `~/cafe-worker/logs`. Laptop: scratch in `/private/tmp/claude-501/-Users-aaroh-Downloads-everything-cafe-main/e5175414-543a-42ed-83ef-98e3ca2ddc48/scratchpad/r22e/` (checker.py, dry.py, mut.py, newblock.py, r22e_lint.sh, one empty `tmp*` directory made by the dry run).
