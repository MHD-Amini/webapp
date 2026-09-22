#!/bin/bash
# resumable per-TF v4 comparison; commits + pushes each part so a sandbox reset loses nothing
cd "$(dirname "$0")"
CSV="${1:-/home/user/uploaded_files/XAUUSD.t_M1_202501020100_2026090423581112.csv}"
save() { git add "$1" && git commit -qm "$2" && timeout 60 git -c credential.helper= push -q origin HEAD:main; }
for TF in M15 M10 M5; do
  [ -f study_results/compare_v4parts_${TF}_quality.pkl ] && continue
  python3 compare_modes.py --csv "$CSV" --from 2026-01-15 --oos 2026-03-01 --model models/quality_model_trainonly.json \
          --approach-model models/approach_model_trainonly.json \
          --timeframes $TF --out study_results/compare_v4parts_${TF} --only quality > logs/compare_v4_${TF}.log 2>&1
  save study_results/compare_v4parts_${TF}_quality.pkl "v4 OOS part: $TF"
  echo "=== $TF done $(date)"
done
# single-stage v4 (selection model only) - ablation of the approach stage
for TF in H1 M30 M15 M10 M5; do
  [ -f study_results/compare_v4single_${TF}_quality.pkl ] && continue
  python3 compare_modes.py --csv "$CSV" --from 2026-01-15 --oos 2026-03-01 --model models/quality_model_trainonly.json \
          --timeframes $TF --out study_results/compare_v4single_${TF} --only quality > logs/compare_v4s_${TF}.log 2>&1
  save study_results/compare_v4single_${TF}_quality.pkl "v4 single-stage OOS part: $TF"
  echo "=== single $TF done $(date)"
done
echo "=== PARTS DONE $(date)"
