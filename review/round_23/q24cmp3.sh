# The pages of q23 and q24, in full: every differing line of the three HTML files, untruncated, with diff's own exit status (1 = they differ, 2 = trouble).
O=/data/runs/q24cmp; mkdir -p $O
for f in index.html credibility.html; do
  diff /data/runs/q23/report/$f /data/runs/q24/report/$f > $O/$f.diff 2>&1; echo "$f diff_rc=$? lines=$(grep -c '^[<>]' $O/$f.diff)"
done
python review/round_22/q23_leaves.py /data/runs/q23 /data/runs/q24 report/credibility.json ingest/derived.digest.json > $O/leaves3.txt 2>&1; echo "leaves3_rc=$?"; cat $O/leaves3.txt
