"""Check a fleet from one file: upload each design (CAD + numbers), wait for it to be characterized, fly the
deployment, print the verdicts.   python3 lab/check.py lab/fleet.json

A design is re-used, not re-characterized, while its file and numbers are unchanged (matched by a hash kept in
the design's note), so the second run goes straight to the deployment. Standard library only.
"""
import hashlib, json, os, pathlib, sys, time, urllib.error, urllib.request, uuid

API = os.environ.get("CAFE_API", "http://100.108.213.121:8740")


def call(method, path, body=None, headers=None):
    if isinstance(body, dict):
        body, headers = json.dumps(body).encode(), {"content-type": "application/json"}
    for attempt in range(20):           # characterizing takes an hour; ride out Wi-Fi/Tailscale drops meanwhile
        try:
            with urllib.request.urlopen(urllib.request.Request(API + path, body, headers or {}, method=method), timeout=120) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            sys.exit(f"{method} {path}: {json.loads(e.read()).get('detail', e.reason)}")
        except (urllib.error.URLError, OSError) as e:
            if method == "POST" and path == "/api/designs" or attempt == 19:   # a retried upload could make a duplicate
                sys.exit(f"can't reach {API} ({e}); is Tailscale up?")
            time.sleep(15)


def notes_out(x):
    """Drop the _ keys the template uses for notes."""
    if isinstance(x, dict):
        return {k: notes_out(v) for k, v in x.items() if not k.startswith("_")}
    return [notes_out(v) for v in x] if isinstance(x, list) else x


def design_id(key, spec, here, existing):
    spec = dict(spec, name=spec.get("name", key))
    f = here / spec.pop("file") if "file" in spec else None
    cad = f.read_bytes() if f else None
    tag = "fleet " + hashlib.sha256((cad or b"") + json.dumps(spec, sort_keys=True).encode()).hexdigest()[:12]
    for d in existing:
        if d["name"] == spec["name"] and not d.get("sample") and d["status"] != "failed" \
                and (call("GET", f"/api/designs/{d['id']}")["spec"] or {}).get("note") == tag:
            print(f"{key}: unchanged, using {d['id']}")
            return d["id"]
    spec["note"] = tag
    if cad is None:                     # a simple shape: {"shape": "torpedo", "dims": {...}, ...numbers}
        shape, dims = spec.pop("shape"), spec.pop("dims", {})
        d = call("POST", "/api/designs/shape", dict(shape=shape, dims=dims, spec=spec))
    else:
        b = uuid.uuid4().hex
        body = (f"--{b}\r\nContent-Disposition: form-data; name=\"spec\"\r\n\r\n{json.dumps(spec)}\r\n"
                f"--{b}\r\nContent-Disposition: form-data; name=\"mesh\"; filename=\"{f.name}\"\r\n"
                f"Content-Type: application/octet-stream\r\n\r\n").encode() + cad + f"\r\n--{b}--\r\n".encode()
        d = call("POST", "/api/designs", body, {"content-type": f"multipart/form-data; boundary={b}"})
        if d.get("units_assumed"):
            print(f"{key}: units guessed as {d['units_assumed']} ({max(d['extents']):.2f} m long); set \"units\" if that's wrong")
    print(f"{key}: uploaded as {d['id']}, characterizing (CFD + FEA; tens of minutes for a sub or quad, hours for a boat)")
    return d["id"]


def wait_designs(ids):
    last = None
    while True:
        ds = {k: call("GET", f"/api/designs/{i}") for k, i in ids.items()}
        for k, d in ds.items():
            if d["status"] == "failed":
                sys.exit(f"{k} failed: {'; '.join(d.get('errors') or ['see its log in the Hangar'])}")
        line = "  ".join(f"{k}: {'ready' if d['status'] == 'done' else d.get('step') or d['status']}" for k, d in ds.items())
        if line != last:
            print(time.strftime("%H:%M"), line, flush=True)
            last = line
        if all(d["status"] == "done" for d in ds.values()):
            for k, d in ds.items():
                for w in d.get("warnings") or []:
                    print(f"  note on {k}: {w}")
            return
        time.sleep(30)


def pct(r):
    lo, hi = r.get("p_interval") or (None, None)
    return f"{r['p_success']:.0%} of runs" + (f" (90% sure: {lo:.0%}-{hi:.0%})" if lo is not None else "")


if __name__ == "__main__":
    path = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else pathlib.Path(__file__).with_name("fleet.json"))
    fleet = notes_out(json.loads(path.read_text()))
    specs, mission = fleet.get("designs", {}), fleet["deployment"]
    existing = call("GET", "/api/designs")
    ids = {k: design_id(k, s, path.parent, existing) for k, s in specs.items()}
    if ids:
        wait_designs(ids)
    for d in mission["drones"]:
        d["design"] = ids.get(d["design"], d["design"])
    mid = call("POST", "/api/missions", mission)["id"]
    print(f"flying the deployment ({mid}) ...", flush=True)
    while (m := call("GET", f"/api/missions/{mid}"))["status"].get("state") not in ("done", "failed"):
        time.sleep(10)
    if m["status"]["state"] == "failed":
        sys.exit(f"the simulation failed: {m['status'].get('error')}")
    res = m["result"]
    print(f"\n{mission.get('name', 'deployment')}: {res['fleet']['verdict']}  ({pct(res['fleet'])})")
    for w in res.get("warnings") or []:
        print(f"  note: {w}")
    for lk in res.get("links") or []:
        print(f"\n  {lk['a']} <-> {lk['b']} within {lk['max_m']} m: {lk['verdict']}  ({pct(lk)})")
        print(f"    in range {lk['in_range_p50']:.0%} of the time typically; peak separation {lk['max_sep_m_p50']:.0f} m")
        for a in lk.get("advice") or []:
            print(f"    to pass: {a}")
    for i, r in res["drones"].items():
        why = "; ".join(f"{x['reason']} ({x['share']:.0%})" for x in r["reasons"][:2]) or "did its job in every run"
        print(f"\n  {i}: {r['verdict']}  ({pct(r)})  battery left {r['battery_left_p50']:.0%}")
        print(f"    {why}")
        for a in r.get("advice") or []:
            print(f"    to pass: {a}")
    print(f"\nSee it on the map: {API}/?mission={mid}#plan")
