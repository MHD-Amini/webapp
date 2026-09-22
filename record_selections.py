#!/usr/bin/env python3
"""Record the bot's selection stream (what the scanner shows at EVERY closed bar) for one
or more timeframes, so the trading simulator can replay it on M1 bars.

Walk-forward, no look-ahead: the selection at bar i uses bars <= i only and is stamped
with the CLOSE time of bar i (= the first moment a live bot could act on it).

    python record_selections.py --csv data.csv --from 2026-01-15 --oos 2026-03-01 \
        --model models/quality_model_trainonly.json --timeframes M15 --out study_results/sel_v7

Resumable: one pickle per timeframe (<out>_<TF>.pkl); existing files are skipped.
Each row = one *change* of the selection on one side:
    t (close time of the bar), tf, side (above/below), event (set/clear), id, type, direction,
    top, bottom, key_level, quality, grade, atr, distance, distance_atr, price, bar (index),
    candidates
"""
from __future__ import annotations

import argparse
import os
import sys
import time

import pandas as pd

from lubot import StrategyConfig, load_mt5_csv
from lubot.engine import MultiTimeframeScanner


def compact(d, side, sel, e, i, event="set", with_features=False):
    c = e.candles
    row = {"t": c.index[i] + pd.Timedelta(minutes=e.cfg.tf_minutes(e.tf)), "tf": e.tf, "side": side,
           "event": event, "bar": int(i), "price": float(sel.price), "atr": float(c.atr[i]),
           "candidates": int(sel.candidates_above if side == "above" else sel.candidates_below)}
    if d is None:
        row.update(id=-1, type="", direction="", top=float("nan"), bottom=float("nan"), key_level=float("nan"),
                   quality=float("nan"), grade="", distance=float("nan"), distance_atr=float("nan"), created=pd.NaT)
    else:
        row.update(id=int(d["id"]), type=d["type"], direction=d["direction"], top=float(d["top"]),
                   bottom=float(d["bottom"]), key_level=float(d["key_level"]) if d.get("key_level") is not None else float("nan"),
                   quality=float(d["quality"]) if d.get("quality") is not None else float("nan"),
                   grade=d.get("grade") or "", distance=float(d["distance"]),
                   distance_atr=float(d["distance_atr"]) if d.get("distance_atr") is not None else float("nan"),
                   created=pd.Timestamp(d["time"]) if d.get("time") else pd.NaT)
        if with_features:
            # v8: the full feature vector of the selected POI (creation + selection context, as the
            # quality model sees it) so a trade filter can be scored inside the portfolio simulator
            row["feats"] = {**d.get("features", {}), **d.get("context", {})}
            row["stage"] = d.get("stage", "")
    return row


def record_tf(m1: pd.DataFrame, cfg: StrategyConfig, tf: str, oos: pd.Timestamp, warmup_bars: int = 300,
              log_every: int = 5000, with_features: bool = False) -> pd.DataFrame:
    cfg.timeframes = (tf,)
    scanner = MultiTimeframeScanner(m1, cfg)
    e = scanner.engines[tf]
    n = e.candles.n
    rows = []
    last = {"above": None, "below": None}
    t0 = time.time()
    for _ in range(n):
        i = e.step()
        if i < warmup_bars:
            continue
        sel = e.select(i)
        for side, d in (("above", sel.above), ("below", sel.below)):
            cur = d["id"] if d else None
            if cur != last[side]:
                if e.candles.index[i] >= oos - pd.Timedelta(days=1):
                    rows.append(compact(d, side, sel, e, i, "set" if d else "clear", with_features))
                last[side] = cur
        if log_every and i % log_every == 0:
            print(f"  [{tf}] bar {i}/{n}  {e.candles.index[i]}  events={len(rows)}  {time.time() - t0:.0f}s", flush=True)
    df = pd.DataFrame(rows)
    if len(df):
        # chunked recording: a POI that was already shown when the window opens must still be
        # placed by the trader -> re-stamp the last pre-window "set" of each side to the window start
        before = df[df.t < oos]
        carry = []
        for side, g in before.groupby("side"):
            lastrow = g.iloc[-1]
            if lastrow.event == "set":
                lastrow = lastrow.copy()
                lastrow["t"] = oos
                carry.append(lastrow)
        after = df[df.t >= oos]
        df = pd.concat([pd.DataFrame(carry), after], ignore_index=True) if carry else after.reset_index(drop=True)
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
    ap.add_argument("--timeframes", default="H1,M30,M15,M10,M5")
    ap.add_argument("--out", default="study_results/sel_v7")
    ap.add_argument("--set", dest="overrides", default=None, help="extra StrategyConfig overrides key=value,...")
    ap.add_argument("--with-features", action="store_true", help="v8: store the selected POI's feature dict per event")
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
        df = record_tf(ohlc, cfg, tf, oos, with_features=a.with_features)
        tmp = path + ".tmp"
        df.to_pickle(tmp)
        os.replace(tmp, path)
        print(f"=== {tf}: {len(df)} events -> {path}", flush=True)


if __name__ == "__main__":
    main()
