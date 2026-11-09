# Round 13, reviewer C

Scope: `cafe/pm/stats/` (intervals, rare, sampling, sensitivity, sequential), `vv.py`, `physics/rigid.py`, `env/conventions.py`, `env/protocol.py`, `env/bathy.py`, `env/environment.py`, `env/ocean.py`, `env/grid.py`, `ledger.py`, `par.py`, `shares.py`, at commit `939851e` (code of `cdad21a`).

What was checked and found correct (no finding):
- Wilson, Newcombe method 10, `n_certify` (73, 25 at 10 %/90 %, 657 at 1 %/99 %), `n_certify_one_sided` (59, 22, 459, 80) against a brute-force score-equation solve and a closed form; every (k, n) the q13 summary prints (18/64, 0/64, 62/64, 55/64, 64/64 at 90 % and 95 %) reproduces to 5e-13; no (k, n) with n < 150 where `interval_region` contradicts `verdict`; Wilson mean coverage at n = 40 is 0.9510.
- EASI against closed forms (y = x0 + 2 x1 gives 0.21 and 0.80 for 0.2 and 0.8; a sine plus linear term gives 0.952, 0.033 for 0.96, 0.04); the 95 % permutation floor is 0.30 at 32 members and 6 columns, and the false-positive rate on unrelated outcomes is 4.9 % at n = 32 and 3.6 % at n = 64 (700 draws each), as documented.
- `lhs_unit`: exact strata and KS <= 1/n in 2,800 draws including antithetic columns.
- `subset_simulation` against the Gaussian tail (bias and spread consistent with Au and Beck); `_gamma` matches eq. 29-30.
- `celik_gci` reproduces Celik 2008 Table 1 column 1 (p 1.534, phi_ext 6.1685, e_a 1.50 %, e_ext 1.71 %, GCI 2.17 %), recovers p exactly (to 1e-9) for power-law data at six ratio pairs, and satisfies eq. 3 to 2e-16 in an oscillatory case.
- Implicit midpoint conserves |I w| and the energy to 1e-15 over 1,000 steps; explicit Euler's |H|^2 growth equals dt^2 |w x H|^2 to 4 digits.
- `grid.interp` equals scipy's RegularGridInterpolator to 2e-16 in 4-D; NaN-corner renormalisation, one-point axis, empty and 0-d queries behave as documented.
- `rain_rate_nodes` conserves the accumulation exactly (derived by hand).
- 92 hand-made mutants of these files were run against their own test files on orca (two sweeps of 46). 74 were killed and 18 survived their own file: 2 are killed by other files (`ledger.shared_diff` file-gone, `conventions` compass_from), 5 are equivalent (`SHARE_MIN_BYTES` `>=` / `>`, the cgroup `2**60` bound, the `grid.locate` upper clamp which the `wts > 0` filter makes redundant, the strict coverage inequality at a measure-zero point, and the KS clause of `stratification_report`, which cannot fail once the strata are exact), and 11 are the test gaps in C-12 and C-13.

### C-1. `GriddedEnv.air` returns the relative sigmas of Q2 and SWDOWN as if they were absolute uncertainties
severity: minor
lane: honesty / data
where: cafe/pm/env/environment.py:206 (`q2=tag("Q2", s["q2_frac"])`, `swdown=tag("SWDOWN", s["swdown_frac"])`); contract in cafe/pm/__init__.py:19 ("1-sigma, same units as value"); config/assumptions.yaml `env.sigma.q2_frac` (0.10, unit "-") and `swdown_frac` (0.20, unit "-")
reproduction: on orca, `GriddedEnv(ci_env.cache, env_sigmas()).air(lon, lat, t)` over 24 hours of the ci_env fixture gives `q2.value` 0.0170 kg/kg with `.uncertainty` 0.1 (588 % of the value) and `swdown.value` 0..949 W/m2 with `.uncertainty` 0.2 (a fraction, not W/m2; 20 % of 949 would be 190). `Hs` three lines later correctly multiplies (`s["hs_frac"] * hs`), `T2`, `glw`, `psfc` are absolute. `tests/test_environment.py:251` asserts only T2 and glw, so nothing pins Q2 or SWDOWN.
why it matters: the Tagged contract says same units as the value; today no output prints these two (report.py:856 shows only wind, Hs and current), but anything that reads `air()["q2"].uncertainty` gets a number wrong by a factor of 59 (humidity: 0.1 against 10 % of 0.017 = 0.0017) or 949 (shortwave: 0.2 against 20 % of 949 = 190).

### C-2. `par.py` says a queued task's maps stay alive in the parent; `Pool.submit` keeps only the pickled bytes, so dropping the array while the task is queued loses the file
severity: minor
lane: robustness / documentation
where: cafe/pm/par.py:10-11 (docstring: "a queued task's maps are alive in the parent until its result is back"), :231-236 (`Pool.submit` pickles at once and hands `self.ex.submit(_run, blob)` only the bytes), :140-146 (`_release` unlinks on the last map)
reproduction: on orca with `PM_CPUS=2` (script run through `bin/pmx.sh python r9.py`): `with par.Pool(2): a = par.adopt(np.ones(400_000)); busy = [par.submit(slow, 1) for _ in range(2)]; f = par.submit(total, a); del a; gc.collect(); f.result()` raises `FileNotFoundError: [Errno 2] No such file or directory: '/tmp/cafe-share-<pid>-<random>/0.npy'` (with `PM_CPUS=2` `workers()` is 2, `adopt` returned a `memmap`). This is the failure DECISIONS 273 fixed for a different cause (a queued task naming a file that was replaced).
why it matters: today `stage1.run` keeps `env` in its frame until the futures are collected, so no run is affected; the stated invariant is nonetheless the caller's discipline, not the module's, and the next caller that builds an environment inline in the `submit` call will fail only under load (when the task is actually queued). Fix: keep the args on the Future (`fut._args = args`) or correct the sentence.

### C-3. `celik_gci` and `vv20_row` accept inputs the procedure cannot handle, with a crash or a wrong word
severity: minor
lane: robustness
where: cafe/pm/vv.py:60 (`p = base / math.log(r21)` before any check), :130-147 (`celik_gci` does not validate r21, r32), :171-176 (`vv20_row`)
reproduction: on orca, `vv.celik_gci(1, 1.1, 1.15, 1.0, 2.0)` raises `ZeroDivisionError: float division by zero`; with `r21 = 0.9` (r32 = 2), `r32 = 1.0` (r21 = 2) or `r21 = nan` it raises `RuntimeError: fixed-point iteration for the apparent order did not converge` (a refinement ratio at or below 1 is not an order problem); `r21 = 0.0` raises `ValueError: math domain error`. `vv.vv20_row("x", 1.0, 1.2, 0.05, 0.05, float("inf"))` returns `Vv20(... u_val=inf, ratio=0.0, validated=True)`: an infinite data uncertainty reads as validated.
why it matters: the `r_ok` flag exists to report r < 1.3, but r <= 1 (two grids with the same cell count, which `refinement_ratio` returns as exactly 1.0) crashes instead of flagging; an infinite or unknown U_D should not be able to validate a row.

### C-4. Perturbation entries from a hostile or hand-edited YAML are not validated: raw exceptions, silent NaN members, a boolean sd
severity: minor
lane: robustness
where: cafe/pm/stats/sampling.py:39-47 (`load_perturbations`), :50-69 (`to_marginals`), :31-35 (`marginal`)
reproduction: on orca, `load_perturbations` / `to_marginals` / `lhs(8, ...)` on small files: an empty file raises `AttributeError: 'NoneType' object has no attribute 'items'`; `foo: 3` raises `AttributeError: 'int' object has no attribute 'keys'`; an entry with no `dist` raises `KeyError: 'dist'`; `dist: uniform` without `lo` raises `KeyError: 'lo'`; `dist: uniform, lo: 2, hi: 1` loads, samples and returns NaN for every member (`{'foo': [nan, nan, nan]}`) with no error, although the lines above it refuse a zero sd because "scipy turns 0 into NaN members"; `dist: normal, value: true` is accepted as sd 1 (`isinstance(True, int)`); `marginal({"dist": "truncnorm", "sd": 0, ...})` raises `ZeroDivisionError`. `to_marginals` also refuses `truncnorm` ("not a sampled parameter") although `marginal` and its docstring offer it.
why it matters: `config/perturbations.yaml` is meant to be edited when the lab's numbers arrive; a reversed uniform gives an ensemble of NaN members that fails far from the cause.

### C-5. `Ledger.__exit__` can fail inside `clean` and hide the stage's own exception when a ledger value has a numpy integer dict key
severity: minor
lane: robustness
where: cafe/pm/ledger.py:175 (`json.dumps(clean(self.d), ...)` in `__exit__`), :194-203 (`clean` converts values but leaves keys as they are)
reproduction: on orca, `json.dumps(ledger.clean({np.int64(3): 1.0}), allow_nan=False)` raises `TypeError: keys must be str, int, float, bool or None, not numpy.int64`. In `__exit__` that TypeError replaces the exception the stage was leaving with and no ledger.json is written (the previous one, if any, stays).
why it matters: a `L.check(..., value={member_index: x})` with a numpy key (an index from `np.flatnonzero`) turns a clear StageFailed into a TypeError with no ledger; `clean` is where the key should become `str(k)`. No current value has such a key (all dicts in stage 1's checks use string keys), so this is latent.

### C-6. `GriddedEnv.sst` states "frozen at 2023-03-01: SST_UPDATE=0" for whatever WRF data it was given
severity: minor
lane: honesty
where: cafe/pm/env/environment.py:344 (`f"{self.wrf_src} SST (frozen at 2023-03-01: SST_UPDATE=0)"`); cafe/pm/env/environment.py:84 (`12 km hourly` also fixed)
reproduction: `grep -rn SST_UPDATE cafe` finds nothing that reads the attribute from a file; the date and the flag are literal text. STATUS.md row 20 and QUESTIONS_FOR_LAB 3 name the replacement ("A coupled-SST WRF run ... point CAFE_ORCA at them"). With that run the Tagged source of every SST value would still say frozen, and `tests/test_environment.py:391` asserts the word "frozen".
why it matters: provenance text is part of the report; once the lab's coupled run is used the report would call a time-varying SST frozen. The frozen date and flag should come from the file's attributes or the sentence should say it is the demo cache's.

### C-7. bathy.py's docstring gives 8 kB for a row of the TEPEX-C cut; it is 16 kB
severity: minor
lane: documentation
where: cafe/pm/env/bathy.py:5-6 ("one box row is one HTTP byte range (about 8 kB for the 34 deg TEPEX-C box)")
reproduction: the demo box is lon 165..-165 (30 deg) plus `pad_deg` 2 each side = 34 deg; GEBCO 15 arc-second is 240 columns per degree, 34 x 240 = 8,160 columns of int16 = 16,320 bytes per row. DECISIONS 27 gives 59 MB for the cut: 59 MB / 3,360 rows (14 deg x 240) = 17.6 kB per row. The 8,160 is the count of points, not kB.
why it matters: a wrong figure in the one place that explains why the byte-range design is cheap.

### C-8. `seconds()` turns NaT into -9.22e18 and `Axis` accepts it as the first time
severity: minor
lane: robustness
where: cafe/pm/env/environment.py:33-34 (`seconds`), cafe/pm/env/grid.py:19 (strictly-increasing check only)
reproduction: `seconds(np.array(["NaT", "2023-03-01T12:00", "2023-03-01T13:00"], "datetime64[s]"))` gives `[-9.22337204e+18, 1.67767200e+09, 1.67767560e+09]` and `np.all(np.diff(t) > 0)` is True, so `Axis` takes it; `GriddedEnv.bounds[4]` would be -9.2e18, `inside` is True for every earlier time, and the first hour interpolates from the NaT slot. With NaT last, the check does reject it.
why it matters: a damaged time coordinate (a fill value at index 0) passes the loader and gives wrong edge behaviour instead of the "delete the cache and refetch" ConfigError that every other bad coordinate gets.

### C-9. `GriddedEnv._check` raises a bare `ValueError` for a NaN time, not `OutsideData`
severity: minor
lane: robustness
where: cafe/pm/env/environment.py:138 (`dt.datetime.fromtimestamp(T, ...)` in the message)
reproduction: on orca with the ci_env cache, `env.wind(lon0, lat0, 10.0, np.nan)` raises `ValueError: Invalid value NaN (not a number)`; for NaN lon or an out-of-box point it raises `OutsideData` correctly. `whatif.py:348,355,595,620` and `__main__.py:173` catch `OutsideData` by name.
why it matters: a NaN sortie time (for example from a NaN perturbation, C-4) escapes the handlers that turn out-of-data into a clean exit 2 and prints a traceback with a message that names nothing.

### C-10. `subset_simulation` uses the nominal `p0` in the c.o.v. but `nc / n` for the probability, and fails with ZeroDivisionError for small n (the function is not called by the pipeline)
severity: minor
lane: statistics
where: cafe/pm/stats/rare.py:53-55 (`nc = round(n * p0)`, `length = n // nc`, `n = nc * length`), :72 (`d2 += (1 - p0) / (p0 * n) * (1 + gam)`), :73 (`p *= nc / n`)
reproduction: `n = 1000, p0 = 0.3`: `nc = 300`, `length = 3`, `n = 900`, the realised level probability is 1/3 but the c.o.v. term uses 0.3: (1 - 0.3)/(0.3 x 900) = 0.002593 against (2/3)/((1/3) x 900) = 0.002222, 17 % too large per level. Over 60 seeds at a 3-sigma target the reported c.o.v. was 0.169 against an empirical 0.250 at p0 = 0.3 (0.228 against 0.265 at the default p0 = 0.1). `subset_simulation(f, d, t, n=4)` gives `nc = 0` and raises `ZeroDivisionError` at `n // nc`.
why it matters: the function is documented and receipted-by-test but not used (PHYSICS 13.5); if it is ever used, use `nc / n` consistently and refuse n * p0 < 1.

### C-11. `AnalyticEnv` and the protocol docstring mention things that do not exist
severity: minor
lane: documentation
where: cafe/pm/env/protocol.py:49 ("default 1 above `ml_depth`"; the constructor has no `ml_depth`, `_profile` falls linearly from the surface to 0 at 1000 m with no mixed layer); :13 (`air` lists `ustar` and `L`; `GriddedEnv.air` without a sub-grid returns `ustar_wrf` and `pblh`, and has them under their short names only when a `SurfaceLayer` is attached)
reproduction: read the constructor at protocol.py:52-60 and `GriddedEnv.air` at environment.py:200-211: without a sub-grid the keys are `T2, q2, psfc, swdown, glw, rain, ustar_wrf, pblh` (read, not run).
why it matters: the Protocol is what a new vehicle model is written against.

### C-12. Tests that pass on a changed `vv.py`: eq. 6, `r_ok`, the validated boundary, `phi_ext32`, 2-D `grid_size`
severity: minor
lane: tests
where: tests/test_vv.py:39 (eext21 at abs=1e-3), :40 (r_ok only True or all False), :150-153 (boundary), nothing on `phi_ext32`, :116-117 (`grid_size` only with dim 3); cafe/pm/vv.py:143, :147, :176, :140, :46
reproduction: each of these edits leaves `pytest tests/test_vv.py` green (run on orca, rc 0): (a) line 143 `abs((ext21 - phi1) / ext21)` -> `/ phi1` (Table 1 column 1 gives 1.710 % against 1.740 %, inside the 1e-3 tolerance); (b) line 147 `r21 >= R_MIN and r32 >= R_MIN` -> `or` (no case has exactly one ratio below 1.3); (c) line 176 `ratio <= 1.0` -> `< 1.0` (no row with |E| = U_val); (d) line 140 `(r32 ** p * phi2 - phi3)` -> `(r32 ** p * phi3 - phi2)` (no test reads `phi_ext32`); (e) line 46 `** (1.0 / dim)` -> `** (1.0 / 3)` (no 2-D call).
why it matters: eq. 6 and the ratio check are two of the numbers the credibility report gates on; a test with eps large enough to separate the denominators, a (1.5, 1.2) ratio pair and a |E| = U_val row would fail each.

### C-13. Tests that pass on a changed `environment.py` / `par.py`: rain over the end of the data, restart-spectrum distance, `lenient` restore, 3-D hour gap, fractional CPU quota
severity: minor
lane: tests
where: cafe/pm/env/environment.py:158 (`t1 = np.minimum(t + 3600.0, self.tw.x[-1])`), :304 (`* np.cos(np.radians(float(lat)))`), :126 (`self.strict = was`), :247 (`<= 3600.0 + 1e-6`); cafe/pm/env/ocean.py:75 (`wrap_about(lon, centre)`); cafe/pm/par.py:64 (`max(1, ...)`); tests/test_environment.py:499-515, :358-364, tests/test_par.py:328-333
reproduction: each edit leaves its test file green on orca: (a) drop the `np.minimum` at :158: the test of the hour past the data end (`rain_hourly(.., 3600*4) == 0.0`) lands on the last node, where both versions give 0; an hour that begins inside the data and runs past it (half an hour of rain) would differ by a factor of 2. (b) drop the cosine at :304: the ci_env box is within 2 deg of the equator, cos = 0.9994. (c) `self.strict = was` -> `= True`: no test enters `lenient()` on an environment built with `strict=False`, which would be left strict. (d) `<= 3600.0 + 1e-6` -> `<= 7200.0 + 1e-6`: no test has 3-D hours two hours apart. (e) `Ocean._lon` -> `cv.wrap360(lon)`: no test opens a store whose longitude axis is continuous across 0 E (`ocean.py:3-4`, `bathy.py:50` and `environment.py:117` document it). (f) `par._cgroup_cpus` without `max(1, ...)`: the table has 150000/100000 (1) but no quota below one CPU (`--cpus 0.5`), where the mutant returns 0 workers.
why it matters: each is a documented behaviour with no test that notices it breaking.

total: 13 findings (0 critical, 0 major, 13 minor)
