# Round 19, batch F handback: M-8 and the A-8 tests of M-16

Branch `r19-f` (cut from 51eb433), worktree `cafe-r19f`. Commits: 7772d4a (code), db8d792 (tests), then this file. Open decisions: none applies to this batch (M-8 is "not an owner decision"), so nothing "awaiting the owner".

## Files touched

In my list: `cafe/pm/stats/intervals.py`, `cafe/pm/stats/sequential.py`, `tests/test_round19_f.py` (new, 105 tests with the parametrised rows). `cafe/fea.py`, `tests/test_stats_exact.py`, `tests/test_stage3.py`, `tests/test_round18_f.py`: no edit needed.
Outside my list: `tests/test_round18_m.py`, one line (see "Pins moved"). Batch B lists that file: a one-hunk touch, merge by hand if B edits the same line.

## M-8: narrow numpy integers in the count rule

Where: `intervals._count` now returns `int(x)` after the type check (bool and float still refused); `_check` returns `(k, n)` as Python ints; `wilson`, `agresti_coull`, `newcombe_diff` (both pairs) take `k, n = _check(...)`; `rule_of_three` takes `n = _count(...)`. `interval`, `verdict`, `interval_region`, `decided_region` and `ensemble_stop` go through `wilson`, so they are covered at the one rule. `sequential.sprt_decide` takes `k, n = intervals._count(k, "k"), intervals._count(n, "n")` and then refuses `not 0 <= k <= n` ("need 0 <= k <= n, got k=.., n=.."); k = 0 with n = 0 stays "continue" as today.
Callers grepped: `stage1`, `whatif`, `report`, `acceptance`, `credibility`, `pipeline`, `__main__` pass `int(...)` or JSON ints; `sprt_decide` has no caller outside tests.
Equal to today's: `cmp_f.py` printed `wilson`, `agresti_coull` (conf 0.9), `interval`, `newcombe_diff`, `verdict`, `interval_region`, `decided_region`, `sprt_decide`, `ensemble_stop`, `rule_of_three` for 92 (k, n) pairs (n from 1 to 4000, k at 0, 1, n/3, n/2, n-1, n) as Python int and as `np.int64`, on 51eb433 and on the fix: all values equal. The only difference: an `np.int64` input gave `np.float64` elements before and gives Python floats now (same values).
Test (fail before / pass after, on 51eb433 in a detached worktree and on orca): 58 of the M-8 tests fail before (r19f_old2: wilson, interval, verdict, interval_region, decided_region on uint8, int8, uint16, int16, uint32, int32; newcombe on the same six; the two reproductions of the finding; the stopper with uint8; `_count`/`_check` return types; the `sprt_decide` range rows; the helper-use test); all pass after (r19f_2, rc=0). Not failing before, kept as guards: `agresti_coull` (its `n + z*z` is float, so it never wrapped), `int64` and arrays equal Python ints, the range's edges, kind-before-range. Honest note on `sprt_decide`: with k <= n a narrow dtype gave the right answer before (`n - k` is not negative); the wrong decision of the finding needs k > n, which is now refused.

## A-8: the five mutants (reviewer A could not finish the wide rerun)

Wide selection per mutant: `test_round18_f.py`, `test_round17_f.py`, `test_round16_pb.py`, `test_round18_m.py`, `test_config.py` and `test_stage3.py -k "r15_l0 or r15_m14 or r16_m20"` for the hull mutants; `test_stats.py`, `test_stats_exact.py`, `test_round18_m.py`, `test_round18_f.py` for the `sprt_decide` mutants. Driver `mut_f.py` (scratchpad, run in orca's pmdata), `-x`, first failure = killed.

| mutant | before my tests | after my tests |
|---|---|---|
| G11 colon out of `_NOT_PLAIN_FIRST` | SURVIVED every file | killed by `test_r19_a8_a_plain_text_that_starts_with_a_colon_is_outside_the_grammar` |
| G14 `_MESH_KEY_LINE` check removed | killed only by `test_stage3.py::test_r15_l0_4_a_comment_or_blank...` (not by the fast files) | also killed by `test_r19_a8_a_key_line_with_text_after_the_colon_is_refused_as_a_key_line` |
| G16 whole line in the refusal (two sites, G16a "outside the grammar", G16b "is indented") | both SURVIVED every file | killed by the two `..._named_by_its_first_40_characters_only` tests |
| I7 `sprt_decide` without the k check | KILLED by existing `test_round18_m.py::test_e_sprt_decide_refuses_a_k_that_is_not_an_integer_count[True]` (it survived only A's narrow selector, `test_round18_f.py`) | no test needed |
| I8 the same for n | KILLED by `test_e_sprt_decide_refuses_an_n_that_is_not_an_integer_count[True]` | no test needed |
G15 is equivalent (A), not run. G11 note: `why: :a` is a text PyYAML may read; the test pins the documented closed grammar (the docstring's list of first characters), it does not claim equality with PyYAML. Extra mutants of the new code, all killed: `_count` returning `x`; the k check in `sprt_decide` as `k <= n`, `0 <= k`, `0 <= k < n`, `0 < k <= n`, dropped; I7/I8 in the new spelling.

## Decisions taken (text for batch G)

- DECISIONS (new row): "Round 19, M-8. `intervals._count` returns the count as a Python `int` (after the unchanged type check: an int or a numpy integer, not a bool or a float), `_check` returns `(k, n)`, and `wilson`, `agresti_coull`, `newcombe_diff`, `rule_of_three` and `sprt_decide` use what they return, so a numpy `uint8`, `int8`, `int16` or `int32` count cannot wrap in `4 * n * n` (`wilson(np.uint8(30), np.uint8(100))` was (0.0, 0.778), now (0.219, 0.396)). `sprt_decide` refuses k below 0 or above n (a count of n runs), ValueError, after the kind check; k = 0 with n = 0 is still 'continue'. Results for Python ints and `np.int64` are unchanged to the last bit (92 pairs compared); an `np.int64` input now returns Python floats, not `np.float64`. Amends 967 and 972." Verified by 58 tests failing on 51eb433.
- CHANGELOG: "Counts of the interval functions and of `sprt_decide` are Python ints after the check (narrow numpy integers no longer wrap); `sprt_decide` refuses k outside 0 to n."
- DECISIONS (same or a second row): "A-8: three refusals of the hull-mesh reader are pinned (a plain text starting with `:` is outside the grammar; the key line holding a value is named as a key line; the refusal prints the first 40 characters of a line); I7 and I8 of reviewer A were killed by `test_round18_m.py` and need nothing."

## Pins moved

`tests/test_round18_m.py::test_e_sprt_decide_uses_the_helper_of_the_interval_functions`: its patched `_count` returned None; `sprt_decide` now uses the return value, so the double returns `x` (`... or x`). The assertions on the calls `[(2, "k"), (5, "n")]` are unchanged. No other pin moved (`test_stats*`, `test_round18_f`, `test_stage3` unchanged and green).

## Verification (orca, proot, 2 CPUs each)

- `tests/test_round19_f.py`: rc=0 (r19f_2 and in `r19f_all`); on 51eb433: rc=1, 58 failed.
- `r19f_all` (one file per pytest call): test_round19_f, test_stats, test_stats_exact, test_round18_f, test_round18_m, test_round17_f, test_round16_pb, test_config, test_acceptance, test_whatif: all rc=0.
- `tests/test_stage3.py` (whole file, once, last): rc=0 (`r19f_stg`). There is no `test_intervals*`, `test_sequential*` or `test_fea*` file in the repo.
- `ruff check cafe/pm tests`: clean (r19f_ruff2; the first run found one line of 166 characters in my pin edit, shortened). `mypy cafe/pm`: "no issues found in 55 source files" (r19f_mypy).
- Coverage of `cafe/pm/stats` (`--cov-branch`, only the five stats-related files above): `sequential.py` 100 %; `intervals.py` 92 % with its misses at lines 41, 80, 124, 152, 159-161 (`set_thresholds`' and `_level`'s and `rule_of_three`'s refusals, `verdict_band`, `band_in`), none of them lines this batch added: other test files cover them. Every line I added or changed is covered. I did not run the whole suite's coverage gate.
- No banned token in the diff (grepped `audit.BANNED`).

## Not verified / cross-batch

- No cross-batch needs: no other batch's file is needed for M-8. Batch G: the rows above.
- Not run: the full suite or `make audit`; `mutmut` (the 85 % mutation gate on stats); the coverage gate of the whole suite.
- A reviewer's other A-8 claim "G15 equivalent" not re-checked.
- The G11 mutant's behaviour under PyYAML (whether `why: :a` loads) was not run.

## Orca leftovers (all mine, inside `~/cafe-worker`, none running, `tmux ls` shows no `r19f_*`)

Directories under `~/cafe-worker/cafe/`: `pm_r19f`, `pm_r19f_old` (51eb433 plus my test file), `pm_r19f_m`, `pm_r19f_lint`, `pm_r19f_cov`, and the markers `.pmx.job.pm_r19f*`. In `pmdata/`: `mut_f.py`, `cmp_f.py`, `f_runall.sh`, `f_test_*.out` (ten files). Logs `~/cafe-worker/logs/r19f_*.log`. One job I killed by exact session name: `r19f_muti` (rc=143; it used a selection that included my new tests against the old code, rerun as `r19f_muti2`). Local: the scratch worktree `cafe-r19f-old` is removed.
