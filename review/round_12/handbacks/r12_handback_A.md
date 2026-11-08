# Round 12, batch A handback (branch r12-a, from a8b8bb1)

Findings done: M-3, M-4, M-8, M-34, M-6, M-5, M-9, M-30, M-32, M-33, M-31, M-35 (all twelve, in that order). Documents (DECISIONS, CHANGELOG, RUNBOOK, PHYSICS, CREDIBILITY) are not edited: the text for them is below.

Files changed: `cafe/pm/report.py`, `cafe/pm/credibility.py`, `cafe/pm/acceptance.py`, `cafe/pm/receipts.py`, `cafe/receipts.py`, `tests/test_report.py`, `tests/test_credibility.py`, `tests/test_acceptance.py`, `tests/test_receipts.py`, plus one line of `tests/test_cli.py` (batch B's file, see "needs from other batches"), one line of `tests/test_reproducible.py`, and two rows in `review/orca/PROBLEMS.md` (P-R12A1, P-R12A2). `tests/golden/tepex_c_demo_quick.json` is NOT changed.

## The golden (M-9 and M-6 change the report)

Measured on orca by re-rendering a copy of q12 (`report --run` on a copy in the job's own /tmp; q12 itself only read, no simulation):

- `acceptance.summary(old q12 report.json) == acceptance.summary(re-rendered report.json)`: True. The golden keeps only the mission name, seed, and per vehicle and link the verdict, k_fail, n, p_fail, conf, cls and platform; none of the changed paths (`vehicles.*.mode_notes`, `assumed_inputs.*`, `machine.timing.total`, `sanity.reason`) is among them.
- `acceptance.compare(golden, summary(old))` and `compare(golden, summary(new))` return the same problem list. That list is not empty: the shipped golden is from an earlier code state and q12 differs from it already (n 32 against 64 for every vehicle, k_fail 18 of 64 against 8 for glider_eq, uas MARGINAL against NO-GO, and so on). That predates batch A; the golden is re-minted at code freeze. So: **the shipped golden does not have to change because of batch A**, and the tests that read it (`test_the_golden_in_the_repo_has_the_shape_the_comparison_reads` and the others in tests/test_acceptance.py) pass.
- Traceability problems of the re-rendered q12 report: none; `report --run` exit 0 (both self-checks pass).

Printed numbers of the demo (q12 re-rendered):

| number | before | after |
|---|---|---|
| assumed inputs, `assumed_inputs.total` | 285 | 285 (the demo uses every platform file, radios and modems; `catalogue` is 285 too, `not_used_by_file` is empty). Only the sentence changes. |
| mode notes under the vehicle cards | glider_eq: no_current_data, overdepth; glider_2n: the same two; usv: capsize_proxy, no_current_data; uas: no_current_data, profile_incomplete | glider_eq, glider_2n, usv: none (their counts are 0); uas: profile_incomplete |
| `machine.timing.total` | not printed | 562.2 s (the stages hangar to emulator; ingest and report stage left out) against the budget 1200 s: 0.4685 times the budget |

A UAS-only mission (the reviewer's example) would print 156 (quad_uas 45 + assumptions.yaml 99 + perturbations.yaml 12) of 285, where it printed 285.

## Per finding

### M-3. A vehicle or link named `values` crashes the report
- DECISIONS (new row): `report._walk` tells a number node by its payload, not by a key name. A dict is a node when `values` is a list of numbers (or of lists of numbers; an empty list only beside a `unit`) or when `value` is a number or null. A vehicle, link or window id `values` is a container whose parts are walked, traced and checked as before. (`vals()` is the only maker of `values` nodes and always makes such a list.)
- Amends: none. It contradicts no row. If batch B's M-2 also reserves ids in the schema, this fix still stands (the tracing of that branch is kept).
- CHANGELOG: "report: a vehicle or link with the id `values` no longer ends the report in KeyError 'unit' and its numbers are traced (round 12, M-3)."
- Docs: none needed.
- Could break / checked: callers of `_walk` are `check_traceability`, `check_rendered`, `render` (the path table) and the printed-path check; all four are covered by the two test files that run them (whole test_report.py). The review's proposed test (`isinstance(o.get("values"), list)`) was wrong: `map.windows`, keyed by vehicle id, holds a list of window records, so a renamed vehicle there was taken for a node (P-R12A1). Hence the numeric-list test. The regression test renames the vehicle in every section of a real report and also holds the window-list and empty-list shapes. Known corner: a section with a vehicle `values` holding an empty list AND another vehicle named `unit` would read as an empty node (both ids are allowed by the schema pattern); I did not guard it.

### M-4. Vehicle cards explain failure modes that did not occur
- DECISIONS (new row): the vehicle card explains a failure mode only when its count is above 0 (`report._drivers`: `mode_notes` and the overdepth add-on). The mode table keeps every mode with its share (a table, not an explanation).
- Amends: 550 ("include it" means a nonzero count; add that sentence), and the rows that say a note is printed for a mode: 308, 356, 406, 463 only if they say "every mode".
- CHANGELOG: "report: a mode that did not fire gets no explanation under 'What drives the failures' (round 12, M-4)."
- Docs: none.
- Could break / checked: the only reader of `mode_notes` is `_drivers_html`; the q12 diff above shows exactly the dropped notes. `tests/test_report.py::test_r10_m16_...` gave a glider with `k_fail` 0 an overdepth count of 0 and expected the explanation: it pinned the defect. It now gives the glider `k_fail` 3 (comment in the test; P-R12A2).

### M-8. A `runs/receipts.json` of the wrong shape crashes the report
- DECISIONS (new row): `report.Trace._table` accepts the receipts table only if it is a list of objects, each with a text `module`, and each pass or fail row with a text `name` and a true/false `ok` (`_rows_problem`); otherwise the physics block says "not run" with "runs/receipts.json is not a receipts table (<why>): rerun `python -m cafe.pm receipts`". `receipts.run` writes the table through `config.write_json` (a temporary and `os.replace`), so a kill mid-write keeps the old table.
- Amends: none (527 and 528 concern stored slow results). Same class as batch B's M-7.
- CHANGELOG: "report: a receipts table of the wrong shape is 'not run', not a KeyError or TypeError; `receipts` writes the table atomically (round 12, M-8)."
- Docs: RUNBOOK, where it says what the report does with a damaged receipts.json: it now says not run, naming the shape fault.
- Could break / checked: the text "is not valid JSON" stays for JSON syntax errors (tests match it); a wrong shape has its own text "is not a receipts table", because the file is valid JSON. The meta file (`receipts.meta.json`) is still written with `write_text`; the review asked for the table only. Rows of kind other than pass/fail are read only for `module`.

### M-34. Two assumed modem entries print the value "None"
- DECISIONS (new row): a provenance item with no `value` key shows `n/a (see why)` (`credibility._val`, used for platform items and assumptions.yaml entries); an explicit null value still shows `None`.
- Amends: none.
- CHANGELOG: "credibility: modems.benthos_atm960 and whoi_micromodem show 'n/a (see why)', not 'None' (round 12, M-34)."
- Docs: docs/CREDIBILITY.md:174 (the two modem entries: their Value cell is "n/a (see why)" and the figures are in the Why column).
- Could break / checked: `hangar --platform modems` prints the same value (it goes through `pipeline.provenance`), so its output changed: `modems.benthos_atm960 = n/a (see why)`. `tests/test_cli.py:1149` pinned `= None`; changed by one line (the verifier's "no test pins it" was wrong; P-R12A2). credibility.json's sha in the receipts changes (normalised in same_seed anyway); no consumer parses the value as a number.

### M-6. "N inputs are assumed ... verdicts depend on them" counts platforms the mission does not fly
- DECISIONS (new row): the credibility report keeps listing the whole catalogue (every platform file, assumptions.yaml, perturbations.yaml), and marks each item `used`: a platform item is used when its file is one of the mission's vehicle platforms, or radios (a mission with an rf link) or modems (an acoustic link); the items of config/ (assumptions.yaml, perturbations.yaml) are counted as used because they apply to every mission and which keys a run read is not recorded. The mission report counts the used items as `assumed_inputs.total` and says "N of the M in the catalogue are used by this mission, are assumed or are priors, and verdicts depend on them"; the others are listed as `not_used_by_file` and marked in the page lists.
- Amends: 221 (refines the count); the hangar parity row 566 (the count in `hangar` is by file and unchanged).
- CHANGELOG: "report: the assumed-inputs count is of the platforms the mission uses; the catalogue size is printed beside it (round 12, M-6)."
- Docs: docs/CREDIBILITY.md:165-174 (the list is the catalogue; `used` says which count) and the "263" figure at :173 (the demo prints 285 of 285; recount with `credibility.assumed_inputs()`). New report.json fields: `assumed_inputs.catalogue`, `.not_used_by_file`, `.items[].used`; `by_file` now holds the used files only. New credibility.json field: `assumed_inputs[].used`.
- Could break / checked: `platform_assumed_counts` (per platform, unchanged); tests that assumed `total == len(items)` (test_report.py:276 and :1707) now assert `catalogue`; the whole test_credibility.py passes.

### M-5. The "Sanity check against the brief" is keyed on the mission name
- DECISIONS (new row): the sanity block applies only to the mission BRIEF section 6 describes: the name `tepex_c_demo` AND its window (start and end), box (lon_min, lon_max, lat_min, lat_max) and set of vehicle ids (`credibility.DEMO_IDENTITY`, `is_the_demo`). A mission with the demo's name and another window, box or fleet gets no sanity block (`credibility.json` `sanity` null) and the report says so ("This mission has the demo's name but not its window, box and vehicles ..."). pad_deg, seed, description, budget and platforms are not part of the identity.
- Amends: extends 177 (and states 210, 467, 477 are unchanged).
- CHANGELOG: "credibility/report: the demo's expected-outcome table is for the demo's name, window, box and vehicles, not its name alone (round 12, M-5)."
- Docs: docs/CREDIBILITY.md and BRIEF section 6 pointers where they say "the demo mission": "as shipped".
- Could break / checked: the finding also asked to compute the USV text ("7-8 March, the demo window ends 7 March 12Z") from the window; not done, because the identity now forces the demo's window, so the hard-coded text is true wherever it is shown. A lab that edits the demo's window or fleet and keeps the name loses the table (intended). The cache and the other name-only identities (`pipeline.py:102, 256, 462`, `budget.py:107`) are not batch A's and are unchanged.

### M-9. A 20-vehicle quick run takes 26 minutes against the 20-minute budget and the report does not say so
- DECISIONS (new row): the machine block sums the walls of the stages hangar to emulator (ingest left out as in 196; the report stage's own ledger is written after the table, so it is left out too and the page says so) as `machine.timing.total.took`, with `.budget` (plan budget_s) and `.times` (their ratio); the page prints "The stages took X in all (the ingest and the report stage are not counted) against the budget of Y: N times the budget" and, over 1.0, "Over the budget." with the known causes that apply in this run: stage 1 above its planned lower bound, and the stage 1b sensitivity case that no share pays for, with their seconds. Not a failing check. `machine.timing.total` is in `acceptance.VOLATILE` (same_seed and the golden never see it).
- Amends: extends 196 and 265 (a wall ratio is information about the machine, not a gate).
- CHANGELOG: "report: the machine block says how long the stages took in all against the budget and names the known causes when over (round 12, M-9)."
- Docs: RUNBOOK timing section (what the sentence means; ingest not counted).
- Could break / checked: `tests/test_report.py` line ~1983 asserted the timing keys were exactly `{"stage1"}`; it is now `{"stage1", "total"}`. The demo number is in the table above. The sum is a node whose receipt is the first counted stage's ledger (its `source` lists the stages), not a per-stage receipt.

### M-30. `acceptance.normalize` leaves the run path when it has a non-ASCII letter, a quote or a backslash
- DECISIONS (new row): `normalize` replaces the run directory in the parsed strings of report.json (keys and values) and of credibility.json, not in their JSON text (`_each_str`).
- Amends: none.
- CHANGELOG: "acceptance: same_seed no longer fails when the run directory's name has a non-ASCII letter, a quote or a backslash (round 12, M-30)."
- Docs: none.
- Could break / checked: the replace is the same two replacements as before, on each string; the test runs five directory names (café, q"x, a\b, a b, quick), the first three fail on the old code.

### M-32. `other_seed` requires equal n
- DECISIONS (new row): in `acceptance.compare`, n must match exactly only for the same-seed comparison (the golden); the other-seed comparison needs class, platform and the set of entries equal, and Newcombe takes both n. A verdict note names both n when they differ ("undecided in both at n = 40 and 64").
- Amends: 134 (n = 32 as a quick-run example stays true) and 596 (exact comparison is same-seed only: now also for n).
- CHANGELOG: "acceptance: other_seed accepts a different number of members; same_seed and the golden still need the same n (round 12, M-32)."
- Docs: RUNBOOK acceptance section if it says "n must match"; the acceptance.py docstring is updated.
- Could break / checked: `test_l0_r11_a_summary_with_n_zero_or_k_beyond_n` asserted a line starting "links rf: n " for both seeds; under seed=False there is no n mismatch any more by design, so the assertion is `any(...) == seed` (the "is not a count" line, which names n, is still asserted for both). The golden path (`seed=True`) is unchanged; a test holds that n 40 against 80 is a problem there.

### M-33. `acceptance --update-golden` writes the shipped golden from any mission
- DECISIONS (new row, or amend 130): `--update-golden` writes the golden only when there is no file, or the file is the golden of the same mission, or `--golden-mission NAME` names this run's mission. A file that is not a golden (not JSON, not an object, no string `summary.mission`) is refused the same way. The refusal is a failed `golden_diff` row (`updated` false, `refused` true) naming both missions and the flag, the file untouched; `acceptance.run` refuses before any run starts (it would otherwise be found after hours).
- Amends: 130 (and 202 only if it says the update overwrites).
- CHANGELOG: "acceptance: --update-golden refuses to overwrite the golden of another mission, or a file that is not a golden, unless --golden-mission names this mission (round 12, M-33)."
- Docs: RUNBOOK:253 (re-basing after a mission rename needs `--golden-mission NAME`), the `--update-golden` help.
- Could break / checked: `check_golden(..., golden_mission=None)` and `run(..., golden_mission=None)` are new keyword parameters; `main` reads `getattr(a, "golden_mission", None)`. The argparse flag itself is NOT added (see below).

### M-31. `receipts --only a,typo` runs `a` and ignores `typo`
- DECISIONS (amend 319): every part of `--only` must select a group; a part that selects none, or an empty part (a stray comma), exits 2 naming that part and the groups, and writes nothing. Plain, `--slow` and `--broken` share the check (`receipts.run`).
- Amends: 319 ("any part" instead of the ambiguous wording).
- CHANGELOG: "receipts: --only exits 2 when any part matches no group, and an empty part selects nothing (round 12, M-31)."
- Docs: RUNBOOK where `--only` is described. The `--only` help text in `__main__.py` already says "a part that matches no group exits 2" (true now).
- Could break / checked: scripts that pass a trailing comma or a stale group name now get exit 2 (intended). The existing single-part test passes unchanged.

### M-35. Stored CFD and SITL results are PASS rows with no check of which code made them; the environment is not restored on error
- DECISIONS (new row): a stored result of the app (`torpedo.external.json`, `wigley.surface.json`, `suboff.incidence.json`, `crosscheck.json`) is a receipt only if it carries `date`, `host`, `git_sha` and `code_digest` (`cafe.receipts.stamp()` adds them) and the digest equals the hash of cafe/*.py (the one `cafe.pm.receipts.code_digest("app")` gives; a test holds the two together). Unstamped, stale, unreadable or not-an-object files become a context row saying which, never a pass; a valid one gets " [stored <date>, <host>, git <sha>]" in each row's source. `weather_receipts` and `fleet_receipts` put CAFE_OCEAN (as it was, also unset) and the quad time step back whatever happens (`_env_kept`).
- Amends: none found (no row accepts unstamped app rows). It follows 527/528 for the slow groups.
- CHANGELOG: "receipts: stored CFD and SITL results count only with a stamp from the current code; the app receipts restore CAFE_OCEAN and the quad step on error (round 12, M-35)."
- Docs: docs/PHYSICS.md:745 and RUNBOOK (the stored CFD and cross-check results are optional inputs that count only when stamped; how to stamp).
- Could break / checked: **nothing in the repo writes these four files** (grep), so every existing one turns from PASS to a context row until remade with a stamp; the app group's pass count in the receipts table drops accordingly. Any edit of cafe/*.py makes a stamped file stale (the same rule as the slow groups). `_app` in `cafe/pm/receipts.py` needed no change (a context row in the group CFD or Emulator also stops its "no stored ..." row). After `weather_receipts`/`fleet_receipts` CAFE_OCEAN is now what the caller had (absent when unset) instead of "1"; `cafe/env.py` reads absent as "1", so no behaviour moves. `python -m cafe.receipts` is unchanged apart from the above.

## Verification

- Tests, on orca only (proot, 2 CPUs; progress characters counted with the strict pattern of CLAUDE.md, since pytest prints no summary):
  - the whole files tests/test_report.py, test_credibility.py, test_acceptance.py, test_receipts.py plus the `hangar` test of test_cli.py: 650 passed, 1 failed (`test_r10_m16_...`, which gave a glider a failure count without a matching verdict); the test was corrected and passes on rerun together with `test_r12_m4_...`.
  - the neighbouring files tests/test_audit.py, test_config_docs.py, test_ledger.py, test_reproducible.py, test_cli.py (whole), test_runners.py, test_comms.py: 756 passed, 2 failed (both in test_reproducible.py: it has its own list of fields that differ between runs and did not know `machine.timing.total`; one line added, 6 passed on rerun). That file is outside batch A's list; the change is `"machine.timing.total"` in its `TIMING` tuple (the same entry as in `acceptance.VOLATILE`; a precedent is DECISIONS 340).
  - the report-related tests of other files (`-k report` over test_pipeline.py, test_ingest_fetch.py, test_stage3.py, test_emulator.py, test_whatif.py): 16 passed.
  - Not run: the rest of test_pipeline.py, test_stage3.py, test_emulator.py, test_whatif.py and the other files (nothing in them reads what changed beyond the `-k report` tests above); no full gate.
- Each new regression test fails on the unfixed code: the four test files with the new tests were copied into a detached worktree of a8b8bb1 and `-k r12` run there: 25 failures covering all twelve findings (M-30's `a b` and `quick` parameters pass there, as controls). The detached worktree and its orca directory were removed.
- `ruff check` clean, `mypy` clean (55 files). `audit --code-only`: no banned token and no commented-out code; its only line is the mutation record absent from my private directory.
- Regression-test names: `test_r12_m3_...`, `test_r12_m4_...`, `test_r12_m5_...` (two), `test_r12_m6_...`, `test_r12_m8_...` (two), `test_r12_m9_...`, `test_r12_m30_...`, `test_r12_m31_...`, `test_r12_m32_...`, `test_r12_m33_...` (three), `test_r12_m34_...`, `test_r12_m35_...` (three).

## Needs from other batches

- **Batch B (owns `cafe/pm/__main__.py`)**: add the flag M-33 reads. In the `acceptance` sub-parser, beside `--update-golden`: `p.add_argument("--golden-mission", default=None, metavar="NAME", help="with --update-golden: let this run's mission NAME replace a golden of another mission, or a file that is not a golden")`, and mention it in the `--update-golden` help and the usage line 17. Until then the refusal works and the override is unreachable from the command line (the code reads `getattr(a, "golden_mission", None)`; the unit tests call `acceptance.main` with a namespace).
- **Batch B (owns `tests/test_cli.py`)**: I changed line 1149 (`test_r10_m32_hangar_counts_...`) from `= None` to `= n/a (see why)` for M-34. Keep it when merging. Optionally a parse test for `--golden-mission`.
- **Merge note**: `tests/test_reproducible.py` (`TIMING`, one entry added) is in no batch's list; if another batch also adds a timing field there, keep both entries.
- **Batch B**: if M-2 reserves ids in the schema, no change is needed here (M-3 is fixed on its own). The name-only identity of the demo at `pipeline.py:102, 256, 462` and `budget.py:107` (siblings of M-5) are theirs.
- **Batch F**: the DECISIONS rows, CHANGELOG lines and doc sentences above; CREDIBILITY.md:173 (the 263 figure); RUNBOOK:253; PHYSICS.md:745.
- **Whoever writes the stored CFD and SITL results** (lab scripts, outside this repo): call `cafe.receipts.stamp(record)` before writing, or the rows stay context rows.
- No need from batches C, D, E.
