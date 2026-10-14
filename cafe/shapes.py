"""Simplified shapes: describe a drone with a handful of dimensions instead of a CAD file.

Each shape builds a watertight mesh (FLU metres, normalized like an upload) and names its structural
PARTS, so FEA can load each the way it is loaded in service: a pressure hull, a wing at its root, a
quad arm at the motor, a boat bottom in slamming. All dimensions in metres.
"""
import numpy as np
import trimesh
import trimesh.creation as tc

from cafe.geom import loft, normalize

# name -> (label, default, min, max)
PARAMS = {
    "torpedo": dict(kind="uuv", label="Torpedo hull (AUV)", params=dict(
        length=("Length", 1.6, 0.3, 8), diameter=("Diameter", 0.2, 0.05, 1.5))),
    "glider": dict(kind="uuv", label="Buoyancy glider", params=dict(
        length=("Hull length", 1.5, 0.5, 4), diameter=("Hull diameter", 0.22, 0.08, 0.6),
        wing_span=("Wing span (tip to tip)", 1.0, 0.2, 3), wing_chord=("Wing chord", 0.18, 0.04, 0.6))),
    "pod": dict(kind="uuv", label="Cylinder pod", params=dict(
        length=("Length", 1.0, 0.2, 6), diameter=("Diameter", 0.3, 0.05, 2))),
    "monohull": dict(kind="usv", label="Monohull boat", params=dict(
        length=("Length", 2.5, 0.5, 15), beam=("Beam", 0.7, 0.15, 5), depth=("Hull depth (keel to deck)", 0.45, 0.1, 3))),
    "catamaran": dict(kind="usv", label="Catamaran", params=dict(
        length=("Length", 2.0, 0.5, 15), beam=("Overall beam", 1.1, 0.3, 8), hull_beam=("Each hull's beam", 0.25, 0.05, 2),
        depth=("Hull depth", 0.35, 0.1, 2))),
    "quad": dict(kind="uav", label="Quadcopter frame", params=dict(
        wheelbase=("Motor-to-motor diagonal", 0.45, 0.1, 2), arm_d=("Arm tube outer diameter", 0.016, 0.005, 0.08),
        body=("Body width", 0.15, 0.04, 0.8), motor_d=("Motor diameter", 0.035, 0.01, 0.15))),
}


def defaults(shape):
    return {k: v[1] for k, v in PARAMS[shape]["params"].items()}


def check(shape, p):
    """Errors for out-of-range or self-contradictory dimensions (never build nonsense)."""
    if shape not in PARAMS:
        return [f"unknown shape {shape!r}"]
    errs = []
    for k, (label, _, lo, hi) in PARAMS[shape]["params"].items():
        v = p.get(k)
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not np.isfinite(v) or not (lo <= v <= hi):
            errs.append(f"{label}: {v!r} m is outside {lo}-{hi} m")
    if errs:
        return errs
    if shape in ("torpedo", "glider", "pod") and p["length"] < 2 * p["diameter"]:
        errs.append("length must be at least twice the diameter")
    if shape == "glider" and p["wing_span"] <= p["diameter"] * 1.2:
        errs.append("wing span must be wider than the hull")
    if shape == "catamaran" and p["beam"] < 2.2 * p["hull_beam"]:
        errs.append("overall beam must exceed two hull beams with a gap between them")
    if shape == "glider" and p["wing_chord"] > 0.5 * p["length"]:
        errs.append("wing chord can be at most half the hull length")
    if shape == "monohull" and p["length"] < 2 * p["beam"]:
        errs.append("length must be at least twice the beam")
    if shape == "catamaran" and p["length"] < 1.2 * p["beam"]:
        errs.append("length must be at least 1.2 x the overall beam")
    if shape in ("monohull", "catamaran") and p["depth"] > p["beam"] * (2 if shape == "monohull" else 1):
        errs.append("hull depth is too large for the beam (it would roll over)")
    if shape == "quad" and p["wheelbase"] < 1.5 * p["body"]:
        errs.append("arms must reach beyond the body (wheelbase > 1.5 x body width)")
    if shape == "quad" and p["motor_d"] < p["arm_d"]:
        errs.append("motor must be at least as wide as the arm it sits on")
    if shape == "quad" and p["motor_d"] > 0.5 * p["wheelbase"] / np.sqrt(2):
        errs.append("motors would overlap their neighbours (motor diameter > half the motor spacing)")
    return errs


# ------------------------------------------------------------------ builders

def _revolve(x, r, n=40):
    ang = np.linspace(0, 2 * np.pi, n, endpoint=False)
    secs = [np.column_stack([max(ri, 1e-3 * r.max()) * np.cos(ang), max(ri, 1e-3 * r.max()) * np.sin(ang)]) for ri in r]
    return loft(x, secs)


def torpedo_mesh(L, D, nose=0.15, tail=0.30):
    """Myring-type body: elliptic nose to a smooth pole, parallel middle, cubic tail cone (25 deg) down to a
    prop hub 0.16 D across, closed by a rounded cap. No needle tip and no flat end with a sharp rim: neither
    can carry a real wall, and in FEA both fold the shell and fake a collapse far below the true one."""
    a, c = nose * L, tail * L
    b = L - a - c
    rh = 0.08 * D
    th = np.radians(25)
    tail_r = lambda t: D / 2 - (3 * D / (2 * c ** 2) - np.tan(th) / c) * t ** 2 + (D / c ** 3 - np.tan(th) / c ** 2) * t ** 3
    tt = np.linspace(0, c, 400)
    t_end = tt[np.argmax(tail_r(tt) <= rh)]                       # where the cone reaches the hub radius
    phi = np.linspace(0, np.pi / 2, 7)[1:]
    s = np.concatenate([np.linspace(0, a, 18), np.linspace(a, a + b, 6)[1:-1], a + b + np.linspace(0, t_end, 20),
                        a + b + t_end + rh * np.sin(phi)])
    r = np.concatenate([D / 2 * np.sqrt(np.clip(1 - ((np.linspace(0, a, 18) - a) / a) ** 2, 0, 1)), np.full(4, D / 2),
                        tail_r(np.linspace(0, t_end, 20)), rh * np.cos(phi)])
    s = s * L / s[-1]                                               # keep the overall length exactly L
    return _revolve(L / 2 - s, r)          # nose at +x


def pod_mesh(L, D):
    m = tc.capsule(height=L - D, radius=D / 2, count=[24, 24])
    m.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [0, 1, 0]))
    return m


def wing_mesh(span_half, chord, thick, root_y):
    """One wing: a thin slab from the hull centreline-ish root out to the tip (+y side)."""
    w = tc.box([chord, span_half, thick])
    w.apply_translation([0, root_y + span_half / 2, 0])
    return w


def glider_parts(L, D, span, chord):
    hull = torpedo_mesh(L, D, nose=0.12, tail=0.25)
    half = span / 2 - D / 2 * 0.8
    x_w = -0.05 * L
    wings = []
    for sgn in (1, -1):
        w = wing_mesh(half, chord, max(0.06 * chord, 0.004), D / 2 * 0.8)
        if sgn < 0:
            w.apply_transform(trimesh.transformations.reflection_matrix([0, 0, 0], [0, 1, 0]))
        w.apply_translation([x_w, 0, 0])
        wings.append(w)
    fin = tc.box([0.12 * L, 0.006, 0.6 * D])
    fin.apply_translation([-0.42 * L, 0, D / 2 + 0.2 * D])
    body = trimesh.boolean.union([hull] + wings + [fin], engine="manifold")
    return body, dict(hull=hull, wing=wings[0])


def monohull_mesh(L, B, H):
    """Hard-chine monohull: 15 deg deadrise bottom, vertical topsides, bow tapering over the front 30 %."""
    xs = np.linspace(-L / 2, L / 2, 41)
    dead = np.tan(np.radians(15))
    secs = []
    for x in xs:
        f = 1.0 if x < 0.2 * L else max(1 - (x - 0.2 * L) / (0.3 * L), 0.02)   # half-beam factor toward the bow
        hb = B / 2 * f
        keel_rise = 0.0 if x < 0.2 * L else 0.35 * H * (1 - f)                    # bow rises a little
        chine_z = keel_rise + hb * dead
        pts = [(-1e-4, keel_rise), (-hb, chine_z), (-hb, H), (hb, H), (hb, chine_z), (1e-4, keel_rise)]
        # resample to a fixed count so loft can join stations
        pts = np.array(pts)
        seg = np.r_[0, np.cumsum(np.linalg.norm(np.diff(np.vstack([pts, pts[:1]]), axis=0), axis=1))]
        u = np.linspace(0, seg[-1], 48, endpoint=False)
        loop = np.vstack([pts, pts[:1]])
        secs.append(np.column_stack([np.interp(u, seg, loop[:, 0]), np.interp(u, seg, loop[:, 1])]))
    return loft(xs, secs)


def catamaran_parts(L, B, hb, H):
    demi = monohull_mesh(L, hb, H)
    off = B / 2 - hb / 2
    a, b = demi.copy(), demi.copy()
    a.apply_translation([0, off, 0]); b.apply_translation([0, -off, 0])
    deck = tc.box([0.6 * L, 2 * off, 0.12 * H])
    deck.apply_translation([-0.05 * L, 0, H - 0.06 * H])
    body = trimesh.boolean.union([a, b, deck], engine="manifold")
    return body, dict(hull=a, deck=deck)


def quad_parts(wheelbase, arm_d, body, motor_d):
    r = wheelbase / 2
    core = tc.box([body, body * 0.75, body * 0.4])
    parts = [core]
    arm0 = None
    for k in range(4):
        a = np.pi / 4 + k * np.pi / 2
        u = np.array([np.cos(a), np.sin(a), 0])
        arm = tc.cylinder(radius=arm_d / 2, height=r, sections=20)
        arm.apply_transform(trimesh.geometry.align_vectors([0, 0, 1], u))
        arm.apply_translation(u * r / 2)
        motor = tc.cylinder(radius=motor_d / 2, height=motor_d * 0.9, sections=24)
        motor.apply_translation(u * r + [0, 0, arm_d / 2 + motor_d * 0.45])
        parts += [arm, motor]
        if arm0 is None:
            arm0 = arm
    body_m = trimesh.boolean.union(parts, engine="manifold")
    return body_m, dict(arm=arm0, body=core)


def build(shape, p):
    """-> (mesh normalized for its kind, {part: mesh in the same frame}, hints for the vehicle spec)"""
    errs = check(shape, p)
    if errs:
        raise ValueError("; ".join(errs))
    kind = PARAMS[shape]["kind"]
    hints = {}
    if shape == "torpedo":
        m = torpedo_mesh(p["length"], p["diameter"]); parts = dict(hull=m)
        hints = dict(layout="torpedo")
    elif shape == "pod":
        m = pod_mesh(p["length"], p["diameter"]); parts = dict(hull=m)
        hints = dict(layout="vectored6")
    elif shape == "glider":
        m, parts = glider_parts(p["length"], p["diameter"], p["wing_span"], p["wing_chord"])
        hints = dict(layout="glider", wing_area=(p["wing_span"] - p["diameter"]) * p["wing_chord"],
                     wing_span=p["wing_span"], wing_chord=p["wing_chord"], hull_d=p["diameter"])
    elif shape == "monohull":
        m = monohull_mesh(p["length"], p["beam"], p["depth"]); parts = dict(hull=m)
    elif shape == "catamaran":
        m, parts = catamaran_parts(p["length"], p["beam"], p["hull_beam"], p["depth"])
    else:
        m, parts = quad_parts(p["wheelbase"], p["arm_d"], p["body"], p["motor_d"])
        hints = dict(wheelbase=p["wheelbase"])
    # normalize the whole body, and move every part by the same offset so they stay registered
    lo, hi = m.bounds
    c = (lo + hi) / 2
    if kind == "usv":
        c[2] = lo[2]
    for x in [m] + list(parts.values()):
        x.apply_translation(-c)
    m = normalize(m, kind)          # merge/fix normals; offset is already applied (normalize recentres: no-op shift)
    if not m.is_watertight:
        raise ValueError(f"{shape}: the generated surface isn't closed (please report these dimensions)")
    return m, parts, hints


if __name__ == "__main__":
    for s in PARAMS:
        m, parts, hints = build(s, defaults(s))
        print(f"{s:10s} watertight {m.is_watertight} extents {np.round(m.extents, 3)} volume {m.volume:.4f} "
              f"parts {list(parts)} hints {list(hints)}")
        assert m.is_watertight
    # bad input must be refused, not built
    assert check("glider", dict(length=1.5, diameter=0.22, wing_span=0.2, wing_chord=0.18))
    assert check("torpedo", dict(length=float("nan"), diameter=0.2))
    print("shapes ok")
