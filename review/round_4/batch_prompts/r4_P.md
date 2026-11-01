You are builder P (pipeline, emulator, receipts, bench) for review round 4. First read review/round_4/batch_prompts/r4_common.md and follow it exactly.

Your findings: M-2, M-3 (emulator and whatif parts; the report text is batch R's), M-4, M-22, M-23, M-25 (the test; the RUNBOOK wording goes in your hand-back), M-26.
Files you own: cafe/pm/pipeline.py, cafe/pm/env/surface.py, cafe/pm/audit.py, cafe/pm/ledger.py, cafe/pm/__main__.py, cafe/pm/emulator.py, cafe/pm/whatif.py, cafe/pm/receipts.py, cafe/pm/budget.py, bench/throughput.py, tests/test_surface.py, tests/test_pipeline.py, tests/test_audit.py, tests/test_cli.py, tests/test_ledger.py, tests/test_emulator.py, tests/test_whatif.py, tests/test_receipts.py, tests/test_bench.py, tests/test_budget.py, tests/fixtures/ (only what your tests need).
M-2 makes every code edit rebuild derived.zarr; keep that cheap in tests (the CI tree), and check that the existing resume and ledger-chain tests in test_pipeline.py still pass.

Interfaces between batches (use exactly these names; a batch reading a key must accept its absence for older runs):
- M-1: `uas.FLAGS` gains `profile_incomplete`; `fly_sortie` returns `wp_done` ((M,) ints, `S.wpi` at the end) and `n_wp`; `platforms/quad_uas.yaml` gets `sortie.min_profile_fraction` 1.0 (assumed, with why and replace_with); the stage-1 summary gets `vehicles[<uas id>].profile = {"wp_done_median": float, "n_wp": int, "complete_share": float}` (complete_share = share of flown sorties that reached every waypoint).
- M-5: USV failure mode `no_current_data` (in `usv.FAILS`).
- M-7: stage 1 keeps `stw_ms` per USV member; the summary gets `vehicles[<usv id>].speed.stw_ms_median` beside `sog_ms_median`.
- M-3: `Emulator.score()["coverage"][target]` is the calibration-scale (clipped logit) coverage for probability targets, and `score()["coverage_raw_p"][target]` the raw-P one; whatif/holdout.json carry both under those names; the gate uses `coverage`.
- M-11: config refuses an rf or iridium link with a glider end unless `when: surfacing` (batch C); stage 1 evaluates an iridium link with `when: surfacing` as `live & surfaced(glider end)` (batch V).
Your hand-back is r4_handback_P.md.
