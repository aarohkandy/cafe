# Round 1 reviewer prompt (BRIEF §5.6)

Both reviewers got this prompt word for word, apart from the reviewer letter and the output file. Neither saw the other's findings or wrote any of the code.

---

You are reviewer {A|B} of the TEPEX-C pre-mission simulator in `/Users/aaroh/Downloads/everything/cafe` (branch `premission-step4`).

**Find every way this is not perfect. Your output is only findings, each with file:line, a reproduction, and severity.**

Material:
- The brief: `docs/BRIEF.md`. Its §5.6 lists the lanes, and you cover all of them: physics, numerics, statistics, data, performance, reproducibility, robustness, documentation, honesty.
- The repo; `cafe/pm/` is the pipeline. Also read `DECISIONS.md`, `QUESTIONS_FOR_LAB.md`, `docs/RUNBOOK.md`, `docs/PHYSICS.md` and `docs/CREDIBILITY.md`.
- A real quick run of `missions/tepex_c_demo.yaml` (`--budget quick --gpus 0`, about 9 min on homebase). Its report, credibility report, `report.json` and every stage's ledger are in `{RUN}`. Large binary outputs (parquet, zarr, pkl) were left out of that copy; they are on homebase at `~/work/cafe/pmdata/runs/q1/`.

Rules:
- Do not edit anything in the repo. Write your findings only to `{OUT}`.
- You may read files on homebase: `ssh -i ~/.ssh/homebase_ed25519 azureuser@100.108.213.121`. The box is busy with a long CFD study and a mutation-testing run, so do not start containers, CFD or full test suites there. You can reproduce one targeted test or a short python snippet at 1 CPU with `PMX=pm_rev_{a|b} PM_CPUS=1 PM_MEM=6g {PMX} python -m pytest -q tests/test_x.py::test_y`, run from the repo root. It syncs the repo into your private directory on the box. Do not touch other directories in `~/work/cafe`.
- If you open a browser page with media, mute it immediately.
- Known and already stated in the repo, so do not report these unless the repo's claim about them is wrong:
  - no GPU exists (quota 0), so the GPU path is untested;
  - the DTMB 5415 three-grid study is being rerun with the v4 recipe, and its v3 results are not used;
  - lab inputs are missing (QUESTIONS_FOR_LAB.md).

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
