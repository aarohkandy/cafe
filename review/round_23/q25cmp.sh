# q25 against q24: each step's own exit status is printed (no pipe hides it); outputs kept in /data/runs/q25cmp/ (inside ~/cafe-worker).
O=/data/runs/q25cmp; mkdir -p $O
echo "=== ledger audit"; python -m cafe.pm audit /data/runs/q25 --ledgers-only > $O/audit.txt 2>&1; echo "audit_rc=$?"; cat $O/audit.txt
echo "=== q14summary"; python review/round_14/q14summary.py q25 q24 > $O/summary.txt 2>&1; echo "summary_rc=$?"; grep -a "DIFFERS" $O/summary.txt
echo "=== pkl"; python review/round_22/q23_pkl.py /data/runs/q24 /data/runs/q25 > $O/pkl.txt 2>&1; echo "pkl_rc=$?"; cat $O/pkl.txt
echo "=== leaves"; python review/round_22/q23_leaves.py /data/runs/q24 /data/runs/q25 > $O/leaves.txt 2>&1; echo "leaves_rc=$?"; grep -a "^==" $O/leaves.txt
