# Laptop GPU rungs (FluidX3D, TRT, FP16S, no wall model): raw results from out

A glider rung enters the ladder only if its status is done, it ran on the plain build (no subgrid model) and cd is steady at the end: sd over the last 40 % at most 1% of the mean and drift between the last two fifths at most 0.5%. Runs with the Smagorinsky subgrid model (names ending _sgs) are listed apart and never enter it.

| case | status | Re_L | cells along L | across D | steps run | cd mean | sd / mean (last 40 %) | drift, last two fifths | if not done: partial cd |
|---|---|---|---|---|---|---|---|---|---|
| seaglider_re0.105k_n108 | done | 105 | 108 | 18.0 | 14400 of 14400 | 8.4733 | 0.0002 | -0.0000 |  |
| seaglider_re0.105k_n108_a0 | done | 105 | 108 | 18.0 | 14400 of 14400 | 8.3808 | 0.0001 | +0.0001 |  |
| seaglider_re0.105k_n144 | done | 105 | 144 | 24.0 | 19200 of 19200 | 8.4276 | 0.0001 | -0.0001 |  |
| seaglider_re0.105k_n72 | done | 105 | 72 | 12.0 | 9600 of 9600 | 8.4404 | 0.0002 | +0.0002 |  |
| seaglider_re0.105k_n72_a0 | done | 105 | 72 | 12.0 | 9600 of 9600 | 8.3401 | 0.0002 | +0.0004 |  |
| seaglider_re0.105k_n72_big | done | 105 | 72 | 12.0 | 9600 of 9600 | 8.2094 | 0.0002 | +0.0003 |  |
| seaglider_re0.105k_n72_huge | done | 105 | 72 | 12.0 | 9600 of 9600 | 8.1630 | 0.0006 | +0.0000 |  |
| seaglider_re0.105k_n72_xlong | done | 105 | 72 | 12.0 | 9600 of 9600 | 8.3056 | 0.0002 | -0.0001 |  |
| seaglider_re0.16k_n108 | done | 160 | 108 | 18.0 | 14400 of 14400 | 6.5135 | 0.0003 | +0.0006 |  |
| seaglider_re0.16k_n108_a0 | done | 160 | 108 | 18.0 | 14400 of 14400 | 6.4259 | 0.0001 | +0.0002 |  |
| seaglider_re0.16k_n144 | done | 160 | 144 | 24.0 | 19200 of 19200 | 6.5397 | 0.0003 | +0.0000 |  |
| seaglider_re0.16k_n72 | done | 160 | 72 | 12.0 | 9600 of 9600 | 6.4444 | 0.0006 | +0.0008 |  |
| seaglider_re0.16k_n72_a0 | done | 160 | 72 | 12.0 | 9600 of 9600 | 6.3663 | 0.0003 | +0.0004 |  |
| seaglider_re0.16k_n72_big | done | 160 | 72 | 12.0 | 9600 of 9600 | 6.2977 | 0.0011 | -0.0005 |  |
| seaglider_re0.16k_n72_huge | done | 160 | 72 | 12.0 | 9600 of 9600 | 6.2950 | 0.0002 | +0.0002 |  |
| seaglider_re0.24k_n108 | done | 240 | 108 | 18.0 | 14400 of 14400 | 5.0913 | 0.0005 | +0.0004 |  |
| seaglider_re0.24k_n108_a0 | done | 240 | 108 | 18.0 | 14400 of 14400 | 5.0198 | 0.0001 | +0.0002 |  |
| seaglider_re0.24k_n144 | done | 240 | 144 | 24.0 | 19200 of 19200 | 5.1357 | 0.0004 | +0.0004 |  |
| seaglider_re0.24k_n72 | done | 240 | 72 | 12.0 | 9600 of 9600 | 5.0492 | 0.0007 | +0.0013 |  |
| seaglider_re0.24k_n72_a0 | done | 240 | 72 | 12.0 | 9600 of 9600 | 4.9522 | 0.0005 | +0.0004 |  |
| seaglider_re0.24k_n72_big | done | 240 | 72 | 12.0 | 9600 of 9600 | 4.9508 | 0.0002 | +0.0004 |  |
| seaglider_re0.24k_n72_huge | done | 240 | 72 | 12.0 | 9600 of 9600 | 4.9299 | 0.0003 | +0.0001 |  |
| seaglider_re0.36k_n108 | done | 360 | 108 | 18.0 | 14400 of 14400 | 4.0256 | 0.0006 | +0.0003 |  |
| seaglider_re0.36k_n108_a0 | done | 360 | 108 | 18.0 | 14400 of 14400 | 3.9517 | 0.0007 | +0.0001 |  |
| seaglider_re0.36k_n144 | done | 360 | 144 | 24.0 | 19200 of 19200 | 4.0610 | 0.0009 | +0.0003 |  |
| seaglider_re0.36k_n72 | done | 360 | 72 | 12.0 | 9600 of 9600 | 3.9825 | 0.0003 | +0.0005 |  |
| seaglider_re0.36k_n72_a0 | done | 360 | 72 | 12.0 | 9600 of 9600 | 3.9119 | 0.0004 | +0.0000 |  |
| seaglider_re0.36k_n72_big | done | 360 | 72 | 12.0 | 9600 of 9600 | 3.9051 | 0.0009 | +0.0001 |  |
| seaglider_re0.36k_n72_huge | done | 360 | 72 | 12.0 | 9600 of 9600 | 3.9088 | 0.0001 | +0.0001 |  |
| seaglider_re0.55k_n108 | done | 550 | 108 | 18.0 | 14400 of 14400 | 3.1725 | 0.0008 | -0.0007 |  |
| seaglider_re0.55k_n108_a0 | done | 550 | 108 | 18.0 | 14400 of 14400 | 3.0951 | 0.0011 | -0.0005 |  |
| seaglider_re0.55k_n144 | done | 550 | 144 | 24.0 | 19200 of 19200 | 3.1970 | 0.0009 | +0.0001 |  |
| seaglider_re0.55k_n72 | done | 550 | 72 | 12.0 | 9600 of 9600 | 3.1564 | 0.0004 | +0.0007 |  |
| seaglider_re0.55k_n72_a0 | done | 550 | 72 | 12.0 | 9600 of 9600 | 3.0747 | 0.0009 | +0.0010 |  |
| seaglider_re0.55k_n72_big | done | 550 | 72 | 12.0 | 9600 of 9600 | 3.0985 | 0.0001 | +0.0001 |  |
| seaglider_re0.55k_n72_huge | done | 550 | 72 | 12.0 | 9600 of 9600 | 3.0905 | 0.0002 | +0.0003 |  |
| seaglider_re0.55k_n72_xlong | done | 550 | 72 | 12.0 | 9600 of 9600 | 3.1209 | 0.0004 | +0.0006 |  |
| seaglider_re0.8k_n108 | done | 800 | 108 | 18.0 | 14400 of 14400 | 2.5897 | 0.0007 | -0.0000 |  |
| seaglider_re0.8k_n108_long | done | 800 | 108 | 18.0 | 43200 of 43200 | 2.5875 | 0.0010 | -0.0003 |  |
| seaglider_re0.8k_n144 | done | 800 | 144 | 24.0 | 19200 of 19200 | 2.6025 | 0.0012 | -0.0002 |  |
| seaglider_re0.97k_n108_limit | diverged | 970 | 108 | 18.0 | 2400 of 14400 | nan | 0.0088 | -0.0167 | 2.3836 over 5 samples, up to step 2400 |
| seaglider_re1.1k_n144 | done | 1100 | 144 | 24.0 | 19200 of 19200 | 2.2041 | 0.0007 | -0.0004 |  |
| slocum_re0.105k_n108 | done | 105 | 108 | 15.8 | 14400 of 14400 | 10.0876 | 0.0000 | -0.0000 |  |
| slocum_re0.105k_n72 | done | 105 | 72 | 10.6 | 9600 of 9600 | 10.0596 | 0.0002 | +0.0004 |  |
| slocum_re0.105k_n72_big | done | 105 | 72 | 10.6 | 9600 of 9600 | 9.8299 | 0.0001 | +0.0001 |  |
| slocum_re0.105k_n72_huge | done | 105 | 72 | 10.6 | 9600 of 9600 | 9.8013 | 0.0001 | +0.0000 |  |
| slocum_re0.16k_n108 | done | 160 | 108 | 15.8 | 14400 of 14400 | 7.7443 | 0.0000 | +0.0000 |  |
| slocum_re0.16k_n72 | done | 160 | 72 | 10.6 | 9600 of 9600 | 7.6521 | 0.0005 | +0.0008 |  |
| slocum_re0.16k_n72_big | done | 160 | 72 | 10.6 | 9600 of 9600 | 7.5256 | 0.0005 | +0.0009 |  |
| slocum_re0.16k_n72_huge | done | 160 | 72 | 10.6 | 9600 of 9600 | 7.5054 | 0.0001 | +0.0002 |  |
| slocum_re0.24k_n108 | done | 240 | 108 | 15.8 | 14400 of 14400 | 6.0386 | 0.0004 | +0.0005 |  |
| slocum_re0.24k_n72 | done | 240 | 72 | 10.6 | 9600 of 9600 | 5.9780 | 0.0003 | +0.0003 |  |
| slocum_re0.24k_n72_big | done | 240 | 72 | 10.6 | 9600 of 9600 | 5.8740 | 0.0002 | +0.0004 |  |
| slocum_re0.24k_n72_huge | done | 240 | 72 | 10.6 | 9600 of 9600 | 5.8725 | 0.0000 | +0.0000 |  |
| slocum_re0.36k_n108 | done | 360 | 108 | 15.8 | 14400 of 14400 | 4.7443 | 0.0009 | -0.0005 |  |
| slocum_re0.36k_n72 | done | 360 | 72 | 10.6 | 9600 of 9600 | 4.7090 | 0.0003 | -0.0004 |  |
| slocum_re0.36k_n72_big | done | 360 | 72 | 10.6 | 9600 of 9600 | 4.6395 | 0.0003 | +0.0004 |  |
| slocum_re0.36k_n72_huge | done | 360 | 72 | 10.6 | 9600 of 9600 | 4.6237 | 0.0004 | +0.0006 |  |
| slocum_re0.55k_n108 | done | 550 | 108 | 15.8 | 14400 of 14400 | 3.7210 | 0.0011 | +0.0001 |  |
| slocum_re0.55k_n72 | done | 550 | 72 | 10.6 | 9600 of 9600 | 3.7047 | 0.0006 | -0.0002 |  |
| slocum_re0.55k_n72_big | done | 550 | 72 | 10.6 | 9600 of 9600 | 3.6425 | 0.0013 | -0.0013 |  |
| slocum_re0.55k_n72_huge | done | 550 | 72 | 10.6 | 9600 of 9600 | 3.6374 | 0.0009 | -0.0006 |  |
| sphere_re100_d16_w12 | done | 100 | 16 | 16.0 | 10600 of 10600 | 1.1463 | 0.0007 | +0.0005 |  |
| sphere_re100_d24 | done | 100 | 24 | 24.0 | 16000 of 16000 | 1.1582 | 0.0004 | -0.0003 |  |
| sphere_re100_d32 | done | 100 | 32 | 32.0 | 21400 of 21400 | 1.1664 | 0.0011 | +0.0013 |  |
| sphere_re200_d24 | done | 200 | 24 | 24.0 | 16000 of 16000 | 0.8322 | 0.0007 | -0.0009 |  |
| smoke_sphere_re100_d16 | no summary (killed or still running) | nan |  | nan | ? of ? | nan | 0.0008 | -0.0013 | 1.1641 over 9 samples, up to step 4400 |

## Smagorinsky subgrid runs: NOT laminar-resolved values at the stated Reynolds number, never in the ladder

The subgrid model adds eddy viscosity where the grid cannot hold the gradients, so the effective Reynolds number is lower than the label and unknown. Listed only as a record.

- seaglider_re0.55k_n72_sgs: status done, cd 3.2647 +- 0.0005 (sd / mean 0.00), cl 0.6487

## Proof on a sphere (textbook cd, unbounded: about 1.09 at Re 100, 0.77 at Re 200, 0.47 at Re 1000; the box is 6 D wide unless the name ends _w12, 12 D)

- sphere_re100_d16_w12: cd 1.1463 with 16 cells across, +5.2 % against 1.09
- sphere_re100_d24: cd 1.1582 with 24 cells across, +6.3 % against 1.09
- sphere_re100_d32: cd 1.1664 with 32 cells across, +7.0 % against 1.09
- sphere_re200_d24: cd 0.8322 with 24 cells across, +8.1 % against 0.77
- Re 100, 6 D box: from 24 to 32 cells across cd goes 1.1582 -> 1.1664, AWAY FROM the reference: the bias is not a resolution error that refining removes

## seaglider: hull ellipsoid plus plate wing, reduced-Reynolds rungs (the physical Re_L is 2.04e+05)

A_ref = pi D^2/4 = 0.070686 m2. S_wet = 1.7111 m2 (analytic: hull ellipsoid 1.3411 + both faces and the edges of the 50 mm plate wing outside the hull, as modelled; the real body, with its 12 mm plate, has 1.6427 m2, so the ff values here are about 4 % low against the real body's; the scaled cd does not depend on S_wet). ITTC-57 is printed beside Blasius as asked; at these Reynolds numbers neither applies.

**Box checks** (coarse grid; base = the ladder's box, big = 1.5 x wider and higher with longer clearances, huge = 1.75 x wider and higher with the same longer clearances; both change the lateral and the up/downstream clearance at once, so the two effects are not separated):

| Re_L | grid | cd base box | cd big | cd huge | big / base - 1 | huge / base - 1 | huge / big - 1 |
|---|---|---|---|---|---|---|---|
| 105 | 72 | 8.4404 | 8.2094 | 8.1630 | -0.0274 | -0.0329 | -0.0056 |
| 160 | 72 | 6.4444 | 6.2977 | 6.2950 | -0.0228 | -0.0232 | -0.0004 |
| 240 | 72 | 5.0492 | 4.9508 | 4.9299 | -0.0195 | -0.0236 | -0.0042 |
| 360 | 72 | 3.9825 | 3.9051 | 3.9088 | -0.0195 | -0.0185 | +0.0010 |
| 550 | 72 | 3.1564 | 3.0985 | 3.0905 | -0.0183 | -0.0209 | -0.0026 |

The ladder below uses the finest grid's cd times the coarse grid's (largest box / base box) ratio where a box check ran, and adds the change between the two largest boxes (or base to big, if only one ran) to the error as the box error.

| Re_L | cd by grid (base box) | cd (finest) | grid error | how | box factor | box error | cd used | ff Blasius | ff ITTC-57 |
|---|---|---|---|---|---|---|---|---|---|
| 105 | n72: 8.4404, n108: 8.4733, n144: 8.4276 | 8.4276 | 0.0457 | three grids, NOT monotone: the spread, not a GCI | 0.9671 | 0.0448 | 8.1507 | 2.598 | 0.002 |
| 160 | n72: 6.4444, n108: 6.5135, n144: 6.5397 | 6.5397 | 0.0267 | three grids, monotone: GCI (Fs 1.25, observed order clipped to 2.78) | 0.9768 | 0.0026 | 6.3881 | 2.514 | 0.147 |
| 240 | n72: 5.0492, n108: 5.0913, n144: 5.1357 | 5.1357 | 0.3589 | three grids, monotone: GCI (Fs 1.25, observed order clipped to 0.50) | 0.9764 | 0.0207 | 5.0144 | 2.416 | 0.399 |
| 360 | n72: 3.9825, n108: 4.0256, n144: 4.0610 | 4.0610 | 0.2537 | three grids, monotone: GCI (Fs 1.25, observed order clipped to 0.56) | 0.9815 | 0.0037 | 3.9858 | 2.352 | 0.679 |
| 550 | n72: 3.1564, n108: 3.1725, n144: 3.1970 | 3.1970 | 0.0726 | three grids, monotone: GCI (Fs 1.25, observed order clipped to 1.23) | 0.9791 | 0.0080 | 3.1302 | 2.284 | 0.945 |
| 800 | n108: 2.5897, n144: 2.6025 | 2.6025 | 0.0128 | two grids: the difference | 1.0000 | nan | 2.6025 | 2.290 | 1.169 |
| 1100 | n144: 2.2041 | 2.2041 | nan | one grid: no grid error | 1.0000 | nan | 2.2041 | 2.274 | 1.317 |

**laminar (Blasius).** (grid error plus box error per rung in the floor) mean ff 2.390. Gates at 0.1: (a) ff constancy across rungs 0.087 pass; (b) bracket 0.857 FAIL (ff constant gives cd 0.1700, cd constant gives 2.2041); (c) slope -0.058 +- 0.007 per ln Re, reach 0.344 FAIL.
DIAGNOSTIC ONLY (the top rung is below Re_L 1e+04, where no friction line applies): cd at the physical Re on this line = 0.1700 +- 1.0788 (pooled 0.0090, grid and box floor 0.3595, bracket half-width 1.0170). fin1: analytic model 0.3014, CPU RANS 0.3729.

**turbulent (ITTC-57).** (grid error plus box error per rung in the floor) mean ff 0.665. Gates at 0.1: (a) ff constancy across rungs 0.997 FAIL; (b) bracket 0.905 FAIL (ff constant gives cd 0.1103, cd constant gives 2.2041); (c) slope +2.236 +- 0.660 per ln Re, reach 15.124 FAIL.
DIAGNOSTIC ONLY (the top rung is below Re_L 1e+04, where no friction line applies): cd at the physical Re on this line = 0.1103 +- 1.1101 (pooled 0.0838, grid and box floor 0.3595, bracket half-width 1.0469). fin1: analytic model 0.3014, CPU RANS 0.3729.

**Two-term fit, cd = a + b x cf(Re)** (the lead's suggestion: a is the part that does not change with Reynolds number, b x cf the part that does).
- Blasius: a = -0.5766, b = 66.51, rms misfit 0.0872; predicts cd -0.3812 at the physical Re; fitted without the top rung it predicts that rung as 2.0234 against 2.2041 (-8.2 %).
- ITTC-57: a = 3.8705, b = 0.03, rms misfit 1.3281; predicts cd 3.8707 at the physical Re; fitted without the top rung it predicts that rung as 4.2079 against 2.2041 (+90.9 %).

**Beside the turbulent RANS rungs** (the lead's simpleFoam k-omega SST on the same shape):

| Re_L | this solver, laminar-resolved (finest grid) | RANS, turbulent model | ratio |
|---|---|---|---|
| 1e+04 | not run | 0.6588 |  |
| 2e+04 | not run | 0.5259 |  |
| 4e+04 | not run | 0.4530 |  |
| 8e+04 | not run | 0.3948 |  |
| 2.045e+05 | not run | 0.3739 |  |

Steadiness check: seaglider_re0.8k_n108 over 10 body lengths of flow gives cd 2.58966; over 30, 2.58755 (-0.081 %).

Known ways this fails: the solver is stable only up to a cell Reynolds number of about 8 (Re_L / cells along L), so with the grids the laptop holds the rungs stop near Re_L 800, 250 times below the physical value, where the boundary layer is a third of the body length thick and the box still matters; the plate wing is 4 times thicker than the real one (2 cells of the coarse grid) so both grids see one shape; the 5.3 deg (Seaglider) angle of attack puts pressure and induced drag in cd that no friction line scales.

## slocum: hull ellipsoid plus plate wing, reduced-Reynolds rungs (the physical Re_L is 2.84e+05)

A_ref = pi D^2/4 = 0.038013 m2. S_wet = 1.0258 m2 (analytic: hull ellipsoid 0.8170 + both faces and the edges of the 42 mm plate wing outside the hull, as modelled; the real body, with its 12 mm plate, has 0.9821 m2, so the ff values here are about 4 % low against the real body's; the scaled cd does not depend on S_wet). ITTC-57 is printed beside Blasius as asked; at these Reynolds numbers neither applies.

**Box checks** (coarse grid; base = the ladder's box, big = 1.5 x wider and higher with longer clearances, huge = 1.75 x wider and higher with the same longer clearances; both change the lateral and the up/downstream clearance at once, so the two effects are not separated):

| Re_L | grid | cd base box | cd big | cd huge | big / base - 1 | huge / base - 1 | huge / big - 1 |
|---|---|---|---|---|---|---|---|
| 105 | 72 | 10.0596 | 9.8299 | 9.8013 | -0.0228 | -0.0257 | -0.0029 |
| 160 | 72 | 7.6521 | 7.5256 | 7.5054 | -0.0165 | -0.0192 | -0.0027 |
| 240 | 72 | 5.9780 | 5.8740 | 5.8725 | -0.0174 | -0.0177 | -0.0003 |
| 360 | 72 | 4.7090 | 4.6395 | 4.6237 | -0.0148 | -0.0181 | -0.0034 |
| 550 | 72 | 3.7047 | 3.6425 | 3.6374 | -0.0168 | -0.0182 | -0.0014 |

The ladder below uses the finest grid's cd times the coarse grid's (largest box / base box) ratio where a box check ran, and adds the change between the two largest boxes (or base to big, if only one ran) to the error as the box error.

| Re_L | cd by grid (base box) | cd (finest) | grid error | how | box factor | box error | cd used | ff Blasius | ff ITTC-57 |
|---|---|---|---|---|---|---|---|---|---|
| 105 | n72: 10.0596, n108: 10.0876 | 10.0876 | 0.0280 | two grids: the difference | 0.9743 | 0.0279 | 9.8286 | 2.810 | 0.002 |
| 160 | n72: 7.6521, n108: 7.7443 | 7.7443 | 0.0922 | two grids: the difference | 0.9808 | 0.0201 | 7.5959 | 2.681 | 0.156 |
| 240 | n72: 5.9780, n108: 6.0386 | 6.0386 | 0.0605 | two grids: the difference | 0.9823 | 0.0015 | 5.9320 | 2.564 | 0.424 |
| 360 | n72: 4.7090, n108: 4.7443 | 4.7443 | 0.0354 | two grids: the difference | 0.9819 | 0.0156 | 4.6584 | 2.466 | 0.712 |
| 550 | n72: 3.7047, n108: 3.7210 | 3.7210 | 0.0163 | two grids: the difference | 0.9818 | 0.0050 | 3.6534 | 2.391 | 0.989 |

**laminar (Blasius).** (grid error plus box error per rung in the floor) mean ff 2.583. Gates at 0.1: (a) ff constancy across rungs 0.088 pass; (b) bracket 0.909 FAIL (ff constant gives cd 0.1738, cd constant gives 3.6534); (c) slope -0.099 +- 0.005 per ln Re, reach 0.645 FAIL.
DIAGNOSTIC ONLY (the top rung is below Re_L 1e+04, where no friction line applies): cd at the physical Re on this line = 0.1738 +- 1.7424 (pooled 0.0113, grid and box floor 0.0944, bracket half-width 1.7398). fin1: analytic model 0.284, CPU RANS 0.3539.

**turbulent (ITTC-57).** (grid error plus box error per rung in the floor) mean ff 0.457. Gates at 0.1: (a) ff constancy across rungs 1.166 FAIL; (b) bracket 0.958 FAIL (ff constant gives cd 0.0776, cd constant gives 3.6534); (c) slope +3.340 +- 1.084 per ln Re, reach 27.627 FAIL.
DIAGNOSTIC ONLY (the top rung is below Re_L 1e+04, where no friction line applies): cd at the physical Re on this line = 0.0776 +- 1.7917 (pooled 0.0683, grid and box floor 0.0944, bracket half-width 1.7879). fin1: analytic model 0.284, CPU RANS 0.3539.

**Two-term fit, cd = a + b x cf(Re)** (the lead's suggestion: a is the part that does not change with Reynolds number, b x cf the part that does).
- Blasius: a = -1.2513, b = 84.86, rms misfit 0.0770; predicts cd -1.0397 at the physical Re; fitted without the top rung it predicts that rung as 3.4447 against 3.6534 (-5.7 %).
- ITTC-57: a = 5.4367, b = 0.03, rms misfit 1.3038; predicts cd 5.4368 at the physical Re; fitted without the top rung it predicts that rung as 6.0411 against 3.6534 (+65.4 %).

Known ways this fails: the solver is stable only up to a cell Reynolds number of about 8 (Re_L / cells along L), so with the grids the laptop holds the rungs stop near Re_L 800, 250 times below the physical value, where the boundary layer is a third of the body length thick and the box still matters; the plate wing is 4 times thicker than the real one (2 cells of the coarse grid) so both grids see one shape; the 5.3 deg (Seaglider) angle of attack puts pressure and induced drag in cd that no friction line scales.
