# Round 13, reviewer A

Scope done: 115 mutants of round 12's fixes (97 + 18, plus 10 whole-file reruns of survivors) on orca, 2 CPUs, proot, detached copy at 939851e; 50 DECISIONS rows from 530 to 637 read, about 18 of them checked against code or arithmetic; hostile mission, CLI, remote-server and damaged-run probes. See the end for what was not reached.

Mutation result: 115 mutants, 83 killed by the round-12 tests, 19 survived the targeted tests (14 of them are equivalent, killed by older tests in the same file, or inert; 7 are findings below: A-3 to A-7 and the two minor ones in A-7). Killed (good): every remote.py resume/identity branch (If-Range, validator, probe total, header identity, cdf1_read, RemoteFile block, bathy rows), config id uniqueness and damaged_run_files, the stage-1 two-end Hs and wind, check_case, golden refusal, update_command, receipts --only, the credibility entry rules, the sanity digest, the report node test, mode notes, pad, CALM_SWH_M, FLAT_SHARE_MAX, YPLUS_LAM, NU_MAX (to 0.1 %).

### A-1. The "used by this mission" rule for radios.yaml misses the entry the UAS sortie hook reads when no rf link names it
severity: minor
lane: honesty
where: cafe/pm/credibility.py:442-464 (`entries_read`), :124-133 (`item_used`); cafe/pm/stage1.py:278-285 (`_uas_radio`), :301, :347 (`_uas_links` called for every sortie)
reproduction: on orca, `from cafe.pm import credibility as C; C.entries_read([])` -> `[]`; `C.entries_read([{"kind":"rf","radio":"xbee_pro_24"}])` -> `[('radios','xbee_pro_24')]`. `stage1._uas_radio(uas.load_platform())` reads `radios.yaml radios.rfd900x` (gt_dbi 2.0, gr_dbi 2.0, misc_loss_db 3.0, all `assumed: true`) for every UAS sortie whatever the mission's links are. So a UAS mission with no rf link (the "one UAS and no link" mission DECISIONS 646 and docs/CREDIBILITY.md use for its 156), or one whose rf link names another radio, counts those three assumed inputs (they set the lost-link margin) as "platform not used by this mission", and Input pedigree leaves them out.
why it matters: the same defect row 681 set out to remove (a used input shown as unused), still there for the UAS hook; the demo is not hit (its link names rfd900x), so no printed demo number moves.

### A-2. "The items of config/ are used by every mission" (DECISIONS 646, credibility.py:947) is false for some of them
severity: minor
lane: honesty
where: cafe/pm/credibility.py:947; config/assumptions.yaml:82-92 (`dtmb5415.u_D_rel`, `u_S_rel`, `u_nu_rel`), :203-283 (`stage3.glider.*` 8 keys, `stage3.usv.*` 2, `stage3.uas.*` 5); cafe/pm/dtmb5415.py:76-83
reproduction: `grep -n dtmb5415 cafe/pm/pipeline.py cafe/pm/stage1.py cafe/pm/report.py cafe/pm/budget.py cafe/pm/__main__.py` is empty; the only reader of `dtmb5415.<name>` is `dtmb5415.assumed` (its own validation study). Yet every mission's report counts the 3 as "used by this mission, ... verdicts depend on them" (the demo's 273 of 285 includes them). A glider-only or UAS-only mission also counts the `stage3.<other class>.*` keys.
why it matters: the sentence "N of the M in the catalogue are used by this mission" is round 12's answer to M-6 and is still too high by at least 3 for every mission; DECISIONS 646 says the reason (which keys a run read is not recorded) but states the opposite as a fact in CREDIBILITY.md ("used by every mission").

### A-3. The wave-form fade constants CP_MIN 2.0 and CP_FULL 3.5 are in no test
severity: minor
lane: tests
where: cafe/pm/env/coare.py:42 (`CP_MIN, CP_FULL = 2.0, 3.5`); tests/test_coare.py (new tests read `coare.CP_MIN`, `coare.CP_FULL` themselves)
reproduction: mutant `CP_FULL = 3.0` survives the whole of tests/test_coare.py (and `-k` of the four new tests); so does squaring the fade weight (`np.clip(...)**2`). Harness: scratch copy, one edit, `python -m pytest -q -x tests/test_coare.py`. (A mutant clip(0, 1.5) is killed by older tests in the file.)
why it matters: DECISIONS 653 states 2.0 and 3.5 and says the demo (dcp >= 3.93) is unchanged; nothing checks the values or the fade shape, only that Cd has no step.

### A-4. The diurnal-jet midpoint 0.2 m/s (DECISIONS 650) is pinned by a test that reads the same attribute
severity: minor
lane: tests
where: tests/test_surface.py:136; cafe/pm/env/surface.py:244 (`self.jet_mid`)
reproduction: mutant `self.jet_mid = j["u_max"]` (0.3 instead of 0.2) survives all of tests/test_surface.py: the assertion is `hypot(jet) == sl.jet_mid * dT0 / sl.jet_ref`.
why it matters: row 650 and PHYSICS say every member gets 0.2 m/s; a change to the config range or the formula moves every USV current with no test failing.

### A-5. The receipt stamp test does not require non-empty strings
severity: minor
lane: tests
where: cafe/receipts.py:81-82 (`missing = [k for k in STAMP if not isinstance(rec.get(k), str) or not rec[k]]`); tests/test_receipts.py r12_m35 tests
reproduction: mutant `if k not in rec` survives the full tests/test_receipts.py (136 s): no case has `"host": ""`, `"git_sha": 5` or `"date": null`.
why it matters: DECISIONS 675/678 say a result "carries `date`, `host`, `git_sha` and `code_digest`"; the string/non-empty clause is untested, and `rec['git_sha'][:10]` on a non-string would be a traceback.

### A-6. The `command` field written into a golden is not tested to be quoted
severity: minor
lane: tests
where: cafe/pm/acceptance.py:352 (`_golden_record`: `--mission {shlex.quote(mission)}`); tests/test_acceptance.py:316
reproduction: mutant that drops `shlex.quote` there survives all of tests/test_acceptance.py (626 s). DECISIONS 685 lists "the `command` field of a written golden" among the quoted words; the test only checks `endswith("--update-golden")` for a plain path.
why it matters: a mission path with a space or quote gives a stored command that does not paste as one command; nothing would fail.

### A-7. Other surviving mutants (small)
severity: minor
lane: tests
where: cafe/pm/env/surface.py:159-163 (`_med`: dropping the NaN filter survives tests/test_surface.py); cafe/pm/report.py:~1663 (the "stage 1 took X against Y planned" cause: `if s1:` instead of the comparison survives -k r12_m9); cafe/pm/stage3/nest.py (`NU_MAX * (1 + 1e-6)` survives -k r12: the "not a hair over" test is coarser than 1e-3 relative, 1e-3 is killed only by older tests); cafe/pm/orca.py:370-371 (`hour % 3`, and `pts is not None` -> True survive the new M-29 test, whose windows are hours 0-2 and 4-6 and always spectra: the older tests kill them).
reproduction: harness as in A-3, one edit each, named test selection; results in the orca log `rev13_a_mut*.log` (removed).
why it matters: each is a branch a round-12 test says it pins and does not.

### A-8. `python -m cafe.cfd WHAT ...`: any WHAT but two runs the free-surface study, and missing arguments are a bare IndexError
severity: minor
lane: robustness
where: cafe/cfd.py:~648-665 (`main`: `if what == "incidence" ... elif what == "external" ... else:` the surface branch)
reproduction: reading the code: `python -m cafe.cfd externel wigley DIR` (a typo) takes the `else` branch and starts the OpenFOAM free-surface characterisation, then writes `wigley.externel.json` stamped by `receipts.stamp` (hours of CFD for a file `cfd_receipts` never reads). On orca, `python -m cafe.cfd` gives `IndexError: list index out of range` and `python -m cafe.cfd bogus nosample DIR` a `KeyError: 'nosample'`, tracebacks, no usage line. Round 12 (M-35) turned this `__main__` into `main(argv)` and made the stamp part of its contract.
why it matters: the stamped file is what RUNBOOK sends a user to produce; a typo should be a usage error, not a long run.

### A-9. The stated sea-water parameters do not give the quoted eps_c
severity: minor
lane: documentation
where: cafe/pm/physics/comms.py:112-113; QUESTIONS_FOR_LAB.md:119; docs/PHYSICS.md:806; tests/test_comms.py:618
reproduction: the docstring says "eps_c = 72.8 - j118.9 (T 29 C, S 35, sigma 5.9 S/m)" at 915 MHz. eps'' = 60 lambda sigma = 60 x 0.32765 x 5.9 = 116.0, not 118.9 (118.9 needs sigma 6.05 S/m). With 116.0 the table changes at the second digit (|G| at 0.5 deg 0.84, phase at 5 deg -87, at 2 deg -155; with 118.9: 0.83 at 0.5 deg, -86, -154), so the quoted numbers follow 118.9 and the stated sigma follows 116. The test hard-codes 118.9.
why it matters: the error band quoted for the margin ("7.6 dB") rests on a parameter set that is not the one printed; the effect is below the other uncertainty, but a reader who recomputes from sigma gets different figures.

## DECISIONS rows read (530 to 637, spread)
530, 532, 534, 536, 538, 540, 543, 545, 547, 549, 551, 553, 556, 558, 560, 562, 564, 566, 568, 570, 572, 574, 576, 578, 580, 582, 584, 586, 588, 590, 592, 594, 596, 598, 600, 603, 605, 607, 609, 611, 613, 615, 617, 619, 621, 623, 625, 627, 630, 632, 636, 637 (52). Checked against code or by arithmetic: 530 (`n_var` in `s_emulator`), 536 (`running_mean_ok` blocks), 538 (`open_` Wilson bound), 540 (`COVERAGE_DUST`), 551 (`pos<=3.5`), 553 (`SELECTION` 2), 562 and 580 (`pm_shape`, `pm_word`: a_s3_s1, a_s3_x, one-letter tags), 568 (every GB figure recomputed from `env_model_gb` and `padding`: all agree), 586 (`_deploy_in_window`), 596 (`SAME_SEED_K_TOL` 1), 603 (`bounce_back` against Bouzidi's formula: matches), 607 (kind x field refusal), 617 (`_read_json` returns a dict only), 632 (constants, 0.21 U^2/g = 1.04 mm at 0.22 m/s). No row contradicted its code. The q13 report's glider_eq card (18 of 64, Wilson 90 % 0.1991 to 0.3811, 95 % lower 0.1859) recomputed independently: equal.

## Probes that found nothing (for the record)
- 50 mission variants through `validate` (outside box, 30-day window, year 9999, NaN/inf, swapped box, ids with unicode/newline/empty, 65 vehicles, links to nothing, seeds of 2^70): every refusal is an `error:` line, exit 2, no traceback; `plan` on a 30-day window, a 2.9-million-day window and a 2^70 seed gives a plan or the memory refusal.
- 157 damaged-file cases on a copy of q13 (26 JSON files x `{}`, `[]`, `null`, 0, "x", `{"a":1}`, half the bytes) through `report --run`: no traceback; every damage to a ledger is exit 2 or listed in `ledger_problems`.
- A local HTTP server with a strong ETag, an ETag that changes per request, an ETag on 200 only, `bytes 0-0/*`, and one that ignores Range: `download` and `RemoteFile` finish or refuse as designed, no loop.
- `receipts --only` with '', 'x,', ',', ' ': exit 2 with the groups named. `python -m cafe.receipts stamp` on a directory, a list, a missing file, binary: an `error:` line.
- `report --run` with CAFE_DATA unset and `audit --ledgers-only` on the q13 copy: report written, 0 audit problems.

## Not covered
- DECISIONS rows 641-690 not mutated: 650 (jet) only through A-4; 652, 655, 656, 657-659, 663, 676 are documents or "no change" rows (tests for the docs, tests/test_config_docs.py, not mutated); 661 only YPLUS_LAM, CALM_SWH_M, FLAT_SHARE_MAX; 665-666 download only through the mutants listed; 669 once; 686 by two mutants (conventions, environment) and one for hycom; the GEBCO and OutsideData labels not mutated separately.
- Mutants were single edits chosen by hand (115), not a tool's full set; the stage-3 and emulator tests were not mutated. Only the targeted tests (and, for survivors, the whole file) were run, not the full suite.
- No run of RUNBOOK, no `acceptance` run (golden refusal tested through its tests only), no stage-1 or stage-3 computation, no CFD.
- Incident: a probe of CLI calls included `whatif --mission missions/tepex_c_demo.yaml` with no modification (a real run, not a check). Started through `PMX=pm_rev13_a2`, it outlived the tool call; killing the process by pid was refused as unverifiable, so it was left to end. `/data/emulator/train.parquet` was last written at 23:53, before it started, and `pm_rev13_a2/runs` does not exist, so it does not seem to have written anything shared; recorded as P-R13A1 in review/orca/PROBLEMS.md. A process on orca of about 45 minutes' age may be it.
- Cleanup: the worktree ../cafe-rev13-a and orca's pm_rev13_a, pm_rev13_a2 and runs/rev13_a_* were removed at the end (see the last lines of this file if any is left).

total: 9 findings (0 critical, 0 major, 9 minor)
