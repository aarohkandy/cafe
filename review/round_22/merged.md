# Round 22 merged findings (BRIEF 5.6 step 2)

Inputs: reviewer_a.md (5 findings), reviewer_b.md (2), reviewer_c.md (4), reviewer_d.md (8) = 19 source ids. Merged to 12 findings, M-1 .. M-12; every source id appears in exactly one merged finding (C-1 and C-2 form M-1; A-1, A-2 and B-2 form M-2; B-1 is M-3; C-3 is M-4; D-1 is M-5; D-2 and D-4 form M-6; D-3 is M-7; C-4 is M-8; D-5 and D-7 form M-9; A-3 and D-6 form M-10; A-4 and D-8 form M-11; A-5 is M-12). Four points are mine, found while verifying (marked "found here"): the card's "overstated everywhere" sentence is also a 400-point statement (M-1); the "up to 5.0 dB from 200 m" clause of L23 is another grid extreme, not measured by anyone (M-1); a surfaced glider at 0 m flips as often against the median-depth run as one at 900 m, so the median depth is no proxy for a dive cycle (M-3); the enumeration of what `merge` takes from the first batch (class table below). They sit inside the merged rows, so the source-id count stays 19.

Verified by this merge against HEAD e65c907 (code of c58fba0; every later commit is review material). By reading the cited code, and on cafe-orca (proot, 2 CPUs, one job at a time, detached worktree `../cafe-rev22-v`, private `pm_rev22_v`, both removed at the end) by four small scripts, kept in the lead's scratchpad `.../scratchpad/v22/`:
- `v1.py`: `comms.two_ray_loss_db` minus `rfband.fresnel_loss_db` for nine height pairs at 397, 400, 401, 4,000 and 40,000 distance samples (minimum, 1st, 5th, 50th, 95th, 99th percentile, maximum, share more than 3 dB off, split by sign), and the move of every statistic for the lower antenna +-0.01 m (C-1, C-2).
- `v2.py`: `stage1._acoustic` with Bellhop switched off for a Thorp margin of +18.4 dB and for one inside the band, and `stage1.merge` of two Thorp-only batches in both orders (A-1, A-2, B-2).
- `v3.py`: a real Bellhop (made-up Mackenzie profile of B's: T = 4 + 24 exp(-z/60), 4,000 m of water; the project's own `_run_set`, MF modem, 33 ranges 600 to 3,900 m, ship end 1 m, glider depth 0 to 950 m every 50 m) against the run at the median depth 514 m (B-1: mechanism, not B's 217-sample member).
- `v4.py`: the same difference at 400 and at 40,000 samples over every pair of 14 heights from 0.1 to 1,000 m (105 pairs) at 915 and 2,440 MHz: which statistic of the band is stable (C-1's fix).
Also a Node one-expression check on the laptop of `app.js`'s `fmt` (D-2; no Python, no test). Not done here: any full Stage-1 run, any demo, any report render, any mutant, any test, B's 217-sample member rerun, D-1's twelve YAML edits rerun, a real GOFS profile (every profile is made up, as the reviewers'). ssh to orca answered every time; no claim rests on a reviewer alone because ssh failed. Claims that rest on a reviewer alone by choice are marked "by reading" or "reviewer's run".

**Severity.** 0 critical, 0 major, 12 minor. The two the lead asked about:
- **B-1 (M-3) stays minor.** It needs a `when: always` acoustic link with a submerged end (the demo's acoustic links are `surfacing`, glider at 0 to 1 m, where the median depth IS the depth), a real Bellhop and a profile with structure; the size comes from made-up profiles (here 25 % of a uniform range-by-depth grid change sign, B's real member 15 %, 4 to 32 samples, both directions, median |difference| 0.5 to 0.7 dB); and Thorp, which judged the same samples before round 21, has no depth at all, so round 21 did not make the verdict worse, it made the label claim more than the run supports. If the lead's rule for major is "a verdict of a mission the lab plausibly flies can flip", it qualifies; I rate it minor for the same reasons round 21 left M-3 and M-4 minor, and say so in the severity line so that the lead can overrule.
- **D-1 (M-5) stays minor.** It needs a `.inf` or `.nan` typed into a shipped table (`platforms/radios.yaml`, `modems.yaml`, `config/assumptions.yaml`); nothing shipped has one (grep); it is not user data, it is the developer's table, and a typo cannot make it (a mistyped `inf` without the dot is a string and a TypeError). But it is wrong data, not a traceback: `tx_dbm: .inf` gives an RF link that always passes, and the lab's own provenance check says "provenance OK". The fix is one line, so I would not argue about the grade.

Status: 12 merged; confirmed or partly confirmed 12; refuted 0. Of the nine source ids the reviewers rate "wrong data: yes", all nine hold (D-2 only conditionally: the mechanism is confirmed, a NaN force reaching it is not shown).

INCIDENTS and side effects of this merge: one scratch worktree `../cafe-rev22-v` (detached, removed with `git worktree remove --force`), one orca directory `~/cafe-worker/cafe/pm_rev22_v` (removed by that exact name; no job marker, no tmux session of mine, no kill, nothing in `pmdata`, nothing under /tmp on orca or the laptop). Bellhop (arlpy) wrote its temporary files where arlpy puts them inside the proot, as the reviewers' runs did. No code, test or document was edited and nothing was committed.

---

## Critical

None.

## Major

None. (See the severity paragraph above for M-3 and M-5.)

---

## Minor, wrong data: yes (M-1 to M-7)

### M-1. The RF card's and L23's "up to +39.2 dB / down to -10.8 dB" are extremes of a 400-point grid, called bounds; a finer grid moves them by 4 to 54 dB; and the sentence that the figures are stable to a centimetre is false for the demo's own pair   (sources: C-1, C-2; the "everywhere" sentence and the "5.0 dB" clause found here)
severity: minor / status: confirmed (reproduced) / lane: honesty, numerics
wrong data: yes. The "overstated by up to X dB ... understated by up to Y dB" sentence on the card of every RF link (`report._low_antenna_note`, the "over these pairs it is X to Y dB" sentence for several pairs), L23's pair list, the word "bound" (`credibility._l23_text`, RUNBOOK 190), and L23's "moving the lower antenna by 0.01 m moves a pair's figures by up to 1.0 / 0.4 / 0.2 dB (under 0.1 dB at 2.2 m)". The demo has the pair (2.2 m, 108.1 m) on the card of `usv-uas-rf`.
where: cafe/pm/physics/rfband.py (`N_POINTS` = 400, `pair_band`), cafe/pm/report.py:845-864, cafe/pm/credibility.py:40-71 (`band_figures`, `band_effect`) and `_l23_text`, docs/RUNBOOK.md:190, docs/PHYSICS.md 12.1
claim (C-1): the extremes at 400 points are not the extremes of the model: 2.2 m with 108.1 m gives -10.8 / +39.2 at 400 points, -14.7 / +48.7 at 4,000, -14.9 / +70.9 at 40,000. (C-2): +0.01 m moves that pair's maximum by 11.4 dB and -0.01 m moves its minimum by 1.2 and its maximum by 4.5 dB (the sentence says under 0.1 dB at 2.2 m).
check: reproduced on orca (`v1.py`), to the digit of C's figures: (2.2, 108.1) min/max -10.77/+39.25 (400), -14.74/+48.69 (4,000), -14.88/+70.92 (40,000); (0.5, 108.1) max +17.4 at 400 and +64.3 at 4,000; (2.2, 68.1) max +30.3, +60.7, +67.4; (2.2, 38.1) max +24.5, +42.4, +62.9; (15, 108.1) min -12.2, -14.7, -15.0. The grid is not even stable at its own size: 397, 400 and 401 points give maxima of +31.3, +39.3, +32.5 for (2.2, 108.1). For C-2: the same pair's medians move 0.00 dB and its 5th and 95th percentiles 0.01 to 0.24 dB. Over the WHOLE domain (`v4.py`, 105 height pairs from 0.1 to 1,000 m, 915 and 2,440 MHz, 400 against 40,000 points): the minimum moves up to 5.2 dB, the maximum up to 54.1 dB, the 95th percentile up to 3.8 dB, the 5th up to 1.35 dB (all at 1,000 m ends, outside what the demo flies), the MEDIAN at most 0.52 dB, and the share of samples more than 3 dB off at most 0.05 (absolute).
found here: (1) `band_effect` says "a positive minimum is a loss overstated everywhere" and "a negative maximum ... understated everywhere": the 400-point minimum cannot show "everywhere" (it is the same grid statistic). (2) L23's "(from 200 m, 0.5 m with a 15 m partner is understated by up to 5.0 dB)" is a 400-point minimum from a grid starting at 200 m; C reproduced -5.02 at 400 points; nobody measured it at a finer grid. (3) The model's departure is the model's whole loss (curved earth, divergence, the transition) minus a flat Fresnel two-ray, so the extremes are where two nulls of different position sit near one another (B's observation); that is why they grow without limit as the sampling is refined and why the median and the share do not.
root cause: round 21 moved the card from a table of ten rows (each "measured" at 400 points) to a live computation at the same 400 points and kept the table's vocabulary: "bound", "up to", "minimum to maximum". A sample extreme is a statement about the grid. The class is "a number the sampling decides, printed as a limit": the Bellhop grid maximum (round 21, M-4) and this.
fix, smallest first (OD-1):
- (1, default) Make the output true by deleting the claim, not by adding machinery. The card and L23 print what is robust: for each pair of heights the MEDIAN of the model's loss minus the Fresnel loss over the 400 samples, and COUNTS of the 400 samples: how many are overstated by more than 3 dB (the margin too low there), how many are understated by more than 3 dB (the margin too high there). Example for the demo's pair (counts from `v1.py`): "median -1.9 dB; 18 of 400 samples overstate the loss by more than 3 dB (the margin is too low there), 20 of 400 understate it by more than 3 dB (the margin is too high there); the extremes are not stated". No "bound", no "up to", no "minimum to maximum", no "everywhere", no "over these pairs it is X to Y" sentence (an extreme of extremes), no stability sentence (C-2: deleted, not restated: at 0.1 m the claim holds (about 1 dB), at 2.2 m it holds for the median and not for the 95th percentile (0.24 dB), and any restatement is one more claim to prove), no "5.0 dB from 200 m" clause. `rfband.pair_band` keeps returning the minimum and maximum (the ten-row table fixture of tests/test_round18_x.py still holds them to an independent recomputation; they are documented there as sampling-limited and are not printed) and gains the two signed counts; `band_effect` decides its words from the counts. The robust statistics are the median and the counts, measured stable by `v4.py` (median within 0.52 dB, counts within 0.05 of the share, 400 against 40,000 points, over 105 pairs and 2 frequencies); the 5th and 95th percentiles are stable to 0.15 and 0.5 dB on the pairs of the demo but to 1.35 and 3.8 dB at the edge of the domain, so they are NOT proposed (a card that prints them would need the domain tolerance printed too).
- (2) Print the extremes of a dense grid (40,000 points: the maximum of the demo's pair has settled to 0.1 dB between 40,000 and 400,000 per C) with the words "the largest difference found on a 40,000-point grid, at an interference null". Rejected as the default: it still reads as a limit, the number is large (+71 dB) and means "two nulls sit at slightly different distances", which is not what a lab sizes a margin from; and the domain test would have to hold the grid-convergence for every pair.
- (3) Keep the 400-point extremes and say "of 400 samples" next to them. Rejected: the figures stay as they are and the page still implies a bound.
test that proves the sentences true over the whole input domain (a printed count is true by construction, so the tests guard the words and the arithmetic): (a) over a grid of heights 0.1 to 1,000 m (the `v4.py` grid, both frequencies) the three printed counts satisfy over + under = the existing "more than 3 dB off" count, each from 0 to 400, and the printed median equals `np.median` of the recomputed difference; (b) the generated card and L23 text of every pair of that grid contain none of "bound", "up to", "at most", "everywhere", "minimum", "maximum"; (c) the word chosen by `band_effect` follows the counts for every combination (over only, under only, both, neither: "no sample is more than 3 dB off"). The fix adds no claim about stability, so no stability test is needed; `docs/PHYSICS.md` 12.1 carries the measured sensitivity (the table above) as a dated measurement, not a promise.
What it could break: tests/test_round21_b.py (368, 384: the L23 text and the printed counts), tests/test_round18_x.py:259 (monkeypatches `pair_band` to a 4-tuple: it must return the new shape), tests/test_round18_a.py and test_round19_b.py (pin card sentences), tests/test_report.py; `report.json` `low_antenna` text and `credibility.html` L23 change (q24 against q23: the `usv-uas-rf` card text and L23 only); the lab loses the extremes (OD-1 says so). The counts are of 400 samples at Hs 0 from 300 m, as now.
owner decision: OD-1. sources: C-1, C-2 (+ found here)

### M-2. A Thorp-only acoustic link's Method line is wrong in two ways on a machine without Bellhop (the default `make install`): it says "Thorp budget decides every link" for an in-range link outside the +-6 dB band, and after `merge` it carries the count of the first batch   (sources: A-1, A-2, B-2)
severity: minor / status: confirmed (reproduced) / lane: honesty (class "first batch / first sample", "a label that names a method")
wrong data: yes. The "Method:" line of an acoustic link card and `links.<id>.method` of report.json, with Bellhop unavailable. (a) A-1: for an in-range needed link whose Thorp margin is outside +-6 dB the line is "Thorp budget decides every link"; RUNBOOK 52 says the report says "Thorp only, Bellhop unavailable" on each such link. Round 21's own measure (M-3) is that Thorp passes outside the band flip to Bellhop fails. (b) A-2 and B-2: `merge` rebuilds the label only when some batch carries a Bellhop count (`infos`); with no Bellhop `infos` is empty and `l0["method"]` (batch 0's) survives: the label describes one batch of 32 members of 64 and depends on batch order.
where: cafe/pm/stage1.py:709-717 (the `not comms.bellhop_available()` branch; the count there is the +-6 dB band's, `res["ambiguous"] & need`, not the samples that would have been refined), stage1.py:889-894 (`merge`), docs/RUNBOOK.md:52, tests/test_round21_a.py:199-204 (pins the old wording)
check: reproduced on orca (`v2.py`, Bellhop forced off): a link at 1.5 km, Thorp margin +18.38 dB at every sample: the method is "Thorp budget decides every link"; at 4.3 km (margin +1.45 dB) "Thorp only, Bellhop unavailable (5 ambiguous samples)". `merge` of batches labelled "(7 ambiguous samples)" and "(40 ambiguous samples)": "(7 ...)" for (A, B) and "(40 ...)" for (B, A); the merged link has 47.
root cause: round 21 rebuilt the label from summed counts through one function for the path in which Bellhop ran; the path in which it could not run was left on a separate wording with a different count (the +-6 dB band of round 20) and no `bellhop` record.
fix (closes the class for acoustic labels): `_acoustic` returns the same count record in the no-Bellhop path (`done=0`, `total` = the needed in-range samples within the cap of a pass or a fail, `beyond` as now, `ran=False`), and ONE function `_bellhop_label(info)` words it ("Thorp only, Bellhop unavailable: N needed in-range samples that Bellhop would refine keep their Thorp margin", plus the existing `beyond` clause); `merge` sums the records and rebuilds the label whenever any batch has one (it does already). The record is the one the Bellhop path counts, so the two paths cannot disagree about what "refined" means. A link with no needed in-range sample keeps "Thorp budget decides every link", which is true. New surface: one more key (`ran`) in a dict that only `merge` reads; no new constant, no new number that is not a count of a mask the code already makes. RUNBOOK 52 then states what the code does.
test that proves it over the domain: a property test over random masks (`need`, `valid`, margins from -120 to +120 dB, NaN included), random batch splits and both orders: with Bellhop off, the label of `merge(batches)` equals the label of one batch holding all the members, its N equals `(need & valid & |margin| <= cap).sum()` recounted, and merge(A, B) == merge(B, A); the same property with a fake `_bellhop_member` (Bellhop on) so that the two paths are held to one rule; and an enumeration test of every key of a real link result (see the class table below).
What it could break: tests/test_round21_a.py:199-204 and any test that pins "(N ambiguous samples)" in stage 1 (comms.py's own `THORP_ONLY_LABEL` for `acoustic_link` is unchanged); `report.json` `method` for acoustic links on a machine without Bellhop (q23 was run with Bellhop and its acoustic links have no needed in-range sample, so its labels do not move; the leaf-by-leaf q24 against q23 comparison must say so).
owner decision: none (OD-2 only for the wording). sources: A-1, A-2, B-2

### M-3. A `when: always` acoustic link to a glider that dives is judged by ONE pair of Bellhop depths per member: 25 % of a uniform range-by-depth grid (15 % of B's real samples) change pass/fail against the depth actually flown, in both directions, and the label says "Bellhop on 434 of 434 needed in-range samples" without saying it   (sources: B-1; the surfaced-depth case found here)
severity: minor (see the severity paragraph) / status: confirmed (mechanism reproduced here; B's 32 of 217 by the reviewer's run) / lane: physics, numerics, honesty
wrong data: yes, conditional on `when: always` (or any link whose end changes depth within the needed samples), Bellhop available and a profile with structure. The printed pass fraction and verdict of such a link, and the label's claim of "refined". Not the demo (its acoustic links are `surfacing`: the glider is at 0 to 1 m, the median depth is the depth).
where: cafe/pm/stage1.py:725-729 (`np.median(A[3][i, m])`, `np.median(B[3][i, m])`), the `ponytail:` note at 719-721 (says it; the report and report.json do not)
check: `v3.py`, real Bellhop, a made-up profile, the project's `_run_set` (as named, swapped, floored): the margin at glider depth g against the run at the median depth 514 m, 33 ranges 600 to 3,900 m, g from 0 to 950 m every 50 m: pass share at 514 m 0.45; 15 of 33 ranges change sign at g = 0 m, 14 at 100 m, 7 at 300 m, 1 at 500 m, 8 at 750 m, 15 at 950 m; 165 of 660 (25 %) in all; the largest difference 60 dB (the cap). Found here: the surfaced glider (0 m) flips as often (15 of 33) as the deepest one, so no single depth (not the median, not the mean) is a proxy for the cycle; and it is the same flip both ways, so the error is neither optimistic nor pessimistic on the average. B's real batch: 32 of 217 samples (member 0), pass share 0.069 against 0.180 with the depth bins; two near-surface samples +20 dB at the median depth and -24.9 dB at their own.
root cause: before round 21 only the samples within +-6 dB were refined, so one depth pair per member was a small approximation on few samples; "refine every sample" makes the one pair carry every sample, and the label (a count of "refined" samples) reads as if each had its own depth. The cheap approximation was documented in a docstring and nowhere a reader sees.
options with their cost (OD-2):
- (a, default) State the limit in the label and in PHYSICS 12.2: when Bellhop ran, the label adds "one pair of transducer depths per member (the median of the depths of its refined samples)". True by construction, no new number, no new constant, no cost. It does not make the margin right; it says what it is. If the lead wants a number: "N of the M refined samples have a transducer more than 50 m from the depth that was run", a count of a mask, true by construction (the 50 m is a printed definition, not a claim about accuracy).
- (b) Restrict refinement: samples whose own depth differs from the one run by more than D keep Thorp and are counted in the label (the `beyond` mechanism). No cost, but D is profile-dependent: from `v3.py` even 50 to 100 m from 514 m flips 1 to 4 of 33 here and near a thermocline far more; no D is true over the domain, so the sentence "cannot change which they are" cannot be written for it. Not recommended.
- (c) Per-depth-bin runs (depth quantile bins of the member's samples): the Bellhop calls multiply by the number of bins; round 21 measured 3 to 5 times the cost already (B: 224 calls, 237 s for 12 acoustic links x 4 members at 2 CPUs, about 1 s a call), so 4 bins is about 15 minutes for that fixture and an hour or more for a 64-member run. Right in principle, wrong for the budget; only if a lab flies `when: always` glider links.
- (d) Per-sample runs: about 0.2 s a sample, thousands of samples: no.
test: every label with `done > 0` (one batch, merged, both orders, one run or three) contains the depth sentence; with (a+) the count equals a recount of `|depth - run depth| > 50`.
What it could break: tests that pin the Bellhop label text (test_round21_a, test_stage1); report.json `method` of acoustic links with Bellhop (q23's has none refined).
owner decision: OD-2. sources: B-1 (+ found here)

### M-4. The RF card ignores a link's `when`: a UAS end `when: always` prints the airborne-leg heights and never the deck height at which the UAS sits between sorties   (sources: C-3)
severity: minor / status: confirmed by reading (the code paths) / lane: output correctness
wrong data: yes, for a mission with an RF link that has a UAS end and `when: always` (config accepts it; the only refusals are for gliders) or `surfacing` with a UAS at the other end; not the demo (`uas_airborne`). The card prints a band "for the link's own pair of heights" that is not the dominant pair: the UAS is at deck + antenna (8.1 m in the demo) on the deck almost all the time, and stage 1 needs every record.
where: cafe/pm/report.py:768-798 (`_end_heights`, the UAS branch) and `_low_antenna_note` (no use of `lk["when"]`); stage1.py:496 (`alt = alt + deck_height_m`: on the ground `alt` is 0, so the height is deck + antenna) and `_pos` (stage1.py:613); stage1.py:812-819 (`need` by `when`)
check: read; C ran it on orca: the note is byte-identical (1,131 characters) for `uas_airborne` and `always`. I did not rerun it.
fix: `_end_heights` takes the link's `when` and, for every `when` except `uas_airborne`, adds the deck height + the antenna's height above the body to the UAS end's heights and says so ("on the deck at 8.1 m, flown at ..."). No other change; the card then prints the band of the pair stage 1 uses. New surface: one parameter and one list item.
test that proves it over the domain: for `when` in {always, surfacing, uas_airborne} x several (deck, levels, antenna) combinations, the set of heights the card prints for the UAS equals the set of heights `stage1._pos` gives on a synthetic `out` with grounded and airborne samples (the card and stage 1 are held to each other, not to a list).
What it could break: the pinned heights text of the demo's `usv-uas-rf` card must not change (`uas_airborne` keeps the legs only: a test that the q23 card text is byte-equal); tests/test_round21_b.py's UAS cases.
owner decision: none. sources: C-3

### M-5. `radios.yaml`, `modems.yaml` and `config/assumptions.yaml` are read without the finite-number test that the mission and the four vehicle platform files get: `tx_dbm: .inf` gives an RF link that always passes, and `hangar --platform radios` says "provenance OK"   (sources: D-1)
severity: minor (see the severity paragraph) / status: confirmed by reading (the reader and its callers; the twelve edits are the reviewer's run) / lane: robustness
wrong data: yes, conditional on a hand-edited non-finite number in one of three files: the RF link verdict (GO from `tx_dbm: .inf`, NO-GO or NaN from `.nan`), an acoustic margin, a sigma (`env_sigmas`), and the provenance line.
where: cafe/pm/config.py:145-165 (`_yaml` = `read_yaml`, "the one YAML reader"; `_finite` is called only at config.py:537 for the mission), cafe/pm/physics/comms.py:77-78 (`_yaml` of radios/modems), config.py:677-690 (`assumptions`, `env_sigmas`), cafe/pm/__main__.py:273-295 (`_hangar`)
reuse of an existing check (the lead's step 2): the four vehicle platform files are refused through `physics.check_params` (kind rules, `_numeric`, "Numbers the table does not list must still be finite, an integer too large for a float included"), which only the three platform loaders call; radios, modems and assumptions have no schema, so `check_params` does not fit them. What does fit them, and everything else, is `config._finite`: `_yaml` is the one reader (`read_yaml = _yaml`, config.py:165; no `yaml.safe_load` of ours elsewhere), `_finite` walks the constructed document, and `finite_real` is the one test.
every YAML the code loads, and its status today:

| file | read by | non-finite or oversized number refused? |
|---|---|---|
| missions/*.yaml (and a run's `mission.yaml`, a validated copy) | `config.load_mission`; `credibility` reads the copy | yes, `_finite` at config.py:537 |
| platforms/saildrone_explorer.yaml | `usv.load_platform` (`physics.check_params`) | yes (D: 4 variants x 3 leaves, rc 1) |
| platforms/seaglider.yaml, platforms/slocum.yaml | `glider.load_platform` (`check_params`) | yes |
| platforms/quad_uas.yaml | `uas.load_platform` | yes |
| **platforms/radios.yaml** | `comms._yaml`: `rf_margin`, `_radio`, Iridium, `uas.load_platform` (names), `credibility` | **NO** |
| **platforms/modems.yaml** | `comms._yaml`: bands, anchors, `valid_range_m`, `ambiguous_db`; `credibility` | **NO** |
| **config/assumptions.yaml** | `config.assumptions`, `env_sigmas`, `env.subgrid._assumptions`, `dtmb5415.assumed`, `credibility`, `ledger.values_sha256` | **NO** |
| config/perturbations.yaml | `stats.sampling.load_perturbations` | yes by its own checks (`_num`, finite and > 0, round 13), not through `_finite` |
| the overlay file (`CAFE_PM_OVERLAY`) | `env.conventions` | reads `waves.direction_convention`, a name: no number |
| the JSON tables (config/premission.json, subgrid.json, throughput.json, fea_hull_mesh_study.json) | `config.load_json` | integers and nesting (round 21); a NaN is readable on purpose |

fix (a reused check, one line): call `_finite(doc, path)` inside `_yaml`, after `_expanded_size` (it already says "before `_finite` ... walk it as a tree"). Then every row above is covered by construction, including a file added later, and the mission's own call becomes a second walk of a small document (keep or drop it). New surface: none (no new function, no new constant); the message gains the file's path (it already carries the path). The only attack is a document `_finite` cannot walk: `_expanded_size` runs first and bounds aliases; timestamps are not numbers; a `!!float` tag is walked after construction.
test that proves it over the domain: generated from the files, not a list of them: for every `platforms/*.yaml` and `config/*.yaml`, every numeric leaf set to `.nan`, `.inf`, `-.inf` and `10**400` (about 230 leaves a file, D) is refused by `config._yaml` with a ConfigError naming the file and the key, and `python -m cafe.pm hangar --platform <copy>` exits 1; plus a grep test that no `yaml.safe_load(` or `yaml.load(` of ours is outside config.py. A new YAML file is covered the day it is added.
What it could break: tests that pin a platform loader's own NaN message (the vehicle loaders' messages are pre-empted by `_finite`'s: "{path}: {where}: nan is not a finite number; write a number"); a document that legitimately holds `.nan` (none shipped: grep of every yaml; ledger values files hold values, not NaN receipts); the ledger's `values_sha256` of a file with a NaN now raises where it hashed (damaged input, named). Performance: one tree walk per `_yaml` call (`comms._yaml` is on the stage-1 path: measure; the documents are a few hundred leaves).
owner decision: none. sources: D-1

### M-6. A direction whose force is NaN reads as a drag area of 0.0000 m2 in the Hangar, since round 21 writes the NaN as null (and `vehicle.build` fails with an unnamed TypeError on the same null)   (sources: D-2, D-4)
severity: minor / status: D-2 mechanism confirmed (Node one-liner here: `fmt(-1 * null / 72, 4)` is "0.0000", the same with NaN is the dash), reachability of a NaN force not shown (cafe/cfd.py checks no force for finiteness; a diverged run is the plausible source; C looked for a path and found none); D-4 by reading / lane: robustness, honesty (sibling of round 21 M-12)
wrong data: D-2 yes (conditional), D-4 no.
where: cafe/static/app.js:464 (`fmt(-s * x.force[ax] / q, 4)`; `fmt` tests only the final value), cafe/hangar.py:396 (`_write_result`: every non-finite number, array items included, becomes null), cafe/vehicle.py:286-289 (`np.asarray(r["force"])` of a list holding null)
fix: D-2: `x.force[ax] == null ? "—" : ...` in app.js (a one-line guard; the same for any other array item of a result that app.js does arithmetic on: the builder greps `app.js` for every use of `.force`, `.moment`, `.viscous` and lists them). D-4: `vehicle.build` refuses a non-finite force or moment of a direction with a named ValueError (the design and the direction), before the arithmetic, and the callers that already turn a ValueError into a 400 keep doing so (the builder reads cafe/app.py:358, 548, mission.py:666, emulator.py:330 and says which end in a 500). No new machinery.
test: D-4 yes (Python): a result with null or NaN in any force or moment item of any direction names the design and direction. D-2: there is no JS test runner in the suite and a skipped test is banned; the builder runs the guard as one expression in Node (as D did), pastes the output into the hand-back, and says it is not run in a browser.
What it could break: a hangar result that today builds with a silent NaN drag (the old behaviour for a bare `NaN`) now refuses: that is the point.
owner decision: none. sources: D-2, D-4

### M-7. `vehicle.hull_lift` stores a grid index of 0.0 (a converged grid) when no coarse force exists, and looks only at the last angle; `drag_sigma` then narrows the spread to 0.10   (sources: D-3)
severity: minor / status: confirmed by reading (the reviewer's probe gives 0.05 with and 0.0 without `force_coarse`) / lane: statistics (sibling of round 21 M-5: a missing index is not a converged grid)
wrong data: yes, for a hand-made, older or truncated incidence result with no coarse forces: the sampled drag spread (hypot(0.10, 0) = 0.10 instead of the estimate's 0.30) and with it the verdict.
where: cafe/vehicle.py:395-398 (`gcis.append(...)` only `if a == alphas[-1] and all("force_coarse" ...)`), `vv.worst_gci(gcis)` with default 0.0 at the end of `hull_lift` (vehicle.py:399), `limits["lift_gci"]` (vehicle.py:334), cafe/mission.py:74 (`drag_sigma`)
fix: a plane that has no coarse force at the last angle contributes `inf` to `gcis` (a missing index is not a converged grid, the rule of `vv.gci_value`), so the plane count decides and the default 0.0 can only mean "no plane at all". One expression. `drag_sigma` already gives the estimate's spread for any untrusted index.
test over the domain: for every non-empty subset of the planes missing their coarse forces, for 1 to 3 angles, `lift_gci` is inf; for none missing it is the finite worst index; `drag_sigma` of each is 0.30 and of the complete one `hypot(0.10, gci)` capped at 0.30. Check that `lift_gci` = inf is not written as a bare `Infinity` by any writer of `limits` (builder greps).
What it could break: a design whose incidence result has no coarse forces now samples drag with the estimate's 0.30 spread: wider, honest. tests that stand in a hull result without `force_coarse` (the round 20 and 21 seed tests gained a `gci` per direction; the builder adds `force_coarse` where the test means a converged hull).
owner decision: none. sources: D-3

---

## Minor, wrong data: no (M-8 to M-12)

### M-8. No invariant ties `need_count_median` and `granularity_ok` to `n_needed`; a hand-edited summary prints two contradictory sentences with green checks   (sources: C-4)
severity: minor / status: confirmed by the reviewer's run (stage 1 never writes such a summary: it needs a hand-edited or foreign one) / lane: robustness
wrong data: no (damaged input only; the checks refuse every other edit C tried).
where: cafe/pm/credibility.py:875-889 (`check_link_needed`), `check_censored` (accepts a share of 0.1 where stage 1 only records more than 0.5), report.py `_never_required_html`, `_granularity_samples_html`
fix (default: do not code it; record it): the two ties are one comparison each (`need_count_median` is 0 if and only if `n_needed` is 0 when both are stored; `censored.share` above 0.5), but each is a new check on input stage 1 never produces, and round 21 added the previous four. Default: PROBLEMS entry, no code. Alternative (OD-5): add the two comparisons to `check_link_needed` and `check_censored` (batch B's file), with the two hand-edited summaries as the tests.
sources: C-4

### M-9. `/api/live/{sid}/step` answers 500 for a 400-digit integer in a target's lat, lon, z or speed; `check_fleet` accepts `minutes: true`   (sources: D-5, D-7)
severity: minor / status: confirmed by reading (cafe/live.py:72-73 catches `(KeyError, TypeError, ValueError)`, `float(10**400)` is an OverflowError, an ArithmeticError) / lane: robustness (class "oversized number at a boundary": DECISIONS 1049 lists `live_step`)
wrong data: no.
fix: add `ArithmeticError` to that `except` (one word) and `not isinstance(l.get("minutes"), bool)` to the leg test (app.py:420); `{"lat": true}` is accepted as 1.0 there too: the same guard. Tests: `live_step` with `10**400` and `true` in lat, lon, z, speed and `-10**400` is the 400 of the module's own message; `check_fleet` with `minutes: true` is a 400.
sources: D-5, D-7

### M-10. The grep tests of round 21's JSON sweep stop at `cafe/` and miss four spellings   (sources: A-3, D-6)
severity: minor / status: confirmed by reading (tests/test_round21_e.py:65-101 walks `CAFE.rglob`; D's probe `p9.py` for the spellings) / lane: tests, documentation
wrong data: no (lab/check.py only forwards a document the app refuses; bench is a developer tool; neither feeds a verdict).
fix: extend `_modules()` to `lab/`, `bench/` and `bin/` `*.py`, and the rule to `import math as m; m.isfinite`, `getattr(json, "loads")`, `__import__("json").loads` and `json.JSONDecoder().decode`; and the docs say "78 sites in 30 files, `cafe/` and the scripts, and the rule". A tests-only batch.
sources: A-3, D-6

### M-11. `finite_real` is documented as refusing numpy scalars and accepts `np.float64`; statistics edges (`extreme_ranks` with an int array, a NaN `target`, `first_order` with NaN in `x`, an off-by-one of `n_certify` near 1e-16); `pair_band` accepts a frequency of 1e-300   (sources: A-4, D-8)
severity: minor / status: confirmed by the reviewers' runs / lane: documentation, statistics
wrong data: no (`stage1` passes a bool mask and finite arrays; the `n_certify` counts are near 2e15, above `MAX_COUNT`; the frequency comes only from a `radios.yaml` `center_mhz`, and with M-5 the file cannot hold a non-finite one).
fix (default): DECISIONS 1049 says "an `np.float64` is a float and passes, every other numpy number does not"; the rest to PROBLEMS with the inputs (the reviewers' probes), no code. Alternative (OD-6): the type or result check of each guard (`extreme_ranks` requires a bool mask of the length of `x`; `subset_simulation` requires a finite `target`; `first_order` a finite `x`), and a lower bound on `pair_band`'s frequency; each is a new refusal, the kind this loop has found to be the next sibling.
sources: A-4, D-8

### M-12. Test gaps found by mutation (A)   (sources: A-5)
severity: minor / status: by the reviewer's run (49 new mutants of round 21: 46 killed, the survivors listed in A-5) / lane: tests
wrong data: no.
fix: two tests, because two of the survivors sit in code that prints a count: `far_ge` (a sample at exactly the cap: `beyond` counts it and the refinement also does, so it is counted twice; refined margin exactly 0 is a fail where Thorp +60 is a pass) goes to batch A with M-2's property test (a mask at exactly +-60); `rb_off` (`>` against `>=` at exactly 3 dB) goes to batch B with M-1's count test (a pair whose difference is exactly 3 dB at one sample: the counts are strict). The other survivors (`dead_flush`, `cln_iff`, `cln_sum`, `rp_omit_none`, `rp_atfloor`, `hy_*`, `nc_log1p_th`, and round 20's equivalent `S1c`, `S1j`, `S1l`, `IVd`, `RMb`) are recorded in PROBLEMS (`cln_*` and `rp_omit_none` may be killed by `test_credibility.py` and `test_report.py`, which A did not run: the builder runs them before calling them gaps).
sources: A-5

---

## Class-closing fixes, in one place (the owner's whack-a-mole rule)

| class | siblings so far | the one place that closes it | where it lives |
|---|---|---|---|
| A number the sampling decides, printed as a limit | round 21 M-4 (Bellhop grid maximum), round 22 M-1 (400-point band extremes, "up to", "bound", "everywhere", the stability sentence, the 5.0 dB clause) | print only statistics measured stable over the domain (the median, counts of samples); no extreme of a sampled grid is printed or called a bound; a text lint test over the generated card and L23 | `rfband`, `report._low_antenna_note`, `credibility._l23_text`, the lint test |
| A text or number `merge` takes from the first batch, a label that names a method that did not run | round 21 M-4 (the Bellhop label), round 22 M-2 (Thorp-only label and count) | the count record in BOTH acoustic paths, ONE label function, `merge` sums and rebuilds; every key of a link and a vehicle result has a declared rule and a test that fails on a new key (the table below) | `stage1._acoustic`, `_bellhop_label`, `merge`, the enumeration test |
| The members that needed the link | rounds 19 to 21 | unchanged (`n_needed`); no sibling this round except M-8 (damaged input) | `stage1.summarize` |
| Non-finite or oversized number at a boundary | round 19 M-8, round 20 M-7, M-9, round 21 M-9, round 22 M-5, M-9 | `config._yaml` is the one YAML reader and now the one place `_finite` is called; `load_json` for JSON; the `ArithmeticError` in the live step; a generated test over every YAML and a grep test over every raw loader (including `lab/`, `bench/`, `bin/`) | `config.py`, `live.py`, `tests/test_round21_e.py` |
| A missing index is not a converged one | round 20 M3, round 21 M-5, round 22 M-7, M-6 | every GCI, in every plane and direction, goes through `vv.gci_value` / `worst_gci`, a missing one is inf; a NaN item of a result array is refused by name, shown as a dash | `vehicle.hull_lift`, `vehicle.build`, `app.js` |
| A card that does not know the link | round 21 M-2 (the cliff), round 22 M-4 (`when`) | `_end_heights` takes the link's `when` and the card is held to stage 1's `_pos` | `report._end_heights` |

### Enumeration for the label class: every key `merge` handles

Link result (`stage1.evaluate_link`, the keys named at stage1.py:841-842 and `extra`):

| key | how `merge` combines it | status |
|---|---|---|
| `frac`, `success`, `margin_db`, `n_invalid`, `need_count`, `dist_m` | concatenated along the member axis | fine |
| `bellhop_spread_db` (acoustic only) | concatenated | fine |
| `hs_filled` | summed over the batches | fine |
| `method` | **first batch's text, except rebuilt from the summed `bellhop` records when any batch has one** | **the defect (M-2) for the Thorp-only path; for an RF or Iridium link the text is constant by kind** |
| `bellhop` (acoustic only: the count record or None) | read by `merge` for the rebuild, then dropped from the merged link | after M-2 every acoustic batch carries one |
| `margin_kind`, `invalid_kind` | first batch (constants of the link's kind) | fine; the enumeration test asserts every batch agrees |
| `t` | first batch (the same time axis in every batch: one mission; for `uas_airborne` the union with the sortie windows, which are "the same in every batch") | fine; assert equal |

Vehicle result (`_run_glider`, `_run_usv`, `_run_uas`, `run_batch`):

| key | combined as | status |
|---|---|---|
| `lon`, `lat`, `depth`, `alt`, `airborne`, `surfaced`, `heading`, `sog_ms`, `stw_ms`, `u10_ms`, `wind_anem_ms`, `margin`, `profile_margin`, `energy_margin`, `battery_margin`, `scrubbed` | concatenated | fine |
| `fail`, `first` (dicts of arrays, incl. `left_data`) | concatenated per mode | fine |
| `fine` (UAS) | `t` first, the rest concatenated | fine |
| `sorties` (UAS) | `t_launch` first, every other key concatenated per sortie | fine |
| `hs_filled`, `wind3d` | summed | fine |
| `t`, `class`, `antenna_m`, `n_wp`, `hours_dropped` | first batch (properties of the platform and the mission, not of a member) | fine; assert equal |
| `margin_name`, `profile_margin_name`, `energy_margin_name`, `battery_margin_name` | first batch (a constant string per class and task mode) | fine; assert equal |
| `sim`, `wall_s` | dropped (the simulator object and the wall time of a batch) | by design; the test lists them as "dropped" |
| top level `U`, `X` | concatenated | fine |
| top level `seeds` | a list per batch | fine |

Builders close the class by the enumeration, not by the next sibling: a test runs a real tiny batch pair, takes the key set of every link and vehicle result, and fails on any key that is not in the table above (a new key must declare cat, sum, first-and-equal, rebuilt or dropped), and for every "first" key asserts that the batches agree. Alternative (OD-3): `merge` itself raises a ValueError naming the key when a "first" key differs between batches. That is new runtime surface on the happy path (a legitimate batch difference would stop a run); default: the test only.

---

## Open decisions (the lead takes the defaults)

- OD-1 (M-1): the RF band on the card and in L23. Options: (a) the median and the two signed counts of the 400 samples, extremes not printed, no stability sentence, no "5.0 dB" clause, no "bound"; (b) the extremes of a 40,000-point grid with the words "largest difference found"; (c) keep the extremes with "of 400 samples" beside them. Default: (a). The lead should know that (a) takes the figure "-10.8 to +39.2" away from the page and that it is the figure a reader quotes.
- OD-2 (M-3): the depth pair of a Bellhop run for a link whose end changes depth. Options: (a) state it in the label (constant sentence; optionally the count of refined samples more than 50 m from the depth run); (b) refine only samples near the depth run (a profile-dependent constant: not recommended); (c) per-depth-bin runs (3 to 5 times the cost again); (d) per-sample runs. Default: (a). The lead may rule M-3 major (see the severity paragraph).
- OD-3 (class table): the "first batch" enumeration as a test only, or also a runtime equality check in `merge`. Default: test only.
- OD-4 (M-5): `_finite` inside `config._yaml` (one place) against calling it in `comms._yaml`, `assumptions()` and the three other readers (three places, the next file is the next miss). Default: inside `_yaml`.
- OD-5 (M-8): the two summary invariants. Default: record in PROBLEMS, no code; the alternative is two comparisons in batch B.
- OD-6 (M-11): the statistics and frequency edges. Default: PROBLEMS and the DECISIONS 1049 wording; the alternative is a refusal per guard.
- OD-7 (round shape): whether round 23 is restricted to deletions and narrowings of claims plus the enumeration tests (see "Convergence"). Default: yes.

---

## Batches (non-overlapping by file; builders in parallel; G is last)

Contracts between batches: `rfband.pair_band` keeps its four-tuple and gains two signed counts (B only); the stage-1 count record gains `ran` (A only; `merge` is the only reader); `config._yaml` now refuses non-finite numbers (C; every other batch's tests that load a YAML with a non-finite number are named in C's hand-back).

### Batch A: stage 1 labels
- findings: M-2, M-3 (a), M-12 (`far_ge`)
- files: cafe/pm/stage1.py, tests/test_stage1.py, tests/test_round21_a.py, tests/test_round22_a.py (new: the label property test, the key enumeration test, the depth sentence)
- must fail before: M-2: with Bellhop off a link at +18 dB says "Thorp only, Bellhop unavailable: N ...", `merge` is order-independent and sums; M-3: every label with `done > 0` carries the depth sentence; M-12: a sample at exactly +-60 dB is counted once.
- notes: does not touch comms.py (`acoustic_link`'s own labels are unchanged); the hand-back says whether the CI link test's runtime moved (it should not).

### Batch B: report, credibility, the RF band
- findings: M-1, M-4, M-12 (`rb_off`), the `pair_band` frequency bound if OD-6 takes it, M-8 if OD-5 takes it
- files: cafe/pm/report.py, cafe/pm/credibility.py, cafe/pm/physics/rfband.py, tests/test_report.py, tests/test_credibility.py, tests/test_round18_a.py, tests/test_round18_x.py, tests/test_round19_b.py, tests/test_round21_b.py, tests/test_round22_b.py (new: the counts and words over the height grid, the lint of "bound" and the like, `_end_heights` against `stage1._pos`)
- must fail before: M-1: the card and L23 contain none of "bound", "up to", "at most", "everywhere", "minimum", "maximum", and print the median and the two counts; M-4: the card of a `when: always` UAS link prints the deck pair.
- notes: reads stage 1 (`_pos`) in a test only; the demo's `uas_airborne` card text moves only by the M-1 sentence.

### Batch C: the YAML boundary
- findings: M-5
- files: cafe/pm/config.py, tests/test_config.py, tests/test_round22_c.py (new: every numeric leaf of every platform and config YAML, the grep for the loader)
- must fail before: a copy of radios.yaml with `tx_dbm: .inf` is refused by `comms._yaml` and `hangar --platform` exits 1; every leaf of every file likewise.
- notes: the hand-back lists each existing test that pinned a platform loader's NaN message and how it changed, and the timing of `comms._yaml`.

### Batch D: vehicle, app, live
- findings: M-6, M-7, M-9
- files: cafe/vehicle.py, cafe/static/app.js, cafe/live.py, cafe/app.py, cafe/hangar.py only if the `Infinity` check of M-7 needs it, tests/test_vehicle.py (or the vehicle tests the builder names), tests/test_live.py, tests/test_app.py, tests/test_round22_d.py (new)
- must fail before: M-6: a null or NaN force names the design and direction; M-7: a missing coarse force gives `lift_gci` inf and the estimate's spread; M-9: `live_step` with `10**400` is a 400, `minutes: true` is a 400.
- notes: `app.js` is not run in a browser and has no suite test: the Node one-expression output goes in the hand-back.

### Batch E: the grep tests
- findings: M-10
- files: tests/test_round21_e.py (extended), docs only through G
- must fail before: a raw `json.loads` or `m.isfinite` of the four spellings in `lab/`, `bench/`, `bin/` or `cafe/` is named.

### Batch G: documents (last)
- findings: M-8, M-11 (as recorded), M-12 (the survivors) and every document a code batch changed
- files: DECISIONS.md (new rows 1057 onward, one per decision above; amend 1049, 1041, 1043 in place), CHANGELOG.md, docs/RUNBOOK.md (52: the label as the code says it; 190: no "bound", the median and the counts; the card bullet), docs/PHYSICS.md (12.1: "the model's whole loss minus a flat Fresnel two-ray", the measured sensitivity of the extremes to the sampling as a dated table, 105 pairs; 12.2: the one depth pair), docs/CREDIBILITY.md (L23 as generated), QUESTIONS_FOR_LAB.md, PROBLEMS.md (M-8, M-11, M-12's survivors, the real GOFS profile not run, `app.js` not run in a browser), STATUS.md, HANDOFF.md
- must say: the stop-rule count is 0 after round 22; q24 against q23 in every existing value (the new text of the RF card and L23 only); the Bellhop runtime before and after.

---

## Totals

- Findings: 12 merged from 19 source ids, plus the four found here (inside M-1, M-3 and the class table). By severity: 0 critical, 0 major, 12 minor.
- By status: confirmed 11 (reproduced on orca: M-1, M-2, M-3's mechanism; by reading: M-4, M-5, M-7, M-8, M-9, M-10, M-11; M-6's D-2 mechanism by a Node one-liner), partly confirmed 1 (M-6: reachability of a NaN force not shown), not confirmed 0, refuted 0. Resting on a reviewer's run alone: M-3's 32 of 217 (B), M-5's twelve edits (D), M-6's D-4 TypeError, M-8 (C), M-12 (A), the second halves of M-11 and M-10 (D's probes).
- Wrong data: yes (7 merged, 9 source ids): M-1 (C-1, C-2), M-2 (A-1, A-2, B-2), M-3 (B-1), M-4 (C-3), M-5 (D-1), M-6 (D-2, conditionally), M-7 (D-3). No (5): M-8 to M-12. History of wrong-data source ids by round: 5, 3, 5, about 9 reported, 9 confirmed.
- Reviewers' own ratings against this merge: all nine "yes" kept; D-2 kept with "reachability not shown"; every other source id "no" kept. One merge-level change: A-1 is merged with A-2 and B-2 because one record and one function close all three.

**Stop rule.** Round 22 is NOT clean: seven merged findings (nine source ids) give wrong data to act on, though none is critical or major. The count of consecutive clean rounds was 0 before this round and is 0 after it. The owner's stop rule needs two consecutive rounds with none.

## Not covered (by any reviewer or by this merge)

- This merge: B's real 217-sample member (my `v3.py` is a uniform grid on the same mechanism), the 5.0 dB clause at a finer grid, the RF band at Hs above 0 and for ranges nearer than 300 m, a real GOFS profile, `app.js` in a browser, a NaN force from a real diverged CFD run, the 12 YAML edits (D's), any full Stage-1 or demo run, any mutant of the proposed code.
- Reviewers: A did not run `rfband`, `report._end_heights`, `credibility._l23_text`, `acceptance._damage`, `jsonio` text/bytes/Path, `hangar._write_result`, `app._read` and 50 DECISIONS rows; B did not run a GOFS profile, `whoi_micromodem`, the HF band, `nbeams`, the UAS leg climbs, the 22.5 dB grid maximum or the isolated-null question; C did not run a real what-if to its end, the Stage-1 flip texts, `report --run` of an old plan, the app; D did not run a real zarr kill, two concurrent runs, the TAO lock, a mission with an untrusted index, the 78 sites one by one.

---

## Convergence

My view, for the lead to decide. The evidence: wrong-data source ids per round 5, 3, 5 and now 9; seven of this round's nine (M-1, M-2, M-3, M-4, M-6, M-7, and the label half of the class) sit in code or text that round 21 added; the sibling pattern (a new sentence or number is a new claim, and a reviewer finds the input where it is false) has repeated four rounds running.

- **Live RF band: keep the computation, roll back the claims.** The table with a cliff produced a finding in rounds 17, 18, 19, 20 and 21; the live band has produced none about coverage, so the computation is a net gain. The claims it was dressed in are not: "bound", "up to", "everywhere", the stability sentence and a "5.0 dB" clause are all statements about a grid, and my `v4.py` shows the minimum moves up to 5.2 dB and the maximum up to 54 dB between 400 and 40,000 points over the domain, while the median moves at most 0.5 dB. M-1 (a) is a deletion that makes the page true; I would take it, and I would not print percentiles (stable to 0.15 and 0.5 dB on the demo's pairs, 1.35 and 3.8 dB at the edge of the domain).
- **Refine-every-sample Bellhop: keep the refinement, the cap and the run set, state the limit.** Round 21 measured 7, 82 and 87 of 87 Thorp passes flipping on three profiles, so "Thorp decides" was wrong data and the refinement is justified by evidence; the 60 dB cap and the swapped/floored run set answer measured 12 to 34 dB disagreements. What round 21 did not finish is what "refined" means: one depth pair per member is a fine approximation for a surfaced glider and a bad one for a dive cycle (25 % of a uniform grid flips, both ways; Thorp, which it replaced, has no depth at all). The honest simple statement is M-3 (a): say it in the label. A partial roll-back is available and cheap: for a link that is not `surfacing` (the demo's) and has a submerged end, do not claim refinement at all and keep Thorp with that said; I did not make it the default because it deletes a refinement that is right for the demo's case and for every `when: surfacing` link, and because per-bin runs (the real fix) cost what a lab will not pay. The cost (3 to 5 times, about 1 s a Bellhop call) is the real argument against growing this further.
- **Subset sensitivity: keep.** B measured it (false-positive rate 3 to 6 % against 5 %, unbiased S1 on the subset, power falling with the subset as the floor says) and no reviewer found a wrong output; its one limit (a column that decides who needed the link cannot rank on the subset) is printed. It is the one round-21 addition that did what it said.
- **The loop itself.** Each round's fixes add roughly as many sentences and constants as they remove claims, and the reviewers attack the new ones. For round 23 I recommend the diff be net-negative in claims: only M-1's deletions, M-2's one function, M-3's constant sentence, one-line guards (M-4 to M-7, M-9) and tests that enumerate (the merge table, the YAML leaves, the height grid), no new check on input the product never produces (M-8, M-11 to PROBLEMS), and no new printed number that is not a count of a mask the code already makes. If round 23 then finds only things in code that round 22 did NOT touch, the class fixes are working; if it finds siblings of M-1, M-2 or M-5, the class fix was incomplete and the table above says which.
