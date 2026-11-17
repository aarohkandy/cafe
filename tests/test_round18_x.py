"""Round 18 addendum (DECISIONS 991 to 994): four items found after the round 18 merge, one regression test per fix, each seen to fail on 21fcff0.
Item 1: the direction of the low-antenna error depends on the PAIR of heights (card and L23); item 2: the acting columns of the UAS and the drift glider as
measured on the gridded demo environment; item 3: `fix.same_members.measured`; item 4: sentences round 18 added that say more than the code supports."""
import json
import re

import numpy as np
import pytest

from cafe.pm import config, credibility, report, stage1, whatif
from cafe.pm.physics import comms, glider
from tests.test_round16_report import data_dir  # noqa: F401  (autouse)
from tests.test_round17_d import F915
from tests.test_round18_a import WHOLE, fake_runs, flip_report, search
from tests.test_round18_b import band

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
    return report._low_antenna_note(dict(kind="rf", a="a", b="b" if h2 != 15.0 else "ship"), mission)


def floats(text):
    return [float(x) for x in re.findall(r"[+-]?\d+\.\d", text)]


# ---------------------------------------------------------------------------------------------------------------- item 1: the direction is of the pair

def test_x1_the_table_is_the_measured_band_of_every_pair_to_0_1_db():
    assert sorted(comms.LOW_ANTENNA_PAIR_BAND) == sorted(PAIRS)
    for pair in PAIRS:
        for got, printed in zip(measured(pair), comms.LOW_ANTENNA_PAIR_BAND[pair], strict=True):
            assert abs(got - printed) <= 0.1, (pair, measured(pair))


def test_x1_a_positive_figure_is_a_margin_too_low():
    """The margin is the budget minus the loss, so a loss the model overstates is a margin that is too low: what every direction word rests on."""
    r = comms._radio("rfd900x")
    d = np.array([400.0, 900.0, 2000.0])
    budget = r["tx_dbm"] + r["gt_dbi"] + r["gr_dbi"] - r["cable_loss_db"] - r["misc_loss_db"] - r["rx_sens_dbm"]
    assert np.allclose(comms.rf_margin(d, 0.5, 2.2, 0.0), budget - comms.two_ray_loss_db(d, 0.5, 2.2, 0.0, F915))
    assert measured((0.5, 2.2))[0] > 0.0                                                                    # 0.5 m with the USV's whip: overstated everywhere


@pytest.mark.parametrize("pair", PAIRS)
def test_x1_the_card_prints_the_measured_figures_and_the_direction_their_signs_give(pair, monkeypatch):
    note = card(*pair, monkeypatch=monkeypatch)
    if pair[0] > 0.5:
        assert note is None  # no end at or below 0.5 m: no card sentence (L23 has the pair)
        return
    mn, md, mx = measured(pair)
    assert note and note.endswith("(CREDIBILITY, limitation L23).") and "not among those measured" not in note
    assert f"({pair[0]:g} m with {pair[1]:g} m)" in note
    if mn > 0.0:                                                                                           # overstated everywhere: too low, never too high
        assert "the margin is too low by that much" in note and "too high" not in note and "understated" not in note
        lo, hi = map(float, re.search(r"is \+([\d.]+) to \+([\d.]+) dB", note).groups())
        assert abs(lo - mn) <= 0.1 and abs(hi - mx) <= 0.1, (pair, note)
    elif mx < 0.0:
        assert "the margin is too high by that much" in note and "too low" not in note and "overstated" not in note
    else:                                                                                                  # across zero: both, with each extreme
        over = re.search(r"overstated by up to ([\d.]+) dB \(the margin too low\)", note)
        under = re.search(r"understated by up to ([\d.]+) dB \(the margin too high\)", note)
        assert over and under and abs(float(over.group(1)) - mx) <= 0.1 and abs(float(under.group(1)) + mn) <= 0.1, (pair, note)
        assert "too low by that much" not in note and "too high by that much" not in note


def test_x1_the_seaglider_with_the_usv_is_too_low_not_too_high(monkeypatch):
    """The finding: round 18's sentence for an end of 0.5 m said 'can be too high' for a partner of 2.2 m or 15 m; with 2.2 m the model overstates the loss."""
    note = report._low_antenna_note(dict(kind="rf", a="glider_eq", b="usv"), DEMO)
    assert "too low by that much" in note and "too high" not in note and "can be too high" not in note and "at worst understates" not in note
    assert "+1.8 to +2.7 dB (median +2.6)" in note
    with_ship = report._low_antenna_note(dict(kind="rf", a="glider_eq", b="ship"), DEMO)  # the demo's ship mast is 15.0 m: the measured pair 0.5 / 15
    assert "overstated by up to 2.2 dB (the margin too low) and understated by up to 2.9 dB (the margin too high)" in with_ship


def test_x1_a_partner_height_that_was_not_measured_is_said_to_be_not_measured(monkeypatch):
    uas = report._low_antenna_note(dict(kind="rf", a="glider_2n", b="uas"), DEMO)  # a UAS flies at 18 to 108 m: not one of the measured heights
    assert "is not among those measured" in uas and "no error band is stated" in uas and "uas (no single height)" in uas
    assert "dB (median" not in uas and "too low" not in uas and "too high" not in uas                      # no other pair's figure stands in for it
    for h2 in (0.4, 1.0, 5.0, 10.0, 15.1):  # between or beyond the measured heights, near ones included
        note = card(0.3, h2, monkeypatch)
        assert "is not among those measured" in note and "dB (median" not in note, h2
    monkeypatch.undo()
    ship10 = dict(DEMO, ship=dict(DEMO["ship"], antenna_height_m=10.0))                                    # a ship mast of 10 m is not the measured 15 m
    note = report._low_antenna_note(dict(kind="rf", a="glider_eq", b="ship"), ship10)
    assert "is not among those measured" in note and "dB (median" not in note
    assert "glider_2n (0.3 m), usv (2.2 m)" not in uas                                                      # the UAS is named without a height


def test_x1_the_start_of_each_sentence_is_the_one_round_17_and_18_pinned(monkeypatch):
    assert card(0.5, 0.3, monkeypatch).startswith("Both ends of this RF link have an antenna of 0.5 m or lower: a (0.5 m), b (0.3 m).")
    assert card(0.3, 2.2, monkeypatch).startswith("An end of this RF link has an antenna below 0.5 m: a (0.3 m).")
    assert card(0.5, 2.2, monkeypatch).startswith("An end of this RF link has an antenna of 0.5 m: a (0.5 m).")


def test_x1_l23_states_every_pairs_figures_and_direction_not_a_pooled_one():
    t = {x["id"]: x for x in credibility.LIMITATIONS}["L23"]["text"]
    assert t.startswith("RF links to a low antenna, an antenna below 0.5 m or the USV's 2.2 m whip:")
    for pair in PAIRS:
        mn, md, mx = measured(pair)
        m = re.search(rf"(?<![\d.]){pair[0]:g} m \([^)]*\) with {pair[1]:g} m \([^)]*\) ([+-][\d.]+) to ([+-][\d.]+) dB \(median ([+-][\d.]+)\), "
                      r"(margin too [^;]*?)(?=;|\. A positive)", t)
        assert m, pair
        got = [float(x) for x in m.groups()[:3]]
        assert all(abs(g - w) <= 0.1 for g, w in zip(got, (mn, mx, md), strict=True)), (pair, m.group(0), mn, mx, md)
        effect = m.group(4)
        if mn > 0.0:
            assert effect == "margin too low", (pair, effect)
        elif mx < 0.0:
            assert effect == "margin too high", (pair, effect)
        else:
            e = re.fullmatch(r"margin too low by up to ([\d.]+) dB and too high by up to ([\d.]+) dB", effect)
            assert e and abs(float(e.group(1)) - mx) <= 0.1 and abs(float(e.group(2)) + mn) <= 0.1, (pair, effect)
    for gone in ("within 3.3 dB", "at worst understates", "can be too high; nearer", "so there the margin, the USV whip's included", "never too high"):
        assert gone not in t, gone
    assert "is not measured and no band is stated for it" in t and "UAS's 18 to 108 m" in t
    assert "understated by up to 5.0 dB" in t and "nearer than 300 m none of this is stated" in t


def test_x1_the_docstring_and_physics_say_the_direction_by_pair():
    doc = " ".join(comms.two_ray_curved_db.__doc__.split())
    for gone in ("within 3.3 dB of the Fresnel two-ray over that range and at worst UNDERSTATES",
                 "so there a margin can be too high: that includes the USV's 2.2 m whip"):
        assert gone not in doc
    for text in ("the margin is too LOW, never too high, over this range for the pairs 0.1 / 15, 0.3 / 15, 0.3 / 0.5, 0.3 / 0.3, 0.5 / 0.5, "
                 "0.3 / 2.2 and 0.5 / 2.2",
                 "up to 2.9 dB too high, up to 2.2 dB too low", "up to 2.4 dB too high, 1.6 dB too low", "up to 3.3 dB too high, 0.2 dB too low",
                 "which is overstated by +1.8 to +2.7 dB", "A pair that is not in the table is NOT MEASURED"):
        assert " ".join(text.split()) in doc, text
    para = " ".join(next(p for p in (ROOT / "docs" / "PHYSICS.md").read_text().split("\n\n") if p.startswith("**Low antennas**")).split())
    for text in ("0.5 m with a 2.2 m partner", "not measured", "too low, never too high"):
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


def test_x2_wind_direction_acts_on_the_uas_battery_reserve_and_not_on_its_profile_share():
    """Round 18 took `wind_direction_bias` out of the UAS profile share's row (its S1 there was 0.0134 in q18, under the floor): measured on the demo it
    moves the reserve margin by 2.5e-3 at some quantiles (the row still lists it) and the profile share by nothing, at 5 quantiles for 8 members'
    other draws."""
    assert "wind_direction_bias" in moved("uas", "margin") and "wind_direction_bias" in stage1.ACTING[("uas", "margin")]
    assert "wind_direction_bias" not in moved("uas", "profile_margin") and "wind_direction_bias" not in stage1.ACTING[("uas", "profile_margin")]
    assert moved("uas", "profile_margin") == {"wind_speed_bias"}
    assert set(stage1.UNSEEN[("uas", "profile_margin")]) == {"bulk_stress_scale", "battery_capacity_scale", "hs_scale"}


# ------------------------------------------------------------ item 4: a sentence that said a cause the code does not know

def test_x4_a_baseline_that_was_not_run_does_not_name_one_cause_when_there_are_two(tmp_path):
    """`base_same` is None when this vehicle's share of the Stage-1 budget did not cover a batch, and also when the unchanged mission left the environment data
    (`flip_search` catches `Invalid` from the baseline too); the line said only 'the share was spent'."""
    rep, t, _ = flip_report(tmp_path, base_same=None, verdict="NO-GO", p_fail=0.45, target="GO or MARGINAL", n=64, target_same=None)
    assert rep["vehicles"]["usv"]["fix"]["same_members"]["available"] is False
    assert "(this vehicle's share of the Stage-1 budget did not cover a run, or the unchanged mission leaves the environment data)" in t
    assert "share of the Stage-1 budget was spent" not in t
