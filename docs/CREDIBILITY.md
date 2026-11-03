# CREDIBILITY — how the credibility report is scored

What `cafe/pm/credibility.py` computes, what evidence each level needs, and what the tool cannot show. Written against `bb68642` on 2026-10-29; section 3 (`RULES`, `LEVELS`), the limitation table (`LIMITATIONS`) and sections 5 and 6 were checked against `credibility.py`, `wallmodel.py`, `subgrid.py`, `stage1.py` and the platform files on 2026-10-31 (review round 1, M-17). Section 4 (the ASME rows) was not rechecked except where review round 2 changed it (M-3, marked there). Review round 2 (M-35, 2026-10-31) added the thirteenth limitation to section 5 and the new ones, L14 to L18 (L18 at integration, from batch B's M-2 diagnosis), and rechecked the counts against `credibility.json` of the q2 run. If this file and
`credibility.py` disagree, the code is right; `LIMITATIONS`, `FACTORS`, `RULES` and `LEVELS` below are copied from it and must be kept the same.

## 1. What it is

The report stage (`pipeline.s_report`, `report.write`) writes `run_dir/report/credibility.html` and `credibility.json` next to the mission report. They hold four things:

| Part | Content |
|---|---|
| NASA-STD-7009B factor table | nine factors, a level 0 to 4 each, the rule that gave it, the evidence (with the file), what is missing |
| ASME V&V 20 table | one row per comparison with a reference: `E = S - D`, the three uncertainty terms, `U_val`, `\|E\| <= U_val` |
| Known limitations | `LIMITATIONS` (L01 to L12 and, from round 2, L14 to L20) plus L13, the sub-grid reason the run adds when the layer is uncalibrated; each caps the factors it bears on |
| Assumed inputs | every `config/assumptions.yaml` key, every perturbation prior, every platform leaf marked `assumed: true` |

`credibility.build(run_dir)` returns the dict; `write(run_dir)` renders it. Every level is computed from files that exist: the run directory (ledgers, summaries, plan,
`mission.yaml`) and the repository (`platforms/`, `config/`, `tests/`, `docs/`, `pyproject.toml`) and, for the V&V rows, `$CAFE_DATA` (`dtmb5415/`, `receipts/`).
Where evidence is missing the level is 0 and the cell says what is missing.

Two statements the report prints about itself, and which hold:

- **The 0 to 4 scale is the brief's (BRIEF 5.4); the rule behind each level is this tool's own reading of the factor.** NASA-STD-7009B was not re-read. The rule is printed next to every level.
- **Level 4 is never awarded.** It needs independent review or field evidence, which no file in this tool can show.

## 2. The scale and the cap

| Level | Meaning (`LEVELS`) |
|---|---|
| 0 | none: no evidence |
| 1 | weak: evidence exists, nothing checked it |
| 2 | moderate: checked by this tool's own self-checks |
| 3 | strong: checked against an independent reference |
| 4 | very strong: independent review or field evidence (never awarded here) |

`factor_table` takes the level `lvl` the scorer found and, if any entry of `LIMITATIONS` lists the factor, sets `level = min(lvl, 2)`. The record keeps `evidence_level` (what the evidence alone
would give), `limitations` (every entry bearing on the factor) and `capped_by` (those entries, shown only when the cap lowered the level). A limitation is retired only by editing `LIMITATIONS`
with the evidence that retires it; it is not computed away.

## 3. The nine factors: what each level needs

The rule text is `RULES` verbatim. "Reads" is what the code looks at.

| Factor | Rule (`RULES`) | Reads |
|---|---|---|
| Data pedigree | 1 ingest ledger names its inputs; 2 and every ingest self-check passed and the wrfout/umwmout schemas exist; 3 and the WRF wind and SST were compared with TAO/TRITON moorings for this mission, with pooled wind RMSE within the brief's prior sd (2.0 m/s, 15 deg); the comparison also sets the wind priors, so it is not independent of the run. Round 2, M-17: level 3 reads "compared with moorings (the comparison also sets the wind priors)", not "independent"; it is capped at 2 when the pooled speed RMSE exceeds 2.0 m/s or the direction RMSE 15 deg (the brief's prior sd), unless a limitation names it. | `checkpoints/ingest/ledger.json` inputs and checks; `cafe/schemas/wrfout.json`, `umwmout.json`; `run_dir/ingest/tao_compare.json` and the mission name |
| Verification | 1 a stage ledger exists; 2 every ledger is clean (ok, no failed check, chain intact, hashes reproduce) and tests exist; 3 and a grid-convergence (GCI) study backs a V&V 20 row. A row counts only if it was made by the current recipe (round 2, M-3). | all nine ledgers, `audit.ledger_problems` (ignoring "no ledger" and "stage report" lines), `tests/test_*.py`, a V&V row with `status == run` and a `u_num` |
| Validation | 1 a comparison with a reference ran; 2 and one has all of U_num, U_input, U_D; 3 and at least four such rows all satisfy \|E\| <= U_val with U_val below half the reference (a wider uncertainty cannot validate it). Round 2, M-3: an uncertainty as large as the quantity validates nothing; the 50 % is a labelled choice (DECISIONS 184). | the V&V rows (section 4) |
| Input pedigree | 1 platform inputs carry provenance; 2 and at least half are sourced (not assumed, not recalled); 3 and at least 80 % are, and no perturbation prior is of kind assumed. | the platform files the mission uses (its vehicles' platforms, plus `radios` if an RF link exists, `modems` if an acoustic link exists), `perturbations.yaml` |
| Uncertainty characterization | 1 verdict intervals exist; 2 and the Latin-hypercube stratification checks passed; 3 and every vehicle and link that leaves P(fail) < 5 % open (95 % Wilson lower bound on P(fail) below 5 %) has n >= n_certify, and no perturbation prior is of kind assumed. | `stage1b/summary.json`; the `lhs_stratified_batch*` checks in the ledger of the stage that produced the verdict's ensemble (the stage-1 ledger when stage 1b is a copy, else the stage-1b ledger; round 2, M-16) |
| Results robustness | 1 one ensemble ran; 2 and first-order sensitivities exist for a vehicle or link with both outcomes; 3 and a stage-3 refit reran stage 1 and no verdict changed. | `stage1b/summary.json` sensitivities; `refit/refit.json` (`used`); verdicts of stage 1 against stage 1b |
| Use history | 1 only if docs/USE_HISTORY.md records a past prediction compared with a real outcome; otherwise 0. | the existence of the file; its content is not machine-checked |
| M&S management | 1 ledgers exist; 2 and every ledger carries a git sha, config hash, versions, and the stage-1 seeds; 3 and the ledger chain audits clean, docs/BUILDERS.md exists and ruff is configured. | ledger fields, `docs/BUILDERS.md`, `[tool.ruff]` in `pyproject.toml` |
| People qualifications | 1 only if docs/QUALIFICATIONS.md records who ran and reviewed this; otherwise 0. | the existence of the file |

How the details work:

- **Data pedigree 3** needs `ingest/tao_compare.json`. The comparison feeds the wind priors, so it is a check against moorings and not an independent one; it is evidence about the WRF wind and the frozen SST, not about waves (TAO has no wave variable) or the ocean. The evidence line carries the pooled RMSE, bias and mooring count (q2: speed RMSE 1.46 m/s, bias +0.62; direction RMSE 24.8 deg; SST bias -0.11 K).
- **Verification 3** needs a V&V row with a numerical-uncertainty term, which only the DTMB 5415 rows have (`vv.gci_two_grid`: Roache, `Fs = 3`, assumed order 2, `r` from the cell counts).
- **Validation 2** needs one row with all three terms; the stored sphere and wall-model rows never have them (section 4), so Validation 2 rests on the DTMB rows. **3 needs four complete rows and every one inside its `U_val`.**
- **Input pedigree** counts a platform leaf as sourced when it has a `source` and is neither `assumed` nor "recalled" in its text. It reads only the `value / source / assumed` structure, so a bare number is not counted at all and a block that carries a `source`
  string counts as one sourced item whatever its numbers are.
- **Uncertainty 3** needs `n >= n_certify` (73) for every vehicle and link that leaves P(fail) < 5 % open, i.e. whose 95 % Wilson lower bound on P(fail) is below 5 % (an ensemble above that excludes P(fail) < 5 %, and no number of members certifies it; review round 5, M-11), and no prior of kind `assumed`. Budget `quick` (at most 64 members) cannot reach it; `battery_capacity_scale` is of kind `assumed`,
  so no budget reaches it while that prior is assumed.
- **Robustness 3** needs a vehicle to have been refit, which needs a stage-3 window that passed all its self-checks.
- **M&S management 2** needs a git sha other than `none`: a run from an archive without `.git` stops at 1.
- **M&S management 3** is checked by the tool's own audit (ledger chain, `docs/BUILDERS.md`, ruff), not by an independent reference, so the page reads "strong: ledger chain, house rules and lint checked by the tool's own audit (no independent reviewer)" for it, as `LEVEL_TEXT` does for data pedigree (review round 4, M-20).
- **Use history** and **People** are 0 today: neither `docs/USE_HISTORY.md` nor `docs/QUALIFICATIONS.md` exists. With the file they are 1 and no higher.

### What the current build can reach

With the limitations below (L01 to L12, L13 while the sub-grid layer is uncalibrated, which is every CPU run, and L14 to L20 from rounds 2 to 6), and the files that exist today:

| Factor | Caps from | Highest level this build can show | Needs for more |
|---|---|---|---|
| Data pedigree | none | 3 | a mission with a TAO comparison stored |
| Verification | L04, L10, L12 | 2 | retire L04 (an independent Cd), L10 (a reliable SITL return) and L12 (rerun the stored CFD); the v4 DTMB study is installed in `$CAFE_DATA/dtmb5415` and fills the four V&V rows (numbers in section 4) |
| Validation | L01, L02, L03, L04, L07, L08, L09, L13, L15, L17, L18, L20 | 2 | retire the twelve; complete V&V rows from the current recipe with U_val below 50 % of the reference |
| Input pedigree | L01, L05, L06, L11 | 2 | retire the four; sourced platform data; no assumed prior |
| Uncertainty characterization | L07, L12, L13, L14, L18 | 2 | retire the five; at least 73 members; no assumed prior |
| Results robustness | L10, L15, L16 | 2 | retire the three; a refit that does not change a verdict |
| Use history | none | 0 (1 with the file) | a record in `docs/USE_HISTORY.md` of a prediction compared with a campaign outcome |
| M&S management | none | 3 | nothing the repository lacks, when run from a git checkout |
| People qualifications | none | 0 (1 with the file) | a record in `docs/QUALIFICATIONS.md` |

This table is derived from the code and the file list. It is not a score: the levels of a given run are in its `credibility.json`.

## 4. The ASME V&V 20 rows

```
E = S - D                    S the simulation value, D the data
U_val = sqrt( U_num^2 + U_input^2 + U_D^2 )
|E| <= U_val                 the comparison error is inside the validation uncertainty: the model is not shown wrong at that level; |E| > U_val: E is mostly model-form error
```

Validation is **reported, not pass/fail** in the credibility table (`vv.py`, `credibility._row`). A row has `status` `run` or `not run`; `validated` is `True` or `False` only when all three terms are known,
and `None` ("not assessable (U_val not stored)") otherwise. The DTMB receipts do gate on it (a `bracket` per Froude number), because that module chooses to.

| Rows | Source | S, D | Uncertainty terms |
|---|---|---|---|
| `dtmb5415:Fr0.10`, `Fr0.20`, `Fr0.28`, `Fr0.41` | `$CAFE_DATA/dtmb5415/run_coarse.json` and `run_fine.json` through `dtmb5415.tabulate`, which reads a file only if its `recipe` is `dtmb5415.RECIPE` (`pout-lts01-parts-v4`); `dtmb5415.stale_files(root)` lists the others | S = C_T on the fine grid; D = the INSEAN 2340 value (Olivieri et al. 2001 via the brief: 4.02, 3.95, 4.23, 6.67 x 1e-3) | **U_num** = sqrt( (GCI x S)^2 + (fine-grid iteration std)^2 ), GCI = 3 \|S_f - S_c\| / S_f / (r^2 - 1) with r from the two meshes' cell counts; **U_input** = S x sqrt(u_S^2 + u_nu^2), u_S = 1.3 %, u_nu = 0.6 %; **U_D** = 1.0 % of D |
| `nest_sphere:Re100`, `Re1000`, `Re1e4` | the finest `$CAFE_DATA/receipts/nest_sphere_<Re>_d<cells>.json` (the row names the other resolutions stored, "d = 16 cells (d = 8 and 12 also stored)") | S = native-kernel Cd, D = Morrison 2013 | none stored |
| `lbm_sphere:Re100`, `Re1000`, `Re1e4` | `$CAFE_DATA/receipts/lbm_sphere_<Re>.json` | S = XLB staircase Cd, D = Morrison 2013 | none stored |
| `wallmodel:wm_flat_plate`, `wm_channel` | `$CAFE_DATA/receipts/wm_flat_plate.json`, `wm_channel.json` | S, D = C_f against ITTC-57, against Dean 1978 | none stored |

- The DTMB `u_S`, `u_nu` and `u_D` are **assumed** (`config/assumptions.yaml` `dtmb5415.*`): the DTIC report (ADA458075) answered HTTP 403, so the experimental uncertainty was not read; the free surface is held at the static draft, so sinkage and
  trim sit in E; the water is taken as fresh at 20 C. The brief's four C_T values were not re-read at source. Each row says so.
- The sphere and wall-model rows store S and D only, so they are listed with E and "U_val not stored" and can never be counted as validated.
- A row is `not run` with the file name when its file is missing; the Validation factor lists each such row as missing. Round 2 (M-3): a file of another recipe is also `not run`, with the reason ("run_coarse.json was made by recipe None, not pout-lts01-parts-v4"). The q2 report counted the two v3 files (made before the recipe stamp existed) as four `run` rows, three of them validated at U_val about 100 % of C_T, and showed Validation 2; with them refused the report read Validation 1 and Verification 2 until the v4 files were copied to `/data/dtmb5415` (done after round 3). A row also counts toward Validation 3 only if U_val is below 50 % of its reference.
- The `nest_sphere` rows read the finest `nest_sphere_<Re>_d<d>.json` that `stage3.nest` stores (round 3, M-11); with none stored the row reads "not run: no nest_sphere_<tag>_d*.json under <dir>". Before round 3 they looked for a name without the grid size and read "not run" even when runs were stored.
- The earlier stored table (`runs/receipts.json`, 2026-10-29 00:36) has one DTMB row, Fr 0.28: C_T 4.06e-3 against 4.23e-3, E = -0.17e-3, U_val = 3.66e-3, all of it U_num (90 % of C_T). That row satisfies `|E| <= U_val` because the numerical uncertainty is large, which says little.
  That table was made before the recipe stamp existed. The v4 study (three grids, Fr 0.10, 0.20, 0.28 and 0.41) is done: E x1e3 = +0.865, +0.722, +0.842, -0.040 against U_val x1e3 = 1.882, 1.085, 2.653, 1.993, so |E| <= U_val at all four, but U_val / D is 0.27 to 0.63 (0.468, 0.275, 0.627, 0.299) against the 0.1 that the "validation says something" check asks for, and iterative convergence fails at Fr 0.28 and 0.41 on all three grids (last-quarter drift 0.03 to 0.07 against 0.005). Read the four rows as consistent with the data, not as a validation.

## 5. The known limitations (`LIMITATIONS`)

Copied from the code. "Bears on" lists the factors it caps at 2. L01 to L12 were checked against the code on 2026-10-29; L13 to L18 on 2026-10-31 (review round 2). The texts of L01 to L12 and L14 to L20 are the same in `credibility.py`, character for character (`tests/test_config_docs.py` checks it); L13 is built at run time. The table is in the order the code lists them: L13 sits between L12 and L14.

| Id | Text | Bears on | Where | State today |
|---|---|---|---|---|
| L01 | acoustic 4 km MF range is true by construction | validation, input pedigree | `platforms/modems.yaml`, `cafe/pm/physics/comms.py` | holds: the implementation loss is derived from the vendor range with a 3 dB margin; the 6 and 8 km rows test the shape |
| L02 | the USV 12 m/s point is a fit | validation | `platforms/saildrone_explorer.yaml`, `cafe/pm/physics/usv.py` | holds: `appendage_cda_m2` 0.02 to 0.04; the receipt is labelled CALIBRATED |
| L03 | the Sun et al. magnitude is 8–26 % vs the published 30–35 % | validation | `cafe/pm/physics/usv.py` | holds: the sign is reproduced, the size is not |
| L04 | the Cd receipt is a closure | validation, verification | `cafe/pm/env/coare.py` | holds: Edson's Cd table was unreadable (HTTP 403) |
| L05 | several citations were recalled, not re-read | input pedigree | `platforms/saildrone_explorer.yaml`, `seaglider.yaml`, `quad_uas.yaml` | holds; also `config/assumptions.yaml` (the Seaglider and Slocum dimensions) and `config/subgrid.json` (Iyer and Drushka, Wills et al., Okubo) |
| L06 | the glider T(z) profile is assumed | input pedigree | `platforms/seaglider.yaml` | holds: an exponential profile, 4 degC and 150 m |
| L07 | turbulence σ_v/σ_u and σ_w/σ_u are low | validation, uncertainty | `cafe/pm/env/subgrid.py` | holds: 0.63 and 0.43 against IEC 0.8 and 0.5 |
| L08 | LBM sphere drag is not met on CPU | validation | `cafe/pm/stage3/lbm.py`, `nest.py` | holds: the XLB staircase rows fail by +30 to +73 %; the native kernel meets Re = 100 by extrapolation and needs d >= 24 and 40 for Re = 1e3 and 1e4 |
| L09 | the wall model is not validated | validation | `cafe/pm/stage3/wallmodel.py` | holds in part: a body-force channel passes (C_f within 1 % of Dean); the flat plate at Re_L >= 1e6 needs a stored 1.8 h run |
| L10 | the SITL return/landing is unreliable | verification, robustness | `cafe/pm/physics/uas.py` | holds: touchdown 4 to 160 m from the ship in 4 trials |
| L11 | the UAS propulsion curve is parametric | input pedigree | `platforms/quad_uas.yaml` | holds: figure of merit, omega_max and efficiency assumed |
| L12 | GCI values stored before the r = (N_f/N_c)^(1/3) fix were understated | verification, uncertainty | `cafe/pm/vv.py`, `cafe/pm/dtmb5415.py` | holds for results stored before `9e0bdc7`; the fix itself is in `cafe/cfd.py`. The stored files are on homebase and were not opened here |
| L13 | sub-grid layer uncalibrated: \<reason\> (the text comes from the stage-3 ledger note, else from `config/subgrid.json` `calibration.source_run` being null; a run that wrote its own `stage3/subgrid_calibration.json` is calibrated, round 3, M-23) | validation, uncertainty | `config/subgrid.json`, `cafe/pm/stage3/pipeline_windows.py` | holds in every CPU run: no LES window has passed, so the layer keeps its fixed coefficients (DECISIONS 162, 179). With `--gpus 0` the stage-3 ledger's reason is still "no LES window passed its self-checks", because the windows are not run (L15) |
| L14 | the wind prior's persistent and short-lived parts are split from the TAO moorings over this window: an estimate of the order, not a measurement | uncertainty | `cafe/pm/pipeline.py`, `cafe/pm/env/perturb.py`, `config/perturbations.yaml` | holds: the q2 fit took the whole hourly misfit (sd 1.33 m/s, 23.7 deg) as persistent; the 11 per-mooring time-mean speed biases have sd 0.375 m/s and direction sd 8.7 deg, and six-day means of a synoptic WRF error are still correlated within the run (M-1) |
| L15 | no LES window can reach the lattice viscosity floor on a CPU, so none is run and the sub-grid layer and the drag refit stay uncalibrated; no GPU run exists | validation, robustness | `config/assumptions.yaml`, `cafe/pm/budget.py`, `cafe/pm/stage3/pipeline_windows.py` | holds: all five q2 windows ran with the viscosity raised (glider_eq 1e-4 against 3.70e-6 at dx 0.095 m); reaching the floor takes about 1e13 to 1e14 cell-updates against 2.2e8 per window at `quick`, at a measured 7.5e6 cell-updates/s (M-8) |
| L16 | the refit is a single pass: stage 1 is rerun once with the refitted multipliers, not looped until the verdicts stop changing | robustness | `cafe/pm/pipeline.py` | holds: BRIEF 2.6 asks for a loop capped at two iterations; the pipeline performs 0 (no window passed) or 1 (M-27) |
| L17 | UAS attitude exceedance cannot fire in this controller model (tilt clamp 35 deg, exceedance 42 deg) | validation | `cafe/pm/physics/uas.py`, `platforms/quad_uas.yaml` | holds: `max_tilt_deg` is 35.00 in all 96 q2 sorties and the mode fired in 0 members, so the UAS verdict rests on the battery and on finishing the profile inside the time limit (q5: 55 of 64 members failed `profile_incomplete`, 6 `battery_reserve`; M-28, review round 5, M-26) |
| L18 | the USV speed prior is calibrated in a scenario without current, and the mission's westward current then lowers the speed ratio again; whether Chiodi et al.'s 0.178 already includes currents is not known, so a double penalty is possible and not established | validation, uncertainty | `platforms/saildrone_explorer.yaml`, `cafe/pm/physics/usv.py` | open (M-2): the nominal diagnosis scenario of review round 2 (not the ensemble) gave a USV ratio of 0.120 (anemometer height 0.125) against 0.178; wind alone gives 0.186, waves 0.180, the westward current 0.150, all three 0.120. The q5 ensemble's median ratio is 0.129 (0.135 at the anemometer height; review round 5, M-26). The current alone costs a third of the speed: the mean zonal drift of 0.33 m/s turns a beam reach into a close-hauled course (true wind angle 85 to 45 deg) and the speed through the water falls from 1.1 to 0.72 m/s. The current is counted once. The prior was not retuned. QUESTIONS_FOR_LAB asks whether 0.178 was observed in real currents |
| L19 | the persistent wind-speed prior is a boundary moment estimate from the TAO moorings of one regime, not a measured spread: in the evidence run q5 11 moorings over 6 days gave 0.113 m/s, with a 95 % upper bound of about 0.5 m/s (the literature prior was 2.0 m/s), and regime-to-regime bias outside the window is not sampled | uncertainty, validation | `cafe/pm/pipeline.py` | holds (review round 5, M-10): the 11 time-mean speed errors have variance 0.141 (sd 0.375 m/s) and their sampling variance (autocorrelated hourly errors, about 144 hours each) is about 0.15, so the true between-mooring spread is estimated as 0 and the prior's 0.113 m/s is only the uncertainty of the mean of 11 moorings. The 95 % one-sided upper bound of the between-mooring variance with 10 degrees of freedom is 10 x 0.1408 / 3.94 = 0.357, which gives a persistent sd up to about 0.46 to 0.49 m/s. `ingest/priors_fitted.json` carries it as `value_hi95` next to `value` and the report prints both. The fitted mean correction (-0.616 m/s) is applied to every member, so a regime-to-regime bias outside 2023-03-01 to 07 is not in the ensemble. The prior's `value` stays the fitted estimate (BRIEF 5.2); QUESTIONS_FOR_LAB asks whether the upper bound should replace it. Both factors it bears on were already capped at 2 by other limitations, so no level moved |
| L20 | UAS turbulence is generated at one height for all legs: one Mann box per sortie, at the deck height plus the mean of the sortie's flight altitudes, is applied to every leg, so a leg flown at another altitude sees the length scale of that height | validation | `cafe/pm/stage1.py`, `cafe/pm/env/subgrid.py` | holds (review round 6, M-18): for the demo mission (altitudes 10, 30, 60 and 100 m, deck height 8 m) the box is made at z = 8 + 50 = 58 m, where Lambda_1 = min(0.7 z, 42 m) = 40.6 m; the 10 m leg (z = 18 m) would have 12.6 m and the 100 m leg (z = 108 m) the cap of 42 m. sigma_u = 2.5 u* does not depend on height in this model, so the amplitude is unchanged and only the length scale (the size of the energy-containing eddies) is. Whether it moves a flag was not tested; the demo's UAS failures in q6 are 55 of 55 `profile_incomplete`, which turbulence does not set. A box per leg would change `_uas_forcing` and `fly_sortie`'s interface, so it is a feature and not done. Validation was already capped at 2, so no level moved |

### Limitations that bear on a factor and are not in the list

These were found while writing the docs. They are not in `LIMITATIONS`, so they do not cap anything; each is in `CHANGELOG.md` under Known issues.

- `wind_sea_age` (2.0) and `swell_age` (1.2) in `cafe/pm/env/waves.py` are assumed and are not in `assumptions.yaml`, so they are not in the assumed-inputs list.
- The "Hangar" coefficient that the refit and the stage-3 rows divide by is the vehicle's baseline model coefficient (analytic; no Hangar CFD run), so there is no Hangar GCI, observed order or mesh-quality evidence behind it (Verification, Validation).
- The stage-1 UAS Mann-turbulence draws are keyed by batch, not by member (a Mann box is generated for the whole batch), so a member's turbulence segment depends on the batch size, which the stage-1 ledger records. Round 2 (M-12) keys the gust-front and Iridium draws per member where that is cheap (Uncertainty).
- The emulator is scored only on a synthetic table; the real-spectrum correction takes a median error as a 1-sigma (Uncertainty).

## 6. The assumed-inputs list

`assumed_inputs()` returns, in this order:

1. every key of `config/assumptions.yaml` (kind `assumed`), with value, unit, why and what replaces it;
2. every entry of `config/perturbations.yaml`, kind `prior` (the brief's number) or `assumed` (an entry of kind `assumed`, or one whose citation contains "ASSUMED");
3. every mapping in `platforms/*.yaml` that carries `assumed: true` (the leaf with its why).

Round 3 (M-12): when the run holds `ingest/env_sigmas_fitted.json`, the `assumptions.yaml:env.sigma.<k>` items for the keys present (`sst_k`, `t2_k`) have kind `fitted` and read "this run used 0.259 (fitted from the TAO comparison); assumed 0.5". They stay in the list, with both values, and the report's count of assumed inputs leaves them out.

On 2026-11-01, in the review-round-4 working tree, that is 263 items: 78 from `assumptions.yaml`; 12 from `perturbations.yaml` (11 priors, 1 assumed: `battery_capacity_scale`); 173 platform leaves marked assumed (`quad_uas` 46, `saildrone_explorer` 59, `slocum` 26, `seaglider` 21,
`radios` 19, `modems` 2). Review round 4 added two assumed inputs, both in `platforms/quad_uas.yaml` (44 before): `sortie.min_profile_fraction` (1.0; the shortest acceptable fraction of the flux profile, M-1) and `radio.link_loss_hold_s` (5 s; the radio failsafe timeout, M-10); both are asked of the lab in `QUESTIONS_FOR_LAB.md` 4 and 5. The counts change whenever an input file does; recount with `pm python -c "from cafe.pm import credibility as C; print(len(C.assumed_inputs()))"`. The mission report marks a verdict that depends on one of these with an "assumed" badge.

Provenance is also enforced at load: `glider.load_platform`, `usv.load_platform` and `uas.load_platform` refuse a leaf with neither a `source` nor `assumed: true` with a `why`, and the hangar stage fails a run on one.

## 7. Reading the report honestly

- A verdict that cites a model-receipt table made by other code than the run's reads "stale: made by other code" and is not counted as a pass (round 2, M-4).
- A level of 2 is the highest this build can show for five factors. It does not mean "moderate confidence in the verdicts"; it means the build's own checks pass and a named limitation remains.
- The sanity table compares each demo verdict with BRIEF section 6, except that a drift glider has `agrees` null: it has no mission criterion, so its GO means only that the battery and depth limits held on its fixed heading (round 3, M-1).
- The "most sensitive to" entry ranks one continuous outcome (a margin), not the verdict, over the columns that can act on the vehicle, and says which outcome and which of five cases applies; with at most three failures or passes it prints the hypercube ranks of those members instead of an index (round 3, M-2).
- A link decided on too few required samples for its `required_fraction` (one missed sample is more than the mission allows to be missed) reads "undecided: granularity" (round 3, M-5).
- A GO from a budget below 73 members says so in its note; the Uncertainty factor cannot reach 3 there.
- A verdict is `decided` (report.json `decided`, `region` = GO or NO-GO) only when the whole 95 % interval on P(fail) lies inside GO (at most 0.10) or inside NO-GO (above 0.40), the interval the sequential stopper reads. Otherwise the report marks it "undecided at n = N" and says which threshold the interval spans: the printed verdict is the best estimate at that n, not a call, and a larger `--budget` is what decides it. MARGINAL is never decided by this reading.
- A verdict that rests on an assumed input (the acoustic range, the USV speed bias, the UAS battery, the glider ballast, the wall-model coefficients) carries the badge; the list in section 6 says what would replace each.
- A comparison with a reference that exists only as a context row in `python -m cafe.pm receipts` (the sub-grid ranges, the sea-state roughness against `pycoare`, the Sun et al. size) is not in the V&V table and does not raise any level.
- The tool has no use history and no record of who ran or reviewed a run. Those two factors read 0 until the files exist.
