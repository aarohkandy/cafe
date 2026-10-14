"""Public ocean data for the mission box, used when the weather files carry no ocean:

  currents  HYCOM GOFS 3.1 analysis (expt_93.0): 3-D, 1/12 deg, 3-hourly, Jan 2018 - Sep 2024 (OPeNDAP; the
            GLBv grid until Feb 2020, the GLBy grid from Dec 2018)
  waves     NOAA WAVEWATCH III global (NWW3_Global_Best): Hs, peak period, peak direction, hourly, 0.5 deg (ERDDAP)

Each request is cut to the box/time window, fetched once and cached under /work/ocean, so a mission or
reachability map re-run costs nothing. If a server is down the caller falls back to labelled estimates.
"""
import datetime as dt, hashlib, json, os, pathlib, urllib.error, urllib.parse, urllib.request
import numpy as np

CACHE = pathlib.Path(os.environ.get("CAFE_WORK", "/work")) / "ocean"
HYCOM = ("https://tds.hycom.org/thredds/dodsC/GLBy0.08/expt_93.0/uv3z",     # same experiment, same units and
         "https://tds.hycom.org/thredds/dodsC/GLBv0.08/expt_93.0/uv3z")     # 0-360 longitudes; first that covers t0
WW3 = "https://coastwatch.pfeg.noaa.gov/erddap/griddap/NWW3_Global_Best"
WW3_180 = "https://pae-paha.pacioos.hawaii.edu/erddap/griddap/ww3_global_lon180"
EPOCH = dt.datetime(2000, 1, 1)


def _key(*a):
    return hashlib.sha1(json.dumps(a, default=str).encode()).hexdigest()[:16]


def currents(t0, hours, lat_range, lon_range, max_depth=250.0):
    """-> dict(t_s [seconds after t0], depth [m, positive down], lat, lon (0-360), u, v [t, depth, lat, lon] m/s,
    floor [lat, lon] approximate seafloor depth (nan = deeper than max_depth))."""
    lo0, lo1 = sorted(np.mod(lon_range, 360.0))
    key = _key("hycom", t0.isoformat(), round(hours, 2), [round(x, 3) for x in lat_range], [round(lo0, 3), round(lo1, 3)], max_depth)
    f = CACHE / f"hycom_{key}.npz"
    if f.exists():
        z = np.load(f)
        return {k: z[k] for k in z.files}
    import netCDF4
    want0 = (t0 - EPOCH).total_seconds() / 3600 - 3
    want1 = want0 + hours + 6
    spans = []
    for url in HYCOM:
        ds = netCDF4.Dataset(url)
        th = ds["time"][:]                               # hours since 2000-01-01
        k = np.where((th >= want0) & (th <= want1))[0]
        if len(k):
            break
        spans.append(f"{EPOCH + dt.timedelta(hours=float(th[0])):%Y-%m-%d} to {EPOCH + dt.timedelta(hours=float(th[-1])):%Y-%m-%d}")
    else:
        raise ValueError(f"HYCOM has no data for {t0:%Y-%m-%d} (covers {', '.join(spans)})")
    lat, lon, dep = ds["lat"][:], ds["lon"][:], ds["depth"][:]
    j = np.where((lat >= min(lat_range) - 0.1) & (lat <= max(lat_range) + 0.1))[0]
    i = np.where((lon >= lo0 - 0.1) & (lon <= lo1 + 0.1))[0]
    d = np.where(dep <= max_depth)[0]
    d = np.r_[d, d[-1] + 1] if d[-1] + 1 < len(dep) else d
    sl = (slice(k[0], k[-1] + 1), slice(d[0], d[-1] + 1), slice(j[0], j[-1] + 1), slice(i[0], i[-1] + 1))
    u = np.ma.filled(ds["water_u"][sl].astype(float), np.nan)
    v = np.ma.filled(ds["water_v"][sl].astype(float), np.nan)
    depth = np.asarray(dep[d], float)
    # seafloor: first depth level that is missing everywhere in time
    wet = ~np.isnan(u).all(0)                               # [depth, lat, lon]
    floor = np.where(wet.all(0), np.nan, depth[np.argmin(wet, axis=0)])
    out = dict(t_s=(np.asarray(th[k], float) - (t0 - EPOCH).total_seconds() / 3600) * 3600, depth=depth,
               lat=np.asarray(lat[j], float), lon=np.asarray(lon[i], float), u=u, v=v, floor=floor)
    CACHE.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(f, **out)
    return out


def _get(url):
    """GET with retries: ERDDAP throws the odd 5xx/timeout under load. A 4xx is an answer, not a hiccup."""
    import time
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=120) as r:
                return r.read().decode()
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt == 2 or (isinstance(e, urllib.error.HTTPError) and e.code < 500):
                raise
            time.sleep(5 * 3 ** attempt)


def waves(t0, hours, lat_range, lon_range):
    """-> dict(t_s, lat, lon (0-360), hs [m], tp [s], dir_from [deg, nautical]) on the WW3 grid."""
    lo0, lo1 = sorted(np.mod(lon_range, 360.0))
    key = _key("ww3", t0.isoformat(), round(hours, 2), [round(x, 3) for x in lat_range], [round(lo0, 3), round(lo1, 3)])
    f = CACHE / f"ww3_{key}.npz"
    if f.exists():
        z = np.load(f)
        return {k: z[k] for k in z.files}
    ta = (t0 - dt.timedelta(hours=1)).strftime("%Y-%m-%dT%H:00:00Z")
    tb = (t0 + dt.timedelta(hours=hours + 1)).strftime("%Y-%m-%dT%H:00:00Z")
    la0, la1 = min(lat_range) - 0.5, max(lat_range) + 0.5
    w180 = lambda x: (x + 180.0) % 360.0 - 180.0
    # the same UH/NCEP model from two servers: NOAA's copy (0-360 lon) proxies PacIOOS, and the proxy has
    # broken before while PacIOOS's own -180..180 copy kept working
    sources = [(WW3, lo0 - 0.5, lo1 + 0.5)]
    if w180(lo0 - 0.5) < w180(lo1 + 0.5):               # (not across the dateline)
        sources.append((WW3_180, w180(lo0 - 0.5), w180(lo1 + 0.5)))
    text, errs = None, []
    for base, a, b in sources:
        sel = f"[({ta}):({tb})][(0.0)][({la0}):({la1})][({a}):({b})]"
        url = base + ".csv?" + ",".join(v + urllib.parse.quote(sel) for v in ("Thgt", "Tper", "Tdir"))
        try:
            text = _get(url)
            break
        except (urllib.error.URLError, TimeoutError) as e:
            errs.append(f"{base.rsplit('/', 1)[-1]}: {e}")
    if text is None:
        raise ValueError("WAVEWATCH III unavailable (" + "; ".join(errs) + ")")
    rows = [l.split(",") for l in text.splitlines()[2:] if l.strip()]
    if not rows:
        raise ValueError("WAVEWATCH III returned no data for this box/time")
    tt = sorted({r[0] for r in rows}); la = sorted({float(r[2]) for r in rows}); lo = sorted({float(r[3]) for r in rows})
    shape = (len(tt), len(la), len(lo))
    hs, tp, di = (np.full(shape, np.nan) for _ in range(3))
    ti = {t: n for n, t in enumerate(tt)}; ji = {x: n for n, x in enumerate(la)}; ii = {x: n for n, x in enumerate(lo)}
    num = lambda s: float(s) if s not in ("", "NaN") else np.nan
    for r in rows:
        a = (ti[r[0]], ji[float(r[2])], ii[float(r[3])])
        hs[a], tp[a], di[a] = num(r[4]), num(r[5]), num(r[6])
    secs = np.array([(dt.datetime.strptime(t, "%Y-%m-%dT%H:%M:%SZ") - t0).total_seconds() for t in tt])
    out = dict(t_s=secs, lat=np.array(la), lon=np.mod(np.array(lo), 360.0), hs=hs, tp=tp, dir_from=di)
    CACHE.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(f, **out)
    return out


if __name__ == "__main__":
    t0 = dt.datetime(2023, 3, 7, 17)
    c = currents(t0, 6, (9.5, 10.5), (-95.5, -94.5))
    print("HYCOM", c["u"].shape, "depths", c["depth"][:6], "...", c["depth"][-1], "surface u mean", np.nanmean(c["u"][:, 0]))
    assert c["u"].shape[1] == len(c["depth"]) and np.isfinite(c["u"][:, 0]).any()
    c2 = currents(t0, 6, (9.5, 10.5), (-95.5, -94.5))          # cached
    assert np.array_equal(np.nan_to_num(c["u"]), np.nan_to_num(c2["u"]))
    try:
        w = waves(t0, 6, (9.5, 10.5), (-95.5, -94.5))
        print("WW3 Hs", np.nanmean(w["hs"]), "Tp", np.nanmean(w["tp"]))
    except Exception as e:
        print("WW3 unavailable right now:", type(e).__name__, str(e)[:120])
    print("ocean ok")
