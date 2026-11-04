You are the merger for review round 8 of the TEPEX-C pre-mission simulator in `/Users/aaroh/Downloads/everything/cafe_main` (branch `premission-step4`, commit `46567a1`, code at `0a0509c`). You did not write the code or either review.

Inputs: `review/round_8/reviewer_a.md` (15 findings), `reviewer_b.md` (12), `reviewer_c.md` (15), `reviewer_d.md` (17) and the lead's `lead_findings.md` (L-1 to L-3, from the hosted CI runs; check them like the others), made with the prompt in `review/round_8/PROMPT.md` against the quick run copied to `/private/tmp/claude-501/-Users-aaroh--claude-spares-spare-P6utrU/96cd665b-6853-40e7-8769-780fbfcaeebd/scratchpad/q8` (big binaries on homebase at `~/work/cafe/pmdata/runs/q8/`).

Task: write `review/round_8/merged.md` in exactly the form of `review/round_7/merged.md` (read it first: header paragraph saying what you checked and how, severity / status / lane per finding, claim / check / fix, Critical / Major / Minor sections, M-1.. numbering, ranking inside a severity, every source id (A-, B-, C-, D-, L-) in exactly one merged finding). For each finding:
- check the claim yourself by reading the cited code and the run files; say "confirmed", "partly" or "not confirmed" with the evidence (numbers, file:line). Reviewers can be wrong: a finding that does not hold is kept with status "not confirmed" and no fix.
- merge duplicates (A and B reviewed everything, C the physics and stage 3, D the readers, the report, the receipts and the round-7 tests; check every pair for overlaps).
- change a severity only with a stated reason. Major = changes a verdict, a printed number, or a gate result, or crashes the run; minor = otherwise.
- write a concrete fix: what changes, in which files, the message text where a message changes, and the regression test that must fail before the fix. Prefer the smallest honest fix; where the code cannot do better with the available inputs, the fix is wording (say what the claim becomes). Check that a fix does not contradict an earlier round's DECISIONS row (rounds 1-7: DECISIONS 152-392); if it reverses one, say which.
- for each fix, list the files it touches, so the lead can split the work into batches that do not share files.

Rules: do not edit anything except `review/round_8/merged.md`. You may read files on homebase (`ssh -i ~/.ssh/homebase_ed25519 azureuser@100.108.213.121`), and you may run a short targeted test or python snippet at 1 CPU with `PMX=pm_merge8 PM_CPUS=1 PM_MEM=6g bin/pmx.sh python ...` from the repo root (it syncs the repo to your own directory and runs the cafe-pm image; it splits its arguments on spaces, so for anything with quotes write a script, scp it to `azureuser@100.108.213.121:work/cafe/pmdata/<name>.sh` and run `pmx.sh sh /data/<name>.sh`). No full test suite, no runs, no CFD, nothing outside your own directory. The laptop's python is 3.9 and cannot import the package. If you open a browser page with media, mute it immediately.

When done, reply with one line: counts by severity and by status, and the number of merged findings.

Work steadily: check each claim with the smallest read or snippet that settles it, and do not sit idle waiting on anything (the round-4 merger took 6 h of wall time). A test run you start on homebase must finish before you reply, and leave no container of yours running.

Never use `git stash` (CLAUDE.md).
