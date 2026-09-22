#!/usr/bin/env python3
"""Realistic portfolio backtest of the v7 trader on the recorded selection stream.

    python backtest_trader.py --csv data.csv --sel "study_results/sel_v7_*.pkl" --from 2026-03-01 \
        [--trader risk_pct=1,exec_mode=split,...] [--spec commission_per_lot=7,...] [--out study_results/trader_v7]

Writes <out>_trades.csv, <out>_equity.csv, <out>_summary.json, <out>_by_*.csv and prints the report.
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

import pandas as pd

from lubot import load_mt5_csv
from lubot.execution import SymbolSpec, TraderConfig
from lubot.portfolio_sim import PortfolioSimulator

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 50)


def spec_override(spec: SymbolSpec, text: str | None) -> SymbolSpec:
    if not text:
        return spec
    for pair in text.split(","):
        if not pair.strip():
            continue
        k, v = pair.split("=", 1)
        k = k.strip()
        cur = getattr(spec, k)
        setattr(spec, k, type(cur)(v) if not isinstance(cur, str) else v)
    return spec


def load_selections(pattern: str) -> pd.DataFrame:
    files = sorted(glob.glob(pattern))
    if not files:
        raise SystemExit(f"no selection files match {pattern}")
    parts = [pd.read_pickle(f) for f in files]
    parts = [p for p in parts if len(p)]
    df = pd.concat(parts, ignore_index=True).sort_values("t").reset_index(drop=True)
    print(f"selections: {len(df)} events from {len(files)} files, TFs {sorted(df.tf.unique())}, "
          f"{df.t.min()} -> {df.t.max()}", flush=True)
    return df


def run(m1: pd.DataFrame, sel: pd.DataFrame, tcfg: TraderConfig, spec: SymbolSpec, start, end, be_delay=0,
        progress=False):
    sim = PortfolioSimulator(m1, sel, tcfg, spec, be_delay_bars=be_delay, start=start, end=end)
    return sim.run(progress=progress)


def report(res, out: Path | None, title: str = "") -> dict:
    s = res.summary()
    print(f"\n===== {title or 'TRADER BACKTEST'} =====")
    for k, v in s.items():
        print(f"  {k:<18} {v}")
    if len(res.trades):
        print("\n--- by timeframe ---\n" + res.by("tf").to_string())
        print("\n--- by POI type ---\n" + res.by("kind").to_string())
        print("\n--- by side ---\n" + res.by("side").to_string())
        print("\n--- by grade ---\n" + res.by("grade").to_string())
        print("\n--- by outcome ---\n" + res.trades.groupby("outcome").agg(n=("net", "size"), avg_R=("r_net", "mean"),
                                                                              net=("net", "sum")).round(3).to_string())
        print("\n--- monthly ---\n" + res.monthly().to_string())
        print("\n--- skipped plans ---\n" + res.skipped_reasons().to_string())
        print("\n--- cancelled pending orders ---\n" + res.cancel_reasons().to_string())
        if len(res.filter_reasons()):
            print("\n--- v8 trade filter rejections ---\n" + res.filter_reasons().to_string())
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        res.trades.to_csv(f"{out}_trades.csv", index=False)
        res.equity.to_csv(f"{out}_equity.csv")
        json.dump({"summary": s, "trader": res.tcfg.to_dict(), "spec": res.sim.spec.__dict__},
                  open(f"{out}_summary.json", "w"), indent=1, default=str)
        for col in ("tf", "kind", "side", "grade"):
            if len(res.trades):
                res.by(col).to_csv(f"{out}_by_{col}.csv")
        if len(res.trades):
            res.monthly().to_csv(f"{out}_by_month.csv")
        print(f"\n-> {out}_trades.csv / _equity.csv / _summary.json")
    return s


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--sel", default="study_results/sel_v7_*.pkl", help="glob of recorded selection pickles")
    ap.add_argument("--from", dest="start", default="2026-03-01")
    ap.add_argument("--to", dest="end", default=None)
    ap.add_argument("--trader", default=None, help="TraderConfig overrides key=value,...")
    ap.add_argument("--spec", default=None, help="SymbolSpec overrides key=value,...")
    ap.add_argument("--be-delay", type=int, default=0, help="minutes between TP1 fill and the BE modification (bot latency)")
    ap.add_argument("--out", default="study_results/trader_v7")
    ap.add_argument("--progress", action="store_true")
    a = ap.parse_args(argv)

    m1 = load_mt5_csv(a.csv)
    sel = load_selections(a.sel)
    tcfg = TraderConfig().override(a.trader)
    spec = spec_override(SymbolSpec(), a.spec)
    print("trader:", {k: v for k, v in tcfg.to_dict().items()})
    from lubot.trade_filter import TradeFilter
    print("trade filter:", TradeFilter.parse(tcfg.trade_filter).describe())
    print("spec:", spec)
    res = run(m1, sel, tcfg, spec, a.start, a.end, a.be_delay, a.progress)
    report(res, Path(a.out))


if __name__ == "__main__":
    main()
