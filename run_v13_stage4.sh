#!/bin/bash
# v13 step 4: stress (6 scenarios) of the finalists, resumable, autosave every 4 min.   nohup bash run_v13_stage4.sh > logs/v13_stage4.log 2>&1 &
cd "$(dirname "$0")"
FIN="RG_adr1.0_tight_l03,RG_adr0.9_tight_w3_20,RG_adr1.0_tight,RG_adr1.1_three,RG_er0.2_three,RG_er0.4_G_l03_10,ref"
( while true; do sleep 240; bash save.sh "v13 autosave stage4 $(date -u +%H:%M)" >/dev/null 2>&1; done ) &
AS=$!
python3 run_v13_levers.py --csv data/xauusd_m1.csv --workers 2 --only "$FIN" --stress "$FIN"
kill $AS 2>/dev/null
bash save.sh "v13 step 4: stress runs finished"
