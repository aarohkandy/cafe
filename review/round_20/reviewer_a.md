# Round 20, reviewer A

Scope done: round 19's reviewer-A mutants re-run against the fixed tree (27 mutants, each written afresh from that file's descriptions, with Q3 as an analogue because its line is gone); 51 mutants of round 19's own fixes (the new code of `stage1.py`, `report.py`, `credibility.py`, `__main__.py`, `whatif.py`, `stats/`, `env/hycom.py`, `env/remote.py`, `pipeline.py`, `cfd.py`, `_seed.py`); a diff of every pin round 19 moved; 57 DECISIONS rows no `reviewer_a.md` of rounds 13 to 19 lists (rows 996 to 1016 read in full, 36 others from 25 to 168, 198, 247, 282, 286, 310, 313, 745, 868), about 20 of them checked against code or arithmetic; 24 hostile pairs of antenna heights through `report._low_antenna_note`; narrow numpy counts through `stats`. All on orca (proot, detached copy of `67aa547`, code of `979e37a`, own directories `pm_rev20_a` and `pm_rev20_a2`, 1 to 2 CPUs, one pytest at a time per directory; removed at the end). Nothing in the checkout was edited.

Result in one line: **4 findings, all minor, none gives wrong data to act on.** Every mutant of round 19's reviewer-A list is now killed; of the 51 mutants of round 19's own fixes, 39 are killed and 12 survive the tests I ran them against (8 of the 12 are equivalent or near-equivalent edits; 4 name a test gap, listed in A-4).

## Findings

### A-1. The link card drops the 'nearest measured pair is biased' sentence at exactly 0.55 m, the value its own start sentence says it covers
severity: minor
lane: documentation, numerics
where: cafe/pm/report.py:805 (`near[1] <= RF_NEAR_ANTENNA_M`), :732 (`RF_NEAR_ANTENNA_M = 0.05`), :778 (the trigger `h <= RF_LOW_ANTENNA_M + RF_NEAR_ANTENNA_M`)
reproduction: on orca, `report._low_antenna_note(dict(kind="rf", a="glider_eq", b="ship"), mission)` with `report._end_antenna_m` patched to give (0.549, 15.0) and (0.55, 15.0) (script `rev20_a_s3.py` in the scratch worktree; the demo mission). 0.549 m prints '... is not among those measured ..., so no error band is stated for this margin; the nearest measured pair, 0.5 m with 15 m, has a biased margin (...)'. 0.55 m prints the start 'just above 0.5 m (up to 0.55 m)' and 'not among those measured', and **no** nearest-pair sentence. Cause: `abs(0.55 - 0.5)` is 0.050000000000000044 and `_nearest_row` returns that, which is above 0.05, while the trigger (`0.5 + 0.05` is 0.55 exactly) admits it. The same at (0.3, 0.55): the nearest row (0.3, 0.5) is 0.050000000000000044 away and is not named. DECISIONS 1000 says 'within 0.05 m of a row it names the nearest measured pair as biased'.
why it matters: the card's own sentence says the bound is 0.55 m and the text changes between 0.549 and 0.55 m for no physical reason; a ship mast of 0.55 m (the mission schema's floor is 0.5 m) gets the shorter card without the bias warning. Fix: compare with a tolerance (`<= RF_NEAR_ANTENNA_M + 1e-9`) or round the difference.
wrong data: no (the card still prints, says the pair is not measured and gives no band; only the clause that names the nearest biased pair is missing at that one value)

### A-2. DECISIONS row 112 still says the emulator table's read-modify-write 'is not locked'; it has been locked since row 313
severity: minor
lane: documentation
where: DECISIONS.md:165 (row 112), DECISIONS.md:366 (row 313), cafe/pm/emulator.py:113 (`locked`), :182, cafe/pm/whatif.py:435
reproduction: `grep -n '^| 112 |' DECISIONS.md` ends 'the read-modify-write is not locked' and 'Concurrent runs can lose rows; that is acceptable for one box running one pipeline at a time', with no '(amended by ...)' tag (every row of the 30 or so I compared that a later row reversed carries one: 85 by 310, 103 by 282, 155 by 247). Row 313 (round 6, M-6): `whatif.add_rows` and `Emulator.append` hold an exclusive `fcntl.flock` on `<table>.lock` and 'concurrent runs share the table safely'. The code does so (`with locked(p)` at whatif.py:435, `with locked(self.path)` at emulator.py:182) and RUNBOOK's lock rows depend on it. The prompt's rule is that a change that reverses a row amends that row.
why it matters: a reader who takes DECISIONS 112 as current would run two pipelines against one table expecting lost rows, or tell the lab the table is unprotected.
wrong data: no

### A-3. `intervals.coverage` and `intervals.verdict` still take a narrow numpy count unchanged (round 19's M-8 fixed the five functions it names, not these)
severity: minor
lane: numerics
where: cafe/pm/stats/intervals.py:200 to :205 (`coverage`: `np.arange(n + 1)`), :164 to :184 (`verdict`: `n=n, k_fail=k_fail` stored as given)
reproduction: `python rev20_a_s1.py` on orca (`bin/pmx.sh`): `intervals.coverage(np.uint8(255), np.array([0.1, 0.5]))` gives `RuntimeWarning: overflow encountered in scalar add` and `IndexError: too many indices for array` (n + 1 wraps to 0 and `ks` is empty); the same for `np.int8(127)`; `np.uint8(100)` works. `intervals.verdict(np.uint8(3), np.uint8(100))` returns a dict with `n` and `k_fail` as `numpy.uint8`, and `json.dumps` of it raises `TypeError: Object of type uint8 is not JSON serializable`, where `wilson(np.uint8(30), np.uint8(100))` is now correct (0.2189, 0.3958) for the same arguments. `wilson`, `agresti_coull`, `newcombe_diff`, `rule_of_three`, `sprt_decide` (the five of row 1008) all return the right numbers for `uint8`, `int8`, `uint16`, `int16`, `int64`.
why it matters: row 1008 and the `_count` docstring make a numpy integer a valid count for the module; two public functions of it still wrap or leak the numpy type. No caller in `cafe/pm` passes one (`stage1.summarize` passes `int(f.sum())`), so no output is affected today.
wrong data: no

### A-4. Test gaps that round 19's own mutants expose (four survivors that name a claim in DECISIONS 996, 997, 1007 and 1000)
severity: minor
lane: tests
where: cafe/pm/stage1.py:713 to :716 (the union of every UAS end's sortie grid), cafe/pm/stage1.py:958 (`n_never_required`), cafe/_seed.py (`_vec`'s `len(v) == 3`), cafe/pm/report.py:848 (`members` and `never_required` stored together)
reproduction: mutants run on orca against `tests/test_round19_a.py` to `_f.py`, `_m.py` and `tests/test_round18_x.py` (the driver is `rev20_a_mut.py` in the scratch worktree; every mutant is a one-line edit, each unmutated run was green):
- S1e, `for u in _ends(out, a, b, "uas")[:1]:` (only the first UAS's 30 s grid enters the link's time axis, the behaviour row 996 says it replaced): **survives**, also the ten link tests of `tests/test_stage1.py` (`-k '30_s or judged_only_while or required_samples ...'`). `tests/test_round19_a.py::test_r19_m1_a_link_between_two_uas_is_required_only_while_both_fly` gives both UAS the same grid (`tf`, line 83), so the union of one equals the union of two. The effect of the mutant is at most the edge samples of an overlap whose two grids are out of phase (the AND needs both flying and the first end's grid already covers the overlap), so it is near-equivalent, but the sentence 'the sortie grids of both UAS ends are unioned' is held by no test.
- S1g, `n_never_required` counted with `need_count <= 1` for `== 0`: **survives** (also the same ten `test_stage1.py` tests). The test uses counts of 30 and 0 only; a member required at exactly one moment would be 'never required' in the mutant (row 997's definition is no moment).
- SEb, `_seed._vec` with `len(v) >= 3` (a `force`, `moment` or `viscous` of four numbers is cached under the real key): **survives**; row 1007 says 'three finite numbers each' and the refusal tests use shorter vectors.
- RPi, `never_required` kept when `n` is missing (so `members` is null beside it): survives; the summaries `summarize` writes always hold `n`, so this is equivalent for real runs.
why it matters: each is a statement a DECISIONS row makes that a revert would not fail a test for.
wrong data: no

## Round 19's reviewer-A list, re-run against the fixed tree

Selectors: each mutant ran against `tests/test_round19_a.py` to `_f.py` and `_m.py`, `tests/test_round18_a.py`, `_c.py`, `_m.py`, `_x.py`, `_f.py` and `tests/test_hycom.py` (stopping at the first failure); every one of them was run unmutated first as part of the same selector (green). K, W, FH, SM, H, N, D, A, G, I, U and PE are as in round 19's `reviewer_a.md` A-2 to A-9; I wrote each edit from that file's description, so a mutant may differ in detail from the original.

| group | mutants | result |
|---|---|---|
| `whatif` baseline-from-flags guard (A-2) | W3a, W3b, W4, W6a, W7, F10 | **all killed**, each by its own test in `tests/test_round19_c.py` (`test_a2_w3a_...` to `test_a2_f10_...`) |
| fix text (A-3) | FH6, FH8, FH9, FH10, SM9 | **all killed**, `tests/test_round19_b.py::test_a3_*` |
| credibility lines (A-4) | K4, K7b, K12a | **all killed**, `test_a4_k4_...`, `test_a4_k7b_...`, `test_a4_k12a_...` |
| `hycom.asides` (A-6) | H7 (a link with an aside's name), H9 (`{1,12}` hex) | **killed** (`test_r19_a6_h7_...` through the `is_symlink` mutant HYd, `test_r19_a6_h9_...`) |
| `par.py`, `_seed.py`, `atomic.py` (A-7) | N5, D7, A3 | **all killed**, `tests/test_round19_d.py::test_r19_a7_*` |
| hull grammar (A-8) | G11, G14, G16 (both sites) | **all killed**, `tests/test_round19_f.py::test_r19_a8_*` |
| `sprt_decide` (A-8) | I7, I8 | **killed**, `test_r19_m8_sprt_decide_checks_the_kind_before_the_range` |
| UAS turbulence length (A-9) | U10 | **killed**, `test_r19_a9_the_turbulence_series_of_a_sortie_covers_its_hard_stop_...` |
| the four the merge started and lost | PE11 | killed (`test_m2_the_names_l23_gives_the_heights_are_the_platform_files_heights`) |
| | Q3 (`round(known[0], 1)` in the pair lookup) | **no equal line in the new code**: `pair = (known[0], known[1])` and the exact-membership test are gone; the analogue in `_nearest_row`, `round(h, 1)` inside the difference (Q3x), is killed by `test_m2_a_height_just_above_0_5_m_or_off_a_row_is_not_silence_and_not_a_band` |
| | FH8, W3b | killed (above) |

## Mutants of round 19's own fixes

Killed (39): `_surfaced`'s AND as an OR (S1a), the `need=True` check dropped from `_surfaced` (S1b), `_airborne`'s AND as an OR (S1d), the `ConfigError` of `_ends` dropped (S1f), `battery_capacity_scale` removed from `TRACK_ACTS['uas']` (S1h), `wind_direction_bias` removed from `UNSEEN` (S1i), `searchsorted` side (S1k), `(i >= -1)` in `_airborne` (S1m); `RF_NEAR_ANTENNA_M` 0.05 to 0.04 (RPa), `low()` with `+ tol` (RPc, killed only by the older `tests/test_round18_x.py::test_x1_...`, not by a round 19 test), `_nearest_row` `max` as `min` (RPe), the 'read as' branch inverted (RPg), the never-required sentence printed for a count of 0 (RPh), the older-`flip.json` rule reverted (RPj), `measured` defaulting to false (RPk), the string test of `source` dropped (RPl), `_end_antenna_m`'s ship branch inverted (RPm), the 0.5 m start (RPn, again only by `test_round18_x`), `LOW_ANTENNA_ROW_TOL_M` 0.001 to 0.01 (CRa), Q3's analogue (Q3x); `ingest-ocean`'s aside line inverted (MAa), `_plan_sizes` with `n_min < n_max` (MAb) and with `isinstance` for `type is int` (MAc), `:g` against `repr` (WIa); `_count` returning `x` (IVa), `sprt_decide`'s `k < n` (IVb), `_check` not returning the ints (IVc); the `.dead.tmp` rename dropped (HYa), the dead sweep made lock-only (HYb), `leftover_note` for an existing store (HYc), `asides` accepting a link (HYd), a failing rename of the aside deleting it (HYe); the inode left out of `store_lock`'s key (RMa); `_need`'s leftover dropped (PIa) and given the wrong `lab` (PIb); `cfd._literals`' walk through a top-level `if` cut (CFa) and `async def` dropped (CFb); `_seed` writing before checking (SEa) and accepting any `dirs` key (SEc).

Survived (12), with my reading of each:
- S1c, `< FINE_S` as `<= FINE_S` in the sample-and-hold: survives the round 19 and round 18 tests and the ten link tests of `tests/test_stage1.py`. Equivalent for real sorties: the 30 s grid of a sortie runs 61 s past `uas.sortie_t_max` (`stage1.py:380`, `np.arange(0.0, uas.sortie_t_max(so) + 61.0, 30.0)`), so its last sample is a deck sample whose flag is False; the held flag at exactly 30 s after it is False either way.
- S1e, S1g, SEb, RPi: the four of A-4 (S1e near-equivalent, RPi equivalent for real runs, S1g and SEb real gaps).
- S1j, `> 0.5` as `>= 0.5` on the interpolated `surfaced` flag: equivalent on the records' own grid (the interpolant is 0 or 1 there); differs only for a moment midway between a surfaced and a submerged record. The line is unchanged from before round 19.
- S1l, an Iridium link's `when != "always"` for `== "surfacing"`: equivalent for any mission `load_mission` accepts (an Iridium link is `always` or `surfacing`).
- RPb, RPd, `>=`/`<` at exactly the 0.001 m tolerance: float-boundary edits; no test can pin an exact float distance.
- RPf, `len(known) < 2` for `!= 2`: equivalent (`known` has at most two entries).
- IVd, `rule_of_three` not using the returned int: equivalent (`3.0 / n` cannot wrap).
- RMb, the device left out of the lock key (`(0, st_ino)`): equivalent on one file system, which is all a test has; RMa (the inode left out) is killed.

## The pins that round 19 moved (DECISIONS 1016), compared with `git diff 51eb433..HEAD -- tests/<file>`

None weakened. `test_config.py` (3 to 4 bare `os.replace` in `env/hycom.py`: a count that now includes `_delete_aside`'s rename, the pin still exact); `test_round17_c.py` and `test_round18_c.py` (`battery_capacity_scale` added to the expected set, and the link probe now has to move it: stricter); `test_round18_x.py::test_x2` (renamed; it still asserts that the probe does not move `wind_direction_bias` on the profile share, and now also that `ACTING` lists it, with `UNSEEN` pinned to the new four columns); `test_stage1.py` (the assertion flips from 'not in' to 'in' for the UAS link and keeps 'not in' for the acoustic glider link); `test_round18_a.py` twice (the older-`flip.json` pair: the expected string now carries the same-members verdict and '(whole run: MARGINAL)', and the card's full sentence carries 'at Hs 0 (a calm sea)' and 'at a wave height of 1 to 3 m ... (L23)'; both are exact-string pins); `test_round17_e.py` and `test_round18_d.py` (the stand-in result gained `fluid`, `rho`, `nu`, `speed`, `moment`, `viscous` so that it passes the stricter `_seed._checked`: the test still checks what it checked); `test_round18_e.py` (the event list gained the rename to `.dead.tmp`, the aside name must still end `.old.tmp`); `test_round18_m.py` (the `_count` double returns `x`, the asserted calls are unchanged).

## Fresh sample of DECISIONS rows (57 read; none of rounds 13 to 19's `reviewer_a.md` lists them)

Rows 996 to 1016 read in full and each claim checked against code or arithmetic (996 `_ends`, `_surfaced`, `_airborne`, `summarize`; 997 `_granularity`, `_never_required_html`; 998 `TRACK_ACTS`, `UNSEEN`; 999 recomputed: 3.5 x 370 = 1295, + 414 = 1709, + 150.83e-6 x 101325 / 0.4 = 38.2 gives 1747.2 J and 1747.2 / (1.2e7 x 0.9) = 1.618e-4, and `platforms/slocum.yaml` has 1.2e7 J, 0.10, 3.5 W, 0.40; 1000 and 1001 run through `_low_antenna_note` (24 hostile pairs, see A-1); 1002, 1003 `_fix`, `_fix_html`; 1004 `_plan_sizes`, with the real q21 `plan.json` (batch 32, n_min 32, n_max 64) passing it; 1005 `_numbers`; 1006 `_literals`; 1007 `_seed`; 1008 `intervals`, `sequential`; 1010 `store_lock`, whose callers I listed (`write_store`, `pipeline._shared_store`, `surface` four times, `audit`, `remote.download`) and none nests an `emulator.locked`; 1011 to 1013 `hycom`, `pipeline._need`, `__main__`; 1014 to 1016). Every amendment tag that rows 996 to 1016 claim ('amends 247', '958', '992', '929', '960', '962', '967', '972', '953', '993', '944', '956', '991', '952', '977', '969', '964', '968') is present on the amended row; row 1009's 'extends 966' carries none and need not.

Rows 25, 27, 29, 37, 38, 47, 49, 56, 59, 62, 69, 71, 72, 76, 83, 85, 86, 88, 89, 92, 93, 97, 99, 103, 104, 107, 109, 110, 112, 114, 116, 117, 119, 122, 124, 128, 130, 132, 133, 135, 137, 140, 142, 144, 145, 146, 150, 151, 155, 159, 161, 162, 163, 164, 166, 167, 168 read; checked against code or a document: 29 (`coare.py` `A_SS = 0.091`, the `0.11 nu / u*` floor), 37 and 38 (`config/subgrid.json` gust statistics, `subgrid.rain_lens`), 49 (`glider.py:270`), 56 (the Saildrone platform's 45, 25, 1.5, 15 and 1800 s), 59 (`DT_PHYS, DT_ENV = 0.0025, 0.05`, Peukert 1.05), 72 and 868 (`SENS_MIN_N`), 85 (`BUDGET_S`, `SHARE`, `BATCH`, `N_MIN`; the SITL count amended by 310), 103 (amended by 282, `subgrid.switch` is on by default), 112 (stale: A-2), 155 and 247 (the iridium `when`), 198 (`refit_iterations_max`), 286, 310, 313, 745 (`CLASS_PRIORS` is `ACTS` turned round, `battery_capacity_scale` for the glider and the UAS). The others were read for what the sentence says and not traced to code.

## Other checks that found nothing

- `store_lock` re-entry by `(st_dev, st_ino)`: read for inode reuse (the held file's inode cannot be reissued while its descriptor is open, so a made-again lock file is a different key), for the early `return` inside the `try` (the descriptor is closed by the outer `finally`) and for thread-locality (a forked child inherits the set and the open file description together).
- `hycom.write_store`: a kill before the first rename, between the two, after the second and during the delete reasoned through; the `.dead.tmp` sweep is harmless to a concurrent writer (both ignore errors). Not run: a real kill (D's scope).
- `cfd._literals`: `defs` does not descend into a def or a class (the parent is keyed whole), does descend into `if`, `try`, `with`, `for`, `while`; module-level assignments are outside the key as the row says.
- `_seed._checked`: nothing is written when one file is refused (checked by reading and by SEa, killed); `float("nan")` and `inf` keys of `speeds` fail the case's speed list.
- DECISIONS numbering 996 to 1016 is gap-free and QUESTIONS_FOR_LAB 17a to 17j exist for every row that says so.
- q21's `report.json` and `stage1b/summary.json`: `granularity.never_required` 0 and `.members` 64 for all four links, equal to `n_never_required` and `n` of the summary.

## Not run

- A real `run_batch` of a two-glider or two-UAS link (B's lane); a real kill of `write_store` (D's); the full `docs/RUNBOOK.md` followed word for word (D's); a what-if on a real flip (C's).
- The 50 rows of the sample as 50 separate checks: 57 rows were read, about 20 of them against code.
- The survivors S1e, S1g and RPi against the whole of `tests/test_stage1.py` and `tests/test_report.py`: the file takes over 14 minutes per run, so I ran the ten link tests of it (`-k`, 8 s) and stopped the full run by the exact pid of its pytest child.

total: 4 findings (0 critical, 0 major, 4 minor)
