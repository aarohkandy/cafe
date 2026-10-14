"""Receipts: every claim the simulator makes, checked against an analytic or published reference.

`python -m cafe.receipts [results_dir]` runs them all and exits non-zero if any fail. The app shows
the same list, so what the user sees is exactly what was tested.
"""
import json, pathlib, sys, time
import numpy as np

from cafe import geom, vehicle, dyn, env as envm

OUT = []


def bracket(group, claim, value, lo, hi, unit="", source=""):
    """Value must fall between two independent bounds."""
    ok = lo <= value <= hi
    OUT.append(dict(group=group, claim=claim, value=float(value), lo=float(lo), hi=float(hi), unit=unit, ok=bool(ok),
                    source=source, kind="bracket"))
    print(f"[{'PASS' if ok else 'FAIL'}] {group}: {claim}: {value:.4g} in [{lo:.4g}, {hi:.4g}] {unit}")


def context(group, claim, value, reference, unit="", source=""):
    """Shown for orientation only; never counted as a pass."""
    OUT.append(dict(group=group, claim=claim, value=float(value), reference=float(reference), unit=unit,
                    source=source, kind="context", ok=None))
    print(f"[ -- ] {group}: {claim}: {value:.4g} (published {reference:.4g} {unit}) — {source}")


def receipt(group, claim, value, reference, tol, unit="", source="", rel=True):
    err = abs(value / reference - 1) if rel else abs(value - reference)
    r = dict(group=group, claim=claim, value=float(value), reference=float(reference), unit=unit,
             tol=tol, rel=rel, error=float(err), ok=bool(err <= tol), source=source)
    OUT.append(r)
    print(f"[{'PASS' if r['ok'] else 'FAIL'}] {group}: {claim}: {value:.4g} vs {reference:.4g} {unit} "
          f"({'%.1f%%' % (100 * err) if rel else '%.3g' % err}, tol {tol})")
    return r


CALM = envm.Waves(0.0, 1.0, 0.0)


def _still(B, flow=(0, 0, 0)):
    return dict(flow_ned=np.broadcast_to(flow, (B, 3)).astype(float))


def dynamics_receipts():
    # 1. Archimedes from panel pressure integration: REMUS 10 m deep, level, still water
    s = geom.SAMPLES["torpedo"]
    m = s["make"]()
    v = vehicle.build("uuv", m, s["spec"])
    d = dyn.Dynamics(v, 1)
    st = dyn.State(1, len(v.actuators), p=[0, 0, 10.0])
    F, M, _ = d.panel_forces(st, dyn.quat_to_R(st.q), CALM, 0.0)
    # panels are area-scaled to the true volume (so this alone can't fail); test the RAW panel set too
    receipt("6-DOF", "Hull panels before volume correction: enclosed volume vs true hull", 1 / v.limits["panel_volume_correction"],
            1.0, 0.03, "", "discretization error the area correction removes; must be small for moments to be right")
    receipt("6-DOF", "Panel pressure integrates to buoyancy rho*g*V (direction and magnitude)", -F[0, 2],
            vehicle.RHO["water"] * 9.81 * m.volume, 0.01, "N", "Archimedes")

    # 2. Pure drift: unpowered, neutrally buoyant sub in a 0.5 m/s current ends up moving with it
    spec = dict(s["spec"]); spec["mass"] = vehicle.RHO["water"] * m.volume
    v = vehicle.build("uuv", m, spec)
    d = dyn.Dynamics(v, 1)
    st = dyn.State(1, len(v.actuators), p=[0, 0, 20.0])
    for _ in range(int(400 / 0.05)):
        d.step(st, np.zeros((1, len(v.actuators))), _still(1, (0.5, 0, 0)), 0.05, CALM)
    vn = dyn.bmv(dyn.quat_to_R(st.q), st.v)[0]
    receipt("6-DOF", "Unpowered sub drifts at current speed", vn[0], 0.5, 0.02, "m/s", "kinematics")


    # 4. Quad hover: thrust balances weight at the throttle momentum theory predicts; power vs bench data
    q = geom.SAMPLES["quad"]
    vq = vehicle.build("uav", q["make"](), q["spec"])
    dq = dyn.Dynamics(vq, 1)
    tmax = vq.actuators[0].tmax
    u_h = np.sqrt(vq.mass * 9.81 / 4 / tmax)
    st = dyn.State(1, 4, p=[0, 0, -20.0]); st.u[:] = u_h
    out = dq.step(st, np.full((1, 4), u_h), _still(1), 0.002)
    receipt("6-DOF", "Hover: vertical specific force reads -g", st.accel_body[0, 2], -9.81, 0.002, "m/s2", "IMU convention")
    # hover RPM depends only on the UIUC thrust coefficient (not on the motor efficiency fitted to bench power)
    rpm = vq.actuators[0].wmax / (2 * np.pi) * u_h * 60
    receipt("Propulsion", "1.8 kg quad, 10\" props: hover RPM", rpm, 5500, 0.08, "rpm",
            "T-Motor MN3110 bench data, 450 g/motor at ~5500 rpm; model uses UIUC APC 10x4.7 C_T only")
    context("Propulsion", "1.8 kg quad hover electrical power", out["power"][0] - vq.hotel_w, 220.0, "W",
            "motor efficiency 0.79 was fitted to this bench figure, so it is not an independent check")

    # 5. Rotational energy conserved with no damping (checks the Coriolis terms)
    vq2 = vehicle.build("uav", q["make"](), q["spec"])
    vq2.rot_damp = np.zeros(3)
    dq2 = dyn.Dynamics(vq2, 1, scale=dict(drag=np.zeros(1)))
    st = dyn.State(1, 4, p=[0, 0, -1000.0])
    st.w[:] = [3.0, 1.0, -2.0]
    e0 = 0.5 * st.w[0] @ vq2.inertia @ st.w[0]
    for _ in range(2000):
        dq2.step(st, np.zeros((1, 4)), _still(1), 0.0005)
    st.alive[:] = True
    e1 = 0.5 * st.w[0] @ vq2.inertia @ st.w[0]
    receipt("6-DOF", "Torque-free tumbling conserves rotational energy", e1, e0, 0.01, "J", "Euler's equations")

    # 6. Boat roll period from panel hydrostatics vs 2*pi*sqrt((Ixx+A44)/(rho g V GM))
    w = geom.SAMPLES["wigley"]
    mw = w["make"]()
    spec = dict(w["spec"])
    hs = geom.hydrostatics(mw, spec["mass"])
    kg = 0.6 * hs["draft"]
    spec["cog"] = [0.0, 0.0, -kg]          # boat mesh origin is the keel; FRD z is down
    hs = geom.hydrostatics(mw, spec["mass"], kg=kg)
    vw = vehicle.build("usv", mw, spec)
    vw.drag = {k: (c[0] * 0, c[1] * 0, c[2], c[3]) for k, c in vw.drag.items()}
    vw.rot_damp = np.zeros(3)
    vw.added_mass = np.zeros((6, 6))
    dw = dyn.Dynamics(vw, 1)
    st = dyn.State(1, len(vw.actuators), p=[0, 0, hs["draft"] - kg], q=dyn.euler_to_quat(np.radians(4), 0, 0))
    roll, t = [], []
    for k in range(int(12 / 0.002)):
        dw.step(st, np.zeros((1, len(vw.actuators))), _still(1), 0.002, CALM)
        roll.append(dyn.quat_to_euler(st.q)[0, 0]); t.append(st.t)
    roll = np.array(roll); t = np.array(t)
    zc = t[1:][(roll[:-1] > 0) & (roll[1:] <= 0)]
    period = np.mean(np.diff(zc)) if len(zc) > 1 else np.nan
    T_ref = 2 * np.pi * np.sqrt(vw.inertia[0, 0] / (vehicle.RHO["water"] * 9.81 * hs["displacement_m3"] * hs["gm"]))
    receipt("6-DOF", "Wigley free roll period (small angle)", period, T_ref, 0.05, "s", "linear hydrostatics, GM from geometry")


def ocean_receipts():
    """The environment's 4-D current interpolation vs the raw HYCOM grid at a grid node (independent read)."""
    import datetime as dt
    from cafe import ocean
    t0 = dt.datetime(2023, 3, 7, 18)
    try:
        c = ocean.currents(t0, 3, (9.5, 10.5), (-95.5, -94.5))
        E = envm.Env(t0, 3, (9.5, 10.5), (-95.5, -94.5))
    except Exception as e:
        context("Ocean", "HYCOM unreachable, ocean checks skipped", 0, 0, "", str(e)[:80]); return
    j, i, k = len(c["lat"]) // 2, len(c["lon"]) // 2, 8
    s = E.at(np.array([c["lat"][j]]), np.array([c["lon"][i] - 360]), np.array([c["t_s"][1]]), np.array([-c["depth"][k]]))
    receipt("Ocean", f"Current at a HYCOM grid node ({c['depth'][k]:.0f} m), east", s["current_ne"][0, 1], c["u"][1, k, j, i], 1e-3, "m/s",
            "raw HYCOM GOFS 3.1 value", rel=False)
    receipt("Ocean", f"Current at a HYCOM grid node ({c['depth'][k]:.0f} m), north", s["current_ne"][0, 0], c["v"][1, k, j, i], 1e-3, "m/s",
            "raw HYCOM GOFS 3.1 value", rel=False)


def env_receipts():
    hs, tp = envm.pm_sea(10.0)
    receipt("Environment", "PM sea: Hs at U10=10 m/s", hs, 0.22 * 100 / 9.81, 0.01, "m", "Stewart eq. 16.30")
    wv = envm.Waves(hs, tp, 0.0, n=60, seed=1)
    eta = wv.eta(0.0, 0.0, np.arange(0, 3 * 3600, 0.5))
    receipt("Environment", "Realized wave record reproduces Hs", 4 * eta.std(), hs, 0.10, "m", "4*sqrt(m0)")
    sig, _ = envm.Gusts.params(30.0, 10.0)
    receipt("Environment", "Dryden sigma_u/sigma_w at 30 m", sig[0] / sig[2], 1 / (0.177 + 0.000823 * 30 / 0.3048) ** 0.4,
            1e-9, "", "MIL-F-8785C")


def geometry_receipts():
    t = geom.sample_torpedo()
    receipt("Geometry", "REMUS hull wetted area", t.area, 0.709, 0.05, "m2", "Prestero 2001 Table 2.7")
    receipt("Geometry", "REMUS frontal area", geom.projected_area(t, 0), 0.0285, 0.03, "m2", "Prestero 2001 Table 2.7")
    w = geom.sample_wigley()
    L, B, T = 2.5, 0.25, 0.156
    hs = geom.hydrostatics(w, geom.RHO_SEA * 4 / 9 * L * B * T)
    receipt("Geometry", "Wigley draft at design displacement", hs["draft"], T, 0.03, "m", "Cb = 4/9 (analytic)")
    receipt("Geometry", "Wigley wetted surface", hs["wetted_area"], 0.661 * L * (2 * T + B), 0.03, "m2", "Kajitani 1983")
    # floating box (barge): exact KB = T/2, BM = B^2 / (12 T); a randomly triangulated box tests the integration
    import trimesh
    Lb, Bb, Db, Tb = 3.0, 1.2, 0.8, 0.3
    box = trimesh.creation.box([Lb, Bb, Db]).subdivide().subdivide()
    box = geom.normalize(box, "usv")
    hb = geom.hydrostatics(box, geom.RHO_SEA * Lb * Bb * Tb, kg=0.0)
    receipt("Geometry", "Floating box: metacentric radius BM", hb["gm"] - hb["kb"], Bb ** 2 / (12 * Tb), 0.01, "m", "BM = B^2/12T (exact)")
    receipt("Geometry", "Floating box: waterplane area", hb["waterplane_area"], Lb * Bb, 0.005, "m2", "L x B (exact)")


def bem_receipts():
    """Capytaine on the bare REMUS hull vs slender-body strip theory on the SAME hull.
    (Prestero's published values include the fins/tail cruciform, so they are context, not a target.)"""
    from cafe import hangar
    s = geom.SAMPLES["torpedo"]
    m = s["make"]()
    v = vehicle.build("uuv", m, s["spec"])
    A = np.diag(np.array(hangar.bem(m, "uuv", v.cog)["added_mass"]))
    rho = geom.RHO_SEA
    I = m.moment_inertia                       # density 1: integrals over the volume about the centroid
    x2 = (I[1, 1] + I[2, 2] - I[0, 0]) / 2     # integral of x^2 dV
    receipt("BEM", "REMUS sway added mass vs strip theory (rho*V)", A[1], rho * m.volume, 0.08, "kg",
            "slender-body strip theory, 2-D circle sections")
    bracket("BEM", "REMUS pitch added inertia between spheroid (slimmer ends) and strip theory (overshoots ends)",
            A[4], vehicle.spheroid_added_mass(1.33, 0.191, rho)[4, 4], rho * x2, "kg m2",
            "Lamb prolate spheroid of equal L, D (lower bound); strip theory (upper bound)")
    context("BEM", "REMUS surge added mass (bare hull)", A[0], 0.93, "kg",
            "Prestero 2001 used an empirical ellipsoid formula; a fuller midbody should read higher")
    context("BEM", "REMUS sway added mass (bare hull)", A[1], 35.5, "kg",
            "Prestero 2001 strip theory includes fins and tail cruciform")
    context("BEM", "REMUS pitch added inertia (bare hull)", A[4], 4.88, "kg m2",
            "Prestero 2001 strip theory includes fins, whose lever arm dominates pitch")


def cfd_receipts(results):
    """Reads hangar CFD outputs if they exist (they take minutes-hours to produce)."""
    t = results / "t1" / "torpedo.external.json"
    if t.exists():
        r = json.loads(t.read_text())
        d = r["dirs"]["+x"]
        cd = -d["force"][0] / (0.5 * r["rho"] * r["speed"] ** 2 * 0.0285)
        receipt("CFD", "REMUS bare hull Cd (frontal)", cd, 0.12, 0.25, "", "Prestero 2001: Hoerner estimate 0.11-0.13")
        re_ = r["speed"] * r["L"] / r["nu"]
        wet = 0.709
        receipt("CFD", "REMUS friction drag vs ITTC-57 flat plate", -d["viscous"][0],
                0.5 * r["rho"] * r["speed"] ** 2 * wet * 0.075 / (np.log10(re_) - 2) ** 2, 0.15, "N", "ITTC-57 line")
    w = results / "w1" / "wigley.surface.json"
    if w.exists():
        r = json.loads(w.read_text())
        ref = {0.2: 4.21, 0.3: 4.96, 0.4: 5.49}   # UT 2.5 m fixed model, Kajitani 1983 Fig 1 (digitized)
        S = 0.661 * 2.5 * (2 * 0.156 + 0.25)
        for U, res in r["speeds"].items():
            fn = float(U) / np.sqrt(9.81 * 2.5)
            k = min(ref, key=lambda f: abs(f - fn))
            ct = res["resistance"] / (0.5 * 1025 * float(U) ** 2 * S) * 1e3
            receipt("CFD", f"Wigley Ct x1e3 at Fn {fn:.2f}", ct, ref[k], 0.15, "", "Kajitani et al. 1983, UT 2.5 m fixed")


def fea_receipts():
    """CalculiX on a closed thin aluminium cylinder (R 0.1 m, t 3 mm, L 0.6 m) under 1 MPa external pressure."""
    import trimesh
    from cafe import fea
    R, t, Lc, p = 0.1, 0.003, 0.6, 1.0e6
    cyl = trimesh.creation.cylinder(radius=R, height=Lc, sections=96)
    cyl.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [0, 1, 0]))
    r = fea.solve(cyl, "shell", "al6061", thickness=t, pressure=lambda c, n: np.full(len(c), p), steps=("static", "buckle"), h=0.012)
    f = r["field"]
    mid = (np.abs(f["nodes"][:, 0]) < 0.05) & (np.hypot(f["nodes"][:, 1], f["nodes"][:, 2]) > 0.98 * R)
    receipt("FEA", "Thin cylinder, mid-length von Mises vs membrane theory", np.median(f["vm"][mid]) / 1e6,
            np.sqrt(3) / 2 * p * R / t / 1e6, 0.06, "MPa", "hoop pR/t, axial pR/2t")
    E, nu, D = fea.MATERIALS["al6061"]["E"], fea.MATERIALS["al6061"]["nu"], 2 * R
    p_wt = 2.42 * E / (1 - nu ** 2) ** 0.75 * (t / D) ** 2.5 / (Lc / D - 0.45 * (t / D) ** 0.5)
    context("FEA", "Short capped cylinder collapse (flat 3 mm end caps)", r["buckling_factor"] * p / 1e6, p_wt / 1e6, "MPa",
            "Windenburg-Trilling assumes simply supported ends; real caps restrain more, and the 3/4 follower "
            "correction is conservative for this 4-lobe mode, so no clean reference")
    # long tube: the 2-lobe collapse is end-condition free -> Bresse 2E/(1-nu^2)(t/D)^3 (hydrostatic, follower)
    tube = trimesh.creation.cylinder(radius=R, height=3.0, sections=64)
    tube.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [0, 1, 0]))
    runs = [fea.solve(tube, "shell", "al6061", thickness=t, pressure=lambda c, n: np.full(len(c), p),
                      steps=("static", "buckle"), h=0.015)["buckling_factor"] for _ in range(2)]
    Dm = D - t
    receipt("FEA", "Long tube collapse pressure (with follower-pressure correction)", runs[0] * p / 1e6,
            2 * E / (1 - nu ** 2) * (t / Dm) ** 3 / 1e6, 0.10, "MPa", "Bresse long-cylinder formula, mid-surface diameter")
    receipt("FEA", "Buckling repeats exactly on identical input", runs[1], runs[0], 1e-9, "", "determinism (single-threaded eigensolver)")
    # a real free-floating hull: the glider shape (nose, tail cone, hub). Its collapse must sit between the long-tube
    # (Bresse) and finite-length (Windenburg-Trilling, parallel section) values, and the lowest mode must be a lobar
    # PAIR (cylinders buckle in degenerate pairs; a lone lowest mode is a support or mesh artifact)
    from cafe import shapes
    Lg, Dg, tg = 1.5, 0.22, 0.007
    hull = shapes.build("glider", dict(shapes.defaults("glider"), length=Lg, diameter=Dg))[1]["hull"]
    pg = geom.RHO_SEA * 9.81 * 100
    rg = fea.solve(hull, "shell", "al6061", thickness=tg, pressure=lambda c, n: np.full(len(c), pg), steps=("static", "buckle"), h=Lg / 70)
    Lpar = Lg * (1 - 0.12 - 0.25)
    wt = 2.42 * E / (1 - nu ** 2) ** 0.75 * (tg / Dg) ** 2.5 / (Lpar / Dg - 0.45 * (tg / Dg) ** 0.5)
    bracket("FEA", "Glider hull collapse pressure (free-floating, 7 mm Al)", rg["buckling_factor"] * pg / 1e6,
            2 * E / (1 - nu ** 2) * (tg / (Dg - tg)) ** 3 / 1e6, wt / 1e6, "MPa", "Bresse long tube .. Windenburg-Trilling on the parallel section")
    f1, f2 = rg["buckling_factors_dead_load"][:2]
    receipt("FEA", "Glider hull: two lowest buckling modes are a degenerate pair", f2, f1, 0.02, "", "axisymmetric shell: lobar modes come in pairs")
    # free body with an UNBALANCED, off-centre load: 1 kN sideways at one end of the 3 m tube (net force AND
    # net moment), balanced by inertia relief (translation + rotation)
    fb = fea.solve(tube, "shell", "al6061", thickness=t, pressure=None, point_loads=[((1.5, 0.0, R), (0.0, 0.0, 1000.0), 0.02)],
                   steps=("static",), h=0.03)
    # (no supports at all: the mean rigid motion is held by equations, so the stress must be the free-free beam's): peak moment 4PL/27 at L/6 past the centre, toward the load
    ff = fb["field"]
    band = np.abs(ff["nodes"][:, 0] - 0.5) < 0.04
    receipt("FEA", "Free-free tube, end load: peak bending stress at L/6", ff["vm"][band].max() / 1e6,
            4 * 1000.0 * 3.0 / 27 * R / (np.pi * R ** 3 * t) / 1e6, 0.08, "MPa", "beam theory with inertia relief, M = 4PL/27")

    # clamped cantilevers (the quad-arm and glider-wing load cases) vs Euler-Bernoulli beam theory
    E = fea.MATERIALS["cfrp"]["E"]
    Lt, R, tw, P = 0.25, 0.008, 0.001, 10.0
    tube = trimesh.creation.cylinder(radius=R, height=Lt, sections=48)
    tube.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [0, 1, 0]))     # along x
    x0, x1 = tube.bounds[0][0], tube.bounds[1][0]
    r = fea.solve(tube, "shell", "cfrp", thickness=tw, fixed=lambda nd: nd[:, 0] <= x0 + 0.003,
                  point_loads=[(np.array([x1, 0, 0]), [0, 0, P], 0.004)], h=0.004)
    I = np.pi / 4 * (R ** 4 - (R - tw) ** 4)
    tipz = r["field"]["u"][np.argmax(r["field"]["nodes"][:, 0]), 2]
    receipt("FEA", "Clamped tube (quad arm) tip deflection", tipz * 1e3, P * Lt ** 3 / (3 * E * I) * 1e3, 0.10, "mm",
            "Euler-Bernoulli cantilever PL^3/3EI, thin-wall tube")
    receipt("FEA", "Clamped tube support reaction equals the applied load", abs(r["reaction"][2]), P, 0.01, "N", "statics")
    b, tk, Ls = 0.10, 0.010, 0.30
    slab = trimesh.creation.box([b, Ls, tk]); slab.apply_translation([0, Ls / 2, 0])
    r = fea.solve(slab, "solid", "al6061", fixed=lambda nd: nd[:, 1] <= 1e-4,
                  point_loads=[(np.array([0, Ls, tk / 2]), [0, 0, -50.0], 0.006)], h=0.004)
    tipz = np.min(r["field"]["u"][r["field"]["nodes"][:, 1] > Ls - 1e-4, 2])
    Is = b * tk ** 3 / 12
    receipt("FEA", "Clamped slab (glider wing) tip deflection", -tipz * 1e3, 50 * Ls ** 3 / (3 * fea.MATERIALS["al6061"]["E"] * Is) * 1e3,
            0.08, "mm", "Euler-Bernoulli cantilever, solid rectangular section")


def fleet_receipts():
    """Reachability (grid Zermelo) vs exact uniform-current times; link statistics vs exact geometry;
    glider speed and pump energy."""
    from types import SimpleNamespace as NS
    from cafe import reach, mission, shapes, ctrl
    V, c, D = 1.0, 0.4, 20000.0

    class FlatEnv:      # uniform current toward +north
        def at(self, lat, lon, t, z):
            n = len(lat)
            return dict(current_ne=np.tile([c, 0.0], (n, 1)), wind_ne=np.tile([c, 0.0], (n, 1)), land=np.zeros(n, bool))
    veh = NS(kind="usv", battery_wh=1e9, hotel_w=1.0, actuators=[])
    real_cruise, real_fam, real_end = ctrl.cruise_speed, ctrl.family, reach.endurance_h
    ctrl.cruise_speed = lambda v: V; reach.endurance_h = lambda *a, **k: 1e9
    try:
        r = reach.reach(veh, FlatEnv(), 10.0, -95.0, hours=12, n=121)
        rt = reach.reach(veh, FlatEnv(), 10.0, -95.0, hours=12, n=241, round_trip=True)
    finally:
        ctrl.cruise_speed, reach.endurance_h = real_cruise, real_end
    H = np.array(r["hours"], float); lat = np.array(r["lat"]); lon = np.array(r["lon"])
    c0 = len(lat) // 2
    k = int(round(D / ((lat[1] - lat[0]) * np.pi / 180 * 6371000)))
    receipt("Reach", "Time to a point 20 km downstream (uniform current)", H[c0 + k, c0], D / (V + c) / 3600, 0.02, "h", "D/(V+c), exact")
    receipt("Reach", "Time to a point 20 km upstream", H[c0 - k, c0], D / (V - c) / 3600, 0.02, "h", "D/(V-c), exact")
    # round trip: out with the current, back against it, within 12 h -> D_max = T (V^2 - c^2) / (2V)
    Hr = np.array(rt["hours"], float); latr = np.array(rt["lat"]); cr = len(latr) // 2
    north = np.where(np.isfinite(Hr[cr:, cr]))[0]
    dmax = north.max() * (latr[1] - latr[0]) * np.pi / 180 * 6371000
    receipt("Reach", "Farthest round trip downstream and back in 12 h", dmax / 1e3, 12 * 3600 * (V ** 2 - c ** 2) / (2 * V) / 1e3,
            0.08, "km", "T(V^2-c^2)/2V, exact; grid step 1.3 km")
    kx = int(round(D / ((lon[1] - lon[0]) * np.pi / 180 * 6371000 * np.cos(np.radians(10)))))
    receipt("Reach", "Time to a point 20 km across the current", H[c0, c0 + kx], D / np.sqrt(V ** 2 - c ** 2) / 3600, 0.03, "h",
            "D/sqrt(V^2-c^2) (crabbing), exact; grid directions add a little")

    # link statistics: B separates from A at 1 m/s starting 0 m apart; limit 300 m over 600 s
    A = NS(id="a", st=NS(p=np.zeros((1, 3))), done=np.zeros(1, bool), leg=np.zeros(1, int), legs=[dict(type="hold")])
    Bd = NS(id="b", st=NS(p=np.zeros((1, 3))), done=np.zeros(1, bool), leg=np.zeros(1, int), legs=[dict(type="hold")])
    lk = mission.Link(dict(a="a", b="b", max_m=300.0), {"a": A, "b": Bd}, 1)
    for t in range(1, 601):
        Bd.st.p[0, 0] = float(t)
        lk.record(float(t))
    sm = lk.summary()                          # the same summary a mission result carries
    receipt("Links", "Share of time in range, drones separating at 1 m/s past a 300 m limit", sm["in_range_p50"], 300 / 600, 0.005, "", "geometry, exact")
    receipt("Links", "Longest out-of-range gap", lk.longest[0], 300, 0.005, "s", "geometry, exact")

    # glider: a through-water performance check, so no real currents here
    import os
    os.environ["CAFE_OCEAN"] = "0"
    m, parts, hints = shapes.build("glider", shapes.defaults("glider"))
    spec = dict(name="g", mass=geom.RHO_SEA * m.volume, power_w=30, battery_wh=500, hotel_w=0.6, buoyancy_cc=400, **hints)
    vg = vehicle.build("uuv", m, spec)
    w = mission.World(dict(t0=_t0(), max_hours=1.2, samples=1, drones=[dict(id="g", vehicle=vg, start=[10.0, -95.0, 5],
                                                                            legs=[dict(type="goto", to=[10.2, -95.0, 100])])]), B=1)
    d = w.by_id["g"]
    bottoms, was = 0, True
    while w.t < 3600:
        w.tick()
        dv = bool(getattr(d.ap, "diving", [True])[0])
        bottoms += was and not dv                      # a bottom turn = one full buoyancy swing at depth
        was = dv
    n0 = d.start[0]
    receipt("Glider", "Horizontal speed made good (1 h, 5-100 m saw-tooth)", (d.st.p[0, 0] - n0) / w.t, 0.25, 0.25, "m/s",
            "Slocum-class gliders make 0.2-0.35 m/s horizontally (manufacturer-typical, not a specific vehicle)")
    pump_wh = (d.st.energy_wh[0] - vg.hotel_w * w.t / 3600)
    receipt("Glider", "Pump energy per full buoyancy swing at 100 m", pump_wh / max(bottoms, 1),
            geom.RHO_SEA * 9.81 * 100 * 2 * 400e-6 / 0.5 / 3600, 0.35, "Wh", "rho g depth x 2 dV / 0.5 pump efficiency")
    vs, t_yo = ctrl.glide_sim(vg, 5, 100)
    receipt("Glider", "Steady-glide formula vs 6-DOF yo (speed made good, 5-100 m)", ctrl.glide_speed(vg) * np.cos(np.radians(26)), vs,
            0.25, "m/s", "our 6-DOF sim incl. top/bottom turns (consistency of two models, not a measurement)")
    os.environ["CAFE_OCEAN"] = "1"


def _t0():
    from cafe import env as envm
    cat = envm.catalog()
    return next(iter(cat)).isoformat() if cat else "2023-03-07T17:00:00"


def crosscheck_receipts(results):
    """Same mission, two independent autopilots on the same physics: ours (fast mode) and ArduPilot SITL.
    Reads the pair recorded in runs/crosscheck.json (SITL runs take minutes, so they aren't rerun here)."""
    f = results / "crosscheck.json"
    if not f.exists():
        return
    c = json.loads(f.read_text())
    for drone, x in c["drones"].items():
        receipt("Emulator", f"{drone}: battery left, fast mode vs {x['firmware']}", x["fast"]["battery_left"],
                x["sitl"]["battery_left"], 0.03, "", "ArduPilot SITL flying the same physics")
        receipt("Emulator", f"{drone}: hold error p95, fast mode vs {x['firmware']}", x["fast"]["hold_p95"],
                x["sitl"]["hold_p95"], 0.5, "m", "absolute difference; both well inside the 3 m tolerance", rel=False)


if __name__ == "__main__":
    results = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path("/work/runs")
    t0 = time.time()
    geometry_receipts()
    env_receipts()
    dynamics_receipts()
    ocean_receipts()
    bem_receipts()
    fea_receipts()
    fleet_receipts()
    cfd_receipts(results)
    crosscheck_receipts(results)
    (results / "receipts.json").write_text(json.dumps(OUT, indent=1)) if results.exists() else None
    scored = [r for r in OUT if r.get("kind") != "context"]
    bad = [r for r in scored if not r["ok"]]
    print(f"{len(scored) - len(bad)}/{len(scored)} receipts pass, {len(OUT) - len(scored)} context rows ({time.time() - t0:.0f}s)")
    sys.exit(1 if bad else 0)
