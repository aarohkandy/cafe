# Reviewer B, round 7: findings on commit c59c449 (branch premission-step4)

Method: read cafe/pm (config, stage1, stats, emulator, env, glider, comms, budget, report paths), recomputed numbers from the q7 ledgers and report.json, and ran probes at 1 CPU in `~/work/cafe/pm_rev7_b` on homebase (mission variants through `config.load_mission` and `budget.plan`, `stage1.run_batch` against `AnalyticEnv` with hostile fields, CLI calls with corrupt files). Probe scripts are in `/private/tmp/claude-501/-Users-aaroh--claude-spares-spare-P6utrU/96cd665b-6853-40e7-8769-780fbfcaeebd/scratchpad/rev7/b/` (t6.py, t13.py, t5.py, t9.py, t7.py, t11.py, t12.py; run with `run.sh <script>`).

### B-1. A mission with a UAS silently loses its own `verdict: {go, nogo}` thresholds when the budget is planned
severity: major
lane: statistics / reproducibility (wrong verdicts, no error)
where: cafe/pm/budget.py:229-231 (`bench_sortie_rate` calls `load_mission` on the benchmark's mission) called from budget.py:244 (`scale_uas_costs`, reached by `budget.plan`); cafe/pm/config.py:341 (`load_mission` ends with `intervals.set_thresholds`, module-global state); cafe/pm/pipeline.py:98 and :122 (Context loads the user's mission, then plans)
reproduction: the shipped `config/throughput.json` `stage1.uas` entry has no `sortie_min`, so `bench_sortie_rate` takes the `load_mission(ROOT / e["mission"])` branch, which loads `missions/tepex_c_demo.yaml` (go 0.9, nogo 0.6) and overwrites the thresholds of the mission the user loaded. `t13.py` (real `pipeline.Context`, mission = demo with `verdict: {go: 0.8, nogo: 0.5}`):
```
mission verdict block {'go': 0.8, 'nogo': 0.5} | module thresholds after Context(): 0.1 0.4     (should be 0.2 0.5)
9 of 20 members fail (success 0.55) -> NO-GO        (mission says NO-GO only below success 0.5: MARGINAL)
no-UAS mission: thresholds 0.2 0.5 -> MARGINAL
```
`t6.py` shows the same with a bare `config.load_mission` followed by `budget.plan`: P_FAIL_GO 0.2 -> 0.1, P_FAIL_NOGO 0.5 -> 0.4. Everything after planning uses `intervals.verdict`, `verdict_from_p`, `interval_region` (the sequential stopper too), the emulator's verdict and the report's "GO when P(fail) is at most ..." sentence, all at the demo's cut-offs. The shipped demo and CI missions both use 0.9/0.6, which is why no test or q-run saw it.
why it matters: RUNBOOK and QUESTIONS_FOR_LAB tell the lab to set their own go/no-go cut-offs in the mission; for any mission that has a UAS they are ignored without a message and the verdicts and stopping point are those of the demo. Fix at the root (do not let `bench_sortie_rate` call the stateful `load_mission`, or save and restore the thresholds, or pass them explicitly) and add a test that plans a UAS mission with non-default `verdict` and checks the thresholds afterwards.

### B-2. `subset_simulation` computes the chain-correlation factor on the wrong indicator at every intermediate level, so its c.o.v. is too low
severity: minor (the function is not called by the pipeline or the report; it is a tested module in `cafe/pm/stats`)
lane: statistics
where: cafe/pm/stats/rare.py:61; tests/test_stats_exact.py:499 and :510 pin the wrong values (`cov == 0.3544901912004715`, `0.3037728921604659`)
reproduction: line 61 is `gam = _gamma(g.reshape(length, nc) >= levels[-1])`. At level `lvl` the samples `g` are the chains already conditioned on `g >= levels[-1]`, so that indicator is all ones and `_gamma` returns 0.0 (its `r0 == 0` branch). Au and Beck's gamma_i (their eq. 29-30) is the correlation of the indicator of the NEW threshold `b_i`, which is computed on the next line. Spy on `_gamma` (`P(u0 >= 3.5)`, n = 1000, seed 1): calls return `(mean 1.0 -> gamma 0.0)` three times, then `(0.211 -> 5.11)` for the final level only. Over 150 seeds (`t9.py`, n = 500, 1-D normal, target 3.5): the empirical c.o.v. of p-hat is 0.77, the mean reported cov is 0.30; with gamma taken on `g >= b` the reported mean is 0.47. So the reported c.o.v. is 2.6 times too small, and the test pins that number.
why it matters: the module claims to follow Au and Beck Sec. 5; anyone who uses it for a rare-failure probability gets a confidence that is far too tight. Either wire it to the correct indicator and repin, or delete the module (nothing reads it).

### B-3. The emulator's out-of-range threshold counts replicate rows as nearest-neighbour distance 0 and can collapse to 0
severity: minor
lane: statistics / robustness
where: cafe/pm/emulator.py:185-186 (`nn = self._tree.query(z, k=2)[0][:, 1]`, `threshold = quantile(nn, 0.99)`); fed by cafe/pm/whatif.py:402-425 (`fit_class` trains on all rows, not on distinct feature points)
reproduction: `t5.py`: `synthetic_table(120)` fitted once gives threshold 2.09 and refuses 0.5 % of fresh in-distribution points; the same 120 points repeated 5 times (replicates) give `threshold 0.0` and `refused frac on fresh in-distribution points 1.0`. Any table in which at least 99 % of rows have an exact duplicate behaves this way (two rows per point is enough). The report itself says "only 4 of them are distinct feature points" for the UAS rows of q7, so duplicated feature vectors do occur in the real table (variants whose change `_fits` shrinks to "no change" share the baseline's features; `row_key` includes the variant label, so they are separate rows). The hold-out is split by distinct point, but the threshold is not computed on distinct points.
why it matters: once the 100-distinct-point gate is passed, a table with many collapsed variants gives an emulator that says "out_of_range" to every query (or a much smaller guard than the one the documentation describes). It fails on the safe side but silently, so the "emulator trained" report line is misleading. Compute the leave-one-out distances on `drop_duplicates` of the z-scored features.

### B-4. A corrupt (non-UTF-8) mission or platform file, and a corrupt or non-object `plan.json`, end in a raw Python traceback, not an `error:` line
severity: minor
lane: robustness
where: cafe/pm/config.py:60 (`yaml.load(path.read_text(), ...)` catches `yaml.YAMLError` and `ConfigError` only); cafe/pm/__main__.py:174 (`json.loads((run / "plan.json").read_text())`, then `plan["budget"]`)
reproduction (`t7.py`, `t11.py`, `validate` and `report` through `python -m cafe.pm`): a mission file of `bytes(range(256))` or a UTF-16 file gives `rc=1` and `UnicodeDecodeError: 'utf-8' codec can't decode byte 0x80 ...` (Traceback); the same for a binary `mission.yaml` in a run directory passed to `report`. `report --run D` with `plan.json` = `{` gives `json.decoder.JSONDecodeError` (rc 1, Traceback); with `plan.json` = `[]` gives `TypeError: list indices must be integers or slices, not str`. A UTF-8 BOM file is read correctly, a NaN, an empty file, a list, a scalar and a tab are all refused cleanly, so the gap is only the decode step and the JSON step. (Round 6 M-8 fixed the same class for the orca manifests.)
why it matters: BRIEF 5.6 lists "corrupt file" as a robustness input and the RUNBOOK promises `error:` with exit 2 for a wrong file. Catch `UnicodeDecodeError` in `_yaml` and `ValueError`/`TypeError` around the `plan.json` read (and any other `json.loads` of a run file the CLI reads).

### B-5. `hangar --platform <file>` on a glider or USV file that lacks a top-level block dies with `KeyError: 'params'`, against the RUNBOOK's claim
severity: minor
lane: documentation / robustness
where: cafe/pm/physics/glider.py:103 and cafe/pm/physics/usv.py:140 (`flat(raw["params"], "params")`); cafe/pm/__main__.py:219 (`_hangar` catches only `ValueError`); docs/RUNBOOK.md:115 ("`hangar --platform <file>` and `validate` name the file and the field that is missing or out of range")
reproduction (`t12.py`): a file `kind: seaglider` / `mass_kg: 52` (and likewise `kind: saildrone_usv`) gives
```
  File "/app/cafe/pm/__main__.py", line 219, in _hangar
  File "/app/cafe/pm/physics/glider.py", line 103, in load_platform
    P = flat(raw["params"], "params")
KeyError: 'params'
```
exit 1, no file name. The UAS loader, for an empty file, does give "missing ['airframe', ...]; add them (see platforms/quad_uas.yaml for the layout)". `validate` with the same file prints `does not load as a glider platform (KeyError: 'params')`: names the file, but not what to add.
why it matters: the lab is told to edit these files when datasheets arrive; the first typo in the structure gives a traceback from `hangar`, the command the RUNBOOK sends them to. Give the glider and USV loaders the same "missing [...]; see platforms/<file>" refusal as the UAS loader.

### B-6. RUNBOOK step 2 says `pm make ci` ends with the `report:` line; it ends with `audit: 0 problem(s)`
severity: minor
lane: documentation
where: docs/RUNBOOK.md:71; Makefile `ci` target (the last command is `python -m cafe.pm.audit --ledgers-only $(RUNS)/ci`, whose last print is `audit: N problem(s)`, cafe/pm/audit.py:294)
reproduction: read the two; the `report: runs/ci/report/index.html` line is printed by the `run` command before the audit. A lab user following "you should see ... at the end" will look for a line that is a few lines above the end.
why it matters: step 2 is the lab's first check; BRIEF 0.5 asks that the runbook be followable blind, and a "you should see" that does not match is exactly what its troubleshooting rule says to stop on.

### B-7. The verdict's "90 % Wilson interval" does not say that it holds only the Monte-Carlo error given point-estimate priors
severity: minor
lane: honesty / statistics
where: cafe/pm/report.py:336 (label "Wilson interval (Stage 1)"), report text "P(fail) = 0.2344, 90% wilson interval 0.159 to 0.331 (the verdict's own level)"; cafe/pm/pipeline.py:660-681 (fitted prior = point estimate); ingest/priors_fitted.json
reproduction: the persistent wind-direction bias sd is fitted from 11 moorings and 6 days to 2.63 deg, with a stated 95 % upper bound of 11.6 deg (10 degrees of freedom); the speed one to 0.113 m/s with an upper bound of 0.484 (the BRIEF prior was 15 deg and 2.0 m/s). The ensemble samples the point estimates (`to_marginals` uses `value`), the report prints the upper bounds in the sensitivity-scope paragraph, and the verdict interval for glider_eq (15 of 64) is a binomial interval that carries neither that uncertainty nor the other 261 assumed inputs. No sentence next to the interval says "given these inputs". `grep -i "conditional" docs/*.md STATUS.md /tmp/q7_report.txt` finds nothing.
why it matters: a reader of "0.159 to 0.331" takes it for the uncertainty of the P(fail); it is the sampling error of 64 members at fixed inputs. One sentence in the verdict block (and a stage-1b case at the upper-bound priors, as is done for the USV VPP bias) would make the claim match what is computed.

## Checked and found sound (so the next round need not repeat it)
- Wilson, Newcombe, `n_certify` (73), rule of three, SPRT log-likelihood thresholds, Kerr cubic and divergence factor, Thorp and Stojanovic noise forms, Bolton theta_e, `launch_times` (local solar time at 165 W is 01:00Z), `lhs_unit` strata pairing, `fill_hs` forward/backward fill, `_in_box` with the dateline, the equirectangular distance helpers.
- q7 numbers recomputed from the ledgers: 90 % Wilson 0.159-0.331 for 15/64, 0 of 64 upper bound 0.0406, 6 launches x 4 vehicles, the fitted wind-correction signs (mean -0.616 m/s and +7.2 deg are the negatives of the mean WRF-minus-TAO bias 0.616 and -7.2).
- Mission variants (one vehicle, 20 vehicles, no links, NaN, vehicle outside the box, zero-width box, 30-day window, global box) either validate or are refused with a message; the memory model refuses the global box (851 GB) and the 140 GB wide box; the 30-day demo box is accepted with 1 worker and 32 members (45 GB).
- `run_batch` against hostile analytic environments (zero wind, zero Hs and Tp, NaN wind, NaN Tp, 60 m/s wind, 3 m/s current, depth 0 and 5 m, Hs 20 m) completes with failure modes, except NaN Hs at the ship, which is a deliberate `OutsideData` with a message.
- HTML report escapes every string it inserts (vehicle ids, link ids, notes).

total: 7 findings (0 critical, 1 major, 6 minor)
