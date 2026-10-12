#!/bin/bash
# v16c step 6a: final backtest (bat strings) + bat verification, then save.  Resumable: just re-run.  Needs the M1 CSV.
#   nohup setsid bash run_v16c_final.sh > logs/v16c_final_all.log 2>&1 &
cd "$(dirname "$0")"
mkdir -p logs data
[ -f data/xauusd_m1.csv ] || ln -sf /home/user/uploaded_files/XAUUSD.t_M1_202501020100_2026090423581112.csv data/xauusd_m1.csv
[ -f data/xauusd_m1.csv ] || { echo "!! no CSV - re-upload /home/user/uploaded_files/XAUUSD.t_M1_202501020100_2026090423581112.csv"; exit 1; }
python3 backtest_v16c_final.py 2>&1 | grep -v "^selections" | tee logs/v16c_final.log
bash save.sh "v16c step 6a: FINAL_BACKTEST_V16C.md (bat strings replayed) + final_v16c/*"
python3 verify_bat_v16c.py 2>&1 | grep -v "^selections" | tee -a logs/v16c_final.log
bash save.sh "v16c step 6a: verify_bat_v16c (bat == study json)"
echo "=== done $(date -u)"
