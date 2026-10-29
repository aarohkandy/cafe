"""FluidX3D as a second LBM backend, behind the same window interface. DISABLED by default.

FluidX3D's licence forbids commercial and military use and requires publishing modifications (docs/LICENSES.md), so cafe
neither bundles nor builds it. This module drives a binary the lab built itself, only when
`config["fluidx3d"] = {"enabled": true, "binary": "/path/to/executable"}` and that path is an executable file. Anything
else raises `FluidX3DUnavailable` with the reason, and callers fall back to the XLB / interFoam paths.

Contract of the executable (FluidX3D itself has no CLI and no forces file: it is configured by recompiling `setup.cpp`; the
lab's build wraps that in a binary that honours this contract):
    <binary> --case case.json --out forces.dat
case.json: name, cells [nx,ny,nz], dx, dt, nu, rho, velocity (ground frame, body axes), steps, free_surface, stl (path,
           body frame, metres) or null, draft.
forces.dat: text, one line per sampled step, `# ` comments allowed:  step  time_s  Fx_N  Fy_N  Fz_N  (force on the body, body axes).
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import pathlib
import subprocess
from collections.abc import Sequence
from typing import Any

import numpy as np
from numpy.typing import NDArray

DEFAULTS: dict[str, Any] = {"enabled": False, "binary": None, "timeout_s": 7200}


class FluidX3DUnavailable(RuntimeError):
    """The FluidX3D backend is off, or its binary is missing."""


def settings(config: dict[str, Any] | None) -> dict[str, Any]:
    return {**DEFAULTS, **((config or {}).get("fluidx3d") or {})}


def available(config: dict[str, Any] | None) -> tuple[bool, str]:
    """(ok, reason). ok only when enabled in the config and the binary is an executable file."""
    s = settings(config)
    if not s["enabled"]:
        return False, "disabled in config (default: licence forbids commercial/military use, see docs/LICENSES.md)"
    b = s["binary"]
    if not b:
        return False, "enabled but config['fluidx3d']['binary'] is not set"
    p = pathlib.Path(b)
    if not p.is_file():
        return False, f"binary {b} does not exist"
    if not os.access(p, os.X_OK):
        return False, f"binary {b} is not executable"
    return True, f"using {b}"


def read_forces(path: str | os.PathLike[str]) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """forces.dat -> (time (n,), force (n, 3)). Rejects malformed rows, non-finite values and non-increasing time."""
    rows: list[list[float]] = []
    for ln, line in enumerate(pathlib.Path(path).read_text().splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) != 5:
            raise ValueError(f"{path}:{ln}: expected 'step time Fx Fy Fz', got {len(parts)} columns")
        rows.append([float(x) for x in parts])
    if not rows:
        raise ValueError(f"{path}: no data rows")
    a = np.array(rows)
    if not np.isfinite(a).all():
        raise ValueError(f"{path}: non-finite value")
    if (np.diff(a[:, 1]) <= 0).any():
        raise ValueError(f"{path}: time is not increasing")
    return a[:, 1], a[:, 2:5]


def run_case(config: dict[str, Any] | None, case: dict[str, Any], workdir: str | os.PathLike[str]) -> dict[str, Any]:
    """Run the lab's FluidX3D build on `case`. Returns {t, force, source, binary_sha256, seconds}."""
    ok, why = available(config)
    if not ok:
        raise FluidX3DUnavailable(why)
    s = settings(config)
    wd = pathlib.Path(workdir)
    wd.mkdir(parents=True, exist_ok=True)
    (wd / "case.json").write_text(json.dumps(case, default=float, indent=1))
    out = wd / "forces.dat"
    out.unlink(missing_ok=True)
    r = subprocess.run([s["binary"], "--case", str(wd / "case.json"), "--out", str(out)], cwd=wd, capture_output=True,
                       text=True, timeout=s["timeout_s"])
    (wd / "fluidx3d.log").write_text(r.stdout + r.stderr)
    if r.returncode:
        raise RuntimeError(f"FluidX3D exited {r.returncode}: {(r.stdout + r.stderr)[-500:]}")
    if not out.exists():
        raise RuntimeError("FluidX3D finished without writing forces.dat")
    t, f = read_forces(out)
    sha = hashlib.sha256(pathlib.Path(s["binary"]).read_bytes()).hexdigest()
    return dict(t=t, force=f, source="fluidx3d", binary_sha256=sha, steps=int(case["steps"]))


def case_dict(name: str, cells: Sequence[int], dx: float, dt: float, nu: float, rho: float, velocity: Sequence[float], steps: int,
              stl: str | None = None, free_surface: bool = False, draft: float = 0.0) -> dict[str, Any]:
    if not math.isfinite(dx * dt * nu * rho) or min(dx, dt, nu, rho) <= 0:
        raise ValueError("dx, dt, nu and rho must be positive and finite")
    return dict(name=name, cells=[int(c) for c in cells], dx=dx, dt=dt, nu=nu, rho=rho, velocity=[float(v) for v in velocity],
                steps=int(steps), free_surface=bool(free_surface), stl=stl, draft=draft)
