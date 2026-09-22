#!/bin/bash
# v8 step 1: label every training candidate with the v7 plan outcome (M5 first, then the other TFs).
# Resumable (per-TF outputs + .part checkpoints); each finished TF is committed + pushed.
#   nohup bash run_v8_label.sh > logs/label_v8.log 2>&1 &
cd "$(dirname "$0")"
mkdir -p logs models
for TF in M5 M10 M15 M30 H1; do
  [ -f models/plan_labels_${TF}.pkl ] && { echo "=== $TF exists, skip"; continue; }
  echo "=== $TF start $(date)"
  python3 label_plan_outcomes.py --csv data/xauusd_m1.csv --tf $TF > logs/label_v8_${TF}.log 2>&1 \
    && bash save.sh "v8 step 1: plan labels $TF" || echo "!!! $TF FAILED - see logs/label_v8_${TF}.log"
  echo "=== $TF done $(date)"
done
echo "=== V8 LABEL DONE $(date)"
