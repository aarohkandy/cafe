# Reviewer B findings, round 8 (commit 95085cb; q8 run at 0a0509c)

How the evidence was made. Everything below was run on homebase at 1 CPU in `pm_rev8_b` / `pmdata/rev8_b`, on the synthetic CI environment
(`python -m tests.fixtures.ci_env.make D missions/ci_fixture.yaml`, 16 MB) or on `AnalyticEnv`, never on the shared demo cache, and no full pipeline run was started.
`CAFE_OFFLINE=1 CAFE_DATA=D python -m cafe.pm fetch --mission missions/ci_fixture.yaml --out R [--fresh]` is the ingest stage alone.
Test-quality probes were made on a scratch copy of the repo: 29 one-line mutations of `cafe/pm/stats`, `physics` and `stage1.py`, each run against the one or two test files that name that code. 27 are killed, one survivor is an equivalent mutant (`ks <= 1/n` -> `ks <= 1.0` after `exact` has already been required), and one is B-7.

### B-1. Neither resume nor `audit` ever looks at the contents of a directory input (the ocean store, the orca zarr stores): a changed or damaged store is "up to date" and "audits clean"
severity: major
lane: reproducibility
where: cafe/pm/ledger.py:170 (`done` re-hashes an input only `if ... f.is_file()`); cafe/pm/audit.py:78-88 (`_dir_problems` compares the store's own `manifest_sha256` attribute with the ledger, it hashes no data); cafe/pm/pipeline.py:556-575 (`no_nan_in_sea_cells` reads only the UMWM sea nodes and the WRF fields, never the ocean store); cafe/pm/audit.py:6-8 and BRIEF 5.5 ("every input and output still hashes to what the ledger recorded")
reproduction: (a) CI environment D; run `fetch ... --out R` once (ingest ledger ok). Then `zarr.open(D+'/ocean/gofs_ci_fixture.zarr', mode='r+')['water_u'][...] = 9.0` (9 m/s everywhere). `fetch ... --out R` again prints `ingest: up to date (ledger R/checkpoints/ingest/ledger.json)`. `python -m cafe.pm.audit --ledgers-only R` prints 8 problems and all 8 are `stage X: no ledger` for the stages that were not run: nothing says the ocean input changed. (b) Copy D, delete one chunk file (`rm D2/ocean/gofs_ci_fixture.zarr/water_v/c/2/0/0/0`; the array's fill_value is NaN): `fetch --fresh` exits 0 with `ingest: done`; reading the store gives 1210 NaN values where the intact store has -0.1..0.0; no check names it. (c) Copy D, multiply `U10` and `V10` of `cache/ci_fixture/orca/wrf.zarr` by 3 and run `fetch --fresh`: `derived.zarr` (the surface layer built from the old winds) stays "current" and is used, and the ledger values are digit for digit those of the unmutated store (`coare_ustar_vs_umwm_ust` 1.0, `spectrum_peak_period_vs_file` 0.0604807...).
why it matters: the ledger chain is the claim that a report can be traced to the bytes it was made from; the biggest input (5 GB of ocean) is the one that is not checked, and a half-downloaded or edited store silently becomes a hole or a wrong current for the gliders and the USV.

### B-2. No plausibility gate on the forcing: a wind field 3 times too strong passes every ingest check, and Data pedigree is still scored 2 ("moderate: checked by this tool's own self-checks")
severity: major
lane: data / honesty
where: cafe/pm/pipeline.py:586-589 (`coare_ustar_vs_umwm_ust` is ok whenever n > 0 and the median is finite; no limit), cafe/pm/pipeline.py:655-720 (`_tao` fits and stores the buoy comparison, nothing gates on it), cafe/pm/credibility.py:384-386 (level 2 is granted when all ingest checks passed), cafe/pm/credibility.py:401-405 (the buoy comparison can only add level 3, never remove level 2)
reproduction: CI environment copy with `U10` and `V10` of `wrf.zarr` multiplied by 3, `derived.zarr` deleted so that it is rebuilt from them, `fetch --fresh`. Ledger `ok: true`; check `coare_ustar_vs_umwm_ust`: "918 sampled sea points: median |COARE u* - UMWM ust| / ust = 2.530, 0.0% within 20 %" and `ok: true`; `ingest/tao_compare.json` ALL: speed_bias +10.72 m/s, speed_rmse 10.74 m/s. Nothing fails. credibility.py:384 then gives Data pedigree 2. Single-cell versions also pass: `U10 = 500 m/s` in one cell, `swh = -3` in one cell, `SST = 0 K` for one hour (`_ingest_checks` has no range test on any field). The same run with UMWM `ust` x 0.1 gives `0.0` agreement and `ok: true`.
why it matters: BRIEF 2.1 says an `ust` disagreement "is a finding, not a test to loosen"; here a gross forcing error (a unit slip, a wrong run) goes through to the verdicts with only a line in `tao_compare.json`, and the credibility report calls the data moderate.

### B-3. A cached WRF time axis that is not strictly increasing ends in a raw `ValueError` traceback, and the ingest check named for it cannot fire
severity: minor
lane: robustness
where: cafe/pm/pipeline.py:561 (`ctx.env` is built before any check runs) and :573 (`time_axes_hourly_gap_free`); cafe/pm/env/grid.py:20; docs/RUNBOOK.md troubleshooting row "environment cache file ... cannot be read"
reproduction: CI environment copy, `zarr.open(.../orca/wrf.zarr)['time']`: set element 10 equal to element 9; `fetch --fresh`. Output ends `ValueError: axis time: must be strictly increasing` after a traceback through `s_ingest -> _ingest_checks -> ctx.env -> GriddedEnv.__init__ -> Axis.__init__`; no `error:` line, no ledger check, no file named. The check `time_axes_hourly_gap_free` (BRIEF 5.5: "time axis monotonic and gap-free") can fail only for a gap in a monotone axis, never for the case it is named after.
why it matters: the same troubleshooting row promises a clean message for a corrupt cache; truncated and garbage chunks do get one (checked), this one does not.

### B-4. RUNBOOK step 3 (`make bench`) comes before step 4 (`fetch`), and the stage-1 part of the bench needs the fetched cache: on a clean machine `make bench` fails at its last job
severity: minor
lane: documentation
where: docs/RUNBOOK.md:74 (step 3) and :96 (step 4); Makefile:15-16 (`bench` runs `bench/throughput.py all`); bench/throughput.py:214-216 (`all` = foam, lbm, stage1 in that order) and :170-171
reproduction: read the three places: `all` runs `stage1(mission=DEMO)`, whose `_stage1` does `raise SystemExit("stage1 bench: no environment cache at .../cache/tepex_c_demo; run `python -m cafe.pm fetch --mission missions/tepex_c_demo.yaml` first")` when the demo cache is absent, i.e. after step 1-3 of the RUNBOOK on a fresh machine and after the 10 minutes of OpenFOAM and LBM timing. (The check at :170 comes after the busy-machine refusal at :155; on homebase at load 4.3 the refusal text was what I got, so I did not run the OpenFOAM part.) The step text says it "writes config/throughput.json ... and the stage-1 cost per vehicle class".
why it matters: a lab user following the document word for word ends step 3 with an error and a half-written `throughput.json` (foam and lbm entries, no stage-1 entry), and the planner then keeps using the shipped stage-1 costs (its source line names homebase and 2026-11-01, but nothing says the lab's own bench did not finish).

### B-5. RUNBOOK step 3 rewrites a tracked file, then steps 5-7 need a clean tree; the RUNBOOK never says to commit it
severity: minor
lane: documentation / reproducibility
where: docs/RUNBOOK.md:74-95 (step 3), :213-214 (the golden "on a clean, committed checkout"); Makefile:15-16; config/throughput.json is tracked (`git ls-files config`) and is inside `pipeline.code_digest()` (config/*.*)
reproduction: `make bench` writes config/throughput.json, so `git status --porcelain` is non-empty; the step-1 wrapper `pm()` then passes `CAFE_GIT_DIRTY=1` to every later command, every ledger records `git_dirty: true`, and `acceptance --update-golden` writes a golden whose `source.dirty` is true, which `provenance_problems` (acceptance.py:223-235) rejects ("made from a checkout with uncommitted changes"). Nothing in steps 3-7 says to commit `config/throughput.json` between them.
why it matters: the documented sequence cannot produce a golden that `golden_diff` accepts.

### B-6. `run --seed S` rewrites the saved `mission.yaml` with a regex that only matches `seed:` at the start of a line, so other valid spellings keep the old seed in the copy that `report` and `whatif` reload
severity: minor
lane: reproducibility
where: cafe/pm/pipeline.py:1335-1336 (`re.sub(r"(?m)^seed:.*$", ...)`); cafe/pm/report.py:941 and cafe/pm/whatif.py:675 read the copy
reproduction: `re.sub(r"(?m)^seed:.*$", "seed: 9", text)` leaves `seed : 5`, `"seed": 5` and a JSON-style or flow mapping (`{name: x, seed: 5}`) unchanged, all of which `config._yaml` loads. A mission written that way and run with `--seed 9` runs with 9 (`ctx.mission["seed"]`, in the resume hash) but `runs/<x>/mission.yaml` says 5, so `python -m cafe.pm report --run runs/<x>` prints "seed 5" and `whatif` draws with 5.
why it matters: the report names the wrong seed after a re-render and a what-if answers from a different member set than the run.

### B-7. `stats.sensitivity.default_harmonics` is not pinned by any test in the stats files: `n // 16` -> `n // 8` leaves `tests/test_stats.py` and `tests/test_stats_exact.py` green
severity: minor
lane: statistics / tests
where: cafe/pm/stats/sensitivity.py:15-19 (`return min(6, max(2, n // 16))`); tests/test_stats_exact.py:355 compares `first_order(x, y)` with `first_order(x, y, default_harmonics(len(x)))`, which holds for any definition
reproduction: scratch copy with `n // 16` replaced by `n // 8` in that line; `pytest -q -x tests/test_stats.py tests/test_stats_exact.py` exits 0, and so does `pytest -q -x tests/test_stage1.py tests/test_credibility.py tests/test_report.py` (the tests that print the floor; none pins it) (the other 28 mutations that I tried are each killed by a named test, bar the one equivalent mutant). At 64 members M goes from 4 to 6, which moves the permutation noise floor the report prints (0.118 in q8) and so every "ranked / nothing above the floor" sentence. The docstring and PHYSICS.md 13.4 state the values (2 harmonics at 32 to 47 members, 6 from 96) and DECISIONS 156, but no test states them.
why it matters: `docs/mutation.json` does not exist yet, so this is the first concrete survivor in `cafe/pm/stats`; the 85 % gate will not see it unless it is counted.

### B-8. Verification is scored 2 ("checked by this tool's own self-checks") from the existence of test files, not from any test result
severity: minor
lane: honesty
where: cafe/pm/credibility.py:413-416 (`tests = glob("test_*.py")`; `if not f.problems and tests: lvl = 2`), evidence text "ledger chain audits clean; 49 test files"
reproduction: read the rule; the run never executes or reads the result of a test, so a suite with every test failing scores the same. The rule text printed in credibility.json ("every ledger is clean ... and tests exist") says so, but the level text printed beside it is "moderate: checked by this tool's own self-checks".
why it matters: "49 test files" next to "moderate" reads as a claim about passing tests; it is a claim about file names.

### B-9. A glider member with a non-finite wind (or current) at one surfacing is failed as `no_flight`, a flight-model failure, for the rest of the window
severity: minor
lane: robustness
where: cafe/pm/physics/glider.py:418 (surfaced drift adds `windage * wind`), :425 (`no_flight` is `fly & ~st.ok`); the USV has `no_current_data` for exactly this case (usv.py, round 7 M-16), the glider's FAILS has no such mode
reproduction: `stage1.run_batch` on ci_fixture's gliders with an `AnalyticEnv` subclass whose `wind()` returns NaN: `glider_eq (8, {'no_flight': 8})`, `glider_1n (8, {'no_flight': 8})`, while the USV in the same batch reports `no_current_data`. The position becomes NaN at the first surfacing, the density lookup is then NaN, and the flight model "cannot fly".
why it matters: the report would tell the lab that the glider's flight model failed when the input has a hole; only reachable with a damaged cache, but it is the case B-1 lets through.

### B-10. The emulator's conformal calibration split is by row, the hold-out gate's split is by feature point: replicates of one mission sit on both sides of the production calibration, so the shipped intervals are narrower than the ones the 90 % +-0.05 gate scored
severity: minor
lane: statistics
where: cafe/pm/emulator.py:181-183 (`fit`: `perm = rng.permutation(prim)`, `cal, tr = perm[:n_cal], perm[n_cal:]` over rows) against :263-266 (`holdout_report`: "rows that share it (replicates of one mission) are all on one side"); docs/PHYSICS.md 13.6 and RUNBOOK 5 say replicates of one mission are expected in the table (the base mission is re-run with every new `--seed`)
reproduction: 14 distinct feature points with 3 replicate rows each (42 rows, a base mission run under three seeds), the split of `fit` with `cal_frac=0.2` repeated 2000 times: 98 % of the calibration rows have a training row at the identical feature point (computed with numpy replicating lines 181-183). The calibration score `|y - mu| / sigma` of such a row is the in-sample residual of a GP with a nugget of 0.01, so `q` (the ceil((n+1)(1-alpha))-th smallest score) is too small and `predict` returns intervals that are too narrow; the gate that measures coverage never sees this because it splits by point.
why it matters: the coverage the report quotes (hold-out, by point) is not the coverage of the interval `predict` returns (by row); it is only reachable once the table has 100 distinct points, so no run so far shows it.

### B-11. An unquoted `local_solar_time: 14:00` is read by YAML 1.1 as the integer 840 and `validate` reports "840 is not of type 'string'"
severity: minor
lane: documentation / robustness
where: cafe/pm/config.py:28-53 (`_Loader` refuses octal ints, a repeated key) and :80-86 (`_say` explains an unquoted timestamp and an empty key only); cafe/schemas/mission.json (`local_solar_time` is a string `HH:MM`); docs/RUNBOOK.md:115 (the quoting advice names times, not HH:MM)
reproduction: `yaml.safe_load('local_solar_time: 14:00')` -> `{'local_solar_time': 840}` (YAML 1.1 base-60 integer; `09:30` stays a string, `14:00:00` becomes 50400). Validating the demo mission with that one line unquoted against `cafe/schemas/mission.json` gives `vehicles/3/sorties/local_solar_time: 840 is not of type 'string'` (reproduced with the repo's schema and PyYAML, and by `python -m cafe.pm validate` on homebase; `_say` has no branch for it). The same family: a vehicle `id: no` (or `on`, `off`, `yes`) becomes the boolean False and `validate` prints `vehicles/3/id: False is not of type 'string'` and `links/0/b: False is not of type 'string'`. The shipped demo quotes the value, a lab user writing a new mission will not.
why it matters: the first slip a lab user makes in a sortie block gets a message that names a number the user never wrote; the loader already special-cases the sibling YAML 1.1 traps (octal, duplicate keys, timestamps).

### B-12. A truncated or garbage `ledger.json` makes resume and `audit` crash with a raw `JSONDecodeError` traceback instead of rerunning the stage or reporting a problem
severity: minor
lane: robustness
where: cafe/pm/ledger.py:162 (`done`: `json.loads(p.read_text())`, unguarded); cafe/pm/audit.py:110 (`ledger_problems`: same); contrast cafe/pm/__main__.py `_json_object` and orca.read_json, which round 7 (M-34) made tolerant for `plan.json` and the manifests
reproduction: run `fetch --out R` on the CI environment, then `head -c 200 R/checkpoints/ingest/ledger.json > t && cp t R/checkpoints/ingest/ledger.json`. `fetch --out R` again ends `json.decoder.JSONDecodeError: Unterminated string starting at: line 6 column 17 (char 199)` (exit 1, traceback through `pipeline.run -> ledger.done`), and `python -m cafe.pm.audit --ledgers-only R` ends in the same traceback (exit 1) instead of an `AUDIT FAIL: ... ledger.json is not valid JSON` line. The RUNBOOK troubleshooting table lists the truncated `plan.json` family ("not a JSON object ... rerun with --fresh") but not the ledgers.
why it matters: a ledger is the one file a killed or full-disk run is most likely to leave half written (the stage's own `tmp + os.replace` protects only its own write), and the audit exists to say what is wrong with it.

total: 12 findings (0 critical, 2 major, 10 minor)
