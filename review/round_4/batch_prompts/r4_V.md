You are builder V (vehicles and stage 1) for review round 4. First read review/round_4/batch_prompts/r4_common.md and follow it exactly.

Your findings: M-1 (physics, platform file and stage-1 parts; the report text is batch R's), M-5 (usv.py and stage-1 parts), M-7 part (1) (stage 1 stores stw_ms), M-8, M-10, M-11 (the stage-1 part).
Files you own: cafe/pm/physics/uas.py, cafe/pm/physics/usv.py, cafe/pm/physics/comms.py, platforms/quad_uas.yaml, cafe/pm/stage1.py, tests/test_uas.py, tests/test_usv.py, tests/test_comms.py, tests/test_comms_exact.py, tests/test_stage1.py.
M-1: with the default 1.0 the demo's UAS verdict may change; that is expected. Say in the hand-back what fraction of sorties completes at the demo's median wind if you can measure it with a short targeted run.

Interfaces between batches (use exactly these names; a batch reading a key must accept its absence for older runs):
- M-1: `uas.FLAGS` gains `profile_incomplete`; `fly_sortie` returns `wp_done` ((M,) ints, `S.wpi` at the end) and `n_wp`; `platforms/quad_uas.yaml` gets `sortie.min_profile_fraction` 1.0 (assumed, with why and replace_with); the stage-1 summary gets `vehicles[<uas id>].profile = {"wp_done_median": float, "n_wp": int, "complete_share": float}` (complete_share = share of flown sorties that reached every waypoint).
- M-5: USV failure mode `no_current_data` (in `usv.FAILS`).
- M-7: stage 1 keeps `stw_ms` per USV member; the summary gets `vehicles[<usv id>].speed.stw_ms_median` beside `sog_ms_median`.
- M-3: `Emulator.score()["coverage"][target]` is the calibration-scale (clipped logit) coverage for probability targets, and `score()["coverage_raw_p"][target]` the raw-P one; whatif/holdout.json carry both under those names; the gate uses `coverage`.
- M-11: config refuses an rf or iridium link with a glider end unless `when: surfacing` (batch C); stage 1 evaluates an iridium link with `when: surfacing` as `live & surfaced(glider end)` (batch V).
Your hand-back is r4_handback_V.md.
