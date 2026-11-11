# Round 15, batch B handback: M-7, M-9, M-10, M-11, M-13, M-14, M-15, M-16, M-17, M-18, M-19, M-20, M-21, M-23, M-24, M-25, M-27

Branch `r15-b` (cut from 09f4ce4), worktree `cafe-r15b`, orca dirs `pm_r15b` and the probe dirs `pm_r15b_*` (all removed at the end, with their logs; the detached mutant worktrees `cafe-r15b-mut*` too). Documents edited: `review/orca/PROBLEMS.md` (rows P-R15BB1 to P-R15BB3), a stored measurement `config/fea_hull_mesh_study.json` (new), `config/assumptions.yaml` (values and `why` texts, which are code), `cafe/schemas/mission.json` and `platforms/quad_uas.yaml` (text), and this file. DECISIONS, CHANGELOG, RUNBOOK, PHYSICS, QUESTIONS_FOR_LAB, CREDIBILITY are batch D's: their text is below. New DECISIONS rows are numbered by D after the last row (845 at 09f4ce4 on this branch); "amends N" names an existing row.

## The FEA decision (M-14, M-15, M-23, M-16, M-17 first, as the lead asked)

**What the default glider hull's collapse depth really is under the model's own rules.** Hull: ellipsoid 1.8 x 0.30 m (semi-axes 0.9, 0.15, 0.15), 8 mm Al6061, 500 m of sea water, `windows.fea_window(buckle=True)`, collapse depth = 500 m x buckling factor x `hangar.KNOCKDOWN` (0.5). The study (orca, proot, 2 CPUs, five meshes, stored in `config/fea_hull_mesh_study.json`):

| mesh | elements | dead-load factor | follower-corrected factor | collapse depth | wall time |
|---|---|---|---|---|---|
| L/20 | 1,408 | 1.94033 | 1.4552 | 363.8 m | 65 s |
| L/30 | 1,680 | 1.88437 | 1.4133 | 353.3 m | 68 s |
| L/45 | 2,944 | 1.77970 | 1.3348 | 333.7 m | 555 s |
| L/70 | 5,546 | 1.76333 | 1.3225 | 330.6 m | 584 s |
| L/100 | 10,558 | 1.75724 | 1.3179 | 329.5 m | 645 s |

Successive steps of the factor: -2.9 %, -5.6 %, -0.92 %, -0.35 %. The 2 % rule ends at L/45 to L/70; **I chose L/70** (within 0.35 % of the finest, L/45 is 1.3 % from it; L/70 costs no more than L/45; `hangar.py` already used it). **The converged collapse depth of the default glider hull is 331 m (330.6 at L/70, 329.5 at L/100), against 364 m today (L/20): the 364 m was 10 % unsafe.** The lowest mode of the hull is a 2-lobe mode at every mesh (lobe count read from the mode shape: 1.996, 1.998, 2.000, 2.001, 2.003), so M-15 changes nothing for this hull: the 3/4 follower correction belongs to this mode. The Slocum hull assumed by stage 3 (ellipsoid 1.5 x 0.22 m, same wall and material, L/70, 4,864 elements, 450 s) collapses at **654.6 m** (factor 2.6186, 2-lobe), so glider_2n's 500 m order is inside it. The stress utilization of the default hull at L/70 is 0.305 (was 0.367), the buckling one 1.512 (was 1.374); `utilization` (the larger) 1.512.

**M-15, the rule (one, documented).** The linear buckling step of CalculiX treats the pressure as a dead load; the sea's follows the wall. For an n-lobe ring or tube mode the follower critical pressure is (n^2 - 1) / n^2 of the dead-load one (3/4 at n = 2, 8/9 at n = 3, near 1 for a sphere). `fea.follower_correction(n)`; `fea.lobe_count(nodes, el, u)` reads n from the mode's normal displacement (circumferential derivative about the principal axis for a body with a long axis; the whole-surface gradient, sqrt(l (l + 1)), for a body with no long axis, a sphere); `fea._follower_buckling` takes the least of correction x eigenvalue over the modes that can set it (those below the lowest eigenvalue / 3/4, so a 2-lobe mode just above a 4-lobe one is not missed), and falls back to 3/4 for all, with `buckling_lobes` None, where there is no mode shape (solid mesh, no `.frd` block). The result carries `buckling_factor_dead_load`, `buckling_lobes` and `buckling_follower_correction` beside `buckling_factor`. **The 0.5 knockdown does not cover it**: the knockdown (`hangar.KNOCKDOWN`, "NASA SP-8007-style", a comment only, not re-read) is an allowance for shell imperfection, applied once to the corrected factor; the follower correction removes a bias of the linear analysis (a stiffer load than the sea's). They are two allowances for two different things and both stay, each applied once. Both are now applied to what they belong to.

Closed form, as reviewer C did (orca, Al6061, p = 1 MPa, R 0.1 m, t 3 mm; reported = follower-corrected):

| case | lobes | dead load | reported | closed form | reported / closed |
|---|---|---|---|---|---|
| long tube L 3 m (41,610 nodes) vs Bresse | 2 | 0.7652 MPa | 0.5739 | 0.5461 | 1.051 (dead 1.401) |
| tube L 1.2 m vs von Mises n = 2 | 2 | 1.0279 | 0.7709 | 0.7332 | 1.051 (dead 1.402) |
| tube L 0.6 m vs von Mises n = 3 | 3 | 2.0283 | 1.8029 | 1.6857 | 1.070 (dead 1.203; flat 3/4 gave 0.902) |
| sphere R 0.15 m, t 3 mm vs Zoelly 33.71, h 0.04 / 0.03 / 0.02 | 13 | 35.98 / 35.98 / 34.62 | 35.77 / 35.77 / 34.42 | 33.71 | 1.061 / 1.061 / 1.021 (dead 1.067 / 1.067 / 1.027) |

With the flat 3/4 the sphere would read 0.80 of Zoelly at h 0.04 and the 3-lobe tube 0.90 of von Mises (reviewer C: 0.78 and 0.90). The remaining distance above the closed form is the mesh (it falls with h for the sphere: 6.1 %, 6.1 %, 2.1 %) and, for the tubes, the flat end caps, which restrain more than the simply supported ends of the formulas.

**M-23.** `vm_max` is gone from `fea.solve`, `windows.fea_window` and `hangar._case` (the app's load-case table loses `vm_max_mpa`); `vm_p99` stays the stress basis (row 730). The p99 can under-report a true hot spot (the clamped tube reads 13.1 MPa against 15.0 at the beam root, reviewer C): that is the documented choice (row 730), now said in a comment where `vm_p99` is computed.

**M-16, M-17.** `fea.py` docstring rewritten (mean-rigid-motion equations, `reaction` only for a clamped solve); the module self-test is `fea.selftest(workdir)` (called by `python -m cafe.fea`), no longer indexes `r['reaction']`, and runs on the real solver in a test. `fea.solve` raises `ValueError` before the mesher for a shell with no finite positive wall (None, 0, negative, NaN, inf, a bool, a string) and for `body_accel` without `fixed=`.

### Numbers of the demo (before and after, as the lead asked)

- **M-10, the UAS in q15** (re-flown alone on the run's own 64 draws and environment, two batches of 32, orca, 2 CPUs; the probe first reproduced the stored q15 exactly): **before** k_fail 55 of 64 (profile_incomplete 55, battery_reserve 10, wind_exceeds_airspeed 0), 249 of 381 flown sorties reach 8 of 8 waypoints, median seconds beyond the lean-angle clamp 563 s; **after** k_fail **61 of 64** (profile_incomplete 61, battery_reserve 18, wind_exceeds_airspeed 0), 186 of 381 reach 8 of 8, median clamp 9.5 s. The verdict is NO-GO both times; p_fail 0.859 to 0.953. Everything that follows the UAS rows (emulator rows, flip search, sensitivity indices, the report sentences with these counts) moves with it. P-R15BB3.
- **M-14/M-15, the default glider hull**: collapse depth 364 m to 331 m; `buckling_utilization` and `utilization` 1.374 to 1.512; `stress_utilization` 0.367 to 0.305; `vm_p99` 101.3 to 84.3 MPa (mesh); these are in a stage-3 FEA row only when the FEA runs (q15: `run` False). The row's key set changes (`vm_max` out, `buckling_lobes` and `buckling_follower_correction` in): the stage-3 window ledger hash changes.
- **M-14, `stage3.fea_min_s`: 68.2 s to 641.1 s** (the whole FEA child on the default hull at L/70, measured). **Consequence the lead must see: the glider FEA no longer runs under any shipped budget.** The FEA reserve is 0.25 of the glider window's slice; for the demo mission on one GPU the slices are ci 36 s, quick 72 s, 4h 288 s, overnight 720 s, so the reserves are 9, 18, 72 and 180 s against 641.1 s (measured with `Context(...).plan["stage3"]["fea"]`); on CPU (`--gpus 0`) the demo's LES windows are unreachable (slice 0) so the FEA is never reached, as before. At the L/20 floor of 68.2 s it ran under `4h` and `overnight` on a GPU. A glider window's FEA now runs only in a slice of 2,564 s or more. The hull's collapse depth is nevertheless known on every machine: it is the stored converged figure (M-11), which does not need the LES at all (the LES wall pressure adds about 1e-4 of the hydrostatic load; the FEA's answer depends on depth, wall and material). Options for the owner, none taken: raise `fea_reserve_frac` (0.89 would be needed at overnight), take the hull FEA out of the LES window's slice (run it once per hull, cached), or accept L/45's cost (the same) with the lower floor. P-R15BB1 records the eightfold jump of cost between L/30 and L/45, cause unknown.
- **M-11**: no verdict, count or array moves; the report gains a warning on glider_eq (ordered 950 m against the assumed hull's 330.6 m) and none on glider_2n (500 m against 654.6 m).
- **M-24**: under `--budget ci` a glider window's LES kill is the whole slice (36 s), not 27 s, when the FEA is planned out.
- M-13, M-9, M-16, M-17, M-18, M-19, M-20, M-21, M-25, M-27: no printed number of the demo moves (q15's members stay within -170.5 to -164.98 for M-20; the window-longitude sibling is unchanged for them).

## Per finding

Each: what the code does now, the DECISIONS row (new or the amendment), the CHANGELOG line, doc sentences needed, what I checked could break and how, and the test with its mutant.

### M-7 (survivors: EPERM, `median`, NORMAL_MIN)

Code. None: tests only. `test_r15_m7_every_errno_the_golden_probe_names_is_read_as_it_says` (six errnos through a patched `os.stat`: EACCES and EPERM denied; ENOENT, ENOTDIR, ELOOP, EBADF absent); a lognormal fraction with `median=50` added to the fraction-not-a-percent list of `test_stats_exact.py`; `test_r15_m7_a_wall_cell_gets_a_normal_by_the_size_of_its_smoothed_gradient_not_by_its_being_nonzero` (a one-cell slot with one cell missing from the upper wall has smoothed-solid gradients from 1e-9 to 1e-3: the dust-sized ones, under 1e-7, get no normal, the faint real ones, 1e-5 to 1e-3, keep the wall model).

DECISIONS: new row: "The three survivors of the round 14 tests are pinned: every errno `acceptance._probe` names is driven (EPERM was not), a lognormal speed fraction with a median of 50 is refused as a percent (the `median` field of `_check_factor` was not), and the wall model gives a cell a normal by the size of its smoothed gradient: below 1e-7 none, between 1e-5 and 1e-3 one (`NORMAL_MIN`, 1e-6, could be 1e-2 or 0 unseen). Tests only; the mutants die (round 15, M-7). Extends the round 14 rows of M-2, M-9 and M-34."

CHANGELOG: "Tests pin the EPERM branch of `acceptance._probe`, the `median` field of the speed-fraction check and the size of `wallmodel.NORMAL_MIN` (three mutants survived round 14's tests; round 15, M-7)."

Doc sentences. None.

Could break, checked. Nothing (tests only). Mutants, each run against the new test only: EPERM dropped, `median` dropped, NORMAL_MIN 1e-2, NORMAL_MIN 0.0: @@MUT7@@.

### M-9 (`hangar.bem` frequencies)

Code. Comment corrected where it lives, and the choice made a function: `hangar.bem_omega(dof, draft)` (heave: sqrt(g / draft), the natural frequency of a box hull; **roll and pitch borrow the heave frequency, an assumption** because their own need GM and radii of gyration the hull spec does not carry; surge, sway, yaw: `BEM_OMEGA_LOW` 0.3 rad/s, "no stated basis"); `bem` and the docstring say so. No number moves (cached USV hangar results stay valid). Not done: the physical option (roll and pitch at their own natural frequencies from `hs['gm']` and a radius of gyration): it needs an assumed radius of gyration, which is a new invented input; the size of the effect is unmeasured (Capytaine not run).

DECISIONS: new row: "`hangar.bem` evaluates a boat's added mass in heave at sqrt(g / draft), in roll and pitch at the same frequency (an assumption: their natural frequencies need GM and radii of gyration the spec does not carry; typically lower than heave's, a few rad/s for roll) and in surge, sway and yaw at 0.3 rad/s (no further basis); the comment said each of heave, roll and pitch was near its own. `hangar.bem_omega` is the one definition; a stand-in Capytaine in the test records the frequency of every dof (round 15, M-9). The size of the roll and pitch choice is not measured."

CHANGELOG: "`hangar.bem` says what frequency each degree of freedom's added mass is evaluated at (`bem_omega`): roll and pitch borrow the heave frequency, an assumption; no number moves (round 15, M-9)."

Doc sentences. If PHYSICS or the Hangar section of the README describes the BEM frequencies, say "heave at its natural frequency, roll and pitch at that frequency by assumption, the rest at 0.3 rad/s".

Could break, checked. `bem` callers: `hangar.run` (the USV path) and `receipts.py:338` (`kind="uuv"`, frequency independent, does not call `bem_omega`); `V = pm.volume ...` was an unread variable and is removed. Mutants: the docstring sentence, and Roll and Pitch dropped from the borrowing set: @@MUT9@@.

### M-10 (UAS airspeed cap)

Code. `uas.airspeed_envelope(limits, d_x)` = min(`max_airspeed_ms`, g tan(`max_tilt_deg`) / `d_x`) and `uas.leg_speed(wind, heading, leg, v_max, xp)` = the largest ground speed in [0, leg] along a heading that keeps |wind - s h| within the envelope, and whether one exists: the one definition. Stage 3's `pipeline_windows.uas_leg_speed` and `uas_case` now call them (stage 3's own copy of the interval is gone); stage 1's `_block` calls `leg_speed` (with `xp=jnp`) on the wind relative to the deck at every 50 ms block and holds the commanded leg speed to it; where no ground speed holds the envelope (the wind beyond it) the command is left alone and the airframe saturates at its tilt limit, so `wind_exceeds_airspeed` fires as before (14 m/s upwind: still flagged, the old test passes). `derive` stores `v_env` per member (from that member's drag) and `v_air`, stored and read nowhere, is gone. The stuck monitor judges the uncapped ask (as before), so a leg slowed to the envelope is not "a controller asking for nothing". **Launch rule and flag agree with the helper**: at the platform's launch limit (`launch_rule.max_mean_wind_ms` 12 = `airspeed_envelope`) an upwind leg has exactly 0 m/s of ground speed left, a hair above it none at all (a test pins it); the flag stays down where the helper has a ground speed (11 m/s: 1 m/s) and fires where it has none (13 m/s). The two yaml strings are reworded; the tilt-limited speed is 12.6 m/s, the rated limit 12.0 (envelope 12.0). `G` of stage 3 is 9.81 and `uas.G0` 9.80665; the envelope uses `G0` (min(12, 12.6) = 12 either way; the stage-3 tilt of a row, `atan(d_x v / G)`, keeps 9.81: P-R15BB2).

DECISIONS: amend 161 ("... by slowing the leg") with "; stage 1's sortie holds the same envelope by the same rule, `uas.leg_speed` (round 15, M-10)" and amend 237 ("the verdict rests on finishing the profile") with "; the profile is flown at the ground speed the airspeed envelope allows against the wind on each leg"; new row: "Stage 1's UAS sortie holds the airframe's airspeed inside `airspeed_envelope` (min of `limits.max_airspeed_ms` and g tan(`max_tilt_deg`) / `d_x`) by capping the commanded leg ground speed at `uas.leg_speed` against the deck-relative wind of each 50 ms block, the rule stage 3's window case uses (one definition; `uas_leg_speed` is a wrapper); where no ground speed holds it the command stays and the airframe saturates, so `wind_exceeds_airspeed` still fires. The launch rule's 12 m/s is the wind at which an upwind leg has no ground speed left. The q15 UAS re-flown alone: k_fail 55 to 61 of 64 (profile_incomplete 55 to 61, battery_reserve 10 to 18); the verdict is NO-GO both times (round 15, M-10)."

CHANGELOG: "The UAS sortie of stage 1 holds the airframe inside its airspeed envelope as stage 3's window does, by capping the commanded leg speed against the wind on the leg (`uas.leg_speed`, one rule for both); `v_air`, stored and never read, is gone. The q15 UAS goes from 55 to 61 of 64 failing (NO-GO both) (round 15, M-10)."

Doc sentences. PHYSICS 11: the sentence "Pattern: stacked legs upwind ..." gets "each leg is flown at `leg_speed_ms` or, against a wind w, at the ground speed that keeps the air within min(12 m/s, g tan 35 deg / d_x) (`uas.leg_speed`): 12 - w upwind"; **the "Control authority" paragraph is out of date**: "found the demand beyond the clamp in every sortie from about 6 m/s of wind" is no longer so (median `sat_s` falls from 563 s to 9.5 s on the q15 draws) and its counts ("q6: 55 of 64 `profile_incomplete`") are q6's; the report sentence built from `authority` (clamp seconds per sortie) reads the new numbers by itself. RUNBOOK/README: any statement of the UAS threshold in wind (the 5.8 m/s of the reviewer) is replaced by "the profile no longer fits the 20 min above about 5 to 6 m/s of upwind leg". PHYSICS limitation text for `attitude_exceedance` unchanged.

Could break, checked. Callers of `derive` (`fly_sortie`, `fly_sitl`, `receipts`, the `no_drag` fault: `airspeed_envelope` with `d_x` 0 has no tilt term, a test covers it through the receipts' `no_drag` run, which passes); the SITL path does not use `_block`; `test_uas.py` passes whole except the two tests that encoded the old behaviour (a 10 m/s and a 9 m/s wind inside the envelope were demanded beyond the clamp for most of the sortie): both now use a wind beyond the envelope (13 m/s) as their "strong" case, and the new sortie test pins the new behaviour (9 m/s: clamp touched for under 30 s; before more than 100 s). Mutants: the cap removed (`sh = sh0`), the interval's upper end moved: @@MUT10@@.

### M-11 (dive depth beyond the assumed hull's collapse depth)

Code. Lead's decision followed: no cap, no verdict change. `glider.hull_collapse_depth_m(P, a)` is the one function: the stored converged figure (`stage3.glider.hull_collapse_depth_m` 330.6 m, `stage3.slocum.hull_collapse_depth_m` 654.6 m, config/assumptions.yaml, from the L/70 study: hangar's rule on the converged mesh, computed without CalculiX so it exists on CPU), valid only for the hull written beside it (`hull_collapse_for`: "ellipsoid 1.8 x 0.3 m, 0.008 m al6061"); when the assumed wall, diameter, material or length no longer give that text it returns None with the reason and the report says the check was not made. `report._hull_warning(v)` puts a warning beside a glider's verdict (rendered after the task block of its card, in the json as `hull_warning`) when `min(ordered, rating)` (what the model flies) exceeds the collapse depth, naming both depths, QUESTIONS_FOR_LAB 4a and that the verdict assumes the ordered depth; None otherwise. Not a config check, so no mission is refused.

DECISIONS: amend 730 ("the model hull collapses at about 500 / 1.374 = 364 m") with "; 331 m on the converged mesh (row N, M-14)"; new row: "A glider whose ordered dive depth (the order, or the platform's rating when shallower, which is what the model flies) is deeper than the collapse depth of the pressure hull stage 3 assumes gets a warning beside its verdict in the report, naming both depths, QUESTIONS_FOR_LAB 4a and that the verdict assumes the ordered depth; no cap, no change of verdict (the owner has not answered the question of a cap; a warning does not refuse the demo or change a ledger hash). The depth is `glider.hull_collapse_depth_m`: hangar's rule on the converged mesh, stored for one named hull (330.6 m for the Seaglider assumptions, 654.6 m for the Slocum) and not applied to another. glider_eq's 950 m order is 619 m beyond it (round 15, M-11)."

CHANGELOG: "The report warns beside a glider's verdict when its ordered dive depth is deeper than the collapse depth of the pressure hull stage 3 assumes (glider_eq: 950 m ordered, 331 m collapse); no cap and no verdict changes (round 15, M-11)."

QUESTIONS_FOR_LAB 4a (hand-over, as asked): the station-loss dependence reviewer B measured on the q15 draws and environment, glider_eq alone, only the dive depth changed (orca, two batches of 32, EUC flow profile): **950 m: 18 of 64 lose station; 700 m: 38; 500 m: 60; 364 m: 64 of 64.** The collapse depth of the assumed hull changed with M-14: it is **331 m** (not 364 m); 364 m was the L/20 figure; the flight at 331 m was not re-flown (the series is monotone and 364 m already loses all 64). The loss is the depth-mean eastward current against the 0.2 to 0.28 m/s swim speed (the EUC is eastward at 100-200 m and slightly westward below 400 m), so the shallower the order the more of the dive is in the jet. Default stays: 8 mm wall, Al6061, knockdown 0.5; the 1000 m rating is not reached by this hull (331 m by the model's own rule; the Slocum assumption reaches 655 m).

Doc sentences. STATUS/QFL 4a: 331 m and utilization 1.512 replace 364 m and 1.374; PHYSICS.md:992 likewise.

Could break, checked. `report._vehicles` gains two keys per vehicle (`hull_warning`, `uas_levels_note`; None for the other classes); `check_traceability` walks them as strings; `tests/test_report.py` passes (below). `glider.hull_collapse_depth_m` reads `a["glider.hull_*"]`, `a["slocum.*"]` and the four new keys, all in `assumptions.yaml`; `credibility` lists every `stage3.*` assumption (scope by the word after `stage3.`: `glider`, `slocum`), and its tests pass. Mutants: the warning off, the staleness guard off: @@MUT11@@.

### M-13 (UAS levels above the deck)

Code. The BRIEF is silent (it names "a 20-min flux-profile sortie"); the code, the platform yaml ("stacked flux-profile legs above the deck") and PHYSICS 5.1 read the levels as heights above the deck, so I did not shift them (that would move every UAS wind, RF and turbulence number). `mission.json` says "metres ABOVE THE DECK (the platform's sortie.deck_height_m, 8 m for the quad ...), so 10, 30, 60, 100 are flown at 18, 38, 68, 108 m"; the report gives the sea-referenced heights per UAS (`uas_levels_note`, shown under the verdict card: "10, 30, 60, 100 m on a 8 m deck ... flown at 18, 38, 68, 108 m above the sea; the wind, the radio antenna height and the turbulence box are taken there"). No number moves.

DECISIONS: new row cross-referencing 325: "A UAS mission's `altitudes_m` are heights above the deck (`sortie.deck_height_m`, 8 m for the quad): the legs fly at deck + altitude above the sea (18, 38, 68, 108 m for the demo's 10, 30, 60, 100), where the wind is read, the radio antenna sits (plus 0.1 m) and the Mann box is centred (row 325: deck + the mean altitude). The schema and the report say so; the BRIEF does not say which height the flux profile is referenced to, and the lab's convention (sea) is open (round 15, M-13)." QUESTIONS_FOR_LAB: add "Are the flux-profile heights 10, 30, 60, 100 m above the sea or above the deck? Default: above the deck (18 ... 108 m above the sea)."

CHANGELOG: "The mission schema and the report say that a UAS's `altitudes_m` are heights above the deck and give the heights above the sea (18, 38, 68, 108 m for the demo); no number moves (round 15, M-13)."

Doc sentences. RUNBOOK:98 where `altitudes_m` is listed: "distinct and rising, metres above the deck". Sibling (not fixed, batch A's file): the 400 m check in `config.load_mission` compares the level, not deck + level (P-R15BB2).

Could break, checked. Text only. Tests: `test_r15_m13_*` (note in the report json and html; the schema description). Mutants: the report sentence, the schema text: @@MUT13@@.

### M-14 (mesh)

Code. `config/assumptions.yaml` `stage3.fea_elements_along` 20 to 70 with the study in its `why` (and `replace_with` no longer names a missing study); `cafe/fea.hull_elements_along()` reads that one value; `hangar.fea_cases` (the Hangar's hull case, which had `/70` in code) and `pipeline_windows._fea` mesh by it, so the repo has one collapse depth for one hull. `config/fea_hull_mesh_study.json` stores the five rows and the two hulls at the chosen mesh. `stage3.fea_min_s` re-measured: **641.1 s** (the whole child at L/70). The cost grows eightfold between L/30 and L/45 (P-R15BB1, cause unknown).

DECISIONS: amend 730 (the "364 m" and "h = L/20" and "1.3743" in it) and 741 (68.2 s) and 776 (68.2 s, "9.0 s of the 36.0 s slice"): "the mesh is L/70 and the floor 641.1 s (row N)"; new row: "The stage-3 hull FEA and the Hangar's hull case mesh the hull by one number, `stage3.fea_elements_along` = 70 (cafe.fea.hull_elements_along), chosen from a five-mesh study of the default Seaglider hull (config/fea_hull_mesh_study.json): factor 1.4552, 1.4133, 1.3348, 1.3225, 1.3179 at L/20 ... L/100, collapse depth 363.8, 353.3, 333.7, 330.6, 329.5 m; L/70 is within 0.35 % of the finest and costs as much as L/45; the converged collapse depth of the default hull is 331 m, L/20's 364 m was 10 % unsafe. `stage3.fea_min_s` is 641.1 s, the measured whole child at that mesh (68.2 s at L/20): the glider FEA is planned out below a reserve of 641.1 s, i.e. a slice of 2,564 s (round 15, M-14)."

CHANGELOG: "The hull FEA of stage 3 and the Hangar mesh the hull at L/70 (`stage3.fea_elements_along`, one number): the default glider hull collapses at 331 m, not the 364 m of the L/20 mesh (10 % unsafe); the mesh study is stored (`config/fea_hull_mesh_study.json`); `stage3.fea_min_s` is 641.1 s (round 15, M-14)."

Doc sentences. PHYSICS.md:992 and QFL 4a: 331 m (utilization 1.512, stress utilization 0.305) replace 364 m / 1.374; README line 80 is unaffected. RUNBOOK:76 and DECISIONS 776 must carry **641.1 s** where they say 68.2 s: `tests/test_config_docs.py::test_r14_m15_the_makefile_and_the_runbook_say_that_make_ci_plans_the_glider_fea_out_under_the_floor_the_assumption_file_holds` reads `floor` from the yaml (pinned to 641.1 there) and the numbers in RUNBOOK and row 776, and **fails until batch D edits them**.

Could break, checked. `need(a, "fea_elements_along")` callers (`_fea` only; the plan's `budget.stage3_plan` reads `fea_min_s` and `fea_reserve_frac`, not the mesh); tests that run the FEA through `cheap()` patch `fea_elements_along` to 6 and `fea_min_s` is read by `sizes["fea"]["runs"]` (the stage-3 tests passed; see below). `hangar.fea_cases` for a UUV now meshes at L/70 as before. The test `test_r15_m14_the_hangars_hull_case_and_the_stage_3_window_mesh_the_hull_by_the_one_number_in_the_assumptions` records `h` on both paths. Mutant: `/20` back in the Hangar: @@MUT14@@.

### M-15 (follower correction): see the FEA section above.

DECISIONS: amend 730 ("the model hull collapses at ..." and the 3/4 it does not state) and 792 (the buckling factor row) with "the buckling factor is the dead-load factor times (n^2 - 1) / n^2 of the mode that sets it (3/4 for the 2-lobe mode of the default hull), n read from the mode shape; 3/4 where no shape exists"; new row: "`fea.solve`'s `buckling_factor` is the least over the modes below the lowest dead-load eigenvalue / 3/4 of (n^2 - 1) / n^2 x eigenvalue, n the lobe count read from the mode's normal displacement (`fea.lobe_count`); the flat 3/4 of the 2-lobe mode applied to every mode made a sphere read 20 % under Zoelly and a 3-lobe tube 10 % under von Mises. The knockdown 0.5 (`hangar.KNOCKDOWN`) is a separate allowance for imperfection and stays, applied once. Verified: long tube 1.051 of Bresse, 1.2 m tube 1.051 of von Mises n = 2, 0.6 m tube 1.070 of von Mises n = 3, sphere 1.02 to 1.06 of Zoelly falling with the mesh. The default glider hull's lowest modes are 2-lobe at every mesh, so its collapse depth does not move (round 15, M-15)."

CHANGELOG: "The follower-pressure correction of the FEA buckling factor is (n^2 - 1) / n^2 of the mode's own lobe count (3/4 only for the 2-lobe mode, near 1 for a sphere), read from the mode shape, instead of 3/4 for every mode; the default glider hull is unchanged (2-lobe) (round 15, M-15)."

Doc sentences (for C-13 / M-26 "Hull FEA" subsection): the mean-rigid-motion equations; CalculiX OFFSET +0.5 (wall inside the outer skin) and its fallbacks; p99 von Mises and why `vm_max` is not stored; Bresse (1866) 2E/(1-nu^2)(t/D)^3 hydrostatic; the ring ratio dead/follower n^2/(n^2-1); von Mises (1914) and Windenburg-Trilling for finite tubes; Zoelly 2E/sqrt(3(1-nu^2)) (t/R)^2 for the sphere; the verification table above; KNOCKDOWN 0.5 "NASA SP-8007-style" (a comment, not re-read); the mesh study and the collapse depth 331 m. The receipts' context row in `cafe/receipts.py` ("Short capped cylinder collapse") no longer says the 3/4 is "conservative for this 4-lobe mode": its value now carries that tube's own correction.

Could break, checked. Consumers of `buckling_factor`: `windows.fea_window` (`1 / (lam x KNOCKDOWN)`), `hangar.fea_cases` (`buckle_depth = REF_DEPTH x factor x KNOCKDOWN`), `receipts.fea_receipts` (the bracket "Glider hull collapse pressure": the 1.5 m / 0.22 m / 7 mm hull, lowest mode presumably 2-lobe, so unchanged: it is a slow receipt, not rerun here; the long-tube row 0.5739 against Bresse is the same 3/4 case), the fake-ccx tests (no `.frd`: the 3/4 fallback, `buckling_lobes` None). Mutants: correction flat 3/4; only the lowest mode considered; the correction function returning 3/4: @@MUT15@@.

### M-16, M-17, M-23: see the FEA section above.

DECISIONS: new row (one for the three): "`fea.py`: the docstring and `selftest` describe the mean-rigid-motion constraint (no reaction for a free body; `python -m cafe.fea` runs `selftest`, which runs on the real solver in a test); `solve` refuses a shell without a finite positive wall and `body_accel` without `fixed=` before the mesher runs (the d'Alembert loads of a body acceleration on a free body are not implemented, and a dropped load is worse than a refusal); `vm_max` is not stored (the largest element value is the mesh's: 3.8 to 6.4 x the 99th percentile on a uniform sphere); `vm_p99` is the stress basis of every utilization (row 730) and can under-report a hot spot by about 13 % (round 15, M-16, M-17, M-23). Amends 730 ('vm_max' is not among the stored fields)."

CHANGELOG: "`cafe.fea`: the docstring and the self-test no longer describe a 3-2-1 constraint and reactions (`python -m cafe.fea` ran into a KeyError; it is `fea.selftest` and a test); `solve` raises ValueError before meshing for a shell with no wall and for `body_accel` on a free body; `vm_max` (a mesh artefact) is no longer stored (round 15, M-16, M-17, M-23)."

Doc sentences. As the M-15 list; the Hangar app's load-case table no longer has a "vm_max" column value.

Could break, checked. `body_accel` callers: only `hangar.fea_cases` (the lifting case) with `fixed=`; `thickness` callers: `hangar` passes `t if struct == "shell" else None`, `fea_window` the vehicle's thickness (a positive number); `fixed=None` solid with `thickness` None unaffected. `vm_max` readers: `windows.fea_window`, `hangar._case` (both edited), a test fixture. The app's JS does not read `vm_max_mpa` (grep). Mutants: validation off (x2), `vm_max` back, the `r['reaction']` print back in `selftest`: @@MUT16@@.

### M-18 (two-window refit floor: a stated limit)

Code. None. The `refit.py` docstring states the limit with the measured figures (tau^2 = 0 in about 15 % to 34 % of draws at k = 2; sigma up to 17 % short in those draws, not short on average: 0.0736 against 0.0616 and 0.0548 against 0.0524); `test_r15_m18_*` pins the behaviour (two agreeing windows: `tau` 0, `sigma_between` 0, sigma = standard error and discretisation floor; one window gets the floor) and the docstring words.

DECISIONS: amend 181 ("fewer than two windows") with "; at two windows DerSimonian-Laird has tau^2 = 0 in 15 to 34 % of draws (replicated on 20,000), where sigma is the standard error and the discretisation floor alone; stated, not floored: a floor at k < 3 would widen every two-window multiplier spread and could move a GO/NO-GO near a threshold (round 15, M-18)".

CHANGELOG: "The refit module states that the between-window floor stops at two windows and what that costs (round 15, M-18); no behaviour change."

Doc sentence. PHYSICS.md:994 (refit): "With two windows the between-window variance is estimated as 0 in 15 to 34 % of draws; the sigma then rests on the standard error and the 5 % discretisation floor. A floor for two windows is not applied."

Could break, checked. Nothing (docstring and a characterisation test). Mutant: the docstring phrase changed: @@MUT18@@.

### M-19 (`refit.pool`)

Code. `pool` raises `ValueError` for a non-finite mean or standard error and for a negative one, and floors a standard error of exactly 0 at `refit.SE_FLOOR` (1e-12) for every caller; the three `max(spread, 1e-12)` clamps in `refit()` are removed (the free-surface row's own floor in `freesurface.row_fields` stays). Zero spread: drag and lift, one-reference and per-window branches now behave alike. The weight of a spread-0 window is still 1e24 (a larger floor as a fraction of |mean| would change printed numbers and needs an owner's row; not done).

DECISIONS: amend 181 (or the refit row) with: "`refit.pool` refuses a NaN or infinite mean or standard error and a negative one, and takes a standard error of 0 as `SE_FLOOR` (1e-12), the one policy for every caller (the one-reference drag raised, the lift and the per-window branch clamped; round 15, M-19)."

CHANGELOG: "`refit.pool` refuses NaN and infinite inputs and has one policy for a standard error of 0 (floored at 1e-12) in all its callers (round 15, M-19)."

Doc sentences. None.

Could break, checked. Callers: `refit.refit` (both branches), `pipeline.s_refit` (only `ok=True` windows: finite), `tests/test_stage3.py::test_pool_random_effects` (the `([1.0], [0.0])` raise case is now a floor case; its bad list has a negative error instead). `cafe/pm/env/subgrid.py:481` has its own `_pool` (not read: said by the finding). Mutants: the finite check off; the floor off: @@MUT19@@.

### M-20 (longitude median)

Code. `conventions.lon_median(lon, axis)` (images nearest the slice's circular mean, median, wrapped into [-180, 180) only if outside it, so a slice away from the line is the plain median bit for bit); used by `pipeline_windows.track_heading` (the UAS course over ground) and `pipeline.s_windows` (the window's longitude, which feeds the LES's environment lookups). `report._median_track` is left: it reduces about the mission centre and was correct. The `wrap` also covers an all-NaN slice (NaN).

DECISIONS: new row: "A median of longitudes is taken about the slice's circular mean (`conventions.lon_median`): the course over ground of members on either side of the dateline and the longitude of a window (which feeds its LES's wind, current and wave lookups) no longer come from a raw median that put them at lon 0. A slice that does not touch the line is the plain median bit for bit, so q15 does not move (round 15, M-20; round 15 RC-6)." (D-4's `dlon` bound is batch A's.)

CHANGELOG: "The heading and the longitude of a window are taken from a median of longitudes about their circular mean, so members either side of the dateline no longer put a window at lon 0 (round 15, M-20)."

Doc sentences. None (the demo box 165E..165W makes it live for a mission nearer the line).

Could break, checked. Callers of the raw median on longitudes: `grep` finds only these two and `report._median_track`; the heading result for a non-straddling run is bit-identical (`wrap_about` adds 0.0; the final wrap only touches values outside [-180, 180)); `test_pipeline.py` and `test_stage3.py` pass (below). Mutants: raw median back at either site, helper without the images: @@MUT20@@.

### M-21 (SIGKILL is not always the deadline)

Code. `pipeline_windows._killed_at_deadline(rc, armed_s, started)` (rc -9, a watchdog armed, at least `armed_s` - 1 s elapsed) is the one rule of `_fea` and `_fs_work`; an earlier -9 is "FEA killed by SIGKILL before its deadline (out of memory or an outside kill, not the watchdog): it did not finish" (`run` False, as the killed FEA) and, for the free-surface child, "free-surface run failed (-9): killed by SIGKILL before its deadline (...)"; no watchdog (no deadline) means no -9 is the watchdog's.

DECISIONS: amend 734 (the FEA child's kill) and the free-surface row: "a child's exit -9 is its watchdog's only if the watchdog's time had come (within 1 s of skew); before it, it is the OOM killer's or an outside kill and says so (round 15, M-21)". CHANGELOG: "A stage-3 child (FEA, free surface) that dies of SIGKILL before its deadline is reported as killed from outside (out of memory?), not as a deadline kill (round 15, M-21)."

Doc sentences. None.

Could break, checked. The reason strings: tests matched the prefix "killed: the FEA" (kept for the deadline case, 1645 unchanged) and "killed by its watchdog" (kept); the stub `_spawn` cases that returned -9 at once now return the new reason: `test_round_13_m42_a_fea_with_no_time_left...` and `test_the_hull_fs_row_failures_are_rows_with_reasons` are extended (a stub that sleeps 0.3 s with a 1.2 s deadline is the watchdog's; an instant -9 with 60 s or none is not). No pipeline row of q15 has a -9. Mutants: the rule always true: @@MUT21@@.

### M-24 (FEA reserve when planned out)

Code. `fea_s` in `_row` is the reserve only `and sizes["fea"]["runs"]`; `budget.py:186` (cell-steps) untouched, so cell-steps and ledger hashes do not move. DECISIONS: amend 137 and 776: "the FEA reserve is withheld from the LES window's safety kill only when the FEA is planned to run; a planned-out FEA leaves its quarter to the LES (the sizing keeps it, 137; round 15, M-24)." CHANGELOG: "A glider window whose FEA is planned out is no longer cut at 0.75 of its slice for an FEA that never runs (round 15, M-24)." Doc sentence: none. Could break, checked: only the kill (`spec.wall_s`); worst-case ci window 27 s to 36 s. Mutant: the condition removed: @@MUT24@@.

### M-25 (`run_windows`)

Code. Deleted with its docstring line, its imports and `test_run_windows_overlaps_fea_with_the_next_les_window`; `test_r15_m25_the_pipelines_child_is_the_one_entry_point_...` asserts it is gone and that `_fea_child` asks for `buckle=True`. DECISIONS: amend 792: "`windows.run_windows`, a second FEA entry point whose default left the buckling step off, is deleted; the pipeline's `_fea_child` is the only one (round 15, M-25)." CHANGELOG: "The dead `windows.run_windows` is deleted (round 15, M-25)." Could break: callers (`grep`): only that test. Mutant: a `run_windows` defined again: @@MUT25@@.

### M-27 (`fea_min_s` text)

Code. The `why` of `stage3.fea_min_s` names the default hull correctly ("ellipsoid 1.8 m long, 0.30 m diameter, i.e. semi-axes 0.9 and 0.15 m, 8 mm Al6061, h = L/70 = stage3.fea_elements_along, 5,546 elements") and the new measurement; a test guards the words (`test_budget.py`). The stage-3 ledger records `config/assumptions.yaml` by the sha-256 of its VALUES (row 753), so a `why` edit alone would not move it; the value edits (`fea_elements_along`, `fea_min_s`, four new keys) do. DECISIONS: part of the M-14 row. CHANGELOG: "`stage3.fea_min_s` cites the hull it was measured on correctly (round 15, M-27)." `tests/test_budget.py:396` docstring now says the same hull.

## Needs from other batches

- **Batch D**: all the DECISIONS / CHANGELOG / PHYSICS / RUNBOOK / QFL text above. Hard dependencies: `tests/test_config_docs.py::test_r14_m15_...` fails until RUNBOOK:76 and row 776 say **641.1** (the test reads both and the yaml); `test_budget.py` pins 641.1. PHYSICS.md:759 (the "Control authority" claim about 6 m/s) and PHYSICS 11's sortie sentence (M-10); PHYSICS.md:992 and QFL 4a (331 m, 1.512, 0.305, the 2-lobe mode, the station-loss series 18/38/60/64 and that the series was measured at 364 m not 331 m); a "Hull FEA" subsection for M-26 with the verification table of the FEA section; RUNBOOK:98 (`altitudes_m` above the deck); QFL: the flux-profile height question (M-13); the row numbers for the amendments of 137, 161, 181, 237, 325, 730, 734, 741, 776, 792.
- **Batch A**: `config.py` is theirs: the 400 m check of `altitudes_m` compares the level, not deck + level (P-R15BB2); M-11's check is a report warning, so no `config.py` dive-depth check was added (their D-5 / A-2 / B-2 shared function does not need one). `missions/tepex_c_demo.yaml` unchanged.
- **Batch C**: nothing; `report.py` is touched here only in `_vehicles`/`_vehicle_html` and two new helpers (no overlap with `_median_track`, `_reach`).
- **The gate / next run**: the q-run after this batch moves the UAS counts (M-10) and the stage-3 ledger hash; the glider_eq verdict is unchanged and now carries a warning.

## Checked (what I ran)

@@CHECKED@@
