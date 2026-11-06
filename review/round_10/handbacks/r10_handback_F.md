# Round 10, batch F (M-12): hand-back for the docs step

Branch `r10-f`, code in `cafe/pm/acceptance.py`, tests in `tests/test_acceptance.py`. M-34 and M-36 are documents and were not touched.

## M-12. acceptance deletes only a directory it made itself

What changed: `acceptance.claim_out(out, names)` and the constant `MARKER = ".cafe_acceptance"`. `run_one` calls it right after `refuse_wiped_mission` and before the first `shutil.rmtree` (so both rmtree sites, `out/<name>` and `out/<name>_fetch`, sit behind it); `run` calls it once for every name in `RUN_NAMES`, so a user's `overnight` or `4h` is protected before the first run starts, not after hours.

Rule (as amended in the follow-up below): if `out/.cafe_acceptance` exists, acceptance made or claimed `out`: replace as before. If it does not exist, `out` is refused (`config.ConfigError`, exit 2, nothing touched, no marker written) when it holds `<name>`, `<name>_fetch`, `<name>.log` or `<name>_fetch.log` for any name asked, or `plan.json` or `checkpoints` (it is itself a run). Otherwise (missing, empty, or holding only other files) acceptance writes the marker, then runs. The marker is written before the first rmtree, so a run killed half-way is rerunnable. The guard also covers the two logs that `_execute` overwrote.

### DECISIONS row (next free number; I assumed 535, renumber if another batch took it)
| 535 | `acceptance` removes only what it made itself: `acceptance.claim_out` marks `--out` with `.cafe_acceptance` before the first removal. An `--out` without the marker that already holds `<name>`, `<name>_fetch`, `<name>.log` or `<name>_fetch.log` for a run name (quick, quick_same, quick_seed, overnight, 4h), or that is itself a run (`plan.json`, `checkpoints/`), is a `ConfigError` (exit 2) naming what it holds; nothing is touched and no marker is written. A missing or empty directory, or one with only other files, is claimed and marked; with the marker present the runs are replaced on every run as before. `run` checks every run name before the first run starts; `run_one` checks its own two directories and logs, so a direct caller is guarded too. | Review round 10, M-12. `acceptance --out runs` removed the user's reviewed `runs/quick` and `runs/overnight` (a 10 h result) with no prompt, and overwrote `<name>.log`. Row 328 answered it only for `make acceptance` (the Makefile points at `runs/acceptance`, plus a RUNBOOK sentence); any other `--out` was unguarded. The marker (one file in `--out`, not one per run) survives `run --fresh`, which can empty a run directory. |

Amends: row 328 (add "(amended by 535)"; the Makefile path is now a convenience, not the only protection). Row 328's text stays true. Related and unchanged: the round 9 M-12 sibling, `refuse_wiped_mission` (a mission file inside `out/<name>`); it still runs first, so its message wins when both apply.

### CHANGELOG line (Fixed)
- `acceptance --out DIR` no longer removes a directory it did not make: `--out` is marked `.cafe_acceptance` on first use, and an unmarked `--out` that holds `quick`, `quick_fetch`, `overnight`, `4h` and the rest (or their `.log` files, or is itself a run) is refused with exit 2 before anything is removed (M-12; DECISIONS 535, amends 328).

### Doc sentences needed
- RUNBOOK ~line 212, after "are replaced on every run; your `runs/quick` is not touched": "`acceptance` marks its `--out` with a `.cafe_acceptance` file and replaces only what is in a marked directory; given a directory that is not marked and already holds `quick`, `overnight`, `4h` (or their `.log` files) it exits 2 and touches nothing. Use an empty or new `--out`; to reuse a directory by hand, move those entries out first and acceptance will mark it."
- RUNBOOK troubleshooting: the message begins `--out <dir> holds <names>, and acceptance replaces those on every run`.
- If M-35 (RUNBOOK rows that quote messages) is done, this message is one more entry-point message.

## What I checked could break, and how
- Callers: `run_one` is called by `run` and by tests only (grep of cafe, tests, Makefile, bin, docs: no other); `acceptance.run` only by `main` and tests; `refuse_wiped_mission` is unchanged. `Makefile` `acceptance` uses `runs/acceptance`: WRONG as first written, see the follow-up (an `runs/acceptance` from before the marker was refused); fixed. `make audit` reads `runs/acceptance/quick`: unaffected. `bin/sync_filters` keeps `/runs/` whole, so the marker is not deleted by a sync.
- Other deletes of a user-named directory: searched `rmtree`, `unlink`, `os.remove`, `shutil.move` in `cafe/pm`. Only the two acceptance sites (:100, :111 before the change) delete a directory named by the user. The rest are the code's own scratch (`par`, `pipeline` derived.zarr, `pipeline_windows` jobdir) or have their own guard (`hycom.refuse_overlap`). Not changed.
- Files `run` writes directly into `out` that are not guarded: `emulator_table.parquet`, `receipts_broken.json`, `receipts_wave_direction.json`, `receipts_broken.log`, `acceptance.txt`, `acceptance.json`. These carry acceptance-only names and are overwritten by design in a marked directory; in an unmarked directory they would be written over a same-named user file. I left them out of the refusal list to keep it to the run results. If the owner wants them guarded, add them to the `mine` list in `claim_out` (one line).
- Case a user adds their own `quick` to a directory acceptance already marked: acceptance replaces it (the marker means "acceptance's"). Stated in the RUNBOOK sentence above.
- A marker in `--out` is a file in a user directory that held only other files: visible as a dotfile, one line of text.
- Existing test `test_run_one_starts_clean_names_the_run_and_reads_its_report` pre-populates `out/quick` by hand, so it now writes the marker first (the only existing test that needed it; the CI-fixture tests and the `Fake` tests start from missing directories).
- Tests added (all `test_r10_m12_*`): refusal for each of quick, quick_fetch, quick.log, quick_fetch.log, plan.json, checkpoints (run_one, nothing starts, a neighbouring `overnight/report.json` survives, no marker written); `run` refuses before its first run when only `overnight`, `4h` and `quick_seed.log` are taken; first run into a missing and an empty directory marks it, a rerun replaces only the run's own directories; a directory with other files is claimed and the other files stay; a run killed after the mark is rerunnable; the mission refusal still wins.
- Verified: `tests/test_acceptance.py` whole file passes on orca (rc=0) with the fix. Against the unfixed `acceptance.py` (detached worktree at 6c352ef with the new test file, since removed) 9 of the 11 new tests fail (the six refusals, the `run` refusal, the first-run/rerun marker and the killed-run test); the other two (other files stay, mission refusal first) pass on both, as they describe behaviour that must not change. `ruff check cafe/pm tests` clean, `mypy cafe/pm` clean (55 files). I did not run the whole suite or `audit`.

## Needs from other batches
- `cafe/pm/__main__.py:107`: the `--out` help text says "each run in its own subdirectory, removed first". It should say "removed first; a directory that holds runs acceptance did not make is refused". I did not edit it (file outside my scope, and M-5 touches `__main__.main`). Whoever owns that file takes it, or the lead's doc pass does. No test pins the string (grep of `tests` for "removed first" finds nothing).
- RUNBOOK, DECISIONS and CHANGELOG are the lead's (rows and sentences above).
- Nothing else depends on this change; no other batch needs to call `claim_out`.

## Follow-up (adversary finding): an existing runs/acceptance from before the marker

Problem: a `runs/acceptance` made by an earlier acceptance run holds `quick/` and `acceptance.json` and no marker, so the next `make acceptance` exited 2 and the owner had to `touch` the marker before the 11 h run. My claim above that it was "empty or marked" was wrong for every directory made before this change.

Fix, at the one shared place (`claim_out`; `run` and `run_one` both route through it): an unmarked `out` that holds one of `OWN_FILES` (`acceptance.json`, `acceptance.txt`, `emulator_table.parquet`, `receipts_broken.json`, `receipts_wave_direction.json`, `receipts_broken.log`: names only `run` writes into `--out`) and is not itself a run (no `plan.json`, no `checkpoints/`) is acceptance's own from an earlier version: it is marked and replaced as before. `emulator_table.parquet` is written before the first run, so an earlier run killed in hour one is recognised too; one killed before that (only `quick/` and `quick.log`) is still refused, and the message says what to do. No Makefile change (a `touch` there would claim whatever `RUNS=` points at).

Residual, stated: a user directory that holds a file with one of those names plus a `quick` is now claimed. These are acceptance's own file names (the same list the section above left unguarded), so this is the case the marker was never going to tell apart.

Tests (fail on the unfixed `claim_out`, pass after): `test_r10_m12_an_out_from_before_the_marker_is_claimed_not_refused[<each of OWN_FILES>]` (6; all fail on the unfixed code, shown with the constant appended to the old module and the new test file in a detached worktree, since removed). `test_r10_m12_an_out_that_is_itself_a_run_is_refused_even_with_an_acceptance_file[plan.json|checkpoints]` pin the other side and pass on both. The earlier 11 tests unchanged and pass.

For the docs step, add to the RUNBOOK sentence: "A `runs/acceptance` from an earlier version is marked on the next run and replaced; nothing to do by hand." The CHANGELOG line need not change. DECISIONS 535: add "or holds a file only `run` writes (`OWN_FILES`) and is not itself a run: an earlier acceptance run, claimed".

Verified: `tests/test_acceptance.py` whole file on orca: rc=0, 94 passed, `ruff check cafe/pm tests` clean, `mypy cafe/pm` clean (55 files). Not run: the whole suite, `audit`.

Not problems (lead's decisions or documents): M-34 and M-36 (documents, not touched by design); the `__main__.py:107` help text (another batch's file, listed above); the unguarded `run` output files and a user's later `quick` in a marked dir (stated decisions above).
