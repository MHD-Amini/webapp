#!/usr/bin/env python3
"""v16: record the scanner's TOP-K qualified candidates per side (not only the slot winner) so the trading simulator
can trade the 2nd-ranked zone too, and record NEW timeframes (M20) with the same walk-forward recorder.

Same walk-forward / no-look-ahead rules as record_selections.py: the ranking at bar i uses bars <= i only and is stamped
with the CLOSE time of bar i.  Output rows (one per *change* of a (side, rank) slot):
    t, tf, side (above/below), rank (1 = the slot winner = what record_selections.py recorded), event (set/clear), bar,
    price, atr, candidates (count of qualified on that side), id, type, direction, top, bottom, key_level, quality, grade,
    distance, distance_atr, created [, feats, stage with --with-features]
A rank-k slot is "set" to a POI id and "cleared" when nothing is ranked k any more.  The rank-1 rows are byte-for-byte the
record_selections.py stream (verified by the pilot / tests).  The rank-2 slot clears when the candidate that was rank 2 is
promoted to rank 1 (then it is "set" at rank 1 in the same bar), so a POI id lives in at most one slot at a time.

    python record_selections_v16.py --csv data.csv --from 2025-07-21 --oos 2025-09-01 --to 2025-10-01 \
        --model models/quality_model_trainonly.json --timeframes M10 --top-k 2 --out study_results/parts_v16/tmp_M10

Resumable: one pickle per timeframe (<out>_<TF>.pkl); existing files are skipped.
"""
from __future__ import annotations

import argparse
import os
import sys
import time

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lubot import StrategyConfig, load_mt5_csv  # noqa: E402
from lubot.engine import MultiTimeframeScanner, Selection  # noqa: E402
from record_selections import compact  # noqa: E402


def record_tf_topk(m1: pd.DataFrame, cfg: StrategyConfig, tf: str, oos: pd.Timestamp, top_k: int = 2, warmup_bars: int = 300,
                   log_every: int = 5000, with_features: bool = False) -> pd.DataFrame:
    cfg.timeframes = (tf,)
    scanner = MultiTimeframeScanner(m1, cfg)
    e = scanner.engines[tf]
    n = e.candles.n
    rows = []
    last = {(side, k): None for side in ("above", "below") for k in range(1, top_k + 1)}
    t0 = time.time()
    for _ in range(n):
        i = e.step()
        if i < warmup_bars:
            continue
        # qualified() is what select() calls (rank 1 = q[side][0] = sel.above / sel.below); computed ONCE per bar
        q = e.qualified(i)
        sel = Selection(tf=e.tf, time=str(e.candles.index[i]), price=float(e.candles.close[i]),
                        above=q["above"][0] if q["above"] else None, below=q["below"][0] if q["below"] else None,
                        range_bias=e.structure.range.bias, price_zone=e.structure.range.zone_of(float(e.candles.close[i])),
                        candidates_above=len(q["above"]), candidates_below=len(q["below"]))
        in_window = e.candles.index[i] >= oos - pd.Timedelta(days=1)
        for side in ("above", "below"):
            lst = q[side]
            for k in range(1, top_k + 1):
                d = lst[k - 1] if len(lst) >= k else None
                cur = d["id"] if d else None
                if cur != last[(side, k)]:
                    if in_window:
                        row = compact(d, side, sel, e, i, "set" if d else "clear", with_features)
                        row["rank"] = k
                        rows.append(row)
                    last[(side, k)] = cur
        if log_every and i % log_every == 0:
            print(f"  [{tf}] bar {i}/{n}  {e.candles.index[i]}  events={len(rows)}  {time.time() - t0:.0f}s", flush=True)
    df = pd.DataFrame(rows)
    if len(df):
        # chunked recording: a slot already set when the window opens must still be placed -> re-stamp the last pre-window
        # "set" of each (side, rank) to the window start
        before = df[df.t < oos]
        carry = []
        for (side, k), g in before.groupby(["side", "rank"]):
            lastrow = g.iloc[-1]
            if lastrow.event == "set":
                lastrow = lastrow.copy()
                lastrow["t"] = oos
                carry.append(lastrow)
        after = df[df.t >= oos]
        df = pd.concat([pd.DataFrame(carry), after], ignore_index=True) if carry else after.reset_index(drop=True)
        df = df.sort_values(["t", "rank"], kind="stable").reset_index(drop=True)
    print(f"[{tf}] bars={n} events={len(df)} ({time.time() - t0:.0f}s)", flush=True)
    return df


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--from", dest="start", default="2026-01-15", help="load data from here (warm-up before --oos)")
    ap.add_argument("--to", dest="end", default=None)
    ap.add_argument("--oos", default="2026-03-01", help="keep selections from this time on")
    ap.add_argument("--model", default="models/quality_model_trainonly.json")
    ap.add_argument("--mode", default="quality", help="quality | closest")
    ap.add_argument("--min-quality", type=float, default=0.50)
    ap.add_argument("--timeframes", default="H1,M30,M20,M15,M10,M5")
    ap.add_argument("--top-k", type=int, default=2)
    ap.add_argument("--out", default="study_results/sel_v16")
    ap.add_argument("--set", dest="overrides", default=None, help="extra StrategyConfig overrides key=value,...")
    ap.add_argument("--with-features", action="store_true", help="store the POI's feature dict per event (M5 trade filter)")
    a = ap.parse_args(argv)

    m1 = load_mt5_csv(a.csv)
    m1 = m1[a.start:a.end] if a.end else m1[a.start:]
    ohlc = m1[["open", "high", "low", "close", "volume"]]
    print(f"loaded {len(ohlc)} M1 bars {ohlc.index[0]} -> {ohlc.index[-1]}", flush=True)
    oos = pd.Timestamp(a.oos)
    for tf in [x.strip() for x in a.timeframes.split(",") if x.strip()]:
        path = f"{a.out}_{tf}.pkl"
        if os.path.exists(path):
            print(f"=== {tf}: {path} exists, skip", flush=True)
            continue
        cfg = StrategyConfig(selection_mode=a.mode, quality_model_path=a.model, min_quality=a.min_quality)
        if a.overrides:
            from bot import apply_overrides
            cfg = apply_overrides(cfg, a.overrides)
        df = record_tf_topk(ohlc, cfg, tf, oos, top_k=a.top_k, with_features=a.with_features)
        tmp = path + ".tmp"
        df.to_pickle(tmp)
        os.replace(tmp, path)
        print(f"=== {tf}: {len(df)} events -> {path}", flush=True)


if __name__ == "__main__":
    main()
