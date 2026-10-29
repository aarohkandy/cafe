"""COARE 3.5 bulk air-sea fluxes (vectorized), the wind profile below the first model level, and the diurnal warm layer.

Inputs are SI (K, Pa, kg/kg, m/s, W/m2, rain in mm/h); arrays broadcast against each other, so a leading axis M of
ensemble members costs nothing extra. Nothing here loops over members; `warm_layer` loops over time only (it is a
sequential accumulation).

Sources (every constant below comes from one of these):
- Fairall, Bradley, Rogers, Edson, Young 2003, J. Climate 16, 571 (COARE 3.0): bulk loop, gustiness (beta = 1.2),
  cool skin (Fairall et al. 1996 eqs. 12-17), thermal roughness (Liu-Katsaros-Businger via z0q = min(1.6e-4, 5.8e-5/Rr^0.72)).
- Edson, Jampana, Weller, Bigorre, Plueddemann, Fairall, Miller, Mahrt, Vickers, Hersbach 2013, J. Phys. Oceanogr. 43, 1589
  (COARE 3.5): Charnock alpha = m*U10n + b, m = 0.0017 s/m, b = -0.005, constant above 19 m/s (their eq. 13 region);
  wave-age form alpha = A (u*/cp)^B with A = 0.114, B = 0.622; sea-state form z0 = Ad Hs (u*/cp)^Bd with Ad = 0.091, Bd = 2.
- Beljaars & Holtslag 1991 (stable psi), Grachev, Fairall, Bates... 2000 (convective psi), Businger et al. 1971 (Kansas psi).
- Fairall, Bradley, Godfrey, Wick, Edson, Young 1996, J. Geophys. Res. 101, 1295: warm layer (Price-Weller-Pinkel 1986 bulk
  Richardson criterion Ri = 0.65, three-band solar absorption of Paulson & Simpson 1981 / Soloviev 1982), coded as in the
  NOAA PSL reference implementation (coare36vnWarm_et.py).
- Gosnell, Fairall, Webster 1995, J. Geophys. Res. 100, 18437: rain heat flux.
- Normal gravity: WGS84 Somigliana formula.

The paper wins over any code. Bulk and wave-age modes agree with pycoare 0.4.3 to round-off. In sea-state mode pycoare
0.4.3 passes a truthy object as `setup` in its in-loop `_get_charn` call, so it never subtracts 0.11 nu/u* from the sea-state
z0 (it returns Ad Hs (u*/cp)^2 + 0.11 nu/u*). We return z0 = Ad Hs (u*/cp)^2 as Edson 2013 writes the sea-state form (the NOAA
Matlab subtracts the smooth term too, from memory, not re-read), floored at the smooth-flow value 0.11 nu/u*; this differs
from pycoare by up to ~5 % in u* (10 % in Cd) on the test grid. Tests pin our z0 to the formula.
"""

from typing import Any

import numpy as np
from numpy.typing import ArrayLike, NDArray

Arr = NDArray[np.floating[Any]]
Num = Arr | float
VON, BETA, FDG, TDK = 0.4, 1.2, 1.0, 273.16
RGAS, CPA = 287.1, 1004.67
BE, CPW, RHOW, VISW, TCW = 0.026, 4000.0, 1022.0, 1.0e-6, 0.6
A_WAVE, B_WAVE, A_SS, B_SS = 0.114, 0.622, 0.091, 2.0
UMAX, CH1, CH2 = 19.0, 0.0017, -0.0050  # Charnock alpha = CH1*U10n + CH2, capped at U10n = UMAX


def grav(lat: ArrayLike) -> Arr:
    """WGS84 normal gravity [m/s2] at latitude `lat` [deg]."""
    s = np.sin(np.radians(lat)) ** 2
    return 9.7803253359 * (1 + 0.001931853 * s) / np.sqrt(1 - 0.00669437999013 * s)


def qsat(tc: Num, p: Num) -> Num:
    """Saturation vapour pressure [mb] at tc [degC], p [mb] (Buck 1981, with the 1.0007 + 3.46e-6 p enhancement)."""
    return 6.1121 * np.exp(17.502 * tc / (240.97 + tc)) * (1.0007 + p * 3.46e-6)


def qsea(tc: Num, p: Num) -> Num:
    """Saturation specific humidity [kg/kg] over sea water (salinity 35 lowers vapour pressure by 2 %)."""
    es = 0.98 * qsat(tc, p)
    return 0.622 * es / (p - 0.378 * es)


def qair(tc: Num, p: Num, rh: Num) -> Num:
    """Specific humidity [kg/kg] from relative humidity rh [0..1]."""
    em = rh * qsat(tc, p)
    return 0.62197 * em / (p - 0.378 * em)


def psit(z: ArrayLike) -> Arr:
    """Temperature/humidity stability function of zeta = z/L (BH91 stable, Grachev 2000 + Kansas unstable)."""
    z = np.asarray(z, float)
    zs, zu = np.maximum(z, 0.0), np.minimum(z, 0.0)
    stable = -((1 + 2 / 3 * zs) ** 1.5 + 0.6667 * (zs - 5 / 0.35) * np.exp(-np.minimum(50.0, 0.35 * zs)) + 0.6667 * 5 / 0.35 - 1)
    x = np.sqrt(1 - 15 * zu)
    y = (1 - 34.15 * zu) ** (1 / 3)
    psic = 1.5 * np.log((y * y + y + 1) / 3) - np.sqrt(3) * np.arctan((2 * y + 1) / np.sqrt(3)) + np.pi / np.sqrt(3)
    f = zu * zu / (1 + zu * zu)
    out: Arr = np.where(z >= 0, stable, (1 - f) * 2 * np.log((1 + x) / 2) + f * psic)
    return out


def _psiu(z: ArrayLike, a: float, c_k: float, c_c: float) -> Arr:
    z = np.asarray(z, float)
    zs, zu = np.maximum(z, 0.0), np.minimum(z, 0.0)
    stable = -(a * zs + 0.75 * (zs - 5 / 0.35) * np.exp(-np.minimum(50.0, 0.35 * zs)) + 0.75 * 5 / 0.35)
    x = (1 - c_k * zu) ** 0.25
    psik = 2 * np.log((1 + x) / 2) + np.log((1 + x * x) / 2) - 2 * np.arctan(x) + np.pi / 2
    y = (1 - c_c * zu) ** (1 / 3)
    psic = 1.5 * np.log((y * y + y + 1) / 3) - np.sqrt(3) * np.arctan((2 * y + 1) / np.sqrt(3)) + np.pi / np.sqrt(3)
    f = zu * zu / (1 + zu * zu)
    out: Arr = np.where(z >= 0, stable, (1 - f) * psik + f * psic)
    return out


def psiu(z: ArrayLike) -> Arr:
    """Wind stability function of zeta = z/L used in the COARE 3.5 bulk loop and profile (a = 0.7, 15, 10.15)."""
    return _psiu(z, 0.7, 15.0, 10.15)


def psiu_setup(z: ArrayLike) -> Arr:
    """The variant COARE 3.5 uses only for its first guess (a = 1, 18, 10)."""
    return _psiu(z, 1.0, 18.0, 10.0)


def coare35(
    u: ArrayLike,
    zu: ArrayLike,
    t: ArrayLike,
    zt: ArrayLike,
    q: ArrayLike,
    zq: ArrayLike,
    P: ArrayLike,
    ts: ArrayLike,
    Rs: ArrayLike,
    Rl: ArrayLike,
    lat: ArrayLike,
    zi: ArrayLike = 600.0,
    cp: ArrayLike | None = None,
    sigH: ArrayLike | None = None,
    rain: ArrayLike | None = None,
    jcool: int = 1,
    nits: int = 10,
) -> dict[str, Any]:
    """COARE 3.5 fluxes. `u` is the wind speed at zu RELATIVE to the surface current [m/s]; `t` air temperature [K] at zt;
    `q` air specific humidity [kg/kg] at zq; `P` surface pressure [Pa]; `ts` sea temperature [K] (bulk if jcool=1, skin if 0);
    `Rs`, `Rl` downward shortwave and longwave [W/m2]; `zi` boundary-layer height [m]; `cp` dominant phase speed [m/s] and
    `sigH` significant wave height [m] switch the roughness to wave-age (cp only) or sea-state (cp and sigH) form where finite;
    `rain` rain rate [mm/h] (only adds the rain heat flux `rf`).

    Returns a dict of arrays shaped like the broadcast inputs: ustar, tau [N/m2, stress on the sea], z0, z0t, z0q, L (Obukhov,
    negative = unstable), zeta (zu/L), Cd, Ch, Ce (at the measurement heights, relative to gust-inclusive speed), Cdn10,
    u10n, hsb, hlb (W/m2, positive = sea loses heat), rf (W/m2, rain heat flux), tsr, qsr, dter (cool-skin dT, K, skin = ts -
    dter), tkt, gf (gustiness factor, ut/du), ut, rhoa, lhvap and `zu` (needed by `profile`).
    """
    a = np.broadcast_arrays(*[np.asarray(v, float) for v in (u, zu, t, zt, q, zq, P, ts, Rs, Rl, lat, zi)])
    u, zu, t, zt, q, zq, P, ts, Rs, Rl, lat, zi = a
    shape = u.shape
    if cp is None:
        cp = np.full(shape, np.nan)
    if sigH is None:
        sigH = np.full(shape, np.nan)
    cp, sigH = np.broadcast_to(np.asarray(cp, float), shape), np.broadcast_to(np.asarray(sigH, float), shape)
    wave = np.isfinite(cp)
    sea = wave & np.isfinite(sigH)
    tc, tsc, pmb = t - 273.15, ts - 273.15, P / 100.0
    g = grav(lat)
    qs = qsea(tsc, pmb)
    lhvap = (2.501 - 0.00237 * tsc) * 1e6
    rhoa = pmb * 100.0 / (RGAS * (tc + TDK) * (1 + 0.61 * q))
    visa = 1.326e-5 * (1 + 6.542e-3 * tc + 8.301e-6 * tc**2 - 4.84e-9 * tc**3)
    al = 2.1e-5 * (tsc + 3.2) ** 0.79
    bigc = 16.0 * g * CPW * (RHOW * VISW) ** 3 / (TCW**2 * rhoa**2)
    wetc = 0.622 * lhvap * qs / (RGAS * (tsc + TDK) ** 2)
    rns = 0.945 * Rs
    rnl = 0.97 * (5.67e-8 * (tsc - 0.3 * jcool + TDK) ** 4 - Rl)

    du, dt, dq = u, tsc - tc - 0.0098 * zt, qs - q
    ta = tc + TDK

    def stars(ut: Arr, zo: Arr, zot: Arr, zoq: Arr, L: Arr, dter: Arr, setup: bool) -> tuple[Arr, Arr, Arr]:  # u*, T*, q* from the log-law with stability
        fu = psiu_setup(zu / L) if setup else psiu(zu / L)
        return (
            ut * VON / (np.log(zu / zo) - fu),
            -(dt - dter * jcool) * VON * FDG / (np.log(zt / zot) - psit(zt / L)),
            -(dq - wetc * dter * jcool) * VON * FDG / (np.log(zq / zoq) - psit(zq / L)),
        )

    # first guess (neutral roughness at 10 m, Ch10 = 1.15e-3) and the stable-limit flag
    dter = np.full(shape, 0.3)
    ut = np.sqrt(du**2 + 0.5**2)
    u10 = ut * np.log(10 / 1e-4) / np.log(zu / 1e-4)
    usr = 0.035 * u10
    zo10 = 0.011 * usr**2 / g + 0.11 * visa / usr
    cd10 = (VON / np.log(10 / zo10)) ** 2
    zot10 = 10 / np.exp(VON / (0.00115 / np.sqrt(cd10)))
    cd = (VON / np.log(zu / zo10)) ** 2
    ct = VON / np.log(zt / zot10)
    cc = VON * ct / cd
    ribcu = -zu / zi / 0.004 / BETA**3
    ribu = -g * zu / ta * ((dt - dter * jcool) + 0.61 * ta * dq) / ut**2
    zetu = np.where(ribu < 0, cc * ribu / (1 + ribu / ribcu), cc * ribu * (1 + 27 / 9 * ribu / cc))
    k50 = zetu > 50
    usr, tsr, qsr = stars(ut, zo10, zot10, zot10, zu / zetu, dter, True)
    tkt = np.full(shape, 0.001)

    def charnock(uu: Arr, ustar: Arr, first: bool) -> Arr:
        cC = np.where(uu > UMAX, CH1 * UMAX + CH2, CH1 * uu + CH2)
        with np.errstate(all="ignore"):
            cW = A_WAVE * (ustar / cp) ** B_WAVE
            zoS = sigH * A_SS * (ustar / cp) ** B_SS - (0.0 if first else 0.11 * visa / ustar)
            cS = np.maximum(zoS, 0.0) * g / ustar**2  # sea-state z0 below the smooth-flow value: keep the smooth value
        return np.where(sea, cS, np.where(wave, cW, cC))

    charn = charnock(u10, usr, True)
    gf = ut / du
    first = None
    for i in range(nits):
        zet = VON * g * zu / ta * (tsr + 0.61 * ta * qsr) / usr**2
        L = zu / zet
        zo = charn * usr**2 / g + 0.11 * visa / usr
        rr = zo * usr / visa
        zoq = np.minimum(1.6e-4, 5.8e-5 / rr**0.72)
        zot = zoq
        usr, tsr, qsr = stars(ut, zo, zot, zoq, L, dter, False)
        tvsr = tsr + 0.61 * ta * qsr
        bf = -g / ta * usr * tvsr
        ug = np.where(bf > 0, BETA * np.abs(bf * zi) ** (1 / 3), 0.2)
        ut = np.sqrt(du**2 + ug**2)
        gf = np.where(du != 0, ut / np.where(du != 0, du, 1.0), np.inf)
        hsb = -rhoa * CPA * usr * tsr
        hlb = -rhoa * lhvap * usr * qsr
        qcol = rnl + hsb + hlb - rns * (0.065 + 11 * tkt - 6.6e-5 / tkt * (1 - np.exp(-tkt / 8.0e-4)))
        alq = al * qcol + BE * hlb * CPW / lhvap
        xlam = np.where(alq > 0, 6 / (1 + (bigc * np.abs(alq) / usr**4) ** 0.75) ** 0.333, 6.0)
        tkt = np.where(
            alq > 0, xlam * VISW / (np.sqrt(rhoa / RHOW) * usr), np.minimum(0.01, xlam * VISW / (np.sqrt(rhoa / RHOW) * usr))
        )
        dter = qcol * tkt / TCW
        rnl = 0.97 * (5.67e-8 * (tsc - dter * jcool + TDK) ** 4 - Rl)
        if i == 0:
            first = (usr, tsr, qsr, L, zet, dter, tkt)
        charn = charnock(usr / VON / gf * np.log(10 / zo), usr, False)
    assert first is not None
    usr, tsr, qsr, L, zet, dter, tkt = (
        np.where(k50, f, c) for f, c in zip(first, (usr, tsr, qsr, L, zet, dter, tkt), strict=True)
    )
    hsb, hlb = -rhoa * CPA * usr * tsr, -rhoa * lhvap * usr * qsr
    tau = rhoa * usr**2 / gf
    dqer = wetc * dter
    if rain is None:
        rf = np.zeros(shape)
    else:  # Gosnell et al. 1995 rain heat flux, W/m2
        rain = np.broadcast_to(np.asarray(rain, float), shape)
        dwat = 2.11e-5 * ((tc + TDK) / TDK) ** 1.94
        dtmp = (1 + 3.309e-3 * tc - 1.44e-6 * tc**2) * 0.02411 / (rhoa * CPA)
        dqs_dt = q * lhvap / (RGAS * (tc + TDK) ** 2)
        alfac = 1 / (1 + 0.622 * (dqs_dt * lhvap * dwat) / (CPA * dtmp))
        rf = rain * alfac * CPW * ((tsc - tc - dter * jcool) + (qs - q - dqer * jcool) * lhvap / CPA) / 3600
    zo = charn * usr**2 / g + 0.11 * visa / usr
    rr = zo * usr / visa
    zoq = np.minimum(1.6e-4, 5.8e-5 / rr**0.72)
    with np.errstate(invalid="ignore", divide="ignore"):  # Ch, Ce are 0/0 when there is no T or q difference
        ch = -usr * tsr / ut / (dt - dter * jcool)
        ce = -usr * qsr / (dq - dqer * jcool) / ut
    return dict(
        ustar=usr,
        tau=tau,
        z0=zo,
        z0t=zoq,
        z0q=zoq,
        L=L,
        zeta=zu / L,
        tsr=tsr,
        qsr=qsr,
        hsb=hsb,
        hlb=hlb,
        rf=rf,
        dter=dter,
        tkt=tkt,
        gf=gf,
        ut=ut,
        rhoa=rhoa,
        lhvap=lhvap,
        zu=zu,
        Cd=tau / rhoa / ut / np.maximum(0.1, du),
        Ch=ch,
        Ce=ce,
        Cdn10=(VON / np.log(10 / zo)) ** 2,
        u10n=usr / VON / gf * np.log(10 / zo),
    )


def profile(res: dict[str, Any], z: ArrayLike) -> Arr:
    """Mean wind speed relative to the surface current at height z [m] (broadcast against the arrays in `res`; add an axis
    to z to get a profile per member): U(z) = u*/(kappa gf) [ln(z/z0) - psi_u(z/L)], 0 at and below z0.

    gf converts the gust-inclusive speed COARE solves for back to the mean (vector-averaged) wind, as pycoare's u_rf does.
    Used to get wind at 0.5-100 m from the 10 m value; above the surface layer (z >~ 0.1 zi) it overestimates stable shear.
    """
    z = np.asarray(z, float)
    zz = np.maximum(z, res["z0"])
    with np.errstate(divide="ignore", invalid="ignore"):
        out: Arr = np.maximum(
            res["ustar"] / (VON * res["gf"]) * (np.log(zz / res["z0"]) - (psiu(zz / res["L"]) - psiu(res["z0"] / res["L"]))), 0.0
        )
    return out


def warm_layer(
    t: ArrayLike,
    swdown: ArrayLike,
    u: ArrayLike,
    tair: ArrayLike,
    q: ArrayLike,
    P: ArrayLike,
    sst: ArrayLike,
    glw: ArrayLike,
    lat: ArrayLike,
    lon: ArrayLike,
    zu: float = 10.0,
    zt: float = 2.0,
    zq: float = 2.0,
    zi: float = 600.0,
    rain: ArrayLike | None = None,
    sst_depth: float | None = None,
    max_depth: float = 19.0,
    ri_c: float = 0.65,
) -> dict[str, Arr]:
    """Diurnal warm layer (Fairall et al. 1996) and cool skin over a series; time is the LAST axis, everything else broadcasts.

    t [s since epoch, increasing, shape (T,)], swdown/glw [W/m2], u [m/s, wind relative to the current at zu], tair [K] at zt,
    q [kg/kg] at zq, P [Pa], sst [K] = the temperature BELOW the warm layer (WRF's frozen SST is a foundation value; if the
    SST you hold is measured at `sst_depth` m inside the layer pass that depth), lat/lon degrees. The accumulators reset at
    local mean solar midnight (lon/15 h from UTC) and start accumulating once the net warm-layer heating first exceeds
    50 W/m2 (NOAA reference code). A series starting after dawn under-warms its first partial day by construction.

    Returns dT_warm [K, surface minus foundation across the layer], dz_warm [m], dT_cool [K, skin cooler than the bulk
    by this], sst_skin [K], plus ustar, tau, hsb, hlb for the same steps, shaped (..., T).
    """
    t = np.asarray(t, float)
    nt = t.size
    sw, uu, ta, qq, pp, tsea, lw = np.broadcast_arrays(*[np.asarray(v, float) for v in (swdown, u, tair, q, P, sst, glw)])
    full = sw.shape
    if full[-1] != nt:
        raise ValueError(f"time must be the last axis: got {full} for {nt} times")
    lead = full[:-1]
    lat, lon = np.broadcast_to(np.asarray(lat, float), lead), np.broadcast_to(np.asarray(lon, float), lead)
    rn = None if rain is None else np.broadcast_to(np.asarray(rain, float), full)
    out: dict[str, Arr] = {k: np.zeros(full) for k in ("dT_warm", "dz_warm", "dT_cool", "sst_skin", "ustar", "tau", "hsb", "hlb")}
    tau_ac = np.zeros(lead)
    qcol_ac = np.zeros(lead)
    dz = np.full(lead, max_depth)
    fxp = np.full(lead, 0.5)
    dtw = np.zeros(lead)
    jam = np.zeros(lead, bool)
    hours = np.mod(t / 3600.0 + lon[..., None] / 15.0, 24.0)
    ds = np.inf if sst_depth is None else sst_depth

    def call(k: int, ts: Arr) -> dict[str, Any]:
        return coare35(
            uu[..., k],
            zu,
            ta[..., k],
            zt,
            qq[..., k],
            zq,
            pp[..., k],
            ts,
            sw[..., k],
            lw[..., k],
            lat,
            zi,
            rain=None if rn is None else rn[..., k],
        )

    r = call(0, tsea[..., 0])
    skin_prev = r["dter"]
    for k in range(nt):
        if k:
            dtime = t[k] - t[k - 1]
            reset = hours[..., k] < hours[..., k - 1]
            tau_ac, qcol_ac, dz, fxp, dtw, jam = (
                np.where(reset, v0, v)
                for v0, v in ((0.0, tau_ac), (0.0, qcol_ac), (max_depth, dz), (0.5, fxp), (0.0, dtw), (False, jam))
            )
            tsc = tsea[..., k] - 273.15
            al = 2.1e-5 * (tsc + 3.2) ** 0.79
            ctd1 = np.sqrt(2 * ri_c * CPW / (al * grav(lat) * RHOW))
            ctd2 = np.sqrt(2 * al * grav(lat) / (ri_c * RHOW)) / CPW**1.5
            sw_net = 0.945 * sw[..., k]
            lw_net = 0.97 * (5.67e-8 * (tsc - skin_prev + TDK) ** 4 - lw[..., k])
            qr_out = lw_net + r["hsb"] + r["hlb"] + r["rf"]
            q_pwp = fxp * sw_net - qr_out
            act = (q_pwp >= 50) | jam
            jam = act
            tau_new = tau_ac + np.maximum(0.002, r["tau"]) * dtime
            heat = qcol_ac + q_pwp * dtime > 0
            d, f = dz, fxp
            for _ in range(5):
                f = (
                    1
                    - (
                        0.28 * 0.014 * (1 - np.exp(-d / 0.014))
                        + 0.27 * 0.357 * (1 - np.exp(-d / 0.357))
                        + 0.45 * 12.82 * (1 - np.exp(-d / 12.82))
                    )
                    / d
                )
                qj = (f * sw_net - qr_out) * dtime
                ok = qcol_ac + qj > 0
                d = np.where(ok, np.minimum(max_depth, ctd1 * tau_new / np.sqrt(np.where(ok, qcol_ac + qj, 1.0))), d)
            f_n = np.where(heat, f, 0.75)
            d_n = np.where(heat, d, max_depth)
            qj_n = (f_n * sw_net - qr_out) * dtime
            qcol_n = qcol_ac + qj_n
            dtw_n = np.where(qcol_n > 0, ctd2 * np.abs(qcol_n) ** 1.5 / tau_new, 0.0)
            tau_ac, qcol_ac, dz, fxp, dtw = (
                np.where(act, a, b) for a, b in ((tau_new, tau_ac), (qcol_n, qcol_ac), (d_n, dz), (f_n, fxp), (dtw_n, dtw))
            )
        to_skin = np.where(dz < ds, dtw, dtw * ds / dz) if np.isfinite(ds) else dtw
        r = call(k, tsea[..., k] + to_skin)
        skin_prev = r["dter"]
        out["dT_warm"][..., k], out["dz_warm"][..., k], out["dT_cool"][..., k] = dtw, dz, r["dter"]
        out["sst_skin"][..., k] = tsea[..., k] + to_skin - r["dter"]
        for n in ("ustar", "tau", "hsb", "hlb"):
            out[n][..., k] = r[n]
    return out


def _diurnal_forcing(hours: Arr, peak: float = 1000.0) -> Arr:
    """Clear-sky-ish tropical SW day: peak * sin(pi (h-6)/12) between 06 and 18 local, 0 at night."""
    return np.maximum(0.0, peak * np.sin(np.pi * (hours - 6.0) / 12.0))


def receipts() -> list[dict[str, Any]]:
    """Published-reference checks for this module; returns the receipt records it appended (each can fail)."""
    from cafe import receipts as R
    from pycoare import coare_35

    n0 = len(R.OUT)
    g = "COARE 3.5"
    # neutral drag: closure of Edson 2013 (Charnock alpha = 0.0017 U10N - 0.005, z0 = alpha u*^2/g + 0.11 nu/u*, log law),
    # solved independently of the bulk loop with a root finder; classical open-ocean fits shown for orientation
    from scipy.optimize import brentq

    for uref in (5.0, 10.0, 15.0):

        def f(us: float, uref: float = uref) -> float:
            z0 = (CH1 * min(uref, UMAX) + CH2) * us**2 / 9.81 + 0.11 * 1.5e-5 / us
            return float(us - VON * uref / np.log(10 / z0))

        cd_ref = (brentq(f, 0.01, 3.0) / uref) ** 2
        ts = 300.0
        r = coare35(uref, 10, ts - 0.0098 * 10, 10, qsea(ts - 273.15, 1010.0), 10, 101000.0, ts, 0.0, 0.0, 0.0, jcool=0)
        R.receipt(
            g,
            f"C_D10N at U10N = {uref:g} m/s (Edson 2013 closure)",
            float(r["Cdn10"]),
            cd_ref,
            0.03,
            "-",
            "Edson et al. 2013 alpha(U10N)",
        )
        lp = 1.14e-3 if uref <= 10 else (0.49 + 0.065 * uref) * 1e-3
        R.context(
            g,
            f"C_D10N at U10N = {uref:g} m/s vs Large & Pond 1981",
            float(r["Cdn10"]),
            lp,
            "-",
            "Large & Pond 1981 (not a pass criterion)",
        )
    # profile reproduces the log law in neutral conditions: U(100)/U(10) = ln(100/z0)/ln(10/z0)
    ts = 300.0
    r = coare35(8.0, 10, ts - 0.098, 10, qsea(ts - 273.15, 1010.0), 10, 101000.0, ts, 0.0, 0.0, 0.0, jcool=0)
    ratio = float(profile(r, 100.0) / profile(r, 10.0))
    R.receipt(
        g,
        "neutral U(100 m)/U(10 m) vs log law",
        ratio,
        float(np.log(100 / r["z0"]) / np.log(10 / r["z0"])),
        0.01,
        "-",
        "log law, Monin-Obukhov",
    )
    # state agreement with pycoare on a grid
    g3 = np.meshgrid([2.0, 5.0, 10.0, 18.0], [-3.0, -0.5, 1.0, 3.0], [0.6, 0.85])
    uu, dT, rh = (a.ravel() for a in g3)
    tc = 27.0 + dT * 0
    tsc = tc + dT
    p = 1010.0
    cpv = np.where(uu > 4, 8.0, 0.0) + 10.0
    qa = qair(tc, p, rh)
    for tag, kw, tol in (("bulk", {}, 0.005), ("wave-age", dict(cp=cpv), 0.005), ("sea-state", dict(cp=cpv, sigH=2.0), None)):
        ref = coare_35(
            uu,
            t=tc,
            rh=rh * 100,
            zu=10.0,
            zt=2.0,
            zq=2.0,
            ts=tsc,
            p=p,
            lat=0.0,
            zi=600.0,
            rs=400.0,
            rl=420.0,
            **{k: (np.full(uu.shape, v) if k == "sigH" else v) for k, v in kw.items()},
        )
        mine = coare35(uu, 10.0, tc + 273.15, 2.0, qa, 2.0, p * 100, tsc + 273.15, 400.0, 420.0, 0.0, 600.0, **kw)
        for name, a, b in (
            ("u*", mine["ustar"], ref.velocities.usr),
            ("sensible", mine["hsb"], ref.fluxes.hsb),
            ("latent", mine["hlb"], ref.fluxes.hlb),
            ("Cd", mine["Cd"], ref.transfer_coefficients.cd),
        ):
            e = float(np.max(np.abs(a / b - 1)))
            if tol is None:  # pycoare omits the -0.11 nu/u* term of the sea-state z0 inside its loop (see module docstring)
                R.context(
                    g,
                    f"max relative difference to pycoare 0.4.3, {tag} roughness: {name}",
                    e,
                    0.0,
                    "-",
                    "pycoare quirk, not a pass criterion",
                )
            else:
                R.bracket(
                    g,
                    f"max relative difference to pycoare 0.4.3, {tag} roughness, {uu.size} states: {name}",
                    e,
                    0.0,
                    tol,
                    "-",
                    "pycoare 0.4.3 (state agreement)",
                )
    r = coare35(10.0, 10.0, 300.0, 2.0, 0.017, 2.0, 101000.0, 301.0, 400.0, 420.0, 0.0, 600.0, cp=12.0, sigH=2.0)
    R.receipt(
        g,
        "sea-state z0 = Ad Hs (u*/cp)^2",
        float(r["z0"]),
        float(A_SS * 2.0 * (r["ustar"] / 12.0) ** B_SS),
        0.01,
        "m",
        "Edson et al. 2013 sea-state form",
    )
    # warm layer
    t = np.arange(0, 3 * 86400, 3600.0)
    hours = np.mod(t / 3600.0, 24.0)
    sw = _diurnal_forcing(hours)
    for wind, lo, hi, tag in ((2.0, 0.3, 3.5, "calm sunny day (U = 2 m/s)"), (10.0, 0.0, 0.1, "windy day (U = 10 m/s)")):
        w = warm_layer(
            t,
            sw,
            np.full(t.size, wind),
            np.full(t.size, 300.0),
            np.full(t.size, 0.017),
            np.full(t.size, 101000.0),
            np.full(t.size, 302.0),
            np.full(t.size, 420.0),
            0.0,
            0.0,
        )
        R.bracket(
            g,
            f"peak warm-layer dT, {tag}",
            float(w["dT_warm"][-24:].max()),
            lo,
            hi,
            "K",
            "Fairall et al. 1996; Webster et al. 1996 (0.5-3 K calm, ~0 windy)",
        )
    return R.OUT[n0:]
