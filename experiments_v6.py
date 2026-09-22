#!/usr/bin/env python3
"""v6 learner study on the existing v5 training sets (no rebuild needed).

Strict time split: train < 2025-12-01 · validate 2025-12-01..2026-03-01 · test >= 2026-03-01.
Everything is chosen on VALIDATION; the test window is only reported.

Part A  honest baseline: the v5 production GBM re-measured with
          - POI-level weights (1 / rows per POI, a POI is re-recorded every 25 bars while alive)
          - slot-level top-1 metrics (what the bot does: best-ranked candidate per (bar, side))
Part B  learner grid (LightGBM binary, exported to the bot's JSON trees):
          leaves / min_data / feature_fraction / L1-L2 / rounds (early stopping on val)
          x sample weights (none / 1 per POI)  x targets (ge1 / soft bounce)
Part C  ranking objective (lambdarank on slot groups) vs binary, judged on slot top-1 hit-rate
Part D  bagged best LightGBM (5 seeds) vs v5 GBM: AUC, slot metrics, calibration, export check

Resumable: each part writes its CSV and is skipped when it exists.
    python experiments_v6.py
"""
import os
import time

import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.metrics import roc_auc_score, log_loss

from lubot.quality import FEATURE_ORDER, QualityScorer, bagged_train
from lubot.lgbm_export import export_lgbm
from lubot.trainset import load_training

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 40)
OUT = "study_results"
os.makedirs(OUT, exist_ok=True)


def save(name, df):
    df.to_csv(f"{OUT}/{name}.csv", index=False)
    os.system(f'cd {os.path.dirname(os.path.abspath(__file__))} && bash save.sh "v6 step 1/2: {name}" >/dev/null 2>&1')


meta, fx = load_training()
tr_m = (meta.sel_time < "2025-12-01").to_numpy()
va_m = ((meta.sel_time >= "2025-12-01") & (meta.sel_time < "2026-03-01")).to_numpy()
te_m = (meta.sel_time >= "2026-03-01").to_numpy()
kinds = meta.kind.to_numpy()
y = meta.ge1.to_numpy().astype(int)
dist = fx["distance_atr"].to_numpy(dtype=float)
# POI-level weight: 1 / number of rows of that POI (the bot sees a POI once, not 13 times)
poi_key = (meta.tf + "_" + meta.id.astype(str)).to_numpy()
cnt = pd.Series(poi_key).map(pd.Series(poi_key).value_counts()).to_numpy(dtype=float)
w_poi = 1.0 / cnt
# slot id for ranking groups / slot metrics
slot_key = (meta.tf + "_" + meta.sel_i.astype(str) + "_" + meta.side).to_numpy()
# soft target: clipped bounce in ATR (0..3) scaled to 0..1 - rewards big bounces, punishes none
soft = np.clip(meta.bounce_atr.to_numpy(dtype=float), 0.0, 3.0) / 3.0
print("rows train/val/test", tr_m.sum(), va_m.sum(), te_m.sum(), "| unique POIs", len(set(poi_key)), flush=True)

sc0 = QualityScorer(features=list(FEATURE_ORDER))
X = sc0.matrix_from_frame(fx, list(kinds)).astype(np.float32)
del fx


def slot_metrics(p: np.ndarray, m: np.ndarray, penalty: float = 0.02) -> dict:
    """Bot-style: best (p - penalty*dist) per slot; hit-rate / bounce of the chosen candidate,
    and how often the chosen one beats the slot's mean (rank skill inside the slot)."""
    d = pd.DataFrame({"slot": slot_key[m], "p": p, "y": y[m], "b": meta.bounce_atr.to_numpy()[m],
                      "ge2": meta.ge2.to_numpy()[m], "key": -p + penalty * dist[m], "w": w_poi[m]})
    best = d.sort_values("key").groupby("slot").head(1)
    multi = d.groupby("slot").y.transform("size") > 1
    dm = d[multi]
    slot_mean = dm.groupby("slot").y.mean()
    bm = dm.sort_values("key").groupby("slot").head(1).set_index("slot")
    lift_in_slot = float((bm.y - slot_mean.reindex(bm.index)).mean()) if len(bm) else np.nan
    out = {"auc": round(roc_auc_score(y[m], p), 4),
           "auc_w": round(roc_auc_score(y[m], p, sample_weight=w_poi[m]), 4),
           "logloss": round(log_loss(y[m], np.clip(p, 1e-6, 1 - 1e-6)), 4),
           "top1": round(best.y.mean(), 3), "top1_bounce": round(best.b.median(), 2),
           "lift_in_slot": round(lift_in_slot, 4)}
    for q in (0.5, 0.55, 0.6, 0.65):
        k = best[best.p >= q]
        out[f"p{int(q * 100)}"] = round(k.y.mean(), 3) if len(k) else np.nan
        out[f"kept{int(q * 100)}"] = round(len(k) / len(best), 3)
        out[f"ge2_{int(q * 100)}"] = round(k.ge2.mean(), 3) if len(k) else np.nan
    return out


SHOW = ("auc", "auc_w", "top1", "p50", "kept50", "p60", "p65", "lift_in_slot")


def report(name, p_va, p_te, extra=None):
    r = {"setting": name}
    r.update({f"val_{k}": v for k, v in slot_metrics(p_va, va_m).items()})
    r.update({f"test_{k}": v for k, v in slot_metrics(p_te, te_m).items()})
    if extra:
        r.update(extra)
    print({k: v for k, v in r.items() if k == "setting" or (k.startswith("val_") and k[4:] in SHOW) or k in ("test_auc", "test_p50", "test_p60")}, flush=True)
    return r


def sig(z):
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))


# --------------------------------------------------------------- Part A: v5 honest baseline
P5 = dict(max_iter=400, learning_rate=0.02, max_depth=3, max_leaf_nodes=8, min_samples_leaf=300, l2_regularization=10.0)
if not os.path.exists(f"{OUT}/quality_v6_baseline.csv"):
    print("\n=== Part A: v5 production GBM, honest metrics ===", flush=True)
    rows = []
    t0 = time.time()
    s5 = bagged_train(X[tr_m], y[tr_m], list(kinds[tr_m]), n_models=5, gbm_params=P5, scorer=QualityScorer(features=list(FEATURE_ORDER)))
    rows.append(report("v5_gbm_bag5", s5.score_many(list(kinds[va_m]), X[va_m]), s5.score_many(list(kinds[te_m]), X[te_m]), {"sec": round(time.time() - t0)}))
    del s5
    t0 = time.time()
    s5w = bagged_train(X[tr_m], y[tr_m], list(kinds[tr_m]), n_models=5, gbm_params=P5, scorer=QualityScorer(features=list(FEATURE_ORDER)), sample_weight=w_poi[tr_m])
    rows.append(report("v5_gbm_bag5_poiweights", s5w.score_many(list(kinds[va_m]), X[va_m]), s5w.score_many(list(kinds[te_m]), X[te_m]), {"sec": round(time.time() - t0)}))
    del s5w
    # the shipped model (trained < Mar 2026 = train+val) on test only, for reference
    ship = QualityScorer.load("models/quality_model_trainonly.json")
    p_te = ship.score_many(list(kinds[te_m]), X[te_m])
    r = {"setting": "shipped_v5_trainonly(<Mar26)"}
    r.update({f"test_{k}": v for k, v in slot_metrics(p_te, te_m).items()})
    rows.append(r)
    save("quality_v6_baseline", pd.DataFrame(rows))

# --------------------------------------------------------------- Part B: LightGBM grid
BASE = dict(objective="binary", metric="auc", verbose=-1, num_threads=2, seed=7, bagging_freq=1)
GRID_B = {
    "lgb_l8_md300": dict(num_leaves=8, learning_rate=0.02, min_data_in_leaf=300, feature_fraction=0.7, bagging_fraction=0.8, lambda_l2=10.0),
    "lgb_l15_md300": dict(num_leaves=15, learning_rate=0.02, min_data_in_leaf=300, feature_fraction=0.7, bagging_fraction=0.8, lambda_l2=10.0),
    "lgb_l15_md600": dict(num_leaves=15, learning_rate=0.02, min_data_in_leaf=600, feature_fraction=0.7, bagging_fraction=0.8, lambda_l2=10.0),
    "lgb_l31_md600": dict(num_leaves=31, learning_rate=0.02, min_data_in_leaf=600, feature_fraction=0.6, bagging_fraction=0.8, lambda_l2=20.0),
    "lgb_l8_lr01_ff5": dict(num_leaves=8, learning_rate=0.01, min_data_in_leaf=300, feature_fraction=0.5, bagging_fraction=0.8, lambda_l2=10.0),
    "lgb_l15_ff4_l1": dict(num_leaves=15, learning_rate=0.02, min_data_in_leaf=300, feature_fraction=0.4, bagging_fraction=0.8, lambda_l2=10.0, lambda_l1=5.0),
    "lgb_l15_d4": dict(num_leaves=15, max_depth=4, learning_rate=0.02, min_data_in_leaf=300, feature_fraction=0.7, bagging_fraction=0.8, lambda_l2=10.0),
    "lgb_l6_d3": dict(num_leaves=6, max_depth=3, learning_rate=0.02, min_data_in_leaf=200, feature_fraction=0.7, bagging_fraction=0.8, lambda_l2=5.0),
}
SOFT_ON = ("lgb_l8_md300", "lgb_l15_md300")


def fit_lgb(params, target, weight, rounds=3000, es=150):
    p = dict(BASE, **params)
    if target is soft:
        p.update(objective="cross_entropy", metric="cross_entropy")
    dtr = lgb.Dataset(X[tr_m], target[tr_m], weight=None if weight is None else weight[tr_m], free_raw_data=False)
    dva = lgb.Dataset(X[va_m], y[va_m].astype(float), weight=None if weight is None else weight[va_m], reference=dtr, free_raw_data=False)
    return lgb.train(p, dtr, num_boost_round=rounds, valid_sets=[dva], callbacks=[lgb.early_stopping(es, verbose=False)])


if not os.path.exists(f"{OUT}/quality_v6_lgb_grid.csv"):
    print("\n=== Part B: LightGBM grid (early stopping on val) ===", flush=True)
    part = f"{OUT}/quality_v6_lgb_grid_partial.csv"
    rows = pd.read_csv(part).to_dict("records") if os.path.exists(part) else []
    done = {r["setting"] for r in rows}
    for name, params in GRID_B.items():
        for wname, wt in (("nw", None), ("pw", w_poi)):
            for tname, tgt in (("ge1", y.astype(float)), ("soft", soft)):
                if tname == "soft" and name not in SOFT_ON:
                    continue
                key = f"{name}|{wname}|{tname}"
                if key in done:
                    continue
                t0 = time.time()
                b = fit_lgb(params, tgt, wt)
                p_va = sig(b.predict(X[va_m], raw_score=True))
                p_te = sig(b.predict(X[te_m], raw_score=True))
                rows.append(report(key, p_va, p_te, {"best_iter": b.best_iteration, "sec": round(time.time() - t0)}))
                pd.DataFrame(rows).to_csv(part, index=False)       # resumable inside the grid
    grid = pd.DataFrame(rows).sort_values("val_auc", ascending=False)
    print(grid[["setting", "val_auc", "val_auc_w", "val_top1", "val_p50", "val_kept50", "val_p60", "val_p65", "val_lift_in_slot",
                "test_auc", "test_top1", "test_p50", "test_p60", "test_p65", "best_iter"]].to_string(index=False))
    save("quality_v6_lgb_grid", grid)

# --------------------------------------------------------------- Part C: lambdarank
if not os.path.exists(f"{OUT}/quality_v6_rank.csv"):
    print("\n=== Part C: lambdarank on slot groups vs binary ===", flush=True)
    from sklearn.linear_model import LogisticRegression
    rows = []
    idx_tr = np.flatnonzero(tr_m)
    idx_tr = idx_tr[np.argsort(slot_key[idx_tr], kind="stable")]
    grp_tr = pd.Series(slot_key[idx_tr]).groupby(slot_key[idx_tr], sort=False).size().to_numpy()
    idx_va = np.flatnonzero(va_m)
    idx_va = idx_va[np.argsort(slot_key[idx_va], kind="stable")]
    grp_va = pd.Series(slot_key[idx_va]).groupby(slot_key[idx_va], sort=False).size().to_numpy()
    b_atr = meta.bounce_atr.to_numpy(dtype=float)
    rel = (b_atr >= 0.5).astype(int) + (b_atr >= 1.0).astype(int) + (b_atr >= 2.0).astype(int)
    for name, params in (("rank_l8_md300", GRID_B["lgb_l8_md300"]), ("rank_l15_md300", GRID_B["lgb_l15_md300"])):
        for relname, relv in (("bin", y), ("graded", rel)):
            t0 = time.time()
            p = dict(BASE, objective="lambdarank", metric="ndcg", eval_at=[1], lambdarank_truncation_level=5, **params)
            dtr = lgb.Dataset(X[idx_tr], relv[idx_tr], group=grp_tr, free_raw_data=False)
            dva = lgb.Dataset(X[idx_va], relv[idx_va], group=grp_va, reference=dtr, free_raw_data=False)
            b = lgb.train(p, dtr, num_boost_round=3000, valid_sets=[dva], callbacks=[lgb.early_stopping(150, verbose=False)])
            z_va = b.predict(X[va_m], raw_score=True)
            z_te = b.predict(X[te_m], raw_score=True)
            # ranking scores are not probabilities: 1-D logistic calibration fitted on TRAIN scores
            z_tr = b.predict(X[tr_m], raw_score=True)
            cal = LogisticRegression(C=100.0).fit(z_tr[:, None], y[tr_m])
            p_va = cal.predict_proba(z_va[:, None])[:, 1]
            p_te = cal.predict_proba(z_te[:, None])[:, 1]
            rows.append(report(f"{name}|{relname}", p_va, p_te, {"best_iter": b.best_iteration, "sec": round(time.time() - t0)}))
    save("quality_v6_rank", pd.DataFrame(rows))

# --------------------------------------------------------------- Part D: bagged best vs v5
if not os.path.exists(f"{OUT}/quality_v6_bag_compare.csv"):
    print("\n=== Part D: bagged LightGBM (5 seeds) vs v5 GBM ===", flush=True)
    grid = pd.read_csv(f"{OUT}/quality_v6_lgb_grid.csv")
    grid = grid[grid.setting.str.endswith("|ge1") & (grid.val_kept50 >= 0.30) & (grid.best_iter >= 100)]
    # selection rule: POI-weighted validation AUC (one vote per POI, what the bot sees)
    best = grid.sort_values("val_auc_w", ascending=False).iloc[0]
    name, wname, _ = best.setting.split("|")
    params = GRID_B[name]
    wt = w_poi if wname == "pw" else None
    n_iter = int(best.best_iter)
    print("best:", best.setting, "iters", n_iter, flush=True)
    rows = []
    zs_va, zs_te, boosters = [], [], []
    t0 = time.time()
    for k in range(5):
        p = dict(BASE, **params, bagging_seed=100 + k, feature_fraction_seed=100 + k)
        p["seed"] = 100 + k
        b = lgb.train(p, lgb.Dataset(X[tr_m], y[tr_m], weight=None if wt is None else wt[tr_m]), num_boost_round=n_iter)
        boosters.append(b)
        zs_va.append(b.predict(X[va_m], raw_score=True))
        zs_te.append(b.predict(X[te_m], raw_score=True))
    p_va, p_te = sig(np.mean(zs_va, 0)), sig(np.mean(zs_te, 0))
    rows.append(report(f"lgb_bag5[{best.setting}]", p_va, p_te, {"sec": round(time.time() - t0)}))
    trees = []
    for b in boosters:
        trees += export_lgbm(b, scale=1.0 / len(boosters))["trees"]
    exp = QualityScorer(features=list(FEATURE_ORDER))
    exp.models["ALL"] = {"kind": "gbm", "trees": trees, "baseline": 0.0, "n": int(tr_m.sum()), "rate": float(y[tr_m].mean()), "n_trees": len(trees), "bagged": 5}
    p_chk = exp.score_many(list(kinds[va_m]), X[va_m])
    print("export check max|diff| =", float(np.abs(p_chk - p_va).max()), flush=True)
    # ensemble: bagged LightGBM + v5-GBM (POI weights) - average of probabilities
    s5w = bagged_train(X[tr_m], y[tr_m], list(kinds[tr_m]), n_models=5, gbm_params=P5, scorer=QualityScorer(features=list(FEATURE_ORDER)), sample_weight=w_poi[tr_m])
    q_va, q_te = s5w.score_many(list(kinds[va_m]), X[va_m]), s5w.score_many(list(kinds[te_m]), X[te_m])
    rows.append(report("ens[lgb_bag5 + v5gbm_pw]", 0.5 * (p_va + q_va), 0.5 * (p_te + q_te)))
    base = pd.read_csv(f"{OUT}/quality_v6_baseline.csv")
    rows.append(base.iloc[0].to_dict())
    rows.append(base.iloc[1].to_dict())
    d = pd.DataFrame({"p": p_te, "y": y[te_m]})
    d["b"] = pd.cut(d.p, [0, 0.4, 0.5, 0.55, 0.6, 0.65, 0.7, 1.0])
    print("lgb calibration (test):\n", d.groupby("b", observed=True).agg(n=("y", "size"), pred=("p", "mean"), actual=("y", "mean")).round(3).T.to_string())
    save("quality_v6_bag_compare", pd.DataFrame(rows))
print("=== experiments_v6 done")
