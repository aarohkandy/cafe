"""Geometry: load and normalize drone meshes, built-in sample drones, hydrostatics.

Body frame everywhere: x forward, y left, z up, metres, origin at the bbox centre
(for a boat, z=0 is the keel so drafts read naturally).
"""
import pathlib, subprocess, tempfile
import numpy as np
import trimesh

RHO_SEA = 1025.0
G = 9.81
UNITS = {"m": 1.0, "cm": 0.01, "mm": 0.001, "in": 0.0254, "ft": 0.3048}
_AX = {"+x": [1, 0, 0], "-x": [-1, 0, 0], "+y": [0, 1, 0], "-y": [0, -1, 0], "+z": [0, 0, 1], "-z": [0, 0, -1]}


def _read(path):
    p = pathlib.Path(path)
    if p.suffix.lower() in (".step", ".stp", ".iges", ".igs", ".brep"):
        out = pathlib.Path(tempfile.mkdtemp()) / "m.stl"   # CAD -> triangles via gmsh's OpenCASCADE
        subprocess.run(["python3", "-c", f"""
import gmsh; gmsh.initialize(); gmsh.option.setNumber('General.Terminal',0)
v = gmsh.model.occ.importShapes({str(p)!r})
v = [e for e in v if e[0] == 3]
if len(v) > 1: gmsh.model.occ.fuse(v[:1], v[1:])   # an assembly's parts -> one closed solid
gmsh.model.occ.synchronize()
gmsh.option.setNumber('Mesh.MeshSizeFromCurvature', 24); gmsh.model.mesh.generate(2); gmsh.write({str(out)!r})"""],
                       check=True, capture_output=True)
        p = out
    m = trimesh.load(p, force="mesh")
    if not isinstance(m, trimesh.Trimesh) or len(m.faces) == 0:
        raise ValueError(f"{path}: no triangles found")
    bodies = m.split(only_watertight=False)
    if len(bodies) > 1 and all(b.is_watertight for b in bodies):   # mesh export of an assembly: overlapping shells
        m = trimesh.boolean.union(bodies, engine="manifold")
    return m


def load(path, units="auto", forward="+x", up="+z", kind="uuv"):
    """Returns the normalized mesh; when units == "auto", m.metadata["units_assumed"] says what was guessed."""
    m = _read(path)
    guessed = None
    if units == "auto":
        ext = m.extents.max()
        units = guessed = "mm" if ext > 20 else "m"   # nothing we fly is 20 m long; everything in mm is
    m.apply_scale(UNITS[units])
    fwd, upv = np.array(_AX[forward], float), np.array(_AX[up], float)
    if abs(fwd @ upv) > 0.5:
        raise ValueError("forward and up axes must differ")
    R = np.eye(4)
    R[:3, :3] = np.vstack([fwd, np.cross(upv, fwd), upv])  # rows = body axes in file coords
    m.apply_transform(R)
    m = normalize(m, kind)
    m.metadata["units_assumed"] = guessed
    return m


def normalize(m, kind):
    m = m.copy()
    m.merge_vertices()
    m.update_faces(m.nondegenerate_faces())
    m.fix_normals()
    lo, hi = m.bounds
    c = (lo + hi) / 2
    if kind == "usv":
        c[2] = lo[2]   # keel at z=0
    m.apply_translation(-c)
    return m


def report(m, kind, mass):
    """Numbers the rest of the pipeline and the UI need. Hydrostatics only for water drones."""
    L, B, H = m.extents
    r = dict(length=L, beam=B, height=H, watertight=bool(m.is_watertight),
             area=float(m.area), faces=len(m.faces),
             frontal_area=projected_area(m, 0), side_area=projected_area(m, 1), top_area=projected_area(m, 2))
    if m.is_watertight:
        r["volume"] = float(m.volume)
        r["centroid"] = m.center_mass.tolist()
    if kind == "uuv" and m.is_watertight:
        r["buoyancy_N"] = RHO_SEA * G * m.volume
        r["net_buoyancy_N"] = r["buoyancy_N"] - mass * G
    if kind == "usv":
        r.update(hydrostatics(m, mass))
    return r


def projected_area(m, axis):
    """Silhouette area looking along `axis`, rasterized (exact enough, and robust to bad meshes)."""
    a, b = [i for i in range(3) if i != axis]
    n = 400
    lo, hi = m.bounds[0][[a, b]], m.bounds[1][[a, b]]
    h = (hi - lo).max() / n
    grid = np.zeros((int((hi[0] - lo[0]) / h) + 2, int((hi[1] - lo[1]) / h) + 2), bool)
    for tri in m.triangles[:, :, [a, b]]:
        tl, th = ((tri.min(0) - lo) / h).astype(int), ((tri.max(0) - lo) / h).astype(int) + 1
        ii, jj = np.mgrid[tl[0]:th[0] + 1, tl[1]:th[1] + 1]
        p = np.stack([ii.ravel(), jj.ravel()], 1) * h + lo
        v0, v1, v2 = tri
        d = lambda p1, p2: (p[:, 0] - p2[0]) * (p1[1] - p2[1]) - (p1[0] - p2[0]) * (p[:, 1] - p2[1])
        s1, s2, s3 = d(v0, v1), d(v1, v2), d(v2, v0)
        inside = ~(((s1 < 0) | (s2 < 0) | (s3 < 0)) & ((s1 > 0) | (s2 > 0) | (s3 > 0)))
        grid[ii.ravel()[inside], jj.ravel()[inside]] = True
    return float(grid.sum() * h * h)


def below(m, z):
    return trimesh.intersections.slice_mesh_plane(m, [0, 0, -1], [0, 0, z], cap=True)


def hydrostatics(m, mass, kg=None):
    """Free-floating upright draft by bisection on displaced volume, then initial stability (GM)."""
    if not m.is_watertight:
        raise ValueError("boat mesh must be watertight to float it")
    target = mass / RHO_SEA
    if target >= m.volume:
        return dict(sinks=True, draft=None)
    lo, hi = 0.0, m.bounds[1][2]
    for _ in range(40):
        z = (lo + hi) / 2
        lo, hi = (z, hi) if below(m, z).volume < target else (lo, z)
    draft = (lo + hi) / 2
    sub = below(m, draft)
    # waterplane = the flat cap that closes the submerged volume at z = draft; integrate over its triangles
    # exactly (area, centroid, second moment about the centreline). The slicer's waterline segments are NOT
    # consistently ordered, so a shoelace sum over them is wrong for general hulls.
    cap = (np.abs(sub.triangles[:, :, 2] - draft).max(1) < 1e-6) & (sub.face_normals[:, 2] > 0.99)
    tri = sub.triangles[cap][:, :, :2]
    x, y = tri[..., 0], tri[..., 1]
    a = 0.5 * np.abs((x[:, 1] - x[:, 0]) * (y[:, 2] - y[:, 0]) - (x[:, 2] - x[:, 0]) * (y[:, 1] - y[:, 0]))
    awp = a.sum()
    yc = (a * y.mean(1)).sum() / max(awp, 1e-12)
    Iyy = (a / 6 * (y[:, 0] ** 2 + y[:, 1] ** 2 + y[:, 2] ** 2 + y[:, 0] * y[:, 1] + y[:, 1] * y[:, 2] + y[:, 2] * y[:, 0])).sum()
    Ixx = Iyy - awp * yc ** 2            # roll second moment about the waterplane centreline
    wp = trimesh.intersections.mesh_plane(m, [0, 0, 1], [0, 0, draft])  # waterline segments (extents only)
    kb = sub.center_mass[2]
    kg = m.center_mass[2] if kg is None else kg
    gm = kb + Ixx / sub.volume - kg
    lwl = np.ptp(wp[:, :, 0]); bwl = np.ptp(wp[:, :, 1])
    wet = sub.area - awp   # cap face is not wetted
    return dict(sinks=False, draft=draft, displacement_m3=sub.volume, lwl=float(lwl), bwl=float(bwl),
                waterplane_area=float(awp), wetted_area=float(wet), kb=float(kb), kg=float(kg), gm=float(gm),
                freeboard=float(m.bounds[1][2] - draft))


# ---------------------------------------------------------------- built-in samples

def loft(xs, sections):
    """Watertight mesh from closed yz-polylines at stations xs (same vertex count each), fan-capped ends."""
    n = len(sections[0])
    V = [np.column_stack([np.full(n, x), s]) for x, s in zip(xs, sections)]
    V = np.vstack(V + [[xs[0], *sections[0].mean(0)], [xs[-1], *sections[-1].mean(0)]])
    F = []
    for i in range(len(xs) - 1):
        for j in range(n):
            a, b, c, d = i * n + j, i * n + (j + 1) % n, (i + 1) * n + j, (i + 1) * n + (j + 1) % n
            F += [[a, c, b], [b, c, d]]
    c0, c1 = len(V) - 2, len(V) - 1
    last = (len(xs) - 1) * n
    F += [[c0, (j + 1) % n, j] for j in range(n)] + [[c1, last + j, last + (j + 1) % n] for j in range(n)]
    m = trimesh.Trimesh(V, F, process=True)
    m.merge_vertices()
    m.update_faces(m.nondegenerate_faces())
    m.fix_normals()
    return m


def sample_torpedo():
    """REMUS AUV bare hull, exact Myring parameters from Prestero (2001, MIT) Table 2.1 / Eqs 2.1-2.3."""
    a, a_off, b, c, c_off, n, th, d, l = 0.191, 0.0165, 0.654, 0.541, 0.0368, 2.0, 0.436, 0.191, 1.33
    lf = a + b - a_off
    x = np.concatenate([np.linspace(0, a - a_off, 30), np.linspace(a - a_off, lf, 12)[1:-1], np.linspace(lf, l, 40)])
    r = np.where(x < a - a_off, d / 2 * np.clip(1 - ((x + a_off - a) / a) ** 2, 0, 1) ** (1 / n), d / 2)
    t = x - lf
    tail = d / 2 - (3 * d / (2 * c ** 2) - np.tan(th) / c) * t ** 2 + (d / c ** 3 - np.tan(th) / c ** 2) * t ** 3
    r = np.maximum(np.where(x > lf, tail, r), 0.01 * d)   # blunt the tips so rings never collapse
    ang = np.linspace(0, 2 * np.pi, 48, endpoint=False)
    secs = [np.column_stack([ri * np.cos(ang), ri * np.sin(ang)]) for ri in r]
    return normalize(loft(l - x, secs), "uuv")   # nose at +x


def suboff_radius(x_ft):
    """DARPA SUBOFF bare hull (AFF-1) radius in feet at x feet from the nose: Groves, Huang & Chang 1989
    (DTRC/SHD-1298-01) analytic forebody, parallel middle body, afterbody and cap. L = 14.2917 ft = 4.356 m."""
    R, rh, k0, k1 = 5 / 6, 0.1175, 10.0, 44.6244
    x = np.asarray(x_ft, float)
    a = 0.3 * x - 1
    fore = R * np.clip(1.126395101 * x * a ** 4 + 0.442874707 * x ** 2 * a ** 3 + 1 - a ** 4 * (1.2 * x + 1), 0, None) ** (1 / 2.1)
    xi = (13.979167 - x) / 3.333333
    aft = R * np.sqrt(np.clip(rh ** 2 + rh * k0 * xi ** 2 + (20 - 20 * rh ** 2 - 4 * rh * k0 - k1 / 3) * xi ** 3
                              + (-45 + 45 * rh ** 2 + 6 * rh * k0 + k1) * xi ** 4 + (36 - 36 * rh ** 2 - 4 * rh * k0 - k1) * xi ** 5
                              + (-10 + 10 * rh ** 2 + rh * k0 + k1 / 3) * xi ** 6, 0, None))
    cap = rh * R * np.sqrt(np.clip(1 - (3.2 * x - 44.733333) ** 2, 0, None))
    return np.select([x <= 10 / 3, x <= 10.645833, x <= 13.979167], [fore, R, aft], cap)


def sample_suboff():
    """DARPA SUBOFF bare hull at model scale (4.356 m), the standard benchmark for hull forces at incidence."""
    ft = 0.3048
    x = np.concatenate([np.linspace(0, 10 / 3, 40), np.linspace(10 / 3, 10.645833, 10)[1:-1],
                        np.linspace(10.645833, 13.979167, 40), np.linspace(13.979167, 14.291667, 12)[1:]])
    r = np.maximum(suboff_radius(x), 0.004 / ft) * ft      # blunt pole so rings never collapse
    ang = np.linspace(0, 2 * np.pi, 64, endpoint=False)
    secs = [np.column_stack([ri * np.cos(ang), ri * np.sin(ang)]) for ri in r]
    return normalize(loft(14.291667 * ft - x * ft, secs), "uuv")   # nose at +x


def sample_wigley(L=2.5, B=0.25, T=0.156, freeboard=0.15):
    """Wigley hull at the Univ. of Tokyo model size (Kajitani et al. 1983). Classic test hull: y = B/2 (1-(2x/L)^2)(1-(z/T)^2), walled up to a flat deck."""
    xs = np.linspace(-L / 2, L / 2, 61)
    zs = np.concatenate([np.linspace(-T, 0, 16), np.linspace(0, freeboard, 6)[1:]])
    secs = []
    for x in xs:
        hx = max(B / 2 * (1 - (2 * x / L) ** 2), 1e-4 * B)
        y = hx * np.where(zs < 0, 1 - (zs / T) ** 2, 1)
        y[0] = 1e-4 * B   # keel line
        starboard = np.column_stack([-y, zs])
        port = np.column_stack([y, zs])[::-1]
        secs.append(np.vstack([starboard, port]))
    return normalize(loft(xs, secs), "usv")


def sample_quad(wheelbase=0.45, prop_d=0.254):
    """X-frame quadcopter: body pod, four arms, four motor cans. Rotor discs are not geometry —
    rotors are modelled as actuator disks in the dynamics."""
    import trimesh.creation as tc
    parts = [tc.box([0.16, 0.11, 0.06])]
    arm = wheelbase / 2
    for k in range(4):
        a = np.pi / 4 + k * np.pi / 2
        p = arm * np.array([np.cos(a), np.sin(a), 0])
        cyl = tc.cylinder(radius=0.009, height=arm, sections=16)
        cyl.apply_transform(trimesh.geometry.align_vectors([0, 0, 1], [np.cos(a), np.sin(a), 0]))
        cyl.apply_translation(p / 2)
        motor = tc.cylinder(radius=0.016, height=0.035, sections=20)
        motor.apply_translation(p + [0, 0, 0.012])
        parts += [cyl, motor]
    m = trimesh.boolean.union(parts, engine="manifold")
    return normalize(m, "uav")


SAMPLES = {
    "torpedo": dict(kind="uuv", make=sample_torpedo,
                    spec=dict(name="Remora", mass=31.7, power_w=150, battery_wh=1000, hotel_w=15,
                              prop_d=0.12, material="al6061", wall_mm=6.0, structure="shell",
                              layout="torpedo", appendage_factor=2.0)),
    "wigley": dict(kind="usv", make=sample_wigley,
                   spec=dict(name="Skiff", mass=44.4, power_w=400, battery_wh=1500, hotel_w=20,
                             prop_d=0.12, material="gfrp", wall_mm=4.0, structure="shell",
                             cog=[0.0, 0.0, -0.094], design_category="D")),   # cog FRD/keel origin: KG = 0.6 draft (KM 0.124); a tank model, so sheltered water only
    "suboff": dict(kind="uuv", make=sample_suboff, hangar=False,     # validation hull only, never a hangar design
                   spec=dict(name="SUBOFF", mass=716.0, power_w=2000, battery_wh=5000, layout="torpedo",
                             cog=[0.165, 0.0, 0.0])),     # moment reference = Roddy's, 2.013 m from the nose (FRD)
    "quad": dict(kind="uav", make=sample_quad,
                 spec=dict(name="Gnat", mass=1.8, power_w=1400, battery_wh=111, hotel_w=10,
                           prop_d=0.254, rotors=4, wheelbase=0.45, material="cfrp", wall_mm=3.0,
                           structure="solid")),
}


if __name__ == "__main__":
    t = sample_torpedo()
    assert t.is_watertight and abs(t.extents[0] - 1.33) < 1e-6, t.extents
    # Prestero Table 2.7: volume ~0.0315 m3 (estimated), wetted area 0.709 m2, frontal 0.0285 m2
    assert abs(t.volume / 0.0315 - 1) < 0.08, t.volume
    assert abs(t.area / 0.709 - 1) < 0.05, t.area
    w = sample_wigley()
    assert w.is_watertight, "wigley not closed"
    # Wigley analytic: Cb = 4/9 below the design waterline
    L, B, T = 2.5, 0.25, 0.156
    hs = hydrostatics(w, mass=RHO_SEA * 4 / 9 * L * B * T, kg=0.0)
    assert abs(hs["draft"] - T) < 0.004, hs
    bm_exact = (2 / 3) * (B / 2) ** 3 * (L / 2) * (32 / 35) / (4 / 9 * L * B * T)  # I_T / V
    # Kajitani's wetted surface S = 0.661 L (2T + B)
    assert abs(hs["wetted_area"] / (0.661 * L * (2 * T + B)) - 1) < 0.03, hs["wetted_area"]
    assert abs((hs["gm"] - hs["kb"]) / bm_exact - 1) < 0.03, (hs["gm"] - hs["kb"], bm_exact)
    q = sample_quad()
    assert q.is_watertight, "quad not closed"
    sb = sample_suboff()
    # Groves et al. 1989 bare hull (AFF-1): 4.356 m, D 0.508 m, volume 0.699 m3, wetted surface 5.988 m2
    # (0.718 m3 is the appended model's)
    assert sb.is_watertight and abs(sb.extents[0] - 4.356) < 2e-3 and abs(sb.extents[1] - 0.508) < 2e-3, sb.extents
    assert abs(sb.volume / 0.699 - 1) < 0.01 and abs(sb.area / 5.988 - 1) < 0.01, (sb.volume, sb.area)
    assert abs(projected_area(t, 0) / 0.0285 - 1) < 0.03, projected_area(t, 0)
    print("geom ok", t.extents, w.extents, q.extents, hs["draft"], hs["gm"])
