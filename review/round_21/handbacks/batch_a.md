# Round 21, batch A hand-back (builder; branch r21-a, cut from premission-step4 at 7599881)

Findings: M-1 (stage-1 part), M-3, M-4, M-10, the `ACTING` comment of M-14. Files touched: `cafe/pm/stage1.py`, `cafe/pm/physics/comms.py`, `tests/test_stage1.py` (two pins), `tests/test_round20_a.py` (four pins), `tests/test_round21_a.py` (new), this file. `platforms/modems.yaml` is NOT touched (OD-3 (a)).

## LOUD (read these first)

1. **M-3 is ruled MAJOR (the lead's ruling, carried into the decision text below): a Thorp pass that Bellhop turns into a fail is a wrong verdict.** On the real CI fixture the first real `run_batch` I could make moved a member the OTHER way (see "Real run_batch"): Thorp said fail, Bellhop said pass, at 8 km. The class is "Thorp decides wherever it is outside +-6 dB", in both directions.
2. **The cost of M-3 is not "2 to 3 times the runs" for a real link.** The merge's argument ("the cost per member is the same four runs whether the call carries 1 sample or 400") is true of the NUMBER of runs and false of their TIME: a Bellhop call takes about 0.2 s to 6 km, about 1 s to 12 km, 2.1 s to 20 km and 6.1 s to 40 km (measured, below), and the 48-point range grid is spread over the whole span of the member's needed samples. A member whose needed samples run 0.1 to 20 km now costs about 6 runs x 2 s where it cost about 4 runs x 0.2 s: the real `run_batch` at a 20 km ship distance went from 5.6 s to 53.2 s for 4 members. The same 48-point grid over 0.1 to 40 km differs from a grid at every 100 m by a median 0.7 dB, p90 4.0 dB and at most 17.2 dB in the excess (tropical profile; 4 to 11 of 400 samples change the SIGN of the excess; 0.0 to 0.1 dB median on the other two profiles). I did NOT cut the fix (lead's instruction). Two cheap, verdict-neutral options for the lead, NOT implemented (hunks at the end): (i) skip a sample whose Thorp margin is beyond +-`BELLHOP_EXCESS_CAP_DB` (the excess is held within +-60 dB, so such a sample cannot change sign; it would keep the Thorp margin and the span of MF refinement would end at 18.4 km, HF at 10.6, LF at 38.4: measured margin = -60 dB distances); (ii) scale `bellhop_tl`'s `n_grid` with the span (the time per call is nearly independent of `n_grid`: 11.7 s against 12.2 s for 400 ranges at 40 km).
3. **The 60 dB cap is an ASSUMED number** (labelled so in `comms.py`, in the label of a link and here): the largest finite excess in the merge's 45 cases was 56 dB, and a real shadow is thought to be 20 to 40 dB down. It needs one QUESTIONS_FOR_LAB sub-item with the default 60 (batch G).
4. **The 5 m floor is a choice measured on made-up profiles** and says less than the merge thought: see "What the 5 m floor rests on".
5. Commit attribution: the commits end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>` (the model that wrote them), not the `Fable 5.2` line of the brief.

## Commits (on r21-a)

See `git log 7599881..r21-a`: one for code and tests, one for this hand-back.

## What changed and why

### M-1 (stage 1): the members that needed the link (`stage1.summarize`, `_sensitivity`)
- ONE mask in `summarize`: `n_needed = #(need_count > 0)`, `on = need_count > 0` (all members where there is no `need_count`, or where no member needed the link, the NOT EXERCISED case keeping the all-member values). `_sensitivity(names, U[on], f[on], acting, frac[on], ..., total=n)`, `frac_median` and `frac_p10` over `frac[on]`; the verdict, `k_fail`, `granularity_ok`, `need_count_median`, `margin_db_median` (NaN where not needed already), the stopping rule are unchanged. The `_sensitivity` call keeps its signature for the first six arguments and gains the keyword `total` (the members of the run): only then the texts say "among the 18 of 48 members that needed the link", "The link was needed in only 10 of 48 members: at least 16 are needed to rank the parameters." and "Every member that needed the link failed". With no member excluded every text is byte-for-byte the old one.
- `censored`: `_sensitivity` records `censored = dict(share, at="min"|"max", value)` for ANY continuous ranked quantity with more than half of its finite rows at the minimum or the maximum (all equal: `max`, share 1.0). Absent for the 0/1 failure indicator (mostly zeros by nature), for a case with no index (all_pass, all_fail, too_few, no_acting_input) and when half or fewer sit at one value (exactly half is not censored). It is on vehicles as well as links, so round 20's USV-only clause can be generated from it (batch B).
- Contract keys, exactly as batch B reads them: `links.<id>.n_needed` (int; None for a result with no `need_count`), `links.<id>.sensitivity.censored` (dict or absent), `links.<id>.bellhop_spread_db_median` (float or None; the key exists only for an acoustic link). One real example, from the CI fixture run below (ship 3 km from the station, 4 members, real Bellhop), full link entry:

```json
{"bellhop_spread_db_median": 5.5250443700867535, "distance_km_median": 3.7631983155800337, "frac_beyond_horizon": null, "frac_median": 0.775, "frac_out_of_range": 0.0, "frac_p10": 0.575, "granularity_ok": false, "k_fail": 3, "margin_db_median": 6.530348690733064, "margin_kind": "acoustic link margin, dB", "method": "Thorp/Stojanovic budget on the slant range, Bellhop on 20 of 20 needed in-range samples (the lowest of 3 runs: as named, swapped, both ends at least 5 m deep)", "n": 4, "n_needed": 4, "n_never_required": 0, "need_count_median": 5, "sensitivity": {"S1": {}, "case": "too_few", "noise_floor": null, "param": null, "quantity": "fraction of the required moments the link worked", "text": "Only 4 members: at least 16 are needed to rank the parameters."}, "verdict": {"conf": 0.9, "fail_hi": 0.9420926788001414, "fail_lo": 0.3561680085985064, "k_fail": 3, "method": "wilson", "n": 4, "n_certify": 73, "note": "", "p_fail": 0.75, "success_lo": 0.05790732119985864, "verdict": "NO-GO"}}
```
  (a `censored` entry looks like `"censored": {"at": "max", "share": 0.75, "value": 1.0}` inside `sensitivity`).

### M-3 (ruled major): every needed in-range sample is refined (`stage1._acoustic`, `evaluate_link`)
- `refine = need & valid` (`valid` = within `comms.valid_range_m`, now computed once in `evaluate_link` and passed in) replaces `amb & need`. `_bellhop_member` calls `comms.acoustic_link(..., ambiguous_db=np.inf)` so the helper's own band does not cut the samples it is handed; the helper's band semantics, its default and `modems.yaml` are unchanged for every other caller. Every old-refined sample is a new-refined sample (within +-6 dB is within about 5.5 km, far inside the valid range), so the new set contains the old one.
- The band stays only where Bellhop is not available: the samples keep the Thorp margin and the label is the old `THORP_ONLY_LABEL (n ambiguous samples)`.
- Depth approximation (M-3 foresight 4, read and changed): one profile and one depth pair per member and link stays, but the pair is now the MEDIAN transducer depths of the member's refined samples (was: the middle sample's), because with every needed sample refined a link `when: always` to a submerged glider spans its dive cycle and the middle sample is an accident. The profile position and time stay those of the middle sample. The `ponytail:` comment in `_acoustic` says so. A NaN depth is not reachable: `valid` is False for a NaN slant range, so such a sample is out of range and never refined (tested).
- The label counts all members of the run (new, a sibling found here): `merge` kept `l0["method"]`, the FIRST batch's label, so "Bellhop on 434 of 434 ..." described 32 of 64 members. `evaluate_link` now returns the count (`bellhop` = dict(done, total, capped, runs_lo, runs_hi)) and `merge` rebuilds the label from the sums with the same function (`_bellhop_label`). Where no batch refined anything the first batch's label is kept as before.

### M-4: the run set and the spread (`stage1._run_set`, `_bellhop_member`)
- Set = as named, swapped, both ends floored at `comms.BELLHOP_MIN_DEPTH_M = 5.0`, de-duplicated in that order: (1,1) -> 2 runs ((1,1), (5,5)); (5,5) or any equal pair from 5 m -> 1; (1,5) -> 3; (5,300) -> 2; (4.999,5) -> 3. Each run is `acoustic_link`, i.e. a profile call and an isovelocity call: 2, 4 or 6 `_run_bellhop` calls per member.
- Margin = the lowest of the set per sample (`np.fmin`, a run with no number does not hide the others). `spread` per sample = max - min of the set, NaN where fewer than two runs gave a finite number, so a member whose set is one run states NO spread (a 0.0 there would read as "converged"). `bellhop_spread_db_median` = the median over the finite spreads of the needed samples, None where there is none (no Bellhop, one-run sets).
- Label: "(the lowest of n runs: as named, swapped, both ends at least 5 m deep)" (n, or "2 to 3" where members differ) only where some member ran more than one run: not where Bellhop could not refine (A-3's mutant: tested), not for one-run sets.
- `_bellhop_member` now returns a `_Refined(margin, spread, runs, capped)` or None (was an array or None).

### M-10: the excess held at an assumed bound (`comms.acoustic_link`)
- `BELLHOP_EXCESS_CAP_DB = 60.0` (ASSUMED). The excess `tl_b - tl_i` is clipped to +-60 in BOTH directions (a zero field in the isovelocity run would be a gain of 540 dB, a pass nobody can believe; the merge asked for the upper side only) and `acoustic_link` returns `capped` (bool per sample). `_run_bellhop` is unchanged (its 600 dB floor is pinned by `test_r8_m40_the_loss_is_minus_20_log10_...`): the clip in `acoustic_link` covers a zero field and any other huge excess in one place. The label says how many samples were held ("; 12 of them held at the assumed 60 dB bound on the Bellhop excess (no ray reached the receiver, or almost none)"), a sample once however many runs hit it. A capped sample is a fail with or without the cap where the Thorp margin is not above +60.
- The M-10 mechanism and the M-3 prerequisite: not reachable through the +-6 dB band in the merge's probes, and certain once every sample is refined.

### The ACTING comment (M-14, B-5)
`stage1.py` above `ACTING`: the trim is no platform value (2 x `vbd_delta_cc` + the neutral-VBD spread at the start: 138 cc on the demo, 150.86 in B's toy), the surfacing arithmetic now uses the demo's 138 cc throughout (34.96 J, 1743.96 J, 1.6148e-4 of 1.08e7 J; the old sentence mixed 150.83 cc and 138 cc), the apogee step "was seen in reviewer B's toy (5 of its 18 steps) and not on the demo".

## Evidence

### Fail before / pass after (job names, rc)
"Before" = detached worktree `../cafe-r21a-base` at 7599881 with only `tests/test_round21_a.py` added, orca `pm_r21a_base2`, job `r21a_b2` (first draft of the file, 44 of its tests failed there, rc=1): the behavioural failures are M-1 (`wind_speed_bias` ranked where `hs_scale` is right; `too_few` and `all_fail` not reached; `n_needed` absent), M-3 (`calls == []`: a +25 dB sample never reached Bellhop; `Thorp budget decides every link` where "Bellhop on N of N needed in-range samples" is expected; depth (300, 5) was used where the median is (5, 5)), M-4 (`[(1.0, 1.0)]` only for two 1 m ends; the label absent) and M-10 (margin Thorp - 60.01 against Thorp - 60 at 60.01 dB of excess; no `capped`). The others fail for the missing names (`_censored`, `_run_set`, `capped`, `bellhop_spread_db`).
FINAL_COUNTS

### Runtime (orca, 2 CPUs, proot)
- Test files with a FAKE Bellhop (the CI link tests are of this kind; none of them runs the real one, `CAFE_DATA` is private in pytest so `bellhop_available()` is False there): TIMING
- A REAL `run_batch` on the CI fixture, link `glider_eq-ship-acoustic` (benthos MF, `when: surfacing`), glider_eq alone, the ship moved to km km from the glider's station, 4 members, real Bellhop, script `r21a_batch.py` (jobs `r21a_bb` before, `r21a_ba` after):

| ship km from station | `_run_bellhop` calls before / after (per member) | wall before / after | frac per member before | frac per member after | k_fail before / after | verdict |
|---|---|---|---|---|---|---|
| 1.5 | 16 / 24 (4.0 / 6.0) | 8.9 s / 12.7 s | 0.8, 0.667, 0.75, 1.0 | the same | 3 / 3 of 4 | NO-GO both |
| 3 | 16 / 24 | 8.0 s / 11.6 s | 0.8, 0.5, 0.75, 1.0 | the same | 3 / 3 | NO-GO both |
| 5 | 12 / 24 (3.0 / 6.0) | 8.1 s / 12.9 s | 0.6, 0.0, 0.75, 1.0 | the same | 3 / 3 | NO-GO both |
| 8 | 0 / 24 | 5.6 s / 17.0 s | 0.0, 0.0, 0.0, 0.4 | 0.0, 0.0, 0.0, 1.0 | 4 / 3 | NO-GO both (member 3: Bellhop turns Thorp's fail into a pass) |
| 20 | 0 / 24 | 5.6 s / 53.2 s | all 0.0 | all 0.0 | 4 / 4 | NO-GO both |

  Calls per member: 0 where no sample was in the band (before), otherwise 4 (the two directions, profile + isovelocity each); after: 6 for the CI glider (1 m) beside the ship's 5 m transducer (three runs), 4 for unequal pairs from 5 m, 2 for equal pairs from 5 m. The verdict class did not move on any of the five; one member's pass fraction did (0.4 to 1.0 at 8 km), in the direction of a PASS: the CI ocean has a surface duct and the excess is a gain, not the shadow of the merge's made-up profiles. `bellhop_spread_db_median` there: 3.0, 5.5, 3.4, 3.6, 2.7 dB (a printed number for what the run set disagrees by).
- One Bellhop call by span (18.5 kHz, 4000 m, 48 receiver ranges from 100 m, `r21a_span.py`, job `r21a_span`): 6 km 1.4 s (first call, includes the import; 0.23 s warm in `r21a_floor.py`), 12 km 0.9 s, 20 km 2.1 s, 40 km 6.1 s. Thorp margin at which distances (wind 6 m/s): MF +6 dB at 3.2 km, 0 at 4.3, -6 at 5.5, -60 at 18.4; LF -60 at 38.4; HF -60 at 10.6; `valid_range_m` 60 / 40 / 20 km.

### What the 5 m floor rests on (job `r21a_floor`, rc=0)
Real Bellhop through `comms.bellhop_tl`, reviewer B's THREE made-up Mackenzie profiles (`v21/v1.py prof`: tropical, sharp thermocline, Munk-like), 4,000 m water, ranges 2 to 7 km every 100 m, band centres 11.5, 18.5, 24.5 kHz, `|TL(pair) - TL(10 m, 10 m)|` mean / max in dB, (transmitter, receiver) depths:
- sharp thermocline, 18.5 kHz: (1,1) 48.3 / 55.9; (2,2) 25.4; (3,3) 13.5; (4,4) 12.3; (5,5) 0.1 / 1.8; (6,6) 0.1; (8,8) 0.1 / 2.6; (20,20) 0.2; (1,5) 12.1 / 20.8; (5,1) 0.3 / 1.0; (4,5) 9.9; (5,4) 0.1 / 1.8; (1,2) 25.3; (2,1) 47.0. At 11.5 kHz the same pattern; at 24.5 kHz (5,5) is 1.2 / 13.4 and (8,8) 2.7 / 9.7, so HF is not converged to 1 dB at any depth.
- Munk-like: converged from 3 m (0.0 dB at 18.5 kHz), (1,1) 0.3, (20,20) 4.1 (physical, not convergence). Tropical: every pair differs from (10,10) by 2 to 6 dB (3.2 for (5,5)): a depth effect in a noisy field; nothing is "converged" there to 1 dB.
- The finding the merge did not make: the non-converged runs are the ones with a SHALLOW TRANSMITTER ((1,5) 12.1 against (5,1) 0.3; (4,5) 9.9 against (5,4) 0.1); a shallow receiver is harmless. The set (named, swapped, both floored) always contains a run with a transmitter of 5 m or more, so it is sufficient; flooring only the transmitter would also be, and would not model a 1 m receiver at 5 m. Not changed (the brief's set).
- Where the spurious runs are on the optimistic side (sharp: TL below the converged one by 6 to 48 dB) the lowest margin discards them; tropical (1,1) is 3.8 dB BELOW (10,10) and (1,5) 4.1 dB above: there the lowest picks whichever is lower and the printed spread is the honest number.
- A surfaced glider (1 m) is modelled at 5 m in the floored run: a documented conservative approximation (deeper = higher TL on the profiles measured), not a claim of physics.

## Siblings (grep and what I did)

| sibling | where | decision |
|---|---|---|
| a link label with counts of the FIRST batch only | `merge` (`method=l0["method"]`) | fixed here: counts and run range are summed in `merge` and the label rebuilt |
| `need_count_median` / `granularity_ok` are medians over ALL members (zeros of never-needed members included) | `summarize` | NOT changed: they are defined as "the median member" (round 16 M-4, read by the report's "in the median member" sentence); changing them moves `granularity_ok` for a partly-needed link. A statistic about a link that ignores who needed it, same class as M-1: lead/owner decision (a needed-members median is a one-line change) |
| label "Thorp only, no sound-speed profile supplied" printed when Bellhop IS available and a profile exists, because the helper's call without a profile finds an UNNEEDED sample in the band | `_acoustic`, the no-refine path | NOT changed (q22's text must not move; it needs an unneeded in-band sample and no needed in-range one). Seen in the real CI run before the fix at 8 km (the label said "no sound-speed profile" with a profile present); the new path labels that case correctly |
| the same `acoustic_link` called by anything else | grep: only `stage1._acoustic`/`_bellhop_member` and tests | none |
| the cap applies to `acoustic_link`, `bellhop_tl` and `_run_bellhop` do not | `comms` | by design (above) |
| other quantities that read all members: `margin_db_median`, `distance_km_median`, `frac_beyond_horizon`, `frac_out_of_range` | `summarize` | already needed-samples only (NaN or ratios over `need`): safe |
| vehicles' sensitivity | `summarize` | members all exist for a vehicle: no `total` |

## Hostile review of my own fix (what I tried)
- Boundaries: 15 and 16 needed members (`SENS_MIN_N`); exactly half and one more than half of 10 and 11 rows at the extreme; all equal; both ends holding values (the larger share wins); NaN rows (the share is of the finite ones); an excess of 59.99, 60.0, 60.01, -59.99, -60.0, -60.01, +-540 and NaN; depths 4.999 / 5.0 / 5.001; (1,1), (5,5), (7,7), (1,300) and (300,1); a sample exactly out of range (45 km) and just in (39 km); a NaN depth.
- The other order of arguments: a = ship b = glider gives the same margin and the same spread (tested for 1 m ends); the run set has the same members either way.
- Printed but should not be: "lowest of n runs" with no profile, with Bellhop unavailable, with a one-run set; "held at" with 20 dB of excess; "among the n of N members" with nobody excluded; the spread key on a link that is not acoustic. Not printed but should be: the label of a merged run whose FIRST batch refined nothing; the cap for a gain.
- Reverse cases: a Thorp FAIL far below the band refined and passed by a gain (km 12, -30 dB); a member with no profile among members that have one (partial count, the rest Thorp only).
- Not attackable by a test, found by measurement: the span cost and grid spacing (LOUD 2).
- ruff and mypy --strict clean (job `r21a_lint2`: `All checks passed!`, `Success: no issues found in 55 source files`); `audit.banned()` 0 hits (job `r21a_ban`); my new statements in `stage1.py` and `comms.py` are all run by `test_stage1`, `test_round20_a`, `test_round21_a`, `test_comms`, `test_comms_exact` (job `r21a_cov`: the six lines missing there are old error branches covered elsewhere: comms 285, 301, 303; stage1 730, 938, 1187).

## Pins moved (and why)
1. `tests/test_stage1.py::test_a_clear_acoustic_link_never_reaches_bellhop` -> `test_an_out_of_range_acoustic_link_never_reaches_bellhop` (km 45): the pin WAS the M-3 behaviour (a Thorp margin above +6 dB, no Bellhop call). The new pin keeps what is still true (beyond `valid_range_m` nothing is refined); the +6 dB case is pinned the other way in `test_round21_a.py`.
2. `tests/test_stage1.py::test_the_method_of_an_acoustic_link_is_a_string_...`: `bellhop_available` is patched False (the test is about the label's type; with Bellhop present every needed sample is now refined and its fake `acoustic_link` takes no profile). No assertion changed.
3. `tests/test_round20_a.py`: the set of Bellhop depth pairs gains (5.0, 5.0); the label is the new text ("needed in-range samples (the lowest of 3 runs: ...)"); the clipped-depth run list gains the 5 m run; `m` is a `_Refined` (`m.margin`); one `"lower of the two" not in` becomes `"lowest of" not in`. No margin assertion changed: the lowest of three is the same -2.0 / THORP - max(...) because the added run is the deep-sends one.
No assertion about a margin or a count of failures was weakened.

## Hunks / lines for other batches
- Batch B's test files (`test_round17_a/m`, `test_round18_a/m`): RESULT_B. Nothing of mine is needed in `report.py`/`credibility.py`: keys are as the contract says.
- Batch G, exact sentences (file, line at 7599881):
  - `docs/PHYSICS.md:832` ("Bellhop's two directions ...") says "outside the ambiguous band the two orders were identical" and "can turn a pass into a fail, never the reverse": both false after this batch. Replace by: the run set (as named, swapped, both ends at least 5 m deep, de-duplicated; the lowest margin; the spread printed), B-1's cause (Bellhop's incoherent TL is not converged for a transmitter shallower than about 5 m; a shallow receiver is harmless; measured in `review/round_21` on three made-up profiles, numbers above), "the lowest of the set is biased low and can turn a pass into a fail; a refined Thorp pass can also become a pass of a Thorp fail (a duct)", the cap.
  - `docs/PHYSICS.md:837-838` ("Bellhop refines the needed acoustic samples inside the `ambiguous_db` band ... middle ambiguous sample") -> every needed in-range sample, the median depths, the band only for the Thorp-only label; add the cost sentence (time grows with the span: 0.2 s to 6 km, 2 s to 20 km, 6 s to 40 km; the 48-point grid differs from a 100 m grid by a median 0.7 dB, at most 17 dB, over 40 km).
  - `docs/RUNBOOK.md:189` ("... the method line says '(the lower of the two directions)' ... it can turn a pass into a fail, never the reverse"); and the RUNBOOK acoustic timing sentence (the bullet that quotes Bellhop's cost): a link's Bellhop time now scales with the span of its needed ranges.
  - `DECISIONS.md` 166 (inside the `ambiguous_db` band, "middle ambiguous sample"), 1017 (alternatives (b) the mean and (c) the shallower first stay; the choice becomes "lowest of the set"; "no demo number moves" stays true; "about 0.2 s a run" is true only to 6 km), 997 (the verdict stays on all members; say the sensitivity and `frac_*` are over the needed ones).
  - `CHANGELOG.md:912` (round 20 M-1 line) and a new round 21 line; `QUESTIONS_FOR_LAB.md` 18a (the band is gone for refinement; the cap 60 dB ASSUMED; the 5 m floor), `docs/CREDIBILITY.md` (the cap is an assumed number: it belongs in the assumed list if the audit counts constants).
  - `platforms/modems.yaml:11` comment ("Bellhop runs when the Thorp margin is within +-6 dB of 0"): should read "used where Bellhop cannot refine every sample (the Thorp-only label counts the samples within it); stage 1 refines every needed in-range sample (round 21, M-3)". NOT edited: `modems.yaml` is a hashed hangar input (DECISIONS 635), so even a comment changes a ledger hash; the lead decides.
- Decision text for DECISIONS (new rows after 1036; which need the owner is marked):
  1. **M-3, MAJOR (needs the owner: it amends BRIEF 2.8's "Bellhop runs within +-6 dB").** An acoustic link's needed in-range samples are ALL refined by Bellhop when Bellhop and a profile exist; `ambiguous_db` stays a parameter of `comms.acoustic_link` and `modems.yaml`, used only where Bellhop cannot refine (the Thorp-only label counts the samples within it). A Thorp pass that Bellhop turns into a fail is a wrong verdict (the lead's ruling); round 21's probes (made-up profiles) found it on two of three, and the CI fixture's duct turned a fail into a pass (8 km). The cost is the span of the needed ranges (LOUD 2). *Alternatives:* (b) widen the band to 40 dB; (c) document only; (d) skip samples beyond +-60 dB of the cap (verdict-neutral, cheaper, hunk below).
  2. **M-4 (needs the owner).** The margin is the lowest of {as named, swapped, both ends at least 5 m deep}; the spread is printed. The floor is a measurement on three made-up profiles; a 1 m glider is modelled at 5 m in one run (conservative on the profiles measured). *Alternatives:* (b) add an `nbeams` 4000 run (not measured here: no measurement of the right `nbeams`), (c) floor and run one direction, (d) document only.
  3. **M-10.** The Bellhop excess is held within +-60 dB (ASSUMED) and the label counts the held samples. *Default if the owner does not answer:* 60.
  4. **M-1.** Link statistics about performance (sensitivity, `frac_median`, `frac_p10`) are over the members that needed the link, `n_needed` in the summary, `censored` for any quantity with more than half its rows at its minimum or maximum; the verdict stays on all members. Sibling left open: `need_count_median`/`granularity_ok`.
  5. The depth pair of a refined member is the median depths of its refined samples (was the middle sample's); the label of a merged run counts every batch.
- What a demo run q23 should show against q22: no verdict, count, interval or margin moves (q22's two acoustic links are 555 and 632 km long: no sample in range, no Bellhop; `n_never_required` is 0 on all four links, so the sensitivity and `frac_*` subset is the whole). summary.json gains `n_needed` on the four links (equal to `n`) and `bellhop_spread_db_median: null` on the two acoustic ones; `report.json` leaf changes belong to batch B. `sensitivity.censored` appears wherever a ranked continuous quantity has more than half its rows at its minimum or maximum: I could not check q22's quantities (no run read; the USV state of charge and the UAS profile share do not qualify by the merge's own numbers), so a new `censored` leaf in q23 is possible and would be correct.

## Optional hunks (NOT applied) for the cost of M-3
```python
# stage1._acoustic, after `refine = need & valid` (verdict-neutral: the excess is held within +-BELLHOP_EXCESS_CAP_DB, so a Thorp margin beyond it cannot change sign):
refine &= np.abs(margin) <= comms.BELLHOP_EXCESS_CAP_DB
# and say it in `_bellhop_label`: "... needed in-range samples within 60 dB of a pass or a fail"
# comms.bellhop_tl: n_grid = max(48, int(np.ceil((r.max() - lo) / 100.0)))   # 100 m spacing; the time per call hardly depends on it (11.7 s against 12.2 s at 40 km)
```
Either changes printed margins for the samples it skips (Thorp instead of Bellhop) or for the grid; tests would move with them.

## Problems met
- `test_round18_c.py` and `test_pipeline.py` take 8.5 min and longer on orca at 2 CPUs; the shared box ran 8 to 9 load. A first batch-B run (25 files, serial) did not finish in 40 minutes and I stopped it by exact session name (`r21a_b1`, rc 143), then ran with `-n 2`.
- My first draft of `test_round21_a` had 4 wrong tests (a member 111 km away instead of 1 km, a keyword dict with tuple keys, a NaN depth that is out of range and never reaches the code I tried to cover, a `censored` fixture with too few rows at the maximum): fixed before the final runs.
- A background wait that greps `^rc=` hangs on a killed job (the log's last line is `....rc=143`, no newline).

## Not verified
- A real GOFS profile (all profiles are made up: B's three, and the CI fixture's analytic ocean); the whole suite and the gate; any mutant (`make mutation` not run; the new constants and comparisons have boundary tests on both sides: 60.01 / 60.0 / 59.99, 4.999 / 5.0, 15 / 16 members); q22/q23; the effect of the 48-point grid on the margin printed by a real long link beyond what `r21a_floor.py` shows for the excess; the tests of other batches' files beyond RESULT_B.

## Leftovers
- Orca (`~/cafe-worker`): CLEANUP.
- Laptop: worktree `../cafe-r21a-base` (detached 7599881, with `tests/test_round21_a.py` copied in; removed with `git worktree remove --force`), scratchpad `.../scratchpad/r21a/` (scripts and nothing else).
