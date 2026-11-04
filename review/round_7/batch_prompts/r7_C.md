You are builder C (mission config and CLI) for review round 7. First read review/round_7/batch_prompts/r7_common.md and follow it exactly. Your letter is c; PM_CPUS=1.
Your findings: M-1, M-32, M-33, M-34, and M-47's part about the M-9 bounds (row 316: a refusing test for each of the five bounds that has none).
Files you own: cafe/pm/config.py, cafe/schemas/, cafe/pm/__main__.py (M-34's plan.json helper), tests/test_config.py, tests/test_cli.py (append).
Shared, only these parts: cafe/pm/budget.py `bench_sortie_rate` (M-1); cafe/pm/stats/intervals.py the docstring M-1 names; cafe/pm/pipeline.py the `ocean_box` message (M-32); tests appended to tests/test_budget.py and tests/test_pipeline.py.
