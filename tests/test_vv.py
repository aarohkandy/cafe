"""cafe.pm.vv (Celik 2008 GCI, ASME V&V 20 table) and cafe.pm.dtmb5415 (hull loft, runs, receipts, tabulation)."""
import hashlib
import io
import json
import math
import pathlib
import re
import runpy
import shutil
import sys
import zipfile
from types import SimpleNamespace as NS

import numpy as np
import pytest
import trimesh
from hypothesis import given, settings, strategies as st

from cafe import cfd, receipts as rc
from cafe.pm import dtmb5415 as dt
from cafe.pm import vv

# ------------------------------------------------------------------ Celik et al. 2008, Table 1

TABLE1 = [   # (phi1, phi2, phi3, r21, r32) -> p, phi_ext21, ea21, eext21, GCI21 as printed
    ((6.063, 5.972, 5.863, 1.5, 1.333), (1.53, 6.1685, 0.015, 0.017, 0.022), False),
    ((10.7880, 10.7250, 10.6050, 2.0, 2.143), (0.75, 10.8801, 0.006, 0.009, 0.011), False),
    ((6.0042, 5.9624, 6.0909, 2.0, 2.143), (1.51, 6.0269, 0.007, 0.004, 0.005), True),
]


@pytest.mark.parametrize("args, printed, osc", TABLE1)
def test_celik_table1_worked_example(args, printed, osc):
    g = vv.celik_gci(*args)
    p, ext, ea, eext, gci = printed
    assert g.p == pytest.approx(p, abs=0.01)
    assert g.phi_ext21 == pytest.approx(ext, abs=6e-4)
    # printed to 0.1 percentage point (the paper shows e_ext21 = 0.9 % for column 2; the formula gives 0.85 %)
    assert g.ea21 == pytest.approx(ea, abs=1e-3) and g.eext21 == pytest.approx(eext, abs=1e-3) and g.gci_fine21 == pytest.approx(gci, abs=1e-3)
    assert g.oscillatory is osc and g.r_ok and g.converging


def test_celik_fails_when_a_number_is_wrong():
    """A transposed digit in the paper's first column must move the answer outside its printed precision."""
    g = vv.celik_gci(6.063, 5.972, 5.836, 1.5, 1.333)
    assert abs(g.p - 1.53) > 0.05


def test_asymptotic_ratio_for_an_exact_power_law_is_phi1_over_phi2():
    """GCI32 / (r21^p GCI21) = phi1/phi2 exactly for phi = phi0 + c h^p (the two e_a are normalised by different phi)."""
    phi1, phi2, phi3, a, b = power_law(2.0, 0.3, 1.7, [0.1, 0.15, 0.24])
    assert vv.celik_gci(phi1, phi2, phi3, a, b).asymptotic == pytest.approx(phi1 / phi2, rel=1e-9)


def power_law(phi0, c, p, hs):
    """phi on grids with sizes hs (fine first) for phi = phi0 + c h^p, and the two ratios."""
    phis = [phi0 + c * h ** p for h in hs]
    return (*phis, hs[1] / hs[0], hs[2] / hs[1])


def test_constant_ratio_recovers_second_order():
    phi1, phi2, phi3, r21, r32 = power_law(10.0, 1.0, 2.0, [0.1, 0.2, 0.4])
    g = vv.celik_gci(phi1, phi2, phi3, r21, r32)
    assert g.p == pytest.approx(2.0, abs=1e-12) and g.phi_ext21 == pytest.approx(10.0, abs=1e-12)
    assert g.gci_fine21 == pytest.approx(1.25 * abs((phi1 - phi2) / phi1) / 3.0, rel=1e-12)


@settings(max_examples=100, deadline=None)
@given(st.floats(-5, 5), st.floats(0.01, 2), st.floats(0.3, 4), st.floats(1.3, 2.5), st.floats(0.0, 0.6), st.booleans())
def test_property_exact_power_law_is_recovered_with_unequal_ratios(phi0, c, p, r21, grow, neg):
    """For phi = phi0 + c h^p with the coarse ratio r32 >= r21 (the usual way grids are laid out) the fixed-point iteration
    finds p and Richardson extrapolation finds phi0 (the non-constant-r branch of eq 3)."""
    c = -c if neg else c
    h1 = 0.05
    r32 = r21 * (1 + grow)
    phi1, phi2, phi3, a, b = power_law(phi0, c, p, [h1, h1 * r21, h1 * r21 * r32])
    if abs(phi0) < 0.1 or min(abs(phi2 - phi1), abs(phi3 - phi2)) < 1e-6 * max(1.0, abs(phi0)):
        return
    g = vv.celik_gci(phi1, phi2, phi3, a, b)
    assert g.p == pytest.approx(p, rel=1e-6) and g.phi_ext21 == pytest.approx(phi0, abs=1e-6 * max(1, abs(c)))
    assert g.converging and g.gci_fine21 == pytest.approx(1.25 * g.ea21 / (a ** p - 1), rel=1e-6)


def test_eq3_with_and_without_the_absolute_value_differ_only_where_the_solution_diverges():
    """phi = 1 + h at h = 0.05, 0.1, 0.1375 (r21 = 2, r32 = 1.375) has |eps32/eps21| = 0.75 < 1 yet converges (the coarse
    pair is closer in h). Eq 3 as printed, with |ln|.||, would give p = 2.26 here; the true order is 1 and is returned."""
    g = vv.celik_gci(1.05, 1.1, 1.1375, 2.0, 1.375)
    assert g.p == pytest.approx(1.0, abs=1e-9) and g.converging and g.phi_ext21 == pytest.approx(1.0, abs=1e-9)
    assert vv._fixed_point(abs(math.log(0.75)), 1.0, 2.0, 1.375, 1e-12, 500) == pytest.approx(2.2625, abs=1e-3)


def test_divergence_and_range_flags():
    g = vv.celik_gci(1.0, 1.1, 1.15, 1.5, 1.5)          # the fine pair moves 0.1, the coarse pair 0.05: diverging
    assert vv.observed_order(0.1, 0.05, 1.5, 1.5) > 0   # the paper's |.| would still report a positive order
    assert not g.converging and math.isnan(g.gci_fine21) and math.isnan(g.phi_ext21) and math.isnan(g.asymptotic)
    g = vv.celik_gci(1.0, 1.01, 1.03, 1.2, 1.2)
    assert not g.r_ok and g.converging


def test_observed_order_error_paths():
    for bad in [(0.0, 1.0), (1.0, 0.0), (math.nan, 1.0), (1.0, math.inf)]:
        with pytest.raises(ValueError):
            vv.observed_order(*bad, 2.0, 2.0)
    with pytest.raises(RuntimeError, match="converge"):
        vv.observed_order(1.0, 2.0, 0.5, 2.0)             # ratios below 1: not a refinement
    assert vv.observed_order(1.0, 2.5, 1.5, 1.2, max_iter=1) == pytest.approx(vv.observed_order(1.0, 2.5, 1.5, 1.2), abs=1e-9)   # bracketing fallback
    with pytest.raises(RuntimeError, match="converge"):
        vv.observed_order(1.0, 1e-300, 1.5, 1.2)                # the order would be ~1700: out of range for both solvers
    with pytest.raises(ValueError, match="zero solution"):
        vv.celik_gci(0.0, 1.0, 2.0, 1.5, 1.5)
    zero_ext = vv.celik_gci(0.5, 1.0, 2.0, 2.0, 2.0)                 # Richardson value exactly 0: e_ext is undefined, not infinite
    assert zero_ext.phi_ext21 == pytest.approx(0.0, abs=1e-12) and math.isnan(zero_ext.eext21)


def test_grid_size_and_refinement_ratio():
    assert vv.grid_size([8.0] * 4) == 2.0
    assert vv.grid_size([1.0, 27.0], dim=3) == pytest.approx(14 ** (1 / 3))
    assert vv.refinement_ratio(8000, 1000) == pytest.approx(2.0)
    assert vv.refinement_ratio(400, 100, dim=2) == pytest.approx(2.0)
    for bad in ([], [1.0, -1.0]):
        with pytest.raises(ValueError):
            vv.grid_size(bad)
    with pytest.raises(ValueError):
        vv.refinement_ratio(0, 10)


# ------------------------------------------------------------------ tie to cafe.cfd.gci

@settings(max_examples=100, deadline=None)
@given(st.floats(0.5, 50), st.floats(-0.3, 0.3), st.floats(1.3, 3), st.floats(1.0, 3.0), st.floats(1.0, 4.0))
def test_property_two_grid_gci_equals_cfd_gci(fine, rel, ratio, p, fs):
    coarse = fine * (1 + rel)
    assert vv.gci_two_grid(fine, coarse, ratio, p, fs) == pytest.approx(cfd.gci(fine, coarse, ratio, p, fs), rel=1e-12)


def test_cfd_uses_the_cell_count_ratio():
    """Regression (2026-10-29): cafe.cfd passed the default ratio 2 although its free-surface grids differ by one
    horizontal-only box, which understated the GCI ~1.8x. It now uses Celik's (N_f/N_c)^(1/3), the same as vv, and
    flags r < 1.3. Cell counts are this repo's DTMB 5415 meshes."""
    r = cfd.ratio_from_cells(330535, 150967)
    assert r == pytest.approx(vv.refinement_ratio(330535, 150967), rel=1e-12) and 1.2 < r < 1.4
    assert cfd.gci(100.0, 102.0, ratio=r) / cfd.gci(100.0, 102.0) > 1.8


# ------------------------------------------------------------------ V&V 20

def test_vv20_row_arithmetic_and_flags():
    row = vv.vv20_row("x", 4.2, 4.0, 0.1, 0.12, 0.1)
    assert row.E == pytest.approx(0.2) and row.u_val == pytest.approx(math.sqrt(0.01 + 0.0144 + 0.01))
    assert row.ratio == pytest.approx(0.2 / row.u_val) and row.validated is (row.ratio <= 1)
    assert vv.vv20_row("y", 4.5, 4.0, 0.1, 0.1, 0.1).validated is False
    assert vv.vv20_row("z", 3.9, 4.0, 0.1, 0.1, 0.1).E == pytest.approx(-0.1)
    assert vv.vv20_row("zero", 1.0, 1.0, 0, 0, 0).ratio == 0.0 and vv.vv20_row("zero", 1.0, 1.0, 0, 0, 0).validated
    assert vv.vv20_row("inf", 1.1, 1.0, 0, 0, 0).ratio == math.inf
    with pytest.raises(ValueError):
        vv.vv20_row("neg", 1, 1, -0.1, 0, 0)


@given(st.floats(-10, 10), st.floats(-10, 10), st.floats(0, 3), st.floats(0, 3), st.floats(0, 3))
def test_property_vv20_antisymmetric_error_and_dominant_uncertainty(S, D, a, b, c):
    r = vv.vv20_row("p", S, D, a, b, c)
    assert r.E == pytest.approx(-vv.vv20_row("q", D, S, a, b, c).E)
    assert r.u_val >= max(a, b, c) - 1e-12 and r.u_val <= a + b + c + 1e-12


def test_format_table_has_one_line_per_row_plus_header():
    rows = [vv.vv20_row("a", 1.0, 1.1, 0.01, 0.01, 0.01), vv.vv20_row("b", 2.0, 1.0, 0.01, 0.01, 0.01)]
    out = vv.format_table(rows).splitlines()
    assert len(out) == 3 and out[0].split()[0] == "case" and out[1].split()[-1] == "no" and out[2].split()[-1] == "no"
    assert vv.format_table([vv.vv20_row("c", 1.0, 1.0, 0.1, 0.1, 0.1)]).splitlines()[1].split()[-1] == "yes"


# ------------------------------------------------------------------ DTMB 5415: IGES, loft, hydrostatics

W, H, STEM = 0.2, 0.4, 0.3


def patch(cols, knots_u):
    """Degree-1 patch from a control net given as columns (u direction) of 3 section points (keel, chine, sheer)."""
    c = np.array(cols, float)                         # (n1, n2, 3)
    return (1, 1), (np.array(knots_u, float), np.array([0, 0, 0.5, 1, 1.0])), np.ones((3, len(cols))), c.transpose(1, 0, 2), (0, 1, 0, 1)


def section_pts(x):
    return [(x, 0, 0), (x, W, 0), (x, W, H)]


def toy_patches():
    body = patch([section_pts(1.0), section_pts(4.0)], [0, 0, 1, 1])                       # x 1 -> 4, rectangular sections
    stem = [(0.3, 0, -0.05), (0.2, 0, 0.0), (0.0, 0, H)]                                    # stem profile in the centre plane
    bow = patch([section_pts(1.5), stem], [0, 0, 1, 1])
    return [bow, body]


def write_iges(path, patches):
    d, p, ent = [], [], 0
    for deg, (ku, kv), wt, c, span in patches:
        n2, n1 = wt.shape
        nums = [128, n1 - 1, n2 - 1, deg[0], deg[1], 0, 0, 1, 0, 0, *ku, *kv, *wt.ravel(), *c.reshape(-1), *span]
        rec = ",".join(f"{x:.9g}" if isinstance(x, float) or hasattr(x, "dtype") else str(x) for x in nums) + ";"
        chunks = [rec[i:i + 64].ljust(64) for i in range(0, len(rec), 64)]
        start = len(p) + 1
        p += [f"{ch}{2 * ent + 1:8d}P{start + k:7d}" for k, ch in enumerate(chunks)]
        d.append(f"{128:8d}{start:8d}{0:8d}{0:8d}{0:8d}{0:8d}{0:8d}{0:8d}{0:8d}D{2 * ent + 1:7d}")
        d.append(f"{128:8d}{0:8d}{0:8d}{len(chunks):8d}{0:8d}{'':8s}{'':8s}{'':8s}{0:8d}D{2 * ent + 2:7d}")
        ent += 1
    d += [f"{406:8d}{0:8d}{0:8d}{0:8d}{0:8d}{0:8d}{0:8d}{0:8d}{0:8d}D{2 * ent + 1:7d}",       # a property entity: ignored
          f"{406:8d}{0:8d}{0:8d}{0:8d}{0:8d}{'':8s}{'':8s}{'':8s}{0:8d}D{2 * ent + 2:7d}"]
    path.write_text("\n".join(["toy".ljust(72) + "S      1", "toy".ljust(72) + "G      1", *d, *p, "T".ljust(72) + "T      1"]) + "\n")


@pytest.fixture()
def toy_igs(tmp_path):
    f = tmp_path / "toy.igs"
    write_iges(f, toy_patches())
    return f


def test_read_iges_round_trips_the_control_net(toy_igs):
    got = dt.read_iges(toy_igs)
    assert len(got) == 2
    for g, ref in zip(got, toy_patches(), strict=True):
        assert g.deg == ref[0] and np.allclose(g.C, ref[3]) and np.allclose(g.W, ref[2]) and g.span == (0, 1, 0, 1)
        assert np.allclose(g.knots[0], ref[1][0]) and np.allclose(g.knots[1], ref[1][1])


def test_read_iges_without_surfaces_raises(tmp_path):
    f = tmp_path / "empty.igs"
    f.write_text("nothing here\n")
    with pytest.raises(ValueError, match="entity 128"):
        dt.read_iges(f)


def test_eval_patch_is_exact_for_a_bilinear_net_and_honours_weights(toy_igs):
    body = dt.read_iges(toy_igs)[1]
    g = dt.eval_patch(body, 7, 5)
    assert np.allclose(g[0, 0], [1.0, 0, 0]) and np.allclose(g[-1, -1], [4.0, W, H]) and np.allclose(g[3, 2], [2.5, W, 0.0])
    w2 = body.W.copy()
    w2[1, :] = 3.0                                    # pulls the chine row's influence: rational, no longer the polyline midpoint
    assert not np.allclose(dt.eval_patch(body._replace(W=w2), 3, 5)[1, 1], dt.eval_patch(body, 3, 5)[1, 1])


@pytest.fixture(scope="module")
def toy_mesh(tmp_path_factory):
    f = tmp_path_factory.mktemp("toy") / "toy.igs"
    write_iges(f, toy_patches())
    return dt.build_hull(dt.read_iges(f), n_stations=120, n_girth=24, res=(40, 60))


def test_loft_has_outward_normals_whichever_side_of_the_centre_plane_the_file_puts_the_hull(tmp_path):
    f = tmp_path / "mirror.igs"
    write_iges(f, [(d, k, w, c * [1, -1, 1], sp) for d, k, w, c, sp in toy_patches()])
    m = dt.build_hull(dt.read_iges(f), n_stations=60, n_girth=12, res=(20, 30))
    assert m.is_watertight and m.volume > 0


def test_loft_is_closed_and_has_the_prismatic_body(toy_mesh):
    m = toy_mesh
    assert m.is_watertight and m.is_winding_consistent and m.volume > 0
    lo, hi = m.bounds
    assert hi[0] == pytest.approx(0.0, abs=1e-9) and lo[0] == pytest.approx(-4.0, abs=1e-9)      # bow +x: stem head at 0, transom at -4
    xs = -m.vertices[:, 0]                                       # back in file coordinates
    body = m.vertices[(xs > 2.0) & (xs < 3.5)]
    on_wall = np.isclose(np.abs(body[:, 1]), W, atol=1e-6)
    on_keel = np.isclose(body[:, 2], 0.0, atol=1e-6)
    on_deck = np.isclose(body[:, 2], H, atol=1e-6)
    assert (on_wall | on_keel | on_deck).all() and np.abs(body[:, 1]).max() == pytest.approx(W)
    assert m.extents[1] == pytest.approx(2 * W) and m.bounds[0][2] == pytest.approx(-0.05, abs=0.01) and m.bounds[1][2] == pytest.approx(H)


def test_hydrostatics_agrees_with_an_independent_capped_volume(toy_mesh):
    h = dt.hydrostatics(toy_mesh, 0.2)
    cut = trimesh.intersections.slice_mesh_plane(toy_mesh, [0, 0, -1], [0, 0, 0.2], cap=True)
    assert h["displacement"] == pytest.approx(cut.volume, rel=1e-6)
    # prismatic body alone is 2 W T (4 - 1.5); bow wedge and nothing else adds to it
    assert 2 * W * 0.2 * 2.5 < h["displacement"] < 2 * W * 0.2 * 3.9
    assert h["bwl"] == pytest.approx(2 * W, rel=1e-6) and h["lwl"] == pytest.approx(4.0 - 0.1, abs=0.05)
    assert h["wetted_area"] > 2 * W * 2.5 + 2 * 0.2 * 2.5


def test_hydrostatics_needs_a_waterline_that_cuts_the_hull(toy_mesh):
    with pytest.raises(ValueError, match="does not cut"):
        dt.hydrostatics(toy_mesh, 5.0)


def test_loft_input_checks(toy_igs):
    patches = dt.read_iges(toy_igs)
    with pytest.raises(ValueError, match="bow patch"):
        dt.build_hull(patches[:1])
    with pytest.raises(ValueError, match="layout"):
        dt.build_hull(patches[::-1], res=(10, 10))


def test_loft_that_cannot_close_is_rejected(toy_igs, monkeypatch):
    monkeypatch.setattr(trimesh.Trimesh, "is_watertight", property(lambda self: False))
    with pytest.raises(ValueError, match="closed"):
        dt.build_hull(dt.read_iges(toy_igs), n_stations=30, n_girth=10, res=(20, 20))


def test_resample_and_section_degenerate_cases():
    fb = np.array([1.0, 2.0, 3.0])
    assert np.allclose(dt._resample(np.zeros((0, 3)), 4, fb), np.tile(fb, (4, 1)))
    assert np.allclose(dt._resample(np.array([[5.0, 6.0, 7.0]]), 3, fb), np.tile([5.0, 6.0, 7.0], (3, 1)))
    line = dt._resample(np.array([[0.0, 0, 0], [2.0, 0, 0], [2.0, 2.0, 0]]), 5, fb)
    assert np.allclose(line[:, 0], [0, 1, 2, 2, 2]) and np.allclose(line[:, 1], [0, 0, 0, 1, 2])
    grid = np.zeros((3, 2, 3))
    grid[..., 0] = [[0, 0], [1, 1], [2, 2]]
    assert dt._section(grid, 5.0).shape == (0, 3) and np.allclose(dt._section(grid, 0.5)[:, 0], 0.5)


# ------------------------------------------------------------------ DTMB 5415: download check

def make_zip(igs_bytes):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(dt.MEMBER, igs_bytes)
    return buf.getvalue()


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def sha(b):
    return hashlib.sha256(b).hexdigest()


def test_fetch_igs_checks_both_hashes_and_caches(tmp_path):
    igs = b"toy iges bytes"
    blob = make_zip(igs)
    calls = []
    opener = lambda url: calls.append(url) or Resp(blob)
    dest = tmp_path / "sub" / dt.MEMBER
    assert dt.fetch_igs(dest, "u", sha(blob), sha(igs), opener).read_bytes() == igs
    assert dt.fetch_igs(dest, "u", sha(blob), sha(igs), lambda url: 1 / 0) == dest          # cached: never opens
    assert len(calls) == 1
    with pytest.raises(ValueError, match="zip sha256"):
        dt.fetch_igs(tmp_path / "a.igs", "u", "0" * 64, sha(igs), opener)
    with pytest.raises(ValueError, match="sha256 differs"):
        dt.fetch_igs(tmp_path / "b.igs", "u", sha(blob), "0" * 64, opener)
    assert not (tmp_path / "b.igs").exists()


def test_recorded_hashes_and_url_are_well_formed():
    assert len(dt.SHA_ZIP) == len(dt.SHA_IGS) == 64 and dt.URL.startswith("http://www.simman2008.dk/")
    assert dt.froude_speeds()[0.28] == pytest.approx(0.28 * math.sqrt(9.81 * 5.719))


# ------------------------------------------------------------------ DTMB 5415: assumptions, disk guard, runs

REAL_ASSUMED = dt.assumed


@pytest.fixture(autouse=True)
def default_assumptions(monkeypatch):
    """The tests state their expected numbers from ASSUMED, not from whatever config/assumptions.yaml says today."""
    monkeypatch.setattr(dt, "assumed", lambda name, config=None: dt.ASSUMED[name][0])


@pytest.fixture(autouse=True)
def roomy_disk(monkeypatch):
    """The fake cases write kilobytes: the disk guard sees 100 GB free, not whatever the test machine has left (the guard's own tests override it)."""
    monkeypatch.setattr(dt.shutil, "disk_usage", lambda p: NS(free=100e9))


def test_assumed_reads_config_overrides(tmp_path):
    assert REAL_ASSUMED("u_D_rel", tmp_path / "missing.yaml") == dt.ASSUMED["u_D_rel"][0]
    f = tmp_path / "a.yaml"
    f.write_text("dtmb5415.u_D_rel: {value: 0.02, unit: '', why: x, replace: y}\ndtmb5415.u_S_rel: 0.005\nother: 1\n")
    assert REAL_ASSUMED("u_D_rel", f) == 0.02 and REAL_ASSUMED("u_S_rel", f) == 0.005 and REAL_ASSUMED("u_nu_rel", f) == dt.ASSUMED["u_nu_rel"][0]
    f.write_text("")
    assert REAL_ASSUMED("u_D_rel", f) == dt.ASSUMED["u_D_rel"][0]


def test_disk_guard_and_tree_size(tmp_path):
    assert dt.check_disk(tmp_path / "new", 0.0) > 0
    with pytest.raises(OSError, match="GB free"):
        dt.check_disk(tmp_path, 1e9)
    (tmp_path / "x").write_bytes(b"0" * 1000)
    assert dt.tree_gb(tmp_path) == pytest.approx(1e-6, rel=0.5)


# ------------------------------------------------------------------ wall treatment, layers, convergence

def test_first_layer_puts_the_first_cell_centre_at_the_requested_y_plus():
    for fr in dt.CT_REF:
        u = dt.froude_speeds()[fr]
        re = u * dt.LPP / dt.TANK["nu"]
        u_tau = u * math.sqrt(0.075 / (math.log10(re) - 2) ** 2 / 2)                      # ITTC-57 written out
        assert dt.first_layer(u) == pytest.approx(2 * 100 * dt.TANK["nu"] / u_tau, rel=1e-12)
        assert dt.first_layer(u, 30.0) == pytest.approx(0.3 * dt.first_layer(u), rel=1e-12)
    slow, fast = (dt.first_layer(dt.froude_speeds()[fr]) for fr in (0.10, 0.41))
    assert 6e-3 < slow < 7e-3 and 1.6e-3 < fast < 2e-3                                     # mm-scale layers, 3.5x thinner at Fr 0.41
    assert 30 < dt.Y_PLUS_AIM < 300 and dt.Y_PLUS_BAND == (30.0, 300.0) and math.sqrt(30 * 300) == pytest.approx(dt.Y_PLUS_AIM, rel=0.07)


def test_layer_count_makes_the_stack_about_as_thick_as_the_hull_cell_and_is_bounded():
    for first, cell, g in ((1.77e-3, 0.0179, 2.0), (6.4e-3, 0.0179, 2.0), (1.77e-3, 0.0236, 2.0), (2e-3, 0.02, 1.5), (3e-3, 0.036, 1.3)):
        n = dt.layer_count(first, cell, g)
        total = first * (g ** n - 1) / (g - 1)
        assert (cell - first) / g < total <= cell * (1 + 1e-12), (first, cell, g, n, total)        # the next layer would not fit
    assert [dt.layer_count(dt.first_layer(dt.froude_speeds()[fr]), 0.0179) for fr in (0.10, 0.41)] == [1, 3]
    assert dt.layer_count(6e-3, 0.001) == 1 and dt.layer_count(1e-5, 1.0) == dt.MAX_LAYERS
    assert dt.hull_cell(5.72, 1.0, 2) == pytest.approx(5.72 * cfd.FS_H0 / 2 ** (len(cfd.FS_BOXES) + 2))
    assert dt.hull_cell(5.72, 1.32) == pytest.approx(dt.hull_cell(5.72, 1.0) / 1.32)


def test_settle_measures_drift_and_scatter_of_the_last_quarter():
    m, s, d, sc = dt.settle(np.full(400, 5.0))
    assert (m, s, d, sc) == (5.0, 0.0, 0.0, 0.0)
    step = np.r_[np.full(200, 4.0), np.full(100, 4.0), np.full(100, 5.0)]
    m, s, d, sc = dt.settle(step)
    assert (m, s) == (5.0, 0.0) and d == pytest.approx(0.2) and sc == 0.0                    # (5 - 4) / 5
    wave = 100.0 + 3.0 * np.tile([1.0, -1.0], 200)
    m, s, d, sc = dt.settle(wave)
    assert m == pytest.approx(100.0) and s == pytest.approx(3.0) and d == pytest.approx(0, abs=1e-12) and sc == pytest.approx(0.03)


def test_set_replaces_exactly_one_entry():
    assert dt._set("a 1;\nendTime 5;\n", "endTime", 9) == "a 1;\nendTime 9;\n"
    for text in ("a 1;\n", "endTime 1;\nendTime 2;\n"):
        with pytest.raises(ValueError, match="expected one"):
            dt._set(text, "endTime", 3)


def test_last_numbers_and_layer_cover_read_what_openfoam_writes(tmp_path):
    assert dt._last_numbers(tmp_path, "yPlus/*/yPlus.dat") == []
    for t, line in (("0", "250 hull 1.0 20.0 3.0"), ("250", "500 hull 2.0 700.0 105.5")):
        d = tmp_path / "postProcessing/yPlus" / t
        d.mkdir(parents=True)
        (d / "yPlus.dat").write_text(f"# y+\n# Time patch min max average\n{line}\n")
    assert dt._last_numbers(tmp_path, "yPlus/*/yPlus.dat") == [500.0, 2.0, 700.0, 105.5]       # newest time, numeric sort, patch name dropped
    empty = tmp_path / "postProcessing/none/0"
    empty.mkdir(parents=True)
    (empty / "x.dat").write_text("# only a header\n")
    assert dt._last_numbers(tmp_path, "none/*/x.dat") == []
    log = tmp_path / "log.snappyHexMesh"
    log.write_text("hull 3582    2      0.00218   0.00465\n\npatch faces layers avg thickness[m]\n"
                   "hull 3582     2        0.08     0.000325   3.33  \nhull 3582 2 1.41 0.00327 67.2\n")
    assert dt._layer_cover(tmp_path) == 67.2                                  # the 6-column final table, last row; the 5-column ones are not it
    log.write_text("no table\n")
    assert dt._layer_cover(tmp_path) is None


class Foam:
    """Stands in for cafe.cfd.sh: snappyHexMesh logs a layer table; interFoam writes force, moment and y+ files for the iterations its
    controlDict asks for (a restart continues after the last one), the x force at iteration i being series(i)."""

    def __init__(self, series=lambda i: -100.0, y_plus=105.0, cover=88.0):
        self.series, self.y_plus, self.cover = series, y_plus, cover
        self.calls, self.snappy, self.controls, self.at = [], "", [], 0

    def __call__(self, case, cmd, log):
        case = pathlib.Path(case)
        self.calls.append(log)
        if log == "snappyHexMesh":
            self.snappy = (case / "system/snappyHexMeshDict").read_text()
            (case / "log.snappyHexMesh").write_text(f"hull 3582 2 1.41 0.003 {self.cover}\n")
        if log.startswith("interFoam"):
            ctl = (case / "system/controlDict").read_text()
            self.controls.append(ctl)
            self.fv = (case / "system/fvSolution").read_text()
            start, end = (0 if "startFrom startTime;" in ctl else self.at), int(re.search(r"^endTime (\d+);", ctl, re.M)[1])
            d = case / "postProcessing/forces" / str(start)
            d.mkdir(parents=True)
            for kind in ("force", "moment"):
                rows = "".join(f"{i} ({self.series(i)} 0 0) ({0.7 * self.series(i)} 0 0) ({0.3 * self.series(i)} 0 0)\n" for i in range(start + 1, end + 1))
                (d / f"{kind}.dat").write_text("# header\n" + rows)
            if self.y_plus is not None:
                for fo, name, row in (("yPlusWet", "surfaceFieldValue", f"{end} {self.y_plus}"), ("yPlus", "yPlus", f"{end} hull 2.0 700.0 {self.y_plus}")):
                    (case / "postProcessing" / fo / str(start)).mkdir(parents=True)
                    (case / "postProcessing" / fo / str(start) / f"{name}.dat").write_text(f"# header\n{row}\n")
            self.at = end


FV_SOLUTION = "PIMPLE\n{\n    momentumPredictor no;\n    maxCo 10; maxAlphaCo 5; rDeltaTSmoothingCoeff 0.05; rDeltaTDampingCoeff 0.5;\n}\n"
ADD_LAYERS = "addLayersControls\n{\n    relativeSizes true;\n    layers { hull { nSurfaceLayers 2; } }\n    nLayerIter 50;\n}\nmeshQualityControls\n{\n}\n"


def fake_free_surface(foam, fail_levels=(), cells=100_000, calls=None, fail_log="... uses more than 8 points ..."):
    """cafe.cfd.free_surface with the OpenFOAM calls replaced by `foam`: writes the two dictionaries the recipe edits, then makes the calls
    in the real order."""
    def solve(stl, draft, case, speeds, off, iters, log, surf_level):
        case = pathlib.Path(case)
        if calls is not None:
            calls.append((off, surf_level, cfd.FS_H0, cfd.FS_NZ, cfd.FLUIDS["water"]["nu"]))
        (case / "system").mkdir(parents=True, exist_ok=True)
        (case / "system/snappyHexMeshDict").write_text("castellatedMesh true;\n" + ADD_LAYERS)
        (case / "system/fvSolution").write_text(FV_SOLUTION)
        if surf_level in fail_levels:
            (case / "log.snappyHexMesh").write_text(fail_log)
            raise RuntimeError("snappy failed")
        cfd.sh(case, "blockMesh", "blockMesh")
        cfd.sh(case, "snappyHexMesh", "snappyHexMesh")
        res = {}
        for u in speeds:
            (case / "system/controlDict").write_text(cfd._control("interFoam", iters, cfd._forces_fo("", (0, 0, 0), "hull")))
            shutil.rmtree(case / "postProcessing", ignore_errors=True)
            cfd.sh(case, "interFoam", f"interFoam.{u}")
            res[u] = dict(resistance=7.0, resistance_std=0.5, iters=foam.at, seconds=1.0)
        return dict(mesh=dict(cells=cells, failed_checks=0), L=5.72, half=True, speeds=res)
    return solve


@pytest.fixture()
def foam(monkeypatch):
    f = Foam()
    monkeypatch.setattr(cfd, "sh", f)
    return f


def test_the_recipe_replaces_the_layers_scales_the_mesh_and_restores_everything(foam, tmp_path):
    before = (cfd.FS_H0, cfd.FS_NZ, dict(cfd.FLUIDS["water"]), cfd.sh)
    calls = []
    with dt.case_recipe(2.5e-3, 7, 1.32):
        fake_free_surface(foam, calls=calls)("h.stl", 0.248, tmp_path, [1.5], 0, 3000, print, 2)
        assert cfd.FLUIDS["water"]["nu"] == dt.TANK["nu"]
    assert calls[0][2] == pytest.approx(cfd.FS_H0 / 1.32, rel=1e-6) and calls[0][3] == tuple(round(n * 1.32) for n in cfd.FS_NZ)
    assert (cfd.FS_H0, cfd.FS_NZ, dict(cfd.FLUIDS["water"]), cfd.sh) == before
    assert "nSurfaceLayers 7;" in foam.snappy and "firstLayerThickness 0.0025;" in foam.snappy and "relativeSizes false;" in foam.snappy
    assert f"expansionRatio {dt.GROWTH};" in foam.snappy and "nSurfaceLayers 2;" not in foam.snappy and foam.snappy.count("addLayersControls") == 1
    assert "meshQualityControls" in foam.snappy                                      # only the layer block was replaced
    with pytest.raises(ValueError, match="no `maxCo"):
        with dt.case_recipe(2.5e-3, 7, 1.0):
            (tmp_path / "system/fvSolution").write_text("PIMPLE { maxCo 10; }\n")
            cfd.sh(tmp_path, "interFoam", "interFoam.1")
    assert cfd.sh is foam
    with pytest.raises(ValueError, match="no addLayersControls"):
        with dt.case_recipe(2.5e-3, 7, 1.0):
            (tmp_path / "system/snappyHexMeshDict").write_text("nothing here\n")
            cfd.sh(tmp_path, "snappyHexMesh", "snappyHexMesh")
    assert (cfd.FS_H0, cfd.FS_NZ, cfd.sh) == before[:2] + (before[3],)                # restored after the failure too


def test_interfoam_runs_in_chunks_until_the_history_settles(foam, tmp_path):
    with dt.case_recipe(2.5e-3, 7, 1.0) as seen:
        fake_free_surface(foam)("h.stl", 0.248, tmp_path, [1.5], 0, 3000, print, 2)
    assert foam.calls == ["blockMesh", "snappyHexMesh"] + [f"interFoam.{u}.{n}" for u in ("1.5",) for n in (250, 500, 750, 1000)]
    assert [re.search(r"^endTime (\d+);", c, re.M)[1] for c in foam.controls] == ["250", "500", "750", "1000"]
    assert ["startFrom startTime;" in c for c in foam.controls] == [True, False, False, False] and all("startFrom latestTime;" in c for c in foam.controls[1:])
    assert all("writeInterval 250;" in c and "yPlusWet" in c and c.count("yPlus {") == 1 for c in foam.controls)
    assert "maxCo 3.0; maxAlphaCo 1.5; rDeltaTSmoothingCoeff 0.05" in foam.fv and "maxCo 10" not in foam.fv
    assert sorted(d.name for d in (tmp_path / "postProcessing/forces").iterdir()) == ["00000000", "00000250", "00000500", "00000750"]
    assert seen["converged"] and seen["iters"] == 1000 and seen["mean"] == 100.0 and seen["std"] == 0.0 and seen["drift"] == 0.0
    assert seen["y_plus"] == 105.0 and (seen["y_plus_min"], seen["y_plus_max"]) == (2.0, 700.0) and seen["layer_cover"] == 88.0


def test_a_settling_history_stops_after_the_first_chunk_that_passes_not_before_min_iters(monkeypatch, tmp_path):
    f = Foam(series=lambda i: -(100.0 + 80.0 * math.exp(-i / 200.0)))
    monkeypatch.setattr(cfd, "sh", f)
    with dt.case_recipe(2.5e-3, 7, 1.0) as seen:
        fake_free_surface(f)("h.stl", 0.248, tmp_path, [1.5], 0, 3000, print, 2)
    assert seen["converged"] and dt.MIN_ITERS < seen["iters"] < dt.MAX_ITERS and seen["drift"] <= dt.DRIFT_TOL and seen["iters"] % dt.CHUNK == 0
    assert dt.settle(-np.array([f.series(i) for i in range(1, seen["iters"] - dt.CHUNK + 1)]))[2] > dt.DRIFT_TOL      # the chunk before it had not passed
    steady = Foam(series=lambda i: -100.0)
    monkeypatch.setattr(cfd, "sh", steady)
    with dt.case_recipe(2.5e-3, 7, 1.0, 600) as short:
        fake_free_surface(steady)("h.stl", 0.248, tmp_path / "b", [1.5], 0, 3000, print, 2)
    assert short["iters"] == 750 and not short["converged"]          # max_iters 600 ends after the chunk that reaches it; below MIN_ITERS: unjudged


def test_a_history_that_never_settles_is_recorded_as_unconverged_at_max_iters(monkeypatch, tmp_path):
    for series in (lambda i: -(100.0 + 0.05 * i), lambda i: -(100.0 + 10.0 * math.sin(i / 3.0))):         # still drifting; oscillating at 7 %
        f = Foam(series=series)
        monkeypatch.setattr(cfd, "sh", f)
        with dt.case_recipe(2.5e-3, 7, 1.0, 1500) as seen:
            fake_free_surface(f)("h.stl", 0.248, tmp_path / str(id(series)), [1.5], 0, 3000, print, 2)
        assert seen["iters"] == 1500 and seen["converged"] is False and (seen["drift"] > dt.DRIFT_TOL or seen["scatter"] > dt.SCATTER_TOL)


def test_a_running_case_stops_before_the_box_runs_out_of_disk(monkeypatch, tmp_path):
    f = Foam(series=lambda i: -(100.0 + 0.05 * i))
    monkeypatch.setattr(cfd, "sh", f)
    monkeypatch.setattr(dt.shutil, "disk_usage", lambda p: NS(free=2e9))
    with pytest.raises(OSError, match="GB free"):
        with dt.case_recipe(2.5e-3, 7, 1.0):
            fake_free_surface(f)("h.stl", 0.248, tmp_path, [1.5], 0, 3000, print, 2)
    assert f.calls == ["blockMesh", "snappyHexMesh", "interFoam.1.5.250"]


def fake_solver(**kw):
    return fake_free_surface(kw.pop("foam", None) or Foam(**kw.pop("foam_kw", {})), **kw)


def prepared(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "hull.stl").write_text("solid x\nendsolid x\n")
    (tmp_path / "hydro.json").write_text(json.dumps(dict(displacement=0.5532, wetted_area=4.9, lwl=5.7188, bwl=0.7690, draft=0.248)))
    return tmp_path


def test_run_grid_records_the_case_and_cleans_up(foam, tmp_path):
    root = prepared(tmp_path)
    (root / "coarse" / "processor0").mkdir(parents=True)
    calls, logs = [], []
    out = dt.run_grid(root, "coarse", 1000, logs.append, fake_solver(foam=foam, calls=calls), frs=(0.28, 0.10))
    assert dt.GRIDS["coarse"] < dt.GRIDS["medium"] == 1.0 < dt.GRIDS["fine"]
    assert list(out["speeds"]) == ["0.28", "0.10"] and out["recipe"] == dt.RECIPE and out["tree_gb"] < 1e-3
    assert all(c[:2] == (0, 2) for c in calls) and calls[0][2] == pytest.approx(cfd.FS_H0 / dt.GRIDS["coarse"], rel=1e-6)
    c = out["speeds"]["0.28"]
    u = dt.froude_speeds()[0.28]
    assert c["R"] == 200.0 and c["R_std"] == 0.0 and c["ct"] == pytest.approx(200.0 / (0.5 * dt.TANK["rho"] * u ** 2 * 4.9))        # half domain: x2
    assert c["first_layer"] == dt.first_layer(u) and c["layers"] > 1
    assert c["layers"] == dt.layer_count(c["first_layer"], dt.hull_cell(5.7188, dt.GRIDS["coarse"]))
    assert (c["y_plus"], c["layer_cover"], c["drift"], c["scatter"], c["converged"], c["iters"]) == (105.0, 88.0, 0.0, 0.0, True, 1000)
    assert c["ct_viscous"] == pytest.approx(0.3 * c["ct"])                                 # the fake puts 30 % of the force in the viscous column
    assert c["cells"] == 100_000 and c["surf_level"] == 2 and c["failed_checks"] == 0 and c["seconds"] == 1.0
    assert out["speeds"]["0.10"]["first_layer"] > c["first_layer"] and any("layers from" in m for m in logs) and any("y+ 105" in m for m in logs)
    assert json.loads((root / "run_coarse.json").read_text())["speeds"]["0.10"]["ct"] > 0 and not (root / "coarse" / "processor0").exists()
    assert cfd.FLUIDS["water"]["nu"] == 1.19e-6                      # tank water was only in force during the run


def test_a_solver_that_never_calls_openfoam_leaves_the_diagnostics_empty(tmp_path):
    def bare(stl, draft, case, speeds, off, iters, log, surf_level):
        one = dict(resistance=3.0, resistance_std=0.2, iters=iters, seconds=2.0)
        return dict(mesh=dict(cells=5, failed_checks=1), half=False, speeds={u: one for u in speeds})
    c = dt.run_grid(prepared(tmp_path), "fine", 10, print, bare, frs=(0.41,))["speeds"]["0.41"]
    assert c["R"] == 3.0 and c["R_std"] == 0.2 and c["iters"] == 10 and c["failed_checks"] == 1
    assert (c["y_plus"], c["y_plus_min"], c["drift"], c["scatter"], c["converged"], c["layer_cover"], c["ct_viscous"]) == (None,) * 7


def test_run_grid_resumes_after_a_crash_and_refuses_files_of_another_recipe(foam, tmp_path):
    root = prepared(tmp_path)
    n = []

    def dies_on_third(*a, **k):
        n.append(1)
        if len(n) == 3:
            raise RuntimeError("OOM")
        return fake_solver(foam=foam)(*a, **k)
    with pytest.raises(RuntimeError, match="OOM"):
        dt.run_grid(root, "fine", 1000, print, dies_on_third)
    assert list(json.loads((root / "run_fine.json").read_text())["speeds"]) == ["0.20", "0.10"]      # finished speeds are on disk
    calls = []
    out = dt.run_grid(root, "fine", 1000, print, fake_solver(foam=foam, calls=calls))
    assert len(calls) == 2 and len(out["speeds"]) == 4                                                # only the two missing speeds ran
    f = root / "run_fine.json"
    f.write_text(json.dumps(dict(grid="fine", S=4.9, iters=2000, speeds={"0.20": {}})))               # the first study's file has no recipe
    with pytest.raises(ValueError, match="made by recipe None"):
        dt.run_grid(root, "fine", 1000, print, fake_solver(foam=foam))


def test_run_grid_steps_down_a_surface_level_and_reraises_other_errors(foam, tmp_path):
    root = prepared(tmp_path)
    calls, logs = [], []
    out = dt.run_grid(root, "fine", 1000, logs.append, fake_solver(foam=foam, calls=calls, fail_levels=(2,)), frs=(0.1, 0.28))
    assert [c[1] for c in calls] == [2, 1, 1] and {c["surf_level"] for c in out["speeds"].values()} == {1} and any("surface level 1" in m for m in logs)
    with pytest.raises(RuntimeError):
        dt.run_grid(root, "coarse", 1000, logs.append, fake_solver(foam=foam, fail_levels=(2,), fail_log="some other failure"))
    again, calls = prepared(tmp_path / "again"), []
    with pytest.raises(RuntimeError):                                     # fails at level 0 as well: no third try
        dt.run_grid(again, "coarse", 1000, logs.append, fake_solver(foam=foam, calls=calls, fail_levels=(0, 1, 2)))
    assert [c[1] for c in calls] == [2, 1, 0]


def test_run_grid_refuses_to_start_on_a_full_disk(tmp_path, monkeypatch):
    monkeypatch.setattr(dt.shutil, "disk_usage", lambda p: NS(free=1e9))             # 1 GB free < the 4 GB rule
    with pytest.raises(OSError, match="GB free"):
        dt.run_grid(prepared(tmp_path), "coarse", 10, print, fake_solver())


def test_tree_budget_warning(foam, tmp_path, monkeypatch):
    monkeypatch.setattr(dt, "MAX_TREE_GB", 0.0)
    logs = []
    dt.run_grid(prepared(tmp_path), "coarse", 1000, logs.append, fake_solver(foam=foam), frs=(0.1,))
    assert any("budget" in m for m in logs)


# ------------------------------------------------------------------ discretisation uncertainty, tabulation and receipts

def cells_for(r21, r32, n=1000.0):
    """Cell counts, fine first, of three grids whose representative sizes step by r21 (fine/medium) and r32 (medium/coarse)."""
    return [n * (r21 * r32) ** 3, n * r32 ** 3, n]


def test_three_grids_in_the_asymptotic_range_give_celiks_gci_with_the_observed_order():
    for (phi1, phi2, phi3, r21, r32), (p, _, _, _, gci), _ in TABLE1[:2]:                # Celik Table 1, columns 1 and 2
        n = cells_for(r21, r32)
        u, r, note = dt.discretization([phi1, phi2, phi3], n)
        g = vv.celik_gci(phi1, phi2, phi3, r21, r32)
        assert u == pytest.approx(gci, abs=1e-3) and r == pytest.approx(r21) and note == f"p = {g.p:.2f}, Fs = 1.25" and g.p == pytest.approx(p, abs=0.01)
        assert u == pytest.approx(g.gci_fine21, rel=1e-9)


def test_discretization_falls_back_to_roache_and_says_why():
    n = cells_for(1.32, 1.32)
    roache = lambda a, b: vv.gci_two_grid(a, b, vv.refinement_ratio(n[0], n[1]))
    u, r, note = dt.discretization([1.0, 1.02], n[:2])                                 # two grids
    assert u == pytest.approx(roache(1.0, 1.02)) and note == "Fs = 3, p = 2 assumed: two grids" and r == pytest.approx(1.32)
    u, _, note = dt.discretization([1.0, 1.0, 1.0], n)                                 # equal values: no observed order
    assert u == 0.0 and note.endswith("observed order undefined")
    u, _, note = dt.discretization([1.02, 1.0, 0.99], n)                               # moves less between the coarse pair than the fine pair: diverging
    assert note.endswith("diverging") and u == pytest.approx(max(roache(1.02, 1.0), 0.03 / 2 / 1.02))
    u, _, note = dt.discretization([1.0, 1.01, 1.0], n)
    assert note.endswith("oscillating") and u == pytest.approx(max(roache(1.0, 1.01), 0.005))
    for p in (0.3, 3.5):                                                               # converging, but at an order nobody believes
        assert "outside" in dt.discretization(power_law(1.0, 0.01, p, [1.0, 1.32, 1.32 ** 2])[:3], n)[2]
    phis = [1.0 + 0.004 * h ** 2 for h in (1.0, 1.1, 1.21)]                            # converging, but r = 1.1 < 1.3
    assert dt.discretization(phis, cells_for(1.1, 1.1))[2].endswith("r < 1.3")
    good = power_law(1.0, 0.01, 2.0, [1.0, 1.32, 1.32 ** 2])[:3]
    assert dt.discretization(good, n, [2, 2, 1])[2].endswith("grids differ in snappy surface level")
    assert dt.discretization(good, n, [2, 2, 2])[2].startswith("p = 2.00")


CELLS = {"fine": 760_000, "medium": 330_000, "coarse": 143_000}                      # r = 1.32 between neighbours
SIZE = {g: (CELLS["fine"] / n) ** (1 / 3) for g, n in CELLS.items()}                  # representative size relative to the fine grid


def stored(root, ct_by_grid, cells=None, **case):
    """Write run_<grid>.json for each grid in ct_by_grid = {grid: fn(fr) -> C_T}; `case` overrides any per-case field."""
    root = prepared(root)
    cells = cells or CELLS
    for g, fn in ct_by_grid.items():
        speeds = {f"{fr:.2f}": dict(U=1.0, R=1.0, R_std=0.0, ct=fn(fr), ct_std=0.0, iters=1000, seconds=1.0, cells=cells[g], failed_checks=0, surf_level=2,
                                    first_layer=2e-3, layers=9, layer_cover=90.0, y_plus=100.0, y_plus_min=5.0, y_plus_max=400.0, drift=0.001, scatter=0.005,
                                    converged=True) | case for fr in dt.CT_REF}
        (root / f"run_{g}.json").write_text(json.dumps(dict(grid=g, recipe=dt.RECIPE, S=4.9, speeds=speeds)))
    return root


def converging(off=1.01, a=0.004):
    """C_T(h) = D (off + a h^2) on grids of size SIZE[g] times the fine one: exactly second order."""
    return {g: (lambda fr, h=SIZE[g]: dt.CT_REF[fr] * (off + a * h ** 2)) for g in CELLS}


def test_tabulate_uses_three_grids_when_it_has_them_and_two_otherwise(tmp_path):
    root = stored(tmp_path, converging())
    rows = dt.tabulate(root)
    assert len(rows) == 4
    s = [dt.CT_REF[0.28] * (1.01 + 0.004 * SIZE[g] ** 2) for g in CELLS]
    r = [vv.refinement_ratio(a, b) for a, b in ((760_000, 330_000), (330_000, 143_000))]
    g = vv.celik_gci(*s, *r)
    row = rows[0.28]
    assert row.S == s[0] and row.u_num == pytest.approx(g.gci_fine21 * s[0]) and g.p == pytest.approx(2.0, abs=1e-6)
    assert "p = 2.00, Fs = 1.25" in row.case
    assert row.u_input == pytest.approx(s[0] * math.hypot(0.013, 0.006)) and row.u_D == pytest.approx(0.01 * 4.23e-3) and row.E == pytest.approx(s[0] - 4.23e-3)
    two = dt.tabulate(stored(tmp_path / "two", {k: v for k, v in converging().items() if k != "medium"}))[0.28]       # fine + coarse only
    assert two.u_num == pytest.approx(vv.gci_two_grid(s[0], s[2], vv.refinement_ratio(760_000, 143_000)) * s[0]) and "two grids" in two.case
    assert dt.tabulate(tmp_path / "nothing") == {} and dt.tabulate(stored(tmp_path / "one", {"fine": converging()["fine"]})) == {}
    noisy = dt.tabulate(stored(tmp_path / "noisy", converging(), ct_std=1e-4))[0.28]
    assert noisy.u_num == pytest.approx(math.hypot(row.u_num, 1e-4))                     # iteration scatter joins U_num in quadrature


def test_tabulate_leaves_out_froude_numbers_not_run(tmp_path):
    root = stored(tmp_path, converging())
    for g in ("fine", "medium", "coarse"):
        j = json.loads((root / f"run_{g}.json").read_text())
        del j["speeds"]["0.20"]
        (root / f"run_{g}.json").write_text(json.dumps(j))
    assert list(dt.tabulate(root)) == [0.10, 0.28, 0.41]
    out = receipt_state()
    dt.receipts(root)                                       # rows must stay attached to their own Froude number
    assert [x["claim"].split()[2] for x in out if "|E| <=" in x["claim"]] == ["0.10:", "0.28:", "0.41:"]
    assert np.allclose(sorted(x["reference"] for x in out if x.get("kind") == "context"), [4.02, 4.23, 6.67])


def receipt_state():
    rc.OUT.clear()
    return rc.OUT


def failing(out):
    return [x["claim"] for x in out if x.get("ok") is False]


def test_receipts_pass_for_a_good_study_and_name_each_requirement(tmp_path):
    out = receipt_state()
    status = dt.receipts(stored(tmp_path, converging()))
    assert "4 Froude rows" in status and "12 cases" in status
    assert len([x for x in out if "Lofted" in x["claim"]]) == 3 and failing(out) == []
    br = [x["claim"] for x in out if x.get("kind") == "bracket"]
    assert sum("|E| <= U_val" in c for c in br) == 4 and sum("U_val / D <= 0.1" in c for c in br) == 4
    assert [sum(w in c for c in br) for w in ("y+ in the log layer", "last-quarter drift", "last-quarter scatter")] == [12, 12, 12]
    ctx = [x for x in out if x.get("kind") == "context"]
    assert len(ctx) == 4 and all("E =" in x["claim"] and "U_val" in x["claim"] for x in ctx)


def test_a_validation_whose_uncertainty_is_comparable_to_c_t_fails_even_when_E_is_inside_it(tmp_path):
    """The first study: |E| <= U_val passed at Fr 0.10 and 0.28 with U_val ~ 100 % of C_T. That must not read as validated."""
    out = receipt_state()
    wide = {"fine": lambda fr: dt.CT_REF[fr], "medium": lambda fr: dt.CT_REF[fr] * 1.3, "coarse": lambda fr: dt.CT_REF[fr] * 1.9}
    dt.receipts(stored(tmp_path, wide))
    bad = failing(out)
    assert len(bad) == 4 and all("U_val / D <= 0.1" in c for c in bad)
    assert all(x["ok"] for x in out if "|E| <= U_val" in x["claim"])                      # E = 0 sits inside U_val, which is the problem
    row = dt.tabulate(tmp_path)[0.10]
    assert row.u_val / row.D > 0.3


def test_receipts_fail_when_the_physics_is_wrong(tmp_path):
    """C_T 30 % high (a wrong density, speed or area normalisation) must fail every |E| <= U_val receipt; a hull built at the wrong scale
    must fail the geometry receipts; a unit slip is just as visible."""
    out = receipt_state()
    root = stored(tmp_path, {g: (lambda fr, f=f: f(fr) * 1.3) for g, f in converging().items()})
    h = json.loads((root / "hydro.json").read_text())
    h["displacement"] *= 1.1
    h["lwl"] *= 1.02
    (root / "hydro.json").write_text(json.dumps(h))
    dt.receipts(root)
    bad = failing(out)
    assert sum("|E| <= U_val" in c for c in bad) == 4 and sum("Lofted" in c for c in bad) == 2 and len(bad) == 6
    out.clear()
    dt.receipts(stored(tmp_path / "unit", {g: (lambda fr, f=f: f(fr) * 1e3) for g, f in converging().items()}))
    assert sum("|E| <= U_val" in c for c in failing(out)) == 4


def test_receipts_fail_for_y_plus_outside_the_log_layer_and_for_unconverged_iterations(tmp_path):
    out = receipt_state()
    root = stored(tmp_path, converging(), y_plus=1500.0)                                  # no layers: the cell centre is in the outer region
    dt.receipts(root)
    assert len(failing(out)) == 12 and all("y+ in the log layer" in c for c in failing(out))
    out.clear()
    dt.receipts(stored(tmp_path / "low", converging(), y_plus=12.0))
    assert len(failing(out)) == 12
    out.clear()
    dt.receipts(stored(tmp_path / "drift", converging(), drift=0.03))
    assert len(failing(out)) == 12 and all("drift" in c for c in failing(out))
    out.clear()
    dt.receipts(stored(tmp_path / "wave", converging(), scatter=0.06, converged=False))
    assert len(failing(out)) == 12 and all("scatter" in c for c in failing(out))


def test_a_case_that_recorded_no_diagnostics_fails_them(tmp_path):
    out = receipt_state()
    root = stored(tmp_path, converging())
    for g in ("fine", "medium", "coarse"):
        j = json.loads((root / f"run_{g}.json").read_text())
        j["speeds"]["0.41"].update(y_plus=None, drift=None, scatter=None)
        (root / f"run_{g}.json").write_text(json.dumps(j))
    dt.receipts(root)
    assert len(failing(out)) == 9 and all("Fr 0.41" in c for c in failing(out))        # y+, drift and scatter on three grids


def test_receipts_without_results_say_so_and_emit_nothing(tmp_path):
    out = receipt_state()
    assert "no" in dt.receipts(tmp_path) and out == []
    prepared(tmp_path)
    assert "0 Froude rows + 0 cases" in dt.receipts(tmp_path) and len(out) == 3         # geometry only until two grids have run


def test_receipts_default_root_comes_from_cafe_data(tmp_path, monkeypatch):
    receipt_state()
    monkeypatch.setenv("CAFE_DATA", str(tmp_path))
    assert dt.data_root() == tmp_path / "dtmb5415"
    assert "no" in dt.receipts()


# ------------------------------------------------------------------ command line

def test_prepare_with_a_fake_download_and_cli(tmp_path, monkeypatch, capsys):
    root = tmp_path / "out"
    f = tmp_path / "toy.igs"
    write_iges(f, toy_patches())
    igs, blob = f.read_bytes(), make_zip(f.read_bytes())
    monkeypatch.setattr(dt, "SHA_ZIP", sha(blob))
    monkeypatch.setattr(dt, "SHA_IGS", sha(igs))
    h = dt.prepare(root, opener=lambda url: Resp(blob), n_stations=40, n_girth=12, res=(20, 30))
    assert (root / "hull.stl").stat().st_size > 1000 and json.loads((root / "hydro.json").read_text()) == h
    assert trimesh.load(root / "hull.stl").is_watertight
    monkeypatch.setenv("CAFE_DATA", str(tmp_path))
    monkeypatch.setattr(dt, "prepare", lambda r: {"ok": 1})
    monkeypatch.setattr(dt, "run_grid", lambda r, g, n=dt.MAX_ITERS, frs=dt.ORDER: {"grid": g, "iters": n, "frs": frs})
    assert dt.main(["prepare"]) == 0 and '"ok": 1' in capsys.readouterr().out
    assert dt.main(["run", "fine", "7"]) == 0 and '"iters": 7' in capsys.readouterr().out
    assert dt.main(["run", "fine", "7", "0.28,0.1"]) == 0 and '"frs": [\n  0.28,\n  0.1\n ]' in capsys.readouterr().out
    assert dt.main(["run", "coarse"]) == 0 and f'"iters": {dt.MAX_ITERS}' in capsys.readouterr().out
    assert dt.main(["report"]) == 0 and "no" in capsys.readouterr().out
    assert dt.main(["bogus"]) == 2 and "Usage" in capsys.readouterr().out
    monkeypatch.setattr(sys, "argv", ["x", "bogus"])
    with pytest.raises(SystemExit) as e:
        runpy.run_module("cafe.pm.dtmb5415", run_name="__main__")
    assert e.value.code == 2
