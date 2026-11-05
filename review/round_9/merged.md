# Round 9 merged findings (BRIEF 5.6 step 2)

Inputs: reviewer_a.md (11 findings), reviewer_b.md (8), reviewer_c.md (8), reviewer_d.md (15). Merged to 40 findings, M-1 .. M-40. Every source id appears in exactly one merged finding (42 ids: A-1..A-11, B-1..B-8, C-1..C-8, D-1..D-15). Two merges: M-8 (A-4, B-2) and M-10 (A-6, B-3).
Each finding was checked by an independent verifier against HEAD c1dd8cd, by reading the cited code and the q9 run files (`plan.json`, `checkpoints/*/ledger.json`, `emulator/design.json`, `report/index.html`, `stage1b/summary.json`) and, for most code claims, by reproducing it on cafe-burst in a detached worktree and a private `pm_v9_*` directory (removed afterwards). The "check" lines below are the verifiers' results; this merge did not re-run anything, and the severity and status are the verifiers', not the reviewers'. Where a verifier lowered or raised a severity, the check says so.
Not covered by any reviewer (their own lists): no full pipeline on real demo data, no real HYCOM or orca fetch, no `make receipts` / `audit` / `acceptance`, no CFD, no Bellhop (no `bellhop.exe` in the burst image), no ArduCopter SITL, no CalculiX, no NaN or corrupt-file inputs end to end, no mutants in stage1 summarize, report, credibility, receipts or the runner scripts. The orca scripts were read, not run. glider.py, uas.py, coare.py, waves.py, subgrid.py, tao.py, bathy.py, stage3/* and dtmb5415.py were not read line by line. Reviewer B noted a `tmux kill-server` on cafe-burst while cleaning up; no other job was visible but none could be confirmed untouched.

Severity: 0 critical, 6 major, 34 minor. Status: 37 confirmed, 3 partly (M-8, M-17, M-31), 0 not confirmed.

---

## Critical

None. No reviewer found one and no verifier raised one.

---

## Major

### M-1. A platform given as a path passes `validate`, then `run` stops in the hangar stage with `file not found`   (sources: A-1)
severity: major / status: confirmed / lane: robustness
where: cafe/pm/pipeline.py:953-958 (`PLATFORMS / f"{v['platform']}.yaml"`, then `L.input(p)`, `_yaml(p)`); cafe/pm/config.py `load_platform` (:407-409), `_check_platform` (:247-255); cafe/schemas/mission.json:42 (platform is a name or a path)
claim: With `platform: platforms/seaglider.yaml` (or an absolute path), `validate` prints "valid" and `run` ends after ingest with `/app/platforms/platforms/seaglider.yaml.yaml: file not found`; `hangar --platform` accepts the same path.
check: holds, by code. Every other consumer accepts a path (config.load_platform, glider/usv/uas.load_platform, `_check_platform`); only `s_hangar` re-derives the file by string formatting. `L.input(p)` records `sha256=None` for the missing file, so even a patch in place would leave an unhashed input and a lab-edited platform file would not invalidate a resume. Not run on the box. No DECISIONS row contradicts a fix.
fix: one resolver in config.py, `platform_path(name) -> Path` (`.yaml`/`.yml` suffix means the path as given, else `PLATFORMS/<name>.yaml`). `s_hangar` uses the resolved path for `L.input`, `_yaml` and the rows' `file`. Siblings that need the same resolver: report.py:451 (source label), the credibility `used` / assumed-count keys (credibility.py:365/481/740, key by stem or by path: decide), and the glider/usv "not suffix" rule against config's ".yaml/.yml" (dotted names). Regression test: a mission with the platform as a repo-relative path and as an absolute path through `s_hangar`; it must fail now, and the ledger input hash must be non-null. Check goldens that store the ref string.
sources: A-1

### M-2. A YAML alias shared between two vehicles makes `whatif` (and the emulator variants) move or shift both   (sources: A-2)
severity: major / status: confirmed / lane: robustness / correctness
where: cafe/pm/whatif.py:97-144 (`apply` edits `v['deploy']`, `v['task']` in place on a deepcopy that keeps shared references), :160 (`solo`); cafe/pm/config.py `_yaml` / `load_mission` (aliases accepted, never unshared); cafe/pm/pipeline.py:1354 (one `apply` per emulator variant)
claim: With `deploy: &d {...}` on one glider and `deploy: *d` on another, `apply(m, {'glider_eq': {'dlon': -0.5, 'shift_h': 3.0}})` changes both; two `dlon: -1.0` edits give lon -172.0 for both (expected -171.0 each); an aliased task does the same to `dive_depth_m`.
check: reproduced on cafe-burst (aliased copy of the demo). `_Loader` rejects only duplicate keys. The what-if answer, the "what would fix it" line and the emulator training rows then describe a mission that is not the one stated, with no warning. The shipped demo and ci_fixture contain no anchors, so q9 is unaffected.
fix: at the end of `config.load_mission` unshare with `json.loads(json.dumps(m))` (the mission is already finite JSON by `_finite` and the schema). That covers `apply`, `solo`, the emulator variants and `flip_search`. Alternative, stricter: reject aliases in `_Loader`. Test: aliased deploy and task, load, `apply({glider_eq: {dlon: -0.5}})` leaves `glider_2n` unchanged; fails before. New DECISIONS row and CHANGELOG line. Check that no caller relies on identity with the validated doc and that the mission content hash is unchanged.
sources: A-2

### M-3. The UAS has no `no_current_data` path: a NaN wind met in flight gives a silent NaN vehicle reported only as `profile_incomplete`   (sources: C-1)
severity: major / status: confirmed / lane: robustness
where: cafe/pm/physics/uas.py:301-395 (`_block`), :562-581 (`make_wind`), :429-447, :51 (`FLAGS`); compare glider.py:421-427, usv.py:508/562-567/629
claim: A wind lookup that returns NaN after launch leaves every UAS flag False except `profile_incomplete`, with `soc_end`, `max_tilt_deg` and the final position NaN; the glider and USV label the same input `no_current_data`.
check: reproduced on cafe-burst (`fly_sortie`, M=1, NaN wind for lon > 0.002 deg): only `profile_incomplete`, `wp_done` 1 of 8, `soc_end` NaN, `max_tilt_deg` NaN. The claim that Stage 1's min over `soc_end` turns the battery margin NaN rests on code reading, not a run. A hole at the ship is scrubbed by the launch gate; only a hole in flight is silent, and real HYCOM/ORCA stores have masked cells. Extends DECISIONS 241, 308, 356, 406 to the third class.
fix: in `uas.make_wind`, where every lookup goes, test `np.isfinite`; replace a non-finite vector with zero and set a per-member `no_current_data` flag that sticks (the 1 s held mean must not clear it), with the member ended or its NaN outputs masked as the glider does. Add the flag to `uas.FLAGS` and to report `MODE_TEXT` (batch B hand-off) and every FLAGS-keyed table. Test with the NaN-wind env; fails before. New DECISIONS row and CHANGELOG line. Check fixtures that build `{k: ... for k in uas.FLAGS}` and a hole beyond the sortie's reach that must not flag.
sources: C-1

### M-4. A stored wall-model receipt with `code_sha` but no numeric `err` crashes the stage instead of failing a check   (sources: C-4)
severity: major / status: confirmed / lane: robustness
where: cafe/pm/stage3/wallmodel.py:358-384 (`stale_wall_receipts`, `stored_wall_error`: `float(json.loads(...)["err"])`), `receipts()` (`plate["re"]`, `["cf"]`, `["yfrac"]`); cafe/pm/stage3/windows.py:321; cafe/pm/stage3/pipeline_windows.py:550-562 (catches only `ValueError`, `RuntimeError`)
claim: Receipts `{"code_sha": <current>}` make `stale_wall_receipts()` return `[]` and `stored_wall_error()` raise `KeyError('err')` (`TypeError` with `err: null`) after the LES has run.
check: reproduced on cafe-burst. `KeyError` and `TypeError` pass through `run_window` and `s_stage3`; `err: "abc"` is a `ValueError` and is caught but yields a window `error`, not the failed `wall_model_receipt_error` check. Reviewer rated it minor; the verifier raised it to major by the round's rule (a crash). Trigger is narrow (a hand-edited or schema-changed file with a current sha). Finishes the intent of DECISIONS 424.
fix: validate in `_read_receipt` (wallmodel.py): return `None` unless every required field is a finite real number (not bool, str, None): `err`, `cf`, and for the plate `re`, `ittc`, `yfrac`; for the channel `cf_dean`. Then `stale_wall_receipts` says "unreadable", `stored_wall_error()` returns `None`, the gate fails with that text, `receipts()` shows NOT STORED. Have `stored_wall_error` use the validated result. Tests: `{code_sha}` alone, `err: null`, `err: "x"` for both files; plus one `run_window` level test that a bad receipt gives a failed check, not an exception. Same field check for `lbm.result_row` (`rec[ref_key]` before the sha test) in stage3, and `credibility._json` for `wm_*.json` (batch B hand-off). Amend DECISIONS 424. Must be done together with M-23 (same function).
sources: C-4

### M-5. `ingest_lab_hycom` deletes the lab's source directory when the store path is, or contains, that directory   (sources: D-1)
severity: major / status: confirmed / lane: robustness / data
where: cafe/pm/env/hycom.py:187-188 (`write_store`: `shutil.rmtree(out)` then `os.replace`), :723-767 (`ingest_lab_hycom`); cafe/pm/__main__.py:204-214 (`_ingest_ocean` passes `spec['path']` as output and `a.path` as input); cafe/pm/config.py:312
claim: With `environment.ocean.path` equal to the `--path` of `ingest-ocean`, the call returns success and the three `snap_*.nc` files are gone, replaced by the Zarr store.
check: reproduced on cafe-burst with `tests/fixtures/hycom/make_fixtures`. Worse than reported: output = the parent of the source also succeeds and removes the source directory and the fixture dir with it (output as an ancestor of the input). The other `write_store` caller (GOFS download, hycom.py:417) has no lab source. The repo itself names this harm (`hycom.unreadable` docstring). Not in the PROMPT "Known" list; no DECISIONS row contradicts a fix.
fix: one guard at the top of `ingest_lab_hycom`, before any read: resolve both paths; raise `ValueError`/`ConfigError` naming both if `out == p`, `p` is inside `out` (ancestor), or `out` is inside `p`; the CLI then needs no separate check. Optionally refuse a non-empty `out` that has no `zarr.json`. Use `resolve()` so symlinks are covered. Tests in test_hycom.py: out == src, out == parent, out inside src: error raised and the `snap_*.nc` files still present; fails now. Decide whether nested is allowed (safe, but a conservative guard refuses it). New DECISIONS row and CHANGELOG line.
sources: D-1

### M-6. `orca.assemble` keeps every hourly `.npz` open; a window of about 21 days or more ends in `OSError: Too many open files`   (sources: D-2)
severity: major / status: confirmed / lane: robustness / performance (BRIEF 5.6 30-day window)
where: cafe/pm/env/orca.py:323, :333, :338, :348 (lists of `np.load` handles, never closed; `W` read again for `bytes_fetched`)
claim: Two files per hour with a container soft limit of 1024 gives a limit near 500 hours; the 30-day window needs 720 hours (about 1,440 fds plus about 120 spec files).
check: reproduced on cafe-burst in the cafe-pm image with synthetic 3x3 parts: 200 hours pass, 600 hours fail with errno 24. The failure comes after the network fetch, and every rerun fails the same way because the parts are cached. Not run: a real 30-day fetch. DECISIONS 192 says a 30-day fetch should work.
fix: inside `assemble()` only: replace the four list comprehensions with one helper that opens each part in a `with` block, copies the keys needed and `_bytes`, and closes it; sum `bytes_fetched` from what the helper collects, not from a retained `W`. Test: write 600+ tiny parts, `assemble` under `resource.setrlimit(RLIMIT_NOFILE, (256, hard))`; fails before. Do not raise the ulimit instead (proot settings differ and it hides the leak).
sources: D-2

---

## Minor

### M-7. The USV speed-sanity sentence sets SOG per 10 m wind beside a calibration ratio defined per anemometer-height wind   (sources: A-3)
severity: minor / status: confirmed / lane: honesty / physics
where: cafe/pm/report.py:462-471 (`_speed_ratio`) and :1155-1158; cafe/pm/credibility.py:633-637; cafe/pm/stage1.py:807-815; platforms/saildrone_explorer.yaml:71
claim: The report prints 0.129 against Chiodi's 0.178 (27.6 % short); the like-for-like anemometer-height ratio is 0.135 (24.2 % short).
check: holds. q9 `stage1b/summary.json`: `ratio_median` 0.12867, `ratio_anem_median` 0.13478, `calibration_ratio` 0.17778; the report HTML reads exactly "mean 10 m wind ... 0.129 ... against Chiodi 0.178". The 0.129 is correctly labelled "10 m"; the defect is the pairing, about 3.4 points of overstated gap. No printed sentence states a percentage, and no verdict or gate reads this ratio. The estimators also differ (median of ratios against ratio of means).
fix: pass `ratio_anem_median` through `_speed_ratio` (optional: older summaries lack it); in `_speed_html` and the credibility sanity row compare the anemometer-height ratio with 0.178 and show the 10 m one as secondary; fall back to the 10 m ratio, labelled, when absent. Optionally state the estimator difference. Test: a summary with both ratios, the comparison uses the anemometer value. Amend DECISIONS 183 and 216, new row. Check tests that assert the "mean 10 m wind ... 0.129" string and the report text hash.
sources: A-3

### M-8. The overrun and wall-share figures in RUNBOOK step 4 and DECISIONS 444 (2.2 times, about 45 %, emulator 12 % over) are one machine's; the q9 run on a different machine measured 4.2 times and 2.05 times   (sources: A-4, B-2)
severity: minor / status: partly / lane: performance / documentation
where: docs/RUNBOOK.md step 4; DECISIONS.md row 444; cafe/pm/budget.py `plan` / `describe`; cafe/pm/ledger.py:90
claim: q9 stage 1 planned 52.68 s, measured 223.05 s (4.23x); emulator `wall_s` 492.85 s against a 240 s share (2.05x); variants 283 s against 105.4 s planned (2.7x). At 4.2x the 45 % rule is about 24 %.
check: the numbers are real but the docs are not contradicted. The q8 ledgers (host homebase, 8 CPUs, the bench machine) give 117.2 s (2.2x), 270.4 s against 240 s (12 %), exactly what RUNBOOK and DECISIONS 444 say. q9 ran on host `cafetest` (32 vCPU, 6 workers, `bench_id` homebase), with the same `plan.json`. So most of the gap is the machine mismatch (M-9), not a wrong q8 figure; the split between machine, load and thread contention is unmeasured. B-2's "flip search not held by the share" is wrong: pipeline.py:1362 and :1434 charge it at planned cost against the 30 % reserve (budget.py:42); the unexplained ~210 s is training plus real flip-search evaluation. Severity: A-4 minor; B-2 lowered from major to minor (no verdict, number or gate changes). Valid part: quick's margin on this machine is 380 s of 1,200 s, worth a sentence. The 30-day-copy plan figure (about 1,110 s) is arithmetic, not run.
fix: do not change 45 % or 2.2. Amend RUNBOOK step 4 and DECISIONS 444: the ratios are per machine; q8 on homebase 2.2x and 12 %, q9 on the 32-vCPU VM 4.2x and 2.05x; re-measure with `make bench` on the machine used. The code part is M-9. Optionally record `wall_s / planned` in the stage1 and emulator ledgers so the report prints it.
sources: A-4, B-2

### M-9. The planner uses `throughput.json` from another machine with no warning   (sources: A-5)
severity: minor / status: confirmed / lane: performance / reproducibility
where: cafe/pm/budget.py:94-109 (`measurement_warnings`), :73-91 (`member_cost`, `lbm_rate` source strings); cafe/pm/ledger.py:90; cafe/pm/report.py `_machine` (:894-900); config/throughput.json `machine`
claim: q9 ran on `cafetest` (32 CPUs) with a `bench_id` of homebase (8 CPUs); `plan` prints "measured (2026-11-01, homebase, load 1.40...)" and no warning.
check: holds, by code and the q9 ledger/plan; the live `plan` line was not reproduced (the burst VM refused at 8 GB). `measurement_warnings` judges contention against the measured box's own CPUs and never compares the machine block to the host. DECISIONS 157 defines the warning as load or other mission only, so nothing contradicts a fix. RUNBOOK 4 says "once per machine".
fix: one helper in budget.py called from `measurement_warnings` (and the `lbm_rate` / `FALLBACK_COST` notes) comparing `thr["machine"]` (cpus, cpu model) with `os.cpu_count()` and the `/proc/cpuinfo` model, adding "throughput.json was measured on <id> (<n> CPUs, <cpu>), this machine has <n>: re-run `make bench`". Use `os.cpu_count()`, not `par.workers()` or the docker cap. A note, not a refusal. Surface it in the report machine block (batch B hand-off). Amend DECISIONS 157, CHANGELOG, test with a `thr` whose `machine.cpus` differs. Plan-note text is hashed by the emulator and report stage ledgers (DECISIONS 290) and acceptance fixtures: regenerate goldens. Watch false warnings on cgroup-limited boxes.
sources: A-5

### M-10. The report's emulator section states the plan (7 points per class, 26 s per variant), not what ran (5 points, 4 variants, 2.7x the cost)   (sources: A-6, B-3)
severity: minor / status: confirmed / lane: honesty
where: cafe/pm/report.py:815-858 (`plan_note` from `budget.emulator_plan`, budget.py:405-431), :1386 (printed as a bare warn paragraph), `_emulator` ignores `design["killed"]`; tests/test_report.py:1226-1233
claim: The HTML says "7 distinct points per vehicle class ... (6 variants of 26 s + the base mission ...)"; the ledger says "killed ... before variant v4 of 6", "5 usv rows, 5 uas rows, 10 glider rows"; `design.json` has 4 variants, measured 71/80/61/70 s.
check: holds. The word "killed" appears nowhere in the q9 HTML; the design block shows the real count 4 but never the cut. DECISIONS 188 has the report repeat the plan's note, so repetition is by design but unlabelled and wrong once the run diverges. Measured seconds are deliberately kept out of hashed outputs.
fix: in `report._emulator` (the one place), when `design.json` exists build the sentence from it (variants + 1 points per vehicle, `killed.at_variant` of `planned_variants`) and label the plan version "Plan:"; print `design["killed"]["reason"]`. Keep `plan_note` as its own field and add `run_note`, so the traceability checks still match and test_report.py:1226 keeps passing. Put the formatter in report.py (budget.py belongs to another batch). No measured seconds in hashed output. Test: design with `killed.at_variant=4` of 6 shows 5 points and the kill, not "7 distinct". Amend DECISIONS 188, CHANGELOG.
sources: A-6, B-3

### M-11. `--gpu-mem-gb` accepts nan, inf, negative and zero   (sources: A-7)
severity: minor / status: confirmed / lane: robustness
where: cafe/pm/__main__.py:51 (bare `type=float`); cafe/pm/budget.py:347-349 (`if gpus > 0 and gpu_mem_gb:`), :390, :484-491
claim: nan is a `ValueError` traceback at budget.py:349, inf an `OverflowError`; -5 and 0 print a normal GPU plan.
check: reproduced on cafe-burst. Zero silently disables the memory guard (falsy conflated with `None`) and -5 stores a negative `max_cells`. `plan(gpu_mem_gb=nan)` is also unguarded through the Python API (callers: `__main__.py:148`, `pipeline.py:123`, `pipeline_windows.py:627`). No DECISIONS row contradicts.
fix: in `budget.plan()` next to the `gpus < 0` check: `if gpu_mem_gb is not None and not (math.isfinite(gpu_mem_gb) and gpu_mem_gb > 0): raise PlanError("--gpu-mem-gb must be a positive number of GB")`; test `is not None`, not truthiness. Optionally a positive-finite argparse type like `_seed`. Tests: parametrized `plan()` over nan, inf, -5, 0 and a CLI test (nonzero exit, message, no traceback). Check existing tests for `gpu_mem_gb=0`. New DECISIONS row, CHANGELOG.
sources: A-7

### M-12. `run --mission <run dir>/mission.yaml --out <run dir>` is a `shutil.SameFileError` traceback   (sources: A-8)
severity: minor / status: confirmed / lane: robustness
where: cafe/pm/pipeline.py:1474-1478 (`shutil.copy(ctx.mission_path, ctx.path('mission.yaml'))` and the `--seed` branch); cafe/pm/__main__.py:163-168 (catches only ConfigError, PlanError, StageFailed)
claim: Re-running from the run's own copy ends in a Python traceback with no `error:` line, exit 1.
check: reproduced on cafe-burst. The failure comes before any stage runs and nothing is corrupted; RUNBOOK:167 invites the path. `fetch` goes through the same `run()`. With `--seed` and the same file the branch rewrites the file over itself without crashing (drops comments).
fix: in `pipeline.run`, copy only if the destination is absent or not the same file (`os.path.samefile`, test existence first). Make the seed branch either skip or still rewrite with the new seed. Tests: mission inside the out dir, once without and once with `--seed`: exit 0 and `mission.yaml` unchanged (or carrying the seed); fails now.
sources: A-8

### M-13. A USV or glider section with identical waypoints is accepted, and the track test is silently off   (sources: A-9)
severity: minor / status: confirmed / lane: physics / robustness
where: cafe/pm/config.py:396 (only `len(task.waypoints) < 2`); cafe/pm/physics/usv.py:477-488, :523-536 (`_geom`: zero-length leg gives `nl = 0`, cross-track 0), :618; cafe/pm/physics/glider.py:276-278
claim: Waypoints `[[-165,0],[-165,0]]` give fails `{becalmed: 4}` and `xte_max` 0; the same point as station mode gives `swept_off_track: 4` and `xte_max` 112.6 km.
check: reproduced on cafe-burst (116.8 km with a different VPP seed). A control with distinct waypoints under a north current flags `swept_off_track`. The glider has the same empty-only check (not run). The trailing-duplicate `[A,B,B]` case was not isolated. Degenerate input someone has to type; the `becalmed` verdict still prints. Closes a gap in DECISIONS 155.
fix: in `config.load_mission` (shared by every vehicle) refuse a section with fewer than two distinct points and consecutive duplicate waypoints, naming the index. Defence in depth (batch C hand-off): drop consecutive duplicates in the USV and glider constructors before the `len == 1` station collapse. Tests: load refusal; `USVSim` `[A,A]` raises or equals the station result. Grep missions and tests for deliberate repeats (loiter) first. New DECISIONS row (amends 155), CHANGELOG.
sources: A-9

### M-14. Raw Python in user-facing text: `Dominant failure mode: None` and a dict repr of the mission box in what-if rows   (sources: A-10)
severity: minor / status: confirmed / lane: documentation
where: cafe/pm/report.py:1197 (`e(str(v['dominant_mode']))`); cafe/pm/whatif.py:136; cafe/pm/config.py:333, :356; cafe/pm/pipeline.py:214
claim: q9 HTML shows "Dominant failure mode: None" for glider_2n and three what-if rows with `{'lon_min': 165.0, 'lon_max': -165.0, ...}`, where the antimeridian wrap is also unexplained.
check: holds, by code and a grep of the q9 HTML (not run on the box). `dominant_mode` is `None` when no member fails (stage1.py:750). The same box-dict message is in config.py:333/:356 (shown on the CLI). pipeline.py:214 and env/hycom, env/bathy errors were not checked (probably tuples). Not required by any DECISIONS row.
fix: one helper `config.fmt_box(b)` next to `_in_box` ("lon 165.0 E to 165.0 W (across the antimeridian), lat -5 to 5, pad 2 deg"), called from whatif.py:136, config.py:333/:356 (and pipeline.py:214 if a dict). At report.py:1197 render "none (no member failed)" for `None` in the HTML only; the stored value stays `None` (batch B hand-off). Tests: a what-if shift outside the box has no `{` and no `lon_min`; a zero-failure vehicle card has no "None". Grep tests for "outside the mission box".
sources: A-10

### M-15. Two tests pass on broken code: the current-direction error spread and the 20 % u* tolerance   (sources: A-11)
severity: minor / status: confirmed / lane: tests
where: cafe/pm/env/perturb.py:181; tests/test_perturb.py:54-59; cafe/pm/pipeline.py:654 (`r <= 0.2`); tests/test_pipeline.py:2246-2254, :3150
claim: Changing `self.cd / np.sqrt(2.0) * self.fd` to `self.cd * self.fd` leaves 33 tests green; changing `r <= 0.2` to `r <= 0.5` leaves 7 green (the test asserts only `0 <= frac <= 1`).
check: reproduced on a detached HEAD copy on cafe-burst: mutant 1 gave rc 0 with 435 passes across seven test files (wider than reported); mutant 2 rc 0, 8 passes. Code on HEAD is right; this is test strength. The wind-direction random field, other PerturbedEnv fields and the "value <= limit" ingest checks have the same shape (not mutated).
fix: tests plus one constant. (1) Direction-spread test next to `test_current_spread_matches_prior`: current (1, 0), M=2000, speed prior zeroed, std of the heading about `current_direction_bias.value / sqrt(2)` within about 0.03 rad; same for wind direction if the structure matches. (2) Name `USTAR_AGREE_BAND = 0.2` next to `USTAR_AGREE_FRACTION` in pipeline.py; a test builds `ust` as the computed COARE u* times 1.15 (inside) and 1.3 (outside), expecting a fraction near 1 and near 0 (scale the computed value, not fixed numbers).
sources: A-11

### M-16. `report --run` re-render makes `audit` fail on the same run: four outputs "changed since the stage ran"   (sources: B-1)
severity: minor / status: confirmed / lane: reproducibility
where: cafe/pm/__main__.py:178-197 (`_report` calls `report.write`, never updates `checkpoints/report/ledger.json`); cafe/pm/audit.py:154-159; docs/RUNBOOK.md:162
claim: `audit --ledgers-only` gives 0 problems; after `report --run` it gives 4 x "stage report: output .../report/{index.html,report.json,credibility.html,credibility.json} changed since the stage ran".
check: reproduced on cafe-burst. Reviewer rated it major; the verifier lowered it to minor (no verdict, number or crash; the analysis outputs are intact; a rerun of the report stage restores a clean state). The re-render is deterministic (a second one is byte-identical) but differs from what the stage wrote; the cause of that difference (cache present or absent) was not isolated. `report --run` needs about 20 GB (8 GB was OOM-killed, rc 137). The only other `report.write` caller is `s_report`, which records its outputs. No DECISIONS row allows a stale ledger (398 is memory only).
fix: preferred: after `report.write`, `_report` reloads the report ledger, replaces the `outputs` sha256 values (reuse `Ledger.output` / `ledger.sha256`) and adds a note "re-rendered by report --run" with `git_sha` / `code_digest`; stricter, re-run `report_traceable` and `report_html_matches_json` on the new files first, so a re-render with other code is not recorded as the stage's own output. Cheapest: one RUNBOOK 5 sentence that a re-render makes `audit` fail until the stage is rerun. Test: tiny run, call `_report`, `ledger_problems` empty; fails before.
sources: B-1

### M-17. A link needed at no sample gets verdict GO with P(fail) = 0 beside a NO-GO UAS   (sources: B-4)
severity: minor / status: partly / lane: statistics
where: cafe/pm/stage1.py:~616 (`frac = np.where(need.sum(0) > 0, ..., 1.0)`), :786-792 (links summary); cafe/pm/report.py:1004-1010 (`_undecided_badge`), :1216-1221
claim: With `max_mean_wind_ms` 0.5 and `sorties.every_days` 400 the UAS is NO-GO 16/16 `no_sortie_flown` while link `usv-uas-rf` has `need_count_median` 0, `p_fail` 0, verdict GO.
check: the mechanism is real (code), but this is a recorded, deliberately deferred decision: DECISIONS 283 (round 5, M-8) describes exactly this case and leaves a change of verdict semantics to the lead; row 214 sets `granularity_ok` false for need 0. The badge "undecided: granularity" and the text "not exercised" are shown in the Verdicts table and card, so the GO is not hidden ("a headline GO beside a NO-GO UAS" is half true). Not run (q9 `summary.json` has no `links` key). Vehicles have no analogue. Not marked not confirmed because PROMPT.md has no "Known" line for it.
fix: no change unless the lead decides. If so, one place: the stage1.py links summary (line 786): when `granularity_ok` is False and `nc == 0` set an explicit "NOT EXERCISED" verdict (not MARGINAL, which would make an unflown mission look failed), so the badge, the acceptance diff and the report read one field. Needs a new DECISIONS row amending 197, 214, 283. Test: a link with need 0 whose verdict is not GO. Check the verdict vocabulary in report CSS, `acceptance.diff`, the schema and HANDOFF baselines. Limit to `nc == 0`.
sources: B-4

### M-18. `whatif --drop` of every vehicle is accepted   (sources: B-5)
severity: minor / status: confirmed / lane: robustness
where: cafe/pm/whatif.py `answer` (~676-706) and `apply` (:103); cafe/pm/__main__.py `_whatif`; cafe/schemas/mission.json:38 (`vehicles` `minItems` 1)
claim: Dropping all four demo vehicles prints "dropped ..." with the removed links and exits 0, while `vehicles: []` is refused by `validate`.
check: reproduced on cafe-burst (14 GB needed; 8 GB refused). No verdict or number changes; the output is true about the links removed. `--vehicle ID --drop ID` (same id) gives an empty answer with exit 0, a milder variant. No DECISIONS row permits it.
fix: guard in `whatif.answer`, the one command-line entry: raise `Invalid` ("--drop would leave no vehicles; a mission needs at least one") when every vehicle id is in `drop`. Not in `apply()`: `run_variant` (whatif.py:308) relies on an empty result. Check the `Invalid` prints "error:" with a nonzero exit. Test in test_whatif.py: dropping all ids raises, a partial drop works. DECISIONS row, CHANGELOG.
sources: B-5

### M-19. `audit` of a renamed or copied run says "chain broken" (and silently audits the original's files)   (sources: B-6)
severity: minor / status: confirmed / lane: documentation / reproducibility
where: cafe/pm/audit.py:54-64 (`_resolve`), :142, :155, :160-161; cafe/pm/ledger.py `done()` (~176-200), `hashed()` (:173)
claim: `cp -r runs/q9 runs/quick; audit --ledgers-only runs/quick` gives 8 problems "does not record the <prev> ledger as an input (chain broken)".
check: reproduced on cafe-burst (q9 copy: 0 problems; a copy named quick: 8). Worse than reported: because `/data/runs/q9` also existed, input and output hashes of the copy were not checked at all (outputs resolved to the original's files), so a tampered renamed copy would pass every hash check and fail only on the chain; with the original absent you get "missing" lines. The `_resolve` docstring promises copied runs work; that holds only if the directory keeps its name. `done()` has the same recorded-path assumption, so a copied run resumes against the original's files. report.py:177/:526 are name-agnostic. No DECISIONS row covers it.
fix: make `_resolve` independent of the directory name and move it to ledger.py so `audit` and `done()` use one function: rebase on structure (the last component followed by `checkpoints` or a STAGES output dir, joined onto `run_dir`); keep the name match first; fall back to the recorded path only when no run-shaped segment is found (external inputs such as `/app/config`); require the rebased path to exist. Test: copy a fixture run to a new name, tamper one output byte, expect exactly that change and no chain problem; an untampered copy gives 0 with the original removed. New DECISIONS row, CHANGELOG, a RUNBOOK sentence and ideally a different message when only the name differs.
sources: B-6

### M-20. A mission box with `lon_min == lon_max` gives a misleading error, and the codebase reads equal longitudes two ways   (sources: B-7)
severity: minor / status: confirmed / lane: robustness
where: cafe/pm/config.py:325-326 (lat checked only), :141-145 (`_in_box`: zero-width strip); cafe/pm/budget.py:184 (`% 360.0 or 360.0`: full circle); cafe/pm/env/perturb.py:139-141, cafe/pm/whatif.py:224, cafe/pm/report.py:708 (width 0)
claim: With `lon_min = lon_max = -165` the error is "point (-170.0, 0.0) is outside the mission box", not an empty-box message (a reversed lat is named).
check: reproduced on cafe-burst (`load_mission` on the q9 mission). The message is true but never says the box is empty. Equal longitudes (or -180 and 180) are a zero-width strip at config time and a full circle in the budget; undocumented. No DECISIONS row covers it (24, 309, 372 are about the wrap).
fix: in `config.load_mission` after the lat check add a lon check using `_in_box`'s modulo: if `(lon_max - lon_min) % 360 == 0` raise ConfigError "box.lon_min and box.lon_max are equal (X); an empty box ...". All callers go through `load_mission`. First grep tests and missions for equal lons meaning a full circle; if intended, document it in a DECISIONS row and make `_in_box` accept it instead. One shared rule either way. Test: equal lons raise ConfigError matching "lon_min".
sources: B-7

### M-21. The reach-map caption says "within the horizon" while the polygons are 24 h   (sources: B-8)
severity: minor / status: confirmed / lane: documentation
where: cafe/pm/report.py:1294-1295 (caption), :1274 (tooltip "reach within {h:g} h of the deploy"), :1302; config/assumptions.yaml:353 (`reach.horizon_h` 24)
claim: The caption reads as the whole 6-day mission window; the polygon is 24 h.
check: holds, from code and the q9 HTML (static text; the 30.06 km glider_eq reach is under the 41 km 24 h bound, so the numbers are right). "Horizon" also sits near "radio horizon" wording. No other "the horizon" without a number was found in report.py.
fix: make the caption an f-string using `reach["horizon"]["value"]`: "...within {h:g} h of the deploy, in the currents at the deploy time". One test that the caption contains "24 h" and not "the horizon"; check tests and goldens that match the old caption (a grep of tests found none). CHANGELOG line only.
sources: B-8

### M-22. Platform loaders do not require the `mission_defaults` keys the simulators index: load succeeds, `run` dies with a bare `KeyError`   (sources: C-2)
severity: minor / status: confirmed / lane: robustness
where: cafe/pm/physics/usv.py:121 (`MISSION_REQUIRED` has only `cap_cycles`), :152, :577, :603-626; cafe/pm/physics/glider.py:113, :387-397, :477-478; cafe/pm/physics/__init__.py:56 (`check_params` only checks keys in its table); cafe/pm/stage3/pipeline_windows.py:524; cafe/pm/report.py:448, :602; cafe/pm/stage1.py:112
claim: Deleting `corridor_km` (USV) or `station_tol_m` (glider) from a platform copy loads, then raises `KeyError` at the first step that reads it.
check: reproduced on cafe-burst for USV `corridor_km`, `wp_radius_m`, `becalmed_after_h`, `track_tolerance_km`, `roll_limit_deg`, `stall_sustain_s`, `calm_sustain_s` and glider `dive_depth_m` (both modes), `station_tol_m`, `lost_hours` (station), `wp_radius_m`, `unreach_hours` (section); mode-specific keys pass in the other mode. Shipped missions rely on the defaults. Needs a hand-edited platform file. DECISIONS 279 (finite but not required) is the row to amend.
fix: in the two loaders, through the existing `check_params` call: add mission_defaults tables (`glider.REQUIRED[kind]` gets a mission block; `usv.MISSION_REQUIRED` grows to every key read; mode-specific keys required for their kind, or all required, so valid files are not refused). One change per loader covers stage 3 and report. Tests per platform deleting each key and expecting a `ValueError` naming `file:mission_defaults.key`; extend `test_platform_required.py` to scan `md["..."]` / `self.md["..."]` literals. The stage-3 read (pipeline_windows.py:524) and report.py:448/:602 need no change once the loader refuses; `.get` at stage1.py:112 stays. Fixtures with `mission_defaults: {}` in test_glider.py need updating. Amend DECISIONS 279, CHANGELOG.
sources: C-2

### M-23. The stage-3 wall-model gate and the receipts table disagree about a flat-plate run below Re_L = 1e6   (sources: C-3)
severity: minor / status: confirmed / lane: honesty
where: cafe/pm/stage3/wallmodel.py:358-373 (`stale_wall_receipts`: never reads `re`), :376-384, :412-415 (`receipts()` forces FAIL below `PLATE_RE_MIN`); cafe/pm/stage3/windows.py:231, :321-322
claim: A plate with `re` 9.8e5, `err` 0.01 and the current sha fails the receipts row but passes `wall_model_receipt_error` and enters the refit.
check: holds, by code (not run; laptop is Python 3.9). The `stale_wall_receipts` docstring claims the two agree. Today's `PLATE_SLOW` length gives Re_L about 1.02e6, so only a hand-edited file or a changed constant gets there; homebase's stored plate (re 981333, err 0.165, no sha) fails on error and sha anyway. Contradicts DECISIONS 384 ("one FAIL row whatever its error") and 104. A hand-written receipt lacking `re` or `err` raises `KeyError` too (same function as M-4).
fix: in `stale_wall_receipts()` (the gate's helper) add, for the plate file, a missing/non-numeric `re` or `re < PLATE_RE_MIN` case with a phrase such as "wm_flat_plate.json is at Re_L 9.8e5, below the 1e6 the comparison needs (rerun it)"; `stored_wall_error()` then returns `None` and the window fails with that text. Optionally make `receipts()` branch on the same phrase. Test next to the M-8 test (test_stage3.py ~1983): re 9.8e5 / err 0.01 / current sha gives `stored_wall_error()` None, a failing gate row naming Re_L, and a failing receipts row; fails now. Fixtures near test_stage3.py:269-281 and :2002 need `re >= 1e6`. New DECISIONS row extending 384. Do together with M-4.
sources: C-3

### M-24. A window that diverges in its final chunk is not flagged diverged: NaN coefficients enter the hashed row and the FEA runs on NaN pressure   (sources: C-5)
severity: minor / status: confirmed / lane: numerics
where: cafe/pm/stage3/nest.py:262-275 (`simulate` breaks with `done == steps`); cafe/pm/stage3/windows.py:303-307 (`n < steps`), :313-317; cafe/pm/stage3/pipeline_windows.py:557, :565, :571-576, :603-608; callers nest.py:390/411/428, wallmodel.py:262/304
claim: Because `steps` is a whole number of chunks, a blow-up in the last chunk leaves a full-length series; `diverged` and `cut` stay False, `cd` is NaN in `stage3/windows.json`, and `_fea` launches on NaN wall pressure.
check: holds, by code (not run). `ok` is still False (Mach and running-mean checks fail on NaN), so no verdict passes wrongly; the difference is the reason text and a spent FEA slice. DECISIONS 186 and 197 do not exclude the final chunk, so this is a hole. Whether NaN breaks the "same seed, identical report.json" claim was not tested. Wall-model callers use the series as if complete.
fix: `nest.simulate` returns a `diverged` boolean computed from `diverged(chunks[-1])` after the loop; windows.py sets `wlog["diverged"]` from it and `cut` in pipeline_windows.py is `run_steps < planned_steps or wl["diverged"]`. Do not shorten `run_steps`. The wall-model calibration callers decide whether to raise on the flag. Test: a spec whose last chunk goes non-finite gives `diverged` True, `cut` True, no FEA call and no `cd` in the hashed row; fails now. Amend DECISIONS 186, 197.
sources: C-5

### M-25. `comms.acoustic_link` with a scalar range and an ambiguous Bellhop link raises `TypeError`   (sources: C-6)
severity: minor / status: confirmed / lane: robustness
where: cafe/pm/physics/comms.py:324-336 (`margin = m_t.copy(); margin[amb] = ...`)
claim: For 0-d `r` the Thorp margin is `numpy.float64`, which does not support item assignment.
check: reproduced on cafe-burst with `bellhop_available` forced True and `bellhop_tl` stubbed (the real Bellhop branch was not run): array input works, scalar input raises. The test at test_comms.py:207 uses `ambiguous_db=0.1`, so the assignment is never reached. Production callers (stage1.py:532, :545) pass n-d arrays, so no run can hit it. Only `margin` is affected; the other arrays are 0-d.
fix: `m_t = np.asarray(acoustic_margin(...), float)` in `acoustic_link`; check `Tagged(margin, ...)` and the scalar-in test still pass (a 0-d array replaces `np.float64` in `.value`). Test: scalar `r` with `ssp`, `ambiguous_db=60` and `bellhop_tl` monkeypatched; fails before.
sources: C-6

### M-26. `fly_sitl` documents "same fields as fly_sortie for one member" but returns a different dict   (sources: C-7)
severity: minor / status: confirmed / lane: documentation
where: cafe/pm/physics/uas.py:731 (docstring) vs :889-894 (return); `FLAGS` at :51
claim: The returned dict lacks `t_first`, `wp_done`, `n_wp`, `ditched`, `airborne`, `failed`, `launch`, `max_dist_m`, `max_wind_ms`, `sat_s`, `demand_ratio_max`, `t_launch` and the `profile_incomplete` flag; `wind_exceeds_airspeed` and `lost_link` are constant False.
check: holds, by code (not run; SITL needs arducopter). Only slow receipts call it (`_sitl_receipts` reads `track` and `sitl.attitude`); test_budget.py:559-564 forbids stage1.py and pipeline.py naming it. DECISIONS 310 does not state a plan to adopt SITL members, so the `KeyError` risk is hypothetical.
fix: reword the docstring to list the keys actually returned and say the two flags are not modelled; optionally a test comparing the key set (fake firmware as in test_uas.py). Do not fill the missing fields unless a stage adopts SITL members. CHANGELOG line.
sources: C-7

### M-27. USV `no_current_data` is stamped at the start of the step, every other USV flag at its end   (sources: C-8)
severity: minor / status: confirmed / lane: reproducibility
where: cafe/pm/physics/usv.py:567 (before `self.t = t + dt` at :599), :550-553 (`_flag`), :616-632; glider.py `_tf`
claim: A wind or current hole gives `first['no_current_data'] = t`; an insolation hole in the same step gives `t + dt` (60 s in stage 1); the glider stamps everything at step end.
check: holds, by code (not run). The start-position flag at usv.py:508 is stamped t0 on purpose (DECISIONS 356, pinned by test_usv.py:998). DECISIONS 356 says the insolation flag is "the end of the step ... as the glider". `first` feeds `failed_at`, what-if and the report; no verdict or gate changes.
fix: add `self._tf` set at the top of `step()` (mirror the glider), have `_flag` use it, with `__init__` setting `_tf = self.t` so line 508 stays t0; or move `self.t = t + dt` ahead of line 567. Test: a wind-hole USV at dt = 60 gives `first['no_current_data'] == 60.0`, and the same hole in insolation the same value. Amend DECISIONS 356, CHANGELOG.
sources: C-8

### M-28. `PMX=pmdata` (or `data`, `pm`, `tmp`, `../x`) makes `rsync --delete` empty shared data   (sources: D-3)
severity: minor / status: confirmed / lane: robustness / documentation
where: bin/pmx.sh:6 (`D=${PMX:-pm_x}`), :9 (proot-only `[A-Za-z0-9_-]` filter), :14 (`rsync -az --delete ... ./ $H:$R/$D/`); docs/ORCA_RUNNER.md:6; DECISIONS 458
claim: Fake `ssh`/`rsync` echoing their arguments show destinations `cafe/pmdata/`, `cafe/data/`, `cafe/pm/`, `cafe/tmp/` in both runtimes; docker mode has no filter at all.
check: reproduced with stubs (a real `PMX=pmdata` was not run). Two corrections to the report: `tmp` hits `cafe/tmp/`, not every job's `/tmp`; and a `pm_` prefix check does not stop a collision with another agent's `pm_*`. Found additionally: docker mode `PMX=../x` reaches `work/cafe/../x/` (`PMX=..` would reach `~/work`). Reviewer rated it major; the verifier lowered it to minor (needs a human or agent to choose a reserved name; no verdict, number or gate) while noting the data loss potential (18 GB, an hour to copy). The "cannot reach outside" claim is true only for `~/cafe-worker`.
fix: in bin/pmx.sh before line 9 (covers both runtimes) require `D` to match `pm_[A-Za-z0-9_-]+` and exit 2 otherwise; keep the proot filter for `TM`. Test with fake ssh/rsync on PATH: exit 2 and rsync not invoked for `pmdata data pm tmp ../x ..`, `pm_a` accepted. Amend ORCA_RUNNER.md:6 and DECISIONS 458 and say that other agents' `pm_*` can still collide (a per-agent suffix would be needed). CLAUDE.md already uses `pm_<you>`.
sources: D-3

### M-29. `orca_sync.sh` marks `pmdata.done` / `data.done` after a tar that failed   (sources: D-4)
severity: minor / status: confirmed / lane: robustness
where: bin/orca_sync.sh:43 (`tar cf - $dirs | gzip -1` remotely), :44 (`touch $p.done`), :34-35; bin/orca_ready.sh:11 (tests only that the marker exists)
claim: A missing directory in the hard-coded list, a file changing while read, or an I/O error on the 97 %-full disk gives a short valid archive and exit 0.
check: reproduced locally: `sh -c 'tar cf - /nonexistent | gzip -1; echo $?'` prints 0; the local `pipefail` sees only ssh's status, which is the remote shell's last command (gzip). The root step is guarded (line 35 re-checks `usr/bin/env` and `venv/lib`); the pmdata and data steps are not. Not run against the box. No DECISIONS row contradicts a fix.
fix: in orca_sync.sh line 43 make the producer's status the pipeline's (single-process `tar czf -` with `GZIP=-1`, or `pipefail` under bash) and mirror it at line 34; gate `touch $p.done` on a content check (`test -d` of the hard-coded dirs; an equivalent for data); optionally re-check in orca_ready.sh. GNU tar exits 1 for "file changed as we read it": tolerate rc 1, fail on rc >= 2. Keep the `ORCA_SRC='sh -c'` rehearsal override working (no `pipefail` in `sh`). Test: a source whose tar fails gives nonzero exit and no `.done`.
sources: D-4

### M-30. Three mutants of reader code survive their tests (tao A/B twin window, tao `MIN_IN_BIN` default, `tree_sha256` path)   (sources: D-5)
severity: minor / status: confirmed / lane: tests
where: cafe/pm/env/tao.py:106 (`_candidates`: `- 10 * 86400`), :51 and :255 (`MIN_IN_BIN = 3`); cafe/pm/env/remote.py:146 (`h.update(f.relative_to(root)...)`); cafe/pm/env/surface.py:58 (alias); tests/test_tao.py, tests/test_remote.py
claim: Each mutant leaves `test_tao.py` / `test_remote.py` green.
check: reproduced on cafe-burst in a detached worktree. (a) `- 0`: test_tao.py and test_ingest_fetch.py pass; (b) `MIN_IN_BIN` 3 to 1: both plus `test_pipeline.py -k tao` pass (the one default-need test has 6 samples per bin; others pass `need=`); (c) deleting the name update: stronger than reported, test_ledger, test_audit and test_surface also pass (none swaps chunk names). Live paths: pipeline.py:750/:863 use the default `need`, tao.py:136 calls `_candidates`. No DECISIONS row covers the 10-day rule or the 3-sample default. `tao._bin`'s default `half` is unmutated and likely the same.
fix: tests only. (1) `tree_sha256`: two stores with the same chunk files under swapped names hash differently; an added empty file changes it. (2) `_candidates`: deployments at t0-5d (twin), t0-30d, t0+2d: first and third kept, second dropped, plus the exact 10-day boundary. (3) `_bin`: with no `need=`, 2 samples give NaN and 3 a value; same for `half`. Each must fail on its mutant.
sources: D-5

### M-31. `tao._series` treats a file with no `_QC` variable as all-good   (sources: D-6)
severity: minor / status: partly / lane: data / robustness
where: cafe/pm/env/tao.py:175 (`... if qc_of + '_QC' in ds else np.ones(len(t))`); tests/test_tao.py:192
claim: A file with `WSPD_QC` all 4 keeps 0 of 36 samples; the same file without it keeps 36 of 36, so a renamed or dropped QC variable silently disables the filter.
check: the behaviour is accurate but deliberate and tested: `test_qc_without_a_flag_variable_keeps_everything` pins it since the first commit 9e0bdc7, and no DECISIONS row covers it (44 gives only the flag sets). Not run (code read). No real file with a missing QC variable was found; the q9 `tao_compare.json` has n=144 for the moorings read, so QC is present and applied. The "feeds the fitted wind priors" part was not traced. One line covers all four TAO variables; hycom.py:158 fills NaN and fails closed (not a sibling).
fix: defensive hardening, optional. Edit line 175 only: when the `_QC` variable is absent raise `ValueError` naming file and variable, or (softer, avoiding aborting the whole fetch) score the file 0 in `fetch_tao` so another deployment is picked. Replace the test with one expecting the refusal (must fail on the old code). New DECISIONS row, CHANGELOG. Offline caches built from files without QC would stop loading.
sources: D-6

### M-32. `tao.compare` holds air temperature, humidity and SST constant outside their own record   (sources: D-7)
severity: minor / status: confirmed / lane: data / numerics
where: cafe/pm/env/tao.py:309 (`np.interp(t, m[v]['t'], m[v]['value'])`); cafe/pm/pipeline.py:~744 (verbatim copy feeding `tao.wind_to_10m`)
claim: With wind every 10 min for 6 h and airt/rh/sst only at 0 and 3600 s, the COARE 4 to 10 m lift at 5 h uses the 0-1 h values, with no warning.
check: reproduced on cafe-burst. The effect is small: a 2 K air drift moves the bias by 0.023 m/s (0.4 % of 6 m/s); the bounded difference COARE against log is 0.15 m/s here and 2-3 % in DECISIONS 44; below the existing 1-1.7 m/s RMSE. Real gaps in the q9 TAO cache were not checked (n is 144-145 for most moorings). The pipeline.py copy builds the fitted wind prior and `tao_compare.json`, so a fix in `tao.compare` alone leaves it.
fix: one helper in tao.py (`_air_at(m, t, gap_s)`) used by `tao.compare` and by pipeline.py:~744: interpolate within the record, NaN beyond a limit (say 1 h) from the nearest valid sample; `wind_to_10m(coare)` falls back to the neutral lift where any of airt/rh/sst is NaN (as the `auto` path does). Put the gap limit in assumptions.yaml. Test: the record above gives the log-law lift at 5 h; fails before. New DECISIONS row. Stored `tao_compare.json`, `priors_fitted.json` and the golden would be re-based at code freeze. pipeline.py is a hub file (batch A).
sources: D-7

### M-33. A gofs31 mission with `ocean.path` not ending in `.zarr` can never be fetched   (sources: D-8)
severity: minor / status: confirmed / lane: robustness
where: cafe/pm/pipeline.py:417, :428-429 (`fetch_gofs(..., store.parent, name=store.stem)`), :436-437; cafe/pm/env/hycom.py:365 (writes `<name>.zarr`); cafe/pm/env/ocean.py:29-30; cafe/pm/config.py:312-316; cafe/schemas/mission.json:29
claim: `path: /data/ocean/my_gofs` is fetched to `my_gofs.zarr` and then the check on `my_gofs` fails after every fetch; `x.v2` becomes `x.zarr`.
check: holds, by code and pathlib arithmetic (pipeline not run). `fetch_gofs` keeps its parts so a rerun does not download again, but the check still fails. No DECISIONS row contradicts (21, 314, 318, 352). `gofs_run.v2.zarr` is fine. The lab path (`ingest_lab_hycom`) was not checked for a similar suffix assumption.
fix: preferred (a): in config.py near line 312, for `source: gofs31` with a `path`, require the `.zarr` suffix and raise ConfigError naming `environment/ocean/path`, before any download. Alternative (b): `ocean.store_path` appends `.zarr`. Test: a gofs31 path `/x/my_gofs` raises at `load_mission`; `.zarr` and `*.v2.zarr` still load. Update fixtures with a suffixless path. Amend DECISIONS 318.
sources: D-8

### M-34. `bin/pmx.sh` reports success for a dead detached job when another tmux session's name contains `$TM`   (sources: D-9)
severity: minor / status: confirmed / lane: robustness
where: bin/pmx.sh:20 (`sleep 3 && tmux ls | grep $TM`)
claim: With sessions `rev9a_one` and `rev9b_edge`, `TM=rev9 ... pmx.sh false` exits 0 though the job died at once.
check: reproduced on cafe-burst (log `rc=1`, script exit 0). A job that finishes within 3 s exits 1 even on success; one that dies after 3 s exits 0. Only this line; the proot branch shares it. No DECISIONS row covers it.
fix: `tmux has-session -t =$TM` (exact match; needs tmux 2.1+, check the orca tmux from orca_setup.sh); better, pass if the session exists or `~/logs/$TM.log` already ends in `rc=0`, so a quick successful job is not a failure. Test in test_config_docs.py: line 20 has no bare `grep $TM` and has the exact match.
sources: D-9

### M-35. `bathy.from_gofs` gives sigma 0 where the deepest valid level is the last (5000 m) and no bias term   (sources: D-10)
severity: minor / status: confirmed / lane: honesty / data
where: cafe/pm/env/bathy.py:152-163 (`np.diff(z, append=z[-1])[k] / np.sqrt(12.0)`); cafe/pm/env/hycom.py:46-47 (`GOFS_DEPTHS`); tests/test_bathy.py:159-166; docs/PHYSICS.md:439
claim: A node wet to 5000 m reports depth 5000 with sigma 0 though the floor is unbounded below; for other nodes the floor is in `[z_k, z_k+1)`, so the depth is biased shallow by half a spacing and sigma = spacing/sqrt(12) omits the offset.
check: holds, by code. The zero is pinned by test_bathy.py:162-165. Reachable only when GEBCO is missing and the GOFS fallback is used (not in q9: the report cites GEBCO_2026). No DECISIONS row contradicts a fix (27, 99). `from_umwm` / `from_gebco` use `_relative` and are unaffected.
fix: in `from_gofs` only: for the open-ended last level return 5000 m as a lower bound with a large stated sigma (previous spacing, or an `assumptions.yaml` bathy key with a `why`); for bounded levels use `z_k + spacing/2` with sigma `spacing/sqrt(12)`, or keep `z_k` with sigma sqrt((spacing/sqrt(12))^2 + (spacing/2)^2). Update source string, docstring, PHYSICS.md:439. Test: amend test_bathy.py:159-166 (fails on the old code). Seafloor-contact numbers from the GOFS fallback will move. DECISIONS row, CHANGELOG.
sources: D-10

### M-36. `orca_sync.sh` ignores an unknown part name and can replace the root filesystem under a running job   (sources: D-11)
severity: minor / status: confirmed / lane: robustness
where: bin/orca_sync.sh:20-21 (`want`/`todo`), :35 (`rm -f root.done && rm -rf root && mv root.new root`), :30, :47; bin/proot_run.sh
claim: `sh bin/orca_sync.sh <ip> pmdta` copies nothing and prints "== done"; nothing checks for a running `proot_run.sh` before replacing `root`.
check: reproduced for the part-name half by running `want`/`todo` in isolation (all four parts skipped); the script was not run against real hosts. grep finds no lock, pgrep or flock in proot_run.sh, orca_ready.sh or orca_setup.sh. Line 30 re-extracts root automatically when the image id differs, so a no-argument run can replace root too. No DECISIONS row contradicts a fix (458).
fix: in the remote heredoc, right after `PARTS=$3`, loop over `$PARTS` and exit 1 "STOP: unknown part X (proot root pmdata data)". Before line 32 add a guard refusing when a process runs from `cafe-worker/root` (pgrep on the `cafe-worker/bin/proot` path only, as orca_setup.sh does), overridable with `FORCE`. Test with the `ORCA_SRC`/`ORCA_DST` rehearsal env and `PARTS=pmdta`: nonzero exit, no "== done". Check trailing-slash part names.
sources: D-11

### M-37. `orca_setup.sh undo` logs out of Tailscale after killing `tailscaled`, and deletes the folder under running jobs   (sources: D-12)
severity: minor / status: confirmed / lane: robustness
where: bin/orca_setup.sh:35 (`stop_ours; tailscale logout 2>/dev/null || true; rm -rf -- "$W"`), :12-16 (`stop_ours`), :36, :68
claim: `logout` talks to a socket nobody serves, fails, and the failure is swallowed; the node key stays valid; any proot job of ours keeps running while its folder is deleted.
check: holds, by code (not run, by rule). SIGTERM does not deregister a node; the only mitigation is the line telling the owner to remove `orca-cafe` in the admin console. HANDOFF says no real job has moved to orca yet, so the job half is unlikely to bite today. No DECISIONS row or test covers undo. `stop_ours` at line 68 (restart) must keep stopping only the two daemons.
fix: in the undo branch only: (1) before stopping anything, list processes whose `/proc/PID/exe` is under `$W` other than the two pid-file daemons; print and exit 1 (or kill by the same exe-under-`$W` test, never by name); (2) run `logout` first, with `timeout 10`, and print its failure instead of hiding it; (3) replace `sleep 1` with a wait until the two pids are gone, then `rm`. Test with a stub `tailscale` recording call order and a fake process under `$W`.
sources: D-12

### M-38. `orca.assemble` overwrites the three stores before it replaces the old manifest   (sources: D-13)
severity: minor / status: confirmed / lane: robustness / reproducibility
where: cafe/pm/env/orca.py:330, :337, :345, :355 (`to_zarr(mode='w')`), :362 (manifest written last); cafe/pm/pipeline.py:403-411, :446, :526 (`_orca_covers` trusts the manifest alone)
claim: If the process dies (or M-6 fires) after `wrf.zarr` is rewritten and before the manifest is replaced, the old manifest still covers the old window and the cache is half new, half old.
check: reproduced on cafe-burst by injecting an `OSError` into the `umwm.zarr` write: manifest unchanged, `_orca_covers` still True, `wrf.zarr` and `wrf3d.zarr` already rewritten. The reviewer overstates it: retrying the same extended window is not affected (the old manifest does not cover the larger window); it bites only when the next request is covered by the old manifest (original window, sub-window, smaller box, another mission). A truncated store from a kill mid-write was not reproduced (rests on `mode='w'` semantics). Recoverable by deleting the cache; the ledger `tree_sha256` notices at ingest. M-6 is the likely trigger.
fix: in `orca.assemble`, unlink `out/manifest.json` (`missing_ok`) before the first `to_zarr`; `read_json` returning `None` already means "fetch again" (DECISIONS 315). The hourly parts are kept, so the cost is re-assembly only. Test: monkeypatch `to_zarr` to raise on `umwm.zarr` after a good assemble: manifest absent and `orca_covers` False; fails now. Do with M-6 (same function).
sources: D-13

### M-39. `pm.sh` syncs without `--delete`, so a file removed from the tree still runs on the server   (sources: D-14)
severity: minor / status: confirmed / lane: reproducibility
where: pm.sh:13 (rsync, no `--delete`; header comment says outputs must survive), :17 (`CAFE_GIT_SHA` from the laptop); bin/pmx.sh; cafe/pm/pipeline.py:50-61 (`code_digest`); docs/RUNBOOK.md:46; Makefile / audit.py:51 (`MUTATION_CMD`)
claim: After deleting `tests/test_x.py` or `cafe/pm/old.py` locally, `./pm.sh python -m pytest` still collects it, and the ledger `git_sha` is the laptop's.
check: holds, by reading (rsync semantics; not run). `code_digest` hashes every `cafe/**/*.py`, so a stale module changes the digest, but nothing compares it with the commit. The gates run on whatever is on the server. pmx.sh already uses `--delete`. No DECISIONS row requires no-delete; the reason is only the header comment. `docs/mutation.json` is also a server-written output.
fix: in pm.sh add `--delete` and exclude every server-written output (`report`, `config/throughput.json`, `docs/mutation.json`, plus any path the RUNBOOK names) alongside the existing excludes; never `--delete-excluded`. Better, one shared exclude list sourced by pm.sh and pmx.sh. Test in test_config_docs.py: pm.sh has `--delete` and each output path is excluded. A missed output path is wiped on the next sync; the shared `pm` dir is used by concurrent agents (CLAUDE.md: use pmx.sh). DECISIONS row, CHANGELOG.
sources: D-14

### M-40. `proot_run.sh` stop and sweep behaviour has no automated test, and ORCA_RUNNER does not say it was run   (sources: D-15)
severity: minor / status: confirmed / lane: documentation / tests
where: bin/proot_run.sh:14-25; tests/test_runners.py (static and dry-run checks only); docs/ORCA_RUNNER.md "Stopping a job" (line 18), rehearsal table (lines 27-40); DECISIONS 458
claim: TERM to the whole job, KILL after 10 s, kill -9 plus sweep, and a second job during a first are stated as facts with no test.
check: the verifier ran the real, unmodified script on cafe-burst with a fake `proot` that ignores TERM and spawns a child: TERM gave rc 143 after 10 s, the run dir removed and no process left; kill -9 on the wrapper left the group running and its dir; a second job did not sweep the live orphan's dir; after the orphan was killed the next start removed the stale dir. All as documented, so the logic is right and the claim true; real proot on orca's 5.10 kernel was not run. Siblings equally untested: orca_setup.sh:14, orca_sync.sh's trap.
fix: one test in test_runners.py: scratch HOME with a fake proot (`trap '' TERM; sleep & wait`), `root/usr/bin/env`, `root.done`, `app`/`pmdata`/`data` dirs, `CAFE_MIN_FREE_GB=0`; run `sh bin/proot_run.sh app x` with `Popen`, SIGTERM, assert rc 143 within about 15 s, no `run.*` dir, no surviving group; a second case with SIGKILL as above; clean the group in a `finally`. Add an env override for the grace (`PM_STOP_GRACE`, default 10) so it runs fast. No name matching `audit.BANNED`. Add a rehearsal row to ORCA_RUNNER.md saying what was run (fake proot) and what was not (real proot).
sources: D-15

---

## Root causes

Clusters, each with the one place the fix belongs and the sibling instances (finding numbers).

1. **A name-or-path or path-identity rule re-implemented per consumer instead of shared.** One resolver per concept.
   - Platform name or path (M-1): `config.platform_path`; siblings: report.py:451 label, credibility keys, glider/usv "not suffix" rule against config's ".yaml/.yml".
   - Run directory identity (M-19): one `_resolve` in ledger.py used by `audit` and `done()`; sibling: M-12 (mission and out are the same file).
   - Store path against source path (M-5): the guard in `ingest_lab_hycom`; sibling: M-33 (`store` against what `fetch_gofs` writes).
   - Reserved shared directory names (M-28): the one `D` check in pmx.sh; siblings M-39 (pm.sh `--delete` list), M-34 (the same script's success test).

2. **Input is not validated at the trust boundary; failure comes later, hours into a run or as a traceback.** Fix at load time or in the shared validator.
   - `load_mission` (config.py): M-2 (unshare aliases), M-13 (identical waypoints), M-20 (empty box), M-33 (gofs31 suffix).
   - `budget.plan` / CLI: M-11 (`--gpu-mem-gb`), M-18 (`--drop` all, in `whatif.answer`).
   - Platform loaders (`check_params` tables): M-22 (mission_defaults keys).
   - Stored-file readers: M-4 and M-23 (`_read_receipt` / `stale_wall_receipts` in wallmodel.py), M-31 (tao QC variable).

3. **A resource or write that is not closed or ordered, leaving a half-written state.** Fix inside the one function.
   - `orca.assemble`: M-6 (open handles) and M-38 (manifest not invalidated first); fix both in the same function, in that order.
   - `report --run` writes outputs without the ledger (M-16): in `_report`.
   - Shell scripts that report success without checking the producer: M-29 (tar pipeline), M-36 (unknown part, root swap), M-37 (undo order), M-34 (tmux name match).

4. **Each vehicle model guards its environment lookups separately, so the third class lacks what the other two got.**
   - `uas.make_wind` (M-3); siblings: M-27 (USV stamps `no_current_data` at step start, glider at end; fix with an `_tf` as the glider has), M-26 (`fly_sitl` contract).

5. **Two independent implementations of the same rule drift apart.**
   - Wall-model receipts: `stale_wall_receipts` (gate) against `receipts()` (table) (M-23); same function as M-4.
   - Divergence inferred from `n < steps` instead of reported by `nest.simulate` (M-24).
   - Tao air interpolation duplicated in `tao.compare` and pipeline.py (M-32).
   - Speed-sanity sentence written twice, in report.py and credibility.py (M-7).

6. **The report prints the plan, a constant or a raw Python value as a result.** Fix in the single renderer.
   - M-10 (`_emulator` ignores `design.json`), M-7 (10 m ratio against an anemometer-height ratio), M-14 (`None`, dict repr), M-21 (caption "the horizon"), M-17 (a GO with no samples; a recorded decision, lead's call).

7. **Constants and measurements carried from one machine or run to another without a check, and docs quoting a single run as general.**
   - `budget.measurement_warnings` (M-9); docs: M-8 (amend RUNBOOK 4 and DECISIONS 444); sibling: M-35 (a sigma that claims more than the data back).

8. **Tests pin the fix they shipped with, not the rule they rely on.** Tests only, in the file that owns the rule.
   - M-15 (direction spread, u* band), M-30 (tao twin window, `MIN_IN_BIN`, `tree_sha256` names), M-40 (proot stop and sweep). Same shape in the unmutated siblings named in each check.

---

## Batches

Six batches, no file shared between them. Within a batch the findings are done in the order listed (shared files). DECISIONS.md, CHANGELOG.md, docs/RUNBOOK.md, docs/ORCA_RUNNER.md, docs/PHYSICS.md and QUESTIONS_FOR_LAB.md belong to no batch: the lead appends the DECISIONS rows and edits the docs in one pass at the end, so the sentences describe what was built. Hand-offs between batches are named in the batch (the other batch's part is a single line); A runs before B and C where a hand-off depends on it.

### Batch A: mission input, CLI, run control, ledger, budget, TAO
- findings: M-1, M-2, M-9, M-11, M-12, M-13, M-14, M-15, M-16, M-18, M-19, M-20, M-30, M-31 (optional), M-32, M-33; M-8 is documents only (its code part is M-9)
- order: M-2, M-13, M-20, M-33, M-1, M-14, M-12, M-16, M-19, M-9, M-11, M-18, M-31, M-32, M-15, M-30 (M-31 and M-32 share tao.py)
- files: cafe/pm/config.py, cafe/pm/pipeline.py, cafe/pm/whatif.py, cafe/pm/__main__.py, cafe/pm/audit.py, cafe/pm/ledger.py, cafe/pm/budget.py, cafe/schemas/mission.json, cafe/pm/env/tao.py, cafe/pm/env/remote.py, cafe/pm/env/surface.py, cafe/pm/env/perturb.py (read only for M-15), tests/test_config.py, test_whatif.py, test_cli.py, test_audit.py, test_ledger.py, test_budget.py, test_tao.py, test_remote.py, test_pipeline.py, test_perturb.py, test_ingest_fetch.py
- hand-offs out: M-1 resolver is used by batch B (report.py:451, credibility keys) and batch C (suffix rule); M-14 gives B the `report.py:1197` None rendering; M-13 gives C the constructor de-duplication; M-9 gives B the report machine-block flag.

### Batch B: report, credibility, stage 1 summary
- findings: M-7, M-10, M-17, M-21, plus the hand-off lines of M-1 (report.py:451, credibility keys), M-3 (`MODE_TEXT`), M-4 (`credibility._json`), M-9 (machine block), M-14 (`dominant_mode` text)
- order: M-21, M-7, M-10, M-17, then the hand-off lines
- files: cafe/pm/report.py, cafe/pm/credibility.py, cafe/pm/stage1.py, tests/test_report.py, tests/test_credibility.py, tests/test_stage1.py
- run after A and C so the resolver, the new UAS flag and the plan-note field exist. M-10 builds its note formatter in report.py (not budget.py). M-17 is a lead decision; skip it unless the lead says so.

### Batch C: vehicle physics
- findings: M-3, M-22, M-25, M-26, M-27, plus the hand-off lines of M-1 (the suffix rule in glider/usv/uas `load_platform`) and M-13 (drop consecutive duplicate waypoints in the constructors)
- order: M-22, M-27, M-3, M-25, M-26, then the hand-off lines
- files: cafe/pm/physics/uas.py, cafe/pm/physics/usv.py, cafe/pm/physics/glider.py, cafe/pm/physics/comms.py, cafe/pm/physics/__init__.py, tests/test_uas.py, test_usv.py, test_glider.py, test_comms.py, test_platform_required.py
- hand-offs out: M-3 adds `no_current_data` to `uas.FLAGS`; batch B adds the `MODE_TEXT` entry. M-22's stage-3 and report readers need no edit once the loader refuses.

### Batch D: stage 3
- findings: M-4, M-23, M-24
- order: M-4, M-23 (same functions), then M-24
- files: cafe/pm/stage3/wallmodel.py, cafe/pm/stage3/windows.py, cafe/pm/stage3/pipeline_windows.py, cafe/pm/stage3/nest.py, cafe/pm/stage3/lbm.py, tests/test_stage3.py
- hand-off out: `credibility._json` (M-4 sibling) to batch B.

### Batch E: runner scripts and their tests
- findings: M-28, M-29, M-34, M-36, M-37, M-39, M-40
- order: M-28, M-34, M-39 (pmx.sh and pm.sh share the exclude list), then M-29, M-36, M-37, M-40
- files: bin/pmx.sh, pm.sh, bin/orca_sync.sh, bin/orca_ready.sh, bin/orca_setup.sh, bin/proot_run.sh, tests/test_runners.py, tests/test_config_docs.py
- note: the `PM_STOP_GRACE` override (M-40) changes proot_run.sh, so M-40 follows M-36. Docs for these (ORCA_RUNNER.md, RUNBOOK) in the lead's doc pass.

### Batch F: environment stores (HYCOM lab ingest, orca cache, bathymetry)
- findings: M-5, M-6, M-38, M-35
- order: M-6, M-38 (same function), then M-5, M-35
- files: cafe/pm/env/hycom.py, cafe/pm/env/orca.py, cafe/pm/env/bathy.py, tests/test_hycom.py, tests/test_orca.py, tests/test_bathy.py
- note: M-5's guard sits in `ingest_lab_hycom`, so `__main__.py` and config.py (batch A files) need no edit. M-38 reads `pipeline.orca_covers` but needs no change there.

Coverage check: M-1 to M-40 each appear in a batch (M-8 is documents plus the code in M-9; M-17 is the lead's decision and listed under B; M-31 is optional hardening, scheduled in batch A.)
