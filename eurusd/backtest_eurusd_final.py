#!/usr/bin/env python3
"""FINAL BACKTEST of the single-file v14-A bot on the EURUSD M1 CSV (mirror of backtest_v14_final.py).

The v14-A strings are the ones embedded in lubot_trader_v14_single.py (V14A_TRADER / filters = run_trader.bat), replayed
by the single file's own PortfolioSimulator over Sep 2025 -> Sep 2026 of the user's EURUSD CSV fed in pips ($10 000,
1 % base risk, CSV spread, 7 $/lot commission, SL slippage 0.1 pip, the v10 account rules).  The v13-A reference (same
strings, every mart_* key dropped) is run alongside so the martingale's effect is isolated.  Writes:
    eurusd/out/final/v14A_*.csv|json, ref_*.csv|json, eurusd/out/final/equity.png, eurusd/FINAL_BACKTEST_EURUSD.md
    python eurusd/backtest_eurusd_final.py [--csv data/eurusd_m1.csv]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

HERE = Path(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, str(HERE))
import lubot_trader_v14_single as lu  # noqa: E402
from backtest_eurusd import load_sel  # noqa: E402
from eurusd_tools import CSV, PIP_SCALE, eurusd_spec, load_eurusd  # noqa: E402

OUT = HERE / "out" / "final"
OOS_SPLIT = "2026-03-01"
XAU_REF = HERE.parent / "study_results" / "final_v14" / "v14A_summary.json"


REF_OVERRIDE = "mart_mode=,mart_tfs=,mart_sides=,mart_ungated_scale=1"   # v14a_config() always applies the mart keys -> switch them off


def _max_run(mask: pd.Series) -> int:
    best = cur = 0
    for v in mask:
        cur = cur + 1 if v else 0
        best = max(best, cur)
    return best


def judge(res, start_balance: float = 10_000.0) -> dict:
    """The v14 scorecard (v14_common.judge) - identical metrics so the EURUSD run reads like the XAUUSD report."""
    s = res.summary()
    tr = res.trades
    out = {k: s.get(k) for k in ("trades", "return_%", "max_dd_%", "max_dd_$", "profit_factor", "win_%", "sl_%", "total_R",
                                 "avg_R", "sharpe_daily", "end_balance", "daily_halts", "halted", "stopped_out")}
    if not len(tr):
        return out
    losses, wins = tr[tr.net < 0], tr[tr.net > 0]
    d = tr.set_index("close_time").net.resample("1D").sum()
    d = d[d != 0]
    eq = res.equity.equity
    tr = tr.assign(month=tr.close_time.dt.strftime("%Y-%m"))
    mo, mo_r = tr.groupby("month").net.sum(), tr.groupby("month").r_net.sum()
    oos, is_ = tr[tr.close_time >= OOS_SPLIT], tr[tr.close_time < OOS_SPLIT]
    pf = lambda x: (x[x.net > 0].net.sum() / abs(x[x.net < 0].net.sum())) if (x.net < 0).any() else float("inf")
    out.update({
        "gross_loss_$": round(losses.net.sum(), 2), "gross_win_$": round(wins.net.sum(), 2),
        "avg_loss_$": round(losses.net.mean(), 2) if len(losses) else 0.0,
        "avg_loss_R": round(losses.r_net.mean(), 3) if len(losses) else 0.0,
        "worst_trade_$": round(tr.net.min(), 2), "worst_trade_%eq": round(100 * tr.net.min() / start_balance, 2),
        "worst_day_$": round(d.min(), 2) if len(d) else 0.0, "worst_day_%": round(100 * d.min() / start_balance, 2) if len(d) else 0.0,
        "neg_days": int((d < 0).sum()), "neg_days_%": round(100 * (d < 0).mean(), 1) if len(d) else 0.0,
        "max_dd_R": s.get("max_dd_R"),
        "ulcer": round(float(np.sqrt(((eq / eq.cummax() - 1) ** 2).mean()) * 100), 3),
        "max_risk_$": round(tr.risk_money.max(), 2), "max_risk_%start": round(100 * tr.risk_money.max() / start_balance, 2),
        "avg_risk_$": round(tr.risk_money.mean(), 2),
        "months_pos": int((mo > 0).sum()), "months": int(len(mo)),
        "worst_month_$": round(mo.min(), 2), "worst_month_R": round(mo_r.min(), 2),
        "IS_n": len(is_), "IS_R": round(is_.r_net.sum(), 2), "IS_PF": round(pf(is_), 3) if len(is_) else 0.0,
        "OOS_n": len(oos), "OOS_R": round(oos.r_net.sum(), 2), "OOS_PF": round(pf(oos), 3) if len(oos) else 0.0,
        "OOS_net_$": round(oos.net.sum(), 2),
        "max_consec_losses": int(_max_run(tr.net < 0)),
        "mart_trades": int((tr.mart_step > 0).sum()), "mart_down_trades": int((tr.mart_step < 0).sum()),
        "return_over_dd": round(s["return_%"] / abs(s["max_dd_%"]), 2) if s.get("max_dd_%") else float("nan"),
    })
    for k in ("start_balance", "net_profit", "commission_$", "swap_$", "avg_hold_min", "median_hold_min", "avg_lots", "expectancy_$",
              "trades_per_day", "days", "mart_max_scale", "range_trades", "confluent_trades", "cancelled", "pending_placed", "skipped"):
        out[k] = s.get(k)
    return out


def run(m1, sel, trader: str, spec):
    t = lu.v14a_config(trader, 1.0)
    t0 = time.time()
    res = lu.PortfolioSimulator(m1, sel, t, spec).run()
    j = judge(res)
    j["secs"] = round(time.time() - t0, 1)
    return res, j


def dump(res, j: dict, name: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    tr = res.trades.assign(month=res.trades.close_time.dt.strftime("%Y-%m"))
    tr.to_csv(OUT / f"{name}_trades.csv", index=False)
    res.equity.to_csv(OUT / f"{name}_equity.csv")
    mo = tr.groupby("month").agg(trades=("net", "size"), net_usd=("net", "sum"), R=("r_net", "sum"),
                                 win_pct=("net", lambda x: 100 * (x > 0).mean()), losses=("net", lambda x: int((x < 0).sum())),
                                 lost_usd=("net", lambda x: x[x < 0].sum()), up=("mart_step", lambda x: int((x > 0).sum())),
                                 down=("mart_step", lambda x: int((x < 0).sum()))).round(2)
    mo.to_csv(OUT / f"{name}_monthly.csv")
    res.by("tf").to_csv(OUT / f"{name}_by_tf.csv")
    json.dump(j, open(OUT / f"{name}_summary.json", "w"), indent=1, default=str)


def md(df: pd.DataFrame, index: bool = True) -> str:
    return df.to_markdown(index=index)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=str(CSV))
    a = ap.parse_args()
    m1 = load_eurusd(a.csv)
    sel = load_sel()
    spec = eurusd_spec()
    print(f"M1 bars {len(m1):,} {m1.index[0]} -> {m1.index[-1]} (pips) | selection events {len(sel):,} TFs {sorted(sel.tf.unique())}")
    res_a, ja = run(m1, sel, "", spec)
    print(f"v14-A: {ja['trades']} tr / {ja['return_%']:+.2f} % / DD {ja['max_dd_%']} / PF {ja['profit_factor']} / up {ja['mart_trades']} dn {ja['mart_down_trades']} [{ja['secs']} s]")
    dump(res_a, ja, "v14A")
    res_r, jr = run(m1, sel, REF_OVERRIDE, spec)
    print(f"v13-A ref: {jr['trades']} tr / {jr['return_%']:+.2f} % / DD {jr['max_dd_%']} / PF {jr['profit_factor']} [{jr['secs']} s]")
    dump(res_r, jr, "ref")

    # ---- chart
    fig, ax = plt.subplots(2, 1, figsize=(12, 8), sharex=True, gridspec_kw={"height_ratios": [3, 1]})
    for res, lab, col in ((res_r, "v13-A reference (no martingale)", "tab:gray"), (res_a, "v14-A (asymmetric martingale)", "tab:blue")):
        ax[0].plot(res.equity.index, res.equity.equity, label=lab, color=col, lw=1.2)
        dd = res.equity.equity / res.equity.equity.cummax() - 1
        ax[1].fill_between(dd.index, dd * 100, 0, color=col, alpha=0.35)
    ax[0].set_ylabel("equity $")
    ax[0].set_title(f"EURUSD v14-A single-file bot: {ja['trades']} trades, {ja['return_%']:+.2f} %, max DD {ja['max_dd_%']} %, PF {ja['profit_factor']}")
    ax[0].legend(loc="upper left")
    ax[0].grid(alpha=0.3)
    ax[1].set_ylabel("drawdown %")
    ax[1].grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUT / "equity.png", dpi=110)

    # ---- markdown
    rows = [("trades", "trades", "{:d}"), ("return %", "return_%", "{:+.2f}"), ("end balance $", "end_balance", "{:,.0f}"),
            ("net profit $", "net_profit", "{:,.0f}"), ("max drawdown %", "max_dd_%", "{:.2f}"), ("max drawdown $", "max_dd_$", "{:,.0f}"),
            ("profit factor", "profit_factor", "{:.3f}"), ("win %", "win_%", "{:.1f}"), ("stop-outs %", "sl_%", "{:.1f}"),
            ("total R", "total_R", "{:.2f}"), ("avg R / trade", "avg_R", "{:.4f}"), ("expectancy $ / trade", "expectancy_$", "{:.2f}"),
            ("gross $ won", "gross_win_$", "{:,.0f}"), ("gross $ lost", "gross_loss_$", "{:,.0f}"), ("avg loss $", "avg_loss_$", "{:.1f}"),
            ("worst trade % of equity", "worst_trade_%eq", "{:.2f}"), ("worst day % of equity", "worst_day_%", "{:.2f}"),
            ("negative days", "neg_days", "{:d}"), ("max consecutive losses", "max_consec_losses", "{:d}"), ("ulcer index", "ulcer", "{:.3f}"),
            ("return / max DD", "return_over_dd", "{:.1f}"), ("daily Sharpe", "sharpe_daily", "{:.2f}"),
            ("max risk % of start equity", "max_risk_%start", "{:.2f}"), ("avg risk $", "avg_risk_$", "{:.0f}"),
            ("avg lots", "avg_lots", "{:.3f}"), ("commission $", "commission_$", "{:,.0f}"), ("swap $", "swap_$", "{:,.0f}"),
            ("avg hold (min)", "avg_hold_min", "{:.0f}"), ("months positive", "months_pos", "{:d}"), ("worst month $", "worst_month_$", "{:,.0f}"),
            ("IS trades / R / PF (Sep25-Feb26)", None, None), ("OOS trades / R / PF (Mar-Sep26)", None, None), ("OOS net $", "OOS_net_$", "{:,.0f}"),
            ("daily-loss halts", "daily_halts", "{}"), ("stepped up / down", None, None), ("pending placed / cancelled / plans skipped", None, None)]

    def cell(j, key, f):
        v = j.get(key)
        if v is None:
            return "-"
        try:
            return f.format(int(v) if f == "{:d}" else v)
        except (ValueError, TypeError):
            return str(v)

    tab = []
    xau = json.load(open(XAU_REF)) if XAU_REF.exists() else None
    for label, key, f in rows:
        if key is None:
            def spec_cell(j):
                if label.startswith("IS"):
                    return f"{j['IS_n']} / {j['IS_R']:.2f} / {j['IS_PF']:.3f}"
                if label.startswith("OOS trades"):
                    return f"{j['OOS_n']} / {j['OOS_R']:.2f} / {j['OOS_PF']:.3f}"
                if label.startswith("stepped"):
                    return f"{j['mart_trades']} / {j['mart_down_trades']}"
                return f"{j.get('pending_placed')} / {j.get('cancelled')} / {j.get('skipped')}"
            r = [label, spec_cell(jr), spec_cell(ja)]
            if xau:
                r.append(spec_cell(xau) if not label.startswith("pending") else "-")
        else:
            r = [label, cell(jr, key, f), cell(ja, key, f)]
            if xau:
                r.append(cell(xau, key, f))
        tab.append(r)
    cols = ["metric", "EURUSD v13-A reference", "EURUSD v14-A"] + (["XAUUSD v14-A (shipped study)"] if xau else [])
    table = pd.DataFrame(tab, columns=cols)

    tra = res_a.trades.assign(month=res_a.trades.close_time.dt.strftime("%Y-%m"))
    mo = tra.groupby("month").agg(trades=("net", "size"), net_usd=("net", "sum"), R=("r_net", "sum"),
                                  win_pct=("net", lambda x: 100 * (x > 0).mean()), lost_usd=("net", lambda x: x[x < 0].sum()),
                                  up=("mart_step", lambda x: int((x > 0).sum())), down=("mart_step", lambda x: int((x < 0).sum()))).round(2)
    by_tf = res_a.by("tf")
    by_side = res_a.by("side")
    by_kind = res_a.by("kind")
    by_out = res_a.by("outcome")
    by_reg = res_a.by("regime")
    reasons = res_a.filter_reasons().head(15)
    sp = m1.spread
    lines = [
        f"# FINAL BACKTEST — single-file v14-A bot on `{Path(a.csv).name}` (EURUSD)",
        "",
        f"*Generated by `eurusd/backtest_eurusd_final.py` on {pd.Timestamp.utcnow():%Y-%m-%d %H:%M} UTC.  Bot = `eurusd/lubot_trader_v14_single.py` "
        f"(the one-file v14-A: scanner, quality model, trade filter, martingale, M1 portfolio simulator); selection streams "
        f"`eurusd/study_results/sel_eurusd_<TF>.pkl` (that same file's scanner run over this CSV by `eurusd_tools.py`).*",
        "",
        "## Setup",
        "",
        f"- **Data**: {len(m1):,} M1 bars, {m1.index[0]:%Y-%m-%d %H:%M} -> {m1.index[-1]:%Y-%m-%d %H:%M}, fed to the bot in **pips** "
        f"(price x {PIP_SCALE:,.0f}: 1.16961 -> 11696.1) so every ATR-relative detector, the quality model's price-unit features and the "
        f"3-decimal rounding see a gold-like magnitude.  Median spread {sp.median():.1f} pip (p90 {sp.quantile(.9):.1f}, p99 {sp.quantile(.99):.1f}).",
        f"- **Contract**: 1 lot = 100 000 EUR = 10 $/pip, 0.01-lot steps, commission 7 $/lot round-turn, swap long -7 / short +2 $/lot/night (3x Wed), leverage 1:100.",
        "- **Account**: $10 000 start, **1.0 % base risk** per plan sized on equity, SL slippage 0.1 pip / market 0.05 pip, daily loss limit 4.5 % -> flat "
        "until next server day, total loss 9 % -> halt (identical to the XAUUSD run).",
        f"- **Trader** (`V14A_TRADER`): `{lu.V14A_TRADER}`",
        f"- **Trade filter**: `{lu.V14A_TRADE_FILTER}`",
        f"- **Confluence filter**: `{lu.V14A_CONFLUENCE_FILTER}`",
        "- **Reference**: the same strings with every `mart_*` key removed = v13-A.",
        "- **Caveat**: the quality model and every threshold (min_quality 0.57/0.60, cost_r 0.08, ladder, regime) were fitted on XAUUSD.  Nothing was "
        "re-tuned for EURUSD: this is a pure transfer test of the shipped bot, in-sample for nothing.",
        "",
        "## Result — full year",
        "",
        f"**v14-A on EURUSD: {ja['trades']} trades, {ja['return_%']:+.2f} % ($10 000 -> ${ja['end_balance']:,.0f}), max drawdown {ja['max_dd_%']} %, "
        f"profit factor {ja['profit_factor']}, win rate {ja['win_%']} %, {ja['months_pos']}/{ja['months']} months positive, worst day {ja['worst_day_%']} % "
        f"of start equity, max risk on one plan {ja['max_risk_%start']} %, IS PF {ja['IS_PF']} / OOS PF {ja['OOS_PF']}.**  "
        f"Against the v13-A reference: return {ja['return_%'] - jr['return_%']:+.2f} pt, PF {ja['profit_factor'] - jr['profit_factor']:+.3f}, "
        f"max DD {ja['max_dd_%'] - jr['max_dd_%']:+.2f} pt.",
        "",
        "![equity](out/final/equity.png)",
        "",
        md(table, index=False),
        "",
        "## Month by month (v14-A)",
        "",
        md(mo),
        "",
        "## By timeframe / side / POI kind / outcome / regime (v14-A)",
        "",
        md(by_tf), "", md(by_side), "", md(by_kind), "", md(by_out), "", md(by_reg),
        "",
        "## Why plans were skipped (v14-A)",
        "",
        md(reasons.rename("plans").to_frame()),
        "",
        "## Files",
        "",
        "- `eurusd/out/final/v14A_trades.csv`, `v14A_equity.csv`, `v14A_monthly.csv`, `v14A_by_tf.csv`, `v14A_summary.json` (+ `ref_*` for v13-A)",
        "- `eurusd/study_results/sel_eurusd_<TF>.pkl` — the recorded selection streams (`bash eurusd/run_eurusd_record.sh` rebuilds them)",
        "- Re-run: `python eurusd/backtest_eurusd_final.py --csv data/eurusd_m1.csv`",
    ]
    (HERE / "FINAL_BACKTEST_EURUSD.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"-> {HERE / 'FINAL_BACKTEST_EURUSD.md'}")


if __name__ == "__main__":
    main()
