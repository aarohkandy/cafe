# Round 12, batch E handback (M-25, M-26, M-29)

Branch `r12-e`, worktree `cafe-r12e`, from a8b8bb1. Code: `cafe/pm/env/remote.py`, `cafe/pm/env/tao.py`, `cafe/pm/env/orca.py`. Tests: `tests/test_remote.py`, `tests/test_tao.py`, `tests/test_orca.py`. No document was edited.

## M-25 and M-26 (one change in `remote.download`, `tao.fetch_tao`)

What changed:
- `remote.download(url, path, sha=None, pin=False)`. A `.part` now has a record `<name>.part.id` (JSON: total size, ETag and Last-Modified when the server sends them), written from the first probe. A `.part` is resumed only if the record equals what the server sends now; no record, an unreadable one, or any difference deletes the `.part` and starts at byte 0. The resume request carries `If-Range` (the ETag, or Last-Modified when the ETag is weak or absent); a reply that is not 206 on a resume means the file changed (or ranges are ignored) and the whole body replaces the `.part`. The record is deleted on `os.replace` and on a pinned mismatch.
- `sha` is now only the reuse check (an existing file with this hash is returned as it is). A fresh download is compared with it only with `pin=True`, which raises the old ValueError ("SHA-256 mismatch against the pinned hash, download removed"). `remote.size` is `_probe(url)[0]`, unchanged in behaviour.
- `tao.fetch_tao` calls without `pin`. If the file's new hash differs from the manifest's old one it adds `man["replaced"][key] = {old, new}` and issues a `UserWarning` ("upstream replaced it; the wind prior fitted from it can change"). The key `replaced` is absent when nothing was replaced, so ordinary manifests are byte-identical to before.

Integrity that is weaker: a fresh TAO download is checked for size only (the server states the total); the new hash is recorded, not compared. Not done: a server checksum header (none of the servers used here send one).

### DECISIONS rows (numbers after the last, 640 at review; F assigns)

Row A (M-25): "`remote.download` resumes a `.part` only when `<name>.part.id` records the same total size, ETag and Last-Modified the server sends now, and asks for the tail with `If-Range`; no record, a damaged record, another version, or a non-206 answer to the resume restarts from byte 0. Test: `tests/test_remote.py::test_r12_m25_*`." Why: "Review round 12, M-25 (C-1). A `.part` of v1 resumed after upstream became v2 gave v1[:k] + v2[k:], which `fetch_tao` hashed into the manifest and `tao.verify` then passed. A server that ignores `If-Range` is covered by the second pass (the resume reply's own identity is compared)."

Row B (M-26): "`remote.download`'s `sha` decides only whether an existing file is kept; it is checked on a fresh download only with `pin=True`. `fetch_tao` does not pin: it takes the upstream copy, records its hash, and lists the file under `manifest["replaced"]` with the old and new hash and a warning. Test: `tests/test_remote.py::test_r12_m26_*`, `tests/test_tao.py::test_r12_m26_*`." Why: "Review round 12, M-26 (C-2). The old manifest hash was passed as the expected hash, so a file missing here whose NOAA copy had been replaced (delayed-mode data are added after the fact, DECISIONS 589) failed with 'SHA-256 mismatch ... rerun' on every try; only deleting manifest.json broke the loop."

Rows amended:
- 19: "a stalled zero-byte download raises and keeps its `.part`" stays true, but the kept `.part` is reused only while its record matches the server (add "(round 12, M-25)").
- 589: add that a file whose upstream copy changed is now taken and listed under `replaced`; the wind prior can change without a code change, and the manifest says which files.
- 336 and 491 (other manifest cases) need no change; 491's advice "delete manifest.json" is no longer needed for the changed-upstream case.

### CHANGELOG lines
- "`remote.download` resumes a `.part` only when its `.part.id` record matches the server (size, ETag, Last-Modified) and sends `If-Range`; otherwise it restarts at byte 0 (review round 12, M-25)."
- "`remote.download(..., sha)` no longer refuses a fresh download that differs from `sha` (new `pin=True` does); `fetch_tao` records the new hash and lists replaced files under `replaced` (review round 12, M-26)."

### Doc sentences needed
- RUNBOOK:283 ("delete the file and run fetch, which downloads a file whose hash is not the manifest's again"): now true. Add: "if NOAA has replaced the file meanwhile, fetch takes the new copy, writes its hash into the manifest and lists it under `replaced` with a warning; the wind prior fitted from it can differ from the earlier run's." RUNBOOK:291 (the `tao_manifest.json` row): same sentence is enough.
- RUNBOOK troubleshooting: an interrupted fetch leaves `<file>.part` and `<file>.part.id` beside it; both are removed on completion, and a `.part` from before round 12 (no `.id`) is fetched again from byte 0.
- `tao.py` module/`fetch_tao` docstring already says `replaced` (done in the code).

## M-29 (`orca.assemble`)

What changed: the manifest's `parts` is built from the names `assemble` read: `wrf_<stamp>` and `umwm_<stamp>` for each hour of `ts`, and `spec_<stamp>` for each restart hour only when `pts` is not None; each is hashed from `out/hours/`, in sorted order (the same order and format as before). It no longer lists whatever `hours/*.npz` holds. The parts of other windows stay on disk (a later ingest of them reuses them).

DECISIONS row C: "The orca cache manifest's `parts` lists the per-hour parts of its own window (`wrf_`, `umwm_`, and `spec_` for each restart hour when spectra are ingested), not the files in `hours/`; its hash (derived-layer key, ledger input) no longer depends on which other windows were cached before. Test: `tests/test_orca.py::test_r12_m29_*`." Why: "Review round 12, M-29 (C-7). Window A, a shifted window B, then A again gave stores byte-identical to the first A and a manifest that listed A and B, so the derived layer (about 1 min) was rebuilt for nothing."

Rows 238, 396, 466 hold as written (the key is still sha256 of the manifest; only what the manifest lists changed). Add one clause to 238: "the manifest lists the window's parts only (round 12, M-29)".

CHANGELOG line: "The orca cache manifest lists the parts of its window, not every file in `hours/`, so its hash does not depend on cache history (review round 12, M-29)."

What an existing cache pays: its `manifest.json` is not touched until the next ingest rewrites it. Then, only if `hours/` held parts outside that window, the manifest differs, the derived-layer key changes and `surface.build` runs once (about 1 min). The code digest is in the same key, so any code edit already rebuilds it. Checked (read only) on the demo's cache on cafe-orca (`pmdata/cache/tepex_c_demo/orca`): manifest window 2023-03-01 12:00 to 2023-03-07 12:00, 145 hours; `parts` has 315 names, the window needs 315 (145 + 145 + 25) and `hours/` holds 315, none extra: the new code would write the same `parts` there, and nothing rebuilds.

Demo numbers do not move: nothing the numbers read changes. `assemble` writes the four zarr stores before the manifest and this change touches only the `parts` dict; the stores' `tree_sha256` equal those of a cold cache in the new test (A, B, A). The manifest hash is used for the derived-layer cache key and as a ledger input hash, not for any seed or value. No printed demo number is moved (before and after: identical).

## What I checked could break, and how

- `remote.download` has one caller (`tao.fetch_tao`); `size` and `cdf1_*` are unchanged in behaviour; `RemoteFile` changed in the second pass below (the whole of `tests/test_remote.py` passes). `hycom` (`out + ".part"` written with "w"), `bathy`, `ocean` and `ledger.py:106` write `.part` files fresh and never resume: not the same defect.
- Tests that encoded the old behaviour: `test_download_sha_mismatch_removes_the_part_and_the_target` now passes `pin=True` (renamed `..._pinned_...`); `test_download_resumes_a_partial_file` and `test_download_discards_an_oversized_part` wrote a `.part` by hand with no record, which is now (correctly) not resumed; they build the part by an interrupted download instead, and new tests cover the no-record case. No assertion was weakened.
- `manifest["replaced"]`: read the readers of the TAO manifest (`verify`, `load_tao`, `wind_gap`, `unusable_selected`, `pipeline._tao_cached/_tao_covers`, ledger `shared_diff`): they use `files`, `selected`, `t0`, `t1`, `box` only, so an extra key is ignored. It is absent unless a file was replaced.
- `ledger.shared_diff` and `audit._orca_problems` read `parts`: a part in a run's older manifest copy that a later window no longer lists is either unchanged (hash equal: nothing) or gone (skipped); a part that differs is a "rewrite" only when the live manifest lists it, which it does for every part a later ingest refetches (it is in that ingest's window). So no rewrite is mistaken for a change. `tests/fixtures/ci_env/make.py` writes every part of its window before `assemble`, so the fixture's manifest is unchanged. Whole files run on orca: `tests/test_remote.py`, `tests/test_tao.py`, `tests/test_orca.py` (rc 0), and `tests/test_ingest_fetch.py` with `tests/test_ledger.py` (rc 0). Coverage of `cafe/pm/env/remote.py` and `orca.py` from these files: 100 % line and branch.
- ruff (`cafe/pm tests`) and mypy strict (`cafe/pm`): clean.
- Regression tests fail on a8b8bb1 (detached worktree, removed): `test_r12_m25_a_part_of_another_version_is_restarted_not_spliced` (got v1[:1000] + v2[1000:]), `..._a_file_replaced_between_the_probe_and_the_resume_comes_back_whole`, `..._with_no_validator_a_changed_size_restarts`, `..._a_part_with_no_record_is_not_resumed`, `test_r12_m26_a_hash_of_an_earlier_copy_does_not_refuse_the_new_one` (ValueError mismatch), `tests/test_tao.py::test_r12_m26_...` (ValueError mismatch), `tests/test_orca.py::test_r12_m29_...` (manifest lists 14 parts). They pass on r12-e. The two tests that only restate kept behaviour (`test_download_resumes_a_partial_file`, the oversized part) pass on both.

## Second pass (the items the first pass left)

Probed the real servers first (read only: two one-byte ranged GETs per URL, then one with `If-Range`; headers printed, nothing stored, the probe file removed). Result, from cafe-orca on 2026-11-08:
- orca.atmos.washington.edu (WRF, UMWM) and dap.ceda.ac.uk (GEBCO): strong ETag and Last-Modified, equal across ranges; `If-Range` with the ETag or the date answers 206, with a wrong value 200 (honoured).
- dods.ndbc.noaa.gov THREDDS (TAO files): Last-Modified only, no ETag; **`If-Range` is ignored** (a wrong value still answers 206 with the tail).
- None of the four sends Content-MD5, Digest, Repr-Digest or any checksum header, so there is nothing to check: "server checksum not checked" is not a defect today.

Fixed at the one shared place (`remote._ident`, the identity of a ranged reply: total from Content-Range, ETag, Last-Modified; `_probe` is now `_ident` of a one-byte GET):
- `RemoteFile` (HDF5 block cache, used by `orca.wrf_grid`, `orca.wrf_hour`, `bathy.fetch_gebco`): records the probe's identity and every block's reply must carry the same one, else `ConnectionError: ... the file changed on the server during this session`. It does not send `If-Range`: comparing the headers of the 206 reply needs nothing from the server beyond what the four servers above send, so a server that mishandles `If-Range` cannot break the demo's ingest (the first pass's reason for leaving it). Cost: none (no extra request). Blocks already cached are not re-checked.
- `download`: the first pass relied on `If-Range` between the probe and the resume request. THREDDS ignores it, so a file replaced in that window would have been spliced (the 206 tail of the new file after the old `.part`). The resume reply's identity is now compared with the probe's; a non-206 or another identity unlinks the `.part`, probes again and restarts at byte 0. `If-Range` stays (it saves the wasted tail on servers that honour it). This corrects the first pass's sentence "a server that ignores If-Range costs bandwidth, not correctness": true for a change before the probe, not for one after it.
- The weak-ETag fallback to Last-Modified moved into `remote._if_range` and has a test (before, only strong ETags were served): `test_r12_m25_a_weak_etag_is_not_an_if_range_validator_but_last_modified_is`.

Tests (`tests/test_remote.py`; the `versioned` fixture is now `_validators(monkeypatch, honour, weak, last_modified)`, plus fixture `deaf`: a server that ignores If-Range). Failing on the first-pass code (commit 60afaf7, detached worktree, removed): `..._a_server_that_ignores_if_range_cannot_splice_a_file_replaced_after_the_probe` (got V1[:1000] + V2[1000:]), `..._remotefile_refuses_a_block_of_another_version` and `..._remotefile_with_no_validator_refuses_a_block_of_another_size` (read the second block of V2 after the first of V1 without error), the weak-ETag test (`remote._if_range` absent there; as a mutant, with the `W/` test removed from `_if_range`, it fails: `If-Range` carried `W/"..."`). They pass on r12-e. `cafe/pm/env/remote.py`: 100 % line and branch from `tests/test_remote.py` with `tests/test_tao.py`. ruff and mypy strict clean. Whole files run on orca, rc 0: `test_remote`, `test_tao`, `test_orca`, `test_bathy`, `test_ingest_fetch`, `test_ledger`.

Demo numbers do not move: the check adds no request, and on a file that does not change every reply carries the identity the probe saw.

DECISIONS row A (M-25) should add: "`RemoteFile` and the resume reply of `download` compare the identity (size, ETag, Last-Modified) of each ranged reply with the probe's; another identity is a ConnectionError (`RemoteFile`) or a restart at byte 0 (`download`)". CHANGELOG: "`RemoteFile` refuses a block from another version of the file than the one it first saw; `download` restarts when its resume reply is from another version, also on servers that ignore If-Range (review round 12, M-25)." RUNBOOK: a `ConnectionError ... changed on the server during this session` means NOAA/UW/CEDA replaced a file while it was read; run again.

## Not done, and siblings

- `cdf1_header` / `cdf1_read` (UMWM and restart NetCDF-1 reads in `orca.umwm_grid` and the hours' ingest): same trust, between the header read and the later variable reads of one file. `Header` is a plain `(dims, nrec, vars)` tuple that callers store and pass on (`orca.umwm_grid` returns it in its dict), so the identity has no place to travel in without changing that type and every consumer. Not done; a file replaced between its header and its data read would be misread by offset. Window: seconds, and hours are written once by the model run.
- A server checksum (Digest, Content-MD5): none of the four servers sends one (probed), nothing to check.
- `docs/RUNBOOK.md`, `DECISIONS.md`, `CHANGELOG.md` text above and in the first pass is for batch F.

## Needs from other batches

Nothing. `tests/conftest.py` is not touched (the ETag and If-Range server behaviour lives in a fixture inside `tests/test_remote.py`, which imports `_Handler` from `tests.conftest`); if batch A to D change `_Handler._reply` or `_serve` in `conftest.py`, that fixture wraps both and needs a look. For batch F: the three DECISIONS rows, the amendments to 19, 238 and 589, the RUNBOOK sentences and the CHANGELOG lines above.
