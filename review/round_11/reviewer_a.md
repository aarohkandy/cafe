# Round 11, reviewer A

Commit `778d8b6` code (HEAD `095c094` adds documents only). All runs on orca (`PM_HOST=cafe-orca PM_RUNTIME=proot`, 2 CPUs, `PMX=pm_rev11_a*`), from a detached copy of the repo.

What I did, in order: read DECISIONS 530 to 592 against the code each row names (the diffs `a1c7204..778d8b6` of `cafe/pm` and `bin`), recomputed the printed numbers of q11 I could trace (Wilson intervals of the eight verdicts, the 73-member rule, the coverage-gate chance figures of row 540 with an exact Fraction oracle, the `stall_map` figures of row 547, `running_mean_ok` figures of row 536, the span-by-span `check_rendered` claim of row 561 on q11's own page), then ran round 10's regression tests against 86 mutants of the fixes (below), then hostile CLI inputs.

Checked and found as the rows say (not findings): row 540 (0.2545 / 0.3573 / 0.18 / 0.1261 / 0.0636 for n 20 / 28 / 40 / 60 / 100, equal to an exact rational oracle); row 547 (2759 cells, 658 at V = 0, 56 weak, 12 unbalanced weak, 2045 moving, 22 stall-onset angles from 14.5 to 45, onset 17 / 26 / 30 at TWA 15 / 30 / 45); row 536 (white 5 % noise dev 0.001 to 0.006, ramp to 1.05 passes at 0.0195, to 1.06 fails at 0.0233, 5 % step in the last sixth fails 0.0244); row 561 (on q11's `index.html` there are 486 spans whose path occurs once; removing the text of each, one at a time, is found in all 486 cases: 0 undetected); `_lon_arc_covers` against a dense-sampling oracle on 6,000 random arcs (0 mismatches); row 568's day counts; row 570's `N_MIN`; the 8 verdict rows of q11 (Wilson 90 % and 95 % bounds and the n_certify sentences are exact); `audit --ledgers-only` on q11 and q10lb: 0 problems (q10lb prints the derived-layer note); DECISIONS numbering 1 to 592 has no gap or repeat.

## Mutation run of round 10's tests (what round 10 judged by reading)

86 mutants of the fixes of DECISIONS 530 to 591 were applied one at a time to a scratch copy and the tests that name the fix were run (`pytest -x`, 2 CPUs, orca). Each selection was first run unmutated and passed. Mutants: audit `_same_place` / `_shared_problems` / `_rebuilt_by_a_later_run` (8), `ledger.shared_changes` / `done` (7), `__main__` OSError and ResourceError routing (5), `config.damaged_run_files`, `receipts` stored-record shape, `budget.platform_label` (2), `hycom` zarr recognition (4) and receipt `_worst_abs` (4), `tao.caches` / `_candidates` / `wind_gap` (7), `whatif._deploy_in_window` / `flight_note` / `_clean` / row key / coverage band (8), `report._stat` / `data-path` / `_run_note` (6), `acceptance.claim_out` (4), `usv` wing-stall gate / `stall_map` / cap bound (3), `nest.running_mean_ok` (3), `pipeline.ocean_box` (2) / `_lon_arc_covers` (2) / flip budget / fitted-bias note, `freesurface.fitting_budget` (2), `shares` (2), `pm_checks.sh` `pm_word`, `_val`, `provenance`, `cand`.

73 were killed, 13 survived. Three survivors are equivalent mutants and are not findings: `band_gate_abs` (for nominal 0.9, `0.9 - 0.05 == 0.85` exactly in floats, so the plain bound and the dust band give the same gate; the dust itself is pinned by `band_dust`, killed), `shares_py` (one `python_files` pattern), `stall_weak` (no cell has V exactly 0.2). Three that survived the tests that name them were killed by the wider file selection (`prov_count`, `cand_lt`, `cand_twin`: the older `test_hangar_checks_provenance...` and `test_r9_m30_candidates_...` pin them) and are not findings. The other 10 survive the whole of the selection stated and are findings A-3 to A-8 below. The harness is `mut_rev11c.py` / `mut_rev11d.py` (in the scratch copy, not committed).

### A-1. A later run that adds a 3-D hour or changes the box rewrites orca parts under the same names, and the audit of the earlier run then reports a problem line, which DECISIONS 571 and 574 say the fix removed
severity: minor
lane: reproducibility
where: cafe/pm/env/orca.py:297-316 (`_drop_stale_parts`), cafe/pm/ledger.py:234-249 (`shared_changes`), cafe/pm/audit.py:108-135 (`_shared_problems`), DECISIONS 571 and 574, docs/RUNBOOK.md:278
reproduction: `_drop_stale_parts(out, box, h3)` with a cache whose `cut.json` has `hours3d` = [A] and a new run with {A, B}: it unlinks `hours/wrf_<B>.npz` and the ingest fetches it again with the 3-D fields (so its bytes change); a different `box` unlinks every `hours/*.npz` (probe on orca: parts left after the 3-D hour was added: only `umwm_*.npz`; after another box: none). `pipeline.py:399-409` takes `h3` from the UAS sortie hours of the mission, so a mission edited to fly its sorties at another hour (same name, so the same `cache/<mission>/orca`) does it. The manifest copy of the earlier run lists `parts[wrf_<B>.npz] = sha_old`; `shared_changes` returns "present and different" for the rewritten part and `_shared_problems` makes it a problem line ("the cache file was edited, or rebuilt by a later run"), which `credibility.build` turns into the red banner "the numbers may not be what the stages produced". The only test of orca parts (`tests/test_ingest_fetch.py:320-351`, `test_p32_a_grown_orca_cache_...`) grows the cache by adding a part name and replaces a part by hand; it never has a later run rewrite a part. In the same event the assembled stores (rewritten whole by `assemble`) give only the P-34 note.
why it matters: DECISIONS 571 lists "another window or 3-D hour for orca" as the growth case and 574 says it amends it; for a 3-D hour or a box change the part check still makes a healthy earlier run look damaged, while the stores of the same run get a note. RUNBOOK 278 does say "rebuilt by a later run" gives the line (so the user is told), but 591's rule ("a rewrite is a note, never a problem") is not applied to the parts. Either the parts need the manifest-copy test of 591(c) (shared manifest differs from the run's copy, so the part is a rebuild) or 574's sentence should be narrowed.

### A-2. `receipts --broken <missing file>` now prints the path twice and an errno
severity: minor
lane: documentation
where: cafe/pm/receipts.py:456, cafe/pm/__main__.py:172-176
reproduction: `PM_HOST=cafe-orca PM_RUNTIME=proot PMX=pm_rev11_a2 PM_CPUS=1 bin/pmx.sh python -m cafe.pm receipts --broken /nonexistent` prints `error: [Errno 2] broken configuration /nonexistent: no such file: '/nonexistent'`, exit 2. DECISIONS 579 made the raise `FileNotFoundError(errno.ENOENT, msg, filename)` so that `_names_a_path_given` sees a filename; `str()` of that exception adds the errno prefix and the filename again. Before 579 the line was `error: broken configuration /nonexistent: no such file`.
why it matters: the message got worse as a side effect of a fix (no document quotes it); `test_a_missing_broken_file_fails_the_check` matches a substring and does not see it.

### A-3. The `not root.is_dir()` clause of `ledger.done`, claimed by DECISIONS 575, is not pinned by any test
severity: minor
lane: documentation
where: cafe/pm/ledger.py:281-283 (`if not root.is_dir() or shared_changes(...)`), DECISIONS 575
reproduction: mutant `if shared_changes(json.loads(f.read_text()), root):` (clause removed): the whole of `tests/test_ledger.py` passes (survived). `test_p32_a_resume_notices_that_a_file_the_copy_names_changed_or_the_cache_is_gone` deletes TAO files with the directory, which `shared_changes` already reports as "gone"; for a manifest that names only orca parts a missing cache directory returns no change (parts absent count for nothing), and no test has one.
why it matters: row 575 says `done` returns None "when the cache directory is gone"; for an orca-only manifest that is only true through the store inputs, and the clause that says it is dead as tested.

### A-4. `looks_like_zarr` is tested only with Zarr 3 stores; the v2 ocean store with a variable `c` is the case its helper exists for and is not tested
severity: minor
lane: robustness
where: cafe/pm/env/hycom.py:191-210 (`_chunks_dir`), tests/test_hycom.py:1202-1216 and the `fx` stores
reproduction: mutant `all(` to `any(` in `_chunks_dir` survives `tests/test_hycom.py -k "zarr or store or lb0 or ingest or damaged"`. With the mutant, `looks_like_zarr(folder)` for `folder/ocean.zarr/{.zgroup, c/.zarray, c/0.0.0.0}` (a Zarr 2 group holding the `c` sound-speed variable) is True (probe on orca: real code False, mutant True), so `write_store` would replace (delete) a folder of other stores, which is exactly what row 581 closed. The real code is right; the test cannot tell.
why it matters: the docstring of `_chunks_dir` names the `c` variable as the reason for `all`; nothing makes it stay.

### A-5. `_val(x, what, n)` checks only the first `n` components (row 549), and no test has a NaN in a component past `n`
severity: minor
lane: robustness
where: cafe/pm/stage3/pipeline_windows.py:142-150, tests/test_stage3.py:918-937 (`test_r10_m15_...`)
reproduction: mutant `np.isfinite(a if n is None else a[:n]).all()` to `np.isfinite(a).all()` survives `tests/test_stage3.py -k "r10 or no_current or hole or nan or finite"`. The test's `AnalyticEnv` returns 2-tuples, so `a[:2]` is `a`. Row 549 states "a NaN in a field a path never reads cannot refuse a window" and the code does that, but a 3-vector with NaN in w is not tried.
why it matters: the behaviour that distinguishes `n=2` from no `n` is the one the row names.

### A-6. Edges of two round 10 guards are untested: the north latitude limit of `ocean_box` and the tolerance of `_lon_arc_covers`
severity: minor
lane: robustness
where: cafe/pm/pipeline.py:210 (`box[1] > 90.0`), cafe/pm/pipeline.py:540-560 (`start > 360.0 - eps`), tests/test_config.py `test_r10_m8_*`, tests/test_pipeline.py `test_r10_m3_*`
reproduction: mutants `box[1] > 90.0` to `box[1] > 91.0` and removal of `0.0 if start > 360.0 - eps else start` survive `tests/test_config.py -k r10_m8` and `tests/test_pipeline.py -k r10_m3`. The first: a north edge of 90.5 + pad passes the mutant; the second: a wanted west edge 1e-13 below the cached one (float noise) is "not covered" without the clause.
why it matters: "exactly 90 loads, beyond refuses" (row 542) is tested on one side only; the second clause is there for float noise and a refetch of a whole orca cache is what its absence costs.

### A-7. The error-type tuples of the "valid JSON of the wrong shape" fixes (rows 539, 582) are not each pinned
severity: minor
lane: robustness
where: cafe/pm/audit.py (`ledger_problems` except tuple), cafe/pm/ledger.py:`done`, cafe/pm/config.py:`damaged_run_files`, cafe/pm/receipts.py (stored record shape), cafe/pm/__main__.py:`_names_a_path_given` (`filename2`)
reproduction: each of these mutants survives the tests named for it (all pass with the mutant applied): `AttributeError` removed from the `ledger_problems` tuple (`tests/test_audit.py -k "lb0 or damaged or wrong or shape or unreadable or incomplete"`), `ValueError` removed from `done`'s tuple (whole `tests/test_ledger.py`; it may be unreachable, since a changed copy fails its hash first), `TypeError` removed from `damaged_run_files` (`tests/test_cli.py tests/test_stage1.py -k "damaged or m5 or incomplete or wrong"`), `ValueError` removed from the stored-record tuple in `receipts` (whole `tests/test_receipts.py`), and `e.filename2` dropped from `_names_a_path_given` (`tests/test_cli.py -k "oserror or lb0 or p37 or m5 or broken or receipts"`). The parametrised `edit` cases in `test_lb0_a_ledger_that_is_json_of_the_wrong_shape...` raise KeyError or TypeError only.
why it matters: each tuple was widened because a specific shape raised that error; a later narrowing returns a traceback and no test says so.

### A-8. The manifest copy a stage records is a second read of a file the stage then reads again
severity: minor
lane: reproducibility
where: cafe/pm/pipeline.py:455-459 (orca: `d = json.loads(man.read_text())`, then `L.snapshot(man, ...)`), cafe/pm/pipeline.py:824-826 (TAO: `L.snapshot(...)`, then `tao.load_tao(tdir, ...)` reads `tdir/manifest.json` itself), cafe/pm/ledger.py:`snapshot`
reproduction: by reading. `snapshot` copies the shared manifest and records the copy; the stage's data come from a separate read of the shared file (orca: before the copy; TAO: after it). A `fetch` of another run in the same data directory (the normal case on a shared server) between the two reads makes the recorded copy differ from the manifest the stage used. Window: milliseconds; the effect is that the audit checks the run against the wrong list of files.
why it matters: the point of P-32 is that the ledger records what the run read; reading from the copy would make that true by construction.

## Not covered

The survivors of A-3 to A-7 were run with the selections stated, not the whole suite. Not read line by line: `physics/glider.py`, `uas.py`, `comms.py`, most of `stage3/` (reviewer C's), the readers in `env/` other than the ones round 10 touched (D's). Not run: hostile missions (zero wind, 30 days, 20 vehicles, one vehicle, dateline), the 30-day and 20-vehicle memory refusals, the golden check (D's); RUNBOOK steps 1 to 7 and the three orca scripts (B's); mutants of rounds 1 to 9; DECISIONS rows 1 to 529 beyond numbering; FEA, CFD, SITL, Bellhop, GPU. Not run end to end: A-1 (reproduced in two parts: `_drop_stale_parts` on a scratch cache, and the audit's reaction to a changed part from the existing test; no second full ingest on a changed 3-D hour). Self-inflicted, logged as P-R11A in `review/orca/PROBLEMS.md`: two real demo `run`s started by a hostile-input probe (about 5 and 2 minutes, 1 to 2 CPUs, stopped by TERM on their own wrapper pids; the shared cache was not rewritten). Cleaned up: `pm_rev11_a`, `pm_rev11_a2`, `pm_rev11_a3` and my logs on orca, the detached worktree.

total: 8 findings (0 critical, 0 major, 8 minor)
