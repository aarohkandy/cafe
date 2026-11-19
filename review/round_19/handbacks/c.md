# Round 19, batch C hand-back: what-if and the command line

Branch `r19-c`, cut from 51eb433. Files edited: `cafe/pm/__main__.py`, `cafe/pm/whatif.py`, `tests/test_round19_c.py` (new). `budget.py` was not needed. No shared document was edited.

## M-10: a `plan.json` with a bad size

- Where: `cafe/pm/__main__.py`, new `_plan_sizes(plan)`, called in `_whatif` inside the existing `with _run_files(run):` right after `plan.json` is read (`bud = run_plan["budget"]`). That is the one place `batch`, `n_min` and `n_max` are read from the file (`ctx.plan.update` is the only copy; `grep` of `run_plan` and `plan.json` finds no other reader of these three numbers: `_report` reads `gpus` and `budget` only, `report.py` reads `stage1_s`, `budget_s`, `member_cost` and others, which are not this finding).
- What: all three must be `type(x) is int` (so a bool, a float such as 32.5 or 12.0, a string and null are refused) with `1 <= batch` and `1 <= n_min <= n_max`. It raises `ValueError` inside `damaged_run_files`, which turns it into the same `error: <run>: damaged or incomplete (ValueError: plan.json has batch ..., n_min ..., n_max ...: whole numbers ...); run it again (--fresh); ...` that a missing key gives (exit 2). A `ConfigError` raised directly would have passed through that wrapper unwrapped, with different text.
- Test: `test_m10_a_plan_json_with_a_bad_size_is_the_damaged_file_message_and_nothing_is_answered` (10 cases: batch 0, -8, "32", 32.5, true; n_min 500 with n_max 10; n_min 0 and null; n_max "72" and 12.0) and `test_m10_the_sizes_a_real_plan_has_are_read_as_they_were` (24/24/72, 1/1/1, 32/32/32 still answered, sizes reach `ctx.plan`).
- Before (unfixed 51eb433 source with the new test file, orca job `r19c_before`): all 10 cases FAIL (rc 0 where 2 is asked, the stubbed `answer` ran). After: pass. Note: in the test the `answer` is a stub, so "before" shows as rc 0, not as the reviewer's ZeroDivisionError/TypeError (those are in `stage1.wave`/`budget.py` which the stub bypasses); the real tracebacks were not re-run (reviewer's, 24 to 85 s each).

## M-15: duty printed in the refusal

- Where: `cafe/pm/whatif.py` `_numbers`: the duty is printed with `:g` when that reads back as the same float, else with `repr`. (`.10g` would still read "1" for 1.00000000001; this prints whatever differs, and an allowed duty such as 1.0 is never in the message.) The other three numbers keep `:g` (a finite shift or move that is refused is refused for being a box-wide move, which has its own message; only the duty has the "at most 1" edge).
- Test: `test_m15_a_duty_that_is_refused_is_printed_so_that_it_differs_from_one` (1.0000001, 1.00000000001, 1.5, 0.0, -0.25, nan, inf; exact message) plus duty 1.0 still accepted.
- Before: the 1.0000001 and 1.00000000001 cases fail ("duty 1 needs ..."); the others pass on both. After: all pass. Pin check: `tests/test_whatif.py:177` pins "duty 1 needs" for a valid duty 1.0 with an infinite shift: unchanged (`:g` of 1.0).

## M-16, A-2: the baseline-from-flags guard in `flip_search` (whatif.py:816 to 823)

Tests (all in `tests/test_round19_c.py`, each mutant applied to a copy of `whatif.py` in the orca directory by a driver `x_mut19c.py` that was not committed, job `r19c_mut`; a control run without a mutant passed, and each mutant below failed exactly its own test and no other):

| mutant | test that kills it |
|---|---|
| W3a `>` for `>=` in `len(flags) >= plan["batch"]` | `test_a2_w3a_...`: flags of exactly one batch are a baseline from flags, no run of the unchanged mission |
| W3b `>= 1` | `test_a2_w3b_...`: 1, 10 and 31 flags (batch 32) give a measured baseline (source RUN, n 32, first call is the unchanged mission) |
| W4 UAS-3-D exclusion dropped | `test_a2_w4_...`: a 3-D UAS with base-run flags still measures its baseline (`base_2d` source RUN, first `measure` call is the base mission) |
| W6a `<` for `<=` in `used + cost <= share` | `test_a2_w6a_...`: a share of exactly the baseline's cost runs it; 0.999 of it runs nothing |
| W7 `elif run_s1` for `elif uas_3d or run_s1` | `test_a2_w7_...`: a 3-D UAS with an emulated fix (no Stage-1 row) still states its measured 2-D baseline (`predict` patched to answer a fix) |
| F10 `n=len(flags)` for `n=len(f0)` | `test_a2_f10_...`: 64 flags, batch 32: `base_same["n"] == 32` |

On the unfixed code these six tests PASS (they are tests of the round-18 code's edges, not of a bug), which is what the "before" run `r19c_before` shows (only M-10 and M-15 tests fail there). S1 (near-equivalent, reviewer's and merge's own reading) was not tested.

## Decisions taken (the text for batch G)

- DECISION (M-10, not an owner decision): `whatif` reads the three sizes of the ensemble (`batch`, `n_min`, `n_max`) from the run's `plan.json` only if they are whole numbers (not bool, float or string) with `1 <= batch` and `1 <= n_min <= n_max`; otherwise it ends in the "damaged or incomplete" message (exit 2, `ValueError` inside `damaged_run_files`) before anything is run. The check is in `cafe/pm/__main__.py` `_plan_sizes`. It does not check `n_min` against `batch` (a plan whose n_min is not a multiple of the batch is allowed: `stage1.wave` rounds up) and does not check the other plan.json values (`budget` is looked up by the planner; `gpus`, `stage1_s`, ... are `report`'s). Amends row 953 (plan.json read by whatif) and row 952.
- DECISION (M-15, not an owner decision): the refusal of a duty prints the duty with `:g`, or `repr` when `:g` would read as another number.
- Open decisions that concern this batch: none (OD-1 to OD-8 are other batches'). "Awaiting the owner": none taken by this batch.

## Pins moved

None. No existing test needed an edit.

## Verification on orca (proot, 2 CPUs, PMX `pm_r19c*`)

| job | what | rc |
|---|---|---|
| `r19c_before` | `tests/test_round19_c.py` against the unfixed source of 51eb433 | 1 (12 failures: the 10 M-10 cases and 2 M-15 cases, as intended) |
| `r19c_1` | `tests/test_round19_c.py` on the fix (24 tests) | 0 |
| `r19c_mut` | the six A-2 mutants and a control | 0 (control green, each mutant killed by its own test) |
| `r19c_2` | `tests/test_whatif.py tests/test_cli.py tests/test_budget.py tests/test_round18_a.py tests/test_round17_a.py` (504 result characters, all `.`) | 0 |
| `r19c_lint3` | `ruff check cafe/pm tests` (0), `mypy cafe/pm` (success, 55 files), `tests/test_round19_c.py` and the banned-token tests of `tests/test_audit.py` (0) | 0 |

`r19c_2` ran on the commit's code before two cosmetic edits (a wrapped message line in `_plan_sizes`, a lambda default in a test) that ruff asked for; `r19c_lint3` ran the new file after them.

## Not verified

- The real tracebacks of M-10 (a real `whatif` of 24 to 85 s) were not re-run: the new test stubs `whatif.answer` like `tests/test_cli.py`'s `wi` fixture, so it shows the missing refusal as rc 0, and the fix as the refusal before any stage runs.
- `n_min` above `batch`'s multiples and other odd-but-whole sizes are accepted (not a defect found by the reviewer).
- M-16's S1 mutant; the "wide" rerun is not this batch's.
- A full gate, coverage of the whole tree and the full suite were not run; only the files below.

## Orca leftovers (all inside `~/cafe-worker`, mine, to remove)

Directories `~/cafe-worker/cafe/pm_r19c`, `pm_r19c_2`, `pm_r19c_before`; markers `~/cafe-worker/cafe/.pmx.job.pm_r19c`, `.pmx.job.pm_r19c_2`, `.pmx.job.pm_r19c_before`; logs `~/cafe-worker/logs/r19c_1.log`, `r19c_2.log`, `r19c_before.log`, `r19c_mut.log`, `r19c_lint2.log`, `r19c_lint3.log`. (`r19c_lint` was a first try whose command was split on spaces; it left no log.) The mutant driver ran inside `pm_r19c` and restored `whatif.py` there; the local copy was never edited by it. Locally: the scratch worktree `../cafe-r19c-before` (detached at 51eb433), to be removed with `git worktree remove --force`.
