"""Verification and validation arithmetic: grid convergence and the ASME V&V 20 comparison table.

Celik, Ghia, Roache, Freitas, Coleman & Raad (2008), "Procedure for Estimation and Reporting of Uncertainty Due to
Discretization in CFD Applications", J. Fluids Eng. 130(7):078001, steps 1-6 (eqs 1-7), implemented as written:
h = (sum V_i / N)^(1/3); refinement ratio r = h_coarse / h_fine >= 1.3; apparent order p by fixed-point iteration of
eq 3 (q(p) = 0 when r21 = r32); Richardson extrapolation eq 4; e_a, e_ext eqs 5-6; GCI_fine = 1.25 e_a / (r^p - 1).
Negative eps32/eps21 means oscillatory convergence. Check: the paper's Table 1 (tests/test_vv.py reproduces all
three columns).

Two grids only: Roache (1998), "Verification and Validation in Computational Science and Engineering": GCI =
Fs |e| / (r^p - 1) with Fs = 3 and an assumed order p. `cafe.cfd.gci` is that formula; `gci_two_grid` is the same
formula and the tests hold them equal.

ASME V&V 20-2009 (reaffirmed 2016), sec 4: comparison error E = S - D; validation uncertainty
U_val = sqrt(U_num^2 + U_input^2 + U_D^2). The model error delta_model lies in E +/- U_val; |E| <= U_val means the
model is validated at that level, |E| > U_val means E is mostly model-form error. Validation is reported, not
pass/fail, except where a caller chooses to gate on it.
"""
import math
from typing import NamedTuple, Sequence

R_MIN = 1.3          # Celik 2008 step 2: "desirable that r be greater than 1.3" (experience, not derivation)
FS_THREE_GRID = 1.25  # Celik 2008 eq 7
FS_TWO_GRID = 3.0     # Roache 1998 for two grids with an assumed order


class GCI(NamedTuple):
    """Celik 2008 step 5 outputs for the fine / medium / coarse triple (subscripts follow the paper)."""
    p: float             # apparent order, eq 3
    phi_ext21: float     # eq 4
    phi_ext32: float
    ea21: float          # approximate relative error, eq 5
    eext21: float        # extrapolated relative error, eq 6
    gci_fine21: float    # eq 7 (relative)
    gci_coarse32: float
    asymptotic: float    # GCI32 / (r21^p GCI21): = phi1/phi2 (~ 1) for an exact power law, so ~ 1 in the asymptotic range (Celik step 6)
    oscillatory: bool    # eps32 / eps21 < 0
    r_ok: bool           # both refinement ratios >= 1.3
    converging: bool     # eq 3 without |.| has a positive root; False means the solution diverges under refinement


def grid_size(cell_volumes: Sequence[float], dim: int = 3) -> float:
    """Eq 1/2: representative cell size h = (mean cell volume)^(1/dim) (area, dim = 2, for 2-D meshes)."""
    if not cell_volumes or min(cell_volumes) <= 0:
        raise ValueError("cell volumes must be positive")
    return float((sum(cell_volumes) / len(cell_volumes)) ** (1.0 / dim))


def refinement_ratio(n_fine: float, n_coarse: float, dim: int = 3) -> float:
    """r = h_coarse / h_fine from cell counts of geometrically similar meshes: (N_fine / N_coarse)^(1/dim).
    Anisotropic refinement (e.g. horizontal-only) gives an effective r from counts that is a lower bound on the
    largest per-direction ratio; Celik's h is defined this way, so this is the right number for the GCI."""
    if n_fine <= 0 or n_coarse <= 0:
        raise ValueError("cell counts must be positive")
    return float((n_fine / n_coarse) ** (1.0 / dim))


def _fixed_point(base: float, s: float, r21: float, r32: float, tol: float, max_iter: int) -> float:
    """p = (base + ln((r21^p - s) / (r32^p - s))) / ln r21, started at the first term, as in eq 3."""
    p = base / math.log(r21)
    if r21 == r32:
        return p
    for _ in range(max_iter):
        try:
            a, b = r21 ** p - s, r32 ** p - s
            if a / b <= 0:
                raise RuntimeError("eq 3b has no real q(p) at this p (the order is not defined for these ratios)")
            new = (base + math.log(a / b)) / math.log(r21)
        except (OverflowError, ZeroDivisionError):
            raise RuntimeError("fixed-point iteration for the apparent order did not converge") from None
        if abs(new - p) < tol:
            return new
        p = new
    raise RuntimeError("fixed-point iteration for the apparent order did not converge")


def _scan(base: float, s: float, r21: float, r32: float, tol: float) -> float:
    """Smallest positive root of eq 3 found by bracketing on a log grid (scipy brentq); RuntimeError if there is none."""
    from scipy.optimize import brentq

    def f(p: float) -> float:
        try:
            return p * math.log(r21) - base - math.log((r21 ** p - s) / (r32 ** p - s))
        except (ValueError, OverflowError, ZeroDivisionError):
            return math.nan
    grid = [10 ** (k / 20) for k in range(-80, 41)]
    vals = [f(p) for p in grid]
    for lo, hi, flo, fhi in zip(grid, grid[1:], vals, vals[1:], strict=False):
        if flo * fhi < 0:
            return float(brentq(f, lo, hi, xtol=tol))
    raise RuntimeError("fixed-point iteration for the apparent order did not converge")


def _signed_order(eps21: float, eps32: float, r21: float, r32: float, tol: float = 1e-12, max_iter: int = 500) -> float:
    """Root of eq 3 without the absolute value: fixed-point iteration from the first term, bracketing if that cycles or
    lands at p <= 0. NaN when there is no positive root, i.e. the solution diverges under refinement."""
    ratio = eps32 / eps21
    base, s = math.log(abs(ratio)), math.copysign(1.0, ratio)
    try:
        p = _fixed_point(base, s, r21, r32, tol, max_iter)
        if p > 1e-9:
            return p
    except RuntimeError:
        pass
    try:
        return _scan(base, s, r21, r32, tol)
    except RuntimeError:
        return math.nan


def observed_order(eps21: float, eps32: float, r21: float, r32: float, tol: float = 1e-12, max_iter: int = 500) -> float:
    """Apparent order p from eq 3 (eps21 = phi2 - phi1, eps32 = phi3 - phi2). When the solution converges this is the
    positive root of eq 3 itself. The paper puts an absolute value around the logarithm so that p > 0 always; where eq 3
    has no positive root (|eps32| < |eps21| with r32 >= r21: diverging) that absolute-value p is returned and
    `celik_gci` sets converging = False. Raises ValueError when either difference is zero or non-finite (Celik: the
    procedure does not work; run another grid) and RuntimeError when not even the absolute-value form has a root."""
    if not (math.isfinite(eps21) and math.isfinite(eps32)) or eps21 == 0 or eps32 == 0:
        raise ValueError("eps21 and eps32 must be finite and non-zero")
    p = _signed_order(eps21, eps32, r21, r32, tol, max_iter)
    if p > 1e-9:
        return p
    ratio = eps32 / eps21
    base, s = abs(math.log(abs(ratio))), math.copysign(1.0, ratio)
    try:
        return _fixed_point(base, s, r21, r32, tol, max_iter)
    except RuntimeError:
        return _scan(base, s, r21, r32, tol)


def celik_gci(phi1: float, phi2: float, phi3: float, r21: float, r32: float) -> GCI:
    """Celik 2008 steps 3-6 for solutions on the fine (1), medium (2) and coarse (3) grids. `converging` is False when
    eq 3 without its absolute value has no positive root (the solution moves more between the fine pair than between
    the coarse pair): the paper's |.| would still return a p there; the extrapolation and GCI are then NaN."""
    if phi1 == 0 or phi2 == 0:
        raise ValueError("relative errors (eqs 5-7) are undefined for a zero solution on the fine or medium grid")
    eps21, eps32 = phi2 - phi1, phi3 - phi2
    p = observed_order(eps21, eps32, r21, r32)
    converging = _signed_order(eps21, eps32, r21, r32) > 1e-9
    ext21 = (r21 ** p * phi1 - phi2) / (r21 ** p - 1) if converging else math.nan
    ext32 = (r32 ** p * phi2 - phi3) / (r32 ** p - 1) if converging else math.nan
    ea21 = abs((phi1 - phi2) / phi1)
    ea32 = abs((phi2 - phi3) / phi2)
    eext21 = abs((ext21 - phi1) / ext21) if converging and ext21 != 0 else math.nan
    gci21 = FS_THREE_GRID * ea21 / (r21 ** p - 1) if converging else math.nan
    gci32 = FS_THREE_GRID * ea32 / (r32 ** p - 1) if converging else math.nan
    return GCI(p, ext21, ext32, ea21, eext21, gci21, gci32, gci32 / (r21 ** p * gci21) if converging else math.nan,
               eps32 / eps21 < 0, r21 >= R_MIN and r32 >= R_MIN, converging)


def gci_two_grid(fine: float, coarse: float, ratio: float = 2.0, p: float = 2.0, fs: float = FS_TWO_GRID) -> float:
    """Relative uncertainty of the fine-grid value from two grids and an assumed order (Roache). Same as cafe.cfd.gci."""
    return float(fs * abs((coarse - fine) / fine) / (ratio ** p - 1))


class Vv20(NamedTuple):
    """One row of the V&V 20 table, all in the units of the compared quantity."""
    case: str
    S: float            # simulation value
    D: float            # experimental value
    E: float            # S - D
    u_num: float
    u_input: float
    u_D: float
    u_val: float
    ratio: float        # |E| / U_val
    validated: bool     # |E| <= U_val


def vv20_row(case: str, S: float, D: float, u_num: float, u_input: float, u_D: float) -> Vv20:
    """E = S - D; U_val = sqrt(U_num^2 + U_input^2 + U_D^2) (ASME V&V 20-2009 sec 2, independent terms)."""
    if min(u_num, u_input, u_D) < 0:
        raise ValueError("uncertainties are magnitudes and cannot be negative")
    E = S - D
    u_val = math.sqrt(u_num ** 2 + u_input ** 2 + u_D ** 2)
    ratio = abs(E) / u_val if u_val > 0 else (0.0 if E == 0 else math.inf)
    return Vv20(case, S, D, E, u_num, u_input, u_D, u_val, ratio, ratio <= 1.0)


def format_table(rows: Sequence[Vv20], fmt: str = "{:.4g}") -> str:
    """Plain-text V&V 20 table for logs and the credibility report."""
    head = ["case", "S", "D", "E=S-D", "U_num", "U_input", "U_D", "U_val", "|E|/U_val", "|E|<=U_val"]
    body = [[r.case, *(fmt.format(x) for x in (r.S, r.D, r.E, r.u_num, r.u_input, r.u_D, r.u_val, r.ratio)),
             "yes" if r.validated else "no"] for r in rows]
    w = [max(len(row[i]) for row in [head, *body]) for i in range(len(head))]
    return "\n".join("  ".join(c.rjust(w[i]) for i, c in enumerate(row)) for row in [head, *body])
