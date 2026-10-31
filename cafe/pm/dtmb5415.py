"""DTMB 5415 / INSEAN 2340 bare-hull free-surface validation of cafe's interFoam path (cafe.cfd.free_surface).

Reference: total resistance coefficient C_T = R / (0.5 rho U^2 S) of the 5.72 m INSEAN 2340 model at Fr = U / sqrt(g Lpp)
= 0.10, 0.20, 0.28, 0.41 (docs/BRIEF.md 5.2; Olivieri et al. 2001, DTIC ADA458075 - that PDF answered HTTP 403 to a
plain request on 2026-10-29, so the four numbers are the brief's and were not re-read at source).

Geometry: SIMMAN 2008 "5415 hull (FORCE 2004, IIHR 2005, INSEAN 2005)" IGES, three rational B-spline patches in metres
at INSEAN model scale (24.83). Downloaded and checked against two SHA-256 sums, lofted to a closed STL here (no CAD
kernel: the patches overlap, which OpenCASCADE cannot sew). Hydrostatics of the STL are receipts against the SIMMAN
table (displacement 0.554 m3, Lwl 5.726 m, Bwl 0.768 m), so a wrong scale or a bad loft fails.

Known gaps against the experiment, all inside E and none hidden: the hull is held at its static draft (the model was
free to sink and trim); the raked transom overhang above the waterline is closed by a flat plate at the last
station; appendages and bilge keels are absent; the CFD uses fresh-water density and viscosity at an assumed 20 C.

Method (second study; the first, a 151 k / 331 k pair, is discarded). Measured on it with the yPlus function object (200 iterations, same
meshes): the fine grid had hull prism layers (2 of ~2.2 mm, 67 % of their thickness) and sat at a wetted-area-mean y+ of 192 at Fr 0.41
(patch max 1950), the coarse grid had none (2.6 %) and sat at 960 at Fr 0.20 (max 3670). The pair therefore differed in wall-function error
as much as in cell size, and at Fr 0.10 the fine run's resistance was still swinging by 6 % (std of the last quarter) at 2000 iterations.
Now: the first prism layer is sized per Froude number for y+ = 100 (`first_layer`) and is the same on three grids (`GRIDS`); each case
runs in CHUNK-iteration restarts until the last-quarter drift and scatter of the resistance history are inside DRIFT_TOL / SCATTER_TOL
(`_converge`, `settle`) or MAX_ITERS; y+ (wetted-area mean), prism-layer coverage, drift, scatter and the viscous share of C_T are stored
per case and receipted. U_num comes from Celik's three-grid GCI (observed order, Fs = 1.25) when it can, else from the two-grid Fs = 3
estimate with a stated reason (`discretization`). The pseudo-time march (cafe.cfd.FS_LTS) and the outlet boundary conditions
(cafe.cfd.FS_FIELDS) are cafe.cfd's own; the rest wraps cafe.cfd.free_surface without editing it (`case_recipe`).

Usage on homebase (see docs/BUILDERS.md):  ./pm.sh python -m cafe.pm.dtmb5415 prepare | run coarse|medium|fine [max_iters [fr,fr]] | report
"""
import contextlib
import hashlib
import io
import json
import math
import os
import pathlib
import re
import shutil
import sys
import urllib.request
import zipfile
from typing import Any, Callable, Iterator, NamedTuple, Optional, Sequence, cast

import numpy as np
import trimesh
from scipy.interpolate import BSpline

from cafe import cfd
from cafe import receipts as rc
from cafe.pm import vv

_cfd: Any = cfd        # cafe.cfd is untyped and this module patches some of its globals; going through Any keeps both quiet

G = 9.81
SIMMAN = "SIMMAN 2008 DTMB 5415 geometry and conditions, INSEAN column (http://www.simman2008.dk/5415/5415_geometry.htm)"
URL = ("http://www.simman2008.dk/Technical%20data/ships/Frigate%205415/ship%20data/Geometry/"
       "hull%20(FORCE%202004,%20IIHR%202005,%20INSEAN%202005)/5415%20hull%20(FORCE%202004,%20IIHR%202005,%20INSEAN%202005).zip")
SHA_ZIP = "daae8a4bca5e586721f2ee71285d390625ec299782d5ee45a4fb22a4e789f50c"
SHA_IGS = "dac17b470ddadce21ec5a55d9d544181ac13027dd8ceda39e26fe26219bbbc28"
MEMBER = "5415.igs"
LPP, LWL, BWL, DRAFT, DISPLACEMENT = 5.719, 5.726, 0.768, 0.248, 0.554       # SIMMAN 2008, INSEAN model
CT_REF = {0.10: 4.02e-3, 0.20: 3.95e-3, 0.28: 4.23e-3, 0.41: 6.67e-3}        # docs/BRIEF.md 5.2
TANK = dict(rho=998.2, nu=1.004e-6)         # fresh water, 20 C (tank temperature not published in what was read): assumed
# Uncertainties with no source in hand. Relative to the quantity they apply to; `why` says what would replace them.
# config/assumptions.yaml overrides any of these by key (dtmb5415.<name>) so the lab can set them without code changes.
ASSUMED = {
    "u_D_rel": (0.010, "INSEAN 2340 resistance repeatability; Olivieri et al. 2001 states it, not read (DTIC 403)"),
    "u_S_rel": (0.013, "half the spread of the wetted area of the three published 5415 models scaled to 5.72 m (4.82-4.95 m2)"),
    "u_nu_rel": (0.006, "+-6 % in viscosity (water 20 +- 3 C) moves ITTC-57 C_F by ~1 %, ~60 % of C_T"),
}
# Free surface is held at the static draft, so these runs also differ from the experiment by sinkage and trim.


def data_root() -> pathlib.Path:
    return pathlib.Path(os.environ.get("CAFE_DATA", "/data")) / "dtmb5415"


def assumed(name: str, config: Optional[pathlib.Path] = None) -> float:
    """An assumed relative uncertainty: config/assumptions.yaml key `dtmb5415.<name>` if present, else the default."""
    path = config or pathlib.Path(__file__).resolve().parents[2] / "config" / "assumptions.yaml"
    if path.exists():
        import yaml
        entry = (yaml.safe_load(path.read_text()) or {}).get(f"dtmb5415.{name}")
        if entry is not None:
            return float(entry["value"] if isinstance(entry, dict) else entry)
    return ASSUMED[name][0]


# ------------------------------------------------------------------ geometry: IGES entity 128 -> closed STL

def fetch_igs(dest: pathlib.Path, url: Optional[str] = None, sha_zip: Optional[str] = None, sha_igs: Optional[str] = None,
              opener: Callable[[str], Any] = urllib.request.urlopen) -> pathlib.Path:
    """Download the SIMMAN zip, check both SHA-256 sums, write the IGES to dest. A cached file with the right sum is reused."""
    url, sha_zip, sha_igs = url or URL, sha_zip or SHA_ZIP, sha_igs or SHA_IGS
    if dest.exists() and hashlib.sha256(dest.read_bytes()).hexdigest() == sha_igs:
        return dest
    with opener(url) as r:
        blob = r.read()
    if hashlib.sha256(blob).hexdigest() != sha_zip:
        raise ValueError(f"{url}: zip sha256 differs from the recorded {sha_zip}")
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        igs = z.read(MEMBER)
    if hashlib.sha256(igs).hexdigest() != sha_igs:
        raise ValueError(f"{MEMBER}: sha256 differs from the recorded {sha_igs}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(igs)
    return dest


class Patch(NamedTuple):
    """Rational B-spline surface (IGES entity 128): control net C[v, u, 3], weights W[v, u], knot vectors, degrees."""
    deg: tuple[int, int]
    knots: tuple[np.ndarray, np.ndarray]
    W: np.ndarray
    C: np.ndarray
    span: tuple[float, float, float, float]


def read_iges(path: pathlib.Path) -> list[Patch]:
    """Parse the entity-128 surfaces of a fixed-format IGES file (D and P sections only)."""
    lines = path.read_text().splitlines()
    dsec = [ln for ln in lines if ln[72:73] == "D"]
    psec = [ln for ln in lines if ln[72:73] == "P"]
    out = []
    for a, b in zip(dsec[0::2], dsec[1::2], strict=True):
        if int(a[0:8]) != 128:
            continue
        start, count = int(a[8:16]), int(b[24:32])
        rec = "".join(ln[:64] for ln in psec[start - 1:start - 1 + count]).split(";")[0].split(",")
        v = [float(x) for x in rec[1:]]
        k1, k2, m1, m2 = (int(x) for x in v[:4])
        n1, n2, o = k1 + 1, k2 + 1, 9
        u = np.array(v[o:o + k1 + m1 + 2]); o += k1 + m1 + 2
        w = np.array(v[o:o + k2 + m2 + 2]); o += k2 + m2 + 2
        wt = np.array(v[o:o + n1 * n2]).reshape(n2, n1); o += n1 * n2
        c = np.array(v[o:o + 3 * n1 * n2]).reshape(n2, n1, 3); o += 3 * n1 * n2
        out.append(Patch((m1, m2), (u, w), wt, c, (v[o], v[o + 1], v[o + 2], v[o + 3])))
    if not out:
        raise ValueError(f"{path}: no rational B-spline surface (entity 128) found")
    return out


def eval_patch(p: Patch, nu: int, nv: int) -> np.ndarray:
    """Surface points on an (nu, nv) parameter grid -> (nu, nv, 3). u runs along the hull, v around the section."""
    (m1, m2), (ku, kv) = p.deg, p.knots
    n2, n1 = p.W.shape
    u = np.linspace(p.span[0], p.span[1], nu)
    v = np.linspace(p.span[2], p.span[3], nv)
    hom = np.concatenate([p.C * p.W[..., None], p.W[..., None]], -1)
    h = np.einsum("vj,ui,jik->uvk", BSpline(kv, np.eye(n2), m2)(v), BSpline(ku, np.eye(n1), m1)(u), hom)
    return cast(np.ndarray, h[..., :3] / h[..., 3:])


def _section(g: np.ndarray, x0: float) -> np.ndarray:
    """Points of the constant-x section of a (nu, nv, 3) grid, one per v-line that crosses x0, keel side first."""
    d = g[..., 0] - x0
    hit = d[:-1] * d[1:] <= 0
    ok = hit.any(0)
    j = np.nonzero(ok)[0]
    i = hit.argmax(0)[ok]
    a, b = d[i, j], d[i + 1, j]
    f = np.where(a != b, a / np.where(a != b, a - b, 1.0), 0.0)[:, None]
    return cast(np.ndarray, g[i, j] * (1 - f) + g[i + 1, j] * f)


def _resample(pts: np.ndarray, n: int, fallback: np.ndarray) -> np.ndarray:
    """n points equally spaced in arc length along a polyline; a section shorter than 2 points collapses to a point."""
    if len(pts) == 0:
        return np.tile(fallback, (n, 1))
    if len(pts) == 1:
        return np.tile(pts[0], (n, 1))
    s = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))]
    t = np.linspace(0.0, s[-1], n)
    return np.stack([np.interp(t, s, pts[:, k]) for k in range(3)], 1)


def build_hull(patches: list[Patch], n_stations: int = 400, n_girth: int = 100, res: tuple[int, int] = (600, 800)) -> trimesh.Trimesh:
    """Closed half-breadth loft of patch 0 (bow, to the stem profile) and patch 1 (body, to the transom edge), mirrored,
    deck closed by a strip between the sheer lines, transom closed by a flat fan. Output: bow towards +x, z up, keel at z = 0
    (the sonar dome reaches below it), metres. Needs the patch layout of the SIMMAN file: u along the hull, v from the
    centre-plane keel line to the sheer line, patch 0 ahead of patch 1 with an overlap."""
    if len(patches) < 2:
        raise ValueError("expected a bow patch and a body patch")
    g0, g1 = (eval_patch(p, *res) for p in patches[:2])
    stem = g0[-1, -1]                                    # stem head: forward-most point, on the sheer
    x_switch = 0.5 * (g0[0, 0, 0] + g1[0, 0, 0])         # overlap of the two patches: cut half way
    x_min, x_end = stem[0], g1[-1, :, 0].min()
    if not (x_min <= g0[..., 0].min() + 1e-9 and g1[0, 0, 0] < g0[0, 0, 0] < g1[-1, 0, 0]):
        raise ValueError("patch layout is not the SIMMAN bow/body arrangement")
    x_end -= 1e-3 * (x_end - x_min)
    t = np.linspace(0.0, 1.0, n_stations)[1:]
    xs = x_min + (x_end - x_min) * (1 - np.cos(np.pi * t)) / 2
    secs = [np.tile(stem, (n_girth, 1))]
    secs += [_resample(_section(g0 if x <= x_switch else g1, x), n_girth, stem) for x in xs]
    secs.append(_resample(g1[-1], n_girth, stem))        # transom edge curve
    s = np.array(secs)
    s[:, 0, 1] = 0.0                                     # keel / stem line lies exactly in the centre plane
    m, n = s.shape[:2]
    v = s.reshape(-1, 3)
    f = [(i * n + k, i * n + k + 1, (i + 1) * n + k + 1) for i in range(m - 1) for k in range(n - 1)]
    f += [(i * n + k, (i + 1) * n + k + 1, (i + 1) * n + k) for i in range(m - 1) for k in range(n - 1)]
    off = m * n
    faces = f + [(a + off, c + off, b + off) for a, b, c in f]                  # mirrored half, winding flipped
    for i in range(m - 1):                                                       # deck strip between the two sheer lines
        a, b = i * n + n - 1, (i + 1) * n + n - 1
        faces += [(a, b + off, b), (a, a + off, b + off)]
    last = [(m - 1) * n + k for k in range(n)]
    loop = last + [k + off for k in last[::-1]]
    both = np.vstack([v, v * [1, -1, 1]])
    vv_ = np.vstack([both, both[loop].mean(0)])
    faces += [(loop[i], loop[(i + 1) % len(loop)], 2 * off) for i in range(len(loop))]
    mesh = trimesh.Trimesh(vv_ * [-1, 1, 1], np.array(faces), process=False)    # file x runs aft: flip so the bow is +x
    mesh.merge_vertices(digits_vertex=6)
    mesh.update_faces(mesh.nondegenerate_faces())
    mesh.remove_unreferenced_vertices()
    if mesh.volume < 0:
        mesh.invert()
    if not (mesh.is_watertight and mesh.is_winding_consistent):
        raise ValueError("lofted hull is not a closed, consistently wound surface")
    return mesh


def hydrostatics(mesh: trimesh.Trimesh, draft: float = DRAFT) -> dict[str, float]:
    """Displacement (m3), wetted area (m2, waterplane excluded), Lwl and Bwl (m) at the draft, by the divergence theorem on
    the part of the closed mesh below z = draft: V = integral (z - draft) n_z dS, exact for flat triangles."""
    wet = trimesh.intersections.slice_mesh_plane(mesh, [0, 0, -1], [0, 0, draft], cap=False)  # type: ignore[no-untyped-call]  # trimesh ships no annotations for slice_mesh_plane
    vol = float(np.sum((wet.triangles_center[:, 2] - draft) * wet.face_normals[:, 2] * wet.area_faces))
    wl = mesh.section(plane_origin=[0, 0, draft], plane_normal=[0, 0, 1])
    if wl is None:
        raise ValueError(f"the plane z = {draft} does not cut the hull")
    pts = wl.vertices
    return dict(displacement=vol, wetted_area=float(wet.area_faces.sum()), lwl=float(np.ptp(pts[:, 0])), bwl=float(np.ptp(pts[:, 1])),
                draft=draft)


def froude_speeds(lpp: float = LPP, frs: tuple[float, ...] = tuple(CT_REF)) -> dict[float, float]:
    return {fr: fr * math.sqrt(G * lpp) for fr in frs}


def prepare(root: pathlib.Path, opener: Callable[[str], Any] = urllib.request.urlopen, **kw: Any) -> dict[str, float]:
    """Fetch the IGES, loft it, write hull.stl and hydro.json under root. -> hydrostatics."""
    root.mkdir(parents=True, exist_ok=True)
    mesh = build_hull(read_iges(fetch_igs(root / MEMBER, opener=opener)), **kw)
    mesh.export(root / "hull.stl")
    h = hydrostatics(mesh)
    (root / "hydro.json").write_text(json.dumps(h, indent=1))
    return h


# ------------------------------------------------------------------ the runs

@contextlib.contextmanager
def tank_water() -> Iterator[None]:
    """cafe.cfd writes sea water (1025 kg/m3, 1.19e-6) into transportProperties; the INSEAN tank is fresh."""
    old = dict(cfd.FLUIDS["water"])
    cfd.FLUIDS["water"].update(rho=TANK["rho"], nu=TANK["nu"])
    try:
        yield
    finally:
        cfd.FLUIDS["water"].clear()
        cfd.FLUIDS["water"].update(old)


# Three geometrically similar grids: the background mesh of cafe.cfd.free_surface (cell size, cells per z block) scaled by k about the
# medium grid, the refinement boxes and the snappy surface level unchanged. Counts go as k^2.4..2.8, not k^3 (boxes and prism layers do not
# scale), so the steps are asymmetric to give measured count ratios of 2.3 (r = 1.32) on both sides; the GCI takes r from the counts.
# The first pair (151 k / 331 k, r = 1.30) changed the hull cells and left the wall treatment out of range, which no GCI can separate.
GRIDS = {"coarse": 1 / 1.42, "medium": 1.0, "fine": 1.35}
GRID_ORDER = ("fine", "medium", "coarse")
SURF_LEVEL = 2          # snappy surface level at the hull, the same on every grid (a grid that has to step down is flagged in tabulate)
RECIPE = "pout-lts01-parts-v4"     # stamped on run_<grid>.json; a file made by another recipe is refused, never extended
ORDER = (0.20, 0.10, 0.28, 0.41)
ITERS = 2000          # what cafe.pm.stage3.freesurface prices per production window; this study uses MIN_ITERS..MAX_ITERS below
MIN_FREE_GB = 4.0      # do not start a case with less free disk than this ...
ABORT_FREE_GB = 3.0    # ... and stop a running one before the shared box gets below this
MAX_TREE_GB = 3.0      # keep the whole dtmb5415 tree under this

# Wall treatment. nutUSpaldingWallFunction is built for the log layer, y+ = 30..300. The first prism layer is sized per Froude number for
# y+ = 100 at the ITTC-57 friction velocity and is the same on all grids, so the wall-function error is the same on each and the GCI sees
# the discretisation. The stack grows by GROWTH to a total about the hull cell size: a stack several times thicker than the cell it is carved
# from does not extrude (10 layers of x1.3, 4x the cell, reached 6 % of their thickness; 3 layers of x2, 0.7x the cell, reach 60 %; 3 of
# 3.4 mm x2, 1.3x the cell, 33 %), so the total is kept at or under the cell.
Y_PLUS_AIM, Y_PLUS_BAND = 100.0, (30.0, 300.0)
GROWTH, MAX_LAYERS = 2.0, 8
# Iterative convergence, judged after every CHUNK pseudo-time steps once MIN_ITERS are done on the resistance history and on its pressure and
# viscous parts: the mean over the last quarter of the run may differ from the mean over the quarter before it by DRIFT_TOL (of the total, for
# each of the three), and the standard deviation of the total (the pseudo-time oscillation of the free surface) stays within SCATTER_TOL of its
# mean. Not met by MAX_ITERS: the case is recorded as unconverged. The parts are judged too because they drift against each other: the first
# study's fine grid at Fr 0.28 was accepted at 1000 iterations with the total flat to 1 % since iteration 250, while the pressure part had
# risen by 20 % and the viscous part fallen by 28 % in that time; the coarse and medium grids' parts went on moving for 5000 iterations.
MIN_ITERS, MAX_ITERS, CHUNK = 1000, 8000, 250
DRIFT_TOL, SCATTER_TOL = 0.005, 0.02
INFORMATIVE = 0.10     # U_val / D at most: a validation whose uncertainty is a large part of the answer claims nothing
P_SANE = (0.5, 2.5)    # observed GCI orders outside this are not believed; the two-grid Fs = 3, p = 2 estimate is used instead
YPLUS_FO = """    yPlus { type yPlus; libs (fieldFunctionObjects); patches (hull); executeControl writeTime; writeControl writeTime; }
    yPlusWet { type surfaceFieldValue; libs (fieldFunctionObjects); regionType patch; name hull; operation weightedAreaAverage;
               weightField alpha.water; fields (yPlus); executeControl writeTime; writeControl writeTime; writeFields no; log yes; }
"""


def check_disk(path: pathlib.Path, min_free_gb: float = MIN_FREE_GB) -> float:
    """Free disk (GB) under path; raises OSError below min_free_gb."""
    path.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(path).free / 1e9
    if free < min_free_gb:
        raise OSError(f"only {free:.1f} GB free under {path}; a DTMB 5415 case needs {min_free_gb} GB")
    return free


def tree_gb(path: pathlib.Path) -> float:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) / 1e9


def ct(resistance: float, speed: float, area: float, rho: float = TANK["rho"]) -> float:
    return resistance / (0.5 * rho * speed ** 2 * area)


def first_layer(u: float, y_plus: float = Y_PLUS_AIM, lpp: float = LPP, nu: float = TANK["nu"]) -> float:
    """First prism layer thickness (m) whose centre sits at y+ = y_plus when u_tau = U sqrt(Cf / 2), Cf = ITTC-57 at Re = U Lpp / nu."""
    return 2.0 * y_plus * nu / (u * math.sqrt(float(_cfd.ittc57(u * lpp / nu)) / 2.0))


def layer_count(first: float, cell: float, growth: float = GROWTH, most: int = MAX_LAYERS) -> int:
    """Layers `first`, `first` x growth, ... as many as keep their total thickness within the hull cell size `cell`, between 1 and `most`."""
    return int(min(most, max(1, math.log(1 + (growth - 1) * cell / first) / math.log(growth))))


def hull_cell(lwl: float, k: float, level: int = SURF_LEVEL) -> float:
    """Horizontal cell (m) at the hull: the background cell of the grid with factor k, halved once per refinement box and surface level."""
    return float(lwl * cfd.FS_H0 / k / 2 ** (len(cfd.FS_BOXES) + level))


def settle(series: np.ndarray) -> tuple[float, float, float, float]:
    """(mean, std, drift, scatter) over the last quarter of an iteration history: drift = |mean - mean of the quarter before| / |mean|,
    scatter = std / |mean|."""
    w = len(series) // 4
    last, prev = series[-w:], series[-2 * w:-w]
    mean = float(last.mean())
    return mean, float(last.std()), abs(mean - float(prev.mean())) / abs(mean), float(last.std()) / abs(mean)


def part_drift(series: np.ndarray, total: float) -> float:
    """|mean over the last quarter - mean over the quarter before| of one force component, as a fraction of the total force `total`."""
    w = len(series) // 4
    return abs(float(series[-w:].mean()) - float(series[-2 * w:-w].mean())) / abs(total)


def _set(text: str, key: str, value: object) -> str:
    out, n = re.subn(rf"^{key} .*;$", f"{key} {value};", text, flags=re.M)
    if n != 1:
        raise ValueError(f"expected one `{key}` entry, found {n}")
    return out


def _last_numbers(case: pathlib.Path, pattern: str) -> list[float]:
    """The numbers on the last data line of the newest postProcessing file matching pattern ([] if there is none)."""
    files = sorted(case.glob(f"postProcessing/{pattern}"), key=lambda f: float(f.parent.name))
    lines = [ln for ln in files[-1].read_text().splitlines() if ln.strip() and ln[0] != "#"] if files else []
    return [float(x) for x in lines[-1].replace("(", " ").replace(")", " ").split() if re.fullmatch(r"[-+.\deE]+|nan|inf", x)] if lines else []


def _layer_cover(case: pathlib.Path) -> Optional[float]:
    """Percent of the target layer thickness snappyHexMesh reached on the hull (last row of its patch table), None if there is none."""
    rows = re.findall(r"^hull\s+\d+\s+\d+\s+\S+\s+\S+\s+(\S+)\s*$", (case / "log.snappyHexMesh").read_text(errors="replace"), flags=re.M)
    return float(rows[-1]) if rows else None


def _converge(run: Callable[[Any, str, str], None], case: pathlib.Path, cmd: str, log: str, max_iters: int) -> dict[str, Any]:
    """interFoam in CHUNK-step restarts, with the yPlus function objects added, until the resistance history settles (judged by
    `settle`, never before MIN_ITERS) or max_iters. Disk is checked between pieces. -> what was seen."""
    ctl = case / "system/controlDict"
    base = ctl.read_text().replace("functions\n{", "functions\n{\n" + YPLUS_FO, 1)
    done = 0
    while True:
        done += CHUNK
        ctl.write_text(_set(_set(_set(base, "endTime", done), "writeInterval", CHUNK), "startFrom", "latestTime" if done > CHUNK else "startTime"))
        run(case, cmd, f"{log}.{done}")
        forces = case / "postProcessing/forces"
        for d in forces.glob("[0-9]*"):             # zero-padded names, so that cfd.read_forces' sorted() reads the pieces in time order
            d.rename(forces / f"{int(d.name):08d}")
        f = _cfd.read_forces(case)["force"]
        mean, std, drift, scatter = settle(-f["total"][:, 0])
        parts = max(part_drift(-f[k][:, 0], mean) for k in ("pressure", "viscous"))
        ok = done >= MIN_ITERS and max(drift, parts) <= DRIFT_TOL and scatter <= SCATTER_TOL
        if ok or done >= max_iters:
            break
        check_disk(case, ABORT_FREE_GB)
    wet, rng = _last_numbers(case, "yPlusWet/*/surfaceFieldValue.dat"), _last_numbers(case, "yPlus/*/yPlus.dat")
    return dict(mean=mean, std=std, drift=drift, scatter=scatter, drift_parts=parts, converged=bool(ok), iters=int(f["it"][-1]),
                viscous=-float(f["viscous"][-(len(f["it"]) // 4):, 0].mean()),
                y_plus=wet[-1] if wet else None, y_plus_min=rng[1] if len(rng) > 3 else None, y_plus_max=rng[2] if len(rng) > 3 else None)


@contextlib.contextmanager
def case_recipe(first: float, layers: int, k: float, max_iters: int = MAX_ITERS) -> Iterator[dict[str, Any]]:
    """What this study does to cafe.cfd.free_surface without editing it, for one case: tank water; the background mesh scaled by k;
    `layers` hull prism layers (x GROWTH from `first` metres) in place of the dictionary the module wrote, set just before snappyHexMesh
    runs; interFoam run by `_converge`. The yielded dict is filled with what was seen (convergence, y+, layer coverage)."""
    seen: dict[str, Any] = {}
    real, old = _cfd.sh, (_cfd.FS_H0, _cfd.FS_NZ)

    def sh(case: Any, cmd: str, log: str) -> None:
        case = pathlib.Path(case)
        if log == "interFoam" or log.startswith("interFoam."):
            seen.update(_converge(real, case, cmd, log, max_iters))
            return
        if log == "snappyHexMesh":
            f = case / "system/snappyHexMeshDict"
            block = (f"addLayersControls\n{{\n    relativeSizes false;\n    layers {{ hull {{ nSurfaceLayers {layers}; }} }}\n"
                     f"    expansionRatio {GROWTH}; firstLayerThickness {first:.6g}; minThickness {0.25 * first:.6g}; nGrow 0; featureAngle 60;\n"
                     "    nRelaxIter 5; nSmoothSurfaceNormals 1; nSmoothNormals 3; nSmoothThickness 10;\n"
                     "    maxFaceThicknessRatio 0.5; maxThicknessToMedialRatio 0.3; minMedialAxisAngle 90;\n"
                     "    nBufferCellsNoExtrude 0; nLayerIter 50; nRelaxedIter 20;\n}\n")
            text, n = re.subn(r"addLayersControls\n\{.*?\n\}\n", lambda _: block, f.read_text(), count=1, flags=re.S)
            if n != 1:
                raise ValueError(f"{f}: no addLayersControls block to replace")
            f.write_text(text)
        real(case, cmd, log)
        if log == "snappyHexMesh":
            seen["layer_cover"] = _layer_cover(case)
    _cfd.sh = sh
    _cfd.FS_H0, _cfd.FS_NZ = old[0] * (1 - 1e-9) / k, tuple(max(2, round(n * k)) for n in old[1])
    try:
        with tank_water():
            yield seen
    finally:
        _cfd.sh, (_cfd.FS_H0, _cfd.FS_NZ) = real, old


def _rmtree_heavy(case: pathlib.Path) -> None:
    cfd._shrink(case)


def _case(solver: Callable[..., dict[str, Any]], root: pathlib.Path, grid: str, h: dict[str, float], fr: float, max_iters: int,
          log: Callable[[str], None], level: int) -> dict[str, Any]:
    """One speed on one grid, all the way to a record: prism layers sized for y+ = 100, mesh + interFoam until converged, stepping the
    snappy surface level down from `level` when snappy cannot refine the pre-refined cells (as cafe.cfd.characterize_free_surface does). Heavy case
    files are removed afterwards, even on failure; logs and postProcessing stay."""
    u = froude_speeds()[fr]
    first = first_layer(u)
    with contextlib.ExitStack() as cleanup:
        cleanup.callback(_rmtree_heavy, root / grid)
        while True:
            n = layer_count(first, hull_cell(h["lwl"], GRIDS[grid], level))
            log(f"{grid} Fr {fr:.2f}: U {u:.3f} m/s, {n} layers from {first * 1e3:.2f} mm, surface level {level}")
            try:
                with case_recipe(first, n, GRIDS[grid], max_iters) as seen:
                    r = solver(str(root / "hull.stl"), h["draft"], root / grid, [u], 0, iters=max_iters, log=log, surf_level=level)
                break
            except RuntimeError as e:
                snap = root / grid / "log.snappyHexMesh"
                if level == 0 or not (snap.exists() and "more than 8 points" in snap.read_text(errors="replace")):
                    raise e
                level -= 1
                log(f"snappy cannot refine the pre-refined cells at the hull; retrying at surface level {level}")
    s, area, k2 = r["speeds"][u], h["wetted_area"], 2.0 if r["half"] else 1.0
    force, std = (k2 * seen["mean"], k2 * seen["std"]) if "mean" in seen else (s["resistance"], s["resistance_std"])
    return dict(U=u, R=force, R_std=std, ct=ct(force, u, area), ct_std=ct(std, u, area), iters=s["iters"], seconds=s["seconds"],
                cells=r["mesh"]["cells"], failed_checks=r["mesh"]["failed_checks"], surf_level=level, first_layer=first, layers=n,
                ct_viscous=ct(k2 * seen["viscous"], u, area) if "viscous" in seen else None,
                layer_cover=seen.get("layer_cover"), y_plus=seen.get("y_plus"), y_plus_min=seen.get("y_plus_min"),
                y_plus_max=seen.get("y_plus_max"), drift=seen.get("drift"), drift_parts=seen.get("drift_parts"), scatter=seen.get("scatter"),
                converged=seen.get("converged"))


def run_grid(root: pathlib.Path, grid: str, max_iters: int = MAX_ITERS, log: Callable[[str], None] = print,
             solver: Callable[..., dict[str, Any]] = cfd.free_surface, frs: tuple[float, ...] = ORDER) -> dict[str, Any]:
    """interFoam LTS at the Froude numbers `frs` on one grid (GRIDS), one meshing + solve per speed so each finished speed is on disk
    (run_<grid>.json) and a restart does not repeat it. Disk is checked before every case. A file stamped with another RECIPE is refused."""
    h = json.loads((root / "hydro.json").read_text())
    f = root / f"run_{grid}.json"
    out = json.loads(f.read_text()) if f.exists() else dict(grid=grid, recipe=RECIPE, S=h["wetted_area"], surf_level=SURF_LEVEL, speeds={})
    if out.get("recipe") != RECIPE:
        raise ValueError(f"{f} was made by recipe {out.get('recipe')!r}, not {RECIPE!r}; move it aside rather than mix the two")
    for fr in frs:
        key = f"{fr:.2f}"
        if key in out["speeds"]:
            continue
        check_disk(root)
        c = out["speeds"][key] = _case(solver, root, grid, h, fr, max_iters, log, out["surf_level"])
        out["surf_level"] = c["surf_level"]              # a level snappy could not do stays down for the later speeds of this grid
        f.write_text(json.dumps(out, indent=1))
        log(f"{grid} Fr {key}: C_T {c['ct']:.5g} (reference {CT_REF[fr]:.5g}), {c['cells']} cells, y+ {c['y_plus']}, "
            f"{c['iters']} iterations, converged {c['converged']}, viscous C_T {c['ct_viscous']}")
    out["tree_gb"] = tree_gb(root)
    if out["tree_gb"] > MAX_TREE_GB:
        log(f"warning: {root} is {out['tree_gb']:.1f} GB, over the {MAX_TREE_GB} GB budget")
    return out


# ------------------------------------------------------------------ V&V 20 tabulation and receipts

def discretization(values: Sequence[float], cells: Sequence[float], levels: Sequence[Any] = ()) -> tuple[float, float, str]:
    """Relative U_num of values[0] from two or three grids, finest first, and how it was got. -> (u_rel, r fine/next, note).
    Three grids that converge monotonically at r >= 1.3 with an observed order inside P_SANE: Celik 2008 GCI_fine with Fs = 1.25.
    Anything else (two grids, divergence, oscillation, an unbelievable p, grids that differ in snappy surface level) falls back to
    Roache's Fs = 3 with the order assumed to be 2 on the finest pair, and never less than half the spread of the values; the note says why."""
    r21 = vv.refinement_ratio(cells[0], cells[1])
    why = "two grids" if len(values) == 2 else "grids differ in snappy surface level" if len(set(levels)) > 1 else ""
    if not why:
        try:
            g = vv.celik_gci(values[0], values[1], values[2], r21, vv.refinement_ratio(cells[1], cells[2]))
        except (ValueError, RuntimeError):
            why = "observed order undefined"
        else:
            why = ("oscillating" if g.oscillatory else "diverging" if not g.converging else f"r < {vv.R_MIN}" if not g.r_ok
                   else f"p = {g.p:.2f} outside {P_SANE}" if not P_SANE[0] <= g.p <= P_SANE[1] else "")
            if not why:
                return g.gci_fine21, r21, f"p = {g.p:.2f}, Fs = {vv.FS_THREE_GRID}"
    return max(vv.gci_two_grid(values[0], values[1], r21), (max(values) - min(values)) / 2 / abs(values[0])), r21, f"Fs = 3, p = 2 assumed: {why}"


def tabulate(root: pathlib.Path) -> dict[float, vv.Vv20]:
    """One V&V 20 row per Froude number (keyed by it) that has at least two grids run. S = C_T on the finest grid; U_num = `discretization`
    of that speed's grids times S, in quadrature with the finest grid's iteration scatter (std of C_T over the last quarter of the run);
    U_input = S and viscosity assumptions; U_D assumed."""
    runs = {g: json.loads(f.read_text()) for g in GRID_ORDER if (f := root / f"run_{g}.json").exists()}
    rows = {}
    for fr, ref in CT_REF.items():
        key = f"{fr:.2f}"
        got = [runs[g]["speeds"][key] for g in GRID_ORDER if g in runs and key in runs[g]["speeds"]]
        if len(got) < 2:
            continue
        s = got[0]["ct"]
        u_rel, r, note = discretization([c["ct"] for c in got], [c["cells"] for c in got], [c.get("surf_level") for c in got])
        u_num = math.hypot(u_rel * s, got[0].get("ct_std", 0.0))
        rows[fr] = vv.vv20_row(f"C_T Fr {key} (r={r:.2f}, {note})", s, ref, u_num, s * math.hypot(assumed("u_S_rel"), assumed("u_nu_rel")),
                               assumed("u_D_rel") * ref)
    return rows


def receipts(root: Optional[pathlib.Path] = None) -> str:
    """Hull-geometry receipts when hydro.json exists; per-Froude C_T rows when two grids have run; per-case wall and convergence rows
    for every case on disk (a case that recorded none of it fails them: a required check that did not happen is not fine). -> a status line."""
    root = root or data_root()
    if not (root / "hydro.json").exists():
        return f"DTMB 5415: no {root}/hydro.json (run `python -m cafe.pm.dtmb5415 prepare`); no receipts emitted"
    h = json.loads((root / "hydro.json").read_text())
    grp = "DTMB 5415"
    rc.receipt(grp, "Lofted hull displacement at T = 0.248 m", h["displacement"], DISPLACEMENT, 0.01, "m3", SIMMAN)
    rc.receipt(grp, "Lofted hull Lwl at T = 0.248 m", h["lwl"], LWL, 0.005, "m", SIMMAN)
    rc.receipt(grp, "Lofted hull Bwl at T = 0.248 m", h["bwl"], BWL, 0.01, "m", SIMMAN)
    rows = tabulate(root)
    for fr, row in rows.items():
        src = "INSEAN 2340, Olivieri et al. 2001 via docs/BRIEF.md 5.2; U_D, U_input assumed (see cafe.pm.dtmb5415.ASSUMED)"
        rc.context(grp, f"C_T x1e3 at Fr {fr:.2f}: E = {row.E * 1e3:+.3f}, U_val = {row.u_val * 1e3:.3f}, U_num = {row.u_num * 1e3:.3f}",
                   row.S * 1e3, row.D * 1e3, "", src)
        rc.bracket(grp, f"C_T Fr {fr:.2f}: |E| <= U_val (ASME V&V 20)", abs(row.E), 0.0, row.u_val, "", src)
        rc.bracket(grp, f"C_T Fr {fr:.2f}: U_val / D <= {INFORMATIVE} (the validation says something)", row.u_val / row.D, 0.0, INFORMATIVE, "",
                   "a pass with U_val comparable to the quantity claims nothing; U_num must come down with grid and iteration quality")
    n = 0
    for g in GRID_ORDER:
        if (root / f"run_{g}.json").exists():
            for key, c in json.loads((root / f"run_{g}.json").read_text())["speeds"].items():
                v = {k: math.nan if c.get(k) is None else float(c[k]) for k in ("y_plus", "drift", "drift_parts", "scatter")}
                rc.bracket(grp, f"{g} Fr {key}: wetted-area mean y+ in the log layer", v["y_plus"], *Y_PLUS_BAND, "",
                           "Spalding wall function; first prism layer sized per Froude number (first_layer)")
                rc.bracket(grp, f"{g} Fr {key}: iterative convergence, last-quarter drift", v["drift"], 0.0, DRIFT_TOL, "", "resistance history, settle()")
                rc.bracket(grp, f"{g} Fr {key}: iterative convergence, last-quarter drift of the pressure and viscous parts", v["drift_parts"], 0.0,
                           DRIFT_TOL, "", "pressure and viscous histories, part_drift()")
                rc.bracket(grp, f"{g} Fr {key}: iterative convergence, last-quarter scatter", v["scatter"], 0.0, SCATTER_TOL, "",
                           "resistance history, settle()")
                n += 1
    return f"DTMB 5415: geometry receipts + {len(rows)} Froude rows + {n} cases checked for y+ and convergence"


def main(argv: list[str]) -> int:
    root = data_root()
    cmd = argv[0] if argv else "report"
    if cmd == "prepare":
        print(json.dumps(prepare(root), indent=1))
    elif cmd == "run":
        frs = tuple(float(x) for x in argv[3].split(",")) if len(argv) > 3 else ORDER
        print(json.dumps(run_grid(root, argv[1], int(argv[2]) if len(argv) > 2 else MAX_ITERS, frs=frs), indent=1))
    elif cmd == "report":
        print(vv.format_table(list(tabulate(root).values())))
        print(receipts(root))
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
