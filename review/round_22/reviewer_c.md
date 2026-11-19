# Round 22, reviewer C (output correctness, the owner's rule as a lens)

Tree: `65e187e` (code of `c58fba0`, run q23). Reproductions ran on orca at 2 CPUs from a detached worktree (`../cafe-rev22-c`, `PMX=pm_rev22_c`), one job at a time.

## Findings

### C-1. The card's and L23's "up to +39.2 dB / down to -10.8 dB" are extremes of a 400-point grid, not bounds; a finer grid moves them by 10 to 47 dB
severity: minor
lane: honesty / numerics
where: cafe/pm/physics/rfband.py:20-21 (N_POINTS = 400) and `pair_band`; cafe/pm/report.py:872-876 (the "over these pairs ... overstated by up to ... understated by up to ..." sentence); cafe/pm/credibility.py `_l23_text` ("a bound"); docs/RUNBOOK.md:190 ("It is a bound against a Fresnel two-ray")
reproduction: on orca, `scratch_c/f3.py` (model `comms.two_ray_loss_db` minus `rfband.fresnel_loss_db`, 300 m to min(radio horizon, 12 km), Hs 0, 915 MHz), minimum / median / maximum and share more than 3 dB off by sample count:
- 2.2 m with 108.1 m: n = 400 gives -10.8 / -1.9 / +39.2 (0.095); n = 4,000 gives -14.7 / -1.9 / +48.7; n = 40,000 gives -14.9 / -1.9 / +70.9 (0.094); n = 400,000 gives -14.9 / -1.9 / +71.0.
- 0.5 m with 108.1 m: maximum +17.4 at 400, +64.3 at 4,000.
- 2.2 m with 18.1 m and 2.2 m with 15 m: no change (the null is not sharp there).
The q23 card prints "-10.8 to +39.2 dB ... overstated by up to 39.2 dB (the margin too low) and understated by up to 10.8 dB (the margin too high)" for exactly the first pair. The median and the share more than 3 dB off are stable; the extremes are not.
why it matters: the card, L23 and the RUNBOOK call the figure a bound ("up to"); for the pairs the demo itself has, the true extreme of the model against the same reference is 1.2 to 1.8 times (maximum) and 1.4 times (minimum) the printed one. A user sizing a link margin from "understated by up to 10.8 dB" gets 14.9 dB at 4,000 points. The merge noted the grid's maximum error for Bellhop but not for this band.
wrong data: yes. The "up to X dB" figures on the link card of `usv-uas-rf` (and the L23 UAS pairs) are printed as limits and are not.

### C-2. L23's "moving the lower antenna by 0.01 m moves a pair's figures by up to 1.0 / 0.4 / 0.2 dB, under 0.1 dB at 2.2 m" is false for the UAS-height pairs that L23 itself prints
severity: minor
lane: documentation / honesty
where: cafe/pm/credibility.py `_l23_text` (the "The figures move with the heights" sentence); docs/PHYSICS.md 12.1 "Height off a row" ("stay true and L23 prints them")
reproduction: `scratch_c/f2.py` on orca, `pair_band(h + 0.01, partner)` against `pair_band(h, partner)`, largest move of any of minimum, median, maximum:
- 2.2 m with 108.1 m: +0.01 m moves the maximum by 11.41 dB; -0.01 m moves the minimum by 1.19 and the maximum by 4.50 dB (claim: under 0.1 dB at 2.2 m).
- 0.5 m with 108.1 m: maximum moves 1.59 dB (+0.01) and 8.01 dB (-0.01) (claim: 0.2 dB at 0.5 m).
- 0.1 m with 108.1 m: 1.23 dB (claim: 1.0).
- 0.1 m with 0.5 m: 0.72; 0.1 m with 2.2 m: 0.84 (below 1.0, consistent).
The measured claim holds for the ten table pairs (partner 15 m or lower end), which is where it was measured; the sentence is general and sits in the same text as the 2.2 m with 108.1 m pair.
why it matters: the page tells the reader the figures are stable to a centimetre; the one pair the demo shows is not (same root as C-1: single-null extremes).
wrong data: yes (a stated stability of the printed figures that is wrong for the demo's own pair).

### C-3. The card ignores `when`: an RF link with a UAS end `when: always` prints the same airborne-leg heights and never the deck height the UAS sits at between sorties
severity: minor
lane: output correctness
where: cafe/pm/report.py:768-798 (`_end_heights`, UAS branch) and `_low_antenna_note` (no use of `lk["when"]`); cafe/pm/stage1.py:613 (`_pos`: height = `alt` (+ deck) + antenna, on the deck between sorties)
reproduction: `scratch_c/f4.py` on orca: `report._low_antenna_note(dict(id='x', a='usv', b='uas', kind='rf', radio='rfd900x', when=w, ...), demo_mission)` is byte-identical (1,131 characters, "uas (flown at 18.1, 38.1, 68.1, 108.1 m)") for `w = 'uas_airborne'` and `w = 'always'`. `config.load_mission` accepts `when: always` for an rf link with a UAS (the only refusals are gliders); stage 1 then needs every record and the UAS is at deck + 0.1 = 8.1 m on the deck almost all the time.
why it matters: for such a link the dominant height pair (2.2 or 15 m with 8.1 m) is not on the card, while the card says it is the band "for the link's own pair of heights".
wrong data: yes, for a mission with that link (not the demo): the card's band is of the wrong pairs.

### C-4. No invariant ties `need_count_median` / `granularity_ok` to `n_needed`; an inconsistent summary prints two contradictory sentences with green checks
severity: minor
lane: robustness / documentation
where: cafe/pm/credibility.py:875-889 (`check_link_needed`), report.py `_never_required_html` and `_granularity_samples_html`
reproduction: `scratch_c/g1.py`, row 11: edit `stage1b/summary.json` of a demo-shaped run to `n_needed=20, n_never_required=28, need_count_median=0, granularity_ok=False`. `check_summary` accepts it; the card prints "The link was required at no moment in 28 members ..." and "Required at no moment in the median member (0) ... not exercised in it" together; `check_rendered` is empty. Row 12 (`need_count_median=30` with `n_needed=0`) is refused only through the verdict. Likewise `check_censored` accepts a share of 0.1 although stage 1 only records more than 0.5, and then prints "0.1 of the ranked members share the same ... value" (a clip claim that is false).
why it matters: stage 1 never writes these, so it needs a hand-edited or foreign summary; it is the "field no invariant ties to another" the prompt asked for. Refused edits (n_needed above n, bool, float, text, NaN, 10**30, negative, adds-up) were all refused with the right message.
wrong data: no (damaged input only).

## Looked at, nothing found

- q23 recomputed from `q20_mission.json` (equal to q23's arrays): every link's k_fail (64, 64, 64, 0), median and 10th percentile of `frac`, median margin (15.16 dB; null for the acoustic links), `need_count_median` (249.5, 18.5, 71, 865), zero counts of `need_count` (0 everywhere, so `n_never_required` 0 and `n_needed` 64), the beyond-horizon share 0.8878, the median distances (80.14, 554.7, 632.5 km); vehicles' k_fail and mode counts (15, 0, 61, 62). All equal the summary.
- Wilson 90 % / 95 % bounds, the rule of three (3/64 = 0.0469) and n_certify 73 recomputed by hand: equal.
- `granularity.needed` of the four links: value 64, source `stage1b/summary.json summary.links.<id>.n_needed`, traces to `n_needed`; `on_needed` correctly absent (n_needed = n).
- The card of `usv-uas-rf`: heights (USV 2.2 m from `saildrone_explorer.yaml`; deck 8 + 10, 30, 60, 100 + 0.1 = 18.1, 38.1, 68.1, 108.1 m; 915 MHz from `radios.yaml`) read from the platform files; every figure (minimum, median, maximum, samples off: -3.2/-0.2/+0.6 (10), -8.1/-1.0/+24.4 (19), -9.9/-1.5/+30.3 (28), -10.8/-1.9/+39.2 (38)) reproduced with my own Fresnel two-ray written separately (`scratch_c/f1.py`, `comms.two_ray_loss_db` for the model). The "from 200 m, 0.5 m with 15 m partner is understated by up to 5.0 dB" of L23 reproduced (-5.02).
- `_low_antenna_note` driven over ends of 0.1, 0.5 (one ulp either side), 0.55, 2.2, 2.3, 15, 108.1, 1000, 1000.0001 m, bool, text, NaN, inf, 10**400, 0, -1; a UAS with levels [400], [10, 100], [], [10, 10], ['a'], deck True, antenna text, [1000], [990]; two UAS ends; a ship with no height, 15, 0.5, 0.4, 1000, 1001, text, True (`scratch_c/g2.py`): no traceback, no silent card, reference heights say "assumed". Cosmetic only: a height of 0.4999999 m prints as "0.5 m" (`:g`), and a UAS whose levels are readable but above 1000 m with the deck is described as "flight levels could not be read" (the loader limits levels far below that, so unreachable).
- `n_needed` variants through a real `report.write` and `check_rendered` (`scratch_c/g1.py`): 0, 1, 28 with never 20, n + 1, bool, 3.0, -1, NaN, '3', 10**30, missing with and without `n_never_required`; the sentences ("no member needed it", "N needed it", counts as a pass ... failed of the M that needed the link, the median among the needed) print as the RUNBOOK says. The baseline `mission.box ... not in the HTML` and receipt lines in that script come from running without ledgers (`ledgers=False`), not from the code.
- `_plan_sizes` read against `budget.plan` (the only writer; `n_max = min(N_MAX, n_batches * bs)`, `batch = min(bs, n_max)`), q23's plan (quick, 32, 32, 64) and the RUNBOOK row 280/304 wording: consistent. Not run with hostile plans end to end.
- The RUNBOOK 188 sentences ("3 failures of 64 is a GO, 3 of 24 MARGINAL") match `intervals.verdict` thresholds by hand arithmetic.
- `app.js` `gciText`, `hangar._write_result`, `app._read`, `_site_data.gci_table`, `vehicle.build`, `mission.drag_sigma` read as diffs: the logic is as the DECISIONS rows say. One observation, not reproduced: `app.js` draws `-s * x.force[ax] / q`; a `null` force item (a NaN written by `_write_result`) is 0 in JavaScript arithmetic and `fmt` would print 0.0000 m^2 beside " no index". Reaching it needs a CFD result with a NaN force, which I did not find a path to.
- Whether a "3 of 64 is GO beside 3 of 24 needed" pair of sentences is enough, or a second verdict is the next finding: a design question under DECISIONS 997 and 1042, I did not count it.

## Not run (allowance, or not possible)

- A real `whatif` to its end; the Stage-1 flip texts ('becomes' line, '(whole run: X)', same-members fix table) from a real run; `report --run` of an old run with a plan above the tables.
- The app in a browser or over HTTP.
- Censored clause for every ranked quantity from a real run (q23 has none); the censored record, `too_few` and `constant` cases through `stage1.summarize` with real arrays (only through `report.write` with edited summaries).
- CREDIBILITY and PHYSICS 12.2 Bellhop numbers (B's lane).

total: 4 findings (0 critical, 0 major, 4 minor)
Giving wrong data to act on: C-1, C-2, C-3 (C-4 does not).
