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

   4b. **The USV's solar panel yield and the shortwave error of the window mean** (review round 16, M-10). The USV's insolation is sampled by `solar_yield_scale`: lognormal, median 1, sigma 0.20, the `env.sigma.swdown_frac` relative error of hourly model shortwave applied to a member's whole window, **assumed**; the panel's area (2 m2) and efficiency (0.20) are the platform file's assumed numbers. Do you have the panel's measured yield, and the error of WRF's window-mean shortwave against a radiometer (the TAO SWRAD residual is the stand-in we would fit)? *Default:* sigma 0.20; the pack capacity is not sampled; the report prints the lowest state of charge of the members as the USV's battery margin (demo: median 0.7356, none emptied). *Lead's choice, awaiting the owner:* the new column re-draws every member of a mission with a USV, so the demo's counts moved by re-sampling (glider_eq 18 to 15 of 64, USV 62 to 61, UAS 61 to 62, no verdict) (DECISIONS 915); the alternative is `battery_capacity_scale` as the only USV energy input, with no new column and no insolation sampled. Default: keep the column.

5. **Mission definition.** Deployment windows, waypoints, station-keeping tolerance (the mission's `radius_km`, default 5 km, and `lost_after_h`, default 6 h, when the task omits them: the glider platform file's `station_tol_m` and `lost_hours` are read by no verdict, review round 17, DECISIONS 940), surfacing schedule, which
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

   (f) How many delivered flux profiles must a UAS member have to count as having done the mission? (review round 16, M-5) *Default:* one flown sortie, as now: a member fails for scrubbed launches only when none of its launches flew (`no_sortie_flown`), the sortie shares are over the sorties that flew, and the report states how many launches the weather gate scrubbed (3 of 384 in the demo) beside them (DECISIONS 888). *If your answer differs:* a decision, then a change to the failure rule in `stage1`; the verdict rule is not changed by the count alone.

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

   7b. **Are TAO/RAMA ADCP records at the moorings acceptable as the truth for the ocean-current prior?** (review round 16, M-7) The current prior (`current_speed_scale`, sigma 0.30, and `current_direction_bias`, 20 deg) is the BRIEF 2.5 literature value and is compared with no in-situ current record: the mooring comparison covers wind and SST only, no ADCP is read, and the credibility page lists this as L21 (waves and subsurface temperature and salinity likewise, L22). *Default:* no ADCP is ingested, the BRIEF 2.5 prior stands and L21 says so. *If yes:* ingest the ADCP files and fit the current prior as the wind prior is fitted (a code change).

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

    12d. **Low RF antennas, and the lowest antenna height a platform may have** (review round 17, M-5 and M-6, review round 18, M-3; DECISIONS 925, 926, 944, 945, 957, 979). The two-ray model's reflection coefficient of -1 makes the field vanish with the antenna height, where the sea's own coefficient leaves a floor, and its error is of the PAIR of antenna heights. Against a Fresnel two-ray of the assumed sea (`docs/PHYSICS.md` 12.1, 300 m to the horizon) the direction depends on the pair: a link to the Slocum's 0.3 m with a partner of 2.2 m or 15 m has its loss overstated by about 1 to 6 dB, a link with both ends 0.5 m or lower (two gliders, which the loader accepts) by 6 to 11 dB, and 0.1 m with 15 m by 11 to 16 dB, and the Seaglider's 0.5 m with the USV's 2.2 m whip by 1.8 to 2.7 dB, so for those pairs a margin is too low and a GO can show as MARGINAL or NO-GO; for 0.5 m with a 15 m partner, two 2.2 m ends and 2.2 m with 15 m the loss can be understated by up to 2.9, 2.4 and 3.3 dB (and overstated by up to 2.2, 1.6 and 0.2 dB), so a margin there can be too high as well as too low. A pair of heights that was not measured (a UAS end, a ship mast other than 15 m) has no stated band. Limitation L23 and the link card say so. Which antenna heights do the lab's vehicles really have, and which polarisation and sea temperature (12a)? *Default:* the -1 stays; a platform's RF antenna height must be 0.1 m or above (the loader refuses lower); two low ends on one RF link are accepted and carry the stated band. *Alternative:* refuse an RF link with both ends below 0.5 m, a floor of 0.5 m with a warning below it, or the Fresnel coefficient of the assumed sea (a code change that moves every printed RF margin, the goldens and the platform-file hashes).

    12b. **At which air data rate does the lab fly the RFD900x USV-UAS link?** (review round 16, M-6) The default sensitivity, -121 dBm, is the radio's datasheet value at its lowest air data rate, the best case; `radios.yaml` also lists `rfd900x_fast` at -105 dBm. *Default:* the lowest rate, -121 dBm, marked assumed (DECISIONS 889); a faster rate lowers every RF margin by the difference in sensitivity (-111 dBm at 12 kbps, about -98 dBm at 200 kbps: 6 dB less margin for each step down). No demo verdict moves with it (usv-uas-rf is NO-GO because 89 % of its needed moments are beyond the horizon). *Lead's choice, awaiting the owner:* keep -121 dBm (DECISIONS 914).

    12c. **Is the smooth-earth diffraction loss near the radio horizon wanted?** (review round 16, M-14) The RF loss between the critical grazing angle and the horizon now includes the ITU-R P.526 smooth-earth diffraction loss (4/3-earth, vertical polarisation over sea); the plane-earth stand-in was 6 to 12 dB optimistic against it at the horizon of the demo's antennas, so printed RF margins near the horizon fall by 5 to 11 dB (the margin of a 15 m / 3 m link at 20 km 13.0 to 8.1 dB). It is within -2.8 to +0.3 dB of the exact residue-series field from 0.5 to 3 horizons for five antenna pairs; it is not verified for other frequencies, sea states, a k other than 4/3 or antenna pairs outside 8 to 108 m over 2.2 m. *Lead's choice, awaiting the owner:* keep it (DECISIONS 913); no demo verdict moves with it. *Default:* keep. *If not:* revert the transition rule to the larger of the curved and the plane-earth loss and keep the corrected wording.

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

15. **Choices of review round 17 that the owner has not answered** (DECISIONS 942 to 951; each is the lead's choice, kept until the owner says otherwise).
    15a. **How does the fix table show a Stage-1 candidate's effect?** (M-1, DECISIONS 917, 942) *Default:* against the unchanged mission on the candidate's own members (the base run's first
    batch, free), with the whole run's P(fail) printed beside it. *Alternative:* run every candidate at the full 64 members, which doubles each candidate's cost and shrinks the number of
    candidates tried.
    15b. **Should a platform input the mission replaces count as used?** (M-2, DECISIONS 921, 939, 943) *Default:* no: it stays listed, marked not used, with the mission's value, and the
    demo's used count goes 274 to 258 of 289. *Alternative:* count it as used, as the page did, which tells the lab to replace a value the run does not read.
    15c. **Take the per-class sensitivity columns now?** (M-8, DECISIONS 923, 946) *Default:* yes: the demo's noise floors go to 0.177, 0.190 and 0.199 and the UAS's leader to wind_speed_bias;
    the UAS keeps `hs_scale` (round 18, M-4, rows 958, 980, 988, 989: the floors are now 0.172 for glider_eq and 0.182 for the UAS, the USV's 0.199 unchanged, and the ranked quantity is that of the dominant failure mode; see 16d). *Alternative:* defer, with a CREDIBILITY line saying the floor counts inert columns.
    15d. **A symbolic link at the emulator table's own name.** (M-13, DECISIONS 934, 947) *Default:* refuse it and keep the table's mode. *Alternative:* follow it (a link planted in a shared
    data directory would then redirect the write).
    15e. **The largest number of elements along the hull the reader accepts.** (M-14, DECISIONS 935, 948) *Default:* 500, about 7 times the converged study's 70. *If you answer:* another number is
    `fea.MAX_ELEMENTS_ALONG`.
    15f. **A finished CFD result that cannot be cached.** (M-10, DECISIONS 930, 949) *Default:* warn and return it, so the next run computes again (the runners mount `/work` read-only: set
    `CAFE_WORK` to a writable directory to keep the cache). *Alternative:* raise.
    15g. **The CFD cache key.** (M-4, DECISIONS 929, 950) *Default:* the key hashes every number and text written in `cafe/cfd.py`'s functions, so every cache file made before round 17 is
    computed once more (hours on homebase). *Alternative:* a list of named constants in `cfd.SETTINGS`, which misses the next literal added.
    15h. **`CAFE_WORKERS` and `CAFE_NPROC` with a space or sign around the digits.** (M-11, DECISIONS 931, 951) *Default:* refused with a `ConfigError` naming the variable (`CAFE_WORKERS=" 4"`
    used to be 4). *Alternative:* strip the value for `CAFE_WORKERS` only.

16. **Choices of review round 18 that the owner has not answered** (DECISIONS 977 to 990; each is the lead's choice, kept until the owner says otherwise).
    16a. **What is a Stage-1 candidate's target in the fix table measured against?** (M-1, DECISIONS 952, 977) *Default:* the verdict of the unchanged mission on the candidate's own members (free from the base run's flags, else one batch), the whole run's verdict shown beside it when it differs; emulated rows keep the whole run's. *Alternative:* the whole run's verdict, which prints 'NO-GO to MARGINAL' for a change that leaves the verdict where it was on the same members.
    16b. **How much of the CFD code is in the cache key?** (M-2, DECISIONS 960, 978) *Default:* every number with its sign and every text written in `cafe/cfd.py`'s functions; every cached CFD result made before round 18 is computed once more (hours on homebase). *Alternative:* every arithmetic operator too (`L/200` to `L*200`), at the price of a renamed cache on any such edit.
    16c. **Low antennas on an RF link** (M-3, DECISIONS 956, 957, 979; the heights and the polarisation are 12a and 12d). *Default:* the band and its direction are stated by pair (L23, PHYSICS 12.1, the card; a pair not measured is said so), the -1 stays, and two low ends on one link are accepted. *Alternative:* refuse an RF link with both ends below 0.5 m ('give a partner above 0.5 m').
    16d. **Which quantity does the sensitivity rank for a failure that is not the cross-track error or the distance from the station?** (M-4, DECISIONS 958, 980) *Default:* the quantity of the dominant mode (a USV's battery failure ranks its lowest state of charge, a glider's its battery margin), over the columns found to move it (on the demo's own environment: DECISIONS 992); an Iridium link nothing acts on is not ranked. *Alternative:* keep the ranking and print that the ranked quantity is not what failed.
    16e. **Where does `whatif` take its Stage-1 members from?** (M-5, DECISIONS 953, 981) *Default:* the run's own `plan.json`; a `--budget` that is not the run's is an error. *Alternative:* `--budget` (default `quick`), which draws other members for a run made with another budget without a word.
    16f. **Should `whatif` rerun the links of a changed vehicle?** (M-6, DECISIONS 954, 982) *Default:* no: it prints which links it did not rerun. *Alternative:* rerun them (a large change: both ends' tracks and the environment at the moved positions).
    16g. **How is the ocean store replaced?** (M-13, DECISIONS 965, 969, 983) *Default:* by renames (the old store aside, the new one in, the old one deleted); the name is absent for the time between two renames, and a kill leaves the old store whole beside the name (a whole copy on a disk that is 97 % full, deleted by the next ingest of that store and named by the refusal of a missing store). *Alternative:* delete first, as before, with a gap as long as a delete of thousands of chunk files.
    16h. **A lock file that cannot be opened.** (M-9, DECISIONS 964, 968, 984) *Default:* lock files are created `0o666` under the umask; the emulator stops with an error naming the file and its owner, the ingest runs the block unlocked and says so once. A lock made under `umask 077` is 0600 and another account cannot use it: the owner `chmod g+w`s it. *Alternative:* keep `0o644` and the silent unlocked block.
    16i. **How many hours may a UAS `--shift` be?** (M-7, DECISIONS 955, 985) *Default:* at most the window's length, as for the other vehicles. *Alternative:* no bound.
    16j. **The hull reader's grammar.** (M-10, DECISIONS 966, 987, 990) *Default:* a closed grammar over the whole of `config/assumptions.yaml` (plain one-line values, quoted text without a backslash, a one-line list of numbers; no tab, nothing deeper than a child), so a lab edit of another entry in a layout outside it is refused at the Hangar's hull case with the line named; PyYAML would read some of those layouts. *Alternative:* read the entry alone (another entry's layout is not checked).
    16k. **The USV's charge is ranked over eight columns.** (M-4, DECISIONS 958, 988) *Default:* the six forcing columns, its speed prior and `solar_yield_scale`, because the insolation it harvests varies in the environment (the analytic environment moves the charge by `solar_yield_scale` alone). *Alternative:* `solar_yield_scale` alone.
    16l. **The columns kept in the sensitivity although no probe moved them.** (M-4, DECISIONS 958, 989) *Default:* `hs_scale` on the UAS (inert for the shipped radio, whose link has 35 dB or more of margin at any range a sortie reaches) and the stress and battery scales on its profile share stay listed (the round 18 addendum's wider probe on the demo, five quantiles at eight members' other draws, did not move them either: DECISIONS 992). *Alternative:* drop `hs_scale` from the UAS rows, which lowers its noise floor a little.
