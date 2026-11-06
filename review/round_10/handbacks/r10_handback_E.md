# Round 10, batch E: runner scripts and their tests (branch r10-e, from 6c352ef)

Findings: M-23, M-30, M-26, M-28, M-29, M-31, in that order. Docs (DECISIONS, CHANGELOG, RUNBOOK, CLAUDE.md, HANDOFF, docs/ORCA_RUNNER.md) are not edited; the text for them is below.

What is new: `bin/pm_checks.sh`, sourced (never run) by `pm.sh`, `bin/pmx.sh`, `bin/orca_ready.sh`, `bin/orca_gate.sh` and `bin/proot_suite.sh`. It holds every rule about what a name or a number may be before it is pasted into a command line: `pm_num`, `pm_size`, `pm_shape`, `pm_tag`, `pm_names` (PMX, TM), `pm_job` (PM_CPUS, PM_STOP_GRACE, CAFE_MIN_FREE_GB, PM_THREADS in proot; PM_CPUS, PM_MEM, PM_SHM in docker). Each exits 2 before anything is sent. `PM_STOP_GRACE` and the `PMX`/`TM` rules moved into it from the two copies in `pmx.sh`/`pm.sh` (same wording, one copy now).

Evidence (all on cafe-orca, proot, `pm_r10e*`, 2 CPUs):
- Final code: `tests/test_shares.py tests/test_proot_suite.py tests/test_runners.py tests/test_config_docs.py` rc=0 on the final tree; `tests/test_audit.py` rc=0 together with them one edit earlier; `ruff check cafe/pm tests` clean; `mypy cafe/pm` strict, no issues in 55 files; `audit --code-only`: the banned scan and ledgers clean, its one problem is the absent `docs/mutation.json` (not from this batch).
- Unfixed code: a detached worktree at 6c352ef with the three new test files copied in failed every new test of M-23, M-26, M-28, M-29, M-30, M-31 (112 test ids, counted in the log of the run `r10e_mut`, not kept). For M-30 the fixture needs `pm_checks.sh`, so it was run again with only that file added to the old tree: the old `orca_ready.sh` still failed the PMX, marker, name-of-ours and pasted-value tests for the reasons the tests name. The worktree and its orca directory were removed.

## M-23: one check of what is pasted into the remote command line

DECISIONS row: `bin/pm_checks.sh` is the one place that decides what `pm.sh`, `bin/pmx.sh` and `bin/orca_ready.sh` may paste into a command line, and each refuses with exit 2 and nothing sent. `PM_CPUS` and `PM_THREADS` and `CAFE_MIN_FREE_GB` (proot) are whole numbers from 1 (`02`, `1.5`, `2,` and `2;x` are refused); `PM_MEM` and `PM_SHM` (docker) are such a number with an optional `k`, `m`, `g`, `kb`, `mb`, `gb` or `b` (upper case too); `PM_STOP_GRACE` stays whole seconds (0 allowed); `TM` is 2 or more letters, digits, `_` or `-`, the first a letter or digit. `bin/proot_run.sh` refuses a `PM_CPUS` that is not a whole number from 1 too (exit 2, checked before the proot files), for a run by hand on the worker. | The value is parsed by a shell on the worker or by docker, so a `;` was a command (`PM_CPUS='2;x'` ran `x` on orca, `CAFE_MIN_FREE_GB='1;echo INJ'` ran `echo INJ`), `2,` became `CAFE_WORKERS=2,` with a misleading 32-CPU warning, `TM=x` is no docker name and `TM=-x` is a tmux option. Only the caller's own environment could inject, so the harm was a wrong run, not an attack.

Amends: 488 (TM: now also 2 or more characters, first a letter or digit; PMX unchanged), 500 (the `PM_STOP_GRACE` check moved to the shared file, same rule and wording), 524 (`PM_THREADS` is validated on the laptop as well as in `proot_run.sh`).

CHANGELOG: `bin/pm_checks.sh` (new): `pm.sh`, `bin/pmx.sh` and `bin/orca_ready.sh` refuse a `PM_CPUS`, `PM_MEM`, `PM_SHM`, `PM_THREADS`, `CAFE_MIN_FREE_GB` or `TM` that is not plain, before anything is sent (exit 2); a decimal `PM_CPUS` such as `1.5` is no longer accepted; DECISIONS (M-23).

Doc sentences: docs/ORCA_RUNNER.md, the table row for `PMX` and `TM` (line 67): add "`PM_CPUS`, `PM_THREADS`, `CAFE_MIN_FREE_GB`: whole numbers from 1; `PM_MEM`, `PM_SHM`: a number and optionally k, m, g; `TM`: 2 or more characters, first a letter or digit; anything else exits 2 with nothing sent; `bin/pm_checks.sh` holds the rules". CLAUDE.md "Running things": "PM_CPUS must be a whole number (`1.5` is refused)".

Could break, and how checked:
- A caller with a decimal `PM_CPUS` (docker accepted `--cpus 1.5`). The finding accepts this. A search of Makefile, bench, docs, HANDOFF, CLAUDE.md, CI and the scripts found none. Say so in the DECISIONS row.
- A one-character `TM`/gate tag: refused now (it was never a valid docker name; under proot tmux took it). No document uses one. Through the gate, a one-character tag is therefore refused, though `proot_suite.sh` run by hand still takes it.
- Valid docker values unchanged: `test_m23_what_was_valid_is_still_sent` sends the defaults, `2`, `16`, empty, `8g`, `512m`, `28G`, `8gb`, `64MB`, `8192`, `CAFE_MIN_FREE_GB=1`, `PM_THREADS=2` in both runtimes and both scripts; the docker command line itself is unchanged apart from the M-31 defaults.
- `orca_setup.sh` and `orca_sync.sh` need no edit: `orca_sync.sh` quotes `CAFE_MIN_FREE_GB` through `q()`; `orca_setup.sh` and `orca_watch.sh` read it in their own shell on the worker, where it is not pasted (a bad value only fails their own arithmetic).
- `pm.sh` now also refuses the bad values in the environment of a `--pull`.

## M-30: the go check takes the caller's PMX

DECISIONS row: `bin/orca_ready.sh` uses `PMX` from the caller (default `pm_ready`), checks it, `PM_STOP_GRACE` and `CAFE_MIN_FREE_GB` with `bin/pm_checks.sh` before the first ssh (they are pasted into it), and names its start marker `~/cafe-worker/.ready_start_<PMX>`. Its last step fails only for a path outside `~/cafe-worker` that changed during the check AND whose name is ours (`cafe*`, `pm_*`, `pmx_*`, depth 2); any other changed path is printed as a warning with exit 0. | The check exported `PMX=pm_ready` over the caller's, so two checks synced onto one directory with `--delete`, and on the shared account any other person's file at depth 2 newer than the marker (5 paths in the first hour on orca) failed it. The guarantee "nothing of ours landed outside" now holds for names that are ours; a leak under a foreign name would be a warning only. | Amends 458 and 489 (their mentions of `orca_ready.sh`); no row sets the fixed name.

CHANGELOG: `bin/orca_ready.sh` runs under the caller's `PMX` (default `pm_ready`), has a marker per PMX, and fails its last step only for a changed path with a name of ours, else warns; DECISIONS (M-30).

Doc sentences: docs/ORCA_RUNNER.md step 3 and docs/orca/README.md:79: "`PMX=pm_<you> PM_HOST=cafe-orca sh bin/orca_ready.sh` (default `pm_ready`): use your own PMX when another agent may run the check; the last step lists, as a warning, anything else that changed under `~` while it ran (the account is shared)".

Could break, and how checked:
- Someone relying on `pm_ready` always being used while PMX is exported in their shell for other work: the check now runs there. Documented in the sentence above. Old markers `.ready_start` on orca are no longer read (harmless leftover; one exists and can be removed by the lead from `~/cafe-worker`).
- The test runs the real script with the real `ssh` executed in a scratch HOME (fake `bin/pmx.sh` that logs `PMX`). The real `pmx.sh` calls were not run (they would sync onto the existing `pm_ready` on orca).
- `bin/pmx.sh` inside the script is still resolved from the current directory, as before ("from the checkout").

## M-26: the disk note fires again, a rerun failing the same way is noted

DECISIONS row (after 522): `bin/orca_watch.sh` writes its disk note once per dip: it is latched while free space is under `FLOOR + 40` GB and cleared when it reaches `FLOOR + 45` (5 GB of hysteresis, so a value hovering at the line writes no snap a minute onto a nearly full disk). The state of a finished job log (one that ends `rc=N`) also holds the log's modification time in seconds, so a rerun that ends with the same counts as the last look is noted again; a log still running is compared on its counts as before. | `low` was never cleared, and `bin/pmx.sh` rewrites the log of a rerun in place with `>` (same inode, so the finding's inode idea would not have worked), so an identical failing rerun between two looks 60 s apart left no trace. | Amends 522.

CHANGELOG: `bin/orca_watch.sh` notes a second dip of the disk after a recovery and a rerun that fails with the same counts (the state of a finished log carries its mtime); the first look after this change writes one extra note per failing finished log; DECISIONS (M-26).

Doc sentences: docs/ORCA_RUNNER.md near line 28 (the recorder): "one disk note per dip (cleared 5 GB above the line); a rerun of a job under the same name is noted again if it fails".

Could break, and how checked:
- State files written by the old script have no mtime: the first look after an upgrade writes one extra note for each failing finished log (said in the CHANGELOG line). Passing logs write none (the case on the counts is unchanged: `0 0 ` and `0 0 rc=0` never note).
- Anything that touches a finished failing log (an `echo >>`, `touch`) is a new state and notes again; `bin/proot_suite.sh` appends `rc=` before the log is finished, never after. A script that rewrites the logs of a finished gate would add notes; none exists.
- `stat -c %Y` is GNU; the recorder runs only on orca (Linux). The tests run there.
- The existing -vv/xdist counting test passes unchanged.

## M-28: one tag rule for proot_suite.sh and orca_gate.sh

DECISIONS row: a gate tag (and, under `PM_RUNTIME=proot`, a `TM`) must not itself be one of the suite's log names: it may not end in `_s<digits>`, `_serial`, `_shares` or `_audit`. The rule is `pm_tag`/`pm_shape` in `bin/pm_checks.sh`, called by `bin/orca_gate.sh` (before anything is sent), by `bin/proot_suite.sh` (on the worker, from its own directory) and, for `TM`, by `bin/pmx.sh`. The P-30 sweep of `bin/proot_suite.sh` is unchanged. | With logs `a_s2.log`, `a_s3.log` and `a_s3_s1.log` and tag `a` at K=1, the sweep deleted `a_s2.log`, the main log of a tag `a_s2` (named `<tag>.log` by the gate), and its `rc=` line; the same flat folder also meant `a_serial` as a tag shared a log with the serial job of `a`. The sweep cannot tell the two apart, so the names that could be both are refused. | Amends 532 and 517.

CHANGELOG: a gate tag or proot `TM` that ends `_s<digits>`, `_serial`, `_shares` or `_audit` is refused (exit 2): it would share a log with another tag's job; one rule in `bin/pm_checks.sh` for `orca_gate.sh`, `proot_suite.sh` and `pmx.sh`; DECISIONS (M-28).

Doc sentences: docs/ORCA_RUNNER.md near line 20: "a tag may not end in `_s<digits>`, `_serial`, `_shares` or `_audit`: those are the names of its own jobs' logs". CLAUDE.md orca paragraph: the same in one clause.

Could break, and how checked:
- Tags in use: searched DECISIONS, HANDOFF, CLAUDE.md, docs, review/orca and the PROBLEMS table for tags or `TM=` of those shapes: none (`go1`, `proof1`, `q10`, `r4_full` are fine). A tag such as `r9_s2` would now be refused; the finding named it as a thing to check and none is documented.
- Docker `TM` (plain jobs on homebase) is not restricted by the shape rule (their logs are in `~/logs`, no suite writes there).
- Other deleting globs: searched `rm` with globs under `bin/` and `cafe/pm`; only the P-30 loop and `.coverage*`/`serial.xml` removal in the tag's own folder.
- Existing P-30 test (`t1_s3_s5.log`, `t2_s9.log` kept; `t1_s9.log`, `t1_s12.log` removed) passes unchanged.

## M-29: one definition of a test file

DECISIONS row: `[tool.pytest.ini_options] python_files = ["test_*.py"]` in pyproject.toml is the one definition of a test file; `cafe/pm/shares.py` reads it (`shares.PYTHON_FILES`) instead of its own glob, so `pytest tests` and the shares cannot disagree. A test case whose id is in `audit.SERIAL_TESTS` adds no time to its file's weight (they run alone, and the first suite's junit file still holds their old times). | pytest's default also collects `*_test.py`; a failing `tests/foo_test.py` would have run in no share while `audit --pytest-done` (which only checks `coverage.json` is newer than the code) passed. No such file exists now. The serial tests' time made `test_uas.py` and `test_emulator.py` look heavy on the first balance. | Amends 517 (the shares step).

CHANGELOG: `pyproject.toml` sets `python_files = ["test_*.py"]` and `cafe/pm/shares.py` reads it; the weight of a test file leaves out the real-time tests that run alone; DECISIONS (M-29).

Doc sentences: docs/BUILDERS.md or CLAUDE.md where test file names are mentioned: "a test file is `tests/**/test_*.py`; `*_test.py` is not collected (pyproject `python_files`)".

Could break, and how checked:
- Narrowing `python_files` also narrows the xdist audit pass and `make` targets that call pytest: all pass directories, so no change unless a `*_test.py` exists (none: `git ls-files 'tests/**/*_test.py'` is empty). `conftest.py` is collected by its own rule.
- `shares.py` now reads pyproject.toml at import. The `cafe-pm` image and every checkout have it (`audit.py` already reads it). `tests/test_shares.py` builds a tmp tree and runs the real pytest `--collect-only` there with a copy of the pyproject, so it checks the two against each other.
- Coverage of `cafe/pm/shares.py`: all new lines are executed by the new and existing tests (the file was at 100 %).

## M-31: the PMX path defaults to 2 CPUs and 12g, pm.sh keeps the whole box

DECISIONS row: on the `bin/pmx.sh` path the defaults are `PM_CPUS=2` and `PM_MEM=12g` (docker `--cpus` and `--memory`; under proot `PM_CPUS` sets `CAFE_WORKERS`); `PM_SHM` stays 16g. `pm.sh`, the lead's whole-box path, keeps 8 CPUs and 28g. `PM_THREADS`, when set, is passed by `pmx.sh` and `pm.sh` to `bin/proot_run.sh` (proot only; docker ignores it), so a 2-CPU job under proot no longer sizes its BLAS and OpenMP pools to 64 threads. No load check is added. | The incident of the round: `bin/pmx.sh` with nothing set started 8 CPUs and 28g on the shared server. Amends 458 (runner defaults) and 524 (`PM_THREADS` now reaches the job from the laptop's runners, not only from `proot_suite.sh`); P-20.

CHANGELOG: `bin/pmx.sh` defaults to `PM_CPUS=2 PM_MEM=12g` (was 8 and 28g; 12g is the least that plans the demo mission; `pm.sh` unchanged); `PM_THREADS` is passed through `pmx.sh` and `pm.sh` to `proot_run.sh`; DECISIONS (M-31).

Callers swept (what relied on the old default of `bin/pmx.sh`):
- `bin/orca_ready.sh`: sets `PM_CPUS=2` itself (unchanged). `bin/orca_gate.sh` -> `proot_suite.sh`: the suite exports `PM_CPUS=2 PM_THREADS=2` itself, so the pmx default is not used. `bin/orca_suite.sh`: its documented command sets `PM_CPUS=30`. `bin/proot_run.sh` called by hand keeps its own default of 8 (every runner passes the number explicitly, the worker is the only place it is read); the lead may want 2 there too, not changed (not asked).
- Makefile, bench/, CI (`.github/workflows/premission.yml` runs `docker run` directly): no use of `pmx.sh` or the defaults.
- Docs that rely on the old default, for the lead to change: `CLAUDE.md` line 34 (the quick demo run through `bin/pmx.sh` names no `PM_CPUS`/`PM_MEM`: it now gets 2 CPUs and 12g, which plans (see the follow-up below); say `PM_CPUS=6 PM_MEM=24g` for the 6-CPU time); `docs/RUNBOOK.md` line 44 ("on homebase `PM_CPUS` and `PM_MEM`, default 8 and 28g") is about `pm.sh` and stays true, but add "bin/pmx.sh: 2 and 12g"; `docs/BUILDERS.md` and `HANDOFF.md` lines 90, 196, 208, 224 name their numbers already.
- Headers: `bin/pmx.sh` and `pm.sh` now state their defaults.

Could break, and how checked:
- A lab user's quick demo run (`PMX=... bin/pmx.sh python -m cafe.pm run ...` with no numbers): fewer workers and a 12g cap under docker; `plan` reads the cgroup memory limit. Not run under docker (cannot run on orca; homebase is off limits), see the follow-up below for what was checked instead. This is the one behaviour change a user can see.
- Explicit numbers are sent unchanged: `test_m31_the_docker_defaults...` asserts `--cpus 6 --memory 24g --shm-size 4g` for `PM_CPUS=6 PM_MEM=24g PM_SHM=4g`, and the defaults `--cpus 2 --memory 12g --shm-size 16g` (pmx) and `--cpus 8 --memory 28g --shm-size 16g` (pm.sh).
- Docker command otherwise byte-identical (the existing test that compares it with and without `PM_ENTRY` still passes).

## Follow-up after the adversary (same branch, second commit)

M-31 (the 8g default made the documented quick demo refuse to start): confirmed from the code, not from a docker run. With `--memory 8g` `par.memory_gb()` reads 8.59 GB, `budget.plan` needs `env_model_gb` (about 9 GB for the demo's 6-day window) plus `WORKER_GB` (0.9) and raises `PlanError` "9 GB is available". Root cause: the default memory of `bin/pmx.sh` was chosen without reading the planner's floor. Fix, in the one place: `bin/pmx.sh` defaults to `PM_MEM=12g` (header and the `pm.sh` comment say so; `PM_CPUS=2` unchanged). 12g leaves 12.88 GB to the plan, 3.9 GB over the environment: 4 workers by memory, 2 asked for. `HANDOFF.md` line 196 documents this demo at 16g with 4 workers (12.6 GB by the model); 12g with 2 workers is 10.8 GB by the same model. The peak under docker at 12g is still not measured.
- Test (`tests/test_runners.py`): `test_m31_every_documented_demo_run_through_pmx_sh_gets_the_memory_the_plan_needs` reads every command in `CLAUDE.md`, `HANDOFF.md` and `docs/*.md` that runs `missions/tepex_c_demo.yaml` through `bin/pmx.sh`, takes its `PM_MEM` (else the default `bin/pmx.sh` actually sends) and calls `budget.plan` with that container memory; it also asserts that the `CLAUDE.md` command with no `PM_MEM` is among them, so it cannot pass by finding nothing. A new document line that names too little memory fails it. `test_m31_the_memory_check_sees_a_default_below_the_floor` shows 8g is refused and 12g planned. The existing default-values test now expects 12g.
- Fail first: a detached worktree at 00b2e02 with the new test file failed the documented-commands test (`CLAUDE.md:34: --memory 8g is below what the plan needs ... 9 GB is available`) and the defaults test; the worktree and its orca directory and log were removed. After the fix: `tests/test_runners.py tests/test_config_docs.py tests/test_proot_suite.py tests/test_shares.py` rc=0 as whole files, `ruff check cafe/pm tests` clean, `mypy cafe/pm` strict no issues in 55 files.
- Docs for F (not edited here): `CLAUDE.md` line 34 is now true as written; line 25's example `PM_MEM=8g` is fine for tests but would make the demo refuse, so say 12g there or drop it; `docs/RUNBOOK.md` line 44 add "bin/pmx.sh: 2 CPUs and 12g". DECISIONS row of M-31: 12g, not 8g.

The other items the builder left:
- Docs not edited (CLAUDE.md line 34, RUNBOOK line 44): handed to F by the batch text, not a defect; the command in line 34 is now correct (above).
- Docker path not run: still true and not possible (no docker on orca, homebase off limits). What replaces it is the planner arithmetic above and the logged command line.
- The real `bin/pmx.sh` calls in `bin/orca_ready.sh`: run for real on orca with `PM_HOST=cafe-orca PMX=pm_r10e sh bin/orca_ready.sh` (own directory and marker, 2 CPUs); it ran to `orca-ready` (exit 0): the marker `.ready_start_pm_r10e` was written, the real `pmx.sh` calls ran under `pm_r10e` (workers 2), the `tests/test_par.py` and interFoam test passed, and the last step reported no changed path and no warning. The marker and directory were removed.
- Behaviour changes (decimal `PM_CPUS`, one-character tag, `r9_s2`-like tags refused): stated decisions of the finding, not problems.
- `bin/proot_run.sh` default `PM_CPUS=8` for a run by hand: left to the lead, as the handback said; every runner passes the number, so nothing in the repo reaches it.
- `audit --code-only` "docs/mutation.json absent": investigated, not a defect. The file is not in git (`git ls-files docs/mutation.json` is empty); `audit.py` says a clean checkout has none until `make mutation` writes it; `bin/sync_filters` protects it on the server (`P /docs/mutation.json`).
- Old marker `~/cafe-worker/.ready_start` on orca: not removed by this batch (the lead's call; it is unused).

## Needs from other batches

- Batch F (documents, by the lead): the doc sentences above, and the row numbers. Also F's acceptance guard (M-12) is untouched by this batch.
- No code from another batch is needed. Batch A or others that add a new environment variable pasted into a runner command line should add it to `pm_job` in `bin/pm_checks.sh`, not to the scripts.
- The lead decides: `bin/proot_run.sh`'s own default of `PM_CPUS=8` for a run by hand (kept); whether `TM` single-character gate tags matter (refused now through the gate).
- Left behind on orca by this batch: nothing (the `pm_r10e*` directories and the `r10e_*` logs are removed at the end). One older marker `~/cafe-worker/.ready_start` (from an earlier go check) is now unused and can be removed by the lead.
