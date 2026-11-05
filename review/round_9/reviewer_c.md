# Round 9, reviewer C: physics/usv.py, uas.py, glider.py, comms.py and all of stage3/

Method: read all of the scope line by line at commit c1dd8cd (08f05d7 code); re-derived the Kerr cubic, divergence factor, Thorp, Stojanovic noise, the strip-theory heave/pitch system, the Gerritsma-Beukelman integral, the Seaglider fixed-point, the quadrotor mixer, torque and attitude error, the Peukert closed form and the nest/wall-model bookkeeping against their sources; ran four short probes on cafe-burst (2 CPUs, detached scratch worktree, removed afterwards). Most of what I checked holds. What follows is what did not.

### C-1. The UAS has no `no_current_data` path: a NaN wind in flight is a silent NaN vehicle, reported only as a mislabelled `profile_incomplete`
severity: major
lane: robustness
where: cafe/pm/physics/uas.py:301-395 (`_block`: no finiteness test on `wind`), :562-605 (`fly_sortie`), :429-447 (`make_wind` passes NaN through); compare glider.py:421-427 and usv.py:562-567, 627-629, which flag `no_current_data`
reproduction: on cafe-burst, `AnalyticEnv(wind=(-4, 0))` subclassed so that `wind()` returns NaN where lon > 0.002 deg (about 220 m east of the ship; the outbound leg heads east, into the wind), then `uas.fly_sortie(env, lambda t: np.zeros(2), 0.0, M=1, origin=(0.0, 0.0))`. Result: all five flags False except `profile_incomplete` (True, from `wp_done` 1 of `n_wp` 8), `landed` False, `ditched` False, `airborne` True, `t_end` 1920 s (the hard stop), `soc_end` NaN, `max_tilt_deg` NaN, last track position `[nan nan nan]`. With the same hole at the ship the launch gate scrubs the member (NaN mean compares False), so the gap is only for a hole met in flight. Stage 1 then takes `np.min` of `soc_end` over sorties (stage1.py, `_run_uas`), so a NaN `soc_end` turns the battery margin into NaN and drops it, with no flag naming the cause.
why it matters: BRIEF 5.6 asks for a vehicle outside the box or a masked cell; the glider and USV label it (rounds 7 and 8, M-14, M-16), the UAS does not, so the same input is a labelled failure for two classes and an unexplained "profile incomplete" plus NaN margins for the third.

### C-2. The platform loaders do not require the `mission_defaults` keys the simulators index: a file that loads fine crashes mid-run with a bare KeyError
severity: minor
lane: robustness
where: cafe/pm/physics/usv.py:121 (`MISSION_REQUIRED` lists only `cap_cycles`), :152; read at usv.py:577 (`corridor_km`), :603-605 (`wp_radius_m`), :615-616 (`becalmed_after_h`), :618 (`track_tolerance_km`), :619, :622 (`roll_limit_deg`, `stall_sustain_s`), :624 (`calm_sustain_s`); glider.py:113 (`check_params({}, ...)`), read at glider.py:393, 397, 477 (`wp_radius_m`, `unreach_hours`, `station_tol_m`, `lost_hours`)
reproduction: copy platforms/saildrone_explorer.yaml, delete `mission_defaults.corridor_km`; `usv.load_platform(copy)` succeeds, then `USVSim(P, 2, AnalyticEnv(), (-165, 0), 0.0, dict(mode="section", waypoints=[(-165, 0), (-164, 0)])).run(7200)` raises `KeyError: 'corridor_km'`. Same for seaglider.yaml without `station_tol_m` (`GliderSim.run` raises `KeyError: 'station_tol_m'` at the first step). Both run on cafe-burst.
why it matters: the round-7/8 design (M-26, M-28, M-35) is that a bad platform file is a ValueError naming file and field at load time; these keys are the exception, and the failure surfaces hours into a pipeline run as a bare KeyError.

### C-3. The stage-3 wall-model gate and the receipts table disagree about a flat-plate run below Re_L = 1e6
severity: minor
lane: honesty
where: cafe/pm/stage3/wallmodel.py:358-383 (`stale_wall_receipts`, `stored_wall_error`: no Reynolds-number test) against :412-415 (`receipts()`: `plate["re"] < PLATE_RE_MIN` is "not a pass whatever its error"); docstring at :358-360 says the two "agree"
reproduction: write `$CAFE_DATA/receipts/wm_flat_plate.json` with `re` 9.8e5, `err` 0.01, and `code_sha` equal to `lbm.physics_sha()`, plus a current channel receipt. `wallmodel.receipts()` fails the plate row ("below the 1e6 the comparison needs"); `stored_wall_error()` returns 0.01 and `windows.stage3_checks` passes `wall_model_receipt_error` (0.01 <= PLATE_TOL 0.10). Homebase's stored plate today is exactly this shape of run (`re` 981333, `cf` 0.003673 vs `ittc` 0.004398, `err` 0.165, no `code_sha`), so only its error and missing sha keep it failing the gate; the Reynolds number is not what does.
why it matters: a window can be marked `ok` and enter the refit on a wall-model receipt the report's own receipts table calls a failure.

### C-4. A stored wall-model receipt that is valid JSON with a `code_sha` but no numeric `err` crashes the whole stage instead of failing the check
severity: minor
lane: robustness
where: cafe/pm/stage3/wallmodel.py:383 (`float(json.loads(f.read_text())["err"])`), called from windows.py:321 inside `run_window`; pipeline_windows.py:562 catches only `(ValueError, RuntimeError)` there
reproduction: store `wm_channel.json` and `wm_flat_plate.json` as `{"code_sha": "<current physics_sha>"}`. `stale_wall_receipts()` returns [] (it checks only existence, readability, sha), then `stored_wall_error()` raises `KeyError('err')` (with `"err": null` it is a `TypeError`); neither is caught by `_row`, so `pipeline_windows.run` and the stage die. `_read_receipt` was written (round 8, M-32) so that a bad file is a failing check.
why it matters: the same file that the table reports as a row can take down the stage; a hand-transcribed receipt is the case the sha rule exists for.

### C-5. A window that diverges in its last chunk is not recognised as diverged: its NaN coefficients enter the row and the FEA is run on NaN pressure
severity: minor
lane: numerics
where: cafe/pm/stage3/windows.py:304 (`if n < steps and not wlog["killed"]`), nest.py:272-273 (`simulate` breaks on a diverged chunk but returns the whole chunk), pipeline_windows.py:565, 571-576
reproduction: `steps` is a whole number of chunks (pipeline_windows.py:557), so a blow-up inside the final chunk leaves `len(ser["F"]) == steps`: `wlog["diverged"]` stays False, `cut = wl["run_steps"] < wl["planned_steps"]` is False, the row takes the non-cut path with `cd = float(r["cd"])` = NaN written into the hashed `stage3/windows.json`, and for the glider hull `_fea` (line 575) is launched on a NaN `wall_pressure` (CalculiX/gmsh time spent, "FEA failed"). The row is still `ok` False because `mach_max` and `force_running_mean_dev` fail on NaN, but the reason reads "mach number nan above the limit" and not "diverged".
why it matters: the divergence logic exists precisely so that a blown-up window says so and spends no more of the slice; it has a hole exactly one chunk wide, and a NaN lands in a hashed output.

### C-6. `comms.acoustic_link` with a scalar range and an ambiguous Bellhop link raises TypeError
severity: minor
lane: robustness
where: cafe/pm/physics/comms.py:324-336 (`margin, label = m_t.copy(), ...` then `margin[amb] = ...`)
reproduction: for 0-d `r` the Thorp margin `m_t` is a `numpy.float64`; `np.float64(1.0).copy()[np.array(True)] = 2.0` raises `TypeError: 'numpy.float64' object does not support item assignment` (checked). So `acoustic_link(4000.0, ssp=(z, c), ambiguous_db=50.0)` with bellhop.exe present reaches line 335 and fails. Without Bellhop or without `ssp` the scalar case works (run: label "Thorp only, no sound-speed profile supplied"). Reasoned for the Bellhop branch, not run (no bellhop.exe in the cafe image on the burst VM).
why it matters: the docstring promises "any shape of r" for `bellhop_tl` and every other function in the module is shape-agnostic; this one is not for the one case it exists for.

### C-7. `fly_sitl` documents "same fields as fly_sortie for one member" and returns a different dict
severity: minor
lane: documentation
where: cafe/pm/physics/uas.py:731 (docstring) against :889-894 (return)
reproduction: the returned dict has `flags` with 4 of the 5 `FLAGS` (no `profile_incomplete`), no `t_first`, `wp_done`, `n_wp`, `ditched`, `airborne`, `failed`, `launch`, `scrubbed`-consistent arrays of the `fly_sortie` shape, and `wind_exceeds_airspeed` and `lost_link` are hard-coded False. Only the slow receipts call it (DECISIONS 310), so nothing breaks today; stage 1 treating a SITL member like a `fly_sortie` member (the stated plan in 310's last sentence) would raise KeyError.
why it matters: a documented contract the code does not meet, in the one function reserved for a later feature.

### C-8. USV `no_current_data` is time-stamped at the start of the step, every other USV flag at its end
severity: minor
lane: reproducibility
where: cafe/pm/physics/usv.py:567 (`_flag` called before `self.t = t + dt` at :599) against :508, :629 and every flag after :599 (stamped `t + dt`); glider.py stamps all flags with `_tf`, the end of the step
reproduction: `USVSim` with a wind NaN from the first step: `first["no_current_data"]` equals the start time `t0`, and `first["no_current_data"]` from the insolation hole (line 629, same step) equals `t0 + dt`. One step (60 s in stage 1) of difference for the same event, and a different convention from the glider's.
why it matters: the history docstring says "first[name] (M,) epoch seconds of the first occurrence"; the verdict timelines in the report mix the two conventions.

total: 8 findings (0 critical, 1 major, 7 minor)

Checked and found correct (no finding): Kerr cubic and divergence factor; Thorp; Stojanovic noise terms and the band integral; Iridium retry logic; glider steady flight (both models), steering/DAC bookkeeping and the energy ledger; USV force sign conventions in the mirrored frame, root search, strip-theory coupled heave/pitch system (derived independently), Bretschneider integral; UAS rotor torques and mixer, attitude error vee-map, Peukert closed form, ship-frame guidance; stage-3 frame rotation, the Galilean relative-velocity bookkeeping, `fit_window`, DerSimonian-Laird pooling. Not covered: see the structured return.
