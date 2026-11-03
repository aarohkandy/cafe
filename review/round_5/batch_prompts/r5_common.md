# Review round 5 fixes: common rules for every batch

Findings: `review/round_5/merged.md` (M-1 .. M-26). Read the whole finding (claim, check, fix) for each one you own before you change anything, and the file map at its end. The brief is `docs/BRIEF.md`; earlier choices are in `DECISIONS.md` (rows up to 275). Read `CLAUDE.md` (the bar for a change, the banned tokens of `cafe/pm/audit.py` `BANNED`, how to run on homebase).

**Your own worktree.** Five builders work at once. Before anything else, from `/Users/aaroh/Downloads/everything/cafe`:
`git worktree add ../cafe-r5<x> -b r5-<x> premission-step4` (`<x>` is your batch letter in lower case), and work only in `/Users/aaroh/Downloads/everything/cafe-r5<x>`. Never edit the main checkout or another batch's worktree.

**Edit only the files and functions your batch owns** (your prompt lists them; a shared file names the functions you may touch). If a fix needs a change elsewhere, do not make it: write it in your hand-back under "needs from other batches", with the exact change. New tests go at the end of the test file, or in a new test function placed next to the code's existing tests, so the lead's merge stays simple.

Do not edit `DECISIONS.md`, `CHANGELOG.md`, `STATUS.md`, `QUESTIONS_FOR_LAB.md`, `docs/RUNBOOK.md`, `README.md` unless your prompt says so. Write the doc text into your hand-back instead:
- one proposed DECISIONS row per finding: `| ? | <what was decided, with numbers> | Review round 5, M-<n>. <why> |` (the lead numbers them from 276); name any row it amends;
- one CHANGELOG line per finding;
- any RUNBOOK / PHYSICS / CREDIBILITY / QUESTIONS / STATUS text, quoted exactly, with where it goes.

Every fix gets a regression test that fails before the change and passes after. Show it: run the new test on the unfixed code (a `git stash`, or a scratch copy of the old function) and on the fixed code, and quote both results in the hand-back. Never weaken an existing assertion to get green; if an existing test asserted the old wrong behaviour, say which and why it changed. Coverage: 100 % on `cafe/pm/physics`, `cafe/pm/stats`, `cafe/pm/env`, `cafe/pm/stage3`, and do not lower `cafe/pm` (99.94 %). `ruff check cafe/pm tests bench` (lines up to 160) and `mypy cafe/pm` (strict) clean.

Run tests on homebase only, from your worktree root:
`PMX=pm_r5<x> PM_CPUS=<n> PM_MEM=8g bin/pmx.sh python -m pytest -q -p no:cacheprovider tests/test_x.py -k ...`
(`<n>` is in your prompt.) pmx.sh syncs your worktree into your private `~/work/cafe/pm_r5<x>` and runs the `cafe-pm` image there; it splits its arguments on spaces, so for quotes or pipes write a small `sh` script, `scp -i ~/.ssh/homebase_ed25519` it to `azureuser@100.108.213.121:work/cafe/pmdata/r5<x>_<name>.sh` and run `bin/pmx.sh sh /data/r5<x>_<name>.sh`. Other people's services run on the box: never touch containers or directories that are not yours, and do not run the full test suite (the lead runs it after the merge). Whole test files of the code you changed are fine. Leave no container of yours running when you hand back (`docker ps | grep pm_r5<x>`). Disk is 97 % full: write nothing large.

Honesty: no fake results, no weakened tests, no test that only checks the code does what it does. If a fix in `merged.md` turns out wrong or impossible, say so with the evidence and do the honest alternative. Match the surrounding code style (dense, comment-light, long lines up to 160). Use the exact interface names below; a reader of a new key must accept its absence (older runs).

Interfaces between batches (fixed in advance):
- M-10: batch P writes `value_hi95` (m/s, the 95 % upper bound) beside `value` in the persistent wind prior's entry of `ingest/priors_fitted.json`; batch S's report prints it when present ("upper bound").
- M-13: batch P writes, at the top level of `emulator/design.json`, `variant_planned_s` (float, the planned seconds per variant run) and `variant_wall_s` (list of floats, the measured wall seconds of the variant runs in order); `plan.json` gets `stage1_s_basis` (string). Batch S's report machine block reads those, `plan.json` `stage1_s` and `checkpoints/stage1/ledger.json` `wall_s`, and prints "planned X s, measured Y s".
- M-6: `plan.json` gets `workers_by_cpu`, `workers_by_memory` (None when memory is unknown) and keeps `workers` (batch P).
- M-15: `ledger.machine()` gets `workers` (batch P).
- M-7 (batch S alone): the stage-1 summary gets `subgrid_switches` = {name: {"on": bool, "defaulted": bool}} for the five switches. Decision: the two switches that defaulted off (turbulence, gust fronts) default on, like the other three.
- M-10 decision: the prior's `value` stays the fitted estimate (BRIEF 5.2); the upper bound is reported, and replacing it is a QUESTIONS_FOR_LAB sub-item with the point estimate as the default.
- M-19 and M-1 both touch `cafe/pm/env/environment.py`: batch C only `GriddedEnv.__init__` (the open guard); batch V everything else there.

When done: commit your work on your branch `r5-<x>` (one commit is fine; message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; do not push), and write the hand-back to `review/round_5/handbacks/r5_handback_<X>.md` inside your worktree and commit it too. Hand-back: per finding, what changed (file:line), the test, its before/after result, and the doc text; then "needs from other batches"; then the exact commands you ran and their results. Reply with one line: the findings fixed and any not fixed.

If you open a browser page with media, mute it immediately.
