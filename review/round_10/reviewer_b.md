# Round 10, reviewer B

Reviewed commit `a470119` (code as `8b870a6`), branch `premission-step4`. Followed `docs/RUNBOOK.md` and `docs/ORCA_RUNNER.md` as a lab user on orca (proot, 2 CPUs, `PMX=pm_rev10_b`), from a detached scratch copy.

What was run: the RUNBOOK's `validate`, `plan`, `hangar`, `make ci` (rc 0, ends `audit: 0 problem(s)`), `report --run` and `audit --ledgers-only` on a copy of the q10 run (report.json equal to q10's except the run name and one hash that holds it), `whatif` (five forms), 49 hostile mission files through `validate`, 14 corrupted run directories through `report`, six more missions through a real `run --budget ci` (one vehicle, 20 vehicles, a 3 h window, a vehicle on the box edge and corner, a go cut-off of 0.99), `plan` for a 30-day window and 20 vehicles, and the same ci mission at 1 and 2 workers. Printed numbers recomputed from q10: the Wilson intervals and `n_certify` 73 of all eight verdicts, the V&V 20 row Fr 0.10, the assumed-input counts, the planned stage-1 time (2 x 26.34 s), the table rows (21 other + 28). All of those agree.

Not found wrong: nothing in the validate, plan, ci and re-render paths contradicts the RUNBOOK except what is listed. 0 critical.

### B-1. The emulator pools missions and platforms but has no feature for the flight's length or the platform
severity: major
lane: statistics
where: cafe/pm/whatif.py:51-53 (`BASE`, `TASK`), 388-393 (`_clean`), 421 and 433 (`fit_class`), docs/RUNBOOK.md step 5 ("new points come from ... a different mission")
reproduction: `Emulator(BASE + TASK[cls], ...)` has deploy_h, lon, lat, six wind/Hs/current statistics and the task fields; no feature holds `window.end - deploy` (the time a vehicle is exposed) or the platform. `_clean` keeps every row of the class, whatever its mission or platform, and the RUNBOOK tells the user to add points by running other missions. The `glider` class already holds a Seaglider (glider_eq) and a Slocum (glider_2n): 14 rows in q10's table. P(fail) depends strongly on the exposure: from q10's `stage1b/res.pkl`, glider_eq with the same feature vector (deploy 0 h, -170/0, dive 950, radius 5, lost 12) has P(fail by day d) = 5/64, 10/64, 13/64, 15/64, 15/64 for d = 2, 3, 4, 5, 6. A 3-day and a 6-day mission therefore have the same inputs (apart from small differences in the wind means) and P(fail) 0.156 and 0.234. Within one mission `deploy_h` stands in for the exposure, which is why a shift variant works there; across missions it does not.
why it matters: once 100 points exist, rows of unlike missions are fitted as one function and a what-if for mission A is answered from mission B's response. The hold-out is a random split of the pooled points, so a pooled model that fits the pool can pass the acceptance gates and still be wrong for A. Not seen in the demo (7 points, never trains); latent until the table grows.

### B-2. `whatif --shift` on a glider compares P(fail) over a shorter flight with the baseline's and does not say so
severity: minor
lane: documentation
where: cafe/pm/whatif.py:117-121 (`apply`: deploy time moves, `window.end` stays), docs/RUNBOOK.md step 5 (what if)
reproduction: `python -m cafe.pm whatif --mission missions/tepex_c_demo.yaml --run <q10 copy> --shift 48h` prints `glider_eq: MARGINAL (P(fail) 0.234) -> MARGINAL (P(fail) 0.125) (0.072 to 0.209) [Stage 1, n = 64 ...]`. The shifted glider flies 4 days, not 6. The baseline's own 64 members censored at 4 days give 13/64 = 0.203 (res.pkl, `fail.station_lost` first times), so 0.031 of the 0.109 drop is the shorter exposure alone. The same applies to the flip search's "deploy N h later" candidates.
why it matters: "deploy two days later" reads as a gain in weather, partly it is two days less to fail in. The answer line and the RUNBOOK should say the flight is shortened (or the window end should move with the shift).

### B-3. `acceptance --out DIR` deletes `DIR/quick`, `DIR/overnight` and the others with no guard on what DIR is
severity: minor
lane: robustness
where: cafe/pm/acceptance.py:99-100 (`run_one`: `shutil.rmtree(d, ignore_errors=True)`, `d = out / name`), 109-111 (`<name>_fetch`); the guard at 85-89 covers only the mission file
reproduction: `mkdir -p /tmp/myruns/quick /tmp/myruns/overnight; echo x > /tmp/myruns/quick/report.json; CAFE_OFFLINE=1 python -m cafe.pm acceptance --mission missions/ci_fixture.yaml --out /tmp/myruns --skip-overnight`. Right after the start `/tmp/myruns/quick` holds only `emulator_table/`; report.json is gone. With `--out runs` the same removes the user's `runs/quick` and, without `--skip-overnight`, `runs/overnight` (10 h). (Run on orca inside the container's /tmp; stopped by its pid after the check.)
why it matters: every other command takes `--out runs/quick`, so `--out runs` is a natural slip; the RUNBOOK's promise that `runs/quick` "is not touched" holds only for `make acceptance`. Refuse an `--out` that already holds a run (a `plan.json`) or is not empty and not an acceptance directory.

### B-4. The documented go check writes to the fixed name `pm_ready`, which other people's checkouts already use
severity: minor
lane: robustness
where: bin/orca_ready.sh:6 (`PMX=pm_ready` exported over the caller's), 20-24 (the "changed outside cafe-worker" test); docs/ORCA_RUNNER.md step 3
reproduction: `ssh cafe-orca 'ls -d ~/cafe-worker/cafe/pm_*'` lists `pm_ready` now (not ours). `PM_HOST=cafe-orca sh bin/orca_ready.sh` runs `bin/pmx.sh`, which rsyncs the caller's checkout onto `~/cafe-worker/cafe/pm_ready/` with `--delete`, so it replaces whatever that directory holds. Not run for that reason. The last step lists every file under `~` (depth 2) newer than a marker and fails the check on any: on a shared account another user's file lands there, and the message itself says "or someone else on the account".
why it matters: following ORCA_RUNNER step 3 word for word overwrites another checkout, and a clean check cannot be had while anyone else on the account writes. Take the directory from `${PMX:-pm_ready_$USER-or-a-tag}` and test only paths the check could have written.

### B-5. `report --run` renders a GO from a hand-edited summary, exit 0, traceability clean, and does not check the stage hashes
severity: minor
lane: honesty
where: cafe/pm/report.py:1637-1645 (`write`), 1648-1653 (`self_checks`); cafe/pm/__main__.py `_report`
reproduction: copy a run, then set `stage1b/summary.json` `summary.vehicles.usv` to `verdict.verdict: GO`, `verdict.k_fail: 0`, `verdict.p_fail: 0.0`, `k_fail: 0`; `python -m cafe.pm report --run <copy>` exits 0 and `report.json` says `usv ... GO`, `k_fail 0`, `traceability_problems: []`. Only `python -m cafe.pm audit --ledgers-only <copy>` reports `output .../summary.json changed since the stage ran` (3 problems). Two more inputs of the same kind pass silently: `verdict.p_fail = NaN` renders `p_fail.value` as null with the verdict NO-GO kept and exit 0, and `verdict.k_fail = 70` of n = 64 in the file is not compared with the top-level `k_fail`.
why it matters: the report's "Traceability check: every number links to a receipt" line is true of the links and says nothing of the hashes; a re-render of an edited run looks like a clean one. `report` could run the hash part of the audit (or print the audit's problems) before it writes, and check that verdict, k_fail, n and p_fail agree.

### B-6. `report --run` on a run with a refit file or a summary missing a key ends in a traceback
severity: minor
lane: robustness
where: cafe/pm/report.py:829 (`rv["used"]`), 999 (`FileNotFoundError` for a missing `stage1b/summary.json`)
reproduction: in a copy of q10 remove `used` from every entry of `refit/refit.json`; `python -m cafe.pm report --run <copy>` exits 1 with `KeyError: 'used'` and a Python traceback. Remove `stage1b/` instead: exit 1, traceback ending `FileNotFoundError: .../stage1b/summary.json: stage1b/summary.json is not in the run directory; run the stage1b stage first`. The other twelve corruptions tried (truncated JSON, a list or a string where an object belongs, an empty mission.yaml, a missing plan.json, flip.json, design.json or the report directory) give `error: ...` with exit 2 or render, as the RUNBOOK says.
why it matters: the RUNBOOK's troubleshooting table promises `error: ... run it again (--fresh)` for damaged files. There is also no command that runs "the stage1b stage" by itself, so the advice cannot be followed; say `run --fresh`.

### B-7. Other commands that print a traceback on a bad path
severity: minor
lane: robustness
where: cafe/pm/receipts.py:446 (`FileNotFoundError` for `--broken <missing file>`); `run --out <existing file>` (`FileExistsError` from `os.mkdir`, before any stage); cafe/pm/__main__.py (`main` catches only `ConfigError`, `PlanError` and `StageFailed`)
reproduction: `python -m cafe.pm receipts --broken /nonexistent.yaml` ends `FileNotFoundError: broken configuration /nonexistent.yaml: no such file`; `: > /tmp/afile; python -m cafe.pm run --mission missions/ci_fixture.yaml --budget ci --gpus 0 --out /tmp/afile` ends `FileExistsError: [Errno 17] File exists: '/tmp/afile'`.
why it matters: the same RUNBOOK promise (`error:` and exit 2 for a bad input) does not hold for a path argument.

### B-8. The free-surface refusal reads "it would fit no --budget profile's plan holds it (the largest gives 0 min)"
severity: minor
lane: documentation
where: cafe/pm/stage3/pipeline_windows.py:646-648 joined with cafe/pm/stage3/freesurface.py:144
reproduction: `make ci` (RUNBOOK step 2) log: `... against 0.6 min left of the 1 min stage-3 share; it would fit no --budget profile's plan holds it (the largest gives 0 min)`. The sentence is built as "it would fit " + `fitting_budget(...)`, and `fitting_budget` returns a full clause when none fits. The demo run gives the clean "it would fit --budget overnight (118 min ...)". The RUNBOOK troubleshooting row quotes the second form as the message.
why it matters: the text a lab user reads on any mission whose hull window fits no profile is ungrammatical; it ends "(the largest gives 0 min)" beside "1 min stage-3 share" for the running plan, which looks like a contradiction.

### B-9. RUNBOOK step 1: "About 15 days of the demo box fit 32 GB" is not what the memory model gives
severity: minor
lane: documentation
where: docs/RUNBOOK.md:44, cafe/pm/budget.py:54-56, 249-252 (`env_model_gb`), pipeline.padding
reproduction: `budget.env_model_gb` on the demo with the window lengthened (start 2023-03-01T12Z): with the demo's `pad_deg: 2.0`, 15 d needs 22.5 GB (+0.9 per worker), 20 d 30.0 GB, 21 d 31.5 GB: about 20 days fit 32 GB. With the default pad (no `pad_deg`), 15 d needs 43.7 GB, 20 d 75.4 GB, and 32 GB holds about 10 days. 30 d with the default pad needs 141.8 GB (the RUNBOOK says "more than 100 GB", true; with the demo's pad of 2 it is 45 GB, which would fit a bigger machine and is not mentioned).
why it matters: the sentence is read as a sizing rule and fits neither box.

### B-10. `hangar --platform modems` counts 2 assumed inputs; the report counts 4 for the same file
severity: minor
lane: documentation
where: cafe/pm/pipeline.py:963-967 (`_assumed` counts `assumed: true` only), cafe/pm/__main__.py:254; report.json `assumed_inputs.by_file["platforms/modems.yaml"]`
reproduction: `python -m cafe.pm hangar --platform modems` prints `provenance OK, 2 of 2 values assumed`; q10's `report.json` lists `modems.yaml:modems.benthos_atm960` and `modems.whoi_micromodem` as assumed too (their `assumed:` is a sentence naming SL and SNR), 4 in all. The two modem entries' assumed source level and SNR are not listed by `hangar`, which RUNBOOK step 5a names as the place to see every assumed input.
why it matters: the command a lab user is told to use to see what to replace leaves out the acoustic modem's source level and required SNR.

### B-11. Several RUNBOOK messages and counts do not match what the commands print
severity: minor
lane: documentation
where: docs/RUNBOOK.md troubleshooting table; cafe/pm/__main__.py (`argparse` for `audit`), cafe/pm/par.py:53
reproduction: (a) table row "`error: unknown option --x` from `audit`": `python -m cafe.pm audit --bogus` prints argparse's usage and `unrecognized arguments: --bogus` (exit 2); only `python -m cafe.pm.audit --bogus` prints `error: unknown option --bogus (--code-only, ...)`. (b) row "`error: ...: no plan.json; this is not a finished run directory`": for a directory that has no `mission.yaml` either (any wrong path) `report --run` prints `error: <dir>/mission.yaml: file not found`; the `no plan.json` text appears only when mission.yaml exists. (c) "`CAFE_WORKERS` and `CAFE_NPROC` must be a whole number of at least 1": `CAFE_WORKERS=" 3"`, `"+3"` and `"١٢"` (Arabic-Indic digits) are accepted and read as 3, 3 and 12 (Python `int`).
why it matters: small, but a lab user following the table to the letter looks for text that is not there.

total: 11 findings (0 critical, 1 major, 10 minor)
