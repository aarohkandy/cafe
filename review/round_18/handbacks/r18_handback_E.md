# Round 18, batch E hand-back (atomic writers, locks, store replace)

Branch `r18-e`, worktree `cafe-r18e`, cut from `premission-step4` at d69be8f. Code and tests: 97cecbb and 3e9c2b7; this file is the last commit.
Findings done: M-8, M-9, M-13, and the A-4 and A-6 tests of M-16. Skipped: none. Decisions taken as the lead set them: OD-7, OD-8, OD-10.

## Files touched

Production (all on the batch list): `cafe/atomic.py`, `cafe/pm/emulator.py`, `cafe/pm/env/remote.py`, `cafe/pm/env/hycom.py`. `cafe/pm/env/hycom.py` and `remote.py`
are under the 100 % gate.
Tests: `tests/test_round18_e.py` (new, 26 tests) and one pin moved in `tests/test_config.py` (`BARE_REPLACES["env/hycom.py"]` 1 -> 3: see M-13; it sits in this batch
because my code moves it; the batch list did not name the file). No other test file needed an edit: `test_round17_f.py`, `test_remote.py`, `test_emulator.py`,
`test_hycom.py` pass unchanged. No document, DECISIONS, CHANGELOG, STATUS, HANDOFF, QUESTIONS_FOR_LAB or PROBLEMS file is edited.

## What changed, per finding

### M-8 `atomic.replace_from` and a link as the source (OD-10)
- `cafe/atomic.py` `replace_from`: `src` is opened with `O_RDONLY | O_NOFOLLOW | O_CLOEXEC` whatever the target is; `fchmod` only when the target has a mode to keep; the fd
  is closed either way; then `os.replace`. The `_target` rules, the nine permission bits, no setuid/setgid/sticky, no copy (a rename), and the signature are unchanged. A
  missing source is still `FileNotFoundError` (from the open instead of the rename). Docstring says so.
- Callers (grep): `remote._download` (the first fetch of a TAO file) and `hycom._fetch_part` (a first part): both always have a new target, so the guard now applies to the
  first fetch, which is the case the finding is about. No other caller.
- Tests: `test_r18_m8_a_link_as_the_source_is_eloop_for_a_new_target_too[False|True]` (the new-target link source, with and without `follow_symlinks`, and a new target
  reached through a dangling link), `test_r18_m8_a_regular_source_for_a_new_target_still_moves_with_the_umasks_mode_and_leaves_no_file_behind` (guard).

### M-9 the emulator table's lock and `store_lock` (OD-8)
- `emulator.locked`: the lock file is opened with `os.open(..., O_RDWR | O_CREAT | O_NOFOLLOW | O_CLOEXEC, 0o666)` (the umask applies; an existing lock's mode is never
  changed); any `OSError` of the `mkdir` or the open is a `ConfigError` that names the lock file, the errno text, what stands at the name (a link: "never followed: remove it";
  not a regular file: remove it; a file: its owner, its mode and ``chmod g+w <file>`` or removal; an owner that cannot be read, `KeyError` included as in a container:
  directory/permissions advice) and says why the run does not go on (the lock stops two runs from losing each other's rows). The flock is released (`LOCK_UN`) and the fd
  closed when the block ends or raises. New helper `_lock_remedy`. Without `fcntl` the block runs as before.
- `remote.store_lock`: created `0o666` under the umask (was `0o644`); optional keyword `log: Callable[[str], None] | None = None`; when the block runs unlocked (no `fcntl`, a
  failed open) `log` is called once, before the block, with `warning: <lock> is not locked (<why>); this block runs without the lock, so another run that shares the directory
  may write at the same time`; no line for `create=False` with no file (the audit asks for none), none for a lock held (also re-entrantly), none when `log` is None
  (the existing callers). Return value (True/False) and the `O_NOFOLLOW | O_CLOEXEC` open unchanged.
- **Not done, needs a lead decision (outside the batch's files):** `pipeline._shared_store` (cafe/pm/pipeline.py:451) is the ingest's call; it does not pass `log` yet, so
  the ingest still runs unlocked in silence until it does. The edit is one argument: `log=ctx.log` next to the existing `wait=...`, and the same for the `derived.lock` calls
  (`pipeline.py:1050, 1071, 1110`, and `surface.py:66, 134, 226`, which have no logger in scope). No batch owns `pipeline.py`. The default `None` keeps every existing call
  valid, as the batch notes said.
- Not changed, and said: under `umask 077` a lock is still created 0600 (the umask applies, as OD-8 says), so a second account still cannot open it: for the emulator that is
  now a `ConfigError` naming the file and the owner (it was a bare `PermissionError`); for `store_lock` it is the logged warning (when `log` is passed). The remedy in the
  message is a `chmod g+w` by the owner. A lock that exists is never chmod'ed by the code.
- Callers of `emulator.locked` (grep): `Emulator.append` (emulator.py:144) and `whatif.py:429`: both now raise `ConfigError` where they raised `PermissionError`/`OSError`.
  `test_cli.py:1208`'s test patches a stage to raise `PermissionError` and is unaffected (passes).
- Tests: `test_r18_m9_the_emulator_lock_is_opened_without_following_links_close_on_exec_and_0o666`, `..._takes_the_umask_and_never_changes_the_mode_of_one_that_exists`,
  `..._a_link_planted_at_the_emulator_lock_is_refused_and_its_target_is_not_made`, `..._a_lock_that_cannot_be_opened_is_a_config_error_that_names_the_file_its_owner_and_the_remedy`,
  `..._what_stands_at_the_lock_name_decides_the_remedy` (directory, owner unreadable `KeyError`, directory that cannot be made), `..._the_emulator_lock_is_released_when_the_block_raises`,
  `..._an_append_with_an_unusable_lock_writes_nothing_and_says_why`, `test_r18_m9_store_lock_creates_its_file_0o666_under_the_umask_and_keeps_the_mode_of_one_that_exists`,
  `..._store_lock_logs_once_when_its_block_runs_unlocked` (planted link, missing directory, no fcntl), `..._store_lock_says_nothing_when_it_holds_the_lock_or_nothing_was_to_be_locked`.

### M-13 `hycom.write_store` (OD-7)
- Order now: build in `atomic.tmp_name(out)` (as before); `old = atomic.tmp_name(out)` if `out` is a directory and not a link; `os.replace(out, old)`; `os.replace(tmp, out)`;
  `shutil.rmtree(old, ignore_errors=True)`. If the second rename raises (any `BaseException`), `os.replace(old, out)` puts the old store back and the error is re-raised;
  the existing outer `except` still removes `tmp`. If the put-back fails too, the original error is the `__context__` of the put-back's, and the old store is kept whole
  beside the name (`.<hex>.tmp`), never deleted. A fresh store (no `out`) is one rename as before. A link at `out` is not moved aside: the rename onto it is `ENOTDIR`, as before
  (a link is never followed or replaced; kept deliberately, a test guards it). The docstring stops saying "atomically" and states the two-rename gap, the kill case and where the
  old store waits.
- **Crash points (each tested):** (a) failure while building: unchanged, covered by `test_r16_m24_a_store_write_that_fails...`; (b) first rename fails: the old store stays, no
  temporary; (c) second rename fails: the old store is put back whole, no temporary; (d) second rename and put-back fail: the old store whole beside the name, the name absent and
  `open_store` refuses it (`ConfigError`: "cannot be read ... run FETCH again"), nothing deleted; (e) the delete of the old store does not finish: the new store is in place and
  readable, the old one is left aside; (f) three real kills (`os._exit(7)` in a child process, at the rename): before the old store is moved aside the name is the old store
  and nothing of the old is aside; between the two renames the name is absent, `open_store` refuses it, and the old store is whole under a `.tmp` name; after the second rename the
  name is the new store (full time axis) and the old one is whole under a `.tmp` name; in all three the next `write_store` works. So the name is never half a tree or an empty
  store; for the time between the two renames it is absent, which the readers already treat as "fetch it". That window is the remaining gap and is stated in the docstring.
- Cost: a kill after the second rename leaves a whole copy of the old store (`.<hex>.tmp`, ignored by `bin/sync_filters` and `pipeline.is_junk`) on a disk that is 97 % full; the
  next ingest does not clean it. Same class as P-R16C2 (a killed ingest leaves a `.tmp`), only larger: the store is 10s of GB for a real box. A sweep of stale `.<hex>.tmp`
  directories beside a store would be a new feature; not done.
- Pin: `tests/test_config.py` `BARE_REPLACES["env/hycom.py"]` is 3 (three `os.replace` calls: aside, in, put-back), with the reason.
- Tests: `test_r18_m13_the_old_store_goes_aside_whole_the_new_one_in_and_only_then_the_old_one_is_deleted` (the order of the three calls, the old tree whole at the first and at the
  delete), `..._a_first_store_is_one_rename_with_nothing_aside`, `..._a_failed_first_rename_...`, `..._a_failed_second_rename_puts_the_old_store_back_whole_...`,
  `..._when_the_put_back_fails_too_...`, `..._a_delete_of_the_old_store_that_does_not_finish_...`, `..._a_link_at_the_store_name_is_not_replaced_...` (guard),
  `..._a_process_killed_at_any_point_of_the_replace_leaves_a_readable_store_or_a_clear_refusal[before_aside|between|after_in]`. The file imports `fx` and `truth` from
  `tests/test_hycom.py` for the store fixture.

### M-16 A-4 and A-6 (tests only)
- A-4: `test_r18_m16_a4_a_download_that_waited_for_the_lock_finds_the_file_the_first_one_made_and_fetches_nothing` (the test holds the lock, a thread waits in `download`, the file is
  made, the lock released: the server log stays empty, so the re-check inside the lock is what returned it) and
  `test_r18_m16_a4_an_unlocked_download_that_fails_mid_way_removes_its_part_and_its_record` (no lock; the body is cut after the first read; nothing but `a.lock` is left).
- A-6: `test_r18_m16_a6_the_temporary_of_an_existing_file_is_0o600_while_it_is_written_and_a_new_files_has_the_creation_mode` (the mode of the temporary read through the descriptor
  during the write, for `write_with` and for `_replace_through` directly: 0o600 for an existing file, `0o666 & ~umask` for a new one).

## Fail before

All on orca, proot, 2 CPUs; logs `~/cafe-worker/logs/<tag>.log`.
- **Base** (`r18e_b1`): `tests/test_round18_e.py` alone in a detached worktree at d69be8f (orca `pm_r18e_base`, removed): **18 failed, 8 passed** (26 tests), PYTEST_RC=1.
  Failed for the defect: M-8 x2; the emulator-lock opened-flags, planted-link, cannot-open, what-stands, unusable-lock-append tests (5); `store_lock` 0o666; M-13: the order test, the
  first-rename, second-rename, both-fail and delete tests (5), and the three kill points (3).
  **Failed only for a missing name on base (not evidence of the defect):** `test_r18_m9_store_lock_logs_once_when_its_block_runs_unlocked` and `..._store_lock_says_nothing_...`
  (the `log` keyword does not exist there).
  Passed on base, as designed: the regular-source guard (M-8), the emulator lock's umask test, the lock-released test, the link-at-the-store-name guard, the fresh-store test, and
  the three M-16 tests (they test correct behaviour and are for the mutants below).
- **Mutants** (driver `mut.py`, a copy in the scratchpad, applies one replacement to the file, runs the named tests with `-x`, restores): `r18e_6` and, for the one survivor after
  its test was strengthened, `r18e_9`. Killed (rc=1): A-4 inside-the-lock re-check as `if False:`; A-4 `finally` of the unlocked part as `pass`; A-6 `0o666` for the existing-file
  temporary; A-6 `0o600` for the new-file one; M-8 `O_NOFOLLOW` only when a mode is kept; M-8 no `O_NOFOLLOW`; emulator lock `0o600`; emulator lock without `O_NOFOLLOW`;
  emulator remedy without its link branch (this one **survived** in `r18e_6`: the errno text for ELOOP already contains "symbolic link", so my assertion was too weak; the test now
  asserts "never followed" and the mutant is killed in `r18e_9`); `store_lock` `0o644`; `store_lock` logging the audit's absent file; `store_lock` never logging; `write_store` without
  the put-back; without the delete of the old store; moving a link aside; deleting first. 16 mutants, 15 killed at first, 16 after the fix. The A-1 to A-3, A-5 mutants belong to other batches.

## Final runs

- `r18e_7` (commit 97cecbb): `pytest -n 2 --cov=cafe/pm/env` on 18 files (`tests/test_round18_e.py test_round17_f.py test_round16_pb.py test_round15_a.py test_remote.py
  test_ingest_fetch.py test_emulator.py test_hycom.py test_ledger.py test_config.py test_audit.py test_surface.py test_tao.py test_ocean.py test_bathy.py test_orca.py
  test_round16_a.py test_round17_m.py`): 1,303 passed by the dot count, 1 failed (`test_audit::test_the_whole_scanned_tree_has_no_banned_token_today`: `NotImplementedError` in
  my `except` of `_lock_remedy`, fixed in 3e9c2b7), PYTEST_RC=1. **Coverage: `cafe/pm/env/hycom.py` 100 % (631 statements, 0 missed), `cafe/pm/env/remote.py` 100 % (369, 0 missed)**
  (`env/surface.py`, `ocean.py`, `orca.py` also 100 %; the other env modules in that table are not changed by this batch and are covered by other files than this selection).
- `r18e_8` (commit 3e9c2b7, the final code): part 1 `pytest -n 2 tests/test_round18_e.py test_emulator.py test_config.py test_audit.py`: 502 passed, 0 failed, PYTEST_RC=0.
  `ruff check cafe/pm cafe/atomic.py tests`: "All checks passed", RUFF_RC=0. `mypy cafe/pm`: "Success: no issues found in 55 source files", MYPY_RC=0.
  `python -m cafe.pm audit --code-only`: **1 problem, AUDIT_RC=1: "mutation: no stored result at docs/mutation.json"**, which is the missing record of `make mutation` (the file is not in the
  repository, in `cafe_main` either; nothing to do with this batch). The banned-token scan is clean (the other problem of `r18e_7` is gone). Part 2 `pytest -n 2 tests/test_pipeline.py
  test_cli.py test_whatif.py test_acceptance.py test_reproducible.py test_credibility.py test_report.py` (the callers of `store_lock` and of `emulator.locked`, and the pins of reports):
  1,386 passed, 0 failed, PYTEST2_RC=0, job rc=0.
- Every test file that imports or pins what I changed was run: `test_round18_e` (new), `test_round17_f` (the round 17 batch F pins: modes, links, `store_lock`, `replace_from`),
  `test_round16_pb`, `test_round15_a` (atomic writers), `test_remote`, `test_ingest_fetch`, `test_tao` (downloads, locks), `test_emulator`, `test_hycom`, `test_ocean`, `test_orca`,
  `test_bathy`, `test_surface`, `test_ledger`, `test_config` (the write scans), `test_audit`, `test_pipeline` (`_shared_store`, `derived.lock`), `test_cli`, `test_whatif`,
  `test_acceptance`, `test_reproducible`, `test_credibility`, `test_report`, `test_round16_a`, `test_round17_m`. Counts method: `grep -aE "^[.sxFE]+ *(\[ *[0-9]+%\])?$" | sed ... | uniq -c`.

## Proposed DECISIONS rows (the lead numbers them, after 951; each amends the rows named)

- "R18-E1. `atomic.replace_from` opens its source with `O_NOFOLLOW` whether or not the target exists (it did so only for an existing target, so the first fetch of a TAO file or a GOFS
  part, which has a new target, accepted a link as its source and the target became a link): a link at the source is ELOOP for every call, a failed call leaves both names as they
  were. (amends 937; OD-10)"
- "R18-E2. The emulator table's lock file is opened as the table's writers open theirs: `O_NOFOLLOW | O_CLOEXEC`, created `0o666` under the umask, the mode of an existing lock never
  changed; a lock that cannot be opened (a link at the name, a file of another account without write access, a directory that cannot be made) is a `ConfigError` that names the file,
  its owner and the remedy, and the run stops, because the lock is what stops two runs from losing each other's rows. `store_lock` creates its file `0o666` under the umask (it was
  `0o644`, which a second account could not open read-write: its block ran unlocked in silence) and takes an optional `log`: called once, before the block, when the block runs unlocked,
  except for `create=False` with no file. Not changed: a lock made under umask 077 is 0600 and a second account still cannot use it (a `ConfigError` for the emulator, the warning for
  `store_lock`). Not done: the ingest's `_shared_store` does not pass `log` yet (pipeline.py). (amends 934; OD-8)"
- "R18-E3. `hycom.write_store` puts a store in place by renames: the old store is renamed aside (`.<hex>.tmp`), the new one renamed in, then the old one deleted, and the old one is put back if
  the second rename fails; it deleted the old store first, so for the length of a delete of thousands of chunk files the name held nothing or half a tree. The write is two renames,
  not one, and the docstring no longer says "atomically": the name is absent between them, which the readers refuse as missing (`unreadable`); a kill there leaves the old store whole
  under a `.tmp` name, and a kill after the second rename leaves it too (a whole copy of the old store on a disk that is 97 % full, not cleaned by the next ingest). A link at the
  name is still not replaced (ENOTDIR). (amends 911, 941; OD-7)"
- CHANGELOG lines: "Fixed: a link as the source of `atomic.replace_from` was accepted for a new target." / "Fixed: the emulator table's lock followed a link and failed with a bare PermissionError
  for another account's lock; `store_lock` created a 0o644 lock a second account could not use and ran unlocked without a word (it logs, when given a logger)." / "Fixed: the ocean
  store was deleted before the new one was moved in; it is renamed aside first."

## Document sentences for batch G

- RUNBOOK :295 (the locks): "The emulator table `train.parquet` has a lock file `train.parquet.lock` beside it, and the ocean store, the GEBCO cut and each TAO file one `<name>.lock`:
  delete none of them while a run is going on. A lock file is created with the umask's mode (group-writable under 002); one made under `umask 077` is 0600 and another account cannot
  use it: `chmod g+w` it as its owner (the emulator's error names the file and the owner; the ingest's log line says the block ran unlocked)."
- RUNBOOK, ingest troubleshooting: "A `.<hex>.tmp` directory beside `gofs_*.zarr` is a store of an earlier ingest that was killed while it replaced it: the one that holds the old data is
  whole and can be renamed back to the store's name (if the store is missing) or deleted (if it is there). `delete` is safe once the store's name opens."
- PROBLEMS (orca/PROBLEMS.md): "P-R18E1: `store_lock` callers do not pass `log` (pipeline.py, surface.py): an unlocked block is silent there until they do."

## Not verified

- Nothing was run against a real GOFS store, a real TAO server, two real ingests, or two accounts: the second-account halves of M-9 are tested by an injected `PermissionError`
  (orca's account has no passwd entry, so `Path.owner` is `KeyError` there: that branch is tested too, the owner-named branch with a patched `owner`).
- The kills are real process kills of `write_store` on a small fixture store (the unit tests' size), not on a store of 10s of GB; the time between the two renames is two directory
  renames either way.
- The mutation driver covers my fixes and A-4, A-6 only; `make mutation` (physics and stats) is not affected by this batch and was not run.
- The full suite and the gate were not run (the lead's); the focused runs above are the 25 files listed.
- `audit --code-only` is red for the missing `docs/mutation.json` only; not mine.

## Outside the batch

- `cafe/pm/pipeline.py` and `cafe/pm/env/surface.py`: the `log=` argument for the ingest (above). No batch owns them; one argument each at the call sites named.
- `docs/mutation.json` is missing from the repository, so `python -m cafe.pm audit --code-only` is red in every worktree.
- `emulator.py` line 208 is 173 bytes long (awk count; ruff is clean: the file's own `# type: ignore` line): not touched.

## Left on orca

`~/cafe-worker/cafe/pm_r18e` (the synced tree of this branch, and `~/cafe-worker/cafe/.pmx.job.pm_r18e`), the logs `~/cafe-worker/logs/r18e_1.log` to `r18e_9.log` and `r18e_b1.log`. Removed
by exact name: `pm_r18e_base` and `.pmx.job.pm_r18e_base`. No shared store, cache or `/data/runs/q18` was written; the tests use pytest's temporary directories (inside the proot's `/tmp`,
which is the worker's own). The laptop worktree `cafe-r18e-base` is removed; `x_r18e/` (the scripts, uncommitted) was moved to the session scratchpad
(`/private/tmp/claude-501/-Users-aaroh-Downloads-everything-cafe-main/e5175414-543a-42ed-83ef-98e3ca2ddc48/scratchpad/r18e/`: `mut.py`, `a.sh`, `b2.sh`, `t1.sh`).
