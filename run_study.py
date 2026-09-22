#!/usr/bin/env python3
"""Run the full POI bounce study on a CSV and write all tables + charts.

    python run_study.py --csv data.csv --out study_results [--timeframes M5,M10,M15,M30,H1]
"""
import argparse
import pickle
import time
from pathlib import Path

import pandas as pd

from lubot import StrategyConfig, load_mt5_csv
from lubot.study import run_study, save_study

pd.set_option("display.width", 300)
pd.set_option("display.max_columns", 60)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--csv", required=True)
    p.add_argument("--out", default="study_results")
    p.add_argument("--timeframes", default="M5,M10,M15,M30,H1")
    p.add_argument("--hold", type=int, default=300, help="HTF bars to follow after the touch")
    p.add_argument("--wait", type=int, default=300, help="HTF bars to wait for the touch")
    p.add_argument("--set", dest="overrides")
    a = p.parse_args()

    cfg = StrategyConfig(timeframes=tuple(a.timeframes.split(",")))
    if a.overrides:
        from bot import apply_overrides
        cfg = apply_overrides(cfg, a.overrides)
    m1 = load_mt5_csv(a.csv)
    spread = m1["spread"] if "spread" in m1 else pd.Series(0.0, index=m1.index)
    ohlc = m1[["open", "high", "low", "close", "volume"]]
    from bot import spread_note
    print(f"{len(m1)} M1 bars {m1.index[0]} -> {m1.index[-1]}  |  {spread_note(m1)}")
    t0 = time.time()
    res = run_study(ohlc, spread, cfg, max_wait_bars=a.wait, hold_bars=a.hold)
    print(f"study done in {time.time() - t0:.0f}s")
    out = Path(a.out)
    tables = save_study(res, out)
    with open(out / "touches.pkl", "wb") as f:
        pickle.dump(res["df"], f)
    res["df"].to_csv(out / "touches.csv", index=False)
    for name in ("overall", "by_tf", "by_type", "by_direction", "by_session", "scenarios_all"):
        print(f"\n### {name}\n{tables[name].to_string()}")


if __name__ == "__main__":
    main()
