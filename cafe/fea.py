"""FEA with CalculiX 2.21, meshed by gmsh.

Hulls: quadratic shells (S6) at a wall thickness. Frames: quadratic tets (C3D10).
A flying/swimming body has no supports, so the net applied load is balanced by an equal and
opposite body acceleration (inertia relief by hand) and held by a statically determinate 3-2-1
constraint whose reactions should come out ~0 (checked and reported).
"""
import pathlib, re, shutil, subprocess, tempfile
import numpy as np
import trimesh

# E [Pa], nu, rho [kg/m3], yield/strength [Pa]. Handbook values; composites are quasi-isotropic
# laminate approximations (ponytail: isotropic stand-in, a layup needs *SHELL SECTION COMPOSITE).
MATERIALS = {
    "al6061": dict(name="Aluminium 6061-T6", E=68.9e9, nu=0.33, rho=2700, yield_=276e6),
    "ti6al4v": dict(name="Titanium Ti-6Al-4V", E=113.8e9, nu=0.342, rho=4430, yield_=880e6),
    "ss316": dict(name="Stainless 316", E=193e9, nu=0.27, rho=8000, yield_=205e6),
    "cfrp": dict(name="Carbon fibre (quasi-iso)", E=50e9, nu=0.30, rho=1550, yield_=450e6),
    "gfrp": dict(name="Glass fibre (quasi-iso)", E=20e9, nu=0.30, rho=1900, yield_=200e6),
    "abs": dict(name="ABS", E=2.2e9, nu=0.35, rho=1050, yield_=40e6),
    "pla": dict(name="PLA", E=3.5e9, nu=0.36, rho=1240, yield_=50e6),
    "petg": dict(name="PETG", E=2.1e9, nu=0.38, rho=1270, yield_=50e6),
    "hdpe": dict(name="HDPE", E=1.0e9, nu=0.42, rho=950, yield_=25e6),
    "pmma": dict(name="Acrylic (PMMA)", E=3.0e9, nu=0.37, rho=1190, yield_=70e6),
    "pom": dict(name="Acetal (POM)", E=3.1e9, nu=0.35, rho=1410, yield_=70e6),
}


def _gmsh():
    import gmsh
    gmsh.initialize(interruptible=False)   # safe off the main thread
    gmsh.option.setNumber("General.Terminal", 0)
    return gmsh


def mesh_body(m, structure, h, curvature=12, straight=False):
    """trimesh -> (nodes[N,3], elements[M,k] 0-based, kind). Shell: 6-node tris. Solid: 10-node tets.
    Tries a clean remesh first; if gmsh can't reparametrize the surface (boolean-unioned parts often
    have patches it rejects), tet-meshes the original triangles as they are."""
    last = None
    for reparam in (True, False):
        try:
            return _gmsh_mesh(m, structure, h, curvature, reparam, straight)
        except Exception as e:
            last = e
    raise ValueError(f"could not mesh the model for FEA: {last}")


def _gmsh_mesh(m, structure, h, curvature, reparam, straight=False):
    tmp = pathlib.Path(tempfile.mkdtemp())
    m.export(tmp / "in.stl")
    gmsh = _gmsh()
    try:
        gmsh.merge(str(tmp / "in.stl"))
        if reparam:
            gmsh.model.mesh.classifySurfaces(np.radians(40), True, True, np.pi)
            gmsh.model.mesh.createGeometry()
        if structure == "solid":
            surf = [s[1] for s in gmsh.model.getEntities(2)]
            gmsh.model.geo.addVolume([gmsh.model.geo.addSurfaceLoop(surf)])
        gmsh.model.geo.synchronize()
        gmsh.option.setNumber("Mesh.MeshSizeMax", h)
        gmsh.option.setNumber("Mesh.MeshSizeMin", h / 4)
        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", curvature)
        gmsh.option.setNumber("Mesh.HighOrderOptimize", 0 if straight else 1)
        gmsh.option.setNumber("Mesh.SecondOrderLinear", 1 if straight else 0)   # straight-sided: can't fold
        if reparam or structure == "solid":
            gmsh.model.mesh.generate(3 if structure == "solid" else 2)
        gmsh.model.mesh.setOrder(2)
        tags, xyz, _ = gmsh.model.mesh.getNodes()
        idx = {t: i for i, t in enumerate(tags)}
        etype = 11 if structure == "solid" else 9   # gmsh: 11 = tet10, 9 = tri6
        _, enodes = gmsh.model.mesh.getElementsByType(etype)
        k = 10 if structure == "solid" else 6
        el = np.array([idx[t] for t in enodes]).reshape(-1, k)
        nodes = xyz.reshape(-1, 3)
    finally:
        gmsh.finalize()
        shutil.rmtree(tmp, ignore_errors=True)
    if len(el) == 0:
        raise ValueError("gmsh produced no elements (mesh not closed or too coarse?)")
    used = np.unique(el)
    remap = -np.ones(len(nodes), int)
    remap[used] = np.arange(len(used))
    return nodes[used], remap[el], structure


# gmsh tet10 node order -> CalculiX C3D10: gmsh swaps the last two mid-edge nodes
_TET10 = [0, 1, 2, 3, 4, 5, 6, 7, 9, 8]


def _tri_geometry(nodes, el):
    a, b, c = nodes[el[:, 0]], nodes[el[:, 1]], nodes[el[:, 2]]
    n = np.cross(b - a, c - a)
    area = np.linalg.norm(n, axis=1) / 2
    return (a + b + c) / 3, n / (2 * area[:, None]), area


def orient_outward(nodes, el):
    """Flip shell elements so every normal points out of the body (trimesh makes the corner mesh's
    winding consistent and outward; elements that disagree get reversed)."""
    corner = trimesh.Trimesh(nodes, el[:, :3], process=False)
    trimesh.repair.fix_normals(corner, multibody=True)
    flip = np.einsum("ij,ij->i", _tri_geometry(nodes, el)[1], corner.face_normals) < 0
    el = el.copy()
    # S6 node order: 3 corners then mid-edges (12, 23, 31); reversing = swap corners 1<->2 and mids
    el[flip] = el[flip][:, [0, 2, 1, 5, 4, 3]]
    return el


def _mean_rigid_equations(r, mn, max_nodes=600):
    """A free body has no supports. Instead of pinning 3 points (a pinned node on a thin shell is soft: the
    body rolls about it and the dimple shows up as a fake low buckling mode), constrain its MEAN rigid motion:
    sum m_i u_i = 0 and sum m_i r_i x u_i = 0 over (a sample of) the nodes, as six CalculiX equations.
    Any load imbalance is then carried mass-proportionally, which is inertia relief itself.
    r = node positions relative to the centre of mass, mn = lumped nodal masses."""
    idx = np.where(mn > 0)[0]
    if len(idx) > max_nodes:                       # ponytail: a sample keeps each equation short; plenty to fix 6 DOF
        idx = idx[np.linspace(0, len(idx) - 1, max_nodes).astype(int)]
    m, rr = mn[idx] / mn[idx].mean(), r[idx]
    # each equation's first term is eliminated by CalculiX: six different (node, dof) pairs, each used only there
    rot = []
    for k, (a, b) in enumerate(((1, 2), (2, 0), (0, 1))):
        # rotation about axis k: sum m (r_a u_b - r_b u_a) = 0; dependent dof b at a node with a big |r_a|
        rot.append((int(np.argsort(-np.abs(rr[:, a]))[k]), b))
    free = [i for i in range(len(idx)) if i not in {n for n, _ in rot}]
    dep = [(free[k], k) for k in range(3)] + rot                          # translations: any other node
    used = {d[0] for d in dep}
    rest = [i for i in range(len(idx)) if i not in used]
    eqs = []
    for k in range(3):
        n0, d0 = dep[k]
        eqs.append([(n0, d0, m[n0])] + [(i, k, m[i]) for i in rest])
    for k, (a, b) in enumerate(((1, 2), (2, 0), (0, 1))):
        n0, d0 = dep[3 + k]
        eqs.append([(n0, b, m[n0] * rr[n0, a])] + [(i, b, m[i] * rr[i, a]) for i in rest] + [(i, a, -m[i] * rr[i, b]) for i in rest])
    out = []
    for eq in eqs:
        terms = [f"{idx[i] + 1},{d + 1},{c:.9g}" for i, d, c in eq if c != 0 or i == eq[0][0]]
        out += ["*EQUATION", str(len(terms))] + [",".join(terms[j:j + 4]) for j in range(0, len(terms), 4)]
    return out


def solve(m, structure, material, thickness=None, pressure=None, point_loads=(), steps=("static",),
          h=None, workdir=None, n_modes=10, fixed=None, body_accel=None, density=None):
    """
    m           trimesh in body frame, metres
    structure   "shell" (needs thickness [m]) or "solid"
    pressure    f(centres[N,3], outward_normals[N,3]) -> Pa, positive pushes inward (shells only)
    point_loads [(position[3], force[3] N, footprint radius m)] spread over nearby surface nodes
    steps       subset of ("static", "buckle", "modes")
    fixed       f(nodes[N,3]) -> bool mask of clamped nodes (a wing root, an arm at the body, lifting
                points). Without it the body floats free: loads are balanced by inertia relief + 3-2-1.
    body_accel  [3] m/s^2 applied to all material (gravity, a hard landing, a lift at 2 g)
    density     overrides the material density (e.g. to make a hull skin carry the whole boat's mass)

    Meshing/expansion fallbacks, in order: curved quadratic elements with the wall inside the skin;
    straight-sided elements (curved ones fold on razor-thin regions); then, for shells, the wall at
    mid-surface and grown outward (inner skins of a knife-edge stem collide otherwise). The offset used is
    reported, because a wall moved outward changes the section."""
    # CalculiX OFFSET +0.5 puts the wall INSIDE the reference surface (verified: a clamped tube with -0.5 is
    # exactly I_outside/I_inside = 1.46x too stiff). Meshes are outer skins, so the wall goes inside first.
    attempts = [(0.5, False), (0.5, True), (0.0, True), (-0.5, True)] if structure == "shell" else [(0.0, False), (0.0, True)]
    last = None
    for offset, straight in attempts:
        try:
            return _solve(m, structure, material, thickness, pressure, point_loads, steps, h, workdir, n_modes,
                          offset, straight, fixed, body_accel, density)
        except RuntimeError as e:
            if "jacobian" not in str(e):
                raise
            last = e
    raise last


def _solve(m, structure, material, thickness, pressure, point_loads, steps, h, workdir, n_modes,
           offset, straight, fixed, body_accel, density):
    mat = dict(MATERIALS[material])
    if density:
        mat["rho"] = density
    h = h or m.extents.max() / 60
    nodes, el, _ = mesh_body(m, structure, h, straight=straight)
    if structure == "shell":
        el = orient_outward(nodes, el)
    work = pathlib.Path(workdir or tempfile.mkdtemp())
    work.mkdir(parents=True, exist_ok=True)
    lines = ["*NODE, NSET=NALL"] + [f"{i + 1}, {x:.9g}, {y:.9g}, {z:.9g}" for i, (x, y, z) in enumerate(nodes)]
    if structure == "shell":
        lines += ["*ELEMENT, TYPE=S6, ELSET=EALL"] + [f"{i + 1}, " + ", ".join(str(n + 1) for n in e) for i, e in enumerate(el)]
    else:
        lines += ["*ELEMENT, TYPE=C3D10, ELSET=EALL"] + [f"{i + 1}, " + ", ".join(str(e[j] + 1) for j in _TET10) for i, e in enumerate(el)]
    lines += ["*MATERIAL, NAME=M", "*ELASTIC", f"{mat['E']:.6g}, {mat['nu']}", "*DENSITY", f"{mat['rho']}"]
    # OFFSET: the mesh is the hull's outer skin; which side the wall grows into is chosen per model below
    lines += ([f"*SHELL SECTION, ELSET=EALL, MATERIAL=M, OFFSET={offset}", f"{thickness:.6g}"] if structure == "shell"
              else ["*SOLID SECTION, ELSET=EALL, MATERIAL=M"])

    # --- loads, in a form shared by every step
    F_total = np.zeros(3)
    M_total = np.zeros(3)
    load_lines = []
    if structure == "shell":
        cen, nrm, area = _tri_geometry(nodes, el)
        vol_struct = area.sum() * thickness
        if pressure is not None:
            p = pressure(cen, nrm)
            # CalculiX shell P pushes ALONG the element normal (verified: +P on outward normals bulges
            # a cylinder outward), so inward pressure is written negative.
            load_lines += ["*DLOAD"] + [f"{i + 1}, P, {-pi:.6g}" for i, pi in enumerate(p) if pi != 0]
            f = -(p * area)[:, None] * nrm
            F_total += f.sum(0); M_total += np.cross(cen, f).sum(0)
    else:
        vol_struct = abs(trimesh.Trimesh(nodes, _tet_boundary(el), process=True).volume)
    surf_nodes = np.unique(el[:, :3]) if structure == "shell" else np.unique(_tet_boundary(el))
    cload = {}
    for pos, force, radius in point_loads:
        d = np.linalg.norm(nodes[surf_nodes] - pos, axis=1)
        sel = surf_nodes[d <= max(radius, d.min() * 1.001)]
        for n in sel:
            cload[n] = cload.get(n, np.zeros(3)) + np.asarray(force) / len(sel)
        F_total += force; M_total += np.cross(pos, force)
    mass = vol_struct * mat["rho"]
    alpha = np.zeros(3)
    if fixed is None:
        # free body, inertia relief by hand: the loads accelerate the body at a0 = F/m and spin it up at
        # alpha = I^-1 M (about the centre of mass); each node carries its d'Alembert force -m_i (a0 + alpha x r_i)
        # with lumped masses, so the applied set sums to exactly zero.
        # (Not CalculiX GRAV: with an offset wall on a curved shell its mass differs from ours by ~t/2R.)
        if structure == "shell":
            corners, share = el[:, :3], np.repeat((area * thickness / 3)[:, None], 3, 1)
        else:
            a4 = nodes[el[:, :4]]
            vol = np.abs(np.einsum("ij,ij->i", a4[:, 1] - a4[:, 0], np.cross(a4[:, 2] - a4[:, 0], a4[:, 3] - a4[:, 0]))) / 6
            corners, share = el[:, :4], np.repeat((vol / 4)[:, None], 4, 1)
        mn = np.bincount(corners.ravel(), share.ravel(), minlength=len(nodes)) * mat["rho"]
        mn *= mass / mn.sum()
        com = (mn[:, None] * nodes).sum(0) / mass
        r = nodes - com
        I = np.einsum("i,ij,ik->jk", mn, r, r)
        I = np.eye(3) * np.trace(I) - I
        alpha = np.linalg.solve(I, M_total - np.cross(com, F_total))
        if np.linalg.norm(F_total) > 0 or np.linalg.norm(M_total) > 0:
            fr = -mn[:, None] * (F_total / mass + np.cross(alpha, r))
            for n in np.where(mn > 0)[0]:
                cload[n] = cload.get(n, np.zeros(3)) + fr[n]
        lines += _mean_rigid_equations(r, mn)
    if cload:
        load_lines += ["*CLOAD"] + [f"{n + 1}, {k + 1}, {v[k]:.9g}" for n, v in cload.items() for k in range(3) if v[k]]
    grav = lambda v: ["*DLOAD", f"EALL, GRAV, {np.linalg.norm(v):.9g}, " + ", ".join(f"{x / np.linalg.norm(v):.9g}" for x in v)]
    if fixed is not None:
        # clamped part: external loads + body loads react at the clamp
        clamp = np.where(fixed(nodes))[0]
        if len(clamp) == 0:
            raise ValueError("the clamped region contains no nodes")
        if body_accel is not None and np.linalg.norm(body_accel) > 0:
            load_lines += grav(np.asarray(body_accel, float))
        load_lines = ["*BOUNDARY"] + [f"{n + 1}, 1, 3" for n in clamp] + load_lines
        support = clamp
    else:
        support = None       # free body: held only by the mean-rigid-motion equations above, no supports

    for s in steps:
        if s == "static":
            lines += ["*STEP", "*STATIC"] + load_lines + [
                "*NODE FILE", "U, RF", "*EL FILE", "S",
                "*EL PRINT, ELSET=EALL", "S", "*END STEP"]
        elif s == "buckle":
            # 10 modes: with only 2 the eigensolver sometimes converges past the lowest (cylinder modes cluster)
            # nev, tolerance, Lanczos vectors, max iterations: tight enough that repeated runs agree
            lines += ["*STEP", "*BUCKLE", "10, 1e-5, 60, 2000"] + load_lines + ["*END STEP"]
        elif s == "modes":
            # boundary conditions persist across CalculiX steps: clear them so the modes are free-free
            lines += ["*STEP", "*FREQUENCY", f"{n_modes + 6}", "*BOUNDARY, OP=NEW", "*END STEP"]
    (work / "job.inp").write_text("\n".join(lines) + "\n")
    # single-threaded, always: multithreaded CalculiX 2.21 (static steps too) now and then returns garbage
    # (a 10 N clamp reaction read [8.3, -3.7, 4.1]; a beam stress came out 1.8x) on identical input
    one = {k: "1" for k in ("OMP_NUM_THREADS", "CCX_NPROC_STIFFNESS", "CCX_NPROC_RESULTS", "CCX_NPROC_EQUATION_SOLVER")}
    r = subprocess.run(["ccx", "-i", "job"], cwd=work, capture_output=True, text=True, env=dict(one, PATH="/usr/bin:/bin"))
    log = r.stdout + r.stderr
    (work / "ccx.log").write_text(log)
    if r.returncode or "*ERROR" in log:
        errs = sorted({l.strip() for l in log.splitlines() if "ERROR" in l or "error" in l})
        raise RuntimeError("CalculiX failed: " + "; ".join(errs)[:500])
    out = dict(nodes=len(nodes), elements=len(el), structure=structure, h=h, material=material, offset=offset,
               struct_mass=mass, applied_force=F_total.tolist(), applied_moment=M_total.tolist(),
               balance_accel=(-F_total / mass).tolist() if fixed is None else None,
               balance_alpha=alpha.tolist() if fixed is None else None, clamped=fixed is not None, work=str(work))
    dat = (work / "job.dat").read_text()
    if "static" in steps:
        S = _el_stress(dat)
        vm = _mises(S)
        out["vm_max"] = float(vm.max())
        out["vm_p99"] = float(np.percentile(vm, 99))
        out["safety_factor"] = mat["yield_"] / out["vm_p99"] if out["vm_p99"] > 0 else np.inf
        U, nodal_vm, Fn = _frd(work / "job.frd", nodes)
        if support is not None:
            # RF at a node = reaction + whatever load was applied there
            own = np.array([cload.get(n, np.zeros(3)) for n in support]).reshape(-1, 3)
            out["reaction"] = (Fn[support].sum(0) - own.sum(0)).tolist()
        out["u_max"] = float(np.linalg.norm(U, axis=1).max())
        out["field"] = dict(nodes=nodes, faces=el[:, :3] if structure == "shell" else _tet_boundary(el),
                            vm=nodal_vm, u=U)
    if "buckle" in steps:
        blk = dat.split("B U C K L I N G   F A C T O R   O U T P U T")[-1] if "B U C K L I N G" in dat else ""
        fac = [float(x) for x in re.findall(r"^\s*\d+\s+([-\d.E+]+)\s*$", blk.split("E I G E N")[0], re.M)]
        pos = [f for f in fac if f > 0]
        # CalculiX's linear buckling treats pressure as a dead load; sea pressure follows the surface, which
        # lowers collapse by n^2/(n^2-1): 4/3 for the 2-lobe mode (verified: long tube 0.765 vs Bresse 0.546 MPa).
        # Apply the conservative 3/4 to every result.
        out["buckling_factor_dead_load"] = min(pos) if pos else None
        out["buckling_factors_dead_load"] = sorted(pos)[:6]
        out["buckling_factor"] = 0.75 * min(pos) if pos else None
    if "modes" in steps:
        fr = re.findall(r"^\s*\d+\s+[-\d.E+]+\s+[-\d.E+]+\s+([-\d.E+]+)\s+[-\d.E+]+\s*$",
                        dat.split("E I G E N V A L U E   O U T P U T")[-1].split("P A R T I C I P")[0], re.M)
        f = np.array([float(x) for x in fr])
        out["frequencies_hz"] = f[f > 1.0][:n_modes].tolist()
    return out


def _tet_boundary(el):
    """Outer corner triangles of a tet mesh (faces used once)."""
    f = np.vstack([el[:, [0, 2, 1]], el[:, [0, 1, 3]], el[:, [1, 2, 3]], el[:, [0, 3, 2]]])
    key = np.sort(f, 1)
    _, idx, cnt = np.unique(key, axis=0, return_index=True, return_counts=True)
    return f[idx[cnt == 1]]


def _mises(S):
    sxx, syy, szz, sxy, sxz, syz = S.T
    return np.sqrt(0.5 * ((sxx - syy) ** 2 + (syy - szz) ** 2 + (szz - sxx) ** 2) + 3 * (sxy ** 2 + sxz ** 2 + syz ** 2))


def _el_stress(dat):
    # the FIRST stress block is the static step; later ones (if any) are mode shapes with arbitrary scale
    block = dat.split("stresses (elem, integ.pnt.,sxx,syy,szz,sxy,sxz,syz)")[1].split(" stresses (")[0]
    rows = re.findall(r"^\s*\d+\s+\d+\s+([-\d.E+]+)\s+([-\d.E+]+)\s+([-\d.E+]+)\s+([-\d.E+]+)\s+([-\d.E+]+)\s+([-\d.E+]+)",
                      block, re.M)
    return np.array(rows, float)


def _frd(path, nodes):
    """Nodal displacement and von Mises of the static step from the ASCII .frd. For shells CalculiX
    reports on its expanded 3-D nodes, so every frd node is mapped to the nearest input node and the
    max stress through the thickness (outer fibres) is kept."""
    from scipy.spatial import cKDTree
    xyz, disp, stress, forc = {}, {}, {}, {}
    cur, seen = "COORD", set()
    for line in path.read_text().splitlines():
        if line.startswith("    2C"):
            cur = "COORD"
        elif line.startswith(" -4"):
            name = line.split()[1]
            cur = name if name in ("DISP", "STRESS", "FORC") and name not in seen else None
            seen.add(name)
        elif line.startswith(" -3"):
            cur = None
        elif line.startswith(" -1") and cur:
            nid = int(line[3:13])
            vals = [float(line[13 + 12 * k: 25 + 12 * k]) for k in range((len(line) - 13) // 12)]
            {"COORD": xyz, "DISP": disp, "STRESS": stress, "FORC": forc}[cur][nid] = vals
    ids = np.array(sorted(stress))
    owner = cKDTree(nodes).query(np.array([xyz[i] for i in ids]))[1]
    vm_frd = _mises(np.array([stress[i][:6] for i in ids]))
    u_frd = np.array([disp.get(i, [0, 0, 0])[:3] for i in ids])
    vm = np.zeros(len(nodes)); np.maximum.at(vm, owner, vm_frd)
    cnt = np.bincount(owner, minlength=len(nodes))[:, None]
    U = np.zeros((len(nodes), 3)); np.add.at(U, owner, u_frd)
    # CalculiX "RF" is the nodal force at EVERY node (loads and reactions alike; it sums to zero), so
    # reactions are read off the supported nodes only. Expanded shell nodes map back to their input node.
    F = np.zeros((len(nodes), 3))
    if forc:
        fid = np.array(sorted(forc))
        fown = cKDTree(nodes).query(np.array([xyz[i] for i in fid]))[1]
        np.add.at(F, fown, np.array([forc[i][:3] for i in fid]))
    return U / np.maximum(cnt, 1), vm, F


if __name__ == "__main__":
    import sys
    # Receipt 1: closed thin cylinder under external pressure -> hoop stress pR/t at mid-length,
    # and linear buckling pressure vs von Mises' formula (needs the research numbers; printed for now).
    R, t, Lc, p = 0.1, 0.003, 0.6, 1.0e6       # 1 MPa ~ 100 m depth
    cyl = trimesh.creation.cylinder(radius=R, height=Lc, sections=96)
    cyl.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [0, 1, 0]))
    r = solve(cyl, "shell", "al6061", thickness=t, pressure=lambda c, n: np.full(len(c), p),
              steps=("static", "buckle"), h=0.012, workdir=sys.argv[1] if len(sys.argv) > 1 else None)
    f = r["field"]
    mid = (np.abs(f["nodes"][:, 0]) < 0.05) & (np.hypot(f["nodes"][:, 1], f["nodes"][:, 2]) > 0.98 * R)
    hoop = p * R / t
    vm_mid = np.median(f["vm"][mid])
    # mid-length membrane state: hoop pR/t, axial pR/2t -> von Mises = sqrt(3)/2 * pR/t
    print(f"cyl: vm mid {vm_mid / 1e6:.2f} MPa vs membrane {np.sqrt(3) / 2 * hoop / 1e6:.2f} MPa; "
          f"radial disp inward? {np.median(np.einsum('ij,ij->i', f['u'][mid][:, 1:], f['nodes'][mid][:, 1:])) < 0}; "
          f"buckling factor {r['buckling_factor']}; reaction {r['reaction']}; nodes {r['nodes']}")
    assert abs(vm_mid / (np.sqrt(3) / 2 * hoop) - 1) < 0.05, vm_mid
    assert np.median(np.einsum("ij,ij->i", f["u"][mid][:, 1:], f["nodes"][mid][:, 1:])) < 0, "pressure must push inward"
    # Windenburg-Trilling elastic collapse pressure of a finite cylinder between rigid-ish ends
    E, nu, D = MATERIALS["al6061"]["E"], MATERIALS["al6061"]["nu"], 2 * R
    p_wt = 2.42 * E / (1 - nu ** 2) ** 0.75 * (t / D) ** 2.5 / (Lc / D - 0.45 * (t / D) ** 0.5)
    print(f"buckling: CalculiX {r['buckling_factor'] * p / 1e6:.3f} MPa vs Windenburg-Trilling {p_wt / 1e6:.3f} MPa")
    assert abs(r["buckling_factor"] * p / p_wt - 1) < 0.15
    assert max(map(abs, r["reaction"])) < 1e-6 * p * np.pi * R ** 2, "inertia relief must leave ~0 reactions"
    print("fea ok")
