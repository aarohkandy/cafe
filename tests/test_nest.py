"""Moving nest: shifts, refill, sponge, zero spurious force, mass conservation, vmap over vehicles, coupling helpers."""
import json
import re

import numpy as np
import pytest
from hypothesis import given, settings, strategies as st
import jax
import jax.numpy as jnp

import cafe.receipts as cr
from cafe.pm.stage3 import lbm, nest

settings.register_profile("jax", deadline=None)               # first call of a jitted function compiles
settings.load_profile("jax")


@pytest.fixture(autouse=True)
def clean_receipts():
    cr.OUT.clear()
    yield
    cr.OUT.clear()


# ------------------------------------------------------------------ receipts and the tests that break them
def test_uniform_flow_gives_zero_force_and_the_nest_really_shifts():
    r = nest.uniform_flow_force()
    assert r["f_rel"] < 1e-4 and r["shifts"] >= 10


def test_zero_force_receipt_fails_without_the_moving_wall_term():
    r = nest.uniform_flow_force(wall_vel=False)
    assert r["f_rel"] > 1e-2                                              # the carried body now sees a phantom wind


def test_shear_layer_mass_and_interpolation_residual():
    r = nest.shear_layer_mass()
    assert r["drift"] < 1e-3 and r["shifts"] >= 10 and r["res"] < nest.RES_MAX


def test_mass_receipt_fails_with_a_wrong_refill_density():
    r = nest.shear_layer_mass(rho_override=1.05)
    assert r["drift"] > 1e-3


def test_residual_receipt_fails_when_the_shift_is_not_refilled():
    r = nest.shear_layer_mass(refill=False)
    assert r["res"] > nest.RES_MAX


def test_receipts_pass_and_are_recorded(monkeypatch, tmp_path):
    monkeypatch.setattr(nest, "SLOW_DIR", tmp_path)
    out = nest.receipts()
    core = [x for x in out if x["group"] == "LBM nest"]
    assert len(core) == 5 and all(x["ok"] for x in core)
    sph = [x for x in out if x["group"] == "LBM native sphere"]
    assert len(sph) == 3 and all(x["ok"] is None and "not stored" in x["claim"] for x in sph)      # no slow runs yet: context rows


def _sphere_json(re, cd, **over):
    d = dict(cd=cd, ref=lbm.morrison(re), d=16, shape=[8, 9, 9], seconds=1200.0, needs_d=32, re=re)
    d.update(over)
    return json.dumps(d)


def test_richardson_recovers_the_limit_and_the_order():
    ds = [8, 12, 16]
    first = nest.richardson(ds, [1.0 + 2.0 / d for d in ds])
    assert first["cd_inf"] == pytest.approx(1.0, abs=1e-6) and first["p"] == pytest.approx(1.0, abs=0.02) and first["ds"] == [8.0, 12.0, 16.0]
    second = nest.richardson(ds, [1.0 + 10.0 / d ** 2 for d in ds])
    assert second["cd_inf"] == pytest.approx(1.0, abs=1e-4) and second["p"] == pytest.approx(2.0, abs=0.02)
    two = nest.richardson([12, 8], [1.2087, 1.305])                                 # unsorted, two grids: first order
    assert two["p"] == 1.0 and two["cd_inf"] == pytest.approx(1.2087 - (1.305 - 1.2087) / (1 / 8 - 1 / 12) * (1 / 12), abs=1e-9)
    flat = nest.richardson(ds, [1.2, 1.2, 1.2])                                      # nothing to extrapolate: no root bracketed, p = 1
    assert flat["p"] == 1.0 and flat["cd_inf"] == pytest.approx(1.2)


def test_sphere_receipts_pass_fail_and_never_pass_the_high_re_rows(monkeypatch, tmp_path):
    monkeypatch.setattr(nest, "SLOW_DIR", tmp_path)
    ref = lbm.morrison(100.0)
    nest.sphere_path("100", 8).write_text(_sphere_json(100.0, 1.305, d=8))
    out = nest.sphere_receipts()
    assert any("needs >= 2 stored grids" in x["claim"] for x in out) and any("finest stored grid d=8" in x["claim"] for x in out)
    cr.OUT.clear()
    nest.sphere_path("100", 12).write_text(_sphere_json(100.0, 1.2087, d=12))
    nest.sphere_path("1000").write_text(_sphere_json(1000.0, lbm.morrison(1000.0) * 1.01))          # even an exact hit is context only
    nest.sphere_path("1e4").write_text(_sphere_json(1e4, lbm.morrison(1e4) * 1.7))
    out = nest.sphere_receipts()
    rich = [x for x in out if "Richardson" in x["claim"]][0]
    assert rich["ok"] is True and rich["value"] == pytest.approx(1.016, abs=0.01) and abs(rich["value"] / ref - 1) < 0.10
    by = {re.search(r"Re=(\d+)", x["claim"]).group(1): x for x in out if "NOT MET" in x["claim"]}
    assert by["1000"]["ok"] is None and by["10000"]["ok"] is None
    assert "needs d >= 32" in by["10000"]["claim"] and "python -m cafe.pm.stage3.nest slow 1e4 32" in by["10000"]["claim"]
    cr.OUT.clear()
    nest.sphere_path("100", 8).write_text(_sphere_json(100.0, 1.6, d=8))                          # a code that is 50 % off at both grids
    nest.sphere_path("100", 12).write_text(_sphere_json(100.0, 1.55, d=12))
    assert any(x["ok"] is False for x in nest.sphere_receipts())
    assert nest.gpu_command("100", 16).startswith("python -m cafe.pm.stage3.nest slow 100 16 9 6 6")


def test_nest_cli(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(nest, "SLOW_DIR", tmp_path)
    monkeypatch.setattr(nest, "sphere_drag", lambda re, d, dom, lateral: dict(cd=1.1, d=d, shape=(1, 2, 3), history=np.ones(3), steps=3))
    assert nest.main(["slow", "100", "16", "14", "8", "8", "--lateral", "dirichlet", "--needs-d", "24"]) == 0
    saved = json.loads(nest.sphere_path("100", 16).read_text())
    assert saved["lateral"] == "dirichlet" and saved["needs_d"] == 24 and saved["ref"] == pytest.approx(lbm.morrison(100.0))
    assert nest.main(["slow", "1000", "16", "14", "8", "8"]) == 0 and json.loads(nest.sphere_path("1000").read_text())["lateral"] == "freeslip"
    assert "cd" in capsys.readouterr().out
    monkeypatch.setattr(nest, "uniform_flow_force", lambda **k: dict(f_rel=0.0, shifts=20))
    monkeypatch.setattr(nest, "shear_layer_mass", lambda **k: dict(drift=0.0, shifts=20, res=0.0))
    assert nest.main([]) == 0
    monkeypatch.setattr(nest, "shear_layer_mass", lambda **k: dict(drift=0.5, shifts=20, res=0.0))
    cr.OUT.clear()
    assert nest.main([]) == 1


# ------------------------------------------------------------------ mechanics
def _env_uniform(u):
    u = np.asarray(u, np.float32)
    return lambda x, y, z, t: jnp.stack([jnp.full_like(x, u[0]), jnp.full_like(x, u[1]), jnp.full_like(x, u[2])])


def test_shift_follows_the_vehicle_one_cell_at_a_time():
    shape = (16, 16, 16)
    spec = nest.NestSpec(shape, 0.01, 1.0, 1e-4, u_lat=0.05, wall_model=False, sponge=2)
    geom = nest.make_geom(np.zeros(shape, bool), (8, 8, 8))
    v = np.array([1.0, -0.47, 0.0])
    p0 = np.array([0.085, 0.085, 0.085])
    params = (jnp.asarray(p0, jnp.float32), jnp.asarray(v, jnp.float32))
    state, ser = nest.simulate(spec, _env_uniform(v), geom, p0, params, 300, chunk=100, v0=tuple(v))
    assert np.abs(ser["shift"]).max() == 1                                # never more than one cell per axis per step
    p_end = p0 + v * 300 * spec.dt
    want = np.floor(p_end / spec.dx).astype(int) - 8
    assert np.array_equal(np.asarray(state.ix), want)                     # the grid tracks the vehicle to a cell
    assert ser["shift"][:, 0].sum() > 0 and ser["shift"][:, 1].sum() < 0 and ser["shift"][:, 2].sum() == 0


def test_shell_weights_and_periodic_axes():
    spec = nest.NestSpec((12, 12, 6), 1.0, 1.0, 1e-3, periodic=(False, False, True), sponge=3)
    idx, inner, w, k = nest._shell(spec)
    assert w.max() == 1.0 and (w[k == 0] == 1).all() and (np.diff(np.sort(w[k > 0])) >= 0).all()
    assert (k <= 3).all() and idx[2].max() == 5 and k.max() == 3          # z is periodic: no z layers in the shell
    assert (inner[0] >= 1).all() and (inner[0] <= 10).all()
    assert (idx[2][k == 0].reshape(-1) >= 0).all()
    # a periodic axis contributes no shell cells of its own: cells with only z on the face are not in the shell
    assert not ((idx[0] == 6) & (idx[1] == 6)).any()


def test_geometry_must_not_touch_open_faces():
    s = np.zeros((10, 10, 10), bool)
    s[0, 4:6, 4:6] = True
    with pytest.raises(ValueError, match="touches"):
        nest.make_geom(s, (5, 5, 5))
    nest.make_geom(s, (5, 5, 5), periodic=(True, False, False))           # periodic axis: allowed


def test_init_state_sets_equilibrium_and_wall_equilibrium():
    shape = (14, 14, 14)
    spec = nest.NestSpec(shape, 0.01, 1.0, 1e-4, wall_model=False)
    solid = nest._sphere(shape, (7, 7, 7), 2.5)
    geom = nest.make_geom(solid, (7, 7, 7))
    s = nest.init_state(spec, geom, _env_uniform([0.5, 0, 0]), (0.075, 0.075, 0.075), v0=(0.2, 0, 0))
    rho, u = lbm.moments(s.f)
    assert np.allclose(np.asarray(rho), 1.0, atol=1e-6)
    ul = 0.5 * spec.dt / spec.dx
    assert np.asarray(u)[0, 0, 0, 0] == pytest.approx(ul, rel=1e-4)
    assert np.asarray(u)[0, 7, 7, 7] == pytest.approx(0.2 * spec.dt / spec.dx, rel=1e-4)


def test_vmap_over_vehicles_matches_separate_runs():
    shape = (24, 20, 20)
    spec = nest.NestSpec(shape, 0.01, 1.0, 1e-4, u_lat=0.05, wall_model=True, sponge=3)
    env = _env_uniform([1.0, 0.0, 0.0])
    bodies = [nest._sphere(shape, (12, 10, 10), 3.0), nest._sphere(shape, (12, 10, 10), 4.0)]
    geoms = [nest.make_geom(b, (12, 10, 10)) for b in bodies]
    p0 = np.array([0.125, 0.105, 0.105])
    vels = [np.array([0.2, 0, 0]), np.array([0.0, 0, 0])]
    params = [(jnp.asarray(p0, jnp.float32), jnp.asarray(v, jnp.float32)) for v in vels]
    states = [nest.init_state(spec, g, env, p0, tuple(v)) for g, v in zip(geoms, vels, strict=True)]
    run1 = nest.make_run(spec, env, 60)
    singles = [run1(s, g, p) for s, g, p in zip(states, geoms, params, strict=True)]
    batched = nest.make_run(spec, env, 60, batched=True)
    stack = lambda xs: jax.tree.map(lambda *a: jnp.stack(a), *xs)         # noqa: E731
    _, ser = batched(stack(states), nest.stack_geoms(geoms), stack(params))
    assert ser["F"].shape == (2, 60, 3)
    for i in range(2):
        assert np.allclose(np.asarray(ser["F"][i]), np.asarray(singles[i][1]["F"]), rtol=2e-3, atol=2e-5)
    assert not np.allclose(np.asarray(ser["F"][0]), np.asarray(ser["F"][1]), atol=1e-6)   # different bodies, different forces


def test_fp16_storage_nest_runs():
    shape = (16, 16, 16)
    spec = nest.NestSpec(shape, 0.01, 1.0, 1e-4, wall_model=False, storage="fp16", sponge=2)
    geom = nest.make_geom(np.zeros(shape, bool), (8, 8, 8))
    p0 = np.array([0.085] * 3)
    _, ser = nest.simulate(spec, _env_uniform([1.0, 0, 0]), geom, p0, (jnp.asarray(p0, jnp.float32), jnp.zeros(3, jnp.float32)), 40)
    assert np.isfinite(ser["mass"]).all() and nest.mass_drift(ser) < 1e-3


# ------------------------------------------------------------------ coupling helpers
@given(st.floats(-2, 2), st.floats(-2, 2), st.floats(-2, 2), st.floats(0.05, 0.95), st.floats(0.05, 0.95), st.floats(0.05, 0.95))
@settings(max_examples=20, deadline=None)
def test_grid_field_is_exact_for_linear_fields(a, b, c, fx, fy, fz):
    g = np.stack(np.meshgrid(*[np.arange(6)] * 3, indexing="ij")).astype(np.float32)
    u = np.stack([a * g[0] + b * g[1], c * g[2] + a, b * g[0] - c * g[1]])
    f = nest.grid_field(u, (0, 0, 0), 1.0)
    x, y, z = (jnp.asarray([fx + 2.0]), jnp.asarray([fy + 1.0]), jnp.asarray([fz + 3.0]))
    got = np.asarray(f(x, y, z, 0.0))[:, 0]
    X, Y, Z = fx + 2.0, fy + 1.0, fz + 3.0
    assert np.allclose(got, [a * X + b * Y, c * Z + a, b * X - c * Y], atol=2e-4)


def test_grid_field_time_interpolation_and_edge_hold():
    g0 = np.zeros((3, 4, 4, 4), np.float32)
    g1 = np.ones((3, 4, 4, 4), np.float32)
    f = nest.grid_field(g0, (0, 0, 0), 1.0, 0.0, g1, 10.0)
    p = jnp.asarray([1.5])
    assert float(f(p, p, p, 5.0)[0, 0]) == pytest.approx(0.5)
    assert float(f(p, p, p, 99.0)[0, 0]) == pytest.approx(1.0)            # time held after t1
    assert float(f(jnp.asarray([-50.0]), p, p, 0.0)[0, 0]) == pytest.approx(0.0)    # space held outside the grid


@given(st.integers(1, 4), st.integers(0, 2 ** 16))
def test_restrict_preserves_the_mean(r, seed):
    u = np.random.default_rng(seed).normal(size=(3, 4 * r, 2 * r, 3 * r))
    c = nest.restrict(u, r)
    assert c.shape == (3, 4, 2, 3) and np.allclose(c.mean((1, 2, 3)), u.mean((1, 2, 3)))


def test_residual_forcing_is_zero_for_a_matching_field_and_nonzero_otherwise():
    shape = (16, 16, 16)
    spec = nest.NestSpec(shape, 0.01, 1.0, 1e-4, wall_model=False)
    geom = nest.make_geom(np.zeros(shape, bool), (8, 8, 8))
    env = _env_uniform([1.0, 0, 0])
    s = nest.init_state(spec, geom, env, (0.085,) * 3)
    assert np.abs(nest.residual_forcing(spec, s, env, 2)).max() < 1e-4
    r = nest.residual_forcing(spec, s, _env_uniform([0.7, 0, 0]), 2)
    assert r.shape == (3, 8, 8, 8) and np.allclose(r[0], 0.3, atol=1e-3)


def test_two_nests_chain_through_grid_field():
    """Coarse nest (2 dx) feeds a fine nest through trilinear interpolation: the fine one in a uniform stream stays uniform."""
    cs = nest.NestSpec((12, 12, 12), 0.02, 1.0, 1e-4, wall_model=False, sponge=2)
    geom = nest.make_geom(np.zeros((12, 12, 12), bool), (6, 6, 6))
    env = _env_uniform([1.0, 0.0, 0.0])
    st0 = nest.init_state(cs, geom, env, (0.13,) * 3)
    _, u = lbm.moments(st0.f)
    coarse = nest.grid_field(np.asarray(u) * cs.dx / cs.dt, (0.01, 0.01, 0.01), 0.02)
    fs = nest.NestSpec((16, 16, 16), 0.01, 1.0, 1e-4, wall_model=False, sponge=2)
    fg = nest.make_geom(np.zeros((16, 16, 16), bool), (8, 8, 8))
    p0 = np.array([0.1, 0.1, 0.1])
    _, ser = nest.simulate(fs, coarse, fg, p0, (jnp.asarray(p0, jnp.float32), jnp.zeros(3, jnp.float32)), 50)
    assert ser["res"].max() < 1e-3 and nest.mass_drift(ser) < 1e-3


def test_neq_ratio_formula():
    assert nest.neq_ratio(0.6, 0.7, 2) == pytest.approx(0.7 / 1.2)
    assert nest.neq_ratio(1.0, 1.0, 1) == 1.0
    # viscosity match across a 2:1 interface (acoustic scaling): tau_f - 1/2 = 2 (tau_c - 1/2)
    assert nest.neq_ratio(0.6, 0.7, 2) < 1.0 < nest.neq_ratio(0.6, 1.5, 2)


def test_convergence_and_mass_helpers():
    ok, dev = nest.running_mean_ok(np.ones(90))
    assert ok and dev == 0
    drifting = np.concatenate([np.ones(60), np.linspace(1, 3, 30)])
    assert not nest.running_mean_ok(drifting)[0]
    assert nest.mass_drift({"mass": np.array([100.0, 100.0, 100.5])}) == pytest.approx(0.005)


# ------------------------------------------------------------------ curved walls (Bouzidi) and the native sphere
def test_ellipsoid_wall_distance_for_a_sphere():
    shape = (24, 24, 24)
    q = lbm.ellipsoid_q(shape, (12, 12, 12), (3.6, 3.6, 3.6))
    assert q[1][8, 12, 12] == pytest.approx(0.4)                          # cell 4 left of the centre, wall at 3.6: t = 0.4
    assert q[2][16, 12, 12] == pytest.approx(0.4)                         # mirror image, direction -x
    assert q[1][3, 12, 12] == 0.5 and q[0].min() == 0.5                   # no crossing -> halfway default
    solid = nest._sphere(shape, (12, 12, 12), 3.6)
    link = np.asarray(lbm.links(jnp.asarray(solid)))
    assert ((q[1:] > 0) & (q[1:] <= 1)).all() and (q[link] > 0).all()


@given(st.floats(2.5, 5.0), st.floats(-0.4, 0.4))
@settings(max_examples=15, deadline=None)
def test_wall_distance_is_inside_the_link_for_every_wall_link(r, off):
    shape = (20, 20, 20)
    c = (10 + off, 10.0, 10.0)
    q = lbm.ellipsoid_q(shape, c, (r, r, r))
    link = np.asarray(lbm.links(jnp.asarray(nest._sphere(shape, c, r))))
    assert ((q[link] > 0) & (q[link] <= 1)).all()
    # each link's fractional distance puts the wall exactly on the sphere
    g = np.stack(np.meshgrid(*[np.arange(n) for n in shape], indexing="ij")).astype(float)
    k, ix = np.nonzero(link.reshape(19, -1))
    pts = g.reshape(3, -1)[:, ix] + lbm.C19[k].T * q.reshape(19, -1)[k, ix]
    d = np.linalg.norm(pts - np.array(c).reshape(3, 1), axis=0)
    assert np.abs(d - r).max() < 1e-4


def test_bouzidi_with_halfway_distances_is_the_plain_bounce_back_and_otherwise_differs():
    shape = (16, 16, 16)
    solid = nest._sphere(shape, (8, 8, 8), 3.0)
    link = lbm.links(jnp.asarray(solid))
    rng = np.random.default_rng(0)
    f = lbm.feq(jnp.ones(shape), jnp.asarray(rng.normal(0, 0.03, (3,) + shape), jnp.float32))
    fs, rho = lbm.stream(f), jnp.ones(shape)
    a, Fa = lbm.bounce_back(f, fs, link, rho, jnp.zeros(3))
    b, Fb = lbm.bounce_back(f, fs, link, rho, jnp.zeros(3), qdist=jnp.full(link.shape, 0.5))
    assert np.allclose(np.asarray(a), np.asarray(b), atol=1e-6) and np.allclose(np.asarray(Fa), np.asarray(Fb), atol=1e-5)
    q = jnp.asarray(lbm.ellipsoid_q(shape, (8, 8, 8), (3.0,) * 3))
    c, Fc = lbm.bounce_back(f, fs, link, rho, jnp.zeros(3), qdist=q)
    assert not np.allclose(np.asarray(c), np.asarray(a), atol=1e-4)


def test_native_sphere_curved_wall_changes_the_drag_and_all_options_run():
    kw = dict(d=6, domain=(8, 4, 4), steps=500)
    curved = nest.sphere_drag(20.0, **kw)
    stair = nest.sphere_drag(20.0, bouzidi=False, **kw)
    assert curved["cd"] > 1 and stair["cd"] > 1 and curved["cd"] != pytest.approx(stair["cd"], rel=0.005)
    assert curved["shape"] == (48, 24, 24) and len(curved["history"]) >= 20
    per = nest.sphere_drag(20.0, lateral="periodic", **kw)
    assert np.isfinite(per["cd"])
    les = nest.sphere_drag(1000.0, d=6, domain=(8, 4, 4), steps=200)         # re >= 500 switches Smagorinsky on
    assert np.isfinite(les["cd"])
    fs = nest.sphere_drag(20.0, lateral="freeslip", **kw)                   # duct of specular walls: shape grows by the 2-cell slabs
    assert fs["shape"] == (48, 28, 28) and np.isfinite(fs["cd"]) and fs["cd"] > 1 and fs["cd"] != pytest.approx(curved["cd"], rel=0.01)


def test_stack_geoms_mixes_curved_and_halfway_bodies():
    shape = (16, 16, 16)
    a = nest.make_geom(nest._sphere(shape, (8, 8, 8), 3.0), (8, 8, 8), qdist=lbm.ellipsoid_q(shape, (8, 8, 8), (3.0,) * 3))
    b = nest.make_geom(nest._sphere(shape, (8, 8, 8), 2.0), (8, 8, 8))
    g = nest.stack_geoms([a, b])
    assert g.qd.shape == (2, 19) + shape and float(g.qd[1].min()) == 0.5
    h = nest.stack_geoms([b, b])
    assert h.qd is None


def test_body_force_accelerates_a_periodic_fluid_exactly():
    shape = (6, 6, 6)
    g = 2e-5
    spec = nest.NestSpec(shape, 0.01, 1.0, 1e-4, wall_model=False, periodic=(True, True, True), body_force=(g, 0.0, 0.0))
    geom = nest.make_geom(np.zeros(shape, bool), (3, 3, 3), periodic=spec.periodic)
    p0 = np.array([0.035] * 3)
    params = (jnp.asarray(p0, jnp.float32), jnp.zeros(3, jnp.float32))
    state, ser = nest.simulate(spec, _env_uniform([0.0, 0.0, 0.0]), geom, p0, params, 400, chunk=200)
    _, u = lbm.moments(state.f)
    assert float(u[0].mean()) == pytest.approx(g * 400, rel=0.02) and abs(float(u[1].mean())) < 1e-6    # first-order forcing: u = g t
    assert ser["mass"].std() / ser["mass"].mean() < 1e-5


def test_stack_geoms_pads_near_wall_lists_of_different_length():
    shape = (16, 16, 16)
    a = nest.make_geom(nest._sphere(shape, (8, 8, 8), 3.0), (8, 8, 8))
    b = nest.make_geom(nest._sphere(shape, (8, 8, 8), 2.0), (8, 8, 8))
    g = nest.stack_geoms([a, b])
    assert g.ws.near.shape[0] == 2 and g.ws.near.shape[2] == max(a.ws.near.shape[1], b.ws.near.shape[1])
    assert float(g.ws.near_damp[1, -1]) == 0.0 or a.ws.near.shape[1] == b.ws.near.shape[1]


def test_simulate_steps_hook_cuts_the_run_to_whole_chunks():
    shape = (12, 12, 12)
    spec = nest.NestSpec(shape, 0.01, 1.0, 1e-4, wall_model=False, periodic=(True, True, True))
    geom = nest.make_geom(np.zeros(shape, bool), (6, 6, 6), periodic=spec.periodic)
    p0 = np.array([0.065] * 3)
    params = (jnp.asarray(p0, jnp.float32), jnp.zeros(3, jnp.float32))
    seen = []

    def hook(done, elapsed):
        seen.append((done, elapsed))
        return 150 if done == 50 else 10 ** 6                                 # after the first chunk: stop at 150
    _, ser = nest.simulate(spec, _env_uniform([0.0, 0.0, 0.0]), geom, p0, params, 400, chunk=50, steps_hook=hook)
    assert len(ser["mass"]) == 150 and [d for d, _ in seen] == [50, 100, 150] and all(e >= 0 for _, e in seen)
    _, ser = nest.simulate(spec, _env_uniform([0.0, 0.0, 0.0]), geom, p0, params, 200, chunk=50, steps_hook=lambda d, e: 0)
    assert len(ser["mass"]) == 50                                             # a hook cannot un-run what is done
