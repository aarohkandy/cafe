You are builder S (report, receipts, what-if table, credibility) for review round 6. First read review/round_6/batch_prompts/r6_common.md and follow it exactly. Your letter is s; PM_CPUS=2.

Your findings: M-3, M-12, M-13, M-17, M-18.
Files you own: cafe/pm/report.py (all but the `MODE_TEXT["no_current_data"]` entry, which is batch V's), cafe/pm/receipts.py, cafe/pm/credibility.py, docs/CREDIBILITY.md and docs/PHYSICS.md (only the sentences M-18 changes), tests/test_report.py, tests/test_receipts.py, tests/test_credibility.py.
Shared, only these parts: cafe/pm/budget.py the `SITL` constant (M-3); cafe/pm/whatif.py the `tried` entries (M-13; `add_rows` is batch P's); cafe/pm/pipeline.py the stage-1b note in `s_stage1b` (M-17); cafe/pm/__main__.py the `receipts` flag text (M-12); tests appended to tests/test_budget.py, tests/test_whatif.py, tests/test_pipeline.py, tests/test_cli.py.
