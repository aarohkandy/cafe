"""Round 18 addendum (DECISIONS 991 to 994): four items found after the round 18 merge, one regression test per fix, each seen to fail on 21fcff0.
Item 1: the direction of the low-antenna error depends on the PAIR of heights (card and L23); item 2: the acting columns of the UAS and the drift glider as
measured on the gridded demo environment; item 3: `fix.same_members.measured`; item 4: sentences round 18 added that say more than the code supports."""
import json
import re

import numpy as np
import pytest

from cafe.pm import config, credibility, report, stage1, whatif
from cafe.pm.physics import comms, glider, rfband
from tests.test_round16_report import data_dir  # noqa: F401  (autouse)
from tests.test_round17_d import F915
from tests.test_round18_a import WHOLE, fake_runs, flip_report, search
from tests.test_round18_b import band
from tests.test_round22_b import counts_sentence, figs, ref_diff

pytestmark = pytest.mark.usefixtures("emulator_speed_not_tested")

ROOT = config.ROOT
DEMO = config.load_mission(ROOT / "missions" / "tepex_c_demo.yaml")
PAIRS = [(0.1, 15.0), (0.3, 15.0), (0.5, 15.0), (2.2, 15.0), (0.3, 0.5), (0.3, 0.3), (0.5, 0.5), (0.3, 2.2), (0.5, 2.2), (2.2, 2.2)]


def measured(pair):
    """Model minus a flat-earth Fresnel two-ray over 300 m to the pair's radio horizon or 12 km, recomputed here (minimum, median, maximum)."""
    return band(pair[1], pair[0])


def card(h1, h2, monkeypatch):
    """The real `_low_antenna_note` for a link between two ends of these heights: two vehicles of glider class with the heights patched into the platform
    loader, or a vehicle and the mission's ship when a height is 15 m (the ship's `antenna_height_m`)."""
    vehicles = [dict(id="a", platform="pa")] + ([dict(id="b", platform="pb")] if h2 != 15.0 else [])
    mission = dict(vehicles=vehicles, ship=dict(id="ship", antenna_height_m=15.0))
    monkeypatch.setattr(report, "_classes", lambda m: dict(a="glider", b="glider"))
    monkeypatch.setattr(glider, "load_platform", lambda p: dict(antenna_height_m=dict(pa=h1, pb=h2)[p]))
    return report._low_antenna_note(dict(kind="rf", when="uas_airborne", a="a", b="b" if h2 != 15.0 else "ship"), mission)


def floats(text):
    return [float(x) for x in re.findall(r"[+-]?\d+\.\d", text)]


# ---------------------------------------------------------------------------------------------------------------- item 1: the direction is of the pair

def test_x1_the_table_is_the_measured_band_of_every_pair_to_0_1_db():
    """Round 21, M-2: the table is a test fixture now, held to the independent recomputation AND to the live band the card prints (`rfband.pair_band`)."""
    assert sorted(comms.LOW_ANTENNA_PAIR_BAND) == sorted(PAIRS) == sorted(credibility.L23_PAIRS)
    for pair in PAIRS:
        for got, printed, live in zip(measured(pair), comms.LOW_ANTENNA_PAIR_BAND[pair], rfband.pair_band(*pair)[:3], strict=True):
            assert abs(got - printed) <= 0.1 and abs(live - printed) <= 0.1 and f"{live:+.1f}" == f"{printed:+.1f}", (pair, measured(pair))


def test_x1_a_positive_figure_is_a_margin_too_low():
    """The margin is the budget minus the loss, so a loss the model overstates is a margin that is too low: what every direction word rests on."""
    r = comms._radio("rfd900x")
    d = np.array([400.0, 900.0, 2000.0])
    budget = r["tx_dbm"] + r["gt_dbi"] + r["gr_dbi"] - r["cable_loss_db"] - r["misc_loss_db"] - r["rx_sens_dbm"]
    assert np.allclose(comms.rf_margin(d, 0.5, 2.2, 0.0), budget - comms.two_ray_loss_db(d, 0.5, 2.2, 0.0, F915))
    assert measured((0.5, 2.2))[0] > 0.0                                                                    # 0.5 m with the USV's whip


@pytest.mark.parametrize("pair", PAIRS)
def test_x1_the_card_prints_the_measured_figures_and_the_direction_their_signs_give(pair, monkeypatch):
    note = card(*pair, monkeypatch=monkeypatch)                                # round 20, M-2: the two rows with a 2.2 m lower end print too
    md = measured(pair)[1]
    assert note and note.endswith("(CREDIBILITY, limitation L23).") and "not among those measured" not in note
    assert f"({pair[0]:g} m with {pair[1]:g} m)" in note
    assert f"): {figs(*pair)}." in note and abs(float(re.search(r"median ([+-][\d.]+) dB", note).group(1)) - md) <= 0.1, (pair, note)
    x = ref_diff(*pair)                                                                  # the direction follows the counts of each sign, never an extreme
    over, under = int(np.sum(x > 3.0)), int(np.sum(x < -3.0))
    assert ("the margin is too low there" in note) == (over > 0) and ("the margin is too high there" in note) == (under > 0), (pair, note)
    assert ("at none is it understated" in note) == (over > 0 and under == 0) and ("at none is it overstated" in note) == (under > 0 and over == 0)
    assert ("at none of the 400 sampled ranges" in note) == (over == 0 and under == 0), (pair, note)


def test_x1_the_seaglider_with_the_usv_is_too_low_not_too_high(monkeypatch):
    """The finding of round 18: the sentence for an end of 0.5 m said 'can be too high' for a partner of 2.2 m or 15 m; with 2.2 m the model overstates the
    loss (the median is +2.6 dB: within 3 dB at every one of the 400 sampled ranges, so there is no direction to state beyond the median's sign)."""
    note = report._low_antenna_note(dict(kind="rf", when="uas_airborne", a="glider_eq", b="usv"), DEMO)
    assert "too high" not in note and "can be too high" not in note and "at worst understates" not in note
    assert f"(0.5 m with 2.2 m): {figs(0.5, 2.2)}." in note and "median +2.6 dB, at none of the 400 sampled ranges is the loss more than 3 dB off" in note
    with_ship = report._low_antenna_note(dict(kind="rf", when="uas_airborne", a="glider_eq", b="ship"), DEMO)  # the demo's mast: 15.0 m
    assert "median +1.3 dB, at none of the 400 sampled ranges is the loss more than 3 dB off" in with_ship and "understated by" not in with_ship


def test_x1_a_partner_height_that_was_not_listed_prints_its_own_figures_and_no_other_pairs(monkeypatch):
    """Round 21, M-2 (rounds 18 to 20: 'is not among those measured ... no error band is stated'): a UAS at 18.1 to 108.1 m, a height between or beyond the
    listed ones, a ship mast of 10 m: each prints the band of ITS pair, the independent reference's, and no word of a pair that was not measured."""
    uas = report._low_antenna_note(dict(kind="rf", when="uas_airborne", a="glider_2n", b="uas"), DEMO)
    assert "is not among those measured" not in uas and "no error band is stated" not in uas and "uas (flown at 18.1, 38.1, 68.1, 108.1 m)" in uas
    for h in (18.1, 38.1, 68.1, 108.1):
        assert f"0.3 m with {h:g} m {figs(0.3, h)}" in uas, h
    for h2 in (0.4, 1.0, 5.0, 10.0, 15.1):
        note = card(0.3, h2, monkeypatch)
        assert f"for this pair of heights ({0.3:g} m with {h2:g} m): {figs(0.3, h2)}" in note, h2
    monkeypatch.undo()
    ship10 = dict(DEMO, ship=dict(DEMO["ship"], antenna_height_m=10.0))                                    # a ship mast of 10 m
    note = report._low_antenna_note(dict(kind="rf", when="uas_airborne", a="glider_eq", b="ship"), ship10)
    assert f"for this pair of heights (0.5 m with 10 m): {figs(0.5, 10.0)}" in note


def test_x1_the_start_of_each_sentence_is_the_one_round_17_and_18_pinned(monkeypatch):
    assert card(0.5, 0.3, monkeypatch).startswith("Both ends of this RF link have an antenna of 0.5 m or lower: a (0.5 m), b (0.3 m).")
    assert card(0.3, 2.2, monkeypatch).startswith("An end of this RF link has an antenna below 0.5 m: a (0.3 m).")
    assert card(0.5, 2.2, monkeypatch).startswith("An end of this RF link has an antenna of 0.5 m: a (0.5 m).")


def test_x1_l23_states_every_pairs_figures_and_direction_not_a_pooled_one():
    t = {x["id"]: x for x in credibility.LIMITATIONS}["L23"]["text"]
    assert t.startswith("RF links, from an antenna below 0.5 m or one of 2.2 m to a UAS at 108 m:")
    for pair in PAIRS:
        md = measured(pair)[1]
        m = re.search(rf"(?<![\d.]){pair[0]:g} m with {pair[1]:g} m (median ([+-][\d.]+) dB, at [^;]*?)(?=;|\. A positive)", t)
        assert m and abs(float(m.group(2)) - md) <= 0.1 and m.group(1) == figs(*pair), (pair, m and m.group(0))
    for gone in ("within 3.3 dB", "at worst understates", "can be too high; nearer", "so there the margin, the USV whip's included", "never too high"):
        assert gone not in t, gone
    assert "none of it is a table row" in t and "the demo's USV whip (2.2 m)" in t and "highest (108.1 m) leg" in t
    assert "nearer than 300 m none of this is stated" in t and "up to" not in t


def test_x1_the_docstring_and_physics_say_the_direction_by_pair():
    doc = " ".join(comms.two_ray_curved_db.__doc__.split())
    for gone in ("within 3.3 dB of the Fresnel two-ray over that range and at worst UNDERSTATES",
                 "so there a margin can be too high: that includes the USV's 2.2 m whip"):
        assert gone not in doc
    for text in ("at the sampled ranges the margin is too LOW, never too high, for the pairs 0.1 / 15, 0.3 / 15, 0.3 / 0.5, 0.3 / 0.3, 0.5 / 0.5, "
                 "0.3 / 2.2 and 0.5 / 2.2",                                                       # round 22: the rows are 400 samples, not limits
                 "the rows' 2.9 dB too high and 2.2 dB too low", "2.4 dB too high, 1.6 dB too low", "3.3 dB too high, 0.2 dB too low",
                 "which is overstated by +1.8 to +2.7 dB", "A pair that is not in the table is computed live by"):
        assert " ".join(text.split()) in doc, text
    para = " ".join(next(p for p in (ROOT / "docs" / "PHYSICS.md").read_text().split("\n\n") if p.startswith("**Low antennas**")).split())
    for text in ("0.5 m with a 2.2 m partner", "computed live", "too low, never too high"):         # round 21 merge: "not measured" is superseded (rfband)
        assert text in para, text


# ------------------------------------------------------------ item 3: `same_members.measured` says what it means

def test_x3_flip_json_records_whether_the_same_members_baseline_was_read_from_the_base_runs_flags_or_run(monkeypatch):
    fake_runs(monkeypatch, WHOLE, set(range(11)))
    (flips, _), _ = search(WHOLE)                                                                      # the base run's flags: no batch is run for the baseline
    assert next(iter(flips.values()))["base_same"]["source"] == whatif.BASE_SAME_FLAGS
    calls = fake_runs(monkeypatch, WHOLE, set(range(11)))
    (flips, _), _ = search(WHOLE, flags=False)                                                         # no flags: the baseline is the first batch run
    assert next(iter(flips.values()))["base_same"]["source"] == whatif.BASE_SAME_RUN and calls[0][0] is True


BASE = dict(verdict="MARGINAL", p_fail=0.375, lo=0.23, hi=0.55, n=32)


def test_x3_the_report_says_measured_only_for_a_baseline_a_batch_was_run_for(tmp_path):
    kw = dict(verdict="NO-GO", p_fail=0.45, target="GO or MARGINAL", n=64, target_same="GO")
    got = {}
    for name, same in (("flags", dict(BASE, source=whatif.BASE_SAME_FLAGS)), ("run", dict(BASE, source=whatif.BASE_SAME_RUN)), ("old", dict(BASE)),
                       ("none", None)):
        rep, t, _ = flip_report(tmp_path / name, base_same=same, **kw)
        sm = rep["vehicles"]["usv"]["fix"]["same_members"]
        got[name] = (sm["available"], sm["measured"], sm["source"])
        assert (("P(fail) 0.375 on the same 32 members becomes" in t) is (same is not None)), name      # of its existence, not its source
    assert got == {"flags": (True, False, whatif.BASE_SAME_FLAGS), "run": (True, True, whatif.BASE_SAME_RUN), "old": (True, None, None),
                   "none": (False, False, None)}


# ------------------------------------------------------------ item 2: the acting table is what moved on the demo

MOVE = 1e-6                                    # the threshold of tests/test_round18_c.py's wide probe
VEHICLE_ROWS = {"glider_eq": dict(margin=("glider", "margin"), battery_margin=("glider", "battery_margin")),        # a Seaglider on station
                "glider_2n": dict(battery_margin=("glider", "battery_margin")),  # a Slocum drifting (its `margin` is the same array)
                "usv": dict(margin=("usv", "margin"), energy_margin=("usv", "energy_margin")),
                "uas": dict(margin=("uas", "margin"), profile_margin=("uas", "profile_margin"))}


def record():
    """`review/round_18x/demo_probe.json`: what `probe_acting.py` measured on orca on the demo's gridded environment (8 members' other draws, 5 quantiles,
    11 columns)."""
    return json.loads((ROOT / "review" / "round_18x" / "demo_probe.json").read_text())["vehicles"]


def moved(vid, key):
    return {col for col, mx in record()[vid]["quantities"][key]["max_abs"].items() if max(mx) > MOVE}


def test_x2_the_record_has_every_vehicle_quantity_and_column_and_the_threshold_sits_in_a_gap():
    rec = record()
    assert set(rec) == set(VEHICLE_ROWS) and all(r["members"] == 8 for r in rec.values())
    assert set(stage1.FORCING) | {"glider_speed_scale", "usv_vpp_bias", "bulk_stress_scale", "battery_capacity_scale", "solar_yield_scale"} == set(
        next(iter(rec["uas"]["quantities"].values()))["max_abs"])                                              # all eleven sampled columns
    sizes = [x for r in rec.values() for q in r["quantities"].values() for mx in q["max_abs"].values() for x in mx]
    assert all(len(mx) == 5 for r in rec.values() for q in r["quantities"].values() for mx in q["max_abs"].values())      # the five quantiles
    assert all(x <= 1e-7 or x >= 1e-5 for x in sizes), sorted(x for x in sizes if 1e-7 < x < 1e-5)       # a smooth 1e-8 or a step of 1e-4: nothing near MOVE


def test_x2_the_acting_table_is_the_set_of_columns_that_moved_each_quantity_on_the_demo_plus_the_unseen():
    for row in stage1.ACTING:
        got = set()
        for vid, keys in VEHICLE_ROWS.items():
            for key, r in keys.items():
                if r == row:
                    here = moved(vid, key)
                    assert here <= set(stage1.ACTING[row]), (vid, key, sorted(here - set(stage1.ACTING[row])))
                    got |= here
        assert got | set(stage1.UNSEEN.get(row, ())) == set(stage1.ACTING[row]), (row, sorted(got ^ set(stage1.ACTING[row])))


def test_x2_the_drift_gliders_battery_margin_moves_with_the_current_columns_on_the_demo():
    """Reviewer B found three columns (with `current_direction_bias`), batch C two (round 18's table): on the demo environment it is four. The two wind
    columns are float noise (1e-9); the Seaglider on station is moved by neither current column (5e-11). The current columns move it by a STEP: 1.6e-4 at
    the tail quantiles (the 95 % of the direction bias, the 75 and 95 % of the speed scale) and 1e-8 at the others, so a probe at the medians misses them."""
    assert moved("glider_2n", "battery_margin") == {"glider_speed_scale", "battery_capacity_scale", "current_speed_scale", "current_direction_bias"}
    assert moved("glider_eq", "battery_margin") == {"glider_speed_scale", "battery_capacity_scale"}
    assert set(stage1.ACTING[("glider", "battery_margin")]) == moved("glider_2n", "battery_margin")
    mx = record()["glider_2n"]["quantities"]["battery_margin"]["max_abs"]
    assert max(mx["wind_speed_bias"]) < 1e-8 and max(mx["wind_direction_bias"]) < 1e-8 and 1e-5 < max(mx["current_speed_scale"]) < 1e-3
    assert [x > 1e-5 for x in mx["current_speed_scale"]] == [False, False, False, True, True]               # a step at the tail quantiles, not a slope
    assert [x > 1e-5 for x in mx["current_direction_bias"]] == [False, False, False, False, True]


def test_x2_wind_direction_acts_on_the_uas_battery_reserve_and_on_its_profile_share_only_at_the_battery_limit():
    """Round 18 took `wind_direction_bias` out of the UAS profile share's row (its S1 there was 0.0134 in q18, under the floor): measured on the demo it
    moves the reserve margin by 2.5e-3 at some quantiles (the row still lists it) and the profile share by nothing, at 5 quantiles for 8 members'
    other draws. Round 19 (M-5) put it back, among the `UNSEEN`: the profile share steps (0.625 to 0.875) at an edge of the battery scale, which the demo's
    probe never reaches, and the wind direction moves that edge (reviewer B's bisection of the edge on the CI fixture)."""
    assert "wind_direction_bias" in moved("uas", "margin") and "wind_direction_bias" in stage1.ACTING[("uas", "margin")]
    assert "wind_direction_bias" not in moved("uas", "profile_margin") and "wind_direction_bias" in stage1.ACTING[("uas", "profile_margin")]
    assert moved("uas", "profile_margin") == {"wind_speed_bias"}
    assert set(stage1.UNSEEN[("uas", "profile_margin")]) == {"bulk_stress_scale", "battery_capacity_scale", "hs_scale", "wind_direction_bias"}


# ------------------------------------------------------------ item 4: a sentence that said a cause the code does not know

def test_x4_a_baseline_that_was_not_run_does_not_name_one_cause_when_there_are_two(tmp_path):
    """`base_same` is None when this vehicle's share of the Stage-1 budget did not cover a batch, and also when the unchanged mission left the environment data
    (`flip_search` catches `Invalid` from the baseline too); the line said only 'the share was spent'."""
    rep, t, _ = flip_report(tmp_path, base_same=None, verdict="NO-GO", p_fail=0.45, target="GO or MARGINAL", n=64, target_same=None)
    assert rep["vehicles"]["usv"]["fix"]["same_members"]["available"] is False
    assert "(this vehicle's share of the Stage-1 budget did not cover a run, or the unchanged mission leaves the environment data)" in t
    assert "share of the Stage-1 budget was spent" not in t


def test_x1_a_band_with_no_sample_over_reads_margin_too_high(monkeypatch):
    """No measured pair has a loss understated everywhere today; a re-measured one would, and the direction must follow its counts (the live band patched):
    understated at 200 of the 400, overstated at none."""
    monkeypatch.setattr(rfband, "pair_band", lambda h1, h2, f_hz=rfband.F_DEFAULT_HZ: (-9.0, -5.0, -3.5, 0.5, 0, 200))
    long = credibility.pair_figures((2.2, 2.2))
    assert long == "median -5.0 dB, " + counts_sentence(0, 200)
    assert "the margin is too high there" in long and "too low" not in long and "at none is it overstated" in long
