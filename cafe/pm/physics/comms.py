"""Communication-link physics for the pre-mission check: RF (two-ray + horizon), Iridium (latency/availability), acoustic
(Thorp + Stojanovic budget, Bellhop for the ambiguous links). Every function is elementwise over numpy arrays
(leading axis = ensemble members, any trailing time axis); nothing loops over members.

Parameters live in platforms/radios.yaml and platforms/modems.yaml (each with its source and its assumptions).

References
- Two-ray: L = -20 log10[(lam/4 pi d) 2 sin(2 pi ht hr / lam d)] (BRIEF 2.8), here with exact path lengths, reflection
  coefficient -1 (grazing, smooth sea) and the Ament roughness factor on the reflected ray.
- Ament, W.S. (1953), "Toward a theory of reflection by a rough surface", Proc. IRE 41(1), 142-146; Beckmann & Spizzichino
  (1963), The Scattering of EM Waves from Rough Surfaces, ch. 5: rho_s = exp[-2 (2 pi sigma_h sin(psi)/lam)^2], sigma_h = Hs/4.
- Radio horizon: d = 4.12 (sqrt(ht) + sqrt(hr)) km, h in m, effective earth radius 4/3 x 6371 km
  (ITU-R P.834; Skolnik, Radar Handbook).
- Thorp (1967), J. Acoust. Soc. Am. 42, 270; formula as printed in Stojanovic (2007) eq. (4), f in kHz.
- Stojanovic, M. (2007), "On the relationship between capacity and distance in an underwater acoustic communication
  channel", ACM SIGMOBILE MC2R 11(4), 34-43: A(l,f) = l^k a(f)^l (eq. 1-3) and noise N(f) = turbulence + shipping + wind
  + thermal (eq. 6-10; after Coates 1989). Spreading is referenced to 1 m, absorption uses l in km.
- Sound speed: TEOS-10 (IOC/SCOR/IAPSO 2010) via gsw.sound_speed.
- Bellhop: Porter (2011), "The BELLHOP manual and user's guide";
  Acoustics Toolbox at_2026_10_27 built by bench/install_bellhop.sh.
"""
import functools
import os
import pathlib
import shutil

import numpy as np
import yaml

from .. import Tagged

PLATFORMS = pathlib.Path(__file__).resolve().parents[3] / "platforms"
C0 = 299792458.0
NO_LINK_DB = -200.0                  # margin returned when a link is physically impossible (beyond the radio horizon)
THORP_ONLY_LABEL = "Thorp only, Bellhop unavailable"


@functools.lru_cache(None)
def _yaml(name: str) -> dict:
    return yaml.safe_load((PLATFORMS / name).read_text())


# ---------------------------------------------------------------- RF
def radio_horizon_km(ht, hr=0.0):
    """4/3-earth radio horizon between antennas at heights ht, hr [m]: 4.12 (sqrt ht + sqrt hr) km (Skolnik; ITU-R P.834)."""
    return 4.12 * (np.sqrt(np.maximum(ht, 0.0)) + np.sqrt(np.maximum(hr, 0.0)))


def ament_rho(hs, grazing, wavelength):
    """Specular reflection reduction rho_s = exp[-2 (2 pi sigma sin(psi)/lam)^2], sigma = Hs/4 (Ament 1953). MODELLED."""
    return np.exp(-2.0 * (2 * np.pi * (hs / 4.0) * np.sin(grazing) / wavelength) ** 2)


def two_ray_loss_db(d, ht, hr, hs, f_hz):
    """Path loss [dB] over the sea at ground range d [m], antenna heights ht, hr [m] above the mean surface, significant
    wave height hs [m], frequency f_hz. Field = |1 - rho_s (r1/r2) exp(-j 2 pi (r2-r1)/lam)| x free space at the direct
    distance r1: reflection coefficient -1 (valid for grazing angles below ~1-2 deg, i.e. d >> 100 (ht+hr)/ lam-scale
    geometry; closer in it is a smooth-sea idealisation). Specular only: diffuse scatter is neglected, so null filling is
    underestimated. Antenna height changing with wave elevation on small craft is NOT modelled (the roughness term stands
    in for it statistically)."""
    lam = C0 / f_hz
    d = np.maximum(d, 1.0)
    r1, r2 = np.hypot(d, ht - hr), np.hypot(d, ht + hr)
    rho = ament_rho(hs, (ht + hr) / r2, lam)
    field = np.abs(1.0 - rho * (r1 / r2) * np.exp(-2j * np.pi * (r2 - r1) / lam))
    return 20 * np.log10(4 * np.pi * r1 / lam) - 20 * np.log10(np.maximum(field, 1e-12))


def _radio(radio):
    return radio if isinstance(radio, dict) else _yaml("radios.yaml")["radios"][radio]


def rf_margin(d, ht, hr, hs, radio="rfd900x"):
    """Link margin [dB] = Pt + Gt + Gr - cable - misc - L(two-ray) - sensitivity; NO_LINK_DB beyond the radio horizon.
    d [m] ground range; ht, hr [m] antenna heights above the surface; hs [m] significant wave height (local WRF/UMWM swh)."""
    r = _radio(radio)
    loss = two_ray_loss_db(d, ht, hr, hs, r["center_mhz"] * 1e6)
    m = r["tx_dbm"] + r["gt_dbi"] + r["gr_dbi"] - r["cable_loss_db"] - r["misc_loss_db"] - loss - r["rx_sens_dbm"]
    return np.where(np.asarray(d) <= radio_horizon_km(ht, hr) * 1e3, m, NO_LINK_DB)


# ---------------------------------------------------------------- Iridium
def iridium_session(n_bytes, rng, members, service="sbd", direction="MO"):
    """One message of n_bytes (scalar or (members,)) through Iridium: -> (success (members,) bool, latency_s (members,)).
    SBD is split into ceil(n/340) MO (270 MT) sessions; RUDICS is one call at 2.4 kbps. Each session is retried up to
    max_attempts; a failed attempt costs fail_cost_s. Availability and latency only, no range (BRIEF 2.8). Latency
    = log-normal session setup (assumed) + published transfer time (SBD 5 s short .. 20 s full message)."""
    p = _yaml("radios.yaml")["iridium"][service]
    n = np.broadcast_to(np.asarray(n_bytes, float), (members,))
    if service == "sbd":
        segs = np.maximum(np.ceil(n / p["max_bytes"][direction]), 1).astype(int)
        frac = np.minimum(n / p["max_bytes"][direction], 1.0)
        xfer = p["latency_short_s"] + (p["latency_full_s"] - p["latency_short_s"]) * frac
        xfer = np.where(segs > 1, p["latency_full_s"], xfer)[:, None, None]
    else:
        segs = np.ones(members, int)
        xfer = (8.0 * n / p["rate_bps"])[:, None, None]
    S, A = int(segs.max()), p["max_attempts"]
    ok_att = rng.random((members, S, A)) < p["p_success"]
    setup = np.exp(np.log(p["session_setup_median_s"]) + p["session_setup_sigma"] * rng.standard_normal((members, S, A)))
    first = np.argmax(ok_att, axis=-1)
    ok = ok_att.any(-1)
    t_ok = np.take_along_axis(setup, first[..., None], -1)[..., 0] + xfer[..., 0]
    t_seg = np.where(ok, first * p["fail_cost_s"] + t_ok, A * p["fail_cost_s"])
    used = np.arange(S)[None, :] < segs[:, None]
    return (ok | ~used).all(-1), (t_seg * used).sum(-1)


# ---------------------------------------------------------------- acoustics
def thorp_db_per_km(f_khz):
    """Thorp absorption [dB/km], f in kHz: 0.11 f2/(1+f2) + 44 f2/(4100+f2) + 2.75e-4 f2 + 0.003."""
    f2 = np.square(f_khz)
    return 0.11 * f2 / (1 + f2) + 44 * f2 / (4100 + f2) + 2.75e-4 * f2 + 0.003


def acoustic_tl_db(r_m, f_khz, k=1.5):
    """Stojanovic path loss 10 log A = k 10 log10(r/1 m) + r_km 10 log a(f) [dB]; k=1 cylindrical, 2 spherical."""
    r = np.maximum(r_m, 1.0)
    return 10 * k * np.log10(r) + thorp_db_per_km(f_khz) * r / 1e3


def stojanovic_noise_db(f_khz, wind, shipping=0.5):
    """Ambient noise PSD [dB re 1 uPa^2/Hz] at f_khz: turbulence + shipping (s in 0..1) + wind (w m/s) + thermal, power sum."""
    lf = np.log10(f_khz)
    turb = 17 - 30 * lf
    ship = 40 + 20 * (shipping - 0.5) + 26 * lf - 60 * np.log10(f_khz + 0.03)
    wnd = 50 + 7.5 * np.sqrt(wind) + 20 * lf - 40 * np.log10(f_khz + 0.4)
    therm = -15 + 20 * lf
    return 10 * np.log10(sum(10 ** (x / 10) for x in (turb, ship, wnd, therm)))


def band_noise_db(f_lo, f_hi, wind, shipping=0.5, n=33):
    """In-band noise level [dB re 1 uPa^2]: the PSD integrated over [f_lo, f_hi] kHz (trapezoid, power domain)."""
    f = np.linspace(f_lo, f_hi, n)
    psd = 10 ** (stojanovic_noise_db(f, np.asarray(wind, float)[..., None], shipping) / 10)
    return 10 * np.log10(np.trapezoid(psd, f * 1e3, axis=-1))


def _band(modem, band):
    return _yaml("modems.yaml")["modems"][modem]["bands"][band]


@functools.lru_cache(None)
def implementation_loss_db(modem, band, k=1.5):
    """Everything the budget does not model (multipath, platform noise, directivity, detector, true SL) in dB. Derived so
    the budget reproduces the vendor's published range at the reference conditions with anchor_margin_db to spare
    (modems.yaml defaults); bands with no published range copy another band's value (`implementation_loss_like`)."""
    b, d = _band(modem, band), _yaml("modems.yaml")["defaults"]
    if "implementation_loss_like" in b:
        return implementation_loss_db(*b["implementation_loss_like"], k)
    fc = np.mean(b["f_khz"])
    nl = band_noise_db(*b["f_khz"], d["ref_wind_ms"], d["ref_shipping"])
    return float(b["sl_db"] - acoustic_tl_db(b["range_km"] * 1e3, fc, k) - nl - b["snr_req_db"] - d["anchor_margin_db"])


def acoustic_margin(r, modem="benthos_atm960", band="MF", wind=5.0, shipping=0.5, k=1.5, tl_extra=0.0):
    """Thorp-budget margin [dB] = SL - TL - NL(band, wind) - SNR_req - implementation loss (+ tl_extra dB of extra
    transmission loss, e.g. Bellhop excess). r [m] range, wind [m/s] the WRF 10 m wind at the receiver."""
    b = _band(modem, band)
    tl = acoustic_tl_db(r, np.mean(b["f_khz"]), k) + tl_extra
    return b["sl_db"] - tl - band_noise_db(*b["f_khz"], wind, shipping) - b["snr_req_db"] - implementation_loss_db(modem, band, k)


def sound_speed_profile(z, t, SA=None, SP=None, lon=0.0, lat=0.0):
    """TEOS-10 sound speed [m/s] on a column: z [m, up, <= 0], in-situ temperature t [degC], and either SA [g/kg] or SP
    (practical salinity; converted with gsw.SA_from_SP at lon, lat)."""
    import gsw
    z = np.asarray(z, float)
    p = gsw.p_from_z(z, lat)
    SA = gsw.SA_from_SP(SP, p, lon, lat) if SA is None else SA
    return gsw.sound_speed(SA, gsw.CT_from_t(SA, t, p), p)


# ---------------------------------------------------------------- Bellhop
@functools.lru_cache(None)
def _bellhop_dir() -> str | None:
    """Directory holding a working bellhop.exe: $CAFE_DATA/bin (homebase: /data/bin), else PATH; None when absent."""
    here = pathlib.Path(os.environ.get("CAFE_DATA", "/data")) / "bin"
    exe = shutil.which("bellhop.exe", path=f"{here}{os.pathsep}{os.environ.get('PATH', '')}")
    return str(pathlib.Path(exe).parent) if exe else None


def bellhop_available() -> bool:
    return _bellhop_dir() is not None


def _run_bellhop(r_m, f_hz, z, c, tx_depth, rx_depth, water_depth):
    """Incoherent TL [dB] (Bellhop 'T' option includes Thorp volume attenuation) at ranges r_m (increasing, > 0)."""
    import arlpy.uwapm as pm
    os.environ["PATH"] = f"{_bellhop_dir()}{os.pathsep}{os.environ['PATH']}"          # arlpy shells out to `bellhop.exe`
    d = -np.asarray(z, float)
    if d[0] > 0:                                                                       # Bellhop needs the surface node
        d, c = np.r_[0.0, d], np.r_[c[0], c]
    if d[-1] < water_depth:
        d, c = np.r_[d, water_depth], np.r_[c, c[-1]]
    keep = d <= water_depth
    d, c = d[keep], np.asarray(c, float)[keep]
    if len(d) < 4:                                                                     # arlpy wants >= 4 profile points
        d, c = np.linspace(0.0, water_depth, 4), np.interp(np.linspace(0.0, water_depth, 4), d, c)
    prof = np.column_stack([d, c])
    env = pm.create_env2d(frequency=f_hz, depth=water_depth, soundspeed=prof, tx_depth=tx_depth, rx_depth=rx_depth,
                          rx_range=np.asarray(r_m, float), bottom_soundspeed=1700.0, bottom_density=1900.0,
                          bottom_absorption=0.5, min_angle=-80, max_angle=80, nbeams=0)
    p = pm.compute_transmission_loss(env, mode=pm.incoherent, model="bellhop")
    if p is None:
        raise RuntimeError("bellhop.exe ran but produced no field (see its .prt file)")
    return -20 * np.log10(np.maximum(np.abs(np.asarray(p)[0]), 1e-30))


def bellhop_tl(r_m, f_khz, z, c, tx_depth=1.0, rx_depth=5.0, water_depth=4000.0, n_grid=48):
    """Bellhop incoherent TL [dB] for any shape of r_m: one run on an `n_grid`-point range grid spanning r_m, interpolated."""
    r = np.asarray(r_m, float)
    lo = max(r.min(), 100.0)
    grid = np.linspace(lo, max(r.max(), 1.02 * lo), n_grid)                           # Bellhop wants strictly increasing ranges
    tl = _run_bellhop(grid, f_khz * 1e3, z, np.asarray(c, float), tx_depth, rx_depth, water_depth)
    return np.interp(r, grid, tl)


def acoustic_link(r, modem="benthos_atm960", band="MF", wind=5.0, ssp=None, shipping=0.5, k=1.5,
                  tx_depth=1.0, rx_depth=5.0, water_depth=4000.0, ambiguous_db=None):
    """Margin for every range in r. The Thorp budget decides every link whose margin is outside +-ambiguous_db of 0; the
    ambiguous ones are re-done with Bellhop on ssp = (z, c) (z up, <=0), which is the high-fidelity path.

    Bellhop enters as an EXCESS: its TL on ssp minus its TL on an isovelocity column (c at the surface), added to the Thorp
    TL. The implementation loss is anchored to the vendor range under Thorp k=1.5 spreading, so an absolute Bellhop TL
    (deep isovelocity water is spherical, k=2) would double-count the spreading; the excess keeps what Thorp cannot see
    (refraction, ducts, shadow zones) and nothing else. Absolute TLs are returned too.

    Returns dict: margin (Tagged), thorp_margin, ambiguous (bool), method (str per element), label (str; THORP_ONLY_LABEL
    when an ambiguous link could not be refined), tl_bellhop_db / tl_bellhop_iso_db (NaN where Bellhop did not run)."""
    r, w = np.broadcast_arrays(np.asarray(r, float), np.asarray(wind, float))
    amb_db = _yaml("modems.yaml")["defaults"]["ambiguous_db"] if ambiguous_db is None else ambiguous_db
    m_t = acoustic_margin(r, modem, band, w, shipping, k)
    amb = np.abs(m_t) <= amb_db
    tl_b, tl_i = np.full(m_t.shape, np.nan), np.full(m_t.shape, np.nan)
    method = np.full(m_t.shape, "thorp", dtype=object)
    margin, label = m_t.copy(), "Thorp budget decides every link"
    if amb.any():
        if bellhop_available() and ssp is not None:
            z, c = ssp
            f = float(np.mean(_band(modem, band)["f_khz"]))
            tl_b[amb] = bellhop_tl(r[amb], f, z, c, tx_depth, rx_depth, water_depth)
            tl_i[amb] = bellhop_tl(r[amb], f, z, np.full(len(np.atleast_1d(z)), c[0]), tx_depth, rx_depth, water_depth)
            margin[amb] = acoustic_margin(r[amb], modem, band, w[amb], shipping, k, tl_extra=tl_b[amb] - tl_i[amb])
            method[amb] = "bellhop"
            label = "Bellhop refined the ambiguous links"
        else:
            method[amb] = "thorp-only (bellhop unavailable)" if ssp is not None else "thorp-only (no sound-speed profile)"
            label = THORP_ONLY_LABEL if ssp is not None else "Thorp only, no sound-speed profile supplied"
    src = f"Thorp/Stojanovic budget {modem}/{band}" + (" + Bellhop" if label.startswith("Bellhop") else "")
    return dict(margin=Tagged(margin, src, None, "modelled"),
                thorp_margin=m_t, ambiguous=amb, method=method, label=label, tl_bellhop_db=tl_b, tl_bellhop_iso_db=tl_i)


# ---------------------------------------------------------------- receipts
def receipts() -> list:
    """Run every comms receipt through cafe.receipts and return the entries it recorded."""
    from cafe import receipts as R
    n0, g = len(R.OUT), "Comms"

    def rc(claim, value, ref, tol, unit, src, rel=True):
        R.receipt(g, claim, float(value), ref, tol, unit, src, rel=rel)

    def br(claim, value, lo, hi, unit, src):
        R.bracket(g, claim, float(value), lo, hi, unit, src)

    f, lam = 915e6, C0 / 915e6
    # two-ray: 4th-power law far out (-40 dB/decade, independent of frequency) and the last null at d = 2 ht hr / lam
    L = two_ray_loss_db(np.array([5e3, 5e4]), 2.0, 5.0, 0.0, f)
    rc("Two-ray far field: loss rise per decade of range", L[1] - L[0], 40.0, 0.05, "dB",
       "d^-4 law (Rappaport, Wireless Communications 2e, sec 4.6)", rel=False)
    dg = np.linspace(30, 120, 90001)
    rc("Two-ray last null for ht=2 m, hr=5 m at 915 MHz", dg[np.argmax(two_ray_loss_db(dg, 2.0, 5.0, 0.0, f))],
       2 * 2.0 * 5.0 / lam, 0.01, "m", "2 pi ht hr/(lam d) = pi (BRIEF 2.8)")
    rc("Rough sea (rho=0) collapses to free space at 1 km, 915 MHz", two_ray_loss_db(1e3, 2.0, 5.0, 1e3, f),
       32.44 + 20 * np.log10(915.0), 0.002, "dB", "FSPL = 32.44 + 20 log d_km + 20 log f_MHz (Friis)")
    rc("Ament factor when 4 pi sigma sin(psi)/lam = 1", ament_rho(lam / np.pi, np.pi / 2, lam), np.exp(-0.5), 1e-9, "",
       "Ament 1953 / Beckmann-Spizzichino: rho_s = exp(-g/2), g = (4 pi sigma sin psi/lam)^2")
    re_, kf = 6371e3, 4.0 / 3.0
    for h in (2.0, 5.0):
        rc(f"Radio horizon of a {h:g} m antenna", radio_horizon_km(h), np.sqrt(2 * kf * re_ * h) / 1e3, 0.002, "km",
           "sqrt(2 k Re h), k=4/3, Re=6371 km")
    rc("Radio horizon between 2 m and 5 m antennas", radio_horizon_km(2.0, 5.0),
       (np.sqrt(2 * kf * re_ * 2.0) + np.sqrt(2 * kf * re_ * 5.0)) / 1e3, 0.002, "km", "sum of the two horizons")
    # acoustics
    rc("Thorp absorption at 10 kHz", thorp_db_per_km(10.0), 1.187, 0.001, "dB/km",
       "Thorp 1967, by hand: 0.1089+1.0476+0.0275+0.003")
    br("Thorp absorption at 10 kHz is ~1.1-1.2 dB/km", thorp_db_per_km(10.0), 1.1, 1.2, "dB/km", "BRIEF 2.8")
    fk = np.logspace(0, 2.5, 600)
    br("Stojanovic noise-PSD minimum (calm, 0 m/s wind) lies at tens of kHz", fk[np.argmin(stojanovic_noise_db(fk, 0.0))],
       10.0, 100.0, "kHz", "Stojanovic 2007 fig. 2 / Coates 1989")
    dw = stojanovic_noise_db(10.0, 10.0) - stojanovic_noise_db(10.0, 0.0)
    rc("Wind noise at 10 kHz rises with 7.5 sqrt(w): 10 vs 0 m/s wind", dw,
       7.5 * np.sqrt(10.0), 0.01, "dB", "Stojanovic 2007 wind term (the other terms dilute it)")
    for r_km, lo, hi in ((4.0, 0.0, 30.0), (6.0, -30.0, 0.0), (8.0, -60.0, 0.0)):
        br(f"Benthos ATM-960 MF margin at {r_km:g} km, 5 m/s wind", acoustic_margin(r_km * 1e3), lo, hi, "dB",
           "anchored to the vendor's >= 4 km (modelled; the 4 km row is the anchor, 6/8 km the shape)")
    br("Benthos LF margin at 6 km and HF at 2 km, 5 m/s wind (the smaller)",
       min(acoustic_margin(6e3, band="LF"), acoustic_margin(2e3, band="HF")), 0.0, 30.0, "dB", "vendor LF >= 6 km, HF >= 2 km")
    R.context(g, "Benthos ATM-960 MF margin at 4 km in 10 m/s wind (a rougher sea than the 5.4 m/s window mean)",
              float(acoustic_margin(4e3, wind=10.0)), 0.0, "dB", "modelled: wind noise +6.9 dB over the 5 m/s anchor")
    # Bellhop vs Thorp on an isovelocity column: Thorp with spherical spreading (k=2, deep isovelocity) and the Lloyd-mirror
    # image doubling the incoherent intensity (-3 dB)
    if bellhop_available():
        rg, worst = np.linspace(500, 6000, 12), 0.0
        for fkhz in (11.5, 18.5, 24.5):
            tl = bellhop_tl(rg, fkhz, np.array([0.0, -4000.0]), np.array([1500.0, 1500.0]))
            worst = max(worst, float(np.max(np.abs(tl - (acoustic_tl_db(rg, fkhz, 2.0) - 10 * np.log10(2))))))
        br("Bellhop vs Thorp (k=2, -3 dB image) isovelocity TL, 11.5/18.5/24.5 kHz, 0.5-6 km: worst |difference|",
           worst, 0.0, 3.0, "dB", "BRIEF 2.8 receipt; Bellhop incoherent, 4000 m water, tx 1 m, rx 5 m")
    else:
        R.context(g, "Bellhop vs Thorp isovelocity TL: NOT RUN, " + THORP_ONLY_LABEL, float("nan"), 3.0, "dB",
                  "bellhop.exe not found; run bench/install_bellhop.sh")
    # Iridium
    ok, lat = iridium_session(100, np.random.default_rng(0), 200000)
    p = _yaml("radios.yaml")["iridium"]["sbd"]
    rc("Iridium SBD success after retries", ok.mean(), 1 - (1 - p["p_success"]) ** p["max_attempts"], 2e-4, "",
       "binomial over attempts (assumed per-attempt p)", rel=False)
    br("Iridium SBD median latency of a 100 B message", np.median(lat[ok]), 15.0, 40.0, "s",
       "published nominal 5-20 s + session setup; RockBLOCK guide ~40 s per session")
    return R.OUT[n0:]
