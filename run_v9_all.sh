#!/bin/bash
# v9 RISK-MANAGEMENT STUDY - full pipeline, resumable, commits + pushes after every stage.
#   nohup bash run_v9_all.sh > logs/v9_all.log 2>&1 &
# Every stage skips work whose output already exists, so re-running after a crash continues where it stopped.
cd "$(dirname "$0")"
mkdir -p logs study_results/rm_study study_results/rm_insample study_results/rm_stress
export PYTHONUNBUFFERED=1
CSV=data/xauusd_m1.csv

# a background "heartbeat" saver: commits + pushes whatever finished every 4 minutes while long stages run
( while true; do sleep 240; bash save.sh "v9 autosave $(date -u +%H:%M)"; done ) &
HB=$!
trap 'kill $HB 2>/dev/null' EXIT

echo "=== stage 2: OOS grid (run_rm_study.py) $(date -u)"
python3 run_rm_study.py --csv $CSV --workers 2 2>&1 | tee -a logs/rm_study.log | grep -v "^\[" | tail -80
bash save.sh "v9 step 2: OOS grid complete (rm_study_grid.csv)"

echo "=== stage 3: in-sample replay of ALL managements (rm_insample.py) $(date -u)"
python3 rm_insample.py --csv $CSV --all 2>&1 | tee -a logs/rm_insample.log | tail -120
bash save.sh "v9 step 3: in-sample replay of top OOS variants (rm_insample.csv)"

echo "=== stage 4: stress tests of the finalists (rm_stress.py) $(date -u)"
python3 rm_stress.py --csv $CSV 2>&1 | tee -a logs/rm_stress.log | tail -80
bash save.sh "v9 step 4: stress tests (rm_stress.csv)"

echo "=== stage 5: report + charts (make_rm_report.py) $(date -u)"
python3 make_rm_report.py 2>&1 | tee -a logs/rm_report.log | tail -40
bash save.sh "v9 step 5: report tables + charts"
echo "=== ALL STAGES DONE $(date -u)"
