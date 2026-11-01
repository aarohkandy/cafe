You are the merger for review round 4 of the TEPEX-C pre-mission simulator in `/Users/aaroh/Downloads/everything/cafe` (branch `premission-step4`, commit `fd91422`, code at `23e9a95`). You did not write the code or either review.

Inputs: `review/round_4/reviewer_a.md` (13 findings) and `review/round_4/reviewer_b.md` (14 findings), made with the prompt in `review/round_4/PROMPT.md` against the quick run copied to `~/work/cafe/pmdata/runs/q4 (on homebase)` (big binaries on homebase at `~/work/cafe/pmdata/runs/q4/`).

Task: write `review/round_4/merged.md` in exactly the form of `review/round_3/merged.md` (read it first: header paragraph saying what you checked and how, severity / status / lane per finding, claim / check / fix, Critical / Major / Minor sections, M-1.. numbering, ranking inside a severity, every source id in exactly one merged finding). For each finding:
- check the claim yourself by reading the cited code and the run files; say "confirmed", "partly" or "not confirmed" with the evidence (numbers, file:line). Reviewers can be wrong: a finding that does not hold is kept with status "not confirmed" and no fix.
- merge duplicates (A-9 and B-6 look like the same reach-map defect; check).
- change a severity only with a stated reason. Major = changes a verdict, a printed number, or a gate result, or crashes the run; minor = otherwise.
- write a concrete fix: what changes, in which files, the message text where a message changes, and the regression test that must fail before the fix. Prefer the smallest honest fix; where the code cannot do better with the available inputs, the fix is wording (say what the claim becomes). Check that a fix does not contradict an earlier round's DECISIONS row (rounds 1-3: DECISIONS 152-236); if it reverses one, say which.
- for each fix, list the files it touches, so the lead can split the work into batches that do not share files.

Rules: do not edit anything except `review/round_4/merged.md`. You may read files on homebase (`ssh -i ~/.ssh/homebase_ed25519 azureuser@100.108.213.121`), and you may run a short targeted test or python snippet at 1 CPU with `PMX=pm_merge4 PM_CPUS=1 PM_MEM=6g bin/pmx.sh python ...` from the repo root (it syncs the repo to your own directory and runs the cafe-pm image; it splits its arguments on spaces, so for anything with quotes write a script, scp it to `azureuser@100.108.213.121:work/cafe/pmdata/<name>.sh` and run `pmx.sh sh /data/<name>.sh`). No full test suite, no runs, no CFD, nothing outside your own directory. The laptop's python is 3.9 and cannot import the package. If you open a browser page with media, mute it immediately.

When done, reply with one line: counts by severity and by status, and the number of merged findings.
