"""Load and validate mission, platform and config files. Every refusal names the file, the field and the fix.

    load_mission(path) -> dict   (schema-checked against cafe/schemas/mission.json, then cross-checked; sets the verdict thresholds
                                  of cafe.pm.stats.intervals from the mission's verdict block)
    load_platform(name_or_path) -> dict
    assumptions() -> dict        (config/assumptions.yaml: every number that is a prior, not a measurement)
"""
from __future__ import annotations

import contextlib, datetime as dt, hashlib, json, math, os, pathlib, re
from collections.abc import Hashable, Iterator
from typing import Any

import yaml

from .stats import intervals

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCHEMAS = ROOT / "cafe" / "schemas"
PLATFORMS = ROOT / "platforms"
CONFIG = ROOT / "config"
THROUGHPUT_FIX = "`make bench` measures it again, or `git checkout config/throughput.json` restores the tracked one"


class ConfigError(ValueError):
    """A file the user wrote is wrong; the message says where and how to fix it."""


class _Loader(yaml.SafeLoader):                                         # type: ignore[misc]
    """SafeLoader that refuses what YAML 1.1 accepts silently: a repeated mapping key (the later value wins) and a leading-zero integer (octal)."""

    def construct_mapping(self, node: Any, deep: bool = False) -> dict[Any, Any]:
        seen: set[Any] = set()
        for k, _ in node.value:
            if k.tag == "tag:yaml.org,2002:merge":
                continue
            key = self.construct_object(k, deep=True)
            if isinstance(key, Hashable) and key in seen:
                raise ConfigError(f"line {k.start_mark.line + 1}: duplicate key {key!r}; a later value would silently replace an earlier one")
            seen.add(key)
        out: dict[Any, Any] = super().construct_mapping(node, deep)
        return out


def _int(self: _Loader, node: Any) -> Any:
    text = str(node.value)
    v = yaml.SafeLoader.construct_yaml_int(self, node)
    if re.fullmatch(r"[-+]?0[0-7_]+", text):
        raise ConfigError(f"line {node.start_mark.line + 1}: {text} is read as octal {v}; write {v}, or quote it for a string")
    return v


_Loader.add_constructor("tag:yaml.org,2002:int", _int)
# YAML 1.1 wants a dot in a float, so PyYAML reads 1e-6, 5e0 and 1e+7 as text; every file read through `read_yaml` takes them as numbers (round 8, L0)
_Loader.add_implicit_resolver("tag:yaml.org,2002:float", re.compile(r"^[-+]?[0-9][0-9_]*[eE][-+]?[0-9]+$"), list("-+0123456789"))


def _yaml(path: str | pathlib.Path) -> Any:
    path = pathlib.Path(path)
    if not path.exists():
        raise ConfigError(f"{path}: file not found")
    try:
        return yaml.load(path.read_text(), Loader=_Loader)                  # noqa: S506  _Loader is a SafeLoader
    except UnicodeDecodeError as e:
        raise ConfigError(f"{path}: not a UTF-8 text file ({e.reason} at byte {e.start}); the mission and platform files are UTF-8 YAML") from e
    except OSError as e:
        raise ConfigError(f"{path}: cannot be read ({e.strerror or e})") from e
    except ConfigError as e:
        raise ConfigError(f"{path}: {e}") from e
    except yaml.YAMLError as e:
        raise ConfigError(f"{path}: not valid YAML ({e})") from e


read_yaml = _yaml                                                       # the one YAML reader: every config, platform and mission file goes through it


def platform_doc(path: str | pathlib.Path) -> Any:
    """A platform file's mapping, read as `_yaml` does (round 8, M-25). An empty or comment-only file (a failed copy), a list or a bare value is a
    ConfigError that says what a platform file is, the same for the three vehicle classes; it was a bare TypeError (USV, glider) or a misleading
    message (UAS)."""
    doc = _yaml(path)
    if not isinstance(doc, dict):
        raise ConfigError(f"{path}: expected a mapping of platform parameters (the file is empty or not a mapping); a platform file has `params:` "
                          f"with a `value` and a `source` or `assumed` + `why` for each number")
    return doc


def _finite(node: Any, path: pathlib.Path, where: str = "") -> None:
    """Refuse a NaN or infinite number anywhere in the mission (JSON Schema's `number` accepts both and every comparison with NaN is False)."""
    if isinstance(node, float) and not math.isfinite(node):
        raise ConfigError(f"{path}: {where or '(top level)'}: {node!r} is not a finite number; write a number (a missing value is a missing key, not .nan)")
    for k, v in (node.items() if isinstance(node, dict) else enumerate(node) if isinstance(node, list) else ()):
        name = v["id"] if isinstance(node, list) and isinstance(v, dict) and "id" in v else k          # a vehicle or link is named by its id
        _finite(v, path, f"{where}/{name}".lstrip("/"))


def _is_float(v: str) -> bool:
    try:
        return math.isfinite(float(v))
    except ValueError:
        return False


def _say(e: Any) -> str:
    """The schema's message, except for the slips a lab user makes first: YAML reads an unquoted timestamp as a time, an empty key as None,
    an unquoted HH:MM as minutes, an unquoted no/yes/on/off as a boolean, and a quoted number as text."""
    if e.validator == "type" and isinstance(e.instance, (dt.datetime, dt.date)):
        return f"an unquoted timestamp is read by YAML as a time; put it in quotes, e.g. \"{e.instance:%Y-%m-%dT%H:%M:%SZ}\""
    if e.validator == "type" and e.instance is None:
        return "is empty; give it a value or remove the key"
    if e.validator == "type" and e.validator_value == "string" and type(e.instance) is int and list(e.absolute_path)[-1:] == ["local_solar_time"]:
        v = e.instance
        hm = f"{v // 60:02d}:{v % 60:02d}"
        return (f"YAML reads an unquoted HH:MM as a number ({v} = {hm} as minutes); put it in quotes, e.g. \"{hm}\"" if 0 <= v < 1440
                else f"YAML reads an unquoted time as the number {v}; put it in quotes, e.g. \"14:00\"")
    if e.validator == "type" and e.validator_value == "string" and isinstance(e.instance, bool):
        return f"YAML reads an unquoted no/yes/on/off as {str(e.instance).lower()}; put it in quotes"
    if e.validator == "type" and e.validator_value == "number" and isinstance(e.instance, str) and _is_float(e.instance):
        return f"the number is written in a form YAML reads as text ({e.instance!r}); write {float(e.instance):g}"
    return str(e.message)


def validate(doc: Any, schema_name: str, where: str) -> Any:
    import jsonschema
    schema = json.loads((SCHEMAS / schema_name).read_text())
    errs = sorted(jsonschema.Draft202012Validator(schema).iter_errors(doc), key=lambda e: list(e.absolute_path))
    if errs:
        lines = [f"  {'/'.join(map(str, e.absolute_path)) or '(top level)'}: {_say(e)}" for e in errs[:12]]
        raise ConfigError(f"{where}: {len(errs)} problem(s) against cafe/schemas/{schema_name}:\n" + "\n".join(lines))
    return doc


def utc(s: str, where: str = "") -> dt.datetime:
    """A YYYY-MM-DDTHH:MM:SSZ string as an aware UTC time. A calendar-invalid one (the schema checks digits only) is a ConfigError naming `where`."""
    try:
        return dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    except ValueError as e:
        raise ConfigError(f"{where + ': ' if where else ''}{s!r} is not a calendar time ({e}); use YYYY-MM-DDTHH:MM:SSZ") from e


def _lon_text(x: float) -> str:
    return f"{abs(x):g} {'W' if x < 0 else 'E'}"


def fmt_box(b: dict[str, float]) -> str:
    """A mission box in words for a message: "lon 165 E to 165 W (across the antimeridian), lat -5 to 5, pad 2 deg" (never the dict). A box crosses the
    antimeridian when lon_min is above lon_max (longitudes are in [-180, 180), as the schema has them)."""
    wrap = " (across the antimeridian)" if b["lon_min"] > b["lon_max"] else ""
    pad = f", pad {b['pad_deg']:g} deg" if "pad_deg" in b else ""
    return f"lon {_lon_text(b['lon_min'])} to {_lon_text(b['lon_max'])}{wrap}, lat {b['lat_min']:g} to {b['lat_max']:g}{pad}"


def _in_box(lon: float, lat: float, b: dict[str, float]) -> bool:
    lo, hi = b["lon_min"] % 360, b["lon_max"] % 360
    x = lon % 360
    inlon = lo <= x <= hi if lo <= hi else (x >= lo or x <= hi)
    return inlon and b["lat_min"] <= lat <= b["lat_max"]


ORCA_ROUTE = ("this build reads the atmosphere and the waves only from the orca run; the one working way to read another copy is the CAFE_ORCA "
              "environment variable (a directory or URL laid out like orca's files). Leave the key out")


def _unread_keys(doc: Any, path: pathlib.Path) -> None:
    """Mission keys that parse but that nothing in this build reads. Refused here (before the schema) so the message names the working route."""
    if not isinstance(doc, dict):
        return
    env = doc.get("environment")
    for block, source in (("atmosphere", "orca_uwincm"), ("waves", "orca_umwm")):
        b = env.get(block) if isinstance(env, dict) else None
        for key, val in (b.items() if isinstance(b, dict) else ()):
            if (key, val) != ("source", source):
                raise ConfigError(f"{path}: environment/{block}/{key}: nothing reads {key}: {val!r} ({ORCA_ROUTE}, or write source: {source})")
    for v in doc.get("vehicles", []) if isinstance(doc.get("vehicles"), list) else []:
        pat = v.get("sorties", {}).get("pattern") if isinstance(v, dict) and isinstance(v.get("sorties"), dict) else None
        if pat not in (None, "flux_profile"):
            raise ConfigError(f"{path}: vehicles/{v.get('id')}/sorties/pattern: only 'flux_profile' is flown by this build, not {pat!r}; use flux_profile")


TABLES = {"radios": "radio table", "modems": "modem table"}      # platform files that hold a table of radios / modems, not one vehicle


def table_provenance(doc: Any) -> list[str]:
    """Paths in a radios.yaml / modems.yaml table that say nothing about where they come from: an entry (radios.rfd900x, modems.benthos_atm960)
    with no `source`, and a {value, ...} leaf that has neither a `source` nor (`assumed: true` and a `why`)."""
    bad: list[str] = []
    for group, entries in (doc.items() if isinstance(doc, dict) else ()):
        for name, entry in (entries.items() if isinstance(entries, dict) else ()):
            if not isinstance(entry, dict):
                continue
            if "value" in entry:                         # a {value, ...} leaf of `defaults`: it needs a source or assumed+why, not an entry source
                bad += [f"{group}.{name}"] if _leaf_problems(entry) else []
                continue
            if not entry.get("source"):
                bad.append(f"{group}.{name}.source")
            bad += [f"{group}.{name}.{p}" for p in _leaf_problems(entry)]
    return bad


def json_object(p: pathlib.Path, fix: str = "`run` writes it, so run it again (--fresh)") -> dict[str, Any]:
    """A JSON object a run wrote and a command reads back; a corrupt file or any other JSON is a ConfigError (exit 2), not a traceback. `fix` says
    what makes the file again."""
    try:
        d = json.loads(p.read_text())
    except (ValueError, OSError) as e:                                   # JSONDecodeError and UnicodeDecodeError are ValueErrors
        raise ConfigError(f"{p}: not a JSON object ({e}); {fix}") from e
    if not isinstance(d, dict):
        raise ConfigError(f"{p}: not a JSON object (it holds {type(d).__name__}); {fix}")
    return d


@contextlib.contextmanager
def damaged_run_files(run: pathlib.Path) -> Iterator[None]:
    """Round 10, M-5. A file of a finished run that is valid JSON but lacks a key, or holds another type where one is read, is the same damage as one that is
    not JSON: a ConfigError (`error:`, exit 2), not a traceback. The original text stays in the message, so a bug in the code is not hidden by it."""
    try:
        yield
    except (KeyError, TypeError) as e:
        raise ConfigError(f"{run}: damaged or incomplete ({type(e).__name__}: {e}); run it again (--fresh)") from e


def write_json(p: pathlib.Path, obj: Any, **kw: Any) -> None:
    """`obj` as JSON in `p` through a sibling temporary and os.replace: a run killed mid-write leaves the old file, never half of a new one that
    `json_object` and the other readers of a stored result would then have to refuse (round 9, L0; the writer of every slow-run receipt)."""
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(obj, **kw))
    os.replace(tmp, p)


def finite_real(v: Any) -> bool:
    """A finite real number: not a bool, a string, None, NaN or infinity, nor an integer too large for a float (json.loads gives a 400-digit literal as an
    int, and math.isfinite raises OverflowError on it)."""
    try:
        return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
    except OverflowError:
        return False


def missing_numbers(d: dict[str, Any], numeric: tuple[str, ...], optional: tuple[str, ...] = ()) -> list[str]:
    """The keys of a stored result that the code reads as numbers and that are not finite reals: each of `numeric`, and each of `optional` that is
    present. The one rule of every reader of a stored receipt (stage 3's `lbm.read_stored` and the credibility report): a hand-edited or schema-changed
    file is a result that is not stored, never a KeyError or a TypeError (round 9, M-4)."""
    return [k for k in numeric if not finite_real(d.get(k))] + [k for k in optional if k in d and not finite_real(d[k])]


PLATE_FIELDS = ("err", "cf", "re", "ittc", "yfrac")         # what the wall-model plate receipt's readers index; each must be a finite number (missing_numbers)
CHANNEL_FIELDS = ("err", "cf", "cf_dean")                   # the channel's: stage 3's gate reads `err`, the credibility report `cf` and `cf_dean`
PLATE_RE_MIN = 1e6                                          # ITTC-57 is a turbulent correlation: a plate run below this Re_L is not compared with it


def plate_re_problem(name: str, d: dict[str, Any]) -> str | None:
    """Why a stored flat-plate receipt `d` (read by `missing_numbers` over PLATE_FIELDS, so `re` is a finite number) cannot count: it was run below
    PLATE_RE_MIN. The one rule of the stage-3 gate (`wallmodel._stored_receipts`) and the credibility page (round 9, L0)."""
    if d["re"] < PLATE_RE_MIN:
        return f"{name} is at Re_L {d['re']:.3g}, below the {PLATE_RE_MIN:g} the comparison needs (rerun it)"
    return None


def stored_receipt_problem(name: str, d: dict[str, Any], current_sha: str, plate: bool = False) -> str | None:
    """Why a stored slow-run receipt `d` (a JSON object already read with its numbers checked) cannot count, or None: stored without a `code_sha` (legacy
    or hand-written), stored by code other than `current_sha` (`lbm.physics_sha()`, which the caller passes: config cannot import stage 3), or, for the
    flat plate (`plate`), run below PLATE_RE_MIN (`plate_re_problem`). The one rule of the stage-3 gate (`wallmodel._stored_receipts`) and of the credibility
    page's rows of stored receipts (`credibility._stored_rows`), so a receipt stage 3 refuses is never shown as a result (round 9, DECISIONS 527)."""
    if d.get("code_sha") is None:
        return f"{name} was stored without a code sha (rerun it)"
    if d["code_sha"] != current_sha:
        return f"{name} was stored by different code (rerun it)"
    return plate_re_problem(name, d) if plate else None


def _leaf_problems(node: Any, path: str = "") -> list[str]:
    from .physics.uas import check_provenance
    if isinstance(node, dict) and "value" in node:
        return check_provenance(node, path)
    return [b for k, v in node.items() for b in _leaf_problems(v, f"{path}.{k}" if path else k)] if isinstance(node, dict) else []


def _registry(name: str, key: str) -> dict[str, Any]:
    return dict(_yaml(PLATFORMS / name)[key])


def _modem_names() -> set[str]:
    """The names a link's `modem` may take: a modems.yaml key, or "<key>_<band>" as stage 1 resolves it (case-insensitive)."""
    return {n.lower() for k, v in _registry("modems.yaml", "modems").items() for n in (k, *(f"{k}_{b}" for b in v["bands"]))}


MODES = {"glider": ("station", "section", "drift"), "usv": ("station", "section"), "uas": ()}      # task.mode each vehicle class can fly
MIN_DEPLOY_BEFORE_END_S = 600.0       # stage 1's record interval (stage1.REC_S): a vehicle deployed later than this before window.end gets no record


def _kind_class(kind: str) -> str:
    return "usv" if "sail" in kind or "usv" in kind else "glider"


def platform_class(v: dict[str, Any]) -> str:
    """The one rule: "uas" if the vehicle has `base`; else "usv" if its platform's kind (the file name if none) contains sail or usv; else "glider"."""
    if "base" in v:
        return "uas"
    return _kind_class(str(load_platform(v["platform"]).get("kind") or v["platform"]).lower())


def _file_class(plat: dict[str, Any]) -> str:
    """What the platform file itself is: a file with no `kind` is the UAS file."""
    return _kind_class(str(plat["kind"]).lower()) if plat.get("kind") else "uas"


def _platforms_of(cls: str) -> list[str]:
    out = []
    for f in sorted(PLATFORMS.glob("*.yaml")):
        d = _yaml(f)
        if isinstance(d, dict) and (("airframe" in d) if cls == "uas" else bool(d.get("kind")) and _kind_class(str(d["kind"]).lower()) == cls):
            out.append(f.stem)
    return out


def _check_platform(v: dict[str, Any], where: str) -> str:
    """The vehicle's class, after its platform file has been loaded with that class's loader (so stage 1 never meets a wrong-class file)."""
    cls, plat = platform_class(v), load_platform(v["platform"])
    if _file_class(plat) != cls:
        why = "has `base`, so it is a UAS" if cls == "uas" else "has no `base`, so it is not a UAS" if _file_class(plat) == "uas" else f"is a {cls}"
        raise ConfigError(f"{where}/platform: '{v['platform']}' is a {_file_class(plat)} platform file, but the vehicle {why}; use one of {_platforms_of(cls)}")
    from .physics import glider, uas, usv
    try:
        {"uas": uas, "usv": usv, "glider": glider}[cls].load_platform(v["platform"])
    except (ValueError, KeyError) as e:
        raise ConfigError(f"{where}/platform: '{v['platform']}' does not load as a {cls} platform ({type(e).__name__}: {e})") from e
    return cls


def _check_links(m: dict[str, Any], path: pathlib.Path, nodes: set[str]) -> None:
    cls = {v["id"]: platform_class(v) for v in m["vehicles"]}
    lids = [lk["id"] for lk in m["links"]]
    if dupl := sorted({i for i in lids if lids.count(i) > 1}):
        raise ConfigError(f"{path}: link ids {dupl} appear more than once; give each link its own id (results are keyed by link id)")
    shore = m.get("shore", {}).get("id")
    radios, modems = set(_registry("radios.yaml", "radios")), _modem_names()
    for lk in m["links"]:
        where = f"{path}: links/{lk['id']}"
        if lk["a"] == lk["b"]:
            raise ConfigError(f"{where}: a link from '{lk['a']}' to itself; give it two different ends")
        for end in ("a", "b"):
            if lk[end] not in nodes:
                raise ConfigError(f"{where}/{end}: '{lk[end]}' is not a vehicle, the ship or the shore ({sorted(nodes)})")
        if lk["kind"] != "iridium" and shore in (lk["a"], lk["b"]):
            raise ConfigError(f"{where}: the shore has no position; only iridium links can end at the shore, not {lk['kind']}")
        need = {"rf": "radio", "acoustic": "modem"}.get(lk["kind"])
        if need and need not in lk:
            raise ConfigError(f"{where}: a {lk['kind']} link needs '{need}' (a key in platforms/{need}s.yaml)")
        if "radio" in lk and lk["radio"] not in radios:
            raise ConfigError(f"{where}/radio: '{lk['radio']}' is not in platforms/radios.yaml; use one of {sorted(radios)}")
        if "modem" in lk and lk["modem"].lower() not in modems:
            raise ConfigError(f"{where}/modem: '{lk['modem']}' is not in platforms/modems.yaml; use a key or <key>_<band>, e.g. {sorted(modems)[:3]}")
        ends = {cls.get(lk["a"]), cls.get(lk["b"])}
        if lk["kind"] == "acoustic" and "uas" in ends:
            raise ConfigError(f"{where}: an acoustic link cannot end at a UAS (it flies, depth 0); use an rf link, or move that end")
        if lk["kind"] == "iridium":
            if lk.get("when", "always") not in ("always", "surfacing") or (lk.get("when") == "surfacing" and "glider" not in ends):
                raise ConfigError(f"{where}/when: an iridium link is checked at every record, or at a glider's "
                                  f"surfacings (surfacing, with a glider at one end), not '{lk['when']}'; use always or leave it out")
        elif "when" not in lk:
            raise ConfigError(f"{where}/when: a {lk['kind']} link needs when: always, surfacing or uas_airborne")
        elif lk["when"] == "uas_airborne" and "uas" not in ends:
            raise ConfigError(f"{where}/when: uas_airborne needs the UAS at one end of the link; use always or change a/b")
        elif lk["when"] == "surfacing" and "glider" not in ends:
            raise ConfigError(f"{where}/when: surfacing needs a glider at one end of the link; use always or change a/b")
        if lk["kind"] in ("rf", "iridium") and "glider" in ends and lk.get("when") != "surfacing":
            raise ConfigError(f"{where}/when: a glider's radio and Iridium antenna work only at the surface: "
                              f"use when: surfacing (not '{lk.get('when', 'always')}')")


def _unshare(node: Any) -> Any:
    """`node` rebuilt so that no list or mapping is one object in two places. YAML anchors and aliases (`deploy: &d {...}` ... `deploy: *d`) give two
    vehicles the same dict, and a what-if edit of one (`whatif.apply`, the emulator's variants) would then edit both."""
    if isinstance(node, dict):
        return {k: _unshare(v) for k, v in node.items()}
    return [_unshare(v) for v in node] if isinstance(node, list) else node


def load_mission(path: str | pathlib.Path, set_verdict: bool = True) -> dict[str, Any]:
    """The checked mission. `set_verdict` sets the verdict cut-offs of `stats.intervals` (module state of the one mission a command runs); a mission
    loaded only to be read (the benchmark's, for its sortie-minutes) passes False and leaves them alone."""
    path = pathlib.Path(path)
    doc = _yaml(path)
    _unread_keys(doc, path)
    _finite(doc, path)
    m: dict[str, Any] = validate(doc, "mission.json", str(path))
    t0, t1 = utc(m["window"]["start"], f"{path}: window/start"), utc(m["window"]["end"], f"{path}: window/end")
    if t1 <= t0:
        raise ConfigError(f"{path}: window.end {m['window']['end']} is not after window.start; swap them")
    oc = m["environment"]["ocean"]
    if oc["source"] == "lab_hycom" and not oc.get("path"):
        raise ConfigError(f"{path}: environment/ocean: source 'lab_hycom' needs a path to the lab's ingested HYCOM store; add path: <store>, "
                          f"e.g. path: /data/ocean/lab_{m['name']}.zarr")
    if oc["source"] == "gofs31" and "temperature_kind" in oc:
        raise ConfigError(f"{path}: environment/ocean/temperature_kind: it belongs to the lab's HYCOM (source: lab_hycom) and GOFS 3.1 has its own; remove it")
    if oc["source"] == "gofs31" and oc.get("path") and pathlib.Path(oc["path"]).suffix != ".zarr":
        raise ConfigError(f"{path}: environment/ocean/path: {oc['path']!r} does not end in .zarr; the GOFS fetch writes <name>.zarr, so the check on this path "
                          f"would fail after every download. Write {oc['path']}.zarr, or leave the path out (the default is DATA/ocean/gofs_{m['name']}.zarr)")
    ids = [v["id"] for v in m["vehicles"]]
    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        raise ConfigError(f"{path}: vehicle ids {sorted(dup)} appear more than once; give each vehicle its own id")
    owners = [(v["id"], f"vehicles/{v['id']}") for v in m["vehicles"]] + [(m[k]["id"], k) for k in ("ship", "shore") if k in m]
    for i in dict.fromkeys(i for i, _ in owners):
        if len(who := [w for j, w in owners if j == i]) > 1:
            raise ConfigError(f"{path}: ids must be unique across vehicles, ship and shore; '{i}' is used by {' and '.join(who)}; rename one")
    if not m["box"]["lat_min"] < m["box"]["lat_max"]:
        raise ConfigError(f"{path}: box.lat_min ({m['box']['lat_min']}) must be below box.lat_max ({m['box']['lat_max']}); swap them")
    if (m["box"]["lon_max"] - m["box"]["lon_min"]) % 360.0 == 0:             # `_in_box`'s modulo: the same longitude twice is a strip with no width
        raise ConfigError(f"{path}: box.lon_min and box.lon_max are both {m['box']['lon_min']}: the box has no width and nothing fits in it; "
                          "give the west and east edges (a box across the dateline is lon_min 165, lon_max -165)")
    from .pipeline import ocean_box                                         # refuse here the box ingest would refuse
    try:
        ocean_box(m)
    except ConfigError as e:
        raise ConfigError(f"{path}: {e}") from e
    if "ship" in m and not _in_box(m["ship"]["lon"], m["ship"]["lat"], m["box"]):
        raise ConfigError(f"{path}: ship ({m['ship']['lon']}, {m['ship']['lat']}) is outside the mission box ({fmt_box(m['box'])}); "
                          "widen the box or move the ship")
    nodes = set(ids) | {m.get("ship", {}).get("id"), m.get("shore", {}).get("id")} - {None}
    for v in m["vehicles"]:
        where = f"{path}: vehicles/{v['id']}"
        if "base" in v and v["base"] != m.get("ship", {}).get("id"):
            raise ConfigError(f"{where}/base: '{v['base']}' is not the ship's id; add a ship block with that id or fix the base")
        if "base" not in v and v.get("task", {}).get("mode") == "station" and not {"lon", "lat"} <= set(v["task"]):          # a UAS's task is refused below
            raise ConfigError(f"{where}/task: mode 'station' needs lon and lat of the station "
                              "(radius_km, default 5, and lost_after_h, default 6, are optional)")
        if "deploy" in v:
            d = v["deploy"]
            td = utc(d["time"], f"{where}/deploy/time")
            if not t0 <= td < t1:
                raise ConfigError(f"{where}/deploy/time: {d['time']} is outside the window {m['window']['start']} .. {m['window']['end']}")
            if (t1 - td).total_seconds() < MIN_DEPLOY_BEFORE_END_S:
                mn, last = MIN_DEPLOY_BEFORE_END_S / 60, t1 - dt.timedelta(seconds=MIN_DEPLOY_BEFORE_END_S)
                raise ConfigError(f"{where}/deploy/time: {d['time']} is less than {mn:g} min before window.end; "
                                  f"deploy at least {mn:g} min before the end, by {last:%Y-%m-%dT%H:%M:%SZ}")
            pts = [(d["lon"], d["lat"])] + [tuple(p) for p in v.get("task", {}).get("waypoints", [])]
            if "lon" in v.get("task", {}):
                pts.append((v["task"]["lon"], v["task"]["lat"]))
            for lon, lat in pts:
                if not _in_box(lon, lat, m["box"]):
                    raise ConfigError(f"{where}: point ({lon}, {lat}) is outside the mission box ({fmt_box(m['box'])}); widen the box or move the point")
        plat, cls = load_platform(v["platform"]), _check_platform(v, where)
        if cls == "glider" and "dive_depth_m" in v.get("task", {}):
            from .physics import glider
            P, dd = glider.load_platform(v["platform"]), v["task"]["dive_depth_m"]
            if not P["min_dive_m"] <= dd <= P["rating_m"]:
                raise ConfigError(f"{where}/task/dive_depth_m: {dd:g} m is outside what the {P['kind']} '{v['platform']}' "
                                  f"dives: min_dive_m {P['min_dive_m']:g} m to rating_m {P['rating_m']:g} m; use a depth in that range")
        if "sorties" in v and cls != "uas":
            raise ConfigError(f"{where}/sorties: only a UAS (a vehicle with `base`) flies sorties; remove sorties, or add base: <the ship's id>")
        so = v.get("sorties", {})
        hard = so.get("duration_min", 0) * float(plat.get("sortie", {}).get("hard_stop_factor", {}).get("value", 1.0))
        if so and so.get("every_days", 1) * 1440 < hard:
            raise ConfigError(f"{where}/sorties/every_days: {so.get('every_days', 1)} d is shorter than duration_min x the platform's hard_stop_factor "
                              f"({hard:g} min), so sorties would overlap; raise every_days to at least {hard / 1440:.3g} or shorten duration_min")
        if so:
            from . import stage1
            from .env import orca
            if not len(stage1.launch_times(so, float(m["ship"]["lon"]), t0.timestamp(), t1.timestamp(), 60.0 * hard)):
                hh, mm = (int(x) for x in so["local_solar_time"].split(":"))
                h, mi = divmod(round(hh * 60 + mm - m["ship"]["lon"] * 4.0) % 1440, 60)
                utc_hm = f"{h:02d}:{mi:02d}"
                raise ConfigError(f"{where}/sorties: no launch fits in the window "
                                  f"(local_solar_time {so['local_solar_time']} at lon {m['ship']['lon']:g} is {utc_hm}Z, "
                                  f"a launch needs {hard:g} min before window.end); widen the window or change the time")
            alt = so.get("altitudes_m", ())
            if any(b <= a for a, b in zip(alt, alt[1:], strict=False)):
                raise ConfigError(f"{where}/sorties/altitudes_m: {list(alt)} does not rise; list the flight levels from the lowest to the highest, each once")
            if (high := [a for a in alt if a > orca.WIND3D_TOP_M]):
                raise ConfigError(f"{where}/sorties/altitudes_m: {high[0]:g}: the stored WRF levels end at about {orca.WIND3D_TOP_M:g} m; "
                                  f"the wind above that is not known; "
                                  f"use altitudes up to {orca.WIND3D_TOP_M:g} m")
        task = v.get("task", {})
        if "task" in v and cls == "uas":
            raise ConfigError(f"{where}/task: a UAS flies sorties and takes no task; remove task")
        if task and task["mode"] not in MODES[cls]:
            raise ConfigError(f"{where}/task/mode: '{task['mode']}' is not a mode a {cls} flies; use one of {list(MODES[cls])}")
        if task.get("mode") == "drift" and "heading_to" not in task:
            raise ConfigError(f"{where}/task: drift needs heading_to, the compass heading the glider swims on; "
                              f"there is no pass/fail criterion other than battery, depth and seafloor")
        if task.get("mode") == "section" and len(task.get("waypoints", [])) < 2:
            raise ConfigError(f"{where}/task: mode 'section' needs at least two waypoints: [[lon, lat], [lon, lat], ...]")
        wps = task.get("waypoints", []) if task.get("mode") == "section" else []
        for i, (a, b) in enumerate(zip(wps, wps[1:], strict=False), 1):
            if a == b:                                                       # (the schema keeps lon in [-180, 180): there is one spelling of a point)
                raise ConfigError(f"{where}/task/waypoints/{i}: {list(b)} is the same point as waypoints/{i - 1}; a leg of zero length has no track to "
                                  "hold, so the cross-track test would be silently off. Remove the repeat, or use mode: station to hold one point")
    _check_links(m, path, nodes)
    if not m["verdict"]["nogo"] < m["verdict"]["go"]:
        raise ConfigError(f"{path}: verdict.nogo ({m['verdict']['nogo']}) must be below verdict.go ({m['verdict']['go']})")
    if set_verdict:
        intervals.set_thresholds(m["verdict"]["go"], m["verdict"]["nogo"])
    m = _unshare(m)
    m["_path"] = str(path)
    return m


def platform_path(ref: str | pathlib.Path) -> pathlib.Path:
    """The file a vehicle's `platform` names: a path as given when it ends in .yaml or .yml, else platforms/<ref>.yaml. The one rule; every consumer
    of a platform reference (this loader, the hangar stage, the class loaders) resolves it here."""
    p = pathlib.Path(ref)
    return p if p.suffix in (".yaml", ".yml") else PLATFORMS / f"{ref}.yaml"


def platform_display(ref: str | pathlib.Path) -> str:
    """`platform_path(ref)` as a label for a report: relative to the repo when the file is in it (a name and `platforms/<name>.yaml` give the same
    text), else the path as given."""
    p = platform_path(ref)
    try:
        return p.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(p)


def load_platform(name: str | pathlib.Path) -> dict[str, Any]:
    path = platform_path(name)
    if not path.exists():
        have = sorted(x.stem + (" (table)" if x.stem in TABLES else "") for x in PLATFORMS.glob("*.yaml"))
        raise ConfigError(f"platform '{name}': no file {path}; available: {have}")
    doc = _yaml(path)
    return {} if doc is None else platform_doc(path)                  # an empty file: the class loader (and `hangar`) names it, as "provenance FAILED"


def assumptions() -> dict[str, Any]:
    p = CONFIG / "assumptions.yaml"
    return _yaml(p) if p.exists() else {}


def env_sigmas() -> dict[str, Any]:
    """1-sigma uncertainties GriddedEnv tags its values with: wind, Hs and Tp from the Stage-1 priors (perturbations.yaml),
    the rest from assumptions.yaml (env.sigma.*) until the TAO comparison replaces them."""
    pri = _yaml(CONFIG / "perturbations.yaml")
    a = assumptions()
    out = {k.split(".")[-1]: a[k]["value"] for k in a if k.startswith("env.sigma.")}
    out.update(wind_ms=pri["wind_speed_bias"]["value"], hs_frac=pri["hs_scale"]["value"], tp_s=pri["tp_bias"]["value"])
    return out


def digest(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()
