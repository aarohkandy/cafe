# Pages split at every HTML tag, then diffed (diff, not difflib: fast on long lines); each step's own rc printed.
O=/data/runs/q25cmp
for f in index.html credibility.html; do
  for r in q24 q25; do sed 's/</\n</g' /data/runs/$r/report/$f > $O/$r.$f.seg; done
  diff $O/q24.$f.seg $O/q25.$f.seg > $O/$f.segdiff; echo "$f seg_diff_rc=$? segments=$(wc -l < $O/q25.$f.seg) differing=$(grep -c '^[<>]' $O/$f.segdiff)"
done
