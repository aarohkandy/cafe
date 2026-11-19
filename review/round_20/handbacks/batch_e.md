# Batch E hand-back (round 20, M-8: hycom leftovers), branch r20-e from 8e22951

## What changed (cafe/pm/env/hycom.py, cafe/pm/pipeline.py, tests/test_round20_e.py new)
- `hycom.leftover_note(path, lab)`: same signature and the same words ("puts it back", the `mv`, "without a download", the sweep text), but the asides are
  ordered newest first by modification time (ties by name) and each is listed with size, "newest" or "older" and its date (UTC, minutes). The `mv` is of the
  newest. New helper `hycom._mtime(d)` (0.0 for a vanished directory).
- NEW `hycom.dead_note(path) -> str`: "" when no `.dead.tmp` of that store is beside it; otherwise "; a half-deleted leftover of an earlier ingest that was
  killed while it deleted the old store is beside the store: <path> (<N.N> GB)[, ...]: nothing reads it and it is safe to delete (`rm -r <paths>`); the next
  ingest that writes the store deletes it too". Valid whether the store is there or not. `asides`, `dead`, `leftover_note` signatures unchanged.
- `pipeline._need`: `leftover` is now asked whether the input is present or not. A present input passes (ok True) with the extra text in the check's note
  (`<what>` + text) and `ctx.log("ingest: <note>")`; a failed input is as before. The ocean store's call passes
  `hycom.leftover_note(store, lab) + hycom.dead_note(store)`. `leftover_note` is "" for a present store, so a present store with only asides is unchanged.

## For batch C (`ingest-ocean` in cafe/pm/__main__.py, not edited here)
Call `hycom.dead_note(out)` (after `ocean store: ...`): it returns "" or the text above beginning with "; ". Print it as `note:` + text with the leading "; "
replaced, e.g. `if d := hycom.dead_note(out): print("note:" + d[1:])`. For the asides, `hycom.asides(out)` is still name-sorted; if C wants the
same newest-first order and the date, sort with `key=lambda x: (hycom._mtime(x), x.name), reverse=True` (private name; say if you want it made public).
This hunk's test is C's: `ingest-ocean` beside a `.dead.tmp` prints the line.

## Evidence (orca, proot, 2 CPUs)
- Unfixed tree (worktree cafe-r20e-base at 8e22951 plus the new test file), job `r20e_base`, rc=1: all 6 test functions (7 cases) fail; named:
  the two orders of `..._offers_the_newest_aside...` (the `ffffffffffff` order fails on the `mv` itself: the older is offered; the other on the new text),
  `_a_vanished_directory_has_no_time`, `_a_dead_leftover_is_named...`, `_need_passes_a_present_store...` (before: note is just "the store"),
  `_ingest_passes_with_a_dead_leftover...` (before: the note is the plain text, `.dead.tmp` unnamed).
- Fixed tree, job `r20e_1` rc=0 (tests/test_round20_e.py, test_round19_e.py, test_round18_e.py, test_round19_m.py, test_hycom.py: 235 passed); job `r20e_4`
  rc=0, 131 passed (test_pipeline.py, test_ingest_fetch.py, test_bathy.py, test_round20_e.py with `-k "need or ocean or ingest or leftover or store or r20 or gebco"`;
  the whole of those files was not run). The `pipeline.py` line wrap was made after r20e_1/r20e_2 started; r20e_4 and the lint run are on the final text.
- `ruff check cafe/pm tests` clean (job `r20e_lint2` rc=0; the first run found one 163-char line, fixed), `mypy cafe/pm` clean (job `r20e_lint`, 55 files).

## Pins moved
None. `test_round19_e` pins ("mv <aside> <store>", "without a download", `leftover_note == ""` for a store with only a dead leftover, `"mv " not in` the
error) hold because `leftover_note` stays "" for a dead-only store and `dead_note` is separate.

## Notes for the documents batch (G)
- DECISIONS row for OD-6: default (a). The date is the aside directory's own mtime, which for a store built by `write_store` is the time its metadata
  was written (the build), not the last chunk write: it orders generations; it does not date the data in them.
- RUNBOOK :298: the notes now name the newest aside with its date, list older ones as "older", and name a `.dead.tmp` with its size and an `rm -r`.
- test_config.py: no `os.replace` or write added to or removed from cafe/pm (the change is reads and string building): its counts are unchanged.

## Not verified / still wrong
- The `.dead.tmp` size walk (`_size_bytes`) of a 20 GB half-deleted store is a stat of every remaining file: not timed; it runs only when one is beside the store.
- The mtime of a directory is not changed by writes inside subdirectories; for a store built by `write_store` and renamed whole this is the build time. A lab store
  that someone edited by hand in place could carry any date. Not measured on a real store (the tests set the time with `os.utime`).
- Coverage (job `r20e_cov4`, rc=0, the four hycom test files, `--cov=cafe.pm.env.hycom`): 99.71 %, the only missing lines are 280-281, the existing `except OSError: pass` of
  `_size_bytes`, not mine (covered by another test file in the gate, not run here). Every line I added in hycom.py is covered. pipeline.py coverage not measured.
- Not run: the whole of tests/test_pipeline.py (it was started, 17 % in 13 minutes with no failure, and killed by me by session name; rc=143 is that job).
