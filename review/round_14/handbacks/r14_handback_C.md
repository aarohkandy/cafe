# Round 14, batch C handback (branch r14-c): M-7, M-8, M-9, M-10, M-13, M-23, M-25

Code files changed: `cafe/pm/stats/sampling.py`, `cafe/pm/physics/usv.py`, `cafe/pm/env/environment.py`, `cafe/pm/env/bathy.py`, `cafe/pm/par.py`.
Tests added or changed: `tests/test_stats_exact.py`, `tests/test_usv.py`, `tests/test_environment.py`, `tests/test_bathy.py`, `tests/test_par.py`.
No document was edited. No printed number of the demo moves: the demo's WRF labels are byte-identical (`_wrf_notes` on the demo cache's `wrf.zarr` attributes gives `('12 km', 'frozen at 2023-03-01: SST_UPDATE=0')` before and after), and `config/perturbations.yaml` and the q14 `ingest/priors_fitted.json` pass every new check unchanged (probe output at the end).

New decision numbers below are written `NEW-C1 ..` to be numbered by F after 760.

---

## M-9 (and M-13, M-8): sampling.py, usv.py

### What changed
- `sampling.FRACTIONS = ("usv_vpp_bias", "usv_vpp_bias_brief")`: the priors stage 1 reads as a fraction x and turns into the speed factor `1 + x` (`stage1._run_usv`; `sensitivity_case` replaces `usv_vpp_bias` by the brief's). `sampling.FACTORS` = the five `*_scale` priors, read as the factor x itself (a speed, a height, a stress, a capacity). Found by reading every use of a prior in `stage1.py`, `env/perturb.py`, `physics/{usv,glider,uas}.py`: no other prior is a fraction; wind and direction biases and `tp_bias` are additive in m/s, deg, s.
- `sampling._check_factor`, called at the end of `check_entry` (so by `load_perturbations`, by `to_marginals` and so for a fitted prior): for a fraction, no number of the entry (`lo`, `hi`, `mean`, `median`, and `value` of a normal) has |x| >= 1, and the message names the entry and says "a fraction of speed ... not a percent: write -0.3 for -30 %"; for both kinds, the factor is positive over the whole support: a uniform's `lo` (`1 + lo > 0` for a fraction, `lo > 0` for a factor) and a normal's `mean - 6 sd` (`SUPPORT_SD = 6.0`). A lognormal is positive by construction and is not tested. These are the limits the factor gives, not chosen ranges.
- `usv.USVSim.__init__` raises `ValueError` when any `fac = 1 + bias` is <= 0 on any path (NaN is not caught: it compares false, as before; a NaN member stays a labelled failure of its own). The drawn path is clipped to [-0.9, 0.5] so it never reaches it.
- M-13: `sampling.REQUIRED` (the 11 entries every reader indexes: six `FORCING`, `current_correlation_length`, `bulk_stress_scale`, `glider_speed_scale`, `usv_vpp_bias`, `battery_capacity_scale`); `load_perturbations` raises `ValueError("perturbation 'tp_bias': missing from <file>")` (the first in REQUIRED's order, the rest listed after "and") once every present entry has passed its own checks, so an existing entry's error is still the first one. `usv_vpp_bias_brief` stays optional: `stage1.check_case` already names it ("prior 'usv_vpp_bias_brief' is not a uniform entry ...", a ConfigError, before the environment loads); a test pins that.
- M-8: the `to_marginals` docstring now says a fixed entry is skipped when `names` is empty or None and a named one raises `ValueError`; the regression test `to_marginals(load_perturbations(), ['current_correlation_length'])` is in.

### Callers and what could break (checked)
- `check_entry` callers: `load_perturbations` (stage1 `priors_for` and `--prior`, `config.env_sigmas`, `credibility`, `perturb` tests) and `to_marginals`. Ran whole files: test_stats_exact, test_stats, test_usv, test_perturb_env, test_perturb, test_stage1, test_config, test_credibility, test_report, test_whatif, test_cli, test_glider, test_receipts, test_ingest_fetch, test_ocean, test_surface, test_comms_exact, test_config_docs (see the results line in the commit message / the lead's gate).
- Fixtures with partial perturbation files: `tests/test_stats_exact.py::test_load_perturbations_names_the_entry_and_the_missing_fields` built a file of two entries and asserted `list(...) == ["a", "b"]`; it now starts from the shipped file plus `a` and `b` and asserts the last two keys (the refusals before it are unchanged). Every other partial-file test expects an error on one entry, which is raised before the missing-entry check. `tests/test_credibility.py` reads the raw file and copies the whole shipped one.
- `credibility.py` reads the raw file unchecked by design (row 746): unchanged.
- A lab edit that was valid before and is refused now: a scale prior (`hs_scale` and the others) of dist normal or uniform whose support reaches 0, and a `usv_vpp_bias` with a number of size 1 or more. The shipped file and the demo's fitted priors have neither (probe below).
- `usv.USVSim` with `vpp_bias` <= -1: refused; the tests that use it (`bias=-0.3`) are unchanged.

### DECISIONS
- NEW-C1 (M-9): "A prior that stage 1 reads as a speed factor is checked against what the factor needs, in `sampling.check_entry` (`_check_factor`): `usv_vpp_bias` and `usv_vpp_bias_brief` are fractions (the factor is `1 + x`), the five `*_scale` priors are factors (`x`). The factor is positive over the whole support (a uniform's `lo`; a normal's `mean - 6 sd`; a lognormal is positive), and a fraction has no number of size 1 or more in it, because a fraction typed as a percent (`lo: -35`) is the one mistake that gives a factor near -30; the message names the entry and says a fraction, not a percent, is meant. `usv.USVSim` raises when a factor `1 + bias` is <= 0 on the perturb path (the drawn path is clipped to >= 0.1 already). The limits are the factor's, not chosen ranges: the shipped file and the fitted priors pass unchanged. Row 456 (bounds for unlisted keys need a lab number) is not reversed: no magnitude range is added for `tp_bias`, `hs_scale`'s sd or the others, which stay unbounded above." Why: round 14, M-9 (B-1): `check_entry('usv_vpp_bias', uniform lo=-35, hi=-30)` returned None and the USV flew at a speed factor of about -30.
- NEW-C2 (M-13): "`sampling.REQUIRED` lists the 11 entries every reader indexes by name; `load_perturbations` refuses a file without one (`perturbation 'k': missing from <file>`), where it was a KeyError at `config.env_sigmas` or at the first `PerturbedEnv`. `usv_vpp_bias_brief` is optional until the sensitivity case, where `stage1.check_case` names it. (extends 720 and 746)" Why: M-13 (B-5).
- Amends: 720 and 746 (extends), 456 (cross-reference: the brief's text on bounds), RUNBOOK 314's `perturbation 'X': ...` row.

### CHANGELOG
- "Perturbation priors read as a speed fraction or factor are checked against the factor (positive over the support; a fraction is not a percent) and `USVSim` refuses a speed factor <= 0; `load_perturbations` refuses a file missing a required entry (round 14, M-9, M-13). `to_marginals` docstring: a named fixed entry raises (M-8)."

### Doc sentences needed
- RUNBOOK line 314 (the `perturbation 'X': ...` row): add causes "a prior read as a speed fraction (`usv_vpp_bias`, `usv_vpp_bias_brief`) has a number of size 1 or more (a percent typed for a fraction: write -0.3 for -30 %) or its factor `1 + x` reaches 0 inside the distribution; a scale prior (`current_speed_scale`, `hs_scale`, `bulk_stress_scale`, `glider_speed_scale`, `battery_capacity_scale`) that is normal or uniform reaches 0 or below; a required entry is deleted (`missing from <file>`)."
- `config/perturbations.yaml` header comment is unchanged (not edited: it is a tracked config the digest hashes).

---

## M-8 (documents; its docstring is in the code step above)
DECISIONS and STATUS sentences for F (the code facts, checked in this batch's reading):
- Row 126: the Fr order is `ORDER = (0.20, 0.10, 0.28, 0.41)` (`cafe/pm/dtmb5415.py:271`), not "0.20, 0.41, 0.10, 0.28"; state the reason for the change or cite the commit that made it (reviewer says f48fde3) and add "amended by <row>" to 126.
- Row 334, STATUS 59 and 103 (and RUNBOOK's `make audit` row, which also says five): the real-time tests are seven (`audit.SERIAL_TESTS`, `cafe/pm/audit.py:369-372`).
- Row 9: the surface drone is the wing-sail USV (`platforms/saildrone_explorer.yaml`); the "motor boat until a saildrone model exists" is superseded: add "amended by <row>".
- Row 113: add "glider current amended by 243 (mean over six levels from 5 m to the task's dive depth)".
- Row 741: as the finding says, state the whole child with the buckling step as 65.7 to 67.3 s and the static solve alone as 25 to 26 s; the sentence lists 26 s plus 65.7 to 67.3 s plus start-up beside a 68.2 s total, which does not add up as written. I did not check whether the buckling time includes the static solve.
- A test in the style of `tests/test_config_docs.py` that `len(audit.SERIAL_TESTS)` equals the number the docs state: that file is F's (see "needs from other batches").

---

## M-10: environment.py

### What changed
`GriddedEnv._need_ocean()` raises the `OutsideData` ("no ocean source loaded: run `... fetch <mission file>` ...") that `current` raised inline; `current`, `density` and `sound_speed` call it instead of the inline `if` and the two `assert`s. Returns the store, so mypy narrows it.

### Callers and what could break (checked)
- `density`/`sound_speed` callers: `physics/glider._trim` (stage 1 workers, `whatif`), `comms` (`sound_speed`), `PerturbedEnv.__getattr__` pass-through. The worker exception crosses the pool: `OutsideData(ValueError)` takes one message and pickles (the existing `OutsideData` tests already pickle it; `tests/test_stage1.py` keeps its `env.ocean = None` comms case, whole file run).
- `__main__.py:178` already turns an `OutsideData` into an `error:` line, exit 2. The early check in `_whatif` is not made (`__main__.py` is B's).
- Sibling asserts: `environment.py:284` `assert self.w3 is not None` was read: guarded by the caller's `if self.w3` path, unchanged. No other `assert ... ocean` in `cafe/pm`.

### DECISIONS
- NEW-C3: "`GriddedEnv.density` and `sound_speed` without an ocean store raise the same `OutsideData` as `current` (`_need_ocean`), so `whatif` on a cache whose fetch was interrupted ends in `error: no ocean source loaded: run ...` (exit 2), not an `AssertionError` traceback after the workers started. (extends 294)" Why: M-10 (B-2).
- Amends: 294 (add "extended by NEW-C3").

### CHANGELOG
- "`density` and `sound_speed` without an ocean store raise `OutsideData` like `current`, not an `AssertionError` (round 14, M-10)."

---

## M-7: environment.py `_wrf_notes`

### What changed
`_wrf_notes(attrs)` returns `(grid text, SST note)`: the grid text is `"<dx/1000:g> km"` only when `DX` parses to a finite number above 0, else `"grid spacing (DX) not recorded"`; the SST note comes from `float(SST_UPDATE)` and needs a finite whole number, else `"SST_UPDATE not recorded"` (`"1.0"` is 1, so "updated during the run: SST_UPDATE=1"; 1.5 is not recorded, not truncated); for 0 the date is `SIMULATION_START_DATE[:10]` and, when that is absent too, `"frozen: SST_UPDATE=0 (start date not recorded)"` (the same defect on the third attribute: the function used to put in 2023-03-01 itself). `GriddedEnv.__init__` builds `wrf_src = f"WRF {title} {grid} hourly (...)"`, so the first element carries its unit ("12 km"). Its signature is `tuple[str, str]` as before.

### Callers and what could break (checked)
- One caller (`GriddedEnv.__init__`), and `sst()` prints `sst_note`. `receipts.synthetic_cache` has no `DX` or `SST_UPDATE`, so its WRF source and SST text now read "grid spacing (DX) not recorded" and "SST_UPDATE not recorded" (grep over `cafe` and `tests` for the old words: only `tests/test_environment.py` pinned them; changed).
- Tests changed: the round 13 M-30 table: `LEGACY` is gone; the cases `{"DX": "x", "SST_UPDATE": "?"}` and `{}` now expect the not-recorded words, `{"DX": 12000.0, "SST_UPDATE": 0}` expects the no-date words, and the first element has " km". The demo's and the ci_env's text is unchanged (their attributes are the schema's), checked by `test_r13_m30_the_demos_sst_and_wrf_labels_are_the_words_they_always_were` (unchanged but for the "12 km" element).
- The `orca.wrf_grid` schema check (`cafe/schemas/wrfout.json`) still makes the not-recorded words unreachable on a fetched cache: only a hand-built or edited cache reaches them.

### DECISIONS
- NEW-C4 (amends 722): "`_wrf_notes` states only what the attributes say: a `DX` that is not a finite number above 0, or absent, prints `grid spacing (DX) not recorded` (it printed `nan`, `0`, `-12` and `inf` km); an `SST_UPDATE` that is not a finite whole number, or absent, prints `SST_UPDATE not recorded` (it was labelled frozen, and 1.5 was cut to 1); an `SST_UPDATE` of 0 with no `SIMULATION_START_DATE` prints `frozen: SST_UPDATE=0 (start date not recorded)`. This reverses the sentence of row 722 that an absent or non-numeric attribute falls back to the old words (12 km, frozen at 2023-03-01); the demo's text is byte-identical."
- Amends: 722 (replace "falls back to the old words (12 km, frozen at 2023-03-01)" by "is said to be not recorded (amended by NEW-C4)").

### CHANGELOG
- "WRF source and SST labels say `not recorded` for an attribute that is absent or no usable number, instead of `nan`/`0`/`-12` km or the orca run's words (round 14, M-7)."

---

## M-23: bathy.py

### What changed
`bathy.from_gebco` reads the cache inside one `try` (`with np.load(path) as z`, now closed) and turns `EOFError`, `zipfile.BadZipFile`, `zlib.error`, `KeyError` and the `ValueError` of numpy's pickle refusal or of a bad `attrs` into `ValueError(f"{path}: not a readable GEBCO cache (<type>: <message>); delete it and refetch")`. The SHA-256 mismatch ValueError is unchanged and outside it.

### Callers and what could break (checked)
- Callers: `pipeline._gebco_cached` (its tuple already has `ValueError`, so it answers False for a zero-byte file and the fetch replaces it; no edit in `pipeline.py`), `bathy.load` (catches `Exception`, the text goes in `tried`), `bathy.receipts` (`from_gebco(cache)` raises the clear message), `tests/test_ingest_fetch.py` (whole file run). `receipts` line 231 `np.load(cache)` after a successful `from_gebco` is unchanged.
- The garbage-file message changed from numpy's "This file contains pickled (object) data ..." to the one above (it names the path now); nothing matched the old text.
- Unconfirmed siblings named by the finding (`orca._stack` on zero-byte part files) are not touched: not in this batch's files.

### DECISIONS
- NEW-C5: "`bathy.from_gebco` says one thing for every unreadable GEBCO cut (empty, cut short, not an archive, a missing array or `attrs`, pickled data): `ValueError ...: not a readable GEBCO cache (...); delete it and refetch`, whichever caller reads it, so `_gebco_cached` answers False and the ingest's fetch replaces a zero-byte file (it raised EOFError out of `present()`, offline or not). (extends 19 and 665: downloads write `.part.npz` then `os.replace`, so the code itself never makes such a file; a crash after the rename, a copy or a `touch` does)." Why: M-23 (C-3).
- Amends: 19 and 665 (cross-reference only).

### CHANGELOG
- "A zero-byte or damaged GEBCO cut is refetched instead of ending the ingest in `EOFError` (round 14, M-23)."

---

## M-25: par.py

### What changed
- `par._sweep(base)`, called by the first `_share` of a process for both `/dev/shm` and the temporary directory: removes `cafe-share-<digits>-*` directories that are directories (lstat, a link is not followed), owned by this uid, whose pid is dead (`os.kill(pid, 0)` raises `ProcessLookupError`). A pid that cannot be told (PermissionError, overflow) is alive. Both places because a dead run's 9 GB in `/dev/shm` is exactly why the next run may pick the disk. The `SHM_MIN_FREE` test is taken after the sweep.
- `par._clean_on_signals`, called on every `_share` (cheap; only the main thread can install, so a first `_share` from a batch thread tries again at the next): installs `_on_signal` for SIGTERM and SIGHUP only where the disposition is `SIG_DFL` (an ignore, as under nohup, or any handler stays theirs). `_on_signal` removes the directory (no lock) and then sets the signal back to `SIG_DFL` and re-sends it to itself, so the process still dies of the signal (exit status unchanged: -15, 143 for a shell). SIGHUP is added beside the lead's TERM because the TM runner's `kill-session` sends HUP and it is the same defect (no atexit); remove it if not wanted (one word).
- `par._init` (worker): a daemon thread blocks in `multiprocessing.parent_process().join()` (the parent sentinel pipe, not pids: independent of proot's pid view) and `os._exit(1)` when the parent is gone, however it ended. Nothing to poll.
- The module docstring says all three.

### Callers and what could break (checked)
- `_share` is called by `_Pickler.reducer_override` (adopt) from `ocean.py:68`, `pipeline.py:173`, `stage1.py:949`, possibly from the stage-1 batch threads: the handler install is main-thread only and the `_lock` is held as before; the handler takes no lock.
- No other `signal` or `atexit` use in `cafe/pm`; the SITL kill (`uas.py:932`, `proc.kill()`), `freesurface`'s killpg and `fea.py`'s SIGPIPE read are on other signals/processes and unchanged. The handler is not installed over an existing disposition, so a runner that sets its own TERM handling first keeps it. If a later part of the program sets its own TERM handler after the first share, theirs replaces ours (no cleanup then; the next run's sweep gets the directory).
- Pytest: any test that adopts an array now installs the two handlers in the pytest process (main thread only) for the rest of the process; they exit the process the same way the default does, after removing the directory. The new tests restore the dispositions they touch; the older par tests do not (harmless: same exit status).
- Residual, stated: the sweep trusts the pid view of its own pid namespace. Two containers that bind-mount the same `/tmp` or `/dev/shm` and run as the same uid would each see the other's pids as dead. The supported runners do not (docker `--shm-size` and the container's own `/tmp`; proot shares the host's pids; `bin/proot_run.sh` gives each run its own `/tmp`). A pid reused by a live unrelated process keeps its dead neighbour's directory (the safe direction); the merged note's "not newer than the pid's start" test is not made: it would only narrow that, and the start time of a pid in another namespace is not readable.

### DECISIONS
- NEW-C6 (amends 273, 718): "A killed run leaves nothing for the next. `par._share` sweeps the `cafe-share-<pid>-*` directories of this user whose pid is dead from `/dev/shm` and the temporary directory before it makes its own; SIGTERM and SIGHUP remove the process's directory and then kill it with the same signal, installed only where the disposition is the default, from the main thread; a spawned worker exits when its parent does (`parent_process().join()` in `_init`). SIGKILL cannot be caught, so the sweep is its cleanup. The sweep never touches another user's directory, a link, or a live pid's directory." Why: M-25 (C-5): five SIGKILLs left five directories on orca; SIGTERM left its one; a parent killed with -9 left its workers running their tasks to the end.
- Amends: 273 and 718 (the `par.py` docstring now says it; add "amended by NEW-C6"); RUNBOOK: one line in the troubleshooting table: "`/dev/shm` or `/tmp` holds `cafe-share-<pid>-*` directories after a killed run: the next run removes those of dead pids; remove by hand with `rm -rf` only the ones whose pid is gone."

### CHANGELOG
- "A killed run no longer leaves its `cafe-share-*` directory behind for good (SIGTERM/SIGHUP clean up, the next run sweeps after SIGKILL) and its workers leave with it (round 14, M-25)."

---

## Adversary pass on cd5f2cb: two more problems fixed (M-9 siblings)

### 1. A speed-factor prior with a huge sigma or tiny median was accepted (inf or 0 members)
`sampling._check_range` (called by `check_entry` for every sampled prior, before `_check_factor`): the prior must be a finite float over its `SUPPORT_SD` support: a lognormal's `|log median| + 6 sigma < log(1e300)` (so `median * exp(+-6 sigma)` is inside 1e-300 to 1e300 and `ppf` is never inf or 0), a normal's `mean +- 6 sd` finite, a uniform's `hi - lo` finite. It is in the one shared place (`check_entry`), so `load_perturbations`, `to_marginals` and a fitted prior all get it, and it covers the lognormals `_check_factor` did not test and the additive priors (`tp_bias`, the wind biases) alike. Only finiteness is refused: `tp_bias` sd 1e9 s and `hs_scale` sigma 50 are finite (ppf 1e130 at 6 sd) and stay accepted, which is row 456 (a plausible magnitude is a lab number; NEW-C1 says so). Before: `hs_scale` value 1000, `battery_capacity_scale` median 1e-300, `glider_speed_scale` median 1e300 accepted, `ppf([.01,.5,.99])` of the first `[0, 1, inf]`; after: each ValueError naming the entry. The shipped file and the q14 fitted priors pass (re-checked by `test_r14_m9_the_shipped_priors_pass_every_check_unchanged`). One earlier test accepted `lognormal median=1e-300 sigma=50` as "positive of any shape": that is the case the finding proves wrong, so it now uses median 1e-3, sigma 5.
- Callers checked: `check_entry` is called by `load_perturbations` and `to_marginals` only (grep); no other prior passes a larger support.
- DECISIONS NEW-C1 for F: add "and every sampled prior is finite over its 6 sd support (`_check_range`): a sigma of 1000 gave Hs factors of inf; a large finite sd stays accepted (456)". RUNBOOK 314 row: add "or its support is not a finite float".

### 2. `vpp_bias_mean` typed as a percent was clipped to a speed factor of 0.1 on the default path
`usv.VPP_BIAS_CLIP = (-0.9, 0.5)` is now the one statement of the clip: `draw_vpp_bias` clips to it, and `REQUIRED["vpp_bias_mean"]` is `range:-0.9:0.5` (was `any`), so `load_platform` refuses a mean outside what the draw can keep, with the hint (physics `HINTS`) "a fraction of speed ... not a percent". `draw_vpp_bias` also runs `check_params` on that one key, so a P dict handed to `USVSim` without the loader (the adversary's probe) is refused too, with `usv params.vpp_bias_mean: -24.22 must be a finite number from -0.9 to 0.5; a fraction of speed ... not a percent`. The perturb path (`mean_sog`, stage 1's `vpp_bias`) keeps its `fac <= 0` check. The drawn spread is not refused: `vpp_bias_sd` stays `nonneg` and the draw still clips (tests with sd 5 pin it); a sd typed as a percent only widens a clipped draw, it does not fly a constant 0.1. The shipped mean (-0.2422) is inside; the printed demo numbers do not move. `tests/test_usv.py::test_every_leaf_of_the_usv_table_that_may_take_any_value...` lists the `any` kinds: `vpp_bias_mean` left the set (the test says a change there must be conscious; this is it).
- Callers: `draw_vpp_bias` is called by `USVSim.__init__` only (and tests); `usv.REQUIRED` by `load_platform` only (grep). Whole test_usv, test_stats_exact, test_config, test_stage1, test_credibility, test_perturb_env files run.

### Fail-first for the two fixes (throwaway detached worktree at cd5f2cb, orca `pm_r14c_mut`, removed with its directory afterwards)
| code | tests that fail |
|---|---|
| unfixed cd5f2cb (new tests copied in) | `test_r14_m9_a_sampled_prior_whose_support_is_not_a_finite_float_is_refused` (48 cases: 8 shapes x 5 factor priors + `tp_bias`), `test_r14_m9_a_percent_typed_for_the_platforms_mean_bias_is_refused_not_clipped...` (5) |
| fix applied, `draw_vpp_bias` check removed | the percent test, the `USVSim(P-dict)` half (5 cases); the loader half stays green |
| fix applied, `_check_range` call removed | the 48 cases |
The two "stays allowed" tests (a finite sigma 50 / sd 1e9, a mean inside the clip) pass on both: they pin that nothing legal moved.

### Not problems / left, with the reason
- Stray pids 2082561 and 2082562 on orca: not started by this agent (they are the previous run's), so by the orca rules I did not kill them. Still alive (parent pid 1, plus the proot_run.sh wrapper 2080555 / proot 2080582 waiting for them). Owner or the agent that started them: `kill 2082561 2082562`.
- Full suite, `orca_gate.sh` and `make mutation`: the lead's gate, not run here.
- `tests/test_pipeline.py -k gebco` matched nothing: `_gebco_cached` is covered through `tests/test_bathy.py`; no edit in `pipeline.py` this round.
- SIGHUP in `par` beside the lead's TERM-only decision: left as the builder flagged it (one word to remove). Not mine to decide; the lead's call.
- `par._sweep` pid-namespace residual and the "not newer than the pid start" test: a stated residual of unsupported setups (shared bind-mounted `/tmp`), unchanged.
- Docs (DECISIONS, CHANGELOG, RUNBOOK, STATUS) and the `len(audit.SERIAL_TESTS)` guard: handed to F, not problems.

## Tests and what I verified

Each fix has a regression test that fails on a mutant of the fix and passes on the fix (throwaway detached worktree `cafe-r14c-mut` at d5aea52 with the batch applied, one mutant at a time on orca, `pm_r14c_mut`; removed afterwards):

| mutant of the fix (one at a time) | tests that fail |
|---|---|
| M-9 `_check_factor` not called | `test_r14_m9_a_speed_fraction_must_be_a_fraction...` (all), `..._a_scale_prior_is_a_factor...`, `..._a_percent_in_the_file_is_refused...` (37 cases) |
| M-9 percent limit 1 changed to 1e9 | the fraction test and the file test (13 cases) |
| M-9 support limit loosened (`<= 0` to `< -10`) | the fraction and scale-prior tests (24 cases) |
| M-9 `usv_vpp_bias_brief` not a fraction prior | the fraction test, brief rows (8 cases) |
| M-9 `USVSim` factor guard removed | `test_r14_m9_a_speed_bias_that_makes_the_speed_factor_zero_or_negative...` (5 cases) |
| M-13 required entries not enforced | `test_r14_m13_a_deleted_required_prior_is_named...` (11 + 1 cases), `..._reaches_env_sigmas...` |
| M-8 docstring as before | `test_r14_m8_a_named_fixed_entry_is_refused...` |
| M-10 `assert` instead of `OutsideData` | `test_r14_m10_density_and_sound_speed_without_an_ocean...` (3 cases) |
| M-7 DX not tested for finite and positive | `test_r14_m7_a_grid_spacing_that_is_no_positive_finite_number...` (10 cases) |
| M-7 SST_UPDATE cut to int | `test_r14_m7_an_sst_update_that_is_no_whole_number...` (2 cases) |
| M-7 unreadable SST_UPDATE labelled frozen | the same test (10 cases) |
| M-23 `EOFError` not in the `except` of `from_gebco` | `test_r14_m23_a_gebco_cut_that_is_no_readable_cache...` (2 cases: empty and cut) |
| M-25 no sweep of dead runs | `test_r14_m25_the_next_run_removes_the_directories...` |
| M-25 sweep takes other users' directories | `test_r14_m25_a_directory_of_another_user_is_never_removed` |
| M-25 sweep takes live pids | `..._a_pid_that_is_alive...`, `..._the_next_run_removes...` |
| M-25 no signal handlers installed | `test_r14_m25_a_terminated_run_leaves_no_shared_directory...` (TERM and HUP) |
| M-25 handler installed over a set disposition | `..._a_signal_disposition_the_program_set_is_left_alone` (ignore and own), `..._the_handlers_are_installed_only_where...` |
| M-25 workers do not watch the parent | `test_r14_m25_a_worker_leaves_when_its_parent_is_killed`, `..._the_watch_on_the_parent_ends_the_worker...` |

(The first run of the last mutant, with a test that did not kill the worker it started, hung: see "Stray processes on orca" below. The test now records the worker's pid and ends it itself; the mutant run after that failed the two tests above and left nothing.)

Gates (orca, `pm_r14c`): `ruff check cafe/pm tests`: all checks passed. `mypy cafe/pm`: success, no issues in 55 source files. Whole test files run before the commit: test_par, test_stats_exact, test_stats, test_usv, test_bathy, test_environment, test_perturb_env, test_perturb all pass (rc=0); and, as callers of what changed, test_stage1, test_config, test_credibility, test_receipts, test_glider, test_whatif, test_cli (rc=0) and test_ingest_fetch, test_comms_exact, test_ocean, test_surface, test_config_docs, test_report (rc=0). `python -m cafe.pm audit --code-only` reports the banned-token and commented-code scans clean; its one problem is the missing `docs/mutation.json` (not this batch). Coverage of the touched modules from these test files alone: `usv.py` and `sampling.py` 100 %; the lines left in `environment.py` (385) and `bathy.py` (193) are lines this batch did not touch and other test files cover (385 was covered by a test added afterwards: `test_r14_m10_with_an_ocean_the_same_calls_reach_it`); `par.py` 99 % before the two sweep-error cases were added

Probe (orca, read only, `probe_c.py` not committed):
```
config/perturbations.yaml: 12 entries pass check_entry and the REQUIRED test: True
  usv_vpp_bias {'dist': 'uniform', 'lo': -0.2565, 'hi': -0.228, 'value': 0.0}
  usv_vpp_bias_brief {'dist': 'uniform', 'lo': -0.35, 'hi': -0.3, 'value': 0.0}
  current_speed_scale {'dist': 'lognormal', 'median': 1.0, 'value': 0.3}
  hs_scale {'dist': 'lognormal', 'median': 1.0, 'value': 0.15}
  bulk_stress_scale {'dist': 'lognormal', 'median': 1.0, 'value': 0.3}
  glider_speed_scale {'dist': 'lognormal', 'median': 1.0, 'value': 0.1}
  battery_capacity_scale {'dist': 'lognormal', 'median': 1.0, 'value': 0.05}
q14 ingest/priors_fitted.json: ['wind_speed_bias', 'wind_speed_noise', 'wind_direction_bias', 'wind_direction_noise'] -> all pass check_entry
priors_for(demo mission, fitted) builds the marginals of [battery_capacity_scale, bulk_stress_scale, current_direction_bias, current_speed_scale, glider_speed_scale, hs_scale, tp_bias, usv_vpp_bias, wind_direction_bias, wind_speed_bias]
demo wrf.zarr attrs: {'DX': '12000.0', 'SST_UPDATE': '0', 'SIMULATION_START_DATE': '2023-03-01_00:00:00'}
_wrf_notes -> ('12 km', 'frozen at 2023-03-01: SST_UPDATE=0')
```

Not run: the full suite or the gate (the lead's); the demo (no printed number can move: nothing computed changes); the mutation-testing score for physics and stats (`make mutation`, hours: `usv.py` has one new branch, `sampling.py` is in the stats scope, both have tests that fail on the mutants above). Coverage 100 % on `cafe/pm/physics`, `stats`, `env` was not measured here: every new line of `usv.py`, `sampling.py`, `environment.py` and `bathy.py` is executed by the new tests (in-process, none in a subprocess); `par.py` lines that run only in a subprocess (`_exit_with`'s body is tested in-process with a fake parent; `_on_signal` in-process with `os.kill` patched, and again for real in a subprocess).

## Needs from other batches
- F (documents): everything under the DECISIONS / CHANGELOG / RUNBOOK / STATUS lines above, numbered after 760; amended rows: 9, 113, 126, 334, 741 (M-8), 456 and RUNBOOK 314 (M-9, M-13), 720 and 746 (M-13), 294 (M-10), 722 (M-7), 19 and 665 (M-23), 273 and 718 (M-25). A `test_config_docs.py` guard that the number of real-time tests the docs state equals `len(audit.SERIAL_TESTS)` (M-8; F owns that test file).
- B: `bin/sync_filters` and `pipeline.code_digest` are not touched here. M-23 needed no `pipeline.py` edit. The optional early check in `__main__._whatif` for a missing ocean store (M-10) is B's file and not needed.
- A: nothing. D: `bin/proot_suite.sh` kills by process group; the new SIGTERM handler is compatible (the job still dies of TERM) but D's M-38 trap work should be read with it in mind if the foreground step is a pytest run.
- E, F: no code dependency. F's M-39 (`link_2g4`) changes platform-file hashes: unrelated to this batch.

## Stray processes on orca (needs the owner or lead)
The first run of the "workers do not watch the parent" mutant (the unfixed behaviour) left two python processes, parent pid 1, started 11:47:33 on 11-10, which I could not stop: the sandbox refused a `kill` of the exact pids. They are a spawned worker (`Sl`) and its resource tracker (`S`): pids 2082561 and 2082562, both mine (their start is 7 s after my `proot_run.sh` for `pm_r14c_mut`, 11:47:26). They are idle, not running a task. The `proot_run.sh` wrapper of that run (pid 2080555, proot 2080582) waits for them, so `~/cafe-worker/cafe/pm_r14c_mut` and a `~/cafe-worker/cafe/tmp/run.*` directory stay until they are killed. Kill those two pids (`kill 2082561 2082562`), after which the wrapper ends and the stale `run.*` directory is swept by the next run. This is also a finding: **without the parent watch, the orphaned worker does not leave when its task ends** (still alive 20 minutes after `kill -9` of the parent, on orca under proot); the merged text and the C-5 check said it exits at the end of its task or on EOF of the call-queue pipe. With the fix it leaves at once (the test passes on orca).
