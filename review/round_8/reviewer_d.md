# Reviewer D, round 8 (commit 95085cb; cafe/ identical to 0a0509c)

Scope: the readers `cafe/pm/env/{hycom,ocean,orca,tao,bathy,remote}.py`; `report.py`, `credibility.py` against the q8 ledgers; `receipts.py`, `dtmb5415.py`; and test effectiveness of every round-7 fix.

Method.
- Reports: I recomputed from `q8/stage1b/summary.json` and `ingest/tao_compare.json` the verdict counts, the 90 % and 95 % Wilson intervals (k = 15, 0, 60, 55, 64 of 64), `n_certify` = 73, the rule of three 3/64 = 0.046875, the failure-mode shares (22/60, 54/60, 30/60, 12/60; 6/55), the pooled wind RMSE (1.464 m/s, 24.8 deg) and the Richardson numbers of DECISIONS 349 (extrapolations 1.016 to 1.167; +12.4 % against Morrison) from the stored `nest_sphere_100_d{8,12,16}.json`. All agree with the report. Every `#` and `credibility.html#` anchor in `index.html` resolves.
- Test effectiveness: I undid each fix of DECISIONS 341-392 in a scratch copy on homebase (`~/work/cafe/pm_rev8_d`, 1 CPU, container `cafe-pm`) and ran the tests that name it. 150 mutants of the 53 fixes (scripts `scratchpad/rev8/d_mut.py` and `d_mut2.py`: exact old string -> new string, exactly one match each, the tree restored after each; the first run left `report.py` mutated by a kill, so M-11, M-15, M-16, M-20, M-21, M-41 were run again on a clean tree). 8 mutants survived (D-2 a, b, c; D-7; D-8; D-9 a; D-9 b twice); the others failed, each at the assertion the test names (first failing line read for every one). Not counted as findings: M-19 has no code change (its test pins numbers), and the `fly_sitl` call site of M-43 is stated in DECISIONS 383 to be untested.
- Hostile inputs: probes `scratchpad/rev8/d/probe1..5.py` run at 1 CPU on homebase against the clean tree.

Findings are ordered by severity.

### D-1. A lab ocean store passes `ocean_store_present` with any time spacing, two snapshots six days apart included, though docs/RUNBOOK.md:107 says "any regular cadence works"
severity: major
lane: data, honesty
where: cafe/pm/pipeline.py:292-300 (`_ocean_time_problem`), pipeline.py:311 (`_ocean_cached` with `window`); docs/RUNBOOK.md:107; DECISIONS 352
reproduction: in the cafe-pm image, `from cafe.pm import pipeline; import numpy as np; t0 = 1677672000.0; t1 = t0 + 6*86400`:
`pipeline._ocean_time_problem(np.array([t0, t1]), (t0, t1))` returns `None` (covered); so does `np.array([t0, t0 + 6*3600, t1])` (a 5.75-day hole after the second snapshot). An empty array raises a raw `ValueError: zero-size array to reduction operation minimum`, and `np.array([nan, t1])` returns `None`. The function takes `min` and `max` of the times and nothing else. `Ocean` interpolates linearly in time (`grid.interp`), so the ocean current of a glider's whole six days is a straight line between two lab snapshots, with no failed check, no ledger note and no line in the report. Before M-12 (DECISIONS 352) the GOFS 3-hourly membership test at least fixed the cadence; M-12 replaced it for lab stores by coverage only.
why it matters: the glider station-keeping verdict is driven by the current; a lab store that is too sparse (or has a hole) is silently accepted and its verdicts look like any other, and the RUNBOOK claims a "regular cadence" the code never checks.

### D-2. M-23's statistical rule for Results robustness is not pinned by any test: three mutants of the rule pass
severity: minor
lane: statistics, test effectiveness
where: cafe/pm/credibility.py:505-507; tests/test_credibility.py:791-830 (`test_one_sensitivity_among_many_tests_is_not_clearly_above_chance`, `test_a_refit_alone_earns_robustness_two_as_the_printed_rule_says`)
reproduction: scratch copy, run `python -m pytest -q tests/test_credibility.py::test_one_sensitivity_among_many_tests_is_not_clearly_above_chance`; all three pass (rc 0) with these edits, one at a time:
(a) `luck < 0.05` -> `luck < 0.15` (q8 itself is 1 ranked of 3 tests, luck 0.1426, so the edit would give q8 Robustness 2 again);
(b) `0.05 ** i * 0.95 ** (tests - i)` -> `0.1 ** i * 0.9 ** (tests - i)`;
(c) `tests = sum(... noise_floor is not None ...)` -> `tests = len(allv)`.
The undone fix itself (`clear = bool(sens)`) is caught (`assert 2 == 1`), so the test only separates "any ranked parameter" from "some luck test", with luck far from 5 % in its cases.
why it matters: the 5 % level, the per-test level and the count of tests are the whole of M-23; q8's Robustness 1 vs 2 depends on exactly the 0.1426 vs 0.05 comparison, and nothing would notice a change of either.

### D-3. A lab ocean store whose grid is coarser than 0.2 deg can never pass `ocean_store_present`; the failure advice loops
severity: minor
lane: data, robustness
where: cafe/pm/env/hycom.py:669-678 (`_sub` keeps points within box +-0.1 deg); cafe/pm/pipeline.py:311-313 (`_ocean_cached` wants `lat.min <= s + 0.1`, `lat.max >= n - 0.1`, same for lon); pipeline.py:392-395
reproduction: fixture of tests/fixtures/hycom (grid 0.04 x 0.08 deg), every 4th point kept (0.16 x 0.32 deg), `h.ingest_lab_hycom(dir, fx["box"], "c.zarr", "in_situ")` then `pipeline._ocean_cached(z, fx["box"], np.array([]), (tmin, tmax))`: `False`. The store spans lat -0.04..0.12 and lon 180.0..180.32 against the box -0.12..0.12, 179.84..180.48. Every 5th point (0.20 x 0.40) also fails; every 1st and 3rd pass. A grid spacing of more than 0.2 deg cannot meet "within 0.1 deg of the box edge" when the cut keeps only points within 0.1 deg outside it. The run then fails `ocean_store_present` and its `fetch_ocean` raises "which this pipeline cannot download: write it with `ingest-ocean`", which writes the same store again (the M-12 loop, now in space).
why it matters: a coarser lab model (1/4 deg is common for reanalysis) cannot be used, and nothing says why.

### D-4. A lab ocean store whose files do not sort in time order, or repeat a snapshot, is ingested "successfully" and fails later with a raw `ValueError`
severity: minor
lane: robustness, data
where: cafe/pm/env/hycom.py:689 (`sorted(p.glob("*.nc"))`), hycom.py:176-185 (`write_store` appends in that order, checks nothing about time)
reproduction: copy the three fixture snapshots (12:00, 15:00, 18:00) to `snap_0.nc`, `snap_1.nc`, `snap_2.nc` in reverse (so name order is 18:00, 15:00, 12:00): `ingest_lab_hycom` returns the store with times `[1677693600, 1677682800, 1677672000]`; `Ocean(store, None, lab=True)` then raises `ValueError: axis time: must be strictly increasing`. The same snapshot copied twice gives times `[1677672000, 1677672000]` and the same error. `_ocean_time_problem` (min/max) does not notice either, so `ocean_store_present` is green. M-36 refused the all-NaN store "because the failure would show far away"; this is the same kind of failure, not a `ConfigError` and not at ingest.
why it matters: lab file names such as `snap_10.nc` / `snap_9.nc` sort the wrong way; the user gets a traceback in a later stage naming an axis, not the file.

### D-5. The M-5 note prints a false inequality when the finest grid is not converged for a reason other than the drift of the resistance
severity: minor
lane: honesty, documentation
where: cafe/pm/credibility.py:284-288; the rule it reports is cafe/pm/dtmb5415.py:383 (`ok = done >= MIN_ITERS and max(drift, parts) <= DRIFT_TOL and scatter <= SCATTER_TOL`)
reproduction: probe2 case E: copy the q8 data directory's `dtmb5415`, set in `run_fine.json` every speed to `converged: False, drift: 0.001, scatter: 0.5`, `credibility.build(...)`: the four notes end "finest grid not converged (iterative drift 0.001 > 0.005)". A drift of 0.001 is not above 0.005. `converged` is False also when the pressure/viscous drift (`drift_parts`), the scatter, or the iteration count fail; the note names only `drift` and always writes `>`.
why it matters: the credibility page, which exists to be checked, would state a number comparison that is false; with the stored q8 files the three drifts happen to exceed the tolerance, so the page is right by luck.

### D-6. `converged` missing from a DTMB run file counts as converged in credibility, and as a failed check in the receipts
severity: minor
lane: honesty, statistics
where: cafe/pm/credibility.py:284 (`if fine["converged"] is False`), cafe/pm/dtmb5415.py:462 (`converged=seen.get("converged")` may be None), dtmb5415.py:581-585 (a missing drift is NaN and fails its bracket)
reproduction: probe2 case F: delete `converged` from every speed of `run_fine.json`: `credibility.build` marks all four rows judged (`validated True` for Fr 0.10, 0.20, 0.28, 0.41); the receipts for the same files record "iterative convergence, last-quarter drift" as FAIL (NaN) because `drift` is None too. The two statements about one file disagree, and the credibility one is the generous one.
why it matters: M-5's whole purpose is that unconverged rows are not judged; a row with no convergence record is "not known to have converged" and should not count toward Validation 3.

### D-7. M-5: the rule that an unjudged row "does not count toward Validation 3, which needs four judged rows" is not tested (the filter is dead in the tested cases)
severity: minor
lane: test effectiveness
where: cafe/pm/credibility.py:444-446; tests/test_credibility.py:767-776 (`test_validation_three_counts_only_rows_whose_finest_grid_converged`)
reproduction: scratch copy; replace `judged = [r for r in full if not r.get("not_judged")]` by `judged = list(full)`; the test passes (rc 0). An unjudged row has `validated None`, so `all(r["validated"] for r in judged)` is already False for it, and with the DTMB set (three rows plus none) the two codes agree. They differ for four judged valid rows plus one not judged: the code gives 3, the mutant 2. No test builds that case.
why it matters: the sentence in the printed rule ("a row whose finest grid has not converged is not judged") is only true by an accident of `None` being falsy.

### D-8. M-6: the hold-out's fresh-draw loop drops duplicates on the wrong columns without a test noticing
severity: minor
lane: test effectiveness
where: cafe/pm/emulator.py:274 (`df[test].drop_duplicates(self.point_cols)`); tests/test_emulator.py:452-468
reproduction: scratch copy; replace `self.point_cols` by `self.features` in that line; `tests/test_emulator.py::test_the_holdout_splits_on_the_point_columns_so_replicates_with_other_noise_columns_stay_together` passes (rc 0), and so does every test of `fresh` (`test_holdout_report_scores_the_held_out_points_against_fresh_draws_and_stops_at_three` has no replicates with other noise columns). With replicates of one mission that differ in the environment medians, up to `FRESH_POINTS` = 3 "fresh points" would be the same mission three times.
why it matters: the fresh check is the emulator's only honest out-of-sample score; scoring one point three times inflates its apparent count.

### D-9. M-47 and M-41: two bounds and one sentence of the fixes are not tested
severity: minor
lane: test effectiveness
where: cafe/schemas/mission.json:49 (`"lost_after_h": {"exclusiveMinimum": 0, ...}`); tests/test_config.py:628-646 (`test_r7_m47_the_other_bounds_of_r6_m9_are_each_refused_naming_their_field`); cafe/pm/report.py:1081 (the flip line); tests/test_report.py:1998 (`test_the_rendered_report_repeats_no_noun_and_has_no_unit_doubled_by_its_sentence`)
reproduction: scratch copy. (a) Replace `"exclusiveMinimum": 0, "maximum": 720` by `"minimum": 0, "maximum": 720` in `lost_after_h`: the M-47 test passes (rc 0), so `lost_after_h: 0` is accepted. DECISIONS 387 says "`lost_after_h` above 0 ... refused by a test that fails when the bound is loosened"; the upper bound is, the "above 0" is not (a negative value is, 0 is not). (b) Restore the old flip sentence (`f"none of the {_n(f['evaluated'])} evaluated (of ...`) or any other wording: the M-41 test still passes; nothing renders or checks "N candidates evaluated, of M candidates that could be: none reaches ...".
why it matters: DECISIONS 387 claims each bound has a refusing test; for one it does not.

### D-10. The Results-robustness rule gives level 2 when there are no permutation tests at all
severity: minor
lane: statistics, robustness
where: cafe/pm/credibility.py:505-507
reproduction: probe2 cases B and C: remove `noise_floor` from every entry of q8's `stage1b/summary.json` (an older summary, or a hand-edited one) while `glider_eq` still names `current_speed_scale`: `tests = 0`, `range(len(sens), tests + 1)` = `range(1, 1)` is empty, `luck = 0.0`, `clear` is True and the factor is `(evidence 2, level 2)`; with `noise_floor: null` everywhere the same. A ranked parameter without a floor was not a test, and its chance by luck is not 0.
why it matters: the sum is zero for exactly the case it cannot assess; M-23 was written so that Robustness 2 is not handed out on one lucky test.

### D-11. The credibility page says the audit does not run ruff; `make audit` does
severity: minor
lane: documentation, honesty
where: cafe/pm/credibility.py:85 (`LEVEL_TEXT["ms_management"][3]`: "house rules and ruff configured (not run by the audit)"); docs/CREDIBILITY.md:68 ("does not run ruff"); contradicted by cafe/pm/audit.py:283-286 (`_run(["ruff", "check"])`), Makefile:47 and docs/RUNBOOK.md:174 ("banned tokens, ruff, mypy --strict, coverage")
reproduction: `grep -n "ruff" cafe/pm/audit.py Makefile docs/RUNBOOK.md`; the q8 `credibility.json` M&S management level text is "strong: ledger chain audited by the tool; house rules and ruff configured (not run by the audit); no independent reviewer". What the credibility build checks is that `[tool.ruff]` exists; the audit it cites does run ruff. M-23 rewrote the text from "lint checked" to a statement that is false in the other direction.
why it matters: the page that tells the reader what was and was not checked gives the wrong account of the repository's own gate.

### D-12. DTMB receipts pass "|E| <= U_val" for the rows the credibility report declares "not judged"
severity: minor
lane: honesty
where: cafe/pm/dtmb5415.py:572-576 (`rc.bracket(... "|E| <= U_val (ASME V&V 20)" ...)` for every row of `tabulate`, whatever `converged` says); cafe/pm/credibility.py:284-288
reproduction: from the stored `pmdata/dtmb5415/run_*.json` (finest = `fine`, `converged` False at Fr 0.20, 0.28, 0.41): |E| = 7.2e-4, 8.4e-4, 4.0e-5 against U_val = 1.085e-3, 2.653e-3, 1.993e-3, so all three brackets pass in the receipts table, while `credibility.json` marks the same three rows `not_judged` and `validated null`. The table of receipts counts them as passes.
why it matters: the same row is a PASS in one deliverable and not judged in the other; M-5 changed one of them.

### D-13. M-17 does not repair, or reject, an orca cache made by the old code for a window that does not start on the hour
severity: minor
lane: reproducibility, data
where: cafe/pm/pipeline.py:464-470 (`_orca_covers`), pipeline.py:783-786 (`_covers`), pipeline.py:750-759 (`_derived_span_problem`, one hour of slack)
reproduction: reasoning from the code. A cache built before M-17 for a window starting at 12:30 has a manifest `t0 = 12:30` and a time axis labelled 12:30, 13:30, ... holding the 12:00, 13:00, ... files (the 30 minute shift of M-17). Under the new code `hours()` returns 12:00, 13:00, ...; the same window is `_covers(d, t0, t1)` (manifest 12:30 <= 12:30, last >= end), so `orca_covers()` is true, nothing is fetched or reassembled, and `derived.zarr` is accepted by `_derived_span_problem` (it allows an hour). The mislabelled forcing stays in use; nothing in the manifest (no code or layout version) says the cache is old.
why it matters: the fix holds only for a cache built after it; the ledger gives no sign that a run read a shifted atmosphere.

### D-14. The receipts job for bathymetry reads a leftover `.part.npz` as the GEBCO cache
severity: minor
lane: robustness
where: cafe/pm/receipts.py:348 (`glob("gebco2026_*.npz")`); cafe/pm/env/bathy.py:151-152 (`fetch_gebco` writes `<name>.npz.part.npz`)
reproduction: probe3: `CAFE_DATA=<tmp>` holding only `bathy/gebco2026_-7_7_163_197.npz.part.npz` (a killed `fetch_gebco`), then `dict(receipts.jobs())["pm.env.bathy"]()` raises `BadZipFile: File is not a zip file`. M-39's context row ("GEBCO cache not found ... not run") is skipped because the glob matches the partial file; with the real file present too, `sorted()` happens to put the real one first.
why it matters: an interrupted fetch turns the bathymetry receipts into a failing row instead of the "not found" context row M-39 added.

### D-15. A truncated stored wall-model receipt makes every stage-3 window raise instead of being "stale"
severity: minor
lane: robustness
where: cafe/pm/stage3/wallmodel.py:342-354 (`stale_wall_receipts`, `json.loads(f.read_text())`), wallmodel.py:411, 419 (`write_text`, not an atomic replace); called from cafe/pm/stage3/windows.py:316-317
reproduction: probe5: `CAFE_DATA=<tmp>`, write `receipts/wm_flat_plate.json` as `{"cf": 0.0036, "ittc": 0.0039, "re": 1.0e6, "err": 0.0` (a kill during `wallmodel slow`'s `write_text`) and a good channel file: `wm.stale_wall_receipts()`, `wm.stored_wall_error()` and `wm.receipts()` all raise `JSONDecodeError`. M-8 made this function the gate of every window (`run_window` calls it), so one truncated file stops stage 3 with a traceback; the tests cover "not stored", "no code sha" and "other code" only.
why it matters: the gate that M-8 added has no case for a damaged file, the one state a killed 1.8 h run leaves.

### D-16. Sentences of the deliverable read "1 candidates" and "1 notches"
severity: minor
lane: documentation
where: cafe/pm/report.py:340, 353-354 (units "notches", "candidates") with `_txt` (report.py:964-971); q8 `report/index.html`
reproduction: `grep -c "1 candidates" q8/report/index.html` / the text of glider_eq: "What would fix it (GO): 1 candidates evaluated, of 14 candidates that could be: none reaches GO" and the table column "deploy 6 h later 1 notches". M-41 (DECISIONS 381) fixed the doubled noun and left the count's unit unpluralised; its test checks only for repeats.
why it matters: visible wording defect in the one deliverable, in the sentence M-41 rewrote.

### D-17. "The speed model is sampled over 1.4 % only" is a literal, not a number from the prior, and the unit is ambiguous
severity: minor
lane: honesty, documentation
where: cafe/pm/report.py:1005-1008 (`_usv_bias_html`), cafe/pm/credibility.py:485; config/perturbations.yaml `usv_vpp_bias` (lo -0.2565, hi -0.2280)
reproduction: the prior is uniform on [-0.2565, -0.2280]: width 0.0285, half-width 0.01425 in bias, centre -0.2422. The speed factor is 1 + bias = 0.7435 to 0.7720, i.e. 3.8 % wide and +-1.9 % of the flown speed (0.01425 / 0.7578); sd 0.0082 is 1.1 % of the flown speed. "1.4 %" is the half-width in units of the unbiased polar, and it is typed into both modules, so editing the prior (the lab's, say) leaves the sentence unchanged. The perturbations.yaml and DECISIONS 355 also quote "sd 0.8 %" in the same units.
why it matters: a figure in the deliverable that is not computed from the config it describes, in a unit that does not say what it is a fraction of.

total: 17 findings (0 critical, 1 major, 16 minor)
not covered: tests/test_*.py of the other lanes (physics of the USV added-resistance model, M-19 has no code change); `report.py` layout and the map/SVG; stage 3 and CFD content (`stage3/`, DTMB solver runs, `hangar`); `remote.py` and `tao.py`/`bathy.py` were read in full but only the paths listed above were exercised (no network); GPU paths; the full `report` command on a mutated copy of q8 (it needs the 9 GB environment); the RUNBOOK word-for-word run.
