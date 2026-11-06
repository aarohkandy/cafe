# Round 10, look-ahead L0 hand-back: the TAO selection bump (cache directory) and the stage-3 row time (report)

Branch `r10-merged`. Tests ran on cafe-orca (`PM_HOST=cafe-orca PM_RUNTIME=proot`, `PMX=pm_r10m`, 2 CPUs). Docs (DECISIONS, CHANGELOG, RUNBOOK) are not edited here: the text for them is below.

## 1. The TAO selection bump invalidates earlier runs and forces a network fetch

Root cause: one cache directory (`<data>/tao`) served every selection rule, and the run ledger hashes its `manifest.json`. The first run of a new rule rewrote that manifest in place.

Fix, in the one shared place: `tao.cache_dir(data)` returns `<data>/tao/s<SELECTION>`. The two readers of the directory (`pipeline.ingest` and `pipeline._tao`) and the receipts job `pm.env.tao` take it from there; so do the `ci_env` generator and the tests. The manifest and files of an older rule (`<data>/tao/manifest.json` and `<data>/tao/<mooring>/`) are never opened or written again, so the ledgers that hash them keep auditing. The `bin/worker_setup.sh` and `bin/orca_sync.sh` copies take the whole `tao` directory, so `s2` goes along with it. `_tao_cached` keeps its `selection` check (a copy of an older cache put into `s2` by hand is still refused).

Offline: a pre-round-10 cache cannot be used by the new rule without the catalog (the rule picks the files from it), so the first run needs network once. The check `tao_present` now says so when only the older cache exists: "(the cache in <data>/tao was selected by an older rule and stays as it is for the runs that read it; this code fills <data>/tao/s2: one run with network access)".

Callers checked: `pipeline.ingest` (sbox, `_need`), `pipeline._tao`, `receipts.jobs`, `tests/fixtures/ci_env/make.py`; no other reader of `DATA/tao` (grep of the repo). Not changed and noted as P-31: the same ledger/manifest problem exists whenever a cache grows (wider box or window), for TAO and orca alike.

Test: `test_ingest_fetch.py::test_l0_fetching_under_a_new_tao_selection_rule_leaves_the_manifest_an_earlier_run_hashed_as_it_was` and `::test_l0_offline_with_only_a_cache_of_an_older_selection_rule_fails_the_check_and_says_which_cache_stays`. Both fail on a mutant where `cache_dir` returns `<data>/tao` (the old behaviour) in a detached worktree (removed), and pass on the fix.

## 2. "Time not shown" on every normal USV report

Root cause: `report._stage3` used the row index as the window index. A window has one row per part (USV: hull, wing, hull_fs), so row 2 and 3 of a one-window USV looked up window 2 and 3, and with two windows the wing of window 1 read the time of window 2 (a wrong time, not only a missing one). The label `W<row>` had the same mix-up.

Fix, in `report._stage3`: each row is matched to its window by the t, lon and lat the stage writes into the row (`pipeline_windows._base`), and takes that window's time (traced to `windows/windows.json <vid>[<k>].t`) and label `W<k> <part>`. A row that matches no window gets `t` null, the label `row <n>` and the reason "windows/windows.json has N window(s) for <vid>, none at the time and place of this row" instead of borrowing another window's time. A run without `windows.json` still says so (M-9, unchanged). The map and forcing sections index `windows.json` by its own window index and were not affected.

Fixture change: `tests/fixtures/pm_run.stage3_rows` now writes rows with the t, lon, lat and part of their window, as the stage does. Two tests changed because they had pinned the defect: `test_r10_m9_an_intact_run_has_no_missing_windows_note` (said "a stage-3 row beyond the windows" has no time; now no row lacks one and the page has no "Time not shown") and `test_a_window_that_was_not_run_shows_its_reason_not_an_empty_list` (its appended row now carries its window, label `W1 hull_fs`).

Test: `test_report.py::test_l0_a_stage_3_row_takes_the_time_of_its_window_not_of_the_window_at_its_index` (a USV with two windows and rows hull, wing, hull_fs each; then a row that matches no window). Fails on a mutant with the index lookup (TypeError on the missing time); passes on the fix.

## Text for the documents (the lead's doc pass)

DECISIONS row (number after the last):
| NNN | The TAO cache of a selection rule lives in `<data>/tao/s<SELECTION>` (`tao.cache_dir`), not in `<data>/tao`. The run ledger hashes the cache manifest, so rewriting the one shared manifest when the rule changed (M-19, SELECTION 2) made every earlier run in the data directory fail its ledger audit ("input .../tao/manifest.json changed since the stage ran"). The older cache stays as it is. The first run of a rule fetches TAO again, which needs the network; an offline machine fails `tao_present` until one run (or `fetch`) has been done online. The stage-3 rows of the report take their window by t, lon and lat, not by their index (a window has one row per part), and are labelled `W<k> <part>`. | The alternative was to document that older runs stop auditing and to fetch once on every cache: it leaves the reference runs of the round unverifiable. The growing-cache case is open (P-31). |

CHANGELOG line:
- TAO cache of the current selection rule in `<data>/tao/s2` (`tao.cache_dir`): the first run on this code fetches TAO again (network needed once, also for a machine that runs with `CAFE_OFFLINE`), and the older cache and the ledgers that hash it are left as they were. Report: a stage-3 row takes the time of its own window and is labelled `W<k> <part>`; "Time not shown" no longer appears on a USV with one window.

RUNBOOK sentences:
- Under "Running offline" / first install: "The first run after the round-10 update fetches TAO into `<data>/tao/s2`; do it once online with `python -m cafe.pm fetch --mission M` on every machine that later runs with `CAFE_OFFLINE`. The older `<data>/tao/manifest.json` and its files stay, and the runs that read them still audit."
- Troubleshooting row for `variable ..._QC is missing` (line 273): the manifest to delete is `<data>/tao/s2/manifest.json`, not `<data>/tao/manifest.json`.
- Row for `tao_present` "not cached and CAFE_OFFLINE is set ... (the cache in <data>/tao was selected by an older rule ...)": run `fetch` online once.
