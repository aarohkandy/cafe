# Reviewer C, round 8: usv.py, uas.py, glider.py, comms.py, platforms/, stage3/, PHYSICS.md for them, their tests

Commit 95085cb. Every reproduction below was run on homebase at 1 CPU in `~/work/cafe/pm_rev8_c` (scripts and logs in
`/private/tmp/claude-501/-Users-aaroh--claude-spares-spare-P6utrU/96cd665b-6853-40e7-8769-780fbfcaeebd/scratchpad/rev8/c/`, `t*.py`, `m_*.json`, `m_*.out`).
Mutation runs copy the repo into the container's /tmp and edit the copy; the repo and `pm_rev8_c` were not edited.
What held up (checked, no finding): the USV polar converges (sway and yaw residual below 2.1e-4 over 1934 moving cells; 48 iterations against 400 differ by at most 0.025 m/s),
the flat-plate wall model at CI size gives the same C_f with 3 % inflow turbulence and without (0.00557 against 0.00560, `t22.py`; the Re_L >= 1e6 case at tu = 0 was not run), every number in PHYSICS 10.1/10.2 that I recomputed (bias rows 0.2345/0.1642/0.1584/0.1525 of U, 1.554 m/s and R_aw 312.6/207.9/155.6/129.3 N, 0.545 m/s at TWS 6 TWA 15, MF margin
-3.94 dB at 10 m/s, calibration 0.96001 m/s at 5.4 m/s), the Galilean invariance of `through_water` (2.5e-15 m/s), glider and USV loaders refuse NaN/inf/negative/string/missing leaves with
file and field named, 256 members x 30 d USV in 53 s and glider in 18 s at 1 CPU.

### C-1. `through_water_table` (what Stage 1 flies) and `through_water` (the direct solve; what Stage 3 and the receipts use) disagree by up to 0.8 m/s near the bow cone, against the documented "the two agree"
severity: minor
lane: numerics / documentation
where: cafe/pm/physics/usv.py:353-369 (table, 1 m/s x 2.5 deg grid, linear `_lin`), :328-337; claims at usv.py:20-21, docs/PHYSICS.md 10.1 ("the direct solve agrees"), receipt "Stage-1 table == direct current-coupled solve" (usv.py:748-754, 5 hand-picked states, tol 0.02)
reproduction: `t16.py`/`t17.py`: 20 000 random states (wind relative to water 0..14 m/s, current up to 1 m/s, random heading), `max |stw_table - stw_direct|`: TWS 0-4: 0.148 m/s; 4-8: 0.455 m/s (47 of 7444 states above 0.2); 8-12: 0.749 (63 of 8983); 12-16: 0.813. All 121 states above 0.2 m/s (242 above 0.05) have a true wind angle of 12.6 to 14.8 deg (7 % of the states inside 30 deg of the wind), in the cell where V collapses from 0.55 m/s (TWA 15) to 0 (TWA 12.5) and `_lin` smears the cliff
(e.g. wind (7.67, 13.79), current (0.13, 0.60), heading 224.3: direct 0.000, table 1.039 m/s; leeway differs by up to 11.4 deg).
why it matters: Stage 1 and the stage-3 window kinematics see different through-water speeds for the same state in about 1 % of close-hauled states, and the receipt that is meant to catch a table/solve divergence samples none of them.

### C-2. The `hull_fs` window hull displaces about 2.7 times the platform's mass; no document mentions it
severity: minor
lane: physics
where: cafe/pm/stage3/pipeline_windows.py:168-179 (ellipsoid semi-axes lwl/2, beam/2, `usv.hull_draft_m` 0.45; keel plate), config/assumptions.yaml:243-247, cafe/pm/stage3/freesurface.py:52-72
reproduction: waterline at body z = 0 (freesurface.write_stl), so the submerged volume is half the ellipsoid: 2/3 pi x 3.25 x 0.60 x 0.45 = 1.838 m3 = 1880 kg at rho_water 1023, plus the keel box (0.667 x 0.10 x 2.21 m = 0.148 m3 = 151 kg): about 2.03 t against `mass_kg` 750 (saildrone_explorer.yaml) and against the strip theory, which uses the mean draft (M/rho)/waterplane = 0.12 m (usv.py:382). The `hull` (no free surface) window is a fully submerged ellipsoid of 3.75 t. Only the wetted-area ratio (1.29 / 2.6) is stated (`wetted_area_note`).
why it matters: the free-surface resistance (wave making grows with displacement) that is divided by `usv.hull_resistance` and refitted into Stage 1 is for a hull 2.7 times too heavy.

### C-3. Empty or comment-only platform YAML crashes with a bare TypeError (usv, glider) or a misleading message (uas)
severity: minor
lane: robustness
where: cafe/pm/physics/usv.py:128-130, cafe/pm/physics/glider.py:88-90, cafe/pm/physics/uas.py:100-103
reproduction: `usv.load_platform(<file containing "">)` and `glider.load_platform(<same>)`: `TypeError: argument of type 'NoneType' is not iterable` (`raw` is None before `k not in raw`; the round-7 M-35 fix only covers a non-empty file). `uas.load_platform`: `ValueError: platform numbers without a source or an assumed+why: ['']`. Same for a file with only a comment. (`t11.py`)
why it matters: BRIEF 4 "a vehicle yaml ... a specific, actionable error naming the file, field and fix"; a truncated file (a failed copy) is the likeliest bad lab file.

### C-4. A battery internal resistance of 0 (allowed: `r_int_ohm: "nonneg"`) gives NaN charge, voltage and position, and no flag ever fires
severity: minor
lane: robustness / numerics
where: cafe/pm/physics/uas.py:83 (kind), :259-267 (`_batt`: `cur = (voc - sqrt(...)) / (2 * rint)`)
reproduction: `P["battery"]["r_int_ohm"] = 0.0`; `check_params` passes; `_scenario(P, 2, _hold(10.0, 2), zeros(3), t_max=6)`: `soc_end [nan nan]`, `energy_wh [nan nan]`, final voltage `[nan nan]`, final position `[nan nan nan]`, `flags["battery_reserve"] [False False]` (NaN compares False, so `dead` and `n_batt` never trigger; the run goes to the hard stop with a silent NaN). (`t5.py`)
why it matters: an ideal-pack sensitivity run, a natural lab experiment, returns NaN verdict inputs with no labelled failure.

### C-5. Array-valued platform leaves are not checked for shape or order, and a list is accepted for a scalar
severity: minor
lane: robustness
where: cafe/pm/physics/uas.py:78-93 (`ocv_soc`, `ocv_cell_v`, `inertia_kgm2` kinds), cafe/pm/physics/__init__.py:39-52 (`check_params` tests only finiteness and sign), usv.py:105-117, glider.py:68-77
reproduction (`t5.py`, `t10.py`, `t11.py`): `ocv_soc` reversed: loads, flies, `jnp.interp` on a descending axis silently returns wrong voltages. `ocv_cell_v` with one element short: loads; `ValueError: xp and fp must be one-dimensional arrays of equal size` only when a sortie flies. `inertia_kgm2: [0.0025, 0.0025]`: loads; `TypeError: mul got incompatible shapes (2, 2), (3, 2)` at fly time. `mass_kg: [750.0, 760.0]` in the USV file loads (`check_params` "pos" is an elementwise test); `usv.tables(P)` then raises `TypeError: can't multiply sequence by non-int of type 'float'`. Same acceptance for `battery_J` (glider) and `mass_kg` (uas).
why it matters: load-time refusal naming the field is the repo's stated rule (glider.py:66-67); these fail late, obscure, or wrong.

### C-6. The USV wing window sizes its boundary-layer resolution with the span (5 m) as the plate length, not the 1.2 m chord the flow runs along
severity: minor
lane: numerics
where: cafe/pm/stage3/pipeline_windows.py:182 (`W.Vehicle(platform, "air", max(c, P["wing_span_m"]), ...)`), :357 (`lbm.les_resolution(veh.length, ...)`), :439 (`why_failed` uses the same `delta_te`)
reproduction: wing area 6.0 m2 and span 5.0 m give chord 1.2 m; flow along the chord. At U = 5 m/s, nu_air 1.5e-5: delta_te(L = 5 m) = 0.37 x 5 x (1.67e6)^-0.2 = 0.105 m; delta_te(L = 1.2 m) = 0.37 x 1.2 x (4.0e5)^-0.2 = 0.0336 m. The planned dx is delta_te / 10, so 3.1 times coarser than BRIEF 2.6 asks for this wing, and the "resolution below the rule" sentence tests the 5 m value, so it cannot report the shortfall. The y+ self-check measures the real cells and is the only thing that catches it.
why it matters: the sizing rule the planner and the row text report for the wing is for a different body than the one flown.

### C-7. `comms._run_bellhop` prepends the Bellhop directory to PATH on every call
severity: minor
lane: robustness / performance
where: cafe/pm/physics/comms.py:270
reproduction: `t18.py`: three `bellhop_tl` calls change `len(os.environ["PATH"])` 70 -> 80 -> 90 -> 100 (`/data/bin:/data/bin:/data/bin:/venv/bin...`): 10 characters per call, unconditionally. A single environment string is limited to 131 072 bytes on Linux (MAX_ARG_STRLEN), so about 13 000 calls in one process (`stage1._bellhop_member` calls it twice per member and link) make every later `bellhop.exe`/`subprocess` exec fail with E2BIG; it is also visible to every child process meanwhile.
why it matters: latent failure in a long, many-member, many-link run; one `if` removes it.

### C-8. Tests that do not fail when the named behaviour is removed (mutation sample, 71 mutants run over usv.py, comms.py and glider.py; the stage-3 batch is appended at the end if it finished)
severity: minor
lane: tests
where: tests/test_usv.py (tack tests at 380-411), tests/test_comms*.py, tests/test_glider.py; mutants in `m_usv.json`, `m_cm.json`, `m_gl.json`
reproduction: each mutant applied to a copy and the module's test files run with `-x`; SURVIVED means all tests passed.
- usv.py:574-575 `pen = ... self.stw * tack_time_s / tack_horizon_s` replaced by 0: survives. The penalty is not cosmetic: upwind to a station 55 km away for 24 h with 8 members gives 34 tacks with it and 144 without (`t9.py`; path 66.8 km against 58.3 km, final distance 7.2 against 12.5 km); `test_upwind_tacks...` asserts `n_tacks >= 3` only.
- usv.py:586 `tack_speed_frac` replaced by 1.0 (no slow-down during a manoeuvre): survives.
- usv.py:234 foil aspect ratio `ar = 2 span^2 / area` (the free-surface image doubling, claimed in PHYSICS 10.1) replaced by `span^2 / area`: survives; keel and rudder lift slopes and induced drag are untested.
- usv.py:568 `g = ... + (cur + stokes)` in the heading search without `stokes`: survives (the motion update is tested, the planning is not).
- usv.py:577-580 `self.hd = np.where(free, cand[best], self.hd)` with the not-free branch set to `cand[0]` (north): survives. The branch is dead with the shipped numbers: `free` is evaluated only at a replan (`replan_s` 300 s) and `tack_time_s` is 120 s, so it is always true.
- comms.py:172 Iridium retry cost `first * fail_cost_s` removed: survives; no test checks that a retried message is later.
- comms.py:193 turbulence noise slope (17 - 30 lf -> 17 - 20 lf) survives (outside the modem bands, harmless); comms.py:91 second divergence-factor plane survives (matters only at steep angles).
- glider.py (25 mutants, 9 survive): `reserve_frac` removed from the battery flag (glider.py:463) survives because tests/test_glider.py:383-384 compares the first-fire time with `rel=0.2` while the factor is 0.10; `speed_scale` removed from the vertical speed (:428) survives; `bytes_per_dive / iridium_Bps` removed from the surfacing time (:312) and `attitude_J_per_dive` removed from the per-dive energy (:313) survive; the pilot-ballast trigger margin `d` halved (:343) survives; the steering reference speed taken at the surface instead of mid-depth (`k = 5`, :351) survives; the stall speed `u_min_ms` set to 0 (:186) survives; the Slocum rule `dF * pitch > 0` (buoyancy against pitch, :222) removed survives; the waypoint capture radius halved in the advance rule (:383) survives.
- stage 3 (7 of 15 planned mutants finished before I stopped the batch, with `-k` limited to the unit-level tests, `m_s3.json`): `windows.coefficients` `cd_spread = cd_s / sqrt(nb)` (the standard error of the five block means, windows.py:192) replaced by the standard deviation `cd_s`: survives, so a factor 2.24 on the spread that feeds the refit sigma is untested; `e_l = _unit(zb - (zb @ e_d) * e_d)` (the lift axis perpendicular to the flow, windows.py:184) replaced by `_unit(zb)`: survives, so a lift axis that is not perpendicular to the drag direction passes every `coefficients` test; the other five (pool tau^2, the single-window floor, the rotation's left axis, the wing's angle-of-attack sign, the keel's factor 2) were killed.
why it matters: BRIEF 5.5/5.1 ask for a test that fails when the physics is wrong; these terms change published outputs (tack count, resistance) without any test noticing. `docs/mutation.json` does not exist yet, so the 85 % gate has not looked at them.

### C-9. `stw_cap_ms` that is not a multiple of the 0.05 m/s search step makes the polar exceed the cap
severity: minor
lane: numerics
where: cafe/pm/physics/usv.py:277-279 (`np.linspace(0, cap, nv)`, step cap / (nv - 1)) against :313-314 (`Vg[i0] + frac * DV`, `K = (x0 - x1) / DV`), receipt at :713
reproduction: `t2.py`: cap 3.33 -> polar maximum 3.33030 m/s (> cap, so the receipt "no (TWS, TWA) in the polar exceeds the hull-speed cap", upper bound cap + 1e-9, fails); cap 3.37 -> 3.3697; cap 0.04 (allowed, "pos<=50") -> 0.05 m/s. `K` is scaled by 0.05 while the grid step is 0.0497.
why it matters: a lab value for the hull-speed cap is not a multiple of 0.05; the load check lets it through and the model is silently inconsistent (Stage 1 clamps afterwards at usv.py:541, Stage 3's direct solve does not).

### C-10. One non-finite start position removes the pilot ballast shift for the whole glider ensemble
severity: minor
lane: robustness
where: cafe/pm/physics/glider.py:343-348 (`need_lo, need_hi = n.min() - d, n.max() + d`, `if need_lo < lo or need_hi > hi`)
reproduction: `t8.py`, 2 members in a stratified column (rho 1000 to 1060 kg/m3 over 500 m): start lons `[180, 180]` -> `ballast_kg` 0.00398; `[180, nan]` -> `ballast_kg` 0.0 and the finite member's VBD settings are unchanged. `n.min()` / `n.max()` are NaN, both comparisons are False, so no shift is made for anyone (the NaN member only fails `no_flight`, as intended).
why it matters: a member that starts on a land cell silently changes the trim of the others; the USV's M-16 fix isolated its non-finite member, the glider's did not.

### C-11. Documented "within 2 km the curved model is the plane-earth result to 0.15 dB" is false at interference nulls
severity: minor
lane: documentation
where: cafe/pm/physics/comms.py:126, docs/PHYSICS.md 12.1 ("Within 2 km it is the plane-earth result (0.15 dB)")
reproduction: `t20.py`, `max |two_ray_loss_db(curved) - two_ray_loss_db(a_eff=FLAT_A)|` for d = 100..2000 m at 915 MHz: ht 2.2, hr 10: 0.19 dB; ht 2.2, hr 18.1, Hs 0: 0.73 dB; ht 2.2, hr 108.1 (UAS at the top level), Hs 0: 26.3 dB; ht 10, hr 18.1, Hs 0: 28.9 dB, Hs 1: 2.4 dB. The differences sit at nulls, which move by a fraction of a wavelength between the two geometries.
why it matters: the claim is used to say the curved model reduces to the validated plane-earth one near the ship, where the UAS spends its sortie; at low Hs the lost-link time series differs at nulls.

### C-12. `fly_sortie` reports a scrubbed member's `t_end` as the other members' simulation end; `fly_mission` crashes on an empty launch list
severity: minor
lane: robustness / documentation
where: cafe/pm/physics/uas.py:547 (`t_end=np.where(np.isnan(S.t_end), t + DT_ENV, S.t_end)`) vs :591 (all-scrubbed branch: `t_end=0`), :604-605 (`np.stack([])`)
reproduction: `t21.py`, M = 2, duration 90 s, member 0 in 20 m/s wind (scrubbed), member 1 calm: `scrubbed [True False]`, `t_end [144. 144.]`; when both are scrubbed `t_end [0. 0. 0.]`. `uas.fly_mission(env, ship, [], M=3)`: `ValueError: need at least one array to stack` (`t6.py`; `stage1` guards `len(ts)` itself, so only direct callers see it).
why it matters: the same field means two things depending on the other members; nothing in the docstring says which.

### C-13. Nonsense parameter ranges and mission values are accepted and only fail (or do not fail) later
severity: minor
lane: robustness
where: cafe/pm/physics/usv.py:105-117 (kinds are `pos`), glider.py `GliderSim.__init__`/`_begin_dive`
reproduction: `t2.py`: `wing_stall_deg` 120, `heel_target_deg` 120, `min_awa_deg` 400, `wing_trim_deg` 200, `keel_stall_deg` 200 all load and build a finite polar (the post-stall branch is evaluated with cos(s) < 0 and discarded by `np.where`; `heel_target_deg` 120 feeds `sin` of an angle past 90). `stw_cap_ms: 1e300`/`mass_kg: 1e300` load. `GliderSim` with `dive_depth_m = -50`: `ValueError: z should be generally negative; found max(z) = 50.0` from gsw (`t8.py`), unnamed; `GliderSim.__init__` takes `min(dive_depth_m, rating_m)` (glider.py:282) with no lower bound.
why it matters: the loaders advertise a range check per field; these fields have none.

### C-14. `fly_sitl` binds its physics socket on all interfaces and answers any sender
severity: minor
lane: robustness / security
where: cafe/pm/physics/uas.py:750 (`sock.bind(("0.0.0.0", 9002 + 10 * inst))`), :848-868 (`recvfrom`, `sendto(sim.reply(), addr)`)
reproduction: reasoning from the code: the firmware is started with `--model JSON:127.0.0.1`, so loopback is enough; the bind is on 0.0.0.0 on homebase, which sits on the tailnet (and other people's services run on it). Any host that can reach UDP 9002+10*inst and sends a 40-byte packet with magic 18458 or 29569 advances the simulation by one step with its servo values and receives the JSON state at its own address.
why it matters: a stray packet corrupts a receipt run and the reply is a reflector; `127.0.0.1` costs nothing.

### C-15. The on-disk USV table cache is unused, and its key does not include the code
severity: minor
lane: reproducibility
where: cafe/pm/physics/usv.py:153-155 (`_digest`), :420-435 (`tables(P, cache_dir)`)
reproduction: `grep -rn "cache_dir" cafe/pm` finds no caller of `usv.tables` with a `cache_dir`; the docstring and module header advertise "optionally on disk". Round 7 M-18 added `N_IT` to the digest because a code constant changed the table, which shows the digest is only a list of the numeric parameters plus that one constant: `DV`, the TWS/TWA grid, `_forces` and every other change in this file keep the same key. A caller who passes `cache_dir` keeps a stale polar across a physics fix.
why it matters: dead code with a latent stale-result mode; delete it or key it on the source hash as `lbm.physics_sha` does.


total: 15 findings (0 critical, 0 major, 15 minor)
not covered: the mutation sample did not reach cafe/pm/physics/uas.py (JAX tests take minutes per mutant at 1 CPU) and finished only 7 of 15 planned stage-3 mutants; no GPU path, no real Bellhop or ArduCopter SITL run beyond one Bellhop TL probe; the XLB reference cases in stage3/lbm.py (poiseuille, cavity, taylor_green, sphere), nest.sphere_drag/richardson numerics, the OpenFOAM free-surface child, FEA (fea_window) and the FluidX3D plugin were read but not exercised; the Re >= 1e6 flat plate (1.9 h) was not run; the docs/PHYSICS.md sections 9.1 and 5.x numbers for the glider were not recomputed.
