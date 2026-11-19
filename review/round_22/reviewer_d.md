# Round 22, reviewer D: robustness and operations of round 21's changes

Tree: `65e187e` (code of `c58fba0`). Reproductions ran on orca (`pm_rev22_d`, 2 CPUs, proot) from the detached worktree `../cafe-rev22-d`, probes in its `probe/`. All findings are minor. Three give wrong data to act on (D-1, D-2, D-3), each only on a hand-edited or degenerate input.

### D-1. radios.yaml, modems.yaml and config/assumptions.yaml numbers are never checked: `.nan`, `.inf` and a 400-digit integer pass, and `hangar --platform radios` says "provenance OK"
severity: minor
lane: robustness (class "non-finite or oversized number at a boundary": does it end at JSON? it ends at the mission file and the vehicle platforms)
where: cafe/pm/config.py:537 (`_finite` is called on the mission only), cafe/pm/config.py:145 (`_yaml`, no `_finite`), cafe/pm/physics/comms.py:77 and 286-301 (`_yaml`, `_radio`, `rf_margin`), cafe/pm/config.py:687 (`env_sigmas`), cafe/pm/__main__.py:273-295 (`_hangar`)
reproduction: probes `probe/p2.py`, `p3.py`, `p9.py` (orca). A copy of `platforms/radios.yaml` with one numeric leaf set to `.nan`, `.inf`, `-.inf` or 400 nines: `python -m cafe.pm hangar --platform <copy>` prints `(radio table): provenance OK, 20 of 25 items assumed`, rc 0, for all 12 variants (the four vehicle platform files refuse every one of the same edits, rc 1). `comms.rf_margin([3000, 8000], 10, 2, 0, "rfd900x")` with the edited radios.yaml: `rx_sens_dbm` nan gives `[nan nan]`, `rx_sens_dbm` inf gives `[-inf -inf]`, `tx_dbm` inf gives `[inf inf]` (every sample passes: GO), `center_mhz` inf gives nan, any 400-digit value gives an uncaught `OverflowError: int too large to convert to float` mid-stage. `config.env_sigmas()` with `env.sigma.t2_k` set to `.nan`, `.inf` or 400 nines returns it unchanged. `modems.yaml` is read by the same `_yaml`.
why it matters: round 21 named `_finite` as the YAML boundary but it covers one file kind. A typo in a lab-edited link table gives either a traceback deep in stage 1 or an RF link that always passes or always fails, and the provenance check the lab is told to run says OK.
wrong data: yes: the RF link verdict (GO from `tx_dbm: .inf`; NO-GO from NaN) when radios.yaml is hand-edited; nothing in the report says the input was non-finite.

### D-2. `app.js` shows a drag area of 0.0000 m2 for a direction whose force is NaN, since `hangar._write_result` turned the NaN into null
severity: minor
lane: robustness / honesty (sibling of M-12)
where: cafe/static/app.js:464 (`fmt(-s * x.force[ax] / q, 4)`), cafe/hangar.py:396 (`_write_result`: every NaN becomes null, arrays included)
reproduction: `probe/p5.py`: `_write_result` of a result holding `force: [-1, NaN, 0]` writes `[-1.0, null, 0]`. In Node, `fmt(-1 * [null,0,0][0] / 72, 4)` is `0.0000` where the same with NaN was the dash (`—`): JS coerces null to 0 in the product, and `fmt` only tests for `null` and `NaN` of the final value. The row is printed with " no index" beside it, but the drag area reads as a finite zero.
why it matters: before the M-12 change a diverged direction read as a dash; now it reads as a drag area of zero.
wrong data: yes: the Hangar's "drag area <dir>" fact shows 0.0000 m2 for a direction with no force.

### D-3. `vehicle.hull_lift` gives a grid index of 0.0 (converged) when no coarse force exists, and only the last angle is looked at
severity: minor
lane: robustness / statistics (sibling of M-5: a missing index is not a converged grid)
where: cafe/vehicle.py:395-398 (`gcis` appended only `if a == alphas[-1] and all("force_coarse" ...)`; `vv.worst_gci(gcis)` with default 0.0), cafe/vehicle.py:334 (`lift_gci`), cafe/mission.py:74 (`drag_sigma` takes it as a trusted index)
reproduction: `probe/p6.py`: `hull_lift` of an incidence result with and without `force_coarse` in its directions: with it `gci` 0.05; without it `gci` 0.0. `drag_sigma` then reads `lift_gci` 0.0 as the best possible grid and gives `hypot(0.10, worst)` instead of the estimate's 0.30. The docstring of `drag_sigma` says a missing `lift_gci` is no study; a missing coarse force is the same fact in another place. Angles other than the last never enter.
why it matters: a hand-made, older or truncated incidence result narrows the drag spread to 0.10 as if it were converged.
wrong data: yes: the sampled drag spread of a vehicle (and with it the verdict) for a result with no coarse forces.

### D-4. A NaN item of a stored force or moment now reads back as null and `vehicle.build` fails with an unnamed TypeError
severity: minor
lane: robustness
where: cafe/vehicle.py:286-289 (`np.asarray(r["force"])` of a list holding null), cafe/hangar.py:396, callers cafe/app.py:358, cafe/app.py:548, cafe/mission.py:666, cafe/emulator.py:330
reproduction: `probe/p5.py`: `vehicle.build("uav", box, spec, {"cfd": {... "+x": {"force": [-1.0, None, 0.0], ...}}})` raises `TypeError: unsupported operand type(s) for *: 'float' and 'NoneType'`; with NaN in place of None it builds (a silent NaN drag, the old behaviour). The message names neither the design nor the field. `/api/reach`, the live start and a mission job end in a 500 or a worker traceback.
why it matters: the change is right in refusing a NaN force but the refusal is an accident of arithmetic.
wrong data: no.

### D-5. `/api/live/{sid}/step` answers 500 for an integer of 400 digits in a target's lat, lon, z or speed
severity: minor
lane: robustness (class: oversized number at a boundary; DECISIONS 1049's list names `live_step` with 10**400)
where: cafe/live.py:72-73 (`except (KeyError, TypeError, ValueError)` does not catch OverflowError), cafe/app.py:558-568 (`seconds` is guarded, `targets` is not)
reproduction: `probe/p4.py`: `app.live_step("s", {"seconds": 1, "targets": {"a": {"lat": 10**400, "lon": 1}}})` raises `OverflowError: int too large to convert to float` (not an `HTTPException`); the same for lon, z, speed, and `-10**400`. `seconds: 10**400` gives the 400. `cfd._finite_positive("speed", 10**400)` is also an OverflowError (not reachable from a file through `load_json`).
why it matters: the sweep's claim "a 400, never a 500" does not hold for the live step. Also `{"lat": true}` is accepted as 1.0 there.
wrong data: no.

### D-6. The two grep tests of `tests/test_round21_e.py` have gaps
severity: minor
lane: tests
where: tests/test_round21_e.py:65-93 (`raw_json_calls`, `isfinite_uses`); `_modules()` walks `cafe/` only
reproduction: reading, plus `probe/p9.py`: `import math as m; m.isfinite(x)` is not matched (the rule needs the Name `math`); `getattr(json, "loads")`, `__import__("json").loads(...)` and `json.JSONDecoder().decode` are not matched; `np.isfinite` of a scalar (a TypeError for a 400-digit int) is outside the rule; `bin/`, `bench/`, `lab/` are outside the walk.
why it matters: the closure of the class is held by the test; a new reader spelled any of these slips past it.
wrong data: no.

### D-7. `check_fleet` accepts `minutes: true`
severity: minor
lane: robustness
where: cafe/app.py:420 (`isinstance(l.get("minutes"), (int, float))` admits a bool; `_point` and `max_hours` refuse one)
reproduction: reading: `0 < True <= 1440`, so a hold or follow leg of `true` is one minute.
why it matters: a bool is no number is the rule everywhere else in the sweep.
wrong data: no.

### D-8. Statistics edges left without a refusal
severity: minor
lane: statistics
where: cafe/pm/stats/sensitivity.py:83-93 (`extreme_ranks`), cafe/pm/stats/rare.py:47-58 (`subset_simulation`), cafe/pm/stats/sensitivity.py:26 (`first_order`)
reproduction: `probe/p7.py`: `extreme_ranks(names, x, np.array([1]*64))` (ints, not a mask) is read as row indices and returns `[57, 57, ...]` for every parameter; a mask of the wrong length is a bare IndexError; `subset_simulation(..., target=nan)` returns `p=0.0, cov=inf` after 20 levels instead of refusing; `d=0` is a reshape ValueError and `d=True` a TypeError; `first_order` refuses a NaN `y` but takes a NaN or inf in `x` (answer `[0.985, 0, 0]`). `n_certify_one_sided(3e-16, 0.5)` and `n_certify(1e-16, 0.5)` are off by one from a 80-digit Decimal oracle (counts near 2e15, 4.5e15).
why it matters: guards without a type or result check; `stage1` passes a bool mask and finite `U`, so no run is affected.
wrong data: no.

## Looked at, nothing found
- `jsonio.load_json` (probe `p1.py`, Python 3.12): integers of 309, 400, 4300 digits are the "too large" ValueError, 5,000 and 10**6 digits the stdlib's 4300-digit ValueError (no literal printed); `1e999` reads as inf (finite_real refuses it); `-0` is 0; NaN, Infinity readable; `[` x 10**5 and 10**6, closed or not, and `{"a":` x 10**5 are "nested too deeply"; depth 900 and 1100 closed parse; NUL, empty, bytes, bytes with BOM, a `Path`, a missing file and a directory give ValueError or OSError as stated; a str with a BOM is a JSONDecodeError (as before). `finite_real`: bool, 10**400, 2**1100, numpy float32 and int64 all False.
- `vv.gci_value`, `gci_trusted`, `worst_gci` over 14 values (negative, -0.0, numpy 32 and 64, bool, text, list, None, 2**1100, 0.3 and one ulp above); `drag_sigma` with NaN first, last and alone, a missing key, 0.29, 0.3 (continuous at 0.283 to 0.3); `grid_warning`.
- `_plan_sizes`: 24 hostile plans (bool, 12.0, string, None, negative, 0, n_min above n_max, batch above n_max, n_max 65, 10**6, 10**30, list, None, dict, unknown budget, numpy int, extra keys) all refused with the stated message; missing keys are a KeyError inside `damaged_run_files`. `budget.plan` always writes `n_max <= N_MAX`, `batch <= min(BATCH, n_max)` (budget.py:411-440).
- `hycom.dead_note` and `leftover_note` with a parent holding a space, quote, double quote, `$`, newline, `;`, leading dash: the advice words round-trip through `sh` to the same paths; equal mtimes, a far-future and a negative mtime, a symlink loop and a dangling link in a `.dead.tmp` print. A backtick in the path breaks the code span of the message only.
- Vehicle platform YAML with `.nan`, `.inf`, `-.inf`, 400 nines in first, middle and last leaf (4 files x 3): all refused with a named message, rc 1.
- `hangar._write_result` (NaN, inf, numpy scalars, arrays, nested lists, big int, finite results byte-identical to `json.dumps`), `app._read` (NaN, null, big int, half file, empty, BOM) readable or default; a directory at the path is an uncaught IsADirectoryError.
- `_seed._checked` read in full: sibling paths covered.
- Statistics (`p7.py`): `first_order` constant, int, float32, length mismatch, harmonics 0, -3, 2.5, True; `noise_floor` perms; `n_certify*` against a Decimal oracle at 10 levels x 6 confidences (only the two off-by-one cases above); `sprt_decide` at 1e-300, 5e-324, 1e-310 (numpy float64 subnormal warns, known); `sprt_indifference` huge, 10**400, NaN; `set_thresholds` 1e-13 apart refuses and leaves state untouched; `subset_simulation` p0 inf, n 10**400, 2**53+1, 100.0, 0, -5; `stratification_report` zero rows.

## Not run
`write_store` with a real zarr and real kills; the 20 GB delete time; two concurrent runs; a kill in an emulator append; the TAO lock; the whole-file hull fuzz; recomputing `cfd.recipe()` and `_code_literals()`; a real what-if with a valid plan; the app over HTTP or in a browser (httpx absent; `app.js` run as one expression in Node only); a mission flown with an untrusted index; the 78 sites one by one (the 15 of `pipeline.py` and the 10 stage-function sites only through the grep test); the RUNBOOK Troubleshooting rows beyond the plan, leftover and damaged-run rows; `import` of `jsonio`, `vv`, `vehicle`, `mission`, `_seed` with yaml unimportable; `emulator._verdict_band` against a damaged table.

total: 8 findings (0 critical, 0 major, 8 minor)
