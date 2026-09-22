#!/bin/bash
# v8 step 6: filter grid with the real portfolio simulator.  Resumable (finished variants skipped), commits after each set.
#   nohup bash run_v8_study.sh > logs/v8_study.log 2>&1 &
cd "$(dirname "$0")"
mkdir -p logs
if [ -f study_results/sel_v8_M5.pkl ]; then
  nice -n 3 python3 run_filter_study.py --set oos >> logs/filter_study_oos.log 2>&1; bash save.sh "v8 step 6: filter study OOS" | tail -1
fi
if [ -f study_results/sel_v8is_M5.pkl ]; then
  nice -n 3 python3 run_filter_study.py --set insample >> logs/filter_study_insample.log 2>&1; bash save.sh "v8 step 6: filter study in-sample" | tail -1
fi
echo "=== V8 STUDY DONE $(date)"
