# Round 12, reviewer D (report.py, credibility.py, receipts.py, acceptance golden; hostile missions run for real)

Method. Worktree `../cafe-rev12-d` (detached at 0a0532e, code identical to 72d7e66). All runs on orca at 1 to 2 CPUs from `pm_rev12_d*`, outputs under `/data/runs/rev12_d*`, each with its own `--emulator-table` (the shared table was not touched). The demo's cache is keyed by the mission name (`cache/<name>`, `gofs_<name>.zarr`), so the hostile variants of the demo (one vehicle, 24 h window, 20 vehicles) had to keep `name: tepex_c_demo` to run offline on the cached window and box; the dateline fixture and the id/platform variants used the synthetic `ci_env` data in `/data/runs/rev12_d_dl/data` with `--budget ci`.

Runs made (all finished unless noted): `rev12_d_dl` (ci_env dateline box, whole ingest to report, clean: no traceability or ledger problem, map box `[178.5, -178.5, -1.5, 1.5]`, tracks and reach polygons wrap correctly), `rev12_d_one` (1 glider, quick), `rev12_d_24h` (24 h window inside the cached one, quick), `rev12_d_lk_same` and `rev12_d_lk_odd` (link ids), `rev12_d_values` (vehicle id), `rev12_d_plat`, `rev12_d_uo`, `rev12_d_20` (20 vehicles).

The scripts quoted as `rev12d/*.py` (run on orca from the scratch copy as `python -m rev12d.<name>`) are kept in the session scratchpad `.../scratchpad/rev12d/`; the repo was not edited. The runs stay under `~/cafe-worker/cafe/pmdata/runs/rev12_d*` (about 130 MB), the scratch dirs `pm_rev12_d`, `pm_rev12_d2`, `pm_rev12_d3` and the detached worktree were removed.

Not findings (checked and held): a glider's current below the seafloor is filled, not NaN, so the reach grid is not blocked on the shelf (probe at Howland/Baker, z -500 and -950 on cells 486 m deep: 0 NaN); `check_rendered` and `check_traceability` pass for link ids with quotes, `<`, `&`, `.`, `[0]`; the dateline map and the report with a dateline box are right; the `json.dumps(default=str)` in `receipts._save` cannot turn a numpy bool into a string, because `cafe/receipts.py` casts `ok` with `bool()` in all three recorders.

### D-1. A link id equal to a vehicle id is accepted, and the Verdicts table then shows the link's verdict under the vehicle's name (and drops the other row)
severity: major
lane: robustness, honesty
where: cafe/pm/report.py:1677 (`{**rep["vehicles"], **rep["links"]}` builds the Verdicts table), :1051 (`both = {**vehicles, **links}` in the sanity rows), :1707-1708 (two `<div id='v-<id>'>`), cafe/pm/credibility.py:753 (`ens = {**vehicles, **links}`); cafe/pm/config.py:416-422 (ids are unique "across vehicles, ship and shore" only, links are not in `owners`); cafe/schemas/mission.json:64 (a link `id` is any string, even "")
reproduction: `rev12d/ids.py` on orca: `load_mission` ACCEPTS links with id `usv`, `ship`, `""` and `a b<i>'x"&`; it refuses only a link id repeated among links. Then a real run: the dateline `ci_env` fixture mission with its three links renamed `usv`, `glider_eq`, `uas` (`/data/runs/rev12_d_dl/mission_same.yaml`), `run --budget ci` rc 0, `report_traceable` and `report_html_matches_json` both ok, `traceability_problems` and `ledger_problems` empty. `report.json`: vehicles glider_eq GO 0 of 16, usv GO 1 of 16, uas NO-GO 16 of 16; links glider_eq NO-GO 16 of 16, usv NO-GO 11 of 16, uas GO 0 of 16. The page's Verdicts table has 4 rows (glider_eq, glider_1n, usv, uas) and shows `glider_eq NO-GO ... 16 members`, `usv NO-GO 0.6875`, `uas GO ... 16 members`: the link's numbers under the vehicle's name; the three vehicle rows' own verdicts (GO, GO, NO-GO) and the three link rows are not in it. The page has `id='v-usv'`, `v-glider_eq`, `v-uas` twice. Sanity rows (demo name only) read `both[r["id"]]["p_fail"]`, the same collision. An empty link id gives a row with a blank name and `<div id='v-'>`.
why it matters: the headline table of a valid mission contradicts the cards below it (a NO-GO vehicle is listed GO), and both self-checks pass because they compare the JSON with the HTML, which was built from the same merged dict. The loader's own rule ("ids must be unique") stops one namespace short.

### D-2. A vehicle (or link) whose id is `values` crashes the last stage with a KeyError after the whole run
severity: major
lane: robustness
where: cafe/pm/report.py:214-218 (`_walk` treats any dict with a `values` key as a number node), :1111 (`_txt` reads `n["unit"]`), :1740 (`check_rendered`), :1762 (`self_checks`); cafe/schemas/mission.json vehicle `id` pattern `^[A-Za-z0-9_\-]+$` allows it
reproduction: the dateline `ci_env` fixture with `glider_1n` renamed `values` (`rev12d/vals.py`, `/data/runs/rev12_d_dl/mission_values.yaml`), `run --budget ci`: stages run to the end (`report/index.html`, `report.json`, `credibility.*` are written), then the report stage's self-check dies with `File "/app/cafe/pm/report.py", line 1740, in check_rendered ... line 1111, in _txt: unit = f" {n['unit']}" ... KeyError: 'unit'`, a Python traceback, no `error:` line, no report ledger; `python -m cafe.pm report --run /data/runs/rev12_d_values` fails the same way. `rep["vehicles"]` is `{"glider_eq": ..., "values": ...}`, so `"values" in o` is true and the whole `vehicles` dict is yielded as one "node" (and `_walk` returns without looking inside it, so even where it did not crash, no vehicle number would be checked for traceability). The same holds for `links`, `map.vehicles`, `reach.vehicles`, `environment.vehicles`, `emulator.vehicles` (any dict keyed by an id).
why it matters: a valid mission fails at the very end of a run that may have cost hours, and the checks that guard "every number traces" are silently skipped for the colliding branch. The id can come from a lab user naming a vehicle `values`.

### D-3. The vehicle card explains failure modes that did not occur, and for a GO glider states something false
severity: minor
lane: honesty, documentation
where: cafe/pm/report.py:437-438 (`mode_notes={m: ... for m in e["modes"] if m in MODE_TEXT}`, and `overdepth` added when the key is present), :1273 (`_drivers_html` prints every note)
reproduction: `q12/report/report.json` (the demo): `vehicles.glider_2n` has `k_fail` 0, `modes` all 0, and `mode_notes` holds `overdepth`: "the depth passed the platform's rating_m (1000 m): the ordered dive depth (500 m) plus the apogee overshoot ... exceeded it; this is the vehicle's own overshoot at that order" and `no_current_data`. `index.html` prints both under "What drives the failures: no member failed." 500 m plus any overshoot cannot exceed 1000 m. `glider_eq` (18 failures, all `station_lost`) prints the same two notes; `usv` prints `capsize_proxy` and `no_current_data` with 0 members; `uas` prints `no_current_data` with 0. `e["modes"]` carries every mode with its count, zeros included (`mode_shares` of `glider_eq` lists eight modes, seven at 0).
why it matters: a reader of a GO card is told a failure cause that is false for that vehicle; the UAS speed block (report.py:1314) already tests `.get("value")` before it says "also met a wind that was not finite", which is the check the notes lack.

### D-4. The "Sanity check against the brief" is keyed on the mission name, so an edited copy of the demo gets the demo's expectations
severity: minor
lane: honesty
where: cafe/pm/credibility.py:123 (`EXPECTED = {"tepex_c_demo": ...}`), :749-751 (`sanity` looks up `mission["name"]`), cafe/pm/report.py:1046-1054
reproduction: `rev12_d_24h` (the demo with a 24 h window 3 to 4 March inside the cached one, otherwise unchanged, same name): the report has `sanity.applies` true and rows `glider_eq ... gliders MARGINAL or NO-GO ... observed GO ... agrees False`, `usv-uas-rf ... links GO ... observed NO-GO ... agrees False`, and the USV row's expectation reads "MARGINAL in the low-wind/high-current window of 7-8 March (the demo window ends 7 March 12Z)" for a window that ends 4 March. `rev12_d_one` (one glider) shows the table for the 2 rows it has. The name is also the key of the cache (`cache/<name>`, `gofs_<name>.zarr`, pipeline.py:102), so a variant run offline on the cached window must keep the name: a variant named `rev12_d_one` failed `orca_present` and `ocean_store_present` with "not cached" (rc 1, 8 s), so reusing the cache and getting the demo's sanity table go together.
why it matters: a mission that is not the demo is judged against the demo's expected outcome and a disagreement is printed in bold as "NO". Key it on the mission's content (window, box, vehicles, positions) or its file hash, not its name.

### D-5. "N inputs are assumed or are priors ... and verdicts depend on them" counts the platforms the mission does not fly
severity: minor
lane: honesty
where: cafe/pm/credibility.py:283-286 and :874-883 (`assumed_inputs` walks every `platforms/*.yaml`), cafe/pm/report.py:1034-1043 (`_assumed`), :1634 (the sentence)
reproduction: `rev12_d_uo` (one UAS, no links, no shore): `report.json` `assumed_inputs.total` 285 with `by_file` saildrone_explorer 59, seaglider 21, slocum 26, modems 4, radios 19 (129 of the 285), none of which the mission uses; the page says "285 inputs ... are assumed or are priors, not measurements, and verdicts depend on them". `Facts.used` already knows the platforms and tables the mission uses (credibility.py:448) and the input-pedigree score reads only those.
why it matters: the count is the report's headline for how much of a verdict rests on assumptions; here 129 of the 285 (45 %) belong to platforms that are not in the mission.

### D-6. `damaged_run_files` does not catch AttributeError, so valid JSON with a non-object entry is a traceback in `report --run`
severity: minor
lane: robustness
where: cafe/pm/config.py:228-233 (catches KeyError and TypeError only); readers: the per-vehicle `.get` calls in `_vehicles` (report.py:466, `s1` summary), `_stage3` (:850, :855 `rv.get`, `w.get`), `_emulator` (:949 `e.get("trained")`) and `_fix` (:366)
reproduction: `rev12d/fuzz.py` calls `report.build` with each input replaced by a wrong-shaped object: `stage1/summary.json`, `refit/refit.json`, `emulator/holdout.json`, `emulator/flip.json` with a vehicle entry that is an int or a list raise `AttributeError: 'int' object has no attribute 'get'`; `emulator/flip.json` = `{}` raises `KeyError 'vehicles'` (this one is caught). End to end (`rev12d/dmg.py`): `emulator/holdout.json` = `{"glider_eq": 5}` in `/data/runs/rev12_d_one`, `cli.main(["report","--run",...])` ends with `UNCAUGHT AttributeError 'int' object has no attribute 'get'` (restored afterwards). `report --run` does not verify the ledgers first, so this path is reachable by a damaged or hand-edited file.
why it matters: this is the "valid JSON of the wrong shape" class that rounds 10 and 11 closed (M-5, M-25) for KeyError and TypeError; the third exception of the same class is the one left out, and `audit.py:220` already lists AttributeError.

### D-7. A `runs/receipts.json` of the wrong shape crashes the report with a bare KeyError or TypeError
severity: minor
lane: robustness
where: cafe/pm/report.py:104-111 (`_table` checks that the file is JSON, not its shape), :158 (`r["module"]`), :161 (`r["name"]`)
reproduction: `rev12d/rt.py` points `report.RECEIPTS` at a file holding `[{"x": 1}]`, `[1, 2]`, `{"a": 1}`, `"x"`, `null`: `Trace(run).physics("glider")` raises KeyError 'module', TypeError, TypeError, TypeError, TypeError; a row `{"module": "pm.physics.glider", "kind": "fail", "ok": false}` raises KeyError 'name'. `report.write` calls `physics` for every vehicle, so the report stage dies without an `error:` line.
why it matters: the same class as D-6; the receipts table is the one input of the report that is shared by every run and written by a separate command (non-atomically: `receipts.run` uses `out.write_text`).

### D-8. `acceptance.normalize` leaves the run's path in the report when it has a non-ASCII character, a quote or a backslash, so `same_seed` fails
severity: minor
lane: reproducibility
where: cafe/pm/acceptance.py:381-383 (`unrun` replaces `str(run_dir)` inside `json.dumps(rep)`, which escapes non-ASCII and quotes)
reproduction: `rev12d/norm.py`: `normalize({"x": {"ref": f"{d}/ingest/a.json"}}, d)` with `d = /data/runs/rev12_d_norm/<name>` gives `<run>/ingest/a.json` for `quick` and `a b`, but `/data/runs/rev12_d_norm/café/ingest/a.json` for `café` and `/data/runs/rev12_d_norm/q"x/ingest/a.json` for `q"x`. The report holds the run's path (`mission.data_consumed.inputs[].ref`, q11_vs_q12 notes the manifest copies). `acceptance --out /home/josé/acc` therefore compares `.../quick/...` with `.../quick_same/...` and reports differing fields.
why it matters: `make acceptance` uses `runs/acceptance` under the checkout, so a checkout under a path with an accented letter fails `same_seed` for a reason that has nothing to do with reproducibility. Replace the path in the dict (walk the strings) instead of in the dumped text.

### D-9. `receipts --only a,typo` runs `a` and ignores `typo`; the docstring says a part that matches nothing exits 2
severity: minor
lane: documentation, robustness
where: cafe/pm/receipts.py:449 (`not any(o in n for o in only for n in names)` fails only when no part matches), docstring :32
reproduction: `CAFE_DATA=/data/runs/rev12_d_norm python -m cafe.pm receipts --only pm.stats.intervals,nosuchgroup --json /data/runs/rev12_d_norm/r2.json` runs `pm.stats.intervals` (8 pass), prints no word about `nosuchgroup`, exit 0.
why it matters: a typo in a partial run is silent, and the partial table is what a reader then trusts for the group they thought they ran.

### D-10. `other_seed` fails on a different member count, which the stopping rule makes data-dependent
severity: minor
lane: statistics
where: cafe/pm/acceptance.py:317-318 (`compare`: `cls`, `platform`, `n` must be equal also when `seed=False`), docstring lines 40-42; cafe/pm/stats/sequential.py:37-47 (`ensemble_stop` stops as soon as every interval is inside GO or NO-GO, else at `n_max`)
reproduction: by reasoning with q12 and the golden: the old golden stopped at n = 32 for every entry, q12 at 64; the demo stops at 64 whatever the seed only because `glider_eq` stays MARGINAL, which never satisfies the stop. For a mission in which every interval clears a cut-off at 32 under one seed and one does not under another, `quick` and `quick_seed` end at 32 and 64 and `other_seed` fails with "n: 32 in the reference, 64 now", although `intervals.newcombe_diff` takes two different n and is the test the check says it makes. Not run (the check needs two 20-minute runs).
why it matters: a spurious red in a gate for a mission that decides early; the exact-n rule belongs to the same-seed golden, not to two independent seeds.

### D-11. `acceptance --update-golden` writes the shipped golden from any mission
severity: minor
lane: robustness
where: cafe/pm/acceptance.py:305-310 (`check_golden` with `update`), :109 and `__main__.py:109` (default `--golden` is the demo's file)
reproduction: by reading: `acceptance --mission missions/ci_fixture.yaml --update-golden` writes `tests/golden/tepex_c_demo_quick.json` with `summary.mission` "ci_fixture"; no check compares the mission with the file's name or with the existing golden's mission. The next demo acceptance then fails `mission: 'ci_fixture' in the reference`. (The file is tracked, so git restores it.)
why it matters: the golden is the regression reference; the command that rewrites it has no guard on what it rewrites it from. Refuse when `summary.mission` differs from the existing golden's, unless the golden is absent.

### D-12. Two assumed modem entries print the value "None"
severity: minor
lane: documentation
where: cafe/pm/credibility.py:186-187 (`value=repr(node.get("value"))`), :866
reproduction: `q12/report/credibility.json` `assumed_inputs`: ids `modems.yaml:modems.benthos_atm960` and `modems.yaml:modems.whoi_micromodem` have `value` "None" (their numbers are in the `assumed:` text, `platforms/modems.yaml:22,29`); both pages print `(assumed) None` in the Value column.
why it matters: a reader sees an assumed input with the value None; the table cannot say what was assumed.

### D-13. The app's stored CFD and SITL result files become PASS rows with no check of which code made them
severity: minor
lane: honesty, reproducibility
where: cafe/receipts.py:253-277 (`cfd_receipts`), :528-539 (`crosscheck_receipts`), cafe/pm/receipts.py:229-240 (`_app`); also cafe/receipts.py:480-518 (`os.environ["CAFE_OCEAN"] = "0"` and `mission.PHYS_DT["uav"]` restored without try/finally; `weather_receipts` sets "1" unconditionally)
reproduction: `rev12d/xc.py`: a hand-written `crosscheck.json` ({"drones": {"q": {"firmware": "ArduCopter-SITL", "fast": {"battery_left": 0.5, "hold_p95": 1.0}, "sitl": {"battery_left": 0.5, "hold_p95": 1.0}}}}) gives two rows of kind `pass`: "Emulator: q: battery left, fast mode vs ArduCopter-SITL" and "hold error p95", sources "ArduPilot SITL flying the same physics". Unlike the slow groups (a code digest, a date, a host in `_save`), these files carry nothing the table can check, and the app group is "stale" only by the whole-table digest.
why it matters: the report cites the `app` group as model receipts; a stale or edited result file passes. If `fleet_receipts` raises between lines 480 and 518, `CAFE_OCEAN` stays "0" and the quad time step stays halved for the rest of that process.

### D-14. A 20-vehicle quick run takes 26 minutes against the 20-minute budget, and the report does not say so
severity: minor
lane: performance, honesty
where: cafe/pm/report.py:1013-1031 (`_machine`: per-stage `wall_s`, no total, no comparison with `plan.budget_s`), cafe/pm/budget.py:526-528 (`emulator_share_s`), the `stage1b_sensitivity` rerun (report.py:1000-1002, "in no share of the plan")
reproduction: `/data/runs/rev12_d_20` (8 gliders, 8 USVs, 4 UAS, 8+8+4 links, demo cache, `--budget quick`, 2 CPUs on a loaded orca, started 08:45:59, rc 0 at 09:12:39 UTC): stage walls ingest 45, hangar 1, stage 1 904, windows 3, stage 3 34, stage 1b 215, emulator 347, report 36 s: 1,585 s = 26.4 min against `budget quick (20 min)` (`plan.budget_s` 1200). Stage 1 was planned at 507 s (a stated lower bound) and took 904 s, exactly its share (900 s); stage 1b took 215 s (209 s of it the USV brief-bias rerun, which scales with the 8 USVs and is in no share) and the emulator 347 s, of which the flip search spent 239 s of the 240 s share `emulator_share_s` gives it with stage 1b free; the plan said 0 of 6 variants run. `report.json` `machine` has `describe` "budget quick (20 min)" and the per-stage walls, no sum and no "over budget" text; `index.html` has none either. `traceability_problems` and `ledger_problems` are empty and all 40 verdicts are present (gliders GO, USVs and UAS NO-GO, as the demo's).
why it matters: the budget names the time a lab user has planned for; the page of a run that took 33 % longer prints the budget and the stage times and leaves the sum to the reader. (The planner's lower bound and the unplanned sensitivity rerun are known; the missing line in the report is the finding. acceptance times only the demo.)

total: 14 findings (0 critical, 2 major, 12 minor)
