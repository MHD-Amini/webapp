"""POI quality model - P(price bounces >= 1 ATR before the zone is violated).

v2 (this file) supports two model families behind one ``QualityScorer`` API:

* ``gbm``       gradient-boosted decision trees (sklearn HistGradientBoosting at
                training time, exported to plain JSON node arrays; inference is
                pure numpy - no sklearn needed at runtime).  One model per POI
                type when enough rows exist, plus a pooled fallback.
* ``logistic``  the v1 standardised logistic regression (kept for comparison
                and as a fallback when a legacy model file is loaded).

All features are known when the POI is selected (no look-ahead).  Creation
features come from ``POI.features``; context features from ``TimeframeEngine
.qualified()``.  Missing features default to 0 so an old model still runs on
new feature dicts and vice-versa.

Explanations: ``explain()`` returns the top feature contributions - standardised
coefficient x value for the logistic model, Saabas-style path contributions for
the trees.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from .indicators import IndicatorSet
from .levels import CREATION_KEYS as LEVEL_CREATION, FEATURES as LEVEL_FEATURES

# --------------------------------------------------------------- features
#: v1 features (kept in this order for backwards compatibility with old models)
NUMERIC_V1 = [
    "zone_atr", "displacement_atr", "impulse_bars", "block_candles", "has_imbalance", "body_ratio",
    "n_swept", "swept_quality", "swept_equal", "swept_session",
    "distance_atr", "liq_between_n", "liq_between_quality", "of_total", "of_near", "of_recent",
    "confluence", "aligned_bias", "in_correct_zone", "age_bars", "is_bull",
]
#: v2 additions - POI creation
NUMERIC_V2_CREATION = ["is_leg_origin", "prior_move_atr", "wick_candle_agrees", "parent_zone_atr"]
#: v2 additions - selection context
NUMERIC_V2_CONTEXT = [
    "liq_between_weight", "first_pool_gap_atr", "liq_behind_n", "liq_behind_quality",
    "liq_stacked_beyond_n", "liq_near_edge_n", "opp_liq_between_n",
    "closer_same_dir", "opp_on_path", "range_pos", "away_atr", "min_approach_atr", "near_misses",
    "toward_mom5", "toward_mom20", "atr_ratio", "pos20", "pos100", "bos_recent_n", "bos_recent_aligned",
    "dow",
    "htf_confluence", "htf_confluence_kind", "htf_bias_aligned", "htf_liq_behind_atr", "htf_in_zone", "htf_dist_atr",
]
#: v3 additions - POI creation
NUMERIC_V3_CREATION = [
    "sweep_depth_atr", "created_ny_hour", "created_dow", "impulse_body_frac", "hb_pos_in_impulse",
    "parent_age_bars", "parent_tap_to_break", "break_close_atr",
]
#: v3 additions - selection context
NUMERIC_V3_CONTEXT = [
    "tf_minutes",
    "round_100_atr", "round_50_atr", "round_10_atr",
    "pos_prev_day", "pos_prev_week", "pos_today", "beyond_prev_day", "beyond_today", "dist_prev_day_level_atr",
    "day_range_atr", "retrace_frac", "bars_since_extreme", "tested_violated", "tested_respected", "opp_respected_near",
    "atr_ratio_long", "toward_mom60", "ema_gap_aligned", "price_vs_ema200", "last_bos_age", "last_bos_aligned",
    "n_alive_same_dir", "n_alive_opp_dir", "age_hours",
]
#: v4 additions - price action of the base / impulse (POI creation)
NUMERIC_V4_CREATION = [
    "block_rej_wick_atr", "block_rej_wick_frac", "engulf_ratio", "impulse_max_body_atr", "impulse_close_pos",
    "impulse_dir_frac", "pre_compression_atr", "pre_trend_bars", "caused_bos", "swing_in_zone", "leg_atr",
]
#: v4 additions - price action of the approach (selection context)
NUMERIC_V4_CONTEXT = [
    "ap_toward_run", "ap_last_body", "ap_rej_wick_atr", "ap_rej_wick_frac", "ap_rng_ratio5", "ap_last_rng_atr",
    "ap_body_trend", "ap_ema_stretch", "ap_move5_atr", "ap_eta_bars", "ap_broke5", "ap_broke50",
    "ap_zone_beyond50", "ap_wick_pressure", "ap_body_frac5", "edge_to_key_atr", "zone_vs_bar_range",
]
#: v5 additions - classic indicators at creation (cr_*), at selection (ind_*) and on the parent TF (htf_*)
NUMERIC_V5_CREATION = list(IndicatorSet.CREATION)
NUMERIC_V5_CONTEXT = list(IndicatorSet.SELECTION) + list(IndicatorSet.HTF)
#: v6 additions - level memory (volume profile / value area / reaction counts of the zone area)
NUMERIC_V6_CREATION = list(LEVEL_CREATION)
NUMERIC_V6_CONTEXT = list(LEVEL_FEATURES) + ["lv_visits_since_create", "lv_density_change",
                                             "hlv_vol_density", "hlv_lvn_score", "hlv_va_pos", "hlv_zone_outside_va",
                                             "hlv_rev_with", "hlv_rev_ratio", "hlv_slice_frac", "hlv_poc_beyond"]
NUMERIC_V2 = NUMERIC_V1 + NUMERIC_V2_CREATION + NUMERIC_V2_CONTEXT
NUMERIC_V3 = NUMERIC_V2 + NUMERIC_V3_CREATION + NUMERIC_V3_CONTEXT
NUMERIC_V4 = NUMERIC_V3 + NUMERIC_V4_CREATION + NUMERIC_V4_CONTEXT
NUMERIC_V5 = NUMERIC_V4 + NUMERIC_V5_CREATION + NUMERIC_V5_CONTEXT
NUMERIC = NUMERIC_V5 + NUMERIC_V6_CREATION + NUMERIC_V6_CONTEXT
SESSIONS = ["asia", "london", "preny", "ny", "lclose", "nypm"]
KINDS = ["OB", "BB", "IMB", "HB", "UW"]
LOG_FEATURES = {"zone_atr", "displacement_atr", "distance_atr", "age_bars", "of_total", "of_near", "of_recent",
                "n_swept", "confluence", "liq_between_n", "liq_between_weight", "liq_behind_n",
                "liq_stacked_beyond_n", "closer_same_dir", "opp_on_path", "away_atr", "min_approach_atr",
                "near_misses", "prior_move_atr", "htf_dist_atr", "first_pool_gap_atr", "opp_liq_between_n",
                "sweep_depth_atr", "parent_age_bars", "parent_tap_to_break",
                "day_range_atr", "bars_since_extreme", "tested_violated", "tested_respected", "opp_respected_near",
                "last_bos_age", "n_alive_same_dir", "n_alive_opp_dir", "age_hours", "tf_minutes",
                "engulf_ratio", "impulse_max_body_atr", "pre_compression_atr", "pre_trend_bars", "swing_in_zone",
                "leg_atr", "ap_eta_bars", "ap_last_rng_atr", "edge_to_key_atr", "zone_vs_bar_range",
                # v5 (heavy-tailed indicator features)
                "ind_relvol", "ind_relvol5", "ind_vol_trend", "ind_supertrend_age", "ind_bb_width_atr",
                "ind_pivot_dist_atr", "ind_bars_since_rsi_extreme", "ind_vol_ratio_hl", "ind_zone_at_ma",
                "cr_vol_impulse_rel", "cr_vol_block_rel", "cr_bb_width_atr", "cr_pivot_dist_atr",
                # v6 (counts / densities are heavy tailed)
                "lv_vol_density", "lv_time_density", "lv_vol_density_recent", "lv_rev_with", "lv_rev_against", "lv_visits",
                "lv_bars_since_visit", "lv_behind_density", "lv_path_density", "lv_visits_since_create",
                "cl_vol_density", "cl_rev_with", "cl_rev_against", "cl_visits", "cl_behind_density", "cl_bars_since_visit",
                "hlv_vol_density", "hlv_rev_with"}


def session_of(ny_hour: float) -> str:
    h = int(ny_hour)
    if h >= 17 or h < 1:
        return "asia"
    if h < 5:
        return "london"
    if h < 7:
        return "preny"
    if h < 10:
        return "ny"
    if h < 12:
        return "lclose"
    return "nypm"


def _clean(v) -> float:
    if v is None:
        return 0.0
    try:
        v = float(v)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if (math.isnan(v) or math.isinf(v)) else v


def _transform(feats: Dict[str, float], numeric: List[str], log: bool = True) -> Dict[str, float]:
    """Feature engineering shared by training and inference."""
    out: Dict[str, float] = {}
    for k in numeric:
        v = _clean(feats.get(k, 0.0))
        if log and k in LOG_FEATURES:
            v = math.log1p(max(v, 0.0))
        out[k] = v
    s = session_of(_clean(feats.get("ny_hour", 12)) or 12)
    for name in SESSIONS:
        out[f"sess_{name}"] = 1.0 if s == name else 0.0
    out["ny_hour_raw"] = _clean(feats.get("ny_hour", 12))
    return out


KIND_DUMMIES = [f"kind_{k}" for k in KINDS]
FEATURE_ORDER = NUMERIC + [f"sess_{s}" for s in SESSIONS] + ["ny_hour_raw"] + KIND_DUMMIES
FEATURE_ORDER_V5 = NUMERIC_V5 + [f"sess_{s}" for s in SESSIONS] + ["ny_hour_raw"] + KIND_DUMMIES
FEATURE_ORDER_V4 = NUMERIC_V4 + [f"sess_{s}" for s in SESSIONS] + ["ny_hour_raw"] + KIND_DUMMIES
FEATURE_ORDER_V3 = NUMERIC_V3 + [f"sess_{s}" for s in SESSIONS] + ["ny_hour_raw"] + KIND_DUMMIES
FEATURE_ORDER_V2 = NUMERIC_V2 + [f"sess_{s}" for s in SESSIONS] + ["ny_hour_raw"] + KIND_DUMMIES
FEATURE_ORDER_V1 = NUMERIC_V1 + [f"sess_{s}" for s in SESSIONS]


# ------------------------------------------------------------- tree model
def _compile_trees(trees: List[Dict]) -> List[Tuple[np.ndarray, ...]]:
    """JSON lists -> numpy arrays once (feat, thr, left, right, leaf, val) per tree."""
    return [(np.asarray(t["f"], dtype=int), np.asarray(t["t"], dtype=float), np.asarray(t["l"], dtype=int),
             np.asarray(t["r"], dtype=int), np.asarray(t["leaf"], dtype=bool), np.asarray(t["v"], dtype=float))
            for t in trees]


def _compile_trees_py(trees: List[Dict]) -> List[Tuple[list, ...]]:
    """Plain Python lists per tree (feat, thr, left, right, leaf, val) for the scalar fast path."""
    return [(list(map(int, t["f"])), list(map(float, t["t"])), list(map(int, t["l"])), list(map(int, t["r"])),
             list(map(bool, t["leaf"])), list(map(float, t["v"]))) for t in trees]


def _predict_one(ptrees, x: np.ndarray, baseline: float) -> float:
    """Scalar raw score for one sample (plain Python loops over pre-converted lists are
    ~20x faster than numpy indexing for a single row)."""
    xl = x.tolist()
    out = baseline
    for f, t, l, r, lf, val in ptrees:
        node = 0
        while not lf[node]:
            node = l[node] if xl[f[node]] <= t[node] else r[node]
        out += val[node]
    return out


def _predict_trees(trees: List[Dict], X: np.ndarray, baseline: float, ctrees=None) -> np.ndarray:
    """Vectorised raw-score prediction for exported HistGradientBoosting trees."""
    out = np.full(len(X), baseline, dtype=float)
    rows = np.arange(len(X))
    for feat, thr, left, right, leaf, val in (ctrees or _compile_trees(trees)):
        idx = np.zeros(len(X), dtype=int)
        for _ in range(64):
            is_leaf = leaf[idx]
            if is_leaf.all():
                break
            go_left = X[rows, feat[idx]] <= thr[idx]
            nxt = np.where(go_left, left[idx], right[idx])
            idx = np.where(is_leaf, idx, nxt)
        out += val[idx]
    return out


def _explain_trees(trees: List[Dict], x: np.ndarray, n_features: int, ctrees=None) -> np.ndarray:
    """Saabas path contributions for one sample: change of node value along the path
    is attributed to the feature that was split on."""
    contrib = np.zeros(n_features, dtype=float)
    for feat, thr, left, right, leaf, val in (ctrees or _compile_trees(trees)):
        node = 0
        for _ in range(64):
            if leaf[node]:
                break
            nxt = left[node] if x[feat[node]] <= thr[node] else right[node]
            contrib[feat[node]] += val[nxt] - val[node]
            node = nxt
    return contrib


def _export_hgb(clf) -> Dict:
    """Export a fitted HistGradientBoostingClassifier into JSON-serialisable trees."""
    trees = []
    for it in clf._predictors:
        nodes = it[0].nodes
        trees.append({
            "f": nodes["feature_idx"].astype(int).tolist(),
            "t": nodes["num_threshold"].astype(float).tolist(),
            "l": nodes["left"].astype(int).tolist(),
            "r": nodes["right"].astype(int).tolist(),
            "leaf": nodes["is_leaf"].astype(bool).tolist(),
            "v": nodes["value"].astype(float).tolist(),
        })
    # internal node values are 0 in sklearn's arrays; fill them with the
    # count-weighted mean of their children so Saabas explanations are meaningful
    for t, it in zip(trees, clf._predictors):
        nodes = it[0].nodes
        v = np.array(t["v"], dtype=float)
        cnt = nodes["count"].astype(float)
        for n in range(len(v) - 1, -1, -1):
            if not t["leaf"][n]:
                l, r = t["l"][n], t["r"][n]
                tot = cnt[l] + cnt[r]
                v[n] = (v[l] * cnt[l] + v[r] * cnt[r]) / tot if tot > 0 else 0.5 * (v[l] + v[r])
        t["v"] = v.tolist()
    return {"kind": "gbm", "trees": trees, "baseline": float(np.ravel(clf._baseline_prediction)[0])}


# ------------------------------------------------------------------ scorer
@dataclass
class QualityScorer:
    """kind -> model dict.  Model dicts are either
       {"kind": "logistic", "w", "b", "mu", "sd", "n", "rate"}   (v1)
    or {"kind": "gbm", "trees", "baseline", "n", "rate"}          (v2)
    """
    models: Dict[str, Dict] = field(default_factory=dict)
    base_rate: Dict[str, float] = field(default_factory=dict)
    features: List[str] = field(default_factory=lambda: list(FEATURE_ORDER))
    meta: Dict = field(default_factory=dict)
    _compiled: Dict[str, list] = field(default_factory=dict, repr=False)
    _compiled_py: Dict[str, list] = field(default_factory=dict, repr=False)

    def _ctrees(self, kind_key: str, m: Dict) -> list:
        c = self._compiled.get(kind_key)
        if c is None:
            c = self._compiled[kind_key] = _compile_trees(m["trees"])
        return c

    def _ptrees(self, kind_key: str, m: Dict) -> list:
        c = self._compiled_py.get(kind_key)
        if c is None:
            c = self._compiled_py[kind_key] = _compile_trees_py(m["trees"])
        return c

    # ----------------------------------------------------------- vectors
    @property
    def numeric(self) -> List[str]:
        return [f for f in self.features if not f.startswith("sess_") and not f.startswith("kind_") and f != "ny_hour_raw"]

    def vector(self, feats: Dict[str, float], kind: Optional[str] = None) -> np.ndarray:
        t = _transform(feats, self.numeric)
        if kind is not None:
            for k in KINDS:
                t[f"kind_{k}"] = 1.0 if kind == k else 0.0
        return np.array([t.get(k, 0.0) for k in self.features], dtype=float)

    def matrix(self, rows, kinds: Optional[List[str]] = None) -> np.ndarray:
        """rows: list of raw feature dicts, an already-built matrix (returned as is) or a
        pandas DataFrame whose columns are the raw feature names (vectorised transform)."""
        if isinstance(rows, np.ndarray):
            return rows
        if hasattr(rows, "columns"):
            return self.matrix_from_frame(rows, kinds)
        if not len(rows):
            return np.zeros((0, len(self.features)))
        kinds = kinds or [None] * len(rows)
        return np.vstack([self.vector(r, k) for r, k in zip(rows, kinds)])

    def matrix_from_frame(self, df, kinds: Optional[List[str]] = None) -> np.ndarray:
        """Vectorised equivalent of ``vector`` for a frame of raw feature columns
        (missing columns -> 0, NaN -> 0, log1p on LOG_FEATURES, session dummies, kind dummies)."""
        n = len(df)
        X = np.zeros((n, len(self.features)), dtype=np.float64)
        ny = np.nan_to_num(df["ny_hour"].to_numpy(dtype=float), nan=12.0) if "ny_hour" in df.columns else np.full(n, 12.0)
        ny_s = np.where(ny == 0, 12.0, ny)
        sess = np.array([session_of(h) for h in ny_s])
        kinds_arr = np.array(kinds) if kinds is not None else None
        for j, name in enumerate(self.features):
            if name.startswith("sess_"):
                X[:, j] = (sess == name[5:]).astype(float)
            elif name == "ny_hour_raw":
                X[:, j] = ny
            elif name.startswith("kind_"):
                if kinds_arr is not None:
                    X[:, j] = (kinds_arr == name[5:]).astype(float)
            elif name in df.columns:
                v = np.nan_to_num(df[name].to_numpy(dtype=float), nan=0.0, posinf=0.0, neginf=0.0)
                X[:, j] = np.log1p(np.maximum(v, 0.0)) if name in LOG_FEATURES else v
        return X

    # ----------------------------------------------------------- scoring
    def _model_key(self, kind: str) -> Optional[str]:
        if kind in self.models:
            return kind
        return "ALL" if "ALL" in self.models else None

    def _model(self, kind: str) -> Optional[Dict]:
        k = self._model_key(kind)
        return None if k is None else self.models[k]

    def _raw(self, m: Dict, X: np.ndarray, key: Optional[str] = None) -> np.ndarray:
        if m.get("kind", "logistic") == "gbm":
            return _predict_trees(m["trees"], X, m["baseline"], self._ctrees(key, m) if key else None)
        Xs = np.clip((X - np.array(m["mu"])) / np.array(m["sd"]), -3.0, 3.0)
        return Xs @ np.array(m["w"]) + m["b"]

    # v6: a model file may carry a second pooled member "ALL2" (different learner on the same
    # features); probabilities of "ALL" and "ALL2" are mixed with meta["mix"] (default 50/50)
    def _mix(self) -> Optional[float]:
        if "ALL2" not in self.models:
            return None
        mix = self.meta.get("mix") if isinstance(self.meta, dict) else None
        return float(mix[0]) if mix else 0.5

    def _prob_one(self, key: str, x: np.ndarray) -> float:
        m = self.models[key]
        if m.get("kind", "logistic") == "gbm":
            z = _predict_one(self._ptrees(key, m), x, m["baseline"])
        else:
            z = float(self._raw(m, x[None, :])[0])
        return 1.0 / (1.0 + math.exp(-max(min(z, 30), -30)))

    def score(self, kind: str, feats: Dict[str, float]) -> float:
        key = self._model_key(kind)
        if key is None:
            return self.base_rate.get(kind, 0.4)
        x = self.vector(feats, kind)
        p = self._prob_one(key, x)
        mix = self._mix()
        if mix is not None and key == "ALL":
            p = mix * p + (1.0 - mix) * self._prob_one("ALL2", x)
        return p

    def score_many(self, kinds: List[str], rows) -> np.ndarray:
        """Vectorised scoring (used in training / evaluation); rows = dicts, frame or matrix."""
        X = self.matrix(rows, kinds)
        out = np.zeros(len(rows), dtype=float)
        kinds_arr = np.array(kinds)
        for k in set(kinds):
            mask = kinds_arr == k
            key = self._model_key(k)
            if key is None:
                out[mask] = self.base_rate.get(k, 0.4)
                continue
            z = np.clip(self._raw(self.models[key], X[mask], key), -30, 30)
            p = 1.0 / (1.0 + np.exp(-z))
            mix = self._mix()
            if mix is not None and key == "ALL":
                z2 = np.clip(self._raw(self.models["ALL2"], X[mask], "ALL2"), -30, 30)
                p = mix * p + (1.0 - mix) / (1.0 + np.exp(-z2))
            out[mask] = p
        return out

    def explain(self, kind: str, feats: Dict[str, float], top: int = 5) -> List[Tuple[str, float]]:
        m = self._model(kind)
        if m is None:
            return []
        x = self.vector(feats, kind)
        if m.get("kind", "logistic") == "gbm":
            contrib = _explain_trees(m["trees"], x, len(self.features), self._ctrees(self._model_key(kind), m))
            mix = self._mix()
            if mix is not None and self._model_key(kind) == "ALL":
                m2 = self.models["ALL2"]
                contrib = mix * contrib + (1.0 - mix) * _explain_trees(m2["trees"], x, len(self.features), self._ctrees("ALL2", m2))
        else:
            xs = np.clip((x - np.array(m["mu"])) / np.array(m["sd"]), -3.0, 3.0)
            contrib = xs * np.array(m["w"])
        idx = np.argsort(-np.abs(contrib))[:top]
        return [(self.features[j], round(float(contrib[j]), 3)) for j in idx if abs(contrib[j]) > 1e-9]

    @property
    def model_kind(self) -> str:
        m = self.models.get("ALL") or next(iter(self.models.values()), {})
        return m.get("kind", "logistic")

    # ------------------------------------------------------------- persistence
    def save(self, path: str | Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps({"version": 2, "models": self.models, "base_rate": self.base_rate,
                                          "features": self.features, "meta": self.meta}, indent=None))

    @classmethod
    def load(cls, path: str | Path) -> Optional["QualityScorer"]:
        if isinstance(path, str) and "+" in path:
            members, weights = [], []
            for part in path.split("+"):
                fp, _, w = part.partition("*")
                m = cls.load(fp.strip())
                if m is None:
                    return None
                members.append(m)
                weights.append(float(w) if w else 1.0)
            return EnsembleScorer(members, weights)  # type: ignore[return-value]
        p = Path(path)
        if not p.exists():
            alt = Path(__file__).resolve().parents[1] / path
            if alt.exists():
                p = alt
            else:
                return None
        d = json.loads(p.read_text())
        models = d["models"]
        for m in models.values():
            m.setdefault("kind", "logistic")
        feats = d.get("features")
        if not feats:
            # legacy file without a feature list: infer from the weight vector length
            any_m = next(iter(models.values()), {})
            n_w = len(any_m.get("w", []))
            feats = {len(FEATURE_ORDER): FEATURE_ORDER, len(FEATURE_ORDER_V5): FEATURE_ORDER_V5, len(FEATURE_ORDER_V4): FEATURE_ORDER_V4,
                     len(FEATURE_ORDER_V3): FEATURE_ORDER_V3,
                     len(FEATURE_ORDER_V2): FEATURE_ORDER_V2}.get(n_w, FEATURE_ORDER_V1)
            feats = list(feats)
        return cls(models=models, base_rate=d.get("base_rate", {}), features=feats, meta=d.get("meta", {}))


# --------------------------------------------------------------- ensemble
@dataclass
class EnsembleScorer:
    """Average of several ``QualityScorer`` probabilities (v5: v4 structure/PA model +
    v5 indicator model).  Each member uses its own feature list, so members trained on
    different feature sets can be mixed.  Same public API as QualityScorer.

    Load with ``QualityScorer.load("models/a.json+models/b.json")`` (paths joined by '+',
    optional weights ``models/a.json*0.4+models/b.json*0.6``)."""
    members: List[QualityScorer] = field(default_factory=list)
    weights: List[float] = field(default_factory=list)

    def __post_init__(self):
        if not self.weights:
            self.weights = [1.0 / len(self.members)] * len(self.members)
        tot = sum(self.weights)
        self.weights = [w / tot for w in self.weights]

    @property
    def features(self) -> List[str]:
        return self.members[-1].features

    @property
    def meta(self) -> Dict:
        return {"ensemble": [m.meta for m in self.members], "weights": self.weights}

    @property
    def base_rate(self) -> Dict[str, float]:
        return self.members[-1].base_rate

    @property
    def model_kind(self) -> str:
        return "ensemble"

    def score(self, kind: str, feats: Dict[str, float]) -> float:
        return float(sum(w * m.score(kind, feats) for m, w in zip(self.members, self.weights)))

    def score_many(self, kinds: List[str], rows) -> np.ndarray:
        return sum(w * m.score_many(kinds, rows) for m, w in zip(self.members, self.weights))

    def explain(self, kind: str, feats: Dict[str, float], top: int = 5) -> List[Tuple[str, float]]:
        agg: Dict[str, float] = {}
        for m, w in zip(self.members, self.weights):
            for name, v in m.explain(kind, feats, top=top * 3):
                agg[name] = agg.get(name, 0.0) + w * v
        items = sorted(agg.items(), key=lambda t: -abs(t[1]))[:top]
        return [(k, round(v, 3)) for k, v in items]


# ---------------------------------------------------------------- training
#: default GBM settings - deliberately shallow / heavily regularised.  On the
#: 2025-01..2026-09 XAUUSD set this generalised best (val & test AUC ~0.63-0.64
#: with train AUC ~0.70); deeper trees fit the training period to 0.9 and lost
#: 2-3 AUC points out of sample.  See experiments_gbm.py.
GBM_DEFAULT = {"max_iter": 200, "learning_rate": 0.03, "max_depth": 3, "max_leaf_nodes": 8,
               "min_samples_leaf": 200, "l2_regularization": 5.0, "early_stopping": False, "random_state": 7}


def train(rows, y: np.ndarray, kinds: List[str], C: float = 0.3, min_rows: int = 150,
          model: str = "gbm", gbm_params: Optional[Dict] = None, per_kind: bool = False,
          sample_weight: Optional[np.ndarray] = None, scorer: Optional[QualityScorer] = None) -> QualityScorer:
    """rows: raw feature dicts (POI.features + selection context), y: 0/1 target.

    model="gbm": HistGradientBoostingClassifier (exported to JSON trees), pooled over
                 POI types with type dummies (per_kind=False, default) or one model per type.
    model="logistic": v1 standardised logistic regression.
    scorer: optional pre-built scorer (e.g. with a restricted feature list) to fit into.
    """
    scorer = scorer if scorer is not None else QualityScorer()
    X = scorer.matrix(rows, kinds)
    y = np.asarray(y).astype(int)
    kinds_arr = np.array(kinds)
    sw = None if sample_weight is None else np.asarray(sample_weight, dtype=float)

    params = dict(GBM_DEFAULT)
    if gbm_params:
        params.update(gbm_params)

    def fit(mask) -> Dict:
        Xm, ym = X[mask], y[mask]
        if model == "gbm":
            from sklearn.ensemble import HistGradientBoostingClassifier
            clf = HistGradientBoostingClassifier(**params)
            clf.fit(Xm, ym, sample_weight=None if sw is None else sw[mask])
            d = _export_hgb(clf)
            d.update({"n": int(mask.sum()), "rate": float(ym.mean()), "n_trees": len(d["trees"])})
            return d
        from sklearn.linear_model import LogisticRegression
        mu, sd = Xm.mean(0), Xm.std(0)
        sd[sd == 0] = 1.0
        clf = LogisticRegression(C=C, max_iter=5000)
        clf.fit(np.clip((Xm - mu) / sd, -3.0, 3.0), ym, sample_weight=None if sw is None else sw[mask])
        return {"kind": "logistic", "w": clf.coef_[0].tolist(), "b": float(clf.intercept_[0]),
                "mu": mu.tolist(), "sd": sd.tolist(), "n": int(mask.sum()), "rate": float(ym.mean())}

    scorer.models["ALL"] = fit(np.ones(len(y), dtype=bool))
    for k in KINDS:
        mask = kinds_arr == k
        scorer.base_rate[k] = float(y[mask].mean()) if mask.any() else float(y.mean())
        if per_kind and mask.sum() >= min_rows and len(np.unique(y[mask])) == 2:
            scorer.models[k] = fit(mask)
    scorer.meta = {"model": model, "n": int(len(y)), "rate": float(y.mean()), "gbm_params": params if model == "gbm" else None}
    return scorer


def feature_importance(scorer: QualityScorer, rows, kinds: List[str], y: np.ndarray,
                       n_repeats: int = 3, seed: int = 0) -> List[Tuple[str, float]]:
    """Permutation importance (drop in AUC) of the pooled scorer on the given rows."""
    from sklearn.metrics import roc_auc_score
    rng = np.random.default_rng(seed)
    X = scorer.matrix(rows, kinds)
    kinds_arr = np.array(kinds)

    def auc_of(Xm: np.ndarray) -> float:
        p = np.zeros(len(Xm))
        for k in set(kinds):
            mask = kinds_arr == k
            m = scorer._model(k)
            p[mask] = 1 / (1 + np.exp(-np.clip(scorer._raw(m, Xm[mask]), -30, 30))) if m else 0.5
        return roc_auc_score(y, p)

    base = auc_of(X)
    out = []
    for j, name in enumerate(scorer.features):
        drops = []
        for _ in range(n_repeats):
            Xp = X.copy()
            Xp[:, j] = rng.permutation(Xp[:, j])
            drops.append(base - auc_of(Xp))
        out.append((name, float(np.mean(drops))))
    out.sort(key=lambda t: -t[1])
    return out


def bagged_train(rows, y: np.ndarray, kinds: List[str], n_models: int = 5, subsample: float = 0.8,
                 gbm_params: Optional[Dict] = None, seed: int = 0, scorer: Optional[QualityScorer] = None,
                 sample_weight: Optional[np.ndarray] = None) -> QualityScorer:
    """Bagged GBM: ``n_models`` boosters on random row subsets, averaged.

    The average of k boosters is itself a booster (mean baseline + every tree with
    its leaf values scaled by 1/k), so the result is exported as ONE plain ``gbm``
    model and needs no runtime change (``score`` / ``explain`` work unchanged)."""
    rng = np.random.default_rng(seed)
    y = np.asarray(y).astype(int)
    n = len(y)
    parts = []
    base_scorer = scorer if scorer is not None else QualityScorer()
    if not isinstance(rows, np.ndarray):
        rows = base_scorer.matrix(rows, kinds)      # transform once, subsample the matrix
    for k in range(n_models):
        idx = np.sort(rng.choice(n, size=int(subsample * n), replace=False))
        params = dict(gbm_params or {})
        params["random_state"] = seed * 100 + k
        sub = rows[idx] if isinstance(rows, np.ndarray) else [rows[j] for j in idx]
        s = train(sub, y[idx], [kinds[j] for j in idx], model="gbm", gbm_params=params,
                  scorer=QualityScorer(features=list(base_scorer.features)),
                  sample_weight=None if sample_weight is None else np.asarray(sample_weight)[idx])
        parts.append(s.models["ALL"])
    trees = []
    for m in parts:
        for t in m["trees"]:
            trees.append({**t, "v": [v / n_models for v in t["v"]]})
    out = QualityScorer(features=list(base_scorer.features))
    out.models["ALL"] = {"kind": "gbm", "trees": trees, "baseline": float(np.mean([m["baseline"] for m in parts])),
                         "n": n, "rate": float(y.mean()), "n_trees": len(trees), "bagged": n_models}
    kinds_arr = np.array(kinds)
    for k in KINDS:
        mask = kinds_arr == k
        out.base_rate[k] = float(y[mask].mean()) if mask.any() else float(y.mean())
    out.meta = {"model": "gbm", "bagged": n_models, "subsample": subsample, "n": n, "rate": float(y.mean()),
                "gbm_params": {**GBM_DEFAULT, **(gbm_params or {})}}
    return out
