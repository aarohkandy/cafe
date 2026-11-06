# Round 10, reviewer D

Scope: the readers in `cafe/pm/env/` (hycom, ocean, orca, tao, bathy, remote), `report.py`, `credibility.py`, `receipts.py`, round 9's regression tests against mutants of their fixes (read, not executed), and the runner scripts (`bin/pmx.sh`, `pm.sh`, `bin/proot_run.sh`, `bin/proot_suite.sh`, `bin/orca_gate.sh`, `bin/orca_sync.sh`, `bin/orca_watch.sh`, `cafe/pm/shares.py`). Commit a470119 (= 8b870a6 plus the round 10 documents). Reproductions that needed Python 3.12 ran on orca at 2 CPUs from a detached worktree and `pm_rev10_d`; both are removed.

### D-1. The orca cache check compares longitudes without the antimeridian, so a cache that stops at 170 E "covers" a box that reaches 197.5 E
severity: major
lane: reproducibility / data
where: cafe/pm/pipeline.py:526-531 (`_orca_covers`), written at cafe/pm/pipeline.py:385 and 400, recorded by cafe/pm/env/orca.py:370 (`box=list(box)`)
reproduction: the manifest stores the raw padded box `(lon_min - pad, lon_max + pad, lat_min - pad, lat_max + pad)` and `_orca_covers` tests `b[0] <= box[0] and b[1] >= box[1]` on those raw numbers. On orca: `pipeline._orca_covers(dict(t0="2023-03-01 12:00:00", t1="2023-03-07 12:00:00", layout_version=2, hours3d=[], box=[150.0, 170.0, -8.0, 8.0]), t0, t1, (162.5, -162.5, -7.5, 7.5), [])` returns `True`. The request is the TEPEX-C demo box with its pad (165 E to 165 W, which `orca.box_index` reads as 162.5 E to 197.5 E). The cache holds 150 E to 170 E. `_tao_cached` and `_ocean_cached` normalise through `hycom.box360` first and do not have this flaw.
why it matters: a mission of the same name whose box is edited from a non-crossing one to a dateline-crossing one keeps the old orca cache and no fetch starts. The east 27.5 degrees have no data, vehicles there count as `left_data` failures, and no ingest check looks at the orca box.

### D-2. Six of the eight verdict cards say "certifying P(fail) < 5 % needs 73 members" and a line below say that no number of members certifies it
severity: major
lane: honesty / documentation
where: cafe/pm/report.py:1098 (`_stat_html`, the `cert` parenthesis), cafe/pm/report.py:277 (`n_certify` is set for every exercised link), cafe/pm/report.py:282-288 (`certify_statement`)
reproduction: in `q10/report/index.html` the string "(certifying P(fail) < 5 % needs" occurs 8 times and "is excluded by this ensemble" 6 times. glider_eq (15 of 64): "15 members failed of 64 members (certifying P(fail) < 5 % needs 73 members, two-sided 95 % Wilson bound)" and, four lines below it on the same card, "P(fail) < 5 % is excluded by this ensemble (lower 95 % bound 0.15): no number of members certifies it". The same holds for usv, uas and the three NO-GO links. DECISIONS 533 removed the parenthesis only for NOT EXERCISED.
why it matters: the card states a requirement ("needs 73 members") that its own next sentence says cannot be met, in the report's headline block. A reader can plan a larger `--budget` to certify a verdict that more members will never certify.

### D-3. `tao._candidates` picks the deployment "in the water" from the files of every variable, so a later start date of one variable drops the others
severity: minor
lane: data
where: cafe/pm/env/tao.py:100-109 (`before` and `lo`), called with the whole listing at cafe/pm/env/tao.py:138
reproduction: on orca: `tao._candidates([dict(date="20230101", var="WIND", ...), dict(date="20230220", var="SST", ...)], t, t + 6*86400)` with t = 2023-03-01 returns only `['SST20230220']`. The latest start at or before t0 is taken over all files (all variables, both resolutions, D and R), the window opens 10 days before that start, and `fetch_tao` filters by `var` afterwards (tao.py:138). The WIND file of the 1 Jan deployment, the only wind in the water, is never a candidate.
why it matters: one sensor re-deployed after the wind sensor drops that mooring's wind from the prior fit with no note. The real catalog may date every variable of a deployment alike (not checked, no network); the code does not rely on that anywhere it says so, and the unit test of `_candidates` (DECISIONS 490) uses one variable.

### D-4. `hycom.check_node` returns 0.0 for a node where either value is NaN, so the read-back check passes
severity: minor
lane: robustness / honesty
where: cafe/pm/env/hycom.py:820 (`worst = max(worst, abs(float(np.nanmean(got)) - want))`)
reproduction: `max(0.0, float('nan'))` is `0.0` in Python (checked). A node whose store value (`want`) is NaN (below the seafloor) or whose server answer is all NaN makes `abs(...)` NaN and `worst` stays 0.0. tests/test_hycom.py:405-409 test an agreeing node and a 1.0 K disagreement only.
why it matters: the function is the "store value vs the server" receipt (not wired into a registered receipt, PHYSICS.md 458). When it is wired in, a store with holes would be reported as an exact match.

### D-5. `proot_suite.sh` deletes the main log of another tag whose name is `<tag>_s<digits>`
severity: minor
lane: robustness
where: bin/proot_suite.sh:43-49; its own comment at 43-44 and tests/test_proot_suite.py:158-171
reproduction: in a scratch `HOME` with `cafe-worker/.cafe-worker-owned`, `logs/a_s2.log` ("running...") and `logs/a_s3.log` ("rc=0"), `logs/a_s3_s1.log`, run `sh bin/proot_suite.sh pm_x 1 a`. Afterwards `logs/` holds `a_s1.log` and `a_s3_s1.log` only: `a_s2.log` and `a_s3.log` were removed. `bin/orca_gate.sh` names the detached log of tag `a_s2` `a_s2.log`, which is exactly the `<tag>_s<i>` shape the P-30 loop deletes for i above K. The test covers `t1_s3_s5.log` and `t2_s9.log`, not the main log of a tag called `t1_s3`.
why it matters: a gate under a tag like `r9_s2` loses its tmux log (and the `rc=` line the recorder and waiters read) when a later run under `r9` uses a smaller K. The comment claims tag `a` does not touch the logs of tag `a_s3`.

### D-6. The report prints the BRIEF 2.7 acceptance limits from constants in `report.py`, labelled as read from `whatif.LIMITS`
severity: minor
lane: honesty / documentation
where: cafe/pm/report.py:904 and 914 (`lim(0.05, ...)`, `lim(0.05, ...)`, `lim(10.0, "ms")`, source string "cafe/pm/whatif.py LIMITS (BRIEF 2.7 acceptance)"); the gate uses cafe/pm/whatif.py:57 `LIMITS`
reproduction: change `LIMITS["rmse"]` in whatif.py to 0.04 and the stage judges `rmse_ok` against 0.04 while `report.json` `emulator.vehicles.*.acceptance.limits.rmse.value` still says 0.05 under the source "cafe/pm/whatif.py LIMITS". Nothing compares the two.
why it matters: a traced number whose source label points at a variable it does not read.

### D-7. The UMWM hourly file is trusted by its name; only WRF's `Times` is checked
severity: minor
lane: data
where: cafe/pm/env/orca.py:177-182 (`umwm_hour`) against cafe/pm/env/orca.py:149-151 (`wrf_hour` compares `Times` with the stamp); cafe/schemas/umwmout.json lists no time variable
reproduction: `wrf_hour` raises `Times is X, expected Y` on a mislabelled hour; `umwm_hour` reads 14 fields by byte range with no time check, and `spec_hour` likewise. Two hours served as the same file, or an output stamped at the end of an averaging period, produce a wave series shifted against the wind and nothing flags it.
why it matters: wave and wind forcing are paired by the hour label, and the UMWM half of the pairing is unverified. Whether the file carries a time to check was not examined (no network).

### D-8. `shares.py` collects only `test_*.py`; pytest's default also collects `*_test.py`
severity: minor
lane: robustness
where: cafe/pm/shares.py:20 (`rglob("test_*.py")`), the assertion at shares.py:67, pyproject.toml (no `python_files`)
reproduction: add `tests/foo_test.py` with a failing test. `pytest tests` collects it; `python -m cafe.pm.shares K out` assigns it to no share, its own "every test file is in exactly one share" assertion compares against its own glob, and `proot_suite.sh --cov` then writes `coverage.json` and passes `audit --pytest-done` without that file having run. None exists now (`find tests -name '*_test.py'` is empty).
why it matters: a latent hole in the gate's claim that the orca suite equals the suite. Also: the first suite's junit (`junit_91c9777.xml`, proot_suite.sh:60) is given to shares as a weight source and holds the times of the serial tests now deselected from their files, so `test_uas.py` and `test_emulator.py` are weighted too heavily on the first balance.

### D-9. `remote.download` resumes without checking that the server answered 206
severity: minor
lane: robustness
where: cafe/pm/env/remote.py:163 (`_open(url, have, None)` then append); compare `_read` at remote.py:65-66, which does check
reproduction: a server that ignores `Range` returns 200 and the whole body; with `have > 0` the whole file is appended to the part, `have != total` at remote.py:169 raises "bytes on disk, server says", and the doubled `.part` stays. The rerun finds `have > total`, deletes it and fails the same way. A server that ignores Range for ranged reads is caught in `_read`, `size()` and the RemoteFile path, not here.
why it matters: the download that hashes every TAO file can never finish against such a mirror, and the message does not name the cause.

### D-10. `pmx.sh` and `pm.sh` validate `PM_STOP_GRACE` and `PM_ENTRY` "because they are pasted into the remote command line" but paste `PM_CPUS` and `CAFE_MIN_FREE_GB` unchecked; a one-character `TM` is not a valid docker name
severity: minor
lane: robustness
where: bin/pmx.sh:23 (`PM_CPUS=${PM_CPUS:-8} CAFE_MIN_FREE_GB=${CAFE_MIN_FREE_GB:-60}`), pm.sh:24, bin/proot_run.sh:14-15; bin/pmx.sh:21 (`--name ${TM:-pmx_$D}`) with the TM check at pmx.sh:12
reproduction: `PM_CPUS='2,' sh bin/pmx.sh true` is sent as is; on the worker `[ "2," -le 32 ]` prints an `integer expression expected` error that the `||` turns into the "above 32 CPUs" warning, and `CAFE_WORKERS=2,` reaches the pipeline. `PM_CPUS='2;x'` is part of the remote command line. `TM=x` in the docker runtime passes the check at pmx.sh:12 and is refused by docker (names need two characters, the first alphanumeric).
why it matters: the file's own rule (DECISIONS 500, 488) is to refuse such values before anything is sent; the rule stops at two of the four variables it pastes.

### D-11. A stored slow receipt that is a JSON object without its keys raises a `KeyError` instead of the "not run" row
severity: minor
lane: robustness
where: cafe/pm/receipts.py:301-305 (`rec["code_digest"]`, `rec["date"]`, `rec["host"]`, `rec["git_sha"]`, `rec["rows"]`)
reproduction: `$CAFE_DATA/receipts/pm.emulator.json` containing `{}` passes `json_object`; the job raises `KeyError: 'code_digest'`, `collect` turns it into a row "pm.emulator raised KeyError" with the note `'code_digest'` and no command. A truncated file gets the full "not run on this code: `python -m cafe.pm receipts --slow --only ...`" row.
why it matters: the same failure (a stored result that cannot be read) gets the actionable text or a bare key name depending on how the file was damaged.

### D-12. The GO cards say a verdict "cannot be certified at n = 64" and in the same sentence give 0.04688 as the bound
severity: minor
lane: honesty
where: cafe/pm/report.py:282-288 (`certify_statement`); report.json `vehicles.glider_2n.certify_statement`, `links.usv-shore-iridium.certify_statement`
reproduction: the text is "P(fail) < 5 % cannot be certified at n = 64: 73 members (two-sided 95 % Wilson bound) are needed (with zero failures n members only show P(fail) < 3/n = 0.04688, one-sided 95 %)". 0.04688 is below 0.05, so the parenthesis reads as a certification of the same claim. The `note` of glider_2n spells out the difference (one-sided against two-sided); the statement does not.
why it matters: two numbers a reader will compare with each other, in one sentence, with the stricter rule only named in a clause.

### D-13. The fitted wind prior's citation says "WRF minus 11 moorings" over a mean that is the opposite sign
severity: minor
lane: documentation
where: cafe/pm/pipeline.py:809 (`cite`) and 822-838 (`mean=-a["speed_bias"]`, `-a["dir_bias_deg"]`)
reproduction: `q10/ingest/tao_compare.json` `ALL.speed_bias` is +0.6099 (model minus mooring, as `tao._stats` says) and `q10/ingest/priors_fitted.json` `wind_speed_bias.mean` is -0.60992 with the citation "WRF minus 11 moorings ...". The direction pair is -7.2126 and +7.2126. The sign flip is right for a correction (truth minus WRF), and neither the file nor the citation says so; I recomputed the n-weighted pooled values from the per-mooring rows and they match (0.6099, 1.4593, 2.7091, -7.2126, 24.80).
why it matters: someone who reads the prior next to its citation concludes WRF is 0.61 m/s too slow.

### D-14. `orca_watch.sh` writes its disk note once per watch and never again
severity: minor
lane: robustness
where: bin/orca_watch.sh:33 (`[ -z "$low" ] && { low=1; ... }`; `low` is never cleared)
reproduction: by reading: `low` is set at the first look under FLOOR+40 GB and nothing resets it when the disk recovers. A second dip below the threshold, which is what the recorder exists for on a shared disk, leaves only the timeline row. The `state/<job>` comparison at lines 43-46 also hides a rerun of the same tag that fails identically (`now` equals `was`), unless a look happened to see the truncated log in between (60 s apart).
why it matters: the recorder keeps "the evidence while it still exists" and records the first event only.

### D-15. `check_rendered` accepts a dropped number whenever its text occurs anywhere on the page
severity: minor
lane: documentation / honesty
where: cafe/pm/report.py:1627-1635 (`_token`, `check_rendered`)
reproduction: every node is searched as a whole token in the whole page. Values such as "0 members", "64 members" and "1" occur dozens of times (the eight failure modes alone print "0 members" seven times for glider_eq), so a section that stopped printing one of them still passes `report_html_matches_json`. The DECISIONS 476 `self_checks` run the same function.
why it matters: the check the report ledger records as "the HTML is rendered from the JSON" cannot see a dropped small number; its docstring says it catches a section that drops a number.

total: 15 findings (0 critical, 2 major, 13 minor)

Not covered: mutants were judged by reading, not run. The tests for P-25 (budget), P-30 (log removal), P-18 (junit verdict) and P-3 (reach sector) look discriminating; the one mutant I traced (`-gt` to `-ge` in the P-30 loop) is equivalent, because the run recreates the logs of shares 1 to K. The stage-3 gate readers, `bin/orca_setup.sh`, the network paths (NCSS, OPeNDAP, TAO catalog, GEBCO) and `hycom.fetch_gofs` under real failures were read but not exercised.
