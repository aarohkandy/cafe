# Round 10, reviewer C

Scope: `physics/usv.py`, `uas.py`, `glider.py`, `comms.py` and all of `stage3/`, read line by line at commit `a470119` (documents only above `8b870a6`).
Everything below was run on orca at 2 CPUs (`PM_HOST=cafe-orca PM_RUNTIME=proot PMX=pm_rev10_c PM_CPUS=2 bin/pmx.sh python <script>`) from a detached copy
of the repo; the copy and `pm_rev10_c` on orca were removed at the end. Nothing in the repo was edited.

Checked and found sound (so the next reader need not redo it): the Kerr cubic and the grazing-angle equality over 20,000 random geometries (residual 8e-14),
the divergence factor and Ament factor against their sources, the plane-earth limit of the curved two-ray loss, `utau_loglaw` against a bisection (max relative
error 2e-7 over 800 states), the glider and UAS handling of the dateline, the pole, a 30-day drift, a shallow floor and zero wind, the stage-3 numbers in the
q10 ledger (dx 1.9 mm, 6.5e9 cells, 1.4e15 cell-updates for the glider window reproduce from the assumptions file), and the USV direct solve against the table below 14 m/s of relative wind.
q10's stage-3 windows were all skipped as unreachable, so the LES path was exercised only by the toy windows below.

### C-1. `force_running_mean_dev` fails a converged force series whose per-step noise is above 2 %
severity: major
lane: numerics / statistics
where: cafe/pm/stage3/nest.py:330-338 (`running_mean_ok`); cafe/pm/stage3/windows.py:217, 225; cafe/pm/stage3/pipeline_windows.py:466-468 (the reason text)
reproduction: the running mean is `np.cumsum(seg) / arange(1, n+1)` over the last third `seg`, so it starts again at the first sample of that third, and its first value is one raw
sample. `dev = max|rm - m| / |m|` is therefore at least `|seg[0] - m| / |m|`: the per-step noise, not the convergence of the mean.
```
import numpy as np; from cafe.pm.stage3 import nest
rng = np.random.default_rng(0)
[nest.running_mean_ok(1 + 0.05 * rng.standard_normal(3000)) for _ in range(3)]
# dev = 0.040, 0.040, 0.046 -> ok False each time, although the mean of the last 1000 samples is known to 0.16 % (0.05 / sqrt(1000))
nest.running_mean_ok(1 + 0.005 * rng.standard_normal(3000))   # (True, 0.0039): passes only because the noise is below 2 %
```
A real window shows it: a toy ellipsoid window (`windows.run_window`, Vehicle length 1 m, radii 0.5/0.1/0.1 m, dx 0.04, 4000 steps, nu_floor 1e-4) has std/mean 2.1 % of its
drag over the last third and reports `force_running_mean_dev` 0.0254 > 0.02, ok False, with the mean steady. The same toy with a smooth series (box 3 x 1.6 x 1.6,
dx 0.05) reports 0.00013 and passes, so the check works on laminar series and fails on any series with ordinary fluctuation. The tests feed it only `np.ones` and a
drift (`tests/test_nest.py:309-312`, `tests/test_stage3.py:413`), so no test has noise.
why it matters: BRIEF 5.5 wants the force series "converged (running mean within 2 % over the last third)". A momentum-exchange force on a wake or a plate at incidence
(the USV keel and wing, the glider wing, the UAS arms) fluctuates by more than 2 % per step; such a window is `ok False` however well converged, `usable_for_refit` is
False, and the refit never sees it. On the GPU path this silently throws away the windows the stage exists for, with a reason ("no convergence") that is untrue.

### C-2. The USV polar has unconverged cells and speed cliffs at high wind that no document, receipt or flag mentions
severity: minor
lane: physics / honesty
where: cafe/pm/physics/usv.py:295-323 (`_solve`: depower responds to the heel moment only; the keel saturates at `keel_stall_deg`); usv.py:696-704 and 774-782 (the receipts that cover it); docs/PHYSICS.md section 10.1
reproduction:
```
from cafe.pm.physics import usv; import numpy as np
P = usv.load_platform(); T, A = np.meshgrid(np.arange(0., 30.01), usv.TWA, indexing="ij"); g = np.radians(A)
s = usv._solve(P, -T*np.cos(g), -T*np.sin(g), np.zeros_like(T), np.zeros_like(T))
# resid and yaw_resid reach 0.999 (the sway force is not balanced) in 581 of 2759 cells; 19 cells with resid > 0.5 at TWA >= 30 deg
# TWA 15 deg: V = 1.33 m/s at TWS 16, 0.0 at TWS 17 (keel leeway pinned at 14 deg, heel 25 deg)
# TWA 30 deg: 1.47 -> 0.0 between TWS 25 and 26;  TWA 45 deg: 2.06 m/s at TWS 25, 0.0 at TWS 30 (resid 0.999)
```
Where `V > 0.2` the residuals are below 2.1e-4, so the cells that fail are exactly the ones that report no way. `table_gap` draws wind relative to the water from 0 to 14 m/s only, and
the residual receipt reads five states (wind relative to the water 2.8 to 8.2 m/s), so nothing tests 15 to 30 m/s, the range the table advertises ("TWS 0 to 30 m/s").
why it matters: from 16 m/s upwind the polar says the boat stops, where a boat would reef or head up; the router avoids those headings, so the verdict is hardly moved, but
`becalmed` and the speed made good in a gale rest on cells whose force balance failed, and the docs say the table agrees with the direct solve without giving this range.

### C-3. `mass_drift_per_step` allows 0.1 % per step, which is no bound on "mass conservation <= 0.1 %"
severity: minor
lane: numerics / documentation
where: cafe/pm/stage3/windows.py:226 (`md <= 1e-3`); cafe/pm/stage3/nest.py:341-344 (`mass_drift`: the largest relative change between consecutive steps); docs/BRIEF.md:231
reproduction: BRIEF 5.5 says "mass conservation <= 0.1 %" for the window; the sentence of 5.1 (line 205) that has "per step" is the nest-in-a-shear-layer receipt. The window check applies the per-step reading. A window of the
planned 4,000 to 200,000 steps that loses 9e-4 of its mass every step passes the check and has lost the mass many times over. On the toy window (box 3 x 1.6 x 1.6, dx 0.05, 4000 steps)
the largest step change is 2.5e-6 and the whole-run change is 4.2e-4 (sum of the steps 4.18e-4): the limit is 400 times looser per step than what the kernel does, and
the run's total, which is what the brief names, is not checked.
why it matters: the check cannot fail on a leak that matters, and the row prints as if it checked the brief's statement.

### C-4. A hole in the weather at a window gives misleading errors (or a NaN kinematic case) instead of a "no data" reason
severity: minor
lane: robustness
where: cafe/pm/stage3/pipeline_windows.py:303-312 (`uas_leg_speed`), 315-349 (`uas_case`), 253-254 (`usv_case`), 353-367 (`fit_window`); `glider_case` (202-231) the same for a current that is NaN
reproduction:
```
import types, numpy as np
from cafe.pm import budget; from cafe.pm.physics import uas, usv
from cafe.pm.stage3 import pipeline_windows as pw; from cafe.pm.env.protocol import AnalyticEnv
a = budget.stage3_assumptions(); w = dict(t=0., lon=-165., lat=0.); ctx = types.SimpleNamespace(env=AnalyticEnv(wind=(np.nan, np.nan)))
P = uas.load_platform(); case = pw.uas_case(ctx, w, P, pw.uas_vehicle(P, a, "quad_uas"), a, None)   # returns: leg_speed_ms nan, v_rel_ms nan, tilt nan
pw.fit_window(pw.uas_vehicle(P, a, "quad_uas"), float("nan"), 1e9, a)                               # ValueError: cannot convert float NaN to integer
Pu = usv.load_platform(); pw.usv_case(ctx, w, Pu, pw.usv_vehicle(Pu, a, "saildrone_explorer", "hull"), a, None, "hull")   # ValueError: "... (becalmed)"
```
`np.hypot(nan, nan) > 1e-6` is False, `d2 < 0` is False and `max`/`min` return the NaN, so the UAS case is built from NaN; the row's `error` is the integer-conversion message. A USV window on a NaN wind
says "the USV makes no way through the water at this window's wind (becalmed)", which is a statement about the sea, not about a hole.
why it matters: the row `reasons` are what the report prints for a failed window; the stage-1 rules (`no_current_data`) name a hole as a hole, and this one does not.

### C-5. A glider dive depth inside about 12 m of the rating is accepted by the mission check and fails `overdepth` in every member
severity: minor
lane: robustness / physics
where: cafe/pm/physics/glider.py:287 (`target_depth = min(dive_depth_m, rating_m)`), 448 (apogee overshoot `0.5 w_last dt`), 479 (`overdepth` is `depth > rating_m`); cafe/pm/config.py:436 (accepts `min_dive_m <= dive_depth_m <= rating_m`)
reproduction: `GliderSim(P, 3, AnalyticEnv(wind=(5, 0), current=(0.1, 0.05), rho=1025.), -165., 0., 0., dict(mode="station", station=(-165., 0.), dive_depth_m=1500.))` with the Seaglider (rating 1000 m) gives
`fail["overdepth"]` True for all three members, first at 10,980 s, at the first apogee. Asking for 1000 m, which `config.py:436` accepts, is the same run, as is 990 m (the overshoot is about 12 m).
why it matters: a legal task can never come out GO, and the report says "overdepth" without saying that the depth asked is inside the vehicle's own overshoot. Either the mission check should stop short of the rating by the overshoot, or the flag's note should name it.

### C-6. The added-resistance table clamps at speed 3.5 m/s and peak period 3 to 21 s while the platform check accepts a cap of 50 m/s
severity: minor
lane: robustness / documentation
where: cafe/pm/physics/usv.py:417 (`_build_waves`: `u = linspace(0, 3.5, 8)`, `tp = linspace(3, 21, 19)`), 167-181 (`_lin` clamps), 117 (`stw_cap_ms="pos<=50"`)
reproduction: `usv.added_resistance(P, wt, 2.0, 8.0, 180.0, 3.5)` and `(..., 5.0)` both return 37.408789 N; Tp 2 s and 3 s both return 1846.136 N (Hs 2 m, head seas); Tp 25 s and 21 s both return 1.065 N. A lab file with a cap of 4 m/s passes `check_params`
and then uses R_aw of 3.5 m/s above it.
why it matters: the lab is told to edit the platform file; the range the table is valid in is not in the check or in a note, and for Tp below 3 s (steep short seas, where R_aw is the largest, G = 436 N/m^2 at 3 s) the clamp underestimates.

### C-7. The "hull speed" receipt uses LOA where the formula is for the waterline length
severity: minor
lane: honesty
where: cafe/pm/physics/usv.py:719-721 (`hull_speed = 1.34 * sqrt(loa_m / 0.3048) * 0.514444`); module docstring line 34-35 ("Hull speed 1.34 sqrt(L_ft) kn reproduces the 3.3 m/s cap")
reproduction: with `lwl_m` 6.5 m the formula gives 1.34 * sqrt(21.33) kn = 6.19 kn = 3.18 m/s (3.6 % under 3.3 m/s); with the LOA of 7 m it gives 3.30 m/s. The receipt is labelled "LOA" in its claim but the docstring and docs/PHYSICS.md 10.1 call it the hull speed, which is a function of LWL, and the choice of length is what makes the receipt land on 3.3.
why it matters: a reader takes "the cap is the hull speed" as an independent check; with the waterline length it is a 3.6 % miss that the 4 % tolerance happens to hold, with the LOA it is a tuned match.

total: 7 findings (0 critical, 1 major, 6 minor)
