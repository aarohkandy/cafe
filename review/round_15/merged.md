# Round 15 merged findings (BRIEF 5.6 step 2)

Inputs: reviewer_a.md (7 findings), reviewer_b.md (4), reviewer_c.md (14), reviewer_d.md (15). Merged to 40 findings, M-1 .. M-40, from 40 source ids; no two reviewers filed the same defect, so each merged finding has one source. Every source id appears in exactly one merged finding (A-1..A-7, B-1..B-4, C-1..C-14, D-1..D-15).
Each finding was checked by an independent verifier against HEAD 01a39c0 (the q15 run is the demo at db2debd, which moved no verdict, count or array against q14), by reading the cited code and the q15 run files and, for most claims, by reproducing it on cafe-orca (proot, 2 CPUs) in a detached worktree and a private `pm_v15_*` directory (removed afterwards). Static, arithmetic and pure-text claims were checked by reading or locally on the laptop. The "check" lines are the verifiers' results; this merge re-ran nothing, and severity and status are the verifiers', not the reviewers'. Where a verifier corrected a figure, a line number, a lane or a scope, the check says so.
Not covered by any reviewer (their own lists, shortened):
- Reviewer A: 74 hand-made single-edit mutants run against the tests that name each fix (not the whole suite), about 40 unmutated baselines green; DECISIONS rows 762, 774, 782, 785, 787, 793, 799, 800, 801, 803, 804, 808 and the document-only rows were not mutated, the shell runners only at three edits; of 50 sampled DECISIONS rows 31 were checked against code or arithmetic and 19 read only for what the sentence says. No full demo, no stage-1/stage-3/CFD computation, no acceptance, no gate, no GPU, no Capytaine run; whatif only to see that it starts. Round 14's unread files (hangar.py beyond `check` and `bem`, the orca_* scripts, proot_suite.sh beyond `job()`) are still unread.
- Reviewer B: believable, no finding: USV speed (stw median 0.76 m/s, SOG 0.69, row 183), swept_off_track at 20 km (current-driven, not a guidance artefact), wing_stall_calm 38/64, the glider dive cycle and horizontal speed, Slocum energy, RF link range (geometry, disclosed), acoustic links (disclosed). Not done: Seaglider battery energy, wind3d and turbulence forcing of the UAS, the Iridium model, the stage-3 CFD inputs, the polar's upwind limit against Saildrone's, and a run of the quad itself in a headwind to check 12.6 m/s.
- Reviewer C: buckling-mode lobe counts on the glider hull; nest.py and wallmodel.py (outside scope); any CFD beyond reading; sphere/tube convergence at more than two meshes each; C-8 and C-9 are from reading and numbers only. The fea closed-form results are tabulated at the top of reviewer_c.md.
- Reviewer D: the hull loft (`build_hull`, `read_iges`, hydrostatics) beyond a read-through; no CFD or dtmb5415 run; the app's reach with real WRF/HYCOM data; stage1/emulator internals that whatif calls (`Emulator.fit`, holdout, conformal_rank, coverage_band); a real whatif CLI run (needs the 9 GB environment); `flip_search` and `measure` with a live emulator; subset simulation beyond Gaussian tails; `sequential.sprt_decide` (unused); `acceptance.py`'s use of `newcombe_diff`; whether the GCI-as-standard-uncertainty step in V&V 20 is right against the standard's text; CT_REF values not re-read at source.
INCIDENTS and side effects disclosed by the reviewers and verifiers (none repaired by this merge):
- Reviewer A: a probe (`whatif --run /nonexistent`) kept running on orca after the local shell was stopped and was ended by the exact pid of its wrapper; the shared emulator table was not touched (mtime before the runs). Worktree `cafe-rev15-a`, orca dirs `pm_rev15_a` to `pm_rev15_a9`, their `.pmx.job` markers and `rev15a_*` logs removed by exact name; no stash.
- Reviewer B: findings are in reviewer_b.md; scratch worktree and orca files removed (own names only).
- Reviewer D: worktree `cafe-rev15-d` and orca `pm_rev15_d`, its job marker and log removed; no Azure resource touched; no stash.
- Verifiers removed their own `pm_v15_*` directories, job markers and detached worktrees; the verifier of D-8 used only the laptop and left `scratchpad/d8.py`.

Severity: 0 critical, 2 major (M-1, M-2), 38 minor. Status: 25 confirmed, 13 partly (M-4, M-8, M-10, M-11, M-13, M-15, M-18, M-19, M-21, M-22, M-25, M-34, M-35), 2 not confirmed (M-12, M-38).

---

## Critical

None. No reviewer found one and no verifier raised one.

---


## Major


### M-1. An EMULATED verdict is read off the point estimate alone while Stage 1 and the baseline use the interval, and the flip search mixes the two   (sources: D-1)
severity: major / status: confirmed / lane: statistics
where: cafe/pm/emulator.py:260,336,349,353; cafe/pm/stats/intervals.py:105-107,117; cafe/pm/whatif.py:681-682,734-739,764-765,842-844
claim: `verdict_from_p(p)` is GO for every p <= 0.10 whatever the emulator's own 90% band lo..hi printed beside it; the baseline and every Stage-1 candidate use `intervals.verdict`, which also needs 1 - hi90 >= 0.75. One failure in 10 members: `verdict_from_p` GO, `verdict(1,10)` MARGINAL. A prediction 0.09 with band 0.00..0.40 prints GO. `flip_search` takes the minimum cost over about 18 candidates on point estimates (winner's curse, no multiplicity statement).
check: read the callers and ran the scalar rules on the laptop (`verdict_from_p(0.10)` GO, `verdict(1,10)` MARGINAL); the emulated path was not run and no orca job was started. Callers of `verdict_from_p`: `Emulator.query` (:260), `flip_search` (:336, :349, :353) and the pass-through in `whatif.emulate` and the flip candidates. Every other verdict (stage1.py:767/805/878, whatif.py:697, report.py:315) uses `intervals.verdict`. Latent in q15: `emulator/flip.json` shows `emulator: False` everywhere (fewer than 100 points per scope), so every answer was Stage 1. `whatif.py:764-765` takes the emulated winner with no Stage-1 confirmation. No DECISIONS row endorses the asymmetry (248 only makes ties boundary-inclusive for both).

fix: add one verdict function in `intervals.py` taking (p, lo, hi) of P(fail) and applying the same cut-offs, with the GO term read off hi <= 0.25; use it in `Emulator.query` and `flip_search` including the baseline, so `emulate` and `whatif` inherit it. Settle first, in a DECISIONS row citing 68, 248 and 399, whether the conformal band stands in for the Wilson bound. For the winner's curse require the winner's band inside the target region or confirm it with one Stage-1 run, and print the candidate count. Tests: p 0.09 band 0.00..0.40 is not GO; p 0.10 band 0..0.35 agrees with `verdict(1,10)`; a wide-band candidate no longer wins. Risk: fewer emulated GOs and flips, more fallback to Stage 1, borderline `base_verdict` changes, tests pinning `verdict_from_p`, an infinite band with few calibration points means nothing is GO (correct, say so).

sources: D-1


### M-2. `python -m cafe.pm.dtmb5415 report` prints `|E|<=U_val yes` for three rows whose finest grid has not converged   (sources: D-2)
severity: major / status: confirmed / lane: honesty
where: cafe/pm/dtmb5415.py:701-703 (`format_table(tabulate())`), 592-610, 646-650; cafe/pm/vv.py:171-190; DECISIONS 345, 402
claim: the stored v4 study has fine grid `converged=False` at Fr 0.20, 0.28 and 0.41, yet the last column of the report table is `yes` for all four speeds (|E|/U_val 0.02 at Fr 0.41). `receipts()` applies the not-judged rule, the printed table does not. All rows sit on the Fs=3 oscillating fallback.
check: ran `python -m cafe.pm.dtmb5415 report` on orca (proot, 2 CPUs, detached worktree at 01a39c0): four `yes`, while the receipt lines below the table say `|E| <= U_val is not judged: the finest grid has not converged` for Fr 0.20, 0.28 and 0.41. Fr 0.10 converges, so its `yes` is right. `vv.py:171-190` sets `validated = ratio <= 1.0` with no convergence input; only `receipts()` and `credibility.py:344-346` apply the rule. The report command is the only unguarded path (the only non-test caller of `format_table` is `main`). The output contradicts itself rather than hiding the status, which makes it borderline minor; kept major as a printed verdict the project's rule withholds. DECISIONS 345 and 402 require the fix.

fix: have the report path print `not judged` in the last column for rows whose finest-grid reasons are non-empty, from one helper shared with `receipts()` and `credibility._dtmb_rows` (for example `dtmb5415.not_judged(root)`), so the rule is not copied a third time. Keep `yes`/`no` for converged rows and for bare `vv.format_table` callers (`tests/test_vv.py:276-280`). Test: a stored fine run with `converged False`, `main(['report'])`, last column not `yes`. Do not make a `Vv20` field depend on convergence (`vv20_row` serves non-DTMB rows).

sources: D-2


---


## Minor


### M-3. `_link_hs` takes the larger Hs as 'the conservative one'; for the two-ray link that is the optimistic end   (sources: A-1)
severity: minor / status: confirmed / lane: physics / documentation
where: cafe/pm/stage1.py:262-275 and :638; DECISIONS row 651; CHANGELOG.md:692; cafe/pm/physics/comms.py:145-147
claim: a rougher sea fills the interference nulls, so the minimum margin rises with Hs; taking `np.maximum` of the two ends makes margin, frac and lost-link time optimistic by up to about 20 dB in a null, under a sentence saying the opposite.
check: ran `comms.rf_margin(d, ht, hr, hs, 'rfd900x')` on orca, 0.5 to 40 km: ht 15, hr 60: minimum margin for d <= 15 km is -1.4, 2.6, 9.8, 24.0, 31.8 dB at Hs 0, 0.2, 1, 3, 5 m; median unchanged (46.0 to 45.9); peaks fall the other way (72.0 to 66.3 dB). The reviewer's 3.1 dB at Hs 0 reproduces as -1.4 on a 5 m grid. Near-surface pairs barely move. Mutant `maximum` to `minimum` is killed, so the swap tests pin symmetry, not the reason. Row 651 records that no demo verdict or count moved (usv-uas-rf is NO-GO on the radio horizon). The acoustic `np.fmax` of winds (stage1.py:650) is correct and stays. Hs at the two ends is only a proxy for the specular point.

fix: fix in `_link_hs` only (single caller): `np.minimum` (calm end) or the mean, both symmetric so the R12 M-11 swap tests pass; correct the docstring, the row 651 sentence (amend it, new DECISIONS row, CHANGELOG line) and the stage1.py:638 comment. Test: unequal Hs, null geometry (ht 15, hr 60), margin equals `rf_margin` at the calm end's Hs; it fails under `maximum`. Re-run the demo and check usv-uas-rf and the UAS lost-link 0 of 64 do not change.

sources: A-1


### M-4. A UAS `every_days` that is not a whole number of days (1.5, 0.7) is accepted and the launch hour drifts with no warning   (sources: A-2)
severity: minor / status: partly / lane: robustness / documentation
where: cafe/pm/stage1.py:156-168 (`launch_times`); cafe/pm/config.py:587-589; docs/PHYSICS.md:751; cafe/pm/whatif.py:134-136
claim: for the ship at lon -165 over 6 days, every_days 1 gives local solar hour 14 on every sortie; 1.5 gives 14, 2, 14, 2; 0.7 gives 14, 6.8, 23.6, 16.4, 9.2, 2, 18.8, 11.6. Neither schema, loader nor PHYSICS says the hour drifts.
check: re-ran the body of `launch_times` with a pure numpy copy on the laptop; the numbers match. Partly: sub-daily periods are by design (DECISIONS 164, 195), and the claim that the report names the sorties 14:00 is not supported (`report.py` never mentions `local_solar_time`). What is missing is any statement that `local_solar_time` pins only the first launch. The what-if shift reaches the same schedule; only a whole-day shift is refused (195).

fix: documentation plus one warning, no behaviour change: say in PHYSICS.md:751 that `local_solar_time` fixes only the first launch; in `config.load_mission` next to the every_days check add a warning (not an error) when every_days >= 1 and not an integer, giving the first few local solar hours; sub-daily periods get the documentation note only. Test in `tests/test_config.py`. New DECISIONS row adding to 164 and 195. Do not refuse: it would break sub-daily missions. The schema description of every_days is not edited here (mission.json belongs to batch B).

sources: A-2


### M-5. Manifest and attribute shape checks accept NaN/inf (`orca.real_numbers`) and a JSON true (`_wrf_notes` DX, SST_UPDATE)   (sources: A-3)
severity: minor / status: confirmed / lane: robustness
where: cafe/pm/env/orca.py:247-249; cafe/pm/env/tao.py:211-212; cafe/pm/env/hycom.py:435; cafe/pm/env/environment.py:59-65
claim: `orca.real_numbers([nan, inf], 2)` is True; `tao.manifest_shape` with NaN times passes; `_wrf_notes({'DX': True})` prints `0.001 km`; `{'SST_UPDATE': True, 'DX': 12000}` prints `updated during the run: SST_UPDATE=1`. The M-22 family stops one value short; rows 768 and 819 say such values are not recorded.
check: read the code at HEAD (plain Python semantics, not run on orca). `real_numbers` rejects bool but not NaN or inf; `float(True)` is 1.0. Callers: orca, tao and hycom `manifest_shape`. Manifests are written with `json.dumps` without `allow_nan=False`. NaN times and hours fail the later comparisons (benign, honest); an infinite box or hours claims to cover anything, so a wrong cache is reused. A boolean DX needs a hand-edited Zarr attribute. No demo number moves. Same idiom without bool and finite checks elsewhere (report.py:233/241/249/385/390, credibility.py:686/691, pipeline.py:721) is a different, less reachable defect.

fix: make `real_numbers` call `config.finite_real` per item (lazy import, config pulls scipy), which covers all three `manifest_shape` callers; in `_wrf_notes` treat a bool as not recorded before `float()`. One regression test per fix (NaN/inf `real_numbers`, tao and orca `manifest_shape`, `_wrf_notes` bool). DECISIONS row and CHANGELOG line extending 768, 819 and M-22. Grep fixtures for `inf` or `nan` manifest sentinels first.

sources: A-3


### M-6. `cafe.atomic.write_text` fails for final names of about 235 to 255 characters where a plain write works   (sources: A-4)
severity: minor / status: confirmed / lane: robustness
where: cafe/atomic.py:17; sibling temporaries at cafe/pm/emulator.py:96, env/orca.py:232, env/hycom.py:225, ledger.py:131, cafe/ocean.py:127, env/bathy.py:139
claim: the temporary is `<name>.<pid>.<8 hex>.tmp`, about 21 characters longer than the name; `write_text(d / ('a'*250 + '.json'), '[1]')` raises `OSError 63` where `Path.write_text` works.
check: ran a stdlib-only probe of `cafe/atomic.py` on the laptop (macOS, limit 255): `OSError 63` at final lengths 239, 240, 245, 255, fine at 235; `Path.write_text` fine everywhere. Not run on orca. No caller builds such a name: the mission name is capped at 64 (mission.json, row 373). The dangling-symlink `FileNotFoundError` was not reproduced (needs a missing target directory, a different case). The other temporaries add only 4 to 8 characters (narrower band); `emulator.py:96` copies the 21-character suffix.

fix: in `atomic.py` name the temporary from a short fixed prefix independent of the target (`.<12 hex>.tmp` in the same directory), or `tempfile.mkstemp(dir=...)` plus `fchmod`; route `emulator.py:96` through `atomic.write_text`. Test with a 250-character name. Check `bin/sync_filters` and any ignore pattern matching `<name>.*.tmp`. If not wanted, document the 234-character cap.

sources: A-4


### M-7. Survivors of the round 14/15 tests: the EPERM branch of `acceptance._probe`, the `median` field of `_check_factor`, and the value of `wallmodel.NORMAL_MIN`   (sources: A-5)
severity: minor / status: confirmed / lane: tests
where: cafe/pm/acceptance.py:379-380; cafe/pm/stats/sampling.py:90; cafe/pm/stage3/wallmodel.py:53
claim: dropping `errno.EPERM`, dropping `'median'` from the fraction fields, and `NORMAL_MIN` 1e-6 to 1e-2 or 0.0 each pass the tests that name them.
check: ran on orca (proot, 2 CPUs, detached worktree at 01a39c0): all three edits applied together survive: stats `-k 'r14 or fraction or percent'` rc 0, acceptance `-k r14_m2` rc 0, stage 3 `-k 'r14_m34 or r14_l0 or r15 or wall_set'` rc 0. `grep NORMAL_MIN tests` is empty; the only test reaching it has gradient exactly 0 (test_stage3.py:209). By reading, `_probe` also lists ENOENT, ENOTDIR, ELOOP, EBADF as absent and tests drive only EIO and EACCES. No gate or number moves.

fix: tests only. (1) parametrize the monkeypatched `os.stat` test over every errno in `_probe` (EPERM denied; ENOENT, ENOTDIR, ELOOP, EBADF absent), no chmod, no 442 s run. (2) a lognormal fraction case with median=50 in the PERCENT list of `test_stats_exact.py`; if `_check_factor` is unreachable for that dist delete the dead `'median'` instead. (3) a `wall_set` test with a small nonzero smoothed gradient, valid at 1e-4 and invalid at 0, asserting behaviour not the literal.

sources: A-5


### M-8. DECISIONS rows 739/706 (sibling `<name>.tmp`), 136/176 (nothing read from the clock) and 651 state what the code no longer does   (sources: A-6)
severity: minor / status: partly / lane: documentation
where: DECISIONS.md rows 739, 706, 136, 176, 651
claim: row 739 says `a sibling <name>.tmp` and ends at 'amended by 815'; row 817 changed the temporary and only 'extends' 739. Rows 136 and 176 say nothing is read from the clock and no measured wall time is reported, but rows 288, 754 and 758 record otherwise.
check: read rows and code, nothing run. `cafe/atomic.py:14` builds `<name>.<pid>.<8 hex>.tmp`; rows 739 and 706 never point forward to 817: confirmed. Row 176 is literally contradicted by rows 288 and 754 (`/machine/timing/variants/`, `report.py:1661`). Row 136 is overstated, not wrong, since it also says the wall clock is a safety kill. Row 651 waits on M-3.

fix: edit DECISIONS.md only: 739 and 706 name the temporary and add 817 to 'amended by'; 136 soften 'nothing' to 'nothing but the safety kill' and point to 754; 176 add the exception for `/machine/timing` (288, 754); 651 after M-3. Optionally a warning-level audit check that every 'extends/amends N' in row M has M in row N's list.

sources: A-6


### M-9. `hangar.bem` evaluates roll and pitch added mass at the heave frequency while the comment says natural frequencies of heave/roll/pitch   (sources: A-7)
severity: minor / status: confirmed / lane: physics
where: cafe/hangar.py:110-117; cafe/vehicle.py:266-268; cafe/receipts.py:338
claim: `w_heave = sqrt(9.81/max(draft, 0.02))` is used for Heave, Roll and Pitch (8.2 rad/s at 0.145 m draft, against a roll frequency of a few rad/s); only the live app's USV Hangar is affected, the pm pipeline never calls `bem`.
check: read the code; Capytaine was not run, so the size is unmeasured. Surge, sway and yaw use a fixed 0.3 rad/s with no stated basis. Addition by the verifier: each row i is solved at its own omega and then `0.5*(A + A.T)` symmetrises, so off-diagonal terms average two frequencies; `Bd` stores only the diagonal. The UUV branch is frequency-independent (receipts.py:338). No DECISIONS or PHYSICS line justifies the choice.

fix: fix inside `hangar.bem` only. Minimum: correct the comment to say roll and pitch borrow the heave frequency as an assumption, plus a DECISIONS row. Physical: roll and pitch natural frequencies from `hs.get('gm')` and radii of gyration, clamped, with a fallback for missing or non-positive GM; test with a mocked `cpt.BEMSolver` recording omega per dof. Cached USV hangar results would no longer match fresh ones.

sources: A-7


### M-10. UAS verdict is a step function of launch wind: the sortie commands 8 m/s of ground speed on upwind legs and `max_airspeed_ms` never caps the airspeed   (sources: B-1)
severity: minor / status: partly / lane: physics
where: platforms/quad_uas.yaml:86-88,108-109,119; cafe/pm/physics/uas.py:155,158,323,371; cafe/pm/stage3/pipeline_windows.py:310-339; DECISIONS 161, 237
claim: in q15 the share of sorties reaching 8/8 waypoints is 1.0 up to 5.5 m/s launch wind, 0.47 at 5.5-6 and 0.0 above; the 55 failing members all have a sortie wind of 5.90 or more, the 9 passing peak at 5.67 or less. Upwind airspeed needed is 8 + w, over the tilt-limited 12.6 m/s from w = 4.6. `wind_exceeds_airspeed` is 0/64.
check: rechecked the numbers from `q15_mission.json` and read the code; not run on orca. Numbers hold (3 sorties at 5.87-5.92 m/s did finish, so the split is not exact per sortie). Code: `v_air` is stored (uas.py:155) and read nowhere; `v_leg = min(leg_speed_ms, max_airspeed_ms)` caps ground speed only; stage 3 does hold the envelope (uas_leg_speed, row 161), stage 1 does not. The yaml rationale 'below max_airspeed so wind headroom remains' is false upwind; `launch_rule.max_mean_wind_ms` 12 compares wind alone with the airspeed limit. Only partly: a threshold in wind is not itself a defect (237, 301, 332 and L17 say the verdict rests on finishing the profile), the threshold is set jointly by assumed leg speed, duration and `min_profile_fraction` (lab questions), and enforcing the cap would only move it a little lower.

fix: either read `v_air` in the sortie step (cap upwind ground speed at `min(v_leg, v_air - w.h)` using the stage 3 formula once, imported not copied) or delete `v_air` and reword the two yaml strings and PHYSICS 5. If the cap is added: regression test, a DECISIONS row amending 161 and 237, a quick rerun (wp_done, sat_s and 55/64 may move), and align the launch rule with the same helper. Keep minor unless the rerun moves the count.

sources: B-1


### M-11. glider_eq MARGINAL (18/64 lose station) holds only for a 950 m dive that the stage-3 hull check says the assumed hull cannot make; at 364 m it is NO-GO 64/64   (sources: B-2)
severity: minor / status: partly / lane: physics
where: missions/tepex_c_demo.yaml (glider_eq dive_depth_m 950); cafe/pm/physics/glider.py:293; cafe/pm/config.py:577-582; cafe/pm/stage3/pipeline_windows.py:159-165,543; platforms/seaglider.yaml:20
claim: re-flying glider_eq with only the dive depth changed gives station_lost 18 at 950 m, 38 at 700 m, 60 at 500 m and 64/64 at 364 m (EUC flow profile); the 950 m limit, the 1000 m rating and the 364 m collapse depth are three unlinked limits.
check: reproduced on orca (proot, 2 CPUs) with the q15 Context, environment, refit scales and priors, glider_eq alone, two batches of 32: 18/38/60/64 of 64 at 950/700/500/364 m (950 m identical to q15 k_fail 18). Partly: 364 m belongs to the model's assumed stage-3 hull (Al 6061, 8 mm, QUESTIONS_FOR_LAB 4a), not to a Seaglider rated 1000 m; no printed verdict in the shipped run is wrong; P-R14V4 already says the verdict carries no word of the collapse and B-2 adds the quantified direction. Sibling glider_2n (slocum, 500 m) is GO at 500 and 364 m. Nothing reads `fea['utilization']` (row 730).

fix: owner decision first: correct the assumed hull (QFL 4a) so the collapse depth is at least the rating, or make the limit real in one place: the dive-depth check at `config.py:577` and `glider.py:293` take `min(rating_m, hull collapse depth)` from one platform field, or put a warning next to glider_eq's verdict giving the 500 m (60/64) and 364 m (64/64) results. A warning is the lower-risk option (a hard cap refuses the demo and changes ledger hashes). Test: a mission ordering a depth above the limit is a `ConfigError` or carries the warning. Amends row 730.

sources: B-2


### M-12. `becalmed` ignores the direction of the current, so a cross-track current counts as 'unable to stem it'   (sources: B-3)
severity: minor / status: not_confirmed / lane: physics
where: cafe/pm/physics/usv.py:655 and docstring :56-68; DECISIONS 56, 217, 333; QUESTIONS_FOR_LAB.md:64
claim: 13 of 18 flagged members have over 70% of the current across the north-south section; e.g. member 28 at 21.3 h has 0.70 m/s current with 0.17 northward and a best through-water speed 0.57.
check: read the code and docs; the reviewer's 13-of-18 and the member examples were not re-opened. The code compares a scalar best through-water speed with the current's magnitude, which is the definition in the docstring, the lab question and the brief ('cannot stem the current'); row 56 chose it because a literal SOG rule cannot fire, 217 fixed `<=`, 333 added a mutant test. A boat slower than the current cannot hold position whichever way it points; the cross sweep is `swept_off_track`. Only 1 of 18 fails by becalmed alone, so no verdict moves. A directional rule would risk the SPURS-2 receipt (usv.py:788-791).

fix: none (not confirmed). no code change. If the owner wants lost along-track progress, the change belongs at usv.py:655 (best along-track ground speed against zero), amending rows 56 and 217 and the SPURS-2 receipt. Cheaper: one documentation line in PHYSICS.md or the report that becalmed counts cross-track current too.

sources: B-3


### M-13. UAS flux levels are flown at 18/38/68/108 m above the sea for a mission asking 10/30/60/100 m; the schema and report never say the levels are above the deck   (sources: B-4)
severity: minor / status: partly / lane: documentation
where: cafe/pm/stage1.py:208,314,327,396,408; cafe/pm/physics/uas.py:443,508-518; cafe/schemas/mission.json:60; platforms/quad_uas.yaml:107,113; docs/RUNBOOK.md:98
claim: `altitudes_m` is passed straight to the physics as heights above the deck (deck 8 m); the recorded altitude, the wind read and the RF antenna height use deck + level, and the largest finite USV-UAS range, 48.9 km, is the radio horizon for 2.2 m + 108 m.
check: read the code only (the offset is fixed by it). The 8 m offset is designed: legs are stacked above the deck, the platform yaml already says so (:107, :113), and row 325 uses deck + mean(levels) for turbulence. The reviewer's claim that a flux profile shifted by the deck is wrong physics does not hold; the defect is a documentation gap (schema 'metres' with no reference level, RUNBOOK:98 and the report silent). Shifting the levels by -deck in code would move every UAS wind, RF and turbulence number and is not recommended.

fix: documentation only: `mission.json:60` says 'metres above the deck (platform `deck_height_m`, 8 m for the quad); wind and the radio horizon use deck plus altitude'; one line in the report UAS section giving the sea-referenced heights (18/38/68/108 for the demo). Hand-offs to batch D: RUNBOOK line 98, a DECISIONS row and CHANGELOG line cross-referencing 325. Tests: the schema description contains 'deck'; the report text for a UAS run names the offset. Text only, no numbers move.

sources: B-4


### M-14. Stage-3 hull FEA runs at L/20; the collapse depth falls with refinement to 331 m while the documents quote 364 m   (sources: C-1)
severity: minor / status: confirmed / lane: numerics
where: config/assumptions.yaml stage3.fea_elements_along (20), fea_min_s; cafe/pm/stage3/pipeline_windows.py `_fea`; cafe/hangar.py:162; docs/PHYSICS.md:992; QUESTIONS_FOR_LAB 4a
claim: default glider hull (ellipsoid 1.8 x 0.30 m, 8 mm Al6061, 500 m): L/20 gives factor 1.4552, 364 m; L/30 1.4133, 353 m; L/45 1.3348, 334 m; L/70 1.3225, 331 m. The quoted 364 m and utilization 1.374 are 10% unsafe against the converged 331 m (1.512).
check: reran `windows.fea_window` on orca (proot, 2 CPUs, detached worktree at 01a39c0): L/20 1.4552, 364 m, util 1.374, 1408 elements, 65 s; L/45 1.3348, 334 m, 1.498, 2944 elements, 527 s; L/70 1.3225, 331 m, 1.512, 5546 elements, 550 s (L/30 not rerun). L/45 to L/70 moves 0.7%. `hangar.py:162` already uses L/70 and says L/45 reads about 9% high, so the repo has two collapse depths for one hull. Severity lowered: q15 never ran the FEA (`run=false`) and no pm code reads `fea['utilization']`. The convergence study named in `replace_with` does not exist.

fix: one mesh resolution read by both `hangar.py` and `pipeline_windows._fea` (shared constant or the assumption), at L/70 or at least L/45; replace the `replace_with` text with the measured study (364, 334, 331 m); re-measure `fea_min_s` (L/70 is about 8 times slower; the FEA reserve and plan-out rule, rows 741, 776, depend on it); update PHYSICS.md:992 and QFL 4a to 331 m and 1.512; amend rows 730 and 741. Test that the two meshes agree. Risk: small budgets plan the FEA out.

sources: C-1


### M-15. The 3/4 follower correction is applied to every buckling mode and the 0.5 knockdown is then stacked on it   (sources: C-2)
severity: minor / status: partly / lane: physics
where: cafe/fea.py:310-316 (`buckling_factor = 0.75 * min(pos)`); cafe/pm/stage3/windows.py:370; cafe/hangar.py:14,164; cafe/receipts.py:479,501
claim: for a sphere the dead-load result is +4.4% over Zoll but the reported one -21.7%; an n=3 tube reports 0.902 x von Mises against 1.069 expected; without the 3/4 the default hull utilization would be 1.03 (about 485 m) instead of 1.374 (364 m).
check: read the code, no CalculiX run. The 3/4 is deliberate (the comment gives n^2/(n^2-1) = 4/3 for two lobes and applies the conservative 3/4 to all): right at n=2 (+5% inside the 0.10 receipt tolerance), 15.6% low at n=3, about 25% low for a sphere (the -21.7% was not reproduced; mesh is probably the rest). `hangar.py:164` and `windows.py:370` apply KNOCKDOWN 0.5 on top. DECISIONS 730, PHYSICS:992 and QFL 4a quote 1.455 without saying it includes the 3/4; no row is contradicted. No verdict reads it.

fix: in `fea.solve` only: read the lobe count n of the lowest mode and multiply by (n^2-1)/n^2 (3/4 only for n=2, sphere 1, 3/4 as fallback); or keep the flat 3/4 and state it in PHYSICS, DECISIONS and QFL 4a (1.455 includes it). Test: a 3-lobe tube reports dead-load * 8/9. Review with the knockdown and M-14 together or the error just moves; it changes the glider hull utilization, the bracket receipt (receipts.py:501), rows 730 and 792 and the stage-3 ledger hash.

sources: C-2


### M-16. `fea.py` docstring and self-test describe a 3-2-1 constraint and reactions the code no longer has; `python -m cafe.fea` raises KeyError   (sources: C-3)
severity: minor / status: confirmed / lane: documentation
where: cafe/fea.py:1-6 (docstring), :119-122, :252, :264-266, :302-305, :396-421 (`__main__`)
claim: a free-body solve returns no `reaction` key (support is None unless `fixed=` is given) but the `__main__` print indexes `r['reaction']` before its asserts, so the module's only runnable receipt cannot run.
check: read the code (no FEA needed): the free body is held by `_mean_rigid_equations`, `reaction` is written only under `if support is not None`, the f-string at :412 raises KeyError before the asserts at :413-420, so no check of the self-test ever runs. No test or Makefile entry runs `python -m cafe.fea`. `hangar.py:130` (`.get`) and `receipts.py:528` (clamped tube) are safe. No DECISIONS or PHYSICS row mentions 3-2-1.

fix: edit `fea.py` only: rewrite docstring lines 4-6 (mean-rigid-motion equations; `reaction` only for a clamped solve), drop `r['reaction']` from the print and replace the :420 assert with one that matches (applied loads sum to ~0, or a small clamped case). One regression test running the `__main__` body or asserting `'reaction' not in solve(free body)`.

sources: C-3


### M-17. `body_accel` is silently ignored for a free body; `thickness=None` on a shell gives a TypeError after meshing   (sources: C-4)
severity: minor / status: confirmed / lane: robustness
where: cafe/fea.py:151,161,188,201,210,261-264
claim: icosphere shell with `body_accel=[0,0,-196]` and no `fixed` gives an identical vm_p99 (765734.626365446) and balance_accel; `solve(..., thickness=None)` raises `unsupported format string passed to NoneType.__format__` after gmsh has run.
check: read the code, not run on orca. `body_accel` is read only inside `if fixed is not None:` (:261-262) though the docstring says it applies to all material; `thickness` is first used at :201, after `mesh_body` (:188), and TypeError escapes the jacobian retry loop (:172-179). The only `body_accel` caller (`hangar.py:204`) passes it with `fixed=lift`, and `hangar.py:154` passes `t if struct == 'shell' else None`, so no number moves. `density` is applied before both branches and is fine. No DECISIONS row.

fix: in `fea.solve` before the retry loop: `ValueError` for a shell without thickness, and `ValueError('body_accel needs fixed=')` for a free body (raising cannot change a number; implementing the d'Alembert loads would need a DECISIONS row). Tests: both raise before the mesher is called.

sources: C-4


### M-18. With two windows the refit sigma has no between-window floor although DerSimonian-Laird gives tau2 = 0 in 15-34% of draws   (sources: C-5)
severity: minor / status: partly / lane: statistics
where: cafe/pm/stage3/refit.py:42 (`pool`), :65-67 (`_sigma`), :98, :104
claim: 20,000 draws through `refit.pool`, k=2, se 0.01: tau2 == 0 in 15.3% (true between-window sd 0.05) and 33.7% (sd 0.02).
check: replicated with a pure numpy copy of `pool` (15.9% and 37.6%, same within seed noise); orca not used. The stated consequence is wrong: `_sigma` always adds the discretisation floor (at least 0.05 of the mean) in quadrature, so a tau2 = 0 draw gives sigma about 0.051, not 0.007; mean sigma is 0.0736 against 'true' 0.0616 (sd 0.05) and 0.0548 against 0.0524 (sd 0.02), short only in the tau2 = 0 draws (up to about 17%, about 3%). Documented design (rows 159, 181 say fewer than two windows; PHYSICS:994). In q15 `refit.json` has `used: false`.

fix: optional design change, not a bug: widen the gate in `_sigma` to windows < 3 (or Hartung-Knapp / Paule-Mandel at small k), amending row 181, with a test that k=2 agreeing windows give `sigma_between = f_w * mean`; it widens every two-window multiplier spread and can move GO/NO-GO near a threshold. Recommended instead: state the limit in PHYSICS.md.

sources: C-5


### M-19. `refit.pool` accepts NaN; the refit branches disagree on a zero standard error   (sources: C-6)
severity: minor / status: partly / lane: robustness
where: cafe/pm/stage3/refit.py:35 (`pool`), :90, :94, :96, :102; cafe/pm/stage3/freesurface.py:228
claim: `refit.pool([1.0,1.1],[nan,0.01])` returns NaN mean/se with no error; with `cd_spread = 0` the hangar branch raises ValueError for cd, clamps cl to 1e-12 (weight 1e24), and the `hangar=None` branch clamps.
check: read the code, not run. `(se <= 0).any()` is False for NaN; NaN in `means` and an infinite se are not checked; `max(nan, 1e-12)` returns nan. The mismatch is inside the hangar branch itself (cd raises at :96, cl clamps at :102). Reach is weak: the only production caller is `pipeline.py:1403/1409` with `hangar=None` and only `ok=True` windows, and `freesurface.py:228` floors cd_spread. `cafe/pm/env/subgrid.py:481-482` has its own `_pool` that was not read. No verdict moves.

fix: in `pool()`: require finite means and se (`ValueError`), and put the zero-spread policy there (keep the 1e-12 clamp inside `pool` so all four call sites share it; a larger floor as a fraction of |mean| would change printed numbers and needs a DECISIONS row). Tests: `pool([1,1.1],[nan,.01])` raises; `cd_spread = 0` behaves the same for `hangar=None` and `hangar={'cd':1}`, cd and cl.

sources: C-6


### M-20. `track_heading` takes the member median of raw longitudes, wrong across the antimeridian   (sources: C-7)
severity: minor / status: confirmed / lane: robustness
where: cafe/pm/stage3/pipeline_windows.py:127-130 (`track_heading`); cafe/pm/pipeline.py:1351; cafe/pm/report.py:683 (`_unwrap`, correct)
claim: UAS members at lons [[179.99,-179.99],[-179.99,-179.99],[-179.98,-179.98]] give heading 270.006 deg against 45.000 for the same flight at lon 10.
check: recomputed the arithmetic locally in numpy (not on orca): the median of +179.99 and -179.99 is 0 and the wrap is applied only to the difference afterwards. The UAS has no stage-1 heading, so it always takes this fallback. The demo box 165..-165 crosses the line, but in q15 all members stay within -170.5 to -164.98 so nothing moved. Worse sibling: `pipeline.py:1351` sets each window's lon to `np.nanmedian` of raw longitudes, which feeds the environment lookups at pipeline_windows.py:209/252/325, so members straddling the line put a window near lon 0 (a printed number can change). `report._median_track` is already correct. No DECISIONS row contradicts a fix (474, 480, 537, 542).

fix: one helper `lon_median(lon, axis)` (unwrap about a reference, nanmedian, wrap to [-180,180)) beside `report._unwrap`, called at pipeline_windows.py:127, pipeline.py:1351 and `report._median_track`. Tests: a straddling UAS gives the same heading as at lon 10; a straddling window at pipeline.py:1351 gives lon near 180. Non-straddling results are unchanged (q15 should not move).

sources: C-7


### M-21. Any SIGKILL (including OOM) of the FEA or free-surface child is reported as a deadline kill   (sources: C-8)
severity: minor / status: partly / lane: honesty
where: cafe/pm/stage3/pipeline_windows.py:433 (`_fea`, `returncode == -9`), :690 (`_fs_work`); cafe/pm/stage3/freesurface.py:183-194 (`arm_watchdog`)
claim: -9 is the same for the watchdog and the kernel OOM killer; the row says the FEA did not finish inside the remaining slice, and the free-surface text says 'killed by its watchdog at the deadline'.
check: confirmed by reading, not run; q15 has no -9 row. Neither site compares elapsed time with the deadline. Narrowing: the OOM killer picks the largest process, usually `ccx`, `gmsh` or `interFoam`, which gives a python exception (non-zero, not -9) and reaches the 'FEA failed' branch; the bug is reached when the python child itself is chosen or by a manual kill. Only a reason string changes. `tests/test_stage3.py:1649` pins the current behaviour; 1549 and 1558 match the 'killed: the FEA' prefix.

fix: one helper beside `FS_GRACE_S` (`_sigkill_is_deadline(rc, deadline)`: rc == -9 and now >= deadline - 1 s) used by both sites; an early -9 gets its own reason ('killed by SIGKILL before its deadline (out of memory or an outside kill)'), FEA keeps `run=False`. Test via the `_spawn` seam with a future deadline; keep the 1649 case. The 1 s slack and `FS_GRACE_S` cover timer skew.

sources: C-8


### M-22. `mass_drift_per_step` does not protect the pressure reference of the hull load   (sources: C-9)
severity: minor / status: partly / lane: physics
where: cafe/pm/stage3/windows.py:86-88,223,231,299-327; cafe/pm/stage3/nest.py:356-359; DECISIONS 548; docs/CREDIBILITY.md:164
claim: the check bounds the single-step relative mass change (1e-3), not the mean wall-cell density offset that becomes the FEA pressure; at U_LAT 0.04 the stagnation excess is 2.4e-3, so an offset of 1e-3 is a 40% error.
check: read the code; arithmetic only; no orca run because q15's windows are all `ok=False` (viscosity floor needs 6.5e9 to 6.6e13 cells, or becalmed), so no mass or wall-pressure series exists. Not a defect as filed: DECISIONS 548 (also CREDIBILITY:164, PHYSICS:990) says per step on purpose, that a total bound was not added because the open-boundary box legitimately exchanges mass and the limit must first be measured, and tests pin that meaning; `nest.py:11-14,167` anchors rho = 1 on every open face. The gap is the same as round 10 M-14. No number moves.

fix: not recommended now. If wanted: measure the mean wall-cell density minus 1 on a real executed window, then add a gauge-offset row to `windows.stage3_checks` (single site) with a measured limit, or subtract the far-field mean in `wall_pressure_pa`; test: 0.9e-3 per-step drift with a 1e-3 mean offset fails the new row; amends row 548. A documentation line is enough until then.

sources: C-9


### M-23. `vm_max` is a mesh artefact (163 MPa on a uniform sphere) and is stored; p99 hides true hot spots by about 13%   (sources: C-10)
severity: minor / status: confirmed / lane: numerics
where: cafe/fea.py:298-300 (`vm_max`); cafe/pm/stage3/windows.py:374; cafe/hangar.py:129
claim: sphere h=0.02: vm_p99 25.68, vm_max 163.47 MPa (6.4 x the Lame value), h=0.025 and 0.04 give 28.3 and 29.4; a clamped tube gives p99 13.1 MPa against 15.0 at the beam root.
check: ran on orca (proot, 2 CPUs): shell icosphere r=1 m, t=10 mm, p=0.51 MPa (membrane 25.5 MPa): h=0.04 p99 27.43, max 29.17; h=0.025 28.50, 30.12; h=0.02 28.77, 109.28 MPa (3.8x p99). The spike reproduces, smaller than the reviewer's 163, only at the finest mesh. The tube half (13% low) was not re-run. Every utilization uses `vm_p99`; nothing else reads `vm_max` (pass-through plus one test fixture). The stored FEA row and the app load-case table show it unlabelled. Row 730 makes p99 the stress measure on purpose.

fix: in `fea._solve`: drop `vm_max` from the output, `hangar._case` and `windows.fea_window`, or compute it from the nodal through-thickness field and label it unconverged; keep p99 as the utilization basis. Test: on a uniform-pressure sphere `vm_max` stays within a few times p99 across two meshes, or the key is absent (tests/test_stage3.py:766 fixture uses it). The stage-3 window ledger hash changes (key set); DECISIONS row and CHANGELOG line.

sources: C-10


### M-24. The FEA reserve is withheld from the LES kill even when the FEA is planned out   (sources: C-11)
severity: minor / status: confirmed / lane: performance
where: cafe/pm/stage3/pipeline_windows.py:567-568 (`fea_s`, `run_s`); cafe/pm/budget.py:186,477-489; DECISIONS 137, 741, 776
claim: under `--budget ci` the glider FEA is planned out (9.0 s against 68.2 s) but `run_s = win_s - fea_s` still removes `fea_reserve_frac` of the slice, so a slow machine cuts the LES window at 0.75 of its slice for an FEA that never runs.
check: read, not run; q15 has `slice_s 0.0`, `fea.runs False` and no glider LES. `fea_s` is computed from `veh.extra.get('fea')` and never reads `sizes['fea']['runs']`; the planned-out case is handled only later (:587-589). Only visible on a machine more than 1.5x slower than its bench (cell-steps are sized to 0.75 of the slice with margin 1.5). The same reserve at budget.py:186 is the plan's declared basis (137) and is not a bug.

fix: make the reserve conditional at pipeline_windows.py:567 on `sizes['fea']['runs']`; leave budget.py:186 alone so cell-steps and ledger hashes do not move. Test: a glider window with `fea.runs False` gets `spec.wall_s == win_s`. DECISIONS row amending 137 and 776, CHANGELOG line. Under ci the worst-case window grows from 27 s to 36 s.

sources: C-11


### M-25. `windows.run_windows` is dead code and its FEA omits the buckling step   (sources: C-12)
severity: minor / status: partly / lane: robustness
where: cafe/pm/stage3/windows.py:379 (`run_windows`), :10, :352; cafe/pm/stage3/pipeline_windows.py:409; tests/test_stage3.py:770,797-811
claim: the only caller is a test; `run_windows` passes only `fea_kw`, so utilization is stress-only by default, which round 14 M-31 / row 792 removed.
check: call graph read, nothing run. Facts hold, harm does not: the pipeline uses `_fea_child` with `buckle=True`; the `buckle=False` default is intended (row 730 'None without buckle', test_stage3.py:770); row 792 removed only the silent fallback when `buckle=True` finds no eigenvalue (`fea_window` still raises, windows.py:368). Nothing live reaches the path; no number moves. What remains is a dead, trap-shaped helper.

fix: delete `run_windows`, its docstring line (windows.py:10) and `test_run_windows_overlaps_fea_with_the_next_les_window`; DECISIONS row and CHANGELOG line. Alternative: default `fea_kw` to `{'buckle': True}` with a test. Do not change `fea_window`'s default (contradicts row 730, adds about 40 s to every caller).

sources: C-12


### M-26. The FEA equations (mean-rigid constraint, 3/4 factor, OFFSET choice, p99) have no section in docs/PHYSICS.md   (sources: C-13)
severity: minor / status: confirmed / lane: documentation
where: docs/PHYSICS.md (only line 992 mentions the FEA); cafe/fea.py:118-135,166-170,296-316,417; cafe/hangar.py:14
claim: `grep -n -i 'follower\|mean rigid\|rigid motion\|OFFSET\|0.75'` finds none; the derivations live only in code comments, and Lame, Windenburg-Trilling and Bresse are not cited in PHYSICS (Bresse only in BRIEF 2.6).
check: read PHYSICS.md (1018 lines) and `fea.py`; the grep claim holds; nothing run. Line 992 gives wiring and the utilization definition, no equations; CREDIBILITY has no FEA row. The 0.75 argument is exact only for n=2 (8/9 at n=3, see M-15); the KNOCKDOWN 0.5 is cited 'NASA SP-8007-style' in a code comment only. No DECISIONS row contradicts adding the section.

fix: add a 'Hull FEA' subsection next to PHYSICS.md:992: the mean-rigid-motion equations and why they replace 3-2-1 pins, the CalculiX OFFSET choice and fallback, p99 von Mises and why, the n^2/(n^2-1) derivation with Bresse (1866) and the 0.765 vs 0.546 check, KNOCKDOWN with its source, the Lame and Windenburg-Trilling self-checks; a CREDIBILITY row, a DECISIONS row, a CHANGELOG line; a doc-lint test for the anchor terms. Write it after M-15 and M-14 settle the numbers.

sources: C-13


### M-27. `stage3.fea_min_s` cites a hull (0.15 m, 7 mm) that is not the default (0.30 m, 8 mm)   (sources: C-14)
severity: minor / status: confirmed / lane: documentation
where: config/assumptions.yaml:311 (`stage3.fea_min_s` why) against stage3.glider.hull_diameter_m (0.30), hull_thickness_m (0.008), fea_elements_along (20); cafe/pm/stage3/pipeline_windows.py:164-165; tests/test_budget.py:396; review/orca/PROBLEMS.md
claim: the text says 'ellipsoid 1.8 m x 0.15 m, 7 mm Al, h = L/20, 1408 elements'; the 0.15 is the radius, the 7 mm is wrong.
check: static mismatch confirmed with the YAML and `pipeline_windows.py:164-165` (radii L/2, D/2, D/2). The value is right: PROBLEMS P-R14V4 measured 63.3 s on the default hull against the 68.2 s child time. Not rerun on orca. The same wording may sit in the docstring at tests/test_budget.py:396 (not confirmed). Editing a `why` string changes no value.

fix: edit the `why` to 'ellipsoid 1.8 m long, 0.30 m diameter (semi-axes 0.9 and 0.15 m), 8 mm Al6061, h = L/20, 1408 elements' or cite the keys instead of numbers; note the M-14 point (449 s at L/45) there. Check first whether the stage-3 ledger or credibility page stores the `why` text. Optional guard test reading the YAML.

sources: C-14


### M-28. A what-if whose changes cancel or are zero answers with a header only and exit 0   (sources: D-3)
severity: minor / status: confirmed / lane: robustness
where: cafe/pm/__main__.py:303-305,336-349; cafe/pm/whatif.py:810-815,849
claim: `--shift 6h --shift=-6h`, `--move '1deg W' --move '1deg E'` or `--shift 0h` sum to zero and the CLI prints `whatif demo: +0 h` and returns 0 with no vehicle line; `--drop usv --drop usv` prints `dropped usv, usv`.
check: ran on orca (proot, 2 CPUs, detached worktree at 01a39c0): the cancel case printed two notes and the header, nothing else; the duplicate drop printed `drop usv, usv`. The `--move` cancel takes the same path but was not run. The guard is only 'any option given'; `answer` builds `changed` only `if any(mod.values())`. Row 289 prints 'nothing changes' only for whole-day UAS shifts; row 346 deliberately allows an all-zero change in `run_variant`.

fix: in `whatif.answer` (shared entry): de-duplicate `drop` with `dict.fromkeys`; when changed, unchanged and drop are all empty raise `Invalid('the changes cancel: nothing changes')` (the CLI prints it or exits 2 as row 478 does). Tests: the shift pair and the duplicate drop. Do not route `apply` or `run_variant` through the check.

sources: D-3


### M-29. Move size is unbounded: `dlon` wraps modulo 360, so 355 deg east is accepted as 5 deg west and 1e300 as 10 deg west   (sources: D-4)
severity: minor / status: confirmed / lane: robustness
where: cafe/pm/whatif.py:91-92,145,151,154,156,170-176,790-794; cafe/pm/config.py:254-258
claim: `apply(demo, {'glider_eq': {'dlon': 1e300}})` is accepted with the glider at -180.0; 355 gives -175.0; 360 leaves it in place and counts as a change; `describe` prints the typed size.
check: ran on orca (detached worktree at 01a39c0): 1e300 gives -180.0 and 'move 1e+300 deg east'; 355 gives -175.0; 360 gives -170.0; 721 gives -169.0; 1e18 is refused only through float absorption. `_numbers` checks only finiteness, `_in_box` works modulo 360, and the Invalid check sees only the post-wrap point. Only user input is affected (design and flip moves are small); `dlat` is refused by the box.

fix: in `whatif._numbers` (the single route for `apply` and `answer`) refuse `abs(dlon)` at or above the box width (or 360, or 180) and `abs(dlat)` beyond 180 as `Invalid` naming the vehicle and the limit; covers the ship move, the track under change, `--move` and ops. Tests: 1e300, 355, 360 raise; a small move works. Check tests using dlon above 180.

sources: D-4


### M-30. `duty` is checked only to be > 0; the documented range is <= 1   (sources: D-5)
severity: minor / status: confirmed / lane: robustness
where: cafe/pm/whatif.py:22-23,160-166,173-175; cafe/pm/config.py:577-585; tests/test_whatif.py:196; DECISIONS 195, 731, 109
claim: `apply(demo, {'glider_eq': {'duty': 10}})` gives dive_depth_m 9500; `{'uas': {'duty': 1000}}` gives sorties every 0.001 d; `duty: 1e-300` gives 9.5e-298 m; none is Invalid.
check: ran on orca (proot, 2 CPUs): glider duty 10 gives 9500.0 (baseline 950), 1e-300 gives 9.5e-298, 0.01 gives 9.5 m, below any `min_dive_m`; the UAS 1000 case was not run. `apply` never re-runs the config.py dive-range and every_days overlap checks, so the whole class is that `apply` does not validate the mission it builds. Row 195's premise ('`apply` never shortens `every_days`') is false for duty > 1, so the fix amends 195, 731 and 109. `glider.py:293` clips the dive to `rating_m`. The CLI builds no duty, so only direct callers reach it.

fix: in `_numbers` change `duty <= 0.0` to `not 0.0 < duty <= 1.0`; at the end of `apply` call the same dive-range and sortie-period checks `load_mission` uses, factored out of config.py into one function. Tests: glider duty 10 and a UAS duty above 1 raise `Invalid`; a duty taking the dive below `min_dive_m` raises. `test_whatif.py:196` (duty 1e-300 stays valid, row 731) must be amended; `_fits` and `design` must treat the new Invalid like the box edge.

sources: D-5


### M-31. UAS launch shifts are quantised to a minute and refusals say 'a whole number of days' for 0.001 h or 24.001 h   (sources: D-6)
severity: minor / status: confirmed / lane: documentation
where: cafe/pm/whatif.py:107-109,132-136,817-823
claim: `apply(demo, {'uas': {'shift_h': 0.001}})` raises 'launching +0.001 h later is a whole number of days'; 24.001 and 23.999 the same; 0.01 h is accepted and moves the launch one minute; `design` draws within 30 s of 0 fall through `_fits_all` to the all-zero change.
check: ran on orca (2 CPUs): 0.001, 24.001, 23.999 Invalid; 0.01 gives 14:01; 0.5 gives 14:30; `_fits(demo, uas, shift_h=0.004)` returns the all-zero change. `_whole_days` is `round(h*60) % 1440 == 0`, a minute-resolution test. The 'silently lost' claim is overstated: the fallback is the base mission, one wasted training row, about 0.02% per UAS row. Both callers (`apply`, `answer`) share the wording; rows 195 and 289 pin it in tests.

fix: say what is tested: 'rounds to a whole number of days at one-minute resolution (launch times are HH:MM)', from one helper used by both sites, or refuse |h| < 30 s with a 'below the 1-minute launch-time resolution' message. Tests with 0.001 and 24.001. Grep tests and docs/RUNBOOK for 'whole number of days'. Do not change the rounding (it would move launch times).

sources: D-6


### M-32. The round-trip reach map labels a cell whose return is blocked by current 'beyond endurance or time'   (sources: D-7)
severity: minor / status: confirmed / lane: physics
where: cafe/reach.py:60,107-110; cafe/app.py:343-363; cafe/static/app.js:242
claim: with V = 1 m/s and a 1.5 m/s northward current, round-trip 6 h shows 124 more cells 'beyond endurance or time' than one-way; the `why` test is only `np.isinf(t)` (outbound).
check: ran on orca (proot, 2 CPUs, stub env, usv, n=61, unlimited battery): one-way 6 h 45 'beyond' cells; round trip 6 h 224 (179 extra), only the launch cell feasible; round trip 60 h still 1 feasible and 480 'beyond', so the label's advice is wrong. Worse sibling found by running: in still water 3364 cells read 'currents/winds too strong or blocked' because `_dijkstra` (reach.py:60) never expands past T and `isinf(t)` calls them 'too strong'; this also affects the one-way and adverse=0.25 maps. Only API clients see `why` (app.js tests only 'land'; the report's `_reach_one` is separate).

fix: in `reach()` keep the back array (`tb = _dijkstra(..., back=True)`) and classify in order: land; 'unreachable: flow too strong or blocked' (outbound inf and not merely past the cutoff, which needs a flag from `_dijkstra` or T_s = inf); 'no way back: flow too strong to return' (t finite, tb inf); 'beyond endurance or time' only when total is finite and > T. Keep the `hours` NaN grid unchanged. Tests: c > V round trip downstream cells read the new label; still-water far cell reads 'beyond'.

sources: D-7


### M-33. `implicit_midpoint` does not converge for dt|w| < 1 as documented; it fails for ill-conditioned inertia at dt|w| = 0.3   (sources: D-8)
severity: minor / status: confirmed / lane: numerics
where: cafe/pm/physics/rigid.py:22-30; cafe/dyn.py:~296-298; tests/test_dyn.py
claim: 4000 random diagonal inertias (ratios up to 1e3), dt = 0.1, dt|w| = 0.3: 1817 raise `RuntimeError 'dt |w| is too large'`; first: I = diag(3.734, 0.013, 1.545), w = (-2.27, -1.69, -0.98).
check: ran a copy of the function on the laptop (scratchpad `d8.py`, not orca): 1000 draws each at dt|w| = 0.3 fail 0 for ratio 1 (the test's diag(2,3,5)), 4 for ratio 10, 113 for ratio 50, 467 for ratio 1000. The fixed-point contraction constant is about dt/2 * ||d omega_dot/dw||, which carries the inertia ratios, so the docstring bound and the error text blame the wrong quantity. Only `tests/test_dyn.py` calls `implicit_midpoint` (dt 1e-3, plus a dt = 50 refusal); no pipeline code. `dyn.py` does the same solve with exactly 3 iterations and no check, silently, at dt of 1e-3 to 2e-3 well inside the safe range.

fix: in `rigid.implicit_midpoint`: cheap, correct the docstring (contracts when about dt/2*||d omega_dot/dw|| < 1, which depends on inertia ratios) and the error text; robust, Newton on the 3x3 residual with the analytic Jacobian (or Newton after the fixed point fails). Test: the I = diag(3.734, 0.013, 1.545), dt = 0.1 case, invariants conserved to 1e-12; the dt = 50 refusal test needs a new refusal case if Newton converges. Fix the `dyn.py` comment too. DECISIONS and CHANGELOG one line each.

sources: D-8


### M-34. A zero time budget returns a map where every cell is reachable in 0 h   (sources: D-9)
severity: minor / status: partly / lane: robustness
where: cafe/reach.py:88-92,102-108; cafe/app.py:124-125,350; cafe/hangar.py:41-44
claim: `reach(veh, env, 10, -95, hours=0.0, n=9)` gives radius_km 0 and all 81 cells at 0.0 h; `T = min(hours, endur)` is 0 for `battery_wh = 0` the same way.
check: not run; follows from the code (T = 0 makes the grid a single point and every edge cost 0). No live caller can supply T = 0: `/api/reach` refuses `hours <= 0` and NaN, `clean_spec` returns 400 for a zero value, `hangar.check` refuses `battery_wh <= 0` before characterisation, the report path (`_reach_one`) does not call `reach.reach`, and `receipts.py:559-560` uses 12 h. So it is a missing guard on a direct call. A negative reserve or a reserve above 1 is likewise unvalidated. Rows 113 and 216 do not mention T = 0.

fix: in `reach.reach`, after computing T: `if not T > 0: raise ValueError('no time or energy budget: nothing is reachable')` (app.py already maps ValueError to 400). Test: `hours=0.0` and `battery_wh=0` raise. CHANGELOG line only.

sources: D-9


### M-35. The reach search extends to 400 km but the loaded weather box is 4 degrees; beyond it the edge value is held silently   (sources: D-10)
severity: minor / status: partly / lane: data
where: cafe/reach.py:90-95; cafe/app.py:355-376; cafe/env.py:109-111,270-271; cafe/pm/report.py:784
claim: `Env(..., lat +-3.8, lon +-3.8, pad_deg=0.2)` holds +-4.0 deg, `reach` sets R = min((V+2.5)T*3600, 400 km) and `Env.at` clips to the nearest edge; E-W half-width is 315 km at 45N and 223 km at 60N; a UAV at 20 m/s for 6 h reaches 432 km.
check: read, not run (needs WRF files on orca; the argument is arithmetic). Overstated: R is a search radius, a cell is drawn reachable only if `_dijkstra` gets there inside T; below about 25.8 N/S the 400 km grid lies inside the box; no shipped platform reaches the edge (USV about 121 km plus current, gliders 0.23 m/s, the quad about 36 km per sortie). Real only for a user-built fast vehicle at high latitude. The pipeline's `_reach_one` masks with `env.inside` already, so row 113 ('outside the ingested data counts as unknown') is true of the report and false of the legacy `/api/reach`.

fix: in `reach.reach`: build an `inside` mask from `E.lat/E.lon` (lon360), treat outside cells as blocked with `why = 'outside weather data'`, or cap R at the box half-width `min(400 km, 3.8 deg*111.3*cos lat)`. Test: a fast long-endurance vehicle at lat 50 reaches no cell beyond the box. May shrink the drawn reach and change tests pinning `radius_km` or grid size.

sources: D-10


### M-36. `dtmb5415` tabulate/row_notes/receipts raise raw KeyError/TypeError/ValueError on a damaged speed entry although `read_run` promises a damaged file is 'not there'   (sources: D-11)
severity: minor / status: confirmed / lane: robustness
where: cafe/pm/dtmb5415.py:537 (`read_run`), :551-559, :600-609, :620-625, :656-657; cafe/pm/credibility.py:332
claim: a speed entry that is an int, a missing `ct` or `cells`, `ct` null or 'x', `ct_std` null, `cells` 0, or `drift` 'x' end the receipts and the DTMB report in a traceback.
check: ran on orca (detached worktree at 01a39c0): entry 5 gives TypeError from receipts; missing `ct` KeyError in tabulate, row_notes and receipts; missing `cells` the same; `ct` null TypeError in all three; `ct_std` null TypeError in tabulate and receipts; `cells` 0 ValueError in all three; `drift` 'x' ValueError only in receipts; `y_plus` 'hi' not run (same `float()` path). `credibility._dtmb_rows` also calls tabulate and row_notes with no try, so the credibility table crashes too. Needs a hand-edited file; round 9 L0 applied one level deeper.

fix: in `read_run` (reached by `_runs` and `stale_files`) validate each per-speed entry after the `speeds` dict check: a dict, `ct` real (NaN and inf allowed, round 13 M-27), `ct_std` optional, `cells` positive real, `y_plus`/`drift`/`drift_parts`/`scatter` None or numeric; else return None so the file is 'unreadable (rerun the grid)'. Parametrized test over the damage list. Do not tighten past what `run_grid` writes (NaN/inf ct, missing ct_std, None optionals).

sources: D-11


### M-37. Domain edges: EASI n=4 crashes and n=5 returns S1 = 1 for noise; `wilson`, `n_certify`, `shares.main` traceback on bad arguments   (sources: D-12)
severity: minor / status: confirmed / lane: robustness
where: cafe/pm/stats/sensitivity.py:15-18,28-35; cafe/pm/stats/intervals.py:54-70,94-102; cafe/pm/shares.py:64-70; cafe/pm/stage1.py:728,742
claim: `first_order(random(4,2), random(4))` gives ZeroDivisionError (lam = 1) and n = 5 gives [1.0, 1.0] for independent noise; `wilson(5,3)`, `wilson(0,0)`, `newcombe_diff` n = 0, `n_certify(0.0)` and `n_certify_one_sided(conf=1.0)` raise; `shares.main(['0', out])` and `['²', out]` raise ValueError, a truncated junit raises ParseError, all uncaught (the convention is usage and exit 2).
check: ran on orca (proot, 2 CPUs): n = 4 ZeroDivisionError; n = 5 mean S1 1.0 over 200 noise draws (96% exactly 1.0); n = 6 [0.96, 0.99]; n = 8 and 16 sane; `noise_floor` n = 4 ZeroDivisionError; the rest as filed; the truncated junit was not run. Unreachable from the pipeline (`SENS_MIN_N = 16`, `intervals.interval` validates). Siblings: `agresti_coull` (n = 0 or k > n), `rule_of_three(0)`, `extreme_ranks`, `default_harmonics` at tiny n. No DECISIONS row covers n < 16 (72 says n >= 16).

fix: `sensitivity.first_order`: refuse n < 16 or `lam >= 1` and share `SENS_MIN_N` from `stats.sensitivity` with stage1.py; `intervals`: one `_check(k, n)` for `wilson`, `agresti_coull`, `newcombe_diff` (same `ValueError` as `interval`) and range checks in `n_certify*`; `shares.main`: ASCII-digit K >= 1, catch `ParseError`/`OSError`, usage and exit 2. One test per function. Check `tests/test_stats*.py` and the exact-Wilson mutation tests for calls at small n.

sources: D-12


### M-38. Tests stay green when the D-lane statistics corrections are removed   (sources: D-13)
severity: minor / status: not_confirmed / lane: tests
where: tests/test_stats.py:391-440; tests/test_round14_survivors.py; tests/test_stats_exact.py:396-421,494-512,732-787; cafe/pm/stats/rare.py:42; sensitivity.py:29; sampling.py:51,91
claim: mutants SURVIVED: `rare._gamma` without the `(1-k*nc/n)` weight, EASI `lam = 2m/n` to `m/n`, `_check_factor` `abs(e[f])>=1` to `>1`, `SUPPORT_SD` 6.0 to 3.0.
check: read the tests and reasoned; no mutant was run and no worktree created. The reviewer ran a subset (test_stats.py, test_round14_survivors.py, test_config.py). `tests/test_stats_exact.py` kills each of the four: hand-worked `_gamma` chains to 1e-12 and an Au and Beck reimplementation (:494-512), `easi_reference` with `lam = 2*m/n` (:396-421), the `lo = -1.0` message 'not a percent' (:740), and 'mean - 6 sd = -1.45' text (:744-745, 785-787). The survivors do not match this checkout.

fix: none (not confirmed). no fix needed. To confirm, re-run the rev_d9 mutants with `tests/test_stats_exact.py` included; optionally add a pointer comment in `tests/test_stats.py` near :437 to the exact tests.

sources: D-13


### M-39. Tests stay green when `reach.py` glider band, reserve, hold and corner rules are broken   (sources: D-14)
severity: minor / status: confirmed / lane: tests
where: tests/test_reach.py; cafe/reach.py:33-34,47,98-100,111; cafe/receipts.py:548-560; REVIEW.md rows 7-8
claim: `linspace(top,bottom,6)` to `linspace(top,top,6)`, `battery_wh*(1-reserve)` to `battery_wh`, hold `0.8*V` to `1.0*V`, and the diagonal rule `and` to `or` all survive `tests/test_reach.py`.
check: ran on orca (proot, 2 CPUs, detached worktree at 01a39c0), one mutant at a time with `pytest -x`: all six survive, the four filed plus glider hotel power `+1.0` to `+100.0` (:33) and the default `glide_band (5,100)` to `(5,5)` (:98); also with `tests/test_report.py -k reach` added. The test fixture patches `endurance_h` to 1e9 and builds only a USV, so the reserve and the glider branch never run; uniform-flow geometry cannot tell 0.8 from 1.0. The diagonal `or` mutant fails safe (over-blocks), so the missing test asserts a one-corner diagonal IS allowed. The pipeline's own glider band (`report._reach_one`) is killed by `test_report.py -k reach`. `reach.py` is outside the mutation and coverage gates (row 205).

fix: tests only, in `tests/test_reach.py`: (1) a glider with `limits={'glide_band': (a,b)}` and a depth-dependent `Env.at`, asserting flow_max or hours equal the mean over `linspace(top,bottom,6)`; (2) `endurance_h` unpatched, asserting `battery_wh*(1-reserve)/P` for a USV and a glider (hotel_w + 1.0); (3) a hold test with flow between 0.8*V and 1.0*V; (4) a one-corner diagonal allowed. Pins the assumed 1.0 W and 0.8 factor; DECISIONS row and CHANGELOG line per CLAUDE.md.

sources: D-14


### M-40. Tests stay green when whatif longitude wrapping, the UAS period float dust guard or the AnalyticEnv current profile is broken   (sources: D-15)
severity: minor / status: confirmed / lane: tests
where: cafe/pm/whatif.py:91-92,145,151,154,156,185,277,290; cafe/pm/env/protocol.py:44; tests/test_whatif.py:138-151; tests/test_environment.py; tests/test_stage1.py
claim: `_wrap` to identity, `math.ceil(x - 1e-9)` to `math.ceil(x)` in `_duty_days` (row 733) and the profile depth 1000 to 500 m (row 727) all survive.
check: ran three mutants on orca (detached worktree at 01a39c0, proot, 2 CPUs): each passed its tests with rc 0. The only test moving a position by `dlon` uses a ship at -165 moved by -0.5 or -0.2; `test_whatif.py:151` builds its expectation with `whatif._wrap` itself (circular); the demo box straddles the line but ordinary moves never need `_wrap`. No ordinary every/duty pair differs between the ceil forms, so the guard is defensive. `AnalyticEnv._profile` is test-only and nothing pins 1000 m. The reviewer's lane label (documentation) is wrong; these are coverage gaps. The reviewer's list of killed mutants was not rerun.

fix: tests only: `whatif.apply` with a glider at -170 and `dlon = -25` (or the ship at -165, large westward) asserting a literal such as 165.0, and +180 to -180 for a station and a waypoint; `_duty_days` with `every = 3.0000000000000004, duty = 1` expecting 3.0, plus the fraction and exact cases; `AnalyticEnv` current at z = 0, -500, -1000, -2000 expecting 1, 0.5, 0, 0. Files `tests/test_whatif.py` and `tests/test_environment.py`; no DECISIONS row contradicted (727, 733 state these).

sources: D-15

---

## Root causes


### RC-1. A shared function or loader does not validate what its readers index or rely on (domain, finiteness, range, type)
findings: M-4 (A-2), M-5 (A-3), M-17 (C-4), M-19 (C-6), M-28 (D-3), M-30 (D-5), M-34 (D-9), M-36 (D-11)
one place: the check belongs at the entry every caller goes through: `config.load_mission` plus a shared period/dive check (A-2, D-5), `orca.real_numbers` (A-3), `fea.solve` (C-4), `refit.pool` (C-6), `whatif.answer` (D-3), `reach.reach` (D-9), `dtmb5415.read_run` (D-11).
siblings: `_wrf_notes` bool reads (A-3), the zero-spread clamps inside `refit()` (C-6), `whatif.apply` not re-running the config.py dive and period checks (D-5), report/credibility writers using the same `isinstance(x, (int, float))` idiom (report.py:233/241/249/385/390, credibility.py:686/691, pipeline.py:721), `subgrid._pool`, `agresti_coull`.


### RC-2. Text typed by hand states something the code does not do (comments, docstrings, DECISIONS rows, schema, yaml rationale)
findings: M-3 (A-1), M-8 (A-6), M-9 (A-7), M-12 (B-3), M-13 (B-4), M-16 (C-3), M-22 (C-9), M-26 (C-13), M-31 (D-6), M-33 (D-8)
one place: the claim sits in one sentence per finding: the `_link_hs` docstring and row 651 (A-1), rows 739/706/136/176 (A-6), the `hangar.bem` comment (A-7), the `fea.py` docstring and `__main__` (C-3), `mission.json:60` (B-4), the `rigid.py` docstring (D-8), the `_whole_days` message (D-6); B-3, C-9 and C-13 need one documentation line or section in PHYSICS.md, not a code change. Adopt the rule that a row narrowing an earlier claim adds 'amended by' to the older row.
siblings: CHANGELOG.md:692 repeats row 651; the `dyn.py` 3-iteration comment (D-8); `quad_uas.yaml:108` and `:119` (B-1); `assumptions.yaml` provenance strings (C-14); PHYSICS.md:751 (A-2); rows 504 and 648 (A-6).


### RC-3. Related limits and models are set in different places and nothing ties them (mesh, buckling factors, dive depth, airspeed, stage 1 versus stage 3)
findings: M-10 (B-1), M-11 (B-2), M-14 (C-1), M-15 (C-2), M-23 (C-10), M-25 (C-12), M-27 (C-14)
one place: one source per quantity: the hull FEA mesh read by both `hangar.py` and `pipeline_windows._fea` (C-1, C-14), the buckling factor in `fea.solve` (C-2) and its stress output (C-10), a single hull-collapse/rating depth for `config.py:577` and `glider.py:293` (B-2), one airspeed helper shared by stage 1 and stage 3 (B-1), and removal of the second FEA entry point `run_windows` (C-12). C-1, C-2 and the knockdown must be reviewed together or the error only moves.
siblings: `hangar.py:162` (L/70 against L/20), `receipts.py:479/501` (scaled factor), `whatif` duty moves that order a dive beyond the hull (D-5), `launch_rule.max_mean_wind_ms` (B-1), glider_2n (checked, unaffected).


### RC-4. A rule or label is applied by each caller, or inferred from a weaker signal, instead of being held in the shared function
findings: M-21 (C-8), M-24 (C-11), M-1 (D-1), M-2 (D-2), M-32 (D-7), M-35 (D-10)
one place: the verdict rule in `intervals.py` (D-1), the not-judged rule in a helper shared by `receipts()`, `credibility._dtmb_rows` and the report (D-2), the `why` classification in `reach()` (D-7) and its inside-the-data mask (D-10), one `_sigkill_is_deadline` helper for the two child sites (C-8), the FEA-runs test where the reserve is subtracted (C-11).
siblings: `verdict_from_p` callers in `emulator.py` and `whatif.py` (D-1), the third copy of the not-judged rule that a quick fix in `main()` would add (D-2), the same unclamped grid in the adverse=0.25 call at `app.py:363` (D-7, D-10), `budget.py:186` (declared basis, not a bug).


### RC-5. Tests pin only the input that triggered the fix
findings: M-7 (A-5), M-38 (D-13), M-39 (D-14), M-40 (D-15)
one place: tests only: `tests/test_acceptance.py`, `tests/test_stats_exact.py`, `tests/test_stage3.py` (A-5), `tests/test_reach.py` (D-14), `tests/test_whatif.py` and `tests/test_environment.py` (D-15); D-13 is not confirmed (the exact tests kill the four mutants) and needs only a re-run of the mutants with `test_stats_exact.py` included.
siblings: other errno tuples and field-name tuples in `acceptance.py` and `stats/sampling.py` (A-5), `reach.py` is outside the mutation and coverage gates (row 205) so any further rule there is unpinned, the `tao.manifest_shape` positions/mode clauses (killed only by `test_pipeline.py`).


### RC-6. Longitude is reduced without a reference, so the antimeridian breaks it
findings: M-20 (C-7), M-29 (D-4)
one place: one `lon_median` helper beside `report._unwrap` (C-7) and a magnitude bound in `whatif._numbers` (D-4); the demo box 165E..165W makes both live.
siblings: `pipeline.py:1351` (window lon, a printed-number risk), `report._median_track`, `whatif.py:285-290` (base track under a change), `config._in_box`.


### RC-7. The atomic writer's temporary name depends on the target name
findings: M-6 (A-4)
one place: `cafe/atomic.py:17`: a short fixed-length temporary name in the same directory.
siblings: `emulator.py:96` (same 21-character suffix), `env/orca.py:232`, `env/hycom.py:225`, `ledger.py:131`, `ocean.py:127`, `env/bathy.py:139`, `env/orca.py:263`.


### RC-8. Small-sample statistical estimators have no stated or enforced domain
findings: M-18 (C-5), M-37 (D-12)
one place: `refit._sigma` gate (C-5, documented limit or a gate at windows < 3) and `sensitivity.first_order` / `intervals` argument checks (D-12), with `SENS_MIN_N` shared from `stats.sensitivity`.
siblings: `refit.py:98/104/71-74` reach the same `_sigma`; `agresti_coull`, `rule_of_three(0)`, `extreme_ranks`, `default_harmonics` at tiny n.

---

## Batches

Four batches (the notes cite the reviewers' source ids; the findings line gives M numbers), no file shared between two of them; the document files (DECISIONS.md, CHANGELOG.md, PHYSICS.md and the other documents) belong to batch D, which also takes the document-side hand-off of every finding. A finding that needs a file another batch owns was put in that batch (B-1 and B-4 share `quad_uas.yaml` and `report.py` with C-7's batch; A-5 shares `test_stage3.py`; D-5, A-2 and B-2 share `config.py`; D-12 and D-1 share `intervals.py`).


### Batch A: stage 1, config, what-if, environment manifests, atomic writer, statistics
- findings: M-1, M-3, M-4, M-5, M-6, M-11, M-28, M-29, M-30, M-31, M-37, M-38, M-40
- files: cafe/pm/stage1.py, cafe/pm/config.py, cafe/pm/whatif.py, cafe/pm/emulator.py, cafe/pm/__main__.py, cafe/pm/physics/glider.py, cafe/pm/stats/intervals.py, cafe/pm/stats/sensitivity.py, cafe/pm/shares.py, cafe/pm/env/orca.py, cafe/pm/env/tao.py, cafe/pm/env/hycom.py, cafe/pm/env/environment.py, cafe/atomic.py, missions/tepex_c_demo.yaml, tests/test_stage1.py, tests/test_config.py, tests/test_whatif.py, tests/test_environment.py, tests/test_stats.py, and the new test files for D-1, A-3, A-4, D-12
- notes: order: D-12 (intervals.py checks) before D-1 (same file), then D-1, A-3 and A-4; D-5 and A-2 share a config.py check function, then B-2. B-2 is an owner decision first (a warning is the lower-risk option); A-1 changes margins and needs a demo rerun. B-2 reads `pipeline_windows.py` and `platforms/seaglider.yaml` and edits neither. The schema description of `every_days` (A-2) is not edited here because `mission.json` is B's. Hand-offs to D: DECISIONS rows 651 (A-1), 164/195 (A-2), 768/819 (A-3), 739/706/817 (A-4), 730 (B-2), 195/731/109 (D-5), 248/399 (D-1) and CHANGELOG lines, PHYSICS.md:751 (A-2).


### Batch B: stage 3, FEA, hangar, UAS platform and sortie model, report
- findings: M-7, M-9, M-10, M-13, M-14, M-15, M-16, M-17, M-18, M-19, M-20, M-21, M-23, M-24, M-25, M-27
- files: cafe/fea.py, cafe/hangar.py, cafe/pm/stage3/windows.py, cafe/pm/stage3/pipeline_windows.py, cafe/pm/stage3/refit.py, cafe/pm/stage3/wallmodel.py, cafe/pm/stage3/freesurface.py (read), cafe/pm/pipeline.py, cafe/pm/report.py, cafe/pm/physics/uas.py, cafe/schemas/mission.json, platforms/quad_uas.yaml, config/assumptions.yaml, cafe/pm/acceptance.py (read), cafe/pm/stats/sampling.py (read), tests/test_stage3.py, tests/test_acceptance.py, tests/test_stats_exact.py, tests/test_budget.py, tests/test_uas.py and a test file for refit
- notes: order: C-3 and C-4 (fea.py first, small), C-2 and C-10 (fea.py and windows.py together, with C-1: one decision on mesh, 3/4 factor and vm_max), C-14 and C-1 (assumptions.yaml), C-12 (windows.py, test_stage3.py), C-11, C-8 (pipeline_windows.py), C-7 (pipeline_windows.py, pipeline.py, report.py), C-5 and C-6 (refit.py), B-1 and B-4 (uas.py, quad_uas.yaml, mission.json, report.py), A-7 (hangar.py), then A-5 (tests only; the NORMAL_MIN test pins behaviour, not the literal). `tests/test_stage3.py` is shared by A-5, C-1, C-8, C-11, C-12 so they stay in this batch. Changing the FEA mesh or factor changes the stage-3 window ledger hash. Hand-offs to D: DECISIONS 730, 741, 776, 792 (C-1, C-2, C-10, C-11, C-12), 137 (C-11), 161 and 237 (B-1), 325 (B-4), 181 (C-5), QUESTIONS_FOR_LAB 4a (C-1, C-2), PHYSICS.md:992 (C-1, C-2), RUNBOOK line 98 (B-4).


### Batch C: reach map, DTMB V&V, rigid midpoint
- findings: M-2, M-32, M-33, M-34, M-35, M-36, M-39
- files: cafe/reach.py, cafe/app.py, cafe/static/app.js, cafe/pm/dtmb5415.py, cafe/pm/vv.py, cafe/pm/credibility.py, cafe/pm/physics/rigid.py, cafe/dyn.py, tests/test_reach.py, tests/test_vv.py, tests/test_dyn.py and a test file for dtmb5415
- notes: order: D-9, D-10 and D-7 in `reach.py` (one pass; D-14 tests land first or with them so the mutants stay killed), D-11 then D-2 in `dtmb5415.py` (D-2's shared helper reads the same validated entries), D-8 last. Hand-offs to D: DECISIONS rows 113 and 216 (D-7, D-9, D-10), 345 and 402 (D-2), CHANGELOG lines.


### Batch D: documents
- findings: M-8, M-12, M-22, M-26
- files: DECISIONS.md, CHANGELOG.md, docs/PHYSICS.md, docs/CREDIBILITY.md, docs/RUNBOOK.md, QUESTIONS_FOR_LAB.md, review/round_15/PROMPT.md
- notes: order: run after A, B and C, because C-13 needs the final FEA numbers (C-1, C-2) and A-6's row 651 sentence needs A-1's outcome. All document-side hand-offs listed in A, B and C land here; new DECISIONS rows are numbered after the last row (825 at db2debd); amend existing rows in place and keep numbering. B-3 and C-9 are 'no code change' findings: one sentence in PHYSICS.md each (becalmed counts cross-track current; the wall-pressure reference is bounded by the nest's rho = 1 anchoring and no total-mass bound exists, row 548). If a document that `tests/test_config_docs.py` reads changes, run that file after D.

Coverage check: M-1 to M-40 each appear in exactly one batch.
- A: M-1, M-3, M-4, M-5, M-6, M-11, M-28, M-29, M-30, M-31, M-37, M-38, M-40 (13)
- B: M-7, M-9, M-10, M-13, M-14, M-15, M-16, M-17, M-18, M-19, M-20, M-21, M-23, M-24, M-25, M-27 (16)
- C: M-2, M-32, M-33, M-34, M-35, M-36, M-39 (7)
- D: M-8, M-12, M-22, M-26 (4)
Total 13 + 16 + 7 + 4 = 40.
