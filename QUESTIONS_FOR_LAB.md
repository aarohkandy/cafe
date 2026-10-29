# Questions for the lab

Nothing here blocks a run: every item already has a working default in the code, and every answer is a config
change, not a code change. Each says what we do now and what changes if your answer differs.

1. **HYCOM for `run_2023mar_waves_v4`.** Is there a HYCOM run (or a coupled companion) for this case, and is it
   `archv.*.a/.b` or per-snapshot netCDF? Does it write in-situ or potential temperature?
   *Default:* HYCOM GOFS 3.1 GLBy0.08 expt_93.0 (in-situ T, 3-hourly, 40 z-levels). *If yes:*
   `cafe ingest --ocean lab_hycom --path <dir> --temperature-kind <in_situ|potential>`, then set
   `environment.ocean: {source: lab_hycom, path: ...}` in the mission. The reader is already round-trip tested on
   synthetic `.a/.b` and netCDF files built from GOFS values. Currents then come from the same model as the waves'
   forcing, and the current prior (±30 %) can be narrowed.

2. **Hourly wave spectra and Stokes drift.** The 6-hourly `restart/umwmrst_*.nc` spectra on orca are used (every
   6 h, every 3rd sea point). Could UMWM be re-output with `outspec > 0` at the mission waypoints and
   `stokes = .t.`? *Default:* real spectra at 00/06/12/18 Z, a DHH/JONSWAP spectrum fitted to `swh dwp dwd mwp mwd
   mss` in between, Stokes drift integrated from that spectrum. *If yes:* hourly spectra replace the fit and the
   Stokes term becomes data instead of modelled (report badge changes from MODELLED to DATA).

3. **`SST_UPDATE = 0`.** Was the frozen 1 March SST intentional? Is there a run with `sf_ocean_physics` or coupled
   SST? *Default:* frozen WRF SST + the COARE warm-layer model, enabled and badged MODELLED; the TAO comparison
   quantifies the frozen-SST error. *If a coupled run exists:* point `environment.atmosphere.path` at it; the warm
   layer stays on only if its SST has no diurnal cycle.

4. **Which platforms TEPEX-C will fly** (Saildrone Explorer vs Voyager; Seaglider vs Slocum; which UAS), with mass,
   CG, geometry or CAD, propulsion and battery curves, speed polars or flight-model coefficients, comms hardware and
   antenna heights. *Default:* `platforms/seaglider.yaml`, `slocum.yaml`, `saildrone_explorer.yaml`,
   `quad_uas.yaml`, each number cited or marked `assumed`. *If supplied:* edit those files (or add new ones) and
   check each with `python -m cafe.pm hangar --platform <name>`, which lists every value still marked assumed.
   Verdicts then describe your vehicles instead of the class defaults.

5. **Mission definition.** Deployment windows, waypoints, station-keeping tolerance, surfacing schedule, which
   link pairs must hold and what outage is acceptable, and the go/no-go thresholds the PIs actually use.
   *Default:* `missions/tepex_c_demo.yaml` (brief section 6; GO at P(success) >= 0.9, NO-GO below 0.6).
   *If different:* edit the mission file; `python -m cafe.pm validate --mission <file>` checks it before a run.

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
   interFoam on CPU. *If yes:* set `stage3.fluidx3d: true` in `config/premission.json` after reading
   `docs/LICENSES.md`.

9. **Campaign date, box and file layout.** Confirm spring 2028, 160°E–160°W, 5°S–5°N, and whether a 2028-season
   forecast run (not the 2023 hindcast) will be produced before deployment. *Default:* 2023 hindcast layout
   (`cafe/schemas/wrfout.json`, `umwmout.json`, `umwmrst.json`); ingest refuses any file that does not match.
   *If the layout changes:* regenerate the schemas from one new file and re-point `CAFE_ORCA`.

10. **Forecast mode.** Will UWIN-CM run in forecast mode during the campaign, and at what latency?
    *Default:* offline hindcast. *If yes:* the same `run_premission` runs daily against the newest files; the
    ingest is already resumable and bounding-box only.

11. **The orca run is still growing.** `run_2023mar_waves_v4` has 2023-03-01 00Z to 03-07 18Z today (it is under
    `temp/`). Will it reach 12 March? *Default:* the demo window is 03-01 12Z to 03-07 12Z. *If it grows:* widen
    `window` in the mission file; nothing else changes.

12. **Glider-to-ship acoustic geometry in the demo.** The brief puts the gliders at 170°W and the ship at 165°W
    (about 550 km apart) and requires a glider↔ship acoustic link at every surfacing; an ATM-960 MF modem reaches
    ~4 km, so the demo run reports that link NO-GO in every member. Is there a second ship, a relay (the USV with a
    modem), or is the glider data meant to go over Iridium? *Default:* the mission is run exactly as written and the
    report says why the link fails (range, not environment). *If a relay or a different ship position:* add it to
    `missions/tepex_c_demo.yaml` (a `ship` or a link with `a: glider_eq, b: usv`); nothing else changes.
