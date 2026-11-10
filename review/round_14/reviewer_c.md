# Round 14, reviewer C

Scope: line by line `cafe/pm/pipeline.py`, `config.py`, `__main__.py`, `audit.py` (commit `b42ae10`, code of `20537b1`), every branch against DECISIONS and `docs/RUNBOOK.md`; kill and resume of a `ci_fixture` run at each stage boundary.

Method. Detached worktree `../cafe-rev14-c` (removed at the end), orca at 2 CPUs from `pm_rev14_c`, data from a private copy of the synthetic ci_env (`/data/runs/rev14_c_data`, built by `tests.fixtures.ci_env.make`), `CAFE_OFFLINE=1`, every run under `/data/runs/rev14_c_*` with its own `--emulator-table`; nothing touched the shared table. Processes were stopped only by the exact pid or process group I started. Mutants were applied in memory by re-compiling one function (`inspect.getsource` + `exec`), no file edited.

## Kill and resume: result

An unbroken run (`ref`, 181 s) against runs killed with SIGKILL to their process group and resumed with the same command:

| kill point | run | result |
|---|---|---|
| right after the ingest ledger | `brk` | resumed, equal |
| 15 s into stage 1, then right after the stage-1 ledger | `k3` | equal |
| 12 s into stage 3 (windows ledger +12 s), then at the stage-3 boundary (landed 1 s into stage 1b) | `k3` | equal |
| 30 s into the emulator stage (before the table append), then right after the first `flip search` line (table already appended, ledger not yet written), then 1.2 s into the report | `k4` | equal |
| Ctrl-C (SIGINT with Python's handler, as a terminal leaves it) 8 s into stage 1, 8 s into stage 3, 25 s into the emulator | `k6` | equal |
| resume of a completed run under another CPU count (3 instead of 2), run directory copied | `k3w` | stages 1 to refit up to date, emulator and report rerun, as RUNBOOK says |

"Equal" means: `stage1/res.pkl`, `stage1b/res.pkl` byte-identical (sha256), every JSON of the run identical (recursive leaf-by-leaf compare, `rev14_c_cmp.py`) except timings (`machine.*`, `wall_s`), the run directory name, the emulator table's file name and the sha256 of the two files that contain those names (`design.json`, `credibility.json`); every stage's ledger `ok`, same checks and values, same output hashes for ingest to refit; `audit --ledgers-only` prints `0 problem(s)` for all six resumed runs. After a kill that came after the table append, the table has 12 rows (not 24: `row_key` replaces) and `emulator/train_input.parquet` is an empty frame of 49 columns where the unbroken run's is an empty frame of 12 (`rev14_c_p6.py` output; zero rows in both, bytes differ). No stale ledger was accepted, no half-written file was read back.

(My first two chains were wrong harnesses, not findings: a `kill -9 -$p` sent before the child had called `setsid`, and a SIGINT sent to a background job that the shell had left ignoring it. The runs above are the corrected ones.)

Mutation check on `pipeline.py` with the tests that name these functions (`tests/test_pipeline.py`): killed: the 95 % bound turned into a 90 % bound (`chi2.ppf(0.05` to `0.10`), the 6 h separation of windows `>=` to `>`, the pad rounding to half a degree dropped, `_covers` with start and end swapped. Survived: findings C-10.

## Findings

### C-1. `run --seed S` rewrites `mission.yaml` so that a quoted string like `"1e5"` comes back as a float, and the copy can no longer be loaded
severity: minor
lane: robustness / reproducibility
where: cafe/pm/pipeline.py:1618 (`yaml.safe_dump`), cafe/pm/config.py:61 (the extra implicit float resolver of `_Loader` that `safe_dump` does not have)
reproduction: on orca (`/data/rev14_c_p16.py`): `ci_fixture` with `glider_1n` renamed to the quoted string `"1e5"` (a valid id: `^[A-Za-z0-9_\-]+`) loads. The text `pipeline.run` writes with `--seed 5`, `yaml.safe_dump(dict(_yaml(path), seed=5), sort_keys=False)`, contains `- id: 1e5` unquoted (the default dumper reads `1e5` as text). `load_mission` on that copy raises `ConfigError: vehicles/1/id: 100000.0 is not of type 'string'`. The same holds for `name`, `platform` and any other string of that shape. `report --run`, `whatif --run` and `run --mission <run>/mission.yaml --out <run> --seed S` (RUNBOOK step "A finished run can be resumed ... from its own copy") read this file.
why it matters: the copy the RUNBOOK tells the user to resume from is not loadable by the code that wrote it, for a mission that loads fine; the seed branch is the only writer that dumps instead of copying.

### C-2. Ingest stops with a raw KeyError traceback when a cached manifest is a JSON object without `t0` / `t1`
severity: minor
lane: robustness
where: cafe/pm/pipeline.py:1053 (`_covers`, reached from `_orca_covers` :583), cafe/pm/pipeline.py:363 (`_tao_covers`, reached from `_tao_cached` :376 and `_copy_covering`)
reproduction: copy the ci_env data, then (a) `echo '{}' > cache/ci_fixture/orca/manifest.json`, or (b) delete `"t0"` from `tao/s2/manifest.json`; `CAFE_OFFLINE=1 python -m cafe.pm fetch --mission missions/ci_fixture.yaml --out D/run` ends `File "/app/cafe/pm/pipeline.py", line 1053, in _covers ... KeyError: 't0'` (b: line 363, `KeyError: 't0'`), no `error:` line. `orca.read_json` returns None for a file that is not an object (handled: refetch) but passes any object, so an older-schema or hand-edited manifest takes this path. RUNBOOK (troubleshooting, "An empty or truncated manifest ... needs no deleting: the parts are fetched again") promises the refetch only for the unreadable kind. A `t0` of `"garbage"` is handled (`error: 'garbageZ' is not a calendar time`).
why it matters: `fetch` is documented as safe to rerun and to heal a damaged cache; here it dies before it can.

### C-3. `_gebco_cached` does not catch the error `np.load` gives for an empty file, so `fetch` cannot replace a zero-byte GEBCO cut
severity: minor
lane: robustness
where: cafe/pm/pipeline.py:385-391 (`except (OSError, ValueError, KeyError, zipfile.BadZipFile)`), cafe/pm/env/bathy.py:145 (`np.load(path)`)
reproduction: copy the ci_env data, `: > bathy/gebco2026_*.npz`, run the `fetch` of C-2: ends `File "/app/cafe/pm/env/bathy.py", line 145, in from_gebco ... z = np.load(path) ... EOFError: No data left in file`. A file of `garbage` is handled (`gebco_present` check fails, refetch advice); a truncated zip is `BadZipFile`. Without `CAFE_OFFLINE` the same traceback should end the ingest instead of downloading the cut again (by the code path: `_need` calls `present()` before `fetch()`; not run, it needs the network).
why it matters: RUNBOOK step 3 says `fetch` "is safe to interrupt and rerun"; a download tool that leaves 0 bytes (full disk) leaves a cache that `fetch` cannot repair.

### C-4. A box with no TAO mooring that has a usable wind fails the whole ingest, although the code's docstring and PHYSICS say the configured priors stand
severity: minor
lane: documentation / honesty
where: cafe/pm/pipeline.py:905-909 (docstring of `_tao`: "without moorings the perturbations.yaml priors stand and the ledger says so"), :931 (`L.check("tao_moorings_compared", n > 0, ...)`) and :936-937, docs/PHYSICS.md:528 ("A mission with no TAO download keeps the perturbations.yaml priors and the ledger says so")
reproduction: copy the ci_env data and set `files`, `positions`, `selected` to `{}` in `tao/s2/manifest.json` (what a fetch for a box outside the array gives), run the `fetch` of C-2: `error: stage ingest: self-checks failed: tao_moorings_compared: moorings with usable wind in the window`, exit 1; ledger `ok` false, the only failed check. The "no TAO download" branch (:912-914) cannot be reached from `s_ingest`, because `_need("tao")` has already failed the stage when `manifest.json` is missing. No mission outside the TAO/TRITON array can be run, and the message names no remedy.
why it matters: either the refusal is intended (then the docstring, PHYSICS 528 and RUNBOOK should say that the mission must lie in the array, and the check's note should say so) or the priors should stand as written.

### C-5. A killed run leaves its shared-environment directory and its worker processes behind
severity: minor
lane: robustness / performance
where: cafe/pm/par.py:156-157 (`tempfile.mkdtemp(prefix="cafe-share-<pid>-")` removed only by `atexit.register(shutil.rmtree, ...)`); no `signal.signal` anywhere in `cafe/pm` (grep)
reproduction: (a) the five kills of the chain-3 run left five `cafe-share-<pid>-*` directories in that job's container `/tmp` (counted in the proot run directory, about 4 MB each for the fixture; the demo's environment is about 9 GB, put in `/dev/shm` when it has 12 GB free, else in `$TMPDIR`). (b) `rev14_c_p12.sh`: `kill -9` of only the parent pid 12 s into stage 1 left its 3 children (two workers and the resource tracker) running 20 s later, state S, parent pid 1, and `/tmp/cafe-share-1783688-*` in place; I stopped them by pid. SIGTERM (what `docker stop` and `proot_run.sh`'s `stop()` send) runs no `atexit` either. Under `docker run --rm` the container's end hides this; on the proot runner of orca the wrapper's `rm -rf $T` does, but a bare machine or a long-lived container keeps up to 9 GB of RAM-backed files and N idle workers after an out-of-memory kill of the parent.
why it matters: the planner sizes workers against memory; the leftovers of one killed run are counted against the next.

### C-6. The seed branch of `run` writes `mission.yaml` with a bare `write_text`, against DECISIONS 739
severity: minor
lane: robustness
where: cafe/pm/pipeline.py:1618 (also :1144 `res.pkl` `write_bytes` and :1430 `shutil.copy`, which the ledger's sha256 protects)
reproduction: by reading. DECISIONS 739 makes `config.write_text` "the one writer of a file that a person or a later stage reads back" and lists `pipeline._dump`; line 1618 writes the file `report` and `whatif` reload ("the copy is what `report` and `whatif` reload", the comment above it) in place. With `--mission <run>/mission.yaml --out <run> --seed S` (the documented flow) the source and the destination are the same file, so a kill or a full disk during the write leaves a truncated mission and no original (plan.json only keeps its path). `res.pkl` and the copy are caught by `ledger.done` (hash), mission.yaml is not.
why it matters: the sweep's claim of "one atomic writer" is false for one file; the window is small.

### C-7. The commands the ingest tells the user to run are not shell-quoted
severity: minor
lane: documentation / robustness
where: cafe/pm/pipeline.py:168, :284, :1038, :1047 (`f"{FETCH_CMD} {ctx.mission_path}"`); contrast cafe/pm/__main__.py:216 (`shlex.quote`)
reproduction: `rev14_c_p15.sh`: mission copied to `/data/runs/.../my missions/m 1.yaml`, empty cache, `CAFE_OFFLINE=1 python -m cafe.pm fetch --mission "<that path>"` prints `... run `python -m cafe.pm fetch --mission /data/runs/rev14_c_sp/my missions/m 1.yaml``, which the shell splits into three words. The test of round 13 that parses every advised command with `build_parser` uses paths without a space.
why it matters: a laptop path with a space ("My Drive") is the common case for the lab user; the advice they paste fails.

### C-8. A 300-byte mission file with nested YAML aliases makes `load_mission` take time exponential in the nesting
severity: minor
lane: robustness
where: cafe/pm/config.py:96-102 (`_finite` walks the structure as a tree, one visit per alias use), :423-428 (`_unshare` does the same)
reproduction: `rev14_c_p10.py`: the ci_fixture plus `x: &a0 [0 x10]`, `x1: &a1 [*a0 x10]`, ... one more level each: 4 levels (10^5 nodes) 0.1 s, 5 levels 0.6 s, 6 levels (10^7) 6.1 s on orca; ten times per level, so 9 levels is about 100 minutes and 12 about 70 days. RUNBOOK says "YAML anchors and aliases are allowed". It is refused in the end (extra property), but only after `_finite` has finished.
why it matters: `validate` on an odd but valid file does not return; a visited-set on `id(node)` (a shared node is finite or not once) removes it.

### C-9. `code_digest` hashes every file with a dot in `config/`, and `bin/sync_filters` does not keep `.DS_Store` out of a sync
severity: minor
lane: reproducibility
where: cafe/pm/pipeline.py:57-61 (`root.joinpath("config").rglob("*.*")`), bin/sync_filters (no `.DS_Store`, `*~` or `*.swp`)
reproduction: `pathlib.Path("config").rglob("*.*")` on a directory holding `.DS_Store`, `a.json`, `x.json~`, `sub/.a.swp` returns all four (checked); Finder creates `config/.DS_Store` as soon as the folder is opened on the macOS laptop, `pm.sh` and `bin/pmx.sh` send it, and the server's `code_digest` is then not the digest of the committed tree: every ledger hash, the stored-result and receipt digests and the emulator rows' `code_digest` differ from a clean checkout's. (`./.DS_Store` exists at the repo root now; none in `config/` or `platforms/`.)
why it matters: "same code, same report" and the golden's code digest silently depend on what the laptop's file manager left in a folder.

### C-10. Tests of `fit_wind_error` do not pin two terms of the estimator
severity: minor
lane: statistics (test strength)
where: cafe/pm/pipeline.py:897 (`sampling = ... s2 / n * (1 + rho) / (1 - rho)`), :901 (`noise = np.sqrt(np.average(s2, weights=n - 1))`); tests/test_pipeline.py:936-960, 2939-2950
reproduction: `rev14_c_mut.py` on orca, tests selected by `-k "tao or wind or moorings or fit or prior or persistent or hi95"` over `tests/test_pipeline.py` (every test that calls `fit_wind_error` is in that file): the mutant without the AR(1) factor (`s2 / n`) passes, the mutant `np.mean(s2)` for the pooled noise passes. The first is not equivalent: 6 moorings of AR(1) (phi 0.9, sd 1.0) with a true persistent sd of 0.3, 40 seeds: mean fitted persistent 0.354 with the factor, 0.451 without it, largest per-seed difference 0.18 (`rev14_c_p17.py`). The recovery tests use 120 moorings, where the sampling term is negligible against the spread, and the 11-mooring hi95 test only compares the bound with the estimate.
why it matters: the sampling-variance correction is what keeps a short, autocorrelated record from reading as a persistent bias, which is the point of the split; the demo has 11 to 14 moorings.

### C-11. `_sensitivity_cases` leaves an older `stage1b/sensitivity_cases.json` in place, and the report stage takes every `*.json` of the stage directories as inputs
severity: minor
lane: reproducibility
where: cafe/pm/pipeline.py:1394-1395 (early return for a mission without a USV, nothing removed), :1580-1582 (`glob("*.json")` of `stage1b`, `refit`, `stage3`, `windows`, `emulator`), cafe/pm/report.py:466-475 (`_cases` takes `[vid]` of the stored file by id)
reproduction: by reading, not run. Edit-and-rerun in the same `--out` (the default `runs/<name>/<budget>` is the same for an edited mission of the same name): a mission whose vehicle `usv` is a USV leaves `stage1b/sensitivity_cases.json` with a `usv` entry; the edited mission, where `usv` is another class or the USV is gone, does not write the file (:1394) and does not delete it; `--fresh` does not clean the directory either (the code only sets `redo`). The stale file is then recorded as a report input, and `_cases` shows the "brief VPP bias" case under a vehicle called `usv` that is no USV. `recalibrate_subgrid` already does the unlink that this is missing (`out.unlink(missing_ok=True)`, pipeline_windows.py:765).
why it matters: a number in the report that belongs to another mission, inside a ledger that says it was an input.

### C-12. `fetch` leaves the ledgers current only for `--budget quick`
severity: minor
lane: documentation
where: cafe/pm/pipeline.py:95-97 (docstring of `hash_budget`: "so that a fetch into a run directory leaves its ledgers current for `run`"), cafe/pm/__main__.py:170 (`bud = getattr(a, "budget", "quick")`; `fetch` has no `--budget`), cafe/pm/pipeline.py:1604-1605
reproduction: `rev14_c_p1.py`, `Context(m, None, 0, d, hash_budget="quick").hash == Context(m, b, 0, d).hash` is True for `b = "quick"`, False for `"ci"` and `"4h"` (printed). So `fetch --mission M --out D` followed by `run --mission M --budget 4h --out D` runs the ingest again (the `tree_sha256` of every store, about 9 GB for the demo) instead of "up to date".
why it matters: only time, but the docstring states a property that holds for one budget of four.

## Checked and found as stated (no finding)

- `ledger.done` and `audit.ledger_problems` agree on outputs, inputs, `values_only`, shared copies and the chain; a stage rerun after a kill never accepted an old ledger (the previous ledger's sha is an input of the next, and the report stage deletes its own first).
- `padding` (24.4 days gives 9.5, 24.41 gives 10), `ocean_box` poles and width, `_ocean_time_problem`, `_lon_arc_covers`, `fit_wind_error` formulas (Wilson-type AR(1) variance of a mean, the one-sided chi-square bound, the predictive sd), `_chance_miss`'s Beta-Binomial against `conformal_rank`: read against their docstrings and DECISIONS, no discrepancy.
- Parser and error paths run (all exit 2 with an `error:` line, no traceback): `plan --gpus -1`, `--gpu-mem-gb nan`, `validate` of a missing file, `audit` of a missing directory, `report`/`promote-calibration` of an empty directory, `hangar` of a missing platform, `run --out <file>`, `run --emulator-table <empty file>`, `whatif --vehicle nosuch`, `--drop` of every vehicle, `--shift xyz`, `--move "1deg Q"`, `acceptance --out <file>`, `receipts --only nosuch`, `ingest-ocean` on a GOFS mission, `fetch --out <file>`. `audit --pytest-done` through the front door is "unrecognized arguments", as RUNBOOK 309 says.
- Hostile missions (`load_mission` and `Context`): empty vehicle list, empty links, no ship, one vehicle, 30-day window, 1-hour window, zero-length window, seed 2^70 / negative / float / bool, equal go and nogo, pad 0 / negative / 10, upper-case and `..` names, box at the pole: each loads or is refused with a message naming the field. A name that starts with `-` (`-x`) is accepted.
- The banned-token scan is case-sensitive exactly as BRIEF 5.5's grep is (`# todo`, `Placeholder` are not hits), so it is not reported.

## Not covered

See `not_covered` in the structured output.

total: 12 findings (0 critical, 0 major, 12 minor)
