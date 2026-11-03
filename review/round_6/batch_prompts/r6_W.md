You are builder W (stage-3 budget message, tooling) for review round 6. First read review/round_6/batch_prompts/r6_common.md and follow it exactly. Your letter is w; PM_CPUS=1.

Your findings: M-14, M-19, M-20, M-21.
Files you own: cafe/pm/stage3/pipeline_windows.py, bin/pmx.sh, Makefile, tests/test_stage3.py, tests/test_freesurface*.py, tests/test_config_docs.py.
Shared, only these parts: cafe/pm/stage3/freesurface.py `fitting_budget` (M-14; `nproc` is batch P's); cafe/pm/audit.py `main` (M-20; `BANNED` is batch V's); tests appended to tests/test_audit.py.
M-19: `bin/pmx.sh` must pass `CAFE_GIT_DIRTY` exactly as `pm.sh` does; your own runs through it will then record the flag. M-21: `make acceptance` must not delete a user's runs without saying so (the finding's fix).
