"""Round 16, batch A: what the report prints (M-3 hull note on a dive candidate, M-4 half-integer sample count, M-5 scrubbed launches, M-8 glider surface
fraction, M-9 Iridium sentence, M-10 USV battery margin), the what-if candidate notes, and that each new number is traceable."""
import html
import re

import numpy as np
import pytest

from cafe.pm import config, report, whatif
from cafe.pm.physics import glider
from tests.fixtures import pm_run

NOTE = "deeper than the collapse depth 330.6 m of the pressure hull the model assumes: the glider could not fly 712.5 m (QUESTIONS_FOR_LAB 4a)"
DEMO = config.load_mission(config.ROOT / "missions" / "tepex_c_demo.yaml")


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("CAFE_DATA", str(tmp_path / "data"))
    monkeypatch.setattr(report, "RECEIPTS", tmp_path / "model_receipts.json")


def plain(h):
    return html.unescape(re.sub(r"<[^>]+>", "", re.sub(r"<a class=lk[^>]*>[LR]</a>", "", h)))


@pytest.fixture
def full(tmp_path, monkeypatch):
    """The synthetic run of tests/fixtures/pm_run with what round 16 added to the summaries: scrubbed launches of the UAS (2 launches per member:
    members 0 and 1 of every 24 lose both, member 2 loses one), the lowest state of charge of the USV, glider records on the surface 4 times in 36,
    and a hull note on a fix."""
    real_batch, real_flip = pm_run._batch, pm_run.flip_rows

    def batch(rng, M, names, fail_frac):
        b = real_batch(rng, M, names, fail_frac)
        gone = np.zeros((2, M), bool)
        gone[0, :3], gone[1, :2] = True, True
        b["vehicles"]["uas"]["sorties"] = [dict(t_launch=pm_run.T0, scrubbed=gone[0]), dict(t_launch=pm_run.T0 + 86400.0, scrubbed=gone[1])]
        b["vehicles"]["uas"]["scrubbed"] = gone.sum(0)
        b["vehicles"]["usv"]["energy_margin"] = np.linspace(0.0, 0.9, M)
        sf = np.zeros_like(b["vehicles"]["glider_eq"]["lon"], bool)
        sf[::10] = True
        b["vehicles"]["glider_eq"]["surfaced"] = sf
        return b

    def flip():
        f = real_flip()
        f["vehicles"]["usv"]["best"]["hull_note"] = NOTE
        f["vehicles"]["uas"]["tried"][2]["hull_note"] = NOTE
        return f
    monkeypatch.setattr(pm_run, "_batch", batch)
    monkeypatch.setattr(pm_run, "flip_rows", flip)
    run = tmp_path / "run"
    m, plan = pm_run.make_run(run, thr={"stage1": {"glider": {"s_per_batch_day": 5.0, "s_per_member_day": 0.01, "measured": "2026-10-28", "host": "h"}}})
    report.write(run, m, plan)
    import json
    return run, json.loads((run / "report" / "report.json").read_text()), json.loads((run / "stage1b" / "summary.json").read_text())["summary"]


def test_the_scrubbed_launches_of_the_uas_are_counted_and_printed_and_a_scrubbed_day_is_not_a_failure(full):
    run, rep, summ = full
    assert summ["vehicles"]["uas"]["scrub"] == dict(launches=96, scrubbed=10, members_partly_scrubbed=2, members_all_scrubbed=4)
    sc = rep["vehicles"]["uas"]["scrub"]
    assert [sc[k]["value"] for k in ("launches", "scrubbed", "members_partly_scrubbed", "members_all_scrubbed")] == [96, 10, 2, 4]
    assert all(sc[k]["stage"] and sc[k]["receipt"] and sc[k]["ledger"].startswith("checkpoints/") for k in sc)                 # traceable like every number
    t = plain((run / "report" / "index.html").read_text())
    assert "Launches the weather gate scrubbed: 10 launches, of 96 launches in all " in t
    assert "(members with some scrubbed: 2 members; with every launch scrubbed: 4 members)" in t
    assert "A scrubbed launch is not a failed sortie" in t and "no_sortie_flown" in t
    assert report.check_traceability(rep) == [] and rep["traceability_problems"] == []


def test_a_summary_from_before_the_scrub_count_and_the_energy_margin_renders_without_them():
    assert report._counts(None, {}, "s", "launches", ("launches",)) is None and report._energy(None, {}, "s") is None


def test_the_usv_battery_margin_is_the_lowest_state_of_charge_and_the_emptied_members(full):
    run, rep, summ = full
    e = summ["vehicles"]["usv"]["energy"]
    assert e["soc_min_lowest"] == 0.0 and e["n_empty"] == 2 and e["soc_min_median"] == pytest.approx(0.45) and 0.0 <= e["soc_min_p10"] <= e["soc_min_median"]
    node = rep["vehicles"]["usv"]["energy"]
    assert node["n_empty"]["value"] == 2 and node["soc_min_median"]["value"] == pytest.approx(0.45)
    assert node["soc_min_lowest"]["ledger"].startswith("checkpoints/")
    t = plain((run / "report" / "index.html").read_text())
    assert re.search(r"Battery margin: the lowest state of charge each member reached, as a fraction of the pack: median 0\.45,", t)
    sentence = re.search(r"Battery margin.*?in weather\.", t).group(0)
    assert "2 members emptied it" in sentence and "solar_yield_scale" in sentence and "battery_capacity_scale" not in sentence
    assert "energy" not in rep["vehicles"]["uas"] or rep["vehicles"]["uas"]["energy"] is None


def test_the_glider_window_says_how_little_of_it_the_surface_current_is_seen(full):
    run, rep, _ = full
    node = rep["environment"]["forcing_at_windows"]["glider_eq"]["surfaced"]
    assert node["value"] == pytest.approx(4 / 36) and node["source"].startswith("stage1b/res.pkl vehicles.glider_eq.surfaced")
    assert "surfaced" not in rep["environment"]["forcing_at_windows"]["uas"] or rep["environment"]["forcing_at_windows"]["uas"]["surfaced"] is None
    t = plain((run / "report" / "index.html").read_text())
    assert re.search(r"A glider sees this surface current only while it is at the surface, 0\.1111 of the window \(mean over members\); its station loss "
                     r"follows the flow over the depth it dives through, not this value", t)
    assert t.count("A glider sees this surface current only while") == 2                                    # glider_eq and glider_2n; the USV and UAS have none


def test_every_iridium_verdict_carries_the_sentence_that_it_restates_assumed_numbers(full):
    run, rep, _ = full
    t = plain((run / "report" / "index.html").read_text())
    ir = [k for k in DEMO["links"] if k["kind"] == "iridium"]
    assert len(ir) == 1 and t.count(report.IRIDIUM_NOTE) == len(ir)                                          # once per Iridium link, on no other link's card
    assert report._iridium_html({"method": "two-ray over a 4/3-radius earth"}) == ""
    assert report.IRIDIUM_NOTE in report._iridium_html({"method": "Iridium SBD x"})
    assert "p_success" in report.IRIDIUM_NOTE and "sea state, weather or position" in report.IRIDIUM_NOTE


def test_the_default_rf_sensitivity_is_listed_on_the_credibility_page_as_assumed(full):
    run, _, _ = full
    page = (run / "report" / "credibility.html").read_text()
    assert "radios.rfd900x.rx_sens_dbm" in page and "air data rate" in html.unescape(page)


def test_a_fix_row_carries_the_note_that_its_dive_is_deeper_than_the_hull_can_fly(full):
    run, rep, _ = full
    best = rep["vehicles"]["usv"]["fix"]["best"]
    tried = rep["vehicles"]["uas"]["fix"]["tried"]
    assert best["hull_note"] == NOTE and tried[2]["hull_note"] == NOTE and tried[0]["hull_note"] is None
    t = plain((run / "report" / "index.html").read_text())
    # the best-row sentence, the same row in the table, the uas row
    assert f"Note: {NOTE}." in t and t.count(NOTE) == 3


def test_a_median_of_eighteen_and_a_half_samples_is_printed_as_eighteen_and_a_half():
    ref = dict(stage="stage1b", receipt="r1", ledger="checkpoints/stage1b/ledger.json")
    g = report._granularity(dict(need_count_median=18.5, granularity_ok=True), 0.95, ref, "s")
    t = plain(report._granularity_html(g, "GO"))
    assert "decided on 18.5 samples" in t and "one missed sample is 0.05405" in t


# ------------------------------------------------------------------------------------------------------------ the candidates of the what-if

def dives(vid):
    return {c["change"]: c.get("hull_note") for c in whatif.candidates(DEMO, vid) if "duty" in c["mod"]}


def test_a_dive_candidate_deeper_than_the_collapse_depth_is_offered_with_the_note_and_the_others_without():
    """Round 16, M-3: glider_eq is ordered to 950 m on a hull that collapses at 330.6 m; the candidates 712.5 and 475 m are deeper still; glider_2n (Slocum,
    500 m, collapse 654.6 m) offers 375 and 250 m, within it. The candidate is not dropped or capped."""
    eq = dives("glider_eq")
    assert [d for d in eq if "712.5 m" in d or "475 m" in d] and all(n and "330.6 m" in n for n in eq.values())
    assert {c["change"] for c in whatif.candidates(DEMO, "glider_eq")} >= set(eq)
    assert all(n and "could not fly" in n for d, n in eq.items() if "712.5" in d)
    assert dives("glider_2n") and all(n is None for n in dives("glider_2n").values())
    uas = [c for c in whatif.candidates(DEMO, "uas") if "hull_note" in c]
    assert uas == []


def test_a_missing_collapse_figure_says_the_check_was_not_made(monkeypatch):
    monkeypatch.setattr(glider, "hull_collapse_depth_m", lambda P, a: (None, "the stored figure is for another hull"))
    note = report.hull_depth_note("seaglider", 712.5)
    assert note and "was not checked against 712.5 m" in note and "another hull" in note
    assert report.hull_depth_note("not_a_platform", 100.0) is None                                  # a platform that cannot be read: no claim either way
    assert report.hull_depth_note("seaglider", 200.0) is not None                                   # still unchecked, whatever the depth
    monkeypatch.undo()
    assert report.hull_depth_note("seaglider", 200.0) is None and report.hull_depth_note("seaglider", 330.6) is None
    assert "could not fly 712.5 m" in report.hull_depth_note("seaglider", 712.5)
