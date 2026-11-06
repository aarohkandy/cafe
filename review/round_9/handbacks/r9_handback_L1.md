# Round 9, batch L1 handback (branch r9-merged, worktree cafe-r9m)

Eight look-ahead problems: six fixed at the shared place, one already fixed by L0, one not a code bug. Base is bc5b024 (L0). DECISIONS and CHANGELOG were not
edited; the next free row at my base is 477 (L0's suggested 470 to 476 are not in the file yet), so the numbers below are suggestions for the lead to renumber.
Every new test was run on the unfixed tree (a detached worktree at bc5b024 with only the tests copied over, since removed) and failed there; all passed on the fix.

## L1-1 M-9 sibling: `machine_warning` looked only at the `machine` block, which only the stage-1 bench writes

DECISIONS row (suggested 477): `budget.machine_warning(thr)` compares the `machine` block as before and also each entry's own `cpus` and `cpu`
(`openfoam-*`, `jax-lbm-*`, every `stage1/<class>`), through one helper `_record_diff(record, host)`; an entry that differs is named with its own CPU count,
model and date ("entries measured on another machine: jax-lbm-d3q19-cpu (8 CPUs, AMD EPYC, 2026-10-28), stage1/usv (8 CPUs, ?, 2026-11-01); here it is 4 CPUs,
AMD EPYC"). An entry that differs exactly as the block does is not said twice. A key a record leaves out or gives in the wrong type is not compared (as before for
the block). The host name of an entry is not compared: the foam bench runs in a container whose name is a hash. To make the entries comparable the bench now writes
`cpus` and `cpu` into every entry (`foam`, `lbm`: `cpus`; `stage1` entries: `cpu`, they had `cpus` only). `ledger.machine()` passes the whole throughput block to
`machine_warning` (it passed `dict(machine=m)`), so the warning recorded in each stage ledger (L0, row 471) covers the entries too. Amends 468.

CHANGELOG: the other-machine warning compares every throughput.json entry's own CPU count and model, not only the `machine` block the last stage-1 bench wrote;
the bench stamps `cpus` and `cpu` on every entry; DECISIONS 477, round 9 M-9 sibling (L1).

Tests: `tests/test_budget.py::test_l1_the_machine_warning_compares_each_entry_with_its_own_cpus_and_model_not_only_the_machine_block`,
`...::test_l1_an_entry_that_differs_as_the_machine_block_does_is_not_said_twice_and_a_bad_entry_is_not_compared`,
`tests/test_ledger.py::test_l1_machine_records_a_warning_for_an_entry_of_another_machine_when_the_machine_block_matches`,
`tests/test_bench.py::test_l1_every_bench_entry_records_the_cpus_and_model_it_ran_on` (stage-1 and lbm entries).
Callers checked: `machine_warning` is called by `plan` (`__main__`), `pipeline.run` (a log line) and `ledger.machine()`; the block-only text is byte for byte what
it was (the existing M-9 tests ran whole). Nothing reads the new entry keys but the warning.
Not fixed, and still open: the entries already in config/throughput.json carry no `cpus` (lbm, foam) and no `cpu` (stage1), so until the next `make bench` they are
compared on what they have: an lbm entry from homebase is not flagged on a burst VM with the same CPU model. I did not backfill the file (that would state a CPU count
the bench never recorded). Rerun `make bench` on homebase to stamp them.

## L1-2 M-39 sibling: `pm.sh` synced with `--delete` into the shared `~/work/cafe/pm`, so a run from another checkout removed the lead's files

DECISIONS row (suggested 478): the shared `pm/` has one owner at a time. `pm.sh` records the checkout that last synced it in `~/work/cafe/pm.owner` (`host:path`,
unsafe characters replaced by `_`), and a sync from a different checkout is refused (exit 1, "belongs to ..., use PMX=pm_<you> bin/pmx.sh, or PM_TAKE=1")
before anything is sent. `PM_TAKE=1` takes it over (the new owner syncs with `--delete` as before). `--delete` stays (M-39: a test deleted in the tree must not run on
the server), so what the finding asked, that the guard not be only a rule in CLAUDE.md, is in the script. The marker is written before the rsync, so a sync cut
short still names its owner. `bin/pmx.sh` is untouched (its private dir has one writer by construction). Amends the round 9 M-39 row (batch E, not yet in DECISIONS.md). CLAUDE.md line 24 says "without `--delete`";
it now describes the owner rule (the file in this worktree is updated; cafe_main's copy is outside my worktree).

CHANGELOG: `./pm.sh` refuses to sync the shared pm/ from a checkout that does not own it (`pm.owner`; `PM_TAKE=1` to take over), so a second agent's run can no
longer `--delete` the lead's new files; DECISIONS 478, round 9 M-39 sibling (L1).

Test: `tests/test_runners.py::test_l1_pm_sh_will_not_delete_the_files_of_the_checkout_that_owns_the_shared_dir` (real rsync, stand-in ssh and docker: a second
checkout is refused and nothing is removed; the owner again is accepted; `PM_TAKE=1` takes over and deletes; the old owner is then refused).
Callers checked: `pm.sh` has the `--pull` branch (before the check, unchanged), the docker and the proot branches (both pass the check; the proot test
`test_the_proot_path_names_nothing_outside_cafe_worker` ran whole: the owner file is under `cafe-worker/cafe/`).
Needs your action once: the first `./pm.sh` after this lands on homebase finds no `pm.owner` and claims the dir for whoever runs it. If a lead run is already using
`~/work/cafe/pm`, run `./pm.sh` once from the lead's checkout first.

## L1-3 Cluster-6 sibling: the report printed the UAS tilt clamp, exceedance and airspeed as constants of whatever platform is flown

DECISIONS row (suggested 479): the UAS attitude statement is built from the vehicle's own platform. `report._uas_limits(platform, tr, airspeed)` reads
`limits.max_tilt_deg`, `limits.tilt_exceedance_deg` (and `max_airspeed_ms` for a summary without the profile count, whose sentence names it) through
`load_platform` as traced nodes (`vehicles.<id>.uas_limits`, source "<platform file> limits.<key>"), and `report._attitude_note` renders from them. The old text
is unchanged for the shipped file ("cannot fire ... the tilt clamp, 35 deg, is below the 42 deg exceedance"); when the clamp is not below the exceedance the page
says "Attitude exceedance can fire in this platform (the tilt clamp, X, is not below the Y exceedance), so the UAS verdict also rests on it"; a platform that cannot
be read gets a sentence that says so. The constants `UAS_ATTITUDE_NOTE` and `UAS_ATTITUDE_NOTE_NO_PROFILE` became the tails `UAS_ATTITUDE_TAIL*`. Amends 462's
sibling rows on M-7, M-10 and M-21 (plan values printed as results) and M-28 (the L17 statement).

CHANGELOG: the report's UAS attitude statement and the wind it names come from the vehicle's platform file (traced nodes), not from the shipped file's numbers;
DECISIONS 479, round 9 cluster 6 sibling (L1).

Test: `tests/test_report.py::test_l1_the_uas_attitude_statement_is_built_from_the_platform_the_vehicle_flies` (a copy of quad_uas.yaml at a path with the exceedance
below the clamp, then with another airspeed limit and no profile count; also `check_rendered` and the traceability check).
Callers checked: `_speed_html` is the only reader; the existing M-28 and profile tests (`test_the_uas_block_says_attitude_exceedance_cannot_fire...`, the no-profile
text) ran whole and pass with the same words.
Not changed, deliberately: the USV "30 m/s" in `MODE_TEXT["capsize_proxy"]`. The verifier agreed it is a code constant (`usv.py` builds the polar grid with
`np.arange(0.0, 30.01, 1.0)`), not a platform value. And `credibility.py`'s limitation L17 ("tilt clamp 35 deg, exceedance 42 deg") is the documented limitation of the
shipped model, listed verbatim by `test_limitations_are_listed_verbatim...` and `docs/CREDIBILITY.md`; it describes the shipped file by design.

## L1-4 A copied run missing an output still passed resume and audit, because `resolve` fell back to the original run's file

DECISIONS row (suggested 480): `ledger.resolve` returns, for a recorded path that lies in the run's layout under a place the run was (`roots`) and does not exist
under `run_dir`, its place in `run_dir` (the first, longest, candidate), not the path as recorded. The recorded path is the original run's file; a copy must not
borrow it. A path outside the run's places (`/app/config/...`, the environment cache, `/data/cache/report/x`) is still returned as recorded. `done`, `rerecord` and
`audit.ledger_problems` all use `resolve`, so a missing output of a copy is now "output <copy path> is missing" in the audit and `done` is None (the stage reruns).
Amends M-19's "a path the run lost is reported at the place it was recorded" (the old docstring, and one assertion of
`test_r9_m19_resolve_rebases_on_the_run_layout_longest_tail_first`, which pinned the old answer for a lost file with no copy involved; it now expects the path in the
run, an equally exact assertion).

CHANGELOG: `ledger.resolve` reports a lost file of a copied run in the copy, not at the original run's recorded path, so resume and audit see the copy's missing
output; DECISIONS 480, round 9 M-19 sibling (L1).

Test: `tests/test_ledger.py::test_l1_resolve_reports_a_lost_output_of_a_copy_in_the_copy_not_at_the_original` (copy with the original still there; `done` None, audit
names the copy's file; the original still resumes; an outside path as recorded).
Callers checked: `done` (inputs and outputs), `rerecord` (its `outs` map keys by resolved path: a lost file now keys at the copy, where `report --run` writes it, so
the recorded entry is updated, not duplicated), `audit.ledger_problems` (inputs, outputs, the chain check). `tests/test_audit.py` and `tests/test_ledger.py` ran whole.

## L1-5 Re-rendered report puts the rendering machine's warning under the run's machine

Already fixed by L0 (L0-2/3, DECISIONS row 471 suggested): `ledger.machine()` records `warning` where the stage ran and `report._machine` reads it back from the
ingest ledger; `machine_warning()` is no longer called at render time. Checked at my base: `report._machine` has no `budget.machine_warning` call. No change in L1; L1-1
widens what the recorded warning says.

## L1-6 `refuse_overlap` refused a store that sits inside the source directory, which deletes nothing

DECISIONS row (suggested 481): `hycom.refuse_overlap(out_zarr, source)` raises only when the store (or its `.tmp` sibling) is the source or holds it
(`q == s or q in s.parents`). A store inside a source directory is accepted: `write_store` rmtree()s the store and its `.tmp` only, the lab's files are read from the
directory itself (`glob`, not recursive), and each source file (and each `.a`/`.b` and grid file) is still checked on its own, so a snapshot linked into the store is
still refused. The message no longer says "or one holds the other". Amends 737ba1b's M-5 rule and its test.

CHANGELOG: `ingest_lab_hycom` accepts a store path inside the lab's source directory (it deletes nothing there); a store that is or holds the source is still
refused; DECISIONS 481, round 9 M-5 sibling (L1).

Tests: `tests/test_hycom.py::test_l1_a_store_beside_the_lab_files_inside_their_directory_is_written_and_the_source_survives` (written twice, the second replaces the
first, every snapshot still there). The `inside` case was removed from `test_r9_m5_a_store_that_is_holds_or_lies_inside_the_source_is_refused_and_the_source_survives`
(its parametrization is now same / parent / via_symlink / tmp_sibling, all still refused); that case asserted the false positive.
Callers checked: `ingest_lab_hycom` (the directory, each file, the archv pairs) and `assemble_gofs` (its parts directory and the store are siblings in `fetch_gofs`;
`out == pdir` and the parent are still refused, `test_r9_m5_gofs_parts_are_protected_the_same_way`). `tests/test_hycom.py` ran whole.

## L1-7 The tolerant stored-receipt readers still crashed or silently dropped a grid

DECISIONS row (suggested 482): `lbm.read_stored(f, numeric, optional=())` takes the `optional` fields of `config.missing_numbers` (a field that is present must be a
finite real). `nest.stored_grids(tag)`, the one reader of the sphere grid study, now: (a) takes only files named `nest_sphere_<tag>_d<digits>.json` (a rerun kept as
`..._d8_prev.json` is no grid; the credibility page's reader already used that rule), (b) requires a positive `d`, a numeric `seconds` if present and a `code_sha`
that is text or absent, (c) names, and leaves out, a file whose `d` repeats an earlier file's. The named files show in the receipts table as before ("... is unreadable
(it needs ...): left out, rerun it"). With distinct positive `d` the Richardson fit is finite, so `sphere_discretisation` never hands `default_floor` a NaN. Amends 466
(M-4 reader side).

CHANGELOG: the sphere grid study's reader names and leaves out a grid with a non-numeric `seconds`, a non-text `code_sha`, a non-positive or repeated `d`, and ignores
`_prev` reruns, instead of a TypeError or a NaN floor; DECISIONS 482, round 9 M-4 sibling (L1).

Tests: `tests/test_stage3.py::test_l1_a_stored_sphere_grid_with_a_field_the_readers_cannot_use_is_named_and_left_out_not_a_traceback_or_a_nan` (5 damages: string
seconds, list and object code_sha, d 0, repeated d; each through `stored_grids`, `sphere_discretisation` finite, `sphere_receipts`),
`...::test_l1_a_rerun_kept_beside_a_grid_is_no_grid_of_the_study_as_the_credibility_page_reads_it`.
Callers checked: `stored_grids` is read by `sphere_discretisation` (refit's `default_floor`) and `sphere_receipts`; `read_stored` has the other callers `wallmodel._read_receipt`
and the lbm sphere row, which pass no `optional`. The existing `test_r9_m4_read_stored_and_the_sphere_grid_readers_name_a_damaged_file...` ran whole and passes unchanged.
Not changed: `shape` is not validated (an f-string prints whatever it is; it cannot raise). I did not touch `default_floor` itself: with the reader fixed no NaN
reaches its `max()`. A study with a `cd_inf` of exactly 0 (a zero division in `sphere_discretisation`) is not guarded; it needs contrived data.

## L1-8 Re-rendering an older run with `report --run` drops its credibility levels and the audit fails stage 3

Not a code bug, as the finding says. `config/assumptions.yaml` is a hashed input of the stage-3 ledger, so adding the two rows (`tao.air_gap_s`,
`bathy.gofs_open_level_sigma_m`) makes every pre-merge run's stage-3 ledger read "input ... changed since the stage ran", and `credibility.Facts.problems` counts any
ledger problem against the levels. Consequence for the lead: a run made before this merge (q9 and earlier) cannot be re-rendered at its original credibility
levels; only the post-merge rerun gives a clean audit. I did not add a printout to `report --run` (optional in the finding, and the report's own problem list already
carries the ledger problem it scores against).

## Verified

On cafe-burst (4 vCPU, own dirs pm_r9m and pm_r9m2, removed at the end): ruff (`cafe/pm tests bench`) and `mypy cafe/pm` (strict) clean on the final tree.
Whole files passed: test_budget, test_ledger, test_audit, test_hycom, test_runners, test_bench, test_report, test_credibility, test_cli, test_config_docs,
test_conventions, test_pipeline, test_vv, test_stage1, test_stage3 (exit code 0; the one failure along the way was my own new report test, fixed, and
`test_bench_all_stops_at_once_without_the_cache` when I ran it with `PM_MEM=8g`: the plan refuses 9 GB of environment on 8 GB, so it is the container size, and it passes at 16g).
Not run: test_uas, test_usv, test_acceptance, the full suite and `audit`, mutation: none of them touches the changed code except through the files above.

## Still open after L1

- config/throughput.json entries carry no `cpus` (lbm, foam) or `cpu` (stage1) until the next `make bench` (L1-1).
- First `./pm.sh` on homebase after this merge claims `~/work/cafe/pm` for whoever runs it (L1-2).
- CLAUDE.md in cafe_main (outside this worktree) still says pm.sh syncs "without --delete" (L1-2).
- `credibility.py` L17 still prints "tilt clamp 35 deg, exceedance 42 deg" as the documented limitation of the shipped model (L1-3).
