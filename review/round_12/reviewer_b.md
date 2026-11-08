# Round 12, reviewer B

Commit `72d7e66` content (checkout head `0a0532e`, documents only differ). Everything ran on orca (proot, `PMX=pm_rev12_b`, 1 to 2 CPUs), from a detached worktree and a private `pm_rev12_b`, both removed at the end together with my `pmdata/rev12_b*` files and `logs/rev12_b*`.

## What I did

RUNBOOK and ORCA_RUNNER, word for word as a lab user on orca:

- Step 1: read only. `make install`, the `docker images` grep, `bench/install_sitl.sh` and `bench/install_bellhop.sh` exist and parse under `dash -n`; the pm() wrapper matches `bin/pmx.sh`'s variable list.
- Step 2 `make ci` (via `bin/pmx.sh make ci`): rc=0, ends `audit: 0 problem(s)`, 3 min (the text says about 10).
- Step 3: `validate` prints exactly `missions/tepex_c_demo.yaml: valid (4 vehicles, 4 links)` (plus the stderr note). `fetch` on the cached window ends `ingest: done in 36 s`, then `up to date`; the shared `derived.zarr` mtime (08:13) is older than my call, so it did not rewrite it. 67 variants of the demo mission through `validate` (every limit the text lists, on both sides): all as written, no traceback; see B-10 for the one message that misleads. CLI hostile arguments (`--gpus`, `--budget`, `--seed`, missing files, a directory, `/dev/null`, `audit`/`report`/`whatif` on a missing run): exit 2 and an `error:` line each, no traceback.
- Step 4 and 6: read only.
- Step 5: not run (the prompt forbids the demo); `plan` runs; the 4-hour mission of B-1 plans.
- Step 7: `make receipts` on orca at 2 CPUs: **350 rows, 287 pass, 30 fail, 33 context, rc=2, 12 min** (the text says 287/33/30/350 and about 17 min). The 30 are the 3 `:not_run`, 7 NOT STORED and 20 DTMB rows (4 `U_val / D` + 16 iterative), as written. `make broken`: rc=0, 20 min, "the broken configuration failed 10 receipt(s) that pass without it". `make audit` and `make acceptance` not run (hours).
- ORCA_RUNNER: `bin/orca_ready.sh` (default marker, my `PMX`) ends `orca-ready`, exit 0. The numeric-variable refusals of `bin/pmx.sh` (`PM_CPUS` 1.5, `2,`, 0, `2;x`, `02`; `PM_THREADS`, `CAFE_MIN_FREE_GB`, `PM_STOP_GRACE` 1.5) exit 2 with nothing sent. I did not try `PMX=pmdata`, `..` and `../x` (a `rsync --delete` target; the classifier refused the call and I did not retry) or `TM=watch`.

Line by line, with the equations checked against PHYSICS.md and the cited source: `env/coare.py` (all of it; bulk loop, psi functions, first guess, k50, gustiness, cool skin, rain flux, warm layer against the NOAA reference as I know it, receipts), `env/waves.py` (spectrum shapes, spreading, mss share, restart Jacobian, Stokes drift and transport, Breivik 2016 eq 19/22/23 by integrating `sqrt(s) erfc` by hand, dispersion Newton, second-order kernel: collinear limits, opposing equal waves give 0, denominators never vanish for distinct components, Wheeler stretching, finite-depth transfer), `env/perturb.py` (Fourier-feature field, AR(1) filter initial state, rotation sign, SDE indexing, wave scaling), `env/surface.py` (all of it), `env/subgrid.py` (all of it: Mann length, box segments, theta_e, gust model, SDE step and the dK/dy derivative, rain lens, recalibration). No physics error found in the equations. Probes run: COARE edge cases, wavenumber residual over 600 (depth, f) points (worst 3.9e-16), AR(1) sd 1.00/1.02/1.01 at hours 0/24/48 and lag-1 0.723 against 0.717, the SDE well-mixed receipt over 12 seeds (all inside; the real sd of the ratio is 0.0106, not the 0.0141 of a 1-sigma, so the band is wide enough), the q12 `derived.zarr` (no NaN in any field, tw and tu axes equal, all L < 0 because SST > T2 and the sea virtual temperature exceeds the air's at every sampled point), Wilson 90 % and 95 % bounds of glider_eq (0.19914, 0.38110, 0.18593) recomputed.

## Findings

### B-1. A window with fewer than three 6-hourly restart spectra crashes `surface.build` (none) or writes a NaN uncertainty (one or two)
severity: major
lane: robustness
where: cafe/pm/env/surface.py:163-195 (`T`, the `zip(T[:-2], T[1:-1], T[2:], strict=True)` loop, `np.median(loo)`, `np.clip(np.searchsorted(tt, t) - 1, 0, len(tt) - 2)`), :127 (`json.dumps(fit)`), :258-261 (`stokes_surface` label and uncertainty)
reproduction: `validate` and `plan` accept a 4-hour mission (the demo with the window `2023-03-02T01:00Z` to `05:00Z`, the UAS and its link dropped: "valid (3 vehicles, 3 links)", "0.17 mission days"). The cache of a mission holds only its window (q12: 145 hourly files and 25 restart spectra for 144 h), so a window with no 00/06/12/18 Z inside has no restart. Calling `surface._correct_with_real` on a fake env with 13 hourly steps and 4, 3, 2, 1, 0 restart times inside: 4 and 3 give `n_restart_times` 3 and finite errors; 2 gives `corrected_loo_median_speed_err: NaN, corrected_loo_median_dir_err_deg: NaN` (np.median of an empty list), written into `derived.zarr` attrs as the JSON token `NaN`; 1 gives the same NaN and `k = clip(.., 0, -1)`, so a 0/0 weight and no correction at all; 0 gives `IndexError: index -2 is out of bounds for axis 0 with size 0`, which is the ingest ending in a traceback after the download. With NaN, `stokes_surface` returns `uncertainty = NaN * |v|` and a source text "leave-one-out median speed error nan %". No test covers fewer than three restarts (`grep n_restart_times tests` finds only the 7 of the 36 h fixture).
why it matters: a valid, planned mission fails at the end of a multi-hour fetch, or silently carries a NaN uncertainty on the Stokes drift; the fix is to refuse the window at `validate`/ingest with a message, or fall back to the fit-only tag `0.4 |u_s|` when fewer than three restarts exist.

### B-2. The diurnal jet's "+-0.1 m/s" uncertainty is documented and never carried or sampled
severity: minor
lane: statistics / honesty
where: cafe/pm/env/surface.py:14 (docstring "its half-range is the uncertainty") and :226 (`self.jet_half`, assigned and never read); :268-276 (`current_extra` returns `v.uncertainty` unchanged); docs/PHYSICS.md 5.4 ("+-0.1 as the sigma"); cafe/pm/env/subgrid.py:379 (`diurnal_jet` hard-codes 0.1)
reproduction: `grep -rn jet_half cafe/` gives the one assignment. In the q12 report, `report.json` `environment.vehicles.usv.current` has `source` "... + diurnal surface jet proxy (TEPEX-C hypothesis, modelled)" and `uncertainty: null`. Every member gets the fixed midpoint 0.2 m/s x dT/3 K (tests/test_surface.py:136 pins `jet_mid`), not the per-member U[0.1, 0.3] that `subgrid.diurnal_jet` (receipted, never called by the pipeline) draws.
why it matters: the hypothesis range 0.1 to 0.3 m/s never reaches the ensemble spread or the report, so the USV and glider failure probabilities are conditional on 0.2 without saying so; either sample the amplitude per member or state in PHYSICS 5.4 that it is a fixed midpoint.

### B-3. docs/PHYSICS.md 4.1 says `swell_age` and `wind_sea_age` are not in `config/assumptions.yaml`; they are
severity: minor
lane: documentation
where: docs/PHYSICS.md 4.1 (the bullet "are **code defaults** ... not keys in `config/assumptions.yaml`, so the credibility report does not list them"); cafe/pm/env/waves.py:110-111; config/assumptions.yaml `waves.wind_sea_age`, `waves.swell_age`
reproduction: waves.py reads `assumption("waves.swell_age")` and `assumption("waves.wind_sea_age")`; both keys are in assumptions.yaml; the q12 `report.json` `assumed_inputs.items` lists `assumptions.yaml:waves.swell_age` and `assumptions.yaml:waves.wind_sea_age` (kind `assumed`).
why it matters: the document states the opposite of the code and of the credibility report it points at.

### B-4. surface.py says alpha and beta are taken "at the box's mean surface state"; they are constants (S 35, CT 28)
severity: minor
lane: physics / documentation
where: cafe/pm/env/surface.py:18 (docstring), :228 (`gsw.alpha(35.0, 28.0, 0.0)`, `gsw.beta(35.0, 28.0, 0.0)`); docs/PHYSICS.md 5.3 states the constants correctly
reproduction: `gsw.alpha(35, CT, 0)` is 3.19e-4 at CT 28, 2.14e-4 at 15, 1.13e-4 at 5, 5.2e-5 at 0 (run on orca). A mission whose box has SST 5 C gets the warm-layer density change (`density_extra`) 2.8 times too large, and the rain lens's temperature term likewise. The schema allows any box.
why it matters: the TEPEX-C demo (SST 299 to 303 K) is not affected, but the docstring promises an adaptation the code does not do and a non-tropical mission is silently wrong in density.

### B-5. PHYSICS.md 4.4 gives two figures for the Stokes fit that cannot both be true ("median speed error 38 %" and "under-predicts by about x2.7")
severity: minor
lane: documentation / untraced number
where: docs/PHYSICS.md 4.4; `derived.zarr` attr `stokes_fit_check`
reproduction: the q12 attr is `fit_only_median_speed_err 0.3843` (median of `| |fit| / |real| - 1 |`). A fit that under-predicts by 2.7 has `|fit|/|real| - 1 = -0.63`, so its median error would be 0.63, not 0.38; the value 0.38 means the fit is 0.62 of the real speed (real = 1.6 x fit). The "x2.7" is in no ledger.
why it matters: a printed number with no trace, contradicting the one beside it.

### B-6. `CAFE_OFFLINE=maybe` (and `2`) are accepted with exit 0 by `fetch`, `plan` and `validate`; RUNBOOK 0 and the troubleshooting table say any other value is an `error:` with exit 2
severity: minor
lane: robustness / documentation
where: cafe/pm/pipeline.py:228-235 (`_offline`), called only at :256, :281, :399 (the places that would download); docs/RUNBOOK.md section 0 and the row "`error: CAFE_OFFLINE='x' is not 0 or 1`"
reproduction: `PM_HOST=cafe-orca PM_RUNTIME=proot PMX=pm_<you> bin/pmx.sh env CAFE_OFFLINE=maybe python -m cafe.pm fetch --mission missions/tepex_c_demo.yaml` on a cached mission: output `ingest: up to date (...)`, exit 0; the same with `plan` and `validate`. (`CAFE_WORKERS` is validated at once: 0, 1.5, abc, 2.0 and 1e1 give `error:` and exit 2, so the two variables are not treated alike.)
why it matters: a typo such as `CAFE_OFFLINE=ture` is silently online until a download is needed, which is the case the variable exists to prevent.

### B-7. `coare35` with a finite `cp` of 0 returns NaN u*, z0, L and Cd
severity: minor
lane: robustness
where: cafe/pm/env/coare.py:138 (`wave = np.isfinite(cp)`), :184 (`A_WAVE * (ustar / cp) ** B_WAVE` under `errstate(all="ignore")`); caller surface.py:48-52
reproduction: `coare.coare35(u=8, zu=10, t=300, zt=2, q=0.017, zq=2, P=101000, ts=301, Rs=400, Rl=420, lat=0, cp=0.0)`: ustar, z0, L, Cd all nan (with `cp=inf` it falls back to the Charnock result, with `cp=12, sigH=0` it is finite). The q12 UMWM `dcp` has minimum 3.93 m/s over 5.9 million sea values and `derived.zarr` has no NaN, so the demo is not hit.
why it matters: a UMWM value of 0 (calm, ice, a fill value) would put NaN into `derived.zarr` `ustar`, `z0`, `L` and then every profile and turbulence call; the switch should test `cp > 0`.

### B-8. `coare35(..., jcool=0)` still returns the computed cool-skin `dter` and `tkt`
severity: minor
lane: physics / API
where: cafe/pm/env/coare.py:213-214, :219-221, :253-254 (docstring: "dter (cool-skin dT, K, skin = ts - dter)")
reproduction: same state as B-7 with `jcool=0`: `dter = 0.2416 K`, `tkt = 6.2e-4 m`. With `jcool=0` the temperature passed is the skin, the loop never applies `dter`, but a caller following the docstring would subtract 0.24 K again. Only the receipts use `jcool=0`; `warm_layer` and `surface.build` use the default.
why it matters: latent; the returned value contradicts the stated meaning.

### B-9. Member wind error is inert at exactly zero wind and jumps at 1e-9 m/s
severity: minor
lane: statistics / robustness
where: cafe/pm/env/perturb.py:151-152 (`v * np.where(sp > 1e-9, new / sp, 0.0)`)
reproduction: a base environment returning an exactly zero wind vector, `wind_speed_bias` +1.5 m/s, `wind_speed_noise` sd 1 m/s: `PerturbedEnv.wind(...)` has max speed 0.0 for all four members. At `sp = 1e-8` the same bias gives 1.5 m/s in the base's (arbitrary) direction. A zero-wind window is one the RUNBOOK expects to pass the ingest ("a zero-wind window passes the ingest").
why it matters: the wind priors, and the TAO-fitted noise, have no effect on a calm field, so the ensemble spread is zero there; direction would have to come from somewhere (e.g. the mean of the bias draws) if the additive form is kept.

### B-10. `CAFE_WORKERS=` (empty) is treated as unset: under `PM_CPUS=1` the plan used 32 workers
severity: minor
lane: robustness
where: the `CAFE_WORKERS` reader (error text "`CAFE_WORKERS='0' is not a whole number of at least 1`" exists for every other bad value); docs/RUNBOOK.md troubleshooting row "`error: CAFE_WORKERS=... is not a whole number of at least 1`"
reproduction: `PM_HOST=cafe-orca PM_RUNTIME=proot PMX=pm_<you> PM_CPUS=1 bin/pmx.sh env CAFE_WORKERS= python -m cafe.pm plan --mission missions/tepex_c_demo.yaml --budget quick --gpus 0`: "stage 1: ... on 32 worker(s)", exit 0; `CAFE_WORKERS=+3` is accepted as 3; `CAFE_WORKERS=0`, `1.5`, `abc`, `2.0`, `1e1` give the `error:` and exit 2.
why it matters: `env CAFE_WORKERS=$UNSET ...` on the shared proot box overrides the runner's own count with orca's whole cgroup (32 CPUs) without a message.

### B-11. The 0 deg E and latitude refusals print the padded box as an unlabelled tuple in the order (lat_min, lat_max, lon_min, lon_max)
severity: minor
lane: documentation / usability
where: the messages of `validate` for a crossing box and a box beyond 90 deg latitude (config box checks, cafe/pm/config.py / pipeline.py:210, 548-560)
reproduction: the demo with `box: {lon_min: -10, lon_max: 10, lat_min: -5, lat_max: 5, pad_deg: 2}`: `error: ...: box (-7.0, 7.0, -12.0, 12.0): the box (with its pad of 2 deg) crosses 0 deg E`; the mission's own box order is lon_min, lon_max, lat_min, lat_max, so it reads as lon -7..7, lat -12..12, the reverse of the truth. With `lat_max: 89`: `box (-7.0, 91.0, 163.0, -163.0)`.
why it matters: the message meant to help a lab user fix the box points the wrong way round.

## Not found (checked, no defect)

- COARE 3.5 bulk loop, psi functions, k50, gustiness, Charnock and wave-age forms, rain flux, cool skin, warm layer (including the sensor-depth correction direction at coare.py:396) agree with the NOAA reference as I know it and with PHYSICS 3.
- `waves.py` second-order kernel: collinear limits, equal opposing waves give 0, no vanishing denominator; Breivik 2016 transport constant `(1 - 2 beta/3)/(2k)` derived by hand and matches; the Newton iteration converges although its docstring's "the function is concave" is false for kh below about 1.2 (the iteration still reaches 4e-16).
- `perturb.py`: rotation sign, AR(1) initial state and stationarity, SDE step indexing and window limits, the Fourier field's variance and its 100 km correlation (0.609 at 100 km at 60 N for lon offsets 0 and 10 deg, 0.568 at 20 deg: the cos(lat) metric is a 7 % effect only far from the box centre).
- `subgrid.py`: Mann length and segment capacity, Bolton theta_e, gust triangle, Okubo K and its exact latitude derivative, rain lens, recalibration pooling, the three-key `write_calibration` head cut (works because `calibration` is the last key of `config/subgrid.json`; it would silently drop any key added after it).

## Dead code worth knowing

`waves.Realization`, `stokes_breivik2016`, `encounter_spectrum` and `subgrid.diurnal_jet` are called only by receipts (PHYSICS 4.5 says so for the first three); `diurnal_jet` is not listed there, and the pipeline uses `SurfaceLayer.current_extra` instead (B-2).

## Disclosures

- One `fetch` run against the shared cache `/data/cache/tepex_c_demo` (it found it covering and ended without rewriting it).
- Orca's `ps` listing in my first check showed processes that are not mine; I stopped nothing by name and no process of mine was left (every job of mine ended by itself).
- A scratch file was briefly written to the laptop's `/tmp` (a one-line test of `bin/pmx.sh` refusals) and deleted.

total: 11 findings (0 critical, 1 major, 10 minor)
