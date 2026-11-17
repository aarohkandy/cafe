# Round 18, batch F hand-back (the hull reader and the interval contract)

Branch `r18-f`, worktree `cafe-r18f`, cut from `premission-step4` at d69be8f. Commits: 6d6cf85 (code and tests), 21195ea (one pinned-row comment shortened for ruff), and this file. Findings: M-10 and M-14, both done. Nothing pushed or merged.

## M-10: `fea.hull_elements_along` (OD-11 taken: a closed grammar plus a differential fuzz)

### What changed (cafe/fea.py)
The skip rule and the per-regex layouts are replaced. The reader now checks a closed grammar over the whole file, not only the entry (reason: PyYAML reads the whole file, so a line it refuses in another entry makes the pipeline's read fail while the hand reader returned 70; the whole-file fuzz found 111 such mismatches in 400 on the old reader).
- Before `splitlines`: any character outside `\n \r \x20-\x7e \xa0-\u2027 \u202a-\ud7ff \ue000-\ufffd U+10000-` is refused (so no tab, `\x0b`, `\x0c`, `\x1c-\x1e`, `\x7f`, `\x85`, U+2028, U+2029, U+FFFE).
- Line grammar (`_entries`, `_scalar`): blank, comment, `key:` or `key: text` at column 0, and `  name: text` (exactly two spaces) under a `key:` with nothing after it. Nothing deeper under any key, no child under a key that has a scalar, no child without a parent, no list item, no document marker, no directive. Only a space may follow a colon.
- Text is one line and one of: plain (no first char from `[]{},#&*!|>'"%@` backquote `?` `:`, no `- ` start, no `: `, no trailing colon, ` #` starts a comment), double-quoted with no backslash, single-quoted with `''`, a one-line flow list of plain numbers (`[0.2, 3.0]`), or empty/comment.
- Entry checks kept: key written once and alone on its line (a comment may follow), one `value:`, plain decimal whole number 1 to 500. Messages that tests pin are unchanged (`has no stage3.fea_elements_along`, `has no value`, `not a whole number`, `below 1`, `above 500`, `only the key, a colon and a comment are read`, `written N times`).
- Removed: `_BLANKS`, `_TOP_LINE`, `_MESH_TEXT` (grepped: no other file used them). The docstring now states the grammar and that the claim "returns a number only if PyYAML gives the same one" is held by `tests/test_round18_f.py`'s fuzz, with the converse not claimed.

### A departure from OD-11's text, forced by the shipped file
OD-11 says a scalar that starts with a flow character is refused. The shipped `config/assumptions.yaml` has 26 one-line numeric ranges (`value: [0.2, 3.0]`), so the first run of the first test failed on line 3 of the file. The grammar accepts a one-line flow list of numbers and refuses every other flow collection. Lead: say so if you want the entry-only scope instead (then another entry's layout is not checked and the whole-file fuzz would have to be dropped).

### Behaviour that is now refused although PyYAML reads it (the grammar is closed, not equal to YAML)
Block scalars, nested mappings, lists, children not indented by exactly two spaces, escapes in a double-quoted text, a tab or any control or exotic line-break character anywhere, a non-number flow collection, multi-line quoted text. Only `config/assumptions.yaml` is read by this function, and the shipped file passes (first test). A lab edit of another entry that uses one of these layouts now makes the Hangar hull case fail with a message that names the line and the reason; the pipeline's PyYAML path would still read it. This is the stated trade-off of the closed grammar.

### Tests (tests/test_round18_f.py, new; 305 tests in the file)
- `test_r18_m10_the_shipped_file_is_inside_the_grammar_and_both_readers_give_70`
- `test_r18_m10_the_five_layouts_of_the_finding_are_refused_where_pyyaml_does_not_give_70` (5 rows: tab after `value:`, form feed, vertical tab, `unit: a: b`, deeper line after `unit: x`)
- `test_r18_m10_a_tab_control_or_exotic_line_break_anywhere_in_the_file_is_refused` (12 characters x 4 places)
- `test_r18_m10_a_line_outside_the_grammar_is_refused_wherever_it_stands` (about 50 layouts)
- `test_r18_m10_what_is_inside_the_grammar_reads_and_pyyaml_gives_the_same_number` (guard rows)
- `test_r18_m10_the_value_is_a_plain_whole_number_from_1_to_500`
- `test_r18_m10_fuzz_of_the_entry_wherever_the_reader_gives_a_number_pyyaml_gives_it_too`: 2,000 seeded (seed 18) mutations of the entry and its neighbours; asserts at least 150 numbers read and 150 refused so it cannot pass vacuously.
- `test_r18_m10_fuzz_of_the_whole_file_...`: 400 seeded (1818) mutations of the 527-line file; at least 20 each way.
- `test_r18_m10_the_fuzz_is_seeded_so_a_failure_reproduces`

### Existing tests moved (each with its reason)
- tests/test_stage3.py, `test_r15_l0_4_the_hull_mesh_reading_never_returns_a_number_pyyaml_does_not`: four rows changed from `70` to `"refuse"`: "block scalar text", "nested mapping", "nested mapping after", "continuation of another child". PyYAML reads 70 for each; the closed grammar has no block scalar and nothing deeper than a child, and the last one is the A-9 layout family (deeper line after a key other than `value`).
- tests/test_round17_f.py, `test_r17_m14_comments_blank_lines_and_indented_text_do_not_trip_the_top_level_rule`: the sample's trailing `b:\n  - item\n  - more\n` became `b:\n  why: more\n` (a list is outside the grammar); the test's point (comments, blanks and indented text do not trip the top-level rule) is unchanged.
- Every other row of the r15_l0, r15_l0_4, r16_m20 and r17_m14 tests passed unchanged, as did `test_round16_pb` (the app-tree reading).

## M-14: `intervals` counts (stats/intervals.py)

### What changed
- New `_count(x, name)`: refuses anything that is not a Python `int` or a numpy integer, and refuses `bool` first (`isinstance(True, int)` is true). `np.bool_` is not an `np.integer`, so it is refused. A float is refused even when whole (3.0): stated rule, since no caller passes one.
- `_check(k, n, conf, kn=("k","n"))` calls it before the range checks; `newcombe_diff` passes `("k1","n1")` and `("k2","n2")` so the message names the right argument. `rule_of_three` calls it. `interval`, `verdict`, `interval_region`, `decided_region` and `ensemble_stop` go through `wilson`; `coverage` goes through `wilson` too (tested).
- Message: `k must be an integer count (an int, not a bool or a float), got 1.5 (float)`. The existing range message `need 0 <= k <= n and n >= 1` is unchanged and still pinned by `test_m37_...` in tests/test_round15_a.py.

### Callers checked (grepped every `wilson(`, `agresti_coull(`, `newcombe_diff(`, `rule_of_three(`, `interval(`, `verdict(`, `interval_region(`, `decided_region(`, `ensemble_stop(`)
All pass ints: stage1 (`int(f.sum())`, `len`), whatif (`int(f.sum())`, `len(f)`), pipeline.py:1248 (`int(...)`, `len`), `__main__.py:152` (`range`), sequential (callers pass `int(...)`), acceptance, report and credibility (counts from JSON, already passed through `credibility.check_counts`, which requires ints). `emulator` calls only `verdict_band` / `band_in` (floats, no counts, not touched). No caller passes a whole float, so no caller needed a change. Not checked: any caller outside `cafe/` and `tests/` (none found by grep).

### Tests (same file)
`test_r18_m14_a_count_that_is_not_an_integer_is_refused_by_name` (8 functions x 15 bad values: 1.5, True, False, whole floats, numpy float, `np.bool_`, `np.float32`, strings, None, in either position), `..._a_numpy_integer_count_still_passes_and_gives_the_python_integers_answer`, `..._the_ranges_are_checked_after_the_type_and_keep_their_message`, `..._rule_of_three_refuses_...`, `..._coverage_refuses_...`, `..._the_message_says_what_was_passed`. Each branch of `_count` and the `kn` names are hit, so mutants of the type test, the bool test and the names die. Coverage on `cafe/pm/stats`: 100 % (112 statements in intervals.py, 0 missed; stats total 377, 0 missed).

## Fail before

New file alone, on a detached worktree at d69be8f with only that file copied in (orca `pm_r18f_base`, log `r18f_6`): 225 failed, 80 passed (305 tests), rc=1. The failures are the intended ones: all 5 finding layouts, all 48 character rows, 39 grammar rows, 120 M-14 name rows, the coverage, rule_of_three and message tests, and both fuzzes. The fuzzes found 379 mismatches of 2,000 (entry) and 111 of 400 (whole file) on the round 17 reader, so the fuzz would have caught A-9 and D-5. The 80 that passed on the base are guards by design (shipped file reads 70, in-grammar rows, ranges, numpy ints).

## Final runs (cafe-orca, proot, 2 CPUs, tree `pm_r18f`, counts by the CLAUDE.md method)
- `r18f_4` (pytest `-n 2 --cov=cafe/pm/stats --cov-report=term-missing` on test_round18_f, test_stats, test_stats_exact, test_round15_a, test_round14_survivors, test_round17_f, test_stage3, test_round16_pb, test_config): 1,274 passed, 0 failed, PYTEST_RC=0, stats 100 % (intervals.py 112 statements, 0 missed). This run was on the tree before the last ruff line-wraps.
- `r18f_7` (on the committed tree 21195ea): `ruff check cafe/pm cafe/fea.py tests` RC=0, `mypy cafe/pm` RC=0 (55 files), and `pytest -n 2` on the 26 files test_round18_f, test_report, test_round16_report, test_whatif, test_acceptance, test_credibility, test_emulator, test_stage1, test_pipeline, test_round17_a, test_round17_b, test_round17_c, test_round16_a, test_reproducible, test_cli, test_budget, test_q13cmp, test_round17_m, test_round17_f, test_stage3, test_stats, test_stats_exact, test_round15_a, test_round14_survivors, test_config_docs, test_receipts: 2,973 passed, 0 failed, PYTEST_RC=0, job rc=0.
- `python -m cafe.pm audit --code-only` (inside both jobs): one problem, `mutation: no stored result at docs/mutation.json`. `docs/mutation.json` is not in git and not sent to orca, so the problem comes from the missing record, not the banned-token or commented-code scans (which print nothing). I did not run the audit on the base tree to compare. No banned token in my files (read `audit.BANNED` first).
- Not run: test_config.py was in r18f_4 only (passed); the whole suite and the gate were not run (the lead's job); mutation testing of `intervals.py` not run (hours).

## Proposed DECISIONS rows (the lead numbers them)
- "`fea.hull_elements_along` reads a closed grammar over the whole of `config/assumptions.yaml` and refuses every line outside it (OD-11, M-10): characters are a line break, a space and printable characters (no tab, control character, \x85, U+2028 or U+2029, checked before `splitlines`); a line is blank, a comment, `key:` or `key: text` at column 0, or `  name: text` (two spaces) under a `key:` with nothing after it; the text is one line, plain (no `: `, no trailing colon, no flow, anchor, alias, tag, block-scalar or list-item start), in quotes (no backslash), or a flow list of numbers (the shipped ranges); nothing deeper under any key. The entry is checked as before (one `value`, a plain whole number 1 to 500). The docstring's claim, that a number it returns is the one `yaml.safe_load` returns, is held by a seeded differential fuzz (2,000 mutations of the entry, 400 of the whole file) in `tests/test_round18_f.py`; the converse is not claimed, so a valid layout outside the grammar (block scalar, nested mapping, escape, 4-space indent) is refused. (amends 874, 908, 935)" Source: round 18, M-10 (A-9, D-5), batch F. Mention that the list-of-numbers form departs from OD-11's wording because the shipped file has 26 of them.
- "`intervals.wilson`, `agresti_coull`, `newcombe_diff`, `interval` and everything built on them, and `rule_of_three`, refuse a count `k` or `n` that is not an `int` or a numpy integer with a `ValueError` naming the argument; a `bool` is refused (`isinstance(True, int)` is true) and so is a float, even a whole one (3.0): a mean of flags or `p * n` is not a sum. numpy integers pass. (amends 868)" Source: round 18, M-14 (A-11).
- CHANGELOG lines: "Fixed: the hull mesh reader returned 70 for files PyYAML refuses (a tab or form feed after the value, a sibling's `a: b`, a deeper line under another key, a bad escape in another entry); it now reads a closed grammar and its claim rests on a differential fuzz." and "Fixed: `intervals.wilson` and its siblings accepted a fractional or boolean count (`wilson(1.5, 3)`); they refuse it."
- Documents for batch G: DECISIONS 874, 908, 935 and 868 get "amended by" marks; RUNBOOK needs no edit unless it describes the hull reader's accepted layouts (not grepped by me: `docs/` is not mine). QUESTIONS_FOR_LAB sub-item for OD-11: default "closed grammar, whole file, flow lists of numbers allowed".

## Not verified, and things outside the batch
- The grammar was checked only against `yaml.safe_load` (PyYAML 6.x in the cafe-pm image), on the 2,400 mutations of the fuzz plus the hand rows. It is a seeded sample, not a proof; the PyYAML versions of other images could differ at the edges.
- Reader and PyYAML both use `Path.read_text()` with the locale's encoding; the shipped file is pure ASCII, so I did not examine a non-UTF-8 locale.
- `cafe/pm/stats/sequential.sprt_decide(k, n, ...)` takes counts too and does not refuse a float or bool (its arithmetic is linear in k, so a float gives a number, not a wrong interval). Outside the finding; flag for the lead.
- `credibility.counts_ok` refuses numpy integers while `intervals` now accepts them: harmless (its inputs are JSON), but the two rules are not the same.
- No `docs/` or DECISIONS edit was made, as instructed.

## What I left on orca
`~/cafe-worker/cafe/pm_r18f` (73 MB, my tree), the logs `~/cafe-worker/logs/r18f_1` to `r18f_7.log`. I removed `pm_r18f_base` by its exact path. On the laptop I removed the helper worktree `cafe-r18f-base` and my scratch `r18f_job.sh`. Nothing was written to shared stores or `/data/runs/q18`.
