"""cafe.pm.vv (Celik 2008 GCI, ASME V&V 20 table) and cafe.pm.dtmb5415 (hull loft, runs, receipts, tabulation)."""
import hashlib
import io
import json
import math
import runpy
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
    d += [f"{406:8d}{0:8d}{0:8d}{0:8d}{0:8d}{0:8d}{0:8d}{0:8d}{0:8d}D{2 * ent + 1:7d}",       # a property entity: skipped
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


def fake_solver(scale=1.0, cells=100_000, fail_first=None, calls=None, fail_levels=(2,)):
    def solve(stl, draft, case, speeds, off, iters, log, surf_level):
        if calls is not None:
            calls.append((off, surf_level))
        if fail_first and surf_level in fail_levels:
            (case).mkdir(parents=True, exist_ok=True)
            (case / "log.snappyHexMesh").write_text(fail_first)
            raise RuntimeError("snappy failed")
        return dict(mesh=dict(cells=cells, failed_checks=0), L=6.1, half=True,
                    speeds={u: dict(resistance=scale * 0.5 * dt.TANK["rho"] * u ** 2 * 4.9 * 4e-3, resistance_std=0.1, iters=iters, seconds=1.0)
                            for u in speeds})
    return solve


def prepared(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "hull.stl").write_text("solid x\nendsolid x\n")
    (tmp_path / "hydro.json").write_text(json.dumps(dict(displacement=0.5532, wetted_area=4.9, lwl=5.7188, bwl=0.7690, draft=0.248)))
    return tmp_path


def test_run_grid_writes_ct_per_speed_and_cleans_up(tmp_path):
    root = prepared(tmp_path)
    (root / "coarse" / "processor0").mkdir(parents=True)
    calls = []
    out = dt.run_grid(root, "coarse", 10, lambda s: None, fake_solver(calls=calls))
    assert dt.GRIDS == {"coarse": (-1, 1), "fine": (0, 2)} and out["surf_level"] == 1 and out["tree_gb"] < 1e-3
    assert [c for c in calls] == [(-1, 1)] * 4 and list(out["speeds"]) == [f"{fr:.2f}" for fr in dt.ORDER]
    s = out["speeds"]["0.28"]
    assert s["ct"] == pytest.approx(4e-3, rel=1e-9) and s["ct_std"] > 0 and s["cells"] == 100_000 and s["failed_checks"] == 0
    assert json.loads((root / "run_coarse.json").read_text())["speeds"]["0.41"]["ct"] == pytest.approx(4e-3, rel=1e-9)
    assert not (root / "coarse" / "processor0").exists()
    assert cfd.FLUIDS["water"]["nu"] == 1.19e-6                      # tank water was only in force during the run


def test_run_grid_runs_only_the_requested_froude_numbers(tmp_path):
    calls = []
    out = dt.run_grid(prepared(tmp_path), "fine", 10, print, fake_solver(calls=calls), frs=(0.1, 0.28))
    assert list(out["speeds"]) == ["0.10", "0.28"] and len(calls) == 2


def test_run_grid_resumes_after_a_crash(tmp_path):
    root = prepared(tmp_path)
    calls = []

    def dies_on_third(stl, draft, case, speeds, off, iters, log, surf_level):
        calls.append(speeds[0])
        if len(calls) == 3:
            raise RuntimeError("OOM")
        return fake_solver()(stl, draft, case, speeds, off, iters, log, surf_level)
    with pytest.raises(RuntimeError, match="OOM"):
        dt.run_grid(root, "fine", 10, print, dies_on_third)
    assert list(json.loads((root / "run_fine.json").read_text())["speeds"]) == ["0.28", "0.41"]      # finished speeds are on disk
    calls.clear()
    out = dt.run_grid(root, "fine", 10, print, fake_solver(calls=calls, fail_levels=()))
    assert calls == [(0, 2), (0, 2)] and len(out["speeds"]) == 4                                      # only the two missing speeds ran


def test_run_grid_steps_down_a_surface_level_and_reraises_other_errors(tmp_path):
    root = prepared(tmp_path)
    calls, logs = [], []
    out = dt.run_grid(root, "fine", 10, logs.append, fake_solver(calls=calls, fail_first="... uses more than 8 points ..."))
    assert calls == [(0, 2), (0, 1), (0, 1), (0, 1), (0, 1)] and out["surf_level"] == 1 and any("surface level 1" in m for m in logs)
    with pytest.raises(RuntimeError):
        dt.run_grid(root, "coarse", 10, logs.append, fake_solver(fail_first="some other failure", fail_levels=(1,)))
    calls.clear()
    again = prepared(tmp_path / "again")
    with pytest.raises(RuntimeError):                                     # fails at level 0 as well: no third try
        dt.run_grid(again, "coarse", 10, logs.append, fake_solver(fail_first="more than 8 points", calls=calls, fail_levels=(0, 1)))
    assert calls == [(-1, 1), (-1, 0)]


def test_run_grid_refuses_to_start_on_a_full_disk(tmp_path, monkeypatch):
    monkeypatch.setattr(dt.shutil, "disk_usage", lambda p: NS(free=1e9))             # 1 GB free < the 6 GB rule
    with pytest.raises(OSError, match="GB free"):
        dt.run_grid(prepared(tmp_path), "coarse", 10, print, fake_solver())


def test_tree_budget_warning(tmp_path, monkeypatch):
    monkeypatch.setattr(dt, "MAX_TREE_GB", 0.0)
    logs = []
    dt.run_grid(prepared(tmp_path), "coarse", 10, logs.append, fake_solver())
    assert any("budget" in m for m in logs)


# ------------------------------------------------------------------ tabulation and receipts

def two_grids(root, ct_fine=None, ct_coarse=None, cells=(330_535, 150_967), ct_std=0.0):
    root = prepared(root)
    for g, n, scale in (("fine", cells[0], ct_fine), ("coarse", cells[1], ct_coarse)):
        speeds = {f"{fr:.2f}": dict(U=1.0, R=1.0, R_std=0.0, ct=scale(fr), ct_std=ct_std, iters=1, seconds=1.0, cells=n, failed_checks=0)
                  for fr in dt.CT_REF}
        (root / f"run_{g}.json").write_text(json.dumps(dict(grid=g, surf_level=1, iters=1, S=4.9, speeds=speeds)))
    return root


def test_tabulate_uses_cell_count_ratio_and_assumptions(tmp_path):
    root = two_grids(tmp_path, lambda fr: dt.CT_REF[fr] * 1.01, lambda fr: dt.CT_REF[fr] * 1.03)
    rows = dt.tabulate(root)
    assert len(rows) == 4
    r = vv.refinement_ratio(330_535, 150_967)
    s = dt.CT_REF[0.28] * 1.01
    row = rows[0.28]
    assert row.u_num == pytest.approx(vv.gci_two_grid(s, dt.CT_REF[0.28] * 1.03, r) * s)
    assert row.u_input == pytest.approx(s * math.hypot(0.013, 0.006)) and row.u_D == pytest.approx(0.01 * 4.23e-3)
    assert row.E == pytest.approx(s - 4.23e-3)
    assert dt.tabulate(tmp_path / "nothing") == {}
    noisy = dt.tabulate(two_grids(tmp_path / "noisy", lambda fr: dt.CT_REF[fr] * 1.01, lambda fr: dt.CT_REF[fr] * 1.03, ct_std=1e-4))
    assert noisy[0.28].u_num == pytest.approx(math.hypot(row.u_num, 1e-4))          # iteration scatter joins U_num in quadrature


def test_tabulate_skips_froude_numbers_not_run(tmp_path):
    root = two_grids(tmp_path, lambda fr: dt.CT_REF[fr], lambda fr: dt.CT_REF[fr] * 1.02)
    for g in ("fine", "coarse"):
        j = json.loads((root / f"run_{g}.json").read_text())
        del j["speeds"]["0.20"]
        (root / f"run_{g}.json").write_text(json.dumps(j))
    assert list(dt.tabulate(root)) == [0.10, 0.28, 0.41]
    out = receipt_state()
    dt.receipts(root)                                       # rows must stay attached to their own Froude number
    assert [x["claim"].split()[2] for x in out if x.get("kind") == "bracket"] == ["0.10:", "0.28:", "0.41:"]
    assert np.allclose(sorted(x["reference"] for x in out if x.get("kind") == "context"), [4.02, 4.23, 6.67])


def receipt_state():
    rc.OUT.clear()
    return rc.OUT


def test_receipts_report_E_and_gate_on_U_val(tmp_path):
    out = receipt_state()
    root = two_grids(tmp_path, lambda fr: dt.CT_REF[fr] * 1.005, lambda fr: dt.CT_REF[fr] * 1.02)
    status = dt.receipts(root)
    assert "4 Froude rows" in status
    geom = [x for x in out if "Lofted" in x["claim"]]
    assert len(geom) == 3 and all(x["ok"] for x in geom)
    br = [x for x in out if x.get("kind") == "bracket"]
    ctx = [x for x in out if x.get("kind") == "context"]
    assert len(br) == 4 and len(ctx) == 4 and all(x["ok"] for x in br)       # 0.5 % off with U_D alone 1 %: validated
    assert all("E =" in x["claim"] and "U_val" in x["claim"] for x in ctx)


def test_receipts_fail_when_the_physics_is_wrong(tmp_path):
    """C_T 30 % high (a wrong density, speed or area normalisation) must fail every |E| <= U_val receipt; a hull built at the
    wrong scale must fail the geometry receipts."""
    out = receipt_state()
    root = two_grids(tmp_path, lambda fr: dt.CT_REF[fr] * 1.3, lambda fr: dt.CT_REF[fr] * 1.32)
    h = json.loads((root / "hydro.json").read_text())
    h["displacement"] *= 1.1
    h["lwl"] *= 1.02
    (root / "hydro.json").write_text(json.dumps(h))
    dt.receipts(root)
    bad = [x["claim"] for x in out if x.get("ok") is False]
    assert sum("|E| <= U_val" in c for c in bad) == 4 and sum("Lofted" in c for c in bad) == 2
    # and a unit slip (C_T x 1000) is just as visible
    out.clear()
    root2 = two_grids(tmp_path / "unit", lambda fr: dt.CT_REF[fr] * 1e3, lambda fr: dt.CT_REF[fr] * 1e3)
    dt.receipts(root2)
    assert sum(x.get("ok") is False for x in out) == 4


def test_receipts_without_results_say_so_and_emit_nothing(tmp_path):
    out = receipt_state()
    assert "no" in dt.receipts(tmp_path) and out == []
    prepared(tmp_path)
    assert "0 Froude rows" in dt.receipts(tmp_path) and len(out) == 3         # geometry only until both grids have run


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
    monkeypatch.setattr(dt, "run_grid", lambda r, g, n=dt.ITERS, frs=dt.ORDER: {"grid": g, "iters": n, "frs": frs})
    assert dt.main(["prepare"]) == 0 and '"ok": 1' in capsys.readouterr().out
    assert dt.main(["run", "fine", "7"]) == 0 and '"iters": 7' in capsys.readouterr().out
    assert dt.main(["run", "fine", "7", "0.28,0.1"]) == 0 and '"frs": [\n  0.28,\n  0.1\n ]' in capsys.readouterr().out
    assert dt.main(["run", "coarse"]) == 0 and f'"iters": {dt.ITERS}' in capsys.readouterr().out
    assert dt.main(["report"]) == 0 and "no" in capsys.readouterr().out
    assert dt.main(["bogus"]) == 2 and "Usage" in capsys.readouterr().out
    monkeypatch.setattr(sys, "argv", ["x", "bogus"])
    with pytest.raises(SystemExit) as e:
        runpy.run_module("cafe.pm.dtmb5415", run_name="__main__")
    assert e.value.code == 2
