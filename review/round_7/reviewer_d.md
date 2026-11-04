# Round 7, reviewer D: data readers, report, credibility, receipts, DTMB 5415, test effectiveness of the round-6 fixes

Commit reviewed: `62a3b81` (code of `c59c449`/`8dc0ffc`). Scope: `cafe/pm/env/{hycom,ocean,orca,tao,bathy,remote}.py`, `report.py`, `credibility.py`, `receipts.py`, `dtmb5415.py`, and whether each round-6 fix (M-1..M-26, DECISIONS 308-340) has a test that fails when the fix is undone.
All reproductions ran on homebase in my own directories `pm_rev7_d`, `pm_rev7_d_m`, `pm_rev7_d_scr` at 1 CPU (cafe-pm image, `pmdata` mounted read-only); nothing in the repo was edited.
My scripts are in `/private/tmp/claude-501/-Users-aaroh--claude-spares-spare-P6utrU/96cd665b-6853-40e7-8769-780fbfcaeebd/scratchpad/rev7/d/` (`a1.py`..`a4.py`, `test_rev7_d1..4.py`, `mutrun.py`, `mutrun2.py`, `mutation_results.txt`).

Mutation result in one line: 111 mutants of the round-6 fixes ran (a further 3 patterns did not match), each against the tests that name the fix (`mutation_results.txt`); 99 were killed and 12 survived. Of the 12, 8 are D-6 and D-7 (M6d/X6d, M9a, M9d, M9f, X9j, X9k, X9l), 1 is D-17's boundary (X15b), and 3 are equivalent or not mutants of the fix (M13c, X7f, X5c). Killed: every mutant of M-1, M-2 (11 incl. the re-plan), M-3, M-4, M-5 (the pipeline guard), M-7, M-8, M-10, M-11, M-12, M-13 (3 of 4), M-14, M-15, M-16, M-17, M-18, M-19, M-20, M-21, M-22, M-23, M-24, M-25, M-26.

---

### D-1. `fetch_gofs` reuses downloaded parts cut to another box: a changed box either never refetches or silently mixes boxes
severity: major
lane: data, reproducibility, robustness
where: cafe/pm/env/hycom.py:319-320 (old manifest loaded, `box` overwritten with no comparison), 328-330 (a part is skipped when only its hash matches), 363-390 (`assemble_gofs` concatenates every part in the manifest); cafe/pm/pipeline.py:286-295 (`_ocean_cached`), 370-374
reproduction: part names are `<dataset>_<start>_<end>.nc` only; nothing in them or in the skip rule says which box they were cut to. `orca.py:284-298` (`cut.json`) and `tests/test_orca.py::test_the_manifest_records_the_box_and_a_changed_box_refetches_every_part` protect exactly this for orca; GOFS has no such guard. With the stand-in server of `tests/test_hycom.py` (file `test_rev7_d1.py`, run `python -m pytest -q -s tests/test_rev7_d1.py -k stale`):
(a) box A (lon width 0.32 deg), one step, `fetch_gofs`; then box B (the fixture box, 0.64 deg) over three steps into the same directory: the store's step 0 has 46.8 % NaN in `water_temp`, the truth has 2.4 %; steps 1 and 2 are fine. `_ocean_cached` then passes (it checks only the union of the axes), so the run goes on with an ocean that has NaN holes at the first step. (Xarray printed `FutureWarning: ... join='outer' ... will change` at hycom.py:376; this outer join is what builds the holes; see D-18.)
(b) fetch box A, then ask for a box one degree larger on every side with the same window: 0 requests are made (all 6 parts "hash match"), the manifest box is rewritten to the new box, and the store keeps the old extent. `pipeline._ocean_cached` is False again, `fetch_ocean()` returns normally, so `_need` keeps `note = what` and the failed check `ocean_store_present` reads only "the ocean store gofs_X.zarr for the box and window"; every rerun repeats it. The only way out is to delete `<store>.parts` by hand, which nothing says.
why it matters: editing `box` or `pad_deg` after a first fetch (the advice printed for `left_data`: "widen box or pad_deg and rerun") either wedges the run or lets it continue on an ocean with holes.

### D-2. A lab HYCOM store with a cadence coarser than 3 hours can never pass `ocean_store_present`; the documented lab route loops
severity: major
lane: data, robustness, documentation
where: cafe/pm/pipeline.py:293 (`np.isin(steps, ds.time.values).all()` with `steps = hycom.gofs_steps(...)` at :366), 383-386 (the hint), cafe/pm/env/hycom.py:656-684 (`ingest_lab_hycom` writes whatever times the lab files have); docs/RUNBOOK.md step 4 says nothing about cadence
reproduction: `a2.py` (run `python a2.py` in `pm_rev7_d`): lab per-snapshot netCDF files at 12Z and 18Z (6-hourly) ingested the documented way with `ingest_lab_hycom`; store times are `[0, 6]` h, the pipeline wants GOFS steps `[0, 3, 6]` h, `pipeline._ocean_cached(out, box, steps)` returns False. In `s_ingest` that means `fetch_ocean()` raises "is the lab's HYCOM, which this pipeline cannot download: write it with ingest-ocean", the check `ocean_store_present` fails with that text, the user runs `ingest-ocean` again and gets the same failure. Daily or 6-hourly archv output (common) cannot be used; an hourly store passes only because it is a superset.
why it matters: the lab HYCOM route (BRIEF 2.8, RUNBOOK 4) is the one the lab will use, and its only precondition (3-hourly stamps on the 00Z grid) is written nowhere; the loop gives no hint.

### D-3. A mission box that crosses 0 deg E validates, then `fetch`/`run` end in a bare `ValueError` traceback
severity: major
lane: robustness
where: cafe/pm/env/hycom.py:68-77 (`box360` refuses a box across 0/360 E), cafe/pm/pipeline.py:205-209 (`ocean_box`), :364 (`bathy.cache_path(sbox, ...)` is outside every `try`), cafe/pm/config.py (no check); no document mentions the limit
reproduction: `sed` the demo into a box of lon -15..15 with the vehicles at -5 and 0 (`prime.yaml` in my scratch dir), then in `pm_rev7_d`: `python -m cafe.pm validate --mission prime.yaml` prints `prime.yaml: valid (4 vehicles, 4 links)`; `CAFE_OFFLINE=1 python -m cafe.pm fetch --mission prime.yaml` ends in `ValueError: box (-7.0, 7.0, -17.0, 17.0) crosses 0/360 E; GLBy longitudes start at 0, so fetch it as two boxes` with a traceback from `bathy.cache_path`. The CLI has no way to "fetch it as two boxes".
why it matters: same class as round 6's M-11 (validates, then a bare traceback); BRIEF 5.6 asks for odd but valid inputs, and `validate` is where the limit belongs.

### D-4. The report stage dies with `OutsideData` when a vehicle's median track leaves the downloaded data, i.e. in the very case its own text explains
severity: major
lane: robustness, honesty
where: cafe/pm/report.py:712 (`env.wind(lo, la, 10.0, t)`, `env.waves`, `env.current` on the median track, no handler; `_reach` has a try/except, `_env` has none), cafe/pm/pipeline.py:1270 (`report.write(..., env=ctx.env)` is not inside `_lenient(ctx.env)`; the strict environment is the default, environment.py:59)
reproduction: `test_rev7_d3.py` (`python -m pytest -q -s tests/test_rev7_d3.py`) builds `res` for one USV whose members (median) are at lon -150 while the cached box is -167.1..-162.9, and calls `report._env(...)` with the real `GriddedEnv` of `ci_full`: `cafe.pm.env.environment.OutsideData: WRF U10: (-150.000, 0.000) ... is outside the ingested data ... re-run cafe fetch with a larger box or window`. In a run this is the last stage, after hours of stage 1, 1b and the emulator. `_median_track` is the nanmedian over members, so it is outside as soon as more than half of the members have left (`left_data`), e.g. a 30-day window (pad capped at MAX_PAD_DEG 10 deg, pipeline.py:192) or a small `pad_deg`.
why it matters: the report that says "N members left the downloaded data: widen box or pad_deg and rerun" (report.py `_drivers_html`) cannot be produced exactly when most members left; the verdicts exist but the stage and so the run fail.

### D-5. The credibility V&V 20 table and the Validation/Verification evidence hide that every DTMB row rests on the Fs = 3 fallback and that three of the four finest-grid cases did not converge; STATUS.md also leaves out Fr 0.20
severity: major
lane: honesty, documentation, validation
where: cafe/pm/credibility.py:152-165 (`_dtmb_rows` writes the fixed note "U_D and U_input are assumed ...; the free surface is held at the static draft" and ignores `converged` and the discretization note), :88 (`UVAL_MAX_FRAC = 0.5`), :431-439 (Verification level 3 evidence "a two-grid GCI sets U_num"); cafe/pm/dtmb5415.py:292 (`INFORMATIVE = 0.10`), :507-530 (`tabulate`); STATUS.md:64
reproduction: `~/work/cafe/pmdata/dtmb5415/run_{coarse,medium,fine}.json` (the files behind q7). C_T x1e3 coarse/medium/fine: Fr 0.10 4.720/4.430/4.885, Fr 0.20 4.502/4.422/4.672, Fr 0.28 4.814/4.452/5.072, Fr 0.41 6.620/6.184/6.630. In all four the middle value is the lowest, i.e. the grid sequence oscillates, so `discretization` takes the "Fs = 3, p = 2 assumed: oscillating" branch for every row (the three-grid Celik GCI is used for none), and U_num at Fr 0.28 is 0.0027 = 53 % of C_T. `converged` of the fine grid: Fr 0.10 True, Fr 0.20 False (drift 0.0075 against DRIFT_TOL 0.005), Fr 0.28 False (0.053), Fr 0.41 False (0.049). `q7/report/credibility.json` `vv20[0..3].note` carries neither fact, and the table prints "yes" for |E| <= U_val at Fr 0.41 (ratio 0.02) without them. `credibility.html` contains no "oscillat" and no "converge" in the V&V rows. STATUS.md:64 says convergence "fails at Fr 0.28 and 0.41 on every grid"; the files show Fr 0.20 failing on the medium and fine grids as well. Two "informative" thresholds disagree: dtmb5415 requires U_val / D <= 0.10 (DECISIONS 125: wider "claims nothing"), credibility counts a row as informative below 0.5 (DECISIONS 184), so Fr 0.10 (0.47) is "informative" in the table.
why it matters: STATUS.md states the study does not validate the model, but the credibility report the lab reads shows four "yes" rows with no sign of it; the known-limitations list (L12) is about GCI values from before an old fix, not about this.

### D-6. Round-6 tests that still pass with the M-9 range fix undone: five of the seven new bounds have no refusing test
severity: minor
lane: test effectiveness
where: tests/test_config.py:527-541 (`R6_M9`), cafe/schemas/mission.json:48-59
reproduction: in the scratch copy `pm_rev7_d_m` change one schema bound and run `python -m pytest -q tests/test_config.py -k r6_m9`: all 12 pass for `launch_rules.max_mean_wind_ms` maximum 60 -> 6000 (M9a), `lost_after_h` maximum 720 -> 7200 (M9d), `track_tolerance_km` maximum removed (M9f), `lost_after_h` exclusiveMinimum 0 -> minimum -5 (X9j), `track_tolerance_km` exclusiveMinimum 0 -> minimum -5 (X9k), `no_gust_front_within_min` maximum 1440 -> 144000 (X9l). `R6_M9` refuses a negative and a zero max wind, a negative gust window, a dive of 1e6 m or 1 mm, a radius of 1e-9 and 1e9 km, duplicate and unsorted altitudes; `test_r6_m9_the_edges...` only shows that 60, 720 and 1000 are accepted. DECISIONS 316 states all of these ranges. (The other mutants of M-9, the platform dive range and radius/dive/gust lower bounds, are killed.)
why it matters: DECISIONS 316 says each bound is checked; a typo of two orders of magnitude in a wind limit or a lost-after time still loads.

### D-7. The lock in `Emulator.append` has no test: removing it leaves the whole emulator and what-if test files green
severity: minor
lane: test effectiveness
where: cafe/pm/emulator.py:129 (`with locked(self.path):`), tests/test_emulator.py, tests/test_whatif.py
reproduction: in `pm_rev7_d_m` replace `with locked(self.path):` by `with __import__("contextlib").nullcontext():` and run `python -m pytest -q tests/test_emulator.py tests/test_whatif.py -k "append or lock or concurrent or three_processes or add_rows"`: 5 passed (X6d). The same change in `whatif.py:332` (`add_rows`) is killed by `test_three_processes_adding_rows_to_one_table_lose_none_and_never_corrupt_it`. DECISIONS 313 says both `add_rows` and `Emulator.append` hold the lock; only the first is tested (`Emulator.append` has no caller outside tests in `cafe/pm`).
why it matters: half of a stated fix is unpinned.

### D-8. A window that does not start on the hour reads the hour's files but labels them with the minute: a constant time shift of all WRF and UMWM forcing
severity: minor
lane: data, numerics
where: cafe/pm/env/orca.py:77-83 (`stamp` truncates the minutes, `hours` keeps them), :305, :318, :323 (time axis from `ts`), cafe/schemas/mission.json:8 (the time pattern allows any minute and second); cafe/pm/config.py checks only that the end is after the start
reproduction: `python a1.py`: `orca.hours(2023-03-01T12:30, 2023-03-01T16:30)` gives axis 12:30, 13:30, ... for files `..._12:00:00`, `..._13:00:00`, ...; `wrf_hour` compares `Times` with `stamp(t)` (also truncated), so no check notices. A mission with `start: "2023-03-01T12:30:00Z"` validates and gets forcing that is 30 minutes late with no flag; the GOFS side (`gofs_steps`) rounds up to the 3-hourly grid separately.
why it matters: a quiet half-hour error in wind and waves for every member; also `hours` drops the last partial hour.

### D-9. After one failed part, `orca.ingest` still runs every remaining part to completion and throws their results away, while the error text says the finished parts are kept
severity: minor
lane: performance, robustness
where: cafe/pm/env/orca.py:274-280 (`for fu in cf.as_completed(fut): _save(..., fu.result())` inside `with ThreadPoolExecutor`), cafe/pm/pipeline.py:280 (`note = ... parts already fetched are kept, rerun ... to resume`)
reproduction: `python a1.py` (second half, 10 jobs, 2 threads, job 1 raises): the exception reaches the caller after 1.0 s, with 9 of 10 jobs run to completion inside the `with` exit, none of which was saved. For an ingest the jobs are 290 hourly byte-range fetches: a transient failure at job j (after the retries of `remote._open`/`_read`) costs the whole tail of the queue in time and bandwidth and loses it; only parts completed before the failed future was iterated are on disk.
why it matters: "resumes where it stopped" is true only of the parts that happened to finish first; `cancel_futures=True` on the failure path would make it true.

### D-10. The GEBCO cache receipts read a file name nothing in the pipeline writes
severity: minor
lane: documentation, honesty
where: cafe/pm/receipts.py:338 (`d / "bathy" / "gebco2026_tepex_c.npz"`), cafe/pm/env/bathy.py:169-172 (`cache_path` names it `gebco2026_<s>_<n>_<w>_<e>.npz`, e.g. `gebco2026_-7_7_163_197.npz`)
reproduction: `grep -rn gebco2026_tepex_c cafe docs Makefile bench` finds only receipts.py. On homebase `~/work/cafe/pmdata/bathy/` holds both names as one hard-linked file (made by hand); a lab user who has only run `fetch` has the long name, so `gebco.exists()` is False, `bathy.receipts(cache=None)` records only the linear-field row, and the "GEBCO cache hash" and "deepest node vs -elevation" rows (the two in `runs/receipts.json` today) disappear with no context row saying so. `url` is never passed, so the third receipt (per-row byte-range read against the h5py hyperslab, the only check of `_rows`) is never in the table either.
why it matters: the receipts table the report cites silently loses the check of the bathymetry raster on any machine but homebase.

### D-11. `Ocean` throws away `inside`: outside the store in space or time the nearest edge value is returned with no flag
severity: minor
lane: numerics, data
where: cafe/pm/env/ocean.py:66-68 (`v, _ = interp(...)`), cafe/pm/env/environment.py:149-160 (`inside()` tests the WRF box, the time span of WRF and the bathymetry grid, not the ocean store)
reproduction: `test_rev7_d4.py`: on the `ci_full` ocean, `current()` at the store's last node returns [0.0062, 0.0936]; the same values come back 12 h after the last step and 3 deg east or north of the store. The GOFS store ends at the last 3-hourly step <= window end and starts at the first step >= window start (`gofs_steps`), and `_ocean_cached` lets its edge sit up to 0.1 deg inside the box; a window starting at 13:00 reads the 15:00 current for 13:00-15:00 without a flag.
why it matters: small for the demo (aligned window), but it is the one environment layer without the `inside`/`left_data` accounting that the atmosphere has.

### D-12. The M&S-management level 3 text claims lint was checked; the code only looks for the string `[tool.ruff]`
severity: minor
lane: honesty
where: cafe/pm/credibility.py:85 (`LEVEL_TEXT`: "house rules and lint checked by the tool's own audit"), :518 (`"[tool.ruff]" in pyproject.toml`, `docs/BUILDERS.md` exists)
reproduction: read the condition; running ruff is not part of it, nor is any check that BUILDERS.md's rules hold. q7 prints "ms_management 3: ledger chain audits clean; house rules and ruff configured".
why it matters: "3 of 4, strong ... checked by the tool's own audit" is stronger than the evidence ("configured").

### D-13. The Results-robustness level 2 of q7 rests on a sensitivity the same report calls consistent with chance, and the printed rule differs from the code
severity: minor
lane: honesty, statistics
where: cafe/pm/credibility.py:481-484 (`if sens or refit: lvl = 2`), :110-111 (the rule: "2 and first-order sensitivities exist for a vehicle or link with both outcomes")
reproduction: q7 `credibility.json`: robustness evidence "sensitivity indices for ['glider_eq']". That is `current_speed_scale` S1 0.1239 against a noise floor of 0.118 (difference 0.006), and the glider_eq card says "one in twenty unrelated outcomes would also clear it, and the report makes 3 such tests" (three tests at 5 % give a 14 % chance of one clearing by luck). Separately, `or refit` lets a refit alone give level 2 where the printed rule needs the sensitivities.
why it matters: the credibility table and the verdict card give opposite readings of the same number; the printed rule is not the executed one.

### D-14. Report wording defects visible in the deliverable
severity: minor
lane: documentation
where: cafe/pm/report.py:950-957 (`_txt` appends the unit to every number), :1423 (`_assumed_html`: "{_n(a['total'])} inputs are assumed"), :1156 (`Depends on {_n(v['assumed_platform_inputs'])} assumed platform inputs`)
reproduction: `q7/report/index.html`: "261 inputs inputs are assumed or are priors", "Depends on 21 inputs assumed platform inputs", "none of the 1 candidates evaluated (of 14 candidates )", "Median waypoints flown per sortie: 8 of 8" next to "share ... 0.7192".
why it matters: the unit text is appended by the number node and again by the sentence.

### D-15. A z-level lab netCDF with depth listed deepest-first ingests "successfully" as an all-NaN ocean
severity: minor
lane: data, robustness
where: cafe/pm/env/hycom.py:488-499 (`zc` is only checked for negative values), :505-515 (`_to_levels` assumes ascending `zc` with `searchsorted`)
reproduction: `python a3.py`: the fixture's z-level file with its depth dimension reversed: `ingest`-side `read_lab_netcdf` returns `water_temp` with NaN share 1.0 (the same file in order: 0.024) and a descending depth axis; no error, no warning. The store is written; `Ocean` later fails in `Axis` ("must be strictly increasing", a raw `ValueError`).
why it matters: the ingest has no post-write check that the store holds data; the failure shows up far from the cause.

### D-16. A part that downloaded but is unusable is recorded by hash and never fetched again, and the error does not say to delete it
severity: minor
lane: robustness
where: cafe/pm/env/hycom.py:324-349 (success = the child's exit code, the file starts with a NetCDF magic), :363-385 (`assemble_gofs`), :384 (message "rerun fetch_gofs")
reproduction: `test_rev7_d2.py -k empty_part`: the stand-in server answers one dataset with a valid NetCDF that has no time step; the first run fails in `assemble_gofs` (`OSError: NetCDF: Unknown file format` or, for a readable file, "N GOFS steps are missing ... rerun fetch_gofs"); after the server is fixed the rerun makes 0 requests (hash matches the manifest) and fails the same way.
why it matters: the advice in the message cannot work; the part has to be deleted by hand.

### D-17. The rule-of-three note at n = 60 reads "P(fail) < 0.050 ... below 5%"
severity: minor
lane: statistics, documentation
where: cafe/pm/stats/intervals.py:119-123 (`if n < r3` with `r3 = ceil(3 / level) = 60`)
reproduction: `python a4.py`: `verdict(0, 60)["note"]` = "the one-sided rule of three gives P(fail) < 3/n = 0.050 at 95% confidence (n = 60), below 5%; ..."; at n = 59 it correctly says 60 members are needed "to reach 5%". (The exact one-sided bound at 60 is 0.0487; the sentence is about the approximation it quotes.) The M-15 boundary at 60 has no test (`X15b` survives).
why it matters: a number printed as 0.050 cannot be "below 5%".

### D-18. `assemble_gofs` depends on xarray's deprecated outer-join default
severity: minor
lane: robustness
where: cafe/pm/env/hycom.py:376 (`xr.concat([...], dim="time")`)
reproduction: every `tests/test_hycom.py` fetch test prints `FutureWarning: In a future version of xarray the default value for join will change from join='outer' to join='exact'` (xarray 2026.9.0 is the pinned one). Today the outer join is what lets D-1(a) build a store with NaN holes; after the change the same input would be a `ValueError` out of `assemble_gofs`.
why it matters: an environment upgrade changes the behaviour of the ingest without a code change.

---
Equivalent or rejected mutants (not findings): `M13c` (strict against non-strict inequality at an exactly equal endpoint), `X7f`, `X5c` (my mutants were behaviour-preserving), `M18_L19_table`, `M26d`, `X22c` (patterns did not match; `M26d` was rerun as `X26d` and killed).

total: 18 findings (0 critical, 5 major, 13 minor)
