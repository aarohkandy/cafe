# Round 20, batch D hand-back (M-7 and the SEb test of M-10; `cafe/_seed.py`)

Branch r20-d from 8e22951. Product change: `cafe/_seed.py` only (read only: `cafe/vehicle.py`, `cafe/_site_data.py`, `cafe/cfd.py`).

## What changed

1. `main` catches `RecursionError` beside `OSError` and `ValueError`: a deeply nested file is `NOT seeded <file> - maximum recursion depth exceeded ...`, exit 1,
   nothing written (D-3).
2. `_checked` (external): `dirs` must hold exactly the six directions of `cfd.DIRS` (was: any non-empty subset). Equality, not "at least six": `vehicle.py:286`
   looks every label of `dirs` up in `DIRS`, so a seventh label (the angle labels of the other study) is a KeyError there (D-4).
3. `_checked` (external): every direction must hold a `gci` that is an `int` or `float` and not a `bool` (D-4).
4. SEb: no code change. `_vec` already says `len(v) == 3`; the gap was a test. The new test refuses a `force`, `moment` and `viscous` of four numbers (and of two,
   none, and one NaN).

## Where the merged.md default was adjusted (read this)

- merged.md says "each with `gci`". Measured: `cfd.gci` returns NaN where it has no index (zero fine-grid drag, ratio not above 1), and `characterize_external`
  then takes inf as the study's worst (`cfd.py:446-454`, `:488`); `json.dumps` writes NaN and Infinity and `json.loads` reads them back. A real file can therefore
  hold a non-finite `gci`. A finite-only check (`_num`, the helper beside it) would have refused a result the CFD code itself made, so the check is on the type
  (a number that is not a bool), not the value. NaN and inf are seeded (test `..._seeded_nan_and_inf_included`). The three real fixtures all have finite `gci`
  and six directions (a test asserts it).
- merged.md's "must fail before" lists "a `force` of four numbers" as giving "seeded" before. It did not: `len(v) == 3` already refused it. That row of
  M-10 is a mutant (`len(v) >= 3`), not a bug. The test passes before and after the fix; it fails on the mutant (see evidence). Not a regression test of a fix.

## Tests (all in tests/test_round20_d.py, run on orca, proot, 2 CPUs)

Before = tree at 8e22951 with the new and moved test files copied in (git worktree --detach at 8e22951, throwaway `cafe-r20d-base`), `_seed.py` unfixed.
After = r20-d. Progress characters counted from the log, rc from the log.

| test | before | after |
|---|---|---|
| nested `[` x 100000 (with a good quad file beside it) | FAIL (RecursionError) | pass |
| nested `{"a":` x 100000 | FAIL | pass |
| `dirs` of `+x` only; of five directions (each of `-z`, `+z` left out); of `-z` only (4 cases) | FAIL ("seeded") | pass |
| gci absent / None / "0.1" / True / [0.1] / {} (6 cases) | FAIL ("seeded") | pass |
| gci 0, 0.0, 3, 0.05, NaN, inf are seeded (6) | pass | pass (guard against a finite-only check) |
| a seventh direction `x+y15` | pass (subset check) | pass |
| SEb: force, moment, viscous of four, two, none numbers, or with a NaN (12) | pass | pass; with `len(v) >= 3` they FAIL (3 failures: the four-number case of each field) |
| the three real fixtures (`tests/fixtures/cfd_real`): six directions with finite gci, all three seed end to end, a second run says "already there" x3 | pass | pass |

- before, `tests/test_round20_d.py` + `tests/test_round19_d.py`: job r20d_8 (final test file), rc=1, 79 passed 12 failed (the 12 are the first three rows above).
- after, `tests/test_round20_d.py`, `test_round19_d.py`, `test_round17_e.py`, `test_round18_d.py`, `test_round19_m.py`: job r20d_7, rc=0, 227 passed 0 failed.
- mutant `len(v) >= 3` on the fixed tree: job r20d_3 (`test_round20_d.py` + `test_round19_d.py`), rc=1, 88 passed 3 failed (the SEb tests, `vec0` of each field).
- `ruff check cafe/pm tests`: job r20d_6, rc=0 "All checks passed". Banned-token regex (`audit.BANNED`) grepped over the five touched files: no match.
  (r20d_1 to r20d_5 were earlier runs of the same files before an unused-import and fixture-redefinition lint fix to my test file; all superseded.)
- Not run: the full suite, the gate, mypy (`cafe/_seed.py` is outside `cafe/pm`), the audit. `cafe/vehicle.py` and `cafe/_site_data.py` untouched.

## Pins that moved (existing test files), each and why

None of them pins a product answer; each is a stand-in result the strict check now correctly refuses, rebuilt to the shape of a real one.
- `tests/test_round17_e.py::test_r17_m12_seed_reads_the_runs_beside_the_cache_and_writes_the_cache`: `made["dirs"]` was `+x` only, no `gci`; now the six directions
  of `cfd.DIRS` each with `gci=0.01`. The assertion `d["result"] == made` is unchanged and still holds.
- `tests/test_round18_d.py::seed_runs` (fixture): same stand-in, same change.
- `tests/test_round19_d.py::external()`: same stand-in. New helper `six(**plus_x)` there. `BAD_EXTERNAL`: "a force of two numbers", "a force with a string",
  "a direction that is no axis" (now the six plus `+q`), "a direction that is a list" (now the six with `+x` a list) were rebuilt on the full six so each is
  still refused for the reason in its name, not for the missing directions (without that they would have kept passing for the wrong reason). "no force",
  "empty dirs", "no dirs" are unchanged and still meaningful.
- `tests/test_round19_m.py` (real fixtures) needed no change.
No assertion was weakened or removed.

## For batch G (documents)

- DECISIONS row (number after the last): "`cafe._seed` refuses an external result that does not hold all six directions of `cfd.DIRS` or a direction without a
  numeric `gci` (NaN and inf accepted: `cfd.gci` writes NaN where it has no index), and reports a deeply nested file as `NOT seeded <file> - <reason>` (round 20,
  M-7; amends row 1007's list of what `_checked` asks). The real results in `tests/fixtures/cfd_real` pass."
- CHANGELOG line: "`cafe._seed`: a result with fewer than six directions or a direction without a `gci` is NOT seeded; a deeply nested JSON file is NOT seeded, not a
  RecursionError (round 20, M-7); test for `_vec`'s three-number rule (M-10 SEb)."
- Docs naming the old rule: not searched (docs are batch G's). `_seed.py`'s own module docstring still says "not a result of its case", still true.

## Not verified / still looks wrong

- A NaN or inf `gci` seeded from a real file goes on to `vehicle.py:291` (`r.get("gci", 0.0)`) and the mission's uncertainty use; I did not trace what a NaN does there
  (it is the same value the cache of a real run already carries today, so it is not new). Worth one look by whoever owns the drag-uncertainty path.
- Missing `gci` was read as 0.0 by `vehicle.py` (a perfect grid) and a KeyError by `_site_data.py`; I did not touch either (out of scope), the seed check now keeps such a file
  from being cached in the first place. A hand-placed cache file is not checked by anything.
- The `wigley` (surface) path is unchanged apart from sharing the `RecursionError` catch.

## Leftovers

- Orca: `~/cafe-worker/cafe/pm_r20d` and `pm_r20d_base` (synced trees), logs `~/cafe-worker/logs/r20d_1.log` to `r20d_8.log`, finished tmux sessions gone; no running job of mine.
  Nothing outside `~/cafe-worker`.
- Laptop: throwaway worktree `/Users/aaroh/Downloads/everything/cafe-r20d-base` (detached at 8e22951, with the mutated-then-restored `_seed.py` and copies of my test
  files; delete with `git worktree remove --force` when the lead is done with it as evidence). Nothing pushed.
