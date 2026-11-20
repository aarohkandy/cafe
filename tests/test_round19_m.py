"""Round 19 merge: the cross-batch items that no batch could own.

A1 (M-1 follow-up): a link required in no member, or in some members only, says so on the card and in report.json (batch A's `n_never_required` is read, not
only stored). A2: `ingest-ocean` names an older copy of the store left beside the one it wrote (batch E's hand-back). A3 (M-14): the results of the real CFD
cache are accepted by `_seed._checked`, and the three of them seed end to end (batch D's check had only been tried on files built to the shape of
`cfd.characterize_*`'s return)."""
import json
import pathlib
import re
import shutil

import pytest
import yaml

from cafe import _seed, cfd
from cafe.pm import __main__ as cli, config, report, stage1
from cafe.pm.env import hycom
from tests import test_round19_a as a19
from tests.fixtures import pm_run
from tests.test_report import _not_exercised, data_dir, load, plain, set_link_fields  # noqa: F401  (data_dir is autouse)
from tests.test_round19_d import cached_files
from tests.test_stage1 import merged

@pytest.fixture
def run(tmp_path):
    d = tmp_path / "run"
    d.mkdir()
    return d


@pytest.fixture
def work(tmp_path, monkeypatch):
    """A private `$CAFE_WORK` with a private cache (the shared cache on orca is never named)."""
    monkeypatch.setattr(cfd, "CACHE", tmp_path / "work" / "cfdcache")
    return tmp_path / "work"


NAMES = list(stage1.priors_for(a19.MISSION)[1])
M24 = 24


# ------------------------------------------------------------------------------------------------------ A1: the summary of a real two-end link

def link_summary(lk, out, m=M24):
    """The stage-1 summary of the link `usv-uas-rf`'s slot filled with a real `evaluate_link` of `lk` over `out` (24 members, as `merged` has)."""
    res = merged({}, {})
    res["links"]["usv-uas-rf"] = a19.run(lk, out, m)
    return stage1.summarize(res, NAMES, a19.MISSION, 73)["links"]["usv-uas-rf"]


@pytest.mark.parametrize("lk", [a19.RF, a19.IRIDIUM, a19.ACOUSTIC], ids=["rf", "iridium", "acoustic"])
def test_a1_two_gliders_that_are_never_up_together_have_no_verdict_and_say_in_how_many_members(lk):
    """g1 is up at records 0 to 59 and g2 at 100 to 159: no moment has both up. Not a GO on zero required moments: NOT EXERCISED, in all 24 members."""
    e = link_summary(lk, a19.gliders(range(0, 60), range(100, 160), M24))
    assert e["verdict"]["verdict"] == stage1.NOT_EXERCISED and e["need_count_median"] == 0 and e["n_never_required"] == M24 and e["n"] == M24
    assert e["frac_median"] == 1.0 and e["k_fail"] == 0                                          # frac is the default 1.0: why it is no GO


def test_a1_two_uas_that_never_fly_together_are_not_exercised_either():
    e = link_summary(a19.LK_UU, a19.uas_pair(range(0, 50), range(100, 150), m=M24), M24)
    assert e["verdict"]["verdict"] == stage1.NOT_EXERCISED and e["n_never_required"] == M24


def test_a1_a_link_that_only_some_members_needed_keeps_its_graded_verdict_and_counts_the_rest():
    """g2 surfaces in members 0 to 7 only: 8 members need the link (30 records each), 16 never do. The verdict is graded on all 24; the count is what says that
    two thirds of them passed by default."""
    out = a19.gliders(range(0, 60), range(30, 90), M24)
    out["g2"]["surfaced"][:, 8:] = False
    e = link_summary(a19.RF, out)
    assert e["n_never_required"] == 16 and e["verdict"]["verdict"] != stage1.NOT_EXERCISED
    assert e["need_count_median"] == 30        # round 21 merge: the median over the 8 members that needed it (30 records each), not over all 24 (it was 0)


# ------------------------------------------------------------------------------------------------------------ A1: what the report prints

def card_of(h, lid="usv-uas-rf"):
    return plain(h.split(f"<div id='v-{lid}'>")[1].split("<div id='v-")[0])


def write(run, **fields):
    m, plan = pm_run.make_run(run)
    set_link_fields(run, **{"usv-uas-rf": fields})
    report.write(run, m, plan)
    rep, h = load(run), (run / "report" / "index.html").read_text()
    assert report.check_traceability(rep) == [] and report.check_rendered(rep, h) == []
    return rep, h, rep["links"]["usv-uas-rf"]["granularity"]


def test_a1_the_card_and_report_json_say_in_how_many_members_a_link_was_never_required(run):
    """Before: the card and report.json carried the median need_count only, so a link that the median member needed read as worked in every member."""
    rep, h, g = write(run, need_count_median=30, granularity_ok=True, n_never_required=3)
    n = rep["links"]["usv-uas-rf"]["n"]["value"]
    assert (g["never_required"]["value"], g["members"]["value"], g["never_required"]["unit"]) == (3, n, "members")
    assert f"The link was required at no moment in 3 members, out of {n} members: in each of those it passes by default" in card_of(h)
    assert "counts as a pass in the P(fail) above" in card_of(h)
    row = h[h.index("<a href='#v-usv-uas-rf'>"):].split("</tr>")[0]
    assert "undecided: granularity" not in row                                             # no new badge: the card says what the verdict rests on


def test_a1_a_median_member_that_did_not_need_it_and_some_that_did_print_both_sentences(run):
    rep, h, g = write(run, need_count_median=0, granularity_ok=False, n_never_required=16)
    c = card_of(h)
    assert "Required at no moment in the median member (0 samples)" in c and "required at no moment in 16 members, out of" in c
    assert "undecided: granularity" in h


def test_a1_a_link_never_required_in_any_member_prints_not_exercised_and_the_count_not_go(run):
    m, plan = pm_run.make_run(run)
    _not_exercised(run)
    n = json.loads((run / "stage1b" / "summary.json").read_text())["summary"]["links"]["usv-uas-rf"]["n"]
    set_link_fields(run, **{"usv-uas-rf": dict(n_never_required=n)})
    report.write(run, m, plan)
    rep, h = load(run), (run / "report" / "index.html").read_text()
    c = card_of(h)
    assert rep["links"]["usv-uas-rf"]["verdict"] == stage1.NOT_EXERCISED and "the verdict is NOT EXERCISED, not GO" in c
    assert f"required at no moment in {n} members, out of {n} members" in c
    row = h[h.index("<a href='#v-usv-uas-rf'>"):].split("</tr>")[0]
    assert "NOT EXERCISED" in row and ">GO<" not in row


@pytest.mark.parametrize("fields", [dict(n_never_required=0), dict(n_never_required=None), dict()], ids=["zero", "none", "absent (an older run)"])
def test_a1_no_sentence_and_no_number_when_every_member_needed_the_link_or_the_run_did_not_count(run, fields):
    rep, h, g = write(run, need_count_median=30, granularity_ok=True, **fields)
    assert "required at no moment in" not in card_of(h)
    assert g.get("never_required") is None or g["never_required"]["value"] == 0


# ----------------------------------------------------------------------------------------------------------- A2: ingest-ocean and an older copy

def lab_mission(tmp_path, out):
    m = yaml.safe_load((config.ROOT / "missions" / "ci_fixture.yaml").read_text())
    m["environment"]["ocean"] = dict(source="lab_hycom", path=str(out), temperature_kind="potential")
    (tmp_path / "lab.yaml").write_text(yaml.safe_dump(m))
    return str(tmp_path / "lab.yaml")


def ingest(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(hycom, "ingest_lab_hycom", lambda *a: pathlib.Path(a[2]))
    assert cli.main(["ingest-ocean", "--mission", lab_mission(tmp_path, tmp_path / "lab.zarr"), "--path", "/lab/hycom"]) == 0
    return capsys.readouterr().out


def test_a2_ingest_ocean_names_the_older_copy_that_a_killed_ingest_left_beside_the_store(monkeypatch, tmp_path, capsys):
    """A lab store is not locked, so no write sweeps the `.old.tmp` of a killed earlier ingest: before, the command printed only 'ocean store: ...'."""
    out = tmp_path / "lab.zarr"
    out.mkdir()
    aside = hycom._aside_name(out)
    aside.mkdir()
    text = ingest(monkeypatch, tmp_path, capsys)
    assert f"ocean store: {out}" in text and f"is still beside this one: {aside};" in text
    assert "nothing deletes the leftovers of a lab store" in text and "remove it by hand" in text


def test_a2_ingest_ocean_says_nothing_when_there_is_no_older_copy_or_only_another_stores(monkeypatch, tmp_path, capsys):
    """Round 20, M-8: a `.dead.tmp` of the store itself is named now (tests/test_round20_c.py); another store's leftovers are still not."""
    out = tmp_path / "lab.zarr"
    out.mkdir()
    (tmp_path / "other.zarr").mkdir()
    hycom._aside_name(tmp_path / "other.zarr").mkdir()
    text = ingest(monkeypatch, tmp_path, capsys)
    assert text == f"ocean store: {out}\n"


# ---------------------------------------------------------------------------------- A3: `_seed` against the results the real CFD code made

REAL = pathlib.Path(__file__).parent / "fixtures" / "cfd_real"
KEYS = dict(quad=("external", ("external", "air", 10.0)), torpedo=("external", ("external", "water", 1.5)),
            wigley=("surface", ("surface", 0.1561, [0.99, 1.486, 1.981])))
FILES = dict(quad="quad.external.json", torpedo="torpedo.external.json", wigley="wigley.surface.json")


@pytest.mark.parametrize("sample", list(KEYS))
def test_a3_the_checked_shape_accepts_a_result_that_the_real_cfd_made(sample):
    """The three fixtures are results of real runs, copied from the cache on the worker (`cfd.characterize_external` of the quad at 10 m/s in air and of the
    torpedo at 1.5 m/s in water, `characterize_free_surface` of the Wigley hull, 5,476 s of CFD): `_checked` refused none of the legitimate ones when it was
    tried on all 18 files of that cache, and refused the others for the reason it gives (another speed, another hull)."""
    what, k = KEYS[sample]
    r = json.loads((REAL / FILES[sample]).read_text())
    got = _seed._checked(what, k, r)
    assert got["L"] > 0 and (what == "external" and got["fluid"] == k[1] or what == "surface" and sorted(round(u, 3) for u in got["speeds"]) == k[2])


def test_a3_the_three_real_results_seed_end_to_end_and_a_second_run_finds_them_there(work, capsys):
    for run_name, sample in (("q1", "quad"), ("t1", "torpedo"), ("w1", "wigley")):
        d = work / "runs" / run_name
        d.mkdir(parents=True)
        shutil.copy(REAL / FILES[sample], d / FILES[sample])
    assert _seed.main() == 0
    out = capsys.readouterr().out
    assert out.count("seeded ") == 3 and "NOT seeded" not in out and len(cached_files(work)) == 3
    assert _seed.main() == 0 and capsys.readouterr().out.count("already there") == 3


def test_a3_a_real_result_of_another_case_is_refused_for_the_reason_it_gives():
    """The same real files, under the key of another case: the torpedo's under the quad's, the quad's under the torpedo's, the wigley's under a hull of
    other speeds. A real result in the wrong place is the harm the check is for."""
    tor = json.loads((REAL / FILES["torpedo"]).read_text())
    with pytest.raises(ValueError, match="made for fluid 'water' at speed 1.5, not 'air' at 10.0"):
        _seed._checked("external", KEYS["quad"][1], tor)
    quad = json.loads((REAL / FILES["quad"]).read_text())
    with pytest.raises(ValueError, match="made for fluid 'air' at speed 10.0, not 'water' at 1.5"):
        _seed._checked("external", KEYS["torpedo"][1], quad)
    wig = json.loads((REAL / FILES["wigley"]).read_text())
    with pytest.raises(ValueError, match="are not those of this case"):
        _seed._checked("surface", ("surface", 0.1561, [0.9877, 1.4815, 1.9754]), wig)


# --------------------------------------------------------------------------------------------------------- M-12: RUNBOOK's lock-error symptom

def test_m12_every_error_and_warning_symptom_of_the_runbooks_lock_row_is_text_the_code_prints():
    """The row said `error: the lock file <table>.lock ... cannot be opened`; `emulator.locked` raises "cannot open the emulator table's lock file <path>".
    The fixed words of each backticked symptom of the row (the text between its placeholders) must occur in the code that prints it."""
    code = "".join((config.ROOT / "cafe" / "pm" / f).read_text() for f in ("emulator.py", "env/remote.py"))
    rows = [ln for ln in (config.ROOT / "docs" / "RUNBOOK.md").read_text().splitlines()
            if ln.startswith("| `error:") and "is not locked" in ln.split(" | ")[0]]
    assert len(rows) == 1
    symptoms = [s for s in re.findall(r"`([^`]+)`", rows[0].split(" | ")[0]) if s.startswith(("error: ", "warning: "))]
    assert len(symptoms) == 2
    for s in symptoms:
        for seg in re.split(r"<[^>]*>|\.\.\.", s.split(": ", 1)[1]):
            assert len(seg.strip()) < 10 or seg in code, (s, seg)


def test_an_end_that_is_neither_a_vehicle_nor_the_ship_has_no_antenna_height():
    """A shore station or an unknown id is not one height (the line no test of the merged tree ran). Round 21, M-2: the card does not go silent for it, and
    does not make a height up either: it takes the reference heights `report.RF_REFERENCE_M` and says they are assumed (tests/test_round21_b.py)."""
    from cafe.pm import report
    heights, read, text = report._end_heights("shore", {"vehicles": [], "ship": {"id": "ship"}}, {}, "always")
    assert heights == list(report.RF_REFERENCE_M) and read is False and text.endswith("108.1 m assumed") and "no usable height" in text
