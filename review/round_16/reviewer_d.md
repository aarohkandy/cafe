# Round 16, reviewer D

Scope: `cafe/pm/physics/comms.py`, `usv.py`, `uas.py`, `cafe/pm/env/hycom.py`, `ocean.py`, `bathy.py`, `surface.py` and `cafe/cfd.py`, read line by line at `af880ee` (code of `9328932`), hostile inputs run on orca at 2 CPUs from a detached worktree (`PM_HOST=cafe-orca PM_RUNTIME=proot PMX=pm_rev16_d PM_CPUS=2`), worktree and `pm_rev16_d` removed at the end; my files under `/data/runs/rev16_d*` were removed too.

No critical or major finding. Seven minor ones; only D-1 can hand a user a wrong number, and only after someone edits `cafe/cfd.py` on a machine whose `/work/cfdcache` is populated.

What I checked and found to hold (so the next reader does not redo it):

- Kerr cubic: over 1,996 random geometries (d to 18 km, ht 1 to 120 m, hr 1 to 30 m) the cubic residual is 1e-13 relative, R1 + R2 = d to 2e-12 m and h1/R1 = h2/R2 to 3e-13; the flat limit (`FLAT_A`) reproduces the analytic two-ray loss to 3e-6 dB; swapping the two ends changes the loss by 0.0 dB.
- Every number in the `two_ray_curved_db` / `two_ray_loss_db` docstrings and PHYSICS 12.1 that I recomputed: the Fresnel table (|G| and phase at nine grazing angles, from eps_c = 72.8 - j118.9), psi_c = 2.3 mrad, the 0.8 / 26 / 20 dB (1.0 / 29 / 34 dB at 5 cm) curved-versus-flat differences and the 2.4 / 0.3 dB with Hs, DECISIONS 244's "limit at 6.9 km (found 6.94 km), horizon 23.1 km, rf_margin(20 km) = +13.0 dB (found 13.02)", Thorp 1.187 dB/km, the Benthos MF margins (3.0, -6.8, -15.9 dB) and -3.9 dB at 10 m/s.
- `comms.receipts()` run for real on orca with Bellhop present: all pass (Bellhop against Thorp k = 2 less 3 dB: worst 0.20 dB).
- USV: PHYSICS 10.1's polar statistics reproduce (2759 cells, 658 at V = 0, 56 weak, 12 unbalanced, 2045 moving, max residual 2.07e-4; best-heading speed at 12 m/s 2.92 and 2.215 with the bias; mean SOG / U 0.1778; table gap above 0.2 m/s in 0.1 % of 2000 states).
- `layers_to_z`, `destagger`, `model_day_to_epoch`, `box360`, `_cut`/`_sub` on the fixtures, `from_gofs` on the fixture (land 0 m, shallow column 125 m = 100 m level + half the 50 m gap): correct. `config.load_mission` refuses NaN / infinite / out-of-range box values before any of them reaches `box360` (which would pass a NaN box on its own: `box360((-5,5,nan,0))` returns `(-5,5,nan,nan)`).
- WRF and UMWM time axes in the q16 cache are identical (145 hourly steps, 2023-03-01 12:00 to 03-07 12:00), and `orca.ingest` builds both from one `hours()` list, so `surface._coare_grid`'s use of the WRF hour index into the UMWM arrays (`surface.py:50-51`) holds by construction; it is an unchecked assumption (a hand-edited cache would break it), not a finding.

### D-1. `cfd.cached` keys on the mesh bytes and the call's parameters only, so a result outlives the solver settings that made it
severity: minor
lane: reproducibility
where: cafe/cfd.py:35-46 (the key), cafe/hangar.py:294, 300, 314 and cafe/_seed.py:20 (the callers)
reproduction: on orca, with `cfd.CACHE` pointed at a scratch directory: `cfd.cached(("external","water",1.5), stl, print, compute)` once; then set `cfd.FS_LTS = "maxCo 0.1;"` and change `cfd.EXT_SNAPPY` (`nCellsBetweenLevels 3` to `9`); the same call again prints "CFD: reusing an identical earlier run (1f06083850bddd63.json)" and returns the first result; `compute` ran once.
why it matters: the docstring promises "same mesh bytes + same case parameters -> same answer", but the answer also depends on the whole recipe in `cfd.py` (the snappy and solver dictionaries, `FS_DOMAIN`, `FS_H0`, `FS_LTS`, the OpenFOAM version, `CAFE_NPROC`). After any edit of those, a populated `/work/cfdcache` serves the old numbers as if they were the new recipe's, with only the line "reusing an identical earlier run" to say so. The pm pipeline's stored-result digest covers every `cafe/*.py` (DECISIONS 678-689); this cache does not.
wrong data: yes, in the cafe app's CFD answers (hangar), after a code edit with a warm cache; none in the pm demo.

### D-2. Two ingests of one mission destroy each other's ocean store and GEBCO cut: fixed temporary names, no lock
severity: minor
lane: robustness
where: cafe/pm/env/hycom.py:225-237 (`write_store`: `tmp = out.with_name(out.name + ".tmp")`, `rmtree(tmp)` first, then `rmtree(out)` and `os.replace`); cafe/pm/env/bathy.py:136-139 (`fetch_gebco`: one fixed `<cut>.part.npz`, `os.replace` at the end); nothing in `pipeline.s_ingest` (pipeline.py:440 on) takes a lock around either
reproduction: on the `tests/fixtures/hycom` store, `hycom.write_store(gen(), out, "in_situ", {})` where `gen()` yields step 0 and then, as a second run starting, calls `hycom.write_store` for the same `out` before yielding step 1. Result: the first writer dies with `ValueError: append_dim='time' does not match any existing dataset dimensions {}` (its temporary was removed under it), and `out.zarr.tmp` is left behind next to the other run's finished store. For GEBCO, two processes writing `gebco2026_<box>.npz.part.npz` at once truncate each other; the later `os.replace` then fails or promotes a file the other process is still writing, and `choose` swallows the resulting `ValueError` (SHA mismatch) and falls back to the GOFS floor with only a `tried` note.
why it matters: DECISIONS 883 made the mission cache's `derived.zarr` safe for runs at once; the other two shared stores of the same ingest step (`/data/ocean/gofs_<mission>.zarr`, `/data/bathy/gebco2026_*.npz`) are not, and two runs of one mission that both find the store missing do exactly this. The GEBCO case degrades the bathymetry silently (a 5000 m lower bound with sigma 1000 m in place of a 460 m grid), which the report names but a user may not read.
wrong data: no for the ocean store (a crash and a stale `.tmp`); possible for bathymetry (GOFS floor in place of GEBCO) under the GEBCO race, which I read from the code and did not reproduce.

### D-3. A NaN VPP speed factor passes the positivity guard and becomes a NaN-position member with no failure mode
severity: minor
lane: robustness
where: cafe/pm/physics/usv.py:527-530 (`if (self.fac <= 0).any()`), and `draw_vpp_bias` (usv.py:493-497) whose `np.clip` keeps a NaN
reproduction: `USVSim(P, 3, AnalyticEnv(wind=(-5,0), hs=1), (-165,0), 0, dict(mode="station", station=(-164.9,0)), perturb=dict(vpp_bias=np.array([0.0, np.nan, 0.0])))`, `.run(3600, 60)`: no exception; final lon is `[-164.9997, nan, -164.9997]`; `sim.fail` has no True entry and `sim.first` has no finite entry, so the NaN member is neither failed nor flagged `no_current_data`.
why it matters: DECISIONS (round 14, M-9) made the factor positive "on every path"; `NaN <= 0` is False, so a NaN gets through and the member becomes NaN-positioned. With a gridded environment the NaN position later reaches `no_current_data` by accident (a NaN lookup), with the analytic one it never does. The pipeline cannot draw a NaN today (priors are validated); a what-if or a user's `perturb` can.
wrong data: none today; a hand-made perturbation would give an unflagged NaN member.

### D-4. `cafe/cfd.py` on hostile inputs: a flat STL ends in `OverflowError` after the case directory has been deleted, an empty `CAFE_NPROC` kills the import, a mistyped direction is found after the mesh is built
severity: minor
lane: robustness
where: cafe/cfd.py:226-234 (`external`: `shutil.rmtree(case)` first, then `hs = min(L / 200, m.extents.min() / 16)` and `lvl = int(np.ceil(np.log2(h0 / hs)))`); cafe/cfd.py:15 (`NPROC = int(os.environ.get("CAFE_NPROC", "6"))`); cafe/cfd.py:288-289 (`dvec(d)` first called per direction, after `snappyHexMesh`)
reproduction: (1) `trimesh.creation.box((2, 1, 0.0)).export(p)` then `cfd.external(p, case)` -> `OverflowError: cannot convert float infinity to integer` (extents.min() is 0, so hs is 0 and log2(inf) is inf). (2) `CAFE_NPROC= python -c "import cafe.cfd"` -> `ValueError: invalid literal for int() with base 10: ''`. (3) `python -m cafe.cfd external SAMPLE WORK +x,+q` builds the whole mesh and fails in `dvec` only at the first direction's solver set-up; `dvec` is a pure label parser and could run before the first `sh()`.
why it matters: robustness only: a thin plate (a fin, a deck panel) is a plausible lab STL and gets a library traceback, not a sentence; the directions and `CAFE_NPROC` are cheap to validate before hours of meshing. I did not run OpenFOAM (not on the worker); `CAFE_NPROC=1` (serial) still runs `decomposePar -force` with one subdomain and then writes the fields into `processor*` directories, which I could not check.
wrong data: no.

### D-5. `comms` edge inputs that give a number where the input is meaningless: negative range, zero antenna heights, NaN range
severity: minor
lane: robustness
where: cafe/pm/physics/comms.py:168 (`rf_margin`: the horizon test uses the raw `d`, the loss the clamped `max(d, 1)`), comms.py:172-195 (`iridium_session`)
reproduction: `rf_margin(-3.0, 18, 10, 0.5)` returns +102.2 dB (a negative range passes `d <= horizon` and is clamped to 1 m for the loss); `rf_margin(0.0, 0.0, 0.0, 0.0)` returns +119.1 dB; `rf_margin(nan, 18, 10, 0.5)` and `rf_margin(1000, nan, 10, 0.5)` return -200.0 (`NO_LINK_DB`, the "beyond the horizon" constant) and not NaN; `iridium_session(-5, rng, 3)` succeeds with a 9 s latency, `iridium_session(nan, rng, 3)` raises `ValueError: negative dimensions are not allowed`, `members=0` raises `zero-size array to reduction operation maximum`.
why it matters: the stage-1 callers clamp the range to at least 1 m and take NaN out first (`stage1.py:640`, `need &= live & np.isfinite(d)`), so no demo number is affected; the function itself reports a missing position as a lost link and a negative one as a strong link. The UAS lost-link hook (`stage1.py:320`) does not have the NaN guard: a UAS state that went NaN would be read as "link lost".
wrong data: no.

### D-6. `usv.tables(P, cache_dir)` writes its `.npz` in place; a cut file is unreadable and nothing recovers from it
severity: minor
lane: robustness
where: cafe/pm/physics/usv.py:463-471
reproduction: write `PK\x03\x04truncated` to `usv_tables_<digest>.npz` in a directory, clear `usv._CACHE`, call `usv.tables(P, dir)` -> `zipfile.BadZipFile: File is not a zip file`. A kill or a full disk during `np.savez(f, ...)` leaves exactly such a file, and every later call with that directory raises.
why it matters: DECISIONS 880 and the neighbouring rows made the app's npz caches "written whole or not at all"; this one is the pm side's and was not touched. The pipeline never passes `cache_dir` (`USVSim` calls `tables(P)`), so no run reaches it; the parameter is documented and public.
wrong data: no (latent).

### D-7. `fly_sortie` accepts a turbulence series shorter than the longest flight it will simulate and holds the last row
severity: minor
lane: physics
where: cafe/pm/physics/uas.py:629-630 (guard: `duration_s + 60`), uas.py:642-643 (`t_max = duration_s * hard_stop_factor`, 1920 s at the yaml's 1.6), uas.py:477-478 (`turb[:, min(k, turb.shape[1] - 1)]`)
reproduction: by the lines: a series of 1,260 s (25,200 rows) passes the guard; a member that cannot get home flies until 1,920 s, and from 1,260 s on its turbulence is the last row held constant. `stage1._uas_forcing` asks for `duration_s * hard_stop_factor + 60` (1,980 s), so the pipeline is not affected.
why it matters: the message says the sortie "needs" 1,260 s, and the code can run 660 s past it; the sorties that overrun are the ones that matter for `attitude_exceedance` and `wind_exceeds_airspeed`, and frozen turbulence under-loads exactly them. Any other caller of `fly_sortie` with a `duration_s + 60` series (tests, what-if code, a stage-3 window) gets this without a word.
wrong data: no today.

total: 7 findings (0 critical, 0 major, 7 minor)
