# Round 12, batch E handback (M-25, M-26, M-29)

Branch `r12-e`, worktree `cafe-r12e`, from a8b8bb1. Code: `cafe/pm/env/remote.py`, `cafe/pm/env/tao.py`, `cafe/pm/env/orca.py`. Tests: `tests/test_remote.py`, `tests/test_tao.py`, `tests/test_orca.py`. No document was edited.

## M-25 and M-26 (one change in `remote.download`, `tao.fetch_tao`)

What changed:
- `remote.download(url, path, sha=None, pin=False)`. A `.part` now has a record `<name>.part.id` (JSON: total size, ETag and Last-Modified when the server sends them), written from the first probe. A `.part` is resumed only if the record equals what the server sends now; no record, an unreadable one, or any difference deletes the `.part` and starts at byte 0. The resume request carries `If-Range` (the ETag, or Last-Modified when the ETag is weak or absent); a reply that is not 206 on a resume means the file changed (or ranges are ignored) and the whole body replaces the `.part`. The record is deleted on `os.replace` and on a pinned mismatch.
- `sha` is now only the reuse check (an existing file with this hash is returned as it is). A fresh download is compared with it only with `pin=True`, which raises the old ValueError ("SHA-256 mismatch against the pinned hash, download removed"). `remote.size` is `_probe(url)[0]`, unchanged in behaviour.
- `tao.fetch_tao` calls without `pin`. If the file's new hash differs from the manifest's old one it adds `man["replaced"][key] = {old, new}` and issues a `UserWarning` ("upstream replaced it; the wind prior fitted from it can change"). The key `replaced` is absent when nothing was replaced, so ordinary manifests are byte-identical to before.

Integrity that is weaker: a fresh TAO download is checked for size only (the server states the total); the new hash is recorded, not compared. Not done: a server checksum header (none of the servers used here send one).

### DECISIONS rows (numbers after the last, 640 at review; F assigns)

Row A (M-25): "`remote.download` resumes a `.part` only when `<name>.part.id` records the same total size, ETag and Last-Modified the server sends now, and asks for the tail with `If-Range`; no record, a damaged record, another version, or a non-206 answer to the resume restarts from byte 0. Test: `tests/test_remote.py::test_r12_m25_*`." Why: "Review round 12, M-25 (C-1). A `.part` of v1 resumed after upstream became v2 gave v1[:k] + v2[k:], which `fetch_tao` hashed into the manifest and `tao.verify` then passed. A server that ignores `If-Range` costs bandwidth, not correctness (the validators are compared before the request)."

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

- `remote.download` has one caller (`tao.fetch_tao`); `RemoteFile`, `size`, `cdf1_*` are unchanged in behaviour (the whole of `tests/test_remote.py` passes). `hycom` (`out + ".part"` written with "w"), `bathy`, `ocean` and `ledger.py:106` write `.part` files fresh and never resume: not the same defect.
- Tests that encoded the old behaviour: `test_download_sha_mismatch_removes_the_part_and_the_target` now passes `pin=True` (renamed `..._pinned_...`); `test_download_resumes_a_partial_file` and `test_download_discards_an_oversized_part` wrote a `.part` by hand with no record, which is now (correctly) not resumed; they build the part by an interrupted download instead, and new tests cover the no-record case. No assertion was weakened.
- `manifest["replaced"]`: read the readers of the TAO manifest (`verify`, `load_tao`, `wind_gap`, `unusable_selected`, `pipeline._tao_cached/_tao_covers`, ledger `shared_diff`): they use `files`, `selected`, `t0`, `t1`, `box` only, so an extra key is ignored. It is absent unless a file was replaced.
- `ledger.shared_diff` and `audit._orca_problems` read `parts`: a part in a run's older manifest copy that a later window no longer lists is either unchanged (hash equal: nothing) or gone (skipped); a part that differs is a "rewrite" only when the live manifest lists it, which it does for every part a later ingest refetches (it is in that ingest's window). So no rewrite is mistaken for a change. `tests/fixtures/ci_env/make.py` writes every part of its window before `assemble`, so the fixture's manifest is unchanged. Whole files run on orca: `tests/test_remote.py`, `tests/test_tao.py`, `tests/test_orca.py` (rc 0), and `tests/test_ingest_fetch.py` with `tests/test_ledger.py` (rc 0). Coverage of `cafe/pm/env/remote.py` and `orca.py` from these files: 100 % line and branch.
- ruff (`cafe/pm tests`) and mypy strict (`cafe/pm`): clean.
- Regression tests fail on a8b8bb1 (detached worktree, removed): `test_r12_m25_a_part_of_another_version_is_restarted_not_spliced` (got v1[:1000] + v2[1000:]), `..._a_file_replaced_between_the_probe_and_the_resume_comes_back_whole`, `..._with_no_validator_a_changed_size_restarts`, `..._a_part_with_no_record_is_not_resumed`, `test_r12_m26_a_hash_of_an_earlier_copy_does_not_refuse_the_new_one` (ValueError mismatch), `tests/test_tao.py::test_r12_m26_...` (ValueError mismatch), `tests/test_orca.py::test_r12_m29_...` (manifest lists 14 parts). They pass on r12-e. The two tests that only restate kept behaviour (`test_download_resumes_a_partial_file`, the oversized part) pass on both.

## Not done, and siblings

- `RemoteFile` (HDF5 hyperslab block reads): same trust inside one session; a file replaced mid-session would be spliced block by block. Sending `If-Range` with each block would turn that into a loud error, but I cannot check it against the real orca server from here (no network in the tests, and a server that mishandles `If-Range` would break the demo's ingest), so I left it. Hours are written once by the model run, so the risk is low.
- A weak ETag falling back to Last-Modified in `download` is not exercised by a test (the test server sends strong ETags only); the line is one conditional expression.
- A server checksum (Digest, Content-MD5) is not checked.
- `docs/RUNBOOK.md`, `DECISIONS.md`, `CHANGELOG.md` text above is for batch F.

## Needs from other batches

Nothing. `tests/conftest.py` is not touched (the ETag and If-Range server behaviour lives in a fixture inside `tests/test_remote.py`, which imports `_Handler` from `tests.conftest`); if batch A to D change `_Handler._reply` or `_serve` in `conftest.py`, that fixture wraps both and needs a look. For batch F: the three DECISIONS rows, the amendments to 19, 238 and 589, the RUNBOOK sentences and the CHANGELOG lines above.
