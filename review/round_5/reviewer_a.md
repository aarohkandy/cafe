# Round 5, reviewer A: findings

Tree reviewed: `6d32946` (code identical to `d9878e4`/`09d54f3`). Everything was run at 1 to 3 CPUs in `~/work/cafe/pm_rev5_a` on homebase; the probe scripts are in
`/private/tmp/claude-501/-Users-aaroh--claude-spares-spare-P6utrU/96cd665b-6853-40e7-8769-780fbfcaeebd/scratchpad/rev5/probe/` (`p1.py` mission YAML edits, `p5.py`/`p9.py`/`p13.py` Stage-1 batches on the ci
environment, `p4.py` resume hash, `p2.py` planner, `w1.sh`/`w5.sh` CLI, `w4.sh` mutation of `par.workers`). Recomputed and found consistent (no finding): every Wilson interval and the
stopping interval in `report.json` for the 8 vehicles and links, the sum of assumed inputs (78 + 12 + 173 = 263, headline 261 without the 2 fitted), the test count (1,908 `def test_` in 48 files), ruff on
`cafe/pm` and `tests`, the TAO fit arithmetic (`persistent` = sqrt(max(between - sampling, 0) + between/k) reproduces 0.113 m/s), the first-failure UTC strings.

Order: major first.

### A-1. NaN and Inf pass `validate` in the mission YAML: a station radius or lost-after time of `.nan` makes a glider that never fails (silent GO); `every_days: .nan` crashes with a bare ValueError
severity: major
lane: robustness
where: cafe/schemas/mission.json (`"type": "number"` + `exclusiveMinimum`/`minimum` accept NaN and Inf: `nan <= 0` is False); cafe/pm/config.py:174-285 (`load_mission` has no finiteness check); cafe/pm/physics/glider.py:444-445 (`dist > station_tol_m`, `out_s > lost_hours * 3600`); cafe/pm/physics/usv.py:578-580 (`becalmed_after_h`, `track_tolerance_km`); cafe/pm/stage1.py:151-152 (`launch_times`)
reproduction: copy `missions/tepex_c_demo.yaml`, set one field to `.nan` (PyYAML writes/reads it as a float) and run `python -m cafe.pm validate`.
  `load_mission` returns normally (no ConfigError) for `radius_km`, `lost_after_h`, `dive_depth_m`, `track_tolerance_km`, `becalmed_after_h`, `heading_to`, links `required_fraction`, `box.pad_deg`, ship `antenna_height_m`, UAS
  `launch_rules.max_mean_wind_ms`, `altitudes_m: [.nan]`; `.inf` passes the same way. `sorties.every_days: .nan` (and `.inf`) raises `ValueError: cannot convert float NaN to integer` out of `launch_times`
  (not a ConfigError, so `python -m cafe.pm` prints a traceback).
  Through the real simulator (ci environment, 6 members, glider `glider_eq`, `stage1.run_batch`): `radius_km: 0.001` gives `station_lost` in 6 of 6; `radius_km: .nan` gives 0 of 6; `lost_after_h: .nan` (with radius 0.001) gives 0 of 6. The run
  would print GO for a station-keeping glider whose tolerance is unreadable.
why it matters: BRIEF 4.0 and 5.6 ask for "refuse, never guess" on NaN; a typo-class value turns the failure test off without a word, and the verdict is GO.

### A-2. A platform file with a required parameter missing, zero, negative or NaN loads, passes `hangar` ("provenance OK") and `validate`, and then crashes with KeyError or silently flies
severity: major
lane: robustness
where: cafe/pm/physics/glider.py:65-89 (`load_platform` checks the format of the leaves that exist, never that the needed ones exist or are physical; `usv.py` and `uas.py` loaders likewise); cafe/pm/config.py:120-135 (`_check_platform` relies on it); cafe/pm/pipeline.py hangar stage (`provenance_<platform>` check); glider.py:101-102 (`_mass`), :272
reproduction: copy `platforms/seaglider.yaml`, delete `params.mass_kg`.
  `python -m cafe.pm hangar --platform /tmp/x.yaml` exits 0 and lists the other values (provenance OK); a mission whose glider uses `platform: /tmp/x.yaml` gets `valid (4 vehicles, 3 links)` from `validate`.
  Stage 1 (`stage1.run_batch` on the ci environment) then raises `KeyError: 'mass_kg'` at glider.py:102, after ingest.
  With the value present but unphysical (drift glider, 6 members, same harness): `battery_J: .nan` -> fails `{}` and margin NaN (never a battery failure: silent GO); `mass_kg: .nan` -> `no_flight` 6/6; `mass_kg: 0` -> no failure, margin 0.992 (a zero-mass glider flies and is GO);
  `rating_m: .nan` -> `seafloor` 6/6; `battery_J: -1e7` -> `battery` 6/6 with margin 1.01. `reserve_frac: 1.5`, `length_m: 0`, `hd_b: -1` all load.
why it matters: BRIEF 5.6 names "a vehicle yaml missing mass" as an input that must give "a specific, actionable error naming the file, field and fix"; the hangar stage's "provenance OK" check cannot fail on it, so the ledger claims a check that does not test completeness.

### A-3. CI cannot go green: `make audit` runs the whole suite serially under a 60-minute job timeout
severity: major
lane: documentation (BRIEF 0.7 / 8: "CI config that runs make audit ... on every commit")
where: .github/workflows/premission.yml:9 (`timeout-minutes: 60`); cafe/pm/audit.py:260 (`pytest -q -m "not network" --cov=cafe/pm`, no `-n`); requirements-pm.txt (no pytest-xdist; `docker run cafe-pm python -c "import xdist"` -> `No module named 'xdist'`)
reproduction: HANDOFF.md section 4 records the full gate on homebase: "Serial: about 71 min" (31 min with xdist installed outside the image). The job also has to build both images first (RUNBOOK 1: "~25 min") and run `make ci` and `make broken` afterwards, so one job needs about 100 min of a 60-min allowance on a 4-vCPU GitHub runner that is slower than homebase.
  The step also fails for a second, stated reason (no `docs/mutation.json`), so the required check has no path to green before code freeze either way.
why it matters: the BRIEF requires the audit as a required check on every commit; as written the job is cancelled by the timeout, which hides every other failure behind it.

### A-4. A mission that omits `environment.subgrid` flies the UAS with no turbulence and no gust fronts, and neither the report nor the RUNBOOK says so
severity: major
lane: honesty / physics default
where: cafe/pm/stage1.py:188-191 and :204 (`sw.get("turbulence")`, `sw.get("gust_fronts")`: off unless true); cafe/pm/env/subgrid.py:355-358 (`switch`: warm_layer, rain_lens, ocean_sde default on, "turbulence and gust_fronts ... off unless true"); DECISIONS.md row 103; cafe/schemas/mission.json (`subgrid` optional); cafe/pm/report.py and credibility.py (no mention of either switch: `grep -n "turbulence\|gust_fronts" cafe/pm/report.py` finds only the sensitivity-scope sentence)
reproduction: ci environment, UAS only, 16 members, `stage1.run_batch`: with the fixture's `subgrid: {turbulence: true, gust_fronts: true, ...}` the batch's random streams are `['uas/gust', 'uas/turb/0', 'uas/turb/1']`; with the `subgrid` key removed (still schema-valid) the streams drawn are `[]`
  (failed 10/16 against 9/16 in this synthetic wind; the real wind and the demo's gust-front windows are where it matters).
  RUNBOOK 4 describes what `validate` enforces and never mentions the key; the demo mission sets all five switches explicitly, so a lab user who copies the RUNBOOK's description and writes a smaller mission gets a laminar UAS.
why it matters: BRIEF 2.2 makes the synthetic sub-grid layer "what Stage 1 uses on every machine" and BRIEF 6 expects "UAS NO-GO in any gust-front window"; BRIEF 4.1 asks for default-on with a "modelled" badge. A default-off model with no report line gives optimistic UAS verdicts that look like ordinary ones.

### A-5. The resume hash omits the worker count although the plan depends on it, so a resume under another CPU count mixes plans; the reproducibility claims in RUNBOOK 5 and STATUS 1 are false across CPU counts
severity: major
lane: reproducibility
where: cafe/pm/pipeline.py:116 (`self.hash = digest(dict(mission, budget, gpus, code))`: no plan, no workers); cafe/pm/budget.py:plan (`W = par.workers()` sets `stage1_s`, `tasks` and, through `emulator_plan`, the number of variants); docs/RUNBOOK.md ("`--seed S` ... same seed + same machine bench = the same `report.json`"); STATUS.md section 1 ("The result does not depend on the worker count"); cafe/pm/ledger.py:73-77 (`machine()` records `os.cpu_count()`, not the workers)
reproduction: `Context("missions/tepex_c_demo.yaml", "quick", 0, dir)` with `CAFE_WORKERS=1` and `=8` (p4.py): both have `hash` 7b106f4f...e93 (equal), `plan["workers"]` 1 and 8, `stage1_s` 200.6 and 26.3, emulator variants (`variants_no_refit`) 1 and 6.
  `python -m cafe.pm plan` at W = 1, 2, 4, 8 gives 0/1, 0/3, 1/6, 1/6 variants at quick, and at overnight `trains` False for W < 4 and True for W >= 4 (p2.py).
  So (1) a run interrupted after stage 1 under `--cpus 8` and resumed under `--cpus 2` skips stage 1 as "up to date" and runs the emulator with a different plan, while `plan.json` is rewritten to the new one (`pipeline.py:1224`), and (2) two runs of the same command with the same seed on the same machine at different `--cpus` write different emulator, flip-search and what-if content.
  The STATUS evidence (same `stage1/res.pkl` sha-256 on 1 and 8 workers) is about stage 1 only; the same paragraph's own table lists 1 against 6 emulator variants.
why it matters: acceptance's same-seed gate and the lab's "same seed gives the same report" only hold at a fixed CPU quota; the docs promise more.

### A-6. No memory model: a 30-day window (a BRIEF 5.6 robustness input) passes validate and plan and then needs about 45 GB of environment against a 16 GB /dev/shm and a 28 GB container
severity: major
lane: performance / robustness
where: cafe/pm/budget.py:plan (time model only; no RAM term); cafe/pm/par.py:24, :78-86 (`SHM_MIN_FREE` is checked once, when the first file is created; later `np.save` calls into the same directory are not checked); cafe/pm/env/ocean.py:46-57 (`__getstate__` reads every HYCOM field whole); docs/RUNBOOK.md step 4 ("`fetch` ... works for a 30-day or 20-vehicle mission that only fits a larger budget")
reproduction (reasoned, not run: a 30-day ingest is days of network): DECISIONS 267 and 270 give the 6-day demo environment as 2.9 GB of WRF + UMWM plus 1.2 GB per HYCOM field, "about 9 GB with the five". All of it is linear in the window (hourly files, 3-hourly GOFS), and the pad grows from the demo's `pad_deg: 2.0` to 10 deg without `pad_deg` (RUNBOOK 5). 30 days is at least 5 x 9 = 45 GB.
  `budget.plan("quick"/"4h", ...)` on a 30-day copy of the demo returns normally (n_max 32 at quick, p1.py), `validate` passes, and neither refuses. In `adopt` the shm directory is chosen once; the 16 GB fills part-way and `np.save` raises `OSError: [Errno 28]` in the middle of `Context.env`, after the ingest; with one worker the same arrays do not fit the 28 GB container.
why it matters: "refuse, never guess" and BRIEF 3's memory guard (written for GPUs) have no CPU counterpart; the failure comes hours into a run with an OS error.

### A-7. The RUNBOOK's first what-if example, word for word, fails on the demo mission
severity: minor
lane: documentation
where: docs/RUNBOOK.md step 5 (`pm python -m cafe.pm whatif --mission missions/tepex_c_demo.yaml --run runs/quick --shift 48h`); cafe/pm/whatif.py:106-108 (`apply` raises `Invalid` for a UAS shift of a whole number of days); cafe/pm/__main__.py:231 (`_whatif`); BRIEF 2.9 / 4.0 (the "one command" `cafe whatif --mission ... --shift 48h`)
reproduction: `python -m cafe.pm whatif --mission missions/tepex_c_demo.yaml --run <the q5 run> --shift 48h` prints `error: uas: launching +48 h later is a whole number of days, the same launch time of day: nothing changes` and answers nothing for the gliders and the USV (w5.sh). The RUNBOOK documents the refusal in the next paragraph but the example before it is the failing command; the user must already know to add `--vehicle usv`.
why it matters: the canonical example of the feature the brief calls "pre-solving the next problem" aborts instead of answering the vehicles it can and naming the UAS as unchanged.

### A-8. The planner's stage-1 estimate is 2.05 x low in the evidence run, and the emulator check that guards its share compares the plan with itself
severity: minor
lane: performance / honesty
where: cafe/pm/budget.py:stage1_wall_s/batch_cost_s; cafe/pm/pipeline.py:1124 (`emulator_variants_within_share`: `len(variants) * est <= share`, "planned cost of the variant runs"); cafe/pm/pipeline.py:1096-1103 (kill test only at the start of a variant)
reproduction: q5 `plan.json`: `stage1_s` 52.7 s ("about 53 s on 6 worker(s)", printed in the report's machine block); q5 stage-1 ledger note "64 members in 108 s", `wall_s` 115.6 -> 2.05 x. q5 emulator ledger: 6 variants planned at 26 s (158 s), measured 31, 36, 33, 72, 34, 73 s = 279 s, share 240 s; check `emulator_variants_within_share` value 158, limit 240, ok true. Emulator stage `wall_s` 358.5 s plus stage 1b 31.1 s = 389.6 s against the 240 s share (1.6 x). The whole run still took 9.4 min of 20, so nothing failed; the numbers the report prints as "planned against" are not the ones that held.
why it matters: BRIEF 3 says the report prints the measured numbers it planned against; at `ci` (600 s) or on a larger fleet a 2 x miss decides whether a stage is cut.

### A-9. "Top sensitivities" is labelled "share of the variance of failure" for indices computed on a continuous margin, and the one reported driver is inside the Monte-Carlo noise of its own floor
severity: minor
lane: statistics / honesty
where: cafe/pm/report.py:979 (label); cafe/pm/stats/sensitivity.py:noise_floor (`perms=200`, `seed=0`); cafe/pm/stage1.py:_sensitivity
reproduction: q5 `report/index.html`, glider_eq: "Most sensitive to: current_speed_scale has the largest first-order index (S1 0.12) for the maximum distance from the station, above the 0.12 that unrelated outcomes reach" (S1 0.1239, floor 0.1188) and, two paragraphs on, "Top sensitivities (Sobol first-order, share of the variance of failure ...)": the quantity is the maximum distance, not failure.
  Recomputed from `runs/q5/stage1b/res.pkl` (p6.py): S1 values reproduce (0.1239); the floor with `seed` 0..29 has mean 0.1164, sd 0.0058, range 0.107 to 0.128; 3 of 30 seeds give a floor at or above S1_max, so the "above the floor" statement flips on the seed of the permutation test; 5,000 permutations give 0.1176. Eight such tests run per report (4 vehicles, 4 links) at the 95 % level.
why it matters: a driver reported at 0.005 above a floor whose own noise is 0.006 is presented as a finding; the rounded text reads "0.12 above 0.12".

### A-10. The only test of `par.workers()` cannot see the cgroup quota branch that stops `--cpus` from being oversubscribed
severity: minor
lane: tests
where: cafe/pm/par.py:49-52; tests/test_par.py `test_workers_is_the_environment_override_or_the_cpus_and_one_inside_a_pool` (asserts only `1 <= par.workers() <= len(sched_getaffinity)`)
reproduction: in a container started with `--cpus 2` (affinity 8, `/sys/fs/cgroup/cpu.max` = `200000 100000`) `par.workers()` is 2. Changing `int(quota) // int(period)` to `int(quota) * int(period)` makes it 8, and the test passes (w4.sh, `pytest_rc=0`). STATUS.md lists `par.py:50-51` among the uncovered lines, so no test reaches the arithmetic either.
why it matters: DECISIONS 266's cut to `docker --cpus` is the difference between a quiet shared box and 8 workers on a 2-CPU quota; a wrong operator or a fractional quota (`--cpus 1.5`) would ship untested.

### A-11. RUNBOOK says `--budget ci` on the demo mission "is refused by design"; nothing refuses it
severity: minor
lane: documentation
where: docs/RUNBOOK.md step 3 ("`--budget ci` on the demo mission is refused by design; `ci` is for `missions/ci_fixture.yaml`"); cafe/pm/budget.py, pipeline.py (no such check; `grep -rn ci_fixture cafe/pm` is empty)
reproduction: `python -m cafe.pm plan --mission missions/tepex_c_demo.yaml --budget ci --gpus 0` prints a plan ("stage 1: 8..16 members in batches of 16 ... about 90 s", exit 0), and `run` builds the same plan in `Context.__init__`.
why it matters: a stated guard that does not exist; a lab user who tries it gets a toy-size run on the real data, labelled as a ci run, instead of the promised refusal.

### A-12. Bellhop is not installed by `make install` or mentioned in the RUNBOOK, so a clean install silently runs the acoustic links Thorp-only
severity: minor
lane: documentation / data
where: Dockerfile, Dockerfile.pm (no Bellhop); bench/install_bellhop.sh (homebase only, writes `~/work/cafe/pmdata/bin`); cafe/pm/physics/comms.py:257-265 (`_bellhop_dir` looks in `$CAFE_DATA/bin` then PATH); docs/RUNBOOK.md and STATUS.md (no mention: `grep -in bellhop docs/RUNBOOK.md README.md STATUS.md` is empty)
reproduction: follow RUNBOOK 1 on a clean machine: `comms.bellhop_available()` is False, `acoustic_link` labels ambiguous links "Thorp only, Bellhop unavailable", and the Bellhop-vs-Thorp receipt is a "NOT RUN" context row (comms.py:399-401). On homebase Bellhop is present only because `/data/bin/bellhop.exe` was built by hand, and a 457-ambiguous-sample call then takes 0.4 s (p12.py).
why it matters: BRIEF 2.8 makes Bellhop the automatic high-fidelity path for every ambiguous acoustic link; the demo's acoustic links are 555 and 633 km long so q5 never exercises it, and the lab's own near-ship links would.

### A-13. The free-surface hull window is planned on a fixed 6 MPI ranks whatever the machine has
severity: minor
lane: performance
where: cafe/pm/stage3/freesurface.py:110-112 (`nproc()` = `CAFE_NPROC`, default "6"); cafe/pm/budget.py:fs_plan
reproduction: the ci run of a USV-only mission in a container with `--cpus 1` logs "free-surface window not run: estimated 94 min x 1.25 margin = 118 min (279,060 cells on two grids, 2000 iterations, 6 cores at 153k cell-updates/s)". With 1 CPU the estimate is wrong by about 6 x; on a 32-core lab server the same run uses 6 cores.
why it matters: BRIEF 0.1 "the same command adapts to the lab server without code changes"; the plan's `fit` count and the window's kill are both set from this rate.

### A-14. The report states the verdict thresholds with the boundaries swapped
severity: minor
lane: documentation
where: cafe/pm/report.py:954 ("GO below 0.1, NO-GO from 0.4"); cafe/pm/stats/intervals.py:verdict_from_p, `_at_least`
reproduction: `intervals.verdict` logic replicated: 10 failures of 100 (P(fail) = 0.10) is GO and 40 of 100 (0.40) is MARGINAL; 41 of 100 is NO-GO. The text says GO is "below 0.1" and NO-GO is "from 0.4".
why it matters: at an exact tie (n a multiple of 10) the printed rule and the verdict disagree; the intervals.py docstring and the mission file (`go: 0.9` is "P(success) >= go") say the opposite of the report.

### A-15. `CAFE_WORKERS` with a non-integer value is an uncaught ValueError, and the ledger records the host CPU count, not the workers used
severity: minor
lane: robustness / reproducibility
where: cafe/pm/par.py:46-47 (`int(os.environ["CAFE_WORKERS"])`); cafe/pm/__main__.py:main (catches only ConfigError, PlanError, StageFailed); cafe/pm/ledger.py:73-77
reproduction: `CAFE_WORKERS=abc` and `=2.5`, `=1e1` all raise `ValueError: invalid literal for int()` out of `Context.__init__` (p10.py); `0` and `-3` are silently 1. q5's ledgers say `"cpus": 8` while `plan.json` says `workers: 6` (the container had `--cpus 6`); no ledger names the worker count that sized the plan.
why it matters: the one knob RUNBOOK 1 documents for the pool gives a traceback; the ledger cannot show what a result was sized on (see A-5).

### A-16. Odd but valid YAML is accepted without a word: duplicate keys keep the last, and a leading-zero number is octal
severity: minor
lane: robustness
where: cafe/pm/config.py:30-37 (`yaml.safe_load`); cafe/schemas/mission.json (cannot see duplicates)
reproduction: `yaml.safe_load("seed: 1\nseed: 2\nverdict: {go: 0.9, nogo: 0.6}\nverdict: {go: 0.5, nogo: 0.1}")` -> `{'seed': 2, 'verdict': {'go': 0.5, 'nogo': 0.1}}`; `seed: 010` -> 8. A mission with two `task:` or two `verdict:` blocks (a bad paste) validates and runs on the second.
why it matters: the verdict thresholds and the seed decide what the report says and which run it is; "refuse, never guess".

### A-17. The fitted persistent wind prior (0.113 m/s) rests on a moment estimate that is floored at zero by a noise term as large as the quantity, and it replaces the literature value 2.0 m/s
severity: minor
lane: statistics
where: cafe/pm/pipeline.py:543-566 (`fit_wind_error`), :592-613; q5 `ingest/priors_fitted.json`, `tao_compare.json`
reproduction: from `tao_compare.json` the 11 mooring time-mean speed errors give `between` = var(means) = 0.141 (sd 0.375); the sampling variance of a mooring mean at s^2 = 1.65, n = 145, rho = 0.86 is s^2/n (1+rho)/(1-rho) = 0.151, so `between - sampling` < 0 and the true site-to-site spread is set to 0; what remains is `between/k` = 0.0128, sd 0.113 m/s. With 11 moorings and one 6-day westerly-burst regime the data cannot exclude a persistent spread of several tenths of a m/s; the point estimate 0 is used as if known, and any regime-to-regime bias outside 2023-03-01..07 is not in the ensemble at all (the hourly AR(1) noise, sd 1.28 m/s, tau 6.4 h, is all that is left).
  The report's only uncertainty on P(fail) is the Wilson interval for the member count (`p_fail.uncertainty`), so the narrowed prior shows up as confidence.
why it matters: BRIEF 5.2 says the fitted numbers replace the literature wind prior; replacing it by a boundary estimate from one regime is a statistician's first objection, and the credibility report does not name it.

total: 17 findings (0 critical, 6 major, 11 minor)
