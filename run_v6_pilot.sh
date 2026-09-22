#!/bin/bash
# v6 step 4 pilot: rebuild ONE timeframe (M15) with the v6 feature set and compare v5 vs v6
# features on identical rows.  Resumable; commits + pushes on completion.
cd "$(dirname "$0")"
CSV="${1:-/home/user/uploaded_files/XAUUSD.t_M1_202501020100_2026090423581112.csv}"
mkdir -p models/v6 logs
if [ ! -f models/v6/train_M15.pkl ]; then
  python3 build_training_set.py --csv "$CSV" --tf M15 --out models/v6/train_M15.pkl > logs/build_v6_M15.log 2>&1 \
    && tail -2 logs/build_v6_M15.log && bash save.sh "v6 step 4: pilot training set M15 (v6 features)" \
    || { echo "!!! build failed - see logs/build_v6_M15.log"; exit 1; }
fi
python3 pilot_v6.py > logs/pilot_v6.log 2>&1 && tail -40 logs/pilot_v6.log && bash save.sh "v6 step 4: pilot evaluation M15"
