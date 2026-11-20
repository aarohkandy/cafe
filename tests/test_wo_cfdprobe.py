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
