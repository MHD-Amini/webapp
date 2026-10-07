#!/bin/bash
# v16 step 5a: stress x6 of the finalists (resumable: one json per run), autosave every 4 min.
#   nohup bash run_v16_stress.sh > logs/v16_stress_all.log 2>&1 &
cd "$(dirname "$0")"
mkdir -p logs
[ -f data/xauusd_m1.csv ] || ln -sf /home/user/uploaded_files/XAUUSD.t_M1_202501020100_2026090423581112.csv data/xauusd_m1.csv
( while true; do sleep 240; bash save.sh "autosave v16 stress $(date -u +%H:%M)" ; done ) &
AUTOSAVE=$!
trap 'kill $AUTOSAVE 2>/dev/null' EXIT
FIN="${1:-M20SC_0.55_x0.4,M20SC_0.60_x0.4,M20SC_0.63_x0.4,M20SC_0.60_x0.6_KD,M20SC_0.60_x0.6,KD}"
python3 run_v16_levers.py --stress "$FIN" 2>&1 | tee logs/v16_stress.log | grep -v "^selections"
python3 walkforward_v16.py 2>&1 | tee logs/v16_walkforward.log
bash save.sh "v16 step 5a: stress x6 + walk-forward done"
echo "=== done $(date -u)"
