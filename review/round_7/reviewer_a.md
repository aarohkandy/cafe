# Reviewer A, round 7: findings on commit c59c449 (q7 run at 8dc0ffc)

Method notes. Recomputed from the q7 ledgers: every vehicle and link verdict (k, n, 90 % and 95 % Wilson, GO / MARGINAL / NO-GO rule), `n_certify` = 73, the planner's 52.68 s stage-1 figure (2 waves x 26.3 s), the DTMB V&V ratios, the HYCOM "in-situ" claim (the live `.das` of GLBy0.08/expt_93.0 says `comment "in-situ temperature"`, so that claim is right). All matched; no finding there.
Ran on homebase at 1 CPU in `pm_rev7_a`: 50 hostile mission edits through `load_mission` + `budget.plan`, and `stage1.run_batch` (4 members) on the CI fixture environment with zero wind, NaN patches, 60 m/s wind, Hs 15 m, 20 vehicles, zero-length USV section, glider on the box corner, corrupt zarr stores. Those inputs were handled; the defects below are what did not hold.
Tried and dropped (not findings): row-level cal/train split in `Emulator.fit` with replicated points (24-seed experiment: coverage on new points 0.918 with no replicates, 0.934 with 3 replicates, so no harm shown); COARE 3.5 against the Edson 2013 / NOAA reference structure (psi functions, cool skin, gustiness, warm layer): consistent; Kerr cubic, Thorp, Stojanovic: consistent; Breivik 2016 Stokes profile and transport: consistent; Hou 1996 Smagorinsky, regularised collision, Bouzidi: consistent.

### A-1. The emulator's training design collapses to the base mission for every draw that moves east on a box-edge vehicle, and replicate missions are counted as distinct feature points
severity: major
lane: statistics / honesty
where: cafe/pm/whatif.py:340-351 (`_fits`), 353-373 (`design`), 402 (`points = ... round(9).drop_duplicates()`), cafe/pm/emulator.py:260 (hold-out split by `round(9)`); demo mission ship and USV waypoints at lon -165 = `box.lon_max`
reproduction: in the demo the ship (UAS base) and the USV section sit at lon -165.0, exactly the box's `lon_max`, so any `dlon > 0` fails `apply` with `Invalid` ("moving ... outside the mission box"). `_fits` halves the move 4 times (still east, still outside) and then returns `dict(shift_h=0, dlon=0, dlat=0, duty=1)`, which throws away the shift and the duty as well, though only the move was invalid. The LHS for seeds `20230301 + i` (`scipy.stats.qmc.LatinHypercube(d=4, seed=...)`, i = index of the vehicle, n = 6) gives dlon draws uas [+0.593, +0.934, -0.582, -0.303, +0.305, -0.682] and usv [-0.517, -0.093, +0.175, +0.984, -0.999, +0.348]. `q7/emulator/design.json` shows exactly the positive ones reverted to all zero: uas v0, v1, v4 and usv v2, v3, v5 are `{shift_h: 0, dlon: 0, dlat: 0, duty: 1}`; the negative ones are intact. So 3 of the 6 variants of the UAS and of the USV are the base mission again. `q7/emulator/holdout.json` then reports usv `rows 7, points 7` (the four copies of one mission differ only in the median-track environment features of different member draws, so `round(9)` counts them as four points) and uas `rows 7, points 4`. The UAS features are deterministic, so there the copies do collapse.
why it matters: the "distinct points" gate (100 per class, never lowered) and the hold-out split by point are the emulator's only guard against leakage; the USV count is inflated by replicates of one mission, the same replicates can fall on both sides of the hold-out, and the plan's "N distinct points per class in one run" is wrong for any vehicle on a box edge (the UAS gets 4, not 7). Accumulating rows over seeds (RUNBOOK 5) needs about twice the runs the arithmetic in `emulator_plan` says.

### A-2. Emulator variant v0 reuses stage 1's second batch of members, so the "independent draws" statement (DRAWS, round 3 M-4) is false
severity: major
lane: statistics / reproducibility
where: cafe/pm/pipeline.py:1180 (`list(range((k + 1) * batch, (k + 2) * batch))`), cafe/pm/stage1.py:889 and 431 (`blocks = range(n + j*batch ...)`, `SeedSequence([seed, members[0]])`), cafe/pm/whatif.py:384-388 (`DRAWS`)
reproduction: quick plan: batch 32, n_max 64, so stage 1 runs members [0,32) and [32,64) with LHS seeds `[seed, 0]` and `[seed, 32]` and per-member streams `member_seed(seed, m, stream)`. Emulator variant k = 0 runs members `(0+1)*32 .. 2*32-1` = [32, 64): the same hypercube and the same noise streams as stage 1's second batch. The base training row is built from `stage1b/res.pkl` (all 64 members, `n_members` 64), so half of the base row's draws are v0's draws. At `4h` (batch 64, n_max 256, members 0-255) variants k = 0, 1, 2 run members [64,192), all inside the base row's 256. `DRAWS` says each variant "is independent of every other training row of the run".
why it matters: the training rows share forcing draws, the hold-out is scored against targets that share noise with training points (exactly what M-4 was meant to remove), and the written claim in holdout.json is false whenever stage 1 ran more than one batch.

### A-3. Three different bytes-per-cell figures for the native LES nest: the planner's memory guard is 2.5x to 5.5x too lenient, and `les["max_cells"]` is read by nothing
severity: major
lane: numerics / honesty
where: cafe/pm/budget.py:48 (`LES_BYTES_PER_CELL = 55.0`), 344 (`max_cells`), 388 (`memory_guard(..., LES_BYTES_PER_CELL, ...)`); cafe/pm/stage3/windows.py:254 (`lbm.check_memory(res["cells"], None, spec.storage, "native")`) with cafe/pm/stage3/lbm.py:63, 112 (`JAX_MEM_FACTOR = 2.5` x 55 or 93 = 137.5 or 232.5 B/cell); cafe/pm/stage3/nest.py:430 (`NEST_BYTES_PER_CELL = 300`)
reproduction: `grep -rn max_cells cafe/pm` finds only the write at budget.py:344. The engine that runs every window is the native kernel (windows.py rejects any other backend), for which `lbm.memory_bytes` is 137.5 B/cell at fp16 and 232.5 at fp32, and `nest.py` itself says 300 B/cell (182 measured + masks + Bouzidi q). The plan refuses a nest only above 0.85 x GPU memory / 55 B. For a 24 GB card the plan allows 3.7e8 cells; `run_window` allows 1.5e8 at fp16 (0.9e8 at fp32; 6.8e7 by the nest's own 300 B). `fit_window` (pipeline_windows.py:304-323) sizes cells from the cell-update budget only and never reads `max_cells`. STATUS and the budget docstring say the plan "refuses a nest over 85 % of device memory".
why it matters: on the first GPU run a window the plan accepted raises `MemoryGuardError` mid-stage (after hours of stage 1), or a nest sized for 55 B/cell is rejected only at run time; the GPU path is untested, but the stated claim and its test (`test_the_planner_refuses_a_nest_over_85_percent...`) check only the planner's own constant.

### A-4. The emulator stage sizes its variants for the wrong share when a sub-grid calibration exists but no vehicle was refit
severity: major
lane: reproducibility / performance
where: cafe/pm/pipeline.py:1161 (`free = not scales and not ...subgrid_calibration.json.is_file()`), 1162 (`share = ...stage1b_free=free`), 1164 (`n_var = sizes["variants_refit" if scales else "variants_no_refit"]`)
reproduction: by reading the three lines. Stage 1b reruns stage 1 when `scales` is non-empty or when `stage3/subgrid_calibration.json` exists (s_stage1b: `if not scales and not recal:` is the copy branch), so with a calibration and no usable refit `free` is False and the share is the emulator's own 5 % (60 s at `quick`). `n_var` is still `variants_no_refit`, which `emulator_plan` sized for 70 % of 20 % of the budget (168 s at `quick`, 6 variants at 26 s). The safety kill then ends the loop at about 3 variants, by wall clock. At quick this is the GPU path (calibration written only when an LES window passes), so it is not in q7, but `budget.emulator_plan` already computes the right number (`variants_refit` is n(False), sized without stage 1b's share).
why it matters: BUDGET's central statement is that no amount of work is sized from elapsed time and the same seed gives the same report; in this case the number of training rows, the hold-out, the flip search and the report depend on the clock.

### A-5. A missing or old-layout `derived.zarr` silently runs the whole pipeline without the sub-grid layer and passes `derived_unchanged`; a corrupt chunk gives a raw traceback
severity: major
lane: robustness / honesty
where: cafe/pm/pipeline.py:164 (`if _derived_current(self.cache):` else `sub = None`), 736-745 (`_derived_unchanged`: `if getattr(ctx.env, "subgrid", None) is None: return`); cafe/pm/ledger.py `done()` (a directory input is skipped by `f.is_file()`); cafe/pm/env/surface.py:209 (`SurfaceLayer.__init__`, unguarded `.load()`)
reproduction: on the CI fixture (`pmx.sh python rev7_probe9.py`): build `pipeline.Context("missions/ci_fixture.yaml", "ci", 0, run)`, check `_derived_unchanged` (records `derived_unchanged True`), then `shutil.rmtree(cache/"derived.zarr")` and build a new Context: `ctx.env.subgrid` is None, `_derived_unchanged` appends no check at all, and `ctx.env.wind(...)` is tagged "neutral log profile, z0 = 2e-4 m (no COARE stability: subgrid disabled)" with Stokes drift 0. Ingest's ledger lists `derived.zarr` as an input, but `ledger.done()` only re-hashes inputs that are files, so a resumed run does not rerun ingest when the directory is deleted. Second case: truncate one chunk inside `derived.zarr`: `surface.SurfaceLayer(cache)` raises `RuntimeError: Zstd decompression error` (no ConfigError, no "delete X and run fetch" advice; the orca stores, the ocean store and the manifests all have that path since DECISIONS 294/314/315/336), and because `_derived_unchanged` evaluates `ctx.env` before it hashes the store, the "store changed since ingest" check can never fire.
why it matters: the lab-visible failure is "a stage ran on a different physics than the report says": no warm layer, no COARE profile, no Stokes drift, no failed check, and the report's switch list still shows the mission's five switches on.

### A-6. The free-surface hull mesh has a wetted area 29 % above the platform value its Hangar reference uses, and nothing checks it
severity: minor
lane: physics / honesty
where: cafe/pm/stage3/pipeline_windows.py:645 (records `wetted_area_mesh_m2`, `wetted_area_platform_m2`), 225-237 (`cd_h` from `P["wetted_area_m2"]`), 525-526 (only the UAS case sets `comparable=False`)
reproduction: `q7/stage3/windows.json` usv[2] (`hull_fs`): `wetted_area_mesh_m2 8.392`, `wetted_area_platform_m2 6.5`, `ref_area 1.058`, `cd_hangar 0.03846`. The viscous Hangar drag scales with the platform's 6.5 m^2; the CFD hull would have 8.39 m^2. The refit pools `cd / cd_hangar`, so a +29 % friction-area bias enters the drag multiplier as if it were physics. The row is recorded and unused (`grep wetted cafe/pm/stage3` shows no check, no comparison).
why it matters: when the window does run (a GPU / overnight plan) the multiplier carries a geometry inconsistency; either the platform value (assumed) or the mesh is wrong and the code never says which.

### A-7. `par.workers()` ignores the cgroup v1 CPU quota though `par.memory_gb()` handles v1
severity: minor
lane: robustness / performance
where: cafe/pm/par.py:66 (reads only `/sys/fs/cgroup/cpu.max`), cf. par.py:99-107 (`memory_gb`: v2 and v1)
reproduction: `docker run --cpus 8` on a host with cgroup v1 (RHEL / CentOS 7, Ubuntu <= 20.04 default; the lab server is unknown, QUESTIONS 6): `cpu.max` does not exist, `OSError` is swallowed, and `workers()` returns every CPU of the host (`sched_getaffinity` is not cut by `--cpus`). On a 64-core host the run starts 64 workers, each 0.9 GB plus the environment, against a plan that says 8; `plan.json` `workers_by_cpu` reads 64 and `describe` prints it as the CPUs "this run may use". `cpu.cfs_quota_us` / `cpu.cfs_period_us` is the v1 equivalent.
why it matters: oversubscription and memory pressure on exactly the kind of shared lab server the RUNBOOK is written for.

### A-8. A mission `name` of any length validates and then fails with a raw `OSError: File name too long` at ingest
severity: minor
lane: robustness
where: cafe/schemas/mission.json (`name`: pattern `^[a-z0-9_\-]+$`, no `maxLength`); cafe/pm/pipeline.py (`self.cache = DATA / "cache" / name`), cafe/pm/env/ocean.py:32 (`gofs_<name>.zarr`)
reproduction: `name: aaaa...` (300 characters) passes `load_mission` and `budget.plan` ("OK 64" in the probe); `os.makedirs("/tmp/" + "a"*300)` raises `OSError [Errno 63/36] File name too long` (255-byte limit), which is where ingest's first `mkdir` of the cache directory goes. The "does not run" message the RUNBOOK promises for a wrong mission file ("a wrong file is found here and not hours into a run") does not hold.
why it matters: small, but it is the documented contract of `validate`.

### A-9. A measurement dated after the commit that cites it
severity: minor
lane: reproducibility / honesty
where: cafe/pm/budget.py:52 (`WORKER_GB = 0.9 ... (B's mem.py, 2026-11-05)`), DECISIONS.md row 281, review/round_5/handbacks/r5_handback_P.md:24
reproduction: `git log -3 --date=iso`: the commit carrying budget.py is dated 2026-11-03 16:46 -0800 (the q7 ledgers start 2026-11-04T00:47Z); the memory measurement behind the worker constant is dated 2026-11-05. The provenance of the one constant that decides how many workers fit in memory cannot be right as written.
why it matters: "a number you cannot trace" includes a date that cannot be true; the file and run behind 0.81 to 0.84 GB are not named.

### A-10. A 30-day window (BRIEF 5.6 robustness input) is refused on the lab-class machine, and the refusal rests on an unmeasured 5x extrapolation
severity: minor
lane: robustness / performance
where: cafe/pm/budget.py:53-54, 185-188 (`env_model_gb`: 9 GB at one box and window, linear in days and area), RUNBOOK section 1 ("reasoned from the model and not measured")
reproduction: `budget.plan("quick", 0, <demo with window end 2023-03-31T12:00Z>, mem_gb=30)` raises `PlanError: stage 1 needs about 45 GB for the environment of a 30-day window ... 30 GB is available`; the default pad (no `pad_deg`) gives about 140 GB. The same refusal comes at 20 vehicles only through the stage-1 share, not the memory.
why it matters: documented and graceful, but the tool can run at most about 15 days of the demo box on its own target machine (32 GB), and the 30-day figure is a linear guess. A mission longer than that needs a streaming environment, not a bigger `--budget`.

### A-11. The `ensemble_size` self-check blames the budget for a cap that is a table constant; stage 1 used 13 % of its share
severity: minor
lane: honesty
where: cafe/pm/pipeline.py:851-852 (`ctx.plan["n_max"] < r["n_certify"]` passes; note "below the certifying size only because the budget cannot reach it"), cafe/pm/budget.py:32 (`N_MAX["quick"] = 64`)
reproduction: q7 `checkpoints/stage1/ledger.json`: check `ensemble_size` ok true, value 64, limit 73. q7 `plan.json`: `stage1_share_s` 900, planned `stage1_s` 52.7, measured 120.5 s; the whole run took 446 s of 1200. Seventy-three members would have cost about 20 s more; the cap is `N_MAX["quick"]`, not the budget (the planner's own "ensemble capped by the stage-1 share" note, which would be the true reason, is absent from the plan). BRIEF 5.5 allows "cannot certify" at `--budget quick`, so the verdict text is fine, but the ledger reason is false and the check cannot fail for any plan with n_max < 73.
why it matters: the glider_2n and Iridium GO verdicts say "cannot be certified at n = 64"; a reader of the ledger believes the machine could not do 73.

### A-12. `GriddedEnv` documentation says the atmosphere is 0.4 GB; the code holds 0.76 GB for those fields and DECISIONS 267 measures 2.9 GB
severity: minor
lane: documentation
where: cafe/pm/env/environment.py:4-5 ("6 days x 130 x 313 x 16 WRF fields is ~0.4 GB") against environment.py:79 (`.astype("f8")`)
reproduction: 145 hourly steps x 130 x 313 x 16 fields x 8 bytes = 0.76 GB (0.38 GB only in float32). DECISIONS 267 measured "2.9 GB of WRF and UMWM". Three different sizes for the same arrays in three places; the planner uses the measured 9 GB total.
why it matters: a reader sizing a bigger box from the docstring is 7x low.

total: 12 findings (0 critical, 5 major, 7 minor)
not covered: line-by-line physics of physics/glider.py, usv.py, uas.py (exercised by probes only), stage3/nest.py, wallmodel.py, freesurface.py, fluidx3d.py internals, env/hycom.py, orca.py, tao.py, remote.py, bathy.py readers, report.py/credibility.py rendering, receipts.py, and whether each round-6 test fails on a mutant of its fix (spot-read only; none run)
