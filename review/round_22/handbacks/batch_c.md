# Round 22, batch C hand-back: the YAML boundary (M-5)

Branch r22-c (cut at 7a1aaa9), worktree /Users/aaroh/Downloads/everything/cafe-r22c. Builder: Claude Sonnet 5.5.

## What changed and why

`cafe/pm/config.py`, two hunks, net zero lines of logic:
- `_yaml` (the one YAML reader, `read_yaml = _yaml`) now calls `_finite(doc, path)` after the document is built and `_expanded_size` has bounded it. It sits after the `try`, not inside, so the message carries the path once ("{file}: {key/path}: nan is not a finite number; ..."). OD-4 default taken: one place.
- `load_mission` no longer calls `_finite` itself (the reader did it already; a second walk of the same document). The mission's message is byte-identical; the only difference is the order: a mission with a NaN is now refused by the reader before `_unread_keys` runs, not after.
- No new function, constant, printed number or sentence. `_finite` and its message are unchanged.

`tests/test_round22_c.py` (new, 89 tests). `tests/test_config.py`, `tests/test_platform_required.py`, `tests/test_stats_exact.py`: 21 pins moved (below). The last two files are in no other batch's list.

## Every YAML the code loads, verified by grep and by an AST scan (cafe/, lab/, bench/, bin/; `*.py`, `Makefile`, `*.sh`)

`import yaml` appears only in `cafe/pm/config.py` (the loader `_load`) and `cafe/pm/pipeline.py` (`yaml.dump` of the mission copy a run keeps; no load). lab/, bench/, bin/ import none. Every `read_yaml`/`platform_doc`/`_yaml` caller goes through `config._yaml`: comms (radios, modems, lru_cached), glider/usv/uas loaders (`platform_doc`), `config.assumptions`/`env_sigmas`/`load_platform`/`load_mission`, `stats.sampling.load_perturbations`, `credibility`, `ledger.values_sha256`, `dtmb5415.assumed`, `env.subgrid`, `env.conventions` (the overlay), `pipeline`. merged.md's table is right, with one row it omits:

| reader | covered? |
|---|---|
| everything above | yes, by construction |
| `cafe/fea.py::hull_elements_along` (reads one key of assumptions.yaml BY LINE, no pyyaml, because the live app image has none) | not through `_yaml`, and safe: it returns only a plain decimal whole number from 1 to 500 or raises ValueError; `.inf`, `.nan`, `1e400`, a 400-digit integer, a float are all refused by its grammar. Held by `test_the_one_hand_reader_of_assumptions_yaml_refuses_what_config_yaml_refuses` (9 values). |

The enumeration tests: `test_no_module_but_config_loads_yaml_and_the_modules_that_import_it_are_the_listed_ones` (AST over cafe/, lab/, bench/, bin/: any `import yaml`/`ruamel`/`from yaml import`/`__import__("yaml")` outside the two listed modules, or any attribute of `yaml` other than `dump` outside config.py, fails) and `test_a_yaml_text_is_read_by_no_code_of_ours_but_the_listed_reader` (AST: a `read_text`/`read_bytes`/`open` on an expression naming a YAML file or `ASSUMPTIONS`/`PERTURBATIONS` is a reader; the only one is fea.py and it is listed with its reason).

## Legitimately non-finite value?

None. grep and a regex test (`(?<![\w.])[-+]?\.(inf|nan)\b`, any case) over platforms/, config/ and missions/ YAML: no `.inf`/`.nan` anywhere; `perturbations.yaml` and the schemas hold no infinite bound (their `lo`/`hi` are finite and `sampling` refuses infinite ones). Every shipped file loads (test). No exemption was needed and none was written.

## Evidence

Reproduction of D's case (script `/private/tmp/claude-501/-Users-aaroh-Downloads-everything-cafe-main/e5175414-543a-42ed-83ef-98e3ca2ddc48/scratchpad/r22c/repro_r22c.py`, run on orca under proot, jobs `r22c_rep_base` and `r22c_rep_after`): radios.yaml copy with the first `tx_dbm: 30.0` replaced by `.inf`.
- BEFORE (7a1aaa9): `rf_margin(1000, 2, 2, 0)` = `inf` (a link that always passes); `hangar --platform <copy>` printed "provenance OK, 20 of 25 items assumed", rc 0.
- AFTER: `rf_margin` raises ConfigError "…/radios.yaml: radios/rfd900x/tx_dbm: inf is not a finite number; write a number (a missing value is a missing key, not .nan)"; `hangar` prints that on stderr, rc 2, no "provenance OK".

Exit code: the lead's note says hangar "exits 1"; the real code is 2. `_hangar` calls `load_platform` outside its try, so a ConfigError is the CLI's exit 2 (the same as an unknown platform). It was 1 for a vehicle file with a NaN before ("provenance FAILED", from the class loader's ValueError); the reader now refuses first, so that case is exit 2 with `error: ...` on stderr and no stdout line. No test pinned the old stdout for a non-finite vehicle file (test_cli passed unchanged).

Regression test, unfixed tree (detached worktree at 7a1aaa9 with only the new test file copied in, job `r22c_base1`): 14 passed, 44 failed of 58 (the 44 = 10 shipped files x 4 bad values + the 4 radios cases; the 14 that pass are the ones that hold on both trees: the unedited copy, the grep, the enumeration, the hand reader). Fixed tree (job `r22c_9`, test_config, test_platform_required, test_stats_exact, test_round22_c): 722 passed, rc 0. The new file alone, final: 89 passed (`r22c_5`, before two style edits; `r22c_9` includes the final version).

What the generated test covers: for each of the 10 shipped YAML files (6 platforms, 2 config, 2 missions) and each of `nan`, `inf`, `-inf`, 10**400, EVERY numeric leaf is replaced in turn and the file must be refused by `config._yaml` with a ConfigError whose message starts "{file}: {key path as _finite names it}: {nan|inf|-inf|an integer of 401 digits} is not a finite number". The unedited dump is first shown to round-trip equal to the shipped document, so only the edited leaf can be the cause. Plus 20 hand-typed spellings in a nested list (`.Inf`, `+.inf`, `-.INF`, `.NAN`, `1e400`, `-1e400`, `1.0e+999`, `!!float inf`, 10**309, hex of 300 digits, an underscore-grouped 400-digit integer) and the pass side at the bound: 10**308, -10**308, 1e308, -0.0, 5e-324, 0, true, quoted "nan", quoted ".inf", null all load unchanged. Bound moved by one (10**309) is refused.

Timing (orca, proot, 2 CPUs, 20 loads each, job `r22c_rep_base` vs `r22c_rep_after`): `_yaml` per call, assumptions.yaml 43.44 -> 43.89 ms, radios 8.74 -> 8.82, modems 4.21 -> 4.25, quad_uas 20.34 -> 20.52, saildrone 27.96 -> 28.21, seaglider 12.11 -> 12.22, slocum 10.67 -> 10.75, perturbations 6.68 -> 6.70. About 1 % of a read. `comms._yaml` is `lru_cache`d, so radios and modems are walked once per process; the stage-1 path is not slower.

ruff check cafe/pm tests: rc 0 (`r22c_10`, after the last edit). mypy cafe/pm: "no issues found in 57 source files", rc 0 (`r22c_11`). Statement coverage: the one new statement (`_finite` call in `_yaml`) runs in every load; no new branch.

## Existing tests run (all on orca, pass unless listed under pins moved)

First run (`r22c_2`): test_config, test_cli, test_comms, test_comms_exact, test_platform_required, test_usv, test_glider, test_round21_e, test_round16_a, test_ledger, test_stats_exact, test_config_docs, test_subgrid, test_round17_d: 1,595 passed, 21 failed (all 21 pins, below). Then `r22c_12` (test_uas, test_credibility, test_stage1, test_round21_b, test_budget, test_round17_b, test_round17_m, test_round18_b, test_round19_m, test_round20_a) and `r22c_13` (test_pipeline, test_whatif, test_report, test_ci_env, test_acceptance): 10 files: 1,038 passed, rc 0 (`r22c_12`). `r22c_13` (the five pipeline-side files whole) I killed by its exact tmux name after 8 minutes at 6 %: those files are hours long. In its place `r22c_14`: the same five files, only the tests whose name mentions yaml, platform, finite, nan, radio, modem, assumption, hangar, provenance, mission, config or sigma: 200 passed, rc 0. NOT run whole: test_pipeline, test_report, test_whatif, test_acceptance, test_ci_env (the gate runs them). Nothing else of mine was running; two jobs at a time held except for the few minutes `r22c_13` was still alive while `r22c_14` started (three), and `r22c_14` was synced with `PM_TAKE=1` into `pm_r22cb` while `r22c_13` still ran there (same code tree, byte-identical files; I should have used a third name).

## Pins moved (21), each because the product's answer is now the intended one

The reader refuses a non-finite number before a loader's own check sees it, so a FILE with a NaN, infinity or oversized integer is refused with the reader's message, not the loader's. The loaders' own checks (`check_params`, `sampling.check_entry`) stay and stay tested directly (the tests below already call them on in-memory values, and `test_check_params_kinds_and_non_numbers`, the r14 test of the one check and `check_entry` in `test_one_check_...` are untouched).
- tests/test_platform_required.py: `test_a_platform_with_a_missing_nan_or_unphysical_parameter_is_refused_naming_file_and_field` (8 cases: seaglider-1,5,6,7,9; saildrone_explorer-14; quad_uas-18,20) and `test_r14_a_bad_radio_link_..._huge_integer_...` (5: seaglider-8,9,10; quad_uas-11; saildrone_explorer-12). New helper `reader_refuses(path)`: when `config._yaml(path)` refuses, assert the message is "{path}: {key}: (nan|inf|-inf|an integer of N digits) is not a finite number; " and stop; every other case runs the loader assertion verbatim (not weakened: the cases that are not non-finite are unchanged, and the helper is a stricter statement for the ones that are, because it names the file).
- tests/test_stats_exact.py: `test_one_check_refuses_every_entry_that_would_give_nan_members_or_a_traceback` (5 entries: lo nan, hi inf, sd 10**400, mean nan, median inf) and `test_r13_l1_a_fixed_correlation_length_that_is_nan_..._refused_where_every_reader_sees_it` (2: nan, inf). Only the FILE route (`load_perturbations(p)`) takes the reader's message ("e/lo: nan is not a finite number"); the direct `check_entry` and `to_marginals` assertions of the same input keep the exact words.
- tests/test_config.py: `test_r13_l1_env_sigmas_reads_the_priors_through_the_checked_loader[wind_speed_bias-nan]`: the reader's message for the NaN; the three finite cases keep "perturbation '<key>'".

## Siblings found and what I did

- Raw YAML reader other than `_yaml`: only `fea.hull_elements_along`; safe, listed, tested (above).
- `load_json` (JSON tables): NaN readable on purpose (round 21); not changed.
- A NaN or infinity as a mapping KEY (`.inf: 1`): not a number a value consumer reads; `_finite` walks values only; not refused. Left as is.
- A numeric value written as text that YAML 1.1 reads as a string (`1.0e999`: a float with a dot needs a signed exponent): it is a string, so downstream is a TypeError at the first sum, never a finite-looking wrong number. Held by a test that says so; not changed (the loop's next sibling if one closed it).
- `CAFE_PM_OVERLAY`: `conventions._overlay_wave_convention` reads the overlay through `read_yaml` and takes one name. An overlay with a NaN ANYWHERE is now a ConfigError that names it (it used to be ignored unless the NaN sat in `waves.direction_convention`). The one behaviour change outside the three files; I judge it right (a damaged file is named) and say so.
- `ledger.values_sha256` of a values file with a NaN raises ConfigError named, where it hashed (merged.md predicted this).
- `perturbations.yaml`'s own `_num` checks remain as the second line (still reachable from `to_marginals` with a fitted prior).

## Hostile reviewer: what I tried

`.nan`, `.inf`, `-.inf`, `+.inf`, any case, `!!float`, `1e400`, `1.0e+999`, 10**309, hex and underscore-grouped huge integers, in a list of lists in a mapping; the bound 10**308 (loads) against 10**309 (refused); -0.0 and 5e-324 (load); bool, quoted `nan`, null (not numbers, load); a leaf inside a list item that has an `id`; the empty file (platform_doc's own message, test_platform_required passes); the mission after the move of its `_finite` call (test_config and test_round21_e pass); the generated test run with the call removed (44 of 58 fail on the base tree: it detects removal); the `radios` file edited through its inline `{value: ..., unit: ...}` form and through the plain `tx_dbm: .inf` form.

## Document sentences that must change (for batch G)

- DECISIONS.md row 1049 and the comment at tests/test_round21_e.py:37 say "a YAML number through `config._finite`": still true; add "inside `config._yaml`, for every YAML file read, since round 22".
- config.py's comment on `read_yaml` ("every config, platform and mission file goes through it") is now literally true and now also says every number in them is finite.
- New DECISIONS row (no owner decision; OD-4 default): `_finite` runs inside `config._yaml`; the loaders' own checks are the second line; `hangar` of a non-finite file exits 2 (ConfigError), not 1.
- docs/RUNBOOK.md: if it says a non-finite number in a platform file is "provenance FAILED", it is now an `error:` line and exit 2 (grep before writing it; I did not edit docs).

## Hunks for other batches

None. No raw reader outside config.py needs a change.

## Expected demo q23 against q22

No verdict, count or interval moves: every shipped YAML loads unchanged (test), and the only new work is one tree walk per read. No new printed text.

## Problems, not verified, leftovers

- Not verified: the full suite, the gate, mutation of the new line (the 44 base-tree failures are the nearest evidence), a demo.
- I synced to `pm_r22c` once with `PM_TAKE=1` while the job `r22c_2` was still running there (an `-k` argument I wrote was split on spaces and failed with rc 4). The sync added only `tests/test_round22_c.py`, which that job did not run; nothing it ran changed. Every later job used another directory while one ran.
- The reviewer's "twelve YAML edits" were not rerun as such; the generated test replaces them (about 1,500 leaves x 4 values).
- Orca leftovers: directories `~/cafe-worker/cafe/pm_r22c`, `pm_r22cb`, `pm_r22c_base`, `pm_r22c_rep`; `pmdata/repro_r22c.py` (the script removed its own temp directory). Logs `r22c_*` in `~/cafe-worker/logs`. Laptop: worktree `../cafe-r22c-base` (detached, at 7a1aaa9, with the new test file copied into it), scratchpad `r22c/`.
