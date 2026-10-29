# CHANGELOG

## Unreleased (premission-step4)

Branch `premission-step4`, from `main`. Commits: `c184db4` throughput benchmark and planner, `2928de5` CAD uploads and fleet check, `ab376fd` quad at 2.5 ms and
TEOS-10 density, `9e0bdc7` the pre-mission pipeline, `3c75f38` orchestration tests, `bb68642` rain-lens persistence and the receipts command. Written 2026-10-29.
Choices and numbers are in `DECISIONS.md`; the equations are in `docs/PHYSICS.md`; the credibility scoring is in `docs/CREDIBILITY.md`.

### Added

Pipeline and tools

- `python -m cafe.pm` (`cafe/pm/__main__.py`) with `run`, `fetch`, `validate`, `plan`, `report` and `receipts`; `pm.sh` runs it on homebase in the `cafe-pm` image (`Dockerfile.pm`, `requirements-pm.txt`).
- `cafe/pm/pipeline.py`: ingest, hangar, stage 1, windows, stage 3, refit, stage 1b, emulator, report, each with a sha256 ledger (`ledger.py`), resume and a chained audit (`audit.py`).
- `cafe/pm/budget.py` and `config/throughput.json`: `--budget {ci,quick,4h,overnight}` sized from measured throughput, with labelled fallbacks; `bench/throughput.py` measures the OpenFOAM and JAX LBM rates and, since `3c75f38`, the stage-1 cost per vehicle class.
- `cafe/planner.py` and `config/premission.json` (`c184db4`): resolution planner, `--check` asserts the spec's air and ocean reference rows (the hull rows are shown, not asserted).
- `cafe/pm/report.py`: `report.json` as the source of truth (every number a node with stage, source, uncertainty, receipt and ledger) and an HTML rendered from it; `check_traceability` and `check_rendered` fail the stage.
- `cafe/pm/credibility.py`: the NASA-STD-7009B factor table, the ASME V&V 20 rows and the list of assumed inputs (`docs/CREDIBILITY.md`).
- `cafe/pm/receipts.py`: one table for the existing app's receipts and every pre-mission module's, with slow groups stored per code digest and `--broken` (exit code inverted).
- `Makefile` targets (`install bench fetch run quick overnight ci receipts audit acceptance broken report`), `.github/workflows/premission.yml`, `missions/ci_fixture.yaml` with a synthetic environment (`tests/fixtures/ci_env`) so `make ci` needs no network.
- `docs/BRIEF.md` (with its corrections table), `docs/BUILDERS.md`, `docs/LICENSES.md`, `QUESTIONS_FOR_LAB.md`.
- About 1,100 test functions in 39 test files under `tests/`, with vendored reference terms (`tests/fixtures/pvs`, Fossen's PythonVehicleSimulator) and recorded fixtures for orca and HYCOM.

Environment

- `env/remote.py` and `env/orca.py`: byte-range reads of the orca WRF, UMWM and restart files into Zarr, with per-hour caches, schema checks (`cafe/schemas/*.json`) and a pinned intermediate certificate.
- `env/environment.py` (`GriddedEnv`), `env/grid.py` (NaN-aware multilinear interpolation), `env/protocol.py` (the `Environment` interface and `AnalyticEnv`), `env/conventions.py` (the only place angles become vectors).
- `env/coare.py`: COARE 3.5 bulk fluxes, the stability-corrected profile and the diurnal warm layer, checked against `pycoare` 0.4.3.
- `env/surface.py`: the modelled surface layer precomputed per mission (COARE state, warm layer, time since rain, Stokes drift corrected by the real restart spectra).
- `env/waves.py`: parametric directional spectrum from UMWM's integrated parameters, restart-spectrum conversion, Stokes profile and Breivik 2016 profile, random-phase realisation with second order.
- `env/subgrid.py` and `config/subgrid.json`: Mann turbulence, gust fronts, rain lens, diurnal jet proxy, windage, Okubo/Ito ocean SDE.
- `env/hycom.py`, `env/ocean.py`: GOFS 3.1 fetch with deadlines and a part manifest, the lab HYCOM readers (netCDF and `archv .a/.b`), TEOS-10 density and sound speed, the ocean adapter.
- `env/bathy.py`: GEBCO_2026 by byte range, GOFS floor and UMWM depth in a documented fallback order.
- `env/tao.py`: TAO/TRITON download, mooring-versus-WRF comparison and the fitted wind priors.
- `env/perturb.py`: the per-member perturbed environment (wind, correlated current field, waves).

Vehicles and links

- `physics/glider.py`: Seaglider (basestation3 form) and Slocum (`gliderflight` oracle) steady flight, pilot trim, dive-averaged-current steering, energy, six failure flags.
- `physics/usv.py`: wing-sail 4-DOF steady-state VPP, strip-theory wave resistance, capsize proxy, VMG routing with tacks, five failure flags.
- `physics/uas.py`: JAX quadrotor with rotor drag, Peukert battery, ArduCopter-structured controller, ship sorties, launch gate, and an ArduCopter SITL lockstep path.
- `physics/comms.py`: two-ray RF over the sea, Thorp/Stojanovic acoustics with Bellhop for ambiguous links (`bench/install_bellhop.sh`), Iridium sessions.
- `platforms/*.yaml` for `seaglider`, `slocum`, `saildrone_explorer`, `quad_uas`, `radios`, `modems`, each leaf with a source or `assumed: true` and a why.

Statistics and verification

- `stats/intervals.py` (Wilson, Agresti-Coull, verdict, `n_certify`), `sampling.py` (Latin hypercube, antithetic pairs, common random numbers), `sequential.py` (interval stopper, SPRT), `sensitivity.py` (EASI), `rare.py` (subset simulation).
- `emulator.py`: Kriging with conformal intervals and a range guard.
- `vv.py`: Celik et al. 2008 grid convergence and the V&V 20 table; `dtmb5415.py`: the DTMB 5415 free-surface validation geometry, hydrostatics and C_T table.

Stage 3

- `stage3/lbm.py`: the D3Q19 kernel, XLB bridge and reference cases (Poiseuille, cavity, Taylor-Green, sphere), the resolution rule and the memory guard.
- `stage3/nest.py`, `wallmodel.py`, `windows.py`, `pipeline_windows.py`, `refit.py`: the wall-modelled nest, the window runner and its self-checks, the adapter that builds windows from the platform yamls, and the DerSimonian-Laird refit. `fluidx3d.py` is disabled by default.

Earlier on this branch

- Quad physics step 2.5 ms (was 10 ms) with a receipt re-checking 2.5 against 1.25 ms (`ab376fd`).
- TEOS-10 in-situ density from HYCOM T and S for glider buoyancy in the existing app, gliders ballasted neutral for launch water; `STATUS.md` and `DECISIONS.md` rows 1 to 11 (`ab376fd`).
- CAD uploads for subs and gliders (how the vehicle moves, blank mass trimmed neutral, wing span and chord) and `lab/check.py`, a one-file fleet check (`2928de5`).

### Fixed

Each entry: what was wrong; how it was found; the effect.

The existing app (`cafe/*.py`)

- `dyn.py` integrated the body rates by explicit Euler although its docstring said semi-implicit. Found by the torque-free tumble test (`tests/test_dyn.py::test_energy_and_momentum_conserved_where_explicit_euler_drifts`). Angular momentum |H| grew 1.6 % per 10 s at a 2 ms step; the Coriolis terms are now an implicit midpoint (three fixed-point iterations) with the other forces explicit, and |H| and kinetic energy are conserved to 1e-8. The Fossen-reference tests now read acceleration from a 1 microsecond step (tolerance 1e-5).
- `reach.py` let a knight step hop over a one-cell land wall. Found by the verification of the Zermelo reach. 615 cells were wrongly reachable; `_crosses_land` now blocks a step that passes over land and a diagonal that cuts a corner between two land cells.
- `cfd.py` computed the two-grid GCI with a refinement ratio of 2 whatever the meshes were. Found by the verification work on the DTMB 5415 grid pair, whose r is 1.30. The ratio is now Celik's `(N_fine/N_coarse)^(1/3)`, recorded in the result with a flag when it is below 1.3. GCI scales as 1/(r^p - 1), so r = 1.30 against 2 understates it by 1.8 times (p = 2), and more at smaller r. See Known issues for the stored values.
- The HYCOM down marker was shared between datasets, so a slow temperature and salinity read cost the next mission its currents (`ab376fd`, found while adding the temperature and salinity read); each dataset now has its own.

Ingest and data access

- `parse_cdf1` hung on a truncated header. Found by an ingest test with a truncated header. It now raises `EOFError`.
- A CDF-1 file with a single narrow record variable was read with padding the format does not apply. Found by an ingest test written first. Offsets were wrong; the record size follows the specification (no padding for a lone record variable).
- A body cut in the middle of a read was not retried, and a ranged read accepted a server that ignored `Range`. Found by `test_ranged_reads_refuse...` and an ingest test with a cut body. Reads now retry 3 times and refuse anything but HTTP 206.
- `download` looped forever on 0-byte stalls. Found by an ingest test. It now raises `ConnectionError` and keeps the `.part` for resuming.
- `orca.ingest` raised a bare `IndexError` for a window with no restart hour or with reversed dates. It now raises `ValueError` with the reason.
- XLB 0.3.1 imports `warp.utils.ScopedTimer`, removed after warp-lang 1.12, so it would not import (BRIEF correction, found while installing it). `requirements-pm.txt` pins warp-lang 1.12.1.
- GOFS requests of two or more steps were cut by NCSS with HTTP 500 after 302 s and OPeNDAP 4-step reads failed. Found by timing the live servers (`hycom.fetch_gofs` docstring). Requests are one step each, in killed child processes.
- The emulator could not write `train.parquet` because `pyarrow` was missing from the image. It now falls back to CSV, says which format it used, and `requirements-pm.txt` lists `pyarrow`.

Environment and models

- The hourly Stokes drift from the parametric spectrum had a median speed error of 38 % against the real 6-hourly restart spectra (the fit under-predicted by about 2.7 times). Found by comparing the two on the real cache (receipt `Wave direction (cache ...)`, context row: median speed of the Stokes drift from the parametric spectrum / from the real restart spectrum). `surface._correct_with_real` applies the complex real/fit ratio, interpolated in time; leave-one-out median error is now 5.1 % in speed and 3.7 deg in direction, and the field's uncertainty tag is that error.
- The rain fresh lens took its amplitude from the current rain rate, so it vanished the hour the rain ended and `since_rain_s` had no effect. Found in review: the lens persists for minutes to hours in Iyer and Drushka, and the code did not. `bb68642` stores the rate of the last rainy hour (`last_rain_mm_h`) and the lens decays with `exp(-t/tau)`; `derived.zarr` has layout version 2, ingest rebuilds an older store, and `SurfaceLayer` refuses one with the rebuild command. Test: `test_rain_lens_outlives_the_rain_and_decays_with_its_e_folding_time`.
- The USV VPP bias default (N(-0.30, 0.03)) disagreed with `config/perturbations.yaml` (uniform -0.35 to -0.30). Noted by the USV builder. Stage 1 now passes the perturbation draw; the default is used only when a caller passes none.

Stage 1 and orchestration (`3c75f38`, found by the new orchestration tests)

- A first ingest could not build `derived.zarr` because the environment opened it before it existed. Found by `test_ingest_builds_the_derived_surface_layer_when_it_is_missing`. The first run on any new mission failed.
- Resume did not cascade: stages after a rerun stage were reused with stale inputs. Found by `test_stages_after_a_rerun_stage_run_again_so_the_chain_stays_valid`. A rerun stage now forces every later stage to rerun, so the ledger chain stays valid.
- The refit divided every window by the first window's Hangar coefficient. Found by `test_the_refit_multiplier_is_the_pooled_ratio_to_each_windows_own_hangar_value`. The drag multiplier was wrong whenever windows had different speeds; each window now carries its own `cd_hangar`.
- The refit drag multiplier was a lognormal with the refit mean as its median. Found by `test_refit_drag_is_lognormal_with_its_median_at_the_refit_mean` (the name is stale; the code and the commit use the mean). The multiplier now has the refit's mean (`stage1.refit_drag`).
- Links read wind and Hs at member 0's position and ignored the member's Hs perturbation. Found by `test_rf_margin_follows_the_members_significant_wave_height` and `test_acoustic_noise_is_read_at_each_members_own_position`. Every member's RF margin and acoustic noise are now evaluated at its own position and perturbed Hs.
- Modem bands named in `modems.yaml` (for example `whoi_micromodem_long_10k`) could not be chosen by a link. Found by `test_a_modem_band_named_in_modems_yaml_can_be_chosen_by_a_link`.
- The TAO comparison crashed when no mooring lay in the grid. Found by `test_moorings_outside_the_grid_fail_the_stage_through_its_self_check`. It now fails its own self-check with a message.
- The windows stage crashed on a vehicle with no finite position. Found by `test_a_vehicle_with_no_finite_position_fails_the_window_check`.
- The fewest-Mann-boxes search doubled the count instead of finding the smallest that fits. Found by `test_fewest_boxes_is_the_smallest_box_count_that_fits`. It wasted boxes at about 2 s each.
- The hangar counted a header comment as an assumed value. Found by `test_hangar_lists_every_platform_file_with_its_number_of_assumed_values`.
- The LBM benchmark kernel's roll shifts were `jnp` under `jit` and never ran (`c184db4`); they are NumPy now and the earlier "measured" LBM rate was not a measurement.

Stage 3

- The first flat-plate wall-model receipt compared a laminar CI-size plate with the turbulent ITTC-57 correlation and read 71 % low. Found by the receipt itself; it was ill-posed. The wall model is now checked in a body-force channel (wall stress = g h exactly; C_f against Dean 1978) and, at Re_L of at least 1e6, on a flat plate (stored 1.8 h run).
- Stage-3 sphere and flat-plate receipts were context rows and could not fail. Found by the receipts builder (a context row never fails). `bb68642` makes them required pass/fail rows at 10 %; a missing or stale stored run is a FAIL row naming the command, and a stored FAIL stays a FAIL.
- The ground-frame nest produced a spurious force of about -2 times the drag, because each whole-cell shift displaces fluid without pushing it. Found by a window with a moving body at one shift per 25 steps. Windows now run in the vehicle frame by default.
- A coarse-grid window went NaN (lattice viscosity 3e-6 in float32 BGK). Found by the CI quad window. The viscosity is floored at 1e-4 and a window that needed the floor is reported failed with the reason.

### Known issues

Each was checked against the code on 2026-10-29 (`bb68642`) before it was listed.

- **Stage-3 wall model and sphere drag.** The wall model is validated only in a body-force channel at CI size (C_f 0.00513 against Dean's 0.00518); the flat plate against ITTC-57 at Re_L of at least 1e6 needs a stored 1.8 h run and is a FAIL row until one is stored. The XLB staircase sphere overpredicts Cd by 30 % (Re = 100, d = 8), 59 % (Re = 1000, d = 10) and 73 % (Re = 1e4, d = 12) and fails its 10 % rows; the native curved-wall kernel passes at Re = 100 only after Richardson extrapolation from d = 8 and 12 (-2.2 %, finest grid +16 %), and Re = 1e3 and 1e4 need d of at least 24 and 40, which a CPU cannot afford. A window's wall-model check takes the better of the two stored errors, so the channel alone lets windows through. Until the slow cases run, Stage-3 coefficients rest on a wall model validated in a channel only, and the refit uses a coefficient only when its window passed all its self-checks. Credibility limitations L08 and L09.
- **SITL return and landing.** ArduCopter's EKF drifts on the return: touchdown lands 4 m to 160 m from the ship in 4 trials; its tilt estimate differs from the attitude sent (context rows in `UAS SITL vs our controller`). Only "SITL completes the descent" and the leg-end hold are pass/fail. `WP_YAW_BEHAVIOR = 0` avoids a GPS/compass glitch flag; the equator-compass problem is worked around by telling the firmware it is at Canberra. Limitation L10.
- **UAS propulsion curve.** `T = kT w^2`, `P = kQ w^3` from an assumed figure of merit (0.60), an assumed `omega_max` (30 000 rpm) and efficiency (0.80), with no dyno curve and no loss of thrust with forward speed; the 60 Wh battery is assumed and cannot be carried by the 0.772 kg airframe. The rotor drag is Faessler's from a different airframe, used to 12 m/s. Limitation L11.
- **Stored receipt GCIs on homebase were computed with r = 2.** The fix is in `cafe/cfd.py` (`ratio_from_cells`, since `9e0bdc7`), so any result stored by earlier code still carries r = 2 and understates the GCI by 1.8 times at r = 1.30. They remain until the hangar CFD and the DTMB 5415 runs are redone; the stored files are on homebase and were not opened for this entry (read-only task). Limitation L12.
- **Stage-1 per-batch draws.** The UAS Mann turbulence (`uas/turb/<sortie>`), the gust-front events (`uas/gust`) and the Iridium sessions (`iridium/<link>`) are seeded by the mission seed and the **first member of the batch**, not by member; each batch is also its own Latin hypercube. So member m's turbulence, gusts and Iridium draws depend on the batch size, which depends on the budget: two budgets do not reproduce each other's UAS and Iridium results member for member, and members of one batch share one event set. The current error fields and the refit drag are keyed by member and do not have the problem. A test (`test_mann_turbulence_and_gust_fronts_are_per_member_deterministic_and_seeded_by_the_first_member`) holds the present behaviour.

Also found while writing the docs; each is in the code now:

- The acoustic 4 km mid-frequency range is true by construction, the USV 12 m/s point is a fit, the Sun et al. magnitude is 8 to 26 % against the published 30 to 35 %, the Cd receipt is a closure, several citations were recalled and not re-read, the glider T(z) is assumed, and the turbulence sigma_v/sigma_u and sigma_w/sigma_u are low (0.63 and 0.43 against 0.8 and 0.5). Limitations L01 to L07.
- Not called by any pipeline stage although implemented and receipted: the SPRT, subset simulation, the Okubo/Ito ocean SDE, `subgrid.windage`, `subgrid.diurnal_jet`, `waves.Realization`, `stokes_breivik2016`, `encounter_spectrum`, `Emulator.flip_search` and `next_candidate`. The mission switches `warm_layer`, `rain_lens` and `ocean_sde` are validated and not read. `bulk_stress_scale` in `perturbations.yaml` is applied by nothing.
- The gust-front rate omits the theta_e factor in the pipeline (f = 1), so it is the rain-only upper rate; one event set per window is applied at every point.
- `wind_sea_age = 2.0` and `swell_age = 1.2` are assumed code defaults in `waves.py`, not keys in `config/assumptions.yaml`, so the credibility report does not list them.
- Only the two wind priors are fitted from TAO; the SST residual (-0.11 K, rmse 0.26 K) is recorded and not used, and `assumptions.yaml` says the TAO comparison overwrites `env.sigma.t2_k`, which the code does not do. TAO has no wave variable, so UMWM `swh` is not validated against buoys.
- GOFS, TAO and GEBCO are fetched by library calls; `python -m cafe.pm fetch` and `make fetch` do not download the ocean or TAO data.
- `credibility._stored_rows` looks for `nest_sphere_<Re>.json`; `stage3.nest` writes `nest_sphere_<Re>_d<d>.json`, so the native-sphere V&V 20 rows always read "not run".
- 3-D WRF winds are used without the COSALPHA rotation (the identity on this grid).
- `lost_link` is never set in Stage 1 (no link callback is passed); the RF link is judged separately.
- The emulator receipts are scored on a synthetic table; the real-spectrum correction uses a median error as a 1-sigma.
- The DTMB 5415 coarse and fine runs were in progress in tmux `dtmb5415` on homebase (expected 13:30 to 16:00 UTC, 2026-10-29); until they finish, its V&V 20 rows read "not run".
- No GPU exists (Azure quota 0), so every GPU figure is a labelled projection and the lab's server has not been used.

Checked and not listed: the rain-lens persistence. It was listed as open in the brief of this entry; `bb68642` models it (see Fixed). What remains is that the decay uses the instantaneous wind, not its history, and that the trigger, saturation, e-folding times and the lens temperature are assumed.
