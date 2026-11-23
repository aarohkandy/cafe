# Scale ladder: the demo Seaglider's CPU RANS case at reduced Reynolds numbers

Question: is the form factor (drag over a flat-plate friction line) steady with Reynolds number for the solver's own case? Answer: no. See "Steadiness" below.

Measured on orca, branch scale-ladder (script commit after e297127). Script `review/workorder/rans_probe.py --levels 0 1 --iters 600 --speed-factor F --cores 6`
(PM_CPUS=6), tables by `review/workorder/ladder_table.py`; every number below is from the `result.json` of `~/cafe-worker/cafe/pmdata/runs/rans_ladder_<name>/` and the
solver logs next to it (the raw lines are at the end). Same shape (1332-triangle union STL of the hull ellipsoid and the plate wing, watertight), same label
x-z5.29, same two grids (level offsets 0 and 1 = levels 6 and 7), k-omega SST, 600-iteration cap, at every rung. F = Re / 2.04e5.
Solver nu = 1.19e-6 (`cafe/cfd.py` FLUIDS, `nu` in `transportProperties`), the same as `stage3/windows.py` NU; solver rho 1025. L = 1.8 m (STL's longest extent 1.79999995 m),
Re = U L / nu: the control's Re is 2.045e5, so F = Re_target / 2.04e5 gives 8.02e4, 4.01e4, 2.005e4 and 1.002e4 (0.25 % over the round numbers).
A_ref = 0.070686 m2 (ref_area). cd = fine-grid drag / (0.5 rho U^2 A_ref).

## The table (fine grid = level 7, 1.28 M cells; coarse = level 6, 0.316 M cells; refinement ratio 1.596 on every rung)

| Re (L) | F | U m/s | cells coarse / fine | failed mesh checks | iterations coarse / fine | seconds (both grids) | drag N (fine) | cd (fine) | GCI | drag scatter, fine (tail std / mean) | y+ |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2.045e5 (control, F = 1) | 1 | 0.13520 | 315,938 / 1,284,890 | 0 / 0 | 600 / 600 | 890 | 0.24758 | 0.3739 | 0.0807 | 0.0061 | not in the logs |
| 8.02e4 | 0.392157 | 0.05302 | 315,994 / 1,284,246 | 0 / 0 | 600 / 600 | 898 | 0.04021 | 0.3948 | 0.0805 | 0.0059 | not in the logs |
| 4.01e4 | 0.196078 | 0.02651 | 315,896 / 1,284,995 | 0 / 0 | 271 / 600 | 790 | 0.01153 | 0.4530 | 0.0229 | 0.0052 | not in the logs |
| 2.005e4 | 0.098039 | 0.01325 | 315,966 / 1,284,015 | 0 / 0 | 258 / 600 | 786 | 0.00335 | 0.5259 | 0.0478 | 0.0019 | not in the logs |
| 1.002e4 | 0.04902 | 0.00663 | 315,840 / 1,284,701 | 0 / 0 | 145 / 193 | 289 | 0.00105 | 0.6588 | 0.0603 | 0.0000 (stopped by the residual control) | not in the logs |

| Re (L) | cf ITTC-57 | cf Blasius | ff ITTC-57 on S_stl | ff Blasius on S_stl | ff ITTC-57 on S_ref | ff Blasius on S_ref |
|---|---|---|---|---|---|---|
| 2.045e5 | 0.006838 | 0.002937 | 2.3556 | 5.4887 | 2.3514 | 5.4789 |
| 8.02e4 | 0.008894 | 0.004690 | 1.9140 | 3.6295 | 1.9106 | 3.6230 |
| 4.01e4 | 0.01107 | 0.006632 | 1.7643 | 2.9445 | 1.7612 | 2.9393 |
| 2.005e4 | 0.01415 | 0.009380 | 1.6019 | 2.4171 | 1.5990 | 2.4128 |
| 1.002e4 | 0.01873 | 0.01326 | 1.5163 | 2.1412 | 1.5136 | 2.1374 |

- ff = cd A_ref / (S_wet cf) = drag / (0.5 rho U^2 S_wet cf). cf ITTC-57 = 0.075 / (log10 Re - 2)^2; cf Blasius = 1.328 / sqrt(Re); Re on L = 1.8 m for both.
- Two wetted areas, labelled: **S_stl = 1.63976 m2**, the trimesh area of the STL actually meshed (`info.stl_area_m2`); **S_ref = 1.6427 m2**, the other solver's analytic area
  (hull ellipsoid 1.3411 m2 by `pipeline_windows.ellipsoid_area` plus both faces and four edges of the wing outside the hull), given to me as a number. S_stl is 0.00294 m2
  (0.18 %) below S_ref, so every ff on S_stl is 0.18 % above the one on S_ref. I did not check why: a faceted ellipsoid (1332 triangles in all) has less area than the smooth one, which would
  go that way, but I did not compute it, and I did not recompute 1.3411 or the wing's part.
- "drag scatter" is the true std of the drag (the force projected on the flow direction) over the last 20 % of the fine grid's force history, divided by its mean (`drag_tail_std_rel`).
  The older `scatter` figure (norm of `force_std` over the drag, mostly lift) is in the result files: 0.10, 0.12, 0.14, 0.04, 0.00 for the five rungs; it is not the drag scatter.
- GCI is the one `cfd.gci` gives from the two drags and the ratio, order 2 assumed, as in the earlier probe (its note: the 3-level drag was not monotone at this Reynolds number).
- y+ is not in the logs: the case has no yPlus function object, the case dirs were shrunk (fields deleted) and I changed no product code, so it is not available for any rung. Not measured.

## Control against the earlier measurements

F = 1 reproduces the earlier runs of the same setting: cd 0.3739 here, 0.3726 (cfdprobe g4, 6 cores, 600 iterations) and 0.3729 (fin1, the pipeline's case); GCI 0.0807 here, 0.0903 (g4)
and 0.086 (fin1); fine-grid drag 0.24758 N here, 0.24669 N (g4). The differences are 0.3 % in cd and 0.4 % in drag, about the run-to-run spread cfdprobe.md reports (0.3 %, a different domain split each time).

## Did the drag settle? Reruns

No rerun was needed (0 of 2 used). From each case's `force.dat`, the mean of the drag in each block of 100 iterations (N), fine grid:
control 0.27307, 0.24762, 0.24618, 0.24731, 0.24765, 0.24740; 8.02e4: 0.04751, 0.04037, 0.04017, 0.04002, 0.04032, 0.04015; 4.01e4: 0.01425, 0.01152, 0.01157, 0.01157, 0.01155, 0.01154;
2.005e4: 0.00451, 0.00336, 0.00335, 0.00335, 0.00335, 0.00335; 1.002e4: 0.00154 over its 193 iterations (one 100-block). After the first 100 iterations (start-up) the
drag stays within 1 % of its later value on every rung of 600 iterations. The coarse grids at 4.01e4 (271 iterations), 2.005e4 (258) and 1.002e4 (145) stopped by the SIMPLE residual control ("SIMPLE solution converged"),
and so did the 1.002e4 fine grid (193); the other fine grids ran to the cap (initial residuals at the end: Uy 4e-3 to 9e-3, p 1e-5, k 5e-5 to 1.5e-3), as in the earlier probe. The 1.002e4 coarse and fine drags have no 100-iteration tail: their "tail std" is at the 20-iteration minimum of `cfd.tail_stats` and is 0.0000.

## Steadiness of the form factor across the five rungs

(max |ff_i / mean - 1| over the five; slope of ln ff on ln Re by least squares, with its standard error on 3 degrees of freedom, `rans_probe.loglog_slope`; the area changes ff by a constant, so it changes neither number)

| line, area | mean ff | max abs(ff/mean - 1) | slope d ln ff / d ln Re | within 10 %? |
|---|---|---|---|---|
| ITTC-57, S_stl | 1.8304 | 28.7 % | +0.1445 +- 0.0157 | no |
| Blasius, S_stl | 3.3242 | 65.1 % | +0.3118 +- 0.0300 | no |
| ITTC-57, S_ref | 1.8272 | 28.7 % | +0.1445 +- 0.0157 | no |
| Blasius, S_ref | 3.3183 | 65.1 % | +0.3118 +- 0.0300 | no |

The form factor is not steady on either line; it falls monotonically as the Reynolds number falls (ITTC-57: 2.36, 1.91, 1.76, 1.60, 1.52 from the control down). By the addendum's rule (section 8, item 3) the rungs
are reported and nothing is extrapolated to a physical Reynolds number from them. The ITTC line is the nearer to steady, and the slope +0.14 +- 0.02 is many standard errors from zero.

## Pressure and viscous parts of the drag (fine grid, tail mean of `postProcessing/forces`; pressure + viscous = drag to 4 digits on every rung)

| Re (L) | pressure N | viscous N | pressure share | pressure / (q S_stl) | viscous / (q S_stl) | viscous coeff over cf ITTC-57 | over cf Blasius |
|---|---|---|---|---|---|---|---|
| 2.045e5 | 0.16791 | 0.07967 | 0.678 | 0.01093 | 0.00519 | 0.758 | 1.766 |
| 8.02e4 | 0.02569 | 0.01452 | 0.639 | 0.01087 | 0.00615 | 0.691 | 1.311 |
| 4.01e4 | 0.00651 | 0.00502 | 0.565 | 0.01103 | 0.00850 | 0.768 | 1.281 |
| 2.005e4 | 0.00159 | 0.00176 | 0.474 | 0.01075 | 0.01192 | 0.843 | 1.271 |
| 1.002e4 | 0.00041 | 0.00064 | 0.387 | 0.01098 | 0.01742 | 0.930 | 1.313 |

(q = 0.5 rho U^2 with the solver's rho 1025.) The pressure drag in the dynamic-pressure-times-area form is constant to within 2 % of 0.0109 at every rung (0.01075 to 0.01103), it does not follow the friction line.
The viscous part falls with Re roughly as a flat-plate law (0.69 to 0.93 of ITTC-57; 1.27 to 1.77 of Blasius, no constant ratio on either). So the drag is roughly "constant pressure coefficient + friction", and a
multiplicative form factor cannot describe it: ff = (P + V) / V_plate, and the P / V_plate part grows as the friction falls with Re.

## What the numbers show and what they do not

- Show: for this solver (OpenFOAM simpleFoam, k-omega SST, wall functions, this hull and plate wing, 7 mm and 3.5 mm surface cells) the form factor on either line drifts by 29 % (ITTC-57) to 65 % (Blasius) between Re 1e4 and 2e5, and the drift
  comes from a pressure drag that is steady in q A while the friction is not. It is larger than the grid error of each rung (GCI 0.02 to 0.08).
- Do not show: k-omega SST is fully turbulent at every rung, so these are the turbulent solver's own form factors even at Re 1e4, where a real hull of this shape would be laminar or transitional; the rungs say nothing about a laminar hull, and
  nothing about the physical Reynolds number or an LES/LBM window. The drift may be the solver's turbulence model and wall treatment at low Re as much as a property of the hull: I did not separate the two (no other model, no wall-resolved run).
- Not verified: y+ (not in the logs; if the wall-function mesh is outside its range at the low rungs, the viscous part is off); grid convergence beyond the two-grid GCI (the earlier probe's three levels were not monotone); the S_ref value 1.6427 and its wing part (given, not recomputed);
  that the 0.18 % area gap is faceting; repeatability of each rung (one run per rung, the control's spread against earlier runs is 0.3 %); the early residual stops at 1.002e4, 2.005e4, 4.01e4 (coarse) as converged states rather than premature ones (the drag blocks are flat, the stops are the solver's own criterion).
- Cost: the 600-iteration pair took 786 to 898 s on 6 cores at the four rungs that ran to the cap on the fine grid (4.01e4 and 2.005e4 stopped the coarse grid early), 289 s at 1.002e4. Up to two cases ran at once, 6 cores each.

## Raw rows (output of `ladder_table.py`)

rans_ladder_ctl: Re 2.045e+05 U 0.13520 cells 315938/1284890 failed 0/0 it 600/600 s 890 drag 0.24758 (coarse 0.25789) cd 0.3739 GCI 0.0807 ratio 1.596 std_rel 0.0072/0.0061 scatter 0.1008 P 0.16791 V 0.07967 cf 0.00684/0.00294 ff(stl) 2.3556/5.4887 ff(1.6427) 2.3514/5.4789
rans_ladder_re80k: Re 8.019e+04 U 0.05302 cells 315994/1284246 failed 0/0 it 600/600 s 898 drag 0.04021 (coarse 0.04187) cd 0.3948 GCI 0.0805 ratio 1.596 std_rel 0.0036/0.0059 scatter 0.1157 P 0.02569 V 0.01452 cf 0.00889/0.00469 ff(stl) 1.9140/3.6295 ff(1.6427) 1.9106/3.6230
rans_ladder_re40k: Re 4.01e+04 U 0.02651 cells 315896/1284995 failed 0/0 it 271/600 s 790 drag 0.01153 (coarse 0.01140) cd 0.4530 GCI 0.0229 ratio 1.596 std_rel 0.0000/0.0052 scatter 0.1362 P 0.00651 V 0.00502 cf 0.01107/0.00663 ff(stl) 1.7643/2.9445 ff(1.6427) 1.7612/2.9393
rans_ladder_re20k: Re 2.005e+04 U 0.01325 cells 315966/1284015 failed 0/0 it 258/600 s 786 drag 0.00335 (coarse 0.00343) cd 0.5259 GCI 0.0478 ratio 1.596 std_rel 0.0000/0.0019 scatter 0.0391 P 0.00159 V 0.00176 cf 0.01415/0.00938 ff(stl) 1.6019/2.4171 ff(1.6427) 1.5990/2.4128
rans_ladder_re10k: Re 1.002e+04 U 0.00663 cells 315840/1284701 failed 0/0 it 145/193 s 289 drag 0.00105 (coarse 0.00108) cd 0.6588 GCI 0.0603 ratio 1.596 std_rel 0.0000/0.0000 scatter 0.0000 P 0.00041 V 0.00064 cf 0.01873/0.01326 ff(stl) 1.5163/2.1412 ff(1.6427) 1.5136/2.1374

ff_ittc57: mean 1.8304 max|ff/mean-1| 0.2869 slope +0.1445 +- 0.0157 (n=5)
ff_blasius: mean 3.3242 max|ff/mean-1| 0.6511 slope +0.3118 +- 0.0300 (n=5)
ff_ittc57_on_s_wet_other: mean 1.8272 max|ff/mean-1| 0.2869 slope +0.1445 +- 0.0157 (n=5)
ff_blasius_on_s_wet_other: mean 3.3183 max|ff/mean-1| 0.6511 slope +0.3118 +- 0.0300 (n=5)
