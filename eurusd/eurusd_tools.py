#!/usr/bin/env python3
"""EURUSD adapter + selection recorder for the single-file v14 bot.

The bot (detectors, features, slippage, rounding to 3 decimals) was written for a
2-digit ~3500$ instrument.  EURUSD is fed IN PIPS (price x 10 000 -> 11 696.1) so that
every component sees a gold-like magnitude:  1 unit = 1 pip, point = 0.1 pip,
1 lot = 10 $/pip (100 000 EUR), round-turn commission 7 $/lot (raw account).
"""
from __future__ import annotations

import argparse
import os
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lubot_trader_v14_single as lu  # noqa: E402

PIP_SCALE = 10_000.0            # 1 price unit after scaling = 1 pip
POINT_PIPS = 0.1                # MT5 5-digit point = 0.1 pip
HERE = os.path.dirname(os.path.abspath(__file__))
CSV = os.path.join(HERE, "..", "data", "eurusd_m1.csv")


def eurusd_spec(commission: float = 7.0) -> "lu.SymbolSpec":
    """SymbolSpec for EURUSD expressed in pips (see module doc)."""
    return lu.SymbolSpec(symbol="EURUSD.r", digits=1, point=POINT_PIPS, contract_size=10.0,
                         volume_min=0.01, volume_max=100.0, volume_step=0.01, stops_level_points=0,
                         commission_per_lot=commission, swap_long_per_lot=-7.0, swap_short_per_lot=2.0,
                         swap_triple_weekday=2, leverage=100.0, currency="USD")


def load_eurusd(csv: str = CSV, start: str | None = None, end: str | None = None) -> pd.DataFrame:
    """MT5 EURUSD M1 export -> frame in pips (OHLC x 10 000, spread in pips)."""
    m1 = lu.load_mt5_csv(csv, point_value=POINT_PIPS)      # spread: points -> pips
    for c in ("open", "high", "low", "close"):
        m1[c] = m1[c] * PIP_SCALE
    if start:
        m1 = m1[start:]
    if end:
        m1 = m1[:end]
    return m1


# ---------------------------------------------------------------- recorder (= record_selections.py)
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
            row["feats"] = {**d.get("features", {}), **d.get("context", {})}
            row["stage"] = d.get("stage", "")
    return row


def record_tf(m1: pd.DataFrame, cfg: "lu.StrategyConfig", tf: str, oos: pd.Timestamp, warmup_bars: int = 300,
              log_every: int = 5000, with_features: bool = False) -> pd.DataFrame:
    cfg.timeframes = (tf,)
    scanner = lu.MultiTimeframeScanner(m1, cfg)
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
    ap.add_argument("--csv", default=CSV)
    ap.add_argument("--from", dest="start", default=None)
    ap.add_argument("--to", dest="end", default=None)
    ap.add_argument("--oos", default="2025-09-01")
    ap.add_argument("--model", default=os.path.join(HERE, "models", "quality_model.json"))
    ap.add_argument("--min-quality", type=float, default=0.50)
    ap.add_argument("--timeframes", default="H1,M30,M15,M10,M5")
    ap.add_argument("--out", default=os.path.join(HERE, "study_results", "sel_eurusd"))
    ap.add_argument("--set", dest="overrides", default=None)
    ap.add_argument("--with-features", action="store_true")
    a = ap.parse_args(argv)
    lu._materialize(["models/quality_model.json"])
    m1 = load_eurusd(a.csv, a.start, a.end)
    ohlc = m1[["open", "high", "low", "close", "volume"]]
    print(f"loaded {len(ohlc)} M1 bars {ohlc.index[0]} -> {ohlc.index[-1]} (pips, close {ohlc.close.iloc[-1]:.1f})", flush=True)
    oos = pd.Timestamp(a.oos)
    for tf in [x.strip() for x in a.timeframes.split(",") if x.strip()]:
        path = f"{a.out}_{tf}.pkl"
        if os.path.exists(path):
            print(f"=== {tf}: {path} exists, skip", flush=True)
            continue
        cfg = lu.StrategyConfig(symbol="EURUSD.r", selection_mode="quality", quality_model_path=a.model, min_quality=a.min_quality)
        if a.overrides:
            cfg = lu.apply_overrides(cfg, a.overrides)
        df = record_tf(ohlc, cfg, tf, oos, with_features=a.with_features)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        df.to_pickle(tmp)
        os.replace(tmp, path)
        print(f"=== {tf}: {len(df)} events -> {path}", flush=True)


if __name__ == "__main__":
    main()
