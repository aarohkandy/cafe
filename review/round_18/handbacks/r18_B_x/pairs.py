"""Model minus flat-earth Fresnel two-ray (sea eps 72.8 - j118.9, vertical, 915 MHz, Hs 0), by antenna pair; 400 points from d0 to the radio horizon."""
import numpy as np
from cafe.pm.physics import comms as c

F = 915e6


def fresnel(d, ht, hr, eps_r=72.8, sigma=6.05):
    lam = c.C0 / F
    eps = eps_r - 1j * 60.0 * sigma * lam
    r1, r2 = np.hypot(d, ht - hr), np.hypot(d, ht + hr)
    psi = np.arctan2(ht + hr, d)
    root = np.sqrt(eps - np.cos(psi) ** 2)
    refl = (eps * np.sin(psi) - root) / (eps * np.sin(psi) + root)
    field = np.abs(1.0 + refl * (r1 / r2) * np.exp(-2j * np.pi * (r2 - r1) / lam))
    return 20 * np.log10(4 * np.pi * r1 / lam) - 20 * np.log10(field)


PAIRS = [(0.5, 0.3), (0.3, 0.3), (0.5, 0.5), (0.3, 2.2), (0.5, 2.2), (2.2, 2.2), (0.1, 0.1), (0.1, 2.2), (0.3, 15.0), (0.5, 15.0), (2.2, 15.0), (0.1, 15.0)]
for ht, hr in PAIRS:
    hz = float(c.radio_horizon_km(ht, hr)) * 1e3
    for d0, d1 in ((200.0, min(hz, 12e3)), (300.0, 12e3)):
        if d1 == 12e3 and hz < 12e3:
            continue
        if d1 <= d0 * 1.5:
            continue
        d = np.linspace(d0, d1, 400)
        diff = c.two_ray_loss_db(d, ht, hr, 0.0, F) - fresnel(d, ht, hr)
        print(f"{ht:4g}/{hr:<5g} d {d0:6.0f}..{d1:6.0f} m (horizon {hz:7.0f}): min {diff.min():+7.3f} med {np.median(diff):+7.3f} max {diff.max():+7.3f}")
