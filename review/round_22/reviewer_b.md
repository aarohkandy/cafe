# Round 22, reviewer B (physics and the stage-1 model that round 21 changed)

Tree: `cafe_main`, head 65e187e (code of c58fba0). Everything ran on orca at 2 CPUs from a detached worktree (`../cafe-rev22-b`, removed). My orca directory `pm_rev22_b` is removed. Nothing was edited in the checkout. Scratch scripts were in the worktree's `scratch/`: `order.py`, `depth.py`, `rf.py`, `rfswap.py`, `sens.py`, `mergelabel.py`.

## Findings

### B-1. `when: always` acoustic link to a glider that dives: the single median depth pair flips pass/fail for 15 % of the samples, in both directions
severity: minor
lane: physics, numerics
where: cafe/pm/stage1.py:725-729 (`_acoustic`: `float(np.median(A[3][i, m]))`, `float(np.median(B[3][i, m]))`), the `ponytail:` note at stage1.py:719-721
reproduction: real `stage1.run_batch` on missions/ci_fixture.yaml with the ship moved to -165.47, 0, only the link `acoustic glider_eq - ship, benthos_atm960_mf, when: always`, M=2, real Bellhop, a made-up Mackenzie profile (T = 4 + 24 exp(-z/60 m), 4000 m of water). `scratch/depth.py`: for each member I re-ran `_bellhop_member` per 50 m bin of the glider's depth (its own median depth per bin) and compared with the margins the batch produced.
  - Member 0 (217 samples, glider depth 0 to 942 m, median 514 m): 32 of 217 samples change sign. Pass share 0.069 with the median depth against 0.180 with the depth bins. The largest difference is 42 dB.
  - Member 1: 4 flips. Pass share 0.014 against 0.005. Its two near-surface samples are +20.0 and +20.1 dB with the 472 m median depth and -24.9 dB at their own depth, so a surfaced glider that cannot talk to the ship is a pass.
  - Median |difference| is 0.5 to 0.7 dB, so the effect is in the tail, which is where the verdict sits.
why it matters: the label says Bellhop refined every needed in-range sample ("Bellhop on 434 of 434 needed in-range samples") and prints a spread that covers only the runs of the set. It does not say that the depth is one number for a dive cycle. The `ponytail:` note in the docstring does, but the report text and `report.json` do not. The error is optimistic for some samples and pessimistic for others. The profile is made up, as in every round, so the size on the sea is unknown.
wrong data: yes, on a profile with a thermocline: the printed pass fraction and verdict of a `when: always` glider link, and the label's claim of "refined".

### B-2. `merge` keeps the first batch's count in the Thorp-only label
severity: minor
lane: honesty, statistics (sibling of the class "any other number that takes its input from the first batch")
where: cafe/pm/stage1.py:861-871 (`merge`: the label is rebuilt only `if infos`), comms.THORP_ONLY_LABEL as built at stage1.py:709 (`f"... ({int(amb.sum())} ambiguous samples)"`)
reproduction: `scratch/mergelabel.py`. Bellhop unavailable, two batches whose needed samples in the ambiguous band are 7 and 40. `_acoustic` gives "Thorp only, Bellhop unavailable (7 ambiguous samples)" and "(40 ambiguous samples)". `stage1.merge` of the two prints "Thorp only, Bellhop unavailable (7 ambiguous samples)". The merged link has 47. `info` is None for these batches, so `infos` is empty and `l0["method"]` (batch 0's) survives.
why it matters: round 21 (1041 and the class table) says `merge` rebuilds the label from summed counts with one function. That holds only for the Bellhop-ran path. The Thorp-only path, which a lab without `bellhop.exe` takes, still describes 1 of N batches (on a 64-member run, one batch of 32 or fewer).
wrong data: yes (a count printed on the link card and in `report.json` `links.<id>.method`, understated). The verdict is unaffected.

## Not defects (tried, found nothing)

- Order independence (real batches, M=4, thermocline profile, both orders of every pair, `scratch/order.py`):
  - acoustic glider-ship, glider-glider and glider2-ship, `surfacing` and `always`: `frac`, `success`, `margin_db`, `need_count`, `n_invalid`, `dist_m`, `bellhop_spread_db` and `method` are bit-identical when a and b are swapped.
  - RF glider-glider and Iridium glider-glider `surfacing`: identical. RF glider-ship: `margin_db` differs only at floating-point level (`rfswap.py`: `rf_margin(d, h1, h2)` against `(d, h2, h1)` differs by at most 1e-10 dB over nine height pairs and Hs 0, 1 and 2.5, 0 sign flips, 0 horizon disagreements).
- Needed samples refined: the label counts equal `need & valid & |Thorp margin| <= 60` ("434 of 434", "868 of 868"). The "a further N ... keep that margin" clause appeared (386 samples) and agrees with the Thorp margins. The lowest-of-set margin is `np.fmin` over the set sample by sample (read; the runs are 2 to 3 as the label says).
- The `far` skip: with the cap applied in both directions the sign cannot change (margin_refined = m_t - clip(excess), so m_t > 60 stays > 0 and m_t < -60 stays < 0). For the MF Benthos modem a Thorp margin above +60 needs a range of about 1 m, so only the negative side occurs in practice. The reading rests on the cap, which is ASSUMED. A zero field (my probe held 4 of 39 and 5 of 481 samples at the cap, "no ray reached the receiver") is counted as a 60 dB loss at most.
- Live RF band (`scratch/rf.py`, my own image-method Fresnel two-ray with eps_c = 72.8 - j sigma/(omega eps0)): `pair_band` agrees with it to 3e-3 dB (min, median, max) and has the same counts of samples more than 3 dB off, for 20 pairs at 915 and 2440 MHz. The demo card figures reproduce: 2.2 m with 18.1, 38.1, 68.1 and 108.1 m give -3.2/+0.6, -8.1/+24.4, -9.9/+30.3 and -10.8/+39.2 dB, with 10, 19, 28 and 38 of 400 samples off. Extremes (0.1 and 1000 m, 2.2 and 400 m, two 1000 m ends) are finite and sensible.
  - Observation, not a defect: the band is the model's whole loss (curved earth, divergence, the transition and diffraction branch) minus a flat Fresnel two-ray, not the effect of the -1 alone. With the curvature and transition terms alone the model differs from a flat -1 two-ray by -34 to +29 dB (15 m with 108.1 m at 915 MHz). That is null positions shifting. The card's sentence ("its loss minus the Fresnel loss") is literally right; the PHYSICS wording "error of the -1 reflection" is looser.
  - At 2440 MHz the sea is the 915 MHz assumption. I did not test the permittivity at 2.4 GHz against a reference value.
- Subset EASI (DECISIONS 1042; `scratch/sens.py`, 64-member LHS, 12 columns, members "needed" chosen as the k lowest of one column, 300 repetitions each, floor by 1500 permutations):
  - Unrelated y on the subset: false-positive rate 0.03 (k=16), 0.057 (k=25), 0.043 (k=40), against 0.05 on all 64. The index of a true driver is unbiased on the subset: S1 0.553, 0.557 and 0.561 against 0.569 on all members.
  - Power falls with k, which is correct and honestly reported by the floor: the floor is 0.65 at k=16, 0.43 at k=25 and 0.27 at k=40, and a driver of S1 0.57 is found in 33 %, 82 % and 99.7 % of repetitions. `SENS_MIN_N` = 16 is therefore legal but a ranking there is nearly always "nothing above the floor".
  - A column that decides which members needed the link, when it also drives the failure, loses its range inside the subset and is found in 0 to 11 % of repetitions (against 57 % on all members). The text says "among the n of N members that needed the link", so this is disclosed. It does mean a driver of "needed or not" cannot appear in a link's ranking.
- Drag spread (`mission.drag_sigma`, `vv.gci_value`): the spread is continuous and monotone at the threshold (hypot(0.10, 0.3) = 0.316, capped at 0.30). The mean-preserving lognormal at 0.30 has median exp(-0.045) = 0.956 and a 5 to 95 % range of about 0.61 to 1.56 of nominal. Above `GCI_TRUSTED` the CFD mean is kept with the estimate's 0.30 spread, so an index of 0.44 to 0.57 is covered by a spread no wider than for no CFD. That is the owner's open choice (QUESTIONS_FOR_LAB 18h) and I report no more than the arithmetic.

## Not run (inside the allowance, or not possible)

- A GOFS profile (none in the repo; every profile I used is made up), the second modem (`whoi_micromodem`), `benthos_atm960` HF, the 5 m floor on a second profile, an `nbeams` run, the 60 dB cap against a real shadow, the 50 m grid maximum error, cost on a second fixture or a longer span (my one batch: 224 Bellhop calls, 236.7 s of 239.4 s, for 12 acoustic links x 4 members, 2 CPUs).
- The two-UAS `uas_airborne` link and a two-glider acoustic AND physics (only the acoustic, RF and Iridium glider-glider links were run, with both ends surfaced at the same moments). The UAS leg climbs between legs.
- The `UNSEEN` single-column and interaction probes on a gridded environment, a real USV battery failure end to end, row 1054's 13 and 5 steps of 1747.21 and 1936.66 J (no gridded environment, over the allowance).
- The 22.5 dB grid maximum and the isolated-null question.

total: 2 findings (0 critical, 0 major, 2 minor)
