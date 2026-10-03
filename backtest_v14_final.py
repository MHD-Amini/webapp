#!/usr/bin/env python3
"""FINAL BACKTEST of the shipped v14-A trader on the M1 CSV.

The trader strings are READ FROM run_trader.bat (not re-typed), replayed by the realistic portfolio simulator over the
full year Sep 2025 -> Sep 2026 of the user's CSV ($10 000, 1 % base risk, real spread / commission / slippage, the v10
account rules), alongside the v13-A reference (same strings, every mart_* key dropped) so the martingale's effect is
isolated.  Writes:
    study_results/final_v14/v14A_summary.json, v14A_trades.csv, v14A_equity.csv, v14A_monthly.csv, v14A_by_tf.csv,
    study_results/final_v14/ref_*.csv, study_results/charts/final_v14_equity.png,
    study_results/FINAL_BACKTEST_V14.md                                           (every number comes from this run)
    python backtest_v14_final.py [--csv data/xauusd_m1.csv]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lubot.execution import SymbolSpec, TraderConfig  # noqa: E402
from lubot.portfolio_sim import PortfolioSimulator  # noqa: E402
from run_v10_study import BASE  # noqa: E402
from run_v12_funnel import load_year  # noqa: E402
from v14_common import OOS_SPLIT, judge  # noqa: E402

OUT = Path("study_results/final_v14")
CH = Path("study_results/charts")
STUDY_JSON = Path("study_results/v14_levers/TF_1.5_c3_htfbuy_dn0.5.json")


def bat_strings(path: str = "run_trader.bat") -> dict:
    bat = open(path, encoding="utf-8").read()
    line = next(l for l in bat.splitlines() if l.strip().startswith("python trader.py --symbol"))

    def arg(name: str) -> str:
        return re.search(name + r' "([^"]*)"', line).group(1)

    return {"trader": arg("--trader"), "trade_filter": arg("--trade-filter"), "confluence_filter": arg("--confluence-filter"),
            "risk": float(re.search(r"--risk ([0-9.]+)", line).group(1)),
            "commission": float(re.search(r"--commission ([0-9.]+)", line).group(1)),
            "symbol": re.search(r"--symbol (\S+)", line).group(1)}


def strip_mart(trader: str) -> str:
    return ",".join(kv for kv in trader.split(",") if not kv.startswith("mart_") and not kv.startswith("grid_"))


def run(m1, sel, b: dict, trader: str):
    t = TraderConfig(risk_pct=b["risk"], trade_filter=b["trade_filter"], confluence_filter=b["confluence_filter"],
                     max_daily_loss_pct=4.5, max_total_loss_pct=9.0).override(BASE).override(trader)
    t0 = time.time()
    res = PortfolioSimulator(m1, sel, t, SymbolSpec()).run()
    j = judge(res)
    j["secs"] = round(time.time() - t0, 1)
    s = res.summary()
    for k in ("start_balance", "net_profit", "commission_$", "swap_$", "avg_hold_min", "median_hold_min", "avg_lots", "expectancy_$",
              "partial_hit_%", "tp2_%", "partial_be_%", "forced_%", "trades_per_day", "days", "mart_max_scale", "range_trades",
              "confluent_trades", "reentry_trades", "cancelled", "pending_placed"):
        j[k] = s.get(k)
    return res, j


def dump(res, j: dict, name: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    tr = res.trades.assign(month=res.trades.close_time.dt.strftime("%Y-%m"))
    tr.to_csv(OUT / f"{name}_trades.csv", index=False)
    res.equity.to_csv(OUT / f"{name}_equity.csv")
    mo = tr.groupby("month").agg(trades=("net", "size"), net_usd=("net", "sum"), R=("r_net", "sum"), win_pct=("net", lambda x: 100 * (x > 0).mean()),
                                 losses=("net", lambda x: int((x < 0).sum())), lost_usd=("net", lambda x: x[x < 0].sum()),
                                 up=("mart_step", lambda x: int((x > 0).sum())), down=("mart_step", lambda x: int((x < 0).sum()))).round(2)
    mo.to_csv(OUT / f"{name}_monthly.csv")
    by_tf = res.by("tf")
    by_tf.to_csv(OUT / f"{name}_by_tf.csv")
    json.dump(j, open(OUT / f"{name}_summary.json", "w"), indent=1, default=str)


def md(df: pd.DataFrame, index: bool = True) -> str:
    return df.to_markdown(index=index)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="data/xauusd_m1.csv")
    a = ap.parse_args()
    b = bat_strings()
    print("bat --trader:", b["trader"])
    m1, sel = load_year(a.csv)
    print(f"M1 bars {len(m1):,} {m1.index[0]} -> {m1.index[-1]} | selection events {len(sel):,}")
    res_a, ja = run(m1, sel, b, b["trader"])
    print(f"v14-A: {ja['trades']} tr / {ja['return_%']:+.2f} % / DD {ja['max_dd_%']} / PF {ja['profit_factor']} / up {ja['mart_trades']} dn {ja['mart_down_trades']} [{ja['secs']} s]")
    dump(res_a, ja, "v14A")
    res_r, jr = run(m1, sel, b, strip_mart(b["trader"]))
    print(f"v13-A ref: {jr['trades']} tr / {jr['return_%']:+.2f} % / DD {jr['max_dd_%']} / PF {jr['profit_factor']} [{jr['secs']} s]")
    dump(res_r, jr, "ref")
    identical = None
    if STUDY_JSON.exists():
        st = json.load(open(STUDY_JSON))
        identical = (ja["trades"], ja["return_%"], ja["max_dd_%"], ja["profit_factor"]) == (st["trades"], st["return_%"], st["max_dd_%"], st["profit_factor"])
        print("identical to the v14 study json:", identical)

    # ---- chart
    CH.mkdir(exist_ok=True)
    fig, ax = plt.subplots(2, 1, figsize=(12, 8), sharex=True, gridspec_kw={"height_ratios": [3, 1]})
    for res, j, lab, col in ((res_r, jr, "v13-A reference (flat 1 %)", "tab:blue"), (res_a, ja, "v14-A asymmetric martingale (run_trader.bat)", "tab:red")):
        eq = res.equity.equity
        ax[0].plot(eq.index, eq.values, color=col, lw=1.2, label=f"{lab}: {j['return_%']:+.1f} %, DD {j['max_dd_%']:.2f} %, PF {j['profit_factor']:.2f}, lost {j['gross_loss_$']:,.0f} $")
        ax[1].plot(eq.index, (eq / eq.cummax() - 1) * 100, color=col, lw=1.0)
    ax[0].axvline(pd.Timestamp(OOS_SPLIT), color="k", ls="--", lw=0.8)
    ax[0].set_title(f"FINAL BACKTEST v14-A on {Path(a.csv).resolve().name if not Path(a.csv).is_symlink() else os.readlink(a.csv).split('/')[-1]}  "
                    f"— {m1.index[0]:%Y-%m-%d} -> {m1.index[-1]:%Y-%m-%d}, $10 000, 1 % base risk, real costs (dashed = entry model OOS from here)")
    ax[0].set_ylabel("equity $"); ax[0].grid(alpha=.3); ax[0].legend(loc="upper left", fontsize=9)
    ax[1].set_ylabel("drawdown %"); ax[1].grid(alpha=.3)
    fig.tight_layout(); fig.savefig(CH / "final_v14_equity.png", dpi=110); plt.close(fig)

    # ---- report
    tra = pd.read_csv(OUT / "v14A_trades.csv", parse_dates=["entry_time", "close_time"])
    mo_a = pd.read_csv(OUT / "v14A_monthly.csv", index_col=0)
    mo_r = pd.read_csv(OUT / "ref_monthly.csv", index_col=0)
    mo = pd.DataFrame({"trades": mo_a.trades, "v14-A net $": mo_a.net_usd, "v14-A R": mo_a.R, "v14-A win %": mo_a.win_pct.round(1),
                       "v14-A $ lost": mo_a.lost_usd, "up": mo_a.up, "down": mo_a.down,
                       "v13-A net $": mo_r.net_usd, "v13-A $ lost": mo_r.lost_usd})
    by_tf_a = pd.read_csv(OUT / "v14A_by_tf.csv", index_col=0)
    by_tf_r = pd.read_csv(OUT / "ref_by_tf.csv", index_col=0)
    tf = pd.DataFrame({"trades": by_tf_a.trades, "win %": by_tf_a["win_%"], "v14-A net $": by_tf_a["net_$"], "v14-A PF": by_tf_a.PF,
                       "v13-A net $": by_tf_r["net_$"], "v13-A PF": by_tf_r.PF})
    outc = tra.outcome.value_counts()
    up = tra[tra.mart_step > 0]; dn = tra[tra.mart_step < 0]; flat = tra[tra.mart_step == 0]
    steps = pd.DataFrame([{"sizing": k, "trades": len(x), "win %": round(100 * (x.net > 0).mean(), 1) if len(x) else 0, "net $": round(x.net.sum(), 0),
                           "$ lost": round(x[x.net < 0].net.sum(), 0), "avg risk $": round(x.risk_money.mean(), 0) if len(x) else 0,
                           "avg scale": round(x.mart_scale.mean(), 2) if len(x) else 1.0}
                          for k, x in (("base size (no streak)", flat), ("stepped UP (HTF buy after a loss of its TF)", up),
                                       ("stepped DOWN x0.5 (M5 / sell after a loss of its TF)", dn))])
    by_step = tra.groupby("mart_step").agg(trades=("net", "size"), win_pct=("net", lambda x: round(100 * (x > 0).mean(), 1)),
                                           net_usd=("net", lambda x: round(x.sum(), 0)), avg_scale=("mart_scale", lambda x: round(x.mean(), 2)),
                                           max_risk_usd=("risk_money", lambda x: round(x.max(), 0)))
    oos_a = tra[tra.close_time >= OOS_SPLIT]
    worst = tra.nsmallest(5, "net")[["key", "side", "close_time", "regime", "mart_step", "risk_money", "net", "r_net", "outcome"]].round(2)
    cmp_rows = [("trades", "trades", "{:d}"), ("return %", "return_%", "{:+.2f}"), ("end balance $", "end_balance", "{:,.0f}"), ("net profit $", "net_profit", "{:,.0f}"),
                ("max drawdown %", "max_dd_%", "{:.2f}"), ("max drawdown $", "max_dd_$", "{:,.0f}"), ("profit factor", "profit_factor", "{:.3f}"),
                ("win %", "win_%", "{:.1f}"), ("stop-outs %", "sl_%", "{:.1f}"), ("total R", "total_R", "{:.2f}"), ("avg R / trade", "avg_R", "{:.4f}"),
                ("expectancy $ / trade", "expectancy_$", "{:.2f}"), ("gross $ won", "gross_win_$", "{:,.0f}"), ("gross $ lost", "gross_loss_$", "{:,.0f}"),
                ("avg loss $", "avg_loss_$", "{:.1f}"), ("worst trade % of equity", "worst_trade_%eq", "{:.2f}"), ("worst day % of equity", "worst_day_%eq", "{:.2f}"),
                ("negative days", "neg_days", "{:d}"), ("max consecutive losses", "max_consec_losses", "{:d}"), ("ulcer index", "ulcer", "{:.3f}"),
                ("return / max DD", "return_over_dd", "{:.1f}"), ("daily Sharpe", "sharpe_daily", "{:.2f}"), ("max risk % of equity", "max_risk_%eq", "{:.2f}"),
                ("avg risk $", "avg_risk_$", "{:.0f}"), ("commission $", "commission_$", "{:,.0f}"), ("swap $", "swap_$", "{:,.0f}"),
                ("avg hold (min)", "avg_hold_min", "{:.0f}"), ("months positive", "months_pos", "{:d}"), ("worst month $", "worst_month_$", "{:,.0f}"),
                ("IS R (Sep25-Feb26)", "IS_R", "{:.2f}"), ("IS PF", "IS_PF", "{:.3f}"), ("OOS R (Mar-Sep26)", "OOS_R", "{:.2f}"), ("OOS PF", "OOS_PF", "{:.3f}"),
                ("OOS net $", "OOS_net_$", "{:,.0f}"), ("daily-loss halts", "daily_halts", "{:d}"), ("stepped up / down", None, None)]
    cmp = []
    for lab, k, f in cmp_rows:
        if k is None:
            cmp.append({"metric": lab, "v13-A reference": "0 / 0", "v14-A (shipped)": f"{ja['mart_trades']} / {ja['mart_down_trades']}"})
            continue
        va, vr = ja.get(k), jr.get(k)
        fmt = lambda v: f.format(int(v) if f.endswith("d}") else float(v)) if v is not None else "-"
        cmp.append({"metric": lab, "v13-A reference": fmt(vr), "v14-A (shipped)": fmt(va)})
    cmp = pd.DataFrame(cmp)

    L = []
    w = L.append
    csv_name = os.readlink(a.csv).split("/")[-1] if Path(a.csv).is_symlink() else Path(a.csv).name
    w(f"# FINAL BACKTEST — v14-A (asymmetric martingale) on `{csv_name}`\n")
    w(f"*Generated by `backtest_v14_final.py` on {pd.Timestamp.utcnow():%Y-%m-%d %H:%M} UTC.  Trader strings read from `run_trader.bat`; "
      f"simulator `lubot/portfolio_sim.py`; selection streams `study_results/sel_v10_*.pkl` (the v10 recording of the scanner over this CSV).*\n")
    w("## Setup\n")
    w(f"- **Data**: {len(m1):,} M1 bars, {m1.index[0]:%Y-%m-%d %H:%M} -> {m1.index[-1]:%Y-%m-%d %H:%M} (the year used by every v10-v14 study; the CSV "
      f"starts 2025-01-02 and the entry models were trained before the backtest window; the entry model is out-of-sample from {OOS_SPLIT}).")
    w(f"- **Account**: $10 000 start, **{b['risk']:.1f} % base risk** per plan sized on equity, commission {b['commission']:.0f} $/lot round-turn, "
      f"spread from the CSV, SL slippage 0.10 / market 0.05, daily loss limit 4.5 % -> flat until next server day, total loss 9 % -> halt.")
    w(f"- **Trader** (`--trader`): `{b['trader']}`")
    w(f"- **Trade filter**: `{b['trade_filter']}`")
    w(f"- **Confluence filter**: `{b['confluence_filter']}`")
    w(f"- **Reference**: the same strings with every `mart_*` key removed = v13-A.")
    if identical is not None:
        w(f"- **Reproducibility**: result {'IDENTICAL' if identical else 'DIFFERENT'} to the v14 study json `{STUDY_JSON.name}` "
          f"({ja['trades']} tr / {ja['return_%']:+.2f} % / DD {ja['max_dd_%']} / PF {ja['profit_factor']}).")
    w("\n## Result — full year\n")
    w(f"**v14-A: {ja['trades']} trades, {ja['return_%']:+.2f} % ($10 000 -> ${ja['end_balance']:,.0f}), max drawdown {ja['max_dd_%']:.2f} %, "
      f"profit factor {ja['profit_factor']:.3f}, win rate {ja['win_%']:.1f} %, {ja['months_pos']}/{ja['months']} months positive, worst day "
      f"{ja['worst_day_%eq']:.2f} % of equity, max risk on one plan {ja['max_risk_%eq']:.2f} % of equity, OOS PF {ja['OOS_PF']:.2f}.**  "
      f"Against v13-A: return {ja['return_%'] - jr['return_%']:+.1f} pt, $ lost {100 * (ja['gross_loss_$'] / jr['gross_loss_$'] - 1):+.1f} %, "
      f"average loss {100 * (ja['avg_loss_$'] / jr['avg_loss_$'] - 1):+.1f} %, PF {ja['profit_factor'] - jr['profit_factor']:+.3f}, "
      f"max DD {ja['max_dd_%'] - jr['max_dd_%']:+.2f} pt, return/DD {jr['return_over_dd']:.1f} -> {ja['return_over_dd']:.1f}.\n")
    w("![equity](charts/final_v14_equity.png)\n")
    w(md(cmp, index=False))
    w("\n## Month by month\n")
    w(md(mo))
    w("\n## By timeframe\n")
    w(md(tf))
    w("\n## What the martingale did\n")
    w(md(steps, index=False))
    w("\n*by streak step (negative = stepped down):*\n")
    w(md(by_step.rename(columns={"win_pct": "win %", "net_usd": "net $", "avg_scale": "avg scale", "max_risk_usd": "max risk $"})))
    w(f"\nExit outcomes: " + ", ".join(f"{k} {v}" for k, v in outc.items()) + f".  Range-managed trades: {ja['range_trades']}, confluent: {ja['confluent_trades']}, "
      f"re-entries: {ja['reentry_trades']}.  Pending orders placed {ja['pending_placed']}, cancelled unfilled {ja['cancelled']}.")
    w(f"\nOOS half (from {OOS_SPLIT}): {len(oos_a)} trades, net {oos_a.net.sum():,.0f} $, PF {ja['OOS_PF']:.2f}, win {100 * (oos_a.net > 0).mean():.1f} %.\n")
    w("## Five worst trades\n")
    w(md(worst, index=False))
    w("\n## Files\n")
    w("`study_results/final_v14/v14A_summary.json` (all metrics), `v14A_trades.csv` (every trade with `mart_step` / `mart_scale` / legs), `v14A_equity.csv` "
      "(hourly balance + equity), `v14A_monthly.csv`, `v14A_by_tf.csv`, the same four for `ref_*` (v13-A), chart `charts/final_v14_equity.png`.  "
      "Full study: `study_results/MARTINGALE_V14.md`.\n")
    Path("study_results/FINAL_BACKTEST_V14.md").write_text("\n".join(L), encoding="utf-8")
    print("wrote study_results/FINAL_BACKTEST_V14.md")
    os.makedirs("logs", exist_ok=True)
    open("logs/backtest_v14_final.log", "w").write(json.dumps({"v14A": ja, "ref": jr, "identical": identical}, indent=1, default=str))


if __name__ == "__main__":
    main()
