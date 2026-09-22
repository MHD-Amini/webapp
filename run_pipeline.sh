#!/bin/bash
# Full reproducible pipeline: per-TF study -> merge -> spread floor -> extra metrics -> charts
set -e
cd /home/user/webapp
CSV="${1:-/home/user/uploaded_files/XAUUSD.t_M1_202509010100_2026090423581113.csv}"
OUT="${2:-study_results}"
mkdir -p "$OUT/parts"
for TF in H1 M30 M15 M10 M5; do
  if [ ! -f "$OUT/parts/$TF/touches.pkl" ]; then
    echo "=== $TF start $(date)"
    python3 run_study.py --csv "$CSV" --out "$OUT/parts/$TF" --timeframes $TF > "$OUT/parts/$TF.log" 2>&1
    echo "=== $TF done $(date)"
  fi
done
python3 merge_parts.py "$OUT"
python3 rescore_spread.py "$OUT" 0.28
python3 add_metrics.py "$CSV" "$OUT"
python3 make_report.py --dir "$OUT" --csv "$CSV" --charts-only
echo "=== ALL DONE $(date)"
