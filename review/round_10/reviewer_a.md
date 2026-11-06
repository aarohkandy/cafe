# Round 10, reviewer A (commit a470119, code of 8b870a6)

Method: the q10 report and ledgers recomputed by hand (Wilson intervals, counts of assumed inputs, the 0.72^6 UAS check, the glider/ship ranges, the TAO prior signs); hostile missions and damaged run directories on orca at 2 CPUs (about 60 mission variants through `load_mission`, three toy `--budget ci` runs on the synthetic environment with one vehicle, 20 vehicles and odd ids, 22 damaged-run-directory cases through `report` and `audit`, 19 CLI argument cases); a read of `stats/`, `emulator.py`, `whatif.py`, `budget.py`, `config.py`, the glider and USV step functions and the prefix diff of 8b870a6. Most of what was attacked held. What did not is below.

### A-1. The emulator coverage gate drops a hold-out coverage of exactly 0.85, the lower edge of its own tolerance, to floating-point dust
severity: minor
lane: statistics
where: cafe/pm/whatif.py:456 (the gate), cafe/pm/whatif.py:461 (the chance figure beside it, which has `+ 1e-12`)
reproduction: `python3 -c "print(abs(17/20 - (1 - 0.1)) <= 0.05, abs(19/20 - (1 - 0.1)) <= 0.05)"` prints `False True`: `abs(0.85 - 0.9)` is 0.050000000000000044, `abs(0.95 - 0.9)` is 0.04999999999999993. `Emulator.score` sets `nominal = 1 - alpha`, so 17 of 20 held-out points covered is judged a miss of "0.90 +- 0.05" while 19 of 20 passes. The first training size, 100 distinct points, gives exactly 20 held-out points, and for a calibrated emulator P(17 of 20) = 0.0898. The sibling line 461 adds `1e-12` and so counts k = 17 as inside: the ledger note then prints "coverage MISSED: 0.850 against 0.90 +- 0.05; a calibrated emulator misses this by chance with probability p" with a p that leaves out the outcome that just happened. `intervals.py` already has `_at_least` for this; no other `abs(...) <=` threshold in `cafe/pm` lacks a tolerance.
why it matters: about one calibrated emulator in eleven at the smallest trainable size is marked unusable (and the flip search falls back to Stage 1) by arithmetic, and the printed chance of that miss is computed on a different rule than the gate.

### A-2. Damaged or unwritable paths end in raw tracebacks (rc 1) where sister cases give a clean `error:` (rc 2)
severity: minor
lane: robustness
where: the `report --run` readers of plan.json (the first plan["gpus"] use after the load) and of stage1b/summary.json (cafe/pm/report.py, `NOT_PRESENT` at :74 is raised as a FileNotFoundError), cafe/pm/__main__.py:159 (`run --out`)
reproduction: on a finished run directory copy `R`: (1) `echo '{}' > R/plan.json; python -m cafe.pm report --run R` -> rc 1, `KeyError: 'gpus'` (a truncated plan.json, `[]` and a missing plan.json all give rc 2 "not a JSON object ... run it again (--fresh)"); (2) `rm R/stage1b/summary.json; python -m cafe.pm report --run R` -> rc 1, a `FileNotFoundError` traceback (its message is fine, `truncated` summary.json gives rc 2); (3) `python -m cafe.pm run --mission missions/tepex_c_demo.yaml --budget quick --out /proc/x` -> rc 1, `FileNotFoundError: [Errno 2] No such file or directory: '/proc/x'`, after the plan is printed.
why it matters: a lab user cannot tell a damaged run directory or a read-only `--out` from a bug; the same family of inputs is already handled elsewhere with the advice to rerun with `--fresh`.

### A-3. A padded box beyond +-90 degrees latitude passes `load_mission`
severity: minor
lane: robustness
where: cafe/pm/config.py:393-396 (`ocean_box(m)` is called "to refuse here the box ingest would refuse"), cafe/pm/pipeline.py `ocean_box`, `cafe/schemas/mission.json` box lat range
reproduction: take `missions/tepex_c_demo.yaml`, set `box: {lon_min: 165, lon_max: -165, lat_min: -90, lat_max: 90, pad_deg: 2}` (deploy points and the ship stay inside) and call `config.load_mission` then `pipeline.ocean_box(m)`: no error, and `ocean_box` returns `(-92.0, 92.0, 163.0, -163.0)`. With `lat_min: 88, lat_max: 89.9` it returns `(86.0, 91.9, ...)`. Likewise `lon_min: -179.9, lon_max: 179.9` (a 359.8-degree strip) is accepted with a padded west/east of `-181.9 / 181.9`, with no size guard before `fetch`.
why it matters: the loader promises the ocean box the fetch would refuse is refused here; latitudes of 92 degrees and a near-global strip go on to the HYCOM request (which fails late or asks for a huge subset) instead of a `ConfigError` naming the pad.

### A-4. A run directory missing `windows/windows.json` renders a report that silently drops the stage-3 markers
severity: minor
lane: honesty
where: cafe/pm/report.py:619-622 and 734-746 (`for vid, ws in (wins or {}).items()`), against cafe/pm/report.py:792 (`NOT_PRESENT` is used for stage 3's own section) and the "not in the run directory" text that `flip.json` and `holdout.json` get
reproduction: copy the toy CI run (`--budget ci`, one USV) to `R`, `rm R/windows/windows.json`, `python -m cafe.pm report --run R` -> rc 0, `traceability_problems: []`. Diffing the text of the page against the intact one: the map loses "usv stage-3 window W1 W1" and its "usv W1: ... at 2 values deg" row, and the environment section loses "usv, significant wave height at the worst windows ... 2.467 m", with no sentence saying the file is missing. Deleting `emulator/flip.json` gives "What would fix it: not available. emulator/flip.json is not in the run directory", and `holdout.json` the same.
why it matters: the three outputs of one kind of damage are treated three ways; the one that matters for "worst windows" says nothing, so a reader sees a report that looks complete.

### A-5. `bin/pmx.sh` runs at 8 CPUs by default and checks no load, against the repository's own "2 CPUs while another agent works" rule
severity: minor
lane: documentation
where: bin/pmx.sh:21 (`--cpus ${PM_CPUS:-8}`, `--memory ${PM_MEM:-28g}` for the docker path), CLAUDE.md "Working beside the lead session" (keep to 2 CPUs), docs/RUNBOOK.md:44 (states the 8 and 28g defaults)
reproduction: `PMX=pm_x bin/pmx.sh python -c 1` without `PM_CPUS` starts `docker run --cpus 8 --memory 28g`; one such default run of the demo mission on the shared server raised its 1-minute load to 8.75 within two minutes (measured by the reviewer by accident). The proot path has `CAFE_MIN_FREE_GB`; the docker path has no load or free-CPU check at all.
why it matters: the file that tells agents to share the box leaves the runner's default at the whole box; one forgotten variable takes the machine from the others.

### A-6. The USV table solver and the direct solver disagree on the apparent wind angle at zero apparent wind
severity: minor
lane: physics
where: cafe/pm/physics/usv.py:369-380 (`through_water_table`) against :336 (`through_water`); consumed at usv.py:629 (`e1["awa"] < P["min_awa_deg"]`)
reproduction: `P = usv.load_platform(); pol, wt = usv.tables(P); h = np.array([0., 90., 180.]); z = np.zeros((3, 2))`; `usv.through_water(P, z, z, h)["awa_deg"]` is `[180, 180, 180]` and `usv.through_water_table(P, pol, z, z, h)["awa_deg"]` is `[180, 0, 0]` (aws is 0 in both). `min_awa_deg` is 15, so at exactly zero apparent wind the table path is inside the bow cone for two of three headings.
why it matters: only at aws = 0.0 exactly (a still wind over a boat at rest), so the verdict is not moved (`wing_stall_calm` fires there too), but `wing_stall_angle` is counted beside it and the mode shares and "first failure mode" of a calm member depend on which solver answered. Low confidence that a real member reaches it.

### A-7. STATUS.md gives the ensemble size as "16 to 512 members by budget"; the budgets run 8 to 16, 32 to 64, 73 to 256 and 73 to 512
severity: minor
lane: documentation
where: STATUS.md:37 (stage 1 row), cafe/pm/budget.py:32-33 (`N_MAX`, `N_MIN`)
reproduction: `N_MIN = {"ci": 8, "quick": 32, "4h": 73, "overnight": 73}`, `N_MAX = {"ci": 16, "quick": 64, "4h": 256, "overnight": 512}`; the toy CI log prints "stage 1: 8..16 members in batches of 16 (cannot certify P(fail) < 5 %)"; the q10 plan has `n_min 32, n_max 64`.
why it matters: the reader of STATUS who runs `--budget quick` cannot reach 73 members and so cannot certify; the budget table that says so is not the one STATUS quotes.

total: 7 findings (0 critical, 0 major, 7 minor)
