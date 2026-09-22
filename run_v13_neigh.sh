#!/bin/bash
# v13 step 4 (session 2): neighbourhood of v13-A (10 extra variants), resumable, autosave every 4 min.
#   nohup bash run_v13_neigh.sh > logs/v13_neigh.log 2>&1 &
cd "$(dirname "$0")"
N="RG_adr0.95_tight_l03,RG_adr1.05_tight_l03,RG_adr1.0_tight_l03_w3_20,RG_adr1.0_tight_l03_w5_30,RG_adr1.0_tight_l03_w7_20,RG_adr1.0_tight_l03_w5_15,RG_adr1.0_tight_l03_10,RG_adr1.0_tight_l05,RG_adr1.0_tight_l03_front,RG_adr1.0_t2_l03"
( while true; do sleep 240; bash save.sh "v13 autosave neigh $(date -u +%H:%M)" >/dev/null 2>&1; done ) &
AS=$!
python3 run_v13_levers.py --csv data/xauusd_m1.csv --workers 1 --only "$N"
kill $AS 2>/dev/null
bash save.sh "v13 step 4: neighbourhood variants finished"
