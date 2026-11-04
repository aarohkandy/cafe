# Round 8: the lead's findings from the hosted CI runs

Source: GitHub Actions runs 41749372640 (commit 8dc0ffc) and 41769469026 (commit 4634dc0, the first with the whole audit log uploaded as the `audit-log` artifact). On homebase every test named below passes.

### L-1. Whether the emulator answers depends on the speed of the machine the tests run on, so 10 tests fail on the hosted runner
severity: major
lane: robustness
where: cafe/pm/whatif.py:436-457 (`fit_class`: median of 20 wall-clock queries against `LIMITS["query_ms"]` 10 ms); cafe/pm/emulator.py:372-377 (the receipt's median of 50 queries); tests/test_whatif.py:338, 507, 647, 663, 681; tests/test_pipeline.py:1590, 1755, 1779; tests/test_emulator.py:66, 137
reproduction: run 41769469026, audit.log: `test_query_under_10_ms_and_format` reads min of 5 rounds 10.96 ms (11.3, 13.3, 14.0, 11.7) on the 4-CPU runner under `-n 4`; `fit_class` then marks the glider emulator unused ("missed BRIEF 2.7 acceptance (query time)"), so `test_an_emulated_what_if_carries_the_distance_and_the_interval` gets `Stage 1` instead of `EMULATED`, `test_the_what_if_falls_back_to_stage_1_out_of_range_and_says_why` gets the query-time reason instead of "no track", `test_a_uas_flip_is_answered_without_a_median_track` a TypeError on the missing emulator, and the pipeline and receipt tests likewise. On homebase the same query takes about 3 ms.
why it matters: a test of the emulator's logic passes or fails with the host's speed and load, so CI cannot be green on a hosted runner whatever the code; the one test that should measure the speed is mixed with the parallel load.

### L-2. `test_make_ci_ends_with_the_ledger_audit_of_the_run_it_made` fails whenever it runs under `make audit`
severity: minor
lane: robustness
where: tests/test_audit.py:~495-501
reproduction: run 41769469026, audit.log: the last line of the nested `make -n ci` output is "make[1]: Leaving directory '/app'" (MAKELEVEL is set because the audit runs inside `make audit`), not `python -m cafe.pm.audit --ledgers-only runs/ci`. homebase's gate runs pytest directly, so it never sees it.
why it matters: the CI's own audit step fails one test by construction.

### L-3. Coverage of `cafe/pm/physics` is 99.8 % on the hosted runner and 100 % on homebase, and the uploaded log does not say which lines
severity: minor
lane: reproducibility
where: .github/workflows/premission.yml (uploads `audit.log` only); cafe/pm/audit.py coverage gate
reproduction: runs 41749372640 and 41769469026: "AUDIT FAIL: coverage cafe/pm/physics: 99.8 % < 100 %"; homebase's two-pass audit on the same code gives 1,858 of 1,858.
why it matters: a gate that differs between machines with no way to see why cannot be closed; CI should upload `coverage.json` (and the missed lines should be found and either covered on every machine or explained).
