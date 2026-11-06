# Round 10, batch A hand-back: M-5, M-9, M-24, M-4, M-27, M-7, M-21, M-3, M-8, M-25, M-32, M-16

Branch `r10-a`, from `6c352ef`. Every test ran on cafe-orca (`PM_HOST=cafe-orca PM_RUNTIME=proot`, `PMX=pm_r10a`, 2 CPUs). Each new regression test is named `test_r10_m<n>_...`, so `-k r10` selects them all
in the five files named below. Docs (DECISIONS, CHANGELOG, RUNBOOK, PHYSICS, STATUS) are not touched. M-35 was not changed in code (see the last section).

## Result in one table

| finding | where the fix is | regression test(s) |
|---|---|---|
| M-5 | `__main__.main` (`except OSError` -> `error:` rc 2); `config.damaged_run_files` (KeyError/TypeError -> ConfigError), used in `__main__._report` and `__main__._whatif`; `report.build` raises ConfigError for a missing `stage1b/summary.json` | `test_cli.py::test_r10_m5_*` (3 tests, 6 cases) |
| M-9 | `report._map`, `_env`, `_stage3` (`NO_WINDOWS`); `_map_html`, `_env_html`, `_window_html` | `test_report.py::test_r10_m9_*` (3) |
| M-24 | `receipts.slow_group` | `test_receipts.py::test_r10_m24_*` (5 cases) |
| M-4 | `report._stat` (one `open_` test) | `test_report.py::test_r10_m4_*` (2) |
| M-27 | `report._n` (tags every span with `data-path`), `report.render`, `report.check_rendered` | `test_report.py::test_r10_m27_*` (2) |
| M-7 | `credibility.build` (`ledger_problems`), `report.build`/`_render` (page line), `__main__._report` (stderr `warning:`), `report._stat` (counts and finiteness) | `test_cli.py::test_r10_m7_*` (2), `test_report.py::test_r10_m7_*` (4 cases) |
| M-21 | `report._emulator` reads `whatif.LIMITS` | `test_report.py::test_r10_m21_*` |
| M-3 | `pipeline._orca_covers` + `pipeline._lon_arc_covers` | `test_pipeline.py::test_r10_m3_*` (12 cases) |
| M-8 | `pipeline.ocean_box` (the function `load_mission` and the ingest both call) | `test_config.py::test_r10_m8_*` (3) |
| M-25 | `pipeline._tao` (citation of the two bias entries) | `test_pipeline.py::test_r10_m25_*` |
| M-32 | `pipeline._assumed` + new `pipeline.provenance` (both on `credibility._prov`); `__main__._hangar` | `test_cli.py::test_r10_m32_*` (2) |
| M-16 (option 2) | `report._overdepth_note`, `report._drivers`, `report._vehicles` | `test_report.py::test_r10_m16_*` (2) |

Files changed: `cafe/pm/__main__.py`, `config.py`, `credibility.py`, `pipeline.py`, `receipts.py`, `report.py`; `tests/test_cli.py`, `test_config.py`, `test_pipeline.py`, `test_receipts.py`, `test_report.py`.
Not touched: `audit.py` (not needed: `ledger_problems` already reaches the report through `credibility.Facts.problems`, which is now also written into `credibility.json`), `par.py`, `glider.py`, the platform yamls, `whatif.py`.

## Verification

- Failing before, shown: the final versions of `test_cli.py test_report.py test_receipts.py test_config.py test_pipeline.py` copied onto a detached worktree of `6c352ef` (`PMX=pm_r10amut`, `-k r10`, `-n 2`): 37 FAILED, rc=1. They are the cases of M-5 (6), M-9 (3), M-24 (5), M-4 (2), M-27 (2),
  M-7 (2 + 4), M-21 (1), M-3 (4 of 12; the other 8 are controls that pass before and after, on purpose), M-8 (3 cases; the control `..._the_demo_...` passes before and after), M-25 (1), M-32 (2), M-16 (2). The tests I changed because the behaviour they pinned changed
  (listed per finding) were not part of that run.
- Whole files run, all rc=0 (`-n 2 --dist loadfile`, orca): `test_cli test_report test_receipts test_credibility test_config test_pipeline` on the tree before the last two edits (comment lengths for ruff, one unused variable in a test), then `test_cli test_report test_config` again on the
  committed tree; and the callers of what changed: `test_audit test_acceptance test_budget test_ledger test_reproducible test_vv test_stats test_comms test_glider test_stage1 test_whatif` (one failure there, `test_acceptance.py::test_a_missing_broken_file_fails_the_check`, led to keeping
  `FileNotFoundError` in `receipts.run`; `test_receipts test_acceptance` then passed). `ruff check cafe/pm tests` clean, `mypy cafe/pm` clean (strict), `audit.banned()` returns `[]`.
- Not run: `test_stage3.py` and the rest of the suite (they read `config.json_object`, which did not change); no coverage run; no mutation run.

## Per finding

### M-5  Damaged or unwritable paths give tracebacks where sister cases give `error:` (rc 2)

What changed. (1) `main()` now ends with `except OSError as e: print(f"error: {e}"); return 2`, so every command gets it (`--out` an existing file, `--out` below a file, `receipts --broken <missing>`, `--run` a directory that cannot be read).
(2) `config.damaged_run_files(run)`, a context manager, turns `KeyError`/`TypeError` into `ConfigError("<run>: damaged or incomplete (<original type and text>); run it again (--fresh)")`; the original text stays, so a code bug is not hidden. Used around
`Context(...)` + `report.write` in `_report` (plan `{}`, refit entry without `used`, ...) and around the baseline reads in `_whatif` (`["summary"]["vehicles"]`, `r["used"]`, `track_points`).
(3) `report.build` raises `ConfigError` (was `FileNotFoundError` with "run the stage1b stage first", which cannot be followed) for a missing `stage1b/summary.json`: "...; this is not a finished run: rerun it (--fresh)".

Deliberately not done: `receipts.py:446` still raises `FileNotFoundError` (the merged text proposed ConfigError). `acceptance.check_broken` catches exactly that exception (`acceptance.py:355`; batch F's file); changing it broke
`test_acceptance.py::test_a_missing_broken_file_fails_the_check` (found by running it). `main`'s OSError catch already gives `error: broken configuration X: no such file`, rc 2, which the new CLI test pins.

DECISIONS row. "`main` ends a command with `error: <text>` and exit 2 on any `OSError` (a path the user named that cannot be made or read), not a traceback; a file of a finished run that is valid JSON but lacks a key or has the wrong type is a
`ConfigError` through `config.damaged_run_files` in `report --run` and `whatif` (message keeps the KeyError/TypeError text). `report.build` refuses a run with no `stage1b/summary.json` with a `ConfigError`. Stage failures keep exit 1 and
the mission and plan keep exit 2; an `OSError` that is a full disk or a lost mount is now also exit 2, with its text." Amends 258 (exit codes) and 374 (run files read back: the shape, not only object-ness).
CHANGELOG. "Any `OSError` ends a command in `error: ...` and exit 2; `report --run` and `whatif` name a damaged or incomplete run file in an `error:` line (exit 2) instead of a KeyError/FileNotFoundError traceback; DECISIONS <n>."
Doc sentences. RUNBOOK troubleshooting: add a row "`error: <run>: damaged or incomplete (KeyError: ...); run it again (--fresh)` (exit 2): a file of the run directory is valid JSON but lacks a key (hand-edited or from other code); rerun
the run". The "exit code 2 and `error: ...`" row (RUNBOOK 266) can add "or a path that cannot be created or read".
What could break, checked. Callers of the changed raise sites: `report.build`/`report.write` are called by `pipeline.s_report`, `__main__._report`, tests only; nothing catches `FileNotFoundError` from them (grepped `except.*FileNotFoundError|OSError` in `cafe/pm`:
only `acceptance.py:355`, for `receipts.run`). The OSError catch in `main` changes rc 1 -> 2 for an OSError escaping any command (`acceptance`, `ingest-ocean`, `fetch`); the wait scripts read "rc != 0", not the value. The test that pinned the old exception
type (`test_a_run_with_no_stage1b_summary_is_refused`) was changed to the new type and message; no assertion was weakened.
RC-1 siblings. `__main__._whatif` covered. `stage1.py:873` (`python -m cafe.pm.stage1` sensitivity command: `{k: v for ... if v["used"]}`) has the same unguarded `v["used"]` inside a `try ... except ConfigError`; it is batch B's file and was not touched
(see "needs from other batches"). `credibility.py:173, 346` and `dtmb5415.py:541` read through `json_object`/tolerant readers and are called inside `report.write` (covered) or already catch `ConfigError`.

### M-9  A run without `windows/windows.json` renders a report that drops the stage-3 markers silently

What changed. `NO_WINDOWS = "windows/windows.json is not in the run directory"`. When `wins is None` (the file is absent; `{}` is a run with no windows and stays quiet): `map.windows_missing`, `environment.forcing_missing` (new keys, `None` normally) and, per
stage-3 row, `t_missing` (new key) carry the sentence, and the page prints it ("Stage-3 window positions are not shown: ...", "Forcing at the worst windows is not shown: ...", "Time not shown: ..." in the window card). `_stage3` also says
"windows/windows.json has N window(s) for <vid>, none for W<i>" when the file is there but has fewer windows than stage 3 has rows (same silent `t=None` before). `report.json` keeps every older key.
DECISIONS row. "The windows stage always writes `windows/windows.json` (`{}` when there are none), so an absent file is damage: the map, the 'worst windows' forcing and each stage-3 window card print `windows/windows.json is not in the run
directory` where they would print the markers (`windows_missing`, `forcing_missing`, `t_missing`). A file holding `{}` is a run without windows and says nothing." CHANGELOG. "The report says when `windows/windows.json` is missing instead of dropping the
stage-3 markers; DECISIONS <n>." Doc: none needed (RUNBOOK may list the three phrases under the report's degraded-run sentences).
What could break, checked. Readers of `map.windows`/`forcing_at_windows` keep the same keys and `{}`; the new keys are strings or `None` (the `walk` helper in test_report rejects bare numbers: none). `credibility` does not read them.
The fixture in `pm_run.make_run` has a stage-3 row beyond its windows.json entries, so the intact-run test only asserts `t_missing` where `t` is `None`.

### M-24  A stored slow receipt that is a JSON object without its keys raises `KeyError`

What changed. `receipts.slow_group` reads `date`, `host`, `git_sha`, `code_digest` and builds the tagged rows into locals inside `try ... except (KeyError, TypeError, AttributeError, ValueError)` before it touches `R.OUT`; on failure the reason is
"the stored result at <p> is not a receipt record (missing or wrong-typed fields); the command above writes it again" and the shared `NotRun` row with the command follows. The five shapes tested: `{}`, digest only, `git_sha` not text, `rows` not rows,
old digest and no `git_sha`.
DECISIONS row. "A stored slow receipt that is valid JSON but not a receipt record (a field missing or of the wrong type) is a `not_run` row with its command, like a damaged file; nothing is added to the table from it." Completes and amends 452.
CHANGELOG. "A stored slow receipt of the wrong shape gives the 'not run' row with its command, not a KeyError; DECISIONS <n>."
What could break, checked. `slow_group` is the only reader of these files (`app.fea`, `pm.physics.uas.slow`, `pm.emulator`); `_save` cannot write the bad shape. A good record still extends `R.OUT` with the same `source` text (the tag text is unchanged).
I did not add `required_keys` to `config.json_object`: the other `json_object` callers read run outputs, not records with a fixed key set.

### M-4  Six cards say "needs 73 members" and then "no number of members certifies it"

What changed. `report._stat` computes `open_ = exercised and wilson_lower(k, n, 95 %) < 0.05` once. `n_certify` is a node only when `open_` (None for a NOT EXERCISED link, as before, and now also for an excluded P(fail)), so `_stat_html`
prints no parenthesis. The statement: excluded wording for `exercised and not open_` at any n (it used to appear only when `n < n_certify`); "cannot be certified at n" for `open_ and n < n_certify`. The optional D-12 change (order of the clauses on
GO cards) was not made: both bounds are labelled and the difference is deliberate (PHYSICS 849).
DECISIONS row. "`report._stat` sets `n_certify` to None, and `_stat_html` prints no 'certifying P(fail) < 5 % needs N' parenthesis, for any card whose 95 % Wilson lower bound on P(fail) is 5 % or more (no member count certifies it), not only for a NOT EXERCISED link;
the 'excluded by this ensemble' sentence is printed for such a card at any n (it was silent at n >= n_certify)." Amends 526 (the parenthesis 'claimed no shortfall': wrong for an excluded card) and 533. CHANGELOG. "A card that excludes P(fail) < 5 % no longer
says how many members would certify it; DECISIONS <n>." Doc: none.
What could break, checked. Readers of `n_certify` in report.json: only `_stat_html` and `check_rendered` (a None node is skipped by `_walk`); `credibility.py:584` and `stage1.py`/`pipeline.py` read the stage summary, not the report. A `report.json` reader now finds `n_certify: null` on those cards.
Tests changed because the behaviour they described changed: `test_not_certifiable_below_n_certify` (excluded cards: `n_certify` None, statement kept), `test_certifiable_at_large_n` (an excluded vehicle at n = 80 now has the 'excluded' statement, none has 'cannot be certified'),
`test_a_not_exercised_links_card_has_no_certifying_sentence_and_the_other_cards_keep_theirs` (the 'other' card is `glider_2n`, 0 of 48; `glider_eq-ship-acoustic`, 12 of 48, is excluded).

### M-27  `check_rendered` accepts a dropped number whenever its text occurs anywhere on the page

What changed. `report._n` tags the first anchor of every number span with `data-path="<path(s) in report.json>"` (filled by `render` from `_walk(rep)`, keyed by object id, cleared in a `finally`). `check_rendered` keeps its old rule (every node text is a whole token
somewhere in the page) and adds: if the page prints a path *shape* (`vehicles.*.modes.battery`; `INSTANCE` replaces the id after `vehicles|links|windows|forcing_at_windows|refit` and `[n]`) for any vehicle, link or window, every node of that shape
must be printed under its own path with its own text. A shape the page prints nowhere is not asked for.
Why a shape rule and not "every node is printed": I audited q10 (535 number nodes, 273 distinct texts, 525 paths printed as spans) and the test fixtures first. Some nodes are in `report.json` only or inside a sentence: in q10 `mission.box`, `map.vehicles.*.deploy`
(drawn, not printed) and the `sensitivity_scope.*` nodes (written into a sentence by `_sens_scope`); in the fixtures also `fix.best.cost` (the same change is in `tried`) and `stage3.refit.*.drag.change_vs_hangar`. A rule of "every node is a span" failed a dozen tests of `test_report.py` on the
first try and would have failed the report stage (and `report --run`) on any run with a flip search.
A count rule ("spans with this text >= nodes with this text") was tried first and is too weak: the page prints some nodes twice (64 members: 13 nodes, 30 spans), so the slack hides a dropped instance.
Shown on q10: with the rule, removing the text of one single-path span ("0", "1", "64 members", "0 members") is found in each case (the old rule found none); the intact q10 report.json renders and checks clean.
DECISIONS row. "`report._n` records the node's path(s) in report.json in a `data-path` attribute; `check_rendered` asks, besides the whole-token rule of 175, that a node of a shape the page prints for another vehicle, link or window is printed under its own path with
its own text. Nodes in report.json only are not asked for." Amends 175 and 533 (the 73-members case is now caught). CHANGELOG. "`report_html_matches_json` finds a card that stops printing a number other cards print; DECISIONS <n>."
Doc: the docstring says it; RUNBOOK may say the check compares per path.
What could break, checked. index.html bytes change (the attribute), so its sha256 and any golden holding index.html bytes change; I found none (`acceptance.py` reads index.html for `cpu_fallback` text only). Old index.html files are not re-checked. `test_report.py:482`
pins `<span class=n>0.42<a` and still matches (the attribute is on the first anchor). The old unit test of the token rule (`test_check_rendered_matches_whole_numeric_tokens`) is unchanged and passes: pages without `data-path` are judged by the old rule alone.
Open: nodes that are in report.json and printed only for some instances of a shape (conditional printing) would be false failures. None exists in q10 or the fixtures; if one shows up the fix is to give that shape its own path or drop the node.

### M-7  `report --run` renders a GO from a hand-edited summary with exit 0 and clean traceability

What changed. Decision per the lead's note and DECISIONS 515: a warning, not a failure (an older run whose stage-3 ledger holds an older `assumptions.yaml` must stay re-renderable). `credibility.build` now also writes `ledger_problems` (the list
`Facts.problems` already held: `audit.ledger_problems` without 'stage report' and 'no ledger'); `report.build` copies it to `report.json` `ledger_problems`; `render` prints a warning paragraph above the verdict table naming the first five and the count
("The ledgers of this run do not match its files ... `python -m cafe.pm audit --ledgers-only` lists them"); `report --run` prints each as `warning: ...` on stderr; exit stays 0 and the report ledger is re-recorded as before (476).
Sibling fields, per field. `verdict.n` and `verdict.k_fail` are compared with `n` and `k_fail` of the same summary entry: a difference is a `ConfigError` (exit 2). `verdict.p_fail`, `fail_lo`, `fail_hi` must be finite numbers, else `ConfigError`. NaN to null in `_f` stays (it is deliberate for
real data). The verdict string and `p_fail` against `k_fail/n` are not recomputed: the thresholds come from the mission and an older run may have used others; the ledger warning covers a hand edit that keeps the numbers consistent (the example in the finding).
DECISIONS row. "`report.json` carries `ledger_problems`, the problems `audit --ledgers-only` finds in the ledgers the report reads; the report page prints them above the verdict table and `report --run` prints them as `warning:` lines (exit 0: row 515 keeps older runs
re-renderable). `report._stat` refuses a summary entry whose `verdict.n` or `verdict.k_fail` differs from its own `n`, `k_fail`, or whose `p_fail`, `fail_lo`, `fail_hi` is not finite." Amends 476; relates 515. CHANGELOG. "`report --run` and the report page warn when the
ledgers do not match the files; a summary whose verdict disagrees with its counts is refused; DECISIONS <n>." Doc: RUNBOOK report paragraph (line 166): add the warning sentence; 515's last sentence ("prints no extra line") is no longer true.
What could break, checked. Every report test that edits a stage output after the ledgers were written now shows the warning (a hand edit by definition). One test failed for that reason: `test_a_window_cut_...` asserted that `3500` is not on the page and its tmp directory was named `r3500`; the
directories are now `cut0`/`cut1`. A clean run's `report.json` is unchanged but for `ledger_problems: []`. A run with problems puts absolute paths into report.json (as `credibility.json`'s `missing` text already does). `Facts.problems` is not computed twice.

### M-21  The report prints the BRIEF 2.7 limits from constants, labelled as `whatif.LIMITS`

What changed. `report._emulator` imports `LIMITS` from `whatif` inside the function (whatif imports report) and builds the three limit nodes from it. `whatif.py` is not edited. `emulator.py:376-378` (`receipts()`, its own gate) was not touched (the constant would have to move
to a lower module such as `budget.py`).
DECISIONS row. "The report's emulator acceptance limits are read from `whatif.LIMITS`, the constant the gate judges against, not typed again in `report.py`." CHANGELOG. "The emulator limits in the report follow `whatif.LIMITS`; DECISIONS <n>." Relates 397 (the test fixture's
`query_ms` 1e9 is now what a test report prints). Doc: none.
What could break, checked. `test_report.py` pinned `limits.rmse == 0.05` and `query_ms.unit == "ms"` (still true; the `query_ms` value in tests is now conftest's 1e9, not asserted). Old holdout.json files have no limits and none is read from them.

### M-3  The orca cache check compares longitudes without the antimeridian

What changed. `pipeline._lon_arc_covers(have, want)`: the west->east arc of the cache contains the arc of the wanted box (width `% 360`, 360 or more is the whole circle, 1e-9 tolerance); `_orca_covers` uses it for longitude and keeps the raw latitude test. Cases pinned: the
reviewer's repro (False), wrapped cache against the same wrapped box (True), wrapped cache against a non-wrapped box inside it (True; was False), the same arc written past 180, 358 deg and 380 deg caches, a wanted box of the whole circle.
RC-3 sweep, as asked. Every production `box360` caller takes its box from `pipeline.ocean_box(mission)` (`pipeline.py:256, 392, 421, 435-443, 516, 712`, `__main__._ingest_ocean`); `box360` itself still takes a raw width of 360 or more modulo 360 (a thin strip). The hole is closed
at `ocean_box` (M-8), so no caller can reach it from a mission; a direct call of `box360`, `tao.fetch_tao`, `bathy.fetch_gebco`, `hycom.fetch_gofs` with such a box (tests, future code) is still unguarded. Batch D could add `if e - w > 360: raise ValueError` to `hycom.box360`; I did not
touch `env/`. `orca._drop_stale_parts` compares lists exactly and `orca.box_index` goes through `lon360`: unaffected.
DECISIONS row. "`pipeline._orca_covers` compares the cache box's longitudes as arcs (`_lon_arc_covers`: west to east modulo 360, a width of 360 or more is the whole circle), as `_tao_cached` and `_ocean_cached` do through `hycom.box360`; latitude stays a plain comparison." Agrees with 474 and 480; relates 372.
CHANGELOG. "The orca cache check handles a box across the antimeridian; DECISIONS <n>." Doc: none. What could break: a cache that used to be refetched without need (wrapped cache, non-wrapped box inside it) is now reused; one that was wrongly reused (the repro) is refetched. Both are the right direction.

### M-8  A padded box beyond +-90 degrees latitude, or a full-circle strip, passes `load_mission`

What changed. In `pipeline.ocean_box` (called by `load_mission`, which prefixes the path, and by the ingest, `__main__._ingest_ocean`, `s_ingest`, `pipeline.ocean`): `ConfigError` when `lat_min - pad < -90` or `lat_max + pad > 90` (names the pad and `box.pad_deg`), and when
`((lon_max - lon_min) % 360 or 360) + 2*pad >= 360` ("a full circle or more"). Refusal, not clipping, as the lead decided; exactly +-90 and 360-wide-minus-epsilon still load. `hycom.box360` is unchanged (it keeps its 95-degree tolerance test and its 0 E refusal; a box that is both narrower than 360 and across
0 E still gets the 0 E message).
DECISIONS row. "`pipeline.ocean_box` refuses a box whose pad takes it beyond +-90 degrees latitude or makes it 360 degrees wide or more (`box360` would take the width modulo 360 and fetch a thin strip); it is the one function `load_mission` and the ingest both call." Agrees with 372; relates 474, 480.
CHANGELOG. "A mission box that the pad pushes past a pole or around the globe is refused at load; DECISIONS <n>." Doc: RUNBOOK mission-box sentence may add "at most +-90 degrees with the pad, and less than 360 degrees wide with it".
What could break, checked. The demo box (lat -5..5, pad 2, lon 165..-165) and ci_fixture load (test: `test_r10_m8_the_demo_...`). A pole-adjacent real mission (north edge above 88 with a 2-degree pad) is now refused where the server would have clipped; no shipped mission is near a pole.

### M-25  The fitted wind prior citation says "WRF minus 11 moorings" over a mean of the opposite sign

What changed. In `pipeline._tao`, the citation of `wind_speed_bias` and `wind_direction_bias` gets "mean = minus the N-mooring mean error, i.e. mooring minus WRF: the correction perturb.py adds to WRF (the error itself is WRF minus mooring, +0.61 m/s)" before the
'persistent part only' text. The mean is not changed. The noise entries keep the data-side citation. The existing test (`"2 moorings" in citation and "persistent part only" in citation`) still holds.
DECISIONS row. "In `ingest/priors_fitted.json` the citation of each bias entry says that `mean` is minus the mooring-mean error (mooring minus WRF, the correction added to WRF) and gives the error with its sign." Note under 45 and 182. CHANGELOG. "The fitted wind-bias citation states the
sign of its mean; DECISIONS <n>." Doc: PHYSICS.md around line 483-493 can carry the same sentence.
What could break, checked. The citation text is inside `priors_fitted.json`, which is a hashed output (the ingest ledger and downstream `input` hashes change for a new run, not for old ones); `credibility.Facts.assumed_perts` looks for "ASSUMED" in the citation (not present). I did not check whether report.py or credibility.py print the citation next to the mean (grep: they do not).

### M-32  `hangar --platform modems` counts 2 assumed inputs; the report counts 4

What changed. `pipeline.provenance(node, file)` returns `credibility._prov`'s items (imported inside the function: credibility imports pipeline); `pipeline._assumed` counts `assumed` among them; `__main__._hangar` prints `N of M values assumed` and lists every item with its path, value, unit and
why/source, so the two modem entries (`modems.benthos_atm960 = None`, ...) are listed. `hangar.json` per-vehicle `assumed` uses the same count. The line still says "values" (the RUNBOOK and DECISIONS 408 quote it); it counts provenance items, which are values and entries marked assumed. If the lead
prefers "items" it is one word in `_hangar` and the two tests that pin the line.
Checked on orca: for the six shipped files (`modems`, `radios`, `seaglider`, `slocum`, `saildrone_explorer`, `quad_uas`) the printed count equals `credibility.platform_items()` for the file, and the number of listed lines equals the denominator (new test).
DECISIONS row. "`hangar` counts provenance items with `credibility._prov` (a leaf `assumed: true` and an entry-level `assumed: "<sentence>"` alike), so `hangar --platform modems` says '4 of 4 values assumed' like `credibility.json`; `pipeline._assumed` is that count." Amends 408 ("2 of 2")
and 329. CHANGELOG. "`hangar` counts assumed inputs the way the credibility report does (modems: 4, was 2); DECISIONS <n>." Doc: RUNBOOK 5a unchanged (it already says `hangar` shows every assumed input).
What could break, checked. `tests/test_cli.py::test_r8_m16_hangar_modems_counts_the_two_assumed_defaults` pinned `2 of 2`; it now pins `4 of 4` (same test, the two default lines still asserted). Values that are strings print with their repr (quotes), as `credibility` stores them; for the shipped files none is a string
(the hangar listing test still passes). The ledger of the hangar stage: `hangar.json` content changes only for a platform with an entry-level `assumed` string.

### M-16  A glider dive depth within about 7 m of the rating is accepted and fails overdepth in every member (option 2)

What changed. `report._overdepth_note(vehicle, res_entry)`: for a glider with `overdepth` among its modes the card gets a mode note: "the depth passed the platform's rating_m (1000 m): the ordered dive depth (1000 m) plus the apogee overshoot (the glider keeps sinking while the buoyancy pump runs,
platform apogee_overshoot) exceeded it; the measured peak depth of the members that failed this way was 1007.4 m, 7.4 m past the order; this is the vehicle's own overshoot at that order, not a fault of the mission of another kind". The peak is the maximum of `res.pkl` `depth` over the members whose
`first.overdepth` is finite; without `res.pkl` the measured clause is left out. Loader, model, platform files and `glider.py` are untouched. Slocum gets the same note (same mode).
DECISIONS row. "The report explains the glider mode `overdepth`: ordered dive depth plus the apogee overshoot passed `rating_m`, with the peak depth measured in the members that failed this way. The loader still accepts an ordered depth up to `rating_m`; the model is unchanged." Relates 50 and 316 (RUNBOOK:94
already says 'ordering 1000 m trips overdepth'). CHANGELOG. "The report says an overdepth failure is the glider's own apogee overshoot, with the measured peak; DECISIONS <n>." Doc: RUNBOOK:94 can add that 995 m also fails (cut-off near 992.6 m for the Seaglider at the measured last descent speed), and that the report explains it.
What could break, checked. `mode_notes` is rendered for any key (`_vehicle_html` prints every entry), so nothing else needed a change; the key is added only for gliders with `overdepth` in `modes`. `_drivers` has a new optional argument; its other caller path is unchanged.

## Mutants (a throwaway detached worktree at the commit, removed afterwards)

Several tests fail on the old code partly because a new name is missing (`report.PRINTED`, `report._overdepth_note`), so the behaviour was also checked by breaking the fixed code one line at a time (each run: the named tests only, `PMX=pm_r10amut`, rc=1 each time, the worktree reset after each):

| mutant | test that fails |
|---|---|
| M-27: `check_rendered` without the per-path rule | `test_r10_m27_a_card_that_stops_printing_a_number_the_others_print_...`, `test_r10_m27_every_number_node_of_a_rendered_report_is_printed_under_its_own_path_...` |
| M-16: the measured peak clause of `_overdepth_note` removed | `test_r10_m16_overdepth_is_explained_from_the_measured_peak_depth` |
| M-16: the note not attached to the card's `mode_notes` | `test_r10_m16_a_glider_that_failed_overdepth_carries_the_explanation_in_its_card` |
| M-4: `open_ = exercised or ...` (n_certify kept for an excluded card) | `test_r10_m4_an_ensemble_that_excludes_p_fail_below_5_percent_has_no_member_count_to_ask_for` |
| M-7: `credibility.build` writes `ledger_problems=[]` | `test_r10_m7_a_hand_edited_summary_is_rendered_with_a_warning_above_the_verdicts` |
| M-8: the width test made unreachable (`>= 3600.0`) | `test_r10_m8_a_box_that_the_pad_makes_a_full_circle_is_refused_where_it_used_to_become_a_thin_strip` |

## Needs from other batches

- Batch B (`stage1.py`): `python -m cafe.pm.stage1` (sensitivity command, line ~873) reads `refit.json` with `v["used"]` inside `try ... except ConfigError`; wrap that block in `with config.damaged_run_files(rd):` (or add `except (KeyError, TypeError)`) so a refit entry without `used` is
  an `error:` line. Same defect as M-5, same helper.
- Batch D (`env/hycom.py`): optional defence in depth: `box360` refuses a raw width of more than 360 (`e - w > 360 + 1e-9`); after M-8 nothing reachable from a mission needs it. Its pinned 95-degree latitude tolerance (`test_hycom.py:132`) is not affected.
- Batch F (`acceptance.py`): nothing needed; note that `acceptance.check_broken` depends on `receipts.run` raising `FileNotFoundError` for a missing `--broken` file (kept).
- Batch F (docs): the DECISIONS rows and CHANGELOG lines above; RUNBOOK sentences named per finding (M-5 troubleshooting row, report paragraph for M-7, mission box for M-8, glider depth for M-16); PHYSICS 483-493 for M-25; DECISIONS 515 now reads "prints no extra line" falsely (M-7).

## M-35: messages that differ from the RUNBOOK (documents; no code changed)

- `python -m cafe.pm audit --bogus` prints argparse usage with "unrecognized arguments" (front door); "error: unknown option --x" comes only from `python -m cafe.pm.audit`. The RUNBOOK row should say which entry point prints which. No code message is wrong.
- `report --run` on a directory with no `mission.yaml` prints "<dir>/mission.yaml: file not found"; the RUNBOOK row ("no plan.json; this is not a finished run directory") is right only for a directory that has `mission.yaml` but no `plan.json`. A code message that arguably should change: for a directory with neither file,
  `_report` could check `plan.json` first so that the "not a finished run directory" text is the one printed; `tests/test_cli.py::test_report_of_a_directory_that_is_not_a_run_exits_2` pins the current order, so I left it.
- `CAFE_WORKERS=' 3'`, `'+3'`, Arabic-Indic digits are accepted by `par.env_count` (`int()`); requiring `v.isascii() and v.isdigit()` would match the RUNBOOK's "a whole number of at least 1". Not changed (`par.py` was not needed by anything else).

## Not done / open

- M-4's optional D-12 clause order on GO cards; M-21's move of the limits to a lower module for `emulator.receipts`; `required_keys` on `config.json_object` (M-24); the `box360` guard (M-3 sibling); the three `needs` above.
- M-27 asks for a node printed under its own path only where its shape is printed elsewhere; a report whose whole section stops printing (every instance) is still caught only by the old whole-token rule.
- No new problem rows in `review/orca/PROBLEMS.md` were needed.
