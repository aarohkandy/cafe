# Round 11, batch D (M-18, M-19, M-32, M-33): hand-back for the docs step

Branch `r11-d` (from 3ce8e09). Code: `bin/pm_checks.sh`, `bin/orca_sync.sh`, `bin/worker_setup.sh`, `bin/orca_ready.sh`, `bin/run_premission`, `Makefile`. Tests: `tests/test_runners.py` (25 new cases), `tests/test_config_docs.py` (1). No document was edited. M-29 is not in this batch's brief and was not touched (nothing in `pmx.sh` or `proot_run.sh` changed).

DECISIONS numbers below assume the next free row is 593; renumber if another batch took it.

## M-18. The address is checked before anything is sent

What changed:
- `bin/pm_checks.sh`: `pm_host NAME VALUE` (an IPv4 or IPv6 address or a DNS name: letters, digits, `.`, `-` and `:` only; not empty; not starting with `-`) and `pm_user NAME VALUE` (a login: letters, digits, `.`, `_`, `-`; not empty; not starting with `-`). Both exit 2 through `pm_bad`.
- `bin/orca_sync.sh` sources `pm_checks.sh` and calls `pm_host` on the IP right after the usage line, before the part-name loop and before the first ssh. `ORCA_DST` rehearsals are unchanged (the test IP is still `100.1.2.3`).
- Sibling swept: `bin/worker_setup.sh` pastes its first argument (`user@host`) unquoted into the script that homebase runs, the same class. It now checks the user part with `pm_user` and the host part with `pm_host`, and `$1` is required (usage line). A name without `@` is still accepted (an ssh config name).
- Looked at and left alone: `PM_HOST` (pmx.sh, pm.sh, orca_ready.sh, orca_gate.sh), `ORCA_VIA` and `PM_HOME_HOST` are the caller's own ssh destination, passed as one local ssh argument and never pasted into a remote shell. A leading `-` there would be read by the local ssh as an option, which is the caller's own environment and not this defect. `bin/orca_setup.sh` takes no address (it prints the IP). If the owner wants `PM_HOST` checked too, it needs a rule that passes `cafe-orca`-style config names and `user@host`; not done unasked.

### DECISIONS row
| 593 | `bin/pm_checks.sh` also decides what a machine's address may be: `pm_host` (letters, digits, `.`, `-`, `:`; not empty; not starting with `-`, so an IPv4 or IPv6 address or a DNS name passes) and `pm_user` (a login name). `bin/orca_sync.sh` checks its IP argument with `pm_host` and `bin/worker_setup.sh` its `user@host` with `pm_user` and `pm_host`, each exiting 2 before the first ssh: the address is pasted unquoted into a command line on homebase, where `x;id` ran `id` and `1.2.3.4 id` made `id` the remote command on orca. A re-run of `orca_sync.sh` with no part named copies nothing once `pmdata.done` exists, so a `tao/s2` fetched on homebase after the first copy reaches orca only by naming `pmdata` (all six directories again, about 13 GB) or by copying `tao` by hand. | Review round 11, M-18 (B-7). The address was checked only after the homebase ssh had run with it; part names had been checked before (496) and the PM_* variables since 557, but the address was the one caller-typed value pasted into a command line without a check. The `tao/s2` behaviour is the as-built consequence of 489 and 571 (one marker per part, set by the first whole copy), recorded here so ORCA_RUNNER's "the sync copies the whole tao directory" is not read as "every run brings new tao files". | `tests/test_runners.py::test_r11_m18_*` (8 bad orca addresses, 4 good ones, 9 bad workers) |

Amends: 557 (add "(extended by 593 to addresses)"); 571 (add "(the copy happens with the first whole copy of `pmdata`; see 593)"); 496 (part names were checked before; the address is now too).

### CHANGELOG line (Fixed)
- `bin/orca_sync.sh` and `bin/worker_setup.sh` refuse an address that is not an IP address or host name (`x;id`, `1.2.3.4 id`, a trailing space, a leading `-`) with exit 2 before anything is sent; `bin/pm_checks.sh` gains `pm_host` and `pm_user`.

### Doc sentences needed
- `docs/ORCA_RUNNER.md` line 44 (TAO bullet), after "`bin/orca_sync.sh` and `bin/worker_setup.sh` copy the whole `tao` directory, so `s2` goes along from a machine that has fetched it (DECISIONS 571).": "This happens on the first copy of `pmdata`. A run of `orca_sync.sh` with no part named copies nothing once `pmdata.done` exists, so an `s2` fetched on homebase later reaches orca by naming `pmdata` (it copies all six directories again, about 13 GB, to move a few hundred MB) or by copying `tao` by hand."
- `docs/ORCA_RUNNER.md` Go step 2 (line 9 of the file as read), after "Run it again to resume a cut copy.": "With no part named it copies only what is missing; it does not refresh a part that is marked done."
- Same step: "The address must be an IP address or a host name (letters, digits, `.`, `-`, `:`); anything else exits 2 before anything is sent."
- `tests/test_config_docs.py` does not read ORCA_RUNNER.md for these phrases (checked by grep), so no test breaks if they change.

### What I checked could break, and how
- Callers of `pm_checks.sh`: `pm.sh`, `bin/pmx.sh`, `bin/orca_ready.sh`, `bin/orca_gate.sh`, `bin/proot_suite.sh` source it; I only added two functions after `pm_bad`, so their behaviour is unchanged. The existing `test_m23_*`, `test_m30_*` and `test_m28_*` ran in the whole-file run below.
- `orca_sync.sh` now needs `pm_checks.sh` beside it. It is in the same `bin/`, and `sh bin/orca_sync.sh` and `sh /abs/path/bin/orca_sync.sh` both resolve `$(dirname "$0")` (the tests use the absolute form). A copy of the script moved alone elsewhere would fail to source it (the same has held for `orca_ready.sh` since 557). Same for `worker_setup.sh`.
- A host name with `_` or an IPv6 zone id (`fe80::1%eth0`) is refused. Neither is used here (tailnet IPs and `*.ts.net`); stated so the owner can widen the rule.
- The user part of `worker_setup.sh`'s argument uses `pm_user`, not `pm_word`, so a one-character login is not refused.

## M-19. orca_ready.sh and worker_setup.sh say what they check

What changed:
- (a) `bin/orca_ready.sh` header: the last check looks to depth 2 of `$HOME`; a file rewritten deeper, a new entry four levels down and anything outside `$HOME` are not seen. The `find` is unchanged (the finding says not to deepen it).
- (b) `ps -eo user:12,pcpu,comm --sort=-pcpu | head -6` became `ps -eo pcpu,comm --sort=-pcpu | head -6`.
- (c) `bin/worker_setup.sh` runs `df -Pk .` on the worker before anything is installed or copied and stops (exit 1, "only N GB free on <worker>, 25 GB needed") under 25 GB. The 25 GB is fixed in the script, as the header says.
- (d) after `usermod -aG docker`, the script prints "STOP: docker did not answer for the login on <worker>, which is now in the docker group: ... Log out of it and run this again; if it stops here again, run docker ps on <worker> to see why" and exits 1, instead of going on to `docker load`. If `usermod` itself fails the script exits 1 without that message (ssh and sudo print their own error). A first run on a machine where the login is not in the docker group now exits non-zero on purpose; the second run goes on.

### DECISIONS row
| 594 | `bin/orca_ready.sh` says what its last check covers: new or removed entries and changed directories at depth 2 of `$HOME`; a rewrite deeper down, a new entry four levels down and anything outside `$HOME` are not seen, and the `find` is not deepened (slower on a large shared home, and other people's paths would become warnings). Its busy-process list is `ps -eo pcpu,comm`, process names only. `bin/worker_setup.sh` checks the 25 GB it says it needs (`df -Pk .` on the worker) before it installs or copies anything, and after adding the login to the `docker` group it stops with exit 1 and "log out and run again", because the session that did it does not have the group and the next `docker load` would fail. | Review round 11, M-19 (B-8), partly confirmed: (a) holds in part, since `-newer` at depth 2 also sees a new entry one level deeper through the parent directory's mtime, so the wording says what is and is not seen instead of changing the scan; (b) the account column was the only thing that broke the "process names only" rule; (c) the header promised a check that did not exist; (d) a fresh ssh session may lack the group, and `docker load` then failed under `set -eu` on the first run only. `worker_setup.sh` served the burst VM (deleted 2026-11-06) and is near-dead, so the change is small. | `tests/test_runners.py::test_r11_m19_*` |

Amends: 564 (its "depth 2" is now stated in the header and the doc; add "(wording in 594)"); 458 (the process-names-only rule now holds for the busy list).

### CHANGELOG line (Fixed)
- `bin/orca_ready.sh` lists busy processes by name only (no account column) and says its last check covers depth 2 of `$HOME`; `bin/worker_setup.sh` checks the 25 GB it needs before installing or copying and stops, asking for a new login, after adding the login to the `docker` group.

### Doc sentences needed
- `docs/ORCA_RUNNER.md:13` (Go step 3), replace "and nothing of ours changed outside `~/cafe-worker`" with: "and nothing of ours changed outside `~/cafe-worker`, looked at to depth 2 of `$HOME` (a new or removed entry or a changed directory there; a file rewritten deeper down, a new entry four levels down and anything outside `$HOME` are not seen)".
- Wherever `bin/worker_setup.sh` is described (grep found it in `HANDOFF.md`, `docs/ORCA_RUNNER.md` and DECISIONS only): "It checks for 25 GB free first. On a machine where the login is not yet in the docker group the first run adds it and stops with exit 1; log out of that login and run it again."

### What I checked could break, and how
- `ps -eo pcpu,comm` is valid procps syntax; the test pins the arguments with a ps stand-in. The real scripts were not run on orca (`orca_ready.sh` writes into the shared account; the rules for this batch forbid it). Anything that parses the old three-column output: grep for `user:12` found only this line; no reader of the printed list exists in `bin/`, `tests/` or docs.
- `worker_setup.sh`: the awk-free `df -Pk . | tail -1 | tr -s " " | cut -d" " -f4` avoids a third layer of `$` escaping (laptop heredoc, homebase shell, worker shell). If the ssh for `df` fails the script exits (set -e in the assignment) with ssh's own error. The test pins the 25 GB boundary (24 GB stops with nothing installed or copied, 25 GB reaches the rsync) and that the usermod branch stops before rsync and `docker load`.
- Not changed, noted for later: `df` free-space code is duplicated in `orca_ready.sh` and `orca_sync.sh` (R7 sibling), and the unquoted `$D '...'` expansion in `orca_sync.sh` is shared by every line; with the address checked the IP can no longer split it. `ORCA_DST` is the caller's own rehearsal setting.

## M-32. `run` and `clean-runs` are no longer phony

What changed: both names deleted from `.PHONY` (Makefile line 10); `make run` and `make clean-runs` now fail with "No rule" (exit 2) instead of printing "Nothing to be done". No target was added: `clean-runs` would be destructive and `run` would duplicate `quick`. Callers: grep over docs, DECISIONS, CHANGELOG, tests, `bin`, `.github` and `Makefile` found no use of either name.

### DECISIONS row
| 595 | The Makefile's `.PHONY` list names only targets that have a rule; `run` and `clean-runs`, listed since the first commit and never defined, are removed (they made `make clean-runs` look like a clean that did nothing). No target is added in their place. A test requires a `^name:` rule line for every `.PHONY` name. | Review round 11, M-32 (B-9). Deleting is safer than defining: `clean-runs` would be `rm -rf $(RUNS)` on the user's reviewed runs, and the acceptance runs were already made not to touch them (328, 535). | `tests/test_config_docs.py::test_r11_m32_every_phony_make_target_has_a_rule` |

Amends: none (97, 233, 328 describe other targets).

### CHANGELOG line (Fixed)
- `make run` and `make clean-runs` no longer succeed without doing anything: they were listed as phony targets and defined nowhere, and are removed from `.PHONY`.

### Doc sentences needed
- None.

### What I checked could break, and how
- The test fails before (the two names have no rule line) and passes after. `ci` has the rule `ci:` besides target-specific `ci: MISSION := ...` lines, so `^ci:` matches either way. `4h` is not phony and not a target (the `make audit` wildcard reads `$(RUNS)/4h`).

## M-33. One path for the 4 h run: the code is right, the RUNBOOK paragraph is wrong

Choice: the RUNBOOK step 6 command writes to `runs/4h` (`--out runs/4h`), the convention of every other command and of the code that looks for runs by name: the Makefile (`--out $(RUNS)/quick`, `$(RUNS)/overnight`; `make audit` reads `$(RUNS)/quick $(RUNS)/overnight $(RUNS)/4h`), `audit.py:393` ("the run directories are runs/quick, runs/overnight, runs/4h"), README and STATUS. The default `runs/<mission name>/<budget>` of `--out` (`__main__.py:56`) applies only when `--out` is left out. Changing the default would move the `report --run` and `whatif --run` defaults too, so the code default is not changed. The paragraph after the command is the part to change.

What changed in code: only the usage line of `bin/run_premission` (adds `ci`, the fourth budget `BUDGET_S` accepts, and states the default `--out`). Test: the budgets named in the usage line equal `list(budget.BUDGET_S)`.

### DECISIONS row
| 596 | The run directories are named by budget under `runs/` (`runs/quick`, `runs/overnight`, `runs/4h`) wherever a command is given an `--out`: the Makefile, `make audit`, the audit's error line and the RUNBOOK use that form. `--out` left out defaults to `runs/<mission name>/<budget>` (`cafe.pm run`, and the `--run` default of `whatif`); the default is unchanged. The usage line of `bin/run_premission` lists every budget the command accepts, `ci` too, and states the default `--out`. | Review round 11, M-33 (B-10). RUNBOOK step 6 gave `--out runs/4h` and then sent the user to `runs/<mission>/<budget>/stage3/subgrid_calibration.json` and `promote-calibration --run runs/<mission>/<budget>`: the two directories differ, and the second is where nothing was written. | `tests/test_runners.py::test_r11_m33_run_premissions_usage_line_names_every_budget_the_command_accepts` |

Amends: none.

### CHANGELOG line (Fixed)
- The usage line of `bin/run_premission` lists the `ci` budget and the default `--out`.

### Doc sentences needed (RUNBOOK step 6, docs/RUNBOOK.md lines 199-200; check the line numbers against the file as edited by M-34)
- Line 199: replace "`runs/<mission>/<budget>/stage3/subgrid_calibration.json`" with "`runs/4h/stage3/subgrid_calibration.json`" (the directory the step's command gave to `--out`). M-34 says this step promises a file nothing can write, so the sentence may be rewritten there anyway; keep the path the same as the command's `--out` whichever way it goes.
- Line 200: replace "`--run runs/<mission>/<budget>`" with "`--run runs/4h`".
- Optionally: "Left out, `--out` defaults to `runs/<mission name>/<budget>`, and `whatif --run` defaults to the same directory, so give `--run runs/4h` when you used `--out runs/4h`."
- No test I found pins `runs/<mission>/<budget>` in a document (grep: the only hits are `__main__.py:56` and `:80`), so editing these lines breaks nothing; run `tests/test_config_docs.py` after the docs step anyway.

### What I checked could break, and how
- The usage line is a comment; `exec python -m cafe.pm run "$@"` is untouched. `tests/test_acceptance.py::test_run_premission_is_executable_and_runs_the_run_command_from_the_repo_root` passes on the changed tree.

## Verification (all on orca, `PM_HOST=cafe-orca PM_RUNTIME=proot PMX=pm_r11d PM_CPUS=2`; no real orca_sync, orca_ready or worker_setup was run, only the tests' stand-in ssh)
- New tests: 26 cases pass on the fixed tree. On a detached worktree of 3ce8e09 with only the two test files copied in, 22 of the 26 fail; the 4 that pass are the "good addresses are still sent" cases, which must pass before and after. The worktree and its orca directory were removed.
- `ruff check cafe/pm tests`: clean (after shortening two comment lines in the new tests).
- Whole files `tests/test_runners.py` and `tests/test_config_docs.py` (TM log `r11d_files`): exit code 0, 321 passed, none failed or errored.
- mypy not run: no file under `cafe/pm` changed.

## Needs from other batches
- Docs step (E): the doc sentences above, M-33 (RUNBOOK lines 199-200, coordinated with M-34), M-18 and M-19 (ORCA_RUNNER lines 9, 13, 44), then DECISIONS rows 593-596 and the amended rows (496, 557, 571, 564, 458) and the four CHANGELOG lines.
- Nothing is needed from batches A, B or C. If a batch adds a `.PHONY` name, the M-32 test checks it has a rule.
- M-29 (RUNBOOK `pm()` wrapper and env-var forwarding) is outside this brief; `bin/pmx.sh` and `bin/proot_run.sh` are untouched, so a forwarding option would not conflict with anything here.
