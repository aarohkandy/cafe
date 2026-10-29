# CREDIBILITY — how the credibility report is scored

What `cafe/pm/credibility.py` computes, what evidence each level needs, and what the tool cannot show. Written against `bb68642` on 2026-10-29. If this file and
`credibility.py` disagree, the code is right; `LIMITATIONS`, `FACTORS`, `RULES` and `LEVELS` below are copied from it and must be kept the same.

## 1. What it is

The report stage (`pipeline.s_report`, `report.write`) writes `run_dir/report/credibility.html` and `credibility.json` next to the mission report. They hold four things:

| Part | Content |
|---|---|
| NASA-STD-7009B factor table | nine factors, a level 0 to 4 each, the rule that gave it, the evidence (with the file), what is missing |
| ASME V&V 20 table | one row per comparison with a reference: `E = S - D`, the three uncertainty terms, `U_val`, `\|E\| <= U_val` |
| Known limitations | `LIMITATIONS`, twelve entries, each capping the factors it bears on |
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
| Data pedigree | 1 ingest ledger names its inputs; 2 and every ingest self-check passed and the wrfout/umwmout schemas exist; 3 and a TAO/TRITON comparison is stored for this mission. | `checkpoints/ingest/ledger.json` inputs and checks; `cafe/schemas/wrfout.json`, `umwmout.json`; `run_dir/ingest/tao_compare.json` and the mission name |
| Verification | 1 a stage ledger exists; 2 every ledger is clean (ok, no failed check, chain intact, hashes reproduce) and tests exist; 3 and a grid-convergence (GCI) study backs a V&V 20 row. | all nine ledgers, `audit.ledger_problems` (ignoring "no ledger" and "stage report" lines), `tests/test_*.py`, a V&V row with `status == run` and a `u_num` |
| Validation | 1 a comparison with a reference ran; 2 and one has all of U_num, U_input, U_D; 3 and at least four such rows all satisfy \|E\| <= U_val. | the V&V rows (section 4) |
| Input pedigree | 1 platform inputs carry provenance; 2 and at least half are sourced (not assumed, not recalled); 3 and at least 80 % are, and no perturbation prior is of kind assumed. | the platform files the mission uses (its vehicles' platforms, plus `radios` if an RF link exists, `modems` if an acoustic link exists), `perturbations.yaml` |
| Uncertainty characterization | 1 verdict intervals exist; 2 and the Latin-hypercube stratification checks passed; 3 and every vehicle and link has n >= n_certify and no perturbation prior is of kind assumed. | `stage1b/summary.json`; the `lhs_stratified_batch*` checks in the stage-1b ledger (a stage 1b that is a copy of stage 1 has none) |
| Results robustness | 1 one ensemble ran; 2 and first-order sensitivities exist for a vehicle or link with both outcomes; 3 and a stage-3 refit reran stage 1 and no verdict changed. | `stage1b/summary.json` sensitivities; `refit/refit.json` (`used`); verdicts of stage 1 against stage 1b |
| Use history | 1 only if docs/USE_HISTORY.md records a past prediction compared with a real outcome; otherwise 0. | the existence of the file; its content is not machine-checked |
| M&S management | 1 ledgers exist; 2 and every ledger carries a git sha, config hash, versions, and the stage-1 seeds; 3 and the ledger chain audits clean, docs/BUILDERS.md exists and ruff is configured. | ledger fields, `docs/BUILDERS.md`, `[tool.ruff]` in `pyproject.toml` |
| People qualifications | 1 only if docs/QUALIFICATIONS.md records who ran and reviewed this; otherwise 0. | the existence of the file |

How the details work:

- **Data pedigree 3** needs `ingest/tao_compare.json`. The comparison feeds the wind priors; it is evidence about the WRF wind and the frozen SST, not about waves (TAO has no wave variable) or the ocean.
- **Verification 3** needs a V&V row with a numerical-uncertainty term, which only the DTMB 5415 rows have (`vv.gci_two_grid`: Roache, `Fs = 3`, assumed order 2, `r` from the cell counts).
- **Validation 2** needs one row with all three terms; the stored sphere and wall-model rows never have them (section 4), so Validation 2 rests on the DTMB rows. **3 needs four complete rows and every one inside its `U_val`.**
- **Input pedigree** counts a platform leaf as sourced when it has a `source` and is neither `assumed` nor "recalled" in its text. It reads only the `value / source / assumed` structure, so a bare number is not counted at all and a block that carries a `source`
  string counts as one sourced item whatever its numbers are (section 5, `radios.yaml`).
- **Uncertainty 3** needs `n >= n_certify` (73) for every vehicle and link and no prior of kind `assumed`. Budget `quick` (at most 64 members) cannot reach it; `battery_capacity_scale` is of kind `assumed`,
  so no budget reaches it while that prior is assumed.
- **Robustness 3** needs a vehicle to have been refit, which needs a stage-3 window that passed all its self-checks.
- **M&S management 2** needs a git sha other than `none`: a run from an archive without `.git` stops at 1.
- **Use history** and **People** are 0 today: neither `docs/USE_HISTORY.md` nor `docs/QUALIFICATIONS.md` exists. With the file they are 1 and no higher.

### What the current build can reach

With the twelve limitations below, and the files that exist today:

| Factor | Caps from | Highest level this build can show | Needs for more |
|---|---|---|---|
| Data pedigree | none | 3 | a mission with a TAO comparison stored |
| Verification | L04, L10, L12 | 2 | retire L04 (an independent Cd), L10 (a reliable SITL return) and L12 (rerun the stored CFD) |
| Validation | L01, L02, L03, L04, L07, L08, L09 | 2 | retire the seven; complete V&V rows |
| Input pedigree | L01, L05, L06, L11 | 2 | retire the four; sourced platform data; no assumed prior |
| Uncertainty characterization | L07, L12 | 2 | retire both; at least 73 members; no assumed prior |
| Results robustness | L10 | 2 | retire L10; a refit that does not change a verdict |
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
| `dtmb5415:Fr0.10`, `Fr0.20`, `Fr0.28`, `Fr0.41` | `$CAFE_DATA/dtmb5415/run_coarse.json` and `run_fine.json` through `dtmb5415.tabulate` | S = C_T on the fine grid; D = the INSEAN 2340 value (Olivieri et al. 2001 via the brief: 4.02, 3.95, 4.23, 6.67 x 1e-3) | **U_num** = sqrt( (GCI x S)^2 + (fine-grid iteration std)^2 ), GCI = 3 \|S_f - S_c\| / S_f / (r^2 - 1) with r from the two meshes' cell counts; **U_input** = S x sqrt(u_S^2 + u_nu^2), u_S = 1.3 %, u_nu = 0.6 %; **U_D** = 1.0 % of D |
| `nest_sphere:Re100`, `Re1000`, `Re1e4` | `$CAFE_DATA/receipts/nest_sphere_<Re>.json` | S = native-kernel Cd, D = Morrison 2013 | none stored |
| `lbm_sphere:Re100`, `Re1000`, `Re1e4` | `$CAFE_DATA/receipts/lbm_sphere_<Re>.json` | S = XLB staircase Cd, D = Morrison 2013 | none stored |
| `wallmodel:wm_flat_plate`, `wm_channel` | `$CAFE_DATA/receipts/wm_flat_plate.json`, `wm_channel.json` | S, D = C_f against ITTC-57, against Dean 1978 | none stored |

- The DTMB `u_S`, `u_nu` and `u_D` are **assumed** (`config/assumptions.yaml` `dtmb5415.*`): the DTIC report (ADA458075) answered HTTP 403, so the experimental uncertainty was not read; the free surface is held at the static draft, so sinkage and
  trim sit in E; the water is taken as fresh at 20 C. The brief's four C_T values were not re-read at source. Each row says so.
- The sphere and wall-model rows store S and D only, so they are listed with E and "U_val not stored" and can never be counted as validated.
- A row is `not run` with the file name when its file is missing; the Validation factor lists each such row as missing.
- The `nest_sphere` rows look for a file name without the grid size, but `stage3.nest` stores `nest_sphere_<Re>_d<d>.json`, so these three rows read "not run" even when runs are stored. This is a mismatch in the code, not a result.
- The earlier stored table (`runs/receipts.json`, 2026-10-29 00:36) has one DTMB row, Fr 0.28: C_T 4.06e-3 against 4.23e-3, E = -0.17e-3, U_val = 3.66e-3, all of it U_num (90 % of C_T). That row satisfies `|E| <= U_val` because the numerical uncertainty is large, which says little.
  The coarse and fine runs that will fill all four rows were still running when this was written.

## 5. The known limitations (`LIMITATIONS`)

Copied from the code. "Bears on" lists the factors it caps at 2. Each was checked against the code on 2026-10-29.

| Id | Text | Bears on | Where | State today |
|---|---|---|---|---|
| L01 | acoustic 4 km MF range is true by construction | validation, input pedigree | `platforms/modems.yaml`, `cafe/pm/physics/comms.py` | holds: the implementation loss is derived from the vendor range with a 3 dB margin; the 6 and 8 km rows test the shape |
| L02 | the USV 12 m/s point is a fit | validation | `platforms/saildrone_explorer.yaml`, `cafe/pm/physics/usv.py` | holds: `appendage_cda_m2` 0.02 to 0.04; the receipt is labelled CALIBRATED |
| L03 | the Sun et al. magnitude is 8-26 % vs the published 30-35 % | validation | `cafe/pm/physics/usv.py` | holds: the sign is reproduced, the size is not |
| L04 | the Cd receipt is a closure | validation, verification | `cafe/pm/env/coare.py` | holds: Edson's Cd table was unreadable (HTTP 403) |
| L05 | several citations were recalled, not re-read | input pedigree | `platforms/saildrone_explorer.yaml`, `seaglider.yaml`, `quad_uas.yaml` | holds; also `config/assumptions.yaml` (the Seaglider and Slocum dimensions) and `config/subgrid.json` (Iyer and Drushka, Wills et al., Okubo) |
| L06 | the glider T(z) profile is assumed | input pedigree | `platforms/seaglider.yaml` | holds: an exponential profile, 4 degC and 150 m |
| L07 | turbulence sigma_v/sigma_u and sigma_w/sigma_u are low | validation, uncertainty | `cafe/pm/env/subgrid.py` | holds: 0.63 and 0.43 against IEC 0.8 and 0.5 |
| L08 | LBM sphere drag is not met on CPU | validation | `cafe/pm/stage3/lbm.py`, `nest.py` | holds: the XLB staircase rows fail by +30 to +73 %; the native kernel meets Re = 100 by extrapolation and needs d >= 24 and 40 for Re = 1e3 and 1e4 |
| L09 | the wall model is not validated | validation | `cafe/pm/stage3/wallmodel.py` | holds in part: a body-force channel passes (C_f within 1 % of Dean); the flat plate at Re_L >= 1e6 needs a stored 1.8 h run |
| L10 | the SITL return/landing is unreliable | verification, robustness | `cafe/pm/physics/uas.py` | holds: touchdown 4 to 160 m from the ship in 4 trials |
| L11 | the UAS propulsion curve is parametric | input pedigree | `platforms/quad_uas.yaml` | holds: figure of merit, omega_max and efficiency assumed |
| L12 | GCI values stored before the r = (N_f/N_c)^(1/3) fix were understated | verification, uncertainty | `cafe/pm/vv.py`, `cafe/pm/dtmb5415.py` | holds for results stored before `9e0bdc7`; the fix itself is in `cafe/cfd.py`. The stored files are on homebase and were not opened here |

### Limitations that bear on a factor and are not in the list

These were found while writing the docs. They are not in `LIMITATIONS`, so they do not cap anything; each is in `CHANGELOG.md` under Known issues.

- Assumed numbers in `platforms/radios.yaml` (antenna gain 2 dBi, 3 dB miscellaneous loss, Iridium success 0.95, three attempts, set-up time) and `platforms/modems.yaml` `defaults` (3 dB anchor margin) are not marked leaf by leaf. The report lists each radio and Iridium block as **sourced**
  and lists the two modem blocks as assumed as wholes, so Input pedigree is counted too high for a mission with RF or Iridium links.
- `wind_sea_age` (2.0) and `swell_age` (1.2) in `cafe/pm/env/waves.py` are assumed and are not in `assumptions.yaml`, so they are not in the assumed-inputs list.
- The stage-1 UAS turbulence, gust-front and Iridium draws are keyed by batch, not by member (Uncertainty).
- The stage-3 wall-model check takes the better of the stored flat-plate and channel errors (Validation, Robustness).
- The emulator is scored only on a synthetic table; the real-spectrum correction takes a median error as a 1-sigma (Uncertainty).
- Mission switches `warm_layer`, `rain_lens` and `ocean_sde` are not read; `bulk_stress_scale` is applied by nothing (Input pedigree: the report lists priors that do nothing).

## 6. The assumed-inputs list

`assumed_inputs()` returns, in this order:

1. every key of `config/assumptions.yaml` (kind `assumed`), with value, unit, why and what replaces it;
2. every entry of `config/perturbations.yaml`, kind `prior` (the brief's number) or `assumed` (an entry of kind `assumed`, or one whose citation contains "ASSUMED");
3. every mapping in `platforms/*.yaml` that carries `assumed: true` (the leaf with its why).

On 2026-10-29 that is 220 items: 58 from `assumptions.yaml`; 11 from `perturbations.yaml` (10 priors, 1 assumed: `battery_capacity_scale`); 151 platform leaves marked assumed (`quad_uas` 44, `saildrone_explorer` 58, `slocum` 26, `seaglider` 21,
`modems` 2). `radios.yaml` contributes none, for the reason in section 5. The mission report marks a verdict that depends on one of these with an "assumed" badge.

Provenance is also enforced at load: `glider.load_platform`, `usv.load_platform` and `uas.load_platform` refuse a leaf with neither a `source` nor `assumed: true` with a `why`, and the hangar stage fails a run on one.

## 7. Reading the report honestly

- A level of 2 is the highest this build can show for five factors. It does not mean "moderate confidence in the verdicts"; it means the build's own checks pass and a named limitation remains.
- A GO from a budget below 73 members says so in its note; the Uncertainty factor cannot reach 3 there.
- A verdict that rests on an assumed input (the acoustic range, the USV speed bias, the UAS battery, the glider ballast, the wall-model coefficients) carries the badge; the list in section 6 says what would replace each.
- A comparison with a reference that exists only as a context row in `python -m cafe.pm receipts` (the sub-grid ranges, the sea-state roughness against `pycoare`, the Sun et al. size) is not in the V&V table and does not raise any level.
- The tool has no use history and no record of who ran or reviewed a run. Those two factors read 0 until the files exist.
