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

2. **Hourly wave spectra and Stokes drift.** The 6-hourly `restart/umwmrst_*.nc` spectra on orca are used (every
   6 h, every 3rd sea point). Could UMWM be re-output with `outspec > 0` at the mission waypoints and
   `stokes = .t.`? *Default:* real spectra at 00/06/12/18 Z, a DHH/JONSWAP spectrum fitted to `swh dwp dwd mwp mwd
   mss` in between, Stokes drift integrated from that spectrum. *If yes:* hourly spectra replace the fit and the
   Stokes term becomes data instead of modelled (report badge changes from MODELLED to DATA).

3. **`SST_UPDATE = 0`.** Was the frozen 1 March SST intentional? Is there a run with `sf_ocean_physics` or coupled
   SST? *Default:* frozen WRF SST + the COARE warm-layer model, enabled and badged MODELLED; the TAO comparison
   quantifies the frozen-SST error. *If a coupled run exists:* lay its files out like orca's WRF files and re-point `CAFE_ORCA` at them (the mission file has no atmosphere
   path and no source other than `orca_uwincm`; `validate` refuses `local_wrf` and `path` and names this route); the warm layer stays on only
   if its SST has no diurnal cycle.

4. **Which platforms TEPEX-C will fly** (Saildrone Explorer vs Voyager; Seaglider vs Slocum; which UAS), with mass,
   CG, geometry or CAD, propulsion and battery curves, speed polars or flight-model coefficients, comms hardware and
   antenna heights. *Default:* `platforms/seaglider.yaml`, `slocum.yaml`, `saildrone_explorer.yaml`,
   `quad_uas.yaml`, each number cited or marked `assumed`. *If supplied:* edit those files (or add new ones) and
   check each with `python -m cafe.pm hangar --platform <name>`, which lists every value still marked assumed.
   Verdicts then describe your vehicles instead of the class defaults.
   Two numbers of the Saildrone file are asked for by name (review round 3, M-8): is there a minimum apparent wind angle below which the vehicle cannot hold a tack, and what is it?
   *Default:* `min_awa_deg` = 15 deg, assumed with no source (the polar still gives positive speed inside it). *If supplied:* edit `params.min_awa_deg` in `platforms/saildrone_explorer.yaml`.

5. **Mission definition.** Deployment windows, waypoints, station-keeping tolerance, surfacing schedule, which
   link pairs must hold and what outage is acceptable, and the go/no-go thresholds the PIs actually use.
   *Default:* `missions/tepex_c_demo.yaml` (brief section 6; GO at P(success) >= 0.9, NO-GO below 0.6).
   *If different:* edit the mission file: `verdict: {go: ..., nogo: ...}` is read by the verdict, the stopping rule and the what-if
   search, and `validate` refuses values outside 0 < nogo < go <= 1 (GO also needs the Wilson lower bound on success >= min(0.75, go)); `python -m cafe.pm validate --mission <file>` checks it before a run.
   Two parts of the mission definition are open (review round 3). (a) What does a drift glider have to do (heading, and what is its pass/fail criterion)? *Default:* it swims on the fixed
   `task.heading_to` written in the mission (the demo writes 0.0, due north) and can only fail by battery, depth or the seafloor, so its GO carries no mission criterion and the report says so.
   *If you give one:* use `mode: station` or `section` where the glider has a station or waypoints, or set `heading_to` to the intended heading; a success criterion for a drift glider needs a code change.
   (b) How long may a calm last before it counts as a USV failure? *Default:* `wing_stall_calm` after 30 min of apparent wind below 1.5 m/s (`calm_sustain_s` 1800 s) and `becalmed` after 6 h of being unable to stem
   the current (`becalmed_after_h` 6 h), both assumed and different on purpose. *If your threshold differs:* edit those two `mission_defaults` in `platforms/saildrone_explorer.yaml` (the first is the platform's, the second can also be set in the mission's `task`).

6. **The lab server.** GPU model(s) and VRAM, CPU cores, RAM, disk, OS, who administers it, and whether there is a
   user account with Docker. *Default:* designed for one 32–96 GB NVIDIA GPU + 32–64 cores; everything also runs
   CPU-only (as on `az_serv` today, with LES windows labelled CPU-fallback). *When it exists:* `make install bench
   acceptance GPUS=1` there; the planner re-sizes every stage from that machine's measured throughput.

7. **Validation truth.** Is TAO/TRITON for March 2023 acceptable as the wind/SST truth, and is there in-situ wave or
   current data from the 2023 TPOS Saildrone mission we can use? *Default:* TAO only; the wind prior in the
   ensemble is replaced by the fitted TAO error. *If Saildrone data is shared:* it becomes a second validation set
   for wind, SST, waves and the USV speed model (`cafe.pm.env.tao.compare` takes any time series).

8. **FluidX3D licence.** Is FluidX3D's licence (no commercial or military use; modifications must be published)
   acceptable for NOAA use? *Default:* the FluidX3D backend exists but ships disabled; free-surface windows use
   interFoam on CPU. *If yes:* after reading `docs/LICENSES.md`, build FluidX3D and set
   `"fluidx3d": {"enabled": true, "binary": "/path/to/FluidX3D"}` in `config/premission.json`.

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

13. **The UAS frame-only drag.** The Hangar `d_x` for the quadrotor includes the rotor momentum drag, so a stage-3 LES of the frame alone cannot be
    compared with it like for like. Can you split `d_x` into its frame and rotor parts, or give the frame's Cd*A?
    *Default:* UAS stage-3 windows are never used in the refit (on a CPU machine they are not run at all, see `STATUS.md`). *If supplied:* no code reads such
    a key yet (`cafe/pm/stage3/pipeline_windows.py` sets `comparable=False` for the UAS window), so the answer needs a small code change: read the frame-only
    reference from `platforms/quad_uas.yaml` and set `comparable` from it. The UAS windows then become usable for the refit once a window passes its checks.

14. **Does Chiodi et al.'s 0.178 include currents?** The Saildrone speed prior is calibrated to the mean speed over ground / mean wind of Chiodi et al.
    (0.96 m/s over 5.4 m/s). That ratio was observed in real ocean currents, while the calibration scenario of the tool has none. In the demo mission the
    ensemble's ratio is 0.120 (0.125 at the anemometer height), and the westward current alone lowers it from 0.186 to 0.150 by turning a beam reach into a
    close-hauled course. If the 0.178 already contains the effect of currents, the tool penalises the current twice. Which is it, and if you have the
    underlying Saildrone tracks, what was the current along them?
    *Default:* assume the 0.178 does not include currents; the prior stays as calibrated, the report prints the mission ratio beside it, and
    `docs/CREDIBILITY.md` lists the question as L18. *If it does include currents:* `vpp_bias_mean` in `platforms/saildrone_explorer.yaml` has to be
    recalibrated with the same current in the calibration scenario (a code change, since `usv.mean_sog` has no current), which makes the USV faster in the mission.
