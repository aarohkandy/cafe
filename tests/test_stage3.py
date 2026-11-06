"""Wall model, windows (LES + FEA), FluidX3D plugin, refit. Physics checks sit next to tests that break them."""
import json
import math
import os
import pathlib
import pickle
import re
import stat
import tempfile
import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest
from hypothesis import given, settings, strategies as st
import jax.numpy as jnp

import cafe.receipts as cr
from cafe.pm import budget
from cafe.pm.config import ConfigError
from cafe.pm.env import subgrid as sg_mod
from cafe.pm.env.protocol import AnalyticEnv
from cafe.pm.physics import glider as pg, uas, usv as pu
from cafe.pm.stage3 import fluidx3d, freesurface as fs, lbm, nest, pipeline_windows as pw, refit, wallmodel as wm, windows as W

STUB = pathlib.Path(__file__).parent / "fixtures" / "fluidx3d_stub.py"

settings.register_profile("jax", deadline=None)               # first call of a jitted function compiles
settings.load_profile("jax")


@pytest.fixture(autouse=True)
def clean_receipts():
    cr.OUT.clear()
    yield
    cr.OUT.clear()


# ------------------------------------------------------------------ wall model
@given(st.floats(30, 1500), st.floats(1e-4, 5e-3), st.floats(1e-6, 1e-4))
def test_loglaw_inverts_to_the_friction_velocity(yplus, ut, nu):
    y = yplus * nu / ut
    u = ut * (math.log(yplus) / wm.KAPPA + wm.B_LOG)
    got = float(wm.utau_loglaw(jnp.float32(u), jnp.float32(y), jnp.float32(nu)))
    assert got == pytest.approx(ut, rel=2e-3)


def test_loglaw_breaks_with_wrong_constants_and_uses_the_viscous_law_below_y_plus_11():
    ut, nu, y = 2e-3, 2e-5, 2.5
    u = ut * (math.log(y * ut / nu) / wm.KAPPA + wm.B_LOG)
    assert float(wm.utau_loglaw(jnp.float32(u), y, nu)) == pytest.approx(ut, rel=2e-3)
    assert abs(float(wm.utau_loglaw(jnp.float32(u), y, nu, kappa=0.30)) / ut - 1) > 0.1      # wrong kappa
    assert abs(float(wm.utau_loglaw(jnp.float32(u), y, nu, B=3.0)) / ut - 1) > 0.05          # wrong B
    low = float(wm.utau_loglaw(jnp.float32(0.01), 0.5, 0.05))                                  # y+ << 11
    assert low == pytest.approx(math.sqrt(0.05 * 0.01 / 0.5), rel=1e-4)


def test_ittc57_and_yplus_fraction():
    assert wm.ittc57(1e6) == pytest.approx(0.075 / 16)
    assert wm.ittc57(1e9) < wm.ittc57(1e6)
    yp = np.array([10.0, 30.0, 100.0, 300.0, 301.0, 50.0])
    assert wm.yplus_fraction(yp, np.ones(6, bool)) == pytest.approx(4 / 6)
    assert wm.yplus_fraction(yp, np.array([1, 1, 1, 1, 0, 0], bool)) == pytest.approx(3 / 4)


def _plate(shape=(30, 22, 6)):
    solid = np.zeros(shape, bool)
    solid[8:22, 10:12, :] = True
    return solid


def test_wall_set_plate_has_normals_distance_and_matching_points_on_the_right_side():
    solid = _plate()
    link = np.asarray(lbm.links(jnp.asarray(solid)))
    ws = wm.wall_set(solid, link)
    top = ws.cell[1] == 12
    bot = ws.cell[1] == 9
    assert top.any() and bot.any()
    assert np.allclose(ws.nrm[1][top & (ws.cell[0] > 11) & (ws.cell[0] < 18)], 1, atol=0.05)
    assert np.allclose(ws.nrm[1][bot & (ws.cell[0] > 11) & (ws.cell[0] < 18)], -1, atol=0.05)
    mid = top & (ws.cell[0] > 11) & (ws.cell[0] < 18)
    assert np.allclose(ws.phi[mid], 0.5)
    # the matching point lies 2.5 cells off the wall surface: y = 11.5 + 2.5 = 14 -> cell-index coordinate 13.5 around
    ym = (ws.sten[1][:, mid] * ws.wgt[:, mid]).sum(0)
    assert np.allclose(ym, 13.5 + 0.0, atol=0.51)
    assert np.allclose(ws.wgt.sum(0), 1) and ws.valid.all()


def test_wall_set_padding_and_errors():
    solid = _plate()
    ws = wm.wall_set(solid, np.asarray(lbm.links(jnp.asarray(solid))))
    n = ws.cell.shape[1]
    p = wm.pad_wall_set(ws, n + 7)
    assert p.cell.shape[1] == n + 7 and not p.valid[n:].any() and p.valid[:n].all() and (p.wgt[:, n:] == 0).all()
    with pytest.raises(ValueError, match="pad_to"):
        wm.pad_wall_set(ws, n - 1)
    assert wm.wall_set(solid, np.asarray(lbm.links(jnp.asarray(solid))), pad_to=n + 3).cell.shape[1] == n + 3


def test_wall_set_near_list_padding_and_error():
    solid, ws = _plate_ws()
    ws0 = wm.WallSet(*(np.asarray(a) for a in ws))
    m = ws0.near.shape[1]
    p = wm.pad_wall_set(ws0, ws0.cell.shape[1], m + 5)
    assert p.near.shape[1] == m + 5 and (p.near_damp[m:] == 0).all() and (p.near_damp[:m] > 0).all()
    with pytest.raises(ValueError, match="near-wall"):
        wm.pad_wall_set(ws0, ws0.cell.shape[1], m - 1)


def test_wall_set_sphere_normals_are_radial_and_a_solid_stencil_falls_back_to_the_wall_cell():
    shape = (24, 24, 24)
    solid = nest._sphere(shape, (12, 12, 12), 4.0)
    ws = wm.wall_set(solid, np.asarray(lbm.links(jnp.asarray(solid))))
    r = ws.cell.T - 12.0
    cosang = (r * ws.nrm.T).sum(1) / np.linalg.norm(r, axis=1)
    assert np.median(cosang) > 0.95 and (cosang > 0).all()
    tiny = np.zeros((9, 9, 9), bool)
    tiny[3:6, 3:6, 3:6] = True                                             # 3-cell cube: 2.5 cells out is still near; make y_match huge
    ws2 = wm.wall_set(tiny, np.asarray(lbm.links(jnp.asarray(tiny))), y_match=0.0)
    assert np.isfinite(ws2.wgt).all() and np.allclose(ws2.wgt.sum(0), 1)


def _plate_ws(nu=4e-5):
    solid = _plate()
    link = np.asarray(lbm.links(jnp.asarray(solid)))
    return solid, wm.WallSet(*(jnp.asarray(a) for a in wm.wall_set(solid, link)))


def test_wall_state_imposes_the_log_law_stress_on_a_free_slip_wall():
    solid, ws = _plate_ws()
    shape = solid.shape
    nu = 4e-5
    u = jnp.zeros((3,) + shape).at[0].set(0.05)
    st_ = wm.wall_state(u, ws, nu)
    cell = np.asarray(ws.cell)
    mid = (cell[0] > 11) & (cell[0] < 18)
    ut = float(wm.utau_loglaw(jnp.float32(0.05), 2.5, nu))
    fw = np.asarray(st_["fw"])
    assert np.allclose(fw[0][mid], ut ** 2, rtol=0.05) and np.abs(fw[1:][:, mid]).max() < 1e-2 * ut ** 2      # along the flow, area ~1
    assert np.allclose(np.asarray(st_["u_slip"])[0][mid], 0.05, rtol=1e-3)                                    # free slip: u_w = u_1t
    assert np.allclose(np.asarray(st_["yplus"]), 2.5 * np.asarray(st_["utau"]) / nu)
    # a wall moving with the fluid has no relative velocity -> (almost) no stress; against it, the sign flips
    still = wm.wall_state(u, ws, nu, u_wall=(0.05, 0, 0))
    assert float(jnp.abs(still["fw"]).max()) < 1e-9
    back = wm.wall_state(u, ws, nu, u_wall=(0.10, 0, 0))
    assert np.allclose(np.asarray(back["fw"])[0][mid], -ut ** 2, rtol=0.05)
    # normal velocity does not make shear
    v = jnp.zeros((3,) + shape).at[1].set(0.05)
    assert np.abs(np.asarray(wm.wall_state(v, ws, nu)["fw"])[:, mid]).max() < 1e-8


def test_wall_force_adds_exactly_the_stress_momentum_to_the_fluid_and_reports_the_body_force():
    solid, ws = _plate_ws()
    shape = solid.shape
    f = lbm.feq(jnp.ones(shape), jnp.zeros((3,) + shape).at[0].set(0.05))
    st_ = wm.wall_state(lbm.moments(f)[1], ws, 4e-5)
    f2, fw = wm.wall_force(f, ws, st_)
    dm = (lbm.Cj.T @ (f2 - f).reshape(19, -1).sum(1))
    assert np.allclose(np.asarray(dm), -np.asarray(fw), atol=2e-6) and float(fw[0]) > 0     # fluid loses what the body gains
    assert float((f2 - f).sum()) == pytest.approx(0, abs=1e-6)                              # no mass created


def test_wall_field_overrides_only_valid_wall_cells():
    solid, ws = _plate_ws()
    st_ = wm.wall_state(jnp.zeros((3,) + solid.shape).at[0].set(0.05), ws, 4e-5, u_wall=(0.0, 0.01, 0.0))
    fld = np.asarray(wm.wall_field((0.0, 0.01, 0.0), ws, st_, solid.shape))
    cell = tuple(np.asarray(ws.cell))
    mid = (np.asarray(ws.cell[0]) > 11) & (np.asarray(ws.cell[0]) < 18)
    mask = np.ones(solid.shape, bool)
    mask[cell] = False
    assert np.allclose(fld[0][cell][mid], 0.05, rtol=5e-3) and np.allclose(fld[1][cell][mid], 0.01, atol=1e-3)
    assert (fld[0][mask] == 0).all() and np.allclose(fld[1][mask], 0.01)           # everywhere else: the body velocity


def test_near_wall_tau_is_the_log_consistent_mixing_length_and_only_raises_tau():
    solid = np.zeros((16, 20, 4), bool)
    solid[:, :4, :] = True
    link = np.asarray(lbm.links(jnp.asarray(solid)))
    ws = wm.WallSet(*(jnp.asarray(a) for a in wm.wall_set(solid, link)))
    u = jnp.zeros((3,) + solid.shape).at[0].set(0.04)
    nu = 3e-5
    st_ = wm.wall_state(u, ws, nu)
    base = jnp.full(solid.shape, 0.5001)
    new = np.asarray(wm.near_wall_tau(base, ws, st_, nu))
    ut = float(st_["utau"][0])
    for j, phi in ((4, 0.5), (5, 1.5), (6, 2.5)):                           # cells 1-3 above the wall
        nut = wm.KAPPA * ut * phi
        assert new[8, j, 1] == pytest.approx(0.5 + 3 * (nu + nut), rel=1e-4)
    assert new[8, 7, 1] == pytest.approx(0.5001) and (new >= 0.5001 - 1e-7).all()      # beyond the layer, and never lowered
    big = jnp.full(solid.shape, 1.2)
    assert (np.asarray(wm.near_wall_tau(big, ws, st_, nu)) == 1.2).all()                # Smagorinsky already larger: untouched
    # a thick layer (channel): damped linearly to zero at the layer edge
    ws2 = wm.WallSet(*(jnp.asarray(a) for a in wm.wall_set(solid, link, rans_layer=10.0)))
    t2 = np.asarray(wm.near_wall_tau(base, ws2, wm.wall_state(u, ws2, nu), nu))
    assert t2[8, 8, 1] == pytest.approx(0.5 + 3 * (nu + wm.KAPPA * ut * 4.5 * (1 - 4.5 / 10)), rel=1e-3) and t2[8, 14, 1] == pytest.approx(0.5001)


def test_channel_receipts_at_ci_size():
    """Thin periodic channel, Re_tau 1000: balance, Dean, log-layer position, specular walls (the well-posed wall-model receipts)."""
    c = wm.channel(**wm.CHANNEL_CI)
    assert c["balance_err"] < 0.01 and c["err"] < 0.10 and c["bb_tangential_frac"] < 0.01
    assert wm.YPLUS_OK[0] < c["yplus_m"] < wm.YPLUS_OK[1] and c["ym_over_h"] < 0.3 and c["mach_max"] < 0.12
    assert c["profile"].shape == (24,) and (np.diff(c["profile"][:12]) > 0).all()        # monotone profile up to the centreline
    assert c["tau_target"] == pytest.approx(0.0026 ** 2)                      # g h = u_tau^2


def test_channel_breaks_without_the_near_wall_eddy_viscosity_or_with_the_wrong_law():
    short = dict(wm.CHANNEL_CI, steps=60000)
    no_rans = wm.channel(rans=False, **short)
    assert no_rans["err"] > 0.3 or no_rans["balance_err"] > 0.1                          # Smagorinsky alone cannot carry the stress
    assert wm.dean_cf(4e4) == pytest.approx(0.073 * 4e4 ** -0.25) and wm.dean_cf(1e5) < wm.dean_cf(1e4)
    no_wm = wm.channel(wall_model=False, **short)
    assert no_wm["tau_w"] == 0 and no_wm["yplus_m"] == 0                                 # no stress BC, no wall shear


def test_flat_plate_ci_size_regression():
    """CI-size plate (Re_L ~ 1e5, laminar nu_lat, boundary layer thinner than the 3rd cell): ITTC-57 does not apply here, so this
    is a regression pin (C_f ~ 0.78 of ITTC), not a receipt; the receipts are the channel (CI) and the Re_L >= 1e6 plate (slow)."""
    on = wm.flat_plate(**wm.PLATE_CI)
    assert 0.6 < on["cf"] / on["ittc"] < 0.95 and on["yfrac"] >= 0.9 and on["mach_max"] < 0.12
    f = on["force"]
    assert np.isfinite(f).all() and f[-3000:].mean() > 0                    # drag on the plate, steady sign
    off = wm.flat_plate(wall_model=False, **wm.PLATE_CI)
    assert off["yfrac"] == 0 and off["utau"] == 0 and abs(off["cf"]) < 0.05 * on["cf"]    # specular walls without the stress BC: frictionless


def test_inflow_turbulence_intensity_and_mean():
    env = wm.inflow_turbulence(0.1, seed=3)
    g = np.stack(np.meshgrid(np.arange(60.0), np.arange(30.0), np.arange(20.0), indexing="ij"))
    u = np.asarray(env(jnp.asarray(g[0]), jnp.asarray(g[1]), jnp.asarray(g[2]), 0.0))
    assert u[0].mean() == pytest.approx(1.0, abs=0.05)
    assert 0.05 < u[1].std() < 0.2 and 0.05 < (u[0] - 1).std() < 0.2
    u2 = np.asarray(env(jnp.asarray(g[0]), jnp.asarray(g[1]), jnp.asarray(g[2]), 5.0))
    shifted = np.asarray(env(jnp.asarray(g[0] - 5.0), jnp.asarray(g[1]), jnp.asarray(g[2]), 0.0))
    assert np.allclose(u2, shifted, atol=1e-5)                              # frozen turbulence, convected at U
    assert np.allclose(wm.inflow_turbulence(0.0)(jnp.asarray(g[0]), jnp.asarray(g[1]), jnp.asarray(g[2]), 0.0)[1], 0)


def test_plate_mask_and_ittc_strip_average():
    m = wm.plate_mask((60, 40, 3), 10, 40, 20.0, 2.0, 8)
    assert m[:, :, 0].sum() == m[:, :, 2].sum() and m[30, 18:22, 0].all() and not m[30, 16, 0] and not m[5, 20, 0]
    assert m[10, :, 0].sum() <= 2 and m[30, :, 0].sum() == 4 and m[49, :, 0].sum() <= 2   # rounded nose and tail, 4 cells between
    a, b = 2e4, 8e4
    mean = wm.ittc57_mean(a, b)
    assert 0.5 * wm.ittc57(b) < mean < wm.ittc57(a)                           # strip mean: below the total up to a, above half the total up to b
    h = 1e-3
    local = ((1e6 + h) * wm.ittc57(1e6 + h) - (1e6 - h) * wm.ittc57(1e6 - h)) / (2 * h)       # d(Re C)/dRe = local friction
    assert wm.ittc57_mean(1e6 - 50, 1e6 + 50) == pytest.approx(local, rel=1e-3) and local < wm.ittc57(1e6)


def _stub_plate(**over):
    base = dict(cf=0.0040, ittc=0.0040, re=1e6, yfrac=0.95, force=np.ones(10), utau=0.002, mach_max=0.05, err=0.0, re_a=1e5)
    base.update(over)
    return base


def _stub_channel(**over):
    base = dict(tau_w=1e-5, tau_target=1e-5, cf=0.0051, cf_dean=0.0052, re_b=4e4, yplus_m=200.0, ym_over_h=0.2, bb_tangential_frac=0.0,
                err=0.02, balance_err=0.0)
    base.update(over)
    return base


def test_wall_model_receipts_pass_and_fail(monkeypatch, tmp_path):
    monkeypatch.setattr(wm, "SLOW_DIR", tmp_path)
    monkeypatch.setattr(wm, "flat_plate", lambda **k: _stub_plate())
    monkeypatch.setattr(wm, "channel", lambda **k: _stub_channel())
    assert wm.stored_wall_error() is None
    out = wm.receipts()                                                       # nothing stored: the plate row is required, so it fails with the command
    plate_row = [r for r in out if "Flat plate" in r["claim"]]
    assert len(out) == 7 and [r["ok"] for r in out].count(False) == 1 and plate_row[0]["ok"] is False
    assert "NOT STORED" in plate_row[0]["claim"] and wm.PLATE_COMMAND in plate_row[0]["source"] and wm.PLATE_ETA in plate_row[0]["source"]
    cr.OUT.clear()
    assert all(r["ok"] for r in wm.receipts(_stub_plate(cf=0.0042), _stub_channel()))
    sha = lbm.physics_sha()                                                    # (stored by the current code: round 7 M-8 makes a missing or old sha stale)
    bad_plate = {k: v for k, v in _stub_plate(cf=0.0010, err=0.75).items() if k != "force"}              # friction 4x too low
    wm.slow_path().write_text(json.dumps(dict(bad_plate, code_sha=sha)))
    assert wm.stored_wall_error() is None                                      # the plate alone is not enough
    wm.channel_path().write_text(json.dumps(_stub_channel(err=0.03, code_sha=sha)))
    assert wm.stored_wall_error() == 0.75                                      # the worse stored receipt counts: a passing channel cannot hide the plate
    cr.OUT.clear()
    bad = wm.receipts()
    assert any(r["ok"] is False and "Flat plate" in r["claim"] for r in bad)
    cr.OUT.clear()
    wm.slow_path().write_text(json.dumps(dict({k: v for k, v in _stub_plate(cf=0.0040, err=0.09).items() if k != "force"}, code_sha="stale")))
    assert any("DIFFERENT CODE" in r["claim"] for r in wm.receipts())
    for over, claim in ((dict(tau_w=1.1e-5), "wall stress"), (dict(cf=0.0070), "bulk C_f"), (dict(yplus_m=900.0), "y+"),
                        (dict(ym_over_h=0.6), "height"), (dict(bb_tangential_frac=0.2), "tangential")):
        cr.OUT.clear()
        out = wm.receipts(_stub_plate(), _stub_channel(**over))
        assert any(r["ok"] is False and claim in r["claim"] for r in out), claim
    cr.OUT.clear()
    assert any(r["ok"] is False for r in wm.receipts(_stub_plate(yfrac=0.2), _stub_channel()))   # y+ out of the log layer fails too


def test_wall_model_receipt_fails_with_a_wrong_kappa(monkeypatch, tmp_path):
    monkeypatch.setattr(wm, "SLOW_DIR", tmp_path)
    monkeypatch.setattr(wm, "KAPPA", 0.30)
    out = wm.receipts(_stub_plate(), _stub_channel())
    assert any(r["ok"] is False and "Log law" in r["claim"] for r in out)


def test_wall_model_cli(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(wm, "SLOW_DIR", tmp_path)
    monkeypatch.setattr(wm, "flat_plate", lambda **k: _stub_plate())
    monkeypatch.setattr(wm, "channel", lambda **k: _stub_channel(profile=np.ones(3)))
    assert wm.main(["slow"]) == 0 and json.loads(wm.slow_path().read_text())["cf"] == 0.004 and "code_sha" in json.loads(wm.slow_path().read_text())
    assert wm.main(["channel"]) == 0 and json.loads(wm.channel_path().read_text())["cf"] == 0.0051
    assert json.loads(wm.channel_path().read_text())["code_sha"] == lbm.physics_sha()                   # round 7 M-8: the CLI stores the sha it ran with
    assert wm.main([]) == 0
    monkeypatch.setattr(wm, "flat_plate", lambda **k: _stub_plate(cf=0.001))
    assert wm.main(["slow"]) == 0
    cr.OUT.clear()
    monkeypatch.setattr(wm, "channel", lambda **k: _stub_channel(tau_w=2e-5))
    assert wm.main([]) == 1                                                   # the stored run now fails the receipt


# ------------------------------------------------------------------ geometry
HULL = W.Vehicle("auv", "water", 0.3, [dict(type="ellipsoid", center=(0, 0, 0), radii=(0.15, 0.04, 0.04))], material="al6061",
                 thickness=0.002, depth=10.0)


def test_voxelization_volumes_and_shape_types(tmp_path):
    dx, shape, anc = 0.005, (80, 60, 60), (40, 30, 30)
    v_ell = W.voxelize(HULL, dx, shape, anc).sum() * dx ** 3
    assert v_ell == pytest.approx(4 / 3 * math.pi * 0.15 * 0.04 * 0.04, rel=0.05)
    cyl = W.Vehicle("c", "water", 0.3, [dict(type="cylinder", center=(0.01, 0, 0), radius=0.04, length=0.2)], None)
    assert W.voxelize(cyl, dx, shape, anc).sum() * dx ** 3 == pytest.approx(math.pi * 0.04 ** 2 * 0.2, rel=0.08)
    pl = W.Vehicle("p", "air", 0.3, [dict(type="plate", center=(0, 0.1, 0), size=(0.1, 0.2, 0.01))], None)
    assert W.voxelize(pl, dx, shape, anc).sum() * dx ** 3 == pytest.approx(0.1 * 0.2 * 0.01, rel=0.25)    # 2-3 cells thick at dx = 5 mm
    assert W.frontal_area(W.voxelize(HULL, dx, shape, anc), dx) == pytest.approx(math.pi * 0.04 ** 2, rel=0.2)
    import trimesh
    p = tmp_path / "b.stl"
    trimesh.creation.box(extents=(0.1, 0.05, 0.05)).export(p)
    stl = W.Vehicle("s", "water", 0.1, [dict(type="stl", path=str(p))], None)
    assert W.voxelize(stl, dx, shape, anc).sum() * dx ** 3 == pytest.approx(0.1 * 0.05 * 0.05, rel=0.35)   # fill adds <= half a voxel per face
    assert abs(W.vehicle_mesh(stl).volume - 0.1 * 0.05 * 0.05) < 1e-9
    with pytest.raises(ValueError, match="unknown shape"):
        W.voxelize(W.Vehicle("x", "water", 1, [dict(type="torus")], None), dx, shape, anc)
    with pytest.raises(ValueError, match="unknown shape"):
        W.vehicle_mesh(W.Vehicle("x", "water", 1, [dict(type="torus")], None))


def test_vehicle_meshes_are_closed_and_placed():
    for sh, vol in ((dict(type="ellipsoid", center=(0.1, 0, 0), radii=(0.15, 0.04, 0.04)), 4 / 3 * math.pi * 0.15 * 0.04 ** 2),
                    (dict(type="cylinder", center=(0, 0, 0), radius=0.05, length=0.4), math.pi * 0.05 ** 2 * 0.4),
                    (dict(type="plate", center=(0, 0, 0), size=(0.1, 0.2, 0.01)), 2e-4)):
        m = W.vehicle_mesh(W.Vehicle("v", "water", 1, [sh], None))
        assert m.is_watertight and m.volume == pytest.approx(vol, rel=0.05)
    cyl = W.vehicle_mesh(W.Vehicle("v", "water", 1, [dict(type="cylinder", center=(0, 0, 0), radius=0.05, length=0.4)], None))
    assert np.allclose(cyl.extents, [0.4, 0.1, 0.1], atol=1e-6)            # axis along x


def test_window_resolution_applies_the_brief_rule():
    v = W.Vehicle("hull", "water", 1.5, [], None)
    r = W.window_resolution(v, W.WindowSpec(velocity=(1.5, 0, 0), box=(2 / 1.5, 0.5 / 1.5, 0.5 / 1.5)))
    assert r["dx"] == pytest.approx(0.003, rel=0.03) and 1.5e7 < r["cells"] < 2.2e7 and 0.8e5 < r["steps"] < 1.3e5
    assert r["y_plus_estimate"] > 300
    r2 = W.window_resolution(v, W.WindowSpec(velocity=(1.5, 0, 0), dx=0.01, steps=77, box=(1, 1, 1)))
    assert r2["dx"] == 0.01 and r2["steps"] == 77 and r2["shape"] == (150, 150, 150)


# ------------------------------------------------------------------ coefficients
def test_coefficients_drag_lift_geometry_and_scaling():
    rho, area, v = 1025.0, 0.02, np.array([1.0, 0.0, 0.0])
    q = 0.5 * rho * area
    F = np.tile([-0.3 * q, 0.0, 0.1 * q], (50, 1))                         # body moving +x in still water: drag pushes -x
    c = W.coefficients(F, -v, rho, area)
    assert c["cd"] == pytest.approx(0.3) and c["cl"] == pytest.approx(0.1) and c["cd_spread"] == pytest.approx(0, abs=1e-12)
    assert np.allclose(c["flow_dir"], [-1, 0, 0])
    c2 = W.coefficients(-F, -v, rho, area)                                  # opposite force: negative drag, not abs()
    assert c2["cd"] == pytest.approx(-0.3) and c2["cl"] == pytest.approx(-0.1)
    ar = W.coefficients(F, -v, rho, area, cd_ref=0.25)["added_resistance"]
    assert ar == pytest.approx(0.3 / 0.25 - 1) and W.coefficients(F, -v, rho, area)["added_resistance"] is None


@given(st.floats(0.1, 10), st.floats(0.5, 5.0))
def test_coefficients_scale_linearly_with_force_and_quadratically_with_speed(k, s):
    rng = np.random.default_rng(0)
    F = rng.normal(-3, 0.3, (60, 3))
    base = W.coefficients(F, np.array([-1.0, 0, 0]), 1000.0, 0.05)
    assert W.coefficients(k * F, np.array([-1.0, 0, 0]), 1000.0, 0.05)["cd"] == pytest.approx(k * base["cd"], rel=1e-9)
    assert W.coefficients(F, np.array([-s, 0, 0]), 1000.0, 0.05)["cd"] == pytest.approx(base["cd"] / s ** 2, rel=1e-9)   # q ~ s^2
    assert W.coefficients(F, np.array([-s, 0, 0]), 1000.0, 0.05)["q"] == pytest.approx(base["q"] * s ** 2)


def test_blocks_spread_detects_a_drift():
    flat, sd = W.blocks(np.ones(100))
    assert flat == 1 and sd == 0
    drift = W.blocks(np.linspace(0, 1, 100))
    assert drift[1] > 0.2 and W.blocks(np.ones(3), 1)[1] == 0.0


def _series(n=300, **over):
    s = dict(umax=np.full(n, 0.05), yfrac=np.full(n, 0.95), mass=np.full(n, 1e5), res=np.full(n, 1e-3), shift=np.zeros((n, 3), int))
    s.update(over)
    return s


def test_stage3_checks_each_one_can_fail():
    spec = nest.NestSpec((20, 20, 20), 0.01, 1.0, 1e-6)
    f = np.ones(300)

    def verdicts(series=None, force=f, buffer=10, plate=0.1):
        return {c["name"]: c["ok"] for c in W.stage3_checks(series or _series(), spec, force, buffer, plate)}
    assert all(verdicts().values()) and len(verdicts()) == 9
    assert not verdicts(plate=None)["wall_model_receipt_error"]                      # no stored receipt: not validated
    assert not verdicts(plate=0.7)["wall_model_receipt_error"]                       # receipt out of tolerance
    assert not verdicts(_series(umax=np.full(300, 0.07)))["mach_max"]                      # 0.07 sqrt3 = 0.121
    assert not verdicts(_series(umax=np.full(300, 0.35)))["courant_max"]
    assert not verdicts(_series(yfrac=np.full(300, 0.5)))["yplus_in_30_300_fraction"]
    assert not verdicts(force=np.concatenate([np.ones(200), np.linspace(1, 3, 100)]))["force_running_mean_dev"]
    assert not verdicts(_series(mass=1e5 * (1 + 2e-3 * np.arange(300) % 2)))["mass_drift_per_step"]
    assert not verdicts(_series(res=np.full(300, 0.5)))["interpolation_residual"]
    assert not verdicts(buffer=3)["sponge_clearance_cells"]
    sh = np.zeros((300, 3), int)
    sh[::10, 0] = 1
    row = [c for c in W.stage3_checks(_series(shift=sh), spec, f, 10, 0.1) if c["name"] == "nest_shift_count"][0]
    assert row["value"] == 30 and row["ok"]
    wall_off = nest.NestSpec((20, 20, 20), 0.01, 1.0, 1e-6, wall_model=False)
    assert [c for c in W.stage3_checks(_series(yfrac=np.zeros(300)), wall_off, f, 10, 0.1) if c["name"].startswith("yplus")][0]["ok"]


def test_the_yplus_row_is_not_a_wall_model_pass_when_it_was_evaluated_at_the_raised_lattice_viscosity():
    raised = nest.NestSpec((20, 20, 20), 0.01, 1.0, 1e-6, nu_floor=1e-4)
    assert raised.nu_lat == 1e-4 > 1e-6 * raised.dt / raised.dx ** 2
    checks = lambda spec: W.stage3_checks(_series(yfrac=np.full(300, 0.97)), spec, np.ones(300), 10, 0.1)  # noqa: E731
    row = lambda spec: [c for c in checks(spec) if c["name"] == "yplus_in_30_300_fraction"][0]  # noqa: E731
    r = row(raised)
    assert r["value"] == pytest.approx(0.97) and not r["ok"] and r["note"] == W.YPLUS_RAISED_NOTE            # 97 % inside, yet not a pass
    assert row(nest.NestSpec((20, 20, 20), 0.01, 1.0, 1e-6))["ok"]                                         # the same series at the physical viscosity passes
    assert row(nest.NestSpec((20, 20, 20), 0.01, 1.0, 1e-6, nu_floor=1e-12))["ok"]                         # a floor below the physical value changes nothing
    off = nest.NestSpec((20, 20, 20), 0.01, 1.0, 1e-6, nu_floor=1e-4, wall_model=False)
    assert row(off)["ok"]
    res = dict(delta_te=0.1, dx=0.01, y_plus_estimate=1370.0)
    why = pw.why_failed([r], res, {})
    assert len(why) == 1 and "raised lattice viscosity" in why[0] and "1370" in why[0] and "not a wall-model pass" in why[0]


# ------------------------------------------------------------------ one real LES window
def _uniform(u):
    u = np.asarray(u, np.float32)
    return lambda x, y, z, t: jnp.stack([jnp.full_like(x, u[0]), jnp.full_like(x, u[1]), jnp.full_like(x, u[2])])


def test_run_window_small_ellipsoid_in_a_current():
    v = (0.5, 0.0, 0.0)
    sp = W.WindowSpec(velocity=v, dx=0.01, steps=1600, box=(2.0, 0.8, 0.8), cd_ref=0.2, chunk=200)
    r = W.run_window(HULL, sp, _uniform([0, 0, 0]))
    assert r["resolution"]["shape"] == (60, 24, 24) and r["source"] == "native-nest"
    assert r["cd"] > 0 and r["drag"].shape == (1600,)
    assert abs(r["cl"]) < 0.5 * r["cd"]                                    # symmetric body: no lift to speak of
    assert r["flow_dir"][0] == pytest.approx(-1) and r["force"][-200:, 0].mean() < 0   # body moves +x: force on it points -x
    assert r["added_resistance"] == pytest.approx(r["cd"] / 0.2 - 1, rel=0.05)
    assert r["wall_points"].shape[1] == 3 and r["wall_pressure"].shape[0] == r["wall_points"].shape[0]
    assert r["wall_pressure"].max() > 0 > r["wall_pressure"].min()          # stagnation overpressure and wake/side suction
    names = {c["name"] for c in r["checks"]}
    assert {"mach_max", "yplus_in_30_300_fraction", "mass_drift_per_step"} <= names
    assert r["shifts"] == 0                                                  # vehicle frame: the grid sits on the vehicle
    # the same hull towed the other way: force flips sign, drag coefficient does not
    r2 = W.run_window(HULL, W.WindowSpec(velocity=(-0.5, 0, 0), dx=0.01, steps=1600, box=(2.0, 0.8, 0.8)), _uniform([0, 0, 0]))
    assert r2["force"][-200:, 0].mean() > 0 and r2["cd"] == pytest.approx(r["cd"], rel=0.15)


def test_run_window_ground_frame_shifts_the_nest_with_the_vehicle():
    sp = W.WindowSpec(velocity=(0.5, 0.0, 0.0), dx=0.01, steps=400, box=(2.0, 0.8, 0.8), frame="ground")
    r = W.run_window(HULL, sp, _uniform([0, 0, 0]))
    assert r["shifts"] >= 10 and np.isfinite(r["force"]).all()
    shift_row = [c for c in r["checks"] if c["name"] == "nest_shift_count"][0]
    assert shift_row["value"] == r["shifts"]
    with pytest.raises(ValueError, match="frame"):
        W.run_window(HULL, W.WindowSpec(velocity=(0.5, 0, 0), dx=0.01, steps=10, frame="body"), _uniform([0, 0, 0]))


def test_run_window_rejects_bad_requests(monkeypatch):
    sp = W.WindowSpec(velocity=(0.5, 0, 0), dx=0.01, steps=10)
    with pytest.raises(ValueError, match="native kernel"):
        W.run_window(HULL, sp, _uniform([0, 0, 0]), backend="warp")
    tiny = W.Vehicle("none", "water", 0.3, [dict(type="ellipsoid", center=(5, 5, 5), radii=(0.01, 0.01, 0.01))])
    with pytest.raises(ValueError, match="no cells"):
        W.run_window(tiny, sp, _uniform([0, 0, 0]))
    monkeypatch.setattr(lbm, "device_memory_bytes", lambda: 1e6)
    with pytest.raises(lbm.MemoryGuardError):
        W.run_window(HULL, sp, _uniform([0, 0, 0]))


# ------------------------------------------------------------------ FEA
def _sphere_points(r, n=600):
    i = np.arange(n) + 0.5
    phi, th = np.arccos(1 - 2 * i / n), math.pi * (1 + 5 ** 0.5) * i
    return r * np.stack([np.cos(th) * np.sin(phi), np.sin(th) * np.sin(phi), np.cos(phi)], 1)


def test_fea_window_matches_the_thin_sphere_membrane_stress_and_scales_with_pressure(tmp_path):
    ball = W.Vehicle("ball", "water", 0.1, [dict(type="ellipsoid", center=(0, 0, 0), radii=(0.05, 0.05, 0.05))],
                     material="al6061", thickness=0.002, depth=0.0)
    pts = _sphere_points(0.05)
    p0 = 1.0e5
    a = W.fea_window(ball, pts, np.full(len(pts), p0), workdir=tmp_path / "a", h=0.01)
    membrane = p0 * 0.05 / (2 * 0.002)                                       # p R / (2 t), 1.25 MPa
    assert 0.8 * membrane / 276e6 < a["utilization"] < 1.4 * membrane / 276e6
    b = W.fea_window(ball, pts, np.full(len(pts), 2 * p0), workdir=tmp_path / "b", h=0.01)
    assert b["utilization"] == pytest.approx(2 * a["utilization"], rel=0.03)
    assert 0.1 < a["min_element_quality"] <= 1 and a["elements"] > 100 and a["safety_factor"] > 1
    # depth adds hydrostatic pressure rho g d: 100 m of sea water ~ 10 bar, on top of a zero LES pressure
    d = W.Vehicle(**{**ball.__dict__, "depth": 100.0})
    c = W.fea_window(d, pts, np.zeros(len(pts)), workdir=tmp_path / "c", h=0.01)
    assert c["hydrostatic_pa"] == pytest.approx(1025 * 9.81 * 100)
    assert c["utilization"] == pytest.approx(c["hydrostatic_pa"] * 0.05 / (2 * 0.002) / 276e6, rel=0.3)


def test_fea_buckling_utilization_can_exceed_the_stress_utilization(tmp_path):
    thin = W.Vehicle("thin", "water", 0.4, [dict(type="cylinder", center=(0, 0, 0), radius=0.05, length=0.4)],
                     material="al6061", thickness=0.0005, depth=0.0)
    th = np.linspace(0, 2 * math.pi, 40, endpoint=False)
    pts = np.array([[x, 0.05 * math.cos(a), 0.05 * math.sin(a)] for x in np.linspace(-0.2, 0.2, 20) for a in th])
    r = W.fea_window(thin, pts, np.full(len(pts), 3e5), workdir=tmp_path, h=0.02, buckle=True)
    assert r["buckling_factor"] and r["utilization"] == pytest.approx(max(r["vm_p99"] / 276e6, 1 / r["buckling_factor"]))


def test_tri_quality():
    nodes = np.array([[0, 0, 0], [1, 0, 0], [0.5, math.sqrt(3) / 2, 0], [10, 0, 0]], float)
    assert W.tri_quality(nodes, np.array([[0, 1, 2]])) == pytest.approx(1.0)
    assert W.tri_quality(nodes, np.array([[0, 1, 2], [0, 3, 2]])) < 0.5


def test_run_windows_overlaps_fea_with_the_next_les_window(monkeypatch):
    seen = []
    real = W.fea_window

    def spy(*a, **k):
        seen.append(threading.get_ident())
        return dict(utilization=0.1, spy=True)
    monkeypatch.setattr(W, "fea_window", spy)
    sp = W.WindowSpec(velocity=(0.5, 0, 0), dx=0.01, steps=60, box=(2.0, 0.8, 0.8))
    out = W.run_windows([(HULL, sp), (HULL, sp)], _uniform([0, 0, 0]), omp_threads=3)
    assert len(out) == 2 and all(o["fea"]["spy"] for o in out)
    assert len(seen) == 2 and all(t != threading.get_ident() for t in seen)      # FEA ran in the worker, not on the LES thread
    assert os.environ["OMP_NUM_THREADS"] == "3"
    assert W.fea_window is spy and real is not spy
    assert W.run_windows([], _uniform([0, 0, 0])) == []


# ------------------------------------------------------------------ FluidX3D plugin (against the stub in tests/fixtures)
def cfg(path=STUB, enabled=True):
    return {"fluidx3d": {"enabled": enabled, "binary": str(path)}}


def test_fluidx3d_is_disabled_by_default_and_says_why(tmp_path):
    assert fluidx3d.settings(None)["enabled"] is False
    ok, why = fluidx3d.available({})
    assert not ok and "disabled" in why and "LICENSES" in why
    with pytest.raises(fluidx3d.FluidX3DUnavailable, match="disabled"):
        fluidx3d.run_case({}, {"steps": 1}, tmp_path)
    assert "not set" in fluidx3d.available({"fluidx3d": {"enabled": True}})[1]
    assert "does not exist" in fluidx3d.available(cfg(tmp_path / "nope"))[1]
    f = tmp_path / "f"
    f.write_text("x")
    assert "not executable" in fluidx3d.available(cfg(f))[1]
    assert fluidx3d.available(cfg())[0]


def test_stub_binary_round_trip_gives_the_known_drag_coefficient(tmp_path):
    assert os.access(STUB, os.X_OK) or STUB.chmod(STUB.stat().st_mode | stat.S_IXUSR) is None
    v = W.Vehicle("stubby", "water", 0.5, [], ref_area=0.02)
    sp = W.WindowSpec(velocity=(1.0, 0.0, 0.0), dx=0.01, steps=500, box=(1, 1, 1))
    r = W.fluidx3d_window(v, sp, cfg(), tmp_path)
    assert r["source"] == "fluidx3d" and len(r["binary_sha256"]) == 64
    assert r["cd"] == pytest.approx(0.30, rel=0.01) and abs(r["cl"]) < 1e-9 and r["force"].shape == (100, 3)
    assert r["force"][:, 0].max() < 0                                       # drag opposes +x motion
    (tmp_path / "case.json").exists() and json.loads((tmp_path / "case.json").read_text())["velocity"] == [1.0, 0.0, 0.0]
    # default reference area when the vehicle gives none
    assert W.fluidx3d_window(W.Vehicle("s", "water", 0.5, []), sp, cfg(), tmp_path / "b")["ref_area"] > 0


def test_stub_failures_are_reported(tmp_path):
    case = fluidx3d.case_dict("stub-crash", (4, 4, 4), 0.01, 0.001, 1e-6, 1000.0, (1, 0, 0), 10)
    with pytest.raises(RuntimeError, match="exited 3"):
        fluidx3d.run_case(cfg(), case, tmp_path / "a")
    case["name"] = "stub-nofile"
    with pytest.raises(RuntimeError, match="without writing"):
        fluidx3d.run_case(cfg(), case, tmp_path / "b")


def test_forces_file_format_is_validated(tmp_path):
    f = tmp_path / "forces.dat"
    f.write_text("# c\n1 0.1 1 2 3\n\n2 0.2 4 5 6\n")
    t, F = fluidx3d.read_forces(f)
    assert np.allclose(t, [0.1, 0.2]) and np.allclose(F, [[1, 2, 3], [4, 5, 6]])
    for body, msg in (("1 0.1 1 2\n", "columns"), ("# only comment\n", "no data"), ("1 0.1 1 nan 3\n", "non-finite"),
                      ("1 0.2 1 2 3\n2 0.1 1 2 3\n", "not increasing")):
        f.write_text(body)
        with pytest.raises(ValueError, match=msg):
            fluidx3d.read_forces(f)


def test_case_dict_validates():
    c = fluidx3d.case_dict("a", (1, 2, 3), 0.01, 0.001, 1e-6, 1000.0, (1, 0, 0), 5, free_surface=True, draft=0.1)
    assert c["cells"] == [1, 2, 3] and c["free_surface"] and c["draft"] == 0.1
    with pytest.raises(ValueError):
        fluidx3d.case_dict("a", (1, 1, 1), 0.0, 0.001, 1e-6, 1000.0, (1, 0, 0), 5)
    with pytest.raises(ValueError):
        fluidx3d.case_dict("a", (1, 1, 1), 0.01, float("nan"), 1e-6, 1000.0, (1, 0, 0), 5)


def test_free_surface_window_uses_fluidx3d_when_enabled_else_interfoam(tmp_path):
    v = W.Vehicle("boat", "water", 1.0, [], ref_area=0.02)
    r = W.free_surface_window("hull.stl", 0.1, [1.0, 2.0], tmp_path, config=cfg(), vehicle=v)
    assert r["source"] == "fluidx3d" and set(r["speeds"]) == {1.0, 2.0}
    assert r["speeds"][2.0]["resistance"] == pytest.approx(4 * r["speeds"][1.0]["resistance"], rel=0.02)   # R ~ U^2
    calls = []

    def runner(stl, draft, wd, speeds):
        calls.append((stl, draft, speeds))
        return dict(speeds={U: dict(resistance=10 * U, gci=0.02, lift=-1.0, resistance_std=0.5) for U in speeds}, mesh=dict(cells=1000), coarse_cells=200)
    r2 = W.free_surface_window("hull.stl", 0.1, [1.0], tmp_path, runner=runner, config={}, vehicle=v)
    assert r2["source"] == "interfoam" and r2["speeds"][1.0] == dict(resistance=10.0, gci=0.02, lift=-1.0, std=0.5)
    assert r2["cells"] == 1000 and r2["coarse_cells"] == 200 and calls == [("hull.stl", 0.1, [1.0])]


@pytest.mark.slow
def test_free_surface_window_with_the_real_interfoam_at_toy_size(tmp_path, monkeypatch):
    """cafe.cfd.free_surface on the Wigley hull, coarse level, 10 LTS iterations: proves the plumbing end to end (the numbers are
    not converged and are not checked); the production path adds the fine level and the GCI via characterize_free_surface."""
    from cafe import cfd, geom
    import numpy as _np
    monkeypatch.setattr(cfd, "NPROC", 2)
    m = geom.SAMPLES["wigley"]["make"]()
    stl = tmp_path / "wigley.stl"
    m.export(stl)
    hs = geom.hydrostatics(m, geom.SAMPLES["wigley"]["spec"]["mass"])

    def toy(stl_, draft, wd, speeds):
        out = {}
        for name, off in (("coarse", -1), ("fine", -1)):
            out[name] = cfd.free_surface(stl_, draft, wd / name, speeds, off, iters=10, log=lambda *a: None)
        for U, r in out["fine"]["speeds"].items():
            r["gci"] = cfd.gci(r["resistance"], out["coarse"]["speeds"][U]["resistance"]) if r["resistance"] else 0.0
        out["fine"]["coarse_cells"] = out["coarse"]["mesh"]["cells"]
        return out["fine"]
    U = float(0.2 * _np.sqrt(9.81 * hs["lwl"]))
    r = W.free_surface_window(stl, hs["draft"], [U], tmp_path / "fs", runner=toy)
    assert r["source"] == "interfoam" and r["cells"] > 1000 and np.isfinite(r["speeds"][U]["resistance"])


# ------------------------------------------------------------------ refit
def test_pool_random_effects():
    p = refit.pool([0.30, 0.30, 0.30], [0.01, 0.01, 0.01])
    assert p["mean"] == pytest.approx(0.30) and p["tau2"] == 0 and p["se"] == pytest.approx(0.01 / math.sqrt(3))
    q = refit.pool([0.20, 0.30, 0.40], [0.01, 0.01, 0.01])                 # windows disagree far beyond their errors
    assert q["tau2"] > 0.005 and q["mean"] == pytest.approx(0.30) and q["se"] > p["se"] * 3
    one = refit.pool([0.3], [0.02])
    assert one["tau2"] == 0 and one["se"] == pytest.approx(0.02)
    heavy = refit.pool([0.2, 0.4], [0.001, 0.1])                            # random effects: tau2 is big, so the weights even out
    assert 0.2 < heavy["mean"] < 0.3 and heavy["tau2"] > 0.01
    for bad in (([], []), ([1.0], [0.1, 0.2]), ([1.0], [0.0])):
        with pytest.raises(ValueError):
            refit.pool(*bad)


@given(st.lists(st.floats(0.05, 2.0), min_size=2, max_size=8), st.floats(0.01, 0.2))
def test_pool_mean_is_inside_the_estimates_and_scales(ms, se):
    p = refit.pool(ms, [se] * len(ms))
    assert min(ms) - 1e-9 <= p["mean"] <= max(ms) + 1e-9 and p["se"] > 0
    p2 = refit.pool([3 * m for m in ms], [3 * se] * len(ms))
    assert p2["mean"] == pytest.approx(3 * p["mean"]) and p2["se"] == pytest.approx(3 * p["se"], rel=1e-6)


def _w(cd, se, cl=0.0, cls=1e-3, ar=None):
    return dict(cd=cd, cd_spread=se, cl=cl, cl_spread=cls, added_resistance=ar)


def test_refit_builds_the_stage1_multiplier_distribution():
    wins = [_w(0.33, 0.005, 0.10, 0.01, 0.05), _w(0.36, 0.005, 0.12, 0.01, 0.08), _w(0.30, 0.005, 0.08, 0.01, 0.02)]
    r = refit.refit(wins, {"cd": 0.30, "cl": 0.1})
    assert r["drag"]["mean"] == pytest.approx(1.1, abs=0.01) and r["drag"]["change_vs_hangar"] == pytest.approx(0.1, abs=0.01)
    assert r["drag"]["sigma"] > 0.0167 and r["drag"]["windows"] == 3          # includes the between-window spread
    assert r["lift"]["mean"] == pytest.approx(1.0, abs=0.02)
    assert r["added_resistance"]["mean"] == pytest.approx(0.05) and r["added_resistance"]["sigma"] > 0
    # a hangar value twice the window value gives a multiplier of one half (units/convention check)
    assert refit.refit([_w(0.15, 0.01)], {"cd": 0.30})["drag"]["mean"] == pytest.approx(0.5)
    assert "lift" not in refit.refit([_w(0.15, 0.01)], {"cd": 0.30}) and "added_resistance" not in refit.refit([_w(0.15, 0.01)], {"cd": 0.3})
    assert refit.refit([_w(0.15, 0.01, ar=0.1)], {"cd": 0.30})["added_resistance"]["sigma"] == 0.0
    with pytest.raises(ValueError):
        refit.refit([], {"cd": 0.3})


ONE = [dict(cd=1.962, cd_spread=0.000345, cd_hangar=1.8, cl=0.0, cl_spread=1e-3, cl_hangar=None, added_resistance=None)]
FLOOR = dict(between_window_frac=0.1, between_window_source="test", discretisation_frac=0.05, discretisation_source="test")


def test_a_single_window_refit_sigma_is_floored_and_adds_the_discretisation_error():
    bare = refit.refit(ONE, floor={})
    assert bare["drag"]["sigma"] == pytest.approx(0.000345 / 1.8) and "floor" not in bare              # the batch-means error of one run: 0.02 %
    r = refit.refit(ONE, floor=FLOOR)
    m = 1.962 / 1.8
    assert r["drag"]["sigma"] == pytest.approx(math.sqrt((0.000345 / 1.8) ** 2 + (0.1 * m) ** 2 + (0.05 * m) ** 2)) and r["drag"]["sigma"] > 0.1
    assert r["drag"]["sigma_statistical"] == pytest.approx(0.000345 / 1.8) and r["drag"]["tau"] == 0.0 and r["floor"] == FLOOR
    hangar = refit.refit(ONE, dict(cd=1.8), floor=FLOOR)["drag"]                                     # the one-reference form is floored alike
    assert hangar["sigma"] == pytest.approx(r["drag"]["sigma"], rel=1e-6)
    lift = [dict(ONE[0], cl=0.2, cl_spread=0.001, cl_hangar=0.25)]
    assert refit.refit(lift, floor=FLOOR)["lift"]["sigma"] > 0.1 * 0.8
    assert refit.refit(lift, dict(cd=1.8, cl=0.25), floor=FLOOR)["lift"]["sigma"] > 0.1 * 0.8


def test_with_two_or_more_windows_the_between_window_floor_gives_way_to_the_estimated_spread_but_the_discretisation_stays():
    two = [dict(ONE[0]), dict(ONE[0], cd=1.9)]
    r = refit.refit(two, floor=FLOOR)["drag"]
    m = r["mean"]
    assert r["tau"] > 0.01 and r["sigma_between"] == pytest.approx(r["tau"]) and r["sigma_discretisation"] == pytest.approx(0.05 * m)
    assert r["sigma"] == pytest.approx(math.sqrt(r["sigma_statistical"] ** 2 + (0.05 * m) ** 2))


def test_the_default_floor_uses_the_stored_sphere_grid_study_else_says_it_is_assumed(tmp_path, monkeypatch):
    monkeypatch.setattr(nest, "SLOW_DIR", tmp_path)
    assert nest.sphere_discretisation() is None
    f = refit.default_floor()
    assert f["discretisation_frac"] == budget.stage3_assumptions()["refit.discretisation_frac"] and f["discretisation_source"].startswith("ASSUMED")
    assert f["between_window_frac"] == budget.stage3_assumptions()["refit.between_window_frac"] and refit.refit(ONE)["floor"] == f
    for d in (8, 12, 16):                                                                       # Cd(d) = 1 + 0.4 / d: first order, Cd_inf = 1
        (tmp_path / f"nest_sphere_100_d{d}.json").write_text(json.dumps(dict(d=d, cd=1 + 0.4 / d)))
    (tmp_path / "nest_sphere_1000_d24.json").write_text(json.dumps(dict(d=24, cd=0.5)))         # one grid only: no estimate from it
    e, src = nest.sphere_discretisation()
    assert e == pytest.approx(0.4 / 16, rel=0.02) and "Re = 100" in src and "[8, 12, 16]" in src
    assert "NOT in the asymptotic range" not in src                                              # first order exactly: the pairs agree
    f = refit.default_floor()
    assert e < 0.05 and f["discretisation_frac"] == 0.05 and src in f["discretisation_source"]  # a study cannot lower the assumed floor (round 7 M-9)
    assert refit.refit(ONE)["drag"]["sigma_discretisation"] == pytest.approx(0.05 * 1.962 / 1.8)


def test_verdict_changes_and_the_two_iteration_cap():
    assert refit.verdict_changes({"a": "GO", "b": "GO"}, {"a": "GO", "b": "NO-GO"}) == [("b", "GO", "NO-GO")]
    assert refit.verdict_changes({"a": "GO"}, {}) == [("a", "GO", None)]
    calls = []

    def stable(p):
        calls.append(p)
        return {"x": "GO"}
    out = refit.refit_loop(stable, lambda i: {"iter": i})
    assert out["converged"] and out["iterations"] == 1 and out["reason"] == "converged" and calls == [None, {"iter": 1}]
    flip = iter(["GO", "NO-GO", "GO", "NO-GO", "GO"])
    out = refit.refit_loop(lambda p: {"x": next(flip)}, lambda i: i)
    assert not out["converged"] and out["iterations"] == refit.MAX_ITER == 2 and out["reason"] == "cap"
    assert len(out["changes"]) == 2 and out["changes"][0] == [("x", "GO", "NO-GO")]
    seq = iter(["GO", "NO-GO", "NO-GO"])
    out = refit.refit_loop(lambda p: {"x": next(seq)}, lambda i: i)
    assert out["converged"] and out["iterations"] == 2 and out["changes"][1] == []


# ------------------------------------------------------------------ the pipeline adapter (cafe/pm/stage3/pipeline_windows.py)

VEHICLES = [dict(id="g", platform="seaglider", task=dict(dive_depth_m=500.0)), dict(id="g2", platform="slocum", task=dict(dive_depth_m=300.0)),
            dict(id="u", platform="saildrone_explorer"), dict(id="q", platform="quad_uas", base="ship")]
CLASSES = dict(g="glider", g2="glider", u="usv", q="uas")
WIN = dict(t=1.0e9, lon=-165.0, lat=0.0, stress=1.0, basis="all members")


class FakeL:
    def __init__(self):
        self.checks = {}
        self.inputs = []
        self.notes = []

    def note(self, s):
        self.notes.append(s)

    def input(self, ref, sha=None, **meta):
        self.inputs.append(str(ref))

    def check(self, name, ok, value=None, limit=None, note=""):
        self.checks[name] = (bool(ok), value, limit)
        return bool(ok)


def fake_ctx(tmp_path, budget=3e7, cpu=True, env=None, vehicles=VEHICLES, classes=CLASSES, rate=1.0):
    """A plan with no wall-clock budget (the windows get `budget` cell-steps per vehicle window, split between its parts); a test that gives it
    shares and budget_s makes the windows' sizes the stage's share at `rate` cell-updates/s, which is tiny here so that they stay toy-sized."""
    plan = dict(les=dict(cell_steps_per_window=budget, cpu_fallback=cpu, label="CPU fallback: toy", windows_per_vehicle=1, rate=rate))
    logs: list = []
    return SimpleNamespace(mission=dict(vehicles=vehicles), plan=plan, env=env or AnalyticEnv(wind=(6.0, 2.0), current=(0.3, 0.1)),
                           classes=classes, log=logs.append, run_dir=tmp_path, logs=logs)


@pytest.fixture
def no_wall_receipt(monkeypatch, tmp_path):
    monkeypatch.setattr(wm, "SLOW_DIR", tmp_path / "receipts")             # nothing stored: the wall-model check row must fail
    return tmp_path


FS = dict(R=1000.0, gci=0.04, cells=300_000, coarse=120_000, std=3.0, calls=[], spawned=[])      # what the fake interFoam returns; tests change it


def fake_interfoam(stl, draft, wd, speeds):
    """Stands in for cafe.cfd (OpenFOAM): checks that the stage handed it a real STL and returns the shape two_grid returns."""
    assert pathlib.Path(stl).stat().st_size > 1000 and draft > 2.0
    FS["calls"].append((stl, draft, list(speeds)))
    return dict(speeds={U: dict(resistance=FS["R"], gci=FS["gci"], lift=-5.0, resistance_std=FS["std"]) for U in speeds}, mesh=dict(cells=FS["cells"]),
                coarse_cells=FS["coarse"])


def in_process_fea(cmd, **kw):
    """Stands in for the child processes: runs the same entry points in this process (the real subprocess is tested once, below)."""
    import subprocess
    if "cafe.pm.stage3.freesurface" in cmd:
        FS["spawned"].append(dict(kw, cmd=cmd))
        return subprocess.CompletedProcess(cmd, fs.run_child(cmd[-3], cmd[-2], runner=fake_interfoam), "", "")
    rc = pw._fea_child(cmd[-2], cmd[-1])
    return subprocess.CompletedProcess(cmd, rc, "", "")


@pytest.fixture(autouse=True)
def fresh_fs():
    FS.update(R=1000.0, gci=0.04, cells=300_000, coarse=120_000, std=3.0)
    FS["calls"].clear()
    FS["spawned"].clear()


def cheap(monkeypatch, **over):
    base = pw.assumptions()
    base.update(dict(fea_elements_along=6, min_cells_thin_part=0), **over)             # (0: the toy sizes run the UAS arms under a cell)
    monkeypatch.setattr(pw, "assumptions", lambda: base)
    monkeypatch.setattr(pw, "_spawn", in_process_fea)
    monkeypatch.setattr(pw, "profile_stage3_s", lambda ctx: {"quick": 100.0, "overnight": 1e6})                # (the fake plans have no mission to plan with)


def test_assumptions_file_carries_every_key_the_adapter_reads():
    a = pw.assumptions()
    for k in ("window_s", "box_bodies", "cells_per_delta", "min_cells_across", "min_cells_thin_part", "min_flow_throughs", "spinup", "fea_elements_along",
              "glider.hull_diameter_m", "glider.wing_span_m", "glider.wing_chord_m", "glider.wing_thickness_m", "glider.wing_x_frac",
              "glider.hull_thickness_m", "glider.hull_material", "glider.window_depth_m", "slocum.length_m", "slocum.hull_diameter_m",
              "usv.hull_draft_m", "usv.wing_t_c", "fs.margin", "fs.cost_factor", "fs.mesh_s_per_cell", "fs.snappy_cell_factor",
              "uas.window_altitude_m", "uas.body_radii_m", "uas.arm_length_m", "uas.arm_width_m",
              "uas.arm_thickness_m"):
        assert pw.need(a, k) is not None
    import yaml
    raw = yaml.safe_load((pathlib.Path(pw.__file__).parents[3] / "config" / "assumptions.yaml").read_text())
    assert all({"value", "unit", "why", "replace_with"} <= set(v) for k, v in raw.items() if k.startswith("stage3."))
    with pytest.raises(KeyError, match="stage3.nonsense"):
        pw.need(a, "nonsense")


def test_frames_and_track_heading(tmp_path):
    R = pw.rotation(90.0, 0.0)
    assert np.allclose(R @ R.T, np.eye(3)) and np.allclose(R @ [1, 0, 0], [1, 0, 0]) and np.allclose(R @ [0, 1, 0], [0, 1, 0])   # facing east
    assert np.allclose(R @ [0, 1, 0], [0, 1, 0]) and np.allclose((R @ [0, 0, 1]), [0, 0, 1]) and np.allclose(pw.rotation(0, 0) @ [0, 1, 0], [1, 0, 0])
    Rp = pw.rotation(0.0, 30.0)                                              # nose up 30 deg while facing north: x has +z
    assert np.allclose(Rp @ [0, np.cos(np.radians(30)), np.sin(np.radians(30))], [1, 0, 0]) and np.linalg.det(Rp) == pytest.approx(1)
    assert pw.compass(1.0, 0.0) == 90.0 and pw.compass(0.0, -1.0) == 180.0 and pw.compass(-1.0, 0.0) == 270.0
    t = np.arange(5.0) * 3600
    res = dict(vehicles=dict(a=dict(t=t, lon=np.stack([-170 + 0.01 * np.arange(5)] * 3, 1), lat=np.stack([0.0 + 0.01 * np.arange(5)] * 3, 1)),
                             s=dict(t=t, lon=np.full((5, 2), -170.0), lat=np.full((5, 2), 1.0)),
                             n=dict(t=t, lon=np.full((5, 2), np.nan), lat=np.full((5, 2), 1.0)),
                             w=dict(t=t, lon=np.stack([179.9 + 0.1 * np.arange(5)] * 2, 1), lat=np.zeros((5, 2)))))
    assert pw.track_heading(res, "a", t[2]) == pytest.approx(45.0, abs=1.0)
    assert pw.track_heading(res, "w", t[2]) == pytest.approx(90.0, abs=0.5)           # across the dateline
    assert pw.track_heading(res, "s", t[2]) is None and pw.track_heading(res, "n", t[2]) is None     # stationary / no finite position
    assert pw.track_heading(res, "missing", t[2]) is None and pw.track_heading(None, "a", 0.0) is None
    res1 = dict(vehicles=dict(one=dict(t=t[:1], lon=np.zeros((1, 2)), lat=np.zeros((1, 2)))))
    assert pw.track_heading(res1, "one", 0.0) is None                                  # one record: no direction


def test_fit_window_follows_the_budget_and_the_body(monkeypatch):
    a = pw.assumptions()
    veh = pw.glider_vehicle(pg.load_platform("seaglider"), a, "seaglider", 500.0)
    big = pw.fit_window(veh, 0.25, 1e15, a)
    assert big["dx"] == pytest.approx(lbm.les_resolution(1.8, 0.25, W.NU["water"], (10,))["rows"][10]["dx"]) and big["budget_ok"]
    small = pw.fit_window(veh, 0.25, 1e8, a)
    assert small["dx"] > big["dx"] and small["cells"] < big["cells"]                   # coarser for a smaller budget
    assert small["dx"] <= veh.extra["resolve_dim"] / a["min_cells_across"] + 1e-12     # but the body keeps its cells
    assert small["steps"] >= small["min_flow_throughs_steps"] and not small["budget_ok"] == small["cell_steps"] <= 1e8
    mid = pw.fit_window(veh, 0.25, 5e12, a)
    assert big["dx"] <= mid["dx"] <= small["dx"] and mid["cell_steps"] <= 5e12 * 1.001


def test_hangar_numbers_are_the_vehicles_own_models(no_wall_receipt, monkeypatch):
    a = pw.assumptions()
    ctx = fake_ctx(no_wall_receipt)
    P = pg.load_platform("seaglider")
    veh = pw.glider_vehicle(P, a, "seaglider", 500.0)
    c = pw.glider_case(ctx, WIN, P, veh, a, 90.0)
    U = c["info"]["through_water_ms"]
    L_, D_ = pg.seaglider_force_balance(P, U, c["info"]["glide_deg"], c["info"]["alpha_deg"], 1024.0)
    assert c["cd_h"] == pytest.approx(D_ / (0.5 * 1024 * U * U * veh.ref_area)) and c["cl_h"] == pytest.approx(L_ / (0.5 * 1024 * U * U * veh.ref_area))
    assert 0.0 < U < 0.6 and c["info"]["glide_deg"] < 0 and c["info"]["alpha_deg"] > 0           # descending, positive attack angle (BS3)
    rel = c["R"] @ (c["v"] - c["u_env"])                                                          # flow relative to the body, body axes
    assert rel[0] > 0 and abs(rel[1]) < 1e-9 and "seaglider_force_balance" in c["src"]
    # heading is respected: the horizontal through-water velocity points where the glider points
    assert np.allclose((c["v"] - c["u_env"])[:2] / np.linalg.norm((c["v"] - c["u_env"])[:2]), [1.0, 0.0], atol=1e-9)
    Ps = pg.load_platform("slocum")
    vs = pw.glider_vehicle(Ps, a, "slocum", 300.0)
    cs = pw.glider_case(ctx, WIN, Ps, vs, a, None)                                                # no track: head with the current (0.3 E, 0.1 N)
    assert cs["heading"] == pytest.approx(pw.compass(0.3, 0.1)) and cs["cd_h"] > 0 and cs["cl_h"] > 0 and "slocum" in cs["src"]
    assert vs.length == a["slocum.length_m"]
    Pu = pu.load_platform("saildrone_explorer")
    hull = pw.usv_vehicle(Pu, a, "saildrone_explorer", "hull")
    ch = pw.usv_case(ctx, WIN, Pu, hull, a, 0.0, "hull")
    stw = ch["info"]["stw_ms"]
    visc = 0.5 * Pu["rho_water"] * stw ** 2 * Pu["wetted_area_m2"] * pu.cf_ittc57(stw * Pu["lwl_m"] / Pu["nu_water"]) * (1 + Pu["form_factor_k"])
    assert ch["cd_h"] * 0.5 * Pu["rho_water"] * stw ** 2 * hull.ref_area > visc and ch["cl_h"] is None        # hull friction + keel > hull friction alone
    assert "residuary" in ch["src"] and hull.fluid == "water" and (ch["R"] @ (ch["v"] - ch["u_env"]))[0] > 0
    wing = pw.usv_vehicle(Pu, a, "saildrone_explorer", "wing")
    cw = pw.usv_case(ctx, WIN, Pu, wing, a, 0.0, "wing")
    cl, cd = pu.wing_polar(Pu, Pu["wing_trim_deg"])
    assert cw["cd_h"] == pytest.approx(float(cd)) and cw["cl_h"] == pytest.approx(float(cl)) and wing.fluid == "air" and wing.length == 5.0
    vrel = cw["v"] - cw["u_env"]
    assert np.arctan2(-vrel[2], vrel[0]) == pytest.approx(np.radians(Pu["wing_trim_deg"])) and abs(vrel[1]) < 1e-12      # flow arrives at the trim angle
    Pq = uas.load_platform()
    q = pw.uas_vehicle(Pq, a, "quad_uas")
    cq = pw.uas_case(ctx, WIN, Pq, q, a, None)
    vr = np.linalg.norm(cq["v"] - cq["u_env"])
    assert cq["cd_h"] == pytest.approx(Pq["airframe"]["mass_kg"] * Pq["aero"]["d_x"] * vr / (0.5 * 1.2 * vr ** 2 * q.ref_area), rel=0.1)
    assert cq["cl_h"] is None and cq["info"]["tilt_deg"] == pytest.approx(np.degrees(np.arctan(Pq["aero"]["d_x"] * vr / 9.81)))
    assert (cq["R"] @ (cq["v"] - cq["u_env"]))[0] != 0



def uas_case_at(tmp_path, wind, heading=None):
    ctx = fake_ctx(tmp_path, env=AnalyticEnv(wind=wind, current=(0.3, 0.1)))
    a, P = pw.assumptions(), uas.load_platform()
    return P, pw.uas_case(ctx, WIN, P, pw.uas_vehicle(P, a, "quad_uas"), a, heading)


def test_a_uas_case_is_clipped_to_the_airframes_envelope_and_a_wind_beyond_it_is_refused(tmp_path):
    P = uas.load_platform()
    lim = min(P["limits"]["max_airspeed_ms"], 9.81 * np.tan(np.radians(P["limits"]["max_tilt_deg"])) / P["aero"]["d_x"])
    _, c = uas_case_at(tmp_path, (3.0, 0.0))                                                    # light wind: the nominal leg, not clipped
    assert c["info"]["leg_speed_ms"] == P["sortie"]["leg_speed_ms"] and not c["info"]["leg_clipped"] and c["info"]["v_rel_ms"] == pytest.approx(11.0)
    _, c = uas_case_at(tmp_path, (8.0, 0.0))                                                    # 8 + 8 = 16 m/s relative: past 12, so the leg slows to 4
    assert c["info"]["leg_clipped"] and c["info"]["leg_speed_ms"] == pytest.approx(4.0) and c["info"]["v_rel_ms"] == pytest.approx(lim)
    assert c["info"]["tilt_deg"] <= P["limits"]["max_tilt_deg"] and c["info"]["v_rel_limit_ms"] == pytest.approx(lim)
    with pytest.raises(ValueError, match=r"outside the UAS flight envelope: wind 14\.0 m/s .* would not be airborne"):
        uas_case_at(tmp_path, (14.0, 0.0))                                                      # the wind alone is over the limit at every ground speed
    _, c = uas_case_at(tmp_path, (14.0, 0.0), heading=90.0)                                     # flying downwind slows the relative flow into the envelope
    assert c["info"]["v_rel_ms"] <= lim + 1e-9


@settings(max_examples=60, deadline=None)
@given(st.floats(-20, 20), st.floats(-20, 20), st.floats(0, 360))
def test_a_uas_case_is_never_outside_the_envelope(wx, wy, heading):
    ctx = fake_ctx(pathlib.Path("."), env=AnalyticEnv(wind=(wx, wy), current=(0.3, 0.1)))
    a, P = pw.assumptions(), uas.load_platform()
    try:
        c = pw.uas_case(ctx, WIN, P, pw.uas_vehicle(P, a, "quad_uas"), a, heading)
    except ValueError:
        return
    assert c["info"]["v_rel_ms"] <= c["info"]["v_rel_limit_ms"] + 1e-9 and c["info"]["tilt_deg"] <= P["limits"]["max_tilt_deg"] + 1e-9
    assert 0.0 <= c["info"]["leg_speed_ms"] <= P["sortie"]["leg_speed_ms"]


def test_a_window_the_uas_cannot_fly_is_a_reasoned_row_not_a_crash(no_wall_receipt, monkeypatch):
    cheap(monkeypatch)
    r = pw.run(fake_ctx(no_wall_receipt, env=AnalyticEnv(wind=(14.0, 0.0), current=(0.3, 0.1))), {"q": [WIN]}, FakeL())["q"][0]
    assert not r["ok"] and "outside the UAS flight envelope" in r["error"] and r["reasons"] == [r["error"]] and not r["usable_for_refit"]


def test_a_uas_window_is_never_usable_for_the_refit_because_its_reference_includes_the_rotor_drag(no_wall_receipt, monkeypatch):
    cheap(monkeypatch)
    wm.channel_path().parent.mkdir(parents=True, exist_ok=True)
    wm.channel_path().write_text(json.dumps(dict(err=0.03)))
    wm.slow_path().write_text(json.dumps(dict(err=0.05)))                                       # both receipts stored and passing: nothing else blocks the row
    r = pw.run(fake_ctx(no_wall_receipt), {"q": [WIN], "g": [WIN]}, FakeL())
    q = r["q"][0]
    chk = [c for c in q["checks"] if c["name"] == "hangar_reference_comparable"]
    assert len(chk) == 1 and not chk[0]["ok"] and "rotor momentum" in chk[0]["note"] and "frame" in chk[0]["note"]
    assert not q["ok"] and not q["usable_for_refit"] and any("not usable for the refit" in x for x in q["reasons"])
    assert not [c for c in r["g"][0]["checks"] if c["name"] == "hangar_reference_comparable"] and r["g"][0]["usable_for_refit"] == r["g"][0]["ok"]
    assert "TOTAL drag" in q["cd_hangar_source"]


def _row_ok(ok, series=None, part="body"):
    r = dict(ok=ok, part=part, t=1.0e9)
    if series is not None:
        r["inflow_series"] = series
    return r


def test_no_passed_window_writes_no_calibration_and_the_ledger_says_so(tmp_path):
    out = tmp_path / "stage3" / "subgrid_calibration.json"
    out.parent.mkdir()
    out.write_text('{"source_run": "an earlier attempt"}')
    series = dict(u=[0.0], dt=1.0, U=6.0, ustar=0.3, z=10.0)
    L = FakeL()
    assert pw.recalibrate_subgrid(fake_ctx(tmp_path), {"g": [_row_ok(False, series)]}, L) is None            # a failed window's series is never used
    assert not out.exists()                                         # and a file left by an earlier attempt is not this attempt's
    assert L.notes == ["sub-grid layer uncalibrated: no LES window passed its self-checks; stage3/subgrid_calibration.json was not written"]
    assert L.checks["subgrid_calibration_written_only_from_passed_windows"] == (True, 0, 0)


def test_passed_windows_that_resolved_no_turbulence_write_nothing_and_say_why(tmp_path):
    L = FakeL()
    assert pw.recalibrate_subgrid(fake_ctx(tmp_path), {"g": [_row_ok(True)]}, L) is None
    assert not (tmp_path / "stage3" / "subgrid_calibration.json").exists()
    assert "1 window(s) passed but none carries a resolved inflow-turbulence series" in L.notes[0] and "uniform" in L.notes[0]


def test_a_passed_window_with_a_series_is_written_to_the_run_not_to_the_tracked_config(tmp_path, monkeypatch):
    """Round 3 M-23: stage 3 rewrote config/subgrid.json, which code_digest hashes, so a run that calibrated invalidated its own checkpoints and left the
    tree dirty. Its calibration is now stage3/subgrid_calibration.json of the run, and the tracked file is byte-identical afterwards."""
    shipped = sg_mod._CFG_DIR / "subgrid.json"
    before = shipped.read_bytes()
    good, bad = dict(u=[1.0], dt=1.0, U=6.0, ustar=0.3, z=10.0), dict(u=[9.0], dt=1.0, U=6.0, ustar=0.3, z=10.0)
    seen = []

    def fake(windows):
        seen.extend(windows)
        cal = dict(sg_mod.load_config()["calibration"], sigma_u_over_ustar=2.9, length_scale_factor=1.2)
        return dict(calibration=cal, uncertainty=dict(sigma_u_over_ustar=0.2, length_scale_factor=0.1), windows=[dict(label="x")], skipped=["w2: too short"])
    monkeypatch.setattr(sg_mod, "recalibrate", fake)
    L = FakeL()
    ctx = fake_ctx(tmp_path / "run_7")
    cal = pw.recalibrate_subgrid(ctx, {"g": [_row_ok(True, good), _row_ok(False, bad)]}, L)
    assert cal is not None and [w["u"] for w in seen] == [[1.0]] and seen[0]["label"] == "g body t=1000000000"
    new = json.loads((tmp_path / "run_7" / "stage3" / "subgrid_calibration.json").read_text())
    assert new["source_run"] == "stage 3 of this run (stage3/subgrid_calibration.json)" and new["sigma_u_over_ustar"] == 2.9
    assert new["uncertainty"]["sigma_u_over_ustar"] == 0.2 and new["windows"] == 1
    assert shipped.read_bytes() == before and sg_mod.load_config()["calibration"]["source_run"] is None
    assert "recalibrated from 1 passed window(s): sigma_u/u* = 2.9 +- 0.2, length_scale_factor = 1.2 +- 0.1" in L.notes[0] and "w2: too short" in L.notes[0]
    assert "stage3/subgrid_calibration.json" in L.notes[0] and "config/subgrid.json" not in L.notes[0]
    assert L.checks["subgrid_calibration_written_only_from_passed_windows"][0]


def test_the_stage_does_not_touch_the_shipped_subgrid_config_when_no_window_passed(no_wall_receipt, monkeypatch):
    cheap(monkeypatch)
    shipped = sg_mod._CFG_DIR / "subgrid.json"
    before = shipped.read_text()
    L = FakeL()
    out = pw.run(fake_ctx(no_wall_receipt), {"g": [WIN]}, L)
    assert not any(r["ok"] for rs in out.values() for r in rs)                                       # no stored wall-model receipt: nothing may pass
    assert shipped.read_text() == before and sg_mod.load_config()["calibration"]["source_run"] is None
    assert L.notes[-1].startswith("sub-grid layer uncalibrated: no LES window passed") and L.checks["subgrid_calibration_written_only_from_passed_windows"][0]


def test_run_all_classes_rows_have_everything_and_nothing_unvalidated_is_ok(no_wall_receipt, monkeypatch):
    cheap(monkeypatch)
    ctx = fake_ctx(no_wall_receipt)
    L = FakeL()
    wins = {v: [WIN] for v in CLASSES}
    out = pw.run(ctx, wins, L)
    assert {k: len(v) for k, v in out.items()} == dict(g=1, g2=1, u=3, q=1)
    assert [r["part"] for r in out["u"]] == ["hull", "wing", "hull_fs"] and out["u"][0]["fluid"] == "water" and out["u"][1]["fluid"] == "air"
    for rows in out.values():
        for r in rows:
            assert "error" not in r, r.get("error")
            for k in ("t", "lon", "lat", "fluid", "resolution", "checks", "ok", "cd", "cd_spread", "cl", "cl_spread", "added_resistance", "cd_hangar",
                      "cl_hangar", "cd_hangar_source", "fea", "label", "timing", "heading_source"):
                assert k in r
            assert np.isfinite(r["cd"]) and r["cd_hangar"] > 0 and r["timing"]["wall_s"] > 0 and r["label"].startswith("CPU fallback")
            if r["part"] != "hull_fs":                                          # interFoam has no wall-model receipt: its checks are the GCI's
                assert r["resolution"]["dx"] > 0 and "budget_ok" in r["resolution"]
                wall = [c for c in r["checks"] if c["name"] == "wall_model_receipt_error"][0]
                assert not wall["ok"] and not r["ok"]                          # no stored passing wall-model receipt: no row may be ok
            assert r["heading_source"].startswith("relative-flow") and r["added_resistance"] is not None
    assert out["g"][0]["fea"]["run"] and out["g"][0]["fea"]["utilization"] > 0                           # glider pressure hull
    assert not out["u"][0]["fea"]["run"] and "no structural model" in out["u"][0]["fea"]["reason"] and not out["q"][0]["fea"]["run"]
    assert out["g"][0]["cl_hangar"] is not None and out["u"][0]["cl_hangar"] is None and out["u"][1]["cl_hangar"] is not None
    assert L.checks["every_window_attempted"][0] and L.checks["no_row_claims_ok_with_a_failing_check"][0] and L.checks["every_window_attempted"][1] == 6
    assert any("stage3 g/body" in s for s in ctx.logs)
    assert any(f.endswith("assumptions.yaml") for f in L.inputs)             # the ledger names the numbers the rows depend on
    # the refit reads exactly these fields
    assert all("cd_hangar" in r for rows in out.values() for r in rows)


def test_both_stored_passing_receipts_clear_only_the_wall_model_row(no_wall_receipt, monkeypatch):
    cheap(monkeypatch)
    wm.channel_path().parent.mkdir(parents=True, exist_ok=True)
    sha = lbm.physics_sha()                                                    # stored by the current code (round 7 M-8)
    wm.channel_path().write_text(json.dumps(_stub_channel(err=0.03, code_sha=sha)))                          # (whole records: R9 M-4)
    plate = lambda err: json.dumps(dict(_without(_stub_plate(err=err), "force"), code_sha=sha))                # noqa: E731
    row = lambda: [c for c in pw.run(fake_ctx(no_wall_receipt), {"q": [WIN]}, FakeL())["q"][0]["checks"] if c["name"] == "wall_model_receipt_error"][0]
    assert not row()["ok"]                                                     # the channel alone does not validate a hull
    wm.slow_path().write_text(plate(0.165))
    assert not row()["ok"]                                                     # nor does it hide a failing plate
    wm.slow_path().write_text(plate(0.05))
    out = pw.run(fake_ctx(no_wall_receipt), {"q": [WIN]}, FakeL())
    r = out["q"][0]
    assert [c for c in r["checks"] if c["name"] == "wall_model_receipt_error"][0]["ok"]
    assert r["ok"] == all(c["ok"] for c in r["checks"])                         # ok is exactly "every check passed": nothing else decides it


def r_ok(out):
    return all("error" not in r for rs in out.values() for r in rs)


def test_track_heading_from_res_pkl_and_cpu_fallback_label_off(no_wall_receipt, monkeypatch):
    cheap(monkeypatch)
    t = np.array([WIN["t"] - 3600, WIN["t"], WIN["t"] + 3600])
    res = dict(vehicles=dict(q=dict(t=t, lon=np.full((3, 2), -165.0) + 0.01 * np.arange(3)[:, None], lat=np.zeros((3, 2)))))
    (no_wall_receipt / "stage1").mkdir()
    (no_wall_receipt / "stage1" / "res.pkl").write_bytes(pickle.dumps(res))
    ctx = fake_ctx(no_wall_receipt, cpu=False)
    ctx.cache = no_wall_receipt / "cache"
    import jax
    out = pw.run(ctx, {"q": [WIN]}, FakeL())
    jax.config.update("jax_compilation_cache_dir", None)
    assert jax.config.jax_persistent_cache_min_compile_time_secs == 0.0 and r_ok(out)
    r = out["q"][0]
    assert r["heading_source"] == "course over ground (no heading in res.pkl)" and r["heading_deg"] == pytest.approx(90.0, abs=0.5) and r["label"] is None
    # round 7 M-27: with a recorded bow heading the row says so (it said "stage-1 median track" whichever was used)
    res["vehicles"]["q"]["heading"] = np.full((3, 2), 80.0)
    (no_wall_receipt / "stage1" / "res.pkl").write_bytes(pickle.dumps(res))
    r = pw.run(ctx, {"q": [WIN]}, FakeL())["q"][0]
    assert r["heading_source"] == "stage-1 heading (circular median)" and r["heading_deg"] == pytest.approx(80.0, abs=0.5)


def test_windows_that_cannot_run_become_error_rows_not_crashes(no_wall_receipt, monkeypatch):
    cheap(monkeypatch)
    still = AnalyticEnv(wind=(0.0, 0.0), current=(0.0, 0.0))
    L = FakeL()
    out = pw.run(fake_ctx(no_wall_receipt, env=still), {"u": [WIN], "q": [WIN]}, L)
    assert all("error" in r and not r["ok"] and r["cd"] is None for r in out["u"])      # becalmed: no way through the water / wing below its trim minimum
    assert all("becalmed" in r["error"] for r in out["u"])
    assert "error" not in out["q"][0]                                                     # the UAS still has its own flight speed
    assert L.checks["every_window_attempted"][0]                                         # attempted, honestly failed
    real_tw = pu.through_water
    monkeypatch.setattr(pw.usv, "through_water", lambda P, w, c, h: dict(stw=1.0, track_to=90.0, leeway_deg=0.0, heel_deg=0.0))
    calm_wind = AnalyticEnv(wind=(1.0, 0.0), current=(0.0, 0.0))                          # the boat sails at the wind's speed: no apparent wind
    out = pw.run(fake_ctx(no_wall_receipt, env=calm_wind), {"u": [WIN]}, FakeL())
    assert "error" not in out["u"][0] and "trim minimum" in out["u"][1]["error"]
    monkeypatch.setattr(pw.usv, "through_water", real_tw)
    # a UAS drifting with the wind: track east at the wind speed gives no relative flow
    t = np.array([WIN["t"] - 3600, WIN["t"], WIN["t"] + 3600])
    (no_wall_receipt / "stage1").mkdir()
    (no_wall_receipt / "stage1" / "res.pkl").write_bytes(pickle.dumps(dict(vehicles=dict(
        q=dict(t=t, lon=-165.0 + 0.01 * np.arange(3)[:, None] * np.ones((1, 2)), lat=np.zeros((3, 2)))))))
    east = AnalyticEnv(wind=(8.0, 0.0))
    out = pw.run(fake_ctx(no_wall_receipt, env=east), {"q": [WIN]}, FakeL())
    assert "no relative flow" in out["q"][0]["error"]
    # a glider that cannot fly, a platform dimension missing from the assumptions, a window the memory guard refuses
    real = pg.flight
    monkeypatch.setattr(pw.glider, "flight", lambda *a, **k: SimpleNamespace(ok=np.array(False)))
    assert "stalled" in pw.run(fake_ctx(no_wall_receipt), {"g": [WIN]}, FakeL())["g"][0]["error"]
    monkeypatch.setattr(pw.glider, "flight", real)
    base = pw.assumptions()
    base.pop("glider.hull_diameter_m")
    monkeypatch.setattr(pw, "assumptions", lambda: base)
    assert "stage3.glider.hull_diameter_m" in pw.run(fake_ctx(no_wall_receipt), {"g": [WIN]}, FakeL())["g"][0]["error"]
    cheap(monkeypatch)
    monkeypatch.setattr(lbm, "device_memory_bytes", lambda: 1e3)
    assert "cells need" in pw.run(fake_ctx(no_wall_receipt), {"q": [WIN]}, FakeL())["q"][0]["error"]


def test_fea_failure_timeout_and_the_real_child_process(no_wall_receipt, monkeypatch):
    import subprocess
    real_run = subprocess.run
    cheap(monkeypatch)

    def boom(cmd, **k):
        return subprocess.CompletedProcess(cmd, 1, "", "Traceback ...\nRuntimeError: CalculiX failed: forced")

    def slow(cmd, **k):
        raise subprocess.TimeoutExpired(cmd, k["timeout"])
    monkeypatch.setattr(pw, "_spawn", boom)
    r = pw.run(fake_ctx(no_wall_receipt), {"g": [WIN]}, FakeL())["g"][0]
    assert not r["fea"]["run"] and "FEA failed: RuntimeError: CalculiX failed: forced" in r["fea"]["reason"] and r["cd"] is not None
    monkeypatch.setattr(pw, "_spawn", slow)
    r = pw.run(fake_ctx(no_wall_receipt), {"g": [WIN]}, FakeL())["g"][0]
    assert not r["fea"]["run"] and r["fea"]["reason"].startswith("killed: the FEA")
    # the real thing, once: a thin sphere shell through `python -m cafe.pm.stage3.pipeline_windows --fea`
    ball = W.Vehicle("ball", "water", 0.1, [dict(type="ellipsoid", center=(0, 0, 0), radii=(0.05, 0.05, 0.05))], material="al6061",
                     thickness=0.002, depth=0.0, extra=dict(fea=True))
    pts = _sphere_points(0.05, 200)
    monkeypatch.setattr(pw, "_spawn", real_run)
    out = pw._fea(ball, dict(wall_points=pts, wall_pressure=np.full(len(pts), 1e5)), dict(fea_elements_along=4), timeout_s=300)
    assert out["run"] and out["utilization"] > 0 and out["seconds"] > 0
    out2 = pw._fea(ball, dict(wall_points=pts, wall_pressure=np.full(len(pts), 1e5)), dict(fea_elements_along=4), timeout_s=0.05)
    assert not out2["run"] and out2["reason"].startswith("killed: the FEA")                  # a hard stop at the slice, however far gmsh/ccx got


def test_run_flags_a_row_that_claims_ok_with_a_failing_check(no_wall_receipt, monkeypatch):
    cheap(monkeypatch)
    real = pw._row

    def liar(*a, **k):
        r = real(*a, **k)
        r["ok"] = True
        return r
    monkeypatch.setattr(pw, "_row", liar)
    L = FakeL()
    pw.run(fake_ctx(no_wall_receipt), {"q": [WIN]}, L)
    assert not L.checks["no_row_claims_ok_with_a_failing_check"][0]               # the stage check catches a lying row


def test_refit_from_per_window_hangar_ratios():
    wins = [dict(cd=0.33, cd_spread=0.005, cd_hangar=0.30, cl=0.10, cl_spread=0.01, cl_hangar=0.10, added_resistance=0.05),
            dict(cd=0.66, cd_spread=0.010, cd_hangar=0.60, cl=0.2, cl_spread=0.02, cl_hangar=0.20, added_resistance=0.1),
            dict(cd=0.31, cd_spread=0.005, cd_hangar=0.30, cl=0.0, cl_spread=0.01, cl_hangar=None, added_resistance=None)]
    r = refit.refit(wins)                                                    # hangar value differs per window: ratios, not one reference
    assert r["drag"]["mean"] == pytest.approx(1.1, abs=0.03) and r["drag"]["windows"] == 3
    assert r["drag"]["change_vs_hangar"] == pytest.approx(r["drag"]["mean"] - 1)
    assert r["lift"]["windows"] == 2 and r["lift"]["mean"] == pytest.approx(1.0) and r["added_resistance"]["windows"] == 2
    one_ref = refit.refit(wins, dict(cd=0.30))                                # the single-value form would misread the 0.66/0.60 window
    assert one_ref["drag"]["mean"] > r["drag"]["mean"] + 0.2
    assert "lift" not in refit.refit([wins[2]]) and refit.refit([wins[2]])["drag"]["mean"] == pytest.approx(31 / 30)


# ------------------------------------------------------------------ wall-clock budget and reasons
def test_wall_hook_never_shortens_a_run_that_is_on_time_and_kills_one_that_overruns():
    log: dict = {}
    h = W.wall_hook(1000, 100, 20.0, 5000, log)
    assert h(100, 8.0) == 1000 and log["cut_reason"] is None and log["cells_per_s"] is None      # chunk 1 holds the compile: no rate yet
    # chunk 2 took 2 s for 100 steps: the rate is measured and reported, but 800 more steps would end at 26 s and that projection cuts nothing
    assert h(200, 10.0) == 1000 and log["run_steps"] == 1000 and log["cut_reason"] is None and log["killed"] is False
    assert log["cells_per_s"] == pytest.approx(5000 / 0.02) and log["compile_s"] == pytest.approx(6.0)
    assert h(300, 19.9) == 1000                                                 # 0.1 s inside the slice: on time
    assert h(400, 20.0) == 400 and log["run_steps"] == 400 and log["killed"] and "killed after 400 of 1000 steps" in log["cut_reason"]
    done = W.wall_hook(300, 100, 5.0, 10, {})
    done(100, 1.0)
    done(200, 2.0)
    assert done(300, 9.0) == 300                                                # past the slice but finished: nothing to kill
    log2: dict = {}
    assert W.wall_hook(1000, 100, 5.0, 10, log2)(100, 9.0) == 100 and log2["killed"] and "took 9 s" in log2["cut_reason"]     # the compile alone spent it
    assert W.wall_hook(500, 100, None, 10, {})(100, 99.0) == 500                # no kill set: never cut
    odd = W.wall_hook(250, 100, 50.0, 10, {})
    odd(100, 3.0)
    odd(200, 4.0)
    assert odd(250, 6.0) == 250                                                 # a short last chunk (it recompiles) does not break the rate


def test_run_window_under_a_wall_clock_kill_reports_what_it_stopped():
    sp = W.WindowSpec(velocity=(0.5, 0.0, 0.0), dx=0.01, steps=1200, box=(2.0, 0.8, 0.8), chunk=100, wall_s=0.001)
    r = W.run_window(HULL, sp, _uniform([0, 0, 0]))
    assert r["wall"]["run_steps"] == 100 == r["steps_run"] and r["wall"]["planned_steps"] == 1200 and r["wall"]["killed"]
    assert "killed after 100 of 1200 steps" in r["wall"]["cut_reason"]
    assert r["force"].shape == (100, 3) and r["wall"]["setup_s"] > 0 and not r["ok"]


def test_stage_share_and_reasons_for_every_check():
    assert pw.stage_share_s(SimpleNamespace(plan=dict(shares=dict(stage3=0.35), budget_s=600.0))) == pytest.approx(210.0)
    assert pw.stage_share_s(SimpleNamespace(plan={})) is None
    res = dict(dx=0.02, delta_te=0.05, y_plus_estimate=400.0)
    wl = dict(run_steps=200, planned_steps=1000, cut_reason="cut from 1000 to 200 steps")
    spec = [("mach_max", 0.12, 0.1), ("courant_max", 0.4, 0.3), ("yplus_in_30_300_fraction", 0.2, 0.9), ("force_running_mean_dev", 0.1, 0.02),
            ("mass_drift_per_step", 5e-3, 1e-3), ("interpolation_residual", 0.2, 0.05), ("sponge_clearance_cells", 2, 6),
            ("wall_model_receipt_error", math.nan, 0.2), ("nest_shift_count", 3, math.inf)]
    checks = [dict(name=n, value=v, limit=lim, ok=False) for n, v, lim in spec] + [dict(name="ok_one", value=1, limit=2, ok=True)]
    reasons = pw.why_failed(checks, res, wl)
    text = " | ".join(reasons)
    for frag in ("resolution below the rule: 2.5 cells per boundary-layer", "mach number 0.12", "courant number 0.4",
                 "y+ at the matching point outside 30-300 at 80%", "no convergence: the force running mean moves 10.0%",
                 "200 of 1000 steps run (run cut: cut from 1000 to 200", "mass changes", "residual", "2 cells from the relaxation layer",
                 "wall model unvalidated: the flat plate", "check nest_shift_count failed"):
        assert frag in text, frag
    assert len(reasons) == len(spec) + 1                                          # one sentence per failure plus the resolution rule
    fine = dict(dx=0.001, delta_te=0.05, y_plus_estimate=1)
    fl = pw.why_failed([dict(name="viscosity_floor", value=1e-4, limit=3e-6, ok=False)], fine, {})
    assert fl == ["viscosity raised to the stability floor (lattice 0.0001 instead of 3e-06): Reynolds number distorted at this dx"]
    assert "stored receipt error 70% > 20%" in pw.why_failed([dict(name="wall_model_receipt_error", value=0.7, limit=0.2, ok=False)], fine, {})[0]
    assert pw.why_failed([], res, wl, error="becalmed") == ["becalmed"]
    assert pw.why_failed([], fine, {}) == []                                       # fine grid, nothing failed: no reason


def test_a_share_too_small_for_any_window_gives_reasoned_not_run_rows_decided_by_the_plan(no_wall_receipt, monkeypatch):
    cheap(monkeypatch)
    ctx = fake_ctx(no_wall_receipt)
    ctx.plan.update(shares=dict(stage3=0.35), budget_s=10.0)                       # 3.5 s for 5 windows: 0.7 s each, below min_window_s
    L = FakeL()
    out = pw.run(ctx, {v: [WIN] for v in CLASSES}, L)
    rows = [r for rs in out.values() for r in rs]
    assert len(rows) == 6 and all(not r["ok"] and r["cd"] is None and r["reasons"] for r in rows)
    assert all(r["reasons"][0].startswith("not run: the stage-3 share of this --budget is 4 s for 5 LES windows, 0.7 s each")
               and "use a larger --budget" in r["reasons"][0] for r in rows if r["part"] != "hull_fs")
    assert [r for r in rows if r["part"] == "hull_fs"][0]["reasons"][0].startswith("free-surface window not run: estimated")     # priced, not started
    assert L.checks["every_failed_window_states_a_reason"][0] and L.checks["every_window_attempted"][0]
    assert "stage_held_its_wall_clock_share" not in L.checks and any(re.fullmatch(r"stage 3 took \d+ s of its 4 s share \(0\.\d\d x\)", n) for n in L.notes)


def slow_clock(monkeypatch, factor):
    """Every module that times a window sees time pass `factor` times faster."""
    real, t0 = time.perf_counter, time.perf_counter()
    fake = SimpleNamespace(perf_counter=lambda: t0 + factor * (real() - t0), time=lambda: t0 + factor * (real() - t0), sleep=time.sleep)
    for m in (pw, nest, W):
        monkeypatch.setattr(m, "time", fake)


def untimed(rows):
    """The rows as stage 3 hashes them: without `timing`."""
    return {v: [{k: x for k, x in r.items() if k != "timing"} for r in rs] for v, rs in rows.items()}


def toy_g_ctx(tmp, share_s):
    """One glider and a share of `share_s`: its window gets (share - FEA reserve - compile) / 1.5 seconds at 2000 cell-updates/s, a few 10^6 cells x steps."""
    ctx = fake_ctx(tmp, vehicles=VEHICLES[:1], classes=dict(g="glider"), rate=2000.0)
    ctx.plan.update(shares=dict(stage3=1.0), budget_s=share_s)
    return ctx


def test_the_sizes_of_a_window_come_from_the_plan_and_are_unchanged_when_the_clock_runs_ten_times_slower(no_wall_receipt, monkeypatch):
    cheap(monkeypatch)
    ctx = toy_g_ctx(no_wall_receipt, 2000.0)
    want = budget.stage3_plan(ctx.plan, ctx.classes, pw.assumptions())["cell_steps_per_part"]["glider"]
    assert want == pytest.approx(2000.0 * (2000.0 - 0.25 * 2000.0 - 10.0) / 1.5)
    fast = pw.run(ctx, {"g": [WIN]}, FakeL())
    slow_clock(monkeypatch, 10.0)
    slow = pw.run(toy_g_ctx(no_wall_receipt, 2000.0), {"g": [WIN]}, FakeL())
    f, s = fast["g"][0], slow["g"][0]
    assert "error" not in f and f["resolution"]["cell_steps_budget_plan"] == s["resolution"]["cell_steps_budget_plan"] == pytest.approx(want)
    assert s["timing"]["wall_s"] > 5 * f["timing"]["wall_s"] / 2                       # the clock really was slower
    assert f["resolution"]["cut_reason"] is None and s["resolution"]["cut_reason"] is None
    assert untimed(fast) == untimed(slow)                                              # dx, cells, steps, coefficients, checks, FEA: all alike
    assert f["fea"]["run"] and f["fea"]["utilization"] > 0


def test_a_clock_so_slow_that_the_slice_is_spent_kills_the_window_and_the_row_says_so(no_wall_receipt, monkeypatch):
    import subprocess
    cheap(monkeypatch)

    def spawn(cmd, **kw):  # the real child is killed at its timeout; the in-process stand-in is told to
        if kw["timeout"] is not None and kw["timeout"] <= 0:
            raise subprocess.TimeoutExpired(cmd, kw["timeout"])
        return in_process_fea(cmd, **kw)
    monkeypatch.setattr(pw, "_spawn", spawn)
    ctx = toy_g_ctx(no_wall_receipt, 2000.0)
    w2 = dict(WIN, t=WIN["t"] + 3600.0)
    ok = pw.run(ctx, {"g": [WIN, w2]}, FakeL())["g"]
    slow_clock(monkeypatch, 1e5)                                                       # one chunk of 100 steps takes longer than the whole share
    ctx2 = toy_g_ctx(no_wall_receipt, 2000.0)
    L = FakeL()
    killed, never = pw.run(ctx2, {"g": [WIN, w2]}, L)["g"]
    assert ok[0]["resolution"]["run_steps"] == ok[0]["resolution"]["planned_steps"]
    planned = ok[0]["resolution"]["planned_steps"]
    assert not killed["ok"] and killed["cut"] and killed["reasons"][0].startswith(f"killed: its wall-clock slice was spent before the {planned} planned steps")
    assert killed["resolution"]["run_steps"] is None and killed["timing"]["machine_dependent"]["run_steps"] == 100     # where it stopped is machine-dependent
    assert killed["resolution"]["planned_steps"] == planned                              # it was sized exactly as before; only its end changed
    assert killed["resolution"]["diverged"] is False                                     # the report says which of the two cut it (M-24)
    assert not never["ok"] and never["cd"] is None and never["reasons"][0].startswith("killed before it started: the stage-3 wall-clock share was spent")
    assert not killed["fea"]["run"] and killed["fea"]["reason"].startswith("not run: the LES window was cut")
    over = [n for n in L.notes if n.startswith("stage 3 took ")]           # the stage says it overran, as a note: not a check that fails the stage
    assert "stage_held_its_wall_clock_share" not in L.checks and len(over) == 1 and "over the 1.1 x allowance" in over[0] and "(killed rows)" in over[0]
    assert L.checks["every_window_attempted"][0]


def test_an_overrun_of_the_share_is_a_note_in_the_real_ledger_and_does_not_fail_the_stage(no_wall_receipt, monkeypatch, tmp_path):
    """Follow-up 2: `stage_held_its_wall_clock_share` was a ledger check, so a loaded machine failed a correct run. The overrun is stated; the budget is
    still enforced by the windows' slices and the stage deadline (the killed rows)."""
    import subprocess

    from cafe.pm import ledger
    cheap(monkeypatch)

    def spawn(cmd, **kw):
        if kw["timeout"] is not None and kw["timeout"] <= 0:
            raise subprocess.TimeoutExpired(cmd, kw["timeout"])
        return in_process_fea(cmd, **kw)
    monkeypatch.setattr(pw, "_spawn", spawn)
    slow_clock(monkeypatch, 1e5)
    ctx = toy_g_ctx(no_wall_receipt, 2000.0)
    with ledger.Ledger(tmp_path, "stage3", "h") as L:                                   # a failed check here would raise StageFailed on exit
        rows = pw.run(ctx, {"g": [WIN, dict(WIN, t=WIN["t"] + 3600.0)]}, L)["g"]
    d = json.loads((tmp_path / "checkpoints" / "stage3" / "ledger.json").read_text())
    assert d["ok"] and all(r["cut"] or r["reasons"] for r in rows) and "stage_held_its_wall_clock_share" not in {c["name"] for c in d["checks"]}
    note = next(n for n in d["notes"] if n.startswith("stage 3 took "))
    assert re.fullmatch(r"stage 3 took \d+ s of its 2000 s share \(\d+\.\d\d x\); over the 1\.1 x allowance: .*\(killed rows\)", note), note


def test_a_small_slice_runs_the_plans_size_and_the_fea_is_planned_out_when_its_reserve_is_below_the_minimum(no_wall_receipt, monkeypatch):
    cheap(monkeypatch, fea_min_s=1e9)
    ctx = toy_g_ctx(no_wall_receipt, 40.0)
    r = pw.run(ctx, {"g": [WIN]}, FakeL())["g"][0]
    assert not r["fea"]["run"] and r["fea"]["reason"].startswith("not planned: the FEA reserve is 10.0 s of a 40.0 s slice, below stage3.fea_min_s")


def test_viscosity_floor_is_reported_by_the_window_and_fails_the_row(no_wall_receipt, monkeypatch):
    air = W.Vehicle("probe", "air", 0.3, [dict(type="ellipsoid", center=(0, 0, 0), radii=(0.1, 0.04, 0.04))], ref_area=0.005)
    sp = dict(velocity=(5.0, 0.0, 0.0), dx=0.01, steps=40, box=(2.0, 0.8, 0.8))
    r0 = W.run_window(air, W.WindowSpec(**sp), _uniform([0, 0, 0]))
    r1 = W.run_window(air, W.WindowSpec(nu_floor=1e-4, **sp), _uniform([0, 0, 0]))
    assert not r0["resolution"]["nu_floored"] and r0["resolution"]["nu_lat"] == pytest.approx(r0["resolution"]["nu_lat_physical"])
    assert r1["resolution"]["nu_floored"] and r1["resolution"]["nu_lat"] == 1e-4 and r1["resolution"]["nu_lat_physical"] < 1e-4
    cheap(monkeypatch)
    q = pw.run(fake_ctx(no_wall_receipt), {"q": [WIN]}, FakeL())["q"][0]
    if q["resolution"]["nu_floored"]:
        assert any(c["name"] == "viscosity_floor" and not c["ok"] for c in q["checks"]) and any("viscosity raised" in x for x in q["reasons"])
    assert np.isfinite(q["cd"])                                                 # the floor keeps the coarse air window finite


# ------------------------------------------------------------------ the free-surface hull window (stage3/freesurface.py, pipeline_windows hull_fs)
def fs_case(tmp, ctx=None):
    a = pw.assumptions()
    P = pu.load_platform("saildrone_explorer")
    ctx = ctx or fake_ctx(tmp)
    veh = pw.usv_vehicle(P, a, "saildrone_explorer", "hull_fs")
    return ctx, a, P, veh, pw.usv_case(ctx, WIN, P, veh, a, 0.0, "hull_fs")


def keel_and_hull(P, stw):
    """Independent of the code under test: the hull's whole resistance from usv.hull_resistance and the keel's profile drag from the first term of
    usv._forces' dk, and the rudder and appendage terms of usv._forces' d, so the three can be put back together against `_forces` itself."""
    q = 0.5 * P["rho_water"] * stw ** 2
    k_area, _, _, k_tc, k_c = pu._foil(P, "keel")
    r_area, _, _, r_tc, r_c = pu._foil(P, "rudder")
    keel = q * k_area * 2 * float(pu.cf_ittc57(stw * k_c / P["nu_water"])) * (1 + 2 * k_tc + 60 * k_tc ** 4)
    rudder = q * r_area * 2 * float(pu.cf_ittc57(stw * r_c / P["nu_water"])) * (1 + 2 * r_tc + 60 * r_tc ** 4)
    return float(pu.hull_resistance(P, np.float64(stw), 0.0)), keel, rudder + q * P["appendage_cda_m2"]


def test_the_hull_fs_hangar_number_is_the_vpps_whole_hull_resistance_on_the_windows_reference_area(no_wall_receipt):
    ctx, a, P, veh, c = fs_case(no_wall_receipt)
    stw = c["info"]["stw_ms"]
    hull, keel, rest = keel_and_hull(P, stw)
    q = 0.5 * P["rho_water"] * stw ** 2
    assert c["cd_h"] == pytest.approx((hull + keel) / (q * veh.ref_area)) and c["cl_h"] is None and "residuary" in c["src"]
    d = pu._forces(P, np.float64(stw), np.float64(0.0), np.float64(0.0), np.float64(1.0), np.float64(0.0), *(np.float64(0.0),) * 4)["d"]
    assert hull + keel + rest == pytest.approx(float(d))                    # the three pieces are exactly the VPP's total at zero leeway, heel and wind
    visc = pw.usv_case(ctx, WIN, P, pw.usv_vehicle(P, a, "saildrone_explorer", "hull"), a, 0.0, "hull")
    both = pw.usv_case(ctx, WIN, P, veh, a, 0.0, "hull_fs", visc["wetted_window_m2"])    # (one surface for both; each has its own since round 7 M-10)
    resid = q * visc["wetted_window_m2"] * P["cr0"] * (stw / math.sqrt(pu.G * P["lwl_m"]) / P["cr_fr_ref"]) ** 4
    assert (both["cd_h"] - visc["cd_h"]) * q * veh.ref_area == pytest.approx(resid)    # the viscous `hull` number differs by the residuary term, nothing else
    assert visc["info"] == c["info"] and np.allclose(visc["v"], c["v"]) and veh.extra["part"] == "hull_fs" and veh.fluid == "water"


def fs_rows(tmp, monkeypatch, windows=(WIN,), ctx=None):
    cheap(monkeypatch)
    return pw.run(ctx or fake_ctx(tmp, budget=2e6), {"u": list(windows)}, FakeL())["u"]


def test_every_usv_window_gets_a_hull_fs_row_with_total_resistance_on_the_hangars_reference_area(no_wall_receipt, monkeypatch):
    w2 = dict(WIN, t=WIN["t"] + 3600.0)
    rows = fs_rows(no_wall_receipt, monkeypatch, (WIN, w2))
    assert [r["part"] for r in rows] == ["hull", "wing", "hull", "wing", "hull_fs", "hull_fs"]
    assert [r["t"] for r in rows[4:]] == [WIN["t"], w2["t"]] and len(FS["calls"]) == 2
    r, hull = rows[4], rows[0]
    P = pu.load_platform("saildrone_explorer")
    stw = r["kinematics"]["stw_ms"]
    A, q = r["ref_area"], 0.5 * P["rho_water"] * stw ** 2
    # one reference area for cd and cd_hangar
    assert A == hull["ref_area"] and A == pytest.approx(pw.usv_vehicle(P, pw.assumptions(), "x", "hull_fs").ref_area)
    assert r["cd"] == pytest.approx(FS["R"] / (q * A)) and r["resistance_n"] == FS["R"]                    # total resistance / (q A_ref), not a viscous part
    h, k, _ = keel_and_hull(P, stw)
    h = float(pu.hull_resistance(dict(P, wetted_area_m2=r["wetted_area_mesh_m2"]), np.float64(stw), 0.0))      # on the mesh's own wetted area (round 7 M-10)
    assert r["cd_hangar"] * q * A == pytest.approx(h + k)                                                    # friction (1+k) + residuary + keel
    assert r["added_resistance"] == pytest.approx(r["cd"] / r["cd_hangar"] - 1.0) and r["cl"] is None and r["cl_hangar"] is None
    assert r["source"] == "interfoam" and r["fluid"] == "water" and r["ok"] and r["reasons"] == [] and not r["fea"]["run"]
    # the spread is GCI x cd and the force's own wobble, in quadrature
    assert r["cd_spread"] == pytest.approx(math.hypot(0.04 * r["cd"], FS["std"] / (q * A))) and r["gci"] == 0.04
    assert r["refinement_ratio"] == pytest.approx((300_000 / 120_000) ** (1 / 3))
    assert [c["name"] for c in r["checks"]] == ["fs_gci", "fs_refinement_ratio", "fs_iterative_scatter"]
    assert all(c["ok"] for c in r["checks"]) and r["resolution"]["cells_fine"] == 300_000 and r["resolution"]["cells_coarse"] == 120_000
    # the stand-in mesh is 29 % over the yaml's wetted area; the row carries both and its reference is on the mesh's
    assert r["wetted_area_platform_m2"] == P["wetted_area_m2"] and 7.5 < r["wetted_area_mesh_m2"] < 9.5
    stl, draft, speeds = FS["calls"][0]
    # the through-water speed; the hull's vertical semi-axis plus the keel span below the waterline
    assert speeds == [pytest.approx(stw)] and draft == pytest.approx(0.45 + P["keel_span_m"], abs=1e-4)
    sp = FS["spawned"][0]
    assert sp["start_new_session"] is True and sp["cmd"][1:3] == ["-m", "cafe.pm.stage3.freesurface"]
    assert float(sp["cmd"][-1]) == 1e9                                       # no budget: no deadline


@pytest.mark.parametrize("gci, cells, coarse, failing, words", [
    (None, 300_000, 120_000, "fs_gci", "no grid-convergence index"),
    (float("nan"), 300_000, 120_000, "fs_gci", "no grid-convergence index"),
    (0.11, 300_000, 120_000, "fs_gci", "grid-convergence index 11% is above 10%"),                  # a GCI that large is not information
    (0.10, 300_000, 120_000, None, None),
    (0.04, 130_000, 120_000, "fs_refinement_ratio", "refinement ratio r = 1.03 (cells 130,000 / 120,000) is below 1.3"),
    (0.04, 263_000, 120_000, "fs_refinement_ratio", "r = 1.30"),                                      # 2.19x the cells is r = 1.2986: still below
    (0.04, 264_000, 120_000, None, None)])                                                           # 2.2x is r = 1.3006: passes
def test_a_missing_gci_or_a_refinement_ratio_below_1_3_fails_the_row_and_says_why(no_wall_receipt, monkeypatch, gci, cells, coarse, failing, words):
    FS.update(gci=gci, cells=cells, coarse=coarse)
    r = fs_rows(no_wall_receipt, monkeypatch)[-1]
    assert r["cd"] > 0 and r["cd_spread"] > 0
    assert [c["name"] for c in r["checks"] if not c["ok"]] == ([failing] if failing else [])
    assert r["ok"] is (failing is None)
    if failing:
        assert any(words in x for x in r["reasons"]) and len(r["reasons"]) == 1
    else:
        assert r["reasons"] == [] and r["refinement_ratio"] >= 1.3


def test_the_fluidx3d_plugin_replaces_interfoam_when_enabled_and_stays_off_by_default(no_wall_receipt, monkeypatch, tmp_path):
    assert fluidx3d.available(fs.fluidx3d_config())[0] is False                      # config/premission.json as shipped: disabled
    cheap(monkeypatch)
    f = tmp_path / "premission.json"
    f.write_text(json.dumps(cfg()))
    monkeypatch.setattr(fs, "CONFIG_FILE", f)
    ctx = fake_ctx(no_wall_receipt, budget=2e6)
    ctx.plan.update(shares={"stage3": 0.3}, budget_s=1200.0)                         # quick: 6 min, which interFoam could never fit (see below)
    r = pw.run(ctx, {"u": [WIN]}, FakeL())["u"][-1]
    assert r["part"] == "hull_fs" and r["source"] == "fluidx3d" and FS["calls"] == []                  # the fake interFoam was never called
    assert r["cd"] > 0 and r["resolution"]["estimate"] is None and r["gci"] is None
    assert not r["ok"] and r["reasons"][0].startswith("no grid-convergence index")                    # a lattice-Boltzmann free surface has no second grid
    f.write_text(json.dumps(cfg(enabled=False)))
    r2 = pw.run(ctx, {"u": [WIN]}, FakeL())["u"][-1]
    assert "source" not in r2 and r2["reasons"][0].startswith("free-surface window not run: estimated") and FS["calls"] == []


def plan_with(ctx, share_s):
    ctx.plan.update(shares={"stage3": 0.3}, budget_s=share_s / 0.3)
    return ctx


def test_the_share_decides_whether_a_free_surface_case_runs_and_a_second_one_queues_behind_the_first(no_wall_receipt, monkeypatch):
    monkeypatch.setenv("CAFE_NPROC", "6")
    a = pw.assumptions()
    est = fs.estimate(6, a["fs.snappy_cell_factor"], a["fs.cost_factor"], a["fs.mesh_s_per_cell"])
    need = est["total_s"] * a["fs.margin"]
    w2 = dict(WIN, t=WIN["t"] + 3600.0)
    # a share one third short of the estimate: not run, with the numbers
    rows = fs_rows(no_wall_receipt, monkeypatch, ctx=plan_with(fake_ctx(no_wall_receipt, budget=2e6), 0.66 * need))
    r = rows[-1]
    assert not r["ok"] and r["cd"] is None and FS["spawned"] == [] and r["error"] == r["reasons"][0]
    assert f"estimated {est['total_s'] / 60:.0f} min x {a['fs.margin']} margin = {need / 60:.0f} min" in r["reasons"][0]
    assert f"of the {0.66 * need / 60:.0f} min stage-3 share" in r["reasons"][0] and "iterations" in r["reasons"][0] and "cell-updates/s" in r["reasons"][0]
    assert "it would fit --budget " in r["reasons"][0] and r["resolution"]["estimate"]["total_s"] == pytest.approx(est["total_s"])
    # a share 1.5 times the need: one case fits, the second window finds only the rest of the share
    rows = fs_rows(no_wall_receipt, monkeypatch, (WIN, w2), ctx=plan_with(fake_ctx(no_wall_receipt, budget=2e6), 1.5 * need))
    first, second = rows[-2], rows[-1]
    assert first["ok"] and len(FS["spawned"]) == 1 and first["resolution"]["estimated_s"] == pytest.approx(est["total_s"])
    left = float(re.search(r"against ([\d.]+) min left", second["reasons"][0]).group(1))
    assert not second["ok"] and second["cd"] is None and left == pytest.approx(0.5 * need / 60, abs=1.0)           # the rest of the share, not all of it
    # a share of three times the need holds both
    FS["spawned"].clear()
    rows = fs_rows(no_wall_receipt, monkeypatch, (WIN, w2), ctx=plan_with(fake_ctx(no_wall_receipt, budget=2e6), 3.0 * need + 5.0))
    assert rows[-2]["ok"] and rows[-1]["ok"] and len(FS["spawned"]) == 2
    assert 0.0 < float(FS["spawned"][0]["cmd"][-1]) <= 3.0 * need + 5.0                 # the child's own deadline lies inside the share


def test_the_free_surface_go_no_go_is_the_plans_and_does_not_depend_on_the_clock(no_wall_receipt, monkeypatch):
    monkeypatch.setenv("CAFE_NPROC", "6")
    a = pw.assumptions()
    need = fs.estimate(6, a["fs.snappy_cell_factor"], a["fs.cost_factor"], a["fs.mesh_s_per_cell"])["total_s"] * a["fs.margin"]
    for factor in (1.0, 200.0):                                                          # a second to spare: the old rule spent it on the clock
        FS["spawned"].clear()
        slow_clock(monkeypatch, factor)
        r = fs_rows(no_wall_receipt, monkeypatch, ctx=plan_with(fake_ctx(no_wall_receipt, budget=2e6), need + 1.0))[-1]
        assert r["ok"] and len(FS["spawned"]) == 1, factor
    for factor in (1.0, 200.0):                                                          # a second short: no, whatever the clock
        FS["spawned"].clear()
        slow_clock(monkeypatch, factor)
        r = fs_rows(no_wall_receipt, monkeypatch, ctx=plan_with(fake_ctx(no_wall_receipt, budget=2e6), need - 1.0))[-1]
        assert not r["ok"] and r["reasons"][0].startswith("free-surface window not run: estimated") and FS["spawned"] == [], factor


def test_the_named_budgets_quick_does_not_fit_a_free_surface_window_and_overnight_fits_one(no_wall_receipt, monkeypatch):
    from cafe.pm import budget
    monkeypatch.setenv("CAFE_NPROC", "6")
    a = pw.assumptions()
    est = fs.estimate(6, a["fs.snappy_cell_factor"], a["fs.cost_factor"], a["fs.mesh_s_per_cell"])
    assert sum(est["cells"].values()) == pytest.approx(0.98 * (fs.refined_cells(1) + fs.refined_cells(4)))
    share = {k: budget.SHARE["stage3"] * v for k, v in budget.BUDGET_S.items()}
    need = est["total_s"] * a["fs.margin"]
    assert need > share["quick"] and need > share["4h"] and need < share["overnight"] < 2 * need                  # quick, 4h: no; overnight: exactly one
    ctx = fake_ctx(no_wall_receipt, budget=2e6)
    ctx.plan.update(shares=budget.SHARE, budget_s=budget.BUDGET_S["quick"])
    r = fs_rows(no_wall_receipt, monkeypatch, ctx=ctx)[-1]
    assert not r["ok"] and f"of the {share['quick'] / 60:.0f} min stage-3 share" in r["reasons"][0] and "it would fit --budget overnight" in r["reasons"][0]


def test_the_hull_fs_row_failures_are_rows_with_reasons(no_wall_receipt, monkeypatch, tmp_path):
    import subprocess
    ctx, a, P, veh, case = fs_case(no_wall_receipt)
    base = pw._base(ctx, WIN, "hull_fs")
    geo = dict(draft=2.55, length=6.5, area=20.0, wetted_hull_m2=8.4)
    seen: list = []

    def out(cmd, R=1000.0, gci=0.05):
        res = dict(speeds={"2.5": dict(resistance=R, gci=gci, lift=None, std=1.0)}, cells=3, coarse_cells=1, source="interfoam")  # std 0.1 % of R: converged
        pathlib.Path(cmd[-2]).write_text(json.dumps(res))
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def work(spawn, deadline=None):
        (tmp_path / "out.json").unlink(missing_ok=True)

        def rec(cmd, **k):
            seen.append(k)
            return spawn(cmd, **k)
        monkeypatch.setattr(pw, "_spawn", rec)
        return pw._fs_work(base, veh, case, 2.5, geo, str(tmp_path), {}, None, deadline, time.perf_counter())

    def timeout(cmd, **k):
        raise subprocess.TimeoutExpired(cmd, k["timeout"])

    def nopython(cmd, **k):
        raise FileNotFoundError("no python")
    soon = time.perf_counter() + 50.0
    for spawn, deadline, words in [
            (timeout, soon, "killed at its deadline"),
            (lambda cmd, **k: subprocess.CompletedProcess(cmd, 3, "", "Traceback\nRuntimeError: snappy: forced"), None,
             "failed (3): RuntimeError: snappy: forced"),
            (lambda cmd, **k: subprocess.CompletedProcess(cmd, -9, "", ""), soon, "killed by its watchdog"),
            (lambda cmd, **k: subprocess.CompletedProcess(cmd, 0, "", ""), None, "failed (0): no message"),
            (lambda cmd, **k: out(cmd, R=-4.0), None, "non-physical resistance (-4.0 N)"),
            (nopython, None, "window failed: no python"),
            (lambda cmd, **k: out(cmd), time.perf_counter() - 1.0, "share was spent before its turn came")]:
        r = work(spawn, deadline)
        assert not r["ok"] and r["cd"] is None and words in r["reasons"][0] and r["error"] == r["reasons"][0] and r["part"] == "hull_fs", words
    # the parent waits a grace past the child's own deadline, and for ever without one
    assert seen[0]["timeout"] == pytest.approx(50.0 + pw.FS_GRACE_S, abs=1.0) and seen[1]["timeout"] is None
    assert len(seen) == 6                                                    # the spent deadline never starts a child
    good = work(lambda cmd, **k: out(cmd))
    assert good["ok"] and good["gci"] == 0.05 and good["refinement_ratio"] == pytest.approx(3 ** (1 / 3)) and good["cd"] > 0


def test_a_free_surface_case_that_cannot_be_prepared_is_a_row_with_the_reason_and_leaves_no_job_directory(no_wall_receipt, monkeypatch):
    import glob
    before = set(glob.glob(f"{tempfile.gettempdir()}/fs_job_*"))

    def refuse(veh, path):
        raise ValueError("the hull and keel do not union into a closed solid")
    monkeypatch.setattr(fs, "write_stl", refuse)
    rows = fs_rows(no_wall_receipt, monkeypatch)
    assert rows[-1]["part"] == "hull_fs" and rows[-1]["reasons"] == ["the hull and keel do not union into a closed solid"] and FS["spawned"] == []
    assert set(glob.glob(f"{tempfile.gettempdir()}/fs_job_*")) == before             # the job directory goes with the failed preparation ...
    monkeypatch.undo()
    cheap(monkeypatch)
    pw.run(fake_ctx(no_wall_receipt, budget=2e6), {"u": [WIN]}, FakeL())
    assert set(glob.glob(f"{tempfile.gettempdir()}/fs_job_*")) == before             # ... and with the finished run


def test_a_becalmed_usv_gets_a_hull_fs_row_that_says_so(no_wall_receipt, monkeypatch):
    still = AnalyticEnv(wind=(0.0, 0.0), current=(0.0, 0.0))
    r = fs_rows(no_wall_receipt, monkeypatch, ctx=fake_ctx(no_wall_receipt, env=still))[-1]
    assert r["part"] == "hull_fs" and "becalmed" in r["reasons"][0] and not r["ok"] and FS["spawned"] == []


# ------------------------------------------------------------------ freesurface.py on its own
def test_the_stl_is_one_closed_solid_with_its_lowest_point_at_zero_and_the_waterline_at_the_draft(tmp_path):
    import trimesh
    a, P = pw.assumptions(), pu.load_platform("saildrone_explorer")
    veh = pw.usv_vehicle(P, a, "saildrone_explorer", "hull_fs")
    info = fs.write_stl(veh, tmp_path / "h.stl")
    m = trimesh.load(tmp_path / "h.stl", force="mesh")
    assert m.is_watertight and len(m.split(only_watertight=False)) == 1 and m.bounds[0][2] == pytest.approx(0.0, abs=1e-6)
    assert info["draft"] == pytest.approx(a["usv.hull_draft_m"] + P["keel_span_m"], abs=1e-4) and info["length"] == pytest.approx(P["lwl_m"], abs=0.05)
    # the ellipsoid's top is a hull semi-axis above the waterline
    assert m.bounds[1][2] == pytest.approx(info["draft"] + a["usv.hull_draft_m"], abs=1e-2)
    assert info["area"] == pytest.approx(m.area) and 0.9 * P["wetted_area_m2"] < info["wetted_hull_m2"] < 1.5 * P["wetted_area_m2"]
    kc = P["keel_area_m2"] / P["keel_span_m"]
    hull_only = W.vehicle_mesh(veh, 0)
    assert m.volume > hull_only.volume + 0.5 * kc * P["keel_t_c"] * kc * P["keel_span_m"]                  # the keel is in it ...
    # ... once: its overlap with the hull is not added
    assert m.volume < hull_only.volume + kc * P["keel_t_c"] * kc * (P["keel_span_m"] + 0.25 * a["usv.hull_draft_m"])


def test_a_union_that_is_not_a_closed_solid_is_refused(tmp_path, monkeypatch):
    import trimesh
    open_box = trimesh.creation.box(extents=(1, 1, 1))
    open_box.update_faces(np.arange(len(open_box.faces)) != 0)
    monkeypatch.setattr(trimesh.boolean, "union", lambda bodies, engine=None: open_box)
    veh = pw.usv_vehicle(pu.load_platform("saildrone_explorer"), pw.assumptions(), "saildrone_explorer", "hull_fs")
    with pytest.raises(ValueError, match="do not union into a closed solid"):
        fs.write_stl(veh, tmp_path / "h.stl")


def test_zlayers_and_the_refined_cell_count_follow_the_cfd_recipe():
    from cafe import cfd
    zl = fs.zlayers()
    assert len(zl) == sum(cfd.FS_NZ) == 86 and sum(w for _, w in zl) == pytest.approx(cfd.FS_Z[-1] - cfd.FS_Z[0])
    assert zl[0][0] == pytest.approx(cfd.FS_Z[0] + zl[0][1] / 2) and zl[-1][0] == pytest.approx(cfd.FS_Z[-1] - zl[-1][1] / 2)
    assert zl[23][1] / zl[0][1] == pytest.approx(cfd.FS_GRADE[0])                                            # first block: last cell / first cell = the grading
    assert all(zl[i][0] < zl[i + 1][0] for i in range(85))
    nx, ny = int((cfd.FS_DOMAIN[1] - cfd.FS_DOMAIN[0]) / cfd.FS_H0), int(-cfd.FS_DOMAIN[2] / cfd.FS_H0)
    assert fs.refined_cells(0) == nx * ny * 86 == 44_032
    dx, dy = (cfd.FS_DOMAIN[1] - cfd.FS_DOMAIN[0]) / nx, -cfd.FS_DOMAIN[2] / ny
    x0, x1, by, z0, z1 = cfd.FS_BOXES[0]
    inside = sum(1 for z, _ in zl if z0 <= z <= z1)
    assert fs.refined_cells(1) - fs.refined_cells(0) == pytest.approx(3 * inside * (x1 - x0) * (by + 0.01) / (dx * dy))     # each box cell becomes four
    c = [fs.refined_cells(n) for n in range(5)]
    assert all(c[i] < c[i + 1] for i in range(4))
    # measured on homebase 2026-10-29 with the Explorer's hull and keel, snappy surface level 0 (cells after checkMesh): the estimate is within 3 %
    for n, cells in {1: 70_585, 2: 101_615, 3: 143_996, 4: 209_085}.items():
        assert 0.98 * fs.refined_cells(n) == pytest.approx(cells, rel=0.03), n


def test_the_grid_pair_has_a_refinement_ratio_of_at_least_1_3_by_construction():
    from cafe.pm import vv
    a = pw.assumptions()
    est = fs.estimate(6, a["fs.snappy_cell_factor"], a["fs.cost_factor"], a["fs.mesh_s_per_cell"])
    assert vv.refinement_ratio(est["cells"]["fine"], est["cells"]["coarse"]) >= vv.R_MIN + 0.1
    assert vv.refinement_ratio(fs.refined_cells(3), fs.refined_cells(4)) < vv.R_MIN                         # the app's own pair (boxes 3 and 4) could not pass


def test_the_rate_is_interpolated_between_the_measured_core_counts():
    meas = json.loads((pathlib.Path(pw.__file__).parents[3] / "config" / "throughput.json").read_text())[fs.SOLVER]["cell_updates_per_s"]
    assert fs.rate(4)[0] == pytest.approx(meas["4"]) and fs.rate(1)[0] == pytest.approx(meas["1"]) and fs.rate(16)[0] == pytest.approx(meas["8"])
    r6, src = fs.rate(6)
    assert meas["4"] < r6 < meas["8"] and r6 == pytest.approx(0.5 * (meas["4"] + meas["8"])) and "interpolated to 6" in src and fs.SOLVER in src


def test_the_estimate_is_cells_x_iterations_over_the_rate_times_the_measured_factor_plus_meshing():
    from cafe.pm import dtmb5415
    e = fs.estimate(4, 0.98, 2.0, 1e-3)
    cells = sum(e["cells"].values())
    assert set(e["cells"]) == {"coarse", "fine"} and cells == pytest.approx(0.98 * (fs.refined_cells(1) + fs.refined_cells(4)))
    assert e["iters"] == dtmb5415.ITERS and e["cores"] == 4 and e["rate"] == pytest.approx(fs.rate(4)[0])
    assert e["solve_s"] == pytest.approx(2.0 * cells * e["iters"] / e["rate"]) and e["mesh_s"] == pytest.approx(1e-3 * cells)
    assert e["total_s"] == pytest.approx(e["solve_s"] + e["mesh_s"])
    assert fs.estimate(8, 0.98, 2.0, 1e-3)["solve_s"] < e["solve_s"] < fs.estimate(1, 0.98, 2.0, 1e-3)["solve_s"]       # more cores, less time


def test_the_smallest_budget_profile_whose_plan_holds_the_estimate_is_named():
    prof = {"ci": 360.0, "quick": 360.0, "4h": 4320.0, "overnight": 10800.0}
    assert fs.fitting_budget(300, prof) == "--budget ci (6 min of stage 3 in that plan)" and fs.fitting_budget(361, prof).startswith("--budget 4h")
    assert fs.fitting_budget(5000, prof) == "--budget overnight (180 min of stage 3 in that plan)"
    assert fs.fitting_budget(11000, prof) == "no --budget profile's plan holds it (the largest gives 180 min)"
    assert fs.fitting_budget(1, {}) == "no --budget profile's plan holds it (the largest gives 0 min)"


def test_review_round_6_m14_each_profile_is_judged_by_its_own_plan_not_by_the_running_plans_share(monkeypatch):
    """The demo at 6 cores: the quick and 4h plans give stage 3 nothing (their LES slices went to stage 1), overnight's gives 118 min, so a 117 min case
    fits overnight and a 10 h case fits none. The running plan's share (0 at quick) times each budget said "no profile" for both."""
    from cafe.pm import config, stage1
    monkeypatch.setenv("CAFE_NPROC", "6")
    m = config.load_mission("missions/tepex_c_demo.yaml")
    ctx = SimpleNamespace(mission=m, classes=stage1._classes(m), plan=dict(gpus=0, workers=6, mem_gb=None, env_gb=None, les={}))
    s = pw.profile_stage3_s(ctx)
    assert s["quick"] == 0.0 and s["4h"] == 0.0 and 100 * 60 < s["overnight"] < budget.SHARE["stage3"] * budget.BUDGET_S["overnight"]
    assert list(s) == sorted(s, key=budget.BUDGET_S.get)
    assert fs.fitting_budget(117 * 60, s) == f"--budget overnight ({s['overnight'] / 60:.0f} min of stage 3 in that plan)"
    assert fs.fitting_budget(36000, s) == f"no --budget profile's plan holds it (the largest gives {s['overnight'] / 60:.0f} min)"
    real = budget.plan

    def refuse_ci(name, *args, **kw):
        if name == "ci":
            raise budget.PlanError("stage 1 cannot run in it")
        return real(name, *args, **kw)
    monkeypatch.setattr(budget, "plan", refuse_ci)
    assert "ci" not in pw.profile_stage3_s(ctx) and "quick" in pw.profile_stage3_s(ctx)                 # a profile that cannot run holds nothing


def test_nproc_follows_the_environment(monkeypatch):
    monkeypatch.setenv("CAFE_NPROC", "3")
    assert fs.nproc() == 3
    monkeypatch.delenv("CAFE_NPROC")
    monkeypatch.setenv("CAFE_WORKERS", "16")
    assert fs.nproc() == 6                                                                  # the measured knee caps it


def test_two_grid_runs_the_coarse_and_fine_cases_and_puts_the_gci_at_the_measured_ratio(tmp_path, monkeypatch):
    from cafe import cfd
    from cafe.pm import dtmb5415, vv
    calls = []

    def fake(stl, draft, case, speeds, off, iters, log, surf_level):
        calls.append((off, iters, surf_level, pathlib.Path(case).name))
        n, R = (70_000, 1100.0) if off == -3 else (210_000, 1000.0)
        return dict(mesh=dict(cells=n), speeds={U: dict(resistance=R, lift=-1.0, resistance_std=2.0) for U in speeds})
    monkeypatch.setattr(cfd, "free_surface", fake)
    monkeypatch.setattr(cfd, "_shrink", lambda case: calls.append(("shrink", pathlib.Path(case).name)))
    r = fs.two_grid("h.stl", 2.55, tmp_path, [2.5, 3.0])
    assert calls == [(-3, dtmb5415.ITERS, 0, "coarse"), ("shrink", "coarse"), (0, dtmb5415.ITERS, 0, "fine"), ("shrink", "fine")]
    rr = (210_000 / 70_000) ** (1 / 3)
    assert r["refinement_ratio"] == pytest.approx(rr) and r["ratio_below_1_3"] is False and r["coarse_cells"] == 70_000 and r["mesh"]["cells"] == 210_000
    assert set(r["speeds"]) == {2.5, 3.0} and r["speeds"][2.5]["gci"] == pytest.approx(cfd.gci(1000.0, 1100.0, ratio=rr))
    assert r["speeds"][2.5]["gci"] == pytest.approx(vv.gci_two_grid(1000.0, 1100.0, rr))                     # Roache at the measured r, not at 2


def test_run_child_writes_what_free_surface_window_returns(tmp_path):
    stl = tmp_path / "h.stl"
    stl.write_bytes(b"x" * 2000)
    job, out = tmp_path / "job.json", tmp_path / "out.json"
    job.write_text(json.dumps(dict(stl=str(stl), draft=2.55, speeds=[2.5], config={}, vehicle=None)))
    assert fs.run_child(str(job), str(out), runner=fake_interfoam) == 0
    r = json.loads(out.read_text())
    assert r["source"] == "interfoam" and r["speeds"]["2.5"]["resistance"] == FS["R"] and r["cells"] == 300_000 and r["coarse_cells"] == 120_000
    assert r["speeds"]["2.5"]["std"] == FS["std"] and FS["calls"][0][2] == [2.5]


def test_row_fields_checks_and_reasons():
    r = dict(speeds={2.0: dict(resistance=500.0, gci=0.1, lift=3.0, std=1e-9)}, cells=250, coarse_cells=100)
    f = fs.row_fields(r, 2.0, 1000.0, 0.5, 0.2)
    assert f["cd"] == pytest.approx(500.0 / (0.5 * 1000 * 4.0 * 0.5)) == pytest.approx(0.5) and f["cd_spread"] == pytest.approx(0.05)
    assert f["added_resistance"] == pytest.approx(0.5 / 0.2 - 1) and f["vertical_force_n"] == 3.0 and all(c["ok"] for c in f["checks"])
    assert f["refinement_ratio"] == pytest.approx(2.5 ** (1 / 3)) and fs.reasons(f["checks"], f["refinement_ratio"], (250, 100)) == []
    bad = fs.row_fields(dict(r, cells=None), 2.0, 1000.0, 0.5, 0.2)
    assert [c["name"] for c in bad["checks"] if not c["ok"]] == ["fs_refinement_ratio"]
    assert fs.reasons(bad["checks"], None, (None, 100)) == ["refinement ratio unknown (no cell counts)"]
    nogci = fs.row_fields(dict(r, speeds={2.0: dict(resistance=500.0, gci=None, std=0.0)}), 2.0, 1000.0, 0.5, 0.2)
    assert nogci["gci"] is None and nogci["cd_spread"] == 1e-12 and [c["name"] for c in nogci["checks"] if not c["ok"]] == ["fs_gci"]
    for std, ok in ((10.0, True), (10.01, False), (None, False)):                                     # 2 % of 500 N is the limit
        f = fs.row_fields(dict(r, speeds={2.0: dict(resistance=500.0, gci=0.1, std=std)}), 2.0, 1000.0, 0.5, 0.2)
        assert [c["ok"] for c in f["checks"] if c["name"] == "fs_iterative_scatter"] == [ok]
        assert ok or "not converged" in fs.reasons(f["checks"], 1.36, (250, 100))[0] or "no force history" in fs.reasons(f["checks"], 1.36, (250, 100))[0]
    for R in (0.0, -1.0, math.nan, math.inf):
        with pytest.raises(ValueError, match="non-physical"):
            fs.row_fields(dict(r, speeds={2.0: dict(resistance=R, gci=0.1)}), 2.0, 1000.0, 0.5, 0.2)


def test_the_watchdog_kills_the_group_it_leads_else_only_itself(monkeypatch):
    calls = []
    monkeypatch.setattr(os, "killpg", lambda g, sig: calls.append(("group", g, sig)))
    monkeypatch.setattr(os, "kill", lambda p, sig: calls.append(("pid", p, sig)))
    monkeypatch.setattr(os, "getpid", lambda: 77)
    monkeypatch.setattr(os, "getpgrp", lambda: 77)
    fs.arm_watchdog(0.01).join(5)
    monkeypatch.setattr(os, "getpgrp", lambda: 5)
    fs.arm_watchdog(0.01).join(5)
    assert calls == [("group", 77, 9), ("pid", 77, 9)]


def test_a_child_killed_by_its_watchdog_takes_everything_in_its_process_group_with_it():
    import subprocess
    import sys
    code = ("import subprocess, time\nfrom cafe.pm.stage3 import freesurface as f\nf.arm_watchdog(1.0)\n"
            "p = subprocess.Popen(['sleep', '120'])\nprint(p.pid, flush=True)\ntime.sleep(120)\n")
    t0 = time.time()
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, start_new_session=True, timeout=60,
                       cwd=str(pathlib.Path(pw.__file__).resolve().parents[3]))
    assert r.returncode == -9 and time.time() - t0 < 30
    time.sleep(0.3)
    try:
        state = pathlib.Path(f"/proc/{int(r.stdout.split()[0])}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except FileNotFoundError:
        state = "gone"
    assert state in ("gone", "Z", "X"), f"the grandchild is still running ({state})"


@pytest.mark.slow
def test_the_unioned_hull_meshes_and_solves_in_openfoam_at_toy_size(tmp_path, monkeypatch):
    """The real OpenFOAM on the real stl of the Explorer's hull + keel: the coarse grid (one refinement box, surface level 0), five LTS iterations.
    It proves that blockMesh -> refineMesh -> snappyHexMesh accepts the unioned solid and that interFoam runs on it; the numbers are not converged."""
    from cafe import cfd
    monkeypatch.setattr(cfd, "NPROC", 2)
    a, P = pw.assumptions(), pu.load_platform("saildrone_explorer")
    info = fs.write_stl(pw.usv_vehicle(P, a, "saildrone_explorer", "hull_fs"), tmp_path / "h.stl")
    r = cfd.free_surface(str(tmp_path / "h.stl"), info["draft"], tmp_path / "case", [2.0], -3, iters=5, log=lambda *x: None, surf_level=0)
    assert 0.9 * 70_585 < r["mesh"]["cells"] < 1.1 * 70_585 and np.isfinite(r["speeds"][2.0]["resistance"]) and r["half"]


# ---------------------------------------------------------------------------------------------------------------- review round 2: M-5, M-8, M-26

def test_a_cut_window_withholds_every_machine_dependent_number_so_two_cut_points_give_the_same_rows(no_wall_receipt, monkeypatch):
    """M-5: the chunk the clock cut a run at changes cd and every check value; none of them may be in the hashed row."""
    cheap(monkeypatch)

    def run_cut(step_s):                                  # nest's clock advances `step_s` per reading: chunk k ends at k x step_s
        tick = iter(range(1, 10 ** 6))
        monkeypatch.setattr(nest, "time", SimpleNamespace(perf_counter=lambda: step_s * next(tick), time=time.time, sleep=time.sleep))
        return pw.run(toy_g_ctx(no_wall_receipt, 2000.0), {"g": [WIN]}, FakeL())
    early, late = run_cut(2000.0), run_cut(600.0)         # the slice is about 1500 s: cut after chunk 1, or after chunk 3
    e, l = early["g"][0], late["g"][0]
    assert e["cut"] and l["cut"] and not e["ok"] and not l["ok"] and e["resolution"]["planned_steps"] > 300
    assert e["timing"]["machine_dependent"]["run_steps"] == 100 and l["timing"]["machine_dependent"]["run_steps"] == 300
    assert untimed(early) == untimed(late)                                              # equal hashed rows
    for r in (e, l):
        assert r["cd"] is None and r["cl"] is None and r["cd_spread"] is None and r["resolution"]["run_steps"] is None
        assert not any(c["name"] in ("mach_max", "force_running_mean_dev") for c in r["checks"])          # solver check values are withheld too
        assert {"cd", "cd_spread", "cl", "cl_spread", "checks"} <= set(r["timing"]["machine_dependent"])
        assert "withheld" in r["reasons"][0] and r["usable_for_refit"] is False
    assert e["timing"]["machine_dependent"]["cd"] != l["timing"]["machine_dependent"]["cd"]       # the numbers do differ; they are just not hashed


def test_a_run_that_is_not_cut_has_cut_false_and_keeps_its_numbers(no_wall_receipt, monkeypatch):
    cheap(monkeypatch)
    r = pw.run(toy_g_ctx(no_wall_receipt, 2000.0), {"g": [WIN]}, FakeL())["g"][0]
    assert r["cut"] is False and r["cd"] is not None and r["resolution"]["run_steps"] == r["resolution"]["planned_steps"]
    assert "machine_dependent" not in r["timing"]


def test_nest_diverged_sees_non_finite_forces_and_speeds_and_mach_above_one():
    ok = dict(F=np.ones((4, 3)), umax=np.full(4, 0.05))
    assert not nest.diverged(ok)
    assert nest.diverged(dict(ok, F=np.array([[1.0, np.nan, 0.0]])))
    assert nest.diverged(dict(ok, umax=np.array([0.05, np.inf])))
    assert nest.diverged(dict(ok, umax=np.array([0.05, 0.6]))) and not nest.diverged(dict(ok, umax=np.array([0.05, 0.57])))


def test_a_diverged_chunk_ends_the_run_there_and_does_not_run_to_the_wall_clock_kill():
    """M-26: lattice speed 0.7 is Mach 1.2 from the first chunk; the run used to go on to its kill."""
    sp = W.WindowSpec(velocity=(0.5, 0.0, 0.0), dx=0.01, steps=1200, box=(2.0, 0.8, 0.8), chunk=100, u_lat=0.7)
    r = W.run_window(HULL, sp, _uniform([0, 0, 0]))
    assert r["wall"]["diverged"] and not r["wall"]["killed"] and r["wall"]["run_steps"] == r["wall"]["diverged_at_step"] == 100 == r["steps_run"]
    assert r["wall"]["planned_steps"] == 1200 and r["wall"]["cut_reason"].startswith("diverged after 100 of 1200 steps") and not r["ok"]
    fine = W.run_window(HULL, W.WindowSpec(velocity=(0.5, 0.0, 0.0), dx=0.01, steps=200, box=(2.0, 0.8, 0.8), chunk=100), _uniform([0, 0, 0]))
    assert not fine["wall"]["diverged"] and fine["steps_run"] == 200


def test_a_diverged_window_row_says_so_without_the_step_and_frees_the_rest_of_its_slice(no_wall_receipt, monkeypatch):
    cheap(monkeypatch)
    monkeypatch.setattr(nest, "diverged", lambda ser: True)
    w2 = dict(WIN, t=WIN["t"] + 3600.0)
    first, second = pw.run(toy_g_ctx(no_wall_receipt, 2000.0), {"g": [WIN, w2]}, FakeL())["g"]
    for r in (first, second):
        assert r["cut"] and not r["ok"] and r["cd"] is None and r["reasons"][0].startswith("diverged: the flow went non-finite or past Mach 1")
        assert r["timing"]["machine_dependent"]["run_steps"] == 100
    assert second["timing"]["wall_share_s"] > first["timing"]["wall_share_s"]           # what the first did not use went to the second


def planned_ctx(tmp, windows, share_s=2000.0):
    ctx = toy_g_ctx(tmp, share_s)
    ctx.plan["les"]["windows"] = windows
    return ctx


def test_a_window_the_planner_did_not_run_is_written_with_its_reason_and_never_reaches_the_solver(no_wall_receipt, monkeypatch):
    """M-8: an unreachable CPU window is a row that says why; no LES, no FEA, no wall-clock check on a stage whose share went to stage 1."""
    cheap(monkeypatch)
    monkeypatch.setattr(pw.W, "run_window", lambda *a, **k: pytest.fail("a window the plan skipped was run"))
    # q3 at eceb176: the real reason is ~330 characters and was cut at 300 in the row and 200 in the log, and the log printed "of -0.0"
    reason = ("not run: the physical lattice viscosity (stage3.nu_lat_floor 0.0001) needs dx 1.9 mm, 6.5e+09 cells and 1.4e+15 cell-updates; this "
              "machine does 2.2e+08 in the window's slice at 7.5e+06 cell-updates/s (6.3e+06x short, skipped beyond 100x); the window could only fail "
              "viscosity_floor, so its share went to stage 1")
    ctx = planned_ctx(no_wall_receipt, {"g/body": dict(runs=False, skip_reason=reason, reachable=False)}, 0.0)
    ctx.plan["shares"] = dict(stage3=0.0)
    L = FakeL()
    r = pw.run(ctx, {"g": [WIN]}, L)["g"][0]
    assert not r["ok"] and r["cd"] is None and r["reasons"] == [reason] and r["error"] == reason and not r["cut"]
    assert L.checks["every_window_attempted"][0] and L.checks["every_failed_window_states_a_reason"][0] and "stage_held_its_wall_clock_share" not in L.checks
    assert not any(n.startswith("stage 3 took ") for n in L.notes)                                # no share, no statement about it
    assert any("sub-grid layer uncalibrated: no LES window passed" in n for n in L.notes)
    assert len(reason) > 300 and any(reason in m and "s of 0.0]" in m for m in ctx.logs) and not any("-0.0" in m for m in ctx.logs)


def test_the_slice_of_a_skipped_window_goes_to_the_windows_that_run(no_wall_receipt, monkeypatch):
    cheap(monkeypatch)
    ctx = fake_ctx(no_wall_receipt, vehicles=VEHICLES[:1], classes=dict(g="glider"), rate=2000.0)
    ctx.plan.update(shares=dict(stage3=1.0), budget_s=2000.0)
    ctx.plan["les"]["windows"] = {"g/body": dict(runs=True, skip_reason=None, reachable=False)}
    runs = pw.run(ctx, {"g": [WIN]}, FakeL())["g"][0]
    assert runs["timing"]["wall_share_s"] == pytest.approx(2000.0, rel=0.01)                         # the whole share, no skipped window takes a part of it
    two = fake_ctx(no_wall_receipt, vehicles=VEHICLES[:2], classes=dict(g="glider", g2="glider"), rate=2000.0)
    two.plan.update(shares=dict(stage3=1.0), budget_s=2000.0)
    two.plan["les"]["windows"] = {"g/body": dict(runs=False, skip_reason="not run: x", reachable=False),
                                  "g2/body": dict(runs=True, skip_reason=None, reachable=False)}
    rows = pw.run(two, {"g": [WIN], "g2": [WIN]}, FakeL())
    assert rows["g"][0]["reasons"] == ["not run: x"] and rows["g2"][0]["timing"]["wall_share_s"] == pytest.approx(2000.0, rel=0.01)


def test_a_uas_window_with_arms_under_two_cells_is_not_run_because_that_resolution_diverges(no_wall_receipt, monkeypatch):
    """M-26: the q2 case (arms 10 x 15 mm at dx 14.6 mm) diverged; measured here at 1 CPU, arms two cells thick are stable. The slice is not wasted."""
    cheap(monkeypatch, min_cells_thin_part=2)
    monkeypatch.setattr(pw.W, "run_window", lambda *a, **k: pytest.fail("a window with sub-cell arms was run"))
    r = pw.run(fake_ctx(no_wall_receipt), {"q": [WIN]}, FakeL())["q"][0]
    assert not r["ok"] and r["cd"] is None and r["reasons"][0].startswith("not run: numerically unstable at this resolution: the thinnest part is 10.0 mm")
    assert "stage3.min_cells_thin_part 2" in r["reasons"][0] and not r["cut"]
    a = pw.assumptions()
    assert pw.uas_vehicle(uas.load_platform(), a, "quad_uas").extra["min_dim"] == min(a["uas.arm_width_m"], a["uas.arm_thickness_m"])
    assert "min_dim" not in pw.glider_vehicle(pg.load_platform("seaglider"), a, "seaglider", 500.0).extra


def test_nproc_follows_the_machine_and_stage_3_runs_the_ranks_it_planned(monkeypatch):
    """M-22: 6 ranks whatever the machine had (the plan on 1 CPU was 6 times too low, 32 cores used 6)."""
    monkeypatch.setenv("CAFE_NPROC", "x")
    monkeypatch.delenv("CAFE_NPROC")                                                        # (monkeypatch restores it to unset after the test)
    monkeypatch.setenv("CAFE_WORKERS", "1")
    assert fs.nproc() == 1
    monkeypatch.setenv("CAFE_WORKERS", "3")
    assert fs.nproc() == 3
    monkeypatch.setenv("CAFE_NPROC", "4")
    assert fs.nproc() == 4                                                                  # an explicit CAFE_NPROC still wins
    monkeypatch.delenv("CAFE_NPROC")
    monkeypatch.setenv("CAFE_WORKERS", "2")
    pw.run(fake_ctx(pathlib.Path(tempfile.mkdtemp())), {}, FakeL())
    assert os.environ["CAFE_NPROC"] == "2"                                                  # exported before cafe.cfd or a child reads it


def test_a_bad_cafe_nproc_is_a_config_error_and_0_or_negative_is_not_accepted(monkeypatch):
    """M-23: `abc` was a ValueError traceback, `0` and `-3` were returned as the rank count."""
    for bad in ("abc", "0", "-3"):
        monkeypatch.setenv("CAFE_NPROC", bad)
        with pytest.raises(ConfigError, match=rf"CAFE_NPROC='{bad}' is not a whole number of at least 1; set CAFE_NPROC=N or unset it"):
            fs.nproc()
    monkeypatch.setenv("CAFE_NPROC", "")
    monkeypatch.setenv("CAFE_WORKERS", "2")
    assert fs.nproc() == 2                                                                  # empty is unset


# ---- review round 7, M-27: the window's heading is the bow heading stage 1 recorded, not the course over ground
def _bow_res(heading, n=3):
    """A USV whose course is north-east (45 deg) at every record: a current sets it north of the east-pointing bow."""
    t = np.arange(n) * 3600.0
    return dict(vehicles=dict(u=dict(t=t, lon=np.stack([-170 + 0.01 * np.arange(n)] * 4, 1), lat=np.stack([0.0 + 0.01 * np.arange(n)] * 4, 1),
                                     **({} if heading is None else dict(heading=np.full((n, 4), heading))))))


def test_r7_m27_track_heading_is_the_recorded_bow_heading_and_the_course_only_without_one():
    t = 3600.0
    assert pw.track_heading(_bow_res(None), "u", t) == pytest.approx(45.0, abs=1.0)                                    # the course, as before
    assert pw.track_heading(_bow_res(90.0), "u", t) == pytest.approx(90.0, abs=1e-9)                                   # the bow, not the course
    assert pw.track_heading_source(_bow_res(None), "u", t) == "course over ground (no heading in res.pkl)"
    assert pw.track_heading_source(_bow_res(90.0), "u", t) == "stage-1 heading (circular median)"


def test_r7_m27_the_heading_median_is_circular_and_skips_members_without_one():
    res = _bow_res(0.0)
    res["vehicles"]["u"]["heading"][1] = [350.0, 355.0, 5.0, 10.0]                                                    # a plain median of these is 180
    assert pw.track_heading(res, "u", 3600.0) == pytest.approx(0.0, abs=1e-9)
    res["vehicles"]["u"]["heading"][1] = [np.nan, 270.0, 280.0, np.nan]
    assert pw.track_heading(res, "u", 3600.0) == pytest.approx(275.0, abs=1e-9)
    res["vehicles"]["u"]["heading"][0] = np.nan                                                             # no heading at the deploy record: the course
    assert pw.track_heading(res, "u", 0.0) == pytest.approx(45.0, abs=1.0) and pw.track_heading_source(res, "u", 0.0).startswith("course over ground")


# ------------------------------------------------------------------ review round 7, batch S: M-8, M-9, M-10, M-13, M-28, M-29, M-44
def test_the_wall_model_gate_counts_a_stored_receipt_only_when_the_current_code_made_it(monkeypatch, tmp_path):
    """M-8: stored_wall_error ignored code_sha, so a plate made by other code (or a hand-written file) cleared the stage-3 check."""
    monkeypatch.setattr(wm, "SLOW_DIR", tmp_path)
    plate = {k: v for k, v in _stub_plate(err=0.09).items() if k != "force"}
    chan = _stub_channel(err=0.01)
    wm.slow_path().write_text(json.dumps(dict(plate, code_sha="OLDCODE")))
    assert wm.stale_wall_receipts() == ["wm_flat_plate.json was stored by different code (rerun it)", "wm_channel.json is not stored"]
    wm.channel_path().write_text(json.dumps(chan))                                                    # no code_sha at all
    assert wm.stored_wall_error() is None                                                             # (0.09 before: it passed the 0.10 gate)
    problems = "; ".join(wm.stale_wall_receipts())
    assert problems == "wm_flat_plate.json was stored by different code (rerun it); wm_channel.json was stored without a code sha (rerun it)"
    spec = nest.NestSpec((20, 20, 20), 0.01, 1.0, 1e-6)
    row = lambda err, why="": [c for c in W.stage3_checks(_series(), spec, np.ones(300), 10, err, why) if c["name"] == "wall_model_receipt_error"][0]  # noqa: E731
    r = row(wm.stored_wall_error(), problems)
    assert not r["ok"] and r["problem"] == problems
    why = pw.why_failed([r], dict(delta_te=1.0, dx=0.1), {})[0]
    assert "not both stored by the current code" in why and "wm_channel.json was stored without a code sha" in why
    wm.slow_path().write_text(json.dumps(dict(plate, code_sha=lbm.physics_sha())))
    assert wm.stored_wall_error() is None and wm.stale_wall_receipts() == ["wm_channel.json was stored without a code sha (rerun it)"]     # one stale is enough
    wm.channel_path().write_text(json.dumps(dict(chan, code_sha=lbm.physics_sha())))
    assert wm.stored_wall_error() == 0.09 and wm.stale_wall_receipts() == [] and row(wm.stored_wall_error())["ok"] and "problem" not in row(0.09)
    ok = row(None, "wm_channel.json is not stored")                                                   # a missing receipt keeps the old NaN wording
    assert not ok["ok"] and pw.why_failed([ok], dict(delta_te=1.0, dx=0.1), {})[0].endswith("(wm_channel.json is not stored)")


def test_the_plate_receipt_names_its_reynolds_number_and_is_not_a_pass_below_1e6(monkeypatch, tmp_path):
    """M-44: the stored plate run had Re_L = 9.8e5 under a claim that said 'at Re_L >= 1e6'."""
    monkeypatch.setattr(wm, "SLOW_DIR", tmp_path)
    plate_row = lambda out: [r for r in out if "Flat plate" in r["claim"]][0]  # noqa: E731
    low = plate_row(wm.receipts(_stub_plate(re=9.8e5, cf=0.0040, ittc=0.0040, err=0.0), _stub_channel()))
    assert low["ok"] is False and "Re_L = 9.8e+05, below the 1e6 the comparison needs" in low["claim"] and "not a pass whatever its error" in low["source"]
    cr.OUT.clear()
    fine = plate_row(wm.receipts(_stub_plate(re=1.02e6, cf=0.0040, ittc=0.0040), _stub_channel()))
    assert fine["ok"] is True and "applies at Re_L >= 1e6" in fine["claim"] and "Re_L = 1.02e+06" in fine["claim"]
    p = wm.PLATE_SLOW
    assert lbm.U_LAT * (p["length"] - p["nose"]) / p["nu_lat"] >= 1e6                                  # the run the next re-store makes (9.8e5 at length 384)


def test_the_default_refit_floor_is_the_larger_of_the_assumed_and_the_stored_study(tmp_path, monkeypatch):
    """M-9: the stored three-grid sphere study (1.3053, 1.2087, 1.1848 at d = 8, 12, 16) gave a 1.5 % floor under an assumed 5 %."""
    monkeypatch.setattr(nest, "SLOW_DIR", tmp_path)
    for d, cd in ((8, 1.3053), (12, 1.2087), (16, 1.1848)):
        (tmp_path / f"nest_sphere_100_d{d}.json").write_text(json.dumps(dict(d=d, cd=cd)))
    e, src = nest.sphere_discretisation()
    assert e == pytest.approx(0.0153, abs=2e-4)
    f = refit.default_floor()
    assert f["discretisation_frac"] == 0.05                                                            # (0.0153 before)
    s = f["discretisation_source"]
    assert "NOT in the asymptotic range (extrapolations 1.016 to 1.167)" in s and "floor = max(assumed 0.05, study 0.0153)" in s
    assert "+12.4% from Morrison 2013 (outside the 10 % of the receipt)" in s and "[8, 12, 16]" in s
    assert refit.refit(ONE)["floor"]["discretisation_source"] == s


def test_a_study_in_the_asymptotic_range_can_raise_the_floor_and_none_gives_the_assumed_value(tmp_path, monkeypatch):
    monkeypatch.setattr(nest, "SLOW_DIR", tmp_path)
    assert refit.default_floor()["discretisation_frac"] == 0.05 and refit.default_floor()["discretisation_source"].startswith("ASSUMED")
    for d in (8, 12, 16):                                                                # Cd(d) = 1 + 2 / d: first order, Cd_inf = 1, 12.5 % at d = 16
        (tmp_path / f"nest_sphere_100_d{d}.json").write_text(json.dumps(dict(d=d, cd=1 + 2.0 / d)))
    f = refit.default_floor()
    assert f["discretisation_frac"] == pytest.approx(0.125, rel=0.02) and "NOT in the asymptotic range" not in f["discretisation_source"]
    assert refit.refit(ONE)["drag"]["sigma_discretisation"] == pytest.approx(f["discretisation_frac"] * 1.962 / 1.8)
    (tmp_path / "nest_sphere_100_d8.json").unlink()
    (tmp_path / "nest_sphere_100_d16.json").unlink()                                                   # one grid: no study
    assert refit.default_floor()["discretisation_frac"] == 0.05


def _usv_case(no_wall_receipt, part="hull", wetted=None, heading=0.0):          # heading None: downwind, as pw.run without a stage-1 track
    a = pw.assumptions()
    P = pu.load_platform("saildrone_explorer")
    veh = pw.usv_vehicle(P, a, "saildrone_explorer", part)
    return a, P, veh, pw.usv_case(fake_ctx(no_wall_receipt), WIN, P, veh, a, heading, part, *([] if wetted is None else [wetted]))


def test_the_hull_window_reference_is_evaluated_on_the_windows_own_ellipsoid_not_the_platforms_wetted_area(no_wall_receipt):
    """M-10: the `hull` window is a fully submerged ellipsoid of 17 m2; its Hangar reference used the platform's 6.5 m2, so cd / cd_hangar carried 2.62 x."""
    a, P, veh, c = _usv_case(no_wall_receipt)
    stw = c["info"]["stw_ms"]
    A_e = W.vehicle_mesh(veh, 0).area                                                                  # independent: the area of the meshed ellipsoid
    assert c["wetted_window_m2"] == pytest.approx(A_e, rel=0.02) and c["wetted_window_m2"] == pytest.approx(17.03, abs=0.05)
    assert c["wetted_platform_m2"] == P["wetted_area_m2"] == 6.5
    assert "2.62 x" in c["wetted_area_note"] and "fully submerged ellipsoid of draft 0.45 m" in c["wetted_area_note"]
    q = 0.5 * P["rho_water"] * stw ** 2
    _, keel, _ = keel_and_hull(P, stw)
    fr = float(pu.cf_ittc57(stw * P["lwl_m"] / P["nu_water"])) * (1 + P["form_factor_k"])
    assert c["cd_h"] == pytest.approx((q * c["wetted_window_m2"] * fr + keel) / (q * veh.ref_area))
    window_drag = q * A_e * fr + keel                                              # a window whose drag is exactly the model on its own surface ...
    assert window_drag / (q * veh.ref_area) / c["cd_h"] == pytest.approx(1.0, rel=0.02)                  # ... is a multiplier of 1 (1.9 before)
    old = (q * P["wetted_area_m2"] * fr + keel) / (q * veh.ref_area)
    assert window_drag / (q * veh.ref_area) / old > 1.5                                               # (1.9 x: the keel is the same in both)


def test_the_hull_fs_reference_is_built_on_the_meshes_wetted_area_and_the_row_carries_both_areas(no_wall_receipt, monkeypatch):
    a, P, veh, c = _usv_case(no_wall_receipt, "hull_fs", 8.392)
    stw = c["info"]["stw_ms"]
    q = 0.5 * P["rho_water"] * stw ** 2
    _, keel, _ = keel_and_hull(P, stw)
    assert c["cd_h"] == pytest.approx((float(pu.hull_resistance(dict(P, wetted_area_m2=8.392), np.float64(stw), 0.0)) + keel) / (q * veh.ref_area))
    assert c["wetted_window_m2"] == 8.392 and "1.29 x" in c["wetted_area_note"]
    assert _usv_case(no_wall_receipt, "hull_fs")[3]["wetted_window_m2"] == P["wetted_area_m2"]          # no mesh area given: the platform's, as before
    rows, L = None, FakeL()
    cheap(monkeypatch)
    rows = pw.run(fake_ctx(no_wall_receipt, budget=2e6), {"u": [WIN]}, L)["u"]
    fs_row, hull_row = rows[2], rows[0]
    assert fs_row["part"] == "hull_fs" and fs_row["wetted_area_window_m2"] == fs_row["wetted_area_mesh_m2"] and 7.5 < fs_row["wetted_area_window_m2"] < 9.5
    assert fs_row["wetted_area_platform_m2"] == hull_row["wetted_area_platform_m2"] == 6.5
    assert hull_row["wetted_area_window_m2"] == pytest.approx(17.03, abs=0.05)
    assert hull_row["wetted_area_note"] in L.notes and fs_row["wetted_area_note"] in L.notes             # the ledger states both ratios
    _, _, _, mesh = _usv_case(no_wall_receipt, "hull_fs", fs_row["wetted_area_mesh_m2"], None)
    assert fs_row["cd_hangar"] == pytest.approx(mesh["cd_h"])


def test_the_windows_use_the_platforms_water_and_air_not_the_tank_water_of_the_old_app(no_wall_receipt):
    """M-28: the window ran at nu = 1.19e-6, the Hangar reference at the platform's 0.86e-6: +6 % in the friction part."""
    a, P, hull, c = _usv_case(no_wall_receipt)
    assert hull.nu == P["nu_water"] == 0.86e-6 and hull.rho == P["rho_water"] == 1023.0 and W.nu_of(hull) == 0.86e-6 and W.rho_of(hull) == 1023.0
    stw = c["info"]["stw_ms"]
    assert hull.length * stw / W.nu_of(hull) == pytest.approx(stw * P["lwl_m"] / P["nu_water"])      # the window's Reynolds number is the reference's
    wing = pw.usv_vehicle(P, a, "saildrone_explorer", "wing")
    assert W.nu_of(wing) == W.NU["air"] and W.rho_of(wing) == P["rho_air"] == 1.16
    g = pw.glider_vehicle(pg.load_platform("seaglider"), a, "seaglider", 500.0)
    assert g.nu is None and W.nu_of(g) == 1.19e-6 and W.rho_of(g) == 1025.0                          # no water leaf on the glider platforms: the default stays
    sp = W.WindowSpec(velocity=(1.0, 0.0, 0.0), box=(2.0, 0.6, 0.6))
    lo = W.window_resolution(hull, sp)
    hi = W.window_resolution(W.Vehicle(**dict(hull.__dict__, nu=1.19e-6)), sp)
    assert lo["dx"] == pytest.approx(lbm.les_resolution(hull.length, 1.0, 0.86e-6, (sp.cells_per_delta,), sp.box, sp.duration, sp.u_lat)["rows"][10]["dx"])
    assert lo["dx"] != hi["dx"] and lo["y_plus_estimate"] != hi["y_plus_estimate"]
    fit = pw.fit_window(hull, 1.0, 1e15, a)
    n = a["cells_per_delta"]
    assert fit["dx"] == pytest.approx(lbm.les_resolution(hull.length, 1.0, 0.86e-6, (n,), fit["box"], a["window_s"])["rows"][n]["dx"])


def test_run_window_runs_at_the_vehicles_own_viscosity_and_density():
    air = W.Vehicle("probe", "air", 0.3, [dict(type="ellipsoid", center=(0, 0, 0), radii=(0.1, 0.04, 0.04))], ref_area=0.005)
    sp = W.WindowSpec(velocity=(5.0, 0.0, 0.0), dx=0.01, steps=40, box=(2.0, 0.8, 0.8))
    r0 = W.run_window(air, sp, _uniform([0, 0, 0]))
    r1 = W.run_window(W.Vehicle(**dict(air.__dict__, nu=3e-5, rho=2.4)), sp, _uniform([0, 0, 0]))
    assert r1["resolution"]["nu_lat_physical"] == pytest.approx(2.0 * r0["resolution"]["nu_lat_physical"])       # nu 3e-5 against the default 1.5e-5
    assert r1["q"] == pytest.approx(2.0 * r0["q"])                                                                 # rho 2.4 against 1.2


def test_the_planners_memory_figure_is_the_nests_and_run_window_refuses_what_the_plan_would_refuse(monkeypatch):
    """M-13: the plan allowed 0.85 x 24e9 / 55 = 3.7e8 cells, run_window 1.5e8 (fp16) or 0.9e8 (fp32); the nest needs 300 B/cell."""
    assert budget.LES_BYTES_PER_CELL == nest.NEST_BYTES_PER_CELL == 300.0
    plan = budget.plan("4h", 1, dict(window=dict(start="2023-03-01T12:00:00Z", end="2023-03-07T12:00:00Z")), thr={}, gpu_mem_gb=24.0,
                       vehicle_classes=dict(g="glider", u="usv", q="uas"))
    cap = plan["les"]["max_cells"]
    assert cap == int(0.85 * 24e9 / 300.0)                                                             # 3.7e8 before
    dev = 24e9
    for cells in (0.5 * cap, 0.99 * cap, 1.01 * cap, 2 * cap):                                         # the plan's guard and the window's agree
        try:
            budget.memory_guard(cells, budget.LES_BYTES_PER_CELL, 24.0)
            planner = True
        except budget.PlanError:
            planner = False
        try:
            nest.check_memory(cells, dev)
            window = True
        except lbm.MemoryGuardError as e:
            window = False
            assert "300 B/cell" in str(e)
        assert planner == window == (cells <= cap)
    sp = W.WindowSpec(velocity=(0.5, 0, 0), dx=0.01, steps=10, box=(2.0, 0.8, 0.8))
    cells = W.window_resolution(HULL, sp)["cells"]
    monkeypatch.setattr(lbm, "device_memory_bytes", lambda: cells * 300.0 / 0.85 * 0.9)                # fits at the old 232 B/cell, not at the nest's 300
    with pytest.raises(lbm.MemoryGuardError, match="300 B/cell"):
        W.run_window(HULL, sp, _uniform([0, 0, 0]))


def test_fit_window_never_sizes_a_box_above_the_plans_max_cells(no_wall_receipt, monkeypatch):
    a = pw.assumptions()
    veh = pw.glider_vehicle(pg.load_platform("seaglider"), a, "seaglider", 500.0)
    free = pw.fit_window(veh, 0.25, 1e15, a)
    cap = int(free["cells"] / 5)
    held = pw.fit_window(veh, 0.25, 1e15, a, cap)
    assert free["cells"] > cap and held["cells"] <= cap and held["dx"] > free["dx"] and held["steps"] >= held["min_flow_throughs_steps"]
    assert pw.fit_window(veh, 0.25, 1e15, a, free["cells"]) == free                                   # a cap it already meets changes nothing
    cheap(monkeypatch)                                                                                 # the stage passes the plan's cap to every window
    ctx = fake_ctx(no_wall_receipt, budget=2e6)
    base = pw.run(ctx, {"q": [WIN]}, FakeL())["q"][0]["resolution"]["cells"]
    ctx.plan["les"]["max_cells"] = base // 3
    r = pw.run(ctx, {"q": [WIN]}, FakeL())["q"][0]
    assert r["resolution"]["cells"] <= base // 3 < base and r.get("error") is None


def test_the_free_surface_check_notes_say_what_the_gci_is_and_is_not():
    """M-29: the notes and the cd_spread docstring said 'GCI' without saying it holds only the horizontal refinement."""
    r = dict(speeds={2.0: dict(resistance=500.0, gci=0.1, lift=3.0, std=1e-9)}, cells=250, coarse_cells=100)
    notes = {c["name"]: c["note"] for c in fs.row_fields(r, 2.0, 1000.0, 0.5, 0.2)["checks"]}
    assert "horizontal" in notes["fs_gci"] and "not a bound of the total error" in notes["fs_gci"] and "vertical resolution is the same" in notes["fs_gci"]
    assert "effective ratio from the cell counts" in notes["fs_refinement_ratio"] and "Celik" in notes["fs_refinement_ratio"]
    assert "GCI-based (Fs = 3) spread" in fs.row_fields.__doc__ and "standard error" in fs.row_fields.__doc__


# ------------------------------------------------------------------ review round 8, batch S: M-15, M-32, M-43 (stage 3), M-48
def test_the_hull_fs_row_states_the_displacement_next_to_the_platforms_mass(no_wall_receipt):
    """M-15: the free-surface hull (half ellipsoid + keel) displaces 2.0 t against the platform's 0.75 t; the row said only the wetted-area ratio."""
    a, P, veh, c = _usv_case(no_wall_receipt, "hull_fs", 8.392)
    kc = P["keel_area_m2"] / P["keel_span_m"]
    v_half = 2 * math.pi / 3 * (P["lwl_m"] / 2) * (P["beam_wl_m"] / 2) * a["usv.hull_draft_m"]              # independent of the vehicle's shapes
    v_keel = kc * P["keel_t_c"] * kc * P["keel_span_m"]
    vol = v_half + v_keel
    assert vol == pytest.approx(1.98, abs=0.01) and vol * P["rho_water"] / P["mass_kg"] == pytest.approx(2.7, abs=0.05)
    note = c["wetted_area_note"]
    assert f"displaces {vol:.2f} m3 ({vol * P['rho_water']:.0f} kg) against the platform's {P['mass_kg'] / P['rho_water']:.2f} m3 (750 kg), 2.7 x" in note
    assert "1.29 x" in note and "wave-making resistance is for that larger displacement" in note             # the wetted-area sentence is still there
    assert "displaces" not in _usv_case(no_wall_receipt, "hull")[3]["wetted_area_note"]                   # the fully submerged `hull` window is another body
    import yaml
    why = yaml.safe_load((pathlib.Path(__file__).parents[1] / "config" / "assumptions.yaml").read_text())["stage3.usv.hull_draft_m"]["why"]
    assert "displaces about 2.0 t" in why and "0.75 t" in why and "2.7 times the displacement" in why and "1.29" in why


def test_a_truncated_wall_model_receipt_is_stale_not_a_crash(monkeypatch, tmp_path):
    """M-32: a half-written wm_flat_plate.json raised JSONDecodeError out of stored_wall_error() after the window's LES had run."""
    monkeypatch.setattr(wm, "SLOW_DIR", tmp_path)
    wm.slow_path().write_text('{"cf": 0.0036, "ittc": 0.0039, "re": 1.0e6, "err": 0.0')
    wm.channel_path().write_text(json.dumps(_stub_channel(err=0.01, code_sha=lbm.physics_sha())))
    assert wm.stale_wall_receipts() == ["wm_flat_plate.json is unreadable (rerun it)"] and wm.stored_wall_error() is None
    wm.slow_path().write_text("[1, 2]")                                                                      # valid JSON, not an object
    assert wm.stale_wall_receipts() == ["wm_flat_plate.json is unreadable (rerun it)"]
    wm.slow_path().write_text('{"cf": 0.0036, "ittc"')
    monkeypatch.setattr(wm, "channel", lambda **k: _stub_channel())
    plate_row = [r for r in wm.receipts() if "Flat plate" in r["claim"]][0]                                  # the receipts table reads it as not stored
    assert plate_row["ok"] is False and "NOT STORED" in plate_row["claim"]
    cr.OUT.clear()
    spec = nest.NestSpec((20, 20, 20), 0.01, 1.0, 1e-6)
    row = [c for c in W.stage3_checks(_series(), spec, np.ones(300), 10, wm.stored_wall_error(), "; ".join(wm.stale_wall_receipts()))
           if c["name"] == "wall_model_receipt_error"][0]
    assert not row["ok"] and "unreadable" in row["problem"]


def test_a_killed_wall_model_run_leaves_the_old_receipt(monkeypatch, tmp_path):
    """M-32: wallmodel slow / channel wrote the receipt with write_text, so a kill left half of the new one and none of the old."""
    monkeypatch.setattr(wm, "SLOW_DIR", tmp_path)
    monkeypatch.setattr(wm, "flat_plate", lambda **k: _stub_plate())
    monkeypatch.setattr(wm, "channel", lambda **k: dict(_stub_channel(), profile=None))
    old = json.dumps(dict(cf=0.0036, code_sha="OLD"))
    wm.slow_path().write_text(old)
    wm.channel_path().write_text(old)
    orig = pathlib.Path.write_text

    def cut(self, text, *a, **k):                                                                            # the process dies halfway through the write
        orig(self, text[:20], *a, **k)
        raise OSError("killed")
    monkeypatch.setattr(pathlib.Path, "write_text", cut)
    for cmd, f in (("slow", wm.slow_path()), ("channel", wm.channel_path())):
        with pytest.raises(OSError, match="killed"):
            wm.main([cmd])
        assert f.read_text() == old
    monkeypatch.undo()
    monkeypatch.setattr(wm, "SLOW_DIR", tmp_path)
    monkeypatch.setattr(wm, "flat_plate", lambda **k: _stub_plate())
    assert wm.main(["slow"]) == 0 and json.loads(wm.slow_path().read_text())["code_sha"] == lbm.physics_sha()
    assert not (tmp_path / "wm_flat_plate.json.tmp").exists()                                                # the temporary is gone once the replace is done


def test_the_coefficient_spread_is_the_standard_error_of_five_blocks_and_the_lift_axis_is_perpendicular_to_the_flow():
    """M-43: cd_spread = cd_s / sqrt(nb) -> cd_s (a factor 2.24 on the refit sigma) and a lift axis of plain body z survived every test."""
    rho, area = 1000.0, 0.5
    rel = np.array([-1.0, 0.0, -0.5])                                                          # the flow has a z part: z is not perpendicular to it
    e_d = rel / np.linalg.norm(rel)
    q = 0.5 * rho * area * float(rel @ rel)
    ramp = np.repeat([1.0, 2.0, 3.0, 4.0, 5.0], 10) * q                                                      # block means 1..5: std (ddof 1) sqrt(2.5)
    c = W.coefficients(np.outer(ramp, e_d), rel, rho, area, spinup=0.0)
    se = math.sqrt(2.5) / math.sqrt(5)
    assert c["cd"] == pytest.approx(3.0) and c["cd_spread"] == pytest.approx(se) and c["cl"] == pytest.approx(0.0, abs=1e-12)    # all drag
    e_l = np.array([0.0, 0.0, 1.0]) - (np.array([0.0, 0.0, 1.0]) @ e_d) * e_d
    e_l /= np.linalg.norm(e_l)
    assert abs(e_l @ e_d) < 1e-12 and abs(e_l[2]) < 1.0
    c = W.coefficients(np.outer(ramp, e_l), rel, rho, area, spinup=0.0)
    assert c["cl"] == pytest.approx(3.0) and c["cl_spread"] == pytest.approx(se) and c["cd"] == pytest.approx(0.0, abs=1e-12)  # all lift


def test_the_wing_window_sizes_its_boundary_layer_on_the_chord_not_the_span(no_wall_receipt):
    """M-48: veh.length (the 5 m span) was the plate length of delta_te, so dx was 3.1 x too coarse for the 1.2 m chord."""
    a = pw.assumptions()
    P = pu.load_platform("saildrone_explorer")
    wing = pw.usv_vehicle(P, a, "saildrone_explorer", "wing")
    chord, U, nu = P["wing_area_m2"] / P["wing_span_m"], 5.0, W.NU["air"]
    assert wing.length == P["wing_span_m"] == 5.0 and W.bl_length(wing) == pytest.approx(chord) == pytest.approx(1.2)
    d_chord = 0.37 * chord * (U * chord / nu) ** -0.2                                                         # independent: the BL rule on the chord
    sp = W.WindowSpec(velocity=(U, 0.0, 0.0), box=(2.0, 0.6, 0.6))
    r = W.window_resolution(wing, sp)
    assert r["delta_te"] == pytest.approx(d_chord, rel=1e-6) and r["dx"] == pytest.approx(d_chord / 10, rel=1e-6) and r["dx"] == pytest.approx(3.4e-3, rel=0.03)
    assert r["shape"][0] == math.ceil(2.0 * wing.length / r["dx"])                                           # the box stays the span's
    assert pw.fit_window(wing, U, 1e30, a)["dx"] == pytest.approx(d_chord / 10, rel=1e-6)                    # was 10.5 mm
    glider = pw.glider_vehicle(pg.load_platform("seaglider"), a, "seaglider", 500.0)
    assert W.bl_length(glider) == glider.length
    coarse = W.window_resolution(wing, W.WindowSpec(velocity=(U, 0.0, 0.0), dx=0.0105))                      # the dx the span gave
    why = pw.why_failed([], coarse, {})
    assert len(why) == 1 and "resolution below the rule: 3.2 cells per boundary-layer thickness at dx = 0.0105 m" in why[0]


# ------------------------------------------------------------------ review round 9, batch D: M-4, M-23, M-24
def _without(rec, key):
    return {k: v for k, v in rec.items() if k != key}


PLATE_BAD = {"code_sha_only": lambda r: dict(code_sha=r["code_sha"]), "err_null": lambda r: dict(r, err=None), "err_text": lambda r: dict(r, err="x"),
             "err_bool": lambda r: dict(r, err=True), "err_NaN": lambda r: dict(r, err=math.nan), "cf_missing": lambda r: _without(r, "cf"),
             "re_text": lambda r: dict(r, re="1e6"), "yfrac_null": lambda r: dict(r, yfrac=None), "ittc_missing": lambda r: _without(r, "ittc")}


@pytest.mark.parametrize("what", list(PLATE_BAD))
def test_r9_m4_a_plate_receipt_without_a_number_where_the_code_reads_one_is_unreadable_not_a_crash(monkeypatch, tmp_path, what):
    """M-4: {code_sha} alone, err null or text passed stale_wall_receipts and raised KeyError/TypeError out of stored_wall_error after the LES ran."""
    monkeypatch.setattr(wm, "SLOW_DIR", tmp_path)
    plate = dict(_without(_stub_plate(), "force"), code_sha=lbm.physics_sha())
    wm.slow_path().write_text(json.dumps(PLATE_BAD[what](plate)))
    wm.channel_path().write_text(json.dumps(_stub_channel(err=0.01, code_sha=lbm.physics_sha())))
    assert wm.stale_wall_receipts() == ["wm_flat_plate.json is unreadable (rerun it)"] and wm.stored_wall_error() is None
    monkeypatch.setattr(wm, "channel", lambda **k: _stub_channel())
    plate_row = [r for r in wm.receipts() if "Flat plate" in r["claim"]][0]
    assert plate_row["ok"] is False and "NOT STORED" in plate_row["claim"]


@pytest.mark.parametrize("what", ["code_sha_only", "err_null", "err_text", "cf_dean_missing", "cf_NaN"])
def test_r9_m4_a_channel_receipt_without_a_number_where_the_code_reads_one_is_unreadable_not_a_crash(monkeypatch, tmp_path, what):
    monkeypatch.setattr(wm, "SLOW_DIR", tmp_path)
    wm.slow_path().write_text(json.dumps(dict(_without(_stub_plate(err=0.02), "force"), code_sha=lbm.physics_sha())))
    chan = dict(_stub_channel(err=0.01), code_sha=lbm.physics_sha())
    body = {"code_sha_only": {"code_sha": chan["code_sha"]}, "err_null": dict(chan, err=None), "err_text": dict(chan, err="x"),
            "cf_dean_missing": _without(chan, "cf_dean"), "cf_NaN": dict(chan, cf=math.nan)}[what]
    wm.channel_path().write_text(json.dumps(body))
    assert wm.stale_wall_receipts() == ["wm_channel.json is unreadable (rerun it)"] and wm.stored_wall_error() is None


def test_r9_m4_a_window_with_an_unreadable_receipt_fails_the_check_and_does_not_raise(monkeypatch, tmp_path):
    """M-4, at the level the crash happened: run_window reads the receipt after the LES. A bad receipt is a failed wall_model_receipt_error row."""
    monkeypatch.setattr(wm, "SLOW_DIR", tmp_path)
    wm.slow_path().write_text(json.dumps({"code_sha": lbm.physics_sha()}))
    wm.channel_path().write_text(json.dumps(dict(_stub_channel(err=None), code_sha=lbm.physics_sha())))
    sp = W.WindowSpec(velocity=(0.5, 0.0, 0.0), dx=0.01, steps=200, box=(2.0, 0.8, 0.8), chunk=100)
    r = W.run_window(HULL, sp, _uniform([0, 0, 0]))
    row = [c for c in r["checks"] if c["name"] == "wall_model_receipt_error"][0]
    assert not row["ok"] and math.isnan(row["value"])
    assert row["problem"] == "wm_flat_plate.json is unreadable (rerun it); wm_channel.json is unreadable (rerun it)"
    assert not r["ok"]


@pytest.mark.parametrize("rec", [dict(cd=1.0), dict(ref=1.0), dict(cd=None, ref=1.0), dict(cd="1.0", ref=1.0), dict(cd=True, ref=1.0),
                                 dict(cd=math.nan, ref=1.0), dict(cd=1.0, ref=math.inf)])
def test_r9_m4_result_row_with_a_stored_record_lacking_a_number_is_a_failed_row_not_a_crash(rec):
    """M-4 sibling: result_row read rec[ref_key] (and rec[value_key]) before it looked at the sha."""
    cr.OUT.clear()
    lbm.result_row("g", "claim", dict(rec, code_sha=lbm.physics_sha()), "cd", "ref", 0.1, "cmd", "2 h", "src")
    (row,) = cr.OUT
    assert row["ok"] is False and "STORED WITHOUT A NUMBER FOR" in row["claim"] and "rerun: cmd" in row["source"]
    cr.OUT.clear()


HUGE = "9" * 400                                                                                          # json.loads makes this an int no float holds


@pytest.mark.parametrize("field", ["err", "cf", "re", "ittc", "yfrac"])
def test_r9_m4_a_plate_field_holding_an_integer_too_large_for_a_float_is_unreadable_not_an_overflow(monkeypatch, tmp_path, field):
    """M-4: math.isfinite raised OverflowError on a 400-digit integer literal; read_stored catches only OSError and ValueError."""
    monkeypatch.setattr(wm, "SLOW_DIR", tmp_path)
    good = json.dumps(dict(_without(_stub_plate(), "force"), code_sha=lbm.physics_sha()))
    wm.slow_path().write_text(re.sub(rf'"{field}": [^,}}]+', f'"{field}": {HUGE}', good))
    assert f'"{field}": {HUGE}' in wm.slow_path().read_text()
    wm.channel_path().write_text(json.dumps(_stub_channel(err=0.01, code_sha=lbm.physics_sha())))
    assert wm.stale_wall_receipts() == ["wm_flat_plate.json is unreadable (rerun it)"] and wm.stored_wall_error() is None


@pytest.mark.parametrize("field", ["err", "cf", "cf_dean"])
def test_r9_m4_a_channel_field_holding_an_integer_too_large_for_a_float_is_unreadable_not_an_overflow(monkeypatch, tmp_path, field):
    monkeypatch.setattr(wm, "SLOW_DIR", tmp_path)
    wm.slow_path().write_text(json.dumps(dict(_without(_stub_plate(err=0.02), "force"), code_sha=lbm.physics_sha())))
    good = json.dumps(dict(_stub_channel(err=0.01), code_sha=lbm.physics_sha()))
    wm.channel_path().write_text(re.sub(rf'"{field}": [^,}}]+', f'"{field}": {HUGE}', good))
    assert f'"{field}": {HUGE}' in wm.channel_path().read_text()
    assert wm.stale_wall_receipts() == ["wm_channel.json is unreadable (rerun it)"] and wm.stored_wall_error() is None


@pytest.mark.parametrize("key", ["cd", "ref"])
def test_r9_m4_result_row_and_read_stored_treat_an_integer_too_large_for_a_float_as_no_number(tmp_path, key):
    cr.OUT.clear()
    rec = dict(cd=1.0, ref=1.0, code_sha=lbm.physics_sha())
    (tmp_path / "r.json").write_text(json.dumps(rec).replace(f'"{key}": 1.0', f'"{key}": {HUGE}'))
    assert lbm.read_stored(tmp_path / "r.json", ("cd", "ref")) is None
    lbm.result_row("g", "claim", json.loads((tmp_path / "r.json").read_text()), "cd", "ref", 0.1, "cmd", "2 h", "src")
    (row,) = cr.OUT
    assert row["ok"] is False and f"STORED WITHOUT A NUMBER FOR {key}" in row["claim"]
    cr.OUT.clear()


def test_r9_m4_read_stored_and_the_sphere_grid_readers_name_a_damaged_file_instead_of_raising(monkeypatch, tmp_path):
    """M-4 siblings: nest.sphere_discretisation (the refit's default floor) and nest.sphere_receipts parsed nest_sphere_*.json raw."""
    monkeypatch.setattr(nest, "SLOW_DIR", tmp_path)
    (tmp_path / "a.json").write_text('{"cd": 1.2, "d"')
    assert lbm.read_stored(tmp_path / "a.json") is None and lbm.read_stored(tmp_path / "missing.json") is None
    (tmp_path / "a.json").write_text("[1]")
    assert lbm.read_stored(tmp_path / "a.json") is None
    (tmp_path / "a.json").write_text(json.dumps(dict(cd=1.2, d=8)))
    assert lbm.read_stored(tmp_path / "a.json", ("cd", "d")) == dict(cd=1.2, d=8) and lbm.read_stored(tmp_path / "a.json", ("cd", "x")) is None
    for d, cd in ((8, 1.3053), (12, 1.2087), (16, 1.1848)):
        (tmp_path / f"nest_sphere_100_d{d}.json").write_text(json.dumps(dict(d=d, cd=cd)))
    (tmp_path / "nest_sphere_100_d20.json").write_text('{"d": 20, "cd": 1.1')                               # a kill during the write
    (tmp_path / "nest_sphere_100_d24.json").write_text(json.dumps(dict(d=24, cd=None)))                     # a schema change
    runs, bad = nest.stored_grids("100")
    assert [r["d"] for r in runs] == [8, 12, 16] and bad == ["nest_sphere_100_d20.json", "nest_sphere_100_d24.json"]
    e, src = nest.sphere_discretisation()
    assert e == pytest.approx(0.0153, abs=2e-4) and "[8, 12, 16]" in src
    cr.OUT.clear()
    rows = nest.sphere_receipts()
    names = [r["claim"] for r in rows]
    assert any("nest_sphere_100_d20.json is unreadable" in n for n in names) and any("nest_sphere_100_d24.json is unreadable" in n for n in names)
    assert any("Richardson-extrapolated from d=[8, 12, 16]" in n for n in names)
    cr.OUT.clear()


def test_r9_m23_a_plate_stored_below_re_1e6_fails_the_gate_the_same_as_the_receipts_table(monkeypatch, tmp_path):
    """M-23: the gate never read `re`, so a plate at Re_L 9.8e5 with a small error and the current sha cleared the check that the table fails."""
    monkeypatch.setattr(wm, "SLOW_DIR", tmp_path)
    monkeypatch.setattr(wm, "channel", lambda **k: _stub_channel())
    plate = _without(_stub_plate(re=9.8e5, err=0.01), "force")
    wm.slow_path().write_text(json.dumps(dict(plate, code_sha=lbm.physics_sha())))
    wm.channel_path().write_text(json.dumps(_stub_channel(err=0.01, code_sha=lbm.physics_sha())))
    phrase = "wm_flat_plate.json is at Re_L 9.8e+05, below the 1e+06 the comparison needs (rerun it)"
    assert wm.stale_wall_receipts() == [phrase] and wm.stored_wall_error() is None
    spec = nest.NestSpec((20, 20, 20), 0.01, 1.0, 1e-6)
    gate = [c for c in W.stage3_checks(_series(), spec, np.ones(300), 10, wm.stored_wall_error(), "; ".join(wm.stale_wall_receipts()))
            if c["name"] == "wall_model_receipt_error"][0]
    assert not gate["ok"] and gate["problem"] == phrase
    assert "Re_L 9.8e+05" in pw.why_failed([gate], dict(delta_te=1.0, dx=0.1), {})[0]
    table = [r for r in wm.receipts() if "Flat plate" in r["claim"]][0]
    assert table["ok"] is False and "Re_L = 9.8e+05, below the 1e6 the comparison needs" in table["claim"]                  # the table and the gate agree
    wm.slow_path().write_text(json.dumps(dict(plate, re=wm.PLATE_RE_MIN, code_sha=lbm.physics_sha())))                    # at the limit it counts
    assert wm.stale_wall_receipts() == [] and wm.stored_wall_error() == 0.01
    wm.slow_path().write_text(json.dumps(dict(plate, code_sha="OLD")))                                                     # stale code is said first
    assert wm.stale_wall_receipts() == ["wm_flat_plate.json was stored by different code (rerun it)"]


def _nan_in_the_last_chunk(monkeypatch, last):
    """The real solver, with the force of the chunk that ends at step `last` made non-finite (a blow-up in the final chunk of a whole-chunk run)."""
    real = nest.make_run

    def make_run(*a, **k):
        run = real(*a, **k)

        def wrapped(state, geom, params):
            st, ser = run(state, geom, params)
            return (st, dict(ser, F=ser["F"] * jnp.nan)) if int(st.n) == last else (st, ser)
        return wrapped
    monkeypatch.setattr(nest, "make_run", make_run)


def test_r9_m24_a_window_that_blows_up_in_its_last_chunk_is_flagged_diverged(monkeypatch, tmp_path):
    """M-24: steps is a whole number of chunks, so a blow-up in the last chunk left a full-length series and `n < steps` stayed False."""
    monkeypatch.setattr(wm, "SLOW_DIR", tmp_path)
    _nan_in_the_last_chunk(monkeypatch, 200)
    sp = W.WindowSpec(velocity=(0.5, 0.0, 0.0), dx=0.01, steps=200, box=(2.0, 0.8, 0.8), chunk=100)
    r = W.run_window(HULL, sp, _uniform([0, 0, 0]))
    w = r["wall"]
    assert w["diverged"] and not w["killed"] and w["run_steps"] == w["diverged_at_step"] == w["planned_steps"] == 200 == r["steps_run"]
    assert w["cut_reason"].startswith("diverged after 200 of 200 steps") and not r["ok"]


def test_r9_m24_a_pipeline_window_that_blows_up_in_its_last_chunk_is_cut_and_runs_no_fea(no_wall_receipt, monkeypatch):
    cheap(monkeypatch)
    clean = pw.run(toy_g_ctx(no_wall_receipt, 2000.0), {"g": [WIN]}, FakeL())["g"][0]
    planned = clean["resolution"]["planned_steps"]
    assert clean["cut"] is False and planned % 100 == 0 and not math.isnan(clean["cd"])
    _nan_in_the_last_chunk(monkeypatch, planned)
    monkeypatch.setattr(pw, "_fea", lambda *a, **k: pytest.fail("the FEA ran on the wall pressure of a window that blew up"))
    r = pw.run(toy_g_ctx(no_wall_receipt, 2000.0), {"g": [WIN]}, FakeL())["g"][0]
    assert r["cut"] is True and not r["ok"] and r["usable_for_refit"] is False and r["cd"] is None and r["resolution"]["run_steps"] is None
    assert r["resolution"]["cut_reason"].startswith("diverged: the flow went non-finite or past Mach 1") and r["fea"]["run"] is False
    assert r["timing"]["machine_dependent"]["run_steps"] == planned                                    # the numbers (NaN here) are in the ledger, not the row
    assert r["resolution"]["diverged"] is True                                                         # the report says "diverged", not "cut at the time limit"
    assert r["cl"] is None and "NaN" not in json.dumps(untimed({"g": [r]}), default=str)


def test_r9_m24_the_wall_model_calibrations_and_the_sphere_store_refuse_a_diverged_run(monkeypatch, tmp_path):
    """M-24, per caller: a flat plate, a channel or a sphere that blew up is no measurement, so none returns numbers (a NaN `err` used to be written
    as the receipt) and the CLI writes no file. A window (above) is cut instead; the two bound-checked nest receipts fail their own bound on the NaN."""
    monkeypatch.setattr(wm, "SLOW_DIR", tmp_path)
    monkeypatch.setattr(nest, "SLOW_DIR", tmp_path)
    monkeypatch.setattr(wm, "CHANNEL_CI", dict(h=4, re_tau=100.0, u_tau=0.003, steps=200, span=4))
    _nan_in_the_last_chunk(monkeypatch, 200)
    with pytest.raises(RuntimeError, match="diverged in the chunk ending at step 200 of 200"):
        wm.channel(h=4, re_tau=100.0, u_tau=0.003, steps=200, span=4, chunk=100)
    with pytest.raises(RuntimeError, match="diverged in the chunk ending at step 200 of 200"):
        wm.flat_plate(length=48, half=10, span=4, steps=200, nose=8, thick=1)
    with pytest.raises(RuntimeError, match="diverged"):
        wm.main(["channel"])
    assert not wm.channel_path().exists() and not (tmp_path / "wm_channel.json.tmp").exists()
    with pytest.raises(RuntimeError, match="diverged in the chunk ending at step 200 of 200"):
        nest.sphere_drag(100.0, 4, (6, 3, 3), steps=200)
    with pytest.raises(RuntimeError, match="diverged"):
        nest.main(["slow", "100", "4", "6", "3", "3"])
    assert not list(tmp_path.glob("nest_sphere_*"))
