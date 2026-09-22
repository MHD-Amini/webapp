#!/usr/bin/env python3
"""Post-process touches.pkl with time-boxed / initial-reaction metrics (vectorised on M1).

Adds per touch:
  init_pen_zone     depth into the zone BEFORE price first bounced 0.5 ATR (the initial wick)
  pen_before_mfe    depth before the best bounce (SL-truncated path)
  bounce_1bar/3bar/12bar_atr   max bounce within 1 / 3 / 12 HTF bars of the touch (SL-truncated)
  sl_hit_within     HTF bars until SL (far edge + 0.1 ATR) was hit, NaN if never in window
  first_event       'bounce1ATR' | 'sl' | 'neither'  – which came first
"""
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from lubot import load_mt5_csv
from lubot.config import TIMEFRAME_MINUTES

csv = sys.argv[1]
d = Path(sys.argv[2] if len(sys.argv) > 2 else "study_results")
df = pickle.load(open(d / "touches.pkl", "rb"))
m1 = load_mt5_csv(csv)
idx = m1.index.values.astype("datetime64[ns]")
L, H = m1.low.to_numpy(), m1.high.to_numpy()

cols = {k: np.full(len(df), np.nan) for k in
        ["init_pen_zone", "pen_before_mfe", "bounce_1bar_atr", "bounce_3bar_atr", "bounce_12bar_atr",
         "sl_hit_within", "bounce1_within"]}
first_event = np.array(["not_reached"] * len(df), dtype=object)

for k, row in enumerate(df.itertuples()):
    if not row.reached:
        continue
    tfm = TIMEFRAME_MINUTES[row.tf]
    m0 = int(np.searchsorted(idx, np.datetime64(pd.Timestamp(row.touch_time)), side="left"))
    m1_end = min(len(idx), m0 + 300 * tfm)
    lo, hi = L[m0:m1_end], H[m0:m1_end]
    bull = row.direction == "bullish"
    edge = row.top if bull else row.bottom
    atr = row.atr_at_selection
    if bull:
        adv, fav = edge - lo, hi - edge
    else:
        adv, fav = hi - edge, edge - lo
    sl_level = row.zone_h + 0.1 * atr
    sl_hits = np.nonzero(adv >= sl_level)[0]
    sl_i = int(sl_hits[0]) if len(sl_hits) else None
    end = sl_i + 1 if sl_i is not None else len(adv)
    adv_t, fav_t = adv[:end], fav[:end]
    # bars until SL / until 1 ATR bounce
    b1 = np.nonzero(fav_t >= 1.0 * atr)[0]
    b1_i = int(b1[0]) if len(b1) else None
    cols["sl_hit_within"][k] = sl_i / tfm if sl_i is not None else np.nan
    cols["bounce1_within"][k] = b1_i / tfm if b1_i is not None else np.nan
    if b1_i is not None and (sl_i is None or b1_i < sl_i):
        first_event[k] = "bounce1ATR"
    elif sl_i is not None:
        first_event[k] = "sl"
    else:
        first_event[k] = "neither"
    # initial penetration before first 0.5 ATR bounce
    h = np.nonzero(fav_t >= 0.5 * atr)[0]
    cut = int(h[0]) + 1 if len(h) else len(adv_t)
    cols["init_pen_zone"][k] = adv_t[:cut].max() / row.zone_h if row.zone_h > 0 else np.nan
    mfe_i = int(np.argmax(fav_t)) if len(fav_t) else 0
    cols["pen_before_mfe"][k] = adv_t[:mfe_i + 1].max() / row.zone_h if row.zone_h > 0 else np.nan
    for nb in (1, 3, 12):
        seg = fav_t[: nb * tfm]
        cols[f"bounce_{nb}bar_atr"][k] = seg.max() / atr if len(seg) else np.nan

for kk, v in cols.items():
    df[kk] = v
df["first_event"] = first_event
pickle.dump(df, open(d / "touches.pkl", "wb"))
df.to_csv(d / "touches.csv", index=False)
r = df[df.reached]
print("reached", len(r))
print("init_pen_zone quantiles", r.init_pen_zone.quantile([.1, .25, .5, .75, .9]).round(2).to_dict())
print("share init_pen <=0.5:", round((r.init_pen_zone <= 0.5).mean(), 3), " <=1:", round((r.init_pen_zone <= 1).mean(), 3))
print("first_event", r.first_event.value_counts(normalize=True).round(3).to_dict())
print("bounce within 1/3/12 bars median ATR", r.bounce_1bar_atr.median().round(2), r.bounce_3bar_atr.median().round(2), r.bounce_12bar_atr.median().round(2))
print("P(bounce>=1ATR within 3 bars)", round((r.bounce_3bar_atr >= 1).mean(), 3), " 12 bars", round((r.bounce_12bar_atr >= 1).mean(), 3))
print("median bars to SL", r.sl_hit_within.median(), " to 1ATR bounce", r.bounce1_within.median())
print("orderflow_count quantiles", r.orderflow_count.quantile([.1, .25, .5, .75, .9]).to_dict())
