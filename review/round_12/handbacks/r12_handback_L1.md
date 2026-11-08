# Round 12, look-ahead L1 handback (branch r12-merged, from 7c6210a)

Five look-ahead findings. Four fixed at their shared place with a fail-first test; one (stored CFD and SITL results never stamped) was already fixed by L0 and needs nothing. No document but `review/round_12/q12_vs_q11.md` is edited here: the DECISIONS rows and CHANGELOG lines below are for the lead to apply. PROBLEMS rows: P-R12L1-1 and P-R12L1-2.

Files: `cafe/pm/env/conventions.py`, `pipeline.py`, `env/hycom.py`, `env/bathy.py`, `env/environment.py`, `env/remote.py`, `receipts.py`, `__main__.py`; tests in `tests/test_conventions.py`, `test_environment.py`, `test_hycom.py`, `test_bathy.py`, `test_receipts.py`, `test_remote.py`.

## M-24 (sibling): one name for a box in every message
- Change: `conventions.box_words(box)` ("lat -7 to 7, lon -12 to 12", for a (south, north, west, east) box) replaces `pipeline._box_words` (moved, not copied; `pipeline` was its only caller). It is used by the three `ocean_box` refusals, `hycom.box360` (two messages), `hycom.read_archv` and `hycom._sub` ("no lab-HYCOM points ..."), `bathy.fetch_gebco` ("no grid points ..."), and `GriddedEnv._check` (OutsideData), whose `bounds` are (west, east, south, north, t0, t1), so it passes `bounds[2:4] + bounds[:2]`. `ocean.bounds()` has the same order and goes through the same `_check`.
- Callers checked: every message above is read by a test with `match=` on the leading words only (`crosses 0/360`, `more than the whole circle`, `no lab-HYCOM points`, `no grid points`, `crosses 0 deg E; ...`); none matched the tuple. The one test that did (`test_outside_data_names_the_point_and_the_box`) now matches the words; the point, the times and the advice in the message are as before. Not changed: `fmt_box` (config.py, for the mission dict, already labelled), `orca.py:201` (no box printed).
- Sweep: grep of `cafe/pm` for `box {`, `{box}`, `bounds[:4]` leaves no unlabelled tuple.
- DECISIONS row: "A box in an error message is written by `conventions.box_words` as `lat S to N, lon W to E`: `ocean_box`, `hycom.box360`, the lab-HYCOM and GEBCO empty-box refusals and `OutsideData` all use it. A bare tuple of the box is not printed, because (south, north, west, east) and (west, east, south, north) were both in use. Test: `tests/test_*::test_r12_l1_m24_*`. Amends the M-24 row." Why: "Look-ahead L1 after round 12, M-24. The fix labelled the `ocean_box` refusals only; the message people meet when a track leaves the data (`OutsideData`) printed the tuple in the other order."
- CHANGELOG: "Every box in an error message reads `lat S to N, lon W to E`, including OutsideData and the HYCOM and GEBCO refusals (look-ahead L1, M-24)."

## M-31 (sibling): `receipts --only ""` ran the whole table
- Change: the command line passes `a.only.split(",")` whenever `--only` was given (`is not None`), so `""` is `[""]` and the existing check refuses it with exit 2; `receipts.run` treats an empty list like an empty part (`only or [""]`). `collect` and the output-file choice test `only` by truthiness, but `run` is their only caller with a user-supplied value and it now refuses `[]` first.
- Callers: `acceptance._broken` calls `run(only=[WAVE_MODULE])` (non-empty), `run(broken=...)` (None).
- DECISIONS row: "`receipts --only` given empty (`--only ""`, or an unset shell variable) is refused with exit 2 like an empty part of a list: 'given' is tested with `is not None`, not by truthiness, and `receipts.run(only=[])` is refused too. Test: `tests/test_receipts.py::test_r12_l1_m31_*`. Amends the M-31 row." Why: "Look-ahead L1 after round 12, M-31. An empty string was falsy, so the check for an empty part never ran and the full table was written."
- CHANGELOG: "`receipts --only \"\"` exits 2 instead of running every group (look-ahead L1, M-31)."

## M-25 (sibling): a server with no validator cannot have a part resumed
- Change: in `remote.download`, a `.part` left by an earlier call is kept only if the sidecar matches and the server sends a validator that can go in If-Range (`_if_range(valid)` is not None: a strong ETag or Last-Modified). Otherwise it is removed and the file is fetched from byte 0. A weak ETag alone counts as no validator (the first pass already said it cannot be an If-Range validator). A transfer cut inside one call is still continued from where it stopped (seconds apart; size and 206 still checked): a restart there could loop on a link that always cuts.
- Callers: `tao.fetch_tao` (the only one; `pin=False`). Cost: a TAO fetch interrupted on a server with no validator restarts from byte 0. I did not check whether the real TAO server sends a validator; if it does, nothing changes for it.
- Tests: the existing `test_download_resumes_a_partial_file` used the test server, which sends no validator, and so pinned the hazard as the behaviour; it now uses the `versioned` fixture (a server with an ETag). The in-call cut test (`test_download_resumes_after_a_connection_cut_mid_body`) is unchanged and passes.
- DECISIONS row: "`remote.download` resumes a `.part` of an earlier call only when the server sends a strong ETag or a Last-Modified and the `.part.id` record equals what it sends now; with neither, the part is removed and the file is fetched whole (a weak ETag alone is no validator). A cut inside one call is continued. Test: `tests/test_remote.py::test_r12_l1_m25_*`. Amends the M-25 row." Why: "Look-ahead L1 after round 12, M-25. With no validator the record held only the total, so v1[:k] + v2[k:] of the same size was resumed with no hash check (TAO passes `pin=False` on purpose)."
- CHANGELOG: "`remote.download` does not resume a `.part` across calls from a server that sends no ETag or Last-Modified (look-ahead L1, M-25)."

## M-35: nothing to do
Already done by L0 (`cafe.cfd.main` writes `receipts.stamp(r)`; `python -m cafe.receipts stamp FILE` stamps a checked result; tests `test_r12_l0_m35_*`; see the L0 handback). The finding's remaining point, that the digest covers every `cafe/*.py`, was decided in L0 and is unchanged. crosscheck.json still has no writer in the repo.

## Reference-run claims (document only)
`review/round_12/q12_vs_q11.md` now says that q12 audits with no note only as first run, that after q12la it prints the `derived.zarr` note like q11 (checked on orca: `audit q12 q12la --ledgers-only`), and that the `res.pkl` sha-256 is shared by q10lb, q11 and q12 as made but not by q12la: one array, `links/usv-uas-rf/margin_db`, 343 of 78,784 samples differ, max 5.33e-4 dB (a read-only probe on orca comparing every array of the two pickles; the probe is not kept). No HANDOFF, STATUS or DECISIONS text quotes q12's audit; grepped.
- CHANGELOG: none (a review document).

## Printed numbers of the demo
None moved by these changes: only message text and the resume rule of a download. The run `q12la` was not redone.

## Verified
On orca (proot, 2 CPUs, `pm_r12m`, removed with its logs afterwards):
- Fail-first: the seven new tests were run on a detached worktree of 7c6210a with the new test files; all seven failed (rc=1, seven FAILED lines). The worktree is removed.
- Passing on the final tree (rc=0): tests/test_config, test_hycom, test_bathy, test_environment, test_orca, test_ocean, test_receipts, test_remote, test_cli, test_tao, test_conventions, test_whatif (whole files), and `tests/test_pipeline.py -k box` (the ocean_box refusals). Not run: the rest of test_pipeline (a whole-file run was stopped at 15 % after 20 min, my own session, by its exact name; it reads none of the changed messages except the `box` ones above), test_report, test_stage1 and the slow files.
- ruff check cafe/pm tests: clean. mypy cafe/pm (strict): clean.

Still wrong or not done
- A resume inside one call, on a server with no validator, is still not checked against a change in those seconds.
- Whether the real TAO server sends ETag or Last-Modified is unknown here.
