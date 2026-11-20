# Round 22, batch D hand-back (M-6, M-7, M-9)

Branch `r22-d`, cut at 7a1aaa9. Files touched: `cafe/vehicle.py`, `cafe/static/app.js`, `cafe/live.py`, `cafe/app.py`, new `tests/test_round22_d.py`, this file. No existing test edited. `cafe/hangar.py` not touched (see M-7, "Infinity"). Nothing deployed; `sync.sh` and `run.sh` not run.

## What changed and why

### M-6 (D-2 the dash, D-4 the named refusal)

`cafe/vehicle.py`: one new helper `_vec3(r, key, d)`: `np.asarray(r[key], float)`, then `shape == (3,)` and `np.isfinite(...).all()`; anything else (a null item, NaN, inf, an integer too large for a float, text, a wrong length, a scalar) is `ValueError("direction {d}: `{key}` is not three finite numbers")`. Used for `force`, `moment` and `viscous` of every direction in `build`, and for `force` and `moment` (and the two `_coarse` ones) in `hull_lift` (`frd` now takes the direction label). A numpy array or float32 items pass (np, not `finite_real` per item). Before: a null was `TypeError: unsupported operand ... 'NoneType'` and a bare NaN built a silent NaN drag.

Callers of `build`, and what a ValueError does there (read, and by the global handler):
- `cafe/app.py` `reach_map` (`hangar.load_vehicle(d)`, outside its own try): the app's `@app.exception_handler(ValueError)` turns it into a 400 with the message.
- `cafe/app.py` `live_create` (`live.create(..., load_vehicle)`): inside `except ValueError -> HTTPException(400)`.
- `cafe/mission.py` `__main__` (a mission job) and `cafe/emulator.py:330` (an emulation job): `except Exception` writes `state=failed, error="ValueError: direction ... "`; no traceback to a client, no 500.
- `cafe/hangar.py` `run` (characterization): line 351 sits in a try that says "structure NOT checked"; lines 367 to 378 sit in the outer `except Exception` that writes `errors` and status failed. So a fresh run whose CFD gave a NaN force now fails the design with the named message (it used to build a silent NaN drag). That is the intended change; reachability of a NaN force from a real diverged solve is still NOT shown (merged.md said so; I did not try either).
None ends in a 500.

`cafe/static/app.js`: a null of a stored result times 100 is 0 in JS, so `fmt(x * 100)` printed 0 for a number that was missing. Every arithmetic first argument of `fmt(` and every `Math.round(` over a stored result now reads `(x ?? NaN)`: NaN times anything is NaN and `fmt` prints the dash. 7 existing `fmt(` arguments changed and 7 `Math.round(x * 100)` sites (4 in `pct`, 1 in `showResult`, 2 in `linkCard`) became `fmt((x ?? NaN) * 100, 0)`, 14 guarded arguments in all: identical text for every p in [0, 1] on a 1e-5 grid (Node: 0 differences in 100,001 values). No new function, option or printed sentence.

Every number formatter of `app.js`, and how each treats null, undefined, NaN:
- `fmt(x, d)`: null, undefined and NaN all print "—" (unchanged: `x == null || Number.isNaN(x)`). Infinity would print "Infinity"; a stored file cannot hold one (`_read` reads the token as null).
- the 14 guarded arithmetic arguments (drag area, in_range_p50, in_range_p10, battery_left_p50, `-(r.z[0])`, receipt error and tol, p_success and p_interval[0], [1] and p_success in `pct`, share, link need, link p_success): null, undefined, NaN all "—" (Node output below).
- unguarded arithmetic arguments, each with the reason it cannot see a stored null (these five are held by the lint test): the two wind expressions of `/api/env/field` (a live response, the strict encoder refuses NaN); `lk.never_acquired * 100` (only reached when `> 0`, false for null and NaN); `gci * 100` (only reached when `gci == null` is false); `+U` (an object key).
- plain `fmt(x.y)` arguments (about 40): null, undefined, NaN print "—".
- `Math.round` left as is (5 uses): `kt / 5` (wind barb of the env field), `l.need * 100` (the editor's own value), `(st.progress || 0) * 100` twice (defaulted), `d.progress * 100` (design summary through the strict encoder).
- `gciText(gci)`: null or undefined " no index"; a number " +-N%" (NaN cannot arrive in JSON; if it did, `fmt(NaN * 100)` is the dash).
- `mmss(s)`: not a stored-result formatter (the time slider; `tmax` is `|| 1`-defaulted).
- raw template interpolation of a number (a null would print "null"), left: `d.power_w`, `d.battery_wh`, `dsg.battery_wh`, `d.spec.power_w`, `d.spec.battery_wh` (spec numbers, finite by `clean_spec`), `lk.max_m` (the mission's own requirement), `r.runs` (a count), `lk.max_m` in the tooltips.

Node run of the exact expressions (extracted from `app.js` by text, so they cannot drift; script `scratchpad/r22d/fmt_sites.js`, the ONE thing that exercises the JS; no browser, no JS runner in the suite; null, undefined, NaN, 0, 0.5, -0.25):
```
drag area     null: "—", undefined: "—", NaN: "—", 0: "0.0000", 0.5: "-0.0069", -0.25: "0.0035" | before: null: "0.0000", undefined: "—", NaN: "—"
in range p50  null: "—", undefined: "—", NaN: "—", 0: "0", 0.5: "50", -0.25: "-25"          | before: null: "0", undefined: "—", NaN: "—"
battery left  null: "—", undefined: "—", NaN: "—", 0: "0", 0.5: "50", ...                   | before: null: "0", ...
depth (uuv)   null: "—", undefined: "—", NaN: "—", 0: "0", 0.5: "-1", -0.25: "0"            | before: null: "0", ...
(and in range p10, receipt error, receipt tol, p_success, p_interval[0] and [1], reason share, link need, link p_success, plain longest gap, plain resistance: all three missing values "—")
all missing values read as a dash
```
What this does not show: the page in a browser (no browser run), and that the dash looks right in the layout ("—%" appears in `pct` for a missing probability).

`tests/test_round22_d.py::test_every_number_app_js_multiplies_before_formatting_reads_a_missing_one_as_a_dash` is a text lint over `app.js` (an enumeration test: a new arithmetic `fmt(` argument without `?? NaN` or a new `Math.round(` fails until listed with its reason). It is a text test, not a run.

### M-7

`cafe/vehicle.py` `hull_lift`: at the last angle of a plane, `gci(KF[ax], coarse)` is computed inside `try ... except (KeyError, ValueError): gcis.append(None)`. A missing `force_coarse` or `moment_coarse` key, or a coarse vector with a null/NaN item, is "no index": `None` goes through `vv.worst_gci`, whose `vv.gci_value(None)` is inf (the existing rule, reused; no new constant). So `lift_gci` is inf if any plane has no coarse force at its last angle, and the default 0.0 can only mean no plane at all (`build` stores no `lift_gci` then). Docstring narrowed to say exactly that. Only the LAST angle is read, as before: merged.md's fix text says "at the last angle", so I did not widen it; a test pins that a missing coarse force at an earlier angle is not read (0.2 stays 0.2). A coarse vector with a null used to be an unnamed TypeError; it is now "no index", not a refusal (a diverged coarse run with a finite fine run is a study with no index, not a damaged file).

"Infinity" check: `v.limits` (where `lift_gci` lives) is read by `mission.drag_sigma` and written to no file: `hangar.py` writes its own `hangar["limits"]` dict (rated depth, crush depth, glide band). Test: only `mission.py` and `vehicle.py` name `lift_gci`. So `hangar.py` needed no hunk.

Real cached results, measured on orca (read-only copy of the 18 files of `~/cafe-worker/cafe/data/cfdcache` into `~/cafe-worker/cafe/pmdata/r22d_cfd`, run through `vehicle.hull_lift` in the base tree (7a1aaa9, `pm_r22d_base`) and this tree (`pm_r22d`)): none changes. Four incidence results (`1ff6095fb1e9ca7d`, `554e9a17be98c3fe`, `797f434dbfe885db`, `8bcc680f9a9fd83c`; alphas 5 and 10, planes +y +z; all have `force_coarse` in every direction; all forces and moments finite): `lift_gci` before = after = 0.2115533020530432, 0.07135084174902702, 0.6485612941943396, 0.0853279900494573. The drag spread therefore does not move (it moves only when a lift index goes from finite to inf; 0.6486 is already above `GCI_TRUSTED` and already gives the estimate's 0.30). The 14 files with `dirs` (and `tests/fixtures/cfd_real/quad` and `torpedo`) have every `force`, `moment` and `viscous` of three finite numbers: `_vec3` refuses none (`total refused 0`). `tests/fixtures/cfd_real` has no incidence file (quad, torpedo external; wigley surface).

### M-9

`cafe/live.py` `step`: the four target numbers go through `jsonio.finite_real` (a bool, text, NaN, inf, and an integer too large for a float are refused; the message is the module's own "target needs numeric lat, lon (and optional z, speed)", one `ValueError` that `live_step` turns into a 400), then `float()`. The old `np.isfinite` clause went (finite_real covers it); "target is not a real position" now means only a latitude beyond the poles. `cafe/app.py` `live_step`: `seconds` through `finite_real` too (a bool was 1.0 s; message unchanged "seconds must be a number"). `cafe/app.py` `check_fleet`: `finite_real(l.get("minutes"))` (a bool was one minute). Import in `live.py`: `from cafe.pm.jsonio import finite_real` (stdlib only; a subprocess test with `yaml` and `jsonschema` unimportable imports `cafe.live` and `cafe.app` and asserts `cafe.pm.config` stays unloaded).

Every request handler of `cafe/app.py` and `cafe/live.py`: which reader, which number test:
- `list_designs`, `get_design`, `get_mission`, `get_emulation`, `receipts`, `live_get`: no body; files read by `_read` (`load_json`, NaN and Infinity read as null).
- `create_design` (multipart form): `load_json(spec, parse_constant=raise)`; `clean_spec`: spec numbers by `float()` after a bool/type refusal, OverflowError caught, then `math.isfinite`; `cog` by `finite_real`; `inertia` by `np.asarray` with OverflowError caught and `np.isfinite`.
- `create_shape_design` (JSON body, parsed by Starlette, so `load_json` cannot reach it): bool refused, `float()` with OverflowError caught, `shapes.check` bounds (it tests `np.isfinite` and a range); `clean_spec` for the spec.
- `env_field`, `reach_map` (query floats typed by FastAPI): `math.isfinite`.
- `create_mission`, `create_emulation`, `live_create` (via `check_fleet`): `_point` by `finite_real` (start, goto point); legs' `minutes` by `finite_real` (changed); link `max_m` and `need` by `float()` with OverflowError caught then `math.isfinite` and a range (OPEN: see below); `max_hours` and `samples` by `isinstance` without bool and a range (a 400-digit int fails the range, a NaN fails `0 <`); `live_create`'s `start` by `finite_real`; `live.create` `hours` by `isinstance`, bool refused, a range.
- `live_step`: `seconds` and the four target numbers by `finite_real` (changed).
- `live_end`, `delete_design`, `rerun_design`: no number.
`tests/test_round22_d.py::test_every_float_of_the_request_handlers_is_one_that_is_listed_with_what_checks_it` is an AST enumeration of every `float(` call of `app.py` and `live.py` by function with its reason: a new one fails until listed.

Behaviour change to decide on (the lead's instruction was `finite_real`, which the other handlers use): numeric TEXT in a live target or in `seconds` ("1.5") was accepted by `float()` and is now a 400, as it already was for `start` in `live_create` and in `_point`. Nothing in the repo sends text there (README example uses numbers). To keep text accepted, the alternative is merged.md's literal fix: `ArithmeticError` in the except plus a bool guard; I did not take it because it leaves `live_step` as the one handler outside `finite_real`.

## Siblings found, NOT fixed (the lead's steer: nothing new that merged.md does not name), with the exact hunk if wanted

1. `cafe/app.py` `check_fleet` link `max_m` and `need`: `float(lk.get("max_m"))` accepts `true` (1.0 m) and numeric text, and `mission.py:335-336` does `float(spec["max_m"])` again. Hunk (reuses the existing message; refuses numeric text, which would also stop an older stored mission with a text `max_m` from being re-flown by `create_emulation`):
   ```python
   mx, need = lk.get("max_m"), lk.get("need", 0.95)
   if not (finite_real(mx) and finite_real(need)):
       raise HTTPException(400, f"link {lk['a']}-{lk['b']}: max_m must be a number")
   if not (mx > 0) or not (0 < need <= 1):
   ```
   (the `try/except` and `math.isfinite(mx)` go). Listed as OPEN in the enumeration test, so adopting the hunk means updating that one entry.
2. `cafe/vehicle.py` free-surface branch (`build`, "fs"): `sp[0][1]["resistance"]` and `[r["resistance"] ...]` of a null (a NaN resistance written as null) is the same unnamed TypeError as D-4 (a bare NaN builds a silent NaN resistance). The cache path is safe (`_seed._checked` asks a number); a fresh run's result.json is not. Hunk: `for U, r in sp: if not finite_real(r["resistance"]): raise ValueError(f"speed {U}: `resistance` is not a finite number")`.
3. `_vec3` does not refuse a bool or numeric text item (`np.asarray([True, 0, 0], float)` is 1.0, `"1.0"` is 1.0; `"x"` is refused). Forces are solver output; a hand edit with `true` would build. Not closed.
4. `cafe/_site_data.py:163-164` and `cafe/receipts.py:363-462` do `np.asarray(c["dirs"][k]["force"])` on cached results; the cache holds only what `_seed._checked` accepted (three finite numbers), so no null can be there. Not touched.
5. `live.step` has no range for `lon` (finite only) and `z` (finite, `>= 0` for a non-USV); a finite `1e300` passes. Pre-existing, not named.
6. `live.create`'s `seed` and `links` are passed on unchecked by `live.create` (`links` pass `check_fleet`; `seed` into the mission). Not examined.
7. Batch E hunk: `tests/test_round21_e.py` `APP_IMAGE` lists `app.py` but not `live.py`; add `"live.py"` (my test already checks `live.py` by subprocess and by AST).

## What I tried as a hostile reviewer (all in `tests/test_round22_d.py`, 214 tests)

- `_vec3`: each of the three items bad (null, NaN, inf, -inf, 10**400, -10**400, text) for each of force, moment, viscous; whole value None, empty, two, four items, scalar, 2-D, text, dict, all null; good inputs of every kind (ints, tuple, float32 array, int array, 1e308).
- `build` of the real quad result with a null and a NaN at item 1 of every field of every one of the six directions (36 builds): names the direction and field. The real quad and torpedo vectors pass unchanged.
- `hull_lift`: null in the fine force or moment of `x+y5`, `+x`, `+z`, `x+z10` is named.
- M-7 property: for 1 to 3 angles x three ways of having no coarse force (key `force_coarse`, key `moment_coarse`, a null item) x EVERY subset of the directions of the study (672 subsets x 3 ways = 2,016 calls: 1,953 inf, 63 finite): inf exactly when a direction that a plane's last angle reads is in the subset, 0.2 otherwise (the test asserts more than 1,000 inf and more than 20 finite cases, so neither side can empty). One plane alone, no plane at all (0.0 and `{}`). End to end on the real quad: complete study index 0.2 gives `hypot(0.10, 0.2)` = 0.2236, one missing coarse force gives lift inf and exactly the estimate's 0.30.
- M-9: lat, lon, z, speed each with 10**400, -10**400, true, false, "1.5", NaN, inf, -inf, [1.0], {} (and null/absent for lat, lon, z): 400 naming the target, no tick, no leg set. `seconds` likewise plus null. A target that is not an object (text, int, null, list, text number). Accepted as before: ints and floats, the poles +-90, -0.0, absent z and speed, no targets, the default 10 s, speed 5.0 (the drone's top) and 1e-9; refused: 90.0000001 and -90.0000001 ("not a real position"), speed one ulp above top, 0, -1. `check_fleet` minutes for hold and follow: true, false, NaN, inf, -inf, 0, -1, 1441, 1440.0001, 10**400, text, null, list refused; 1, 0.5, 1440, 1e-9, 5e-324 accepted.
- Mutation by hand (15 mutants of my own changes, run on orca in `pm_r22d`, each restored): speed test removed, lat/lon/z test removed, latitude bound moved to -89, `TypeError` dropped from the target except, `seconds` test removed, `minutes` back to `isinstance`, `_vec3` shape test removed, finite test removed, `OverflowError` dropped, `KeyError` dropped, `ValueError` dropped, missing index taken as 0.0, first angle read instead of the last, and the two `app.js` guards removed: all 15 killed. This is not `make mutation` (no mutmut run).

## Verification (orca, proot, 2 CPUs each; jobs `r22d_*` in `~/cafe-worker/logs`, every one ended with an `rc=` line)

- `tests/test_round22_d.py` on this tree: `r22d_8`, 214 passed, rc=0.
- Same file on the base tree (7a1aaa9, a throwaway `git worktree add --detach ../cafe-r22d-base`, `pm_r22d_base`, job `r22d_b1`): 146 failed, 68 passed (the 68 are the tests that pin unchanged behaviour: good inputs, real results, in-range numbers). Reasons on base: no `_vec3`; `TypeError ... 'NoneType'`; `OverflowError: int too large to convert to float` from `live_step`; `DID NOT RAISE` for true, NaN and 400-digit values; `check_fleet` accepts `minutes` true and false (2 failures: only a bool was wrongly accepted there, NaN, inf, 0, 1441 and the rest were refused already).
- Existing tests that import or pin what I touched: `r22d_3`: `test_round20_m`, `test_round21_c`, `test_round21_d`, `test_round21_e`, `test_round21_m`, `test_round19_d`, `test_round20_d`, `test_audit`: 696 passed, rc=0. `r22d_4`: `test_receipts`, `test_dyn`, `test_glider`, `test_reach`, `test_usv`, `test_emulator`: 530 passed, 1 failed, rc=1: `tests/test_usv.py::test_table_equals_direct_coupled_solve`, a Hypothesis test (40 random examples) that found wind_from=180, speed=5, heading=0, cspeed=0, cdir=0 (track 5.64 deg off, bound 1.5). Not mine: the same example fails identically on the base tree (job `r22d_b4`, a direct call), and on a second run of the file in each tree the random draw did not hit it (`r22d_6`, `r22d_b2`: passed). It is a pre-existing corner of the USV table, not caused by anything here; for the lead.
- `ruff check cafe/pm tests`: clean (job `r22d_9`). `mypy cafe/pm`: "no issues found in 57 source files" (I changed nothing in `cafe/pm`). `audit.banned(.)`: `[]`.
- Coverage: no statement added in `cafe/pm`, so the 100 % gates are unaffected. Not run: the full suite, the gate, a demo, `make mutation`, `test_uas.py`, any run in a browser.

## Pins moved

None. No existing assertion changed; no existing test needed a `force_coarse` added (the round 20 `incidence()` already carries one; the `hull_lift_algebra_receipts` has no `force_coarse`, so its vehicle's `lift_gci` is now inf instead of 0.0, and that receipt checks the dynamics only, `test_receipts` passes).

## Decision text for DECISIONS (new rows; the owner is needed for the second)

1. (M-6/M-7, lead's choice) `vehicle._vec3` is the one reader of a stored force, moment or viscous vector: three finite numbers or a ValueError naming the direction and the field; `build` and `hull_lift` use it; a coarse force that is missing or not three finite numbers is "no index" (`vv.gci_value(None)` is inf), so `lift_gci` is inf for any plane with no coarse force at its last angle and 0.0 only for no plane. A hangar result with a NaN force now fails the design (it built a silent NaN drag). Only the last angle is read (stated, as the docstring always said). `app.js`: a stored number multiplied before `fmt` is `(x ?? NaN)`, so a missing one is a dash; every `fmt(` and `Math.round(` is held by a lint test. Amends 1052 ("'no index' in the browser, never 0 %": true for `gciText`, and now for the drag area and every product).
2. (M-9, needs the owner: numeric text is no longer accepted in a live step) `live_step` and `live.step` use `jsonio.finite_real` for `seconds` and every target number, as `_point` and `live_create`'s `start` do; `check_fleet`'s `minutes` too. Amends 1049, whose list names `live_step` as refusing an oversized integer "through `finite_real` and an `OverflowError` clause": it did not until now. Open sibling: `check_fleet` `max_m` and `need` (hunk above).

## Exact document sentences that must change (for batch G)

- DECISIONS 1049: "`live_step` refuse an oversized integer with a 400 through `finite_real` and an `OverflowError` clause" is true of `live_step` only after this batch, and not for `max_m`/`need` of `check_fleet` (`float()` + OverflowError clause, not `finite_real`); say so.
- DECISIONS 1052: "`cafe/static/app.js` `gciText(gci)` shows ' no index' ..." add the drag-area guard and the lint test.
- DECISIONS 1047/1033's `vehicle.build` and `hull_lift` descriptions: "a missing coarse force is skipped" if any sentence says it (`hull_lift` docstring is the source; I changed it).
- PROBLEMS: `app.js` not run in a browser; NaN force from a real diverged solve not shown; siblings 1 to 6 above; the USV Hypothesis corner.

## Expected demo q23 against q22

No verdict, count, interval or drag spread moves: the demo's vehicles come from the seed (cfd cache and fixtures), every force, moment and viscous vector of the 14 cached results with `dirs` is three finite numbers (none refused), and the four incidence results' `lift_gci` is unchanged to the last digit. The live step, the Hangar page and `check_fleet` are not on the demo's path.

## Leftovers

- orca: `~/cafe-worker/cafe/pm_r22d`, `pm_r22d2`, `pm_r22d_base`; `~/cafe-worker/cafe/pmdata/r22d_cfd/` (my copy of the 18 cache files) is REMOVED (by that exact name, after the runs); left: `r22d_real_lift.py`, `r22d_real_ext.py`, `r22d_lint.sh`, `r22d_usv.sh`, `r22d_mut.py`; logs `~/cafe-worker/logs/r22d_*.log`, `r22d_b*.log`. No tmux session of mine is running; nothing in `cafe/data`, `pmdata/cache`, `/tmp`. I leave these for the lead as evidence and will remove them by exact name on request.
- laptop: worktree `../cafe-r22d-base` (detached, with an untracked copy of the test file), scratch files under `scratchpad/r22d/`.
