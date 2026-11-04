You are builder V (vehicles) for review round 7. First read review/round_7/batch_prompts/r7_common.md and follow it exactly. Your letter is v; PM_CPUS=2.
Your findings: M-4, M-16, M-18, M-19, M-20, M-27, M-35, M-42, M-43.
Files you own: cafe/pm/physics/*.py, platforms/*.yaml (what your fixes need), cafe/pm/stage1.py (M-27's heading record), tests/test_usv.py, tests/test_glider.py, tests/test_uas*.py, tests/test_platform_required.py, tests/test_stage1.py.
Shared, only these parts: cafe/pm/stage3/pipeline_windows.py `track_heading` (M-27); cafe/pm/report.py the `MODE_TEXT` entries of the modes M-16 and M-20 add or reword; tests appended to tests/test_cli.py (M-35), tests/test_stage3.py, tests/test_report.py.
M-18 and M-19 are numerics: show the non-convergence and its fix with numbers in the hand-back (iterations, residuals), not only a passing test.
