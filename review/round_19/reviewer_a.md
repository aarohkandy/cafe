# Round 19, reviewer A

Scope done: about 330 hand-made single-edit mutants run on orca (proot, 2 CPUs, one job at a time, detached copy of `51150e7` whose code is `7260ebb`'s, own directories `pm_rev19_a` and `pm_rev19_a2`; driver `x_rev/mut_driver.py` in my scratch worktree, which applies one edit, runs `pytest -x`, restores the file; every selector run unmutated first and green, rc 0 in the log). A mutant is KILLED on pytest rc 1 and SURVIVED on rc 0.
Groups: round 18's K3 to K12 (K3, K5, K6, K7 killed; K4, K7b, K12a survive, K12b, K12c killed), R1, R2a, R2b (killed), W1 to W7, flip search F1 to F10, links-not-rerun L1 to L4, UAS shift S1 to S4, the `plan.json` budget P1 to P4, the header H1 to H3, `same_members` SM1 to SM9, the fix text FH1 to FH10, the CFD key C1 to C11, `env_count` and `dvec` N1 to N11, `_seed` D1 to D7, `replace_from` A1 to A5, the locks O1 to O13, `write_store` and `asides` H1 to H13, the hull grammar G1 to G16, the counts I1 to I9, every row of `LOW_ANTENNA_PAIR_BAND` three ways plus its key (40: all killed), `pair_effect` and `_l23_text` PE1 to PE12, `_low_antenna_note` Q1 to Q12, the five comms mutants A1a to A1e (all killed), the UAS sortie sites U3, U4, U8 to U11, A-4's D1, D3a, D3b (killed), `RANKED`, `ACTING`, `UNSEEN`, `DEMO_ONLY`, `link_acts` R1 to R20 (killed, with R12 an import error). Then 50 DECISIONS rows no reviewer_a of rounds 13 to 18 listed. Everything below is minor; none gives a user wrong data as shipped (a surviving mutant is a gap in a test, the shipped code is right unless a finding says otherwise).

Not killed means: the mutant passes every test I ran for it. Where a mutant is equivalent I say so.

## Findings

### A-1. `store_lock`'s re-entry test is by the spelling of the path, so a nested take of one lock under another spelling hangs for ever
severity: minor
lane: robustness
where: cafe/pm/env/remote.py:233 to :236 (`path = pathlib.Path(cache) / name`; `if path in held`)
reproduction: on orca, `PM_HOST=cafe-orca PM_RUNTIME=proot PMX=pm_rev19_a2 PM_CPUS=1 PM_TAKE=1 bin/pmx.sh python x_rev/probe1.py` (probe: `with store_lock(d/"sub"): with store_lock(spelled): ...` under `signal.alarm(5)`). `d/"sub"/` and `d/"sub"/.` re-enter (True, True); `d/"link"` (a symbolic link to `sub`) and `d/"sub"/".."/"sub"` block until the alarm: the second `flock` is on a new open file description of the same file, and `flock` of the same process on another description waits for the first. The re-entry set holds the unresolved `Path`.
why it matters: the docstring promises the same thread may take the lock again (the ingest decides and builds under it, and `hycom.write_store` takes `<name>.lock` inside `_shared_store`'s hold). Both callers build the path from one variable today, so no run hangs now; a `CAFE_DATA` or cache path that reaches the two sites by two spellings (a relative and an absolute one, a link) would hang a run with no message, holding the lock for every other run.
wrong data: no

### A-2. Round 18's what-if baseline-from-flags guard is not held at its edges: W3a, W3b, W4, W6a, W7, F10 survive
severity: minor
lane: tests
where: cafe/pm/whatif.py:816 (`len(flags) >= plan["batch"]`), :816 (`not uas_3d and flags is not None`), :821 (`used + cost <= share`), :823 (`elif uas_3d or run_s1`), :819 (`n=int(len(f0))`); tests/test_round18_a.py
reproduction: `PM_HOST=cafe-orca PM_RUNTIME=proot PMX=pm_rev19_a PM_CPUS=2 python x_rev/mut_driver.py mut1 W3a W3b W4 W6a W7 F10` (selector `tests/test_round18_a.py`, green unmutated, 104 s): all six pass with (W3a) `>` for `>=`, (W3b) `>= 1` for `>= plan["batch"]` (a baseline from fewer flags than the batch is then taken as the batch's), (W4) the UAS-3-D exclusion dropped (a 3-D UAS would take the 2-D-wind flags of the base run as its baseline: the case row 885 and the code comment name), (W6a) `<` for `<=` in the share test, (W7) `elif run_s1` for `elif uas_3d or run_s1` (a 3-D UAS no longer measures its baseline when no Stage-1 row is run), (F10) `n=len(flags)` for `n=len(f0)` (the printed 'on the same N members' would be the whole run's count). S1 (`>=` for `>` in the UAS shift bound) also survives; it differs only at a shift of exactly the window length, which the whole-days refusal that comes first takes for a window of whole days, so it is near-equivalent.
why it matters: row 952 states the flags rule (same members, a batch's worth, a UAS in 3-D measured) and a test per case; these edges are the ones that decide whether the baseline is of the row's members.
wrong data: no

### A-3. The fix-text edges of rows 952, 977 and 993 survive: FH6, FH8, FH9, FH10, SM9
severity: minor
lane: tests
where: cafe/pm/report.py:1456 (`sm = f.get("same_members") if b["method"] == "Stage 1" else None`), :1457 to :1458 (the `... on the whole run of N` text), :437 to :440 (the interval of the same-members P(fail)), :413 (`same["p_fail"] if same and t["method"] == "Stage 1"`), :430 (`"base_same" not in f`)
reproduction: `python x_rev/mut_driver.py mut1 FH6 FH8 FH9 FH10 SM9`, selector `tests/test_round18_a.py tests/test_round18_x.py` (green unmutated, 130 s): all pass with (FH8) the Stage-1 test removed so that an EMULATED best row reads `sm` too (the line would then say 'P(fail) 0.3 on the same 64' for a row the emulator answered, on the full ensemble), (FH6) the 'on the whole run of N' branch cut to the bare P(fail), (FH9) the Wilson interval of the same-members baseline written with `hi=same["lo"]`, (FH10) `same_as_baseline` always tested against the whole run's P(fail), (SM9) the 'older flip.json has no such key: nothing is said' guard removed.
why it matters: FH8 is the one that would print a same-members sentence beside a whole-run (emulated) answer, the confusion round 18's M-1 closed; no test sets an EMULATED best row beside a `same_members` entry.
wrong data: no (as shipped); a mutant of this kind would

### A-4. The credibility evidence line's counts and the `used_counts` rule: K4, K7b, K12a survive
severity: minor
lane: tests
where: cafe/pm/credibility.py:910 (`sum(bool(r['validated']) for r in judged)`), :914 (`and not wide`), :381 (`if i["kind"] != "fitted"`)
reproduction: `python x_rev/mut_driver.py mut4 K4w K7bw K12aw` (selector: the seven credibility tests that name the lines, `tests/test_round17_b.py` and `tests/test_round18_m.py`; 80 s, green unmutated). K4 (the count of `|E| <= U_val` over `full` for `judged`), K7b (the `not wide` clause of the level-3 rule dropped) and K12a (`kind != "fitted"` as `True`, so a value fitted from data counts as used or not used) pass. K3, K5, K6, K7, K8, K9, K10, K11, K12b, K12c are killed. The same K4, K7b, K12a pass the narrow selector too; I did not find a test in `tests/test_credibility.py`, `test_round17_b.py` or `test_round18_m.py` that fails on them (a full-file selector took 566 s and I did not run the three against it).
why it matters: K7b means a row with U_val at or above 50 % of the reference no longer blocks level 3 when four other rows pass: the rule row 880 and the page's 'an uncertainty that wide cannot validate it' state.
wrong data: no (as shipped)

### A-5. Addendum: `_l23_text` names two heights, and `_low_antenna_note` accepts a rounded height as exact: PE11, Q3, Q5
severity: minor
lane: tests
where: cafe/pm/credibility.py:LOW_ANTENNA_NAMES (0.3 'the Slocum', 0.5 'the Seaglider'), cafe/pm/report.py:777 (`pair = (known[0], known[1])`), :739 (`mission["ship"]["antenna_height_m"]`)
reproduction: `python x_rev/mut_driver.py mut3 PE11 Q3 Q5` (selector `tests/test_round18_x.py tests/test_round18_a.py`, green, 127 s): (PE11) the names of 0.3 m and 0.5 m swapped, so L23 would call the 0.5 m antenna the Slocum's and the 0.3 m the Seaglider's, with every figure right; (Q3) `round(known[0], 1)` in the pair lookup, which turns 0.30000000000000004 into the 0.3 row, against row 991's rule that a pair is measured only when exactly a row's; (Q5) a ship with no `antenna_height_m` read as 15.0 for the lookup. All ten rows of the table (each of minimum, median and maximum +0.2 dB, and each key off by 0.05 m: 40 mutants), PE4 to PE10, PE12, Q1, Q2, Q4, Q7 to Q12 are killed; PE1, PE2, PE3 and Q6 are equivalent (no row has a bound at exactly 0; a UAS end's platform file has no `rf_antenna_height_m`, so Q6 gives the same None through the `except`).
why it matters: Q3 is the edge row 991 states ('maps to a pair only when exactly a row's heights'), and no test passes 0.30000000000000004 or 0.5000001 through the card (D's scope does: a hostile input that would be accepted if the code rounded).
wrong data: no (as shipped)

### A-6. `hycom.write_store`: the leftover sweep and `asides` are held only at part of their conditions: H7, H9, H12 survive
severity: minor
lane: tests
where: cafe/pm/env/hycom.py (`asides`: `q.is_dir() and not q.is_symlink()`, the `{12}` hex run), the `held` test in `write_store` (H4, H5, H6 are killed by `tests/test_round18_m.py` and `tests/test_hycom.py`, not by `tests/test_round18_e.py` alone)
reproduction: `python x_rev/mut_driver.py mut4 H7w H9w H12w` (selector `tests/test_round18_m.py tests/test_hycom.py tests/test_remote.py tests/test_round17_f.py`, 14 s, green): (H7) `asides` also returns a symbolic link whose name fits the pattern (`write_store` then `rmtree`s it, which `shutil.rmtree` refuses for a link and `ignore_errors` hides, so the link stays); (H9) `[0-9a-f]{1,12}` for the 12 hex digits (a shorter name of the same stem is then a leftover); (H12 is an identity edit of mine: ignore). H1 to H3, H4 to H6, H8, H10, H11, H13 are killed (the first run with `tests/test_round18_e.py` alone passed H4 to H9, H11 to H13: the sweep is held by `test_round18_m.py` and `test_hycom.py`, a file the row does not name). O13 (the `yield False` comment edit removed, an identity edit: ignore) survives.
why it matters: row 969's claim 'a directory, not a link, the 12 hex digits' is held at one condition of three.
wrong data: no

### A-7. CFD cache key, `env_count`, `_seed`, `replace_from` and the lock files: surviving mutants
severity: minor
lane: tests
where: cafe/pm/par.py:55, :56 (N5, N6), cafe/cfd.py:62 to :68 (C9, C10), cafe/_seed.py (D7, D2), cafe/atomic.py (A3)
reproduction: `python x_rev/mut_driver.py mut4 N5w D7w A3w` (selector `tests/test_round18_m.py tests/test_cfd.py tests/test_config.py tests/test_round17_e.py`, 120 s, green) and `mut2`:
- N5 (`digits and` dropped from the wording test, so any value longer than 9 characters, such as `CAFE_X=abcdefghij`, is told it 'has more than 9 digits'): survives. N6, N9, N10, D2 are killed by the wider selector (they survived `tests/test_round18_d.py`).
- D7 (the last warning of the cache instead of the first named in the `NOT seeded` line) survives, A3 (`replace_from`'s `fchmod` of the target's mode written `fchmod(fd, mode or 0o600)`, `0o600` for a new name) survives in both selectors.
- C9 (the exempt names of `NOT_KEYED` gaining `dvec`, so an edit of `dvec`'s numbers or labels leaves the CFD key) and C11 (`ClassDef` dropped from the key's walk) were killed by `tests/test_cfd.py` and `tests/test_round17_e.py` (they survived `test_round18_d.py` alone, which names the row). C10 (`par` as the import name) fails at import, not counted.
why it matters: A3 is row 963's 'fchmod only when the target has a mode to keep' stated twice and held by neither test; D7 is the exit text of `_seed`.
wrong data: no

### A-8. The hull grammar and `sprt_decide`: G11, G14, G15, G16, I7, I8 passed the narrow selector; the wide rerun did not finish
severity: minor
lane: tests
where: cafe/fea.py (`_NOT_PLAIN_FIRST` without `:`, the key-line check, `if not m[1]` as `len(m[1]) == 0` (equivalent), the 40-character cut of the message), cafe/pm/stats/sequential.py:28 to :29
reproduction: with `tests/test_round18_f.py` (green, 14 s) G11 (the colon removed from `_NOT_PLAIN_FIRST`), G14 (the `_MESH_KEY_LINE` check removed: a key line with a flow mapping or a tag is then read), G16 (the whole line in the refusal message, not its first 40 characters), I7 and I8 (`sprt_decide` no longer checks `k` or no longer checks `n`) all pass; G15 is equivalent. I reran them with `tests/test_stage3.py`, `tests/test_round16_pb.py`, `tests/test_round18_m.py` and `tests/test_stats*.py` as `mut4`: not finished when I stopped (the stage-3 baseline is long). Not run.
why it matters: `tests/test_round18_m.py` is the file that names `sprt_decide` (972); if it holds neither argument the row's two checks are unheld.
wrong data: no

### A-9. The UAS Mann-turbulence length is not held by a test (U10)
severity: minor
lane: tests
where: cafe/pm/stage1.py:286 (`uas.sortie_t_max(so) + 60.0`)
reproduction: `python x_rev/mut_driver.py mut5 U10` (selector the four `test_r18_a2_*` tests of `tests/test_round18_c.py`, 11 s, green): `so["duration_s"] + 60.0` passes. U3, U4, U8, U9, U11 (the other sites and the helper) and round 18's A-2 U8 and U3 are killed by the new tests; A-2's U2 site of round 17 is this one in its present place.
why it matters: row 959 says each of the sortie-length sites was shown failing on its mutant; this one, the length of the turbulence series a hard-stop flight reads, is not.
wrong data: no

### A-10. `whatif._numbers` prints a duty the message says is allowed: 1.0000001 is refused as 'duty 1'
severity: minor
lane: robustness
where: cafe/pm/whatif.py (`_numbers`, the 'needs finite numbers and a duty above 0 and at most 1' message)
reproduction: on orca, `whatif._numbers("v", dict(shift_h=0, dlon=0, dlat=0, duty=1.0000001), box)` raises `Invalid: v: the change shift_h 0, dlon 0, dlat 0, duty 1 needs finite numbers and a duty above 0 and at most 1` (probe `x_rev/probe2.py`).
why it matters: the refusal prints the value with `:g`, so it reads 'duty 1 needs ... at most 1'. A lab user is told a duty of 1 is refused.
wrong data: no

## Mutants of the rows that all tests killed

For the record, killed by the tests the rows name: the flip search's `want`, `want_s1`, `_better_than` (both cases), the early stop and the budget charge (F1 to F9); links not rerun (L1 to L4); the UAS shift bound (S2 to S4); the `plan.json` check (P1 to P4); the header (H1 to H3); `same_members` `available`, `measured`, `source` and the `BASE_SAME_*` values (SM1 to SM8); the three cases of the card (Q1, Q2, Q4, Q7 to Q12); R1, R2a, R2b; every `RANKED`, `ACTING`, `UNSEEN`, `DEMO_ONLY`, `link_acts` edit (R1 to R20, the six table ones against the heavy `ci_full` probe, 180 to 376 s each); the five comms mutants A1a to A1e and the sortie sites U3, U4, U8, U9, U11 (the comms ones, which round 18's reviewer A found alive, are now dead); the CFD sign cases C1 to C8; the lock modes and links O1 to O12; `replace_from`'s link refusal A1, A2, A4, A5.

## DECISIONS rows read (50, none listed by the reviewer_a files of rounds 13 to 18)

54, 67, 106, 148, 153, 194, 196, 209, 220, 232, 273, 292, 357, 359, 362, 409, 454, 455, 467, 502, 518, 539, 573, 577, 624, 697, 704, 708, 722, 729, 732, 744, 766, 785, 840, 850, 861, 871, 885, 916, 918, 927, 934, 946, 969, 989, 991, 992, 993, 994.

Checked against code or by running: 153 (`set_thresholds`: `P_FAIL_GO = round(1 - go, 12)`, the 0.75 cap, the bound 0 < nogo < go <= 1: as the row says), 209 (`pipeline.fit_wind_error`: `max(between - sampling, 0) + between / k`, the square root, `to_marginals`: as the row says), 357 (`orca.hours`: floor of the start, ceil of the end, empty before: as the row says), 409 (`stage1.ship_antenna_m`: the mission's, else the platform's `ship_antenna_height_m`, else 10: as the row says), 573 (`hycom.box360`: 361 and 371 degrees refuse, 360 is fine, run on orca), 708 (`remote._is_url`), 850 (`refit.pool`: a standard error 0 becomes `SE_FLOOR` 1e-12, NaN and a negative one `ValueError`, run on orca), 861 (`_numbers`: a duty 0, nan, -1 or above 1 is `Invalid`, run: A-10), 871 (`_duty_days(3.0000000000000004, 1.0) == 3.0`, 3.1 gives 4.0, run), 918 (the 'of the run' text, R1 killed), 946 and 989 (the floors and `UNSEEN` as the rows say; the floors are amended by the prompt's 0.172, 0.182, 0.199), 969 (`_aside_name`, `asides`, the lock condition: A-6), 991 to 994 (all four read against the code and the 100 mutants above; 993's `measured` keys are held by SM1 to SM8 and the `source` of an older `flip.json` by SM9's survivor, A-3). The others were read for what they say: 54 and 106 are history of numbers that STATUS and PHYSICS carry (the USV `appendage_cda_m2` 0.04 and the 2.9 m/s calibration target are in the platform file's header as the row says), 148 (the pragma list), 518, 624 (the `.PHONY` line names only targets with a rule: checked by reading), 927 and 934 by reading.

## Not run

- A Fock or parabolic-equation recomputation of the ten pairs (B's lane); every row of the table is held to 0.1 dB by `tests/test_round18_x.py` (the 40 table mutants are killed) but I did not recompute any of them.
- The wide rerun of G11, G14 to G16, I7, I8 (A-8).
- `make audit`, a gate, a demo run, a full mutation run: none started. The what-if end to end and a real run's 'becomes' line (C's scope).
- The mutants of K12a, K4, K7b against the full-file credibility selector (566 s each).
- Orca state at the end: my directories `pm_rev19_a` and `pm_rev19_a2`, their `.pmx.job.*` markers and my `rev19a_*` logs are removed; the tmux sessions I started (`rev19a_base`, `rev19a_m1` to `rev19a_m4`) were killed by exact name; the scratch worktree `../cafe-rev19-a` is removed. The stage-3 baseline of A-8 was cut short by the kill; `tmux ls` shows only `watch`. Probe 1 wrote and removed one temporary directory under `/data` (inside `~/cafe-worker`). The one `bin/pmx.sh` call made without `PM_HOST` (a shell-chain slip) was refused by the owner check before anything was sent.

total: 10 findings (0 critical, 0 major, 10 minor)
