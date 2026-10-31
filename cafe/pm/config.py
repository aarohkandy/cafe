"""Load and validate mission, platform and config files. Every refusal names the file, the field and the fix.

    load_mission(path) -> dict   (schema-checked against cafe/schemas/mission.json, then cross-checked; sets the verdict thresholds
                                  of cafe.pm.stats.intervals from the mission's verdict block)
    load_platform(name_or_path) -> dict
    assumptions() -> dict        (config/assumptions.yaml: every number that is a prior, not a measurement)
"""
from __future__ import annotations

import datetime as dt, hashlib, json, pathlib
from typing import Any

import yaml

from .stats import intervals

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCHEMAS = ROOT / "cafe" / "schemas"
PLATFORMS = ROOT / "platforms"
CONFIG = ROOT / "config"


class ConfigError(ValueError):
    """A file the user wrote is wrong; the message says where and how to fix it."""


def _yaml(path: str | pathlib.Path) -> Any:
    path = pathlib.Path(path)
    if not path.exists():
        raise ConfigError(f"{path}: file not found")
    try:
        return yaml.safe_load(path.read_text())
    except yaml.YAMLError as e:
        raise ConfigError(f"{path}: not valid YAML ({e})") from e


def validate(doc: Any, schema_name: str, where: str) -> Any:
    import jsonschema
    schema = json.loads((SCHEMAS / schema_name).read_text())
    errs = sorted(jsonschema.Draft202012Validator(schema).iter_errors(doc), key=lambda e: list(e.absolute_path))
    if errs:
        lines = [f"  {'/'.join(map(str, e.absolute_path)) or '(top level)'}: {e.message}" for e in errs[:12]]
        raise ConfigError(f"{where}: {len(errs)} problem(s) against cafe/schemas/{schema_name}:\n" + "\n".join(lines))
    return doc


def utc(s: str) -> dt.datetime:
    return dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)


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


def _registry(name: str, key: str) -> dict[str, Any]:
    return dict(_yaml(PLATFORMS / name)[key])


def _modem_names() -> set[str]:
    """The names a link's `modem` may take: a modems.yaml key, or "<key>_<band>" as stage 1 resolves it (case-insensitive)."""
    return {n.lower() for k, v in _registry("modems.yaml", "modems").items() for n in (k, *(f"{k}_{b}" for b in v["bands"]))}


def _klass(v: dict[str, Any]) -> str:
    """uas / usv / glider, decided as stage1._classes does."""
    kind = str(load_platform(v["platform"]).get("kind") or v["platform"]).lower()
    return "uas" if "base" in v else ("usv" if "sail" in kind or "usv" in kind else "glider")


def _check_links(m: dict[str, Any], path: pathlib.Path, nodes: set[str]) -> None:
    cls = {v["id"]: _klass(v) for v in m["vehicles"]}
    radios, modems = set(_registry("radios.yaml", "radios")), _modem_names()
    for lk in m["links"]:
        where = f"{path}: links/{lk['id']}"
        if lk["a"] == lk["b"]:
            raise ConfigError(f"{where}: a link from '{lk['a']}' to itself; give it two different ends")
        for end in ("a", "b"):
            if lk[end] not in nodes:
                raise ConfigError(f"{where}/{end}: '{lk[end]}' is not a vehicle, the ship or the shore ({sorted(nodes)})")
        need = {"rf": "radio", "acoustic": "modem"}.get(lk["kind"])
        if need and need not in lk:
            raise ConfigError(f"{where}: a {lk['kind']} link needs '{need}' (a key in platforms/{need}s.yaml)")
        if "radio" in lk and lk["radio"] not in radios:
            raise ConfigError(f"{where}/radio: '{lk['radio']}' is not in platforms/radios.yaml; use one of {sorted(radios)}")
        if "modem" in lk and lk["modem"].lower() not in modems:
            raise ConfigError(f"{where}/modem: '{lk['modem']}' is not in platforms/modems.yaml; use a key or <key>_<band>, e.g. {sorted(modems)[:3]}")
        ends = {cls.get(lk["a"]), cls.get(lk["b"])}
        if lk["kind"] == "iridium":
            if lk.get("when", "always") != "always":
                raise ConfigError(f"{where}/when: an iridium link is checked at every record, not '{lk['when']}'; use always or leave it out")
        elif "when" not in lk:
            raise ConfigError(f"{where}/when: a {lk['kind']} link needs when: always, surfacing or uas_airborne")
        elif lk["when"] == "uas_airborne" and "uas" not in ends:
            raise ConfigError(f"{where}/when: uas_airborne needs the UAS at one end of the link; use always or change a/b")
        elif lk["when"] == "surfacing" and "glider" not in ends:
            raise ConfigError(f"{where}/when: surfacing needs a glider at one end of the link; use always or change a/b")


def load_mission(path: str | pathlib.Path) -> dict[str, Any]:
    path = pathlib.Path(path)
    doc = _yaml(path)
    _unread_keys(doc, path)
    m: dict[str, Any] = validate(doc, "mission.json", str(path))
    t0, t1 = utc(m["window"]["start"]), utc(m["window"]["end"])
    if t1 <= t0:
        raise ConfigError(f"{path}: window.end {m['window']['end']} is not after window.start; swap them")
    ids = [v["id"] for v in m["vehicles"]]
    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        raise ConfigError(f"{path}: vehicle ids {sorted(dup)} appear more than once; give each vehicle its own id")
    if "ship" in m and not _in_box(m["ship"]["lon"], m["ship"]["lat"], m["box"]):
        raise ConfigError(f"{path}: ship ({m['ship']['lon']}, {m['ship']['lat']}) is outside the mission box {m['box']}; widen the box or move the ship")
    nodes = set(ids) | {m.get("ship", {}).get("id"), m.get("shore", {}).get("id")} - {None}
    for v in m["vehicles"]:
        where = f"{path}: vehicles/{v['id']}"
        if "base" in v and v["base"] != m.get("ship", {}).get("id"):
            raise ConfigError(f"{where}/base: '{v['base']}' is not the ship's id; add a ship block with that id or fix the base")
        if "deploy" in v:
            d = v["deploy"]
            if not t0 <= utc(d["time"]) < t1:
                raise ConfigError(f"{where}/deploy/time: {d['time']} is outside the window {m['window']['start']} .. {m['window']['end']}")
            pts = [(d["lon"], d["lat"])] + [tuple(p) for p in v.get("task", {}).get("waypoints", [])]
            if "lon" in v.get("task", {}):
                pts.append((v["task"]["lon"], v["task"]["lat"]))
            for lon, lat in pts:
                if not _in_box(lon, lat, m["box"]):
                    raise ConfigError(f"{where}: point ({lon}, {lat}) is outside the mission box {m['box']}; widen the box or move the point")
        load_platform(v["platform"])
        task = v.get("task", {})
        if task.get("mode") == "station" and "lon" not in task:
            raise ConfigError(f"{where}/task: mode 'station' needs lon, lat and radius_km of the station")
        if task.get("mode") == "section" and len(task.get("waypoints", [])) < 2:
            raise ConfigError(f"{where}/task: mode 'section' needs at least two waypoints: [[lon, lat], [lon, lat], ...]")
    _check_links(m, path, nodes)
    if not m["verdict"]["nogo"] < m["verdict"]["go"]:
        raise ConfigError(f"{path}: verdict.nogo ({m['verdict']['nogo']}) must be below verdict.go ({m['verdict']['go']})")
    intervals.set_thresholds(m["verdict"]["go"], m["verdict"]["nogo"])
    m["_path"] = str(path)
    return m


def load_platform(name: str | pathlib.Path) -> dict[str, Any]:
    p = pathlib.Path(name)
    path = p if p.suffix in (".yaml", ".yml") else PLATFORMS / f"{name}.yaml"
    if not path.exists():
        have = sorted(x.stem for x in PLATFORMS.glob("*.yaml"))
        raise ConfigError(f"platform '{name}': no file {path}; available: {have}")
    doc = _yaml(path)
    if not isinstance(doc, dict):
        raise ConfigError(f"{path}: expected a mapping of platform parameters")
    return doc


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
