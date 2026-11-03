You are builder P (planner memory, concurrency, environment switches) for review round 6. First read review/round_6/batch_prompts/r6_common.md and follow it exactly. Your letter is p; PM_CPUS=2.

Your findings: M-2, M-6, M-23.
Files you own: cafe/pm/budget.py (all but the `SITL` constant, which is batch S's), cafe/pm/par.py, cafe/pm/emulator.py, tests/test_budget.py, tests/test_par.py, tests/test_emulator.py.
Shared, only these parts: cafe/pm/pipeline.py `Context`, the re-plan in `s_ingest` (M-2) and `_offline` (M-23); cafe/pm/whatif.py `add_rows` (M-6); cafe/pm/stage3/freesurface.py `nproc` (M-23); tests appended to tests/test_pipeline.py, tests/test_whatif.py, tests/test_freesurface*.py or tests/test_stage3.py.
M-6 is a race between processes: the regression test must really run concurrent writers (processes, not threads) and show rows lost or a corrupt table before the fix.
