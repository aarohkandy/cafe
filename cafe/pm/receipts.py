"""`python -m cafe.pm receipts [--broken YAML] [--slow] [--only NAME,..] [--json OUT]`: every receipt in one table.

Runs the existing app's receipts (cafe/receipts.py) and every pre-mission module's `receipts()`, plus the wave-direction
receipts defined here, and normalises each record `cafe.receipts` kept to one row:

    {id, module, name, value, reference, tolerance, unit, ok, kind: pass|fail|context, source, note}

pass/fail rows have a boolean `ok`; context rows (shown for orientation, or "this input is absent here") have ok = null and
never count as failures. A bracket receipt's reference is the middle of its interval and its tolerance the half width (the
note says `bracket [lo, hi]`); a receipt's note says whether the tolerance is relative or absolute. A receipt function that
raises becomes a failing row, and so does one that records nothing (a required check that did not happen is not "fine"). Context rows
are for orientation and for optional inputs that are absent here. Nothing is relabelled: a stored FAIL stays a FAIL.

Slow receipts. Some take a long time on 2 CPUs: the emulator's n = 500 kriging (about 35 min), ArduCopter SITL and the 20 min sortie
(about 5), the app's CalculiX FEA (about 60). `--slow` runs them and stores their rows in $CAFE_DATA/receipts/<group>.json with the
git sha, a code digest, the date and the host. A default run reads them back (a stored FAIL stays a FAIL).
A required group with no stored result, or one made by
different code, is a FAIL row `<group>:not_run` whose note gives the command and the time it takes: "not run" is never reported as fine.
The digest is pipeline.code_digest() (the whole cafe/pm tree + config + platforms) for pm groups and the hash of cafe/*.py for the app's;
a finer per-group file list would miss a dependency, so any edit of the tree makes every stored result stale. Also under `--slow`: the
wall-model flat plate and the native-kernel sphere Re = 100 are rerun (the sphere into a scratch directory, never over the stored
file); their stored-file contracts belong to cafe.pm.stage3. The multi-hour GPU/CPU runs (`python -m cafe.pm.stage3.lbm slow`,
`python -m cafe.pm.dtmb5415 run`) stay their own commands; this one only reads what they stored.

Broken configuration. `--broken tests/fixtures/broken/wave_direction.yaml` sets $CAFE_PM_OVERLAY to that yaml for this run
(cafe.pm.env.conventions reads `waves.direction_convention` from it, so UMWM's angles are read with WW3's convention). The
exit code is then inverted, because the point is that the receipts notice: 0 if at least one receipt failed, 1 if the broken
configuration passed everything (what `make broken` and the CI job check). The table goes to runs/receipts_broken.json.
"""
import contextlib, datetime as dt, hashlib, importlib, io, json, math, os, pathlib, platform, re, tempfile, time

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[2]
SYNTH_MS, SYNTH_FROM_DEG = 7.0, 75.0          # the synthetic fixture: a 7 m/s trade wind from the east-north-east
ALIGN_MAX_DEG, WDIR_MAX_DEG, STOKES_DIR_MAX_DEG, FIT_DIR_MAX_DEG = 25.0, 0.5, 1.0, 30.0


def _say(s):
    print(s, flush=True)


def data_root():
    return pathlib.Path(os.environ.get("CAFE_DATA", "/data"))


# ------------------------------------------------------------------ normalising one record


def _num(x):
    """float, or None when it is not finite (JSON has no inf / nan)."""
    return float(x) if x is not None and math.isfinite(x) else None


def _ident(module, text, seen):
    base = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:72]
    seen[base] = seen.get(base, 0) + 1
    return f"{module}/{base}" + (f"-{seen[base]}" if seen[base] > 1 else "")


def _row(module, d, seen):
    """One cafe.receipts record -> the table row."""
    ctx = d.get("kind") == "context"
    note = []
    if d.get("kind") == "bracket":
        ref, tol = (d["lo"] + d["hi"]) / 2, (d["hi"] - d["lo"]) / 2
        note.append(f"bracket [{d['lo']:.6g}, {d['hi']:.6g}]")
    elif ctx:
        ref, tol = d["reference"], None
        note.append("context: shown for orientation, never a pass")
    else:
        ref, tol = d["reference"], d["tol"]
        note.append(("relative" if d["rel"] else "absolute") + f" tolerance, error {d['error']:.4g}")
    if not (math.isfinite(d["value"]) and math.isfinite(ref)):
        note.append(f"value {d['value']!r}, reference {ref!r}")
    ok = None if ctx else bool(d["ok"])
    return dict(id=_ident(module, f"{d['group']} {d['claim']}", seen), module=module, name=f"{d['group']}: {d['claim']}", value=_num(d["value"]),
                reference=_num(ref), tolerance=_num(tol), unit=d.get("unit", ""), ok=ok, kind="context" if ctx else "pass" if ok else "fail",
                source=d.get("source", ""), note="; ".join(note))


def _extra_row(module, name, failed, note, seen, ident=None):
    """A row for something that is not a cafe.receipts record: a receipt function that raised or recorded nothing, or a slow group not run."""
    return dict(id=ident or _ident(module, name, seen), module=module, name=name, value=None, reference=None, tolerance=None, unit="",
                ok=False if failed else None, kind="fail" if failed else "context", source="cafe.pm.receipts", note=note)


# ------------------------------------------------------------------ the synthetic trade-wind fixture and the wave-direction receipts


def synthetic_cache(root):
    """A 3 x 4 point GriddedEnv cache (wrf.zarr, umwm.zarr, umwmspec.zarr) built from first principles: a steady 7 m/s trade wind from
    75 deg, UMWM `wdir` its direction (math radians toward), `mwd` 10 deg and `dwd` 20 deg counter-clockwise of it, and a restart spectrum
    that is one UMWM direction bin (the one nearest `dwd`) with E ~ f^-5. No cafe.pm.env.conventions call: the angles are cos/sin of
    the east/north components, so the expected directions do not depend on the code the receipts test."""
    import warnings
    import xarray as xr
    warnings.filterwarnings("ignore", message="Consolidated metadata")
    root = pathlib.Path(root) / "orca"
    root.mkdir(parents=True, exist_ok=True)
    lat, lon = np.array([-2.0, 0.0, 2.0]), np.array([190.0, 192.0, 194.0, 196.0])
    t = np.array(["2023-03-04T00:00:00", "2023-03-04T06:00:00"], "datetime64[ns]")
    shape = (len(t), len(lat), len(lon))
    a = np.radians(SYNTH_FROM_DEG)
    u, v = -SYNTH_MS * np.sin(a), -SYNTH_MS * np.cos(a)
    coords = dict(time=t, lat=lat, lon=lon)
    full = lambda x: (("time", "lat", "lon"), np.full(shape, x))
    static = lambda x: (("lat", "lon"), np.full(shape[1:], x))
    wdir = math.atan2(v, u)
    xr.Dataset(dict(U10=full(u), V10=full(v), RAINNC=full(0.0), RAINC=full(0.0), COSALPHA=static(1.0), SINALPHA=static(0.0)), coords=coords,
               attrs=dict(TITLE="synthetic trade wind", source="cafe.pm.receipts.synthetic_cache")).to_zarr(root / "wrf.zarr", mode="w")
    xr.Dataset(dict(swh=full(1.5), mwp=full(7.0), dwp=full(9.0), mss=full(0.01), dcp=full(14.0), ust=full(0.25), wdir=full(wdir),
                    mwd=full(wdir + math.radians(10.0)), dwd=full(wdir + math.radians(20.0)), seamask=static(1), depth=static(4000.0)),
               coords=coords, attrs=dict(source="synthetic")).to_zarr(root / "umwm.zarr", mode="w")
    f = 0.0313 * 1.12246 ** np.arange(37)
    th = -np.pi + (np.arange(32) + 0.5) * 2 * np.pi / 32
    k = (2 * np.pi * f) ** 2 / 9.81
    j = int(np.argmin(np.abs(np.angle(np.exp(1j * (th - wdir - math.radians(20.0)))))))
    F = np.zeros((len(th), len(f)))
    F[j] = 1e-3 * k ** -4.0                                              # E(f) ~ f^-5 in a single direction bin
    pts = [(x, y) for y in lat for x in lon]
    n = len(pts)
    xr.Dataset(dict(F=(("time", "point", "th", "f"), np.broadcast_to(F, (len(t), n) + F.shape).copy()),
                    k=(("time", "point", "f"), np.broadcast_to(k, (len(t), n, len(f))).copy()),
                    plon=(("point",), np.array([p[0] for p in pts])), plat=(("point",), np.array([p[1] for p in pts]))),
               coords=dict(time=t, f=f, th=th)).to_zarr(root / "umwmspec.zarr", mode="w")
    return pathlib.Path(root).parent


def _dang(a, b):
    """Absolute angle between two compass directions, degrees in [0, 180]."""
    return np.abs((np.asarray(a) - np.asarray(b) + 180.0) % 360.0 - 180.0)


def _stokes_native(F, k, f, th):
    """UMWM's surface Stokes drift (east, north) straight from a restart spectrum F(th, f) [m^4 rad^-1]: sum 2 w k F k dk dth (cos th, sin th)
    in UMWM's own angles (radians counter-clockwise from east, toward). It does not use cafe.pm.env.conventions."""
    w = 2 * np.pi * f
    wt = 2 * w * k * k * (k * np.gradient(np.log(k)))
    dth = 2 * np.pi / len(th)
    return dth * np.array([np.einsum("tf,f,t->", F, wt, np.cos(th)), np.einsum("tf,f,t->", F, wt, np.sin(th))])


def _direction_receipts(label, cache, max_points=800, n_spec=200):
    """Wave-direction receipts on the GriddedEnv in `cache`; the same set runs on the synthetic fixture and on the real cache."""
    from cafe import receipts as R
    from . import config
    from .env import conventions as cv, waves
    from .env.environment import GriddedEnv
    env = GriddedEnv(cache, config.env_sigmas())
    S = env.spec
    g = f"Wave direction ({label})"
    ts = np.array([x for x in S["t"] if env.tu.x[0] <= x <= env.tu.x[-1]])
    ts = ts[:: max(1, len(ts) // 4)][:4]
    sel = np.arange(len(S["lon"]))[:: max(1, len(S["lon"]) // max_points)]
    lon, lat = np.tile(S["lon"][sel], len(ts)), np.tile(S["lat"][sel], len(ts))
    t = np.repeat(ts, len(sel))
    ok = env.inside(lon, lat, t)                                    # the restart lattice reaches the edge of the UMWM box, WRF's is smaller
    lon, lat, t = lon[ok], lat[ok], t[ok]
    w = env.waves(lon, lat, t)
    u10 = env.u10(lon, lat, t)
    wind_to, strong = cv.to_deg(u10), cv.speed(u10) > 3.0
    R.bracket(g, "median angle between the mean wave direction (UMWM mwd) and the WRF 10 m wind direction, wind > 3 m/s",
              float(np.median(_dang(w["mdir_to"].value, wind_to)[strong])), 0.0, ALIGN_MAX_DEG, "deg",
              "waves in steady trade winds lie within tens of degrees of the wind; the bound is ours, about twice what the TEPEX-C cache gives (12 deg)")
    wdir = cv.math_rad_to_compass_to(np.arctan2(env._u("wdir_n", lon, lat, t), env._u("wdir_e", lon, lat, t)))
    R.bracket(g, "median angle between UMWM wdir (the wind it was forced with), read as UMWM angles, and the WRF 10 m wind direction",
              float(np.median(_dang(wdir, wind_to)[strong])), 0.0, WDIR_MAX_DEG, "deg",
              "UMWM is forced with this WRF wind, so the two directions are the same wind (math radians toward vs east/north components)")
    err, ratio, fit_err, fit_ratio = [], [], [], []
    pick = slice(None, None, max(1, len(lon) // n_spec))
    for lo, la, tt in zip(lon[pick], lat[pick], t[pick], strict=True):
        r = env.restart_spectrum(lo, la, tt)
        native = _stokes_native(r["F"], r["k"], r["f"], r["th"])
        thc = waves.theta_compass(r["th"])
        real = waves.stokes_profile(waves.spectrum_from_restart(r["F"], r["k"], r["f"], r["th"]), r["f"], thc, 0.0)
        pw = env.waves(np.array([lo]), np.array([la]), np.array([tt]))
        E = waves.spectrum_from_params(pw["Hs"].value, pw["Tp"].value, pw["dir_to"].value, pw["mss"].value,
                                       cv.speed(env.u10(np.array([lo]), np.array([la]), np.array([tt]))), r["f"], thc)
        par = waves.stokes_profile(E, r["f"], thc, 0.0)[0]
        err.append(_dang(cv.to_deg(real), cv.to_deg(native)))
        ratio.append(np.hypot(*real) / np.hypot(*native))
        fit_err.append(_dang(cv.to_deg(par), cv.to_deg(native)))
        fit_ratio.append(np.hypot(*par) / np.hypot(*native))
    R.bracket(g, "median direction error of the Stokes drift from the restart spectrum (pipeline) vs summing cos/sin of UMWM's own angles",
              float(np.median(err)), 0.0, STOKES_DIR_MAX_DEG, "deg",
              "same spectrum, two ways to turn UMWM theta into east/north; Kenyon 1969, Breivik et al. 2016")
    R.receipt(g, "median speed of the Stokes drift from the restart spectrum (pipeline) / summed from UMWM's own k and dk", float(np.median(ratio)), 1.0,
              0.02, "", "pipeline: deep-water E(f); reference: the file's own k(f)", rel=True)
    R.bracket(g, "median direction error of the Stokes drift from the parametric spectrum (swh, dwp, dwd, mss) vs from the real restart spectrum",
              float(np.median(fit_err)), 0.0, FIT_DIR_MAX_DEG, "deg",
              "BRIEF 1.2/2.3: the parametric spectrum is the hourly stand-in for the 6-hourly real one; bound is ours, twice what the TEPEX-C cache "
              "gives (15 deg); a wrong convention gives more than 100 deg")
    R.context(g, "median speed of the Stokes drift from the parametric spectrum / from the real restart spectrum", float(np.median(fit_ratio)), 1.0, "",
              "surface.build multiplies the parametric field by the real/parametric ratio at every restart time")


def wave_direction_receipts():
    """Direction receipts on the synthetic fixture always, and on the real mission cache when one is under $CAFE_DATA/cache."""
    from cafe import receipts as R
    with tempfile.TemporaryDirectory() as d:
        _direction_receipts("synthetic trade-wind fixture", synthetic_cache(d))
    real = sorted((data_root() / "cache").glob("*/orca/umwmspec.zarr"))
    if real:
        _direction_receipts(f"cache {real[0].parents[1].name}", real[0].parents[1])
    else:
        R.context("Wave direction", f"no mission cache with restart spectra under {data_root() / 'cache'}", 0.0, 0.0, "", "python -m cafe.pm fetch --mission M")


# ------------------------------------------------------------------ which receipts run


def _app(results):
    """The existing app's quick receipts, in the order `python -m cafe.receipts` runs them (its FEA ones are the slow group `app.fea`).
    The CFD and SITL cross-check results it reads are optional inputs from earlier hangar runs: absent means a context row."""
    from cafe import receipts as R
    for f in (R.geometry_receipts, R.env_receipts, R.weather_receipts, R.dynamics_receipts, R.hull_lift_algebra_receipts, R.ocean_receipts,
              R.bem_receipts, R.fleet_receipts):
        f()
    for f, group, what in ((R.cfd_receipts, "CFD", "hangar CFD results"), (R.crosscheck_receipts, "Emulator", "the SITL cross-check")):
        n0 = len(R.OUT)
        f(results)
        if not any(d["group"] == group for d in R.OUT[n0:]):
            R.context(group, f"no stored {what} under {results}", 0.0, 0.0, "", "cafe/receipts.py reads them if they exist")


# ------------------------------------------------------------------ slow groups: run with --slow, stored, read back by default


class NotRun(Exception):
    """A required slow group has no stored result made by this code."""


def store_path(group):
    return data_root() / "receipts" / f"{group}.json"


SCOPES = {"pm": "pipeline.code_digest(): the whole cafe/pm tree + config + platforms",
          "app": "hash of cafe/*.py: the app's own modules"}


def code_digest(scope):
    if scope == "app":
        h = hashlib.sha256()
        for p in sorted((ROOT / "cafe").glob("*.py")):
            h.update(p.name.encode() + b"\0" + p.read_bytes())
        return h.hexdigest()
    from .pipeline import code_digest as whole_tree
    return whole_tree()


def _save(group, scope, rows, seconds):
    from .ledger import git_sha
    p = store_path(group)
    p.parent.mkdir(parents=True, exist_ok=True)
    rec = dict(group=group, scope=scope, code_digest=code_digest(scope), git_sha=git_sha(), date=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
               host=platform.node(), seconds=round(seconds), rows=rows)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(rec, indent=1, default=str))
    os.replace(tmp, p)


def slow_group(group, minutes, scope, runner, slow, keep=None):
    """The job for one slow group. slow: run `runner` (which records through cafe.receipts), keep the rows `keep` accepts, store them.
    Otherwise: read the stored rows if they were made by this code, else raise NotRun."""
    def job():
        from cafe import receipts as R
        if slow:
            n0, t0 = len(R.OUT), time.time()
            runner()
            rows = [d for d in R.OUT[n0:] if keep is None or keep(d)]
            R.OUT[n0:] = rows
            _save(group, scope, rows, time.time() - t0)
            return None
        p = store_path(group)
        why = f"no stored result at {p}"
        if p.is_file():
            rec = json.loads(p.read_text())
            if rec["code_digest"] == code_digest(scope):
                tag = f"[stored {rec['date']}, {rec['host']}, git {rec['git_sha'][:10]}]"
                R.OUT.extend(dict(d, source=f"{d.get('source', '')} {tag}") for d in rec["rows"])
                return None
            why = f"the stored result ({rec['date']}, {rec['host']}, git {rec['git_sha'][:10]}) was made by different code"
        raise NotRun(f"not run on this code: `python -m cafe.pm receipts --slow --only {group}` (≈{minutes} min); {why}; digest = {SCOPES[scope]}")
    return job


def _fea():
    from cafe import receipts as R
    R.fea_receipts()


def _call(mod, fn="receipts", **kw):
    return lambda: getattr(importlib.import_module(mod), fn)(**kw)


def _plate():
    """The wall-model flat plate, rerun (not stored): wallmodel.receipts reads the fields main() writes."""
    from .stage3 import wallmodel
    r = wallmodel.flat_plate(**wallmodel.PLATE_SLOW)
    r.pop("force")
    return wallmodel.receipts(plate=r)


def _nest_sphere():
    """The native-kernel sphere at Re = 100, rerun into a scratch directory (the stored file is left alone), then nest.receipts."""
    from .stage3 import nest
    old = nest.SLOW_DIR
    with tempfile.TemporaryDirectory() as d:
        nest.SLOW_DIR = pathlib.Path(d)
        try:
            nest.main(["slow", "100", "16", "14", "8", "8"])
            return nest.receipts()
        finally:
            nest.SLOW_DIR = old


def jobs(slow=False):
    """[(name, zero-argument function)]; each function records through cafe.receipts and returns anything (a str is kept as a note)."""
    d = data_root()
    gebco, tao = d / "bathy" / "gebco2026_tepex_c.npz", d / "tao"
    pm = "cafe.pm."
    sitl_groups = ("UAS sortie", "UAS SITL vs our controller")
    return [
        ("app", lambda: _app(pathlib.Path(os.environ.get("CAFE_APP_RUNS", "/work/runs")))),
        ("app.fea", slow_group("app.fea", 60, "app", _fea, slow)),
        ("pm.physics.comms", _call(pm + "physics.comms")),
        ("pm.physics.glider", _call(pm + "physics.glider")),
        ("pm.physics.usv", _call(pm + "physics.usv")),
        ("pm.physics.uas", _call(pm + "physics.uas", sitl=False, sortie=False)),
        ("pm.physics.uas.slow", slow_group("pm.physics.uas.slow", 5, "pm", _call(pm + "physics.uas", sitl=True, sortie=True), slow,
                                           keep=lambda r: r["group"] in sitl_groups)),
        ("pm.env.coare", _call(pm + "env.coare")),
        ("pm.env.waves", _call(pm + "env.waves")),
        ("pm.env.wave_direction", wave_direction_receipts),
        ("pm.env.subgrid", _call(pm + "env.subgrid")),
        ("pm.env.hycom", _call(pm + "env.hycom")),
        ("pm.env.tao", _call(pm + "env.tao", out_dir=tao if tao.is_dir() else None)),
        ("pm.env.bathy", _call(pm + "env.bathy", cache=gebco if gebco.exists() else None)),
        ("pm.stats.intervals", _call(pm + "stats.intervals")),
        ("pm.emulator", slow_group("pm.emulator", 35, "pm", _call(pm + "emulator"), slow)),
        ("pm.dtmb5415", _call(pm + "dtmb5415")),
        ("pm.stage3.lbm", _call(pm + "stage3.lbm")),
        ("pm.stage3.nest", _nest_sphere if slow else _call(pm + "stage3.nest")),
        ("pm.stage3.wallmodel", _plate if slow else _call(pm + "stage3.wallmodel")),
    ]


def collect(slow=False, only=None, log=_say):
    """Run the jobs (all, or those whose name contains one of `only`) and return the normalised rows."""
    from cafe import receipts as R
    rows, seen = [], {}
    for name, fn in jobs(slow):
        if only and not any(o in name for o in only):
            continue
        n0, t0, note, raised = len(R.OUT), time.time(), None, False
        log(f"  {name} ...")
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                ret = fn()
            note = ret if isinstance(ret, str) else None
        except NotRun as e:                                                     # required, and not established on this code: a failure
            raised = True
            rows.append(_extra_row(name, f"{name}: not run on this code", True, str(e), seen, ident=f"{name}:not_run"))
        except Exception as e:                                                  # a receipt that cannot run is a failed receipt
            raised = True
            rows.append(_extra_row(name, f"{name} raised {type(e).__name__}", True, str(e)[:400], seen))
        new = R.OUT[n0:]
        rows += [_row(name, d, seen) for d in new]
        if not new and not raised:
            rows.append(_extra_row(name, note or f"{name} recorded no receipts", True, note or "the function returned without recording a receipt", seen))
        log(f"  {name:28s} {len(new):4d} records  {time.time() - t0:6.1f} s")
    return rows


def summary(rows):
    c = {k: sum(r["kind"] == k for r in rows) for k in ("pass", "fail", "context")}
    lines = [f"{c['pass']} pass, {c['fail']} fail, {c['context']} context ({len(rows)} rows)"]
    for r in rows:
        if r["kind"] == "fail":
            lines.append(f"FAIL {r['id']}: {r['name']}: value {r['value']} {r['unit']} ({r['note']})")
    return c, "\n".join(lines)


def run(slow=False, only=None, broken=None, out=None, log=_say):
    """-> (rows, exit code). `broken`: the overlay yaml to apply for this run (exit code inverted, see the module docstring)."""
    from .env import conventions as cv
    old = os.environ.get(cv.OVERLAY_ENV)
    if broken:
        if not pathlib.Path(broken).is_file():
            raise FileNotFoundError(f"broken configuration {broken}: no such file")
        os.environ[cv.OVERLAY_ENV] = str(pathlib.Path(broken).resolve())
        log(f"broken configuration {broken}: waves.direction_convention = {cv.wave_direction_convention()}")
    try:
        rows = collect(slow, only, log)
    finally:
        if old is None:
            os.environ.pop(cv.OVERLAY_ENV, None)
        else:
            os.environ[cv.OVERLAY_ENV] = old
    out = pathlib.Path(out or ROOT / "runs" / ("receipts_broken.json" if broken else "receipts.json"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, indent=1, allow_nan=False))
    counts, text = summary(rows)
    log(text)
    log(f"table: {out}")
    failed = counts["fail"] > 0
    if broken:
        log("the broken configuration failed "
            + (f"{counts['fail']} receipts, as required" if failed else "NO receipt: the receipts cannot see a wrong wave-direction convention"))
        return rows, 0 if failed else 1
    return rows, 1 if failed else 0
