#!/bin/bash
# Recovery: re-create the sandbox state after a reset / new session.
#   bash restore.sh
# 1. code + models + results come from git (this repo, branch main)
# 2. the M1 CSV is the user upload (symlinked to data/xauusd_m1.csv)
# 3. PROGRESS.md tells which step to continue from
cd "$(dirname "$0")"
# origin = https://github.com/MHD-Amini/webapp (save.sh pushes there; a Genspark sb-git origin also works via $GSK_TOKEN)
echo "origin: $(git remote get-url origin 2>/dev/null | sed -E 's#^(https?://)[^@]*@#\1#')"
CSV="/home/user/uploaded_files/XAUUSD.t_M1_202501020100_2026090423581112.csv"
mkdir -p data logs models study_results
[ -f "$CSV" ] && ln -sf "$CSV" data/xauusd_m1.csv || echo "!! CSV not found at $CSV - re-upload it"
pip install -q scikit-learn lightgbm 2>/dev/null || true
python3 -m pytest tests -q 2>&1 | tail -1
echo "--- next step (PROGRESS.md):"; grep -m1 "^- \[ \]" PROGRESS.md
echo "--- v14 (all complete): python3 verify_bat_v14.py (bat == study), python3 backtest_v14_final.py (FINAL BACKTEST -> study_results/FINAL_BACKTEST_V14.md), python3 walkforward_v14.py, python3 make_v14_report.py; grid: python3 run_v14_levers.py [--stress names] (resumable), python3 shuffle_v14.py"
ls study_results/v14_levers/*.json 2>/dev/null | wc -l | sed 's/^/    v14 runs on disk: /'
echo "--- v13 (all complete): python3 verify_bat_v13.py (bat == study), python3 walkforward_v13.py, python3 make_v13_report.py; grid pieces: bash run_v13_all.sh / run_v13_stage4.sh / run_v13_neigh.sh (resumable)"
ls study_results/v13_levers/*.json 2>/dev/null | wc -l | sed 's/^/    v13 runs on disk: /'
echo "--- v12 (all complete): re-run pieces if needed - nohup bash run_v12_all.sh (grid) / bash run_v12_stage4.sh (stress) / python3 rank_v12.py / python3 make_v12_report.py"
ls study_results/v12_levers/*.json 2>/dev/null | wc -l | sed 's/^/    v12 runs on disk: /'
echo "--- v8 long jobs (resumable, run in background):"
echo "    nohup bash run_v8_label.sh > logs/label_v8.log 2>&1 &            # plan-outcome labels (skips finished TFs)"
ls models/plan_labels_*.pkl 2>/dev/null | sed 's/^/    have: /'
echo "--- v7 long jobs (resumable, run in background):"
echo "    nohup bash run_v7_record.sh > logs/record_v7.log 2>&1 &        # selection streams (skips finished TFs)"
echo "    nohup python3 run_trader_study.py --csv data/xauusd_m1.csv > logs/trader_study.log 2>&1 &   # variants (skips finished)"
ls study_results/sel_v7_*.pkl 2>/dev/null | sed 's/^/    have: /'
ls study_results/trader_v7_var_*.json 2>/dev/null | wc -l | sed 's/^/    trader variants done: /'
