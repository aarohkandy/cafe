# RUNBOOK — the TEPEX-C pre-mission simulator, from a clean machine to a report

Follow it top to bottom. Every command is meant to be pasted as written; `<...>` is the only thing you fill in. If a step's
"you should see" does not match, stop there: the troubleshooting table at the end says what each failure means.

## 0. What you need

* Linux with Docker (any user in the `docker` group; no root inside the containers). 8 cores and 32 GB RAM run the quick
  budget in under 20 min; a GPU is optional (see step 6).
* About 20 GB of disk: the images are 7.3 GB (`cafe` 2.4 GB + `cafe-pm` 5.0 GB), the demo's data 6.4 GB (the GOFS ocean store
  5.1 GB, the orca WRF/UMWM cache 1.1 GB, TAO 0.1 GB, GEBCO 0.03 GB), a run directory about 50 MB.
* Network on the first run only, to: `orca.atmos.washington.edu` (UWIN-CM WRF + UMWM, byte-range reads),
  `ncss.hycom.org` / `tds.hycom.org` (HYCOM GOFS 3.1), `dods.ndbc.noaa.gov` (TAO/TRITON), `dap.ceda.ac.uk` (GEBCO_2026).
  After that every run is offline (`CAFE_OFFLINE=1` makes that a rule: nothing is downloaded, a missing input fails a check
  that names the command to fetch it).

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
pm() { docker run --rm -u $(id -u):$(id -g) -e HOME=/tmp -e PYTHONPATH=/app -e CAFE_DATA=/data -e CAFE_GIT_SHA=$(git rev-parse HEAD) \
       -v $PWD:/app -v $CAFE_HOST_DATA:/data -w /app cafe-pm "$@"; }
```

(On homebase this is `./pm.sh <command>`, which also syncs the checkout there; data is `~/work/cafe/pmdata`.)

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
(`python -m cafe.pm plan` prints what the budget buys and where each rate came from, with the load it was measured at).

## 4. Fetch the mission's data (once, ~2.5 h; resumable)

```bash
pm python -m cafe.pm validate --mission missions/tepex_c_demo.yaml
pm python -m cafe.pm fetch --mission missions/tepex_c_demo.yaml
```

`validate` should print `missions/tepex_c_demo.yaml: valid (4 vehicles, 4 links)`. `fetch` is safe to interrupt and rerun (each input is hash-checked and
only missing parts are fetched). The HYCOM GOFS store is the long part. To use the lab's own HYCOM instead, set
`environment.ocean: {source: lab_hycom, path: /data/ocean/lab_tepex_c_demo.zarr}` in the mission and run
`pm python -m cafe.pm ingest-ocean --mission missions/tepex_c_demo.yaml --path /data/<lab dir> --temperature-kind <in_situ|potential>`.

## 5. Run the mission

```bash
pm bin/run_premission --mission missions/tepex_c_demo.yaml --budget quick --gpus 0 --out runs/quick
```

* `--budget quick` = 20 min, `overnight` = 10 h, `4h` = 4 h (meant for a GPU). `--gpus 0` runs the LES windows on the
  XLB-JAX CPU path, labelled "CPU fallback" everywhere it appears.
* The run is resumable: rerunning the same command skips every stage whose ledger and outputs are intact. `--fresh` ignores
  the checkpoints. `--seed S` replaces the mission's seed (same seed + same machine bench = the same `report.json`).
* You should see one line per stage and finally `report: runs/quick/report/index.html`, exit code 0.

Read, in this order: `runs/quick/report/index.html` (verdicts, failure modes, links, map, the stage-3 windows and why each
was or was not used), `runs/quick/report/credibility.html` (NASA-STD-7009B factors, the ASME V&V 20 rows, every assumed
input), and `runs/quick/report/report.json` (the same numbers, each with its stage, source, uncertainty, receipt and ledger).
Re-render a finished run with `pm python -m cafe.pm report --run runs/quick`.

What if: `pm python -m cafe.pm whatif --mission missions/tepex_c_demo.yaml --run runs/quick --shift 48h` (also `--move "1deg W"`,
`--drop uas`, `--vehicle usv`); it answers from the emulator when it can and runs stage 1 when it cannot, and says which.

## 6. With a GPU (not tested here: no GPU was available while this was built)

The code path exists (XLB with the Warp backend, `--gpus N`), but every run so far was on CPU. On a GPU machine: add
`--gpus all` to the `docker run` in `pm()`, make sure the image has CUDA builds of `jax` and `warp-lang`, measure the GPU with
`pm python bench/throughput.py lbm gpu`, then `pm bin/run_premission --mission missions/tepex_c_demo.yaml --budget 4h --gpus 1
--out runs/4h`. The plan and the report then say "GPU path" instead of "CPU fallback"; `make acceptance GPUS=1` adds the 4 h run.

## 7. Check it

```bash
pm make receipts          # every receipt; exit 0 only if none failed (slow ones are read from their stored result for this code)
pm make broken            # the deliberately broken wave-direction config must FAIL a receipt: exit 0 means it did
pm make audit             # ledgers re-hashed, banned tokens, ruff, mypy --strict, coverage, mutation score
pm make acceptance        # brief 5.3: quick + overnight (+ 4h with GPUS=1), golden diff, same seed, other seed, broken config (~11 h)
```

Each writes its table (`runs/receipts.json`, `runs/acceptance.json` and `.txt`). `make acceptance` refuses to pass if the golden
(`tests/golden/tepex_c_demo_quick.json`) is missing; `--update-golden` rewrites it from a reviewed quick run and then fails
that one check until it is rerun without the flag.

## Troubleshooting

| You see | It means | Do |
|---|---|---|
| `CAFE_OFFLINE ... run python -m cafe.pm fetch` | an input is not cached | step 4 |
| `ensemble capped at 32 members by the stage-1 share` | the budget buys only one batch on this machine | expected at `quick` on 8 CPUs; `overnight` runs more |
| a stage-3 row `ok=False ... killed` | the window ran past its wall-clock slice (a busy machine) | rerun on a quiet machine, or raise `stage3.les_margin` in `config/assumptions.yaml` |
| `free-surface window not run: estimated ... it would fit --budget overnight` | the interFoam hull case does not fit this budget | expected at `quick`; the report says the hull refit was not used |
| `only N GB free under ...; a DTMB 5415 case needs 4.0 GB` | disk | free space; the DTMB receipts are slow and stored |
| exit code 2 and `error: ...` | the mission file or a config is invalid | the message names the field |
