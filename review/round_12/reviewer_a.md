# Round 12, reviewer A

Scope done: mutants of round 11's fixes (30 + 6 runs on orca, 2 CPUs, proot, detached copy at 0a0532e), and 58 DECISIONS rows between 4 and 526 read against the code. See "not covered" at the end.

### A-1. The "10 deg pad from about 26 days" figure is wrong: it is reached at 24.4 days
severity: minor
lane: documentation
where: docs/RUNBOOK.md:158; DECISIONS.md row 229; cafe/pm/pipeline.py:196-202 (the rule); cafe/pm/pipeline.py:192 (the comment names `config/schemas mission.json`, the file is `cafe/schemas/mission.json`)
reproduction: `padding()` is `min(10, ceil(days*86400*0.5/111e3*2)/2)`. At 24.4 d: 9.4949*2 = 18.99, ceil 19, pad 9.5. At 24.5 d: 9.535*2 = 19.07, ceil 20, pad 10. python: `min(10, math.ceil(24.5*86400*0.5/111e3*2)/2)` = 10.0. The cap is reached at 24.41 d, not "about 26".
why it matters: RUNBOOK tells a lab user at which window length the pad stops growing; a 25-day mission is told it is not capped and is. Carried unchanged from round 3.

### A-2. Regression tests of round 11 whose mutants survive (tests that do not pin their fix)
severity: minor
lane: documentation / tests
where: tests/test_stage3.py:475-482 (M-27, `YPLUS_LAM`); tests/test_credibility.py:1245-1253 and tests/test_cli.py:1094-1105 (M-5, `counts_ok`); tests/test_pipeline.py `test_l0_r11_*` and `test_r11_m6_*` (`CALM_SWH_M`, `FLAT_SHARE_MAX`); tests/test_report.py::test_l0_r11_* (M-2 label check)
reproduction: harness `mut12a.py`/`mut12a2.py` (detached copy only; apply one edit, run the named tests with `-x`, restore). Results, "SURVIVED" = the tests named still pass:
- `stage3/wallmodel.py:49 YPLUS_LAM = 11.06 -> 11.0` survives `tests/test_stage3.py -k r11_m27`: the parametrised points are y+ 9.5 / 12.5 / 40, so any constant between 9.5 and 12.5 passes (11.06 is the root of ln(y+)/0.41+5.2 = y+; 11.0 is 0.5 % off). 12.4 is caught by other tests in the file, 11.0 is not.
- `credibility.py:473 counts_ok`: `0 <= k <= n` -> `0 <= k < n` survives `-k r11_m5` in test_credibility.py and test_cli.py: no case has k == n, yet k == n is the demo's real data (usv-uas-rf 64 of 64, both acoustic links 64 of 64). The wider run (whole test_credibility/test_cli/test_report) hit my 900 s limit, so whether a distant test catches it is not known; the fix's own test does not.
- `pipeline.py:606 CALM_SWH_M 1e-3 -> 5e-2` (50 times larger) and `pipeline.py:813 broken = flat > FLAT_SHARE_MAX*seen -> flat > 3*FLAT_SHARE_MAX*seen` both survive `tests/test_pipeline.py -k 'ust or calm or wave or umwm or coare or flat'`. The tests pin "one flat point of the sample is fine" and "a third is broken", nothing between; a sea with up to 3 % (or swh up to 5 cm) of dead points passes as healthy. `FLAT_SHARE_MAX` is a stated assumption, but the test does not hold it to 1 %.
- `pipeline.py:813 flat > -> >=` and `uas.py stuck >= stuck_w -> >` survive; the latter is likely equivalent in float32 (stuck accumulates 0.05 s steps), the former sits on an exact-share boundary that no test builds.
- `report.py:292 if again != v["verdict"]` -> `if False` survives `-k l0_r11` (only the NOT EXERCISED relabel is tested there); the wider test_report.py/test_cli.py run timed out at 900 s so another test may kill it.
Killed (good): M-1 `_num`, M-5 isinstance/bool and n>=1, M-20 os_error_text, M-12 overshoot (both `left` and the factor), M-28 sponge ramp and centre weight, M-16 SPREADING_K, M-26 battery reserve, M-6 CALM_WIND_MS, M-22 chunk-key regex, M-10 SUITE_DIRS (both dirs), M-4 `SAME_SEED_K_TOL` (both `>=` and 2), L1 worker_setup 25 GB, M-23 `_val` n slice, M-27 fit_window exponent, M-2 p_fail / conf checks, bounce_back `1/q` for `1/(2q)` (the `q >= .5 -> q > .5` mutant is equivalent: both give 1 at q = 0.5).
why it matters: a surviving mutant is a test that would pass on a broken fix; here three constants (11.06, 1e-3 m, 1 %) the rows claim as pinned are not.

### A-3. "The Environment has no T(z)" is not true of the code: `Ocean.temperature` exists and is unused by the glider
severity: minor
lane: honesty / documentation
where: DECISIONS.md row 49; docs/PHYSICS.md:611; cafe/pm/physics/glider.py:35,249; platforms/seaglider.yaml:23-24; cafe/pm/env/ocean.py:105; credibility limitation L06 (docs/CREDIBILITY.md:132)
reproduction: `grep -n "def temperature" cafe/pm/env/ocean.py` gives line 105, `Tagged(self._at("water_temp", lon, lat, z, t), "... in-situ temperature [degC]")`; row 166 and `Environment.sound_speed` already use the same GOFS T/S at depth. The glider hull's thermal expansion (`glider.py:249`) still uses `t_deep 4 degC + (SST-4) exp(-z/150 m)` and PHYSICS/L06 say "the environment holds no T(z)". `Environment`/`protocol.py` do not expose `temperature`, but the ocean layer holds it.
why it matters: the statement is stale, and L06 (which caps the Input pedigree factor with L01, L05, L11) is a limitation the code could retire with a three-line call, not a missing data source. The text should say "not wired", which is what the lab is told when choosing what to supply.

### A-4. K limit comment says orca has 32 CPUs, the runner comments elsewhere say 64
severity: minor
lane: documentation
where: bin/orca_gate.sh:5,7 ("orca has 32 CPUs", "above orca's 32 CPUs"); bin/pmx.sh header (P-20: "the worker's 64 CPUs")
reproduction: `ssh cafe-orca nproc` printed 64. K=16 jobs of 2 CPUs is 32 CPUs: either 32 is the stated share (then say so) or the comment is wrong.
why it matters: the refusal message for K > 16 gives a reason that does not match the machine's CPU count the other scripts quote.

total: 4 findings (0 critical, 0 major, 4 minor)
