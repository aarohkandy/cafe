# Round 23 merged findings (BRIEF 5.6 step 2)

Inputs: reviewer_a.md (A-1 to A-5), reviewer_b.md (B-1 to B-4 and notes N-1 to N-4), reviewer_c.md (C-1 to C-3), reviewer_d.md (D-1 to D-8) = 20 source ids (the commit message and B's own header say B has 3 findings; B's body labels four, B-1 to B-4, and I count four; the notes N-1 to N-4 are not findings but two of them are folded in below). Merged to 10 findings, M-1 .. M-10; every source id appears in exactly one merged finding: A-2 is M-1; B-1 is M-2; B-2 is M-3; C-1 is M-4; A-3, B-3, B-4, C-2, C-3 and B's N-1 and N-4 are M-5; A-1 and D-1 are M-6; A-4 and D-6 are M-7; D-2 is M-8; D-3, D-4 and D-5 are M-9; A-5, D-7 and D-8 are M-10. Points that are mine (found while verifying or sweeping, marked "found here"): the Iridium sentence is also false for `p_success` or `max_attempts` edited by the lab, not only for `required_fraction` (M-1); the card's tail "at a wave height of 1 to 3 m these figures are different" (M-2); `NOT_EXERCISED_NOTE` ends "no number of members changes that" (sweep S-9); CREDIBILITY 66's and report.py:345's "no number of members certifies it" (S-12); the comms docstring's 7.6 dB sits in a test pin (M-4); several more in the Claims sweep.

## How this was verified

Against HEAD c523f32 (r23-prep; code of 935aee0), by reading the cited code, and on cafe-orca (proot, 2 CPUs, one job, scratch worktree `../cafe-rev23-v` detached, private `pm_rev23_v`; both removed by exact name at the end; nothing under /tmp, nothing outside `~/cafe-worker`, no kill, no mutant, no test) by one script, `probes/v.py` (in the removed worktree; 40 lines):
- `rfband`-equivalent two-ray minus Fresnel at 400 and 40,000 evenly spaced ranges for (0.3, 0.3), (0.3, 15), (0.5, 0.5), (2.2, 15), (2.2, 108.1) at 915 MHz and (500, 132.658), (706, 838), (571, 971) at 2,440 MHz (B-1, B-4, A-3, C-1).
- `comms.iridium_session(340, rng, 20000)` over 865 moments: per-sample failure and the share of members that miss at least one moment (A-2).
Results (all reproduce the reviewers): (0.3, 0.3): min / median / max 11.26 / 11.41 / 11.42 at 400 and at 40,000, 400 of 400 over, none under; (0.3, 15) 1.19 / 5.14 / 6.04 at both, 390 and 390.9 over; (0.5, 0.5) 6.38 / 6.68 / 6.70 and 6.36 / 6.68 / 6.70; (2.2, 15) -3.31 / -0.40 / +0.23 at both. So for pairs of low antennas the extremes at 400 ranges are the model's. (2.2, 108.1): -10.77 / -1.91 / +39.25 (400) against -14.88 / -1.92 / +70.92 (40,000), counts 18 over and 20 under against 18.6 and 19.1 per 400. (500 m, 132.658 m) at 2,440 MHz: over 74 of 400 at 400 ranges and 94.3 per 400 at 40,000 (a move of 20.3 = 0.051, above the printed 0.046), median -2.47 against -2.56. Iridium: per-sample failure 1.28e-4 (0.05^3 = 1.25e-4), and 10.5 % of members miss at least one of 865 moments (analytic 10.25 %). My (706, 838) and (571, 971) at 2,440 MHz did NOT reproduce B-4's 0.92 dB and 28 of 400 (counts moved 3.5 and 7 of 400, the median 0.27 and 0.09 dB): B's heights were rounded in the report and the figure is height-sensitive near a null; A-3's pair reproduces exactly. Not run here: B's 4,000 random pairs, real Bellhop, a GOFS profile, the YAML and app probes of A and D (read only), q24 (does not exist).

Claims that rest on a reviewer alone: A-1 and D-1's digit counts (I read `_finite` and `_yaml`: the mechanism is there, the 4,301-digit threshold is Python's), D-2's shapes (read `live_create`, not run), D-3 to D-5, D-7, D-8, A-4 and D-6 (read; `r[key]` is inside a `try` that does not name KeyError), A-5's mutants, B-1's 282 of 4,000 and B-4's 0.92 dB, B's N-1 (real batch heights) and N-2 (real Bellhop with a constant profile), C-2's 632.45 km. A, B and C agree with each other on everything I did not rerun.

## Severity

0 critical, 0 major, 10 minor. None of the four "wrong data" findings is major: each is a printed sentence about a limit or a cause that is false for part of the input domain and none moves a verdict (M-1 restates assumed numbers; M-2 over-warns; M-3 names a cause for a count that is right; M-4 is a document figure for a link no demo verdict rests on).

Status: 10 merged; confirmed 10 (reproduced on orca: M-1, M-2, M-5's A-3 half; by reading: M-3, M-4, M-6 to M-10); partly confirmed 0 as to the mechanism, but B-4's 0.92 dB figure not reproduced (M-5); refuted 0.

## Stop rule (the owner's, quoted)

"A round is clean only if it has no critical or major finding AND no finding where a verdict, printed number, map, warning or other acted-on output, documents a user acts on included, is wrong or misleading."

Wrong data to act on: yes for M-1 (A-2), M-2 (B-1), M-3 (B-2), M-4 (C-1): all four reviewer ratings hold. No for M-5 to M-10. History of wrong-data merged findings by round: 5, 3, 5, 7, now 4 (source ids 4: A-2, B-1, B-2, C-1; none refuted).

**Round 23 is NOT clean. The count of consecutive clean rounds was 0 before this round and is 0 after it.** The owner's rule needs two in a row.

---

## Critical

None.

## Major

None.

---

## Minor, wrong data: yes (M-1 to M-4)

### M-1. The Iridium note printed beside every Iridium verdict says a member "cannot miss the required fraction by chance"; at `required_fraction` 1.0 about 1 member in 10 does   (source: A-2; the edited-numbers case found here)
severity: minor / status: confirmed (reproduced on orca) / lane: honesty, statistics
wrong data: yes. `report.IRIDIUM_NOTE` (report.py:1827-1830, printed by `_iridium_html` for every link whose method starts with "Iridium"), and PHYSICS.md 849 ("with 865 independent samples a member cannot miss 5 % of them by chance (P(fail) below 1e-90 ...)"). The sentence is conditioned on the number of samples and not on the required fraction: `mission.json` allows `required_fraction` up to 1 (exclusive minimum 0), the per-sample failure of a 340-byte SBD message is `(1 - p_success)^max_attempts` = 1.25e-4, so 10.5 % of members miss at least one of 865 moments (my run: 0.105; analytic 0.1025), and a member with `required_fraction` 1.0 fails. Found here: `p_success` and `max_attempts` are assumed numbers the lab is told to replace (the note says so itself), so the sentence is false after the lab's own edit too (p_success 0.5: per-sample failure 12.5 %, no member passes 865 moments at 0.95).
check: by reading `iridium_session` (comms.py:322-338: attempts independent, one session, A attempts) and `stage1.py:804`; the run above.
root cause: a printed absolute ("cannot ... by chance") that is true for the demo's four numbers (0.95, 3, 865, 0.95) and a statement about the product of them.
fix (narrow, no new code): delete the clause ", so a member needing hundreds of samples cannot miss the required fraction by chance" from `IRIDIUM_NOTE` (the sentence then ends "... geometry enters it). It is no evidence about the real service; replace the numbers ..."). Delete the parenthesis in PHYSICS 849 ("a member cannot miss 5 % ... P(fail) below 1e-90"). Keep "restates assumed numbers", "the same in any sea state, weather or position": true by the code path (`iridium_session` takes bytes, an rng and the member count: no height, state or position).
test that proves it over the domain: (a) a lint test over the generated page for an Iridium link at `required_fraction` 1.0, 0.95 and 0.1 and any `p_success`: `IRIDIUM_NOTE` contains none of "cannot", "by chance", "never", "hundreds" (the note is a constant, so one assertion on the constant covers the whole domain); (b) the existing `tests/test_round16_report.py:107-110` pins (once per Iridium link, "p_success" and "sea state, weather or position" present) stay.
What it could break: tests/test_round16_report.py (it pins pieces of the note, not the deleted clause), the report page of the demo (one Iridium card: the note text only; q25 against q24 must say so); docs: PHYSICS 849.
owner decision: none. source: A-2

### M-2. The sampling note printed on every RF card and in L23 says the model's error at a null is larger than the median and a finer sampling can find a larger one; for the ten pairs of low antennas the card prints, and every glider, USV and ship pair, it cannot   (source: B-1; the card's tail found here)
severity: minor / status: confirmed (reproduced on orca) / lane: honesty (class: a hedge that is false in the safe direction)
wrong data: yes, as misleading (an over-warning, not an under-warning). `credibility.SAMPLING_NOTE` (credibility.py:55-56: "These are figures of the 400 sampled ranges, not of the worst case: at an interference null the model's error is larger than the median, and a finer sampling of the ranges can find a larger one"), printed by `report._low_antenna_note` (report.py:871, 873) on the card of every RF link and inside L23. For every pair whose antennas are both about 15 m or lower at 915 MHz there is no null in the band: (0.3, 0.3) is 11.26 / 11.41 / 11.42 at 400 and at 40,000 ranges (B: also at 400,000), (0.3, 15) 1.19 / 5.14 / 6.04, (2.2, 15) -3.31 / -0.40 / +0.23. The card says the real error may be worse than its +9.3 dB median for the Slocum pair; it is not. It is true for pairs with a UAS-height partner. Also a document sentence of RUNBOOK 190 ("the largest and smallest differences of a sampled grid are the sampling's") and PHYSICS 817 ("which is why the extremes keep growing as the sampling is refined").
found here: the card's tail (report.py:~862) says "at a wave height of 1 to 3 m these figures are different (L23)": L23 measured only three pairs above Hs 0, and B shows those three are identical to Hs 0 at the median and within 0.5 dB at the minimum; for every other pair nothing was measured, so "are different" is an unmeasured absolute printed on every card. And `tests/test_round22_b.py::test_m1_*` passes only because it compares a 40,000-point maximum with the 400-point median on a set where the plateau pairs exceed their median by 0.01 dB.
root cause: round 22 replaced the extremes by the median and counts and then added a sentence about the extremes that it had measured on the demo's pair. A generic hedge is a claim about every pair.
fix (smallest first, OD-1): (1, default) shorten `SAMPLING_NOTE` to the part that is true for every pair: "These are figures of the 400 sampled ranges." Delete "not of the worst case: ... a finer sampling ... can find a larger one". Change the card's tail to "this is for a calm sea (Hs 0); L23 gives three pairs at Hs 1 to 3 m". No new code, one constant and one tail. (2) Make the note conditional on `pair_band`'s own extremes moving with the sampling: new code and a second `pair_band` call at a finer N per card; rejected.
test that proves it over the domain: the note and tail are constants: (a) over a grid of heights 0.1 to 1,000 m at both radio frequencies (the `tests/test_round22_b.py` grid) the generated card for each pair contains "400 sampled ranges" and none of "worst", "larger", "finer", "null", "different"; (b) the counts and median printed equal `rfband.pair_band` (already held); (c) the claims lint of S-lint (below).
What it could break: tests/test_round20_b.py, tests/test_round22_b.py (pin "not of the worst case" and "finer sampling"), tests/test_round18_a.py, tests/test_round19_b.py, tests/test_round20_b.py (pin "these figures are different"), docs/CREDIBILITY.md L23 cell (equal to `_l23_text()`: change both), docs/RUNBOOK.md 190, docs/PHYSICS.md 817 and QUESTIONS_FOR_LAB.md 20a (all quote "not of the worst case"); the `credibility.json` L23 text and every RF card of q25 (text only; the median and counts do not move).
owner decision: OD-1. source: B-1 (+ tail found here)

### M-3. The Bellhop label explains every capped sample as "no ray reached the receiver"; a sample capped on the negative side is the opposite   (source: B-2)
severity: minor / status: confirmed (by reading; no real profile to run) / lane: honesty (class: a label that names a cause)
wrong data: yes. `stage1._bellhop_label` (stage1.py:689-692): "N of them held at the assumed 60 dB bound on the Bellhop excess (no ray reached the receiver, or almost none)". `capped` is `np.abs(excess) > BELLHOP_EXCESS_CAP_DB` (comms.py:532), both signs, and the comms comment (comms.py:46-49) says a negative excess (a zero field in the isovelocity run: an excess of about -540 dB) is held too. There the refined margin is RAISED by 60 dB (Bellhop found rays where the isovelocity run found none) and the label says the opposite, to a lab user deciding whether an acoustic link is worse than Thorp says.
root cause: one count (`capped`, an OR of both signs over the run set) named by one cause (the positive one).
fix (deletion): delete the parenthesis: "N of them had a Bellhop excess beyond +-60 dB (the assumed cap) and were held at it". No cause, no sign, and the word "bound" goes (round 22 removed it elsewhere). Do NOT split the count by sign (new field in `_Refined`, `info` and `merge`).
test that proves it over the domain: a unit test of `_bellhop_label` over every value of `info` (done 0 to 3, total, capped 0 to 3, beyond, ran True and False): the label never contains "ray", "no ray", "almost" or "bound"; and the existing `tests/test_round22_a.py` label property test (sums and orders) stays; the `tests/test_round21_a.py` pin of the old parenthesis changes.
What it could break: tests/test_round21_a.py and tests/test_round22_a.py pin "dB bound on the Bellhop excess" and "no ray reached"; docs: RUNBOOK 189 ("the line says how many samples were held": still true). The `method` text of a Bellhop-on link in report.json (q23 had none that ran Bellhop: the demo's acoustic links are out of range, so q25 against q24 does not move).
owner decision: none. source: B-2

### M-4. "Up to 7.6 dB where the model is optimistic" and "within about 8 dB at a peak" are a grid figure printed as a limit in two documents and a pinned docstring; the demo's own pair on the card's own conditions is optimistic by 10.8 to 14.9 dB   (source: C-1)
severity: minor / status: confirmed (reproduced on orca and by A, B, C) / lane: honesty (class: round 22 M-1, a sibling the round did not narrow)
wrong data: yes. docs/CREDIBILITY.md:164 (limitation row for the sea reflection: "up to 7.6 dB where the model is optimistic and by more where it is conservative"), QUESTIONS_FOR_LAB.md:130 (12a's default: "states the error band, up to 7.6 dB optimistic at interference peaks"), cafe/pm/physics/comms.py:157 and :161 ("by up to 7.6 dB", "a link whose budget is within about 8 dB at a peak is not decided by this function"), and the "7.5 dB lower to 34.7 dB higher" sortie-hook figure beside them. The 7.6 dB is the round-12 reviewer's figure for Hs 0.5 to 1.5 m from 200 m on one grid (the docstring says "as the reviewer measured it"; the two documents do not). At Hs 0, the card's condition, (2.2, 108.1) is -10.77 dB at 400 ranges and -14.88 dB at 40,000 (my run; RUNBOOK 190 and the credibility page print these two themselves); 20 of 400 ranges are more than 3 dB optimistic. A negative difference is a model loss below the Fresnel loss: the model margin too high, the model optimistic. B confirms -7.4 / +23.6 dB at Hs 0.5 and 1.5 and at 4,000, 40,000 and 400,000 ranges (so those two figures are not grid statistics once Hs > 0), but could not reproduce the 34.7 (the hook's heights are not stated).
fix (deletion, no code): delete "up to 7.6 dB" and "within about 8 dB at a peak" in the four places and say instead: "the margin differs from a Fresnel two-ray in either direction; the card and L23 print the median and the counts for the link's own pair of heights"; point to L23. Keep the two named-grid figures in the docstring ("7.4 dB lower to 23.6 dB higher at Hs 0.5 m": reproduced by B, scope them "of one grid, 40,000 ranges") and delete the 34.7 (not reproduced). `tests/test_comms.py:642` and `tests/test_config_docs.py:433-438` pin "7.6 dB" and "7.5 dB lower to 34.7 dB higher": they change in the same batch.
test that proves it over the domain: a lint test over `docs/CREDIBILITY.md`, `docs/PHYSICS.md`, `QUESTIONS_FOR_LAB.md` and the comms docstring: none contains "up to 7.6", "within about 8 dB", "34.7"; and the claims lint (S-lint) so that the next "up to N dB" is a failure.
What it could break: tests/test_comms.py:642, tests/test_config_docs.py:433-438 (both pin the sentence), docs/PHYSICS.md 819 (the same figure). No printed report figure moves.
owner decision: OD-2 (default: delete). source: C-1

---

## Minor, wrong data: no (M-5 to M-10)

### M-5. Stability figures, a false reason and demo labels in the RF documents   (sources: A-3, B-3, B-4, C-2, C-3, B's N-1 and N-4)
severity: minor / status: confirmed (A-3 and B-3 reproduced; C-2 by the document; B-4's 0.92 dB not reproduced, the kind confirmed by A-3) / lane: documentation, honesty
wrong data: no. Each figure names its set, so each is true of it: RUNBOOK 190, PHYSICS 817 and the comms docstring print "the median moved by at most 0.59 dB and each count by at most 0.046 of 400 ... (190 pairs of heights, two frequencies)"; A-3 finds a pair in the card's domain (500 m with 132.658 m at 2,440 MHz) where a count moves by 0.051 (reproduced above) and B-4 one where the median moves by 0.7 to 0.9 dB (two UAS ends above 200 m). The reader's risk is to read "at most" as the card's accuracy; I rate it no (the words name the set) and DELETE the figures in the sweep (S-20, S-21), because a figure measured on a sample is not worth a sentence the card does not use. The other members: B-3: "unlike the Hs 0 extremes they are not nulls (the sea's roughness takes the nulls out of both curves)" (tests/test_round22_b.py docstring, PHYSICS 817) is false: the same three pairs at Hs 0 are also identical at 400 and 400,000 ranges; the cells are stable because there is no null. C-2: RUNBOOK 189 "555 and 633 km" against the run's 632.45 km (632 on the report). C-3: L23's `LOW_ANTENNA_NAMES` ("the ship's mast" for 15 m, "the USV's whip" for 2.2 m) print the demo's names in a limitation row for every mission, and "the same Fresnel two-ray" for the Hs 1 to 3 m cells omits that its reflection carries the Ament factor. B's N-1: `_end_heights`'s docstring and PHYSICS 817 say a UAS on the ground has `alt` 0 in the records; stage1.py:484 and :496 store `alt + deck_height_m` (the conclusion is right). B's N-4: `band_figures` prints "median -0.0 dB" for a median within 0.05 dB of 0.
fix (deletions and rewording; one one-line code change): delete the stability sentences (S-20, S-21) and B-3's parenthesis; RUNBOOK 189: "(555 and 632 km at q23, 150 times the 4 km range)" or drop the numbers; L23: the names stay for the four UAS pairs ("the demo's") and are dropped for the ten pairs ("0.3 m with 15 m", with the platform names in the platform column of the table of L23, or "(the Slocum)" only as the demo's), and "the same Fresnel two-ray" becomes "the same Fresnel two-ray with the Ament roughness factor in its reflection coefficient"; `_end_heights` docstring and PHYSICS: "the record holds the deck height"; `band_figures`: normalise the median with `med + 0.0` after rounding (`f"{round(med, 1) + 0.0:+.1f}"`), one expression.
test: (a) the claims lint (no "at most 0.59", "0.046" in the five documents); (b) a unit test of `band_figures` over medians from -0.04 to +0.04: no "-0.0"; (c) the L23 cell test that equates `_l23_text()` with the CREDIBILITY.md cell (already exists) holds the new text.
What it could break: tests/test_round19_b.py (pins "the ship's mast"), tests/test_round22_b.py (docstring and sentence pins), docs/CREDIBILITY.md L23 cell.
owner decision: none. sources: A-3, B-3, B-4, C-2, C-3, N-1, N-4

### M-6. A YAML integer of 4,301 or more decimal digits (or a hex one that long) and a list used as a mapping key escape the one YAML reader as a bare ValueError or TypeError   (sources: A-1, D-1)
severity: minor / status: confirmed by reading (the mechanism: `_finite` calls `len(str(node))`, which is Python 3.12's own 4,300-digit limit; PyYAML's `int(...)` raises before `_finite`; `_Loader.construct_mapping` does `seen.add(key)` on a list), the digit counts are A's and D's runs / lane: robustness
wrong data: no (a traceback and exit 1 on a file that is refused anyway). RUNBOOK 100's sentence "in ANY YAML file ... `hangar --platform` exits 2 with `error:`" is false for these inputs. `ledger.values_sha256` of such a file raises ValueError instead of returning "" (D).
fix (reuse the one reader, two lines in `config._yaml` and `_finite`): in `_finite` replace `len(str(node))` by `node.bit_length()` (no digit conversion: the message says "an integer of N bits"); add `ValueError` and `TypeError` to the `except` tuple of `_yaml` as a ConfigError ("not valid YAML"), after the ConfigError branch; no second reader, no new constant. Also `ledger.values_sha256` already catches ConfigError, so it follows.
test that proves it over the domain: parametrised over decimal digit counts 399, 400, 4,300, 4,301, 5,000, hex 3,999 and 4,000 digits, negative and underscored forms, and `? [1, 2]` / `? {a: 1}` keys: `config.read_yaml` raises ConfigError (never ValueError or TypeError), `hangar --platform` exits 2 with `error:` and nothing on stdout, `ledger.values_sha256` returns "". Plus the grep test that `_yaml` is the only reader (exists: tests/test_round22_c.py).
What it could break: tests/test_config.py and tests/test_round22_c.py (the 400-digit message wording is "an integer of 400 digits": the bit-count message changes it: keep digits where `str` is safe, bits otherwise, or pin the new wording).
owner decision: none. sources: A-1, D-1

### M-7. `vehicle._vec3` with a missing `force`, `moment` or `viscous` key is a bare KeyError, not the ValueError of DECISIONS 1064   (sources: A-4, D-6)
severity: minor / status: confirmed by reading (`raw = r[key]` is inside a `try` that names TypeError, ValueError, OverflowError; KeyError is none of them) / lane: robustness, documentation
wrong data: no. `app.reach_map` and `live_create` catch ValueError only, so a stored result with no `viscous` (an older cache: the real way to get it) is a 500; DECISIONS 1064 says every stored-vector case is a named ValueError.
fix (one token): add `KeyError` to the `except` tuple of `_vec3` (vehicle.py:371); `hull_lift`'s coarse-read `except (KeyError, ValueError)` stays.
test that proves it over the domain: `_vec3` over `{}`, a result with each of the three keys missing in turn, None, NaN, inf, 10**400, a bool, a string, a length-2 and length-4 list, a dict: always ValueError naming direction and field; and `build` and `hull_lift` on a result with each key missing: ValueError, never KeyError.
What it could break: tests/test_vehicle.py (a pin that expects KeyError from a missing key, if any); `hull_lift`'s KeyError swallowing for the coarse read keeps its meaning.
owner decision: none. sources: A-4, D-6

### M-8. `live_create`, `check_fleet` (so `create_mission` and `create_emulation`) answer 500 to a malformed body shape   (source: D-2)
severity: minor / status: confirmed by reading (`live_create`: `for x in drones: x.get(...)` runs before any type test; `check_fleet`: `for lk in body.get("links") or []`) / lane: robustness
wrong data: no (a 500 for a body no page of the app sends). `samples: 2.5` is accepted by `check_fleet` and fails later in the worker (D, reasoned, not run).
fix (one guard per entry, reuse the existing 400 raiser): at the top of `live_create`, `check_fleet` and `live.create`: `isinstance(drones, list) and all(isinstance(x, dict) for x in drones)`, `links` a list of dicts, `t0` present and a string, `samples` an int (`isinstance(.., int)` and not bool), each a 400 through the existing `HTTPException(400, ...)`.
test that proves it over the domain: a table of body shapes (drones as str, int, dict, list of int; links as 5, true, "abc", a list of lists; t0 missing, a number, a list; samples 2.5 and true) against each handler: status 400 and never an exception other than HTTPException.
What it could break: tests/test_app.py, tests/test_live.py (any that send a string `links`, which used to be a 400 by accident).
owner decision: OD-3 (default: do it; the alternative is PROBLEMS). sources: D-2

### M-9. Three readers that stay NaN-readable by design feed a model coefficient with no finite test: the calibration promote step, `config/throughput.json` and an overlay named by `CAFE_PM_OVERLAY`   (sources: D-3, D-4, D-5)
severity: minor / status: confirmed by reading (no run of mine) / lane: robustness (sibling of round 22's M-5)
wrong data: no, and not shown reachable: D-3 needs the GPU path or a hand edit (a real window's `ustar` is positive; `--gpus 0` writes no inflow series); D-4 needs a failed `make bench`; D-5 needs a bad overlay file and fails mid-run, not at argument checking. If reached, D-3 and D-4 would be (NaN turbulence in every later run; a NaN rate halves the ensemble silently: `n_max` 32 for 64 and `stage1_s` NaN).
fix: smallest first (OD-4): (1, default) one `finite_real` check inside `budget.throughput` for each leaf it returns (reuse the helper; the plan refuses a NaN, inf or non-positive rate as a PlanError), and PROBLEMS entries for D-3 and D-5 (`subgrid.promote_calibration` refuses a non-finite leaf: one loop over the dict with the same helper is a second option: batch D); (2) all three guarded; (3) PROBLEMS only. Default (1): D-4 is the only one that silently changes the number of members behind every verdict.
test that proves it over the domain: `budget.plan` with each throughput leaf set to NaN, +-inf, 0, -1: PlanError naming the leaf.
What it could break: tests/test_budget.py (a throughput fixture with a zero rate, if any).
owner decision: OD-4. sources: D-3, D-4, D-5

### M-10. Weak spots in tests and a parity gap: `noswap_sorted` survives, the AST checker's wording overstates, `fea.hull_elements_along` accepts a file the pipeline's reader refuses   (sources: A-5, D-7, D-8)
severity: minor / status: confirmed by reading / lane: tests, documentation
wrong data: no. A-5: `noswap_sorted` is equivalent today because the three functions are symmetric in the two heights to 1e-9 dB (B measured over 300 pairs), but no test asserts it, so the card's pair would depend on the order the mission names the ends after a non-symmetric edit; `vec3_len` is equivalent. D-7: `scan_source`'s "through any alias" does not reach `a, b = json, 1`, a class attribute, `self.j = json`, `d['l']`; and no test says `config._yaml` is the one YAML reader (the grep test of tests/test_round22_c.py does). D-8: `fea.hull_elements_along()` returns 70 for an `assumptions.yaml` with an extra `.nan` entry that `config.read_yaml` refuses (a parity gap; the number is the same PyYAML gives).
fix: (a) one symmetry test (`pair_band(h1, h2)` equals `pair_band(h2, h1)` over the height grid) in the new test file; (b) reword "through any alias" in tests/test_round21_e.py and DECISIONS 1066 to "through the spellings listed (plain, `import ... as`, `from ... import`, `getattr`)"; (c) PROBLEMS for D-8 (the hand reader exists only to avoid importing PyYAML into the live app image; its docstring's "refuses every line outside the grammar" is true; the `.nan` entry is inside the grammar).
test: (a) above; (b) none (words); (c) none.
What it could break: nothing in the product.
owner decision: none. sources: A-5, D-7, D-8

---

## Claims sweep (the new ask: every absolute or quantitative sentence a user sees)

Method: `ast`-extracted every non-docstring string constant of `cafe/pm/report.py` (20 hits), `credibility.py` (22), `stage1.py` (6) and `cafe/pm/physics/*.py` (8) that matches `up to | at most | cannot | never | no ray | within about | by chance | finer | no number | worst | everywhere | every | always` (the script is in the lead's scratchpad: `.../scratchpad/ext.py`, 25 lines; 56 hits, of which the ones below are the ones that make a claim about the output, the rest are error messages, CSS, receipt names or constants), then grepped the four user documents with the same words and read each hit. Rows I could only grep and not read are marked (g). Not swept line by line: the 1,054 lines of PHYSICS.md outside the RF, Iridium, certification and UAS-flag passages, the 207 lines of CREDIBILITY.md outside rows L17, L23 and the limitation list, QUESTIONS_FOR_LAB outside 12a, 18 to 20: a hit list for them is in `ext.py`'s output form and the claims lint below is what closes them.

"KEEP" means true over the whole domain, with the test or reason. "SCOPE" means rewrite to name the set it was measured on or the condition it needs. "DELETE" means remove the clause (the page is true without it).

| # | claim (short) | file:line | domain: true for | verdict |
|---|---|---|---|---|
| S-1 | "a member needing hundreds of samples cannot miss the required fraction by chance" | report.py:1829; PHYSICS 849 | required_fraction 0.95, p_success 0.95, 3 attempts, 865 samples: false at 1.0 and after the lab edits the assumed numbers (M-1) | DELETE |
| S-2 | Iridium "the same in any sea state, weather or position (no antenna height, heel or geometry enters it)" | report.py:1827-1828 | every Iridium link: `iridium_session` takes bytes, an rng, a member count | KEEP (code path; `tests/test_round16_report.py:107-110`) |
| S-3 | SAMPLING_NOTE "not of the worst case: ... larger than the median ... a finer sampling ... can find a larger one" | credibility.py:55 (printed through report.py:871,873) | pairs with a UAS-height partner; false for low pairs (M-2) | DELETE (keep "figures of the 400 sampled ranges") |
| S-4 | card tail "at a wave height of 1 to 3 m these figures are different (L23)" | report.py:~862 | three pairs measured in L23; nothing measured for the others | SCOPE ("this is for Hs 0; L23 gives three pairs at Hs 1 to 3 m") |
| S-5 | "at none of the 400 sampled ranges is the loss 3 dB off" (and the two one-sided forms) | credibility.py:49-51 | a count of a mask of the 400 samples, by construction; A, B, C: 0 counterexamples in 640, 4,000, 240 pairs | KEEP (`tests/test_round22_b.py` words follow counts) |
| S-6 | L23 "it does not stop at any height" | credibility.py:97-100; CREDIBILITY L23 cell | not measured above 1,000 m or at all heights; the card is defined 0.1 to 1,000 m | DELETE |
| S-7 | L23 / card "for any heights from 0.1 m to 1000 m" ... "nearer than 300 m none of this is stated" | credibility.py:105-109 | `rfband.valid_height`, `D_MIN_M` | KEEP (`tests/test_round21_b.py`, `test_round22_b.py` grids) |
| S-8 | L23 names: "the ship's mast" 15 m, "the USV's whip", "the Slocum" in a fixed limitation row | credibility.py:81-82, 90 | the demo's platforms; a mission with a 10 or 30 m mast prints 15 m as "the ship's mast" (C-3) | SCOPE ("the demo's"; drop for the ten generic pairs) |
| S-9 | NOT EXERCISED note "... and no number of members changes that" | stage1.py:992 (NOT_EXERCISED_NOTE; shown on the card and in `report.json`) | the members run; a larger ensemble draws other members and one may need the link | DELETE the clause |
| S-10 | Bellhop label "(no ray reached the receiver, or almost none)" and "assumed 60 dB bound" | stage1.py:689-692 | positive-sign cap only (M-3) | DELETE |
| S-11 | Bellhop label "the Bellhop excess is held within 60 dB, so it cannot change which they are" | stage1.py:678-681 | a sample more than 60 dB from pass or fail on Thorp, excess clipped to +-60: sign-preserving for both signs (C; the `far_ge` case at exactly 60 is pinned) | KEEP (`tests/test_round22_a.py`) |
| S-12 | "P(fail) < 5 % is excluded by this ensemble (lower 95 % bound ...): no number of members certifies it" | report.py:345; CREDIBILITY 66; PHYSICS (g) | at 95 % confidence only; with probability up to 5 % the bound is wrong and more members would certify | SCOPE ("at 95 % confidence") |
| S-13 | "P(fail) < 5 % cannot be certified at n = N: 73 members ... are needed (with zero failures n members only show P(fail) < 3/n, one-sided 95 %)" | report.py:347-348; RUNBOOK 187; PHYSICS 887 | `n_certify` = 73 exact (receipt "exactly 73", C recomputed: 72 gives 0.0507, 73 gives 0.04999); 3/n is above the exact 1 - 0.05^(1/n) for every n >= 1 since ln 20 < 3 | KEEP (receipt `smallest n certifying ...`, `tests/test_stats.py`) |
| S-14 | "Attitude exceedance cannot fire in this controller model (tilt clamp A, below the B exceedance)" | report.py:683; PHYSICS 756 | computed from the platform's two numbers at render; the mechanism (the commanded force clamped, uas.py:372) is read, the actual tilt (uas.py:396) not proved <= clamp for every wind; evidence is 96 of 96 q2 sorties at 35.00 deg | SCOPE ("did not fire in the sorties run; the command is clamped at A" ) |
| S-15 | L17 "UAS attitude exceedance cannot fire in this controller model (tilt clamp 35 deg, exceedance 42 deg)" | credibility.py:137; CREDIBILITY 143 | the shipped `quad_uas.yaml`; the numbers are typed, not read | SCOPE ("in the shipped quad_uas.yaml") |
| S-16 | "so the ensemble is pure physics" | report.py:2106 | no autopilot software in the ensemble; it also holds assumed inputs, fits and (stage 3) an emulator | SCOPE ("runs no autopilot software") |
| S-17 | "(the plan is a lower bound: basis)" | report.py:2087; RUNBOOK 146 ("the estimate is a lower bound") | homebase's rate table: stage 1 ran 2.2 times over (q8) and 4.2 times on the burst VM; a faster machine runs under | SCOPE ("an estimate; it ran 2.2 times over on homebase") |
| S-18 | "an uncertainty that wide cannot validate it" | credibility.py:1010; CREDIBILITY 48 | by the rule printed beside it (U_val below half the reference) | KEEP (rule is the definition) |
| S-19 | "a calibrated emulator misses it by chance with probability P on this many held-out points" | report.py:2014 | a computed number; the exact binomial is not read by any reviewer (g) | KEEP (not read; flagged for the builder to confirm it is exact) |
| S-20 | "the median moved by at most 0.59 dB and each count by at most 0.046 of 400 ... (190 pairs, two frequencies)" | RUNBOOK 190; PHYSICS 817; comms.py docstring "at most 0.52 dB" | the 190 pairs; A-3 finds 0.051 at 500 m with 132.658 m (2,440 MHz), B-4 0.7 to 0.9 dB for two UAS ends | DELETE |
| S-21 | "the largest and smallest differences of a sampled grid are the sampling's" and "the extremes keep growing as the sampling is refined" | RUNBOOK 190; PHYSICS 817 | pairs with a UAS-height partner; false for ten of the twelve pairs the platform files can make (M-2) | SCOPE ("for a pair with a high partner") |
| S-22 | "(the demo's pair of 2.2 m with 108.1 m is -10.8 to +39.2 dB at 400 points and -14.9 to +70.9 at 40,000)" | RUNBOOK 190; credibility page (g) | that pair, those two samplings (reproduced here to 0.01) | KEEP (named pair and sampling) |
| S-23 | "MINIMUM moves by up to 5.2 dB and the MAXIMUM by up to 54.1 dB" and percentiles "up to 1.35 and 3.8 dB" | PHYSICS 817; comms.py docstring | the 105 pairs sampled, 400 against 40,000 | SCOPE (name "in the 105 pairs measured"; it is the same kind of "up to") |
| S-24 | Hs 1 to 3 m cells "(the sea's roughness takes the nulls out of both curves)" | PHYSICS 817; tests/test_round22_b.py docstring | false: the three pairs have no null at Hs 0 either (B-3) | DELETE |
| S-25 | L23 Hs cells (a range and median for 0.1, 0.3, 0.5 m with 15 m at Hs 1 to 3) | credibility.py:72-78; L23 | those 9 cells, identical to 0.01 dB at 400, 4,000, 40,000 (B), reference with the Ament factor | KEEP (`tests/test_round19_b.py` recomputes to 0.1 dB); SCOPE the words "the same Fresnel two-ray ... with the Ament roughness factor" (C-3) |
| S-26 | "optimistic ... by up to 7.6 dB", "within about 8 dB at a peak is not decided by this function", "7.5 dB lower to 34.7 dB higher" | comms.py:157-161; CREDIBILITY 164; QUESTIONS 12a (130); PHYSICS 819 | one reviewer's grid at Hs 0.5 to 1.5 m; false at Hs 0 for the demo's pair (M-4); 34.7 not reproduced | DELETE (the 7.6 and the 8; the 34.7); SCOPE the "7.4 lower to 23.6 higher" (reproduced by B at 4,000 to 400,000 ranges) |
| S-27 | "at the sampled ranges the margin is too LOW, never too high, for 0.1/15, 0.3/15, ... 0.5/2.2" and "about 1 to 6, 6 to 11, 11 to 16 dB" | comms.py docstring (low-antenna paragraph) | those named pairs at 915 MHz, 400 sampled ranges; B: holds at 400, 40,000 and 400,000; no null | KEEP (`tests/test_round18_x.py` recomputes each row to 0.1 dB; names the pairs and "at the sampled ranges") |
| S-28 | `two_ray_loss_db` docstring "largest \|difference\| for d = 100 to 2000 m ... 26 dB (29)" | comms.py (docstring) | already says it is a function of the sampling; B did not re-run | SCOPE (builder: delete the figure if it is not re-measured) |
| S-29 | "Hs 0 would be a glass-calm sea, the deepest two-ray null" | stage1.py:1240 | the Ament factor is <= 1 in the model and the Fresnel reference, so roughness only reduces \|R\| | KEEP (physics monotone; `tests/test_round19_b.py` Hs cells) |
| S-30 | "Level 4 is never awarded" | credibility.py:37; CREDIBILITY 24, 34 | the rule code awards at most 3 | KEEP (`LEVELS`, cap in code) |
| S-31 | "every number links to a receipt, which is a hashed ledger output, a ledger check, or a group of model receipts" | report.py:2167 | `_PATHS` self-check at render (report.py:2213-2222) | KEEP (the render-time self-check) |
| S-32 | "links GO except glider acoustic at more than 3 km" | credibility.py:213-214 | BRIEF 6 for the demo only; the line says it applies to that mission only | KEEP |
| S-33 | "A GO from a budget below 73 members says so in its note; the Uncertainty factor cannot reach 3 there" | CREDIBILITY 203; RUNBOOK (g) | when some verdict leaves P(fail) < 5 % open; a run whose every verdict has its lower bound above 5 % or is NOT EXERCISED has no open verdict | SCOPE ("while a verdict leaves P(fail) < 5 % open") |
| S-34 | "an integer too large for a float in ANY YAML file ... exits 2 with `error:`" | RUNBOOK 100 | false for 4,301-digit decimals, 4,000-digit hex and a list key (M-6) until the fix | SCOPE now; KEEP after M-6 with its test |
| S-35 | "(555 and 633 km)" demo acoustic distances | RUNBOOK 189, 58 | q23's medians 554.7 and 632.45 km | SCOPE (632; or "about 150 times the 4 km range") |
| S-36 | "The lowest margin is conservative for the transmitter depth" | RUNBOOK 189 | the lowest of a run set is lower than each run, for the pair of depths run; not for the depth flown (M-3's own sentence in the same line says a Thorp fail can become a pass) | DELETE |
| S-37 | Bellhop reversal counts "7 of 87, 82 of 87 and 87 of 87" on three made-up profiles; cost "0.25 s to 6 km, 2.2 s to 20 km, 6.8 s to 40 km (orca, 2 CPUs)" | RUNBOOK 189; PHYSICS 836, 838 | the named profiles and machine | KEEP (set named, dated) |
| S-38 | "q8 ran 2.2 times over; the 45 % and the 2.2 stay as homebase's figures" | RUNBOOK 146 | homebase, q8, dated, machine named | KEEP |
| S-39 | "9 members without a failure are GO whatever `go` is" | RUNBOOK 104 | the 90 % Wilson lower bound of 9 of 9 is 0.769 (8 of 8: 0.747), my arithmetic; point estimate 1.0 meets any `go` <= 1 | KEEP (arithmetic; add a test row if none) |
| S-40 | "in short steep seas the boat is credited 0.57 m/s it cannot make, so `becalmed` and `swept_off_track` are under-reported in exactly those sea states" | CREDIBILITY 156 | one case (Hs 2 m, Tp 6 s); "exactly those" is not measured | SCOPE (drop "in exactly") |
| S-41 | demo distances "555 and 598 km", "the USV up to 111 km" | QUESTIONS 122 | the demo as measured at some run (g); 598 does not match q23's 632 | SCOPE (name the run or delete the numbers) |
| S-42 | "the best heading avoids [the V = 0 cells] from 15 m/s" and "658 of 2759 cells" | CREDIBILITY 171 (g) | the table at some commit | SCOPE (name the commit) (not read beyond the line) |
| S-43 | "the model's loss minus the Fresnel loss is described by its median and by how many of the sampled ranges are more than 3 dB off"; the median is "signed: positive, the loss is overstated" | report.py:859; credibility.py:40-71 | definitions of the printed numbers | KEEP (`tests/test_round22_b.py`; recomputed by C against an independent Fresnel) |

Counts: 43 rows. KEEP 17 (S-2, 5, 7, 11, 13, 18, 19, 22, 27, 29, 30, 31, 32, 37, 38, 39, 43; S-25 is KEEP with a SCOPE of its words and is counted under SCOPE), SCOPE 17 (S-4, 8, 12, 14, 15, 16, 17, 21, 23, 25, 28, 33, 34, 35, 40, 41, 42), DELETE 9 (S-1, 3, 6, 9, 10, 20, 24, 26, 36). That is 17 + 17 + 9 = 43. Rows that rest on a reviewer alone: S-5 (A, B, C ran counterexample searches), S-25 and S-27 (B's 400,000-range runs), S-35 (C), S-28 (nobody this round); rows I measured: S-1, S-3 (low pairs), S-20, S-26 (at Hs 0), S-39.

**The claims lint (S-lint), a test that fails when a new member appears.** Not a row but the class fix: a new test `tests/test_round23_claims.py` extracts, as `ext.py` does, every non-docstring string constant of `cafe/pm/report.py`, `credibility.py`, `stage1.py` and `cafe/pm/physics/*.py` and fails on any that matches `up to|at most|cannot|never|no ray|within about|by chance|finer|no number|worst|everywhere|every|always` unless the pair (file, first 60 characters) is in a reasoned allow-list (the KEEP rows above are its first 17 entries; every other hit of the 56 is an error message, a constant or a receipt name, which the builder lists with the reason "message", "constant" or "receipt"); it also fails on an allow-list entry that no longer matches (stale). A second half does the same over the five documents with the narrower phrases `up to [0-9]`, `at most [0-9]`, `by chance`, `no number of members`, `within about`, with the DECISIONS-dated rows as its allow-list. It adds no product code. What it does not prove: that an allowed sentence is true (the KEEP column says why), only that no new absolute lands unreviewed.

---

## Open decisions (the lead takes the defaults)

- OD-1 (M-2): the sampling note. Options: (a) keep only "figures of the 400 sampled ranges" (delete the worst-case hedge); (b) condition the hedge on the pair (new code); (c) leave it (over-warning on the low pairs). Default: (a). The lead should know that (a) takes away the only sentence that tells a reader of a UAS-pair card that a finer sampling finds larger errors; RUNBOOK 190 and L23 keep the measured -10.8 to +39.2 / -14.9 to +70.9 for the demo's pair as named measurements.
- OD-2 (M-4): the 7.6 dB figure. Options: (a) delete in the four places, keep the 7.4 / 23.6 figures scoped to the one grid; (b) scope it to "Hs 0.5 to 1.5 m, 2.2 m with 108.1 m, 0.2 km to the horizon, one grid" and keep it; (c) re-measure at Hs 0. Default: (a).
- OD-3 (M-8): body-shape guards in `live_create`/`check_fleet`. Default: do it (one guard each). Alternative: PROBLEMS.
- OD-4 (M-9): which of the three unguarded readers to guard. Default: `budget.throughput` only (the one that silently shrinks every verdict's n); D-3 and D-5 to PROBLEMS with the reachability said.
- OD-5 (sweep): the claims lint. Default: yes (test only, no product code). Alternative: no lint, only the 26 edits (SCOPE or DELETE rows): the next round's reviewers then find the next absolute.
- OD-6 (round shape): round 24 restricted to the edits below plus the lint (no new printed sentence and no new constant on an output). Default: yes.

---

## Batches (non-overlapping by file; builders in parallel; D last; E after A and B)

Contracts: the L23 cell of `docs/CREDIBILITY.md` is pinned equal to `credibility._l23_text()` and `tests/test_config_docs.py` pins phrases of CREDIBILITY, QUESTIONS and the comms docstring, so every text change of the RF band lives in batch B with its pins; `NOT_EXERCISED_NOTE` is read by report.py and credibility.py by import, not by copy.

### Batch A: stage 1 labels
- findings: M-3, S-9, S-10
- files: cafe/pm/stage1.py, tests/test_round21_a.py, tests/test_round22_a.py (the pins of "no ray reached", "dB bound", the label property test), tests/test_stage1.py (if it pins NOT_EXERCISED_NOTE), tests/test_round23_a.py (new: the label never contains "ray", "almost", "bound" for every `info`; the note has no "no number of members")
- must fail before: a label with `capped > 0` carries a cause; the NOT EXERCISED note ends with "no number of members changes that".
- notes: does not touch comms.py.

### Batch B: report, credibility and the RF-band texts with their documents
- findings: M-1, M-2, M-4, M-5 (code and text part), S-1, 3, 4, 6, 8, 12, 14, 15, 16, 17, 20 (the PHYSICS and comms part; RUNBOOK 190 is batch G), 21, 23, 24, 25, 26, 28, 33, 40
- files: cafe/pm/report.py, cafe/pm/credibility.py, cafe/pm/physics/comms.py (docstring only), docs/CREDIBILITY.md, docs/PHYSICS.md, QUESTIONS_FOR_LAB.md, tests/test_report.py, tests/test_credibility.py, tests/test_round16_report.py, tests/test_round18_a.py, tests/test_round19_b.py, tests/test_round20_b.py, tests/test_round21_b.py, tests/test_round22_b.py, tests/test_comms.py, tests/test_config_docs.py, tests/test_round23_b.py (new: the IRIDIUM_NOTE and SAMPLING_NOTE words over the height grid and the three required fractions; `band_figures` "-0.0"; the "7.6 dB" lint)
- must fail before: IRIDIUM_NOTE contains "cannot"; the card contains "worst case" and "these figures are different"; the docs contain "up to 7.6 dB"; `band_figures(-0.04, ...)` prints "-0.0".
- notes: documents the model's RF behaviour only; no number on the page moves except by the text edits. The hand-back says which of S-14 to S-17 it changed to what wording and which pins moved.

### Batch C: the YAML boundary and the stored vector
- findings: M-6, M-7
- files: cafe/pm/config.py, cafe/vehicle.py, tests/test_config.py, tests/test_round22_c.py, tests/test_vehicle.py, tests/test_round23_c.py (new: digit counts, list keys, missing keys)
- must fail before: a 5,000-digit integer is a ValueError; `_vec3({}, "force", "+x")` is a KeyError.
- notes: the message of `_finite` for an oversized integer changes if the bit count is used: the hand-back lists the tests that pin the old text.

### Batch D: app, live, budget
- findings: M-8, M-9 (D-4 only, per OD-4)
- files: cafe/app.py, cafe/live.py, cafe/pm/budget.py, tests/test_app.py, tests/test_live.py, tests/test_budget.py, tests/test_round23_d.py (new: the body-shape table; the throughput leaves NaN, inf, 0, -1)
- must fail before: `live_create({"drones": "abc"})` raises AttributeError; `plan` with a NaN rate returns a plan.

### Batch E: the claims lint and the symmetry test (tests only; runs after A and B have landed)
- findings: S-lint, M-10 (a), (b)
- files: tests/test_round23_claims.py (new), tests/test_round23_e.py (new: `pair_band` symmetric in the two heights), tests/test_round21_e.py (the "through any alias" wording)
- must fail before: the lint fails on every row marked DELETE or SCOPE that is still on the tree (so it is run last and is green only when A, B and C have landed).

### Batch G: documents (last)
- findings: M-5 (RUNBOOK part), M-10 (c), S-20, S-34, S-35, S-36, S-41, S-42, and every document a code batch changed
- files: docs/RUNBOOK.md (52 and 58 stay; 100: stays true after C, named test; 146: S-17; 189: S-35, S-36; 190: S-20, S-21, no "worst case"), DECISIONS.md (new rows numbered after the last (1069 is the last named in round 22), one per decision above; amend 1066 "through any alias"), CHANGELOG.md, PROBLEMS.md (D-3, D-5, D-8, the 0.92 dB figure not reproduced, B's N-3 stage-1 `_eval` dead-run tack, "q25"), STATUS.md, HANDOFF.md, QUESTIONS_FOR_LAB.md only for 122 (S-41: if batch B did not take it; B owns 12a and 20a)
- must say: the stop-rule count is 0 after round 23; the sweep's counts (KEEP 17, SCOPE 17, DELETE 9, over 43 rows); q25 against q24 in every existing value (text only: the RF cards, L23, the Iridium note, a Bellhop label if one ran); the number of members, verdicts, intervals do not move.

---

## Totals

- Findings: 10 merged from 20 source ids, plus the points found here (the card tail S-4, S-9, S-12, S-14 to S-17, S-33 and others in the sweep). By severity: 0 critical, 0 major, 10 minor.
- By status: confirmed 10 (reproduced on orca: M-1, M-2, the A-3 half of M-5, M-4's figures; by reading: M-3, M-6 to M-10); refuted 0; not reproduced: B-4's 0.92 dB and 28 of 400 (inside M-5).
- Wrong data: yes 4 merged (M-1, M-2, M-3, M-4; source ids A-2, B-1, B-2, C-1; all four reviewer ratings hold); no 6. Wrong data by round: 5, 3, 5, 7, 4.
- Claims sweep: 43 rows; KEEP 17, SCOPE 17, DELETE 9.

**Stop rule.** Round 23 is NOT clean. The stop-rule count of consecutive clean rounds is 0 (it was 0 before). Two in a row are needed.

## Not covered (by any reviewer or by this merge)

- This merge: real Bellhop and GOFS (M-3 is by reading), B's two-UAS 0.92 dB, `app.js` in a browser, any HTTP client, the Hs 0.5 to 1.5 m grids behind the 7.4 / 23.6 figures at other pairs, the stage-3 and emulator sentences of the report not named above, the PHYSICS and CREDIBILITY passages outside the grep.
- Reviewers: A did not run `make mutation`, the sample of round 21, 20 and 19 mutants, `app.live_step`, `check_fleet`, `scan_source`'s allow-lists; B did not run a GOFS profile, a two-UAS link or an Iridium `surfacing` link through a real batch; C did not run q24 (it did not exist), the Stage-1 flip texts, `whatif`; D did not run a real `live.step`, `write_store` with kills, any HTTP client, a browser or any stage 1 with a NaN coefficient.

## Convergence

My honest view. Wrong-data findings per round are 5, 3, 5, 7, 4: smaller, not zero, and the shape is now narrow and uniform. All four of this round are printed absolutes or causes that are true for the demo or one grid and false elsewhere ("cannot miss ... by chance", "a finer sampling can find a larger one", "no ray reached", "up to 7.6 dB"); none is a number computed wrongly. Round 22's fixes narrowed claims and added three new sentences (the Iridium clause was old; the sampling note, the Bellhop label cause and the stability figures were round 21 and 22's), and each new sentence was attacked and three of four fell. The pattern says: every sentence a round leaves on an output is a new claim, and the reviewers find the pair of inputs where it is false.

What to roll back to a simpler honest statement, in order of value:
1. The sampling note (M-2): roll back to "figures of the 400 sampled ranges". The "worst case / finer sampling" hedge was added to protect the reader from the extremes it had just stopped printing; it is true only for pairs with a UAS partner, and for them the page already prints the counts. This is the one place where a hedge did harm.
2. The Bellhop cause (M-3): roll back to a count and a cap with no cause.
3. The three "no number of members ..." / "cannot ... by chance" absolutes (S-1, S-9, S-12): each is true in the demo and an inference at 95 % or an assumption elsewhere.
4. All "at most N" and "up to N" figures measured on a sample (S-20, S-23, S-26): a figure measured on 190 pairs does not become the card's accuracy by being named; delete it, and keep only named measurements of named pairs (S-22).
5. Not a roll-back, but keep: the live RF band (median and two counts), refine-every-sample Bellhop and the subset sensitivity: no round-23 reviewer found a wrong number in any of them (C recomputed every card and L23 figure independently, and the 400-point counts equal A's, B's and my runs).

Can round 24 be clean if this sweep is done? Honestly: it can be, with two conditions that I cannot promise. (1) The sweep's 26 edits (17 SCOPE, 9 DELETE) must really leave no new sentence: each SCOPE row adds a scope clause ("in the shipped quad_uas.yaml", "at 95 % confidence", "the demo's") and a scope clause is a claim a reviewer can test; prefer the DELETE reading wherever the page is true without the clause (S-4, S-15, S-16, S-17, S-40 can be deleted outright and I would). (2) The sweep is by grep over strings and over four documents I only partly read: 56 string hits and about 40 document lines were judged, and the 1,054-line PHYSICS.md and the report's stage-3 and emulator paragraphs were not read; that is why the lint is in the batches: it turns "a reviewer finds the next absolute" into "a test names it". The robustness findings (M-6 to M-9) are the other half of what reviewers find each round and are not what the stop rule is about; they will continue to appear at the rate of about 8 a round (D found 8) until the YAML, vehicle and app boundaries are enumerated, and the owner's rule does not count them. If round 24's reviewers find only robustness items and no printed claim, the round is clean on the rule. If the lead wants a better chance, the cheapest extra step is to give round 24 reviewer C the lint's allow-list and ask only "which KEEP row is false", since the allow-list is the complete set of absolutes a user can see.
