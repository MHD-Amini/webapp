#!/usr/bin/env python3
"""Build the *approach* training set (stage 2 of the v4 quality model).

For every reached candidate of the selection training set (models/train_*.pkl) we look at
the closed bars between its selection and its tap and keep those where price was already
within ``--near`` ATR of the zone edge (the state the bot sees while price is approaching).
Creation features are constant; the distance / approach price-action features are
recomputed at that bar; the label is the candidate's outcome after the tap (unchanged).

Rows are de-duplicated on (tf, poi id, bar) and capped to the last ``--per-poi`` near bars
before the tap.

    python build_approach_set.py --csv data.csv --out models/approach_rows.pkl
"""
import argparse
import time

import numpy as np
import pandas as pd

from lubot import StrategyConfig, load_mt5_csv
from lubot.data import resample
from lubot.engine import TimeframeEngine
from lubot.poi import POI
from lubot.quality import NUMERIC_V4_CONTEXT
from lubot.trainset import load_training

AP = [f for f in NUMERIC_V4_CONTEXT if f.startswith("ap_")]
# context features that are recomputed at the approach bar (the rest is kept from selection time)
DYN = ["distance_atr", "toward_mom5", "toward_mom20", "toward_mom60", "atr_ratio", "retrace_frac", "bars_since_extreme"] + AP


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="/home/user/uploaded_files/XAUUSD.t_M1_202501020100_2026090423581112.csv")
    ap.add_argument("--out", default="models/approach_rows.pkl")
    ap.add_argument("--near", type=float, default=2.0, help="keep bars with distance <= near ATR")
    ap.add_argument("--per-poi", type=int, default=6, help="max near bars per (poi, tap)")
    a = ap.parse_args()

    meta, fx = load_training()
    m1 = load_mt5_csv(a.csv)[["open", "high", "low", "close", "volume"]]
    cfg = StrategyConfig(selection_mode="closest", htf_confluence=False)
    t0 = time.time()
    out_meta, out_feat = [], []
    for tf in sorted(meta.tf.unique()):
        e = TimeframeEngine(tf, resample(m1, tf), cfg)
        c = e.candles
        sub = meta[meta.tf == tf]
        # one pass per (poi id, tap_i): use the earliest selection row as the feature template
        sub = sub.sort_values("sel_i")
        seen = set()
        for j, r in sub.iterrows():
            key = (int(r.id), int(r.tap_i))
            if key in seen:
                continue
            seen.add(key)
            bull = r.direction == "bullish"
            top, bottom = float(r.top), float(r.bottom)
            p = POI(0, tf, r.kind, r.direction, top, bottom, 0, 0)
            base = fx.loc[j].to_dict()
            max_away = float(base.get("away_atr", 0.0)) * float(r.atr_sel)   # in price units at selection
            ks = []
            for k in range(int(r.tap_i) - 1, int(r.sel_i) - 1, -1):
                price = float(c.close[k])
                atr = float(c.atr[k])
                dist = (price - top) if bull else (bottom - price)
                if dist <= 0:
                    continue
                if dist <= a.near * atr:
                    ks.append((k, price, atr, dist))
                if len(ks) >= a.per_poi:
                    break
            for k, price, atr, dist in ks:
                f = dict(base)
                f.update(e._approach_features(p, k, price, atr, dist))
                sgn = -1.0 if bull else 1.0
                f["distance_atr"] = dist / atr
                f["toward_mom5"] = float(e._ret5[k] / atr * sgn)
                f["toward_mom20"] = float(e._ret20[k] / atr * sgn)
                f["toward_mom60"] = float(e._ret60[k] / atr * sgn)
                f["atr_ratio"] = float(atr / e._atr_long[k]) if e._atr_long[k] > 0 else 1.0
                f["retrace_frac"] = float(min(max((max_away - dist) / max_away, -1.0), 1.5)) if max_away > 0 else 0.0
                f["bars_to_tap"] = float(int(r.tap_i) - k)
                out_feat.append(f)
                out_meta.append({"tf": tf, "id": int(r.id), "kind": r.kind, "direction": r.direction, "sel_i": int(r.sel_i),
                                 "bar_i": k, "tap_i": int(r.tap_i), "bar_time": str(c.index[k]), "sel_time": r.sel_time,
                                 "side": "below" if bull else "above", "ge1": bool(r.ge1), "ge2": bool(r.ge2),
                                 "bounce_atr": float(r.bounce_atr), "top": top, "bottom": bottom})
        print(f"[{tf}] {len(sub)} candidates -> {sum(1 for m in out_meta if m['tf'] == tf)} near rows  {time.time() - t0:.0f}s", flush=True)
        del e
    meta_out = pd.DataFrame(out_meta)
    feat_out = pd.DataFrame(out_feat).astype("float32")
    feat_out.columns = ["f__" + c for c in feat_out.columns]
    df = pd.concat([meta_out, feat_out], axis=1)
    df.to_pickle(a.out)
    print(f"{len(df)} approach rows, ge1={meta_out.ge1.mean():.3f}, {meta_out.groupby('tf').size().to_dict()} -> {a.out}")


if __name__ == "__main__":
    main()
