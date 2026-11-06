# q10 against oq9 (same machine, same worker count, older code)

orca, `--budget quick --gpus 0`, `PM_CPUS=6`. oq9: code `91c9777`. q10: head `8b870a6` (log `~/cafe-worker/logs/q10.log`, `rc=0`; 137 s stage 1, 52 s stage 1b, 364 s emulator, 31 s report). Orca load 0.7 on 32 CPUs and 383 GB free before the start. Compared: `report/report.json` leaf by leaf, then the stage files `ingest/`, `refit/`, `stage1/`, `stage1b/`, `windows/`, `stage3/`, `hangar/`.

## Verdicts: nothing moved

| | oq9 | q10 |
|---|---|---|
| glider_eq | MARGINAL, k_fail 15, n 64, p_fail 0.2344 | same |
| glider_2n | GO, 0, 64, 0.0 | same |
| usv | NO-GO, 60, 64, 0.9375 | same |
| uas | NO-GO, 55, 64, 0.8594 | same |
| link usv-uas-rf | NO-GO, 64, 64, 1.0 | same |
| link glider_eq-ship-acoustic | NO-GO, 64, 64, 1.0 | same |
| link glider_2n-ship-acoustic | NO-GO, 64, 64, 1.0 | same |
| link usv-shore-iridium | GO, 0, 64, 0.0 | same |

The failure modes' member counts are equal too, except `usv` `wing_stall_angle` 13 to 14 (members can have several modes; k_fail is 60 in both). No flip search found a flip in either run.

## What else moved in report.json

3,535 of about 11,700 leaves differ: 3,336 numbers beyond 1e-9 relative, 52 numbers within it, 129 texts, 16 added keys, 2 other. 3,045 are under `map` (member tracks and medians), 290 under `environment` (the forcing along those tracks).

| mover | size | DECISIONS row |
|---|---|---|
| Fitted wind priors: `ingest/priors_fitted.json` and `tao_compare.json`. Speed bias mean -0.6165 to -0.6099, sd 0.1131 to 0.1099, hi95 0.4836 to 0.4609; direction bias mean 7.2128 to 7.2126; mooring T5N165E speed bias 1.209 to 1.142. This is the first thing that differs in the chain; everything below follows from it | 10 numbers | 492 (one lift for `tao.compare` and `pipeline._wind_residuals`, air state only within `tao.air_gap_s` of a sample) |
| Member tracks and medians (`map`): usv up to 0.032 deg, glider_eq 0.0037 deg, glider_2n 4e-5 deg; `environment` forcing along them: usv wind 10 m up to 0.007 m/s, Hs 0.0009 m, current 0.0024 m/s; `windows`/`stage3` window positions; `sensitivity_scope` wind SDs and hi95; noise floors (usv 0.19425 to 0.19468, glider_eq 0.11799 to 0.11837); S1 (glider_eq 0.123916 to 0.123924); usv speed 0.7408 to 0.7420, SOG 0.6747 to 0.6798; uas authority clamp and demand ratio (+0.3 % at the median); link distances (usv-uas-rf median 81.03 to 81.07 km, `frac_beyond_horizon` 0.89349 to 0.89370, margin 16.633 to 16.630 dB) | continuous, no verdict | follow from the row above (492). Not shown by a separate run with 492 reverted; the evidence is the priors differ at the first stage and the size of the moves follows their size (glider_2n, the vehicle least touched by wind, moved least) |
| `usv` `failed_at` of the 60 failed members in the window block: 16 differ by 60 s multiples (-360 s to +2,160 s); `uas` 30 of 55 differ by -23.6 s to +24.6 s | | 487 (a USV flag is stamped with the end of the step: +60 s) and 492 (a member whose track moved fails at another time) |
| Reach polygon of glider_2n: vertex 9 (-170.0, 2.0) to (-169.857, 1.857), a cell on the 135 degree diagonal | 1 vertex | 525 (the sector from the bearing rounded before `% 360`) |
| Reach polygon of usv: all 24 vertices by about 1e-4 deg, vertex 7 by one cell (0.068 deg); `max_range_km` 98.91 to 98.98, `speed` +0.16 % | | 492 through the speed; the cell flip is the 24 h threshold `tt <= hours * 3600` on a 0.16 % faster speed, not 525 (no integer offset has a bearing at a sector edge except the axes and diagonals) |
| `derived.zarr` sha-256 `b07e6b4e...` to `851862f7...`, and the `built_from` key in `ingest/derived.digest.json` | 2 | `s_ingest`: the key holds the code digest, "every code edit rebuilds it". The layer's numbers were not compared (the shared cache holds only the new store) |
| `assumed_inputs`: 283 to 285 items (+`tao.air_gap_s`, +`bathy.gofs_open_level_sigma_m`) | 2 | 492, 495 |
| New keys: `vehicles/uas/modes/no_current_data` (0 members, with its note and share) | 3 | 463 |
| New keys: `vehicles/uas/uas_limits` (tilt clamp 35 deg, exceedance 42 deg; `None` for the other vehicles) | 3 | 511 |
| New key `vehicles/usv/speed_ratio/ratio_anem` 0.1346; `sanity` row 2 compares the ratio at the anemometer height with Chiodi et al. (value 0.129 to 0.135, wording) | 2 | 467 |
| New key `stage3/vehicles/*/diverged` (`False`, 6 windows) | 6 | 484 |
| New key `emulator/run_note`: "6 variant runs of the 6 planned and the base mission, 7 points in the smallest vehicle class (100 are needed)" | 1 | 470 and 531 (the 7 comes from `holdout.json`, as 531 says) |
| `machine/machine/warning` (throughput.json was measured on homebase) | 1 | 469 |
| Refusal texts of what-if moves outside the box: the dict `{'lon_min': 165.0, ...}` to "(lon 165 E to 165 W (across the antimeridian), lat -5 to 5, pad 2 deg)" (usv, uas, 4 texts) | 4 | 474 |
| Emulator reasons, 27 texts (3 class, 14 glider_eq and 10 usv candidates): "...; 14 rows made by other code are left out" appended | 27 | 174 (the table is shared and keyed by mission, not by run; `whatif.fit_class` leaves out rows of other code) |
| `emulator/design/table_rows` 28 to 49 (`rows_added` is 28 in both, 6 variants in both) | 1 | 174: the shared table on orca already held 21 rows when q10 began (oq9 began with none: its `table_rows` equals its `rows_added`), left by other runs since (the glider reason says 14 rows made by other code are left out) |
| Receipts: `physics.status` "stale: made by other code" to "not run" (4 links, 4 vehicles); reason "runs/receipts.json has no readable receipts.meta.json" to "is not there" | 8 | 499. oq9's checkout was synced before `bin/sync_filters`, so the laptop's `runs/receipts.json` (29 Oct) went with it; the filter now keeps `/runs/` out, and orca has no `runs/receipts.json`, so the page says "not run". Not a change in the reader. The receipts stay unrun until `make receipts --slow` at code freeze (527, 528) |
| Run name, git sha, config hashes in every `receipt` id, ledger ids | | bookkeeping (hash of `config/assumptions.yaml`, which has two more keys) |
| Wall seconds: ingest 245 to 157, stage 1 176 to 137, stage 1b 54 to 52, emulator variants 274 to 261, emulator stage 380 to 364 | | machine load at the time, not code; planned stage 1 is 53 s in both, as P-7 states |

## Movers no DECISIONS row explains

None found. The one step that rests on reading rather than on a run is the chain from 492 to the tracks: no run with 492 reverted was made (a run is 20 minutes of orca), so the attribution rests on the priors differing at the first stage and on the sizes of the moves. No row was added to `review/orca/PROBLEMS.md`.

## Same machine, but still not identical

`stage1b/sensitivity_cases.json`, `refit/refit.json` and `hangar/hangar.json` are equal. oq9 and q10 differ in code, so none of this tests "same seed identical report"; that claim holds on one machine for one code state (P-2).
