# Round 20, batch C hand-back (branch r20-c, cut from premission-step4 at 8e22951)

Findings: M-5, M-6, and the `ingest-ocean` hunk of M-8. Production code: `cafe/pm/__main__.py` only. Tests: `tests/test_round20_c.py` (new, 18 cases) and one pin moved in `tests/test_cli.py`.

## What changed in `cafe/pm/__main__.py`

- M-5 (OD-5 default taken as written). `_plan_sizes` now also reads `plan["budget"]` first (so a missing key is still `KeyError: 'budget'` first, as before) and refuses, as `ValueError` inside `damaged_run_files` (the "damaged or incomplete ... run it again (--fresh)" message, exit 2): a budget that is not a `str` in `budget.BUDGET_S` (list, null, int, bool, object, unknown name), and `batch` or `n_max` above `PLAN_SIZE_MAX = 10**6`. `_whatif` calls `_plan_sizes` before it reads `bud`. The size message keeps its words ("plan.json has batch ..., n_min ..., n_max ...: whole numbers with batch at least 1 and 1 <= n_min <= n_max are needed") and appends ", batch and n_max at most 1000000".
- M-6 (OD-4 default). The answer line appends `; ` + `report.SAME_AS_BASELINE` when the row has an interval and `lo <= base p_fail <= hi` (ends inclusive, as `report._fix`). Same words as the report (imported, not repeated). Rows with no interval ("unchanged") get nothing. No new statistic.
- M-8 hunk. `_ingest_ocean` prints, after the existing aside note, "note: a half-deleted `.dead.tmp` is beside the store: <path> (<n.n> GB); an earlier ingest was killed while deleting the store it replaced, nothing reads it, and it is safe to delete by hand (the disk is not freed until it is)" for each `hycom.dead(out)`; the size comes from `hycom._size_bytes` (private today).

## Merge-step follow-up for batch E's `hycom` change (one line)

I wrote the hunk against today's `hycom`: `hycom.dead(out)` and `hycom._size_bytes(q)`. If batch E (a) renames or removes `_size_bytes`, or (b) adds a public helper that names a `.dead.tmp` with its size (for `pipeline._need`), change the one `print` in `_ingest_ocean` (the `if gone := hycom.dead(out):` block, lines ~267-270) to call that helper, and keep the test strings of `tests/test_round20_c.py::test_m8_*`: they assert "note: a half-deleted `.dead.tmp` is beside the store: <path> (2.5 GB); ", "safe to delete by hand", "nothing reads it". If E changes the wording, move those three strings with it. `test_round20_c.py` imports `ingest` and `lab_mission` from `tests/test_round19_m.py`; if batch B/D/E rename them there, import from the new place.

## Before / after evidence (orca, 2 CPUs, proot)

- Before (detached worktree `../cafe-r20c-base` at 8e22951, `pm_r20c_base`, job `r20c_b1`): `tests/test_round20_c.py` alone: 14 failed, 4 passed, rc=1. The 4 that pass before are guards of unchanged behaviour (10**6 itself accepted and every budget name read as before; a sound plan whose budget differs from `--budget` still gets the flag's message; a row with no interval gets no words; nothing printed when nothing is beside the store). The 14 failures: all 10 `test_m5` parametrized plans (batch 1e30, n_max 1e30, batch 1e6+1, n_max 1e6+1, budget list, null, int, unknown, bool, object), the M-5 message test, the M-6 interval test, and the two M-8 tests.
- After (`pm_r20c`, job `r20c_2`): `tests/test_round20_c.py tests/test_round19_c.py tests/test_round19_m.py`: 62 passed, rc=0 (with the temporary `test_round19_m.py` hunk below applied).
- `r20c_3`: `tests/test_cli.py tests/test_round17_a.py`: 196 passed, rc=0 (with the two temporary hunks below applied).
- `r20c_4` (`pm_r20c2`): `tests/test_round18_a.py tests/test_round16_a.py tests/test_whatif.py`: 253 passed, rc=0.
- `r20c_7`: `python -m ruff check cafe/pm tests` All checks passed (ruff_rc=0); `python -m mypy cafe/pm` Success, no issues in 55 source files (mypy_rc=0). (r20c_5 found 3 E501 lines in my own test text; shortened; r20c_6 ran an older lint script and is superseded by r20c_7.) After the last edits (a comment spacing in `tests/test_cli.py` and the docstring of `test_round20_c.py`, both whitespace and prose only) only ruff and mypy were re-run, not the test jobs.

## Pins that moved, and why

1. `tests/test_cli.py:525` (`test_whatif_prints_the_verdict_with_its_badge_distance_or_stage_1_n`, the `uas` line): the fake answer has base P(fail) 0.700 and interval 0.300 to 0.700, which holds the base, so the line now ends with `; not distinguishable from the baseline (its interval contains the baseline's P(fail))`. The product's answer is the intended one (OD-4). EDITED and committed here. Note: this file is not named in batch C's row (the row names `test_whatif.py` and `test_round19_c.py`, whose pins I read: neither pins a line that moves, and `test_round18_a.py`/`test_round16_a.py` use `startswith`); no other batch's row names `tests/test_cli.py`, so I edited it rather than leave it failing.

Two more pins move, in files that other batches own, so I did NOT commit them. The exact hunks (verified: applied temporarily, jobs `r20c_2` and `r20c_3` green, then reverted) are in `review/round_20/handbacks/batch_c_other_files.patch`. Without them these two tests FAIL on branch r20-c as committed, and the merge step must apply them:

2. `tests/test_round17_a.py:148` (batch A's file, `test_m1_the_whatif_command_says_which_baseline_it_prints_and_which_is_the_reports`): base 0.156 is inside 0.100 to 0.200, so the `==` line gains the same `; not distinguishable ...` tail.
3. `tests/test_round19_m.py` (batch B's file, `test_a2_ingest_ocean_says_nothing_when_there_is_no_older_copy_or_only_a_dead_one_or_another_stores`): it asserted that a `.dead.tmp` of the store itself prints nothing; that is exactly what M-8 reverses. The hunk renames it (`..._or_only_another_stores`), drops the dead directory, and keeps the other-store case; the dead case is covered by `test_m8_*` in `tests/test_round20_c.py`. Batches D and E also run this file; it is fine for them (they do not touch the ingest print).

## Decisions and judgement calls

- OD-4 and OD-5: defaults taken as written. Measured nothing unsafe in them. One remark on OD-5: 10**6 is a loose bound (largest real values: n_max 512, batch 128 in `budget.py`; the new test asserts both are below it). A `batch` of 10**6 is accepted and would ask Stage 1 for a very large batch at once; the refusal that matters (OverflowError, 10**30) is fixed. OD-5(b) (the table's own maximum) is the tighter alternative if the owner wants it.
- M-6: for an emulated row the interval is the conformal 90 % one and the base is the whole run's P(fail) (as `report._fix`); for a Stage-1 row the base on the line is the unchanged mission on the same members (as the report's `same`). The line uses the base it prints, so it matches the report's flag in both cases.
- Documents (batch G): RUNBOOK :175 (a change of one to three members is inside the noise of a what-if; the line now says so), RUNBOOK :298 (the `.dead.tmp` line `ingest-ocean` prints), the plan.json "damaged or incomplete" row (the new reasons: a budget that is not a budget name, batch or n_max above 10**6), a DECISIONS row for each (M-5 bound 10**6, M-6 words on the command line, M-8 ingest line), CHANGELOG lines, QUESTIONS_FOR_LAB sub-items for OD-4 and OD-5 with their defaults.

## Not verified / still wrong

- The what-if was not run end to end with a real rerun (the `wi` fixture fakes `whatif.answer`); M-6 words were checked on made-up answers only.
- `hycom._size_bytes` is a private function used across modules (mypy strict accepts it); see the follow-up above.
- `test_round20_c.py::dead_dir` makes a 2.5 GB sparse file (`truncate`); on a filesystem without sparse files that test would write 2.5 GB. On orca (proot) it passed.
- The full suite, the gate and a demo were not run (as told).

## Leftovers

- Orca: directories `~/cafe-worker/cafe/pm_r20c`, `pm_r20c2`, `pm_r20c_base`, and the scripts `~/cafe-worker/cafe/pmdata/r20c_lint.sh`, logs `~/cafe-worker/logs/r20c_*.log`; no job of mine is running (all ended with an rc line). Not removed (the lead may want the logs); remove by those exact names.
- Laptop: the detached worktree `/Users/aaroh/Downloads/everything/cafe-r20c-base` (holds a copy of `tests/test_round20_c.py`, untracked); remove with `git worktree remove --force ../cafe-r20c-base`. A scratch file `/tmp/none` was written once by mistake and removed.
