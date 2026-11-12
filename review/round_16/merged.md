# Round 16 merged findings (BRIEF 5.6 step 2)

Inputs: reviewer_a.md (5 findings), reviewer_b.md (9), reviewer_c.md (9), reviewer_d.md (7). Merged to 29 findings, M-1 .. M-29, from 30 source ids; C-1 and C-2 share one root cause and one fix site and form M-1. Every source id appears in exactly one merged finding (A-1..A-5, B-1..B-9, C-1..C-9, D-1..D-7).
Each finding was checked by an independent verifier against HEAD af880ee, by reading the cited code and the q16 run files and, for many claims, by reproducing it on cafe-orca (proot, 2 CPUs) in a detached worktree and a private `pm_v16_*` directory (removed afterwards). Static, arithmetic and pure-text claims were checked by reading or locally. The "check" lines are the verifiers' results; this merge re-ran nothing, and severity and status are the verifiers', not the reviewers'. Where a verifier corrected a figure, a line number or a scope, the check says so.
Not covered by any reviewer (their own lists, shortened):
- Reviewer A: DECISIONS rows 832 to 876 not mutated (833, 838 to 840, 842, 843, 845 to 849, 853 to 858, 862, 863, 869, 871, 873 to 876); the shell runners (proot_run.sh, pmx.sh) not mutated; mutants ran against the tests that name each fix, not the whole suite; no full demo, stage-1, stage-3 or CFD run, no acceptance, gate or GPU, whatif not run end to end; of 50 sampled DECISIONS rows about 25 checked against code, the rest read only; the store lock was exercised only by the existing tests, not under 2-CPU contention with a real build; P-R16Q2 is already in review/orca/PROBLEMS.md.
- Reviewer B: the run's own hourly WRF wind/SST at the mooring positions (derived.zarr is on orca; only stored tao_compare.json, priors_fitted.json, env_sigmas_fitted.json used); no TAO ADCP fetched, so the EUC core is compared to nothing; Bellhop and the GOFS sound-speed profile never entered the demo; waves/Hs checked against nothing; Seaglider thermal term (M-19) and 1 % windage left as owner decisions; glider and USV energy checked by arithmetic, not by recomputing pump energy per dive; Hs worse-end rule reviewed by geometry only; the P.526 figures in M-19 come from the reviewer's and verifier's own hand-coded implementations and should be re-derived before being acted on.
- Reviewer C: values needing the environment cache (worst-window forcing, reach-map outline, environment-along-tracks arrays, a fresh FEA hull depth); wind noise sd and tau beyond consistency checks; credibility.json levels beyond the arithmetic checked; emulator/design.json variants and receipt digests; whatif with --vehicle, a trained emulator or a vehicle with links in both directions. No demo, gate or CFD started. C did not add the PROBLEMS.md row (PROMPT.md says to edit nothing but the findings file); M-1 is the row it would add.
- Reviewer D: OpenFOAM is not on the worker, so cfd.py case generation was read, not run; hycom.fetch_gofs / assemble_gofs read, not run (no network); read_archv / read_lab_netcdf exercised only through shipped fixtures, not fuzzed; the GEBCO fetch race (M-12) is read from the code, not reproduced; UAS rigid-body, controller and battery equations read but no sortie flown; USV strip theory checked only through its receipts; bathy over a continuous-across-0E lab store read, not run; coare.py outside scope.
INCIDENTS and side effects disclosed by the reviewers and verifiers (none repaired by this merge):
- Reviewer A: scratch worktree ../cafe-rev16-a, orca directories pm_rev16_a and pm_rev16_a2, job markers and rev16a_* logs removed by exact name; one run of A's own ended by exact pid after the tmux kill did not stop it; no stash.
- Reviewer B: scratch worktree and pm_rev16_b removed; nothing written to /data or the repo except reviewer_b.md.
- Reviewer C: pm_rev16_c, c2, c3, their .pmx.job markers, pmdata/runs/rev16_c_t, logs rev16c_* and worktree cafe-rev16-c removed by exact name; no stash; no shared store written; no Azure resource touched.
- Verifiers: each removed its own `pm_v16_*` directory, scripts, logs and detached worktree.

Severity: 0 critical, 1 major (M-1), 28 minor. Status: 18 confirmed, 10 partly (M-4, M-6, M-7, M-8, M-9, M-13, M-21, M-26, M-27, M-28), 1 not confirmed (M-12).

---

## Critical

None. No reviewer found one and no verifier raised one.

---

## Major

### M-1. whatif draws its Stage-1 answers from other Latin-hypercube columns than the base run, so the answer is not what a rerun of the changed mission gives (sign can flip); the base numbers also depend on which other classes are in the mission   (sources: C-1, C-2)
severity: major / status: confirmed / lane: statistics, reproducibility
where: cafe/pm/whatif.py:904-911 (`_stage1` -> `stage1.run` on `solo()`), cafe/pm/stage1.py:938 and :62-75 (`priors_for` lists only the present classes' columns), cafe/pm/stats/sampling.py:193 (`lhs_unit`), cafe/pm/whatif.py:223-227 (`solo` docstring), :728-731 (`measure` claims common random numbers); cafe/pm/__main__.py:356-357 (`--drop` message); sampling.py:241-243 (`member_seed` comment)
claim: `whatif --move 0.5degW` on q16 prints glider_eq MARGINAL 0.281 -> 0.344 (22 of 64); the same change made in the mission file and run as the whole mission with the base draws gives 12 of 64 = 0.1875 (baseline 18): opposite sign. `--shift 6h`: glider_eq CLI 12/64 vs rerun 14/64; usv CLI 30/32 vs flip.json 31/32; uas CLI 32/32 vs 31/32. `--drop uas` prints "Other vehicles are unaffected" while a rerun without the UAS (9 columns) gives glider_eq 13/64 (q16 had 18) and usv 60/64 (q16 62). The report's candidate table and the whatif command disagree for the same change.
check: confirmed by reading and by a numpy check. `whatif.answer` builds `pri, marg` from the FULL mission and passes them to `measure`, `flip_search` and `run_variant` (whatif.py:397-409, 790, 803, 889), which call `run_batch` with the full mission's columns. The what-if answer path `_stage1` calls `stage1.run(solo(m2, vid))`, and `stage1.run` (stage1.py:938) recomputes `priors_for` of the solo mission. `lhs_unit(64, 8)` vs `lhs_unit(64, 10)`, same seed: column 0 differs by up to 0.0137, so every column changes with the column count. The orca numbers (22/64 vs 12/64) are the reviewer's and are consistent with the mechanism; the verifier did not rerun them. Unpaired draw noise has sd about 0.08, which is the size of the shown effect. No DECISIONS row sanctions the unpaired path: row 71 keys seeds by member and stream, never by vehicle, and rows 141/275 run variants with the mission's pri/marg. C-2: the physics claim ("Stage-1 vehicles do not interact") is true; the draws are not independent of the class set, so only the sentence about numbers is wrong; `--drop` prints no P(fail).
fix: give `stage1.run` an optional `priors=(pri, marg)` argument (default `priors_for(mission, fitted)`) and have `whatif._stage1` pass the pair `answer()` already holds from the full mission. Regression test: for a two-class mission, the what-if Stage-1 result for the base mission must equal the same members of the full run (same failure vector); it fails before. Could break: the summary and sensitivity indices now include columns the solo vehicle does not use (the names list and ledger text change), existing whatif tests that pin Stage-1 counts, and the sequential stop on the solo vehicle stops at a different n. For C-2 reword the message in `__main__.py` ("physics are unaffected; a rerun of a mission without it draws other members, so counts can differ by sampling noise"); keeping the full columns on a reduced rerun is the exact alternative. Correct the `solo` docstring and the `member_seed` comment.
sources: C-1, C-2

---

## Minor

### M-2. The UAS what-if line compares a 3-D-wind baseline with a 10 m-profile candidate, against RUNBOOK 5   (sources: C-3)
severity: minor / status: confirmed / lane: honesty
where: cafe/pm/whatif.py:861 (`b = base.get(vid)`), :884-897; cafe/pm/__main__.py:337-350; docs/RUNBOOK.md:175; only `flip_search` computes `base_2d` (whatif.py:797-804)
claim: `whatif --shift 6h` prints "uas: NO-GO (P(fail) 0.953) -> NO-GO (P(fail) 1.000) (0.922 to 1.000) [Stage 1, n = 32]". The baseline is the stage-1b 3-D-wind result; the candidate runs inside `wind_2d` (10 m profile). The same-model baseline in flip.json (`base_2d`) is 0.96875, so the CLI shows +0.047 where the same-model difference is +0.031.
check: read only. q16 stage1b summary has uas p_fail 0.953125 (n=64) and `wind3d_fraction` 0.625. `__main__.py:337-350` prints `base['p_fail']` with no wind-model note. RUNBOOK:175 says candidate and baseline alike use the 10 m profile; false for the CLI path. DECISIONS 187 covers the flip search and emulator variants only, so no row is contradicted. With no finished run `base` is empty and `measure()` runs under `wind_2d`, so the mix occurs only with a finished run.
fix: in `whatif.answer`, for a UAS with `hasattr(env, 'use_3d')` compute the baseline with `measure(...)` (2-D, same members as the candidate) and print that, keeping the 3-D value as a labelled secondary field. Cheaper: print the WIND_MODEL_2D note for UAS lines and say the baseline is the report's 3-D result. Regression test in tests/test_whatif.py with a fake env where `use_3d` changes p_fail. Cost: one extra Stage-1 batch per changed UAS, charged to the budget. Amend DECISIONS 187; fix RUNBOOK:175 if only the note is added.
sources: C-3

### M-3. The glider fix table offers dives of 712.5 m and 475 m, both deeper than the 330.6 m collapse depth the same page warns about   (sources: C-8)
severity: minor / status: confirmed / lane: honesty
where: cafe/pm/whatif.py:679-680 (duty candidates 0.75, 0.5), :262 (wording); cafe/pm/report.py:462-482 (`_hull_warning`), :552, :1446, :1462
claim: q16 glider_eq carries a hull warning (950 m ordered, 330.6 m collapse) while the fix table lists "dive 25 % shallower (950 m to 712.5 m)" and "dive 50 % ... 475 m" with no note. Both rows are "not evaluated" in q16.
check: read code and q16 report.json. No hull check in whatif.py. No candidate can reach the collapse depth (duty about 0.35 or less is needed, and DUTIES has 0.75 and 0.5). Slocum glider_2n (500 m ordered, collapse 654.6 m) has no problem. DECISIONS 842 says the warning does not cap or change the verdict; a note on a fix row caps nothing. Latent: once such a candidate evaluates to GO the table would offer a depth the page's own warning says the hull cannot fly.
fix: factor one helper taking a depth out of `_hull_warning`; in `whatif.candidates` add a `hull_note` to each dive candidate deeper than the collapse depth ("deeper than the assumed hull's collapse depth 330.6 m: cannot fly it"), and render it in the fix table and best-row sentence. Do not cap or drop the candidate. Test: ordered 950 m gives notes for 712.5 and 475, none for the Slocum case; a missing collapse figure says the check was not made. Could break: the report.json schema (new key) and any hash of the `change` text.
sources: C-8

### M-4. A required-sample median of 18.5 is printed as 18   (sources: C-6)
severity: minor / status: partly / lane: statistics
where: cafe/pm/stage1.py:807 (`int(np.median(...))`); cafe/pm/report.py:683-690
claim: `np.median(need_count)` for glider_eq-ship-acoustic is said to be 18.5; the page prints "decided on 18 samples (the median ...); one missed sample is 0.05556".
check: the code defect is real: `int()` truncates an even-count half-integer median and feeds both `granularity_ok` and the printed figure. The 18.5 for q16 is unverified (no res.pkl or per-member array locally, no orca rerun). The verdict does not change here: `granularity_ok` holds at 18 and 18.5. No DECISIONS row requires truncation (214, 283 do not). A median of 0.5 truncates to 0 and sets `granularity_ok` False (not reachable in q16, not tested).
fix: `nc = float(np.median(...))` at stage1.py:807 and let `_granularity` print a .5; one regression test with need_count [15,22,18,19] expecting 18.5 and 1/18.5. The float can only flip a borderline link from not-ok to ok. Old summaries store an int and stay compatible; check that no golden compares this field.
sources: C-6

### M-5. The report never states the UAS scrubbed launches, and a scrubbed day is not a failure   (sources: C-7)
severity: minor / status: confirmed / lane: honesty
where: cafe/pm/stage1.py:402-416, :787-793; cafe/pm/report.py (`_uas_html`, ~1395-1425; no mention of "scrub")
claim: q16_mission.json uas.scrubbed is 3 of 384 launches (members 22, 28, 60; all fail anyway). The UAS section prints "share of the flown sorties ... 0.4882" (381 flown) and no scrub count.
check: `grep -c -i scrub` is 0 in report.py and in q16 index.html. Only an all-scrubbed member is failed (`n_flown == 0`). summary.json carries no scrub count. DECISIONS 60 says a scrubbed sortie is "a failure of the mission, not a pass", yet a partly scrubbed member passes; rows 237 and 249 do not address it. No row forbids reporting the count. Latent: no q16 number is wrong.
fix: add `scrub = {launches, scrubbed, members_partly_scrubbed, members_all_scrubbed}` to `vehicles.uas` in `summarize` and print one sentence in `_uas_html`; old summaries without the key must still render. Regression test in tests/test_report.py (new file, see Batches). Add a ledger path for the new number. Do not change the verdict rule; a lab question on how many delivered profiles a member needs belongs in QUESTIONS_FOR_LAB.md.
sources: C-7

### M-6. Default RF sensitivity is the lowest-air-rate datasheet value; the air rate is not marked assumed nor asked of the lab   (sources: B-1)
severity: minor / status: partly / lane: physics, honesty
where: platforms/radios.yaml:10 (`rx_sens_dbm` -121, "low air rate only"); platforms/quad_uas.yaml:131; missions/tepex_c_demo.yaml:46; cafe/pm/physics/comms.py:167
claim: radios.yaml also has rfd900x_fast at -105 dBm. The printed usv-uas-rf margin (median 16.14 dB, 1,762 in-horizon margins) is the best case of one radio setting; subtracting 16 dB leaves 48.8 % below 16 dB and halves the mean working fraction (0.109 to 0.055).
check: the -121 choice is the spec (BRIEF:143, DECISIONS 65, PHYSICS:804). The median 16.144 matches q16 summary.json:623. No mention of the air rate in the q16 report, credibility.html or json, and no air-rate question in QUESTIONS_FOR_LAB.md. The 48.8 % and 0.109 to 0.055 figures were not recomputed (no res.pkl locally). The NO-GO is beyond-horizon driven (64 of 64) and does not move.
fix: wrap `rx_sens_dbm` of rfd900x (and rate-dependent entries) as `{value, unit, assumed: true, why, replace_with}` in radios.yaml, read `.value` in comms.py and stage1, add a QUESTIONS_FOR_LAB sub-item with default -121, and one test that the key is flagged assumed and appears on credibility.html. Risks: assumed/used counts (268 of 283, pedigree 69 of 233) move by one or two; tests that read `r["rx_sens_dbm"]` as a float (the row 279 table test) need updating; hash pins in tests/test_ledger.py if the file bytes feed them. No flown number moves. Amend DECISIONS 65.
sources: B-1

### M-7. Nothing checks the ocean current at EUC depths against the moorings, and CREDIBILITY has no limitation saying so   (sources: B-2)
severity: minor / status: partly / lane: data, honesty
where: cafe/pm/pipeline.py:~925 (`_tao`: wind and SST only); cafe/pm/env/tao.py:43 (`VARS`); config/perturbations.yaml:23-36; docs/CREDIBILITY.md
claim: GOFS window means at 0N 170W give surface u 0.10 and u 0.65 m/s at 125 m; no ADCP is ingested; `current_speed_scale` (sigma 0.30, BRIEF 2.5 literature value) decides the one MARGINAL verdict (glider_eq 18/64) and nothing compares currents with in-situ data.
check: partly. Read: `tao.VARS` is WIND/SST/AIRT/RH, `_tao` passes wind and SST only, CREDIBILITY.md has no current-skill limitation, the prior is listed as "prior" on credibility.html, BRIEF:262 defaults "TAO only", so it is a brief-level choice. Not verified: the orca profile numbers and the AUC values 0.51/0.72. q16 report.json glider_eq names no driver (`sensitivity.param` None). Not in the PROMPT known list.
fix: add an L-row to the limitations table in cafe/pm/credibility.py and docs/CREDIBILITY.md: ocean currents at all depths are HYCOM/GOFS with the BRIEF 2.5 prior and no in-situ comparison (wind and SST only are checked). The Validation factor cites a list of L-ids and tests pin the counts, so the new row goes into those lists and tests. New DECISIONS row and CHANGELOG line. The larger fix (ingest TAO/RAMA ADCP and fit the prior) is optional. Sibling gaps (wave_dir, hs_scale, T/S profiles) can take one row each.
sources: B-2

### M-8. Glider worst-window and "forcing at windows" use surface current, which the glider sees 2.3 % of the time   (sources: B-3)
severity: minor / status: partly / lane: physics, documentation
where: cafe/pm/pipeline.py:1287 (CRITERION glider), :1344-1348; cafe/pm/report.py:73, :913, :1597-1605
claim: report.json `forcing_at_windows.glider_eq` gives "surface current speed" 0.449 m/s at 2023-03-05 09:00Z; mean `surfaced` is 0.023 for glider_eq (0.082 for glider_2n); station loss follows the depth-averaged flow.
check: the label is accurate ("surface current"), and the page already says the window is not the instant a member failed (DECISIONS 219, 89). BRIEF 2.6 says "max current" with no depth. The 2.3 % holds (0.0232); the GOFS depth figures were not rechecked, and which flow stage-3 LES uses was not checked. The weakness is a possible misreading, not a wrong number.
fix: option A (changes no number): extend the report.py:1597 sentence for gliders with the surfaced fraction and that station loss follows the depth-averaged flow. Option B (physics, amends 89 and 219): rank glider windows by the depth-mean current over 0..dive_depth and set CRITERION and FORCING together; it changes which stage-3 windows run and moves the refit and Stage-1' numbers. Take option A in this round; option B needs an owner decision.
sources: B-3

### M-9. The Iridium link cannot fail by construction and no physical input reaches it   (sources: B-4)
severity: minor / status: partly / lane: physics, honesty
where: cafe/pm/stage1.py:612-625; cafe/pm/physics/comms.py:162-164; platforms/radios.yaml:44-45; cafe/pm/physics/usv.py:132 (`OPTIONAL`, `iridium_antenna_height_m` read by no code)
claim: per-sample success is 1 - 0.05^3 = 0.999875 and 865 independent samples per member need 0.95, so P(fail) is below 1e-90; q16 usv-shore-iridium prints "GO, P(fail) 0 (0 of 64)". No Hs, wind, heel, antenna height or position enters.
check: partly. The numbers are right and the repo discloses the limit (DECISIONS 66 "all of these are assumed", PHYSICS 12.3, PHYSICS:851 "a binomial identity of the assumed numbers"; radios.yaml marks p_success and max_attempts assumed). The report's method line says "no range dependence" but nothing next to the verdict says it is independent of sea state. Not a hidden defect.
fix: no code change is justified without SBDIX data. Optionally print, next to any Iridium verdict in report.py, that the result restates the assumed per-attempt success and is independent of weather and geometry; test that the sentence appears whenever the mission has an Iridium link. A physical coupling would be another assumed number and would need a new DECISIONS row.
sources: B-4

### M-10. USV energy has no sampled input and no reported margin, so its 64 members are one sample   (sources: B-5)
severity: minor / status: confirmed / lane: statistics, physics
where: cafe/pm/physics/usv.py:667-672; cafe/pm/stage1.py:45 (`ACTS` usv = `usv_vpp_bias` only); cafe/pm/env/perturb.py:31, :219; cafe/pm/env/environment.py:253; config/assumptions.yaml `env.sigma.swdown_frac`; platforms/saildrone_explorer.yaml:80
claim: `soc' = clip(soc + (0.20*2.0 m2*SWDOWN - 80 W)dt)` with WRF SWDOWN unperturbed and no battery or solar scale for the USV: every member sees the same insolation. The balance is near neutral (0.4*200 W/m2 = 80 W). q16 fail.battery is 0/64, one deterministic outcome, and no SOC minimum is reported (the USV margin is cross-track error).
check: read only. `swdown_frac` is used nowhere else (DECISIONS 717: nothing computes with it); air fields pass through `perturb`. Not a wrong count in q16 (battery mode 0), but a Wilson interval on battery treats members as independent with no energy uncertainty. No DECISIONS row forbids the fix; 356 and 717 are compatible.
fix: add a USV energy scale column (lognormal on `solar_eff*SWDOWN`, sigma from `env.sigma.swdown_frac`) in perturbations.yaml, list usv for it in `stage1.ACTS` and apply it at usv.py:670; report the minimum SOC as a USV margin. If deferred, add a CREDIBILITY limitation line saying the USV battery verdict is one deterministic outcome. Test: members with different scales give a different minimum SOC. Risks: `sampling.REQUIRED` (row 774), the class-prior table (row 745), a new Sobol/EASI column (row 211); demo numbers move only if the battery flag fires.
sources: B-5

### M-11. Link positions are interpolated in raw longitude across 180 deg   (sources: B-6)
severity: minor / status: confirmed / lane: robustness
where: cafe/pm/stage1.py:512-515 (`_pos`, `np.interp` on lon)
claim: records at lon 179.99, -179.99, -179.97 (t = 0, 600, 1200) and a ship at -179.95: the interpolated lon at t=300 is 0.0 and the distance to the ship is 20,009,527 m (6,672 and 4,448 m at the records).
check: ran on orca at af880ee: interpolated lon [179.99, 2.8e-14, -179.99], `_dist` [6671.7, 20009527, 4447.8] m, exactly as claimed. For a `uas_airborne` link the grid is unioned with the 30 s sortie grid, so a vehicle crossing 180 deg during a sortie gets a 20,000 km range (acoustic: out_of_range; RF: beyond_horizon) and wind/Hs/SSP are read at lon 0. Other links sample on the 10 min grid, where records fall exactly on the grid. q16 has no track near 180, so no q16 number moves. Other lon handling (`_dist`, `_mid`, `path_speed`, `report._unwrap`, `cv.lon_median`) already wraps; `_pos` is the only raw-lon interpolation. DECISIONS 245, 216, 474, 537 say go the short way.
fix: in `_pos.g` only: unwrap each member's lon column before `np.interp`, then re-wrap to [-180, 180) (reuse `report._unwrap` or a `cv` helper). Regression test: the repro, asserting lon about 180 and distance about 5.6 km, plus a no-wrap control. A DECISIONS row and a CHANGELOG line.
sources: B-6

### M-12. A glider surfacing (490 s) is shorter than the 600 s record grid, so some surfacings are never judged by links   (sources: B-7)
severity: minor / status: not_confirmed / lane: numerics
where: cafe/pm/physics/glider.py:339, :443, :481-497, :518-520; cafe/pm/stage1.py:39, :78-86, :583-586
claim: surf_s = 120 + 250 + 120 = 490 s against a 600 s grid, so 18 % of surfacings would hold no record.
check: not confirmed, by reading. The simulator steps at 60 s and records the phase at the end of every step; a surfacing is recorded as 1 + 9 = 10 consecutive SURF steps (600 s), and `_record_grid` keeps every 10th step, so every surfacing holds exactly one grid record whatever the phase. need_count of 14-24 per member for about 18 apogees agrees. Latent only: the guarantee holds while ceil(surf_s/60)+1 >= 10, i.e. surf_s > 480 s; a platform with surf_s <= 480 would lose surfacings with probability 1/10 per 60 s short of 600. No DECISIONS row covers the edge.
fix: none needed for the demo. Optional hardening: a check or warning at load when ceil(surf_s/DT_VEHICLE)+1 < REC_S/DT_VEHICLE, and a test with surf_s = 440 s that counts records per surfacing (and one for the demo's exactly 1).
sources: B-7

### M-13. RF wave height is taken at the two link ends, not at the specular point   (sources: B-8)
severity: minor / status: partly / lane: physics
where: cafe/pm/stage1.py:262-280 (`_link_hs`), :643-644; cafe/pm/physics/comms.py:74 (`kerr_reflection` returns R1, unused for the Hs query)
claim: for USV 2.2 m, UAS 108 m, d 30 km the specular point is 0.6 km from the USV; the code evaluates Hs at the USV and at the UAS ground position and takes the lower margin.
check: partly. The code is as described but documented: DECISIONS 834 ("Hs at the two ends is still only a proxy for Hs at the specular point"), 651 the same. The "up to 20 dB" is the null-depth difference between Hs 0 and 3 m, not the difference between the two ends of one link. The min of the two ends is a deliberate order-independent bracket. Round 15 measured the effect on the demo at at most 0.000588 dB; the usv-uas-rf NO-GO (89 % beyond horizon) does not move. Not run.
fix: preferred: document only. State in PHYSICS 12.1 and CREDIBILITY that Hs is the end-point bracket. The code option (compute R1 with `kerr_reflection`, interpolate along A-B, call `env.waves` once there, replace the `np.minimum` pair) would break tests/test_stage1.py r12_m11 and tests/test_round15_a.py m3, change `hs_filled`, and amend rows 651 and 834; do it only for a mission with strong along-path Hs gradients.
sources: B-8

### M-14. Near the horizon the RF model is 7-12 dB more optimistic than smooth-earth diffraction; "conservative by construction" is not backed; k fixed at 4/3   (sources: B-9)
severity: minor / status: confirmed / lane: physics, documentation
where: cafe/pm/physics/comms.py `two_ray_loss_db` (docstring, transition zone), `rf_margin` (cliff to NO_LINK_DB at `radio_horizon_km`), `A_EFF`; DECISIONS 244, 652; docs/PHYSICS.md ~801
claim: `rf_margin(0.999*H, ...)` is 11.9 / 9.1 / 7.0 dB for 2.2/108.1 m (H 48.9 km), 2.2/18.1 (23.6 km), 2.2/8.1 (17.8 km); ITU-R P.526 smooth-earth diffraction gives 0.1 and 2.2 dB at the first two horizons, about -5 dB per 5 km beyond.
check: ran on orca at af880ee: margins 11.9 / 9.1 / 7.0 dB and loss at the horizon 140.1 / 142.9 / 145.0 dB; the verifier's own P.526 code (k 4/3, 915 MHz, beta 1) gives about 151.8 / 150.2 / 151.2 dB, so the model is 11.7 / 7.3 / 6.2 dB more optimistic; also optimistic at 0.8H and 0.95H, with the gap growing toward H. The code takes max(curved, plane earth), conservative only against curved-with-D, not against diffraction. DECISIONS 244 repeats "conservative by construction"; PHYSICS ~801 admits P.526 is not modelled yet calls the larger-of rule conservative. No demo verdict moves (about 89 % of needed samples are far beyond the horizon). Caveat: the hand-coded P.526 should be re-derived before being acted on.
fix: minimum (this round): reword the docstring, DECISIONS 244 and PHYSICS to say the stand-in is conservative only against the curved-with-D loss and is 6-12 dB optimistic against P.526 near the horizon, and that k = 4/3 is fixed. Better (owner decision): add the P.526 smooth-earth field inside `two_ray_loss_db` between psi_critical and the horizon (take the larger loss), optionally continued beyond the horizon in place of the cliff. That changes printed margins, goldens and parameter-file hashes (like the Fresnel option in row 652) and could flip links near the horizon; test rf_margin at 0.999*H at or below the P.526 margin.
sources: B-9

### M-15. Limitation L19 states the wind prior as a boundary estimate of 0.113 m/s; this run fitted 0.5689 m/s from 14 moorings   (sources: C-4)
severity: minor / status: confirmed / lane: documentation
where: cafe/pm/credibility.py:68-72 (L19); docs/CREDIBILITY.md:145; tests/test_credibility.py:468
claim: credibility.html L19: "boundary moment estimate ... q5 11 moorings gave 0.113 m/s, 95 % upper bound about 0.5 m/s". priors_fitted.json holds 0.5689 (interior) with `value_hi95` 0.9572 over 14 moorings.
check: read and compared with the stored q16 output; the text is literally true of q5 but stale and present-tense. `fit_wind_error`'s docstring records both pairs. DECISIONS 589 says the quoting documents give the 14-mooring fit; true for the docs state column, not for the L19 claim text the report prints. The fit itself and the printed wind-prior line are right. No other run-specific number is hard-coded in LIMITATIONS.
fix: edit the L19 text once in credibility.py (state the property that always holds: between-mooring spread less sampling variance plus the uncertainty of the mean, from one 6-day regime; q5 gave 0.113, q10lb and later 0.569 with bound 0.957, depends on one mooring), then docs/CREDIBILITY.md:145 and the pin at tests/test_credibility.py:468. Better: build the sentence at render time from priors_fitted.json (needs a fallback for a run with no fit). Amend DECISIONS 285 and 589. No level moves.
sources: C-4

### M-16. "USV speed factor is sampled within +-1.4 % of the unbiased polar speed" reads as a speed near the polar's   (sources: C-5)
severity: minor / status: confirmed / lane: honesty
where: cafe/pm/credibility.py:167-175 (`usv_speed_sampling`); callers cafe/pm/report.py:1253-1255 (`_usv_bias_html`), cafe/pm/credibility.py:799; docs/CREDIBILITY.md:73; tests/test_report.py:2165, 2172; tests/test_credibility.py:1181
claim: `usv_vpp_bias` is uniform on [-0.2565, -0.228] (centre -0.2422), so the USV flies 23 to 26 % below the polar; the sentence gives only the half-width 0.0143 and "+-1.9 % of the speed flown".
check: read the code and the q16 report text. Read literally the phrase is false: the factor is 1 + bias in [0.7435, 0.772]. The centre appears nowhere on the USV card or the credibility page, only in perturbations.yaml:78, PHYSICS:577 and 699 and a provenance "why". The verdict numbers are right.
fix: in `usv_speed_sampling()` print the centre and direction ("sampled uniformly 23 to 26 % below the unbiased polar speed (centre -24.2 %, half-width +-1.4 %, sd 0.8 %; +-1.9 % of the speed flown)"); all three callers change together. Update the pinned strings in tests/test_report.py:2172, tests/test_credibility.py:1181 and docs/CREDIBILITY.md:73; handle "below/above" for a prior that is positive or straddles zero. Test: the sentence contains the centre and the direction. DEMO_DIGEST is unaffected.
sources: C-5

### M-17. The V&V 20 summary counts judged and not-judged rows on different bases   (sources: C-9)
severity: minor / status: confirmed / lane: documentation
where: cafe/pm/credibility.py:751-753 (evidence string), :322, :345, :758-760
claim: "4 comparison(s) ran, 4 with all uncertainty terms, 1 with |E| <= U_val, 3 with U_val below 50% ..., 3 not judged": all four rows have |E| < U_val, the "1" counts only the judged row (validated is None for not-judged rows) and the "3" includes two not-judged rows (`informative` is set before the judged check).
check: read the code and the stored q16 credibility.json/html: confirmed as stated. Validation stays at level 2 either way; the per-row table and the level-3 rule are correct.
fix: define `judged` before the evidence string and count validated and informative over `judged` ("1 of 1 judged with |E| <= U_val, 1 of 1 judged with U_val below 50 %, 3 not judged"). Test in tests/test_credibility.py with one judged and two not-judged rows; grep tests for the old wording. Note the amendment on DECISIONS 345.
sources: C-9

### M-18. Four sites of round 16's store lock, and its release, are not held by any test   (sources: A-1)
severity: minor / status: confirmed / lane: robustness (tests)
where: cafe/pm/env/remote.py:239 (`held.discard(path)`); cafe/pm/pipeline.py:184 (`Context.env`); cafe/pm/env/surface.py:134; cafe/pm/audit.py:90
claim: with `held.discard(path)` replaced by `pass` 4 tests pass (the thread keeps the path, so its next `store_lock` of that cache takes no flock); a null context substituted for the lock at pipeline.py:184, surface.py:134 or audit.py:90 leaves every test green. The two new pipeline tests kill only the edits at pipeline.py:1030 and :1051.
check: ran all four edits on orca from a detached worktree at af880ee; none failed a test. The pipeline r16 tests go through `_derived_record` and `_derived_current`; nothing drives the lock around `surface.build`'s write, `Context.env` or the audit tree hash. The code is correct as shipped. Siblings not mutated: pipeline.py:1090, surface.py:66 and :226.
fix: tests only (tests/test_remote.py, test_pipeline.py, test_audit.py): after a `with remote.store_lock(p)` block ends, a flock taken by another descriptor must succeed and a fresh block must lock afresh; for `surface.build`, `Context.env` and `audit._tree`, hold `store_lock` from a second thread, start the call, and assert it waits until release (the pattern of test_r16_pa_a_run_that_checks_the_layer...). Mutate the three siblings too and check DECISIONS 883 against the list. Accept the wait(0.4)-style timing the existing tests already accept.
sources: A-1

### M-19. RUNBOOK still says a different mission adds points to an emulator scope   (sources: A-2)
severity: minor / status: confirmed / lane: documentation
where: docs/RUNBOOK.md:181 (against :178 and DECISIONS 882); cafe/pm/whatif.py:562-566
claim: RUNBOOK:178 says adding points by running other missions does not help; line 181 says "new points come from a different --seed, a different mission, or a bigger budget".
check: `whatif.fit_class` keeps only rows with the run's `mission_hash`; another mission's rows land in `other_mission_rows` and add nothing. q16 holdout.json for glider_eq: rows 7, points 7, other_mission_rows 0, left_out_rows 75, trained False. No other copy of the stale advice in cafe/pm/*.py, docs/*.md, HANDOFF.md or STATUS.md. Not in the PROMPT known list.
fix: edit docs/RUNBOOK.md:181 to "new points come from a different --seed or a bigger budget", optionally noting that another mission's rows stay in the table but are left out. CHANGELOG line. Add a docs test only if one already guards RUNBOOK sentences.
sources: A-2

### M-20. `fea.hull_elements_along` returns a number PyYAML would not, for two layouts   (sources: A-3)
severity: minor / status: confirmed / lane: robustness
where: cafe/fea.py:73 (`if n > indent[0]: continue`), :78, :87 (`\s` and `.strip()` match U+00A0); tests/test_stage3.py:985-1000; DECISIONS 874
claim: `value: 70` followed by a deeper line `    more` returns 70 where `yaml.safe_load` gives '70 more' (also with 3 or 5 spaces of indent); `value: 70` followed by U+00A0 returns 70 where PyYAML gives '70\xa0'. The docstring says the reader must never return a number PyYAML would not.
check: the verifier exec'd the real text of fea.py against temp files and compared with `yaml.safe_load` (laptop, strict stripped; orca not used): the cases above reproduce; controls agree (a deeper `# c` comment, a continuation on `unit`). The pipeline reads the same key with PyYAML (pipeline_windows.py:423), so after such a hand edit the app meshes the hull at 70 while the pipeline gets text, and the two-collapse-depths problem returns. Only a hand edit of config/assumptions.yaml with an odd layout triggers it; the shipped file is plain. Row 874 is wrong for the `value` child. No other hand YAML reader in cafe/.
fix: in `fea.hull_elements_along` (the only reader): refuse any deeper non-comment line that directly follows the `value:` line, and use `.strip(" \t")` and `[ \t]` instead of `\s`/`.strip()` so U+00A0 fails the whole-number match. Block-scalar and nested-mapping text under other children stays skipped, so the existing tests keep passing. Regression tests: parametrize rows in test_r15_l0_4_... (continuation at 4 and 5 spaces, NBSP, each "refuse"). Amend row 874. Other line-break characters (\x0b, \x0c, \x85) are not covered.
sources: A-3

### M-21. Three branches of cafe/atomic.py that rows 872 and 880 describe are untested   (sources: A-4)
severity: minor / status: partly / lane: robustness (tests)
where: cafe/atomic.py:71 (`'xb'`); :49 (`os.fchmod`); :35 (`is_symlink`)
claim: three single edits survive: `'xb'` to `'wb'`, `fchmod` to `pass`, `elif p.is_symlink()` to `elif False`.
check: partly. Only the `'xb'` mutant is real. The reviewer's `-k` filters deselected the tests that kill the other two: tests/test_round15_a.py:62-73 and tests/test_config.py:1213-1225 assert the final mode (a 0o664 file rewritten ends 0o600 under the mutant, so they fail), and test_a_symbolic_link_at_the_target_is_refused... (test_round15_a.py:76-96) fails under the `elif False` mutant. Not reachable in practice: a collision of the 48-bit random name.
fix: one test in tests/test_round16_pb.py: monkeypatch `atomic.tmp_name` to return an existing file and assert `write_with` raises `FileExistsError` and leaves that file and the target untouched. Items 2 and 3 need nothing.
sources: A-4

### M-22. Six edits of round 15's fixes survive the tests that name them   (sources: A-5)
severity: minor / status: confirmed / lane: robustness (tests)
where: cafe/pm/stage1.py:277 and :166; cafe/pm/env/orca.py:252; cafe/pm/whatif.py:193 and :196; cafe/reach.py:113
claim: (a) the `np.where(isfinite...)` guard dropped at stage1.py:277 (row 834); (b) `len(v) == n` replaced by True at orca.py:252 (836); (c) `abs(dlon) >= width` to `>` at whatif.py:196 (860); (d) `0.0 < duty` to `0.0 <= duty` at whatif.py:193 (861); (e) `np.linspace(top, bottom, 6)` to 5 at reach.py:113; (f) `first = slot - every*floor(...)` to `first = slot` at stage1.py:166 (835). All pass the tests that name them.
check: ran all six on orca (pytest rc 0 each). Corrections: DECISIONS 870 does not say that n = 6 is pinned (it lists six other killed mutants); (e) is partly an equivalent mutant for the test's fixture, because DepthEnv in test_reach.py:428 is linear in depth; (f) differs only for a sub-daily period; (d) with duty 0 divides by zero in `_duty_days`, read, not run. Code is correct as shipped. Siblings not mutated: `orca.real_numbers` callers in tao.py:212, :216 and hycom.py:435.
fix: tests only, each checked failing on the mutant and passing on the control: (a) a `_link_hs` case with a NaN position; (b) `real_numbers` and `manifest_shape` with 3- and 5-number boxes; (c) dlon equal to the box width; (d) duty 0.0 and -0.5; (e) a quadratic-profile DepthEnv; (f) `launch_times` with every_days=0.5.
sources: A-5

### M-23. cfd.cached keys on mesh bytes and call parameters only, so a result outlives the solver settings that made it   (sources: D-1)
severity: minor / status: confirmed / lane: reproducibility
where: cafe/cfd.py:35-46 (key); callers cafe/hangar.py:294, 300, 314 and cafe/_seed.py:20
claim: after `cfd.FS_LTS` and `EXT_SNAPPY` are changed, the same `cached(("external","water",1.5), stl, ...)` call prints "CFD: reusing an identical earlier run" and returns the first result; compute ran once.
check: ran locally with numpy and trimesh stubbed, against a scratch cache dir (the logic is pure Python): reproduced. The key is sha1(stl bytes + json of the key) and nothing else (no recipe, OpenFOAM version, CAFE_NPROC). `receipts.app_digest()` hashes cafe/*.py but only for stored receipts. No pm path calls `cfd.cached`, so the pm demo is unaffected. Rows 815/817 cover only the write path. The app's other caches were not traced.
fix: in `cfd.cached`, add a recipe fingerprint to the hash input (a hash of the settings constants and the OpenFOAM version string, not the whole file, so a comment edit does not invalidate hours of CFD). Do not key on CAFE_NPROC; record it in the cached JSON. `_seed.py` seeds old validation runs: they stay valid only if seeding runs from the same recipe. Test: compute once, patch `FS_LTS`, call again, assert compute runs twice. New DECISIONS row.
sources: D-1

### M-24. Two ingests of one mission destroy each other's ocean store and GEBCO cut (fixed temp names, no lock)   (sources: D-2)
severity: minor / status: confirmed / lane: robustness
where: cafe/pm/env/hycom.py:225-237 (`write_store`: fixed `<out>.tmp`, rmtree first), :290-326 (`out + ".part"`); cafe/pm/env/bathy.py:136-139 (`fetch_gebco`: fixed `.part.npz`), :247; cafe/pm/env/orca.py:232 (`_save`: fixed `.tmp.npz`); cafe/pm/pipeline.py:440- (`s_ingest`, no lock)
claim: a second `write_store` for the same out while the first runs makes the first die with `ValueError: append_dim='time' does not match any existing dataset dimensions {}` and leaves `out.zarr.tmp` beside the other run's store. Two processes writing the same `.part.npz` truncate each other, `os.replace` then fails or promotes a partial file.
check: the ocean-store race was run on orca at af880ee on the tests/fixtures/hycom store (3 steps) and reproduced as stated. The GEBCO race is read from the code, not reproduced; `_gebco_cached` refetches on a bad file, while `bathy.choose` can swallow the SHA error and fall back to the GOFS floor. DECISIONS 883 locks only derived.zarr. No printed number was shown to change; unusual use (concurrent same-mission ingests).
fix: in `pipeline.s_ingest`, wrap the fetch phase in `surface.store_lock(...)` per shared store (re-check the `_need` predicate inside the lock); the ocean-store and GEBCO locks live beside the stores in DATA, not in the mission cache, since both are shared across missions. Defence in depth: `cafe.atomic.tmp_name` for `write_store`, `fetch_gebco`, `orca._save` and the hycom `.part`. Log a waiting line; a lock on a non-writable DATA dir must degrade to unlocked as `store_lock` does. Test: two threads or processes on one path, as in test_r16_pa_*. Unique temps leave orphans after a kill (`is_junk` and `sync_filters` already ignore `*.tmp`).
sources: D-2

### M-25. A NaN VPP speed factor passes the positivity guard and becomes a NaN-position member with no failure mode   (sources: D-3)
severity: minor / status: confirmed / lane: robustness
where: cafe/pm/physics/usv.py:527-530 (`(self.fac <= 0).any()`), :493-497 (`draw_vpp_bias`, `np.clip` keeps NaN)
claim: `USVSim(..., perturb=dict(vpp_bias=np.array([0.0, np.nan, 0.0]))).run(3600, 60)` runs without error: final lon [-164.98, nan, -164.98]; `fail` has no True and `first` no finite entry, so the member is neither failed nor flagged `no_current_data`. `+inf` behaves the same.
check: ran on orca at af880ee, both cases reproduced. The only production caller (stage1.py:143) is fed a finite X and a `drag` from stage1.py:445; whether `drag` can be 0 or NaN there was not tested. The step-time guards flag only a non-finite environment value or start position. DECISIONS 770 says the factor is positive on every path; not true for NaN or inf.
fix: in `USVSim.__init__` replace the guard with `not (np.isfinite(self.fac) & (self.fac > 0)).all()` ("finite and > 0"); test beside tests/test_usv.py:1291 over nan, inf, -inf. Optionally flag a non-finite position as `no_current_data` at step time. Callers that catch ValueError should be checked. Wider sibling not checked: the glider and UAS sims have the same guard shape.
sources: D-3

### M-26. cafe/cfd.py hostile inputs: flat STL ends in OverflowError after the case dir is deleted; empty CAFE_NPROC kills the import; mistyped direction found after meshing   (sources: D-4)
severity: minor / status: partly / lane: robustness
where: cafe/cfd.py:226-234 (`external`: `rmtree(case)`, `hs`, `lvl`), :15 (`NPROC = int(os.environ.get('CAFE_NPROC','6'))`), :274-289 (`dvec` first called after meshing); cafe/pm/stage3/pipeline_windows.py:807 (`setdefault`)
claim: a zero-thickness box STL gives `OverflowError: cannot convert float infinity to integer`; `CAFE_NPROC= python -c 'import cafe.cfd'` gives `ValueError`; `python -m cafe.cfd external SAMPLE WORK +x,+q` builds the mesh and fails in `dvec`.
check: ran locally (trimesh 4.12.2; no OpenFOAM). (1) confirmed; `rmtree(case)` has already run, the case dir is derived scratch, and hangar wraps the call in `except Exception` (warning, falls back to estimates). (2) confirmed but a recorded non-fix: DECISIONS 569 and 663, HANDOFF:51 (open owner decision). (3) confirmed, reachable only through the cfd main. New sibling: `pipeline_windows.py:807` `setdefault` leaves an empty `CAFE_NPROC` in place, so the later import raises. `CAFE_NPROC=1` and `free_surface` were not run. Every path ends loudly; no wrong number.
fix: top of `cafe.cfd.external`, before `rmtree(case)`: validate every direction with `dvec(d)` and require `m.extents.min() > 0` (ValueError naming the file, "flat or empty mesh"); replace the bare `int` at line 15 with `par.env_count('CAFE_NPROC') or 6` after checking the import chain for a cycle (amends rows 569 and 663; `CAFE_NPROC=abc`, 0 and -3 become a ConfigError, per row 330); make pipeline_windows.py:807 set the variable when missing or empty. Tests: zero-thickness box leaves a pre-existing case dir intact; `CAFE_NPROC=''` gives NPROC 6; a bad label raises before any `sh()`. Do not use a relative thickness threshold (real foils).
sources: D-4

### M-27. comms edge inputs give a number where the input is meaningless: negative range, zero heights, NaN range, negative bytes   (sources: D-5)
severity: minor / status: partly / lane: robustness
where: cafe/pm/physics/comms.py:168 (`rf_margin` horizon test uses raw d, loss uses `max(d,1)`), :172-195 (`iridium_session`); cafe/pm/stage1.py:320 (UAS lost-link hook)
claim: `rf_margin(-3.0,18,10,0.5)` = +102.2 dB; `rf_margin(0,0,0,0)` = +119.1 dB; NaN range or height gives -200 (NO_LINK_DB), not NaN; `iridium_session(-5, rng, 3)` succeeds; `members=0` raises a reduction error.
check: read; not run (comms.py does not import on the laptop's Python 3.9). `stage1.evaluate_link` clamps d >= 1 and removes NaN, so no pipeline number moves; the only unguarded caller is the stage1.py:320 hook, where a NaN UAS state reads as link lost (conservative) and no path to a NaN UAS state was found. DECISIONS 167 is consistent with the proposed NaN contract. Latent.
fix: in `rf_margin` use `np.maximum(d, 1.0)` for the horizon test too and decide the NaN contract (raise, or return NaN); add `& np.isfinite(rel)` in the stage1.py:320 hook if a NaN state should not count as lost (owner decision); guard `iridium_session` (members >= 1, finite n_bytes >= 0). Returning NaN changes the contract `evaluate_link` relies on (`margin != NO_LINK_DB`) and must be checked against test_a_nan_position_is_not_a_moment_the_link_was_required.
sources: D-5

### M-28. `usv.tables(P, cache_dir)` writes its .npz in place; a cut file is unreadable and nothing recovers   (sources: D-6)
severity: minor / status: partly / lane: robustness
where: cafe/pm/physics/usv.py:458-475; tests/test_config.py:1330 (`BARE_COPIES["physics/usv.py"]`)
claim: a file `b'PK\x03\x04truncated'` as `usv_tables_<digest>.npz` makes every later `tables(P, dir)` raise `zipfile.BadZipFile`.
check: read; not run. The pipeline never passes `cache_dir` (USVSim calls `tables(P)`); the repo records the site as a deliberate exception in `BARE_COPIES`, and DECISIONS 880 covers only npz files the app reads back via `cafe.atomic.write_with`, so no row is contradicted. Other pm writers (bathy.py:138, orca.py:233) already write temp then replace. Latent.
fix: write via `cafe.atomic.write_with` in `usv.tables`; optionally wrap `np.load` in `try/except (BadZipFile, OSError, ValueError, KeyError)` and rebuild. Test: a cut file is rebuilt (physics coverage is 100 %, so the new branch needs it). Remove the BARE_COPIES entry, adjust the scan count, add a DECISIONS row and CHANGELOG line. Leaving it as is is also reasonable with zero callers.
sources: D-6

### M-29. `fly_sortie` accepts a turbulence series shorter than the longest flight it simulates and holds the last row   (sources: D-7)
severity: minor / status: confirmed / lane: physics
where: cafe/pm/physics/uas.py:629-630 (guard `duration_s + 60`), :642-643 (`t_max = duration_s*hard_stop_factor`), :477-478 (`turb[:, min(k, n-1)]`), :835-851 (`fly_sitl`, no guard); cafe/pm/stage1.py:224, 306, 335, 396; tests/test_uas.py:330-333
claim: a 1,260 s series passes the guard while a member that cannot get home flies to 1,920 s, and from 1,260 s on its turbulence is the last row held constant.
check: read only; the defect is fully determined by the lines. `stage1._uas_forcing` asks for `duration_s*hard_stop_factor + 60` = 1,980 s, so the pipeline is unaffected. No test covers a series between `duration+60` and `duration*factor+60`. The needed-length rule is written twice (guard and stage1) and `duration_s*hard_stop_factor` is recomputed by hand in four stage1 places.
fix: one helper `sortie_t_max(so)` in uas.py used by the `fly_sortie` guard (require `t_max + 60`), by `fly_sitl` (same guard against `max_s` if given) and by stage1 lines 224, 306, 335, 396. Test: a `duration_s + 60` series raises `ValueError` "turbulence series covers"; a `t_max + 60` series passes. Check the `fast_plat` test near test_uas.py:330 and any caller passing a short series. The `make_wind` docstring should say the hold applies only within the 60 s margin.
sources: D-7

---

## Root causes

Findings clustered by root cause; "place" is the one spot where the fix belongs, "siblings" are the other findings or sites with the same cause.

1. What-if compares unlike bases.
   - Place: `whatif.answer` and `stage1.run` (carry the full mission's priors into the solo run; measure the baseline under the candidate's wind model).
   - Findings: M-1 (draw columns; also the `--drop` sentence), M-2 (3-D baseline vs 10 m candidate).
   - Siblings: `measure`, `flip_search` and `run_variant` already pass the full mission's pri/marg and `base_2d`; the CLI path is the only one that does not.

2. A printed statement that omits or misstates the condition it holds under (hard-coded or truncated text).
   - Place: each text generator, once: `credibility.usv_speed_sampling` (M-16), the L19 text and evidence string in credibility.py (M-15, M-17, M-7 new L-row), `stage1.summarize` and `report._uas_html` (M-4, M-5), `report` fix table and forcing sentence (M-3, M-8), the verdict row for Iridium (M-9), docs (M-19, M-13, M-14 wording).
   - Findings: M-3, M-4, M-5, M-7, M-8, M-9, M-13, M-14, M-15, M-16, M-17, M-19, and M-6 (the air rate is not flagged assumed).
   - Siblings: every row needs its pinned test string updated in the same change (tests/test_report.py, tests/test_credibility.py).

3. Shared stores written under fixed names, in place, or keyed by inputs only.
   - Place: `cafe.atomic.tmp_name`/`write_with` for the writers (M-24, M-28); `surface.store_lock` in `pipeline.s_ingest` (M-24); the key in `cfd.cached` (M-23).
   - Siblings: orca `_save`, hycom `.part`, bathy `window_check.npz` (M-24); the app's other result caches were not traced (M-23).

4. Numeric inputs not validated at the function that consumes them (non-finite, flat, empty, too short, wrong shape).
   - Place: `USVSim.__init__` (M-25), `comms.rf_margin` and `iridium_session` (M-27), `cfd.external` and the `CAFE_NPROC` constant (M-26), `uas.fly_sortie`/`fly_sitl` with one `sortie_t_max` helper (M-29), `fea.hull_elements_along` (M-20).
   - Siblings: the glider and UAS sims have the same positive-only guard shape (M-25, not checked); `pipeline_windows.py:807` (M-26).

5. Geometry and RF approximations used beyond their range.
   - Place: `stage1._pos` unwrap (M-11); `comms.two_ray_loss_db` transition zone (M-14); `stage1._link_hs` (M-13); glider record stride vs `surf_s` (M-12, not confirmed, latent).
   - Siblings: all RF callers route through `rf_margin`/`two_ray_loss_db`; `_pos` is the only raw-lon interpolation.

6. An input class with no sampled uncertainty or no validation, disclosed only in prose.
   - Place: `perturbations.yaml` plus `stage1.ACTS` for the USV energy column (M-10); a limitations row for currents (M-7); `radios.yaml` for the air rate (M-6).
   - Siblings: the other never-validated forcing classes (waves, subsurface T/S).

7. Regression tests that name a fix but not its boundary.
   - Place: the test files only, no production change: M-18 (locks), M-21 (`xb`), M-22 (six boundaries).
   - Siblings: `real_numbers` callers in tao.py and hycom.py; the three unmutated `store_lock` sites.

---

## Batches

Six at most; four are used. No two batches share a file. Documents (DECISIONS.md, CHANGELOG.md, docs/*, QUESTIONS_FOR_LAB.md, STATUS.md) belong to batch D alone: the code batches hand D the rows and wording they need, and D runs last. New tests for batch A's report and credibility findings go in new test files (`tests/test_round16_report.py`, `tests/test_round16_a.py`), so they do not touch test_report.py or test_credibility.py, which batch B owns. Where a finding touches a file in two batches, it sits in the batch that holds the production code.

### Batch A: stage 1, link physics, what-if and report text
- findings: M-1, M-2, M-3, M-4, M-5, M-6, M-8, M-9, M-10, M-11, M-12, M-13, M-14, M-22, M-25, M-27, M-28, M-29
- files: cafe/pm/stage1.py, cafe/pm/whatif.py, cafe/pm/__main__.py, cafe/pm/report.py, cafe/pm/physics/comms.py, cafe/pm/physics/usv.py, cafe/pm/physics/uas.py, cafe/pm/physics/glider.py (M-12 hardening only), cafe/pm/env/perturb.py, cafe/pm/env/environment.py, config/perturbations.yaml, platforms/radios.yaml, platforms/quad_uas.yaml, platforms/saildrone_explorer.yaml, cafe/reach.py (read), cafe/pm/env/orca.py (read, M-22 is tests only), tests/test_whatif.py, tests/test_stage1.py, tests/test_usv.py, tests/test_uas.py, tests/test_comms.py, tests/test_reach.py, tests/test_round15_a.py, tests/test_config.py (BARE_COPIES for M-28), tests/test_ledger.py (M-6 hash pin), tests/test_round16_report.py (new), tests/test_round16_a.py (new)
- notes: M-3 and M-8 take the report-text option (no pipeline.py change, so no overlap with C); M-14 and M-13 in this round are wording only (hand-off to D), the P.526 code change needs an owner decision; M-6 relies on the credibility catalogue reading the `assumed` flag from the yaml, and needs no credibility.py edit (if it does, hand it to B). M-12 is not_confirmed: the optional hardening may be skipped. M-27 owner decision on the NaN contract before the stage1.py:320 edit.

### Batch B: credibility
- findings: M-7, M-15, M-16, M-17
- files: cafe/pm/credibility.py, tests/test_credibility.py, tests/test_report.py (pinned USV sentence at :2165/:2172 for M-16), cafe/pm/pipeline.py (read only for M-7)
- notes: M-16 fixes `usv_speed_sampling()` once for all three callers (report.py:1254 is read through, not edited, so no overlap with A); M-7 adds the L-row to the id lists the Validation factor cites. CREDIBILITY.md wording for M-7, M-15, M-16 goes to D.

### Batch C: stores, hostile inputs and test gaps outside the pipeline core
- findings: M-18, M-20, M-21, M-23, M-24, M-26
- files: cafe/pm/env/hycom.py, cafe/pm/env/bathy.py, cafe/pm/env/orca.py, cafe/pm/env/remote.py, cafe/pm/env/surface.py, cafe/pm/pipeline.py, cafe/pm/audit.py, cafe/atomic.py (read), cafe/cfd.py, cafe/fea.py, cafe/pm/stage3/pipeline_windows.py, cafe/pm/par.py, cafe/hangar.py (read), cafe/_seed.py (read), tests/test_remote.py, tests/test_pipeline.py, tests/test_audit.py, tests/test_stage3.py, tests/test_round16_pb.py, tests/test_cfd.py, tests/test_hycom.py, tests/test_bathy.py
- notes: M-21 and M-18 are tests only; M-24 owns pipeline.py (the window criterion of M-8 option B would also need it; not taken this round); M-23 hashes the settings constants, not the whole file.

### Batch D: documents (last)
- findings: M-19, plus the document edits handed over from M-6, M-7, M-8, M-9, M-13, M-14, M-15, M-16, M-17, M-20, M-23, M-26, M-1, M-2, M-5, M-10
- files: docs/RUNBOOK.md (:175 for M-2, :181 for M-19), docs/PHYSICS.md (12.1, 12.3, ~801, 804), docs/CREDIBILITY.md (:73, :145, a new L-row), docs/BRIEF.md (:143, read), DECISIONS.md, CHANGELOG.md, QUESTIONS_FOR_LAB.md (M-6 air rate with default -121; M-5 delivered profiles), STATUS.md, HANDOFF.md, review/orca/PROBLEMS.md
- notes: new DECISIONS rows are numbered after 883; amend existing rows in place and keep numbering (65, 187, 244, 285, 345, 589, 651, 652, 834, 842, 874, 882, 883, 569, 663); the M-1 PROBLEMS row is the one reviewer C did not add.

Coverage check: M-1 to M-29 each appear in exactly one batch's findings list (A: 18, B: 4, C: 6, D: 1 = 29).
