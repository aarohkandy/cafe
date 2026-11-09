# q13 against q12la and q12 (same machine, same worker count, same TAO cache, newer code)

orca, `--budget quick --gpus 0 --fresh`, `PM_CPUS=6 PM_MEM=16g`, TAO cache `tao/s2` (manifest copies byte-identical in all three). q13: code `cdad21a` (head of `premission-step4`), started 2026-11-08 23:43:55 UTC, `rc=0` (`~/cafe-worker/logs/q13.log`), report done 23:55. Orca load 1.4 to 2.0 and 601 GB free at the start. q12la: `9b8eea6`; q12: `72d7e66`. The commits `7c6210a`, `e00a75b` and `2d5e6ad` (look-ahead L0, L1 and the adversary), `c7edc4b` and the round 13 prefix `cdad21a` are the code difference q12la to q13 (16 files under `cafe/`; `credibility.py` is the one that changes what the demo's report prints, `comms.py` changed in a docstring and `stage1.py` in a CLI error clause). Compared on orca by `review/round_13/q13cmp.py` (read only, `python q13cmp.py A B`): the bytes of all 34 files of the run, every json leaf by leaf, and every array of `stage1/res.pkl` and `stage1b/res.pkl` (295 entries each). The same script on q12 against q12la reproduced row 690's figures (RF margin 343 of 78,784 samples, at most 5.33e-4 dB; `report.json` 11,737 and 12,045 leaves), so it sees what the row saw.

## Nothing that is a number moved against q12la

| | q12, q12la and q13 |
|---|---|
| glider_eq | MARGINAL, k_fail 18, n 64, p_fail 0.28125 |
| glider_2n | GO, 0, 64, 0.0 |
| usv | NO-GO, 62, 64, 0.96875 |
| uas | NO-GO, 55, 64, 0.859375 |
| link usv-uas-rf | NO-GO, 64, 64, 1.0 |
| link glider_eq-ship-acoustic | NO-GO, 64, 64, 1.0 |
| link glider_2n-ship-acoustic | NO-GO, 64, 64, 1.0 |
| link usv-shore-iridium | GO, 0, 64, 0.0 |

- Byte-identical to q12la (and to q12 unless stated): `ingest/priors_fitted.json` (wind speed bias mean -0.4692, sd 0.5689, 14 of 15 moorings compared, T5N170W left out), `env_sigmas_fitted.json` (sst_k 0.3028, t2_k 1.1910), `tao_compare.json` (15 keys), both manifests, `hangar/hangar.json`, `windows/windows.json`, `stage3/windows.json`, `refit/refit.json`, `emulator/design.json` (train_input_rows 110, table_rows 110, rows_added 28), `flip.json`, `holdout.json`, `stage1/summary.json`, `stage1b/summary.json`, `stage1b/sensitivity_cases.json`, `mission.yaml`, and `plan.json` (against q12 it differs in one leaf, `les/cell_steps_per_window`, 678,105,250 to 0.0: row 668).
- `stage1/res.pkl` and `stage1b/res.pkl`: sha-256 `a8d709692e28` in q12la and q13, **0 arrays differ**. Against q12 (`751343753065`) one array differs, `links/usv-uas-rf/margin_db`, 343 of 78,784 samples, at most 5.33e-4 dB: M-11 (row 651), as row 690 says.
- The 21 ingest self-checks are all `ok`; `traceability_problems` and `ledger_problems` are empty. The shared emulator table is 110 rows, all `tepex_c_demo` (q13's 28 rows replaced q12la's, same keys).
- `report.json` against q12la: 12,045 leaves become 12,059, **111 differ** (against q12: 11,737 to 12,059, 422 differ). `credibility.json`: 3,274 leaves become 3,448, 190 differ.

## What differs from q12la, with its row

| mover | size | DECISIONS row |
|---|---|---|
| **Assumed-input count at entry level**: `assumed_inputs/total/value` 285 to **273**; `by_file` radios.yaml 19 to **8**, modems.yaml 4 to **3**; a new `not_used_by_file` node for the two files (radios.yaml 11, modems.yaml 1: 12 not used); `catalogue` stays 285 | 3 values, 14 leaves of the new node; in `credibility.json` 12 `used` flags True to False | 681 (`credibility.entries_read`, `Facts.item_used`): exactly the count row 690 predicted, 273 of a catalogue of 285, radios 8 of 19, modems 3 of 4; no demo had run it end to end until now |
| `credibility.json` items carry `path` | 174 leaves | 681 ("items carry `path`") |
| Input pedigree text: "80 of 258 platform inputs sourced and not recalled (31%); 174 assumed, 13 recalled" to "77 of 243 ... (32%); 162 assumed, 13 recalled"; the missing-list line "178" to "166" | 2 leaves | 681 (its own figures: "77 of 243 ... (32%); 162 assumed, 13 recalled"); the factor's level does not move |
| Config-hash receipt ids (`...:config:4b1fca33c84f` to `...:config:991a59562fdd`, `emulator:config:0f1434560d56` to `7d739e272c4a`) and the sha-256 of the 9 receipts that carry them | 48 ids in `machine`, `map`, `mission`, `vehicles`, `stage3`; 8 ids and 9 sha-256 in `receipts` | by construction (the config hash follows the code digest) |
| `machine.git_sha` 9b8eea6 to cdad21a; `run` q12la to q13; the two manifest copies' run-path refs; `derived.zarr` tree sha-256 `8c9e4186a0cd` to `77460c497b8c`, its `derived.digest.json` `built_from` | 5 leaves in `report.json`, 2 in the digest file, plus 1 check pair in each of 4 ledgers | by construction; 576, 601 (the store carries the code digest, so any code edit rebuilds it) |
| Wall times: `machine.wall_s` and `timing` 12 numbers (ingest 114.5 to **107.9 s**, stage 1 148.3 to 136.6, stage 1b 52.7 to 52.4, variants 273.1 to 267.4, emulator 377.0 to 371.8, windows 1.617 to 1.474, stage 3 0.152 to 0.139, refit 0.025 to 0.012, total 580.0 to 562.6 s which is 0.4834 to 0.4688 of the 1,200 s budget); the ledgers' `variant_wall_s` (6), `sensitivity_wall_s`, and the timing text in 5 ledger notes | wall time | run-to-run noise (0 to 8 % on the long stages); orca load was 1.4 to 2.0 before the run, and 6 workers of ours ran during it |

Everything else of the run is as in q12la: 0 numbers differ except the wall times. The differences q12 to q13 beyond these are row 690's list and nothing else: M-4 (`mode_notes` of the 7 modes that did not occur; the nonzero modes keep their notes), M-6 (the `used` flag on 287 credibility items and 285 report items, the `catalogue` node, `total/source` reworded), M-34 (items 115 and 116 value None to "n/a (see why)"), M-9 (`machine.timing.total`), M-28 (`les/cell_steps_per_window`), M-11 (the 343 RF margin samples). **No mover is unexplained; nothing was added to `review/orca/PROBLEMS.md` from this comparison.**

## Ingest wall time

| run | code | ingest |
|---|---|---|
| q11 | 778d8b6 | 131.8 s |
| q11la | 9a8fd5b | 168.1 s |
| q12 | 72d7e66 | 190.6 s |
| q12la | 9b8eea6 | 114.5 s |
| **q13** | cdad21a | **107.9 s** |

q13 is 82.7 s (43 %) under q12 and 6.6 s under q12la, on the same ingest code, at an orca load of 1.4 to 2.0 at the start. This is the floor row 690 gave for an ingest (about 100 to 115 s) and fits its inference that the +59 s of q12 was I/O wait on the shared disk, not a regression (P-R12Q1). It does not prove it: the one run that is slow (q12) has not been reproduced slow, and no per-check times exist in the ledger. Stages 1, 1b and the emulator are within 1 % of q12 (stage 1 136.6 s against 137.4 s) and within 8 % of q12la; the report stage took 23.1 s (q12la 23.6 s, q12 36.4 s).

## Audits (`python -m cafe.pm audit /data/runs/<run> --ledgers-only`, on cdad21a)

- **q13**: `audit: 0 problem(s)`, no note (it is the newest run, so it re-checks the shared `derived.zarr`).
- **q12la**: the `derived.zarr` note ("the bytes this run read were replaced by a later fetch, and this run can no longer be re-checked against them (what the run made is checked by its own ledgers)") and `audit: 0 problem(s)`. Row 690 said q12la prints no note; that was true while it was the newest run. q13's ingest rebuilt the one shared store for the new code digest, so from here q12la prints the same note as q12. Expected, as 690 states ("only the newest run re-checks it"); not a defect.
- **q12**: the same `derived.zarr` note, `audit: 0 problem(s)`; no note about the hangar tables (its hangar ledger records both).
- **q11**: three notes and `audit: 0 problem(s)`: the `derived.zarr` note; "the report ledger records neither mission.yaml nor plan.json (a run from before round 11): an edit of either is not seen here"; and the new one of 691, "the hangar ledger records neither platforms/modems.yaml nor platforms/radios.yaml (a run from before round 11's look-ahead, DECISIONS 635): an edit of either is not seen here". So the round 13 prefix does what 691 says, on a real old run: P-R12Q3 is met.

## Reading

On a TAO cache that did not change, code `9b8eea6` to `cdad21a` moves no number of the demo, not one array of the stage 1 or stage 1b results, and the verdicts, counts, intervals, priors, mooring count, flip, holdout, emulator design and sensitivity are byte-identical. What moved is provenance (head, run, config-hash ids, the rebuilt `derived.zarr` hash), wall times, and the entry-level count of assumed inputs that 681 changes (285 to 273 of 285; radios 8 of 19, modems 3 of 4), which prints exactly the figures row 690 predicted. Against q12 the movers are row 690's list. Open: nothing new; P-R12Q1 stays open as an inference.
