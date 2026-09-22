#!/usr/bin/env python3
"""Re-price cached study / comparison results with the *imputed* spread.

Older result pickles were produced when bars without an exported spread paid
spread 0 (or a flat floor).  ``load_mt5_csv`` now fills those bars with the
typical spread of the same (weekday, NY hour) taken from the bars that do carry
one, so this script looks up the new spread at each touch minute and shifts every
net-R column by the cost difference.  Idempotent: running it twice changes nothing.

    python rescore_imputed_spread.py --csv data.csv study_results/compare_closest.pkl [more.pkl ...]
"""
import argparse

import numpy as np
import pandas as pd

from lubot import load_mt5_csv
from lubot.study import SCENARIOS

ap = argparse.ArgumentParser()
ap.add_argument("--csv", required=True)
ap.add_argument("pickles", nargs="+")
a = ap.parse_args()

m1 = load_mt5_csv(a.csv)
spread = m1["spread"]
for path in a.pickles:
    df = pd.read_pickle(path)
    r = df.reached.to_numpy()
    touch = pd.to_datetime(df.touch_time)
    new = spread.reindex(touch[r]).ffill().to_numpy(dtype=float)
    new = np.where(np.isfinite(new), new, float(spread.median()))
    old = df.loc[r, "spread"].to_numpy(dtype=float)
    delta = new - old
    risk_basic = (df.loc[r, "zone_h"] + 0.1 * df.loc[r, "atr_at_selection"]).to_numpy()
    df.loc[r, "net_r_1"] = df.loc[r, "net_r_1"].to_numpy() - delta / risk_basic
    df.loc[r, "net_r_2"] = df.loc[r, "net_r_2"].to_numpy() - delta / risk_basic
    for name, entry, slb, tp in SCENARIOS:
        col = f"sc_{name}"
        if col not in df:
            continue
        risk = df.loc[r, "zone_h"].to_numpy() * (1.0 if entry == "edge" else 0.5) + slb * df.loc[r, "atr_at_selection"].to_numpy()
        df.loc[r, col] = df.loc[r, col].to_numpy() - delta / risk
    df.loc[r, "spread"] = new
    df.to_pickle(path)
    print(f"{path}: {int(r.sum())} reached, spread {old.mean():.3f} -> {new.mean():.3f} "
          f"({int((delta != 0).sum())} touches re-priced)")
