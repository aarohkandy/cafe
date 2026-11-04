# Review round 7 fixes: common rules for every batch

Findings: `review/round_7/merged.md` (M-1 .. M-26). Read the whole finding (claim, check, fix) for each one you own before you change anything, and the file map at its end. The brief is `docs/BRIEF.md`; earlier choices are in `DECISIONS.md` (rows up to 340). Read `CLAUDE.md` (the bar for a change, the banned tokens of `cafe/pm/audit.py` `BANNED`, how to run on homebase).

**Your own worktree.** Six builders work at once. Before anything else, from `/Users/aaroh/Downloads/everything/cafe`:
`git worktree add ../cafe-r7<x> -b r7-<x> premission-step4` (`<x>` is your batch letter in lower case), and work only in `/Users/aaroh/Downloads/everything/cafe-r7<x>`. Never edit the main checkout or another batch's worktree.

**Edit only the files and functions your batch owns** (your prompt lists them; a shared file names the functions you may touch). If a fix needs a change elsewhere, do not make it: write it in your hand-back under "needs from other batches", with the exact change. New tests go at the end of the test file, or in a new test function placed next to the code's existing tests, so the lead's merge stays simple.

Do not edit `DECISIONS.md`, `CHANGELOG.md`, `STATUS.md`, `QUESTIONS_FOR_LAB.md`, `docs/RUNBOOK.md`, `README.md` unless your prompt says so. Write the doc text into your hand-back instead:
- one proposed DECISIONS row per finding: `| ? | <what was decided, with numbers> | Review round 7, M-<n>. <why> |` (the lead numbers them from 341); name any row it amends;
- one CHANGELOG line per finding;
- any RUNBOOK / PHYSICS / CREDIBILITY / QUESTIONS / STATUS text, quoted exactly, with where it goes.

Every fix gets a regression test that fails before the change and passes after. Show it: run the new test on the unfixed code (a throwaway `git worktree add --detach`, or a scratch copy of the old function on homebase; **never `git stash`**: the stash list is shared by every worktree and two builders' stashes crossed in round 6) and on the fixed code, and quote both results in the hand-back. Never weaken an existing assertion to get green; if an existing test asserted the old wrong behaviour, say which and why it changed. Coverage: 100 % on `cafe/pm/physics`, `cafe/pm/stats`, `cafe/pm/env`, `cafe/pm/stage3`, and do not lower `cafe/pm` (99.95 %). `ruff check cafe/pm tests bench` (lines up to 160) and `mypy cafe/pm` (strict) clean.

Run tests on homebase only, from your worktree root:
`PMX=pm_r7<x> PM_CPUS=<n> PM_MEM=8g bin/pmx.sh python -m pytest -q -p no:cacheprovider tests/test_x.py -k ...`
(`<n>` is in your prompt.) pmx.sh syncs your worktree into your private `~/work/cafe/pm_r7<x>` and runs the `cafe-pm` image there; it splits its arguments on spaces, so for quotes or pipes write a small `sh` script, `scp -i ~/.ssh/homebase_ed25519` it to `azureuser@100.108.213.121:work/cafe/pmdata/r7<x>_<name>.sh` and run `bin/pmx.sh sh /data/r7<x>_<name>.sh`. Other people's services run on the box: never touch containers or directories that are not yours, and do not run the full test suite (the lead runs it after the merge). Whole test files of the code you changed are fine. Leave no container of yours running when you hand back (`docker ps | grep pm_r7<x>`). Disk is 97 % full: write nothing large.

Honesty: no fake results, no weakened tests, no test that only checks the code does what it does. If a fix in `merged.md` turns out wrong or impossible, say so with the evidence and do the honest alternative. Match the surrounding code style (dense, comment-light, long lines up to 160). Use the exact interface names below; a reader of a new key must accept its absence (older runs).

Memory: six builders share the box. Run tests at `PM_MEM=8g`; a whole `tests/test_cli.py`, `tests/test_pipeline.py` or `tests/test_whatif.py` may need 12g (the stage-1 memory guard), never more. Prefer node ids and `-k` while you work.

Interfaces between batches (fixed in advance). Shared files are split by function; touch no other function of a shared file:
- `cafe/pm/pipeline.py`: C the `ocean_box` message (M-32); P `n_var` (M-14), the `ensemble_size` note (M-22) and the member offsets in `s_emulator` (M-7); O `_derived_unchanged` (M-2), `_ocean_cached` (M-12) and the comment of M-17.
- `cafe/pm/budget.py`: C `bench_sortie_rate` (M-1); S `LES_BYTES_PER_CELL` and `max_cells` (M-13); P everything else it needs (M-38's message, M-46's comment).
- `cafe/pm/stage3/pipeline_windows.py`: V `track_heading` (M-27); S everything else.
- `cafe/pm/report.py`: V the `MODE_TEXT` entries of the modes M-16 and M-20 add or reword; R everything else.
- `cafe/pm/env/environment.py`: O (M-24 and M-46's docstring).
- `cafe/pm/stats/intervals.py`: C the docstring of M-1; R the rest (M-40).
- New test functions go at the end of a test file; several batches append to the same test file and the lead merges them.

When done: commit your work on your branch `r7-<x>` (one commit is fine; message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; do not push), and write the hand-back to `review/round_7/handbacks/r7_handback_<X>.md` inside your worktree and commit it too. Hand-back: per finding, what changed (file:line), the test, its before/after result, and the doc text; then "needs from other batches"; then the exact commands you ran and their results. Reply with one line: the findings fixed and any not fixed.

If you open a browser page with media, mute it immediately.
