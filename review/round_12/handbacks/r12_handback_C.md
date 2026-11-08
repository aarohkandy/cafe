# Round 12 batch C hand-back (environment and physics)

Branch `r12-c`, worktree `cafe-r12c`, from a8b8bb1. Findings: M-1, M-13, M-14 (code), M-10, M-15, M-16, M-19 (wording only). DECISIONS.md, CHANGELOG.md, PHYSICS, CREDIBILITY and RUNBOOK are not edited here; this file holds the text for batch F. New DECISIONS rows are numbered by F after the last one (640 at the time of review).

Printed numbers of the demo: none moves. Checked on orca against the q12 cache (`cache/tepex_c_demo/orca/umwm.zarr`): `dcp` has 5,900,050 finite values, minimum 3.9305 m/s, none under 3 and none at or under 0, so the new floor (2.0 m/s) never fires; the demo's restart count is 25 with finite errors, so `_correct_with_real` takes the unchanged path; the three `jcool=0` callers read neither `dter` nor `tkt`. The code digest in the ingest key changes with any edit, so the derived surface layer rebuilds once (as after every code edit, pipeline.py "every code edit rebuilds it") with the same values.

## M-1  fewer than three restart spectra (cafe/pm/env/surface.py)

Change: `_correct_with_real` returns `(St, None)` when the window holds fewer than three restart times (the field stays the fit alone), and also when any of the four statistics (`n_restart_times` aside) is not finite after computing. The medians use a new `_med` (NaN-ignoring, NaN without a warning when nothing is left) instead of `np.nanmedian` / `np.median` of a possibly empty list. `build` logs why when a real spectrum exists but the check is dropped. `stokes_surface` already had the `fit is None` branch (fit-only tag 0.4|u_s|); nothing else reads the fit (`SurfaceLayer.fit` is read only there; grep of cafe/ and tests/).

Decision lead-given: fit None and the fit-only tag for fewer than three restarts or a non-finite leave-one-out.

- DECISIONS row text (new row, amends 34): "The Stokes bias correction and its leave-one-out error need at least three 6-hourly restart spectra inside the window (an interior one to predict from its neighbours). With one or two, or with a leave-one-out error that is not finite, the stored check is null, the hourly field is the parametric fit alone and its uncertainty tag is the fit-only 0.4 |u_s|. | A window of 5:00 to 7:00 holds one restart hour and ran today with a NaN uncertainty printed as "nan %" (one or two restarts) or, with the weight at infinity, a correction held constant. A correction without an error estimate is not honest, so the window loses it. The 25-restart demo and the 7-restart test are unchanged."
- Amends: row 34 (add "from three restart times; fewer, or a non-finite error, leaves the fit alone with the 0.4 tag", see the new row).
- CHANGELOG line: "Stokes surface: a window with fewer than three 6-hourly restart spectra, or a non-finite leave-one-out error, keeps the parametric fit alone with its 0.4 |u_s| tag instead of a NaN uncertainty (review round 12, M-1)."
- Doc sentences: PHYSICS 4.4 (Stokes correction): "The correction is applied only when the window holds at least three restart times; otherwise the field is the fit alone, tagged 0.4 |u_s|." RUNBOOK (short windows, if a section lists them): a window of under about 12 h may hold fewer than three restart hours and then has no Stokes correction; the log line says "fewer than three restart spectra".
- Checked, could break: the only caller of `_correct_with_real` is `build`; the only reader of its result is `SurfaceLayer.stokes_surface` (None already handled). Old caches written with a bare NaN in `stokes_fit_check` are rebuilt because the key holds the code digest. `json.dumps(None)` is `null` and `SurfaceLayer` reads it with `json.loads(... "null")`. Test: `tests/test_surface.py::test_build_with_fewer_than_three_restart_spectra_or_no_finite_error_keeps_the_fit_alone` (0, 1, 2 restarts and an all-NaN real spectrum; fails before on all four: IndexError or NaN fit; passes after). The 7-restart test and the no-restart test are unchanged and pass.

## M-13  coare35 with a cp of 0 or tiny, and the drag cliff at the floor (cafe/pm/env/coare.py)

Change (second pass, after the adversary proved the first one): the wave-age and sea-state forms now fade in linearly with the dominant phase speed. `wmix = clip((cp - CP_MIN) / (CP_FULL - CP_MIN), 0, 1)` (0 for a NaN cp), `CP_MIN = 2.0`, `CP_FULL = 3.5` m/s, and `charnock()` returns `(1 - wmix) * Charnock + wmix * (sea-state or wave-age form)` where `wmix > 0` and plain Charnock elsewhere. So cp of 0, negative, tiny or at most 2 is exactly Charnock (as a NaN cp), cp from 3.5 up is the pure form, and between the two the drag is continuous. This is the one place that picks the roughness form (`coare35` is the only consumer).

Why the first pass was not a fix: the hard switch at 2.0 was a step in Cd of 1.19e-3 to 3.07e-3 (U 8 m/s, sigH 1.5), 1.05e-3 to 1.91e-3 (U 3), and without sigH 2.37e-3 to 3.55e-3 (U 20). Raising the floor to 3 would only move the same step (about 2 times at U 8), so the cause is the step, not the value. The fade removes it; the demo is not touched, since its smallest dcp (3.9305 m/s over 5.9 million sea values) is over `CP_FULL`, where `wmix` is exactly 1.0 and the expression is `0.0 * Charnock + 1.0 * form`, bit-for-bit the form (`CP_FULL <= 3.93` is asserted by a test). The coare self-checks and the pycoare comparisons use cp of 6 to 14, also over `CP_FULL`. The lead's bound ("floor under about 3 m/s") is met: nothing under 2 m/s takes any wave form and the pure form starts at 3.5, under the demo's 3.93.

Printed numbers of the demo: none moves (same reasoning; the derived surface layer rebuilds once because the code digest changes).

- DECISIONS row text (new row, amends 29): "COARE uses the wave-age and sea-state roughness in full only where UMWM's dominant phase speed is at least 3.5 m/s (`CP_FULL`); between 2 m/s (`CP_MIN`) and 3.5 m/s the Charnock parameter is blended linearly from the Charnock value to that form, and at 2 m/s or under, or with a missing value, it is the Charnock form. | cp = 0 gave NaN u*, z0, L and Cd; and a single switch speed gave a step in Cd of 1.5 to 3 times where it sat (Cd 1.2e-3 to 3.1e-3 at U = 8 m/s), which a drag that depends on the sea state should not. The two speeds are the builder's, chosen under the 3.93 m/s that is the smallest dcp of the demo window, so the demo is unchanged. The linear fade is a guard against the step, not a calibration of young-sea drag."
- Amends: row 29.
- CHANGELOG line: "COARE: the wave-age and sea-state roughness fade in between a UMWM phase speed of 2 and 3.5 m/s (Charnock at 2 and under, 0 in calm or ice, instead of a NaN u*, z0, L and Cd and a step of up to 2.6 times in Cd) (review round 12, M-13)."
- Doc sentence: PHYSICS (section with "the roughness is the sea-state form wherever UMWM has a value", about line 162): "... wherever UMWM has a value of at least 3.5 m/s for dcp; from 2 to 3.5 m/s the Charnock parameter fades linearly into it, and at 2 m/s or under it is the Charnock form."
- Checked, could break: callers are `surface._coare_grid` (passes UMWM dcp), `coare.warm_layer` (passes no cp), the three `tao.py` `jcool=0` calls (no cp) and the self-checks in `coare.receipts` (cp = 12 and 6 to 14). None has a cp under 3.5. The sibling `sigH` needs no guard: it is read only where `wmix > 0`, and a sigH of 0 is finite.
- Tests (`tests/test_coare.py`): `test_a_phase_speed_below_the_floor_gives_the_charnock_result_not_nan` (18 cases, cp 0, -1, 1e-3, 0.3, 1.9 and 2.0 against sigH none, 0, 2: equal to the no-cp result; fails on the cp-0 cases before the first pass); `test_the_drag_has_no_step_in_the_phase_speed` (U 3, 8, 20, with and without sigH, cp 0.5 to 6 in 0.01 steps: Cd moves under 6 percent per step; fails on the first-pass code in all six cases with steps of 12 to 230 percent, which is the adversary's finding); `test_the_wave_form_is_pure_from_cp_full_and_charnock_up_to_cp_min` (the result at `CP_FULL` does not depend on `CP_MIN`, `CP_FULL` is under the demo's 3.93; fails before with no `CP_FULL`). The first-pass test "at the floor still uses the wave-age form" is replaced, not weakened: its premise (a jump at the floor) is the defect.

## M-14  coare35 with jcool=0 (cafe/pm/env/coare.py)

Change (lead decision, code): with `jcool=0` the returned `dter` and `tkt` are zeros (no cool skin), set once after the loop. Nothing above can see this: every use of `dter` in the loop and after is `* jcool`, and `tkt` feeds only the next `dter`. Docstring adds the cool-skin layer thickness unit and the jcool=0 sentence. Callers listed first: `tao.py:328, 441, 453` (jcool=0, read neither key), `coare.py` 429 and 450 (self-checks, jcool=0, read ustar/Cd only), `warm_layer` (default jcool=1, reads `dter` for the skin, unchanged), `surface._coare_grid` (jcool=1). Nothing in cafe/ or tests/ reads `dter` or `tkt` at jcool=0.

Honest note: the reviewer's check says reference COARE 3.5 (pycoare) also returns the computed `dter` at jcool=0. This change departs from that diagnostic on purpose (the lead's decision); the fluxes still match pycoare (the receipts compare ustar, hsb, hlb and Cd, all at jcool=1 or unaffected, and pass).

- DECISIONS row text (new row, optional; no existing row concerns it): "`coare35(..., jcool=0)` returns `dter` = 0 and `tkt` = 0: with the skin temperature given there is no cool skin to report. | The loop never applied the estimate it used to return (0.24 K, 6e-4 m), so a caller reading it would have been misled. No caller read it."
- Amends: none.
- CHANGELOG line: "COARE: with jcool=0 the returned cool-skin dT and thickness are 0, not the unused estimate (review round 12, M-14)."
- Test: `tests/test_coare.py::test_without_the_cool_skin_dter_and_tkt_are_zero` (fails before: dter 0.24 K).

## M-10  diurnal jet "+-0.1 m/s" (cafe/pm/env/surface.py, subgrid.py): wording and deletion

Change: deleted the unread `jet_half` (grep: assigned once, read nowhere); the surface.py header no longer says the half-range is the uncertainty and now says every member gets the midpoint, the range is not sampled and `current_extra` returns the base uncertainty; `subgrid.diurnal_jet`'s docstring says only the receipts call it. No behaviour change. The code option (per-member draw, stage1.py) is not taken, as decided.

- DECISIONS row text (amends 39, edit in place): replace "0.2 +- 0.1 m/s" by "0.2 m/s (the midpoint of the 0.1 to 0.3 range)" and add to the reason: "Every member gets the midpoint: the range is not sampled per member and the jet carries no uncertainty in the run; `subgrid.diurnal_jet` draws it per member and only the receipts call it. Sampling it would shift USV and glider P(fail) and is left to the owner."
- CHANGELOG line: "Diurnal jet: documented that all members use the 0.2 m/s midpoint (the 0.1 to 0.3 range is exercised by the receipt only) and removed the unread jet_half (review round 12, M-10)."
- Doc sentences: PHYSICS 5.4 line 369: replace "+-0.1 as the sigma" by "no uncertainty is carried; the run uses the midpoint for every member, the 0.1 to 0.3 range is drawn only by the receipt". CREDIBILITY: if the jet is described as sampled, same change.
- Checked: `jet_half` has no reader in cafe/ or tests/ (`jet_mid` is read by `current_extra` and tests/test_surface.py:136, kept).

## M-15  zero-wind member error (cafe/pm/env/perturb.py): wording only

Change: header of perturb.py (Wind bullet) and a comment on the `np.where(sp > 1e-9, ...)` line say that member wind error is a factor on the base vector, so it is not applied where the base speed is 1e-9 m/s or less, a window of exactly zero wind has no wind spread, and at 1.1e-9 m/s the full bias applies. No code or test change (a pin test was offered by the finding, not asked for here).

- DECISIONS row text (new row): "Member wind error (bias, AR(1) noise) is a factor on the base wind vector and is not applied where the base speed is 1e-9 m/s or less; a window of exactly zero wind therefore has no wind spread. | Wind direction is undefined at zero, so staying zero is one defensible limit; a seeded-direction convention would change every small-wind number and the calm-window verdicts. Exactly zero wind comes from a fixture or a synthetic calm window, which the ingest accepts (RUNBOOK:287, rows 598 and 632). `current()` is multiplicative, so zero current staying zero is right."
- Amends: none (relates to 598, 632).
- CHANGELOG line: "Documented that member wind error is not applied where the base wind is exactly zero (review round 12, M-15)."
- Doc sentence (PHYSICS or CREDIBILITY limitation): "A calm window of exactly zero wind has no wind-error spread." Report note: optional, not added.

## M-16  alpha and beta constants (cafe/pm/env/surface.py): wording only

Change: the module docstring now says TEOS-10 alpha and beta are at the fixed SA 35, CT 28, p 0, not adapted to the box, and `density_extra` is too large by alpha(28 C)/alpha(CT) outside the tropics (2.8 times at 5 C). Code unchanged.

- DECISIONS row 40 (amend in place): replace "(box mean surface)" and the second sentence by: "SA 35, CT 28 are fixed tropical constants, not the box's mean state; outside the tropics `density_extra` is too large by the alpha ratio (2.8 times at 5 degC). The demo (SST 299-303 K) is unaffected."
- CHANGELOG line: "Corrected the docstring: alpha and beta are fixed tropical constants, not the box mean (review round 12, M-16)."
- Doc sentence: CREDIBILITY limitation line: "The warm-layer and rain-lens density change uses alpha and beta at 28 degC; a box colder than the tropics gets too large a change (2.8 times at 5 degC)."

## M-19  "the Environment has no T(z)" (cafe/pm/physics/glider.py): wording only

Change: glider.py header now reads "The Environment API does not expose the ocean store's temperature (`Ocean.temperature` exists but is not wired to the protocol, `Environment` or the perturbed wrapper)". Code unchanged; the code option (wire T(z)) is not taken.

- DECISIONS row 49 (amend in place): replace "The Environment has no T(z). Replace with the ocean store's temperature field." by "The Environment API does not expose the ocean store's temperature: `Ocean.temperature` exists but is not wired to the protocol, `Environment` or the perturbed wrapper. Wiring it (and sourcing T_ref and alpha_T) replaces the profile."
- CHANGELOG line: "Reworded 'the Environment has no T(z)': the ocean store's temperature exists and is not wired (review round 12, M-19)."
- Doc sentences: PHYSICS line 611 ("the environment holds no T(z)") and CREDIBILITY L06 ("the glider T(z) profile is assumed" is true; add "the store's temperature is not wired").

## What I checked

- Whole files run on orca (2 CPUs): tests/test_coare.py, test_surface.py, test_perturb.py, test_perturb_env.py, test_subgrid.py, test_tao.py, test_environment.py, test_glider.py (see the result in the report to the lead); `ruff check cafe/pm tests` and `mypy cafe/pm` clean.
- The new tests fail on the a8b8bb1 sources (detached throwaway worktree, removed) and pass on r12-c: 21 failures before (first pass: 15 floor cases, floor boundary, cool skin, 4 restart cases; second pass: the 6 step cases and the CP_FULL test fail on the first-pass code, 7 more failures), none after.
- 100 % env coverage: both new lines of coare.py (floor, jcool=0) and the new early return and `_med` empty branch in surface.py are exercised by the new tests; the coverage run itself is the gate's.

## Needs from other batches

- Batch F: the DECISIONS rows and CHANGELOG lines above, the PHYSICS (4.4, about 162, 354, 369, 611) and CREDIBILITY (L06 and the density limitation) sentences, in the order of the finding list. F should number the new rows (M-1, M-13, M-14, M-15) after 640.
- Batch D (stage1.py): nothing needed from it; M-10's code option (a per-member jet draw in stage1.py:426) is not taken, so stage1.py is untouched.
- No other batch must change code for these.
