# Round 19, batch A hand-back (branch `r19-a`, cut from 51eb433)

Findings: M-1, M-5, the A-9 test of M-16. Open decisions OD-1 (a) and OD-5 (a) taken as the defaults: **awaiting the owner**.

## M-1: a link with two glider (or two UAS) ends

- Changed (`cafe/pm/stage1.py`): `_surfaced` is now an AND over EVERY glider end (new `_ends` helper); the UAS branch of `evaluate_link` is `_airborne` (new, the old sample-and-hold / interpolation code moved out unchanged) AND-ed over every UAS end, and the 30 s sortie grids of both UAS ends are unioned into `t` (before: the first UAS's only). RF, acoustic and Iridium all route through `_surfaced`, so one change covers the three kinds. `_ends(..., need=True)` raises a `ConfigError` naming the run when neither end is of the class (before: a `KeyError`; a bare AND over nothing would have been a silent "required everywhere").
- A submerged glider's margin: nothing changes in `_pos` (its `antenna_m` is still added to the height whatever the depth). It no longer matters: a moment with either glider under water is not required, so `margin_db` is NaN there (the probe's finite margin at depth is gone). One-glider links are unchanged (existing tests pass).
- `summarize` gains `n_never_required` per link (members with `need_count` 0; None for a batch without counts). It is a new key in `summary.json`; nothing reads it yet. **Cross-batch (B, report.py):** a page can print "never required in n members" from `links[<id>].n_never_required`; `report.json` was not touched here. `frac` stays 1.0 and `success` True for such a member (the existing NOT EXERCISED verdict still covers the all-members case).
- Tests (`tests/test_round19_a.py`), run on the UNFIXED code first (orca job `r19a_1`): RF, Iridium, acoustic two-glider order independence and overlap count (60 against 30), the reviewer's scene g1 up always / g2 never (217 against 0), two UAS ends with and without sortie grids (100 against 50; 41 against 21), `n_never_required` (KeyError), all failed. They pass after (job `r19a_11`). The ConfigError test is new behaviour (not run before the fix).

## M-5: acting columns

- `TRACK_ACTS["uas"]` gains `battery_capacity_scale`, so `link_acts` of `usv-uas-rf` (and any link with a UAS end, RF or acoustic) lists it; a glider's, USV's and shore/ship ends do not. `UNSEEN[("uas","profile_margin")]` gains `wind_direction_bias` (so `ACTING` and `SENS_ACTS["uas"]` list it; the CI probe test subtracts `UNSEEN`, so its expectation is unchanged). `ACTS` (what `credibility.py` counts "used by" from) is untouched; a test pins it and `CLASS_PRIORS`. Comments in stage1.py updated (the "inert" wording lived in the test name and DECISIONS 992, not the code).
- Not changed: `PATTERN_ACTS["uas"]` (Iridium with a UAS end), unreachable because the loader refuses `uas_airborne` for Iridium.
- Tests: `link_acts` pins, the UNSEEN/ACTING rows (failed before), and the 18 h probe of reviewer B (`usv` + `uas` + `usv-uas-rf`, battery scale 0.70 against 1.00, need_count differs: before the fix this part already passed, showing 39 against 48, and the `link_acts` assertion after it failed; after, green).
- `tests/test_round18_c.py`: the link-acts probe now uses the 18 h window (was 9 h) and also moves `battery_capacity_scale` to explicit 0.70/1.00 (the prior's 5 % quantile is 0.92, which never reaches the battery edge at 0.78, so quantiles alone cannot hold the column); asserts `battery_capacity_scale` is in `seen`.
- `tests/test_round18_x.py` (the one hunk assigned by merged.md to B, applied here at the lead's instruction): `test_x2_wind_direction_acts_on_the_uas_battery_reserve_and_not_on_its_profile_share` renamed `..._and_on_its_profile_share_only_at_the_battery_limit`: ACTING lists `wind_direction_bias` for the profile row, `moved` (demo record) still does not, UNSEEN has the four columns. **Batch B: skip this hunk (or expect an identical conflict there).**
- q21 note for G: more acting columns raise the permutation noise floor of a row (B-4's figures: 0.155 for 2 columns, 0.186 for 4 at n = 64). The UAS link row gains one column and the UAS profile row gains one, so their floors may move at q21: re-evaluate. q20's UAS vehicle-row floor is not recomputed here.

## M-16, A-9 (U10)

`test_r19_a9_...` captures the length passed to `_fewest_boxes` and asserts `uas.sortie_t_max(so) + 60.0` (1980 s, not `duration_s` + 60 = 1260 s). Passes on the real code (job `r19a_5`), FAILS on the mutant `so["duration_s"] + 60.0` (job `r19a_6`, rc=1; the mutation was applied to the worktree for that run only and reverted).

## Pins moved (each is the product's new, intended answer)

- `tests/test_stage1.py::test_the_summary_ranks_the_margin_the_simulator_stored_...`: `battery_capacity_scale` was asserted NOT in the S1 of `usv-uas-rf` ("no end's battery moves a link"); now asserted IN (a UAS end), and still NOT in the glider-ship acoustic link's.
- `tests/test_round17_c.py::test_r17_m8_each_vehicle_and_link_ranks_only_the_columns_its_simulator_reads`: the RF row gains `battery_capacity_scale`.
- `tests/test_round18_c.py`: `link_acts(usv-uas rf)` pin gains `battery_capacity_scale`; probe window and extra battery probe as above.
- `tests/test_round18_x.py`: the one hunk above.

## Decisions for DECISIONS (text)

1. (OD-1 (a), amends the rule of `evaluate_link`'s docstring) A link `when: surfacing` is required only while EVERY glider end is on the surface (RF, acoustic, Iridium); `when: uas_airborne` only while EVERY UAS end flies. The verdict no longer depends on the order of `a` and `b`. The loader (`config.py`) is unchanged and still accepts two glider ends. A link with no end of the class named by its `when`, among the run's vehicles, is a `ConfigError`, not a link never required. The link summary carries `n_never_required` (members with no required moment: `frac` 1.0 and pass for them, as before). Awaiting the owner.
2. (OD-5 (a), amends 958 and 992) `TRACK_ACTS["uas"]` lists `battery_capacity_scale` (the battery size ends a sortie early, which moves the moments a link with a UAS end is required at), and `UNSEEN[("uas","profile_margin")]` lists `wind_direction_bias` (it moves the profile share only where the sortie is battery-limited, which no probe reaches); 992's word "inert" is withdrawn for it. Awaiting the owner; q21 re-evaluates the UAS rows' floors.

## Verification (orca, proot, 2 CPUs per job)

On the final tree (all rc=0, logs `~/cafe-worker/logs/<job>.log`):
- `r19a_11` (rc=0): `tests/test_round19_a.py`, `test_round18_c.py`, `test_round18_x.py`, `test_stage1.py`, `test_round17_c.py`.
- `r19a_12` (rc=0): `ruff check cafe/pm tests` clean, `mypy cafe/pm` clean (55 files).
- `r19a_9` (rc=1 on the tree before the `test_round17_c.py` pin moved; source unchanged since): `test_round15_a`, `16_a`, `17_a`, `17_c`, `17_m`, `17_b`, `test_report`, `test_credibility`, `test_round18_a`, `18_m`, `test_whatif`: one failure only, `test_round17_c.py::test_r17_m8_...` (the moved pin above, green in `r19a_11`). The rest of that job passed; it was not rerun after the pin edit.
- Before the fix: `r19a_1` (new file on the unfixed tree: 9 failed, A-9 passes on the real code); `r19a_6` (U10 mutant: A-9 fails, rc=1).
## Not verified

- An acoustic two-glider link through a real `run_batch` and a `uas_airborne` link with two UAS ends through a real batch (only `evaluate_link` on synthetic scenes); the Bellhop path for two surfaced gliders (the acoustic test checks the required moments only).
- M-6 (the Slocum step's mechanism comment at stage1.py:58) is in NO batch of merged.md's list; I did not touch it (outside the brief). Text for it: the step is a count of surfacings at the window's end, one surfacing fewer (comm_J 3.5 W x 370 s + 414 J + the pump 38.2 J = 1747.2 J = 1.62e-4 of the usable pack), and the wind columns can do the same with a smaller probability.
- `test_pipeline.py`, the full suite, the gate and coverage were not run (stage 1 is not in the 100 % gated packages).

## Orca leftovers (all mine, in `~/cafe-worker`)

Directories `cafe/pm_r19a`, `cafe/pm_r19a_b`; markers `cafe/.pmx.job.pm_r19a*` if present; `cafe/pmdata/lint_r19a.sh`; logs `logs/r19a_1.log` to `r19a_12.log`; no tmux session of mine should remain. Nothing removed (kept for the lead to inspect).
