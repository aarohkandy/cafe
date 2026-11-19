# Round 21, batch C hand-back (command line and app: M-8, M-11, M-12, and `hangar.grid_warning` for M-5)

Branch `r21-c` (cut at 7599881), worktree `/Users/aaroh/Downloads/everything/cafe-r21c`. Defaults taken: OD-5 (a), OD-10 yes, OD-11 (a). Nothing deployed, no `sync.sh` or `run.sh`, no demo, gate or full suite.

## 1. What changed and why

Files: `cafe/pm/__main__.py`, `cafe/hangar.py`, `cafe/app.py`, `cafe/_site_data.py`, `cafe/static/app.js`; tests `tests/test_round21_c.py` (new), `tests/test_round19_c.py`, `tests/test_round20_c.py`, `tests/test_round20_m.py` (ingest-ocean case only).

**M-8 (`__main__._plan_sizes`).** `PLAN_SIZE_MAX` (10**6) is deleted. After the budget name is validated, `batch` must satisfy `1 <= batch <= min(budget.BATCH[name], n_max)` and `1 <= n_min <= n_max <= budget.N_MAX[name]`, all `type is int`. The message keeps the words "plan.json has batch ..." and now names the limits: "n_max at most 64 and batch at least 1, at most 32 and not above n_max, for budget quick". Every plan `budget.plan` writes passes by construction (`n_max = min(N_MAX, n_batches*bs)`, `n_min = min(N_MIN, n_max)`, `batch = min(bs, n_max)`, `bs <= BATCH`).

Fields of plan.json and how each is bounded (lead's request). A what-if reads from the file only `budget`, `batch`, `n_min`, `n_max` (`_whatif` copies those three into the machine's own plan: `ctx.plan.update(...)`); nothing else of the file reaches `stage1.run`, `whatif.measure` or any allocation.

| field | what reads it | bound |
|---|---|---|
| `budget` | `_whatif`, `_report` (resume hash) | `type is str` and a key of `budget.BUDGET_S` |
| `batch` | `_whatif` (sizes blocks and the ensemble) | `1 <= batch <= min(BATCH[budget], n_max)` |
| `n_min`, `n_max` | `_whatif` (`stage1.run` stops at `n_max`) | `1 <= n_min <= n_max <= N_MAX[budget]` |
| `budget_s, gpus, days, stage1_s, stage1_share_s, workers, workers_by_cpu, workers_by_memory, mem_gb, env_gb, stage1_s_basis, tasks, sitl_members, member_cost, les, refit_iterations, notes, certify_possible, shares, vehicle_classes, vehicle_scopes, seed_override, refit_iterations_max, stage3, emulator` | `report --run` (`budget.describe`, `report._machine/_timing/_stage3/_les_reach`, `budget.emulator_plan`: printed or divided), `acceptance` (`les` only), the audit (hash of the bytes) | not bounded, and need none: none is a count of anything built. A huge number can at worst be an arithmetic error (the M-9 class: batch D's `ArithmeticError` in `damaged_run_files`), never memory. Dict-valued fields grow with the file's own size only. |

`tests/test_round21_c.py` keeps this table as three sets (`SIZE_FIELDS`, `NAME_FIELD`, `DISPLAY_FIELDS`) and fails if the planner writes a field in none of them, so a new field has to be looked at; and one test sets every numeric display-only field to 10**9 in a run's plan.json and checks the what-if still answers and runs on the machine's own plan, not the file's number.

I did NOT add `_plan_sizes` to `report --run`: it reads no size to build anything, and a re-render of an old run made under older tables must stay possible.

**M-11 (`__main__._ingest_ocean`).** `hycom.dead_note(spec["path"])` is asked and printed BEFORE `ingest_lab_hycom` (flushed, so it shows during a long ingest), with `dead_note`'s wording plus ": this ingest does, once it has written the new store". The `asides` note stays after the "ocean store:" line. Output order for a store with a leftover is now: note, "ocean store: ...", then the asides note. I printed before, not after, because after a successful write the directory is gone and a note telling the user to `rm -r` it would be stale; printed before it is true even if the ingest then fails ("once it has written").

**M-12.** (a) `hangar._write_result(d, res)` replaces the three `atomic.write_json(d / "result.json", res, default=_j)`: one pass through `json.loads(..., parse_constant=lambda _: None)` turns every NaN/Infinity (python float, numpy float, array item) into null; byte-identical output for finite results (tested). (b) `app._read` (the one place the app reads its files) reads NaN/Infinity tokens as null, so a result written by an older hangar is a 200 with `gci: null` too (writing alone would leave every stored file a 500). (c) `_site_data.gci_table(dirs)` (new, used by `hull()`): null where `vv.gci_value` is inf (NaN, missing key, non-number), else `round(g, 4)`. (d) `app.js`: `gciText(gci)` shows " no index" for null/undefined and " ±N%" otherwise, used at both former `(x.gci || 0)` sites (cfd directions and free-surface speeds); `0` still reads "±0%".

**M-5 (`hangar.grid_warning` only).** The limit is `vv.GCI_TRUSTED` (was literal 0.3); a missing `gci` key is `None` (read as inf by `vv.worst_gci`; was 0.0, a perfect grid); the text no longer says "verdicts lean MARGINAL": "...so the grid index cannot stand for the drag uncertainty: the mission takes the spread of an estimate instead, and a verdict for this vehicle is not decided by the CFD. A finer mesh level would narrow it". The "takes the spread of an estimate" claim is true only after batch D's `drag_sigma` change merges (the contract).

## 2. Evidence (orca, proot, 2 CPUs, PMX `pm_r21c`, `pm_r21c_b`, `pm_r21c_base`)

- New file on the fix: `python -m pytest tests/test_round21_c.py` rc=0, 104 passed at the first run (two tests were added later; final runs below).
- New file on the unfixed tree (detached worktree `../cafe-r21c-base` at 7599881, test file copied in, `pm_r21c_base`): rc=1, 85 failed, 19 passed. Failing: all 60 `_plan_sizes` refusal cases (no message words, and 16 did-not-raise for the pre-fix bounds: batch above table, n_max above table, batch above n_max, 10**6, 10**400 where 10**400 is also a pre-fix refusal with the old message), the 5 what-if cases (rc 0 where 2 is needed: `batch` 1000, `n_max` 65, `batch` 33, `batch` 10**6 is rc 0 on the old tree), both M-11 tests, all 6 + 3 + 1 + 1 M-12 tests (`hangar._write_result` absent; the endpoint's NaN not null), all M-5 tests but the ones that guard unchanged answers. The 19 that pass on the old tree are guards of answers that did not change (the planner's plans accepted, the field classification, the budget-name cases, finite results written as before).
- M-12 mechanism on the old tree (`pm_r21c_base`, script `get_design` on a stored `NaN` gci): `value nan`, then `JSONResponse(jsonable_encoder(out))` raises `ValueError Out of range float values are not JSON compliant: nan`. (`httpx` is not installed in the image, so there is no `TestClient`; the tests call the endpoint function and the encoder directly.)
- Existing plan.json files on orca, read only, tables typed into a script: all 28 (`pmdata/runs/*`, `pmdata/evidence/q9_burst_08f05d7`: quick, 32/32/64) pass the new bound, including q22.
- `app.js`: `node --check` passes. Not run in a browser. By a Node script that extracts the `fmt` and `gciText` lines and runs them: null -> " no index", undefined -> " no index", 0 -> " ±0%", 0.0205 -> " ±2%", 1.5 -> " ±150%".

- Jobs on the final tree, all ended with an rc line or exit code: (1) `tests/test_round19_c.py tests/test_round20_c.py tests/test_round20_m.py tests/test_round18_a.py tests/test_round19_m.py tests/test_round20_e.py tests/test_round21_c.py` (TM `r21c_a`, before two tests were added and lines wrapped): rc=1, 257 passed, 3 failed: exactly the three tests of section 6 (items 1 and 2), nothing else. (2) `tests/test_cli.py tests/test_whatif.py tests/test_budget.py` (TM `r21c_b`): rc=0, 448 passed. (3) After the last edits, `tests/test_round21_c.py tests/test_round19_c.py tests/test_round20_c.py tests/test_round20_m.py`: rc=1, 198 passed, 1 failed (item 2 of section 6, the grid-warning test of `test_round20_m.py`: `vv.GCI_TRUSTED` is absent until batch D merges, and it pins the old sentence). With the section 6 hunks applied temporarily (and a `monkeypatch.setattr(vv, "GCI_TRUSTED", 0.3, raising=False)` for item 2) the three tests pass (rc=0, 3 passed); the temporary edits are reverted, the tree holds none of them.
- `python -m ruff check cafe/pm tests`: rc=0 (All checks passed). `python -m mypy cafe/pm`: rc=0 (no issues in 55 source files).
- Coverage: not measured (no gate run). Every statement I added in `cafe/pm` is in `_plan_sizes` and `_ingest_ocean`, each run by the tests above (the refusal, the acceptance, the note and no-note branches). `cafe/app.py`, `hangar.py`, `_site_data.py` are outside the coverage gate.

## 3. Siblings (grep) and what I did

- Other readers of a plan.json size: `_report` (display only, see table), `acceptance.py:197` (`les`), `pipeline` (writes it), `ledger` (hash). Safe by reading.
- Other `10**6`-style second constants for plan sizes: only `PLAN_SIZE_MAX`, deleted. References left in documents: see section 5.
- Other readers of `.dead.tmp` notes: `pipeline._need` already asks before any write (right). `ingest-ocean` was the one.
- `r.get("gci", 0.0)` readers: `hangar.py` (fixed, both lines), `vehicle.py:290,344`, `mission.py:65,67` (batch D's files, per the contract; not touched).
- NaN tokens in JSON the app serves or the site ships: `_read` is the only app reader of a file (the others: `app.py:92` already `allow_nan=False`, `:155` already strict); `site/data/*.json` contain no NaN/Infinity token (grep), and no site JavaScript reads `gci` from `hull.json` (grep: the only JS readers of `gci` are `app.js:463-464`, which read design results). `_site_data.save` still writes with `allow_nan` on: not changed (a NaN in another field of a site file would still be written; none is).
- `app.js` other uses of a possibly-null hangar number: `x.force[ax]` at line 463 would show 0 for a null force component (a NaN force written as null). Not changed; no real result has a non-finite force (the three real fixtures in `tests/fixtures/cfd_real` contain no NaN/Infinity token).

## 4. Hostile-reviewer attempts

M-8: batch = BATCH+1 with n_max at its table (quick, 4h, overnight; for ci BATCH = N_MAX so only n_max can refuse it), n_max = N_MAX+1, n_min = n_max+1, n_min 0, batch 0 and -1, n_max 0, batch above n_max (3 vs 2), 10**6, 10**400 (int compare does not overflow), bool True, float 1.0, text "64", null, budget as list/null/int/unknown/bool/dict; each for all four names; edge values accepted (`batch=1,n_min=1,n_max=1`; `batch=2,n_min=1,n_max=2`; the table edge itself for each name); the plan the planner writes (hypothesis: 60 draws over name x batch_day x member_day, PlanError skipped) accepted. The bound is moved by one in either direction by at least one case (`BATCH+1`, `N_MAX+1`, `batch 3 / n_max 2`).
M-11: nothing beside the store (no note), another store's leftovers (no note, existing test), the store's parent directory missing (`_leftovers` catches OSError: no note, no crash), whole aside plus dead (both notes, order note / store / aside), a sweep that deletes before the note would be asked (the old order: the stub records `at_note`).
M-12: NaN, inf, -inf, numpy float64/float32 NaN and inf, an array with a NaN item, the strings "NaN" and "Infinity" (kept as text), clean files unchanged byte for byte, the three tokens in a stored file through the endpoint, a missing file and a damaged file in `_read`.
M-5: the limit exactly (0.3 trusted, next float above warns), the constant moved to 0.5 and 0.1 (the warning follows), missing key in cfd, cfd_aoa, fs, bool/text/list/dict/-inf gci (all "no index"), no study, `cfd=None`, converged study.

Not tried: a negative gci reads as converged here (`-1 <= GCI_TRUSTED`); no code writes one.

## 5. Decision text and documents (for batch G)

Decision text (DECISIONS, new row; OD-5 needs the owner only if they want the old 10**6 back): "`plan.json`'s bound is the planner's own tables, not a second constant: `batch` at most `budget.BATCH[name]` and not above `n_max`, `n_max` at most `budget.N_MAX[name]`, `1 <= n_min <= n_max` (`__main__._plan_sizes`); a plan the planner wrote always passes, a plan made under older tables that exceeds them is refused with the damaged-file message (none of the 28 plan.json files on orca is). The what-if reads only `budget`, `batch`, `n_min`, `n_max` from the file; the other fields are display only." Second row: "`ingest-ocean` asks for a half-deleted `.dead.tmp` before the write that deletes it and prints the note before the ingest starts". Third: "result.json and hull.json carry null, never NaN, for a direction with no index; `app._read` reads the NaN token as null; `app.js` shows 'no index'". Fourth: "`hangar.grid_warning` uses `vv.GCI_TRUSTED`, reads a missing key as no index, and says the mission takes the spread of an estimate".

Document sentences that must change:
- `docs/RUNBOOK.md` line 280: "`batch` and `n_max` are also at most 1000000 ... `... has batch ..., batch and n_max at most 1000000`" -> the tables of the run's budget and the new message ("n_max at most N and batch at least 1, at most B and not above n_max, for budget NAME").
- `DECISIONS.md` 1022 (the `PLAN_SIZE_MAX` = 10**6 sentence) and `CHANGELOG.md` 914 (same); `QUESTIONS_FOR_LAB.md` 18e (its "Alternative: the budget table's own largest values" is now the default).
- `DECISIONS.md` 1025 / CHANGELOG round 20 ("`ingest-ocean` names it" and "the next ingest ... deletes it too"): it names it before the write, and says this ingest deletes it.
- `DECISIONS.md` 1033 "Not changed and still a gap: `cafe/static/app.js:463-464` ... '+-0%' ... `_site_data.py:186`": both are now fixed (null, "no index"); the missing key read as 0.0 stays for `vehicle.py` and `mission.py` (batch D).
- `QUESTIONS_FOR_LAB.md` 18h: the warning text.
- `tests/test_round20_d.py` line 73 docstring ("`_site_data.py` reads `v["gci"]` ... a KeyError without it") is stale: `gci_table` reads a missing key as no index.

Pins moved (each by design):
- `tests/test_round19_c.py::test_m10_the_sizes_a_real_plan_has_are_read_as_they_were`: `n_max=72` -> `48` (72 is above quick's 64, which no plan has).
- `tests/test_round20_c.py::test_m5_the_bounds_are_the_edge_not_below_it_and_every_budget_name_is_read`: rewritten: the edge is each budget's own table (accepted) and one past it (refused); the old `batch=10**6, n_max=10**6` accepted and `batch=32, n_min=32, n_max=64` for every name (ci has 16) are plans no planner writes.
- `tests/test_round20_c.py::test_m5_a_sound_plan_whose_budget_differs_from_the_flag...`: sizes set to ci's (16/8/16) so the plan is sound and the flag message is still the one reached.
- `tests/test_round20_c.py` M-8 ingest-ocean tests (two): order of lines (note first) and the first test's `startswith` -> `endswith`.
- `tests/test_round20_m.py::test_m2_ingest_ocean_prints_the_wording_of_hycom_dead_note_and_no_other` (HUNK, the `ingest-ocean` case, mine): `lines == ["note:" + hycom.dead_note(out)[1:] + ": this ingest does, once it has written the new store", f"ocean store: {out}"]` and the two `not in lines[1]` -> `lines[0]`.

## 6. Hunks for other batches (I did not edit these files)

1. **`tests/test_round18_a.py` (batch B's file), two tests, red on this branch alone until edited**:
   - `test_m5_the_ensemble_of_the_fallback_is_the_runs_own_and_not_this_machines_plan_for_the_budget` (line 297-300): `d.update(batch=24, n_min=24, n_max=72)` -> `d.update(batch=24, n_min=24, n_max=48)` and `(24, 24, 72, "quick")` -> `(24, 24, 48, "quick")`. Reason: 72 is above quick's table (64).
   - `test_m5_a_run_made_with_another_budget_is_answered_with_that_budgets_plan` (line 306): `d.update(budget="ci")` -> `d.update(budget="ci", batch=16, n_min=8, n_max=16)`. Reason: the fixture's quick sizes (32/32/64) are not a ci plan; with only the name edited the plan is now refused.
2. **`tests/test_round20_m.py::test_m3_the_hangar_warns_of_a_grid_with_no_index_wherever_it_stands_and_says_so` (not an ingest case; batch D's/lead's)**: `"verdicts lean MARGINAL" in w` -> `"not decided by the CFD" in w`. Red on this branch alone for two reasons: the sentence, and `vv.GCI_TRUSTED` does not exist until batch D merges (AttributeError in `grid_warning`). This is the only existing test that calls `grid_warning`.
3. Batch D: `vv.GCI_TRUSTED` is read as `vv.GCI_TRUSTED` (the constant only; `vv.gci_trusted` is not used). My tests set it with `monkeypatch.setattr(vv, "GCI_TRUSTED", 0.3, raising=False)` so `tests/test_round21_c.py` passes on this branch alone and after the merge (then it overrides to its own value). Tests red on this branch alone: items 1 (two tests) and 2 (one test) only, measured above.

## 7. q23 against q22

Expected: nothing moves. `plan.json` of q23 is a planner plan (quick, 32/32/64) and passes; no vehicle in the demo has a GCI above 0.3 (real fixtures 0.001 to 0.125); the app and `ingest-ocean` are not in the run. `report.json`/`credibility.json` do not read anything I changed.

## 8. Not verified, problems met

- `app.js`: not run in a browser (none here); only syntax-checked and the one helper run in Node.
- The endpoint is called as a function and rendered with FastAPI's `jsonable_encoder` + `JSONResponse`; no HTTP client (`httpx` absent from the image), no real uvicorn. The old tree's raise there was measured (ValueError), the status code the app's `ValueError` handler would give was not.
- `hangar.run` end to end with a real CFD result was not run; `_write_result` is tested on a synthetic result.
- NaN items in numeric arrays of a stored result now read back as null (object arrays) in `load_vehicle`/`vehicle.build`, where they were silent NaN floats: a TypeError at build rather than a silent NaN. No real result has one (cfd_real fixtures: no non-finite token); I did not check the other hangar parts (bem, fea) for real NaN.
- `_plan_sizes` is not called by `report --run` (by decision, see section 1).
- Laptop: wrote one file `/tmp/probe1.py` by mistake and removed it at once (exact name); nothing else outside the scratchpad `.../scratchpad/r21c`.
- Orca leftovers: none. `pm_r21c`, `pm_r21c_b`, `pm_r21c_base` and their `.pmx.job.*` markers were removed by exact name; logs `~/cafe-worker/logs/r21c_a.log` and `r21c_b.log` remain (small). Laptop: the throwaway worktree `../cafe-r21c-base` was removed; scratch files are in `.../scratchpad/r21c`.
