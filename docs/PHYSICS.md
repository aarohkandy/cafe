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
  gives UMWM data the WW3 convention on purpose; `python -m cafe.pm receipts --broken ...` must then fail a receipt.

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
| context: median speed of the Stokes drift from the parametric spectrum / from the real restart spectrum | none | shows the size of the correction that `surface.build` applies |

---

## 1. Ingest

Code: `cafe/pm/env/orca.py` (`ingest`, `wrf_hour`, `umwm_hour`, `spec_hour`, `assemble`), `remote.py` (`RemoteFile`, `cdf1_header`,
`cdf1_read`, `download`), `cafe/schemas/*.json`. Tests: `tests/test_orca.py`, `tests/test_remote.py`.

What is read. The UWIN-CM run `run_2023mar_waves_v4` on orca: `wrfout_d01_YYYY-MM-DD_HH:00:00` (HDF5, 12 km Mercator, WRF 4.7.1),
`output/umwmout_*.nc` (NetCDF classic, UMWM), `restart/umwmrst_*.nc` (00/06/12/18 Z only). Directory listing is 403, so names are
built from the hour. Only the mission box plus `pad_deg` (2 deg in the demo) and one cell on each side is read, by HTTP byte range.

| Product | Variables | Notes |
|---|---|---|
| `wrf.zarr` | `U10 V10 T2 Q2 PSFC SST TSK HFX LH QFX RAINNC RAINC SWDOWN GLW UST PBLH`, static `XLAT XLONG LANDMASK HGT COSALPHA SINALPHA` | `SST` is frozen at the 1 March field (`SST_UPDATE = 0`); it is not a diurnal SST. |
| `wrf3d.zarr` | `U3 V3 Z3 TH3` on the 8 lowest mass levels (about 21 to 400 m) | only for the hours a UAS flies (`hours3d`). `U3`, `V3` destaggered by averaging the two faces; `Z3 = (PH+PHB)/g` averaged over the two w-levels; `TH3 = T + 300`. |
| `umwm.zarr` | `swh mwp mwd dwp dwd mss wspd wdir ust cd dcp dcg mwl dwl`, static `seamask depth` | `seamask = 0` is land; the file's integrated fields are NaN there and `GriddedEnv` masks them with `seamask` (no data, not zero); `depth` is 0 on land. |
| `umwmspec.zarr` | `F(time, point, th, f)` [m^4 rad^-1], `k(time, point, f)` | every 6 h; every 3rd sea point in each direction (36 km, `SPEC_STRIDE = 3`); `x` is the outermost dimension of the file so each box row is one byte range. |

Formulas.

```
rain rate [mm/h] = max( d(RAINNC + RAINC)/dt over the actual time step, 0 ) x 3600        (GriddedEnv: backward difference)
UMWM:  swh = 4 sqrt( sum F k dk dtheta ),   mss = sum F k^3 dk dtheta,   dk = k dln(k) per log-f bin     (umwm_domain_output.f90)
```

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
below z_1:  the COARE profile.   above the top stored level (about 400 m):  the top level's value (a clipped to 1).
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
cool skin: Fairall et al. 1996 eqs 12-17;  thermal roughness z0q = min(1.6e-4, 5.8e-5 / R_r^0.72)        rain heat flux: Gosnell et al. 1995
psi:  Beljaars & Holtslag 1991 (stable),  Grachev et al. 2000 (convective) blended with Businger et al. 1971 (Kansas) in the unstable branch
profile:   U(z) = u* / (kappa gf) [ ln(z/z0) - psi_u(z/L) + psi_u(z0/L) ]       (mean, not gust-inclusive, wind relative to the current)
```

In the pipeline `surface.build` runs COARE once per WRF hour on the whole grid with `cp = dcp` and `sigH = swh` from UMWM, so the roughness
is the **sea-state** form wherever UMWM has a value. Inputs: `U10, T2, Q2, PSFC, SST, SWDOWN, GLW, PBLH` (z_i = max(PBLH, 100 m)), `RAINNC+RAINC`.
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
- The swell threshold `swell_age = 1.2` and the short-sea age `wind_sea_age = 2.0` are **assumed**, and are **code defaults** of
  `spectrum_from_params`; they are not keys in `config/assumptions.yaml`, so the credibility report does not list them.
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
restart times it was wrong: **median speed error 38 %**, the fit under-predicts by about x2.7 at the sample points (lead's log, real data). The
fix (`surface._correct_with_real`):

```
c(node, t_r) = ( real_e + i real_n ) / ( fit_e + i fit_n )      at each restart time t_r (complex ratio: speed error and rotation)
c(node, t)   = linear in t between restart times, held outside; c = 1 at nodes with no real spectrum; the hourly field is c x fit
leave-one-out: predict each interior restart b from the corrections at its neighbours a, c (12 h apart, twice the span used):
    pred = [(1 - w) c_a + w c_c] fit_b,   w = (t_b - t_a)/(t_c - t_a)
    speed error = median | |pred|/|real| - 1 |,   direction error = median | arg(pred/real) |
```

Measured on the real cache (lead's log): **leave-one-out median speed error 5.1 %, direction 3.7 deg** (fit alone 38 %). `stokes_surface` tags
the field with `uncertainty = (LOO median speed error) x |u_s|`: a median is used as a 1-sigma, which is an **assumption**. Without restart spectra the tag
is `0.4 |u_s|` (assumed).

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
is what Stage-3 LES is meant to overwrite; `calibration.source_run` is `null`, so the shipped defaults run. Tests: `tests/test_subgrid.py`,
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

### 5.2 Gust fronts

```
lambda [1/h] = lambda_bg + lambda_max (1 - exp(-rain / R0)) f(theta_e),    f = clip( (theta_e - 335 K) / 15 K, 0, 1 )
    lambda_bg = 0.005, lambda_max = 0.3, R0 = 1 mm/h   (all assumed);   theta_e: Bolton 1980 eqs 21, 24, 43 from T2, Q2, PSFC
events per member-hour ~ Poisson(lambda), start uniform in the hour; duration U[600, 1800] s; peak dU U[3, 10] m/s;
direction = mean wind direction + N(0, 45 deg) (assumed); dT = -1.5 K (the detection threshold, so a bound, not a distribution)
dU(t), dT(t): triangle, rising linearly over 450 s (wind) and 600 s (temperature) after onset, falling linearly to the end of the event
```

The structure (cold pools sit under rain) follows Wills, Cronin & Zhang 2021, **abstract only**; peak gusts 5 to 10 min after the temperature front is
Wills et al. 2023 **as summarised in a search**; every number in the rate model is assumed. **The pipeline does not pass `theta_e` to `gust_fronts`**
(`stage1._uas_forcing`), so f = 1: the rate is the rain-only upper value. The `theta_e_lo_K` and `theta_e_span_K` assumptions are not used by a run.
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

**Persistence.** `surface.build` stores `since_rain_s` (time since the last hour with rain above the trigger) and `last_rain_mm_h` (that hour's rate), and
`SurfaceLayer._lens` feeds `last_rain_mm_h` as the rate, so a lens formed by an hour of rain decays with `exp(-t_since/tau)` after the rain stops. This was
**added in commit bb68642 (2026-10-29)**; before it the lens followed the instantaneous rain rate and vanished with it, so `since_rain_s` had no effect.
`derived.zarr` layout version 2 holds the new field; ingest rebuilds an older store and `SurfaceLayer` refuses one with the rebuild command. Test:
`tests/test_surface.py::test_rain_lens_outlives_the_rain_and_decays_with_its_e_folding_time`. The wind enters the decay through the instantaneous
U10, not the wind history.

### 5.4 Diurnal jet and ocean SDE

```
jet [m/s] = 0.2 (midpoint of config/subgrid.json [0.1, 0.3]) x min(dT_warm / 3 K, 1) x ( 1 + z/d_warm )_+ , along the 10 m wind, added to the HYCOM current; +-0.1 as the sigma
```

TEPEX-C's own hypothesis (BRIEF 2.2), **modelled, not observed**; `dT_ref = 3 K` is assumed. It enters through `SurfaceLayer` (mission switch
`warm_layer`: no warm layer, no jet). Windage is **not** added to the current, because the HYCOM top layer holds the Ekman drift and the USV VPP has its
own windage. At the surface the glider drifts with a per-member leeway of 1.8-2.3 % of U10 (`subgrid.windage_fraction`).

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

---

## 6. Ocean: GOFS / HYCOM, TEOS-10, bathymetry

Code: `cafe/pm/env/hycom.py` (`fetch_gofs`, `assemble_gofs`, `teos10`, `read_lab_netcdf`, `read_archv`, `ingest_lab_hycom`), `ocean.py`, `bathy.py`. Tests:
`tests/test_hycom.py`, `tests/test_ocean.py`, `tests/test_bathy.py`.

Source. GOFS 3.1 GLBy0.08 expt_93.0, 3-hourly, 40 z-levels, `water_temp salinity water_u water_v surf_el`; or the lab's HYCOM (per-snapshot netCDF, or `archv.*.a/.b`
with `yrflag 3` only, curvilinear grids refused). Store: `DATA/ocean/gofs_<mission>.zarr`, `(time, depth positive down, lat, lon in [0, 360))`, float32
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
- The existing app's one-snapshot rule (DECISIONS 8) does not apply here: the pre-mission environment interpolates the 3-hourly fields in time.
- The glider and USV read `rho` through `GriddedEnv.density`, which adds the warm-layer and rain-lens terms of section 5.3.

Bathymetry (`bathy.choose`), in this order, first that works:

| Order | Source | Resolution | 1-sigma |
|---|---|---|---|
| 1 | GEBCO_2026 15 arc-second, `elevation` positive up, depth = -elevation, 0 on land; cut from the 7.47 GB file by one HTTP byte range per box row | 460 m | `bathy.gebco_rel_sigma` = 5 % of depth (**assumed**) |
| 2 | deepest valid level of the GOFS store (never below 5000 m; the floor is at or below that level) | 0.08 x 0.04 deg | level spacing / sqrt(12), computed |
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

The lab readers have only ever read a synthetic fixture. The real-store check against NCSS (`check_node`) needs the network and is not a registered receipt.

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
model - mooring:  samples within +-30 min of each hourly model time, vector mean, at least 3 samples;
    speed bias, speed RMSE, vector RMSE; direction bias (FROM, signed, wrapped to +-180, only where both speeds >= 1 m/s); SST bias and RMSE
```

Fit on the real window (2023-03-01..07, lead's log): 11 moorings, 1492 hourly pairs.

| Quantity (WRF minus TAO) | Bias | RMSE |
|---|---|---|
| 10 m wind speed | +0.62 m/s | 1.46 m/s |
| wind direction (FROM) | -7.2 deg | 24.8 deg |
| SST | -0.11 K | 0.26 K |

Fitted Stage-1 priors (`pipeline._tao`, written to `ingest/priors_fitted.json`, read by `stage1.priors_for`):

```
wind_speed_bias     ~ N( -bias_speed,  sqrt(rmse_speed^2 - bias_speed^2) )   = N(-0.62, 1.33) m/s      (sign: the correction that removes the model bias)
wind_direction_bias ~ N( -bias_dir,    sqrt(rmse_dir^2   - bias_dir^2)   )   = N(+7.2, 23.7) deg
```

Conservative by construction: the whole residual sd, hourly scatter included, becomes a member-wide persistent bias, because `PerturbedEnv` has no time-varying wind
error term. The between-mooring sd of the mean bias alone is about 0.36 m/s (lead's log). Only the two wind priors are fed back: the SST bias and RMSE, and every other
residual, are recorded in `ingest/tao_compare.json` and not used; `env.sigma.sst_k` and `env.sigma.t2_k` stay at their assumed values (0.5 K, 1.0 K) although the
text of `assumptions.yaml` says the TAO comparison overwrites `t2_k`. A mission with no TAO download keeps the `perturbations.yaml` priors and the ledger says so.

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
current: v' = R(b_cdir) v exp(s),   s = ln(a)/sqrt2 + (sigma_c/sqrt2) F_speed(x) - sigma_c^2/4,    b_cdir_total = b_cdir/sqrt2 + (sigma_d/sqrt2) F_dir(x)
         a = current_speed_scale[m] (lognormal, median 1, sigma 0.30);  half of each prior's variance is member-wide (the LHS draw, so the sensitivity indices see it)
         and half is a smooth random field with correlation length 100 km
F(x)   = sqrt(2/32) sum_{i=1..32} cos( k_i . x + phi_i ),   k_i ~ N(0, 1/ell^2) per axis, phi_i ~ U(0, 2 pi)        random Fourier features, Gaussian covariance (Rahimi & Recht 2007)
waves:   Hs' = Hs hs_scale[m];  Tp' = max(Tp + tp_bias[m], 1 s);  Stokes drift x hs_scale^2 (it is quadratic in amplitude)
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
| `usv_vpp_bias` | uniform[-0.35, -0.30] | BRIEF 2.5 (VPPs overpredict USV SOG by 30 to 35 %) |
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
- Ground velocity while flying = `U cos(theta)` along the heading + `env.current(z)` (which includes the surface jet inside the warm layer); surfaced: current + 0.01 x 10 m wind (windage **assumed**).
- Pilot ballasting (`_trim`): at the start position, 11 depths. Dive VBD = `delta` below the lightest ballast point, climb VBD = `delta` above the heaviest (`vbd_delta_cc` = 60 cc, **assumed**);
  if the span does not fit the 850 cc pump range the vehicle mass is shifted to centre it.
- Temperature: the environment holds no T(z), so `T = t_deep + (SST - t_deep) exp(-z/h)` with t_deep 4 degC and h = 150 m (**assumed**); it enters only through `alpha_T`. Credibility limitation L06.
- Energy: hotel 0.5 W (**assumed**) + pump work `p dV/eta` with eta 0.40 (**assumed**; bracketed by NOC 65 W for 2 min and Copernicus os-2019-36) + surface comms + attitude motors (414 J per dive, sourced).
- Failure flags: `station_lost` (outside the tolerance for `lost_hours`), `battery`, `seafloor`, `overdepth`, `no_flight`, `waypoint_unreachable`. Phase changes are evaluated at step ends, late by at most one step.
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
hull    R = 1/2 rho V^2 S [ C_F (1 + k) + C_R0 (Fr/Fr_ref)^4 ] (1 + c phi^2),   C_F = 0.075/(log10 Re - 2)^2                  ITTC 1957; hull-speed cap 1.34 sqrt(L_ft) kn = 3.3 m/s
foils   a = 2 pi AR/(2 + sqrt(4 + AR^2)) (Helmbold 1942; Hoerner & Borst 1975), AR doubled for the free-surface image, induced drag C_L^2/(pi AR),
        profile drag 2 C_F (1 + 2 t/c + 60 (t/c)^4) on planform area (Hoerner 1965)
roll    righting moment Delta g GM sin(phi) = heeling moment of the lateral force about the centre of lateral resistance
balance sum X = 0 by a root search on a 0.05 m/s speed grid; Y, heel, depower, rudder by 24 damped fixed-point iterations
```

- The still-water table (TWS 0 to 30 m/s, TWA 0 to 180 deg) is built once per parameter set (cached by a digest); because hull and keel see only the water and the sail only the air, the solution depends
  on `w - c`, so Stage 1 reads the table at the relative wind (`through_water_table`) and the direct solve (`through_water`) agrees.
- **Fit.** `appendage_cda_m2` was raised from 0.02 to 0.04 so that the best-heading speed at 12 m/s matches Chiodi et al. 2021 (2.9 m/s). The receipt is labelled `CALIBRATED` and is a calibration, not a validation (limitation L02).
- Wave added resistance, Gerritsma & Beukelman 1972 in the form of Journee & Massie 2001, by closed-form strip theory (21 sections, coupled heave and pitch with sectional added mass `rho pi b^2/8`):

```
R_aw = (k / 2 w_e) int b'(x) |V_z(x)|^2 dx,   b' = rho g^2 A^2 / w_e^3,   A = 2 sin(k_e b/2) exp(-k_e d)             (Journee & Massie; equation number not checked)
spectrum: Bretschneider S = (5/16) Hs^2 wp^4 w^-5 exp(-1.25 (wp/w)^4);   R = 2 int S R_aw/zeta_a^2 dw = Hs^2 G(Tp, chi, U),   tabulated (Tp 3-21 s, chi 0-180, U 0-3.5 m/s)
oblique seas: R_aw x max(-cos chi, 0)                       no source (zero in following and beam seas)
Stage 1 lowers the speed by R_aw/K, K = -dX/dV at the root (first order)
```

  Capytaine (3-D BEM) was **not used**: a 7 m slender hull follows waves longer than about 30 m, and a BEM call per (omega, heading, speed) would dominate the build.
- Capsize proxy: `peak = steady heel + sigma_phi sqrt(2 ln N)` (Longuet-Higgins 1952, N = 100 cycles), `sigma_phi` from a 1-DOF roll response at the peak period to the wave slope `k Hs/4 |sin chi|`; fires above 45 deg (**assumed**, a knock-down flag, not a capsize angle).

### 10.2 Stage-1 kinematics (`USVSim`)

Every `replan_s` the heading is chosen from 72 candidates to maximise velocity made good: `g = V(trk) + (current + Stokes drift)`; speed = `min( max(V_polar - R_aw/K, 0) (1 + bias), 3.3 m/s )`.
A tack costs `V t_tack` of distance and is taken only if the VMG gain over `tack_horizon` repays it; on a section only headings that reduce the cross-track error are allowed outside the corridor.
`bias` is the member's `usv_vpp_bias` draw (uniform on [-0.35, -0.30]); the platform's own N(-0.30, 0.03) default is used only when a caller passes none, and Stage 1 passes the perturbation draw.
Flags: `becalmed` (best through-water speed over all headings below the current speed for `becalmed_after_h`; the literal "SOG below current" cannot fire because a drifting boat's SOG equals the current),
`swept_off_track`, `capsize_proxy`, `wing_stall` (apparent wind below the tail's authority or inside the bow stall cone for `stall_sustain_s`), `battery` (solar gain `eff x area x SWDOWN` minus hotel load).

Receipts, job `pm.physics.usv`, group `usv`:

| Claim | Tolerance | Note |
|---|---|---|
| `ITTC-1957 C_F at Re = 1e7` | 1e-12 | closure |
| `hull speed 1.34 sqrt(LOA ft) kn vs the 3.3 m/s cap` | 4 % | Mazza et al. 2026 Part 1, as quoted in the brief |
| `mean SOG / U at 5.4 m/s (VMG routing, all bearings, prior bias)` | 25 % band (assumed) | 0.164 against Chiodi's 0.178, -7.6 % (lead's log) |
| `best-heading still-water speed at 12 m/s (CALIBRATED: appendage_cda_m2)` | 10 % | **fit**; 2.92 against 2.9 m/s |
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
  Flags: `battery_reserve`, `wind_exceeds_airspeed` (no headway for 10 s while commanding more than 1 m/s), `attitude_exceedance` (tilt 7 deg beyond the 35 deg limit), `lost_link` (never set in Stage 1: no link callback is
  passed; the RF link is judged separately by `stage1.evaluate_link`), and `no_sortie_flown` (every launch scrubbed).
- Wind: the mean wind from `env.wind` is looked up every 1 s (20 blocks) and held; turbulence (section 5.1) and gust fronts (5.2) are added at 50 ms. The Mann series are built from the fewest boxes that fit.
- ArduCopter SITL (JSON backend, ArduPilot 4.7.x) flies the same physics in lockstep for a few members (`fly_sitl`); the firmware is told it is at Canberra (`SITL_HOME`) because its compass and EKF
  misbehave at the equator; only metres from home are used.

Uncertainty: per-member scales on battery capacity (lognormal 0.05, **assumed**) and drag (Stage-3 refit); wind error and turbulence through the environment. The turbulence and gust draws are per batch (Known issues).

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
E / E_free = | 1 - rho_s (r1/r2) exp( -j 2 pi (r2 - r1)/lambda ) |,   r1 = sqrt(d^2 + (ht - hr)^2),  r2 = sqrt(d^2 + (ht + hr)^2)        reflection coefficient -1 (grazing, smooth)
L = 20 log10( 4 pi r1 / lambda ) - 20 log10( |E/E_free| )                                                        path loss
rho_s = exp[ -2 (2 pi sigma_h sin(psi)/lambda)^2 ],   sigma_h = Hs/4,   sin(psi) = (ht + hr)/r2                      Ament 1953; Beckmann & Spizzichino 1963
margin = P_t + G_t + G_r - cable - misc - L - sensitivity;     -200 dB beyond the 4/3-earth horizon  d_max = 4.12 (sqrt(ht) + sqrt(hr)) km          ITU-R P.834
```

Specular only: diffuse scatter is neglected, so null filling is underestimated; antenna motion with the waves is not modelled (the roughness term stands in). Antenna gain 2 dBi and 3 dB misc loss
are **assumed**; the 900 MHz sensitivity is the datasheet's lowest-rate value. The member's own Hs (perturbed) feeds the roughness. The antenna height of an aircraft is deck + flight altitude + 0.1 m.

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

### 12.3 Iridium

SBD message of n bytes = ceil(n/340) sessions; each session retried up to 3 times; per-attempt success 0.95; set-up time log-normal (median 10 s, log sigma 0.6); transfer 5 s (short) to 20 s (full message), published nominal;
a failed attempt costs 60 s. **All of the success, retry and set-up numbers are assumed** (no published statistic found); latency and availability only, no range dependence (BRIEF 2.8). Stage 1 draws one session per
10-minute moment, independently.

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
Agresti & Coull 1998: p~ = (k + z^2/2)/(n + z^2),  half = z sqrt(p~(1-p~)/(n + z^2))
interval(): Wilson for n <= 40, Agresti-Coull above (Brown, Cai & DasGupta 2001, Sec. 5)
verdict (conf 0.90, as the existing app):  GO if success p >= 0.90 and the lower bound on success >= 0.75;  NO-GO if p < 0.60;  MARGINAL otherwise
n_certify(level, conf) = floor( z^2 (1/level - 1) ) + 1 = 73 at 5 %, 95 %  (zero-failure Wilson upper bound below 5 %);   one-sided (1 - 0.05)^n <= 0.05 -> 59;   rule of three 3/n -> 60   (Hanley & Lippman-Hand 1983)
```

The existing app's `_rate` is a Wilson interval at every n; the pre-mission verdict switches to Agresti-Coull above n = 40, so the two agree only up to 40 members (`tests/test_stats.py` checks that range).
With zero failures and n below 73 the verdict carries the note that P(fail) < 3/n and 73 members are needed to certify 5 %. Budget `quick` (at most 64 members) cannot certify.

### 13.2 Latin hypercube, antithetic pairs, common random numbers (`sampling.py`)

```
LHS (McKay, Beckman & Conover 1979): n strata per dimension, one jittered point each, strata permuted independently
antithetic (Hammersley & Morton 1956): u[i + n/2] = 1 - u[i] on 'wind_speed_bias' and 'current_speed_scale', strata paired (s, n - 1 - s) so the column is still an exact LHS
CRN: seed = SeedSequence(entropy = base, spawn_key = (member, sha256(stream_name)[:8]));   the vehicle is NOT in the key, so every vehicle in member m sees the same draws
```

Each Stage-1 batch is its own Latin hypercube (`SeedSequence([seed, first_member])`); the ledger records `lhs_stratified_batch<k>`: every stratum hit once and the Kolmogorov-Smirnov distance of each
column below 1/n (an exact LHS column satisfies it; a p-value would be near 1 for any LHS and could not fail). The random fields of the current error (section 8) and the refit drag draw are keyed by
member. **The UAS Mann turbulence, the gust-front events and the Iridium sessions are keyed by the batch's first member, not by member** (Known issues).

### 13.3 Stopping (`sequential.py`, `stage1.run`)

`ensemble_stop` is asked about every vehicle and link after each batch: stop when the 95 % interval on P(fail) lies wholly at or below 0.10 (GO) or above 0.40 (NO-GO), and `n >= n_min`;
or at `n_max`. `n_min` / `n_max` per budget: ci 8 / 16, quick 32 / 64, 4h 73 / 256, overnight 73 / 512, further limited by the planner's time share. An interval wholly inside GO implies the verdict GO
(tested), so stopping never contradicts the final verdict. Repeated looks at a fixed-sample interval inflate its error slightly (docstring); the 95 % interval is wide.

Wald's SPRT (1945) with an indifference region (Younes & Simmons 2006), `sprt_decide`, is **implemented and tested but not called by the pipeline**; the stopper is the interval rule.

### 13.4 Sensitivity (`sensitivity.py`)

EASI, Plischke (2010): sort by X_i, reorder to a periodic sequence (even ranks ascending, odd descending), `S_i` = share of the output's spectral power in the first 6 harmonics; small-sample bias removed with
`S~ = S - lam/(1 - lam)(1 - S)`, lam = 2M/N (Plischke, Borgonovo & Smith 2012). Applied to the 0/1 failure indicator, only where at least one member failed, one passed, and n >= 16. It names the "most
sensitive to" parameter; it is a ranking from one sample, not a variance decomposition with a confidence interval.

### 13.5 Subset simulation (`rare.py`)

Au & Beck 2001: nested `F_i = {g(u) >= b_i}`, the top 10 % as seeds, modified Metropolis moves in standard-normal space, c.o.v. with the chain-correlation factor gamma. **Implemented and tested against a known
Gaussian tail; not called by the pipeline.** The reported c.o.v. underestimates the spread (lead's log).

### 13.6 Emulator (`emulator.py`)

SMT Kriging per target (KPLS above 10 features); probabilities on the logit scale clipped to [1e-3, 1 - 1e-3]; GP nugget 0.01 on the normalised scale; Kennedy & O'Hagan (2000) co-kriging (SMT MFK) once at least 3 high-fidelity rows exist;
normalised split-conformal intervals (Lei et al. 2018): score `|y - mu|/sigma_GP` on a 20 % calibration set, `q` = the ceil((n+1)(1-alpha))-th smallest, interval `mu +- q sigma`; **range guard**: the nearest-neighbour distance in z-scored feature space
against the 99th percentile of leave-one-out nearest-neighbour distances, beyond which `query` returns `out_of_range` and no number. The pipeline trains it on the Stage-1 members of vehicles that both fail and pass and stores its hold-out scores;
what-if queries are not part of a run.

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
moving wall (Ladd 1994):   f_qbar = f_q+ - 6 w_q rho c_q . u_w;     curved wall (Bouzidi, Firdaouss & Lallemand 2001): linear interpolation on the wall fraction q, exact sphere/ellipsoid distance
force: momentum exchange  F = sum c_q ( f_q+ + f_qbar,new ) over the links (Mei et al. 2002 for the curved case)
sponge (Davies 1976): relaxation to the coarse velocity with a quadratic ramp over 4 layers;  inflow refill: equilibrium of the coarse velocity at the outermost layer
resolution rule:  delta_te = 0.37 L Re^(-1/5),  dx = delta_te / n (n = 5 to 10 cells),  u_tau = U sqrt(cf/2),  cf = 0.0592 Re^(-1/5),  y+ = 2.5 dx u_tau / nu      (Schlichting & Gersten)
storage: fp32 on CPU; fp16 on a GPU keeps f - w_q (FluidX3D FP16S idea; Lehmann, Krauzig & Schmid 2022);  memory 93 / 55 B per cell, x2.5 for the JAX path (measured 182 B/cell = 1.96x, rounded up for masks)
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
times the voxel face area; between the wall and the matching point the eddy viscosity is `nu_t = kappa u_tau y`. A stress-boundary-condition family after Malaspinas & Sagaut 2014 (their algorithm itself is not reproduced). Rejected after measurement (docstring):
a no-slip wall with a tuned viscosity (1.3 to 2.6x the log-law stress), a tuned slip velocity (noise), a free-slip wall without near-wall viscosity (C_f 70 % low).

### 14.4 Windows and the refit

- Windows (`pipeline.s_windows`): the K record times (K = 1, 1, 3, 3 by budget) of the strongest forcing per vehicle (10 m wind for UAS and the USV wing, Hs for the USV hull, current speed for gliders), at least 6 h apart, taken from the
  members that failed, else from all.
- Each window builds the vehicle from its platform yaml and `assumptions.yaml` `stage3.*` (box 3 x 1.6 x 1.6 body lengths, 10 cells per boundary-layer thickness, minimum 2 cells across, at least 3 box transits, 30 % spin-up
  discarded, **all assumed**), takes the inflow from the environment, and fits cells x steps to the plan's budget (coarsening by the fourth root of the shortfall). On CPU the row carries the plan's `CPU fallback` label.
- Self-checks (`windows.stage3_checks`, each can fail; `ok` needs all): `mach_max` (at most 0.1), `courant_max` (0.3), `yplus_in_30_300_fraction` (0.9), `force_running_mean_dev` (0.02), `mass_drift_per_step` (1e-3), `interpolation_residual` (0.05),
  `sponge_clearance_cells`, `wall_model_receipt_error` (the smaller of the stored flat-plate and channel errors, at most `PLATE_TOL`; fails when none is stored), and a window that needed the viscosity floor fails with the reason.
- Refit (`refit.py`): per-window ratio `cd/cd_hangar` (the vehicle's own Stage-1 coefficient at the window's speed, same reference area and density), pooled by DerSimonian & Laird 1986,
  `tau^2 = max(0, (Q - (k-1)) / (S1 - S2/S1))`, `w* = 1/(se^2 + tau^2)`; the multiplier Stage 1 samples is Normal(pooled, sqrt(se^2 + tau^2)) as a **lognormal with that mean** per member. Only rows with `ok` enter. Speed scales as `d^(-1/2)`
  for the glider and USV (drag ~ v^2 at fixed propulsive force); the UAS takes d directly. Budget `ci` never refits.

### 14.5 Receipts

| Job, group | Claim | Tolerance | State |
|---|---|---|---|
| `pm.stage3.lbm`, `LBM jax` | `Poiseuille: curvature of the steady profile g_eff/g`; `relative residual of the parabola fit` | 1 %; 0.5 % | pass |
| | `Cavity Re=100 max \|u-u_Ghia\| on the vertical centreline / U_lid` (and `\|v-v_Ghia\|`) | 0.04 of the lid speed | pass (0.033 and 0.025 in the stored table) |
| | `Taylor-Green decay: fitted viscosity / analytic` | 3 % | pass |
| | `Sphere Cd at Re=100, XLB halfway bounce-back (staircase), d=8` (also Re=1000 d=10, Re=1e4 d=12) | 10 % of Morrison 2013 | **FAIL by design** until a run that reaches 10 % is stored (staircase error about 1/d) |
| `pm.stage3.nest`, `LBM nest` | `Vehicle-following nest, uniform flow: \|F\| / (rho U^2 d^2) (zero expected)`; `Nest crossing a shear layer: max \|dM\|/M per step`; `... interpolation residual at the first sponge layer / u_lat`; shift counts | 1e-4; 1e-3; 0.005; at least 10 shifts | pass |
| | `Sphere Cd at Re=100, Richardson-extrapolated from d=[8, 12] (order 1.00)` (also Re=1000, 1e4) in group `LBM native sphere` | 10 % of Morrison 2013 | Re=100 passes (1.0155 against 1.0382, -2.2 %); Re=1e3 (needs d at least 24) and Re=1e4 (d at least 40) are **FAIL until stored** |
| `pm.stage3.wallmodel`, `LBM wall model` | `Log law inverted for u_tau (kappa 0.41, B 5.2) at y+ = 100` | 0.5 % | pass |
| | `Channel (Re_tau 1000): wall stress / (g h)` | 1 % | pass |
| | `Channel: bulk C_f at Re_b = 3.95e+04 vs Dean` | 10 % of Dean 1978 | pass (0.00513 against 0.00518) |
| | `Channel: matching-point y+`, `matching height y/h`, `bounce-back tangential exchange / wall shear` | 30 to 300; below 0.3; below 0.01 | pass |
| | `Flat plate C_f vs ITTC-57 at Re_L >= 1e6, wall-modelled with inflow turbulence` | 10 % of ITTC-57 | **FAIL until a 1.8 h run is stored**; an earlier CI-size plate was 71 % low and the comparison was ill-posed (ITTC-57 is turbulent, the plate was laminar) |

The figures in the State column are the values in `runs/receipts.json` written 2026-10-29 00:36. That table predates bb68642, which made the sphere and flat-plate rows
required, so a fresh `python -m cafe.pm receipts` shows those rows as failures until the slow runs are stored (`--slow`, or the commands in the row notes). A stored FAIL stays a FAIL.
The earlier XLB staircase values, for scale: Cd 1.347 against Morrison's 1.038 at Re = 100 (d = 8, +30 %), 0.769 against 0.484 at Re = 1000 (d = 10, +59 %), 0.681 against 0.394 at
Re = 1e4 (d = 12, +73 %); the native kernel at Re = 100 gave 1.2087 on d = 12 (+16 %) and 1.0155 extrapolated. The lead's log records a working hypothesis for the Re = 100 excess, an effective diameter of d + 1; it is untested.
