# Round 18, reviewer A

Scope done: 79 hand-made single-edit mutants (77 + 2) of round 17's fixes (DECISIONS 917 to 941) run on orca (proot, 2 CPUs, one at a time, detached copy of `08a2f23`, own directories `pm_rev18_a` and `pm_rev18_a2`), each against the round 17 test files that the row names (`tests/test_round17_*.py`, plus `tests/test_round16_a.py`, `tests/test_stage1.py`, `tests/test_credibility.py` where the row's code is covered there). The selector was run unmutated nowhere beforehand except as the driver's first line (a mutant that passes is "survived the named tests"; a mutant is "killed" only on pytest rc 1). Batch 1 (77 mutants) finished; batch 2 (21 mutants) was stopped after 2 (see its section). Then 50 DECISIONS rows no reviewer_a of rounds 13 to 17 listed, read against the code (about 25 checked by running or computing). Probes (short snippets on orca at 1 CPU): the stats domain checks, `lon_median`, `resolve_modem`, `lbm.sphere_tag`, `ledger.clean` keys, `par.env_count`, `cfd.dvec`, 19 mission variants through `config.load_mission`, a 4,000-layout differential fuzz of `fea.hull_elements_along` against PyYAML.

## Mutants: killed (by group)

- P.526 (C10 to C22, C25, C29, C31, C33, C34): the exponent and both branches of F(X), the 1.6 switch, the height gain constants and floor, X and Y constants, sea sigma and the K exponent, beta's four constants, the P.452 `m` kind of edits that are not tiny (a 2 % change of `a_em`, the `(1 - h_se/h_req)` factor, the `d1`/`d2` swap in `h_se`, hr/ht swap in the receive height gain), the sea permittivity.
- Antenna floors (Q11 to Q14, Q15, Q16, Q17): the floor value, `>=` against `>`, the USV iridium bound, the glider kind, `RF_LOW_ANTENNA_M`, `<` against `<=`, the `kind != "rf"` guard.
- UAS sortie length: U1 (`sortie_t_max` without `hard_stop_factor`), U2 (the environment series at stage1.py:239), U5 (the fine record at stage1.py:412), U6 and U7 (both `_turbulence_covers` calls).
- `atomic` (A1 to A5, A7, A8): the nine bits, the `fchmod` in `replace_from`, `O_NOFOLLOW`, the link refusal, the loop check, the mode `fchmod` of a write, the regular-file test.
- Download, mesh reader, CFD key (D2, D4 to D12, D15): the `held` branch, the 500 bound (both edits), the top-level line check, `isascii`, the 90 degree bound, the hit path returning `["result"]`, the key without the code digest, `external` in `NOT_KEYED`, `raise` statements in the key, `_plain`.
- `credibility` (J1 to J8): the mode filter, the USV station tolerance, `intersection` against `union`, the mode-only keys, the drift keys, the 5 km and 6 h defaults.
- Sensitivity (S1 to S5): each column of `SENS_ACTS`, `LINK_ACTS`, the union at a link.

## Mutants that survived the tests named for them

### A-1. The inside-the-horizon interpolation of `smooth_earth_diffraction_db` is not pinned: five constants and an edge survive
severity: minor
lane: tests
where: cafe/pm/physics/comms.py (`m = 250.0 * d_km ** 2 ...` in `smooth_earth_diffraction_db`; `h_req = 17.456 * ...`; `np.maximum(_diffraction_beyond_db(a_em, ...), 0.0)`; `d_los = np.sqrt(2.0 * a_km) * (...)`; the `hr` term of `d_los`); tests/test_round17_d.py, tests/test_round16_a.py
reproduction: on orca, `PM_HOST=cafe-orca PM_RUNTIME=proot PMX=pm_rev18_a PM_CPUS=2 bin/pmx.sh python -m pytest -q -q -x tests/test_round17_d.py tests/test_round16_a.py` passes (rc 0) with each of: (C23) `250.0` as `249.0`; (C24) `17.456` as `17.5`; (C28) the `np.maximum(..., 0.0)` around the `a_em` diffraction removed; (C30) `np.sqrt(2.0 * a_km)` as `np.sqrt(2.01 * a_km)`; (C32) the `hr` height in `d_los` multiplied by 1.01. (C26 and C27, `>` for `>=` at exact equality, are equivalent for continuous inputs and are not counted.)
why it matters: DECISIONS 928 says the P.526 chain is pinned by closed forms (1e-9 dB); the constants that give the loss inside the horizon (P.452's `m`, `h_req`, the horizon distance) are held only by the five-pair Fock tolerance of 2.8 dB, so a 0.5 to 1 % change of the radio horizon moves where the model switches branch and nothing fails. The demo's one RF link has 89 % of its needed moments beyond the horizon, so the horizon distance is the number that decides it.
wrong data: no (the shipped code is right; the figures printed are unchanged)

### A-2. Three of the five sites of the UAS sortie length are not held by a test (DECISIONS 899)
severity: minor
lane: tests
where: cafe/pm/stage1.py:321 (`tg = t0 + np.arange(0.0, uas.sortie_t_max(so) + 61.0, 30.0)`), cafe/pm/stage1.py:351 (`launch_times(..., uas.sortie_t_max(so))`), cafe/pm/physics/uas.py:657 (`t_max=sortie_t_max(so)`)
reproduction: `-x` run of `tests/test_round17_c.py tests/test_round16_a.py tests/test_stage1.py` is green with (U3) :321 as `so["duration_s"] + 61.0`, (U4) :351 as `so["duration_s"]`, (U8) :657 as `t_max=so["duration_s"]`. U1, U2 (:239), U5 (:412), U6 and U7 (the two guards) are killed.
why it matters: row 899 says `sortie_t_max` is the one place the rule is written and that "`stage1.py` uses the helper in its four places"; with :351 as the nominal duration a launch whose hard-stop flight would end after the window is still counted, and with :657 a member that cannot get home is stopped at the nominal length, and no test notices either.
wrong data: no (code as shipped is right)

### A-3. The CFD key's exempt calls and the cache's write guard: two mutants survive
severity: minor
lane: tests
where: cafe/cfd.py `_text_and_numbers` (`c.func.id in ("log", "print")`), cafe/cfd.py `cached` (`except (OSError, TypeError, ValueError)`)
reproduction: `tests/test_round17_e.py` passes with (D13) `("log", "print", "sh")`: every `sh(case, "<OpenFOAM command>", ...)` call's literal then leaves the key, so an edit of a command text (a `snappyHexMesh` option, a `postProcess` list) no longer renames the cache entry; and with (D14) `ValueError` removed from the write's `except` (a result `json` refuses with ValueError, such as a NaN with `allow_nan`, or a circular object, would then raise after hours of CFD instead of warning). The test of "an exempt call keeps the key" uses `log` and `print` only.
why it matters: DECISIONS 929 and 930 are the fixes for the one round 17 finding that gave a stale CFD table (M-4); the two guards that make them hold are not pinned against this edit.
wrong data: no (as shipped)

### A-4. Download: the re-check inside the lock and the unlocked part's cleanup are unpinned (DECISIONS 933)
severity: minor
lane: tests
where: cafe/pm/env/remote.py:274 (the second `path.exists() and ...` inside `store_lock`), :281 to :283 (`finally: part.unlink(...)`)
reproduction: `tests/test_round17_f.py` is green with (D1) the inside check replaced by `if False:` (the second caller then downloads the file the first made, over it) and with (D3) the `finally` body replaced by `pass` (an unlocked download leaves its `.<hex>.tmp` and `.id`). The tests for both name the behaviour but also pass without it, because the test file already exists before the call or the second call is not timed against the first.
why it matters: the M-9 race (two downloads of one TAO file) is the finding of round 17 that gave a raw `FileNotFoundError`; the half of the fix that stops the second download is not held.
wrong data: no

### A-5. `_low_antenna_note` looks at only one end of a link (test gap)
severity: minor
lane: tests
where: cafe/pm/report.py:738 (`for end in (lk["a"], lk["b"]):`); tests/test_round17_a.py:254 to :278
reproduction: with (Q18) the tuple as `(lk["a"],)` the two tests named in 920 still pass: the Slocum link of the test has the Slocum as end `a`. A link written `a: usv`, `b: glider_2n` would lose its sentence with the tests green.
why it matters: the card of the RF link to a 0.3 m antenna is the one place a lab user is told its margin is 5 dB too low; half of the guard is unpinned.
wrong data: no (as shipped)

### A-6. The temporary of `_replace_through` is created with the mode 0o666 or 0o600 and nothing tests which
severity: minor
lane: tests
where: cafe/atomic.py `_replace_through` (`0o666 if mode is None else 0o600`)
reproduction: `tests/test_round17_f.py` passes with the existing-file case as `0o666` (A6). The docstring says the temporary "is never readable more widely than the file it becomes"; with 0o666 it is, between the create and the `fchmod`, under the process umask only.
why it matters: a security claim of the module (round 15, security review) without a test; low impact.
wrong data: no

## Mutants of batch 2

See the end of this file for the ones that had finished.

## Findings from reading and probes

### A-7. `par.env_count` raises a bare `ValueError` for a value of 4,300 digits or more, and accepts any size
severity: minor
lane: robustness
where: cafe/pm/par.py:55 (`n = int(v) if v.isascii() and v.isdecimal() else 0`), used by cafe/cfd.py:16 (`NPROC`, at import) and `par.workers`
reproduction: on orca, `os.environ["CAFE_X"] = "9" * 5000; par.env_count("CAFE_X")` gives `ValueError: Exceeds the limit (4300 digits) for integer string conversion`, not the `ConfigError` that names the variable that DECISIONS 931 and 951 describe; `CAFE_NPROC=99999999999` and `CAFE_WORKERS=99999999999` are returned as 99999999999 (`par.workers()` too; `cfd.NPROC` then goes into `mpirun -np` and `numberOfSubdomains`).
why it matters: the round 17 fix of "bad value is a ConfigError naming it" has one more input class (and `import cafe.cfd` fails with a message that does not name the variable: the same shape as P-R16C1).
wrong data: no

### A-8. `cfd.dvec` raises `TypeError` for a label that is not a string
severity: minor
lane: robustness
where: cafe/cfd.py:24 to :27
reproduction: on orca, `cfd.dvec(None)` gives `TypeError: expected string or bytes-like object`; `cfd.dvec(["+x"])` gives `TypeError: unhashable type: 'list'` (from `d in DIRS`). DECISIONS 931 says `external` and `free_surface` refuse a bad direction with `ValueError` "before the case directory is touched".
why it matters: a directions list read from a JSON spec of the Hangar with a number or a nested list in it reaches the same call; the message names neither the label nor the rule.
wrong data: no

### A-9. `fea.hull_elements_along` returns 70 for a layout PyYAML refuses (a deeper line after a key other than `value`)
severity: minor
lane: robustness
where: cafe/fea.py:86 to :90 (`if n > indent[0]: if last == "value": raise ...; continue`)
reproduction: differential fuzz on orca (`x_rev/fuzz_hull.py`, 4,000 random layouts, seed 18): besides the tab-only line that DECISIONS 935 names as not done, the text `stage3.fea_elements_along:\n  value: 70\n  unit: x\n    deeper: 1\n` is read as 70, and `yaml.safe_load` raises a `ScannerError` on it. Row 935 and the docstring say the reader "refuses every other layout" and the file PyYAML refuses.
why it matters: `pipeline_windows` reads the same file with PyYAML; the two readers can then disagree on whether the file loads. The claim "the two agree on the shipped file" holds; the claim that the hand reader never returns what PyYAML refuses does not.
wrong data: no

### A-10. `hycom.write_store` deletes the old store before it moves the new one in, though its docstring says it writes atomically
severity: minor
lane: robustness
where: cafe/pm/env/hycom.py:236 to :237 (`shutil.rmtree(out, ignore_errors=True); os.replace(tmp, out)`), docstring at :218 ("writes atomically (tmp dir, then rename)")
reproduction: by reading: between the `rmtree` (which takes as long as the number of chunk files) and the `os.replace` the store name holds nothing or a partly deleted tree; a kill in that interval leaves no store, a run that opens the name then (Zarr reads a missing chunk as the fill value) can read NaN or zero currents without an error. DECISIONS 937 lists the umask and the mode of this call as not done, not this window. Not run (a zarr store of real size is not allowed to this review).
why it matters: the store is shared by missions (rows 911 and 941) and the ingest lock is held by the writer only; a reader that already passed the lock is not protected.
wrong data: no (needs a concurrent reader of a store that is being replaced, which the lock normally prevents)

### A-11. `intervals.wilson` and its siblings accept a non-integer or boolean count
severity: minor
lane: statistics
where: cafe/pm/stats/intervals.py (`_check`)
reproduction: on orca `intervals.wilson(1.5, 3)` returns (0.125, 0.875) and `intervals.wilson(True, 3)` returns (0.061, 0.792); DECISIONS 868 says the functions need `0 <= k <= n`, which holds, so this is only the contract's gap: a fractional `k` (a mean of flags, not a count) gives an interval as if it were a count.
why it matters: a caller passing `f.mean()` for `f.sum()` is not refused.
wrong data: no (no caller does)

### A-12. DECISIONS row 43 contradicts `config/assumptions.yaml`
severity: minor
lane: documentation
where: DECISIONS.md row 43 (last sentence), config/assumptions.yaml:115 to :116
reproduction: row 43 says "only wind speed and direction are re-fitted from TAO ... the `assumptions.yaml` text for T2 says TAO overwrites it, and the code does not"; the yaml now says the ingest stage (`pipeline._tao`) replaces the T2 sigma with the RMSE against TAO AIRT whenever the data exist, and `ingest/env_sigmas_fitted.json` is a stage output of q18. The row is stale and no later row amends it.
why it matters: a reader of DECISIONS is told the T2 text is wrong when the code does what the text says.
wrong data: no

## DECISIONS rows read (50, none listed by the reviewer_a files of rounds 13 to 17 that I could find)

43, 79, 102, 121, 138, 158, 174, 193, 210, 228, 245, 263, 280, 298, 316, 331, 348, 367, 383, 398, 416, 433, 449, 465, 482, 497, 517, 533, 557, 581, 606, 629, 654, 680, 707, 721, 742, 758, 773, 796, 817, 830, 851, 868, 886, 899, 910, 922, 933, 945.

Checked against code or by running: 43 (A-12), 102 (the `sqrt(stress_scale)` at stage1.py:224), 158 (the label in budget.py), 263 (recomputed: Beta-Binomial 0.5267 / 0.5683 / 0.2064 and Binomial 0.2545 / 0.3573 / 0.0636 for 20 of 16, 28 of 22, 100 of 80: all match the row), 316 (schema ranges and the two refusals: 19 variants through `load_mission`, all refused with the messages the row says, including altitudes that do not rise and the glider dive outside `min_dive_m` to `rating_m`), 482 (`MISSION_REQUIRED` of both models, eight USV keys), 517 (K at most 16 in `orca_gate.sh`), 557 (`pm_num` and `pm_count` patterns), 606 (`resolve_modem`: bare `whoi_micromodem` None, `Benthos_ATM960` resolves), 721 (`ledger.clean` keys: the output keeps one of two keys that collide), 773 (`sphere_tag`: `1e2`, `100.0`-style, `1_00`, `+1E4`, `0100`, full-width digits accepted, `nan`, `inf`, `0x64`, `100.5`, `1e400` refused), 796 (`_numeric` of 10**400 is infinity), 851 (`lon_median`: -180.0 for the pair, NaN for an all-NaN slice), 868 (`wilson`, `rule_of_three`, `n_certify`, `newcombe_diff`, `first_order` at n 3, 4, 5, 15 refuse; 16 returns), 886 (`hull_depth_note` exists), 899 (four sites in stage1.py, A-2), 922 (the platform antennas 0.5, 0.3, 2.2 m against the 0.5 m threshold), 933 (`copy_manifest` through `atomic.write_with`), 937 (`keep_mode` is gone from `cafe/`, `bin/`, `docs/`; `hycom.write_store` keeps its own `os.replace`, A-10). The rest were read for what they say and not traced further.

## Not run

- The Fock and parabolic-equation checks of B's lane (the reference solutions need more than one short snippet).
- Batch 2's mutants that had not finished when this file was written (see below).
- A real mutation of `tests/test_round17_b.py` against a full `make audit`; no gate, no suite.
- Nothing was run against homebase; no shared store, no emulator table, no run directory but `/data/runs/rev18_a_probe` (the mission probe wrote its yaml inside the proot's own /tmp).

## Batch 2 results

Run time was the limit (each credibility-file mutant took about 295 s): I stopped batch 2 after two of its 21 mutants, K1 (`judged = full`) and K2 (the `>= 3` for `>= 4` of level 3), both KILLED. Not run: K3 to K12 (the judged counts of the evidence line, `wide`, the L19 id, the `n` of moorings, the 95 % bound and literature clauses, `used_counts`), R1, R2 (the 'of the run' text and `hull_depth_note`) and W1 to W7 (the what-if baseline from `base_failed`, its slice, its length guard, the UAS 3-D rule, the charge). The L19 text, the judged-row counts beyond K1 and K2, and the what-if baseline are therefore unfinished, as in round 17. The tmux session `rev18a_mut2`, the directories `pm_rev18_a` and `pm_rev18_a2`, `pmdata/runs/rev18_a_probe` and the job marker were removed by exact name; the logs `rev18a_mut.log`, `rev18a_mut2.log` stay in `~/cafe-worker/logs`.

total: 12 findings (0 critical, 0 major, 12 minor)
