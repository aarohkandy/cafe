# Reviewer B, round 5 (commit 09d54f3 / 6d32946; q5 run at d9878e4)

Method: read the brief, STATUS, DECISIONS 237-275, RUNBOOK, the q5 ledgers, `plan.json`, `report.json`, `credibility.json`, `index.html`; reran numbers from them;
probed the code on homebase at 1 CPU in `~/work/cafe/pm_rev5_b` (CI synthetic environment, `AnalyticEnv`, `config.load_mission`, `budget.plan`, the CLI).
All probe scripts are in `/private/tmp/claude-501/-Users-aaroh--claude-spares-spare-P6utrU/96cd665b-6853-40e7-8769-780fbfcaeebd/scratchpad/rev5/b_work/cafe_copy/probes/` (p1 to p13) and run
through `/private/tmp/claude-501/-Users-aaroh--claude-spares-spare-P6utrU/96cd665b-6853-40e7-8769-780fbfcaeebd/scratchpad/rev5/b_work/rb.sh <cmd>` (rsync without --delete, 1 CPU, private dir). Nothing in the repo was edited.

## Major

### B-1. A vehicle whose last 60 s step ends seconds after `window.end` is failed as `left_data` in every member (spurious 100 % NO-GO); the emulator design already drops 2 of 28 vehicle-variants this way
severity: major
lane: robustness / data (time)
where: cafe/pm/physics/glider.py:458 and cafe/pm/physics/usv.py:594 (`range(int(round(seconds / dt)))`), cafe/pm/stage1.py:68-82 (`_record_grid`), cafe/pm/stage1.py:431-441 (`_left_data`), cafe/pm/env/environment.py:134-143 (`inside`, `t <= tw.x[-1]`), cafe/pm/whatif.py:310-312 (skip text), cafe/pm/config.py (accepts deploy times with seconds; `MIN_DEPLOY_BEFORE_END_S` only checks 600 s)
reproduction: `rb.sh sh probes/p11.sh` (CI environment, `missions/ci_fixture.yaml` window ends 2023-03-03T06:00:00Z, one drift glider, M = 4, lenient env as the pipeline runs it). Deploy time -> last stored record minus `window.end` -> members flagged `left_data`:
`18:00:00Z` -> 0 s -> 0 of 4; `18:00:20Z` -> +20 s -> 4 of 4; `18:00:30Z` -> +30 s -> 4 of 4; `18:00:50Z` -> -550 s -> 0 of 4. The same for the USV (probe `p11u.py`). `validate` calls all four missions valid. Cause: steps = round((T - t0) / 60) can end up to 30 s after T; when that count is a multiple of 10 the last 10-min record is the final step, its time exceeds the last WRF hour, `inside()` is False and `_left_data` fails the member although the track is inside the box.
In the shipped q5 run: `emulator/design.json` v3 glider_eq (shift 8.83440 h: 8110 steps, ends T+3.9 s) and v5 glider_2n (shift 37.00706 h: 6420 steps, ends T+25.4 s) are the two skipped rows; the check against every other variant of `design.json` reproduces it exactly (end - T and step counts in the q5 file; skipped iff the count is a multiple of 10 and the end is past T). Its ledger note blames the location: "WRF U10: (-170.255, -0.360) at 2023-03-07 12:00Z is outside the ingested data (box (162.9, -162.905, -7.032, 7.071) ...)" while that point is well inside the box (only the time, by 3.9 s, is outside; the message prints minutes, so the time looks equal to the end).
why it matters: a legal deploy time with seconds (or a window end with seconds) turns a healthy vehicle into a 100 % failed one with no explanation but `left_data`; the emulator design silently loses rows and states a wrong reason. No test deploys at a non-whole-minute offset from `window.end`.

### B-2. The planner does not scale the UAS cost with the number or length of sorties, so `--budget` is not held for a mission with more flights
severity: major
lane: performance
where: cafe/pm/budget.py:326-341 (`_batch` uses `s_per_batch_day` x days for the UAS; `tasks` only enters the critical path), cafe/pm/budget.py:358-370 (`stage1_wall_s`), config/throughput.json (UAS cost measured with one 20 min sortie per day), cafe/pm/stage1.py:818-822 (`task_counts`)
reproduction: `rb.sh sh probes/p13.sh`. The demo mission with `sorties.every_days: 1` and with `every_days: 0.05` (20 sorties a day instead of 1), `CAFE_WORKERS=6`, quick budget: `uas tasks` 6 and 119, `plan["stage1_s"]` 52.7 s in both, `member_cost.uas.s_per_batch_day` 4.62 in both. A sortie costs about 4.6 s (4.62 s per batch-day at one sortie per day), so the second mission is about 20 times the UAS work (about 550 s per batch of work instead of 28 s) and the plan still says 53 s. `duration_min` (up to 120) is not in the cost either (the same plan for 20 and 120 min sorties).
why it matters: BRIEF 0.1 and the planner's own docstring ("Stage 1 never overruns its share ... `plan` refuses") rest on a stage-1 cost that is wrong by the sortie rate; a 30-day window with hourly sorties passes `plan` and overruns the whole budget.

### B-3. The report names `battery_capacity_scale` as what drives the UAS failures although 55 of 55 failures are `profile_incomplete`; the index is computed on the battery margin
severity: major
lane: honesty / statistics
where: cafe/pm/stage1.py:359 (`margin=... soc - reserve`, `margin_name="battery reserve margin"`), cafe/pm/stage1.py:658-700 and :710 (`_sensitivity` takes `margin` whenever it exists), cafe/pm/report.py:979 (`Top sensitivities (Sobol first-order, share of the variance of failure ...)`)
reproduction: q5 `stage1b/summary.json` summary.vehicles.uas: `modes` battery_reserve 6, profile_incomplete 55, `k_fail` 55; `sensitivity.quantity` "battery reserve margin", `param` battery_capacity_scale, S1 0.4678 (floor 0.1881). q5 `report/index.html` text for the UAS card: "Most sensitive to: battery_capacity_scale has the largest first-order index (S1 0.47) for the battery reserve margin ..." and, a few lines later, "What drives the failures: the first failure was by profile_incomplete ... Top sensitivities (Sobol first-order, share of the variance of failure, above the permutation noise floor): battery_capacity_scale 0.4678". `report.json` vehicles.uas.top3 = [battery_capacity_scale 0.4678].
why it matters: the failure is the 1200 s timer meeting the wind (72 % of flown sorties reach all 8 waypoints; the wind error that decides it is the unranked hourly stream), and the one prior the report points the lab at is the assumed +-5 % battery scale, which fixes no failure. The round-4 fix (M-1) added `profile_incomplete` but left the UAS sensitivity quantity on the battery; the sentence "share of the variance of failure" is wrong for every vehicle whose index is taken on a margin that is not the failure criterion.

### B-4. The CI workflow cannot demonstrate what the brief asks of it: the audit step fails (and stops the job) before `make ci` and `make broken`, and the job's 60 min limit is shorter than the suite it runs
severity: major
lane: reproducibility / documentation (BRIEF 0.3)
where: .github/workflows/premission.yml:9 (`timeout-minutes: 60`), :14-16 (`make audit` first, no `if: always()`), :17-22 (`make ci`, `make broken`); cafe/pm/audit.py:250-262 (`pytest ... --cov` over the whole suite) and :244-246 (`mutation_problems`)
reproduction: reading the workflow against the repo's own numbers: CLAUDE.md "The full suite takes about 75 min on 6 CPUs" (a hosted runner has 4); `make audit` runs `pytest -q -m "not network" --cov=cafe/pm` (audit.py:260) after ruff and mypy. Independently of time, `docs/mutation.json` does not exist, so `mutation_problems` fails the audit on every commit until code freeze, and a failed step ends the job: the steps "make ci" and "broken configuration must fail a receipt" never run. BRIEF 0.3 says the CI job demonstrates that a deliberately broken configuration fails.
why it matters: as committed the CI job is red on every commit and never reaches the step that is its evidence for exit condition 3; after the mutation record exists it still times out. The file was last edited 2026-10-28, before every round that changed what `make audit` and `make broken` do.

### B-5. The stage-1 worker count is capped by CPUs only; each worker is about 0.83 GB private before it touches the real environment, and the RUNBOOK wrapper sets neither `--cpus` nor `--memory`
severity: major
lane: performance (memory guard) / robustness
where: cafe/pm/par.py:41-56 (`workers()`: `CAFE_WORKERS`, else affinity mask cut to a cgroup `cpu.max` quota; nothing looks at memory), cafe/pm/pipeline.py:1227-1228 (`par.Pool(par.workers())`), docs/RUNBOOK.md step 1 (`pm()` has `--shm-size 16g` only; "8 cores and 32 GB RAM are the machine the quick budget is sized for")
reproduction: `rb.sh sh probes/p8.sh` (`probes/mem.py`): the CI mission with 3 workers (`par.Pool(3)`, `stage1.run`, batch 4); after the run each worker has VmRSS 840, 825 and 823 MB (parent 589 MB). With the demo's environment mapped in, a worker also holds its task's arrays. The same code on a 64-core host with the RUNBOOK wrapper starts `len(os.sched_getaffinity(0))` = 64 workers: at least 64 x 0.83 = 53 GB private plus the 9 GB shared environment and the parent, against the "32-96 GB GPU + 32-64 cores" lab server of BRIEF/QUESTIONS 6, with no memory figure. On a cgroup-v1 host `docker --cpus 2` leaves `/sys/fs/cgroup/cpu.max` absent (par.py:49-52), so `workers()` returns the host's CPU count regardless.
why it matters: BRIEF 5.6 lists the "memory guard" under performance. A kernel OOM kill of one worker is a `BrokenProcessPool` that aborts stage 1 with a traceback after the ingest; nothing in `plan` or `run` warns first.

## Minor

### B-6. `emulator_variants_within_share` cannot fail, and the emulator stage ran 49 % over its share without any check noticing
severity: minor
lane: honesty / performance
where: cafe/pm/pipeline.py:1124 (`len(variants) * est <= share`), cafe/pm/budget.py:304 (`n` = `min(cap, TRAIN_FRAC * share // est)`), cafe/pm/pipeline.py:1096-1107 (wall-clock kill checked only before a variant)
reproduction: `n_var <= 0.7 x share / est` by construction, so `len(variants) x est <= share` is always true (q5: 6 x 26.34 = 158.05 against 240). The same ledger's note: "measured 31, 36, 33, 72, 34, 73 s" = 279 s of variants against the planned 158 s (1.77x; the two 72-73 s variants are the B-1 reruns, one vehicle at a time), and `checkpoints/emulator/ledger.json` `wall_s` 358.5 s against the 240 s share (+49 %). Total q5 compute 562 s, so the 1200 s contract held; the check just does not measure it.
why it matters: BRIEF 5.5 says every self-check must be able to fail. The kill (`> share` before a variant) lets the last variant run to 279 s and the stage to 358 s.

### B-7. The certification sentence is printed for every vehicle, false for high P(fail), and self-contradictory for a zero-failure ensemble that already has 64 members
severity: minor
lane: honesty
where: cafe/pm/report.py:275-277 (`certify_statement` whenever `n < n_certify`), cafe/pm/stats/intervals.py:119-122 (`note` with `math.ceil(3 / level)`), cafe/pm/credibility.py:456-460 (Uncertainty counts every such verdict)
reproduction: q5 `report.json`: usv (60 of 64 failed, P(fail) 0.94) and uas (55 of 64) and glider_eq (15 of 64) each carry "P(fail) < 5 % cannot be certified at n = 64: 73 members (two-sided 95 % Wilson bound) are needed". No number of members certifies P(fail) < 5 % when the point estimate is 0.94. glider_2n (0 of 64): `note` "P(fail) < 3/n = 0.047 at 95% confidence, one-sided (n = 64); 60 members would be needed for that bound to reach 5%" - n is 64, the bound 3/64 = 0.0469 is already under 5 % by the sentence's own arithmetic. `credibility.json` Uncertainty: "8 verdict(s) have n below n_certify" counts the NO-GO and link verdicts too. (The sentence also says 59 elsewhere: `n_certify_one_sided()` 59 against `ceil(3/0.05)` 60.)
why it matters: M-18 of round 4 rewrote this sentence; it still tells the lab that more members would certify a P(fail) < 5 % that the data say is false.

### B-8. The planner's stage-1 time is 2.05 times low on the quick demo
severity: minor
lane: performance
where: cafe/pm/budget.py:358-370 (`stage1_wall_s`: the longest task or work / workers; nothing for the parent's serial part: link evaluation, `_left_data`, pickling, merge), plan.json `stage1_s`
reproduction: q5 `plan.json` `stage1_s` 52.68 against `checkpoints/stage1/ledger.json` note "64 members in 108 s" and `wall_s` 115.6 s, on the same 6 workers (2.05 and 2.19 times). Hand check of the formula: 2 batches x 26.3 s (USV, the longest task) = 52.6 s. `describe` prints "about 53 s on 6 worker(s)".
why it matters: the quick demo has 900 s of slack, but the same model sizes `n_max` on `4h` and `overnight` and the emulator variants (B-6: 26 s planned, 46.5 s measured on average).

### B-9. `rain_rate_nodes` does not "integrate to the accumulation" per hour and feeds the gust-front hours with half of the previous hour's rain
severity: minor
lane: physics / data (time)
where: cafe/pm/env/environment.py:49-54 (docstring and code), cafe/pm/stage1.py:207 (`rain = env._w("rain_mm_h", lo, la, hours)` at the hour starts), cafe/pm/env/subgrid.py:261-277 (`gust_fronts`: "hours are taken as starting at each entry of `times`")
reproduction: `accum = [0, 0, 6, 6, 6, 6]` mm at hourly nodes (one 6 mm hour between nodes 1 and 2). `rain_rate_nodes` returns [0, 3, 3, 0, 0, 0] mm/h; the trapezoid integral per hour is [1.5, 3.0, 1.5, 0, 0] mm against the true [0, 6, 0, 0, 0] (only the total, 6 mm, is conserved). `gust_fronts` draws events in hour [t_k, t_k + 1 h) from the value at t_k, which is the mean of the rates of hours k-1 and k, so half of an hour's rain drives events in the following hour and the peak is halved. Docstring: "puts an hour of rain at the middle of that hour" and "integrates to the accumulation" - both false per interval.
why it matters: M-16 (round 4) replaced a 30 min lag by a smear of the same size; the gust-front rate is concave in rain rate, so UAS gust-front timing and rate are off by up to an hour for isolated showers.

### B-10. A `station` task with `lon` and no `lat` crashes `validate`, `plan` and `run` with a KeyError traceback
severity: minor
lane: robustness
where: cafe/pm/config.py:211 (`pts.append((v["task"]["lon"], v["task"]["lat"]))`), :245-246 (the station check only tests `"lon" not in task`, though its message names lat); cafe/pm/__main__.py catches only `ConfigError` and `PlanError`
reproduction: `rb.sh sh probes/p3.sh` (first block): the demo mission with `lat` deleted from glider_eq's `task` -> `python -m cafe.pm validate --mission /tmp/nolat.yaml` ends in `KeyError: 'lat'` with a traceback (same for `plan`); `probes/p1.py` shows `CRASH station without lat KeyError 'lat'` from `config.load_mission`.
why it matters: RUNBOOK step 4 promises `validate` exits 2 with `error: ...` naming the field for a wrong file.

### B-11. The schema accepts NaN and infinity in numeric fields, and a NaN `required_fraction` silently fails the link in every member
severity: minor
lane: robustness
where: cafe/schemas/mission.json (`exclusiveMinimum`/`maximum` only; NaN passes every comparison), cafe/pm/stage1.py:601-606 (`evaluate_link`: `success=frac >= lk["required_fraction"]`)
reproduction: `probes/p1.py`: `required_fraction: .nan`, `dive_depth_m: .inf` -> `OK` from `load_mission`; `validate` prints "valid (4 vehicles, 4 links)" for `/tmp/nanreq.yaml`. `frac >= nan` is False for every member, so that link is p_fail = 1.0 NO-GO without a message; `becalmed_after_h: .nan` makes `acc >= nan` False and removes the failure mode; `heading_to: .nan` passes (min/max comparisons are False).
why it matters: BRIEF 5.6 lists NaN as a robustness input; here a typo disables a criterion or fails a link and the report calls it a verdict.

### B-12. `env.grid.interp` raises on an empty query, so an all-land box (or any zero-point request) ends ingest in a ValueError traceback
severity: minor
lane: robustness
where: cafe/pm/env/grid.py:64 (`.reshape(shape + (-1,))` with a zero in `shape`), reached from cafe/pm/pipeline.py:436-446 (`_ustar_agreement` with 0 sampled sea points) and :404-435 (`_spectrum_errors`)
reproduction: `rb.sh sh probes/p7.sh`: `interp(f, [Axis, Axis], [np.array([]), np.array([])])` -> `ValueError: cannot reshape array of size 0 into shape (0,newaxis)` (also for shape (0, 3)); with the CI cache's UMWM `seamask` set to 0, `python -m cafe.pm fetch --mission missions/ci_fixture.yaml` (offline) ends with that traceback from `pipeline._ustar_agreement`, not a named "no sea cells in the box" check.
why it matters: the same code before DECISIONS 269 had the same line, so this is old, but it is the crash a box with no sea gives and no test covers a zero-size query.

### B-13. A corrupt cache chunk, a corrupt store `zarr.json` and a run directory without `plan.json` end in raw tracebacks
severity: minor
lane: robustness
where: cafe/pm/env/environment.py:64-65 (`xr.open_zarr(...).load()` unguarded), cafe/pm/env/hycom.py (`open_store`), cafe/pm/__main__.py:166-175 (`_report` reads `plan.json` unguarded)
reproduction: `rb.sh sh probes/p6.sh` on a copy of the CI cache: (a) one `wrf.zarr/U10/c/...` chunk file truncated to 0 bytes -> `fetch` rc 1, `RuntimeError: Zstd decompression error: invalid input data`; (b) `ocean/gofs_ci_fixture.zarr/zarr.json` replaced by `{not json` -> `json.decoder.JSONDecodeError`; (c) `python -m cafe.pm report --run <dir with mission.yaml but no plan.json>` -> `FileNotFoundError: ... plan.json`. (A NaN in U10, a removed TAO manifest, a truncated TAO file and a negative `swh` are all caught by named ingest checks; those paths work.)
why it matters: BRIEF 5.6 "corrupt file": the message should name the file and the fix; RUNBOOK's table promises `error: ...` for exit 2.

### B-14. RUNBOOK says `--budget ci` on the demo mission "is refused by design"; it is not
severity: minor
lane: documentation
where: docs/RUNBOOK.md:74
reproduction: `rb.sh sh probes/p9.sh`: `python -m cafe.pm plan --mission missions/tepex_c_demo.yaml --budget ci` prints a 600 s plan (stage 3 "4 of 5 window part(s) are not run", "0 of 2 variants run") and exits 0; `pipeline.Context` has no check that refuses the pairing (grep "refus" in pipeline.py finds none for it).
why it matters: a lab user who tries it as the RUNBOOK says gets a plan or a run, not the refusal the text promises.

### B-15. Documents still quote numbers and conclusions from before the round-4 fixes
severity: minor
lane: documentation / honesty
where: QUESTIONS_FOR_LAB.md:99 and docs/PHYSICS.md:671 and docs/CREDIBILITY.md:137 (L18), docs/CREDIBILITY.md:136 (L17), CHANGELOG.md:289
reproduction: q5 `stage1b/summary.json` usv.speed: `ratio_median` 0.1287 and `ratio_anem_median` 0.1348; QUESTIONS 14, PHYSICS and CREDIBILITY L18 say "0.120 (anemometer height 0.125)" and "all three 0.120" (M-6 moved current-driven numbers by about 2 %, STATUS says so). CREDIBILITY.md L17 says "the demo UAS verdict is a battery verdict (M-28)"; in q5 battery_reserve is 6 of 55 failures and `profile_incomplete` is 55 of 55 (B-3). CHANGELOG.md:289 "The UAS verdict is a battery verdict below about 12 m/s of wind" is the same claim.
why it matters: the lab reads QUESTIONS_FOR_LAB first and is told the model's own ratio is 0.120 while the report shows 0.129; the UAS limitation row now describes the wrong failure.

### B-16. A link that is never required (for example `usv-uas-rf` when no sortie flew) is p_fail 0 and a GO badge in the headline table
severity: minor
lane: honesty
where: cafe/pm/stage1.py:600 (`frac = where(need.sum(0) > 0, ..., 1.0)` in `evaluate_link`, :530) and the `success` on the next line, cafe/pm/report.py:1135 vs :1389 (the `undecided: granularity` badge is on the card only)
reproduction: `probes/p2.py` ("wind 40": `AnalyticEnv(wind=(40, 0))`, M = 4): UAS `no_sortie_flown` 4 of 4, link `usv-uas-rf` k_fail 0 of 4 (also with NaN wind). The summary row has `need_count_median` 0 and `granularity_ok` False; the verdict is GO with p_fail 0 and the summary table (index.html "Verdicts") shows the plain verdict badge.
why it matters: "GO" for a link that never had a moment to fail sits next to a NO-GO UAS for the same cause.


total: 16 findings (0 critical, 5 major, 11 minor)
