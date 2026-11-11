"""Reference integrators for Euler's equations of a torque-free rigid body, used to grade cafe.dyn.

Body-frame angular velocity w obeys I dw/dt = (I w) x w. Two exact invariants: the angular-momentum magnitude |I w|
and the kinetic energy 0.5 w.I w. Explicit Euler changes both: |H|^2 grows by dt^2 |w x H|^2 every step (H_{n+1} =
H_n - dt w_n x H_n, and w x H is orthogonal to H). The implicit midpoint rule conserves every quadratic invariant
(Cooper 1987; Hairer, Lubich & Wanner 2006, Geometric Numerical Integration, sec IV.2), so it is the energy-keeping
reference the explicit scheme is compared with.
"""
import numpy as np


def omega_dot(inertia: np.ndarray, w: np.ndarray) -> np.ndarray:
    """dw/dt of the torque-free body: I^-1 ((I w) x w)."""
    return np.linalg.solve(inertia, np.cross(inertia @ w, w))


def explicit_euler(inertia: np.ndarray, w: np.ndarray, dt: float) -> np.ndarray:
    """w + dt dw/dt(w): what cafe.dyn does to the body rates (velocities first, with the old velocities)."""
    return w + dt * omega_dot(inertia, w)


def _skew(a: np.ndarray) -> np.ndarray:
    """The matrix of a x (.)."""
    return np.array([[0.0, -a[2], a[1]], [a[2], 0.0, -a[0]], [-a[1], a[0], 0.0]])


def implicit_midpoint(inertia: np.ndarray, w: np.ndarray, dt: float, tol: float = 1e-14, max_iter: int = 50) -> np.ndarray:
    """Solve w1 = w + dt dw/dt((w + w1)/2) by Newton's method from the explicit Euler step, with the analytic Jacobian
    d(dw/dt)/dw = I^-1 ([I w]x - [w]x I). RuntimeError when it does not converge. It stops when the Newton step is below `tol` times max(1, |w1|_max): a
    step cannot be smaller than the rounding of w1 itself (about 1e-16 |w1|), so an absolute 1e-14 never settled for |w| above about 100 (round 15, M-33).
    Not a fixed-point iteration: that one contracts only when about dt/2 ||d(dw/dt)/dw|| < 1, a bound that carries the inertia ratios and so is no
    "dt |w| < 1" (4000 random diagonal inertias, ratios up to 1e3, dt |w| = 0.3: 1817 of them failed it; round 15, M-33). Newton converged for all of 1000
    random diagonal inertias at dt |w| = 0.3 for each ratio 1, 10, 50 and 1000 (residual below 2e-14); at dt |w| = 1 it failed for 2 of 1000 at ratio 50 and
    22 at ratio 1000, and at dt |w| = 3 for 14, 28 and 105 at ratios 10, 50 and 1000. Past about dt |w| = 1 with a very uneven inertia the midpoint equation can
    have no root near the Euler step, and this raises; a long step with an even inertia (diag(2, 3, 5), dt = 50) converges."""
    w1 = explicit_euler(inertia, w, dt)
    for _ in range(max_iter):
        wm = 0.5 * (w + w1)
        res = w1 - w - dt * omega_dot(inertia, wm)
        jac = np.eye(3) - 0.5 * dt * np.linalg.solve(inertia, _skew(inertia @ wm) - _skew(wm) @ inertia)
        try:
            step = np.linalg.solve(jac, res)
        except np.linalg.LinAlgError:
            break
        w1 = w1 - step
        if np.max(np.abs(step)) < tol * max(1.0, np.max(np.abs(w1))):
            return w1
    raise RuntimeError("implicit midpoint did not converge: Newton found no root near the Euler step (a step too long for this angular velocity and inertia)")


def invariants(inertia: np.ndarray, w: np.ndarray) -> tuple[float, float]:
    """(|I w|, 0.5 w.I w)."""
    h = inertia @ w
    return float(np.linalg.norm(h)), float(0.5 * w @ h)
