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

Usage on homebase (see docs/BUILDERS.md):  ./pm.sh python -m cafe.pm.dtmb5415 prepare | run coarse [iters [fr,fr]] | run fine | report
"""
import contextlib
import hashlib
import io
import json
import math
import os
import pathlib
import shutil
import sys
import urllib.request
import zipfile
from typing import Any, Callable, Iterator, NamedTuple, Optional, cast

import numpy as np
import trimesh
from scipy.interpolate import BSpline

from cafe import cfd
from cafe import receipts as rc
from cafe.pm import vv

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


# (level_offset, snappy surface level) of the two grids. cafe.cfd.characterize_free_surface varies only the horizontal refinement
# boxes (151 k -> 234 k cells, r = 1.16 < Celik's 1.3); adding one hull surface level to the fine grid gives 331 k cells, r = 1.30.
GRIDS = {"coarse": (-1, 1), "fine": (0, 2)}
ORDER = (0.28, 0.41, 0.20, 0.10)   # most informative first; run_grid skips what run_<grid>.json already holds
ITERS = 2000          # LTS pseudo-time steps per speed: ~2.6 s each on the 330 k-cell fine grid at 6 ranks on a loaded box
MIN_FREE_GB = 6.0      # lead's rule for the shared box: do not start a case with less free disk than this
MAX_TREE_GB = 3.0      # and keep the whole dtmb5415 tree under this


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


def _case(solver: Callable[..., dict[str, Any]], root: pathlib.Path, grid: str, draft: float, u: float, off: int, top: int, iters: int,
          log: Callable[[str], None]) -> tuple[dict[str, Any], int]:
    """One speed on one grid: mesh + interFoam, stepping the snappy surface level down when snappy cannot refine the
    pre-refined cells (as cafe.cfd.characterize_free_surface does). Heavy case files are removed afterwards, even on failure."""
    with tank_water(), contextlib.ExitStack() as cleanup:
        cleanup.callback(_rmtree_heavy, root / grid)
        sl = top
        while True:
            try:
                return solver(str(root / "hull.stl"), draft, root / grid, [u], off, iters=iters, log=log, surf_level=sl), sl
            except RuntimeError as e:
                snap = root / grid / "log.snappyHexMesh"
                if sl == 0 or not (snap.exists() and "more than 8 points" in snap.read_text(errors="replace")):
                    raise e
                sl -= 1
                log(f"snappy cannot refine the pre-refined cells at the hull; retrying at surface level {sl}")


def run_grid(root: pathlib.Path, grid: str, iters: int = ITERS, log: Callable[[str], None] = print,
             solver: Callable[..., dict[str, Any]] = cfd.free_surface, frs: tuple[float, ...] = ORDER) -> dict[str, Any]:
    """interFoam LTS at the Froude numbers `frs` (default all four) on one grid (GRIDS), one meshing + solve per speed so each finished speed
    is on disk (run_<grid>.json) and a restart skips it. Disk is checked before every case."""
    off, top = GRIDS[grid]
    h = json.loads((root / "hydro.json").read_text())
    f = root / f"run_{grid}.json"
    out = json.loads(f.read_text()) if f.exists() else dict(grid=grid, iters=iters, surf_level=top, S=h["wetted_area"], speeds={})
    for fr in frs:
        key = f"{fr:.2f}"
        if key in out["speeds"]:
            continue
        check_disk(root)
        u = froude_speeds()[fr]
        r, out["surf_level"] = _case(solver, root, grid, h["draft"], u, off, out["surf_level"], iters, log)
        s = r["speeds"][u]
        out["speeds"][key] = dict(U=u, R=s["resistance"], R_std=s["resistance_std"], ct=ct(s["resistance"], u, h["wetted_area"]),
                                  ct_std=ct(s["resistance_std"], u, h["wetted_area"]), iters=s["iters"], seconds=s["seconds"],
                                  cells=r["mesh"]["cells"], failed_checks=r["mesh"]["failed_checks"])
        f.write_text(json.dumps(out, indent=1))
        log(f"{grid} Fr {key}: C_T {out['speeds'][key]['ct']:.5g} (reference {CT_REF[fr]:.5g}), {r['mesh']['cells']} cells")
    out["tree_gb"] = tree_gb(root)
    if out["tree_gb"] > MAX_TREE_GB:
        log(f"warning: {root} is {out['tree_gb']:.1f} GB, over the {MAX_TREE_GB} GB budget")
    return out


def _rmtree_heavy(case: pathlib.Path) -> None:
    cfd._shrink(case)


# ------------------------------------------------------------------ V&V 20 tabulation and receipts

def tabulate(root: pathlib.Path) -> dict[float, vv.Vv20]:
    """One V&V 20 row per Froude number (keyed by it) that has both grids run. S = C_T on the fine grid; U_num = two-grid GCI
    (Roache Fs = 3, assumed p = 2, r from the cell counts of that speed's two meshes) times S, in quadrature
    with the fine-grid iteration scatter (std of C_T over the last 20 % of iterations); U_input = S and viscosity assumptions; U_D assumed."""
    runs = {g: json.loads((root / f"run_{g}.json").read_text()) for g in ("coarse", "fine") if (root / f"run_{g}.json").exists()}
    if len(runs) < 2:
        return {}
    rows = {}
    for fr, ref in CT_REF.items():
        key = f"{fr:.2f}"
        if key not in runs["fine"]["speeds"] or key not in runs["coarse"]["speeds"]:
            continue
        r = vv.refinement_ratio(runs["fine"]["speeds"][key]["cells"], runs["coarse"]["speeds"][key]["cells"])
        s_f, s_c = runs["fine"]["speeds"][key]["ct"], runs["coarse"]["speeds"][key]["ct"]
        u_num = math.hypot(vv.gci_two_grid(s_f, s_c, r) * s_f, runs["fine"]["speeds"][key].get("ct_std", 0.0))
        u_in = s_f * math.hypot(assumed("u_S_rel"), assumed("u_nu_rel"))
        rows[fr] = (vv.vv20_row(f"C_T Fr {key} (r={r:.2f})", s_f, ref, u_num, u_in, assumed("u_D_rel") * ref))
    return rows


def receipts(root: Optional[pathlib.Path] = None) -> str:
    """Hull-geometry receipts when hydro.json exists; per-Froude C_T rows when both grids have run. -> a status line."""
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
    return f"DTMB 5415: geometry receipts + {len(rows)} Froude rows"


def main(argv: list[str]) -> int:
    root = data_root()
    cmd = argv[0] if argv else "report"
    if cmd == "prepare":
        print(json.dumps(prepare(root), indent=1))
    elif cmd == "run":
        frs = tuple(float(x) for x in argv[3].split(",")) if len(argv) > 3 else ORDER
        print(json.dumps(run_grid(root, argv[1], int(argv[2]) if len(argv) > 2 else ITERS, frs=frs), indent=1))
    elif cmd == "report":
        print(vv.format_table(list(tabulate(root).values())))
        print(receipts(root))
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
