# Round 13 reviewer prompt (BRIEF §5.6)

Four reviewers get this prompt word for word, apart from the reviewer letter, the output file and a scope line in the lead's spawn message: A reviews everything, in particular it runs round 12's regression tests (DECISIONS 638 to 690 and this round's prefix) against mutants of their fixes and reads a spread sample of 50 DECISIONS rows from 530 to 637 against the code they describe; B reviews everything, follows `docs/RUNBOOK.md` and `docs/ORCA_RUNNER.md` word for word again as a lab user would on orca, and reads line by line the look-ahead commits `7c6210a`, `e00a75b` and `2d5e6ad`, which no reviewer has read; C reviews line by line `cafe/pm/stats/`, `vv.py`, `physics/rigid.py`, then `env/conventions.py`, `env/protocol.py`, `env/bathy.py`, `env/environment.py`, `env/ocean.py` and `env/grid.py`, then `ledger.py`, `par.py` and `shares.py`, and checks the intervals numerically; D reviews line by line the stage-3 path and the app modules the pipeline imports from outside `cafe/pm`, which no round has read since round 2 to 7. None saw another's findings, took part in rounds 1 to 7, or wrote any of the code.
---

You are reviewer {A|B} of the TEPEX-C pre-mission simulator in `/Users/aaroh/Downloads/everything/cafe_main` (branch `premission-step4`, commit `cdad21a`).

**Find every way this is not perfect. Your output is only findings, each with file:line, a reproduction, and severity.**

Material:
- The brief: `docs/BRIEF.md`. Its §5.6 lists the lanes, and you cover all of them: physics, numerics, statistics, data, performance, reproducibility, robustness, documentation, honesty.
- The repo; `cafe/pm/` is the pipeline. Also read `DECISIONS.md`, `QUESTIONS_FOR_LAB.md`, `docs/RUNBOOK.md`, `docs/PHYSICS.md` and `docs/CREDIBILITY.md`.
- A real quick run of `missions/tepex_c_demo.yaml` (`--budget quick --gpus 0`) at commit `cdad21a`, which holds the fixes through round 10 (DECISIONS 530 to 573), the look-ahead (574 to 589), the round 11 prefix (590 to 592), round 11's fixes (593 to 627), its look-ahead (628 to 636), the demo's numbers (637), round 12's prefix (638 to 640), fixes (641 to 677), look-ahead, adversary and merge (678 to 689), the demo's numbers (690) and this round's prefix (691 onward). Its report, credibility report, `report.json` and every stage's ledger are in `/private/tmp/claude-501/-Users-aaroh-Downloads-everything-cafe-main/3ffc3622-1caa-4fef-bc21-ff4bf3298226/scratchpad/q13`. Large binary outputs (parquet, zarr, pkl) were left out of that copy; they are on orca at `~/cafe-worker/cafe/pmdata/runs/q13`.

How to attack it (adversarially, across everything: `cafe/pm`, `bin/`, `missions/`, `config/`, `platforms/`, `tests/`, the `Makefile`, the CI workflow and every document):
- Assume each earlier fix is wrong until you have checked it, and look for what it broke next to it.
- Recompute printed numbers yourself from the ledgers and the inputs; a number you cannot trace to a ledger, a receipt or a stated assumption is a finding.
- Feed it the BRIEF §5.6 robustness inputs and anything else hostile: missing or corrupt files, NaN, a vehicle outside the box, zero wind, a 30-day window, one vehicle, 20 vehicles, odd but valid YAML.
- Check that each test would actually fail if the behaviour it names broke; a test that passes on broken code is a finding.
- Follow the RUNBOOK as a lab user would, word for word, and report each step that does not work as written.

Rules:
- Do not edit anything in the repo. Write your findings only to `{OUT}`.
- Reproductions run on orca at 2 CPUs from a detached scratch copy of the repo (`git worktree add --detach ../cafe-rev13-{x} HEAD`, removed at the end), never by editing the repo: `PM_HOST=cafe-orca PM_RUNTIME=proot PMX=pm_rev13_{x} PM_CPUS=2 bin/pmx.sh python -m pytest -q tests/test_x.py::test_y` (arguments are split on spaces, CLAUDE.md says how to run anything with quotes), and your `pm_rev13_{x}` directory on orca removed at the end. One targeted test or a short python snippet; no full suites, no CFD beyond one toy test, no long runs.
- ORCA RULES (a shared account, other people work there; these are absolute): write only inside ~/cafe-worker, never in /tmp, ~ or dotfiles; never pkill or kill by name or user; never rm or rsync --delete outside ~/cafe-worker; never touch ~/work or ~/logs there; the tmux session named watch is the recorder, leave it alone; check /proc/loadavg before anything heavy; record process names only, never other people's command lines; never write another person's name in the repo, which is public. Run jobs from your worktree with ALL of PM_HOST=cafe-orca PM_RUNTIME=proot PMX=pm_rev13_{x} PM_CPUS=2 in front of bin/pmx.sh <cmd> (without PM_HOST it goes to homebase, which is forbidden for this work). Do not use homebase for tests, and create or start no Azure resource.
- Your own runs write only under `/data/runs/rev13_{x}*` and, where the CLI allows, keep out of the shared emulator table (`/data/emulator/train.parquet` is what every run appends to). Never run a real demo. Stop processes only by an exact pid you started, never by name. Never `rm` with a glob wider than your own names.
- If you open a browser page with media, mute it immediately.
- Earlier rounds' merged findings are in `review/round_1/merged.md` (fixes: DECISIONS 152 to 181), `review/round_2/merged.md` (fixes: DECISIONS 182 to 207; 208 and 209 came from run attempts), `review/round_3/merged.md` (fixes: DECISIONS 210 to 236) and `review/round_4/merged.md` (fixes: DECISIONS 237 to 263; 264 and 265 are follow-ups found while verifying them; 266 to 275 are the parallel stage 1) `review/round_5/merged.md` (fixes: DECISIONS 276 to 301; 302 to 307 are the lead's integration items) `review/round_6/merged.md` (fixes: DECISIONS 308 to 333; 334 to 340 are the lead's integration items) and `review/round_7/merged.md` (fixes: DECISIONS 341 to 387; 388 to 392 are the lead's integration items). A fix that does not hold, or that broke something else, is a finding. Round 8's are in `review/round_8/merged.md` (fixes: DECISIONS 393 to 447; 448 to 456 are the lead's look-ahead fixes, 457 to 460 the gate's and the close; 458 is the orca runner). Round 9's are in `review/round_9/merged.md` (fixes: DECISIONS 461 to 500; 501 to 516 are the lead's look-ahead fixes; 517 to 524 the orca runner; 525 to 529 the close). The prefix since then is DECISIONS 530 to 534 (530 the flip search's budget, P-25; 531 the run note's point count, P-29; 532 the old share logs of a gate with a smaller K, P-30; 533 the card of a NOT EXERCISED link; 534 twelve statements covered, with P-31 opened). Round 10's are in `review/round_10/merged.md` (fixes: DECISIONS 530 to 573; 574 to 589 the look-ahead and P-32; the prefix's rows from 590). Round 11's are in `review/round_11/merged.md` (prefix: DECISIONS 590 to 592; fixes: 593 to 627; 628 to 636 the look-ahead; 637 the demo's numbers). Round 12's are in `review/round_12/merged.md` (prefix: DECISIONS 638 to 640; fixes: 641 to 677; 678 to 689 the look-ahead, its adversary and the merge; 690 the demo's numbers; this round's prefix rows from 691).
- Known and already stated in the repo, so do not report these unless the repo's claim about them is wrong:
  - no GPU exists (quota 0), so the GPU path is untested;
  - the DTMB 5415 v4 three-grid study is done and does not validate the model (U_val / D 0.27 to 0.63, no iterative convergence at Fr 0.28 and 0.41), as STATUS.md says;
  - lab inputs are missing (QUESTIONS_FOR_LAB.md);
  - the golden has no provenance yet and `docs/mutation.json` does not exist yet; both are produced at code freeze;
  - `config/throughput.json`: its stage-1 costs were re-measured on 2026-11-01 (DECISIONS 272); its other rates predate the round-1 changes, and the whole file is re-measured at code freeze;
  - the receipts table is shown as stale because `runs/receipts.meta.json` was written by older code; `make receipts` reruns it at code freeze;
  - the emulator coverage gate is BRIEF 2.7's two-sided 0.90 +-0.05 on 20 to 30 held-out points, so a calibrated emulator misses it by chance about a third of the time (DECISIONS 263, 264 state this and make a miss a note, with Stage 1 answering);
  - UAS `sortie.min_profile_fraction` 1.0 and the other values marked assumed are lab questions, not findings, unless the code uses them wrongly.
  - the CI job's `make audit` step is red until `docs/mutation.json` exists (code freeze); `make ci` and `make broken` run before it (DECISIONS 291); the first hosted run of the two-pass audit (DECISIONS 334) and the SITL install (335) is in progress on the reviewed commit, so its timing is not known yet;
  - the planner's stage-1 time is a stated lower bound (DECISIONS 288), and the report prints it beside the measured time.
  - the stored slow stage-3 results (wall-model plate and channel, nest and LBM sphere grids) were made by code that round 7 changed, so the receipts show them stale until they are re-stored at code freeze (DECISIONS 348, RUNBOOK 7); the golden is re-based then too;
  - the hosted CI job: the first runs of the two-pass audit failed tests that pass on homebase (the OpenFOAM ones because the container ran as root, fixed in DECISIONS 388; others varying between runs), and the run that uploads the whole audit log is being diagnosed.
  - the USV table against the direct solve: DECISIONS and `docs/PHYSICS.md` 10.1 give the measured disagreement, not zero;
  - `cafe validate` for any file and `cafe fetch --full` are not built, and BRIEF 148 and 246 still name them: DECISIONS 442 records it (a finding only if that row is wrong);
  - the proot runner on orca: `docs/ORCA_RUNNER.md` lists what was rehearsed and what was not; memory is not limited under proot, as that file says.
  - planned times on orca come from homebase's `throughput.json` until `make bench` at code freeze (P-7); the shared disk reports 100 % used and is not ours (P-8, P-23); the stored receipts read "not run" until `make receipts --slow` at code freeze (DECISIONS 527, 528); "same seed, identical report" holds on one machine only (P-2); whether the emulator trains can depend on the clock near 100 points, and the report states what ran (P-25).
  - TAO files can change on NOAA's side between fetches (`review/round_10/moved_numbers.md`, P-40): the same code on a later TAO cache can give other moorings and other fitted priors, with the verdicts unchanged;
  - `q10` and `oq9` cannot be audited (DECISIONS 588, P-38): their ledgers name inputs whose bytes no longer exist;
  - runs made before P-32 keep the old check of the TAO manifest (P-36).
  - the golden tolerance is one member until a two-machine check exists (`acceptance.SAME_SEED_K_TOL`);
  - the receipt digest is taken after the jobs end;
  - a platform yaml is hashed whole, so any edit of one fails the audit of earlier runs by design (P-R11L0-3);
  - `FLAT_SHARE_MAX` 1 % is an assumption;
  - the stored-result digest covers every `cafe/*.py`, so any edit there makes stored CFD and SITL results stale by design (DECISIONS 678 to 689);
  - `crosscheck.json` has no writer in the repo, only `python -m cafe.receipts stamp`;
  - a resume inside one call from a server with no validator is not checked against a change in those seconds;
  - the Verdicts table keys are not prefixed because ids are one name space since M-2;
  - the owner's open calls (per-member jet draw M-10, alpha and beta from the box M-16, ocean T(z) for the glider M-19, Fresnel in place of -1 M-12, a strict empty `CAFE_WORKERS` M-23) are decided as documented and are not findings unless the documents are wrong.

## Aim this round

Two clean rounds in a row are needed to finish (BRIEF §0, §5.6). A clean round is one whose reviewers have read what no earlier round read, not one that read the same places and found nothing: a round that repeats round 12's coverage and finds little proves little. So check first what round 12 did not read (`review/round_12/merged.md`, the line "Not covered by any reviewer", and each reviewer's own list in `review/round_12/reviewer_<x>.md`), then read that. Per reviewer:

- A: everything. In particular, run round 12's regression tests (DECISIONS 638 to 690 and this round's prefix) against mutants of their fixes and say which mutants survive (a surviving mutant is a test that does not test its fix). Then a spread sample of 50 DECISIONS rows from 530 to 637, each read against the code it describes, not only its numbering (round 12 sampled 1 to 529).
- B: everything. Follow `docs/RUNBOOK.md` and `docs/ORCA_RUNNER.md` word for word again as a lab user would on orca (round 12 rewrote the TAO, receipt, golden and id rows): steps 2, 3, 5 and 7 as far as they run in under an hour at 2 CPUs; steps 1, 4 and 6 by reading only. Then line by line the look-ahead commits `7c6210a`, `e00a75b` and `2d5e6ad`, which no reviewer has read (`git show` each): receipts stamp, `damaged_run_files`, `update_command` and `--golden-mission`, `entries_read` and `item_used`, `remote.Header` identity in `cdf1_header`, `cdf1_read` and `bathy._rows`, `DEMO_DIGEST`, `box_words`, `receipts --only`, and `download` without a validator, each with hostile inputs at 2 CPUs.
- C: line by line, each formula against its cited source and `docs/PHYSICS.md`: `cafe/pm/stats/` (`rare.py`, `sampling.py`, `sensitivity.py`, `sequential.py`, `intervals.py`), `cafe/pm/vv.py` and `cafe/pm/physics/rigid.py`, which no round has read or not since round 8; then `env/conventions.py`, `env/protocol.py`, `env/bathy.py`, `env/environment.py`, `env/ocean.py` and `env/grid.py`; then `ledger.py`, `par.py` and `shares.py`. For stats, check each interval or bound numerically against an independent computation (scipy or a brute-force sum) at the n and k the demo prints.
- D: line by line the stage-3 path: `stage3/lbm.py`, `nest.py`, `freesurface.py`, `fluidx3d.py`, `refit.py`, `windows.py` and `pipeline_windows.py`, and the app modules the pipeline imports from outside `cafe/pm`, which no round has read since round 2 to 7: `cafe/planner.py` `boundary_layer`, `cafe/fea.py`, `cafe/reach.py`, `cafe/cfd.py` (what the pipeline and `dtmb5415.py` use of it), `cafe/emulator.py` and `cafe/pm/emulator.py`; then `dtmb5415.py` and `whatif.py`. Run the stage-3 and emulator tests that take under 20 minutes at 2 CPUs; quantify any physics claim with a small computation.

## Spawn lines

Each reviewer's spawn message carries the reviewer letter, the output file (`review/round_13/reviewer_<a|b|c|d>.md`) and this scope line:

- A: everything; in particular, run round 12's regression tests (DECISIONS 638 to 690 and this round's prefix) against mutants of their fixes and say which survive; then a spread sample of 50 DECISIONS rows from 530 to 637, each read against the code it describes, not only its numbering (round 12 sampled 1 to 529).
- B: everything; follow docs/RUNBOOK.md and docs/ORCA_RUNNER.md word for word again as a lab user would on orca (round 12 rewrote the TAO, receipt, golden and id rows): steps 2, 3, 5 and 7 as far as they run in under an hour at 2 CPUs; steps 1, 4 and 6 by reading only. Then line by line the look-ahead commits 7c6210a, e00a75b and 2d5e6ad, which no reviewer has read (git show each): receipts stamp, damaged_run_files, update_command and --golden-mission, entries_read and item_used, remote.Header identity in cdf1_header, cdf1_read and bathy._rows, DEMO_DIGEST, box_words, receipts --only, and download without a validator, each with hostile inputs at 2 CPUs.
- C: line by line, each formula against its cited source and docs/PHYSICS.md: cafe/pm/stats/ (rare.py, sampling.py, sensitivity.py, sequential.py, intervals.py), cafe/pm/vv.py and cafe/pm/physics/rigid.py, which no round has read or not since round 8; then env/conventions.py, env/protocol.py, env/bathy.py, env/environment.py, env/ocean.py and env/grid.py; then ledger.py, par.py and shares.py. For stats, check each interval or bound numerically against an independent computation (scipy or a brute-force sum) at the n and k the demo prints.
- D: line by line the stage-3 path: stage3/lbm.py, nest.py, freesurface.py, fluidx3d.py, refit.py, windows.py and pipeline_windows.py, and the app modules the pipeline imports from outside cafe/pm, which no round has read since round 2 to 7: cafe/planner.py boundary_layer, cafe/fea.py, cafe/reach.py, cafe/cfd.py (what the pipeline and dtmb5415.py use of it), cafe/emulator.py and cafe/pm/emulator.py; then dtmb5415.py and whatif.py. Run the stage-3 and emulator tests that take under 20 minutes at 2 CPUs; quantify any physics claim with a small computation.

Format of each finding in `{OUT}`:

```
### <A|B>-<n>. <one-line title>
severity: critical | major | minor
lane: <lane>
where: path/to/file.py:LINE (more than one if needed)
reproduction: exact command, or exact reasoning with numbers from the run, that shows the defect
why it matters: one or two sentences
```

Be concrete and checkable. A finding without a reproduction is not a finding. Do not pad with style nits; do report wrong physics, wrong statistics, an untraced number, a claim the code does not back, a runbook step that fails, and a crash on an edge-case input. Order your findings by severity. End with one line: `total: N findings (c critical, m major, n minor)`.
