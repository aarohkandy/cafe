# Round 7 reviewer prompt (BRIEF §5.6)

Both reviewers got this prompt word for word, apart from the reviewer letter and the output file. Reviewers A and B each ended with the parts they did not cover; the parts neither covered went to two more fresh reviewers, C and D, with this prompt and a scope line (in the lead's spawn message): C the line-by-line physics of `physics/usv.py`, `physics/uas.py` and `physics/glider.py` and all of `stage3/` (lbm, nest, wallmodel, freesurface, fluidx3d, windows, refit, pipeline_windows); D the readers in `env/` (hycom, ocean, orca, tao, bathy, remote), `report.py`, `credibility.py`, `receipts.py`, `dtmb5415.py`, and whether each round-6 regression test fails on a mutant of its fix. Neither saw the other's findings, took part in rounds 1 to 6, or wrote any of the code.

---

You are reviewer {A|B} of the TEPEX-C pre-mission simulator in `/Users/aaroh/Downloads/everything/cafe` (branch `premission-step4`, commit `c59c449`).

**Find every way this is not perfect. Your output is only findings, each with file:line, a reproduction, and severity.**

Material:
- The brief: `docs/BRIEF.md`. Its §5.6 lists the lanes, and you cover all of them: physics, numerics, statistics, data, performance, reproducibility, robustness, documentation, honesty.
- The repo; `cafe/pm/` is the pipeline. Also read `DECISIONS.md`, `QUESTIONS_FOR_LAB.md`, `docs/RUNBOOK.md`, `docs/PHYSICS.md` and `docs/CREDIBILITY.md`.
- A real quick run of `missions/tepex_c_demo.yaml` (`--budget quick --gpus 0`) at commit `8dc0ffc`, which holds the round-1 to round-6 fixes. Its report, credibility report, `report.json` and every stage's ledger are in `/private/tmp/claude-501/-Users-aaroh--claude-spares-spare-P6utrU/96cd665b-6853-40e7-8769-780fbfcaeebd/scratchpad/q7`. Large binary outputs (parquet, zarr, pkl) were left out of that copy; they are on homebase at `~/work/cafe/pmdata/runs/q7/`.

How to attack it (adversarially, across everything: `cafe/pm`, `bin/`, `missions/`, `config/`, `platforms/`, `tests/`, the `Makefile`, the CI workflow and every document):
- Assume each earlier fix is wrong until you have checked it, and look for what it broke next to it.
- Recompute printed numbers yourself from the ledgers and the inputs; a number you cannot trace to a ledger, a receipt or a stated assumption is a finding.
- Feed it the BRIEF §5.6 robustness inputs and anything else hostile: missing or corrupt files, NaN, a vehicle outside the box, zero wind, a 30-day window, one vehicle, 20 vehicles, odd but valid YAML.
- Check that each test would actually fail if the behaviour it names broke; a test that passes on broken code is a finding.
- Follow the RUNBOOK as a lab user would, word for word, and report each step that does not work as written.

Rules:
- Do not edit anything in the repo. Write your findings only to `{OUT}`.
- You may read files on homebase: `ssh -i ~/.ssh/homebase_ed25519 azureuser@100.108.213.121`. Other people's services run on the box and the lead's jobs share it, so do not start CFD, long runs or full test suites there. You can reproduce one targeted test or a short python snippet at 1 CPU with `PMX=pm_rev7_{a|b} PM_CPUS=1 PM_MEM=6g bin/pmx.sh python -m pytest -q tests/test_x.py::test_y`, run from the repo root. It syncs the repo into your private directory on the box. Do not touch other directories in `~/work/cafe`.
- If you open a browser page with media, mute it immediately.
- Earlier rounds' merged findings are in `review/round_1/merged.md` (fixes: DECISIONS 152 to 181), `review/round_2/merged.md` (fixes: DECISIONS 182 to 207; 208 and 209 came from run attempts), `review/round_3/merged.md` (fixes: DECISIONS 210 to 236) and `review/round_4/merged.md` (fixes: DECISIONS 237 to 263; 264 and 265 are follow-ups found while verifying them; 266 to 275 are the parallel stage 1) `review/round_5/merged.md` (fixes: DECISIONS 276 to 301; 302 to 307 are the lead's integration items) and `review/round_6/merged.md` (fixes: DECISIONS 308 to 333; 334 to 340 are the lead's integration items). A fix that does not hold, or that broke something else, is a finding.
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
