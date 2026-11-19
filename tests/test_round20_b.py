"""Round 20, batch B: the link card above 0.55 m and at 0.55 m (M-2: the envelope for an end of 0.55 to 2.2 m, the nearest-pair sentence at 0.55 m, L23;
round 21, M-2 replaced that with the live band of any pair: the tests of the envelope, of the nearest-pair sentences and of the cliff at 2.2 m are gone and
tests/test_round21_b.py holds their successors), what a user reads beside a GO of a link some members never needed (M-3), the check of `n_never_required`
(M-4), the clause on a battery-dominated USV's
ranked state of charge (M-12) and the test of the RPi mutant (M-10). One regression test per fix, each run against 8e22951 (it must fail there) and against the
fixed tree (it must pass); the hand-back says which job did which.
The envelope is recomputed here from the project's own reference (`tests.test_round18_b.band`: the model's loss minus a flat-earth Fresnel two-ray at Hs 0)."""
import json
import re

import pytest

from cafe.pm import config, credibility as cr, report, stage1
from cafe.pm.physics import glider
from cafe.pm.stats import intervals
from tests.fixtures import pm_run
from tests.test_report import data_dir, edit_json, load, plain, set_link_fields  # noqa: F401  (data_dir is autouse)
from tests.test_round18_a import rf
from tests.test_round18_x import card

ROOT = config.ROOT
DEMO = config.load_mission(ROOT / "missions" / "tepex_c_demo.yaml")


def l23():
    return {x["id"]: x for x in cr.LIMITATIONS}["L23"]["text"]


def ship_card(h, ship_h, monkeypatch):
    """The real `_low_antenna_note` for a glider-class end of height `h` and the ship, whose mast is `ship_h` (the mission's own `antenna_height_m`)."""
    mission = dict(vehicles=[dict(id="a", platform="pa")], ship=dict(id="ship", antenna_height_m=ship_h))
    monkeypatch.setattr(report, "_classes", lambda m: dict(a="glider"))
    monkeypatch.setattr(glider, "load_platform", lambda p: dict(antenna_height_m=h))
    return report._low_antenna_note(dict(kind="rf", a="a", b="ship"), mission)


# ------------------------------------------------------------------------------------------------------------------------- M-2: 0.55 to 2.2 m

def test_m2_the_demos_usv_uas_link_gets_exactly_this_card_and_no_other_link_of_the_demo_has_one():
    """What a demo shows for `usv-uas-rf` (round 20: 'no error band is stated'; round 21: the band of the whip with each of the UAS's four legs, computed;
    the figures are those of the independent reference, tests/test_round21_b.py). The demo's other links are acoustic or Iridium."""
    note = report._low_antenna_note(rf("usv", "uas"), DEMO)
    assert note == USV_UAS_CARD
    assert report._low_antenna_note(rf("uas", "usv"), DEMO) is not None
    assert [lk["id"] for lk in DEMO["links"] if report._low_antenna_note(lk, DEMO)] == ["usv-uas-rf"]


USV_UAS_CARD = ("The antennas of this RF link: usv (2.2 m), uas (flown at 18.1, 38.1, 68.1, 108.1 m). The two-ray model takes the ground "
                "reflection as -1; against a Fresnel two-ray at Hs 0 (a calm sea) at 915 MHz from 300 m to the pair's radio horizon or 12 km its "
                "loss minus the Fresnel loss is, by pair of heights: 2.2 m with 18.1 m -3.2 to +0.6 dB (median -0.2) (10 of 400 samples are more "
                "than 3 dB off); 2.2 m with 38.1 m -8.1 to +24.4 dB (median -1.0) (19 of 400 samples are more than 3 dB off); 2.2 m with 68.1 m "
                "-9.9 to +30.3 dB (median -1.5) (28 of 400 samples are more than 3 dB off); 2.2 m with 108.1 m -10.8 to +39.2 dB (median -1.9) "
                "(38 of 400 samples are more than 3 dB off); over these pairs it is -10.8 to +39.2 dB, both extremes are those of 2.2 m with "
                "108.1 m: the loss is overstated by up to 39.2 dB (the margin too low) and understated by up to 10.8 dB (the margin too high); a "
                "UAS is taken at each height it flies a leg at; the climbs between the legs pass other heights, which are not computed; at a wave "
                "height of 1 to 3 m these figures are different (L23); nearer than 300 m this is not stated (CREDIBILITY, limitation L23).")


def test_m2_the_whole_report_of_the_demo_run_carries_that_one_text(tmp_path):
    run = tmp_path / "run"
    m, plan = pm_run.make_run(run)
    report.write(run, m, plan)
    rep = load(run)
    notes = {lid: k["low_antenna"] for lid, k in rep["links"].items() if k["low_antenna"]}
    assert list(notes) == ["usv-uas-rf"] and notes["usv-uas-rf"].startswith("The antennas of this RF link: usv (2.2 m), uas (flown at ")
    assert report.check_traceability(rep) == [] and report.check_rendered(rep, (run / "report" / "index.html").read_text()) == []
    assert notes["usv-uas-rf"] in plain((run / "report" / "index.html").read_text())


def test_m2_the_usvs_whip_with_the_ships_15_m_mast_is_a_listed_row_that_prints(monkeypatch):
    """The row (2.2 m, 15 m) of `LOW_ANTENNA_PAIR_BAND` was in L23 and no card ever showed it (round 20: None), nor the row of two 2.2 m ends."""
    note = card(2.2, 15.0, monkeypatch)
    assert note.startswith("The antennas of this RF link: a (2.2 m), ship (15 m).")
    assert "(2.2 m with 15 m)" in note and "-3.3 to +0.2 dB (median -0.4)" in note and "not among those measured" not in note and "envelope" not in note
    assert "understated by up to 3.3 dB (the margin too high)" in note and "overstated by up to 0.2 dB (the margin too low)" in note
    two = card(2.2, 2.2, monkeypatch)
    assert two.startswith("The antennas of this RF link: a (2.2 m), b (2.2 m).") and "(2.2 m with 2.2 m)" in two


def test_m2_the_three_pinned_starts_are_unchanged_and_every_other_pair_gets_the_plain_one(monkeypatch):
    assert card(0.5, 0.3, monkeypatch).startswith("Both ends of this RF link have an antenna of 0.5 m or lower: a (0.5 m), b (0.3 m).")
    assert card(0.3, 2.2, monkeypatch).startswith("An end of this RF link has an antenna below 0.5 m: a (0.3 m).")
    assert card(0.5, 2.2, monkeypatch).startswith("An end of this RF link has an antenna of 0.5 m: a (0.5 m).")
    assert card(0.51, 15.0, monkeypatch).startswith("The antennas of this RF link: a (0.51 m), ship (15 m).")
    assert card(1.0, 15.0, monkeypatch).startswith("The antennas of this RF link: a (1 m), ship (15 m).")


def test_m2_l23_says_what_the_card_does():
    t = l23()
    assert "The card of every RF link computes the band of the link's own pair of heights, for any heights from 0.1 m to 1000 m" in t
    assert "for none above that" not in t and "envelope" not in t and "within 0.05 m of a listed pair" not in t and "is read as that one" not in t


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
    assert g["needed"]["source"] == "stage1b/summary.json summary.links.usv-uas-rf.n (less n_never_required)"          # a summary with no `n_needed`
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
            "no member needed it (0 members out of 48 members).") in c
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
