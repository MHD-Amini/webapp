"""Loading of the quality-model training sets written by ``build_training_set.py``.

Layout (v4): one row per (POI, sampling bar) with meta columns (tf, kind, sel_time,
ge1, bounce_atr, ...) and one ``float32`` column per raw feature, prefixed ``f__``.
Only *reached* rows are kept in memory (the sandbox has 1 GB)."""
from __future__ import annotations

import glob
from typing import List, Tuple

import numpy as np
import pandas as pd

META_KEEP = ["tf", "id", "kind", "direction", "sel_i", "sel_time", "rank", "n_side", "closest",
             "bounce_atr", "ge1", "ge2", "ge05", "ge1_clean", "bounce_first", "pen_zone", "bars_to_reach", "tap_i", "top", "bottom", "price", "atr_sel"]


def load_training(pattern: str = "models/train_*.pkl") -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Return (meta, features) frames of the reached candidates, aligned by position."""
    metas, feats = [], []
    for p in sorted(glob.glob(pattern)):
        d = pd.read_pickle(p)
        d = d[d.reached == True]
        fcols = [c for c in d.columns if c.startswith("f__")]
        if not fcols and "features" in d.columns:            # legacy dict layout
            f = pd.DataFrame(list(d.features)).astype("float32")
        else:
            f = d[fcols].copy()
            f.columns = [c[3:] for c in fcols]
        metas.append(d[[c for c in META_KEEP if c in d.columns]].reset_index(drop=True))
        feats.append(f.reset_index(drop=True))
        del d
    meta = pd.concat(metas, ignore_index=True)
    fx = pd.concat(feats, ignore_index=True).astype("float32")
    meta["sel_time"] = pd.to_datetime(meta.sel_time)
    meta["side"] = np.where(meta.direction == "bullish", "below", "above")
    for c in ("ge1", "ge2", "ge05", "ge1_clean", "bounce_first", "closest"):
        if c in meta.columns:
            meta[c] = meta[c].astype(bool)
    return meta, fx
