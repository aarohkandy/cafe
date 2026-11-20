# Hand-back: contribution table (work-order step 6 / done item 4)

Branch wo-table from 8ecf0e7. Only `cafe/pm/report.py` and the new `tests/test_wo_table.py` changed.

## What changed (cafe/pm/report.py)
- New `_contribution(rep, mission, st3)` after `_links`: returns `dict(rows={id: dict(kind, cfd, fea, emulator)}, statements=[...])`.
  - Vehicle CFD: `rep["stage3"]["refit"][vid]["used"]`. FEA: any raw stage-3 row of the vehicle with `fea.run is True`. Emulator: `rep["emulator"]["vehicles"][vid]["used"]` (the report's existing reading of holdout.json) or any `tried[].method == "EMULATED"` of the vehicle's fix.
  - Link CFD: either endpoint (`a`, `b`) is a vehicle with CFD yes; FEA and Emulator no.
  - Statements: `CONTRIB_ELLIPSOID` only when some CFD cell is yes; `CONTRIB_UAS` when the mission has a vehicle of class uas.
- New `CONTRIB_ELLIPSOID`, `CONTRIB_UAS`, `_contribution_html(c)`.
- Two insertion lines: `build` sets `rep["contribution"]` before `rep["sanity"]`; `_render` prints `_contribution_html` right after the Verdicts table, before the sensitivity-scope paragraph.
- No `hull_fea` dependency. SCHEMA unchanged (additive key).

## Where the code differs from the plan
- The plan builds on raw `refit` and `holdout`; I read `rep["stage3"]["refit"]` and `rep["emulator"]["vehicles"]` instead, so no new reader of holdout.json exists. Only the FEA flag needs the raw stage-3 rows (`st3`), as `_stage3` drops `fea`.
- `statements` key and cell keys avoid `value`/`values`, so `_walk` sees no number node.

## Regression tests (tests/test_wo_table.py), job names
All five fail on report.py at 8ecf0e7 (KeyError/AttributeError on `contribution`) and pass with the change.
- `test_contribution_rows`, `test_contribution_fea_and_used` (monkeypatches `pm_run.stage3_rows` so the ledgers stay clean, as the critic said), `test_contribution_emulator_used_in_holdout`, `test_contribution_files_missing`, `test_contribution_page`.
- Before: orca job run foreground by `bin/pmx.sh` (PMX=pm_wo_table), 5 F, rc=1. After: same command, 5 passed, rc=0. (Foreground, not TM: log /tmp/wo_before.log on the laptop.)

## Pins moved
None. Job `wo_table_1` (orca, pm_wo_table, 2 CPUs, `-n 2`), rc=0, 1,465 passed, 0 failed: tests/test_wo_table.py, test_round23_claims.py, test_report.py, test_cli.py, test_round16_report.py, test_round17_{a,b,m}.py, test_round18_{a,m}.py, test_round19_{b,m}.py, test_round20_{b,m}.py, test_round21_b.py, test_pipeline.py. `ruff check cafe/pm tests` clean; `mypy cafe/pm` clean (found 1 no-untyped-call on a lambda first, replaced it). No new claims-lint hit.

## Document text for the lead
DECISIONS (one row): The report's first screen carries a contribution table after the Verdicts table: per vehicle and link, yes or no for CFD (the refit used the vehicle; a link: one of its ends), FEA (a stage-3 row of the vehicle ran the hull FEA, `fea.run`) and Emulator (holdout.json `used` true, or the emulator answered one of the vehicle's fix candidates). Link FEA and Emulator are always no. "Emulator yes" says the emulator was used or answered a candidate, not that it changed a verdict; a GO vehicle with a trained emulator but no fix candidate reads no. FEA yes does not say the FEA passed. The ellipsoid sentence prints only when some CFD cell is yes, the UAS sentence when the mission has a UAS.
CHANGELOG: report: contribution table after the Verdicts table (CFD, FEA, Emulator per vehicle and link) and `report.json` key `contribution`.

## Printed text / keys added
- Header `Vehicle or link | CFD | FEA | Emulator`; cells `yes` / `no`.
- "The CFD geometry is a set of ellipsoids from a few yaml dimensions, not CAD." (only when some CFD cell is yes)
- "The UAS is out: its window is the frame without rotors." (when the mission has a UAS)
- Key `contribution = {rows: {id: {kind, cfd, fea, emulator}}, statements: [str]}`.

## Not verified
- First-screen position on a real run (the `tr` warnings may push the table below the fold); no browser look.
- On a real run: FEA yes only for glider LES windows today (step 2 will change that); link CFD rule not traced to the link verdict in `stage1.py:1051`.
- Whole suite, coverage gates, mutation not run.

## Still wrong / open
- Emulator ambiguity for GO vehicles (above). Done item 4 reads all "no" on a q24-style run until steps 1 to 4 land.
- A stage-3 RANS-CPU row will read CFD yes without saying RANS or LES.
