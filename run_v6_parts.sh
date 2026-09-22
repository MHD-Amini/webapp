#!/bin/bash
# v6 step 7: bot-level out-of-sample walk-forward (Mar 2 - Sep 4 2026) of the v6 model, per timeframe.
# Resumable: finished parts (study_results/compare_v6parts_<TF>_quality.pkl) are skipped and each is committed.
#   bash run_v6_parts.sh [CSV]
cd "$(dirname "$0")"
CSV="${1:-/home/user/uploaded_files/XAUUSD.t_M1_202501020100_2026090423581112.csv}"
mkdir -p logs
for TF in H1 M30 M15 M10 M5; do
  [ -f study_results/compare_v6parts_${TF}_quality.pkl ] && { echo "=== $TF exists, skip"; continue; }
  python3 compare_modes.py --csv "$CSV" --from 2026-01-15 --oos 2026-03-01 --model models/quality_model_trainonly.json \
          --timeframes $TF --out study_results/compare_v6parts_${TF} --only quality > logs/compare_v6_${TF}.log 2>&1 \
    && bash save.sh "v6 step 7: bot-level OOS part $TF" || echo "!!! $TF FAILED - see logs/compare_v6_${TF}.log"
  echo "=== $TF done $(date)"
done
echo "=== V6 PARTS DONE $(date)"
