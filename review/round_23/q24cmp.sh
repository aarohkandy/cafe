echo "=== ledger audit"; python -m cafe.pm audit /data/runs/q24 --ledgers-only; echo "audit_rc=$?"
echo "=== q14summary"; python review/round_14/q14summary.py q24 q23 2>&1 | grep -a "DIFFERS" ; echo "summary_rc=$?"
echo "=== pkl"; python review/round_22/q23_pkl.py /data/runs/q23 /data/runs/q24
echo "=== leaves"; python review/round_22/q23_leaves.py /data/runs/q23 /data/runs/q24 2>&1 | grep -av "receipt\|sha256\|digest\|timing\|wall\|_s\"\|/t0\|/t1\|started\|ended\|elapsed\|git_sha\|path" | head -150
