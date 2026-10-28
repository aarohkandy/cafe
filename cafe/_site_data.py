"""Export the demo site's data from real runs: ./run.sh python -m cafe._site_data [chain2023 chain2018]

Writes /work/site_data/*.json; copy them to site/data/. Everything the site draws comes from here:
  land.json      Natural Earth 10 m land, clipped to the Gulf of Tehuantepec
  depth.json     NOAA ETOPO (ERDDAP etopo180) on a 4' grid, for the depth contours
  wind.json      WRF 10 m wind, 25 hourly UWIN-CM fields (2018-02-03/04) + the 2023-03-07 snapshot
  missions.json  the TEPEX chain on both dates: 8 Monte Carlo runs per drone every 10 s, verdicts, links
  shapes.json    side and plan outlines of each vehicle, projected from the meshes the CFD and FEA used
  ocean.json     HYCOM currents (0/50/100 m) and WAVEWATCH III wave height, both dates
  fullsim.json   the full simulator's verdicts for the example plan, with mission ids (the browser check is compared to it)
  hull.json      SUBOFF hull offsets, the hull-lift model curve, Roddy 1990 points, Remora dives with/without lift
"""
import datetime as dt, json, os, pathlib, sys, time, urllib.request
import numpy as np

OUT = pathlib.Path("/work/site_data")
BOX = dict(lat=(6.0, 19.0), lon=(-102.0, -87.0))          # padding around the chart's 7-18 N, 101-88 W
SITE = (10.0, -95.0)                                       # TEPEX example deployment
MISSIONS = dict(chain2023=sys.argv[1] if len(sys.argv) > 1 else "fe6a6e77",
                chain2018=sys.argv[2] if len(sys.argv) > 2 else "e7209706")


def save(name, obj):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(obj, separators=(",", ":")))
    print(f"{name}: {(OUT / name).stat().st_size / 1024:.0f} kB", flush=True)


def get(url, timeout=300):
    req = urllib.request.Request(url, headers={"user-agent": "cafe-site-export"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def land():
    from shapely.geometry import shape, box, mapping
    raw = json.loads(get("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/geojson/ne_10m_land.geojson"))
    b = box(BOX["lon"][0], BOX["lat"][0], BOX["lon"][1], BOX["lat"][1])
    polys = [shape(f["geometry"]).intersection(b) for f in raw["features"]]
    geom = [p.simplify(0.004, preserve_topology=True) for p in polys if not p.is_empty]
    rnd = lambda c: [[round(x, 4), round(y, 4)] for x, y in c]
    out = []
    for g in geom:
        for p in getattr(g, "geoms", [g]):
            if p.geom_type == "Polygon" and p.area > 1e-5:
                out.append([rnd(p.exterior.coords)] + [rnd(i.coords) for i in p.interiors])
    save("land.json", dict(source="Natural Earth 10 m land v5.1.2", polygons=out))


def depth():
    step = 4                                               # ETOPO1 is 1'; every 4th point is ~7 km
    q = (f"altitude%5B({BOX['lat'][0]}):{step}:({BOX['lat'][1]})%5D%5B({BOX['lon'][0]}):{step}:({BOX['lon'][1]})%5D")
    for host in ("coastwatch.pfeg.noaa.gov", "upwell.pfeg.noaa.gov"):     # same ERDDAP, two front ends
        try:
            rows = get(f"https://{host}/erddap/griddap/etopo180.csv?{q}").decode().splitlines()[2:]
            break
        except OSError as e:
            print(f"{host}: {e}", flush=True)
    else:
        raise RuntimeError("ETOPO unavailable from both ERDDAP hosts")
    a = np.array([[float(x) for x in r.split(",")] for r in rows])
    lats, lons = np.unique(a[:, 0]), np.unique(a[:, 1])
    z = a[:, 2].reshape(len(lats), len(lons))
    save("depth.json", dict(source="NOAA ETOPO1 (ERDDAP etopo180), every 4th point", lat0=lats[0], dlat=float(lats[1] - lats[0]),
                            lon0=lons[0], dlon=float(lons[1] - lons[0]), ny=len(lats), nx=len(lons),
                            z=z.astype(int).ravel().tolist()))


def wind():
    import netCDF4
    from cafe import env as envm
    cat = envm.catalog()
    times = [t for t in cat if t.year == 2018] + [dt.datetime(2023, 3, 7, 17)]
    lat2, lon2, *_ = envm.grid()
    la, lo = lat2[:, 0], lon2[0, :]
    j = np.where((la >= 7) & (la <= 18))[0][::4]          # every 4th 12 km cell: ~48 km between barbs
    i = np.where((lo >= -101) & (lo <= -88))[0][::4]
    frames = []
    for t in times:
        path, k = cat[t]
        with netCDF4.Dataset(path) as ds:
            u = np.asarray(ds["U10"][k])[np.ix_(j, i)]
            v = np.asarray(ds["V10"][k])[np.ix_(j, i)]
        frames.append(dict(t=t.isoformat(), snapshot=t.year == 2023,
                           u=np.round(u * 10).astype(int).ravel().tolist(), v=np.round(v * 10).astype(int).ravel().tolist()))
    save("wind.json", dict(units="0.1 m/s, east (u) and north (v)", source="WRF 10 m wind: UWIN-CM run_nosal_2018020300b (Kerns, UW) and the 2023-03-07 WRF 4.7.1 snapshot",
                           lat=np.round(la[j], 3).tolist(), lon=np.round(lo[i], 3).tolist(), frames=frames))


def ne(lat, lon):
    lat, lon = np.asarray(lat, float), np.asarray(lon, float)
    return (lat - SITE[0]) * 111320.0, (lon - SITE[1]) * 111320.0 * np.cos(np.radians(SITE[0]))


def missions():
    base = pathlib.Path("/work/missions")
    out = {}
    for key, mid in MISSIONS.items():
        r = json.loads((base / mid / "result.json").read_text())
        m = json.loads((base / mid / "mission.json").read_text())
        drones = {}
        for d in m["drones"]:
            spec = json.loads((pathlib.Path("/work/designs") / d["design"] / "spec.json").read_text())
            res = r["drones"][d["id"]]
            tr = res["track"][::10]
            n, e = ne([s["lat"] for s in tr], [s["lon"] for s in tr])
            drones[d["id"]] = dict(
                design=d["design"], name=spec.get("name"), kind=spec["kind"],
                verdict=res["verdict"], p=res["p_success"], interval=res["p_interval"],
                reasons=res["reasons"], battery_p50=res["battery_left_p50"], legs=res["legs"],
                t=[s["t"] for s in tr], n=np.round(n, 1).T.tolist(), e=np.round(e, 1).T.tolist(),
                z=np.round(np.array([s["z"] for s in tr]), 1).T.tolist(),
                battery=np.round(1 - np.array([s["wh"] for s in tr]) / spec["battery_wh"], 3).T.tolist())
        links = [dict(a=l["a"], b=l["b"], max_m=l["max_m"], verdict=l["verdict"], p=l["p_success"],
                      t=l["timeline"]["t"], sep=l["timeline"]["nominal"]) for l in r["links"]]
        out[key] = dict(t0=m["t0"], env=r["env"], frozen=r["env_frozen"], fleet=r["fleet"], drones=drones, links=links,
                        plan=m)
    save("missions.json", out)


def outline(mesh, axes):
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    tri = mesh.vertices[mesh.faces][:, :, axes]
    polys = [Polygon(t) for t in tri if Polygon(t).area > 1e-10]
    u = unary_union(polys).simplify(0.002 * mesh.extents.max())
    g = max(getattr(u, "geoms", [u]), key=lambda p: p.area)
    return [[round(x, 4), round(y, 4)] for x, y in g.exterior.coords]


def shapes():
    import trimesh
    from cafe import geom
    out = {}
    for key in ("sample-petrel", "sample-tern", "sample-quad", "sample-torpedo"):
        m = trimesh.load(f"/work/designs/{key}/mesh.stl", force="mesh")
        spec = json.loads((pathlib.Path("/work/designs") / key / "spec.json").read_text())
        out[key] = dict(name=spec.get("name"), extents=np.round(m.extents, 3).tolist(),
                        side=outline(m, [0, 2]), plan=outline(m, [0, 1]))
    sb = geom.sample_suboff()
    out["suboff"] = dict(name="DARPA SUBOFF", extents=np.round(sb.extents, 3).tolist(), side=outline(sb, [0, 2]))
    save("shapes.json", out)


def hull():
    from cafe import vehicle, geom, mission
    from cafe.hangar import load_vehicle
    c = json.loads(pathlib.Path("/work/runs/s1/suboff.incidence.json").read_text())
    L = 4.356
    cog = np.array(geom.SAMPLES["suboff"]["spec"]["cog"], float)
    cross, _ = vehicle.hull_lift(c, cog, np.zeros((3, 3)))
    q = 0.5 * c["rho"] * c["speed"] ** 2
    F = {d: vehicle.FLU2FRD @ np.asarray(c["dirs"][k]["force"]) / q for d, k in (("+x", "+x"), ("-y", "+y"))}
    M = {d: vehicle.FLU2FRD @ np.asarray(c["dirs"][k]["moment"]) / q - np.cross(cog, F[d]) for d, k in (("+x", "+x"), ("-y", "+y"))}
    curve = []
    for b in np.arange(0, 16.01, 0.25):
        cb, sb = np.cos(np.radians(b)), -np.sin(np.radians(b))
        KF, KM = vehicle.cross_k(cross[1], b)
        Fp = cb ** 2 * F["+x"] + sb ** 2 * F["-y"] + cb * sb * KF
        Mp = cb ** 2 * M["+x"] + sb ** 2 * M["-y"] + cb * sb * KM
        F0 = cb ** 2 * F["+x"] + sb ** 2 * F["-y"]
        curve.append([round(float(b), 2), round(abs(Fp[1]) / L ** 2 * 1e3, 4), round(abs(Mp[2]) / L ** 3 * 1e3, 4),
                      round(abs(F0[1]) / L ** 2 * 1e3, 4)])
    U, rho = 6.5 * 0.514444, 998.2
    qe = 0.5 * rho * U ** 2
    roddy = [[b, round(Y / (qe * L ** 2) * 1e3, 4), round(N / (qe * L ** 3) * 1e3, 4)]
             for b, (Y, N) in {4.07: (45.43, 429.81), 8.00: (155.58, 737.14), 12.03: (350.65, 977.97)}.items()]
    x_ft = np.linspace(0, 14.291667, 160)
    profile = [[round(x * 0.3048, 4), round(float(geom.suboff_radius(x)) * 0.3048, 4)] for x in x_ft]
    dives = {}
    for lift in (True, False):                              # Remora: dive 20 m and run 1.4 km, same weather and seed
        v = load_vehicle("/work/designs/sample-torpedo")
        if not lift:
            v.cross = None
        lat, lon = 21.20, -158.40
        w = dict(t0="2018-02-03T14:00", max_hours=1.0, samples=2, seed=0, drones=[dict(id="sub", vehicle=v, start=[lat, lon, 10],
                 legs=[dict(type="goto", to=[lat + 0.009, lon + 0.009, 30]), dict(type="hold", minutes=5)])])
        d = mission.run(w)["drones"]["sub"]
        tr = d["track"][::5]
        dives["with" if lift else "without"] = dict(verdict=d["verdict"], reasons=d["reasons"], t=[s["t"] for s in tr],
                                                    depth=[round(-s["z"][0], 2) for s in tr], pitch=[s["pitch"][0] for s in tr])
        print("dive", lift, d["verdict"], flush=True)
    save("hull.json", dict(curve=curve, roddy=roddy, cfd_angles=c["alphas"], profile=profile, dives=dives,
                           gci={k: round(v["gci"], 4) for k, v in c["dirs"].items()}, grids=c.get("grids")))


def vehicles():
    """What the in-browser quick check needs from each characterized design: power against speed through the
    fluid from ctrl._level_power (CFD drag + propeller model + hotel load), speeds, battery, windage, limits."""
    from cafe import ctrl
    from cafe.hangar import load_vehicle
    from cafe.mission import SEA_LIMIT_HS
    out = {}
    for key in ("sample-petrel", "sample-tern", "sample-quad"):
        v = load_vehicle(f"/work/designs/{key}")
        spec = json.loads((pathlib.Path("/work/designs") / key / "spec.json").read_text())
        res = json.loads((pathlib.Path("/work/designs") / key / "result.json").read_text())
        d = dict(name=spec["name"], kind=v.kind, family=ctrl.family(v), battery_wh=v.battery_wh, hotel_w=v.hotel_w,
                 cruise=round(float(ctrl.cruise_speed(v)), 3), vmax=round(float(ctrl.max_speed(v)), 3), length=round(v.length, 3))
        if d["family"] == "glider":
            lim = res["hangar"]["limits"]
            d.update(glide_speed=round(lim["glide_speed_sim"], 3), band=lim["glide_band"], rated_depth=round(lim["rated_depth_m"], 1),
                     yo_s=round(lim["glide_yo_s"], 1))
        else:
            vs = np.round(np.linspace(0, d["vmax"], 25), 3)
            pw = [ctrl._level_power(v, float(V)) for V in vs]
            d["power"] = [[float(V), round(float(P), 2)] for V, (P, ok) in zip(vs, pw) if np.isfinite(P)]
        if v.kind == "usv":
            d["windage_cda"] = round(float(v.windage[0]), 4)
            d["hs_limit"] = SEA_LIMIT_HS[v.limits.get("design_category", "C")]
            d["design_category"] = v.limits.get("design_category", "C")
            R = np.interp(d["cruise"], *v.resistance)
            P0 = ctrl._level_power(v, d["cruise"])[0] - v.hotel_w
            d["drive_eff"] = round(float(R * d["cruise"] / P0), 3)       # thrust power / electrical, near cruise
        out[key] = d
        print(key, {k: d[k] for k in ("cruise", "vmax", "battery_wh")}, flush=True)
    save("vehicles.json", out)


HYCOM_DEADLINE_S = int(os.environ.get("HYCOM_DEADLINE_S", 900))     # per date; after that the date is left out of ocean.json


def _hycom(key, t0, lat_r, lon_r):
    """HYCOM currents at 0, 50 and 100 m for the 24 h from t0, or None. The local cache (with its coordinates) is
    read first and needs no network; otherwise each URL in oc.HYCOM is tried in turn until the deadline."""
    import netCDF4
    from cafe import ocean as oc
    cache = OUT / f"_hycom_{key}.npz"
    want0 = (t0 - oc.EPOCH).total_seconds() / 3600
    z = dict(np.load(cache)) if cache.exists() else {}
    if "lat" in z:
        return z
    deadline = time.time() + HYCOM_DEADLINE_S
    for url in oc.HYCOM:
        name = url.split("dodsC/")[1]
        ds = None
        for attempt in range(1, 100):                     # the THREDDS server times out under load: back off, then give up on this URL
            try:
                ds = netCDF4.Dataset(url)
                th = ds["time"][:]
                break
            except (OSError, RuntimeError) as e:
                ds = None
                wait = min(30 * attempt, 120)
                if time.time() + wait > deadline:
                    break
                print(f"{key}: {name} failed ({e}); retry in {wait} s", flush=True)
                time.sleep(wait)
        if ds is None:
            print(f"{key}: {name} unavailable, trying the next URL", flush=True)
            continue
        k = np.where((th >= want0) & (th <= want0 + 24))[0]
        if not len(k):
            continue                                       # this experiment does not cover the date
        lat, lon, dep = ds["lat"][:], ds["lon"][:], ds["depth"][:]
        j = np.where((lat >= lat_r[0]) & (lat <= lat_r[1]))[0]
        i = np.where((lon >= lon_r[0] % 360) & (lon <= lon_r[1] % 360))[0]
        dk = [int(np.argmin(abs(dep - d))) for d in (0, 50, 100)]
        js, is_ = slice(j[0], j[-1] + 1, 3), slice(i[0], i[-1] + 1, 3)      # every 3rd point: 0.24 deg

        def grab(var, kk, d):                              # one time and depth per request: big strided reads trip the DAP server
            for attempt in range(4):
                try:
                    return np.ma.filled(ds[var][kk, d, js, is_].astype(float), np.nan)
                except RuntimeError as e:
                    print(f"retry {var} t{kk} d{d}: {e}", flush=True)
                    time.sleep(5 * (attempt + 1))
            raise RuntimeError(f"HYCOM {var} t{kk} d{d} failed 4 times")
        try:
            for var in ("water_u", "water_v"):
                if var not in z:
                    a = np.array([[grab(var, kk, d) for d in dk] for kk in k])
                    z[var] = np.where(np.isnan(a), -9999, np.round(a * 100)).astype(int)    # cm/s; -9999 = land/seafloor
        except RuntimeError as e:
            print(f"{key}: {e}; trying the next URL", flush=True)
            continue
        z.update(source=np.str_(name), t=(np.asarray(th[k], float) - want0) * 3600,
                 depths=np.asarray([float(dep[d]) for d in dk]), lat=np.round(lat[js], 3), lon=np.round(np.asarray(lon[is_]) - 360, 3))
        OUT.mkdir(parents=True, exist_ok=True)
        np.savez(cache, **z)
        return z
    return None


def ocean():
    """HYCOM currents at 0, 50 and 100 m and WAVEWATCH III wave height over the gulf, for both dates. A date whose
    currents cannot be fetched is left out (the page then says which dates have real currents)."""
    from cafe import ocean as oc
    lat_r, lon_r = (7.0, 18.0), (-101.0, -88.0)
    prev = json.loads((OUT / "ocean.json").read_text()) if (OUT / "ocean.json").exists() else {}
    out = {}
    for key, t0 in (("2018", dt.datetime(2018, 2, 3, 12)), ("2023", dt.datetime(2023, 3, 7, 12))):
        want0 = (t0 - oc.EPOCH).total_seconds() / 3600
        cur = _hycom(key, t0, lat_r, lon_r)
        if cur is None:
            print(f"{key}: HYCOM unavailable; " + ("kept the previous ocean.json entry" if key in prev else "left out of ocean.json"), flush=True)
            if key in prev:
                out[key] = prev[key]
            continue
        w = oc.waves(t0, 24.0, lat_r, lon_r)
        out[key] = dict(
            currents=dict(source=str(cur["source"]), t=cur["t"].tolist(), depths=cur["depths"].tolist(),
                          lat=cur["lat"].tolist(), lon=cur["lon"].tolist(),
                          u=cur["water_u"].ravel().tolist(), v=cur["water_v"].ravel().tolist()),
            waves=dict(t=np.round(w["t_s"] - (want0 * 3600 - (t0 - oc.EPOCH).total_seconds()), 1).tolist(),
                       lat=np.round(w["lat"], 3).tolist(), lon=np.round(np.where(w["lon"] > 180, w["lon"] - 360, w["lon"]), 3).tolist(),
                       hs=np.round(np.nan_to_num(w["hs"], nan=-1) * 10).astype(int).ravel().tolist()))
        print(key, "currents", cur["water_u"].shape, "waves", np.shape(w["hs"]), flush=True)
    if not out:
        raise RuntimeError("no currents for either date; keeping the previous ocean.json")
    save("ocean.json", out)


def fullsim():
    """Reference verdicts from the full simulator's TEPEX missions, read from their result.json, with the mission ids
    and run counts so every number is traceable. site/js/sim.check.mjs and about.html compare the browser against this."""
    base = pathlib.Path("/work/missions")
    out = {}
    for key, mid in MISSIONS.items():
        r = json.loads((base / mid / "result.json").read_text())
        m = json.loads((base / mid / "mission.json").read_text())
        drones = {}
        for did, d in r["drones"].items():
            eta = next((l["eta_min_p50"] for l in d["legs"] if l["type"] == "goto" and l.get("eta_min_p50") is not None), None)
            drones[did] = dict(verdict=d["verdict"], p=d["p_success"], interval=d["p_interval"], runs=d["runs"],
                               reasons=d["reasons"], battery_p50=d["battery_left_p50"], eta=eta)
        links = [dict(a=l["a"], b=l["b"], verdict=l["verdict"], p=l["p_success"], max_m=l["max_m"], mode=l["mode"],
                      from_min=l["from_min"], until_min=l["until_min"]) for l in r["links"]]
        out[key] = dict(mission=mid, t0=m["t0"], hours=m["max_hours"], samples=r["samples"], env=r["env"], frozen=r["env_frozen"],
                        fleet=dict(verdict=r["fleet"]["verdict"], p=r["fleet"]["p_success"], interval=r["fleet"]["p_interval"],
                                   runs=r["fleet"]["runs"], reasons=r["fleet"]["reasons"]),
                        drones=drones, links=links)
    save("fullsim.json", out)


if __name__ == "__main__":
    # SITE_STEPS=depth,hull reruns only those steps
    only = os.environ.get("SITE_STEPS")
    for f in (land, depth, wind, missions, shapes, hull, vehicles, ocean, fullsim):
        if not only or f.__name__ in only.split(","):
            f()
