# Round 21, batch F hand-back (M-13 / D-7: statistics that pass the guard and fail in the arithmetic)

Branch `r21-f`, cut at 7599881. Files: `cafe/pm/stats/intervals.py` (the batch's own file) and, for the siblings the sweep found, `cafe/pm/stats/{sequential,sensitivity,rare,sampling}.py`; new `tests/test_round21_f.py`. `tests/test_round20_f.py` is unchanged (the digest test passes as it is). No document touched.

## What changed and why

The brief's class is "the result is checked, not just the argument", so the fix is one rule plus a sweep of everything in `cafe/pm/stats` (five modules, 35 public functions) over its guarded domain, edges included.

**D-7 itself (`intervals.py`)**
- `n_certify` and `n_certify_one_sided` raise the module's `ValueError` ("the certification count for level=.. and conf=.. is not a finite count at most 9007199254740992 (2**53)", one helper `_no_count`) when the count made is infinite, NaN or above `MAX_COUNT`. The check is on the result, after the arithmetic, so no range of (level, conf) is listed. OD-13's default taken.
- Beyond OD-13's default, found by the sweep, same function: `n_certify_one_sided` was wrong in its arithmetic, not only at the edge. `log(1 - x)` is 0 for x under 1.1e-16 (ZeroDivisionError for the level; a count of **0** for the confidence: `(0.05, 1e-20)`), and `1 - x` loses digits above that: a level of 1e-8 gave 299573225 for the exact 299573226, 1e-12 gave 2995798545770 for 2995732273553, (3e-16, 1e-10) gave 300241 for 333334, (1e-16, 0.5) gave 6243314768165359 for 6931471805599453 (exact = 60-digit `Decimal`, test oracle). So below 1e-3 (either argument) it uses `log1p`; at and above 1e-3 the expression is the old one, bit for bit (measured: `log1p` everywhere would have moved 5 of 998,001 decimal pairs, e.g. (0.3, 0.51) 2 to 3 and (0.1, 0.271) 4 to 3, which is why it is not used there). A count that underflows to 0.0 (conf 5e-324 over level 1 - 1.1e-16) is `max(1, ..)`: one member, never none.
- `level` is taken as a Python float in `n_certify`/`n_certify_one_sided` (as `_kappa` does for `conf`): a numpy float32 divided in single precision, a numpy float64 subnormal warned on overflow.
- `set_thresholds` refuses two cut-offs that are one after the 12-place rounding (`go=0.9, nogo=0.8999999999999`; `go=1e-300, nogo=5e-324` gave P_FAIL_GO = P_FAIL_NOGO = 1.0, so every ensemble was GO). The state is untouched on refusal.

**Siblings found by the sweep (each failed on 7599881; each has a test)**
| function | input that passes its guard | before | after |
|---|---|---|---|
| `sequential.sprt_indifference` | `delta` a huge int (`10**400`, `-10**400`), or `cut` one | OverflowError (`cut - delta`) | ValueError (`_unit(cut)`, `abs(delta) < 1` first) |
| `sequential.sprt_decide` | `p0` under 5.6e-309 (`p1 / p0` is inf, `0 * inf` at k = 0 is NaN) | 0 failures in 100 runs: "continue" (accept_go at p0 = 1e-300): **wrong decision** | `log(p1) - log(p0)` only when the ratio is not finite; the ordinary path is the old expression |
| `sensitivity.first_order` | a constant y of 47 members (the mean of 47 copies of 0.1 is not 0.1) | S1 = 0.29 for every parameter (documented "constant y gives zeros"; n = 47, 211 and the values 0.1, 0.3, 1/3, 7.7, 1e-5, 123456.789, -0.1, 1e300 all failed) | exact test `y.min() == y.max()`: zeros |
| same | y of scale 1e160 or 1e-200 (squared spectrum overflows or underflows) | NaN; zeros | y scaled by a power of two first (`frexp`/`ldexp`, exact): S1 unchanged to the bit at any scale |
| same | a NaN or inf in y; a y of the wrong length; `harmonics` -3, -1, 0, True, 2.0 | zeros (reads as "no parameter matters"); IndexError or broadcast; S1 = 1.0 for noise at -3 | ValueError for each (`harmonics` is a count >= 1) |
| `sensitivity.noise_floor` | `perms` 0, -1, 2.5, True | IndexError / TypeError | ValueError |
| `sensitivity.extreme_ranks` | no member marked | `[(name, []), ..]` with a RuntimeWarning (NaN mean) | ValueError |
| `rare.subset_simulation` | `p0` inf (or True, a string); `n = 10**400`, `2**53 + 1`, a float | OverflowError / TypeError | ValueError (`p0` through `_unit`, `n` through `_count`) |
| `sampling.stratification_report` | zero members | ZeroDivisionError (`1 / n`) | ValueError |

Behaviour changes a caller could see: `first_order` and so `noise_floor` and `dominant` refuse a non-finite y (stage 1 filters with `np.isfinite(margin)` and passes the 0/1 indicator otherwise, so nothing in `cafe/pm` reaches it); `subset_simulation` takes `n` only as an int (a float `n` such as 1000.0 was accepted and rounded; nothing in `cafe/pm` calls it, only tests, all with ints); `verdict(k, n, level=1e-17)` raises for any k (it returned a dict whose `n_certify` was 3.8e17).

## Test: `tests/test_round21_f.py` (43 test functions, 183 cases; 183 pass on the fix, rc from the progress characters of two orca runs)
- D's four inputs and every sibling above, each with its before value in the docstring.
- `test_r21_m13_sweep_*`: hypothesis over the guarded domain (derandomized, no database) for all public functions of the five modules: result finite and sane (ordered intervals in [0, 1], counts in [1, MAX_COUNT], decisions in their set) or the module's `ValueError`, nothing else; numpy warnings count as failures. Edges in the strategies: 5e-324, 1e-320, 5.6e-309, 2.3e-308, 1e-300, 1e-17, 1.1e-16, 1 - 1.1e-16, 0.9999999999999999; counts 0, 1, 2, 10**6, 2**53 - 1, 2**53; `10**400`. A table `SWEPT` fails when a public function of any of the five modules has no place in it (round 20's table covered two modules).
- "No ordinary answer moved": `_old_one_sided` and `_old_certify` (the old expressions, 2,000+ decimal pairs at and above 1e-3), `_old_first_order` (the old function verbatim; 900 cases n = 16..400 bit-identical), and the round-20 digest test, unchanged, passes.
- Bound pins: `monkeypatch` of `MAX_COUNT` to 73 / 72 and 59 / 58 (`>` not `>=`); `log1p` threshold by `(0.3, 0.51) == 2` (kills a raised threshold) and `(1e-8, 0.95)` against the exact `Decimal` count (kills a lowered one). The `1e-3` boundary itself (`<` against `<=`) is an equivalent mutant: no (level, conf) at level or conf exactly 1e-3 gives different integers by the two expressions (scanned the 999 decimals of one argument against 0.001 of the other, both ways).

Before/after (orca, `PM_RUNTIME=proot`, 2 CPUs):
- Before: 7599881 tree with the new file (`pm_r21f_base`): 94 of 183 cases FAIL (89 pass) (every one of D's four, every sibling row, and the sweeps `certify`, `intervals`, `thresholds`, `sprt`, `sensitivity`, `rare`, and `dominant`). `sweep_coverage` and `sweep_sampling` pass on it: no finding there.
- After (`pm_r21f`, job `r21f_d1`, rc=0): `tests/test_round21_f.py tests/test_round20_f.py tests/test_stats.py tests/test_stats_exact.py tests/test_round19_f.py tests/test_round18_f.py`, 1232 passed.
- Job `r21f_a1`, rc=0, 1816 passed: stats files, `test_round14_survivors`, `test_round15_a`, `test_round16_a`, `test_round18_c`, `test_round18_m`, `test_round19_a`, `test_round20_m`, `test_config`, `test_budget`.
- Job `r21f_b1`, rc=0, 624 passed: `test_stage1`, `test_credibility`, `test_round20_b`, `test_perturb`, `test_perturb_env`, `test_cli`.
- `ruff check cafe/pm tests`: clean. `mypy cafe/pm` (strict): clean, 55 files (job `r21f_c2`).
- Coverage of `cafe/pm/stats`: 446 statements, 158 branches, 0 missed (100 %), measured on the seven stats test files (job `r21f_c2`, `--cov-branch`).
- `python -m cafe.pm.audit --code-only` (job `r21f_c3`): one problem, the missing `docs/mutation.json` (expected); no banned token.
- Not run: `test_report`, `test_pipeline`, `test_whatif`, `test_usv`, `test_dyn`, `test_glider`, `test_emulator`, `test_par`, `test_round17_*`: they call `n_certify()` or `dominant` only through the defaults, which are unchanged by construction (the digest test and the old-expression test); the full gate is the lead's.

## Siblings listed and left, with the reason
- `coverage(n, ..)` for n in the billions (MemoryError at 2**53; 10**7 is minutes) and `subset_simulation(n=2**53)` (MemoryError): the guard admits any count up to 2**53 and the call asks for an array of that size. Resource exhaustion, not arithmetic; I did not invent a bound. The sweep runs `coverage` to n = 40 and `subset_simulation` to 300 and states why. If the owner wants a bound, say a `COVERAGE_MAX_N`, it is a new decision (OD-13's second option does not cover it).
- `sprt_decide` with a numpy float64 subnormal p0 gives the right answer with a numpy RuntimeWarning (`p1 / p0` of numpy scalars); not converted to Python floats because that would move float32 decisions at a boundary.
- `lhs`/`marginal`: a normal prior is guarded at mean +- 6 sd but a draw can reach 8 to 9 sd (`ppf` of 1e-17); with sd above about 1.9e307 that is `inf`, at probability ~1e-16 per member. Not reachable in practice, not changed (`SUPPORT_SD` is a documented constant); noted.
- `_kappa(conf)` is infinite for conf = 0.9999999999999999 (`0.5 + conf / 2` rounds to 1): `wilson` and `agresti_coull` then return (0.0, 1.0) (the right limit), `newcombe_diff` a finite hybrid; only `n_certify` needed the check. The sweep asserts all of them finite.
- `lhs_unit`, `marginal_report`, `member_seed`, `member_rng`, `check_entry`, `to_marginals`, `marginal`: in the sweep (finite members for every entry `check_entry` passes, plus `lhs_unit` at n = 0); no finding.

## Hostile reviewer: what I tried
`n_certify`/`one_sided` at level and conf each in {5e-324, 1e-320, 5.6e-309, 2.3e-308, 1e-300, 1e-17, 1.1e-16, 3.3e-16, 1e-10, 0.05, 0.5, 0.95, 1 - 1e-10, 1 - 1.1e-16, 0.9999999999999999} all pairs (probe `probe1`, then the hypothesis sweep): the first run found 102 ZeroDivisionErrors, 68 + 491 OverflowErrors, 25 + 75 counts out of range (above 2**53 or 0) and 75 zeros; none left. Level equal to conf (n = 1); level 0.9999999999999999 with conf 5e-324 (underflow, n = 1); numpy float32 and float64 for level and conf, with warnings turned into errors; a bool, a string and None (the guard); `MAX_COUNT` patched to the count itself and one below (inclusive bound); (1e-16, 0.5) (6.93e15, just under 2**53, answered exactly) and (5e-17, 0.95) (above, refused); `verdict(5, 10, level=1e-17)` (refused too: it needs `n_certify` for its dict). `sprt_decide` p0 in {5e-324, 1e-320, 1e-310, 5.6e-309, 1e-308, 1e-300} with k = 0 and 1 at n = 1 and 100. `first_order` y constant for n = 16..211 and nine values, y scaled by 2**-900 to 2**900, y = 1.8e308 beside 5e-324 (hypothesis), a y that differs by one ulp (not treated as constant: its S1 is found, test), x with a NaN (not guarded: stage 1 gives uniforms), 2 * harmonics at n and one below.

## Decisions for DECISIONS (after row 1036; batch G writes them)
1. "The certification counts are checked after the arithmetic. `n_certify` and `n_certify_one_sided` raise a ValueError ('is not a finite count at most 9007199254740992 (2**53)') when the count made is infinite, NaN or above `MAX_COUNT` (`n_certify(5e-324)` was an OverflowError, `n_certify_one_sided(1e-17)` a ZeroDivisionError, `verdict(0, 10, level=1e-17)` returned 3.8e17). OD-13's default; `_level` keeps its range (amends 1027)." Not an owner decision.
2. "`n_certify_one_sided` uses `log1p` when its level or confidence is below 1e-3 (`log(1 - x)` is 0 under 1.1e-16: the count of 0 for `(0.05, 1e-20)`, and off by a part in 1e8 at x = 1e-8: 299573225 for 299573226) and the old expression otherwise (`log1p` everywhere moves 5 of 998,001 decimal pairs, e.g. (0.3, 0.51) 2 to 3); the count is at least 1." Owner decision only if the owner prefers `log1p` everywhere (moves ordinary pairs at exact decimal boundaries; the defaults 59 and the 0.01/0.99 pair 459 do not move). Default: as built.
3. "The sweep of the statistics widens to all five modules of `cafe/pm/stats` (35 public functions; `tests/test_round21_f.py::SWEPT` fails for a function without a place) and asserts, over the guarded domain with the edges, a finite sane value or the module's ValueError. It found: [the table above]. Left (resource, not arithmetic): `coverage` and `subset_simulation` at counts in the billions." Not an owner decision, except the open question of a bound for those two (default: none).
4. "`set_thresholds` refuses two cut-offs that round to one (`go - nogo` of 1e-12 or less)." Not an owner decision.
5. "`first_order` refuses a non-finite y or one of the wrong length and a `harmonics` that is not a count of at least 1; a constant y gives zeros at any n; y is scaled by a power of two (bits unchanged)." Not an owner decision.

## Document sentences that must change (batch G)
- `DECISIONS.md` row 1027 (the text "sweep of all 19 public functions" and `tests/test_round20_f.py`'s table `TAKES`): amend in place with "and, in round 21, all five modules (decision <new>)"; row 868 list of refusals needs no change.
- `docs/RUNBOOK.md`: I found no row that names `n_certify` limits or constant-y sensitivity (grep of `n_certify_one_sided`, "constant y", `MAX_COUNT` in `docs/*.md`: none outside DECISIONS). No change.
- The docstring in `sensitivity.first_order` ("Constant y gives zeros") is now true; it was false for n = 47.

## Pins moved
None. `tests/test_round20_f.py` (digest and all) and every other test file I ran pass unchanged (the pins listed in "After" above).

## Hunks for other batches
None. Batch E's `acceptance._damage` (D-6) is not touched; it needs only `credibility.counts_rule()` from batch B, which is independent of this batch's `_no_count` message (the two sentences are different: one is about arguments, one about a result).

## q23 against q22
No verdict, count or interval moves (the batch touches no code path of a demo run except `intervals.n_certify()` defaults (73, 59 unchanged), `sensitivity.first_order` for y that is not constant (bit-identical, tested on 900 cases) and for a constant margin (a vehicle or link whose margin is the same number for every member now has S1 of zero instead of a residue: if q22 has such an entry, its `sensitivity.S1` and the text "largest S1 .." in `nothing_above_floor` change; I did not run q22/q23 and did not search `summary.json` of q22 for a constant margin, so this is the one place q23 could differ from q22 and it would be a correction, not a regression).

## Problems met, not verified
- Mutation testing (`make mutation`, hours) not run. By reading: the `<` against `<=` at `1e-3` in `n_certify_one_sided` is an equivalent mutant (above); `abs(delta) < 1` against `<= 1` is equivalent (delta of 1 is refused by `0 < cut - delta` anyway); every other new branch has a test that fails if the operator or bound moves by one.
- The sweep is hypothesis with `derandomize=True`, 40 to 400 examples per function: it found every failure on 7599881 (above) but is not exhaustive; a failure only reachable by an input hypothesis did not draw is possible.
- Not run: the full suite, the gate, a demo (brief).

## Leftovers
- Orca: directories `~/cafe-worker/cafe/pm_r21f`, `pm_r21f2`, `pm_r21f_base`; logs `~/cafe-worker/logs/r21f_{a1,b1,c1,c2,c3,d1}.log` (all with an `rc=` line; no job running). The exploration probes and the lint script were removed from `pmdata` (kept in the laptop scratch).
- Laptop: worktrees `/Users/aaroh/Downloads/everything/cafe-r21f` (the branch) and `/Users/aaroh/Downloads/everything/cafe-r21f-base` (detached at 7599881, removed at the end); scratch `/private/tmp/claude-501/-Users-aaroh-Downloads-everything-cafe-main/e5175414-543a-42ed-83ef-98e3ca2ddc48/scratchpad/r21f`.
