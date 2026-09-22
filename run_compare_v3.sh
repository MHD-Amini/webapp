#!/bin/bash
# End-to-end OOS comparison closest vs quality v1 / v2 / v3 (Mar 2 - Sep 4 2026, models trained < Mar 1).
# The v3 run is done per timeframe (each part cached in study_results/compare_v3parts_*) so it is resumable;
# the other modes are re-used from their cached pickles.
cd "$(dirname "$0")"
CSV="${1:-/home/user/uploaded_files/XAUUSD.t_M1_202501020100_2026090423581112.csv}"
MODEL=models/quality_model_trainonly.json
mkdir -p logs study_results
for TF in H1 M30 M15 M10 M5; do
  [ -f study_results/compare_v3parts_${TF}_quality.pkl ] && continue
  python3 compare_modes.py --csv "$CSV" --from 2026-01-15 --oos 2026-03-01 --model $MODEL --timeframes $TF \
          --out study_results/compare_v3parts_${TF} --only quality > logs/compare_v3_${TF}.log 2>&1
  echo "=== $TF done $(date)"
done
python3 - <<'PY'
import glob, pandas as pd
parts = [pd.read_pickle(p) for p in sorted(glob.glob("study_results/compare_v3parts_*_quality.pkl"))]
df = pd.concat(parts, ignore_index=True); df.to_pickle("study_results/compare_quality.pkl"); print("merged", len(df))
PY
python3 compare_modes.py --csv "$CSV" --from 2026-01-15 --oos 2026-03-01 --model $MODEL \
        --model-v1 models/v1/quality_model_trainonly.json --model-v2 models/v2/quality_model_trainonly.json \
        --summary-only > logs/compare_summary.log 2>&1
echo "=== COMPARE DONE $(date)"
