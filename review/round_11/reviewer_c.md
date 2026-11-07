# Round 11, reviewer C

Scope: `physics/glider.py`, `physics/uas.py`, `physics/comms.py` and every file of `stage3/` (`lbm.py`, `nest.py`, `wallmodel.py`, `windows.py`, `pipeline_windows.py`, `freesurface.py`, `refit.py`, `fluidx3d.py`), read line by line at commit `095c094` (code of `778d8b6`). Every equation was checked against `docs/PHYSICS.md` and its source.
Reproductions ran on orca at 2 CPUs (`PM_HOST=cafe-orca PM_RUNTIME=proot PMX=pm_rev11_c[2] PM_CPUS=2 bin/pmx.sh python <script>`) from a detached copy of the repo; the copy and the `pm_rev11_c*` directories on orca were removed at the end. Nothing in the repo was edited.

Checked and found sound (so the next reader need not redo it): `_sg_core` algebra (D = l^2 q (b q^s + c alpha^2) reduces to the printed fixed point; derived by hand), the Slocum `_alpha_gf` Newton, `slocum_steady` signs, the trim ballast shift, `GliderSim` phase machine and DAC steering sign (`h = sqrt(1-r^2) e - r perp`), `kerr_reflection` cubic, `divergence_factor` (derived from the tangential and sagittal focal lengths of a convex mirror), `ament_rho`, Thorp, Stojanovic noise (all four terms), the docstring figures of `two_ray_loss_db` (0.8 / 1.0, 26 / 29, 20 / 34, 2.4, 0.3 dB: recomputed, all hold), `_dyn` (rotor layout, torque signs, quaternion update, deck contact), `_ctrl` (mixer is the exact inverse of `_dyn`'s torque map), `_batt` closed form, `utau_loglaw` against brentq from y+ = 3 to 2e7 (max relative error 7e-8), `richardson` against exact power laws, the Hou 1996 and regularised-collision constants, `ittc57_mean`, the Cf definition of `flat_plate`, `pool` (DerSimonian-Laird), the receipts of glider, comms and UAS (`sitl=False`) all pass on orca at 2 CPUs and the Seaglider numbers of PHYSICS 9 (0.2284 m/s, ratio 3.04) reproduce. A box carried by a uniform stream in the nest (wall model on or off, specular on or off) feels |F|/(rho U^2 d^2) of 1e-5 to 1e-4. q11's stage-3 windows were all skipped as unreachable, so the LES path was exercised only by toy windows.

### C-1. Curved-wall bounce-back applies the moving-wall term of the halfway wall for q >= 1/2: a sphere carried by the stream feels 0.39 rho U^2 d^2
severity: minor
lane: physics
where: cafe/pm/stage3/lbm.py:261-262 (`bounce_back`, the Bouzidi branch), docstring 244-253; cafe/pm/stage3/nest.py:206 passes the body velocity to it for any geometry with `qdist`; docs/PHYSICS.md 14.1 ("moving wall (Ladd 1994) ... curved wall (Bouzidi ...)")
reproduction: `uniform_flow_force` with the sphere given the exact wall distance (`make_geom(..., qdist=lbm.ellipsoid_q(shape, c, (r, r, r)))`), everything else as in `nest.uniform_flow_force` (nest 40x28x28, dx 0.01, u = (1, 0.3, 0), vehicle velocity = flow velocity, 400 steps). Script `p3.py` in the scratch copy:
```
halfway  (max |F|/fs, mean of last 100 steps): 9.3e-06  8.6e-06
bouzidi  : 7.78  0.389              (centre offset 0.3 cells: 7.4  0.357)
```
Cause: for q < 1/2 the interpolated population is a convex combination of two populations, and subtracting 6 w rho c.u_w from it is right. For q >= 1/2 the interpolation is `f_post/(2q) + (2q-1)/(2q) f_post[opp]`, and the wall term belongs inside the 1/(2q) factor (Bouzidi et al. 2001; Lallemand and Luo 2003: 3 w rho c.u_w / q), but line 262 subtracts the full 6 w rho c.u_w after the interpolation. For a fluid moving with the wall the post-collision populations are the equilibrium of u, and the result is w (1 + 3 (1-q)/q c.u - 6 c.u) instead of w (1 - 3 c.u): exact only at q = 1/2. With the term scaled by 1/(2q) for q >= 1/2 (one `jnp.where` in the scratch copy) the same run gives 2.8e-6 (centre offset 0.3 cells: 6e-6).
Mutation check of the same branch: replacing the second term of the q >= 1/2 interpolation (`(2 * q - 1) / (2 * q) * f_post[OPPj]` by `... * f_streamed`) passes all of `tests/test_lbm.py` and `tests/test_nest.py` (295 s on orca); the Bouzidi tests (`tests/test_nest.py:342-398`) all use `u_wall = 0`.
why it matters: a curved moving wall is documented as supported and the nest receipt for a body carried by a stream (`uniform_flow_force`) tests only the halfway wall. No pipeline path reaches it today (`windows.run_window` calls `make_geom` without `qdist`; `sphere_drag` is a stationary wall), so no printed number is wrong, but the first window run with `qdist` and a moving body (the "ground" frame, or a refinement of the voxel hull) would carry a spurious force of the order of the drag.

### C-2. The glider's apogee overshoot is counted per step, so it is 0.5 w pump_time only when pump_time is a multiple of dt and dt <= pump_time
severity: minor
lane: physics / numerics
where: cafe/pm/physics/glider.py:448 (`depth + apogee_overshoot * w_last * dt` in every APO step), 467 (`timer = pump_time_s`), 461-463; platforms/seaglider.yaml:30 and slocum.yaml:30 ("sets the depth overshoot (~ 0.5 * w * pump_time)")
reproduction: `GliderSim` (Seaglider, drift mode, `AnalyticEnv(wind=(0, 0), rho=1025.)`, dive depth 500 m, one day), maximum depth minus 500 m (script `p9.py`):
```
pump_time 120 s, dt  60 s:  6.05 m   (0.5 w pump = 6.05 m)
pump_time 150 s, dt  60 s:  9.08 m   (7.57 m documented: three APO steps)
pump_time 100 s, dt  60 s:  6.05 m   (5.04 m)
pump_time 120 s, dt 120 s:  6.02 m
pump_time 120 s, dt 300 s: 14.95 m   (5.98 m: one APO step of 300 s)
```
why it matters: at the shipped 120 s and 60 s it is exact, but the platform file is the thing the lab edits (pump_time_s is a sourced number a lab will replace with the real pump), and the overshoot is what `overdepth` and `seafloor` test (C-5 of round 10). A pump_time of 150 s gives 20 % more overshoot than the yaml says; a coarser dt (receipts and tests call `run(dt=...)`) several times more. The yaml should say "per APO step", or the overshoot should be `0.5 w_last * pump_time` applied once.

### C-3. `fly_sitl` compares the vehicle position (relative to the launch point) with a target in the ship's absolute frame, so it only works when the ship is at the origin at launch
severity: minor
lane: robustness / correctness
where: cafe/pm/physics/uas.py:771 (`ship0`), 802 (`_Sim1(..., ship0, ...)`: `sim.p` starts at 0, i.e. relative to `ship0`), 860-866 (`goto`: `tgt = ship(t_launch + sim.t)[:2] + rel` is absolute, `pos = sim.p` is relative to `ship0`; `math.hypot(*(pos[:2] - tgt[:2]))`), 913 (`tr["pos"]`: `p - ship(t_launch + sim.t)`)
reproduction: by reading, the SITL binary is not installed on orca. With `steaming(pos0=(1000, 0))` or any `t_launch > 0` for a steaming ship (`ship(t)` is absolute on the epoch clock, `steaming` is `pos0 + vel * t`), `tgt` is `ship0 + ...` while `pos` is `0 + ...`: the arrival test `< tol_h` is never true, `goto` runs to its `limit_s` (4 x `duration_s` of simulated, i.e. real, time, per waypoint) and returns without an error, and `track["pos_rel"]` is off by `ship0` (it should be `p + ship0 - ship(...)`). The firmware itself is commanded correctly (`tgt - ship0`), the wind is read at `p + ship0` (correct), so only the arrival logic and the returned track are wrong. All callers (the slow receipts and `tests/test_uas.py`) use `steaming()` at the origin with `t_launch` 0, which hides it.
why it matters: latent (no stage flies SITL, DECISIONS 310) but the docstring presents `fly_sitl` as taking any ship and any launch time.

### C-4. `defaults.spreading_k` in platforms/modems.yaml is read by nothing; the lab editing it changes no margin
severity: minor
lane: data / honesty
where: platforms/modems.yaml:10 (`spreading_k: 1.5`, "Stojanovic 2007 practical spreading"); cafe/pm/physics/comms.py:188, 216, 238, 306 (each has its own `k: float = 1.5`)
reproduction: `grep -rn spreading_k cafe` finds no reader; of the `defaults` keys only `ref_wind_ms`, `ref_shipping`, `anchor_margin_db`, `ambiguous_db` and `valid_range_factor` are read. A scan of every leaf of seaglider, slocum, quad_uas, radios, modems and saildrone_explorer yaml for a name that appears in no code finds this one only. Setting it to 2.0 changes no `acoustic_margin`.
why it matters: the yaml is the file the lab is told to edit ("Parameters live in platforms/radios.yaml and platforms/modems.yaml"), and PHYSICS 12.2 / DECISIONS 63 present k = 1.5 as a model choice; a lab that moves it to 2 (the deep-water value PHYSICS says Bellhop prefers) sees nothing happen and the implementation loss derived at the same k would also have to move.

### C-5. A modem name typed as a bare modems.yaml key with capitals passes `load_mission` and ends stage 1 with `KeyError`
severity: minor
lane: robustness
where: cafe/pm/config.py:288-290 and 357-358 (`_modem_names` and the check are case-insensitive); cafe/pm/stage1.py:636 (`modem, band = next(..., (lk["modem"], "MF"))` keeps the name as typed); cafe/pm/physics/comms.py:_band (`_yaml("modems.yaml")["modems"][modem]`, case-sensitive)
reproduction: script `p10.py`: the demo mission with `modem: benthos_atm960_mf` replaced by `modem: Benthos_ATM960`:
```
load_mission accepted: ['Benthos_ATM960', 'Benthos_ATM960']
stage 1 resolves it to ('Benthos_ATM960', 'MF')
stage 1 would raise KeyError 'Benthos_ATM960'
lowercase bare key resolves to ('benthos_atm960', 'MF')
```
(`BENTHOS_ATM960_MF`, with the band, resolves correctly because the generator compares lower-cased.) `evaluate_link` runs after the vehicles of a batch are simulated, so the error comes after the expensive part.
why it matters: a mission the loader accepted fails with a bare `KeyError` late in stage 1. Also undocumented: a bare key silently takes band MF.

### C-6. RUNBOOK step 6 promises a sub-grid calibration file after a GPU run that nothing can write
severity: minor
lane: documentation / honesty
where: docs/RUNBOOK.md:199 ("After a GPU run whose LES windows passed, the run's sub-grid calibration is in `.../stage3/subgrid_calibration.json` and the stages after stage 3 already used it."), docs/CREDIBILITY.md L13 ("holds in every CPU run: no LES window has passed"); cafe/pm/stage3/pipeline_windows.py:738-744 (`recalibrate_subgrid` needs a row with `inflow_series`)
reproduction: `grep -rn inflow_series cafe` finds two lines, both in `recalibrate_subgrid`; no code puts `inflow_series` in a row, and `_row` runs every window with the uniform inflow `jnp.stack([0, 0, 0])` (pipeline_windows.py:567). docs/PHYSICS.md 5.x says so ("The windows of this build use a uniform inflow, so no series is resolved"), the ledger note says so for a run with passed windows, but RUNBOOK 199 and the "CPU run" wording of L13 say the opposite for a GPU run. So `promote-calibration --run <GPU run>` has nothing to copy.
why it matters: a lab with a GPU follows the RUNBOOK, waits for the file and gets a "none carries a resolved inflow-turbulence series" note instead; BRIEF 2.2's recalibration is not reachable on any machine.


### C-7. Tests of the UAS thresholds pass on mutants of the lines they name (reserve fraction, no-headway window, launch-gate samples, lever arm, link hold)
severity: minor
lane: verification
where: cafe/pm/physics/uas.py:373 (`n_batt = new(flying & (soc < prm["reserve"]), ...)`), 374 (`n_stuck = new(stuck >= prm["stuck_w"], ...)`), 471 (`ts = t_launch + np.array([0.0, 0.5, 1.0]) * so["duration_s"]`), 144 (`arm=f(af["motor_radius_m"] / math.sqrt(2))`), 553 (`hit = (run_s >= link_hold_s) & ...`); tests/test_uas.py:282-292, 295-303
reproduction: mutate one line in the scratch copy on orca and run `python -m pytest -q -x tests/test_uas.py tests/test_uas_exact.py -k "not twenty and not 256 and not receipts and not sitl"` (fast tests, about 56 s); every one of these passes (SURVIVED):
```
373  soc < 0.5 * prm["reserve"]          (the battery_reserve flag at half the reserve_frac)
374  stuck >= 2 * prm["stuck_w"]         (wind_exceeds_airspeed after 20 s without headway instead of the yaml's 10 s)
471  [0.0, 0.5, 0.5]                      (the launch gate's mean wind over three times of the sortie, the last one dropped)    -k "launch or scrub or wind": 19 tests
144  arm = motor_radius (no / sqrt 2)    (a lever arm 41 % too long; the closed loop is invariant to it, no open-loop torque test)    -k "torque or tilt or hover or controller or sortie": 17 tests
553  run_s > link_hold_s                  (a link lost for exactly link_loss_hold_s is ridden through)     -k "link or fade or hold"
```
Why: `test_battery_reserve_flag_with_first_time` compares a pack scaled to 1.0 with one scaled to 0.2 (nowhere near the 0.2 reserve); `test_wind_exceeding_what_the_airframe_can_make_headway_against` uses 14 m/s, where the flag is set long before either window; no test sets a launch wind that only the third time exceeds; `test_rotor_torque_signs...` checks signs only. (For comparison the glider's reserve is pinned, `test_r8_m43_the_battery_flag_fires_at_the_reserve_not_at_empty`.)
why it matters: `reserve_frac` and `stuck_window_s` are lab-editable yaml numbers (assumed) that decide `battery_reserve` and `wind_exceeds_airspeed`, and nothing holds them to the file.

### C-8. Tests of the stage-3 adapter pass on mutants of the window sizing, the glider window's vertical flow, the wall pressure and the viscous switch
severity: minor
lane: verification
where: cafe/pm/stage3/pipeline_windows.py:372 (`short ** 0.25`), 225 (`math.sin(math.radians(th))` in the glider's through-water velocity); cafe/pm/stage3/windows.py:318 (`pwall = (mean - 1.0) / 3.0 * rho_f * (dx / dt) ** 2`); cafe/pm/stage3/wallmodel.py:49 (`YPLUS_LAM`); tests/test_stage3.py:863-873, 876-892, 447-457
reproduction: on orca, `python -m pytest -q -x tests/test_stage3.py -k "fit or sizes or run_all or plan or share or window or budget or slice or hangar or glider"` (54 tests, 1052 s) with the glider line changed to `-math.sin(...)`: passes. With `short ** 0.5` (a much coarser dx than the budget needs; the documented rule is the fourth root, cells ~ dx^-3 and steps ~ dx^-1) and the same selection minus the last two words (53 tests, 1086 s): passes, because `test_fit_window_follows_the_budget_and_the_body` asserts only that dx grows as the budget falls and that `cell_steps <= budget`, both true for any larger exponent. With `/ 3.0` removed in `pwall`: passes `-k "run_window or fea"` (245 s) because the only assertion on `wall_pressure` is its shape and sign (test_stage3.py:456-457). With `YPLUS_LAM = 14.0`: passes `-k "loglaw or wall_state or channel"` (13 tests).
The glider line matters most: the window frame is built from `vb = R @ (v - u_env)`, `R = rotation(heading, pitch)` with pitch -14 deg and the glide angle -18.2 deg, so the relative flow arrives 4.2 deg from below the body axis (alpha = +4.2 deg). With the vertical sign flipped the glider is climbing at +18.2 deg with its nose 14 deg down, an attack angle of -32 deg, every glider window's drag and lift would be those of a stalled body, and `test_hangar_numbers_are_the_vehicles_own_models` still passes because it asserts `rel[0] > 0`, `rel[1] ~ 0` and the signs in `info`, never `rel[2]` or the angle between the body axis and the flow.
why it matters: these are the lines that turn the plan into a window (how coarse, at what incidence, with what load for the FEA); none is wrong today, but none would be caught.

### C-9. Kernel and glider details that no test holds: the sponge ramp, the apogee overshoot value, the "stuck" reset, the surfacing pump work
severity: minor
lane: verification
where: cafe/pm/stage3/nest.py:144 (`(1 - kk / (spec.sponge + 1.0)) ** 2`); cafe/pm/physics/glider.py:448, 400, 476
reproduction: on orca, each of these changes passes the whole test file of its module: `nest.py:144` with `** 2` removed (a linear ramp, where PHYSICS 14.1 and the module docstring say quadratic, Davies 1976): all 35 tests of `tests/test_nest.py` (101 s); `glider.py:448` with the overshoot halved (`0.5 * P["apogee_overshoot"]`, though removing it altogether is caught): all 41 tests of `tests/test_glider.py` (169 s); `glider.py:400` with the `0.0` in `np.where(bad, self.stuck_s + cyc, 0.0)` replaced by `self.stuck_s` (the unreachable-waypoint time then adds up over non-consecutive dives instead of "for `unreach_hours` in a row"): all of `tests/test_glider.py` (179 s); `glider.py:476` with `+ pump_energy_J(dV, 0.0, P["pump_eta"])` removed (the pump work against 1 atm at each surfacing, about 40 J of 17 MJ per dive): all of `tests/test_glider.py` (182 s).
why it matters: smaller than C-7 and C-8; the first and third change what the code does, the others only a number that is small today.

Mutants that were killed (so these need not be repeated): comms divergence factor, Kerr h2, psi_critical exponent, Iridium failed-attempt cost, Bellhop excess sign, RF horizon factor, valid-range factor; UAS launch gate, time limit, `uas_leg_speed` lower bound, tilt formula; Hou constant, lattice dt, restrict, `neq_ratio`, ITTC strip mean, near-wall damping, mass drift (max to mean), running-mean block count, ellipsoid area exponent, `row_fields` spread, DerSimonian-Laird denominator, lift axis; glider apogee overshoot removed, DAC divisor, temperature profile, atmospheric pressure in the pump work. 49 mutants were run in all (29 + 17 + 3, `-x`, orca, 2 CPUs); the ones that survived are C-1 (second term), C-7, C-8 and C-9 above, and "leg_length corner term removed" (a 12.8 s change of a 1186 s sortie, inside the receipt's 5 % band, so equivalent for practical purposes).

total: 9 findings (0 critical, 0 major, 9 minor)
