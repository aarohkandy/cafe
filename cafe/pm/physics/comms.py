"""Communication-link physics for the pre-mission check: RF (two-ray + horizon), Iridium (latency/availability), acoustic
(Thorp + Stojanovic budget, Bellhop for the ambiguous links). Every function is elementwise over numpy arrays
(leading axis = ensemble members, any trailing time axis); nothing loops over members.

Parameters live in platforms/radios.yaml and platforms/modems.yaml (each with its source and its assumptions).

References
- Two-ray: L = -20 log10[(lam/4 pi d) 2 sin(2 pi ht hr / lam d)] (BRIEF 2.8), here over a 4/3-radius earth: the reflection point from
  Kerr's cubic, the antenna heights above the tangent plane there, exact path lengths, reflection coefficient -1 (grazing, smooth sea; the error
  against the Fresnel coefficient is stated in `two_ray_curved_db`), the divergence factor of the curved surface and the Ament roughness factor on
  the reflected ray.
- Kerr, D.E. (ed.) (1951), Propagation of Short Radio Waves, MIT Rad. Lab. Series 13, ch. 2 (reflection point on a spherical earth,
  divergence factor); Blake, L.V. (1980), Radar Range-Performance Analysis, ch. 5.
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
from typing import Any, cast

import numpy as np
from numpy.typing import ArrayLike, NDArray

from .. import Tagged, config

PLATFORMS = pathlib.Path(__file__).resolve().parents[3] / "platforms"
PARAMETER_FILES = ("radios.yaml", "modems.yaml")                     # every file `_yaml` reads: the hangar stage hashes each (a ledger input, round 11 L1)
C0 = 299792458.0
NO_LINK_DB = -200.0                  # margin returned when a link is physically impossible (beyond the radio horizon)
THORP_ONLY_LABEL = "Thorp only, Bellhop unavailable"
F = NDArray[np.float64]
FA = float | F


def _plain(node: Any) -> Any:
    """radios.yaml marks assumed numbers as {value, unit, assumed: true, why} leaves (so the credibility report counts them);
    the link models read the bare value."""
    if isinstance(node, dict):
        return node["value"] if "value" in node and "unit" in node else {k: _plain(v) for k, v in node.items()}
    return node


@functools.lru_cache(None)
def _yaml(name: str) -> dict[str, Any]:
    d = config._yaml(PLATFORMS / name)                                 # duplicate keys and octal numbers refused (round 5, M-18)
    return cast(dict[str, Any], _plain(d) if name == "radios.yaml" else d)


# ---------------------------------------------------------------- RF
def radio_horizon_km(ht: FA, hr: FA = 0.0) -> F:
    """4/3-earth radio horizon between antennas at heights ht, hr [m]: 4.12 (sqrt ht + sqrt hr) km (Skolnik; ITU-R P.834)."""
    return 4.12 * (np.sqrt(np.maximum(ht, 0.0)) + np.sqrt(np.maximum(hr, 0.0)))


def ament_rho(hs: FA, grazing: FA, wavelength: FA) -> F:
    """Specular reflection reduction rho_s = exp[-2 (2 pi sigma sin(psi)/lam)^2], sigma = Hs/4 (Ament 1953). MODELLED."""
    return np.exp(-2.0 * (2 * np.pi * (hs / 4.0) * np.sin(grazing) / wavelength) ** 2)


A_EFF = 4.0 / 3.0 * 6371e3           # effective earth radius [m] (k = 4/3), the one the radio horizon uses


def kerr_reflection(d: FA, ht: FA, hr: FA, a: float = A_EFF) -> tuple[F, F, F, F]:
    """Specular point of a smooth sphere of radius a (default A_EFF; 1e12 is flat to 1e-6 relative) between antennas ht, hr [m] at ground range
    d [m] (Kerr 1951; Blake 1980 ch. 5):
    the root of the cubic 2x^3 - 3dx^2 + (d^2 - 2a(ht+hr))x + 2a ht d = 0 for the ground range x = R1 from the ht antenna, by its trigonometric form.
    -> R1, R2 = d - R1, and the antenna heights above the tangent plane at that point, h1 = ht - R1^2/2a, h2 = hr - R2^2/2a (zero at the horizon, clipped
    there: beyond it the reflection point is below the line of sight and the function stays finite)."""
    p = 2.0 / np.sqrt(3.0) * np.sqrt(a * (ht + hr) + (d / 2.0) ** 2)
    phi = np.arccos(np.clip(2.0 * a * (hr - ht) * d / p ** 3, -1.0, 1.0))
    r1 = d / 2.0 - p * np.cos((phi + np.pi) / 3.0)
    r2 = d - r1
    return r1, r2, np.maximum(ht - r1 ** 2 / (2 * a), 0.0), np.maximum(hr - r2 ** 2 / (2 * a), 0.0)


def divergence_factor(d: FA, r1: FA, r2: FA, psi: FA, a: float = A_EFF) -> F:
    """Divergence of the reflected beam off the convex sphere, in (0, 1]: D = [1 + 2 R1 R2 / (a d sin psi)]^-1/2 x [1 + 2 R1 R2 sin psi / (a d)]^-1/2
    (the two principal planes of a spherical mirror, focal lengths a sin(psi)/2 in the plane of incidence and a/(2 sin psi) across it; Kerr 1951;
    Blake 1980). psi [rad] is the grazing angle at the specular point; D falls to 0 as psi does, i.e. toward the horizon."""
    s = np.maximum(np.sin(psi), 1e-9)
    q = 2.0 * r1 * r2 / (a * d)
    return ((1.0 + q / s) * (1.0 + q * s)) ** -0.5


FLAT_A = 1e12                        # earth radius [m] that stands for a plane earth (flat to 1e-6 relative)


def psi_critical(lam: FA, a: float = A_EFF) -> FA:
    """Grazing angle [rad] below which the geometric-optics two-ray solution is not trusted: psi_c = (lam / (pi a))^(1/3), 2.3 mrad at 915 MHz over the
    4/3 earth. ASSUMED: the interference region of the Kerr / Blake treatment is said to end at about this angle, recalled and not re-read (Blake 1980
    ch. 5); replace with the re-read value, or with a smooth-earth diffraction field (ITU-R P.526), which this model does not have."""
    return (lam / (np.pi * a)) ** (1.0 / 3.0)


def two_ray_curved_db(d: FA, ht: FA, hr: FA, hs: FA, f_hz: FA, divergence: bool = True, a_eff: float = A_EFF) -> F:
    """The geometric-optics two-ray loss [dB] over the sea at ground range d [m], antenna heights ht, hr [m] above the mean surface, significant
    wave height hs [m], frequency f_hz, over a sphere of radius a_eff (default the 4/3 earth; FLAT_A is the plane earth). Field = |1 - rho_s D (r1/r2)
    exp(-j 2 pi (r2-r1)/lam)| x free space at the direct distance r1: r1, r2 are the direct and reflected path lengths between the antenna heights
    above the tangent plane at the specular point (kerr_reflection), D the divergence factor (divergence_factor; `divergence=False` leaves it out),
    reflection coefficient -1: the limit of the Fresnel coefficient G of a vertical-polarised wave on sea water as the grazing angle goes to 0, and a
    smooth-sea idealisation everywhere else. Round 12 (review C-6), for sea water at 915 MHz with eps_c = 72.8 - j118.9 (T 29 C, S 35, sigma 6.05 S/m, for
    eps'' = 60 lambda sigma is 118.9 at 915 MHz: ASSUMED, the lab has not given the sea temperature or the antenna polarisation, QUESTIONS_FOR_LAB),
    |G| is 0.98 at 0.05 deg, 0.91 at 0.25, 0.84 at 0.5, 0.70 at 1, 0.49 at 2, 0.35 at 3, 0.26 at 5 (the pseudo-Brewster angle, phase -86 deg), 0.49 at 12
    and 0.65 at 20 deg, and its phase is
    -179 deg at 0.05, -168 at 1 and -154 at 2 deg: -1 is within 10 % of the magnitude only below about 0.3 deg, not below "1-2 deg" as this docstring
    said until then. The demo's grazing angles (UAS 18 to 108 m, USV whip 2.2 m) are 1.2 deg at 1 km and 0.2 deg at 5 km for the 18 m UAS and 6.3 and
    1.3 deg for the 108 m UAS, so -1 is within 10 % of the magnitude from about 4 km out for the 18 m UAS (0.3 deg at 3.9 km, flat earth) and from
    about 21 km for the 108 m UAS, not inside those distances; the UAS-ship hook inside a sortie (a 15 m mast, a few hundred metres to a few km)
    is at 2 to 30 deg, where |G| is 0.26 at 5 deg and 0.65 at 20 deg. The error band of the margin against the Fresnel coefficient, as the
    reviewer measured it (a script run outside this module, with this module's geometry and G(psi) in place of -1; with -1 it reproduces this
    function to 0.0 dB; the margin sweeps were not re-run): this model is optimistic at interference peaks, by up to 7.6 dB, and conservative at nulls;
    on the UAS-USV mission link from 0.2 km to the horizon the Fresnel margin is 7.4 dB lower to 23.6 dB higher at Hs 0.5 m and 2.8 dB lower to 6.9 dB
    higher at Hs 1.5 m; on the sortie hook (0.05 to 6 km, Hs 0.5 m) 7.5 dB lower to 34.7 dB higher; no sample changed its sign. No verdict of the demo
    rests on it (usv-uas-rf is NO-GO because 89 % of its needed moments are beyond the radio horizon, and the UAS lost-link mode is 0 of 64), but a link
    whose budget is within about 8 dB at a peak is not decided by this function. Specular only: diffuse scatter is neglected, so null filling is
    underestimated. Antenna height changing with wave elevation on small craft is NOT modelled (the roughness term stands in for it statistically).
    Fades out toward the horizon (D -> 0): use two_ray_loss_db."""
    lam = C0 / f_hz
    d = np.maximum(d, 1.0)
    q1, q2, h1, h2 = kerr_reflection(d, ht, hr, a_eff)
    r1, r2 = np.hypot(d, h1 - h2), np.hypot(d, h1 + h2)
    psi = np.arctan2(h1 + h2, d)                      # the grazing angle: tan(psi) = h1 / R1 = h2 / R2 (ament_rho takes the sine itself)
    rho = ament_rho(hs, psi, lam) * (divergence_factor(d, q1, q2, psi, a_eff) if divergence else 1.0)
    field = np.abs(1.0 - rho * (r1 / r2) * np.exp(-2j * np.pi * (r2 - r1) / lam))
    return cast(F, 20 * np.log10(4 * np.pi * r1 / lam) - 20 * np.log10(np.maximum(field, 1e-12)))


def two_ray_loss_db(d: FA, ht: FA, hr: FA, hs: FA, f_hz: FA, a_eff: float = A_EFF) -> F:
    """Path loss [dB] over the sea: the curved-earth two-ray loss with divergence (two_ray_curved_db) while the grazing angle at the specular point
    is above psi_critical; between that limit and the radio horizon the larger of it and the plane-earth loss (FLAT_A), so the loss cannot fall
    toward free space as D -> 0 where the geometric optics no longer holds; beyond the horizon the curved loss, unchanged (rf_margin gives no link
    there). Within 2 km the curved and the plane-earth loss agree between interference nulls and differ AT them,
    by an amount that grows as the distance is sampled more finely (the nulls are sharp): the largest |difference| for d = 100 to 2000 m at 915 MHz,
    Hs 0, sampled every 1 m (every 5 cm): 0.8 dB (1.0) for a surface antenna pair, ht 2.2 m and hr 10 m; 26 dB (29) with the UAS at the top of
    its profile, ht 2.2 m and hr 108.1 m; 20 dB (34) for ht 10 m and hr 18.1 m; with Hs 1 m 2.4 dB and with Hs 3 m 0.3 dB for that last pair. The
    lost-link time of a UAS sortie is the statistic that depends on it (round 8, M-49; the earlier 0.15 dB was measured at single distances).
    ponytail: no smooth-earth diffraction (ITU-R P.526) in the transition zone, the plane-earth loss stands in for it and is conservative by
    construction; upgrade path is the P.526 field between psi_critical and the horizon."""
    d = np.maximum(d, 1.0)
    curved = two_ray_curved_db(d, ht, hr, hs, f_hz, True, a_eff)
    _, _, h1, h2 = kerr_reflection(d, ht, hr, a_eff)
    horizon = np.sqrt(2.0 * a_eff) * (np.sqrt(np.maximum(ht, 0.0)) + np.sqrt(np.maximum(hr, 0.0)))
    transition = (np.arctan2(h1 + h2, d) < psi_critical(C0 / f_hz, a_eff)) & (d <= horizon)
    return cast(F, np.where(transition, np.maximum(curved, two_ray_curved_db(d, ht, hr, hs, f_hz, False, FLAT_A)), curved)[()])


def _radio(radio: str | dict[str, Any]) -> dict[str, Any]:
    return radio if isinstance(radio, dict) else _yaml("radios.yaml")["radios"][radio]


def uas_radio_names(P: dict[str, Any]) -> tuple[str, str]:
    """(the `radio` block of a UAS platform, the entry of platforms/radios.yaml) the lost-link hook reads (`stage1._uas_radio`): the platform's first `radio`
    block with a `tx_power_dbm`, and the entry of that name, else rfd900x. A platform with no such block is (rfd900x, rfd900x). The one choice, shared by the
    hook and by the credibility report's "used by this mission" rule (round 13, M-2: the report listed the entry as unused)."""
    block = next((k for k, v in (P.get("radio") or {}).items() if isinstance(v, dict) and "tx_power_dbm" in v), "rfd900x")
    return block, block if block in _yaml("radios.yaml")["radios"] else "rfd900x"


def rf_margin(d: FA, ht: FA, hr: FA, hs: FA, radio: str | dict[str, Any] = "rfd900x") -> F:
    """Link margin [dB] = Pt + Gt + Gr - cable - misc - L(two-ray) - sensitivity; NO_LINK_DB beyond the radio horizon.
    d [m] ground range; ht, hr [m] antenna heights above the surface; hs [m] significant wave height (local WRF/UMWM swh)."""
    r = _radio(radio)
    loss = two_ray_loss_db(d, ht, hr, hs, r["center_mhz"] * 1e6)
    m = r["tx_dbm"] + r["gt_dbi"] + r["gr_dbi"] - r["cable_loss_db"] - r["misc_loss_db"] - loss - r["rx_sens_dbm"]
    return np.where(np.asarray(d) <= radio_horizon_km(ht, hr) * 1e3, m, NO_LINK_DB)


# ---------------------------------------------------------------- Iridium
def iridium_session(n_bytes: FA, rng: np.random.Generator, members: int, service: str = "sbd", direction: str = "MO") -> tuple[NDArray[np.bool_], F]:
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
def thorp_db_per_km(f_khz: FA) -> F:
    """Thorp absorption [dB/km], f in kHz: 0.11 f2/(1+f2) + 44 f2/(4100+f2) + 2.75e-4 f2 + 0.003."""
    f2 = np.square(f_khz)
    return cast(F, 0.11 * f2 / (1 + f2) + 44 * f2 / (4100 + f2) + 2.75e-4 * f2 + 0.003)


SPREADING_K = 1.5        # Stojanovic 2007 practical spreading (1 cylindrical, 2 spherical): a constant of the code, not a table entry (round 11, M-16)


def acoustic_tl_db(r_m: FA, f_khz: FA, k: float = SPREADING_K) -> F:
    """Stojanovic path loss 10 log A = k 10 log10(r/1 m) + r_km 10 log a(f) [dB]; k=1 cylindrical, 2 spherical."""
    r = np.maximum(r_m, 1.0)
    return 10 * k * np.log10(r) + thorp_db_per_km(f_khz) * r / 1e3


def stojanovic_noise_db(f_khz: FA, wind: FA, shipping: float = 0.5) -> F:
    """Ambient noise PSD [dB re 1 uPa^2/Hz] at f_khz: turbulence + shipping (s in 0..1) + wind (w m/s) + thermal, power sum."""
    lf = np.log10(f_khz)
    turb = 17 - 30 * lf
    ship = 40 + 20 * (shipping - 0.5) + 26 * lf - 60 * np.log10(f_khz + 0.03)
    wnd = 50 + 7.5 * np.sqrt(wind) + 20 * lf - 40 * np.log10(f_khz + 0.4)
    therm = -15 + 20 * lf
    return 10 * np.log10(sum(10 ** (x / 10) for x in (turb, ship, wnd, therm)))


def band_noise_db(f_lo: float, f_hi: float, wind: FA, shipping: float = 0.5, n: int = 33) -> F:
    """In-band noise level [dB re 1 uPa^2]: the PSD integrated over [f_lo, f_hi] kHz (trapezoid, power domain)."""
    f = np.linspace(f_lo, f_hi, n)
    psd = 10 ** (stojanovic_noise_db(f, np.asarray(wind, float)[..., None], shipping) / 10)
    return 10 * np.log10(np.trapezoid(psd, f * 1e3, axis=-1))


def modem_names() -> dict[str, tuple[str, str]]:
    """Every name a link's `modem` may take, lowercase, with the (modems.yaml key, band) it means: `<key>_<band>` for each band, and the bare `<key>` for
    the modem's default band: its only band, else MF where it has one (the name the demo's early missions used), else none (round 11, M-14). The one
    table the mission loader and stage 1 both resolve through."""
    names: dict[str, tuple[str, str]] = {}
    for key, m in _yaml("modems.yaml")["modems"].items():
        bands = list(m["bands"])
        names.update({f"{key}_{b}".lower(): (key, b) for b in bands})
        default = bands[0] if len(bands) == 1 else "MF" if "MF" in bands else None
        if default is not None:
            names.setdefault(key.lower(), (key, default))
    return names


def resolve_modem(name: str) -> tuple[str, str] | None:
    """(modems.yaml key, band) a link's `modem` names, any case, or None when it names no modem band (see `modem_names`)."""
    return modem_names().get(name.lower())


def _band(modem: str, band: str) -> dict[str, Any]:
    return cast(dict[str, Any], _yaml("modems.yaml")["modems"][modem]["bands"][band])


@functools.lru_cache(None)
def implementation_loss_db(modem: str, band: str, k: float = SPREADING_K) -> float:
    """Everything the budget does not model (multipath, platform noise, directivity, detector, true SL) in dB. Derived so
    the budget reproduces the vendor's published range at the reference conditions with anchor_margin_db to spare
    (modems.yaml defaults); bands with no published range copy another band's value (`implementation_loss_like`)."""
    b, d = _band(modem, band), _yaml("modems.yaml")["defaults"]
    if "implementation_loss_like" in b:
        return implementation_loss_db(*b["implementation_loss_like"], k)
    fc = np.mean(b["f_khz"])
    f_lo, f_hi = b["f_khz"]
    nl = band_noise_db(f_lo, f_hi, d["ref_wind_ms"], d["ref_shipping"])
    return float(b["sl_db"] - acoustic_tl_db(b["range_km"] * 1e3, fc, k) - nl - b["snr_req_db"] - d["anchor_margin_db"]["value"])


def valid_range_m(modem: str, band: str) -> float:
    """Slant range [m] beyond which the Thorp budget of this band is an extrapolation: `valid_range_factor` (modems.yaml defaults, assumed) times
    the vendor's published range the budget is anchored to (a band with `implementation_loss_like` takes that band's range)."""
    b = _band(modem, band)
    if "implementation_loss_like" in b:
        return valid_range_m(*b["implementation_loss_like"])
    return float(_yaml("modems.yaml")["defaults"]["valid_range_factor"]["value"] * b["range_km"] * 1e3)


def acoustic_margin(r: FA, modem: str = "benthos_atm960", band: str = "MF", wind: FA = 5.0, shipping: float = 0.5, k: float = SPREADING_K,
                    tl_extra: FA = 0.0) -> F:
    """Thorp-budget margin [dB] = SL - TL - NL(band, wind) - SNR_req - implementation loss (+ tl_extra dB of extra
    transmission loss, e.g. Bellhop excess). r [m] range, wind [m/s] the WRF 10 m wind at the receiver."""
    b = _band(modem, band)
    tl = acoustic_tl_db(r, np.mean(b["f_khz"]), k) + tl_extra
    f_lo, f_hi = b["f_khz"]
    return cast(F, b["sl_db"] - tl - band_noise_db(f_lo, f_hi, wind, shipping) - b["snr_req_db"] - implementation_loss_db(modem, band, k))


def sound_speed_profile(z: FA, t: FA, SA: FA | None = None, SP: FA | None = None, lon: float = 0.0, lat: float = 0.0) -> F:
    """TEOS-10 sound speed [m/s] on a column: z [m, up, <= 0], in-situ temperature t [degC], and either SA [g/kg] or SP
    (practical salinity; converted with gsw.SA_from_SP at lon, lat)."""
    import gsw
    z = np.asarray(z, float)
    p = gsw.p_from_z(z, lat)
    SA = gsw.SA_from_SP(SP, p, lon, lat) if SA is None else SA
    return cast(F, gsw.sound_speed(SA, gsw.CT_from_t(SA, t, p), p))


# ---------------------------------------------------------------- Bellhop
@functools.lru_cache(None)
def _bellhop_dir() -> str | None:
    """Directory holding a working bellhop.exe: $CAFE_DATA/bin (homebase: /data/bin), else PATH; None when absent."""
    here = pathlib.Path(os.environ.get("CAFE_DATA", "/data")) / "bin"
    exe = shutil.which("bellhop.exe", path=f"{here}{os.pathsep}{os.environ.get('PATH', '')}")
    return str(pathlib.Path(exe).parent) if exe else None


def bellhop_available() -> bool:
    return _bellhop_dir() is not None


def _run_bellhop(r_m: ArrayLike, f_hz: float, z: ArrayLike, c: F, tx_depth: float, rx_depth: float, water_depth: float) -> F:
    """Incoherent TL [dB] (Bellhop 'T' option includes Thorp volume attenuation) at ranges r_m (increasing, > 0)."""
    import arlpy.uwapm as pm
    if (bd := _bellhop_dir()) not in os.environ["PATH"].split(os.pathsep):             # arlpy shells out to `bellhop.exe`; once (round 8, M-37)
        os.environ["PATH"] = f"{bd}{os.pathsep}{os.environ['PATH']}"
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
    return cast(F, -20 * np.log10(np.maximum(np.abs(np.asarray(p)[0]), 1e-30)))


def bellhop_tl(r_m: ArrayLike, f_khz: float, z: ArrayLike, c: ArrayLike, tx_depth: float = 1.0, rx_depth: float = 5.0, water_depth: float = 4000.0,
               n_grid: int = 48) -> F:
    """Bellhop incoherent TL [dB] for any shape of r_m: one run on an `n_grid`-point range grid spanning r_m, interpolated."""
    r = np.asarray(r_m, float)
    lo = max(r.min(), 100.0)
    grid = np.linspace(lo, max(r.max(), 1.02 * lo), n_grid)                           # Bellhop wants strictly increasing ranges
    tl = _run_bellhop(grid, f_khz * 1e3, z, np.asarray(c, float), tx_depth, rx_depth, water_depth)
    return cast(F, np.interp(r, grid, tl))


def acoustic_link(r: FA, modem: str = "benthos_atm960", band: str = "MF", wind: FA = 5.0, ssp: tuple[FA, F] | None = None,
                  shipping: float = 0.5, k: float = SPREADING_K, tx_depth: float = 1.0, rx_depth: float = 5.0, water_depth: float = 4000.0,
                  ambiguous_db: float | None = None, dz: FA = 0.0) -> dict[str, Any]:
    """Margin for every horizontal range r [m]. The path the Thorp budget sees is the slant range hypot(r, dz), dz [m] the vertical
    separation of the two ends (0: both at the same depth). The Thorp budget decides every link whose margin is outside +-ambiguous_db
    of 0; the ambiguous ones are re-done with Bellhop on ssp = (z, c) (z up, <=0), which is the high-fidelity path (Bellhop takes the
    horizontal range and the depths).

    Bellhop enters as an EXCESS: its TL on ssp minus its TL on an isovelocity column (c at the surface), added to the Thorp
    TL. The implementation loss is anchored to the vendor range under Thorp k=1.5 spreading, so an absolute Bellhop TL
    (deep isovelocity water is spherical, k=2) would double-count the spreading; the excess keeps what Thorp cannot see
    (refraction, ducts, shadow zones) and nothing else. Absolute TLs are returned too.

    Returns dict: margin (Tagged), thorp_margin, ambiguous (bool), method (str per element), label (str; THORP_ONLY_LABEL
    when an ambiguous link could not be refined), tl_bellhop_db / tl_bellhop_iso_db (NaN where Bellhop did not run)."""
    r, w, dz = np.broadcast_arrays(np.asarray(r, float), np.asarray(wind, float), np.asarray(dz, float))
    slant = np.hypot(r, dz)
    amb_db = _yaml("modems.yaml")["defaults"]["ambiguous_db"] if ambiguous_db is None else ambiguous_db
    m_t = np.asarray(acoustic_margin(slant, modem, band, w, shipping, k), float)  # 0-d array: a numpy scalar takes no item assignment (round 9, M-25)
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
            margin[amb] = acoustic_margin(slant[amb], modem, band, w[amb], shipping, k, tl_extra=tl_b[amb] - tl_i[amb])
            method[amb] = "bellhop"
            label = "Bellhop refined the ambiguous links"
        else:
            method[amb] = "thorp-only (bellhop unavailable)" if ssp is not None else "thorp-only (no sound-speed profile)"
            label = THORP_ONLY_LABEL if ssp is not None else "Thorp only, no sound-speed profile supplied"
    src = f"Thorp/Stojanovic budget {modem}/{band}" + (" + Bellhop" if label.startswith("Bellhop") else "")
    return dict(margin=Tagged(margin, src, None, "modelled"),
                thorp_margin=m_t, ambiguous=amb, method=method, label=label, tl_bellhop_db=tl_b, tl_bellhop_iso_db=tl_i)


# ---------------------------------------------------------------- receipts
# mutation: not mutated. A receipt generator is the audit instrument, not the model: make receipts and the broken-physics tests grade it, and
# its mutants are label, unit and source strings and widened tolerances, each costing a full receipt run.
def receipts() -> list[dict[str, Any]]:  # pragma: no mutate block
    """Run every comms receipt through cafe.receipts and return the entries it recorded."""
    from cafe import receipts as R
    n0, g = len(R.OUT), "Comms"

    def rc(claim: str, value: Any, ref: float, tol: float, unit: str, src: str, rel: bool = True) -> None:
        R.receipt(g, claim, float(value), ref, tol, unit, src, rel=rel)

    def br(claim: str, value: Any, lo: float, hi: float, unit: str, src: str) -> None:
        R.bracket(g, claim, float(value), lo, hi, unit, src)

    f, lam = 915e6, C0 / 915e6
    # two-ray: 4th-power law far out (-40 dB/decade, independent of frequency) and the last null at d = 2 ht hr / lam
    L = two_ray_loss_db(np.array([5e3, 5e4]), 2.0, 5.0, 0.0, f, a_eff=FLAT_A)   # the law is the plane-earth one: a 4/3 earth bends it off at the horizon
    rc("Two-ray far field: loss rise per decade of range", L[1] - L[0], 40.0, 0.05, "dB",
       "d^-4 law (Rappaport, Wireless Communications 2e, sec 4.6), plane earth", rel=False)
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
