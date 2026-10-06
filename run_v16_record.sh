#!/bin/bash
# v16 step 2: FULL-YEAR TOP-3 selection streams (2025-09-01 .. 2026-09-05) for every timeframe + the new M20, in chunks so a
# sandbox reset loses at most a few minutes.  Resumable (existing chunk files are skipped); each chunk is committed + pushed.
#   nohup bash run_v16_record.sh > logs/record_v16.log 2>&1 &
# Chunking mirrors the v10 streams EXACTLY (so the rank-1 rows reproduce sel_v10_* and therefore v15-A byte-for-byte):
#   * Sep 2025 .. Feb 2026: monthly chunks, 6-week warm-up each (all TFs)
#   * Mar .. Sep 2026: H1/M30/M15/M10 (and M20) = ONE chunk warmed from 2026-01-15 (= the v7 recording), M5 = monthly chunks (= v8)
# Output: study_results/parts_v16/sel_v16_<TF>_<from>.pkl  ->  merged study_results/sel_v16_<TF>.pkl (ids offset per chunk)
cd "$(dirname "$0")"
CSV="${1:-data/xauusd_m1.csv}"
[ -f "$CSV" ] || ln -sf /home/user/uploaded_files/XAUUSD.t_M1_202501020100_2026090423581112.csv "$CSV"
mkdir -p logs study_results/parts_v16
MONTHS_IS="2025-09-01 2025-10-01 2025-11-01 2025-12-01 2026-01-01 2026-02-01 2026-03-01"
MONTHS_OOS="2026-03-01 2026-04-01 2026-05-01 2026-06-01 2026-07-01 2026-08-01 2026-09-05"
TOPK=3
record_range () {   # $1=TF $2=from $3=to(excl) $4=warm-up start
  local tf=$1 from=$2 to=$3 warm=$4
  local out=study_results/parts_v16/sel_v16_${tf}_${from}.pkl
  [ -f "$out" ] && return 0
  echo "=== $tf $from -> $to (warm-up from $warm) $(date)"
  nice -n 5 python3 record_selections_v16.py --csv "$CSV" --from "$warm" --oos "$from" --to "$to" --top-k $TOPK \
      --model models/quality_model_trainonly.json --timeframes $tf --out study_results/parts_v16/tmp_${tf}_${from} \
      > logs/record_v16_${tf}_${from}.log 2>&1 || { echo "!!! FAILED $tf $from"; return 1; }
  mv study_results/parts_v16/tmp_${tf}_${from}_${tf}.pkl "$out"
  bash save.sh "v16 step 2: stream $tf chunk $from" | tail -1
}
# higher TFs first (fast), M5 last (slow)
for TF in M10 M20 M15 M30 H1; do
  set -- $MONTHS_IS
  while [ $# -ge 2 ]; do record_range $TF $1 $2 $(date -d "$1 -42 days" +%F) || exit 1; shift; done
  record_range $TF 2026-03-01 2026-09-05 2026-01-15 || exit 1
done
set -- $MONTHS_IS
while [ $# -ge 2 ]; do record_range M5 $1 $2 $(date -d "$1 -42 days" +%F) || exit 1; shift; done
set -- $MONTHS_OOS
while [ $# -ge 2 ]; do record_range M5 $1 $2 $(date -d "$1 -42 days" +%F) || exit 1; shift; done
# ---- merge (ids offset per chunk, same scheme as run_v10_record.sh: k * 1_000_000 in chunk order)
python3 - <<'PY'
import glob, pandas as pd
for tf in ("H1", "M30", "M20", "M15", "M10", "M5"):
    parts = sorted(glob.glob(f"study_results/parts_v16/sel_v16_{tf}_*.pkl"))
    dfs = []
    for k, p in enumerate(parts):
        d = pd.read_pickle(p)
        d.loc[d.id >= 0, "id"] += k * 1_000_000
        dfs.append(d)
    df = pd.concat(dfs, ignore_index=True).sort_values(["t", "rank"], kind="stable").reset_index(drop=True)
    df.to_pickle(f"study_results/sel_v16_{tf}.pkl")
    print(f"{tf}: {len(parts)} chunks -> sel_v16_{tf}.pkl: {len(df)} events {df.t.min()} -> {df.t.max()} "
          f"(rank-2 set events: {int(((df['rank'] == 2) & (df.event == 'set')).sum())})")
PY
bash save.sh "v16 step 2: sel_v16_<TF>.pkl merged (full year Sep25-Sep26, top-3, + M20)"
echo "=== V16 RECORD DONE $(date)"
