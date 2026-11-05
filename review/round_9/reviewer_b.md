### B-1. `report --run` (RUNBOOK step 5 re-render) makes `audit` fail on the same run
severity: major
lane: reproducibility
where: cafe/pm/__main__.py:178-197 (`_report`), cafe/pm/audit.py:154-159, docs/RUNBOOK.md step 5 ("Re-render a finished run with `pm python -m cafe.pm report --run runs/quick`")
reproduction: copy the q9 run to a dir named q9 on the burst VM; `python -m cafe.pm audit --ledgers-only <dir>` gives `audit: 0 problem(s)`; then `python -m cafe.pm report --run <dir>`; audit again gives 4 x `AUDIT FAIL: q9: stage report: output .../report/{index.html,report.json,credibility.html,credibility.json} changed since the stage ran`. `_report` calls `report.write` and never updates checkpoints/report/ledger.json.
why it matters: the documented way to re-render a run breaks the audit chain of that run, so `make audit` / acceptance on a re-rendered run fail with no hint that the re-render is the cause.

### B-2. Emulator stage ran 2.05x over its wall-clock share; RUNBOOK says 12 %
severity: major
lane: performance
where: docs/RUNBOOK.md step 4 ("the emulator stage ran 12 % over its share (270 s of 240 s)"), cafe/pm/pipeline.py (emulator stage), checkpoints/emulator/ledger.json of q9
reproduction: q9 emulator ledger `wall_s` = 492.85 s against the 240 s share. Variant runs measured 71+80+61+70 = 283 s against 26.3 s planned each (2.7x); the other ~210 s is outside the variants (flip search "88 s of Stage 1 (planned cost)", training), unbudgeted. Total compute stages 821 s of 1200 s, so quick still fits, but with 380 s margin, and a slower machine or the "plan above 45 % of the share" case the documentation allows breaks the 20 min.
why it matters: a stated budget guarantee and the doc's measured overrun (12 %) are both wrong for the reviewed commit; the flip search is not held by the share.

### B-3. Plan/report claim "7 distinct points per vehicle class in one run"; the run produced 5
severity: minor
lane: honesty
where: report.json machine.describe / plan note ("6 variants of 26 s + the base mission"), emulator ledger notes
reproduction: ledger note "killed: the variant runs spent the emulator stage's whole wall-clock share (240 s) before variant v4 of 6"; training table afterwards: glider 10 rows, usv 5, uas 5 (2 classes of 4 vehicles x 5 missions = 5 points). The report's header still prints the plan's 7.
why it matters: the run summary states a count the run did not reach, without saying 2 variants were cut.

### B-4. A link with zero required samples reports verdict GO
severity: minor
lane: statistics
where: cafe/pm/stage1.py:576-620 (link evaluation, `uas_airborne`), report index badge
reproduction: ci_fixture with `vehicles[uas].launch_rules.max_mean_wind_ms: 0.5` and `sorties.every_days: 400` (UAS never launches: uas NO-GO, mode no_sortie_flown 16/16). Link `usv-uas-rf`: `need_count_median 0`, `frac_median 1.0`, `granularity_ok false`, p_fail 0, verdict GO (16 members, 0 failed). Report row reads "GO undecided: granularity".
why it matters: a link that was never tested gets a headline GO and P(fail)=0 in a table beside a NO-GO UAS; the only warning is a badge.

### B-5. `whatif --drop` of every vehicle is accepted
severity: minor
lane: robustness
where: cafe/pm/whatif.py (drop handling), cafe/schemas/mission.json (`vehicles` minItems 1)
reproduction: `whatif --mission missions/tepex_c_demo.yaml --run <q9> --drop uas --drop usv --drop glider_eq --drop glider_2n` prints "dropped uas, usv, glider_eq, glider_2n; links removed: ..." and exits 0, while a mission with `vehicles: []` is refused by `validate`.
why it matters: the what-if accepts a mission the tool itself calls invalid.

### B-6. Audit of a run copied to a differently named directory says "chain broken"
severity: minor
lane: documentation
where: cafe/pm/audit.py:54-64 (`_resolve`), :160-161
reproduction: `cp -r runs/q9 runs/quick` then `audit --ledgers-only runs/quick`: 8 problems "stage refit: does not record the stage3 ledger as an input (chain broken)" etc. `_resolve` only maps a recorded path through a directory with the audited run's name (q9); the ledgers hold absolute paths.
why it matters: a renamed or archived run reads as tampered; the message does not say the cause is the directory name, and RUNBOOK does not say a run must keep its directory name.

### B-7. Box with lon_min == lon_max gets a misleading error
severity: minor
lane: robustness
where: cafe/pm/config.py (box checks)
reproduction: demo mission with `box: {lon_min: -165.0, lon_max: -165.0, ...}`: error is "point (-170.0, 0.0) is outside the mission box", not "empty box".
why it matters: a degenerate box is not named as such (a lat reversal is).

### B-8. Reach-map caption contradicts its title
severity: minor
lane: documentation
where: report.py caption of the map ("where the vehicle can get to within the horizon") vs legend "reach within 24 h of the deploy" / "fastest routes within 24 h"
reproduction: read report/index.html map section of q9; the horizon is 6 days, the reach is 24 h (glider_eq 30.06 km <= (0.23+0.248) m/s x 86400 s = 41 km, consistent with 24 h).
why it matters: the caption reads as the whole window's reach.

Checked and held (no finding): ~95 hostile mission variants through `load_mission` (all refused with a named field or accepted sensibly); `plan` on 20 vehicles, 1 vehicle, 30-day window, whole-globe box, UAS every 400 d; `make ci` (rc 0, `audit: 0 problem(s)`, about 6 min at 2 CPUs); ci_fixture runs with a never-launching UAS (B-4) and with a USV-only/duplicate-waypoint/2**70-seed mission (verdicts, no crash, traceability clean); `whatif` bad inputs (`nanh`, `9999d`, `5 deg up`, none) all exit with a clear error; Wilson/verdict arithmetic (9 members clear the 0.75 bound, 8 do not; 4/32 interval 0.057-0.251) recomputed by hand and right; `test_a_uas_flip_is_answered_without_a_median_track` passes on the burst VM (flaky by its own gate, DECISIONS 457).

total: 8 findings (0 critical, 2 major, 6 minor)
