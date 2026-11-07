# Round 10, look-ahead hand-back LB1: five confirmed look-ahead problems

Branch `r10-la` (worktree `../cafe-r10la`), on top of LB0 `3ae2402`. Tests ran on cafe-orca (`PM_HOST=cafe-orca PM_RUNTIME=proot`, 2 CPUs per job, `PMX=pm_r10la`). DECISIONS, CHANGELOG, RUNBOOK and HANDOFF are not edited here (the lead's doc pass); the text for them follows each item. DECISIONS numbers 583 to 587 follow 582 of LB0; renumber if that changes. `review/orca/PROBLEMS.md` has the one new row, P-38 (item 5).

Stated numbers: none moves. The receipts keep their labels and counts (1,845 cells; the archv `water_u` and `water_v` rows keep their 1,395), `tao_moorings_compared` keeps its value, and the emulator scopes are the strings they were. What changes is text: a flip-table `change` of a refused deploy shift (item 3) and one new ledger note (item 4).

Each new test was run on a detached worktree of `3ae2402` (`../cafe-r10la-mut`, the four test files copied over, removed at the end, with its orca dir `pm_r10la_mut`) and fails there for the stated reason; the same tests pass on the fixed tree.

## 1. The lab-HYCOM ingest receipts passed a lost ocean cell (RC-4 sibling)

Root, one place: `hycom.receipts` took the maximum error over `isfinite(a) & isfinite(b)`, so a cell finite in the GOFS values and NaN in the ingested store fell out of the comparison and the row read `[PASS] ... over 1844 cells: 0 vs 0` (the count falls by one, nothing checks it). M-20 fixed this for `check_node` only. New `hycom._worst_abs(a, b, rel=False, skip=None)`: `inf` when the two finite masks differ anywhere (outside `skip`), otherwise the largest |a - b| (or |a / b - 1|) and the cell count. `receipts` uses it for both loops: the lab round trip (both readers, six variables) and the GSW check cast (a point the code loses to NaN was dropped the same way: sibling in the same function).

Found by running it, not by reading: with a strict mask comparison the archv `water_u` and `water_v` rows failed on the unfixed store (1,395 of 1,845 cells finite on both sides). The archv reader destaggers the C-grid currents and drops their last column and row on purpose (`test_hycom.py`, the test of the `u[..., -1]` NaN edge). So `skip` is that edge, for archv `water_u` and `water_v` only (`"grid" in extra`); the rows' `source` text now says so. The count in their labels is unchanged (1,395 was already the cells outside the edge). Any other lost cell, including one next to the edge, is `inf`.

Callers checked: `receipts` only (`h.receipts` is run by `cafe.pm.receipts` and `test_hycom.py`); the receipt ids are made from the claim, which did not change. `check_node` (the server read-back) is untouched and already returns `inf` for a one-sided mask. Swept the other `isfinite(a) & isfinite(b)` masks in `cafe/pm` (`pipeline._ustar_agreement`, `_wind_residuals` lag products, `tao._stats`, `surface.good`): they compare model and observation series with real gaps, and say how many points they used; they are statistics, not receipts of an exact copy, and are left as they are.

Tests: `test_hycom.py::test_lb1_a_cell_lost_on_one_side_fails_the_lab_round_trip_receipts_and_the_check_cast` (the ingested stores lose cell (0,0,0,1) of `water_temp`: both readers' rows fail and exactly those two; and one density point of the check cast set to NaN fails its row). `test_receipts_pass_and_cover_both_readers` (16 rows, all pass) and the three `_failing` tests are unchanged and pass.

DECISIONS 583: The lab-HYCOM and check-cast receipts in `pm.env.hycom.receipts` fail (error `inf`) when a cell is finite on one side and NaN on the other, as `check_node` does (M-20); only the destaggered last column and row of the archv `water_u` and `water_v` are not compared (the reader drops them on purpose). Labels and counts are unchanged. | Look-ahead LB1. The maximum over the cells finite on both sides let a lost ocean cell pass (`over 1844 cells: 0 vs 0`). Amends 554 (M-20). Test: `tests/test_hycom.py::test_lb1_a_cell_lost_*`.

CHANGELOG: The lab-HYCOM ingest receipts and the GSW check-cast receipt fail when the store loses a cell the source has (they took the maximum over the surviving cells); DECISIONS 583.

## 2. A link id with a space made `report` fail its own HTML self-check

Root: `_n` wrote `data-path="p1 p2"` (the paths of a node joined by a space) and `check_rendered` split it on a space, but a link id may hold any character (`mission.json` restricts only vehicle ids). The node `links.usv uas-rf.p_fail` was looked up under two broken paths, never found, and (with a space-free link beside it, which keeps the shape in `shapes`) reported "not in the HTML". Now the attribute is a JSON list (`html.escape(json.dumps(where))`) and `check_rendered` reads it with `json.loads`; nothing else is split or joined.

Callers checked: `data-path` is read only by `check_rendered`; that is called only by `report.self_checks` (the report stage, and `report --run`), both after `report.write` has just written the page, so no page written with the old format is read by the new reader. `PRINTED` (`data-path="([^"]*)"`) still matches: `html.escape` turns `"` into `&quot;`. `INSTANCE` (the shape of an id) is unchanged; an id with a `.` makes a shape no other link has, so it is not asked for under its shape, a looseness and not a false failure.

Two existing M-27 tests wrote and read the attribute in the old format (a hand-built span with `data-path="p1 p2"`, `ps.split(" ")`); they now write and read the JSON list (`span()` takes the paths separated by a space and writes the list; the second test loads it). What they assert is unchanged.

Test: `test_report.py::test_lb1_a_link_id_with_a_space_is_found_under_its_own_path` (links `a`, `usv uas-rf` and `q"<b>`; fails before with `links.usv uas-rf.p_fail: '3 members' is not in the HTML`; and the guard that a page without the spaced link's span still reports exactly that path, so the per-path rule is not weakened).

DECISIONS 584: `report` writes the paths of a number node as a JSON list in `data-path` and `check_rendered` reads that list; they are not joined or split on a space. | Look-ahead LB1. A link id with a space failed `report_html_matches_json` (exit 1) with the numbers on the page. Amends 561 (M-27). Test: `tests/test_report.py::test_lb1_a_link_id_*`.

CHANGELOG: `report` no longer fails its HTML self-check for a link id with a space (`data-path` is a JSON list); DECISIONS 584.

## 3. Refused deploy-shift candidates were described as flying a negative number of days

Root: `flight_note` computed `new = old - shift / 24` with no look at the window, and `candidates` wrote the text for every shift before `apply` had refused any. The rule `apply` uses (inside the window and at least an hour before its end) is now one function, `whatif._deploy_in_window(t, window)`, used by `apply` and by `flight_note`, which returns `None` for a shift `apply` would refuse (so `flies -0.75 d` and, at the other end, a "longer flight" for a deploy before the window opens, are no longer written). To have both bounds, `flight_note` and `describe` take the window `(start, end)` in place of its end alone (`describe(mod, v, window=None)`).

Callers checked: `describe` (called by `candidates`, which passes `_window(mission)`), `flight_note` (also called by `answer` after `apply` has succeeded, where it cannot be None for a shift; it passes the window too). No other module calls either (grep over `cafe`, `bin`, `tests`). `tried[].change` in `emulator/flip.json` and the report's tried table take the text from `candidates`: a refused row keeps its reason and loses the flight sentence.

An existing assertion had to be given a setting in which its shift is accepted. In `test_a_deploy_shift_of_a_glider_says_it_flies_a_different_time_in_every_line_that_shows_it`, the note for a 12 h earlier shift was asserted on the CI mission, whose window opens at the glider's deploy time: `apply` refuses that shift, so the assertion pinned the defect. The text asserted is unchanged; it is now asserted on the CI mission with a window that opens 12 h sooner, and the CI case asserts `None`. The `t_end` argument became `window` in that test's other calls. Three more existing tests keyed the refused rows by the old text with the sentence (`test_candidates_are_single_changes_in_cost_order`, `test_the_emulated_flip_search_finds_the_24_h_shift_that_avoids_the_storm`, `test_the_uas_candidates_leave_out_whole_day_shifts_and_the_others_keep_them`: `shifted(-48, 1.5)` and `shifted(-6, 2.5)`, shifts earlier than the window's start, which `apply` refuses); their helper `shifted(h, flight_d=None)` gives the change alone when no flight is passed, and those three calls pass none. Every other assertion is unchanged, and the accepted shifts keep their full text.

Test: `test_whatif.py::test_lb1_a_deploy_shift_that_apply_refuses_is_not_described_as_a_flight` (a glider deployed 30 h before the end: for each of the eight shifts, `"flies" in change` iff `apply` accepts it; the +-48 h and the -12, -24 h shifts are refused and carry no sentence). Fails before with `deploy 12 h earlier (flies 1.75 d instead of 1.25 d ...)` next to a refused shift.

DECISIONS 585: A deploy-shift candidate's `change` text gets the flight sentence ("flies N d instead of M d ...") only when the shifted deploy is one `apply` accepts; the rule is `whatif._deploy_in_window` and `apply` and `flight_note` both use it. `flight_note` and `describe` take the window `(start, end)`. | Look-ahead LB1. The flip table showed `deploy 48 h later (flies -0.75 d instead of 1.25 d ...)` beside the reason `apply` refused it, for any glider or USV deployed within 48 h of the window end (or a "longer flight" before its start). Amends 545 (M-11). Test: `tests/test_whatif.py::test_lb1_a_deploy_shift_*`.

CHANGELOG: The what-if candidates no longer describe a refused deploy shift as a flight (a negative flight time in the flip table's tried rows); DECISIONS 585.

## 4. Moorings with no usable wind were dropped without being named

Root: a mooring whose WIND files have no QC-good sample in the window has `selected[name] == {}`, `load_tao` returns it without a `wind` key and `tao.compare` skips it; `_tao` counted the survivors and wrote nothing about the rest, so a change of 3 in `tao_moorings_compared` and of 5x in the fitted prior width needed the files' mtimes to explain. Now `_tao` writes one ledger note when any mooring of the manifest is not in the comparison: `N moorings in the TAO manifest, M compared; left out: T1N165W (no WIND file overlaps the window); T2S165W (OS_..._D_WIND_10min.nc (delayed mode): QC flags 3 in the window, none of the good ones 1, 2, 5); T5N170W (outside the environment's grid)`. The reason for a mooring inside the grid is `tao.wind_gap(cache, name, t0, t1)` (new): no WIND file at all, or for each WIND file its mode and the QC flags it carries in the window against `GOOD[mode]`, or "unusable" with the reason the manifest has, or "no sample in the window". The note is written before the stage can stop on the failed check, so the case of no mooring left is explained too. No note when all moorings are compared: the two notes of the ordinary run are the same.

Not changed: `tao_moorings_compared` and what it counts. A mooring that is compared but has no hour with three wind samples is still counted (`compare` keeps it); it is not "left out" by the code, so the note does not list it (it would contradict "M compared"). That count is the same question one level down and is not touched here.

Callers checked: `_tao` is the only user of `wind_gap` and the only writer of the note; `test_pipeline.py` counts the notes of the ordinary run (2) and the all-outside case (fails on the check, notes not asserted); the ledger note list is otherwise free text.

Test: `test_pipeline.py::test_lb1_a_mooring_left_out_of_the_comparison_is_named_with_its_reason` (three left out for the three reasons; then `wind_gap` for the unusable, no-sample and real-time forms). Fails before: the first note is `env sigmas fitted ...`.

DECISIONS 586: The ingest ledger names every mooring of the TAO manifest that is not in the wind comparison, with the reason (outside the grid; no WIND file; each WIND file's mode and QC flags against the good ones, or unusable, or no sample in the window), and the number of moorings the manifest holds (`tao.wind_gap`, one note from `pipeline._tao`). The count `tao_moorings_compared` is unchanged. | Look-ahead LB1. Between two downloads the compared moorings went from 11 to 14 and the fitted persistent wind sd from 0.110 to 0.569 m/s with nothing in the ledger to tell a data gap (real-time files all flagged 3) from a code drop. Test: `tests/test_pipeline.py::test_lb1_a_mooring_left_out_*`.

CHANGELOG: The ingest ledger lists the TAO moorings left out of the wind comparison and why (a data gap is told from a code drop); DECISIONS 586.

RUNBOOK sentence (where the ingest ledger's notes are described): "When the TAO moorings in the comparison are fewer than the manifest holds, the ingest ledger has one note naming each one left out and the reason (outside the grid, no WIND file, QC flags of its files in the window)."

## 5. The round's reference runs `q10` and `oq9` no longer audit (P-38)

Measured, not assumed, on orca at the LB0 code (read only, through `pmx.sh`, `audit /data/runs/<run> --ledgers-only`): `q10` 1 problem (`/data/tao/manifest.json changed since the stage ran`), `oq9` 2 (the same, and `/app/config/assumptions.yaml changed since the stage ran`), `q10lb` 0. The `derived.zarr` line of the finding is gone: all three runs have `ingest/derived.digest.json`, and LB0's audit tells a rebuild from damage with it. What is left is not a code defect and cannot be fixed without falsifying a record: `q10` and `oq9` hashed the shared older-rule `<data>/tao/manifest.json`, which the demo run before L0 rewrote in place, and no copy of the bytes they read exists (P-36 said so in general; P-38 has the measured case). `oq9`'s `assumptions.yaml` is a config file that round 10 edited after its stage 3. No ledger was edited to make an audit pass; no code changed for this item.

Also found while measuring: `q10lb` passes today but hashes the shared `tao/s2/manifest.json` in place (its ledger has no `shared`, it predates P-32), so it fails the same way the next time that cache grows. A copy of that manifest kept beside the run (the file as it is now) would let a person check it; I did not write into `pmdata/runs`.

PROBLEMS: row P-38 added. HANDOFF sentence: "`q10` and `oq9` are unauditable on orca (`audit` says the older TAO manifest, and for `oq9` `assumptions.yaml`, changed since the stage ran; the manifest was rewritten before the cache moved to `tao/s2`, nothing holds the old bytes): read their numbers, do not cite their ledgers as verified. The 11-mooring selection of `q10` was rebuilt by dropping the 3 moorings the 5 Nov files added; that reproduces its priors and is no proof of the manifest. `q10lb` audits clean now; keep a copy of `tao/s2/manifest.json` with it, since it predates P-32."

DECISIONS 587: `q10` and `oq9` are not repaired: their ledgers name inputs whose bytes no longer exist, and a record is never rewritten to make an audit pass; they are documented as unauditable (PROBLEMS P-38). | Look-ahead LB1. Measured on orca at the LB0 code. Amends the L0 text (571), whose "ledgers that hash the old manifest keep auditing" holds only for rewrites made after the fix. No test: a statement about two runs in a data directory.

CHANGELOG: none (a documented limitation of two reference runs, PROBLEMS P-38).

## Verified

- `ruff check cafe/pm tests` clean, `mypy cafe/pm` clean (strict), on orca.
- Orca, 2 CPUs per job, no coverage run: `tests/test_pipeline.py` whole rc=0; `test_hycom test_whatif test_report test_tao test_receipts test_ingest_fetch test_audit` passed except the five tests named in items 2 and 3 above, which pinned the old text; those were then fixed and `test_whatif.py` and `test_report.py` rerun whole, rc=0; `test_cli test_config_docs test_acceptance test_credibility test_ci_env test_reproducible test_ocean test_emulator` rc=0.
- Each new test fails on `3ae2402` and passes after (the check-cast half of the item 1 test was checked on its own: it fails before too).
- `audit --code-only`: the banned-token scan and the commented-code scan are clean; the only problem it prints is the missing `docs/mutation.json` (no `make mutation` was run: neither `physics` nor `stats` is touched). Coverage was not measured; every new branch of `hycom._worst_abs`, `tao.wind_gap` and `whatif._deploy_in_window` is run by the tests above.
- Not verified: the real `report` command on a copied q10 run (the finding's reproduction), and a real `fetch` with a mooring that has only real-time files; the fixtures stand in for both.

## Still looks wrong

- `tao_moorings_compared` counts a mooring that `compare` keeps but that has no hour with three wind samples; the new note does not list it (item 4).
- `INSTANCE` in `report.py` splits an id at a `.`; a link id with a dot is never held to the per-path rule (looser, not wrong), item 2.
- `q10lb` hashes the shared `tao/s2/manifest.json` and will fail its audit when that cache grows (item 5).
