# Round 13 merged findings (BRIEF 5.6 step 2)

Inputs: reviewer_a.md (9 findings), reviewer_b.md (15), reviewer_c.md (13), reviewer_d.md (9). Merged to 45 findings, M-1 .. M-45, from 46 source ids; A-1 and B-13 are the same defect and form M-2. Every source id appears in exactly one merged finding (A-1..A-9, B-1..B-15, C-1..C-13, D-1..D-9).
Each finding was checked by an independent verifier against HEAD 939851e, by reading the cited code and the q13 run files and, for most claims, by reproducing it on cafe-orca (proot, 2 CPUs) in a detached worktree and a private `pm_v13_*` directory (removed afterwards). Static, arithmetic and pure-text claims were checked by reading or locally. The "check" lines are the verifiers' results; this merge re-ran nothing, and severity and status are the verifiers', not the reviewers'. Where a verifier corrected a figure, a line number or a scope, the check says so.
Not covered by any reviewer (their own lists):
- Reviewer A: DECISIONS 641-690 not all mutated (650, 652, 655-659, 663, 676 are documents or "no change" rows; test_config_docs.py not mutated; 661 only for YPLUS_LAM, CALM_SWH_M, FLAT_SHARE_MAX; 665-666 only through the listed remote.py mutants; 686 labels not for GEBCO or OutsideData). 115 hand-chosen single-edit mutants, 83 killed, 19 survived targeted tests (7 are A-3..A-7, 12 equivalent, inert, killed by older tests or a bad mutant). Stage-3 and emulator tests not mutated; only targeted tests plus whole files for survivors, never the full suite. No RUNBOOK run, no acceptance run, no stage-1 or stage-3 computation, no CFD. 50 DECISIONS rows (530-637) read, about 18 checked.
- Reviewer B: RUNBOOK steps 1, 4, 6 by reading only; step 3 fetch, step 5 demo run (forbidden), make bench, make audit, make acceptance, receipts --slow, orca_gate.sh not run. orca_setup.sh and orca_sync.sh only for argument refusals. remote.py identity checks were run against a local ranged server only: what the real orca.atmos, THREDDS, NOAA and CEDA servers send in ETag/Last-Modified/Content-Range on a 206 was not seen, so a spurious "file changed on the server" on a real host is not excluded. New tests not mutation-checked. Credibility factor scorers and stage-1 physics only as far as touched. Prepared but not run: ci-budget variants (vehicles at the data edge, a UAS that never launches, one vehicle). TM=watch reasoned only. Orca load 8-45, timings are upper bounds.
- Reviewer C: no real-data GriddedEnv (synthetic ci_env only); live GEBCO fetch (byte-range and h5py paths read, not run; 0 E and dateline edges by reading); hycom readers and Ocean on a real zarr; par.Pool beyond 2 workers; shares.main with real junit files; ledger.resolve/shared_diff under a moved run directory; emulator, acceptance use of newcombe_diff and report rendering beyond q13 numbers; EASI/Sobol numbers not recomputed (no stage-1 pickles); Mann-box, Stokes, surface-layer code, subgrid, waves out of scope. 92 hand-picked mutants, not make mutation.
- Reviewer D: only the first 42 of 155 tests in tests/test_stage3.py ran (stopped, rc=143); test_emulator, test_reach, test_whatif passed; test_lbm and test_nest not run. No LES window, free-surface case or pipeline FEA window ran. wallmodel.py out of list; cafe/cfd.py external-flow half and OpenFOAM dictionaries skimmed; dtmb5415.py not fuzzed; no mutation runs; cafe/emulator.py (SITL) and planner.py read not run; no 30-day, NaN or zero-wind mission.
INCIDENTS and side effects disclosed by the reviewers (none repaired by this merge):
- Reviewer A: a CLI probe ran `whatif --mission missions/tepex_c_demo.yaml` with no modification, which is a real run, started through PMX=pm_rev13_a2. It outlived the tool call; a kill by exact pid was refused as unverifiable, so it was left to end. /data/emulator/train.parquet was last written at 23:53, before the probe, and pm_rev13_a2/runs did not exist, so nothing shared looks written. Recorded as P-R13A1 in review/orca/PROBLEMS.md. An orca process of about 45+ minutes may be it. Worktree ../cafe-rev13-a, pm_rev13_a, pm_rev13_a2 and runs/rev13_a_* removed.
- Reviewers B, C and D removed their worktrees and orca directories (pm_rev13_b*, pm_rev13_c, pm_rev13_d) and added no PROBLEMS.md row; B and C note up to 3 CPUs used at times beside a long job. Verifiers removed their own pm_v13_* directories and worktrees (several, e.g. C-1, C-8, C-9, C-10, C-2/C-5 style static checks, ran nothing on orca).

Severity: 0 critical, 1 major (M-1), 44 minor. Status: 43 confirmed, 2 partly (M-13, M-30), 0 not confirmed.

---

## Critical

None. No reviewer found one and no verifier raised one.

---

## Major

### M-1. The printed chance that a calibrated emulator misses the coverage gate is about half the true figure at the planned hold-out size   (sources: D-1)
severity: major / status: confirmed / lane: statistics, honesty
where: cafe/pm/whatif.py:450-457 (`_chance_miss`) and :517-519; cafe/pm/pipeline.py:1551; cafe/pm/emulator.py:34-38, :50-54, :189-194; cafe/pm/report.py:999, :1580, :1614; DECISIONS 263, 540; tests/test_whatif.py:1285-1294
claim: `_chance_miss` models hold-out hits as Binomial(n_test, nominal). Split-conformal coverage is itself random, Beta(k, n_cal+1-k) with mean k/(n_cal+1), so the hits are Beta-Binomial. At 100 points: 20 held out, n_cal 16, k 16, coverage 16/17 = 0.941, and the 0.85..0.95 gate on 20 points is missed by chance with probability about 0.53, not the printed 0.2545.
check: arithmetic and Monte Carlo (100k draws) give 0.526 at 20 test points, matching the reviewer. An exact Beta-Binomial with the code's own sizing (points = 5*n_test, n_cal = round(0.2*(points-n_test))) gives 0.527 vs 0.255 printed at 20; 0.666 vs 0.508 at 25; 0.568 vs 0.357 at 28; 0.571 vs 0.359 at 30; 0.424 vs 0.234 at 50; 0.206 vs 0.064 at 100. Correction: the reviewer's 25 and 30 point figures (0.76, 0.68) kept n_cal at 16; n_cal grows with the table, the right figures are 0.67 and 0.57. q13 holdout.json has no trained scope (7 rows, below MIN_ROWS 100), so no run exercises it; no orca run was needed. tests/test_whatif.py:1285-1294 pins the Binomial figure. Severity raised from the reviewer's minor to major by the verifier: a wrong printed number, stored as coverage_chance_fail. The gate and verdicts are unchanged; the error understates how weak a MISSED result is.
fix: in `whatif._chance_miss`: pass `n_cal` (add `sub.n_cal` to `holdout_report`'s output) and compute the miss with `scipy.stats.betabinom` over the same `_coverage_in` set, k = ceil((n_cal+1)*nominal), keeping the single gate rule of DECISIONS 540; Binomial fallback only when n_cal is absent (older holdout.json), labelled. Handle k > n_cal (infinite intervals, coverage 1) explicitly. Regression test: n_test 20, n_cal 16 gives about 0.527 against an exact Fraction or Monte Carlo oracle (fails on 0.2545). Amend DECISIONS 263 and 540 (their figures 0.2545, 0.357, 0.064 are wrong) and add a row and CHANGELOG line. Do not loosen the gate (BRIEF 2.7). Could break: tests or docs pinning 0.255/0.357/0.064; report.py:999 reads the field with `_opt`, so older runs still read.
sources: D-1

---

## Minor

### M-2. The "used by this mission" rule for radios.yaml misses the entry the UAS lost-link hook reads   (sources: A-1, B-13)
severity: minor / status: confirmed / lane: honesty, data
where: cafe/pm/credibility.py:442-466 (`entries_read`), :485-490 (`Facts.__init__` tables), :498-507 (`item_used`); cafe/pm/stage1.py:278-286 (`_uas_radio`), :301, :347; tests/test_credibility.py:805-818 (`test_r12_l0_m6_an_iridium_only_...`)
claim: `entries_read` takes only the mission links. `stage1._uas_radio` reads radios.yaml `rfd900x` (gt_dbi, gr_dbi, misc_loss_db, all assumed) for every UAS sortie whatever the links say. A UAS mission with no rf link, or an rf link naming another radio, counts those 3 inputs as "platform not used"; the Iridium-only test keeps the UAS and asserts none is used, pinning the omission.
check: confirmed by reading; the finding's orca numbers were not re-measured. `Facts.tables` gates the whole "radios" key on rf/iridium link kinds. No other reader of radios.yaml or modems.yaml exists outside links (rf_margin at stage1.py:319 is the UAS hook, :643 rf links). The demo's rf link names rfd900x, so its 273 of 285 is right. DECISIONS 646 and 681 say "when a link reads that entry", so they describe the code as written; 681's "what the verdicts depend on" is the wrong part for the UAS hook. No verdict change, minor stays.
fix: factor the radio-name choice out of `stage1._uas_radio` into one helper next to `comms` (`uas_radio_name(P)`: first `radio` block with `tx_power_dbm`, else `rfd900x`), used by `_uas_radio` and credibility; guard a platform with no radio block (the `next(...)` would raise StopIteration). In `entries_read` (or `Facts`) add ("radios", name) per vehicle platform with a radio block and add "radios" to `tables` then. Test: a UAS-only mission counts exactly the three rfd900x inputs; do not weaken the existing Iridium/rf tests, change them to the new rule. Moves the DECISIONS 681 figures (264/269/283/267, pedigree 77 of 243) by about +3 for a UAS mission; demo 273 of 285 and golden unmoved. New DECISIONS row amending 646 and 681.
sources: A-1, B-13

### M-3. "Items of config/ are used by every mission" is false for dtmb5415.* and class-specific stage3.* keys   (sources: A-2)
severity: minor / status: confirmed / lane: honesty
where: cafe/pm/credibility.py:947 (`build`), :929; cafe/pm/report.py:1688; cafe/pm/budget.py:451-454; cafe/pm/dtmb5415.py:76-83; config/assumptions.yaml:82-92, 203-283
claim: every item of config/assumptions.yaml is marked used, so the 3 `dtmb5415.u_*` keys (read only by the DTMB validation study, never by a mission verdict) and the `stage3.<class>.*` keys of classes the mission does not fly count as used and "verdicts depend on them".
check: confirmed by reading code and q13 credibility.json (`dtmb5415.u_D_rel`, `u_S_rel`, `u_nu_rel` have used=True; 273 includes them). The demo flies every class, so only the 3 dtmb keys are over-counted there; a single-class mission also over-counts other classes' stage3 keys. Caveat: the dtmb keys do feed the V&V 20 DTMB row inside the credibility report, not any mission verdict. DECISIONS 646 states the approximation with a false reason. Not checked: perturbations.yaml priors may have the same problem.
fix: in `credibility.build` give config items a `used` rule: `dtmb5415.*` not used by the mission; `stage3.<class>.*` used only when a vehicle of that class flies (classes are in the plan's `vehicle_classes`); everything else used. Change the "platform not used" label at :929 for config items. Counts follow in report.py unchanged. Alternative that moves nothing: reword the sentence to say config/ items are counted whether or not this mission reads them. Test: a one-UAS mission counts no `stage3.slocum.*` as used; the demo drops 273 to 270; a test that every `stage3.*` key maps to a class or "all". Could break tests with exact totals (test_report.py r12_m6, test_credibility.py) and the numbers in DECISIONS 690 and the golden. New DECISIONS row amending 646.
sources: A-2

### M-4. Coare fade constants CP_MIN 2.0 and CP_FULL 3.5 are pinned by no test   (sources: A-3)
severity: minor / status: confirmed / lane: tests
where: cafe/pm/env/coare.py:42, :145, :195; tests/test_coare.py:267, :281, :283
claim: the new tests read `coare.CP_MIN/CP_FULL` back and check only continuity and a loose bound; the mutant CP_FULL = 3.0 survives all of test_coare.py.
check: the mutant ran on orca in a detached worktree at HEAD: `pytest -q -x tests/test_coare.py` rc=0. The squared-fade mutant was not run, nor the full suite. DECISIONS 653 and PHYSICS.md:163 state 2.0 and 3.5. Other module constants (UMAX, CH1, CH2, A_WAVE, B_WAVE, A_SS, B_SS) are read back the same way and were not checked.
fix: one test in test_coare.py with literals: `(CP_MIN, CP_FULL) == (2.0, 3.5)` and the mid-fade Cd at cp = 2.75 (wmix 0.5) against a hard-coded value or 0.5*Charnock + 0.5*wave from `run()` at cp 2.0 and 3.5 (kills the squared weight and CP_MIN 2.5). A deliberate retune then amends row 653.
sources: A-3

### M-5. Diurnal-jet midpoint 0.2 m/s (DECISIONS 650) is pinned by a test that reads the same attribute   (sources: A-4)
severity: minor / status: confirmed / lane: tests
where: tests/test_surface.py:136; cafe/pm/env/surface.py:244, :292
claim: the assertion is `hypot(jet) == sl.jet_mid * dT0 / sl.jet_ref`; the mutant `self.jet_mid = j['u_max']` (+50 % on every USV jet) survives.
check: ran on orca: test_surface, test_usv, test_ci_env, test_ocean, test_environment, test_vv gave 324 passed, rc=0 with the mutant. test_acceptance.py (golden at demo level) not run. `sl.jet_ref` is read from the code under test the same way (dT_ref_K and the clip are equally unpinned). test_subgrid.py:315 covers the per-member draw, not this path. The per-member draw (M-10 of round 12) is the owner's open call.
fix: tests only. Replace `sl.jet_mid` and `sl.jet_ref` at :136 with independent values (0.5*(u_min+u_max) from `subgrid.load_config()`, a literal 0.2 via approx, the dT_ref_K literal). Will fail on an intended range change, which is wanted.
sources: A-4

### M-6. The receipt stamp test does not require non-empty strings   (sources: A-5)
severity: minor / status: confirmed / lane: tests
where: cafe/receipts.py:81-82 (`missing` comprehension), :91, :94; tests/test_receipts.py:775-776 and r12_m35
claim: the mutant `if k not in rec` survives all of test_receipts.py; no case has host "", git_sha 5 or date null.
check: read only; no mutant run. A non-string git_sha would TypeError at `rec['git_sha'][:10]`; empty strings print " [stored , , git ]". Bad stamps arise only from a hand-edited file; `stamp()` always writes strings. cafe/pm/acceptance.py:339 checks `not source.get("code_digest")` on a different record; cafe/pm/receipts.py:302 has its own reader, not read.
fix: one test next to r12_m35 parametrised over a stamped record with one of date, host, git_sha, code_digest replaced by "", None or 5; `run_crosscheck` returns one context row whose claim says "carries no <field>" and nothing raises. No code change.
sources: A-5

### M-7. The command written into a golden record is not tested to be shlex-quoted   (sources: A-6)
severity: minor / status: confirmed / lane: tests
where: cafe/pm/acceptance.py:352-353 (`_golden_record`); tests/test_acceptance.py:316, :1333-1347
claim: dropping `shlex.quote(mission)` at :353 survives all of test_acceptance.py; the test checks only `endswith('--update-golden')` for a plain path.
check: confirmed by reading; no mutation run (laptop is Python 3.9). The DECISIONS 685 test follows the golden through `check_golden(update=True)` but reads only `summary.mission`, never the stored "command". No other reader of the field; the shipped golden holds a plain-path command. `update_command` and `golden_refusal` advice are covered. DECISIONS 685 names this test as proof of the quoted field; it does not prove it.
fix: in the 685 test after :1346 assert `shlex.split(json.loads(f.read_text())["command"])` has the mission as the word after `--mission` and no extra words. Better: have `_golden_record` use the same builder as `update_command`, but keep the stored command to the base form (mission, gpus, `--update-golden`) so the shipped golden and its digest checks do not move. See M-19 for the missing `--out`, which belongs to the same builder.
sources: A-6

### M-8. Other surviving mutants: `_med` NaN filter, "stage 1 took more than planned" cause, NU_MAX hair, orca M-29 test windows   (sources: A-7)
severity: minor / status: confirmed / lane: tests
where: cafe/pm/env/surface.py:159-163; cafe/pm/report.py:1663 (`_machine_html` causes); cafe/pm/stage3/nest.py:72; cafe/pm/env/orca.py:273, 360, 370-371; tests/test_surface.py, test_report.py, test_nest.py, test_orca.py (`test_r12_m29_*`)
claim: each is a branch a round-12 test says it pins and does not.
check: mutants ran on orca (detached worktree at 939851e): (1) deleting the NaN filter in `_med` passes all of test_surface.py (NaN is live in production, R is `np.full(..., nan)` where no real spectrum); (2) `if s1 and measured > planned` to `if s1` passes -k r12_m9 and all of test_report.py; (3) NU_MAX*(1+1e-6) passes all of test_nest.py; (4) `hour%6` to `hour%3` and `pts is not None` to True pass both M-29 tests but fail the full test_orca.py, so older tests kill them and this item holds only as the finding words it.
fix: tests only. A direct `_med` test with NaN entries and all-NaN; an r12_m9 case with stage 1 within plan but total over budget asserting no "stage 1 took" cause; a nest test at NU_MAX*(1+1e-9) that must raise; an M-29 window with an hour divisible by 3 but not 6 plus a case with pts None asserting no spec_ names. Each must fail on its mutant. The `hour % 6 == 0` selection repeats at orca.py:273, 360, 371; a shared helper would let one test pin all three (optional).
sources: A-7

### M-9. `python -m cafe.cfd WHAT`: any WHAT other than two runs the free-surface study; missing arguments give bare tracebacks   (sources: A-8)
severity: minor / status: confirmed / lane: robustness
where: cafe/cfd.py:637-667 (`main`, the final `else`), :641-643, :661
claim: "externel" falls to the surface branch, starting the OpenFOAM free-surface study and writing a stamped `*.externel.json`. Empty argv gives IndexError; an unknown sample gives KeyError after `work.mkdir`.
check: confirmed by reading the dispatch (`if incidence / elif external / else`); no orca run needed. Docstring says "external|incidence|surface" but nothing checks. test_receipts.py:854-858 calls `cfd.main` only with valid WHATs. Similar bare argv use in emulator.py:403, hangar.py:385, mission.py:642, planner.py:186-198 runs no long solver. DECISIONS 569 and 663 note cfd.py as the old app's module; row 678 (the M-35 stamped writer) is the row this amends.
fix: in `cfd.main` before mkdir: if `len(argv) < 3`, WHAT not in (external, incidence, surface) or sample not in `geom.SAMPLES`, `SystemExit` with a usage line (exit 2); make the last branch `elif what == "surface"`. Test in test_receipts.py: "externel", `[]` and an unknown sample are refused, no file written, `characterize_free_surface` (monkeypatched to raise) not called.
sources: A-8

### M-10. The stated sea-water parameters do not give the quoted eps_c in the two-ray docstring, PHYSICS and QUESTIONS_FOR_LAB   (sources: A-9)
severity: minor / status: confirmed / lane: documentation
where: cafe/pm/physics/comms.py:112-113; QUESTIONS_FOR_LAB.md:119; docs/PHYSICS.md:806; DECISIONS.md row 652 (line 705); tests/test_comms.py:618
claim: eps'' = 60*lambda*sigma = 60*0.32765*5.9 = 116.0 at 915 MHz, not 118.9 (that needs sigma 6.05 S/m). The quoted phases and magnitudes follow 118.9; the printed sigma follows 116.
check: computed directly: |G| differs by under 0.005, phase by about 1 degree (-154.7 vs -154.2 at 2 deg; -87.4 vs -86.4 at 5 deg); test tolerances (abs 0.006, 1.0 deg) pass with either. The same pair sits in five places; no code path consumes eps_c. The error-band figures (7.6 dB, 7.4/23.6, ...) came from the reviewer's outside script and were not re-run.
fix: documents only; pick one set and make the five places agree: sigma 6.05 S/m (smallest edit, no figure moves) or sigma 5.9 with eps_c 72.8 - j116.0 and the table recomputed. Add one assert to test_r12_m12 that `-eps.imag == 60*lam*sigma` for the stated sigma. Amend row 652.
sources: A-9

### M-11. The command printed by the golden messages is refused by the CLI: it lacks the required `--out`   (sources: B-1)
severity: minor / status: confirmed / lane: documentation
where: cafe/pm/acceptance.py:383 (`update_command`), :391-420 (`check_golden` messages), :353; cafe/pm/__main__.py:106-108 (`--out` required=True); tests/test_acceptance.py:305, 1009, 1323, 1327, 1342
claim: the command `python -m cafe.pm acceptance --mission M --gpus N --update-golden` exits 2 with "the following arguments are required: --out". DECISIONS 680/685 claim it cannot be refused and pastes as one command.
check: code reading only; the argparse definition is unambiguous. The tests compare strings or shlex-split them into check logic, never into the parser; only test_cli.py:1175 builds a real argv and it includes `--out`. RUNBOOK.md:256 elides the flags, so the docs are fine. `_golden_record` (:353) keeps a second hand-written copy of the string.
fix: in `update_command` (single builder) add `--out DIR` with the real out directory (`r['dir'].parent`, shlex-quoted; not an angle-bracket placeholder, a shell reads `<` as a redirect); make `_golden_record` use it (base form, see M-7). Test: shlex.split the command, drop `python -m cafe.pm`, feed it to the real parser from `__main__`, no SystemExit. Amend DECISIONS 680/685, CHANGELOG. Could break the string assertions at :305, 1009, 1323, 1327 and :316; the shipped golden's command changes at the next re-mint; reusing the same out dir risks "directory holds runs it did not make", so a fresh sibling dir may be safer.
sources: B-1

### M-12. The report still says a same-name copy of the demo differs in "window, box and vehicles"   (sources: B-2)
severity: minor / status: confirmed / lane: honesty, documentation
where: cafe/pm/report.py:1087 (`_sanity`); cafe/pm/credibility.py:804-820 (`is_the_demo`, `sanity`); tests/test_report.py:1051
claim: since DECISIONS 683 `is_the_demo` compares the whole mission (DEMO_DIGEST); a copy that moves only the ship, a platform, a link or a cut-off still gets "has the demo's name but not its window, box and vehicles", false for exactly those copies. docs/CREDIBILITY.md:191 was updated; the sentence and test were not.
check: static; the branch is deterministic. The test changes only the window end, so it passes. q13 is the unmodified demo and does not touch this branch. The phrase appears in five places; credibility.py and test_credibility.py were not checked for docstring wording. Rows 645 and 683 are history.
fix: change the one string to say the mission has the demo's name but is not the shipped demo mission (something other than seed and description differs). Update the pinned text in test_report.py:1051 and add a case where only the ship or a link differs. Note in 683 or CHANGELOG.
sources: B-2

### M-13. RUNBOOK 7 point 3 (stamping stored results) cannot be followed with the RUNBOOK's own `pm()`; CAFE_APP_RUNS is undocumented   (sources: B-3)
severity: minor / status: partly / lane: documentation, reproducibility
where: cafe/pm/receipts.py:368 (CAFE_APP_RUNS default /work/runs); cafe/receipts.py:99, :640-649; docs/RUNBOOK.md:35-39, :248; pm.sh:28; bin/pmx.sh:21; tests/test_receipts.py:391-395
claim: `make receipts` reads stored CFD/crosscheck files from `$CAFE_APP_RUNS` (default `/work/runs`), mentioned in no document. The step-1 `pm()` mounts no /work, so on a clean machine nothing the RUNBOOK says makes the files count; on pm.sh/pmx.sh /work is `:ro`, so the row's own advice ends in an OSError traceback.
check: documentation gap confirmed (grep finds CAFE_APP_RUNS only in code and one test); `receipts --only app` on orca gave 41 pass, 1 fail (app.fea not_run, known), 8 context, rc=1, with the four stored rows "unstamped: not counted" and the advice paths, which exist on orca because /work is writable there. The OSError claim was not run, only inferred from `stamp_file` -> `os.replace` and the `except ValueError` only. "crosscheck.json has no writer" is a known item; the advice path is correct on orca, unusable only on read-only runners.
fix: RUNBOOK point 3: one sentence that `make receipts` reads those files from `$CAFE_APP_RUNS`, default `/work/runs`; on a clean machine `pm env CAFE_APP_RUNS=/data/work/runs ...` with files under `$CAFE_HOST_DATA/work/runs`, stamped at `/data/work/runs/...`. Say /work is read-only under pm.sh and pmx.sh. Optionally mention CAFE_APP_RUNS in the advice string and catch OSError in the `stamp` CLI branch (see M-14). Do not change the default path (pinned at test_receipts.py:395).
sources: B-3

### M-14. `python -m cafe.receipts stamp`: a read-only directory is a traceback; a symlink is replaced by a stamped copy   (sources: B-4)
severity: minor / status: confirmed / lane: robustness
where: cafe/receipts.py:69-75 (`stamp_file`), :640-650 (catches only ValueError); cafe/pm/config.py:247-251 (`write_json`)
claim: on a chmod 500 directory the stamp gives a PermissionError traceback; `stamp sl.json` on a symlink prints "stamped" but `sl.json` becomes a regular file and `real.json` stays unstamped.
check: ran on orca (detached worktree at 939851e): both reproduced; a chmod 400 file in a writable directory is also replaced by a new 0644 file (extra). Callers inheriting the symlink replacement: dtmb5415 run_grid/prepare, lbm.main, nest.main, receipts.run/write_meta, wallmodel._write_receipt (per DECISIONS 504 and 648, not run); orca.write_json and hycom._write_json are copies of the writer. The caller list comes from DECISIONS (grep failed on a zsh glob). DECISIONS 504 and 648 say write_json is tmp + os.replace for kill safety and keep that.
fix: in `config.write_json` use `p = p.resolve()` (or `os.path.realpath`) before building tmp, covering every caller; in the `stamp` CLI catch `(ValueError, OSError)` and print `os_error_text(e)`. A regression test for each. A resolve moves the tmp to the target's directory (may be read-only; still an OSError, now caught); orca.write_json and hycom._write_json need the same one line or should call config.write_json.
sources: B-4

### M-15. `parse_cdf1` accepts or crashes raw on a corrupt header (negative length read as an empty name, IndexError, KeyError)   (sources: B-5)
severity: minor / status: confirmed / lane: robustness
where: cafe/pm/env/remote.py:270 (`_Buf.take`), :283 (name), :301-332 (`parse_cdf1`), :352 (`cdf1_read`); callers cafe/pm/env/orca.py:168-227, bathy `_rows`
claim: the header comes from a server and its lengths, counts, dimension ids, type codes and sizes are trusted: name length -8 returns an empty name with no error and rewinds the parser; a dimension id out of range gives IndexError; type code 99 KeyError; a negative size gives shape [-3]; `cdf1_read` rec=-1 gives OSError Errno 22.
check: hand-built CDF-1 files on orca (detached worktree, 939851e): all five reproduced. `_Buf.take` never checks n >= 0; a huge positive length fetches that many bytes into memory; a negative shape gives a negative nbytes so a local `f.read(nbytes)` reads the whole file. DECISIONS 665/682/684 cover file identity only; 556 only that parse_cdf1 discards globals. A malformed header never occurs in a good run, so q13 is no evidence. attrs() (m*w with t from `_NC`) has the same trust.
fix: put the checks in the two shared functions. `_Buf.take`: ValueError if n < 0 and a cap (e.g. 64 MiB; must still pass the real 2.5 GB restart header, so test against a real umwmrst header). `parse_cdf1`: turn IndexError/KeyError/struct.error/EOFError/UnicodeDecodeError into ValueError naming the file and check type in `_NC`, dim ids in range, sizes >= 0; the wrapper must not hide the EOFError retry or the identity ConnectionError. `cdf1_read`: require 0 <= rec < nrec and non-negative shape. Tests in test_remote.py with the hand-built byte strings. New DECISIONS row.
sources: B-5

### M-16. `cdf1_header` and `cdf1_read` treat any local path starting with "http" as a URL   (sources: B-6)
severity: minor / status: confirmed / lane: robustness
where: cafe/pm/env/remote.py:337 and :369; callers cafe/pm/env/orca.py:168-227
claim: `remote.cdf1_header('httpx.nc')` raises `ValueError: unknown url type`; a local file or folder named http_cache/... or https-data.nc is unreadable.
check: reproduced on the laptop's Python 3.9 (no file opened, version irrelevant). In the product the argument is a URL by default; a local path reaches these only with CAFE_ORCA set to a relative directory starting "http", or in tests. Only these two lines test the prefix (grep of cafe and bin). No DECISIONS row. Not run on orca.
fix: one helper in remote.py `_is_url(p) = p.startswith(("http://", "https://"))`, used at both sites. Test in test_remote.py: a small CDF-1 file named `httpx.nc` (or in `http_cache/`) read locally by both functions, failing on the current code. Mixed-case schemes: lowercase first if that matters.
sources: B-6

### M-17. `--update-golden` with `--golden DIR --golden-mission NAME` ends in a traceback after the first long run; the golden is written non-atomically   (sources: B-7)
severity: minor / status: confirmed / lane: robustness
where: cafe/pm/acceptance.py:360-374 (`golden_refusal`), :393-396 (`golden.write_text`), :511, :534 (`run`)
claim: `golden_refusal` treats every unreadable existing path as "not a golden file" and `--golden-mission` overrides it, so a directory passes the early refusal, the first quick run (about 20 min) executes, then `write_text` raises IsADirectoryError and the remaining checks never run; `acceptance.json` is not written. `golden.write_text` is not tmp + `os.replace`, so a cut write on a full disk leaves a truncated golden that reads as "not a golden file".
check: ran on orca (detached worktree): `golden_refusal(dir, 'm', 'm')` returns None; `check_golden(r, dir, 'm.yaml', True, 'm')` raised IsADirectoryError (with `_golden_record` stubbed, since the fake run had no report.json; without the stub FileNotFoundError comes first, so only the write site is proved). The 20-min timing is from reading `run()`. The same bare `write_text(json.dumps(...))` appears at acceptance.py:568, audit.py:433 and :490, credibility.py:973, report.py:1805; ledger.py:175, :344 and receipts.py:276 write a tmp first. DECISIONS 673 does not list a directory; 680 and 685 only shape the printed command.
fix: in `golden_refusal` after the exists test: `if not golden.is_file(): return f"{golden} is not a file: not written"` so `run()`, `check_golden` and `update_command` agree. Replace `golden.write_text(...)` with `config.write_json(golden, _golden_record(...), indent=1, allow_nan=False)`, checking it can append the trailing newline (otherwise tmp + `os.replace` by hand); pin the output bytes, since the "byte for byte" claim in 685 and the golden digest depend on it. Tests: a directory with golden_mission returns a refused row and starts no run; a write killed halfway leaves the old golden. Amend 673, CHANGELOG.
sources: B-7

### M-18. `remote.download` of an empty file and into a missing directory give misleading errors   (sources: B-8)
severity: minor / status: confirmed / lane: robustness
where: cafe/pm/env/remote.py:55-56 (`_open` maps 403/404/416 to FileNotFoundError), :113-120 (`_probe`), :130, :139, `download` :221-230
claim: a 0-byte upstream file answers the `bytes=0-0` probe with 416 and raises FileNotFoundError "<url>: HTTP 416"; a destination directory that does not exist raises FileNotFoundError naming `.../nodir/f.part.id`.
check: confirmed by reading (no job run). The only production caller (tao.py:166) does `p.parent.mkdir(exist_ok=True)`, so the missing directory is reachable only by direct callers and tests. DECISIONS row 19 is a different case (nonempty file, empty body). `size()` and `RemoteFile.__init__` share the 416 mislabel; `_read_ident` and the CDF reader rely on `_open`'s 416 behaviour, so `_open` must not change; tao.py:73 uses `_open` without Range.
fix: (a) in `_probe` catch the 416 FileNotFoundError from the `bytes=0-0` request and return `(0, {})` (corrects `size()`, `RemoteFile` and `download` together); (b) in `download` call `path.parent.mkdir(parents=True, exist_ok=True)` before the first `mark.write_text`, and for total == 0 touch the part file because the loop is skipped and `os.replace(part, path)` would fail. Check that a size-0 `RemoteFile` reads and seeks. One regression test each in test_remote.py.
sources: B-8

### M-19. The unstamped crosscheck.json row says to rerun a program that does not write it   (sources: B-9)
severity: minor / status: confirmed / lane: documentation, honesty
where: cafe/receipts.py:98-99 (one advice string for every file), :343, :354, :365, :627; comment at :49-50; docs/RUNBOOK.md point 3; tests/test_receipts.py around :773, :867
claim: the Emulator row "stored result crosscheck.json (unstamped)" says "rerun the run that writes it (python -m cafe.cfd stamps its file)", but `cafe.cfd` writes only torpedo.external.json, wigley.surface.json and suboff.incidence.json.
check: read; the advice is a constant depending only on the path. PROMPT.md lists "crosscheck.json has no writer" as known; B-9 is that the printed advice contradicts it. Tests check only the word "unstamped". The stale case has the same wrong advice. No other copy of the advice text found (the grep of md files agreed).
fix: in `stored()` make the advice depend on the file (optional `writer` parameter or `path.name` in the three cfd names). For crosscheck.json: "redo the SITL cross-check by hand (no program in the repo writes this file), or, if you have checked it, python -m cafe.receipts stamp PATH". Test: the row's source for crosscheck.json does not mention cafe.cfd; for a CFD file it still does.
sources: B-9

### M-20. RUNBOOK 7 point 2 still gives round 11's clean-orca receipt counts (350 rows, 287 passing, 33 context)   (sources: B-10)
severity: minor / status: confirmed / lane: documentation
where: docs/RUNBOOK.md:208, :246, point 3; STATUS.md:56
claim: `make receipts` on orca at HEAD (2 CPUs, no slow group stored) prints "273 pass, 30 fail, 32 context (335 rows)" in about 11.5 min; the RUNBOOK says 287/30/33 of 350 and "about 17 min".
check: ran on orca at 939851e: exactly those counts; the 30 failures are DTMB convergence/U_val rows, NOT STORED lbm/nest/wallmodel rows. The wrapper recorded rc=1, not the reviewer's exit 2; the RUNBOOK says only "non-zero". STATUS.md:56 repeats the stale numbers; docs/CREDIBILITY.md:181's 287 is the unrelated input catalogue.
fix: edit RUNBOOK 246 to "273 pass, 30 fail, 32 context (335 rows)", RUNBOOK 208 to about 12 min, give the new total in point 3, same in STATUS.md:56, and say the totals move with every change to the app group's stamped files. Re-measure at code freeze (the run costs 12 min).
sources: B-10

### M-21. A symlink loop in a run directory is a RuntimeError traceback in audit and report   (sources: B-11)
severity: minor / status: confirmed / lane: robustness
where: cafe/pm/audit.py:115, :205, :221, :226-227 (`_stage_problems`, `ledger_problems`); cafe/pm/ledger.py:338, :340
claim: `ln -s windows windows` in a copy of a run makes `python -m cafe.pm.audit --ledgers-only` and `python -m cafe.pm report --run` both exit 1 with "RuntimeError: Symlink loop"; the other 17 damages tried give a clean error.
check: ran on orca (copy of q13, detached worktree): both end in the traceback at audit.py:205 (`.resolve()`); `ledger_problems` catches only `_Unreadable` and `(KeyError, TypeError, AttributeError)`. Python 3.12 non-strict `Path.resolve` raises RuntimeError on ELOOP (3.13 raises OSError); `exists()` and `is_file()` swallow ELOOP. No DECISIONS row. Other `.resolve()` calls act on repo or user paths, lower risk.
fix: one helper in ledger.py (`real(p) = pathlib.Path(os.path.realpath(p))`, non-strict never raises on loops) used at audit.py:115, 205 and ledger.py:338, 340; the loop then shows as the existing "is missing" problem lines. Test: a tmp run copy with a self-symlinked windows dir; `ledger_problems` returns lines, audit main returns 1. Adding RuntimeError to the except tuple would fix the audit only and leave ledger.py:338/340.
sources: B-11

### M-22. `validate`: a long vehicle list is echoed whole, 64 vehicles is an undocumented limit, deep YAML is a RecursionError traceback   (sources: B-12)
severity: minor / status: confirmed / lane: robustness, documentation
where: cafe/schemas/mission.json:40 (maxItems 64); cafe/pm/config.py:69-79 (`_yaml`), :126-136 (`_say`, `validate`); cafe/pm/__main__.py:181; docs/RUNBOOK.md:96
claim: 65 vehicles gives a ConfigError of 15,040 characters, 3,000 gives 694,992 (the repr of the whole list plus "is too long"); `a: [[[...3000 deep]]]` gives a RecursionError traceback.
check: ran on orca (scratch worktree) with `python -m cafe.pm validate`; all figures reproduced (64 pass the vehicle schema and give a short links error). `_say` ends in `str(e.message)` and jsonschema embeds `repr(instance)`; `_yaml` catches only YAMLError, UnicodeDecodeError, OSError, ConfigError. `__main__.py:181` deliberately keeps tracebacks for non-ConfigError. No document states the 64 limit (only a 64-character name, DECISIONS 373). Sibling: any schema error on a big instance echoes (long strings, wrong-type lists); every `read_yaml` caller shares the RecursionError gap.
fix: in `config._say` truncate the message to about 200 characters + "..." and for maxItems name the limit and `len(e.instance)`; in `config._yaml` catch `RecursionError` at the `yaml.load` call and raise ConfigError "nested too deeply to read". Add one sentence to RUNBOOK:96 and the schema description stating the 64-vehicle limit. Tests: 65 vehicles gives an error under 1 kB; deeply nested YAML gives a ConfigError. Search tests for messages matched in full with a repr; keep the field path and reason visible. DECISIONS row, CHANGELOG.
sources: B-12

### M-23. The OutsideData message, printed as "error:" by main, names a command that does not exist (`cafe fetch`)   (sources: B-14)
severity: minor / status: confirmed / lane: documentation
where: cafe/pm/env/environment.py:142 and :316; cafe/pm/__main__.py:173, :311; docs/BRIEF.md:148, :246
claim: both messages say to run `cafe fetch`; there is no cafe script or `cafe/__main__.py` and pyproject has no console entry. The real command is `python -m cafe.pm fetch --mission <file>`, which `__main__.py:311` already prints correctly.
check: static; not run on orca. No test asserts "cafe fetch". DECISIONS 442 covers only `cafe validate` and `cafe fetch --full`, not plain `cafe fetch`. BRIEF.md:148 and :246 keep the old name, unamended. Exactly two sites; docs/RUNBOOK has none.
fix: replace both strings with `python -m cafe.pm fetch --mission <mission.yaml>`; optionally one module constant `FETCH_CMD` reused at `__main__.py:311`. Test: raise OutsideData from both sites, assert "python -m cafe.pm fetch" in the text and bare "cafe fetch" not. Check the wording-change guard at tests/test_ledger.py:695 before editing. Note on DECISIONS 442, CHANGELOG.
sources: B-14

### M-24. A stamp naming no commit (git_sha "none") is a valid stamp, and the README workflow writes exactly that   (sources: B-15)
severity: minor / status: confirmed / lane: reproducibility, honesty
where: cafe/receipts.py:91 (`stored`, non-empty-string test); cafe/pm/ledger.py:33-39 (`git_sha`); cafe/pm/receipts.py:~304, :438; cafe/pm/credibility.py:748; cafe/pm/acceptance.py:337; run.sh; README.md:173
claim: `./run.sh` passes no CAFE_GIT_SHA and the synced `cafe/` has no .git, so `stamp()` writes git_sha "none" with a code_digest, and `stored()` accepts it as a pass ("[stored ..., git none]"). An empty CAFE_GIT_SHA (proot_run.sh, pm.sh when `git rev-parse` fails) gives "" which `stored()` rejects, so "none" and "" are treated differently.
check: ran on orca from a detached worktree: `R.stamp` gives "none" and the container id as host, `R.stored` accepts it with no context row. The repo already treats "none" as no commit in credibility.py:748 and acceptance.py:337 (40 hex digits). code_digest still ties the stamp to the code, so only the provenance text is weak. README and RUNBOOK `pm()` wrappers pass `$(git rev-parse HEAD)` unguarded and can pass "". Other readers: pm/receipts.py slow_group, report.py:1058 ("Code: git none"), ledger.py:117, pipeline.py:1465. No DECISIONS row requires accepting "none".
fix: in `ledger.git_sha()` treat blank and "none" alike and add a predicate `has_commit(s)` (hex, 7 or more characters); use it in `cafe/receipts.stored`, the `cafe/pm/receipts.py` read path and credibility.py:748 so a no-commit stamp becomes an unstamped context row whose advice says to run via pm.sh/pm() or set CAFE_GIT_SHA. Make `run.sh` pass `-e CAFE_GIT_SHA=$(git rev-parse HEAD)` and `CAFE_GIT_DIRTY`. Test: stamp with the variable unset in a no-.git copy, `stored()` returns None with a context row. Existing results carrying "none" become context rows (rerun or `stamp FILE`). tests/test_ledger.py:197-203 pins the "none" fallback and test_receipts fixtures use short shas like `'abc' * 14`; accept 7 or more hex characters. New DECISIONS row, CHANGELOG.
sources: B-15

### M-25. `GriddedEnv.air` returns the relative sigmas of Q2 and SWDOWN as absolute uncertainties   (sources: C-1)
severity: minor / status: confirmed / lane: honesty, data
where: cafe/pm/env/environment.py:206 (`tag("Q2", s["q2_frac"])`, `tag("SWDOWN", s["swdown_frac"])`), :284; cafe/pm/__init__.py:19; config/assumptions.yaml:117, :127; tests/test_environment.py:251
claim: `Tagged.uncertainty` is documented as 1-sigma in the value's units, but q2 (about 0.017 kg/kg) carries 0.1 and swdown (to about 949 W/m2) carries 0.2.
check: read the code; no orca run (plain from the code). Hs is done correctly (`s["hs_frac"] * hs`). Nothing prints these (report.py:856 reads wind, Hs, current); air() consumers read only `.value`. The only air sigmas tested are T2 and glw. Other fractional sigmas: only these three; surface.py:275 builds its own correctly. No DECISIONS row mentions q2_frac or swdown_frac.
fix: in `air()` make the local `tag()` multiply fractional sigmas by the value (`rel=True`): `Tagged(q2v, src, s["q2_frac"] * q2v)`, same for swdown. Test: extend test_air at test_environment.py:251 with `allclose(a["q2"].uncertainty, s["q2_frac"] * a["q2"].value)` and swdown. The uncertainty becomes an array; no scalar consumer found. Swdown at night gives uncertainty 0.
sources: C-1

### M-26. `par.py` says a queued task's maps stay alive in the parent, but `Pool.submit` keeps only the pickled bytes   (sources: C-2)
severity: minor / status: confirmed / lane: robustness, documentation
where: cafe/pm/par.py:10-11 (docstring), :140-146 (`_release`), :231-236 (`Pool.submit`); callers stage1.py:362, :470-490, pipeline.py:172, env/ocean.py:68
claim: after `del a; gc.collect()` the queued task's `/tmp/cafe-share-.../0.npy` is unlinked before the worker opens it: `f.result()` raises FileNotFoundError.
check: reproduced on orca (PM_CPUS=2, load 49): `Pool(2)`, `adopt(np.ones(400000))`, two slow tasks, `submit(total, a)`, `del a`, `gc.collect()` raises FileNotFoundError. Real callers are safe by frame lifetime (env stays bound until every `.result()`), so the invariant is unenforced, not violated. Only `Pool.submit` has the gap (module-level `par.submit` runs inline). DECISIONS 273's "none is removed before the process exits" is stale since the refcounted `_release`.
fix: in `Pool.submit` keep a strong reference to `args` on the Future (`fut._cafe_args = args`), so the parent's maps live until the future is released; or reword the docstring to say callers must keep adopted objects until `result()`. Regression test: the script above with a cheap sleeping task. Amend DECISIONS 273. Retaining args delays the shm unlink on a long-lived Future list.
sources: C-2

### M-27. `celik_gci` and `vv20_row` accept inputs the procedure cannot handle: ZeroDivisionError for r21 == 1, misleading RuntimeError for r <= 1 or NaN, infinite U_D validates   (sources: C-3)
severity: minor / status: confirmed / lane: robustness
where: cafe/pm/vv.py:60 (`_fixed_point`), :130-147 (`celik_gci`), :171-176 (`vv20_row`), `gci_two_grid`; cafe/pm/dtmb5415.py:521-525, :581, :591
claim: `celik_gci(1, 1.1, 1.15, 1.0, 2.0)` raises ZeroDivisionError; r21=0.9, r32=1.0 or NaN give "did not converge"; r21=0.0 a math domain error; `vv20_row('x', 1.0, 1.2, .05, .05, inf)` gives u_val=inf, ratio=0.0, validated=True.
check: ran on orca (detached worktree): all reproduced; a NaN u_D gives validated=False (safe). `dtmb5415.discretization` catches only `(ValueError, RuntimeError)`: equal cell counts on the two finest grids give ZeroDivisionError there too, and the two-grid fallback (`gci_two_grid` divides by ratio**p-1 = 0) fails even in the fallback. Reachability is low (GRIDS differ by surface level; u_D in tabulate is the finite assumed u_D_rel*ref). cafe.cfd.gci mirrors the property. freesurface.py:163, :215 and cfd.py:355, :630 only compare `refinement_ratio` with R_MIN. DECISIONS grep errored on a zsh glob, so that check is weak.
fix: guards in vv.py. `celik_gci`: ValueError unless r21, r32 finite and > 1 (r < 1.3 stays valid so `r_ok` can flag it); `gci_two_grid`: ValueError for ratio <= 1 or invalid p; `vv20_row`: ValueError unless all three u finite and >= 0. In `discretization` treat r21 <= 1 as a "grids not refined" note and use the spread-only bound instead of calling `gci_two_grid`. One regression test per guard in tests/test_vv.py plus a `discretization` test with equal cell counts. Confirm `tabulate` never passes inf. Tests at test_vv.py:34-110 use r >= 1.2. New DECISIONS row, CHANGELOG.
sources: C-3

### M-28. Perturbation entries are not validated: raw AttributeError/KeyError, reversed uniform gives silent NaN members, boolean sd accepted, truncnorm unreachable or ZeroDivisionError   (sources: C-4)
severity: minor / status: confirmed / lane: robustness
where: cafe/pm/stats/sampling.py:31-35 (`marginal`), :39-47 (`load_perturbations`), :50-69 (`to_marginals`); cafe/pm/stage1.py:64-75, :872, :902; cafe/pm/credibility.py:169, :293; config/perturbations.yaml
claim: an empty file or `foo: 3` gives AttributeError; an entry without `dist` or a uniform without `lo` gives KeyError; uniform lo 2 hi 1 loads and `lhs` returns NaN for every member; `normal` with `value: true` is read as sd 1 (`isinstance(.., int)` accepts bool); `marginal(truncnorm, sd=0)` gives ZeroDivisionError; `to_marginals` refuses truncnorm though `marginal()` offers it.
check: ran on orca (detached worktree): every symptom reproduced. The shipped yaml is valid, so no printed number moves today. Caveats: truncnorm is used only by tests (test_stats_exact.py:218, test_stats.py:202), so "unreachable" is a docstring mismatch; the ZeroDivisionError is reachable only by a direct `marginal()` call. `stage1.priors_for` does `pri.update(fitted)` so a fitted prior from ingest/priors_fitted.json bypasses `load_perturbations`. Non-finite lognormal sigma, normal mean, median, uniform lo/hi also give NaN members. Rows 19 supports the fix; row 55 only describes the usv uniform; no row covers perturbation validation.
fix: one per-entry check in sampling.py called from both `load_perturbations` and `to_marginals` (covers fitted entries): entry is a dict; `dist` in normal/lognormal/uniform/fixed (truncnorm if kept); value finite and not bool (idiom at config.py:259) for normal/lognormal only (the shipped uniforms use `value: 0.0`); uniform finite lo < hi; mean/median/lo/hi finite, median > 0; a top-level mapping check giving a ValueError naming the file. Either validate sd > 0 and lo < hi in `marginal()` or accept direct-call misuse; allow truncnorm in `to_marginals` or drop it from the docstring and tests. One test per defect, each failing before. Keep the 100 % coverage gate on cafe/pm/stats; tests at test_stats.py:258-280, :504 expect current messages.
sources: C-4

### M-29. `Ledger.__exit__` can fail inside `clean()` on a numpy-integer dict key and hide the stage's own exception   (sources: C-5)
severity: minor / status: confirmed / lane: robustness
where: cafe/pm/ledger.py:175 (`json.dumps(clean(self.d), ...)`), :194-203 (`clean` converts values, not keys), :344; cafe/pm/pipeline.py:266, :1402; cafe/pm/credibility.py:957, :973 (`_clean`); cafe/pm/report.py:1805; cafe/pm/acceptance.py:568
claim: `json.dumps(ledger.clean({np.int64(3): 1.0}), allow_nan=False)` raises TypeError "keys must be str, int, float, bool or None"; in `__exit__` that replaces the exception the stage was leaving and writes no ledger.json.
check: read and stdlib/numpy behaviour on the laptop; no orca worktree. `np.int64` is not an int subclass; `np.float64` is a float subclass, fine; tuple and date keys also fail. The TypeError is raised before `os.replace`; Python chains it, so the stage's error shows as context. Latent: no current ledger value has such a key (q13 ledgers are JSON, all string keys). `credibility._clean` is a duplicate of `ledger.clean` with the same gap; `pipeline.py:1402` uses `sort_keys=True`; report.py:1805 and acceptance.py:568 (`default=str` converts values, not keys) take no clean step. Only the value case is tested (test_ledger.py:283). DECISIONS 593 covers non-finite floats only.
fix: in `ledger.clean()` coerce each key: `k if isinstance(k, str) else str(_jsonable(k))`, with a guard for collisions (np.int64(3) and 3 both become "3"; raise or keep first); keep native int/float keys (json stringifies them). Make `credibility._clean` call `ledger.clean`. Test next to test_ledger.py:283: `clean({np.int64(3): np.float64(1.0)})` dumps, and `Ledger.__exit__` writes ledger.json and re-raises the stage's own exception. Readers already see string keys after a round trip. New DECISIONS row.
sources: C-5

### M-30. `GriddedEnv.sst` states "frozen at 2023-03-01: SST_UPDATE=0" for whatever WRF data it is given   (sources: C-6)
severity: minor / status: partly / lane: honesty
where: cafe/pm/env/environment.py:344 (literal), :84 ("12 km hourly"); cafe/pm/env/orca.py:121-135, :339; cafe/schemas/wrfout.json; tests/test_environment.py:391; STATUS.md row 20; QUESTIONS_FOR_LAB 3
claim: the SST provenance text is a literal, so a coupled-SST WRF file (the lab replacement) would still be labelled frozen.
check: read only. Partly: `orca.wrf_grid` reads SST_UPDATE and SIMULATION_START_DATE from the file's global attributes and raises ValueError if they differ from `wrfout.json` (0 and 2023-03-01), and copies them to wrf.zarr attrs, so every file the code can ingest is frozen by construction and the label is true for all accepted data; a coupled run is refused at fetch time, not mislabelled. The residual defect is that the label is not derived from `w.attrs`, so loosening the schema without touching environment.py leaves a stale label. STATUS row 20 and QUESTIONS 3 understate that the schema must change too. `wrf_src` also hard-codes "12 km hourly" (DX is in attrs). No DECISIONS row contradicts the fix (31, BRIEF 49 describe frozen SST as a property of the orca run). Not in PROMPT.md.
fix: in `GriddedEnv.__init__` next to `wrf_src` build one `sst_note` from the attrs ("frozen at {SIMULATION_START_DATE[:10]}: SST_UPDATE={SST_UPDATE}" if `int(SST_UPDATE) == 0`, else "updated (SST_UPDATE=n)"), and "12 km" from DX/1000; fall back to the current text on an absent attribute (attrs are strings; parse with int()). Test: a grid whose attrs say SST_UPDATE=1 has no "frozen" in the source. The demo's strings stay the same. Alternative with no code: say in STATUS row 20 and QUESTIONS 3 that the schema and this label must change together.
sources: C-6

### M-31. bathy.py docstring gives 8 kB per GEBCO row for the TEPEX-C cut; it is 16 kB   (sources: C-7)
severity: minor / status: confirmed / lane: documentation
where: cafe/pm/env/bathy.py:5-6; DECISIONS 27; missions/tepex_c_demo.yaml:10
claim: the box (lon 165..-165 plus pad 2 = 34 deg at 15 arc-seconds, 240 columns/deg) is 8,160 int16 columns = 16,320 bytes per row; 8,160 is a count, not kB.
check: arithmetic and code read (`_rows` bathy.py:82-89 reads int16 columns); the pipeline was not run. DECISIONS 27's 59 MB over 3,360 rows is 17.6 kB per row; 3,360 x 16,320 B = 54.8 MB, so 59 MB is about 7 % higher (pad/edge cells or a measured total), not affecting the finding. Only this one per-row figure exists.
fix: docstring at bathy.py:6: "about 16 kB for the 34 deg TEPEX-C box (8,160 int16 columns)", keeping the line short (ruff 160). No test.
sources: C-7

### M-32. `seconds()` maps NaT to -9.22e18 and `Axis` accepts it as the first time   (sources: C-8)
severity: minor / status: confirmed / lane: robustness
where: cafe/pm/env/environment.py:33-34 (`seconds`), :74-80 (`axis`), :86, :92, :106, :112, :243-246, :301; cafe/pm/env/grid.py:19-21 (`Axis`); cafe/pm/env/ocean.py:48; cafe/pm/env/surface.py:230, :236
claim: a time array with NaT at index 0 becomes `[-9.22e18, ...]` and `np.all(np.diff(t) > 0)` is True, so the damaged coordinate loads; NaT in the middle or last slot is rejected only by accident.
check: reproduced with numpy only on the laptop; not run on orca or the pipeline. The `w3["t"]` and `spec["t"]` arrays never pass through `Axis` (they go to `searchsorted` and `argmin`), so NaT anywhere in them is unchecked. Lat/lon NaN is already rejected. Only a damaged or fill-valued slot triggers it. No DECISIONS row found contradicting a fix (not searched exhaustively).
fix: add an `np.isfinite` check raising ValueError in `Axis.__init__` (`environment.axis()` already maps it to ConfigError; Ocean and SurfaceLayer are covered), and make `seconds()` raise on `np.isnat` as the choke point for the four environment.py callers (covers `w3` and `spec`). Test: NaT at index 0 raises ConfigError for each of wrf, umwm, wrf3d, umwmspec; `Axis` rejects NaT and inf. Check HYCOM and surface stores for legitimate NaN padding slots first.
sources: C-8

### M-33. `GriddedEnv._check` raises a bare ValueError for a NaN time instead of OutsideData   (sources: C-9)
severity: minor / status: confirmed / lane: robustness
where: cafe/pm/env/environment.py:132-143 (line 138 `fromtimestamp`), callers :146, :161, :167, :185; cafe/pm/env/grid.py:26; cafe/pm/__main__.py:173; cafe/pm/whatif.py:348, 355, 595, 620
claim: a NaN time takes the raise branch (`inside` is False for NaN) and `dt.datetime.fromtimestamp(NaN)` raises ValueError, which the handlers that turn out-of-data into a clean exit 2 do not catch; inf and 1e30 give OverflowError at the same line.
check: the mechanism ran on the laptop with plain numpy/datetime; the orca reproduction was not repeated. Strict mode only (the lenient `run_batch` path never raises). `config.damaged_run_files` would wrap it as "damaged, rerun --fresh", which misleads. Needs a non-finite time that validation should have refused (see M-28). Other `fromtimestamp` sites (whatif.py:173, report.py:89, pipeline.py:321, 1022, hycom.py:98) take times from data or the validated window. DECISIONS 141, 190, 276, 351 cover OutsideData; 276's format for finite times is kept.
fix: in `_check` (the single raise site) build the time text through a guarded helper: try `fromtimestamp`, except `(ValueError, OverflowError, OSError)` fall back to `f"{T}"` / "not a number", so OutsideData is raised for every bad point. Test: strict `GriddedEnv` queried with `t=np.nan`, `np.inf`, `1e30` raises OutsideData whose text names the position and "nan"/"inf". Messages for finite times stay byte-identical. Also fix C-4's source so non-finite perturbations are refused upstream.
sources: C-9

### M-34. `subset_simulation` uses nominal p0 in the c.o.v. but nc/n for the probability, and divides by zero for small n (function not called by the pipeline)   (sources: C-10)
severity: minor / status: confirmed / lane: statistics
where: cafe/pm/stats/rare.py:53-55, :72, :73; tests/test_stats_exact.py:489-515; docs/PHYSICS.md 13.5; DECISIONS 73, 366
claim: nc = round(n*p0), length = n // nc, n = nc*length, so the realised level probability nc/n differs from p0 unless it divides evenly; the c.o.v. term uses p0 and the probability update uses nc/n. For n=1000, p0=0.3 the term is (0.7)/(0.3*900)=0.002593 against (2/3)/((1/3)*900)=0.002222, 16.7 % high per level. `subset_simulation(f, d, t, n=4)` gives nc=0 and ZeroDivisionError.
check: read the code; arithmetic by hand, not run on orca; the 60-seed c.o.v. figures were not checked. The nominal term over-reports the variance here, so the reviewer's reported-vs-empirical gap (0.169 vs 0.250) is not explained by this defect (it comes from gamma and mixing). No caller outside tests; nothing in PROMPT.md. Rows 73 and 366 concern gamma and the c.o.v. level, not contradicted.
fix: in `subset_simulation`: raise ValueError if `nc < 1` (refusing n*p0 < 1 is cleaner than n*p0 < 0.5); set `p_lvl = nc / n` once after `n = nc * length` and use it in both the c.o.v. term and `p *= p_lvl`. Tests: n=1000, p0=0.3 uses 1/3; n=4 raises ValueError. The pinned c.o.v. runs at test_stats_exact.py:494-515 are rounding-exact (p0=0.2 n=200; p0=0.1 n=200); the n=107 test asserts only `n_evals`. Amend DECISIONS 366, CHANGELOG. No gate number moves.
sources: C-10

### M-35. `AnalyticEnv` and the Environment protocol docstring mention things that do not exist   (sources: C-11)
severity: minor / status: confirmed / lane: documentation
where: cafe/pm/env/protocol.py:13, :41-43, :49, :52-60, :104-105; cafe/pm/env/environment.py:200-211; tests/test_environment.py:253
claim: the default current profile is documented as "1 above `ml_depth`" but there is no such parameter (`_profile` is `clip(1 + min(z,0)/1000, 0, 1)`); the module docstring lists air keys including ustar and L, which `GriddedEnv.air` returns only when a sub-grid is attached (otherwise T2, q2, psfc, swdown, glw, rain, ustar_wrf, pblh).
check: read only, no run; `ml_depth` appears only on that line; the test at :253 asserts the no-subgrid key set exactly. No runtime effect: stage1.py:223 reads ustar/L from `sl.surface_layer` guarded by `sl is not None`, and :234 reads only T2, q2, psfc. No other consumer indexes `air()["ustar"]` or `["L"]`.
fix: docstring-only edit in protocol.py: line 49 says full strength at the surface falling linearly to 0 at 1000 m; line 13 lists T2, q2, psfc, swdown, glw, rain always, plus ustar and L (AnalyticEnv, and GriddedEnv only with a SurfaceLayer sub-grid), and ustar_wrf and pblh always from GriddedEnv. Do not add stub keys to GriddedEnv. DECISIONS row, CHANGELOG.
sources: C-11

### M-36. tests/test_vv.py passes on changed vv.py: eq. 6, r_ok, the validated boundary, phi_ext32, 2-D grid_size   (sources: C-12)
severity: minor / status: confirmed / lane: tests
where: tests/test_vv.py:39, :40, :116-118, :147-153; cafe/pm/vv.py:46, :140, :143, :147, :176
claim: five edits leave test_vv.py green: (a) eq. 6 denominator `ext21` to `phi1`, (b) r_ok `and` to `or`, (c) `ratio <= 1.0` to `< 1.0`, (d) the ext32 numerator with phi2/phi3 swapped, (e) `** (1.0/dim)` to `** (1.0/3)`.
check: mutants (a)-(d) ran on orca against test_vv.py + test_credibility.py with `-n 2`, all rc 0; (e) was confirmed by reading (the search pattern matched more than once, so it did not run). grid_size is only called with the default dim 3 and has no non-test caller. The Table 1 tolerance is abs 1e-3 while the two denominators differ by 3e-4 in column 1. vv.py is outside the mutmut scope (physics and stats), so no mutation gate covers it. Same habit in `gci_two_grid`, `format_table`, and possibly dtmb5415.py:529, freesurface.py:164, :221 (an exact-1.3 test was not checked).
fix: tests only, no code change. Assert eext21 against the formula from `g.phi_ext21` with rel=1e-9 (not the printed digits); r_ok pairs (1.5, 1.2) and (1.2, 1.5) False and (1.3, 1.3) True; `vv20_row("b", 5.0, 0.0, 3.0, 4.0, 0.0)` with |E| = U_val = 5 validated True, ratio 1.0; phi_ext32 equals (r32^p*phi2 - phi3)/(r32^p - 1) on the power_law helper; `grid_size([4.0]*3, dim=2)` expects 2.0 (or delete the unused function). Adding vv.py to the mutmut paths changes the 85 % gate and is the owner's call.
sources: C-12

### M-37. Tests pass on changed environment.py / ocean.py / par.py: rain over the data end, restart distance, lenient restore, 3-D hour gap, 0 E store, fractional CPU quota   (sources: C-13)
severity: minor / status: confirmed / lane: tests
where: cafe/pm/env/environment.py:158, :304, :126, :247; cafe/pm/env/ocean.py:75; cafe/pm/par.py:64; tests/test_environment.py:358-364, :450-462, :499-515; tests/test_par.py:209, :328-333; tests/test_ocean.py:121
claim: six edits leave their test files green: (a) drop `np.minimum` at environment.py:158, (b) drop `np.cos` at :304, (c) `self.strict = was` to `= True`, (d) `<= 3600.0 + 1e-6` to `7200.0`, (e) `Ocean._lon` to `cv.wrap360(lon)`, (f) `par._cgroup_cpus` without `max(1, ...)`.
check: all six edits applied at once in a detached worktree on orca; `pytest -q -n 2 tests/test_environment.py tests/test_ocean.py tests/test_par.py` rc=0, so each single mutant survives. The behaviours are real: an hour starting 30 min before the data end gives half the true rate; `--cpus 0.5` gives 0 workers. Siblings: `wrap_about` callers (bathy.py:70, pipeline.py:566, hycom.py:691, :747) share the untested 0 E path; other `np.cos(np.radians` distance code probably shares the equatorial-fixture blind spot; the cgroup v1/v2 memory readers were not checked.
fix: tests only. (a) `rain_hourly` at end-1800 s with acc rising in the last interval, expecting the exact half-hour mean; (b) `restart_spectrum` at lat about 60 where 0.3 deg is under 40 km only with cos; (c) a non-strict env asserts strict still False after `lenient()`; (d) a w3 with two nodes 7200 s apart expects NaN/None between them; (e) a synthetic Ocean store spanning -1..+1 or 359..361 queried at -0.5 and 359.5; (f) add `('50000 100000', 1)` to the cgroup v2 and v1 tables. One parametrised fixture with a high-latitude, 0 E-crossing box next to ci_env covers (b), (e) and the `wrap_about` siblings; keep it separate from ci_env so existing expectations do not move.
sources: C-13

### M-38. Stage-3 FEA never runs the buckling step, so stored utilization omits hull collapse; the default glider reads 1.9x too low   (sources: D-2)
severity: minor / status: confirmed / lane: physics, documentation
where: cafe/pm/stage3/pipeline_windows.py:398-405 (`_fea_child` leaves `buckle` False); cafe/pm/stage3/windows.py:345-366; docs/BRIEF.md:129; cafe/pm/pipeline.py:13; cafe/hangar.py:163-170 (KNOCKDOWN 0.5); tests/test_stage3.py:577-583
claim: BRIEF 2.6 asks for a hull-collapse check; the pipeline stores only von Mises utilization (vm_p99/yield). For the default glider hull on orca: `buckle=False` utilization 0.3671 (vm_p99 101.32 MPa), `buckle=True` 0.6872 (buckling_factor 1.4552), a ratio of 1.87. Nothing in the docs says the value is stress only.
check: ran on orca (detached worktree) with the finding's script: exactly those numbers. The factor is the linear, un-knocked-down value: with hangar.py's KNOCKDOWN 0.5 the same hull is at 1/(1.455*0.5)=1.37, collapse, so the true gap is about 3.7x. `fea_window`'s buckle branch does not apply the knockdown, so enabling it as written would still read 2x too optimistic. q13's glider body window is "not run" (viscosity floor), so nothing reached the report; no pm code consumes `fea['utilization']`, so no verdict or gate moves today. The wing/arm root and slamming checks named in BRIEF 2.6 have no pm code (STATUS.md:39).
fix: in `_fea_child` pass `buckle=True`; in `fea_window` apply `hangar.KNOCKDOWN` (1/(factor*0.5)) and split the key (`stress_utilization`, `buckling_utilization`, `utilization = max`). Regression test in test_stage3.py via the `_spawn` seam: the stored `buckling_factor` is non-null. DECISIONS row and CHANGELOG; if kept stress-only instead, state it in BRIEF 2.6 status, pipeline.py:13, STATUS and CREDIBILITY. The eigen-solve costs budget (budget.py:464-488 `fea_reserve_frac`/`fea_min_s`), and old stored windows' ledger hashes change.
sources: D-2

### M-39. `whatif.apply` raises a bare ValueError (year out of range) instead of Invalid for a very large deploy shift   (sources: D-3)
severity: minor / status: confirmed / lane: robustness
where: cafe/pm/whatif.py:133-139 (`apply`), :172 (`_iso`), :710 (`parse_shift`), :130; callers :388, :657, :673, :687; cafe/pm/pipeline.py:1527; cafe/pm/__main__.py:173
claim: `apply(demo, {'glider_eq': {'shift_h': 1e9}})` raises `ValueError: year 116102 is out of range`; the same for usv and glider_2n; `parse_shift('1000000000h')` returns 1e9, so the CLI `--shift` path reaches it.
check: static; the failing call is pure stdlib, so it was reproduced on the laptop's Python 3.9 (year 116103 there; the report says 116102). A huge negative shift gives ValueError and an inf-length digit string (about 400 digits) OverflowError, so catching only ValueError is not enough. In the base-vehicle branch (:130), `int(round(h*60))` raises OverflowError for inf. `Invalid` subclasses `ConfigError` (:66), so the CLI would exit 2 cleanly; flip search and design callers catch `Invalid` but not ValueError. `flight_note` (:190) does not call `_iso`.
fix: in `apply()` right after the `float()` conversion raise `Invalid` if `not math.isfinite(h)` or `abs(h)` exceeds the window length plus a margin; or build the message from h and the window strings without `_iso(t)` and call `_iso` only on the success path. Tests: ±1e9 and `inf` raise Invalid for glider, glider_2n and usv, and inf for a base vehicle. Messages for shifts only slightly outside the window must keep their wording. DECISIONS row, CHANGELOG.
sources: D-3

### M-40. `whatif.apply` moves a shared ship once, so the second UAS's own move is silently dropped   (sources: D-4)
severity: minor / status: confirmed / lane: correctness, robustness
where: cafe/pm/whatif.py:123, :141-144 (`ship_moved`), :317-330, :380-392 (`_fits`), :398 (`design`); cafe/pm/pipeline.py:1482-1488
claim: with two UAS on one ship, `apply(m, {'uas': {'dlon': -0.5}, 'uas_b': {'dlon': -0.2}})` leaves the ship at -165.5: only the first move applies, with no message.
check: ran on orca (detached worktree): `load_mission` accepts the two-UAS mission; `apply(..., {uas:-0.5, uas_b:-0.2})` gives -165.5; `{uas_b: -0.2}` alone gives -165.2; swapping dict order gives -165.2, so first wins. `design(m, 4, 1)` row 0 draws uas dlon -0.256 and uas_b dlon -0.904 but the ship ends at -165.2557, so uas_b's drawn point is not the one run. Rows 1 and 2 are all-zero. The training row stays self-consistent (`vehicle_rows` reads lon/lat from the mission's ship), so the damage is lost design coverage and an ignored move. `_fits` validates one vehicle at a time and cannot see the clash. Shipped missions have one UAS, so no printed number moves. `_points` and `uas_track` read the single ship for every UAS (same one-ship assumption). No DECISIONS row covers it.
fix: in `whatif.apply`, either (A) raise `Invalid` naming both vehicles when a second base vehicle asks for a different dlon/dlat than the move already applied, or (B) have `design` draw one ship move per ship and give it to every vehicle based on it. B is needed with A, else `_fits` just drops the second UAS's move. Test: a two-UAS mission where apply with two different ship moves raises Invalid (or both get the same), and design gives both the same dlon/dlat; fails now. Amend the whatif docstring and PHYSICS.md line 22 ("moves with its ship"); DECISIONS row, CHANGELOG.
sources: D-4

### M-41. Flip-search UAS duty candidates 0.75 and 0.5 are the same mission at costs 1 and 2 notches   (sources: D-5)
severity: minor / status: confirmed / lane: honesty, statistics
where: cafe/pm/whatif.py:61 (`DUTIES`), :165 (`_duty_days`), :576 (`candidates`), :666, :694; tests/test_whatif.py:799-805; q13 emulator/flip.json (vehicles.uas.tried[6] and [13])
claim: for every_days 1 both `ceil(1/0.75)=2` and `ceil(1/0.5)=2`, so `apply(m,{'uas':{'duty':0.75}}) == apply(m,{'uas':{'duty':0.5}})`, yet `candidates` prices them at cost 1.0 and 2.0 ((1-f)/0.25).
check: read the code and the q13 flip.json; nothing run on orca. Both entries in flip.json are "not evaluated" (7 rows against 100 needed). Effects: the search sorts by cost, so the real change is listed first as the cheapest; the Stage-1 fallback `left[:FALLBACK_K=3]` loses a slot to the duplicate; the "candidates" count (:694) counts it twice. No verdict or number changes. A duplicate occurs for any every_days where `ceil(e/0.75) == ceil(e/0.5)` (e=0.9, 1); e=2, 3, 0.5 are distinct. Glider duty is linear and unaffected. The shift candidates already drop whole-day shifts for a UAS by hand at :570.
fix: in `candidates()` for a UAS compute `eff = every / _duty_days(every, f)`, price at `(1-eff)/0.25`, and skip any candidate whose effective duty is already listed or equals 1. For every_days=1 one candidate remains (2 d, cost 2.0), and "(rounded up)" wording appears only when the period really rounds (e=3 at 0.75 becomes 4 d). Test: `candidates(CI,'uas')` has exactly one sorties-every candidate for every_days=1 at cost 2.0 plus a distinct case (e=3). Update test_whatif.py:804-805; amend DECISIONS 111 and 195 (109 stays true), CHANGELOG. Could change golden/q-run flip.json counts, the FALLBACK_K third pick, and fixtures expecting 16 UAS candidates.
sources: D-5

### M-42. A killed FEA window leaves its ccx process running   (sources: D-6)
severity: minor / status: confirmed / lane: robustness, performance
where: cafe/pm/stage3/pipeline_windows.py:408-427 (`_fea`, `_spawn` without `start_new_session`), :670; cafe/fea.py:274-278 (`subprocess.run(["ccx", ...])`, no timeout); cafe/pm/stage3/freesurface.py:182-190 (`arm_watchdog`); cafe/pm/stage3/fluidx3d.py:88; tests/test_stage3.py:1286
claim: on the FEA deadline `subprocess.run`'s timeout kills only the python child; the ccx grandchild keeps a CPU busy while its temp dir is deleted under it.
check: mechanism reproduced on the laptop (python child running `sleep 7` under `subprocess.run(timeout=1)`: TimeoutExpired fired and `ps` showed the sleep alive with ppid 1); no orca job. The free-surface spawn at :670 already uses `start_new_session=True` and `arm_watchdog` (os.killpg). test_stage3.py:1286 uses a stub raising TimeoutExpired; no test checks that ccx is gone. q13 has no "killed: the FEA" row. The result is one orphan single-threaded ccx; the row says killed either way. DECISIONS 138 says the FEA child is killed at the deadline, true of the python child only. Siblings: fluidx3d.py:88 (single binary, low risk), ocean.py:104 and hycom.py:277 (no grandchildren), cfd.py:55 (`bash -c` with no timeout at all, not in this path).
fix: add `start_new_session=True` to the `_spawn` call in `_fea` (as at :670) and call `arm_watchdog(timeout_s)` at the top of `_fea_child` so the group is killed with `killpg`. Test: a real child that spawns a uniquely timed `sleep` and hangs, through `pw._fea` with a short timeout; no process of that duration remains. The in-process `_spawn` fakes in test_stage3.py (:887, 1283-1293, 1442, 1475, 1696) use `**k` and should accept the kwarg. A SIGKILL watchdog skips the child's TemporaryDirectory cleanup, so put the child's workdir under the parent's wd. Check session and killpg once under proot.
sources: D-6

### M-43. `fluidx3d.available` treats any truthy `enabled` as on, including the string "false"   (sources: D-7)
severity: minor / status: confirmed / lane: robustness
where: cafe/pm/stage3/fluidx3d.py:34-35, :43; cafe/pm/stage3/freesurface.py:46-48; cafe/pm/budget.py:224; cafe/pm/stage3/windows.py:411; cafe/pm/stage3/pipeline_windows.py:667; tests/test_stage3.py:611-625
claim: `available({'fluidx3d': {'enabled': 'false', 'binary': '/bin/ls'}})` returns `(True, 'using /bin/ls')`; the plugin is licence-restricted (commercial and military use forbidden) and meant to need one deliberate line, and `budget.fs_plan` then drops the interFoam plan.
check: read; not re-run on orca (pure function). The config is `json.loads(config/premission.json)` without type checking; the shipped config has no fluidx3d key, so the default is off. Narrow harm: a person must hand-write a quoted "false" and name an existing executable. `binary` also reaches `pathlib.Path` and raises TypeError for a non-string. env/subgrid.py:405 `c["enabled"]` has the same pattern on an env config (not traced). DECISIONS 83 (disabled by default) is not contradicted; 119 limits the damage.
fix: in `fluidx3d.available()` (the single gate) require `s["enabled"] is True`; non-bool returns `(False, "enabled must be the JSON boolean true")`; check `binary` is a str. Add cases for enabled "false", "true" and a numeric binary to `test_fluidx3d_is_disabled_by_default_and_says_why`. A lab config writing `"enabled": 1` or "true" would now be refused, arguably wanted for a licence-gated switch. DECISIONS row, CHANGELOG.
sources: D-7

### M-44. The draft stated to give the platform's displacement ignores the keel the same sentence counts   (sources: D-8)
severity: minor / status: confirmed / lane: documentation
where: DECISIONS.md row 407 (line 460); config/assumptions.yaml `stage3.usv.hull_draft_m` `replace_with` (:257); docs/PHYSICS.md:993 (14.4); cafe/pm/stage3/freesurface.py `write_stl`; tests/test_stage3.py (`test_the_hull_fs_row_states_the_displacement_next_to_the_platforms_mass`)
claim: the mesh displaces 1.98 m3 = half ellipsoid 1.838 + keel box 0.140, against the platform's 750/1023 = 0.733 m3. The stated remedy draft c = 3V/(2 pi a b) = 0.179 m matches the ellipsoid alone; with the keel kept c = 0.145 m. At 0.18 m the mesh displaces 0.875 m3 (895 kg), 19 % over.
check: recomputed on the laptop with numpy (manifold3d absent): c=0.45 gives 1.978 m3 (2023 kg), reproducing row 407; c=0.18 gives 0.735+0.140 = 0.875 m3; c=0.145 gives 0.732 m3 (749 kg). The keel volume does not depend on c. The 0.18 m figure appears only in the three places (DECISIONS 407, assumptions.yaml, PHYSICS 993); review/round_8 files are history. The existing test checks only the 1.98 m3 and 2.7x figures and the why text, not the 0.18 m remedy. Latent: no GPU window has run, so no refit used it.
fix: change 0.18 m to about 0.145 m and write c = (V_platform - V_keel) / (2 pi a b / 3) with V_keel = 0.14 m3, in all three places (assumptions.yaml first, the others point to it). Amend row 407 in place, CHANGELOG. One regression test: mesh volume at the stated draft (half ellipsoid + keel, as the existing test does) is within a few percent of `mass_kg / rho_water`; fails at 0.18, passes at 0.145. Keep the why-text assertions (2.0 t, 0.75 t, 2.7 times); the value stays 0.45.
sources: D-8

### M-45. "6 is the measured scaling knee" is not a measured point   (sources: D-9)
severity: minor / status: confirmed / lane: documentation, honesty
where: cafe/pm/stage3/freesurface.py:110-115 (`nproc`); DECISIONS.md row 297; tests/test_stage3.py:1872; config/throughput.json `openfoam-pimpleFoam-les`
claim: throughput is measured at 1, 2, 4, 8 cores only (46.4k, 86.4k, 141.9k, 164.5k cell-updates/s; efficiency 1.00, 0.93, 0.76, 0.44); six cores is `np.interp` in `freesurface.rate` (153k, efficiency 0.55), and the curve already bends at 4.
check: static (config data and code); no orca job. `freesurface.rate()` is honest (`rate_source` says measured at [1,2,4,8], interpolated to N; q13 plan.json carries it), so no printed number is wrong, only the word "measured" on the cap. The phrase appears in exactly three places outside review/. Rows 330/662/663 amend env parsing only.
fix: reword the three places to say 6 is a chosen cap between the measured 4-core (0.76) and 8-core (0.44) points, priced at the interpolated 153k; amend row 297 in place. Alternative: add a real 6-core benchmark to config/throughput.json (moves the interpolated rate, free-surface prices and tests). Wording only cannot break runtime behaviour.
sources: D-9

---

## Root causes

1. Tests and prose are derived from the code under test, so a changed constant or branch still passes. The cure is a literal or independent oracle in the test, in the same file as the existing one.
   - Place: tests/test_vv.py (M-36), tests/test_environment.py, test_ocean.py, test_par.py (M-37), tests/test_coare.py (M-4), tests/test_surface.py (M-5), tests/test_receipts.py (M-6), tests/test_acceptance.py (M-7); the mixed tail in test_surface/test_report/test_nest/test_orca (M-8).
   - Siblings: M-11 (the printed command was fed back to `check_golden`, never to the parser) and M-34/M-27 (tests pinned values the code also produced). `vv.py` is outside the mutmut scope, so no gate catches M-36; the owner decides whether to add it.

2. The "used by this mission" rule is derived from less than the code reads.
   - Place: `credibility.entries_read` / `Facts` / `build` (one fix per reader): M-2 (UAS lost-link radio) and M-3 (config/ items defaulted to used).
   - Siblings: perturbations.yaml priors were not checked; the "platform not used" label at credibility.py:929 is wrong for a config key; M-12's sanity wording is the same drift (rule changed, sentence not).

3. One printed command or advice string with several hand-written copies or no check against the parser or the writer set.
   - Place: `acceptance.update_command` (M-11, with `_golden_record` M-7), `receipts.stored` advice (M-19, with M-13's CAFE_APP_RUNS note), `environment.py` fetch text (M-23, one `FETCH_CMD` constant).
   - Siblings: M-9 (a usage line in `cfd.main`), M-13, M-20 (counts typed into prose at RUNBOOK 208/246 and STATUS:56), M-45, M-31, M-35, M-10, M-44 (hand-typed figures with no link to what they describe).

4. Stamp provenance that can name no commit and writers that do not treat the target as a file the user chose.
   - Place: `ledger.git_sha()` plus one `has_commit` predicate used by `receipts.stored`, `pm/receipts.py` and `credibility.py:748` (M-24, with M-6's non-empty-string clause); `config.write_json` resolves the path (M-14); `run.sh` passes CAFE_GIT_SHA.
   - Siblings: `orca.write_json` and `hycom._write_json` copies; M-17 (golden written non-atomically, same pattern at acceptance.py:568, audit.py:433, :490, credibility.py:973, report.py:1805).

5. Untrusted or hand-written input trusted at the shared reader, so a typo becomes a raw traceback, a silent NaN or the wrong run.
   - 5a, remote files: `remote._Buf.take` and `parse_cdf1`/`cdf1_read` (M-15), `_is_url` (M-16), `_probe` and `download` (M-18).
   - 5b, config and ledger writers: `config._say` and `_yaml` (M-22), `ledger.clean` keys (M-29), `ledger.real()` instead of `.resolve()` (M-21).
   - 5c, numeric domain: `vv.celik_gci`/`gci_two_grid`/`vv20_row` (M-27), `sampling` per-entry check (M-28), `Axis`/`seconds` NaT (M-32), `GriddedEnv._check` time text (M-33), `whatif.apply` shift (M-39), `subset_simulation` nc guard (M-34).
   - 5d, CLI and flags: `cfd.main` argv (M-9), `golden_refusal` is_file (M-17), `fluidx3d.available` bool (M-43).
   - Siblings: M-28 feeds M-33 (a non-finite perturbation should be refused upstream); `ledger.py:338/340` resolve calls are covered by M-21's helper.

6. Documented invariants and labels that nothing enforces.
   - Place: `Pool.submit` keeps args (M-26); `GriddedEnv.__init__` derives the SST note from attrs (M-30); `candidates()` prices by effective duty (M-41); `whatif.apply`/`design` handle one ship move per ship (M-40); `_fea`/`_fea_child` own the process group (M-42); `_chance_miss` models random conformal coverage (M-1).
   - Siblings: `fluidx3d.py:88` and `cfd.py:55` use the same no-group pattern; M-38 (stress-only "utilization") and M-25 (relative sigma passed as absolute) are the same class of unit or meaning mismatch.

7. Environment arithmetic left to a typed figure in prose: M-10 (eps_c), M-31 (kB), M-44 (draft), M-35 (docstring keys). One owner for each figure's source (the formula or mesh volume), with a one-line assert in the test where a number is stated.

---

## Batches

Batches share no files. DECISIONS.md, CHANGELOG.md, docs/*.md (PHYSICS, CREDIBILITY, RUNBOOK, BRIEF), STATUS.md and QUESTIONS_FOR_LAB.md are edited only by batch F; every other batch hands F the DECISIONS rows and CHANGELOG lines noted in its findings. Where a finding below lists a doc file, F makes that edit. Where a source edit would touch a file owned by another batch (named in notes), hand it to that batch.

### Batch A: ledger, receipts, credibility, report, config, comms
- findings: M-2, M-3, M-5, M-6, M-8, M-10, M-12, M-13, M-14, M-19, M-21, M-22, M-24, M-29
- order: M-29 and M-21 (ledger.py), M-14 (config.write_json) and M-22 (config), M-24, M-6, M-19, M-13 (receipts), M-2, M-3, M-12 (credibility/report), M-10 (comms), then tests-only M-5 and M-8
- files: cafe/pm/ledger.py, cafe/pm/audit.py, cafe/pm/config.py, cafe/schemas/mission.json, cafe/receipts.py, cafe/pm/receipts.py, cafe/pm/credibility.py, cafe/pm/report.py, cafe/pm/stage1.py (only `_uas_radio` for M-2), cafe/pm/physics/comms.py, cafe/pm/pipeline.py (read; `ledger.clean` carries M-29), run.sh, pm.sh, bin/pmx.sh, tests/test_ledger.py, tests/test_config.py, tests/test_receipts.py, tests/test_credibility.py, tests/test_report.py, tests/test_surface.py, tests/test_nest.py, tests/test_orca.py, tests/test_comms.py
- notes: M-5 and M-8 are tests only (no source change) and take test_surface, test_nest, test_orca, test_report here. `pipeline.py` is owned by E; M-29 changes `ledger.clean` only, so no edit there. `orca.write_json`/`hycom._write_json` (M-14 sibling) are in cafe/pm/env, batch C's; change them there. Hand-offs to F: DECISIONS 646 and 681 (M-2, M-3), 683 (M-12), 504 and 648 (M-14), 675, 678 and 689 (M-6, M-19, M-24), 593 (M-29), 652 (M-10), CHANGELOG, RUNBOOK point 3, README.md:172-174, QUESTIONS_FOR_LAB:119 and PHYSICS:806 (M-10).

### Batch B: acceptance
- findings: M-7, M-11, M-17
- order: M-17 (is_file and atomic write), M-11 (one command builder with `--out`), M-7 (stored command quoted, same builder)
- files: cafe/pm/acceptance.py, cafe/pm/__main__.py (read; the parser check only), tests/test_acceptance.py, tests/test_cli.py
- notes: if `config.write_json` cannot append the golden's trailing newline (M-17), hand a one-line change to batch A rather than editing config.py here. The shipped golden's command field changes only at the next re-mint. Hand-offs to F: DECISIONS 673 (M-17), 680 and 685 (M-11, M-7), CHANGELOG.

### Batch C: environment, remote data, surface, par, bathy
- findings: M-4, M-15, M-16, M-18, M-23, M-25, M-26, M-30, M-31, M-32, M-33, M-35, M-37
- order: M-15, M-16, M-18 together in remote.py (one in-process Range-server fixture), M-32 and M-33, M-25, M-30, M-23, M-26, then M-35, M-31, then tests M-4 and M-37
- files: cafe/pm/env/remote.py, cafe/pm/env/tao.py, cafe/pm/env/orca.py, cafe/pm/env/environment.py, cafe/pm/env/grid.py, cafe/pm/env/ocean.py, cafe/pm/env/surface.py, cafe/pm/env/coare.py, cafe/pm/env/bathy.py, cafe/pm/env/protocol.py, cafe/pm/env/hycom.py (M-14 sibling `_write_json` only), cafe/pm/par.py, cafe/schemas/wrfout.json, cafe/pm/__main__.py (M-23 only if the shared constant is reused at :311), tests/test_remote.py, tests/test_tao.py, tests/test_environment.py, tests/test_ocean.py, tests/test_par.py, tests/test_coare.py
- notes: M-4 (coare) is a tests-only finding; M-37 may add a fixture box next to ci_env without moving existing expectations. M-15's header cap must be checked against a real umwmrst header. M-30 defaults to deriving the label; the docs-only alternative goes to F. `__main__.py` is edited by C only for M-23 (batch B reads it). Hand-offs to F: DECISIONS 19 context, 442 (M-23), 665, 682, 684 (M-15), 273 (M-26), 653 (M-4), 27 (M-31), 31 and STATUS row 20 and QUESTIONS_FOR_LAB 3 (M-30), CHANGELOG.

### Batch D: stats, V&V, perturbations, CLI of the old CFD app
- findings: M-9, M-27, M-28, M-34, M-36
- order: M-28 (sampling), M-34 (rare), M-27 (vv, then `dtmb5415.discretization`), M-36 tests (after M-27 so the guards are in), M-9 (cfd.main)
- files: cafe/pm/stats/sampling.py, cafe/pm/stats/rare.py, cafe/pm/vv.py, cafe/pm/dtmb5415.py, cafe/cfd.py, config/perturbations.yaml (read; only if a shipped value needs fixing), tests/test_stats.py, tests/test_stats_exact.py, tests/test_vv.py
- notes: M-9's test needs a new case in a test file; put it in tests/test_cfd.py or tests/test_cfd_main.py (a new file) rather than test_receipts.py, which batch A owns. M-28 must not edit stage1.py (batch A's `_uas_radio` is the only edit there); if the fitted-prior merge needs a call, hand it to A. Hand-offs to F: DECISIONS 569, 663 and 678 (M-9), 19 (M-28), 73 and 366 (M-34), PHYSICS 13.5 (M-34), CHANGELOG.

### Batch E: whatif, emulator, stage 3, pipeline docstring
- findings: M-1, M-38, M-39, M-40, M-41, M-42, M-43, M-44, M-45
- order: M-1 (printed number), M-39, M-40, M-41 (whatif), M-43, M-42, M-38, then M-44, M-45 (wording and values)
- files: cafe/pm/whatif.py, cafe/pm/emulator.py, cafe/pm/pipeline.py (pipeline.py:13 docstring for M-38 and :1551 wording for M-1), cafe/pm/stage3/pipeline_windows.py, cafe/pm/stage3/windows.py, cafe/pm/stage3/fluidx3d.py, cafe/pm/stage3/freesurface.py, cafe/pm/budget.py (read; sizing check for M-38), cafe/fea.py, cafe/hangar.py (KNOCKDOWN reuse), config/assumptions.yaml, config/throughput.json (read), tests/test_whatif.py, tests/test_stage3.py, tests/test_emulator.py
- notes: M-1 changes the report line only if it says "binomial"; report.py is batch A's, so hand that wording to A if needed. M-44 changes text in config/assumptions.yaml and adds one test; the DECISIONS 407 and PHYSICS 14.4 side is F's. Hand-offs to F: DECISIONS 263 and 540 (M-1), 111 and 195 (M-41), 138 (M-42), 83 and 119 (M-43), 407 (M-44), 297 (M-45), BRIEF 2.6, STATUS and CREDIBILITY (M-38 option), PHYSICS.md line 22 (M-40), CHANGELOG.

### Batch F: documents
- findings: M-20, plus every hand-off line from A to E
- order: M-20 (re-measure `make receipts` at code freeze first), then the document side of M-1 to M-45 and the new DECISIONS rows and CHANGELOG lines
- files: DECISIONS.md, CHANGELOG.md, docs/PHYSICS.md, docs/CREDIBILITY.md, docs/RUNBOOK.md, docs/BRIEF.md, STATUS.md, QUESTIONS_FOR_LAB.md, README.md, review/round_13/PROMPT.md
- notes: run after A to E. New DECISIONS rows are numbered after the last one (692 at the time of review); amend existing rows in place and keep their numbering (19, 27, 31, 73, 83, 109, 111, 119, 138, 195, 263, 273, 297, 366, 407, 442, 504, 540, 569, 593, 646, 648, 652, 653, 663, 665, 673, 675, 678, 680, 681, 682, 683, 684, 685, 689). If a document that tests/test_config_docs.py reads changes, run that file after F.

Coverage check: M-1 to M-45 each appear in exactly one batch.
- A: M-2, M-3, M-5, M-6, M-8, M-10, M-12, M-13, M-14, M-19, M-21, M-22, M-24, M-29 (14)
- B: M-7, M-11, M-17 (3)
- C: M-4, M-15, M-16, M-18, M-23, M-25, M-26, M-30, M-31, M-32, M-33, M-35, M-37 (13)
- D: M-9, M-27, M-28, M-34, M-36 (5)
- E: M-1, M-38, M-39, M-40, M-41, M-42, M-43, M-44, M-45 (9)
- F: M-20 (1)
Total 14 + 3 + 13 + 5 + 9 + 1 = 45.
