import json, pathlib
for r in ("on1", "q25"):
    rep = json.loads(pathlib.Path(f"/data/runs/{r}/report/report.json").read_text())
    def val(x): return x.get("value") if isinstance(x, dict) else x
    for kind in ("vehicles", "links"):
        for k, v in rep[kind].items():
            st = v.get("stat") or v
            print(r, kind[:-1], k, "|", val(v.get("verdict")), "| k", val(st.get("k_fail")), "n", val(st.get("n")), "p_fail", val(st.get("p_fail")), "ci", [val(st.get("lo")), val(st.get("hi"))])
ls = sorted(p.name for p in pathlib.Path("/data/runs/on1/stage3").iterdir())
print("stage3 dir:", ls[:30])
