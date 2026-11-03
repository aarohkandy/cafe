You are builder C (mission config and input files) for review round 6. First read review/round_6/batch_prompts/r6_common.md and follow it exactly. Your letter is c; PM_CPUS=1.

Your findings: M-7, M-8, M-9, M-11, M-22, M-24.
Files you own: cafe/pm/config.py, cafe/schemas/, cafe/pm/env/hycom.py, cafe/pm/env/ocean.py, cafe/pm/env/orca.py, tests/test_config.py, tests/test_hycom.py, tests/test_orca.py, tests/test_ocean*.py.
Shared, only these parts: cafe/pm/pipeline.py functions `orca_covers`, `_umwm_depth`, `_tao_cached` (M-8); cafe/pm/__main__.py function `_hangar` (M-22); tests appended to tests/test_environment.py, tests/test_cli.py and tests/test_pipeline.py.
