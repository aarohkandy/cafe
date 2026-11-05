# Round 9, reviewer D

Commit `08f05d7` (worktree `c1dd8cd`, same code). Scope: `env/` readers (hycom, ocean, orca, tao, bathy, remote), `report.py`, `credibility.py`, `receipts.py`, the round-8 tests against mutants, and the runner scripts. Reproductions ran on `cafe-burst` at 2 CPUs in the `cafe-pm` image from a detached copy; nothing in the repo was edited.

### D-1. `ingest_lab_hycom` deletes the lab's source directory when the store path is that directory
severity: major
lane: robustness / data
where: cafe/pm/env/hycom.py:187-188 (`write_store`: `shutil.rmtree(out, ignore_errors=True)`, then `os.replace(tmp, out)`), cafe/pm/env/hycom.py:723-767, cafe/pm/__main__.py:204-214 (`_ingest_ocean` passes `spec["path"]` as the output and `a.path` as the input with no comparison), cafe/pm/config.py:312
reproduction: in the `cafe-pm` image, with the test fixture (`tests/fixtures/hycom/make_fixtures.make`): `shutil.copytree(fx["layered_dir"], src)` (holds `snap_0.nc snap_1.nc snap_2.nc`), then `hycom.ingest_lab_hycom(src, fx["box"], src, "in_situ", depth=fx["depth"])`. It returns `src`; afterwards `sorted(src.iterdir())` is `['c','depth','lat','lon','rho','salinity','surf_el','time']`: the three source files are gone, replaced by the Zarr store. The same happens through the CLI when the mission says `environment.ocean: {source: lab_hycom, path: <the lab's directory>}` and `ingest-ocean --path <the same directory>` is run: the YAML key is called `path` and the schema only says "type: string".
why it matters: `hycom.unreadable` itself says deleting the lab store "would destroy the only copy"; this destroys it silently, after a "successful" ingest. `ingest_lab_hycom` / `_ingest_ocean` should refuse an output that equals or contains the input.

### D-2. `orca.assemble` keeps every hourly `.npz` open: a window of about 21 days or more ends in `OSError: Too many open files`
severity: major
lane: robustness / performance (BRIEF 5.6 "a 30-day window")
where: cafe/pm/env/orca.py:323 (`W = [np.load(...) ...]`), :333 (`W3`), :338 (`U`), :348 (`S`); the `NpzFile` handles are never closed
reproduction: `docker run cafe-pm sh -c 'ulimit -n'` on homebase prints 1024 (the soft limit inside the container; the burst VM container shows `RLIMIT_NOFILE (1024, 524288)`). In the image I wrote N hourly `wrf_*.npz` and `umwm_*.npz` parts of a 3 x 3 grid and called `orca.assemble(out, ts, wg, ug, None, [], None)`: 200 hours pass, 600 hours (25 days) fail with `OSError: [Errno 24] Too many open files: '.../hours/umwm_2023-03-18_10:00:00.npz'`. Two files per hour, so the limit is about 500 hours (21 days), fewer with spectra (one more per 6 h). `np.load` on 300 files under `ulimit -n 256` fails at the 253rd.
why it matters: RUNBOOK 4 and DECISIONS 192 say `fetch` works for the 30-day mission "that only fits a larger budget"; the hours are downloaded (hours of network), then assemble dies with a raw errno, and rerunning dies identically because every part is cached. Close each `NpzFile` (`with np.load(...) as z`) or copy the arrays out.

### D-3. `PMX=pmdata` (or `data`, `tmp`, `pm`, another agent's `pm_*`) makes `rsync --delete` empty the shared data
severity: major
lane: robustness / documentation
where: bin/pmx.sh:14 (`rsync -az --delete ... ./ "$H:$R/$D/"`), bin/pmx.sh:9 (the proot name filter only keeps `[A-Za-z0-9_-]`), docs/ORCA_RUNNER.md:5 ("so `rsync --delete` cannot reach outside")
reproduction: with fake `ssh`/`rsync` that echo their arguments on PATH: `PM_RUNTIME=proot PMX=pmdata sh bin/pmx.sh true` prints `rsync ... --delete ... ./ azureuser@...:cafe-worker/cafe/pmdata/`; `PMX=data`, `PMX=pm`, `PMX=tmp` give `.../cafe/data/`, `.../cafe/pm/`, `.../cafe/tmp/` (the last is every running job's `/tmp`). Docker mode has no filter at all (`PMX=pmdata` -> `work/cafe/pmdata/`, and `PMX='../x'`, `PMX=''`-style names are not refused either).
why it matters: `pmdata` holds the runs, the DTMB study, the GEBCO and ocean caches (18 GB that `orca_sync.sh` takes an hour to copy); the claim "cannot reach outside" is true of `~/cafe-worker` only. A reserved-name list (`pmdata data tmp pm logs`) and `pm_*`-only prefix check would close it. CLAUDE.md tells agents to pick `PMX` themselves.

### D-4. `orca_sync.sh` marks `pmdata.done` / `data.done` after a tar that failed, because the remote pipeline's status is `gzip`'s
severity: minor
lane: robustness
where: bin/orca_sync.sh:43 (`$S "cd work/cafe/$p && tar cf - $dirs | gzip -1" | $D "..."`, then `$D "touch cafe-worker/$p.done"`)
reproduction: `sh -c 'tar cf - /nonexistent | gzip -1 > /dev/null; echo $?'` prints `0`. The local `set -o pipefail` only sees the ssh status, which is the remote shell's last command (gzip). A missing directory in the list (`ocean`, `cache`, `tao`: the list is hard-coded and differs from what is on homebase when one is absent), a file that changes while read, or an I/O error on the 97 %-full disk yields a short, valid archive and exit 0. `orca_ready.sh:11` then only tests that `pmdata.done` exists.
why it matters: the worker is declared complete and the first job fails later on a missing file, with no hint that the copy was short. Use `set -o pipefail` in the remote command (`bash -c`) or check `tar`'s status. The `root` step has the same shape (`docker export | gzip -1`, line 34) but its completeness test (`usr/bin/env`, `venv/lib`) is real.

### D-5. Round-8 tests that survive a mutant of the code they cover (tao and remote)
severity: minor
lane: tests
where: cafe/pm/env/tao.py:98-107 (`_candidates`: `lo = max(before) - 10 * 86400`), cafe/pm/env/tao.py:51 and :255 (`MIN_IN_BIN = 3` as the default of `_bin(need=...)`), cafe/pm/env/remote.py:146 (`tree_sha256` hashes the relative path)
reproduction: in a copy of the tree, run `python -m pytest -x -q -q tests/test_tao.py` after each of: (a) `- 10 * 86400` -> `- 0`: **passes**, so the "A/B twin deployment within 10 days" rule has no test; (b) `HALF_BIN_S, MIN_IN_BIN = 1800.0, 3` -> `1800.0, 1`: **passes**, `tests/test_tao.py:254,260` always pass `need=` explicitly, so the "at least 3 samples" rule of `compare()`'s docstring is untested; (c) in `tests/test_remote.py`, deleting the `h.update(f.relative_to(root)...)` line in `tree_sha256`: **passes**, so two chunk files exchanging names (same bytes) hash the same, against the docstring ("relative path and bytes"). The other 23 mutants I applied (see the end) were killed.
why it matters: DECISIONS 396 builds the store audit on `tree_sha256`; the TAO window selection and the bin rule feed the wind priors and Data pedigree level 3.

### D-6. `tao._series` treats a file with no `_QC` variable as all-good
severity: minor
lane: data / robustness
where: cafe/pm/env/tao.py:175 (`... if qc_of + "_QC" in ds else np.ones(len(t))`)
reproduction: a TAO-style file with `UWND`, `VWND`, `HEIGHT` and `WSPD_QC` all 4 (bad) keeps 0 of 36 samples; the same file without the `WSPD_QC` variable keeps 36 of 36 (`tao._series(path, "WIND", "D", t0, t1)`, probed in the image).
why it matters: a renamed or dropped QC variable (a format change, a corrupt file) turns the quality filter off silently, and the result feeds the fitted wind priors. It should fail closed (raise or skip the file).

### D-7. `tao.compare` holds air temperature, humidity and SST constant outside their own record
severity: minor
lane: data / numerics
where: cafe/pm/env/tao.py:309 (`np.interp(t, m[v]["t"], m[v]["value"])`)
reproduction: wind samples every 10 min for 6 h, `airt`, `rh`, `sst` samples only at t = 0 and t = 3600 s: `tao.compare({"M": dict(t=[18000.0], wind10=[[5, 1]])}, {"M": m})` returns n = 1 with no warning; the COARE lift for the 5 h point used the 0-1 h values. `np.interp` clamps to the end values with no limit on the gap.
why it matters: the 4 m to 10 m lift (and so the bias and RMSE that set Data pedigree and the wind priors) can rest on stale stability for days when one of the three files covers less of the window (the selection per variable is the file with the most good samples, independently).

### D-8. A `gofs31` mission with `ocean.path` not ending in `.zarr` can never be fetched
severity: minor
lane: robustness
where: cafe/pm/pipeline.py:417 and :429 (`store = store_path(spec, name)`; `fetch_gofs(..., store.parent, name=store.stem)`), cafe/pm/env/hycom.py:365 (writes `<out_dir>/<name>.zarr`), cafe/pm/env/ocean.py:29-30 (`path` is honoured for any source), cafe/schemas/mission.json (`path` is a bare string, allowed with `gofs31`)
reproduction: `environment.ocean: {source: gofs31, path: /data/ocean/my_gofs}`: the pipeline checks `/data/ocean/my_gofs` (`_ocean_cached`), `fetch_ocean` writes `/data/ocean/my_gofs.zarr` (`Path("/data/ocean/my_gofs").stem` + ".zarr"), so the check fails after every fetch. `/data/ocean/gofs_run.v2.zarr` is fine; `.../x.v2` writes `x.zarr`.
why it matters: valid YAML that loads, downloads for hours and then reports the store missing. `load_mission` should require a `.zarr` suffix (or `fetch_ocean` should write exactly `store`).

### D-9. `bin/pmx.sh` reports success for a dead detached job whenever another tmux session's name contains `$TM`
severity: minor
lane: robustness
where: bin/pmx.sh:20 (`... && sleep 3 && tmux ls | grep $TM`)
reproduction: on the burst VM while `rev9a_one` and `rev9b_edge` exist, a job started with `TM=rev9` whose command dies at once leaves no session of its own, but `tmux ls | grep rev9` matches the others and the script exits 0. This is the case CLAUDE.md warns about ("tmux new-session returns 0 even when the command dies"); the grep is a substring match, and a job that finishes within 3 s also exits 1.
why it matters: concurrent agents choose short names; the check needs `grep -q "^$TM:"`.

### D-10. `bathy.from_gofs` gives the seafloor depth sigma 0 where the deepest valid level is the last (5000 m)
severity: minor
lane: honesty / data
where: cafe/pm/env/bathy.py:160 (`np.diff(z, append=z[-1])[k] / np.sqrt(12.0)`)
reproduction: `np.diff(z, append=z[-1])` is 0 for the last element, so a node whose last valid level is 5000 m reports depth 5000 m with sigma 0; the floor there is at 5000 m or deeper without bound (the docstring says "never reported below 5000 m"). The sigma for other nodes (spacing/sqrt(12)) also has zero mean offset although the floor lies in [z_k, z_k+1), i.e. the depth is biased shallow by half a spacing.
why it matters: it is the fallback path 2 of the bathymetry; a zero uncertainty is a claim the data do not back, and seafloor-contact verdicts read it.

### D-11. `orca_sync.sh` ignores an unknown part name and can swap the root filesystem under a running job
severity: minor
lane: robustness
where: bin/orca_sync.sh:20-21 (`want`/`todo`), :35 (`rm -f root.done && rm -rf root && mv root.new root`)
reproduction: `sh bin/orca_sync.sh <ip> pmdta` (typo): `PARTS=pmdta`, `want` is true for none of `proot root pmdata data`, `todo` is false for all, and it prints `== done` having copied nothing. For `root` (re-extracted when the image id changed, or named), nothing checks for a running `proot_run.sh` before `rm -rf root`, so a job started earlier loses its filesystem mid-run.
why it matters: "done" is printed for a no-op; a re-sync during a lab run corrupts it.

### D-12. `orca_setup.sh undo` logs out of Tailscale after it has killed `tailscaled`
severity: minor
lane: robustness
where: bin/orca_setup.sh:35 (`stop_ours; "$W/bin/tailscale" --socket="$W/ts/sock" logout 2>/dev/null || true; rm -rf -- "$W"`)
reproduction: `stop_ours` (line 12-16) sends TERM to `tailscaled` and sleeps 1 s; the `logout` then talks to a socket nobody serves, fails, and the failure is swallowed. The node key stays valid until the owner removes the device by hand (the next line says to do that, which is why it is minor). Running `undo` also leaves any running `proot` job of ours alone (only `sshd` and `tailscaled` are stopped) while deleting the folder under it.
why it matters: the message after `undo` says "removed" first; the order should be logout, then stop.

### D-13. `orca.assemble` overwrites the three stores before it replaces the old manifest
severity: minor
lane: robustness / reproducibility
where: cafe/pm/env/orca.py:330, :337, :345, :355 (`to_zarr(..., mode="w")`), :362 (`write_json(out / "manifest.json", ...)` last)
reproduction: a window extension re-runs `ingest`; the old `manifest.json` stays until the very end. If the process dies (or D-2 fires) after `wrf.zarr` has been rewritten and before the manifest is replaced, the old manifest still describes the old window and box, `pipeline._orca_covers` is true, and the cache is a mix of new and old stores that `fetch` will not rebuild (only the ledger's `tree_sha256` notices, at the ingest stage).
why it matters: small window, but it is exactly the half-written state the atomic manifest was meant to exclude. Delete (or mark) the manifest before the first `to_zarr`.

### D-14. `pm.sh` syncs without `--delete`, so a file removed from the tree still runs on the server
severity: minor
lane: reproducibility
where: pm.sh:13
reproduction: delete `tests/test_x.py` or `cafe/pm/old.py` locally, run `./pm.sh python -m pytest ...`: the copy under `~/work/cafe/pm` keeps the file (the header comment says why: outputs written there survive). A test of a removed module keeps passing, or a stale module stays importable; the gate then runs different code from the commit (the ledger's `git_sha` is the laptop's).
why it matters: only `pmx.sh` is exact; `./pm.sh make acceptance` is the documented lab command. Exclude the output directories and use `--delete` instead.

### D-15. The proot wrapper's stop/sweep behaviour has no automated test and ORCA_RUNNER does not say it was run
severity: minor
lane: documentation / tests
where: bin/proot_run.sh:14-25, tests/test_runners.py (60 lines: static/dry-run checks of the names and the marker only), docs/ORCA_RUNNER.md "Stopping a job"
reproduction: `tests/test_runners.py` never starts `proot_run.sh`; the rehearsal table lists the suite, the demo and interFoam, not a TERM, a `kill -9` plus sweep, or a second job starting during a first. The text states "TERM to the whole job, KILL after 10 s, as `docker stop` does" and the sweep rule as facts. (I read the logic: `stop()` and the trap order look right for dash with `setsid`; I could not exercise it on the shared VM.)
why it matters: a stuck `proot` that ignores TERM is the failure the wrapper exists for; the claim is untested.

## Mutants applied to round-8 fixes (tests run: the covering file, `-x`)
Killed (tests fail on the mutant): `_cut` bracket off, `_cut` coarse-grid branch off, ingest ordered by name, duplicate-time check off, `cached_cuts` keeps `.part.npz`, `from_gofs` sigma /12, `read_json` ValueError not caught, `hours()` ceil, `_drop_stale_parts` 3-D hours, TAO delayed-mode flags (1,2,5) -> (1,2), TAO min speed 1 -> 0, TAO RH /100, `model_day_to_epoch` epoch, `layers_to_z` bottom limit, HYCOM 2**100 mask, `destagger`, barotropic velocity off, `pang` unit, lone-record-variable packing, Range header ignored, `download` oversize `.part`, `report._singular` (`ches` and the `fraction` guard), `_old_orca_layout` off, `OCEAN_MAX_STEP_S` x100 (last four with the named round-8 tests only).
Survived: the three in D-5 (26 mutants in all, 23 killed).

total: 15 findings (0 critical, 3 major, 12 minor)
