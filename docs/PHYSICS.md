# PHYSICS — the model reference for cafe/pm

For a scientist who has to decide whether to trust a number or to challenge it. Written against the code of branch
`premission-step4` at commit `bb68642`, 2026-10-29. Where this file and the code disagree, the code is right; say so in a review.

How to read it. Each component lists the equations as implemented, the paper, the file and function, the conventions,
the inputs and where they come from, the uncertainty and how it travels, and the receipt that checks it. A receipt is
named as `python -m cafe.pm receipts` prints it: a job (`pm.env.coare`), a group (`COARE 3.5`) and a claim; a row's
name is `group: claim`. A claim quoted here is verbatim, or ends in `...` when shortened. A context row is shown for
orientation and never counts as a pass.

Certainty markers carry over from the code and are never upgraded here:

| Marker | Meaning |
|---|---|
| **assumed** | no source; the number is ours. Listed in `config/assumptions.yaml`, `config/perturbations.yaml` (kind `assumed`) or a platform yaml (`assumed: true`), which `cafe/pm/credibility.py` lists in the credibility report, **except where this file says "code default"**. |
| **recalled, not re-read** | written from memory of a paper or datasheet; the source was not opened for this build. |
| **not re-read** | the source was cited from a summary, an abstract or a search result. |
| **closure** | the receipt reproduces the formula the code uses; it cannot disagree with it. |
| **fit** | a number was tuned until a published value came out; the receipt is a calibration, not a validation. |

Contents: 0 conventions, 1 ingest, 2 WRF wind profile, 3 COARE and warm layer, 4 waves, 5 sub-grid, 6 ocean,
7 TAO validation and fitted priors, 8 perturbations, 9 glider, 10 USV, 11 UAS, 12 comms, 13 statistics, 14 stage 3.

---

## 0. Conventions (every module)

Source: `cafe/pm/__init__.py`, `cafe/pm/env/conventions.py`. Tests: `tests/test_conventions.py`.

| Item | Rule |
|---|---|
| Units | SI. Time is float seconds since 1970-01-01 UTC. |
| Horizontal vectors | `(east, north)` in the last axis, never speed plus direction. Vertical: `(east, north, up)`. |
| Direction scalars | degrees clockwise from north, named `*_from` (wind, meteorological) or `*_to` (waves, currents, headings, vehicle tracks). |
| z | metres, positive up, 0 at mean sea level. Depths are positive numbers named `depth`. The ocean store keeps depth positive down; the protocol converts (`ocean.py`: `-z`). |
| Longitude | taken modulo 360 inside the code (the TEPEX-C box crosses 180); bounds are reported in [-180, 180). |
| Provenance | every environment value is a `Tagged(value, source, uncertainty, kind)`, `kind` in `data`, `modelled`, `assumed`. `uncertainty` is a 1-sigma. |
| Platform leaves | a number the models divide by, take a log of or exponentiate has a range checked at load (`physics.check_params` kinds `nonzero`, `ge1`, `angle90`, `<kind><=max`, `range:lo:hi` and `int:lo:hi`; the limit is in the loader's message; round 8, L1: every angle, the glider and UAS masses, the cell count and the USV sizes and loads carry one), by `hangar` and `validate` too (review round 6, M-10). |

Angle conversions, the only place angles become vectors (`conventions.py`):

```
vec_from_to(s, to)     = s (sin to, cos to)                    to in compass degrees
vec_from_from(s, from) = vec_from_to(s, from + 180)
to_deg(v)              = atan2(v_east, v_north) mod 360        from_deg(v) = to_deg(v) + 180
UMWM theta, wdir, mwd, dwd: radians counter-clockwise from +x (east on this grid), direction the waves travel TOWARD
compass_to = 90 deg - theta_deg      (default, `umwm`)         theta = 90 deg - compass_to
compass_to = theta_deg + 180         (`compass_from`: WW3 and buoys, radians clockwise from north, FROM)
grid -> earth (wrf-python uvmet):  u_e = u cos(a) - v sin(a),  v_n = v cos(a) + u sin(a),   a from COSALPHA, SINALPHA
```

- COSALPHA = 1 and SINALPHA = 0 to float precision on this Mercator grid (BRIEF correction, §1.1). The rotation is applied to
  `U10`/`V10` (`GriddedEnv.u10`) and unit-tested with a quarter turn. The 3-D `U`, `V` are used **without** the rotation
  (`GriddedEnv._wind3d`): the identity here, wrong on a rotated grid.
- UMWM angles are interpolated through `(cos theta, sin theta)` and converted afterwards, so 350 and 10 degrees never average to 180.
- `waves.direction_convention` is read from the yaml named by `$CAFE_PM_OVERLAY`. `tests/fixtures/broken/wave_direction.yaml`
  gives UMWM data the WW3 convention on purpose; `python -m cafe.pm receipts --broken ...` must then fail a receipt that passes without it.

Receipts (job `pm.env.wave_direction`, groups `Wave direction (synthetic trade-wind fixture)` and, when a mission cache with
restart spectra exists under `$CAFE_DATA/cache`, `Wave direction (cache <mission>)`). The fixture is built from first
principles with plain `cos`/`sin`, no call into `conventions`, so the expected directions do not depend on the code under test.

| Claim (verbatim, shortened) | Bound | Why it can fail |
|---|---|---|
| median angle between the mean wave direction (UMWM mwd) and the WRF 10 m wind direction, wind > 3 m/s | 0 to 25 deg (bound is ours; the TEPEX-C cache gives 12 deg, per the code comment) | a TO/FROM or sign error gives tens to 180 deg |
| median angle between UMWM wdir ... read as UMWM angles, and the WRF 10 m wind direction | 0 to 0.5 deg | UMWM was forced with this wind |
| median direction error of the Stokes drift from the restart spectrum (pipeline) vs summing cos/sin of UMWM's own angles | 0 to 1 deg | |
| median speed of the Stokes drift from the restart spectrum (pipeline) / summed from UMWM's own k and dk | 1 +- 2 % | |
| median direction error of the Stokes drift from the parametric spectrum ... vs from the real restart spectrum | 0 to 30 deg (bound is ours, twice the 15 deg the cache gives; a wrong convention gives more than 100) | |
| context: median speed of the Stokes drift from the parametric spectrum / from the real restart spectrum | none | shows the size of the correction that `surface.build` applies (0.657 on the real cache, 2026-11-08: `review/round_12/m18/`) |

---

## 1. Ingest

Code: `cafe/pm/env/orca.py` (`ingest`, `wrf_hour`, `umwm_hour`, `spec_hour`, `assemble`), `remote.py` (`RemoteFile`, `cdf1_header`,
`cdf1_read`, `download`), `cafe/schemas/*.json`. Tests: `tests/test_orca.py`, `tests/test_remote.py`.

What is read. The UWIN-CM run `run_2023mar_waves_v4` on orca: `wrfout_d01_YYYY-MM-DD_HH:00:00` (HDF5, 12 km Mercator, WRF 4.7.1),
`output/umwmout_*.nc` (NetCDF classic, UMWM), `restart/umwmrst_*.nc` (00/06/12/18 Z only). Directory listing is 403, so names are
built from the hour. Only the mission box plus `pad_deg` (2 deg in the demo) and one cell on each side is read, by HTTP byte range. The hours read are the whole hours that cover the window, from the floor of the start to the ceiling of the end (a start at 12:30 reads the 12:00 file and labels it 12:00; review round 7, M-17), and when one part fails the queued parts are cancelled and the finished ones kept (M-31).

| Product | Variables | Notes |
|---|---|---|
| `wrf.zarr` | `U10 V10 T2 Q2 PSFC SST TSK HFX LH QFX RAINNC RAINC SWDOWN GLW UST PBLH`, static `XLAT XLONG LANDMASK HGT COSALPHA SINALPHA` | `SST` is frozen at the 1 March field (`SST_UPDATE = 0`); it is not a diurnal SST. |
| `wrf3d.zarr` | `U3 V3 Z3 TH3` on the 8 lowest mass levels (about 21 to 400 m) | only for the hours a UAS flies (`hours3d`). `U3`, `V3` destaggered by averaging the two faces; `Z3 = (PH+PHB)/g` averaged over the two w-levels; `TH3 = T + 300`. |
| `umwm.zarr` | `swh mwp mwd dwp dwd mss wspd wdir ust cd dcp dcg mwl dwl`, static `seamask depth` | `seamask = 0` is land; the file's integrated fields are NaN there and `GriddedEnv` masks them with `seamask` (no data, not zero); `depth` is 0 on land. |
| `umwmspec.zarr` | `F(time, point, th, f)` [m^4 rad^-1], `k(time, point, f)` | every 6 h; every 3rd sea point in each direction (36 km, `SPEC_STRIDE = 3`); `x` is the outermost dimension of the file so each box row is one byte range. |

Formulas.

```
rain rate of one interval [mm/h] = max( d(RAINNC + RAINC)/dt over the actual time step, 0 ) x 3600;   stored at node k: 0.5 ( r(k-1,k) + r(k,k+1) )   (GriddedEnv, review round 4, M-16)
UMWM:  swh = 4 sqrt( sum F k dk dtheta ),   mss = sum F k^3 dk dtheta,   dk = k dln(k) per log-f bin     (umwm_domain_output.f90)
```

The rain rate at an hourly node is the mean of the rates of the two intervals the node joins, the first and last node taking the one interval they touch; linear interpolation between nodes then integrates to the accumulation and centres an hour of rain on that hour (review round 4, M-16, DECISIONS 252). The earlier backward difference, stored at the end of its hour and interpolated linearly, put the rain half an hour late and spread it over twice the time. One hour of X mm/h now reads X/2 at its two end nodes, so it spreads over three hours at half the rate: a one-hour event is not made narrower than the hourly data can show.

Checks at the door. Every variable's dimensions, dtype, units and shape, and the WRF global attributes (`MAP_PROJ`, `CEN_LAT`, `DX`,
`SST_UPDATE`, ...) are compared with `cafe/schemas/{wrfout,umwmout,umwmrst}.json`, written from one real file; a mismatch refuses the
file. WRF `Times` must equal the requested hour. TLS verification stays on; `config/certs/incommon_rsa_server_ca2.pem` supplies the
intermediate certificate orca fails to send. A server that ignores `Range` is refused (reads must be 206); a cut body is retried 3 times.

Inputs: the files above. Uncertainty: none attached at this layer; the Tagged values built on top carry the sigmas in sections 7 and 8.

Receipts: no registered receipt reads orca. The weighting of UMWM's `F` is checked on synthetic spectra by `pm.env.waves`, group `Waves`,
claim `hs_from_restart of the equivalent UMWM F (Hs 2.0) vs target` (and Hs 1.5, 3.5), tolerance 1 %, against the formula above
(`_restart_from_E` inverts `spectrum_from_restart` with the analytic `dk = 2 k dlnf`, so the two share no code). A one-off comparison on
the real cache, 4620 points x 4 times, gave a maximum error of 0.09 % (lead's log); it is not re-run by `receipts`.

---

## 2. WRF wind profile (COARE below 21 m, log-linear above)

Code: `cafe/pm/env/environment.py` (`GriddedEnv.wind`, `_wind3d`), `surface.py` (`SurfaceLayer.profile_ratio`), `coare.py` (`profile`).
Tests: `tests/test_environment.py`, `tests/test_surface.py`.

```
default (every height, every hour):   U(z) = U10_WRF x  P(z) / P(10 m),    P = COARE profile of section 3
sortie hours, z above the lowest stored mass level z_1 (about 21 m):
    U(z) = U_j + a (U_{j+1} - U_j),   a = ( ln z - ln z_j ) / ( ln z_{j+1} - ln z_j ),  clipped to [0, 1]   (per component, east and north)
    heights z_j interpolated bilinearly to the point; time: linear between the hourly files
below z_1:  the COARE profile.   above the top stored level (about 400 m):  not used (NaN, so the COARE profile answers and the point is not counted as 3-D); missions may not ask for it (review round 4, M-15).
```

- Direction at height follows the WRF components (log-linear on each component), so veer comes from WRF in sortie hours and is zero
  from the COARE profile in the other hours (the COARE profile scales the 10 m vector).
- `profile` overestimates stable shear above the surface layer (z above about 0.1 z_i); the docstring says so. At hours with no 3-D
  field the COARE profile is used up to 100 m.
- 3-D hours are only the launch hour and the next one of each UAS sortie (`pipeline._sortie_hours`).

Inputs: `U10, V10` (earth-relative after rotation), COARE state (section 3), `U3, V3, Z3`. Uncertainty: `Tagged.uncertainty` is the Stage-1 wind
prior sigma (`config.env_sigmas()["wind_ms"]`, 2.0 m/s by default) until the TAO fit replaces the *perturbation* (section 7); the Tagged value
itself keeps the prior sigma.

Receipt: `pm.env.coare`, group `COARE 3.5`, claim `neutral U(100 m)/U(10 m) vs log law`: `U(100)/U(10) = ln(100/z0)/ln(10/z0)` within 1 %. The
log-linear 3-D branch has no registered receipt; `tests/test_environment.py` covers it.
Independent check recorded once (lead's log, real data): COARE u* against WRF `UST` is 0.208 against 0.211 m/s and 0.159 against 0.168 m/s at the
two sample points. Not a registered receipt.

---

## 3. COARE 3.5 and the warm layer

Code: `cafe/pm/env/coare.py`: `coare35`, `profile`, `psit`, `psiu`, `warm_layer`; `surface.py`: `_coare_grid`, `build`. Tests: `tests/test_coare.py`.

Bulk loop (Fairall et al. 2003 COARE 3.0, Edson et al. 2013 COARE 3.5), vectorised over members and points, 10 iterations:

```
u*  =  kappa u_t / [ ln(z_u/z0) - psi_u(z_u/L) ]          T* = -(dT - dT_skin) kappa / [ ln(z_t/z0t) - psi_t(z_t/L) ]      q* likewise
L   =  z_u / zeta,   zeta = kappa g z_u (T* + 0.61 T_a q*) / (T_a u*^2)                          kappa = 0.4
z0  =  alpha u*^2 / g + 0.11 nu / u*       alpha:  Charnock  0.0017 U10n - 0.005   (U10n capped at 19 m/s)     Edson 2013
                                                   wave age  0.114 (u*/c_p)^0.622                                 (c_p finite)
                                                   sea state z0 = 0.091 Hs (u*/c_p)^2, floored at 0.11 nu/u*      (c_p and Hs finite)
gustiness  u_t = sqrt(u^2 + u_g^2),  u_g = 1.2 (B_f z_i)^(1/3)  (B_f > 0),  else 0.2 m/s;      gf = u_t / u
cool skin: Fairall et al. 1996 eqs 12-17 (with `jcool=0` the skin temperature is given, there is no cool skin and `dter` and `tkt` are returned as 0: review round 12, M-14);  thermal roughness z0q = min(1.6e-4, 5.8e-5 / R_r^0.72)        rain heat flux: Gosnell et al. 1995
psi:  Beljaars & Holtslag 1991 (stable),  Grachev et al. 2000 (convective) blended with Businger et al. 1971 (Kansas) in the unstable branch
profile:   U(z) = u* / (kappa gf) [ ln(z/z0) - psi_u(z/L) + psi_u(z0/L) ]       (mean, not gust-inclusive, wind relative to the current)
```

In the pipeline `surface.build` runs COARE once per WRF hour on the whole grid with `cp = dcp` and `sigH = swh` from UMWM, so the roughness
is the **sea-state** form wherever UMWM's dominant phase speed `dcp` is at least 3.5 m/s (`coare.CP_FULL`); from 2 m/s (`CP_MIN`) to 3.5 m/s the Charnock parameter fades linearly into it, and at 2 m/s or under, negative or missing it is the Charnock form (review round 12, M-13, DECISIONS 653: a `dcp` of 0, in a calm or over ice, gave NaN u*, z0, L and Cd, and a hard switch at one speed gave a step of up to 2.6 times in Cd; the demo's smallest `dcp` is 3.93 m/s over 5.9 million sea values, so it takes the pure sea-state form there, bit for bit; the two speeds are ours and the fade is a guard against the step, not a calibration of young-sea drag). Inputs: `U10, T2, Q2, PSFC, SST, SWDOWN, GLW, PBLH` (z_i = max(PBLH, 100 m)), `RAINNC+RAINC`.
WRF SST is read as the foundation temperature.

Deliberate difference from `pycoare` 0.4.3: in sea-state mode pycoare never subtracts `0.11 nu/u*` inside its loop; the code follows the
paper's form (`Ad Hs (u*/cp)^2` floored at the smooth-flow value). The paper wins. The NOAA Matlab subtracting the term too is "from memory,
not re-read". Effect: up to about 5 % in u*, 10 % in Cd on the test grid (context rows).

Warm layer (Fairall et al. 1996; Price, Weller & Pinkel 1986 bulk Richardson criterion; three-band absorption of Paulson & Simpson 1981 and Soloviev
1982), coded as in NOAA PSL `coare36vnWarm_et.py`, re-implemented:

```
f(d)  = 1 - [ 0.28 (0.014)(1 - e^(-d/0.014)) + 0.27 (0.357)(1 - e^(-d/0.357)) + 0.45 (12.82)(1 - e^(-d/12.82)) ] / d     fraction of solar heating inside depth d
Q     = f(d) 0.945 SW - (net longwave out + H + LE + rain flux)        accumulate while Q >= 50 W/m2 (or once active)
d     = sqrt(2 Ri_c c_pw / (alpha g rho_w)) tau_acc / sqrt(Q_acc)   (max 19 m, 5 iterations),   Ri_c = 0.65
dT_w  = sqrt(2 alpha g / (Ri_c rho_w)) / c_pw^1.5 x |Q_acc|^1.5 / tau_acc
```

Accumulators reset at local mean solar midnight (UTC + lon/15 h). A series that starts after dawn under-warms its first partial day by
construction (docstring). The result `dT_warm`, `dz_warm` is the surface-minus-foundation difference and the depth of the layer.

Uncertainty: not propagated. The COARE and warm-layer outputs are deterministic functions of the WRF fields; the Stage-1 wind error enters through
the perturbed U10 only (section 8). The warm layer's own error is not in any prior.

Receipts, job `pm.env.coare`, group `COARE 3.5`:

| Claim | Tolerance | What it is |
|---|---|---|
| `C_D10N at U10N = 5 m/s (Edson 2013 closure)`, same at 10 and 15 | 3 % | **closure**: root-find of the same z0 law; Edson's own Cd table was unreadable (HTTP 403). Credibility limitation L04. |
| `C_D10N at U10N = 5 m/s vs Large & Pond 1981` (and 10, 15) | context | orientation only |
| `max relative difference to pycoare 0.4.3, bulk roughness, 32 states: u*` (and sensible, latent, Cd), same for `wave-age` | 0.5 % | independent code, same paper |
| `max relative difference to pycoare 0.4.3, sea-state roughness: u*` ... | context | the pycoare quirk above |
| `sea-state z0 = Ad Hs (u*/cp)^2` | 1 % | |
| `neutral U(100 m)/U(10 m) vs log law` | 1 % | |
| `peak warm-layer dT, calm sunny day (U = 2 m/s)` | 0.3 to 3.5 K | Fairall 1996; Webster et al. 1996 (0.5 to 3 K calm) |
| `peak warm-layer dT, windy day (U = 10 m/s)` | 0 to 0.1 K | |

On the real cache the warm layer peaks at 3.13 K (03-05/06 calm period), the top of the 0.5 to 3 K range (lead's log).

---

## 4. Waves

Code: `cafe/pm/env/waves.py` (`spectrum_from_params`, `spectrum_from_restart`, `hs_from_restart`, `stokes_profile`, `stokes_transport`,
`stokes_breivik2016`, `Realization`), `surface.py` (`build`, `_correct_with_real`, `SurfaceLayer.stokes_surface`). Tests: `tests/test_waves.py`,
`tests/test_surface.py`.

### 4.1 Spectrum from UMWM's integrated parameters

Axes: `E[..., f, theta]` in m^2 Hz^-1 rad^-1; `f` the 37 UMWM log-spaced bins (0.0313 Hz, ratio 1.1225); `theta` compass degrees TO, full circle,
uniform. Bin width `df = f dlnf`.

```
E = (hs^2 - w) A + w B                      A, B unit spectra with Hs = 1 (m0 = 1/16), each renormalised on the discrete bins
A  primary: peak at fp = 1/Tp.   om = U10/cp = 2 pi fp U10/g,  clipped to [0.83, 5]
     wind sea (cp/U10 <= 1.2):  S = f^-4 exp(-(f/fp)^-4) gamma^exp(-(f-fp)^2/(2 sigma^2 fp^2))             Donelan, Hamilton & Hui 1985
          gamma = 1.7 (om < 1),  1.7 + 6 log10(om) (1 <= om <= 5);   sigma = 0.08 (1 + 4 om^-3)
     swell    (cp/U10 > 1.2):   S = f^-5 exp(-1.25 (f/fp)^-4) gamma^exp(...),  gamma = 3.3,  sigma = 0.07 (f <= fp), 0.09 (f > fp)   JONSWAP, Hasselmann et al. 1973
B  short sea: DHH wind sea at U10/cp = 2.0, fp_B = 2.0 g / (2 pi U10)
D(theta) = cos^(2s)(dtheta/2), normalised;   s = clip( s_p (f/fp)^5 for f < fp, s_p (f/fp)^-2.5 above, 1, 60 );   s_p = 11.5 (cp/U10)^2.5
w   = clip( (mss - a_A hs^2) / (a_B - a_A), 0, hs^2/2 )     a = int k^2 E df dtheta = (2 pi)^4/g^2 m4    (the slope variance of A and of B)
```

- **mss cannot fix the spreading** (BRIEF correction §2.3): UMWM's `mss` is summed over direction. It fixes w, the share of short-wave energy. The
  synthesised mss equals the file's to 0.0 % when w is not clipped.
- s follows Mitsuyasu et al. 1975 and Hasselmann et al. 1980 (both marked `*` in the docstring: **not re-read**); the cap 60 is the narrowest the
  11.25 degree bins can resolve.
- The swell threshold `swell_age = 1.2` and the short-sea age `wind_sea_age = 2.0` are **assumed**. They are the keys `waves.swell_age` and
  `waves.wind_sea_age` of `config/assumptions.yaml`, which `waves.py` reads, and the credibility report lists both as assumed inputs (they moved into the yaml
  in an earlier round; this text said otherwise until review round 12, M-17, DECISIONS 657).
- The discrete shapes lose about 0.5 % of Hs on 37 bins; the renormalisation removes it.

### 4.2 Real restart spectra

```
E(f, theta) = F k (dk/df),    dk/df = (k/f) dln k / dln f   from the file's own k(f)       (deep water: 2k/f)
theta axis reordered to ascending compass-TO.   The k factor is the Jacobian of the polar element k dk dtheta; dropping it is a k-fold error.
```

### 4.3 Stokes drift

```
u_s(z) = 2 int omega k e^(2kz) E(f, theta) (cos, sin)(theta) df dtheta,  omega = 2 pi f,  k = omega^2/g          Kenyon 1969, deep water
u_s(0) = (16 pi^3/g) int f^3 E df dtheta   = 2 m3/g with m3 = int omega^3 E(omega) d omega   (angular-frequency moment; BRIEF correction)  Breivik et al. 2016 eq 6
V      = int_{-inf}^0 u_s dz = int omega E df dtheta                                                   transport
u_s(z) = u0 [ e^(2kz) - beta sqrt(-2 pi k z) erfc(sqrt(-2kz)) ],   V = u0 (1 - 2 beta/3)/(2k)  =>  k = |u0|(1 - 2 beta/3)/(2|V|)       Breivik 2016 eq 19, 22, 23 (beta = 1)
```

### 4.4 The real-spectrum correction and its measured error

The hourly Stokes field is integrated from the parametric spectrum (4.1) on every 3rd UMWM node. Against the real spectra at the 6-hourly
restart times it was wrong: **median speed error 38 %**, the median over all nodes of |fit/real - 1| (the attribute `fit_only_median_speed_err`, 0.3843 on the
real cache, 25 restart times); that measure is symmetric and does not say which way the fit is wrong. The receipt `Wave direction (cache tepex_c_demo)`, context row
"median speed of the Stokes drift from the parametric spectrum / from the real restart spectrum", re-read on the real cache (2026-11-08, code `2d5e6ad`, orca; the
record is `review/round_12/m18/`) gives a median ratio of **0.657** at 211 points (10th to 90th percentile 0.51 to 0.85, largest 0.995): the fit is below the real
speed at every point, by a factor of about 1.5 at the median and at most 2.2. (This section used to say "under-predicts by about x2.7", from the lead's log;
no ledger holds that figure and it is withdrawn, review round 12, M-18, DECISIONS 658.) The fix (`surface._correct_with_real`):

```
c(node, t_r) = ( real_e + i real_n ) / ( fit_e + i fit_n )      at each restart time t_r (complex ratio: speed error and rotation)
c(node, t)   = linear in t between restart times, held outside; c = 1 at nodes with no real spectrum; the hourly field is c x fit
leave-one-out: predict each interior restart b from the corrections at its neighbours a, c (12 h apart, twice the span used):
    pred = [(1 - w) c_a + w c_c] fit_b,   w = (t_b - t_a)/(t_c - t_a)
    speed error = median | |pred|/|real| - 1 |,   direction error = median | arg(pred/real) |
```

Measured on the real cache (the stored attribute `stokes_fit_check` of the demo's `derived.zarr`): **leave-one-out median speed error 5.1 % (0.0513), direction 3.7 deg
(3.74)** (fit alone 38 %). `stokes_surface` tags the field with `uncertainty = (LOO median speed error) x |u_s|`: a median is used as a 1-sigma, which is an
**assumption**. The correction needs at least three restart times in the window (an interior one is predicted from its two neighbours): with fewer, or with a
leave-one-out error that is not finite, there is no correction (`stokes_fit_check` is null) and the field is the fit alone (review round 12, M-1, DECISIONS 641); a window
that short has one or two restart hours, for example 5:00 to 7:00. Without restart spectra, or without that correction, the tag is `0.4 |u_s|` (assumed).

### 4.5 Sea-surface realisation, second order (library only)

`Realization` draws a random-phase sea from E with stratified equal-energy sub-bins (4 per bin, frequencies and directions random in the bin, so
the record never repeats), finite-depth linear kinematics with Wheeler stretching `z_s = h (z - eta)/(h + eta)`, and a second-order elevation from
the 64 largest components when `eps = kp Hs/2 > 0.05`:

```
eta2 = sum_{i<=j} [ c+ cos(psi_i + psi_j) + c- cos(psi_i - psi_j) ],   c = w_ij a_i a_j G(+-),   w_ij = 1/4 (i = j) or 1/2
G+ = [ wa^2 + wb^2 + wa wb (1 - c) + 2 wa wb ws^2 (1 - c) / (g|ka + kb| - ws^2) ] / g,   G- = G+ with wb -> -wb, c -> -c       (c = cos of the angle between components)
```

The deep-water limit of Sharma & Dean 1979 was **derived by the author** and checked against the Stokes crest and the Longuet-Higgins & Stewart 1960
collinear limits (the lead's log asks for a review). The 0.05 threshold is the brief's, attributed to Smit et al. 2017, whose citation is **not verified**.
`Realization`, `stokes_breivik2016` and `encounter_spectrum` are not called by Stage 1 or Stage 3 in this build; they are implemented and receipted.

### 4.6 Receipts, job `pm.env.waves`, group `Waves`

| Claim | Tolerance |
|---|---|
| `Hs of the discretised spectrum (Hs 2.0, Tp 14.0 s, U10 4.0 m/s) vs target` (and 1.5/4.0/12.0, 3.5/11.0/7.0) | 1 % |
| `hs_from_restart of the equivalent UMWM F (Hs 2.0) vs target` (same three) | 1 % |
| `m0 (int f^0 S df) of the DHH wind sea shape, 37 log bins vs quadrature`, `m2` likewise, for `swell` too | 2 % |
| `mean-square slope of the synthesised spectrum vs UMWM mss` | 1 % |
| `Stokes surface drift speed vs (16 pi^3/g) int f^3 E df (= 2 m3/g)` | 1 % |
| `Stokes drift direction (spectrum in the bin toward compass ... deg)` | +-0.5 deg |
| `Breivik 2016 profile speed at z = -0.25 m vs Phillips-spectrum integral` (also -1, -3, -8, -20 m) | 2 % |
| `realization variance of eta (20000 points x 1 h) vs m0` | 5 % |
| `max \|autocorrelation\| of a 1 h record at lags 10-30 min (no repeat)` | below 0.6 (a regular grid gives about 1) |
| `propagation direction of a realization given dwd = -135 deg (math) = 225 deg compass` and `Stokes drift direction for the same input` | 220 to 230 deg |
| `second-order switch at Hs 1.5 m, Tp 10 s ...` (off) and `... Hs 3.0 m ...` (on) | exact |
| `second-order crest of one component vs Stokes a + k a^2 / 2` | 1 % |
| `phase speed -eta_t / (d . grad eta) of a component vs g / omega` | 1 % |

The correction of 4.4 is checked by the `Wave direction` rows of section 0 (direction and speed ratio on the fixture and on the real cache); its
5.1 % / 3.7 deg figures are stored in `derived.zarr` (`stokes_fit_check`) and shown in the report, not in a registered receipt.

---

## 5. Sub-grid: turbulence, gust fronts, rain lens, diurnal jet

Code: `cafe/pm/env/subgrid.py`; configuration `config/subgrid.json` (sourced) and `config/assumptions.yaml` (`subgrid.*`, each with why and
what replaces it); coupling to the environment in `surface.py`. Every output is `Tagged(..., kind="modelled")`. `config/subgrid.json["calibration"]`
is the shipped calibration (a run's Stage-3 LES writes its own, section 5.x); `calibration.source_run` is `null`, so the shipped defaults run. Tests: `tests/test_subgrid.py`,
`tests/test_surface.py`.

### 5.1 Mann turbulence

```
Mann (1994) uniform-shear spectral tensor, Gamma = 3.9, via mannrs 2.0.0 (IEC 61400-1 ed.3 Annex C; Mann 1998)
L_neutral = 0.8 Lambda_1,   Lambda_1 = min(0.7 z, 42 m)
L(z/L_ob) = L_neutral / phi_m(z/L_ob), clipped to [0.2, 3] L_neutral, x calibration.length_scale_factor (1.0)      Pena, Gryning & Mann 2010
phi_m = (1 - 16 zeta)^(-1/4) (zeta < 0),  1 + 5 zeta (zeta >= 0)                                                   Businger et al. 1971, Dyer 1974
box: nx = 16384, dx = L/2, ny = nz = 16, Ly = Lz = 8 L;  series at the centre node, frozen advection x = U t (Taylor)
amplitude: the series is rescaled so sigma_u = 2.5 u*         (Panofsky & Dutton 1984; Kaimal & Finnigan 1994)
```

- Sigma_v/sigma_u = 0.63 and sigma_w/sigma_u = 0.43, against IEC 0.8 and 0.5, because the box resolves the 1-D spectrum only to kL of about 3 (about 80 %
  of the variance) and rescaling puts all of sigma_u into that band: the resolved band carries about 12 % too much amplitude. Credibility limitation L07.
- The stability rule `1/phi_m` and its clip are **assumed**, not validated offshore; Stage-3 calibration is the intended correction.
- Members share boxes through non-overlapping x-segments (two members of a box are separated by at least U x duration, many integral lengths); a
  `ValueError` states the capacity when exceeded. The pipeline picks the fewest boxes that hold the members (`stage1._fewest_boxes`).
- Uncertainty tag: `0.2 sigma_u` (**assumed**).
- The UAS gets one Mann box per sortie, at z = deck height + the mean of the sortie's altitudes (58 m for the demo mission: deck 8 m, altitudes 10, 30, 60 and 100 m), advected at the mean wind of that height; the series is applied to every leg, so the 10 m leg sees the length scale of 58 m (Lambda_1 = 40.6 m; 12.6 m at its own height z = 18 m, 42 m at 100 m). sigma_u = 2.5 u* does not depend on height here, so only the length scale is affected. Credibility limitation L20.

### 5.2 Gust fronts

```
lambda [1/h] = lambda_bg + lambda_max (1 - exp(-rain / R0)) f(theta_e),    f = clip( (theta_e - 335 K) / 15 K, 0, 1 )
    lambda_bg = 0.005, lambda_max = 0.3, R0 = 1 mm/h   (all assumed);   theta_e: Bolton 1980 eqs 21, 24, 43 from T2, Q2, PSFC
events per member-hour ~ Poisson(lambda), start uniform in the hour; duration U[600, 1800] s; peak dU U[3, 10] m/s;
direction = mean wind direction + N(0, 45 deg) (assumed); dT = -1.5 K (the detection threshold, so a bound, not a distribution; the value is `calibration.gust_stats.dT`, and `config/subgrid.json` holds no separate detection threshold: DECISIONS 801)
dU(t), dT(t): triangle, rising linearly over 450 s (wind) and 600 s (temperature) after onset, falling linearly to the end of the event
```

The structure (cold pools sit under rain) follows Wills, Cronin & Zhang 2021, **abstract only**; peak gusts 5 to 10 min after the temperature front is
Wills et al. 2023 **as summarised in a search**; every number in the rate model is assumed. **The pipeline passes `theta_e` to `gust_fronts`** (`stage1._uas_forcing`: `subgrid.theta_e` from the ship's T2, Q2 and PSFC, since `7a359dd`),
so f(theta_e) is active and the cold-pool factor works; the `theta_e_lo_K` and `theta_e_span_K` assumptions are used by a run (review round 6, M-25).
One event set is drawn at the ship for the window and applied everywhere along a sortie (no spatial structure).

### 5.3 Rain fresh lens

```
dS(z) = 0.5 psu x A x W x exp(-t_since / tau) x top(z)
A = clip( (r - 1) / (5 - 1), 0, 1 )   r in mm/h (trigger and saturation are assumed)
W = clip( (8 - U10) / (8 - 5), 0, 1 ), tau = 600 + (7200 - 600) W  s       (Iyer & Drushka 2021: absent above about 8 m/s; tau limits assumed)
top(z) = 1/2 [ 1 - tanh( (-z - 0.5 m) / 0.1 m ) ]     thickness 0.5 m, edge width assumed
dT_lens = -0.2 K x (same factor)                       assumed, not from a paper
density: d rho = rho [ -alpha (dT_warm(z) + dT_lens) - beta dS ],  alpha, beta = gsw.alpha, gsw.beta (SA 35, CT 28, p 0)       lens and warm layer act on density only
```

Iyer & Drushka 2021 is cited "as summarised in BRIEF 2.2; the paper itself was not re-read". The lens size (7 km) is carried but not used.

alpha and beta are evaluated once at the fixed tropical constants SA 35, CT 28, p 0 (`gsw.alpha(35.0, 28.0, 0.0)`), not at the box's mean surface state, which `surface.py` and DECISIONS 40 used to say: alpha is 3.19e-4 at CT 28, 2.14e-4 at 15 and 1.13e-4 at 5, so in a box of 5 degC the warm-layer and rain-lens density change is 2.8 times too large. The demo (SST 299 to 303 K) is unaffected; the box-mean option is not built (review round 12, M-16, DECISIONS 656).

**Persistence.** `surface.build` stores `since_rain_s` (time since the last hour with rain above the trigger) and `last_rain_mm_h` (that hour's rate), and
`SurfaceLayer._lens` feeds `last_rain_mm_h` as the rate, so a lens formed by an hour of rain decays with `exp(-t_since/tau)` after the rain stops. This was
**added in commit bb68642 (2026-10-29)**; before it the lens followed the instantaneous rain rate and vanished with it, so `since_rain_s` had no effect.
`derived.zarr` layout version 2 holds the new field; ingest rebuilds an older store and `SurfaceLayer` refuses one with the rebuild command. Since review round 4 (M-2, DECISIONS 238) the store is built from a key (sha256 of the orca manifest, the ocean store manifest, the GEBCO cut and the code digest) kept in its attributes and in `derived.digest.json`, so any change of the cache, the window or the code rebuilds it (about a minute), the store's hash is a ledger input and output of ingest and is re-checked (`derived_unchanged`) by every stage that reads it, and a store whose hours do not span the window is refused rather than clipped. Test:
`tests/test_surface.py::test_rain_lens_outlives_the_rain_and_decays_with_its_e_folding_time`. The wind enters the decay through the instantaneous
U10, not the wind history.

### 5.4 Diurnal jet and ocean SDE

```
jet [m/s] = 0.2 (midpoint of config/subgrid.json [0.1, 0.3]) x min(dT_warm / 3 K, 1) x ( 1 + z/d_warm )_+ , along the 10 m wind, added to the HYCOM current; no uncertainty is carried: every member uses the 0.2 midpoint and the 0.1 to 0.3 range is drawn only by the receipt (`subgrid.diurnal_jet`)
```

TEPEX-C's own hypothesis (BRIEF 2.2), **modelled, not observed**; `dT_ref = 3 K` is assumed. It enters through `SurfaceLayer` (mission switch
`warm_layer`: no warm layer, no jet). Windage is **not** added to the current, because the HYCOM top layer holds the Ekman drift and the USV VPP has its
own windage. At the surface the glider drifts with a per-member leeway of 1.8-2.3 % of U10 (`subgrid.windage_fraction`). The jet is not drawn per member: the run uses the midpoint 0.2 m/s times the warm-layer factor for every member, `current_extra` returns the base uncertainty, and `subgrid.diurnal_jet`, which draws the 0.1 to 0.3 range per member, is called by the receipts only (review round 12, M-10, DECISIONS 650); drawing it in stage 1 would shift the USV and glider P(fail) and is the owner's call.

Ocean SDE (mission switch `ocean_sde`): the Okubo (1971) diffusivity `K = 0.0103 l^1.15` cm^2/s at the 0.08 deg HYCOM cell (**typed from memory**), and
the Ito/Euler-Maruyama step `dx = (u + dK/dx) dt + sqrt(2K) dW` (OceanParcels tutorial; well-mixed condition of Thomson 1987). The vehicles take
`u dt` from the current they read and add `dK/dx dt + sqrt(2K dt) xi` from `PerturbedEnv.sde_displacement` to their **position only**. Steering, the
glider's dive-averaged current, and the USV's becalmed and wing-stall tests see the resolved, perturbed current, never the unresolved-eddy noise
(DECISIONS row 100). The noise is one stream per member (`member_rng(seed, m, "ocean_sde")`), indexed by step number, and the same in any batch.

### 5.5 Receipts, job `pm.env.subgrid`, group `sub-grid`

| Claim | Bound |
|---|---|
| `sigma_u / u* (mean of 12 members, 1800 s) vs the configured calibration` | 6 % of 2.5 |
| `all members' sigma_u/u* within 25 % of 2.5 (sampling spread)` | 25 % |
| `u' mean over members and time is ~0` | 5 % of sigma_u |
| `u spectrum / analytic Mann spectrum, 0.3 < kL < 1.5` | 0.85 to 1.15 |
| `Mann model inertial-range slope of F11(k1), 30 < kL < 1000` | -1.72 to -1.62 |
| `delivered u spectrum log-slope minus analytic Mann slope, 0.5 < kL < 1.5` | +-0.3 |
| `rms zero-lag correlation between members sharing a box (sampling noise ~0.05)` | below 0.1 |
| `events per member-hour, heavy rain / dry` | 10 to 200 |
| `gust front peak dU, min` / `max`; `gust front duration range, min` / `max` | the configured ranges |
| `front dT 10 min after onset (Wills 2021 detection: <= -1.5 K within 10 min)` | -1.6 to -1.5 K |
| `well-mixed tracer: low-K / high-K count ratio, with dK/dx drift` | 1 +- 4 sigma; the negative control `... WITHOUT the drift term departs from 1 (must lie outside)` must fail it |
| `windage / U10 (min over 500 members)` / `(max ...)`; `diurnal jet at dT = 3 K, min` / `max`; `diurnal jet at dT = 0`; `jet points downwind (cos angle to wind)` | the configured ranges |
| `rain lens dS at 3 m/s, 8 mm/h` / `at 9 m/s, 8 mm/h (absent above ~8 m/s)` / `below 0.5 m is gone (z = -1.5 m)` | 0.45 to 0.5001 psu / 0 / below 0.01 |
| context `configured sigma_u / u* vs the neutral surface-layer value` | none |

The windage, jet and gust-range rows check the code against the numbers written in `config/subgrid.json`; they are consistency checks of the configuration,
not tests of the physics. The ranges themselves are the brief's (BRIEF 2.2) or assumed.

### 5.x Recalibration from stage 3 (`subgrid.recalibrate`, `pipeline_windows.recalibrate_subgrid`)

A run's Stage-3 LES recalibration, made only from passed stage-3 windows that resolved an inflow series, is written to `stage3/subgrid_calibration.json` of that run and is read by the stages after stage 3 (stage 1b is rerun with it even when no vehicle was refit). The tracked `config/subgrid.json` is changed only by `python -m cafe.pm promote-calibration --run DIR`, which records the run's full path, the date and the digest of its stage-3 ledger in `calibration.source_run` (review round 3, M-23); stage 1 always uses the tracked calibration. `calibration.source_run` of the tracked file stays null until a calibration is promoted. `recalibrate` fits sigma_u/u* = std(u)/u*. The length factor is the ratio of the window's Taylor-frozen integral scale to that of the
configured Mann layer at the same z, U and u*. Gust statistics are never changed. The windows of this build use a uniform inflow, so no series is resolved,
the layer stays uncalibrated, and the stage ledger says so (DECISIONS 162). That holds for a GPU run as well: no code sets an inflow series in a window row, so no run writes `stage3/subgrid_calibration.json` and `promote-calibration` has nothing to promote (review round 11, M-34, DECISIONS 626).

---

## 6. Ocean: GOFS / HYCOM, TEOS-10, bathymetry

Code: `cafe/pm/env/hycom.py` (`fetch_gofs`, `assemble_gofs`, `teos10`, `read_lab_netcdf`, `read_archv`, `ingest_lab_hycom`), `ocean.py`, `bathy.py`. Tests:
`tests/test_hycom.py`, `tests/test_ocean.py`, `tests/test_bathy.py`.

Source. GOFS 3.1 GLBy0.08 expt_93.0, 3-hourly, 40 z-levels, `water_temp salinity water_u water_v surf_el`; or the lab's HYCOM (per-snapshot netCDF, or `archv.*.a/.b`
with `yrflag 3` only, curvilinear grids refused). Store: `DATA/ocean/gofs_<mission>.zarr`, `(time, depth positive down, lat, lon in [0, 360))` (review round 8, M-29: for a lab store whose box lies within a grid step of 0 E the axis is continuous with the box, so the bracketing neighbour across 0 E is below 0 or above 360; the readers take a query into the axis's own frame), float32
fields, loaded lazily one variable at a time (about 1.2 GB each over the TEPEX-C box).

```
TEOS-10 per cell, never averaged:   p = gsw.p_from_z(-depth, lat);  SA = gsw.SA_from_SP(SP, p, lon, lat)
    in situ t:   CT = gsw.CT_from_t(SA, t, p)          potential t (referenced to 0 dbar):  CT = gsw.CT_from_pt(SA, t)
    rho = gsw.rho(SA, CT, p),   c = gsw.sound_speed(SA, CT, p)
interpolation: grid.interp, linear in time, depth, lat, lon; NaN corners (below the floor) dropped and the weights renormalised
lab archv: u_total = u_baroclinic + u_barotropic; layer thickness thknss/9806 m; SSH srfhgt/9.806 m; velocities destaggered onto T points;
    layers -> fixed depths by linear interpolation between layer mid-points
```

- `temperature_kind` is `in_situ` or `potential` and is **never guessed**: a store with no such attribute is refused. GLBy writes in-situ temperature (hycom.org).
- The existing app's one-snapshot rule (DECISIONS 8) does not apply here: the pre-mission environment interpolates the 3-hourly fields in time. The fetched steps cover the window (the last at or before the start to the first at or after the end), and `Ocean.inside` tests the store's lat, lon and time axes, so `GriddedEnv.inside` is False and a strict environment raises `OutsideData` where the ocean store ends (review round 7, M-24). A lab store passes its check when its times span the window, whatever its regular cadence (M-12). Parts of a GOFS download are reused only for the box they were cut to (M-3).
- The glider and USV read `rho` through `GriddedEnv.density`, which adds the warm-layer and rain-lens terms of section 5.3.

Bathymetry (`bathy.choose`), in this order, first that works:

| Order | Source | Resolution | 1-sigma |
|---|---|---|---|
| 1 | GEBCO_2026 15 arc-second, `elevation` positive up, depth = -elevation, 0 on land; cut from the 7.47 GB file by one HTTP byte range per box row | 460 m | `bathy.gebco_rel_sigma` = 5 % of depth (**assumed**) |
| 2 | floor between the deepest valid level of the GOFS store and the next: the level plus half the spacing (the levels are 5 to 1000 m apart); where the last level (5000 m) is wet the floor is unbounded below and 5000 m is a lower bound (review round 9, M-35, DECISIONS 495) | 0.08 x 0.04 deg | spacing / sqrt(12), computed; the open last level has the assumed `bathy.gofs_open_level_sigma_m` = 1000 m |
| 3 | UMWM `depth` (12 km) | 12 km | `bathy.umwm_rel_sigma` = 10 % (**assumed**) |

`open_ocean` passes only the GOFS store to `choose`, so in a pipeline run the fallback is GEBCO then GOFS; UMWM depth serves only when no ocean store is loaded.
What failed is kept in `Bathymetry.tried` and reaches the report.

Uncertainty. The ocean values carry no sigma at this layer; the current's error is applied by `PerturbedEnv` (section 8). T/S have no perturbation prior.

Receipts.

| Job, group | Claim | Tolerance |
|---|---|---|
| `pm.env.hycom`, `Ocean (HYCOM / TEOS-10)` | `in-situ density from SP, in-situ t, depth vs GSW check values: max relative error over N points`; same for `sound speed` | 2e-7 |
| | `same 4.4 degC read as potential instead of in situ at 1000 m: conservative temperature too warm by` | 0.05 to 0.15 K (shows the cost of guessing the kind) |
| | `same: density too small by` | 0.005 to 0.05 kg/m^3 |
| | `lab HYCOM per-snapshot netCDF, hybrid layers -> store: water_temp vs the GOFS values it was encoded from, max abs error over N cells` (also salinity, water_u, water_v, rho, c, and `archv .a/.b`) | 5e-5, a float32 round trip on a synthetic fixture encoded from GOFS |
| `pm.env.bathy`, `Bathymetry` | `bilinear depth in a linear field vs the analytic value at 20 off-node points (max abs error)` | exact |
| | `GEBCO cache: depth at its deepest node vs -elevation of that node` | 1e-9 m (only when the GEBCO cache exists). The per-row byte-range row (`GEBCO per-row byte-range read vs h5py hyperslab ...`) needs a `url` argument the registered job does not pass, so it never runs under `receipts`. |

The lab readers have only ever read a synthetic fixture. The real-store check against NCSS (`check_node`) needs the network and is not a registered receipt. A node masked on both sides agrees; masked on one side only gives infinity, never 0.0 (review round 10, M-20).

---

## 7. TAO/TRITON data validation and the fitted priors

Code: `cafe/pm/env/tao.py` (`fetch_tao`, `load_tao`, `wind_to_10m`, `compare`), `pipeline._tao`. Tests: `tests/test_tao.py`.

Source: NDBC THREDDS copy of OceanSITES TAO/TRITON, 10-minute `WIND`, `SST`, `AIRT`, `RH` files; the PMEL ERDDAP only serves daily means for 2023. Winds are at 4 m,
SST at 1 m depth. QC flags (OceanSITES manual): delayed-mode files keep {1, 2, 5} (5 = calibrated; checked on T0N165E: 50863 of 51027 samples), real-time {1, 2}.
The files carry no wave variable, so UMWM `swh` cannot be checked against the moorings (`waves_available` warns).

```
height adjustment to 10 m
  'log':   neutral log profile u(z) = (u*/kappa) ln(z/z0), z0 = alpha(U10n) u*^2/g + 0.11 nu/u* (Edson 2013; Smith 1988), nu = 1.5e-5, fixed point on u*, U10n;
           ignores stability: overstates the 4 -> 10 m shear by 2-3 % at 6 m/s (context row)
  'coare': cafe.pm.env.coare with the mooring's AIRT, RH, SST;   'auto' uses COARE where all three exist
           (review round 9, M-32: only within `tao.air_gap_s` = 3600 s of a sample of each, interpolated linearly between samples; farther from the
           nearest sample of any of the three a sample gets the neutral log lift. One function, `tao.wind10`, serves `tao.compare` and the fitted wind prior)
model - mooring:  samples within +-30 min of each hourly model time, vector mean, at least 3 samples;
    speed bias, speed RMSE, vector RMSE; direction bias (FROM, signed, wrapped to +-180, only where both speeds >= 1 m/s); SST bias and RMSE
```

Fit on the real window (2023-03-01..07, lead's log): 11 moorings, 1492 hourly pairs (the TAO cache of 29 Oct 2026, the fit of q5 to q10; the cache of 6 Nov has 14 moorings with wind, see after the priors below).

| Quantity (WRF minus TAO) | Bias | RMSE |
|---|---|---|
| 10 m wind speed | +0.62 m/s | 1.46 m/s |
| wind direction (FROM) | -7.2 deg | 24.8 deg |
| SST | -0.11 K | 0.26 K |

Fitted Stage-1 priors (`pipeline._tao`, written to `ingest/priors_fitted.json`, read by `stage1.priors_for`). The mean is the correction that removes the model bias (sign flipped): `mean` is minus the mooring-mean error, that is mooring minus WRF, the correction `perturb.py` adds to WRF, while the error itself is WRF minus mooring (+0.62 m/s and -7.2 deg in the table above); the citation in `priors_fitted.json` says so (review round 10, M-25). Superseded first form, the
round-1 prior (the whole residual sd as a member-wide bias): `N(-0.62, 1.33) m/s` and `N(+7.2, 23.7) deg`. The current fit (DECISIONS 182, 209) on the real window with those 11 moorings (the demo's `priors_fitted.json` of q5; q10 gave -0.610, 0.110, 1.284 m/s and 6.41 h, +7.21, 2.63, 22.2 deg and 11.1 h):

```
wind_speed_bias      ~ N(-0.616, 0.113) m/s      persistent part only
wind_direction_bias  ~ N(+7.21,  2.63)  deg
wind_speed_noise     sd 1.283 m/s,  tau 6.43 h   per-member stationary AR(1) about each mooring's own mean
wind_direction_noise sd 22.2 deg,   tau 11.1 h
```

The same fit on the cache of 6 Nov 2026 (q10lb, `6c1fde7`, DECISIONS 589): NOAA had added delayed-mode files (created 5 Nov) for T5N180W, T5S165E and T5S170W, so 14 moorings have a QC-good wind in the window, and it had regenerated the three files of T5S180W.

```
wind_speed_bias      ~ N(-0.469, 0.569) m/s      95 % upper bound of the persistent sd 0.957
wind_direction_bias  ~ N(+6.24,  5.25)  deg      95 % upper bound 12.15
wind_speed_noise     sd 1.461 m/s,  tau 5.52 h
wind_direction_noise sd 24.6 deg,   tau 8.63 h
```

Since round 14 (M-44, DECISIONS 805) the two means are minus the unweighted mean of the moorings' time-mean errors, -0.460 m/s and +6.38 deg for these 14 moorings (q14la), where the pooled-sample means above are -0.469 and +6.24; the sds, bounds and noise terms do not change. The persistent sd is 5 times the 11-mooring one, and one mooring decides it: T5S165E has a speed bias of -1.482 m/s where the other 13 run -0.03 (T2N170W) to +1.14 (T5N165E), and without it (13 moorings) the sd is 0.1545 m/s (95 % bound 0.495, noise 1.293 m/s; `fit_wind_error` on the hourly residuals of q14la, orca, round 14, M-43, DECISIONS 804, `review/round_14/m43/`); leaving out any other one mooring gives 0.562 to 0.610. It is a property of 6 days and 11 to 14 moorings (limitation L19), not a measured spread. The environment sigma `sst_k` went from 0.259 to 0.303 K with the two new SST records (T5S165E, T5N180W), which changes nothing in stage 1. The fit code is the same for both: q10's priors on the code of `6c1fde7` give q10's counts (`review/round_10/moved_numbers.md`).

Review round 2 (M-1, DECISIONS 182) found the round-1 prior wide, not conservative: the whole residual sd, hourly scatter included, became a member-wide persistent bias held for six days,
because `PerturbedEnv` had no time-varying wind error term, and the data support a persistent part about three times smaller (the 11 per-mooring time-mean speed biases have mean
0.595 and sd 0.375 m/s, direction sd 8.7 deg; an estimate of the order, not a measurement, because six-day means of a synoptic WRF error are still correlated within the run). The fit
therefore takes the persistent part from the between-mooring dispersion of the time-mean error minus the mean sampling variance of those means (floored at 0), plus the variance of the fitted mean (var(means) / k for k moorings; a random-effects prediction for the mission site, so it is never 0 while the moorings disagree; the fitted `mean` is the unweighted mean of the k moorings' time-mean errors, the estimator that variance belongs to: round 14, M-44, DECISIONS 805), and fits the remainder,
the hourly residual about each mooring's own mean, as `wind_speed_noise` and `wind_direction_noise` (an sd and an e-folding time from the lag-1 autocorrelation) in `priors_fitted.json`;
`PerturbedEnv.wind` adds that remainder as a per-member stationary AR(1) series on an hourly grid over the window, drawn from `member_rng(seed, m, "wind_speed_noise" | "wind_direction_noise")` and read only when
the fitted priors hold the noise keys (20 to 40 microseconds per query); it is spatially uniform, so one value applies to every point of the box at a time. With fewer than two moorings the split is not defined and the whole hourly misfit stays
the persistent sd (no noise keys). Limitation L14 says the split is an estimate of the order. Four things are fed back: the two wind priors (with their noise terms) and the two tagged environment sigmas, `env.sigma.sst_k` and `env.sigma.t2_k`, which the
fit writes to `ingest/env_sigmas_fitted.json` (the demo run: 0.259 K and 1.191 K, against the assumed 0.5 K and 1.0 K) and `Context.env` applies over `assumptions.yaml` when the file exists. Every other residual (the SST bias, the vector RMSE, the rest) is
recorded in `ingest/tao_compare.json` and not used. A mission whose box holds no TAO/TRITON mooring with usable wind in the window fails the ingest at `tao_moorings_compared` (the comparison is mandatory, BRIEF 5.4); the `perturbations.yaml` priors stand only for a quantity the moorings do not measure (a calm WRF, a mooring without a direction channel), and the ledger says which (round 14, M-24, DECISIONS 785).

Receipts, job `pm.env.tao`, group `TAO / TRITON moorings`:

| Claim | Tolerance |
|---|---|
| `neutral 10 m drag coefficient of the wind-lift roughness law vs COARE 3.5 Cdn10 at COARE's U10n (max relative difference, 3-12 m/s)` | 0.05 absolute |
| `neutral drag coefficient at 10 m/s` | 1.0 to 1.4 (1e-3), Edson 2013 Fig. 6 |
| `wind lift 4 m -> 10 m at 6 m/s, neutral` | 1.05 to 1.11 |
| context `wind lift 4 m -> 10 m at 6 m/s: COARE with 80 % humidity ... vs the neutral lift` | none |
| `compare(): speed bias recovered from a model that is 10 % faster` / `direction bias recovered from a model rotated 10 deg clockwise (wind from)` / `SST bias recovered from a model 0.4 K warm` | 1e-6 / 1e-3 / 1e-6 (injected errors) |
| `TAO files whose SHA-256 differs from the manifest (of N)` | 0 (only when a download exists) |

---

## 8. Perturbations (Stage-1 priors)

Code: `cafe/pm/env/perturb.py` (`PerturbedEnv`, `Field`), `stats/sampling.py` (`load_perturbations`, `to_marginals`, `lhs`), `config/perturbations.yaml`. Tests:
`tests/test_perturb.py`, `tests/test_perturb_env.py`.

One `PerturbedEnv` per batch of members; member m sees the draws of member m, the same for every vehicle (common random numbers, section 13).

```
wind:    |u'| = max(|u| + b_speed[m], 0);  direction rotated clockwise by b_dir[m] degrees (so FROM and TO both increase by b_dir)
current: v' = R(b_cdir) v exp(s),   s = ln(a)/sqrt2 + (sigma_c/sqrt2) F_speed(x),    b_cdir_total = b_cdir/sqrt2 + (sigma_d/sqrt2) F_dir(x)
         a = current_speed_scale[m] (lognormal, median 1, sigma 0.30; s has mean 0, so the realised speed factor has median 1 as stated; a `- sigma_c^2/4` term that made it 0.978 was removed in review round 4, M-6);  half of each prior's variance is member-wide (the LHS draw, so the sensitivity indices see it)
         and half is a smooth random field with correlation length 100 km
x      = ( wrap180(lon - lon0) in radians x R cos(lat),  lat in radians x R ),   lon0 = the centre of the data box on the circle (0 for a whole-circle box): the field has no seam at 180 degrees (review round 4, M-9)
F(x)   = sqrt(2/32) sum_{i=1..32} cos( k_i . x + phi_i ),   k_i ~ N(0, 1/ell^2) per axis, phi_i ~ U(0, 2 pi)        random Fourier features, Gaussian covariance (Rahimi & Recht 2007)
waves:   Hs' = Hs hs_scale[m];  Tm' likewise;  Tp' = max(Tp + tp_bias[m], 1 s);  Stokes drift x hs_scale^2 x (Tp / Tp')^3 (surface Stokes drift of a fixed spectrum shape goes as Hs^2 / Tp^3; review round 2, M-21)
wind:    plus, when the fitted priors hold wind_speed_noise / wind_direction_noise (section 7): an AR(1) series per member, sd and e-folding time tau_h from the fit
         (the bias and the noise are factors on the base wind vector, so they are not applied where the base speed is 1e-9 m/s or less: a window of exactly zero wind has no
         wind spread, and at 1.1e-9 m/s the full bias applies along the base direction; review round 12, M-15, DECISIONS 655)
density, sound speed, depth, SST, air: unchanged
```

Priors (`config/perturbations.yaml`; `kind: prior` = the brief's number, `assumed` = ours):

| Name | Distribution | Source |
|---|---|---|
| `wind_speed_bias` | N(0, 2.0 m/s), replaced by the TAO fit | BRIEF 2.5 (WRF 10 m RMSE 1.8 to 2.5 m/s); primary source not named in the brief |
| `wind_direction_bias` | N(0, 15 deg), replaced by the TAO fit | BRIEF 2.5 |
| `current_speed_scale` | lognormal, median 1, sigma 0.30 | BRIEF 2.5 |
| `current_direction_bias` | N(0, 20 deg) | BRIEF 2.5 |
| `current_correlation_length` | fixed 100 km | BRIEF 2.5 (a setting, not sampled) |
| `hs_scale` | lognormal, median 1, sigma 0.15 | BRIEF 2.5 |
| `tp_bias` | N(0, 1 s) | BRIEF 2.5 |
| `bulk_stress_scale` | lognormal, sigma 0.30 | BRIEF 2.5; listed, not applied by any module in this build |
| `glider_speed_scale` | lognormal, sigma 0.10 | BRIEF 2.5 |
| `usv_vpp_bias` | uniform[-0.2565, -0.2280] | calibrated to Chiodi et al. 2021 (centre -0.2422), spread from Sun et al.'s 30 to 35 % as a speed factor (1/1.35 to 1/1.30); the brief's uniform[-0.35, -0.30] is the sensitivity case `usv_vpp_bias_brief` (DECISIONS 163). The width is the published spread of VPP over-prediction, not an uncertainty of this model: the model's own parameters are assumed and the anchor has no spread, so the ensemble holds the speed nearly fixed (sd 0.8 %); the stage-1b case `usv_vpp_bias_brief` is the sensitivity, and the USV card shows both (review round 7, M-15, DECISIONS 355) |
| `battery_capacity_scale` | lognormal, sigma 0.05 | **assumed** (kind `assumed`), listed in the credibility report |

Other 1-sigma values attached to the Tagged environment values come from `assumptions.yaml` (`env.sigma.*`: T2 1 K, q2 10 %, PSFC 100 Pa, SWDOWN 20 %, GLW 10 W/m^2,
wave direction 20 deg, SST 0.5 K), all **assumed**. They label the values; none is sampled.

Receipts: none registered. Tests check the priors file schema, that the draws are keyed by member, and that a member sees the same random field in any batch.
The per-batch seeding of other streams is listed under Known issues in `CHANGELOG.md`.

---

## 9. Glider (Seaglider and Slocum flight models, Stage-1 kinematics)

Code: `cafe/pm/physics/glider.py` (`seaglider_steady`, `slocum_steady`, `buoyancy`, `GliderSim`); platforms `seaglider.yaml`, `slocum.yaml`. Tests:
`tests/test_glider.py`. Every platform number is `{value, unit, source}` or `{value, unit, assumed: true, why}`; the loader refuses anything else.

### 9.1 Steady flight

Seaglider, as coded in UW/APL basestation3 `HydroModel.hydro_model` (read 2026-10-29) and described in Eriksen et al. 2001, Frajka-Williams et al. 2011.
Units are the code's: q = rho U^2/2 in Pa, alpha in **degrees**, hd_a in 1/deg, hd_c in 1/deg^2, hd_b in Pa^-s.

```
lift   L = l^2 a q alpha                           drag   D = l^2 q ( b q^s + c alpha^2 )                    l = 1.8 m, a = 0.003548, b = 0.011220, c = 5.7e-6, s = -0.25
glide angle  theta = pitch - alpha  (alpha has the sign opposite to theta, so the glide is always steeper than the pitch);   theta > 0 climbing, z up
steady balance along and normal to the path:   D = B sin(theta),   L = -B cos(theta)
=>  c alpha^2 + a tan(theta) alpha + b q^s = 0,   alpha = -(a tan(theta)/(2c)) ( 1 - sqrt(1 - 4 b c q^s / (a^2 tan^2 theta)) ),
    q = B sin(theta) q^(-s) / (2 l^2 b) ( 1 + sqrt(...) ),   iterated to |dq/q| < 1e-6      (Eriksen 2001 eqs 7-8 as in basestation3)
stalled: no real root, B and pitch of opposite sign, no convergence, or U < 0.01 m/s
buoyancy  B = g ( rho V - M ),   V = ( V_hull + dV_vbd ) exp( -gamma p + alpha_T (T - T_ref) ),   gamma = 4.1e-6 per dbar, alpha_T = 7.05e-5 per degC, T_ref = 15 degC
```

- The brief's drag form `D = l^2 q^(1+s)(b + c alpha^2)` and its one-line balance `L + B cos(th) - D sin(th) = 0` are **not used** (BRIEF correction §2.4): they leave a
  3.7e-3 force residual and are dimensionally inconsistent with `hd_b ~ q^(1/4)`; the basestation3 form closes to 1e-9. Battery: 17 MJ, the Kongsberg value, not the brief's 10 MJ.
- Hull compressibility (4.1e-6/dbar) is smaller than seawater's, so the glider gets more buoyant with depth. (DECISIONS 8 keeps hulls rigid in the existing app only.)
- Slocum: Merckelbach et al. 2010/2019 as in `gliderflight` 1.2.1 `SteadyStateGliderModel`, the oracle:
  `F_B = g rho (V_g (1 - eps p) + V_bp)`, `(Cd0 + Cd1 a^2)/((a_w + a_h) tan(a + pitch)) = a`, `U^2 = 2 (F_B - F_g) sin(pitch + a) / ((Cd0 + Cd1 a^2) rho S)`; angle of attack solved by a safeguarded Newton.
- basestation3's own `HydroModel.py` could not be executed here (blocked as an untrusted download); the code is a re-implementation checked by force residuals and a second solver.

### 9.2 Mission kinematics (`GliderSim`, 60 s step, vectorised over members)

- Sawtooth dives. Heading is fixed per dive and chosen so that through-water velocity plus the previous dive's depth-averaged current (DAC) points at the target:
  `r = clip((DAC . perp)/u_h_ref, -1, 1)`, `h = sqrt(1 - r^2) e - r perp`. DAC = (GPS displacement - dead-reckoned water displacement)/dive time.
- Ground velocity while flying = `U cos(theta)` along the heading + `env.current(z)` (which includes the surface jet inside the warm layer); surfaced: current + windage x 10 m wind; windage is 0.01 (**assumed**) for a bare `GliderSim`, and 1.8 to 2.3 % per member in Stage 1 (`subgrid.windage_fraction`, section 5.4; review round 4, M-21).
- Pilot ballasting (`_trim`): at the start position, 11 depths. Dive VBD = `delta` below the lightest ballast point, climb VBD = `delta` above the heaviest (`vbd_delta_cc` = 60 cc, **assumed**);
  if the span does not fit the 850 cc pump range the vehicle mass is shifted to centre it.
- Temperature: the Environment API does not expose the ocean store's temperature (`Ocean.temperature` exists but is not wired to the protocol, `Environment` or the perturbed wrapper), so `T = t_deep + (SST - t_deep) exp(-z/h)` with t_deep 4 degC and h = 150 m (**assumed**); it enters only through `alpha_T`. Credibility limitation L06 (review round 12, M-19, DECISIONS 659).
- Energy: hotel 0.5 W (**assumed**) + pump work `p dV/eta` with eta 0.40 (**assumed**; bracketed by NOC 65 W for 2 min and Copernicus os-2019-36) + surface comms + attitude motors (414 J per dive, sourced).
- Apogee overshoot: while the pump runs at the top of a dive (`pump_time_s`) the glider keeps sinking: the depth added is `apogee_overshoot` (0.5 in both platform files) times the last descent speed `w` for each second of the pump time, so it sums to `apogee_overshoot x w x pump_time_s` for any time step and any pump time (per step before review round 11, M-12: too deep by `ceil(pump/dt) dt / pump` when `pump_time_s` was not a multiple of `dt`; DECISIONS 604). Ordering the rating's depth trips `overdepth` by this overshoot (DECISIONS 550).
- Failure flags: `station_lost` (outside the tolerance for `lost_hours`), `battery`, `seafloor`, `overdepth`, `no_flight`, `waypoint_unreachable`, `no_current_data` (a non-finite current at any member or wind at a surfaced one, review round 8, M-14; since review round 9, batch C, also a flight model that failed while the density or the temperature it was given is not finite, a floor that is not finite at the start of a dive, and a member under water over a floor that is not finite: a hole in the input, not a failure of the flight model, which `no_flight` and `seafloor` now mean only on finite inputs; DECISIONS 501). Phase changes are evaluated at step ends, late by at most one step.
- **Drift mode** (review round 3, M-1). A glider in `drift` mode flies its dive cycle on one fixed compass heading, `task.heading_to` (required, 0 to 360; the demo writes 0.0), and surfaces at the end of every dive. It has no waypoint or station, so it cannot fail `station_lost` or `waypoint_unreachable`; the failure modes left are battery, seafloor, overdepth, no flight and left data. A GO for a drift glider therefore says only that its battery and depth limits held along that heading, not that it did something the mission asked; the report prints the heading and those modes, and its sanity row is "cannot be checked".
- Metres per degree: WGS84 series (NGA length-of-a-degree table), tested against the ellipsoid.

Uncertainty: per member `speed_scale` (lognormal, sigma 0.10, divided by `sqrt(drag multiplier)` after a Stage-3 refit) and `battery_scale` (lognormal, sigma 0.05, assumed); `density_bias` is zero in Stage 1.
The wind, current and temperature errors of section 8 act through the perturbed environment.

Receipts, job `pm.physics.glider`, group `glider`:

| Claim | Tolerance |
|---|---|
| `Seaglider default flight: horizontal speed` / `glide ratio (horizontal : vertical)` | 0.25 m/s and 3 within 15 % (Eriksen 2001; Kongsberg 25 cm/s). The model gives 0.228 m/s (lead's log) |
| `Seaglider dive: speed through water`, `climb ...`; `glide ratio`; `\|alpha\| (hd_a is per degree)` | 0.2 to 0.5 m/s; 1 to 5; 1 to 8 deg |
| `Seaglider steady state: \|sum of forces\| / \|B\|` | 1e-6 |
| `Seaglider speed: fixed-point iteration vs fsolve on the balance` | 1e-5 |
| `Seaglider: seawater compressibility minus hull abs_compress` | 0 to 1e-6 per dbar |
| `Seaglider: buoyancy gain 0 -> 1000 dbar at 15 degC (sign + : deeper = more buoyant)` | 2 % |
| `Slocum vs gliderflight 1.2.1 steady model, 24 shared states: max relative error in speed` (`vertical speed`, `angle of attack`) | 2e-3 (the oracle's own 100-point table); measured 8e-5 (lead's log) |
| `first descent time to the dive depth vs integral of dz/\|w\| (60 s steps)` | 2 % |
| `glider at 0.3 m/s vs uniform 0.5 m/s current: fraction of members losing station` / `... 0.1 m/s ...` | 1 and 0 (BRIEF 1.4) |
| `VBD pump energy, 300 cc against 1000 m` | 1172 to 7800 J |
| `metres per degree of longitude at 30 N` (and 0, 60; latitude) | 1e-5 |
| context `VBD pump energy at apogee, +-21 cc dive to 1000 m` | none (1066 J against 1172 J) |

The receipt anchoring the speed to Eriksen is on the **default flight state** the receipts define (dive and climb settings 150 cc either side of ballast, an assumed nominal), not
on the simulator's trim. Stage-1 speed through the ensemble is not validated against a glider mission.

---

## 10. USV (wing-sail, Saildrone Explorer class)

Code: `cafe/pm/physics/usv.py` (`_forces`, `_solve`, `through_water`, `through_water_table`, `_strip`, `added_resistance`, `USVSim`); `platforms/saildrone_explorer.yaml`.
Tests: `tests/test_usv.py`. Textbook citations in the module are by author, year and title; **chapter and equation numbers were not re-checked**, and formulas marked "recalled" in the
docstring are covered by receipts, not by a re-read. The oracle for the structure, Jouffroy's Simulink model named in the brief, was **not available**: the structure is checked by force-balance
residuals and limiting cases, not against his numbers.

### 10.1 Steady-state VPP

Fossen (2011) `M nu' + C nu + D nu + g = tau` for surge u, sway v, roll phi, yaw psi (Xiao & Jouffroy 2014), solved at `nu' = 0` in a mirrored frame in which the wind
relative to the water comes from starboard; unknowns per (true wind, heading): speed V, leeway beta, heel phi, wing depower k, rudder side force Y_r. Body axes x forward, y starboard.

```
apparent wind  w_a = w_ground - ( c + v_boat )            the current enters through the apparent wind; it is NOT added to a still-water answer (Sun et al. 2026)
wing    C_L = a_3 alpha for |alpha| <= alpha_stall,   a_3 = a_0 / (1 + a_0/(pi e AR)),  C_D = C_D0 + C_L^2/(pi e AR)              Prandtl lifting line; Sheldahl & Klimas 1981 section
        post-stall (Viterna & Corrigan 1982):  C_L = A1 sin 2a + A2 cos^2 a / sin a,  C_D = B1 sin^2 a + B2 cos a,  B1 = C_Dmax = 1.11 + 0.018 AR
        projected area x cos(phi); the self-trimming tail holds alpha = 'wing_trim_deg'; above the heel target alpha -> k alpha (depower)
hull    R = 1/2 rho V^2 S [ C_F (1 + k) + C_R0 (Fr/Fr_ref)^4 ] (1 + c phi^2),   C_F = 0.075/(log10 Re - 2)^2                  ITTC 1957; speed cap 3.3 m/s (Mazza et al. 2026, as quoted in BRIEF 2.4; equal to 1.34 sqrt(LOA ft) kn for the 7 m LOA, 3.18 m/s with the assumed 6.5 m waterline length)
foils   a = 2 pi AR/(2 + sqrt(4 + AR^2)) (Helmbold 1942; Hoerner & Borst 1975), AR doubled for the free-surface image, induced drag C_L^2/(pi AR),
        profile drag 2 C_F (1 + 2 t/c + 60 (t/c)^4) on planform area (Hoerner 1965)
roll    righting moment Delta g GM sin(phi) = heeling moment of the lateral force about the centre of lateral resistance
balance sum X = 0 by a root search on a 0.05 m/s speed grid; Y, heel, depower, rudder by 48 damped fixed-point iterations (review round 7, M-18: 24 left 58 cells at 27 to 30 m/s of wind off by up to 1.5 m/s; 48 agrees with 200 to 0.025 m/s)
```

- The still-water table (TWS 0 to 30 m/s, TWA 0 to 180 deg) is built once per parameter set (cached by a digest); because hull and keel see only the water and the sail only the air, the solution depends
  on `w - c`, so Stage 1 reads the table at the relative wind (`through_water_table`) and the direct solve (`through_water`) agrees with it: to 0.02 m/s at the five receipt states and to 0.2 m/s at 99.93 % of 20 000 seeded random states (99.55 % with a 2.5-degree angle axis). The exceptions sit at a true wind angle of 14 to 15 deg, where the speed itself steps from 0 to about 1 m/s and no linear table follows it (the largest gap is 0.91 m/s). The angle axis is 2.5 deg except 0.5 deg from 10 to 20 deg (89 columns, `usv.TWA`), and the receipts hold the fraction of 2000 seeded random states with a gap above 0.2 m/s to at most 0.25 % (0.1 % measured; review round 8, M-8). A `stw_cap_ms` off the 0.05 m/s search grid is interpolated on the grid's own step, so no cap gives a polar above it (M-12).
- **Where the polar has no root (review round 10, M-13, DECISIONS 358 and 547).** The polar is a fixed-point 4-DOF balance; where it has no positive-speed root the table holds V = 0 (a stall, existing behaviour), and the polar carries V and not the residual of the balance. Over the whole 0 to 30 m/s table 658 of 2759 cells are V = 0 (the calm row included) and 56 more are at or under 0.2 m/s; every one of the 2045 cells above 0.2 m/s balances to a sway and yaw residual of 2.1e-4 or less, while 12 of the 56 weak cells (8 of them at 1 m/s of wind, TWA 14.5 to 18 degrees: the interpolated root next to the upwind stall, where the apparent wind is under `trim_min_aws_ms`) carry a residual above 0.05. The lowest wind speed at which a wind angle stalls after the boat had been moving is 17 m/s at TWA 15, 26 m/s at TWA 30 and 30 m/s at TWA 45 (22 wind angles, from 14.5 to 45 degrees, stall; from 47.5 degrees the polar never stalls after moving). The best heading is at the 3.3 m/s cap from 15 m/s (3.26 at 14 m/s), so a flown route avoids these cells (q10 has `capsize_proxy` 0), but Stage 1 cannot tell a stalled cell from a calm. `usv.stall_map(P)` reproduces these figures and `tests/test_usv.py` pins them; no residual layer is added and the solver is unchanged.
- **Fits.** Two numbers are fitted, each to one target and neither checked against the other (review round 7, M-4). `appendage_cda_m2` was raised from 0.02 to 0.04 so that the best-heading speed at 12 m/s on the polar *without* the VPP bias matches Chiodi et al. 2021 (2.9 m/s). `vpp_bias_mean` is solved so that `usv.mean_sog` gives exactly the 5.4 m/s mean SOG / wind of 0.96 / 5.4: a closure, not a reproduction. Stage 1 flies the polar times (1 + `vpp_bias_mean`), which is 2.215 m/s at 12 m/s, 24 % under 2.9; no single bias meets both targets because the polar is capped at 3.3 m/s (3.3 x 0.7578 = 2.50 m/s < 2.9). Both receipts are labelled `CALIBRATED` and are calibrations, not validations (limitation L02).
- Wave added resistance, Gerritsma & Beukelman 1972 in the form of Journee & Massie 2001, by closed-form strip theory (21 sections, coupled heave and pitch with sectional added mass `rho pi b^2/8`):

```
R_aw = (k / 2 w_e) int b'(x) |V_z(x)|^2 dx,   b' = rho g^2 A^2 / w_e^3,   A = 2 sin(k_e b/2) exp(-k_e d)             (Journee & Massie; equation number not checked)
spectrum: Bretschneider S = (5/16) Hs^2 wp^4 w^-5 exp(-1.25 (wp/w)^4);   R = 2 int S R_aw/zeta_a^2 dw = Hs^2 G(Tp, chi, U),   tabulated (Tp 3-21 s, chi 0-180, U 0-3.5 m/s; outside the table the value is clamped to the table's edge, and `stw_cap_ms` is bounded to 3.5 m/s, `usv.WAVE_U_MAX`, so the speed axis is never clamped; review round 10, M-17)
oblique seas: R_aw x max(-cos chi, 0)                       no source (zero in following and beam seas)
Stage 1 lowers the speed by R_aw/K, K = -dX/dV at the root (first order)
```

  Capytaine (3-D BEM) was **not used**: a 7 m slender hull follows waves longer than about 30 m, and a BEM call per (omega, heading, speed) would dominate the build.
  Regime of validity (review round 7, M-19): added resistance is linearised about the calm speed, where it is smallest (it is largest at rest and falls with speed). Where R_aw(0) exceeds the thrust X(0) (short steep head seas: Hs 2 m, Tp 6 s, TWS 6 m/s, TWA 90 deg gives R_aw = 312.6, 207.9, 155.6, 129.3 N at 0, 0.5, 1.0, 1.554 m/s against X(0) = 105.5 N), the model's own equation X(V) = R_aw(V) has no positive root, the true speed is zero, and the model reports 1.554 - 129.3 / 131.8 = 0.573 m/s. Within modest seas the first-order speed is within 3 % (Hs 1 m, Tp 8 s: 1.475 against 1.470 m/s; reviewer's figure, not re-run). A root find per table cell would be a model change and is not made (DECISIONS 359, limitation text in `docs/CREDIBILITY.md` section 5).
- Capsize proxy: `peak = steady heel + sigma_phi sqrt(2 ln N)` (Longuet-Higgins 1952, N = 100 cycles), `sigma_phi` from a 1-DOF roll response at the peak period to the wave slope `k Hs/4 |sin chi|`; fires above 45 deg (**assumed**, a knock-down flag, not a capsize angle).

### 10.2 Stage-1 kinematics (`USVSim`)

Every `replan_s` the heading is chosen from 72 candidates to maximise velocity made good: `g = V(trk) + (current + Stokes drift)`; speed = `min( max(V_polar - R_aw/K, 0) (1 + bias), 3.3 m/s )`.
A tack costs `V t_tack` of distance and is taken only if the VMG gain over `tack_horizon` repays it; on a section only headings that reduce the cross-track error are allowed outside the corridor.
`bias` is the member's `usv_vpp_bias` draw (uniform on [-0.2565, -0.2280], the Chiodi-calibrated prior; the brief's [-0.35, -0.30] runs as the sensitivity case `usv_vpp_bias_brief`); the platform's own N(-0.2422, 0.0082) default (`vpp_bias_mean`, `vpp_bias_sd` in `platforms/saildrone_explorer.yaml`) is used only when a caller passes none, and Stage 1 passes the perturbation draw.
Mission speed against wind (review round 2, M-2): per member Stage 1 stores the mean speed over ground (`stage1.path_speed`, review round 3, M-7: the sum of the segment lengths of the stored 10 min records over the time they span, on the sphere of radius `usv.R_E`; it is the one definition of speed over ground, used by the speed block, the ratio line and the calibration run `usv.mean_sog` (the reach map swims at the speed through the water instead, below), and it includes the ocean SDE's steps that the simulator's `path_m` leaves out; the ratio line of the report is the median of the per-member ratios and is printed beside the median speed over the median wind, since the quotient of two medians is not the median ratio), the mean 10 m wind along the track and at the anemometer height, and their ratios (`vehicles[usv].speed`: `sog_ms`, `u10_ms`, `wind_anem_ms`, `ratio`, `ratio_anem`, their medians and `calibration_ratio` = Chiodi's 0.96 / 5.4 = 0.178). The nominal diagnosis scenario of review round 2 (a single nominal run, not the ensemble) gave a ratio of 0.120 (0.125 at the anemometer height), against the 0.178 the bias is calibrated to in a scenario without current, in uniform wind, sailing to a station; the q5 ensemble's median ratio is 0.129 per 10 m wind and 0.135 per wind at the anemometer height (review round 5, M-26). Chiodi's 0.178 is defined at the anemometer height, so 0.135 against 0.178 is the like-for-like gap (24 % short), and 0.129 is the secondary figure the report prints in brackets (review round 9, M-7, DECISIONS 467). Adding the mission's effects one at a time in that nominal scenario: wind field alone 0.186, plus waves 0.180, plus current 0.150, all together 0.120. The current costs a third of the speed, all of it from the westward South Equatorial Current (mean |c| 0.33 m/s): the course changes from a beam reach with a leeward set to close-hauled (true wind angle 85 to 45 deg) and the speed through the water falls from 1.1 to 0.72 m/s. Track holding costs little (0.127 opened against 0.120 in the nominal scenario). The current is counted once. No model fault was found and the prior was not retuned. Whether Chiodi's 0.178 was itself observed in real currents is not known; if it was, the current is penalised twice (limitation L18, QUESTIONS_FOR_LAB 14). Reach map (review round 4, M-7, DECISIONS 243): Stage 1 also stores each member's mean speed through the water (`stw_ms`, 0.72 m/s median in the demo against 0.66 m/s over ground), and the report's reach map swims a USV at that median, because the router adds the current itself; the page says "through the water". A summary without `stw_ms_median` falls back to the speed over ground, labelled "over ground". A glider's reach map uses the mean current over six levels from 5 m to the task's `dive_depth_m` (950 m or 500 m in the demo; it was 5 to 100 m) and the page names the band.
Flags: `no_current_data` (review round 4, M-5 and round 6, M-1: a non-finite wind, current or wave state (Hs, Tp, direction or Stokes drift; the UMWM sea-mask holes), e.g. a land block of the ocean store, is replaced by zero for that step (Hs 0, Tp the wave table's first period, direction 0, Stokes 0) and fails the member, as the glider's `no_current_data` does for a non-finite current at any member or wind at a surfaced one (a hole in the input; it was labelled `no_flight`, a failure of the flight model, before review round 8, M-14) (since review round 7, M-16, a non-finite shortwave value too: 0 W of sun for that step, flagged from the end of the step in which it was read, and a non-finite start position, flagged at t = 0 and started at (0, 0)); before round 4 a non-finite current was an IndexError; the wave state is covered since round 6, M-1, where Hs alone passed silently as a NaN position and Hs with Tp was an IndexError), `becalmed` (the best through-water speed over all headings is at most the current speed (`<=`, so a boat that cannot move in a zero current is becalmed) for `becalmed_after_h`; the literal "SOG below current" cannot fire because a drifting boat's SOG equals the current),
`swept_off_track`, `capsize_proxy` (also fired when the wind relative to the water stays above the polar's top, 30 m/s, for `stall_sustain_s`: outside the model, so a failure, not a pass; review round 7, M-20; the polar clamps at 30 m/s), `wing_stall_calm` (apparent wind speed below the tail's authority, `trim_min_aws_ms`, for `calm_sustain_s`), `wing_stall_angle` (apparent wind angle inside the bow cone, `min_awa_deg`, for `stall_sustain_s`, and only while the apparent wind speed is at or above `trim_min_aws_ms`: below it only `wing_stall_calm` counts, because the table's angle at an apparent wind under 1.5 m/s is the sign of a zero (review round 10, M-10, DECISIONS 544); this is not the wing's stall angle of attack `wing_stall_deg`, which only the polar uses), `battery` (solar gain `eff x area x SWDOWN`, 0 W where SWDOWN is not finite, minus hotel load).
Every flag of a step carries the time at its end, a hole in the wind, current or wave state included (review round 9, M-27, DECISIONS 487); only a start position that is not finite carries t0. A waypoint equal to the one before it is dropped (`physics.drop_repeats`, review round 9, M-13), so a section of identical points is the station.
The two calm clocks differ on purpose (review round 3, M-8): `wing_stall_calm` fires after 30 min (`calm_sustain_s` 1800 s, assumed) below 1.5 m/s of apparent wind, when the wing is untrimmed and the vehicle has no drive; `becalmed` is about drifting with the current and needs 6 h (`becalmed_after_h`, assumed). `min_awa_deg` (15 deg, assumed, no source) is the bow cone; the polar still gives positive speed inside it (0.545 m/s at TWS 6 m/s, TWA 15 deg). The report states the clocks when either calm mode occurred.
In `station` mode a USV's `task.radius_km` is its swept-off-track distance (`track_tolerance_km`, unless the task also gives that key): a member farther than that from `(lon, lat)` fails `swept_off_track`.

Receipts, job `pm.physics.usv`, group `usv`:

| Claim | Tolerance | Note |
|---|---|---|
| `ITTC-1957 C_F at Re = 1e7` | 1e-12 | closure |
| `hull speed 1.34 sqrt(LOA ft) kn vs the 3.3 m/s cap` | 4 % | Mazza et al. 2026 Part 1, as quoted in the brief |
| `mean SOG / U at 5.4 m/s (VMG routing, all bearings, prior bias; CALIBRATED: vpp_bias_mean)` | 25 % band (assumed) | 0.1778 against Chiodi's 0.1778: a closure (`vpp_bias_mean` is solved to give it); bias 0 gives 0.2345 (+31.9 %), -0.30 gives 0.1643 (-7.6 %), -0.325 gives 0.1584 (-10.9 %), -0.35 gives 0.1525 (-14.2 %) |
| `best-heading still-water speed at 12 m/s, polar without the VPP bias (CALIBRATED: appendage_cda_m2; not what Stage 1 flies)` | 10 % | **fit**; 2.92 against 2.9 m/s |
| `best-heading speed at 12 m/s as Stage 1 flies it (polar x (1 + vpp_bias_mean))` | 25 % (`chiodi_band`) | 2.215 against 2.9 m/s (23.6 %); passes only because the band is wide; no single bias meets this and the 5.4 m/s mean (the polar is capped at 3.3 m/s) |
| `no (TWS, TWA) in the polar exceeds the hull-speed cap` | exact | |
| `apparent wind speed = \|true wind - boat velocity\| (max relative error over 9 states)` | 0.01 | |
| `SPURS-2: swept_off_track first fires (h)` / `becalmed first fires (h)` / `fraction of members that fail both ways` | 1 to 12 h / 6 to 12 h / 1.0 | Zhang et al. 2019 as quoted in the brief (0.2 m/s wind, 0.9 m/s current); reproduced for 16 of 16 members |
| `still-water VPP + current / current-coupled SOG (6 m/s wind, 0.5 m/s current with it)` | 1.01 to 1.8 | fixes the sign and order only |
| context: `same, speed through water only (published 30-35 % for SOG)`; `4 m/s wind, 0.8 m/s current with the wind, speed through water`; `SOG ratio with the current against the wind` | none | |
| `Stage-1 table == direct current-coupled solve (max \|dV\|)` | 0.02 m/s | |
| `sway force balance residual at the root (max \|Y\| / force scale)` | 0.05 | |
| `strip theory, long head waves: heave RAO` / `pitch / (-i k), bow down positive` | 1 +- 5 % | long-wave limit |
| `Bretschneider m0 = Hs^2 / 16 (Hs = 1)` | 1 % | |

**The Sun et al. 2026 magnitude is not reproduced.** Superposition overpredicts by 8 to 26 % in these cases against the published 30 to 35 %; the direction (superposition overpredicts when the
current runs with the wind) is. Limitation L03. Most hull and wing numbers are assumed (`platforms/saildrone_explorer.yaml`); several sources are "(recalled)" and flagged there.

---

## 11. UAS (quadrotor, flux-profile sorties)

Code: `cafe/pm/physics/uas.py` (`_dyn`, `_ctrl`, `_batt`, `_block`, `simulate`, `fly_sortie`, `fly_sitl`); `platforms/quad_uas.yaml`; forcing assembled in `stage1._run_uas`
and `_uas_forcing`. Tests: `tests/test_uas.py`. World ENU, body FLU, z up; arrays are components-first `(3, M)`; float32 in JAX.

```
p' = v,   v' = -g z_W + c z_B - R D R^T ( v - wind ),   R' = R [w]x,   J w' = tau - w x J w                         Faessler, Franchi & Scaramuzza 2018, IEEE RA-L 3(2), Eq. 2
c = sum T_i / m;   D = diag(d_x, d_y, d_z) = (0.544, 0.386, 0) 1/s  (the paper's circle-trajectory fit; sourced)
the paper has no wind: the air-relative velocity v - wind is OUR extension (a rotor drag is a force of the air on the rotors)
rotors: T_i = kT omega_i^2,  shaft power kQ omega_i^3,  kQ = kT^1.5 / ( sqrt(2 rho A) FM )  (momentum theory, figure of merit)       Leishman 2006 Ch. 2
        first-order lag 33 ms (NeuroBEM, Bauersfeld et al. 2021); kT scales with rho/rho_ref; electrical P = kQ omega^3/eff + hotel
battery: Peukert, I^P with P = 1.05, open-circuit curve, I R sag; I from  P = V I  in closed form
controller: position (sqrt controller) -> velocity PI -> thrust vector -> geometric attitude -> rate loop -> mixer, ArduCopter default gains where sourced
multirate: rigid body and rate loop at 2.5 ms; wind lookup, guidance and velocity loop at 50 ms (zero-order hold)
```

- Airframe NeuroBEM 0.772 kg, J = diag(0.0025, 0.0021, 0.0043) kg m^2 (data-set page). The drag fit of the Faessler paper comes from a **different airframe**; the linear drag is used to 12 m/s.
- **The propulsion curve is parametric** (limitation L11): `T = kT omega^2`, `P = kQ omega^3`, with the maximum static thrust 33 N (4 x 8.25 N, sourced), `omega_max` 30 000 rpm (**assumed**),
  figure of merit 0.60 (**assumed**; 0.4 to 0.65 band "recalled, not re-read"), ESC and motor efficiency 0.80 (**assumed**), battery 60 Wh (**assumed**, sized so a 20 min sortie lands near 30 % state of charge;
  the note in the yaml says the NeuroBEM airframe cannot physically carry it). No dyno curve and no thrust loss with forward speed.
- Sorties: launched at `local_solar_time` (UTC + lon/15 h) every `every_days`, from the ship on station; mission altitudes, duration and launch rules override the platform's. Launch gate: scrub if the mean
  wind at flight height over the sortie exceeds 12 m/s, or a gust front is active at the ship within 15 min. Pattern: stacked legs upwind, climbing at the ends, then return and land.
  Flags: `battery_reserve`, `wind_exceeds_airspeed` (no headway for 10 s while commanding more than 1 m/s), `attitude_exceedance` (tilt 7 deg beyond the 35 deg limit, i.e. 42 deg; **it cannot fire in this controller model**: the commanded horizontal force is clamped at g tan 35 deg, so the tilt stays at 35.00 deg (96 of 96 q2 sorties); limitation L17, review round 2 M-28), `lost_link` (Stage 1 passes the UAS-to-ship RF budget as the link callback, judged once per second; the link must be lost for `radio.link_loss_hold_s` = 5 s in a row, assumed from ArduCopter's GCS failsafe timeout, recalled not re-read, and the flag's time is where that run began, so the 50 ms fade of a smooth-sea two-ray null is ridden through; review round 4, M-10), `profile_incomplete`, `no_current_data` (review round 9, M-3, DECISIONS 463: a wind vector that is not finite at a flying member, in the mean from the store or in its turbulence and gust, flags the member from the end of that 50 ms block and it flies on zero wind from then on, so its battery, tilt and track stay finite; the flag is kept, a member that is down or scrubbed is not flagged, and a ship whose air state is not finite scrubs the launch, as a ship with no finite wind does; the sixth and last entry of `uas.FLAGS`) and `no_sortie_flown` (every launch scrubbed).
  The sortie ends its pattern early when the airborne time exceeds `duration_s x time_limit_factor` (the return-to-ship failsafe, 1200 s) or the state of charge falls below the reserve. Every flown sortie reports the waypoints it reached (`wp_done`) of the pattern (`n_wp` = 2 x levels, 8 in the demo); below `sortie.min_profile_fraction` (1.0, assumed) the member records `profile_incomplete` at the end of the sortie (review round 4, M-1). The nominal pattern takes 1127 s of flight, so a 1200 s timer leaves 6 % slack: in a uniform wind the pattern is complete up to about 5.2 m/s (10 m value, log profile) and ends at 7 of 8 waypoints from 5.5 to 6.5 m/s, 6 at 7 and 5 from 7.5 to 9 m/s (probe, one member per wind, no turbulence). The UAS verdict therefore rests on the battery and on finishing the profile inside the time limit. A non-finite wave height on the link track is the same member's last finite Hs, then the next (counted in the ledger; a member with none stops the run): Hs 0 would be a glass-calm sea, the deepest two-ray null.
- Wind: the mean wind from `env.wind` is looked up every 1 s (20 blocks) and held; turbulence (section 5.1) and gust fronts (5.2) are added at 50 ms. The Mann series are built from the fewest boxes that fit.
- ArduCopter SITL (JSON backend, ArduPilot 4.7.x) flies the same physics in lockstep for a few members (`fly_sitl`; no pipeline stage calls it, it runs only as the slow receipts, so `plan.json` says `sitl_members` 0 for every budget, review round 6, M-3); the firmware is told it is at Canberra (`SITL_HOME`) because its compass and EKF
  misbehave at the equator; only metres from home are used. The app's stored SITL cross-check (`runs/crosscheck.json`) and its stored CFD results are optional inputs that count as receipts only when they carry a stamp of the current code (`cafe.receipts.stamp`: date, host, git sha and the digest of `cafe/*.py`); `python -m cafe.receipts stamp FILE` stamps one somebody has checked, and any other is a context row (review round 12, M-35, DECISIONS 675, 678).

Control authority (review round 2, M-28): per sortie Stage 1 records the seconds the horizontal-force demand was beyond the lean-angle clamp (`sat_s`) and the largest demand / clamp ratio (`demand_ratio_max`); the stage-1b summary carries their median and maximum over the unscrubbed sorties under `vehicles[uas].authority` (`clamp_s_median`, `clamp_s_max`, `demand_ratio_median`, `demand_ratio_max`). A probe in a uniform wind found the demand beyond the clamp in every sortie from about 6 m/s of wind, so a threshold on it would flag them all and separate nothing: no failure mode `authority_saturated` was added; the diagnostic is printed and does not fail a member. The UAS verdict therefore rests on the battery and on finishing the profile inside the time limit (q6: 55 of 64 members `profile_incomplete`, 6 `battery_reserve`); above about 12 m/s of wind the launch gate scrubs the sortie (review round 6, M-25).

Uncertainty: per-member scales on battery capacity (lognormal 0.05, **assumed**) and drag (Stage-3 refit); wind error and turbulence through the environment. The turbulence and gust draws are per batch (Known issues). Stage 1 also stores the share of the sorties' wind points the WRF 3-D fields answered (`vehicles[uas].wind3d_fraction`, `GriddedEnv.use_3d`; the 3-D hours exist only for the ingested hours).

Receipts, job `pm.physics.uas` (fast) and `pm.physics.uas.slow` (SITL and the 20 min sortie; 10 min, stored per code digest):

| Group | Claim | Tolerance |
|---|---|---|
| `UAS propulsion` | `hover thrust equals weight` | 1 % |
| | `hover figure of merit from simulated thrust and power vs the identified FM` | 2 % (closure of the identity) |
| | `hover figure of merit inside the small-rotor band` | 0.40 to 0.70 |
| | `mechanical hover power ratio of a 25 % heavier member` | 2 % of 1.25^1.5 |
| `UAS rotor drag` | `steady tilt forward at 8 m/s: atan(d v / g)` (also forward 4, sideways 4 m/s) | 3 % |
| | `hover in an 8 m/s wind leans as far as flying 8 m/s in still air` | 4 % |
| | `hover in a wind blowing east leans west (into the wind): z_B east component` | -1.0 to -0.2 |
| `UAS battery` | `discharge time at 2 A vs Peukert t = H (C/(I H))^P`; `discharge time ratio 2 A : 6 A vs (6/2)^P` | 1 % |
| `UAS time step` | `energy of a 40 s climb + leg at 2.5 ms vs 1.25 ms` | 0.5 %; context: position difference 0.048 m |
| `UAS sortie` | `still-air sortie, launch to touchdown` | 0.95 to 1.05 x 1200 s |
| | `state of charge at touchdown is above the reserve and the pack was used` | 0.2 to 0.6 |
| `UAS SITL vs our controller` | `SITL holds the leg end (median distance from it while there)` / `our controller holds the same leg end` | 4 m / 3 m |
| | `mean electrical power while holding the leg end, SITL vs our controller` | 15 % |
| | `SITL completes the descent (touchdown height above the deck)` | -0.5 to 0.5 m |
| | context: `SITL touchdown, horizontal distance from the ship [m] ...` ; `ArduPilot's tilt estimate vs the attitude we sent ...` ; `SITL members run (0: binary absent, ...)` | none |

**The SITL return and landing are unreliable.** The firmware's EKF drifts on the return (touchdown 4 m to 160 m from the ship in 4 trials, per the row text), so only the
completion of the descent is a pass/fail row and the distance is context. Limitation L10.

---

## 12. Comms

Code: `cafe/pm/physics/comms.py`; `platforms/radios.yaml`, `modems.yaml`; use in `stage1.evaluate_link`. Tests: `tests/test_comms.py`.

### 12.1 RF: two-ray over the sea

```
E / E_free = | 1 - rho_s D (r1/r2) exp( -j 2 pi (r2 - r1)/lambda ) |,   r1 = sqrt(d^2 + (ht - hr)^2),  r2 = sqrt(d^2 + (ht + hr)^2)        reflection coefficient -1 (grazing, smooth; the error against the Fresnel coefficient is stated below); plane earth: D = 1
L = 20 log10( 4 pi r1 / lambda ) - 20 log10( |E/E_free| )                                                        path loss
rho_s = exp[ -2 (2 pi sigma_h sin(psi)/lambda)^2 ],   sigma_h = Hs/4,   sin(psi) = (ht + hr)/r2                      Ament 1953; Beckmann & Spizzichino 1963
margin = P_t + G_t + G_r - cable - misc - L - sensitivity;     -200 dB beyond the 4/3-earth horizon  d_max = 4.12 (sqrt(ht) + sqrt(hr)) km          ITU-R P.834
```

Curved earth (review round 4, M-8, DECISIONS 244). Two-ray over a 4/3-radius earth (a = 8 495 km): the specular point is the root of the cubic 2x^3 - 3dx^2 + (d^2 - 2a(ht + hr))x + 2a ht d = 0 (Kerr 1951, trigonometric form), R1 = x from the ht antenna; the antennas' heights above the tangent plane there are h1 = ht - R1^2/2a and h2 = hr - R2^2/2a; the direct and reflected path lengths are hypot(d, h1 - h2) and hypot(d, h1 + h2); the reflected field carries the reflection coefficient -1, the Ament roughness factor and the divergence factor of the spherical surface D = [1 + 2 R1 R2/(a d sin psi)]^-1/2 [1 + 2 R1 R2 sin psi/(a d)]^-1/2 (Kerr 1951; Blake 1980 ch. 5). Within 2 km the curved and the plane-earth loss agree between interference nulls and differ at them (review round 8, M-49; the 0.15 dB this sentence gave held for single distances and the ship-to-USV geometry only): the largest difference for d = 100 to 2000 m at 915 MHz, Hs 0, sampled every metre, is 0.8 dB for a surface pair (ht 2.2 m, hr 10 m), 26 dB for the UAS at the top of its profile (ht 2.2 m, hr 108.1 m) and 20 dB for ht 10 m, hr 18.1 m (29 and 34 dB sampled every 5 cm); with Hs 1 m it is 2.4 dB and with Hs 3 m 0.3 dB for that last pair. The nulls move by a fraction of a wavelength between the two geometries; the lost-link time of a UAS sortie is the statistic that depends on it. D falls to 0 with the grazing angle psi, so toward the horizon the reflected ray fades out and the curved loss tends to free space; with D the plane-earth model is pessimistic beyond about 10 km, not optimistic (the review's curved table without D, 9 to 40 dB more loss than flat, has the opposite sign). Geometric optics is not trusted below psi_c = (lambda / pi a)^(1/3) (2.3 mrad at 915 MHz; **ASSUMED**, recalled from Kerr / Blake, not re-read): from there to the radio horizon the loss is the larger of the curved loss and the plane-earth loss, which is conservative; beyond the horizon `rf_margin` reports no link. No smooth-earth diffraction (ITU-R P.526, the upgrade path) is modelled in that zone. For 15 m / 3 m masts at 915 MHz, Hs 0, the limit is at 6.9 km of a 23.1 km horizon, and the loss at 5 / 10 / 15 / 20 / 22 km is 115.7 / 127.7 / 134.0 / 139.0 / 140.6 dB (plane earth 114.9 / 126.9 / 134.0 / 139.0 / 140.6; curved with D 115.7 / 127.7 / 125.8 / 122.4 / 120.9). `rf_margin(20 km, 15 m, 3 m, Hs 0)` is +13.0 dB. The d^-4 receipt is the plane-earth law (`a_eff` = 1e12 m). References: Kerr, D.E. (ed.), Propagation of Short Radio Waves, MIT Rad. Lab. Series 13, 1951, ch. 2; Blake, L.V., Radar Range-Performance Analysis, 1980, ch. 5.

Specular only (the rest of this subsection is the plane-earth form, which the curved model reduces to within 2 km): diffuse scatter is neglected, so null filling is underestimated; antenna motion with the waves is not modelled (the roughness term stands in). Antenna gain 2 dBi and 3 dB misc loss
are **assumed**; the 900 MHz sensitivity is the datasheet's lowest-rate value. `two_ray_loss_db` gives the roughness factor the grazing angle `arctan2(ht + hr, d)`, whose sine is the `sin(psi)` above (review round 3, M-14: it used to pass `sin(psi)` to a function that sines its argument). The member's own Hs (perturbed) feeds the roughness; for an RF link between two nodes it is, at each moment, the larger of the Hs at the link's two ends (`stage1._link_hs`; review round 12, M-11, DECISIONS 651), the conservative one, so the margin does not depend on which end the mission names first (with Hs 0.2 m at the ship and 3 m at the USV the two namings differed by 0.3 dB at 3 km), and the ledger's `hs_filled` counts the filled samples of both ends. On the demo the change is at most 5.3e-4 dB in any sample of the usv-uas-rf margin. The antenna height of an aircraft is deck + flight altitude + 0.1 m.

**The reflection coefficient -1 and the Fresnel coefficient** (review round 12, M-12, DECISIONS 652; documents only, the model is unchanged). -1 is the limit of the Fresnel coefficient G of a vertical-polarised wave on sea water as the grazing angle goes to 0 and a smooth-sea idealisation everywhere else; the earlier text, "valid below 1 to 2 deg", was wrong. For sea water at 915 MHz with eps_c = 72.8 - j118.9 (T 29 C, S 35, sigma 6.05 S/m, which gives the eps'' = 60 lambda sigma = 118.9 quoted: **assumed**, the lab has given neither the sea temperature nor the antenna polarisation, QUESTIONS_FOR_LAB 12a) the magnitude of G is 0.98, 0.91, 0.84, 0.70, 0.49, 0.35, 0.26, 0.49 and 0.65 at 0.05, 0.25, 0.5, 1, 2, 3, 5, 12 and 20 deg, and its phase is -179, -168, -154 and -86 deg at 0.05, 1, 2 and 5 deg (pseudo-Brewster angle 4.85 deg, magnitude 0.26): -1 is within 10 % of the magnitude only below about 0.3 deg (`tests/test_comms.py::test_r12_m12_*` recomputes the table). The demo's grazing angles (UAS 18 to 108 m, whip 2.2 m) are 1.2 deg at 1 km and 0.2 deg at 5 km for the 18 m UAS and 6.3 and 1.3 deg for the 108 m UAS, and 2 to 30 deg for the UAS-ship hook inside a sortie (|G| is 0.26 at 5 deg and 0.65 at 20 deg), so -1 is within 10 % of the magnitude from about 4 km out for the 18 m UAS (0.3 deg at 3.9 km, flat earth) and from about 21 km for the 108 m UAS, and not inside those distances. Error band of the margin against Fresnel, as the reviewer measured it (a script run outside the repository with this module's geometry and G(psi) in place of -1, which with -1 reproduces the function to 0.0 dB; the margin sweeps were not re-run when this was written): the -1 model is optimistic at interference peaks by up to 7.6 dB and conservative at nulls; on the mission link (UAS to USV, 0.2 km to the horizon) the Fresnel margin is 7.4 dB lower to 23.6 dB higher at Hs 0.5 m and 2.8 dB lower to 6.9 dB higher at Hs 1.5 m, on the hook (0.05 to 6 km, Hs 0.5 m) 7.5 dB lower to 34.7 dB higher, and no sample changed its sign. No verdict of the demo rests on it (usv-uas-rf is NO-GO because 88.85 % of its needed moments are beyond the radio horizon, `frac_beyond_horizon` 0.88848 in q12, and the UAS lost-link mode is 0 of 64), but a link whose budget is within about 8 dB at a peak is not decided by this function. A Fresnel function in place of -1 inside `two_ray_curved_db` would move every printed RF margin, the goldens and the parameter-file hashes, and needs a sea temperature and salinity from the lab.

### 12.2 Acoustic: Thorp and Stojanovic, Bellhop for the ambiguous links

```
Thorp (1967), f in kHz:  alpha = 0.11 f^2/(1+f^2) + 44 f^2/(4100+f^2) + 2.75e-4 f^2 + 0.003   dB/km         as printed in Stojanovic 2007 eq 4
TL = k 10 log10(r / 1 m) + alpha r_km,   k = 1.5 (practical spreading; 1 cylindrical, 2 spherical)             Stojanovic 2007 eqs 1-3
N(f) = turbulence + shipping + wind + thermal, power sum, PSD in dB re 1 uPa^2/Hz     (Stojanovic 2007 eqs 6-10, after Coates 1989); in-band by trapezoid in the power domain
margin = SL - TL - NL - SNR_req - L_impl (+ excess)
L_impl = SL - TL(r_vendor) - NL(ref wind 5 m/s) - SNR_req - 3 dB       derived so the budget closes at the vendor's published range with 3 dB to spare
```

- **The 4 km mid-frequency range is true by construction** (limitation L01): `L_impl` is derived from the vendor's `>= 4 km`; `SL = 190 dB` and `SNR_req = 10 dB` are **assumed** and cancel. The 6 and 8 km rows test the
  shape only. At 10 m/s wind the MF margin at 4 km is -3.9 dB. The Micro-Modem bands copy the Benthos MF implementation loss (**assumed**).
- Bellhop (Porter 2011; Acoustics Toolbox at_2026_10_27, built by `bench/install_bellhop.sh`) runs only where the Thorp margin is within +-6 dB of zero, on a 48-point range grid, interpolated. It enters as an
  **excess**: TL on the sound-speed profile minus TL on an isovelocity column, added to the Thorp TL. An absolute Bellhop TL would double-count the spreading, because `L_impl` is anchored under k = 1.5 and deep isovelocity
  water is k = 2. Consequence: k = 1.5 is optimistic against Bellhop's deep isovelocity answer. When Bellhop is absent the link is labelled "Thorp only, Bellhop unavailable".
- Sound speed from TEOS-10 via the ocean store.
- The wind of the noise term is, at each moment, the larger of the 10 m wind at the link's two ends (`np.fmax`: a non-finite wind at one end is the other end's), so the margin does not depend on the order of the ends (review round 12, M-11, DECISIONS 651); the demo's acoustic links have no finite margin, so no demo number moves.
- **Slant range, valid range, Bellhop per member.** The Thorp budget uses the slant range hypot(r, dz), not the horizontal distance. `margin_db` is NaN wherever it is not a budget: beyond the radio horizon, beyond
  `valid_range_m = valid_range_factor x` the vendor range (`valid_range_factor` is **assumed**, 10, in `modems.yaml`), at samples the link does not need, and for Iridium. Summaries report `margin_db_median` over the valid
  samples, with `frac_beyond_horizon` and `frac_out_of_range`. Bellhop refines the needed acoustic samples inside the `ambiguous_db` band one member at a time, on the `env.sound_speed` profile (GOFS T/S, TEOS-10) at the
  midpoint of the member's middle ambiguous sample, with the GEBCO depth there. One profile and depth pair per member and link is a stated simplification. Without Bellhop or a profile the label says "Thorp only".

### 12.3 Iridium

SBD message of n bytes = ceil(n/340) sessions; each session retried up to 3 times; per-attempt success 0.95; set-up time log-normal (median 10 s, log sigma 0.6); transfer 5 s (short) to 20 s (full message), published nominal;
a failed attempt costs 60 s. **All of the success, retry and set-up numbers are assumed** (no published statistic found); latency and availability only, no range dependence (BRIEF 2.8). Stage 1 draws one session per
10-minute moment, independently. A glider's radio and Iridium antenna work only at the surface: `load_mission` refuses an rf or iridium link with a glider end unless `when: surfacing`, and Stage 1 requires an Iridium link with `when: surfacing` only at the records where the glider end is surfaced (review round 4, M-11, DECISIONS 247).

Receipts, job `pm.physics.comms`, group `Comms`:

| Claim | Tolerance |
|---|---|
| `Two-ray far field: loss rise per decade of range` | 40 dB +- 0.05 (the d^-4 law) |
| `Two-ray last null for ht=2 m, hr=5 m at 915 MHz` | 1 % of 2 ht hr/lambda |
| `Rough sea (rho=0) collapses to free space at 1 km, 915 MHz` | 0.2 % of the Friis formula |
| `Ament factor when 4 pi sigma sin(psi)/lam = 1` | 1e-9 of exp(-1/2) |
| `Radio horizon of a 2 m antenna` (5 m; `between 2 m and 5 m antennas`) | 0.2 % |
| `Thorp absorption at 10 kHz` / `... is ~1.1-1.2 dB/km` | 0.1 % of 1.187; 1.1 to 1.2 |
| `Stojanovic noise-PSD minimum (calm, 0 m/s wind) lies at tens of kHz` | 10 to 100 kHz |
| `Wind noise at 10 kHz rises with 7.5 sqrt(w): 10 vs 0 m/s wind` | 1 % |
| `Benthos ATM-960 MF margin at 4 km, 5 m/s wind` (and 6 km, 8 km) | 0 to 30, -30 to 0, -60 to 0 dB: **closure** at 4 km, shape at 6 and 8 |
| `Benthos LF margin at 6 km and HF at 2 km, 5 m/s wind (the smaller)` | 0 to 30 dB (also an anchor) |
| `Bellhop vs Thorp (k=2, -3 dB image) isovelocity TL, 11.5/18.5/24.5 kHz, 0.5-6 km: worst \|difference\|` | below 3 dB (only with `bellhop.exe`; otherwise a context row `NOT RUN`) |
| `Iridium SBD success after retries` | 2e-4 of 1 - 0.05^3 (a binomial identity of the assumed numbers) |
| `Iridium SBD median latency of a 100 B message` | 15 to 40 s |
| context `Benthos ATM-960 MF margin at 4 km in 10 m/s wind ...` | none |

The RF and Iridium parameters are not validated against measured ranges or SBDIX logs; the lab's logs are the stated replacement.

---

## 13. Statistics

Code: `cafe/pm/stats/{intervals,sampling,sequential,sensitivity,rare}.py`, `cafe/pm/emulator.py`, used by `stage1.py`. Tests: `tests/test_stats.py`, `tests/test_emulator.py`.

### 13.1 Intervals and the verdict (`intervals.py`)

```
Wilson (1927):       centre = (p + z^2/2n)/(1 + z^2/n),  half = z sqrt( p(1-p)/n + z^2/4n^2 )/(1 + z^2/n);  ends exact at k = 0 and k = n
Agresti & Coull 1998: p~ = (k + z^2/2)/(n + z^2),  half = z sqrt(p~(1-p~)/(n + z^2))   (a function and a coverage receipt; not used by `interval`)
interval(): Wilson at every n, the interval `n_certify` solves (Brown, Cai & DasGupta 2001 allow Wilson at any n)
verdict (conf 0.90, as the existing app):  GO if success p >= go (0.90) and the lower bound on success >= min(0.75, go);  NO-GO if p < nogo (0.60);  MARGINAL otherwise
                    go and nogo are the mission's `verdict` block (`intervals.set_thresholds`, called by `config.load_mission`)
n_certify(level, conf) = floor( z^2 (1/level - 1) ) + 1 = 73 at 5 %, 95 %  (zero-failure Wilson upper bound below 5 %);   one-sided (1 - 0.05)^n <= 0.05 -> 59;   rule of three 3/n -> 60   (Hanley & Lippman-Hand 1983)
```

The 90 % Wilson interval is the sampling error of the n members at fixed inputs, not an uncertainty of P(fail) over the inputs: the fitted priors enter as their point values and the other assumed inputs are not varied beyond their stated priors, and the report says so under every interval (review round 7, M-21).
The existing app's `_rate` is a Wilson interval at every n, and so is the pre-mission verdict, so the two agree at every n (`tests/test_stats.py` checks it). The interval printed at n = 73 with no failure is the one `n_certify` solves: its upper bound is 0.0500.
With zero failures and n below 73 the verdict carries the note "P(fail) < 3/n at 95% confidence, one-sided; 60 members would be needed for that bound to reach 5%. The report's certification count, 73, is for the two-sided 95% Wilson upper bound." (the 60-member clause only below 60 members; from 60 to 72 the note says the one-sided rule of three is a weaker statement than the report's certification, review round 6, M-15, which replaced round 5's "already below 5%"; at n = 60 exactly it says 3/n = 0.050 "is 5%, not below it", review round 7, M-40). The report prints "cannot be certified" only for an ensemble whose 95 % Wilson lower bound on P(fail) is below 5 %; one above it says "P(fail) < 5 % is excluded by this ensemble: no number of members certifies it", and the credibility report's Uncertainty factor counts only the first kind as short of n_certify. The report states the verdict rule as GO when P(fail) is at most the GO threshold and the 90 % Wilson upper bound on P(fail) is at most 1 - `LO_SUCCESS_GO` (0.25 in the demo), NO-GO when P(fail) is above the NO-GO threshold (review round 5, M-12). Every threshold test of the verdict goes through one helper, `a >= b - 1e-12`, so a tie at P(success) = nogo (7 of 10 at thresholds 0.9 and 0.3) falls on the boundary-inclusive side in `verdict`, `verdict_from_p`, `interval_region` and `decided_region` alike (review round 4, M-12, DECISIONS 248). Budget `quick` (at most 64 members) cannot certify.

### 13.2 Latin hypercube, antithetic pairs, common random numbers (`sampling.py`)

```
LHS (McKay, Beckman & Conover 1979): n strata per dimension, one jittered point each, strata permuted independently
antithetic (Hammersley & Morton 1956): u[i + n/2] = 1 - u[i] on 'wind_speed_bias' and 'current_speed_scale', strata paired (s, n - 1 - s) so the column is still an exact LHS
CRN: seed = SeedSequence(entropy = base, spawn_key = (member, sha256(stream_name)[:8]));   the vehicle is NOT in the key, so every vehicle in member m sees the same draws
```

Each Stage-1 batch is its own Latin hypercube (`SeedSequence([seed, first_member])`); the ledger records `lhs_stratified_batch<k>`: every stratum hit once and the Kolmogorov-Smirnov distance of each
column below 1/n (an exact LHS column satisfies it; a p-value would be near 1 for any LHS and could not fail). The random fields of the current error (section 8) and the refit drag draw are keyed by
member. **The UAS Mann turbulence, the gust-front events and the Iridium sessions are keyed by the batch's first member, not by member** (a Mann box is generated for the whole batch, so a member's turbulence segment depends on the
batch size; the stage-1 ledger records the batch size). `run_batch` returns the seeds it used (`res["seeds"][vehicle][stream]`), and the `common_random_numbers` ledger check compares them across vehicles and with
`member_seed(seed, first_member of a batch, stream)`, so a vehicle entering a seed of its own fails it (Known issues).

### 13.3 Stopping (`sequential.py`, `stage1.run`)

`ensemble_stop` is asked about every vehicle and link after each batch: stop when the 95 % interval on P(fail) lies wholly at or below 0.10 (GO) or above 0.40 (NO-GO), and `n >= n_min`;
or at `n_max`. `n_min` / `n_max` per budget (`budget.N_MIN`, `N_MAX`): ci 8 / 16, quick 32 / 64, 4h 73 / 256, overnight 73 / 512. The planner caps `n_max` by the stage-1 share of the time and lowers `n_min` with it (`n_min = min(N_MIN, n_max)`), so a quick run on a slow or loaded machine plans fewer, for example 16 / 16 (the q2 run of 2026-10-31). An interval wholly inside GO implies the verdict GO
(tested), so stopping never contradicts the final verdict. Repeated looks at a fixed-sample interval inflate its error slightly (docstring); the 95 % interval is wide.

Wald's SPRT (1945) with an indifference region (Younes & Simmons 2006), `sprt_decide`, is **implemented and tested but not called by the pipeline**; the stopper is the interval rule.

### 13.4 Sensitivity (`sensitivity.py`)

EASI, Plischke (2010): sort by X_i, reorder to a periodic sequence (even ranks ascending, odd descending), `S_i` = share of the output's spectral power in the first M harmonics, M = `default_harmonics(n)` = min(6, max(2, n // 16)) (2 at 32 to 47 members, 6 from 96; DECISIONS 156); small-sample bias removed with
`S~ = S - lam/(1 - lam)(1 - S)`, lam = 2M/N (Plischke, Borgonovo & Smith 2012). It names the "most sensitive to" parameter; it is a ranking from one sample, not a variance decomposition with a confidence interval.

**Sensitivity in the report** (review round 3, M-2, DECISIONS 211). For each vehicle and link the report names the parameter with the largest first-order index of one continuous outcome per member: the UAS's lowest battery reserve margin over its sorties, a station glider's or station USV's largest distance from the station, a section USV's largest cross-track error, a section or drift glider's battery energy margin, a link's fraction of required moments that worked. Only the columns that can act on the vehicle are used (a glider's speed scale cannot act on a UAS), so they do not raise the permutation noise floor. A parameter is named only when its index clears that floor (the 95 % level of unrelated outcomes at the member count: about 0.30 at 32 members with two harmonics). This ranks one outcome, not the verdict: a UAS ranks its battery reserve margin unless `profile_incomplete` is its dominant failure mode, in which case it ranks the lowest fraction of the flux profile delivered over its flown sorties (`profile_margin`, review round 5, M-2), and the report names the ranked quantity in the sentence and in the "top sensitivities" line ("share of the variance of the <quantity>", never "of failure"). The floor is the 95 % level of 2000 permutations (200 before round 5; its own sd at 64 members falls from about 0.014 to 0.004 on the test sample), and one test in twenty on unrelated outcomes still clears it, which the sentence says with the number of such tests the report makes. With no margin (or fewer than 16 finite ones) the 0/1 failure indicator is ranked instead, and with fewer than three failures (or passes) no index is computed, because EASI on a 0/1 vector with k ones saturates at its own floor; the hypercube ranks of the few members among all draws are printed instead. Each entry says which of five cases applies (ranked, nothing above the floor, too few, all pass, all fail) and what was ranked.

What the indices cannot see (review round 4, M-17, DECISIONS 253, amends 211). These indices rank only the sampled columns (the member-wide biases and scales of the forcing and of the vehicle). The larger errors are per-member random streams that are not columns and are not ranked: the hourly wind error (for the demo sd 1.28 m/s and 22.2 deg, against 0.11 m/s and 2.6 deg for the wind-speed and direction columns), half of the current error (the 100 km random field), the ocean SDE, the UAS turbulence and gusts, and the Iridium draws. The report prints this sentence once under the verdict table, with the sds from `ingest/priors_fitted.json` when it holds all four wind entries and without them otherwise. A small index for `wind_speed_bias` therefore does not say that wind speed barely matters.

### 13.5 Subset simulation (`rare.py`)

Au & Beck 2001: nested `F_i = {g(u) >= b_i}`, the top 10 % as seeds, modified Metropolis moves in standard-normal space, c.o.v. with the chain-correlation factor gamma. **Implemented and tested against a known
Gaussian tail; not called by the pipeline.** The chain-correlation factor gamma is taken on the indicator of the new threshold b_i at every level, the final one included (review round 7, M-26; the c.o.v. was about 2.5 x too low before: 80 seeds gave an empirical 0.74, a reported 0.30 and, corrected, 0.47). Since review round 13 (M-34, DECISIONS 726) `n` is rounded to a multiple of the chain count `nc = round(n p0)` and the level probability `nc / n`, which equals `p0` only when `n p0` is a whole number that divides `n`, is used in both the estimate and the c.o.v.; an `n` and `p0` that leave no seed (`nc < 1`) or a chain shorter than 2 are refused.

### 13.6 Emulator (`emulator.py`)

SMT Kriging per target (KPLS above 10 features); probabilities on the logit scale clipped to [1e-3, 1 - 1e-3]; GP nugget 0.01 on the normalised scale; Kennedy & O'Hagan (2000) co-kriging (SMT MFK) once at least 3 high-fidelity rows exist;
normalised split-conformal intervals (Lei et al. 2018): score `|y - mu|/sigma_GP` on a 20 % calibration set, `q` = the ceil((n+1)(1-alpha))-th smallest, interval `mu +- q sigma`; **range guard**: the nearest-neighbour distance in z-scored feature space
against the 99th percentile of leave-one-out nearest-neighbour distances between distinct points (replicate rows are one point; a table of one distinct point has an infinite threshold; review round 7, M-25), beyond which `query` returns `out_of_range` and no number. The pipeline trains it on the Stage-1 members of vehicles that both fail and pass and stores its hold-out scores;
what-if queries are not part of a run.

A what-if mission change (review round 13, M-39 to M-41, DECISIONS 731 to 733 and 752) is a dict per vehicle of `shift_h`, `dlon`, `dlat` and `duty`. A UAS moves with its ship and a ship moves once: two UAS launched from it that ask for different moves are `Invalid`, the training design draws one move per ship for all of them, and a move asked of one UAS also answers the other UAS on that ship, with a note. A shift, move or duty that is NaN or infinite, a duty of 0 or less, or a shift past what the calendar holds is `Invalid`. The flip search lists a change once: candidates that make the same mission are one, and a UAS duty is priced by the whole-day period it really is (the demo's UAS has 12 candidates, not 14).

Scope (review round 10, M-1, DECISIONS 535). The features (`whatif.BASE` and `TASK`) hold neither the length of the window nor the platform, and P(fail) is over the whole window, so rows of another window length or platform are another function. An emulator is therefore trained on, and queried for, one scope: the vehicle class, the platform and the window length (`budget.emulator_scope`, for example `glider/seaglider/144h`), and the 100 distinct points are counted per scope. A feature would not do: a variant never changes the window or the platform, so the column would be a constant and would degenerate the GP and its z-scoring.

Coverage scale and the gate (review round 4, M-3, DECISIONS 239 and 263). The conformal guarantee holds on the scale the scores are built on, the clipped logit of a probability target. `score()["coverage"]` is the interval coverage on that scale (the bounds `lo_z`, `hi_z` are exposed by `predict`, so they are not re-clipped after a sigmoid round trip) and is what the 90 % +-0.05 gate (BRIEF 2.7) judges; `coverage_raw_p` is the same intervals on the raw P scale, where a target of exactly 0 or 1 (22 to 27 % of 16 to 32-member P(fail) values) can never be inside a sigmoid interval, so a calibrated emulator reads 0.67 to 0.78 there. `holdout.json` and the report carry both. The gate is not loosened, but `whatif.fit_class` also records `coverage_chance_fail`: the chance that a calibrated emulator misses the gate by luck. Since review round 13 (M-1, DECISIONS 693) the hits on the `n_test` held-out points are Beta-Binomial(n_test, k, n_cal + 1 - k), because the conformal coverage of `n_cal` calibration scores is itself random, Beta(k, n_cal + 1 - k) with k = ceil((n_cal + 1) 0.9) (`emulator.conformal_rank`): at 28 test points and 22 calibration scores a calibrated emulator misses the 0.85 to 0.95 gate with probability 0.568 (0.527 at 20 points and 16 scores, 0.571 at 30 and 24, 0.206 at 100 and 80), where the Binomial(n_test, 0.9) of the earlier text, right only for an exactly nominal coverage, gave 0.357, 0.255, 0.359 and 0.064 (the gate is then passed only for K = 24, 25 or 26 of 28). So a missed coverage gate on a 20- to 30-point hold-out is weak evidence of miscalibration; the report prints the figure beside the gate. Since review round 10 (M-6, DECISIONS 540) the gate and this figure are one rule, `emulator.coverage_band`: the coverage must lie within 0.05 + 1e-9 of nominal. Before, `abs(17/20 - 0.9) <= 0.05` was False in floats while 19 of 20 passed, so at 20 points the gate was missed with probability 0.445 and not the 0.255 printed (at 40 points 0.287 against 0.180, at 100 0.096 against 0.064); the two 28-point figures were never affected.

Hold-out and training draws (review round 3, M-4, DECISIONS 213). Each training variant of a run is run on its own members (variant k: the block of batch members after the ones Stage 1b used, k blocks further on; review round 7, M-7, which found variant 0 on the members of stage 1's second batch), so its hypercube and noise streams are independent of the other training rows of the run. A variant keeps its shift and duty when only its move is invalid, and a variant equal to the base mission is not run; a feature point is the mission columns (`deploy_h`, `lon`, `lat` and the task columns), so replicates of one mission with different environment medians are one point for the 100-point gate, the hold-out split and the fresh draws (review round 7, M-6). The hold-out is also scored against P(fail) re-estimated on members used nowhere else, for up to three held-out points of the run's own variants, and the RMSE limit is judged on the larger of the two debiased figures (each less its own binomial noise). Held-out rows of other runs cannot be re-run, so a hold-out made only of them is judged in sample and says so.

Receipts: `pm.stats.intervals`, group `pm.stats.intervals`:

| Claim | Tolerance |
|---|---|
| `wilson lower bound k=3 n=30 vs statsmodels` (upper; and `agresti_coull` k=7 n=200) | 1e-9 |
| `smallest n certifying P(fail) < 5 % at 95 % (zero-failure Wilson upper bound)` | exactly 73 |
| `zero-failure Wilson upper bound at n=73 is just under 5 %` | 1e-3 |
| `one-sided n for 5 % at 95 % (rule of three region)` | exactly 59 |
| `Wilson mean exact coverage over p at n=40 (nominal 95 %)` | 0.93 to 0.97 |

`pm.emulator` (slow group, about 35 min, stored per code digest), group `pm.emulator`: `held-out RMSE of P(fail) (20 % held out)` below 0.05; `conformal coverage at 90 % nominal, P(fail) (20 % held out)` 0.85 to 0.95;
`median query time` below 10 ms; `far-off mission distance / calibrated threshold` at least 1; `training mission distance / calibrated threshold` at most 1. **These are scored on a synthetic table**
(`synthetic_table`), so they show the machinery works, not that the emulator predicts the real vehicles.
LHS, antithetic, CRN, EASI, SPRT and subset simulation have no registered receipt; they are covered by `tests/test_stats.py` (statsmodels agreement, exact stratification, Ishigami first-order indices, a known Gaussian tail,
SPRT error rates at the edges of the indifference region, a test that fails if the vehicle enters the seed).

---

## 14. Stage 3: LBM nest, wall model, windows, refit

Code: `cafe/pm/stage3/{lbm,nest,wallmodel,windows,pipeline_windows,refit}.py`. Tests: `tests/test_lbm.py`, `tests/test_nest.py`, `tests/test_stage3.py`. Commit bb68642 (2026-10-29) turned the
sphere and flat-plate receipts from context rows into required pass/fail rows and tightened the wall-model tolerance from 20 % to 10 %; the descriptions below are of that commit.

### 14.1 Lattice Boltzmann kernel

```
D3Q19:  feq_q = w_q rho [ 1 + 3 c.u + 4.5 (c.u)^2 - 1.5 u.u ],    c_s^2 = 1/3,   nu_lat = (tau - 1/2)/3
regularised BGK (Latt & Chopard 2006):  f* = feq + (1 - 1/tau) f_neq^reg,   f_neq^reg = 4.5 w_q ( c_q c_q : Pi_neq - tr(Pi_neq)/3 )
Smagorinsky (Hou et al. 1996, eq. 8):   tau = ( tau0 + sqrt( tau0^2 + 18 sqrt2 Cs^2 |Pi_neq| / rho ) )/2,   Cs = 0.17,   |Pi| the Frobenius norm
lattice scaling:  dt = u_lat dx / U,  nu_lat = nu dt/dx^2;  u_lat = 0.04 (Ma = 0.069); sphere runs 0.05;  nu_lat floored at 1e-4 (tau - 1/2 = 3e-4) because float32 BGK went NaN below it
moving wall (Ladd 1994):   f_qbar = f_q+ - 6 w_q rho c_q . u_w;     curved wall (Bouzidi, Firdaouss & Lallemand 2001): linear interpolation on the wall fraction q, exact sphere/ellipsoid distance:
                           q < 1/2:   f_qbar = 2q f_q+(x) + (1-2q) f_q+(x - c_q) - 6 w_q rho c_q . u_w
                           q >= 1/2:  f_qbar = [ f_q+(x) - 6 w_q rho c_q . u_w ]/(2q) + (2q-1)/(2q) f_qbar+(x)      (the moving term is divided by 2q too, so a body carried by the fluid feels no force at any q; review round 11, M-11, DECISIONS 603)
force: momentum exchange  F = sum c_q ( f_q+ + f_qbar,new ) over the links (Mei et al. 2002 for the curved case)
sponge (Davies 1976): relaxation to the coarse velocity with a quadratic ramp over 4 layers (weight (1 - k/(sponge+1))^2 at layer k > 0, pinned by a test: round 11, M-28);  inflow refill: equilibrium of the coarse velocity at the outermost layer
resolution rule:  delta_te = 0.37 L Re^(-1/5),  dx = delta_te / n (n = 5 to 10 cells; L is the length the flow runs along, the chord (1.2 m) for the USV wing and not its 5 m span, review round 8, M-48),  u_tau = U sqrt(cf/2),  cf = 0.0592 Re^(-1/5),  y+ = 2.5 dx u_tau / nu      (Schlichting & Gersten)
storage: fp32 on CPU; fp16 on a GPU keeps f - w_q (FluidX3D FP16S idea; Lehmann, Krauzig & Schmid 2022);  memory 93 / 55 B per cell, x2.5 for the JAX path (measured 182 B/cell = 1.96x, rounded up for masks); the planner and `run_window` use 300 B/cell for the native nest (182 + 38 masks + 76 Bouzidi q, review round 7, M-13)
```

XLB 0.3.1 (Apache-2.0) is kept for the reference cases (Poiseuille, cavity, Taylor-Green, sphere) but cannot be the window engine: no wall-model boundary, no moving nest, boundary state not vmappable. Its Smagorinsky
form uses `36 Cs^2` where Hou et al. derive `18 sqrt2 Cs^2`, so its Cs = 0.17 acts as 0.202; `XLB_CS_SCALE = 1.189` converts and a test compares the two operators. FluidX3D is disabled by default (licence, `docs/LICENSES.md`).

### 14.2 Nest and frame

The window runs in the **vehicle frame** by default: the grid sits on the body and the inflow is the environment velocity minus the vehicle velocity, which is Galilean-exact for constant velocity and needs no shift. The ground-frame
nest of the GO-MELT idea (populations in the ground frame, the grid rolled by whole cells to follow the vehicle, `refill` of the leading layer, sponge) is implemented and receipted but not used for coefficients: each shift displaces
the fluid by a cell without pushing it, which measured as a spurious force of about -2x the drag at one shift per 25 steps (`WindowSpec` docstring; the lead's log says "about the drag's size").

### 14.3 Wall model

Equilibrium log law, no wall-resolved LES: `u+ = ln(y+)/kappa + B`, kappa = 0.41, B = 5.2 (Pope 2000, ch. 7; BRIEF 2.6), viscous `u_tau = sqrt(nu u/y)` below y+ = 11.06, evaluated at the matching point 2.5 cells off the wall.
The wall exchanges no tangential momentum: axis-aligned flat faces use specular reflection (exact free slip); the log-law stress `rho u_tau^2` is removed from the wall cell along the relative tangential flow and added to the body force,
times the voxel face area; between the wall and the matching point the eddy viscosity is `nu_t = kappa u_tau y`. With `l = kappa y` the log law needs a mixing length that Smagorinsky's `C_s dx` = 0.17 cells does not give: it is 2.4 times too short at y = 1 cell and 6 times at the 2.5-cell matching point (DECISIONS 806). A wall cell whose smoothed-solid gradient vanishes (a slot one cell wide between two walls) has no normal: it gets no log-law shear (bounce-back at the body velocity), no `u_tau`, so no mixing-length eddy viscosity from the wall model either, and is left out of the y+ share; the window result counts such cells (`wall.no_shear_cells`, `note`) and fails the check `wall_cells_without_normal`, which a window cut by the clock or by divergence keeps in its row too, the count being a property of the wall set (DECISIONS 795, 810, 812, 822). The face-area factor, the tangent and the post-kick wall velocity are checked on a sphere's diagonal wall (`test_r14_m32_*`, DECISIONS 793). A stress-boundary-condition family after Malaspinas & Sagaut 2014 (their algorithm itself is not reproduced). Rejected after measurement (docstring):
a no-slip wall with a tuned viscosity (1.3 to 2.6x the log-law stress), a tuned slip velocity (noise), a free-slip wall without near-wall viscosity (C_f 70 % low).

### 14.4 Windows and the refit

- Windows (`pipeline.s_windows`): the K record times (K = 1, 1, 3, 3 by budget) of the strongest forcing per vehicle (10 m wind for UAS and the USV wing, Hs for the USV hull, current speed for gliders), at least 6 h apart, taken from the
  members that failed, else from all. The forcing printed at a worst window is the analysis field (WRF, UMWM, the ocean store) at those members' tracks, before the member perturbations; the window is the record of the strongest such forcing, not the instant a member failed (`failed_at` lists those, review round 3, M-10).
- Each window builds the vehicle from its platform yaml and `assumptions.yaml` `stage3.*` (box 3 x 1.6 x 1.6 body lengths, 10 cells per boundary-layer thickness, minimum 2 cells across, at least 3 box transits, 30 % spin-up
  discarded, **all assumed**), takes the inflow from the environment, and fits cells x steps to the plan's budget (coarsening by the fourth root of the shortfall). On CPU the row carries the plan's `CPU fallback` label.
- Self-checks (`windows.stage3_checks`, each can fail; `ok` needs all): `mach_max` (at most 0.1), `courant_max` (0.3), `yplus_in_30_300_fraction` (0.9), `force_running_mean_dev` (0.02; the running mean of five batch means of the last third against the last-third mean, so a sample's own noise is not a convergence failure; review round 10, M-2), `mass_drift_per_step` (1e-3; per step, as BRIEF 5.1; the run's total change is not checked because the open-boundary nest box legitimately exchanges mass, so a leak of 9e-4 per step passes and loses 97 % over 4000 steps; BRIEF 5.5's "mass conservation <= 0.1 %" is read per step, review round 10, M-14), `interpolation_residual` (0.05),
  `sponge_clearance_cells`, `wall_model_receipt_error` (the larger of the stored flat-plate and channel errors, at most `PLATE_TOL`; fails when either is missing, stored without a `code_sha`, or stored by other code than the current `lbm.physics_sha()`, and names the file; review round 7, M-8; also when a file lacks a finite number in a field the code reads ("wm_*.json is unreadable", review round 9, M-4) or the plate was stored at Re_L below 1e6, M-23), and a window that needed the viscosity floor fails with the reason. A window whose last chunk diverges is cut like one that diverged earlier: `windows.run_window` takes `diverged` from `nest.diverged(series)`, and the wall-model and sphere calibrations raise on a diverged run, so none stores a receipt from it (review round 9, M-24).
- FEA of a glider window (`windows.fea_window`; `pipeline_windows._fea` runs it in its own session and kills the whole process group, ccx included, at the window's deadline, DECISIONS 734): the static solve and, since review round 13 (M-38, DECISIONS 730), the eigenvalue buckling step. The stored `utilization` is the larger of `stress_utilization` (von Mises p99 over yield) and `buckling_utilization` = 1 / (buckling factor x `hangar.KNOCKDOWN`), the knockdown 0.5 by which `hangar` rates a hull's collapse depth. For the default Seaglider hull (Al 6061, 8 mm wall, 500 m, h = L/20) that is 0.367 stress, 0.687 linear buckling and 1.374 knocked down, a collapse at about 364 m (QUESTIONS_FOR_LAB 4a). The buckling step takes about 41 s on top of the static solve's 25 s on orca, so `stage3.fea_min_s` is 68.2 s (DECISIONS 741). The wing and arm root and slamming checks of BRIEF 2.6 have no pm code, and no pm code reads `fea['utilization']`. A buckling step that finds no positive eigenvalue is an error: the window's FEA row is then `run` False with the reason, and the Hangar app records 'structure NOT checked' (round 14, M-31, DECISIONS 792). Under `--budget ci` the glider FEA is planned out (its 9.0 s reserve is under that floor, DECISIONS 776).
- Refit (`refit.py`): per-window ratio `cd/cd_hangar` (`cd_hangar` is the vehicle's baseline model coefficient at the window's speed, same reference area and density: analytic, with no Hangar CFD run, so no Hangar GCI, observed order or mesh-quality check applies; DECISIONS 171), pooled by DerSimonian & Laird 1986,
  `tau^2 = max(0, (Q - (k-1)) / (S1 - S2/S1))`, `w* = 1/(se^2 + tau^2)`; the multiplier Stage 1 samples is Normal(pooled, sigma) as a **lognormal with that mean** per member, with sigma = sqrt(se^2 + max(tau, f_w m)^2 + (f_d m)^2) for m = pooled value: the between-window term is floored at `f_w` = `stage3.refit.between_window_frac` (assumed 0.10) of m when fewer than two windows exist (tau^2 cannot be estimated from one), and the discretisation term `f_d` is the finest stored sphere grid against its Richardson extrapolation (`nest.sphere_discretisation`) or, when larger, `stage3.refit.discretisation_frac` (assumed 0.05): a study can raise the floor, never lower it (review round 7, M-9; the stored three-grid study is 0.0153, so the floor is 0.05, and its source text says the study is not in the asymptotic range and that its Richardson Cd is +12.4 % from Morrison). A single window's batch-means standard error alone (a few hundredths of a percent) is not the uncertainty of a drag multiplier; `refit.json` records `sigma_statistical`, `sigma_between`, `sigma_discretisation` and the sources. Only rows with `ok` enter. Speed scales as `d^(-1/2)`
  for the glider and USV (drag ~ v^2 at fixed propulsive force); the UAS takes d directly. Budget `ci` never refits. Stage 1b is a single rerun of stage 1 with the multipliers, not the loop to convergence of BRIEF 2.6 (limitation L16): `plan.json` carries `refit_iterations_max` (the cap), the stage-1b summary `refit_iterations_performed` (0 when no window was usable and stage 1 is copied, else 1), and the ledger check `refit_iterations_within_cap` compares them.
- USV windows (review round 7). The `hull` window is a fully submerged ellipsoid of draft 0.45 m (semi-axes lwl/2, beam/2, 0.45), not the waterline hull; its Hangar reference is the viscous resistance on the ellipsoid's own surface (17.03 m2, Knud Thomsen, against the platform's 6.5 m2), so the multiplier is per unit of that surface (M-10). The `hull_fs` reference is `usv.hull_resistance` on the free-surface mesh's own wetted area (8.392 m2 in q7's plan); the row carries `wetted_area_window_m2`, `wetted_area_platform_m2` and the ratio. That mesh is the half ellipsoid below the waterline plus the keel box and displaces 1.98 m3 (2.02 t at 1023 kg/m3) against the platform's 0.73 m3 (`mass_kg` 750), 2.7 times, so the wave-making resistance that is refitted is for 2.7 times the displacement; the geometry is unchanged and a draft of about 0.145 m, c = (V_platform - V_keel) / (2 pi a b / 3) with V_keel = 0.14 m3, would give the mesh the platform's displacement (review round 8, M-15; round 13, M-44: 0.18 m counted the half ellipsoid alone and left the mesh at 0.875 m3, 19 % over). The platform's `wetted_area_m2` stays what Stage 1 uses. A window runs in the platform's own fluid (USV: `nu_water` 0.86e-6, `rho_water` 1023, `rho_air` 1.16; glider 1.19e-6 and 1025, `nu_air` 1.5e-5 where no leaf exists; M-28). The window heading is the stage-1 bow heading (circular median over members at the record nearest the window time, from `res.pkl` `heading`), the course over ground only without it, and the row's `heading_source` says which (M-27). The free-surface GCI is the sensitivity to horizontal refinement, not a bound of the total error: the grids differ in the horizontal boxes only, the vertical resolution is the same; r is Celik's effective ratio from the cell counts; `cd_spread` is the GCI-based (Fs = 3) spread, used as sigma (conservative; M-29).
- The window size is capped by the plan: `fit_window` coarsens dx until the cells are at most `plan["les"]["max_cells"]` = int(0.85 x GPU bytes / 300), the same figure `run_window` checks (M-13).

### 14.5 Receipts

| Job, group | Claim | Tolerance | State |
|---|---|---|---|
| `pm.stage3.lbm`, `LBM jax` | `Poiseuille: curvature of the steady profile g_eff/g`; `relative residual of the parabola fit` | 1 %; 0.5 % | pass |
| | `Cavity Re=100 max \|u-u_Ghia\| on the vertical centreline / U_lid` (and `\|v-v_Ghia\|`) | 0.04 of the lid speed | pass (0.033 and 0.025 in the stored table) |
| | `Taylor-Green decay: fitted viscosity / analytic` | 3 % | pass |
| | `Sphere Cd at Re=100, XLB halfway bounce-back (staircase), d=8` (also Re=1000 d=10, Re=1e4 d=12) | 10 % of Morrison 2013 | **FAIL by design** until a run that reaches 10 % is stored (staircase error about 1/d) |
| `pm.stage3.nest`, `LBM nest` | `Vehicle-following nest, uniform flow: \|F\| / (rho U^2 d^2) (zero expected)`; `Nest crossing a shear layer: max \|dM\|/M per step`; `... interpolation residual at the first sponge layer / u_lat`; shift counts | 1e-4; 1e-3; 0.005; at least 10 shifts | pass |
| | `Sphere Cd at Re=100, Richardson-extrapolated from d=[8, 12, 16] (order 2.96)` (also Re=1000, 1e4) in group `LBM native sphere` | 10 % of Morrison 2013 | Re=100 **FAILS**: the three grids d = [8, 12, 16] give Cd = 1.305, 1.209, 1.185, Richardson order 2.96 (the top of the [0.5, 3] bracket), Cd_inf = 1.167, +12.4 % over Morrison 1.038. The pairs extrapolate to 1.016 (8, 12) and 1.113 (12, 16): not in the asymptotic range. The earlier "d = [8, 12] passes (order 1.00, -2.2 %)" is not what the code gives (review round 7, M-9); these figures are of the stored files, which are stale until re-stored (M-8). Re=1e3 (needs d at least 24) and Re=1e4 (d at least 40) are **FAIL until stored** |
| `pm.stage3.wallmodel`, `LBM wall model` | `Log law inverted for u_tau (kappa 0.41, B 5.2) at y+ = 100` | 0.5 % | pass |
| | `Channel (Re_tau 1000): wall stress / (g h)` | 1 % | pass |
| | `Channel: bulk C_f at Re_b = 3.95e+04 vs Dean` | 10 % of Dean 1978 | pass (0.00513 against 0.00518) |
| | `Channel: matching-point y+`, `matching height y/h`, `bounce-back tangential exchange / wall shear` | 30 to 300; below 0.3; below 0.01 | pass |
| | `Flat plate C_f vs ITTC-57 (applies at Re_L >= 1e6), wall-modelled with inflow turbulence` | 10 % of ITTC-57 | **FAIL until a run at Re_L >= 1e6 is stored** (the 2026-10 stored run had Re_L 9.8e5 and err 0.165, a fail on both counts; below 1e6 the row is a FAIL that prints its Re_L whatever its error; the next run uses length 400, Re_L 1.02e6, about 1.9 h on 2 CPUs, review round 7, M-44); an earlier CI-size plate was 71 % low and the comparison was ill-posed (ITTC-57 is turbulent, the plate was laminar) |

The figures in the State column are the values in `runs/receipts.json` written 2026-10-29 00:36. That table predates bb68642, which made the sphere and flat-plate rows
required, so a fresh `python -m cafe.pm receipts` shows those rows as failures until the slow runs are stored (`--slow`, or the commands in the row notes). A stored FAIL stays a FAIL.
The earlier XLB staircase values, for scale: Cd 1.347 against Morrison's 1.038 at Re = 100 (d = 8, +30 %), 0.769 against 0.484 at Re = 1000 (d = 10, +59 %), 0.681 against 0.394 at
Re = 1e4 (d = 12, +73 %); the native kernel at Re = 100 gave 1.2087 on d = 12 (+16 %) and 1.0155 extrapolated. The lead's log records a working hypothesis for the Re = 100 excess, an effective diameter of d + 1; it is untested.
