You are the document integrator for review round 4 of the TEPEX-C pre-mission simulator in `/Users/aaroh/Downloads/everything/cafe` (branch `premission-step4`). The code fixes are in the working tree, uncommitted. Do not change any code under `cafe/` or `bench/`.

Inputs:
- `review/round_4/merged.md` (M-1 .. M-26);
- the four builders' hand-backs, which hold the proposed DECISIONS rows, CHANGELOG lines and PHYSICS / CREDIBILITY / QUESTIONS / RUNBOOK text: review/round_4/handbacks/r4_handback_V.md, r4_handback_C.md, r4_handback_P.md and r4_handback_R.md (same directory);
- the lead's own addition below.

Do:
1. **DECISIONS.md:** append rows 237 onward, one per finding M-1 .. M-26 in order, plus one row for the lead's addition. Number them; the last existing row is 236. Where a fix amends or reverses an earlier row (merged.md and the hand-backs say which: 216, 155, 28, 211, 131 and others), edit that row's text to point at the new row ("amended by 2xx"). Do not delete history.
2. **CHANGELOG.md:** a "Review round 4" block under Fixed, grouped by area like the round-3 block. Update the test-count line (line ~30) only with a placeholder the lead fills: write `<TESTS>` where the counts go.
3. **docs/PHYSICS.md, docs/CREDIBILITY.md, QUESTIONS_FOR_LAB.md, docs/RUNBOOK.md, README.md:** apply the hand-backs' text where they say.
   - QUESTIONS_FOR_LAB holds only BRIEF section-7 items, each with its default. Put new questions as sub-items of the existing item they belong to: UAS sortie length and minimum profile; link-loss hold; RF validity limit if it is a lab input. Add a new item only if none fits.
   - CREDIBILITY's assumed-input count rises by the new assumed platform inputs (`sortie.min_profile_fraction`, `radio.link_loss_hold_s` in `platforms/quad_uas.yaml`; check the file for others).
   - Make every number you write match the code or the hand-back's measured value.
4. **The doc-only findings:**
   - M-21: the PHYSICS windage text.
   - M-24: the RUNBOOK `pm()` wrapper and the README. Make the golden mint/pass path work for a lab user, or say exactly what it needs. Add a test in `tests/test_config_docs.py` if the fix says so.
   - M-25: the RUNBOOK "accumulate" wording, from P's hand-back.
5. **STATUS.md:**
   - the round-4 state: findings fixed, and what changed in the demo verdicts is not yet known (the q5 re-run measures it);
   - the test-count line gets `<TESTS>` for the lead;
   - keep the missing physical inputs at the top.

The lead's addition (M-3 follow-up, DECISIONS row after M-26):
"The emulator coverage gate stays BRIEF 2.7's two-sided ±0.05 around 90 %. `whatif.fit_class` now also records `coverage_chance_fail`: the probability that a calibrated emulator misses that gate by chance, P(|K/n − 0.9| > 0.05) with K ~ Binomial(n_test, 0.9). The report prints it beside the gate. Example: 0.357 at n_test 28 (pass only for K = 24, 25 or 26). A MISSED coverage gate on a 20- to 30-point hold-out is therefore weak evidence of miscalibration. The gate is not loosened, because the brief sets it. The two pipeline tests that use `seed_table(seed=4)` test table bookkeeping, not emulator quality (batch P, M-3)."
Add the matching CHANGELOG line.

Check: run `tests/test_config_docs.py` and `tests/test_audit.py` on homebase. From the repo root, run `PMX=pm_r4d PM_CPUS=2 PM_MEM=8g bin/pmx.sh python -m pytest -q -p no:cacheprovider tests/test_config_docs.py tests/test_audit.py`.
- The summary line is suppressed. Count the result characters in the output (`.`, `F`, `E`) or check the exit code.
- They must pass. The banned-token scan (TODO, FIXME, XXX, placeholder, ...) also scans docs: check whether `<TESTS>` trips it. If it does, use the text "(count pending)" instead.
- Do not run anything else on homebase; the lead's full test run is going there now.
- If you open a browser page with media, mute it immediately.

Do not commit. Reply with one line: the DECISIONS rows added (first-last), the earlier rows amended, and the doc-test result.
