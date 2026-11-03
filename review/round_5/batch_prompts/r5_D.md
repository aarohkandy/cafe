You are the document integrator for review round 5 of the TEPEX-C pre-mission simulator in `/Users/aaroh/Downloads/everything/cafe` (branch `premission-step4`). The five code batches are merged there; the lead's integration edits are in the working tree, uncommitted. Do not change any code under `cafe/`, `bench/` or `tests/` except `tests/test_config_docs.py` where a doc fix says so. Work in that checkout (no worktree); the lead is not editing documents meanwhile.

Inputs:
- `review/round_5/merged.md` (M-1 .. M-26, and its file map);
- the five builders' hand-backs with the proposed DECISIONS rows, CHANGELOG lines and RUNBOOK / PHYSICS / CREDIBILITY / QUESTIONS / STATUS text: `review/round_5/handbacks/r5_handback_{V,C,S,P,W}.md`. Where a hand-back says it deviated from merged.md (P: M-5 per-day scale, M-6 env_gb as the larger of 1.5 GB/day and the cache size, M-13 variant timings in the emulator ledger; V: M-9 test; S: M-11 95 % bound), the code is what it says; write the docs for the code;
- the lead's integration items below.

Do:
1. **DECISIONS.md:** append rows from 276, one per finding M-1 .. M-26 in order (a finding that is only wording still gets its row), then one row per lead item below. Where a fix amends an earlier row (merged.md's file map lists them: 103 by M-7, 114 and 211 by M-2, 195 by M-14, 252 by M-9, 266 by M-6, 271/272 by M-5, 84 by M-15, 97 by M-16, 69 by M-11; the hand-backs may name more), add "(amended by 2xx)" to that row's text. Do not delete history.
2. **CHANGELOG.md:** a "Review round 5" block under Fixed, grouped by area like the round-4 block, with the DECISIONS range; the test-count line (`1,908 def test_ ...`) gets "(count pending)" in place of the numbers for the lead to fill.
3. **docs/RUNBOOK.md, README.md, docs/PHYSICS.md, docs/CREDIBILITY.md, QUESTIONS_FOR_LAB.md, STATUS.md:** apply the hand-backs' text where they say (S already edited PHYSICS and CREDIBILITY in its branch; check they are consistent with the rest, do not redo them).
   - QUESTIONS_FOR_LAB holds only BRIEF section-7 items, each with its default; new questions are sub-items (M-10: whether the persistent wind prior should use its 95 % upper bound; default the point estimate).
   - Every number you write must match the code or a hand-back's measured value. RUNBOOK commands must run as written.
4. **The doc-only findings:** M-24 (RUNBOOK's "`--budget ci` on the demo is refused by design": say what really happens, from merged.md's check), M-25 (Bellhop: RUNBOOK install step and `make install`'s scope, as merged.md's fix says; add the `tests/test_config_docs.py` check if it says so), and the M-26 lines S did not cover (`CHANGELOG.md:289`, `QUESTIONS_FOR_LAB.md:99` per S's hand-back).
5. **STATUS.md:** round 5 state: 26 findings (0 critical, 6 major, 20 minor) fixed, each with a regression test; q6 measures what changed in the demo verdicts (not yet known); the test-count line gets "(count pending)"; keep the missing physical inputs at the top; the stage-1 memory model (M-6) and the CI job order (M-16) in their sections.
6. **HANDOFF.md section 0:** one short paragraph: round 5 fixes merged from the five branches, DECISIONS rows written, gate and q6 next.

The lead's integration items (each a DECISIONS row and a CHANGELOG line):
- L1: `bench/throughput.py stage1` times with stdout sent to stderr and prints only the JSON: importing xlb makes warp print a deprecation notice on stdout, so `throughput.py stage1 > out.json` was not JSON and `tests/test_bench.py` failed when the file ran alone. Test: `test_stage1_prints_only_its_json_on_stdout_whatever_a_library_prints_while_it_times`.
- L2: the platform loaders (`glider`, `usv`, `uas` `load_platform`, `comms` radios table) read through `config._yaml`, so a repeated key or an octal number in a platform file is refused like in a mission (M-18 covered only missions). Tests in `tests/test_platform_required.py`.
- L3: `python -m cafe.pm plan` passes the memory and environment size to `budget.plan` like `run` does (M-6), so `plan` shows and refuses what `run` would.
- L4: the report reads the emulator variant timings from `checkpoints/emulator/ledger.json` (`variant_planned_s`, `variant_wall_s`), where batch P put them to keep timings out of the hashed `design.json` (row 139).

Check: run `PMX=pm_r5d PM_CPUS=1 PM_MEM=6g bin/pmx.sh python -m pytest -q -p no:cacheprovider tests/test_config_docs.py tests/test_audit.py` from the repo root. The summary line is suppressed; read the exit code. They must pass, including the banned-token scan over docs. Run nothing else on homebase. If you open a browser page with media, mute it immediately.

Do not commit. Reply with one line: the DECISIONS rows added (first-last), the earlier rows amended, and the doc-test result.
