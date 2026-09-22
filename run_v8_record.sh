#!/bin/bash
# v8 step 4: re-record the M5 selection stream WITH features, in monthly CHUNKS so a sandbox migration
# loses at most ~6 minutes.  Each chunk warms the engines up from 6 weeks before its start (v7 used the same
# 6-week lead-in for the whole OOS period) and is committed + pushed on completion.  Resumable.
#   nohup bash run_v8_record.sh > logs/record_v8.log 2>&1 &
# OOS  : 2026-03-01 .. 2026-09-05 -> study_results/parts_v8/sel_v8_M5_<from>.pkl -> merged into study_results/sel_v8_M5.pkl
# IN-S : 2025-02-15 .. 2026-03-01 -> study_results/parts_v8/sel_v8is_M5_<from>.pkl -> study_results/sel_v8is_M5.pkl
cd "$(dirname "$0")"
CSV="${1:-data/xauusd_m1.csv}"
TF=M5
mkdir -p logs study_results/parts_v8
record_range () {   # $1=tag $2=from $3=to(excl)  (dates YYYY-MM-DD)
  local tag=$1 from=$2 to=$3
  local out=study_results/parts_v8/sel_${tag}_${TF}_${from}.pkl
  [ -f "$out" ] && return 0
  local warm=$(date -d "$from -42 days" +%F)
  echo "=== $tag $from -> $to (warm-up from $warm) $(date)"
  nice -n 5 python3 record_selections.py --csv "$CSV" --from "$warm" --oos "$from" --to "$to" --with-features \
      --model models/quality_model_trainonly.json --timeframes $TF --out study_results/parts_v8/sel_${tag} \
      > logs/record_${tag}_${from}.log 2>&1 || { echo "!!! FAILED $tag $from"; return 1; }
  mv study_results/parts_v8/sel_${tag}_${TF}.pkl "$out"
  bash save.sh "v8 step 4: $tag $TF chunk $from" | tail -1
}
merge () {  # $1=tag $2=final
  python3 - "$1" "$2" <<'PY'
import glob, sys, pandas as pd
tag, final = sys.argv[1], sys.argv[2]
parts = sorted(glob.glob(f"study_results/parts_v8/sel_{tag}_M5_*.pkl"))
dfs = []
for k, p in enumerate(parts):
    d = pd.read_pickle(p)
    d.loc[d.id >= 0, "id"] += k * 1_000_000        # POI ids restart in every chunk -> keep plan keys unique
    dfs.append(d)
df = pd.concat(dfs, ignore_index=True).sort_values("t", kind="stable").reset_index(drop=True)
df.to_pickle(final); print(f"merged {len(parts)} chunks -> {final}: {len(df)} events {df.t.min()} -> {df.t.max()}")
PY
}
# ---- OOS first (needed for the final backtest), monthly chunks
if [ ! -f study_results/sel_v8_${TF}.pkl ]; then
  for R in "2026-03-01 2026-04-01" "2026-04-01 2026-05-01" "2026-05-01 2026-06-01" "2026-06-01 2026-07-01" "2026-07-01 2026-08-01" "2026-08-01 2026-09-05"; do
    set -- $R; record_range v8 $1 $2 || exit 1
  done
  merge v8 study_results/sel_v8_${TF}.pkl && bash save.sh "v8 step 4: sel_v8_M5.pkl merged (OOS, with features)" | tail -1
fi
# ---- in-sample stream for filter tuning, 2-month chunks
if [ ! -f study_results/sel_v8is_${TF}.pkl ]; then
  for R in "2025-02-15 2025-04-01" "2025-04-01 2025-06-01" "2025-06-01 2025-08-01" "2025-08-01 2025-10-01" "2025-10-01 2025-12-01" "2025-12-01 2026-02-01" "2026-02-01 2026-03-01"; do
    set -- $R; record_range v8is $1 $2 || exit 1
  done
  merge v8is study_results/sel_v8is_${TF}.pkl && bash save.sh "v8 step 4: sel_v8is_M5.pkl merged (in-sample, with features)" | tail -1
fi
echo "=== V8 RECORD DONE $(date)"
