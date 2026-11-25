cd /app
python -m cafe.pm audit /data/runs/hr1 --ledgers-only > /data/runs/hr1_audit.txt 2>&1; echo "audit_rc=$?"; tail -2 /data/runs/hr1_audit.txt
python -m cafe.pm whatif --mission missions/tepex_c_demo.yaml --run /data/runs/hr1 --shift 30h > /data/runs/hr1_whatif.txt 2>&1; echo "whatif_rc=$?"; grep -a "EMULATED\|Stage 1" /data/runs/hr1_whatif.txt | cut -c1-260
python - <<'PY'
import re, pathlib
h = pathlib.Path("/data/runs/hr1/report/index.html").read_text()
i, j = h.find("<h2>Verdicts</h2>"), h.find("Vehicle or link<th>CFD<th>FEA<th>Emulator")
k = h.find("id='v-")
print("verdicts_at", i, "table_at", j, "first_card_at", k, "table_before_cards", 0 < i < j < k)
t = re.sub(r"<[^>]+>", " ", h[j:j + 1500]); print(" ".join(t.split())[:700])
for pat in ("Hull FEA (sea pressure only)", "change vs baseline model", "Refit: used", "bare hull", "hull_rans", "box"):
    m = h.find(pat); print(pat, "->", " ".join(re.sub(r"<[^>]+>", " ", h[m:m + 260]).split())[:230] if m >= 0 else "MISSING")
PY
echo "page_rc=$?"
python review/workorder/hr1read.py > /data/runs/hr1_read.txt 2>&1; echo "read_rc=$?"; cat /data/runs/hr1_read.txt
