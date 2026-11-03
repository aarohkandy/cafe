You are builder C (configuration and input robustness) for review round 5. First read review/round_5/batch_prompts/r5_common.md and follow it exactly. Your letter is c; PM_CPUS=1.

Your findings: M-3, M-17, M-18, M-19.
Files you own: cafe/pm/config.py, cafe/schemas/ (mission and platform schemas, if a fix needs them), cafe/pm/env/hycom.py, tests/test_config.py, tests/test_hycom.py.
Shared files, only these parts: cafe/pm/env/environment.py `GriddedEnv.__init__` (M-19's open guard); cafe/pm/__main__.py function `_report` (M-19's plan.json check); new tests appended to tests/test_environment.py and tests/test_cli.py.
M-3 and M-17 are in `load_mission`, M-18 in the YAML loader: a duplicate key is an error naming the key and line, and a leading-zero number is refused or read as decimal with the decision stated (prefer refusing, naming the field). Platform files are batch V's (M-4); do not change their loader.
