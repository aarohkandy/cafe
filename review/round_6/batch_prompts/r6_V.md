You are builder V (vehicles, stage 1, statistics) for review round 6. First read review/round_6/batch_prompts/r6_common.md and follow it exactly. Your letter is v; PM_CPUS=2.

Your findings: M-1, M-4, M-5, M-10, M-15, M-16, M-26.
Files you own: cafe/pm/physics/*.py, platforms/*.yaml (only what M-10 needs), cafe/pm/stage1.py, cafe/pm/stats/*.py, tests/test_usv.py, tests/test_glider.py, tests/test_uas.py, tests/test_platform_required.py, tests/test_stage1.py, tests/test_stats*.py, tests/fixtures/ (only what your tests need).
Shared, only these parts: cafe/pm/report.py the `MODE_TEXT["no_current_data"]` entry (M-1); cafe/pm/pipeline.py function `_tao` (M-5); cafe/pm/audit.py `BANNED` (M-26) and tests appended to tests/test_audit.py and tests/test_pipeline.py.
M-26 is about tests that cannot fail: show each new test failing on the mutant it names (a scratch copy on homebase), as the finding says.
