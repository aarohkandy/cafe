You are builder V (vehicles and links) for review round 8. First read review/round_8/batch_prompts/r8_common.md and follow it exactly. Your letter is v; PM_CPUS=2.
Your findings: M-8, M-11, M-12, M-13, M-14, M-17, M-25, M-26, M-27, M-28, M-36, M-37, M-38, M-49, and M-43 (all but its stage-3 tests, which are batch S's).
Files you own: cafe/pm/physics/*.py (comms.py all but K's `["value"]` read), platforms/*.yaml except modems.yaml, cafe/pm/stage1.py (M-17), tests/test_usv.py, tests/test_glider.py, tests/test_uas*.py, tests/test_comms*.py, tests/test_platform_required.py, tests/test_stage1.py.
Shared, only these parts: config.py's empty-platform refusal (M-25); report.py's `MODE_TEXT` entry of M-14; tests appended to tests/test_report.py and tests/test_config.py.
M-8 and M-43 are numerics and test strength: give the numbers (the polar disagreement before and after; each new test failing on the mutant it names) in the hand-back.
