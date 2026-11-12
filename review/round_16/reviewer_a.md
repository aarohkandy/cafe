# Round 16, reviewer A

Scope done: about 100 hand-made single-edit mutants run on orca (proot, 2 CPUs, detached copy of `af880ee`, own directories `pm_rev16_a` and `pm_rev16_a2`, removed at the end) against the tests that name each fix. about 32 are mutants of this round's prefix (DECISIONS 878 to 883), about 68 of round 15's fixes (832 to 876; a second pass re-ran the batch that had been given too broad a selector). Every selector was run unmutated first (all green). 50 DECISIONS rows that rounds 12 to 15 did not list were read, about 25 of them checked against code or by running it. Probes: acoustic margins, RF margin symmetry, 10 mission variants through `load_mission`, 20 layouts through `fea.hull_elements_along` against PyYAML.

Prefix mutants: 878 (`run.sh` without its `config/` line) killed; 879 (case directory and log name unquoted) killed; 880 (`ocean` currents and waves written directly, `hangar`, `_site_data`, `write_with` without replace or without its cleanup) killed, `"xb"` as `"wb"` survived; 881 (conftest without the private `CAFE_DATA`) killed; 882 (`==` as `!=`, the seed or `_path` kept in the hash, `foreign` 0, `left_out_rows`, a row with no hash kept, `stale_rows` 0, either call site without `mission_hash`, a wrong hash in `meta`) all 10 killed; 883 (LOCK_EX as LOCK_SH, create always, OSError or ImportError uncaught, no re-entry, the default lock name, the lock off at `_derived_record`, at `_derived_current` and at `_derived_unchanged`) killed, and four sites survived (A-1).

Round 15 mutants: 832, 834 (`np.minimum` as `maximum`, one end only), 836, 837, 841 (three), 850 (three), 851, 852, 859, 860b, 861a, 864 (two), 865 (two), 866 (four), 867 (four), 868 (two), 872a, 835a and c killed. Survivors are A-5.

The reproductions are single substring edits run by a small runner that lived in the scratch copy and is not kept; each finding gives the edit and the selector.

### A-1. Four sites of round 16's store lock, and its release, are not held by any test
severity: minor
lane: robustness (tests)
where: cafe/pm/env/remote.py:239; cafe/pm/pipeline.py:184; cafe/pm/env/surface.py:134; cafe/pm/audit.py:90
reproduction: on orca, each edit with `tests/test_remote.py tests/test_pipeline.py tests/test_audit.py -k r16_pa` (and `-k "lock or derived or r16"` for the audit): (a) delete `held.discard(path)` at remote.py:239 (`pass` in its place): 4 passed. After the first block the thread's `held` still names the file, so the next `store_lock` of the same cache by that thread returns at once and takes no `flock` for the rest of the process, while a build by another process runs. (b) pipeline.py:184 `with surface.store_lock(self.cache):` as `with contextlib.nullcontext():` in `Context.env`: 3 passed. (c) surface.py:134 (the lock around the write of the store and its record in `build`) as a null context: 7 passed. (d) audit.py:90 `store_lock(f.parent, create=False)` as a null context: 10 passed. The two new pipeline tests kill the edits at pipeline.py:1030 and :1051 only.
why it matters: DECISIONS 883 lists these as places that "validate or load the layer" under the lock; (a) turns the lock off after its first use in a process, and nothing would show it.
wrong data: no

### A-2. RUNBOOK still says a different mission adds points to an emulator scope
severity: minor
lane: documentation
where: docs/RUNBOOK.md:181 (against :178 and DECISIONS 882)
reproduction: RUNBOOK:178 ends "adding points by running other missions does not help: an emulator trains only on the rows of its own mission (the hash of the mission file without its seed)". Line 181, four lines later: "a repeat of the same mission with the same seed adds no new point ..., so new points come from a different `--seed`, a different mission, or a bigger budget". `whatif.fit_class` keeps only `d["mission_hash"] == mission_hash` (whatif.py:562), so a different mission's rows are counted in `other_mission_rows` and add nothing to this mission's scope (q16: `other_mission_rows` 0 for the demo, `left_out_rows` 75 for glider_eq).
why it matters: a lab user who follows the sentence runs more missions to reach 100 points and gets an emulator that never trains.
wrong data: no

### A-3. `fea.hull_elements_along` returns a number PyYAML would not, for two layouts
severity: minor
lane: robustness
where: cafe/fea.py:73 (deeper lines skipped), :87 (`\s` matches U+00A0)
reproduction: on orca, `fea.ASSUMPTIONS` pointed at a file with `stage3.fea_elements_along:\n  value: 70\n    more\n  unit: e\n`: the hand reader returns 70, `yaml.safe_load` gives the string `'70 more'` (and the same with a continuation indented 3 spaces). With `value: 70` followed by U+00A0: the reader returns 70, PyYAML gives `'70\xa0'`. Other layouts agreed with PyYAML or were refused (plain, comment after, block scalar before, CRLF, indent 4, BOM refused, tag refused, `70%` refused, `70#c` refused, a second document refused). The docstring says "A hand reader of YAML must never return a number PyYAML would not".
why it matters: the pipeline reads the same key with PyYAML, so after such an edit the app meshes the hull with 70 elements and the pipeline gets a text; the two collapse depths of M-14 come back. Only a hand edit of `config/assumptions.yaml` does it.
wrong data: no

### A-4. Three branches of `cafe/atomic.py` that rows 872 and 880 describe are untested
severity: minor
lane: robustness (tests)
where: cafe/atomic.py:71, :49, :35
reproduction: on orca with `tests/test_round16_pb.py` (13 passed unmutated): `open(tmp, "xb")` as `"wb"` at :71: 13 passed (the O_EXCL promise of `write_with`, "ours alone", is not held). With `tests/test_round15_a.py -k temporary_is_never`: `os.fchmod(fd, mode)` as `pass` at :49: 1 passed (a rewritten file then keeps the temporary's 0o600 instead of its own mode, which row 872 states). `elif p.is_symlink():` as `elif False:` at :35 with `tests/test_round15_a.py tests/test_config.py -k "symlink or temporary"`: 8 passed (the refusal of a link at the target).
why it matters: a rewrite of a 0644 report or table by the mutant leaves it 0600 for other users of the shared box.
wrong data: no

### A-5. Six edits of round 15's fixes survive the tests that name them
severity: minor
lane: robustness (tests)
where: cafe/pm/stage1.py:277 and :166; cafe/pm/env/orca.py:252; cafe/pm/whatif.py:193 and :196; cafe/reach.py:113
reproduction: on orca: (a) stage1.py:277, drop `np.where(np.isfinite(P[0].T) & np.isfinite(P[1].T), h, 0.0)` for `h` (row 834, "an unknown position reads 0"): `tests/test_round15_a.py tests/test_stage1.py -k "r12_m11 or m3"` 18 passed. (b) orca.py:252 `(n is None or len(v) == n)` as `True` (a manifest `box` of 3 or 5 numbers passes the shape check; row 836): `-k m5` 5 passed. (c) whatif.py:196 `abs(dlon) >= width` as `>` (a move as wide as the box, row 860; the `dlat` twin is killed): `-k m29` 6 passed. (d) whatif.py:193 `0.0 < duty` as `0.0 <= duty` (duty 0 would reach `_duty_days` as a division by zero; row 861): `-k m30` 6 passed. (e) reach.py:113 `np.linspace(top, bottom, 6)` as 5 (row 870 lists "the mean over np.linspace(top, bottom, 6)" among the six mutants it kills): `tests/test_reach.py` 40 passed. (f) stage1.py:166 `first = slot - every * floor(...)` as `first = slot` (a sub-daily period would start at the first daily slot, not at t0; row 835): 61 passed over `test_round15_a.py test_stage1.py test_config.py test_whatif.py -k "m4 or launch or sortie or solar"`.
why it matters: each is a branch whose correct behaviour is stated in a DECISIONS row and held by no assertion; (e) contradicts the row that says it is pinned.
wrong data: no

total: 5 findings (0 critical, 0 major, 5 minor)

## DECISIONS rows read (50, none listed by the reviewer files of rounds 12 to 15)

3, 11, 17, 26, 31, 40, 44, 57, 63, 70, 77, 84, 91, 98, 105, 118, 129, 134, 147, 160, 169, 184, 195, 207, 214, 225, 238, 252, 265, 279, 288, 297, 310, 325, 340, 356, 371, 388, 402, 418, 430, 445, 460, 474, 489, 505, 520, 650, 700, 760.

Checked against code or by running it: 40 (alpha and beta at SA 35, CT 28, p 0: surface.py:250), 44 (QC flags D (1,2,5), R (1,2): tao.py:65), 57 (0.772 kg, 60 Wh, assumed, in the yaml), 63 (MF 4 km at 5 m/s 3.0 dB, at 10 m/s -3.94 dB; LF 6 km and HF 2 km 3.0 dB at 5 m/s), 70 (n_min 8/32/73/73, n_max 16/64/256/512, 0.10 and 0.40), 77 (Cs 0.17, U_LAT 0.04 and 0.05, JAX_MEM_FACTOR 2.5, `nu_lat_floor` an assumption), 118 and 105 (hull_fs before hull, `<part>_not_used`), 169 (`ensemble_size`), 195 (every_days 0.02 refused with the 32 min hard stop, 0.0223 accepted, NaN, inf, negative, a string and a bool refused), 225 (unknown key in `task` and `sorties` refused), 252 (the node rates integrate to the accumulation: algebra, each interval's rate appears with total weight 1), 279 and 418 (`ocv_soc` strictly increasing, `list:unit`), 297 (`CAFE_NPROC`, cap 6), 310 (`SITL` 0 for every budget), 325 (Lambda_1 = 40.6, 12.6, 42 m from deck 8 m + mean of 10, 30, 60, 100 = 58 m), 388 (CI `-u $(id -u):$(id -g)`), 430 (bind 127.0.0.1, `JSON:127.0.0.1`), 445 (the ten licences present), 460 (`ustar_percent`), 505 (`air_at_ship`), 650 (`jet_half` gone, `diurnal_jet` called by receipts only), 760 (SIGPIPE reset). Read only for what the sentence says: the rest of the list (3, 11, 17, 26, 31, 84, 91, 129, 134, 147, 160, 184, 207, 214, 238, 265, 288, 340, 356, 371, 402, 474, 489, 520, 700).

## Probes that found nothing

- RF margin `comms.rf_margin(d, a, b, h)` against `(d, b, a, h)` over 2,000 random draws (d 0.2 to 40 km, antenna heights 0.3 to 120 m, Hs 0 to 4 m): largest difference 5.7e-14 dB, so the worse-end rule's "same whichever end is named first" holds.
- q16's emulator notes: 7 of 82 glider rows used = 75 left out = 17 other code + 0 other mission + 24 other platforms + 34 of no scope; uas 7 + 13 = 20; usv 7 + 34 = 41, as `holdout.json` says. P-R16Q2 (the first note's "trained on 143") is already in `review/orca/PROBLEMS.md` and is not repeated.
- `review/round_16/evidence/nest_sphere_100_d8.json`: 157 bytes and sha-256 `97b7cb52ea78...` as row 881 states.
- `grep` for `shell=True`, `os.system`, `os.popen`, `"-c"` over `cafe/`: only `cfd.sh` (quoted now) and `geom.py` (`repr` of both paths).
- `ctx.mission` is not changed in place after `Context.__init__` (the only assignment is the seed), so the pipeline's `mission_hash` and the CLI's agree for one mission file.

## Not covered

- Rows 832 to 876 not mutated: 833, 838 to 840, 842, 843, 845 to 849, 853 to 858, 862, 863, 869, 871, 873 to 876 (documents, "no change" rows, FEA and shell-runner rows; 846 and 874 only through the A-3 probe, 875 and 876 not at all). The shell runners (`proot_run.sh`, `pmx.sh`) were not mutated.
- Mutants were run against the tests that name the fix, not the whole suite; a survivor may be killed by a test outside the selector (A-1 (d) was re-run over all of `test_audit.py` -k lock/derived only).
- No full demo, no stage-1, stage-3 or CFD computation, no acceptance, gate or GPU; `whatif` not run end to end.
- The DECISIONS rows listed as read only for what the sentence says were not traced to code.
- Concurrency of the store lock was exercised only by the tests that exist (two threads, two processes); not under 2-CPU contention with a real build.
