#!/usr/bin/env python3
"""Liquidity University POI bot - command line entry point.

    python bot.py backtest --csv data.csv [--out backtest_results] [--plots]
    python bot.py scan     --csv data.csv [--at "2026-09-03 15:00"] [--plots]
    python bot.py live     [--symbol XAUUSD.t] [--login .. --password .. --server ..]
                           [--interval 60] [--once] [--json out.json]

`scan` and `live` print, for every timeframe (M5, M10, M15, M30, H1), exactly
two POIs: the closest qualifying POI above price and the closest below.  If a
side has no qualifying POI the bot prints "none - waiting".
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, fields
from pathlib import Path
from typing import Dict, Optional

import pandas as pd

from lubot import MultiTimeframeScanner, StrategyConfig, load_mt5_csv
from lubot.backtest import run_backtest, save_results

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 40)


# ----------------------------------------------------------------- helpers
def apply_overrides(cfg: StrategyConfig, overrides: Optional[str]) -> StrategyConfig:
    """--set key=value,key=value"""
    if not overrides:
        return cfg
    valid = {f.name: f.type for f in fields(cfg)}
    for pair in overrides.split(","):
        k, v = pair.split("=", 1)
        k = k.strip()
        if k not in valid:
            raise SystemExit(f"unknown config key {k}")
        cur = getattr(cfg, k)
        if isinstance(cur, bool):
            val = v.strip().lower() in ("1", "true", "yes")
        elif isinstance(cur, int):
            val = int(v)
        elif isinstance(cur, float):
            val = float(v)
        elif isinstance(cur, tuple):
            val = tuple(x.strip() for x in v.split("|"))
        else:
            val = v
        setattr(cfg, k, val)
    return cfg


def fmt_poi(d: Optional[Dict]) -> str:
    if not d:
        return "none - waiting"
    liq = ", ".join(d["liquidity_between"][:4])
    ctx = d.get("context", {})
    of = f"OF near {int(ctx.get('of_near', 0))}/recent {int(ctx.get('of_recent', 0))}" if ctx else f"OF x{d['orderflow_count']}"
    q = f"  P(bounce>=1ATR)={d['quality']:.0%}" if d.get("quality") is not None else ""
    grade = f" [{d['grade']}]" if d.get("grade") else ""
    if d.get("stage") == "approach":
        grade += " (approach)"
    htf = ""
    if ctx.get("htf_confluence"):
        htf = "  HTF-confluence"
    elif ctx.get("htf_bias_aligned", 0) > 0:
        htf = "  HTF-aligned"
    behind = f"  liq-behind {int(ctx['liq_behind_n'])}" if ctx.get("liq_behind_n") else ""
    return (f"{d['type']:<3} {d['direction']:<7} zone {d['bottom']:.2f} - {d['top']:.2f}  "
            f"(mid {d['mid']:.2f}, key {d['key_level']})  dist {d['distance']:.2f} ({d['distance_atr']} ATR){q}{grade}  "
            f"{of}{htf}{behind}  liq->[{liq}]  {d['time']}")


def fmt_indicators(d: Optional[Dict]) -> str:
    """v5 - one-line indicator picture of the zone (all values oriented to the zone's
    direction: '+' favours a bounce from it)."""
    ctx = (d or {}).get("context", {})
    if not ctx or "ind_rsi_aligned" not in ctx:
        return ""
    bull = d["direction"] == "bullish"
    rsi = 50.0 - ctx["ind_rsi_aligned"] if bull else 50.0 + ctx["ind_rsi_aligned"]
    parts = [f"RSI {rsi:.0f}" + (" div" if ctx.get("ind_rsi_div_regular") else ""),
             f"ADX {ctx['ind_adx']:.0f}" + (" trend-with" if ctx["ind_di_aligned"] > 5 else " trend-against" if ctx["ind_di_aligned"] < -5 else ""),
             "zone beyond BB" if ctx.get("ind_zone_beyond_bb") else "zone inside BB",
             "BB squeeze" if ctx.get("ind_bb_squeeze") else None,
             f"MA-conf x{int(ctx['ind_zone_at_ma'])}" if ctx.get("ind_zone_at_ma") else None,
             "VWAP band" if ctx.get("ind_zone_at_vwap_band") else None,
             "pivot" if ctx.get("ind_zone_at_pivot") else None,
             "OTE" if ctx.get("ind_zone_in_ote") else None,
             "ST aligned" if ctx.get("ind_supertrend_aligned", 0) > 0 else "ST against",
             f"HTF RSI {50 - ctx['htf_rsi_aligned'] if bull else 50 + ctx['htf_rsi_aligned']:.0f}" if "htf_rsi_aligned" in ctx else None,
             f"relvol {ctx['ind_relvol']:.1f}" if ctx.get("ind_relvol", 1.0) != 1.0 else None,
             f"ATR pct {ctx['ind_atr_pctile']:.0%}"]
    return "  |  ".join(p for p in parts if p)


def fmt_levels(d: Optional[Dict]) -> str:
    """v6 - one-line *level memory* picture of the zone: how the market treated this price
    area before (reversals in the zone direction vs. slices through it, visits, value area,
    volume node)."""
    ctx = (d or {}).get("context", {})
    if not ctx or "lv_rev_with" not in ctx:
        return ""
    rw, ra = int(ctx["lv_rev_with"]), int(ctx["lv_rev_against"])
    dens = ctx.get("lv_vol_density", 1.0)
    node = "LVN" if dens < 0.6 else "HVN" if dens > 1.4 else "mid-volume"
    parts = [f"reversals here {rw} with / {ra} against",
             f"rev/visit {ctx['lv_rev_per_visit']:.2f}",
             f"sliced {ctx['lv_slice_frac']:.0%} of visits",
             f"last visit {int(ctx['lv_bars_since_visit'])} bars ago",
             f"{node} (x{dens:.1f})",
             "outside value area" if ctx.get("lv_zone_outside_va") else ("at VA edge" if ctx.get("lv_zone_at_va_edge") else "inside value area"),
             "POC beyond zone" if ctx.get("lv_poc_beyond") else None,
             f"HTF reversals {int(ctx['hlv_rev_with'])}" if "hlv_rev_with" in ctx else None]
    return "  |  ".join(p for p in parts if p)


def print_scan(result: Dict[str, Dict]) -> None:
    for tf, r in result.items():
        print(f"\n=== {tf} | {r['time']} | price {r['price']:.2f} | range {r['range_bias']} ({r['price_zone']}) "
              f"| candidates above {r['candidates_above']} / below {r['candidates_below']}")
        print(f"  ABOVE: {fmt_poi(r['above'])}")
        print(f"  BELOW: {fmt_poi(r['below'])}")
        for side in ("above", "below"):
            d = r[side]
            if d and d.get("why"):
                print(f"         {side} drivers: " + ", ".join(f"{k} {v:+.2f}" for k, v in d["why"]))
            ind = fmt_indicators(d)
            if ind:
                print(f"         {side} indicators: {ind}")
            lv = fmt_levels(d)
            if lv:
                print(f"         {side} level memory: {lv}")


def make_plots(scanner: MultiTimeframeScanner, result: Dict[str, Dict], out_dir: Path, bars: int = 250) -> None:
    from lubot.plotting import plot_engine
    out_dir.mkdir(parents=True, exist_ok=True)
    for tf, e in scanner.engines.items():
        p = plot_engine(e, result[tf], out_dir / f"{tf}.png", bars=bars)
        print(f"  chart -> {p}")


# ---------------------------------------------------------------- commands
def spread_note(m1: pd.DataFrame) -> str:
    """One-line description of the spread column (real vs imputed bars)."""
    if "spread" not in m1:
        return "no spread column"
    if "spread_imputed" in m1 and m1["spread_imputed"].any():
        real = m1.loc[~m1["spread_imputed"], "spread"]
        return (f"spread: {int((~m1['spread_imputed']).sum())} bars with broker spread (median ${real.median():.2f}), "
                f"{int(m1['spread_imputed'].sum())} bars without -> filled from the (weekday, NY-hour) profile")
    return f"spread: median ${m1['spread'].median():.2f} on every bar"


def cmd_backtest(a: argparse.Namespace, cfg: StrategyConfig) -> None:
    m1 = load_mt5_csv(a.csv)
    print(f"loaded {len(m1)} M1 bars  {m1.index[0]} -> {m1.index[-1]}  |  {spread_note(m1)}")
    res = run_backtest(m1, cfg, warmup_bars=a.warmup)
    print("\n" + res["stats"].to_string())
    out = Path(a.out)
    save_results(res, out)
    print(f"\nresults -> {out}/stats.csv, trades.csv, selections.json")
    if a.plots:
        final = {tf: e.select().to_dict() for tf, e in res["scanner"].engines.items()}
        make_plots(res["scanner"], final, out / "charts", bars=a.bars)


def cmd_scan(a: argparse.Namespace, cfg: StrategyConfig) -> None:
    m1 = load_mt5_csv(a.csv)
    if a.at:
        m1 = m1[: pd.Timestamp(a.at)]
    print(f"loaded {len(m1)} M1 bars  {m1.index[0]} -> {m1.index[-1]}  |  {spread_note(m1)}")
    scanner = MultiTimeframeScanner(m1, cfg)
    result = scanner.scan()
    print_scan(result)
    if a.json:
        Path(a.json).write_text(json.dumps(result, indent=1))
        print(f"\njson -> {a.json}")
    if a.plots:
        make_plots(scanner, result, Path(a.out) / "charts", bars=a.bars)


def cmd_live(a: argparse.Namespace, cfg: StrategyConfig) -> None:
    from lubot.mt5_connector import MT5Connector, wait_for_next_minute

    cfg.symbol = a.symbol
    conn = MT5Connector(a.symbol, a.login, a.password, a.server, a.path)
    if a.server_offset is None:
        cfg.server_utc_offset_hours = conn.server_utc_offset_hours()
    else:
        cfg.server_utc_offset_hours = a.server_offset
    print(f"connected. symbol={a.symbol} server UTC offset={cfg.server_utc_offset_hours:+.1f}h")
    m1 = conn.m1_history(a.history)
    print(f"history: {len(m1)} M1 bars {m1.index[0]} -> {m1.index[-1]}")
    last_state = None
    try:
        while True:
            # refresh the tail of the history (last 3 days) and merge
            fresh = conn.m1_since(m1.index[-1] - pd.Timedelta(days=3))
            if len(fresh):
                m1 = pd.concat([m1[m1.index < fresh.index[0]], fresh])
            scanner = MultiTimeframeScanner(m1, cfg)
            price = conn.current_price()
            result = scanner.scan(price=price)
            state = json.dumps({tf: [(r["above"] or {}).get("id"), (r["below"] or {}).get("id"),
                                     (r["above"] or {}).get("top"), (r["below"] or {}).get("top")]
                                for tf, r in result.items()})
            stamp = time.strftime("%Y-%m-%d %H:%M:%S")
            if state != last_state or a.verbose:
                print(f"\n##### {stamp}  {a.symbol} price {price:.2f}")
                print_scan(result)
                last_state = state
            else:
                print(f"{stamp} price {price:.2f} - no change", end="\r")
            if a.json:
                Path(a.json).write_text(json.dumps({"time": stamp, "price": price, "timeframes": result}, indent=1))
            if a.plots:
                make_plots(scanner, result, Path(a.out) / "live_charts", bars=a.bars)
            if a.once:
                break
            if a.interval >= 60:
                wait_for_next_minute(2.0)
                if a.interval > 60:
                    time.sleep(a.interval - 60)
            else:
                time.sleep(a.interval)
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        conn.shutdown()


# -------------------------------------------------------------------- main
def main(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--set", dest="overrides", help="config overrides key=value,key=value (tuples use a|b)")
    p.add_argument("--timeframes", default=None, help="comma list, default M5,M10,M15,M30,H1")
    p.add_argument("--out", default="backtest_results")
    p.add_argument("--plots", action="store_true", help="render charts")
    p.add_argument("--bars", type=int, default=250, help="bars per chart")
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("backtest", help="walk-forward backtest on a CSV export")
    b.add_argument("--csv", required=True)
    b.add_argument("--warmup", type=int, default=300)

    s = sub.add_parser("scan", help="one-off scan of a CSV (optionally at a past time)")
    s.add_argument("--csv", required=True)
    s.add_argument("--at", help='cut the data at this time, e.g. "2026-09-03 15:00"')
    s.add_argument("--json")

    l = sub.add_parser("live", help="connect to MT5 and scan continuously")
    l.add_argument("--symbol", default="XAUUSD.t")
    l.add_argument("--login", type=int)
    l.add_argument("--password")
    l.add_argument("--server")
    l.add_argument("--path", help="path to terminal64.exe")
    l.add_argument("--history", type=int, default=60000, help="M1 bars to load at start")
    l.add_argument("--interval", type=int, default=60, help="seconds between scans")
    l.add_argument("--server-offset", type=float, default=None, help="broker UTC offset hours (auto)")
    l.add_argument("--once", action="store_true")
    l.add_argument("--verbose", action="store_true")
    l.add_argument("--json", help="write latest result to this file")

    a = p.parse_args(argv)
    cfg = StrategyConfig()
    if a.timeframes:
        cfg.timeframes = tuple(x.strip() for x in a.timeframes.split(","))
    cfg = apply_overrides(cfg, a.overrides)
    {"backtest": cmd_backtest, "scan": cmd_scan, "live": cmd_live}[a.cmd](a, cfg)


if __name__ == "__main__":
    main()
