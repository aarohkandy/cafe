"""Scale-ladder branch: the pure parts of review/workorder/usv_rans_probe.py (a measurement script, loaded by path)."""
import importlib.util
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("usv_rans_probe", ROOT / "review/workorder/usv_rans_probe.py")
assert spec is not None and spec.loader is not None
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)

HULL = dict(type="ellipsoid", center=(0.0, 0.0, 0.0), radii=(3.25, 0.6, 0.45))
KEEL = dict(type="plate", center=(0.0, 0.0, -1.5), size=(0.667, 0.1, 2.1))


def test_the_out_directory_must_be_a_usv_rans_directory_of_the_runs_folder():
    probe.check_out(pathlib.Path("/data/runs/usv_rans_a"))
    for bad in ("/data/runs/fin1", "/tmp/usv_rans_a", "/data/runs/x/usv_rans_a", "/data/runs"):
        with pytest.raises(SystemExit):
            probe.check_out(pathlib.Path(bad))


def test_the_double_body_is_the_hull_the_keel_pushed_into_it_and_its_mirror_image():
    h, down, up = probe.double_body_shapes([HULL, KEEL], 0.25)
    assert h == HULL
    assert down["size"][2] == pytest.approx(2.1 + 0.25 * 0.45) and down["center"][2] == pytest.approx(-1.5 + 0.25 * 0.45 / 2)
    assert up["size"] == down["size"] and up["center"][2] == pytest.approx(-down["center"][2])
    assert up["center"][:2] == down["center"][:2]
    assert KEEL["center"][2] == -1.5                                               # the input is not changed
    top = down["center"][2] + down["size"][2] / 2                                  # the keel's top is inside the ellipsoid (z > -0.45)
    assert top > -0.45


def test_the_layer_recipe_is_read_from_the_snappy_text():
    text = "layers { body { nSurfaceLayers 3; } }\n expansionRatio 1.2; finalLayerThickness 0.5; minThickness 0.1;"
    assert probe.layer_recipe(text) == dict(layers=3.0, expansion=1.2, final=0.5)
    with pytest.raises(ValueError):
        probe.layer_recipe("nothing")


def test_expected_yplus_of_the_first_cell():
    e = probe.expected_yplus(0.0254, 0.59, 1.19e-6, 0.0037, 3, 1.2, 0.5)
    assert e["first_layer_m"] == pytest.approx(0.5 * 0.0254 / 1.44)
    assert e["first_centre_m"] == pytest.approx(e["first_layer_m"] / 2)
    assert e["u_tau_ms"] == pytest.approx(0.59 * (0.0037 / 2) ** 0.5)
    assert e["yplus_first_centre"] == pytest.approx(e["first_centre_m"] * e["u_tau_ms"] / 1.19e-6)
    assert e["yplus_no_layers"] == pytest.approx(0.0127 * e["u_tau_ms"] / 1.19e-6)
    assert 30 < e["yplus_first_centre"] < 300


def test_yplus_log_in_both_openfoam_forms_and_without():
    assert probe.parse_yplus("patch body y+ : min = 1.5, max = 250.25, average = 90.1\n") == dict(min=1.5, max=250.25, average=90.1)
    assert probe.parse_yplus("yPlus body: min = 2e-1, max = 3.5e+2, average = 80\n") == dict(min=0.2, max=350.0, average=80.0)
    assert probe.parse_yplus("patch other y+ : min = 1, max = 2, average = 3\n") is None


def test_the_last_layer_table_row_the_last_residuals_and_the_block_means():
    log = "patch faces layers\nbody 100 1.0 0.1 0.2\nother 5 5 5 5\nbody 200 2.5 0.0034 0.0049\n"
    assert probe.layer_lines(log) == ["body 100 1.0 0.1 0.2", "body 200 2.5 0.0034 0.0049"]
    assert probe.layer_lines("nothing") == []
    assert probe.yplus_of("patch body y+ : min = 1, max = 2, average = 3")["max"] == 2.0
    assert "error" in probe.yplus_of("yPlus will not be calculated\n patch body y+ : min = 0, max = 0, average = 0")
    assert "error" in probe.yplus_of("nothing")
    sf = "Solving for Ux, Initial residual = 1e-2, x\nSolving for p, Initial residual = 0.5, x\nSolving for Ux, Initial residual = 3e-4, x\n"
    assert probe.final_residuals(sf) == dict(Ux=3e-4, p=0.5)
    assert probe.block_means(list(range(250)), 100) == [49.5, 149.5, 224.5]
    assert probe.block_means(list(range(120)), 100) == [49.5]                       # a 20-value tail is dropped


def test_the_hulls_result_is_half_the_double_bodys_drag_and_std_with_the_grids_cells_and_checks():
    fine = dict(cells=2000, failed_checks=0, drag_n=20.0, drag_tail_std_n=0.2, gci=0.05, iterations=600, seconds=100.0)
    coarse = dict(cells=500, failed_checks=1, drag_n=19.0, seconds=30.0)
    r = probe.half_result(fine, coarse, 1025.0, 0.59)
    assert r["drag"] == 10.0 and r["drag_coarse"] == 9.5 and r["drag_std"] == 0.1
    assert (r["cells"], r["coarse_cells"], r["failed_checks"], r["coarse_failed_checks"], r["gci"]) == (2000, 500, 0, 1, 0.05)
    assert probe.half_result(dict(fine, drag_tail_std_n=None), coarse, 1025.0, 0.59)["drag_std"] is None


def test_the_apparent_order_of_three_grids_that_follow_f0_plus_c_h_squared():
    n = lambda h: 1e6 / h ** 3                                                     # noqa: E731  cells of a grid of spacing h
    r = probe.apparent_order((11.0, n(1)), (14.0, n(2)), (26.0, n(4)))             # f = 10 + h^2, r = 2
    assert r["p"] == pytest.approx(2.0, abs=1e-6) and r["f_extrapolated"] == pytest.approx(10.0)
    assert r["e_approx_21"] == pytest.approx(3 / 11) and r["gci_fine_21"] == pytest.approx(1.25 * (3 / 11) / 3)
    r = probe.apparent_order((10.0 + 1.0 ** 1.5, n(1)), (10.0 + 1.3 ** 1.5, n(1.3)), (10.0 + 1.9 ** 1.5, n(1.9)))   # p = 1.5, r not constant
    assert r["p"] == pytest.approx(1.5, abs=1e-6) and r["f_extrapolated"] == pytest.approx(10.0)
    with pytest.raises(ValueError):
        probe.apparent_order((10.0, 1e6), (12.0, 1e5), (11.0, 1e4))                # not monotone


def test_the_friction_only_coefficient():
    assert probe.friction_only(0.004, 8.0, 1.0) == pytest.approx(0.032)
