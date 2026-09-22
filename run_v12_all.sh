#!/bin/bash
# v12 unattended pipeline (resumable): lever grid -> combos -> autosave every 4 min.
#   nohup bash run_v12_all.sh > logs/v12_all.log 2>&1 &
# Every stage skips outputs that already exist, so relaunching after a crash continues where it stopped.
cd "$(dirname "$0")"
mkdir -p logs study_results/v12_levers
CSV=data/xauusd_m1.csv
[ -f "$CSV" ] || ln -sf /home/user/uploaded_files/XAUUSD.t_M1_202501020100_2026090423581112.csv "$CSV"

( while true; do sleep 240; bash save.sh "autosave v12 $(date -u +%H:%M)" ; done ) &
AUTOSAVE=$!
trap 'kill $AUTOSAVE 2>/dev/null' EXIT

echo "=== stage A: v12 single levers $(date -u)"
python3 run_v12_levers.py --csv "$CSV" --workers 2 2>&1 | tee logs/v12_levers.log | grep -v "^selections:"
bash save.sh "v12 stage A: single-lever grid done"

echo "=== stage B: combos $(date -u)"
python3 run_v12_levers.py --csv "$CSV" --workers 2 --combos 2>&1 | tee logs/v12_combos.log | grep -v "^selections:"
bash save.sh "v12 stage B: combos done"
echo "=== done $(date -u)"
