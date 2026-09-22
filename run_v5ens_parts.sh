#!/bin/bash
# Bot-level out-of-sample walk-forward of the v4+v5 ENSEMBLE, one timeframe at a time.
# Resumable: finished parts (study_results/compare_v5ens_<TF>_quality.pkl) are skipped;
# each finished part is committed + pushed (save.sh) so a sandbox reset loses nothing.
#   bash run_v5_parts.sh [CSV]
cd "$(dirname "$0")"
CSV="${1:-/home/user/uploaded_files/XAUUSD.t_M1_202501020100_2026090423581112.csv}"
mkdir -p logs
for TF in H1 M30 M15 M10 M5; do
  [ -f study_results/compare_v5ens_${TF}_quality.pkl ] && { echo "=== $TF exists, skip"; continue; }
  python3 compare_modes.py --csv "$CSV" --from 2026-01-15 --oos 2026-03-01 --model "models/v4/quality_model_trainonly.json+models/quality_model_trainonly.json" \
          --timeframes $TF --out study_results/compare_v5ens_${TF} --only quality > logs/compare_v5ens_${TF}.log 2>&1 \
    && bash save.sh "v5 step 7b: ensemble OOS part $TF" || echo "!!! $TF FAILED - see logs/compare_v5ens_${TF}.log"
  echo "=== $TF done $(date)"
done
echo "=== V5 ENSEMBLE PARTS DONE $(date)"
