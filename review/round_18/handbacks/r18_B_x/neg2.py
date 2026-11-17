import math
import numpy as np
from cafe.pm.physics import comms as c

F = 915e6
a = c.A_EFF / 1e3
lam = c.C0 / F
hits = []
for ht in (0.3, 0.5, 2.2, 5.0, 10.0, 18.1, 30.0, 60.0, 108.1, 200.0):
    for hr in (0.3, 0.5, 2.2, 5.0, 10.0, 18.1, 30.0, 60.0, 108.1, 200.0):
        if hr < ht:
            continue
        dlos = math.sqrt(2 * a) * (math.sqrt(ht / 1e3) + math.sqrt(hr / 1e3))
        for fr in np.concatenate([np.geomspace(0.0005,0.02,30),np.linspace(0.02, 0.999, 200)]):
            d = fr * dlos
            cc = (ht - hr) / (ht + hr)
            m = 250.0 * d ** 2 / a / (ht + hr)
            b = 2 * math.sqrt((m + 1) / 3 / m) * math.cos(math.pi / 3 + math.acos(max(-1, min(1, 1.5 * cc * math.sqrt(3 * m / (m + 1) ** 3)))) / 3)
            d1 = 0.5 * d * (1 + b); d2 = d - d1
            hse = ((ht - 500 * d1 ** 2 / a) * d2 + (hr - 500 * d2 ** 2 / a) * d1) / d
            hreq = 17.456 * math.sqrt(d1 * d2 * lam / d)
            aem = 500.0 * (d / (math.sqrt(ht) + math.sqrt(hr))) ** 2
            raw = float(c._diffraction_beyond_db(aem, d, F / 1e6, ht, hr))
            if raw < 0:
                hits.append((ht, hr, fr, raw, 1 - hse / hreq))
print(len(hits))
print(sum(1 for h in hits if h[4]>0), 'with h_se<h_req'); print(max(hits,key=lambda h:h[4]) if hits else None)
for h in hits[:: max(1, len(hits) // 12)]:
    print(h)
