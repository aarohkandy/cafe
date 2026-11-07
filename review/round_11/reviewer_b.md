# Round 11, reviewer B

Reviewed `095c094` (code as `778d8b6`; the two differ in documents only), branch `premission-step4`. Followed `docs/RUNBOOK.md` and `docs/ORCA_RUNNER.md` as a lab user on orca (proot, `PMX=pm_rev11_b`, `PM_CPUS=2`, `PM_THREADS=2` after the first job), from a detached worktree `../cafe-rev11-b`.

What was run, on orca at 2 CPUs:
- Step 2: `make ci` (rc 0, 6.5 min, ends `audit: 0 problem(s)`).
- Step 3: `validate` of the demo (prints `valid (4 vehicles, 4 links)`), `plan` for quick, 4h, overnight, `--gpus 1`, `--gpus -1`, `--gpu-mem-gb nan/0`, `run --gpus 1` (refuses as written), `hangar` for ten names, and 135 hostile mission files through `validate` (84 + 32 + 19: bad seeds, windows, ids, links, boxes, sorties, bare YAML times and ids, BOM, CRLF, tabs, NUL, latin-1, empty, anchors). No traceback; every refusal names the field. The `fetch` of the demo with `CAFE_OFFLINE` set runs the ingest in 39 s on the warm cache.
- Step 5: a copy of `q11` as `runs/quick`: `audit --ledgers-only` 0 problems; `report --run` re-render equals q11's `report.json` in 11,735 of 11,737 leaves (the run name and the sha-256 that holds it); `whatif` in 14 argument forms; `bin/run_premission ... --out runs/quick` resumed at 2 CPUs with a private `--emulator-table` (emulator 393 s and report rerun, every other stage "up to date", verdicts and p_fail equal to q11's, the flip tables and emulator rows differ as the RUNBOOK says); the same command again (every stage up to date); `audit` 0 problems on both.
- Step 7: `make broken` (rc 0, 10 receipts caught, 20 min), `make receipts` (rc 2, 287 pass, 30 fail, 33 context, 350 rows, 17 min), `ruff check` (clean), `mypy` (clean, 55 files), `audit --code-only` (only the missing `docs/mutation.json`), `audit` option handling. The pytest part of `make audit` was not run (it is the suite).
- The stop recipe of ORCA_RUNNER (`tmux kill-session` on a job: log ends `rc=143`, its `run.*` directory is gone), a repeated `TM` (`duplicate session`, log untouched), the name and number refusals of `bin/pmx.sh`, `bin/orca_gate.sh` and `bin/pm_checks.sh` (24 forms, all refuse with nothing sent), `python -m cafe.pm.shares`.
- Read, not run: `bin/orca_ready.sh`, `bin/orca_sync.sh`, `bin/worker_setup.sh` (they write outside a `scratch_rev11_b` directory), `bin/orca_setup.sh`, `bin/proot_run.sh`, `bin/proot_suite.sh`, `bin/orca_watch.sh`, `pm.sh`, `bin/sync_filters`, RUNBOOK steps 1, 4 and 6.
- Printed numbers recomputed: the Wilson 90 % interval of glider_eq (0.199 to 0.381 from 18/64), its 95 % stop interval (0.1859 to 0.4013), `n_certify` 73, the demo's environment memory (476 deg^2 x 6 d x 0.0031 = 8.9 GB), the pad (0.5 m/s reaches 10 deg at 25.7 d). All agree.

Two things I did that touched shared state, so they are on record: (1) `sh bin/orca_sync.sh 'x;id' root`, typed to see whether the first argument is checked, opened one ssh login to homebase (it ran the script's check and stopped; nothing written there; see B-7). (2) the `fetch` above rebuilt nothing (`audit /data/runs/q11 --ledgers-only` still 0 problems afterwards) and wrote to no run directory of anyone's. No Azure resource touched. At cleanup I ran `rm -rf ~/cafe-worker/cafe/pmdata/shards/rev11*` (a glob wider than my own names; I had made no shards directory, and the folder listed afterwards holds `ab go1 proof1 sig`, so I believe it matched nothing, but I did not list it before). Removed at the end: `~/cafe-worker/cafe/pm_rev11_b`, my `rev11b_*.log` files, the worktree.

Not found wrong: the stop and sweep behaviour, the name and number checks, `validate`'s messages and exit codes, the resume path, the re-render, the troubleshooting-table strings (every quoted message exists in the code), the RUNBOOK's pad and memory arithmetic.

### B-1. The RUNBOOK's `pm()` wrapper and `bin/pmx.sh` drop `CAFE_OFFLINE`, `CAFE_WORKERS`, `CAFE_NPROC` and `CAFE_EMULATOR_TABLE`, which the RUNBOOK tells the user to set
severity: minor
lane: documentation
where: docs/RUNBOOK.md:17 (CAFE_OFFLINE), :34-39 (`pm()`, no `-e` for any of them), :41, :154, :176; bin/pmx.sh:27-30; bin/proot_run.sh:41-44 (`env -i`)
reproduction: on orca, `CAFE_OFFLINE=1 CAFE_WORKERS=1 CAFE_EMULATOR_TABLE=/x bin/pmx.sh python rev11b_env.py` (a script printing `os.environ.get` of the four) prints `[None, '2', None, None]` (the 2 is `PM_CPUS`); `bin/pmx.sh env CAFE_OFFLINE=1 python rev11b_env.py` prints `['1', '2', None, None]`. `docker run` in `pm()` does not inherit the host's environment either, and the RUNBOOK says nowhere to write `pm env CAFE_OFFLINE=1 ...` or to add `-e`.
why it matters: "`CAFE_OFFLINE=1` makes that a rule: nothing is downloaded" cannot be switched on by the documented route, so a run that is meant to be offline downloads what it lacks, and the troubleshooting row for the offline refusal can never be reached; `CAFE_WORKERS=N overrides` is overridden by `PM_CPUS` on this path.

### B-2. RUNBOOK step 7's list of receipts that fail by design leaves out the 20 `pm.dtmb5415` FAIL rows, and the step gives no time for `make receipts` or `make broken`
severity: minor
lane: documentation
where: docs/RUNBOOK.md:219-220 ("A failing row whose id is not on that list ... means a broken install or stale code"), :203-208 (no times)
reproduction: `make receipts` on orca at the reviewed commit: `287 pass, 30 fail, 33 context (350 rows)`, rc 2. The 30 FAIL are: `app.fea`, `pm.physics.uas.slow`, `pm.emulator` (the three `:not_run`), 7 sphere/plate rows (`pm.stage3.lbm` 3, `.nest` 3, `.wallmodel` 1, "NOT STORED"), and **20 of `pm.dtmb5415`** (the four `U_val / D <= 0.1` rows at 0.47, 0.27, 0.63, 0.30 and 16 iterative-convergence rows, e.g. fine Fr 0.41 drift 0.0485 against 0.005). The list the RUNBOOK gives as the only failures that are "not a broken install" is the lbm, nest and wallmodel rows; the DTMB rows (STATUS.md: the study does not validate) are on no list. Timings on orca at 2 CPUs: `make broken` 20 min (the fast receipts twice), `make receipts` 17 min; the step names neither, though it times `--slow` to the minute.
why it matters: a lab user who follows the step word for word reads 20 failing rows as a broken install or stale code and goes looking for it.

### B-3. A run directory's `mission.yaml` (and `plan.json`) is not in any ledger: edit it and `audit` says 0 problems while `report --run` prints cut-offs that contradict the stored verdicts
severity: minor
lane: honesty
where: cafe/pm/audit.py:152-188 (`_stage_problems` hashes inputs and outputs; `mission.yaml` and `plan.json` are neither), cafe/pm/report.py:261-293 (the thresholds are read from `intervals`, which `config.load_mission` set from the file), cafe/pm/__main__.py:200-215
reproduction: `cp -r` q11 to `runs/qb`; change `verdict: {go: 0.9, nogo: 0.6}` to `{go: 0.2, nogo: 0.1}` in `runs/qb/mission.yaml`. `python -m cafe.pm audit --ledgers-only runs/qb` prints `audit: 0 problem(s)`; `python -m cafe.pm report --run runs/qb` exits 0 with no warning, `ledger_problems` and `traceability_problems` both `[]`, and `report.json` has glider_eq `verdict MARGINAL`, `p_fail 0.28125` beside `thresholds {go: 0.8, go_bound: 0.8, nogo: 0.9}` (P(fail) up to 0.8 is GO by those cut-offs). The same edit of `plan.json` (one appended space) and of `mission.yaml` (`# x`) also audits clean. (The re-render also picked up the `runs/receipts.json` my `make receipts` had made, so most other differing leaves are receipt rows; the thresholds are the ones that follow the edit.)
why it matters: the file that defines the cut-offs and the vehicle list is the one file of a run that the audit's "the run's evidence is intact" does not cover, and `whatif` trusts it as the identity of the run (RUNBOOK step 5); round 10's B-5 closed the hand-edited summary and left this sibling.

### B-4. `whatif` with no finished run answers with default priors and no refit and does not say so; its baseline is another model than the report's
severity: minor
lane: statistics
where: cafe/pm/__main__.py:295-307 (`fitted`, `scales` stay `None` when `stage1b/summary.json` is absent; the note says only "run in Stage 1 at the quick budget"), docs/RUNBOOK.md:170-171
reproduction: on orca, `python -m cafe.pm whatif --mission missions/tepex_c_demo.yaml --run /tmp/emptyrun --shift 6h` (the directory has no run) prints `glider_eq ... P(fail) 0.312`, `usv ... 0.781`, `uas ... 0.625` as the baselines. The same mission's report (q11) has 0.281, 0.969 and 0.859 for the same three (n = 64, TAO-fitted priors, refit multipliers). With `--run runs/quick` the same `--shift 6h --vehicle uas` gives `0.859 -> 0.969`; without it `0.625 -> 0.625`. Verdict labels agree (MARGINAL, NO-GO, NO-GO).
why it matters: a user who reads the what-if baseline beside the report's P(fail) sees differences of 0.19 and 0.23 that the note gives no reason for (the unfitted `perturbations.yaml` priors); the repo's rule is that a number states what it is.

### B-5. `docs/orca/README.md`, the page ORCA_RUNNER step 1 sends the owner to, still says orca is not connected and nothing has run there; and RUNBOOK step 0's TAO size is the pre-round-10 one
severity: minor
lane: documentation
where: docs/orca/README.md:5 ("Status, 2026-11-04: not connected, and cafe jobs do not run there yet. Keep using the burst VM until the steps below pass"), :7-15 (the state table: `bin/orca_setup.sh` "never run on Orca", Tailscale "Not tested", the real image "Not tested", `interFoam` in parallel "Not tested; the biggest risk"), :80-86 ("What is left before jobs can run", including asking about deleting `burst-cafetest-rg`); docs/RUNBOOK.md:13 ("TAO 0.13 GB")
reproduction: ORCA_RUNNER.md "Go" step 1 names this file ("`docs/orca/README.md`, 'Connect'"); the same repo has `proof1` gate runs on orca (3,352 tests, ORCA_RUNNER "Measured"), q9/q10/q11 demo runs there, and PROBLEMS.md P-1 to P-41. `du` on orca: `pmdata/tao` is 296 MB (the older cache plus `tao/s2`), not 0.13 GB.
why it matters: the first document a new owner opens contradicts the runner document on whether the worker works.

### B-6. `audit.coverage_stale` trusts file times, and `--pytest-done` does not know whether the tests passed
severity: minor
lane: reproducibility
where: cafe/pm/audit.py:375-383 (`coverage_stale`), :395-433 (`--pytest-done` path), bin/sync_filters (`/coverage.json` is kept across syncs)
reproduction: a scratch tree with `cafe/pm/physics.py` and a `coverage.json`; set the source's mtime to an hour before the coverage file's, then change its content and set the mtime back (what `rsync -a` of a file edited on the laptop during the 55 min gate does): `audit.coverage_stale(root)` returns `[]` both times (run on orca; `rev11b_cov.py`). `python -m cafe.pm.audit --pytest-done` then reports no problem for code the suite never ran, and for a suite that failed, if a `coverage.json` of the right shape exists.
why it matters: "the tests ran on this code" is established by a clock, not by the tree; the gate script itself avoids it (it deletes the old file first and reads the junit files), the manual route the RUNBOOK documents does not.

### B-7. `bin/orca_sync.sh` reaches homebase before it checks its first argument, and a plain re-run never brings a later `tao/s2` to orca
severity: minor
lane: robustness
where: bin/orca_sync.sh:10-17 (`IP` unchecked, `DST` built from it, script sent to homebase), :38 (`todo` copies a part only when its `.done` marker is missing), docs/ORCA_RUNNER.md TAO bullet ("`bin/orca_sync.sh` and `bin/worker_setup.sh` copy the whole `tao` directory, so `s2` goes along")
reproduction: `sh bin/orca_sync.sh 'x;id' root` prints `hostname contains invalid characters` and `STOP: cafe-worker is not set up on orca`: the first line is from an ssh run on homebase. The parts are checked before ssh, the IP is not, though every other value pasted into a command line has a rule since round 9 (`bin/pm_checks.sh`). Reading `todo`/`want`: with no part named and `pmdata.done` present nothing is copied, so a TAO cache fetched on homebase after the first sync does not travel; naming `pmdata` deletes the marker and copies all six directories again (about 13 GB with the 5 GB ocean store) to get 0.3 GB.
why it matters: a typo in the address (or a trailing space copied from a terminal) is sent to the shared server first and fails in an ssh message that does not name the argument; the TAO sentence reads as if a re-run refreshed it.

### B-8. `orca_ready.sh` and `worker_setup.sh` claim more than they check
severity: minor
lane: robustness
where: bin/orca_ready.sh:3-4,28-33 and docs/ORCA_RUNNER.md Go step 3 ("nothing of ours changed outside `~/cafe-worker`"); bin/orca_ready.sh:16 (`ps -eo user:12,pcpu,comm`); bin/worker_setup.sh:3-5,16
reproduction: by reading (not run: they write outside a scratch directory). (a) The last step is `find . -maxdepth 2 -path ./cafe-worker -prune -o -newer ...` from `$HOME`: a write three levels down (`~/.cache/x/y/z`) leaves no entry above depth 2 with a newer time and passes; nothing outside `$HOME` (such as a host `/tmp`) is looked at. (b) It prints each of the top processes with the account name in the first column, on a shared machine where the rule is process names only. (c) `worker_setup.sh` says "It needs 25 GB free" and never runs `df`; `orca_sync.sh` has the check. (d) On a worker where `docker ps` fails, it runs `usermod -aG docker` and goes on to `docker load` in the same session, where the new group does not apply, so the first run would stop at `docker load` (by reading; the header's "Re-running is safe" is the only hint).
why it matters: the "nothing changed outside" line of the go check is a narrower statement than its wording.

### B-9. The Makefile lists `run` and `clean-runs` as phony targets and defines neither
severity: minor
lane: documentation
where: Makefile:10 (`.PHONY: ... run ... clean-runs`), no rule for either
reproduction: `printf '.PHONY: run clean-runs\n' > mk && make -f mk run` prints `make: Nothing to be done for 'run'.` and exits 0 (same for `clean-runs`); in the real Makefile `make run` and `make clean-runs` do the same.
why it matters: a user who types `make run` (the obvious name) sees success and no run; `make clean-runs` appears to clean.

### B-10. RUNBOOK step 6 tells the user `--out runs/4h`, then reads the calibration from `runs/<mission>/<budget>`
severity: minor
lane: documentation
where: docs/RUNBOOK.md:195-196 (`pm bin/run_premission ... --budget 4h --gpus 1 --out runs/4h`) against :201-202 (`runs/<mission>/<budget>/stage3/subgrid_calibration.json`, `promote-calibration --run runs/<mission>/<budget>`); bin/run_premission:2 (names `quick|4h|overnight`, not `ci`)
reproduction: by reading, step 6 (no GPU); the default `--out` is `runs/<mission>/<budget>`, which the step's own command does not use, so the path in the next paragraph does not exist after it.
why it matters: the one step a GPU user must take to keep the calibration names a directory the previous command did not make.

### B-11. `validate` accepts a link field its kind never reads
severity: minor
lane: robustness
where: cafe/pm/config.py (link checks), cafe/schemas/mission.json
reproduction: the demo with `radio: rfd900x` added to `usv-shore-iridium` (kind iridium) and, in another file, `modem: benthos_atm960_mf` added to `usv-uas-rf` (kind rf): both print `valid (4 vehicles, 4 links)`, exit 0. A missing `radio` on an rf link, and a `modem` on an acoustic link to a UAS, are refused with a clear message.
why it matters: RUNBOOK step 3 says a key that is not in the schema is refused; an extra radio on an Iridium link is silently ignored, and the author may believe it decides the link.

total: 11 findings (0 critical, 0 major, 11 minor)
