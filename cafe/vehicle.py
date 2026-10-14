"""Vehicle model: everything the 6-DOF needs, from the mesh, the user's spec and hangar results.

Physics frames: world NED, body FRD (x fwd, y right, z down), moments about the CoG.
Meshes arrive in FLU (geom.py), converted here once. Every coefficient records its source
("cfd", "bem", "estimate") so the UI can say how much to trust a prediction.
"""
from dataclasses import dataclass, field
import numpy as np
import trimesh

FLU2FRD = np.diag([1.0, -1.0, -1.0])
RHO = {"water": 1025.0, "air": 1.20}
NU = {"water": 1.19e-6, "air": 1.5e-5}
G = 9.81
# Open-water propeller model: KT = KT0 (1 - J/J0), KQ = KQ0 (1 - J/JQ), J = Va / (n D).
# Air: APC 10x4.7 static coefficients from the UIUC propeller database (CT ~0.11, CP = 2 pi KQ ~0.048);
#   with motor/ESC efficiency 0.79 this gives a 1.8 kg quad hovering at ~5300 rpm and ~220 W, matching
#   T-Motor MN3110 bench data (450 g at ~5500 rpm, ~55 W) — see receipts.
# Water: Wageningen-B-like 4-blade P/D~1 (KT0 0.40, KQ0 0.065, J0 1.0, JQ 1.2): open-water efficiency
#   ~0.5-0.6 near J 0.7, typical of AUV props. ponytail: one generic curve per fluid; a real prop
#   map (or the user's) replaces it.
PROP = {"air": dict(kt0=0.11, kq0=0.0076, j0=0.55, jq=0.75, eta_m=0.79),
        "water": dict(kt0=0.40, kq0=0.065, j0=1.0, jq=1.2, eta_m=0.75)}
TAU_MOTOR = {"air": 0.04, "water": 0.08}
DIRS = {"+x": (1, 0, 0), "-x": (-1, 0, 0), "+y": (0, 1, 0), "-y": (0, -1, 0), "+z": (0, 0, 1), "-z": (0, 0, -1)}


@dataclass
class Actuator:
    pos: np.ndarray            # body FRD, relative to CoG
    dir: np.ndarray            # unit force direction for a positive command
    kind: str = "prop"         # "prop" | "fin" | "buoy" (buoyancy engine) | "mass" (moving pitch mass)
    fluid: str = "water"
    D: float = 0.0             # prop diameter
    pmax: float = 0.0          # max electrical power, W
    tmax: float = 0.0          # static thrust at full command, N
    rev: float = 0.0           # reverse thrust fraction (0 = one-way)
    spin: int = 0              # +1 CCW from above/behind -> +torque about dir axis... see torque()
    wmax: float = 0.0          # rad/s at full command
    qmax: float = 0.0          # shaft torque at full command, N.m
    area: float = 0.0          # fin planform area
    cla: float = 3.0           # fin lift slope, 1/rad
    dmax: float = np.radians(25)
    name: str = ""
    ar: float = 2.0            # fin/wing aspect ratio (induced drag)
    passive: bool = False      # wings: lift from angle of attack only, never commanded
    vb: float = 0.0            # buoyancy engine: +- displaced volume at full command, m3
    tau: float = 0.0           # actuator time constant override (pump, moving mass), s
    mmass: float = 0.0         # moving mass, kg
    dx: float = 0.0            # moving-mass travel at full command, m (+ = forward)

    @staticmethod
    def prop(pos, dir, fluid, D, pmax, rev=0.0, spin=0, name=""):
        """Max motor speed is where electrical power hits pmax at zero advance."""
        rho, c = RHO[fluid], PROP[fluid]
        n = (pmax * c["eta_m"] / (2 * np.pi * c["kq0"] * rho * D ** 5)) ** (1 / 3)     # rev/s
        return Actuator(np.asarray(pos, float), np.asarray(dir, float) / np.linalg.norm(dir), "prop", fluid, D, pmax,
                        c["kt0"] * rho * n ** 2 * D ** 4, rev, spin, 2 * np.pi * n, c["kq0"] * rho * n ** 2 * D ** 5,
                        name=name)


def prop_perf(fluid, D, nmax, rev, u, va):
    """Thrust (along dir), shaft torque and electrical power for command u in [-1,1] (motor speed
    fraction) with axial inflow va (m/s, positive = into the disk from the front). Vectorized."""
    c, rho = PROP[fluid], RHO[fluid]
    n = np.abs(u) * nmax
    J = np.where(u >= 0, np.maximum(va, 0), 0.0) / np.maximum(n * D, 1e-6)   # ponytail: no 4-quadrant map
    kt = c["kt0"] * np.maximum(1 - J / c["j0"], -0.2)
    kq = c["kq0"] * np.maximum(1 - J / c["jq"], 0.05)
    T = np.where(u >= 0, 1.0, -rev) * kt * rho * n ** 2 * D ** 4
    Q = kq * rho * n ** 2 * D ** 5
    return T, Q, 2 * np.pi * n * Q / c["eta_m"]


@dataclass
class Vehicle:
    name: str
    kind: str                       # uuv | usv | uav
    mass: float
    inertia: np.ndarray             # 3x3 about CoG, FRD
    cog: np.ndarray                 # FRD, in the mesh frame (bbox centre / keel origin)
    added_mass: np.ndarray          # 6x6, FRD about CoG (positive matrix: M = M_RB + A)
    volume: float
    actuators: list
    drag: dict                      # dir -> (force coeff vector m^2, moment coeff vector m^3, viscous fraction)
    drag_re: tuple                  # (reference speed, reference nu, length) for friction re-scaling
    rot_damp: np.ndarray            # quadratic rotational damping K (N.m.s^2 / (kg/m^3)) per axis
    panels: tuple = None            # (centres, normals, areas), FRD relative to CoG, water drones
    resistance: tuple = None        # USV: (speeds, R[N]) from free-surface CFD
    windage: np.ndarray = None      # USV: above-water CdA per body axis
    battery_wh: float = 100.0
    hotel_w: float = 5.0
    power_w: float = 100.0
    cells: int = 4
    limits: dict = field(default_factory=dict)
    sources: dict = field(default_factory=dict)
    linear_damp: np.ndarray = None  # 6 linear damping coefficients (radiation, BEM) — water drones
    length: float = 1.0
    cob: np.ndarray = None          # centre of buoyancy, FRD relative to CoG (fully submerged)

    @property
    def M(self):
        Mrb = np.zeros((6, 6))
        Mrb[:3, :3] = self.mass * np.eye(3)
        Mrb[3:, 3:] = self.inertia
        return Mrb + self.added_mass

    @property
    def fluid(self):
        return "air" if self.kind == "uav" else "water"


# ------------------------------------------------------------------ mass properties

def inertia_estimate(m, kind, mass, spec):
    """Inertia about the CoG in FRD. Uniform solid for hulls; for a quad, 70% central body box
    + 30% at the motors (frames are mostly empty space; batteries sit in the middle)."""
    if kind == "uav":
        w = spec.get("wheelbase", m.extents[:2].max())
        r = w / 2
        body = 0.7 * mass
        bx, by, bz = 0.35 * w, 0.25 * w, m.extents[2]
        I = np.diag([body * (by ** 2 + bz ** 2), body * (bx ** 2 + bz ** 2), body * (bx ** 2 + by ** 2)]) / 12
        mm = 0.3 * mass / 4
        for k in range(4):
            a = np.pi / 4 + k * np.pi / 2
            p = r * np.array([np.cos(a), np.sin(a), 0])
            I += mm * (p @ p * np.eye(3) - np.outer(p, p))
        return I
    if m.is_watertight:
        I = m.moment_inertia * (mass / m.volume)   # trimesh: density 1 -> mass == volume
        return FLU2FRD @ I @ FLU2FRD
    L, B, H = m.extents
    return mass / 12 * np.diag([B ** 2 + H ** 2, L ** 2 + H ** 2, L ** 2 + B ** 2])


def spheroid_added_mass(L, D, rho):
    """Lamb's added-mass coefficients of a prolate spheroid with the body's length and diameter.
    Fallback before (and cross-check for) the BEM result."""
    a, b = L / 2, D / 2
    e = np.sqrt(1 - (b / a) ** 2)
    lg = np.log((1 + e) / (1 - e))
    a0 = 2 * (1 - e ** 2) / e ** 3 * (0.5 * lg - e)
    b0 = 1 / e ** 2 - (1 - e ** 2) / (2 * e ** 3) * lg
    k1, k2 = a0 / (2 - a0), b0 / (2 - b0)
    kp = e ** 4 * (b0 - a0) / ((2 - e ** 2) * (2 * e ** 2 - (2 - e ** 2) * (b0 - a0)))
    md = rho * 4 / 3 * np.pi * a * b ** 2
    Id = md * (a ** 2 + b ** 2) / 5
    return np.diag([k1 * md, k2 * md, k2 * md, 0.0, kp * Id, kp * Id])


def newtonian_drag(cen, nrm, area, v_dir, rot_axis=None, cd=1.2):
    """Windward-face pressure drag per unit 0.5*rho*|v|^2 (translation) or per unit 0.5*rho*w^2
    (rotation about rot_axis through the origin). Bluff-body estimate used before CFD exists and
    for rotational damping, which CFD does not provide here."""
    if rot_axis is None:
        vn = nrm @ np.asarray(v_dir, float)
        vel = np.broadcast_to(v_dir, cen.shape)
    else:
        vel = np.cross(rot_axis, cen)
        vn = np.einsum("ij,ij->i", vel, nrm)
    hit = vn > 0
    f = -(cd * vn[hit] ** 2 * area[hit])[:, None] * nrm[hit]
    return f.sum(0), np.cross(cen[hit], f).sum(0)


# ------------------------------------------------------------------ default actuator layouts

def default_actuators(kind, m_frd, spec):
    L, B, H = m_frd.extents
    P = spec["power_w"]
    if kind == "uav":
        n = spec.get("rotors", 4)
        if n != 4:
            raise ValueError("only quad X layouts for now")
        r = spec.get("wheelbase", max(L, B)) / 2
        D = spec.get("prop_d", 0.254)
        # ArduPilot QUAD X order & spin: 1 FR CCW, 2 RL CCW, 3 FL CW, 4 RR CW (angles clockwise from nose)
        acts = []
        for i, (ang, spin) in enumerate([(45, 1), (-135, 1), (-45, -1), (135, -1)]):
            a = np.radians(ang)
            acts.append(Actuator.prop([r * np.cos(a), r * np.sin(a), -0.25 * H], [0, 0, -1], "air", D, P / n,
                                      spin=spin, name=f"motor{i + 1}"))
        return acts
    D = spec.get("prop_d", 0.076)
    if kind == "usv":
        z = 0.4 * H   # below CoG, near the keel (FRD z down)
        return [Actuator.prop([-0.45 * L, s * 0.3 * B, z], [1, 0, 0], "water", D, P / 2, rev=0.78, name=n)
                for s, n in ((-1, "port"), (1, "starboard"))]
    layout = spec.get("layout", "torpedo")
    if layout == "torpedo":
        prop = Actuator.prop([-0.5 * L, 0, 0], [1, 0, 0], "water", D, P, rev=0.5, name="stern")
        fin_area = spec.get("fin_area", 0.026 * L * max(B, H))
        r = 0.5 * max(B, H) + 0.02 * L          # fin centre of pressure just outside the hull
        x = -0.42 * L
        # four fins at their real positions so roll rate gives them angle of attack (roll damping) and
        # differential deflection gives roll control. Force direction = fin normal.
        mk = lambda pos, d, n: Actuator(np.array(pos, float), np.array(d, float), "fin", "water", area=fin_area, name=n)
        return [prop, mk([x, 0, -r], [0, 1, 0], "rudder_top"), mk([x, 0, r], [0, 1, 0], "rudder_bottom"),
                mk([x, -r, 0], [0, 0, 1], "elevator_port"), mk([x, r, 0], [0, 0, 1], "elevator_stbd")]
    if layout == "glider":
        # buoyancy glider (Slocum/Seaglider class): pump changes displacement, battery slides to pitch,
        # wings turn sinking into forward glide, small rudder for heading. No propeller.
        vb = spec.get("buoyancy_cc", 400) / 1e6
        span, chord = spec.get("wing_span", 1.0), spec.get("wing_chord", 0.18)
        hd = spec.get("hull_d", min(B, H))         # NOT the bbox: a glider's bounding box includes its wings
        half_area = max(span - hd, 0.05) * chord / 2
        ar = (span - hd) ** 2 / (2 * half_area)          # whole wing: span^2 / area
        yw = hd / 2 + (span - hd) / 4              # wing centre of pressure, half way out
        wing = lambda s, n: Actuator(np.array([-0.05 * L, s * yw, 0.0]), np.array([0.0, 0.0, 1.0]), "fin", "water",
                                     area=half_area, cla=2 * np.pi * ar / (ar + 2), ar=ar, passive=True, name=n)
        # the pump sits in the nose (as on a Slocum): pumping also pitches the glider into its dive/climb
        return [Actuator(np.array([0.4 * L, 0.0, 0.0]), np.array([0.0, 0.0, -1.0]), "buoy", "water", vb=vb, tau=spec.get("pump_s", 30.0),
                         pmax=spec.get("power_w", 30.0), name="buoyancy engine"),
                Actuator(np.zeros(3), np.array([1.0, 0, 0]), "mass", "water", mmass=0.15 * spec["mass"],
                         dx=spec.get("mass_travel", 0.02 * L), tau=5.0, name="pitch battery"),
                wing(1, "wing_stbd"), wing(-1, "wing_port"),
                Actuator(np.array([-0.45 * L, 0, -0.5 * H]), np.array([0.0, 1.0, 0.0]), "fin", "water",
                         area=spec.get("rudder_area", 0.08 * L * 0.6 * max(B, H) / 2), ar=1.5, name="rudder")]
    if layout == "vectored6":
        # BlueROV2-style, motor order and thrust directions exactly as ArduSub's "Vectored" frame
        # (AP_Motors6DOF.cpp / SIM_Submarine.cpp, Sub-4.7.1): linear = (forward, lateral, -throttle).
        x, y = 0.35 * L, 0.35 * B
        r2 = np.sqrt(0.5)
        table = [([x, y, 0], [-r2, r2, 0]), ([x, -y, 0], [-r2, -r2, 0]), ([-x, y, 0], [r2, r2, 0]),
                 ([-x, -y, 0], [r2, -r2, 0]), ([0, y, 0], [0, 0, 1]), ([0, -y, 0], [0, 0, 1])]
        return [Actuator.prop(pos, d, "water", D, P / 4, rev=0.78, name=f"M{i + 1}") for i, (pos, d) in enumerate(table)]
    raise ValueError(f"unknown layout {layout}")


# ------------------------------------------------------------------ build

def build(kind, mesh_flu, spec, hangar=None):
    """mesh_flu: normalized geom mesh. hangar: dict with optional 'cfd', 'fs', 'bem', 'fea' results."""
    hangar = hangar or {}
    m = mesh_flu.copy()
    m.apply_transform(np.block([[FLU2FRD, np.zeros((3, 1))], [np.zeros((1, 3)), np.ones((1, 1))]]))
    m.fix_normals()
    mass = float(spec["mass"])
    sources = {}
    cog = np.asarray(spec["cog"], float) if spec.get("cog") is not None else (
        m.center_mass if m.is_watertight else np.zeros(3))
    if kind == "usv" and spec.get("cog") is None and m.is_watertight:
        # a uniform solid puts the CoG near mid-depth incl. topsides, far higher than any real boat;
        # assume it sits at the waterline (flagged as an estimate — enter the real one)
        from cafe.geom import hydrostatics
        hs0 = hydrostatics(mesh_flu, mass)
        if not hs0["sinks"]:
            cog = np.array([cog[0], cog[1], -hs0["draft"]])   # keel at z=0, FRD up is negative
    if kind == "uuv" and spec.get("cog") is None:
        cog = cog + [0, 0, 0.02 * m.extents[2]]   # ballast low: CoG 2% of height below CoB
    sources["cog"] = "spec" if spec.get("cog") is not None else "estimate"
    I = np.asarray(spec["inertia"], float) if spec.get("inertia") is not None else inertia_estimate(m, kind, mass, spec)
    sources["inertia"] = "spec" if spec.get("inertia") is not None else "estimate"
    cen, nrm, area = m.triangles_center - cog, m.face_normals, m.area_faces
    wet = np.ones(len(area), bool)
    if kind == "usv" and m.is_watertight:
        from cafe.geom import hydrostatics
        hsw = hydrostatics(mesh_flu, mass)
        if not hsw["sinks"]:
            wet = m.triangles_center[:, 2] > -hsw["draft"]      # FRD, keel origin: submerged faces only
    rho = RHO["air" if kind == "uav" else "water"]

    # added mass
    if "bem" in hangar:
        A = np.asarray(hangar["bem"]["added_mass"]); sources["added_mass"] = "bem"
        lin = np.asarray(hangar["bem"].get("damping", np.zeros(6)))
    elif kind == "uav":
        A = np.zeros((6, 6)); sources["added_mass"] = "negligible (air)"; lin = np.zeros(6)
    else:
        L, B, H = m.extents
        # hull diameter, not the bounding box (wings or a tail fin would inflate the "spheroid" enormously)
        A = spheroid_added_mass(L, spec.get("hull_d", np.sqrt(B * H)), rho)
        if kind == "usv":
            A *= 0.5    # half-immersed
        sources["added_mass"] = "estimate (spheroid)"; lin = np.zeros(6)

    # translational drag table, per unit 0.5*rho*U^2
    drag, drag_re = {}, (1.5, NU["air" if kind == "uav" else "water"], m.extents.max())
    if "cfd" in hangar:
        c = hangar["cfd"]
        q = 0.5 * c["rho"] * c["speed"] ** 2
        for d, r in c["dirs"].items():
            F = FLU2FRD @ np.asarray(r["force"]) / q
            Mo = FLU2FRD @ np.asarray(r["moment"]) / q
            Mc = Mo - np.cross(cog, F)                     # CFD moments are about the mesh origin
            fv = abs(np.dot(r["viscous"], DIRS[d])) / max(abs(np.dot(r["force"], DIRS[d])), 1e-12)
            drag[_flip(d)] = (F, Mc, fv, r.get("gci", 0.0))
        drag_re = (c["speed"], c["nu"], c["L"])
        sources["drag"] = "cfd"
    for d, vec in DIRS.items():
        if d in drag:
            continue
        v = np.array(vec, float)      # mesh is already FRD here; labels are FRD
        F, Mo = newtonian_drag(cen[wet], nrm[wet], area[wet], v)
        # add turbulent skin friction on the wetted area (streamlined bodies are friction dominated)
        Re = 1.5 * m.extents.max() / NU["air" if kind == "uav" else "water"]
        F = F - v * 0.075 / (np.log10(Re) - 2) ** 2 * area[wet].sum() * 0.5
        drag[d] = (F, Mo, 0.5, 0.0)     # no mesh GCI for an estimate; its 30 % spread is applied in mission
        sources.setdefault("drag", "estimate (newtonian+ITTC)")
    rot = np.array([abs(newtonian_drag(cen, nrm, area, None, np.eye(3)[k])[1][k]) for k in range(3)])

    acts = default_actuators(kind, m, spec)
    if kind == "usv":
        # A real monohull holds its course because keel, skeg and rudder make lift aft that outweighs the hull's
        # destabilizing Munk moment (A_vv - A_uu) u v. Our hull forces come from on-axis CFD, which carries no such
        # lift, so it is added as a passive skeg pair aft (at the props), sized for a 1.5x margin over Munk.
        # ponytail: a typical margin, not this hull's; enter skeg_area (m^2, total) when the real one is known.
        Lx, By, Hz = m.extents
        xs = -0.4 * Lx
        cla = 2 * np.pi * 1.0 / (1.0 + 2)                # aspect ratio 1
        lever = max(abs(xs - cog[0]), 0.1 * Lx)
        S = float(spec.get("skeg_area") or 1.5 * max(A[1, 1] - A[0, 0], 0.0) / (0.5 * RHO["water"] * cla * lever))
        sources["skeg"] = "spec" if spec.get("skeg_area") else f"estimate ({S:.3f} m2 for 1.5x the Munk moment)"
        if S > 0:
            acts += [Actuator(np.array([xs, s * 0.3 * By, 0.4 * Hz]), np.array([0.0, 1.0, 0.0]), "fin", "water", area=S / 2,
                              cla=cla, ar=1.0, passive=True, name=f"skeg_{n}") for s, n in ((-1, "port"), (1, "stbd"))]
    for a in acts:
        a.pos = a.pos - cog          # layouts are placed on the bbox; dynamics want CoG-relative
    v = Vehicle(name=spec.get("name", kind), kind=kind, mass=mass, inertia=I, cog=cog, added_mass=A,
                volume=float(m.volume) if m.is_watertight else 0.0, actuators=acts, drag=drag, drag_re=drag_re,
                rot_damp=rot, battery_wh=float(spec.get("battery_wh", 100)), hotel_w=float(spec.get("hotel_w", 5)),
                power_w=float(spec["power_w"]), cells=int(spec.get("cells", 4)), sources=sources,
                linear_damp=lin, length=float(m.extents.max()))
    if kind in ("uuv", "usv"):
        v.panels, v.limits["panel_volume_correction"] = _panels(mesh_flu, cog, target=600 if kind == "usv" else 1200)
        v.cob = (m.center_mass - cog) if m.is_watertight else np.zeros(3)
    if kind == "usv":
        if "fs" in hangar:
            sp = sorted(hangar["fs"]["speeds"].items(), key=lambda kv: float(kv[0]))
            V1, R1 = float(sp[0][0]), sp[0][1]["resistance"]
            low = np.linspace(0, V1, 6)[:-1]                  # below the first CFD speed: R1 (V/V1)^2, not linear
            v.resistance = (np.r_[low, [float(k) for k, _ in sp]], np.r_[R1 * (low / V1) ** 2, [r["resistance"] for _, r in sp]])
            v.limits["resistance_gci"] = max(r.get("gci", 0.0) for _, r in sp)
            sources["resistance"] = "cfd (free surface)"
        v.windage = np.array([1.0 * _proj(m, ax) * 0.5 for ax in range(3)])   # ponytail: ~half the silhouette is above water
        sources["windage"] = "estimate (Cd 1.0 on half silhouette)"
    v.limits = dict(hangar.get("limits", {}), **v.limits)
    v.limits.setdefault("appendage_factor", float(spec.get("appendage_factor", 1.0)))
    if kind == "usv" and m.is_watertight:
        from cafe.geom import hydrostatics
        hs = hydrostatics(mesh_flu, mass, kg=-cog[2])
        v.limits["gm_m"] = hs.get("gm")
        v.limits["design_category"] = spec.get("design_category", "C")
    return v


def _flip(d):
    """FLU direction label -> FRD label (y and z change sign)."""
    return d if d[1] == "x" else ("-" if d[0] == "+" else "+") + d[1]


def _proj(m, axis):
    from cafe.geom import projected_area
    return projected_area(m, axis)


def _panels(mesh_flu, cog, target=1200):
    """Hull panels for pressure integration: FRD, CoG-relative. gmsh remesh to ~target flat
    triangles (exact for linear pressure, unlike lumping faces); raw faces if that fails."""
    from cafe.fea import mesh_body
    m = mesh_flu.copy()
    m.apply_transform(np.block([[FLU2FRD, np.zeros((3, 1))], [np.zeros((1, 3)), np.ones((1, 1))]]))
    try:
        h = np.sqrt(m.area / (0.43 * target))
        nodes, el, _ = mesh_body(m, "shell", h, curvature=0)
        p = trimesh.Trimesh(nodes, el[:, :3], process=True)
        if not p.is_watertight:
            raise ValueError("remeshed panels not closed")
    except Exception:
        p = m
        while len(p.faces) < target / 2:
            p = p.subdivide()
    p.fix_normals()
    # ponytail: flat panels inscribed in a curved hull enclose ~1-3% less volume; scale areas so the
    # panel set integrates to the true displacement (exact buoyancy, second-order moment error)
    k = m.volume / p.volume if (m.is_watertight and p.volume > 0) else 1.0
    return (p.triangles_center - cog, p.face_normals, p.area_faces * k), k
