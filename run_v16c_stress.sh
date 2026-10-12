#!/bin/bash
# v16c step 4b: stress x6 of the finalists (resumable: one json per run in study_results/v16c_levers/<name>__<tag>.json),
# then the judge (scenario by scenario vs the v16b-A row of v16b_stress.csv); autosave (commit + push) every 4 min.
#   nohup setsid bash run_v16c_stress.sh > logs/v16c_stress_all.log 2>&1 &
# Default finalists = the step-4a walk-forward survivors + the ramp family.  Needs the M1 CSV (restore.sh links it).
cd "$(dirname "$0")"
mkdir -p logs data
CSV=data/xauusd_m1.csv
[ -f "$CSV" ] || ln -sf /home/user/uploaded_files/XAUUSD.t_M1_202501020100_2026090423581112.csv "$CSV"
[ -f "$CSV" ] || { echo "!! no CSV - re-upload /home/user/uploaded_files/XAUUSD.t_M1_202501020100_2026090423581112.csv"; exit 1; }
( while true; do sleep 240; bash save.sh "autosave v16c stress $(date -u +%H:%M)" ; done ) &
AUTOSAVE=$!
trap 'kill $AUTOSAVE 2>/dev/null' EXIT
FIN="${1:-DDT3.5_x0.5_htf,DDT3.0_x0.5_htf,C_DDT3.5_x0.5_htf+DAY1.5_x0.5,C_DDT3.5_x0.5_htf+DAY1.5_x0.25,DDT3.0_x0.5_r2.0,C_DDT3.0_x0.5_r2.0+DAY2.0_x0.5}"
echo "=== v16c stress $(date -u)  finalists: $FIN"
python3 run_v16c_levers.py --csv "$CSV" --stress "$FIN" 2>&1 | tee -a logs/v16c_stress.log | grep -v "^selections"
python3 judge_v16c_stress.py 2>&1 | tee logs/v16c_judge.log
bash save.sh "v16c step 4b: stress x6 of the finalists + judge done"
echo "=== done $(date -u)"
