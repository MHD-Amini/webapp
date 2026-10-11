#!/bin/bash
# v16c unattended pipeline (resumable): single-lever grid, then the combination stage, with autosave (commit + push) every 4 min.
#   nohup bash run_v16c_all.sh > logs/v16c_all.log 2>&1 &
# Every run writes its own json (study_results/v16c_levers/<name>.json); relaunching after a crash continues where it stopped.
cd "$(dirname "$0")"
mkdir -p logs study_results/v16c_levers
CSV=data/xauusd_m1.csv
[ -f "$CSV" ] || ln -sf /home/user/uploaded_files/XAUUSD.t_M1_202501020100_2026090423581112.csv "$CSV"

( while true; do sleep 240; bash save.sh "autosave v16c $(date -u +%H:%M)" ; done ) &
AUTOSAVE=$!
trap 'kill $AUTOSAVE 2>/dev/null' EXIT

echo "=== v16c singles $(date -u)"
python3 run_v16c_levers.py --csv "$CSV" --stage singles 2>&1 | tee logs/v16c_singles.log | grep -v "^selections"
bash save.sh "v16c step 3a: single-lever grid done"
echo "=== v16c combos $(date -u)"
python3 run_v16c_levers.py --csv "$CSV" --stage combos 2>&1 | tee logs/v16c_combos.log | grep -v "^selections"
bash save.sh "v16c step 3: lever grid done (singles + combos)"
echo "=== done $(date -u)"
