#!/bin/bash
# v10 MULTI-TP + FULL-YEAR pipeline - resumable, commits + pushes after every stage and every 4 minutes.
#   nohup bash run_v10_all.sh > logs/v10_all.log 2>&1 &
# Stages skip work whose output already exists (one json per variant), so re-running after a crash continues.
cd "$(dirname "$0")"
mkdir -p logs study_results/v10_study study_results/v10_insample study_results/v10_year
export PYTHONUNBUFFERED=1
CSV=data/xauusd_m1.csv
W=${WORKERS:-1}          # 2 cores: 1 worker while the recorder runs, 2 afterwards

( while true; do sleep 240; bash save.sh "v10 autosave $(date -u +%H:%M)"; done ) &
HB=$!
trap 'kill $HB 2>/dev/null' EXIT

echo "=== stage 5a: OOS multi-TP grid (run_v10_study.py --mode oos) $(date -u)"
python3 run_v10_study.py --mode oos --csv $CSV --workers $W 2>&1 | tee -a logs/v10_study_oos.log | grep -v "^\[" | tail -90
bash save.sh "v10 step 5a: OOS multi-TP grid complete (v10_study_grid.csv)"

echo "=== stage 5b: in-sample replay of the multi-TP grid (run_v10_study.py --mode is) $(date -u)"
python3 run_v10_study.py --mode is --csv $CSV --workers $W 2>&1 | tee -a logs/v10_study_is.log | grep -v "^\[" | tail -60
bash save.sh "v10 step 5b: in-sample multi-TP grid complete (v10_insample.csv)"

# stage 1 must be finished (sel_v10_<TF>.pkl) before the full-year backtest
while [ ! -f study_results/sel_v10_M5.pkl ]; do echo "waiting for sel_v10_M5.pkl (recorder) $(date -u +%H:%M)"; sleep 120; done

if [ -f run_v10_year.py ]; then
  echo "=== stage 6: full-year backtest (run_v10_year.py) $(date -u)"
  python3 run_v10_year.py --csv $CSV 2>&1 | tee -a logs/v10_year.log | tail -120
  bash save.sh "v10 step 6: full-year backtest complete"
fi
if [ -f make_v10_report.py ]; then
  echo "=== stage 7: report (make_v10_report.py) $(date -u)"
  python3 make_v10_report.py 2>&1 | tee -a logs/v10_report.log | tail -40
  bash save.sh "v10 step 7: report + charts"
fi
echo "=== V10 PIPELINE DONE $(date -u)"
