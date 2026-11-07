# q11 against q10lb (same machine, same worker count, same TAO cache, older code)

orca, `--budget quick --gpus 0`, `PM_CPUS=6 PM_MEM=16g`, TAO cache `tao/s2` (manifest sha `51ac8a96a104` in both). q10lb: code `6c1fde7`. q11: head `778d8b6`, started 2026-11-07 18:35 UTC, `rc=0` (`~/cafe-worker/logs/q11.log`). Orca load 3 to 5 on 32 CPUs and 805 GB free before the start. Compared: `report/report.json` leaf by leaf (11,737 leaves in each), then every file of the run.

## Nothing that is a number moved

| | q10lb | q11 |
|---|---|---|
| glider_eq | MARGINAL, k_fail 18, n 64, p_fail 0.28125 (Wilson 90 %: 0.199 to 0.381) | same |
| glider_2n | GO, 0, 64, 0.0 (hi 0.0406) | same |
| usv | NO-GO, 62, 64, 0.96875 (0.910 to 0.990) | same |
| uas | NO-GO, 55, 64, 0.859375 (0.773 to 0.916) | same |
| link usv-uas-rf | NO-GO, 64, 64, 1.0 | same |
| link glider_eq-ship-acoustic | NO-GO, 64, 64, 1.0 | same |
| link glider_2n-ship-acoustic | NO-GO, 64, 64, 1.0 | same |
| link usv-shore-iridium | GO, 0, 64, 0.0 | same |

- Fitted priors (`ingest/priors_fitted.json`), `env_sigmas_fitted.json` and `tao_compare.json`: byte-identical. Wind speed bias mean -0.4692, sd 0.5689, hi95 0.9572; noise 1.4609 m/s, tau 5.52 h; direction bias mean 6.2387, sd 5.2456, hi95 12.1529; noise 24.63 deg, tau 8.63 h; 14 moorings compared, 15 in the manifest.
- `report.json`: 0 numbers differ, not even within 1e-9 relative. `map` (3,055 leaves), `environment`, `reach`, `sanity`, `emulator`, `sensitivity_scope`, `subgrid` and `links` have no difference at all. `stage1/`, `stage1b/` (`summary.json`), `windows/`, `stage3/`, `hangar/`, `refit/` and `emulator/holdout.json` files are byte-identical; `traceability_problems` and `ledger_problems` are empty.
- Mooring count: 14 compared, as q10lb. The 15th, T5N170W, has QC flag 9 for the whole window (the ledger now says so; row 587).

## What differs (88 of the 11,737 leaves: 11 wall-time numbers, 8 texts of the flip table, 69 provenance strings), with its row

| mover | size | DECISIONS row |
|---|---|---|
| Flip table `tried` rows for "deploy 6 / 12 / 24 / 48 h earlier" of glider_eq and usv (and the same text in `emulator/flip.json`): the sentence "(flies 6.25 d instead of 6 d: P(fail) is over the longer flight ...)" is gone. The rows are "not evaluated" in both runs, with the reason "deploying -6 h gives 2023-03-01T06:00:00Z, outside the window", so a flight sentence for a shift that `apply` refuses was wrong in q10lb | 8 leaves in `report.json`, 8 in `flip.json` | 586 (`whatif._deploy_in_window`; code change after `6c1fde7`) |
| `machine.git_sha` 6c1fde7 to 778d8b6; `run` q10lb to q11; the receipt ids `...:config:d13d64ef69c1` to `...:config:f5b7d3e91a1b` and the sha-256 of the same receipts (19 leaves under `receipts`, 45 more that quote the id under `machine`, `mission`, `map`, `vehicles` and `stage3`) | provenance | the config hash follows the code digest; by construction |
| `mission.data_consumed.inputs[1]` and `[9]`: the `ref` is now the run's own copy of the orca and TAO manifests (`ingest/orca_manifest.json`, `ingest/tao_manifest.json`), the sha-256 is the same (`4086aaed7a0d`, `51ac8a96a104`); the two copies are new files in the run | 2 leaves, 2 new files | 574 (manifest copy), 575 |
| `mission.data_consumed.inputs[8]`, `derived.zarr` tree sha-256 `c6f45017e85b` to `e30fd259dcf3`; `ingest/derived.digest.json` `built_from` `4d568548...` to `a3ee98a3...` | 1 leaf, 1 file | 576. The store carries its `built_from` key as an attribute (`env/surface.py` line 129), and the key holds the code digest, so any code edit rebuilds the layer under another hash. This is not proven by comparing the arrays: q10lb's store was overwritten by q11's rebuild and no copy of it exists. What backs "same data" is that the TAO manifest hash and the WRF manifest hash are equal and every number downstream of the layer is bit-equal |
| `credibility.json`: the evidence path of factor 0 (`/data/runs/q10lb/...` to `/data/runs/q11/...`), `run` | 2 leaves | the run's name |
| `machine.timing` and `wall_s` (11 numbers): ingest 339.5 to 131.8 s, stage 1 148.1 to 137.7, stage 1b 52.4 to 50.5, variants 271.9 to 266.6, emulator 379.7 to 370.3 | wall time | ingest of q10lb included the 202 s cold fetch of `tao/s2` (its ledger says so); q11 found the cache warm and did not fetch (131.8 + 202 = 334, close to 339.5). The rest is run-to-run noise at 3 to 7 % |
| `emulator/design.json` `train_input_rows` 89 to 110 (`table_rows` 110 and `rows_added` 28 in both) | 1 leaf, not in `report.json` | not a code change: the shared table `/data/emulator/train.parquet` is what every run appends to (28 rows, deduplicated), so q11 starts from the 110 rows q10lb left and q10lb started from 89. The report's `emulator` block (7 rows of scope glider/seaglider/144h, 100 needed, not trained) is identical in both, as the other scopes are |

Not attributed: none. Nothing went to `review/orca/PROBLEMS.md` from this comparison.

## Audits

- `audit /data/runs/q11 --ledgers-only`: `audit: 0 problem(s)` (exit 0).
- `audit /data/runs/q10lb --ledgers-only` after q11 rebuilt the shared `derived.zarr`: `audit: 0 problem(s)` with one note, "the bytes this run read were replaced by a later fetch, and this run can no longer be re-checked against them (what the run made is checked by its own ledgers)". That is rows 576 and 591 working: moved_numbers.md predicted the audit of q10lb would fail after the next code edit, and it does not.

## Reading

On a TAO cache that did not change between the two runs, the code changes from `6c1fde7` to `778d8b6` move no number of the demo: the data change of round 10 (moved_numbers.md, P-40) was the whole of q10lb's movement, and q11 reproduces q10lb's verdicts, counts and priors exactly. The one visible code effect is the flip table's text (586).
