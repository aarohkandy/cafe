# Round 20 merged findings (BRIEF 5.6 step 2)

Inputs: reviewer_a.md (4 findings), reviewer_b.md (3), reviewer_c.md (5), reviewer_d.md (7) = 19 source ids. Merged to 13 findings, M-1 .. M-13; every source id appears in exactly one merged finding (B-1 is M-1; C-2 and A-1 form M-2; C-1 and C-3 form M-3; C-4 is M-4; D-1 and D-2 form M-5; C-5 is M-6; D-3 and D-4 form M-7; D-5 and D-6 form M-8; A-3 and D-7 form M-9; A-4 is M-10; B-2 is M-11; B-3 is M-12; A-2 is M-13).
Verified by this merge against HEAD 446d539 (code of 979e37a; every later commit is a document): by reading the cited code, and on cafe-orca (proot, 2 CPUs, detached worktree `../cafe-rev20-v`, private `pm_rev20_v`, both removed at the end) by four small scripts, kept only in the lead's scratchpad `.../scratchpad/v/` and in the (removed) worktree: `c1.py` (`intervals.verdict` for the C-1 counts), `c2.py` (the model's `two_ray_loss_db` minus the project's own flat-earth Fresnel reference, `tests.test_round18_b.band`, at 0.5 to 2.2 m with 10, 15 and 2.2 m partners, then a 0.05 m grid), `b1.py` and `b2.py` (a real `comms.acoustic_link` with Bellhop, the two depth orders, two made-up warm-tropical sound-speed profiles, 3 winds, 1.5 to 9 km). The "check" line of each finding says what was done. Not done here: any full Stage-1 run, any report render, any mutant, any test.

**ROUND 20 IS NOT CLEAN under the owner's stop rule.** No finding is critical or major (0 and 0), but three give wrong data to act on, each conditional on a mission the demo does not make: M-1 (an acoustic link's printed margin depends on which end is named first wherever Bellhop refines it: 0 to 17.8 dB in my probes), M-2 (the link card is silent for an RF end of 0.55 to 2.2 m, where the margin is too high by up to 5.1 dB, and L23 says the card speaks for any height off a row), M-3 (the RUNBOOK tells the user to read a GO of a partly-needed link as a GO on the members that needed it: 3 failures of 64 is GO, 3 of the 24 that needed the link is MARGINAL). The stop-rule count was 0 before this round and is **0 after it** (3 findings with wrong data; rounds 15 to 20 have each had at least one). None changes a q21 number or any text of the demo's page (the demo has no acoustic link in range, no RF link with an end of 0.55 to 2.2 m except the USV's whip with a UAS, and no link with `n_never_required` above 0).

Severity: 0 critical, 0 major, 13 minor. Status: 13 confirmed (M-1, M-2, M-3 and the arithmetic of M-2's A-1 half reproduced or recomputed here; the others by reading the cited lines, with the reviewer's run as their evidence); 0 partly; 0 not confirmed; 0 refuted. The Totals section says which were run here.

INCIDENTS and side effects of this merge: one scratch worktree `../cafe-rev20-v` (detached, removed with `git worktree remove --force`), one orca directory `~/cafe-worker/cafe/pm_rev20_v` (removed by that exact name; its job marker `.pmx.job.pm_rev20_v` removed too, none existed), my scripts `c2.py`, `c1.py`, `b1.py`, `b2.py` lived in that directory only (gone with it; `b1.py`, `b2.py`, `c1.py` were deleted from the worktree before `c2.py`'s second form was synced). Nothing in `/tmp` on orca or on the laptop, no shared store, no `pmdata/cache`, no demo, gate or suite, no Azure resource, no kill, no stash, no commit. ssh to orca answered every time. The only file written in the checkout is this one.

---

## Critical

None.

---

## Major

None. (M-1 is the closest: if a builder finds a sign flip of an acoustic margin between the two orders on the CI fixture it becomes major, as round 19's M-1 was; I found none in 272 ambiguous samples, see M-1.)

---

## Minor, wrong data: yes (M-1 to M-3)

### M-1. An acoustic link's margin depends on which end is named first, wherever Bellhop refines it: the transducer depths are passed as (tx = end a, rx = end b)   (sources: B-1)
severity: minor / status: confirmed / lane: numerics, reproducibility (stage 1 links)
wrong data: yes, conditional. Output: `margin_db_median` (and every sample of `margin_db`, and so a pass fraction where the margin is near 0) of an acoustic link between a glider (surfaced, depth clipped to 1 m) and the ship (transducer 5 m), or two gliders with different depths, wherever the Thorp margin is within `ambiguous_db` of 0 and Bellhop runs; the link card's method line ("Thorp ... Bellhop on n of m") does not say the refined number is one of two. Not in q21 (its two acoustic links are 555 and 632 km long, out of range 100 %, so no Bellhop and no ambiguous sample). The verdict is the printed thing that did not flip in anything I ran (reviewer B's 4 members: equal pass fractions in both orders; mine: no sign flip), so the "verdict follows the typed order" claim of round 19's M-1 is not repeated here, only the margin.
where: cafe/pm/stage1.py:652-657 (`_acoustic`: `_bellhop_member(..., float(A[3][k, m]), float(B[3][k, m]), ...)`), :632-633 (`_bellhop_member`: `tx_depth=clip(tx)`, `rx_depth=clip(rx)`), cafe/pm/physics/comms.py:489-491 (`bellhop_tl(r, f, z, c, tx_depth, rx_depth, ...)` twice, on the profile and on the isovelocity column)
claim: B: 3 km 9.45 against 14.04 dB (max |difference| 6.84), 4 km 2.84, 5 km 2.24, none at 6 km (Thorp decides, both orders equal), through a real `run_batch` of the CI fixture; at function level -20.70 against -20.24 dB for (5, 1) against (1, 5).
check: ran on orca (`b1.py`, `b2.py`, `comms.acoustic_link` itself, Bellhop present, benthos_atm960 MF, wind 6 m/s, a warm-tropical profile of my own to 4,000 m, tx 5 m / rx 1 m against tx 1 m / rx 5 m, 1.5 to 9 km every 250 m): outside the ambiguous band the two orders are identical to the last digit (1.5 to 3.0 km and 5.5 to 9 km); inside it (3.25 to 5.25 km, Thorp +5.5 to -4.9 dB) they differ by -4.2, -3.6, -0.6, +2.1, +4.1, -2.3, -16.9, -17.0 and -15.1 dB (margins -11.6 against -7.4 at 3.25 km; -29.8 against -12.9 at 4.75 km). Then 272 ambiguous samples (50 m step, 2 profiles, winds 2, 6, 10): median |difference| 12.2, 4.3, 2.1 dB (warm profile) and 0.7, 0.2, 0.1 dB (a deep mixed layer), maxima 17.8 and 3.4 dB; 0 sign flips (every refined margin was negative, so no verdict moved). So B's finding holds and is larger on a profile with a shadow zone than on B's CI fixture. Ray tracing is reciprocal in theory; the spread is Bellhop's own numerical error (its incoherent TL at a depth of 1 m in a shadow), as B says. Not run: the CI fixture through `run_batch` (B's script `ac_order.py` needs its private `rev20_b_ci` environment, deleted), a real GOFS profile.
root cause: `_bellhop_member` hands the two depths to Bellhop in link order, and nothing symmetrises the two directions, whereas the neighbouring RF code does (`_link_hs`: "the worse margin of the two ends' Hs: the same whichever end is named first") and round 19's M-1 made the required moments order-free.
fix: in `_bellhop_member` (stage1.py only) run both directions, (tx, rx) and (rx, tx), and keep the LOWER margin of the two per sample (OD-1); the label stays "Thorp/Stojanovic budget on the slant range, Bellhop on n of m ambiguous samples" and gains "(the lower of the two directions)". A test: a link written `a, b` and `b, a` gives equal `margin_db`, `frac` and `success` with a fake `comms.acoustic_link` that returns different margins for (5, 1) and (1, 5) (fail before: unequal), and the margin equals the lower of the two. What it could break (foresight): (1) the number of Bellhop runs doubles per member and link (about 0.2 s each, only for members with an ambiguous sample), so a CI link test's time doubles: say so in the DECISIONS row; (2) `tests/test_stage1.py`, `tests/test_round17_m.py`, `tests/test_round18_a.py`, `tests/test_round18_m.py` and `tests/test_round17_a.py` call `_bellhop_member` or `comms.acoustic_link` with fakes and may count calls or pin `tx_depth`/`rx_depth`: read them and adjust only the count, never an assertion on a margin; (3) the demo's numbers do not move (no Bellhop in q21), so q22 against q21 must show zero difference in every link number; (4) the minimum is conservative (it can turn a pass into a fail, never the reverse), which is the direction `_link_hs` already takes; the mean of the two is the alternative (OD-1); (5) `comms.acoustic_link`'s docstring and `docs/PHYSICS.md` should say that Bellhop's TL is not reciprocal in practice (documents batch).
owner decision: OD-1.
sources: B-1

### M-2. The link card is silent for an RF end of 0.55 to 2.2 m, where the margin is too high by up to 5.1 dB; L23 says the card speaks for any height off a row; the nearest-row sentence is dropped at exactly 0.55 m   (sources: C-2, A-1)
severity: minor / status: confirmed / lane: honesty, documentation, physics
wrong data: yes, conditional (C-2): an RF link with an end of 0.55 to 2.2 m (a ship mast of 1 m with a glider, an edited platform file, the USV's whip with a ship mast of 10 m: `ship_antenna_m` defaults to 10 m) prints no card at all, and its margin is optimistic by up to 5.1 dB, the direction that turns a NO-GO or MARGINAL into a better verdict; and the L23 sentence "a height further off is not measured, the card says so and names the nearest listed pair as biased" is false: the card names a pair only within 0.05 m of a row, says "not measured" with nothing named from 0.05 to 0.55 m, and prints nothing above 0.55 m. A-1 half: wrong data no (the card still prints and still says "not measured"; one clause is missing at one value). q21: no card prints and none should (the demo's RF link has a UAS end).
where: cafe/pm/report.py:779 (the trigger `h <= RF_LOW_ANTENNA_M + RF_NEAR_ANTENNA_M`, 0.55 m), :805 (`near[1] <= RF_NEAR_ANTENNA_M`), :732 (`RF_NEAR_ANTENNA_M = 0.05`), :755-758 (`_nearest_row` returns `abs(0.55 - 0.5)` = 0.050000000000000044); cafe/pm/credibility.py:92-94 (L23's sentence), `LOW_ANTENNA_PAIR_BAND` and `LOW_ANTENNA_HS_BAND` (:56-60); docs/CREDIBILITY.md:149 (the same text); DECISIONS 1000 (states the cliff but not its size)
claim: C: the card is silent at 0.5500001, 0.56, 1.0 and 2.2 m with a 15 m mast; 0.6 to 2.0 m unmeasured, too high by up to 5.1 dB (1.0 m with 15 m); L23's "names the nearest pair" is true only within 0.05 m. A: at (0.55, 15) the card prints no nearest-pair sentence, at (0.549, 15) it does; `abs(0.55 - 0.5)` is above 0.05.
check: A-1: `abs(0.55-0.5)` = 0.050000000000000044, `0.5+0.05` = 0.55, so the trigger admits 0.55 and `_nearest_row`'s difference does not (run on the laptop, plain arithmetic); read of lines 779 and 805. C-2: ran on orca (`c2.py`, the project's own `band`, i.e. the model's `two_ray_loss_db` minus the flat-earth Fresnel two-ray of `tests/test_round18_b.py`, Hs 0, 300 m to the radio horizon or 12 km, 400 points): lower end with a 15 m partner, minimum / median / maximum dB: 0.55 m -3.5 / +1.1 / +1.7; 0.6 m -4.0 / +1.0 / +1.9; 0.75 m -4.8 / +0.2 / +1.1; 1.0 m -5.1 / -0.4 / +0.4; 1.5 m -4.4 / -0.6 / +0.2; 2.0 m -3.6 / -0.5 / +0.2 (the table's 2.2 m is -3.3 / -0.4 / +0.2; 0.5 m is -2.9 / +1.3 / +2.2: the first two rows reproduce the table). With a 10 m partner (the ship's default height) -2.0 to -4.0 dB at 0.55 to 1.0 m, -4.1 at 1.2 m. A 0.05 m grid from 0.55 to 2.2 m: the worst too-high figure is -5.13 dB at 1.0 m (15 m partner), -4.1 dB at 1.2 m (10 m), -2.39 dB at 2.2 m (2.2 m partner); the worst too-low is +1.9 (15 m), +2.1 (10 m), +3.3 dB (2.2 m partner, at 0.6 m). So C's 5.1 dB holds, and the unmeasured range is worse on the too-high side than any listed row (worst listed: 3.3 dB). It is a bound against a Fresnel two-ray with no surface wave, as L23 says of all its figures.
root cause: round 17 to 19 built the card for the heights the platform files and the mission schema can give a low end (below 0.5 m, then the 0.05 m step above it) and kept 2.2 m only as a row for pairs that have a lower end; nobody asked what a height between the last schema floor and the last row does, and L23's sentence was written for the exact-row case.
fix (OD-2): the card also speaks for every RF end up to the highest height of the table (2.2 m, plus the 0.001 m row tolerance): for an end of 0.55 to 2.2 m that is not a row it says "An end of this RF link has an antenna of 0.55 to 2.2 m: ... not among those measured" and, when the partner is 10 to 15 m, adds the measured envelope "(for 0.55 to 2.2 m with a partner of 10 to 15 m the margin was too high by up to 5.1 dB and too low by up to 2.1 dB, Hs 0, 0.05 m grid, round 20)"; with any other partner (a UAS, a shore end) it says "no band is stated". The two envelope figures are constants in `credibility.py` (`LOW_ANTENNA_MID_BAND`, partner 10 or 15 m, with the grid), a test recomputes them with `tests/test_round18_b.band` over the 0.05 m grid and 10 and 15 m partners to 0.1 dB, and L23 prints them (L23 is generated from the constants). A-1: `_nearest_row`'s difference is rounded to 9 decimals (`round(diff, 9) <= RF_NEAR_ANTENNA_M`), and a test at (0.55, 15) and (0.3, 0.55) expects the nearest-pair sentence. L23's sentence is rewritten to what the card does: names the nearest pair within 0.05 m, says "not measured" between 0.05 and 2.2 m, and gives the envelope for 0.55 to 2.2 m. What it could break (foresight): (1) an exact row now prints a card at 2.2 m too: the USV's whip (2.2 m) with a 15 m ship mast is a table row that no card ever showed, and now will (it prints "-3.3 to +0.2: margin too high by up to 3.3 dB and too low by up to 0.2 dB"), and the demo's `usv-uas-rf` (whip with a UAS, `known` has one height) gets a card "not among those measured, no band is stated": q22's `report.json` gains one `low_antenna` text, so `review/round_20/q22_vs_q21.md` must name it as the only new text and no number moves; (2) the pins: `tests/test_round18_x.py`, `tests/test_round18_a.py`, `tests/test_round19_b.py`, `tests/test_round19_m.py`, `tests/test_round17_a.py` pin the three starts with `startswith` ("Both ends ... 0.5 m or lower", "An end ... below 0.5 m", "An end ... of 0.5 m") and "just above 0.5 m", and some assert "no card above 0.55 m" or "the USV's 2.2 m whip with a UAS: no card" (the `_low_antenna_note` docstring says so): move those assertions deliberately, keep the starts, add a start for 0.55 to 2.2 m; (3) `_low_antenna_note`'s `None` return is read by `_links` and `credibility.json`; a link that now has a note counts in whatever counts cards (read: `grep low_antenna cafe/pm/*.py`); (4) the RUNBOOK rows about the card and DECISIONS 1000 ("an end of 0.55 to 2.2 m prints no card") are amended (documents batch); (5) report.json adds no key (the note is a string already stored).
owner decision: OD-2.
sources: C-2, A-1

### M-3. RUNBOOK says to read a GO of a partly-needed link as a GO on the members that needed it; it is not one, and the card's two sentences about members that never needed a link contradict each other in the all-members case   (sources: C-1, C-3)
severity: minor / status: confirmed / lane: documentation, statistics, honesty
wrong data: yes (C-1: a document a user acts on; the stop rule counts it): docs/RUNBOOK.md:188 says that members that never needed a link have pass fraction 1.0 and count as passes "so read a GO of such a link as a GO on the members that needed it". The first half is true. The conclusion is not: with n = 64, 40 never needed it and 3 of the other 24 failed, the printed verdict is `intervals.verdict(3, 64)` = GO (P(fail) 0.047), while the members that needed the link are 3 of 24: MARGINAL (0.125). The card prints only "counts as a pass in the P(fail) above" and no page prints the figure on the needed members, so the RUNBOOK sentence is the one place that says what to read, and it says the wrong thing. Not seen in q21 (`n_never_required` is 0 for all four links). C-3 half: wrong data no (two contradictory sentences on one card, the verdict right).
where: docs/RUNBOOK.md:188 (last clause of the NOT EXERCISED bullet); cafe/pm/stage1.py:948 (`v = intervals.verdict(int(f.sum()), n)` over all n members: correct as designed, and DECISIONS 997's reason); cafe/pm/report.py:1679-1686 (`_never_required_html`: "counts as a pass in the P(fail) above") and :1695-1700 (`_granularity_samples_html` `tail`: "the P(fail) above counts nothing" for the NOT EXERCISED verdict); tests/test_round19_m.py:106-117 (pins both sentences together)
claim: C-1 as above; C-3: for a link every member never needed (`n_never_required` = n, verdict NOT EXERCISED) the card prints "... counts as a pass in the P(fail) above" and two lines later "the P(fail) above counts nothing; the verdict is NOT EXERCISED, not GO".
check: ran on orca (`c1.py`, `intervals.verdict`): (3, 64) GO 0.047; (3, 24) MARGINAL 0.125; (6, 64) GO 0.094; (6, 24) MARGINAL 0.25; (0, 64) and (0, 24) both GO; (1, 64) and (1, 24) both GO. So the verdict of the whole set can be better than the verdict of the members that needed it, by a whole class, exactly as C says. By reading: stage 1 gives a never-required member `success` True, so every failure is among the members that needed the link, which makes "K of the M that needed it failed" exactly computable from `k_fail`, `n` and `n_never_required`. C-3 by reading lines 1679-1700 and the pin.
root cause: round 19's M-1 added the count so that "never required" does not read as "worked", and wrote the sentence that tells the user how to read it without computing the verdict it recommends.
fix (OD-3): (a) RUNBOOK 188 says "a GO of such a link is diluted: the members that never needed it pass by default, so the evidence is the members that needed it, and the card says how many of those failed; read that figure, not the GO alone"; (b) the card sentence of `_never_required_html` ends "... counts as a pass in the P(fail) above; K of the M members that needed the link failed" for a link some members needed (`needed` = members - never_required, one new key `granularity.needed` in report.json, so the number is traceable), and says "the verdict is NOT EXERCISED: no member needed the link" without "counts as a pass in the P(fail) above" when `needed` is 0 (C-3: the first sentence is written for the partly-needed link only). The card prints no second verdict and no second interval (two verdicts on one card would be the next finding). What it could break (foresight): `tests/test_round19_m.py:106-117` pins both sentences (move the first for the all-members case, keep the second); the 56 `report.json` leaves of round 19 become 60 (one new key for each of the four links; the q22 leaf count and `review/round_20/q22_vs_q21.md` must say so); `credibility.check_traceability` and `check_rendered` must find the new number in report.json (a test); the HTML of a link with `never_required` 0 is unchanged (the sentence is not printed), so q22's page is byte-equal apart from the new leaves; DECISIONS 997 is amended.
owner decision: OD-3.
sources: C-1, C-3

---

## Minor, wrong data: no (M-4 to M-13)

### M-4. `n_never_required` is not validated like the other counts of a summary: a damaged or edited value prints a false warning with a green traceability check, and NaN fails `report --run`   (sources: C-4)
severity: minor / status: confirmed by reading (the runs are the reviewer's) / lane: robustness
wrong data: no (needs a damaged or hand-edited `summary.json`; stage 1 writes `int(np.sum(need_count == 0))`).
where: cafe/pm/report.py:844-849 (`_granularity`: `never_required=num(never, ...)`, no check), :1679-1686; cafe/pm/credibility.py:815-833 (`check_summary` / `check_counts` cover `k_fail` and `n` only)
check: read the lines; C's runs (70 of 48, -1, 1.5, True, "x", 1e30 print a sentence and pass both checks; NaN fails `report --run`) taken from the reviewer.
fix: `check_counts` covers `n_never_required` (a whole number, 0 <= x <= n, not a bool) with the same message as `k_fail` ("is not a count ... the summary was edited or is damaged"). Tests: 70 of 48, -1, 1.5, True, "x", NaN (fail before: green or a late failure). Foresight: M-3 adds `needed` computed from it, so the check must run before; `credibility.py` and `report.py` are both batch B's.
sources: C-4

### M-5. `plan.json` has no upper bound on `batch` and `n_max`, and its `budget` is not checked: 10**30 is an OverflowError or an unbounded what-if, a list is a TypeError, null runs with no plan, an int is blamed on `--budget`   (sources: D-1, D-2)
severity: minor / status: confirmed by reading (the runs are the reviewer's) / lane: robustness
wrong data: no (the null-budget case printed no answer in D's run; the others end in a traceback or a refusal).
where: cafe/pm/__main__.py:312 (`_plan_sizes`: only lower bounds), :328-330 (`bud = run_plan["budget"]` before `_plan_sizes`, unchecked), :342 (`pipeline.Context(a.mission, bud, ...)`), :345 (`ctx.plan.update`)
check: read the lines: `_plan_sizes` tests `type is int` and the three lower bounds and nothing above; `bud` is taken before it and passed on. D's runs not repeated.
fix (OD-5): in the same function, `batch` and `n_max` at most 10**6 (more than any budget in `budget.py` by orders of magnitude, so no real plan is refused; read the table to name the largest) and `budget` a `str` that is a budget name, with the same "damaged or incomplete" message, exit 2. Tests: batch 10**30, n_max 10**30, budget `["quick"]`, `None`, `5` (fail before: OverflowError, a started what-if, TypeError, a started what-if, a misleading `--budget` error). Foresight: `tests/test_round19_c.py` and `tests/test_whatif.py` pin the message text and the real q21 plan (batch 32, n_min 32, n_max 64) must still pass; keep the existing words so those pins stay.
sources: D-1, D-2

### M-6. The what-if command prints no sign of the null-change floor: a 36 s shift moves P(fail) by two members, and the answer line reads as a change   (sources: C-5)
severity: minor / status: confirmed by reading (the runs are the reviewer's) / lane: statistics, honesty
wrong data: no, borderline: every printed number is the rerun's own and the printed Wilson interval contains the base value, but a user reading "0.234 -> 0.172" for a 6 h shift has nothing on the line that says 0.234 -> 0.203 is what a 36 s shift gives. The lead may count it if the owner thinks "reads as an improvement to act on" is misleading; I do not (the interval is on the line, and the report's fix table carries the flag).
where: cafe/pm/__main__.py:380 (the answer line prints the candidate's interval only); cafe/pm/report.py:420 (`same_as_baseline`) and its text `SAME_AS_BASELINE` (:1472, :1498), which the command line lacks; docs/RUNBOOK.md:175
check: read the lines; C's runs (36 s shift 0.234 -> 0.203, 13 of 64 against 15; the USV 0.906 -> 0.875) from the reviewer.
fix (OD-4): the command line appends the same words the report's fix table uses when the candidate's interval holds the base P(fail) ("not distinguishable from the baseline"), using the interval it already prints; one sentence in RUNBOOK 175 says a change of one to three members is inside the noise of a what-if. No new statistic. Foresight: import `report.SAME_AS_BASELINE` (read only: report.py is batch B's) or repeat the words with a test that they are equal; `tests/test_whatif.py` and `tests/test_round18_a.py` pin the printed line for a candidate that differs: the appended words must not appear when the interval excludes the base.
sources: C-5

### M-7. `python -m cafe._seed`: a deeply nested JSON is a RecursionError traceback, and a result with one direction of six passes the shape check   (sources: D-3, D-4)
severity: minor / status: confirmed by reading (the runs are the reviewer's) / lane: robustness, data
wrong data: no (an operator-supplied file; D-4 needs a truncated or hand-edited one).
where: cafe/_seed.py:79-84 (`except (OSError, ValueError)`: a RecursionError is neither), :48-53 (`_checked` accepts any non-empty subset of the six directions and no `gci`); read by cafe/vehicle.py:284-300, :389 (`sources["drag"] = "cfd"` set for one direction in six) and cafe/_site_data.py:186 (`v["gci"]`, KeyError without it)
check: read the lines; D's runs from the reviewer.
fix: `RecursionError` is caught with the same "NOT seeded <file> - <reason>" path; an external result must hold all six directions (the keys `vehicle.py` reads) and each with `gci`, else "NOT seeded". Tests: `[` x 100000, a result with `+x` only, one without `gci` (fail before: a traceback, "seeded"). Foresight: the real files have six directions (check against `tests/fixtures/cfd_real` if present) and `tests/test_round19_d.py`'s stand-in result and `tests/test_round17_e.py`, `tests/test_round18_d.py`'s stand-ins gained the fields in round 19: give them all six directions if they have fewer; plus the A-4 test SEb (M-10) in the same file.
sources: D-3, D-4

### M-8. `hycom.leftover_note` offers the `mv` of the first leftover by random name, not the newest, and a half-deleted `.dead.tmp` is reported by nothing   (sources: D-5, D-6)
severity: minor / status: confirmed by reading (the runs are the reviewer's) / lane: operations
wrong data: no (the advice names a file to restore and does not say which generation it is; D-6 leaves a 20 GB directory nobody finds on a disk that is 97 % full).
where: cafe/pm/env/hycom.py:329-343 (`left[0]`; `_leftovers` sorts by a random uuid), :247-250 (`dead`, called only at :321), cafe/pm/__main__.py:263 (`ingest-ocean` reports `asides` only; this hunk is batch C's), docs/RUNBOOK.md:298
check: read the lines; D's probes from the reviewer.
fix (OD-6): `leftover_note` offers the newest aside by mtime (and names the others as older) and states its date; `ingest-ocean` (batch C's file, hunk named here) and `pipeline._need` add "a half-deleted `.dead.tmp` is beside the store (N GB): safe to delete" using `hycom.dead` (public already). Tests: two asides with swapped names offer the same newest one; a store beside a `.dead.tmp` prints the line (fail before: the older one, nothing). Foresight: `tests/test_round18_e.py` and `tests/test_round19_e.py` pin the `mv` text and "puts it back"; keep those words; the RUNBOOK row 298 is edited in the documents batch.
sources: D-5, D-6

### M-9. `intervals.coverage` and `verdict` still take narrow numpy counts unchanged (round 19's M-8 fixed five other functions); `verdict` returns the caller's numpy scalars, huge ints are an OverflowError, `sprt_decide`'s alpha and beta are unchecked   (sources: A-3, D-7)
severity: minor / status: confirmed by reading (the runs are the reviewers', two of them the same) / lane: numerics
wrong data: no (no caller in `cafe/pm` passes a numpy integer: `stage1.summarize` passes `int(f.sum())`).
where: cafe/pm/stats/intervals.py:200-205 (`coverage`: `np.arange(n + 1)` wraps for `np.uint8(255)`), :164-184 (`verdict` stores `n=n, k_fail=k_fail` as given), :88-95 (`wilson` with a Python int above 1e308); cafe/pm/stats/sequential.py:34-38 (`alpha` 0, -1 and `beta` 1)
check: read the lines; A's and D's runs agree.
fix: `coverage` and `verdict` take their counts through `_count` (the helper round 19 added) and store the Python ints; `wilson` and friends raise `ValueError` for a count too large for a float; `sprt_decide` checks `0 < alpha < 1`, `0 < beta < 1` with the module's ValueError. Tests: `np.uint8(255)`, `np.int8(127)`, `json.dumps(verdict(np.uint8(3), np.uint8(100)))`, `wilson(1, 10**400)`, `sprt_decide(.., alpha=0)` (fail before as the reviewers show). Foresight: coverage 100 % on `stats` (every new branch needs its test); `tests/test_round18_m.py`'s `_count` double must keep returning what it returns; the `verdict` dict must be JSON-equal to today's for Python ints (a test), so no report number moves.
sources: A-3, D-7

### M-10. Test gaps behind four round-19 claims that surviving mutants name (S1e, S1g, SEb, RPi)   (sources: A-4)
severity: minor / status: confirmed by reading (the mutants are the reviewer's; not re-run) / lane: tests
wrong data: no.
where and what must fail (one test each, fail before on the mutant, pass after; each in the batch that owns the file):
- S1e (stage1.py:713-716, batch A): the two UAS ends' sortie grids are unioned: a test with two UAS whose 30 s grids are out of phase (first end's grid alone gives a different `t`); S1g (stage1.py:958, batch A): `n_never_required` counts `need_count == 0` and not `<= 1`: a member required at exactly one moment is not "never required".
- SEb (_seed.py `_vec`, batch D): a `force`, `moment` or `viscous` of four numbers is refused.
- RPi (report.py:848, batch B): `never_required` is not kept when `n` is missing (equivalent for real runs; one test or a comment that says why; do not add code for it).
sources: A-4

### M-11. The comment and DECISIONS 999 explain the Slocum's current-column step by one discrete event (a surfacing less); the cycle has a second one of about the same size (an apogee)   (sources: B-2)
severity: minor / status: confirmed by reading and arithmetic (B's) / lane: documentation, honesty
wrong data: no (every measured step is of the surfacing size; the 1.62e-4 is right).
where: cafe/pm/stage1.py:62-72 (the comment on `ACTING`), DECISIONS 999; cafe/pm/physics/glider.py:490-492, :499 (the apogee charges `pump_energy_J(dV, p(dive_depth), eta)`, the surfacing `comm_J + pump_energy_J(dV, 0, eta)`)
check: the arithmetic: 138e-6 x (101325 + 505e4) / 0.4 = 1776.6 J = 1.645e-4 of 1.08e7 J against the surfacing's 1.6148e-4; both are in the code lines above. Not re-run (B's toy).
fix: the comment names both events and their sizes (about 1.6e-4 and 1.65e-4, and 3.3e-4 when both cross), and says the per-member ocean displacement also moves which side of a step a member lands on, a second reason the two current columns' index in that row carries no information (B's check 4). A comment edit only (no code); DECISIONS 999 amended in the documents batch. Foresight: a comment inside a keyed function does not move any CFD key (`stage1.py` is not keyed); a doc test that pins the comment's text, if any, is read first (`tests/test_round19_a.py` and `tests/test_round18_x.py` quote DECISIONS 999's numbers).
sources: B-2

### M-12. A battery-dominated USV run ranks the lowest state of charge when 59 of 64 members sit at the clip at 0, and the sentence does not say so   (sources: B-3)
severity: minor / status: confirmed by reading (B's run) / lane: statistics, honesty
wrong data: no: the ranking was the physically expected one (`solar_yield_scale` first) and no wrong ranking was demonstrated; the strength of the printed index is what is overstated.
where: cafe/pm/physics/usv.py:689-690 (`soc_wh` clipped at 0), cafe/pm/stage1.py:228, :831-837, :866-885 (`_ranked`, `_sensitivity`); the printed sentence is in cafe/pm/report.py (the "most sensitive to" line)
check: read; B's run (`battery_wh` 1005: 59 of 64 empty, S1 0.235 against floor 0.130) from the reviewer. The summary already stores `energy.n_empty`, so no stage-1 change is needed.
fix (OD-7): report.py only: when the ranked quantity is the state of charge and `n_empty` is above half the members, the line adds "(N of n members ended with an empty pack: their value is the same 0, so the index rests on the others and a tie)". No stage-1 change, no new key. Foresight: `tests/test_report.py`/`tests/test_round18_*` pin the "most sensitive to" sentence for non-censored runs: the added clause appears only above the threshold, so those pins stay; q22 is unchanged (the demo's USV is not battery-limited: `n_empty` 0 in q21).
sources: B-3

### M-13. DECISIONS row 112 still says the emulator table's read-modify-write 'is not locked'; it has been locked since row 313   (sources: A-2)
severity: minor / status: confirmed by reading / lane: documentation
wrong data: no.
where: DECISIONS.md:165 (row 112), DECISIONS.md:366 (row 313), cafe/pm/emulator.py:113, :182, cafe/pm/whatif.py:435
check: `grep -n '^| 112 ' DECISIONS.md` line carries no "amended by"; the code holds `locked(...)` at the two sites.
fix: row 112 gets "(amended by 313)" and its last sentence says the table is locked; a doc test in the existing DECISIONS-amendment test, if one exists, is read first. Documents batch.
sources: A-2

---

## Open decisions (the lead takes the defaults)

- OD-1 (M-1): the acoustic margin where Bellhop refines. Options: (a) run both directions and keep the lower margin per sample; (b) take the mean of the two; (c) a canonical order (shallower transducer first), one run, order-free but arbitrary. Default: (a): conservative and the same direction as `_link_hs`'s "worse of the two ends"; cost: twice the Bellhop runs for members that have an ambiguous sample. (c) is the cheap fallback if the CI link tests become too slow.
- OD-2 (M-2): the card above 0.55 m. Options: (a) the card speaks for every RF end up to 2.2 m with "not measured" and, for a 10 to 15 m partner, the measured envelope (too high by up to 5.1 dB, too low by up to 2.1 dB); (b) the same without the envelope figures; (c) keep the silence above 0.55 m and amend L23 and DECISIONS 1000 to say so (the 5 dB figure then lives only in L23). Default: (a). It prints a new card on the demo's USV-UAS link ("no band is stated"), which q22 must show as the only new text.
- OD-3 (M-3): how a user reads a link some members never needed. Options: (a) the card gives "K of the M members that needed it failed" (new key `granularity.needed`) and the RUNBOOK says to read that beside the GO; (b) reword the RUNBOOK and the card only, no number. Default: (a).
- OD-4 (M-6): the what-if command's null-change floor. Options: (a) the report's "not distinguishable from the baseline" words when the interval holds the base P(fail); (b) leave as is. Default: (a).
- OD-5 (M-5): the bounds on `plan.json`. Options: (a) `batch` and `n_max` at most 10**6 and `budget` a known budget name; (b) bounds taken from the budget table's largest. Default: (a).
- OD-6 (M-8): which leftover aside `mv` is offered, and the `.dead.tmp`. Options: (a) the newest by mtime, the rest named as older, and a `.dead.tmp` named with its size as safe to delete; (b) RUNBOOK words only. Default: (a).
- OD-7 (M-12): the censored state of charge. Options: (a) the clause on the line when more than half the members are at the clip; (b) leave and say it in the RUNBOOK. Default: (a).
- Not owner decisions, stated so they are not asked: M-4 (`check_counts` covers the count), M-7 (RecursionError and the six directions), M-9 (`_count` in `coverage` and `verdict`, alpha and beta checks), M-10 (tests), M-11 (a comment), M-13 (a document).

---

## Batches

Code batches A to F have disjoint source and test file lists and can run in parallel in separate worktrees; batch G (documents) runs last. Each batch adds its tests in its own new file `tests/test_round20_<letter>.py`; where an existing test file must change (a pinned sentence or a count), it is named in the batch that holds the production code. Gates as CLAUDE.md: ruff, mypy strict, coverage 100 % on physics/stats/env, one regression test per fix that fails before and passes after, no banned tokens, nothing run on the laptop.

### Batch A: stage 1 links
- findings: M-1, M-11 (the comment), and the S1e and S1g tests of M-10
- files: cafe/pm/stage1.py, tests/test_stage1.py, tests/test_round17_a.py, tests/test_round17_m.py, tests/test_round18_a.py (only the lines that call `_bellhop_member` or count `acoustic_link` calls; if a pin there sits in a card test, leave it to batch B), tests/test_round20_a.py (new); cafe/pm/physics/comms.py read only
- must fail before: M-1: a link `a, b` against `b, a` through a fake `comms.acoustic_link` that gives different margins for (tx 5, rx 1) and (1, 5): equal `margin_db`, `frac`, `success`, and `margin == min` of the two; the label says "the lower of the two directions". S1e: two out-of-phase UAS grids; S1g: a member required at one moment is not `n_never_required`.
- notes: the demo's numbers must not move (q21's acoustic links are out of range); the Bellhop runs double (state it in DECISIONS); the comment of `ACTING` names the apogee event and the per-member displacement.

### Batch B: card, never-required, summary check, censored SoC
- findings: M-2, M-3, M-4, M-12, and the RPi test of M-10
- files: cafe/pm/report.py, cafe/pm/credibility.py, tests/test_report.py, tests/test_credibility.py, tests/test_round18_x.py, tests/test_round18_a.py (only the card pins and the old-`flip.json` pair; if batch A also needs a line of this file it is named there as a different hunk), tests/test_round19_b.py, tests/test_round19_m.py, tests/test_round20_b.py (new); cafe/pm/stage1.py (`ship_antenna_m`), cafe/pm/physics/comms.py read only
- must fail before: M-2: an end of 0.6, 1.0 and 2.2 m with a 15 m and a 10 m partner prints a card with "not among those measured" and the envelope (before: None); the USV's whip with a 15 m mast prints the row (before: None); (0.55, 15) and (0.3, 0.55) print the nearest-pair sentence (before: not); the envelope constants equal `band` over the 0.05 m grid to 0.1 dB; L23's text says what the card does. M-3: a link some members never needed prints "K of the M members that needed it failed" with `granularity.needed` in report.json and found by `check_traceability`; the all-members case prints no "counts as a pass in the P(fail) above". M-4: `check_counts` refuses 70 of 48, -1, 1.5, True, "x", NaN. M-12: the clause appears at 59 of 64 and not at 5 of 64.
- notes: keep the three pinned starts and "just above 0.5 m"; `report.json` gains one key (`needed`) and no other; `credibility.json` carries L23's new text (regenerated, not hand-edited); q22 against q21: one new text (the USV-UAS card), no number moved.

### Batch C: command line (what-if and ingest)
- findings: M-5, M-6, and the `ingest-ocean` hunk of M-8
- files: cafe/pm/__main__.py, tests/test_whatif.py, tests/test_round19_c.py (pins of the plan-size message), tests/test_round20_c.py (new); cafe/pm/report.py (`SAME_AS_BASELINE`) and cafe/pm/env/hycom.py (`dead`) read only
- must fail before: M-5: `plan.json` with `batch` 10**30, `n_max` 10**30, `budget` `["quick"]`, `None`, `5` each give the "damaged or incomplete" message, exit 2 (before: OverflowError, a started what-if, TypeError, a started what-if, a wrong `--budget` blame). M-6: a candidate whose interval holds the base prints the "not distinguishable" words, and one whose interval excludes it does not. M-8 hunk: `ingest-ocean` beside a `.dead.tmp` prints the size line.
- notes: the existing words of the plan message stay (pins); the q21 plan (32, 32, 64, "quick" or the run's budget) still passes.

### Batch D: seed
- findings: M-7, and the SEb test of M-10
- files: cafe/_seed.py, tests/test_round19_d.py (the stand-in result), tests/test_round17_e.py and tests/test_round18_d.py (stand-ins, only if they hold fewer than six directions), tests/test_round20_d.py (new); cafe/vehicle.py and cafe/_site_data.py read only
- must fail before: M-7: a nested `[` x 100000 file, a result with `+x` only, a result without `gci`, a `force` of four numbers each give "NOT seeded <file> - <reason>", rc 1, nothing written (before: traceback, seeded).
- notes: check the six direction keys against the fixture or the real file before fixing the set.

### Batch E: hycom leftovers
- findings: M-8 (the `leftover_note` and `pipeline._need` part)
- files: cafe/pm/env/hycom.py, cafe/pm/pipeline.py (`_need`'s note only), tests/test_hycom.py, tests/test_round18_e.py, tests/test_round19_e.py, tests/test_round20_e.py (new); cafe/pm/__main__.py is batch C's
- must fail before: two asides with swapped names offer the same, newest, `mv`; `_need` names a `.dead.tmp` beside a present store with its size.
- notes: keep "puts it back" and the `mv` text; `asides` and `dead` signatures unchanged (batch C calls `dead`).

### Batch F: statistics
- findings: M-9
- files: cafe/pm/stats/intervals.py, cafe/pm/stats/sequential.py, tests/test_stats_exact.py, tests/test_round18_m.py (the `_count` double only), tests/test_round19_f.py, tests/test_round20_f.py (new)
- must fail before: `coverage(np.uint8(255), ...)` and `np.int8(127)` equal the Python-int answer; `json.dumps(verdict(np.uint8(3), np.uint8(100)))` works and equals the Python-int dict; `wilson(1, 10**400)` and `sprt_decide(.., alpha=0)` raise the module's `ValueError`.
- notes: coverage 100 % on `stats`; no number in report.json or summary.json moves.

### Batch G: documents (last)
- findings: the document edits handed over by every other batch, M-13, M-11 (DECISIONS 999)
- files: DECISIONS.md (new rows from 1017; amend 112, 996, 997, 999, 1000, 1004, 1006 where a row it names changes), CHANGELOG.md, docs/RUNBOOK.md (:188 for M-3; :175 for M-6; :298 for M-8; the card rows for M-2), docs/PHYSICS.md (12.1: the 0.55 to 2.2 m envelope; Bellhop's non-reciprocity for M-1), docs/CREDIBILITY.md (L23, regenerated from `credibility._l23_text()`: the text at :149 must equal it), QUESTIONS_FOR_LAB.md (17k onwards: one sub-item per owner decision with its default, OD-1 to OD-7), STATUS.md, HANDOFF.md, review/orca/PROBLEMS.md; review/round_20/q22_vs_q21.md (read; written by the lead)
- notes: runs last, edits no code; the stop-rule line in HANDOFF.md says round 20 is not clean (3 wrong-data findings, no critical or major), so the count of consecutive clean rounds stays at 0; the "not covered" list below goes into HANDOFF.

Coverage check: M-1 to M-13 each appear in exactly one batch as the owner of the production change (A: M-1, M-11 comment; B: M-2, M-3, M-4, M-12; C: M-5, M-6, M-8's `ingest-ocean` hunk; D: M-7; E: M-8's note; F: M-9; G: M-13, M-11's row), M-10 is split by file (S1e, S1g to A; SEb to D; RPi to B). Every source file is in one batch only (`stage1.py`: A; `report.py`, `credibility.py`: B; `__main__.py`: C; `_seed.py`: D; `hycom.py`, `pipeline.py`: E; `intervals.py`, `sequential.py`: F). Shared test files: `tests/test_round18_a.py` is touched by A (calls of `_bellhop_member`) and B (card pins) in different hunks: B owns the file, A hands B the one hunk if it is needed; `tests/test_round18_m.py` is F's only.

---

## Totals

- Findings: 13 merged from 19 source ids. By severity: 0 critical, 0 major, 13 minor.
- By status: confirmed 13, partly 0, not confirmed 0, refuted 0. Reproduced or recomputed here on orca: M-1 (function level, not through `run_batch`), M-2 (the unmeasured band and the 0.05 m grid; A-1's arithmetic on the laptop), M-3 (the verdict counts). By reading only (the reviewer's runs are their evidence): M-4 to M-13.
- Wrong data: yes (3): M-1 (minor: the printed margin of an acoustic link depends on the order of its ends, 0 to 17.8 dB wherever Bellhop refines; no verdict flip seen), M-2 (the card's silence above 0.55 m, margin too high by up to 5.1 dB, and L23's false sentence), M-3 (the RUNBOOK's reading of a GO of a partly-needed link). Wrong data: no (10): M-4 to M-13 (M-6 borderline, see its row).
- Reviewers' own ratings against this merge: B-1 yes (kept, conditional); C-1 yes (kept); C-2 yes (kept, and the 5.1 dB confirmed, plus 4.1 dB for the ship's default 10 m); A-1 no (kept, inside M-2); every other source id no (kept; C-5 borderline).

**Stop rule.** Round 20 is NOT clean: three findings give wrong data to act on (M-1, M-2, M-3), though none is critical or major. The count of consecutive clean rounds was 0 before this round and is 0 after it. The owner's stop rule needs two consecutive rounds with none.

## Not covered (by any reviewer or by this merge)

- This merge: an acoustic link through a real `run_batch` in both orders (the CI fixture's private environment was deleted; M-1 rests on `comms.acoustic_link` with a profile of my own and on B's run); a sign flip of an acoustic margin between orders (none found, none excluded); the unmeasured 0.55 to 2.2 m band beyond Hs 0, beyond 12 km and below 300 m, beyond the 10 and 15 m partners, and for two mid-height ends; any mutant; M-4 to M-13's reviewer runs; the page in a browser.
- Reviewer A: the survivors S1e, S1g and RPi against the whole of `tests/test_stage1.py` and `tests/test_report.py` (the file takes over 14 minutes); 50 DECISIONS rows read for what they say, about 20 traced to code.
- Reviewer B: a parabolic equation for any pair, the demo's gridded environment for DECISIONS 999's mechanism, interactions of two columns on the UAS profile share and the Slocum battery row, a real stage-1 flip, B-1 on the demo's environment.
- Reviewer C: a Stage-1 "becomes" line from a real flip, the no-acting-input line on a real run, a real glider-glider or two-UAS link through `run_batch`, the page in a browser, a 20-vehicle or 30-day mission, stage 3.
- Reviewer D: `write_store` on a real zarr and the delete time of a 20 GB store, two concurrent runs, a kill mid-append of the emulator table, the TAO download lock, a real Stage-1 what-if against a rerun, RUNBOOK troubleshooting rows other than 294 to 300 (a crude grep matched about half), a what-if with a valid plan to its end.
