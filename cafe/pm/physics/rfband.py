"""The error band of the RF link model's -1 ground reflection, computed for the pair of antenna heights of the link itself (round 21, M-2).

`comms.two_ray_loss_db` takes the reflection coefficient as -1. Its departure from a flat-earth two-ray with the Fresnel coefficient of vertical polarisation
over sea water (eps_c = 72.8 - j 60 sigma lambda, sigma 6.05 S/m: the sea of `comms.two_ray_curved_db`'s note, ASSUMED) is a continuous function of the two
heights: there is no height at which it starts or stops. Rounds 17 to 20 printed it from a table of measured rows and the card went silent at the edge of the
table four times (0.5, 0.55, 2.2 m, then every UAS link); the card now computes the band of the link's own pair, here, for any heights.

The definition is that of `comms.LOW_ANTENNA_PAIR_BAND` and of tests/test_round18_b.py: Hs 0, 400 points from 300 m to the pair's radio horizon or 12 km (the
nearer), the model's loss minus the Fresnel loss. Positive: the loss is overstated and the margin too low; negative: understated and the margin too high.
It is a difference from a two-ray with no surface wave, at Hs 0 and not nearer than 300 m. The Fresnel two-ray is written again here from the published
formulas, as tests/test_round17_d.py writes it, and tests/test_round21_b.py compares the two to 1e-9 dB.
Round 22, M-1: the minimum and the maximum of the 400 samples are sampling-limited (a finer sampling finds interference nulls and, for most pairs, larger
differences), so they are returned and never printed; the median and the two signed counts are what the card and L23
print (tests/test_round22_b.py holds them to a 40,000-point sampling).
"""
import numpy as np

from . import ANTENNA_MIN_M, comms

D_MIN_M = 300.0                      # the nearest distance of the band; nearer is not stated
D_MAX_M = 12e3                       # the farthest, where the pair's radio horizon is beyond it
N_POINTS = 400                       # samples between the two
OFF_DB = 3.0                         # "off" in `pair_band`'s share: the model differs from the Fresnel two-ray by more than this
MIN_HEIGHT_M = ANTENNA_MIN_M         # the least a platform file allows (0.1 m)
MAX_HEIGHT_M = 1000.0                # above every height the loaders allow (a UAS leg above 400 m with the deck, a ship mast above 100 m): no band beyond it
F_DEFAULT_HZ = 915e6                 # the RFD900x
EPS_R, SIGMA_SM = 72.8, 6.05         # sea water, T 29 C, S 35 (the note of `comms.two_ray_curved_db`): ASSUMED, not measured by this lab


def fresnel_loss_db(d: np.ndarray, ht: float, hr: float, f_hz: float = F_DEFAULT_HZ) -> np.ndarray:
    """Flat-earth two-ray loss [dB] at ground range d [m] with the Fresnel coefficient of vertical polarisation over sea water:
    field = |1 + R (r1 / r2) exp(-j k (r2 - r1))|, R = (eps_c sin(psi) - sqrt(eps_c - cos^2 psi)) / (eps_c sin(psi) + sqrt(eps_c - cos^2 psi))."""
    lam = comms.C0 / f_hz
    eps = EPS_R - 1j * 60.0 * SIGMA_SM * lam
    r1, r2 = np.hypot(d, ht - hr), np.hypot(d, ht + hr)
    psi = np.arctan2(ht + hr, d)
    root = np.sqrt(eps - np.cos(psi) ** 2)
    refl = (eps * np.sin(psi) - root) / (eps * np.sin(psi) + root)
    field = np.abs(1.0 + refl * (r1 / r2) * np.exp(-2j * np.pi * (r2 - r1) / lam))
    return np.asarray(20.0 * np.log10(4.0 * np.pi * r1 / lam) - 20.0 * np.log10(field))


def valid_height(h: object) -> bool:
    """A height this band is defined for: a real number from `physics.ANTENNA_MIN_M` (0.1 m, the least a platform file allows: below it the pair's radio
    horizon can be nearer than 300 m and there is no range to measure over) to `MAX_HEIGHT_M`. Not a bool, NaN or infinity; an integer too large for a
    float is not a height either."""
    try:
        return isinstance(h, (int, float)) and not isinstance(h, bool) and MIN_HEIGHT_M <= float(h) <= MAX_HEIGHT_M
    except OverflowError:
        return False


def pair_band(h1: float, h2: float, f_hz: float = F_DEFAULT_HZ) -> tuple[float, float, float, float, int, int]:
    """(minimum, median, maximum [dB] of the model's loss minus the Fresnel loss, the share of the `N_POINTS` samples more than `OFF_DB` off, the number of
    samples more than `OFF_DB` over (the loss overstated: the margin too low there), the number more than `OFF_DB` under (the margin too high there)) for
    antennas at heights h1 and h2 [m] above the sea, whichever is higher, at Hs 0 over `D_MIN_M` to the pair's radio horizon or `D_MAX_M`. Both counts are
    strict (a sample at exactly `OFF_DB` is in neither). A height that is not `valid_height`, or a band that is not finite, is a ValueError: the caller says
    that no band is stated."""
    if not (valid_height(h1) and valid_height(h2) and 0.0 < f_hz < np.inf):
        raise ValueError(f"rfband.pair_band: heights {h1!r} and {h2!r} m must be from {MIN_HEIGHT_M:g} to {MAX_HEIGHT_M:g} m, "
                         f"and the frequency {f_hz!r} Hz finite and above 0")
    low, high = sorted((float(h1), float(h2)))
    d = np.linspace(D_MIN_M, min(float(comms.radio_horizon_km(low, high)) * 1e3, D_MAX_M), N_POINTS)
    diff = comms.two_ray_loss_db(d, low, high, 0.0, f_hz) - fresnel_loss_db(d, low, high, f_hz)
    if not np.isfinite(diff).all():
        raise ValueError(f"rfband.pair_band: the band of {low:g} m with {high:g} m is not finite")
    over, under = int(np.sum(diff > OFF_DB)), int(np.sum(diff < -OFF_DB))
    return float(diff.min()), float(np.median(diff)), float(diff.max()), (over + under) / N_POINTS, over, under
