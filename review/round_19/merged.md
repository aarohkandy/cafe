# Round 19 merged findings (BRIEF 5.6 step 2)

Inputs: reviewer_a.md (10 findings), reviewer_b.md (4), reviewer_c.md (4), reviewer_d.md (10) = 28 source ids. Merged to 16 findings, M-1 .. M-16; every source id appears in exactly one merged finding (B-1 is M-1; D-2, C-4, C-2 and A-5 form M-2; C-3 is M-3; C-1 is M-4; B-2 and B-3 form M-5; B-4 is M-6; A-1 and D-7 form M-7; D-1 is M-8; D-8 is M-9; D-6 is M-10; D-4 and D-5 form M-11; D-3 is M-12; D-9 is M-13; D-10 is M-14; A-10 is M-15; A-2, A-3, A-4, A-6, A-7, A-8 and A-9 form M-16).
Verified by this merge against HEAD 1511e36 (code of 7260ebb; later commits are documents): by reading the cited code, and on cafe-orca (proot, 2 CPUs, detached worktree `../cafe-ver19`, private `pm_ver19`, all removed at the end) by five scripts: `p1.py` (a real `stage1.evaluate_link` on a two-glider scene, both orders, RF and Iridium), `p2.py` (a real `stage1.run_batch` of the CI mission's USV and UAS with their RF link on `AnalyticEnv`, one column moved at a time, plus a bisection of the profile-share edge), `p3.py` (`wilson`, `sprt_decide`, `cfd._literals`, `whatif._numbers`, `store_lock` under four spellings, `report._low_antenna_note` with patched heights), `p4.py` (the fix line of a round-17-style `flip.json` through the real `report.write`) and `p5.py` (my own flat-earth Fresnel two-ray with the Ament factor against `comms.two_ray_loss_db` at Hs 0 to 3 m). The "check" line of each finding says which was done.

**ROUND 19 IS NOT CLEAN under the owner's stop rule.** One finding is major (M-1, B-1: a glider-glider link `when: surfacing` is judged on the first-named glider only, so the verdict depends on the order of `a` and `b`), and four more give wrong data (M-2 to M-5), each minor and each conditional on a mission or a re-report that the demo does not make: the card's antenna-pair lookup (a height a rounding off a measured row prints "not measured", and a height just above 0.5 m prints nothing); the card's low-antenna figures stated without "Hs 0"; the fix line of a re-reported round-17 run; the "most sensitive to" line and noise floor of a link with a UAS end. None changes a q20 number (the demo has no two-glider link, no low-antenna RF link and no Stage-1 flip). The count of consecutive clean rounds stays at 0.

Severity: 0 critical, 1 major, 15 minor. Status: 14 confirmed (M-1 to M-10 and M-12 to M-15), 2 partly (M-11, M-16), 0 not confirmed; the Totals section says which were reproduced here and which are by reading. The full "not covered" list is at the end.

INCIDENTS and side effects of this merge: one scratch worktree `../cafe-ver19` (detached, removed with `git worktree remove --force`), one orca directory `~/cafe-worker/cafe/pm_ver19` (removed by that exact name), the job marker `~/cafe-worker/cafe/.pmx.job.pm_ver19` and my five scripts `p1.py` to `p5.py` in `~/cafe-worker/cafe/pmdata/` (all removed by exact name). Nothing in `/tmp` on orca; one accident on the laptop: I copied my probe scripts to `/tmp` on the laptop and removed them at once (`rm -f /tmp/p?.py`). My probes wrote a scratch directory `ver19_lockdir` and `ver19_tmp` inside `pm_ver19` only (gone with it). No shared store, no `cafe/data`, no `pmdata/cache`, no demo, gate, suite or CFD run, no Azure resource, no stash, no push, no commit. A mutant driver (`mut.py`, four of reviewer A's survivors: PE11, Q3, FH8, W3b, with a control) was started on orca after the probes and produced no output: the connection to orca timed out for several minutes while it ran; I killed the driver and its `bin/pmx.sh` child by exact pid (59677, 59678), confirmed on orca that no process of mine remained, and the worktree was clean. So no mutant was re-run here: every "surviving mutant" claim in M-16 and A-5 is the reviewer's, supported only by reading (and by a grep showing no test names the three heights of M-2). `ssh cafe-orca` timed out a few times at the end and answered on retry.

---

## Critical

None.

---

## Major, wrong data: yes (M-1)

### M-1. A glider-glider RF, acoustic or Iridium link `when: surfacing` follows only the glider named first: the other glider is judged as if on the surface, and the verdict depends on the order of `a` and `b`   (sources: B-1)
severity: major / status: confirmed / lane: physics, statistics (stage 1 links)
wrong data: yes. Output: the verdict, pass fraction, required-moment count, margin and distance of any link with two glider ends and `when: surfacing`, which `config.py` accepts (and `docs/PHYSICS.md` 12.1 and CREDIBILITY L23 invite: "two gliders, whose RF link the loader accepts"). Not in the demo (its links have one glider end at most), so no q20 number moves.
where: cafe/pm/stage1.py:658-661 (`_surfaced`: `g = a if out.get(a, {}).get("class") == "glider" else b`: one glider only), :705 (RF and acoustic: `need = _surfaced(out, a, b, t)`), :696 (Iridium: the same call), :588-589 and :597 (`_pos` adds `antenna_m` to the height whatever the depth of the glider, so a submerged glider's antenna is 0.3 or 0.5 m above the sea); cafe/pm/config.py:488-499 (the loader's `when` checks ask for "a glider at one end", not at most one); the docstring of `evaluate_link` ("follows the glider end ... whichever way round the link names them": true for one glider end only)
claim: B: the same two vehicles, radio and `required_fraction`, 4 of 4 members pass in one order and 4 of 4 fail in the other (need_count [2,2,2,2] against [6,6,7,5]); the second-named glider's margin is a finite number while it is under water.
check: ran on orca (`p1.py`, a real `evaluate_link` on a synthetic scene: g1 on the surface at every record with a 0.5 m antenna, g2 never surfaced at 100 m depth with 0.3 m, 2 km apart, 3 members, `flat_env`, the real code path, no fakes in the link): RF `a=g1, b=g2`: need_count [217, 217, 217], frac 1.0, success all True, margin finite at 651 samples (g2, at depth, is given a link budget); `a=g2, b=g1`: need_count [0, 0, 0], frac 1.0 (no moment required: a vacuous pass), success all True, margin finite at 0. Iridium `when: surfacing`: the same, 217 against 0. So the required moments are those of the first-named glider alone, in both kinds. Also confirmed by reading: the one-glider cases (a Seaglider with a USV, a glider with the ship, the shore) are right.
root cause: `_surfaced` was written for one glider end per link (the loader's check says "a glider at one end") and a second glider end was never excluded or handled. Note a second defect the probe shows: a link with no required moment has `frac` 1.0 and `success` True, so "never required" prints as "worked".
fix: required moments = EVERY glider end surfaced (an AND over both, for RF, acoustic and Iridium alike, as the docstring's rule is for an antenna that works at the surface only), and a submerged glider's height is not its antenna's (it is out of the link while submerged, as `need` already says). For an acoustic link the docstring has always said "the glider end surfaced"; keep that rule for both ends and say so in the docstring. Also in the same function: a link whose `need_count` is 0 for a member reports `frac` NaN-free as now but `success` stays True; add `need_count` 0 to the existing granularity note so a page can say "never required in n members" (OD-1). Foresight: `_surfaced`'s sibling, `uas_airborne`, picks `u = a if class == uas else b` the same way (two UAS ends are refused by the loader's "UAS at one end"? it asks for one, not at most one: apply the same AND for two UAS ends, a test); the loader's `when` messages (`config.py:495-499`) are unchanged by this default; `link_acts` (`stage1.py:93-99`) already unions both ends. Sibling sites: `_pos`'s `antenna_m` for a UAS end on the deck (zero height, not this).
owner decision: OD-1.
sources: B-1

---

## Minor, wrong data: yes (M-2 to M-5)

### M-2. The link card's antenna-pair lookup is an exact float match behind a step trigger: 0.5000001 m prints nothing, 0.30000000000000004 m prints "not among those measured", a ship without a height prints "no single height" when stage 1 used 10 m, and three of its edges are untested   (sources: D-2, C-4, C-2, A-5)
severity: minor / status: confirmed / lane: honesty, documentation, tests
wrong data: yes, conditional (D-2): once the lab enters a CAD height for a placeholder (the Seaglider's 0.51 m, the whip's 2.25 m, which both platform files say will happen), the card of an RF link whose margin is biased by about 2 dB falls from a stated "+1.8 to +2.7 dB" to silence (above 0.5 m) or to "not measured" (below it), though the antenna and its error are the same to a fraction of a decibel. The step at 0.5 m is the schema's (DECISIONS 944), the exact match is 991's, and together they make a cliff. C-2, C-4 and A-5 are wrong descriptions, not wrong answers (the "not measured" conclusion stands). q20: no card prints (the demo's RF link has no low end).
where: cafe/pm/report.py:762 (`h <= RF_LOW_ANTENNA_M` trigger), :776-778 (`pair = (known[0], known[1])`, `pair not in comms.LOW_ANTENNA_PAIR_BAND`: exact), :758-761 (`named` prints `:g`, six digits; a missing `ship.antenna_height_m` is a KeyError caught by `_end_antenna_m`, which returns None and the card says "no single height"), :739; cafe/pm/stage1.py:351-354 (`ship_antenna_m`: the mission's height, else the UAS radio's 10 m, else 10 m: what the link model really used); cafe/pm/credibility.py:62 (`LOW_ANTENNA_NAMES`: 0.3 "the Slocum", 0.5 "the Seaglider")
claim: D: 0.5000001 gives None; 0.30000000000000004 with 15 m gives "not among those measured". C: the same, and "ship (no single height)" for a mission without `ship.antenna_height_m`, where stage 1 used 10 m. A: the mutants PE11 (the two names swapped, every figure right), Q3 (`round(known[0], 1)`, which would turn the float dust into the 0.3 row against row 991's "exactly a row's heights") and Q5 (a ship with no height read as 15) survive the tests.
check: ran on orca (`p3.py`, `_low_antenna_note` with `glider.load_platform` patched, the ship at 15 m): 0.5 prints the band ("by up to 2.2 dB (the margin too low) and understated by up to 2.9 dB"); 0.5000001 prints None; 0.30000000000000004 prints "An end ... below 0.5 m: g (0.3 m) ... this pair (g (0.3 m), ship (15 m)) is not among those measured"; 0.4999999 prints "below 0.5 m: g (0.5 m)" and "not among those measured" (the sentence names a pair, 0.5 m with 15 m, that the table has, and calls it not measured); 0.3 prints the 0.3 row. C-2: a ship without a height prints "ship (no single height)" for `g` 0.5 m; `stage1.ship_antenna_m` of such a mission is 10 m (read). A-5's three mutants: not re-run (the mutant driver died, see the top); `grep` of `tests/` for 0.30000000000000004, 0.5000001 and 0.4999999 finds nothing, which is consistent with Q3 surviving.
root cause: the card's rule is a step in the height and an equality in the pair, so a rounding or a refinement of a placeholder changes the card from a statement to a silence; and the card has its own idea of the ship's height.
fix: (a) the card calls `stage1.ship_antenna_m` (the fallback the model used) and prints that height; (b) the match to a row and the trigger use a tolerance (OD-2); (c) a height off a row prints the actual height and the nearest row's figures only where the tolerance holds, otherwise "not among those measured" with both heights printed to the digits that differ (`{:g}` on a 0.30000000000000004 prints 0.3: use `:.4g` or `repr`-free `round(h, 4)` and say it); (d) tests for A-5's three mutants (PE11: the names are asserted against the table's heights; Q3: 0.30000000000000004 and 0.5000001 are asserted to be what OD-2 decides; Q5: a ship with no height is asserted to read 10 m, not 15). Foresight: L23's own text (`credibility._l23_text`) is generated from the same table and keeps its names; `tests/test_round18_x.py` and `tests/test_round18_a.py` pin the card's start words (`startswith`): keep "An end of this RF link has an antenna below 0.5 m:" and the other two starts.
owner decision: OD-2.
sources: D-2, C-4, C-2, A-5

### M-3. The card's low-antenna figures leave out "Hs 0": at a real sea state the stated minimum is too large for the 0.1 m pair and for 0.5 m with 15 m   (sources: C-3)
severity: minor / status: confirmed / lane: physics, honesty
wrong data: yes, conditional: the card prints the table (measured at Hs 0, flat earth, 915 MHz) as "its loss minus the Fresnel loss is +11.4 to +16.0 dB ... the margin is too low by that much", with no sea state; L23 and the docstring do say "Hs 0". The demo's sea is a metre or two. A link of a Seaglider (0.5 m) with the ship (15 m), a shipped pair, prints "understated by up to 2.9 dB (the margin too high)" where at Hs 2 m the figure is 0.3 dB; the 0.1 m pair's minimum is overstated by 5 dB at Hs 2 m. q20: no card prints.
where: cafe/pm/report.py:782-785 (the sentence); cafe/pm/credibility.py:56-71 (L23 says "Hs 0"); cafe/pm/physics/comms.py:162-168 ("Not run: ... Hs above 0")
claim: C's own Fresnel two-ray with the same Ament factor: 0.1 m with 15 m Hs 0 +11.4 / +15.1 / +16.0, Hs 2 +6.1 / +15.2 / +15.9; 0.5 m with 15 m Hs 0 -2.9 / +1.3 / +2.2, Hs 2 -0.3 / +1.5 / +2.4; 0.3 m with 15 m Hs 2 +2.5 / +5.2 / +6.1.
check: ran on orca (`p5.py`, my own flat-earth Fresnel, eps 72.8 - j118.9, vertical polarisation, the model's `ament_rho` formula applied to the reflection coefficient, 400 points from 300 m to the pair's horizon or 12 km, `two_ray_loss_db` minus mine): all twelve rows equal C's to 0.1 dB: 0.1/15 Hs 0: 11.4 / 15.1 / 16.0, Hs 1: 10.9 / 15.2 / 16.0, Hs 2: 6.1 / 15.2 / 15.9, Hs 3: 2.7 / 15.2 / 15.6; 0.5/15 Hs 0: -2.9 / 1.3 / 2.2, Hs 1: -2.0 / 1.3 / 2.3, Hs 2: -0.3 / 1.5 / 2.4, Hs 3: 0.3 / 1.9 / 2.5; 0.3/15 Hs 0: 1.2 / 5.1 / 6.0, Hs 1: 2.0 / 5.2 / 6.1, Hs 2: 2.5 / 5.2 / 6.1, Hs 3: 1.5 / 5.5 / 6.2. The Hs 0 rows are the shipped table. No pair's direction word changes between Hs 0 and 3 except that 0.5/15 loses its "too high" side from Hs 2 (min -0.3).
root cause: the card sentence omits the condition under which its numbers were measured; the table is a measurement at one sea state.
fix: the card says "at Hs 0" beside the figures and "at a sea state of 2 m the minimum is nearer 0 (L23)" (OD-3); L23 and PHYSICS 12.1 carry the Hs 1, 2 and 3 m figures above (documents batch). No number of the table changes (`LOW_ANTENNA_PAIR_BAND` stays an Hs 0 table, `test_round18_x.py` recomputes it to 0.1 dB). Foresight: a test that the card sentence contains "Hs 0"; L23's text is generated and already has it.
owner decision: OD-3.
sources: C-3

### M-4. A round-17 `flip.json` re-reported by the current code prints the Stage-1 P(fail) of the same members beside the verdict of the whole run (round 18 M-1's pair, left on older files)   (sources: C-1)
severity: minor / status: confirmed / lane: honesty
wrong data: yes, for a re-report (`report --run`) of a run made by round 17 code or between DECISIONS 917 and 952: "What would fix it (GO or MARGINAL): deploy 6 h later: P(fail) 0.375 on the same 32 members becomes 0 (...), NO-GO to GO", where 0.375 is the MARGINAL baseline of those 32 members, and the target stays the whole run's "GO or MARGINAL", so a row that stays MARGINAL on its members would be printed as a fix. Not for runs made by the current code (their `flip.json` has `target_same`), and not q20 (it has it).
where: cafe/pm/report.py:1456-1462 (`before` switches to `sm['p_fail']` whenever `same_members` exists; `was` switches to the same-members verdict only when `f.get("target_same") is not None`); DECISIONS 952 ("`target_same` (None for an older `flip.json`, which renders as before)"); tests/test_round18_a.py:168-172 (pins the old rendering)
claim: C: a synthetic round-17 entry renders the pair above.
check: ran on orca (`p4.py`, `tests.test_round18_a.flip_report` with `base_same` MARGINAL 0.375 of 32, whole run NO-GO 0.45 of 64, no `target_same`): the page text reads "What would fix it (GO or MARGINAL): deploy 6 h later: P(fail) 0.375 on the same 32 members becomes 0 (0 to 0.14, Wilson interval (Stage 1)), NO-GO to GO (Stage 1, n = 16 members)", followed by "The Stage-1 rows are compared with the unchanged mission on their own members: MARGINAL P(fail) 0.375 on 32 members. The whole run's P(fail) 0.45, of 64 members." The page contradicts itself two lines apart. Read: `tests/test_round18_a.py:168` pins this only for an old entry whose same-members verdict equals the whole run's (NO-GO and 0.125, the two agree), so the case that is wrong is the one that is untested.
root cause: round 18 M-1 chose to leave the older file "as before", which was right for P(fail) when no same-members baseline existed and is wrong when `base_same` exists without `target_same`.
fix: use `sm['verdict']` on the left whenever `sm['available']` (old file or new), with "(whole run: X)" when they differ, and say that the target is the whole run's when `target_same` is None, as C proposes (OD-4); the existing test of 168 keeps passing for its case (the verdicts agree); a new test for the disagreeing old entry. Foresight: `report.json` `target_same` stays None for the old file (the key is the schema's: unchanged); `_fix_html`'s line 1498 (`tgt`) already falls back to the whole run's target.
owner decision: OD-4.
sources: C-1

### M-5. `stage1.link_acts` omits `battery_capacity_scale` for a link with a UAS end, and the UAS profile-share row omits `wind_direction_bias` (the test and DECISIONS 992 call it inert)   (sources: B-2, B-3)
severity: minor / status: confirmed / lane: statistics (the acting columns of DECISIONS 958, 992)
wrong data: yes, conditional (B-2): the "most sensitive to" line and the noise floor of a link with a UAS end (the demo's `usv-uas-rf` is NO-GO by geometry, 88.8 % beyond the horizon, so no q20 line is affected) rank only the listed columns and a column that moves the link's required moments is excluded; for B-3 the effect is one bin of the battery scale and the UAS profile row ranking would rarely change (the claim "inert" is what is wrong): I count B-3 as no for its own half.
where: cafe/pm/stage1.py:88 (`TRACK_ACTS["uas"] = ("wind_speed_bias", "wind_direction_bias", "bulk_stress_scale")`), :93-99 (`link_acts`), :75 (`("uas", "profile_margin"): ("wind_speed_bias", *UNSEEN[...])`), :67 (`UNSEEN` does not list `wind_direction_bias`); tests/test_round18_c.py `test_r18_m4_every_column_that_moves_a_link_is_one_the_link_table_lists` (9 h window, two members, two quantiles); tests/test_round18_x.py:232-241
claim: B: with every column at its median, only `battery_capacity_scale` changed, the link's required moments are 39 / 42 / 44 / 45 / 48 / 48 at 0.70 / 0.75 / 0.78 / 0.80 / 0.85 / 1.00, and the column is in no `link_acts`; the profile share steps 0.625 to 0.875 at an edge of the battery scale, and `wind_direction_bias` moves that edge.
check: ran on orca (`p2.py`, a real `run_batch` of the CI mission's USV and UAS and the link `usv-uas-rf`, `AnalyticEnv(wind=(-6,2), current=(0.15,-0.1), hs=1)`, window 18 h from 03-01T18Z, two identical members, `X` set from the median of every prior). B-2: `link_acts` = bulk_stress_scale, current_direction_bias, current_speed_scale, hs_scale, tp_bias, usv_vpp_bias, wind_direction_bias, wind_speed_bias (no `battery_capacity_scale`); need_count at battery scale 0.70 / 0.75 / 0.80 / 0.85 / 1.00 = 39 / 42 / 45 / 48 / 48 and the UAS profile share 0.625 / 0.625 / 0.875 / 0.875 / 0.875: the column moves the denominator of the link's pass fraction by 19 % (the same figures as B's). B-3: the bisected edge of the profile share on the battery scale is 0.7824 (6 halvings of 0.75 to 0.80); at that edge, with only one column moved: `wind_direction_bias` at the 5 % quantile 0.75 and at 95 % 0.625, `wind_speed_bias` 0.875 and 0.375, `hs_scale` 0.625 and 0.625 (the median gives 0.625). So `wind_direction_bias` moves the profile share where the sortie is battery-limited, as B says, `hs_scale` does not.
root cause: the table was built from probes that stay far from the battery edge (the cause DECISIONS 992 gives for `UNSEEN`), and the links' table has no `UNSEEN` of its own.
fix: `TRACK_ACTS["uas"]` gains `battery_capacity_scale` (it moves the flight, hence the required moments); `UNSEEN[("uas", "profile_margin")]` gains `wind_direction_bias`, and the test name and the sentence of 992 stop saying "inert" (OD-5); the CI probe test of the links gets a window and quantiles at the battery limit (the 18 h window above). Foresight: more acting columns raise the permutation noise floor (B-4's figures: 0.155 for 2 columns, 0.186 for 4 at n = 64), so a UAS link's `nothing_above_floor` case is more likely and q20's UAS vehicle row floor (0.182, with S1 max 0.121) is not changed by M-5 if the added column is only in the link row and `UNSEEN` of the profile row (it is already there for the battery size): hand G the DECISIONS row (amends 958, 992) and a note that q21 re-evaluates the UAS link's floor; `credibility.py` counts "used by" from `ACTS`: a test that the split does not change those counts (as round 18 M-4 required).
owner decision: OD-5.
sources: B-2, B-3

---

## Minor, wrong data: no (M-6 to M-16)

### M-6. The step effect of the current columns on a drifting Slocum's battery margin has a mechanism that the code comment says nobody found: the last surfacing before the window ends   (sources: B-4)
severity: minor / status: confirmed by reading and by arithmetic, the toy run is the reviewer's / lane: physics, documentation
wrong data: no: the only output is a battery-failure sensitivity line of a drifting Slocum, which q20 does not print (glider_2n passes in every member); keeping or dropping the two columns changes no q20 number.
where: cafe/pm/stage1.py:58 ("no mechanism was identified"), :59-60 (the wind columns "float noise"), :68 (`DEMO_ONLY`); cafe/pm/physics/glider.py:459-470 and :494; DECISIONS 992
claim: B (a toy Slocum in an environment with a horizontal density gradient, current scaled 0 to 3 times): the step of 1747.2 J at current scale 1.5 is one surfacing less in the window (54 completed instead of 55): `comm_J` 3.5 W x (120 s + 250 s) + 414 J = 1709 J plus the surface pump 150.83 cc x 101325 Pa / 0.4 = 38.2 J; as a share of the usable pack 1.62e-4, the 1.6e-4 of DECISIONS 992; a count of surfacings at the window end, not a response of the battery to the current; the two columns raise the noise floor of a Slocum's battery row.
check: read the cited lines (the comment says no mechanism was identified); the arithmetic recomputed here: 3.5 x 370 = 1295, plus 414 = 1709; 150.83e-6 m3 x 101325 / 0.4 = 38.2 J; 1709 + 38.2 = 1747.2 J; 1747.2 / (1.2e7 x 0.9) = 1.618e-4. The toy run was not re-run (reviewer's).
root cause: the "no mechanism" note predates the explanation.
fix: the comment and DECISIONS 992 say the mechanism; whether the two columns stay (OD-6). Default: keep them (no q20 number moves; a column that can step a quantity belongs in its table), with the comment stating the mechanism and that the wind columns "can do the same with a smaller probability, the probe's 8 members cannot exclude it".
owner decision: OD-6.
sources: B-4

### M-7. `store_lock`'s re-entry test is by the spelling of the path, so a nested take of one lock under another spelling hangs for ever   (sources: A-1, D-7)
severity: minor / status: confirmed / lane: robustness
wrong data: no: a hang with no message; no present caller spells one path two ways (`fetch_gofs` builds `out_zarr` from the same `store.parent`).
where: cafe/pm/env/remote.py:233-236 (`path = pathlib.Path(cache) / name`; `held: set[Path]`; `if path in held`); `emulator.locked` (emulator.py:120-134) is not re-entrant at all (no caller nests)
claim: A: `d/"link"` (a symbolic link to `sub`) and `d/"sub"/".."/"sub"` block until an alarm; `d/"sub"/` and `d/"sub"/.` re-enter. D: the same with a symlinked cache directory (the ingest holds the ocean lock and `write_store` takes the same lock).
check: ran on orca (`p3.py`, under `signal.alarm(3)`): `d/sub` then `d/sub` True; `d/sub/.` True; `d/link` HANG; `d/sub/../sub` HANG. The second `flock` is on a new open file description of the same file, which waits for the first.
root cause: the key is the unresolved `Path`; flock's identity is the file.
fix: key the held set by the file's identity: open (as now, `O_NOFOLLOW`), `os.fstat(fd)`, and if `(st_dev, st_ino)` is in `held` close the new fd and yield True; add after the flock. Default (OD-7). Foresight: `held` becomes a set of `(dev, ino)`, the `held.discard` accordingly; `hycom.write_store`'s `held` use (it asks whether the lock is held) is unchanged; tests: the four spellings above must re-enter (fail before: two HANG under an alarm).
owner decision: OD-7.
sources: A-1, D-7

### M-8. The count rule admits narrow numpy integers, and the interval arithmetic then overflows to a wrong interval, a math-domain error, or a wrong sequential decision   (sources: D-1)
severity: minor / status: confirmed / lane: statistics, robustness
wrong data: no: every caller found passes `int(f.sum())` or a JSON int; a future caller with a narrow integer would get a silent wrong answer.
where: cafe/pm/stats/intervals.py:55 (`_count`), :86 (`wilson`'s `4 * n * n`), the same arithmetic in `agresti_coull`, `newcombe_diff`, `interval`; cafe/pm/stats/sequential.py (`sprt_decide`); DECISIONS 967, 972 ("numpy integers pass")
claim: D: `wilson(np.uint8(30), np.uint8(100))` is (0.0, 0.7778) against (0.2189, 0.3958) for the same Python ints; `np.int8(3), np.int8(10)` raises a math-domain error; `sprt_decide(np.uint8(5), np.uint8(3), ...)` is `accept_go` where Python ints give `accept_nogo`.
check: ran on orca (`p3.py`): `wilson(np.uint8(30), np.uint8(100))` = (0.0, 0.7778371...) and `wilson(30, 100)` = (0.2189488..., 0.3958485...); `wilson(np.int8(3), np.int8(10))` raises `ValueError: math domain error`; `sprt_decide(np.uint8(5), np.uint8(3), .1, .3)` is `accept_go` and `sprt_decide(5, 3, .1, .3)` is `accept_nogo` (the Python-int call has k above n and is also answered, not refused: no range check, as D says).
root cause: `_count` checks the type and returns nothing; the arithmetic then runs in the caller's dtype.
fix: `_count` returns `int(x)` and every use takes its result (`k = _count(k, "k")`); `sprt_decide` refuses k above n or below 0 (a count of a sample cannot exceed it; DECISIONS 972 says it checks the arguments). Tests: each narrow dtype through each function equals the Python-int answer (fail before: uint8, int8, int16, int32 at n = 23,170 and above); `sprt_decide(5, 3, ...)` is a ValueError. Not an owner decision. Foresight: the six callers pass Python ints or int64, unchanged; coverage 100 % on `stats`.
sources: D-1

### M-9. `cfd._literals` keys only top-level `def` and `class` statements: a function under a top-level `if` or `try`, or an `async def`, is outside the cache key   (sources: D-8)
severity: minor / status: confirmed / lane: reproducibility
wrong data: no (latent): no function of `cfd.py` has that shape today (the only non-def top-level statement of that kind is an `if`, which holds no function).
where: cafe/cfd.py:78-80 (`ast.parse(src).body` filtered to `(FunctionDef, ClassDef)`); DECISIONS 929/960 ("an edit cannot miss it")
claim: D: `_literals` of two sources that differ only in a literal inside a function under `if True:` or in an `async def` are equal.
check: ran on orca (`p3.py`): the `if True:` pair equal True, the `async def` pair equal True; the top-level statements of `cfd.py` that are not def/class/assign/import/expression are one `If` (the `__main__` guard).
root cause: the walker looks at `body` only, one level, and not at `AsyncFunctionDef`.
fix: collect defs recursively through `If`, `Try`, `With`, `For`, `While` and include `AsyncFunctionDef`; keep `NOT_KEYED`. The current key is unchanged (no def lives there), so no cached CFD result is renamed. Tests: a def under `if`, under `try`, an `async def`: each moves the digest (fail before: equal). Not an owner decision.
sources: D-8

### M-10. A `plan.json` with a bad value is a traceback or a silent answer; only a missing key is the "damaged" message   (sources: D-6)
severity: minor / status: confirmed by reading (the tracebacks are the reviewer's) / lane: robustness
wrong data: no (a hand-damaged file): `n_min: 500, n_max: 10` answers rc 0 on member counts the run never had, and is the one to look at.
where: cafe/pm/__main__.py:312-330 (`ctx.plan.update({k: run_plan[k] for k in ("batch", "n_min", "n_max")})` copies the values unchecked; `_run_files` covers a missing key and a wrong type read inside it), cafe/pm/stage1.py:1039 and :1065, cafe/pm/budget.py:538
claim: D: `batch: 0` ends in `ZeroDivisionError` from `stage1.wave` after 24 s; `batch: "32"` and `batch: 32.5` in `TypeError`; `n_min > n_max` runs and answers.
check: read the lines (the update is outside any value check); not re-run (each probe is 24 to 85 s of a real `whatif`; D ran them).
root cause: the plan's three numbers are trusted as read.
fix: after reading, check `batch`, `n_min`, `n_max` are ints (not bool), `batch` at least 1, `1 <= n_min <= n_max`, and raise the same "damaged or incomplete" `ConfigError` the missing key raises. Tests: the four bad files (fail before: ZeroDivisionError, two TypeErrors, rc 0). Not an owner decision.
sources: D-6

### M-11. The leftover's `mv` advice cannot appear in the commands that meet a missing store, a lab store's leftover is never swept, and a half-deleted aside is called "the older data"   (sources: D-4, D-5)
severity: minor / status: partly (the code paths confirmed by reading: `pipeline._ocean_cached` returns False on a missing store before `open_store`, a lab store is not locked, and the `rmtree(old, ignore_errors=True)` after the second rename leaves a partial tree on a kill; the SIGKILL runs are the reviewer's) / lane: operations, robustness
wrong data: no: advice text and a leftover on a 98 %-full disk; a later ingest check (NaN mask) is likely to catch the holes of D-5.
where: cafe/pm/pipeline.py:365 (`_ocean_cached`: `if not path.exists(): return False`), :318 (`_need`'s note), :525 (a lab store is not locked); cafe/pm/env/hycom.py:305-312 (`unreadable`), :229 (`asides` by name only), :288-289 (the delete); docs/RUNBOOK.md:298
claim: D-4: after a kill between the two renames, `run`, `fetch` and `ingest-ocean` meet the missing store through `_ocean_cached`, and the message that names the `mv` is printed only by `open_store`; for a lab store nothing sweeps. D-5: after a kill during the delete, the aside holds 6 of 11 files and `open_store` of the missing name advises `mv` of it, which puts back a partial store.
check: read the lines above (D-4's path: `_ocean_cached` returns False; the `mv` text is in `unreadable`, called from `open_store`; `held` is False or the lock absent for a lab store so the sweep at :312 does not run); the kills are D's.
root cause: the aside is whole in two of the three kill points and the code names no difference; the missing-store path has its own message.
fix (OD-8): before the `rmtree` the aside is renamed to `.<16 hex>.<12 hex>.dead.tmp`, which `asides` does not offer to `mv` and the next locked write sweeps; `_need`'s note names the asides of a missing store (so the first command a lab user runs says it); RUNBOOK:298 says the lab store is not swept and names the command to list it. Tests: a kill-simulated `rmtree` (a patched `shutil.rmtree` that raises after the first file): the name is `.dead.tmp`, `asides` does not return it, `unreadable` does not advise it; `_need` names a leftover aside. Foresight: the test of 969's `asides` pattern (`{12}` hex digits) gains the new suffix.
owner decision: OD-8.
sources: D-4, D-5

### M-12. RUNBOOK's lock-error symptom is not the text the code prints   (sources: D-3)
severity: minor / status: confirmed / lane: documentation
wrong data: no.
where: docs/RUNBOOK.md:299 (first cell: "`error: the lock file <table>.lock ... cannot be opened`"), cafe/pm/emulator.py:130 (the real text starts "cannot open the emulator table's lock file <path> (<Error>: ...)")
check: read both lines: the RUNBOOK's words ("the lock file ... cannot be opened") do not occur in the code; the code's text begins "cannot open the emulator table's lock file". The second symptom of the row is word for word.
fix: the row's first cell quotes the real text; a doc test that every backticked `error:` symptom in the lock rows occurs in the code (documents batch).
sources: D-3

### M-13. `same_members` `measured` is computed from a display phrase, and an unknown phrase is "not measured" rather than "unknown"   (sources: D-9)
severity: minor / status: confirmed by reading and by the reviewer's re-render / lane: documentation, reproducibility
wrong data: no: nothing prints `measured` or `source`.
where: cafe/pm/report.py:435; cafe/pm/whatif.py:67 (`BASE_SAME_FLAGS, BASE_SAME_RUN` are prose)
claim: D: `source` set to `"<b>weird</b> & \"x\""` gives `measured: false`; a non-string `source` (5) makes `report_traceable` fail and `report --run` exit 1.
check: read the lines (`measured = source == BASE_SAME_RUN`): an unknown phrase is false, not null, and rewording the constant turns every earlier file's `measured` from true to false; the non-string case not re-run.
fix: in `report.py` only: `measured = {BASE_SAME_FLAGS: False, BASE_SAME_RUN: True}.get(source)` for a `str`, None for anything else, and the report stores `source` only when it is a `str` (a test for 5, a list and a dict; fail before: the ledger error for 5). No change in `whatif.py` (the constants stay; an older file with an older phrase reads None, which DECISIONS 993 calls "not known"). Not an owner decision.
sources: D-9

### M-14. `python -m cafe._seed` does not look at what it seeds   (sources: D-10)
severity: minor / status: confirmed by reading (the runs are the reviewer's) / lane: robustness, honesty
wrong data: no (an operator-supplied file): a result of another shape is cached under the real key and the Hangar reads it as a result.
where: cafe/_seed.py:25-45 (`r = json.loads(p.read_text())`, then `cfd.cached(k, stl, log, lambda: r)` with no check of shape; a corrupt file is a raw `JSONDecodeError` with no file name, after earlier samples were seeded)
fix: the shape of a result is checked per case before caching (the keys `cfd.cached` callers read: a dict with the case's fields; for `surface` the `speeds` mapping) and a bad or unreadable file is "NOT seeded <file>: <reason>", exit 1, before anything is written. Tests: `[1,2]`, `{not json`, a result without its keys (fail before: seeded, traceback). Not an owner decision.
sources: D-10

### M-15. `whatif._numbers` refuses a duty of 1.0000001 with the message "duty 1 needs ... at most 1"   (sources: A-10)
severity: minor / status: confirmed / lane: robustness
wrong data: no.
where: cafe/pm/whatif.py:197-199 (`{duty:g}`)
check: ran on orca (`p3.py`): `Invalid: v: the change shift_h 0, dlon 0, dlat 0, duty 1 needs finite numbers and a duty above 0 and at most 1`.
fix: print the number with enough digits to differ (`{duty:.10g}`, or `repr` when `:g` would equal an allowed value). Test: the message of 1.0000001 contains "1.0000001" (fail before: "duty 1"). Not an owner decision.
sources: A-10

### M-16. Surviving mutants of rounds 18's tests: the what-if baseline guard, the fix-text edges, the credibility lines, the hycom sweep, the CFD/`env_count`/seed/`replace_from` pins, the hull grammar and `sprt_decide`, the UAS turbulence length   (sources: A-2, A-3, A-4, A-6, A-7, A-8, A-9)
severity: minor / status: partly: reviewer A's 7 groups are taken from the reviewer; here the code at the mutated lines was read and exists as A describes (whatif.py:816, 821, 823, 819; report.py:413, 430, 437-440, 1456-1458; credibility.py:381, 910, 914; stage1.py:286; hycom `asides`); no mutant was re-run (the driver was lost to an orca timeout: see the top) / lane: tests
wrong data: no (as shipped; A says so and this merge found no contradicting run).
where and what must fail (one test each, fail before on the mutant, pass after; tests in the batch that owns the file):
- A-2 (whatif.py:816, :819, :821, :823; batch C): W3a `>` for `>=` in `len(flags) >= plan["batch"]`; W3b `>= 1`; W4 the UAS-3-D exclusion dropped (a 3-D UAS would take the base run's 2-D-wind flags as its baseline); W6a `<` for `<=` in the share test; W7 `elif run_s1` for `elif uas_3d or run_s1`; F10 `n=len(flags)` for `n=len(f0)`. S1 is near-equivalent (a shift of exactly the window length; the whole-days refusal comes first).
- A-3 (report.py:413, :430, :437-440, :1456-1458; batch B): FH8 (an EMULATED best row reads `sm`: "on the same 64" beside an emulated answer), FH6 (the "on the whole run of N" branch), FH9 (`hi=same["lo"]`), FH10 (`same_as_baseline` against the whole run's P(fail)), SM9 (the older-`flip.json` guard).
- A-4 (credibility.py:381, :910, :914; batch B): K4 (the count of `|E| <= U_val` over `full` for `judged`), K7b (`not wide` dropped: a row with U_val at or above 50 % of the reference no longer blocks level 3), K12a (`kind != "fitted"` as True).
- A-6 (hycom.py; batch E): H7 (`asides` offers a symbolic link with a matching name), H9 (`{1,12}` for the 12 hex digits); H12 and O13 are identity edits (ignore). The sweep is held by `test_round18_m.py` and `test_hycom.py`, files that DECISIONS 969 does not name.
- A-7 (par.py:55-56, cfd.py:62-68, _seed.py, atomic.py; batch D): N5 (`digits and` dropped from the wording test), D7 (the last warning for the first in the "NOT seeded" line), A3 (`fchmod(fd, mode or 0o600)` for a new name); C9 and C11 killed by the wider selector.
- A-8 (fea.py hull grammar, stats/sequential.py:28-29; batch F): G11 (the colon out of `_NOT_PLAIN_FIRST`), G14 (the key-line check), G16 (the whole line in the refusal message); I7 and I8 (`sprt_decide` with no `k` or no `n` check; note M-8 above: if the checks do not exist the mutants are vacuous: decide there first); G15 equivalent; the wide rerun A could not finish is not run here either.
- A-9 (stage1.py:286, batch A): U10 (`so["duration_s"] + 60.0` for `uas.sortie_t_max(so) + 60.0`, the turbulence series of a hard-stop flight).
sources: A-2, A-3, A-4, A-6, A-7, A-8, A-9

---

## Open decisions (the lead takes the defaults)

- OD-1 (M-1): a link with two glider ends. Options: (a) required moments = every glider end surfaced, for RF, acoustic and Iridium; (b) the loader refuses a second glider end in `when: surfacing` and `uas_airborne` and nothing else changes; (c) (a) for RF and Iridium, acoustic follows no surfacing at all (a transducer works under water; DECISIONS' rule says otherwise today). Default: (a), the minimal change that makes the function symmetric and keeps the loader as it is, plus the "never required" count on the page.
- OD-2 (M-2): the card's pair lookup. Options: (a) float tolerance only (1e-6 m) for the match and the trigger; (b) a row is matched within 0.05 m, the trigger is `<= 0.5 + 0.05`, and the card prints the actual heights and "taken as the row of X m"; (c) as (b) and the trigger widened to every end of 2.5 m or lower, with "not measured" for a height with no row within tolerance. Default: (b), after the batch checks that the table's figures move by under 1 dB over plus or minus 0.05 m for every row (a test recomputes it with the Fresnel reference of `tests/test_round18_x.py`; if one row moves more, shrink that row's tolerance). I did not measure the 0.05 m sensitivity here.
- OD-3 (M-3): the Hs of the card figures. Options: (a) words "at Hs 0" on the card and the Hs 1, 2, 3 m figures of M-3 in PHYSICS 12.1 and L23; (b) re-measure the table at Hs 1 and 2 m and print the one nearest the run's sea state. Default: (a).
- OD-4 (M-4): an older `flip.json` with `base_same` and no `target_same`. Options: (a) the left badge is the same-members verdict and "(whole run: X)" beside it, the target stated as the whole run's; (b) leave it as before (round 18's choice). Default: (a).
- OD-5 (M-5): the acting columns of a UAS link and of the UAS profile row. Options: (a) `battery_capacity_scale` into `TRACK_ACTS["uas"]` and `wind_direction_bias` into `UNSEEN` of the profile row; (b) leave the tables and amend the "inert" sentence. Default: (a); q21's UAS floor may move (more columns).
- OD-6 (M-6): the two current columns on a Slocum's battery row. Options: (a) keep them (`DEMO_ONLY`), with the mechanism written in the comment and DECISIONS 992; (b) drop them from the row. Default: (a).
- OD-7 (M-7): the re-entry key of `store_lock`. Options: (a) the file's `(st_dev, st_ino)` after the open; (b) `os.path.realpath` of the path. Default: (a) (it holds for hard links and bind mounts, (b) does not).
- OD-8 (M-11): the half-deleted aside. Options: (a) rename it to `.dead.tmp` before the `rmtree`, never offered for `mv`, swept by the next locked write, and `_need` names a leftover; (b) only reword the RUNBOOK and the `unreadable` message ("whole unless the kill came during the delete; check its size"). Default: (a).
- Not owner decisions, stated so they are not asked: M-8 (`int()` after `_count`, range check in `sprt_decide`), M-9 (recursive def walk), M-10 (plan.json value checks), M-12 (the RUNBOOK text), M-13 (`measured` from a table), M-14 (`_seed` shape check), M-15 (the printed duty), M-16 (tests).

---

## Batches

Code batches A to F have disjoint source and test file lists and can run in parallel in separate worktrees; batch G (documents) runs last. Each batch adds its tests in its own new file `tests/test_round19_<letter>.py`; where an existing test file must change (a pinned sentence or a count), it sits in the batch that holds the production code. Gates as CLAUDE.md: ruff, mypy strict, coverage 100 % on physics/stats/env, one regression test per fix that fails before and passes after, no banned tokens.

### Batch A: stage 1 links and acting tables
- findings: M-1, M-5, and the A-9 test of M-16
- files: cafe/pm/stage1.py, cafe/pm/config.py (only if OD-1 option b is taken instead), tests/test_stage1.py (the link tests that pin `_surfaced` and the docstring), tests/test_round18_c.py (the link-acts test's window and quantiles), tests/test_round19_a.py (new); cafe/pm/physics/*, cafe/pm/credibility.py read only
- must fail before: M-1: the two-glider scene of `p1.py` (both orders give the same need_count, and a submerged glider has no margin; before: 217 against 0); an Iridium link on two gliders; a link with `need_count` 0 is reported as never required. M-5: `link_acts` of `usv-uas-rf` contains `battery_capacity_scale`; the 18 h probe at battery scales 0.70 to 1.00 never moves a column outside `link_acts` (before: need_count 39 to 48); `wind_direction_bias` is in `UNSEEN` of the UAS profile row, and the test of `test_round18_x.py:232-241` is handed to batch B (below). A-9: `so["duration_s"] + 60.0` is killed.
- notes: `tests/test_round18_x.py:232-241` (`test_x2_wind_direction_acts_on_the_uas_battery_reserve_and_not_on_its_profile_share`) must change for M-5; because batch B owns that file, B applies the one hunk (name and assertions) from this batch's note. `credibility.py` counts "used by" from `ACTS`: a test that the split does not change those counts. Hand G the DECISIONS row (amends 958, 992) and the note on q21's UAS floor.

### Batch B: card, fix line, credibility
- findings: M-2, M-3, M-4, M-13, the A-3 and A-4 tests of M-16, and the one hunk of M-5 in `tests/test_round18_x.py`
- files: cafe/pm/report.py, cafe/pm/credibility.py, tests/test_report.py, tests/test_credibility.py, tests/test_round18_a.py (the old-`flip.json` test of line 168 and any pinned card sentence), tests/test_round18_x.py, tests/test_round18_m.py, tests/test_round17_b.py (only if a pin moves), tests/test_round19_b.py (new); cafe/pm/stage1.py (`ship_antenna_m`), cafe/pm/physics/comms.py are read only
- must fail before: M-2: 0.5000001 and 0.30000000000000004 with 15 m as OD-2 decides (before: None and "not measured"); a ship without `antenna_height_m` prints 10 m, not "no single height"; PE11 (swapped names), Q3 and Q5 mutants die. M-3: the card sentence contains "Hs 0" (before: it does not). M-4: the disagreeing round-17 entry (MARGINAL 0.375 of 32, whole run NO-GO) prints a MARGINAL badge on the left and "(whole run: NO-GO)" (before: "NO-GO to GO" beside 0.375). M-13: `source` 5, a list and a dict leave `report --run` green and `measured` null (before: ledger failure for 5). A-3's FH6, FH8, FH9, FH10, SM9 and A-4's K4, K7b, K12a die.
- notes: `_low_antenna_note`'s three start phrases stay (tests pin them with `startswith`); `report.json` gains no key. Hand G the figures for PHYSICS 12.1 and L23 (Hs 1 to 3).

### Batch C: what-if and the command line
- findings: M-10, M-15, and the A-2 tests of M-16
- files: cafe/pm/whatif.py, cafe/pm/__main__.py, cafe/pm/budget.py (only if the plan check needs `batch` there), tests/test_whatif.py, tests/test_round18_a.py is batch B's: use `tests/test_round19_c.py` (new) only
- must fail before: M-10: `plan.json` with `batch: 0`, `"32"`, `32.5` and `n_min 500, n_max 10` each give the "damaged or incomplete" `ConfigError` (before: ZeroDivisionError, two TypeErrors, rc 0). M-15: the message of 1.0000001 names it. A-2: W3a, W3b, W4, W6a, W7, F10 die (the flags-baseline guard at its edges).
- notes: `whatif.py:67`'s constants stay (batch B reads them); `ctx.plan` is the only place `run_plan` is copied.

### Batch D: CFD key, seed, atomic, parser pins
- findings: M-9, M-14, and the A-7 tests of M-16
- files: cafe/cfd.py, cafe/_seed.py, cafe/pm/par.py (tests only expected), cafe/atomic.py (tests only expected), tests/test_cfd.py, tests/test_round17_e.py, tests/test_config.py, tests/test_round19_d.py (new)
- must fail before: M-9: `_literals` moves for a def under `if`, under `try`, and an `async def` (before: equal). M-14: `[1,2]`, a corrupt file and a result without its keys are "NOT seeded", exit 1 (before: seeded, traceback). A-7: N5, D7, A3 die.
- notes: the current CFD key is unchanged (no def sits under an `if` today), so no cached result is renamed; a test pins that `recipe()` of the shipped file equals its value before the change.

### Batch E: locks, hycom store, ingest hint
- findings: M-7, M-11, and the A-6 tests of M-16
- files: cafe/pm/env/remote.py, cafe/pm/env/hycom.py, cafe/pm/pipeline.py (`_need`'s note only), cafe/pm/emulator.py (no change expected), tests/test_remote.py, tests/test_hycom.py, tests/test_emulator.py, tests/test_round18_e.py, tests/test_round19_e.py (new)
- must fail before: M-7: the four spellings of `p3.py` re-enter under an alarm (before: two HANG). M-11: a store whose aside deletion was interrupted is named `.dead.tmp`, is not offered by `asides` or `unreadable`, and `_need` names a leftover aside (before: offered `mv`). A-6: H7 and H9 die against the named files.
- notes: `store_lock` keeps its signature (the `log` argument stays); `hycom.write_store`'s `held` is unchanged.

### Batch F: statistics and the hull reader
- findings: M-8, and the A-8 tests of M-16
- files: cafe/pm/stats/intervals.py, cafe/pm/stats/sequential.py, cafe/fea.py (tests only expected), tests/test_stats_exact.py, tests/test_stage3.py (the r15_l0_4 rows only), tests/test_round18_f.py, tests/test_round19_f.py (new)
- must fail before: M-8: narrow dtypes through `wilson`, `agresti_coull`, `newcombe_diff`, `interval` and `sprt_decide` equal the Python-int answers (before: uint8, int8, int16, int32 give other numbers or a math-domain error); `sprt_decide(5, 3, ...)` is a ValueError. A-8: G11, G14, G16, I7, I8 die.
- notes: coverage 100 % on `stats`; the shipped `config/assumptions.yaml` entry must still read (the first test of `test_round18_f.py`).

### Batch G: documents (last)
- findings: the document edits handed over from every other batch, and M-12
- files: DECISIONS.md (new rows from 996 on; amend 944, 958, 967, 969, 972, 991, 992, 993), CHANGELOG.md, docs/RUNBOOK.md (:299 for M-12, :298 for M-11), docs/PHYSICS.md (12.1: Hs 1 to 3 figures, M-3), docs/CREDIBILITY.md (L23), QUESTIONS_FOR_LAB.md (a sub-item per owner decision with its default: OD-1 to OD-8), STATUS.md, HANDOFF.md, review/orca/PROBLEMS.md, review/round_19/q20_vs_q19.md (read)
- notes: runs last, edits no code; the stop-rule line in HANDOFF.md says round 19 is not clean (one major, four "wrong data: yes"), so the count of consecutive clean rounds stays at 0.

Coverage check: M-1 to M-16 each appear in exactly one batch as the owner of the production change (A: M-1, M-5; B: M-2, M-3, M-4, M-13; C: M-10, M-15; D: M-9, M-14; E: M-7, M-11; F: M-8; G: M-12), M-16 is split by file (A-2 to C, A-3 and A-4 to B, A-6 to E, A-7 to D, A-8 to F, A-9 to A), and every source file is in one batch only (`stage1.py`, `config.py`: A; `report.py`, `credibility.py`: B; `whatif.py`, `__main__.py`, `budget.py`: C; `cfd.py`, `_seed.py`, `par.py`, `atomic.py`: D; `remote.py`, `hycom.py`, `pipeline.py`, `emulator.py`: E; `intervals.py`, `sequential.py`, `fea.py`: F). One shared test file is split by hunk: `tests/test_round18_x.py` is batch B's and carries the single M-5 hunk from batch A.

---

## Totals

- Findings: 16 merged from 28 source ids. By severity: 0 critical, 1 major (M-1), 15 minor.
- By status: confirmed 14 (M-1 to M-10 and M-12 to M-15: M-6, M-10, M-13 and M-14 by reading with the reviewer's run, the others reproduced or recomputed here), partly 2 (M-11: code paths read, kills the reviewer's; M-16: read, no mutant re-run), not confirmed 0. Reproduced or recomputed here on orca: M-1, M-2, M-3, M-4, M-5, M-7, M-8, M-9, M-15 and M-2's, M-3's tables; by reading: M-6 (with arithmetic), M-10, M-11, M-12, M-13, M-14, M-16.- Wrong data: yes (5): M-1 (major: the verdict and pass fraction of a two-glider link depend on the order of its ends), M-2 (the card's silence or "not measured" for a height off a placeholder by float dust or by a CAD refinement), M-3 (the card's figures stated without Hs 0), M-4 (the fix line of a re-reported round-17 run), M-5 (the "most sensitive to" line and floor of a link with a UAS end; B-3's half counted no). Wrong data: no (11): M-6 to M-16. q20 itself: no q20 number, verdict, map or interval is affected by any finding.
- Reviewers' own ratings against this merge: B-1 yes (kept, major); B-2 yes (kept, conditional); B-3 yes limited (kept inside M-5, own half no); B-4 no (kept); D-2 yes by omission (kept, conditional); C-1 yes (kept); C-3 partly (raised to yes, conditional: the printed minimum of two shipped-pair rows is wrong at the sea states the missions run at); C-2 and C-4 no (kept, inside M-2); every other source id no (kept).

**Stop rule.** Round 19 is NOT clean: one major finding and four wrong-data findings (M-1 to M-5). The count of consecutive clean rounds is 0. Rounds 15 to 19 have each had at least one such finding; round 19 has a major again (rounds 17 and 18 had none). The owner's stop rule needs two consecutive rounds with none.

## Not covered (by any reviewer or by this merge)

- Reviewer A: no mutant was re-run by this merge (see the top); A's wide rerun of G11, G14 to G16, I7, I8 did not finish; the K4, K7b, K12a mutants against the full credibility file; no gate, suite, demo or `make audit`; no recomputation of the ten pairs (B's and C's lanes, and mine for three of them).
- Reviewer B: the parabolic equation for any pair and 0.02 m, Hs above 1 m for the table, ranges under 300 m; the gridded demo environment's single-column probes (the demo's data copy was deleted, P-R18X1); interactions of two columns; a real stage-1 `run` and the report page of a two-glider link.
- Reviewer C: the stage-1 "becomes" line from a real flip (the demo's vehicles have no flipping candidate), the no-acting-input line on a real run, `credibility.html` factor levels, the stage-3 and reach tables, the environment table, the pages in a browser, the PE figures.
- Reviewer D: a full run, a kill and resume, two concurrent runs, a kill landing mid-append of the emulator table, `write_store` on a real zarr and the delete time of a 20-GB store, the hull fuzz on the whole file (a 41-line excerpt only), the `cfd` key on the real file before and after each signed literal, a real Stage-1 what-if compared with a rerun, the TAO download lock.
- This merge: the mutants of M-16 and A-5 (the driver was lost to an orca timeout; supported only by reading and by the grep of `tests/`); M-6's toy run (arithmetic only); M-10's and M-11's tracebacks and kills (reviewer's); M-14's runs; the sensitivity of the card's figures to a height off a row by 0.05 m (OD-2's default needs it measured); an acoustic link between two gliders (`when: surfacing`) through a real batch (only RF and Iridium were run); a `uas_airborne` link with two UAS ends (read: the same one-end pick, not run); whether the NaN mask would catch D-5's holes.
