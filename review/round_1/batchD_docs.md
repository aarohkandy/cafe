# Batch D docs (report, credibility, what-if, emulator, acceptance), to be applied by the integration builder

## DECISIONS

1. **M-1.** A receipt is provenance, not a pass.
   - An output receipt carries the output's own quality bit. For stage-3 `windows.json` it is ok if and only if some window passed its self-checks.
   - Each vehicle and link verdict cites the model-receipt group of its class in `runs/receipts.json` as pass and fail counts, with context rows excluded. The groups are pm.physics.glider, usv, uas (including .slow) and comms.
   - A missing table is "not run", never ok.
   - A failed output or model receipt is shown as FAILED OR MISSING and does not fail `report_traceable`. A missing ledger or a failed ledger check still does.
2. **M-6.** `flip_search` splits the Stage-1 budget over the non-GO vehicles and rolls the unused part forward. For each vehicle it records `evaluated`, `invalid` and `candidates`. The report says "not searched" when no candidate was evaluated.
3. **M-8.** Training rows are keyed by mission, class, vehicle, variant and features, not by run directory.
   - The emulator trains only on rows with the current `code_digest`; a row without one is stale.
   - `MIN_ROWS` counts distinct feature points.
   - The hold-out splits by feature point.
4. **M-18.** The report gives the stopper's 95 % interval and the verdict thresholds as traced nodes. They are labelled separately from the verdict's own 90 % interval. `check_rendered` matches whole numeric tokens.
5. **M-22.** The flip search's seconds are a planned charge. No measured wall time goes into `report.json` beyond `machine.wall_s`.
6. **M-24, M-30.**
   - Credibility prints each perturbation prior as its distribution, and adds the run's fitted draw when it differs.
   - A sanity block compares the demo mission's verdicts with BRIEF section 6. The report gives the mode of the first failure and each mode's share of the failed members.
7. **M-33.** The golden is a regression snapshot of this tool's own output from a reviewed quick run, not an independent expectation.
   - It must record a commit sha, a clean tree, the code digest and the reviewed run's report hash; otherwise `golden_diff` FAILs.
   - A verdict change that is undecided in both runs passes only while the two runs' 95 % P(fail) intervals overlap.
8. **Sub-grid layer.** "sub-grid layer uncalibrated: <reason>" is limitation L13. The reason comes from the stage-3 ledger note, or else from `config/subgrid.json` `calibration.source_run` being null. L13 caps the validation and uncertainty factors, and the report shows it as a warning.

## CHANGELOG (Fixed, review round 1, report and credibility)

- One line for each of M-1, M-6, M-8, M-18, M-21, M-22, M-24, M-30 and M-33, as above.
- M-21: a window that was not run says "did not run" and gives the reason, with no empty failed-check list.
- report/credibility: the sub-grid layer is shown as uncalibrated and listed as limitation L13.
- links table: the margin prints n/a when there is no budget sample, and a column gives the beyond-horizon or out-of-range share.
- The `_n()` HTML in the candidates table was escaped and printed as raw text.

## RUNBOOK

- **Troubleshooting row 4:** for a window that was not run, the report now shows "W3 did not run; not used in the refit: free-surface window not run: ...".
- **New paragraph on the golden:** the golden is a regression snapshot, not an independent expectation.
  - Rewrite it with `./pm.sh python -m cafe.pm acceptance ... --update-golden` from a reviewed quick run, on a clean, committed checkout.
  - `golden_diff` FAILs until then.
- **New note on model receipts:** a report with no `runs/receipts.json` says "Model receipts: not run". Run `python -m cafe.pm receipts` first.
