# Round 4, reviewer A: findings

Tree: branch `premission-step4` at `c1faf3f` (code of `23e9a95`), q4 quick run in `.../scratchpad/q4`. Scratch scripts I used are in `.../scratchpad/rc/ra/` (a copy of the repo plus `edge*.py`; the repo itself was not edited). All one-CPU snippets ran on homebase through `pmx.sh` with `PMX=pm_rev4_a` / `pm_rev4_a2`.

### A-1. The derived surface layer (`derived.zarr`: COARE u*, z0, L, warm layer, rain lens, Stokes drift) is outside every hash, check and invalidation rule
severity: major
lane: reproducibility / data
where: cafe/pm/pipeline.py:322-331 (the ledger inputs and the rebuild rule), cafe/pm/pipeline.py:627-631 (`_derived_current`), cafe/pm/env/surface.py:39, 113, 187 (`LAYOUT_VERSION` is the only guard), cafe/pm/env/orca.py (nothing removes or rebuilds it when the orca cache is refetched)
reproduction:
1. q4 ingest ledger (`checkpoints/ingest/ledger.json`): the inputs are the orca manifest, the ocean store manifest hash, the GEBCO cut and the TAO manifest. `derived.zarr` is neither an input nor an output, and no check reads it.
2. On homebase, `ls -l --time-style=full-iso ~/work/cafe/pmdata/cache/tepex_c_demo/derived.zarr/zarr.json ~/work/cafe/pmdata/cache/tepex_c_demo/orca/manifest.json`: derived 2026-10-29 11:41:46, manifest 2026-10-31 22:04:53. The layer q4 read is 2.4 days older than the orca cache beside it, and `config/assumptions.yaml`, `subgrid.py` (8ee5f50, 23e9a95) and `environment.py` changed after it was built; none of that rebuilt it.
3. Offline proof that nothing notices: build the CI tree (`tests/fixtures/ci_env/make.py`), open `derived.zarr` with `zarr r+`, multiply `ustar` by 3 and set `dT_warm` to 0, then run `pipeline.s_ingest` in a `Ledger` (`ra/edge8.py`). Output: `ingest ledger ok: True`, failed checks `[]`, no `derived` entry in inputs or outputs, and `Context.env.subgrid.surface_layer` at (-165, 0) returns u* 0.494 (was 0.165) and dT_warm 0 (was 0.057).
4. `_derived_current` only compares `layout_version`. Editing the mission window or box makes `orca_covers()` false, `orca.ingest` refetches `wrf.zarr`, and the old `derived.zarr` (old time axis and grid) is kept; `grid.Axis.locate` clips out-of-range queries to the edge (grid.py:28-30), so new hours silently get the last old hour's u*, warm layer, rain lens and Stokes drift.
why it matters: every Stage 1, 1b and UAS result reads this store, yet the ledger chain, `audit` and resume cannot see it, and the same `code_digest` and config hash can produce different numbers. The "ledger proves what it read" claim does not hold for the largest derived input.

### A-2. The "most sensitive to" indices can only see 10 hypercube columns; the dominant random errors are not columns
severity: major
lane: statistics
where: cafe/pm/stage1.py:36-41 (`priors_for`), cafe/pm/stage1.py:577 (`_sensitivity`, columns `acting`), stage1.py:38 (`ACTS`), cafe/pm/env/perturb.py:130-140, 174-176 (wind AR(1) noise, current random field, ocean SDE all drawn from `member_rng`, not from `U`), cafe/pm/report.py:921 and the "Most sensitive to" lines
reproduction: `q4/ingest/priors_fitted.json`: `wind_speed_bias` sd 0.113 m/s (a column) against `wind_speed_noise` sd 1.283 m/s, tau 6.4 h (not a column); `wind_direction_bias` 2.63 deg against `wind_direction_noise` 22.2 deg. The column therefore carries 0.113^2 / (0.113^2 + 1.283^2) = 0.8 % of the wind-speed error variance (and 1.4 % for direction). `current_speed_scale` and `current_direction_bias` carry only half of their prior's variance (perturb.py:174-176; the other half is a per-member Fourier field), and the ocean SDE, the windage draw, the UAS turbulence and gust draws and the Iridium draws are also outside `U`. Result in `q4/stage1/summary.json`: the USV S1 for `wind_speed_bias` is 0.033, `current_speed_scale` 0.0, and all ten sit under the floor 0.27, so the report prints "No parameter clears the noise floor ... the sample cannot rank them". DECISIONS 211 and the report do not say that the columns exclude the main wind and current error streams.
why it matters: the sensitivity block is the report's only attribution of failures to inputs, and by construction it cannot attribute them to the wind and current errors that the TAO fit says dominate; a reader will conclude wind speed barely matters (S1 0.03) when the column is a 0.1 m/s bias. It should either include the stream amplitudes as columns (draw a per-member amplitude from `U`) or say plainly what it cannot see.

### A-3. The two-ray RF model is flat-earth all the way to the 4/3-earth horizon, so the margin is overstated by 9 to 40 dB near the horizon
severity: major
lane: physics
where: cafe/pm/physics/comms.py:67-83 (`two_ray_loss_db`, `r1`, `r2` from straight-line geometry), comms.py:86-96 (`rf_margin` cuts off only at `radio_horizon_km`), cafe/pm/stage1.py:~509 (links), stage1.py:~230 (`_uas_links`); docs/PHYSICS.md and the report label it "two-ray + 4/3-earth horizon" with no curvature caveat (grep "curvature" finds nothing)
reproduction: `ra/edge3.py` (homebase). Ship mast 15 m, antenna 3 m, 915 MHz, Hs 0, horizon 23.09 km. Flat loss from the repo, against the same two-ray with effective-radius (k = 4/3) reflection-point heights h' = h - d_i^2 / (2 k R) (the standard Kerr cubic):

| d | flat (repo) | curved | extra loss |
|---|---|---|---|
| 5 km | 114.9 dB | 115.7 | 0.7 |
| 10 km | 126.9 | 130.2 | 3.2 |
| 15 km | 134.0 | 142.7 | 8.7 |
| 18 km | 137.1 | 152.4 | 15.2 |
| 20 km | 139.0 | 161.9 | 22.9 |
| 22 km | 140.6 | 180.6 | 39.9 |

`rf_margin(20e3, 15, 3, 0.0, 'rfd900x')` = +13.0 dB (link counted up) and +11.4 dB at 22 km; with the curved-earth loss they are about -10 dB and -28 dB. The earth bulge between the antennas at 15 km is 2.4 m, comparable to the 3 m antenna.
why it matters: any RF link whose range is 40 to 100 % of the horizon (a USV 15 to 22 km from a ship, a UAS at 100 m altitude about 40 km from a ship, a different mission's geometry) is judged up where it should be down. The demo hides it because the USV-UAS samples are 89 % beyond the horizon and all 32 members fail by range anyway.

### A-4. A non-finite current (a land block in the ocean store) crashes the USV step with a bare IndexError and aborts Stage 1
severity: major
lane: robustness
where: cafe/pm/env/grid.py:55-58 (`interp` returns NaN when every corner of the cell is NaN), cafe/pm/physics/usv.py:132-145 (`_lin`: `np.floor(NaN).astype(int)` is -9223372036854775808) via usv.py:530 (`step` -> `_eval`)
reproduction: `ra/edge9.py`:
```
env = AnalyticEnv(wind=(-5.0, 0.0), current=(float("nan"), 0.0), hs=1.0)
sim = usv.USVSim(P, 4, env, (-165.0, -1.0), 0.0, dict(mode="section", waypoints=[(-165.0, -1.0), (-165.0, 1.0)]))
sim.run(3600.0)    # IndexError: index -9223372036854775808 is out of bounds for axis 0 with size 31
```
The same through `stage1.run_batch` (`ra/edge2.py`, case `nan_current`: traceback `_run_usv` -> `step` -> `_eval` -> `_lin`). The glider handles the same input (it flags `no_flight`, `ra/edge7.py`), so this is the one vehicle class that dies. A NaN current is reachable in a real run: any query whose four horizontal GOFS corners are land (two adjacent masked 0.08 deg cells, an atoll group or island of a dozen km) returns NaN, and the box 165E-165W holds the Gilbert and Phoenix Islands. `_left_data` does not catch it (`inside` looks at the WRF box and the bathymetry grid only).
why it matters: a mission whose USV section passes an island ends in a traceback hours into a run, with no `error:` line and no partial result, where the glider in the same situation produces a labelled failure.

### A-5. The UAS `lost_link` flag latches on one 50 ms sample of a smooth-sea two-ray null, and a NaN wave height becomes a glass-calm sea
severity: minor
lane: physics
where: cafe/pm/physics/uas.py:498-500 (`f_link |= lost` at every `DT_ENV` sample, no duration; every other UAS flag with a time scale has one, e.g. `stuck_window_s` 10 s), cafe/pm/stage1.py:236 and :509 (`np.nan_to_num(hs)`), comms.py:67-83
reproduction: `ra/edge4.py` (CI mission, UAS only, `AnalyticEnv(wind=(-5,0), current=(-0.3,0), hs=h)`, 8 members): lost_link members = 5 of 8 at Hs 0.0, 2 of 8 at 0.2, 0 at 0.4 and above; battery and wind flags 0 throughout. At low Hs the Ament factor (comms.py:50-54) stops blurring the nulls (`rho` 0.75 at Hs 0.2 m and sin psi 0.4), and the controller sweeps the UAS through several of them on every ascent. `nan_to_num` turns an Hs of NaN (UMWM sea mask) into Hs = 0, the deepest-null case.
why it matters: a calm morning (Hs <= 0.3 m) flips the UAS to NO-GO by `lost_link` although a 915 MHz telemetry link rides through a 50 ms fade; the demo has Hs of 1 to 2.3 m so it does not show. Needs a hold time like the other flags, and NaN Hs should be an error or a labelled fallback.

### A-6. A UAS with no launch inside the window fails every member as `no_sortie_flown` (NO-GO), and `validate` accepts it
severity: minor
lane: robustness / honesty
where: cafe/pm/stage1.py:299-300 (`fail["no_sortie_flown"] = n_flown == 0`, comment "every launch scrubbed"), cafe/pm/config.py:load_mission (no check that `launch_times` is non-empty)
reproduction: `ra/edge1.py` case `short1h`: `ci_fixture` with `window.end` 2023-03-01T19:00:00Z and `local_solar_time: "00:00"` (launch at 11Z, outside the window). `load_mission` accepts it; `run_batch` gives UAS NO-GO 8 of 8 members, mode `no_sortie_flown`, and the UAS link `usv-uas-rf` needs zero samples so it reads "success" (frac 1.0, stage1.py:523) and MARGINAL. Same for a 11 min window (`short11min`).
why it matters: nothing was scrubbed (no weather gate ran); the mission asked for no flight in the window and the tool answers with a failure label meant for a weather scrub. `validate` should refuse a sortie schedule with no launch in the window.

### A-7. Verdict tie at P(success) = nogo falls on the wrong side for some thresholds (floating point)
severity: minor
lane: statistics
where: cafe/pm/stats/intervals.py:40 (`round(1 - nogo, 12)`) and :109 (`p >= 1 - P_FAIL_NOGO`)
reproduction:
```
intervals.set_thresholds(0.9, 0.3); intervals.verdict(7, 10)['verdict']   # 'NO-GO'
intervals.verdict_from_p(0.7)                                              # 'MARGINAL'
```
`P_FAIL_NOGO` = 0.7, `1 - 0.7` = 0.30000000000000004, and p = 3/10 = 0.3 < that. The docstring and the schema say NO-GO is "below" nogo, so p = 0.3 should be MARGINAL. A sweep over go in {0.5 ... 0.99}, nogo = 0.3 and n up to 512 gives 51 wrong ties (n = 10, 20, 30 ... with k = 0.7 n). The demo thresholds (0.9, 0.6) are fine; the schema accepts any 0 < nogo < go <= 1.
why it matters: `verdict` and `verdict_from_p` (used by the emulator and the flip search) disagree at the boundary, and the stopper's `interval_region` and `decided_region` use the other formulation. Compare success counts in integers, or add a tolerance.

### A-8. A ship id equal to a vehicle id passes `validate`, and then `_pos` silently moves the vehicle onto the ship
severity: minor
lane: robustness
where: cafe/pm/config.py:187 (`nodes = set(ids) | {ship id, shore id}` with no cross-check; duplicates are checked among vehicles only), cafe/pm/stage1.py:377 (`if node == mission["ship"]["id"]` is tested first)
reproduction: `ra/edge6.py`: the demo mission with `ship.id: glider_2n`, the UAS `base: glider_2n` and one link `glider_eq` -> `glider_2n` (acoustic, surfacing) is ACCEPTED. In stage 1 the link end named `glider_2n` is resolved as the ship (-165, 0), never as the glider, so the link is judged against the wrong geometry with no message. (A `shore.id` equal to a vehicle id fails only by luck of the link rules.)
why it matters: a one-word typo changes a link verdict silently. Refuse ids that appear in `vehicles`, `ship` or `shore` more than once.

### A-9. The reach map feeds the Zermelo router the wrong speed for both drifting classes
severity: minor
lane: physics
where: cafe/pm/report.py:564-569 (USV `speed` = median ground path speed), report.py:585-589 (glider current = mean of z = -5 to -100 m), cafe/reach.py:made_good (V is the speed through the fluid) and the docstring at reach.py:7-8
reproduction: `q4/report/report.json` `reach.vehicles.usv`: `speed` 0.6613 m/s "median mean path speed over ground of the Stage-1 ensemble, which already includes the drift in the currents", `flow_max` 0.585 m/s, farthest cell 93.57 km in 24 h. `made_good(V, c, d)` adds `c.d` to `V`, so the current that is already inside the over-ground speed is added again (the ensemble's through-water speed is 0.72 m/s by PHYSICS.md section on the USV). For the gliders `reach.glider_2n` reports `flow_max` 0.998 m/s, the largest value of the 5 to 100 m mean current on its grid, while the glider's task dives to 500 m (and glider_eq to 950 m): its depth-averaged current, which sets what it can do, is not the 5 to 100 m mean, and the glider's own median track makes 27.9 km in 24 h (0.32 m/s) against a 52.6 km envelope.
why it matters: the map is the one quantitative figure for "where can it go" and its inputs do not match the vehicle's physics. Use the through-water speed of the stage-1 tracks and the current averaged over the dive depth.

### A-10. "M&S management 3 of 4" is labelled "strong: checked against an independent reference" with only self-checks behind it
severity: minor
lane: honesty
where: cafe/pm/credibility.py:34 (`LEVELS[3]`), credibility.py:77 (`LEVEL_TEXT` overrides level 3 for `data_pedigree` only), credibility.py:496 (`_ms_management`)
reproduction: `q4/report/credibility.json` factor `ms_management`: `level` 3, `level_text` "strong: checked against an independent reference"; its rule is "ledger chain audits clean, docs/BUILDERS.md exists and ruff is configured" and the evidence is the tool's own ledgers and `cafe/pm/audit.py`. Nothing independent is read. Round 2 M-17 fixed this wording for data pedigree by `LEVEL_TEXT`; the same fix was not applied here.
why it matters: the credibility page shows one factor as externally checked when it is not. Add `ms_management` to `LEVEL_TEXT` ("strong: ledgers, chain and house rules checked by the tool's own audit").

### A-11. The current-speed prior is documented as lognormal with median 1, and the perturbed environment realises a median of 0.97
severity: minor
lane: statistics
where: cafe/pm/env/perturb.py:174 (`- self.cs ** 2 / 4`), config/perturbations.yaml `current_speed_scale`, docs/PHYSICS.md:527 and :541 ("lognormal, median 1, sigma 0.30")
reproduction: `ra/edge3.py` part (b): `PerturbedEnv` over a uniform 1.0 m/s current with 4000 members whose scale is drawn lognormal(median 1, sigma 0.3): realised speed ratio median 0.969, mean 1.019. The cause: the log-scale is built as N(-sigma^2/4, sigma^2), so its median is exp(-0.3^2/4) = 0.978 and its mean exp(+sigma^2/4) = 1.023: neither the documented median (1) nor mean-preserving (that would need -sigma^2/2). No source or DECISIONS row explains the term.
why it matters: a 2 % systematic cut of the currents in every vehicle's environment, undocumented, in a mission whose USV and glider verdicts are driven by currents of 0.3 to 0.6 m/s.

### A-12. UAS `altitudes_m` up to 1000 m are accepted, and wind above the top ingested level is held constant and counted as "flown in the WRF 3-D field"
severity: minor
lane: data / honesty
where: cafe/pm/env/environment.py:215 (`np.clip(..., 0, 1)` above the top level), environment.py:180 (`wind3d_points += used`), cafe/pm/env/orca.py:30 (`NZ3 = 8`, "~21 to ~400 m"), cafe/schemas/mission.json (`altitudes_m` maximum 1000)
reproduction: `ra/edge2.py` case `uas_1000m`: `altitudes_m: [10, 1000]` loads and runs (UAS MARGINAL, 1 of 8 `wind_exceeds_airspeed`). Above about 400 m the profile is the top WRF level's wind unchanged, yet `wind3d_points` counts those queries as 3-D, so the report's "Sortie records flown in the WRF 3-D wind field: x fraction" includes them.
why it matters: a 1000 m profile is flown in a wind field that stops at 400 m, with no warning and a statement that it used WRF. Either cap `altitudes_m` at the top ingested level or count the extrapolated points separately.

### A-13. The certification sentence mixes a one-sided and a two-sided confidence level
severity: minor
lane: statistics / honesty
where: cafe/pm/stats/intervals.py:n_certify (73, two-sided Wilson) and n_certify_one_sided (59), the `note` built in `verdict` (intervals.py:~112-118) and the report line copied from it
reproduction: `q4/report/report.json` / index.html for glider_2n, uas and usv-shore-iridium: "P(fail) < 3/n = 0.094 (n = 32; 73 members are needed to certify P(fail) < 5% at 95% confidence)". 3/n is the one-sided 95 % rule of three, under which 3/n < 0.05 needs n = 60 (`n_certify_one_sided()` = 59); the 73 is the n at which the two-sided 95 % Wilson upper bound is below 5 % (a one-sided 97.5 %). Round 1 M-18 removed an earlier mix of two levels in one sentence; this one remains.
why it matters: a reader who applies the quoted rule gets a different n from the one stated in the same bracket.

total: 13 findings (0 critical, 4 major, 9 minor)
