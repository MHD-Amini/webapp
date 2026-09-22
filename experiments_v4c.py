#!/usr/bin/env python3
"""Touch-time price action: does the approach *right before the tap* predict the bounce?

For every reached training candidate the v4 approach features are recomputed at bar
``tap_i - 1`` (the last closed bar before price touched the zone) and models are trained
on  v3/v4 features (known at selection)  +  approach@tap-1.  Strict time split as before.

    python experiments_v4c.py    ->  study_results/quality_v4_touch_grid.csv, models/touch_features.pkl
"""
import time

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from lubot import StrategyConfig, load_mt5_csv
from lubot.data import resample
from lubot.engine import TimeframeEngine
from lubot.poi import POI
from lubot.quality import (FEATURE_ORDER, FEATURE_ORDER_V3, NUMERIC_V4_CONTEXT, QualityScorer, bagged_train,
                           feature_importance)
from lubot.trainset import load_training

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 40)
CSV = "/home/user/uploaded_files/XAUUSD.t_M1_202501020100_2026090423581112.csv"

meta, fx = load_training()
m1 = load_mt5_csv(CSV)[["open", "high", "low", "close", "volume"]]
cfg = StrategyConfig(selection_mode="closest", htf_confluence=False)
AP = [f for f in NUMERIC_V4_CONTEXT if f.startswith("ap_")]
cols = ["t_" + f for f in AP] + ["t_dist_atr", "t_toward_mom5", "t_bars_to_tap"]
touch = np.full((len(fx), len(cols)), np.nan, dtype=np.float32)
t0 = time.time()
for tf in sorted(meta.tf.unique()):
    e = TimeframeEngine(tf, resample(m1, tf), cfg)          # only the vectorised arrays are used
    c = e.candles
    idx = np.flatnonzero((meta.tf == tf).to_numpy())
    for j in idx:
        r = meta.iloc[j]
        i = int(r.tap_i) - 1
        if i < 5:
            continue
        bull = r.direction == "bullish"
        p = POI(0, tf, r.kind, r.direction, float(r.top), float(r.bottom), 0, 0)
        price = float(c.close[i])
        atr = float(c.atr[i])
        dist = (price - p.top) if bull else (p.bottom - price)
        f = e._approach_features(p, i, price, atr, max(dist, 0.0))
        touch[j, :len(AP)] = [f[k] for k in AP]
        touch[j, len(AP)] = dist / atr if atr > 0 else 0.0
        touch[j, len(AP) + 1] = (e._ret5[i] / atr) * (-1 if bull else 1) if atr > 0 else 0.0
        touch[j, len(AP) + 2] = float(r.tap_i - r.sel_i)
    print(tf, len(idx), f"{time.time() - t0:.0f}s", flush=True)
    del e
touch = pd.DataFrame(touch, columns=cols)
touch.to_pickle("models/touch_features.pkl")
ok = touch.notna().all(axis=1).to_numpy()
print("rows with touch features", ok.sum(), "/", len(ok))

fx2 = pd.concat([fx.reset_index(drop=True), touch], axis=1)
tr_m = (meta.sel_time < "2025-12-01").to_numpy() & ok
va_m = ((meta.sel_time >= "2025-12-01") & (meta.sel_time < "2026-03-01")).to_numpy() & ok
te_m = (meta.sel_time >= "2026-03-01").to_numpy() & ok
kinds = meta.kind.to_numpy()
y = meta.ge1.to_numpy().astype(int)
dist = fx["distance_atr"].to_numpy(dtype=float)
P = dict(max_iter=400, learning_rate=0.02, max_depth=3, max_leaf_nodes=8, min_samples_leaf=200, l2_regularization=5.0)

# univariate view of the touch features (val+test)
d = fx2[va_m | te_m].copy()
d["ge1"] = y[va_m | te_m]
print(f"\nunivariate (val+test n={len(d)}, base {d.ge1.mean():.3f}):")
for f in cols:
    x = d[f]
    if x.nunique() <= 3:
        g = d.groupby(x)["ge1"].agg(["mean", "size"])
        print(f"  {f:<22}", "  ".join(f"{k:g}:{v['mean']:.3f}(n{int(v['size'])})" for k, v in g.iterrows()))
    else:
        q = pd.qcut(x, 5, labels=False, duplicates="drop")
        g = d.groupby(q)["ge1"].mean()
        print(f"  {f:<22}", "  ".join(f"q{k}:{v:.3f}" for k, v in g.items()), f"  spread={g.max() - g.min():.3f}")


def ev(s, X, m, penalty=0.02):
    p = s.score_many(list(kinds[m]), X[m])
    dd = meta.loc[m, ["tf", "sel_i", "side", "ge1", "bounce_atr"]].copy()
    dd["p"] = p
    dd["key"] = -p + penalty * dist[m]
    best = dd.sort_values("key").groupby(["tf", "sel_i", "side"]).head(1)
    k, k6 = best[best.p >= 0.5], best[best.p >= 0.6]
    return dict(auc=round(roc_auc_score(y[m], p), 4), best=round(best.ge1.mean(), 3), p50=round(k.ge1.mean(), 3),
                kept=round(len(k) / len(best), 2), p60=round(k6.ge1.mean(), 3) if len(k6) else np.nan,
                kept60=round(len(k6) / len(best), 2))


sess = [f for f in FEATURE_ORDER if f.startswith("sess_") or f.startswith("kind_") or f == "ny_hour_raw"]
v3num = [f for f in FEATURE_ORDER_V3 if f not in sess]
v4num = [f for f in FEATURE_ORDER if f not in sess]
GRID = {"v3": FEATURE_ORDER_V3, "v4": FEATURE_ORDER,
        "v3+touchPA": v3num + cols + sess,
        "v4+touchPA": v4num + cols + sess,
        "touchPA_only+zone": ["zone_atr", "tf_minutes", "is_bull", "zone_vs_bar_range", "edge_to_key_atr"] + cols + sess}
rows = []
for name, feats in GRID.items():
    t1 = time.time()
    sc = QualityScorer(features=list(feats))
    X = sc.matrix_from_frame(fx2, list(kinds))
    s = bagged_train(X[tr_m], y[tr_m], list(kinds[tr_m]), n_models=5, gbm_params=P, scorer=sc)
    r = {"setting": name, "n_features": len(feats)}
    r.update({f"val_{k}": v for k, v in ev(s, X, va_m).items()})
    r.update({f"test_{k}": v for k, v in ev(s, X, te_m).items()})
    r["sec"] = round(time.time() - t1)
    rows.append(r)
    print(r, flush=True)
    if name == "v4+touchPA":
        idx = np.random.default_rng(0).choice(np.flatnonzero(te_m), 8000, replace=False)
        imp = feature_importance(s, X[idx], [kinds[j] for j in idx], y[idx], n_repeats=2)
        print("\ntop-20 importance (test):")
        for n, v in imp[:20]:
            print(f"  {n:<24}{v:+.4f}")
        pd.DataFrame(imp, columns=["feature", "auc_drop"]).to_csv("study_results/quality_v4_touch_importance.csv", index=False)
    del X, s
out = pd.DataFrame(rows)
out.to_csv("study_results/quality_v4_touch_grid.csv", index=False)
print(out.to_string(index=False))
