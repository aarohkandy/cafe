# Round 21, batch D hand-back: seed, GCI readers, the JSON reader (M-5; M-9's reader, seed and wrapper)

Branch r21-d, cut at 7599881. OD-6 (a) and OD-8 (a) as the lead's notes say.

## The names the other batches use (exact)

```
cafe/pm/jsonio.py          stdlib only (see "Where it lives")
config.load_json(src: str | bytes | pathlib.Path, **kw: Any) -> Any
config.finite_real(v: Any) -> bool
vv.GCI_TRUSTED = 0.3                                   (float)
vv.gci_trusted(g: Any) -> bool
vv.gci_value(g: Any) -> float                          (unchanged signature; None, a missing key's .get, NaN, inf, text, bool, an oversized int -> inf)
vv.worst_gci(gcis, default=0.0) -> float               (unchanged)
```

`config.load_json(src, **kw)`: `src` is the TEXT (str or bytes) of the JSON, or a `pathlib.Path` of the file (read with `Path.read_text`; an OSError is
the caller's, as with `read_text`). It is `json.loads(text, parse_int=<checked int>, **kw)` with two failures made `ValueError`: an integer literal that
does not fit a float (`float(int(literal))` overflows: about 1.8e308, the message is "an integer of N characters is too large for a number (...)", it never
prints the literal) and nesting deep enough for a `RecursionError` ("nested too deeply to be read"). Everything else is what `json.loads` does, including
`JSONDecodeError`, `UnicodeDecodeError` (both `ValueError`), and NaN / Infinity / -Infinity, which STAY READABLE (the project writes a NaN `gci` on
purpose). `kw` passes through to `json.loads` (an `object_pairs_hook` works); `parse_int` may not be passed (TypeError). An integer that fits a float is
returned as the `int` it is (2**53 + 1 stays exact). A string that is a PATH is not read as one: pass `pathlib.Path(...)`.

`config.finite_real(v)`: True only for a Python `int` or `float` (not a bool, not `numpy.int64` or `float32`) that is finite; an int too large for a float is
False (not an OverflowError). It is the same function object as `jsonio.finite_real`; `vv.gci_value`, `_seed._num` and the seed's `gci` check call it.
For batch B: `credibility.real_ok(v)` may be `return finite_real(v)` after `from .config import finite_real`; mypy strict accepts that import because
`config` re-exports it explicitly (`finite_real as finite_real`). `conf_ok`: same test for each element.

`vv.gci_trusted(g)`: `0 <= gci_value(g) <= GCI_TRUSTED`: 0.3 itself is trusted, a negative one (an index is a magnitude) is not, NaN / inf / None / text /
bool / an oversized integer are not.

`damaged_run_files` is in `cafe/pm/config.py` (not `__main__.py`, which only imports it): I added `ArithmeticError` there. Batch C has no hunk to write.

## Where it lives, and a correction of the plan

The plan put `load_json` and `finite_real` in `config.py`. `vv.py` cannot import `config`: `config` imports `yaml`, and the live app image has no pyyaml
(`cafe/atomic.py`'s docstring; `requirements.txt`; `vehicle.py`, `hangar.py` and `mission.py` import `vv`). `cafe/_seed.py` runs in that image too. So both
functions are DEFINED in `cafe/pm/jsonio.py` (stdlib only; inside `cafe/pm`, so it is covered, linted, mypy-checked and in the banned-token scan with no
change to `pyproject.toml` or `audit.py`) and `config` re-exports them under the same names. A test imports `cafe.pm.jsonio, cafe.pm.vv, cafe.vehicle,
cafe.mission, cafe._seed` in a subprocess with `yaml` and `jsonschema` made unimportable and asserts that `cafe.pm.config` was not imported. (A first
version of the module sat in `cafe/jsonio.py`; `tests/test_audit.py::test_every_cafe_module_the_pipeline_imports_is_in_the_banned_token_scan` failed on it
because `cafe/` modules outside `cafe/pm` must be listed in `audit.IMPORTED`; moving it into `cafe/pm` is the smaller change.)

## What changed and why

M-5 (`cafe/pm/vv.py`, `cafe/mission.py`, `cafe/vehicle.py`):
- `vv.GCI_TRUSTED = 0.3`, `vv.gci_trusted`. The one reader of a missing key is `vv.gci_value(r.get("gci"))` (None is inf). `vehicle.py` lines 290 and 344 lost their
  `0.0` default.
- `mission.drag_sigma` is now `min(hypot(SIG["drag_cfd"], vv.worst_gci(gcis)), SIG["drag_est"])`: no branch. A NaN, inf, missing or above-0.3 index gives exactly
  0.30. DEVIATION FROM THE TEXT OF M-5, SAFE: M-5 says "the finite trusted ones combine as today"; as today, an index of 0.3 (trusted) gives hypot(0.10, 0.3) =
  0.316, WIDER than the estimate's 0.30 that an index of 0.31 now gives: a worse index would give a narrower spread. The cap at the estimate's spread makes the
  spread monotone in the index and never wider than an estimate's. It changes nothing for an index up to 0.283 (every real result: 0.001 to 0.125), and
  because hypot(0.10, g) reaches 0.30 at g = 0.283, below `GCI_TRUSTED`, the cap IS the trust threshold: "any untrusted index gives the estimate's spread" holds
  for every input, and a test (`test_m5_the_spread_never_narrows...`) holds the constants to that.
- A missing `lift_gci` key stays "no lift study" (not an index); `lift_gci` present and None is an untrusted index. A resistance vehicle with no
  `resistance_gci` is a missing index (inf); `vehicle.build` always sets it.
- Median member drag scale at the new widest spread: exp(-0.30**2/2) = 0.956 (analytic; M-5's measured table for an index of 1.5 was 0.326, 77 % of members
  below nominal).

M-9 (`cafe/pm/jsonio.py`, `cafe/pm/config.py`, `cafe/_seed.py`, `cafe/pm/vv.py`):
- `load_json`, `finite_real` as above. `config.json_object` (the reader of every run file the commands read back) uses `load_json`; its `RecursionError` clause is
  gone (it cannot happen). `cafe/pm/config.py:227` (the package schema) stays a raw `json.loads`: not user data (the grep test of batch E should allow-list it).
- `damaged_run_files` takes `ArithmeticError` (OverflowError, ZeroDivisionError, FloatingPointError): the same "damaged or incomplete" message, for every file and
  field.
- `_seed`: `_num` is `finite_real`; the `gci` check takes any float (NaN and inf by design) or an integer that is a finite number (a 400-digit `gci` was cached
  and then crashed every `vehicle.build`); the file is read by `load_json` (so a 400-digit `rho`, `force` or `gci` is `NOT seeded <file> - an integer of 401
  characters is too large for a number...`, exit 1, nothing written, no traceback).

## Real results: does a real vehicle's number move?

Measured by reading the JSON (a Python script on orca over a COPY of the 18 files of `~/cafe-worker/cafe/data/cfdcache` in `~/cafe-worker/cafe/pmdata/r21d_cfd`,
removed by the 18 exact names and `rmdir` afterwards; the cache itself was only read by `cp`):
- `tests/fixtures/cfd_real` (the six results `_seed` takes): largest index quad 0.0670, torpedo 0.1254, wigley 0.0319; none above 0.3, none missing, none NaN.
  Their spread is unchanged (a test pins `hypot(0.10, worst)` for each, built through `vehicle.build`), and all three still seed (`test_round20_d`, passed).
- The 18 cache files: 17 have every index at or below 0.188 (largest 0.188, `x+z5` of an incidence study), none missing or non-finite. ONE has indices above 0.3:
  `797f434dbfe885db.json`, water, L 1.5 m, 0.3078 m/s, level 6 (70 728 cells), an incidence study (planes +y and +z, 5 and 10 degrees): all seven indices
  0.4412 to 0.5717. Whatever vehicle is built with it as `cfd_aoa` has `lift_gci` 0.5717, so its drag spread moves from hypot(0.10, 0.5717) = 0.580 to 0.30. I did
  not find which design it belongs to (the file holds the recipe, not the mesh name). `hangar.grid_warning` already warns for it (0.57 > 0.3).
- `cafe/pm` does not import `mission.drag_sigma` or `vehicle.build` (grep: none), so a pre-mission demo run (q23) is untouched by M-5.

## Tests

`tests/test_round21_d.py` (98 ids). On a throwaway `git worktree add --detach ../cafe-r21d-base 7599881` (the file copied in, `jsonio` and `from cafe.pm import
jsonio` made absent: job `r21d_base2`, rc=1): 73 of 98 FAIL, 25 pass (guards of behaviour that did not change: trusted combinations, `finite_real` of good
numbers, the real-result spreads fail there only because `vv.GCI_TRUSTED` does not exist). After the fix: 98 passed (`r21d_lint3`, rc=0 for the pytest step).
Mutation of every new guard by hand (`r21d_mut1`, rc=0): 18 mutants, 18 killed: the bound `<=` -> `<`, the `0 <=`, `GCI_TRUSTED` 0.31 and 0.29, the cap removed,
`lift_gci` missing as `[0.0]`, the resistance default restored, the two `r.get("gci", 0.0)` readers restored, `ArithmeticError` removed from the wrapper, the
overflow check, `parse_int` dropped, the `RecursionError` clause, the bool exclusion and the OverflowError clause of `finite_real`, the seed's `gci` check
and `_num`, `json_object` back to `json.loads`.

Run list (orca, 2 CPUs each, `PMX=pm_r21d*`): `r21d_2` (new file + `test_round20_m` + `test_round20_d`) rc=0, 179 passed; `r21d_3` (test_config, test_vv,
test_round19_d, test_round17_e, test_round18_d, test_dyn, test_audit, test_receipts, test_cfd, test_conventions, test_usv): 1092 passed, 1 failed:
`test_audit::test_every_cafe_module_the_pipeline_imports_is_in_the_banned_token_scan` on `cafe/jsonio.py` (the first location; fixed by the move);
`r21d_5` after the move (new file, round20_m, round20_d, test_audit, test_conventions, test_config_docs, test_vv, test_round19_d, test_round18_d, test_round17_e):
rc=0; `r21d_lint3`: `ruff check cafe/pm tests` clean, `mypy cafe/pm` clean (56 files). `r21d_4` (test_cli, test_whatif, test_report, test_credibility,
test_round20_c, test_round19_m, test_stage1; ran on the tree before the module move, which changes imports only): rc=0, 994 passed (counted from the progress characters).

## Pins moved, each by design

- `tests/test_round20_m.py::test_m3_the_drag_spread_of_a_vehicle` (the `drag_sigma` case; the `gci_value` and `worst_gci` cases are UNCHANGED): `lift_gci=0.4` now gives the
  estimate's 0.30 (was hypot(0.10, 0.4) = 0.41; a pin of 0.25 added to keep a trusted lift index covered); `drag=[0.5, INF]` ("a wide finite one is kept") now 0.30;
  `fake(resistance=1)` with no `resistance_gci` key now 0.30 (a missing key is inf; was 0.10) and `resistance_gci=0.0` carries the old 0.10 pin. The docstring says
  so. For batch C: the rest of that file (the `ingest-ocean` case, and `test_m3_the_hangar_warns...`, which pins the words "verdicts lean MARGINAL" and
  "GCI up to 45%") is yours; I did not touch it.
- `tests/test_round20_d.py::test_r20_m7_a_deeply_nested_file_is_not_seeded_not_a_recursion_error`: the message is `config.load_json`'s "nested too deeply", no longer the
  RecursionError's "recursion".
- The stand-in results of test_round19_d, 17_e, 18_d already carry `gci=0.01` per direction: nothing to add; the three files pass.

## Hunks and notes for other batches

- batch C, `cafe/hangar.py` `grid_warning` (lines 253 to 256): `gcis = [r.get("gci") for c in ... ]` and `gcis += [r.get("gci") for r in ...]` (no `0.0` default: a missing key is
  inf, the warning then says "a direction has no GCI at all"); `if not gcis or vv.gci_trusted(worst):` instead of `worst <= 0.3` (equal for every finite value;
  `worst` is never negative-only in practice); the text per OD-6 ("so drag uncertainty is wide; verdicts for such a vehicle are not decided by the CFD").
  `GCI_TRUSTED` and `gci_trusted` exist in this branch.
- batch B: `credibility.real_ok`, `conf_ok` as above.
- batch E, sites that my reading found (not edited, not my files): `cafe/pm/stage3/freesurface.py:214` `math.isfinite(gci)` and 210, 239, 241 (a stage-3 stored value:
  `finite_real`); `cafe/pm/stats/sampling.py:58, 73, 75`; `cafe/pm/receipts.py:61, 83`; `cafe/pm/ledger.py:258`; `cafe/app.py:124, 135, 324, 350, 392, 444, 539` (batch C; request
  bodies parsed by Starlette's `json.loads`: a 400-digit integer there is an OverflowError, a 500). The raw `json.loads` in `cafe/*.py` (outside `cafe/pm`, so outside the
  grep test as the plan words it): `cfd.py:116` (the CFD cache read: a hand-placed poisoned entry; `cfd.py`'s calls are NOT in its cache key, only its numbers and texts, so
  replacing the call would keep the cache, but it is not in any batch's files), `hangar.py:266, 399, 401`, `mission.py:657`, `emulator.py:313`, `receipts.py:94`,
  `planner.py:57, 189`, `worker.py:19`, `_site_data.py`, `app.py:39`. The grep test of batch E must allow-list `cafe/pm/config.py:227` (schema) and `cafe/pm/jsonio.py` itself
  (it calls `json.loads`).
- `cfd.characterize_external(refine_above=0.3)` is the same threshold written a second time as a keyed literal. NOT changed: it is in the CFD cache key (a literal in a
  default argument), so replacing it by `vv.GCI_TRUSTED` would change the key of all 18 cached results. Same value today; say so in DECISIONS.
- Deploy: `cafe/mission.py` and `cafe/vehicle.py` now need `cafe/pm/vv.py` and `cafe/pm/jsonio.py` beside them in the image (`vehicle.py` already imported `vv`; `sync.sh` ships the
  whole tree). Not deployed.

## Document sentences that must change (batch G)

- DECISIONS.md:1086 (row 1033): "so for a vehicle with an index of `inf` the spread is the larger of the estimate's `SIG['drag_est']` (0.30...) and the usual `hypot(SIG['drag_cfd'], the
  largest finite GCI)`" becomes: the spread is `min(hypot(0.10, the worst index), 0.30)`, so any untrusted index (NaN, inf, missing, above `vv.GCI_TRUSTED` = 0.3) gives exactly 0.30; and
  "a MISSING `gci` key is still read as 0.0" becomes "a missing key is inf".
- DECISIONS.md:1076 (row 1023 (a)): the nested-file message is no longer 'maximum recursion depth exceeded ...' but 'nested too deeply to be read'.
- QUESTIONS_FOR_LAB.md:214 (18h): "the mission's drag spread is the larger of the estimate's 30 % and the usual 10 % combined with the largest finite GCI" becomes the new rule; add that
  0.3 is ASSUMED (the warning's old literal, not derived), and that a vehicle built with `797f434dbfe885db.json`'s incidence study (0.44 to 0.57) moves 0.58 -> 0.30.
- docs/RUNBOOK.md:280: "(the type is KeyError, IndexError, ValueError, TypeError or AttributeError" gains OverflowError and ZeroDivisionError (any ArithmeticError).
- New DECISIONS rows (the owner decides OD-6): OD-6 (a) with the cap deviation above and its evidence (the lognormal table of M-5); OD-8: `cafe/pm/jsonio.py` is the home (the app image
  has no pyyaml), `config` re-exports; the 400-digit message; NaN stays readable. CHANGELOG: one line per decision.

## What a demo run q23 shows against q22

No difference in any verdict, count or interval: `cafe/pm` does not call `drag_sigma` or `vehicle.build`, and `json_object` reads the same files; the only visible change is the text of
an error for a hand-damaged file. Not verified by a run (the brief says no demo).

## Attacks I tried (hostile reviewer), all in the tests

The boundary 0.3 and one ulp either side; -0.0, -1e-12, -0.1, -5 (negative); NaN, inf, -inf, None, text, True, False, list, dict, 10**400, -10**400, 10**308 (fits), the largest
float as an integer and the first integer `float()` refuses (half way to 2**1024, rounds to even: the boundary test asserts both sides); 5000-digit literal with the interpreter's
digit limit on (its own ValueError) and off (`sys.set_int_max_str_digits(0)`: ours); depth 100 000 lists and objects; bytes, Path, a missing file, invalid UTF-8; NaN / Infinity
tokens; the spread over 2001 indices from 0 to 1 (monotone, never above 0.30, equal to the rule); the mean-preserving median at every spread; a missing key in each of six directions of
the real torpedo and quad and each of three speeds of the Wigley; an index of 1.5 in one direction of the real torpedo; the same seeds with the oversized integer in `rho`, `nu`, `L`, `gci`,
`force`; `damaged_run_files` with Overflow, ZeroDivision, FloatingPoint and bare Arithmetic errors, and with a `ConfigError`, a `RuntimeError` and a `KeyError` (unchanged behaviour).
Cost of `load_json`: a stdlib micro-benchmark on the laptop (no project code, Python 3.9): 1 000 000 integers in one file, 0.033 s plain and 0.102 s with the checked `parse_int`; floats unchanged
(0.099 s both). Not measured on orca, so an estimate for the server.

## Known quirks, not fixed

- `drag_sigma` of a small NEGATIVE index (-0.2) uses its magnitude (`hypot`), although `gci_trusted(-0.2)` is False; -5 gives 0.30. No real index is negative (`cfd.gci` is an absolute value);
  not pinned by a test.
- `config._finite` (the mission YAML) checks floats only, so a 400-digit YAML integer passes it; `test_platform_required` covers the platform files. Not touched.
- `finite_real(numpy.int64(1))` is False (as `vv.gci_value` always was): a numpy integer is not a JSON number.

## Not verified

- `r21d_4` and `r21d_3` ran on the tree BEFORE `jsonio.py` moved from `cafe/` to `cafe/pm/` (an import-path change); after the move only `r21d_5` and the lint/new-file job ran, not those two sets again.
- No full suite, no gate, no demo, no browser, no mutation run of mutmut (the gate's mutation record on physics and stats is untouched: none of them imports a changed function).
- The real vehicle that uses `797f434dbfe885db.json`.

## Leftovers

Orca: `~/cafe-worker/cafe/pm_r21d`, `pm_r21d2`, `pm_r21d_base`, `pm_r21d_mut` (synced trees), `~/cafe-worker/cafe/pmdata/r21d_lint.sh`, `r21d_mut.py`, logs `r21d_*` in `~/cafe-worker/logs`. `pmdata/r21d_cfd`
removed. Laptop: the detached worktree `../cafe-r21d-base` was removed; scratch in
`/private/tmp/claude-501/-Users-aaroh-Downloads-everything-cafe-main/e5175414-543a-42ed-83ef-98e3ca2ddc48/scratchpad/r21d`.
