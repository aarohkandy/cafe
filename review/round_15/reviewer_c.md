# Round 15, reviewer C: stage-3 core (fea.py, lbm.py, refit.py, freesurface.py, windows.py, pipeline_windows.py)

Read line by line: `cafe/fea.py`, `cafe/pm/stage3/lbm.py`, `refit.py`, `freesurface.py`, `windows.py`, `pipeline_windows.py`. Reproductions ran on orca (proot, 2 CPUs, `PMX=pm_rev15_c*`) from the detached copy `../cafe-rev15-c` at 01a39c0; nothing in the repo was edited.

## fea.solve against closed-form answers (orca, 2 CPUs, Al 6061, p = 1 MPa external)

| case | quantity | FEA | closed form | difference |
|---|---|---|---|---|
| sphere R 0.15 m, t 3 mm, h 0.02 (10,210 nodes, 763 s with the buckling step) | `vm_p99` | 25.68 MPa | Lame inner wall 25.51 (membrane 25.00) | +0.7 % |
| same, h 0.025 / 0.04 | `vm_p99` | 26.34 / 26.52 | 25.51 | +3.3 % / +4.0 % |
| same, h 0.02 | `u_max` | 3.705e-5 m | (1-nu) p R^2 / (2 E t) = 3.647e-5 | +1.6 % (h 0.04: +15 %) |
| same | linear buckling (dead load) | 35.20 MPa | Zoll 2E/sqrt(3(1-nu^2)) (t/R)^2 = 33.71 | +4.4 % |
| same | `buckling_factor` as reported (x 0.75) | 26.40 MPa | 33.71 | -21.7 % |
| closed tube R 0.1, t 3 mm, L 1.2 (L/D 6, flat caps), h 0.02 | membrane von Mises at mid-length | 29.34 MPa | sqrt(3)/2 p R/t = 28.87 | +1.6 % |
| same | dead-load buckling / reported (x 0.75) | 1.028 / 0.771 MPa | von Mises (n = 2, exact form) 0.733; Bresse (infinite tube) 0.522 | +40 % / +5.1 % vs von Mises |
| same tube, L 0.6, h 0.015 | dead-load / reported | 2.028 / 1.521 MPa | von Mises (n = 3) 1.686; Windenburg-Trilling 1.701 | +20 % / -9.8 % vs von Mises |
| clamped CFRP tube, tip load 10 N (the receipt's case), h 0.004 | nodal von Mises at x = 0.03 / 0.06 / 0.10 m | 13.4 / 11.7 / 9.3 MPa | beam M R / I: 13.2 / 11.4 / 9.0 | +1.5 % / +2.6 % / +3.3 % |

Stress and the first buckling mode agree with theory to a few per cent. Findings follow.

### C-1. The stage-3 hull FEA runs on a mesh the repo itself calls unconverged, and its collapse depth is still falling with refinement
severity: major
lane: numerics
where: `config/assumptions.yaml` `stage3.fea_elements_along` (20); `cafe/pm/stage3/pipeline_windows.py:_fea` (`h=veh.length / need(a, "fea_elements_along")`); `cafe/hangar.py:162` (comment: "L/45 read collapse ~9 % high; L/70 is converged"); `docs/PHYSICS.md:992`, `QUESTIONS_FOR_LAB.md` 4a ("collapse at about 364 m")
reproduction: `windows.fea_window(Vehicle("g","water",1.8,[ellipsoid radii (0.9,0.15,0.15)], material="al6061", thickness=0.008, depth=500), np.zeros((1,3)), np.zeros(1), h=L/n, buckle=True)` on orca at 2 CPUs (the default glider hull of the assumptions, hydrostatic 500 m only). Buckling factor / buckling utilization / collapse depth: L/20 1.4552 / 1.3743 / 364 m (1,408 elements, 65 s); L/30 1.4133 / 1.4152 / 353 m; L/45 1.3348 / 1.4984 / 334 m (449 s); L/70 1.3225 / 1.5123 / 331 m (454 s, 5,546 elements). Each refinement lowers the buckling factor and the collapse depth, and L/70, which hangar calls converged, sits 9.1 % below L/20 in factor (1.4552 to 1.3225) and 33 m shallower in collapse depth (364 m to 331 m). The p99 stress utilization moves the other way, 0.367 to 0.305.
why it matters: the number the documents quote (364 m, utilization 1.374) comes from the coarsest mesh and errs in the unsafe direction by 10 % in collapse depth against the converged 331 m (utilization 1.512); `assumptions.yaml` names the missing convergence study as its `replace_with` and none is stored. P-R14V4 states the 364 m but not that it is a mesh-limited over-estimate; nothing reads `utilization`, so no verdict moves, but the stored row and the document carry the unconverged figure with no caveat.

### C-2. The 3/4 follower-pressure correction is applied to every mode and then the 0.5 knockdown is stacked on it
severity: minor
lane: physics
where: `cafe/fea.py` (`out["buckling_factor"] = 0.75 * min(pos)`, comment above it); `cafe/pm/stage3/windows.py:fea_window` (`1.0 / (lam * hangar.KNOCKDOWN)`); `cafe/hangar.py:164`
reproduction: the comment derives the dead-to-follower ratio as n^2/(n^2-1), 4/3 only for the 2-lobe mode, and then multiplies every result by 3/4. The sphere run above (lowest modes of high n, ratio near 1): dead 35.20 MPa is +4.4 % over Zoll's follower-pressure answer 33.71 and the reported value 26.40 is -21.7 % under it. The L 0.6 tube (n = 3, 9/8 expected): dead is 1.203 x von Mises, reported 0.902 x. On the default glider hull the correction alone moves the utilization 1.03 -> 1.374 (collapse depth about 485 m -> 364 m before mesh error), before `KNOCKDOWN` 0.5.
why it matters: the knockdown 0.5 is a separate allowance for imperfections; piling the n = 2 correction on all modes makes the reported margin 10 to 25 % more pessimistic than the comment's own formula, so "364 m" mixes two conservatisms and one unconverged mesh (C-1) in opposite directions, with no document separating them.

### C-3. `python -m cafe.fea` (the module's self-test) and the module docstring describe a constraint the code no longer has
severity: minor
lane: documentation
where: `cafe/fea.py:1-6` (docstring: "statically determinate 3-2-1 constraint whose reactions should come out ~0 (checked and reported)"); `cafe/fea.py:__main__` (`r['reaction']`, final assert on `r["reaction"]`)
reproduction: `fea.solve(icosphere, "shell", "al6061", thickness=0.002, point_loads=[...], steps=("static",), h=0.04)` returns no `reaction` key (probe: `"reaction" in a` is False); `support` is None for a free body, so `out["reaction"]` is only set with `fixed=`. The `__main__` print line indexes `r['reaction']` before its asserts, so the self-test raises `KeyError: 'reaction'`. The body is held by `_mean_rigid_equations` (six `*EQUATION` rows), not by a 3-2-1 pin.
why it matters: the only runnable receipt in the module cannot run and the docstring promises a check ("reactions ... reported") that nothing performs.

### C-4. `body_accel` is silently ignored for a free body
severity: minor
lane: robustness
where: `cafe/fea.py:_solve` (`body_accel` is read only inside `if fixed is not None:`); docstring "body_accel [3] m/s^2 applied to all material"
reproduction: probe on an icosphere shell, one 100 N point load, `body_accel=[0,0,-196]` against none: `vm_p99` 765734.626365446 in both, `balance_accel` identical. Callers today pass it only with `fixed=` (`hangar.py:204`), so no number moves.
why it matters: a latent trap: the docstring gives no hint that the load is dropped, and a free-body payload case (distributed gravity against a point load) would come out wrong with no message. Same family: `thickness=None` for a shell raises `TypeError: unsupported format string passed to NoneType.__format__` from the f-string after gmsh has meshed (probe), and NaN or non-positive thickness is not checked.

### C-5. The Stage-1 sigma loses its between-window floor with two windows, where DerSimonian-Laird estimates tau^2 = 0 a third of the time
severity: minor
lane: statistics
where: `cafe/pm/stage3/refit.py:_sigma` (`... if windows < 2 and floor else tau`), `pool`
reproduction: 20,000 draws through `refit.pool` with k = 2, se 0.01 each: true between-window sd 0.05 (5 x se) gives `tau2 == 0.0` in 15.3 % of draws; true sd 0.02 (2 x se) in 33.7 %. In those draws `between = tau = 0` (the floor applies only for fewer than two windows) and sigma is sqrt(se^2 + disc^2), a few hundredths of a percent plus the discretisation floor, which is the very situation the module docstring says a single window must not be left in.
why it matters: with two windows the multiplier's spread, which Stage 1 samples, collapses to the statistical error in a sizable share of cases; k = 2 is exactly where DL has least power. The docstring says the floor guards "fewer than two windows" without saying two is no better.

### C-6. `refit.pool` accepts NaN, and the two `refit` branches disagree on a zero standard error
severity: minor
lane: robustness
where: `cafe/pm/stage3/refit.py:pool` (`(se <= 0).any()`), `refit` (`hangar` given: `cd_spread` unguarded; `hangar=None`: `max(w["cd_spread"], 1e-12)`)
reproduction: probe: `refit.pool([1.0,1.1],[nan,0.01])` returns `{'mean': nan, 'se': nan, ...}` with no error (NaN <= 0 is False). `refit.refit([dict(cd=1.0,cd_spread=0.0,cl=0,cl_spread=0)], hangar={"cd":1.0}, floor={})` raises `ValueError: standard errors must be positive`, while `refit.refit([dict(cd=1.0,cd_spread=0.0,cd_hangar=1.0)], None, {})` returns sigma 1e-12 (so a window of spread 0 enters with weight 1e24 and dominates a pool).
why it matters: a NaN spread would produce a NaN perturbation distribution for Stage 1 rather than a refusal; the clamp to 1e-12 turns one zero-spread window into the whole estimate.

### C-7. `track_heading`'s course-over-ground fallback takes the member median of raw longitudes, wrong across the antimeridian that the schema supports
severity: minor
lane: robustness
where: `cafe/pm/stage3/pipeline_windows.py:track_heading` (`lon = np.nanmedian(np.asarray(r["lon"], float), 1)`)
reproduction: probe on orca: a UAS (no heading in `res.pkl`) with two members, lons `[[179.99,-179.99],[-179.99,-179.99],[-179.98,-179.98]]`, lats rising 0.01 per record: `track_heading(res, "u", 1800.0)` = 270.006 deg, against 45.000 for the same flight at lon 10. The median of 179.99 and -179.99 is 0, then -179.99, a 180-degree jump that the wrapped difference reads as a westward leg. `config.py` allows `lon_min 165, lon_max -165` boxes.
why it matters: the UAS has no stage-1 heading, so for any mission across the dateline the UAS window's body frame and relative flow come out with a wrong heading whenever the ensemble straddles the line. (`_bow_heading` uses a circular median and is fine.)

### C-8. A killed FEA or free-surface child is always reported as a deadline kill, including an out-of-memory kill
severity: minor
lane: honesty
where: `cafe/pm/stage3/pipeline_windows.py:_fea` (`if p.returncode == -9: return killed`), `_fs_work` (`how = "killed by its watchdog at the deadline" if p.returncode == -9`)
reproduction: by reading: SIGKILL gives return code -9 whether it came from `arm_watchdog` or from the kernel's OOM killer; the row then says "killed: the FEA did not finish inside the window's remaining wall-clock slice". `freesurface.arm_watchdog` fires at `deadline - time.time()`, so a -9 well before the deadline cannot be told from it. Not run (no memory pressure was created on the shared machine).
why it matters: under proot memory is not limited (ORCA_RUNNER.md); on a 32 GB box the 6-rank free-surface child or ccx on a fine hull can be OOM-killed and the report would blame the time share, so the reader asks for a bigger `--budget` that cannot help.

### C-9. The `mass_drift_per_step` check cannot protect the pressure reference the FEA load is made from
severity: minor
lane: physics
where: `cafe/pm/stage3/windows.py:stage3_checks` (`md <= 1e-3`), `wall_pressure_pa`, `run_window` (`p = cs^2 (rho - 1) rho_f (dx/dt)^2`)
reproduction: by numbers: at `U_LAT` 0.04 the stagnation pressure is 3 x 0.5 x 0.04^2 = 2.4e-3 in lattice density. The check bounds the largest single-step relative change of the total population (1e-3 per step, so a run may drift by 0.1 over 100 steps and pass) and says nothing about the mean density offset, which enters the hull load directly because pressure is taken against a fixed reference of 1. A uniform offset of 1e-3 is a 40 % error in the dynamic wall pressure and acts as extra hydrostatic load in the FEA. No toy CFD was run.
why it matters: the name and limit read as a drift guard but test per-step noise; the pressure used for the hull is not checked against its reference.

### C-10. `vm_max` is a mesh artefact on a uniformly loaded sphere, and the stage stores it
severity: minor
lane: numerics
where: `cafe/fea.py:_solve` (`out["vm_max"] = float(vm.max())`), `windows.fea_window` (`vm_max=r["vm_max"]`)
reproduction: sphere above at h 0.02: `vm_p99` 25.68 MPa, `vm_max` 163.47 MPa (6.4 x the 25.5 MPa Lame value) for a uniform pressure with no stress concentration; the same sphere at h 0.025 and 0.04 gives max 28.3 and 29.4 (dat) so the spike is a few bad elements of one mesh. The 99th percentile hides it by design, which also means a real local concentration (wing root, a point load) is hidden the same way: on the clamped tube p99 is 13.1 MPa where the beam value at the root is 15.0.
why it matters: a stored `vm_max` varying 6x with the mesh gives the reader a figure that looks like a hot spot and is not one, while `vm_p99` can under-report a true one by about 13 %.

### C-11. The stage-3 FEA reserve is withheld from the LES kill even when the FEA is planned out
severity: minor
lane: performance
where: `cafe/pm/stage3/pipeline_windows.py:_row` (`fea_s = ... if (win_s is not None and veh.extra.get("fea")) else 0.0`, before `sizes["fea"]["runs"]` is consulted)
reproduction: under `--budget ci` the glider FEA is planned out (DECISIONS 776), yet `run_s = win_s - fea_s` still removes `fea_reserve_frac` of the slice from the LES window's safety kill; the unused reserve is then dropped.
why it matters: a slow machine kills the LES window earlier than its slice allows (a "cut" row, machine dependent) for an FEA that was never going to run.

### C-12. `run_windows` is dead code and its FEA leaves the buckling step off
severity: minor
lane: robustness
where: `cafe/pm/stage3/windows.py:run_windows` (`pool.submit(fea_window, veh, r["wall_points"], r["wall_pressure"], **(fea_kw or {}))`)
reproduction: the only caller is `tests/test_stage3.py::test_run_windows_overlaps_fea_with_the_next_les_window`; the pipeline calls `_fea_child`, which passes `buckle=True`. Through `run_windows` the utilization is stress-only unless the caller adds `fea_kw={"buckle": True}`.
why it matters: it is exactly the stress-only value that round 14 M-31 and DECISIONS 792 removed from the pipeline; a future caller of this public function gets it back.

### C-13. The FEA and equations of `fea.py` have no section in `docs/PHYSICS.md`
severity: minor
lane: documentation
where: `docs/PHYSICS.md` (only line 992 mentions the FEA, as a bullet); `cafe/fea.py` (mean-rigid-motion equations, hand inertia relief, OFFSET 0.5 choice, 3/4 follower factor, `vm_p99`, nodal-mapping of the expanded shell)
reproduction: `grep -n -i "follower\|mean rigid\|rigid motion\|OFFSET\|0.75" docs/PHYSICS.md` finds none of them; the explanation exists only in code comments. The brief for this lane is "every equation against docs/PHYSICS.md and its cited source".
why it matters: the equations behind every hull number have no cited derivation to check; the 3/4 factor and its n = 2 basis (C-2) are visible only to a reader of the source.

### C-14. `stage3.fea_min_s` cites a hull that is not the default
severity: minor
lane: documentation
where: `config/assumptions.yaml` `stage3.fea_min_s` `why` ("ellipsoid 1.8 m x 0.15 m, 7 mm Al, h = L/20, 1,408 elements"), against `stage3.glider.hull_diameter_m` 0.30 and `hull_thickness_m` 0.008
reproduction: the run above on the current defaults (1.8 x 0.30 m, 8 mm, L/20) gives 1,408 elements and 65 s, so the number is right but the stated hull (0.15 m, 7 mm) is not the one that produced it (the element count equals the 0.30 m case; PHYSICS.md 992 says 8 mm).
why it matters: the input's provenance is wrong in the one place a reader checks it; at L/45 the same hull takes 449 s, so the floor does not carry to a finer mesh (C-1) either.

## Read and found sound (no finding)

- `lbm.py`: D3Q19 weights and `feq`; `moments`; the regularised collision (`4.5 w (Q:Pi - tr/3)`); Hou et al. Smagorinsky `tau`; halfway and Bouzidi bounce-back, including the 1/(2q) on the wall term and the momentum-exchange sum; `specular`; `ellipsoid_q` (smallest entering root, outside start); `les_resolution` (0.37 L Re^-1/5, cf 0.0592 Re^-1/5, y+ at 2.5 dx); Morrison's correlation; Taylor-Green decay law and initial density; `store` half-precision form; memory model.
- `windows.py`: lift axis and sign for the wing window (checked the body-frame flow sign with a = 0.5 deg trim by hand), `coefficients` batch means, wall-pressure scaling `cs^2 (rho-1) rho_f (dx/dt)^2`, `wall_hook`, the `raised` viscosity test (same expression as `NestSpec.nu_lat`).
- `pipeline_windows.py`: `uas_leg_speed` interval, `v_max = g tan(tilt)/d_x`, glider glide-angle sign (negative descending), USV frames and hull_fs displacement, `fit_window` fourth-root coarsening.
- `freesurface.py`: keel overlap, `refined_cells`, `row_fields` coefficient and spread, the GRIDS pair; the refinement ratio from cell counts is the documented weak point (the check's note says so).
- `fea.py`: inertia relief algebra (`I = tr I - I`, `alpha = I^-1 (M - com x F)`, d'Alembert nodal forces), `_tet_boundary`, `_frd` fixed-width parse, the `jacobian` retry order.

## Not reached

The buckling modes' lobe count on the glider hull, the nest/wall-model files (not in scope), any CFD beyond reading.

total: 14 findings (0 critical, 1 major, 13 minor)
