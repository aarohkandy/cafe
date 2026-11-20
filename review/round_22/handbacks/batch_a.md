# Round 22, batch A hand-back: stage 1 labels (M-2, M-3 (a), M-12 `far_ge`)

Branch `r22-a`, cut at 7a1aaa9. Files: `cafe/pm/stage1.py`, `tests/test_round22_a.py` (new), and the five pins listed below. Nothing else touched (no comms.py, no documents).

## What changed and why

**One count record for both acoustic paths, one label function, `merge` sums and rebuilds (M-2).** `stage1._acoustic` now computes `cand`, `far`, `refine` BEFORE asking whether Bellhop exists. With no needed in-range sample it still returns the constant label and `None` (so the out-of-range case is untouched). Otherwise it builds the record `dict(done, total, capped, beyond, runs_lo, runs_hi, ran)`; `ran = comms.bellhop_available()`. If `ran` is False it returns that record at once with `done = 0` and `total` = the needed in-range samples within 60 dB of a pass or a fail (the same mask the Bellhop path refines), and the label is
`Thorp only, Bellhop unavailable: N needed in-range samples that Bellhop would refine keep their Thorp margin` + the existing "a further M ... keep that margin" clause (now one local `further` shared by both paths).
The old no-Bellhop code (the `ambiguous & need` count of the +-6 dB band, "(N ambiguous samples)", and "Thorp budget decides every link" for a +18 dB link) is deleted. `merge` already rebuilt from the summed records whenever any batch had one; every acoustic batch with a needed in-range sample now has one, so the label counts ALL batches and does not depend on their order. `merge` passes `ran=any(...)` (see "not verified").

**Depth sentence (M-3, OD-2 default (a)).** When `done > 0` the Bellhop label adds `, each member on one pair of transducer depths, not one per sample` right after "Bellhop on D of T needed in-range samples". No number, no new constant. I did NOT put "the median of ..." in the label: the depths are the median clipped inside the water depth, and a word I cannot prove over the domain is a claim; PHYSICS 12.2 already says median.

Net claims: deleted "Thorp budget decides every link" for links Bellhop would have refined, deleted the "ambiguous" count; added one clause that states a limit (the depth sentence) and one label that states what ran and how many samples. `ambiguous_db` is no longer read by stage 1 at all (only by `comms.acoustic_link`'s own default for other callers).

**`far_ge` (M-12).** `test_m12_...` puts a column of margins at exactly +60, -60, one ulp past each, 0 and one ulp inside, in both availability states.

## The sentences the label leaves, and the test that holds each (over the whole domain, not a point)

The property tests (`test_m2_the_label_of_a_merged_run...`, 60 cases: 30 seeds x Bellhop off/on; `test_m3_the_depth_sentence...`, 30 seeds) draw margins from -120 to +120 dB with NaN, +-inf, exactly +-60, one ulp past and one ulp inside, random `need`/`valid`, members that never needed the link or were only out of range, five splits into batches (1 to 4 batches) and EVERY order of the batches. The expected label is rebuilt in the test from the masks alone (a recount of `need & valid & |m| <= 60`, an independent copy of the wording) and compared to the label of one batch holding all the members and to `merge` of the split.

| claim on an output | held by |
|---|---|
| `Thorp only, Bellhop unavailable: N needed in-range samples that Bellhop would refine keep their Thorp margin`, N a recount; whole, merged, either order | `test_m2_the_label_of_a_merged_run...[False]`; `test_m2_with_bellhop_off_a_link_outside_the_old_band...` (the reviewer's 7 and 40 samples: 47 in both orders) |
| the samples counted keep their Thorp margin (margin_db equal to Thorp on every sample when Bellhop is off) | same property test (`np.array_equal` of the whole margin array) |
| `Bellhop on D of T needed in-range samples`, D and T recounts; "the rest Thorp only" iff D < T | `..._with_and_without_bellhop[True]` |
| depth sentence iff D > 0, single batch, merged, both orders; never in a Thorp-only label | `test_m3_the_depth_sentence...` and the `(DEPTHS in want) == done` line of the M-2 property |
| "each member on one pair of transducer depths": exactly one `_bellhop_member` call per member with a refined sample, on the median of that member's refined depths | `test_m3_the_depth_sentence...` (spy) |
| `(the lowest of a to b runs ...)`, `N of them held at the assumed 60 dB bound`: min/max over every member, recounted capped | the M-2 property (`[True]`) |
| "a further M ... more than 60 dB from a pass or a fail on Thorp and keep that margin" (M recount; margin unchanged on those samples) | M-2 property (`np.array_equal` on the non-refined samples) |
| "... so it cannot change which they are" (the model's claim, with the cap of 60 dB) | already held over the domain by `tests/test_round21_m.py::test_a_sample_beyond_the_cap_has_the_same_sign_refined_or_not_and_the_cap_is_as_tight_as_it_can_be` (real `acoustic_link`, excess in -1e6..1e6, 1e-6 either side of the cap); reused, not duplicated |
| a sample at exactly +-60 dB is counted once (refined), one ulp past it is beyond | `test_m12_...` (both states) |
| out-of-range / not-needed link: `Thorp budget decides every link`, record None, with and without Bellhop, merged | `test_q23_a_link_with_no_needed_in_range_sample...`, `test_q23_the_same_out_of_range_link_through_evaluate_link` (45 km through `evaluate_link`) |
| the count record has exactly the keys done, total, capped, beyond, runs_lo, runs_hi, ran | M-2 property |
| `merge` of records that disagree on `ran` (not reachable in one run) says Bellhop ran on what it ran on | `test_m2_records_that_disagree_on_whether_bellhop_was_available...` |

## Enumeration (class table, OD-3 default: a test, no runtime check)

`test_every_key_of_a_link_result_has_a_declared_merge_rule_and_the_merge_follows_it` and `test_every_key_of_a_vehicle_result_has_a_declared_merge_rule_and_the_merge_follows_it` run a REAL pair of batches (2 members each, the CI fixture's four vehicles, its three links and a second acoustic link, `when: always`, USV to ship; 18 h window; `AnalyticEnv`; seed 11) through `stage1.run_batch` and `stage1.merge`, take the key set of every link and vehicle result and fail on a key that is not in `LINK_RULES` / `VEHICLE_RULES` / `TOP_RULES` (tables at the top of the enumeration section of the file; a new key must say cat, first, sum, dict_cat, fine, sorties, rebuilt or dropped). For every "first" key the test asserts the batches AGREE and the merged value is the first one; for "cat", "sum", "dict_cat", "fine", "sorties" it recomputes the join and compares; "dropped" keys must be absent from the merged result; the merged key set must be exactly the real keys minus the dropped ones. A third test (`test_the_enumeration_tables_are_complete_enough_to_catch_a_new_key`) adds an invented key to a real result and asserts the tables do not cover it. The tables are the ones in merged.md's "Enumeration" section; the real batches found nothing outside them, and every "first" key agreed between the two batches (no sibling defect found).

## Pins moved (each moved because the product's answer is now the intended one)

1. `tests/test_round21_a.py::test_m3_the_band_stays_where_bellhop_is_not_available`, renamed `test_m3_without_bellhop_every_needed_in_range_sample_within_the_cap_is_counted_not_only_those_in_the_old_6_db_band`. It pinned "(N ambiguous samples)" and, for +18 dB, "Thorp budget decides every link": exactly M-2's two defects.
2. `tests/test_round21_a.py::test_m4_the_label_names_the_set_only_where_more_than_one_run_was_made`: exact label gains the depth sentence (M-3).
3. `tests/test_round21_a.py::test_the_method_of_a_merged_run_counts_every_batch_and_the_runs_of_every_member`: the two hand-made records and the direct `_bellhop_label` call gain `ran=True` (the record has a new key).
4. `tests/test_round21_m.py::test_a_sample_beyond_the_cap_is_left_on_thorp...`: `head` gains the depth sentence; `::test_the_cap_count_is_summed_over_the_batches_of_a_merged_run`: the record equality gains `ran=True`.
5. `tests/test_round20_a.py::test_the_label_says_the_refined_margin_is_the_lower_of_the_two_directions_only_where_bellhop_ran`: exact label gains the depth sentence.
6. `tests/test_stage1.py::test_the_method_of_an_acoustic_link_is_a_string_even_when_comms_returns_one_per_element`: a faked 5 dB margin with Bellhop off was "Thorp budget decides every link"; it is 60 samples 5 dB from a pass, which Bellhop would refine, so the label is the Thorp-only one with N = 60. (The isinstance check stays.)
No assertion was loosened; none was deleted.

## Before / after evidence

All on cafe-orca, proot, 2 CPUs, `PMX=pm_r22a*`, detached (`TM=`), every job ended with an rc line.
- After (tree at the commit below): `r22a_12`: `ruff check cafe/pm tests` rc 0, `mypy cafe/pm` rc 0 (57 files), `tests/test_round22_a.py tests/test_round21_a.py tests/test_round21_m.py tests/test_round20_a.py`: 199 passed, 0 failed (progress characters counted, all `.`), pytest rc 0.
- `tests/test_stage1.py` whole file after the last edit: `r22a_13`, 174 passed (progress characters counted), 0 failed, rc 0.
- Before (`r22a_b1`, detached worktree `../cafe-r22a-base` at 7a1aaa9 with the new test file copied in; first draft of the file): 92 failed, 7 passed. The 7 that pass on the unfixed tree are the q23 out-of-range tests (3) and the enumeration tests (3) plus one seed of the depth-sentence test where no member had a refined sample: they describe what must NOT move or what the tables already say, which is the point. Failing on the unfixed tree: the 60 M-2 property cases, 29 of 30 depth-sentence cases, the 7/40 order case, the `far_ge` test (both states). (That run failed `far_ge` because the unfixed tree lacks `ran`, which is not a kill of the mutant; the mutant run below is.)
- Mutants of the fixed tree (`r22a_m1`, `r22a_m2`; a script replaced one line at a time in the orca copy and ran `tests/test_round22_a.py` without the real-batch tests): `far >=` (the `far_ge` mutant) KILLED; `refine <` KILLED; `ran=True` constant KILLED; `merge` summing only batch 0's record KILLED; depth sentence always printed KILLED; `total + 1` in the no-Bellhop record KILLED; `merge` `ran=all(...)` instead of `any(...)`: SURVIVED the first run and is KILLED by `test_m2_records_that_disagree...` added afterwards (`r22a_m2`; `far >=` killed again in the same run).

## Siblings searched

- Every other producer or reader of an acoustic link's `method` / `bellhop`: `grep` over `cafe/`, `bin/`, `lab/`, `bench/`: `stage1.py` only (report.py prints `method` as given; `summarize` copies it; `comms.py`'s own `acoustic_link` label and `THORP_ONLY_LABEL` for the helper's other callers and the receipts at comms.py:598 are unchanged and are not stage 1's).
- Every caller of `_bellhop_label`: `_acoustic` and `merge` (both pass `ran`); tests that call it directly are listed in pin 3.
- `merge` is only ever called with the raw list of batches (stage1.py:1141 a single batch, :1226 `merge(batches)`), never with an already merged result, so the dropped `bellhop` key cannot make a later merge lose a count. A merge of a merge would fall back to the first batch's text (not reachable; the enumeration test would show it).
- Res pickles (`res.pkl`) hold the merged result, which has no `bellhop` key: no old pickle can lack `ran` when merged.
- `ambiguous_db` / `res["ambiguous"]`: no reader left in stage 1; documents still say stage 1 uses it (see below).

## Hostile-reviewer attempts (what I tried)

Margin exactly +-60, one ulp past and one ulp inside, 0, NaN, +-inf; need/valid all False, all True, mixed; a batch with no candidate beside a batch with; a member with no profile (`_bellhop_member` None) inside a batch that ran (label says "the rest Thorp only", no depth sentence when no member ran); every permutation of up to four batches and five different splits; unequal batch counts (7 and 40); Bellhop off with +18 dB (the reviewer's case); Bellhop off with all samples beyond the cap (label "Bellhop was not run: all N ...", as before and true on a machine without Bellhop); records that disagree on `ran` (unreachable; pinned); the depth sentence on a Thorp-only label (never printed: test); the sentence when `done == 0` with `total > 0` (not printed: test); huge or bool counts (counts are Python ints from `int(mask.sum())`; `ran` is a bool from `bellhop_available()`). Not tried: a real Bellhop (none built on orca's proot image; every Bellhop in these tests is the project's own fake at `comms._run_bellhop` or `stage1._bellhop_member`).

## Decision text for DECISIONS (none needs the owner; OD-2 and OD-3 taken at their defaults)

- New row (M-2): "An acoustic link's count record is made in both paths: with Bellhop unavailable `_acoustic` returns the same record (done 0, total = the needed in-range samples within 60 dB of a pass or a fail, beyond, ran False) and the label `Thorp only, Bellhop unavailable: N needed in-range samples that Bellhop would refine keep their Thorp margin` (+ the beyond clause); `merge` sums the records of every batch and rebuilds it, so the label is independent of batch order; a link with no needed in-range sample keeps 'Thorp budget decides every link' (q23's). The +-6 dB band is no longer read by stage 1. Amends 1041 (the Thorp-only label) and the DECISIONS row that gave the label `(N ambiguous samples)`."
- New row (M-3, OD-2 a): "The Bellhop label says each member is on one pair of transducer depths, not one per sample, when Bellhop ran on any sample. The depth of a member's run is the median of its refined samples' depths (clipped inside the water); a `when: always` link to a glider that dives is judged on it. Options b to d (restrict, per-bin runs 3 to 5 times the cost, per-sample runs) not taken."
- New row (OD-3): "The 'first batch' class is closed by an enumeration test of every key of a link and a vehicle result, not by a runtime check in `merge`."

## Exact document sentences that must change (for batch G)

- `docs/RUNBOOK.md:52`. Replace "(since review round 21, M-3, every one, not only a link within about 6 dB of its margin) is judged on Thorp absorption alone, and the report says "Thorp only, Bellhop unavailable" on each such link." with: "is judged on Thorp absorption alone. The Method line of such a link says "Thorp only, Bellhop unavailable: N needed in-range samples that Bellhop would refine keep their Thorp margin" (N over every member, whatever the batch order) when at least one of its needed in-range samples is within 60 dB of a pass or a fail on Thorp; "Bellhop was not run: all N needed in-range samples are more than 60 dB from a pass or a fail on Thorp ..." when all of them are beyond that; and "Thorp budget decides every link" when it has no needed in-range sample." (The old promise, the words on EACH such link, was false for the last two cases, and false in another way before: it printed "decides every link" for a +18 dB link.)
- `docs/RUNBOOK.md:189` (Bellhop paragraph): add after the sentence about "(the lowest of n runs ...)": "When Bellhop ran, the line also says "each member on one pair of transducer depths, not one per sample": the depth pair is the median of the member's refined samples' depths, so for a `when: always` link to a glider that dives the margin is the one at that depth, not at the depth flown at each sample."
- `docs/PHYSICS.md:833`: "When Bellhop is absent the link is labelled "Thorp only, Bellhop unavailable"." is true only for a link with a needed in-range sample within 60 dB; say "Thorp only, Bellhop unavailable: N ... keep their Thorp margin".
- `docs/PHYSICS.md:841-842` (12.2): "`ambiguous_db` (6 dB, `modems.yaml`) is used only where Bellhop cannot refine every sample." is no longer true: stage 1 does not read it (only `comms.acoustic_link`'s own default does); delete the sentence. "Without Bellhop or a profile the label says "Thorp only"" is half true: without a profile (Bellhop available) the label is "Bellhop on 0 of N needed in-range samples; the rest Thorp only (no sound-speed profile or depth there)". Add: "The label says each member is on one pair of transducer depths, not one per sample".
- `DECISIONS.md` 1041: amend (see above). CHANGELOG: one line per decision row.
- QUESTIONS_FOR_LAB: nothing (no lab question: no number added).

## For other batches

Nothing needed from B, C, D, E.

## What a demo run q23 / q24 should show against q23

No verdict, count, interval or label moves. Both acoustic links of the demo are 555 and 632 km long: no needed in-range sample, record None, label "Thorp budget decides every link" byte for byte (tests `test_q23_*`, with and without Bellhop). `bellhop_spread_db_median` stays null. No Bellhop call is made earlier or later than before (the count is a mask), so the CI link test's runtime should not move; I did not time it.

## Problems met

- `pmx.sh` runs split arguments on spaces: `-k "a or b"` and `sh -c "..."` silently ran the wrong thing (rc 4, and a lint run that printed only `mypy=0`); both redone through scripts in `~/cafe-worker/cafe/pmdata/`.
- A `cat > ...` to a non-existent laptop path in one of my commands swallowed the heredoc that wrote the lint script; the next job failed with "No such file" (rc 2). No harm: redone.

## Not verified / still wrong

- No real Bellhop ran (none on orca's proot image); the Bellhop path is tested with the project's fakes, as rounds 20 and 21 did. The depth-sentence claim "one pair per member" is true by construction and held by a spy; the SIZE of the error it admits (reviewer B's 15 to 25 % of samples flipping against the depth flown, on made-up profiles) is unchanged by this batch and is not measured on a real GOFS profile.
- Records that disagree on `ran` cannot arise in one process (availability is a path lookup); `merge` reads them as "ran where any did", and then the trailing "(no sound-speed profile or depth there)" would give a wrong reason for the unavailable batch's samples. Pinned, not handled.
- The real-batch enumeration test runs two 2-member batches of the CI mission with `AnalyticEnv`: I did not time it separately; the file passed within the job above. With `AnalyticEnv` the acoustic links have no needed in-range samples, so their `bellhop` is None in that fixture; the rebuild rule on real records is covered by the property tests, not by the real pair.
- `tests/test_report.py`, `test_credibility.py`, the pipeline tests were not run (they do not pin an acoustic label by grep); the lead's full gate will.

## Leftovers

- orca: `~/cafe-worker/cafe/pm_r22a` (mine; `pm_r22a2` and `pm_r22abase` removed by exact name); scripts `r22a_*.sh` and `r22a_mut.py` in `~/cafe-worker/cafe/pmdata/` (mine, may be deleted); logs `~/cafe-worker/logs/r22a_*.log`. No tmux session of mine left, nothing killed.
- laptop: worktree `../cafe-r22a` (the branch); the scratch worktree `../cafe-r22a-base` is removed; scratch files in the session scratchpad `.../scratchpad/r22a/`.
