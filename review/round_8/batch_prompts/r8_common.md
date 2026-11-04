# Review round 8 fixes: common rules for every batch

Findings: `review/round_8/merged.md` (M-1 .. M-26). Read the whole finding (claim, check, fix) for each one you own before you change anything, and the file map at its end. The brief is `docs/BRIEF.md`; earlier choices are in `DECISIONS.md` (rows up to 392). Read `CLAUDE.md` (the bar for a change, the banned tokens of `cafe/pm/audit.py` `BANNED`, how to run on homebase).

**Your own worktree.** Six builders work at once. Before anything else, from `/Users/aaroh/Downloads/everything/cafe`:
`git worktree add ../cafe-r8<x> -b r8-<x> premission-step4` (`<x>` is your batch letter in lower case), and work only in `/Users/aaroh/Downloads/everything/cafe-r8<x>`. Never edit the main checkout or another batch's worktree.

**Edit only the files and functions your batch owns** (your prompt lists them; a shared file names the functions you may touch). If a fix needs a change elsewhere, do not make it: write it in your hand-back under "needs from other batches", with the exact change. New tests go at the end of the test file, or in a new test function placed next to the code's existing tests, so the lead's merge stays simple.

Do not edit `DECISIONS.md`, `CHANGELOG.md`, `STATUS.md`, `QUESTIONS_FOR_LAB.md`, `docs/RUNBOOK.md`, `README.md` unless your prompt says so. Write the doc text into your hand-back instead:
- one proposed DECISIONS row per finding: `| ? | <what was decided, with numbers> | Review round 8, M-<n>. <why> |` (the lead numbers them from 393); name any row it amends;
- one CHANGELOG line per finding;
- any RUNBOOK / PHYSICS / CREDIBILITY / QUESTIONS / STATUS text, quoted exactly, with where it goes.

Every fix gets a regression test that fails before the change and passes after. Show it: run the new test on the unfixed code (a throwaway `git worktree add --detach`, or a scratch copy of the old function on homebase; **never `git stash`**: the stash list is shared by every worktree and two builders' stashes crossed in round 6) and on the fixed code, and quote both results in the hand-back. Never weaken an existing assertion to get green; if an existing test asserted the old wrong behaviour, say which and why it changed. Coverage: 100 % on `cafe/pm/physics`, `cafe/pm/stats`, `cafe/pm/env`, `cafe/pm/stage3`, and do not lower `cafe/pm` (99.96 %). `ruff check cafe/pm tests bench` (lines up to 160) and `mypy cafe/pm` (strict) clean.

Run tests on homebase only, from your worktree root:
`PMX=pm_r8<x> PM_CPUS=<n> PM_MEM=8g bin/pmx.sh python -m pytest -q -p no:cacheprovider tests/test_x.py -k ...`
(`<n>` is in your prompt.) pmx.sh syncs your worktree into your private `~/work/cafe/pm_r8<x>` and runs the `cafe-pm` image there; it splits its arguments on spaces, so for quotes or pipes write a small `sh` script, `scp -i ~/.ssh/homebase_ed25519` it to `azureuser@100.108.213.121:work/cafe/pmdata/r8<x>_<name>.sh` and run `bin/pmx.sh sh /data/r8<x>_<name>.sh`. Other people's services run on the box: never touch containers or directories that are not yours, and do not run the full test suite (the lead runs it after the merge). Whole test files of the code you changed are fine. Leave no container of yours running when you hand back (`docker ps | grep pm_r8<x>`). Disk is 97 % full: write nothing large.

Honesty: no fake results, no weakened tests, no test that only checks the code does what it does. If a fix in `merged.md` turns out wrong or impossible, say so with the evidence and do the honest alternative. Match the surrounding code style (dense, comment-light, long lines up to 160). Use the exact interface names below; a reader of a new key must accept its absence (older runs).

Memory: six builders share the box. Run tests at `PM_MEM=8g`; a whole `tests/test_cli.py`, `tests/test_pipeline.py` or `tests/test_whatif.py` may need 12g (the stage-1 memory guard), never more. Prefer node ids and `-k` while you work.

Interfaces between batches (fixed in advance). Shared files are split by function; touch no other function of a shared file:
- `cafe/pm/pipeline.py`: E the ingest checks of M-1 (`forcing_in_physical_range`, the u* note), M-2 (`_ocean_time_problem`, `ocean_time_cadence`), M-24 (the axis failure), M-33 (`_orca_covers`), M-34 (the `mission.yaml` copy); A the `L.input` calls M-4 changes (`tree_sha256`) and `ocean_store_nan_mask`.
- `cafe/pm/__main__.py`: C `_whatif` (M-3), `_report` (M-6), the `audit` subparser (M-52); K the `validate` note (M-7) and moving `_json_object` to config (M-22).
- `cafe/pm/config.py`: C `_say` (M-39); K `table_provenance` (M-16) and the shared JSON reader (M-22); V the empty-platform refusal (M-25).
- `cafe/pm/report.py`: K all but the `MODE_TEXT` entry M-14 changes, which is V's.
- `cafe/pm/physics/comms.py`: V all but the `["value"]` read of M-16, which is K's.
- `config/assumptions.yaml`: E the `ingest.*` entries of M-1; S the `why` of M-15.
- M-1: E writes the ingest check `forcing_in_physical_range` (a ledger check with that name); K's Data pedigree reads it (a failed or missing check caps the level as merged.md says).
- M-5: A adds the injectable query-time measurement and moves the speed test to the serial pass; the tests that rely on the emulator answering get a deterministic query time from A's fixture in `tests/conftest.py` (A owns conftest).
- M-44 is "not confirmed": no batch fixes it.
- New test functions go at the end of a test file; several batches append to the same test file and the lead merges them.

When done: commit your work on your branch `r8-<x>` (one commit is fine; message ends with the Co-Authored-By line of the model you are, from your own session's attribution guidance; do not push), and write the hand-back to `review/round_8/handbacks/r8_handback_<X>.md` inside your worktree and commit it too. Hand-back: per finding, what changed (file:line), the test, its before/after result, and the doc text; then "needs from other batches"; then the exact commands you ran and their results. Reply with one line: the findings fixed and any not fixed.

If you open a browser page with media, mute it immediately.
