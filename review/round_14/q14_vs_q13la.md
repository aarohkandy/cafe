# q14 against q13la and q13 (same machine, same worker count, same TAO cache, newer code)

orca, `--budget quick --gpus 0 --fresh`, `PM_CPUS=6 PM_MEM=16g`, TAO cache `tao/s2` (`tao_manifest.json` and `orca_manifest.json` byte-identical in all three). q14: code `20537b1` (head of `premission-step4`, clean tree), tmux `q14` started 2026-11-10 08:51 UTC, `rc=0` (`~/cafe-worker/logs/q14.log`), report done 09:05; orca load1 6.2 at the start (q13: 1.4 to 2.0). q13la: `ae8f3d5`; q13: `cdad21a`. The code between q13la and q14 is `8c672bf`, `d3a3f33`, `56f5631`, `712773b` and the round 14 prefix (24 files under `cafe/`), none of which had run in a demo. Compared on orca with `review/round_13/q13cmp.py` unchanged (`python q13cmp.py q14 q13la`, then `q14 q13`) and `review/round_14/q14summary.py` (verdicts, priors, mooring count, plan, timing, side by side). Both read only.

## Nothing that is a verdict or a count moved

| | q14, q13la and q13 |
|---|---|
| glider_eq | MARGINAL, k_fail 18, n 64, p_fail 0.28125 |
| glider_2n | GO, 0, 64, 0.0 |
| usv | NO-GO, 62, 64, 0.96875 |
| uas | NO-GO, 55, 64, 0.859375 |
| link usv-uas-rf, glider_eq-ship-acoustic, glider_2n-ship-acoustic | NO-GO, 64, 64, 1.0 |
| link usv-shore-iridium | GO, 0, 64, 0.0 |

- Same in stage 1 and stage 1b (fail_lo, fail_hi, n_certify 73 too). `stage1/res.pkl` and `stage1b/res.pkl`: sha-256 `a8d709692e28` in all three, **0 of 295 arrays differ** (each file). Byte-identical to q13la: `priors_fitted.json` (wind speed bias mean -0.4692, sd 0.5689, hi95 0.9572; 14 of 15 moorings compared, T5N170W left out), `env_sigmas_fitted.json` (sst_k 0.3028, t2_k 1.1910), `tao_compare.json` (15 keys), `hangar/hangar.json`, `windows/windows.json`, `stage3/windows.json`, `refit/refit.json`, `stage1/summary.json`, `stage1b/summary.json`, `stage1b/sensitivity_cases.json`, `mission.yaml`, both manifests. 34 files in each run, none only in one.
- q14 ran 6 of 6 emulator variants (q13 6 of 6, q13la 5 of 6, killed before v5 at the 240 s share). With q13 the count is the same, so `emulator/design.json` and `holdout.json` are byte-identical to q13's (rows_added 28, table 110 rows).
- Assumed inputs 270 of 285 (`assumptions.yaml` 96, `perturbations.yaml` 12, modems 3, radios 8, quad_uas 45, saildrone 59, seaglider 21, slocum 26; not used: assumptions 3, modems 1, radios 11), as q13la.

## q14 against q13la: 382 json leaves differ, each with its row

133 follow the variant count (design 27, flip 34, holdout 20, report 52; `[load-dependent]` in the script's output). 249 do not:

| mover | size | DECISIONS row |
|---|---|---|
| `plan.json` `stage3.fea.min_s` 8.0 to **68.2** | 1 leaf, the only one of `plan.json` | 741 (P-R13L0-2): row 758's predicted change. The demo's FEA stays planned out (`fea.runs` false, `share_s` 0.0), so no window changes |
| the credibility page's assumed input for it: `value` 68.2, `why`, `replace_with` (reworded) | 3 leaves in `credibility.json`, 2 in `report.json` (`value`, `why`) | 741 |
| stage-3 ledger: `assumptions.yaml` input gets the key `values_only: true`; its `sha256` is the values hash | 1 key, plus the hash among 11 provenance leaves | 753, as row 758 says |
| `credibility.json` evidence text 'ledger chain audits clean; **54** test files present' (53) | 1 leaf | `tests/test_q13cmp.py` added by `56f5631` (row 754); also `run` and one evidence path (q14 for q13la) |
| config-hash receipt ids (`6083b174f854` for `4cd59e2d1a2d`) in `machine`, `map`, `mission`, `vehicles`, `stage3` | 45 ids; in `receipts` 8 ids and 12 sha-256 | by construction (the config hash follows the code digest) |
| `machine.git_sha` ae8f3d5 to 20537b1; `run`; 2 manifest-copy refs; `derived.zarr` sha-256 `bd8b04ab...` to `419e0de7...` and `derived.digest.json` `built_from` | 5 in `report.json`, 2 in the digest, check pairs (limit, value) in 4 ledgers | by construction; 576, 601 (any code edit rebuilds the store) |
| ledger provenance leaves (refs, shas, config hash, git sha, started, wall) | 127 over 9 ledgers | by construction |
| wall times: `machine.wall_s` and `timing` 12 leaves, the ledgers' `variant_wall_s` (6), `sensitivity_wall_s`, the timing text in ledger notes | | run-to-run noise, except ingest and report below |
| emulator and flip figures: rows_added 28 vs 24, spent 158.1 vs 131.7 s, variants 6 vs 5, points per scope 7 vs 6, 34 `reason` texts of the flip search, `run_note` '6 variant runs' vs '5' | the 133 | 754 and 288 (the variants the machine had time for); P-R13L2-1 |

**No mover is unexplained.** Row 758 predicted `stage3.fea_min_s` 8.0 to 68.2 s and the `values_only` key in the stage-3 ledger; q14 prints both, and the count 270 of 285 and every verdict as q13la. The look-ahead commits `8c672bf`, `d3a3f33`, `56f5631` and `712773b` therefore moved nothing else that the demo reaches (no leaf of `stage1/*`, `ingest/*` priors, `hangar`, `windows`, `refit`, `stage3/windows` differs).

## q14 against q13: the movers are rows 693 to 758

`stage1/res.pkl` and `stage1b/res.pkl` 0 arrays differ; 336 json leaves differ, 143 of them in `report.json` (same variant count, so none tagged). Besides the 741 and 753 rows above and the by-construction leaves: **695** (M-3): assumed inputs 273 to 270, `assumptions.yaml` 99 to 96 used, 3 `used` flags True to False (the three `dtmb5415.u_*` items), the `not_used_by_file` node gains `assumptions.yaml` (3), the source wording ('of a platform or vehicle class this mission uses'); **736** (M-44): `replace_with` of the USV hull draft (2 leaves); **733** (M-41): the UAS flip search lists 12 changes, not 14, so `candidates` 12 to 10 and 36 leaves of `flip.json` (the 0.75 duty is the 2 d period of 0.5 and is one candidate at 2.0 notches, 12 h earlier is 12 h later), which also moves `fix/tried` in `report.json`. The rest are wall times (ingest 107.9 s in q13). Row 758 had said q13la's candidates followed the variant count; they follow row 733 (below).

## One attribution in the documents is wrong (PROBLEMS P-R14Q2)

UAS candidates are 10 in q14 (6 variants) and in q13la (5 variants), 12 in q13 (6 variants): the count follows the code (row 733), not the variants. DECISIONS 754 and 758 and `review/round_13/q13_vs_q12la.md` read 'flip candidates 10 to 12' as load, and `q13cmp.py` tags every `/fix/` node and `emulator/flip.json` leaf `[load-dependent]` when the counts differ. The leaves that follow the count are the `reason` texts ('6' or '7 rows in the training table') and the figures above. No number of the product is affected.

## Wall times (PROBLEMS P-R14Q1, open)

| run | code | ingest | report stage | stage 1 | stage 1b | emulator | counted total (of 1,200 s) |
|---|---|---|---|---|---|---|---|
| q12 | 72d7e66 | 190.6 | 36.4 | 137.4 | | | |
| q13 | cdad21a | 107.9 | 23.1 | 136.6 | 52.4 | 371.8 | 562.6 s, 0.4688 |
| q13la | ae8f3d5 | 113.1 | 24.8 | 142.5 | 53.2 | 377.2 | 574.9 s, 0.4791 |
| **q14** | 20537b1 | **161.3** | **37.7** | 142.2 | 52.0 | 382.1 | 578.2 s, 0.4818 |

Ingest is 53.4 s (49 %) over q13 and 48.2 s (43 %) over q13la; the report stage 14.6 s (63 %) and 12.9 s (52 %) over them; the compute-bound stages are within 4 %. q12 slowed the same two stages (ingest +83 s, report +13 s) with the CPU stages unchanged. The ingest and report code did not change in a way that reads or writes more (`FETCH_CMD` texts, `ledger.real`, `sampling.load_perturbations`), the recorder shows host load1 3.1 to 4.3 over the ingest minutes against 1.3 to 3.3 in q13. That fits row 690's inference (I/O wait on the shared disk) and does not prove it; no controlled rerun was made.

## Audits (`python -m cafe.pm audit /data/runs/<run> --ledgers-only`, on 20537b1)

- **q14**: `audit: 0 problem(s)`, no note (newest run, it re-checks the shared `derived.zarr`).
- **q13la**: the `derived.zarr` note, `AUDIT FAIL: q13la: stage stage3: input /app/config/assumptions.yaml changed since the stage ran`, `audit: 1 problem(s)`. For q13la the cause is the value edit of row 741.
- **q13**: the same note, the same `AUDIT FAIL` line, `audit: 1 problem(s)`. Both edits (736 wording, 741 value) change the byte hash its ledger holds.

These are the lines row 758 gave and row 753 explains (an old ledger holds the byte hash, which cannot be told from a real value edit). q11 to q13la are history for the audit; q14 is the baseline of round 14.

## Reading

On a TAO cache that did not change, code `ae8f3d5` to `20537b1` moves no verdict, count, interval, prior, mooring count or array of the demo. What moved is `stage3.fea_min_s` (8.0 to 68.2 s, row 741) with its credibility text, the stage-3 ledger's `values_only` key (753), provenance, and wall times; the emulator figures follow the 6 of 6 variants as in q13. q14 prints what row 758 predicted. Open: P-R14Q1 (ingest and report time, cause shown only by inference), P-R14Q2 (rows 754 and 758 and `q13cmp.py` attribute row 733's change to load).
