"""Round 21, batch E (the JSON sweep, M-9) and the count message (D-6, M-13), and round 22's batch E (M-10): no raw JSON read, `math.isfinite`, `numpy.isfinite`
or import by a computed name is left in any Python file of the repository that is shipped or run (`cafe/`, `lab/`, `bench/`, `report/`, anything new) outside an
allow-list that gives each file's exact count and reason, found by an AST checker that is tested against every spelling the reviewers named; every reader of a
user-editable or run-written file refuses an oversized integer, nesting that exhausts the stack and the rest of the hostile documents with its own message or a
ValueError (never an OverflowError, a RecursionError or a traceback), the app's request bodies and the mission YAML refuse a number that does not fit, and
`acceptance._damage` quotes the one rule of a stored count."""
import ast
import copy
import math
import os
import pathlib
import re

import pytest

from cafe import _seed, cfd, hangar, receipts as cafe_receipts, worker
from cafe.pm import acceptance as acc, audit, config, credibility as cr, jsonio, ledger, vv
from cafe.pm.env import hycom, orca, subgrid, tao
from cafe.pm.stage3 import lbm

ROOT = pathlib.Path(__file__).resolve().parents[1]
CAFE = ROOT / "cafe"

# ---------------------------------------------------------------------------------------------------------------------------- the grep tests
# Round 22, M-10: the two grep tests of round 21 walked `cafe/` only and matched four spellings (`json.loads(`, `from json import loads`, `math.isfinite`, `from
# math import isfinite`). They are one AST checker now, over every Python file of the repository that is shipped or run, by what is IMPORTED and what is
# ACCESSED, through the spellings listed here (plain, `import ... as`, `from ... import`, `getattr`) and no others. A site is: json (the module or any other
# JSON parser) read through `load`, `loads`, `JSONDecoder`, a response's `.json()`; `math.isfinite`; `numpy.isfinite`; and the dynamic spellings of those
# (`getattr(m, ...)`, `vars(m)`, `m.__dict__`, `__import__("json")`, `importlib.import_module("json")`; and an import by a computed name, which can bring in
# any of them); a name assigned the module (`m = math`) holds it too. The ceiling (round 23, M-10, D-7): it reads SPELLING, not data flow. A module bound by a
# tuple assignment (`a, b = json, 1`), a class or instance attribute (`C.j`, `self.j = json`), a dict item (`d["l"]`), an argument or `sys.modules` is not
# followed (none was found in the repository; a new one is found in review).
FAMILIES = {"json": ("json", "simplejson", "orjson", "ujson", "rapidjson"), "math": ("math",), "numpy": ("numpy",)}
SITE_NAMES = {"json": {"load", "loads", "JSONDecoder"}, "math": {"isfinite"}, "numpy": {"isfinite"}}
MODULE_NAMES = {m: f for f, mods in FAMILIES.items() for m in mods}


def _family(dotted):
    return MODULE_NAMES.get((dotted or "").split(".")[0])


def _literal(n):
    return n.value if isinstance(n, ast.Constant) and isinstance(n.value, str) else None


def scan_source(src):
    """[(family, what, line)] for every site in the source text; family is json, math, numpy, or dynamic (an import by a computed name)."""
    tree = ast.parse(src)
    alias: dict[str, str] = {}                                   # a name that holds one of the modules (import, from-import, assignment of one)
    importers: set[str] = set()                                  # names that are `importlib.import_module`
    sites: list[tuple[str, str, int]] = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                if _family(a.name):
                    alias[a.asname or a.name.split(".")[0]] = _family(a.name)
        elif isinstance(n, ast.ImportFrom):
            f = None if n.level else _family(n.module)
            for a in n.names:
                if n.module == "importlib" and a.name == "import_module":
                    importers.add(a.asname or a.name)
                elif f is None:
                    if a.name in MODULE_NAMES:                  # `from somewhere import json`
                        alias[a.asname or a.name] = MODULE_NAMES[a.name]
                elif a.name == "*" or a.name in SITE_NAMES[f]:
                    sites.append((f, f"from {n.module} import {a.name}", n.lineno))
                else:                                           # `from json import decoder`: a submodule that holds JSONDecoder
                    alias[a.asname or a.name] = f

    def is_importer(n):
        f = n.func
        return (isinstance(f, ast.Name) and (f.id == "__import__" or f.id in importers)) or (isinstance(f, ast.Attribute) and f.attr == "import_module")

    def dyn_family(e):
        return _family(_literal(e.args[0])) if isinstance(e, ast.Call) and is_importer(e) and e.args else None

    def root_family(e):
        while isinstance(e, ast.Attribute):
            e = e.value
        return alias.get(e.id) if isinstance(e, ast.Name) else None

    changed = True
    while changed:                                              # `m = math`, `d = json.decoder`, `m = __import__("math")`: the target holds the module too
        changed = False
        for n in ast.walk(tree):
            if isinstance(n, (ast.Assign, ast.AnnAssign, ast.NamedExpr)) and n.value is not None:
                f = root_family(n.value) or dyn_family(n.value)
                for t in (n.targets if isinstance(n, ast.Assign) else [n.target]):
                    if f and isinstance(t, ast.Name) and alias.get(t.id) != f:
                        alias[t.id] = f
                        changed = True
    for n in ast.walk(tree):
        if isinstance(n, ast.Attribute):
            f = root_family(n.value)
            if f and n.attr in SITE_NAMES[f]:
                sites.append((f, f".{n.attr}", n.lineno))
            elif f and n.attr == "__dict__":
                sites.append((f, "the module's __dict__", n.lineno))
        elif isinstance(n, ast.Call):
            fn = n.func
            if isinstance(fn, ast.Name) and fn.id in ("getattr", "vars") and n.args:
                f = root_family(n.args[0]) or dyn_family(n.args[0])
                name = _literal(n.args[1]) if len(n.args) > 1 else None
                if f and (fn.id == "vars" or name is None or name in SITE_NAMES[f]):
                    sites.append((f, f"{fn.id}() on the module", n.lineno))
            if is_importer(n):
                name = _literal(n.args[0]) if n.args else None
                if name is None:
                    sites.append(("dynamic", "an import by a computed name", n.lineno))
                elif _family(name):
                    sites.append((_family(name), f"a dynamic import of {name}", n.lineno))
            if isinstance(fn, ast.Attribute) and fn.attr == "json" and not n.args and not n.keywords:
                sites.append(("json", ".json() of a response", n.lineno))
    return sorted(sites, key=lambda s: s[2])


# What is walked: every `*.py` under the repository root, and every file without an extension that starts with a python shebang, except the directories below
# and any directory whose name starts with a dot (.git, .venv, caches). A new top-level directory with Python in it is walked: it fails until it is classified.
NOT_WALKED = {
    "tests": "the suite: it feeds hostile documents and reads its own fixtures on purpose; nothing of it ships or runs in a mission",
    "review": "the review rounds' probes, merge scripts and hand-backs: run once by a reviewer or the lead, never imported by the product",
    "mutants": "mutmut's generated copy of the code (gitignored, written by `make mutation`); the same files are walked in their place",
}


def python_files(root=ROOT):
    for dirpath, dirs, files in os.walk(root):
        here = pathlib.Path(dirpath)
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d != "__pycache__" and not (here == root and d in NOT_WALKED))
        for f in sorted(files):
            if f.endswith(".py"):
                yield here / f
            elif "." not in f:
                try:
                    with open(here / f, "rb") as fh:
                        head = fh.readline(200)
                except OSError:
                    continue
                if head.startswith(b"#!") and b"python" in head:
                    yield here / f


def scan_tree(root=ROOT):
    """({family: {file: count}}, {file: [(family, what, line)]}) over `python_files(root)`."""
    counts: dict[str, dict[str, int]] = {}
    where: dict[str, list[tuple[str, str, int]]] = {}
    for p in python_files(root):
        rel = p.relative_to(root).as_posix()
        for fam, what, line in scan_source(p.read_text()):
            counts.setdefault(fam, {})[rel] = counts.get(fam, {}).get(rel, 0) + 1
            where.setdefault(rel, []).append((fam, what, line))
    return counts, where


# Shell, make and workflow text that could run Python inline (`python -c "..."`): no reader and no finite test may be spelled in it.
TEXT_SITE = re.compile(r"\bjson\.(?:loads?|JSONDecoder)\b|\bisfinite\b")


def text_files(root=ROOT):
    names = [*root.glob("*.sh"), *root.glob("Dockerfile*"), root / "Makefile", *(root / "bin").glob("*"), *(root / ".github" / "workflows").glob("*")]
    return [p for p in sorted(set(names)) if p.is_file() and not p.name.endswith(".py")]


# Each entry: the file, the exact number of sites, and why that number of raw sites is safe or not. The counts are exact: a site that moves is no change, and a
# new one, or one fewer, fails the test until the entry is edited. `jsonio.load_json` is the ONE reader of a user-editable or run-written file, and
# `jsonio.finite_real` the one test of a number that came out of JSON.
RAW_JSON = {
    "cafe/pm/jsonio.py": (1, "the reader itself"),
    "cafe/pm/config.py": (1, "the package's own JSON schema (cafe/pm/schemas), shipped with the code: not user data"),
    "cafe/pm/env/orca.py": (1, "the package's own schema of the WRF and UMWM output, shipped with the code"),
    "cafe/pm/env/hycom.py": (1, "the package's own schema of the HYCOM store, shipped with the code"),
    "cafe/pm/report.py": (1, "the report's own list of report.json paths, which it wrote into the HTML it is checking (`data-paths`)"),
    "cafe/hangar.py": (1, "`_write_result`: the round trip of the text the same call has just dumped, to turn a non-finite float into null"),
    "cafe/app.py": (1, "the round trip of the text its own `json.dumps(..., allow_nan=False)` has just made"),
    "cafe/_tepex_api.py": (1, "a stand-alone client script of the deployed API that imports nothing of cafe: the text is an HTTP response, not a file"),
    "cafe/_redteam.py": (6, "a developer script that replays the red-team cases through the app: five `.json()` of the app's own responses (a 400 or a body "
                            "the app wrote with `allow_nan=False`) and one `__import__(\"json\").dumps` (a WRITER, spelled so because a local `json` shadows "
                            "the module)"),
    "lab/check.py": (3, "a stand-alone script a lab user runs with the standard library only (no cafe import): two reads of the app's own HTTP response, and "
                        "the user's fleet file, which is forwarded as it is to the app, whose request bodies refuse an oversized number with a 400 (reader A, "
                        "A-3). It does no arithmetic on a number of the file"),
    "report/build.py": (1, "the old report builder (`report/` is the pre-round-10 static report, in the sync filter as rewritten by the server): reads three "
                           "JSON files the same repository wrote, quotes them into one HTML; no verdict reads its output"),
}

# Every use of math.isfinite (a call, or a reference such as `map(math.isfinite, ...)`): none is on a number that comes straight out of JSON. A number read from
# a file enters through `load_json` (an integer that does not fit a float is a ValueError there: `math.isfinite` and `float` of one that fits cannot overflow),
# a request body's through `jsonio.finite_real`, a YAML number through `config._finite`. A new use fails this test until it is listed with its reason.
RAW_ISFINITE = {
    "cafe/app.py": (3, "127: of a `float(...)` made inside a try that catches OverflowError; 330 and 356: FastAPI-typed float query parameters"),
    "cafe/cfd.py": (1, "`_finite_positive`: of `float(v)` of a design number (spec.json is read by `load_json`, so an integer fits; keyed code: not edited)"),
    "cafe/pm/budget.py": (1, "`--gpu-mem-gb`: an argparse float"),
    "cafe/pm/config.py": (1, "`_is_float`: of `float(text)`, a string (never an OverflowError)"),
    "cafe/pm/env/environment.py": (2, "of `float(a[...])` of a store attribute inside a try that catches OverflowError"),
    "cafe/pm/jsonio.py": (1, "`finite_real`, the test itself (OverflowError caught)"),
    "cafe/pm/ledger.py": (1, "`clean`: of a value that `isinstance(x, float)` says is a float"),
    "cafe/pm/receipts.py": (3, "values computed in this process by `cafe.receipts` (floats); a stored row is read by `load_json`, so its integers fit a float"),
    "cafe/pm/report.py": (1, "`_f`: of a value that `isinstance(x, float)` says is a float"),
    "cafe/pm/stage3/fluidx3d.py": (1, "`case_dict`: the solver's own float parameters"),
    "cafe/pm/stage3/freesurface.py": (3, "`float(...)` of a stored number (read by `load_json`, an integer fits) and a float the check made"),
    "cafe/pm/stage3/rans.py": (6, "`flow_label`: of a norm the arithmetic made; `row_fields`: of `float(...)` of a stored number (read by `load_json`, an integer fits) "
                                  "and of floats the checks made; `reasons`: of a check's value, a float"),
    "cafe/pm/stage3/lbm.py": (1, "`positive_float`: of `float(text)` of a command-line string"),
    "cafe/pm/stats/intervals.py": (2, "of the result of the arithmetic (a float), which is the check batch F added"),
    "cafe/pm/stats/sampling.py": (3, "`_check_range`, after `_num` (which catches OverflowError) has passed every number of the entry; floats"),
    "cafe/pm/stats/sequential.py": (1, "of a float ratio"),
    "cafe/pm/vv.py": (6, "of floats the grid-convergence arithmetic made, and of the float arguments of `gci_two_grid`"),
    "cafe/pm/whatif.py": (2, "of floats made by `float()` of a command-line number (`mod` is built by `__main__._whatif` from `--shift`, `--move`, `--duty`)"),
}

# Every use of numpy.isfinite: on an array it never raises, but on a SCALAR that is a Python int above 2**63 it is a TypeError (`np.isfinite(2**64)`), which
# `math.isfinite` of the same int is not. Each file says what the argument is. "arrays": a NumPy array made here (np.asarray(..., float), arithmetic, a store
# variable, a model's state) of floats; "float": a Python float made here. Read from the sites, not traced through the callers, except where a site is named.
ARRAYS = "arrays and floats made in this process (np.asarray(..., float), arithmetic, a store variable or a model's state), never a number straight out of JSON"
RAW_NP_ISFINITE = {
    "cafe/_site_data.py": (1, "`P`: a float the power sweep computed"),
    "cafe/app.py": (1, "`clean_spec` inertia: an array made by `np.asarray(v, float)` inside a try that catches OverflowError"),
    "cafe/cfd.py": (2, "the mesh extents (an array from trimesh) and `gci`, a float `gci()` has just computed"),
    "cafe/mission.py": (3, "arrays and a float of the navigation error percentiles made here"),
    "cafe/ocean.py": (1, "an array of the current store read with numpy"),
    "cafe/vehicle.py": (1, "`_vec3`: an array made by `np.asarray(raw, float)` inside a try that catches OverflowError, "
                           "after each item passed `finite_real` or is a numpy number"),
    "cafe/pm/emulator.py": (1, "`q`: a float quantile the emulator computed"),
    "cafe/pm/env/bathy.py": (1, ARRAYS),
    "cafe/pm/env/coare.py": (3, ARRAYS),
    "cafe/pm/env/environment.py": (1, ARRAYS),
    "cafe/pm/env/grid.py": (2, ARRAYS),
    "cafe/pm/env/hycom.py": (5, ARRAYS),
    "cafe/pm/env/perturb.py": (1, ARRAYS),
    "cafe/pm/env/surface.py": (5, ARRAYS),
    "cafe/pm/env/tao.py": (9, ARRAYS),
    "cafe/pm/physics/__init__.py": (1, "an array (`a.size` is read in the same condition)"),
    "cafe/pm/physics/comms.py": (1, "`n_bytes` after `np.asarray(n_bytes, float)`: an integer that does not fit is an OverflowError there, not a "
                                 "TypeError (callers not traced)"),
    "cafe/pm/physics/glider.py": (8, ARRAYS),
    "cafe/pm/physics/rfband.py": (1, "`diff`: an array of the two curves' difference"),
    "cafe/pm/physics/uas.py": (7, ARRAYS),
    "cafe/pm/physics/usv.py": (12, ARRAYS),
    "cafe/pm/pipeline.py": (31, ARRAYS),
    "cafe/pm/report.py": (11, ARRAYS + "; a stored list becomes an array by `np.asarray(..., float)`, and `load_json` refused an integer that does not fit"),
    "cafe/pm/stage1.py": (21, ARRAYS),
    "cafe/pm/stage3/fluidx3d.py": (1, "`np.array(rows)` of parsed floats"),
    "cafe/pm/stage3/nest.py": (2, ARRAYS),
    "cafe/pm/stage3/pipeline_windows.py": (3, ARRAYS),
    "cafe/pm/stage3/refit.py": (2, "`np.asarray(..., float)` of the means and standard errors"),
    "cafe/pm/stats/sampling.py": (1, "`_num`, inside a try that catches OverflowError and TypeError"),
    "cafe/pm/stats/sensitivity.py": (1, "`y`: the response array `first_order` is given (its shape is checked on the same line)"),
    "cafe/pm/whatif.py": (3, "longitude and latitude arrays, and a list of the emulator's feature floats"),
    "cafe/receipts.py": (1, "an array of the hull-lift grid"),
    "cafe/shapes.py": (1, "`check`, of floats made by `float()` in `create_shape_design` inside a try that catches OverflowError"),
}

# Imports by a name that is computed, which can bring in `json`, `math` or `numpy` without one of the spellings above: each has its names from constants.
RAW_DYNAMIC = {
    "cafe/pm/ledger.py": (1, "`_version(m)`: the module names are the string constants of its callers (the packages the run records the versions of)"),
    "cafe/pm/par.py": (2, "the module names of `STATE`, a constant tuple of four (module, attribute) pairs of this package"),
    "cafe/pm/receipts.py": (1, "`_call(mod, fn)`: `mod` is a string constant at each caller in this file (package modules)"),
}

ALLOWED = {"json": RAW_JSON, "math": RAW_ISFINITE, "numpy": RAW_NP_ISFINITE, "dynamic": RAW_DYNAMIC}
USE = {"json": "use `jsonio.load_json`", "math": "use `jsonio.finite_real`", "numpy": "use `jsonio.finite_real` for a scalar", "dynamic": "name the module"}


def _show(where, files):
    return "; ".join(f"{rel}:{line} {what}" for rel in files for fam, what, line in where.get(rel, ()))


@pytest.mark.parametrize("fam", sorted(ALLOWED))
def test_every_raw_json_read_and_finite_test_in_any_python_file_of_the_repository_is_one_that_is_listed_with_its_reason_and_count(fam):
    """`lab/check.py`, `bench/throughput.py` and `report/build.py` read JSON raw and were outside the walk of round 21; so were `import math as m`,
    `from json import loads`, `getattr(json, "loads")`, `__import__("json")` and `np.isfinite` of a scalar."""
    counts, where = scan_tree()
    want = {k: n for k, (n, _) in ALLOWED[fam].items()}
    got = counts.get(fam, {})
    bad = sorted(k for k in set(got) | set(want) if got.get(k) != want.get(k))
    assert not bad, f"{fam}: {USE[fam]} or list the site with its reason and count; now {got}, listed {want}; at {_show(where, bad)}"
    for rel, (n, why) in ALLOWED[fam].items():
        assert n >= 1 and len(why) > 15 and (ROOT / rel).is_file(), rel


def test_no_shell_make_or_workflow_text_spells_a_json_reader_or_a_finite_test():
    assert text_files() and all(not TEXT_SITE.search(p.read_text()) for p in text_files()), [p.name for p in text_files() if TEXT_SITE.search(p.read_text())]
    assert TEXT_SITE.search("python3 -c 'import json; json.loads(x)'") and TEXT_SITE.search("python -c \"import math; math.isfinite(1)\"")


def test_the_walk_covers_everything_shipped_or_run_and_says_why_it_leaves_the_rest():
    walked = {p.relative_to(ROOT).as_posix() for p in python_files()}
    assert {"cafe/app.py", "cafe/pm/stage1.py", "lab/check.py", "bench/throughput.py", "report/build.py", "cafe/_redteam.py"} <= walked
    assert not any(w.split("/")[0] in NOT_WALKED for w in walked) and len(walked) > 80
    assert all(len(why) > 20 for why in NOT_WALKED.values()) and (ROOT / "tests").is_dir() and (ROOT / "review").is_dir()
    top = {d.name for d in ROOT.iterdir() if d.is_dir() and not d.name.startswith(".") and any(d.rglob("*.py"))}
    assert top - set(NOT_WALKED) == {"cafe", "lab", "bench", "report"}, f"a top-level directory with Python in it: {top}: walked automatically; say so here"


def test_a_new_raw_site_anywhere_in_a_tree_fails_and_the_excluded_directories_do_not(tmp_path):
    raw = "import json\njson.loads('1')\n"
    files = {"lab/x.py": raw, "newdir/y.py": "from math import isfinite\n", "bin/tool": "#!/usr/bin/env python3\nimport json\njson.load(f)\n",
             "setup.py": "import numpy as np\nnp.isfinite(1)\n", "tests/t.py": raw, "review/r.py": raw, "mutants/m.py": raw, ".venv/v.py": raw,
             "bin/run.sh": "#!/bin/sh\njson.loads\n"}
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    counts, _ = scan_tree(tmp_path)
    assert counts == {"json": {"lab/x.py": 1, "bin/tool": 1}, "math": {"newdir/y.py": 1}, "numpy": {"setup.py": 1}}


# The spellings of the reviewers' probes, and the ordinary ones: each is fed to the checker as a source text and must be found, once each (the count is part
# of the claim: an allow-list entry's number is what these produce).
CAUGHT = {
    "json.loads": ("import json\njson.loads(s)", {"json": 1}),
    "json.load": ("import json\njson.load(f)", {"json": 1}),
    "import json as j": ("import json as j\nj.loads(s)", {"json": 1}),
    "alias of an alias": ("import json\na = json\nb = a\nb.loads(s)", {"json": 1}),
    "from json import loads": ("from json import loads\nloads(s)", {"json": 1}),
    "from json import loads as parse": ("from json import loads as parse\nparse(s)", {"json": 1}),
    "from json import load, loads": ("from json import load, loads", {"json": 2}),
    "from json import star": ("from json import *", {"json": 1}),
    "from json.decoder import JSONDecoder": ("from json.decoder import JSONDecoder\nJSONDecoder().decode(s)", {"json": 1}),
    "json.JSONDecoder().decode": ("import json\njson.JSONDecoder().decode(s)", {"json": 1}),
    "json.decoder.JSONDecoder": ("import json.decoder\njson.decoder.JSONDecoder()", {"json": 1}),
    "import json.decoder as d": ("import json.decoder as d\nd.JSONDecoder().raw_decode(s)", {"json": 1}),
    "from json import decoder": ("from json import decoder\ndecoder.JSONDecoder()", {"json": 1}),
    "d = json.decoder": ("import json\nd = json.decoder\nd.JSONDecoder()", {"json": 1}),
    "a reference, not a call": ("import json\nlist(map(json.loads, texts))", {"json": 1}),
    "getattr(json, 'loads')": ("import json\ngetattr(json, 'loads')(s)", {"json": 1}),
    "getattr(json, computed)": ("import json\ngetattr(json, name)(s)", {"json": 1}),
    "getattr on an alias": ("import json as j\ngetattr(j, 'load')", {"json": 1}),
    "vars(json)": ("import json\nvars(json)['loads'](s)", {"json": 1}),
    "json.__dict__": ("import json\njson.__dict__['loads'](s)", {"json": 1}),
    "__import__('json').loads": ("__import__('json').loads(s)", {"json": 1}),
    "importlib.import_module('json')": ("import importlib\nimportlib.import_module('json').loads(s)", {"json": 1}),
    "from importlib import import_module as imp": ("from importlib import import_module as imp\nimp('json').loads(s)", {"json": 1}),
    "m = __import__('json')": ("m = __import__('json')\nm.loads(s)", {"json": 2}),
    "getattr(__import__('json'), 'loads')": ("getattr(__import__('json'), 'loads')(s)", {"json": 2}),
    "simplejson as json": ("import simplejson as json\njson.loads(s)", {"json": 1}),
    "orjson": ("import orjson\norjson.loads(s)", {"json": 1}),
    "response.json()": ("r = client.get('/x')\nr.json()['a']", {"json": 1}),
    "from somewhere import json": ("from cafe.x import json\njson.loads(s)", {"json": 1}),
    "from . import json": ("from . import json\njson.loads(s)", {"json": 1}),
    "walrus alias": ("import math\nif (m := math):\n    m.isfinite(1)", {"math": 1}),
    "annotated alias": ("import math\nm: object = math\nm.isfinite(1)", {"math": 1}),
    "inside a function and a try": ("def f(s):\n    try:\n        import json as j\n    finally:\n        pass\n    return j.loads(s)", {"json": 1}),
    "math.isfinite": ("import math\nmath.isfinite(x)", {"math": 1}),
    "import math as m": ("import math as m\nm.isfinite(x)", {"math": 1}),
    "m = math": ("import math\nm = math\nm.isfinite(x)", {"math": 1}),
    "f = math.isfinite": ("import math\nf = math.isfinite\nf(x)", {"math": 1}),
    "map(math.isfinite, xs)": ("import math\nall(map(math.isfinite, xs))", {"math": 1}),
    "from math import isfinite": ("from math import isfinite\nisfinite(x)", {"math": 1}),
    "from math import isfinite as ok": ("from math import isfinite as ok\nok(x)", {"math": 1}),
    "from math import star": ("from math import *", {"math": 1}),
    "getattr(math, 'isfinite')": ("import math\ngetattr(math, 'isfinite')(x)", {"math": 1}),
    "getattr(m, computed)": ("import math as m\ngetattr(m, name)(x)", {"math": 1}),
    "__import__('math')": ("__import__('math').isfinite(x)", {"math": 1}),
    "importlib.import_module('math')": ("import importlib\nimportlib.import_module('math')", {"math": 1}),
    "np.isfinite": ("import numpy as np\nnp.isfinite(x)", {"numpy": 1}),
    "np.isfinite of a scalar of a document": ("import numpy as np\ndoc = load_json(t)\nnp.isfinite(doc['x'])", {"numpy": 1}),
    "import numpy": ("import numpy\nnumpy.isfinite(x)", {"numpy": 1}),
    "import numpy.ma as ma": ("import numpy.ma as ma\nma.isfinite(x)", {"numpy": 1}),
    "from numpy import isfinite": ("from numpy import isfinite\nisfinite(x)", {"numpy": 1}),
    "from numpy import star": ("from numpy import *", {"numpy": 1}),
    "f = np.isfinite": ("import numpy as np\nf = np.isfinite\nf(x)", {"numpy": 1}),
    "getattr(np, 'isfinite')": ("import numpy as np\ngetattr(np, 'isfinite')(x)", {"numpy": 1}),
    "an import by a computed name": ("m = __import__(name)\nm.loads(s)", {"dynamic": 1}),
    "import_module(computed)": ("import importlib\nimportlib.import_module(name)", {"dynamic": 1}),
}
NOT_CAUGHT = {
    "json.dumps": "import json\njson.dumps(x)",
    "json.dump": "import json\njson.dump(x, f)",
    "getattr(json, 'dumps')": "import json\ngetattr(json, 'dumps')(x)",
    "math.sqrt": "import math\nmath.sqrt(2.0)",
    "math.isnan is not this rule": "import math\nmath.isnan(x)",
    "np.zeros": "import numpy as np\nnp.zeros(3)",
    "np.isnan": "import numpy as np\nnp.isnan(x)",
    "a name that is not the module": "def loads(s):\n    return s\nloads('1')\nself.isfinite(3)\nobj.json",
    "a string and a comment": "x = 'json.loads(s) math.isfinite(x)'  # np.isfinite(y)\n",
    "a literal import of another module": "import importlib\nimportlib.import_module('cafe.pm.env.bathy')",
    "json used as a keyword": "client.post('/x', json=dict(a=1))",
    "a relative import of a sibling module that is named like one": "from .json import loads\nloads(s)",
}


@pytest.mark.parametrize("name", sorted(CAUGHT))
def test_the_checker_finds_each_spelling_of_a_raw_json_read_or_finite_test_once(name):
    src, want = CAUGHT[name]
    got: dict[str, int] = {}
    for fam, _, _ in scan_source(src):
        got[fam] = got.get(fam, 0) + 1
    assert got == want, scan_source(src)


@pytest.mark.parametrize("name", sorted(NOT_CAUGHT))
def test_the_checker_leaves_alone_what_is_not_a_reader_or_the_rule(name):
    assert scan_source(NOT_CAUGHT[name]) == []


# The modules the live app image loads (it has no pyyaml, which `cafe.pm.config` imports). `cafe/receipts.py` is the pipeline's and imports config for its own
# stored-result functions (always did): it only needs to reach the reader through `jsonio` like the others.
APP_IMAGE = {"app.py", "hangar.py", "mission.py", "vehicle.py", "_seed.py", "worker.py", "emulator.py", "ocean.py", "cfd.py", "_site_data.py",
             "planner.py", "live.py"}


def test_the_modules_outside_the_package_that_read_json_import_the_stdlib_only_reader_never_config():
    """`cafe/*.py` outside `cafe/pm` reaches the reader through `cafe.pm.jsonio`, and the modules of the app image never import `cafe.pm.config`."""
    for p in sorted(CAFE.glob("*.py")):
        tree = ast.parse(p.read_text())
        mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        mods |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        names = {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module == "cafe.pm" for a in n.names}
        if any(isinstance(n, ast.Name) and n.id == "load_json" for n in ast.walk(tree)):
            assert "cafe.pm.jsonio" in mods, p.name
        if p.name in APP_IMAGE:
            assert "cafe.pm.config" not in mods and "config" not in names, p.name


def test_the_reader_and_the_finite_test_are_one_function_each():
    assert config.load_json is jsonio.load_json and config.finite_real is jsonio.finite_real
    assert vv.finite_real is jsonio.finite_real and _seed.finite_real is jsonio.finite_real and _seed.load_json is jsonio.load_json
    assert cr.real_ok(10 ** 400) is False and cr.real_ok(1.5) is True


# ---------------------------------------------------------------------------------------------------------------------------- hostile documents
BIG = "1" + "0" * 400                                                  # an integer no float holds
DEEP = "[" * 20000 + "]" * 20000                                       # more nesting than the interpreter's stack allows
NESTED_BIG = '{"a": [{"b": ' + BIG + '}], "c": 1}'
NAN_INF = '{"x": NaN, "gci": [Infinity, -Infinity], "n": NaN}'                  # tokens Python reads and the project writes (a NaN gci)
BOOLS = '{"x": true, "gci": false, "n": true, "value": true}'                    # a bool where a number is read
DOCS = {"big": BIG, "deep": DEEP, "nested_big": NESTED_BIG, "nan_inf": NAN_INF, "bools": BOOLS, "bare_true": "true", "bare_nan": "NaN"}


def write(tmp_path, text, name="x.json"):
    p = tmp_path / name
    p.write_text(text)
    return p


def reader_load_json(tmp_path, text, mp):
    return config.load_json(text)


def reader_load_json_path(tmp_path, text, mp):
    return config.load_json(write(tmp_path, text))


def reader_json_object(tmp_path, text, mp):
    return config.json_object(write(tmp_path, text))


def reader_audit(tmp_path, text, mp):
    return audit._read_json(write(tmp_path, text))


def reader_orca(tmp_path, text, mp):
    return orca.read_json(write(tmp_path, text))


def reader_credibility(tmp_path, text, mp):
    return cr._json(write(tmp_path, text))


def reader_copy_manifest(tmp_path, text, mp):
    return ledger.copy_manifest(write(tmp_path, text), tmp_path / "copy" / "m.json")


def reader_ledger_done(tmp_path, text, mp):
    (tmp_path / "checkpoints" / "stage1").mkdir(parents=True)
    write(tmp_path / "checkpoints" / "stage1", text, "ledger.json")
    return ledger.done(tmp_path, "stage1", "abc")


def reader_ledger_rerecord(tmp_path, text, mp):
    (tmp_path / "checkpoints" / "stage1").mkdir(parents=True)
    write(tmp_path / "checkpoints" / "stage1", text, "ledger.json")
    return ledger.rerecord(tmp_path, "stage1", [], None)


def reader_acceptance_ledger(tmp_path, text, mp):
    (tmp_path / "checkpoints" / "ingest").mkdir(parents=True)
    write(tmp_path / "checkpoints" / "ingest", text, "ledger.json")
    return acc._ledger(tmp_path)


def reader_lbm_stored(tmp_path, text, mp):
    return lbm.read_stored(write(tmp_path, text))


def reader_subgrid(tmp_path, text, mp):
    return subgrid._load(str(write(tmp_path, text)))


def reader_hycom_is_array(tmp_path, text, mp):
    write(tmp_path, text, "zarr.json")
    return hycom._is_array(tmp_path)


def reader_tao(tmp_path, text, mp):
    write(tmp_path, text, "manifest.json")
    return tao.verify(tmp_path)


def reader_worker(tmp_path, text, mp):
    write(tmp_path, text, "status.json")
    return worker.state(tmp_path)


def reader_cafe_receipts(tmp_path, text, mp):
    return cafe_receipts.stored(write(tmp_path, text), "g")


def reader_hangar_load_vehicle(tmp_path, text, mp):
    write(tmp_path, text, "spec.json")
    return hangar.load_vehicle(tmp_path)


def reader_fluidx3d_config(tmp_path, text, mp):
    from cafe.pm.stage3 import freesurface
    mp.setattr(freesurface, "CONFIG_FILE", write(tmp_path, text, "premission.json"))
    return freesurface.fluidx3d_config()


def reader_app_read(tmp_path, text, mp):
    from cafe import app
    return app._read(write(tmp_path, text))


READERS = {fn.__name__[len("reader_"):]: fn for fn in (
    reader_load_json, reader_load_json_path, reader_json_object, reader_audit, reader_orca, reader_credibility, reader_copy_manifest, reader_ledger_done,
    reader_ledger_rerecord, reader_acceptance_ledger, reader_lbm_stored, reader_subgrid, reader_hycom_is_array, reader_tao, reader_worker,
    reader_cafe_receipts, reader_hangar_load_vehicle, reader_fluidx3d_config, reader_app_read)}


def clear_refusal(e: BaseException) -> bool:
    """What a refusal may be: a ValueError (the module's own ConfigError is one), or an error class this program defines on purpose (audit's _Unreadable)."""
    return isinstance(e, ValueError) or type(e).__module__.split(".")[0] == "cafe"


# What a reader does not promise: to take a document of any SHAPE (valid JSON that is no object, or an object lacking its keys). These return what they read
# and leave the shape to the caller (`damaged_run_files` turns a KeyError or TypeError into the damaged-file message); they are fed the oversized integer and
# the nesting, which fail at the reader, and not the documents that are valid JSON of the wrong shape (NaN, a bool, an infinity).
SHAPE_IS_THE_CALLERS = {"ledger_rerecord", "acceptance_ledger", "tao", "hangar_load_vehicle", "subgrid", "fluidx3d_config"}
VALID_JSON = {"nan_inf", "bools", "bare_true", "bare_nan"}
CASES = [(n, d) for n in sorted(READERS) for d in sorted(DOCS) if not (n in SHAPE_IS_THE_CALLERS and d in VALID_JSON)]


@pytest.mark.parametrize("name, doc", CASES)
def test_every_reader_of_a_file_answers_a_hostile_document_clearly_or_not_at_all_and_never_with_a_traceback(tmp_path, monkeypatch, name, doc):
    """The reader returns (its own 'no record' answer: None, {}, a reason, or what it makes of a NaN, an infinity, a bool where a number stands) or raises a
    ValueError or its own error: never an OverflowError, a RecursionError or any other traceback. Before: an integer of 400 digits reached `float`,
    `math.isfinite` or a product, nesting of 20000 brackets reached the stack."""
    try:
        READERS[name](tmp_path, DOCS[doc], monkeypatch)
    except BaseException as e:                                       # noqa: BLE001
        assert not isinstance(e, (OverflowError, RecursionError)) and clear_refusal(e), f"{name} on {doc}: {type(e).__name__}: {str(e)[:200]}"


def test_a_400_digit_integer_and_deep_nesting_are_value_errors_with_a_message_that_does_not_print_them():
    with pytest.raises(ValueError, match=r"an integer of 401 characters is too large for a number") as e:
        config.load_json(BIG)
    assert BIG not in str(e.value)
    with pytest.raises(ValueError, match="nested too deeply"):
        config.load_json(DEEP)
    assert config.load_json("1" + "0" * 308) == 10 ** 308                                          # the largest that fits a float is read
    assert config.load_json("[NaN, Infinity, -Infinity]")[0] != config.load_json("[NaN]")[0]       # NaN stays readable (nan != nan): `cfd.gci` writes one


def test_a_poisoned_cfd_cache_entry_is_recomputed_not_a_traceback_and_the_key_has_not_moved(tmp_path, monkeypatch):
    """`cfd.cached` reads the cache through `load_json`: an entry with a 400-digit `gci` that a hand edit or an older seed left is removed and the case computed
    again. `cached` is one of the functions the cache key leaves out (`NOT_KEYED`), so reading it differently moves no key (both are the digests of 7599881)."""
    monkeypatch.setattr(cfd, "CACHE", tmp_path / "cache")
    stl = tmp_path / "m.stl"
    stl.write_bytes(b"solid x")
    import hashlib
    import json
    key = {"a": 1}
    h = hashlib.sha1(stl.read_bytes() + json.dumps(key).encode() + cfd.recipe().encode()).hexdigest()[:16]
    (tmp_path / "cache").mkdir()
    entry = tmp_path / "cache" / f"{h}.json"
    entry.write_text('{"recipe": "x", "result": {"gci": ' + BIG + "}}")
    log = []
    assert cfd.cached(key, stl, log.append, lambda: {"gci": 0.1}) == {"gci": 0.1}
    assert any("cannot be read (ValueError" in x and "computing again" in x for x in log)
    assert cfd._code_literals() == "9a7181651627013ab5dbd3c6e78f833a798f6aac" and cfd.recipe() == "a091d933b7537473"


# ---------------------------------------------------------------------------------------------------------------------------- numbers
NOT_NUMBERS = [10 ** 400, -(10 ** 400), math.nan, math.inf, -math.inf, True, False, "1", None, [1], {}, 1j]
NOT_IDS = ["big", "-big", "nan", "inf", "-inf", "true", "false", "text", "none", "list", "dict", "complex"]


@pytest.mark.parametrize("x", NOT_NUMBERS, ids=NOT_IDS)
def test_every_finite_real_test_answers_no_to_what_is_not_a_finite_real_and_never_raises(x):
    assert config.finite_real(x) is False and cr.real_ok(x) is False and cr.conf_ok(x) is False and _seed._num(x) is False
    assert vv.gci_value(x) == math.inf and vv.gci_trusted(x) is False
    assert math.isnan(cr._num(x)) and cr._num(None) != cr._num(None)


@pytest.mark.parametrize("x", [0, 1, -1, 0.5, 1e308, 10 ** 308, -(10 ** 308), 2 ** 53 + 1], ids=str)
def test_every_finite_real_test_answers_yes_to_a_number_that_fits_a_float(x):
    assert config.finite_real(x) is True and cr.real_ok(x) is True and _seed._num(x) is True and cr._num(x) == float(x)


# ---------------------------------------------------------------------------------------------------------------------------- the app's request bodies
def app():
    from cafe import app as a
    return a


def refused(fn, *args, **kw):
    """The HTTPException a handler raises for a body it refuses (status 400)."""
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:
        fn(*args, **kw)
    assert e.value.status_code == 400
    return e.value.detail


@pytest.mark.parametrize("bad", [10 ** 400, -(10 ** 400)], ids=["big", "-big"])
def test_the_apps_request_bodies_refuse_an_integer_that_does_not_fit_a_float_with_a_400_not_an_overflow(bad, tmp_path, monkeypatch):
    """Before: `math.isfinite(10**400)`, `float(10**400)` and `np.asarray([...], float)` raised OverflowError inside the handlers (a 500)."""
    a = app()
    assert "cog" in refused(a.clean_spec, dict(cog=[bad, 0, 0]), set())
    assert "inertia" in refused(a.clean_spec, dict(inertia=[[bad, 0, 0], [0, 1, 0], [0, 0, 1]]), set())
    assert "must be [lat, lon]" in refused(a._point, [bad, 0], "start")
    shape = next(iter(a.shapes.PARAMS))
    assert "dimensions" in refused(a.create_shape_design, dict(shape=shape, dims={next(iter(a.shapes.PARAMS[shape]["params"])): bad}))
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "status.json").write_text('{"state": "done"}')
    monkeypatch.setattr(a, "DESIGNS", tmp_path)
    drone = lambda i: dict(id=i, design="d", start=[1.0, 2.0, 3.0], legs=[dict(type="hold", minutes=5)])      # noqa: E731
    fleet = dict(drones=[drone("a"), drone("b")])
    assert a.check_fleet(dict(fleet, links=[dict(a="a", b="b", max_m=100.0)]))
    assert "max_m must be a number" in refused(a.check_fleet, dict(fleet, links=[dict(a="a", b="b", max_m=bad)]))
    assert "start must be" in refused(a.create_mission, dict(drones=[dict(drone("a"), start=[bad, 2.0, 3.0])]))
    assert "seconds must be a number" in refused(a.live_step, "sid", dict(seconds=bad))


def test_the_apps_numbers_still_accept_what_they_accepted():
    a = app()
    assert a.clean_spec(dict(cog=[0.1, 0, -0.2]), set())["cog"] == [0.1, 0, -0.2]
    a._point([10.0, 20.0], "start")
    a._point([10, 20, 5], "start")
    refused(a._point, [True, 20.0], "start")                                                          # a bool is no coordinate (it was accepted by isinstance)
    refused(a._point, [91.0, 0.0], "start")


# ---------------------------------------------------------------------------------------------------------------------------- the mission YAML
def test_a_400_digit_yaml_integer_in_a_mission_is_a_config_error_naming_where(tmp_path):
    """YAML reads it as an int, the schema accepts an int as a number, and `config._finite` checked floats only: its first product was an OverflowError."""
    src = (config.ROOT / "missions" / "ci_fixture.yaml").read_text()
    assert "antenna_height_m: 15.0" in src
    import re
    bad = re.sub(r"(antenna_height_m:\s*)[0-9.]+", lambda m: m.group(1) + BIG, src, count=1)
    p = tmp_path / "m.yaml"
    p.write_text(bad)
    with pytest.raises(config.ConfigError, match=r"ship: an integer of 401 digits is not a finite number|an integer of 401 digits is not a finite number"):
        config.load_mission(p)
    with pytest.raises(config.ConfigError, match=r"nan is not a finite number"):
        config._finite(dict(a=[dict(id="v", x=math.nan)]), p)
    config._finite(dict(a=True, b=1, c=1.5, d=10 ** 308), p)                                          # a bool is the schema's business; ints that fit pass


# ---------------------------------------------------------------------------------------------------------------------------- D-6: the count rule
def test_acceptance_damage_quotes_the_one_rule_of_a_stored_count_with_its_bound():
    """Before: 'is not a count (integers, n >= 1, 0 <= k_fail <= n)' for an `n` above 2**53, which satisfies every clause it quoted."""
    rule = cr.counts_rule()
    assert rule == "integers, n >= 1, 0 <= k_fail <= n, n at most 9007199254740992"
    e = dict(k_fail=0, n=2 ** 60, p_fail=0.0, conf=0.9)
    assert acc._damage(e, "now") == [f"k_fail 0 of n {2 ** 60} now is not a count ({rule})"]
    assert acc._damage(dict(e, n=2 ** 53), "now") == [] and acc._damage(dict(e, n=2 ** 53 + 1), "in the reference")
    with pytest.raises(config.ConfigError, match=rf"k_fail 0 of n {2 ** 60} members is not a count \({rule}\)"):
        cr.check_counts(0, 2 ** 60, "summary.links.x")
    for bad in (dict(e, n=0), dict(e, k_fail=-1), dict(e, k_fail=True), dict(e, n=1.0)):
        assert acc._damage(bad, "now")[0].endswith(f"is not a count ({rule})")


def test_a_count_in_the_golden_that_is_too_large_is_one_problem_line_not_a_traceback():
    g = {"a": 1}
    bad = copy.deepcopy(dict(k_fail=0, n=2 ** 60, p_fail=0.0, conf=0.9))
    assert len(acc._damage(bad, "in the reference")) == 1 and g == {"a": 1}
