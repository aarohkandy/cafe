"""Hangar: characterize a drone design once (BEM, CFD, FEA), cache everything on disk.

    python -m cafe.hangar /work/designs/<id>      # runs the whole pipeline, writes status/result

Directory: spec.json (user input), mesh.stl (normalized, FLU metres), status.json, log.txt,
result.json, fea_<case>.npz (one stress field per FEA load case), part_<name>.stl (shape designs).
"""
import json, pathlib, sys, time, traceback
import numpy as np
import trimesh

from cafe import geom, vehicle, fea, cfd, ctrl

KNOCKDOWN = 0.5      # ponytail: linear buckling of imperfect shells under external pressure; NASA SP-8007-style
                     # knock-downs for cylinders are ~0.5-0.75. A Riks run with imperfections replaces it.
REF_DEPTH = 100.0    # m, FEA reference load; stresses scale linearly so any depth reads off it
DEPTH_SF = 1.5       # rated depth = crush depth / 1.5
K_DC = dict(A=1.0, B=0.8, C=0.6, D=0.4)   # ISO 12215-5 design-category factor (2019) [summary-level]


class Job:
    def __init__(self, d):
        self.d = pathlib.Path(d)
        self.t0 = time.time()

    def log(self, msg):
        line = f"[{time.time() - self.t0:7.0f}s] {msg}"
        print(line, flush=True)
        with open(self.d / "log.txt", "a") as f:
            f.write(line + "\n")

    def status(self, state, step="", progress=0.0, **kw):
        (self.d / "status.json").write_text(json.dumps(dict(state=state, step=step, progress=progress,
                                                             updated=time.time(), **kw)))


# ------------------------------------------------------------------ input checks

def check(kind, m, spec):
    """Things that would make every downstream number garbage -> errors. Doubtful -> warnings."""
    errors, warnings = [], []
    for k in ("mass", "power_w", "battery_wh"):          # also guards specs written before the API checked
        v = spec.get(k)
        if not isinstance(v, (int, float)) or not np.isfinite(v) or v <= 0:
            errors.append(f"{k} must be a positive, finite number (got {v!r})")
    if errors:
        return errors, warnings
    if spec.get("units_assumed"):
        warnings.append(f"units weren't given; the file was read as {spec['units_assumed']} "
                        f"({m.extents.max():.3g} m long). If that's wrong, add the design again with units set")
    L = m.extents.max()
    if not (0.05 <= L <= 30):
        errors.append(f"model is {L:.3g} m long after unit conversion; wrong units?")
    if not m.is_watertight:
        (errors if kind in ("uuv", "usv") else warnings).append(
            "mesh is not watertight (holes / non-manifold edges): volume, buoyancy and FEA need a closed surface")
    mass = spec["mass"]
    if mass <= 0 or spec["power_w"] <= 0:
        errors.append("mass and power must be positive")
    if m.is_watertight and kind == "uuv":
        disp = geom.RHO_SEA * m.volume
        off = (disp - mass) / disp
        if abs(off) > 0.10:
            errors.append(f"sub is {abs(off):.0%} {'buoyant' if off > 0 else 'heavy'} (displaces {disp:.1f} kg, "
                          f"mass {mass:.1f} kg): it will not stay at depth; add ballast or check units/mass")
        elif abs(off) > 0.03:
            warnings.append(f"sub is {abs(off):.1%} {'positively' if off > 0 else 'negatively'} buoyant; needs speed for depth control")
    if m.is_watertight and kind == "usv" and mass >= geom.RHO_SEA * m.volume:
        errors.append("boat is heavier than the water its whole hull displaces: it sinks")
    if kind == "uav":
        a = vehicle.Actuator.prop([0, 0, 0], [0, 0, -1], "air", spec.get("prop_d", 0.254), spec["power_w"] / spec.get("rotors", 4))
        tw = a.tmax * spec.get("rotors", 4) / (mass * 9.81)
        if tw < 1.5:
            errors.append(f"thrust/weight is {tw:.2f} with {spec['power_w']:.0f} W: needs >= 1.5 to fly and control")
        elif tw > 6:
            warnings.append(f"thrust/weight {tw:.1f} is unusually high: check power (W) and prop diameter")
    return errors, warnings


# ------------------------------------------------------------------ BEM

def bem(m_flu, kind, cog_frd, draft=None):
    """Added mass (and radiation damping for boats) with Capytaine. Returns 6x6 FRD about the CoG."""
    import capytaine as cpt
    cog_flu = cog_frd * [1, -1, -1]
    target = 1500     # clean, near-equilateral panels; raw CAD/loft tessellations have slivers that NaN the Green function
    nodes, el, _ = fea.mesh_body(m_flu, "shell", np.sqrt(m_flu.area / (0.43 * target)), 0)
    pm = trimesh.Trimesh(nodes, el[:, :3], process=True)
    pm.fix_normals()
    if kind == "usv":
        pm.apply_translation([0, 0, -draft])         # waterline at z = 0
        rc = cog_flu - [0, 0, draft]
    else:
        pm.apply_translation([0, 0, -50.0])           # deep
        rc = cog_flu - [0, 0, 50.0]
    mesh = cpt.Mesh(vertices=pm.vertices, faces=pm.faces.tolist())
    body = cpt.FloatingBody(mesh=mesh, dofs=cpt.rigid_body_dofs(rotation_center=rc), center_of_mass=rc)
    dofs = list(body.dofs)
    solver = cpt.BEMSolver()
    A = np.zeros((6, 6)); Bd = np.zeros(6)
    if kind == "uuv":
        # deeply submerged: no free-surface effect -> frequency-independent, infinite fluid
        for i, d in enumerate(dofs):
            r = solver.solve(cpt.RadiationProblem(body=body, radiating_dof=d, free_surface=np.inf,
                                                  water_depth=np.inf, rho=geom.RHO_SEA, omega=1.0))
            A[i] = [r.added_masses[k] for k in dofs]
    else:
        body = body.immersed_part()
        # evaluate near the natural frequencies of heave/roll/pitch, low frequency for the rest
        V = pm.volume if pm.is_watertight else 0.1
        w_heave = np.sqrt(9.81 / max(draft, 0.02))
        for i, d in enumerate(dofs):
            w = w_heave if d in ("Heave", "Roll", "Pitch") else 0.3
            r = solver.solve(cpt.RadiationProblem(body=body, radiating_dof=d, water_depth=np.inf,
                                                  rho=geom.RHO_SEA, omega=w))
            A[i] = [r.added_masses[k] for k in dofs]
            Bd[i] = r.radiation_dampings[d]
    T = np.diag([1, -1, -1, 1, -1, -1])
    A = T @ A @ T
    A = 0.5 * (A + A.T)
    return dict(added_mass=A.tolist(), damping=Bd.tolist())


# ------------------------------------------------------------------ FEA load cases

def _case(name, what, r, mat, extra=None):
    """One load case result row for the table the app shows."""
    sf = fea.MATERIALS[mat]["yield_"] / r["vm_p99"] if r.get("vm_p99") else None
    row = dict(name=name, what=what, safety_factor=sf, vm_p99_mpa=(r.get("vm_p99") or 0) / 1e6,
               vm_max_mpa=(r.get("vm_max") or 0) / 1e6, u_max_mm=(r.get("u_max") or 0) * 1e3,
               nodes=r["nodes"], reaction_N=r.get("reaction"), applied_N=float(np.linalg.norm(r["applied_force"])))
    row.update(extra or {})
    return row


def _ends(part):
    """Axis of a long part and its two end positions (for a quad arm: root near the body, tip at the motor)."""
    c = part.vertices - part.vertices.mean(0)
    axis = np.linalg.svd(c, full_matrices=False)[2][0]
    t = c @ axis
    p0, p1 = part.vertices.mean(0) + axis * t.min(), part.vertices.mean(0) + axis * t.max()
    return (p0, p1) if np.linalg.norm(p0[:2]) < np.linalg.norm(p1[:2]) else (p1, p0)


def fea_cases(kind, m_flu, spec, veh, parts, work):
    """Every load case that applies to this kind of drone and the parts it has. Returns (summary, fields)."""
    mat = spec.get("material", "al6061")
    structure = spec.get("structure", "shell" if kind != "uav" else "solid")
    t = spec.get("wall_mm", 3.0) / 1000
    out = dict(material=fea.MATERIALS[mat]["name"], structure=structure, cases=[])
    fields = {}
    work = pathlib.Path(work)

    def run(key, part, struct, **kw):
        r = fea.solve(part, struct, mat, t if struct == "shell" else None, workdir=work / key, **kw)
        fields[key] = r.get("field")
        return r

    if kind == "uuv":
        hull = parts.get("hull", m_flu)
        p_ref = geom.RHO_SEA * 9.81 * REF_DEPTH
        r = run("depth", hull, "shell" if structure == "shell" else "solid", pressure=lambda c, n: np.full(len(c), p_ref),
                steps=("static", "buckle"), h=hull.extents.max() / 70)     # L/45 read collapse ~9 % high; L/70 is converged
        yield_depth = REF_DEPTH * fea.MATERIALS[mat]["yield_"] / r["vm_p99"]
        buckle_depth = REF_DEPTH * r["buckling_factor"] * KNOCKDOWN if r.get("buckling_factor") else np.inf
        crush = min(yield_depth, buckle_depth)
        out.update(vm_p99_at_ref=r["vm_p99"], ref_depth=REF_DEPTH, yield_depth=yield_depth,
                   buckling_factor=r.get("buckling_factor"), buckle_depth=buckle_depth, knockdown=KNOCKDOWN,
                   crush_depth=crush, rated_depth=crush / DEPTH_SF,
                   mode="buckling" if buckle_depth < yield_depth else "yield")
        out["cases"].append(_case("Hull at depth", f"{REF_DEPTH:.0f} m of sea water on the hull; scales linearly with depth",
                                  r, mat, dict(key="depth", crush_depth_m=crush, rated_depth_m=crush / DEPTH_SF, limited_by=out["mode"])))
        if "wing" in parts:
            w = parts["wing"]
            y0 = w.bounds[0][1]
            root = lambda nd: nd[:, 1] <= y0 + 0.02 * w.extents[1]
            span = w.extents[1]
            stations = [(np.array([w.centroid[0], y0 + f * span, w.bounds[1][2]]), f) for f in (0.2, 0.4, 0.6, 0.8, 0.95)]
            v = max(ctrl.max_speed(veh), 0.5) * 2              # gust/manoeuvre margin on the fastest flight
            L = 0.5 * geom.RHO_SEA * v ** 2 * w.extents[0] * span * 1.0   # CL 1.0 (stall) on one wing
            r = run("wing_lift", w, "solid", fixed=root, point_loads=[(p, [0, 0, L / 5], 0.01) for p, _ in stations],
                    h=min(w.extents) * 1.5)
            out["cases"].append(_case("Wing at maximum lift", f"stall lift at {v:.2f} m/s on one wing, root clamped", r, mat, dict(key="wing_lift")))
            tip = np.array([w.centroid[0], w.bounds[1][1], w.bounds[1][2]])
            r = run("wing_handling", w, "solid", fixed=root, point_loads=[(tip, [0, 0, -200.0], 0.02)], h=min(w.extents) * 1.5)
            out["cases"].append(_case("Wing handling", "200 N at the tip (lifting or bumping the glider by its wing)", r, mat, dict(key="wing_handling")))
    elif kind == "usv":
        hull = parts.get("hull", m_flu)
        hs = geom.hydrostatics(m_flu, spec["mass"])
        draft = hs["draft"]
        cat = spec.get("design_category", "C")
        p_slam = (2.4 * spec["mass"] ** 0.33 + 20) * 1e3 * K_DC[cat]    # Pa, ISO 12215-5 displacement-mode base
        press = lambda c, n: np.where(c[:, 2] < draft, np.maximum(geom.RHO_SEA * 9.81 * (draft - c[:, 2]), p_slam), 0.0)
        r = run("slamming", hull, structure, pressure=press, h=hull.extents.max() / 50)
        out.update(bottom_pressure_kpa=p_slam / 1e3, design_category=cat, safety_factor=fea.MATERIALS[mat]["yield_"] / r["vm_p99"],
                   vm_p99=r["vm_p99"])
        out["cases"].append(_case("Bottom slamming", f"{p_slam / 1e3:.0f} kPa on the bottom (ISO 12215-5, category {cat}); "
                                  "unstiffened skin, so conservative", r, mat, dict(key="slamming")))
        if structure == "shell":
            area = hull.area
            rho_eff = spec["mass"] / (area * t)          # the skin carries the whole boat's weight
            Lh = hull.extents[0]; top = hull.bounds[1][2]
            lift = lambda nd: (nd[:, 2] > top - 0.03 * hull.extents[2]) & (
                (np.abs(nd[:, 0] - 0.35 * Lh) < 0.06 * Lh) | (np.abs(nd[:, 0] + 0.35 * Lh) < 0.06 * Lh))
            r = run("lifting", hull, "shell", fixed=lift, body_accel=[0, 0, -2 * 9.81], density=rho_eff, h=hull.extents.max() / 50)
            out["cases"].append(_case("Craned aboard at 2 g", "whole boat hanging from bow and stern lifting points, 2 g snatch load",
                                      r, mat, dict(key="lifting")))
    else:
        acts = [a for a in veh.actuators if a.kind == "prop"]
        cog = veh.cog
        if "arm" in parts:
            arm = parts["arm"]
            r0, r1 = _ends(arm)
            axis = (r1 - r0) / np.linalg.norm(r1 - r0)
            root = lambda nd: (nd - r0) @ axis <= 0.02 * np.linalg.norm(r1 - r0)
            r = run("arm", arm, "shell", fixed=root, point_loads=[(r1, [0, 0, acts[0].tmax], 0.006)],
                    h=max(min(arm.extents) / 3, 0.002))
            out["cases"].append(_case("Arm at full thrust", f"{acts[0].tmax:.1f} N at the motor, arm as a {t * 1e3:.1f} mm wall tube, clamped at the body",
                                      r, mat, dict(key="arm")))
        loads = [((a.pos + cog) * [1, -1, -1], np.array([0, 0, a.tmax]), 0.02) for a in acts]
        r = run("frame", m_flu, "solid", point_loads=loads, steps=("static", "modes"), h=m_flu.extents.max() / 60)
        hover_hz = acts[0].wmax / (2 * np.pi) * np.sqrt(veh.mass * 9.81 / len(acts) / acts[0].tmax)
        f1 = (r.get("frequencies_hz") or [None])[0]
        out.update(safety_factor=fea.MATERIALS[mat]["yield_"] / r["vm_p99"], vm_p99=r["vm_p99"], u_max_mm=r["u_max"] * 1e3,
                   frequencies_hz=r.get("frequencies_hz"), hover_rotor_hz=hover_hz, max_rotor_hz=acts[0].wmax / (2 * np.pi),
                   resonance=bool(f1 and 0.8 * hover_hz <= f1 <= 1.25 * acts[0].wmax / (2 * np.pi)))
        out["cases"].append(_case("Whole frame at full thrust", "all motors at full thrust, frame free (inertia relief)", r, mat,
                                  dict(key="frame", first_mode_hz=f1, rotor_hz=[hover_hz, acts[0].wmax / (2 * np.pi)],
                                       note="solid parts overstate the strength of hollow tubes" if structure == "solid" else None)))
    sfs = [c["safety_factor"] for c in out["cases"] if c["safety_factor"]]
    out["worst_safety_factor"] = min(sfs) if sfs else None
    out["worst_case"] = min(out["cases"], key=lambda c: c["safety_factor"] or np.inf)["name"] if out["cases"] else None
    return out, fields


# ------------------------------------------------------------------ pipeline

def run(design_dir, skip=()):
    job = Job(design_dir)
    d = job.d
    spec = json.loads((d / "spec.json").read_text())
    kind = spec["kind"]
    res = dict(kind=kind, started=time.time(), warnings=[])
    try:
        job.status("running", "checking model", 0.02)
        m = trimesh.load(d / "mesh.stl", force="mesh")
        errors, warnings = check(kind, m, spec)
        res["warnings"] = warnings
        for w in warnings:
            job.log("warning: " + w)
        if errors:
            for e in errors:
                job.log("error: " + e)
            res["errors"] = errors
            job.status("failed", "model check", 1.0, errors=errors)
            (d / "result.json").write_text(json.dumps(res, default=_j))
            return res
        res["geometry"] = geom.report(m, kind, spec["mass"])
        hangar = {}
        v0 = vehicle.build(kind, m, spec)
        res["estimates"] = dict(cruise=ctrl.cruise_speed(v0), vmax=ctrl.max_speed(v0))
        job.log(f"model ok: {m.extents.round(3).tolist()} m, estimate cruise {res['estimates']['cruise']:.2f} "
                f"m/s, max {res['estimates']['vmax']:.2f} m/s")

        if kind != "uav" and "bem" not in skip:
            job.status("running", "added mass (BEM)", 0.08)
            draft = res["geometry"].get("draft")
            try:
                hangar["bem"] = bem(m, kind, v0.cog, draft)
                A = np.array(hangar["bem"]["added_mass"])
                job.log(f"BEM added mass diag: {np.diag(A).round(3).tolist()}")
            except Exception as e:                     # thin wings/fins can defeat the panel method
                msg = f"added mass from an estimate: the panel method failed ({type(e).__name__}: {str(e)[:120]})"
                res["warnings"].append(msg); job.log("warning: " + msg)

        if "cfd" not in skip:
          try:
              if kind == "usv":
                  job.status("running", "CFD: free-surface resistance (hours)", 0.15)
                  lwl = res["geometry"]["lwl"]
                  # Fn 0.2-0.4: the displacement range the free-surface method is validated over (receipts);
                  # above Fn 0.4 resistance is extrapolated ~V^2, flagged as an underestimate near hull speed
                  speeds = [float(fn * np.sqrt(9.81 * lwl)) for fn in (0.2, 0.3, 0.4)]
                  draft = res["geometry"]["draft"]
                  hangar["fs"] = cfd.cached(("surface", round(draft, 4), [round(x, 3) for x in speeds]), d / "mesh.stl", job.log,
                                            lambda: cfd.characterize_free_surface(d / "mesh.stl", draft, d / "cfd", speeds, log=job.log))
              else:
                  fluid, speed = ("air", 10.0) if kind == "uav" else ("water", min(1.5, res["estimates"]["vmax"]))
                  job.status("running", f"CFD: drag in 6 directions ({fluid}, {speed:.1f} m/s)", 0.15)
                  # moments about the mesh origin: vehicle.build moves them to the CoG itself
                  hangar["cfd"] = cfd.cached(("external", fluid, round(speed, 3)), d / "mesh.stl", job.log,
                                             lambda: cfd.characterize_external(d / "mesh.stl", d / "cfd", fluid, speed, log=job.log))
          except Exception as e:
            msg = f"drag from estimates: CFD failed ({type(e).__name__}: {str(e)[-200:]})"
            res["warnings"].append(msg); job.log("warning: " + msg)

        if kind == "uuv" and "cfd" in hangar and "aoa" not in skip:
          try:
              # hull lift at incidence, on the bare hull when the design has one: wings and fins are lifting
              # actuators already, so they must not be in this mesh twice
              hull = d / "part_hull.stl"
              stl, which = (hull, "hull") if hull.exists() else (d / "mesh.stl", "full")
              speed = hangar["cfd"]["speed"]
              job.status("running", f"CFD: hull lift at 5 and 10 deg incidence ({which} mesh)", 0.5)
              hangar["cfd_aoa"] = cfd.cached(("incidence", "water", round(speed, 3), (5.0, 10.0), "3-grid"), stl, job.log,
                                             lambda: cfd.characterize_incidence(stl, d / "cfd_aoa", "water", speed, log=job.log))
              hangar["cfd_aoa"]["mesh"] = which
          except Exception as e:
            msg = f"no hull lift: incidence CFD failed ({type(e).__name__}: {str(e)[-200:]})"
            res["warnings"].append(msg); job.log("warning: " + msg)

        # A two-grid GCI is only meaningful when both grids are in the asymptotic range. When the coarse grid is
        # far off (SUBOFF at Re 1.2e7: GCI ~150 % while the fine grid is within 3-8 % of the tank), the mission
        # Monte Carlo still uses it, which is conservative; say so instead of leaving an unexplained MARGINAL.
        gcis = [r.get("gci", 0.0) for c in (hangar.get("cfd"), hangar.get("cfd_aoa")) if c for r in c["dirs"].values()]
        gcis += [r.get("gci", 0.0) for r in (hangar.get("fs") or {}).get("speeds", {}).values()]
        if gcis and max(gcis) > 0.3:
            msg = (f"CFD grid study not converged: the coarse and fine meshes disagree (GCI up to {max(gcis):.0%}), so drag "
                   "uncertainty is wide and verdicts lean MARGINAL. A finer mesh level would narrow it")
            res["warnings"].append(msg); job.log("warning: " + msg)

        if "fea" not in skip:
          try:
              job.status("running", "FEA (CalculiX)", 0.85)
              v1 = vehicle.build(kind, m, spec, hangar)
              parts = {p.stem[5:]: trimesh.load(p, force="mesh") for p in sorted(d.glob("part_*.stl"))}
              res["fea"], fields = fea_cases(kind, m, spec, v1, parts, d / "fea")
              for key, field in fields.items():
                  if field is not None:
                      np.savez_compressed(d / f"fea_{key}.npz", **{k: np.asarray(v) for k, v in field.items()})
              for c in res["fea"]["cases"]:
                  job.log(f"FEA {c['name']}: safety factor {c['safety_factor'] or float('nan'):.2f}, "
                          f"stress {c['vm_p99_mpa']:.1f} MPa (99th pct), deflection {c['u_max_mm']:.2f} mm")
              lim = hangar.setdefault("limits", {})
              if kind == "uuv":
                  lim["crush_depth_m"] = res["fea"]["crush_depth"]
                  lim["rated_depth_m"] = res["fea"]["rated_depth"]
          except Exception as e:
            msg = f"structure NOT checked: FEA failed ({type(e).__name__}: {str(e)[-200:]}); no depth limit applied"
            res["warnings"].append(msg); job.log("warning: " + msg)

        if kind == "uuv" and ctrl.family(vehicle.build(kind, m, spec, hangar)) == "glider":
            job.status("running", "glide test (6-DOF yo)", 0.95)
            vg = vehicle.build(kind, m, spec, hangar)
            top = float(spec.get("top_m", 5.0))
            bottom = max(float(spec.get("dive_m", 100.0)), top + 20.0)
            bottom = min(bottom, hangar.get("limits", {}).get("rated_depth_m") or bottom)
            vs, t_yo = ctrl.glide_sim(vg, top, bottom)
            hangar.setdefault("limits", {}).update(glide_speed_sim=vs, glide_yo_s=t_yo, glide_band=[top, bottom])
            job.log(f"glide test: {vs:.3f} m/s made good over a {top:.0f}-{bottom:.0f} m yo ({t_yo / 60:.0f} min)")
        res["hangar"] = hangar
        v2 = vehicle.build(kind, m, spec, hangar)
        res["performance"] = dict(cruise=ctrl.cruise_speed(v2), vmax=ctrl.max_speed(v2), sources=v2.sources)
        res["finished"] = time.time()
        (d / "result.json").write_text(json.dumps(res, default=_j))
        job.log(f"done: cruise {res['performance']['cruise']:.2f} m/s, max {res['performance']['vmax']:.2f} m/s")
        job.status("done", "ready", 1.0)
    except Exception as e:
        job.log("crashed: " + "".join(traceback.format_exception(e))[-3000:])
        res["errors"] = [f"{type(e).__name__}: {e}"]
        (d / "result.json").write_text(json.dumps(res, default=_j))
        job.status("failed", "error", 1.0, errors=res["errors"])
    return res


def _j(o):
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return str(o)


def load_vehicle(design_dir):
    d = pathlib.Path(design_dir)
    spec = json.loads((d / "spec.json").read_text())
    m = trimesh.load(d / "mesh.stl", force="mesh")
    res = json.loads((d / "result.json").read_text()) if (d / "result.json").exists() else {}
    return vehicle.build(spec["kind"], m, spec, res.get("hangar", {}))


if __name__ == "__main__":
    run(sys.argv[1], skip=tuple(sys.argv[2].split(",")) if len(sys.argv) > 2 else ())
