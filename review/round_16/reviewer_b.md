# Round 16, reviewer B: the simulated mission as physics, second part (links and environment)

Commit af880ee (code of 9328932). Inputs: `q16_mission.json`, the q16 report/ingest/windows files, the code. Reproductions ran on orca at 2 CPUs from a detached worktree (`PMX=pm_rev16_b`), snippets only, nothing written under `/data`.

No critical or major finding. Everything below is minor. Checked and found right (not findings): Thorp formula and its units; Stojanovic noise terms and the in-band integral (Hz); spreading and absorption terms (`acoustic_tl_db`); the anchor (margin 3.00 dB at 4 km, 5 m/s; zero crossing 4.75 km at 5 m/s, 3.5 km at 10 m/s, 8.25 km at 0 m/s, so the report's "GO within 3 km" is conservative); the Kerr cubic and divergence factor against the standard spherical-mirror form; the flat/curved switch at `psi_critical` (no jump: 0.0 dB at the boundary for five antenna pairs, adjacent 2 m steps at most 1.6 dB); 4.12 vs sqrt(2 a) horizon (0.06 %); the glider dive cycle (about 8 h per 950 m dive, 18 apogees in 6 d) and glider_2n's drift (net 128 to 247 km north in 6 d, 0.35 m/s over ground) and energy (9 % of the usable pack in 6 d, about 1.9 W mean); the fitted wind prior's arithmetic (mean 0.45997, between-mooring sd 0.677, persistent 0.569 reproduce from `tao_compare.json`).

### B-1. The default RF sensitivity is the lowest-air-rate datasheet value and the air rate is neither marked assumed nor a lab question
severity: minor
lane: physics, honesty
where: platforms/radios.yaml:10 (`rx_sens_dbm: -121.0`, comment "low air rate only"), platforms/quad_uas.yaml `radio.link: rfd900x`, missions/tepex_c_demo.yaml `radio: rfd900x`; QUESTIONS_FOR_LAB.md has no air-rate question
reproduction: the same file lists `rfd900x_fast` at -105 dBm (64 kbps) "for a video/high-rate MAVLink config". From q16_mission.json, link usv-uas-rf has 1,762 in-horizon margins (min 9.08, median 16.15 dB). Subtract the 16 dB between the two entries: 48.8 % of those samples fall below 16 dB, so would fail; the mean per-member fraction of needed samples met goes from 0.109 to 0.055 (max member 0.336 both).
why it matters: the margin the report prints for this link (median 16.1 dB) and its working fraction are the best case of one radio setting; `rx_sens_dbm` carries no `assumed: true`, so the credibility page does not count it and the lab is never asked which air rate its MAVLink link runs. The verdict (NO-GO, 89 % of needed samples beyond the horizon) does not move.
wrong data: yes (the printed link margin, not the verdict)

### B-2. Nothing checks the ocean current at the EUC depths, and no credibility limitation says so
severity: minor
lane: data, honesty
where: cafe/pm/pipeline.py:925 (`_tao` compares wind and SST only); TAO cache `pmdata/tao/*` holds only WIND, AIRT, RH and SST files; config/perturbations.yaml:23-36 (current error priors are the BRIEF's literature values); docs/CREDIBILITY.md (no limitation row on current skill; L18 and L06 are the only current-related rows)
reproduction: on orca, `hycom.open_store("/data/ocean/gofs_tepex_c_demo.zarr")` mean over the 49 stored 3-hourly times at 0N 170W: surface u 0.10, v -0.27 m/s; u 0.37 at 50 m, 0.64 at 100 m, 0.65 at 125 m (core), 0.51 at 150 m, 0.63 at 200 m, 0.25 at 300 m. The TAO ADCP at T0N170W (the mooring at glider_eq's station) is the check the prompt names and it is not in the cache. The one verdict that depends on this flow is glider_eq (MARGINAL, 18 of 64 `station_lost`); glider_speed_scale does not separate failing from passing members (AUC 0.51) while current_speed_scale does (0.72), so the current decides it.
why it matters: the prior sd (30 %, 20 deg, 100 km) is not fitted to anything for the input that decides the one MARGINAL verdict, and the report's limitation list never says the GOFS EUC (core 0.65 m/s here) is unchecked against the moorings that measure it. A core 30 % off moves a glider's station-keeping outcome more than any fitted input does.
wrong data: no (an undisclosed gap behind a verdict)

### B-3. The glider's "worst window" and the "forcing at windows" row use the surface current, which the glider sees 2.3 % of the time
severity: minor
lane: physics, documentation
where: cafe/pm/pipeline.py:1287 (`CRITERION["glider"]`), cafe/pm/report.py:73 and 913 (`FORCING`)
reproduction: `report.json` environment.forcing_at_windows.glider_eq: "surface current speed" 0.449 m/s at 2023-03-05 09:00Z, while `windows/windows.json` glider_eq failed_at runs 03-02 06:56Z to 03-06 07:04Z (18 members) and the glider is surfaced in 2.3 % of the records (q16_mission.json, mean of `surfaced`). The GOFS surface u mean at the station is 0.10 m/s against 0.65 at 125 m.
why it matters: the window and the number printed beside the failures describe the surface flow at a time unrelated to when any member failed, while the model's station loss comes from the depth-averaged flow of each dive (glider.py:429, 498). BRIEF 5.5 says "max current", which the code reads as the surface; a reader takes 0.449 m/s as the flow that beat the glider.
wrong data: yes (a forcing value shown beside the failures that does not belong to them)

### B-4. The Iridium link cannot fail by construction, and no physical input reaches it
severity: minor
lane: physics, honesty
where: cafe/pm/stage1.py:612-625 (`evaluate_link`, Iridium branch), cafe/pm/physics/comms.py:162-164, platforms/radios.yaml `iridium.sbd` (p_success 0.95, max_attempts 3: both assumed)
reproduction: a sample succeeds with probability 1 - 0.05^3 = 0.999875; the link has 865 independent samples per member and needs 0.95. P(a member falls below 0.95) = P(more than 43 failures in 865 at 1.25e-4) < 1e-90. q16 shows frac 0.99991 mean, 64 of 64 successes. No Hs, wind, heel, antenna height (`iridium_antenna_height_m` is read by no code, usv.py:132), position or vehicle state enters; the latency that `iridium_session` computes is dropped (`[0]`).
why it matters: "GO, P(fail) 0" is the assumed 0.95 restated, for any mission and any weather. Real session failures are correlated in time (sea state, a low antenna on a heeling hull). The report says "no range dependence" but not that the environment cannot change the result.
wrong data: yes (a GO that no input can overturn)

### B-5. The USV's energy has no sampled input and no reported margin, so its 64 members are one sample
severity: minor
lane: statistics, physics
where: cafe/pm/physics/usv.py:667-672, cafe/pm/stage1.py:45 (`ACTS`: usv has only `usv_vpp_bias`), cafe/pm/env/perturb.py (`air` passes through unperturbed), config/assumptions.yaml `env.sigma.swdown_frac` ("replace_with: TAO SWRAD residual", not done)
reproduction: soc' = clip(soc + (0.20 x 2.0 m2 x SWDOWN - 80 W) dt) with WRF SWDOWN unperturbed in every member, no battery scale (`battery_capacity_scale` is glider and UAS only), and a 4000 Wh pack. All 64 members see the same insolation series (positions differ by a few km). The balance is near neutral: 0.4 x 200 W/m2 = 80 W, so a mean of 150 W/m2 empties the pack in 4000 / 20 = 200 h. q16 `fail.battery` 0 of 64 is one deterministic outcome, not 64 trials; the SOC minimum is not reported anywhere (the USV's margin is cross-track error).
why it matters: a USV that passes everything else would get a Wilson interval on `battery` treating the members as independent, with no energy uncertainty in it and no margin to show how close it was. The TAO cache has no SWRAD to fit the 20 % assumed error.
wrong data: no for the demo (the USV fails on other modes); yes for a mission whose USV is otherwise GO

### B-6. Link positions are interpolated in raw longitude across 180 deg
severity: minor
lane: robustness
where: cafe/pm/stage1.py:515 (`_pos`, `np.interp(t, r["t"], a[:, m])` on `lon`)
reproduction: orca, `stage1._pos("usv", out, mission, tq)` with records lon 179.99, -179.99, -179.97 at t = 0, 600, 1200 s and a ship at -179.95: at t = 300 s the interpolated lon is 0.0 and the distance to the ship is 20,009,527 m (at the records themselves 6,672 and 4,448 m). `_dist` handles the wrap; the interpolation before it does not.
why it matters: `t` is the record grid for most links (exact at nodes) but is unioned with the UAS's 30 s sortie grid for `uas_airborne` links, so the other end is interpolated between its 10 min records. A USV or ship crossing 180 deg during a sortie gets a 20,000 km range for those moments: beyond the horizon, a failed moment. The demo's box straddles the dateline (lon_min 165, lon_max -165), so a lab variant can do this.
wrong data: no in the demo; yes for a mission with a vehicle crossing 180 deg during a UAS sortie

### B-7. A glider's surfacing is shorter than the record grid, so some surfacings are never judged
severity: minor
lane: numerics
where: cafe/pm/physics/glider.py:339 (`surf_s` = gps_s 120 + bytes/Bps 250 + pump 120 = 490 s), cafe/pm/stage1.py:39 (`REC_S` 600 s), stage1.py:586 (`_surfaced` on the record grid)
reproduction: a surfacing of 490 s holds a 600 s grid record with probability 490 / 600 = 0.82, so 18 % of surfacings contain none and are not "moments the link was required". glider_eq need_count is 14 to 24 per member for about 18 apogees; glider_2n 56 to 92.
why it matters: the fraction of required moments is estimated from a random 82 % of the surfacings, and a link that works at only one surfacing position can pass or fail by which records fall in. The record grid, not the vehicle, decides which surfacings exist for the link.
wrong data: no (adds noise to `frac`; the demo's link verdicts are decided by range)

### B-8. The RF link's wave height is taken at the two ends of the link, not at the specular point
severity: minor
lane: physics
where: cafe/pm/stage1.py:262-280 (`_link_hs`) and 644 (`np.minimum(*[rf_margin(..., h) ...])`), comms.py:`two_ray_curved_db`
reproduction: for the USV (2.2 m) and the UAS (108 m) at 30 km the specular point is at R1 = d ht / (ht + hr) = 0.6 km from the USV and 29.4 km from the UAS, so only the sea within about a kilometre of the low antenna enters the roughness factor. The code evaluates the link in Hs at the USV and in Hs at the UAS's ground position (30 km away) and takes the lower margin of the two, which is the minimum of two fields neither of which is the reflection's. `kerr_reflection` returns R1 and is not used to place the Hs query.
why it matters: round 15's rule (M-3) makes the answer independent of the order of the names, which is right, but not the right sea: the margin at an interference null can differ by up to 20 dB between the two Hs, and the pessimistic pick is a bias, not a physical value.
wrong data: no (no verdict in the demo rests on it)

### B-9. Near the horizon the RF model is 7 to 12 dB more optimistic than a smooth-earth diffraction field, and the docstring calls its stand-in conservative
severity: minor
lane: physics, documentation
where: cafe/pm/physics/comms.py:`two_ray_loss_db` docstring ("the plane-earth loss stands in for it and is conservative by construction"), `rf_margin` (cliff to NO_LINK_DB at `radio_horizon_km`); k fixed at 4/3 (`A_EFF`)
reproduction: orca, `rf_margin(0.999 H, ht, hr, 1.0)` for the radio rfd900x: 11.9 dB (ht 2.2, hr 108.1, H 48.9 km), 9.1 dB (hr 18.1, H 23.6 km), 7.0 dB (hr 8.1, H 17.8 km). ITU-R P.526 section 3 smooth-earth diffraction (k 4/3, 915 MHz, sea, F(X) + G(Y1) + G(Y2), coded by hand from the recommendation's formulas, not from a library) at the same distances gives margin 0.1 dB, 2.2 dB (and about -5 dB per 5 km beyond). The model's loss at H is 140.1 dB for the first pair against about 152 dB. Above the horizon the margin steps from +12 dB to -200.
why it matters: the claim "conservative by construction" is not backed against the diffraction field at the horizon; the model keeps a link that P.526 gives zero margin, and cuts a link that P.526 degrades smoothly. Refractivity (k) is a constant although the environment holds T, q and SST. The demo is far past the horizon (89 %) so no verdict moves; a mission at 20 to 25 km would see the difference.
wrong data: no in the demo

total: 9 findings (0 critical, 0 major, 9 minor)
