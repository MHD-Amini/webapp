#!/usr/bin/env python3
"""Approach-stage model: score the zone when price is already close (<= 2 ATR).

Rows = models/approach_rows.pkl (build_approach_set.py).  Strict split on the *selection*
time of the candidate: train < 2025-12-01 · val Dec-25..Feb-26 · test >= 2026-03-01.

Compared on the near rows:
  sel_v3      the selection-stage model (v3 features, trained on selection rows) applied at the near bar
  ap_v3       same feature set but trained on near rows
  ap_v4       v4 features (incl. approach price action) trained on near rows
  ap_v4_geo   v4 + geometry only (no ap_* features) - isolates the two contributions

    python experiments_v4e.py   ->  study_results/quality_v4_approach_grid.csv
"""
import time

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from lubot.quality import FEATURE_ORDER, FEATURE_ORDER_V3, NUMERIC_V4_CONTEXT, QualityScorer, bagged_train, feature_importance
from lubot.trainset import load_training

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 40)
P = dict(max_iter=400, learning_rate=0.02, max_depth=3, max_leaf_nodes=8, min_samples_leaf=200, l2_regularization=5.0)

d = pd.read_pickle("models/approach_rows.pkl")
fcols = [c for c in d.columns if c.startswith("f__")]
fx = d[fcols].copy()
fx.columns = [c[3:] for c in fcols]
meta = d.drop(columns=fcols)
meta["sel_time"] = pd.to_datetime(meta.sel_time)
kinds = meta.kind.to_numpy()
y = meta.ge1.to_numpy().astype(int)
dist = fx["distance_atr"].to_numpy(dtype=float)
tr_m = (meta.sel_time < "2025-12-01").to_numpy()
va_m = ((meta.sel_time >= "2025-12-01") & (meta.sel_time < "2026-03-01")).to_numpy()
te_m = (meta.sel_time >= "2026-03-01").to_numpy()
print("near rows train/val/test", tr_m.sum(), va_m.sum(), te_m.sum(), " base ge1", y.mean().round(3), flush=True)

# selection-stage rows for the 'sel_v3' reference model
smeta, sfx = load_training()
s_tr = (smeta.sel_time < "2025-12-01").to_numpy()


def ev(s, X, m, penalty=0.02):
    p = s.score_many(list(kinds[m]), X[m])
    dd = meta.loc[m, ["tf", "bar_i", "side", "ge1", "bounce_atr"]].copy()
    dd["p"] = p
    dd["key"] = -p + penalty * dist[m]
    best = dd.sort_values("key").groupby(["tf", "bar_i", "side"]).head(1)
    k, k6 = best[best.p >= 0.5], best[best.p >= 0.6]
    return dict(auc=round(roc_auc_score(y[m], p), 4), best=round(best.ge1.mean(), 3),
                p50=round(k.ge1.mean(), 3) if len(k) else np.nan, kept=round(len(k) / len(best), 2),
                bounce50=round(k.bounce_atr.median(), 2) if len(k) else np.nan,
                p60=round(k6.ge1.mean(), 3) if len(k6) else np.nan, kept60=round(len(k6) / len(best), 2))


def by_tf(s, X, m):
    p = s.score_many(list(kinds[m]), X[m])
    dd = meta.loc[m, ["tf", "bar_i", "side", "ge1"]].copy()
    dd["p"] = p
    dd["key"] = -p + 0.02 * dist[m]
    best = dd.sort_values("key").groupby(["tf", "bar_i", "side"]).head(1)
    k = best[best.p >= 0.5]
    return {tf: f"{g.ge1.mean():.3f}(n{len(g)})" for tf, g in k.groupby("tf")}


sess = [f for f in FEATURE_ORDER if f.startswith("sess_") or f.startswith("kind_") or f == "ny_hour_raw"]
AP = [f for f in NUMERIC_V4_CONTEXT if f.startswith("ap_")]
v4_no_ap = [f for f in FEATURE_ORDER if f not in AP]
rows = []
# reference: selection-stage v3 model applied at the near bar
sc = QualityScorer(features=list(FEATURE_ORDER_V3))
Xs = sc.matrix_from_frame(sfx, list(smeta.kind))
s_ref = bagged_train(Xs[s_tr], smeta.ge1.to_numpy()[s_tr], list(smeta.kind[s_tr]), n_models=5, gbm_params=P, scorer=sc)
del Xs
X = QualityScorer(features=list(FEATURE_ORDER_V3)).matrix_from_frame(fx, list(kinds))
r = {"setting": "sel_v3 (selection model @near bar)", "n_features": len(FEATURE_ORDER_V3)}
r.update({f"val_{k}": v for k, v in ev(s_ref, X, va_m).items()})
r.update({f"test_{k}": v for k, v in ev(s_ref, X, te_m).items()})
rows.append(r)
print(r, flush=True)
print("   by tf (test):", by_tf(s_ref, X, te_m), flush=True)
del X

GRID = {"ap_v3": FEATURE_ORDER_V3, "ap_v4_geo(no ap_*)": v4_no_ap, "ap_v4": FEATURE_ORDER}
for name, feats in GRID.items():
    t0 = time.time()
    sc = QualityScorer(features=list(feats))
    X = sc.matrix_from_frame(fx, list(kinds))
    s = bagged_train(X[tr_m], y[tr_m], list(kinds[tr_m]), n_models=5, gbm_params=P, scorer=sc)
    r = {"setting": name, "n_features": len(feats)}
    r.update({f"val_{k}": v for k, v in ev(s, X, va_m).items()})
    r.update({f"test_{k}": v for k, v in ev(s, X, te_m).items()})
    r["sec"] = round(time.time() - t0)
    rows.append(r)
    print(r, flush=True)
    print("   by tf (test):", by_tf(s, X, te_m), flush=True)
    if name == "ap_v4":
        idx = np.random.default_rng(0).choice(np.flatnonzero(te_m), 8000, replace=False)
        imp = feature_importance(s, X[idx], [kinds[j] for j in idx], y[idx], n_repeats=2)
        print("\ntop-25 importance (test, approach model):")
        for n, v in imp[:25]:
            print(f"  {n:<24}{v:+.4f}")
        pd.DataFrame(imp, columns=["feature", "auc_drop"]).to_csv("study_results/quality_v4_approach_importance.csv", index=False)
        # calibration on test
        p = s.score_many(list(kinds[te_m]), X[te_m])
        cal = pd.DataFrame({"p": p, "y": y[te_m]}).assign(b=lambda t: pd.cut(t.p, [0, .3, .4, .45, .5, .55, .6, .7, .8, 1]))
        print("\ncalibration (test):")
        print(cal.groupby("b", observed=True).agg(n=("p", "size"), pred=("p", "mean"), actual=("y", "mean")).round(3).T.to_string())
    del X, s
out = pd.DataFrame(rows)
out.to_csv("study_results/quality_v4_approach_grid.csv", index=False)
print(out.to_string(index=False))
