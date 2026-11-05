# Round 9, reviewer A (commit `08f05d7`; the repo at `c1dd8cd` differs only by the prompt file)

Method: every claim below was run or recomputed. Scratch work was on the burst VM at 2 CPUs from a detached worktree (`PM_HOST=cafe-burst PMX=pm_rev9_a*`); the worktree, the `pm_rev9_a*` directories and the `rev9a_*` logs were removed at the end. Mutants were applied only inside those scratch copies. Nothing in the repo was edited. Orca was not touched.

### A-1. A `platform:` given as a path passes `validate` and then `run` stops in the hangar stage
severity: major
lane: robustness / documentation
where: cafe/pm/pipeline.py:953-958 (`p = PLATFORMS / f"{v['platform']}.yaml"`; `L.input(p)`; `_assumed(_yaml(p))`); cafe/pm/config.py:`load_platform` (accepts a path); cafe/schemas/mission.json (`platform`: "name of a file platforms/<name>.yaml, or a path to one")
reproduction: take `missions/ci_fixture.yaml`, keep one glider, set `platform: platforms/seaglider.yaml`, drop the ship, shore and links, name it `rev9_path`. `python -m cafe.pm validate --mission m.yaml` prints `valid (1 vehicle, 0 links)`. Build the synthetic env (`python -m tests.fixtures.ci_env.make D m.yaml`) and `CAFE_DATA=D CAFE_OFFLINE=1 python -m cafe.pm run --mission m.yaml --budget ci --gpus 0 --out O --fresh`: ingest finishes ("ingest: done in 3 s"), then `error: /app/platforms/platforms/seaglider.yaml.yaml: file not found`. `python -m cafe.pm hangar --platform platforms/seaglider.yaml` accepts the same path and works, so the three entry points disagree. An absolute path fails the same way (`PLATFORMS / "/abs/x.yaml"` becomes `/abs/x.yaml.yaml`).
why it matters: the lab's own datasheet file is exactly what will be passed as a path (RUNBOOK 3 says `validate` finds a wrong file "here and not hours into a run"). The failure comes after the multi-hour fetch, and if it were patched in place the provenance input `L.input(p)` would still point at a file that does not exist and so carry no hash, so an edited lab platform file would not invalidate a resume.

### A-2. A YAML alias between two vehicles makes `whatif` move or shift both (and double-applies a change asked for both)
severity: major
lane: robustness / correctness
where: cafe/pm/whatif.py:97-144 (`apply` edits `v["deploy"]`, `v["task"]` in place on a `copy.deepcopy`, which keeps shared references); cafe/pm/config.py:`_yaml`/`load_mission` (aliases are accepted and never unshared); the emulator variants (`whatif` training design) and `flip_search` call `apply` too
reproduction: in `missions/tepex_c_demo.yaml` write `deploy: &d {...glider_eq's...}` and `deploy: *d` for glider_2n (valid YAML; `load_mission` accepts it). `whatif.apply(m, {'glider_eq': {'dlon': -0.5, 'shift_h': 3.0}})` gives glider_eq and glider_2n both `{'time': '2023-03-01T15:00:00Z', 'lon': -170.5}`. `whatif.apply(m, {'glider_eq': {'dlon': -1.0}, 'glider_2n': {'dlon': -1.0}})` gives lon -172.0 for both (expected -171.0 each). The same holds for an aliased `task` (duty edits `dive_depth_m` once per vehicle). Anchors are the natural way to write a 20-vehicle mission.
why it matters: a what-if answer, a "what would fix it" line and the emulator's training rows are for a mission that is not the one described; nothing says so. One `json.loads(json.dumps(m))` after validation in `load_mission` removes the sharing.

### A-3. The USV speed sanity row compares speed over ground per 10 m wind with a calibration ratio defined per anemometer-height wind
severity: minor
lane: honesty / physics
where: cafe/pm/report.py:462-470 and :1155-1158 (`_speed_ratio` takes `ratio_median`, printed as "mean 10 m wind"); cafe/pm/stage1.py:807-815 (`_speed`: `ratio_median` is /u10, `ratio_anem_median` is /anemometer wind); platforms/saildrone_explorer.yaml:71 (`chiodi_mean_wind_ms`: "taken at the anemometer height")
reproduction: q9 `stage1b/summary.json` `vehicles.usv.speed`: `ratio_median` 0.1287 (SOG / 10 m wind), `ratio_anem_median` 0.1348, `calibration_ratio` 0.1778. The report (sanity row for `usv`, and the USV section) prints "0.129 ... against Chiodi et al.'s 0.178", a 27.5 % shortfall; the like-for-like number already in the summary is 0.135, a 24.3 % shortfall. The estimators also differ (median of per-member ratios against Chiodi's ratio of means; the quotient of the two medians is 0.6747 / 5.319 = 0.127).
why it matters: the one sentence that tells the reader how far the NO-GO USV verdict rests on a calibration that the mission does not reproduce overstates the gap by about 3 points because the two numbers are at different heights.

### A-4. The overrun factors the RUNBOOK and DECISIONS give for the planner are contradicted by the reviewed run
severity: minor
lane: performance / documentation
where: docs/RUNBOOK.md step 4 ("q8 ran 2.2 times over it (52.7 s planned, 117 s measured ...) ... above about 45 % of the share can overrun it, and the emulator stage ran 12 % over its share (270 s of 240 s)"); DECISIONS.md row 444; cafe/pm/budget.py (plan)
reproduction: q9 `report.json` `machine.timing` and `checkpoints/*/ledger.json`: stage 1 planned 52.68 s, measured 223.05 s (4.23 times, not 2.2); the emulator stage `wall_s` 492.85 s against its 240 s share (2.05 times; the variant runs alone were 282.98 s against 105.4 s planned, 2.7 times, and the planner's own kill left 4 of the 6 planned variants). With 4.2 times the "about 45 %" becomes about 24 %. `plan --mission 30-day-copy-of-the-demo --budget quick` with enough memory (200 GB, 6 CPUs) is accepted as "stage 1 ... about 263 s"; at the measured factor that is about 1,110 s against a 900 s stage-1 share and a 1,200 s budget. The demo itself still holds (compute stages sum to 797 s of 1,200 s).
why it matters: the figures a lab user is told to size a mission by are out of date by a factor of two, and the planner admits missions that, at the measured ratio, cannot finish in the budget. (Part of the gap may be the machine, see A-5; the document does not say so.)

### A-5. The planner uses `config/throughput.json` from another machine without a word
severity: minor
lane: performance / reproducibility
where: cafe/pm/budget.py:94-109 (`measurement_warnings` checks only load and mission name); cafe/pm/ledger.py:`machine`; config/throughput.json `machine` (`id: homebase`, 8 CPUs, EPYC 9V45)
reproduction: the q9 ledgers record `machine.host: cafetest`, `cpus: 32`, `workers: 6`, `bench_id: homebase`; `python -m cafe.pm plan --mission missions/tepex_c_demo.yaml --budget quick --gpus 0` on the burst VM prints the costs as "measured (2026-11-01, homebase, load 1.40...)" and no warning. RUNBOOK 4 says a stale or loaded measurement makes the plan wrong and that `make bench` is per machine.
why it matters: the plan, `n_max` and the emulator variant count are all sized from another CPU's rates; the only trace is `bench_id` in a ledger.

### A-6. The report's emulator section states the plan, not what ran
severity: minor
lane: honesty
where: report.json `emulator.plan_note` (cafe/pm/budget.py `emulator_plan`) shown in report/index.html "Emulator"; checkpoints/emulator/ledger.json `notes`; emulator/design.json
reproduction: the HTML says "this budget gives 7 distinct points per vehicle class in one run (6 variants of 26 s + the base mission ...)". The same run's ledger says "killed: the variant runs spent the emulator stage's whole wall-clock share (240 s) before variant v4 of 6" and "20 added by this run: 4 vehicles x 5 missions", `design.json` `variants` 4 and measured 71, 80, 61, 70 s against 26 s. So the run produced 5 points, not 7, and each variant cost 2.7 times the printed 26 s.
why it matters: a reader of the report takes the 7 and the 26 s as facts about this run.

### A-7. `--gpu-mem-gb` accepts nan, inf and negative numbers
severity: minor
lane: robustness
where: cafe/pm/__main__.py:51 (`type=float`), cafe/pm/budget.py:347-349 (`int(GPU_MEM_GUARD * gpu_mem_gb * 1e9 / LES_BYTES_PER_CELL)`), :390 (`if les.get("gpu_mem_gb")`), :484-491 (`memory_guard`)
reproduction: `python -m cafe.pm plan --mission missions/ci_fixture.yaml --budget quick --gpus 1 --assume-gpu --gpu-mem-gb nan` ends in a traceback `ValueError: cannot convert float NaN to integer` (budget.py:349); `inf` is an OverflowError by the same line; `-5` and `0` are accepted and the plan prints a normal GPU window plan (a zero is "no guard", a negative is a guard of negative size, `memory_guard` would take a cube root of a negative number).
why it matters: BRIEF 2.9 "memory guard: refuse a configuration that would exceed 85 % of GPU memory and say what to reduce"; a nonsense size should be refused by name.

### A-8. `run --mission <run dir>/mission.yaml --out <run dir>` is a traceback
severity: minor
lane: robustness
where: cafe/pm/pipeline.py:1475 (`shutil.copy(ctx.mission_path, ctx.path("mission.yaml"))`)
reproduction: `mkdir rd && cp missions/ci_fixture.yaml rd/mission.yaml && CAFE_OFFLINE=1 python -m cafe.pm run --mission rd/mission.yaml --out rd --budget ci --gpus 0` ends `shutil.SameFileError: PosixPath('rd/mission.yaml') and PosixPath('rd/mission.yaml') are the same file`, exit 1 with no `error:` line. The RUNBOOK tells the user that `whatif` compares `--mission` with `runs/quick/mission.yaml`, so naming that file to rerun a run is a natural step.
why it matters: "degrade, never crash"; a user retrying a run from its own copy of the mission gets a Python traceback.

### A-9. A USV `section` whose two waypoints are the same point is accepted and can never be "swept off track"
severity: minor
lane: physics / robustness
where: cafe/pm/config.py (`len(waypoints) < 2` is the only check); cafe/pm/physics/usv.py:523-536 (`_geom`: a zero-length leg gives `ul = 0`, `nl = 0`, cross-track error 0)
reproduction: `USVSim` on `AnalyticEnv(wind=(4,0), current=(1.5,0))` (a current above the boat's speed), 4 members, 24 h, start (-165, 0), `track_tolerance_km` 20: waypoints `[[-165,0],[-165,0]]` give fails `{becalmed: 4}`, `xte_max` 0 km, 112.6 km from the start; the same point as `mode: station` gives `{becalmed: 4, swept_off_track: 4}`, `xte_max` 112.6 km; a real N-S section gives swept_off_track as well.
why it matters: the mission schema's own error for one waypoint says "at least two"; two equal ones silently switch off the track test, and a USV that drifts away on a current weaker than its speed (not becalmed) would pass.

### A-10. User-facing report text with raw Python
severity: minor
lane: documentation
where: cafe/pm/report.py:1197 (`e(str(v['dominant_mode']))`), cafe/pm/whatif.py:136 (the `Invalid` message `... outside the mission box {m['box']}`, shown in the what-if table)
reproduction: q9 report/index.html for `glider_2n` (no failure): "Dominant failure mode: None (all modes: ...)". The what-if table rows read "usv: moving (+0.5, +0) deg puts (-164.50, -1.00) outside the mission box {'lon_min': 165.0, 'lon_max': -165.0, 'lat_min': -5.0, 'lat_max': 5.0, 'pad_deg': 2.0}".
why it matters: a dict repr and a bare `None` in the sentence a PI reads.

### A-11. Tests that pass on broken code: the current-direction error field and the 20 % u* tolerance
severity: minor
lane: tests
where: cafe/pm/env/perturb.py:181 (`rot = (...) + self.cd / np.sqrt(2.0) * self.fd(lonb, latb)`); tests/test_perturb.py:54-59 (`test_current_spread_matches_prior` checks the speed field only); cafe/pm/pipeline.py:654 (`float(np.mean(r <= 0.2))` in `_ustar_agreement`); tests/test_pipeline.py:2246-2254
reproduction: (1) in a scratch copy change `self.cd / np.sqrt(2.0) * self.fd` to `self.cd * self.fd` (the random part of the direction error then has 1.22 times the prior sd instead of 1.0): `pytest tests/test_perturb.py tests/test_perturb_env.py` gives 33 passed. Every other `PerturbedEnv` test sets `current_direction_bias` to 0 or passes no draws (test_usv.py:506, test_glider.py:280); the speed twin of the mutant fails at once. I did not complete a run of the other test files with this mutant (it was stopped after more than 20 minutes at 2 CPUs); a grep finds no test that measures the spread of the direction error. (2) change `r <= 0.2` to `r <= 0.5` in `_ustar_agreement`: `pytest tests/test_pipeline.py -k "ustar or coare"` gives 7 passed, because `test_coare_ustar_is_compared_with_umwm_ust_and_the_agreement_is_logged` asserts only `0 <= frac <= 1`.
why it matters: the sd of the current direction error is a stated BRIEF 2.5 prior that feeds every glider and USV verdict, and the 20 % band is BRIEF 2.1's acceptance rule that sets Data pedigree; neither can fail.

total: 11 findings (0 critical, 2 major, 9 minor)
