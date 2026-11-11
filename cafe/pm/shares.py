"""Split the test files into K shares of about equal time, for `bin/proot_suite.sh` (one pytest process per share, no xdist).

    python -m cafe.pm.shares <K> <out dir> [junit.xml ...]      (from the repository root)

Writes <out dir>/s1.args ... sK.args, one pytest `@argument file` per share (its test files, then a `--deselect` for each of `audit.SERIAL_TESTS`, which
run alone afterwards), and <out dir>/serial.args (those tests). A file's weight is its summed test time in the junit files given, later files
overriding earlier ones; a file they do not know weighs its size at the seconds-per-byte of the files they do know. Greedy: heaviest file first, into
the lightest share. Every test file is in exactly one share.
"""
from __future__ import annotations

import pathlib, sys, tomllib
import xml.etree.ElementTree as ET

from .audit import ROOT, SERIAL_TESTS

# pytest's own setting, so that the shares and `pytest tests` collect the same files: a pattern of its own here
# would leave a file out of every share (round 10 M-29)
PYTHON_FILES: list[str] = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["pytest"]["ini_options"]["python_files"]


def test_files(root: pathlib.Path = ROOT) -> list[str]:
    """Every test file under tests/, as pytest collects them (`python_files` of pyproject.toml), relative to `root`, sorted."""
    return sorted({str(f.relative_to(root)) for p in PYTHON_FILES for f in (root / "tests").rglob(p) if "__pycache__" not in f.parts})


def file_seconds(junit: list[pathlib.Path], files: list[str]) -> dict[str, float]:
    """Seconds per test file in `files` summed over the junit files; a file in a later junit file replaces what an earlier one said."""
    mods = {f[:-3].replace("/", "."): f for f in files}
    out: dict[str, float] = {}
    for x in junit:
        one: dict[str, float] = {}
        for tc in ET.parse(x).iter("testcase"):
            m = tc.get("classname", "")
            while m and m not in mods:
                m = m.rpartition(".")[0]                      # tests.test_a.TestClass -> tests.test_a
            if m and f"{mods[m]}::{tc.get('name')}" not in SERIAL_TESTS:       # those run alone, not in a share (an old junit file may still hold their time)
                one[mods[m]] = one.get(mods[m], 0.0) + float(tc.get("time", 0))
        out.update(one)
    return out


def weights(files: list[str], seconds: dict[str, float], root: pathlib.Path = ROOT) -> dict[str, float]:
    size = {f: max((root / f).stat().st_size, 1) for f in files}
    known = [f for f in files if f in seconds]
    rate = sum(seconds[f] for f in known) / sum(size[f] for f in known) if known else 1.0       # seconds per byte; with no junit at all, size alone
    return {f: seconds[f] if f in seconds else size[f] * (rate or 1.0) for f in files}


def split(w: dict[str, float], k: int) -> list[list[str]]:
    """Greedy longest-first into `k` shares; ties by name, so the same input gives the same shares."""
    if not 1 <= k <= len(w):
        raise ValueError(f"{k} shares for {len(w)} test files")
    load = [0.0] * k
    out: list[list[str]] = [[] for _ in range(k)]
    for f in sorted(w, key=lambda f: (-w[f], f)):
        i = min(range(k), key=lambda j: (load[j], j))
        out[i].append(f)
        load[i] += w[f]
    return [sorted(s) for s in out]


def main(argv: list[str], root: pathlib.Path = ROOT) -> int:
    if len(argv) < 2 or not (argv[0].isascii() and argv[0].isdigit() and int(argv[0]) >= 1):     # '²' is a digit to isdigit, int() refuses it; 0 is no share
        print(__doc__)
        return 2
    k, out = int(argv[0]), pathlib.Path(argv[1])
    files = test_files(root)
    try:                                     # a junit file cut or missing, too many shares, an output that is a file: an error line, not a traceback (M-37)
        w = weights(files, file_seconds([pathlib.Path(x) for x in argv[2:]], files), root)
        shares = split(w, k)
        assert sorted(f for s in shares for f in s) == files         # every file in exactly one share
        out.mkdir(parents=True, exist_ok=True)
        for old in out.glob("s*.args"):                              # a smaller K than the last run leaves no stale share behind
            old.unlink()
        for i, s in enumerate(shares, 1):
            (out / f"s{i}.args").write_text("".join(f"{f}\n" for f in s) + "".join(f"--deselect={t}\n" for t in SERIAL_TESTS))
            print(f"s{i}: {len(s)} files, planned {sum(w[f] for f in s):.0f} s")
        (out / "serial.args").write_text("".join(f"{t}\n" for t in SERIAL_TESTS))
    except (ET.ParseError, OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
