# cafe: notes for agents

Two things live in this repo:
- **The cafe app** (`cafe/` minus `cafe/pm`, `run.sh`, `sync.sh`): the deployed mission predictor at http://100.108.213.121:8740. Its notes are in `PLAN.md` and `REVIEW.md`.
- **The TEPEX-C pre-mission simulator** (`cafe/pm`, `bin/run_premission`): what branch `premission-step4` is finishing. The spec is `docs/BRIEF.md`, and the brief's section 0 is the definition of done.

**Picking up the work? Read `HANDOFF.md` first:** the exact state of the review loop, what is verified and what is not, and the next steps in order.

Read these before changing anything, in this order:

| File | What it holds |
|---|---|
| `STATUS.md` | where the project stands; the missing physical inputs are at the top |
| `docs/BRIEF.md` | the spec; §5.6 is the review loop, §0 the exit conditions |
| `DECISIONS.md` | every choice, numbered; a change that reverses one amends that row |
| `docs/RUNBOOK.md` | how a lab user installs and runs it, and troubleshooting |
| `docs/PHYSICS.md`, `docs/CREDIBILITY.md` | the models and what backs each number |
| `review/round_<n>/` | each review round: the prompt, two reviewers' raw findings, `merged.md` |

## Running things

**Never run tests or pipelines on the laptop.** It has Python 3.9; the package needs 3.12 in the `cafe-pm` image on homebase.

- `./pm.sh <cmd>` syncs to the shared `~/work/cafe/pm` (without `--delete`) and runs `<cmd>` in the image. Data is `~/work/cafe/pmdata`, mounted at `/data`.
- `PMX=pm_<you> PM_CPUS=2 PM_MEM=8g bin/pmx.sh <cmd>` syncs with `--delete` to your own `~/work/cafe/pm_<you>`. Use this whenever another agent may be working.
  - `TM=<name>` runs it detached in tmux. The log goes to `~/logs/<name>.log` and ends with `rc=N`.
- Both runners split their arguments on spaces. For anything with quotes or pipes, write a script, copy it over and run it:
  `scp -i ~/.ssh/homebase_ed25519 x.sh azureuser@100.108.213.121:work/cafe/pmdata/` then `bin/pmx.sh sh /data/x.sh`.
- pytest's summary line is suppressed (`-q -q`). Read the result from the exit code, or count the result characters on the progress lines only: `grep -aE "^[.sxFE]+ *(\[ *[0-9]+%\])?$" log | sed "s/ *\[.*//" | tr -d "\n" | fold -w1 | sort | uniq -c`. A looser `^[.sxFE]` also counts traceback lines that start with `E` (round 4 read 2,250 passed for a real 2,196).
- Timings:
  - **The full suite** takes about 75 min on 6 CPUs. Run single files with `-k` while you work.
  - **`python -m cafe.pm audit <run>`** runs the whole suite with coverage. Use `--code-only` or `--ledgers-only` unless you mean it.
  - **A quick demo run:** `bin/pmx.sh python -m cafe.pm run --mission missions/tepex_c_demo.yaml --budget quick --gpus 0 --out /data/runs/<name> --fresh`, about 5 min.
- The SITL ArduCopter test in `tests/test_uas.py` depends on real time and fails now and then. Rerun it before believing a failure.

## The bar for a change

- **One regression test per fix**, which must fail before the change and pass after. Check that yourself: never weaken an assertion to get green.
- **Gates:**
  - `ruff check cafe/pm tests` (lines up to 160) and `mypy cafe/pm` (strict) clean;
  - coverage 100 % on `cafe/pm/physics`, `cafe/pm/stats`, `cafe/pm/env`, and at least 90 % on `cafe/pm` (it is about 99.9 % now);
  - mutation testing at least 85 % on physics and stats (`make mutation`, hours).
- **No banned tokens:** the audit fails on any match of `audit.BANNED` (`cafe/pm/audit.py`) outside `tests/fixtures/broken/`: to-do and fix-me markers, unimplemented stubs, stand-in values, and test skips, test helper names included. Read the pattern before you name a helper.
- **Record every decision:** a new `DECISIONS.md` row (numbered after the last) and a `CHANGELOG.md` line. A lab question goes into `QUESTIONS_FOR_LAB.md` as a sub-item with its default.
- **Honest numbers only:** a measured value or a stated assumption, never a plausible-looking one. If a check fails, the report says so.

## homebase and money

- homebase is the user's shared server; other people's services run in Docker there. Read `~/az_serv/CLAUDE.md` before doing anything beyond running cafe jobs.
- **Read `~/az_serv/docs/MONEY.md` before creating, resizing or deallocating any Azure resource.** The credits are an Azure Sponsorship with the spending limit off, so over-spend charges the owner's card. Name the resource and the cost, and get the owner's yes first.
- Never run `box down` or `box resize`: both restart or stop everything on the box.
- Docker containers for cafe use `--ulimit core=0` (both runners do). A crashing mutmut once filled the disk with core dumps.
- Disk is about 97 % full. Check `df -h /` before writing anything large.

## Working beside the lead session

One session at a time leads: it runs the review rounds, the builder batches per round, the full gate and the commits (`HANDOFF.md` says who and where it stopped). Any other agent, while a lead is active:
- **Do not edit its working tree.** Work in your own worktree and branch, then hand the branch back for merging:
  `git worktree add ../cafe-<task> -b <task> premission-step4`
- **Use only your own homebase directory**, `pm_<you>`. Do not touch `pm_int*`, `pm_q*`, `pm_r*`, `pm_rev*`, `pm_merge*`, `pm_mut`, `pmdata/runs/*`, `pmdata/dtmb5415` or `pmdata/cache`.
- **CPU share:** the box has 8 vCPU and 64 GB. Keep to 2 CPUs unless the lead says the box is free.
