#!/usr/bin/env python3
"""v14-A portfolio backtest on EURUSD (pips) through the single-file bot's M1 simulator.

    python backtest_eurusd.py [--trader "..."] [--filter "..."] [--out out/eurusd_v14a]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from pathlib import Path

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lubot_trader_v14_single as lu  # noqa: E402
from eurusd_tools import CSV, eurusd_spec, load_eurusd  # noqa: E402

SEL_GLOB = os.path.join(HERE, "study_results", "sel_eurusd_*.pkl")


def load_sel(pattern: str = SEL_GLOB) -> pd.DataFrame:
    files = sorted(glob.glob(pattern))
    if not files:
        raise SystemExit(f"no selection files match {pattern}")
    parts = [p for p in (pd.read_pickle(f) for f in files) if len(p)]
    return pd.concat(parts, ignore_index=True).sort_values("t", kind="stable").reset_index(drop=True)


def summary_line(s: dict) -> str:
    return (f"trades {s['trades']:4d} | ret {s['return_%']:+8.2f} % | DD {s['max_dd_%']:6.2f} % | PF {s['profit_factor']:.3f} "
            f"| win {s['win_%']:.1f} % | end {s['end_balance']:.0f}")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=CSV)
    ap.add_argument("--sel", default=SEL_GLOB)
    ap.add_argument("--from", dest="start", default=None)
    ap.add_argument("--to", dest="end", default=None)
    ap.add_argument("--risk", type=float, default=1.0)
    ap.add_argument("--trader", default="", help="extra TraderConfig overrides on top of v14-A")
    ap.add_argument("--filter", default=None, help="replace the v14-A trade filter")
    ap.add_argument("--cfilter", default=None, help="replace the v14-A confluence filter")
    ap.add_argument("--commission", type=float, default=7.0)
    ap.add_argument("--out", default=os.path.join(HERE, "out", "eurusd_v14a"))
    a = ap.parse_args(argv)
    m1 = load_eurusd(a.csv, a.start, a.end)
    sel = load_sel(a.sel)
    print(f"m1 {len(m1)} bars {m1.index[0]} -> {m1.index[-1]} | sel {len(sel)} events TFs {sorted(sel.tf.unique())}", flush=True)
    tcfg = lu.v14a_config(a.trader, a.risk)
    if a.filter is not None:
        tcfg.trade_filter = a.filter
    if a.cfilter is not None:
        tcfg.confluence_filter = a.cfilter
    res = lu.PortfolioSimulator(m1, sel, tcfg, eurusd_spec(a.commission)).run()
    s = res.summary()
    print("\n===== EURUSD BACKTEST =====")
    print(summary_line(s))
    for k, v in s.items():
        print(f"  {k:<20} {v}")
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    res.trades.to_csv(f"{a.out}_trades.csv", index=False)
    res.equity.to_csv(f"{a.out}_equity.csv")
    json.dump(s, open(f"{a.out}_summary.json", "w"), indent=1, default=str)
    if len(res.trades):
        t = res.trades.copy()
        t["month"] = pd.to_datetime(t["close_time"]).dt.to_period("M").astype(str)
        print("\nby month:")
        print(t.groupby("month").agg(n=("net", "size"), net=("net", "sum"), r=("r_net", "sum")).round(2).to_string())
        print("\nby tf:")
        print(t.groupby("tf").agg(n=("net", "size"), net=("net", "sum"), r=("r_net", "sum"), win=("net", lambda x: (x > 0).mean())).round(2).to_string())
        print("\nby side:")
        print(t.groupby("side").agg(n=("net", "size"), net=("net", "sum"), r=("r_net", "sum")).round(2).to_string())
        print("\nby outcome:")
        print(t.groupby("outcome").agg(n=("net", "size"), net=("net", "sum")).round(2).to_string())
        print("\nfilter reasons:")
        print(res.filter_reasons().head(12).to_string())
    print(f"-> {a.out}_trades.csv / _equity.csv / _summary.json")
    return s


if __name__ == "__main__":
    main()
