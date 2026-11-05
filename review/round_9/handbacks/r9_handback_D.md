# Round 9, batch D (stage 3): M-4, M-23, M-24

Branch `r9-d` (worktree `/Users/aaroh/Downloads/everything/cafe-r9d`), cut from 91c9777. No docs edited. Row numbers below are placeholders ("next free"): the lead numbers them.

Files: `cafe/pm/stage3/lbm.py`, `nest.py`, `wallmodel.py`, `windows.py`, `pipeline_windows.py`; `tests/test_stage3.py` (27 new test cases in 9 functions) and one line of `tests/test_config_docs.py` (a source-text pin, see "could break").

**`lbm.physics_sha()` changes** (lbm.py, nest.py and wallmodel.py are in `PHYSICS_FILES`). Every stored slow result (`wm_flat_plate`, `wm_channel`, `nest_sphere_*`, `lbm_sphere_*`) is stale again, as after rounds 7 and 8; they were not rerun after round 8 either, so nothing new is lost, but the RUNBOOK sentence on this (line 218) should name round 9.

## M-4 (and the siblings it names)

What changed
- `lbm.read_stored(f, numeric=())`: the one reader of a stored slow result. None when the file is missing, undecodable, not a JSON object, or lacks a finite real number (not bool, str, None, NaN, inf) in any of `numeric`.
- `wallmodel._read_receipt(f, fields)` now goes through it. `PLATE_FIELDS = (err, cf, re, ittc, yfrac)`, `CHANNEL_FIELDS = (err, cf, cf_dean)`. A receipt missing any is "unreadable (rerun it)", so `stale_wall_receipts()` says so, `stored_wall_error()` is None, the gate row fails with that text, and `receipts()` shows the plate as NOT STORED.
- One shared function `_stored_receipts()` returns (problems, receipts read); `stale_wall_receipts()` and `stored_wall_error()` both use it, so the files are read once and the gate cannot see two different files.
- `lbm.result_row`: a record without a finite number for `value_key` or `ref_key` is one FAIL row "STORED WITHOUT A NUMBER FOR cd AND ref" with the rerun command (it used to `KeyError` / `TypeError` on `rec[ref_key]` before the sha test).
- Siblings swept: `lbm.receipts` sphere rows read through `read_stored` (a truncated `lbm_sphere_*.json` used to be a `JSONDecodeError`, and `rec['shape']` a KeyError); `nest.stored_grids(tag)` is the one reader of `nest_sphere_<tag>_d*.json` for `nest.sphere_discretisation` (the refit's default floor, which crashed on a truncated grid) and `nest.sphere_receipts` (a grid without numeric `d` and `cd` is left out and named in a context row "nest_sphere_..._dN.json is unreadable ... left out, rerun it").

DECISIONS row (next free)
> A stored slow result is read through `lbm.read_stored`: a file that is missing, undecodable, not a JSON object, or without a finite real number (not a bool, text, null, NaN or infinity) in each field the code reads is a result that is not stored, never a `KeyError` or `TypeError`. For the wall-model receipts the fields are the plate's `err`, `cf`, `re`, `ittc`, `yfrac` and the channel's `err`, `cf`, `cf_dean` (`wallmodel.PLATE_FIELDS`, `CHANNEL_FIELDS`): a receipt lacking one is "wm_*.json is unreadable (rerun it)" in the stage-3 gate and NOT STORED in the receipts table, and `stale_wall_receipts()` and `stored_wall_error()` read the files once through `_stored_receipts()`. `lbm.result_row` fails a record without a number for its value or reference ("STORED WITHOUT A NUMBER FOR ..."); the sphere grid readers (`nest.stored_grids`, used by `sphere_discretisation` and `sphere_receipts`, and the XLB sphere rows) use the same reader, and a damaged grid is named, not read. Tests: `tests/test_stage3.py::test_r9_m4_*` (nine plate, five channel variants, a run_window-level one, seven `result_row` records, the sphere grid readers). Amends 424.

Amends: 424 (which covered only a truncated or non-object file); touches 348 only through 424.

CHANGELOG: "Stage 3: a stored wall-model receipt, sphere result or sphere grid without a number where the code reads one is a failed row or a failed gate check naming the file, not a KeyError/TypeError (R9 M-4)."

Doc sentences
- RUNBOOK 218 (stored slow results): add "a stored result with a missing or non-numeric field counts as not stored".
- PHYSICS.md 955: after "stored by other code than the current `lbm.physics_sha()`" add "or lacks a number in a field the code reads (`wm_*.json is unreadable`)".
- STALE sentence about round 8 -> also round 9 (physics_sha).

## M-23

What changed: `_stored_receipts()` (the gate's helper) has one more case, checked after the sha tests: the plate with `re < PLATE_RE_MIN` is "wm_flat_plate.json is at Re_L 9.8e+05, below the 1e+06 the comparison needs (rerun it)". `stored_wall_error()` is then None and the window fails with that text, as the receipts table already did. A missing or non-numeric `re` is "unreadable" (M-4 fields). `receipts()` is unchanged (it already had the Re_L branch, now on a validated record).

DECISIONS row (next free)
> The stage-3 wall-model gate (`wall_model_receipt_error`) refuses a stored flat plate run below Re_L = `PLATE_RE_MIN` (1e6) as the receipts table does: `stale_wall_receipts()` says "wm_flat_plate.json is at Re_L 9.8e+05, below the 1e+06 the comparison needs (rerun it)", `stored_wall_error()` is None, and the window fails with that text whatever the plate's error. The order of the phrases is: not stored, unreadable, no `code_sha`, other code, Re_L below the limit; the table's plate row still prints the Re_L row first for a stored plate (both FAIL; they differ only in which reason is named for a plate that is both stale and below 1e6). Test: `tests/test_stage3.py::test_r9_m23_a_plate_stored_below_re_1e6_fails_the_gate_the_same_as_the_receipts_table`. Extends 384; consistent with 104.

Amends: extends 384 (which was only about the table) and 104 ("at Re_L >= 1e6" now enforced by the gate too).

CHANGELOG: "Stage-3 wall-model gate fails a stored flat plate run below Re_L 1e6, as the receipts table does (R9 M-23)."

Doc sentences: PHYSICS.md 955: add "or a plate stored at Re_L below 1e6".

## M-24

What changed, and one deviation from the finding's fix
- The finding says `nest.simulate` returns a `diverged` boolean. I did **not** change its return type: it has 8 callers and 7 tests in `tests/test_nest.py` that unpack two values, and `nest.diverged(series)` is already the rule `simulate` stops on and is exact on the full series (only the last chunk can be diverged, because `simulate` stops at the first one). So `windows.run_window` sets the flag from `nest.diverged(ser)`: the same predicate, no `n < steps` inference. If the lead prefers the 3-tuple, it is a mechanical change.
- `windows.run_window`: `wlog["diverged"]`, `run_steps`, `diverged_at_step` and `cut_reason` come from `nest.diverged(ser)`; `run_steps` is not shortened (it equals `planned_steps` when the last chunk blew up).
- `pipeline_windows`: `cut = run_steps < planned_steps or wl["diverged"]`, so the row is `cut: true`, `ok: false`, no coefficients, `resolution.run_steps` None, no FEA (`_fea` is not called), and the numbers (NaN) go to `timing["machine_dependent"]`, out of the hashed `windows.json`.
- `nest.simulate(..., strict=False)`: with `strict=True` a diverged chunk raises `RuntimeError("the run diverged in the chunk ending at step N of M: ...")`.
- Per caller, what the flag means:
  - `windows.run_window` (LES window): cut, as above (the row says "diverged", the rest of its slice is the next window's).
  - `wallmodel.flat_plate`, `wallmodel.channel`: a calibration is a measurement; a diverged run is none. `strict=True`: they raise, so `wallmodel slow` / `channel` write no receipt (a NaN or Mach > 1 `err` used to be written as the receipt), and `receipts()` / `cafe.pm.receipts._plate` end as a failed receipt (the receipt runner turns an exception into a failed receipt, `except Exception` in `cafe/pm/receipts.py`).
  - `nest.sphere_drag` (the stored `nest_sphere_*` Cd): same, `strict=True`; `nest.main slow` writes nothing.
  - `nest.uniform_flow_force`, `nest.shear_layer_mass`: **unchanged, non-strict.** Their result is a bound on the whole series, which includes the diverged chunk; a NaN fails `lo <= v <= hi`, and one exception would take the other rows of the nest group with it. Not tested with a real blow-up (their size is fixed in the function); see "still looks wrong".

DECISIONS row (next free)
> A window whose last chunk diverges is flagged diverged: `windows.run_window` sets `wall.diverged` from `nest.diverged(series)` (the rule `nest.simulate` stops on), not from `len(series) < steps`, because `steps` is a whole number of chunks and a blow-up in the final chunk leaves a full-length series. Such a window is `cut: true` (`pipeline_windows`: `run_steps < planned_steps or diverged`) with no coefficients, no FEA and its numbers in `timing["machine_dependent"]`, as a window that diverged earlier. `nest.simulate(strict=True)` raises `RuntimeError` on a diverged chunk, and the callers whose number is a measurement use it: `wallmodel.flat_plate`, `wallmodel.channel` (so `wallmodel slow` / `channel` store no receipt from a blown-up run) and `nest.sphere_drag`. The bound-checked nest receipts (`uniform_flow_force`, `shear_layer_mass`) keep returning the series and fail their own bound. Tests: `tests/test_stage3.py::test_r9_m24_*` (three). Amends 186 and 197 (neither excluded the final chunk).

Amends: 186 ("`run_steps` < `planned_steps`" is no longer the whole definition of a cut by divergence), 197 ("ends at the first chunk ... where"; adds the final chunk and the strict callers).

CHANGELOG: "Stage 3: a window that blows up in its last chunk is cut (diverged), runs no FEA and withholds its coefficients; the wall-model and sphere calibrations raise on a diverged run instead of storing it (R9 M-24)."

Doc sentences: PHYSICS.md / RUNBOOK wherever 186/197 are summarised: "(also in the last chunk)"; wall-model receipts: "a run that diverges stores no receipt".

## Tests: failing before, passing after

All 27 new cases (`pytest -k r9` in `tests/test_stage3.py`) pass on r9-d and all 27 fail on 91c9777 with the new test file copied into a throwaway detached worktree (removed afterwards). The reasons I looked at on the unfixed code: `KeyError: 'err'` out of `run_window`; `[] == [<Re_L phrase>]` for M-23; `assert (False)` on `wall["diverged"]` for the last-chunk window; "the FEA ran on the wall pressure of a window that blew up" for the pipeline row; "DID NOT RAISE RuntimeError" for the calibrations. The last-chunk blow-up is the real solver with the force of the final chunk multiplied by NaN (`_nan_in_the_last_chunk`), so `nest.diverged` and `run_window` are the real code.

## Verified

On cafe-burst (`pm_r9d`, removed afterwards), exit codes read from the logs:
- `tests/test_stage3.py` whole file: all pass except `test_both_stored_passing_receipts_clear_only_the_wall_model_row`, whose fixture wrote receipts with only `err` and `code_sha` (exactly the M-4 case); I changed its fixture to whole records (`_stub_channel`, `_stub_plate`), the assertions are untouched, and the test passes alone. The rest of the file was not rerun after that fixture edit (the source did not change after the full run).
- `tests/test_nest.py tests/test_lbm.py tests/test_config_docs.py tests/test_receipts.py tests/test_credibility.py tests/test_audit.py`: rc=0 (whole files).
- `tests/test_pipeline.py -k sphere` (the ledger inputs of the refit floor): passes.
- `ruff check cafe/pm tests` clean; `mypy cafe/pm` (strict) clean, 54 files.
- Not run: the full suite, `audit` (coverage 100 % on physics/stats/env is untouched; `cafe/pm/stage3` is not in that gate, but I did not measure coverage of the new branches), mutation testing.

## What could break, and how I checked

- `nest.simulate` gained a keyword (default False): no existing call changes. Callers listed and checked: windows.py:300, wallmodel.py (two), nest.py:390 (sphere_drag, now strict), 411, 428 (not strict), tests/test_nest.py (unchanged calls). Whole-file results are in "Verified" below.
- `strict=True` in `sphere_drag`: `tests/test_nest.py` and `tests/test_lbm.py` sphere tests run sphere_drag at the sizes they use; a divergence there would now raise; none did ("Verified").
- `_read_receipt` takes `fields` now (private; only `wallmodel` used it).
- `stored_wall_error()` no longer calls `json.loads` on the files itself: `tests/test_config_docs.py::test_credibility_doc_has_no_claim_the_code_contradicts` pinned the source text of the old line; I changed that one assertion to the new line (`return None if problems else max(float(d["err"]) for d in recs)`), same claim (a max of the errors).
- `lbm.result_row`: callers are `lbm.receipts`, `nest.sphere_receipts`, `wallmodel.receipts`; a record that used to pass with a numeric value and reference is unchanged. A stored record with a numeric `cd` but no `ref` (never written by the code) now fails instead of raising.
- A last-chunk-diverged window changes the hashed `windows.json` for that window only (cut instead of NaN coefficients). A window that did not diverge is byte-identical; `test_a_run_that_is_not_cut_has_cut_false_and_keeps_its_numbers` and the equal-rows cut test are in the whole-file run.

## Needs from other batches

- **Batch B**: `credibility._stored_rows` (`cafe/pm/credibility.py` ~335) reads `float(d["cf"])`, `float(d[dk])` (`ittc` / `cf_dean`) and, for the spheres, `float(d["cd"])` from the same files with no field check, and `_json` raises `ConfigError` for a corrupt file. A `wm_*.json` or `*_sphere_*.json` with `cf: null` is still a `TypeError` there. Suggested: `lbm.read_stored(f, ("cf", "ittc"))` (plate), `("cf", "cf_dean")` (channel), `("cd",)` (sphere; `ref` is optional there) and a "not run: ... unreadable" row; or the same field list from `wallmodel.PLATE_FIELDS` / `CHANNEL_FIELDS`. (`read_stored` returns None for a corrupt file where `config.json_object` raises; whichever they pick, the cases need a test.) `credibility` already imports `lbm` lazily in this function.
- **Batch B / report**: `report.py` prints "window cut at the time limit: its coefficients are withheld" (CUT_STATEMENT, line 790) and "was cut at the time limit" (line 1344) for every `cut` window, including one that diverged (and now a last-chunk one). That was true before for mid-run divergence; the row's `resolution.cut_reason` has the right text. Their call.
- **Nobody needs anything from me for the others.** Batch C/E/F: no overlap in files.

## Still looks wrong / not done

- `lbm.main slow` and `nest.main slow` still write their result with `write_text` (not temp + `os.replace`, as `wallmodel._write_receipt` since round 8 M-32). The readers now survive a truncated file; the writers can still leave one. Not in the findings, not changed.
- `pipeline.s_refit` globs `nest_sphere_*` as ledger inputs (hash only, no parse): fine. `credibility` is the other raw reader (above).
- The `uniform_flow_force` / `shear_layer_mass` decision (fail their own bound on NaN) is argued from the code, not tested with a real blow-up.
- Whether NaN in a cut window's `timing.machine_dependent` (the ledger) breaks "same seed, identical report.json": not tested (the report reads none of it, by 186); the M-24 finding left this open too.
- Mutation testing of the new branches (`make mutation`) was not run (hours); the one-regression-test-per-fix check was by the unfixed-code run above.

## Follow-up after the adversary's pass (same branch, second commit)

**`lbm._real` raised `OverflowError` on a huge integer literal** (a stored `{"err": 9999...(400 digits)}` loads as a Python int and `math.isfinite` cannot convert it). `read_stored` caught only `OSError` and `ValueError`, so the gate, `stale_wall_receipts`, `lbm.receipts`, `sphere_receipts` and `sphere_discretisation` crashed: the M-4 failure again. Fixed in the one shared place, `_real`: `OverflowError` is "not a number" (the file counts as not stored, a failed row). Every reader goes through `_real` (`read_stored`, `result_row`, `wallmodel._read_receipt`, `nest.stored_grids`), so no caller needed a change; swept `lbm.py`, `nest.py`, `wallmodel.py` for another `isfinite`/`float()` on stored data: none outside `_real` (`nest.py:249` is on arrays). Tests: `test_r9_m4_*_integer_too_large_for_a_float_*` (five plate fields, three channel fields, `cd` / `ref` in `read_stored` and `result_row`); all ten fail on ef0415a with `OverflowError: int too large to convert to float` and pass after. `credibility._stored_rows` (batch B) is a separate raw reader and is not changed here.

Other items the adversary or the builder left, status:
- `nest.simulate` still returns two values (deviation from M-24's fix, argued above). `nest.diverged(series)` is the same predicate. A 3-tuple is a mechanical change if the lead wants it.
- The one assertion in `tests/test_config_docs.py` and the fixture in `test_both_stored_passing_receipts_clear_only_the_wall_model_row` changed in the first commit (listed above). The whole `tests/test_stage3.py` has now been rerun after both (rc=0).
- RUNBOOK line 218 should say "round 9" next to rounds 7 and 8 for the stale `physics_sha()`: docs are the lead's, not edited here.
- Not done, as before: full suite, audit, coverage of the new stage3 branches, mutation testing; `uniform_flow_force` / `shear_layer_mass` not tested with a real blow-up; `credibility._stored_rows` and `report.py`'s "cut at the time limit" wording (batch B); `lbm.main slow` and `nest.main slow` still write with `write_text`.

Verified for the follow-up, on cafe-burst (`pm_r9d`, removed afterwards), exit codes from the logs: whole `tests/test_stage3.py` rc=0; `tests/test_lbm.py tests/test_config_docs.py tests/test_receipts.py tests/test_credibility.py tests/test_audit.py` rc=0; the ten new cases rc=0 (and all ten fail on ef0415a, a detached worktree, removed); `ruff check cafe/pm tests` clean; `mypy cafe/pm` clean, 54 files. `tests/test_nest.py` not rerun (nest.py unchanged in the follow-up).
