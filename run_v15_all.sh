#!/bin/bash
# v15 unattended pipeline (resumable): lever grid with autosave (commit + push) every 4 min.
#   nohup bash run_v15_all.sh > logs/v15_all.log 2>&1 &
# Every run writes its own json (study_results/v15_levers/<name>.json); relaunching after a crash continues where it stopped.
cd "$(dirname "$0")"
mkdir -p logs study_results/v15_levers
CSV=data/xauusd_m1.csv
[ -f "$CSV" ] || ln -sf /home/user/uploaded_files/XAUUSD.t_M1_202501020100_2026090423581112.csv "$CSV"

( while true; do sleep 240; bash save.sh "autosave v15 grid $(date -u +%H:%M)" ; done ) &
AUTOSAVE=$!
trap 'kill $AUTOSAVE 2>/dev/null' EXIT

echo "=== v15 grid $(date -u)"
python3 run_v15_levers.py --csv "$CSV" 2>&1 | tee logs/v15_levers.log | grep -v "^selections:"
bash save.sh "v15 step 3: lever grid done"
echo "=== done $(date -u)"
