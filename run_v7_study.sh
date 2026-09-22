#!/bin/bash
# v7 step 4 launcher: waits for all 5 selection streams, then runs the variant study (resumable, commits per variant).
#   nohup bash run_v7_study.sh > logs/trader_study.log 2>&1 &
cd "$(dirname "$0")"
CSV="${1:-/home/user/uploaded_files/XAUUSD.t_M1_202501020100_2026090423581112.csv}"
mkdir -p logs
while [ ! -f study_results/sel_v7_M5.pkl ]; do sleep 30; done
echo "=== all streams present $(date)"
python3 run_trader_study.py --csv "$CSV" && bash save.sh "v7 step 4: trader study complete (report + charts)"
echo "=== V7 STUDY DONE $(date)"
