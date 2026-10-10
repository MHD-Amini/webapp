#!/bin/bash
# v16b step 4: stress x6 of the finalists (resumable: one json per run) + walk-forward, autosave every 4 min.
#   nohup bash run_v16b_stress.sh "name1,name2" > logs/v16b_stress_all.log 2>&1 &
cd "$(dirname "$0")"
mkdir -p logs
[ -f data/xauusd_m1.csv ] || ln -sf /home/user/uploaded_files/XAUUSD.t_M1_202501020100_2026090423581112.csv data/xauusd_m1.csv
( while true; do sleep 240; bash save.sh "autosave v16b stress $(date -u +%H:%M)" ; done ) &
AUTOSAVE=$!
trap 'kill $AUTOSAVE 2>/dev/null' EXIT
FIN="${1:?finalists comma list}"
python3 run_v16b_levers.py --stress "$FIN" 2>&1 | tee -a logs/v16b_stress.log | grep -v "^selections"
python3 walkforward_v16b.py 2>&1 | tee logs/v16b_walkforward.log
bash save.sh "v16b step 4a: stress x6 + walk-forward done"
echo "=== done $(date -u)"
