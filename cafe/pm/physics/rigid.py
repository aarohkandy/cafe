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


def implicit_midpoint(inertia: np.ndarray, w: np.ndarray, dt: float, tol: float = 1e-14, max_iter: int = 100) -> np.ndarray:
    """Solve w1 = w + dt dw/dt((w + w1)/2) by fixed-point iteration (converges for dt |w| < 1)."""
    w1 = explicit_euler(inertia, w, dt)
    for _ in range(max_iter):
        new = w + dt * omega_dot(inertia, 0.5 * (w + w1))
        if np.max(np.abs(new - w1)) < tol:
            return new
        w1 = new
    raise RuntimeError("implicit midpoint did not converge: dt |w| is too large")


def invariants(inertia: np.ndarray, w: np.ndarray) -> tuple[float, float]:
    """(|I w|, 0.5 w.I w)."""
    h = inertia @ w
    return float(np.linalg.norm(h)), float(0.5 * w @ h)
