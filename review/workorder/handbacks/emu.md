# Work order step 4, the emulator: hand-back of the builder (wo-emu)

Base 8ecf0e7 (round 23 closed). Plan followed: `LEAD_HANDOFF/plans/emu_critic.md`, fixes (c), (b), (a) in that order. No printed text added.

## Where the code disagreed with the plan

- **(c) The plan's fix (hash the table path in `Context.stage_hash`) fails three existing tests and is not what is built.** A first build did that; `tests/test_reproducible.py::test_two_runs_with_the_same_seed_make_the_same_report_json`, `...with_the_real_stage_3` and `tests/test_acceptance.py::test_a_real_repeat_of_the_quick_run_is_identical_and_a_noisy_stage_is_caught` then failed (job wo_emu_6): the stage hash is the receipt `emulator:config:<hash>` printed in `report.json` (`machine.timing.variants.planned.receipt`, 4 fields), and two runs of one seed on tables of their own (as `acceptance` makes them, `out/<name>/emulator_table/train.parquet`) no longer produced an equal report. Built instead: the resume check compares the table the emulator ledger recorded with the one the run names now (see below). The stage hash is unchanged.
- Everything else in the plan held: the line numbers drifted only as the critic said; `run_variant` with `mods=None` is safe (`(mods or {})`); the base row of a solo UAS mission is one `run_batch` call.
- The `holdout.json` entries of `tests/fixtures/pm_run.py` carry no `scope` or `used` key (a real run's always do); the gate in `_whatif` reads them with `.get`, so those fixtures are read as "no gate".

## What changed

1. `cafe/pm/pipeline.py`
   - `TABLE_INPUT` (new module constant) holds the text `s_emulator` already gave its snapshot input as `kind`; `s_emulator` uses the constant, the text is the same.
   - `_other_table(ctx, d)` (new): True when the emulator ledger `d` records a `TABLE_INPUT` input whose `source` resolves to another file than `ctx.table`.
   - `run()`: a stage whose ledger is `done` is also not up to date when it is the emulator and `_other_table` is True; it then reruns, and so does every stage after it (the existing `redo`).
   - `s_emulator`: after `whatif.vehicle_rows(...)`, when `ctx.env` has `use_3d`, each UAS base row is replaced (same position in `rows`) by the row of `whatif.run_variant(whatif.solo(mission, vid), env, range(batch), ..., "base")`, which runs inside `wind_2d`. `want`, the note, `report._run_note` and `budget.emulator_plan` count the same rows as before. One solo UAS batch of wall time, not charged to the share. The row's `n_members` is the batch (16 to 32), not the run's 512, since only the base members `range(batch)` are re-run.
   - `by_key` comment: it said the base rows are 3-D-wind rows; it now says why they are left out (their mission is not in `mvs`).
2. `cafe/pm/__main__.py` `_whatif`: when `run/checkpoints/emulator/ledger.json` exists with `ok: true`, `whatif.train(...)` gets its `code_digest` (it filtered on the checkout's digest before). When `run/emulator/holdout.json` exists, every scope that an entry marks `used: false` (an untrained scope has it too) gets `(None, dict(info, used=False, unused_reason=<the run's>))`, so `usable()` answers Stage 1 with the run's own reason. No ledger, `ok: false`, or no `holdout.json`: today's behaviour.

## Regression tests (`tests/test_wo_emu.py`, new file)

Before = a copy of 8ecf0e7 (`git archive`) plus the test file plus one line, the constant `TABLE_INPUT` in `pipeline.py` (the (c) test names it; without the line it would fail on the missing name, not on the missing behaviour), `PMX=pm_wo_emu_b`, job `wo_emu_10`: all four tests failed, rc=1, for the reasons in the table. After = job `wo_emu_11` on the final tree: all four pass (rc=0).

| Test | Fix | Fails before because |
|---|---|---|
| `test_c_a_resume_under_another_emulator_table_reruns_the_emulator_and_the_stages_after_it` | (c) | a rerun with another `emulator_table` ran no stage (calls == []) |
| `test_b_a_uas_base_row_is_made_in_the_10_m_profile_like_its_variants` | (b) | `s_emulator` made no UAS batch at all with no variants (calls == []): the base row stayed the 3-D one |
| `test_a_whatif_trains_on_the_rows_of_the_code_the_run_was_made_with` | (a) digest | every row of the run's digest was "stale": the scope stayed untrained (`None is not None`); also the `ok: false` ledger case |
| `test_a_whatif_keeps_the_scopes_the_run_did_not_use_in_stage_1_with_the_runs_reason` | (a) gate | the scope was usable with `unused_reason` None, the run said it was not |


## Pins moved

None. No existing test was edited.

## Text for DECISIONS (numbered after 1085) and CHANGELOG

- **DECISIONS 1086 (emulator table on resume).** A resume under another `--emulator-table` now reruns the emulator stage and the stages after it: `pipeline.run` compares the `source` the emulator ledger recorded for its training-table snapshot (`TABLE_INPUT`) with the table the run names, as resolved paths. The table's path is not put in `Context.stage_hash`: that hash is the receipt `emulator:config:...` in `report.json`, and two runs of one seed on tables of their own (acceptance makes each so) would no longer give equal reports (three tests failed on that build). The table's contents are not hashed either: the snapshot's sha is the input check. Regression: `tests/test_wo_emu.py` (c). The running measurement `on1` was made before this: a resume of it on this code reruns the emulator in any case, as its code digest differs.
- **DECISIONS 1087 (UAS base row).** A UAS base row of the emulator's training table is made again in the 10 m profile (`wind_2d`) when the environment has the 3-D wind, on the base members `range(batch)`, as the variants' rows are; the report's own UAS verdict is still the 3-D run's. Before, one scope held the 3-D base row beside 10 m-profile variants, and the features carry no wind-model column. The row's `n_members` is the batch, so it weighs as a batch in the P(fail) noise floor. Cost: one UAS batch of wall time per UAS, not counted against the emulator's share. Regression: `tests/test_wo_emu.py` (b).
- **DECISIONS 1088 (whatif and the run's emulator).** `whatif --run R` trains the emulators on rows of the code digest that the emulator ledger of R records (when its `ok` is true), not the checkout's, and a scope that R's `holdout.json` marks `used: false` is answered in Stage 1 with R's own `unused_reason`: the in-sample gate of whatif is weaker than the run's (it has no fresh-draw check) and the run's verdict is the one that counts. Only the digest and the verdict are taken from the run; the table is still the shared one (`pipeline.emulator_table()`). Not changed: a run with no emulator ledger, with `ok: false`, or without `holdout.json` keeps the old behaviour, silently. Regression: `tests/test_wo_emu.py` (a), two tests.

CHANGELOG, one line each:
- A resume under another `--emulator-table` reruns the emulator stage and those after it (DECISIONS 1086).
- The UAS base row of the emulator's training table is made in the 10 m profile, like its variants (DECISIONS 1087).
- `whatif --run` trains on the run's code digest and answers in Stage 1 a scope the run's hold-out did not use (DECISIONS 1088).

## Evidence

Final tree (uncommitted state = the commit), `PMX=pm_wo_emu`, `PM_CPUS=2`, orca:
- `wo_emu_11` (script `/data/wo_emu_chk.sh`), rc=0: `pytest=0` on tests/test_wo_emu.py, test_round23_claims.py, test_cli.py, test_whatif.py, test_pipeline.py, test_reproducible.py, test_acceptance.py, test_round17_a.py, test_ledger.py (`-n 2`); `ruff check cafe/pm tests` all checks passed; `mypy cafe/pm` no issues in 57 source files.
- `wo_emu_10` (before, see above): 4 failed, rc=1.
- Earlier jobs of the interrupted instance (`wo_emu_6`: the stage-hash build of (c) failing three existing tests, which is why it was dropped; `wo_emu_9`: rc=0 on the same set of files) are superseded by `wo_emu_11`.
- No new hit in tests/test_round23_claims.py (it passes unedited).

## Not verified

- No real run: (b) is tested with `Env3D` and a stubbed `run_batch`, never with a real `GriddedEnv` and a 3-D wind cache. Whether the demo has the 3-D wind store live was not looked at (the plan's section 6 measurements on `on1` were not made: no `plan.json`, `design.json` or `holdout.json` of `/data/runs/on1` was read, no whatif run).
- (a) is tested through `whatif.train`'s result as handed to `whatif.answer` (answer is stubbed in the `wi` fixture), not the printed line of a real EMULATED or Stage 1 answer.
- `holdout.json` entries that are not objects, or whose `scope` is not hashable, are not handled (a real run never writes them).
- The mutation record, the full suite and the coverage gate were not run (only the files listed under Evidence). The new lines are covered by the new tests; `_other_table`'s branch for a ledger with no `TABLE_INPUT` input (an old ledger) is not tested.

## Still wrong, not touched

- Plan versus refit: the plan's `trains` follows `max(refit, no_refit)` (`budget.py:532,544`) while a run that refits has only the refit share (1260 s), so reaching 99 variants needs `est <= 12.7 s`, not 12.6 (critic's section 2). Owner's decision, not changed.
- `whatif` still reads the shared table, not the run's `train_input` snapshot; a run that appended rows after another one's whatif is not reproduced exactly.
- Where whatif's code digest differs from the checkout's, it is silent (the critic's open question to the owner).

## Printed text added

None. No new sentence, no new key in any printed or JSON output. The only new strings are the constant `TABLE_INPUT` (the text `s_emulator` already wrote, moved) and code comments.
