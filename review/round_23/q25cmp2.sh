python review/round_22/q23_leaves.py /data/runs/q24 /data/runs/q25 2>&1 | grep -aE "^==|^  /" | sed -E 's/\[[0-9]+\]/[]/g' | sort | uniq -c | sort -rn | head -80
