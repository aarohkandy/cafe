# Round 8 hand-back, lead item L1 (look-ahead findings)

Two findings. Branch `r8-merged`, worktree `/Users/aaroh/Downloads/everything/cafe-r8m`, burst dirs `pm_l1`, `pm_l1b`, `pm_l1m`. The DECISIONS row is written with `?` for the number (the lead numbers it on merge); the CHANGELOG line is below it.

## Finding 1: platform bounds covered the angles and the USV mass only

### Callers checked
`physics.check_params` is called by `glider.load_platform`, `usv.load_platform` (twice, params and mission_defaults) and `uas.load_platform` (per group), and through them by `hangar`, `validate`, the stage-1 vehicle loaders and `tests/test_platform_required.py`. Nothing else substitutes values into these tables. What the change could break:
- a shipped platform file outside a new bound: the existing `test_the_shipped_platform_files_satisfy_their_loaders` and the whole of `test_platform_required.py` pass; the bounds were set from the shipped values (seaglider pitch 14, UAS 6 cells, saildrone loa 7 m, ...) with a wide margin;
- the existing assertions on the old messages: the new bounds use `pos<=max` and `frac<=max`, whose message still begins "above 0" / "from 0 up to", so the M-4 cases (`mass_kg` 0.0, `rating_m` NaN, `reserve_frac` 1.5 and 1.0) pass unchanged. No existing assertion was edited;
- the model modules that read these keys (`glider`, `uas`, `usv`) take the same values as before for every value inside the bounds.

### Root change
- `cafe/pm/physics/__init__.py` `_rule`: new kind `int:lo:hi` (a whole number in a closed interval; the message says "a whole number from 1 to 24"). `check_params` docstring names it. Every table can now say it.
- Tables (the bounds are our choices, each is in the refusal message):
  - glider (`_COMMON` and the kind tables): `pitch_deg` `angle90`; `rating_m` at most 11000; `windage` at most 0.2; `reserve_frac` below 1 and at most 0.5; seaglider `length_m` at most 20, `mass_kg` at most 1e4; slocum `mg` (its mass) at most 1e4.
  - UAS: `cells` `int:1:24`; `reserve_frac` at most 0.5; `airframe.mass_kg` at most 100; `energy_wh` at most 1e4; `v_nom_cell` 1 to 5; `peukert_exponent` 1 to 2 (a Peukert exponent below 1 makes a pack give more than its capacity at a high current); `max_tilt_deg` and `tilt_exceedance_deg` `angle90` (the unit is degrees, the same class as the pitch).
  - USV: `loa_m` at most 100; `wing_area_m2` at most 100; `gm_m` at most 10; `rf_antenna_height_m` at most 50; `battery_wh` at most 1e6; `wind_height_m` at most 50; `hotel_w` at most 1e4; `kyy_frac` 0.05 to 1.
- `docs/PHYSICS.md` platform-leaves row names `angle90` and `int:lo:hi` and the round-8 bounds.

### Tests (fail first)
`tests/test_platform_required.py`:
- `test_r8_l1_an_implausible_platform_number_is_refused_naming_the_field_and_its_bound` (31 cases: every (file, key, value) of the finding, plus cells 0, peukert 0.5, kyy_frac 0, slocum `mg`, UAS tilt keys, glider `reserve_frac`);
- `test_r8_l1_the_bound_itself_and_a_whole_number_written_with_a_dot_load` (24 cells, 1 cell, `4.0` cells, pitch 89, `kyy_frac` 1, Peukert 1: the bounds are inclusive and a whole number written with a dot still loads);
- `test_r8_l1_every_angle_in_a_shipped_platform_file_has_a_bounded_kind` (the class: every key whose unit is `deg` in the four shipped files has a kind other than pos/nonneg/any).

Mutant: the unfixed tree (detached worktree of HEAD 139c27a with the new test file copied in), run on cafe-burst: 31 fail, the 6 inclusive-bound/whole-number tests pass (they hold on both trees by design, as a guard that the fix did not over-refuse). Fixed tree: all of `test_platform_required.py` passes (93 tests).

### Verification
- `ruff check cafe/pm tests` and `mypy cafe/pm` clean (cafe-burst).
- Wide run on cafe-burst (`-n 6`) of test_glider, test_usv, test_uas, test_uas_exact, test_stage1, test_cli, test_config, test_whatif, test_credibility, test_receipts, test_perturb, test_reach, test_subgrid, test_config_docs, test_stage3: one failure, `tests/test_whatif.py::test_a_uas_flip_is_answered_without_a_median_track` (`flips["uas"]["best"]` is None). It fails the same way on the unfixed HEAD 139c27a (detached worktree, same command), so it is not caused by this change; it is open for the lead. `test_platform_required.py` and `test_config_docs.py` re-run after the final line-length edit: pass. The full suite was not run.
- `python -m cafe.pm audit --code-only`: the only problem is the missing `docs/mutation.json` (the stored mutation record), as before.

### Not done (for the lead to decide)
The bare `pos`/`nonneg`/`any` kinds remain on keys the finding did not list and that are not angles: for example USV `lwl_m`, `beam_wl_m`, `wetted_area_m2`, `wing_span_m`, the keel and rudder sizes; glider `volmax_cc`, `battery_J`, `vbd_*`, `hd_a/b/c`; UAS rotor, controller and sortie keys. Most of these are dimensionless coefficients or gains with no physical ceiling that is not itself a modelling choice; I did not invent bounds for them. The new `deg` test is the structural guard for the angle class; a guard for the remaining quantities would need a bound per key from the lab.

### DECISIONS
`| ? | Platform numbers have plausibility bounds, each named in the refusal: angles (glider pitch, UAS max_tilt_deg and tilt_exceedance_deg) are above 0 and below 90 degrees; glider rating_m at most 11000, windage at most 0.2, seaglider length_m at most 20, seaglider mass_kg and slocum mg at most 1e4; UAS cells a whole number 1 to 24, reserve_frac (glider too) at most 0.5, mass_kg at most 100, energy_wh at most 1e4, v_nom_cell 1 to 5, peukert_exponent 1 to 2; USV loa_m, wing_area_m2 at most 100, gm_m at most 10, wind_height_m and rf_antenna_height_m at most 50, battery_wh at most 1e6, hotel_w at most 1e4, kyy_frac 0.05 to 1. \`physics.check_params\` has a new kind \`int:lo:hi\`. A test requires every key in degrees in a shipped platform file to have a bounded kind. The bounds are choices, not measurements; keys not listed (coefficients, gains, the other sizes) keep pos/nonneg/any. | Review round 8, lead item L1. M-28 bounded wing_stall/trim, heel_target, keel_stall and the USV mass only; 12 probes (pitch 120 and 1e6, 2.5 cells, 1e12 kg, ...) loaded. A pitch over 90 degrees flips the sign of the glide, a fractional cell count has no pack, and the others ran into float overflow or a 1e9 W hotel load later. |`

### CHANGELOG
`Platform files refuse an implausible angle (glider pitch, UAS tilt limits), a fractional or huge cell count and an absurd mass, energy, size or hotel load, each with its bound in the message; new check_params kind int:lo:hi (review round 8, L1).`

## Finding 2: M-47 singular fix covers 3 of 9 count units

No change: already fixed in this branch by L0 (commit 139c27a, `report._singular`, written for the same pattern the finding names). The finding read the pre-L0 `SINGULAR` table (3 entries); on HEAD `_txt` calls `_singular`, which takes the last word of any unit that is a plural noun (4 or more letters, ends in s, not ss, not a fraction) and drops the s (`notches` to `notch`).

Checked on HEAD, not assumed:
- `test_r8_l0_every_unit_a_count_of_one_can_carry_is_singular_and_the_rest_are_left_alone` passes on cafe-burst. It renders v=1 and v=2 for receipts, inputs, runs, rows, samples, cores, candidates, notches, members and "held-out points", and scans every `num(..., "unit")` in `cafe/pm` against that list. This is the single test the finding asks for.
- The other call, `vals(...)`, is only ever given `deg` and the epoch unit; `_txt` handles its `values` branch ("1 value deg").
- Left as it was: the phrasing "N of M windows" / "N of M receipts" (report.py lines 144-147, 1516) reads "1 of 1 windows". It is a literal f-string, not a count node, and "of" phrases are outside the finding; say so if it should change.
