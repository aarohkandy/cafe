"""Work order, the lead's fix after the rehearsal run on2: the report prints every number of a refit it stores. on2 was the first real run whose refit fired
(the gliders' CPU RANS rows); its report stage failed its own check `report_html_matches_json` on `stage3.refit.<glider>.drag.change_vs_hangar`
(0.2346, 0.2465): the page printed the multiplier's mean and sigma and not the change. The fixture's own change is a number the page prints elsewhere,
so the gap never showed."""
import pytest

from cafe.pm import report
from tests.fixtures import pm_run
from tests.test_report import load


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("CAFE_DATA", str(tmp_path / "data"))
    monkeypatch.setattr(report, "RECEIPTS", tmp_path / "model_receipts.json")


def test_the_page_prints_the_change_of_a_refit_multiplier(tmp_path, monkeypatch):
    real = pm_run.refit_rows

    def refit(rows):
        r = real(rows)
        r["glider_eq"]["drag"].update(mean=1.2345597267822854, change_vs_hangar=0.23455972678228543)       # on2's glider_eq, a value nothing else prints
        return r
    monkeypatch.setattr(pm_run, "refit_rows", refit)
    run = tmp_path / "run"
    run.mkdir()
    m, plan = pm_run.make_run(run)
    report.write(run, m, plan)
    rep = load(run)
    page = (run / "report" / "index.html").read_text()
    assert report.check_rendered(rep, page) == []
    assert "change vs baseline model" in page and rep["stage3"]["refit"]["glider_eq"]["drag"]["change_vs_hangar"]["value"] == pytest.approx(0.2345597, abs=1e-6)
