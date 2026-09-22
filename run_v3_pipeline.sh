#!/bin/bash
# v3 pipeline (resumable).  Needs the training sets: bash build_all_train.sh <CSV>
#   1. model grids (v2 vs v3 features; regularisation; bagging / weights)  -> study_results/quality_v3_model_grid*.csv
#   2. final model with the setting chosen on the validation window        -> models/quality_model.json (+ _trainonly.json)
#   3. end-to-end OOS comparison closest vs v1 vs v2 vs v3 (Mar 2 - Sep 4 2026, models trained < Mar 1)
cd "$(dirname "$0")"
CSV="${1:-/home/user/uploaded_files/XAUUSD.t_M1_202501020100_2026090423581112.csv}"
GBM="max_iter=400,learning_rate=0.02,max_depth=3,max_leaf_nodes=8,min_samples_leaf=200,l2_regularization=5.0"
mkdir -p logs
[ -f study_results/quality_v3_model_grid.csv ]   || python3 experiments_v3.py  > logs/experiments_v3.log 2>&1
[ -f study_results/quality_v3_model_grid_b.csv ] || python3 experiments_v3b.py > logs/experiments_v3b.log 2>&1
echo "=== GRIDS DONE $(date)"
python3 train_quality.py --split 2026-03-01 --features v3 --gbm "$GBM" --bag 5 --tag v3 --final > logs/train_v3.log 2>&1
echo "=== TRAIN DONE $(date)"
# re-price older cached comparisons with the imputed spread (idempotent), then run only the missing mode(s)
python3 rescore_imputed_spread.py --csv "$CSV" study_results/compare_closest.pkl study_results/compare_quality_v1.pkl \
        study_results/compare_quality_v2.pkl > logs/rescore.log 2>&1 || true
python3 compare_modes.py --csv "$CSV" --from 2026-01-15 --oos 2026-03-01 \
        --model models/quality_model_trainonly.json --model-v1 models/v1/quality_model_trainonly.json \
        --model-v2 models/v2/quality_model_trainonly.json --only quality > logs/compare_v3.log 2>&1
python3 compare_modes.py --csv "$CSV" --from 2026-01-15 --oos 2026-03-01 \
        --model models/quality_model_trainonly.json --model-v1 models/v1/quality_model_trainonly.json \
        --model-v2 models/v2/quality_model_trainonly.json --summary-only > logs/compare_summary.log 2>&1
echo "=== ALL DONE $(date)"
