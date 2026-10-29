"""Directional wave spectra and sea-surface realizations for the pre-mission simulator.

Axes and units (everything here): E[..., f, theta] is a variance density in m^2 / Hz / rad on frequency bins `f` [Hz] and
direction bins `theta` [degrees, compass, direction waves travel TOWARD]. Bins are full-circle and uniform in theta
(dtheta = 2 pi / N) and uniform in ln f; bin width is df = f * dln f (UMWM's rectangle rule, umwm_domain.f90 `dwn`).
Coordinates are x east, y north, z up (0 = mean sea level), metres. Vectors are (east, north[, up]) in the last axis.

Sources (equation numbers as known to the author; the two marked * were not re-read for this module):
  UMWM  umwm_domain_output.f90 / umwm_domain.f90 (github.com/umwm/umwm, read 2026-10-28): F(k, theta) is the
        wavenumber-plane density, swh = 4 sqrt(sum F k dk dtheta), mss = sum F k^3 dk dtheta, dk = 2 pi f dlnf / cg.
  DHH   Donelan, Hamilton & Hui 1985, Phil. Trans. R. Soc. A 315, 509-562: f^-4 spectrum, peak enhancement
        gamma = 1.7 (0.83 < U/cp < 1), 1.7 + 6 log10(U/cp) (1 < U/cp < 5), sigma = 0.08 (1 + 4 (U/cp)^-3).
  JONSWAP* Hasselmann et al. 1973: gamma = 3.3, sigma = 0.07 / 0.09 (used for swell, see _wave_shape).
  Spreading* cos^{2s}(dtheta / 2): Longuet-Higgins et al. 1963; s_p = 11.5 (cp/U10)^2.5 Mitsuyasu et al. 1975;
        s ~ (f/fp)^5 below, (f/fp)^-2.5 above the peak: Hasselmann et al. 1980.
  Wheeler 1970 stretching; second order: deep-water limit of Sharma & Dean 1979 (derived in `_sd_coeffs`;
        equals Longuet-Higgins & Phillips 1962 / Hasselmann 1962), on/off at eps = kp Hs / 2 = 0.05 (brief, Smit et al. 2017).
  Stokes drift: Kenyon 1969; Breivik, Bidlot & Janssen 2016, Ocean Modelling 100, 49-56, eqs 6, 19, 22, 23 (arXiv 1601.08092).
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np
from numpy.typing import ArrayLike, NDArray
from scipy.special import erfc

from . import conventions as cv
from .subgrid import assumption

G = 9.81
DEEP = 1e5                 # "infinite" depth [m]: kh > 390 at the lowest UMWM frequency, tanh = 1 to double precision
EPS_SECOND = 0.05          # steepness above which the second-order correction is applied (brief 2.3)
S_MAX = 60.0               # cos^{2s} narrower than ~10 degrees is below the 11.25-degree bin width
Arr = NDArray[np.floating[Any]]


# ------------------------------------------------------------------ bins and moments

def _dlog(x: Arr) -> Arr:
    return np.gradient(np.log(x))


def _df(f: Arr) -> Arr:
    return f * _dlog(f)


def _dth(theta: ArrayLike) -> float:
    return 2 * np.pi / np.size(theta)


def moment(E: Arr, f: Arr, theta: ArrayLike, n: int = 0) -> Arr:
    """int f^n E df dtheta  [m^2 Hz^n]."""
    m: Arr = np.einsum('...ft,f->...', E, f ** n * _df(f))
    return m * _dth(theta)


def hs_of(E: Arr, f: Arr, theta: ArrayLike) -> Arr:
    return 4 * np.sqrt(moment(E, f, theta, 0))


def mean_square_slope(E: Arr, f: Arr, theta: ArrayLike) -> Arr:
    """Slope variance int k^2 E df dtheta (deep water): UMWM's `mss`, a scalar, so independent of the spreading."""
    return (2 * np.pi) ** 4 / G ** 2 * moment(E, f, theta, 4)


# ------------------------------------------------------------------ spectrum from integrated parameters

def _wave_shape(f: Arr, fp: Arr, om: Arr, swell: NDArray[np.bool_]) -> Arr:
    """Unnormalised E(f). Wind sea: DHH85 (om = U10/cp clipped to 0.83-5). Swell: JONSWAP f^-5 shape, gamma 3.3,
    because DHH's sigma (0.64 at om = 0.83) is far too broad for swell and DHH is not defined for om < 0.83."""
    x = f / fp
    gam = np.where(swell, 3.3, np.where(om < 1, 1.7, 1.7 + 6 * np.log10(om)))
    sig = np.where(swell, np.where(f <= fp, 0.07, 0.09), 0.08 * (1 + 4 / om ** 3))
    base = np.where(swell, x ** -5 * np.exp(-1.25 * x ** -4), x ** -4 * np.exp(-x ** -4))
    shape: Arr = base * gam ** np.exp(-(f - fp) ** 2 / (2 * sig ** 2 * fp ** 2))
    return shape


def _spread(f: Arr, fp: Arr, sp: Arr, theta: Arr, dirs: Arr) -> Arr:
    """cos^{2s}(d/2) on the theta bins with s(f) = sp (f/fp)^5 or ^-2.5, normalised so sum D dtheta = 1."""
    s = np.clip(sp * np.where(f < fp, (f / fp) ** 5, (f / fp) ** -2.5), 1.0, S_MAX)
    d = (np.radians(theta) - np.radians(dirs)[:, None] + np.pi) % (2 * np.pi) - np.pi
    D = np.cos(d / 2)[:, None, :] ** (2 * s[:, :, None])
    return D / (D.sum(-1, keepdims=True) * _dth(theta))


def _unit(f: Arr, theta: Arr, shape: Arr, D: Arr) -> Arr:
    """E for Hs = 1 (m0 = 1/16) with the given frequency shape and spreading."""
    E = shape[:, :, None] * D
    return E / (16 * moment(E, f, theta))[:, None, None]


def spectrum_from_params(hs: ArrayLike, tp: ArrayLike, dir_to_deg: ArrayLike, mss: ArrayLike, u10: ArrayLike, f: ArrayLike, theta_compass_to: ArrayLike,
                         *, swell_age: float | None = None, wind_sea_age: float | None = None) -> Arr:
    """E(f, theta) from the integrated parameters UMWM writes (swh, dwp, dwd, mss) and the 10 m wind.

    Two components, each renormalised on the discrete bins to its own Hs, so 4 sqrt(m0) = hs exactly (the continuous
    shapes lose ~0.5 % on the 37 log bins; the renormalisation removes it, the receipt reports how large it was):
      primary    peak at 1/tp. Swell (JONSWAP shape, narrow) when cp/U10 > swell_age (a fully developed wind sea has
                 U10/cp = 0.83, i.e. cp/U10 = 1.2; DHH85 and Pierson-Moskowitz 1964), otherwise DHH85 wind sea.
      short sea  DHH85 wind sea at U10/cp = wind_sea_age (a developing sea; an assumption, mid-range of DHH's 0.83-5),
                 same direction as the primary. Its share of the variance, w, is the closed-form solution of
                 mss = (hs^2 - w) a_primary + w a_short, clipped to [0, hs^2 / 2] so the primary stays the peak.
    `mss` is the scalar slope variance (UMWM sums F k^3 dk dtheta) and is blind to directional spreading, so it cannot
    fix s as the brief asks; it fixes how much short-wave energy there is. s comes from the Mitsuyasu/Hasselmann law.
    swell_age and wind_sea_age are config/assumptions.yaml waves.swell_age (1.2) and waves.wind_sea_age (2.0) unless given.
    Inputs broadcast; output has their shape + (nf, ntheta)."""
    swell_age = assumption("waves.swell_age") if swell_age is None else swell_age
    wind_sea_age = assumption("waves.wind_sea_age") if wind_sea_age is None else wind_sea_age
    f, theta = np.asarray(f, float), np.asarray(theta_compass_to, float)
    hs, tp, dirs, mss, u10 = np.broadcast_arrays(*(np.asarray(v, float) for v in (hs, tp, dir_to_deg, mss, u10)))
    lead = hs.shape
    hs, tp, dirs, mss, u10 = (v.ravel() for v in (hs, tp, dirs, mss, u10))
    u = np.maximum(u10, 0.5)[:, None]
    fp = np.clip(1 / tp, 1.2 * f[0], f[-1] / 2)[:, None]
    om = u * 2 * np.pi * fp / G                                           # U10 / cp
    A = _unit(f, theta, _wave_shape(f, fp, np.clip(om, 0.83, 5), om < 1 / swell_age),
              _spread(f, fp, 11.5 * om ** -2.5, theta, dirs))
    fw = np.clip(wind_sea_age * G / (2 * np.pi * u), 1.2 * f[0], f[-1] / 3)
    B = _unit(f, theta, _wave_shape(f, fw, np.full_like(fw, wind_sea_age), np.zeros_like(fw, bool)),
              _spread(f, fw, 11.5 * wind_sea_age ** -2.5, theta, dirs))
    aA, aB = mean_square_slope(A, f, theta), mean_square_slope(B, f, theta)
    w = np.where(aB > 1.01 * aA, np.clip((mss - aA * hs ** 2) / (aB - aA), 0, hs ** 2 / 2), 0.0)
    E = (hs ** 2 - w)[:, None, None] * A + w[:, None, None] * B
    return E.reshape(lead + E.shape[1:])


# ------------------------------------------------------------------ UMWM restart spectra

def theta_compass(theta_umwm: ArrayLike) -> Arr:
    """Compass-toward degrees of UMWM's `theta` bins, ascending: the theta axis of spectrum_from_restart's output."""
    return np.sort(cv.math_rad_to_compass_to(np.asarray(theta_umwm, float)))


def spectrum_from_restart(F: ArrayLike, k: ArrayLike, f: Arr, theta: ArrayLike) -> Arr:
    """UMWM restart F(..., th, f) [m^4 rad^-1, wavenumber plane] -> E(..., f, th) [m^2/Hz/rad], th sorted compass-toward.
    E df = F k dk, so E = F k dk/df with dk/df = (k / f) dln k / dln f from the file's own k(f) (exact in deep water,
    where it is 2k/f, and the finite-depth 2 pi / cg to O(dlnf^2)). The k factor is the Jacobian of the polar
    area element k dk dtheta: dropping it is a ~k-fold error, not a rounding one."""
    order = np.argsort(cv.math_rad_to_compass_to(np.asarray(theta, float)))
    k = np.asarray(k, float)[..., None, :]
    dkdf = k * np.gradient(np.log(k), axis=-1) / _df(f)
    return np.swapaxes((np.asarray(F, float) * k * dkdf)[..., order, :], -1, -2)


def hs_from_restart(F: ArrayLike, k: ArrayLike, f: Arr, theta: ArrayLike) -> Arr:
    """4 sqrt(sum F k dk dtheta), UMWM's `swh` (umwm_domain_output.f90): dk = k dln k per log-f bin."""
    k = np.asarray(k, float)[..., None, :]
    return 4 * np.sqrt(np.sum(np.asarray(F, float) * k * k * np.gradient(np.log(k), axis=-1), axis=(-2, -1)) * _dth(theta))


# ------------------------------------------------------------------ Stokes drift

def _dirspec(E: Arr, theta: ArrayLike) -> Arr:
    """int E d dtheta: (..., nf, 2) east/north components per frequency."""
    d: Arr = np.einsum('...ft,tc->...fc', E, cv.vec_from_to(1.0, np.asarray(theta, float)))
    return d * _dth(theta)


def stokes_profile(E: Arr, f: ArrayLike, theta: ArrayLike, z: ArrayLike) -> Arr:
    """Stokes drift (east, north) at z <= 0 from the full spectrum, deep water (Kenyon 1969):
    u_s(z) = 2 int omega k e^{2kz} E d df dtheta. At z = 0 this is (16 pi^3 / g) int f^3 E d df dtheta, which is the
    brief's 2 m3 / g with m3 = int omega^3 E(omega) d omega (angular moment; E(omega) d omega = E(f) df).
    z scalar -> (..., 2); z array (nz,) -> (..., nz, 2)."""
    f, zz = np.asarray(f, float), np.atleast_1d(np.asarray(z, float))
    w = 2 * np.pi * f
    wt = 2 * w * w ** 2 / G * np.exp(2 * w ** 2 / G * zz[:, None]) * _df(f)
    out: Arr = np.einsum('zf,...fc->...zc', wt, _dirspec(E, theta))
    return out[..., 0, :] if np.ndim(z) == 0 else out


def stokes_transport(E: Arr, f: ArrayLike, theta: ArrayLike) -> Arr:
    """int_{-inf}^0 u_s dz = int omega E d df dtheta (deep water): (..., 2)."""
    f = np.asarray(f, float)
    out: Arr = np.einsum('f,...fc->...c', 2 * np.pi * f * _df(f), _dirspec(E, theta))
    return out


def stokes_breivik2016(us0: ArrayLike, transport: ArrayLike, z: ArrayLike, beta: float = 1.0) -> Arr:
    """Breivik et al. 2016 eq 19: u_s(z) = u0 [exp(2 k z) - beta sqrt(-2 pi k z) erfc(sqrt(-2 k z))], the exact Stokes
    profile of a Phillips spectrum (beta = 1) as a function of the surface drift u0 and the transport V (eq 22:
    V = u0 (1 - 2 beta / 3) / (2 k), solved for k, eq 23). Direction is that of `us0`, constant with depth.
    us0, transport (..., 2) east/north; z scalar -> (..., 2), z (nz,) -> (..., nz, 2). z <= 0."""
    us0, V = np.asarray(us0, float), np.asarray(transport, float)
    s0, sv = np.hypot(us0[..., 0], us0[..., 1]), np.hypot(V[..., 0], V[..., 1])
    k = np.divide(s0 * (1 - 2 * beta / 3), 2 * sv, out=np.zeros_like(s0), where=sv > 0)
    zz = np.atleast_1d(np.asarray(z, float))
    q = np.sqrt(-2 * k[..., None] * zz)
    p = np.exp(2 * k[..., None] * zz) - beta * np.sqrt(np.pi) * q * erfc(q)
    out: Arr = us0[..., None, :] * p[..., None]
    return out[..., 0, :] if np.ndim(z) == 0 else out


# ------------------------------------------------------------------ realization

def _wavenumber(w: Arr, h: Arr | float) -> Arr:
    """Linear dispersion w^2 = g k tanh(k h) by Newton from the left of the root (the function is concave, so it is monotone)."""
    k: Arr = np.maximum(w ** 2 / G, w / np.sqrt(G * h))
    for _ in range(12):
        th = np.tanh(k * h)
        k = k - (G * k * th - w ** 2) / (G * (th + k * h * (1 - th ** 2)))
    return k


def _sd_coeffs(a: Arr, w: Arr, dx: Arr, dy: Arr) -> tuple[NDArray[np.intp], NDArray[np.intp], Arr, Arr]:
    """Second-order elevation coefficients for the unordered pairs i <= j of the components (M, n2).
    eta2 = sum_ij [cp cos(psi_i + psi_j) + cm cos(psi_i - psi_j)], psi = k.x - w t + phase.
    Deep-water limit of Sharma & Dean 1979 (derived from the second-order Bernoulli and kinematic conditions;
    G+ = [wa^2 + wb^2 + wa wb (1 - c) + 2 wa wb ws^2 (1 - c) / (g|ka + kb| - ws^2)] / g with c = cos(angle between the
    components); G- is G+ with wb -> -wb, c -> -c). Checks: a = b collinear gives Stokes k a^2 / 2 cos 2 psi; collinear
    a != b gives (k1 + k2) / 2 and -|k1 - k2| / 2 (Longuet-Higgins & Stewart 1960)."""
    ii, jj = np.triu_indices(a.shape[1])
    wa, wb, c = w[:, ii], w[:, jj], dx[:, ii] * dx[:, jj] + dy[:, ii] * dy[:, jj]
    ka, kb = wa ** 2 / G, wb ** 2 / G
    ws, wd = wa + wb, wa - wb
    ks = np.sqrt(ka ** 2 + kb ** 2 + 2 * ka * kb * c)
    kd = np.sqrt(np.maximum(ka ** 2 + kb ** 2 - 2 * ka * kb * c, 0))
    Gp = (wa ** 2 + wb ** 2 + wa * wb * (1 - c) + 2 * wa * wb * ws ** 2 * (1 - c) / (G * ks - ws ** 2)) / G
    den = G * kd - wd ** 2
    t = np.divide(2 * wa * wb * wd ** 2 * (1 + c), den, out=np.zeros_like(den), where=den > 1e-12)
    Gm = (wa ** 2 + wb ** 2 - wa * wb * (1 + c) - t) / G
    wt = np.where(ii == jj, 0.25, 0.5) * a[:, ii] * a[:, jj]
    return ii, jj, wt * Gp, wt * Gm


class Realization:
    """Random-phase sea surface from E(..., f, theta) (leading axes = points / ensemble members, all vectorised).

    Each (f, theta) bin is split into `n_sub` components of equal variance: frequencies are drawn inside the bin from the
    local power law of E (stratified, so each stratum holds equal energy), directions uniformly inside the bin, phases
    uniformly. Frequencies are therefore all different and the record never repeats (a regular grid repeats at 1/df).
    Variance is conserved exactly: sum a^2 / 2 = int E df dtheta.
    Linear kinematics with finite-depth transfer functions and Wheeler (1970) stretching z_s = h (z - eta) / (h + eta)
    (`stretch=False`: linear, clipped at the mean surface). The second-order elevation (and its slope) of the `n2`
    largest components is added for members with eps = kp Hs / 2 > 0.05, or as forced by `second_order`; it is the
    deep-water form, valid for kp h > pi (`second_order_deep_ok` says whether that holds). Orbital velocities stay linear.
    `self.second_order` is the switch state (bool, or a bool array shaped like the leading axes)."""

    _budget = 4_000_000     # elements per intermediate array

    def __init__(self, E: ArrayLike, f: ArrayLike, theta: ArrayLike, depth: ArrayLike = np.inf, seed: int = 0, n_sub: int = 4, n2: int = 64,
                 second_order: bool | None = None, stretch: bool = True) -> None:
        E, f, theta = np.asarray(E, float), np.asarray(f, float), np.asarray(theta, float)
        self.lead, self.f, self.theta, self.stretch = E.shape[:-2], f, theta, stretch
        E2 = E.reshape((-1,) + E.shape[-2:])
        M, nf, nth = E2.shape
        self.depth = np.minimum(np.broadcast_to(depth, self.lead), DEEP).reshape(M).astype(float)
        rng = np.random.default_rng(seed)
        dth = _dth(theta)
        a = np.sqrt(2 * E2 * _df(f)[:, None] * dth / n_sub)[..., None] * np.ones(n_sub)
        # stratified equal-energy frequency draw from E ~ f^p inside each bin (p from the neighbouring bins)
        p = np.gradient(np.log(np.maximum(E2.sum(-1), 1e-300)), np.log(f), axis=-1)
        q = np.clip(p, -10, 3) + 1
        q = np.where(np.abs(q) < 1e-6, 1e-6, q)[..., None, None]
        lo, hi = (f * np.exp(s * _dlog(f) / 2) for s in (-1, 1))
        lo, hi = lo[:, None, None] ** q, hi[:, None, None] ** q
        u = (np.arange(n_sub) + rng.random(a.shape)) / n_sub
        fs = np.exp(np.log(lo + u * (hi - lo)) / q)
        thc = np.radians(theta)[None, None, :, None] + (rng.random(a.shape) - 0.5) * dth
        d = cv.vec_from_to(1.0, np.degrees(thc))
        K = nf * nth * n_sub
        self.a, self.dx, self.dy = a.reshape(M, K), d[..., 0].reshape(M, K), d[..., 1].reshape(M, K)
        self.w = 2 * np.pi * fs.reshape(M, K)
        self.k = _wavenumber(self.w, self.depth[:, None])
        self.phi = rng.uniform(0, 2 * np.pi, (M, K))
        # steepness and the second-order switch
        hs = hs_of(E2, f, theta)
        kp = _wavenumber(2 * np.pi * f[np.argmax(E2.sum(-1), -1)], self.depth)
        self.hs, self.eps = hs.reshape(self.lead)[()], (kp * hs / 2).reshape(self.lead)[()]
        on = kp * hs / 2 > EPS_SECOND if second_order is None else np.full(M, bool(second_order))
        self._on = on
        self.second_order = on.reshape(self.lead)[()]
        self.second_order_deep_ok = (kp * self.depth >= np.pi).reshape(self.lead)[()]
        n2 = min(n2, K)
        top = np.argsort(-self.a, axis=1)[:, :n2]
        self._top = tuple(np.take_along_axis(v, top, 1) for v in (self.a, self.w, self.k, self.dx, self.dy, self.phi))
        self._pairs = _sd_coeffs(*self._top[:2], *self._top[3:5])
        self._step = max(1, self._budget // (M * max(K, len(self._pairs[0]))))

    # -- evaluation helpers; arrays are (M, n, K) for n points
    def _phase(self, x: Arr, y: Arr, t: Arr) -> Arr:
        ph: Arr = (self.k[:, None] * (self.dx[:, None] * x[None, :, None] + self.dy[:, None] * y[None, :, None])
                   - self.w[:, None] * t[None, :, None] + self.phi[:, None])
        return ph

    def _second(self, x: Arr, y: Arr, t: Arr) -> tuple[Arr, Arr]:
        """(eta2 (M, n), grad (M, n, 2)) from the top-n2 components, zero where the switch is off."""
        if not self._on.any():
            return np.zeros((len(self._on), len(x))), np.zeros((len(self._on), len(x), 2))
        a, w, k, dx, dy, phi = self._top
        ii, jj, cp, cm = self._pairs
        psi = (k[:, None] * (dx[:, None] * x[None, :, None] + dy[:, None] * y[None, :, None])
               - w[:, None] * t[None, :, None] + phi[:, None])
        sp, sm = psi[..., ii] + psi[..., jj], psi[..., ii] - psi[..., jj]
        eta = (cp[:, None] * np.cos(sp) + cm[:, None] * np.cos(sm)).sum(-1)
        gr = []
        for kc in (k * dx, k * dy):
            gr.append(-(cp[:, None] * np.sin(sp) * (kc[:, ii] + kc[:, jj])[:, None]
                        + cm[:, None] * np.sin(sm) * (kc[:, ii] - kc[:, jj])[:, None]).sum(-1))
        on = self._on[:, None]
        return np.where(on, eta, 0.0), np.where(on[..., None], np.stack(gr, -1), 0.0)

    def _map(self, fn: Callable[..., Arr], nout: int, *args: ArrayLike) -> Arr:
        """Broadcast the point arrays, evaluate fn on chunks -> shape lead + broadcast shape + (nout,)."""
        args = np.broadcast_arrays(*(np.asarray(v, float) for v in args))
        flat = [v.ravel() for v in args]
        out = np.concatenate([fn(*(v[i:i + self._step] for v in flat)) for i in range(0, flat[0].size, self._step)], axis=1)
        return out.reshape(self.lead + args[0].shape + (nout,))

    def _eta(self, x: Arr, y: Arr, t: Arr) -> Arr:
        e2 = self._second(x, y, t)[0]
        return (self.a[:, None] * np.cos(self._phase(x, y, t))).sum(-1) + e2

    def eta(self, x: ArrayLike, y: ArrayLike, t: ArrayLike) -> Arr:
        """Surface elevation [m] at east x, north y [m], time t [s]; shape lead + broadcast(x, y, t)."""
        return self._map(lambda x, y, t: self._eta(x, y, t)[..., None], 1, x, y, t)[..., 0]

    def slope(self, x: ArrayLike, y: ArrayLike, t: ArrayLike) -> Arr:
        """(d eta/dx, d eta/dy) = (east, north) surface slope, shape lead + broadcast + (2,)."""
        def fn(x: Arr, y: Arr, t: Arr) -> Arr:
            s = -self.a[:, None] * np.sin(self._phase(x, y, t))
            lin = np.stack([(s * (self.k * self.dx)[:, None]).sum(-1), (s * (self.k * self.dy)[:, None]).sum(-1)], -1)
            return lin + self._second(x, y, t)[1]
        return self._map(fn, 2, x, y, t)

    def velocity(self, x: ArrayLike, y: ArrayLike, z: ArrayLike, t: ArrayLike) -> Arr:
        """Orbital velocity (east, north, up) [m/s] at height z [m] (z <= 0 below MSL), shape lead + broadcast + (3,).
        Above the instantaneous surface the value at the surface is returned."""
        def fn(x: Arr, y: Arr, z: Arr, t: Arr) -> Arr:
            ph, eta = self._phase(x, y, t), self._eta(x, y, t)
            h = self.depth[:, None]
            zs = h * (z[None] - eta) / (h + eta) if self.stretch else np.broadcast_to(z[None], eta.shape)
            zs, hh, kk = np.clip(zs, -h, 0)[..., None], h[..., None], self.k[:, None]
            e1, e2 = np.exp(kk * zs), np.exp(-kk * (zs + 2 * hh))
            den = 1 - np.exp(-2 * kk * hh)
            uh = self.a[:, None] * self.w[:, None] * (e1 + e2) / den * np.cos(ph)
            wv = self.a[:, None] * self.w[:, None] * (e1 - e2) / den * np.sin(ph)
            return np.stack([(uh * self.dx[:, None]).sum(-1), (uh * self.dy[:, None]).sum(-1), wv.sum(-1)], -1)
        return self._map(fn, 3, x, y, z, t)

    def encounter_spectrum(self, velocity_en: ArrayLike, edges: ArrayLike | None = None) -> tuple[Arr, Arr]:
        """Variance spectrum [m^2/Hz] seen by a vehicle moving at (east, north) velocity [m/s]: each component lands at
        |omega - k . V| / 2 pi (Doppler; folded, so following seas faster than the waves appear at |f_e|).
        Returns (bin centres [Hz], S shaped lead + (nbins,)). First-order variance only."""
        V = np.broadcast_to(np.asarray(velocity_en, float), self.lead + (2,)).reshape(-1, 2)
        fe = np.abs(self.w - self.k * (self.dx * V[:, :1] + self.dy * V[:, 1:])) / (2 * np.pi)
        edges = np.linspace(0, fe.max() * 1.0001, 401) if edges is None else np.asarray(edges, float)
        nb, M = len(edges) - 1, fe.shape[0]
        ok = fe < edges[-1]
        idx = (np.arange(M)[:, None] * nb + np.digitize(fe, edges) - 1)[ok]
        S = np.bincount(idx, weights=(self.a ** 2 / 2)[ok], minlength=M * nb).reshape(M, nb) / np.diff(edges)
        return (edges[1:] + edges[:-1]) / 2, S.reshape(self.lead + (nb,))


# ------------------------------------------------------------------ receipts

def _max_autocorr(x: Arr, dt: float, lag_min: float, lag_max: float) -> float:
    """max |autocorrelation| of a record at lags lag_min..lag_max [s] (direct sums, mean removed)."""
    x = x - x.mean()
    lags = np.arange(int(lag_min / dt), int(lag_max / dt) + 1)
    return float(max(abs(np.dot(x[:-m], x[m:])) / (len(x) - m) for m in lags) / x.var())


def _grid() -> tuple[Arr, Arr, Arr]:
    """UMWM's bins: f [Hz], theta [math rad, file order], theta [compass deg, ascending]."""
    f = 0.0313 * 1.1225 ** np.arange(37)
    th = (np.arange(32) + 0.5) * np.pi / 16 - np.pi
    return f, th, theta_compass(th)


def _restart_from_E(E: Arr, f: Arr, theta_umwm: Arr) -> tuple[Arr, Arr]:
    """Inverse of spectrum_from_restart in deep water with the analytic dk = 2 k dlnf (so it shares no code with it):
    returns (F(th, f) in file order, k(f))."""
    k = (2 * np.pi * f) ** 2 / G
    F = E.T * f / (2 * k ** 2)
    Fu = np.empty_like(F)
    Fu[np.argsort(cv.math_rad_to_compass_to(theta_umwm))] = F
    return Fu, k


def _single(f: Arr, th: Arr, a: float = 0.3) -> tuple[Realization, int]:
    """Realization of one (f, theta) bin of amplitude a with one component, second order forced on; returns it and the
    index of its (only non-zero) component."""
    E1 = np.zeros((len(f), len(th)))
    E1[20, 8] = a ** 2 / 2 / (_df(f)[20] * _dth(th))
    r = Realization(E1, f, th, n_sub=1, second_order=True, n2=1)
    return r, int(np.argmax(r.a[0]))


def _on_ray(r: Realization, i: int, s: float) -> tuple[float, float]:
    """Point at distance s along the propagation direction of component i."""
    return s * r.dx[0, i], s * r.dy[0, i]


def _fd_grad(r: Realization, x: Arr | float, y: Arr | float, t: Arr | float, h: float = 1e-4) -> Arr:
    """Spatial gradient of eta by central differences of r.eta (independent of r.slope)."""
    gx = (r.eta(x + h, y, t) - r.eta(x - h, y, t)) / (2 * h)
    gy = (r.eta(x, y + h, t) - r.eta(x, y - h, t)) / (2 * h)
    return np.stack([gx, gy], -1)


def _propagation(r: Realization, x: Arr, y: Arr, t: Arr, dt: float = 0.05) -> Arr:
    """<-eta_t grad eta> = (1/2) sum a^2 k w d: a vector along the direction the waves travel toward (east, north)."""
    et = (r.eta(x, y, t + dt) - r.eta(x, y, t - dt)) / (2 * dt)
    return -(et[:, None] * _fd_grad(r, x, y, t)).mean(0)


def _phase_speed(r: Realization, i: int) -> float:
    """c = -eta_t / (d . grad eta) by finite differences of eta alone, where the phase is pi/2 (steepest slope)."""
    x, y = _on_ray(r, i, (np.pi / 2 - r.phi[0, i]) / r.k[0, i])
    et = (r.eta(x, y, 0.01) - r.eta(x, y, -0.01)) / 0.02
    return float(-et / (_fd_grad(r, x, y, 0.0) @ [r.dx[0, i], r.dy[0, i]]))


def receipts() -> None:
    from cafe import receipts as R
    f, th_u, th = _grid()
    gp = "Waves"
    # Hs through the parametric path, and through the restart-file path (UMWM weighting)
    for hs, tp, d, mss, u10 in ((2.0, 14.0, 225.0, 0.004, 4.0), (1.5, 4.0, 40.0, 0.03, 12.0), (3.5, 11.0, 300.0, 0.01, 7.0)):
        E = spectrum_from_params(hs, tp, d, mss, u10, f, th)
        R.receipt(gp, f"Hs of the discretised spectrum (Hs {hs}, Tp {tp} s, U10 {u10} m/s) vs target", float(hs_of(E, f, th)), hs,
                  0.01, "m", "brief 1.2/2.3: <= 1 % after discretisation")
        Fu, k = _restart_from_E(E, f, th_u)
        R.receipt(gp, f"hs_from_restart of the equivalent UMWM F (Hs {hs}) vs target", float(hs_from_restart(Fu, k, f, th_u)), hs,
                  0.01, "m", "UMWM umwm_domain_output.f90: swh = 4 sqrt(sum F k dk dtheta)")
    # m0 and m2 of the discrete shapes vs fine-grid quadrature of the same continuous shape
    ff = np.geomspace(f[0] / 1.06, f[-1] * 1.06, 200001)
    for name, sw, om in (("DHH wind sea", False, 1.5), ("swell", True, 0.4)):
        def sh(x: Arr, om: float = om, sw: bool = sw) -> Arr:
            s: Arr = _wave_shape(x, np.array([[0.1]]), np.array([[om]]), np.array([[sw]]))[0]
            return s
        for n in (0, 2):
            R.receipt(gp, f"m{n} (int f^{n} S df) of the {name} shape, 37 log bins vs quadrature",
                      float(np.sum(f ** n * sh(f) * _df(f))), float(np.trapezoid(ff ** n * sh(ff), ff)), 0.02, "",
                      "discretisation of the spectrum on UMWM's bins")
    E = spectrum_from_params(2.0, 14.0, 225.0, 0.004, 4.0, f, th)
    R.receipt(gp, "mean-square slope of the synthesised spectrum vs UMWM mss", float(mean_square_slope(E, f, th)), 0.004, 0.01,
              "", "UMWM mss = sum F k^3 dk dtheta; fixes the short-sea share")
    # Stokes surface drift vs closed form: E = B f^-5 in one direction bin, u0 = (16 pi^3 / g) B (1/f1 - 1/f2)
    B, j = 1e-4, 24
    E = np.zeros((len(f), len(th)))
    E[:, j] = B * f ** -5 / _dth(th)
    f1, f2 = f[0] * np.exp(-_dlog(f)[0] / 2), f[-1] * np.exp(_dlog(f)[-1] / 2)
    us = stokes_profile(E, f, th, 0.0)
    R.receipt(gp, "Stokes surface drift speed vs (16 pi^3/g) int f^3 E df (= 2 m3/g)", float(np.hypot(*us)),
              16 * np.pi ** 3 / G * B * (1 / f1 - 1 / f2), 0.01, "m/s", "Kenyon 1969; Breivik et al. 2016 eq 6")
    R.bracket(gp, "Stokes drift direction (spectrum in the bin toward compass %.1f deg)" % th[j],
              float(cv.to_deg(us)), th[j] - 0.5, th[j] + 0.5, "deg", "conventions.to_deg of the east/north drift")
    # Breivik 2016 profile (from u0 and V only) vs the numerically integrated Phillips spectrum
    fine = np.geomspace(0.05, 60.0, 4000)
    Ep = np.zeros((len(fine), len(th)))
    Ep[:, j] = np.where(fine > 0.1, 0.0083 * G ** 2 * (2 * np.pi) ** -4 * fine ** -5, 0.0) / _dth(th)
    u0, V = stokes_profile(Ep, fine, th, 0.0), stokes_transport(Ep, fine, th)
    zs = np.array([-0.25, -1.0, -3.0, -8.0, -20.0])
    ref, app = stokes_profile(Ep, fine, th, zs), stokes_breivik2016(u0, V, zs)
    for z, r_, a_ in zip(zs, np.hypot(*ref.T), np.hypot(*app.T), strict=True):
        R.receipt(gp, f"Breivik 2016 profile speed at z = {z} m vs Phillips-spectrum integral", float(a_), float(r_), 0.02, "m/s",
                  "Breivik et al. 2016 eq 19, 22, 23 (beta = 1)")
    # realization statistics
    E = spectrum_from_params(1.5, 9.0, 225.0, 0.02, 6.0, f, th)
    rz = Realization(E, f, th, seed=1)
    rng = np.random.default_rng(2)
    n = 20000
    x, y, t = rng.uniform(-3000, 3000, n), rng.uniform(-3000, 3000, n), rng.uniform(0, 3600, n)
    R.receipt(gp, "realization variance of eta (20000 points x 1 h) vs m0", float(np.var(rz.eta(x, y, t))),
              float(moment(E, f, th)), 0.05, "m2", "random-phase superposition: E[var] = m0")
    ta = np.arange(0, 3600.0, 1.0)
    R.bracket(gp, "max |autocorrelation| of a 1 h record at lags 10-30 min (no repeat)",
              float(_max_autocorr(rz.eta(0 * ta, 0 * ta, ta), 1.0, 600, 1800)), 0.0, 0.6, "",
              "equal-energy sub-binning with random in-bin frequencies; a regular grid repeats at 1/df and gives ~1")
    # direction convention: waves toward the south-west, given as UMWM math radians
    Ed = spectrum_from_params(1.5, 9.0, float(cv.math_rad_to_compass_to(np.radians(-135.0))), 0.02, 6.0, f, th)
    rd = Realization(Ed, f, th, seed=3)
    R.bracket(gp, "propagation direction of a realization given dwd = -135 deg (math) = 225 deg compass",
              float(cv.to_deg(_propagation(rd, x, y, t))),
              220.0, 230.0, "deg", "UMWM convention (radians CCW from east, toward) -> compass via conventions")
    R.bracket(gp, "Stokes drift direction for the same input", float(cv.to_deg(stokes_profile(Ed, f, th, 0.0))), 220.0, 230.0,
              "deg", "conventions.to_deg")
    # second-order switch, Stokes crest, dispersion
    for hs, want in ((1.5, 0.0), (3.0, 1.0)):
        r = Realization(spectrum_from_params(hs, 10.0, 90.0, 0.02, 6.0, f, th), f, th)
        R.bracket(gp, f"second-order switch at Hs {hs} m, Tp 10 s (eps = {float(r.eps):.3f})", float(r.second_order), want, want,
                  "", "on iff eps = kp Hs / 2 > 0.05")
    r1, i = _single(f, th)
    cx, cy = _on_ray(r1, i, -r1.phi[0, i] / r1.k[0, i])
    R.receipt(gp, "second-order crest of one component vs Stokes a + k a^2 / 2", float(r1.eta(cx, cy, 0.0)),
              0.3 + r1.k[0, i] * 0.3 ** 2 / 2, 0.01, "m", "Stokes 1847 / Sharma & Dean deep-water limit")
    R.receipt(gp, "phase speed -eta_t / (d . grad eta) of a component vs g / omega", _phase_speed(r1, i), float(G / r1.w[0, i]),
              0.01, "m/s", "deep-water dispersion; fails if the sign of k.x or of the direction flips")
