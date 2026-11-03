You are builder V (vehicles and environment) for review round 5. First read review/round_5/batch_prompts/r5_common.md and follow it exactly. Your letter is v; PM_CPUS=2.

Your findings: M-1, M-4, M-9, M-20.
Files you own: cafe/pm/physics/*.py, platforms/*.yaml (only what M-4 needs), cafe/pm/env/grid.py, cafe/pm/env/environment.py (everything except `GriddedEnv.__init__`), cafe/pm/env/protocol.py (only if M-9 needs `rain_hourly` on the analytic environment), tests/test_glider.py, tests/test_usv.py, tests/test_uas.py, tests/test_grid.py, tests/test_environment.py, tests/test_physics*.py, tests/test_platform*.py.
Shared files, only these parts: cafe/pm/stage1.py function `_uas_forcing` (M-9); cafe/pm/pipeline.py only the ingest check that reads the zero-sea-node n (M-20), nothing else; new tests appended to tests/test_stage1.py (M-1, M-9), tests/test_whatif.py (M-1's design test) and tests/test_pipeline.py (M-20).
