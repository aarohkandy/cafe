"""Round 20, batch B: the link card above 0.55 m and at 0.55 m (M-2: the envelope for an end of 0.55 to 2.2 m, the nearest-pair sentence at 0.55 m, L23),
what a user reads beside a GO of a link some members never needed (M-3), the check of `n_never_required` (M-4), the clause on a battery-dominated USV's
ranked state of charge (M-12) and the test of the RPi mutant (M-10). One regression test per fix, each run against 8e22951 (it must fail there) and against the
fixed tree (it must pass); the hand-back says which job did which.
The envelope is recomputed here from the project's own reference (`tests.test_round18_b.band`: the model's loss minus a flat-earth Fresnel two-ray at Hs 0)."""
import json
import re

import numpy as np
import pytest

from cafe.pm import config, credibility as cr, report, stage1
from cafe.pm.physics import comms, glider
from cafe.pm.stats import intervals
from tests.fixtures import pm_run
from tests.test_report import data_dir, edit_json, load, plain, set_link_fields  # noqa: F401  (data_dir is autouse)
from tests.test_round18_a import rf
from tests.test_round18_b import band
from tests.test_round18_x import card

ROOT = config.ROOT
DEMO = config.load_mission(ROOT / "missions" / "tepex_c_demo.yaml")
TOL = cr.LOW_ANTENNA_ROW_TOL_M
ENVELOPE = cr.mid_envelope()


def l23():
    return {x["id"]: x for x in cr.LIMITATIONS}["L23"]["text"]


def ship_card(h, ship_h, monkeypatch):
    """The real `_low_antenna_note` for a glider-class end of height `h` and the ship, whose mast is `ship_h` (the mission's own `antenna_height_m`)."""
    mission = dict(vehicles=[dict(id="a", platform="pa")], ship=dict(id="ship", antenna_height_m=ship_h))
    monkeypatch.setattr(report, "_classes", lambda m: dict(a="glider"))
    monkeypatch.setattr(glider, "load_platform", lambda p: dict(antenna_height_m=h))
    return report._low_antenna_note(dict(kind="rf", a="a", b="ship"), mission)


# ------------------------------------------------------------------------------------------------------------------------- M-2: 0.55 to 2.2 m

@pytest.mark.parametrize("ship_h", [10.0, 15.0])
@pytest.mark.parametrize("h", [0.56, 0.6, 0.75, 1.0, 1.5, 2.0, 2.19])
def test_m2_an_end_of_0_55_to_2_2_m_off_a_row_prints_the_card_and_the_measured_envelope(h, ship_h, monkeypatch):
    """Before: None (no card at all above 0.55 m) although the margin is too high by up to 5.1 dB there."""
    note = ship_card(h, ship_h, monkeypatch)
    assert note and note.startswith(f"An end of this RF link has an antenna of 0.55 to 2.2 m: a ({h:g} m).")
    assert f"this pair (a ({h:g} m), ship ({ship_h:g} m)) is not among those measured (L23 lists them), so no band of this pair is stated" in note
    assert ENVELOPE in note and "too high by up to 5.1 dB" in note and "too low by up to 2.2 dB" in note and "dB (median" not in note
    assert note.endswith("(CREDIBILITY, limitation L23).")


def test_m2_the_ship_at_2_2_m_off_the_listed_15_m_is_in_the_envelope_too(monkeypatch):
    note = ship_card(2.2, 10.0, monkeypatch)                                                      # the USV's whip under the ship's default 10 m mast: no row
    assert note and ENVELOPE in note and "dB (median" not in note


NO_BAND = " (L23 lists them), so no error band is stated for this margin (CREDIBILITY, limitation L23)."


@pytest.mark.parametrize("partner", ["uas", "shore", "ship 5 m", "ship 16 m", "end 2.2 m"])
def test_m2_a_partner_the_envelope_was_not_measured_for_gets_the_card_and_no_band(partner, monkeypatch):
    """The USV's whip with a UAS (the demo's link): the card says it is not measured and prints no figure, not the envelope of another partner."""
    if partner in ("uas", "shore"):
        note = report._low_antenna_note(rf("usv", partner), DEMO)
    elif partner == "end 2.2 m":
        note = card(1.0, 2.2, monkeypatch)
    else:
        note = ship_card(1.0, 5.0 if partner == "ship 5 m" else 16.0, monkeypatch)
    assert note and note.split("is not among those measured")[1] == NO_BAND and ENVELOPE not in note


def test_m2_the_demos_usv_uas_link_gets_exactly_this_new_card_and_no_other_link_of_the_demo_changes():
    """What a q22 demo shows for `usv-uas-rf` (before: no `low_antenna` text at all); the demo's three other links have no RF end below 2.2 m."""
    assert report._low_antenna_note(rf("usv", "uas"), DEMO) == (
        "An end of this RF link has an antenna of 0.55 to 2.2 m: usv (2.2 m). The two-ray model takes the ground reflection as -1, which cancels the two "
        "rays as an antenna goes to the surface, and its error is of the pair of heights: this pair (usv (2.2 m), uas (no single height)) is not among "
        "those measured (L23 lists them), so no error band is stated for this margin (CREDIBILITY, limitation L23).")
    assert report._low_antenna_note(rf("uas", "usv"), DEMO) is not None
    assert [lk["id"] for lk in DEMO["links"] if report._low_antenna_note(lk, DEMO)] == ["usv-uas-rf"]


def test_m2_the_whole_report_of_the_demo_run_carries_that_one_new_text(tmp_path):
    run = tmp_path / "run"
    m, plan = pm_run.make_run(run)
    report.write(run, m, plan)
    rep = load(run)
    notes = {lid: k["low_antenna"] for lid, k in rep["links"].items() if k["low_antenna"]}
    assert list(notes) == ["usv-uas-rf"] and notes["usv-uas-rf"].startswith("An end of this RF link has an antenna of 0.55 to 2.2 m: usv (2.2 m).")
    assert report.check_traceability(rep) == [] and report.check_rendered(rep, (run / "report" / "index.html").read_text()) == []
    assert notes["usv-uas-rf"] in plain((run / "report" / "index.html").read_text())


def test_m2_the_usvs_whip_with_the_ships_15_m_mast_is_a_listed_row_that_now_prints(monkeypatch):
    """The row (2.2 m, 15 m) of `LOW_ANTENNA_PAIR_BAND` was in L23 and no card ever showed it (before: None), nor the row of two 2.2 m ends."""
    note = card(2.2, 15.0, monkeypatch)
    assert note.startswith("An end of this RF link has an antenna of 0.55 to 2.2 m: a (2.2 m).")
    assert "(2.2 m with 15 m)" in note and "-3.3 to +0.2 dB (median -0.4)" in note and "not among those measured" not in note and "envelope" not in note
    assert "understated by up to 3.3 dB (the margin too high)" in note and "overstated by up to 0.2 dB (the margin too low)" in note
    two = card(2.2, 2.2, monkeypatch)
    assert two.startswith("An end of this RF link has an antenna of 0.55 to 2.2 m: a (2.2 m), b (2.2 m).") and "(2.2 m with 2.2 m)" in two


def test_m2_the_card_stops_above_2_2_m_where_nothing_was_measured_and_l23_says_so(monkeypatch):
    assert card(2.3, 15.0, monkeypatch) is None and card(5.0, 15.0, monkeypatch) is None and ship_card(2.3, 10.0, monkeypatch) is None
    assert card(2.2 + TOL / 2, 15.0, monkeypatch) is not None                                      # the row tolerance, as everywhere
    assert "The card speaks for every RF link with an end of 2.2 m or lower and for none above that" in l23()


def test_m2_the_nearest_pair_is_named_at_exactly_0_55_m_as_at_0_549(monkeypatch):
    """`abs(0.55 - 0.5)` is 0.050000000000000044: the trigger admitted 0.55 m and the nearest-row test did not, so the clause that names the biased row
    vanished at the one value the start sentence calls the limit (reviewer A, A-1)."""
    for h in (0.549, 0.55):
        note = card(h, 15.0, monkeypatch)
        assert "the nearest measured pair, 0.5 m with 15 m, has a biased margin (" in note, h
    both = card(0.3, 0.55, monkeypatch)
    assert both.startswith("An end of this RF link has an antenna below 0.5 m: a (0.3 m).")
    assert "the nearest measured pair, 0.3 m with 0.5 m, has a biased margin (" in both
    assert "the nearest measured pair" not in card(0.5501 + 0.05, 15.0, monkeypatch)                  # 0.6001 m is 0.1 m off the row: nothing near


def test_m2_a_height_of_0_55_m_gets_the_envelope_as_well_as_the_nearest_pair(monkeypatch):
    note = card(0.55, 15.0, monkeypatch)
    assert note.startswith("An end of this RF link has an antenna just above 0.5 m (up to 0.55 m): a (0.55 m).") and ENVELOPE in note
    assert ENVELOPE not in card(0.549, 15.0, monkeypatch) and ENVELOPE not in card(0.51, 15.0, monkeypatch)       # below the measured range


def test_m2_the_three_pinned_starts_and_just_above_are_unchanged_and_the_fifth_is_new(monkeypatch):
    assert card(0.5, 0.3, monkeypatch).startswith("Both ends of this RF link have an antenna of 0.5 m or lower: a (0.5 m), b (0.3 m).")
    assert card(0.3, 2.2, monkeypatch).startswith("An end of this RF link has an antenna below 0.5 m: a (0.3 m).")
    assert card(0.5, 2.2, monkeypatch).startswith("An end of this RF link has an antenna of 0.5 m: a (0.5 m).")
    assert card(0.51, 15.0, monkeypatch).startswith("An end of this RF link has an antenna just above 0.5 m (up to 0.55 m): a (0.51 m).")
    assert card(1.0, 15.0, monkeypatch).startswith("An end of this RF link has an antenna of 0.55 to 2.2 m: a (1 m).")


def test_m2_the_envelope_constants_are_what_the_model_gives_against_the_fresnel_two_ray_to_0_1_db():
    """The grid is the card's: every 0.005 m of the lower end from 0.55 to 2.2 m and the partners 10, 12.5 and 15 m (the measured figures, on a 0.001 m grid
    and 4,953 pairs, were -5.136 and +2.199; a 0.05 m grid gave +2.13, which is why the grid is not 0.05 m)."""
    lows = np.round(np.arange(0.55, 2.2 + 1e-9, 0.005), 4)
    res = np.array([band(float(h), p) for p in (10.0, 12.5, 15.0) for h in lows])
    lo, hi = float(res[:, 0].min()), float(res[:, 2].max())
    assert abs(lo - cr.LOW_ANTENNA_MID_BAND[0]) <= 0.1 and abs(hi - cr.LOW_ANTENNA_MID_BAND[1]) <= 0.1, (lo, hi)
    assert lo < -5.05 and 2.15 < hi < 2.25 and cr.LOW_ANTENNA_MID_BAND == (-5.1, 2.2)
    # the worst too-high figure of any listed row is smaller (3.3 dB): the envelope is the larger risk, which is why the card prints it
    assert min(r[0] for r in comms.LOW_ANTENNA_PAIR_BAND.values()) == -3.3 and lo < -3.3


def test_m2_the_envelopes_range_and_partners_are_the_cards_and_the_platforms():
    assert cr.LOW_ANTENNA_MID_RANGE_M == (report.RF_LOW_ANTENNA_M + report.RF_NEAR_ANTENNA_M, max(lo for lo, _ in comms.LOW_ANTENNA_PAIR_BAND)) == (0.55, 2.2)
    assert cr.LOW_ANTENNA_MID_PARTNER_M == (stage1.ship_antenna_m(dict(ship={}), None), DEMO["ship"]["antenna_height_m"]) == (10.0, 15.0)


def test_m2_l23_says_what_the_card_does():
    t = l23()
    assert ENVELOPE in t and "-5.1 to +2.2 dB at Hs 0, margin too low by up to 2.2 dB and too high by up to 5.1 dB" in t
    assert "within 0.05 m of a listed pair it also names that pair as biased" in t and "a height further off is not measured: the card says so" in t
    assert "a height further off is not measured, the card says so and names the nearest listed pair as biased" not in t           # the sentence that was false
    assert t.startswith("RF links to a low antenna, an antenna below 0.5 m or the USV's 2.2 m whip:")


def test_m2_l23s_claims_hold_of_the_card_a_height_off_a_row_by_more_than_0_05_m_is_not_measured_and_names_nothing(monkeypatch):
    far = card(0.4, 15.0, monkeypatch)                                                             # 0.1 m from the rows 0.3 and 0.5
    assert "not among those measured" in far and "nearest measured pair" not in far and ENVELOPE not in far
    near = card(0.45, 15.0, monkeypatch)
    assert "the nearest measured pair, 0.5 m with 15 m" in near


# ------------------------------------------------------------------------------------------------------------------------- M-3: the members that needed it

@pytest.fixture
def run(tmp_path):
    d = tmp_path / "run"
    d.mkdir()
    return d


def card_of(h, lid="usv-uas-rf"):
    return plain(h.split(f"<div id='v-{lid}'>")[1].split("<div id='v-")[0])


def link_counts(run, lid="usv-uas-rf"):
    e = json.loads((run / "stage1b" / "summary.json").read_text())["summary"]["links"][lid]
    return e["k_fail"], e["n"]


def fail(run, k, lid="usv-uas-rf"):
    """The link `lid` of the stage-1b summary with `k` failed members (its verdict rebuilt from the counts, as stage 1 writes it)."""
    def go(d):
        e = d["summary"]["links"][lid]
        e.update(k_fail=k, verdict=intervals.verdict(k, e["n"], e["verdict"]["conf"]))
    edit_json(run / "stage1b" / "summary.json", go)


def write(run, **per_link):
    m, plan = pm_run.make_run(run)
    set_link_fields(run, **per_link)
    report.write(run, m, plan)
    rep, h = load(run), (run / "report" / "index.html").read_text()
    assert report.check_traceability(rep) == [] and report.check_rendered(rep, h) == []
    return rep, h


def test_m3_the_card_says_how_many_of_the_members_that_needed_the_link_failed_and_report_json_has_the_count(run):
    """3 failures of 64 is a GO and of the 24 members that needed the link a MARGINAL (reviewer C, C-1): the card gives the second figure, from counts the
    summary already holds. Before: no such sentence and no `needed` key."""
    m, plan = pm_run.make_run(run)
    n = link_counts(run)[1]
    fail(run, 5)
    set_link_fields(run, **{"usv-uas-rf": dict(need_count_median=30, granularity_ok=True, n_never_required=20)})
    report.write(run, m, plan)
    rep, h = load(run), (run / "report" / "index.html").read_text()
    assert report.check_traceability(rep) == [] and report.check_rendered(rep, h) == []
    g = rep["links"]["usv-uas-rf"]["granularity"]
    assert (g["needed"]["value"], g["needed"]["unit"], g["never_required"]["value"], g["members"]["value"]) == (n - 20, "members", 20, n) and n == 48
    assert g["needed"]["source"] == "stage1b/summary.json summary.links.usv-uas-rf.n (less n_never_required)"
    assert "counts as a pass in the P(fail) above; 5 members failed of the 28 members that needed the link." in card_of(h)
    assert sorted(set(g) - {"need_count", "ok", "one_sample", "allowed_miss"}) == ["members", "needed", "never_required"]            # one new key, no other


def test_m3_the_verdict_and_the_interval_of_the_card_are_unchanged_and_no_second_verdict_is_printed(run):
    """The sentence adds a count and no verdict: the link's P(fail), its verdict, n and its interval are those of the same summary with nothing never needed."""
    rows = []
    for name, never in (("a", 20), ("b", 0)):
        d = run / name
        m, plan = pm_run.make_run(d)
        fail(d, 5)
        set_link_fields(d, **{"usv-uas-rf": dict(need_count_median=30, granularity_ok=True, n_never_required=never)})
        report.write(d, m, plan)
        rows.append((load(d)["links"]["usv-uas-rf"], card_of((d / "report" / "index.html").read_text())))
    (r1, c1), (r0, c0) = rows
    for key in ("verdict", "k_fail", "n", "p_fail", "region", "stop_interval", "thresholds"):
        assert r1[key] == r0[key], key
    assert "needed the link" in c1 and "needed the link" not in c0
    sentence = re.search(r"The link was required at no moment.*?needed the link\.", c1).group(0)
    assert not any(w in sentence for w in ("GO", "MARGINAL", "NO-GO", "interval", "P(fail) ="))        # a count, not a second verdict


def test_m3_a_link_every_member_never_needed_does_not_say_its_members_count_as_passes_in_the_p_fail(run):
    """C-3: the first sentence was written for the partly-needed link and contradicted 'the P(fail) above counts nothing' two lines later."""
    from tests.test_report import _not_exercised
    m, plan = pm_run.make_run(run)
    _not_exercised(run)
    n = json.loads((run / "stage1b" / "summary.json").read_text())["summary"]["links"]["usv-uas-rf"]["n"]
    set_link_fields(run, **{"usv-uas-rf": dict(n_never_required=n)})
    report.write(run, m, plan)
    rep, h = load(run), (run / "report" / "index.html").read_text()
    assert report.check_traceability(rep) == [] and report.check_rendered(rep, h) == []
    c = card_of(h)
    assert (f"required at no moment in {n} members, out of {n} members: in each of those it passes by default (a pass fraction of 1.0); "
            "no member needed it.") in c
    assert "counts as a pass in the P(fail) above" not in c and "failed of the" not in c
    assert "the P(fail) above counts nothing; the verdict is NOT EXERCISED, not GO" in c
    assert rep["links"]["usv-uas-rf"]["granularity"]["needed"]["value"] == 0


@pytest.mark.parametrize("fields", [dict(n_never_required=0), dict(n_never_required=None), dict()], ids=["zero", "none", "absent (an older run)"])
def test_m3_no_sentence_when_every_member_needed_the_link_or_the_run_did_not_count(run, fields):
    rep, h = write(run, **{"usv-uas-rf": dict(need_count_median=30, granularity_ok=True, **fields)})
    assert "needed the link" not in card_of(h) and "required at no moment in" not in card_of(h)
    g = rep["links"]["usv-uas-rf"]["granularity"]
    assert g["needed"] is None if fields.get("n_never_required") is None else g["needed"]["value"] == g["members"]["value"]


def test_m3_two_links_one_partly_needed_and_one_not_still_render_traceably(run):
    """Found while adding `needed`: since round 19 the page prints the three counts of the link that has a member that never needed it, `check_rendered` then
    asks every link for the same shape, and the second link's '0 members' (printed nowhere) made `report --run` and the report stage's own check fail. Before
    this fix the second assert failed with three problems (never_required, members and needed of the second link, the last as a key it did not have)."""
    m, plan = pm_run.make_run(run)
    set_link_fields(run, **{"usv-uas-rf": dict(need_count_median=30, granularity_ok=True, n_never_required=20),
                            "glider_eq-ship-acoustic": dict(need_count_median=30, granularity_ok=True, n_never_required=0)})
    report.write(run, m, plan)
    rep, h = load(run), (run / "report" / "index.html").read_text()
    assert report.check_traceability(rep) == []
    assert report.check_rendered(rep, h) == []
    assert "needed the link" not in card_of(h, "glider_eq-ship-acoustic")
    gone = json.loads(json.dumps(rep))                                                           # the exemption is for a count of 0: a dropped print is found
    gone["links"]["glider_eq-ship-acoustic"]["granularity"]["never_required"]["value"] = 3
    assert [b for b in report.check_rendered(gone, h) if "glider_eq-ship-acoustic.granularity.never_required" in b]


# ------------------------------------------------------------------------------------------------------------------------- M-4: the count is a count

@pytest.mark.parametrize("bad", ["n_plus_1", -1, 1.5, True, "x", float("nan"), "3", [3], 1e30],
                         ids=["more than n", "negative", "fraction", "bool", "string", "NaN", "numeral", "list", "huge"])
def test_m4_a_never_required_count_that_is_not_a_count_is_refused_like_k_fail_and_n(run, bad):
    """Before: 70 of 48 printed 'required at no moment in 70 members, out of 48' with green checks, and NaN failed `report --run` late."""
    m, plan = pm_run.make_run(run)
    k, n = link_counts(run)
    set_link_fields(run, **{"usv-uas-rf": dict(need_count_median=30, granularity_ok=True, n_never_required=n + 1 if bad == "n_plus_1" else bad)})
    with pytest.raises(config.ConfigError) as e:
        report.write(run, m, plan)
    assert "summary.links.usv-uas-rf: n_never_required" in str(e.value) and "is not a count" in str(e.value)
    assert "the summary was edited or is damaged; run it again (--fresh)" in str(e.value)


def test_m4_more_members_that_never_needed_the_link_than_passed_is_damaged_too(run):
    """A member that never needed the link passes, so k_fail failures leave at most n - k_fail members that never needed it."""
    m, plan = pm_run.make_run(run)
    n = link_counts(run)[1]
    fail(run, 5)
    set_link_fields(run, **{"usv-uas-rf": dict(n_never_required=n - 5 + 1)})
    with pytest.raises(config.ConfigError, match="n_never_required"):
        report.write(run, m, plan)
    set_link_fields(run, **{"usv-uas-rf": dict(n_never_required=n - 5)})                          # the largest consistent count
    report.write(run, m, plan)


@pytest.mark.parametrize("never", [None, 0, 5, 48])
def test_m4_a_count_of_a_whole_summary_is_accepted_and_the_check_names_the_link(never):
    s = dict(summary=dict(vehicles={}, links=dict(a=dict(k_fail=0, n=48, n_never_required=never), b=dict(k_fail=0, n=48))))      # b: an older summary
    cr.check_summary(s)
    s["summary"]["links"]["b"]["n_never_required"] = 49
    with pytest.raises(config.ConfigError, match=r"summary\.links\.b: n_never_required 49"):
        cr.check_summary(s)


def test_m4_a_vehicle_entry_has_no_never_required_count_and_is_not_asked_for_one():
    cr.check_summary(dict(summary=dict(vehicles=dict(v=dict(k_fail=1, n=4, n_never_required=99)), links={})))                   # not a link's key


# ------------------------------------------------------------------------------------------------------------------------- M-10 RPi

def test_m10_rpi_a_summary_with_no_member_count_keeps_neither_the_never_required_count_nor_the_members_nor_the_needed():
    """Mutant RPi (`never is None or e.get("n") is None` reduced to the first half): the three nodes are stored together or not at all, so no card can say
    '3 members out of n/a'. Equivalent for a real run (`summarize` always writes `n`; `_stat` reads it first): a unit test of `_granularity`."""
    ref = dict(stage="stage1b", receipt="r", ledger="checkpoints/stage1b/ledger.json")
    e = dict(need_count_median=30, granularity_ok=True, n_never_required=3)
    g = report._granularity(e, 0.95, ref, "s")
    assert g["never_required"] is None and g["members"] is None and g["needed"] is None and g["need_count"]["value"] == 30
    g = report._granularity(dict(e, n=10), 0.95, ref, "s")
    assert (g["never_required"]["value"], g["members"]["value"], g["needed"]["value"]) == (3, 10, 7)


# ------------------------------------------------------------------------------------------------------------------------- M-12: the censored SoC

def usv_text(run, n_empty, quantity=None):
    """The USV's card as text, when stage 1 stored `n_empty` emptied packs for it and ranked `quantity` (default: the state of charge)."""
    m, plan = pm_run.make_run(run)

    def go(d):
        v = d["summary"]["vehicles"]["usv"]
        v["energy"] = dict(soc_min_median=0.0, soc_min_p10=0.0, soc_min_lowest=0.0, n_empty=n_empty)
        v["sensitivity"] = dict(v["sensitivity"], quantity=quantity or stage1.QUANTITY["energy_margin"])
    edit_json(run / "stage1b" / "summary.json", go)
    report.write(run, m, plan)
    rep, h = load(run), (run / "report" / "index.html").read_text()
    assert report.check_traceability(rep) == [] and report.check_rendered(rep, h) == []
    return plain(next(b for b in h.split("<div class=card>") if b.startswith("<h3>usv ")))


CLAUSE = "ended with an empty pack: their lowest state of charge is the same 0, the clip, so this index rests on the other members and on a tie among these)."


def test_m12_a_battery_dominated_usv_says_its_ranked_state_of_charge_is_mostly_the_clip(run):
    """59 of 64 members at 0 (reviewer B): the index of a quantity that is the same 0 for most members rests on the rest and on a tie, and the sentence said
    nothing. Before: no clause."""
    t = usv_text(run, 30)
    assert f"(30 members of the 48 members {CLAUSE}" in t
    assert t.index("Most sensitive to:") < t.index(CLAUSE) < t.index("Top sensitivities")


@pytest.mark.parametrize("n_empty, clause", [(5, False), (24, False), (25, True), (48, True)], ids=["5 of 48", "half", "just over half", "all"])
def test_m12_the_clause_needs_more_than_half_the_members_empty(run, n_empty, clause):
    assert (CLAUSE in usv_text(run, n_empty)) is clause


def test_m12_no_clause_when_what_was_ranked_is_not_the_state_of_charge(run):
    """Where stage 1 fell back to the 0/1 failure indicator the index is not of the clipped quantity."""
    assert CLAUSE not in usv_text(run, 48, quantity="failure indicator")


def test_m12_a_run_whose_usv_ended_with_no_empty_pack_prints_no_clause(run):
    m, plan = pm_run.make_run(run)
    report.write(run, m, plan)
    assert "ended with an empty pack" not in (run / "report" / "index.html").read_text()
