You are builder W (what-if, free surface, CI workflow) for review round 5. First read review/round_5/batch_prompts/r5_common.md and follow it exactly. Your letter is w; PM_CPUS=1.

Your findings: M-14, M-16, M-22.
Files you own: cafe/pm/whatif.py, cafe/pm/__main__.py (everything except `_report`, which is batch C's), cafe/pm/stage3/freesurface.py, .github/workflows/premission.yml, Makefile (only if M-16 needs it), tests/test_whatif.py, tests/test_cli.py, tests/test_freesurface*.py, tests/test_stage3.py (only M-22's tests), tests/test_config_docs.py (only M-16's workflow check).
For M-16, the CI job must be able to reach green on GitHub's runner as it is (the fix in merged.md); a test reads the workflow file and pins what makes it reachable.
