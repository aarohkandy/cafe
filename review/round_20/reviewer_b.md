# Round 20, reviewer B (physics and the stage-1 model that round 19 added or changed)

Tree: `premission-step4` at 67aa547 (code `979e37a`'s). All runs on orca at 2 CPUs (pm_rev20_b, `/data/runs/rev20_b*`), from a detached scratch worktree
(removed). The CI fixture environment (`tests/fixtures/ci_env`) was built in a private tree under `/data/runs/rev20_b_ci`; no demo, no gate, no shared store
written. My scripts are kept outside the repo in the lead's session scratchpad, `.../scratchpad/b/` (`twoend.py`, `lowant.py`, `lowant2.py`, `slocum.py`,
`usvbat.py`, `uasbat.py`, `bell.py`, `ac_order.py`). Orca leftovers: none (my directory, run files and logs were removed by exact name).

## Findings

### B-1. An acoustic link's margin depends on which end is named first, by up to 6.8 dB, wherever Bellhop refines it
severity: minor
lane: numerics / reproducibility
where: cafe/pm/stage1.py:622-638 (`_bellhop_member`: `tx=A[3]`, `rx=B[3]` handed to `comms.acoustic_link(tx_depth=, rx_depth=)`), cafe/pm/stage1.py:659-665 (`_acoustic`),
cafe/pm/stage1.py:762
reproduction: scratchpad `b/ac_order.py` (`PM_HOST=cafe-orca PM_RUNTIME=proot PMX=pm_rev20_b PM_CPUS=2 bin/pmx.sh python rev20b/ac_order.py`; the CI fixture, only
`glider_eq` (Seaglider, station at -165.5, 0.0) and a ship moved east by 3, 4, 5, 6 and 8 km, link `acoustic benthos_atm960_mf when: surfacing`, 4 members through
a real `run_batch`, the same link written `a: glider_eq, b: ship` and `a: ship, b: glider_eq`). The pairs of margins at the same samples (dB):
3 km 9.45 against 14.04 (max |difference| 6.84), 4 km 5.85 / 6.56 and 9.95 / 10.62 (max 2.84), 5 km 2.95 / 5.19 and 6.52 / 8.24 (max 2.24), 6 km 0.37, 8 km 0.0
(there the method is 'Thorp only', no Bellhop, and the two orders are identical). The method string at 3 to 6 km is 'Thorp/Stojanovic budget on the slant range, Bellhop on
n of m ambiguous samples'. The same thing at function level: `comms.acoustic_link(d=4000, modem, band, wind=6, ssp=..., tx_depth=5, rx_depth=1)` gives -20.70 dB
and (1, 5) gives -20.24 dB (a smooth profile, 0.46 dB). The Thorp-decided samples are symmetric (identical); only the Bellhop-refined ones are not.
why it matters: the round 19 rule (DECISIONS 996) was checked for the required moments, `need_count`, `n_never_required` and the verdict not depending on the order of
`a` and `b`; the margin of an acoustic link between a glider and the ship (or a second glider with a different transducer depth) does, in exactly the band
(|Thorp margin| <= `ambiguous_db`) where a sample can flip. Ray tracing is reciprocal, so the spread is Bellhop's own numerical error in the refined samples
(near-surface 1 m / 5 m endpoints), which the link card's 'Thorp ... Bellhop on n of m' line does not say. In my four members the pass fraction came out equal in both
orders, so no verdict moved here, but a margin within a few dB of 0 is decided by which end was typed first. The demo is unaffected (its acoustic links are 555 and 632 km
long, out of range).
wrong data: yes, conditional: the printed `margin_db_median` of an acoustic link whose samples fall in the Bellhop band (a glider surfacing within about 3 to 6 km of the
ship); not in q21.

### B-2. The mechanism given for the Slocum's current-column step names one discrete event; the cycle has a second one of nearly the same size
severity: minor
lane: documentation / honesty
where: cafe/pm/stage1.py:62-72 (the comment on `ACTING`), DECISIONS 999
reproduction: `cafe/pm/physics/glider.py:490-492` charges `pump_energy_J(dV, p(dive_depth), eta)` at the apogee (`reach`) and :499 charges `comm_J + pump_energy_J(dV, 0, eta)` at
the surfacing (`up`). Arithmetic with the demo's trim (the 138 cc that the round 19 record gives for the 1.6147e-4 to 1.6154e-4 steps of `review/round_18x/demo_probe.json`,
glider_2n, `current_speed_scale` at 0.75 and 0.95 quantiles): surfacing 1709 + 138e-6 x 101325 / 0.4 = 1743.96 J = 1.6148e-4 of 1.08e7 J (matches the record to 4 figures);
apogee at 500 m, p = 505 dbar: 138e-6 x (101325 + 505e4) / 0.4 = 1776.6 J = 1.645e-4. Both events are in every cycle (my CI toy, `slocum.py`: the distinct non-hotel event
energies of a 64-member Slocum run are 1810 J (surfacing, dV 400 cc there) and 5141 J (apogee), and the members' counts of apogees and of surfacings differ independently:
(16, 15), (16, 16), (17, 16), (17, 17) ...). A shift of the cycle that moves the window end across an apogee instead of a surfacing gives a step of about 1.645e-4, and
across both about 3.3e-4. The comment says the step 'is one surfacing less' and gives no second size. The measured steps are all of the surfacing size, which agrees with the
statement, so this is not a wrong number: the record (8 members x 5 quantiles) simply never showed the apogee case. The 1.62e-4 itself is right: 1709 + 38.2 = 1747.2 J,
1747.2 / 1.08e7 = 1.618e-4 (for 150.83 cc; 1.615e-4 for the demo's 138 cc).
why it matters: the text is offered as the explanation of the step; a reader who sees a step of 1.65e-4 or 3.3e-4 on another environment will not find it in it.
wrong data: no.

### B-3. The USV's ranked state of charge is censored at 0 for almost every member in a battery-dominated run, and the text does not say so
severity: minor
lane: statistics / honesty
where: cafe/pm/physics/usv.py:689-690 (`soc_wh` clipped at 0, `soc_min`), cafe/pm/stage1.py:228 (`energy_margin=sim.soc_min`), cafe/pm/stage1.py:831-837 and :866-885 (`_ranked`,
`_sensitivity`)
reproduction: scratchpad `b/usvbat.py` (the CI fixture with only the USV and the Iridium link, the platform file copied with `battery_wh` 1005 instead of 4000, 64 members through
`run_batch` and `summarize`): modes `battery` 59, `swept_off_track` 35, dominant `battery`; `energy` block `soc_min_median` 0.0, `n_empty` 59; sensitivity `case ranked`,
`solar_yield_scale` S1 0.235 against a floor 0.130, quantity 'lowest state of charge (fraction of the pack)', and `S1` holds the eight columns of DECISIONS 988
(`current_direction_bias`, `current_speed_scale`, `hs_scale`, `solar_yield_scale`, `tp_bias`, `usv_vpp_bias`, `wind_direction_bias`, `wind_speed_bias`). So the end to end path of a real USV
battery failure works (8 columns, `solar_yield_scale` first, as expected from the physics), and the second half of the finding: 59 of 64 values of the ranked quantity are the
same number (0.0), so the index rests on the 5 uncensored members plus a tie plateau whose order inside is arbitrary, and the printed sentence reads like a ranking of a
continuous quantity. (With `battery_wh` 1020, 34 of 64 members empty, the dominant mode stays `swept_off_track` and the ranking is of the cross-track error: also as designed.)
why it matters: when the battery is what fails, the amount by which it fails (the deficit) is the informative quantity and the simulator throws it away at the clip; the
ranking is probably right but its strength is overstated by the wording.
wrong data: no (the ranking was the physically expected one; no wrong ranking was demonstrated).

## Checked, no defect found (so a reader can see what a clean B report rests on)

1. The two-end link rule through real `run_batch` (P-R18M9's first half, now closed by measurement; scripts `twoend.py`, CI fixture, 4 members, both orders each):
   - glider-glider RF (Seaglider 0.5 m, Slocum 0.3 m): `need_count`, `frac`, `success`, `n_invalid`, `dist_m`, `margin_db` identical for `a/b` swapped; the required moments equal the
     intersection of the two gliders' surfaced moments exactly (counts [1,1,1,2] against single counts [5,6,4,5] and [20,22,17,18]); no finite margin outside the intersection (0 of 217 x 4);
     the margin is NaN wherever either glider is under water. With the gliders about 440 m apart the margin is finite (29.6 dB) at the intersection samples.
   - the same for an acoustic glider-glider link ('Thorp only' there) and an Iridium `when: surfacing` link: identical in both orders.
   - gliders 111 km apart (the CI default): all margins NaN, `frac` 0 (RF beyond the horizon, acoustic out of range): a NO-GO decided on 1 or 2 moments per member, which the granularity
     badge handles.
   - `uas_airborne` with two UAS ends (second UAS launching at 14:00, 14:10 and 20:00 local solar time, M = 2): `need_count` [80, 49], [40, 29] and [0, 0]; the time axis is the union of the
     two 30 s grids (339, 377, 400 samples); the order of the ends changes nothing (`need_count`, `frac`, `success`, `margin_db`, `t` all equal); a second UAS that flies at another hour gives `need_count`
     0 in every member (which `summarize` counts as `n_never_required`, NOT EXERCISED).
   - 10 minute record grid note, not a finding: a glider is surfaced 490 s of a 9,400 s (Seaglider) or about 6,400 s (Slocum) cycle and the records are 600 s apart, so two independent gliders coincide at
     a record about once per run (the toy: 1 to 2 moments of 217); an RF or acoustic glider-glider `when: surfacing` link is therefore undecided by granularity in practice, and says so.
2. `_pos` adds `antenna_m` to a submerged glider's height (stage1.py:605): that is dead arithmetic. The heights are used only by `comms.rf_margin` (stage1.py:750), whose result is
   reported only where `need` holds (:769), and `need` requires every glider end surfaced (:741), so the value at a submerged sample never reaches an output. (It does enter `_link_hs`'s
   `hs_filled` count, which counts fills at all samples, harmless.)
3. Is the AND the right physics for an acoustic link (row 996's alternative c)? As a model of `when: surfacing` it is what the mission asks for; as physics of an acoustic modem it is a
   choice, not a derivation: a transducer works under water, and with both gliders surfaced `_acoustic` clips both depths to 1 m (`_bellhop_member`), the worst case for acoustic propagation. I
   found no number that is wrong because of it (no demo link has two glider ends), and I found nothing that says otherwise than DECISIONS 996 does.
4. DECISIONS 999 arithmetic: `comm_J` = 3.5 W x (120 s + 50,000 B / 200 B/s) + 414 J = 3.5 x 370 + 414 = 1709 J (`glider.py:340`, platform values read from `platforms/slocum.yaml`); surface pump
   150.83e-6 m3 x 101325 Pa / 0.4 = 38.21 J; total 1747.2 J = 1.618e-4 of 1.2e7 x 0.9 (the margin's denominator is `cap x (1 - reserve_frac)`, stage1.py:200). Recomputed with the CI toy's
   `GliderSim` (`slocum.py`): comm 1709.0, surfacing event total 1810.45 J at its 400 cc trim. The mechanism (a count of events at the window's end, quantised by the 60 s step) holds by reading;
   on the CI fixture, scanning `current_speed_scale` alone over its whole range at the other columns at their medians leaves the counts at 19 apogees and 18 surfacings in all 64 members and the margin
   constant to 2e-9 (3 distinct values at 1e-9), as the comment says (inert there). It is a real discrete event of the physics (a surfacing either happened in the window or did not), with its time
   resolved only to the 60 s step: the shift it needs (a part in 1e4 of the cycle, 1 s a cycle, 52 s over 55 cycles) is under one step, so which member crosses is partly the step's quantisation.
   Any column that moves position can do it (the wind through the 1 % windage while surfaced: the surface drift is about 1/30 to 1/100 of the current's effect, from 5 m/s x 0.01 x 490 s against
   0.3 m/s x 9,400 s), and so can the per-member ocean SDE displacement, which is no column at all: that is a second reason the two current columns' index in that row carries no information, which the
   comment does not mention. Whether the two columns belong: the text says they do for the floor's sake (0.155 for two, 0.186 for four columns); I take no position beyond B-2.
5. The low-antenna figures, recomputed independently (`lowant.py`: my own flat-earth Fresnel two-ray, eps_c = 72.8 - j60 lambda sigma with sigma 6.05 S/m, 915 MHz, vertical polarisation, the Ament factor in the
   reflection coefficient for Hs above 0, 400 points from 300 m to min(radio horizon, 12 km)): all ten rows of `comms.LOW_ANTENNA_PAIR_BAND` agree to at most 0.05 dB (0.04 typical); the nine Hs 1, 2, 3 figures of
   `credibility.LOW_ANTENNA_HS_BAND` agree to at most 0.05 dB; a height off by 0.001 m at either end moves a figure by at most 0.093 dB (0.1 m row), 0.030, 0.013, 0.001, 0.019, 0.016, 0.009,
   0.027, 0.012, 0.001 dB for the other nine; a 0.01 m move of the lower antenna moves figures by at most 0.97 / 0.31 / 0.13 / 0.01 dB for 0.1 / 0.3 / 0.5 / 2.2 m with 15 m (printed bounds 1.0, 0.4, 0.2, under
   0.1: all hold), and by 0.20, 0.16, 0.09 for the three both-low pairs. 'From 200 m' claims of `two_ray_curved_db`'s docstring: 0.5 m / 15 m -5.0 dB, 0.3 m / 15 m -0.6 dB, 2.2 m / 15 m +31.9 dB at one null: all
   reproduce. The seven pairs 'not measured above Hs 0' move by under 0.3 dB between Hs 0 and 3 m except 2.2 m with 2.2 m and with 15 m (minimum -2.4 to -1.6 and -3.3 to -2.4); the 15 m pairs at Hs 5 m are
   +0.3 / +14.5 / +15.1, +0.2 / +5.8 / +6.5 and +0.1 / +2.6 / +2.9: so the cards' 'at 1 to 3 m these figures are different' is right for the 15 m pairs and the others are stable: conservative, nothing wrong.
6. Acting columns round 19 added: `battery_capacity_scale` for a link with a UAS end (`uasbat.py`, CI UAS with the USV link, 12 members, one column swept, the others at their medians): `need_count` 84 to 87 across the
   battery scale (members differ in their own random draws as well), against 84 to 87 across `wind_direction_bias` and 84 to 86 across `bulk_stress_scale`; the UAS reserve margin moves from -0.033 to +0.148 across the battery
   scale: the effect on the required moments is real but of the same size as the other columns, so listing it is defensible. `wind_direction_bias` on `profile_margin` is not moved by any of the three (0.875 in all 12 members).
   Not tested: its edge effect (round 19's finding, reasoned there).
7. The USV's eight columns on the state of charge: the end-to-end run in B-3 gives all eight and the physics-expected leader. `battery_capacity_scale` is sampled for a USV mission and no USV code reads it (the USV
   has no pack-size column), which `ACTS` already reflects (not a finding).
8. q21's vehicles from the arrays (`q20_mission.json`, 30 min grid): glider_eq's largest excursion from its station recomputed from the arrays equals the stored `margin` to the grid's resolution (9.34 / 9.34, 9.00 / 9.00,
   9.11 / 9.06 km ...), every member leaves the 5 km radius (minimum 5.34 km, median 8.31 km); members outside for more than 12 h on the 30 min grid: 16 (17 at 12 h or more), against `station_lost` 15, which is the
   simulator's own 60 s count against my 30 min one; the demo's two acoustic links are 555 and 632 km long (out of range 100 %), so their NO-GO is geometry, as the summary says (`frac_out_of_range` 1.0).

## Not run (the allowance, or nothing in reach to run against)

- a parabolic equation for any pair (no implementation in the repo, the starter does not hold below about 1 m, and I did not build one); the Norton / Sommerfeld surface-wave field as a third reference for the two low ends;
- the mechanism of DECISIONS 999 on the demo's own gridded environment (needs the demo's data copy, P-R18X1): checked by reading, arithmetic and the CI toy only; the apogee-crossing step of B-2 is derived, not seen;
- interactions of two columns on the UAS's profile share and on the Slocum's battery row; `wind_direction_bias` at the battery edge of the UAS's profile share;
- a Stage-1 `run` / `whatif` flip through the report (the demo flips nothing; C's);
- B-1 on the demo's own environment and with a real `a: ship` link in a full mission (the CI fixture only; Bellhop is the image's).

total: 3 findings (0 critical, 0 major, 3 minor)
