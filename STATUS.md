# STATUS — the TEPEX-C pre-mission simulator (`cafe.pm`)

Rewritten from the code on 2026-10-31 (review round 2, M-14), at `8ee5f50` plus the round-2 fixes, and updated for review rounds 3 (DECISIONS 210 to 236) and 4 (DECISIONS 237 to 263). The earlier version of this file was the audit of the existing app against the
spec of 2026-10-28 (`ab376fd`); it is in git history and no longer describes the repository.

## 0. What is physically missing (BRIEF section 0)

Every exit condition of the brief that is unmet is unmet for one of these inputs, none of which exists on this side. For each: the code path exists and is exercised by a
test or the synthetic CI environment, the one command that completes it, and what you get meanwhile. Each row was checked against `QUESTIONS_FOR_LAB.md` and the code.

| Missing input | Command once it exists | What you get meanwhile |
|---|---|---|
| **A GPU.** The Azure subscription has GPU quota 0 for every VM family in every region; a quota request is the first step. | `bin/run_premission --mission missions/tepex_c_demo.yaml --budget 4h --gpus 1 --out runs/4h`; `python bench/throughput.py lbm gpu` to measure the card; `make acceptance GPUS=1` adds the 4 h run. | `--gpus 0`: Stage 1 and the free-surface hull window run on CPU (the glider hull's FEA belongs to its LES window and runs only when that window does). **No LES coefficients exist on this machine; sub-grid and refit stay uncalibrated:** every LES window would need about 1e13 to 1e14 cell-updates to reach the lattice viscosity floor against about 2e8 in its share of `quick` (M-8), so the plan marks it "not run" with that reason and gives the time back to Stage 1 (`--budget ci` keeps one smoke window so the code is exercised). Any GPU figure in a plan is a projection from published benchmarks and is labelled one: `plan --gpus N` on a machine with no visible GPU begins "no GPU found on this machine", and `run --gpus N` is refused there (exit 2) unless `--assume-gpu` is given (M-19). |
| **The lab's HYCOM run** for `run_2023mar_waves_v4` (QUESTIONS 1), netCDF or `archv.*.a/.b`. | Set `environment.ocean: {source: lab_hycom, path: /data/ocean/lab_tepex_c_demo.zarr}` in the mission, then `python -m cafe.pm ingest-ocean --mission missions/tepex_c_demo.yaml --path <dir> --temperature-kind <in_situ\|potential>` (`--grid <stem>` for archv). | HYCOM GOFS 3.1 GLBy0.08 (in-situ T, 3-hourly, 40 z-levels). The lab reader is tested on synthetic `.a/.b` and netCDF files built from GOFS values, never on a real lab file. |
| **The lab server** (QUESTIONS 6). | `make install bench acceptance GPUS=1` on it; the planner re-sizes every stage from that machine's measured rates. | `homebase`: 8 vCPU, no GPU, run as `./pm.sh <command>`. |
| **Platform datasheets** for the vehicles TEPEX-C will fly (QUESTIONS 4): mass, CG, geometry or CAD, propulsion and battery curves, polars, comms hardware. | Edit `platforms/*.yaml`; `python -m cafe.pm hangar --platform <name>` lists every value still marked assumed. | Class defaults (`seaglider`, `slocum`, `saildrone_explorer`, `quad_uas`, `radios`, `modems`), each number cited or marked `assumed: true` with its reason; the report badges a verdict that depends on one. |
| **A frame-only drag for the UAS** (QUESTIONS 13, "Q13"): the Hangar `d_x` includes the rotor momentum drag, so a frame-only LES cannot be compared with it. | The number, **and a small code change**: no code reads such a key yet (`stage3/pipeline_windows.py` fixes `comparable=False` for the UAS window). Then `pm bin/run_premission ...` with a GPU. | UAS windows are never used in the refit. On CPU the UAS window is not run at all (it also diverged in the q2 run, M-26). |
| **The intended ship and glider positions** (QUESTIONS 12): the brief puts the gliders 555 and 598 km from a ship that needs an acoustic link with a 4 km modem, and the USV up to 111 km from a ship whose radio horizon with the UAS is 24 to 49 km. | Edit `missions/tepex_c_demo.yaml` (a ship, a relay, an Iridium route); `python -m cafe.pm validate --mission <file>`. | The mission as written: the two acoustic links are NO-GO in every member by range, and the report says so (a geometry result, not an environment one). |
| **Hourly UMWM spectra and Stokes drift** (QUESTIONS 2): a UMWM re-output with `outspec > 0` and `stokes = .t.`. | Lay the files out like orca's and point `CAFE_ORCA` at them. | The 6-hourly restart spectra on orca plus a spectrum fitted to the integrated parameters in between; Stokes drift is modelled and badged MODELLED. |
| **A coupled-SST WRF run** (QUESTIONS 3): the orca run froze SST (`SST_UPDATE = 0`). | Lay the files out like orca's WRF files and point `CAFE_ORCA` at them. | Frozen SST plus the COARE warm-layer model, badged MODELLED; the TAO comparison quantifies the frozen-SST error. |
| **Second validation truth** (QUESTIONS 7): Saildrone 2023 wind, SST, waves, SOG. | `cafe.pm.env.tao.compare` takes any time series, but it is a library call; no command reads another data set yet. | TAO/TRITON only. |
| **Campaign layout and forecast mode** (QUESTIONS 9, 10, 11): 2028 files, UWIN-CM in forecast mode, the orca run growing past 7 March. | Re-point `CAFE_ORCA`, regenerate `cafe/schemas/*.json` from one new file (ingest refuses any file that does not match them); widen `window` in the mission as hours appear. | The 2023 hindcast: 2023-03-01 00Z to 03-07 18Z, demo window 03-01 12Z to 03-07 12Z. |

Decisions, not inputs: the go/no-go thresholds the PIs use (QUESTIONS 5, the mission's `verdict` block), what a drift glider must do and how long a calm may last before a USV counts as failed (QUESTIONS 5, round 3) and the FluidX3D licence (QUESTIONS 8, `"fluidx3d": {"enabled": true, "binary": ...}`
in `config/premission.json`; shipped disabled). Each has a working default.

## 1. What runs

`bin/run_premission` is `python -m cafe.pm run`. One command takes the two orca files plus the ocean source to `report/index.html`, `report.json` and `credibility.html`, with a sha256
ledger per stage, resume, and a chained audit. The q2 quick run of 2026-10-31 on homebase did it end to end; the eight compute stages took 691.9 s and its cold ingest 522 s (a warm ingest takes about 6 s, so a warm quick
run is about 700 s of the 1200 s limit; the planner's stage-1 estimate is 2.5 times high until `make bench` is rerun on an idle box).

| Stage | What it does | State |
|---|---|---|
| ingest | byte-range reads of orca WRF, UMWM and restart spectra, GOFS 3.1, TAO/TRITON, GEBCO into Zarr, schema-checked | runs; offline once cached (`CAFE_OFFLINE=1`) |
| hangar | provenance check of the platform files, baseline model coefficients (no Hangar CFD run) | runs |
| stage 1 | ensemble (Latin hypercube, 16 to 512 members by budget) of glider, USV, UAS and the RF, acoustic and Iridium links; Wilson intervals; sequential stopper; failure modes; sensitivities | runs |
| windows, stage 3 | LES windows (native JAX lattice kernel), FEA of the glider hull, free-surface hull window (OpenFOAM interFoam) | LES windows are not run with `--gpus 0` (above; `ci` keeps one smoke window); the free-surface hull window runs where it fits; no GPU path has ever run |
| refit | pools passed windows into drag multipliers | never fires on CPU (no window passes); a single pass, not the loop of BRIEF 2.6 |
| stage 1b | stage 1 rerun with refitted multipliers (or with the run's own sub-grid calibration), else a copy; USV brief-prior sensitivity case | runs |
| emulator | Kriging per vehicle class, flip search of single changes | trains only with 100 distinct points per class, which one run does not make; the flip search falls back to Stage 1 |
| report | `report.json` as the source of truth, HTML from it, credibility report (NASA-STD-7009B, ASME V&V 20, assumed inputs), reach map | runs |

Commands (`python -m cafe.pm ...`): `run`, `fetch`, `ingest-ocean`, `validate`, `plan`, `whatif`, `hangar`, `audit`, `report`, `receipts`, `acceptance`, `promote-calibration` (copies a run's `stage3/subgrid_calibration.json` into the tracked `config/subgrid.json`; a run never writes that file itself, M-23).

Make targets (each runs where it is invoked; from a laptop prefix `./pm.sh`):

| Target | What it does |
|---|---|
| `make install` | builds the `cafe` and `cafe-pm` images |
| `make bench` | measures this machine and writes `config/throughput.json` (OpenFOAM and LBM rates, stage-1 cost per vehicle class); the planner reads it |
| `make fetch` | the mission's data, resumable and hash-checked |
| `make ci` | every stage at toy resolution on CPU from the synthetic environment (`tests/fixtures/ci_env`), no network, under 10 min; ends with `python -m cafe.pm.audit --ledgers-only runs/ci`, a re-hash of the ledgers of the run it made (M-24) |
| `make quick`, `make overnight` | the demo mission at `--budget quick` (20 min) or `overnight` (10 h), `GPUS` from the environment, into `runs/` |
| `make receipts` | every receipt (app and pre-mission) as one table; exits non-zero on any failure, which is expected until the open limitations L08 and L09 are retired |
| `make broken` | the deliberately broken wave-direction configuration must fail a receipt that passes without it (exit 0 means one did; the fast receipts run twice, DECISIONS 240) |
| `make mutation` | mutmut on `cafe/pm/physics` and `cafe/pm/stats`, writes `docs/mutation.json`; hours |
| `make audit` | ledgers of `runs/quick`, `runs/overnight` and `runs/4h` (those that exist) re-hashed, banned tokens (incl. `skip(` and `cafe/static/app.js`), ruff, mypy strict, pytest with coverage gates (100 % on physics, stats and env; 90 % on `cafe/pm`), and the stored mutation result (refused if missing, stale or under 85 %) |
| `make acceptance` | BRIEF 5.3: quick and overnight (and 4h with `GPUS=1`), golden diff, same-seed and other-seed reproducibility, the broken configuration; about 11 h |
| `make report` | re-renders a finished run's report |

Tests: <TESTS> (round-4 tree; the lead's full run on homebase fills this in). The round-3 tree had 1,822 `def test_` in 49 files and 2,122 collected cases, all passing (homebase, 2026-11-01). Coverage: 99.96 % of 12,214 statements in `cafe/pm` (five error-branch lines missed: `pipeline.py:1075-1076`, `report.py:408-409, 913`), 100 % in `physics`, `stats`, `env` and `stage3`; ruff and mypy --strict clean. Credibility of the last q2 report: see its `credibility.json`; the limitations that cap it are in `docs/CREDIBILITY.md` section 5.

DTMB 5415 v4 study (recipe `pout-lts01-parts-v4`, three grids at Fr 0.10, 0.20, 0.28, 0.41): done and installed in `/data/dtmb5415`; |E| <= U_val at all four (E x1e3 = +0.865, +0.722, +0.842, -0.040 against U_val x1e3 = 1.882, 1.085, 2.653, 1.993), but U_val / D is 0.27 to 0.63 against 0.1, so it validates little, and iterative convergence fails at Fr 0.28 and 0.41 on every grid (drift 0.03 to 0.07 against 0.005).

## 2. Pending at code freeze (pending, not done)

The round-3 tree passed the full test suite, ruff and mypy --strict (2026-11-01); the round-4 tree's full run is the lead's and is not recorded here yet. A later review round may change code again, so the steps below have not been run on the final tree. Each is a step for an idle box after the last code change.

- **`make bench`** on an idle box: `config/throughput.json` was measured at load 32.9 on `ci_fixture` and is stale (the plan notes say so).
- **`make mutation`:** `docs/mutation.json` does not exist, so `make audit` fails its mutation step until it is made (gate 85 %).
- **The golden:** `tests/golden/tepex_c_demo_quick.json` records no commit sha, clean-tree flag or code digest, so `golden_diff` fails. Mint it from a reviewed quick run on a clean, committed checkout, through the RUNBOOK 1 wrapper, which passes `CAFE_GIT_SHA` and `CAFE_GIT_DIRTY` (the image has no `git`; DECISIONS 260) (`--update-golden`, then rerun without).
- **Final `make acceptance`** (about 11 h) and **`make receipts --slow`** (about 4 h) on the frozen code.
- **The blind RUNBOOK test (BRIEF exit condition 5):** a fresh agent follows `docs/RUNBOOK.md` on a clean checkout and reports every place it got stuck. Not yet done; no record of one exists.
- **Review:** round 1 (33 findings, fixed in `8ee5f50`), round 2 (36 findings, each fixed with a regression test, DECISIONS 182 to 207) and round 3 (28 findings, 0 critical, 4 major, 24 minor, fixed with DECISIONS 210 to 236; the q3-run fixes 208 and 209 came before it). BRIEF 5.6 needs two consecutive rounds with zero findings from reviewers who did not write the code, so it is open. **Round 4** (26 findings, 0 critical, 5 major, 21 minor, DECISIONS 237 to 263; `review/round_4/merged.md`) is fixed in the working tree, each with a regression test that failed on the old code, and not committed; a round 5 is next. The majors: the UAS return-to-ship timer cut the flux profile invisibly (M-1), `derived.zarr` was outside every hash (M-2), the emulator coverage gate scored exact 0 and 1 as misses (M-3), `make broken` could pass for the wrong reason (M-4), and a NaN current crashed the USV step (M-5). **What changed in the demo's verdicts is not yet known**: the q5 re-run on the round-4 tree measures it. The UAS verdict will probably move to NO-GO (M-1: at 5.3 m/s, the demo's median 10 m wind, the 20 min pattern ends at 7 of 8 waypoints, and `sortie.min_profile_fraction` is 1.0), every current-driven number moves by about 2 % (M-6), the rain-driven numbers move (M-16), and every stored resume and the derived surface layer are rebuilt. Two decisions wait for the lab: the shortest acceptable UAS profile and the radio failsafe timeout (QUESTIONS_FOR_LAB 4 and 5). Two inputs are new and assumed (`sortie.min_profile_fraction`, `radio.link_loss_hold_s`: 263 assumed inputs now).

## 3. Not done and not planned in this build

- **The web UI and the static demo do not read `report.json`** (BRIEF 2.9; DECISIONS 206). A reader was not built.
- No GPU run, no lab-server run, no run on a lab HYCOM file (section 0).
- The 20-minute and 10-hour contracts hold for compute with a warm cache; a cold fetch is a separate step (DECISIONS 196).
- `docs/USE_HISTORY.md` and `docs/QUALIFICATIONS.md` do not exist, so those two credibility factors read 0.

## 4. The existing app (`cafe/*.py`)

Unchanged by the pre-mission work apart from the CAD uploads and `lab/check.py` (`2928de5`) and the quad step and TEOS-10 density (`ab376fd`). The pipeline imports `cafe.cfd`, `cafe.fea`,
`cafe.emulator`, `cafe.reach` and `cafe.receipts` from it. DECISIONS rows 1 to 11 keep the old choices over the spec.
