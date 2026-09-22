#!/usr/bin/env python3
"""Build the quality-model training set.

Walk forward through one timeframe in *closest* mode (no model), and every
``sample_every`` bars record ALL qualifying candidates (above & below) with
their creation + context features.  Each candidate is then scored with the
future: did price bounce >= 1 ATR from the zone edge before violating the far
edge (+0.1 ATR)?  A candidate is only recorded once (first time it qualifies).

    python build_training_set.py --csv data.csv --tf M15 --out models/train_M15.pkl
"""
import argparse
import pickle
import time
from pathlib import Path

import numpy as np
import pandas as pd

from lubot import StrategyConfig, load_mt5_csv
from lubot.config import TIMEFRAME_MINUTES
from lubot.data import Candles, resample
from lubot.engine import MultiTimeframeScanner, TimeframeEngine
from lubot.quality import NUMERIC


def score(row, c, m1a, tfm, wait=300, hold=300):
    bull = row["direction"] == "bullish"
    edge = row["top"] if bull else row["bottom"]
    far = row["bottom"] if bull else row["top"]
    i0 = row["sel_i"] + 1
    tap = None
    for i in range(i0, min(c.n, i0 + wait)):
        if (bull and c.low[i] <= edge) or (not bull and c.high[i] >= edge):
            tap = i
            break
    if tap is None:
        return None
    atr = float(c.atr[tap])
    idx = m1a["index"]
    m0 = int(np.searchsorted(idx, np.datetime64(c.index[tap]), side="left"))
    seg_end = int(np.searchsorted(idx, np.datetime64(c.index[tap]) + np.timedelta64(tfm, "m"), side="left"))
    lows, highs = m1a["low"], m1a["high"]
    hit = (lows[m0:seg_end] <= edge) if bull else (highs[m0:seg_end] >= edge)
    m_touch = m0 + int(np.argmax(hit)) if hit.any() else m0
    m_end = min(len(idx), m_touch + hold * tfm)
    lo, hi = lows[m_touch:m_end], highs[m_touch:m_end]
    adv = edge - lo if bull else hi - edge
    fav = hi - edge if bull else edge - lo
    sl_i = np.nonzero(adv >= (row["top"] - row["bottom"]) + 0.1 * atr)[0]
    end = sl_i[0] + 1 if len(sl_i) else len(adv)
    mfe = fav[:end].max() if end > 0 else 0.0
    b1 = np.nonzero(fav[:end] >= atr)[0]
    bounce_first = bool(len(b1)) and (not len(sl_i) or b1[0] < sl_i[0])
    zone_h = row["top"] - row["bottom"]
    # how deep did price go into the zone before the 1-ATR bounce (or before SL)?
    pen_end = b1[0] + 1 if len(b1) else end
    pen = float(adv[:pen_end].max()) if pen_end > 0 else 0.0
    # "clean" bounce: >= 1 ATR before violation AND price never traded through the far edge
    ge1_clean = bool(mfe >= atr) and pen <= zone_h
    # bounce of at least half an ATR (useful for small targets)
    b05 = np.nonzero(fav[:end] >= 0.5 * atr)[0]
    ge05 = bool(len(b05))
    return {"reached": True, "tap_i": tap, "bounce_atr": mfe / atr, "ge1": bool(mfe >= atr),
            "ge2": bool(mfe >= 2 * atr), "ge05": ge05, "ge1_clean": ge1_clean,
            "pen_zone": pen / zone_h if zone_h > 0 else 0.0, "pen_atr": pen / atr,
            "bounce_first": bounce_first, "atr_tap": atr, "bars_to_reach": int(tap - row["sel_i"])}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--csv", required=True)
    p.add_argument("--tf", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--sample-every", type=int, default=0, help="0 = auto (~12k sample points)")
    p.add_argument("--resample-bars", type=int, default=25, help="a POI may be re-recorded every N bars while alive")
    p.add_argument("--warmup", type=int, default=300)
    p.add_argument("--start", default=None, help="drop M1 data before this timestamp")
    p.add_argument("--no-htf", action="store_true", help="disable HTF confluence features")
    a = p.parse_args()

    cfg = StrategyConfig(timeframes=(a.tf,), selection_mode="closest", htf_confluence=not a.no_htf)
    m1 = load_mt5_csv(a.csv)
    if a.start:
        m1 = m1[pd.Timestamp(a.start):]
    ohlc = m1[["open", "high", "low", "close", "volume"]]
    # the scanner wires the higher-timeframe helper engine (HTF confluence features)
    e = MultiTimeframeScanner(ohlc, cfg).engines[a.tf]
    m1a = {"index": ohlc.index.values.astype("datetime64[ns]"), "low": ohlc.low.to_numpy(), "high": ohlc.high.to_numpy()}
    tfm = TIMEFRAME_MINUTES[a.tf]
    seen = set()
    rows = []
    feat_names = None            # fixed column order, learned from the first candidate
    feat_rows = []               # one float32 array per candidate (memory-lean: no dict per row)
    t0 = time.time()
    n = e.candles.n
    every = a.sample_every or max(1, n // 12000)
    for _ in range(n):
        i = e.step()
        if i < a.warmup or i % every:
            continue
        q = e.qualified(i)
        for side in ("above", "below"):
            for rank, d in enumerate(q[side]):
                key = (d["id"], i // a.resample_bars)
                if key in seen:
                    continue
                seen.add(key)
                f = {**d["features"], **d["context"]}
                if feat_names is None:
                    # fixed column set: every model feature (all POI types) + whatever this candidate carries
                    feat_names = sorted(set(NUMERIC) | set(f) | {"ny_hour", "atr"})
                feat_rows.append(np.fromiter((float(f.get(k, 0.0) or 0.0) for k in feat_names), dtype=np.float32, count=len(feat_names)))
                rows.append({"tf": a.tf, "id": d["id"], "kind": d["type"], "direction": d["direction"],
                             "top": d["top"], "bottom": d["bottom"], "sel_i": i, "sel_time": str(e.candles.index[i]),
                             "price": float(e.candles.close[i]), "atr_sel": float(e.candles.atr[i]),
                             "rank": rank, "n_side": len(q[side]), "closest": rank == 0})
    print(f"[{a.tf}] {n} bars, {len(rows)} candidates in {time.time() - t0:.0f}s; scoring...", flush=True)
    for r in rows:
        s = score(r, e.candles, m1a, tfm)
        if s is None:
            r.update(reached=False)
        else:
            r.update(s)
    # flat, compact layout: one float32 column per feature (prefix f__) instead of a dict per row
    feats = pd.DataFrame(np.vstack(feat_rows) if feat_rows else np.zeros((0, 0), dtype=np.float32),
                         columns=["f__" + c for c in (feat_names or [])])
    del feat_rows
    df = pd.concat([pd.DataFrame(rows), feats], axis=1)
    del rows, feats
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    df.to_pickle(a.out)
    rr = df[df.reached == True]
    print(f"[{a.tf}] reached {len(rr)}/{len(df)}  ge1={rr.ge1.mean():.3f}  bounce_first={rr.bounce_first.mean():.3f}  "
          f"closest-only ge1={rr[rr.closest].ge1.mean():.3f} (n={rr.closest.sum()})")


if __name__ == "__main__":
    main()
