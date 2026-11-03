# Review round 6 fixes: common rules for every batch

Findings: `review/round_6/merged.md` (M-1 .. M-26). Read the whole finding (claim, check, fix) for each one you own before you change anything, and the file map at its end. The brief is `docs/BRIEF.md`; earlier choices are in `DECISIONS.md` (rows up to 307). Read `CLAUDE.md` (the bar for a change, the banned tokens of `cafe/pm/audit.py` `BANNED`, how to run on homebase).

**Your own worktree.** Five builders work at once. Before anything else, from `/Users/aaroh/Downloads/everything/cafe`:
`git worktree add ../cafe-r6<x> -b r6-<x> premission-step4` (`<x>` is your batch letter in lower case), and work only in `/Users/aaroh/Downloads/everything/cafe-r6<x>`. Never edit the main checkout or another batch's worktree.

**Edit only the files and functions your batch owns** (your prompt lists them; a shared file names the functions you may touch). If a fix needs a change elsewhere, do not make it: write it in your hand-back under "needs from other batches", with the exact change. New tests go at the end of the test file, or in a new test function placed next to the code's existing tests, so the lead's merge stays simple.

Do not edit `DECISIONS.md`, `CHANGELOG.md`, `STATUS.md`, `QUESTIONS_FOR_LAB.md`, `docs/RUNBOOK.md`, `README.md` unless your prompt says so. Write the doc text into your hand-back instead:
- one proposed DECISIONS row per finding: `| ? | <what was decided, with numbers> | Review round 6, M-<n>. <why> |` (the lead numbers them from 308); name any row it amends;
- one CHANGELOG line per finding;
- any RUNBOOK / PHYSICS / CREDIBILITY / QUESTIONS / STATUS text, quoted exactly, with where it goes.

Every fix gets a regression test that fails before the change and passes after. Show it: run the new test on the unfixed code (a `git stash`, or a scratch copy of the old function) and on the fixed code, and quote both results in the hand-back. Never weaken an existing assertion to get green; if an existing test asserted the old wrong behaviour, say which and why it changed. Coverage: 100 % on `cafe/pm/physics`, `cafe/pm/stats`, `cafe/pm/env`, `cafe/pm/stage3`, and do not lower `cafe/pm` (99.95 %). `ruff check cafe/pm tests bench` (lines up to 160) and `mypy cafe/pm` (strict) clean.

Run tests on homebase only, from your worktree root:
`PMX=pm_r6<x> PM_CPUS=<n> PM_MEM=8g bin/pmx.sh python -m pytest -q -p no:cacheprovider tests/test_x.py -k ...`
(`<n>` is in your prompt.) pmx.sh syncs your worktree into your private `~/work/cafe/pm_r6<x>` and runs the `cafe-pm` image there; it splits its arguments on spaces, so for quotes or pipes write a small `sh` script, `scp -i ~/.ssh/homebase_ed25519` it to `azureuser@100.108.213.121:work/cafe/pmdata/r6<x>_<name>.sh` and run `bin/pmx.sh sh /data/r6<x>_<name>.sh`. Other people's services run on the box: never touch containers or directories that are not yours, and do not run the full test suite (the lead runs it after the merge). Whole test files of the code you changed are fine. Leave no container of yours running when you hand back (`docker ps | grep pm_r6<x>`). Disk is 97 % full: write nothing large.

Honesty: no fake results, no weakened tests, no test that only checks the code does what it does. If a fix in `merged.md` turns out wrong or impossible, say so with the evidence and do the honest alternative. Match the surrounding code style (dense, comment-light, long lines up to 160). Use the exact interface names below; a reader of a new key must accept its absence (older runs).

Interfaces between batches (fixed in advance):
- M-1: the USV mode key stays `no_current_data`; batch V rewrites the `report.MODE_TEXT["no_current_data"]` entry (only that entry of report.py).
- M-3: batch S sets `budget.SITL` to 0 for every budget (only that constant of budget.py) and writes the report sentence.
- M-23: batch P adds `par.env_count(name)` (the shared parse of a whole-number environment variable, `ConfigError` naming it) and uses it in `freesurface.nproc`.
- `cafe/pm/pipeline.py` is shared by function: V `_tao` (M-5); C `orca_covers`, `_umwm_depth`, `_tao_cached` (M-8); S the stage-1b note in `s_stage1b` and anything M-17 reads there; P `Context` and the re-plan in `s_ingest` (M-2) and `_offline` (M-23). `cafe/pm/__main__.py`: C `_hangar` (M-22), S the `receipts` flag text (M-12). `cafe/pm/whatif.py`: S the `tried` entries (M-13), P `add_rows` (M-6). `cafe/pm/stage3/freesurface.py`: W `fitting_budget` (M-14), P `nproc` (M-23). `cafe/pm/audit.py`: V `BANNED` (M-26), W `main` (M-20). Touch no other function of a shared file.

When done: commit your work on your branch `r6-<x>` (one commit is fine; message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; do not push), and write the hand-back to `review/round_6/handbacks/r6_handback_<X>.md` inside your worktree and commit it too. Hand-back: per finding, what changed (file:line), the test, its before/after result, and the doc text; then "needs from other batches"; then the exact commands you ran and their results. Reply with one line: the findings fixed and any not fixed.

If you open a browser page with media, mute it immediately.
