"""Sub-grid atmosphere and ocean: what lies between WRF's 12 km / 1 h and a vehicle. Everything here is MODELLED, never
read from a file, so every public output is a `Tagged(..., kind="modelled")` and is reproducible from integer seeds.

Pieces: Mann turbulence boxes sampled at a point (`turbulence`, `turbulence_members`), cold-pool gust fronts tied to rain
(`gust_fronts`, `gust_perturbation`), an Ito SDE for unresolved ocean eddy diffusion (`ocean_sde_step`), windage and the
diurnal-jet proxy for surface vehicles (`windage`, `diurnal_jet`), and rain fresh lenses (`rain_lens`).

Coefficients and citations: config/subgrid.json (sourced) and config/assumptions.yaml (unsourced, each with what replaces it).
`config/subgrid.json["calibration"]` is what Stage-3 LES overwrites; `load_config()` returns it and every Tagged `source`
names `calibration.source_run`.
"""

import functools
import json
import pathlib
from typing import NamedTuple

import numpy as np
import yaml

from .. import Tagged
from . import conventions as cv

_CFG_DIR = pathlib.Path(__file__).resolve().parents[3] / "config"


@functools.lru_cache(maxsize=None)
def _load(path: str) -> dict:
    return json.loads(pathlib.Path(path).read_text())


def load_config(path: str | None = None) -> dict:
    """config/subgrid.json (or `path`) as a dict. Do not mutate; copy first."""
    return _load(str(path or _CFG_DIR / "subgrid.json"))


@functools.lru_cache(maxsize=None)
def _assumptions() -> dict:
    return yaml.safe_load((_CFG_DIR / "assumptions.yaml").read_text())


def assumption(key: str):
    """Value of an entry of config/assumptions.yaml."""
    return _assumptions()[key]["value"]


def calibration_note(cfg: dict) -> str:
    """Which run produced the calibration the code is using."""
    run = cfg["calibration"]["source_run"]
    return (
        "calibration: shipped defaults (no Stage-3 LES run has written one)" if run is None else f"calibration: Stage-3 run {run}"
    )


def _tag(value, what: str, cfg: dict, unc=None) -> Tagged:
    return Tagged(value, f"cafe.pm.env.subgrid: {what}; {calibration_note(cfg)}", unc, "modelled")


# ---------------------------------------------------------------- a. turbulence


def mann_length(z, L_ob, cfg: dict | None = None):
    """Mann length scale L [m] at height z [m] for Obukhov length L_ob [m] (inf or large = neutral).

    Neutral: L = 0.8 Lambda1, Lambda1 = min(0.7 z, 42 m) (IEC 61400-1 ed.3 Annex C; Mann 1994/1998). Stability: divided by
    phi_m(z/L_ob) (Businger-Dyer), clipped (assumptions.yaml), after Pena, Gryning & Mann 2010 who tie L to the mixing length.
    Multiplied by calibration.length_scale_factor.
    """
    cfg = cfg or load_config()
    t = cfg["turbulence"]
    z, L_ob = np.asarray(z, float), np.asarray(L_ob, float)
    ln = t["L_over_lambda1"] * np.minimum(t["lambda1_over_z"] * z, t["lambda1_max_m"])
    with np.errstate(divide="ignore"):
        zeta = z / L_ob
    phi = np.where(zeta < 0, (1 - 16 * np.minimum(zeta, 0)) ** -0.25, 1 + 5 * np.maximum(zeta, 0))
    lo, hi = assumption("subgrid.stability_ratio_clip")
    return ln * np.clip(1 / phi, lo, hi) * cfg["calibration"]["length_scale_factor"]


@functools.lru_cache(maxsize=4)
def _unit_box(gamma: float, nx: int, ny: int, nz: int, dx: float, ly: float, lz: float):
    """Mann stencil in units of the length scale (L = 1, ae = 1) and the box standard deviations of (u, v, w).

    All lengths scale with L and all amplitudes with sqrt(ae) L^(1/3), so one stencil serves every z, z/L and u*. The
    standard deviations are measured on 6 fixed seeds (box = 16 x 16 laterally, so ~1 % accuracy)."""
    from mannrs import Stencil

    st = Stencil(L=1.0, gamma=gamma, Lx=nx * dx, Ly=ly, Lz=lz, Nx=nx, Ny=ny, Nz=nz).build(parallel=True)
    sig = np.mean([[f.std() for f in (w.U, w.V, w.W)] for w in (st.turbulence(1.0, s, parallel=True) for s in range(6))], axis=0)
    return st, sig


def _box_series(cfg: dict, seeds) -> tuple[np.ndarray, np.ndarray]:
    """Centre-node (u, v, w) series, shape (len(seeds), nx, 3), of unit boxes and the unit sigmas (3,)."""
    b = cfg["turbulence"]["box"]
    st, sig = _unit_box(cfg["turbulence"]["gamma"], b["nx"], b["ny"], b["nz"], b["dx_over_L"], b["ly_over_L"], b["lz_over_L"])
    out = []
    for s in seeds:
        w = st.turbulence(1.0, int(s), parallel=True)
        out.append(np.stack([c[:, b["ny"] // 2, b["nz"] // 2] for c in (w.U, w.V, w.W)], axis=-1))
    return np.asarray(out, float), sig


def turbulence_members(
    seed: int,
    n_members: int,
    ustar,
    L_ob,
    z,
    U,
    duration_s: float,
    dt: float,
    n_boxes: int | None = None,
    cfg: dict | None = None,
) -> Tagged:
    """Gust time series (M, n, 3) = (along-wind u', cross-wind v', vertical w') [m/s] at a point advected through frozen Mann
    turbulence at the mean wind speed U [m/s] (Taylor's hypothesis, x = U t), t = 0, dt, ... , (n-1) dt.

    Amplitude: total sigma_u of the delivered series = calibration.sigma_u_over_ustar * ustar (2.5 u*; BRIEF 2.2); v and w follow
    from the Mann tensor (Gamma = 3.9), so sigma_v/sigma_u ~ 0.63 and sigma_w/sigma_u ~ 0.43 (IEC: 0.8, 0.5; the box resolves the
    1-D spectrum only to k L ~ 3, ~80 % of the variance, and the rescaling puts all of sigma_u into the resolved band, so the
    resolved band carries ~12 % too much amplitude). Length: `mann_length(z, L_ob)`. ustar may be an array (M,); L_ob, z, U
    are scalars.

    Independence: n_boxes = None gives every member its own box (statistically independent; ~0.5 s per box). With n_boxes = B < M
    members share boxes through non-overlapping x-segments, so two members of a box are separated by at least U * duration >> L
    along the field and their zero-lag correlation is that of the Mann field at that separation (~0; see receipts). Capacity is
    B * floor(box length / segment length) members; a ValueError says so if exceeded. Box length is 8192 L (16384 points at L/2).
    """
    cfg = cfg or load_config()
    ustar = np.broadcast_to(np.asarray(ustar, float), (n_members,))
    Lm = float(mann_length(z, L_ob, cfg))
    U = float(U)
    n = int(np.ceil(duration_s / dt)) + 1
    b = cfg["turbulence"]["box"]
    dx_u = b["dx_over_L"]
    xi = U * dt * np.arange(n) / Lm / dx_u  # box index of each sample (box units of dx)
    seg = int(np.ceil(xi[-1])) + 2
    per_box = b["nx"] // seg
    if per_box < 1:
        raise ValueError(f"series needs {seg} box cells but a box has {b['nx']}: shorten duration_s or call once per hour")
    nb = n_members if n_boxes is None else n_boxes
    if n_members > nb * per_box:
        raise ValueError(f"{n_members} members need more than {nb} boxes x {per_box} segments: raise n_boxes")
    seeds = np.random.SeedSequence(seed).generate_state(nb, dtype=np.uint32)
    boxes, sig = _box_series(cfg, seeds)
    m = np.arange(n_members)
    start = (m // nb) * seg
    pos = start[:, None] + xi[None, :]
    i0 = np.floor(pos).astype(int)
    f = (pos - i0)[..., None]
    bx = boxes[(m % nb)[:, None], i0]
    by = boxes[(m % nb)[:, None], i0 + 1]
    series = (1 - f) * bx + f * by
    sigma_u = cfg["calibration"]["sigma_u_over_ustar"] * ustar
    out = series * (sigma_u / sig[0])[:, None, None]
    unc = 0.2 * sigma_u[:, None, None]
    return _tag(
        out, f"Mann box (mannrs), L={Lm:.3g} m, sigma_u={cfg['calibration']['sigma_u_over_ustar']} u*, frozen advection", cfg, unc
    )


def turbulence(
    seed: int, ustar: float, L: float, z: float, U: float, duration_s: float, dt: float, cfg: dict | None = None
) -> Tagged:
    """One gust series (n, 3) = (along-wind, cross-wind, vertical) [m/s]; `L` is the Obukhov length. See `turbulence_members`."""
    t = turbulence_members(seed, 1, ustar, L, z, U, duration_s, dt, cfg=cfg)
    return Tagged(t.value[0], t.source, t.uncertainty[0], t.kind)


def gust_enu(g, wind_from_deg):
    """Rotate along/cross/vertical gusts (..., 3) to (east, north, up) for a wind blowing FROM `wind_from_deg` (compass)."""
    g = np.asarray(g, float)
    a = cv.vec_from_from(1.0, wind_from_deg)  # unit vector the wind blows toward
    left = np.stack([-a[..., 1], a[..., 0]], axis=-1)
    h = g[..., 0:1] * a + g[..., 1:2] * left
    return np.concatenate([h, g[..., 2:3]], axis=-1)


# ---------------------------------------------------------------- b. gust fronts


def rain_rate_from_accum(rainnc_mm, times) -> np.ndarray:
    """Rain rate [mm/h] at each time from accumulated RAINNC [mm] (last axis = time): backward difference, first value from the
    first interval. Negative differences (accumulator resets) are clipped to 0."""
    r = np.asarray(rainnc_mm, float)
    dh = np.diff(np.asarray(times, float)) / 3600.0
    d = np.maximum(np.diff(r, axis=-1), 0.0) / dh
    return np.concatenate([d[..., :1], d], axis=-1)


def theta_e(T, q, p):
    """Equivalent potential temperature [K] (Bolton 1980, eqs. 21, 24, 43) from T [K], specific humidity q [kg/kg], p [Pa]."""
    T, q, ph = np.asarray(T, float), np.asarray(q, float), np.asarray(p, float) / 100.0
    r = q / (1 - q)
    e = ph * r / (0.622 + r)
    tl = 2840.0 / (3.5 * np.log(T) - np.log(e) - 4.805) + 55.0
    return T * (1000.0 / ph) ** (0.2854 * (1 - 0.28 * r)) * np.exp(r * (1 + 0.81 * r) * (3376.0 / tl - 2.54))


def gust_rate(rain_rate_mm_h, theta_e_K=None):
    """Cold-pool event probability rate [1/h]: lambda_bg + lambda_max (1 - exp(-rain/scale)) * f(theta_e), with the CAPE-like
    factor f = clip((theta_e - lo)/span, 0, 1) from surface theta_e (T2, Q2, PSFC; `theta_e`), 1 if not given. Constants:
    assumptions.yaml (the structure follows Wills et al. 2021: cold pools sit under convection; the numbers are assumed)."""
    r = np.asarray(rain_rate_mm_h, float)
    f = (
        1.0
        if theta_e_K is None
        else np.clip(
            (np.asarray(theta_e_K, float) - assumption("subgrid.gust_front.theta_e_lo_K"))
            / assumption("subgrid.gust_front.theta_e_span_K"),
            0,
            1,
        )
    )
    return (
        assumption("subgrid.gust_front.lambda_bg_per_h")
        + assumption("subgrid.gust_front.lambda_max_per_h")
        * (1 - np.exp(-r / assumption("subgrid.gust_front.rain_scale_mm_h")))
        * f
    )


class Events(NamedTuple):
    member: np.ndarray  # (K,) ensemble member index
    start: np.ndarray  # (K,) s
    duration: np.ndarray  # (K,) s
    dU: np.ndarray  # (K, 2) peak (east, north) wind change [m/s]
    dT: np.ndarray  # (K,) peak air temperature change [K] (negative)
    n_members: int


def gust_fronts(
    seed: int, rain_rate_mm_h, times, n_members: int = 1, theta_e_K=None, wind_to_deg=None, cfg: dict | None = None
) -> Events:
    """Sample cold-pool gust fronts. `rain_rate_mm_h`, `theta_e_K`, `wind_to_deg` are hourly series on `times` [s] (shape (T,) or
    (M, T)); within each hour a member has Poisson(`gust_rate`) events at uniform start times. Each event: duration and peak
    dU uniform over calibration.gust_stats (BRIEF 2.2: 10-30 min, +3 to +10 m/s), dT = calibration dT (-1.5 K, the Wills et al.
    2021 detection threshold, i.e. a lower bound on the drop), gust vector along the mean wind `wind_to_deg` plus a Gaussian
    angular offset (random azimuth if None). Hours are taken as starting at each entry of `times`."""
    cfg = cfg or load_config()
    gs = cfg["calibration"]["gust_stats"]
    rng = np.random.default_rng(seed)
    times = np.asarray(times, float)
    shape = (n_members, times.size)
    lam = np.broadcast_to(gust_rate(rain_rate_mm_h, theta_e_K), shape)
    cnt = rng.poisson(lam)
    mem, hr = np.nonzero(cnt)
    rep = cnt[mem, hr]
    mem, hr = np.repeat(mem, rep), np.repeat(hr, rep)
    k = mem.size
    start = times[hr] + rng.uniform(0, 3600.0, k)
    dur = rng.uniform(gs["duration_min_s"], gs["duration_max_s"], k)
    mag = rng.uniform(gs["dU_min"], gs["dU_max"], k)
    if wind_to_deg is None:
        ang = rng.uniform(0, 360.0, k)
    else:
        ang = np.broadcast_to(np.asarray(wind_to_deg, float), shape)[mem, hr] + rng.normal(
            0, assumption("subgrid.gust_front.direction_sigma_deg"), k
        )
    return Events(mem, start, dur, cv.vec_from_to(mag, ang), np.full(k, float(gs["dT"])), n_members)


def _shape(tau, rise, dur):
    """Triangle: 0 -> 1 linearly over `rise` s, back to 0 at `dur`; 0 outside [0, dur]."""
    rise = np.minimum(rise, dur / 2)
    s = np.where(tau < rise, tau / rise, (dur - tau) / (dur - rise))
    return np.where((tau >= 0) & (tau <= dur), s, 0.0)


def gust_perturbation(ev: Events, t, cfg: dict | None = None) -> tuple[Tagged, Tagged]:
    """Wind change (M, *t.shape, 2) [m/s] and air-temperature change (M, *t.shape) [K] at times `t` [s], summed over each
    member's events. Wind peaks `wind_rise_s` after onset, temperature `temp_rise_s` after onset (assumptions.yaml); both fall
    linearly to zero at the end of the event."""
    cfg = cfg or load_config()
    t = np.asarray(t, float)
    dU = np.zeros((ev.n_members,) + t.shape + (2,))
    dT = np.zeros((ev.n_members,) + t.shape)
    if ev.member.size:
        tau = t[None] - ev.start.reshape((-1,) + (1,) * t.ndim)
        dur = ev.duration.reshape((-1,) + (1,) * t.ndim)
        sw = _shape(tau, assumption("subgrid.gust_front.wind_rise_s"), dur)
        st = _shape(tau, assumption("subgrid.gust_front.temp_rise_s"), dur)
        np.add.at(dU, ev.member, sw[..., None] * ev.dU.reshape((-1,) + (1,) * t.ndim + (2,)))
        np.add.at(dT, ev.member, st * ev.dT.reshape((-1,) + (1,) * t.ndim))
    return _tag(dU, "cold-pool gust front dU", cfg), _tag(dT, "cold-pool gust front dT", cfg)


# ---------------------------------------------------------------- c. ocean


def okubo_K(scale_m):
    """Horizontal eddy diffusivity [m2/s] at length scale `scale_m` [m]: Okubo 1971, K = 0.0103 l^1.15 cm2/s (l in cm)."""
    o = load_config()["ocean"]["okubo"]
    return o["a_cm2_s"] * (np.asarray(scale_m, float) * 100.0) ** o["p"] * 1e-4


def ocean_sde_step(x, K, gradK, dt: float, rng: np.random.Generator, u=None):
    """One Euler-Maruyama step of the Ito SDE  dx = (u + dK/dx) dt + sqrt(2K) dW  for a passive tracer in inhomogeneous
    diffusion (OceanParcels AdvectionDiffusionEM; the dK/dx term is what keeps a well-mixed tracer well mixed, Thomson 1987).

    x (..., 2) position [m]; K [m2/s] shape (...,) (isotropic) or (..., 2); gradK (..., 2) = (dKx/dx, dKy/dy) [m/s]; u optional
    advecting velocity (..., 2) [m/s]. Returns the new x (plain array: positions are not an environment value)."""
    x = np.asarray(x, float)
    K = np.asarray(K, float)
    K = K[..., None] if K.ndim == x.ndim - 1 else K
    drift = np.asarray(gradK, float) if u is None else np.asarray(gradK, float) + np.asarray(u, float)
    return x + drift * dt + np.sqrt(2 * K * dt) * rng.standard_normal(x.shape)


def windage(seed: int, wind10, cfg: dict | None = None) -> Tagged:
    """Leeway velocity [m/s] of a surface vehicle: fraction * 10 m wind vector. wind10 (M, ..., 2) east/north; the fraction is
    drawn per member (axis 0) uniformly in [0.018, 0.023] (BRIEF 2.2; Breivik & Allen 2008, Rohrs et al. 2012 for the range)."""
    cfg = cfg or load_config()
    w = np.asarray(wind10, float)
    a = cfg["ocean"]["windage"]
    frac = np.random.default_rng(seed).uniform(a["fraction_min"], a["fraction_max"], (w.shape[0],) + (1,) * (w.ndim - 1))
    return _tag(frac * w, "windage fraction * U10", cfg, 0.0015 * w)


def diurnal_jet(seed: int, dT_warm, wind10, cfg: dict | None = None) -> Tagged:
    """Surface-trapped diurnal jet proxy [m/s, (east, north)]: u_amp * min(dT_warm / dT_ref, 1) along the wind, u_amp uniform
    in [0.1, 0.3] per member (axis 0). TEPEX-C's own hypothesis (BRIEF 2.2), labelled modelled; dT_ref in assumptions.yaml."""
    cfg = cfg or load_config()
    w = np.asarray(wind10, float)
    j = cfg["ocean"]["diurnal_jet"]
    amp = np.random.default_rng(seed).uniform(j["u_min"], j["u_max"], (w.shape[0],) + (1,) * (w.ndim - 1))
    sp = np.hypot(w[..., 0], w[..., 1])[..., None]
    unit = np.divide(w, sp, out=np.zeros_like(w), where=sp > 0)
    scale = np.clip(np.asarray(dT_warm, float) / assumption("subgrid.diurnal_jet.dT_ref_K"), 0, 1)[..., None]
    return _tag(amp * scale * unit, "diurnal jet proxy (TEPEX-C hypothesis)", cfg, 0.1 * scale * unit)


# ---------------------------------------------------------------- d. rain lens


def rain_lens(rain_rate, u10, t_since_rain, z=0.0, cfg: dict | None = None) -> dict:
    """Fresh-water lens (Iyer & Drushka 2021): salinity change dS [psu] and temperature change dT [K] at depth z [m, <= 0],
    plus the lens size. Amplitude 0.5 psu * clip((rain - trigger)/(saturation - trigger), 0, 1), times a wind factor that is 1
    below 5 m/s and falls linearly to 0 at 8 m/s (absent above), times exp(-t_since_rain / tau) with tau from
    `tau_max_s` at 5 m/s to `tau_min_s` at 8 m/s; the lens is a smooth top hat of thickness 0.5 m. `rain_rate` mm/h,
    `t_since_rain` s since the rain that formed it (use 0 while it rains; the rate then sets the amplitude). Zero everywhere if
    config rain_lens.enabled is false. Returns dict(dS, dT, size_km) with dS, dT Tagged."""
    cfg = cfg or load_config()
    c = cfg["rain_lens"]
    rate, u10, ts, z = (np.asarray(v, float) for v in (rain_rate, u10, t_since_rain, z))
    trig, sat = assumption("subgrid.rain_lens.trigger_mm_h"), assumption("subgrid.rain_lens.saturation_mm_h")
    amp = np.clip((rate - trig) / (sat - trig), 0, 1)
    w = np.clip((c["wind_absent_above_ms"] - u10) / (c["wind_absent_above_ms"] - c["wind_full_below_ms"]), 0, 1)
    tau = (
        assumption("subgrid.rain_lens.tau_min_s")
        + (assumption("subgrid.rain_lens.tau_max_s") - assumption("subgrid.rain_lens.tau_min_s")) * w
    )
    top = 0.5 * (1 - np.tanh((-z - c["thickness_m"]) / assumption("subgrid.rain_lens.edge_width_m")))
    f = amp * w * np.exp(-ts / tau) * np.where(z <= 0, top, 0.0) * (1.0 if c["enabled"] else 0.0)
    return dict(
        dS=_tag(c["dS_psu"] * f, "rain fresh lens dS (Iyer & Drushka 2021)", cfg),
        dT=_tag(assumption("subgrid.rain_lens.dT_K") * f, "rain fresh lens dT (assumed)", cfg),
        size_km=c["size_km"],
    )


# ---------------------------------------------------------------- receipts


def _psd_ratio(series: np.ndarray, dt: float, U: float, Lm: float, sig_scale: float, cfg: dict):
    """Mean PSD of u' (per rad/m) over members divided by the analytic Mann spectrum for the same scaling, by kL."""
    import mannrs
    from scipy.signal import welch

    f, p = welch(series, fs=1 / dt, nperseg=min(1024, series.shape[-1] // 2), axis=-1, detrend="constant")
    p = p.mean(0)
    k = 2 * np.pi * f[1:] / U
    s_k = p[1:] * U / (2 * np.pi)  # PSD per Hz -> per rad/m (S(k) dk = S(f) df, k = 2 pi f / U)
    uu = mannrs.mann_spectra(k * Lm, 1.0, 1.0, cfg["turbulence"]["gamma"])[0]
    ana = sig_scale**2 * Lm * 2 * uu
    return k * Lm, s_k / ana, s_k


def _turbulence_receipts() -> None:
    import mannrs
    from cafe import receipts as R

    cfg = load_config()
    g = "sub-grid"
    ust, z, U, dt, dur, M = 0.3, 10.0, 6.0, 0.5, 1800.0, 12
    t = turbulence_members(1, M, ust, -500.0, z, U, dur, dt, n_boxes=6, cfg=cfg)
    x = t.value
    ratio = x[..., 0].std(axis=1) / ust
    R.receipt(
        g,
        "sigma_u / u* (mean of 12 members, 1800 s) vs the configured calibration",
        float(ratio.mean()),
        cfg["calibration"]["sigma_u_over_ustar"],
        0.06,
        "-",
        "BRIEF 2.2",
        rel=True,
    )
    R.context(
        g,
        "configured sigma_u / u* vs the neutral surface-layer value",
        cfg["calibration"]["sigma_u_over_ustar"],
        2.5,
        "-",
        "Panofsky & Dutton 1984; Kaimal & Finnigan 1994",
    )
    R.bracket(
        g,
        "all members' sigma_u/u* within 25 % of 2.5 (sampling spread)",
        float(np.abs(ratio / 2.5 - 1).max()),
        0.0,
        0.25,
        "-",
        "sampling error",
    )
    R.bracket(
        g,
        "u' mean over members and time is ~0",
        float(abs(x[..., 0].mean()) / (2.5 * ust)),
        0.0,
        0.05,
        "-",
        "zero-mean fluctuation",
    )
    Lm = float(mann_length(z, -500.0, cfg))
    _, sig = _unit_box(
        cfg["turbulence"]["gamma"],
        *[cfg["turbulence"]["box"][k] for k in ("nx", "ny", "nz", "dx_over_L", "ly_over_L", "lz_over_L")],
    )
    sc = 2.5 * ust / sig[0]
    kl, r, _ = _psd_ratio(x[..., 0], dt, U, Lm, sc, cfg)
    band = (kl > 0.3) & (kl < 1.5)
    R.bracket(
        g,
        "u spectrum / analytic Mann spectrum, 0.3 < kL < 1.5",
        float(r[band].mean()),
        0.85,
        1.15,
        "-",
        "Mann 1994 via mannrs.mann_spectra",
    )
    k = np.logspace(1.5, 3, 40)
    uu = mannrs.mann_spectra(k, 1.0, 1.0, cfg["turbulence"]["gamma"])[0]
    R.bracket(
        g,
        "Mann model inertial-range slope of F11(k1), 30 < kL < 1000",
        float(np.polyfit(np.log(k), np.log(uu), 1)[0]),
        -1.72,
        -1.62,
        "-",
        "Kolmogorov -5/3; Mann 1994",
    )
    s_k = _psd_ratio(x[..., 0], dt, U, Lm, sc, cfg)[2]
    sel = (kl > 0.5) & (kl < 1.5)
    ana = mannrs.mann_spectra(kl[sel], 1.0, 1.0, cfg["turbulence"]["gamma"])[0]
    R.bracket(
        g,
        "delivered u spectrum log-slope minus analytic Mann slope, 0.5 < kL < 1.5",
        float(np.polyfit(np.log(kl[sel]), np.log(s_k[sel]), 1)[0] - np.polyfit(np.log(kl[sel]), np.log(ana), 1)[0]),
        -0.3,
        0.3,
        "-",
        "Mann 1994",
    )
    # members sharing a box are uncorrelated
    c = np.corrcoef(x[:, :, 0])
    pooled = np.array([c[i, i + 6] for i in range(6)])  # member m and m + 6 share a box (6 boxes, 12 members)
    R.bracket(
        g,
        "rms zero-lag correlation between members sharing a box (sampling noise ~0.05)",
        float(np.sqrt((pooled**2).mean())),
        0.0,
        0.1,
        "-",
        "independence of pooled members",
    )


def _gust_receipts() -> None:
    from cafe import receipts as R

    cfg = load_config()
    g = "sub-grid"
    # gust fronts
    times = np.arange(0, 48 * 3600.0, 3600.0)
    wet = gust_fronts(2, np.full(times.size, 5.0), times, 2000, theta_e_K=np.full(times.size, 355.0), cfg=cfg)
    dry = gust_fronts(2, np.zeros(times.size), times, 2000, cfg=cfg)
    R.bracket(
        g,
        "events per member-hour, heavy rain / dry",
        float(wet.start.size / dry.start.size),
        10.0,
        200.0,
        "-",
        "Wills et al. 2021: cold pools sit under rain",
    )
    gs = cfg["calibration"]["gust_stats"]
    sp = np.hypot(wet.dU[:, 0], wet.dU[:, 1])
    R.bracket(g, "gust front peak dU, min", float(sp.min()), gs["dU_min"], gs["dU_max"], "m/s", "BRIEF 2.2 (+3 to +10 m/s)")
    R.bracket(g, "gust front peak dU, max", float(sp.max()), gs["dU_min"], gs["dU_max"], "m/s", "BRIEF 2.2 (+3 to +10 m/s)")
    R.bracket(
        g,
        "gust front duration range, min",
        float(wet.duration.min()),
        gs["duration_min_s"],
        gs["duration_max_s"],
        "s",
        "BRIEF 2.2 (10-30 min)",
    )
    R.bracket(
        g,
        "gust front duration range, max",
        float(wet.duration.max()),
        gs["duration_min_s"],
        gs["duration_max_s"],
        "s",
        "BRIEF 2.2 (10-30 min)",
    )
    one = Events(np.array([0]), np.array([0.0]), np.array([1200.0]), np.array([[6.0, 0.0]]), np.array([-1.5]), 1)
    dT10 = gust_perturbation(one, np.array([600.0]))[1].value[0, 0]
    R.bracket(
        g,
        "front dT 10 min after onset (Wills 2021 detection: <= -1.5 K within 10 min)",
        float(dT10),
        -1.6,
        -1.5,
        "K",
        "Wills et al. 2021",
    )


def _ocean_receipts() -> None:
    from cafe import receipts as R

    g = "sub-grid"
    # ocean SDE: well-mixed condition
    rng = np.random.default_rng(3)
    n, lx, dts, steps = 20000, 100.0, 1.0, 4000
    ratios = {}
    for name, use in (("with dK/dx", True), ("without dK/dx", False)):
        xs = np.stack([rng.uniform(0, lx, n), np.zeros(n)], axis=-1)
        for _ in range(steps):
            kx = 0.5 + 2.5 * xs[:, 0] / lx
            gk = np.zeros_like(xs)
            if use:
                gk[:, 0] = 2.5 / lx
            xs = ocean_sde_step(xs, kx, gk, dts, rng)
            xs[:, 0] = lx - np.abs(lx - np.abs(xs[:, 0]))  # reflecting walls at 0 and lx
        ratios[name] = np.mean(xs[:, 0] < lx / 2) / np.mean(xs[:, 0] >= lx / 2)
    sd = 2 * np.sqrt(1 / n) * 2  # ~ 4 sigma of the half-count ratio
    R.bracket(
        g,
        "well-mixed tracer: low-K / high-K count ratio, with dK/dx drift",
        float(ratios["with dK/dx"]),
        1 - sd,
        1 + sd,
        "-",
        "Thomson 1987",
    )
    R.bracket(
        g,
        "well-mixed tracer: ratio WITHOUT the drift term departs from 1 (negative control, must lie outside)",
        float(abs(ratios["without dK/dx"] - 1)),
        sd,
        10.0,
        "-",
        "Thomson 1987",
    )


def _surface_receipts() -> None:
    from cafe import receipts as R

    g = "sub-grid"
    # windage & jet
    w10 = np.tile([[6.0, 8.0]], (500, 1))
    wd = windage(4, w10).value
    R.bracket(
        g,
        "windage / U10 (min over 500 members)",
        float((np.hypot(wd[:, 0], wd[:, 1]) / 10).min()),
        0.018,
        0.023,
        "-",
        "BRIEF 2.2",
    )
    R.bracket(
        g,
        "windage / U10 (max over 500 members)",
        float((np.hypot(wd[:, 0], wd[:, 1]) / 10).max()),
        0.018,
        0.023,
        "-",
        "BRIEF 2.2",
    )
    jet = diurnal_jet(5, np.full(500, 3.0), w10).value
    js = np.hypot(jet[:, 0], jet[:, 1])
    R.bracket(g, "diurnal jet at dT = 3 K, min", float(js.min()), 0.1, 0.3, "m/s", "BRIEF 2.2 (TEPEX-C hypothesis)")
    R.bracket(g, "diurnal jet at dT = 3 K, max", float(js.max()), 0.1, 0.3, "m/s", "BRIEF 2.2 (TEPEX-C hypothesis)")
    R.bracket(
        g,
        "diurnal jet at dT = 0",
        float(np.abs(diurnal_jet(5, np.zeros(500), w10).value).max()),
        0.0,
        1e-12,
        "m/s",
        "scaled by dT",
    )
    R.bracket(
        g,
        "jet points downwind (cos angle to wind)",
        float((jet @ np.array([6.0, 8.0]) / (js * 10)).min()),
        0.999999,
        1.000001,
        "-",
        "downwind",
    )


def _lens_receipts() -> None:
    from cafe import receipts as R

    g = "sub-grid"
    # rain lens
    on = rain_lens(8.0, 3.0, 0.0)["dS"].value
    R.bracket(g, "rain lens dS at 3 m/s, 8 mm/h", float(on), 0.45, 0.5001, "psu", "Iyer & Drushka 2021 (dS ~ 0.5 psu)")
    R.bracket(
        g,
        "rain lens dS at 9 m/s, 8 mm/h (absent above ~8 m/s)",
        float(rain_lens(8.0, 9.0, 0.0)["dS"].value),
        0.0,
        1e-12,
        "psu",
        "Iyer & Drushka 2021",
    )
    R.bracket(
        g,
        "rain lens dS below 0.5 m is gone (z = -1.5 m)",
        float(rain_lens(8.0, 3.0, 0.0, z=-1.5)["dS"].value),
        0.0,
        0.01,
        "psu",
        "Iyer & Drushka 2021 (top ~0.5 m)",
    )


def receipts() -> list[dict]:
    """Published-reference and self-consistency checks for this module; returns the receipt records it appended."""
    from cafe import receipts as R

    n0 = len(R.OUT)
    for f in (_turbulence_receipts, _gust_receipts, _ocean_receipts, _surface_receipts, _lens_receipts):
        f()
    return R.OUT[n0:]
