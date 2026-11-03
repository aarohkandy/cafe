You are builder P (pipeline, planner, workers, ledger) for review round 5. First read review/round_5/batch_prompts/r5_common.md and follow it exactly. Your letter is p; PM_CPUS=2.

Your findings: M-5, M-6, M-10 (`fit_wind_error`/`_tao`: `value_hi95`), M-13 (budget `describe`, `stage1_s_basis`, the emulator check replaced by a note, `variant_planned_s`/`variant_wall_s` in emulator/design.json), M-15, M-21, M-23.
Files you own: cafe/pm/pipeline.py (except the one ingest check of M-20, which is batch V's), cafe/pm/budget.py, cafe/pm/par.py, cafe/pm/ledger.py, bench/throughput.py, config/throughput.json (only if M-5 needs a new key, with its source), tests/test_pipeline.py, tests/test_budget.py, tests/test_par.py, tests/test_ledger.py, tests/test_bench.py.
M-6's PlanError must leave the demo's quick plan on homebase's 8 CPUs and the CI plans unchanged unless memory really caps them; say in the hand-back what the demo plan prints before and after.
