# Round 17, reviewer D (robustness and operations)

Commit `ad7fb0d` (code as of `edac3f5`), scratch worktree on a detached HEAD, orca at 1 to 2 CPUs, every orca job written inline with `PM_HOST=cafe-orca PM_RUNTIME=proot PMX=pm_rev17_d* PM_CPUS=..`. Nothing was written outside `~/cafe-worker/cafe/pmdata/runs/rev17_d_*`, `pm_rev17_d*` and `~/cafe-worker/logs/rev17d_*`; all of it, the job markers and the worktree were removed by exact name at the end. The shared emulator table was not touched (the CI-budget runs used `CAFE_DATA=/data/runs/rev17_d_ci`).

What held (checked, no finding):
- Two concurrent `--budget ci` runs of one mission on one `CAFE_DATA` (same cache, same emulator table, different `--out`): both rc=0, `audit --ledgers-only` 0 problems on both, `stage1/summary.json`, `stage1b/summary.json`, `res.pkl`, `emulator/{design,holdout,flip}.json` byte-identical between the two, the shared table has 12 rows and no duplicates. `report.json` differs only in timings, the run name and the paths.
- Kill and resume: `tmux kill-session` (HUP) on a run after `stage1b`, then the same command again: every finished stage "up to date", the emulator and report stages rerun, rc=0, audit 0 problems, no `.tmp` or share directories left. `store_lock`: a second process waits (`wait` is called), and proceeds once the holder is `kill -9`ed.
- `atomic.write_text` / `write_with`: a directory at the target (error, no temporary), a dangling link refused, a failed or interrupted writer (`KeyboardInterrupt`) leaves the old file and no temporary, an existing 0o444 file keeps its mode, a new file under umask 077 is 0o600, hard links are broken as documented, four threads x 200 writes never produced a torn file.
- `cfd._body` refuses empty, garbage, NaN, inf, one-triangle, 1e-30 and degenerate meshes with a ValueError naming the file; `CAFE_NPROC=''` gives 6; `validate` prints the documented line.

### D-1. Two downloads of one TAO file share a fixed `.part`: the first one dies with a raw `FileNotFoundError`
severity: minor
lane: robustness
where: cafe/pm/env/remote.py:268-300 (`part = path.with_name(path.name + ".part")`, `mark`), cafe/pm/env/tao.py:177 (the only caller), cafe/pm/pipeline.py:~490-520 (`_need(... "tao" ...)` runs outside the `_shared_store` locks that round 16 added for the GEBCO cut and the ocean store)
reproduction: a local HTTP server (8 MB, ETag and Last-Modified, Range, 0.15 s per MB) and two threads calling `remote.download(url, out)` on one `out`, the second starting `d` seconds after the first. For `d` in 0.05, 0.2, 0.4, 0.9 s: B returns `ok`, A raises `FileNotFoundError: [Errno 2] ... f.bin.part` (A's `part.stat()` after B has done `os.replace(part, path)`); the file is intact (sha ok). For `d` = 1.3 s both return ok. Two ingests of one mission, or of two missions whose TAO window overlaps, hit this: `<data>/tao/s2` is shared and nothing locks it. The `.part` and its `.part.id` are one fixed name per file, which is the pattern M-24 removed for the ocean store and the GEBCO cut.
why it matters: a second ingest dies at the TAO step with an errno that names no cause; a rerun heals it. The round 16 RUNBOOK sentences about concurrent ingests describe only the GEBCO cut and the ocean store, so a lab user running two ingests is not told TAO is unprotected.
wrong data: no (a crash, the next run fetches again; the finished file's hash was right in every case tried)

### D-2. `cfd.cached` throws away a finished CFD result when the cache cannot be written, and never heals a bad cache file
severity: minor
lane: robustness
where: cafe/cfd.py:62-76 (`cached`), cafe/hangar.py:294-320 (the callers catch `Exception` and fall back to estimates)
reproduction: on orca, `cfd.CACHE = Path("/proc/nope/cfdcache")` then `cfd.cached(("ro",), stl, print, lambda: {"a": 1})`: the compute runs (`calls == ['computed']`), then `FileNotFoundError` from `CACHE.mkdir`, and the result is not returned. The same happens for a result that holds an array (`default=float` raises `TypeError: only 0-dimensional arrays can be converted`, tried with `{"arr": np.array([1., 2.])}`). `bin/pmx.sh` and `pm.sh` mount `/work` read-only (`-v ~/work/cafe/data:/work:ro`) and do not set `CAFE_WORK`, so on those runners `CACHE` is `/work/cfdcache`, read-only. The reading side: a cache file of 0 bytes, `{`, `{"recipe": "x"}` or `[]` gives `JSONDecodeError`, `KeyError: 'result'`, `TypeError` on every call, after logging "reusing an identical earlier run"; nothing recomputes or removes it.
why it matters: hours of Hangar CFD are lost to a write error that could have been logged, and a damaged cache file turns every later Hangar run for that mesh into "drag from estimates: CFD failed (...)" until someone finds the file.
wrong data: no (the Hangar appends a warning that names the exception and uses its estimates)

### D-3. RUNBOOK's `python -m cafe._seed` instruction reads a hard-coded `/work/runs`, not `$CAFE_WORK`
severity: minor
lane: documentation
where: cafe/_seed.py:6 (`pathlib.Path(f"/work/runs/{run}/{key}.{what}.json")`), docs/RUNBOOK.md (the added troubleshooting row "`CFD: reusing an identical earlier run` for a case whose solver settings you edited")
reproduction: put `quad.external.json` under `$CAFE_WORK/runs/q1/` (`CAFE_WORK=/data/runs/rev17_d_p7/work`) and run `python -m cafe._seed`: it prints `seeded quad`, `seeded torpedo`, `seeded wigley` from the worker's own `/work/runs/...` files, ignoring the one made under `$CAFE_WORK`, and writes the cache under `$CAFE_WORK/cfdcache`. The RUNBOOK's `pm()` wrapper sets `CAFE_WORK=/data/work` and does not mount `/work`, so for a lab user the three `p.exists()` tests fail and the command exits 0 with no output; the row says it "seeds old validation runs into the new names". (Reasoned from the code for the wrapper case; the first half was run.)
why it matters: the remedy the row names does nothing for a lab user, silently.
wrong data: no

### D-4. The CFD cache key leaves out every numeric constant in the bodies of `external`, `free_surface` and `characterize_*`, and the RUNBOOK says only the inline OpenFOAM texts are left out
severity: minor
lane: reproducibility
where: cafe/cfd.py:57-60 (`SETTINGS`), 252 (`iters=1500`), 263-266 (domain 4 L, base cell L/4, surface cell min(L/200, thinnest/16)), 121 (`tail_stats frac=0.2`), 378 (`refine_above=0.3`), 389-406 (levels -1, 0), `includedAngle 150` and the `loc` fractions in `external`; cafe/hangar.py:314 (the key writes `(5.0, 10.0), "3-grid"` by hand); tests/test_cfd.py:80 (asserts a function-body edit keeps the cache on purpose); docs/RUNBOOK.md round 16 row on `CFD: reusing an identical earlier run`
reproduction: `cfd.recipe()` is `sha1(json.dumps({n: globals()[n] for n in SETTINGS}))`; none of the constants above is in `SETTINGS`, so changing any of them leaves `recipe()` and so the file name unchanged and the next call logs "CFD: reusing an identical earlier run" with the result of the old mesh, iteration count or averaging window. The RUNBOOK row says the key "now also holds the solver settings of `cafe/cfd.py`" and lists the inline `fvSchemes`/`fvSolution`/`controlDict`/`transportProperties` texts as the one exception, and DECISIONS 910 and the M-23 limit say the same.
why it matters: the claim reads as "an edit of a setting recomputes", and the exceptions a person would have to know (mesh sizes, domain size, iterations, the averaging window, the third-grid threshold) are not named; the hangar's incidence key repeats two of them by hand.
wrong data: yes, only after such an edit: the Hangar's `cfd`, `cfd_aoa` and `fs` tables (drag by direction, lift at incidence, hull resistance) come back from the cache stamped as an identical earlier run although they were made with other numbers.

### D-5. `emulator.write_table` replaces the shared table without the mode or symlink rules of `cafe.atomic`
severity: minor
lane: robustness
where: cafe/pm/emulator.py:92-102 (`write_table`: `df.to_parquet(name)` then `os.replace(name, path)`), contrast cafe/atomic.py:12-50
reproduction: `write_table(df, p)` over an existing 0o664 `t.parquet` under `umask 077`: the table is 0o600 afterwards (the temporary is made by pyarrow with the process umask; `atomic._replace_through` would keep 0o664). `write_table(df, link)` where `link` is a symlink to `real.parquet`: `link` becomes a regular file and `real.parquet` keeps its old rows (`atomic` refuses a link with ELOOP, or with `follow_symlinks` replaces the target).
why it matters: `/data/emulator/train.parquet` is the table every run appends to and several people share; one run under a stricter umask makes it unreadable to the others, and a symlinked `--emulator-table` silently stops being a link. The round 16 text on "the atomic writers (mode, symlink, O_EXCL)" does not cover this writer.
wrong data: no

### D-6. `fea.hull_elements_along` has no upper bound and returns numbers for files PyYAML refuses
severity: minor
lane: robustness
where: cafe/fea.py:40-110 (the `int(m[1]) < 1` check is the only range test; the docstring says it "must never return a number PyYAML would not")
reproduction: point `fea.ASSUMPTIONS` at a file with `value: 10000000000000000000000000` (or `70000`): returns it (h = L/1e25). Mismatches against `yaml.safe_load` over 6,300 generated layouts (value spellings x preceding and following entries x indents x line ends) and 22 structural variants: the reader returns 70 where PyYAML raises for a second document (`a: 1\n---\nstage3.fea_elements_along:\n  value: 70`), for a top-level list line before the key (`- a\n...`) and for a tab after the key's colon (`stage3.fea_elements_along:   \t\n  value: 70`). The other direction (reader refuses what PyYAML accepts: BOM, duplicate `value` keys, flow mapping, tag, anchor, `value : 70`, a quoted scalar continued at column 0 above) is by design.
why it matters: a typo of two extra digits meshes the pressure hull into millions of shell elements until the stage-3 deadline kills it; and in the live app (no pyyaml) a file the rest of the code could not load still yields a mesh size.
wrong data: no

### D-7. Hostile arguments to `cafe/cfd.py` still fail late, with a raw error, or succeed with a meaningless table
severity: minor
lane: robustness
where: cafe/cfd.py:30-36 (`dvec`), 251-262 and 487-494 (`external`, `free_surface`), 62-76
reproduction (on orca, one 2 x 1 x 1 box STL): `dvec("x+z999")` returns `[0.156, 0, -0.988]` (a "+z" tilt of 999 degrees points toward -z, no error); `dvec("x+z1.2.3")` and `dvec("x+z.")` raise the bare `could not convert string to float`, not `bad direction`; `external(stl, case, dirs=())` meshes 1.2 M cells (46 s here) and returns `{'dirs': {}}`, which `cached` would store as a result; `external(..., speed=float("nan"))` meshes the same 1.2 M cells and only then fails in `simpleFoam` with a log tail; `external(..., fluid="oil")` is `KeyError: 'oil'`; `free_surface(stl, float("nan"), case, [1.0])` deletes `case` (`shutil.rmtree`, line 492) and creates its directories before trimesh raises `data must be finite`. `CAFE_NPROC=1_0` and a full-width `６` are accepted as 10 and 6 (`int()`), though the message says "whole number".
why it matters: M-26 moved the direction check before the mesh, but the other arguments are still checked after the case directory is deleted or the mesh built; only direct callers are exposed (the Hangar and the pipeline pass fixed values).
wrong data: no (a direct call with a 999 degree label returns a force table for an unintended direction, but nothing in the pipeline passes one)

### D-8. `atomic.write_text(follow_symlinks=True)` on a symlink loop replaces one link with a regular file
severity: minor
lane: robustness
where: cafe/atomic.py:34-36 (`os.path.realpath(p)` of a loop returns a name that is itself a link) and the docstring "the link stays a link"
reproduction: `a -> b`, `b -> a`; `atomic.write_text(a, "x", follow_symlinks=True)` returns with no error; afterwards `a.is_symlink()` is False and `b` is still a link to it. A dangling link followed by `follow_symlinks=True` is handled as documented (the target is created, the link stays).
why it matters: a corner of the one writer that every config and ledger write goes through, contradicting its own contract; unreachable without a person planting a loop.
wrong data: no

### D-9. RUNBOOK says the ocean-store lock protects "missions"; the store is per mission name, so only two runs of one name wait
severity: minor
lane: documentation
where: docs/RUNBOOK.md (round 16 row "`ingest: another run is fetching <what> ...`": "two missions with different boxes have different stores and do not wait"), cafe/pm/pipeline.py:441-447 (`_shared_store` docstring: "two ingests of one mission, or of two missions with one box"), cafe/pm/pipeline.py:526, config.py:553 (default store `DATA/ocean/gofs_<mission name>.zarr`, parts in `gofs_<name>.parts`)
reproduction: by reading: the GOFS store and its `.parts` directory are named from the mission's `name`, not from the box, so two differently named missions with the same box each fetch their own 5 GB and never wait for one another; only the GEBCO cut (`bathy.cache_path(sbox, ...)`, keyed by box) is shared across missions. Two missions with the same name and different boxes share one store directory (parts are then refetched "for the box they were cut to"), and the lock serialises them while each replaces the other's store.
why it matters: the sentence suggests a protection or a saving that does not exist for the ocean store, and the same-name, different-box case is not described.
wrong data: no

## Not checked
- `make ci` as the RUNBOOK's step 2 gives it: it writes `/tmp/cafe_ci_data`, which orca's rules forbid; I ran the same CI budget with `CAFE_DATA` under my own run directory instead (three full `--budget ci` runs, 1 to 2 CPUs), so the RUNBOOK's `make ci` line and its `pm()` Docker wrapper were not run word for word (no docker on orca, proot only). RUNBOOK sections 0 to 5 and the round 16 sentences were read and each checkable one run; steps 6 to 8 and most of the troubleshooting table were not followed.
- A real fetch or a killed fetch (no network use): the GOFS, GEBCO and TAO paths were read, `download()` was run against a local server only; P-R16C2 left as the owner's. The kill test was a HUP at the emulator stage, not a `kill -9` of a fetch.
- Two ingests racing on a real GEBCO or ocean store, two runs on one `--out` (no lock exists; not run), a `hull_elements_along` mesh at a large value, any real gmsh/CalculiX run, the SITL test, `whatif`.
- Overrun to disclose: the prompt allows one toy CFD test; two calls to `cfd.external` on a 2 x 1 x 1 box (the `dirs=()` and NaN-speed probes) each ran a 1.2 M cell snappy mesh (about 46 s each, `mpirun -np 6` under proot on a shared worker) before returning or failing.

total: 9 findings (0 critical, 0 major, 9 minor)
