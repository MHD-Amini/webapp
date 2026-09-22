#!/bin/bash
# v7 step 3: record the OOS selection stream (train-only v6 model, 2026-03-01 -> end) per timeframe.
# Resumable: existing study_results/sel_v7_<TF>.pkl are skipped; each finished TF is committed + pushed.
#   nohup bash run_v7_record.sh > logs/record_v7.log 2>&1 &
cd "$(dirname "$0")"
CSV="${1:-/home/user/uploaded_files/XAUUSD.t_M1_202501020100_2026090423581112.csv}"
mkdir -p logs study_results
for TF in H1 M30 M15 M10 M5; do
  [ -f study_results/sel_v7_${TF}.pkl ] && { echo "=== $TF exists, skip"; continue; }
  echo "=== $TF start $(date)"
  python3 record_selections.py --csv "$CSV" --from 2026-01-15 --oos 2026-03-01 \
      --model models/quality_model_trainonly.json --timeframes $TF --out study_results/sel_v7 > logs/record_v7_${TF}.log 2>&1 \
    && bash save.sh "v7 step 3: selection stream $TF" || echo "!!! $TF FAILED - see logs/record_v7_${TF}.log"
  echo "=== $TF done $(date)"
done
echo "=== V7 RECORD DONE $(date)"
