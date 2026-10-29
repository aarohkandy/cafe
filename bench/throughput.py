"""Cell-updates per second for the CFD solvers the planner can use; results merge into bench/throughput.json.

    ./run.sh python bench/throughput.py foam   # OpenFOAM pimpleFoam LES, 1/2/4/8 cores (the cafe image)
    python bench/throughput.py lbm [gpu]       # JAX D3Q19 lattice-Boltzmann LES kernel (needs jax)

One cell-update = one cell advanced one time step (a pimpleFoam step includes its pressure correctors).
The first steps (startup, JIT) are excluded from every timing.
"""
import json, os, pathlib, platform, re, subprocess, sys, tempfile, time

OUT = pathlib.Path(__file__).with_name("throughput.json")
FOAM = "source /usr/lib/openfoam/openfoam2506/etc/bashrc >/dev/null 2>&1; "


def save(solver, entry):
    data = json.loads(OUT.read_text()) if OUT.exists() else {}
    data[solver] = entry
    OUT.write_text(json.dumps(data, indent=2) + "\n")
    print(json.dumps({solver: entry}, indent=2))


# ------------------------------------------------------------------ OpenFOAM LES

def _foam_case(d, n, steps):
    """A 1 x 1 x 1 m box, n^3 hexes, 2 m/s inflow with noise, Smagorinsky LES — the shape of an L2 nest."""
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    from cafe.cfd import write
    write(d, "system/blockMeshDict", f"""convertToMeters 1;
vertices ((0 0 0) (1 0 0) (1 1 0) (0 1 0) (0 0 1) (1 0 1) (1 1 1) (0 1 1));
blocks (hex (0 1 2 3 4 5 6 7) ({n} {n} {n}) simpleGrading (1 1 1));
boundary ( inlet {{ type patch; faces ((0 4 7 3)); }} outlet {{ type patch; faces ((1 2 6 5)); }}
  sides {{ type slip; faces ((0 1 5 4) (3 7 6 2) (0 3 2 1) (4 5 6 7)); }} );""")
    dt = 0.3 / n / 2.0                     # CFL 0.3 at 2 m/s
    write(d, "system/controlDict", f"""application pimpleFoam; startFrom startTime; startTime 0; stopAt endTime;
endTime {dt * steps}; deltaT {dt}; writeControl timeStep; writeInterval 100000; runTimeModifiable false;""")
    write(d, "system/fvSchemes", """ddtSchemes { default backward; } gradSchemes { default Gauss linear; }
divSchemes { default none; div(phi,U) Gauss linear; div((nuEff*dev2(T(grad(U))))) Gauss linear; }
laplacianSchemes { default Gauss linear corrected; } interpolationSchemes { default linear; }
snGradSchemes { default corrected; } wallDist { method meshWave; }""")
    write(d, "system/fvSolution", """solvers { p { solver GAMG; smoother DIC; tolerance 1e-6; relTol 0.05; }
pFinal { $p; relTol 0; } "(U|UFinal)" { solver smoothSolver; smoother symGaussSeidel; tolerance 1e-6; relTol 0; } }
PIMPLE { nOuterCorrectors 1; nCorrectors 2; nNonOrthogonalCorrectors 0; }""")
    write(d, "system/decomposeParDict", "numberOfSubdomains 1; method scotch;")
    write(d, "constant/transportProperties", "transportModel Newtonian; nu 1e-6;")
    write(d, "constant/momentumTransport", "simulationType LES; LES { model Smagorinsky; delta cubeRootVol; }")
    write(d, "constant/turbulenceProperties", "simulationType LES; LES { model Smagorinsky; delta cubeRootVol; }")
    write(d, "0/U", """dimensions [0 1 -1 0 0 0 0]; internalField uniform (2 0 0);
boundaryField { inlet { type fixedValue; value uniform (2 0 0); } outlet { type zeroGradient; } sides { type slip; } }""", "volVectorField")
    write(d, "0/p", """dimensions [0 2 -2 0 0 0 0]; internalField uniform 0;
boundaryField { inlet { type zeroGradient; } outlet { type fixedValue; value uniform 0; } sides { type slip; } }""", "volScalarField")
    write(d, "0/nut", """dimensions [0 2 -1 0 0 0 0]; internalField uniform 0;
boundaryField { inlet { type calculated; value uniform 0; } outlet { type calculated; value uniform 0; } sides { type calculated; value uniform 0; } }""", "volScalarField")
    return dt


def foam(n=100, steps=40, warm=10):
    runs = {}
    with tempfile.TemporaryDirectory() as tmp:
        base = pathlib.Path(tmp) / "base"
        _foam_case(base, n, steps)
        subprocess.run(["bash", "-c", FOAM + f"cd {base} && blockMesh > log.blockMesh"], check=True)
        for np_ in (1, 2, 4, 8):
            c = pathlib.Path(tmp) / f"np{np_}"
            subprocess.run(["cp", "-r", str(base), str(c)], check=True)
            (c / "system/decomposeParDict").write_text((c / "system/decomposeParDict").read_text().replace("numberOfSubdomains 1", f"numberOfSubdomains {np_}"))
            run = "pimpleFoam" if np_ == 1 else f"decomposePar -force > log.dec && mpirun --oversubscribe -np {np_} pimpleFoam -parallel"
            subprocess.run(["bash", "-c", FOAM + f"cd {c} && {run} > log.run 2>&1"], check=True)
            t = [float(x) for x in re.findall(r"^ExecutionTime = ([\d.e+-]+) s", (c / "log.run").read_text(), re.M)]
            rate = n ** 3 * (len(t) - warm) / (t[-1] - t[warm - 1])
            runs[np_] = rate
            print(f"pimpleFoam {n}^3 on {np_} core(s): {rate:.3g} cell-updates/s", flush=True)
    save("openfoam-pimpleFoam-les", dict(
        backend="cpu", host=platform.node(), cpu=_cpu(), cells=n ** 3, steps_timed=steps - warm, measured=time.strftime("%Y-%m-%d"),
        cell_updates_per_s={str(k): v for k, v in runs.items()},
        per_device=runs[1], device="cpu core", node=max(runs.values()), devices_per_node=8,
        scaling_efficiency_1_to_8=runs[8] / (8 * runs[1]),
        note="OpenFOAM v2506, Smagorinsky LES, backward/linear, PIMPLE 1 outer x 2 pressure correctors, GAMG; no GPU build exists"))


# ------------------------------------------------------------------ JAX lattice Boltzmann (candidate GPU nest solver)

def lbm(device="cpu", n=128, steps=60, warm=10):
    os.environ.setdefault("JAX_PLATFORMS", device)
    import jax, jax.numpy as jnp, numpy as np
    # numpy, not jnp: the roll shifts must be concrete under jit
    c = np.array([[0, 0, 0], [1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1], [0, 0, -1],
              [1, 1, 0], [-1, -1, 0], [1, -1, 0], [-1, 1, 0], [1, 0, 1], [-1, 0, -1], [1, 0, -1], [-1, 0, 1],
              [0, 1, 1], [0, -1, -1], [0, 1, -1], [0, -1, 1]])
    w = jnp.array([1 / 3] + [1 / 18] * 6 + [1 / 36] * 12)
    tau0, cs = 0.5 + 3e-4, 0.17                     # nearly inviscid + Smagorinsky: an LES at high Re

    def feq(rho, u):
        cu = jnp.einsum("qd,dxyz->qxyz", c, u)
        return w[:, None, None, None] * rho * (1 + 3 * cu + 4.5 * cu ** 2 - 1.5 * (u ** 2).sum(0))

    @jax.jit
    def step(f):
        rho = f.sum(0); u = jnp.einsum("qd,qxyz->dxyz", c, f) / rho
        fe = feq(rho, u); fneq = f - fe
        Q = jnp.sqrt(sum(jnp.einsum("q,qxyz->xyz", c[:, a] * c[:, b], fneq) ** 2 for a in range(3) for b in range(3)))
        tau = 0.5 * (tau0 + jnp.sqrt(tau0 ** 2 + 18 * cs ** 2 * Q / rho))           # Hou et al. 1996
        f = f - fneq / tau
        return jnp.stack([jnp.roll(f[q], tuple(int(x) for x in c[q]), axis=(0, 1, 2)) for q in range(19)])

    key = jax.random.PRNGKey(0)
    u0 = jnp.zeros((3, n, n, n)).at[0].set(0.05) + 0.005 * jax.random.normal(key, (3, n, n, n))
    f = feq(jnp.ones((n, n, n)), u0).astype(jnp.float32)
    for _ in range(warm):
        f = step(f)
    f.block_until_ready(); t0 = time.perf_counter()
    for _ in range(steps):
        f = step(f)
    f.block_until_ready()
    rate = n ** 3 * steps / (time.perf_counter() - t0)
    dev = jax.devices()[0]
    print(f"JAX D3Q19 LBM {n}^3 on {dev}: {rate:.3g} cell-updates/s", flush=True)
    save(f"jax-lbm-d3q19-{device}", dict(
        backend=device, host=platform.node(), cpu=_cpu(), device=str(dev.device_kind), cells=n ** 3, steps_timed=steps,
        measured=time.strftime("%Y-%m-%d"), per_device=rate, node=rate, devices_per_node=1, jax=jax.__version__,
        note="single JAX process using every core it is given; float32, BGK + Smagorinsky, periodic streaming by roll"))


def _cpu():
    try:
        return next(l.split(":", 1)[1].strip() for l in open("/proc/cpuinfo") if l.startswith("model name"))
    except (OSError, StopIteration):
        return platform.processor()


if __name__ == "__main__":
    {"foam": lambda: foam(), "lbm": lambda: lbm(*(sys.argv[2:3] or ["cpu"]))}[sys.argv[1]]()
