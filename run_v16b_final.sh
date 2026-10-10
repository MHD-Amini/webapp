#!/bin/bash
# v16b step 6a: final backtest (bat strings) + bat verification, then save.  Resumable: just re-run.
#   nohup bash run_v16b_final.sh > logs/v16b_final_all.log 2>&1 &
cd "$(dirname "$0")"
[ -f data/xauusd_m1.csv ] || ln -sf /home/user/uploaded_files/XAUUSD.t_M1_202501020100_2026090423581112.csv data/xauusd_m1.csv
python3 backtest_v16b_final.py --study "study_results/v16b_levers/C_F2+RS_0.5.json" 2>&1 | grep -v "^selections" | tee logs/v16b_final.log
bash save.sh "v16b step 6a: FINAL_BACKTEST_V16B.md (bat strings replayed) + final_v16b/*"
python3 verify_bat_v16b.py 2>&1 | grep -v "^selections" | tee -a logs/v16b_final.log
bash save.sh "v16b step 6a: verify_bat_v16b (bat == study json)"
echo "=== done $(date -u)"
