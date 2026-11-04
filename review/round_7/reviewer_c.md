# Reviewer C, round 7: usv.py, uas.py, glider.py, platforms/, stage3/*, PHYSICS.md for them

Scope reviewed line by line: `cafe/pm/physics/{usv,uas,glider}.py`, `platforms/{saildrone_explorer,quad_uas,seaglider,slocum}.yaml`, `cafe/pm/stage3/{lbm,nest,wallmodel,freesurface,fluidx3d,windows,refit,pipeline_windows}.py`, PHYSICS.md sections 9, 10, 11, 14, and the tests named below.
Experiments ran on homebase at 1 CPU in `pm_rev7_c` (scripts in `/private/tmp/claude-501/-Users-aaroh--claude-spares-spare-P6utrU/96cd665b-6853-40e7-8769-780fbfcaeebd/scratchpad/rev7c/t*.py`; each is a stdin script run in the `cafe-pm` image).
Stage 3 does not run at all in the q7 quick run (every row is "not run": `q7/stage3/windows.json`), so the stage-3 findings are from the code, the stored receipts on homebase and targeted snippets.

### C-1. The USV is calibrated twice: the 12 m/s fit is made on the polar without the bias, the simulation always applies the bias (-24 %)
severity: major
lane: statistics / honesty
where: platforms/saildrone_explorer.yaml:22 (`appendage_cda_m2` raised 0.02 -> 0.04), :87 (`vpp_bias_mean -0.2422`), :8-9 (header); cafe/pm/physics/usv.py:534 (`v = ... * self.fac`), :695-697 (receipt reads `pol.f`, no bias)
reproduction: `usv.tables(P)[0].f[12, :, 0].max()` = 2.923 m/s (the receipt value, "2.92 against 2.9", PHYSICS.md 10.1 table). The speed Stage 1 uses is `v0 * (1 + bias)` (`_eval`), so the best-heading through-water speed at 12 m/s is 2.923 * (1 - 0.2422) = 2.215 m/s, 24 % under the Chiodi maximum (2.9 m/s) that `appendage_cda_m2` was raised to hit. `usv.mean_sog(P, 12.0)` = 2.016 m/s with the prior bias, 2.657 without. The two calibration targets (mean 0.96 at 5.4 m/s via the bias; max 2.9 at 12 m/s via CdA) are met by two different model variants; no variant of the model that is actually flown meets both. The receipt label "(CALIBRATED: appendage_cda_m2)" is on the unbiased polar, which Stage 1 never uses. Also the yaml header (lines 8-9) says "the 5.4 m/s mean ... [is] not fitted to", while line 87 and DECISIONS 163 say the bias is solved to reproduce exactly that mean (PHYSICS.md prints "0.0 % at the prior mean": a closure, not a reproduction), and the receipt row "mean SOG / U at 5.4 m/s" is not labelled as a fit.
why it matters: the model speed at moderate and strong wind is lower than the model's own calibration says, and a reader of the receipts table sees two passes that cannot both be true of the flown model.

### C-2. The USV speed-model uncertainty is +-1.4 % wide: a 5-point range of a bias is used as the width of the prior
severity: major
lane: statistics
where: config/perturbations.yaml:72-79 (`usv_vpp_bias` uniform [-0.2565, -0.2280]); platforms/saildrone_explorer.yaml:87-88 (`vpp_bias_sd 0.0082`); cafe/pm/physics/usv.py:450-452; docs/PHYSICS.md:553, 672
reproduction: width 0.0285 = (1/1.30 - 1) - (1/1.35 - 1), the spread of Sun et al.'s published overprediction (a systematic bias of VPPs in general), taken as the sampling spread of this one model's speed factor, sd 0.82 %. The model's speed rests on assumed mass, wing area, wetted area, residuary coefficient, form factor and heel penalty (yaml `assumed: true` for all of them); the calibration anchor is one campaign mean with "no spread quoted" (the yaml's own words, `chiodi_band` 25 % is the receipt tolerance). One scalar fitted at one wind speed (5.4 m/s) is applied at all speeds: `mean_sog(P, 3.0)` 0.519 and `mean_sog(P, 8.0)` 1.424 m/s are not tested against anything.
why it matters: the USV verdict ensemble varies speed by +-1.4 % from the model and by the environment only, so a verdict that hinges on the speed (swept off track, becalmed) is far more confident than the evidence supports; the `usv_vpp_bias_brief` sensitivity case (-0.35 .. -0.30) differs by 5-10 points and is not in the ensemble.

### C-3. The stage-3 gate trusts stored wall-model results without checking which code made them
severity: major
lane: reproducibility / honesty
where: cafe/pm/stage3/wallmodel.py:341-348 (`stored_wall_error`), :384-389 (`channel` writes no `code_sha`), :391-397; cafe/pm/stage3/windows.py:213-216, 302; tests/test_config_docs.py:48
reproduction: in a temp `SLOW_DIR` write `wm_flat_plate.json` with `err 0.09, code_sha "OLDCODE"` and `wm_channel.json` with `err 0.01` and no `code_sha` (exactly what `python -m cafe.pm.stage3.wallmodel channel` writes). Result (t13.py): `wm.stored_wall_error()` = 0.09 -> `windows.stage3_checks`' `wall_model_receipt_error` passes (0.09 <= `PLATE_TOL` 0.10), while `wm.receipts()` for the same files prints the plate row as "STORED BY DIFFERENT CODE" and FAIL. So a window can be `ok` and enter the refit on a wall model that has since changed, although the receipts table, the PHYSICS.md text ("stored by different code: fail") and the `pipeline_windows` docstring ("so no unvalidated coefficient reaches Stage 1b") say it cannot. `physics_sha()` (lbm.py:614) is computed and stored for the plate only. The only test that "covers" the max logic is `tests/test_config_docs.py:48`, which asserts the SOURCE TEXT `return max(float(json.loads(f.read_text())["err"]) for f in fs)`, not behaviour; `tests/test_stage3.py:269-284` tests `stored_wall_error` and the stale-sha receipt separately, never together.
why it matters: the one gate that decides whether any LES coefficient may change a verdict does not use the staleness check that the report advertises.

### C-4. A stored slow result with no `code_sha` is accepted as current, and every stored result on homebase has none
severity: major
lane: reproducibility
where: cafe/pm/stage3/lbm.py:647 (`rec.get("code_sha") not in (None, physics_sha())`); cafe/pm/stage3/nest.py:507-509
reproduction: `lbm.result_row("g","c",dict(cd=1.0,ref=1.0),"cd","ref",0.1,"cmd","eta","src")` records PASS (t13.py). On homebase `~/work/cafe/pmdata/receipts/`: `wm_flat_plate.json`, `wm_channel.json`, `nest_sphere_100_d8.json`, `_d12.json`, `_d16.json` have no `code_sha` (d8 and d12 say "printed values transcribed, not re-run through the CLI"). The staleness test therefore cannot fire on any file in use, and the Richardson row mixes two transcribed values with one measured run as one "current" study. The docstring says "stored by different code (its `code_sha` differs ...)"; a missing sha is not a different sha but is trusted.
why it matters: the staleness protection is off exactly for the data that exists; a hand-edited or legacy JSON passes.

### C-5. The sphere grid study used for the refit's discretisation floor is a failing receipt, and its "error" (1.5 %) is the distance to an extrapolation whose own order is 2.96
severity: major
lane: statistics / numerics
where: cafe/pm/stage3/refit.py:47-56 (`default_floor`); cafe/pm/stage3/nest.py:450-488 (`richardson`, `sphere_discretisation`); docs/PHYSICS.md:960-975
reproduction (t6.py, stored files): d = 8, 12, 16 give Cd = 1.3053, 1.2087, 1.1848 (Morrison 1.0382). `richardson` on the three: p = 2.956, Cd_inf = 1.1670 (+12.4 % over Morrison, so the row FAILS its 10 %); the finest grid is +14.1 % over Morrison. `sphere_discretisation()` returns 0.0153 (1.5 %), which `default_floor` makes the discretisation term of sigma for EVERY vehicle. The extrapolated Cd drifts with the pair chosen: (8,12) -> 1.0155 (-2.2 %, the "passes" in PHYSICS.md 14.5), (12,16) -> 1.113 (+7.2 %), (8,12,16) -> 1.167: the sequence is not in the asymptotic range, which is what a bracketed p at the upper limit (3) with a nominally second-order scheme says. The floor measures grid-to-extrapolation distance, not the 12-14 % gap to the reference, and a sphere at Re = 100 with a curved-wall scheme says nothing about 2-10 cells across a wall-modelled hull at Re 1e6-1e7. (PHYSICS.md 14.5 still prints "Re=100 passes ... from d=[8, 12] (order 1.00)"; with d16 stored the code gives a three-grid row that fails.)
why it matters: the refit sigma carries 1.5 % where the only measured discrepancy of the native kernel is 12-14 %; a pooled multiplier will look 8x more certain than the study supports.

### C-6. The `hull` LBM window is a fully submerged ellipsoid with 2.6 x the Hangar hull's wetted area (and 5 x its displacement)
severity: major
lane: physics / data
where: cafe/pm/stage3/pipeline_windows.py:139-147 (`usv_vehicle`: ellipsoid radii (lwl/2, beam/2, **0.45**) centred on the waterline), :234-238 (`cd_h` from `P["wetted_area_m2"]` = 6.5 m2); cafe/pm/stage3/windows.py:79-85 (`_inside`), :115-130 (`voxelize`)
reproduction: ellipsoid a=3.25, b=0.6, c=0.45 (assumptions `stage3.usv.hull_draft_m`): area 17.0 m2 (half 8.5), volume 3.68 m3 (half 1.84) against the platform's wetted area 6.5 m2 and displacement 750/1025 = 0.73 m3. The `hull` window has no free surface, so the LES wets the whole 17.0 m2 (both halves; wall model on all faces), while the Hangar number is 0.5 rho U^2 * 6.5 * C_F (1+k) + keel (12.6 N at 1 m/s for the hull). The same viscous friction on 17 m2 would be 33 N: `cd/cd_hangar` ~ 2.6 from geometry alone, before pressure drag. No check compares the two areas (the row records `wetted_area_mesh_m2` for `hull_fs` only; for `hull` nothing). `pipeline.s_refit` (pipeline.py:1048-1061) uses the `hull` windows for the USV multiplier whenever no `hull_fs` window passes, and Stage 1 applies it to the whole through-water resistance as a speed factor d^-1/2 (about 0.6).
why it matters: the first time a USV hull window passes (a GPU run) its multiplier is a geometry artifact of about +160 %, presented as a drag correction.

### C-7. The windows' fluid constants differ from the platform's: water viscosity 1.19e-6 against 0.86e-6
severity: minor
lane: physics / data
where: cafe/pm/stage3/windows.py:29-30 (`RHO`, `NU`); platforms/saildrone_explorer.yaml:62-63 (`rho_water` 1023, `nu_water` 0.86e-6); cafe/pm/stage3/pipeline_windows.py:205, 234-235 (Hangar side uses the platform's)
reproduction: the LES window runs at nu 1.19e-6 (the old cafe app's tank-water value, `cafe/cfd.py:14`), the Hangar `r_hull` and `_keel_drag` at 0.86e-6 (28 C, the mission's water). ITTC-57 at U = 1 m/s, L = 6.5 m: C_F(Re 5.46e6) = 3.342e-3 against C_F(Re 7.56e6) = 3.151e-3, +6.1 %. A tropical glider window at 25-28 C is also run 30 % low in Reynolds number. Nothing in the docs mentions it.
why it matters: a +6 % bias enters `cd/cd_hangar` for the USV before any physics.

### C-8. Window heading is the stage-1 course over ground, used as the bow heading
severity: minor
lane: physics
where: cafe/pm/stage3/pipeline_windows.py:102-116 (`track_heading`), :214-216 (`usv.through_water(P, wind, cur, heading)`), :186-187 (glider), :461; cafe/pm/stage1.py:140-148 (res.pkl holds lon/lat only)
reproduction: `track_heading` is the direction of the member-median position change, i.e. course over ground (current, leeway and Stokes drift included). `usv.through_water(..., heading)` and `glider_case` take it as the direction the bow points. For the USV in a 0.3-0.9 m/s current (the demo: 0.33 m/s mean, close-hauled 85 -> 45 deg true wind angle) the bow is up to tens of degrees off the track, and `usv.through_water` is steeply heading dependent (stw 1.55 m/s at TWS 6 / TWA 90, 1.19 at TWA 45, 0.55 at TWA 15 in this polar). The window's speed, leeway, apparent wind and relative-flow direction are for a different course.
why it matters: the window does not model the state the Stage-1 member was in; the refit ratio compares different conditions.

### C-9. The added-resistance correction is first order in a regime where the model's own equation has no solution
severity: minor
lane: numerics / physics
where: cafe/pm/physics/usv.py:533-534 (`_eval`: `v = (v0 - R_aw(v0)/K) * fac`), :268-271 (K); docs/PHYSICS.md 10.1 ("first order")
reproduction (t4.py, t15.py): TWS 6, TWA 90, head seas Hs 2 m, Tp 6 s: calm V = 1.554, K = 131.8 N s/m, R_aw(1.554) = 129 N, Stage 1 speed = 0.574 m/s. Solving the model's own X(V) = R_aw(V): X(0) = 105.5 N, R_aw(U=0) = 312.6 N, R_aw(0.5) = 207.9 N against X(0.5) = 95.2 N: no positive speed, the boat is driven back. Second case TWS 4, Hs 1 m, Tp 6 s: Stage 1 0.570, self-consistent 0 (X(0) = 46.9 N, R_aw(0) = 78.2 N). With modest seas the linearisation is within 3 % (Hs 1, Tp 8: 1.475 against 1.470). R_aw is evaluated at the calm speed, where it is smallest (it falls with speed), and divided by the local slope.
why it matters: in short steep seas the boat is credited 0.57 m/s it cannot make; becalmed/swept-off-track are then under-reported in exactly the wave states that matter.

### C-10. The 4-DOF fixed point is not converged at 24 iterations above 27 m/s of wind, and no test looks
severity: minor
lane: numerics
where: cafe/pm/physics/usv.py:91 (`N_IT = 24`), :282; docs/PHYSICS.md 10.1 ("24 damped fixed-point iterations")
reproduction (t2.py): rebuild the 31 x 73 polar with `N_IT` = 24, 48, 200: 48 and 200 agree; 24 differs in 39 cells, all at TWS 28-30 m/s, |dV| up to 0.15 m/s over most of them (V 2.940 against 2.902 at TWS 28, TWA 75; 3.194 against 3.059 at TWS 30, TWA 85) and 1.55 m/s in one (TWS 30, TWA 47.5: 1.573 against 0.024). Heel differs by up to 0.93 deg, K by 372 N s/m. The sway residual (the receipt) is 0.001 in those cells, so it does not see the error (depower/heel are what has not settled). No test or receipt varies `N_IT`.
why it matters: speeds in storm winds are over-stated by 2-5 %; the receipt that "proves" convergence tests only TWS <= 14.

### C-11. `sortie.battery_swap` is required, documented as an input, and read by no code
severity: minor
lane: documentation / honesty
where: platforms/quad_uas.yaml:117; cafe/pm/physics/uas.py:89 (kind "other"), :600 (docstring "each on a fresh pack: sortie.battery_swap")
reproduction: `grep -rn battery_swap cafe tests docs config missions` -> only the yaml, the REQUIRED table and the docstring. `fly_mission`/stage 1 always start a sortie with a full pack; setting it to `false` changes nothing.
why it matters: a lab user who sets it believes the second sortie of a day starts on a partly used pack.

### C-12. A non-finite shortwave value makes the USV battery state NaN forever and disables the battery failure
severity: minor
lane: robustness
where: cafe/pm/physics/usv.py:613-616 (`swdown`), :546-555 (guards cover wind, current, waves only)
reproduction (t8.py): an env whose `air()["swdown"]` is NaN after t = 1 h, wind/current/waves finite: after 24 h `soc_wh` = [nan nan], `fail["battery"]` = [False False], `fail["no_current_data"]` = [False False]. The clean env drains and fires `battery` at 50.0 h. Related: `USVSim` accepts a non-finite start position without a flag (positions stay NaN; AnalyticEnv does not care, the real env would flag it); a NaN wind at the ship makes `uas.fly_sortie` report the sortie `scrubbed` (weather rule) instead of a data failure (t10.py).
why it matters: the round-6 guard (DECISIONS) lists the fields that fail a member; the energy path is outside it, so a hole in one field silently removes a failure mode.

### C-13. `fly_sitl` reads the environment at seconds-since-boot, not at launch time
severity: minor
lane: robustness
where: cafe/pm/physics/uas.py:679 (`self.wind_fn(self.k, self.t, pos)`), :741 (`make_wind(env, origin, ...)`), :753 (`_Sim1(P, prm, wfn, ship0, motor_map)` has no `t_launch`); tests/test_uas_exact.py:143-148
reproduction: `make_wind.fn` calls `env.wind(lon, lat, h, t)` with the `t` it is given; `fly_sortie` passes `t0 + k * DT_ENV` (epoch), `_Sim1.step` passes `self.t` = 0.0, 0.05, ... So any `t_launch` != 0 reads the environment (and `gust(t)`) near the start of its time axis (1970 for the epoch clocks of Stage 1). The test pins the behaviour (`[c[1] for c in calls] == [0.0, 0.05, 0.10]`). The receipts run with `t_launch = 0.0`, so they cannot see it. `ship(t_launch + sim.t)` in `goto` is right.
why it matters: only the (never called) SITL path is affected; the first time it flies a real mission it flies in the wrong weather. Stage 1 and the pipeline do not call it (test_budget.py:556).

### C-14. The free-surface GCI uses a cell-count ratio for a mesh refined in two of three directions, and then treats the GCI as a standard error
severity: minor
lane: numerics / statistics
where: cafe/pm/stage3/freesurface.py:107 (`GRIDS`), :148-165 (`two_grid`: `rr = vv.refinement_ratio(cells_fine, cells_coarse)`), :212 (`spread = hypot(gci*cd, std/q)`); cafe/cfd.py:491-494 (refineMesh `directions (tan1 tan2)`, FS_NZ fixed); cafe/pm/stage3/refit.py:29-44
reproduction: the grids differ only by horizontal nested boxes (1 box vs 4): the cell at the hull goes from H0/2 to H0/16 in x and y (linear ratio 8) and not at all in z, while the reported ratio is (N_fine / N_coarse)^(1/3) = 1.45 and the GCI is Roache's with p = 2 assumed and Fs = 3. The vertical (free-surface) discretisation error is identical in both grids and cancels in the difference, so the difference is not a bound of the total error, and 1.45 is not the ratio of anything. `row_fields` then returns `cd_spread = GCI * cd` (a Fs = 3 bound, order 2 sigma) and `refit.pool` weights and sums it as a standard error.
why it matters: the `fs_gci` and `fs_refinement_ratio` checks (the brief's >= 1.3) pass formally for a number that is not a grid-convergence index.

### C-15. The plate receipt calls itself "Re_L >= 1e6" and prints Re_L = 9.8e5
severity: minor
lane: documentation / honesty
where: cafe/pm/stage3/wallmodel.py:325 (`PLATE_SLOW`), :266 (`rb = ul * (x2 - pre) / nu_lat`), :375-376; docs/PHYSICS.md 14.5; wallmodel.py module docstring ("compared with it only at Re_L >= 1e6")
reproduction: `PLATE_SLOW`: length 384, nose 16, nu_lat 1.5e-5, U_LAT 0.04 -> rb = 0.04 * 368 / 1.5e-5 = 9.81e5; the stored `wm_flat_plate.json` on homebase has `re 981333`, `re_a 53333`, so the strip compared with ITTC-57 runs from Re_x = 5.3e4 (laminar/transitional in reality, imposed turbulent here) to 9.8e5. The row text is "... at Re_L >= 1e6 ... (Re_L = 9.8e+05)". The stored run also has `err 0.165` (> 0.10) and `yfrac 0.79` (< 0.9), so it fails both, as the repo says; the point is the claim string and the strip.
why it matters: the receipt's stated applicability condition is not met by the run that stands for it.

### C-16. Wind above the polar (30 m/s) is clamped silently: the USV sails at hull speed in a 60 m/s wind with no failure
severity: minor
lane: robustness
where: cafe/pm/physics/usv.py:155-169 (`_lin` clamps), :349 (`tws` to 30 m/s), :607-608
reproduction (t7.py): `AnalyticEnv(wind=(60,0), hs=2)`, 6 h, 3 members: no failure at all (`{}`); `through_water_table` at 200 m/s returns stw 3.3. Heel is held at the 25 deg target by depower (max 25.08 in the polar), so `capsize_proxy` can only come from waves. Gust fronts add to the wind, so 30 m/s is reachable in a tropical squall + front.
why it matters: the survival regime is a success, not a flag.

## Checked and found sound (so they are not re-reported)
USV `_strip` signs (heave/pitch system, relative vertical velocity `+U*theta` for bow-down pitch), the Bretschneider integral, Morrison's drag formula, D3Q19 weights and the regularised collision, Ladd moving-wall bounce-back, UAS motor/torque signs (QuadX), battery closed form, flux-pattern length formula, glider DAC steering, the hull-speed and ITTC receipts; UAS sortie in still air: 1186 s, SOC 0.329 (t10.py); 6 m/s: 7 of 8 waypoints (t12.py).

total: 16 findings (0 critical, 6 major, 10 minor)
not covered: line-by-line proof of `lbm.specular` / `bounce_back` Bouzidi branch for moving walls (only the stationary-sphere path is exercised by the pipeline), `fea_window` / CalculiX path, the `cafe.cfd` internals that `freesurface.py` calls, and the full test files for usv/uas/glider/stage3 (I read the tests that bear on C-3, C-4, C-13 and grepped the rest)
