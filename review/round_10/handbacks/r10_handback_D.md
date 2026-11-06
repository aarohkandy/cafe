# Round 10, batch D handback (branch r10-d, worktree cafe-r10d)

Findings: M-19, M-20 (code); M-22, M-37 (no code, see the end). Base 6c352ef; next free DECISIONS row at the base is 535, so the numbers below are
suggestions for the lead to renumber. Docs were not edited.

## M-19 `tao._candidates` found the deployment in the water over the files of every variable

Fix, in the one shared place: `tao._candidates` (cafe/pm/env/tao.py) now finds the latest start at or before t0, and the 10-day twin window from
it, per (variable, resolution) pair instead of over the whole listing. D and R files of one pair still share the window (the A/B twin rule and
the mode tie-break are unchanged). Its only caller is `fetch_tao`, which filters `var`/`res` after it as before.

DECISIONS row (suggested 535): `tao._candidates` finds "the deployment in the water at t0" separately for each variable and resolution (the latest
start <= t0 among the files of that pair, its D/R twins up to 10 days before it, and every later start <= t1), not once over all files of the
mooring. Before, a sensor re-deployed after the others (WIND dated 20230101, SST dated 20230220, t0 = 2023-03-01) moved one window to 10 Feb for
every variable and the only wind file in the water was never a candidate: the mooring lost the variable from the prior fit with no note in the
manifest. An hourly file no longer moves the window of the 10-minute twin either. `fetch_tao` still keeps, per mooring and variable, the file with
the most QC-good samples (delayed-mode first on a tie). Amends 490 (the rule it pins now holds per variable and resolution; its test
`test_r9_m30_candidates_*` gives its dicts `var` and `res`, assertions unchanged). Tests: `tests/test_tao.py::test_r10_m19_*`.

Earlier rows amended: 490. Relates to 44 (the twin rule, as quoted in 490), 491 and 506 (unusable files are skipped per candidate; unchanged).

CHANGELOG: TAO deployment selection is per variable and resolution: a mooring whose SST (or any one variable) was re-deployed later than its wind
no longer loses the other variable from the prior fit.

Doc sentences: none required. If the TAO section of PHYSICS.md or the RUNBOOK says "the deployment in the water", add "(found separately for each
variable and resolution)". Not checked: whether the real NDBC catalog ever dates variables of one deployment differently (no catalog in the repo or
in q10); the code no longer depends on it either way.

Checked what could break, and how:
- Callers of `_candidates`: `fetch_tao` only (grep over cafe/, tests/, bin/). Callers of `fetch_tao`: `pipeline.py:433` (ingest) and tests.
- Output order: `_candidates` now returns files grouped by (var, res) in first-seen order, each group in listing order. `fetch_tao` filters one
  (var, res) afterwards, so the order within a group, which breaks `score >` ties, is the listing order as before. Nothing else reads the order.
- More downloads for a mooring whose variables really differ (a variable's earlier twin files are now candidates). Cannot be measured here: no
  catalog. The existing `tree` fixture (tests/test_tao.py) has the same download count (8) and selection as before; whole tests/test_tao.py passes.
- A TAO cache built before this change is still accepted by `pipeline._tao_cached` (it checks box, window, hashes and `unusable_selected`, not the
  selection rule). So q10's TAO cache keeps its old selection; a re-fetch needs its `manifest.json` deleted. See "needs from other batches".
- Sibling search: no other code picks a deployment by date (`grep 86400|"dep"|["date"]` in cafe/pm outside physics/stage3: only `_candidates`).

## M-20 `hycom.check_node` returned 0.0 when either value was NaN

Fix in `hycom.check_node` (cafe/pm/env/hycom.py): NaN on both sides (store value and a server answer with no finite value, empty answers
included) is agreement and contributes nothing; NaN on exactly one side contributes `inf`; otherwise `abs(nanmean(server) - store)` as before.
I chose `inf` over a raise: the function returns "the largest |server - store|", infinity is the correct value of that for a masked-vs-finite
node, and a caller comparing with a tolerance fails it without a new exception path. The docstring now says callers compare with a tolerance and
never `== 0`.

DECISIONS row (suggested 536): `hycom.check_node` treats a node masked (NaN) on both sides as agreeing (0.0) and a node masked on one side only
(a NaN store value against a finite server answer, or a finite store value against an answer of NaN only or an empty one) as `inf`. Before,
`max(worst, nan)` kept `worst`, so all three cases returned 0.0, the value of a store that agrees. No caller outside the tests (it is not a
registered receipt), so no verdict, printed number or gate changed. Amends 507 only in that it names `check_node` (nothing in 507 changes). Tests:
`tests/test_hycom.py::test_r10_m20_*`.

Earlier rows amended: none (507 mentioned, unchanged).

CHANGELOG: `hycom.check_node` no longer passes a node that is NaN on one side only: the result is `inf`; NaN on both sides still agrees.

Doc sentences: docs/PHYSICS.md:458 (goes to F): "The real-store check against NCSS (`check_node`) needs the network and is not a registered receipt. A
node masked on both sides agrees; masked on one side only gives infinity, never 0.0."

Checked what could break, and how:
- Callers of `check_node`: tests/test_hycom.py only (grep over cafe/, bin/, docs/, tests/); the module docstring line 9 and PHYSICS.md:458 mention it.
- Return type is still `float`; `inf` is a float. A future caller must compare with a tolerance (stated in the docstring).
- `np.atleast_1d` added on the server answer: `squeeze()` of a one-node answer is 0-d, and the NaN test uses `.all()` on it.
- The warning `np.nanmean` printed for an all-NaN answer is gone (it is no longer called on one).
- Sibling search (`max(worst, abs(...))` and nanmean-then-max shapes in cafe/): no other instance in env/. `physics/comms.py:400` and
  `physics/glider.py:617` have the same `worst = max(worst, ...)` shape but over `np.max` (propagates NaN) and `np.hypot / abs(B)` of physics
  values, not environment reads; not changed (RC-4 lists the physics NaN handling under M-15, batch with pipeline_windows).

## Tests and gates

- New tests: `tests/test_tao.py::test_r10_m19_the_deployment_in_the_water_is_found_per_variable_and_resolution` (unit: wind and SST, hourly twin,
  D/R twin), `::test_r10_m19_fetch_keeps_the_wind_of_a_mooring_whose_sst_was_redeployed_later` (through `fetch_tao` with a stand-in catalog);
  `tests/test_hycom.py::test_r10_m20_a_node_masked_on_one_side_only_is_infinitely_far_and_on_both_sides_agrees` (3 cases: server-all-NaN,
  store-NaN, both-NaN-agree) and `::test_r10_m20_a_masked_node_is_not_hidden_behind_an_agreeing_one`. The test server `Ncss` got a mode "nan".
- Shown failing on the unfixed code (6c352ef sources, new tests, throwaway detached worktree, removed): both M-19 tests fail (candidates
  `['SST...']` instead of wind and SST; `selected` lacks WIND); M-20 `server-all-NaN`, `store-NaN` and the hidden-behind case fail (`0.0 == inf`).
  `both-NaN-agree` passes on the unfixed code on purpose (it pins that the fix does not break the masked-both-sides case). Edited existing test:
  `test_r9_m30_candidates_*` only gained `var="WIND", res="10min"` in its dicts (needed by the per-pair lookup; assertions unchanged).
- Whole files on orca (PM_HOST=cafe-orca, proot, 2 CPUs): `tests/test_tao.py` and `tests/test_hycom.py` pass, rc=0. ruff `cafe/pm tests` clean; mypy
  `cafe/pm` strict clean (55 files). `audit --code-only` printed one problem only: no `docs/mutation.json` in the worktree (a stored mutation
  result, not a banned token; nothing else reported). Mutation (`make mutation`) and coverage were not run in this batch (hours); every new statement
  is executed by the new tests, but the 100 % coverage of `env` was not measured here.


## Needs from other batches

- Lead / F: PHYSICS.md:458 sentence above (M-20).
- Lead: `pipeline._tao_cached` accepts a TAO cache made under the old selection. If the owner wants q10's or any earlier cache re-selected, delete
  its `tao/manifest.json` (the files stay; `fetch_tao` re-hashes and re-fetches only what is missing). I did not touch pipeline.py (not in this
  batch's files); a rule-version field in the manifest would be a separate change.
- Nothing needed from A, B, C, E, F in code.

## M-22 and M-37 (no code, as assigned)

- M-22 (UMWM time is the file name only): stated assumption for the docs step. Suggested sentence for DECISIONS 14 (amend): "The Times check holds
  for WRF only. A UMWM hourly file (umwmout, umwmrst) carries no time in its content (no global attributes, no time variable: BRIEF.md:54, the
  schema), so its hour is trusted from its file name; two hours served as one file, or an output stamped at the end of an averaging period, would
  shift the waves against the wind unflagged. The pooled u* agreement (`_ustar_agreement`, DECISIONS 168, 393) would probably not catch a one-hour
  shift (not measured)." A content cross-check in `orca.assemble` was not built.
- M-37 (`remote.download` resume without checking 206): not confirmed; nothing done.
