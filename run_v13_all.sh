#!/bin/bash
# v13 step 3: run the whole lever grid unattended, resumable (skips finished jsons), autosave every 4 minutes.
#   nohup bash run_v13_all.sh > logs/v13_all.log 2>&1 &
cd "$(dirname "$0")"
mkdir -p logs
( while true; do sleep 240; bash save.sh "v13 autosave $(date -u +%H:%M)" >/dev/null 2>&1; done ) &
AS=$!
python3 run_v13_levers.py --csv data/xauusd_m1.csv --workers 2 "$@"
kill $AS 2>/dev/null
bash save.sh "v13 step 3: grid finished ($(ls study_results/v13_levers/*.json 2>/dev/null | wc -l) jsons)"
