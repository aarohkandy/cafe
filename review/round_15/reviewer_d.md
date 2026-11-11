# Round 15, reviewer D

Scope: `cafe/pm/whatif.py`, `cafe/pm/stats/{sampling,intervals,sensitivity,rare,sequential}.py`, `cafe/reach.py`, `cafe/pm/physics/rigid.py`, `cafe/pm/env/protocol.py`,
`cafe/pm/dtmb5415.py`, `cafe/pm/shares.py`, read line by line at `01a39c0` (code of `db2debd`), with the hostile inputs run on orca (`PM_HOST=cafe-orca PM_RUNTIME=proot
PMX=pm_rev15_d PM_CPUS=2`, from a detached worktree; scripts `rev_d1.py` to `rev_d11.py`, all removed at the end) and 36 mutants of D-lane lines run against the tests that name them (one, the `shares` tie-break, is an equivalent mutant: `sorted` is stable).

What held (so it is not re-read): Wilson, Agresti-Coull, Newcombe method 10, rule of three, `n_certify` (73 / 59) and the `verdict` / `interval_region` / `decided_region`
consistency were re-derived; intervals at k = 0, k = n and n = 1 are right and `k > n`, `n = 0` are refused (`interval`). EASI (factor 2 for the mirrored harmonics, the
`2M/N` correction) matches Plischke 2010 / 2012; the permutation floor measures 0.277 / 0.318 (n = 32, d = 4 / 8), 0.213 (n = 64, d = 8) and 0.60 at n = 16, as PHYSICS 13.4 says,
and `dominant` on an unrelated 0/1 indicator (n = 32, k = 8, d = 6) named a parameter in 5 of 200 trials (0.025). Subset simulation is unbiased on a 3.5 sigma tail (mean 2.336e-4
against 2.326e-4 over 200 seeds; its reported c.o.v. 0.33 against an empirical 0.45 is the known low bias of PHYSICS 13.5) and never gave a NaN c.o.v. over 2,520 runs. LHS is
exactly stratified with and without antithetic pairs; every degenerate prior (sd 0, lo >= hi, NaN, truncnorm with sd 0) is refused by `check_entry` or, called directly on `marginal`,
documented as unchecked. `implicit_midpoint` conserves |Iw| and the energy to 1e-15 over 1000 steps. The DTMB rows recomputed from the stored runs match RUNBOOK 245 (U_val / D 0.47,
0.27, 0.63, 0.30). `whatif.apply` / `answer` refuse NaN, infinite, outside-window, outside-box, unknown-vehicle, all-vehicles-dropped and conflicting ship moves with `Invalid`.

### D-1. An EMULATED verdict is read off the point estimate alone, the Stage-1 verdict off the interval; the flip search mixes them
severity: major
lane: statistics
where: cafe/pm/emulator.py:260 (`verdict_from_p(res["p_fail"]["value"])`); cafe/pm/stats/intervals.py:105-107; cafe/pm/whatif.py:681-682 (`emulate`), 734-739 and 764-765 (`flip_search`), 842-844 (`answer`); cafe/pm/stats/intervals.py:117 for the other side
reproduction: `intervals.verdict_from_p(p)` is GO for every p <= 0.10 whatever the emulator's own 90 % band `lo`..`hi` (which `emulate` returns beside it and the CLI prints as
`(lo to hi)`); the baseline it is compared with, and every Stage-1 candidate (`measure`, `_stage1`), is `intervals.verdict`, which is GO only when also `1 - hi90 >= 0.75`. The two
disagree on the same P(fail): 1 failure in 10 members is p = 0.100, `verdict_from_p` GO, `verdict(1, 10)` MARGINAL (hi90 0.348). For the emulator the gap is the band: a
prediction of 0.09 with a band of 0.00 to 0.40 is printed GO. `flip_search` then takes `min(hit, key=cost)` over about 18 candidates each judged on its own point estimate (a
winner's-curse selection with no multiplicity statement) and reports it as "the smallest change that makes it GO".
why it matters: BRIEF 2.5 / 2.9 make "the smallest change that flips the verdict" a deliverable; its GO is a weaker statement than the GO the baseline had to earn, and the word is the same.

### D-2. `python -m cafe.pm.dtmb5415 report` prints `|E|<=U_val  yes` for three rows whose finest grid has not converged
severity: major
lane: honesty
where: cafe/pm/dtmb5415.py:701-703 (`print(vv.format_table(list(tabulate(root).values())))`), 592-610; DECISIONS 345 and 402 (an unconverged finest grid is "not judged")
reproduction: on orca, `PM_HOST=cafe-orca PM_RUNTIME=proot PMX=pm_rev15_d bin/pmx.sh python -m cafe.pm.dtmb5415 report` over the stored v4 study (or `rev_d5.py`): the fine
grid has `converged` False at Fr 0.20 (drift 0.0075, parts 0.0134), 0.28 (0.0533) and 0.41 (0.0485), yet the table's last column is `yes` for all four speeds, and
`|E|/U_val` = 0.02 at Fr 0.41. `receipts()` applies the rule (a `rc.context` row "not judged: the finest grid has not converged"); `tabulate` / the printed table does not.
Every row is also on the Fs = 3 fallback ("oscillating": eps32/eps21 = -0.64, -0.32, -0.58, -0.98 from the stored counts and C_T), which the row label says but the `yes` hides.
why it matters: the one command the DTMB module offers for reading the study prints a validation verdict the project's own rule withholds, on a study STATUS says does not validate.

### D-3. A what-if whose changes cancel (or are zero) answers with a header and nothing else, exit 0
severity: minor
lane: robustness
where: cafe/pm/__main__.py:303-305 and 336-349; cafe/pm/whatif.py:810-815, 849
reproduction: `--shift 6h --shift=-6h`, `--move "1deg W" --move "1deg E"`, or `--shift 0h` make `ops` all zero (the CLI sums repeated options, `sum(...)`); the only guard is `if not
(a.shift or a.move or a.drop)`. `whatif.answer(m, dict(shift_h=0, dlon=0, dlat=0, drop=[]), ...)` returns `vehicles={}` (checked, `rev_d2.py`), and the CLI prints `whatif demo: +0 h`
and returns 0: no vehicle line, no "nothing changes". `--drop usv --drop usv` prints `dropped usv, usv` (the list is not de-duplicated, whatif.py:807, 849).
why it matters: a lab user who mistyped a sign gets a clean exit and an empty answer that reads as "no vehicle is affected".

### D-4. A move's size is unbounded: dlon wraps modulo 360, so 355 deg east is accepted as 5 deg west and 1e300 deg as 10 deg west
severity: minor
lane: robustness
where: cafe/pm/whatif.py:91-92 (`_wrap`), 145, 151, 154, 156; cafe/pm/whatif.py:790-794 (`parse_move`, any number of digits)
reproduction: `apply(demo, {"glider_eq": {"dlon": 1e300}})` is accepted and puts the glider at lon -180.0 (the box is 165 E to 165 W); `dlon = 355.0` puts it at -175.0; `dlon = 360.0`
leaves it where it is and is a "change" (not `is_base`, so it is run). A deploy shift of the same size is `Invalid` ("a date beyond the calendar"). `describe` / the CLI header print
the typed size ("move 1e+300 deg east"), the run simulates something else.
why it matters: the answer is labelled with a move the simulation did not make; a typo of a thousand degrees is accepted about one time in twelve (the box is 30 of 360 degrees wide).

### D-5. `duty` is checked only to be above 0; the documented range is at most 1
severity: minor
lane: robustness
where: cafe/pm/whatif.py:173-175 (`_numbers`), 160-166, 22-23 (the docstring "duty (<= 1: ...)")
reproduction: `apply(demo, {"glider_eq": {"duty": 10}})` gives `dive_depth_m` 9500 (the hull collapses at 364 m, P-R14V4); `{"uas": {"duty": 1000}}` gives sorties every 0.001 d; `{"glider_eq": {"duty": 1e-300}}`
gives 9.5e-298 m. None is `Invalid`. Only `design` and `candidates` build duties, both within (0, 1], and the CLI builds none, so it needs a direct caller.
why it matters: the guard `_numbers` calls "the one place every caller goes through" lets through physically impossible missions.

### D-6. UAS launch shifts are quantised to a minute, and the refusal for a tiny or near-day shift says "a whole number of days"
severity: minor
lane: documentation
where: cafe/pm/whatif.py:107-109 (`_whole_days`), 133-136, 817-823
reproduction: `apply(demo, {"uas": {"shift_h": 0.001}})` -> `Invalid: uas: launching +0.001 h later is a whole number of days`; `24.001` and `23.999` the same. `0.01` h (36 s) is accepted and
moves the launch by 1 minute (`round(h * 60)` on an `HH:MM` string). `answer` files `23.999` h under `unchanged` ("keeps the same launch time of day").
why it matters: 3.6 seconds is not a day; the real reason (launch times are `HH:MM`) is nowhere said in the message, RUNBOOK 174 or PHYSICS 13.6, and a `design` draw within 30 s of 0 is silently dropped from the training variants (`_fits_all` falls to the all-zero change, `is_base`), so the plan's variant count can fall one short.

### D-7. A round-trip reach map labels a cell whose RETURN is blocked by the current "beyond endurance or time"
severity: minor
lane: physics
where: cafe/reach.py:107-110
reproduction: `rev_d11.py`: V = 1 m/s, a 1.5 m/s northward current north of the launch, `round_trip=True`, 6 h: of the northern cells 178 read "beyond endurance or time" against 54 for the one-way map (the same battery, unlimited here); the 124 extra cells are
reachable outbound and impossible to return from because the current exceeds V, which is the case the label "currents/winds too strong or blocked" is for. `why` tests only `np.isinf(t)` (the outbound time), not the return leg.
why it matters: the map tells the user to add endurance for a cell where no endurance helps.

### D-8. `implicit_midpoint` does not converge for `dt |w| < 1` as its docstring says; it fails for ill-conditioned inertia at `dt |w| = 0.3`
severity: minor
lane: numerics
where: cafe/pm/physics/rigid.py:22-30
reproduction: `rev_d11.py`: 4,000 random diagonal inertias with ratios up to 1e3 and w scaled so that dt |w| = 0.3 (dt 0.1): 1,817 end in `RuntimeError: implicit midpoint did not converge: dt |w| is too large`; the first is
I = diag(3.734, 0.013, 1.545), w = (-2.27, -1.69, -0.98). The fixed-point contraction constant is about dt/2 times the Jacobian of `omega_dot`, which carries the inertia ratios ((I2 - I3)/I1), not just |w|.
why it matters: it is the reference that grades `cafe.dyn`; a slender hull (Ixx about 1/50 of Iyy) cannot be graded at the step the docstring promises, and the error blames the wrong quantity.

### D-9. A zero time budget returns a map in which every cell is reachable in 0 h
severity: minor
lane: robustness
where: cafe/reach.py:88-92, 102-108
reproduction: `rev_d6.py`: `reach(veh, env, 10, -95, hours=0.0, n=9)` gives `radius_km` 0, all 81 cells at 0.0 h and all `lat` / `lon` equal (`xs = linspace(-0, 0)`, `h = 0`, so every edge costs 0 s). `T = min(hours, endur)` reaches 0 the same way for `battery_wh = 0`;
`/api/reach` refuses `hours <= 0` but not an empty battery.
why it matters: a design with no energy is shown as able to reach everywhere at once.

### D-10. A reach search is cut at 400 km but the loaded weather box is 4 degrees, and beyond the box the edge value is held without a word
severity: minor
lane: data
where: cafe/reach.py:90; cafe/app.py:355-360; cafe/env.py:109-111 and 270-271
reproduction: `Env(..., (lat - 3.8, lat + 3.8), (lon - 3.8, lon + 3.8), pad_deg=0.2)` holds +-4.0 degrees; the "never extrapolate weather" check (env.py:109) covers that rectangle only, while `reach` sets R = min((V + 2.5) T 3600, 400 km) (389 km for V = 2 m/s over 24 h) and `Env.at` clips points outside the box to the nearest edge. East-west half-width of the box is 4.0 x 111.3 x cos(lat) km: 315 km at 45 N, 223 km at 60 N. A UAV at 20 m/s for 6 h reaches 432 km.
why it matters: cells past the box edge are filled with held edge fields (wind, current, land) and drawn as a result, with no warning in `out`.

### D-11. `dtmb5415.tabulate`, `row_notes` and `receipts` die with a raw KeyError / TypeError on a damaged speed entry, although `read_run` promises a damaged file is "a run that is not there"
severity: minor
lane: robustness
where: cafe/pm/dtmb5415.py:551-559 (`read_run` checks `speeds` is a dict only), 600-609, 624, 656
reproduction: `rev_d10.py` (a run_<grid>.json of the right recipe): a speed entry that is `5` -> `TypeError: 'int' object is not subscriptable`; missing `ct` -> `KeyError: 'ct'`; missing `cells` -> `KeyError`; `ct` null or "x" -> `TypeError`; `ct_std` null -> `TypeError`; `cells` 0 -> `ValueError`; `drift` "x" or `y_plus` "hi" -> `ValueError` from `receipts()`. (`converged` "yes" is read as True by `not_converged_reasons`.)
why it matters: round 9 L0's rule (a damaged run file is no run) holds for the JSON layer only; a hand-edited or half-converted file ends `make receipts` and the DTMB report in a traceback.

### D-12. Domain edges of the small statistics functions: EASI at n = 4 crashes and at n = 5 returns S1 = 1 for noise; `shares.main` tracebacks on a bad K
severity: minor
lane: robustness
where: cafe/pm/stats/sensitivity.py:15-18, 28-35; cafe/pm/shares.py:64-70; cafe/pm/stats/intervals.py:54-60, 63-70, 94-102
reproduction: `rev_d1.py`: `first_order(random(4, 2), random(4))` -> `ZeroDivisionError` (M = max(2, n // 16) = 2, lam = 2M/n = 1); n = 5 -> `[1.0, 1.0]` for independent random x, y (two harmonics are all four non-zero bins); `noise_floor` n = 4 -> `ZeroDivisionError`. `wilson(5, 3)` -> `math domain error`, `wilson(0, 0)` / `newcombe_diff(.., 0, ..)` -> `ZeroDivisionError`, `n_certify(0.0)` -> `ZeroDivisionError`, `n_certify_one_sided(conf = 1.0)` -> `ValueError: math domain error`.
`shares.main(["0", out])` -> `ValueError: 0 shares for 55 test files`, `["²", out]` -> `ValueError: invalid literal for int()` (the `isdigit` test passes it), a truncated junit file -> `ParseError`, all uncaught, where the module's own convention is the usage text and exit 2.
Stage 1 keeps `SENS_MIN_N = 16` and `orca_gate` bounds K to 1..16, so none is reachable from the pipeline; DECISIONS 597 states the intervals ones are "the arithmetic".
why it matters: `first_order` is a public function that fails at n = 4 and silently saturates at n = 5, and the docstring promises neither.

### D-13. Tests that stay green when D-lane statistics are broken
severity: minor
lane: documentation
where: tests/test_stats.py:391-400 and 409-440; tests/test_round14_survivors.py; cafe/pm/stats/rare.py:42; cafe/pm/stats/sensitivity.py:29; cafe/pm/stats/sampling.py:91, 51
reproduction: each mutant below applied to the file in a scratch copy on orca and the named tests run (`-x`), restored after (`rev_d9.py`): SURVIVED `rare._gamma` without the `(1 - k nc / n)` weight (tests/test_stats.py; the only c.o.v. checks are `0.05 < cov < 1.0` and `gamma > 0`, so M-26's "2.5 x too low" is not pinned); SURVIVED EASI `lam = 2 * m / n` -> `m / n` (the correction is tested only by `raw[1] >= s[1]` at n = 200, where lam is 0.04); SURVIVED `_check_factor` `abs(e[f]) >= 1` -> `> 1` (a fraction of exactly 1 is accepted: tests/test_stats.py, test_round14_survivors.py, test_config.py); SURVIVED `SUPPORT_SD = 6.0` -> `3.0` (the same three files; `hs_scale` normal(1, 0.2) is refused at 6 and would be at 3 only for sd > 0.33). KILLED: EASI factor 2 and odd/even ordering, Newcombe L, `n_certify` + 1, `decided_region` hi, Agresti-Coull n~, the antithetic stratum pairing.
why it matters: the corrections that make the noise floor and the c.o.v. honest have no test that fails when they are removed.

### D-14. Tests that stay green when `reach.py` is broken in ways its REVIEW rows claim fixed
severity: minor
lane: documentation
where: tests/test_reach.py; cafe/reach.py:47, 98-100, 34, 111; REVIEW.md rows 7 (glider current averaged over the dive band) and 8
reproduction: `rev_d9.py`, all SURVIVED `tests/test_reach.py`: `np.linspace(top, bottom, 6)` -> `np.linspace(top, top, 6)` (the glider band average, REVIEW 7, is untested); `battery_wh * (1 - reserve)` -> `battery_wh` (the reserve); `hold = ... < 0.8 * V` -> `< 1.0 * V`; the diagonal corner rule `land[i + di, j] and land[i, j + dj]` -> `or` (only the blocking direction is tested, not that a one-corner diagonal is allowed). KILLED: the knight-step land rule, the back-leg sign.
why it matters: the receipts exercise a USV in a uniform current (`receipts.py:548`); nothing runs the glider branch or the reserve.

### D-15. Tests that stay green when `whatif` longitude wrapping, UAS period float dust, or the analytic current profile is broken
severity: minor
lane: documentation
where: cafe/pm/whatif.py:91-92 and 185; cafe/pm/env/protocol.py:44; tests/test_whatif.py, tests/test_environment.py, tests/test_stage1.py
reproduction: `rev_d9.py`, SURVIVED `tests/test_whatif.py`: `_wrap` -> identity (the demo box straddles the antimeridian and no test moves a vehicle across 180); `math.ceil(x - 1e-9)` -> `math.ceil(x)` in `_duty_days` (DECISIONS 733's float-dust guard has no test). SURVIVED `tests/test_environment.py tests/test_stage1.py`: the `AnalyticEnv` profile `1000` -> `500` m (DECISIONS 727 states 1000 m). KILLED: the deploy-window hour, the candidate cost, `shift_track` cut, whole-day test, the noise-floor debias, the ship-moves-once rule, the beta-binomial chance figure, rigid midpoint, `first_layer`, `layer_count`, `settle` drift, the GCI spread, the U_input quadrature, the protocol log profile.
why it matters: the dateline case is the demo's own geometry.

total: 15 findings (0 critical, 2 major, 13 minor)
