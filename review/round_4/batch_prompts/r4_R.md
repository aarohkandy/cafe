You are builder R (report, statistics, credibility) for review round 4. First read review/round_4/batch_prompts/r4_common.md and follow it exactly.

Your findings: M-12, M-17, M-18, M-19, M-20, and the report parts of M-1 (part 3: the waypoint line, the profile_incomplete mode name, the new UAS_ATTITUDE_NOTE wording), M-3 (both coverage numbers, labelled as in the fix), M-5 (the no_current_data mode name) and M-7 part (2) (the reach map uses speed.stw_ms_median and says "through the water" only for it; the glider current band label).
Files you own: cafe/pm/report.py, cafe/pm/stats/intervals.py, cafe/pm/credibility.py, tests/test_report.py, tests/test_stats.py, tests/test_stats_exact.py, tests/test_credibility.py, tests/test_reach.py.
The other batches produce the new keys at the same time, so build your test inputs by hand with the names below, and keep the old wording path for runs without them. Keep cafe/pm/stats at 100 % line coverage.

Interfaces between batches (use exactly these names; a batch reading a key must accept its absence for older runs):
- M-1: `uas.FLAGS` gains `profile_incomplete`; `fly_sortie` returns `wp_done` ((M,) ints, `S.wpi` at the end) and `n_wp`; `platforms/quad_uas.yaml` gets `sortie.min_profile_fraction` 1.0 (assumed, with why and replace_with); the stage-1 summary gets `vehicles[<uas id>].profile = {"wp_done_median": float, "n_wp": int, "complete_share": float}` (complete_share = share of flown sorties that reached every waypoint).
- M-5: USV failure mode `no_current_data` (in `usv.FAILS`).
- M-7: stage 1 keeps `stw_ms` per USV member; the summary gets `vehicles[<usv id>].speed.stw_ms_median` beside `sog_ms_median`.
- M-3: `Emulator.score()["coverage"][target]` is the calibration-scale (clipped logit) coverage for probability targets, and `score()["coverage_raw_p"][target]` the raw-P one; whatif/holdout.json carry both under those names; the gate uses `coverage`.
- M-11: config refuses an rf or iridium link with a glider end unless `when: surfacing` (batch C); stage 1 evaluates an iridium link with `when: surfacing` as `live & surfaced(glider end)` (batch V).
Your hand-back is r4_handback_R.md.
