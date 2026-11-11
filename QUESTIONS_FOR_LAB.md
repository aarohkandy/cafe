# Questions for the lab

Nothing here blocks a run: every item already has a working default in the code, and every answer is a mission-file
edit, a platform-file edit or an environment variable (`CAFE_ORCA`), not a code change. Each says what we do now and what changes if your answer differs.

1. **HYCOM for `run_2023mar_waves_v4`.** Is there a HYCOM run (or a coupled companion) for this case, and is it
   `archv.*.a/.b` or per-snapshot netCDF? Does it write in-situ or potential temperature?
   *Default:* HYCOM GOFS 3.1 GLBy0.08 expt_93.0 (in-situ T, 3-hourly, 40 z-levels). *If yes:*
   set `environment.ocean: {source: lab_hycom, path: /data/ocean/lab_tepex_c_demo.zarr}` in the mission, then
   `python -m cafe.pm ingest-ocean --mission missions/tepex_c_demo.yaml --path <dir> --temperature-kind <in_situ|potential>`
   (archv files also take `--grid <regional.grid stem>` when it is not next to them). The reader is already round-trip tested on
   synthetic `.a/.b` and netCDF files built from GOFS values. Currents then come from the same model as the waves'
   forcing, and the current prior (±30 %) can be narrowed.

   1a. **Longest step of the lab's ocean store inside the window** (review round 8, M-2). A lab store is accepted when its times cover the window with no step longer than 24 h between them
   (`pipeline.OCEAN_MAX_STEP_S`); the ocean is interpolated linearly in time, so a longer step would make the current a straight line across it. *Default:* 24 h, so the daily mean of a reanalysis is accepted and a 36-hour step is refused with the step named. *If your model's output is sparser:* tell us the cadence and whether linear interpolation is acceptable; the limit is one constant (a code change).

2. **Hourly wave spectra and Stokes drift.** The 6-hourly `restart/umwmrst_*.nc` spectra on orca are used (every
   6 h, every 3rd sea point). Could UMWM be re-output with `outspec > 0` at the mission waypoints and
   `stokes = .t.`? *Default:* real spectra at 00/06/12/18 Z, a DHH/JONSWAP spectrum fitted to `swh dwp dwd mwp mwd
   mss` in between, Stokes drift integrated from that spectrum. *If yes:* hourly spectra replace the fit and the
   Stokes term becomes data instead of modelled (report badge changes from MODELLED to DATA).

   2a. **Are the `umwmout_YYYY-MM-DD_HH:MM:SS.nc` files stamped at the start or the end of the hour?** (review round 10, M-22) A UMWM file carries no
   time in its content (no global attributes, no time variable), so the hour in its name is the only label, and WRF's files are checked against their
   `Times`. If an output is stamped at the end of an averaging period, the waves are shifted by that period against the wind and nothing flags it.
   *Default:* the hour in a file's name is its valid hour (the waves of `umwmout_..._12:00:00` are those at 12 Z, the same instant as the WRF file of that name).
   *If they are end-stamped:* every UMWM field is one hour late against WRF, and the read in `orca.umwm_hour` has to take the file one hour later (a code
   change); a content cross-check (UMWM `wspd` against WRF 10 m speed by lag) would then be worth building (DECISIONS 556).

3. **`SST_UPDATE = 0`.** Was the frozen 1 March SST intentional? Is there a run with `sf_ocean_physics` or coupled
   SST? *Default:* frozen WRF SST + the COARE warm-layer model, enabled and badged MODELLED; the TAO comparison
   quantifies the frozen-SST error. *If a coupled run exists:* lay its files out like orca's WRF files and re-point `CAFE_ORCA` at them (the mission file has no atmosphere
   path and no source other than `orca_uwincm`; `validate` refuses `local_wrf` and `path` and names this route); the warm layer stays on only
   if its SST has no diurnal cycle. A coupled run also needs the schema and the fetch check changed: `cafe/schemas/wrfout.json` pins `SST_UPDATE` 0, `SIMULATION_START_DATE` and `DX`, and `orca.wrf_grid` refuses a file that differs, so a coupled-SST file is refused at fetch today; once they are loosened the SST label and the grid spacing in the data-source text follow the file's attributes (review round 13, M-30; DECISIONS 722).

4. **Which platforms TEPEX-C will fly** (Saildrone Explorer vs Voyager; Seaglider vs Slocum; which UAS), with mass,
   CG, geometry or CAD, propulsion and battery curves, speed polars or flight-model coefficients, comms hardware and
   antenna heights. *Default:* `platforms/seaglider.yaml`, `slocum.yaml`, `saildrone_explorer.yaml`,
   `quad_uas.yaml`, each number cited or marked `assumed`. *If supplied:* edit those files (or add new ones) and
   check each with `python -m cafe.pm hangar --platform <name>`, which lists every value still marked assumed.
   Verdicts then describe your vehicles instead of the class defaults.
   One number of the UAS file is asked for by name (review round 4, M-10): what is the radio failsafe timeout, i.e. how long may the telemetry link be down before the aircraft returns?
   *Default:* `radio.link_loss_hold_s` = 5 s, assumed from ArduCopter's GCS failsafe default (`FS_GCS_TIMEOUT`, recalled, not re-read); a shorter fade is ridden through. *If supplied:* edit it in `platforms/quad_uas.yaml`.
   Two numbers of the Saildrone file are asked for by name (review round 3, M-8): is there a minimum apparent wind angle below which the vehicle cannot hold a tack, and what is it?
   *Default:* `min_awa_deg` = 15 deg, assumed with no source (the polar still gives positive speed inside it). *If supplied:* edit `params.min_awa_deg` in `platforms/saildrone_explorer.yaml`.
   (d) Do the range limits the loaders enforce fit your vehicles? (review round 6, M-9 and M-10) The limits are bounds of the model that we chose, not datasheet values: a platform leaf outside its range
   (for example `stw_cap_ms` above 50 m/s, `gravity` above 20, `rudder_x_m` 0, Seaglider `hd_s` outside -0.9 to 0) is refused at load, and a mission with `dive_depth_m` outside 1 to 2000 m (for a glider, outside its
   `min_dive_m` to `rating_m`), `radius_km` outside 0.01 to 1000 or `lost_after_h` above 720 is refused by `validate`, each message naming the field and the limit.
   Since review round 9 (M-22) a glider or USV file must also carry every `mission_defaults` key its model reads, each in a range we chose: USV `becalmed_after_h` and `corridor_km` above 0, `calm_sustain_s` and `stall_sustain_s` 0 or above, `track_tolerance_km` above 0 and at most 1000, `wp_radius_m` above 0, `roll_limit_deg` above 0 and at most 180; glider `dive_depth_m`, `station_tol_m` and `wp_radius_m` above 0, `lost_hours` and `unreach_hours` 0 or above.
   *Default:* those limits. *If a real vehicle or mission is outside one:* tell us the number, and the limit in `cafe/schemas/mission.json` or the platform's `REQUIRED` table is widened (a code change).

   4a. **The default glider hull: wall thickness and the buckling knockdown** (review round 13, M-38). Stage 3 now runs the FEA's buckling step on the glider hull and stores the larger of the stress and the knocked-down buckling utilization. For the default hull (`platforms/seaglider.yaml`: Al 6061, 8 mm wall) the stress utilization is 0.305 (von Mises p99 84.3 MPa against 276 MPa yield), the linear buckling utilization 0.756 (follower-corrected factor 1.3225) and, with the 0.5 knockdown for imperfect shells (`hangar.KNOCKDOWN`), 1.512: the model hull collapses at 330.6 m on the converged mesh (L/70, review round 15, M-14; the 364 m and 1.374 first quoted here were the L/20 mesh, 10 % unsafe, and the 1000 m rating of the Seaglider is not reached by this hull). The Slocum hull the stage-3 assumptions describe (1.5 x 0.22 m, same wall and material) collapses at 654.6 m, inside which glider_2n's 500 m order lies. glider_eq orders 950 m, and the report says so beside its verdict (a warning, no cap). How much that matters was measured on the q15 draws with only the dive depth changed (glider_eq alone, EUC flow profile): 18 of 64 members lose station at 950 m, 38 at 700 m, 60 at 500 m and 64 of 64 at 364 m (the L/20 collapse depth; 331 m was not re-flown, the series is monotone). The loss is the depth-mean eastward current against the glider's 0.2 to 0.28 m/s of swim speed (the Equatorial Undercurrent is eastward at 100 to 200 m and slightly westward below 400 m), so the shallower the order, the more of the dive is in the jet, and the dive depth is not a free choice. Is the wall thickness (and the material) the real pressure hull's, is the 0.5 knockdown too conservative for it, and should an ordered depth beyond the hull's collapse depth be refused rather than warned about?
   *Default:* the platform file and the knockdown 0.5 stay; the stage-3 utilization reads above 1 (1.512) for the default glider hull and the 950 m order carries a warning. *If you answer:* a thicker wall, another material or another knockdown is a platform-file or `hangar.KNOCKDOWN` change; no verdict reads the value today (no pm code consumes `fea['utilization']`).

5. **Mission definition.** Deployment windows, waypoints, station-keeping tolerance, surfacing schedule, which
   link pairs must hold and what outage is acceptable, and the go/no-go thresholds the PIs actually use.
   *Default:* `missions/tepex_c_demo.yaml` (brief section 6; GO at P(success) >= 0.9, NO-GO below 0.6).
   *If different:* edit the mission file: `verdict: {go: ..., nogo: ...}` is read by the verdict, the stopping rule and the what-if
   search, and `validate` refuses values outside 0 < nogo < go <= 1 (GO also needs the Wilson lower bound on success >= min(0.75, go), and `validate` prints a note when `go` is above 0.75); `python -m cafe.pm validate --mission <file>` checks it before a run.
   Two parts of the mission definition are open (review round 3). (a) What does a drift glider have to do (heading, and what is its pass/fail criterion)? *Default:* it swims on the fixed
   `task.heading_to` written in the mission (the demo writes 0.0, due north) and can only fail by battery, depth or the seafloor, so its GO carries no mission criterion and the report says so.
   *If you give one:* use `mode: station` or `section` where the glider has a station or waypoints, or set `heading_to` to the intended heading; a success criterion for a drift glider needs a code change.
   (b) How long may a calm last before it counts as a USV failure? *Default:* `wing_stall_calm` after 30 min of apparent wind below 1.5 m/s (`calm_sustain_s` 1800 s) and `becalmed` after 6 h of being unable to stem
   the current (`becalmed_after_h` 6 h), both assumed and different on purpose. *If your threshold differs:* edit those two `mission_defaults` in `platforms/saildrone_explorer.yaml` (the first is the platform's, the second can also be set in the mission's `task`).
   (c) How long may a UAS sortie take, and what is the shortest acceptable flux profile (how many of the stacked levels must be flown)? (review round 4, M-1) *Default:* the demo asks for 20 min and four levels (a pattern of 8 waypoints);
   the return-to-ship timer ends a sortie at `duration_min` x `sortie.time_limit_factor` (1.0, assumed) = 1200 s, and a sortie that returns before its last waypoint is the failure `profile_incomplete` (`sortie.min_profile_fraction` 1.0, assumed).
   The nominal pattern takes 1127 s of flight, so it is complete only up to about 5.2 m/s of 10 m wind (measured on the sortie before review round 15; since M-10 a leg is held to the airspeed envelope and the share of sorties reaching all 8 waypoints falls off at a lower launch wind, DECISIONS 841 and 877, so the edge is lower and not re-measured). *If your answer differs:* edit those two keys in `platforms/quad_uas.yaml`, and `sorties.duration_min` in the mission.
   (d) Should the 90 % lower-bound term of GO follow `verdict.go`? (review round 8, M-7) Now it stays at 0.75 for any `go` above 0.75, so with `go: 0.99` nine members without a failure are GO (DECISIONS 68, 153). *Default:* no, as now; `validate` and the report's rule sentence say so. *If it should follow:* a decision, then a one-line change in `intervals.set_thresholds`.
   (e) Are the flux-profile heights (10, 30, 60 and 100 m in the demo) above the sea or above the deck? (review round 15, M-13) *Default:* above the deck (`sortie.deck_height_m`, 8 m for the quad), so the legs fly at 18, 38, 68 and 108 m above the sea, where the wind is read and the radio antenna sits (DECISIONS 844); the schema and the report say so. *If your answer differs:* give the heights above the sea less the deck height, or ask for the levels to be referenced to the sea, which moves every UAS wind, link and turbulence number.

6. **The lab server.** GPU model(s) and VRAM, CPU cores, RAM, disk, OS, who administers it, and whether there is a
   user account with Docker. *Default:* designed for one 32–96 GB NVIDIA GPU + 32–64 cores; everything also runs
   CPU-only (as on `az_serv` today, with LES windows labelled CPU-fallback). *When it exists:* `make install bench
   acceptance GPUS=1` there; the planner re-sizes every stage from that machine's measured throughput.

7. **Validation truth.** Is TAO/TRITON for March 2023 acceptable as the wind/SST truth, and is there in-situ wave or
   current data from the 2023 TPOS Saildrone mission we can use? *Default:* TAO only; the wind prior in the
   ensemble is replaced by the fitted TAO error. *If Saildrone data is shared:* it becomes a second validation set
   for wind, SST, waves and the USV speed model (`cafe.pm.env.tao.compare` takes any time series).

   7a. **Should the persistent wind prior be its 95 % upper bound?** The TAO fit gives a persistent wind-speed sd of 0.113 m/s from 11 moorings in
   one 6-day regime, a boundary estimate (the sampling variance of a mooring mean, about 0.15, is as large as the variance between the 11 moorings, 0.14, so the true spread
   is estimated as 0 and the 0.113 is only the uncertainty of the mean of 11 moorings). On the TAO cache of 6 Nov 2026, which holds delayed-mode files NOAA added on 5 Nov,
   14 moorings have a wind in the window and the same fit gives 0.569 m/s (95 % upper bound 0.957; direction 5.25 deg, bound 12.15): the figure depends on which moorings
   exist, and one mooring (T5S165E) decides it (0.1545 without it, 95 % bound 0.495: measured in round 14, DECISIONS 804).
   Its one-sided 95 % upper bound is about 0.5 m/s (`value_hi95` in `ingest/priors_fitted.json`; the literature prior was 2.0 m/s), and regime-to-regime
   bias outside the six days is not sampled. *Default:* the point estimate stays the prior (BRIEF 5.2); the report prints both, and `docs/CREDIBILITY.md`
   lists the question as L19. *If the bound should replace it:* a decision, then a small code change in `pipeline._tao` (write the bound as `value`).

8. **FluidX3D licence.** Is FluidX3D's licence (no commercial or military use; modifications must be published)
   acceptable for NOAA use? *Default:* the FluidX3D backend exists but ships disabled; free-surface windows use
   interFoam on CPU. *If yes:* after reading `docs/LICENSES.md`, build FluidX3D and set
   `"fluidx3d": {"enabled": true, "binary": "/path/to/FluidX3D"}` in `config/premission.json` (only the JSON boolean `true` turns it on; a quoted "false" or a 1 is refused with a message, DECISIONS 735).

9. **Campaign date, box and file layout.** Confirm spring 2028, 160°E–160°W, 5°S–5°N, and whether a 2028-season
   forecast run (not the 2023 hindcast) will be produced before deployment. *Default:* 2023 hindcast layout
   (`cafe/schemas/wrfout.json`, `umwmout.json`, `umwmrst.json`); ingest refuses any file that does not match.
   *If the layout changes:* regenerate the schemas from one new file and re-point `CAFE_ORCA` (an environment variable, the only route: the
   mission file cannot name another atmosphere or wave source).

10. **Forecast mode.** Will UWIN-CM run in forecast mode during the campaign, and at what latency?
    *Default:* offline hindcast. *If yes:* the same `run_premission` runs daily against the newest files; the
    ingest is already resumable and bounding-box only.

11. **The orca run is still growing.** `run_2023mar_waves_v4` has 2023-03-01 00Z to 03-07 18Z today (it is under
    `temp/`). Will it reach 12 March? *Default:* the demo window is 03-01 12Z to 03-07 12Z. *If it grows:* widen
    `window` in the mission file; nothing else changes.

12. **Glider-to-ship acoustic and USV-to-UAS radio geometry in the demo.** The brief puts the gliders at 170°W and the ship at 165°W
    (about 550 km apart) and requires a glider↔ship acoustic link at every surfacing; an ATM-960 MF modem reaches
    ~4 km, so the demo run reports that link NO-GO in every member. Is there a second ship, a relay (the USV with a
    modem), or is the glider data meant to go over Iridium? *Default:* the mission is run exactly as written and the
    report says why the link fails (range, not environment). *If a relay or a different ship position:* add it to
    `missions/tepex_c_demo.yaml` (a `ship` or a link with `a: glider_eq, b: usv`); nothing else changes.
    The same holds for the radio: the demo places the gliders 555 and 598 km from a 4 km modem, and the USV up to 111 km from a ship whose radio
    horizon with the UAS is 24 to 49 km, so the RF NO-GO follows from the ship geometry, not the environment. Please give the intended positions.
    *Default:* the demo's positions as given.

    12a. **Antenna polarisation, and the sea temperature and salinity at the RF link** (review round 12, M-12). The RF model reflects the sea with a coefficient of -1. The Fresnel
    coefficient of a vertical-polarised wave on sea water at 915 MHz has magnitude 0.70 at a grazing angle of 1 deg and 0.26 at 5 deg, so -1 is within 10 % of the magnitude only
    below about 0.3 deg (`docs/PHYSICS.md` 12.1). Which polarisation do the antennas on the ship, the USV and the UAS have, and what are the sea temperature and salinity along the link?
    *Default:* vertical polarisation (assumed; the antennas are taken as 2 dBi in `platforms/radios.yaml`, with no polarisation stated) and sea water at 29 C and 35 (eps_c 72.8 - j118.9 at 915 MHz, sigma 6.05 S/m, which gives that eps'', both
    assumed): the model keeps -1 and states the error band, up to 7.6 dB optimistic at interference peaks and conservative at nulls; no demo verdict rests on it (usv-uas-rf is NO-GO
    because 89 % of its needed moments are beyond the radio horizon, and the UAS lost-link mode is 0 of 64). *If you answer:* a horizontal-polarised wave reflects closer to -1 at
    these angles (not computed here), another temperature or salinity changes eps_c; either way the full Fresnel option is a code change in `two_ray_curved_db` (a function of the
    grazing angle in place of -1), which moves every printed RF margin, the goldens and the parameter-file hashes (DECISIONS 652).

13. **The UAS frame-only drag.** The Hangar `d_x` for the quadrotor includes the rotor momentum drag, so a stage-3 LES of the frame alone cannot be
    compared with it like for like. Can you split `d_x` into its frame and rotor parts, or give the frame's Cd*A?
    *Default:* UAS stage-3 windows are never used in the refit (on a CPU machine they are not run at all, see `STATUS.md`). *If supplied:* no code reads such
    a key yet (`cafe/pm/stage3/pipeline_windows.py` sets `comparable=False` for the UAS window), so the answer needs a small code change: read the frame-only
    reference from `platforms/quad_uas.yaml` and set `comparable` from it. The UAS windows then become usable for the refit once a window passes its checks.

14. **Does Chiodi et al.'s 0.178 include currents?** The Saildrone speed prior is calibrated to the mean speed over ground / mean wind of Chiodi et al.
    (0.96 m/s over 5.4 m/s). That ratio was observed in real ocean currents, while the calibration scenario of the tool has none. In the q5 run the
    ensemble's median ratio is 0.135 at the anemometer height, the height Chiodi's 0.178 is defined at (0.129 per 10 m wind; review round 9, M-7); in the nominal diagnosis scenario of review round 2 (not the ensemble) it was 0.120, and the
    westward current alone lowered it from 0.186 to 0.150 by turning a beam reach into a close-hauled course. If the 0.178 already contains the effect of currents, the tool penalises the current twice. Which is it, and if you have the
    underlying Saildrone tracks, what was the current along them?
    *Default:* assume the 0.178 does not include currents; the prior stays as calibrated, the report prints the mission ratio beside it, and
    `docs/CREDIBILITY.md` lists the question as L18. *If it does include currents:* `vpp_bias_mean` in `platforms/saildrone_explorer.yaml` has to be
    recalibrated with the same current in the calibration scenario (a code change, since `usv.mean_sog` has no current), which makes the USV faster in the mission.

    14a. **Which Chiodi target matters more, the 5.4 m/s mean or the 12 m/s maximum?** (review round 7, M-4) The polar is capped at 3.3 m/s, so no single speed bias meets both:
    the bias is solved for the 0.96 / 5.4 mean, and Stage 1 then flies 2.215 m/s at 12 m/s against Chiodi's 2.9 (24 % under; the unbiased polar's 2.92 is what `appendage_cda_m2` was fitted to).
    *Default:* the 5.4 m/s mean is met and the 12 m/s maximum is not; both rows are in the receipts table and `docs/CREDIBILITY.md` lists it as part of L02. *If the maximum matters more:*
    a different bias and a different cap, which is a recalibration (a code change).
