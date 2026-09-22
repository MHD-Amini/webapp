"""Export a fitted LightGBM booster into the plain JSON tree format used by
``lubot.quality`` (``{"f","t","l","r","leaf","v"}`` per tree, ``x <= t`` goes left),
so v6 models run with the same numpy / pure-python inference as v2-v5 and need no
LightGBM at runtime (the bot only needs numpy).

Internal node values are filled with the count-weighted mean of their children so
Saabas explanations (``QualityScorer.explain``) keep working.
"""
from __future__ import annotations

from typing import Dict, List

import numpy as np


def _flatten(tree: Dict) -> Dict:
    f: List[int] = []
    t: List[float] = []
    l: List[int] = []
    r: List[int] = []
    leaf: List[bool] = []
    v: List[float] = []
    cnt: List[float] = []

    def add(node) -> int:
        idx = len(f)
        f.append(0); t.append(0.0); l.append(-1); r.append(-1); leaf.append(False); v.append(0.0); cnt.append(0.0)
        if "leaf_value" in node:
            leaf[idx] = True
            v[idx] = float(node["leaf_value"])
            cnt[idx] = float(node.get("leaf_count", 1.0))
            return idx
        if node.get("decision_type", "<=") != "<=":
            raise ValueError("only numerical '<=' splits are supported (no categorical features)")
        f[idx] = int(node["split_feature"])
        t[idx] = float(node["threshold"])
        # LightGBM: missing values go to the side given by ``missing_type``/``default_left``;
        # our features are never NaN (cleaned to 0) so the plain <= rule is exact.
        li = add(node["left_child"])
        ri = add(node["right_child"])
        l[idx], r[idx] = li, ri
        cnt[idx] = cnt[li] + cnt[ri]
        v[idx] = (v[li] * cnt[li] + v[ri] * cnt[ri]) / cnt[idx] if cnt[idx] > 0 else 0.5 * (v[li] + v[ri])
        return idx

    add(tree["tree_structure"])
    return {"f": f, "t": t, "l": l, "r": r, "leaf": leaf, "v": v}


def export_lgbm(booster, n: int = 0, rate: float = float("nan"), scale: float = 1.0) -> Dict:
    """LightGBM Booster -> {"kind": "gbm", "trees": [...], "baseline": 0.0, ...}.

    LightGBM adds the initial score (``boost_from_average``) to the first tree's
    leaves, so the exported baseline is 0.  ``scale`` multiplies every leaf value
    (used when several boosters are averaged into one model)."""
    dump = booster.dump_model()
    trees = []
    for tr in dump["tree_info"]:
        ft = _flatten(tr)
        if scale != 1.0:
            ft["v"] = [x * scale for x in ft["v"]]
        trees.append(ft)
    return {"kind": "gbm", "trees": trees, "baseline": 0.0, "n": int(n), "rate": float(rate), "n_trees": len(trees),
            "objective": dump.get("objective", "")}


def predict_exported(model: Dict, X: np.ndarray) -> np.ndarray:
    """Raw score with the exported trees (used by the unit test to check the export)."""
    from .quality import _predict_trees
    return _predict_trees(model["trees"], X, model["baseline"])
