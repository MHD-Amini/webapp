#!/bin/bash
# Run the study one timeframe at a time (memory friendly), then merge.
cd /home/user/webapp
CSV="/home/user/uploaded_files/XAUUSD.t_M1_202509010100_2026090423581113.csv"
for TF in H1 M30 M15 M10 M5; do
  if [ ! -f "study_results/parts/$TF/touches.pkl" ]; then
    echo "=== $TF start $(date)"
    python3 run_study.py --csv "$CSV" --out "study_results/parts/$TF" --timeframes $TF > "study_results/parts/$TF.log" 2>&1
    echo "=== $TF done $(date) exit $?"
  fi
done
python3 merge_parts.py
echo "=== ALL DONE $(date)"
