# Round 20, batch A hand-back (builder; branch r20-a, cut from premission-step4 at 8e22951)

Findings: M-1, the M-11 comment, the S1e and S1g tests of M-10. Files touched: `cafe/pm/stage1.py`, `tests/test_stage1.py` (one pin), `tests/test_round20_a.py` (new), this file. Nothing else.

## LOUD: M-1 IS MAJOR BY THE LEAD'S OWN CRITERION (a real pass-to-fail flip between the two orders)

The merge found 0 sign flips in 272 samples; I looked wider and found them, at sample level and at member level (the verdict).

1. Function level (`comms.acoustic_link` with the real Bellhop, `benthos_atm960` MF, `probe_r20a_order.py`, job `r20a_probe1`, rc=0; the probe is deleted, not committed): 6 made-up but ordinary sound-speed profiles (tropical, deep mixed layer, surface duct, sharp thermocline, cold, warm cap; Mackenzie's formula on a temperature profile of my own to 4,000 m), winds 2, 6, 10 m/s, 6 transducer-depth pairs, ranges every 100 m wherever the Thorp margin is within +-6 dB: **2,496 ambiguous samples, 27 of them with a refined margin above 0 in one order and at or below 0 in the other (1.1 %), largest difference between the two orders 26.5 dB**. For the glider-surfaced-beside-the-ship pair (1 m and 5 m: 414 of the samples): 3 flips (sharp thermocline, wind 2 m/s, 4.7 and 4.8 km: -7.37 and -7.93 dB against +2.59 and +3.23; wind 6 m/s, 3.8 km: -8.47 against +0.70).
2. Member level, a real `stage1.evaluate_link` (`probe_r20a_member.py`, the CI fixture's `glider_eq-ship-acoustic` link `when: surfacing`, required fraction 0.9, glider surfaced beside the ship, the sharp-thermocline profile as `env.sound_speed`, wind 2 m/s, 2 members, 60 required samples each) on the UNFIXED tree (job `r20a_mem_base`, rc=0): at 4.7 km, written `a: glider_eq, b: ship` the link has `frac` 0.0, `success` False, margin -4.23 dB; written `a: ship, b: glider_eq` it has `frac` 1.0, `success` True, margin +2.87 dB. **The same link, the same members: FAIL one way round, PASS the other.** At 4.8 and 4.9 km (wind 2) and 3.7 to 3.9 km (wind 6) both orders fail but by different margins (-5.19 against -4.91, -6.50 against -1.78, -8.33 against -5.83 dB, ...). On the FIXED tree (job `r20a_mem_fix`, rc=0) both orders print -4.23 dB, `frac` 0.0, `success` False at 4.7 km, and the lower of the two everywhere else.
3. Conditions: the profile is mine, not a GOFS one; the demo (q21) has no acoustic link in range so none of its numbers move. A real mission with a glider surfaced within about 3 to 6 km of the ship (or two gliders at different depths) in a stratified ocean can be hit. The flip direction in the base tree depends on which end the mission file names first, so a mission's acoustic verdict was decided by a typing order in the cases above. This is a wrong verdict, not just a wrong margin: it is MAJOR by "M-1 becomes MAJOR if you find a case where the order flips a pass to a fail". The lead decides the severity entry in HANDOFF/merged; I changed nothing in documents.

OD-1 default taken ((a): run both directions, keep the lower margin) and it is the safe one: it can turn a pass into a fail, never the reverse. One honesty note for DECISIONS: the minimum of two noisy estimates of the same quantity is biased low by about half their spread (up to several dB where the spread is large), so the printed margin is a conservative figure, not an unbiased one; the mean (OD-1 (b)) would be less biased and equally order-free; it can still sit on either side of 0 where the two directions straddle it, so it would pass what the lower one fails. Neither is "right"; the lower one is the safe one. (c), a canonical order, is order-free too but arbitrary and can hide a failure the other direction shows.

## Commits (on r20-a; messages end with the Co-Authored-By line)

See `git log 8e22951..r20-a`. One commit for the code and tests, one for this hand-back (below).

## Fix 1: M-1 (`cafe/pm/stage1.py`, `_bellhop_member`, `_acoustic`)

- `_bellhop_member` clips the two depths as before, then runs `comms.acoustic_link` in (tx, rx) and (rx, tx) and returns `np.fmin` of the two margins (a direction whose TL is not finite does not hide the other). Two equal clipped depths are one run (the two directions are one run): a glider at the ship's 5 m, or two surfaced gliders (both clipped to 1 m), do not pay the doubling.
- `_acoustic`: the label gains " (the lower of the two directions)" after "... ambiguous samples" only where Bellhop ran for at least one sample (`done > 0`); the Thorp-only labels are unchanged (they claim nothing about directions). The docstring says both directions are run.
- Callers checked: `_bellhop_member` has one caller (`_acoustic`); `_acoustic` has one (`evaluate_link`). Nothing parses the method string (grep `report.py`, `credibility.py`, `pipeline.py`, `__main__.py`, `whatif.py`: it is printed as "Method: ..." at report.py:1725 and stored; no digit in the new words, so `check_rendered` has nothing to trace). The code digest of the pipeline includes `stage1.py` (a normal consequence of any source change).
- Cost: Bellhop runs double for members with an ambiguous sample whose two transducer depths differ (about 0.2 s a run, two runs per direction, as before); a glider-glider `when: surfacing` link (both clipped to 1 m) and a glider at the ship's transducer depth do not. State it in the DECISIONS row. The demo does not move (no Bellhop in q21: both acoustic links are 555 and 632 km long, out of range).

### Tests (all in `tests/test_round20_a.py`; "before" = a detached worktree of 8e22951 with only the new test file added)

| test | before (8e22951) | after |
|---|---|---|
| `test_the_margin_of_an_acoustic_link_does_not_depend_on_which_end_is_named_first` (fake Bellhop: +2 dB margin when the shallow transducer sends, -2 when the deep one does; one order passed with `frac` 1.0 before) | FAIL | pass |
| `test_the_margin_is_the_lower_of_the_two_directions_whichever_sends_the_larger_loss[7.0-3.0]` and `[3.0-7.0]` | FAIL both | pass |
| same, `[5.0-5.0]` (equal losses: both orders always agreed) | pass (a guard, not a before-failure) | pass |
| `test_the_label_says_the_refined_margin_is_the_lower_of_the_two_directions_only_where_bellhop_ran` | FAIL | pass |
| `test_a_direction_bellhop_gives_no_number_for_does_not_hide_the_other` (`np.fmin`) | FAIL | pass |
| `test_two_equal_transducer_depths_are_one_bellhop_run_and_the_same_margin` (8 `_run_bellhop` calls for 2 evaluations x 2 members x profile/iso; 0.2 m clipped to 1 m equals the other end's 1 m: one run) | pass (guards the saving, not a before-failure; always-two-runs would fail it) | pass |

Jobs: before `r20a_t3_base` rc=1 (`FFF.F.F..`: 5 failed, as listed), after `r20a_t3_fix` rc=0 (9 passed). Earlier failures of my own first drafts (a Thorp margin out of the band at 4.5 km, 4 calls not 8 for 2 members, `atol` 1e-6 against the 1.3e-5 of `km_north`'s degree conversion) were test errors, fixed before the runs above.

## Fix 2: M-11 (comment only, `cafe/pm/stage1.py` above `ACTING`)

The comment now says the step is "one discrete event less" (a surfacing or an apogee), gives the apogee's size (138e-6 m3 x (101325 + 505e4) Pa / 0.4 = 1776.6 J = 1.645e-4 of 1.08e7 J for a 500 m dive, against 1.6148e-4 for the surfacing; about 3.3e-4 when both cross), says that case is DERIVED, not seen (every step of the demo's record is of the surfacing's size), and names the per-member ocean displacement as a second reason the current columns' index in that row carries no information. I checked the two energy lines against `glider.py:490-499` and `pump_energy_J` (`|dV| x (P_ATM + p_dbar x 1e4) / eta`). Honest inconsistency left as the merge found it: the older sentence uses the platform's 150.83 cc (1.62e-4) and the new one reviewer B's 138 cc (the demo record's trim, 1.6148e-4); I did not reconcile them (no number was measured by me). No test pins the comment (grep `tests/` for "one surfacing less": none). For DECISIONS 999 (batch G): amend with the same two events, the same sizes and "derived, not seen".

## Fix 3: S1e and S1g tests (M-10)

Written in `tests/test_round20_a.py`; checked against the surviving mutants themselves (the "must fail" is on the mutant, since the unfixed tree has the correct code), by editing a throwaway worktree of 8e22951 and reverting it with `git checkout`:
- S1e, `for u in _ends(out, a, b, "uas")[:1]:` in `evaluate_link`: `test_s1e_...` FAILS (job `r20a_mut_s1e`, rc=1); passes on the unmutated tree (`r20a_t3_fix`, `r20a_t3_base`: it is the 8th character `.`). The test gives u1 a 30 s grid from t0 and u2 a grid 15 s later (20 flying samples each), expects `t` to equal the union of the records and both grids, and `need_count` 39 (19 of u1's samples and 20 of u2's), in both orders.
- S1g, `n_never_required` counted with `<= 1` instead of `== 0`: `test_s1g_...` FAILS (job `r20a_mut_s1g`, rc=1); passes unmutated. Counts `[1]*10 + [0]*14` give 14, `ones(24)` gives 0, `[2]*10 + [1]*4 + [0]*10` give 10.

## Pins moved (exactly one)

`tests/test_stage1.py::test_an_ambiguous_acoustic_link_is_refined_with_bellhop_on_the_gofs_profile_at_the_slant_range`: `len(calls) == 2 and {(tx, rx, wd)} == {(300.0, 5.0, 4000.0)}` became `len(calls) == 4 and {...} == {(300.0, 5.0, 4000.0), (5.0, 300.0, 4000.0)}`. Reason: the product now runs Bellhop in both directions (each the profile and the isovelocity column), so there are twice as many calls and each depth pair appears both ways. No assertion on a margin changed (the fake's TL is symmetric, so the refined margin is still `thorp - 7`). `tests/test_round17_a.py`, `test_round17_m.py`, `test_round18_a.py`, `test_round18_m.py` have no pin on `_bellhop_member`, `tx_depth`/`rx_depth` or an `acoustic_link` call count (grepped): untouched. `tests/test_round18_a.py` is not touched at all, so batch B's hunks there are free.

## Gates and runs (orca, proot, 2 CPUs, directories pm_r20a*, never the full suite, gate or a demo)

- `ruff check cafe/pm tests` clean ("All checks passed!", after wrapping three of my own long lines); `mypy cafe/pm` strict "Success: no issues found in 55 source files".
- `tests/test_stage1.py` whole: rc=0, 174 passed (`r20a_r1`, before the last comment wraps in my tests; `r20a_f2`: `test_round20_a.py` + `test_stage1.py`, rc=0, 183 passed, on the final tree).
- `tests/test_round20_a.py test_round19_a.py test_round17_a.py test_round17_m.py test_round18_a.py test_round18_m.py test_round18_x.py test_round18_c.py test_round15_a.py` (job `r20a_r2`): rc=0, 223 passed (run before my last test-file edits, which changed no assertion and only wrapped lines; `r20a_f2` re-ran the two files that changed).
- Coverage of `cafe/pm/stage1.py` from `test_round20_a.py` + `test_stage1.py` alone (`r20a_cov`, rc=0): 99 %, 3 lines unrun (686, 870, 1104: none of them mine; other test files cover them). Every line I added is run; stage1 is outside the 100 % gate (physics, stats, env), I touched none of those.
- No banned token (`audit.BANNED`) in the added text: I did not use the words it names (no skips, no placeholders).

## Not verified, still wrong or worth a second look

- The flip finding rests on profiles of my own (Mackenzie's equation on a plausible temperature profile), not on a GOFS column, and on `benthos_atm960` MF only (my probe's `whoi_micromodem` leg did nothing: a bug in the probe, not fixed, no rows). No real `run_batch` of an acoustic link; the member-level run used `evaluate_link` on the CI scene with my profile.
- The reviewers' explanation (Bellhop's own numerical error at a 1 m endpoint in a shadow) is plausible and not tested by me; I did not look into why Bellhop's two directions differ (not reciprocal in practice: the incoherent TL of arlpy's Bellhop with `nbeams=0`, `min/max_angle` -80/80, a 48-point range grid, interpolated). A finer `n_grid` or an explicit beam count might narrow the gap; not tried, out of scope. Worth a lab-level question if the owner wants the real error bar.
- The minimum is biased low (see above). The fix does not make the margin accurate, only order-free and conservative.
- The sampled margin is still per (member, link): one profile and one depth pair per member (the existing `ponytail:` note), unchanged.
- The M-11 comment: the apogee case is derived, not seen.

## Hunks for other batches (not edited by me)

- `cafe/pm/physics/comms.py` (`acoustic_link` docstring, physics file, nobody's batch in the table; read only for A): add "Bellhop's TL is not reciprocal in practice: the margin differs between (tx, rx) and (rx, tx), by up to 26 dB in the round 20 probes; `stage1._bellhop_member` runs both and keeps the lower". Batch G (or the lead) decides whether a docstring edit in `comms.py` belongs to anyone; no code change is needed there.
- Documents (batch G): DECISIONS new row for M-1: "an acoustic link's refined margin is the lower of Bellhop's two directions (tx, rx) and (rx, tx) (OD-1 (a)); both are run only where the two transducer depths differ; Bellhop runs double there; the label says '(the lower of the two directions)'; the printed margin is conservative (the minimum of two noisy estimates is biased low) and order-free; the verdict flip of the unfixed tree: 4.7 km, wind 2 m/s, sharp thermocline, FAIL (-4.23 dB) one way round and PASS (+2.87 dB) the other; 27 of 2,496 ambiguous samples flipped in the probes, up to 26.5 dB apart". DECISIONS 999: amend as in Fix 2. `docs/PHYSICS.md`: Bellhop's non-reciprocity and the rule. QUESTIONS_FOR_LAB: OD-1 sub-item with its default (a), alternatives (b) the mean, (c) a canonical order. q22 against q21: no link number moves (no Bellhop in q21); `review/round_20/q22_vs_q21.md` need not mention M-1 beyond "unchanged".
- RUNBOOK: if the card or the report says anything about which end is named first for acoustic links, it should now say the number is the lower of the two directions (I found no such sentence; I did not read the whole RUNBOOK).

## Leftovers

- Laptop: the throwaway worktree `../cafe-r20a-base` (detached 8e22951, with the new test file copied in) is removed at the end by `git worktree remove --force`; no other file outside the repo; the scratch probes `probe_r20a_order.py`, `probe_r20a_member.py`, `probe_r20a_thorp.py` were deleted from the worktree and never committed.
- Orca: the directories `~/cafe-worker/cafe/pm_r20a`, `pm_r20a2`, `pm_r20a_base`, `pm_r20a_mut1`, `pm_r20a_mut2` (removed by those exact names at the end, with their `.pmx.job.*` markers if any); the logs `~/cafe-worker/logs/r20a_*.log` (r20a_probe1, r20a_mem_base, r20a_mem_fix, r20a_t1..t3_fix/base, r20a_mut_s1e, r20a_mut_s1g, r20a_r1, r20a_r2, r20a_f1 (rc=4: my `-k` expression was split on spaces, no test ran), r20a_f2, r20a_cov) are left in place as the evidence and can be deleted by exact name. Nothing in `/tmp` on orca, nothing in `cafe/data` or `pmdata/cache`, no kill, no stash, no push.
