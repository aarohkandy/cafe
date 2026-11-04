You are builder C (command line and mission config) for review round 8. First read review/round_8/batch_prompts/r8_common.md and follow it exactly. Your letter is c; PM_CPUS=1.
Your findings: M-3, M-6, M-18, M-39, M-52.
Files you own: cafe/schemas/mission.json (M-18), tests/test_config.py, tests/test_cli.py.
Shared, only these parts: the __main__.py and config.py functions named for C in the common file.
M-6: a re-render (`report --run`) must not be refused by the planner's stage-1 memory model; the CLI tests that reach the planner must run in a small container (say which limit you tested at).
