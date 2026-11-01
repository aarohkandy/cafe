# Round 4, reviewer B

Tree reviewed: `23e9a95` (repo copy at `c1faf3f`, same `cafe/`), run `q4`. Probes were run on homebase at 1 CPU (`PMX=pm_rev4_b`) from a private copy of the repo; nothing in the repo was edited. Probe sources: `/private/tmp/claude-501/-Users-aaroh-Downloads-everything-cafe/7a1f0993-224f-4f35-ab3f-f6f1853168a1/scratchpad/repo_b/probe/`.

No critical findings. Four major, ten minor.

---

### B-1. A UAS sortie is cut off by the 1200 s return-to-ship timer from the mission's own mean wind, flies 7 of 8 pattern waypoints (4 of 8 at 10 m/s), and is still scored as a success; the battery margin gets better, not worse, above 7 m/s
severity: major
lane: physics / honesty
where: `platforms/quad_uas.yaml:114` (`time_limit_factor` 1.0), `cafe/pm/physics/uas.py:122` (`t_lim = duration_s * time_limit_factor`), `cafe/pm/physics/uas.py:50` (`FLAGS`: no mode for an incomplete pattern), `cafe/pm/report.py:54` ("the UAS verdict rests on battery alone below about 12 m/s of wind")
reproduction: real platform file, uniform wind, no turbulence or gust, `uas.fly_sortie(AnalyticEnv(wind=(-w, 0)), ship=lambda t: zeros(2), 0.0, M=1, origin=(-165, 0), plat=uas.load_platform(), heading_deg=90.0)` (upwind legs, as the platform's `leg_heading: upwind`), then count which of the 8 waypoints of `uas.flux_pattern` the 1 Hz track came within 25 m / 12 m of. Probe `probe/uas_wind2.py`, output:

| wind m/s | waypoints reached | FLY s | t_end s | energy Wh | soc_end | flags |
|---|---|---|---|---|---|---|
| 0 | 8/8 | 1127 | 1186 | 40.3 | 0.329 | none |
| 4.5 | 8/8 | 1155 | 1215 | 40.5 | 0.326 | none |
| 5.3 (the demo's mean 10 m wind) | 7/8 | 1200 | 1260 | 41.7 | 0.305 | none |
| 7 | 6/8 | 1200 | 1493 | 48.4 | 0.185 | battery_reserve |
| 9 | 5/8 | 1200 | 1281 | 40.1 | 0.336 | none |
| 10 | 4/8 | 1200 | 1352 | 41.5 | 0.313 | none |

The nominal pattern takes 1127 s of flight, so the 1200 s timer leaves 6 % slack; any headwind of about 5 m/s or more ends the flux profile early (the failsafe sends the aircraft home with legs unflown). No failure mode records that, `landed` is true, and the sortie counts as a pass. At 9 and 10 m/s the aircraft finishes with more charge than at 5.3 or 7 m/s because it flew half the profile. Related run numbers: the q4 report says the horizontal-force demand sits beyond the 35 deg tilt clamp for a median 480 s of each sortie (demand/clamp 2.15 median), which is the same effect seen from the controller.
why it matters: the UAS "GO" (3 of 32 failed, all by battery) describes a sortie that, at the mission's own median wind, does not deliver the 4-level flux profile it was sent for, and the only failure that can fire has the wrong sign in strong wind. The sentence "rests on battery alone" is also not the whole story: it rests on the tool not counting a truncated profile as a failure.

---

### B-2. `make broken` (the CI step for BRIEF 5.3's "broken configuration must fail a receipt") passes with a configuration that is not broken
severity: major
lane: honesty / reproducibility
where: `cafe/pm/receipts.py:438-441` (`failed = counts["fail"] > 0`; "failed N receipts, as required"), `Makefile:37-38`, `.github/workflows/premission.yml:18-19`, `docs/RUNBOOK.md:141`
reproduction: on homebase, from the repo, a neutral overlay `probe/neutral.yaml` containing `waves: {direction_convention: umwm}` (the default, i.e. nothing broken), then `python -m cafe.pm receipts --only pm.stage3.wallmodel --broken probe/neutral.yaml --json /tmp/rb.json`. Output: "broken configuration probe/neutral.yaml: waves.direction_convention = umwm ... 6 pass, 2 fail ... the broken configuration failed 2 receipts, as required"; the exit code is 0. The two failures are the wall-model rows that RUNBOOK section 7 says fail by design (L09). In CI (`docker run ... cafe-pm make broken`, no `/data`) every slow group is `<group>:not_run` (`app.fea`, `pm.emulator`, `pm.physics.uas.slow`, RUNBOOK 7 point 1), so the baseline already has failing receipts and `make broken` exits 0 whatever the overlay says.
why it matters: the required CI check cannot fail for the reason it names. `acceptance` has the specific check (`acceptance.py:334-338`, baseline against broken, failures in `pm.env.wave_direction`), but the CI job and the RUNBOOK step do not use it, so a receipt suite that no longer sees a wrong wave-direction convention would still show a green "broken configuration fails" step.

---

### B-3. The emulator's coverage gate scores exact 0 and 1 as misses, so a correctly calibrated emulator is reported at 78 % against a 90 % nominal and `coverage_ok` is false
severity: major
lane: statistics
where: `cafe/pm/emulator.py:209` (`coverage = mean((lo <= y) & (y <= hi))` in the P scale), `cafe/pm/emulator.py:45-47` and `:106-107` (`_logit`, `_tf`: the model and its conformal scores live on a clipped logit), `cafe/pm/whatif.py:423` (`coverage_ok`)
reproduction: `probe/emu_cov2.py` on homebase. Train `Emulator(FEATURES, ["p_fail"])` on 150 rows of `synthetic_table` features with `p_fail ~ Binomial(32, p)/32` (the quick-budget ensemble size); test on 400 fresh rows drawn the same way (exchangeable with the calibration rows). Results: 22.25 % of the test rows have `p_fail` exactly 0 or 1; `em.score(test)["coverage"]["p_fail"]` = 0.7775 (what the pipeline gates on, limit |cov - 0.90| <= 0.05); the same intervals mapped back to the logit scale with the clipped target the model was calibrated on cover 0.9275; on the rows with 0 < y < 1 they cover 1.000; rows with y == 0 are covered 0.0 (smallest `lo` among them 1.8e-05, because a sigmoid never reaches 0). The mean interval width is 0.50 in P, so the intervals that do pass are close to uninformative.
why it matters: at n = 32 many vehicles have exactly 0 or 32 failures (in q4: glider_2n 0 of 32, usv-shore-iridium 0, three links 32 of 32), so on a real table the hold-out gate would reject a good emulator, and the conformal claim "guaranteed coverage" (BRIEF 2.7) is checked with a statistic that cannot reach nominal. The coverage receipt passes only because the synthetic table is built with 512-member estimates, where exact 0/1 are rare.

---

### B-4. The member current-error field is not periodic in longitude: it jumps at 180 deg, inside the TEPEX-C box (160E to 160W)
severity: major
lane: numerics / robustness
where: `cafe/pm/env/perturb.py:71` (`x = np.radians(lon) * R_EARTH * cos(lat)` with the raw longitude), called from `PerturbedEnv.current` at `:174`; the vehicles wrap their longitude to [-180, 180) (`glider.py:417`, `usv.py:556`)
reproduction: `python3 -c` (no jax needed): `from cafe.pm.env.perturb import Field; f = Field(20230301, [0,1,2,3], "current_speed_field", 100e3)`; evaluate at lat 0 for lon 179.99 and -179.99 (about 2 km apart): member 1 gets -2.74 and +0.437 (difference 3.18 sigma), member 3 gets 1.91 and -0.022, against differences of 0.005 to 0.05 for two points 2 km apart at -170.0 / -169.98. The configured correlation length is 100 km.
why it matters: a glider or USV that crosses the date line gets an unrelated current error from that step on (a speed factor and a direction rotation of up to three sigma), and vehicles on opposite sides of 180 get independent errors although "common random numbers" are claimed for inter-vehicle consistency. The demo mission stays west of 180, so no q4 number is affected; the lab's actual campaign box straddles it.

---

### B-5. "Which mode failed first is not known (res.pkl is not available)" is printed for vehicles that had no failure, with res.pkl present
severity: minor
lane: honesty
where: `cafe/pm/report.py:343` (`first_fail_mode=None if r is None else _first_mode(r)`; `_first_mode` returns None when nobody failed), `cafe/pm/report.py:975-976`
reproduction: q4 `report/index.html`, vehicle glider_2n (0 of 32 failed): "What drives the failures: which mode failed first is not known (res.pkl is not available)". The same page draws glider_2n's member tracks ("glider_2n: median track 120 values deg", "member 0 120 values"), which come from `stage1b/res.pkl`, and `stage1b:output:res.pkl` is a hash-checked receipt in the same report.
why it matters: the sentence blames a missing file for something that is simply "no member failed"; a reader will think the checkpoint is broken.

---

### B-6. The USV reach map feeds speed over ground into a router that adds the current again, and labels it "through the water"
severity: minor
lane: physics / honesty
where: `cafe/pm/report.py:564-566` (`speed = run_speed` = `path_speed(res["vehicles"][vid])`, described "which already includes the drift in the currents"), `:577-613` (`legacy._dijkstra(flow, ..., speed, ...)` adds `flow` to that speed), `report.json` `reach.vehicles.usv.speed`
reproduction: q4 report: "usv: farthest reachable cell 93.57 km ... at 0.6613 m/s through the water (median mean path speed over ground of the Stage-1 ensemble, which already includes the drift in the currents), largest current on the grid 0.5853 m/s". 0.6613 is the median SOG of the Stage-1 tracks (it is the `speed` block's `sog_ms_median` basis), the Zermelo router treats the number as swim speed and adds the grid's current on top.
why it matters: the current is counted twice in the reach polygon, and the printed label states the opposite of what the number is. PHYSICS 10.2 gives the demo mission's speed through the water as about 0.72 m/s, so the figure is not the through-water number either; it is close to it only by coincidence of this mission.

---

### B-7. A link to a glider with `when: always` (RF) or any Iridium link to a glider is scored as if the glider were on the surface at every record
severity: minor
lane: physics / robustness
where: `cafe/pm/stage1.py:484` (`need = live.copy()` for Iridium, no vehicle state), `cafe/pm/stage1.py:375-391` (`_pos`: height = `alt + antenna_m`, glider antenna 0.5 m whatever the depth), `cafe/pm/config.py:162` (an Iridium link with `when: surfacing` is refused)
reproduction: `probe/irid.py` calls `stage1.evaluate_link` for `kind: iridium, a: g, b: shore, when: always, required_fraction: 0.9` with a glider whose `surfaced` array is all False: "records the link was required at: [145 145 145 145], fraction worked: [1. 1. 1. 1.], success: [True True True True]". `load_mission` accepts such a mission (fuzz case "iridium glider-shore" ACCEPTED) and refuses the form that would express "at surfacing".
why it matters: glider-to-shore Iridium is the standard glider link; the only form `validate` accepts gives a GO for a glider that never surfaces. The demo mission only has the USV on Iridium, so q4 is unaffected.

---

### B-8. The RUNBOOK `pm()` wrapper sets no `CAFE_GIT_DIRTY` and the image has no `git`, so a lab user can never mint or pass the golden
severity: minor
lane: documentation / reproducibility
where: `docs/RUNBOOK.md:35-36` and `README.md:22-23` (wrapper passes only `CAFE_GIT_SHA`), `cafe/pm/ledger.py:38-49` (`git_dirty()` falls back to the env var, else None), `cafe/pm/acceptance.py:221-232` (`provenance_problems`: a golden with `dirty: null` has no provenance), `pm.sh` (the only place that sets `CAFE_GIT_DIRTY`, and it is hard-wired to homebase)
reproduction: `PMX=... pmx.sh which git` on homebase prints nothing, exit 1 (no git in `cafe-pm`). Every ledger of q4 shows `"git_dirty": null`. With the RUNBOOK wrapper `pm python -m cafe.pm acceptance ... --update-golden` writes `dirty: null`, and `golden_diff` then fails with "cannot tell whether the checkout was clean ... run it from a git checkout or through ./pm.sh", which a lab user does not have.
why it matters: RUNBOOK section 7 tells the lab to mint the golden with `./pm.sh` (homebase only); the generic wrapper in section 1 cannot produce a passing acceptance run, and the ledgers of any run made with it cannot say whether the tree was clean.

---

### B-9. Windage: PHYSICS.md and the platform file say 0.01, Stage 1 always uses 1.8 to 2.3 %; the 0.01 is a dead "assumed input" in the credibility count
severity: minor
lane: documentation / honesty
where: `docs/PHYSICS.md:590` ("surfaced: current + 0.01 x 10 m wind (windage assumed)"), `platforms/seaglider.yaml:36` (`windage` 0.01, `assumed: true`), `cafe/pm/stage1.py:349` (`windage=subgrid.windage_fraction(seed, members)`), `config/subgrid.json:23` (0.018 to 0.023)
reproduction: `grep -n windage` in the four places; `GliderSim.__init__` (`glider.py:265`) takes the platform value only when `perturb` has no `windage`, and `_run_glider` always passes one.
why it matters: the document describes a surface drift of half the size that the code applies, and the credibility report counts a platform number as an assumed input of every glider verdict although nothing reads it.

---

### B-10. RUNBOOK says emulator rows "accumulate" over runs; re-running the same mission with the same seed adds no new distinct point, so the 100-point gate cannot be reached that way
severity: minor
lane: documentation
where: `docs/RUNBOOK.md:119-123`, `cafe/pm/whatif.py:340-360` (`design(mission, n, seed)`, `LatinHypercube(seed=seed + i)`), `cafe/pm/pipeline.py:1036-1044` (variant members `(k + 1) * batch ..` and the run's seed), `whatif.py:389` (the gate counts distinct feature points)
reproduction: by reading: the variant design, the variant members and the baseline members are functions of the mission and its seed only, so a second run of the same code and seed appends rows identical to the first (same feature vector, same p_fail). `fit_class` then reports "only N of them are distinct feature points". The RUNBOOK tells the user to give every run the same `--emulator-table` and does not say that a different `--seed` (or mission) is what adds points.
why it matters: a lab member following the page repeats the demo and gets the same "will not train" line each time.

---

### B-11. A failed stage ends in a Python traceback and exit 1, and the actionable text is only in the ledger JSON
severity: minor
lane: robustness / documentation
where: `cafe/pm/__main__.py:151` (only `ConfigError` and `PlanError` become `error: ...`, exit 2), `cafe/pm/ledger.py:127-130` (`StageFailed`)
reproduction: `CAFE_DATA=/tmp/xdata CAFE_OFFLINE=1 python -m cafe.pm fetch --mission probe/late.yaml --out /tmp/rb_run` (a valid mission whose data is not cached). Output: a traceback ending `cafe.pm.ledger.StageFailed: stage ingest: self-checks failed: ['orca_present', 'tao_present', 'gebco_present', 'ocean_store_present'] (see .../ledger.json)`, exit 1. The sentence that names the fix is in the ledger: "...is not cached and CAFE_OFFLINE is set, so nothing is downloaded: run `python -m cafe.pm fetch --mission ...`", which, for the command that was just run, is circular (the fix is to unset `CAFE_OFFLINE`). RUNBOOK's troubleshooting table lists only "exit code 2 and `error: ...`".
why it matters: BRIEF 4.0 "a specific, actionable error naming the file, field and fix"; every failing self-check of any stage reaches the user this way.

---

### B-12. A zero-byte or corrupt `train.parquet` stops the emulator stage with a raw ArrowInvalid traceback, after stages 1 to 3 and 1b are done
severity: minor
lane: robustness
where: `cafe/pm/whatif.py:443-450` (`snapshot` reads the shared table unguarded), `cafe/pm/emulator.py:62-63` (`read_table`)
reproduction: `probe/corrupt.py`: for a file containing `b"this is not parquet"`, a 0-byte file and a truncated valid file, `whatif.snapshot(table, dest, "run1")` raises `ArrowInvalid: Could not open Parquet input source ... Parquet magic bytes not found in footer` / `Parquet file size is 0 bytes` in all three cases; nothing names the file or says to delete it.
why it matters: the table is shared by every run and lives on the data volume; one bad file turns every later run's emulator stage into a crash, though a missing table is already handled ("no training rows").

---

### B-13. The stage-1 benchmark folds one-time JIT cost into the per-batch cost and clips the per-member slope to zero
severity: minor
lane: performance
where: `bench/throughput.py:163` (the batch of 8 is the first call in the process, no warm-up call), `:168-171` (`b = max((a_hi - a_lo) / (hi - lo), 0.0)`, `a = max(a_lo - b * lo, 0.0)`), `config/throughput.json` (`usv` and `uas` have `s_per_member_day: 0.0`), `docs/RUNBOOK.md:64` (tells the lab to use this command)
reproduction: `probe/warm.py` (the bench's own calls, repeated, on the CI fixture at 1 CPU), per-vehicle `run_batch` wall time: first call M=8: uas 33.92 s, usv 8.15 s; M=32: uas 21.60 s (smaller than M=8); second pair M=8: uas 19.05 s, M=32: uas 19.27 s. What `stage1()` would store: uas `s_per_batch_day` 22.6 and `s_per_member_day` 0.0; from the warm pair 12.65 and 0.0061; glider_eq slope 0.0117 against 0.0281 warm. In q4 the planned stage 1 was 561.8 s (`plan.json stage1_s`) against 140.1 s measured (4.0 times); the stale load (32.9) explains part of it, the structure above is what a re-measure on an idle box will not remove.
why it matters: the planner will keep overstating UAS cost by about 1.8 times after the code-freeze re-measure, and a zero per-member slope for two of three classes says larger batches are free, which they are not.

---

### B-14. The rain rate is a backward difference stored at the end of its hour and then interpolated linearly, so rain events are 30 minutes late and twice as wide
severity: minor
lane: data
where: `cafe/pm/env/environment.py:65` (`np.diff(rain, prepend=rain[:1]) / dt`), used by the gust-front and rain-lens triggers
reproduction: by construction: if RAINNC+RAINC jumps by X mm between hour 4 and hour 5, `rain_mm_h[4] = 0`, `[5] = X`, `[6] = 0`; the interpolated rate is a triangle centred on hour 5 spanning 4 to 6, while the rain fell uniformly over 4 to 5 (centre 4.5). The first record of the window (12Z) always has rate 0 (`prepend=rain[:1]`), although the 11Z file exists in the spin-up hours that were dropped.
why it matters: gust fronts and rain lenses are keyed to the rate, and the vehicles meet them half an hour late and smeared against the wind field they should coincide with.

---

total: 14 findings (0 critical, 4 major, 10 minor)
