# Round 17, reviewer B

Method. An independent field for the P.526 / two-ray work: a finite-difference parabolic-equation (PE) solution over an effective-radius earth (earth flattening, Crank-Nicolson, Gaussian starter, Leontovich impedance of sea water eps 72.8 - j118.9, vertical polarisation), checked against the plane-earth Fresnel two-ray formula to 0.1 to 0.5 dB before use. It uses neither Fock's series nor ITU's F and G. Scripts were in a scratch worktree (`x_b/pe.py`, `grid.py`, `zone.py`, `low.py`, `cont.py`, `edge.py`, `m11.py`); the repo was not edited.

## Checked and found sound (no finding)

- `smooth_earth_diffraction_db` against the PE, dB (implementation minus PE), 0.5 to 3 times the horizon:
  - 915 MHz, k 4/3: 108.1/2.2 m -2.7 to +1.3 (the 3x point is below the PE noise floor and is not usable); 8.1/2.2 -2.4 to -0.7; 50/5 -1.6 to +0.2; 18.1/2.2 -2.1 to -0.7.
  - k = 1 and k = 2 (18.1/2.2): -2.0 to -0.3 and -2.0 to +0.8. DECISIONS 894 lists k other than 4/3 as not verified; it holds.
  - 2440 MHz: -1.1 to +0.7. 433 MHz: -3.2 to -1.6, slightly outside the stated -2.8 band, but no radio of the repo is at 433 MHz.
  - 2.2/2.2 m: -3.7 at half the horizon, -1.4 to -2.1 beyond.
- The horizon losses of DECISIONS 894 are reproduced: PE plus free space 154.1, 150.5 and 150.7 dB for the 108.1, 18.1 and 8.1 m UAS, against 154.2, 150.7 and 151.0 given for the Fock series.
- Continuity. At the transition boundary (psi = psi_c) `two_ray_loss_db` has no step: 0.0 dB at 5 m sampling, 7 antenna pairs, Hs 0, 0.5 and 1.5. Across the whole zone the implementation minus PE total loss is -2.9 to -0.6 dB, on both sides of the boundary (pairs 18.1/2.2, 108.1/2.2, 8.1/2.2; Hs 0 and 1).
- The NaN contract for range and height (`rf_margin`, `two_ray_loss_db`, `smooth_earth_diffraction_db`): NaN in, NaN out, including a mixed array. A negative range raises.
- M-11, `stage1._pos` across 180 deg, run on edge cases: 179.9 to -179.9 gives -180.0 at the middle; a NaN gap stays NaN; records exactly at +/-180 are fine; a 0 to 360 track gives -0.1, 0, 0.1; non-crossing members are untouched; an all-NaN member stays NaN.
- M-29: `n = ceil(duration/dt) + 1` samples always cover `sortie_t_max + 60`, so the guard cannot refuse a series that `stage1` builds (checked by reading `env/subgrid.py`).
- Mutants of the P.526 code (15, run against `-k diffraction` of `tests/test_round16_a.py` and `tests/test_comms.py`). Killed (10): X 2.188 to 2.2, Y doubled, F switch 1.6 to 1.0, h_req 17.456 to 25, a_em 500 to 400, h_se curvature term 500 to 400, inside-factor halved, transition without the horizon test, transition without the diffraction term, transition without the free-space term. Survived (5): see B-3.
- q17 vehicles from `q17_mission.json` and `report.json`:
  - Fail counts rebuilt from the arrays equal the report: glider_eq 15 of 64 (station_lost), glider_2n 0, usv 61 (becalmed 18, swept 50, stall_calm 40, stall_angle 15), uas 62 (profile_incomplete 62, battery_reserve 13).
  - UAS `margin < 0` equals the battery flag on all 64.
  - glider_eq station lost: rebuilt from 30-min records, 17 against the 15 flagged. Two members (54, 59) differ; the sampling is coarser than the 60 s step, so this is not a defect.
  - usv-uas-rf: need 16,022, beyond the horizon 14,224 (88.78 %); 40 members with some valid sample against 42 predicted from the USV-ship distance at launch + 10 min against horizons of 23.6, 31.5, 40.1 and 48.9 km. USV-ship distance at launch + 10 min runs 5 to 197 km.
  - USV speed ratio 0.1339 (the report's figure); the USV lowest state of charge median 0.7356 and lowest 0.7254 equal the arrays. The `solar_yield_scale` draws are lognormal (ln-sd 0.193, the inverse CDF of U matches to 1e-6); the lowest state of charge is a dusk-to-dawn deficit of about 13 h at 80 W, which is plausible, and the column moves the margin and not the verdict.
  - Glider_2n energy: 6 days leaves about 0.95 MJ used, which is consistent with 1 W hotel plus roughly 93 dives at about 4.6 kJ each.

## Findings

### B-1. The reflection coefficient -1 makes the RF loss too high for low antennas; the stated error band covers only the UAS and the USV
severity: minor
lane: physics
where: cafe/pm/physics/comms.py:109 (docstring, error band), docs/PHYSICS.md section 12.1
reproduction: PE with the sea's impedance (`x_b/low.py`, 915 MHz, source at the 15 m antenna by reciprocity, Hs 0) against `two_ray_loss_db(d, h_low, 15.0, 0.0, 915e6)`, d = 300 m to 16 km. Implementation minus PE: h_low 0.5 m -2.6 to +1.0 dB (fine); h_low 0.3 m (the Slocum antenna, `platforms/slocum.yaml:37`) +1.8 to +5.0 dB; h_low 0.1 m +12.5 to +15.2 dB. `config.load_mission` accepts an rf link to a glider with `when: surfacing` (config.py:497), so a glider-ship link at 0.3 m is a supported mission.
why it matters: the margin of a glider-to-ship RF link (Slocum, 0.3 m) is understated by 2 to 5 dB, and by more for a lower antenna, which can turn a GO into MARGINAL or NO-GO. The docstring's band (7.6 dB optimistic to 34.7 dB conservative) speaks only of UAS and USV geometry.
wrong data: no for the demo (it has no RF link to a glider; its only RF link is UAS-USV). For a mission with an RF link to a Slocum glider: yes, that link's margin and verdict (conservative direction).

### B-2. A zero antenna height passes validation and gives a finite margin of -43 dB or worse, not "no link" and not an error
severity: minor
lane: robustness
where: cafe/pm/physics/glider.py:74 (`antenna_height_m="nonneg"`), cafe/pm/physics/comms.py:132-139 (the 1e-12 floor on the field), cafe/pm/physics/comms.py:227
reproduction: `rf_margin(5e3, 0.0, 10.0, 0.5)` returns -43.2 dB (loss 195 dB; free space is 105.7 dB); the same for a height of 1e-9 m, and about -90 dB at 1 km. With `-1` the two rays cancel exactly, so the loss is set only by the 1e-12 floor of `max(field, 1e-12)`. `stage1.evaluate_link` counts it as a valid margin (`isfinite` and not `NO_LINK_DB`), so it appears in the card as a real margin.
why it matters: the margin printed for such a link is the floor of a division guard, not physics; the PE gives free-space-like loss near 83 to 153 dB over the same range for 0.1 m.
wrong data: no for the demo (no zero heights). A platform file with `antenna_height_m: 0` gives an RF link margin printed as a very negative number: yes, that link's margin.

### B-3. Five of the 15 P.526 mutants survive; the sea constants and the K / G-floor path are covered by no test
severity: minor
lane: tests
where: cafe/pm/physics/comms.py:142 (SEA_EPS_R, SEA_SIGMA_SM), :165 (K coefficient 0.36), :158 (G branch at B = 2 and the floor 2 + 20 log K), :196 (`np.maximum(beyond, 0.0)`)
reproduction: edit one and run `-k diffraction tests/test_round16_a.py tests/test_comms.py`: `0.36` to `0.5`; `b > 2.0` to `b > 3.0`; the floor replaced by `-60`; the sea constants `72.8, 6.05` to `20.0, 0.01`; dropping the beyond-horizon clip. All five exit 0.
why it matters: for sea at 915 MHz K is about 0.02 and beta about 1, so none of them moves a demo number (the G branch is continuous to 0.3 dB at B = 2 and 3). The mutants are therefore near-equivalent, but a change of radio frequency or sea state would not be caught.
wrong data: no.

total: 3 findings (0 critical, 0 major, 3 minor)

## What was not checked

- The orca host stopped answering (`ssh: connect to host ... port 2222: Operation timed out`) during the last runs, so these did not complete: the PE for glider-USV pairs (0.3 and 0.5 m with the 2.2 m whip, B-1 for the USV end), the PE at 0.05 and 0.02 m (B-2), and the quantification of how many of the 14,224 beyond-horizon samples would have a positive margin if the P.526 field were used past the horizon (by calculation the margin crosses zero a little beyond the horizon, so no demo verdict can move; not run).
- `rf_margin` with a NaN `hs` (by reading, finite in the transition zone and NaN elsewhere, unreachable because stage 1 fills Hs); not run.
- The PE is unreliable below about 1 km for the 108 m antenna (angles outside the paraxial range) and at 3 times the horizon for large heights (noise floor); those points were left out.
- No full run, no gate, no whatif rerun; the M-2 wind-model baseline was read, not run.
- Cleanup: the worktree `../cafe-rev17-b` is removed, and `~/cafe-worker/cafe/pm_rev17_b` and its job marker on orca are removed (the ssh succeeded on the retry).
