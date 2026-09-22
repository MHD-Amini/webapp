#!/bin/bash
# v6 step 5: rebuild the training sets (v6 features) for every timeframe.
#   bash build_all_train_v6.sh [CSV]   resumable (existing models/v6/train_*.pkl skipped), commit+push per TF
cd "$(dirname "$0")"
CSV="${1:-/home/user/uploaded_files/XAUUSD.t_M1_202501020100_2026090423581112.csv}"
mkdir -p models/v6 logs
build() {
  if [ -f models/v6/train_$1.pkl ]; then echo "=== $1 exists, skip"; return; fi
  python3 build_training_set.py --csv "$CSV" --tf $1 --out models/v6/train_$1.pkl > logs/build_v6_$1.log 2>&1 \
    && tail -2 logs/build_v6_$1.log && bash save.sh "v6 step 5: training set $1 built (v6 features)" \
    || echo "!!! $1 FAILED - see logs/build_v6_$1.log"
}
for TF in H1 M30 M15 M10 M5; do build $TF; echo "=== $TF $(date)"; done
echo "=== V6 TRAIN SETS DONE $(date)"
