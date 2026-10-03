#!/bin/bash
# EURUSD selection streams for the v14-A backtest: one file per timeframe (resumable, existing files are skipped).
#   nohup bash eurusd/run_eurusd_record.sh > eurusd/logs/record.log 2>&1 &
# The v14-A trade filter needs no feature vectors (no model gate), so streams are recorded without --with-features.
cd "$(dirname "$0")"
CSV="${1:-../data/eurusd_m1.csv}"
mkdir -p logs study_results
for TF in H1 M30 M15 M10 M5; do
  [ -f "study_results/sel_eurusd_${TF}.pkl" ] && { echo "=== $TF exists, skip"; continue; }
  echo "=== $TF start $(date)"
  nice -n 5 python3 eurusd_tools.py --csv "$CSV" --timeframes "$TF" > "logs/record_${TF}.log" 2>&1 || { echo "!!! FAILED $TF"; exit 1; }
  tail -1 "logs/record_${TF}.log"
done
echo "=== EURUSD RECORD DONE $(date)"
