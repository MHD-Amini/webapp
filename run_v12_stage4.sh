#!/bin/bash
# v12 step 4 unattended: stress + walk-forward (resumable) with a 4-min autosave.  nohup bash run_v12_stage4.sh > logs/v12_stage4.log 2>&1 &
cd "$(dirname "$0")"; mkdir -p logs
[ -f data/xauusd_m1.csv ] || ln -sf /home/user/uploaded_files/XAUUSD.t_M1_202501020100_2026090423581112.csv data/xauusd_m1.csv
( while true; do sleep 240; bash save.sh "autosave v12 stage 4 $(date -u +%H:%M)"; done ) &
AUTOSAVE=$!; trap 'kill $AUTOSAVE 2>/dev/null' EXIT
python3 run_v12_stress.py --csv data/xauusd_m1.csv --workers 2 2>&1 | tee logs/v12_stress.log | grep -v "^selections:"
bash save.sh "v12 step 4: stress + walk-forward done"
