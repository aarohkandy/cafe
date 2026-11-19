# Batch F hand-back (M-9: statistics, count and probability checks)

Branch r20-f from 8e22951. Files touched: `cafe/pm/stats/intervals.py`, `cafe/pm/stats/sequential.py`, new `tests/test_round20_f.py`. No existing test file changed, so **no pin moved** (`tests/test_round18_m.py`'s `_count` double and every other pin passed unedited). No document edited.

## merged.md's proposal: followed, and extended
The proposal (coverage and verdict through `_count`, `wilson` huge ints a ValueError, `sprt_decide` alpha and beta checked) is safe by measurement and was done. Round 19 fixed five functions and round 20 found the siblings, so every public function of both modules was listed (19 functions) and the ones taking a count or a probability all go through the shared helpers. Beyond the proposal, the sibling sweep found and fixed:
- `coverage`: a `p_grid` above 1 or NaN gave a coverage of **0.0** (silent wrong answer), a 2-d grid iterated rows.
- `verdict_from_p`, `verdict_band`, `band_in`: a NaN probability was **"NO-GO"**, a boolean (`True`) was a probability; no range check.
- `ensemble_stop`: `n < n_min` skipped the interval's check, so `ensemble_stop(5, 3, n_min=10)` was answered; `n_min` and `n_max` were not counts (2.5, True accepted).
- `set_thresholds`: `("0.9", .5)` a TypeError, `(True, .5)` accepted, a float32 or int stored as numpy scalar / int module state.
- `sprt_indifference`: negative delta gave the ends reversed, NaN gave NaN.
- `conf`, `level`, `cert_conf`: a string or None was a TypeError from the comparison, not the module's ValueError.
- `_kappa`: a numpy float32 `conf` computed the quantile in single precision (`wilson(3, 10, np.float32(0.5))` lower end 0.2127148644 against the float's 0.2127148628).

## Coverage of each public function
Table `TAKES` in the test file; `test_r20_m9_every_public_function_of_both_modules_is_in_the_table` fails if a public function is added or removed without a row (so no sibling is left unlisted). Shared helpers: `_count` (now also refuses a count above `MAX_COUNT = 2**53`), `_check` (counts + conf, returns Python ints), `_level`, `_unit(x, closed)` (a probability: real, not bool, not NaN, 0<x<1 or 0<=x<=1), `_closed(**named)`, `_real`.

| function | takes | how covered |
|---|---|---|
| wilson, agresti_coull, interval, interval_region, decided_region, newcombe_diff | counts, conf | `_check` (`_count` + `_unit(conf)`); already so, now with the 2**53 bound and the non-number conf |
| verdict | counts, conf, level, cert_conf | NEW: `_check` first, stores Python ints, `conf = float(conf)`; level and cert_conf via `n_certify`'s `_level` |
| rule_of_three | count | `_count` (bound) |
| coverage | n, p_grid, conf | NEW: `_check(0, n, conf)`; p_grid must be 1-d, finite, 0..1 |
| n_certify, n_certify_one_sided | level, conf | `_level` now uses `_unit` |
| verdict_from_p, verdict_band, band_in | probabilities (closed) | NEW: `_closed` |
| set_thresholds | go, nogo | NEW: `_real` + stores floats |
| sprt_decide | k, n, p0, p1, alpha, beta | counts `_count`; p0/p1 `_unit`; NEW: alpha, beta `_unit` |
| sprt_indifference | cut, delta | NEW: ends must satisfy 0 < p0 < p1 < 1 |
| ensemble_stop | k, n, conf, n_min, n_max | NEW: `_check` before the n_min test; n_min, n_max `_count` (n_max None allowed) |
| receipts | none | no argument |

## Before and after (job names, all on orca, proot, 2 CPUs, `pm_r20f*`)
- "Before": throwaway `git worktree add --detach ../cafe-r20f-base 8e22951` with the new test file copied in, job `r20f_base1`, rc=1: **203 failed, 1 error, 132 passed**. Failing groups: huge counts (33 + OverflowError and a 64 PiB allocation), alpha/beta (20), probabilities of the verdict functions (30 + 10 + 20), coverage (narrow ints, p_grid, conf), verdict dict (9 numpy dtypes, conf type), set_thresholds (5), sprt_indifference (12), sprt p0/p1 (2), ensemble_stop (16), conf/level non-number (30), float32 quantile (1). The 132 that pass before are the sanity and mutation-guard tests (closed ends accepted, table, grid digest).
- "After": job `r20f_2`, rc=0, **335 passed**. Final tree (test formatting wrapped, docstrings): job `r20f_final`, rc=0, 1354 passed (test_round20_f, test_round18_m, test_round19_f, test_config, test_stats, test_stats_exact, test_round18_f).
- Wider run on the fixed tree: `r20f_a` rc=0, 1704 passed (test_stats, test_stats_exact, test_round18_m, test_round19_f, test_round18_f, test_config, test_round15_a, test_acceptance, test_emulator, test_round20_f); `r20f_b` rc=0, 599 passed (test_budget, test_round17_a, test_round16_a, test_round14_survivors, test_round18_c, test_round19_a, test_whatif, test_par, test_usv).
- Ordinary answers did not move by a bit: `test_r20_m9_the_answers_of_ordinary_inputs_did_not_move_by_a_bit` hashes the `repr` of every wilson, agresti_coull, interval, region, whole `verdict` dict (3 variants), `verdict_from_p`, `verdict_band`, `band_in`, `sprt_decide`, `ensemble_stop`, `newcombe_diff`, `coverage`, `n_certify*`, `sprt_indifference`, and 4 threshold pairs over n = 1..80 (every k) and five larger n, 3 confidences (>10,000 rows). The digest `4d5c2eb6...eeb44` was taken on 8e22951 (`r20f_base1`, test passes there) and the fixed tree gives the same one (`r20f_2`, `r20f_final`).
- Gates: `ruff check cafe/pm tests` clean, `mypy cafe/pm` strict clean (55 files), job `r20f_gate` rc=0. Coverage of `cafe/pm/stats/intervals.py` and `sequential.py`: 100 % (135 and 33 statements, 0 missed) from the stats, round and receipts test files. The whole of `cafe/pm/stats` was not measured (rare, sampling, sensitivity not touched).
- Mutation: 43 hand-made one-line mutants of the new guards (bound of `MAX_COUNT` +1 and -1, `>` to `>=`, bool exclusion removed, each of the four `_unit` bounds, each `_closed` argument dropped, `_check` removed from verdict / coverage / ensemble_stop, p_grid ndim and both range sides and both bounds, set_thresholds guard and float, `_kappa` float, sprt_indifference guard and each of its three bounds, sprt_decide p0/p1/ordering/alpha/beta, ensemble_stop n_min / n_max): **43 killed, 0 survived** (jobs `r20f_mut`, `r20f_mut2`; driver was a throwaway, deleted). Not run: `make mutation` (the stored mutmut record).

## Things for the documents (batch G)
- DECISIONS row: counts above 2**53 are a ValueError (message "must be at most 9007199254740992 (2**53)"); `verdict` returns Python numbers only; probabilities of `verdict_from_p` / `verdict_band` / `band_in` / `coverage` p_grid are closed 0..1 and NaN, bool, str are refused; `sprt_decide` alpha, beta in (0, 1); `ensemble_stop` checks k, n before n_min; `sprt_indifference` and `set_thresholds` refuse non-probabilities. Amend row 1008 (round 19 M-8) which names the five functions.
- No number in report.json or summary.json moves (stage1 passes `int(f.sum())`, `len(...)`, plan ints).

## Not verified, still wrong, noticed
- Behaviour change to know: a bad probability reaching `verdict_band` / `band_in` (the emulator and what-if) is now a ValueError, where a NaN used to print "NO-GO". The emulator's p, lo, hi are clipped into (0, 1), and test_emulator, test_whatif and test_budget passed, but no real what-if run was made.
- `ensemble_stop` with n < 1 and n_min > n now raises where it returned stop=False; stage 1 always calls it with n >= batch, not exercised with n = 0.
- `verdict` with a float32 `conf` computes with the float of it (single-precision quantile fixed in `_kappa`); `sprt_decide`'s float32 p0, p1, alpha, beta still divide in single precision (not changed: no test can tell, results equal unless an llr sits within about 1e-5 of a threshold).
- Noticed, not changed (not a count or a probability): `coverage(.., method="wilsn")` silently runs Agresti-Coull (any method other than "wilson" does).
- `coverage(n)` with n near 2**53 would try to allocate an array of n + 1 (refused only above 2**53); not a correctness issue, no real caller.
- Not run: test_report.py, test_stage1.py, test_pipeline.py, test_cli.py (they use `verdict` and `ensemble_stop` with ordinary ints, covered by the digest) and no full suite, gate or demo.

## Leftovers
- orca: `~/cafe-worker/cafe/pm_r20f` (the fixed tree, one directory, marker `.pmx.job.pm_r20f`; tell me or remove it with `rm -rf` on that exact path) and logs `~/cafe-worker/logs/r20f_*.log` (r20f_base1, r20f_1, r20f_2, r20f_a, r20f_b, r20f_mut, r20f_mut2, r20f_gate, r20f_final). `pm_r20f_b`, `pm_r20f_base` and their markers were removed by exact name. No tmux session of mine alive, nothing in /tmp, no process killed.
- laptop: nothing in /tmp; the throwaway worktree `../cafe-r20f-base` was removed; no stash.
