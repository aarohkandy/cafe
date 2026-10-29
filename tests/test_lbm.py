"""LBM backends, resolution rule, memory model, receipts: each check next to a test that breaks the physics."""
import json
import os

import numpy as np
import pytest
from hypothesis import given, settings, strategies as st
import jax.numpy as jnp

import cafe.receipts as cr
from cafe.pm.stage3 import lbm

BACKENDS = ["jax", "warp"]               # warp 1.12 runs on its CPU device here; on a GPU box it is the CUDA path

settings.register_profile("jax", deadline=None)               # first call of a jitted function compiles
settings.load_profile("jax")


@pytest.fixture(autouse=True)
def clean_receipts():
    cr.OUT.clear()
    yield
    cr.OUT.clear()


# ------------------------------------------------------------------ resolution rule (BRIEF 2.6)
def test_resolution_matches_brief_for_the_1p5m_hull():
    r = lbm.les_resolution(1.5, 1.5, 1.05e-6, box=(2 / 1.5, 0.5 / 1.5, 0.5 / 1.5), T=10.0)
    assert r["delta_te"] == pytest.approx(0.030, rel=0.03)               # BRIEF: delta_TE ~ 30 mm
    assert 1.8e6 < r["re"] < 2.4e6
    fine, coarse = r["rows"][10], r["rows"][5]
    assert fine["dx"] == pytest.approx(0.003, rel=0.03)                  # BRIEF: dx ~ 3 mm
    assert 1.5e7 < fine["cells"] < 2.2e7                                 # BRIEF: ~ 20 M cells in 2 x 0.5 x 0.5 m
    assert 0.8e5 < fine["steps"] < 1.3e5                                 # BRIEF: 10 s ~ 1e5 steps
    assert fine["cells"] / coarse["cells"] == pytest.approx(8, rel=0.1)  # 5 cells/delta is 2x coarser per axis
    assert fine["mach"] <= lbm.MACH_MAX
    assert fine["tau"] > 0.5


def test_resolution_reports_the_y_plus_window_honestly():
    fine = lbm.les_resolution(1.5, 1.5, 1.05e-6)["rows"][10]
    assert fine["y_plus_match"] > 300 and not fine["y_plus_ok"]          # the BRIEF's own dx puts the 3rd cell above y+ 300
    assert fine["dx_for_y_plus_300"] < fine["dx"]
    ok = lbm.les_resolution(1.5, 1.5, 1.05e-6, cells_per_delta=(15,))["rows"][15]
    assert ok["y_plus_ok"]                                                # the dx that does satisfy it


@given(st.floats(0.2, 20), st.floats(0.1, 30), st.sampled_from([1.05e-6, 1.5e-5]), st.integers(3, 12))
def test_resolution_scaling_laws(L, U, nu, n):
    r = lbm.les_resolution(L, U, nu, (n,), box=(2, 1, 1), T=5.0)["rows"][n]
    assert r["dx"] * n == pytest.approx(lbm.les_resolution(L, U, nu, (n,))["delta_te"])
    r2 = lbm.les_resolution(L, U, nu, (2 * n,), box=(2, 1, 1), T=5.0)["rows"][2 * n]
    assert r2["cells"] / r["cells"] == pytest.approx(8, rel=0.2)
    assert r2["steps"] / r["steps"] == pytest.approx(2, rel=0.01)       # halving dx doubles the steps at fixed lattice speed


def test_lattice_params_and_tau_formula():
    p = lbm.lattice_params(1.5, 0.003, 1.05e-6)
    assert p["dt"] == pytest.approx(lbm.U_LAT * 0.003 / 1.5)
    assert p["nu_lat"] == pytest.approx(1.05e-6 * p["dt"] / 9e-6)
    assert lbm.tau_from_nu(1 / 6) == pytest.approx(1.0)


# ------------------------------------------------------------------ memory model and guard
def test_memory_model_matches_brief_cell_counts():
    gb = lambda cells, st_: lbm.memory_bytes(cells, st_, "warp") / 1e9      # noqa: E731
    assert 1e9 * 93 / 1e9 == gb(1e9, "fp32") and gb(1e9, "fp16") == 55.0
    assert lbm.memory_bytes(1e9, "fp32", "jax") == 2.5 * lbm.memory_bytes(1e9, "fp32", "warp")


def test_memory_guard_refuses_over_85_percent_and_says_what_to_cut():
    dev = 96e9
    assert lbm.check_memory(0.85e9, dev, "fp32", "warp") < 0.85
    with pytest.raises(lbm.MemoryGuardError) as e:
        lbm.check_memory(1.0e9, dev, "fp32", "warp")                      # 93 GB of 96
    msg = str(e.value)
    assert "fp16" in msg and "coarsen dx" in msg and "shrink the box" in msg and "cap at" in msg
    assert lbm.check_memory(1.0e9, dev, "fp16", "warp") < 0.85            # the suggestion works
    with pytest.raises(lbm.MemoryGuardError) as e2:
        lbm.check_memory(1.0e9, dev, "fp16", "jax")                       # JAX needs 2.5x
    assert "fp16 storage" not in str(e2.value)


@given(st.floats(1e5, 5e9), st.floats(8e9, 2e11), st.sampled_from(["fp32", "fp16"]), st.sampled_from(["warp", "jax"]))
def test_memory_guard_is_exactly_the_85_percent_line(cells, dev, storage, backend):
    need = lbm.memory_bytes(cells, storage, backend)
    if need <= 0.85 * dev:
        assert lbm.check_memory(cells, dev, storage, backend) == pytest.approx(need / dev)
    else:
        with pytest.raises(lbm.MemoryGuardError):
            lbm.check_memory(cells, dev, storage, backend)


def test_device_memory_and_backend_choice():
    assert lbm.device_memory_bytes() > 1e9
    assert lbm.pick_backend() == "jax"                                    # no CUDA device on homebase
    assert lbm.check_memory(1e6, None, "fp32", "jax") < 0.85


def test_backend_and_memory_probes_on_a_gpu_box_and_when_things_break(monkeypatch):
    import types
    import warp as wp
    monkeypatch.setattr(wp, "get_cuda_device_count", lambda: 1)
    assert lbm.pick_backend() == "warp"                                     # a CUDA device appears: the warp backend
    monkeypatch.setattr(wp, "get_cuda_device_count", lambda: (_ for _ in ()).throw(RuntimeError("no driver")))
    assert lbm.pick_backend() == "jax"                                      # warp broken: labelled fallback
    gpu = types.SimpleNamespace(platform="gpu", memory_stats=lambda: {"bytes_limit": 96e9})
    monkeypatch.setattr(lbm.jax, "devices", lambda *a: [gpu])
    assert lbm.device_memory_bytes() == 96e9
    assert lbm.storage_for("auto") == "fp16"                                # half storage only where bandwidth is the limit
    monkeypatch.undo()
    cpu = types.SimpleNamespace(platform="cpu")
    monkeypatch.setattr(lbm.jax, "devices", lambda *a: [cpu])
    monkeypatch.setattr(lbm.pathlib.Path, "read_text", lambda self, *a, **k: (_ for _ in ()).throw(OSError("no cgroup")))
    assert lbm.device_memory_bytes() == pytest.approx(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES"))
    monkeypatch.setattr(lbm.pathlib.Path, "read_text", lambda self, *a, **k: "8589934592\n")
    assert lbm.device_memory_bytes() == 8589934592.0
    monkeypatch.setattr(lbm.pathlib.Path, "read_text", lambda self, *a, **k: "max\n")   # unlimited cgroup: fall through to RAM
    assert lbm.device_memory_bytes() > 1e9


def test_storage_policy():
    assert lbm.storage_for("auto") == "fp32"                              # CPU
    assert lbm.storage_for("auto", fp32_storage=True) == "fp32"
    assert lbm.storage_for("fp16") == "fp16" and lbm.storage_for("fp16", True) == "fp32"
    with pytest.raises(ValueError):
        lbm.storage_for("fp8")


# ------------------------------------------------------------------ native kernel
rho_s, u_s = st.floats(0.9, 1.1), st.floats(-0.08, 0.08)


@given(rho_s, u_s, u_s, u_s)
@settings(deadline=None)
def test_equilibrium_moments(r, ux, uy, uz):
    rho, u = lbm.moments(lbm.feq(jnp.full((2, 2, 2), r), jnp.broadcast_to(jnp.array([ux, uy, uz]).reshape(3, 1, 1, 1), (3, 2, 2, 2))))
    assert float(rho[0, 0, 0]) == pytest.approx(r, rel=1e-5)
    assert np.allclose(np.asarray(u)[:, 0, 0, 0], [ux, uy, uz], atol=2e-6)


@given(st.integers(0, 2 ** 16), st.sampled_from(["bgk", "reg"]), st.floats(0.0, 0.2))
@settings(max_examples=15, deadline=None)
def test_collision_conserves_mass_and_momentum(seed, mode, cs):
    rng = np.random.default_rng(seed)
    f = lbm.feq(jnp.ones((4, 4, 4)), jnp.asarray(rng.normal(0, 0.03, (3, 4, 4, 4)), jnp.float32))
    f = f + jnp.asarray(rng.normal(0, 1e-3, f.shape), jnp.float32)
    fp, rho, u, tau = lbm.collide(f, 0.51, cs, mode)
    r1, u1 = lbm.moments(fp)
    assert np.allclose(np.asarray(r1), np.asarray(rho), atol=1e-5) and np.allclose(np.asarray(u1), np.asarray(u), atol=1e-5)
    assert float(tau.min()) >= 0.51 - 1e-6                                # eddy viscosity only adds


def test_collision_mode_must_be_known():
    with pytest.raises(ValueError):
        lbm.collide(lbm.feq(jnp.ones((2, 2, 2)), jnp.zeros((3, 2, 2, 2))), 0.6, 0.1, "mrt")


def test_smagorinsky_tau_agrees_with_xlb_after_the_coefficient_conversion():
    """XLB's SmagorinskyLESBGK = Hou et al. with Cs scaled by XLB_CS_SCALE; the native kernel uses Hou's formula directly."""
    import xlb
    from xlb.compute_backend import ComputeBackend
    from xlb.precision_policy import PrecisionPolicy
    from xlb.operator.collision import SmagorinskyLESBGK
    pp = PrecisionPolicy.FP32FP32
    vs = xlb.velocity_set.D3Q19(precision_policy=pp, compute_backend=ComputeBackend.JAX)
    xlb.init(velocity_set=vs, default_backend=ComputeBackend.JAX, default_precision_policy=pp)
    cx = np.asarray(vs._c).T                                              # (19, 3) in XLB's order
    perm = np.array([int(np.where((lbm.C19 == c).all(1))[0][0]) for c in cx])     # XLB index -> native index
    rng = np.random.default_rng(1)
    shape = (5, 5, 5)
    u = rng.normal(0, 0.04, (3,) + shape).astype(np.float32)
    fe_n = lbm.feq(jnp.ones(shape), jnp.asarray(u))
    f_n = fe_n + jnp.asarray(rng.normal(0, 4e-3, fe_n.shape), jnp.float32) * lbm._wshape(fe_n) * 9
    f_n = f_n / f_n.sum(0)                                                # rho = 1 exactly: XLB's formula has no 1/rho
    cs, tau0 = 0.12, 0.505
    _, rho, uu, tau_n = lbm.collide(f_n, tau0, cs, "bgk")
    inv = np.argsort(perm)
    f_x = f_n[jnp.asarray(perm)]                                           # native order -> XLB order (xlb[i] = native[perm[i]])
    fe_x = lbm.feq(rho, uu)[jnp.asarray(perm)]
    out_n, *_ = lbm.collide(f_n, tau0, cs, "bgk")

    def err(coef):
        op = SmagorinskyLESBGK(vs, pp, ComputeBackend.JAX, smagorinsky_coef=coef)
        return float(np.abs(np.asarray(op(f_x, fe_x, rho[None], uu, 1.0 / tau0))[inv] - np.asarray(out_n)).max())
    scaled, raw = err(cs / lbm.XLB_CS_SCALE), err(cs)
    assert float(tau_n.max()) > tau0 + 1e-3                              # the eddy viscosity was active in this comparison
    assert scaled < 5e-5 and scaled < 0.25 * raw                         # the conversion is what makes them agree


def test_streaming_and_bounce_back_conserve_mass_and_give_zero_force_at_rest():
    shape = (12, 12, 12)
    solid = np.zeros(shape, bool)
    solid[4:8, 4:8, 4:8] = True
    link = lbm.links(jnp.asarray(solid))
    assert int(link.sum()) > 0 and not bool((link & jnp.asarray(solid)[None]).any())
    f = lbm.feq(jnp.ones(shape), jnp.zeros((3,) + shape))
    fs = lbm.stream(f)
    fn, F = lbm.bounce_back(f, fs, link, jnp.ones(shape), jnp.zeros(3))
    assert np.allclose(np.asarray(F), 0, atol=1e-6)
    assert float(lbm.stream(f).sum()) == pytest.approx(float(f.sum()), rel=1e-6)
    # moving wall in still fluid pushes back: force opposes the wall velocity (sign check)
    _, Fm = lbm.bounce_back(f, fs, link, jnp.ones(shape), jnp.array([0.05, 0.0, 0.0]))
    assert float(Fm[0]) < -1e-3 and abs(float(Fm[1])) < 1e-5


@given(st.floats(-0.05, 0.05), st.floats(-0.05, 0.05))
@settings(max_examples=12, deadline=None)
def test_bounce_back_tangential_force_is_cs2_times_the_velocity_difference(u1, uw):
    """The identity the wall model inverts: a flat wall facing +y, fluid moving at u1 along x, wall at uw -> F_x = (u1 - uw)/3 per face."""
    shape = (8, 10, 8)
    solid = np.zeros(shape, bool)
    solid[:, :4, :] = True                                                 # periodic in y: two faces, 2 x 64 cells
    link = lbm.links(jnp.asarray(solid))
    f = lbm.feq(jnp.ones(shape), jnp.zeros((3,) + shape).at[0].set(u1))
    _, F = lbm.bounce_back(f, lbm.stream(f), link, jnp.ones(shape), jnp.array([uw, 0.0, 0.0]))
    assert float(F[0]) / 128 == pytest.approx((u1 - uw) / 3, abs=2e-4 + 0.03 * abs(u1 - uw) / 3)
    field = jnp.broadcast_to(jnp.array([uw, 0.0, 0.0]).reshape(3, 1, 1, 1), (3,) + shape)
    _, F2 = lbm.bounce_back(f, lbm.stream(f), link, jnp.ones(shape), field)
    assert np.allclose(np.asarray(F), np.asarray(F2), atol=1e-5)          # a per-cell field gives the same as a vector


def test_mirror_table_is_an_involution_that_flips_one_component():
    for a in range(3):
        assert (lbm.MIR[a][lbm.MIR[a]] == np.arange(19)).all()
        flipped = lbm.C19[lbm.MIR[a]]
        assert (flipped[:, a] == -lbm.C19[:, a]).all() and (np.delete(flipped, a, 1) == np.delete(lbm.C19, a, 1)).all()


def test_flat_wall_cells_find_exactly_the_axis_aligned_faces():
    shape = (12, 12, 12)
    solid = np.zeros(shape, bool)
    solid[3:9, 4:8, 3:9] = True
    ax, sg = lbm.flat_wall_cells(lbm.links(jnp.asarray(solid)))
    assert ax[6, 8, 6] == 1 and sg[6, 8, 6] == 1 and ax[6, 3, 6] == 1 and sg[6, 3, 6] == -1     # +y and -y faces
    assert ax[2, 6, 6] == 0 and sg[2, 6, 6] == -1 and ax[9, 6, 6] == 0 and sg[9, 6, 6] == 1
    assert ax[2, 3, 6] == -1 and ax[0, 0, 0] == -1 and ax[6, 6, 6] == -1                        # edge cell, far field, solid interior


@given(st.integers(0, 2 ** 16))
@settings(max_examples=8, deadline=None)
def test_specular_wall_force_is_purely_normal_on_a_slab(seed):
    shape = (10, 12, 10)
    solid = np.zeros(shape, bool)
    solid[:, :4, :] = True                                                  # periodic in y: faces at y=4 (+y) and y=11 (-y)
    link = lbm.links(jnp.asarray(solid))
    ax, sg = lbm.flat_wall_cells(link)
    rng = np.random.default_rng(seed)
    f = lbm.feq(jnp.ones(shape), jnp.asarray(rng.normal(0, 0.03, (3,) + shape), jnp.float32))
    f = f * (1 + jnp.asarray(rng.normal(0, 1e-2, f.shape), jnp.float32))
    _, F = lbm.specular(f, lbm.stream(f), link, jnp.asarray(ax), jnp.asarray(sg))
    assert abs(float(F[0])) < 1e-9 and abs(float(F[2])) < 1e-9              # exactly nothing tangential: no term of the sum has one
    assert np.isfinite(float(F[1])) and ax[:, 4, :].min() == 1 and ax[:, 11, :].min() == 1


@given(st.integers(0, 2 ** 16))
@settings(max_examples=8, deadline=None)
def test_specular_reflection_exchanges_no_tangential_momentum_per_cell(seed):
    """For one wall cell: sum_q c_q[tangential] f_new = same for the populations that left it (mirror pairs share their tangential part)."""
    rng = np.random.default_rng(seed)
    f = jnp.asarray(rng.uniform(0.01, 0.3, (19, 3, 3, 3)), jnp.float32)
    link = jnp.zeros((19, 3, 3, 3), bool)
    wall_q = [q for q in range(19) if lbm.C19[q, 1] < 0]                      # solid below: links toward -y
    for q in wall_q:
        link = link.at[q, 1, 1, 1].set(True)
    ax = jnp.full((3, 3, 3), -1, jnp.int8).at[1, 1, 1].set(1)
    sg = jnp.zeros((3, 3, 3), jnp.int8).at[1, 1, 1].set(1)
    fn, F = lbm.specular(f, jnp.zeros_like(f), link, ax, sg)
    incoming = [t for t in range(19) if lbm.C19[t, 1] > 0]
    out_x = sum(float(lbm.C19[q, 0] * f[q, 1, 1, 1]) for q in wall_q)
    in_x = sum(float(lbm.C19[t, 0] * fn[t, 1, 1, 1]) for t in incoming)
    assert in_x == pytest.approx(out_x, abs=1e-6)                             # tangential momentum arrives as it left
    assert sum(float(fn[t, 1, 1, 1]) for t in incoming) == pytest.approx(sum(float(f[q, 1, 1, 1]) for q in wall_q), abs=1e-6)   # mass too
    assert float(F[1]) == pytest.approx(-2 * sum(float(f[q, 1, 1, 1]) for q in wall_q if lbm.C19[q, 1] == -1), abs=1e-6)


@given(st.integers(0, 2 ** 16))
@settings(max_examples=10, deadline=None)
def test_fp16_storage_error_is_relative_to_the_fluctuation(seed):
    rng = np.random.default_rng(seed)
    f = lbm.feq(jnp.ones((4, 4, 4)), jnp.asarray(rng.normal(0, 0.03, (3, 4, 4, 4)), jnp.float32))
    g = lbm.store(f, "fp16")
    fluct = np.abs(np.asarray(f - lbm._wshape(f)))
    assert (np.abs(np.asarray(g - f)) <= 1e-3 * fluct + 1e-7).all()       # half precision of (f - w): error << f_neq
    assert (np.abs(np.asarray(g - f)) > 0).any()
    assert lbm.store(f, "fp32") is f


# ------------------------------------------------------------------ XLB reference cases on both backends
@pytest.mark.parametrize("backend", BACKENDS)
def test_poiseuille_parabola(backend):
    p = lbm.poiseuille(backend)
    assert p["g_ratio"] == pytest.approx(1.0, abs=0.01) and p["resid"] < 0.005
    assert -0.6 < p["y0"] < 0.3 and 30.7 < p["y1"] < 31.6                 # wall at the rim nodes (XLB's convention)


def test_poiseuille_receipt_fails_with_a_wrong_relaxation_time_formula(monkeypatch):
    monkeypatch.setattr(lbm, "tau_from_nu", lambda nu: 0.5 + nu)          # missing the factor 3
    p = lbm.poiseuille("jax")
    assert abs(p["g_ratio"] - 1.0) > 0.1


@pytest.mark.parametrize("backend", BACKENDS)
def test_taylor_green_decay_rate_both_backends(backend):
    r = lbm.taylor_green(backend)
    assert r["ratio"] == pytest.approx(1.0, abs=0.01)
    assert lbm.taylor_green(backend, storage="fp16")["ratio"] == pytest.approx(1.0, abs=0.03)


def test_taylor_green_native_matches_xlb_and_breaks_with_wrong_tau(monkeypatch):
    a, b = lbm.taylor_green("native")["ratio"], lbm.taylor_green("jax")["ratio"]
    assert a == pytest.approx(b, abs=2e-3)
    # FP16-shifted storage keeps the decay rate at a low amplitude where raw half precision of f does not
    lo = dict(u0=0.004, nu=0.02)
    shifted = lbm.taylor_green("native", storage="fp16", **lo)["ratio"]
    raw = lbm.taylor_green("jax", storage="fp16", **lo)["ratio"]
    assert abs(shifted - 1) < 0.02 and abs(raw - 1) > 3 * abs(shifted - 1)
    monkeypatch.setattr(lbm, "tau_from_nu", lambda nu: 0.5 + nu)
    assert abs(lbm.taylor_green("native")["ratio"] - 1) > 0.5


def _stub_fast(monkeypatch, **over):
    base = dict(poiseuille=dict(g_ratio=1.0, resid=0.0, y0=0, y1=31), cavity=dict(err_u=0.0, err_v=0.0),
                taylor_green=dict(ratio=1.0))
    base.update(over)
    for k, v in base.items():
        monkeypatch.setattr(lbm, k, lambda *a, _v=v, **kw: _v)


def test_receipts_sphere_rows_are_required_pass_or_fail(monkeypatch, tmp_path):
    _stub_fast(monkeypatch)
    monkeypatch.setattr(lbm, "SLOW_DIR", tmp_path)
    out = lbm.receipts("jax")
    sph = [r for r in out if "Sphere" in r["claim"]]
    assert len(sph) == 3 and all(r["ok"] is False and "NOT STORED" in r["claim"] and "run:" in r["source"] for r in sph)   # nothing stored: fail
    for tag, re in lbm.SPHERE_RUNS:
        lbm.slow_path(f"sphere_{tag}").write_text(json.dumps(dict(cd=lbm.morrison(re) * 1.3, ref=lbm.morrison(re), seconds=600, shape=[1, 2, 3], d=8)))
    cr.OUT.clear()
    sph = [r for r in lbm.receipts("jax") if "Sphere" in r["claim"]]
    assert len(sph) == 3 and all(r["ok"] is False and r["value"] == pytest.approx(r["reference"] * 1.3, rel=1e-3) for r in sph)    # stored, 30 % off: fail
    for tag, re in lbm.SPHERE_RUNS:
        lbm.slow_path(f"sphere_{tag}").write_text(json.dumps(dict(cd=lbm.morrison(re) * 1.02, ref=lbm.morrison(re), seconds=600, shape=[1, 2, 3], d=48)))
    cr.OUT.clear()
    assert all(r["ok"] is True for r in lbm.receipts("jax") if "Sphere" in r["claim"])


def test_result_row_branches_physics_sha_and_eta(monkeypatch):
    cr.OUT.clear()
    lbm.result_row("g", "claim", None, "cd", "ref", 0.1, "cmd", "2 h", "src")
    assert cr.OUT[-1]["ok"] is False and "NOT STORED" in cr.OUT[-1]["claim"] and "cmd" in cr.OUT[-1]["source"] and "2 h" in cr.OUT[-1]["source"]
    lbm.result_row("g", "claim", dict(cd=1.0, ref=1.0, code_sha="zzz"), "cd", "ref", 0.1, "cmd", "2 h", "src")
    assert cr.OUT[-1]["ok"] is False and "DIFFERENT CODE" in cr.OUT[-1]["claim"]
    lbm.result_row("g", "claim", dict(cd=1.05, ref=1.0, code_sha=lbm.physics_sha()), "cd", "ref", 0.1, "cmd", "2 h", "src")
    assert cr.OUT[-1]["ok"] is True
    lbm.result_row("g", "claim", dict(cd=1.2, ref=1.0), "cd", "ref", 0.1, "cmd", "2 h", "src")        # no sha: stored before the policy, judged on its number
    assert cr.OUT[-1]["ok"] is False and cr.OUT[-1]["value"] == pytest.approx(1.2)
    a = lbm.physics_sha()
    assert a == lbm.physics_sha() and len(a) == 16
    assert "h" in lbm.eta_text(8.6e10) and "loaded" in lbm.eta_text(8.6e10)


@pytest.mark.parametrize("what", ["taylor_green", "poiseuille", "cavity"])
def test_each_receipt_fails_when_its_physics_is_wrong(monkeypatch, tmp_path, what):
    wrong = dict(taylor_green=dict(ratio=1.2), poiseuille=dict(g_ratio=1.2, resid=0.0, y0=0, y1=31), cavity=dict(err_u=0.2, err_v=0.0))
    _stub_fast(monkeypatch, **{what: wrong[what]})
    monkeypatch.setattr(lbm, "SLOW_DIR", tmp_path)
    assert any(r["ok"] is False for r in lbm.receipts("jax"))


@pytest.mark.slow
@pytest.mark.parametrize("backend", BACKENDS)
def test_cavity_against_ghia(backend):
    c = lbm.cavity(backend)
    assert c["err_u"] < 0.04 and c["err_v"] < 0.04


def test_cavity_receipt_fails_against_the_wrong_reynolds_number():
    c = lbm.cavity("jax", n=48, re=1000.0, steps=20000)
    assert c["err_u"] > 0.08                                              # a Re=1000 cavity is not Ghia's Re=100 one


def test_ghia_tables_are_self_consistent():
    assert lbm.GHIA_U[0, 1] == 1.0 and lbm.GHIA_U[-1, 1] == 0.0           # lid speed and no-slip floor
    assert lbm.GHIA_V[0, 1] == 0.0 and lbm.GHIA_V[-1, 1] == 0.0
    assert (np.diff(lbm.GHIA_U[:, 0]) < 0).all() and (np.diff(lbm.GHIA_V[:, 0]) < 0).all()
    assert lbm.GHIA_U[:, 1].min() == pytest.approx(-0.21090) and lbm.GHIA_V[:, 1].min() == pytest.approx(-0.24533)


def test_morrison_correlation_known_points():
    assert lbm.morrison(100.0) == pytest.approx(1.04, abs=0.02)      # (literature ~1.09: Morrison's fit is a few % low here)
    assert lbm.morrison(1000.0) == pytest.approx(0.47, abs=0.03)
    assert lbm.morrison(1e4) == pytest.approx(0.40, abs=0.03)


@given(st.floats(10, 3e5))
def test_morrison_is_positive_and_decreasing_with_re_below_1e3(re):
    assert lbm.morrison(re) > 0
    if re < 900:
        assert lbm.morrison(re * 1.05) < lbm.morrison(re)


def test_taylor_green_breaks_with_the_wrong_tau_in_the_xlb_path_too(monkeypatch):
    monkeypatch.setattr(lbm, "tau_from_nu", lambda nu: 0.5 + nu)
    assert abs(lbm.taylor_green("jax")["ratio"] - 1) > 0.5


def test_sphere_runs_on_both_backends_and_they_agree():
    kw = dict(re=20.0, d=6, domain=(8, 4, 4), steps=800)
    a, b = lbm.sphere("jax", **kw), lbm.sphere("warp", **kw)
    assert a["cd"] > 1.0 and a["shape"] == (48, 24, 24) and a["outlet"] == "equilibrium"
    assert b["cd"] == pytest.approx(a["cd"], rel=0.01)                      # same code, two backends
    c = lbm.sphere("jax", side="open", **kw)
    assert c["cd"] < a["cd"]                                                # open lateral faces: less confinement
    d = lbm.sphere("jax", outlet_bc="extrapolation", **kw)
    assert np.isfinite(d["cd"]) and d["outlet"] == "extrapolation"


def test_sphere_drag_falls_with_reynolds_number_and_les_branch_runs():
    lo = lbm.sphere("jax", 20.0, d=6, domain=(8, 4, 4), steps=800)
    hi = lbm.sphere("jax", 100.0, d=6, domain=(8, 4, 4), steps=800, u_in=0.03)
    assert lo["cd"] > hi["cd"] > 0 and lo["ref"] > hi["ref"]
    les = lbm.sphere("jax", 1000.0, d=6, domain=(8, 4, 4), steps=300, progress=lambda t, c: None)
    assert np.isfinite(les["cd"]) and len(les["history"]) > 10


def test_cli_plumbing(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(lbm, "SLOW_DIR", tmp_path)
    monkeypatch.setattr(lbm, "sphere", lambda *a, **k: (k["progress"](1, 1.0), dict(cd=1.0, ref=1.0, seconds=1.0, shape=(1,), history=[1.0]))[1])
    assert lbm.main(["slow", "1e4", "8", "10", "6", "6", "--backend", "jax"]) == 0
    assert json.loads((tmp_path / "lbm_sphere_1e4.json").read_text())["cd"] == 1.0
    monkeypatch.setattr(lbm, "measure_jax_bytes_per_cell", lambda **k: 190.0)
    assert lbm.main(["memory", "--fp32-storage"]) == 0
    assert "delta_te" in capsys.readouterr().out
    _stub_fast(monkeypatch)
    cr.OUT.clear()
    assert lbm.main(["receipts", "--backend", "jax"]) == 0
    _stub_fast(monkeypatch, taylor_green=dict(ratio=2.0))
    cr.OUT.clear()
    assert lbm.main([]) == 1


def test_measured_jax_memory_per_cell_is_at_least_the_population_array():
    b = lbm.measure_jax_bytes_per_cell(n=24)
    assert b >= 19 * 4 and b < 40 * 19 * 4
