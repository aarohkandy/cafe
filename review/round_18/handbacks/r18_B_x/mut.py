"""Apply each mutant of A-1 to cafe/pm/physics/comms.py (on the orca copy only), run the m16 tests, restore the file. The control first."""
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
F = ROOT / "cafe/pm/physics/comms.py"
SRC = F.read_text()
MUT = [
    ("control", None, None),
    ("C23 250->249", "m = 250.0 * d_km ** 2", "m = 249.0 * d_km ** 2"),
    ("C24 17.456->17.5", "h_req = 17.456 *", "h_req = 17.5 *"),
    ("C28 no maximum", "(1.0 - h_se / h_req) * np.maximum(_diffraction_beyond_db(a_em, d_km, f_mhz, ht, hr), 0.0)", "(1.0 - h_se / h_req) * _diffraction_beyond_db(a_em, d_km, f_mhz, ht, hr)"),
    ("C30 2.01 a", "d_los = np.sqrt(2.0 * a_km)", "d_los = np.sqrt(2.01 * a_km)"),
    ("C32 hr*1.01", "np.sqrt(np.maximum(hr, 0.0) / 1e3))\n    beyond", "np.sqrt(np.maximum(hr * 1.01, 0.0) / 1e3))\n    beyond"),
]
try:
    for name, old, new in MUT:
        if old is not None:
            assert SRC.count(old) == 1, (name, SRC.count(old))
            F.write_text(SRC.replace(old, new))
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-q", "-x", "-p", "no:cacheprovider", "tests/test_round18_b.py", "-k", "m16"], cwd=ROOT, capture_output=True, text=True)
        print(f"{name}: rc={r.returncode} ({'KILLED' if r.returncode else 'SURVIVED'})", [l for l in r.stdout.splitlines() if l.startswith("FAILED")][:1], flush=True)
        F.write_text(SRC)
finally:
    F.write_text(SRC)
