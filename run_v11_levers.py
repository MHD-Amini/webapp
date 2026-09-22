#!/usr/bin/env python3
"""v11 step 2 - LEVER GRID A: relax the existing gates one at a time and measure trades vs loss profile.

Reference = v10 trader (G ladder 25 % x4 @ 0.6/1.2/2.4/4.8R, BE after leg 1, v8 filter, loss rules) on the full-year
streams Sep 2025 -> Sep 2026: 251 trades, +80.7 %, max DD 5.5 %, PF 1.75, win 69 %, worst day -1.9 %.

Every variant changes ONE thing (step 2) or a combination (step 4, --combos) and is run through the same simulator.
Resumable: one json per variant in study_results/v11_levers/, summary -> study_results/v11_levers.csv.

    python run_v11_levers.py --csv data/xauusd_m1.csv [--combos] [--workers 2]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backtest_trader import load_selections, spec_override  # noqa: E402
from lubot import load_mt5_csv  # noqa: E402
from lubot.execution import SymbolSpec, TraderConfig  # noqa: E402
from lubot.portfolio_sim import PortfolioSimulator  # noqa: E402
from run_rm_study import KEYS  # noqa: E402
from run_v10_study import BASE  # noqa: E402

TFS = ("M5", "M10", "M15", "M30", "H1")
G_LADDER = "tp_levels=0.6|1.2|2.4|4.8,tp_fracs=1|1|1|1"
RULES = "max_daily_loss_pct=4.5,max_total_loss_pct=9.0"
REF_T = ",".join([BASE, G_LADDER, RULES])
OUT = Path("study_results/v11_levers")
OOS_SPLIT = "2026-03-01"

# reference filter, decomposed so single gates can be changed
REF_M5 = {"max_cost_r": 0.08, "min_quality": 0.55, "sessions": "asia|london|preny|ny|lclose"}
REF_HTF = {"M10": 0.60, "M15": 0.60, "M30": 0.60, "H1": 0.60}


def make_filter(m5: dict | None = None, htf: dict | None = None, extra: dict | None = None) -> str:
    """Build the filter string.  m5: overrides of REF_M5 (None value = drop the rule); htf: TF -> min_quality
    (None = no quality rule); extra: TF -> extra 'k=v;k=v' text."""
    m5d = {**REF_M5, **(m5 or {})}
    htfd = {**REF_HTF, **(htf or {})}
    extra = extra or {}
    parts = []
    m5_rules = [f"{k}={v}" for k, v in m5d.items() if v is not None]
    if extra.get("M5"):
        m5_rules.append(extra["M5"])
    if m5_rules:
        parts.append("M5:" + ";".join(m5_rules))
    for tf in ("M10", "M15", "M30", "H1"):
        rules = []
        if htfd.get(tf) is not None:
            rules.append(f"min_quality={htfd[tf]}")
        if extra.get(tf):
            rules.append(extra[tf])
        if rules:
            parts.append(f"{tf}:" + ";".join(rules))
    return "/".join(parts)


def variants_single() -> dict[str, tuple[str, str]]:
    """name -> (filter string, extra trader overrides)."""
    v: dict[str, tuple[str, str]] = {"ref": (make_filter(), "")}
    # --- M5 gates
    for q in (0.53, 0.52, 0.50, None):
        v[f"m5_q{q if q is not None else 'off'}"] = (make_filter(m5={"min_quality": q}), "")
    for c in (0.10, 0.12, 0.15, 0.20, None):
        v[f"m5_cost{c if c is not None else 'off'}"] = (make_filter(m5={"max_cost_r": c}), "")
    v["m5_all_sessions"] = (make_filter(m5={"sessions": None}), "")
    # --- higher-timeframe quality gates, one TF at a time
    for tf in ("M10", "M15", "M30", "H1"):
        for q in (0.57, 0.55, 0.52, None):
            v[f"{tf.lower()}_q{q if q is not None else 'off'}"] = (make_filter(htf={tf: q}), "")
    # --- all HTFs together
    for q in (0.57, 0.55, 0.52):
        v[f"htf_all_q{q}"] = (make_filter(htf={tf: q for tf in REF_HTF}), "")
    # --- HTF: replace the quality gate by a cost gate (what made M5 work)
    for tf in ("M10", "M15"):
        for c in (0.06, 0.08):
            v[f"{tf.lower()}_q0.55_cost{c}"] = (make_filter(htf={tf: 0.55}, extra={tf: f"max_cost_r={c}"}), "")
            v[f"{tf.lower()}_qoff_cost{c}"] = (make_filter(htf={tf: None}, extra={tf: f"max_cost_r={c}"}), "")
    # --- portfolio / order-handling levers (trader overrides)
    for d in (0.75, 0.9, 1.01):
        v[f"dedupe{d}"] = (make_filter(), f"dedupe_overlap={d}")
    for n in (6, 8):
        v[f"open{n}"] = (make_filter(), f"max_open_positions={n}")
    for nb in (10, 20, 50, 100):
        v[f"persist{nb}"] = (make_filter(), f"order_policy=persist,max_pending_bars={nb}")
    v["repoi"] = (make_filter(), "one_trade_per_poi=false")
    for off in (-0.1, -0.2, -0.3):
        v[f"entry_front{abs(off)}"] = (make_filter(), f"entry_offset_frac={off}")
    for off in (0.1, 0.2):
        v[f"entry_deep{off}"] = (make_filter(), f"entry_offset_frac={off}")
    return v


def run_one(name: str, flt: str, over: str, m1, sel, extra_s: str = "", tag: str = "", out: Path = OUT) -> dict:
    key = f"{name}{('__' + tag) if tag else ''}"
    f = out / f"{key}.json"
    if f.exists():
        try:
            return json.load(open(f))
        except Exception:
            pass
    t0 = time.time()
    tcfg = TraderConfig().override(",".join(x for x in (REF_T, over) if x))
    tcfg.trade_filter = flt
    spec = spec_override(SymbolSpec(), extra_s)
    res = PortfolioSimulator(m1, sel, tcfg, spec).run()
    s = res.summary()
    row = {"key": key, "name": name, "tag": tag, "filter": flt, "overrides": over, **{k: s.get(k) for k in KEYS}}
    row.update({"pending_placed": s.get("pending_placed"), "cancelled": s.get("cancelled"),
                "daily_halts": s.get("daily_halts"), "halted": s.get("halted")})
    tr = res.trades
    if len(tr):
        tr = tr.assign(month=tr.close_time.dt.strftime("%Y-%m"))
        for lab, part in (("IS", tr[tr.close_time < OOS_SPLIT]), ("OOS", tr[tr.close_time >= OOS_SPLIT])):
            row[f"{lab}_n"] = len(part)
            row[f"{lab}_R"] = round(part.r_net.sum(), 2)
            row[f"{lab}_net_$"] = round(part.net.sum(), 2)
            row[f"{lab}_win_%"] = round(100 * (part.net > 0).mean(), 1) if len(part) else np.nan
            row[f"{lab}_PF"] = round(part[part.net > 0].net.sum() / abs(part[part.net < 0].net.sum()), 3) if (part.net < 0).any() else np.inf
            row[f"{lab}_avg_R"] = round(part.r_net.mean(), 4) if len(part) else np.nan
        eq = res.equity.equity
        row["max_dd_%"] = round(100 * (eq / eq.cummax() - 1).min(), 2)
        row["months_pos"] = int((tr.groupby("month").net.sum() > 0).sum())
        row["months"] = int(tr.month.nunique())
        row["worst_month_$"] = round(tr.groupby("month").net.sum().min(), 2)
        row["worst_day_%"] = round(100 * eq.resample("1D").last().dropna().pct_change().min(), 2)
        day_start = eq.groupby(eq.index.date).transform("first")
        row["worst_intraday_%"] = round(100 * (eq / day_start - 1).min(), 2)
        row["by_tf_n"] = tr.groupby("tf").size().to_dict()
        row["by_tf_R"] = tr.groupby("tf").r_net.sum().round(2).to_dict()
        row["outcomes"] = tr.outcome.value_counts().to_dict()
        row["monthly_$"] = tr.groupby("month").net.sum().round(2).to_dict()
        # loss-streak statistic: longest run of consecutive net-losing trades
        l = (tr.net < 0).astype(int).to_numpy()
        best = cur = 0
        for x in l:
            cur = cur + 1 if x else 0
            best = max(best, cur)
        row["max_consec_losses"] = int(best)
        tr.to_csv(out / f"{key}_trades.csv", index=False)
    res.equity.to_csv(out / f"{key}_equity.csv")
    row["secs"] = round(time.time() - t0, 1)
    tmp = out / f"{key}.json.tmp"
    json.dump(row, open(tmp, "w"), indent=1, default=str)
    os.replace(tmp, f)
    return row


_G: dict = {}


def _init(csv: str, start: str):
    m1 = load_mt5_csv(csv)[start:]
    sel = pd.concat([load_selections(f"study_results/sel_v10_{tf}.pkl") for tf in TFS],
                    ignore_index=True).sort_values("t", kind="stable").reset_index(drop=True)
    _G["m1"], _G["sel"] = m1, sel


def _job(args):
    name, flt, over = args
    return run_one(name, flt, over, _G["m1"], _G["sel"])


def summarize(rows: list[dict], ref_name: str = "ref", path: str = "study_results/v11_levers.csv") -> pd.DataFrame:
    df = pd.DataFrame(rows)
    ref = df[df.name == ref_name].iloc[0]
    df["d_trades"] = df.trades - ref.trades
    df["d_ret"] = (df["return_%"] - ref["return_%"]).round(1)
    df["d_dd"] = (df["max_dd_%"] - ref["max_dd_%"]).round(2)          # negative = deeper drawdown
    df["d_pf"] = (df.profit_factor - ref.profit_factor).round(3)
    df["d_win"] = (df["win_%"] - ref["win_%"]).round(1)
    # "loss profile maintained": DD not deeper than ref + 0.5 pt, PF >= ref - 0.05, win >= ref - 3, worst day >= ref - 0.5
    df["hold_loss"] = (df["max_dd_%"] >= ref["max_dd_%"] - 0.5) & (df.profit_factor >= ref.profit_factor - 0.05) & \
                      (df["win_%"] >= ref["win_%"] - 3.0) & (df["worst_day_%"] >= ref["worst_day_%"] - 0.5)
    df["ret_dd"] = (df["return_%"] / df["max_dd_%"].abs()).round(2)
    df = df.sort_values("trades", ascending=False)
    df.to_csv(path, index=False)
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="data/xauusd_m1.csv")
    ap.add_argument("--from", dest="start", default="2025-09-01")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--only", default="", help="comma list of variant names")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    v = variants_single()
    if a.only:
        v = {k: v[k] for k in a.only.split(",")}
    todo = [(k, f, o) for k, (f, o) in v.items()]
    print(f"{len(todo)} variants, {sum(1 for k, _, _ in todo if not (OUT / f'{k}.json').exists())} to run", flush=True)
    rows = []
    if a.workers > 1:
        with ProcessPoolExecutor(a.workers, initializer=_init, initargs=(a.csv, a.start)) as ex:
            for r in ex.map(_job, todo):
                rows.append(r)
                print(f"{r['key']:<28} n {r['trades']:4d} ret {r['return_%']:+7.1f}% DD {r['max_dd_%']:6.2f}% PF {r['profit_factor']:5.2f} "
                      f"win {r['win_%']:4.1f} wd {r.get('worst_day_%', 0):5.2f} IS {r.get('IS_R', 0):+6.1f}R OOS {r.get('OOS_R', 0):+6.1f}R", flush=True)
    else:
        _init(a.csv, a.start)
        for t in todo:
            r = _job(t)
            rows.append(r)
            print(f"{r['key']:<28} n {r['trades']:4d} ret {r['return_%']:+7.1f}% DD {r['max_dd_%']:6.2f}% PF {r['profit_factor']:5.2f} "
                  f"win {r['win_%']:4.1f} wd {r.get('worst_day_%', 0):5.2f} IS {r.get('IS_R', 0):+6.1f}R OOS {r.get('OOS_R', 0):+6.1f}R", flush=True)
    df = summarize(rows)
    pd.set_option("display.width", 250)
    cols = ["name", "trades", "d_trades", "return_%", "max_dd_%", "profit_factor", "win_%", "worst_day_%", "sl_%", "IS_R", "OOS_R",
            "OOS_PF", "months_pos", "max_consec_losses", "hold_loss"]
    print("\n=== LEVER GRID A (sorted by trades) ===\n" + df[cols].to_string(index=False))


if __name__ == "__main__":
    main()
