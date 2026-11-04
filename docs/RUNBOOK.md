# RUNBOOK — the TEPEX-C pre-mission simulator, from a clean machine to a report

Follow it top to bottom. Every command is meant to be pasted as written; `<...>` is the only thing you fill in. If a step's
"you should see" does not match, stop there: the troubleshooting table at the end says what each failure means.

## 0. What you need

* Linux with Docker (any user in the `docker` group; no root inside the containers). 8 cores and 32 GB RAM are the machine the quick
  budget is sized for; a GPU is optional (see step 6). The 20 minutes of `--budget quick` count the compute stages with the data already cached.
  The network fetch of step 4 is a separate step whose duration depends on your link, not on `--budget`; the run's ingest stage reports its own
  wall time and says "not counted against --budget".
* About 20 GB of disk: the images are 7.3 GB (`cafe` 2.4 GB + `cafe-pm` 5.0 GB), the demo's data 7.7 GB (the GOFS ocean store
  5.1 GB, the orca WRF/UMWM cache 2.1 GB plus 0.2 GB of derived fields, TAO 0.13 GB, GEBCO 0.03 GB; measured with `du` on homebase, 2026-10-31),
  a run directory about 50 MB.
* Network on the first run only, to: `orca.atmos.washington.edu` (UWIN-CM WRF + UMWM, byte-range reads),
  `ncss.hycom.org` / `tds.hycom.org` (HYCOM GOFS 3.1), `dods.ndbc.noaa.gov` (TAO/TRITON), `dap.ceda.ac.uk` (GEBCO_2026).
  After that every run is offline (`CAFE_OFFLINE=1` makes that a rule: nothing is downloaded, a missing input fails a check
  that names the command to fetch it; `0` or unset turns it off; `true`, `yes` and `on` also turn it on, `false`, `no` and `off` off, and any other value is an `error:` with exit 2).

## 1. Get the code and build the image (once, ~25 min)

```bash
git clone https://github.com/aarohkandy/cafe.git && cd cafe && git checkout premission-step4
make install
```

You should see two images: `docker images | grep -E '^cafe(-pm)? '`. Building `cafe-pm` writes ~6 GB of layers; check
`df -h /` first and run `docker builder prune -f` afterwards.

Every command below runs inside the `cafe-pm` image with this repo at `/app` and a data directory at `/data`. Define the
wrapper once per shell (pick any data directory with the space above):

```bash
export CAFE_HOST_DATA=$HOME/cafe-data && mkdir -p $CAFE_HOST_DATA
pm() { docker run --rm --ulimit core=0 --shm-size 16g -u $(id -u):$(id -g) -e HOME=/tmp -e PYTHONPATH=/app -e CAFE_DATA=/data -e CAFE_GIT_SHA=$(git rev-parse HEAD) \
       -e CAFE_GIT_DIRTY=$(if [ -n "$(git status --porcelain)" ]; then echo 1; else echo 0; fi) \
       -e CAFE_WORK=/data/work \
       -v $PWD:/app -v $CAFE_HOST_DATA:/data -w /app cafe-pm "$@"; }
```

Stage 1 uses every CPU the container may use (`--cpus`; `CAFE_WORKERS=N` overrides), and its workers read the environment from
files in `/dev/shm`, which Docker caps at 64 MB unless `--shm-size` raises it: without it they fall back to the temporary directory, on disk.

Give the container its limits so the plan can see them: add `--cpus N --memory M` to the `docker run` of `pm()` (on homebase `PM_CPUS` and `PM_MEM`, default 8 and 28g). `plan` reads the memory limit (else the host's free memory), needs the environment (0.0031 GB per square degree of the padded box per window day, so 9 GB for the demo; calibrated on that one box and window, so a floor beyond them and not a measurement; or the size on disk of the cache's Zarr stores and the ocean store if that is larger) plus 0.9 GB per worker, caps the workers to what fits (`plan.json` has `workers_by_cpu`, `workers_by_memory` and `workers`; `plan` says when memory capped the count) and refuses a mission for which not even one worker fits (exit 2: a 30-day window on the demo's box with the default pad needs more than 100 GB, reasoned from the model and not measured). The plan is made again when the ingest ends, with the stores then on disk: if it changes, the run prints the new figures and rewrites `plan.json`, and it stops with the sizes named if the workers no longer fit. The demo is refused under about 10 GB and capped below 8 workers only under about 16 GB. `CAFE_WORKERS` and `CAFE_NPROC` must be a whole number of at least 1, else `error: ...` and exit 2; an explicit count is honoured and the plan notes the memory it needs. If `/dev/shm` fills part-way, the error says so and tells you to raise `--shm-size`.

(On homebase this is `./pm.sh <command>`, which also syncs the checkout there and sets the same two variables; data is `~/work/cafe/pmdata`.) The image has no `git`, so the ledgers learn the commit and whether the tree was clean only from `CAFE_GIT_SHA` and `CAFE_GIT_DIRTY`; without the second one a ledger says `"git_dirty": null` and the golden of step 7 cannot be minted or passed (review round 4, M-24, DECISIONS 260). Run `pm` from the repository root, in a git checkout where `git status` works.

Optional, for acoustic links near the ship (review round 5, M-25): `make install` builds no Bellhop. Without it every ambiguous acoustic link (one within about 6 dB of its margin) is judged on Thorp absorption alone, and the report says "Thorp only, Bellhop unavailable" on each such link. To build it (needs the network and the `cafe-pm` image; gfortran is installed inside a throwaway container and nothing is added to an image):

```bash
sh bench/install_bellhop.sh
```

The script writes `bellhop.exe` into `$CAFE_HOST_DATA/bin` (set in step 1; without it, homebase's `~/work/cafe/pmdata/bin`), which `pm()` mounts as `/data/bin`, the first place the code looks. The demo's own acoustic links (555 and 633 km) fail by range and never use Bellhop.

For the UAS autopilot receipts (`make audit` runs them, and one of its tests fails without it): the ArduCopter SITL binary, ArduPilot's own
stable-4.7.1 build, and its two parameter files. The script fetches them and checks each sha-256 (needs the network and `curl`):

```bash
sh bench/install_sitl.sh $CAFE_HOST_DATA/work/sitl
```

`pm()` passes `-e CAFE_WORK=/data/work`, so the code finds them at `/data/work/sitl`.

## 2. Check the install without the network (~10 min)

```bash
pm make ci
```

You should see `report: runs/ci/report/index.html` at the end and exit code 0. This flies every stage at toy resolution on a
synthetic environment (`tests/fixtures/ci_env`).

## 3. Measure this machine (once per machine, ~15 min, with nothing else running)

```bash
pm make bench
```

It writes `config/throughput.json`: OpenFOAM and LBM cell-update rates per core count and the stage-1 cost per vehicle class.
The budgets are wall-clock: every stage is sized from these numbers, so a stale or loaded measurement makes the plan wrong
(`python -m cafe.pm plan` prints what the budget buys and where each rate came from, with the load it was measured at). The stage-1 time it prints is a lower bound (the longest task or the work over the workers; the parent's serial part and worker start-up are not in it), and the report's machine block prints it next to the time stage 1 took. The UAS cost scales with sortie-minutes: the benchmark stores the sortie-minutes of its mission (`sortie_min`), and the planner multiplies the UAS cost by this mission's sortie-minutes per day over the benchmark's, so a mission with more or longer sorties plans (or is refused) accordingly.

To re-measure only the stage-1 cost per vehicle class, on a quiet machine (one-minute load below 2 on 8 cores; the tool refuses to write on a busy one,
records the load before and after, and measures on the demo mission unless you name another):

```bash
pm python bench/throughput.py stage1            # on homebase: PM_CPUS=8 ./pm.sh python bench/throughput.py stage1
```

Run it twice, on a quiet box, and compare the two files: the tool times a warm-up batch and keeps the faster of two timings per size, but a class whose entry says `slope_resolved: false` has a per-member slope that 8 versus 32 members could not resolve (to the planner a batch then costs the same whatever its size). The shipped `config/throughput.json` was measured at load 33 and has the old single-timing method; re-measure at code freeze (review round 4, M-26, DECISIONS 262).

Use this, not `make bench`, for that: `make bench` also runs OpenFOAM. The planner never overruns stage 1: it halves the batch down to 4 members, else
refuses with the shortfall. `--budget ci` is the 10 minute toy profile (8 to 16 members, one LES window part, no refit): it plans and runs on any mission, including the demo, but its numbers are a smoke test, not a verdict; it is meant for `missions/ci_fixture.yaml`.

## 4. Fetch the mission's data (once, ~2.5 h; resumable)

```bash
pm python -m cafe.pm validate --mission missions/tepex_c_demo.yaml
pm python -m cafe.pm fetch --mission missions/tepex_c_demo.yaml
```

`validate` should print `missions/tepex_c_demo.yaml: valid (4 vehicles, 4 links)`. `fetch` is safe to interrupt and rerun (each input is hash-checked and
only missing parts are fetched). `fetch` needs no `--budget` and plans none, so it works for a 30-day or 20-vehicle mission that only fits a larger budget. The HYCOM GOFS store is the long part. To use the lab's own HYCOM instead, set
`environment.ocean: {source: lab_hycom, path: /data/ocean/lab_tepex_c_demo.zarr}` in the mission (`path` is required with `source: lab_hycom`, and `validate` says so if it is missing) and run
`pm python -m cafe.pm ingest-ocean --mission missions/tepex_c_demo.yaml --path /data/<lab dir> --temperature-kind <in_situ|potential>`.

What `validate` enforces about vehicles (it exits 2 with `error: ...` naming the field, so a wrong file is found here and not hours into a run). A vehicle with `base` is a UAS: it takes `sorties`
and `launch_rules` and no `task`. A vehicle without `base` takes a `task` and no `sorties`: a glider flies `station`, `section` or `drift`, a USV `station` or `section`. A `station` task
names the station (`lon`, `lat`; `radius_km`, default 5, and `lost_after_h`, default 6, are optional); for a USV `radius_km` is the distance from the station at which it counts as swept off track. A glider `drift` task needs `heading_to`, the compass heading in degrees
(0 to 360) it swims on: a drift glider has no pass/fail criterion, so its GO means only that the battery and depth limits held on that heading. The platform file must be of the
vehicle's class (a Seaglider or Slocum for a glider, `saildrone_explorer` for a USV, `quad_uas` for a UAS), an acoustic link cannot end at a UAS, every time must be a real calendar time,
every vehicle must be deployed at least 10 min before `window.end`, and a key that is not in the schema (a typo in `task`, `sorties`, `launch_rules`, `shore`) is refused. Numbers outside the model's range are refused too (review round 6, M-9): `max_mean_wind_ms` above 0 and at most 60, `no_gust_front_within_min` 0 to 1440, `radius_km` 0.01 to 1000, `lost_after_h` above 0 and at most 720, `dive_depth_m` 1 to 2000 and, for a glider, between its platform's `min_dive_m` and `rating_m`, `track_tolerance_km` above 0 and at most 1000, and `altitudes_m` distinct and rising. A time must be in quotes (`start: "2023-03-01T12:00:00Z"`): YAML reads it bare as a time and `validate` says so. It also refuses a NaN or infinite number (a missing value is a missing key, not `.nan`), a repeated key, and a leading-zero number such as `010` (YAML reads it as octal 8; write 8, or quote it), naming the field or the line.

A platform file must hold every parameter its model reads, each a finite number in its physical range (the limits are in the message; `radios.yaml` and `modems.yaml` are tables, which `hangar --platform radios` and `modems` check for a source on every entry); `python -m cafe.pm hangar --platform <file>` and `validate` name the file and the field that is missing or out of range. A repeated key or an octal number in a platform file is refused like in a mission.

The mission's `environment.subgrid` block has five switches: `turbulence`, `gust_fronts`, `warm_layer`, `rain_lens`, `ocean_sde`. Each is on unless the mission says `false`; the report's header lists the five and which of them the mission left out.

## 5. Run the mission

```bash
pm bin/run_premission --mission missions/tepex_c_demo.yaml --budget quick --gpus 0 --out runs/quick
```

* `--budget quick` = 20 min, `overnight` = 10 h, `4h` = 4 h (meant for a GPU), each counted over the compute stages with the data cached (step 4 is the
  fetch). `--gpus 0` has no LES windows: each window is sized at plan time, and one that would need more than 100 times the cell-updates its share of the
  stage-3 budget holds at this machine's rate is "not run: the physical lattice viscosity ... needs dx ..., N cells and M cell-updates; this machine does Y in the window's slice ..." (every CPU
  window today except the one smoke window of `--budget ci`, because the lattice viscosity floor of `config/assumptions.yaml` `stage3.nu_lat_floor` cannot be
  met at a CPU's resolution). So **no LES coefficients exist on this machine; sub-grid and refit stay uncalibrated**, and the time goes back to stage 1.
  The free-surface hull window still runs where it fits, on `min(6, workers)` MPI ranks (fewer on a machine with fewer CPUs; `CAFE_NPROC` overrides, a whole number of at least 1) and the plan prices the same number; the glider hull's FEA belongs to its LES window, so it does not run when that window is skipped.
* A vehicle that drifts out of the downloaded box is a failed member (failure mode `left_data`), and the report says how many left and when. The pad around the
  mission box is `box.pad_deg` if the mission sets it, else the window length x 0.5 m/s in degrees (at most 10, reached at about 26 days); set `pad_deg`
  for a long window or a fast drifter and rerun the ingest.
* The run is resumable: rerunning the same command skips every stage whose ledger and outputs are intact. `--fresh` ignores
  the checkpoints. `--seed S` replaces the mission's seed (same seed, same machine bench and the same CPU count = the same `report.json`; stage 1 and 1b are the same at any count, the emulator variants are not, so a resume under another CPU count reruns the emulator and the report).
* You should see one line per stage and finally `report: runs/quick/report/index.html`, exit code 0.

Read, in this order: `runs/quick/report/index.html` (verdicts, failure modes, links, map, the stage-3 windows and why each
was or was not used), `runs/quick/report/credibility.html` (NASA-STD-7009B factors, the ASME V&V 20 rows, every assumed
input), and `runs/quick/report/report.json` (the same numbers, each with its stage, source, uncertainty, receipt and ledger).
Re-render a finished run with `pm python -m cafe.pm report --run runs/quick`.

What if: `pm python -m cafe.pm whatif --mission missions/tepex_c_demo.yaml --run runs/quick --shift 48h` (also `--move "1deg W"`,
`--drop uas`, `--vehicle usv`); it answers from the emulator when it can and runs stage 1 when it cannot, and says which. A UAS shifted by a whole
number of days launches at the same time of day: the command prints `uas: unchanged (...)` next to the answers for the other vehicles. UAS what-if answers use the 10 m scaled wind profile for the candidate and the baseline alike,
so a shifted sortie is not compared across two wind models.

**The emulator needs 100 distinct feature points per vehicle class, and one run does not make that many.** The plan says so before the run (`plan.json`:
"this budget gives N points per class, 100 are needed: the emulator will not train"), and the report's emulator section repeats it. Until the table has them,
every what-if answer comes from Stage 1 and says so. Rows accumulate over runs of identical code (the same code digest): give each run the same
`--emulator-table FILE` (or set `$CAFE_EMULATOR_TABLE`); a repeat of the same mission with the same seed adds no new point (the variants, the members and so the rows are functions of the mission and its seed, and DECISIONS 174 replaces the repeat), so new points come from a different `--seed`, a different mission, or a bigger budget; rows made by other code stay in the file but are not trained on, so any commit to `cafe/`, `config/`
or `platforms/` starts the count again. A bigger budget raises the points per run. Runs that overlap share the table safely: every write goes through a temporary of its own and a lock file (`train.parquet.lock`) beside the table makes two adds queue; `--emulator-table FILE` still gives a run a private copy. The threshold is not lowered to make the emulator appear.

## 6. With a GPU (not tested here: no GPU was available while this was built)

The code path exists (XLB with the Warp backend, `--gpus N`), but every run so far was on CPU. On a GPU machine: add
`--gpus all` to the `docker run` in `pm()`, make sure the image has CUDA builds of `jax` and `warp-lang`, measure the GPU with
`pm python bench/throughput.py lbm gpu`, then `pm bin/run_premission --mission missions/tepex_c_demo.yaml --budget 4h --gpus 1
--out runs/4h`. The plan and the report then say "GPU path" instead of "CPU fallback"; `make acceptance GPUS=1` adds the 4 h run.
`run --gpus N` stops with `error: --gpus N but no GPU is visible` when the container cannot see a GPU (usually a forgotten `--gpus all`); `plan --gpus N` then
begins with "no GPU found on this machine" and prints a projection from published benchmarks, not a measurement. Pass `--assume-gpu` only to plan for a GPU that will be there.

After a GPU run whose LES windows passed, the run's sub-grid calibration is in `runs/<mission>/<budget>/stage3/subgrid_calibration.json` and the stages after stage 3 already used it.
To keep it for later runs, `pm python -m cafe.pm promote-calibration --run runs/<mission>/<budget>` copies it into `config/subgrid.json`, recording the run's full path, the date and the digest of its
stage-3 ledger in `calibration.source_run`; review the diff and commit it. Nothing else changes that file, and stage 1 always uses the tracked calibration.

## 7. Check it

```bash
pm make receipts          # every receipt; exit 0 only if none failed. Read "Receipts on a clean machine" below before expecting 0
pm make broken            # the deliberately broken wave-direction config must FAIL a receipt that passes without it: exit 0 means one did; it runs the fast receipts twice (clean, then broken)
pm make audit             # ledgers of runs/quick, runs/overnight and runs/4h (those that exist) and of runs/acceptance/quick re-hashed, banned tokens, ruff, mypy --strict, coverage, mutation score
pm make acceptance        # brief 5.3: quick + overnight (+ 4h with GPUS=1), golden diff, same seed, other seed, broken config (~11 h); the runs live in runs/acceptance/<name>
```

Each writes its table (`runs/receipts.json`, `runs/acceptance/acceptance.json` and `.txt`). The acceptance runs live in `runs/acceptance/<name>` and are replaced on every run; your `runs/quick` is not touched. `audit` takes run directories as arguments and exits 2 at once, before any step, for a path that is not a directory or an option it does not know (`--code-only`, `--ledgers-only`, `--mutation-record`). With none of those run directories `make audit` re-hashes no ledger; `make ci` (step 2) ends with
`python -m cafe.pm.audit --ledgers-only runs/ci`, which re-hashes every ledger of the run it just made and checks the chain.

**Receipts on a clean machine.** `make receipts` exits 0 only when no row failed, and that is not what a clean machine shows, for two reasons.

1. *The slow receipts are not stored yet.* Three groups are read from a result stored under `$CAFE_DATA/receipts/` for this exact code (a digest of every
   `cafe/**/*.py` file, `cafe/schemas/*.json`, `config/` and `platforms/`; any edit makes every stored result stale). Without it the row is a failure named
   `<group>:not_run` (`app.fea`, `pm.physics.uas.slow`, `pm.emulator`). The command that stores them is
   `pm python -m cafe.pm receipts --slow` (or `--slow --only <group>` for one; a part goes to `runs/receipts_partial.json`, never over `runs/receipts.json`, and a name that matches no group exits 2). It takes about 100 minutes on 2 CPUs by the groups' own estimates
   (`app.fea` 60, `pm.emulator` 35, `pm.physics.uas.slow` 5) plus the two reruns under `--slow`: the wall-model flat plate (30 000 steps; the
   stored run took 1.8 h) and the native-kernel sphere at Re = 100, so plan for about 4 hours. Run it again after any edit to the tree.
2. *Some receipts fail by design, because the limitation is open.* They are not a broken install: the XLB sphere drag rows (`pm.stage3.lbm`, L08),
   the native-kernel sphere rows (`pm.stage3.nest`, L08), and the wall-model flat plate against ITTC-57 and its y+ share (`pm.stage3.wallmodel`, L09). The limitation
   ids are those of `docs/CREDIBILITY.md` section 5. A failing row whose id is not on that list, or any `<group>:not_run` after `--slow`, means a broken
   install or stale code: read its note.

So the honest expectation is: after `receipts --slow` the table fails only on the rows above, and `make receipts` still exits non-zero until those
limitations are retired.

**The golden is a regression snapshot, not an independent expectation.** `tests/golden/tepex_c_demo_quick.json` is this tool's own output from a
reviewed quick run, so it catches a change, not an error. `make acceptance` refuses to pass if it is missing, and `golden_diff` FAILs until it records a
commit sha, a clean tree, the code digest and the reviewed run's report hash. Rewrite it from a reviewed quick run on a clean, committed checkout:
`pm python -m cafe.pm acceptance ... --update-golden` (on homebase `./pm.sh ...`); that run then fails the one check until it is rerun without the flag. The golden records the commit and whether the tree was clean, and the image has no `git`, so mint it through the step 1 wrapper (it passes `CAFE_GIT_SHA` and `CAFE_GIT_DIRTY` from the host checkout) from a checkout where `git status --porcelain` prints nothing; run without `CAFE_GIT_DIRTY` it writes `dirty: null` and `golden_diff` says it "cannot tell whether the checkout was clean" (review round 4, M-24).

**Model receipts in the report.** A report with no `runs/receipts.json` says "Model receipts: not run" and its verdicts cite no receipt group. Run
`python -m cafe.pm receipts` first. `receipts` also writes `runs/receipts.meta.json` (the code digest, git sha and time of the table); a verdict whose
receipt table was made by other code than the run's reads "stale: made by other code", is not counted as a pass, and says to rerun `make receipts`; a table made with `--only` (its meta file records it) is stale in the same way, since it holds a part of the receipts.

## Troubleshooting

| You see | It means | Do |
|---|---|---|
| `CAFE_OFFLINE is set, so nothing is downloaded: unset CAFE_OFFLINE and run python -m cafe.pm fetch ...` | an input is not cached | step 4 |
| `ensemble capped at N members by the stage-1 share` | the budget buys N members on this machine (N follows the stage-1 cost in `plan.json`, so it differs between machines and after `make bench`) | expected at `quick`; `overnight` runs more |
| `error: --budget quick: stage 1 needs ... short by ... s` (exit code 2) | `plan` or `run` of a long window or a big fleet does not fit the budget (`budget.PlanError`) | a larger `--budget`, a shorter window or fewer vehicles. `fetch` never plans a budget, so a 30-day mission can still be fetched |
| a stage-3 row `not run: the physical lattice viscosity ... needs ... cell-updates; this machine does ...` | the LES window cannot reach the lattice viscosity floor at this machine's rate | expected with `--gpus 0`: no LES coefficients exist on this machine (step 5); a GPU is the way (step 6) |
| a stage-3 row `window cut at the time limit: its coefficients are withheld` | the window ran past its wall-clock slice (a busy machine); its measured numbers depend on where the clock cut it and are kept out of the report | rerun on a quiet machine, or raise `stage3.les_margin` in `config/assumptions.yaml` |
| the DTMB V&V rows read `not run: run_coarse.json was made by recipe None, not pout-lts01-parts-v4` | files of another recipe are never read | copy the files of the current study to `$CAFE_DATA/dtmb5415` |
| `free-surface window not run: estimated ... it would fit --budget overnight (N min of stage 3 in that plan)` | the interFoam hull case does not fit this budget; the message names the smallest `--budget` whose own plan holds it, or says "no --budget profile's plan holds it" and gives the largest plan's minutes | expected at `quick`; the report shows "W3 did not run; not used in the refit: free-surface window not run: ..." and the hull refit was not used |
| `only N GB free under ...; a DTMB 5415 case needs 4.0 GB` | disk | free space; the DTMB receipts are slow and stored |
| exit code 2 and `error: ...` | the mission file or a config is invalid, or the emulator training table cannot be read | the message names the field, or the table file (move it aside: its rows are lost; the next run starts a new table) |
| `error: environment cache file ... cannot be read` | a downloaded file or chunk is truncated or corrupt | delete the store or directory the message names (the single `gofs_<mission>.zarr`, or `<cache>/orca`), never the whole `ocean` directory, and run `fetch` again: only that part is downloaded again. For a lab store the message says to restore it from the lab's source: the pipeline cannot download it. An empty or truncated manifest (`orca/manifest.json`, `tao/manifest.json`) needs no deleting: the parts are fetched again |
| `error: ... duplicate key` or `... is read as octal` | the mission or a config file repeats a key, or has a number such as `010` | fix the line the message names |
| `error: CAFE_WORKERS=... is not a whole number of at least 1` (also `CAFE_NPROC`) | the variable is set to something else | `CAFE_WORKERS=N` with N of 1 or more, or unset it |
| `error: CAFE_OFFLINE='x' is not 0 or 1` | the variable is set to something else | `CAFE_OFFLINE=1` to download nothing, or `0` or unset it |
| `error: X is not a run directory` or `error: unknown option --x` from `audit` | a wrong path or a mistyped option; nothing was run | the message lists the run directories and the options |
| `error: ...: no plan.json; this is not a finished run directory` | `report` was pointed at a directory that no `run` finished | run the mission first (step 5) |
| `error: stage 1 needs about N GB for the environment of a D-day window ...` (exit code 2) | the memory limit holds not even one worker plus the window's environment | a shorter window, a machine or `--memory` with more memory (step 1) |
| exit code 1 and `error: stage X: self-checks failed: name: note ...` | a stage self-check failed (a missing input, a changed derived layer, an emulator gate) | the message names the check and what to do; the ledger at the path in the message has the detail. With `CAFE_OFFLINE` set, unset it and run `fetch` |
