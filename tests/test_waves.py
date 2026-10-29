import numpy as np
import pytest
from hypothesis import given, settings, strategies as st

from cafe import receipts as R
from cafe.pm.env import conventions as cv
from cafe.pm.env import waves as W

F, TH_U, TH = W._grid()
G = W.G
SW_MATH = np.radians(-135.0)                      # UMWM dwd for waves travelling toward the south-west
HS_ = st.floats(0.2, 8.0)
TP_ = st.floats(3.0, 18.0)
U_ = st.floats(0.5, 20.0)
DIR_ = st.floats(0.0, 359.0)
fast = settings(max_examples=25, deadline=None)


def _negated(sp, deg):
    return -np.stack([sp * np.sin(np.radians(deg)), sp * np.cos(np.radians(deg))], -1)


def swell(hs=1.5, tp=10.0, d=90.0, mss=0.02, u10=6.0):
    return W.spectrum_from_params(hs, tp, d, mss, u10, F, TH)


def prop_dir(rz, n=6000, seed=0):
    """Compass direction waves propagate toward, from finite differences of eta only."""
    r = np.random.default_rng(seed)
    x, y, t = r.uniform(-3000, 3000, n), r.uniform(-3000, 3000, n), r.uniform(0, 3600, n)
    return float(cv.to_deg(W._propagation(rz, x, y, t)))


def sw_restart_spectrum():
    """E from a UMWM-style F with all energy in the math-radian bin containing -135 degrees, via the file convention."""
    E0 = swell(2.0, 12.0, 225.0)
    Fu, k = W._restart_from_E(E0, F, TH_U)
    return W.spectrum_from_restart(Fu, k, F, TH_U), E0


# ---------------------------------------------------------------- spectrum_from_params

@fast
@given(HS_, TP_, DIR_, st.floats(0.0, 0.2), U_)
def test_hs_reproduced_exactly_by_renormalisation(hs, tp, d, mss, u10):
    E = W.spectrum_from_params(hs, tp, d, mss, u10, F, TH)
    assert np.all(E >= 0) and np.isclose(W.hs_of(E, F, TH), hs, rtol=1e-9)


@fast
@given(HS_, TP_, DIR_, U_)
def test_mss_reached_when_in_range(hs, tp, d, u10):
    lo = W.mean_square_slope(W.spectrum_from_params(hs, tp, d, 0.0, u10, F, TH), F, TH)
    hi = W.mean_square_slope(W.spectrum_from_params(hs, tp, d, 9.0, u10, F, TH), F, TH)
    target = 0.5 * (lo + hi)
    got = W.mean_square_slope(W.spectrum_from_params(hs, tp, d, target, u10, F, TH), F, TH)
    assert hi < 1.02 * lo or np.isclose(got, target, rtol=1e-6)      # reachable -> matched; else the short sea is absent


def test_mss_matches_target_and_clips():
    E = swell(2.0, 14.0, 225.0, 0.004, 4.0)
    assert np.isclose(W.mean_square_slope(E, F, TH), 0.004, rtol=1e-6)
    lo = W.mean_square_slope(swell(2.0, 14.0, 225.0, 0.0, 4.0), F, TH)
    hi = W.mean_square_slope(swell(2.0, 14.0, 225.0, 9.0, 4.0), F, TH)
    assert lo < 0.004 < hi                                    # clipped at both ends: all-primary, and half short sea
    assert np.isclose(W.hs_of(swell(2.0, 14.0, 225.0, 9.0, 4.0), F, TH), 2.0, rtol=1e-9)


def test_swell_versus_wind_sea_branch():
    sw = swell(2.0, 14.0, 90.0, 0.004, 4.0)                    # cp/U10 = 3.5: swell
    ws = swell(2.0, 4.0, 90.0, 0.1, 12.0)                      # cp/U10 = 0.5: wind sea
    assert F[np.argmax(sw.sum(1))] == pytest.approx(1 / 14, rel=0.12)
    assert F[np.argmax(ws.sum(1))] == pytest.approx(1 / 4, rel=0.12)
    # swell is narrower in direction than a young wind sea
    width = lambda E: np.sqrt(np.sum(E.sum(0) * (np.cos(np.radians(TH - 90)) < 0.9)) / np.sum(E))
    assert width(sw) < width(ws)


def test_direction_toward_and_vectorised_shape():
    E = W.spectrum_from_params(np.array([1.0, 2.0, 3.0]), 10.0, np.array([0.0, 90.0, 225.0]), 0.02, 6.0, F, TH)
    assert E.shape == (3, 37, 32)
    peak = TH[np.argmax(E.sum(1), axis=-1)]
    for pk, want in zip(peak, (0.0, 90.0, 225.0), strict=True):
        assert abs((pk - want + 180) % 360 - 180) <= 6.0       # within half a bin
    assert not np.isclose(peak[1], 270.0, atol=6.0)             # toward east, not from east


def test_zero_wind_and_extreme_tp_are_finite():
    E = W.spectrum_from_params(1.0, 40.0, 10.0, 0.01, 0.0, F, TH)
    assert np.all(np.isfinite(E)) and np.isclose(W.hs_of(E, F, TH), 1.0)
    assert np.all(W.spectrum_from_params(0.0, 10.0, 10.0, 0.0, 5.0, F, TH) == 0)


# ---------------------------------------------------------------- restart spectra

@fast
@given(HS_, TP_, DIR_, U_)
def test_restart_roundtrip_property(hs, tp, d, u10):
    E = W.spectrum_from_params(hs, tp, d, 0.02, u10, F, TH)
    Fu, k = W._restart_from_E(E, F, TH_U)
    assert np.allclose(W.spectrum_from_restart(Fu, k, F, TH_U), E, rtol=1e-9, atol=1e-14)
    assert np.isclose(W.hs_from_restart(Fu, k, F, TH_U), hs, rtol=1e-9)


def test_restart_batched_points():
    E = np.stack([swell(1.0), swell(2.5, 12.0, 40.0)])
    Fu = np.stack([W._restart_from_E(e, F, TH_U)[0] for e in E])
    k = np.stack([W._restart_from_E(e, F, TH_U)[1] for e in E])
    assert np.allclose(W.hs_from_restart(Fu, k, F, TH_U), [1.0, 2.5])
    assert np.allclose(W.spectrum_from_restart(Fu, k, F, TH_U), E)


def test_wrong_weighting_fails():
    """Dropping the Jacobian's k (treating F as a plain density in (k, theta)) is not a small error."""
    E = swell(2.0, 12.0, 225.0)
    Fu, k = W._restart_from_E(E, F, TH_U)
    dk = k * 2 * np.log(F[1] / F[0])
    wrong = 4 * np.sqrt(np.sum(Fu * dk) * W._dth(TH_U))
    right = 4 * np.sqrt(np.sum(Fu * k * dk) * W._dth(TH_U))
    assert np.isclose(right, 2.0, rtol=1e-3) and abs(wrong / 2.0 - 1) > 0.5
    assert not np.isclose(wrong, W.hs_from_restart(Fu, k, F, TH_U), rtol=0.1)


def test_restart_finite_depth_jacobian():
    """With k(f) from the finite-depth dispersion the Jacobian is 2 pi / cg (UMWM dwn = 2 pi dlnf f / cg)."""
    h = 40.0
    k = W._wavenumber(2 * np.pi * F, h)
    with np.errstate(over="ignore"):
        cg = (2 * np.pi * F / k) * 0.5 * (1 + 2 * k * h / np.sinh(2 * k * h))
    E = swell(1.5, 8.0, 225.0)
    Fu = np.empty((32, 37))
    Fu[np.argsort(cv.math_rad_to_compass_to(TH_U))] = E.T / (k * 2 * np.pi / cg)
    assert np.allclose(W.spectrum_from_restart(Fu, k, F, TH_U), E, rtol=0.01)
    assert np.isclose(W.hs_from_restart(Fu, k, F, TH_U), 1.5, rtol=0.01)


def test_restart_theta_order_and_convention():
    E, E0 = sw_restart_spectrum()
    assert np.array_equal(TH, W.theta_compass(TH_U)) and np.allclose(E, E0)
    pk = TH[np.argmax(E.sum(0))]
    assert abs(pk - 225.0) < 6.0                                # math -135 deg = compass 225, toward SW
    assert not abs(pk - 45.0) < 20 and not abs(pk - 315.0) < 20


def test_restart_conversion_flip_is_detected(monkeypatch):
    E0 = swell(2.0, 12.0, 225.0)
    Fu, k = W._restart_from_E(E0, F, TH_U)
    monkeypatch.setattr(cv, "math_rad_to_compass_to", lambda th: np.mod(90.0 + np.degrees(th), 360.0))
    E = W.spectrum_from_restart(Fu, k, F, TH_U)
    assert not np.allclose(E, E0, rtol=0.1)


# ---------------------------------------------------------------- Stokes drift

def one_bin(B=1e-4, j=24, power=-5):
    E = np.zeros((len(F), len(TH)))
    E[:, j] = B * F ** power / W._dth(TH)
    return E, j


def test_stokes_surface_closed_form_and_direction():
    B = 1e-4
    E, j = one_bin(B)
    f1, f2 = F[0] * np.exp(-W._dlog(F)[0] / 2), F[-1] * np.exp(W._dlog(F)[-1] / 2)
    us = W.stokes_profile(E, F, TH, 0.0)
    assert us.shape == (2,)
    assert np.isclose(np.hypot(*us), 16 * np.pi ** 3 / G * B * (1 / f1 - 1 / f2), rtol=0.005)
    assert np.isclose(cv.to_deg(us), TH[j], atol=0.01)
    # equals 2 m3 / g with m3 = int omega^3 E(omega) d omega, E(omega) = E(f) / 2 pi
    m3 = np.sum((2 * np.pi * F) ** 3 * E.sum(1) * W._dth(TH) / (2 * np.pi) * (2 * np.pi * W._df(F)))
    assert np.isclose(np.hypot(*us), 2 * m3 / G, rtol=1e-9)


def test_stokes_profile_shapes_decay_and_linearity():
    E = np.stack([swell(1.0), swell(2.0, mss=0.08)])
    z = np.array([0.0, -1.0, -5.0, -20.0])
    u = W.stokes_profile(E, F, TH, z)
    assert u.shape == (2, 4, 2)
    s = np.hypot(u[..., 0], u[..., 1])
    assert np.all(np.diff(s, axis=-1) < 0)
    assert np.allclose(s[1] / s[0], 4.0, rtol=1e-3)            # Hs 2 vs 1 at fixed shape: 4x the energy
    assert np.allclose(W.stokes_profile(E, F, TH, -1.0), u[:, 1])


@fast
@given(st.floats(0.05, 0.5), st.floats(0.01, 0.5))
def test_stokes_transport_matches_profile_integral(f_peak, scale):
    E, j = one_bin(scale * 1e-4, 10, -5)
    E[F < f_peak] = 0
    zz = -np.geomspace(1e-4, 4000.0, 6000)
    u = np.hypot(*W.stokes_profile(E, F, TH, zz).T)
    V = np.hypot(*W.stokes_transport(E, F, TH))
    assert np.isclose(np.sum(0.5 * (u[1:] + u[:-1]) * -np.diff(zz)) + u[0] * 1e-4, V, rtol=0.02)


def phillips(fp=0.1, direction=24):
    fine = np.geomspace(0.05, 60.0, 4000)
    Ep = np.zeros((len(fine), len(TH)))
    Ep[:, direction] = np.where(fine > fp, 0.0083 * G ** 2 * (2 * np.pi) ** -4 * fine ** -5, 0.0) / W._dth(TH)
    return Ep, fine


def test_breivik2016_matches_phillips_integral_and_is_not_single_exponential():
    Ep, fine = phillips()
    u0, V = W.stokes_profile(Ep, fine, TH, 0.0), W.stokes_transport(Ep, fine, TH)
    z = np.array([-0.25, -1.0, -3.0, -8.0, -20.0, -60.0])
    ref = np.hypot(*W.stokes_profile(Ep, fine, TH, z).T)
    app = W.stokes_breivik2016(u0, V, z)
    assert app.shape == (6, 2)
    assert np.allclose(np.hypot(*app.T), ref, rtol=0.03)
    assert np.isclose(cv.to_deg(app[2]), cv.to_deg(u0), atol=1e-6)
    s0, kk = np.hypot(*u0), np.hypot(*u0) / (2 * np.hypot(*V))           # single exponential fitted to the same u0 and V
    assert np.abs(s0 * np.exp(2 * kk * z[-2]) / ref[-2] - 1) > 0.5
    assert np.allclose(W.stokes_breivik2016(u0, V, 0.0), u0)
    assert W.stokes_breivik2016(u0, V, -1.0).shape == (2,)


def test_breivik2016_transport_identity_and_zero_transport():
    u0 = np.array([0.1, 0.0])
    for beta in (1.0, 0.5):
        V = u0 / (2 * (u0[0] * (1 - 2 * beta / 3) / (2 * 0.04)))          # chosen so that k = 0.04
        z = -np.geomspace(1e-5, 600.0, 20000)
        u = W.stokes_breivik2016(u0, V, z, beta)[:, 0]
        integral = np.sum(0.5 * (u[1:] + u[:-1]) * -np.diff(z)) + u[0] * 1e-5
        assert np.isclose(integral, V[0], rtol=0.01)
    assert np.all(np.isfinite(W.stokes_breivik2016(np.zeros(2), np.zeros(2), np.array([-1.0, -2.0]))))


# ---------------------------------------------------------------- dispersion and bins

@given(st.floats(0.03, 2.0), st.floats(3.0, 5000.0))
def test_wavenumber_satisfies_dispersion(f, h):
    w = 2 * np.pi * f
    k = W._wavenumber(w, h)
    assert np.isclose(G * k * np.tanh(k * h), w ** 2, rtol=1e-9)


def test_bins_and_moments():
    assert np.isclose(W._dth(TH), np.pi / 16)
    assert np.allclose(W._df(F), F * np.log(1.1225), rtol=2e-3)
    E = np.ones((37, 32))
    assert np.isclose(W.moment(E, F, TH, 0), np.sum(W._df(F)) * 2 * np.pi)
    assert np.isclose(W.hs_of(E, F, TH), 4 * np.sqrt(W.moment(E, F, TH)))


# ---------------------------------------------------------------- Realization

def test_components_conserve_variance_and_never_share_frequencies():
    E = swell(2.0, 10.0, 90.0)
    r = W.Realization(E, F, TH, seed=4, n_sub=3)
    assert np.isclose(np.sum(r.a ** 2) / 2, W.moment(E, F, TH), rtol=1e-12)
    assert len(np.unique(r.w)) == r.w.size
    assert np.allclose(r.k, r.w ** 2 / G, rtol=1e-6)            # deep
    # every component stays inside its own bin: frequency within the bin, direction within the bin
    fb = np.repeat(F, 32 * 3)
    assert np.all(np.abs(np.log(r.w[0] / (2 * np.pi * fb))) <= W._dlog(F)[0] / 2 + 1e-12)
    cdir = cv.to_deg(np.stack([r.dx[0], r.dy[0]], -1))
    tb = np.tile(np.repeat(TH, 3), 37)
    assert np.all(np.abs((cdir - tb + 180) % 360 - 180) <= np.degrees(W._dth(TH)) / 2 + 1e-9)


def test_seed_determinism_and_finite_depth_dispersion():
    E = swell()
    a, b = W.Realization(E, F, TH, seed=5), W.Realization(E, F, TH, seed=5)
    c = W.Realization(E, F, TH, seed=6, depth=25.0)
    assert np.array_equal(a.phi, b.phi) and not np.array_equal(a.phi, c.phi)
    assert np.allclose(G * c.k * np.tanh(c.k * 25.0), c.w ** 2, rtol=1e-9)
    assert not c.second_order_deep_ok and a.second_order_deep_ok


def test_variance_and_ensemble_shapes():
    E = np.stack([swell(1.0), swell(2.0)])
    r = W.Realization(E, F, TH, depth=np.array([np.inf, 500.0]), seed=1, n_sub=2)
    x = np.random.default_rng(0).uniform(-4000, 4000, 8000)
    eta = r.eta(x, x[::-1], 100.0 + 0 * x)
    assert eta.shape == (2, 8000)
    assert np.allclose(np.var(eta, axis=1), np.array([1.0, 4.0]) / 16, rtol=0.1)
    assert r.slope(x[:5], x[:5], 0.0).shape == (2, 5, 2)
    assert r.velocity(x[:5], x[:5], -3.0, 0.0).shape == (2, 5, 3)
    assert r.eta(1.0, 2.0, 3.0).shape == (2,)
    assert r.eps.shape == (2,) and r.hs.shape == (2,)


def test_chunking_does_not_change_results(monkeypatch):
    E = swell()
    x = np.linspace(0, 900, 37)
    ref = W.Realization(E, F, TH, seed=2, n_sub=1, second_order=True, n2=8)
    monkeypatch.setattr(W.Realization, "_budget", 1)
    small = W.Realization(E, F, TH, seed=2, n_sub=1, second_order=True, n2=8)
    assert small._step == 1
    for name, args in (("eta", (x, 2 * x, 7.0)), ("slope", (x, 2 * x, 7.0)), ("velocity", (x, 2 * x, -2.0, 7.0))):
        assert np.allclose(getattr(ref, name)(*args), getattr(small, name)(*args))


def test_no_repeat_and_autocorrelation_detects_repeat():
    t = np.arange(0, 3600.0, 1.0)
    for seed in range(4):
        r = W.Realization(swell(1.5, 9.0, 225.0), F, TH, seed=seed)
        assert W._max_autocorr(r.eta(0 * t, 0 * t, t), 1.0, 600, 1800) < 0.6
    # a regular frequency grid repeats: lines at multiples of 1/1200 Hz
    rng = np.random.default_rng(0)
    comb = sum(np.cos(2 * np.pi * (n / 1200.0) * t + rng.uniform(0, 6.3)) for n in range(60, 100, 3))
    assert W._max_autocorr(comb, 1.0, 600, 1800) > 0.9


# ---- direction conventions

def test_realization_propagates_toward_southwest_from_umwm_radians():
    E, _ = sw_restart_spectrum()
    rz = W.Realization(E, F, TH, seed=3)
    assert abs(prop_dir(rz) - 225.0) < 8.0
    assert abs(float(cv.to_deg(W.stokes_profile(E, F, TH, 0.0))) - 225.0) < 8.0
    r = np.random.default_rng(1)
    x, y, t = r.uniform(-3000, 3000, 6000), r.uniform(-3000, 3000, 6000), r.uniform(0, 3600, 6000)
    s = rz.slope(x, y, t)
    u = rz.velocity(x, y, 0.0, t)
    eta = rz.eta(x, y, t)
    # mean orbital velocity correlated with elevation points the way the waves go (SW: negative east, negative north)
    cu = (eta[:, None] * u[:, :2]).mean(0)
    assert cu[0] < 0 and cu[1] < 0 and abs(float(cv.to_deg(cu)) - 225.0) < 8.0
    assert np.isclose(np.mean(s[:, 0] ** 2 + s[:, 1] ** 2), W.mean_square_slope(E, F, TH), rtol=0.15)


def test_flipped_kx_sign_is_detected(monkeypatch):
    E, _ = sw_restart_spectrum()
    monkeypatch.setattr(cv, "vec_from_to", _negated)
    rz = W.Realization(E, F, TH, seed=3)
    assert abs(prop_dir(rz) - 225.0) > 90.0                      # waves now go north-east


def test_flipped_conversion_is_detected(monkeypatch):
    Fu, k = W._restart_from_E(swell(2.0, 12.0, 225.0), F, TH_U)
    monkeypatch.setattr(cv, "math_rad_to_compass_to", lambda th: np.mod(90.0 + np.degrees(th), 360.0))
    E = W.spectrum_from_restart(Fu, k, F, TH_U)
    assert abs(prop_dir(W.Realization(E, F, TH, seed=3)) - 225.0) > 20.0


# ---- kinematics

def test_single_component_phase_speed_and_dispersion_sign():
    r, i = W._single(F, TH)
    assert np.isclose(W._phase_speed(r, i), G / r.w[0, i], rtol=0.01)
    # a crest at t = 0 has moved toward +d after dt
    x0, y0 = W._on_ray(r, i, -r.phi[0, i] / r.k[0, i])
    c = G / r.w[0, i]
    d = np.array([r.dx[0, i], r.dy[0, i]])
    assert r.eta(x0 + 1.0 * c * d[0], y0 + 1.0 * c * d[1], 1.0) > r.eta(x0 - 1.0 * c * d[0], y0 - 1.0 * c * d[1], 1.0)


def test_linear_orbital_velocity_matches_theory_and_continuity():
    E = np.zeros((37, 32))
    a = 0.05
    E[18, 8] = a ** 2 / 2 / (W._df(F)[18] * W._dth(TH))
    for h in (np.inf, 30.0):
        r = W.Realization(E, F, TH, depth=h, n_sub=1, second_order=False, stretch=False)
        i = int(np.argmax(r.a[0]))
        w, k = r.w[0, i], r.k[0, i]
        z = -5.0
        x, y = W._on_ray(r, i, -r.phi[0, i] / k)                 # phase 0: crest, u along d, w = 0
        u = r.velocity(x, y, z, 0.0)
        hh = min(h, W.DEEP)
        amp = a * w * np.cosh(k * (z + hh)) / np.sinh(k * hh) if h < np.inf else a * w * np.exp(k * z)
        assert np.isclose(u[0] * r.dx[0, i] + u[1] * r.dy[0, i], amp, rtol=1e-6) and abs(u[2]) < 1e-9
        # phase pi/2: w is its extreme and positive (water rises ahead of the crest), u = 0
        x2, y2 = W._on_ray(r, i, (np.pi / 2 - r.phi[0, i]) / k)
        v2 = r.velocity(x2, y2, z, 0.0)
        wamp = a * w * np.sinh(k * (z + hh)) / np.sinh(k * hh) if h < np.inf else a * w * np.exp(k * z)
        assert np.isclose(v2[2], wamp, rtol=1e-6)
        # incompressibility du/ds + dw/dz = 0 along the propagation direction
        ds, dz = 1e-3, 1e-3
        xa, ya = W._on_ray(r, i, (np.pi / 3 - r.phi[0, i]) / k)
        d = np.array([r.dx[0, i], r.dy[0, i]])
        uh = lambda s, zz, r=r, xa=xa, ya=ya, d=d: r.velocity(xa + s * d[0], ya + s * d[1], zz, 0.0)[:2] @ d
        dwdz = (r.velocity(xa, ya, z + dz, 0.0)[2] - r.velocity(xa, ya, z - dz, 0.0)[2]) / (2 * dz)
        div = (uh(ds, z) - uh(-ds, z)) / (2 * ds) + dwdz
        assert abs(div) < 1e-6 * a * w * k


def test_wheeler_stretching_and_surface_clipping():
    E = swell(2.0, 8.0, 0.0)
    rs = W.Realization(E, F, TH, seed=1, stretch=True)
    rl = W.Realization(E, F, TH, seed=1, stretch=False)
    x = np.linspace(0, 400, 50)
    eta = rs.eta(x, 0 * x, 0.0)
    crest = x[np.argmax(eta)]
    us, ul = rs.velocity(crest, 0.0, 0.0, 0.0), rl.velocity(crest, 0.0, 0.0, 0.0)
    assert not np.allclose(us, ul)
    # above the surface the surface value is returned, so any height above the crest gives the same velocity
    top = rs.eta(crest, 0.0, 0.0) + 1.0
    assert np.allclose(rs.velocity(crest, 0.0, top, 0.0), rs.velocity(crest, 0.0, top + 50.0, 0.0))
    assert np.allclose(rl.velocity(crest, 0.0, 5.0, 0.0), rl.velocity(crest, 0.0, 0.0, 0.0))


# ---- second order

def test_second_order_switch_threshold():
    below, above = W.Realization(swell(1.5), F, TH), W.Realization(swell(3.0), F, TH)
    assert below.eps < 0.05 < above.eps and below.second_order is np.False_ and above.second_order is np.True_
    r = W.Realization(np.stack([swell(1.5), swell(3.0)]), F, TH)
    assert r.second_order.tolist() == [False, True]
    assert W.Realization(swell(1.5), F, TH, second_order=True).second_order
    assert not W.Realization(swell(3.0), F, TH, second_order=False).second_order


def test_second_order_changes_only_flagged_members():
    E = np.stack([swell(1.5), swell(3.0)])
    x = np.linspace(0, 2000, 400)
    on = W.Realization(E, F, TH, seed=1, n_sub=1)
    off = W.Realization(E, F, TH, seed=1, n_sub=1, second_order=False)
    d = on.eta(x, 0 * x, 5.0) - off.eta(x, 0 * x, 5.0)
    assert np.all(d[0] == 0) and np.abs(d[1]).max() > 1e-3
    gs = on.slope(x, 0 * x, 5.0) - off.slope(x, 0 * x, 5.0)
    assert np.all(gs[0] == 0) and np.abs(gs[1]).max() > 1e-4
    # the second-order slope is the derivative of the second-order elevation
    h = 1e-3
    d2 = lambda xx: on.eta(xx, 0 * x, 5.0)[1] - off.eta(xx, 0 * x, 5.0)[1]
    assert np.allclose((d2(x + h) - d2(x - h)) / (2 * h), gs[1, :, 0], atol=1e-5)
    assert np.allclose(W._fd_grad(on, x, 0 * x, 5.0)[1], on.slope(x, 0 * x, 5.0)[1], atol=2e-5)     # total slope = d(eta)/dx, dy


def test_stokes_crest_single_component():
    r, i = W._single(F, TH)
    x, y = W._on_ray(r, i, -r.phi[0, i] / r.k[0, i])
    assert np.isclose(r.eta(x, y, 0.0), 0.3 + r.k[0, i] * 0.3 ** 2 / 2, rtol=1e-6)
    x, y = W._on_ray(r, i, (np.pi - r.phi[0, i]) / r.k[0, i])
    assert np.isclose(r.eta(x, y, 0.0), -0.3 + r.k[0, i] * 0.3 ** 2 / 2, rtol=1e-6)    # trough is flatter


def test_sharma_dean_pair_coefficients():
    """Deep-water limits: Stokes; collinear (k1 + k2)/2 and -|k1 - k2|/2 (Longuet-Higgins & Stewart 1960);
    opposing equal waves have no uniform 2w oscillation (volume conservation)."""
    w = np.array([[1.0, 1.7]])
    k = w ** 2 / G
    one = np.ones((1, 2))
    ii, jj, cp, cm = W._sd_coeffs(one, w, one, 0 * one)
    assert ii.tolist() == [0, 0, 1] and jj.tolist() == [0, 1, 1]
    assert np.allclose(cp[0, [0, 2]], 0.25 * 2 * k[0])                 # Stokes: k a^2 / 2 cos 2psi
    assert np.isclose(cp[0, 1], 0.5 * (k[0, 0] + k[0, 1]))
    assert np.isclose(cm[0, 1], -0.5 * abs(k[0, 0] - k[0, 1])) and np.allclose(cm[0, [0, 2]], 0)
    ox, oy = np.array([[1.0, -1.0]]), np.zeros((1, 2))
    _, _, cp2, cm2 = W._sd_coeffs(one, np.array([[1.0, 1.0]]), ox, oy)
    assert abs(cp2[0, 1]) < 1e-12 and np.isclose(cm2[0, 1], 0.5 * 2 / G)


# ---- encounter spectrum

def test_encounter_spectrum_conserves_variance_and_doppler_shifts():
    E = swell(1.5, 10.0, 90.0)
    r = W.Realization(E, F, TH, seed=1, n_sub=2)
    fe0, S0 = r.encounter_spectrum((0.0, 0.0))
    assert np.isclose(np.sum(S0 * np.diff(np.linspace(0, fe0[-1] + (fe0[1] - fe0[0]) / 2, 401))), W.moment(E, F, TH), rtol=1e-6)
    mean = lambda fe, S: np.sum(fe * S) / np.sum(S)
    edges = np.linspace(0, 6, 241)
    f_with = mean(*r.encounter_spectrum((5.0, 0.0), edges=edges))        # waves travel east
    f_against = mean(*r.encounter_spectrum((-5.0, 0.0), edges=edges))
    assert f_against > mean(fe0, S0) > f_with > 0 and f_against > 1.2 * f_with   # moving against the waves raises f_e
    # dropped components outside user edges
    fe, S = r.encounter_spectrum((0.0, 0.0), edges=np.linspace(0, 0.1, 11))
    assert np.sum(S * 0.01) < W.moment(E, F, TH)


def test_encounter_spectrum_single_component_and_batch():
    r, i = W._single(F, TH)
    V = 3.0 * np.array([r.dx[0, i], r.dy[0, i]])                       # moving with the waves at 3 m/s
    fe, S = r.encounter_spectrum(V, edges=np.linspace(0, 1, 2001))
    want = abs(r.w[0, i] - r.k[0, i] * 3.0) / (2 * np.pi)
    assert np.isclose(fe[np.argmax(S)], want, atol=1e-3)
    fe2, S2 = r.encounter_spectrum(-V, edges=np.linspace(0, 1, 2001))
    assert np.isclose(fe2[np.argmax(S2)], (r.w[0, i] + r.k[0, i] * 3.0) / (2 * np.pi), atol=1e-3)
    rb = W.Realization(np.stack([swell(), swell(2.0)]), F, TH, n_sub=1)
    assert rb.encounter_spectrum([1.0, 0.0])[1].shape == (2, 400)


# ---------------------------------------------------------------- receipts

def run_receipts():
    n0 = len(R.OUT)
    W.receipts()
    return [r for r in R.OUT[n0:] if r.get("ok") is not None]


def failed(rs):
    return [r["claim"] for r in rs if not r["ok"]]


def test_receipts_pass():
    rs = run_receipts()
    assert len(rs) >= 26 and failed(rs) == []


def test_receipts_fail_on_conversion_error(monkeypatch):
    monkeypatch.setattr(cv, "math_rad_to_compass_to", lambda th: np.mod(90.0 + np.degrees(th), 360.0))
    assert any("propagation direction" in c or "Stokes drift direction" in c for c in failed(run_receipts()))


def test_receipts_fail_on_kx_sign(monkeypatch):
    monkeypatch.setattr(cv, "vec_from_to", _negated)
    bad = failed(run_receipts())
    assert any("propagation direction" in c for c in bad)


def test_receipts_fail_on_phase_sign(monkeypatch):
    """Flip only the sign of k.x in the phase, leaving the analytic slope and everything else alone."""
    def phase(self, x, y, t):
        return (-self.k[:, None] * (self.dx[:, None] * x[None, :, None] + self.dy[:, None] * y[None, :, None])
                - self.w[:, None] * t[None, :, None] + self.phi[:, None])
    monkeypatch.setattr(W.Realization, "_phase", phase)
    bad = failed(run_receipts())
    assert any("phase speed" in c for c in bad) and any("propagation direction" in c for c in bad)


def test_receipts_fail_on_stokes_factor_two(monkeypatch):
    orig = W.stokes_profile
    monkeypatch.setattr(W, "stokes_profile", lambda *a: orig(*a) / 2)
    assert any("Stokes surface drift" in c for c in failed(run_receipts()))


def test_receipts_fail_on_single_exponential(monkeypatch):
    def expo(us0, V, z, beta=1.0):
        us0, V, z = np.asarray(us0), np.asarray(V), np.atleast_1d(z)
        k = np.hypot(*us0) / (2 * np.hypot(*V))
        return us0[None, :] * np.exp(2 * k * z)[:, None]
    monkeypatch.setattr(W, "stokes_breivik2016", expo)
    assert any("Breivik" in c for c in failed(run_receipts()))


def test_receipts_fail_on_restart_weighting(monkeypatch):
    def no_k(Fv, k, f, th):
        dk = np.gradient(np.log(k), axis=-1)[..., None, :]
        return 4 * np.sqrt(np.sum(Fv * k[..., None, :] * dk, axis=(-2, -1)) * W._dth(th))
    monkeypatch.setattr(W, "hs_from_restart", no_k)
    assert any("hs_from_restart" in c for c in failed(run_receipts()))


def test_receipts_fail_on_second_order_threshold(monkeypatch):
    monkeypatch.setattr(W, "EPS_SECOND", 0.5)
    assert any("second-order switch" in c for c in failed(run_receipts()))


def test_receipts_fail_when_second_order_coefficient_is_wrong(monkeypatch):
    orig = W._sd_coeffs
    def bad(*a):
        ii, jj, cp, cm = orig(*a)
        return ii, jj, -cp, cm
    monkeypatch.setattr(W, "_sd_coeffs", bad)
    assert any("second-order crest" in c for c in failed(run_receipts()))


# ---------------------------------------------------------------- the ages are assumptions.yaml entries

def test_the_wind_sea_and_swell_ages_are_read_from_assumptions_yaml(monkeypatch):
    from cafe.pm.config import assumptions
    a = assumptions()
    for k, v in (("waves.swell_age", 1.2), ("waves.wind_sea_age", 2.0)):
        assert a[k]["value"] == v and a[k]["unit"] == "-" and len(a[k]["why"]) > 40 and len(a[k]["replace_with"]) > 20
    base = swell(1.5, 10.0, 90.0, 0.02, 6.0)
    given = W.spectrum_from_params(1.5, 10.0, 90.0, 0.02, 6.0, F, TH, swell_age=1.2, wind_sea_age=2.0)
    assert np.array_equal(base, given)                                                                                        # the defaults are those values
    table = {"waves.swell_age": 1.2, "waves.wind_sea_age": 5.0}
    monkeypatch.setattr(W, "assumption", lambda k: table[k])
    moved = swell(1.5, 10.0, 90.0, 0.02, 6.0)
    assert not np.allclose(base, moved)  # a different assumption moves it
    assert np.array_equal(moved, W.spectrum_from_params(1.5, 10.0, 90.0, 0.02, 6.0, F, TH, swell_age=1.2, wind_sea_age=5.0))
    table["waves.swell_age"] = 30.0                                                                                           # a huge age: no swell
    assert not np.allclose(moved, swell(1.5, 10.0, 90.0, 0.02, 6.0))
