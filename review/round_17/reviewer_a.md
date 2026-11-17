# Round 17, reviewer A

Scope done: mutants of round 16's fixes (DECISIONS 884 to 912) run on orca (proot, 1 CPU each, two at a time, detached copies of `ad7fb0d`, own directories `pm_rev17_a`, `pm_rev17_a2`, `pm_rev17_a3`), each against the regression tests the DECISIONS row names; then 50 DECISIONS rows no reviewer_a of rounds 12 to 16 listed, read against code.

Mutants: 56 (the main set) plus 18 comms (P.526) and 18 of other fixes were scheduled; 56 + 18 finished. Result of the 74: 59 killed, 15 survived the tests named for them (below). Orca became unreachable (ssh timeout) before the reruns of the survivors against wider test selections could finish, so every "survived" below is "survived the named tests"; M20a, M20b, M23c, M23d, M10b, M10f, M10h, M28b, M29c, M3a and M3c were queued for a rerun against the wider files and did not run.

## Mutants of round 16's fixes: killed

M-1 (priors passed to the what-if's Stage 1: both edits), M-2 (same-wind baseline, `base_3d`, the CLI note), M-3 (`hull_note` in flip.json, report text), M-4 (half-integer median), M-5 (scrub counts, three), M-10 (solar factor in the energy gain, p10, `n_empty`, positivity check, acts on, `solar_scale` wired from the draw, battery-margin paragraph), M-11 (unwrap, wrap-back), M-27 (NaN is lost link, NaN is no margin), M-29 (`+ 60`, `sortie_t_max`, the guard itself), M-28 (BadZipFile), M-25 (non-finite speed factor), M-9 and M-8 texts, M-26 (flat mesh, direction check before the case), M-23 (recipe in the key), S1 writers (`O_EXCL`, mode `0o600`, `fchmod`, symlink refusal, `realpath`), S2 (child temporary), M-24 locks (non-blocking flock, ocean store lock, GEBCO lock, wait message, `wait()` call, reentrancy discard, mkdir of the lock directory), M-22 (six: unknown position reads no sea, manifest box of four, move as wide as the box, duty above 0, six depths, sub-daily start), M-14 comms constants (X constant 2.188 to 2.2, F offset, G coefficient 17.6, h_req constant, a_em factor, the transition term, the 1 m range floor, antennas at or below the surface).

## Mutants that survived the tests named for them

Surviving in the sense of the tests named in DECISIONS; the reran-wider selection did not finish (orca unreachable), so a survivor may be killed by an older test.

### A-1. The what-if candidate's hull note takes its depth from nothing the test checks: `* duty` and `min(depth, rating)` can both be dropped
severity: minor
lane: tests
where: cafe/pm/whatif.py:696, cafe/pm/report.py:480 (`depth = min(float(depth_m), float(P["rating_m"]))`); tests/test_round16_report.py:141-150
reproduction: on orca, `PM_HOST=cafe-orca PM_RUNTIME=proot PMX=pm_rev17_a PM_CPUS=1 bin/pmx.sh python -m pytest -q -x tests/test_round16_report.py::test_a_dive_candidate_deeper_than_the_collapse_depth_is_offered_with_the_note_and_the_others_without tests/test_round16_report.py::test_a_fix_row_carries_the_note_that_its_dive_is_deeper_than_the_hull_can_fly tests/test_round16_report.py::test_a_missing_collapse_figure_says_the_check_was_not_made`, with (a) report.py:480 as `depth = float(depth_m)`: 3 passed; (b) whatif.py:696 as `report.hull_depth_note(v["platform"], v["task"]["dive_depth_m"])` (no `* c["mod"]["duty"]`): 1 passed (the test asserts only "could not fly" for the 712.5 m candidate, never the figure; `hull_depth_note("seaglider", 1500.0)` saying 1000 m is pinned by no test).
why it matters: with (b) the note beside "dive 25 % shallower (950 m to 712.5 m)" would say "could not fly 950 m", and a candidate that the shallower dive would make flyable would be marked unflyable; nothing fails.
wrong data: no (the code as shipped is right; the figures printed are 712.5 and 475 m)

### A-2. `test_r16_m20_...` tests PyYAML, not the fix it is named for
severity: minor
lane: tests
where: tests/test_stage3.py:1028 (the test DECISIONS 908 names); the fix is cafe/fea.py `last == "value"` and `_BLANKS`
reproduction: the test body is `assert yaml.safe_load(text)[...]["value"] != 70`; it never imports `cafe.fea`. On orca, `-k r16_m20` with (a) `if last == "value":` as `if False:` in cafe/fea.py, (b) `_BLANKS = " \t"` as `_BLANKS = None`: 5 passed in both. The behaviour is held only by the added rows of `test_r15_l0_4_the_hull_mesh_reading_never_returns_a_number_pyyaml_does_not` (not run against these two mutants: orca went away before the rerun).
why it matters: the row names a test that passes on broken code.
wrong data: no

### A-3. USV table cache: the atomic write is not held by the round 16 test
severity: minor
lane: tests
where: cafe/pm/physics/usv.py:479; tests/test_round16_a.py:236
reproduction: `-k` the one test `test_a_cut_or_foreign_usv_table_cache_is_rebuilt_and_written_whole` with usv.py:479 as `np.savez(f, **tab)`: passes. (The sweep `test_p_r15a_3_every_npz_the_app_writes_goes_through_write_with_or_is_named_here` would probably catch it; not run against it.)
why it matters: the named test does not prove the write is the temporary-and-replace.
wrong data: no

### A-4. `cfd.cached` hit path: the value returned on a hit is not asserted by the round 16 tests
severity: minor
lane: tests
where: cafe/cfd.py:60 (`return json.loads(f.read_text())["result"]`), :56 (`sort_keys=True` in `recipe`); tests/test_cfd.py:51-76
reproduction: `tests/test_cfd.py -k r16_m23` with cfd.py:60 as `return json.loads(f.read_text())`: passed (the tests read `runs(stl)[1]`, the "computed" flag, on a hit, and the wrapper dict `{"recipe","nproc","result"}` would be returned to callers); with `sort_keys=False` in `recipe()`: passed. Rest of tests/test_cfd.py not run against them.
why it matters: the file format changed in this round, and the reader of it is not pinned by the tests written for the change.
wrong data: no

### A-5. fly_sitl's turbulence-cover check is not tested
severity: minor
lane: tests
where: cafe/pm/physics/uas.py `_turbulence_covers(turb, max_s if max_s is not None else sortie_t_max(so))` in `fly_sitl`
reproduction: `tests/test_round16_a.py::test_a_turbulence_series_shorter_than_the_longest_flight_is_refused_and_one_that_covers_it_is_not` with the `fly_sitl` line as `_turbulence_covers(turb, so["duration_s"])`: passed (the test exercises `fly_sortie` only; the SITL binary is not on the worker).
why it matters: half of M-29's "fly_sortie and fly_sitl refuse" is untested.
wrong data: no

### A-6. USV `soc_min` initial value, solar sensitivity wiring: survived the usv test and the round 16 report test
severity: minor
lane: tests
where: cafe/pm/physics/usv.py:560 (`self.soc_min = self.soc_wh / P["battery_wh"]` as `np.full(M, 1.0)`), usv.py:689 (`np.minimum(self.soc_min, ...)` as plain assignment), cafe/pm/stage1.py:45 (`"solar_yield_scale"` out of `ACTS['usv']`)
reproduction: `tests/test_round16_a.py::test_a_usv_with_less_sun_reaches_a_lower_state_of_charge...` passes with usv.py:689 as `self.soc_min = self.soc_wh / P["battery_wh"]` (the last state of charge, not the lowest) and with :560 as 1.0; `tests/test_stage1.py` usv test and the test_round16_a prior test pass with `ACTS['usv']` without the column. The wider `-k usv` rerun did not finish.
why it matters: the headline new number ("lowest state of charge", q17: 0.7356 / 0.7307 / 0.7254) is the one a mutant can turn into the final state of charge with the named tests green.
wrong data: no

### A-7. P.526 implementation: three constants move with the Fock tolerance and the five pinned values
severity: minor
lane: physics, tests
where: cafe/pm/physics/comms.py `_p526_f` (exponent `1.425`), `_diffraction_beyond_db` (`0.36` in K), `smooth_earth_diffraction_db` (`np.maximum(beyond, 0.0)`)
reproduction: `tests/test_round16_a.py tests/test_comms.py` pass with (a) `** 1.425` as `** 1.4` (the F(X) branch for X below 1.6), (b) `k = 0.36 *` as `0.30 *`, (c) `np.maximum(beyond, 0.0)` removed. The first two are inside the 2.8 dB tolerance of the five pairs; the third matters only where the loss formula goes negative beyond the horizon. Per DECISIONS 913 the five pairs are all that is checked, which is the claim here: the tests do not distinguish the recommendation's constants from nearby values.
why it matters: "pins the formula" (the test's docstring: a change of any constant or branch moves one of them) is not true for these three.
wrong data: no

### A-8. An `_run_bellhop` call with no bellhop puts "None" on PATH once per call
severity: minor
lane: robustness
where: cafe/pm/physics/comms.py:392 (`if (bd := _bellhop_dir()) not in os.environ["PATH"].split(os.pathsep): os.environ["PATH"] = f"{bd}{os.pathsep}..."`)
reproduction: on orca, `CAFE_DATA=/nonexistent`, `PATH=/usr/bin`, call `comms.bellhop_tl([1000., 2000.], 10., [0,-100,-4000], [1500,1490,1520])` twice: the PATH reads `None:/usr/bin` then `None:None:/usr/bin`. `_bellhop_dir()` is None, and `None not in [...]` is always true. DECISIONS 429 says PATH gets the directory "once".
why it matters: row 429's claim holds only when bellhop is found. Production callers (`bellhop_tl` at comms.py:450, :517) are guarded by `bellhop_available()`, so it is unreachable from the pipeline.
wrong data: no

### A-9. `q17_vs_q16.md` says 15 moorings; the fit used 14
severity: minor
lane: documentation
where: review/round_17/q17_vs_q16.md (line "Not moved: `priors_fitted.json` ... 15 moorings")
reproduction: q17 `ingest/tao_compare.json` has 15 keys, one of them `ALL`; `ingest/priors_fitted.json` citation says "WRF minus 14 moorings"; the credibility page's L19 says "from the 14 moorings compared".
why it matters: a reviewer aid states a number the run contradicts.
wrong data: no

### A-10. A USV sensitivity column that cannot act is in the noise floor's family
severity: minor
lane: statistics
where: cafe/pm/stage1.py:45 (`ACTS["usv"]` gains `solar_yield_scale`), cafe/pm/stats/sensitivity.py:48-56 (`noise_floor` is the 95 % quantile of max S1 over every column passed)
reproduction: the USV's sensitivity margin is `xte_max` (largest cross-track error or station distance); nothing in `USVSim.step` reads `soc_wh` except the `battery` flag (usv.py:688-690), so `solar_yield_scale` cannot change the margin. It is nevertheless an `acting` column, so the floor is the max over one more column; `_sensitivity`'s docstring says a column that cannot act does not set the floor. q17's floor 0.202 against q16's 0.195.
why it matters: the floor is a little higher than its stated rule gives; conservative.
wrong data: no

## DECISIONS rows read

50 rows not listed by the reviewer_a files of rounds 12 to 16: 33, 78, 108, 131, 149, 173, 190, 211, 224, 240, 259, 274, 296, 311, 324, 337, 353, 368, 384, 401, 414, 429, 443, 457, 469, 487, 499, 514, 527, 548, 569, 589, 612, 634, 652, 669, 687, 701, 713, 724, 735, 748, 762, 775, 789, 801, 816, 827, 844, 857. Checked against code or by running it: 224 (five bad times each a `ConfigError` naming `window/start`), 296 (`abc`, `2.5`, `1e1`, `0`, `-3` refused; empty is unset), 429 (A-8), 211 (the acting columns now include `solar_yield_scale`, A-10; row 892 says it extends 211), 401 (`round(9)` at emulator.py:198 and :287), 527 (the three phrases in `config.stored_receipt_problem`), 634 (`SUITE_DIRS`, `SUITE_FILES` as stated), 687/701 (`MAIN_WHATS` and the argument check), 735 (`fluidx3d.available`), 801 (the five dead keys are gone from `config/subgrid.json`), 827 (`proot_run.sh` sets the thread pools and `XLA_FLAGS`), 844 (deck 8 m + 10, 30, 60, 100 m), 548 (`mass_drift_per_step` limit 1e-3), 724 (the NaT message), 748 (no `resolve()` on a typed path found except `receipts.py:481`, which is behind an `is_file()` check). Read for the sentence only: the rest.
No wrong claim found in these 50 beyond A-8 (row 429).

## Other checks

- The what-if CLI has no `--duty`; the dive candidates exist only in the flip table, where M-3's note covers them (I first suspected a gap in the direct answer and found there is no such input).
- q17: glider_eq 15/64 Wilson 90 % interval 0.1592 to 0.3311 recomputed by hand: matches. n_certify 73 matches the Wilson bound at k = 0. USV `n_empty` rule `<= 0` matches the battery flag `<= 0`. Glider hull collapse depth in the report (330.6 m) matches the code and QUESTIONS_FOR_LAB 4a; the reviewer prompt's 364 m is the L/20 value.
- `hull_depth_note("seaglider", d)` on orca: None at 300 m; the note at 364, 712.5, 950 m; "could not fly 1000 m" at 1500 m.

## What I could not check

- Reruns of the 11 queued survivors against wider tests (orca went unreachable), so A-2 to A-6 are "survived the named tests".
- About 18 further mutants (comms C10 to C19 and Q11 to Q18: UAS sortie length at four sites, the L19 text, the judged-row counts, the mode keep) did not finish.
- No end-to-end whatif, no hostile-input sweep of the new validators beyond the tests, no RUNBOOK run (reviewer D), no SITL.
- Cleanup: orca directories `pm_rev17_a`, `pm_rev17_a2`, `pm_rev17_a3` and their jobs were not removed because orca stopped answering; one pytest of mine may still run there under pm_rev17_a or pm_rev17_a2 (exact pids not obtainable). Local worktrees `../cafe-rev17-a`, `-a2`, `-a3` still exist and are clean (a3 holds two untracked probe scripts).

total: 10 findings (0 critical, 0 major, 10 minor)
