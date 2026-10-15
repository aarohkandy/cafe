"""CFD with OpenFOAM v2506, modelled on the official motorBike (external RANS) and DTCHull
(free-surface interFoam/LTS) tutorials.

external(): one mesh, freestream BCs on every face, six inflow directions -> force/moment table.
free_surface(): fixed-attitude hull at its hydrostatic draft, resistance at several speeds.
Each runs at two snappy levels; the difference is the Grid Convergence Index (two-grid, p=2, Fs=3).
"""
import json, os, pathlib, re, shutil, subprocess, sys, time
import numpy as np
import trimesh

FOAM = "source /usr/lib/openfoam/openfoam2506/etc/bashrc >/dev/null 2>&1; "
NPROC = int(os.environ.get("CAFE_NPROC", "6"))
FLUIDS = {"water": dict(rho=1025.0, nu=1.19e-6), "air": dict(rho=1.20, nu=1.5e-5)}
DIRS = {"+x": (1, 0, 0), "-x": (-1, 0, 0), "+y": (0, 1, 0), "-y": (0, -1, 0), "+z": (0, 0, 1), "-z": (0, 0, -1)}


def dvec(d):
    """Unit direction for a label: an axis ("+x") or forward motion pitched/yawed toward an axis ("x+z10" =
    moving along +x tilted 10 deg toward +z, i.e. 10 deg angle of attack)."""
    if d in DIRS:
        return np.array(DIRS[d], float)
    m = re.fullmatch(r"x([+-][yz])([0-9.]+)", d)
    if not m:
        raise ValueError(f"bad direction {d!r}")
    a = np.radians(float(m.group(2)))
    return np.cos(a) * np.array(DIRS["+x"], float) + np.sin(a) * np.array(DIRS[m.group(1)], float)


CACHE = pathlib.Path(os.environ.get("CAFE_WORK", "/work")) / "cfdcache"


def cached(key, stl, log, compute):
    """Same mesh bytes + same case parameters -> same answer: reuse it (CFD costs minutes to hours)."""
    import hashlib
    h = hashlib.sha1(pathlib.Path(stl).read_bytes() + json.dumps(key).encode()).hexdigest()[:16]
    f = CACHE / f"{h}.json"
    if f.exists():
        log(f"CFD: reusing an identical earlier run ({f.name})")
        return json.loads(f.read_text())
    r = compute()
    CACHE.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(r, default=float))
    return r


def ittc57(re_):
    return 0.075 / (np.log10(re_) - 2) ** 2


# ---------------------------------------------------------------- plumbing

def sh(case, cmd, log):
    """Run an OpenFOAM command in `case`, log to file; raise with the log tail on failure."""
    r = subprocess.run(["bash", "-c", FOAM + f"cd {case} && {cmd} > log.{log} 2>&1"])
    if r.returncode:
        tail = pathlib.Path(case, f"log.{log}").read_text(errors="replace")[-3000:]
        raise RuntimeError(f"{log} failed in {case}:\n{tail}")


def par(cmd):
    return f"mpirun --oversubscribe -np {NPROC} {cmd} -parallel" if NPROC > 1 else cmd


def write(case, rel, body, cls="dictionary"):
    p = pathlib.Path(case, rel)
    p.parent.mkdir(parents=True, exist_ok=True)
    obj = p.name
    p.write_text(f"FoamFile\n{{\n    version 2.0;\n    format ascii;\n    class {cls};\n    object {obj};\n}}\n" + body)


def fill(text, **kw):
    for k, v in kw.items():
        if isinstance(v, (tuple, list, np.ndarray)):
            v = "(" + " ".join(f"{x:.9g}" for x in v) + ")"
        elif isinstance(v, float):
            v = f"{v:.9g}"
        text = text.replace(f"@{k}@", str(v))
    assert "@" not in text, re.findall(r"@\w+@", text)
    return text


def read_forces(case, name="forces"):
    """postProcessing/<name>/<t>/force.dat + moment.dat -> arrays (iter, total3, pressure3, viscous3)."""
    out = {}
    for kind in ("force", "moment"):
        rows = []
        for f in sorted(pathlib.Path(case, "postProcessing", name).glob(f"*/{kind}.dat")):
            for line in f.read_text().splitlines():
                if line.strip() and not line.startswith("#"):
                    rows.append([float(x) for x in line.replace("(", " ").replace(")", " ").split()])
        if not rows:
            raise RuntimeError(f"no {kind}.dat in {case}")
        a = np.array(rows)
        out[kind] = dict(it=a[:, 0], total=a[:, 1:4], pressure=a[:, 4:7], viscous=a[:, 7:10])
    return out


def tail_stats(series, frac=0.2):
    """Mean and std over the last `frac` of iterations (steady RANS/LTS still wobble)."""
    n = max(int(len(series) * frac), 20)
    s = series[-n:]
    return s.mean(0), s.std(0)


def mesh_stats(case):
    log = pathlib.Path(case, "log.checkMesh").read_text(errors="replace")
    cells = int(re.search(r"cells:\s+(\d+)", log).group(1))
    failed = re.search(r"Failed (\d+) mesh checks", log)
    return dict(cells=cells, failed_checks=int(failed.group(1)) if failed else 0)


def symmetric_y(m):
    """Is the body mirror symmetric about y=0? Compares mirrored-sample distances with the same
    sampling's own baseline, so sample spacing isn't mistaken for asymmetry."""
    from scipy.spatial import cKDTree
    pts = m.sample(4000)
    tree = cKDTree(m.sample(40000))
    d0, _ = tree.query(pts)
    d1, _ = tree.query(pts * [1, -1, 1])
    return bool(np.percentile(d1, 99) < 1.5 * np.percentile(d0, 99) + 1e-4 * m.extents.max())


COMMON_SCHEMES = """
gradSchemes { default Gauss linear; grad(U) cellLimited Gauss linear 1; limitedGrad cellLimited Gauss linear 1; }
laplacianSchemes { default Gauss linear limited corrected 0.33; }
interpolationSchemes { default linear; }
snGradSchemes { default limited corrected 0.33; }
wallDist { method meshWave; }
"""

QUALITY = """
meshQualityControls
{
    #includeEtc "caseDicts/mesh/generation/meshQualityDict.cfg"
}
mergeTolerance 1e-6;
"""

# ---------------------------------------------------------------- external (UUV, UAV)

EXT_SNAPPY = """
castellatedMesh true; snap true; addLayers true;
geometry { body.stl { type triSurfaceMesh; name body; } }
castellatedMeshControls
{
    maxLocalCells 2000000; maxGlobalCells 6000000; minRefinementCells 10;
    maxLoadUnbalance 0.10; nCellsBetweenLevels 3;
    features ( { file "body.eMesh"; level @lvl@; } );
    refinementSurfaces { body { level (@lvl@ @lvl@); patchInfo { type wall; } } }
    resolveFeatureAngle 30;
    refinementRegions { body { mode distance; levels ((@d1@ @lvl1@) (@d2@ @lvl2@)); } }
    locationInMesh @loc@;
    allowFreeStandingZoneFaces true;
}
snapControls { nSmoothPatch 3; tolerance 2.0; nSolveIter 50; nRelaxIter 5; nFeatureSnapIter 10;
               implicitFeatureSnap false; explicitFeatureSnap true; multiRegionFeatureSnap false; }
addLayersControls
{
    relativeSizes true;
    layers { body { nSurfaceLayers 3; } }
    expansionRatio 1.2; finalLayerThickness 0.5; minThickness 0.1; nGrow 0;
    featureAngle 60; slipFeatureAngle 30; nRelaxIter 3; nSmoothSurfaceNormals 1; nSmoothNormals 3;
    nSmoothThickness 10; maxFaceThicknessRatio 0.5; maxThicknessToMedialRatio 0.3;
    minMedialAxisAngle 90; nBufferCellsNoExtrude 0; nLayerIter 50;
}
""" + QUALITY

EXT_FIELDS = {
    "U": ("volVectorField", "[0 1 -1 0 0 0 0]", "uniform @U@",
          "farfield { type freestreamVelocity; freestreamValue uniform @U@; }\n"
          "    body { type noSlip; }"),
    "p": ("volScalarField", "[0 2 -2 0 0 0 0]", "uniform 0",
          "farfield { type freestreamPressure; freestreamValue uniform 0; }\n"
          "    body { type zeroGradient; }"),
    "k": ("volScalarField", "[0 2 -2 0 0 0 0]", "uniform @k@",
          "farfield { type inletOutlet; inletValue uniform @k@; value uniform @k@; }\n"
          "    body { type kqRWallFunction; value uniform @k@; }"),
    "omega": ("volScalarField", "[0 0 -1 0 0 0 0]", "uniform @omega@",
              "farfield { type inletOutlet; inletValue uniform @omega@; value uniform @omega@; }\n"
              "    body { type omegaWallFunction; value uniform @omega@; }"),
    "nut": ("volScalarField", "[0 2 -1 0 0 0 0]", "uniform 0",
            "farfield { type calculated; value uniform 0; }\n"
            "    body { type nutUSpaldingWallFunction; value uniform 0; }"),
}


def _fields(case, fields, root="0", **kw):
    for name, (cls, dim, internal, bcs) in fields.items():
        write(case, f"{root}/{name}", fill(
            f"dimensions {dim};\ninternalField {internal};\nboundaryField\n{{\n"
            f"    #includeEtc \"caseDicts/setConstraintTypes\"\n    {bcs}\n}}\n", **kw), cls)


def _control(app, end, functions, extra=""):
    return (f"application {app};\nstartFrom startTime;\nstartTime 0;\nstopAt endTime;\nendTime {end};\n"
            f"deltaT 1;\nwriteControl timeStep;\nwriteInterval {end};\npurgeWrite 1;\nwriteFormat binary;\n"
            f"writePrecision 8;\nwriteCompression off;\ntimeFormat general;\ntimePrecision 6;\n"
            f"runTimeModifiable false;\n{extra}\nfunctions\n{{\n{functions}\n}}\n")


def _forces_fo(rho_line, cofr, patch="body"):
    return f"""    forces
    {{
        type forces; libs (forces); patches ({patch}); {rho_line}
        CofR ({cofr[0]:.9g} {cofr[1]:.9g} {cofr[2]:.9g}); writeControl timeStep; writeInterval 1; log false;
    }}
"""


SURF_FO = """    bodyPressure
    {
        type surfaces; libs (sampling); writeControl onEnd; surfaceFormat raw; fields (p);
        surfaces { body { type patch; patches (body); interpolate false; } }
    }
"""


def external(stl, case, fluid="water", speed=1.5, dirs=tuple(DIRS), level_offset=0, cofr=(0, 0, 0),
             iters=1500, pressure_dir="+x", log=print):
    """Steady RANS on one mesh for several inflow directions. Returns dict per direction:
    force/moment (N, N.m, body frame) for a body moving at `speed` along that direction."""
    case = pathlib.Path(case)
    shutil.rmtree(case, ignore_errors=True)
    m = trimesh.load(stl, force="mesh")
    L = float(m.extents.max())
    fl = FLUIDS[fluid]
    # sizes: domain half-width 4L; base cell L/4; surface cell min(L/200, thinnest bbox side/16)
    D, h0 = 4 * L, L / 4
    hs = min(L / 200, m.extents.min() / 16)
    lvl = int(np.ceil(np.log2(h0 / hs))) + level_offset
    n = int(round(2 * D / h0))
    (case / "constant/triSurface").mkdir(parents=True)
    m.export(case / "constant/triSurface/body.stl")
    write(case, "system/blockMeshDict", fill("""
scale 1;
vertices ((-@D@ -@D@ -@D@) (@D@ -@D@ -@D@) (@D@ @D@ -@D@) (-@D@ @D@ -@D@)
          (-@D@ -@D@ @D@) (@D@ -@D@ @D@) (@D@ @D@ @D@) (-@D@ @D@ @D@));
blocks (hex (0 1 2 3 4 5 6 7) (@n@ @n@ @n@) simpleGrading (1 1 1));
boundary ( farfield { type patch; faces ((3 7 6 2) (0 4 7 3) (2 6 5 1) (1 5 4 0) (0 3 2 1) (4 5 6 7)); } );
""", D=D, n=n))
    write(case, "system/surfaceFeatureExtractDict", """
body.stl { extractionMethod extractFromSurface; includedAngle 150;
           subsetFeatures { nonManifoldEdges no; openEdges yes; } writeObj no; }
""")
    write(case, "system/snappyHexMeshDict", fill(EXT_SNAPPY, lvl=lvl, lvl1=max(lvl - 2, 1), lvl2=max(lvl - 4, 1),
                                                 d1=0.1 * L, d2=0.5 * L, loc=(0.713 * D, 0.627 * D, 0.571 * D)))
    write(case, "system/decomposeParDict", f"numberOfSubdomains {NPROC};\nmethod scotch;\n")
    write(case, "system/fvSchemes", """
ddtSchemes { default steadyState; }
divSchemes
{
    default none;
    div(phi,U) bounded Gauss linearUpwindV grad(U);
    div(phi,k) bounded Gauss upwind;
    div(phi,omega) bounded Gauss upwind;
    div((nuEff*dev2(T(grad(U))))) Gauss linear;
}
""" + COMMON_SCHEMES)
    write(case, "system/fvSolution", """
solvers
{
    p { solver GAMG; smoother GaussSeidel; tolerance 1e-7; relTol 0.01; }
    "(U|k|omega)" { solver smoothSolver; smoother GaussSeidel; tolerance 1e-8; relTol 0.1; nSweeps 1; }
}
SIMPLE { nNonOrthogonalCorrectors 1; consistent yes; residualControl { p 1e-5; U 1e-6; "(k|omega)" 1e-6; } }
relaxationFactors { equations { U 0.9; k 0.7; omega 0.7; } fields { p 1; } }
cache { grad(U); }
""")
    write(case, "constant/transportProperties", f"transportModel Newtonian;\nnu {fl['nu']:.6g};\n")
    write(case, "constant/turbulenceProperties", "simulationType RAS;\nRAS { RASModel kOmegaSST; turbulence on; printCoeffs off; }\n")
    write(case, "system/controlDict", _control("simpleFoam", iters, ""))
    t0 = time.time()
    sh(case, "blockMesh", "blockMesh")
    sh(case, "surfaceFeatureExtract", "surfaceFeatureExtract")
    sh(case, "decomposePar -force", "decomposeMesh")
    sh(case, par("snappyHexMesh -overwrite"), "snappyHexMesh")
    sh(case, par("checkMesh -constant"), "checkMesh")
    ms = mesh_stats(case)
    log(f"mesh: {ms['cells']} cells, level {lvl}, {time.time() - t0:.0f}s")
    # turbulence inflow: 1% intensity, viscosity ratio 10
    k = 1.5 * (0.01 * speed) ** 2
    omega = k / (10 * fl["nu"])
    results = {}
    for d in dirs:
        U = -speed * dvec(d)     # body moving along +d == fluid moving along -d
        fos = _forces_fo(f"rho rhoInf; rhoInf {fl['rho']};", cofr) + (SURF_FO if d == pressure_dir else "")
        write(case, "system/controlDict", _control("simpleFoam", iters, fos))
        for p in case.glob("processor*"):
            for t in p.iterdir():
                if t.name != "constant":
                    shutil.rmtree(t)
            _fields(p, EXT_FIELDS, U=U, k=k, omega=omega)
        shutil.rmtree(case / "postProcessing", ignore_errors=True)
        t1 = time.time()
        sh(case, par("simpleFoam"), f"simpleFoam.{d}")
        f = read_forces(case)
        tot, std = tail_stats(f["force"]["total"])
        res = dict(force=tot.tolist(), force_std=std.tolist(),
                   pressure=tail_stats(f["force"]["pressure"])[0].tolist(),
                   viscous=tail_stats(f["force"]["viscous"])[0].tolist(),
                   moment=tail_stats(f["moment"]["total"])[0].tolist(),
                   iters=int(f["force"]["it"][-1]), seconds=time.time() - t1)
        if d == pressure_dir:
            res["surface_pressure"] = _keep_surface(case, "bodyPressure", fl["rho"])
        drag = -np.dot(tot, dvec(d))
        log(f"{d}: drag {drag:.4g} N  (CdA {2 * drag / (fl['rho'] * speed ** 2):.4g} m2), "
            f"{res['iters']} it, {res['seconds']:.0f}s")
        results[d] = res
    return dict(fluid=fluid, rho=fl["rho"], nu=fl["nu"], speed=speed, L=L, level=lvl, mesh=ms, dirs=results,
                seconds=time.time() - t0)


def _keep_surface(case, fo, rho):
    """Copy the sampled body pressure (kinematic p -> Pa) out of the case before it is deleted."""
    raw = sorted(pathlib.Path(case, "postProcessing", fo).glob("*/*.raw")) + \
          sorted(pathlib.Path(case, "postProcessing", fo).glob("*/*/*.raw"))
    if not raw:
        return None
    a = np.loadtxt(raw[-1], comments="#")
    out = pathlib.Path(case).parent / (pathlib.Path(case).name + ".pressure.npy")
    a[:, 3] *= rho
    np.save(out, a)   # columns x y z p[Pa], face centres
    return str(out)


def gci(fine, coarse, ratio=2.0, p=2.0, fs=3.0):
    """Two-grid Grid Convergence Index (Roache): relative uncertainty of the fine-grid value."""
    eps = (coarse - fine) / fine
    return fs * abs(eps) / (ratio ** p - 1)


def characterize_external(stl, workdir, fluid, speed, cofr=(0, 0, 0), dirs=tuple(DIRS), log=print, refine_above=0.3):
    """Coarse + fine runs; returns the finest result with a per-direction GCI against the next coarser grid.
    A two-grid GCI only means something when both grids are in the asymptotic range. Slender bare hulls at
    level 5 aren't (SUBOFF: coarse drag 2.5x the fine one, which is within 3 % of the towing tank), so when any
    direction's GCI exceeds `refine_above` a third, finer grid is run and the GCI is taken between fine and finer.
    Case dirs are deleted afterwards (disk on homebase is tight); logs and pressures are kept."""
    workdir = pathlib.Path(workdir)
    out = {}

    def run(name, off):
        log(f"--- {name} mesh")
        out[name] = external(stl, workdir / name, fluid, speed, dirs, off, cofr, log=log)
        _shrink(workdir / name)

    def study(res, ref):
        for d, r in res["dirs"].items():
            drag_f = -np.dot(r["force"], dvec(d))
            drag_c = -np.dot(ref["dirs"][d]["force"], dvec(d))
            r["gci"] = gci(drag_f, drag_c)
            r["drag_coarse"] = drag_c                    # "coarse" = the next coarser grid of the study
            r["force_coarse"] = ref["dirs"][d]["force"]
            r["moment_coarse"] = ref["dirs"][d]["moment"]
        res["coarse_cells"] = ref["mesh"]["cells"]
        return max(r["gci"] for r in res["dirs"].values())

    run("coarse", -1)
    run("fine", 0)
    worst = study(out["fine"], out["coarse"])
    if worst <= refine_above:
        out["fine"]["grids"] = 2
        return out["fine"]
    log(f"coarse grid outside the asymptotic range (GCI {worst:.0%}): adding a finer grid")
    run("finer", 1)
    study(out["finer"], out["fine"])
    out["finer"]["grids"] = 3
    out["finer"]["gci_two_grid"] = worst
    return out["finer"]


def characterize_incidence(stl, workdir, fluid, speed, alphas=(5.0, 10.0), planes=("+y", "+z"), cofr=(0, 0, 0), log=print):
    """Hull lift: forward motion at each angle in `alphas` toward each plane's axis, plus the on-axis runs on the
    SAME mesh that the cross term is measured against (same-grid differencing cancels most discretization error)."""
    dirs = ("+x",) + tuple(planes) + tuple(f"x{p}{a:g}" for p in planes for a in alphas)
    r = characterize_external(stl, workdir, fluid, speed, cofr, dirs=dirs, log=log)
    r["alphas"], r["planes"] = list(alphas), list(planes)
    return r


def _shrink(case):
    """Delete mesh/fields, keep logs + postProcessing."""
    for p in list(case.glob("processor*")) + [case / "constant/polyMesh", case / "constant/triSurface"]:
        shutil.rmtree(p, ignore_errors=True)


# ---------------------------------------------------------------- free surface (USV)

FS_FIELDS = {
    "U": ("volVectorField", "[0 1 -1 0 0 0 0]", "uniform (@mU@ 0 0)",
          "inlet { type fixedValue; value uniform (@mU@ 0 0); }\n"
          "    outlet { type outletPhaseMeanVelocity; alpha alpha.water; Umean @U@; value uniform (@mU@ 0 0); }\n"
          "    atmosphere { type pressureInletOutletVelocity; value uniform (0 0 0); }\n"
          "    hull { type movingWallVelocity; value uniform (0 0 0); }"),
    "p_rgh": ("volScalarField", "[1 -1 -2 0 0 0 0]", "uniform 0",
              "inlet { type fixedFluxPressure; value uniform 0; }\n"
              "    outlet { type zeroGradient; }\n"
              "    atmosphere { type totalPressure; p0 uniform 0; }\n"
              "    hull { type fixedFluxPressure; value uniform 0; }"),
    "alpha.water": ("volScalarField", "[0 0 0 0 0 0 0]", "uniform 0",
                    "inlet { type fixedValue; value uniform 0; }\n"
                    "    outlet { type variableHeightFlowRate; lowerBound 0; upperBound 1; value uniform 0; }\n"
                    "    atmosphere { type inletOutlet; inletValue uniform 0; value uniform 0; }\n"
                    "    hull { type zeroGradient; }"),
    "k": ("volScalarField", "[0 2 -2 0 0 0 0]", "uniform @k@",
          "inlet { type fixedValue; value uniform @k@; }\n"
          "    outlet { type inletOutlet; inletValue uniform @k@; value uniform @k@; }\n"
          "    atmosphere { type inletOutlet; inletValue uniform @k@; value uniform @k@; }\n"
          "    hull { type kqRWallFunction; value uniform @k@; }"),
    "omega": ("volScalarField", "[0 0 -1 0 0 0 0]", "uniform @omega@",
              "inlet { type fixedValue; value uniform @omega@; }\n"
              "    outlet { type inletOutlet; inletValue uniform @omega@; value uniform @omega@; }\n"
              "    atmosphere { type inletOutlet; inletValue uniform @omega@; value uniform @omega@; }\n"
              "    hull { type omegaWallFunction; value uniform @omega@; }"),
    "nut": ("volScalarField", "[0 2 -1 0 0 0 0]", "uniform 0",
            "inlet { type fixedValue; value uniform 0; }\n"
            "    outlet { type zeroGradient; }\n"
            "    atmosphere { type zeroGradient; }\n"
            "    hull { type nutUSpaldingWallFunction; value uniform 0; }"),
}


def free_surface(stl, draft, case, speeds, level_offset=0, cofr=(0, 0, 0), iters=3000, log=print, surf_level=1):
    """interFoam LTS at each speed on one mesh. Hull is shifted so the waterline is z=0.
    Returns per-speed resistance (N, full hull) and vertical force (sinkage check)."""
    case = pathlib.Path(case)
    shutil.rmtree(case, ignore_errors=True)
    m = trimesh.load(stl, force="mesh")
    m.apply_translation([0, 0, -draft])
    lo, hi = m.bounds
    m.apply_translation([-(lo[0] + hi[0]) / 2, 0, 0])
    L = float(m.extents[0])
    half = symmetric_y(m)
    fl = FLUIDS["water"]
    (case / "constant/triSurface").mkdir(parents=True)
    m.export(case / "constant/triSurface/hull.stl")
    # domain in hull lengths (DTCHull proportions): 2L ahead of the bow, 3.5L behind, 3.3L wide, 2.8L deep
    x0, x1, y0, z0, z1 = -4.0 * L, 2.5 * L, -3.3 * L, -2.8 * L, 0.7 * L
    y1 = 0.0 if half else 3.3 * L
    h0 = 0.2 * L
    nx, ny = int((x1 - x0) / h0), int((y1 - y0) / h0)
    zs = [z0, -0.15 * L, -0.03 * L, 0.03 * L, 0.2 * L, z1]
    nz = [24, 14, 20, 16, 12]
    grade = [0.05, 1, 1, 1, 6]
    verts, blocks = [], []
    for z in zs:
        verts += [(x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z)]
    for b in range(5):
        v = list(range(4 * b, 4 * b + 8))
        blocks.append(f"hex ({' '.join(map(str, v))}) ({nx} {ny} {nz[b]}) simpleGrading (1 1 {grade[b]})")
    face = lambda a, b, c, d: f"({a} {b} {c} {d})"
    side = lambda i0, i1: [face(4 * b + i0, 4 * b + i1, 4 * b + 4 + i1, 4 * b + 4 + i0) for b in range(5)]
    bnd = {
        "atmosphere": ("patch", [face(20, 21, 22, 23)]),
        "inlet": ("patch", side(1, 2)),
        "outlet": ("patch", side(3, 0)),
        "bottom": ("symmetryPlane", [face(0, 3, 2, 1)]),
        "side": ("symmetryPlane", side(0, 1)),
    }
    if not half:
        bnd["side2"] = ("symmetryPlane", side(2, 3))    # each symmetry patch must be planar
    if half:
        bnd["midPlane"] = ("symmetryPlane", side(2, 3))
    write(case, "system/blockMeshDict", "scale 1;\nvertices (\n" + "\n".join(f"({x:.9g} {y:.9g} {z:.9g})" for x, y, z in verts)
          + "\n);\nblocks (\n" + "\n".join(blocks) + "\n);\nboundary (\n"
          + "\n".join(f"{k} {{ type {t}; faces ({' '.join(f)}); }}" for k, (t, f) in bnd.items()) + "\n);\n")
    # nested horizontal-only refinement around hull and Kelvin wedge (DTCHull's topoSet/refineMesh trick)
    boxes = [(-2.6, 1.3, 1.4, -0.6, 0.3), (-1.6, 0.95, 0.75, -0.4, 0.22), (-1.0, 0.75, 0.4, -0.3, 0.16),
             (-0.75, 0.62, 0.22, -0.25, 0.12)][:4 + level_offset]
    write(case, "system/refineMeshDict", "set c0;\ncoordinateSystem global;\nglobalCoeffs { tan1 (1 0 0); tan2 (0 1 0); }\n"
          "directions (tan1 tan2);\nuseHexTopology no;\ngeometricCut yes;\nwriteMesh no;\n")
    for i, (bx0, bx1, by, bz0, bz1) in enumerate(boxes):
        ylo, yhi = (-by * L, 0.01 * L) if half else (-by * L, by * L)
        write(case, f"system/topoSetDict.{i}", f"actions ( {{ name c0; type cellSet; action new; source boxToCell; "
              f"box ({bx0 * L:.9g} {ylo:.9g} {bz0 * L:.9g}) ({bx1 * L:.9g} {yhi:.9g} {bz1 * L:.9g}); }} );\n")
    write(case, "system/surfaceFeatureExtractDict", """
hull.stl { extractionMethod extractFromSurface; includedAngle 150;
           subsetFeatures { nonManifoldEdges no; openEdges yes; } writeObj no; }
""")
    write(case, "system/snappyHexMeshDict", fill("""
castellatedMesh true; snap true; addLayers true;
geometry { hull.stl { type triSurfaceMesh; name hull; } }
castellatedMeshControls
{
    maxLocalCells 2000000; maxGlobalCells 6000000; minRefinementCells 0; nCellsBetweenLevels 3;
    features ( { file "hull.eMesh"; level @sl@; } );
    refinementSurfaces { hull { level (@sl@ @sl@); patchInfo { type wall; } } }
    resolveFeatureAngle 45;
    refinementRegions { }
    locationInMesh @loc@;
    allowFreeStandingZoneFaces true;
}
snapControls { nSmoothPatch 3; tolerance 1.0; nSolveIter 100; nRelaxIter 5; nFeatureSnapIter 10;
               implicitFeatureSnap false; explicitFeatureSnap true; multiRegionFeatureSnap false; }
addLayersControls
{
    relativeSizes true;
    layers { hull { nSurfaceLayers 2; } }
    expansionRatio 1.3; finalLayerThickness 0.6; minThickness 0.2; nGrow 0; featureAngle 60;
    nRelaxIter 5; nSmoothSurfaceNormals 1; nSmoothNormals 3; nSmoothThickness 10;
    maxFaceThicknessRatio 0.5; maxThicknessToMedialRatio 0.3; minMedialAxisAngle 90;
    nBufferCellsNoExtrude 0; nLayerIter 50; nRelaxedIter 20;
}
""" + QUALITY, loc=(-0.71 * L, -0.83 * L, -0.37 * L), sl=surf_level))
    write(case, "system/setFieldsDict", "defaultFieldValues ( volScalarFieldValue alpha.water 0 );\n"
          "regions ( boxToCell { box (-1e9 -1e9 -1e9) (1e9 1e9 0); fieldValues ( volScalarFieldValue alpha.water 1 ); }\n"
          "          boxToFace { box (-1e9 -1e9 -1e9) (1e9 1e9 0); fieldValues ( volScalarFieldValue alpha.water 1 ); } );\n")
    write(case, "system/decomposeParDict", f"numberOfSubdomains {NPROC};\nmethod scotch;\n")
    write(case, "system/fvSchemes", """
ddtSchemes { default localEuler; }
divSchemes
{
    div(rhoPhi,U) Gauss linearUpwind grad(U);
    div(phi,alpha) Gauss vanLeer;
    div(phirb,alpha) Gauss linear;
    div(phi,k) Gauss linearUpwind limitedGrad;
    div(phi,omega) Gauss linearUpwind limitedGrad;
    div(((rho*nuEff)*dev2(T(grad(U))))) Gauss linear;
}
""" + COMMON_SCHEMES)
    write(case, "system/fvSolution", """
solvers
{
    "alpha.water.*" { nAlphaCorr 2; nAlphaSubCycles 1; cAlpha 1; icAlpha 0; MULESCorr yes; nLimiterIter 10;
                      alphaApplyPrevCorr yes; solver smoothSolver; smoother symGaussSeidel; tolerance 1e-8; relTol 0; minIter 1; }
    "pcorr.*" { solver PCG; preconditioner { preconditioner GAMG; smoother GaussSeidel; tolerance 1e-5; relTol 0; }
                tolerance 1e-5; relTol 0; }
    p_rgh { solver GAMG; smoother DIC; tolerance 1e-7; relTol 0.01; }
    p_rghFinal { $p_rgh; relTol 0; }
    "(U|k|omega).*" { solver smoothSolver; smoother symGaussSeidel; nSweeps 1; tolerance 1e-7; relTol 0.1; minIter 1; }
}
PIMPLE
{
    momentumPredictor no; nOuterCorrectors 1; nCorrectors 2; nNonOrthogonalCorrectors 1;
    maxCo 10; maxAlphaCo 5; rDeltaTSmoothingCoeff 0.05; rDeltaTDampingCoeff 0.5;
    nAlphaSpreadIter 0; nAlphaSweepIter 0; maxDeltaT 1;
}
relaxationFactors { equations { ".*" 1; } }
cache { grad(U); }
""")
    write(case, "constant/transportProperties", f"""phases (water air);
water {{ transportModel Newtonian; nu {fl['nu']:.6g}; rho {fl['rho']:.6g}; }}
air {{ transportModel Newtonian; nu 1.48e-05; rho 1; }}
sigma 0;
""")
    write(case, "constant/turbulenceProperties", "simulationType RAS;\nRAS { RASModel kOmegaSST; turbulence on; printCoeffs off; }\n")
    write(case, "constant/g", "dimensions [0 1 -2 0 0 0 0];\nvalue (0 0 -9.81);\n", "uniformDimensionedVectorField")
    write(case, "constant/hRef", "dimensions [0 1 0 0 0 0 0];\nvalue 0;\n", "uniformDimensionedScalarField")
    write(case, "system/controlDict", _control("interFoam", iters, ""))
    t0 = time.time()
    sh(case, "blockMesh", "blockMesh")
    sh(case, "surfaceFeatureExtract", "surfaceFeatureExtract")
    for i in range(len(boxes)):
        sh(case, f"topoSet -dict system/topoSetDict.{i}", f"topoSet.{i}")
        sh(case, "refineMesh -dict system/refineMeshDict -overwrite", f"refineMesh.{i}")
    sh(case, "decomposePar -force", "decomposeMesh")
    sh(case, par("snappyHexMesh -overwrite"), "snappyHexMesh")
    sh(case, par("checkMesh -constant"), "checkMesh")
    ms = mesh_stats(case)
    log(f"mesh: {ms['cells']} cells ({'half' if half else 'full'} domain), {time.time() - t0:.0f}s")
    results = {}
    for U in speeds:
        k = 1.5 * (0.01 * U) ** 2
        omega = k / (10 * fl["nu"])
        write(case, "system/controlDict", _control("interFoam", iters, _forces_fo("", cofr, "hull")))
        for p in case.glob("processor*"):
            for t in p.iterdir():
                if t.name != "constant":
                    shutil.rmtree(t)
            _fields(p, FS_FIELDS, U=U, mU=-U, k=k, omega=omega)
        shutil.rmtree(case / "postProcessing", ignore_errors=True)
        sh(case, par("setFields"), f"setFields.{U}")
        t1 = time.time()
        sh(case, par("interFoam"), f"interFoam.{U}")
        f = read_forces(case)
        tot, std = tail_stats(f["force"]["total"])
        k2 = 1 if half else 0.5   # half domain -> double
        R = -tot[0] * 2 * k2
        res = dict(resistance=R, resistance_std=std[0] * 2 * k2, lift=tot[2] * 2 * k2,
                   viscous_x=-tail_stats(f["force"]["viscous"])[0][0] * 2 * k2,
                   iters=int(f["force"]["it"][-1]), seconds=time.time() - t1)
        log(f"V={U}: R {R:.4g} N (Fn {U / np.sqrt(9.81 * L):.3f}), Fz {res['lift']:.4g} N, {res['seconds']:.0f}s")
        results[U] = res
    return dict(L=L, half=half, mesh=ms, speeds=results, seconds=time.time() - t0)


def characterize_free_surface(stl, draft, workdir, speeds, log=print):
    workdir = pathlib.Path(workdir)
    for sl in (1, 0):
        out = {}
        try:
            for name, off in (("coarse", -1), ("fine", 0)):
                log(f"--- {name} mesh")
                out[name] = free_surface(stl, draft, workdir / name, speeds, off, log=log, surf_level=sl)
                _shrink(workdir / name)
            break
        except RuntimeError:
            # refineMesh's directional (2-D) splits carry no hexRef8 history, so snappy can't always refine them
            # again near the hull ("uses more than 8 points"). Then redo BOTH grids without that extra level,
            # so the two grids still differ only by the background refinement and the GCI stays meaningful.
            snap = workdir / name / "log.snappyHexMesh"
            if sl == 0 or not (snap.exists() and "more than 8 points" in snap.read_text(errors="replace")):
                raise
            log("snappy can't refine the pre-refined cells at the hull; redoing both grids without snappy's surface level")
    fine = out["fine"]
    for U, r in fine["speeds"].items():
        r["gci"] = gci(r["resistance"], out["coarse"]["speeds"][U]["resistance"])
    fine["coarse_cells"] = out["coarse"]["mesh"]["cells"]
    return fine


if __name__ == "__main__":
    # python -m cafe.cfd external|surface SAMPLE WORKDIR  (smoke runs on the built-in samples)
    from cafe import geom
    what, sample, work = sys.argv[1], sys.argv[2], pathlib.Path(sys.argv[3])
    work.mkdir(parents=True, exist_ok=True)
    s = geom.SAMPLES[sample]
    m = s["make"]()
    stl = work / f"{sample}.stl"
    m.export(stl)
    if what == "incidence":
        # model-scale tow speed (Roddy 1990 drift tests at 6.5 kn), fresh-water viscosity of the tank
        speed = float(sys.argv[4]) if len(sys.argv) > 4 else 1.5
        r = characterize_incidence(stl, work / sample, "water", speed, planes=("+y",))
    elif what == "external":
        fluid, speed = ("air", 10.0) if s["kind"] == "uav" else ("water", 1.5)
        dirs = sys.argv[4].split(",") if len(sys.argv) > 4 else tuple(DIRS)
        r = characterize_external(stl, work / sample, fluid, speed, dirs=dirs)
    else:
        hs = geom.hydrostatics(m, s["spec"]["mass"])
        L = hs["lwl"]
        speeds = [float(fn * np.sqrt(9.81 * L)) for fn in (0.2, 0.3, 0.4)]
        r = characterize_free_surface(stl, hs["draft"], work / sample, speeds)
    (work / f"{sample}.{what}.json").write_text(json.dumps(r, indent=1, default=float))
    print(json.dumps(r, indent=1, default=float)[:3000])
