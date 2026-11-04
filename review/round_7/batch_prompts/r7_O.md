You are builder O (ocean and cache readers) for review round 7. First read review/round_7/batch_prompts/r7_common.md and follow it exactly. Your letter is o; PM_CPUS=1.
Your findings: M-2, M-3, M-12, M-17, M-24, M-30, M-31, M-36, M-46 (the `GriddedEnv` docstring; the `WORKER_GB` comment is batch P's).
Files you own: cafe/pm/env/hycom.py, cafe/pm/env/ocean.py, cafe/pm/env/environment.py, cafe/pm/env/orca.py, cafe/pm/env/surface.py, tests/test_hycom.py, tests/test_ocean*.py, tests/test_environment.py, tests/test_orca.py, tests/test_surface.py.
Shared, only these parts: cafe/pm/pipeline.py `_derived_unchanged` (M-2), `_ocean_cached` (M-12), the comment of M-17; tests appended to tests/test_pipeline.py.
M-3's xarray deprecation: fix the join explicitly, do not silence the warning.
