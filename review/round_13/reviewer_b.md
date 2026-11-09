# Round 13, reviewer B

Setup: detached worktree `../cafe-rev13-b` at HEAD 939851e (code of cdad21a), orca directories `pm_rev13_b`, `pm_rev13_b2`, all jobs `PM_HOST=cafe-orca PM_RUNTIME=proot PM_CPUS=2`.

## Findings

### B-1. The command the golden messages print is refused by the CLI: it has no `--out`
severity: minor
lane: documentation
where: cafe/pm/acceptance.py:383 (`update_command`), :353 (`_golden_record`'s `command` field); cafe/pm/__main__.py:106 (`--out` is `required=True`)
reproduction: `PM_HOST=cafe-orca PM_RUNTIME=proot PMX=pm_rev13_b2 PM_CPUS=2 bin/pmx.sh python -m cafe.pm acceptance --mission missions/tepex_c_demo.yaml --gpus 0 --update-golden` (exactly what `update_command` returns for the default golden) prints the usage and `python -m cafe.pm acceptance: error: the following arguments are required: --out`, exit 2.
why it matters: DECISIONS 680 and 685 say the printed advice "cannot be refused" and "pastes as one command"; the tests (`test_r12_l0_m33_*`) feed the words back to `check_golden`, never to the argument parser, so the missing required flag was not seen. Every message that asks for a new golden hands the lab user a command that stops at once.

### B-2. The report still says a same-name copy of the demo differs in "window, box and vehicles"
severity: minor
lane: honesty / documentation
where: cafe/pm/report.py:1087 (and tests/test_report.py:1051, which pins the sentence)
reproduction: DECISIONS 683 / `credibility.is_the_demo` now refuses a mission with the demo's name when anything but `seed` and `description` differs (the test `test_r12_l0_m5_a_copy_with_the_demos_name_window_box_and_vehicle_ids_but_anything_else_changed_gets_no_sanity_block` moves only the ship, a platform, a link or a cut-off). For such a copy `report._sanity` still writes "This mission has the demo's name but not its window, box and vehicles, so BRIEF section 6's expected outcome for the demo mission does not apply to it." That is false for exactly the copies the new rule was made for: their window, box and vehicle ids ARE the demo's.
why it matters: the report states a reason that is not the reason, to a reader who then looks for a window or box change that is not there. (CREDIBILITY.md:191 was updated; the report sentence and its test were not.)

### B-3. The stamped-result flow of RUNBOOK 7 (point 3) cannot be followed with the RUNBOOK's own `pm()`; `CAFE_APP_RUNS` is not documented anywhere
severity: minor
lane: documentation / reproducibility
where: cafe/pm/receipts.py:368 (`CAFE_APP_RUNS` default `/work/runs`), cafe/receipts.py:99 (the advice `python -m cafe.receipts stamp {path}`), docs/RUNBOOK.md (point 3 of "Receipts on a clean machine": "`runs/crosscheck.json`"), pm.sh and bin/pmx.sh (`-v $HOME/work/cafe/data:/work:ro`)
reproduction: `grep -rn CAFE_APP_RUNS` finds only the default in cafe/pm/receipts.py and a test: no document names it. The RUNBOOK step 1 `pm()` mounts only `/app` and `/data` (`CAFE_WORK=/data/work`), so `/work/runs` does not exist there and `make receipts` looks for `torpedo.external.json`, `crosscheck.json` ... under a directory the lab user has not got; the RUNBOOK tells them to stamp `runs/crosscheck.json` (a path under `/app`, which `make receipts` never reads). On homebase's `./pm.sh` and `bin/pmx.sh` `/work` is mounted `:ro`, so the advice the row prints (`python -m cafe.receipts stamp /work/runs/crosscheck.json`) fails: `stamp` writes a temporary beside the file, and on a read-only mount that is an OSError traceback (EROFS; a read-only directory gives the PermissionError of B-4). Only orca (`-b $C/data:/work`, writable) accepts it.
why it matters: RUNBOOK 7 point 3 says the app group's pass count recovers after the stored files are remade or stamped; on a clean machine nothing the document says makes them count.

### B-4. `python -m cafe.receipts stamp`: a read-only directory is a traceback, and a symlink is replaced by a stamped copy
severity: minor
lane: robustness
where: cafe/receipts.py:640-650 (`__main__` stamp branch catches only ValueError), cafe/receipts.py:`stamp_file` -> cafe/pm/config.py:247 `write_json` (tmp + os.replace)
reproduction: on orca from a script: `mkdir ro; echo {} > ro/f.json; chmod 500 ro; python -m cafe.receipts stamp ro/f.json` -> exit 1 with a `PermissionError: [Errno 13]` traceback (not `error: ...`). `ln -s real.json sl.json; python -m cafe.receipts stamp sl.json` -> exit 0, `stamped .../sl.json`, but `sl.json` is now a regular file holding the stamped copy and `real.json` (the file the link pointed at) is unstamped.
why it matters: the tool that the new advice sends every lab user to has two of the usual failures unhandled, one of them silent (the stamp lands on a copy the reader never sees).

### B-5. `parse_cdf1` accepts or crashes raw on a corrupt header; a negative length is read as an empty name
severity: minor
lane: robustness
where: cafe/pm/env/remote.py:270 (`_Buf.take`), :283 (`name`), :301-332 (`parse_cdf1`), :352 (`cdf1_read`)
reproduction: local CDF-1 files built by hand (script rev13_b_p7): a name length of -8 returns `({'': 1}, 0, {})` with no error (`take(-8)` slices backwards and moves the cursor back); a variable whose dimension id is out of range gives `IndexError: list index out of range`; a type code of 99 gives `KeyError: 99`; a negative dimension size gives a variable of shape `[-3]`; `rec=-1` in `cdf1_read` is an `OSError [Errno 22]` from `seek`.
why it matters: the header comes from a server; a damaged or replaced file should be a ConnectionError / ValueError with the file named, like the other remote errors (the new identity check only covers a file that changes between requests, not one that is wrong from the first byte).

### B-6. `cdf1_header` and `cdf1_read` treat any local path that starts with "http" as a URL
severity: minor
lane: robustness
where: cafe/pm/env/remote.py:337 and :369 (`p.startswith("http")`)
reproduction: `cd dir; python -c "from cafe.pm.env import remote; remote.cdf1_header('httpx.nc')"` with a local file `httpx.nc` -> `ValueError: unknown url type: 'httpx.nc'`.
why it matters: a data folder or file named `http_cache/...` or `https-data.nc` is unreadable; the test is `startswith("http://", "https://")` in spirit. (Older than the look-ahead, but the look-ahead rewrote both functions.)

### B-7. `--update-golden --golden DIR --golden-mission NAME` ends in a traceback after the first long run, and the golden is written non-atomically
severity: minor
lane: robustness
where: cafe/pm/acceptance.py:360-374 (`golden_refusal` treats a directory as "not a golden file" and advises `--golden-mission`), :393-396 (`golden.write_text`)
reproduction: on orca, `acc.check_golden(r, <a directory>, "m.yaml", True, golden_mission="m")` -> `IsADirectoryError: [Errno 21] Is a directory` (`--golden DIR` without the flag gives the refusal "is not a golden file ... add `--golden-mission m`"). `run()` (acceptance.py:511) passes its early check once `--golden-mission` is given, then `check_golden` (line 534) writes right after the first `quick` run, so the traceback arrives about 20 min into the command and the remaining checks (same seed, other seed, broken, overnight) never run.
why it matters: the advice of the refusal ("add `--golden-mission NAME`") leads to a crash after the first of the long runs; `golden.is_dir()` is the one more test the early check needs. The same line writes the golden with `write_text`, not through `config.write_json` (temporary + `os.replace`, which every other stored result uses since round 9): a write cut by a full disk (orca's shared disk reads 100 %, P-8) leaves a truncated golden, which `golden_refusal` then reads as "not a golden file" and so demands `--golden-mission` to repair.

### B-8. `remote.download` of an empty file and of a path in a missing directory give misleading errors
severity: minor
lane: robustness
where: cafe/pm/env/remote.py:`_probe` / `_open` (HTTP 416 mapped to FileNotFoundError), `download` (`mark.write_text` before the parent exists)
reproduction: local ranged server (script rev13_b_p1): `download(url_of_a_0_byte_file, path)` -> `FileNotFoundError: <url>: HTTP 416`; `download(url, tmp/'nodir'/'f')` -> `FileNotFoundError: [Errno 2] No such file or directory: '.../nodir/f.part.id'`.
why it matters: a zero-byte upstream file looks like a missing one, and the second names a bookkeeping file the user never heard of.

### B-9. The row for an unstamped `crosscheck.json` tells the reader to rerun a program that does not write it
severity: minor
lane: documentation / honesty
where: cafe/receipts.py:98-99 (`stored`: one advice for every file), against the comment at cafe/receipts.py:49-50 and RUNBOOK 7 point 3 ("nothing in the repository writes it")
reproduction: `make receipts` on orca at HEAD (rev13_b_rc, `runs/receipts.json`): the row `Emulator: stored result crosscheck.json carries no date, host, git_sha, code_digest ... (unstamped): not counted` has the source text "rerun the run that writes it (python -m cafe.cfd stamps its file), or if you have checked this one, `python -m cafe.receipts stamp /work/runs/crosscheck.json`". `cafe.cfd` writes only torpedo.external.json, wigley.surface.json and suboff.incidence.json.
why it matters: the first remedy offered on the SITL row cannot work and the comments of the same commit say so; the lab user is sent to run a CFD smoke case that never touches that file.

### B-10. RUNBOOK 7 point 2 still gives the clean-orca receipt counts of round 11
severity: minor
lane: documentation
where: docs/RUNBOOK.md:246 ("`make receipts` ended with 350 rows, 287 passing, 33 context and 30 failing")
reproduction: `PM_HOST=cafe-orca PM_RUNTIME=proot PMX=pm_rev13_b PM_CPUS=2 TM=rev13_b_rc bin/pmx.sh make receipts` at HEAD, no slow group stored: `273 pass, 30 fail, 32 context (335 rows)`, exit 2 (`runs/receipts.json`: 30 failures = pm.dtmb5415 20, pm.stage3.lbm 3, pm.stage3.nest 3, pm.stage3.wallmodel 1, app.fea / pm.physics.uas.slow / pm.emulator `not_run` 1 each; the 4 unstamped CFD/SITL files are context rows). The run took about 11 min (RUNBOOK says "about 17 min").
why it matters: the paragraph is the lab user's check that the install is healthy ("a failing row whose id is not on that list ... means a broken install"); the numbers it gives (350, 287, 33) differ from what a healthy install now prints, and point 3, which explains the drop, gives no new total.

### B-11. A symlink loop inside a run directory is a RuntimeError traceback in `audit` and `report`
severity: minor
lane: robustness
where: whichever `Path.resolve()` the ledger reader and the report reach first (both commands print `RuntimeError: Symlink loop from '<run>/windows/windows.json'`)
reproduction: copy `runs/ci` of `make ci` to `/data/runs/rev13_b_au/x`, `cd x; rm -rf windows; ln -s windows windows`; `python -m cafe.pm.audit --ledgers-only x` and `python -m cafe.pm report --run x` both exit 1 with a traceback ending in that RuntimeError (every other damage tried in the sweep below ends in `error:` / `AUDIT FAIL` and exit 2 / 1 with no traceback).
why it matters: the one damage of a run directory that the round-10 and round-12 sweeps (which mutate JSON content) cannot have found; low likelihood, but it is the only traceback in an 18-case sweep.

### B-12. `validate`: a long vehicle list is echoed whole in the error, 64 vehicles is an undocumented limit, and deeply nested YAML is a RecursionError traceback
severity: minor
lane: robustness / documentation
where: cafe/schemas/mission.json:40 (`vehicles` maxItems 64), cafe/pm/config.py:69 and :409 (`_yaml`, `load_mission`; the loader recurses without a guard)
reproduction: on orca (script rev13_b_p14): a mission with 3,000 `drift` gliders -> `ConfigError` of 544,994 characters whose text is the repr of the whole list followed by `is too long` (21 and 25 vehicles load); nothing in the RUNBOOK (which says 20 vehicles are fine) names the limit of 64. A file `a: [[[...3000 deep...]]]` -> `RecursionError: maximum recursion depth exceeded` from PyYAML's composer, uncaught (every other malformed file in the 24-case sweep of rev13_b_p13 is a one-line `error:`: tab, BOM and CRLF, UTF-16, latin-1, alias, `!!python/object` tag, duplicate key, octal, NaN, empty, list/scalar top level).
why it matters: the first two make a typo in a big fleet file print half a megabyte; the third is a traceback from `validate` on a hostile file.

### B-13. `entries_read` leaves out the radio the UAS's own lost-link hook reads, and a test pins the wrong count
severity: minor
lane: honesty / data
where: cafe/pm/credibility.py:442-466 (`entries_read`: "an rf link its radio"), cafe/pm/stage1.py:278-286 (`_uas_radio`), :301 and :347 (`_uas_links` is built for every sortie), tests/test_credibility.py `test_r12_l0_m6_an_iridium_only_mission_uses_the_sbd_inputs_and_nothing_else_of_radios_and_modems`
reproduction: `stage1._uas_radio(uas.load_platform("quad_uas"))` (script rev13_b_p16, orca) returns the platform's first radio block with a transmit power (`rfd900x`) merged with `radios.yaml`'s entry of that name: `gt_dbi 2.0, gr_dbi 2.0, misc_loss_db 3.0, cable_loss_db 0.0`. `_uas_sortie` hands it to `uas.fly_sortie` as the `link` hook for every sortie, whatever links the mission lists, and a margin below 0 dB for `radio.link_loss_hold_s` (5 s) is the UAS's `lost_link` failsafe: `comms.rf_margin` at 2/3/4 km is 60.18/54.88/50.32 dB, and 63.18/57.88/53.32 with `gt_dbi` +3, so the assumed value moves the UAS's verdict inputs one for one. But `entries_read([iridium link])` is `{('iridium','sbd')}` and `entries_read([rf link with rfd900x_fast])` is `{('radios','rfd900x_fast')}`: in a mission that keeps the UAS and has no RF link, or an RF link on another radio, `radios.rfd900x.{gt_dbi,gr_dbi,misc_loss_db}` are "platform not used by this mission" and out of the assumed-input count and the input-pedigree rule. The Iridium-only test keeps the demo's UAS vehicle and asserts that no `rfd900x` input is used.
why it matters: DECISIONS 681 / CREDIBILITY.md say the count is "the inputs this mission's verdicts depend on"; for a UAS mission that is not true of the radio the UAS flies with, and the test written to pin the new rule pins the omission. (In the demo the RF link names `rfd900x`, so its 273 is right.)

### B-14. The `OutsideData` message, now printed as `error:` by `main`, tells the user to run a command that does not exist
severity: minor
lane: documentation
where: cafe/pm/env/environment.py:142 ("re-run `cafe fetch` with a larger box or window") and :316 ("run `cafe fetch` (GOFS 3.1 by default)"); cafe/pm/__main__.py:173 (the new `except (..., OutsideData)` prints it)
reproduction: on orca inside the job: `which cafe` -> rc 1, `ls /venv/bin | grep cafe` -> nothing, `python -m cafe fetch` -> "No module named cafe.__main__"; `pyproject.toml` has no console script. The command is `python -m cafe.pm fetch --mission <file>` (RUNBOOK 3). DECISIONS 442 records that `cafe validate` and `cafe fetch --full` are not built; the plain `cafe fetch` of BRIEF 148 is not built either.
why it matters: before L0 this text was a traceback's last line; since 7c6210a it is the whole `error:` a lab user reads when a vehicle leaves the data, and its one instruction cannot be pasted. The L1 commit reworked this very message (box_words) and left the command.

### B-15. A stamp that names no commit (`git_sha` "none") is a valid stamp, and the README's own workflow writes exactly that
severity: minor
lane: reproducibility / honesty
where: cafe/receipts.py:`stored` (`missing = [k for k in STAMP if not isinstance(rec.get(k), str) or not rec[k]]`), cafe/pm/ledger.py:33-39 (`git_sha` returns "none"), README.md:173 and run.sh (the documented `./run.sh python -m cafe.cfd ...` mounts a copy of `cafe/` with no `.git` and passes no `CAFE_GIT_SHA`)
reproduction: on orca, `env -u CAFE_GIT_SHA python -c "from cafe import receipts as R; print(R.stamp({'rho': 1.0}))"` gives `git_sha: 'none'` and a `code_digest`; written to a file, `R.stored(file, "CFD")` returns the record and the row source reads `[stored 2026-11-09T00:40:10+00:00, 96c76d5cb870, git none]`. `host` is the container id (`96c76d5cb870`), which names no machine either.
why it matters: the stamp was added so that a stored result says "which commit and which code made them"; by the README route it never names a commit, and the receipt counts as a pass all the same (the golden's provenance check, by contrast, demands 40 hex digits).

## Checked, no defect found

- RUNBOOK 3: `validate` on the demo prints `valid (4 vehicles, 4 links)` and the verdict.go note, as written. RUNBOOK 2: `make ci` ran on orca at 2 CPUs (loaded box, load 8 to 28 from other jobs): rc 0, ends `report: runs/ci/report/index.html`, `audit: 0 problem(s)`, 3.3 min (RUNBOOK says "~10 min"). RUNBOOK 7: `make receipts` ran to its end (11 min, exit 2, the failing rows are the documented ones; see B-10), `make broken` (21 min, rc 0, "the broken configuration failed 10 receipt(s) that pass without it") as the document says.
- ORCA_RUNNER: PMX, TM, PM_CPUS, PM_MEM, PM_SHM, PM_THREADS, PM_STOP_GRACE, CAFE_MIN_FREE_GB and gate-tag refusals (`pmdata`, `data`, `pm`, `tmp`, `..`, `../x`, `pm_a b`, `pm_a;x`, `$(id)`, a trailing newline, `010`, `+2`, `2\n`, an Arabic digit, `1e3`, `12 g`, `0g`, tags `a_s1`, `a_serial`, `x`, K=0/17/08) all exit 2 with nothing sent (tried against a host name that cannot resolve, so a miss would have been harmless); `orca_sync.sh` refuses `a;b`, `-x`, `$(id)`, `host name` and an unknown part name before sending; the stop procedure of "Stopping a job" (tmux kill-session on a `sleep 300` job) ended the log with `rc=143` and the job's temp directory went; exit statuses of proot jobs (`exit 7` gives 7, `(sleep 3; exit 0) & exit 3` gives 3, `(sleep 3; exit 9) & exit 0` gives 0) are as the document says.
- Look-ahead commits read line by line (7c6210a, e00a75b, 2d5e6ad): `_ident`/`_read_ident`/`_probe` (a total of `*`, `-5`, `0`, text: refused or -1 as DECISIONS 684 says; an empty file is the 416 case of B-8), `Header` (pickle, copy, deepcopy keep `.ident`; json gives a list; slicing gives a plain tuple), `download` (weak ETag only and strong ETag resumes as DECISIONS 688 says; a sha mismatch without `pin` replaces the file; a total smaller than the body is a ConnectionError), `bathy._rows` (ident passed on, the replaced-file test is the right one), `box_words` (the tuple order of `GriddedEnv.bounds[2:4] + bounds[:2]` and of `Ocean.bounds()` both give lat then lon; no unlabelled box tuple left in `cafe/`), `receipts --only ""`/`[]`/`","` (exit 2, nothing written), `stage1.main`'s widened except (the names are imported at module level), `damaged_run_files` (a class defined in a module of `cafe` passes through; audit's `_Unreadable` is caught inside audit, so nothing that now passes through reaches `main` unhandled, except `MemoryGuardError`, which no `_run_files` scope can raise), `mission_digest` (digest of the shipped file equals `DEMO_DIGEST`; a seed, a description or key order does not change it; `-165` for `-165.0`, another spelling of the window time, or an extra key does, which is the safe direction), `entries_read` (a cyclic `implementation_loss_like` terminates; hostile link entries: only `None` as a link crashes, and the mission is validated before), `update_command` (every word shell-quoted, including a newline in a path; but see B-1).
- DECISIONS 681: the demo's numbers recomputed from q13: 273 = 285 catalogue minus the 12 unused items (radios.yaml 8 of 19, modems.yaml 3 of 4), the 285 excludes the 2 `fitted` of 287; they match `report.json`. The Wilson 95 % bounds of every vehicle and link in q13's report (e.g. glider_eq 18 of 64: 0.1859 to 0.4013; 0 of 64: upper 0.0566; "73 members" and "3/n = 0.04688") agree with an independent computation.
- `plan` arithmetic on hostile missions (orca, 2 CPUs): 30-day window, 20 gliders, one USV: the stage-1 time is (batches x per-batch-day x days + members x per-member-day x days) summed over vehicles over the workers in all three (382 s for 20 gliders, 502 s for 30 days, 26 s for one USV), the emulator line (3 variants of 50 s plus the base, 70 % of 240 s) is right, and `plan` exits 0 as the troubleshooting table says it should for a fit.
- about 85 hostile missions through `load_mission` (reversed box, ship at 95 N / 400 E, deploy outside box or after the end, link to a missing id, a == b, NaN/inf fractions, go < nogo, platform path traversal and empty, unicode id, name of 64 and 65 characters, UAS with a task / a ship base that is a vehicle / altitudes out of order / duration 0 / 25:00, waypoints with one point, three columns, strings, radio and modem names in the wrong case or the wrong kind, unquoted time, quoted seed, octal, duplicate key, tab, BOM, CRLF, UTF-16, latin-1, alias, python tag, billion laughs): all `ConfigError` with the field named, except the cases in B-12; no crash.
- 18 damages of a finished run directory (truncated or list-valued summary.json, NaN p_fail, missing or list plan.json, binary mission.yaml, missing report/, ledger missing/empty/a directory, truncated or random res.pkl, missing stage3) through `audit --ledgers-only` and `report --run`: every one an `error:` or `AUDIT FAIL`, none a traceback, except the symlink loop of B-11.
- `bin/orca_ready.sh` run as ORCA_RUNNER step 3 says (`PMX=pm_rev13_b3 PM_HOST=cafe-orca sh bin/orca_ready.sh`): ended `orca-ready` (workers 2, memory 270.2 GB, tests/test_par.py and the toy interFoam test pass; the busy list names processes only). `ruff check cafe/pm tests`, `mypy cafe/pm` (55 files) and `tests/test_audit.py` pass at HEAD, whose `audit.py` change (DECISIONS 691) was made after the last gate (9a62f4b).

## Not covered

RUNBOOK steps 1, 4 and 6 by reading only; step 3's `fetch` (network, hours, and the shared cache), step 5's demo run (forbidden), `make bench`, `make audit` (full pytest), `make acceptance`, `receipts --slow` and the gate (`orca_gate.sh`) not run. `orca_setup.sh` and `orca_sync.sh` only for their argument refusals (they reach homebase). The identity checks of `remote.py` ran against a local ranged server only: what the real orca.atmos, THREDDS, NOAA and CEDA servers send in ETag, Last-Modified and Content-Range on a 206 was not seen (no network use), so a spurious "file changed on the server" on a real host is not excluded. Mutation checks of the new tests were by reading (reviewer A's task), not run. Credibility factor scorers, the stage-1 physics and everything in lanes C and D only as far as the above touched them. The ci-budget variants of a mission (vehicles at the data edge, a UAS that never launches, one vehicle) were prepared and not run.

## Disclosures

- Orca was loaded by other reviewers' jobs during the run (load 8 to 45 against the 32-CPU quota); my long jobs (`make ci`, `make receipts`, `make broken`, `orca_ready`) ran one after another at `PM_CPUS=2`, but the short probe scripts (each seconds to two minutes, about one core) ran beside the long job that was running, so for most of the time I used up to 3 CPUs, not 2. No process was stopped except my own tmux session `rev13_b_stop` (by name, with the documented command). The `watch` session was not touched.
- One probe made a scratch directory with Python's `tempfile.mkdtemp` under `/data/runs` with a name outside my `rev13_b_*` prefix (`tmpghaydcmo`); I removed that exact directory at once. Everything else was under `rev13_b_*` names and is removed: the pm_rev13_b, pm_rev13_b2, pm_rev13_b3 directories, my scripts and run directories under pmdata, my four logs and the ready marker; the worktree `../cafe-rev13-b` is removed. A one-line file was briefly written to the laptop's `/tmp` (`rev13b_src_flags.txt`, a grep of flag names) and deleted. No row was added to `review/orca/PROBLEMS.md` (nothing went wrong with the runner; the editing of that file by the lead was left alone).
- The jobs wrote nothing to the shared emulator table: `make ci` ran a pipeline with its own `CAFE_DATA` (`/tmp/cafe_ci_data` inside the job), and `make receipts` and `make broken` append to no table.

total: 15 findings (0 critical, 0 major, 15 minor)
