# Round 12 batch B hand-back (branch r12-b, worktree cafe-r12b)

Findings M-2, M-7, M-22, M-24, M-20, M-28, M-23, M-21. No DECISIONS, CHANGELOG, RUNBOOK, PHYSICS or CREDIBILITY file was edited; the text for them is below.
DECISIONS numbers are left blank (`NNN`): batch F numbers them after 640.

Everything ran on orca (proot, 2 CPUs, `pm_r12b*` directories, logs `r12b_*`). Gates on the final tree: ruff (`cafe/pm tests`) clean, mypy strict (`cafe/pm`, 55 files) clean,
the whole test files touched ran on the final tree (counts are the progress-line characters, as CLAUDE.md says to read them): tests/test_cli.py 153 passed (rc=0), tests/test_pipeline.py 317 passed (rc=0),
tests/test_stage3.py 190 passed (rc=0), and tests/test_config.py + test_budget.py + test_par.py + test_cli.py in one job 512 passed, 2 failed: those two are the first draft of the M-7 test (a flip.json parameter that is a TypeError path, not an AttributeError one), which I replaced and
which the later whole-file run of test_cli.py passes; test_config.py, test_budget.py and test_par.py were not edited after that job started. One more whole run of test_pipeline.py on the tree before the M-20 docstring assertion also passed (rc=0).
Not run: test_config_docs.py (reads RUNBOOK and DECISIONS, which this batch does not edit; it reads only the top-level keys of mission.json, which are unchanged).

Order done: M-2, M-7, M-22, M-24, M-20, M-28, M-23 (no code), M-21 (tests only).

## Regression tests: failing before, passing after

The new tests were copied onto a detached worktree of a8b8bb1 (`cafe-r12b-mut`, removed afterwards) and run there on orca: the M-2, M-7, M-22, M-24 and M-28 tests fail on the unfixed code
(M-2: DID NOT RAISE for a link called `usv`, `ship`, `shore`, empty, quote and markup; M-22: exit 0 for validate, plan, fetch and hangar; M-24: the old text
`box (-7.0, 7.0, -12.0, 12.0)`; M-28: `600000000.0 == 0.0`; M-7: `AttributeError: 'int' object has no attribute 'get'` escapes as a traceback for an int and for a list; M-20: the docstring assertion). M-20 is a documentation error: `padding` itself was right, so the function-level asserts pass on the old code by design (they pin the
numbers the documents now state) and the test fails before only through its docstring assertion ("about 24.4 days"). M-21 is tests only: three hand-made mutants of the production constant
(`wallmodel.YPLUS_LAM` 11.06 -> 11.0, `pipeline.CALM_SWH_M` 1e-3 -> 5e-2, `pipeline.FLAT_SHARE_MAX` 0.01 -> 0.03), each run alone in the throwaway worktree: each is killed by its new test (rc=1, only that test fails).

## M-2 link, ship and shore ids are one namespace with the vehicles

What I found when I grepped for ids that reuse a vehicle id or break the vehicle pattern `^[A-Za-z0-9_-]+$`: `missions/` has two files, `ci_fixture.yaml` and `tepex_c_demo.yaml`. Their link ids are
`usv-uas-rf`, `glider_eq-ship-acoustic`, `usv-shore-iridium` and, in the demo only, `glider_2n-ship-acoustic`; ship `ship`, shore `shore`. Vehicles are `glider_eq`, `usv`, `uas` and `glider_1n` (ci_fixture) or `glider_2n` (demo).
None equals a vehicle id, another link, ship or shore id, and all match the pattern. `tests/fixtures` holds no mission YAML (the ci_env fixture is environment data); the tests build missions
by editing a dict loaded from `missions/tepex_c_demo.yaml` or `ci_fixture.yaml`, and the only link id they add is `gl-x` (test_config.py, `_glider_link`), which is fine. A scan of the double-quoted `"id": "..."` literals in tests/*.py found only `g`, `x`, `a`, `b`, `u`, `m1`, `c`, `bench` and `az_serv`,
all ids of vehicles or of dicts in unit tests that never call `load_mission` (a grep, not a proof: whole test files ran, see the test runs). No shipped mission is refused by the new rule (`test_r12_m2_the_shipped_missions_use_no_id_twice` holds it).

DECISIONS row:
> NNN | Vehicle, link, ship and shore ids are one namespace. `load_mission` refuses an id used by two of them ("ids must be unique across vehicles, links, ship and shore; 'usv' is used by vehicles/usv and links/usv"; two links of one id keep `_check_links`'s message, row 200), and `cafe/schemas/mission.json` gives all four the vehicle id pattern `^[A-Za-z0-9_-]+$` through one `$defs/id`, so an empty id and an id with a quote, an angle bracket or a space is a schema error naming the field. | Review round 12, M-2 (D-1, major). A link called `usv` took the vehicle's row in the report's Verdicts table (`{**vehicles, **links}`) and showed a NO-GO vehicle as GO, dropped the vehicle's row, and emitted `id="v-usv"` twice; both self-checks passed because JSON and HTML are built from the same merged dict. Results, tables, anchors and credibility's robustness and EXPECTED lookups are keyed by id, so the cure is one namespace at load, in the one function every command goes through. |

Amends: 250 (it says an id may be used once across `vehicles`, `ship` and `shore`: add `links`, row NNN), 200 (a duplicate link id: the cross-namespace check is the new row, the duplicate-link message
stays), 155 (the list of what `load_mission` refuses: add "an id of a link, ship or shore that is no vehicle-pattern name").

CHANGELOG: `Fix: a link id equal to a vehicle, ship or shore id (and an empty id, or one with a quote or angle bracket, on a link, the ship or the shore) is refused at load; it showed the link's verdict under the vehicle's name in the report's Verdicts table; DECISIONS NNN.`

Doc sentences: RUNBOOK, where the mission file's ids are described (the mission schema section): "Vehicle, link, ship and shore ids share one namespace and use letters, digits, `_` and `-`; no two may be equal." RUNBOOK troubleshooting table: a row for
`error: ...: ids must be unique across vehicles, links, ship and shore; 'X' is used by A and B` (cause: two ids equal; fix: rename one) and one for a schema error `links/N/id: '' does not match` (cause: an id with a space, quote, bracket or no characters).

What I checked could break, and how:
- Callers: `load_mission` is the one reader of mission files (run, fetch, plan, validate, whatif, report --run, acceptance, receipts, `Context`, stage1's CLI); all route through it, so there is one place and no caller change. The ids' consumers (`stage1._classes`, `_pos`, `report`, `credibility`) read `m["links"]`
  and `m["vehicles"]` after it; the three merged dicts (report.py `_sanity` at :1051, the Verdicts table at :1677, credibility.py :654, :753) can no longer collide for a mission that loaded.
- A lab mission that has a ship called `R/V x` or `ship 1`, or a link id with a dot or a space, is now refused (before: accepted). Shipped missions are unaffected. The error names the field and the pattern; the fix is to rename. Runs made with such a mission (their `mission.yaml` is reloaded by `report --run`, `whatif --run`) now stop at load with exit 2, naming the id.
- `report --run` on an old run directory whose `mission.yaml` has a link equal to a vehicle id now exits 2 at load instead of re-rendering the wrong table: intended.
- Two links of one id: still `_check_links`'s "link ids [...] appear more than once" (test_config.py:320 unchanged and passes), because the new owners list is deduplicated.
- Trailing newline (row P-R12B1 in review/orca/PROBLEMS.md): the schema pattern uses `$`, which Python's `re.search` lets match before a final newline, so an id `usv\n` (a YAML block scalar) is still accepted. That was so for vehicle ids already; the ids stay distinct from each other so no row is shadowed; I did not change the pattern (a `\Z` is not ECMA-262, which the schema is written in). A sibling, not fixed.
- The existing assertion in test_config.py (ROUND4, "M-14 ship = vehicle") changed its expected text to the new "vehicles, links, ship and shore".

Needs from other batches (see the last section): the optional Verdicts-table keys (`vehicle:` and `link:` prefixes) are in report.py, which batch A edits: handed to A.

## M-7 `damaged_run_files` catches AttributeError

DECISIONS row:
> NNN | `config.damaged_run_files` catches `AttributeError` as well as `KeyError` and `TypeError`: valid JSON whose entry is a number or a list where the report reads `.get` (`emulator/holdout.json = {"glider_eq": 5}`) is "damaged or incomplete (AttributeError: ...)", `error:` and exit 2, not a traceback. | Review round 12, M-7 (D-6). Row 617 chose a per-site tuple and held `TypeError` by a test; `AttributeError` is the type of `.get` on a non-mapping, the one reachable case, and `audit.py` and `ledger.py` already catch it. A real `.get` bug on a run file now prints as damage with exit 2; the message carries the exception name and its text and says "if that gives the same error, it is a bug: report it". |

Amends: 617 (add `AttributeError` to the list of types the guards hold; it said TypeError for this function). 539 and 579/582 are the other guards of the same family and are unchanged.

CHANGELOG: `Fix: report --run on a finished run with a non-object entry in emulator/holdout.json ended in an AttributeError traceback; it is now "damaged or incomplete (AttributeError ...)", exit 2; DECISIONS NNN.`

Doc sentence: none needed (the RUNBOOK troubleshooting row for "damaged or incomplete (KeyError ...)" can say "(KeyError, TypeError or AttributeError ...)").

What I checked could break, and how:
- Callers of `damaged_run_files`: `__main__._report` (two blocks), `__main__._whatif` (line 307), `stage1.main` (line 873). In each the guarded block reads run files; none catches AttributeError itself, and none depends on AttributeError escaping.
  A block that raised AttributeError from a real bug (not data) would now print "damaged or incomplete (AttributeError: ...)" and exit 2 instead of a traceback; the message has the original text. That is the trade row 617 already took for TypeError.
- Which readers reach it: only `report._emulator` (`e.get("trained")` at report.py ~948) raises AttributeError on a non-dict entry; `_fix` (flip.json), `_stage3`, `_vehicles` fail with TypeError (`f["needed"]` on an int), already damage. The test covers holdout.json (int and list) end to end through `cli.main(["report","--run",...])`, and the function directly.
- The first version of my test also tried flip.json; the old code gave `KeyError 'vehicles'` for the shape I wrote, which showed that file is not the AttributeError path; the test is holdout.json only.

## M-22 `CAFE_OFFLINE` is parsed once, at the start of every `cafe.pm` command

DECISIONS row:
> NNN | `CAFE_OFFLINE` is parsed at the start of every `python -m cafe.pm` command (`__main__.main` calls `pipeline._offline()` right after the arguments, inside the `ConfigError` handler): a value that is not one of the documented ones is `error: CAFE_OFFLINE='x' is not 0 or 1` and exit 2 for run, fetch, plan, validate, whatif, report, hangar, audit, receipts and acceptance alike, also on a cache that is complete. The three lazy reads (`pipeline.py` `open_ocean`, `_need`, `_copy_covering`) stay: they are the ones that decide whether to download. | Review round 12, M-22 (B-6). The variable was read only when a download or a missing input made a call to `_offline()`, so on a warm cache `CAFE_OFFLINE=ture` was a silent online run, and RUNBOOK 297 said any other value is an error with exit 2. `CAFE_WORKERS` was already parsed at once. |

Amends: 330 (add: "and the parse happens at the start of every command, row NNN"). The RUNBOOK row at line 297 is true as written once this is in.

CHANGELOG: `Fix: a CAFE_OFFLINE that is not 0, 1, true, false, yes, no, on or off is exit 2 at the start of every command, also when the cache is complete; it was parsed only when a download was due; DECISIONS NNN.`

Doc sentence, RUNBOOK:297: add "(read at the start of every command, so a typo is found before anything runs)".

What I checked could break, and how:
- The only readers of the variable are the three `_offline()` calls in pipeline.py (grep of `CAFE_OFFLINE` in cafe/, bin/, tests/); the call in `main` is the same function, no new parse. `tests/conftest.py` sets `CAFE_OFFLINE=1` for every test, so no test sees a bad value except the new ones.
- A shell that exports `CAFE_OFFLINE=maybe` now fails `report --run`, `hangar`, `audit` and the other commands that never download: stricter than the finding's fetch, plan and validate, chosen because they are one entry point and one rule (RUNBOOK says "any other value is an error"). Documented above as intended.
- Not covered: entry points that do not go through `cafe.pm.__main__`: `python -m cafe.pm.stage1`, `.audit`, `.shares`, `.dtmb5415`, `.env.hycom`, `.stage3.*`. None of them downloads through `pipeline` (the variable has no other reader), so a bad value cannot make them go online; I left them alone.
- `acceptance` runs its sub-runs through `cafe.pm` as subprocesses (each parses it again), and `cli.main(["acceptance", ...])` now stops before any run starts.

## M-24 the padded-box refusals label south, north, west, east

DECISIONS row:
> NNN | The three refusals of `pipeline.ocean_box` (a padded latitude beyond +-90, a width of a full circle or more, a box across 0 deg E) name the padded box as `lat S to N, lon W to E` (`pipeline._box_words`), not as the bare tuple (south, north, west, east), which read as lon first: lon -10..10, lat -5..5, pad 2 printed "box (-7.0, 7.0, -12.0, 12.0)". The rest of each message is unchanged, and so is the box itself (`hycom.box360` and its own messages are not touched). | Review round 12, M-24 (B-11). A reader took the first pair for longitudes; the tuple has no labels and `config.fmt_box`, which has, takes a mission dict and not a tuple. |

Amends: 372 and 542 (the refusals' text: "names the padded box as lat S to N, lon W to E").

CHANGELOG: `Fix: the refusals of a padded box that crosses 0 deg E, reaches a pole or is a full circle print it as "lat -7 to 7, lon -12 to 12", not as an unlabelled (south, north, west, east) tuple; DECISIONS NNN.`

Doc sentence: RUNBOOK:294 quotes only the tail ("the box (with its pad of N deg) crosses 0 deg E; ..."), which is unchanged; if the table gets the prefix it is `error: ...: box lat S to N, lon W to E: the box (with its pad of N deg) crosses 0 deg E; ...`.

What I checked could break, and how:
- `ocean_box` callers: `load_mission` (wraps the message with the path), `s_ingest`, `pipeline.ocean`, `__main__._ingest_ocean`, `open_ocean`; all take the returned tuple and only the three messages changed. Tests that matched the old tuple: test_config.py (three patterns, now `box lat .*, lon .*`) and test_pipeline.py:3200, which matches the tail only and is unchanged.
- The numbers print with `:g`, so a pad of 2 on lon -10 gives -12, a 0.5-degree pad -167.5; nothing is rounded beyond six digits.
- Sibling: `hycom.box360` (hycom.py:77, 79, 81) still prints `box {box}` as a raw tuple in its own ValueErrors. `ocean_box` checks width and latitude first and re-wraps the 0 deg E one, so the only user-facing path is the one fixed; other callers of `box360` (`hycom.padded`, the fetch) pass a box they built, and I left the messages. Not fixed: a direct call of the fetch with a hand-built box.

## M-20 the pad cap is reached at 24.4 days, not 26

DECISIONS row: none new. Amend in place:
> 190 and 229: "about 26 days" -> "about 24.5 days (24.41 d: `padding` = min(10, ceil(days x 86400 x 0.5 / 111e3 x 2) / 2); 24.4 d gives 9.5, 24.5 d gives 10)". Row 229: "10 deg from about 26 days" -> "10 deg from about 24.5 days". Add to 190 or 229: "26 days is the unrounded 10 x 111 km / 0.5 m/s = 25.7 d, which ignores the rounding up to half a degree."

CHANGELOG: `Fix (text): the default pad reaches its 10 degree cap at 24.4 days, not 26 (RUNBOOK 3, DECISIONS 190, 229, the padding docstring); no number changes.`

Doc sentences: `docs/RUNBOOK.md:158` "at most 10, reached at about 26 days" -> "at most 10, reached at 24.5 days (24.4 days gives 9.5)". Code side done: `pipeline.padding`'s docstring (it mixed units: "longer than MAX_PAD_DEG / DRIFT_MS days") and the `MAX_PAD_DEG` comment (`config/schemas` -> `cafe/schemas/mission.json`).
The schema's `pad_deg` description states no day count (checked), so nothing there. Suggestion for F: `tests/test_config_docs.py` could assert RUNBOOK says "24.5 days" next to the cap, so the figure cannot drift back.

What I checked could break, and how:
- Nothing computes from the changed text; `padding` is unchanged (computed: 24.4 d 9.5, 24.41 d 10.0, 25 d 10.0, 26 d 10.0). The q12 demo sets `pad_deg: 2.0`, so no printed number moves.
- The test (`test_r12_m20_...`) pins the function at 24.4, 24.5 and 26 days and the docstring's figure.

## M-28 the plan prints the cell-updates of the share it kept, and says when no window runs

DECISIONS row:
> NNN | `budget.plan`'s `les.cell_steps_per_window` is computed from the stage-3 share the plan kept (`shares["stage3"]`), not the constant `SHARE["stage3"]`: when windows are skipped their slices go to stage 1 and the figure follows (a quick CPU plan with every window skipped has 0). `budget.describe` prints "no LES window runs on this machine (N part(s) not run)" instead of a per-window figure when no window runs; otherwise it prints the figure as before. A GPU plan keeps 0.30 and is unchanged. | Review round 12, M-28 (C-3). q12's plan.json had `shares.stage3 = 0.0` and all five windows `runs=False`, and still printed "6.78e+08 cell-updates per window" (0.30 x 1200 s x 7.53e6 / 4 vehicles), a budget the plan had given away. |

Amends: 189 (documents `shares` and `les.windows`: add "`les.cell_steps_per_window` is the kept share's, row NNN"). 136 says sizes derive from the plan: unchanged.

CHANGELOG: `Fix: plan and the report no longer print a cell-update budget per LES window for a stage 3 whose windows are all skipped (it was 6.78e+08 for the demo's quick CPU plan, the share that went to stage 1); plan.json les.cell_steps_per_window follows the share kept; DECISIONS NNN.`

Doc sentence: none (the field is not documented outside DECISIONS).

Printed numbers of the demo that move (CPU, `--budget quick --gpus 0`): `plan.json les.cell_steps_per_window` 678105249.78 (q12) -> 0.0, and the line of the plan text and `index.html` "stage 3: 1 window(s)/vehicle on native-jax-cpu at ...; 6.78e+08 cell-updates per window" -> "...; no LES window runs on this machine (5 part(s) not run)". Measured with `plan --mission missions/tepex_c_demo.yaml --budget quick --gpus 0` on orca (6 CPUs) on a8b8bb1 and on this tree: before "stage 3: 1 window(s)/vehicle on native-jax-cpu at 7.53e+06 cell-updates/s (measured (2026-10-28, cpu)); 6.78e+08 cell-updates per window", after "...; no LES window runs on this machine (5 part(s) not run)" (the next line, "5 of 5 window part(s) are not run ... 360 s of the budget went to stage 1", is the same in both). No verdict, gate or other plan field moves: `stage3_plan` reads the field only when a plan has no `shares`/`budget_s`.

What I checked could break, and how:
- Consumers of `cell_steps_per_window`: `stage3_plan` (budget.py:478, only when the plan has no shares, i.e. a hand-built plan), `wall_estimate` (no caller outside tests; its stage3 term now follows the kept share too), `describe`, and tests (test_stage3.py:824 builds its own plan; test_budget.py:205 `gpu > cpu` still holds, 320-327 recompute from the plan's own field). All of test_budget.py, test_stage3.py ran.
- A plan with the share partly kept (ci's one smoke window; overnight's free-surface case): the figure is the kept share's, divided, as before, by windows x vehicles; so it is still a gross figure and not net of the FEA reserve and compile guess (the finding's other remark). I did not change the divisor: `stage3_plan` already has the per-part figures (`cell_steps_per_part`) and `describe` takes the plan before it is added; describing it per part would need `describe` to receive that dict. Left as it was, and the sentence "per window" now appears only when a window runs.
- `acceptance.VOLATILE` and the golden: `cell_steps_per_window` is in neither (grep of tests/golden and acceptance.py), so the golden comparison does not move. `plan.json` is not part of the resume hash.
- q11 and q12 text stays as historical output.

## M-23 `CAFE_WORKERS=` (empty) means unset: documented, no code change

The lead keeps the design (DECISIONS 296 and 330: an empty value means unset, `par.env_count`, `tests/test_par.py:235`, `budget.py:376`). No code was changed.

DECISIONS row: none. Amend 330 or 296 with one clause: "an empty `CAFE_WORKERS` is unset, so `env CAFE_WORKERS= ...` in front of a command under `PM_RUNTIME=proot` removes the count `bin/proot_run.sh` set from `PM_CPUS` and the plan then uses every CPU the machine reports (32 on orca); choose the count with `PM_CPUS=<n>` or `env CAFE_WORKERS=<n>`" (review round 12, M-23, B-10).

CHANGELOG: `Docs: an empty CAFE_WORKERS is unset (so under proot it drops the count set from PM_CPUS); DECISIONS 296/330, RUNBOOK.`

Doc sentence, RUNBOOK:41 (the proot paragraph, after "Under proot `CAFE_WORKERS` is set from `PM_CPUS`") and the row at line 296: "An empty `CAFE_WORKERS=` counts as unset, so `env CAFE_WORKERS= python ...` removes that count and the plan sizes the pool from the CPUs the machine reports; write `CAFE_WORKERS=<n>` or leave the variable out."

What I checked: the `+3`, ` 3 `, `1_0` spellings are Python `int()` and harmless (the finding says so). `cafe/cfd.py:13` reads `CAFE_NPROC` with a bare `int(os.environ.get("CAFE_NPROC", "6"))`, which raises a bare ValueError on an empty value (not `par.env_count`); it is the old app's module (`IMPORTED`, not under mypy) and outside this finding: noted, not changed.

## M-21 round 11 tests whose mutants survive (tests only)

No production change. DECISIONS 619 and 632: "pinned" is now true of these three; no amendment needed unless the word "pinned" is dropped (then amend 619 and 632). CHANGELOG: `Tests: boundary points for the wall-function switch (y+ 11.03 and 11.1, and the constant derived from KAPPA and B_LOG), CALM_SWH_M (0.0009, 0.0011, 0.01 m) and FLAT_SHARE_MAX (one point at and one over 1 percent of the sample); round 12, M-21.`

- `tests/test_stage3.py::test_r12_m21_the_wall_function_switches_within_a_few_hundredths_of_y_plus_11_06`: derives the root of ln(y+)/kappa + B = y+ from `wm.KAPPA` and `wm.B_LOG` (11.0623) and asserts `YPLUS_LAM` within 0.005 of it, plus the viscous value at y+ 11.03 and the log-law value at 11.1 to rel 2e-4 (the laws differ there by 0.1 percent, so the old 2e-3 could not see it). Mutant 11.0: killed. The numeric points alone kill it too (checked with a probe that had no root assertion, in the throwaway worktree: YPLUS_LAM 11.0 fails the 11.03 point, 11.2 fails the 11.1 point, the unchanged 11.06 passes); the root assertion kills any value more than 0.005 off.
- `tests/test_pipeline.py::test_r12_m21_the_calm_wave_height_...`: with still air, swh 0.0009 m is a calm and swh 0.0011 and 0.01 m are not (the spectrum checks are judged, value not None); and `CALM_SWH_M == 1e-3` asserted once. Mutant 5e-2: killed.
- `tests/test_pipeline.py::test_r12_m21_the_flat_share_limit_...`: of the sampled points (`seen` from `_ustar_agreement`), `int(0.01 seen)` zeroed (swh and ust, first sampled hour) passes all four wave checks and one more fails all four; the test asserts `0 < at <= 0.01 seen < over < 0.03 seen`. `FLAT_SHARE_MAX == 0.01` asserted once. Mutant 0.03: killed.
- Siblings named by the finding and not done (the finding left them unsearched): `YPLUS_OK` window 30/300, `NU_MAX` 0.5 (row 640 measured it and left it), `USTAR_FLOOR_MS`. Not mutated, no test added.

## M-33 `--update-golden` help text (batch A changes the behaviour)

`cafe/pm/__main__.py` `--update-golden` help now ends "A golden file of another mission (or a file that is no golden) is not overwritten (round 12, M-33)". That describes the refusal the finding asks of `check_golden`'s update branch.
If batch A implements it differently (for example an explicit override flag), reword the help: it is the single help string at `__main__.py` near the `acceptance` parser, and the override flag would need its own `add_argument` there, which is batch B's file.
At the time of writing batch A's tree had not yet changed `check_golden`'s update branch.

## What I checked across the batch

- ruff clean and mypy strict clean on the final tree (orca). Whole files run: tests/test_config.py, test_cli.py, test_budget.py, test_par.py, test_pipeline.py, test_stage3.py (counts below).
- Fast-path risk check of the tests that read the schema or the CLI text: `tests/test_config_docs.py` reads RUNBOOK and DECISIONS (not edited here), and `tests/test_runners.py` documented demo commands: not affected by the code; not run.
- Edits to test files only add tests, except two expected-text updates in test_config.py (ROUND4 ship = vehicle, and the three box patterns).

## Needs from other batches

- Batch A (report.py): M-2's optional defence in depth, the Verdicts table keys (report.py:1677) and the `_sanity` merge (report.py:1051) and credibility.py :654 and :753 merging `{**vehicles, **links}`: with the load-time check these cannot collide for a loaded mission, so prefixing the keys with `vehicle:` and `link:` is only a guard for a hand-built dict. Do it only if it is cheap in the lines A already edits. Note that report.py:1707 and :1708 give vehicle and link blocks the same `id='v-<id>'` prefix (no `l-`), so the anchors rely on the same uniqueness; a `l-` prefix for links there would be the same kind of guard (it moves the links' anchors in the HTML and anything that links to them).
- Batch A (M-33): the override mechanism of `--update-golden` if there is one (a flag name), so the help string in `__main__.py` can name it.
- Batch F: all DECISIONS/CHANGELOG/RUNBOOK text above; the DECISIONS number for each `NNN`. RUNBOOK rows to add or change: line 41 and 296 (M-23), 158 (M-20), 294 (M-24, optional), 297 (M-22), the mission ids section and two troubleshooting rows (M-2).
- Nothing needed from C, D or E.

## Second pass (adversary's M-7 escape and the sibling holes the first pass left)

Items of the second-pass list that are not problems: the Verdicts-table key prefix (M-2 optional) and the `v-<id>` anchors at report.py:1707-1708 are batch A's file and stay handed to A; M-33's help text is reworded by whoever
implements the override (stated above); M-22's other entry points have no reader of `CAFE_OFFLINE` (grep: only the three lazy `_offline()` calls in pipeline.py), so none can go online on a bad value; the gross M-28 figure is a stated decision (see M-28 above); `hycom.box360`'s raw tuple is reachable only from a direct fetch call with a hand-built box.

### M-7 again: `IndexError` escaped `damaged_run_files`

`damaged_run_files` now catches `LookupError` (KeyError and IndexError), `ValueError`, `TypeError` and `AttributeError`, and lets a `ConfigError` (a ValueError) through unwrapped, instead of naming KeyError. Root cause: the tuple named the exception types seen so far, and a list where a mapping is read (`plan.json member_cost = [1]`, `mc[v]` at budget.py:537) is an IndexError, a sibling of KeyError. Callers (`__main__._report`, `_whatif`, `stage1.main`) catch nothing of their own; the only change is that an IndexError from a damaged run file is now `error: ...: damaged or incomplete (IndexError: list index out of range); run it again (--fresh); if that gives the same error, it is a bug: report it`, exit 2.
Tests (tests/test_cli.py): `test_r12_m7_a_plan_member_cost_that_is_no_mapping_is_damage_with_exit_2_not_an_index_error_traceback` ([1] fails on the unfixed code with the IndexError traceback; [] and 5 are TypeError and passed already) and `test_r12_m7_damaged_run_files_names_an_index_error_and_keeps_its_text` (fails unfixed). Both failed on a detached worktree of b6ac85a on orca and pass now.
Sweep: a probe (not committed; a throwaway test on orca) replaced every dict entry of every JSON file of a finished run (`make_run`), two levels deep, by `"x"`, None, `[]`, `{}` and -1, and ran `report --run` on each: 3,055 mutations on the tree with the LookupError fix only. Three escaped, all ValueError: `plan.json stage1_s = "x"` (`format("x", ".1f")`), `plan.json les.rate = "x"` (`:g`), `stage1b/summary.json priors = "x"` (`dict("x")`). Same defect, same place, so `ValueError` is in the tuple too. ValueError is a base of `ConfigError`, which `json_object` and `load_mission` raise with the user's message; `except ConfigError: raise` comes first so none of them is wrapped as "damaged" (test `test_r12_m7_damaged_run_files_lets_a_config_error_through_unwrapped`, which fails if the guard is dropped). Tests `test_r12_m7_a_string_where_a_number_or_a_mapping_is_read_is_damage_with_exit_2_not_a_value_error_traceback` (three cases) fail on the tree with the LookupError fix only (checked in the throwaway worktree). Trade, as row 617 took for TypeError: a ValueError from a real bug inside a guarded block (stage1.main's guard also wraps `sensitivity_case`) now prints as damage with its text and "if that gives the same error, it is a bug".
After the ValueError fix a second, shallower probe (one level, values `"x"`, None and `{}`: 1,446 mutations) gave 0 escapes; the same probe on the tree before the ValueError fix gave the same three escapes as above (3 of 1,446). Not rerun after the fix: the two-level, five-value probe (3,055; about two hours on orca). Orca note: an attempt to stop my own first probe by its pid was refused by the permission system, so it ran to its end; no process of anyone else was touched.
DECISIONS 617 amend: the types held are "LookupError (KeyError, IndexError), ValueError, TypeError, AttributeError; a ConfigError passes through". Text for the first-pass M-7 DECISIONS row above: read AttributeError as that list.

### P-R12B1 the trailing-newline hole, fixed for the four patterns

The schema's four `$`-ended patterns (`$defs/id`, `$defs/time`, the mission `name` and `local_solar_time`) accepted a value with a final newline, because `$` matches before it in Python's `re`. Each now ends in `(?![\s\S])` (end of input in Python and in ECMA-262). The `name` one matters most: it is a directory name. Test `tests/test_config.py::test_r12_m2_a_pattern_of_the_mission_schema_does_not_let_a_final_newline_through` (four cases) fails on the unfixed schema for all four and passes now. A lab mission whose id, name, time or HH:MM was written as a YAML block scalar (`|`) is now refused at load; every shipped mission is unaffected (the whole test files that load them pass). The unicode-digit hole of `\d` in the time patterns (Python's `\d` matches Arabic-Indic digits) is a sibling not fixed and not checked for what happens later.

### M-21 siblings, searched

Mutants run alone in the throwaway worktree against the whole test file: `USTAR_FLOOR_MS` 1e-3 to 1e-2: killed (`test_coare_ustar_is_compared_with_umwm_ust_and_the_agreement_is_logged`). `NU_MAX` 0.5 to 0.6: survives, by design: it is not read by any code (DECISIONS 640 says it is not enforced), so there is nothing to test. `YPLUS_OK` low end 30 to 25: survived the whole of test_stage3.py. New test `test_r12_m21_the_log_layer_window_ends_at_30_and_300_and_the_default_fraction_uses_them` (the literal, and the default fraction of 29.9, 30, 300, 300.1); mutants (25, 300) and (30, 400) are killed by it. Not tested: `YPLUS_OK` upper end through `bracket` in the channel gate (the same constant, one place).

### Gates of the second pass

ruff (`cafe/pm tests`) clean, mypy strict clean (55 files), whole files on the final tree (progress-line characters, all rc=0): tests/test_cli.py + test_config.py + test_config_docs.py + test_budget.py + test_par.py + test_report.py in one job, 793 passed (this includes test_config_docs.py, which the first pass had not run); tests/test_stage3.py + tests/test_pipeline.py in one job, 508 passed, run before the last edit of `damaged_run_files` (the ValueError one: no other code and no test_stage3.py / test_pipeline.py line changed after that job started). The schema change (the four patterns) was in the tree for all of these. Not run: the slow receipts, the whole suite.
