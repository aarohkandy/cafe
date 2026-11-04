You are the document integrator for review round 6 of the TEPEX-C pre-mission simulator in `/Users/aaroh/Downloads/everything/cafe` (branch `premission-step4`). The five code batches are merged there; the lead's integration edits are in the working tree, uncommitted. Do not change any code under `cafe/`, `bench/` or `tests/` except `tests/test_config_docs.py` where a doc fix says so. Work in that checkout (no worktree); the lead is not editing documents meanwhile.

Inputs:
- `review/round_6/merged.md` (M-1 .. M-26, and its file map);
- the five hand-backs with proposed DECISIONS rows, CHANGELOG lines and RUNBOOK / PHYSICS / CREDIBILITY / QUESTIONS / STATUS text: `review/round_6/handbacks/r6_handback_{V,C,S,P,W}.md`. Where a hand-back says it deviated from merged.md (V: M-4 keeps the old gust-hour set and drops the hours outside the data, M-10 `cap_cycles` >= 1 and `MISSION_REQUIRED`; P: M-2 0.0031 GB per deg^2 day from one measured point and the re-plan at the end of ingest; S: M-13 needed no whatif change; C: M-9 `radius_km` minimum 0.01 km), the code is what it says; write the docs for the code. W's hand-back holds two lead items (L-W1, L-W2) with their rows;
- the lead's integration items below.

Do:
1. **DECISIONS.md:** append rows from 308, one per finding M-1 .. M-26 in order (a wording-only finding still gets its row), then one per lead item: L-W1, L-W2 (from W's hand-back), then L3 to L5 below. Where a fix amends an earlier row (merged.md's file map: 37 by M-25, 85 by M-3, 260 by M-19, 281 by M-2, 284 by M-4, 286 by M-15, 288 by M-17, 294 by M-7 and M-8, 296/297 by M-23; 291 by L-W1; the hand-backs may name more), add "(amended by 3xx)" to that row's text. Do not delete history.
2. **CHANGELOG.md:** a "Review round 6" block under Fixed, grouped by area like the round-5 block, with the DECISIONS range; the test-count line gets "(count pending)" in place of the numbers.
3. **docs/RUNBOOK.md, README.md, docs/PHYSICS.md, docs/CREDIBILITY.md, QUESTIONS_FOR_LAB.md, STATUS.md:** apply the hand-backs' text where they say (S already edited CREDIBILITY and PHYSICS for M-18, W already added the SITL install step and `CAFE_WORK` to both `pm()` wrappers and README's SITL provenance; check consistency, do not redo). V's hand-back gives the PHYSICS.md:672 and :841 replacements. W's gives RUNBOOK text for M-14, M-20, M-21 and asks for a `tests/test_config_docs.py` assertion that RUNBOOK names `runs/acceptance`. P's and C's give RUNBOOK text for M-2, M-6, M-7, M-23.
   - QUESTIONS_FOR_LAB holds only BRIEF section-7 items with defaults; new questions are sub-items.
   - Every number you write must match the code or a hand-back's measured value; RUNBOOK commands must run as written.
4. **The doc-only finding M-25:** PHYSICS.md and DECISIONS row 37 on `theta_e`, PHYSICS.md on "the battery alone", the comment pointing to `cafe/pm/env/wrf.py` and anything else merged.md lists (if the comment is in code, change only that comment).
5. **STATUS.md:** round 6 state: 26 findings (0 critical, 6 major, 20 minor) fixed, each with a regression test; q7 measures what changed in the demo verdicts (not yet known); the test-count line "(count pending)"; keep the missing physical inputs at the top; the CI section says the audit's test step is now two passes and the SITL binary is installed in CI from ArduPilot's published build, and that no hosted run has timed it yet.
6. **HANDOFF.md section 0:** one short paragraph: round 6 fixes merged from the five branches, DECISIONS rows written, gate and q7 next; batch W was finished by the lead; never use `git stash` (CLAUDE.md).

The lead's integration items (each a DECISIONS row and a CHANGELOG line):
- L3: `cafe/pm/env/tao.py` `fetch_tao` reads its old manifest with `orca.read_json`, so an empty or truncated TAO manifest is no record and the files are checked again (M-8 sent it back there, where `json.loads` still raised). Test: `tests/test_tao.py::test_an_empty_or_truncated_manifest_is_fetched_again_not_a_traceback`.
- L4: the emulator ledger's share note says "stage 1b's share included, since no vehicle was refit" where it said "incl. stage 1b, which was a copy" (S's M-17 need). Test: an assertion in `tests/test_pipeline.py::test_the_emulator_ledger_has_the_planned_and_measured_variant_seconds_and_no_self_comparing_check`.
- L5: CLAUDE.md: never use `git stash` (the stash list is shared by every worktree; two builders' stashes crossed in round 6; nothing was lost).

Check: run `PMX=pm_r6d PM_CPUS=1 PM_MEM=6g bin/pmx.sh python -m pytest -q -p no:cacheprovider tests/test_config_docs.py tests/test_audit.py` from the repo root. The summary line is suppressed; read the exit code. They must pass, including the banned-token scan over docs. Run nothing else on homebase. If you open a browser page with media, mute it immediately.

Do not commit. Reply with one line: the DECISIONS rows added (first-last), the earlier rows amended, and the doc-test result.
