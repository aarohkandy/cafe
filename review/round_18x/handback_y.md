# Hand-back y: P-R18X3, the child that ends with -6

Branch `r18-y` (from `r18-x` at 684642c). Commits: `2d77ae5` (the fix and its test), `7c799a1` (ruff B007 in the new test), `7260ebb` (the stand-in
for `pd.read_parquet` in an old test takes the new argument), then the documents (DECISIONS 995, CHANGELOG, PROBLEMS P-R18X3 and P-R18Y1, this file,
`r18y_probe.py`). Nothing pushed.

## Cause

Measured on orca (Python 3.12.3, pandas 2.3.3, pyarrow 21.0.0; jobs pinned to 2 cores; three children at once in three groups, nine processes;
`PYTHONFAULTHANDLER=1`). Counts are children that ended with -6 of the children run (3 per group) unless it says groups. Probe: `review/round_18x/r18y_probe.py`.

1. **The abort comes after all the work.** Every aborting child printed a marker after its last `add_rows` before `terminate called without an active
   exception`; the table had 36 rows, was readable, no temporary was left (3 of 3 aborts, in the pandas-and-pyarrow-only probe). faulthandler: the
   aborting thread is not the main thread; the main thread is in interpreter shutdown.
2. **It is pyarrow, not JAX, not whatif, not our lock.** `cafe.pm.whatif` imports JAX (XLA threads are alive at exit) but a child with only pandas and
   pyarrow aborts the same way (3 of 1,200). The sharp case is a child that only reads the table and exits:
   `pd.read_parquet(path)` 88 of 900; `pq.read_table(open(path, 'rb'))` (pandas out of it, a Python file object) 28 of 300;
   `pq.read_table(path)` 0 of 300; `pd.read_parquet(path, filesystem=LocalFileSystem())` 0 of 300; `read_table` of ours after the fix 0 of 300.
   Other probes: `pyarrow.set_io_thread_count(1)` + `set_cpu_count(1)` 0 of 300; `use_threads=False` 27 of 300 (no help); `pre_buffer=False` 11 of 300
   (fewer); `pq.ParquetFile(path).read()` 0 of 300; writes alone (path or file object) 0 of 900 each. The window is short: exit 5 ms after the last read 8 of 300,
   50 ms 0 of 300, 250 ms 0 of 300, 1 s 0 of 300. So: pandas, given no `filesystem`, opens the file and hands pyarrow a Python file object; pyarrow's IO threads
   call back into it, and a thread still alive when the interpreter finalizes ends the process with -6. **Inferred, not measured:** that the thread is
   in the GIL acquire of such a callback and that CPython 3.12 then ends it with `pthread_exit` through C++ frames (the usual source of this message). No
   native backtrace was taken.
3. **Not new.** `read_table` alone (the read-and-exit child): 36 of 300 on 684642c, 50 of 300 on 4697b74 (before round 18), 32 of 300 on 23efe7e (before
   round 16). The locked read-modify-write children (the test's shape): 0 of 300 on 684642c here (plus 0 of 100 runs of the old test itself, and 0 of 100
   after the fix), 1 of 900 on 4697b74, 0 of 900 on 23efe7e; the pandas-only version 3 of 1,200 (the later 0 of 900 are a control run of the same probe).
   Round 18's lock change is not the cause. The old test's own failure rate here (2 of 40 beside a gate before) is not reproduced in 100 runs: it has no
   measured before and after; the read-and-exit children and the new test carry the proof.
4. **A real run.** Exposed only if its last act before exit is a read of the table. `run` (preflight read, then hours of work; its last `add_rows` is
   followed by the fresh measurements and the report) and `whatif` (reads in `train`, then `answer`) work for seconds after their last
   read, far above the 50 ms measured. **Inferred small; I did not measure a real run** (no demo run was made). A caller that reads the table as its very last act
   (a script, a test) is exposed, which is what the new test does on purpose.

## Fix

`cafe/pm/emulator.py::read_table`: `pd.read_parquet(path, filesystem=pyarrow.fs.LocalFileSystem())`, so pyarrow opens the path. It is the one function
every read of the table goes through (`add_rows`, `train`, `snapshot`, the pipeline preflight); there is no other `read_parquet` in `cafe/`. Needs
pandas >= 2.1 (the `filesystem` argument; the image has 2.3.3). Nothing in the test was weakened, retried or caught.

## Test

`tests/test_emulator.py::test_a_process_that_reads_the_table_and_then_exits_ends_with_status_0`: 36 children (3 waves of 12 at once) each read the table 12
times with `read_table` and exit; all must end with 0. Probabilistic and its docstring says so. On orca, 2 pinned cores, the test as written, 20 runs each:
**before the fix 20 of 20 fail** (each with some `-6`), **after 0 of 20**. (Per child: 36 of 300 before, 0 of 300 after.) A pass on the old code is possible (about 1 %
at the measured per-child rate); a failure on the new code is a real abort. Also changed: the stand-in for `pd.read_parquet` in
`test_parquet_path_is_used_when_pyarrow_is_present` takes `**kw` (its assertions are unchanged).

## Verified (orca, PM_CPUS=2)

- `ruff check cafe/pm tests`: rc 0. `mypy cafe/pm`: rc 0.
- `tests/test_whatif.py tests/test_emulator.py tests/test_round18_e.py tests/test_round17_f.py`: rc 0, 295 passed (job `r18y_M`, junit `pmdata/r18y_M_junit.xml`).
- Files that mention `read_table`, `add_rows` or `read_parquet`: `tests/test_pipeline.py tests/test_cli.py tests/test_report.py tests/test_reproducible.py
  tests/test_round15_a.py tests/test_runners.py tests/test_acceptance.py` (job `r18y_N`): N_RESULT.

## Not verified

- A native backtrace of the aborting thread; the demo or any real run's exit status (no run was made).
- The full suite and coverage (the lead's gate). The new code is two statements in `read_table`, covered by the existing and new tests; no coverage run was made by me.
- That the fix removes the abort in the read-modify-write children themselves: their rate here is too low (about 0.3 % of groups) to show a difference in 100 to
  300 groups; the read-and-exit children (0 of 300 after, 36 of 300 before) and the new test are the evidence.

## Orca leftovers

Listed by exact name in PROBLEMS P-R18Y1. None deleted by me.
