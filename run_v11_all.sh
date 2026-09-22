#!/bin/bash
# v11 unattended pipeline (resumable): lever grid A -> (grid B / combos when present) -> autosave every 4 min.
#   nohup bash run_v11_all.sh > logs/v11_all.log 2>&1 &
# Every stage skips outputs that already exist, so relaunching after a crash continues where it stopped.
cd "$(dirname "$0")"
mkdir -p logs study_results/v11_levers
CSV=data/xauusd_m1.csv
[ -f "$CSV" ] || ln -sf /home/user/uploaded_files/XAUUSD.t_M1_202501020100_2026090423581112.csv "$CSV"

# background autosave: commit + push every 4 minutes while this script runs
( while true; do sleep 240; bash save.sh "autosave v11 $(date -u +%H:%M)" ; done ) &
AUTOSAVE=$!
trap 'kill $AUTOSAVE 2>/dev/null' EXIT

echo "=== stage A: lever grid (single levers) $(date -u)"
python3 run_v11_levers.py --csv "$CSV" --workers 2 2>&1 | tee logs/v11_levers.log | grep -v "^selections:"
bash save.sh "v11 stage A: lever grid done"

if [ -f run_v11_combos.py ]; then
  echo "=== stage B: combos / new features $(date -u)"
  python3 run_v11_combos.py --csv "$CSV" --workers 2 2>&1 | tee logs/v11_combos.log | grep -v "^selections:"
  bash save.sh "v11 stage B: combos done"
fi
echo "=== done $(date -u)"
