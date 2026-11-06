# RUNBOOK — the TEPEX-C pre-mission simulator, from a clean machine to a report

Follow it top to bottom. Every command is meant to be pasted as written; `<...>` is the only thing you fill in. If a step's
"you should see" does not match, stop there: the troubleshooting table at the end says what each failure means.

## 0. What you need

* Linux with Docker (any user in the `docker` group; no root inside the containers). 8 cores and 32 GB RAM are the machine the quick
  budget is sized for; a GPU is optional (see step 6). The 20 minutes of `--budget quick` count the compute stages with the data already cached.
  The network fetch of step 3 is a separate step whose duration depends on your link, not on `--budget`; the run's ingest stage reports its own
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

Give the container its limits so the plan can see them: add `--cpus N --memory M` to the `docker run` of `pm()` (on homebase `./pm.sh` takes `PM_CPUS` and `PM_MEM`, default 8 and 28g, the whole box; `bin/pmx.sh`, the path of every other agent, defaults to 2 CPUs and 12g, the least that plans the demo mission, and asks for more with `PM_CPUS=<n> PM_MEM=<n>g`; both refuse a `PM_CPUS`, `PM_MEM` or `PM_SHM` that is not a plain number, such as `1.5` or `2;x`, with exit 2 and nothing sent: review round 10, M-23, M-31). `plan` reads the memory limit (else the host's free memory), needs the environment (0.0031 GB per square degree of the padded box per window day, so 9 GB for the demo; calibrated on that one box and window, so a floor beyond them and not a measurement; or the size on disk of the cache's Zarr stores and the ocean store if that is larger) plus 0.9 GB per worker, caps the workers to what fits (`plan.json` has `workers_by_cpu`, `workers_by_memory` and `workers`; `plan` says when memory capped the count) and refuses a mission for which not even one worker fits (exit 2: a 30-day window on the demo's box with the default pad needs more than 100 GB, reasoned from the model and not measured). About 15 days of the demo mission (its shipped `pad_deg` 2.0, 8 workers) fit 32 GB (22.5 GB of environment plus 7.2 GB of workers; 17 days need 32.7 GB); with the default pad about 10 days do (28.8 GB; 11 days need 32.9 GB). A longer window needs more memory or a smaller box (`pad_deg`). The memory figure is the model's (linear from one measured 6-day point), not a measurement. The plan is made again when the ingest ends, with the stores then on disk: if it changes, the run prints the new figures and rewrites `plan.json`, and it stops with the sizes named if the workers no longer fit. The demo is refused under about 10 GB and capped below 8 workers only under about 16 GB. `CAFE_WORKERS` and `CAFE_NPROC` must be a whole number of at least 1, else `error: ...` and exit 2; an explicit count is honoured and the plan notes the memory it needs. If `/dev/shm` fills part-way, the error says so and tells you to raise `--shm-size`.

(On homebase this is `./pm.sh <command>`, which also syncs the checkout there and sets the same two variables; data is `~/work/cafe/pmdata`.) The sync deletes what is no longer in the checkout; the outputs the server wrote (`runs/`, `config/throughput.json`, `docs/mutation.json`, `tests/golden/`, `report/`, ...) are kept by the list in `bin/sync_filters`, and `./pm.sh --pull <path>` brings one back before you commit. The shared `pm` directory belongs to one checkout at a time (`~/work/cafe/pm.owner`): a sync from another checkout is refused, and `PM_TAKE=1` takes it over. Another agent uses `PMX=pm_<you> bin/pmx.sh <command>`; `PMX` must be `pm_` followed by letters, digits, `_` or `-` (review round 9, M-28, M-39). The image has no `git`, so the ledgers learn the commit and whether the tree was clean only from `CAFE_GIT_SHA` and `CAFE_GIT_DIRTY`; without the second one a ledger says `"git_dirty": null` and the golden of step 7 cannot be minted or passed (review round 4, M-24, DECISIONS 260). Run `pm` from the repository root, in a git checkout where `git status` works.

Optional, for acoustic links near the ship (review round 5, M-25): `make install` builds no Bellhop. Without it every ambiguous acoustic link (one within about 6 dB of its margin) is judged on Thorp absorption alone, and the report says "Thorp only, Bellhop unavailable" on each such link. To build it (needs the network and the `cafe-pm` image; gfortran is installed inside a throwaway container and nothing is added to an image):

```bash
sh bench/install_bellhop.sh
```

The script writes `bellhop.exe` into `$CAFE_HOST_DATA/bin` (set in step 1; without it, homebase's `~/work/cafe/pmdata/bin`), which `pm()` mounts as `/data/bin`, the first place the code looks. The demo's own acoustic links (555 and 633 km) fail by range and never use Bellhop. The ledger's versions record whether Bellhop was found (the sha-256 of its executable, or `absent`) and the versions of the other libraries the verdicts depend on, and they are part of the code digest: installing Bellhop after a run makes the next `run` redo the stages (review round 8, M-35).

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

You should see `report: runs/ci/report/index.html`, then `audit: 0 problem(s)` as the last line, and exit code 0. This flies every stage at toy resolution on a
synthetic environment (`tests/fixtures/ci_env`).

## 3. Fetch the mission's data (once, ~2.5 h; resumable)

```bash
pm python -m cafe.pm validate --mission missions/tepex_c_demo.yaml
pm python -m cafe.pm fetch --mission missions/tepex_c_demo.yaml
```

`validate` should print `missions/tepex_c_demo.yaml: valid (4 vehicles, 4 links)`. `fetch` is safe to interrupt and rerun (each input is hash-checked and
only missing parts are fetched). **After the round-10 update the first run fetches TAO again, into `<data>/tao/s2`** (the cache of the current selection rule; the older `<data>/tao/manifest.json` and its files stay as they were, and the runs that read them still audit): do it once online with `python -m cafe.pm fetch --mission <file>` on every machine that later runs with `CAFE_OFFLINE`, or `tao_present` fails (review round 10, look-ahead L0). `fetch` needs no `--budget` and plans none, so it works for a 30-day or 20-vehicle mission that only fits a larger budget. The HYCOM GOFS store is the long part. To use the lab's own HYCOM instead, set
`environment.ocean: {source: lab_hycom, path: /data/ocean/lab_tepex_c_demo.zarr}` in the mission (`path` is required with `source: lab_hycom`, and `validate` says so if it is missing) and run
`pm python -m cafe.pm ingest-ocean --mission missions/tepex_c_demo.yaml --path /data/<lab dir> --temperature-kind <in_situ|potential>`.
The store path (`environment.ocean.path`) must not be, or contain, the directory you pass as `--path`: the command refuses it, because replacing the store deletes the old directory at that path. A path that exists, is not empty and holds no Zarr metadata or chunks is refused too: move it away first. A lab store that lost its `zarr.json` is replaced by running the same command again (review round 9, M-5).
The files must span the window; any cadence with no step longer than 24 h inside the window works (the ocean is interpolated linearly in time, so a longer step would make the current a straight line across it; the ingest records the median and largest step as the check `ocean_time_cadence`), and a grid of any spacing works if the file covers the box, also for a box next to 0 deg E (the box itself still must not cross 0 deg E); GOFS is 3-hourly. Snapshot files are ordered by their time, not their names, and two snapshots of one time are refused naming both files (review round 8, M-2, M-29, M-30). A z-level file is read in order of increasing depth whatever order it lists them in, and a field that is all NaN at a time step is refused with the file named (review round 7, M-12, M-36).
Changing `box` or `pad_deg` downloads the ocean again (the parts are reused only for the box they were cut to). A downloaded part that cannot be opened is removed with its manifest entry and the error says to run `fetch` again, which downloads only it (M-3, M-30).

What `validate` enforces about vehicles (it exits 2 with `error: ...` naming the field, so a wrong file is found here and not hours into a run). A vehicle with `base` is a UAS: it takes `sorties`
and `launch_rules` and no `task`. A vehicle without `base` takes a `task` and no `sorties`: a glider flies `station`, `section` or `drift`, a USV `station` or `section`. A `station` task
names the station (`lon`, `lat`; `radius_km`, default 5, and `lost_after_h`, default 6, are optional); for a USV `radius_km` is the distance from the station at which it counts as swept off track. A glider `drift` task needs `heading_to`, the compass heading in degrees
(0 to 360) it swims on: a drift glider has no pass/fail criterion, so its GO means only that the battery and depth limits held on that heading. The platform file must be of the
vehicle's class (a Seaglider or Slocum for a glider, `saildrone_explorer` for a USV, `quad_uas` for a UAS), an acoustic link cannot end at a UAS, every time must be a real calendar time,
every vehicle must be deployed at least 10 min before `window.end`, and a key that is not in the schema (a typo in `task`, `sorties`, `launch_rules`, `shore`) is refused. Numbers outside the model's range are refused too (review round 6, M-9): `max_mean_wind_ms` above 0 and at most 60, `no_gust_front_within_min` 0 to 1440, `radius_km` 0.01 to 1000, `lost_after_h` above 0 and at most 720, `dive_depth_m` 1 to 2000 and, for a glider, between its platform's `min_dive_m` and `rating_m` (a dive depth within about 7.4 m of `rating_m` still fails `overdepth` in every member, because the glider sinks on past the order while the buoyancy pump runs: the Seaglider ordered to 990 m peaks at 997.4 m and passes, to 995 m peaks at 1002.4 m and fails, the cut-off being near 992.6 m; the report says so with the measured peak, review round 10, M-16), `track_tolerance_km` above 0 and at most 1000, `ship.antenna_height_m` 0.5 to 100, `ship.transducer_depth_m` 0 to 100 (review round 8, M-18), and `altitudes_m` distinct and rising. A time must be in quotes (`start: "2023-03-01T12:00:00Z"`): YAML reads it bare as a time and `validate` says so, and so must a time of day (`local_solar_time: "14:00"`) and an id such as `no` (YAML reads them as a number and false); write a number without quotes (`5`, `5.0` and `5e0` all load; a quoted `"5"` is text and `validate` says so; review round 8, M-39). The mission `name` is lowercase letters, digits, `_` and `-`, at most 64 characters (it is a directory name). The mission box, with its pad (`pad_deg`, else the window length times 0.5 m/s rounded up to 0.5 deg), must not cross 0 deg E: the ocean fetch takes one box in 0..360. Move the box east or west of 0 deg, or run it as two missions. A box across 180 deg is fine. With the pad it must also stay within 90 deg of latitude and be less than 360 deg wide; a box that does not is refused at load naming the pad (review round 10, M-8). A mission or platform file must be UTF-8 text (review round 7, M-32, M-33, M-34). It also refuses a NaN or infinite number (a missing value is a missing key, not `.nan`), a repeated key, and a leading-zero number such as `010` (YAML reads it as octal 8; write 8, or quote it), naming the field or the line.

A platform file must hold every parameter its model reads, each a finite number in its physical range (the limits are in the message; `radios.yaml` and `modems.yaml` are tables, which `hangar --platform radios` and `modems` check for a source on every entry); `python -m cafe.pm hangar --platform <file>` and `validate` name the file and the field that is missing or out of range, and for a glider or USV file a whole top-level block (`kind`, `params`, `mission_defaults`) that is missing (M-35). A repeated key or an octal number in a platform file is refused like in a mission, and so is an empty file, a list where a number belongs, a reversed battery curve and an implausible number (an angle at or above 90 degrees, a fractional cell count, `battery.r_int_ohm` of 0: use 1e-6 for a near-ideal pack), each naming the file and the leaf (review round 8, M-11, M-25, M-26, M-28, L1).

Review round 9 added to what `validate` refuses: a `section` task whose consecutive waypoints are equal (`[A, B, A]` is allowed), a box whose `lon_min` equals `lon_max` (a box across the dateline is `lon_min` 165, `lon_max` -165), and a `gofs31` `ocean.path` that does not end in `.zarr`. YAML anchors and aliases are allowed; each use is its own copy. A vehicle's `platform` is a name in `platforms/`, or a path ending in `.yaml` or `.yml`, relative to where the command runs. A glider or USV platform file must carry every key of its `mission_defaults` block, each in range (`platforms/seaglider.yaml` and `platforms/saildrone_explorer.yaml` show them); one that lacks a key is refused at load naming the file and the key (M-1, M-2, M-13, M-20, M-22, M-33).

For a mission whose `verdict.go` is above 0.75, `validate` also prints a note to stderr: GO needs the point estimate of P(success) at least `go` and the 90 % Wilson lower bound on success at least 0.75, so 9 members without a failure are GO whatever `go` is, and the stopper uses the 95 % bound against `1 - go` (review round 8, M-7).

The mission's `environment.subgrid` block has five switches: `turbulence`, `gust_fronts`, `warm_layer`, `rain_lens`, `ocean_sde`. Each is on unless the mission says `false`; the report's header lists the five and which of them the mission left out.

### 3a. Write your own mission

`missions/tepex_c_demo.yaml` is the reference and `cafe/schemas/mission.json` is the schema that `pm python -m cafe.pm validate --mission <file>` checks a file against (it names the field and the limit when something is wrong). The top-level keys, in the demo's order:

* `name` (lowercase letters, digits, `_` and `-`; it is a directory name) and `description` (free text).
* `window`: `start` and `end`, UTC, in quotes.
* `box`: `lon_min`, `lon_max`, `lat_min`, `lat_max` in degrees (a box may cross 180 deg, not 0 deg E) and the optional `pad_deg`.
* `environment`: `atmosphere: {source: orca_uwincm}`, `waves: {source: orca_umwm}`, `ocean` (`gofs31`, or `lab_hycom` with a `path`, step 3) and the optional `subgrid` switches.
* `ship`: `id`, `lon`, `lat`, `antenna_height_m` (0.5 to 100) and `transducer_depth_m` (0 to 100). The ship is the base of a UAS and one end of an RF or acoustic link. `shore` (`id` only) is the far end of an Iridium link.
* `vehicles`: a list; each has an `id`, a `platform` (a name in `platforms/`, or a path ending in `.yaml` or `.yml`, of a file of the vehicle's class), a `deploy` (`time`, `lon`, `lat`) and a `task` (glider or USV) or, for a UAS, `base`, `sorties` and `launch_rules`. The rules `validate` enforces for them are in step 3.
* `links`: a list; each has an `id`, the two ends `a` and `b` (a vehicle `id`, `ship` or `shore`), a `kind` (`rf`, `acoustic` or `iridium`), the `radio` (a key of `platforms/radios.yaml`) of an RF link or the `modem` (a key of `platforms/modems.yaml`) of an acoustic one, `when` and `required_fraction`. `when` says at which moments the link is required: `always`, `surfacing` (only while the glider at one end is at the surface; an RF or Iridium link with a glider at one end must say it) or `uas_airborne` (only while the UAS is flying a sortie). `required_fraction` (above 0, at most 1) is the share of those moments the link must work for a member to succeed on it; the link's verdict is the share of members that do.
* `verdict: {go, nogo}`: the cut-offs on P(success), `0 < nogo < go <= 1` (the demo: 0.9 and 0.6). GO needs the point estimate of P(success) at least `go` and the 90 % Wilson lower bound on success at least `min(0.75, go)`; below `nogo` is NO-GO; in between MARGINAL (step 5a). For a `go` above 0.75 the lower-bound term stays at 0.75, and `validate` says so (QUESTIONS_FOR_LAB 5).
* `seed`: a whole number, 0 or more.

The YAML traps are the ones in step 3: quote times, times of day (`"14:00"`) and ids such as `no`; do not quote numbers; no repeated keys; no leading zeros.

## 4. Measure this machine (once per machine, ~15 min, with nothing else running, after step 3: the stage-1 part needs the fetched cache)

```bash
pm make bench
```

It writes `config/throughput.json`: OpenFOAM and LBM cell-update rates per core count and the stage-1 cost per vehicle class. The stage-1 part measures the demo mission on the environment cache that step 3 fetched; without the cache `make bench` ends with `stage1 bench: no environment cache at <cache>; run python -m cafe.pm fetch --mission <file> first` after the OpenFOAM and LBM jobs, with a `config/throughput.json` that has no stage-1 entry (review round 8, M-55).
The budgets are wall-clock: every stage is sized from these numbers, so a stale or loaded measurement makes the plan wrong
(`python -m cafe.pm plan` prints what the budget buys and where each rate came from, with the load it was measured at). When the file was written on a machine with another CPU count or CPU model (the `machine` block, or an entry's own record), `plan` prints and `run` logs `note: throughput.json was measured on <machine> (...); here it is ...`: the planned stage-1 times are that machine's, so run `make bench` here. The note is in the report only at `machine.machine.warning`, as the ingest recorded it on the machine the run was made on (review round 9, M-9). The stage-1 time it prints is a lower bound (the longest task or the work over the workers; the parent's serial part and worker start-up are not in it), and the report's machine block prints it next to the time stage 1 took. The UAS cost scales with sortie-minutes: the benchmark stores the sortie-minutes of its mission (`sortie_min`), and the planner multiplies the UAS cost by this mission's sortie-minutes per day over the benchmark's, so a mission with more or longer sorties plans (or is refused) accordingly.

**Commit the new `config/throughput.json`** (`git commit -am 'throughput of this machine'`): `make bench` rewrites a tracked file, the tree must be clean for the golden of step 7, and the ledgers of every later run record whether it was (`CAFE_GIT_DIRTY`, step 1; review round 8, M-56).

To re-measure only the stage-1 cost per vehicle class, on a quiet machine (one-minute load below 2 on 8 cores; the tool refuses to write on a busy one,
records the load before and after, and measures on the demo mission unless you name another):

```bash
pm python bench/throughput.py stage1            # on homebase: PM_CPUS=8 ./pm.sh python bench/throughput.py stage1
```

Run it twice, on a quiet box, and compare the two files: the tool times a warm-up batch and keeps the faster of two timings per size, but a class whose entry says `slope_resolved: false` has a per-member slope that 8 versus 32 members could not resolve (to the planner a batch then costs the same whatever its size). The shipped `config/throughput.json` was measured at load 33 and has the old single-timing method; re-measure at code freeze (review round 4, M-26, DECISIONS 262).

Use this, not `make bench`, for that: `make bench` also runs OpenFOAM. The planner halves the batch down to 4 members, else refuses with the shortfall, so that its estimate fits the stage-1 share; the estimate is a lower bound and q8 ran 2.2 times over it (52.7 s planned, 117 s measured, of a 900 s share), so a mission planned above about 45 % of the share can overrun it, and the emulator stage ran 12 % over its share (270 s of 240 s) (review round 8, M-53). These ratios are per machine. q8 ran on homebase (8 CPUs, the machine of `config/throughput.json`). q9, with the same `plan.json`, ran on the 32-vCPU burst VM: stage 1 took 4.2 times its plan (52.68 s planned, 223.05 s measured) and the emulator 2.05 times its share (492.85 s of 240 s), and at 4.2 times the same rule would read about 24 %. The 45 % and the 2.2 stay as homebase's figures; re-measure with `make bench` on the machine you use (review round 9, M-8). `--budget ci` is the 10 minute toy profile (8 to 16 members, one LES window part, no refit): it plans and runs on any mission, including the demo, but its numbers are a smoke test, not a verdict; it is meant for `missions/ci_fixture.yaml`.

## 5. Run the mission

```bash
pm bin/run_premission --mission missions/tepex_c_demo.yaml --budget quick --gpus 0 --out runs/quick
```

* `--budget quick` = 20 min, `overnight` = 10 h, `4h` = 4 h (meant for a GPU), each counted over the compute stages with the data cached (step 3 is the
  fetch). `--gpus 0` has no LES windows: each window is sized at plan time, and one that would need more than 100 times the cell-updates its share of the
  stage-3 budget holds at this machine's rate is "not run: the physical lattice viscosity ... needs dx ..., N cells and M cell-updates; this machine does Y in the window's slice ..." (every CPU
  window today except the one smoke window of `--budget ci`, because the lattice viscosity floor of `config/assumptions.yaml` `stage3.nu_lat_floor` cannot be
  met at a CPU's resolution). So **no LES coefficients exist on this machine; sub-grid and refit stay uncalibrated**, and the time goes back to stage 1.
  The free-surface hull window still runs where it fits, on `min(6, workers)` MPI ranks (fewer on a machine with fewer CPUs; `CAFE_NPROC` overrides, a whole number of at least 1) and the plan prices the same number; the glider hull's FEA belongs to its LES window, so it does not run when that window is skipped.
* A vehicle that drifts out of the downloaded box is a failed member (failure mode `left_data`), and the report says how many left and when. The pad around the
  mission box is `box.pad_deg` if the mission sets it, else the window length x 0.5 m/s in degrees (at most 10, reached at about 26 days); set `pad_deg`
  for a long window or a fast drifter and rerun the ingest. The ingest holds the whole hours that cover the window (a start at 12:30 reads the 12:00 file).
* The run is resumable: rerunning the same command skips every stage whose ledger and outputs are intact. `--fresh` ignores
  the checkpoints. `--seed S` replaces the mission's seed (same seed, same machine bench and the same CPU count = the same `report.json`; stage 1 and 1b are the same at any count, the emulator variants are not, so a resume under another CPU count reruns the emulator and the report).
* A finished run can be resumed or re-run from its own copy of the mission: `--mission runs/quick/mission.yaml --out runs/quick` (with `--seed S` the copy is rewritten with S; review round 9, M-12).
* You should see one line per stage and finally `report: runs/quick/report/index.html`, exit code 0.

Read, in this order: `runs/quick/report/index.html` (verdicts, failure modes, links, map, the stage-3 windows and why each
was or was not used), `runs/quick/report/credibility.html` (NASA-STD-7009B factors, the ASME V&V 20 rows, every assumed
input), and `runs/quick/report/report.json` (the same numbers, each with its stage, source, uncertainty, receipt and ledger).
Re-render a finished run with `pm python -m cafe.pm report --run runs/quick`. It needs no more memory than the report itself (no stage-1 memory model runs). It runs the report's two self-checks on the new files and records them in `checkpoints/report/ledger.json` with a note; if a check fails it exits 1 and the ledger is left as it was, so `audit` keeps reporting the files as changed until the report stage is rerun. A run made before review round 9 cannot be re-rendered with a clean audit (its stage-3 ledger holds an older `config/assumptions.yaml`): rerun it (M-16, DECISIONS 515). If the ledgers of the run do not match its files (a stage output edited by hand), the page prints a warning above the verdict table naming the first five problems and `report --run` prints each as a `warning:` line on stderr (exit 0; `python -m cafe.pm audit --ledgers-only` lists them); a summary whose verdict disagrees with its own counts, or whose P(fail) is not finite, is refused with `error:` and exit 2; and a run directory without `windows/windows.json` says so where the stage-3 markers, the forcing at the worst windows and the window times would be (review round 10, M-7, M-9).

What if: `pm python -m cafe.pm whatif --mission missions/tepex_c_demo.yaml --run runs/quick --shift 48h` (also `--move "1deg W"`,
`--drop uas`, `--vehicle usv`); it answers from the emulator when it can and runs stage 1 when it cannot, and says which. A deploy shift keeps the window's end, so a glider or USV deployed 48 h later flies 2 days less and its P(fail) is over the shorter flight: the answer says so under the vehicle's line (`note: <vid> flies 4 d instead of 6 d ...`) and in the flip search's candidates. Compare the verdict, not the two P(fail) numbers alone (review round 10, M-11). A UAS shifted by a whole
number of days launches at the same time of day: the command prints `uas: unchanged (...)` next to the answers for the other vehicles. UAS what-if answers use the 10 m scaled wind profile for the candidate and the baseline alike,
so a shifted sortie is not compared across two wind models. The `--mission` must be the one the run was made from (it is compared with `runs/quick/mission.yaml`; only the seed may differ, and the file's seed is then used for the new draws); to try an edited mission, run it first. `--drop` cannot name every vehicle (a mission needs at least one; M-18).

**The emulator needs 100 distinct feature points per emulator scope, and one run does not make that many.** A scope is the vehicle class, the platform and the length of the window (for example `glider/seaglider/144h`). P(fail) is over the whole window and a variant changes neither the window nor the platform, so the table pools only what is one function: a 3-day and a 6-day mission, or a Seaglider and a Slocum, are separate scopes and their points do not add up, and adding points by running other missions helps only the scope they share (same class, platform and window length). Rows made before the table carried a scope are left out and the refusal says how many (review round 10, M-1). The plan says so before the run (`plan.json`:
"this budget gives N distinct points per emulator scope (vehicle class, platform, window length) in one run ..., 100 are needed: the emulator will not train ..."), and the report's emulator section repeats it. Until the table has them,
every what-if answer comes from Stage 1 and says so. Rows accumulate over runs of identical code (the same code digest): give each run the same
`--emulator-table FILE` (or set `$CAFE_EMULATOR_TABLE`); a repeat of the same mission with the same seed adds no new point (the variants, the members and so the rows are functions of the mission and its seed, and DECISIONS 174 replaces the repeat), so new points come from a different `--seed`, a different mission, or a bigger budget; rows made by other code stay in the file but are not trained on, so any commit to `cafe/`, `config/`
or `platforms/` starts the count again. A bigger budget raises the points per run. Runs that overlap share the table safely: every write goes through a temporary of its own and a lock file (`train.parquet.lock`) beside the table makes two adds queue; `--emulator-table FILE` still gives a run a private copy. The threshold is not lowered to make the emulator appear.

### 5a. Which verdicts to trust

Read each verdict with what stands under it, all of it in `report/index.html`:

* **GO, MARGINAL, NO-GO** are cut-offs on P(success) from the mission's `verdict` block (step 3a), and each verdict prints its n, its 90 % Wilson interval on P(fail) and the rule. An interval that crosses a cut-off is badged "undecided at n = N": more members could move the verdict. With no failure in fewer than 73 members (the count at which a two-sided 95 % Wilson bound on P(fail) falls below 5 %) a verdict carries the rule-of-three note: P(fail) below 3/n at 95 % confidence, one-sided, a weaker statement than the 73-member certification.
* **NOT EXERCISED.** A link can have this fourth verdict. It was required at no moment in any member (for example the UAS never flew), so no member could fail it; read nothing from its P(fail) of 0, and do not read it as GO. A link that some members needed is graded as usual, even if most members did not need it.
* **"Stage 1" or "EMULATED".** A what-if answer says which: Stage 1 re-flew the ensemble; EMULATED came from a trained emulator, which carries its own 90 % conformal interval and is used only inside its training range and only if it met its acceptance gates. With fewer than 100 training points in the vehicle's emulator scope (class, platform, window length) the emulator does not train and every answer is Stage 1 (step 5).
* **Stage-3 windows "not run".** No LES coefficients exist on a machine without a GPU (step 5): the sub-grid layer is uncalibrated and the refit did not fire, so the vehicles fly with the coefficients of their platform files. The verdicts are the stage-1 model's, not a CFD-corrected one.
* **Assumed inputs.** Every number that is a guess and not a datasheet value is listed, with what would replace it, in `report/credibility.html` and by `pm python -m cafe.pm hangar --platform <name>`. A verdict that depends on one carries an "assumed" badge; until the lab's numbers replace them the verdicts describe the example designs, not the lab's vehicles.
* **Credibility levels.** `credibility.html` scores nine factors from 0 to 4 and prints the rule beside each; level 4 is never awarded, because it needs independent review or field evidence. Read the lowest ones first: Data pedigree is held at 1 when the forcing fails a plausibility bound or the COARE and UMWM friction velocities agree at fewer than 90 % of the sea points; Verification does not read test results (`make audit` does); Validation is held below 3 while a DTMB row's finest grid has not converged; Robustness needs a ranked sensitivity that stands above chance. `docs/CREDIBILITY.md` has every rule.

## 6. With a GPU (not tested here: no GPU was available while this was built)

The code path exists (XLB with the Warp backend, `--gpus N`), but every run so far was on CPU. On a GPU machine: add
`--gpus all` to the `docker run` in `pm()`, make sure the image has CUDA builds of `jax` and `warp-lang`, measure the GPU with
`pm python bench/throughput.py lbm gpu`, then `pm bin/run_premission --mission missions/tepex_c_demo.yaml --budget 4h --gpus 1
--out runs/4h`. The plan and the report then say "GPU path" instead of "CPU fallback"; `make acceptance GPUS=1` adds the 4 h run.
`run --gpus N` stops with `error: --gpus N but no GPU is visible` when the container cannot see a GPU (usually a forgotten `--gpus all`); `plan --gpus N` then
begins with "no GPU found on this machine" and prints a projection from published benchmarks, not a measurement. Pass `--assume-gpu` only to plan for a GPU that will be there. `--gpu-mem-gb` takes a positive number of GB; nan, inf, zero and negative values are refused (M-11).

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

Each writes its table (`runs/receipts.json`, `runs/acceptance/acceptance.json` and `.txt`). The acceptance runs live in `runs/acceptance/<name>` and are replaced on every run; your `runs/quick` is not touched. `acceptance` marks its `--out` with a `.cafe_acceptance` file and replaces only what is in a marked directory: given a directory that is not marked and already holds `quick`, `overnight`, `4h` (or their `.log` files), or is itself a run, it exits 2 and touches nothing, so use an empty or new `--out`; to reuse a directory by hand, move those entries out first and acceptance will mark it. A `runs/acceptance` from an earlier version is marked on the next run and replaced; nothing to do by hand (review round 10, M-12). A run directory can be copied or renamed (`cp -r runs/q9 runs/quick`): `audit` and a resumed `run` read its files from where the copy is, whatever the directory is called, and a file the copy lost is reported missing in the copy; paths a run recorded outside its own layout (`/app/config/...`, the environment cache) are read where they were recorded (M-19). `audit` takes run directories as arguments and exits 2 at once, before any step, for a path that is not a directory or an option it does not know (`--code-only` and `--ledgers-only` for both `python -m cafe.pm audit` and `python -m cafe.pm.audit`; `--mutation-record` only for `python -m cafe.pm.audit`). With none of those run directories `make audit` re-hashes no ledger; `make ci` (step 2) ends with
`python -m cafe.pm.audit --ledgers-only runs/ci`, which re-hashes every ledger of the run it just made and checks the chain. `python -m cafe.pm.audit --pytest-done` (only that module, like `--mutation-record`; it takes no other option) is everything the full audit does except running pytest, for a suite run elsewhere in pieces (`bin/orca_gate.sh <K> <tag> --cov` on orca); it fails if `coverage.json` is missing or older than the newest file under `cafe/pm` (DECISIONS 518). The audit appends every step's whole output to `audit.log` in the repository root (gitignored; CI uploads it as the artifact `audit-log`); a failing step's printed problem keeps only the last 4000 characters. CI also uploads `coverage.json` with it, and a coverage gate that misses names the files and lines (review round 8, M-40).

**Receipts on a clean machine.** `make receipts` exits 0 only when no row failed, and that is not what a clean machine shows, for two reasons.

1. *The slow receipts are not stored yet.* Three groups are read from a result stored under `$CAFE_DATA/receipts/` for this exact code (a digest of every
   `cafe/**/*.py` file, `cafe/schemas/*.json`, `config/` and `platforms/`; any edit makes every stored result stale). Without it the row is a failure named
   `<group>:not_run` (`app.fea`, `pm.physics.uas.slow`, `pm.emulator`). The command that stores them is
   `pm python -m cafe.pm receipts --slow` (or `--slow --only <group>` for one; a part goes to `runs/receipts_partial.json`, never over `runs/receipts.json`, and a name that matches no group exits 2). It takes about 100 minutes on 2 CPUs by the groups' own estimates
   (`app.fea` 60, `pm.emulator` 35, `pm.physics.uas.slow` 5) plus the two reruns under `--slow`: the wall-model flat plate (30 000 steps; the
   stored run took 1.8 h) and the native-kernel sphere at Re = 100, so plan for about 4 hours. Run it again after any edit to the tree.
   **After review round 10 every stored slow stage-3 result is stale once more** (M-2 changed `nest.py`, so `lbm.physics_sha()` is another value again): rerun the commands below, then `receipts --slow`. **After review round 9 every stored slow stage-3 result is stale again** (the stage-3 fixes M-4, M-24 and the look-ahead items changed `lbm.py`, `nest.py` and `wallmodel.py`, so `lbm.physics_sha()` is another value than the one the stored `wm_flat_plate`, `wm_channel`, `nest_sphere_*` and `lbm_sphere_*` carry): rerun the commands below, then `receipts --slow`. A stored result with a missing or non-numeric field counts as not stored ("wm_*.json is unreadable"), as does a flat plate stored at Re_L below 1e6, and a run that diverges stores no receipt. The same held after review round 8 (S's M-32 and M-48 changed `lbm.py` and `wallmodel.py`) and after review round 7 (M-8): **every stored slow stage-3 result is stale** (`wm_flat_plate`, `wm_channel`, `nest_sphere_*`, `lbm_sphere_*`): a stored result counts only when its
   `code_sha` is the current `lbm.physics_sha()` (a digest of `lbm.py`, `nest.py` and `wallmodel.py`), and one stored without a `code_sha` (an older or a hand-copied file) is
   stale too. The table prints such a row as a FAIL "STORED BY DIFFERENT CODE" or "STORED WITHOUT A CODE SHA" with its `rerun:` command and run time, and no stage-3 window
   passes the wall-model check until both wall-model files are current. Store them again, in this order, each through `pm`:

   ```bash
   pm python -m cafe.pm.stage3.wallmodel channel                    # about 15 s
   pm python -m cafe.pm.stage3.wallmodel slow                       # the flat plate, length 400 (Re_L 1.02e6), about 1.9 h on 2 CPUs
   pm python -m cafe.pm.stage3.nest slow 100 8 12 6 6 --lateral dirichlet
   pm python -m cafe.pm.stage3.nest slow 100 12 12 6 6 --lateral dirichlet
   pm python -m cafe.pm.stage3.nest slow 100 16 12 6 6 --lateral dirichlet
   ```

   and, for the XLB sphere rows, the `python -m cafe.pm.stage3.lbm slow ...` command printed in each row. Then `receipts --slow` as above.
2. *Some receipts fail by design, because the limitation is open.* They are not a broken install: the XLB sphere drag rows (`pm.stage3.lbm`, L08),
   the native-kernel sphere rows (`pm.stage3.nest`, L08), and the wall-model flat plate against ITTC-57 and its y+ share (`pm.stage3.wallmodel`, L09). The limitation
   ids are those of `docs/CREDIBILITY.md` section 5. A failing row whose id is not on that list, or any `<group>:not_run` after `--slow`, means a broken
   install or stale code: read its note.

So the honest expectation is: after `receipts --slow` the table fails only on the rows above, and `make receipts` still exits non-zero until those
limitations are retired.

**The golden is a regression snapshot, not an independent expectation.** `tests/golden/tepex_c_demo_quick.json` is this tool's own output from a
reviewed quick run, so it catches a change, not an error. `make acceptance` refuses to pass if it is missing, and `golden_diff` FAILs until it records a
commit sha, a clean tree, the code digest and the reviewed run's report hash. Rewrite it from a reviewed quick run on a clean, committed checkout (commit the `config/throughput.json` of step 4 first):
`pm python -m cafe.pm acceptance ... --update-golden` (on homebase `./pm.sh ...`); that run then fails the one check until it is rerun without the flag. The golden records the commit and whether the tree was clean, and the image has no `git`, so mint it through the step 1 wrapper (it passes `CAFE_GIT_SHA` and `CAFE_GIT_DIRTY` from the host checkout) from a checkout where `git status --porcelain` prints nothing; run without `CAFE_GIT_DIRTY` it writes `dirty: null` and `golden_diff` says it "cannot tell whether the checkout was clean" (review round 4, M-24).

**Model receipts in the report.** A report with no `runs/receipts.json` says "Model receipts: not run" and its verdicts cite no receipt group. Run
`python -m cafe.pm receipts` first. `receipts` also writes `runs/receipts.meta.json` (the code digest, git sha and time of the table); a verdict whose
receipt table was made by other code than the run's reads "stale: made by other code", is not counted as a pass, and says to rerun `make receipts`; a table made with `--only` (its meta file records it) is stale in the same way, since it holds a part of the receipts.

## Troubleshooting

| You see | It means | Do |
|---|---|---|
| `CAFE_OFFLINE is set, so nothing is downloaded: unset CAFE_OFFLINE and run python -m cafe.pm fetch ...` | an input is not cached | step 3 |
| `ensemble capped at N members by the stage-1 share` | the budget buys N members on this machine (N follows the stage-1 cost in `plan.json`, so it differs between machines and after `make bench`) | expected at `quick`; `overnight` runs more |
| `error: --budget quick: stage 1 needs ... short by ... s` (exit code 2) | `plan` or `run` of a long window or a big fleet does not fit the budget (`budget.PlanError`) | a larger `--budget`, a shorter window or fewer vehicles. `fetch` never plans a budget, so a 30-day mission can still be fetched |
| a stage-3 row `not run: the physical lattice viscosity ... needs ... cell-updates; this machine does ...` | the LES window cannot reach the lattice viscosity floor at this machine's rate | expected with `--gpus 0`: no LES coefficients exist on this machine (step 5); a GPU is the way (step 6) |
| a stage-3 row `window cut at the time limit: its coefficients are withheld` | the window ran past its wall-clock slice (a busy machine); its measured numbers depend on where the clock cut it and are kept out of the report | rerun on a quiet machine, or raise `stage3.les_margin` in `config/assumptions.yaml` |
| the DTMB V&V rows read `not run: run_coarse.json was made by recipe None, not pout-lts01-parts-v4` | files of another recipe are never read | copy the files of the current study to `$CAFE_DATA/dtmb5415` |
| `free-surface window not run: estimated ... ; it would fit --budget overnight (N min of stage 3 in that plan)`, or `... ; no --budget profile's plan holds it (the largest plan gives N min of stage 3)`, or `... ; no --budget profile could be planned for this mission` | the interFoam hull case does not fit this budget; the message ends with the smallest `--budget` whose own plan holds it, or says no profile's plan holds it and gives the largest plan's minutes, or that no profile could be planned at all (review round 10, M-33) | expected at `quick`; the report shows "W3 did not run; not used in the refit: free-surface window not run: ..." and the hull refit was not used |
| `only N GB free under ...; a DTMB 5415 case needs 4.0 GB` | disk | free space; the DTMB receipts are slow and stored |
| exit code 2 and `error: ...` | the mission file or a config is invalid, the emulator training table cannot be read, or a path you named (`--out`, `--broken`) cannot be made or read | the message names the field, the path, or the table file (move it aside: its rows are lost; the next run starts a new table) |
| `error: <run>: damaged or incomplete (KeyError: ...); run it again (--fresh)` (exit 2, from `report`, `whatif` or `python -m cafe.pm.stage1`) | a file of the run directory is valid JSON but lacks a key or has the wrong type (hand-edited, or written by other code); or `stage1b/summary.json` is missing ("this is not a finished run: rerun it (--fresh)") | rerun the mission with `--fresh` (review round 10, M-5) |
| `error: --out <dir> holds quick, overnight, ..., and acceptance replaces those on every run; use an empty directory or a new one ...` (exit 2) | `acceptance --out` was given a directory that is not marked as acceptance's and holds a run name, a run's `.log`, or a run | use an empty or new `--out`, or move those entries out (step 7; review round 10, M-12) |
| the report page begins with "The ledgers of this run do not match its files", or `report --run` prints `warning: ...` | a stage output was changed after its ledger was written | `python -m cafe.pm audit --ledgers-only <run>` lists them; rerun the stage, or the run if you did not edit it (review round 10, M-7) |
| a stage-3 row `no_current_data: the environment gave no finite <field> at this window (a masked cell or a hole in the field)` | the weather had a masked cell or a hole at the window | the window did not run and is not used in the refit; expected near a land block or a hole of the UMWM sea mask (review round 10, M-15) |
| `error: environment cache file ... cannot be read` | a downloaded file or chunk is truncated or corrupt | delete the store or directory the message names (the single `gofs_<mission>.zarr`, or `<cache>/orca`), never the whole `ocean` directory, and run `fetch` again: only that part is downloaded again. For a lab store the message says to restore it from the lab's source: the pipeline cannot download it. An empty or truncated manifest (`orca/manifest.json`, `tao/s2/manifest.json`) needs no deleting: the parts are fetched again |
| `error: derived surface layer ... cannot be read`, or a failed `derived_unchanged` check that says the layer "is missing or has another layout" | `cache/<mission>/derived.zarr` under `$CAFE_HOST_DATA` is damaged, deleted or made by another layout | delete `$CAFE_HOST_DATA/cache/<mission>/derived.zarr` and run `pm python -m cafe.pm fetch --mission <file>`; only it is rebuilt (about a minute) |
| `error: ...: not a JSON object` (from `report`, `whatif` or `python -m cafe.pm.stage1`), or `... is not a UTF-8 text file` (a mission or platform file) | `plan.json`, `summary.json`, `refit.json`, `priors_fitted.json`, `tao_compare.json`, a `windows.json`, `flip.json`, the ingest ledger or `config/throughput.json` is truncated or overwritten; or the mission or platform file was saved in another encoding | rerun the mission with `--fresh` (the run writes these files; `config/throughput.json` is `make bench`'s); save the YAML as UTF-8 |
| `ledger ... is unreadable (...): the stage runs again`, or an audit line `... is not valid JSON` | a `ledger.json` (or an orca, TAO or store manifest the ledger names) is truncated by a disk-full or a kill | `run` and `fetch` rerun that stage by themselves; for a manifest or a store file `audit` names the file: delete it and run `fetch` again |
| `input ... changed since the stage ran (tree ...)`, or `input ... is missing (the stage read it)` | an ocean or orca store was changed, lost a chunk or was deleted | delete it and run `fetch` again (the lab's own ocean store cannot be downloaded: restore it from the lab's source) |
| `environment cache file ...: axis time: must be strictly increasing` | a cached WRF or UMWM time axis repeats or reverses a stamp | delete `<cache>/orca` and run `fetch` again |
| `...: variable WSPD_QC is missing, so no sample of ... can be told good from bad` (also `AIRT_QC`, `RH_QC`, `SST_QC`) | a TAO file has no QC flag variable, so no sample of it can be told good from bad (review round 9, M-31) | `fetch` skips such a file and picks another deployment, listing the refused one under `unusable` in the TAO manifest; for a cache already built from it delete `<data>/tao/s2/manifest.json` and run `fetch` again (the manifest of the current selection rule, not the older `<data>/tao/manifest.json`) |
| `tao_present` fails offline: "not cached and CAFE_OFFLINE is set ... (the cache in <data>/tao was selected by an older rule and stays as it is for the runs that read it; this code fills <data>/tao/s2: one run with network access)" | the TAO cache of rounds 1 to 9 is not used by the current selection rule, which picks files per variable and resolution from the catalog | run `python -m cafe.pm fetch --mission <file>` once online; files that hash are kept and only the missing ones are downloaded (review round 10, M-19) |
| an orca cache directory with `hours/*.npz` and no `manifest.json` | an assemble was interrupted: the manifest is removed before the stores are rewritten, so a half-new cache is never trusted (review round 9, M-38) | run `fetch` again: it re-assembles from the cached parts without downloading |
| `error: ...: the box (with its pad of N deg) crosses 0 deg E; the GLBy ocean fetch cannot cross it` | the ocean fetch takes one box in 0..360 | move the box east or west of 0 deg, or run two missions |
| `error: ... duplicate key` or `... is read as octal` | the mission or a config file repeats a key, or has a number such as `010` | fix the line the message names |
| `error: CAFE_WORKERS=... is not a whole number of at least 1` (also `CAFE_NPROC`) | the variable is set to something else | `CAFE_WORKERS=N` with N of 1 or more, or unset it |
| `error: CAFE_OFFLINE='x' is not 0 or 1` | the variable is set to something else | `CAFE_OFFLINE=1` to download nothing, or `0` or unset it |
| `error: X is not a run directory` from `audit`, or `error: unknown option --x` from `python -m cafe.pm.audit` | a wrong path or a mistyped option; nothing was run. `python -m cafe.pm audit --bogus` (the front door) prints argparse usage with "unrecognized arguments" instead | the message lists the run directories and the options (review round 10, M-35) |
| `error: ...: no plan.json; this is not a finished run directory` (or `error: <dir>/mission.yaml: file not found` for a directory with no `mission.yaml` either) | `report` was pointed at a directory that no `run` finished | run the mission first (step 5; review round 10, M-35) |
| `error: stage 1 needs about N GB for the environment of a D-day window ...` (exit code 2) | the memory limit holds not even one worker plus the window's environment | a shorter window, a machine or `--memory` with more memory (step 1) |
| exit code 1 and `error: stage X: self-checks failed: name: note ...` | a stage self-check failed (a missing input, a changed derived layer, an emulator gate) | the message names the check and what to do; the ledger at the path in the message has the detail. With `CAFE_OFFLINE` set, unset it and run `fetch` |
