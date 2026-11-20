# Batch A hand-back (M-3, S-9, S-10)

## Changed (cafe/pm/stage1.py only, net negative)
- `_bellhop_label`: the capped clause is now "; N of them had a Bellhop excess beyond +-60 dB (the assumed cap) and were held at it". No cause, no sign, no "ray", "almost", "bound". Count not split by sign.
- `NOT_EXERCISED_NOTE`: ", and no number of members changes that" deleted. Name kept (Batch B imports it).
- comms.py untouched.

## Evidence
- Base (f62defd, detached worktree, pm_r23abase): tests/test_round23_a.py, 2 tests, both FAIL (r23a_b1 rc=1). Fixed tree (pm_r23a, r23a_6): rc=0.
- tests/test_round23_a.py, test_round21_a.py, test_round22_a.py, test_stage1.py: r23a_1 had one failure, my own test's grid count (480 vs my guess of 500); corrected to == 480. test_report.py, test_credibility.py, test_round23_a.py: r23a_2 rc=0 (431 passed by progress chars).
- mypy cafe/pm: r23a_5 rc=0 (57 files). ruff: only 4 E501 in tests/test_round21_e.py:217 and tests/test_round22_m.py:140,148,172, all pre-existing, not mine (my file is clean after a fix).

## Claims left and the test that holds each
- Capped clause appears iff capped and total and ran, with exactly that text; label has no "ray", "almost", "bound", "no number of members": test_m3 over 480 `info` combinations (done 0-3, total 0-3, capped 0-3 with capped<=done<=total, beyond 0-2, ran both, four run-range pairs).
- NOT_EXERCISED_NOTE exact text: test_s9. 
- "the Bellhop excess is held within 60 dB, so it cannot change which they are" (S-11, KEEP): unchanged, held by tests/test_round22_a.py.

## Pins moved (reason: the product's sentence is now the intended one)
- tests/test_round21_a.py:433,435,437 and tests/test_round22_a.py:97 (the `_expected` oracle): old parenthesis and "held at ... bound" text replaced by the new clause.
- tests/test_stage1.py:1754 pins "median" not in the note: unchanged and green.

## Siblings
- grep of cafe, tests, docs, bin for "no ray", "dB bound", "almost none", "no number of members", "changes that": remaining hits are batch B's (report.py:345, test_report 1919/2739/2759, test_credibility 934, CREDIBILITY.md 66) or a comment in comms.py:46 ("no ray reached the receiver", a code comment, batch owner of comms; not printed). docs/RUNBOOK 188 and CREDIBILITY 201 describe the note without the deleted clause (CREDIBILITY 201 says "no member count decides it" about the Uncertainty factor, not the note).

## Hostile attempts
Label: capped with total 0 or ran False (clause not printed, tested), capped==done==total, beyond>0 with each branch, runs_lo/hi None, equal and different; `info` summed by `merge` (test_round22_a property test, green). Note: constant only, read by import in report.py and credibility.py (test_report/test_credibility green).

## Hunks for others / document sentences
None required. Demo q25 vs q24: no move (the demo has no Bellhop-run link; the note's text moves in report.json of any NOT EXERCISED link, which q24 may have; expected: only that note text changes, no verdict, count or interval).

## Not verified
Full suite, gate, mutation not run. test_stage1.py full result seen only through the 325-character progress of r23a_1 (one F, mine, since fixed; not re-run after).

## Leftovers
Orca dirs pm_r23a, pm_r23a2, pm_r23abase (mine); logs r23a_*. Base worktree removed.
