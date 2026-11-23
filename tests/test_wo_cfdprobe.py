"""Work order step 3, skeptic pass: the grid record of review/workorder/rans_probe.py (a measurement script, loaded by path)."""
import importlib.util
import pathlib

import numpy as np
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("rans_probe", ROOT / "review/workorder/rans_probe.py")
assert spec is not None and spec.loader is not None
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def _run(level: int, force: list) -> dict:
    return dict(level=level, seconds=10.0, mesh=dict(cells=1000, failed_checks=0),
                dirs={"x+z0.00": dict(force=np.array(force), force_std=np.array([0.01, 0.0, 0.0]), seconds=4.0, iters=50)})


def test_surface_cell_is_the_one_the_level_gives():
    coarse = probe.grid_entry("coarse", _run(5, [-2.0, 0, 0]), "x+z0.00", 10.0, 1.8, pathlib.Path("c"))
    fine = probe.grid_entry("fine", _run(6, [-2.0, 0, 0]), "x+z0.00", 10.0, 1.8, pathlib.Path("f"))
    assert coarse["surface_cell_m"] == pytest.approx(0.45 / 32)
    assert fine["surface_cell_m"] == pytest.approx(0.45 / 64)
    assert fine["cd"] == pytest.approx(0.2) and fine["scatter"] == pytest.approx(0.005)


def test_a_grid_whose_drag_is_not_positive_is_refused():
    with pytest.raises(ValueError, match="not positive"):
        probe.grid_entry("fine", _run(6, [2.0, 0, 0]), "x+z0.00", 10.0, 1.8, pathlib.Path("f"))


def test_the_drag_bound_and_the_history_of_a_case(tmp_path):
    label = "x+z0.00"                                                   # the flow along +x: drag = -Fx
    run = _run(6, [-2.0, 0.5, 0.3])
    run["dirs"][label]["force_std"] = np.array([0.01, 0.2, 0.3])
    f = tmp_path / "postProcessing/forces/0"
    f.mkdir(parents=True)
    rows = ["# header"] + [f"{i} {-2.0 - (0.1 if i % 2 else 0.0)} 0 0 0 0 0 0 0 0" for i in range(1, 101)]
    (f / "force.dat").write_text("\n".join(rows) + "\n")
    (f / "moment.dat").write_text("\n".join(rows) + "\n")
    g = probe.grid_entry("fine", run, label, 10.0, 1.8, tmp_path)
    assert g["scatter_drag_bound"] == pytest.approx(0.01 / 2.0)               # |d| = (1, 0, 0): only the x std counts
    assert g["scatter"] == pytest.approx(np.linalg.norm([0.01, 0.2, 0.3]) / 2.0)
    assert g["drag_tail_mean_n"] == pytest.approx(2.05) and g["drag_tail_std_n"] == pytest.approx(0.05)
    assert g["tail_iterations"] == 20 and g["history_iterations"] == 100
    assert "drag_tail_mean_n" not in probe.grid_entry("fine", run, label, 10.0, 1.8, tmp_path / "none")


def test_form_factors_and_the_slope_of_the_ladder():
    f = probe.form_factors(0.4, 0.07, 1.4, 2.0e5)                          # ITTC-57: 0.075 / (log10 2e5 - 2)^2 = 0.075 / 3.3010^2
    assert f["cf_ittc57"] == pytest.approx(0.075 / (np.log10(2.0e5) - 2) ** 2) and f["cf_blasius"] == pytest.approx(1.328 / np.sqrt(2.0e5))
    assert f["ff_blasius"] == pytest.approx(0.4 * 0.07 / (1.4 * f["cf_blasius"])) and f["ff_ittc57"] == pytest.approx(0.4 * 0.07 / (1.4 * f["cf_ittc57"]))
    b, se = probe.loglog_slope([1e4, 2e4, 4e4, 8e4], [3 * r ** -0.1 for r in (1e4, 2e4, 4e4, 8e4)])    # an exact power law: slope -0.1, no scatter
    assert b == pytest.approx(-0.1) and se == pytest.approx(0, abs=1e-12)
    b, se = probe.loglog_slope([1, 2, 4, 8], [1, 1.1, 0.9, 1.0])
    assert se > 0
