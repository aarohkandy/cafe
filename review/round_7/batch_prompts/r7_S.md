You are builder S (stage 3) for review round 7. First read review/round_7/batch_prompts/r7_common.md and follow it exactly. Your letter is s; PM_CPUS=2.
Your findings: M-8, M-9, M-10, M-13, M-28, M-29, M-44.
Files you own: cafe/pm/stage3/*.py (pipeline_windows.py all but `track_heading`, batch V's), config/assumptions.yaml (M-10's `hull_draft_m` why), tests/test_stage3*.py, tests/test_lbm*.py, tests/test_nest*.py, tests/test_wallmodel*.py, tests/test_refit*.py, tests/test_freesurface*.py, tests/test_windows*.py.
Shared, only these parts: cafe/pm/budget.py `LES_BYTES_PER_CELL` and `max_cells` (M-13); tests appended to tests/test_budget.py.
Coverage of cafe/pm/stage3 stays 100 %.
