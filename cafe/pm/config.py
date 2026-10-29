"""Load and validate mission, platform and config files. Every refusal names the file, the field and the fix.

    load_mission(path) -> dict   (schema-checked against cafe/schemas/mission.json, then cross-checked)
    load_platform(name_or_path) -> dict
    assumptions() -> dict        (config/assumptions.yaml: every number that is a prior, not a measurement)
"""
import datetime as dt, hashlib, json, pathlib

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCHEMAS = ROOT / "cafe" / "schemas"
PLATFORMS = ROOT / "platforms"
CONFIG = ROOT / "config"


class ConfigError(ValueError):
    """A file the user wrote is wrong; the message says where and how to fix it."""


def _yaml(path):
    path = pathlib.Path(path)
    if not path.exists():
        raise ConfigError(f"{path}: file not found")
    try:
        return yaml.safe_load(path.read_text())
    except yaml.YAMLError as e:
        raise ConfigError(f"{path}: not valid YAML ({e})") from e


def validate(doc, schema_name, where):
    import jsonschema
    schema = json.loads((SCHEMAS / schema_name).read_text())
    errs = sorted(jsonschema.Draft202012Validator(schema).iter_errors(doc), key=lambda e: list(e.absolute_path))
    if errs:
        lines = [f"  {'/'.join(map(str, e.absolute_path)) or '(top level)'}: {e.message}" for e in errs[:12]]
        raise ConfigError(f"{where}: {len(errs)} problem(s) against cafe/schemas/{schema_name}:\n" + "\n".join(lines))
    return doc


def utc(s):
    return dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)


def _in_box(lon, lat, b):
    lo, hi = b["lon_min"] % 360, b["lon_max"] % 360
    x = lon % 360
    inlon = lo <= x <= hi if lo <= hi else (x >= lo or x <= hi)
    return inlon and b["lat_min"] <= lat <= b["lat_max"]


def load_mission(path):
    path = pathlib.Path(path)
    m = validate(_yaml(path), "mission.json", str(path))
    t0, t1 = utc(m["window"]["start"]), utc(m["window"]["end"])
    if t1 <= t0:
        raise ConfigError(f"{path}: window.end {m['window']['end']} is not after window.start; swap them")
    ids = [v["id"] for v in m["vehicles"]]
    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        raise ConfigError(f"{path}: vehicle ids {sorted(dup)} appear more than once; give each vehicle its own id")
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
        if task.get("mode") == "section" and not task.get("waypoints"):
            raise ConfigError(f"{where}/task: mode 'section' needs waypoints: [[lon, lat], ...]")
    for lk in m["links"]:
        for end in ("a", "b"):
            if lk[end] not in nodes:
                raise ConfigError(f"{path}: links/{lk['id']}/{end}: '{lk[end]}' is not a vehicle, the ship or the shore ({sorted(nodes)})")
        need = {"rf": "radio", "acoustic": "modem"}.get(lk["kind"])
        if need and need not in lk:
            raise ConfigError(f"{path}: links/{lk['id']}: a {lk['kind']} link needs '{need}' (a key in platforms/{need}s.yaml)")
    if not m["verdict"]["nogo"] < m["verdict"]["go"]:
        raise ConfigError(f"{path}: verdict.nogo ({m['verdict']['nogo']}) must be below verdict.go ({m['verdict']['go']})")
    m["_path"] = str(path)
    return m


def load_platform(name):
    p = pathlib.Path(name)
    path = p if p.suffix in (".yaml", ".yml") else PLATFORMS / f"{name}.yaml"
    if not path.exists():
        have = sorted(x.stem for x in PLATFORMS.glob("*.yaml"))
        raise ConfigError(f"platform '{name}': no file {path}; available: {have}")
    doc = _yaml(path)
    if not isinstance(doc, dict):
        raise ConfigError(f"{path}: expected a mapping of platform parameters")
    return doc


def assumptions():
    p = CONFIG / "assumptions.yaml"
    return _yaml(p) if p.exists() else {}


def env_sigmas():
    """1-sigma uncertainties GriddedEnv tags its values with: wind, Hs and Tp from the Stage-1 priors (perturbations.yaml),
    the rest from assumptions.yaml (env.sigma.*) until the TAO comparison replaces them."""
    pri = _yaml(CONFIG / "perturbations.yaml")
    a = assumptions()
    out = {k.split(".")[-1]: a[k]["value"] for k in a if k.startswith("env.sigma.")}
    out.update(wind_ms=pri["wind_speed_bias"]["value"], hs_frac=pri["hs_scale"]["value"], tp_s=pri["tp_bias"]["value"])
    return out


def digest(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()
