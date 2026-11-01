You are builder C (mission config and environment) for review round 4. First read review/round_4/batch_prompts/r4_common.md and follow it exactly.

Your findings: M-6, M-9, M-11 (config and schema part), M-13, M-14, M-15, M-16.
Files you own: cafe/pm/config.py, cafe/schemas/mission.json, cafe/pm/env/orca.py, cafe/pm/env/environment.py, cafe/pm/env/perturb.py, missions/*.yaml (only if a new refusal makes a shipped mission invalid; say so), tests/test_config.py, tests/test_environment.py, tests/test_perturb_env.py, tests/test_perturb.py.
Keep cafe/pm/env at 100 % line coverage.

Interfaces between batches (use exactly these names; a batch reading a key must accept its absence for older runs):
- M-1: `uas.FLAGS` gains `profile_incomplete`; `fly_sortie` returns `wp_done` ((M,) ints, `S.wpi` at the end) and `n_wp`; `platforms/quad_uas.yaml` gets `sortie.min_profile_fraction` 1.0 (assumed, with why and replace_with); the stage-1 summary gets `vehicles[<uas id>].profile = {"wp_done_median": float, "n_wp": int, "complete_share": float}` (complete_share = share of flown sorties that reached every waypoint).
- M-5: USV failure mode `no_current_data` (in `usv.FAILS`).
- M-7: stage 1 keeps `stw_ms` per USV member; the summary gets `vehicles[<usv id>].speed.stw_ms_median` beside `sog_ms_median`.
- M-3: `Emulator.score()["coverage"][target]` is the calibration-scale (clipped logit) coverage for probability targets, and `score()["coverage_raw_p"][target]` the raw-P one; whatif/holdout.json carry both under those names; the gate uses `coverage`.
- M-11: config refuses an rf or iridium link with a glider end unless `when: surfacing` (batch C); stage 1 evaluates an iridium link with `when: surfacing` as `live & surfaced(glider end)` (batch V).
Your hand-back is r4_handback_C.md.
