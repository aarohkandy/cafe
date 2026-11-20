python review/round_22/q23_leaves.py /data/runs/q23 /data/runs/q24 report/credibility.json ingest/derived.digest.json 2>&1 | cut -c1-400
python review/round_22/q23_leaves.py /data/runs/q23 /data/runs/q24 report/report.json 2>&1 | grep -aA2 "/notes\|/checks" | cut -c1-300
grep -c . /data/runs/q23/report/credibility.html /data/runs/q24/report/credibility.html
