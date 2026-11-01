# Review round 4 fixes: common rules for every batch

Repo: `/Users/aaroh/Downloads/everything/cafe`, branch `premission-step4`, at `fd91422` + the merged file. The findings are in `review/round_4/merged.md` (M-1 .. M-26). Read the whole finding (claim, check, fix) for each one you own before you change anything. The brief is `docs/BRIEF.md`; earlier choices are in `DECISIONS.md` (rounds 1 to 3: rows 152 to 236).

Four builders work at the same time in the same working tree, each on its own files. **Edit only the files your batch owns** (listed in your prompt) and the tests for them. If a fix needs a change in a file you do not own, do not make it: write it in your hand-back under "needs from other batches", with the exact change.

Do not edit `DECISIONS.md`, `CHANGELOG.md`, `STATUS.md`, `QUESTIONS_FOR_LAB.md`, `docs/PHYSICS.md`, `docs/CREDIBILITY.md` (batch G owns docs; see its prompt). Instead write your doc text into your hand-back file:
- one proposed DECISIONS row per finding: `| ? | <what was decided, with numbers> | Review round 4, M-<n>. <why> |` (the lead numbers them);
- one CHANGELOG line per finding, under "Fixed";
- any PHYSICS / CREDIBILITY / QUESTIONS / RUNBOOK text, quoted exactly, with where it goes.

Every fix gets a regression test that fails before the change and passes after (say in the hand-back which test, and that you saw it fail first). Coverage gates: 100 % line coverage on `cafe/pm/physics`, `cafe/pm/stats`, `cafe/pm/env`, and keep `cafe/pm` as a whole at 100 % if you can (gate 90 %). `ruff check cafe/pm tests` and `mypy cafe/pm` (strict) must be clean.

Run tests on homebase, never on the laptop. From the repo root:
`PMX=pm_r4<x> PM_CPUS=2 PM_MEM=8g bin/pmx.sh python -m pytest -q -p no:cacheprovider tests/test_x.py -k ...`
(`<x>` is your batch letter in lower case.) pmx.sh syncs the working tree into your private directory `~/work/cafe/pm_r4<x>` and runs the `cafe-pm` image there; it splits its arguments on spaces, so for anything with quotes or pipes write a small `sh` script, `scp -i ~/.ssh/homebase_ed25519` it to `azureuser@100.108.213.121:work/cafe/pmdata/<name>.sh` and run `pmx.sh sh /data/<name>.sh`. Use at most 2 CPUs. Other people's services run on the box: never touch containers or directories that are not yours (other batches' `~/work/cafe/pm_r4*`, `pmdata/runs`, `pmdata/dtmb5415`), and do not run the full test suite (the lead runs it after integration). Targeted test files only. Because the tree is shared, another batch's half-done edit can break an import in your run; if so, wait a minute and rerun, and never "fix" their file.

Honesty: no fake results, no weakened tests, no tests that only check the code does what it does. If a fix in `merged.md` turns out wrong or impossible, say so in the hand-back with the evidence and do the honest alternative. Match the surrounding code style (dense, comment-light, long lines up to 160).

Do not commit. When done, write the hand-back to `review/round_4/handbacks/r4_handback_<X>.md`: per finding, what changed (file:line), the test, its before/after result, and the doc text; then "needs from other batches"; then the exact test commands you ran and their results. Reply with one line: the number of findings fixed and any not fixed.

If you open a browser page with media, mute it immediately.
