# Round 22, reviewer A

Tree: `premission-step4` head 65e187e (code of c58fba0). Work on orca at 2 CPUs, one job at a time, from a detached scratch worktree (removed) and `pm_rev22_a` (removed). Nothing in the checkout was edited except this file.

## Findings

### A-1. With Bellhop unavailable, an in-range acoustic link outside the +-6 dB band is labelled "Thorp budget decides every link"; RUNBOOK says it is labelled "Thorp only, Bellhop unavailable"
severity: minor
lane: honesty, documentation
where: cafe/pm/stage1.py:709-714 (`_acoustic`, the `not comms.bellhop_available()` branch), docs/RUNBOOK.md:52, tests/test_round21_a.py:199-204 (pins the behaviour)
reproduction: `tests/test_round21_a.py::scene(monkeypatch, km=1.5, available=False)` (a link in range, Thorp margin about +25 dB) gives `method == "Thorp budget decides every link"`. The branch counts only `res["ambiguous"] & need` (the old +-6 dB band, which also ignores `valid`) and falls back to `THORP_DECIDES_LABEL` when that is zero. RUNBOOK 52 says that without Bellhop "every needed in-range acoustic link ... is judged on Thorp absorption alone, and the report says 'Thorp only, Bellhop unavailable' on each such link". Round 21's own M-3 measured that Thorp passes outside the band flip to Bellhop fails (7, 82 and 87 of 87 samples on three made-up profiles).
why it matters: `make install` builds no Bellhop (RUNBOOK 52), so this is the default lab machine. There the verdict of every in-range link whose samples are all outside +-6 dB carries a method line that says Thorp is enough, which is the claim M-3 refuted. The count in the other label, "(N ambiguous samples)", also counts the +-6 dB band and not the samples that would have been refined.
wrong data: yes, the "Method:" line of an acoustic link card (and `method` in report.json) on a machine without Bellhop.

### A-2. `stage1.merge` takes the label of a Thorp-only acoustic link from the first batch, so it describes 32 of 64 members and depends on batch order
severity: minor
lane: honesty (class "first batch / first sample")
where: cafe/pm/stage1.py:874-893 (`method=l0["method"]`; the rebuild of the label runs only when some batch carries a Bellhop count, `infos`)
reproduction: on orca, `stage1.merge` of two minimal batches of one link, with `method` "Thorp budget decides every link" in one and "Thorp only, Bellhop unavailable (40 ambiguous samples)" in the other, gives "Thorp budget decides every link" for the order (A, B) and "Thorp only, Bellhop unavailable (40 ambiguous samples)" for (B, A). Round 21's `_bellhop_label` rebuild fixed this only for the Bellhop-ran path; the unavailable path has no `bellhop` record, so `infos` is empty.
why it matters: the label the user reads is that of the first batch (one batch is 32 members on `quick`), with its count of ambiguous samples. It is the same defect round 21 closed for the other path, and it shares the default-install exposure of A-1.
wrong data: yes, the same Method line (count and wording), limited to the no-Bellhop case.

### A-3. The grep tests of the JSON sweep stop at `cafe/`
severity: minor
lane: robustness (class "oversized numbers at JSON boundaries")
where: tests/test_round21_e.py:94-101 (`CAFE.rglob`), lab/check.py:18,20,86, bench/throughput.py:20,204
reproduction: `grep -n "json.loads" lab/check.py bench/throughput.py` shows 5 raw reads. `lab/check.py:86` reads the lab user's fleet file with `json.loads(path.read_text())` and `bench/throughput.py` reads `config/throughput.json` (which the planner then reads through `load_json`). A 400-digit integer in either file is not refused at the reader. Neither feeds a verdict: lab/check.py only forwards the document to the app, which refuses it, and bench is a developer tool. The docs say "78 sites in 30 files" and do not say that the scripts outside `cafe/` are out of scope.
why it matters: the class claim "one reader" holds only inside `cafe/`; the test cannot see a new raw reader in `lab/`, `bench/` or `bin/`.
wrong data: no.

### A-4. `finite_real` is documented as refusing numpy scalars; it accepts `np.float64` and refuses every other numpy number
severity: minor
lane: documentation
where: cafe/pm/jsonio.py:37-43, DECISIONS 1049
reproduction: on orca, `finite_real(np.float64(1.0))` is True (a `float` subclass), `finite_real(np.float32(1.0))`, `np.int64(1)` and `np.int32(1)` are False. DECISIONS 1049 says "not a numpy scalar". The sites that call it take JSON-parsed values, so nothing is wrong today. `rfband.pair_band` is also lax on frequency: `pair_band(2.2, 15.0, True)` returns a finite band (as 1 Hz: 68.7 to 132.8 dB) and `f_hz = 1e-300` raises ValueError after numpy warnings; both are reachable only through a `radios.yaml` `center_mhz`.
why it matters: a future caller that passes a numpy integer gets "not a number" and one that passes `np.float64` gets a yes; the stated rule is neither.
wrong data: no.

### A-5. Test gaps found by mutation (the mutant is not killed by the round 21 tests I ran)
severity: minor
lane: tests
where: see the list under "Mutants run"
reproduction: harness `probes/mut.py` (not committed; applies one string replacement, runs the listed tests with `-x`, restores). Survivors against `tests/test_round21_*.py` (the big old files `test_stage1.py`, `test_comms.py`, `test_credibility.py`, `test_report.py` and `test_stats.py` were stripped from the first pass to save time, so some of these may be killed there; I did not re-run them):
- `far_ge`: `far = cand & (|margin| >= 60)` (the label's `beyond` count at exactly 60 dB; the refinement itself still happens, so the sample is counted twice). Not equivalent at an excess of exactly the cap: the refined margin is exactly 0, which is a fail, against a kept Thorp margin of 60, a pass.
- `rb_off`: `np.abs(diff) > OFF_DB` as `>=` (the share "more than 3 dB off" at exactly 3 dB; the test that names this passed because no sample sits at exactly 3.0).
- `nc_log1p_th`: the `1e-3` switch of `n_certify_one_sided` moved to `1e-2`: the answers are the same over a Decimal oracle (see "Checked"), so equivalent in practice; no test pins the switch.
- `dead_flush`: `flush=True` dropped from the dead-store note before the write (no test checks the flush).
- `cln_iff`, `cln_sum` (`check_link_needed`'s "NOT EXERCISED iff nobody needed it" and `needed + never == n`) and `rp_omit_none` (`_omit(k, n, need)` dropped from `_never_required_html`) survived `test_round21_a/_m/_b`; `test_round21_b.py` has tests with these names (`test_m6...`, `test_m7...`) that passed with the mutant, so I could not tell whether `test_credibility.py` or `test_report.py` kills them. Re-run with them before treating them as gaps.
- `rp_atfloor`: `at_floor` as `min(hs) <= 0.5` instead of `0.5 in hs` survived (the "An end ... of 0.5 m" start for an end with a leg exactly at the floor beside a lower leg; a UAS list is the only place the two differ).
- Round 21's survivors against the fixed tree: `hy_dead_quote` (no test has a store whose parent path holds a space or quote), `hy_mtime` and `hy_tie` still SURVIVE, `labelAlways` is KILLED now (`test_round21_m.py::test_a_sample_beyond_the_cap...`).
- Round 20's survivors: `S1c`, `S1j`, `S1l`, `IVd`, `RMb` still survive. Round 21 did not change any of their lines (`git diff` of `stage1.py` and `intervals.py` does not touch them) and the reasons stand: S1c, S1j and S1l are equivalent for every grid the code builds; IVd (`3.0 / n` with `n` an int) is equivalent; RMb (lock key without `st_dev`) is equivalent on one file system. `RPb`, `RPd`, `RPf` are gone: `_nearest_row` and the 0.001 m tolerance were deleted.
why it matters: the first three are one-edge cases in code that prints a number or a count; none gives wrong data today.
wrong data: no.

## Mutants run (49 of round 21's new code, plus the survivors of rounds 20 and 21: 58 in all)
KILLED (46): `cens_ge`, `cens_tie_min`, `on_ge`, `refine_lt`, `noswap`, `nofloor_rx`, `fmin_to_fmax`, `median_to_mid`, `spread_min2`, `nc_all_members`, `fracp10_all`, `constant_dropped`, `cap_one_side`, `capped_gt`, `grid_ceil`, `rb_hmax`, `rb_hmin`, `rb_npoints`, `rb_dmin`, `rb_freq`, `rb_median`, `gci_trust_lt`, `gci_neg`, `drag_nomin`, `drag_any`, `json_noparse`, `json_norec`, `fr_bool`, `nc_max1`, `thr_round`, `fo_const`, `fo_harm1`, `fo_scale`, `sprt_ratio`, `plan_typeint`, `plan_batchmin`, `plan_nmax`, `cc_share`, `rp_low`, `rp_both`, `labelAlways`, and others of the list above.
SURVIVED: the 16 named in A-5 (`far_ge`, `rb_off`, `nc_log1p_th`, `dead_flush`, `cln_iff`, `cln_sum`, `rp_omit_none`, `rp_atfloor`, `hy_dead_quote`, `hy_mtime`, `hy_tie`, `S1c`, `S1j`, `S1l`, `IVd`, `RMb`). `merge_label_first` is an invalid mutant (a dead expression, `infos[0] if False else tot`), not a survivor; I did not re-run it as a real one (`tot` from the first batch only).
Not run: the mutants of `rfband` beyond the six above, `report._end_heights`, `_rf_hz`, `credibility._l23_text`, `acceptance._damage`, `jsonio` text/bytes/Path, `config._finite`, `damaged_run_files`, the two grep tests (alias / `from json import`), `hangar._write_result`, `app._read`, `_site_data.gci_table`, `sampling`, `extreme_ranks`, `subset_simulation`, `noise_floor`, the sample of 10 of round 20's killed mutants, round 19's 27, the 50-row DECISIONS sample and the comparison of every pin that round 21 moved (I read DECISIONS 1056's list only).

## Checked, nothing found
- Closure of the classes, by reading and probes: `load_json` with a 4,301-digit integer (the interpreter's own ValueError, no literal printed), 2**1024 (our ValueError), `1e999` (inf, readable on purpose), `-0`, BOM text (JSONDecodeError) and bytes, NUL, empty text: all are ValueErrors or values, none a traceback. A fuzz of every numeric leaf of the four platform YAML files with a 400-digit integer, NaN and inf (just over 230 leaves each, 12 cases): every one is a ValueError or ConfigError, none crashes. So the class does not leak at platform files.
- `n_certify` and `n_certify_one_sided` against a 60-digit Decimal oracle: 20,042 pairs around 1e-3 and across 0.001 to 0.3, 20,000 pairs from 1e-9 to 1e-3, 20,000 Wilson pairs from 1e-12 to 0.98: 0 mismatches.
- The card for the UAS: the heights used by `report._end_heights` (deck + level + 0.1 m) are those of `stage1._uas_links` and of `_pos` (`alt + deck + antenna`). The deck height (8.1 m) is flown during launch and landing and is not a card pair; I computed it: 2.2 m with 8.1 m is -3.4 to +0.4 dB, 15 m with 8.1 m is -5.7 to +40.7 dB, inside the extremes the card prints for 18.1 m (+42.7).
- `drag_sigma`: monotone in the index, flat 0.30 from an index of about 0.283; a missing key, a negative or an oversized index is 0.30 exactly; a missing `lift_gci` is "no lift study". `hull_lift` and `vehicle.build` read through `gci_value`. Not run: a mission flown with an untrusted index.
- `_plan_sizes`: the checks are in the order name, types, bounds; `report --run` does not call it by decision. `_write_result` and `app._read` read as correct (NaN to null in one pass); not run through HTTP or a browser.
- Bellhop: the `wd < 10` return keeps the 5 m floor inside the water; the cap is symmetric so the sign of a sample beyond 60 dB cannot change (the edge at exactly 60 is A-5's `far_ge`).
- Stale text: RUNBOOK 190 and PHYSICS 12.1 describe the live band; QUESTIONS 12d still carries round 19's "matches a measured pair within 0.001 m" sentence as history after its own "computed live" sentence (not counted).
- `platforms/modems.yaml:11` is stale as known (P-R21M6), `docs/BRIEF.md:144` was not re-read.

## Not run
No HTTP client, no browser, no real zarr kill, no real GOFS profile, no `run_batch` through a link, no what-if to its end, no Bellhop cost measurement. 50-row DECISIONS sample not done.

total: 5 findings (0 critical, 0 major, 5 minor)
