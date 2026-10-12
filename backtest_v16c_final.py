#!/usr/bin/env python3
"""FINAL BACKTEST of the shipped v16c-A trader on the M1 CSV.

The trader strings are READ FROM run_trader.bat (not re-typed), replayed by the realistic portfolio simulator over the
full year Sep 2025 -> Sep 2026 of the user's CSV ($10 000, 1 % base risk, real spread / commission / slippage, the v10
account rules), alongside the v16b-A reference (same strings with every v16c key dropped) so the drawdown levers' effect is isolated.
Streams: study_results/sel_v16_<TF>.pkl (the v16 top-3 recording incl. M20).
Writes:
    study_results/final_v16c/v16cA_summary.json, v16cA_trades.csv, v16cA_equity.csv, v16cA_monthly.csv, v16cA_by_tf.csv,
    study_results/final_v16c/ref_*.csv, study_results/charts/final_v16c_equity.png,
    study_results/FINAL_BACKTEST_V16C.md                                          (every number comes from this run)
    python backtest_v16c_final.py [--csv data/xauusd_m1.csv] [--study study_results/v16c_levers/<name>.json]
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
from backtest_v14_final import bat_strings, md  # noqa: E402
from lubot.execution import SymbolSpec, TraderConfig  # noqa: E402
from lubot.portfolio_sim import PortfolioSimulator  # noqa: E402
from run_v10_study import BASE  # noqa: E402
from v14_common import OOS_SPLIT  # noqa: E402
from v16c_common import EXPECT_V16B, dd_episodes, judge16c, load_year16  # noqa: E402

OUT = Path("study_results/final_v16c")
CH = Path("study_results/charts")
V16C_KEYS = ("dd_throttle_pct", "dd_throttle_scale", "dd_throttle_ramp", "dd_basis", "dd_throttle_tfs",
             "day_soft_loss_pct", "day_soft_scale", "max_open_risk_pct", "open_risk_mode", "open_risk_pending",
             "streak_n", "streak_scale", "streak_days")


def strip_v16c(trader: str) -> str:
    """The v16b-A string: drop every v16c key."""
    return ",".join(kv for kv in trader.split(",") if kv.partition("=")[0] not in V16C_KEYS)


def study_from_bat(path: str = "run_trader.bat") -> str:
    m = re.search(r"REM v16c study: (\S+)", open(path, encoding="utf-8").read())
    return m.group(1) if m else ""


def run(m1, sel, b: dict, trader: str):
    t = TraderConfig(risk_pct=b["risk"], trade_filter=b["trade_filter"], confluence_filter=b["confluence_filter"],
                     max_daily_loss_pct=4.5, max_total_loss_pct=9.0).override(BASE).override(trader)
    t0 = time.time()
    res = PortfolioSimulator(m1, sel, t, SymbolSpec()).run()
    j = judge16c(res)
    j["secs"] = round(time.time() - t0, 1)
    s = res.summary()
    for k in ("start_balance", "net_profit", "commission_$", "swap_$", "avg_hold_min", "median_hold_min", "avg_lots", "expectancy_$",
              "partial_hit_%", "tp2_%", "partial_be_%", "forced_%", "trades_per_day", "days", "mart_max_scale", "range_trades",
              "confluent_trades", "tier_trades", "rank2_trades", "reentry_trades", "cancelled", "pending_placed",
              "trend_skipped", "trend_scaled", "fast_cancelled", "fast_scaled", "counter_trend_trades", "fast_fill_trades",
              "dd_scaled", "dd_skipped", "dd_days", "day_soft_scaled", "day_soft_skipped", "open_risk_scaled", "open_risk_skipped",
              "streak_scaled", "dd_scaled_trades"):
        j[k] = s.get(k)
    j["m20_trades"] = int((res.trades.tf == "M20").sum())
    j["episodes"] = [{k: (str(v)[:16] if k in ("start", "trough", "end") else v) for k, v in e.items()} for e in dd_episodes(res.equity.equity, 5)]
    return res, j


def dump(res, j: dict, name: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    tr = res.trades.assign(month=res.trades.close_time.dt.strftime("%Y-%m"))
    tr.to_csv(OUT / f"{name}_trades.csv", index=False)
    res.equity.to_csv(OUT / f"{name}_equity.csv")
    agg = dict(trades=("net", "size"), net_usd=("net", "sum"), R=("r_net", "sum"), win_pct=("net", lambda x: 100 * (x > 0).mean()),
               sl_pct=("outcome", lambda x: 100 * (x == "sl").mean()), lost_usd=("net", lambda x: x[x < 0].sum()))
    if "dd_scale" in tr:
        agg["throttled"] = ("dd_scale", lambda x: int((x < 1.0).sum()))
    mo = tr.groupby("month").agg(**agg).round(2)
    mo.to_csv(OUT / f"{name}_monthly.csv")
    res.by("tf").to_csv(OUT / f"{name}_by_tf.csv")
    json.dump(j, open(OUT / f"{name}_summary.json", "w"), indent=1, default=str)


def pop(x: pd.DataFrame) -> dict:
    return {"trades": len(x), "win %": round(100 * (x.net > 0).mean(), 1) if len(x) else 0,
            "stop %": round(100 * (x.outcome == "sl").mean(), 1) if len(x) else 0, "net $": round(x.net.sum(), 0),
            "$ lost": round(x.net[x.net < 0].sum(), 0), "avg R": round(x.r_net.mean(), 3) if len(x) else 0,
            "avg risk $": round(x.risk_money.mean(), 0) if len(x) and "risk_money" in x else 0,
            "OOS trades": int((x.close_time >= OOS_SPLIT).sum()), "OOS net $": round(x[x.close_time >= OOS_SPLIT].net.sum(), 0)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="data/xauusd_m1.csv")
    ap.add_argument("--study", default="", help="study json of the shipped variant (reproducibility check); default = the bat header's")
    a = ap.parse_args()
    b = bat_strings()
    print("bat --trader:", b["trader"])
    m1, sel = load_year16(a.csv, stream="v16", max_rank=3)
    print(f"M1 bars {len(m1):,} {m1.index[0]} -> {m1.index[-1]} | selection events {len(sel):,}")
    res_a, ja = run(m1, sel, b, b["trader"])
    print(f"v16c-A: {ja['trades']} tr / net {ja['net_$']:+,.0f} $ / {ja['return_%']:+.2f} % / DD {ja['max_dd_%']} / PF {ja['profit_factor']} / "
          f"win {ja['win_%']} sl {ja['sl_%']} / ulcer {ja['ulcer']} / OOS net {ja['OOS_net_$']:+,.0f} / OOS DD {ja['OOS_max_dd_%']} [{ja['secs']} s]")
    dump(res_a, ja, "v16cA")
    res_r, jr = run(m1, sel, b, strip_v16c(b["trader"]))
    print(f"v16b-A ref: {jr['trades']} tr / net {jr['net_$']:+,.0f} $ / {jr['return_%']:+.2f} % / DD {jr['max_dd_%']} / PF {jr['profit_factor']} [{jr['secs']} s]")
    dump(res_r, jr, "ref")
    identical = None
    study = Path(a.study or study_from_bat())
    if str(study) and study.exists():
        st = json.load(open(study))
        identical = (ja["trades"], ja["return_%"], ja["max_dd_%"], ja["profit_factor"]) == (st["trades"], st["return_%"], st["max_dd_%"], st["profit_factor"])
        print(f"identical to the v16c study json {study.name}:", identical)
    ref_ok = (jr["trades"], round(jr["return_%"], 2), round(jr["max_dd_%"], 2)) == EXPECT_V16B
    print("reference == FINAL_BACKTEST_V16B (446 / +338.31 / -5.55):", ref_ok)

    # ---- chart
    CH.mkdir(exist_ok=True)
    fig, ax = plt.subplots(2, 1, figsize=(12, 8), sharex=True, gridspec_kw={"height_ratios": [3, 1]})
    for res, j, lab, col in ((res_r, jr, "v16b-A reference", "tab:blue"), (res_a, ja, "v16c-A (run_trader.bat)", "tab:red")):
        eq = res.equity.equity
        ax[0].plot(eq.index, eq.values, color=col, lw=1.2,
                   label=f"{lab}: {j['trades']} tr, {j['return_%']:+.1f} %, max DD {j['max_dd_%']:.2f} %, ulcer {j['ulcer']:.2f}, PF {j['profit_factor']:.2f}, return/DD {j['return_over_dd']:.0f}")
        ax[1].plot(eq.index, (eq / eq.cummax() - 1) * 100, color=col, lw=1.0)
    ax[0].axvline(pd.Timestamp(OOS_SPLIT), color="k", ls="--", lw=0.8)
    ax[1].axhline(jr["max_dd_%"], color="tab:blue", ls=":", lw=0.8)
    ax[1].axhline(ja["max_dd_%"], color="tab:red", ls=":", lw=0.8)
    csv_name = os.readlink(a.csv).split("/")[-1] if Path(a.csv).is_symlink() else Path(a.csv).name
    ax[0].set_title(f"FINAL BACKTEST v16c-A on {csv_name}  — {m1.index[0]:%Y-%m-%d} -> {m1.index[-1]:%Y-%m-%d}, $10 000, 1 % base risk, "
                    f"real costs (dashed = entry model OOS from here)")
    ax[0].set_ylabel("equity $"); ax[0].grid(alpha=.3); ax[0].legend(loc="upper left", fontsize=9)
    ax[1].set_ylabel("drawdown %"); ax[1].grid(alpha=.3)
    fig.tight_layout(); fig.savefig(CH / "final_v16c_equity.png", dpi=110); plt.close(fig)

    # ---- report
    tra = pd.read_csv(OUT / "v16cA_trades.csv", parse_dates=["entry_time", "close_time"])
    trr = pd.read_csv(OUT / "ref_trades.csv", parse_dates=["entry_time", "close_time"])
    mo_a = pd.read_csv(OUT / "v16cA_monthly.csv", index_col=0)
    mo_r = pd.read_csv(OUT / "ref_monthly.csv", index_col=0)
    mo = pd.DataFrame({"v16c-A trades": mo_a.trades, "v16c-A net $": mo_a.net_usd, "v16c-A stop %": mo_a.sl_pct.round(1),
                       "v16c-A throttled": mo_a.get("throttled"),
                       "v16b-A trades": mo_r.trades, "v16b-A net $": mo_r.net_usd, "v16b-A stop %": mo_r.sl_pct.round(1)})
    by_tf_a = pd.read_csv(OUT / "v16cA_by_tf.csv", index_col=0)
    by_tf_r = pd.read_csv(OUT / "ref_by_tf.csv", index_col=0)
    tf = pd.DataFrame({"v16c-A trades": by_tf_a.trades, "v16c-A win %": by_tf_a["win_%"], "v16c-A net $": by_tf_a["net_$"], "v16c-A PF": by_tf_a.PF,
                       "v16b-A trades": by_tf_r.trades, "v16b-A win %": by_tf_r["win_%"], "v16b-A net $": by_tf_r["net_$"], "v16b-A PF": by_tf_r.PF})
    outc = tra.outcome.value_counts()
    eps = pd.DataFrame([{"trader": "v16b-A", **e} for e in jr["episodes"]] + [{"trader": "v16c-A", **e} for e in ja["episodes"]])

    groups = []
    for lab, src in (("v16c-A", tra), ("v16b-A", trr)):
        pops = [("all", src), ("M5|M10", src[src.tf.isin(["M5", "M10"])]), ("M15+", src[~src.tf.isin(["M5", "M10"])]),
                ("buys", src[src.side == "buy"]), ("sells", src[src.side == "sell"]), ("confluent", src[src.confluent]), ("plain", src[~src.confluent])]
        if "dd_scale" in src and "dd_pct_at" in src:
            pops += [("THROTTLED (dd_scale < 1)", src[src.dd_scale < 1.0]), ("placed > 3.5 % under the peak", src[src.dd_pct_at > 3.5])]
        for pk, x in pops:
            groups.append({"trader": lab, "population": pk, **pop(x)})
    groups = pd.DataFrame(groups)
    ka, kr = set(tra.key), set(trr.key)
    common = tra[tra.key.isin(ka & kr)].drop_duplicates("key").set_index("key")
    common_r = trr[trr.key.isin(ka & kr)].drop_duplicates("key").set_index("key").reindex(common.index)
    resized_idx = common.index[common.risk_money.round(0).values != common_r.risk_money.round(0).values]
    diff = pd.DataFrame([{"slice": "v16b-A trades NOT taken by v16c-A", **pop(trr[trr.key.isin(kr - ka)])},
                         {"slice": "trades NEW in v16c-A", **pop(tra[tra.key.isin(ka - kr)])},
                         {"slice": "common keys at a DIFFERENT size (v16c-A result)", **pop(common.loc[resized_idx].reset_index())},
                         {"slice": "  the same keys in v16b-A", **pop(common_r.loc[resized_idx].reset_index())},
                         {"slice": "common keys at the same size", **pop(common.drop(resized_idx).reset_index())}])
    oos_a = tra[tra.close_time >= OOS_SPLIT]
    worst = tra.nsmallest(5, "net")[[c for c in ("key", "side", "close_time", "regime", "confluent", "dd_pct_at", "dd_scale", "risk_money", "net", "r_net", "outcome") if c in tra]].round(2)
    cmp_rows = [("trades", "trades", "{:d}"), ("net profit $", "net_$", "{:,.0f}"), ("return %", "return_%", "{:+.2f}"), ("end balance $", "end_balance", "{:,.0f}"),
                ("MAX DRAWDOWN %", "max_dd_%", "{:.2f}"), ("max drawdown $", "max_dd_$", "{:,.0f}"), ("2nd deepest DD %", "dd2_%", "{:.2f}"), ("3rd deepest DD %", "dd3_%", "{:.2f}"),
                ("ulcer index", "ulcer", "{:.3f}"), ("return / max DD", "return_over_dd", "{:.1f}"), ("OOS max DD %", "OOS_max_dd_%", "{:.2f}"),
                ("profit factor", "profit_factor", "{:.3f}"), ("win %", "win_%", "{:.1f}"), ("stop-outs %", "sl_%", "{:.1f}"), ("gross $ lost", "gross_loss_$", "{:,.0f}"),
                ("avg loss $", "avg_loss_$", "{:.1f}"), ("gross $ won", "gross_win_$", "{:,.0f}"), ("total R", "total_R", "{:.2f}"), ("avg R / trade", "avg_R", "{:.4f}"),
                ("expectancy $ / trade", "expectancy_$", "{:.2f}"), ("worst trade % of equity", "worst_trade_%eq", "{:.2f}"), ("worst day % of equity", "worst_day_%eq", "{:.2f}"),
                ("negative days", "neg_days", "{:d}"), ("max consecutive losses", "max_consec_losses", "{:d}"),
                ("daily Sharpe", "sharpe_daily", "{:.2f}"), ("max risk % of equity", "max_risk_%eq", "{:.2f}"),
                ("avg risk $", "avg_risk_$", "{:.0f}"), ("commission $", "commission_$", "{:,.0f}"), ("swap $", "swap_$", "{:,.0f}"),
                ("avg hold (min)", "avg_hold_min", "{:.0f}"), ("months positive", "months_pos", "{:d}"), ("worst month $", "worst_month_$", "{:,.0f}"),
                ("IS R (Sep25-Feb26)", "IS_R", "{:.2f}"), ("IS PF", "IS_PF", "{:.3f}"), ("OOS trades (Mar-Sep26)", "OOS_trades", "{:d}"),
                ("OOS R", "OOS_R", "{:.2f}"), ("OOS PF", "OOS_PF", "{:.3f}"), ("OOS win %", "OOS_win_%", "{:.1f}"), ("OOS stop-outs %", "OOS_sl_%", "{:.1f}"),
                ("OOS net $", "OOS_net_$", "{:,.0f}"), ("confluent trades", "confluent_trades", "{:d}"), ("M20 trades", "m20_trades", "{:d}"),
                ("stepped up (martingale)", "mart_trades", "{:d}"), ("stepped down", "mart_down_trades", "{:d}"),
                ("plans THROTTLED by the drawdown lever", "dd_scaled", "{:d}"), ("plans skipped by the drawdown lever", "dd_skipped", "{:d}"),
                ("minutes spent > threshold under the peak", "dd_days", "{:d}"),
                ("plans scaled by the day soft cap", "day_soft_scaled", "{:d}"), ("plans skipped by the day soft cap", "day_soft_skipped", "{:d}"),
                ("fast fills cancelled", "fast_cancelled", "{:d}"), ("pending orders placed", "pending_placed", "{:d}"), ("daily-loss halts", "daily_halts", "{:d}")]
    cmp = []
    for lab, k, f in cmp_rows:
        va, vr = ja.get(k), jr.get(k)
        fmt = lambda v: f.format(int(v) if f.endswith("d}") else float(v)) if v is not None and v == v else "-"
        cmp.append({"metric": lab, "v16b-A reference": fmt(vr), "v16c-A (shipped)": fmt(va)})
    cmp = pd.DataFrame(cmp)

    L = []
    w = L.append
    w(f"# FINAL BACKTEST — v16c-A (less drawdown: a smaller max drawdown % at the same profitability) on `{csv_name}`\n")
    w(f"*Generated by `backtest_v16c_final.py` on {pd.Timestamp.utcnow():%Y-%m-%d %H:%M} UTC.  Trader strings read from `run_trader.bat`; "
      f"simulator `lubot/portfolio_sim.py`; selection streams `study_results/sel_v16_*.pkl` (the v16 top-3 recording of the scanner over this CSV, incl. M20).*\n")
    w("## Setup\n")
    w(f"- **Data**: {len(m1):,} M1 bars, {m1.index[0]:%Y-%m-%d %H:%M} -> {m1.index[-1]:%Y-%m-%d %H:%M} (the year used by every v10-v16c study; the CSV "
      f"starts 2025-01-02 and the entry models were trained before the backtest window; the entry model is out-of-sample from {OOS_SPLIT}).")
    w(f"- **Account**: $10 000 start, **{b['risk']:.1f} % base risk** per plan sized on equity, commission {b['commission']:.0f} $/lot round-turn, "
      f"spread from the CSV, SL slippage 0.10 / market 0.05, daily loss limit 4.5 % -> flat until next server day, total loss 9 % -> halt.")
    w(f"- **Trader** (`--trader`): `{b['trader']}`")
    w(f"- **Trade filter**: `{b['trade_filter']}`")
    w(f"- **Confluence filter**: `{b['confluence_filter']}`")
    w(f"- **Reference**: the same strings with every v16c key removed = v16b-A ({'reproduces' if ref_ok else 'DOES NOT reproduce'} FINAL_BACKTEST_V16B: "
      f"{jr['trades']} tr / {jr['return_%']:+.2f} % / DD {jr['max_dd_%']}).")
    if identical is not None:
        w(f"- **Reproducibility**: result {'IDENTICAL' if identical else 'DIFFERENT'} to the v16c study json `{study.name}` "
          f"({ja['trades']} tr / {ja['return_%']:+.2f} % / DD {ja['max_dd_%']} / PF {ja['profit_factor']}).")
    w("\n## Result — full year\n")
    w(f"**v16c-A: max drawdown {ja['max_dd_%']:.2f} % (v16b-A {jr['max_dd_%']:.2f}, {ja['max_dd_%'] - jr['max_dd_%']:+.2f} pt = "
      f"{100 * (1 - abs(ja['max_dd_%']) / abs(jr['max_dd_%'])):.0f} % less), max DD {ja['max_dd_$']:,.0f} $ (v16b-A {jr['max_dd_$']:,.0f}), "
      f"ulcer {ja['ulcer']:.3f} (v16b-A {jr['ulcer']:.3f}), OOS max DD {ja['OOS_max_dd_%']:.2f} % (v16b-A {jr['OOS_max_dd_%']:.2f}); "
      f"net {ja['net_$']:+,.0f} $ (v16b-A {jr['net_$']:+,.0f}, {100 * (ja['net_$'] / jr['net_$'] - 1):+.1f} %), {ja['return_%']:+.2f} % "
      f"($10 000 -> ${ja['end_balance']:,.0f}), profit factor {ja['profit_factor']:.3f} (v16b-A {jr['profit_factor']:.3f}), return / max DD "
      f"{ja['return_over_dd']:.1f} (v16b-A {jr['return_over_dd']:.1f}), {ja['trades']} trades (v16b-A {jr['trades']}), win rate {ja['win_%']:.1f} % "
      f"(v16b-A {jr['win_%']:.1f}), stop-outs {ja['sl_%']:.1f} % (v16b-A {jr['sl_%']:.1f}), gross $ lost {ja['gross_loss_$']:,.0f} (v16b-A {jr['gross_loss_$']:,.0f}), "
      f"worst day {ja['worst_day_%eq']:.2f} % (v16b-A {jr['worst_day_%eq']:.2f}), {ja['months_pos']}/{ja['months']} months positive, "
      f"OOS net {ja['OOS_net_$']:+,.0f} $ (v16b-A {jr['OOS_net_$']:+,.0f}), OOS PF {ja['OOS_PF']:.2f} (v16b-A {jr['OOS_PF']:.2f}).**  "
      f"Scorecard (v16c_common.judge16c): less drawdown {ja['less_dd']}, profit held {ja['hold_profit']}, loss profile held {ja['hold_loss']}, "
      f"OOS held {ja['hold_oos']} -> score {ja['score']}/4.\n")
    w("![equity](charts/final_v16c_equity.png)\n")
    w(md(cmp, index=False))
    w("\n## The drawdown episodes (five deepest of each equity path)\n")
    w(md(eps, index=False))
    w("\n## Where the drawdown reduction comes from\n")
    w(md(diff, index=False))
    w("")
    w(md(groups, index=False))
    w("\n## Month by month\n")
    w(md(mo))
    w("\n## By timeframe\n")
    w(md(tf))
    w(f"\nExit outcomes: " + ", ".join(f"{k} {v}" for k, v in outc.items()) + f".  Range-managed trades: {ja['range_trades']}, confluent: {ja['confluent_trades']}, "
      f"M20: {ja.get('m20_trades')}, stepped up / down: {ja['mart_trades']} / {ja['mart_down_trades']}.  Plans throttled by the drawdown lever "
      f"{ja['dd_scaled']}, skipped {ja['dd_skipped']}; day soft cap scaled {ja['day_soft_scaled']}, skipped {ja['day_soft_skipped']}; fast fills cancelled "
      f"{ja['fast_cancelled']}.  Pending orders placed {ja['pending_placed']}, cancelled unfilled {ja['cancelled']}.")
    w(f"\nOOS half (from {OOS_SPLIT}): {len(oos_a)} trades, net {oos_a.net.sum():,.0f} $, PF {ja['OOS_PF']:.2f}, win {100 * (oos_a.net > 0).mean():.1f} %, "
      f"stop-outs {100 * (oos_a.outcome == 'sl').mean():.1f} %, max DD {ja['OOS_max_dd_%']:.2f} %.\n")
    w("## Five worst trades\n")
    w(md(worst, index=False))
    w("\n## Files\n")
    w("`study_results/final_v16c/v16cA_summary.json` (all metrics + episodes), `v16cA_trades.csv` (every trade with `dd_pct_at` / `dd_scale` / `risk_scale` / legs), "
      "`v16cA_equity.csv` (balance + equity), `v16cA_monthly.csv`, `v16cA_by_tf.csv`, the same for `ref_*` (v16b-A), chart `charts/final_v16c_equity.png`.  "
      "Full study: `study_results/LESS_DD_V16C.md`.\n")
    Path("study_results/FINAL_BACKTEST_V16C.md").write_text("\n".join(L), encoding="utf-8")
    print("wrote study_results/FINAL_BACKTEST_V16C.md")
    os.makedirs("logs", exist_ok=True)
    open("logs/backtest_v16c_final.log", "w").write(json.dumps({"v16cA": ja, "ref": jr, "identical": identical, "ref_ok": ref_ok}, indent=1, default=str))


if __name__ == "__main__":
    main()
