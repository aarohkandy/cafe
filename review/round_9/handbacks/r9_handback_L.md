# Round 9, batch L handback (branch r9-l, worktree cafe-r9l)

Findings: M-16, M-19, M-31, M-32, M-15, M-30, in that order. Next free DECISIONS row at my base (91c9777) is 461; the row numbers below are
suggestions for the lead to renumber. Docs were not edited.

Names that differ from the brief: the shared resolver is `ledger.resolve` (public, not `_resolve`, because `audit` imports it); the TAO lift helper is
`tao.wind10` plus `tao._air_at` (one function used by `tao.compare` and `pipeline._wind_residuals`).

## M-16 `report --run` re-render leaves `audit` failing

DECISIONS row (suggested 461): `report --run` runs the report stage's own two checks (`report_traceable`, `report_html_matches_json`, now
`report.self_checks`, which `s_report` ledgers too) on the files it just wrote. If both hold it brings the report ledger up to date
(`ledger.rerecord`): the sha256 of each rewritten output (an output the ledger did not list is added) and a note
`re-rendered by report --run (git_sha <sha>, code_digest <digest>)`; the ledger's own checks, config hash and `git_sha` stay what the stage
recorded. If a check fails it prints `error: re-rendered report fails <check>: ...` and exits 1 with the ledger unchanged, so `audit` keeps saying
the outputs changed, which is true. A run without a report ledger is left alone. Amends row 398 (`report --run` builds its Context without a plan).

Earlier rows amended: 398.

CHANGELOG: `report --run` records the files it re-renders in the report ledger (after re-running the report checks on them); `audit` no longer fails
after a re-render. A re-render that fails a report check exits 1.

Doc sentences: RUNBOOK 5 (where `report --run` is described, line ~162 at the base): "`report --run <dir>` re-renders the report and the credibility page,
runs the report's two self-checks on the new files and records them in `checkpoints/report/ledger.json` with a note; if a check fails it exits 1 and
the ledger is left as it was (`audit` then reports the files as changed until the report stage is rerun)."

Checked what could break, and how:
- Callers of `report.write`: `s_report` and `_report` only. `s_report` now loops over `report.self_checks(run_dir)` (same names, same order, same
  `value`/`limit`/`note`); `tests/test_pipeline.py` and `tests/test_report.py` ran whole (see the end).
- `report --run` can now exit 1 (it was 0 or 2). `main` returns `_report`'s value unchanged.
- On a failed check the new files are already on disk (`report.write` writes in place). The message says so. Writing to a temporary directory and
  moving after the checks would avoid it; not done, because `report.write` has one writer and no staging today.
- The report itself ignores the report ledger ("written after this table", test `test_the_report_of_a_resumed_run_ignores_an_earlier_attempts_report_ledger`),
  so changing that ledger cannot change the next render.
- `done()` for the report stage after a re-render: outputs now hash to the ledger, so it resumes as up to date. Its `config_hash` carries the code
  digest, so a different code still reruns the stage.
- Not isolated (the reviewer's note): why a re-render differs from the stage's own output (cache present or absent). Not needed for the fix.

Tests: `tests/test_cli.py::test_r9_m16_report_run_leaves_the_report_ledger_matching_what_it_wrote`,
`...::test_r9_m16_a_re_render_that_fails_a_report_check_exits_1_and_leaves_the_ledger_alone`,
`tests/test_ledger.py::test_r9_m16_rerecord_takes_the_new_hash_adds_a_note_and_leaves_the_checks`.

## M-19 `audit` of a renamed or copied run; `done()` resumes against the original

DECISIONS row (suggested 462): a path a ledger recorded is looked up by one function, `ledger.resolve(ref, run_dir)`, used by `audit.ledger_problems` (inputs,
outputs, the chain test) and by `ledger.done` (outputs and inputs). Order: (1) through a directory named like `run_dir` (as before), (2) from the
first directory of the run's own layout in the recorded path (`checkpoints` or a stage's output directory, `ledger.RUN_DIRS`), longest tail first,
joined onto `run_dir`, (3) as recorded. Only a candidate that exists under `run_dir` is taken. So a run copied or renamed (`cp -r runs/q9 runs/quick`)
is audited and resumed against its own files, and the chain test no longer fails on the name. `STAGES` now lives in `ledger.py` (`audit.STAGES` is
still importable). Amends row 84 (resume reuses a stage only if its ledger matches: the files it matches against are the run's own) and row 454
(a hashed input has to exist: "exist" is now under the audited run first).

Earlier rows amended: 84, 454.

CHANGELOG: `audit` and the resume check read a copied or renamed run's own files; `cp -r runs/q9 runs/quick` no longer gives "chain broken", and a
tampered copy is caught instead of passing against the original.

Doc sentences (RUNBOOK, where a copied run is described / the audit section): "A run directory can be copied or renamed: `audit` and a resumed `run` read
its files from where the copy is, whatever the directory is called. Paths the run recorded outside its own layout (`/app/config/...`, the environment
cache) are read where they were recorded."

Checked what could break, and how:
- `_resolve`'s old callers: `audit.ledger_problems` (3 places) only; `done()` read the recorded absolute path. Both now call `resolve`. A run resumed at
  the path it was made at resolves exactly as before (step 1 matches). Relative `out` dirs (`runs/<m>/quick`) resolve through step 1 too.
- Step 2 could take a wrong file if a recorded path OUTSIDE the run has a component named like a stage (`/lab/ingest/x.nc`) and the same tail exists under
  the run. The pipeline's inputs outside the run live under the data directory (`orca`, `tao`, `cache/<mission>`, the GEBCO cut; read from the `L.input` calls in
  `pipeline.py`), none with a stage-named component unless a mission is named like a stage. The existence requirement limits it to a coincidence.
- RESIDUAL, not fixed: in a renamed copy, a file the copy has lost that the original still has is not rebased (the candidate must exist), so it is
  read from the recorded path, i.e. the original's. The brief asks for "require the rebased path to exist". The only alternative is to return the rebased
  path when it does not exist, which would report outside-run paths with a stage-like component as missing. Decide if you want it.
- Not done: "ideally a different message when only the name differs". With the rebase there is no name-only failure left to message.
- Files at the run root (`mission.yaml`, `plan.json`) or outputs outside the layout directories cannot be rebased when the directory name changed. The
  pipeline records none; `tests/test_audit.py::make_run` writes `run/<stage>.out` at the root, which is why the new tests use a layout-shaped run.
- `STAGES` moved: `pipeline.py`, `report.py` and `credibility.py` now import it from `ledger` (mypy strict refuses a re-export through `audit`).
  `credibility.py` is touched for that one import line only.
- The old test `test_a_path_through_the_run_name_that_is_not_under_the_run_stays_where_it_was_recorded` is kept, now on `ledger.resolve`.

Tests: `tests/test_audit.py::test_r9_m19_a_copy_under_another_name_is_checked_against_its_own_files_with_the_original_present`,
`...::test_r9_m19_a_copy_under_another_name_is_clean_with_the_original_removed`,
`tests/test_ledger.py::test_r9_m19_resolve_rebases_on_the_run_layout_longest_tail_first`,
`...::test_r9_m19_done_reads_a_copy_under_another_name_from_its_own_files`.

## M-31 a TAO file without its `_QC` variable

DECISIONS row (suggested 463): `tao._series` raises `ValueError` ("<file>: variable <VAR>_QC is missing, ...") when the file has no QC variable for the
variable it reads, instead of treating every sample as good. `fetch_tao` catches it while scoring a candidate: the file is still downloaded and hashed
into `manifest["files"]`, but it is not a candidate for `selected`, so another deployment is picked, and the manifest gets an `unusable` entry
`{file key: message}` saying why. `load_tao` does not catch it. Amends row 44 (it gave only the flag sets).

Earlier rows amended: 44.

CHANGELOG: a TAO/TRITON file without its QC flag variable is refused (it used to keep every sample); `fetch` picks another deployment and records the
refused file under `unusable` in the TAO manifest.

Doc sentences: RUNBOOK (the TAO paragraph / troubleshooting): "If ingest stops with `variable WSPD_QC is missing`, the TAO cache was built from a file without its
QC flags (an older fetch); delete `<data>/tao/manifest.json` and run `fetch` again, which picks another file and lists the refused one under `unusable`."

Checked what could break, and how:
- Callers of `_series`: `fetch_tao` (caught) and `load_tao` (not caught: a cache whose selected file has no QC variable now stops ingest with the message,
  whose text gives the fix). `_tao_cached` only verifies hashes, so it does not notice. The q9 cache has QC (`tao_compare.json` n=144 through the QC
  filter), so nothing real is known to hit it. `tests/test_pipeline.py` builds its TAO fixtures with QC and passed whole.
- The manifest gains a key only when a file is refused; no reader of the manifest uses `unusable`.
- A mooring whose every file lacks QC now has no `selected` entry for that variable (the same as a mooring with no good samples).

Tests: `tests/test_tao.py::test_r9_m31_a_file_without_its_qc_variable_is_refused_naming_file_and_variable` (replaces
`test_qc_without_a_flag_variable_keeps_everything`), `...::test_r9_m31_fetch_picks_another_deployment_when_the_fuller_file_has_no_qc_variable`.

## M-32 `tao.compare` and the pipeline copy hold air temperature, humidity and SST outside their record

DECISIONS row (suggested 464): the COARE 4 m to 10 m wind lift of a mooring uses its air temperature, humidity and SST only within `tao.air_gap_s` (3600 s,
`config/assumptions.yaml`) of the nearest sample of that record, interpolating linearly between samples; at a wind time farther than that from the
nearest sample of any of the three, that sample gets the neutral log-law lift (`wind_to_10m(..., "coare", air)` does this per sample, where any
of the three is NaN). One function, `tao.wind10(m, method)` (with `tao._air_at`), lifts a mooring for `tao.compare` and for
`pipeline._wind_residuals`; the second copy of the code is gone. The 1 h limit is an unsourced assumption: the review measured a 2 K air drift as
0.023 m/s on a 6 m/s wind. Amends row 44 (COARE where AIRT, RH and SST exist: now "and within the gap").

Earlier rows amended: 44 (the lift).

CHANGELOG: the TAO wind lift no longer holds the last air temperature, humidity and SST of a short record for the rest of the wind record; beyond
1 h from a sample it uses the neutral lift. `tao.air_gap_s` added to `assumptions.yaml`. `tao_compare.json`, `priors_fitted.json` and any golden that
holds them change when a mooring's air records are shorter than its wind record.

Doc sentences: RUNBOOK / PHYSICS (the TAO comparison): "The wind of a mooring is lifted from 4 m to 10 m with COARE where the mooring reports air temperature, humidity and
SST within 1 h of the wind sample (`tao.air_gap_s`), and with the neutral log profile elsewhere." Assumptions table entry comes from the new
`assumptions.yaml` row (`tao.air_gap_s`).

Checked what could break, and how:
- Callers of `tao.compare`: `pipeline._tao` (sole), receipts in `tao.receipts`. `_wind_residuals` was the only copy; `grep np.interp` over `cafe/pm` finds
  no other mooring-record interpolation. `pipeline.py` line ~856 (`_air_rmse`) bins AIRT with `_bin`, not `np.interp`; not affected.
- `wind_to_10m(..., "coare", air)` now broadcasts `speed`, `z` and the `air` entries and calls COARE only on the samples with all three finite; for fully
  finite input it passes the same values as before (`test_wind_lift_methods_and_their_errors`, the COARE `compare` test and the receipts pass).
- Explicit `method="coare"` for a mooring that lacks `airt`, `rh` or `sst` still raises `KeyError` (unchanged); `auto` still needs all three keys.
- A record with zero samples (possible when `load_tao` is called with a window the file does not cover) was an `np.interp` ValueError; it is now NaN, so the
  neutral lift.
- `env/tao.py` now imports `..config` at import time to read `tao.air_gap_s` (as `bathy.py` does for its sigmas). A `config/assumptions.yaml` without the
  key makes importing `tao` a `KeyError`. `tests/test_config.py` copies of the file keep the real one's keys.
- Stored `tao_compare.json`, `priors_fitted.json`, `env_sigmas_fitted.json` and the golden would be re-based at code freeze if real gaps exist
  (the q9 TAO cache gaps were not checked, as the finding says).
- `tao.py` coverage stays 100 % (checked with `--cov=cafe.pm.env.tao`).

Tests: `tests/test_tao.py::test_r9_m32_compare_lifts_with_the_neutral_profile_where_the_air_record_does_not_reach`,
`...::test_r9_m32_the_air_state_is_used_up_to_the_gap_limit_from_the_nearest_sample_and_not_beyond` (6 cases incl. exactly the gap and one second past it),
`...::test_r9_m32_the_air_state_is_interpolated_between_samples_and_an_empty_record_is_missing`,
`...::test_r9_m32_coare_lift_falls_back_to_the_neutral_one_only_where_the_air_state_is_missing`,
`tests/test_pipeline.py::test_r9_m32_the_hourly_residuals_lift_a_mooring_the_way_tao_compare_does_where_its_air_record_stops`.

## M-15 tests that pass on broken code (direction spread, u* band)

DECISIONS row (suggested 465): tests only plus one name. `pipeline.USTAR_AGREE_BAND = 0.2` is the "within 20 %" of BRIEF 2.1, used by `_ustar_agreement`
and by the check note and the finding text (which print it from the constant). Amends row 168.

Earlier rows amended: 168 (the 20 %).

CHANGELOG: tests for the current-direction error spread, the wind-direction spread and the 20 % u* band; `USTAR_AGREE_BAND` named.

Doc sentences: none.

Checked what could break, and how:
- `pipeline._ustar_agreement` signature and return are unchanged; the strings that carried "20 %" print `{100 * USTAR_AGREE_BAND:.0f} %`, the same text.
  The existing exact-text test of the finding note passes.
- Not touched (other batch): `credibility.py` lines ~95 and ~401 still write "within 20 %" as literals beside `pipeline.USTAR_AGREE_FRACTION`. See "needs from other batches".
- The wind-direction sibling: there is no wind-direction random field in `PerturbedEnv` (only the member-wide bias and the fitted noise, added); the
  new test pins their sum in quadrature through `PerturbedEnv.wind`. `WindNoise` direction sd was already pinned (`white.std() == 20`).

Tests: `tests/test_perturb.py::test_r9_m15_current_direction_spread_is_the_prior_split_in_half_between_the_member_and_the_field`,
`...::test_r9_m15_wind_direction_spread_is_the_bias_and_the_fitted_noise_added_in_quadrature`,
`tests/test_pipeline.py::test_r9_m15_the_ustar_band_is_20_percent_of_umwm_ust_on_both_sides` (4 cases, UMWM ust = COARE u* times 1.2, 0.85, 1.3, 0.75; I used 1.2 and
1.3 rather than 1.15 and 1.3 so that the band is bracketed at 0.167 and 0.231, which also kills a band of 0.15 and 0.25).

## M-30 three surviving mutants

DECISIONS row (suggested 466): tests only. `tao._candidates` keeps the deployment in the water at t0, its A/B twins up to 10 days before it (boundary
inclusive) and every later deployment starting no later than t1; `tao._bin` defaults to a half width of 1800 s and 3 samples; `tree_sha256` hashes the relative
path (with a separator) and the bytes of every file, so a rename, a move, an added empty file and a changed file boundary change it. Row 44's rule and
the 3-sample default had no row.

Earlier rows amended: none (adds the rule; row 44 for context).

CHANGELOG: tests for the TAO deployment window, the `_bin` defaults and the store hash.

Doc sentences: none.

Checked what could break: code unchanged. New tests: `tests/test_tao.py::test_r9_m30_the_bin_takes_half_an_hour_each_side_and_three_samples_by_default`,
`...::test_r9_m30_candidates_are_the_deployment_in_the_water_its_twins_within_ten_days_and_the_later_ones_that_start_in_the_window`,
`tests/test_remote.py::test_r9_m30_the_tree_hash_covers_the_names_of_the_files_and_the_empty_ones` (`surface.store_sha256` is the same function).
The `tests/test_surface.py` mention in the finding needs nothing separate: `store_sha256 is tree_sha256`.

## Mutants (detached throwaway worktree `cafe-r9l-mut` on commit 6c3e17e, run on cafe-burst in `pm_r9l_mut`)

Each row: the mutant applied to the fixed code, the new test(s) run (`-x`), result. All 36 are KILLED (the test fails on the mutant, passes on the fixed code).
The unfixed code has no `ledger.resolve`, `rerecord` or `wind10`, so for M-16, M-19, M-31 and M-32 the mutants that restore the old behaviour stand in for it (a test run on the base commit would fail on a missing name, which shows nothing).

| finding | mutant | result |
|---|---|---|
| M-16 | `_report` without the `ledger.rerecord` call | killed |
| M-16 | `if bad:` made `if False:` (no check gate) | killed |
| M-16 | `rerecord` without the note | killed |
| M-16 | `rerecord` records a wrong sha256 | killed |
| M-19 | `resolve` without the layout step | killed (audit and ledger tests) |
| M-19 | `resolve` takes the shortest tail first (`windows/x` for `stage3/windows/x`) | killed |
| M-19 | `done()` reads recorded output paths | killed |
| M-19 | `audit` reads recorded output paths | killed |
| M-31 | no `ValueError` for a missing QC variable (the old all-good behaviour) | killed |
| M-31 | `fetch_tao` does not catch it | killed |
| M-32 | `near <= AIR_GAP_S` to `<` | killed |
| M-32 | no gap limit (the old hold; compare test and pipeline test) | killed (both) |
| M-32 | gap twice as long | killed |
| M-32 | fallback only where airt and rh are missing (sst ignored) | killed |
| M-32 | `_wind_residuals` lifts without the air state | killed |
| M-15 | current direction field without `/ sqrt(2)` (the finding's mutant) | killed |
| M-15 | member half of the direction without `/ sqrt(2)` | killed |
| M-15 | wind direction noise halved | killed |
| M-15 | u* band 0.5 (the finding's mutant) | killed |
| M-15 | u* band 0.15 | killed |
| M-15 | `r <= 0.5` literal in `_ustar_agreement` | killed |
| M-30 | `tree_sha256` without the name update (the finding's mutant) | killed |
| M-30 | `tree_sha256` without the NUL after the name | killed (case added after the first run let it survive) |
| M-30 | `_candidates` `- 10 * 86400` to `- 0` (the finding's mutant), `- 9`, `- 11` | killed (3) |
| M-30 | `_candidates` `lo <= day` to `<`, `day <= t1` to `<`, `day <= t0` to `<` | killed (3) |
| M-30 | `MIN_IN_BIN` 1 (the finding's mutant), 2, 4 | killed (3) |
| M-30 | `HALF_BIN_S` 3600, 900 | killed (2) |

First run: two mutants of mine survived and one did not apply; all three were my mutant's fault or a missing case, and were fixed and rerun: `M31 old default`
(I had not removed the raise, so it changed nothing; the real old behaviour is the "no raise" row), `tree_sha256` NUL (test case added), `rerecord` wrong sha
(pattern typo). Throwaway worktree and burst directory removed.


## Verification

On cafe-burst, 4 CPUs, in my own `pm_r9l` (removed at the end; no containers left running, no tmux sessions):
- `ruff check cafe/pm tests`: clean. `mypy cafe/pm` (strict): clean (checked before the last two small edits to a message and a test; the final commit changes only a
  string in `tao.py`, a test file and the handback, and ruff was rerun after the string edit).
- Whole files, rc 0: `tests/test_ledger.py`, `test_audit.py`, `test_cli.py`, `test_tao.py`, `test_remote.py`, `test_perturb.py`, `test_ingest_fetch.py`, `test_surface.py` (407 tests, final
  code); `tests/test_pipeline.py`, `test_report.py`, `test_credibility.py` (530 results, all passed, rc 0, final code).
- `cafe/pm/env/tao.py` coverage: 100 % from `tests/test_tao.py` alone (`--cov=cafe.pm.env.tao`), measured before the last message edit; the edit adds no branch.
- NOT run: the full suite, `audit` (ruff, mypy, coverage gate over `cafe/pm`, the banned scan, the mutation record), `make mutation`. `audit.banned` was not run (it needs Python 3.11); instead the added lines of
  `git diff 91c9777 HEAD -- cafe tests config` were grepped with the `audit.BANNED` pattern: no match.
- Not run on real data: nothing here was run against the q9 TAO cache or a real run directory (`report --run` needs about 20 GB; `cp -r` of a real run
  with the original present or removed was reproduced only on synthetic layout-shaped runs).


## Needs from other batches

- Batch B (credibility): `cafe/pm/credibility.py` lines ~95 (the level text) and ~401 (the finding text) spell "within 20 %" literally; they could print
  `pipeline.USTAR_AGREE_BAND` like they read `pipeline.USTAR_AGREE_FRACTION`. I only changed their `STAGES` import line.
- Any batch that adds a run output file outside a stage directory (`ingest`, `hangar`, `stage1`, `windows`, `stage3`, `refit`, `stage1b`,
  `emulator`, `report`) or at the run root: `ledger.resolve` cannot rebase it for a renamed copy; add the directory to `ledger.STAGES`/`RUN_DIRS` or
  keep new outputs in a stage directory.
- Anyone who adds to `report.write`'s outputs: `ledger.rerecord` appends unlisted paths on its own, but `report.self_checks` reads only
  `report/report.json` and `report/index.html`.
- Batch A (hub file `pipeline.py`) and others merging after me: my `pipeline.py` edits are four small ones (the `STAGES` import line, `s_report` loop,
  `_wind_residuals` body, the `USTAR_AGREE_BAND` constant and its three uses). `tests/test_pipeline.py` gets two appended tests and `tests/test_tao.py` is
  changed in several places (a `write_nc` `qc=None` option, the QC test replaced), so expect textual conflicts there.
- RUNBOOK rows named above (step 5 for `report --run`, the audit/copy sentence, the TAO paragraph) are the lead's to write.
- Re-basing at code freeze: `tao_compare.json`, `priors_fitted.json`, `env_sigmas_fitted.json` and the golden if a real mooring's air record is shorter than its wind.
