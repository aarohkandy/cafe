"""Work order step 6: the contribution table (which of CFD, FEA and the emulator contributed, per vehicle and per link)."""
import json
import re

import pytest

from cafe.pm import report
from tests.fixtures import pm_run
from tests.test_report import load, walk


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("CAFE_DATA", str(tmp_path / "data"))
    monkeypatch.setattr(report, "RECEIPTS", tmp_path / "model_receipts.json")


@pytest.fixture
def run(tmp_path):
    d = tmp_path / "run"
    d.mkdir()
    return d


def table(rep):
    return rep["contribution"]["rows"]


def test_contribution_rows(run):
    m, plan = pm_run.make_run(run)
    report.write(run, m, plan)
    rep = load(run)
    got = {i: (r["cfd"], r["fea"], r["emulator"]) for i, r in table(rep).items()}
    assert got["glider_eq"] == (True, False, False)
    assert got["glider_2n"] == (False, False, False)
    assert got["usv"] == (False, False, False)
    assert got["uas"] == (False, False, True)                      # its fix candidates were answered EMULATED
    links = {i: r for i, r in table(rep).items() if r["kind"] == "link"}
    assert set(links) == {lk["id"] for lk in m["links"]} and len(links) == 4
    assert {i for i, r in links.items() if r["cfd"]} == {"glider_eq-ship-acoustic"}
    assert not any(r["fea"] or r["emulator"] for r in links.values())
    assert rep["traceability_problems"] == [] and list(walk(rep["contribution"])) == []


def test_contribution_fea_and_used(run, monkeypatch):
    real = pm_run.stage3_rows

    def rows(vids, wins):
        r = real(vids, wins)
        r["glider_eq"][0]["fea"] = dict(run=True)
        r["usv"][0]["fea"] = dict(run=False, reason="x")
        return r
    monkeypatch.setattr(pm_run, "stage3_rows", rows)
    m, plan = pm_run.make_run(run)
    report.write(run, m, plan)
    rep = load(run)
    assert table(rep)["glider_eq"]["fea"] is True and table(rep)["usv"]["fea"] is False and table(rep)["glider_2n"]["fea"] is False
    assert rep["ledger_problems"] == []


def test_contribution_emulator_used_in_holdout(run):
    m, plan = pm_run.make_run(run, ledgers=False)
    p = run / "emulator" / "holdout.json"
    h = json.loads(p.read_text())
    h["glider_eq"]["used"] = True
    p.write_text(json.dumps(h))
    (run / "emulator" / "flip.json").unlink()                      # no fix candidate answered: the holdout alone decides
    report.write(run, m, plan)
    assert table(load(run))["glider_eq"]["emulator"] is True


def test_contribution_files_missing(run):
    m, plan = pm_run.make_run(run, stage3=False, refit=False, emulator=False)
    report.write(run, m, plan)
    rep = load(run)
    assert all(not (r["cfd"] or r["fea"] or r["emulator"]) for r in table(rep).values()) and len(table(rep)) == 8
    assert rep["contribution"]["statements"] == [report.CONTRIB_UAS]      # no CFD cell is yes: no ellipsoid sentence


def test_contribution_page(run):
    m, plan = pm_run.make_run(run)
    report.write(run, m, plan)
    h = (run / "report" / "index.html").read_text()
    head = "<tr><th>Vehicle or link<th>CFD<th>FEA<th>Emulator</tr>"
    assert h.index("<h2>Verdicts</h2>") < h.index(head) < h.index("id='v-")
    cells = re.findall(r"<tr><td>([\w-]+)<td>(yes|no)<td>(yes|no)<td>(yes|no)</tr>", h.split(head)[1].split("</table>")[0])
    assert [c[0] for c in cells] == list(table(load(run)))
    assert report.CONTRIB_ELLIPSOID in h and report.CONTRIB_UAS in h
    assert report.check_rendered(load(run), h) == []
