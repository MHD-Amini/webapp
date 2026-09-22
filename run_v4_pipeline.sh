#!/bin/bash
# v4 pipeline (resumable).  Needs the training sets: bash build_all_train.sh <CSV>
#   1. model grid v3 vs v4 features (strict train/val/test split)   -> study_results/quality_v4_model_grid.csv
#   2. final v4 model (train < Mar-26 validated + refit on everything) -> models/quality_model.json (+ _trainonly.json)
#   3. end-to-end OOS comparison closest vs v3 vs v4 (Mar 2 - Sep 4 2026, models trained < Mar 1)
cd "$(dirname "$0")"
CSV="${1:-/home/user/uploaded_files/XAUUSD.t_M1_202501020100_2026090423581112.csv}"
GBM="max_iter=400,learning_rate=0.02,max_depth=3,max_leaf_nodes=8,min_samples_leaf=200,l2_regularization=5.0"
mkdir -p logs study_results
[ -f study_results/quality_v4_model_grid.csv ] || python3 experiments_v4.py > logs/experiments_v4.log 2>&1
echo "=== GRID DONE $(date)"
[ -f models/quality_model.json ] && [ "$(python3 -c "import json;print(json.load(open('models/quality_model.json'))['meta'].get('version'))")" = "v4" ] || \
python3 train_quality.py --split 2026-03-01 --features v4 --gbm "$GBM" --bag 5 --tag v4 --final > logs/train_v4.log 2>&1
echo "=== TRAIN DONE $(date)"
# bot-level OOS run of the v4 model, one timeframe at a time (resumable)
for TF in H1 M30 M15 M10 M5; do
  [ -f study_results/compare_v4parts_${TF}_quality.pkl ] && continue
  python3 compare_modes.py --csv "$CSV" --from 2026-01-15 --oos 2026-03-01 --model models/quality_model_trainonly.json \
          --approach-model models/approach_model_trainonly.json \
          --timeframes $TF --out study_results/compare_v4parts_${TF} --only quality > logs/compare_v4_${TF}.log 2>&1
  echo "=== $TF done $(date)"
done
python3 - <<'PY'
import glob, pandas as pd
parts = [pd.read_pickle(p) for p in sorted(glob.glob("study_results/compare_v4parts_*_quality.pkl"))]
df = pd.concat(parts, ignore_index=True); df.to_pickle("study_results/compare_v4_quality.pkl"); print("merged", len(df))
PY
# summary: closest / v1 / v2 / v3 (cached) vs v4
[ -f study_results/compare_v4_closest.pkl ] || cp study_results/compare_closest.pkl study_results/compare_v4_closest.pkl
[ -f study_results/compare_v4_quality_v2.pkl ] || cp study_results/compare_quality_v2.pkl study_results/compare_v4_quality_v2.pkl
[ -f study_results/compare_v4_quality_v3.pkl ] || cp study_results/compare_quality.pkl study_results/compare_v4_quality_v3.pkl
python3 compare_modes.py --csv "$CSV" --from 2026-01-15 --oos 2026-03-01 --model models/quality_model_trainonly.json \
        --model-v3 models/v3/quality_model_trainonly.json --model-v2 models/v2/quality_model_trainonly.json \
        --out study_results/compare_v4 --summary-only > logs/compare_v4_summary.log 2>&1
echo "=== ALL DONE $(date)"
