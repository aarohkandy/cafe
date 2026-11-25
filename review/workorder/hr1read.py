import json, pathlib
R = pathlib.Path("/data/runs/hr1"); Q = pathlib.Path("/data/runs/fin1")
j = lambda p: json.loads(p.read_text())
p = j(R / "plan.json")
print("PLAN n", p.get("n_min"), p.get("n_max"), "shares", p.get("shares"))
print("PLAN emulator", json.dumps(p.get("emulator"), default=str)[:900])
print("PLAN stage3 fs", json.dumps(p.get("stage3", {}).get("fs"), default=str)[:600])
w = j(R / "stage3" / "windows.json")
rows = w if isinstance(w, list) else [r for v in w.values() for r in (v if isinstance(v, list) else [v])] if isinstance(w, dict) and not "rows" in w else w.get("rows", [])
print("STAGE3 rows", len(rows))
for r in rows:
    if not isinstance(r, dict): continue
    print("  ", r.get("vehicle"), r.get("part"), "ok", r.get("ok"), "| cd", r.get("cd"), "cd_spread", r.get("cd_spread"), "cd_hangar", r.get("cd_hangar"), "| fea", (r.get("fea") or {}).get("run"), "|", str(r.get("error") or r.get("reason") or "")[:230])
    if r.get("part") == "hull_fs":
        print("     checks", json.dumps(r.get("checks"), default=str)[:1500]); print("     label", r.get("label"), "timing", r.get("timing"))
for f in ("refit/refit.json", "stage3/refit.json", "refit.json"):
    if (R / f).exists(): print("REFIT", f, json.dumps(j(R / f), default=str)[:1500])
s1, s1b = j(R / "stage1" / "summary.json"), j(R / "stage1b" / "summary.json")
print("refit_iterations_performed", s1b.get("refit_iterations_performed"))
q = j(Q / "stage1b" / "summary.json")
def verd(s):
    out = {}
    for kind in ("vehicles", "links"):
        for k, v in (s.get(kind) or {}).items():
            out[k] = (v.get("verdict"), v.get("k_fail", v.get("fails")), v.get("n"), v.get("p_fail"))
    return out
a, b = verd(s1b), verd(q)
for k in a: print("VERDICT", k, "hr1", a[k], "| fin1", b.get(k))
d = j(R / "emulator" / "design.json")
print("DESIGN", {k: (v if not isinstance(v, list) else len(v)) for k, v in d.items() if k in ("planned_variants", "variants", "skipped", "killed", "stage1b_free", "rows_added")})
h = j(R / "emulator" / "holdout.json")
for vid, e in h.items():
    print("HOLDOUT", vid, {k: e.get(k) for k in ("trained", "scope", "points", "stale_rows", "used", "unused_reason", "rmse", "rmse_gate", "coverage", "nominal", "coverage_chance_fail", "fresh_points", "acceptance")})
L = j(R / "checkpoints" / "emulator" / "ledger.json")
print("EMU LEDGER ok", L.get("ok"), "digest", str(L.get("code_digest"))[:16], "notes", [n[:300] for n in L.get("notes", [])][:6])
print("EMU checks", [(c.get("name"), c.get("ok"), c.get("value"), c.get("limit")) for c in L.get("checks", [])])
rep = j(R / "report" / "report.json")
print("REPORT emulator run_note", str(rep.get("emulator", {}).get("run_note"))[:600])
print("MACHINE total", json.dumps(rep.get("machine", {}).get("timing", {}).get("total"), default=str)[:400])
for vid, v in rep["vehicles"].items():
    fx = v.get("fix") or {}
    print("FIX", vid, "needed", fx.get("needed"), [(t.get("method"), str(t.get("candidate") or t.get("what"))[:60]) for t in fx.get("tried", [])][:6], "| hull_warning", str(v.get("hull_warning"))[:160])
print("CONTRIBUTION", json.dumps(rep.get("contribution"))[:1500])
for vid, v in rep["vehicles"].items():
    print("HULL_FEA", vid, json.dumps(v.get("hull_fea"), default=str)[:600])
    print("VERDICT", vid, (v.get("verdict") or {}).get("value") if isinstance(v.get("verdict"), dict) else v.get("verdict"), "k", (v.get("k_fail") or {}).get("value"), "n", (v.get("n") or {}).get("value"))
for r in rows:
    if isinstance(r, dict) and r.get("part") == "body_rans":
        print("RANS ROW ok", r.get("ok"), "cd", r.get("cd"), "spread", r.get("cd_spread"), "hangar", r.get("cd_hangar"), [(c["name"], c["value"], c["ok"]) for c in r.get("checks", [])], r.get("reasons"))
    if isinstance(r, dict) and (r.get("fea") or {}).get("run"):
        print("FEA ROW", r.get("part"), {k: r["fea"].get(k) for k in ("load", "depth_m", "utilization", "stress_utilization", "buckling_utilization")})
for r in rows:
    if isinstance(r, dict) and r.get("part") == "hull_rans":
        print("HULL_RANS ROW", json.dumps({k: v for k, v in r.items() if k != "checks"}, default=str)[:3000])
        print("HULL_RANS CHECKS", [(c["name"], c["value"], c["ok"]) for c in r.get("checks", [])])
print("TIMING", json.dumps(rep.get("machine", {}).get("timing"), default=str)[:1500])
print("USV STAGE3", json.dumps(rep["vehicles"]["usv"].get("stage3"), default=str)[:3000])
print("PLAN stage3", json.dumps({k: p["stage3"].get(k) for k in ("share_s", "fea", "rans")}, default=str)[:900], "fs.share_s", p["stage3"]["fs"].get("share_s"), "fs.fit", p["stage3"]["fs"].get("fit"))
for name in ("stage1", "stage1b"):
    s = j(R / name / "summary.json"); u = (s.get("vehicles") or {}).get("usv", {})
    print("USV", name, {k: u.get(k) for k in ("verdict", "k_fail", "fails", "n", "p_fail")}, "drag", json.dumps(u.get("drag") or s.get("drag"), default=str)[:300])
