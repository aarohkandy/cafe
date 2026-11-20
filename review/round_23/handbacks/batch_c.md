# Round 23, batch C hand-back (M-6, M-7)

Branch r23-c on f62defd. Files: cafe/pm/config.py, cafe/vehicle.py, tests/test_round23_c.py (new). No other file touched.

## What changed and why
- `config._yaml`: `except yaml.YAMLError` is now `except (yaml.YAMLError, ValueError)` (after the ConfigError branch): PyYAML's own `int()` of 4,301 or more decimal digits (the interpreter's limit; its message names the digit count, not the literal) and any other constructor ValueError (a calendar-invalid timestamp such as `2023-02-30`, `!!int 'zz'`) were bare ValueErrors; they are now `<file>: not valid YAML (...)`, the existing shape. `ledger.values_sha256` already catches ConfigError, so it gives "" (tested).
- `config._Loader.construct_mapping`: `seen.add(key)` moved inside the `isinstance(key, Hashable)` branch. A list, mapping or set key is left to PyYAML's own refusal ("found unhashable key" with the line), through the same `yaml.YAMLError` path. Deviation from merged.md's wording (which names a TypeError in the except tuple): this keeps the except tuple narrow so that a TypeError from a real bug is not relabelled as "not valid YAML", and the message keeps its line. Same outcome: ConfigError.
- `config._finite`: the digit count is `len(decimal.Decimal(node).as_tuple().digits)` instead of `len(str(node))`. `str` of an integer over 4,300 digits raises the interpreter's ValueError; a hex literal of 4,000 hex digits (4,817 decimal) reaches `_finite` and hit it. The message keeps its wording ("an integer of N digits") and is now exact for a negative number (the old count included the minus sign: -10**400 said 402). No new sentence, no new constant.
- `vehicle._vec3`: `KeyError` added to the except tuple (one token). `hull_lift`'s coarse-read `except (KeyError, ValueError)` is unchanged and still gives inf (tested).

## Evidence (orca, proot, 2 CPUs, pm_r23c*, pm_r23cb)
- tests/test_round23_c.py has 110 cases. Before (detached worktree f62defd with the same test file, job r23cb_3, pm_r23cb): rc=1, 39 passed, 71 failed (every M-6 and M-7 case that should fail; the passing ones are the "as before" cases). After (r23c job in pm_r23c): all 110 pass (72 + 38 progress characters, no F).
- Related files after the change, job r23c_2: test_round23_c, test_config, test_round22_c, test_round22_d, test_round22_m, test_round21_e, test_platform_required, test_ledger: rc=0, 1215 passed, 0 F.
- `ruff check cafe/pm tests/test_round23_c.py` clean; `mypy cafe/pm` clean (57 files). (ruff on cafe/vehicle.py reports 12 old findings, outside the gate's scope, untouched.)
- Final re-run after the last comment edit: job r23c_4 (test_round23_c, test_round22_c, test_config) rc=0, 459 passed, 0 F.

## Claims left on an output and the test that holds each
- "an integer of N digits is not a finite number": exact N for 399, 400, 401, 1,000, 4,299, 4,300 digits, both signs (`test_m6_the_message_counts_the_digits_exactly...`), and for hex integers of 250 to 9,000 hex digits against `str` with the limit switched off (`test_m6_a_hex_integer_is_counted...`).
- The literal is never printed, for decimal 399 to 5,000, negative, underscored, plus-signed, hex up to 200,000 digits (`test_m6_an_integer_too_big...`: message shorter than 600 characters and does not contain the literal).
- "not valid YAML (...)" for an unhashable key at top level and nested, three key shapes, and an invalid timestamp or tag conversion.
- `hangar --platform` of a file with such a value: exit 2, empty stdout, stderr starts `error: <file>: ` (5 literals).
- `_vec3`: the named ValueError for a missing key in every container type, each key in turn, and for `build` over all six directions times three keys and `hull_lift` over seven labels times two keys.

## Siblings
- `len(str(` of an int anywhere in cafe: none other. A second YAML reader: none (`yaml.safe_load` appears only in a docstring of fea.py; the round 22 enumeration test holds this).
- `vehicle.build` reads `c["dirs"][d]` for every direction in `DIRS` and `hull_lift` reads `c["dirs"][lab]`: a whole direction missing is still a bare KeyError (not named by M-7; not changed). Left over for the lead.
- Equal keys of different YAML types (`1: x` and `true: z`) are reported as a duplicate because 1 == True in Python: unchanged, noted.

## Hostile attempts
Digit counts at the interpreter's limit and one past; both signs; `+`; underscores; hex at 256 digits (fits a float, read as before), 300, 3,999, 4,000, 200,000; NaN and inf for `_vec3` items, 10**400, bool, text, empty dict, length 2 and 4; `r` as None, list, str, int; unhashable keys at top and nested; set key; a repeated key still refused; hashable keys of other types read as before.

## Pins moved
None. Old pins "an integer of 401 digits" (test_round21_e, test_round22_c via `\d+ digits`) hold unchanged.

## Document sentences
RUNBOOK line 100 ("in ANY YAML file ... exits 2 with `error:`") is now true for these inputs; no change needed. Suggested DECISIONS row: "config._yaml turns a ValueError of the loader into a ConfigError; `_finite` counts digits by Decimal (no str); `_vec3` names a missing key" (batch G).

## Demo q25 versus q24
Nothing moves: no value, verdict, count or interval is read through a changed path for a valid file.

## Not verified
Full suite, gate, mutation testing, coverage numbers (every added statement is run by a test in test_round23_c.py, by reading), a real stored cache with no `viscous` key.
