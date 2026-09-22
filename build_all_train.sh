#!/bin/bash
# Build the v5 quality-model training sets (one per timeframe) from the M1 CSV.
#   bash build_all_train.sh [CSV]     resumable: existing models/train_*.pkl are skipped;
#                                     every finished TF is committed + pushed (save.sh)
cd "$(dirname "$0")"
CSV="${1:-/home/user/uploaded_files/XAUUSD.t_M1_202501020100_2026090423581112.csv}"
mkdir -p models logs
build() {
  if [ -f models/train_$1.pkl ]; then echo "=== $1 exists, skip"; return; fi
  python3 build_training_set.py --csv "$CSV" --tf $1 --out models/train_$1.pkl > logs/build_$1.log 2>&1 \
    && tail -2 logs/build_$1.log && bash save.sh "v5 step 4: training set $1 built" \
    || echo "!!! $1 FAILED - see logs/build_$1.log"
}
# serial: the sandbox has 1 GB RAM and the M5 / M10 builds alone peak at ~500 MB
for TF in H1 M30 M15 M10 M5; do build $TF; echo "=== $TF $(date)"; done
echo "=== TRAIN SETS DONE $(date)"
