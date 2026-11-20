# Round 23, batch E hand-back: the claims lint and the symmetry test (S-lint, M-10 a and b)

Branch r23-e on f71ad43 (round 22 closed + review material + batches A to D). Tests only: no file under `cafe/` or `docs/`, no document, no other test file touched.

## What changed

| file | change |
|---|---|
| tests/test_round23_claims.py (new) | the claims lint, two halves, 9 test functions (29 test cases with the parametrized scanner cases) |
| tests/test_round23_e.py (new) | `rfband.pair_band(a, b, f) == pair_band(b, a, f)` over 15 heights (120 unordered pairs, both orders) and 915 and 2,440 MHz; the default frequency; an invalid height refused in either position |
| tests/test_round21_e.py | comment only: "whatever the alias" is now "through the spellings listed here (plain, `import ... as`, `from ... import`, `getattr`) and no others", plus the ceiling named: not followed are a tuple assignment (`a, b = json, 1`), a class or instance attribute, a dict item, an argument and `sys.modules`. Each of those was run through `scan_source` and found no site (D-7); the claim "nothing in the repository does it" became "none was found" |

DECISIONS 1066 still says "through any alias": batch G amends it (M-10 b names it); the same wording is in my test comment now.

## The lint

**Product half.** Every non-docstring string constant of `cafe/pm/report.py`, `credibility.py`, `stage1.py`, `budget.py`, `pipeline.py` and every file of `cafe/pm/physics/` (a new physics file is in scope at once) found by the AST (the literal pieces of an f-string too), searched for: `up to`, `at most`, `cannot`, `never`, `no ray`, `within about`, `by chance`, `finer`, `no number`, `worst`, `everywhere`, `every`, `always`, `pure physics`, `bound`/`bounds` (whole words, case-insensitive). I added `budget.py` and `pipeline.py` to the lead's list because they print the plan basis ("a lower bound", S-17). 98 hits, 95 entries.
**Documents half.** `docs/RUNBOOK.md`, `docs/CREDIBILITY.md`, `docs/PHYSICS.md`, `QUESTIONS_FOR_LAB.md`, the narrower phrases of merged.md: `up to <digit>`, `at most <digit>`, `by chance`, `no number of members`, `within about`, `worst case`, `finer sampling`, `pure physics`, `lower bound`, `upper bound`. 92 hits, 92 entries. (A bare "every", "never" or "bound" is prose in 2,000 lines; the statistics' own word "bound" is read only as "lower bound" and "upper bound".)

**The allow-list is an enumeration.** A key is (file, scope, the text around the phrase, whitespace collapsed); scope is the enclosing function or class plus the name a module- or class-level assignment gives the string, so the key does not move when a line is added. A row carries the count, a kind and a one-line reason. A new occurrence, a changed context, a second occurrence or a stale row fails (`unclassified`, with file:line and found/allowed). Tested on the machinery (`test_s_lint_a_new_phrase_fails_and_a_stale_entry_fails`, the scanner cases, and "dropping any entry fails the lint") and on a real tree: in a scratch worktree I added `_NEW_CLAIM = "the margin is never worse than 9 dB"` to report.py, "within about 2 dB everywhere" to RUNBOOK.md and changed the S-30 sentence: the two halves failed naming exactly the new string (report.py:2272), the new doc phrase (RUNBOOK.md:332) and the stale S-30 entry; scratch removed.

**Allow-list (kinds).** Product, 95 entries: KEEP 16 (S-2, S-7, S-11, S-12, S-13, S-18, S-19, S-30, S-31; S-22 and S-39 in the documents), definition 40 (the text defines what it names or states what the code does), message 25 (an error or note printed only when its condition holds), constant 5, receipt 3, limit 2, measured 1, OPEN 3. Documents, 92 entries: definition 34, limit 19, history 20 (text a dated round said or did, e.g. rows marked SUPERSEDED), measured 10 (named case, named probe), KEEP 2 (S-22, S-39), OPEN 7. Every row has its reason in the file. The KEEP rows are the sweep's KEEP rows that carry a phrase of the vocabulary in a scanned string or document; the other KEEP rows (S-5, S-27, S-29, S-32, S-37, S-38, S-43) carry none there (S-27 is in a docstring, which the lint skips). S-39's arithmetic is the sweep's, not recomputed here.
S-12 (SCOPE) is KEEP in the lint because batch B printed the confidence ("lower 95 % bound 0.xx") and deleted the absolute clause.

## OPEN items (SCOPE or DELETE rows of the sweep still on the tree at f71ad43; allow-listed with the reason "OPEN: routed to the lead")

- S-17, cafe/pm/budget.py:59: `STAGE1_S_BASIS` "... and worker start-up are not in it, so it is a lower bound" (printed in plan.json and the report's plan block). Batch B's hunk for batch D's file was not applied.
- S-17, cafe/pm/budget.py:619: `describe()` "(a lower bound, not a schedule: plan.json stage1_s_basis)". Same hunk.
- S-17, cafe/pm/pipeline.py:1592: ledger note "the planned cost is a lower bound (plan.json stage1_s_basis)". Same hunk. (tests/test_budget.py:592-594 pin "lower bound": they move with it.)
- S-17, docs/RUNBOOK.md:133: "The stage-1 time it prints is a lower bound (the longest task or the work over the workers; ...)" and "stage 1 above its lower bound": two hits (same family as budget.py:59; not a sweep row of its own, the same claim).
- S-17, docs/RUNBOOK.md:146: "the estimate is a lower bound and q8 ran 2.2 times over it".
- S-20, docs/RUNBOOK.md:190: "the median moved by at most 0.59 dB and each count by at most 0.046 of 400 between 400 and 40,000 ranges (190 pairs of heights, two frequencies)": two hits.
- S-3 sibling, docs/RUNBOOK.md:190: "figures of the 400 sampled ranges, not of the worst case (review round 22, M-1, DECISIONS 1057)": the card's note no longer says it.
- S-41, QUESTIONS_FOR_LAB.md:122: "the gliders 555 and 598 km from a 4 km modem, and the USV up to 111 km": run not named, 598 is not q23's 632.

Total 10 rows of the allow-list (3 product rows, 7 document rows; RUNBOOK 133 is two rows, 190 is three). Each goes stale when its text is fixed, and the stale test then asks for its row to be deleted: batch G and the S-17 hunk each leave the lint red until the row is deleted (do it in the same commit).

**Still on the tree, found by grep, outside the lint's vocabulary or files** (all in batch G's list, not routed by the lint): docs/RUNBOOK.md:58 and :189 "(555 and 633 km)" (S-35); RUNBOOK.md:189 "The lowest margin is conservative for the transmitter depth" (S-36); STATUS.md:18 (S-41's twin) and STATUS.md:179 "the ensemble is pure physics" (S-16's twin; STATUS is not one of the four documents); docs/CREDIBILITY.md:171 "658 of 2759 cells" (S-42); cafe/pm/physics/rfband.py:12-13 docstring "a finer sampling finds interference nulls and, for most pairs, larger differences" (batch B's hunk; a docstring, which the lint skips).

## Read, not measured, in the allow-list (honest list)

Hits that are not sweep rows and that I classified by reading: the product "definition" and "message" rows (the sentence states a code path or a printed-only-if condition; I read each, did not enumerate by test), notably credibility.py:1283 "Every assumptions.yaml key, every perturbation prior, every platform input marked assumed" (`assumed_inputs` builds the list from those; no test enumerates it) and report.py:2061 "Every EMULATED answer comes from a trained emulator" (`method == "EMULATED"` is set on the stage-3 path only; read), and RUNBOOK.md:98 "a dive depth within about 7.4 m of `rating_m` still fails `overdepth` in every member" (not in the sweep; not re-measured). S-19 ("misses it by chance with probability", report.py:2008, pipeline.py:1636) is KEEP as the sweep says: the number is `whatif._chance_miss` (Beta-Binomial or, without `n_cal`, a Binomial the docstring says understates the chance); I read the function, did not recompute it.

## M-10 (a): the symmetry test, and the mutant

- Measured on orca (pm_r23e): `two_ray_loss_db` is NOT bit-symmetric in its two heights: 5 m with 500 m at 915 MHz differs by 2.4e-9 dB at a deep null (index 249 of 400). So the reviewer's "symmetric to 1e-9 dB" is not exact and an exact-equality test can kill `noswap_sorted`; I wrote none that asserts 1e-9 (a first draft did and failed on that pair, so it is deleted).
- Scratch before-copy (`git worktree add --detach ../cafe-r23e-base`, the line `low, high = sorted((float(h1), float(h2)))` replaced by `low, high = (float(h1), float(h2))`, my test file copied in, orca pm_r23ebase, removed afterwards): `test_pair_band_is_the_same_for_either_order_of_the_heights` FAILS for both frequencies (first failures: (0.1, 15.0, 915 MHz) maximum 15.980153627471196 against 15.98015362747114; (0.1, 5.0, 2,440 MHz) 5.799786856451618 against 5.79978685645159). With the sort: passes. The sort is therefore not equivalent in floating point; what the sort gives is bit-for-bit order independence, and that is what the test holds.

## Evidence

- Orca, cafe-orca proot 2 CPUs, `pm_r23e`: job `r23e_1`, rc=0, 242 passed by progress characters: tests/test_round21_e.py, tests/test_round23_claims.py, tests/test_round23_e.py; after two later edits of two allow-list rows (RUNBOOK 104 to KEEP:S-39, RUNBOOK 120 to definition) the two new files again, 29 passed, and ruff clean on the three files. The lint on the merged tree is green with the allow-list as committed.
- `ruff check` on the three files: All checks passed. `audit.banned()` over the repository: no hit in my three files (run on orca by a script).
- Not run: the full suite, the gate, mutation testing. No product statement was added, so no coverage change. No demo.

## Hostile reviewer on my own work

- A row's context can hide a change to the rest of the sentence: the key is 30 characters before the phrase and 60 from it, so an edit further away does not fail the lint (it does not fail an edit that keeps the phrase and its neighbourhood). The count per key catches a repeated phrase. Said, not closed.
- A new absolute phrased outside the vocabulary ("no longer", "impossible", "guarantees", "any ...", "none of ...") is not seen: the lint is a vocabulary lint. Files outside the scope (config, acceptance, whatif, stats, env, stage3, `__main__`; the user-visible strings of `cafe/*.py` outside `cafe/pm`) are not swept: 171 vocabulary hits in all of `cafe/pm` against the 98 I classified.
- Docstrings are not scanned (a docstring is not output); the comms and rfband docstrings that carry sweep rows are a document the builders edit, and the documents half does not read `.py` files.
- A phrase wrapped across a line break in a document ("up to\n4 m") is matched when the digit follows a single space only; the lint's pattern is `up to <digit>`: "up to" at the end of a line followed by a number on the next line is not a hit. Checked that the markdown tables of the four documents are one line per row; I did not scan for wrapped paragraphs.
- The OPEN reason is one string for all rows, so a row marked OPEN can never be silently turned into a KEEP without a kind and a reason (tested: only OPEN rows may use the OPEN reason).

## Leftovers

Laptop: none (worktree `../cafe-r23e-base` removed). Orca: `~/cafe-worker/cafe/pm_r23e` (mine, kept), log `~/cafe-worker/logs/r23e_1.log`; `pm_r23ebase` and `pmdata/r23e_banned.py` removed. No process of mine runs.

## Skeptic pass

Files touched: tests/test_round23_claims.py and this hand-back. Nothing under `cafe/` or `docs/`.

**1. RUNBOOK.md:98 "within about 7.4 m of `rating_m` still fails `overdepth` in every member" (minor, wrong data): real.** `glider.py:471` adds `P["apogee_overshoot"] * self.w_last * left` per member; `w_last` is the member's own last descent speed (`st.w * scale`) and `glider_speed_scale` is perturbed (`config/perturbations.yaml:65`), so the overshoot differs by member. `apogee_overshoot` is 0.5 in both platforms/seaglider.yaml and slocum.yaml, but a Slocum's speeds and pump time differ from the Seaglider's. 7.4 m and the 992.6 m cut-off are the nominal Seaglider's figures; the sentence names no platform. I had called it 'measured' for a row I had only read. Fix: the row is now `OPEN:K-1` (a new kind, OPEN for a sentence the skeptic found that the sweep did not list; the same reason `OPEN: routed to the lead`, and a comment above the row says why), so it is the 11th OPEN row (4 product... 3 product, 8 document) and goes stale, and its row is deleted, when the sentence is scoped. The sentence is in docs/RUNBOOK.md, not my file: see 'For the lead'.

**2a. Generic reasons that do not fit (minor): real for four rows, fixed.**
- PHYSICS.md "a step of up to 2.6 times in Cd": now kind `measured`, reason names the case and source: DECISIONS 653 (review round 12, M-13): Cd 1.19e-3 to 3.07e-3 at U 8 m/s, sigH 1.5 (3.07 / 1.19 = 2.58), the step the hard switch gave and the fade removes. I read it from the row, did not re-measure.
- PHYSICS.md "used up to 100 m": stays `definition`, with its own reason (the height to which the profile code is applied when there is no 3-D field; a modelling limit of the fallback).
- RUNBOOK "wind (at most 0.2 m/s)": was `limit` ("an input limit the code enforces"), which it is not. It is `pipeline.CALM_WIND_MS` = 0.2 with `CALM_SWH_M` = 1e-3 (pipeline.py:659-660): now `definition`, reason names the constants.
- RUNBOOK "at most 10, reached at 24.5 days: 24.4 days gives 9.5": was `limit`. `pipeline.MAX_PAD_DEG` = 10 caps the default pad (pipeline.py:214); the day figures are arithmetic, checked: 24.4 d x 86400 s x 0.5 m/s / 111,195 m per deg = 9.480, rounded up to 0.5 gives 9.5; 24.5 d = 9.518, rounded up gives 10. Now `definition` with that reason. Not run through `pipeline.default_pad`; the arithmetic is by hand.
Other rows of the same boilerplate ("an input limit the code enforces ...") are the input-range rows of the validation sections (`max_mean_wind_ms` at most 60, `lost_after_h` at most 720, `n at most 9007199254740992` and so on): each is a number in the loader's schema; I did not re-check each against `cafe/schemas/` in this pass. Said, not closed.

**2b. The KEEP check only checked 1..43 (minor): real, fixed.** `test_s_lint_a_keep_row_names_its_sweep_row` now parses the table of review/round_23/merged.md (43 rows, asserted) and requires each `KEEP:S-n` row to be a KEEP row of the sweep (S-12 is the one exception: the sweep says SCOPE and batch B applied the scope; `SCOPE_APPLIED = {12}` says so) and each `OPEN:S-n` row to be SCOPE or DELETE there. The module docstring no longer implies more than that: the lint checks that a reason exists and that a KEEP or OPEN number is the sweep's row of that verdict; it does not check that the reason fits the sentence (a reader does). Mutant, run on orca: the first `KEEP:S-13` changed to `KEEP:S-1` (a DELETE row) and the first `OPEN:S-3` to `OPEN:S-2` (a KEEP row): the test fails; the file is restored.

**Evidence.** Orca, cafe-orca proot 2 CPUs, `pm_r23e`: tests/test_round23_claims.py and tests/test_round23_e.py, 29 passed (progress characters), rc=0 on the first run (job r23e_2); after rewrapping six lines over 160 characters the same two files 29 passed again and `ruff check` on them is clean. Not run: the full suite, the gate. No product or document text changed.

### For the lead

- docs/RUNBOOK.md:98 (my `OPEN:K-1`): scope the sentence, then delete the row. Suggested text, replacing the parenthesis "a dive depth within about 7.4 m of `rating_m` still fails `overdepth` in every member, because the glider sinks on past the order while the buoyancy pump runs: the Seaglider ordered to 990 m peaks at 997.4 m and passes, to 995 m peaks at 1002.4 m and fails, the cut-off being near 992.6 m; ...": "(a dive depth close to `rating_m` can fail `overdepth`, because the glider sinks on past the order while the buoyancy pump runs, by `apogee_overshoot` x its last descent speed x the pump time, which differs by platform and by member: the nominal Seaglider ordered to 990 m peaks at 997.4 m and passes, to 995 m peaks at 1002.4 m and fails, the cut-off being near 992.6 m for it; the report says so with the measured peak, review round 10, M-16)". The 7.4 m, 992.6 m and the two peaks are the nominal Seaglider's from the sentence itself; I did not re-run them.
- cafe/pm/report.py:472, the docstring of `_overdepth_note`, says "an order within about 7 m of the rating fails in every member": same unscoped claim, in a docstring (not output, not in the lint's scan). The note it prints (line 480) says only that the peak passed the rating, and is true.
