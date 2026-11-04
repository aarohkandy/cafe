# Reviewer A, round 8: findings on commit 95085cb (run q8 at 0a0509c)

All probes ran on homebase at 1 CPU in `~/work/cafe/pm_rev8_a` (read-only on `pmdata`). `ruff check cafe/pm tests` and `mypy cafe/pm` pass there. Not a finding: reports render, hashes in the q8 ledgers all match, stage 1 is bit-identical at CAFE_WORKERS=1 and 3.

### A-1. The RUNBOOK has no "define a mission" section and never says which verdicts to trust, though BRIEF exit condition 5 and the README say it does
severity: major
lane: documentation
where: docs/RUNBOOK.md (headings at lines 6, 20, 65, 74, 96, 121, 156, 169, 220), README.md:32, docs/BRIEF.md:37
reproduction: `grep -n -i "trust" docs/RUNBOOK.md` prints nothing. `grep -n "uas_airborne\|required_fraction\|links:\|local_solar_time\|schemas/mission" docs/RUNBOOK.md` prints nothing. `git grep -l uas_airborne -- '*.md'` finds only DECISIONS/CHANGELOG/review files. The RUNBOOK's step 4 lists vehicle-task rules a `validate` run enforces, but nowhere says what a `links` entry takes (`kind`, `when`, `radio`/`modem`, `required_fraction`), what `sorties`, `ship`, `shore`, `box`, `verdict` mean, or that the reference is `cafe/schemas/mission.json`. README.md:32 says the RUNBOOK "says which verdicts to trust".
why it matters: BRIEF 0.5 asks that a lab member with no knowledge of the code can "define a mission" and "know which verdicts to trust" from the RUNBOOK; a person editing the demo YAML has to read the JSON schema and the code, and the README states a thing the document does not do.

### A-2. Two assumed modem inputs that move the acoustic verdict are in no assumed-input list; `hangar --platform modems` says "0 of 0 values assumed"
severity: major
lane: honesty
where: platforms/modems.yaml:9 (`anchor_margin_db: 3.0 # assumed`), :12 (`valid_range_factor: 10.0 # assumed`); cafe/pm/__main__.py:245; cafe/pm/physics/comms.py (`implementation_loss_db`, `valid_range_m`); docs/PHYSICS.md:796 calls `valid_range_factor` "**assumed**"
reproduction: `grep -c "anchor_margin\|valid_range_factor" q8/report/credibility.json q8/report/report.json` gives 0 and 0 (q8 = the scratchpad copy). Its modems entries are only the two `modems.yaml:modems.benthos_atm960` / `whoi_micromodem` rows. `python -m cafe.pm hangar --platform modems` prints `modems (modem table): provenance OK, 0 of 0 values assumed`, although STATUS.md and the RUNBOOK say `hangar` "lists every value still marked assumed". Effect of the 3 dB (`anchor_margin_db`), run on homebase with `comms.acoustic_link(d, 'benthos_atm960', 'MF', wind=5)` at d = 2, 3, 4, 4.5, 5, 6, 8 km: margins with the anchor at 0 / 3 / 6 dB are `11.7 5.5 0.0 -2.6 -5.1 -9.8 -18.9` / `14.7 8.5 3.0 0.4 -2.1 -6.8 -15.9` / `17.7 11.5 6.0 3.4 0.9 -3.8 -12.9`, so the range at which the link closes moves between about 4.0 and 5.1 km (the vendor says "at least 4 km").
why it matters: BRIEF 0.4 says every assumed input is listed, not hidden. A glider-ship link inside 10 km is decided by a number the credibility report does not show (the demo's own links are 555 and 633 km and do not reveal it).

### A-3. `report --run` ends in a raw `JSONDecodeError` traceback (exit 1) for a truncated `summary.json`, `refit.json`, `priors_fitted.json`, `tao_compare.json`, `windows.json` or emulator JSON, against the RUNBOOK troubleshooting row and DECISIONS (round 7, M-34)
severity: major
lane: robustness
where: cafe/pm/report.py:74 and :926, cafe/pm/credibility.py:156 (bare `json.loads(p.read_text())`); cafe/pm/__main__.py:163 `_json_object` is used only by `plan.json` (:185) and the `whatif` path (:264-270); docs/RUNBOOK.md troubleshooting row "`error: ...: not a JSON object` (from `report` or `whatif`)"
reproduction: copy `/data/runs/q8` to a scratch directory, cut a file, run `python -m cafe.pm report --run <copy>`. Results (all measured): `plan.json` cut to 200 bytes gives `rc=2 error: ...: not a JSON object (...); run it again (--fresh)` as documented. `stage1b/summary.json` cut to 300 bytes, `refit/refit.json` to 20, `ingest/priors_fitted.json` to 50, `ingest/tao_compare.json` to 50, `stage3/windows.json` to 10, `windows/windows.json` to 10, `emulator/flip.json` to 50, `checkpoints/ingest/ledger.json` to 100: each gives `rc=1` and a Python traceback ending `json.decoder.JSONDecodeError`. The same cut of `summary.json` under `whatif` gives the documented `error:` line, so the fix landed in one of the two commands the row names. An edited `summary.json` with an empty `vehicles` object or one vehicle removed gives `KeyError: 'glider_eq'` / `KeyError: 'usv'`.
why it matters: the RUNBOOK promises a one-line `error:` with the remedy for exactly these files; a truncated file (full disk, killed run) is the commonest corruption and the lab user gets a traceback.

### A-4. The GO rule's interval term is not scaled to the mission's own `verdict.go`: with go = 0.99 nine members and no failure give GO
severity: major
lane: statistics
where: cafe/pm/stats/intervals.py:51 (`LO_SUCCESS_GO = min(0.75, go)`), :132-133 (`verdict`); cafe/schemas/mission.json `verdict.go` (any value in (0, 1])
reproduction: on homebase, `intervals.set_thresholds(0.99, 0.5)` then `intervals.verdict(0, n)['verdict']` for n = 8, 9, 10, 32, 64 gives MARGINAL, GO, GO, GO, GO, with the 90 % Wilson upper bound on P(fail) = 0.253, 0.231, 0.213, 0.078, 0.041 (the user asked for P(success) at least 0.99, i.e. P(fail) at most 0.01). With go = 0.95 and n = 64: k_fail = 3 (P(fail) 0.047, upper bound 0.112) is GO. With the demo's go = 0.9, 0 failures of 9 is GO (upper bound 0.231). Only the stopper (`interval_region`, 95 % upper bound at most `P_FAIL_GO`) scales with go, so the stopper and the verdict disagree for go above 0.9: the ensemble never stops early as GO, yet the capped run prints GO.
why it matters: the mission's `verdict` block is advertised as the PIs' own thresholds (QUESTIONS 5); for a stricter go the printed GO does not mean P(success) >= go at any stated confidence, and the report's rule line ("90 % Wilson upper bound ... at most 0.25") hard-codes a tolerance 25 times the stated one.

### A-5. `whatif` never checks that `--mission` is the mission the `--run` directory was made from
severity: major
lane: reproducibility
where: cafe/pm/__main__.py:252-297 (`_whatif` loads `a.mission`, takes the baseline verdicts from `run/stage1b/summary.json`, tracks from `res.pkl`, and never opens `run/mission.yaml`)
reproduction: edit the demo so `glider_2n` swims south from lat -2 (`task.heading_to: 180`, `deploy.lat: -2.0`), then `python -m cafe.pm whatif --mission <edited> --run /data/runs/q8 --shift 6h --vehicle glider_2n`. Output (measured): `glider_2n: GO (P(fail) 0.000) -> GO (P(fail) 0.031) (0.010 to 0.090)  [Stage 1, n = 64 (...)]`. "GO (0.000)" is the old mission's glider; "GO (0.031)" is the edited mission's shifted glider. No warning.
why it matters: a baseline and a candidate from two different missions are printed as one before-and-after, which is exactly the comparison what-if exists to make. The report stage reads `run/mission.yaml`; `whatif` should compare its hash.

### A-6. A truncated checkpoint ledger crashes `run` (resume) and the audit with a raw traceback, instead of rerunning the stage or reporting a problem
severity: minor
lane: robustness
where: cafe/pm/ledger.py:157-160 (`done`), cafe/pm/audit.py:110 (`ledger_problems`): unguarded `json.loads(p.read_text())`
reproduction: write `{"stage": "ingest", "ok": tr` to `checkpoints/ingest/ledger.json`; `ledger.done(run, 'ingest', 'x')` and `audit.ledger_problems(run)` both raise `JSONDecodeError`. `python -m cafe.pm.audit --ledgers-only <run with checkpoints/stage1/ledger.json cut to 300 bytes>` prints a traceback (exit 1).
why it matters: the audit exists to name broken ledgers and a broken ledger is its crash; a resumed `run` should treat an unreadable ledger as "stage not done".

### A-7. Whether Bellhop ran (and its version), and the versions of pandas, pyarrow, arlpy and others, are in no ledger, no stage hash and not in `code_digest`
severity: minor
lane: reproducibility
where: cafe/pm/ledger.py:22 (`LIBS` has no pandas, pyarrow, arlpy, jsonschema, pyyaml, netCDF4, capytaine); cafe/pm/pipeline.py:49-62 (`code_digest`), :113 (`self.hash`); cafe/pm/physics/comms.py:263 (`bellhop_available`); requirements.txt:2 ("transitive packages still float", pandas among them)
reproduction: `grep -il bellhop q8/checkpoints/*/ledger.json q8/report/report.json q8/stage1/summary.json` prints nothing; the stage-1 ledger `versions` block lists 13 libraries and no Bellhop. `comms._bellhop_dir()` decides whether ambiguous acoustic samples are re-done with Bellhop (stage1.py:541-555), so installing `bellhop.exe` after a run and rerunning the same command resumes the Thorp-only stage 1 without a rerun, and two machines with the same `code_digest` can give different link verdicts.
why it matters: BRIEF 5.5 puts library versions and everything that decides an output into the ledger; the link's own `method` label records it in the report, but the resume logic and the ledger do not.

### A-8. `ship_antenna_height_m` in `platforms/quad_uas.yaml` is a listed assumed input, but the mission-level `usv-uas-rf` link ignores it (hard-coded 10.0)
severity: minor
lane: honesty
where: cafe/pm/stage1.py:486 (`f(s.get("antenna_height_m", 10.0))`) against :280 (`mission["ship"].get("antenna_height_m", ra["ship_antenna_height_m"])`); platforms/quad_uas.yaml:140
reproduction: `grep -rn "ship_antenna_height_m" cafe/pm` shows one reader, the in-sortie `lost_link` hook (`_uas_links`). A mission that omits `ship.antenna_height_m` and a platform file changed to 20 m: the UAS sortie link uses 20 m, `evaluate_link`'s `_pos` for the `usv-uas-rf` link keeps 10 m. `hangar --platform quad_uas` and the credibility report list `ship_antenna_height_m = 10.0` as an assumed input every UAS verdict depends on, and say "replace with the lab's".
why it matters: editing the documented input changes one link judgement and not the other; the two ends of the same geometry disagree.

### A-9. The mission schema leaves `ship.antenna_height_m` and `ship.transducer_depth_m` unbounded above (and antenna 0 allowed)
severity: minor
lane: robustness
where: cafe/schemas/mission.json (ship block: `"minimum": 0` only); contrast docs/RUNBOOK.md line 115 ("Numbers outside the model's range are refused too")
reproduction: `load_mission` accepts `ship.antenna_height_m: 1000`, `0`, and `transducer_depth_m: 20000` (probe on homebase: all `OK`). A 1000 m mast gives a 130 km radio horizon and a link GO for the USV 111 km away; antenna 0 makes the two-ray field null (-240 dB margin).
why it matters: the same round-6 rule (M-9) that bounds `radius_km` and `lost_after_h` was not applied to the ship, and a typo (15 written as 150) silently turns a NO-GO link into GO.

### A-10. Unquoted `local_solar_time: 14:00` (and `5e0`-style numbers) are refused with a message that does not say why
severity: minor
lane: documentation
where: cafe/pm/config.py `_say` (handles unquoted timestamps and empty keys only); docs/RUNBOOK.md (never mentions `local_solar_time`)
reproduction: replace `local_solar_time: "14:00"` by `local_solar_time: 14:00` in the demo: `vehicles/3/sorties/local_solar_time: 840 is not of type 'string'` (YAML 1.1 reads HH:MM as a base-60 integer, 14*60 = 840). `radius_km: 5e0` gives `'5e0' is not of type 'number'` (PyYAML reads it as a string). `id: no` gives `False is not of type 'string'`. `local_solar_time: 09:30` is accepted, `12:30` is not.
why it matters: the natural way to write a time of day is refused with a number the user never typed and no hint to quote it, in the one field the RUNBOOK does not explain.

### A-11. BRIEF 2.9 and 6 name `cafe validate` for "any file" and `cafe fetch --window ... --full`; neither exists and no DECISIONS row records dropping them
severity: minor
lane: honesty
where: cafe/pm/__main__.py:44-60 (`validate --mission` only; `fetch --mission` and `--out`/`--fresh` only); docs/BRIEF.md:148 and the demo-mission paragraph of section 6
reproduction: `python -m cafe.pm validate -h` shows `--mission` only; `grep -n "\-\-full\|full-file" DECISIONS.md STATUS.md docs/RUNBOOK.md README.md QUESTIONS_FOR_LAB.md CHANGELOG.md` is empty. DECISIONS 19 makes a non-206 ranged read an error, so there is no full-file fallback either.
why it matters: the brief's documented fallback when byte ranges stop working is absent, and the build's own record does not say so.

### A-12. 13 tests in `tests/test_cli.py` fail on any machine that gives the container under about 10 GB
severity: minor
lane: reproducibility
where: tests/test_cli.py (the `report` and `whatif` tests, e.g. :222, :268, :300, :388-468, :596); cafe/pm/budget.py memory refusal
reproduction: `docker run --memory 6g ... python -m pytest -q tests/test_cli.py` gives 13 failures, each with `error: stage 1 needs about 9 GB for the environment of a 6-day window and 0.9 GB per worker, and 6 GB is available`; the same file with `--memory 28g` passes (rc=0).
why it matters: the CLI tests read the real host memory through the planner before their monkeypatched engine runs, so a laptop-class CI runner or a lab machine with 8 GB sees a red suite for a reason unrelated to the code.

### A-13. RUNBOOK section 7 lists `--ledgers-only` and `--mutation-record` as options of `audit`, but `python -m cafe.pm audit` accepts only `--code-only`
severity: minor
lane: documentation
where: docs/RUNBOOK.md (section 7 paragraph "`audit` takes run directories as arguments ..."); cafe/pm/__main__.py (the `audit` subparser has `runs` and `--code-only`)
reproduction: `python -m cafe.pm audit --ledgers-only /data/runs/q8` gives `python -m cafe.pm: error: unrecognized arguments: --ledgers-only` (exit 2). The options exist on `python -m cafe.pm.audit`, which only the Makefile calls.
why it matters: a lab user following the RUNBOOK's wording with the `pm python -m cafe.pm audit` form that the same document uses elsewhere gets a usage error.

### A-14. "The planner never overruns stage 1" (RUNBOOK 3) is not backed by an estimate the code itself calls a lower bound, and the emulator stage ran over its share in q8
severity: minor
lane: performance
where: docs/RUNBOOK.md section 3 ("The planner never overruns stage 1: it halves the batch down to 4 members, else refuses"); cafe/pm/budget.py; q8/plan.json `stage1_s_basis`
reproduction: q8 plan.json `stage1_s` = 52.7 s ("a lower bound"); the stage-1 ledger note says "64 members in 109 s" and the ledger `wall_s` is 117.2 s, 2.2 times the plan (the STATUS table says the q5 plan was 2.05 times low). The emulator ledger: `wall_s` 270.4 s against `plan.emulator.share_s.no_refit` 240 s; its variants took 190 s measured against 158 s planned and a `train_budget` of 168 s. The run as a whole used about 480 s of the 1200 s, so no gate failed.
why it matters: a mission whose lower-bound estimate is above about 45 % of the stage-1 share can overrun although the document promises it cannot; the guarantee is as strong as a lower bound allows.

### A-15. docs/LICENSES.md omits pymavlink (LGPL-3.0), which `cafe/pm/physics/uas.py` imports and the image ships
severity: minor
lane: documentation
where: docs/LICENSES.md (tables "Default numerical stack" and "Programs we run"); cafe/pm/physics/uas.py:728; requirements.txt (`pymavlink==2.4.50`)
reproduction: `importlib.metadata.metadata('pymavlink')['License']` inside the cafe-pm image prints `LGPLv3`; `grep -i pymavlink docs/LICENSES.md` is empty. The file also lists none of xarray, zarr, statsmodels, scikit-learn, pyyaml, jsonschema, shapely, networkx, pyarrow, though it opens "Licences of what cafe/pm uses".
why it matters: the file's section 2 tells a deployer which components make a redistributed image carry source-offer duties; the one LGPL library the pipeline links is not among them.

total: 15 findings (0 critical, 5 major, 10 minor)
not covered: ingest from the live servers (no network fetch), stage 3 LES/FEA/free-surface physics, the GPU path, `make ci`/`make audit`/full-suite timing and mutation scores, the emulator's training and conformal coverage, the DTMB study, and a quantitative re-derivation of the USV VPP, glider flight and UAS controller physics beyond reading them and probing them on analytic environments
