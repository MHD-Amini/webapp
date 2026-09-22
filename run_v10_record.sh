#!/bin/bash
# v10 step 1: FULL-YEAR selection streams (2025-09-01 .. 2026-09-05) for every timeframe, in monthly chunks so a
# sandbox migration loses at most a few minutes.  Each chunk warms the engines up from 6 weeks before its start and
# is committed + pushed on completion.  Resumable (existing chunk files are skipped).
#   nohup bash run_v10_record.sh > logs/record_v10.log 2>&1 &
# The Mar-Sep 2026 M5 chunks already exist (parts_v8, with features) and are reused; the other TFs' Mar-Sep 2026
# streams exist as sel_v7_<TF>.pkl (whole period, same recorder) and are reused as one "chunk".
# Output: study_results/sel_v10_<TF>.pkl  (M5 carries the v8 feature dicts, needed by the M5 trade filter)
cd "$(dirname "$0")"
CSV="${1:-data/xauusd_m1.csv}"
mkdir -p logs study_results/parts_v10
MONTHS="2025-09-01 2025-10-01 2025-11-01 2025-12-01 2026-01-01 2026-02-01 2026-03-01"
record_range () {   # $1=TF $2=from $3=to(excl) $4=extra flags
  local tf=$1 from=$2 to=$3 extra=$4
  local out=study_results/parts_v10/sel_v10_${tf}_${from}.pkl
  [ -f "$out" ] && return 0
  local warm=$(date -d "$from -42 days" +%F)
  echo "=== $tf $from -> $to (warm-up from $warm) $(date)"
  nice -n 5 python3 record_selections.py --csv "$CSV" --from "$warm" --oos "$from" --to "$to" $extra \
      --model models/quality_model_trainonly.json --timeframes $tf --out study_results/parts_v10/tmp_${tf}_${from} \
      > logs/record_v10_${tf}_${from}.log 2>&1 || { echo "!!! FAILED $tf $from"; return 1; }
  mv study_results/parts_v10/tmp_${tf}_${from}_${tf}.pkl "$out"
  bash save.sh "v10 step 1: stream $tf chunk $from" | tail -1
}
# higher TFs first (fast), M5 last (slow, with features)
for TF in H1 M30 M15 M10; do
  set -- $MONTHS
  while [ $# -ge 2 ]; do record_range $TF $1 $2 "" || exit 1; shift; done
done
set -- $MONTHS
while [ $# -ge 2 ]; do record_range M5 $1 $2 "--with-features" || exit 1; shift; done
# ---- merge: new in-sample chunks + existing OOS streams
python3 - <<'PY'
import glob, pandas as pd
from backtest_trader import load_selections
for tf in ("H1", "M30", "M15", "M10", "M5"):
    parts = sorted(glob.glob(f"study_results/parts_v10/sel_v10_{tf}_*.pkl"))
    if tf == "M5":
        parts += sorted(glob.glob("study_results/parts_v8/sel_v8_M5_*.pkl"))
    dfs = []
    for k, p in enumerate(parts):
        d = pd.read_pickle(p)
        d.loc[d.id >= 0, "id"] += k * 1_000_000        # POI ids restart in every chunk -> unique plan keys
        dfs.append(d)
    if tf != "M5":
        d = pd.read_pickle(f"study_results/sel_v7_{tf}.pkl")
        d.loc[d.id >= 0, "id"] += (len(parts)) * 1_000_000
        dfs.append(d[d.t >= "2026-03-01"])
    df = pd.concat(dfs, ignore_index=True).sort_values("t", kind="stable").reset_index(drop=True)
    df.to_pickle(f"study_results/sel_v10_{tf}.pkl")
    print(f"{tf}: {len(parts)} new chunks -> sel_v10_{tf}.pkl: {len(df)} events {df.t.min()} -> {df.t.max()}")
PY
bash save.sh "v10 step 1: sel_v10_<TF>.pkl merged (full year Sep25-Sep26)" | tail -1
echo "=== V10 RECORD DONE $(date)"
