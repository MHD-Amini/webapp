#!/bin/bash
# v16 unattended pipeline (resumable): wait for the recorder (run_v16_record.sh) to finish, then the lever grid, with
# autosave (commit + push) every 4 min.
#   nohup bash run_v16_all.sh > logs/v16_all.log 2>&1 &
# Every run writes its own json (study_results/v16_levers/<name>.json); relaunching after a crash continues where it stopped.
cd "$(dirname "$0")"
mkdir -p logs study_results/v16_levers
CSV=data/xauusd_m1.csv
[ -f "$CSV" ] || ln -sf /home/user/uploaded_files/XAUUSD.t_M1_202501020100_2026090423581112.csv "$CSV"

( while true; do sleep 240; bash save.sh "autosave v16 $(date -u +%H:%M)" ; done ) &
AUTOSAVE=$!
trap 'kill $AUTOSAVE 2>/dev/null' EXIT

# 1) streams: (re)launch the recorder if the merged streams are missing (resumable, skips finished chunks)
if [ ! -f study_results/sel_v16_M5.pkl ]; then
  if ! pgrep -f run_v16_record.sh >/dev/null; then
    echo "=== recorder (re)launched $(date -u)"
    bash run_v16_record.sh > logs/record_v16.log 2>&1
  else
    echo "=== waiting for the running recorder $(date -u)"
    while pgrep -f run_v16_record.sh >/dev/null; do sleep 60; done
  fi
fi
[ -f study_results/sel_v16_M5.pkl ] || { echo "!!! streams missing after recorder - abort"; exit 1; }

# 2) grid
echo "=== v16 grid $(date -u)"
python3 run_v16_levers.py --csv "$CSV" 2>&1 | tee logs/v16_levers.log | grep -v "^selections"
bash save.sh "v16 step 4: lever grid done"
echo "=== done $(date -u)"
