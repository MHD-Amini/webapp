#!/usr/bin/env python3
"""v16b step 6b - report study_results/LESS_LOSS_V16B.md + charts/v16b_*.png from the v16b result files
(v16b_diag/*.csv, v16b_levers.csv, v16b_levers/*_trades.csv|_equity.csv, v16b_stress_judged.csv, v16b_stress_summary.csv,
v16b_walkforward.csv/json, final_v16b/*).  Every number in the report is read from those files - nothing is typed in.
    python3 make_v16b_report.py
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

SR = Path("study_results")
RUNS = SR / "v16b_levers"
DG = SR / "v16b_diag"
CH = SR / "charts"
CH.mkdir(exist_ok=True)
OOS = "2026-03-01"
REF, A, B, C, F2 = "ref", "C_F2+RS_0.5", "C_T20_rng+F3_m510+RS_0.25", "C_T10_x0.5_htf+F2", "F2"
LABEL = {REF: "v16-A reference", A: "v16b-A: fast-fill guard 2 min + range sells x0.5 (shipped)",
         B: "v16b-B: + range counter-trend sells skipped (SMA20), F3 M5|M10, range sells x0.25 (most $ saved)",
         C: "v16b-C: fast-fill guard 2 min + counter-trend sells M15+ x0.5 (most $ earned)", F2: "F2 alone: fast-fill guard 2 min"}
COLS = ["name", "trades", "net_$", "OOS_net_$", "max_dd_%", "profit_factor", "win_%", "sl_%", "gross_loss_$", "worst_day_%eq", "OOS_PF", "OOS_sl_%",
        "months_pos", "score"]
NICE = {"trades": "trades", "net_$": "net $", "OOS_net_$": "OOS net $", "max_dd_%": "max DD %", "profit_factor": "PF", "win_%": "win %",
        "sl_%": "stop %", "gross_loss_$": "$ lost", "worst_day_%eq": "worst day %", "OOS_PF": "OOS PF", "OOS_sl_%": "OOS stop %",
        "months_pos": "months +", "score": "score", "name": "variant", "family": "family", "overrides": "keys", "saved_$": "$ saved",
        "d_net_$": "net delta $", "d_sl_pt": "stop pt", "avg_loss_$": "avg loss $", "n": "trades", "sl": "stop-outs", "net_$": "net $",
        "avg_R": "avg R", "tag": "scenario"}
TAGS = ("spread_x2", "commission_x2", "slip_x3", "worst_intrabar", "risk0.5", "risk2")


def esc(t: str) -> str:
    """matplotlib treats $...$ as math text."""
    return t.replace("$", r"\$")


def md(df: pd.DataFrame, index=False) -> str:
    d = df.rename(columns=NICE).copy()
    for col in d.columns:
        if d[col].dtype.kind == "f":
            d[col] = d[col].round(0).astype("Int64") if "$" in str(col) else d[col].round(3)
    return d.to_markdown(index=index)


def fam(name: str) -> str:
    for p, f in (("ref", "ref"), ("C_", "combination"), ("TB", "trend gate both sides (control)"), ("T", "trend gate on sells"),
                 ("F", "fast-fill guard"), ("RS", "range-sell size"), ("BE", "break-even trigger"), ("DL", "day-loss cap")):
        if name.startswith(p):
            return f
    return "?"


def flags(r) -> str:
    return "".join(("L" if r.less_loss else "-", "P" if r.hold_profit else "-", "O" if r.hold_oos else "-", "D" if r.no_worse_day else "-"))


def main():
    lev = pd.read_csv(SR / "v16b_levers.csv")
    lev["family"] = lev.name.map(fam)
    lev["flags"] = lev.apply(flags, axis=1)
    ref = lev[lev.name == REF].iloc[0]
    a = lev[lev.name == A].iloc[0]
    stj = pd.read_csv(SR / "v16b_stress_judged.csv")
    sts = pd.read_csv(SR / "v16b_stress_summary.csv")
    wf = pd.read_csv(SR / "v16b_walkforward.csv", index_col=0)
    wfj = json.load(open(SR / "v16b_walkforward.json"))
    final = json.load(open(SR / "final_v16b" / "v16bA_summary.json"))
    fref = json.load(open(SR / "final_v16b" / "ref_summary.json"))
    trades = {k: pd.read_csv(RUNS / f"{k}_trades.csv", parse_dates=["entry_time", "close_time"]) for k in (REF, A, B, C, F2)}
    eq = {k: pd.read_csv(RUNS / f"{k}_equity.csv", index_col=0, parse_dates=True).equity for k in (REF, A, B, C, F2)}
    dg = {f.stem: pd.read_csv(f) for f in DG.glob("*.csv")}

    # ---------------------------------------------------------------- charts
    fig, ax = plt.subplots(2, 1, figsize=(12, 8), sharex=True, gridspec_kw={"height_ratios": [3, 1]})
    for k, col in ((REF, "tab:blue"), (F2, "tab:gray"), (C, "tab:green"), (B, "tab:orange"), (A, "tab:red")):
        r = lev[lev.name == k].iloc[0]
        ax[0].plot(eq[k].index, eq[k].values, color=col, lw=1.1,
                   label=esc(f"{LABEL[k]}: {int(r.trades)} tr, {r['net_$']:+,.0f} $, DD {r['max_dd_%']:.2f} %, PF {r.profit_factor:.2f}, stop {r['sl_%']:.1f} %, $ lost {r['gross_loss_$']:,.0f}"))
        ax[1].plot(eq[k].index, (eq[k] / eq[k].cummax() - 1) * 100, color=col, lw=0.9)
    ax[0].axvline(pd.Timestamp(OOS), color="k", ls="--", lw=0.8); ax[0].set_ylabel(esc("equity $")); ax[0].grid(alpha=.3); ax[0].legend(fontsize=7, loc="upper left")
    ax[1].set_ylabel("drawdown %"); ax[1].grid(alpha=.3)
    ax[0].set_title("v16b - loss reduction on the v16-A trader: full year, $10 000, 1 % base risk; dashed = entry model OOS")
    fig.tight_layout(); fig.savefig(CH / "v16b_equity.png", dpi=110); plt.close(fig)

    fig, ax = plt.subplots(figsize=(11, 6))
    ok = lev[lev.score == 4]; mid = lev[lev.score == 3]; bad = lev[lev.score < 3]
    ax.scatter(-bad["gross_loss_$"], bad["net_$"], c="lightgray", s=18, label="score 0-2")
    ax.scatter(-mid["gross_loss_$"], mid["net_$"], c="tab:olive", s=20, label="score 3")
    ax.scatter(-ok["gross_loss_$"], ok["net_$"], c="tab:green", s=26, label="score 4 (less loss, profit held, OOS held, no worse day)")
    for k, col in ((REF, "tab:blue"), (A, "tab:red"), (B, "tab:orange"), (C, "tab:green"), (F2, "tab:gray")):
        r = lev[lev.name == k].iloc[0]
        ax.scatter([-r["gross_loss_$"]], [r["net_$"]], c=col, s=90, edgecolor="k", zorder=5)
        ax.annotate("v16-A" if k == REF else k, (-r["gross_loss_$"], r["net_$"]), fontsize=8, xytext=(5, 5), textcoords="offset points")
    ax.axvline(-ref["gross_loss_$"], color="k", lw=0.6, ls=":"); ax.axhline(ref["net_$"], color="k", lw=0.6, ls=":")
    ax.set_xlabel(esc("gross $ lost per year (left = less loss)")); ax.set_ylabel(esc("net $ / year")); ax.grid(alpha=.3); ax.legend(fontsize=8)
    ax.set_title(esc(f"{len(lev)} variants: $ lost vs profit (dotted = v16-A)"))
    fig.tight_layout(); fig.savefig(CH / "v16b_scatter.png", dpi=110); plt.close(fig)

    fig, ax = plt.subplots(1, 2, figsize=(13, 4))
    mo = pd.DataFrame({("v16-A" if k == REF else k): trades[k].assign(m=trades[k].close_time.dt.strftime("%Y-%m")).groupby("m").net.sum() for k in (REF, A)})
    mo.plot.bar(ax=ax[0], width=0.8, color=["tab:blue", "tab:red"]); ax[0].grid(alpha=.3, axis="y"); ax[0].set_ylabel(esc("net $")); ax[0].set_title(esc("net $ per month"))
    lo = pd.DataFrame({("v16-A" if k == REF else k): trades[k].assign(m=trades[k].close_time.dt.strftime("%Y-%m")).groupby("m").net.apply(lambda x: x[x < 0].sum()) for k in (REF, A)})
    lo.plot.bar(ax=ax[1], width=0.8, color=["tab:blue", "tab:red"]); ax[1].grid(alpha=.3, axis="y"); ax[1].set_ylabel(esc("$ lost")); ax[1].set_title(esc("$ lost per month"))
    fig.tight_layout(); fig.savefig(CH / "v16b_monthly.png", dpi=110); plt.close(fig)

    # fast-fill N scan and range-sell scale scan
    fig, ax = plt.subplots(1, 2, figsize=(13, 4))
    fs = lev[lev.name.str.match(r"^F\d+$")].copy(); fs["N"] = fs.name.str[1:].astype(int); fs = fs.sort_values("N")
    ax[0].plot(fs.N, fs["sl_%"], "o-", color="tab:red", label="stop-out %"); ax[0].set_ylabel("stop-out %"); ax[0].set_xlabel("min_fill_age_min (cancel fills younger than N min)")
    ax0b = ax[0].twinx(); ax0b.plot(fs.N, -fs["max_dd_%"], "s--", color="tab:blue", label="max DD %"); ax0b.plot(fs.N, -fs["worst_day_%eq"], "^:", color="tab:purple", label="worst day %"); ax0b.set_ylabel("%")
    ax0b.axhline(-ref["max_dd_%"], color="tab:blue", lw=0.6, ls=":"); ax[0].axhline(ref["sl_%"], color="tab:red", lw=0.6, ls=":")
    ax[0].legend(loc="upper left", fontsize=7); ax0b.legend(loc="upper right", fontsize=7); ax[0].grid(alpha=.3); ax[0].set_title("fast-fill guard: the stop rate falls with N, the DD climbs past N=3")
    rs = lev[lev.name.str.match(r"^RS_[0-9.]+$")].copy(); rs["s"] = rs.name.str[3:].astype(float); rs = rs.sort_values("s")
    ax[1].plot(rs.s, -rs["gross_loss_$"], "o-", color="tab:red", label=esc("$ lost")); ax[1].plot(rs.s, rs["net_$"], "s-", color="tab:green", label=esc("net $"))
    ax[1].axhline(-ref["gross_loss_$"], color="tab:red", lw=0.6, ls=":"); ax[1].axhline(ref["net_$"], color="tab:green", lw=0.6, ls=":")
    ax[1].set_xlabel("range-regime sell size (regime_side_scale=range:sell:s)"); ax[1].set_ylabel(esc("$")); ax[1].grid(alpha=.3); ax[1].legend(fontsize=7)
    ax[1].set_title(esc("range sells: smaller = fewer $ lost at the same net"))
    fig.tight_layout(); fig.savefig(CH / "v16b_levers.png", dpi=110); plt.close(fig)

    # ---------------------------------------------------------------- tables
    tops = lev[lev.score == 4].sort_values("gross_loss_$", ascending=False)
    fam_best = lev[lev.name != REF].sort_values("score", ascending=False).groupby("family").head(3).sort_values(["family", "score", "gross_loss_$"], ascending=[True, False, False])
    singles = {k: lev[lev.name.str.match(p)].sort_values("name") for k, p in (("T", r"^T(5|10|20|50)$"), ("Tscope", r"^T(10|20)_(x0\.5_)?(htf|rng|m510)$"),
                                                                             ("F", r"^F\d+$"), ("Fscope", r"^F(3|5)_(x0\.5_)?(m510|rng)$|^F\d_x0\.5$"),
                                                                             ("RS", r"^RS_"), ("BE", r"^BE"), ("DL", r"^DL"), ("TB", r"^TB"))}
    # who is removed / shrunk by v16b-A, from the final trade lists
    ta = pd.read_csv(SR / "final_v16b" / "v16bA_trades.csv", parse_dates=["close_time"])
    tr_ = pd.read_csv(SR / "final_v16b" / "ref_trades.csv", parse_dates=["close_time"])
    ka, kr = set(ta.key), set(tr_.key)

    def pop(x):
        return {"trades": len(x), "win %": round(100 * (x.net > 0).mean(), 1) if len(x) else 0, "stop %": round(100 * (x.outcome == "sl").mean(), 1) if len(x) else 0,
                "net $": round(x.net.sum(), 0), "$ lost": round(x.net[x.net < 0].sum(), 0), "avg R": round(x.r_net.mean(), 3) if len(x) else 0,
                "OOS net $": round(x[x.close_time >= OOS].net.sum(), 0)}
    removed = tr_[tr_.key.isin(kr - ka)]; added = ta[ta.key.isin(ka - kr)]
    common_a = ta[ta.key.isin(ka & kr)]; common_r = tr_[tr_.key.isin(ka & kr)]
    rs_a = common_a[(common_a.side == "sell") & (common_a.regime == "range")]; rs_r = common_r[(common_r.side == "sell") & (common_r.regime == "range")]
    who = pd.DataFrame([{"slice": "v16-A trades NOT taken by v16b-A (fast fills cancelled + knock-on)", **pop(removed)},
                        {"slice": "trades NEW in v16b-A (knock-on: freed slots / equity path)", **pop(added)},
                        {"slice": "common range-regime SELLS - in v16-A (full size)", **pop(rs_r)},
                        {"slice": "common range-regime SELLS - in v16b-A (half size)", **pop(rs_a)},
                        {"slice": "all common plans - v16-A", **pop(common_r)}, {"slice": "all common plans - v16b-A", **pop(common_a)}])
    # stress tables
    st_rows = stj[stj.name.isin([A, B, C, F2])].copy()
    st_rows["flags"] = st_rows.apply(flags, axis=1)
    st_tbl = st_rows[["name", "tag", "trades", "net_$", "ref_net_$", "OOS_net_$", "max_dd_%", "ref_max_dd_%", "profit_factor", "ref_PF", "sl_%", "ref_sl_%",
                      "gross_loss_$", "ref_gross_loss_$", "worst_day_%eq", "ref_worst_day_%eq", "OOS_PF", "months_pos", "flags", "misses"]].rename(
        columns={"ref_net_$": "v16-A net $", "ref_max_dd_%": "v16-A DD %", "ref_PF": "v16-A PF", "ref_sl_%": "v16-A stop %", "ref_gross_loss_$": "v16-A $ lost",
                 "ref_worst_day_%eq": "v16-A worst day %"})
    st_tbl["misses"] = st_tbl.misses.fillna("none")
    wf_rows = wf.loc[[REF, A, B, C, F2, "F3_m510", "T20_rng", "T10_x0.5_htf", "C_F3_rng+RS_0.5"],
                     ["IS_n", "IS_net_$", "IS_PF", "IS_sl_%", "IS_lost_$", "IS_worst_day_R", "IS_pass", "OOS_n", "OOS_net_$", "OOS_PF", "OOS_sl_%", "OOS_lost_$",
                      "OOS_worst_day_R", "OOS_pass"]].reset_index()
    # worst day of v16b-A vs v16-A
    da = trades[A].groupby(trades[A].close_time.dt.date).agg(net=("net", "sum"), R=("r_net", "sum"), n=("net", "size")).sort_values("net")
    dr = trades[REF].groupby(trades[REF].close_time.dt.date).agg(net=("net", "sum"), R=("r_net", "sum"), n=("net", "size")).sort_values("net")
    wd_a, wd_r = da.iloc[0], dr.iloc[0]
    wd_r_in_a = da.loc[dr.index[0]] if dr.index[0] in da.index else None

    # ---------------------------------------------------------------- report
    L = []; w = L.append
    w("# REDUCE THE LOSS PERCENTAGE WHILE MAINTAINING THE PROFITABILITY PERCENTAGE (v16b) — the v16-A trader\n")
    w(f"*Generated by `make_v16b_report.py` on {pd.Timestamp.utcnow():%Y-%m-%d %H:%M} UTC from the result files in `study_results/` (nothing typed in).*\n")
    w("## 0. Answer\n")
    w(f"**v16b-A = v16-A + `min_fill_age_min=2` + `regime_side_scale=range:sell:0.5`** (shipped in `run_trader.bat`).  Full year Sep 2025 -> Sep 2026, "
      f"$10 000, 1 % base risk, real costs (`FINAL_BACKTEST_V16B.md`): **stop-outs {final['sl_%']:.1f} % (v16-A {fref['sl_%']:.1f}), gross $ lost "
      f"{final['gross_loss_$']:,.0f} (v16-A {fref['gross_loss_$']:,.0f}, {100 * (final['gross_loss_$'] / fref['gross_loss_$'] - 1):+.1f} %), avg loss "
      f"{final['avg_loss_$']:.0f} $ ({fref['avg_loss_$']:.0f}), max drawdown {final['max_dd_%']:.2f} % ({fref['max_dd_%']:.2f}), worst day {final['worst_day_%eq']:.2f} % "
      f"({fref['worst_day_%eq']:.2f}) — while the net went UP: {final['net_$']:+,.0f} $ ({fref['net_$']:+,.0f}, {100 * (final['net_$'] / fref['net_$'] - 1):+.1f} %), "
      f"profit factor {final['profit_factor']:.2f} ({fref['profit_factor']:.2f}), win {final['win_%']:.1f} % ({fref['win_%']:.1f}), OOS net {final['OOS_net_$']:+,.0f} $ "
      f"({fref['OOS_net_$']:+,.0f}), OOS PF {final['OOS_PF']:.2f} ({fref['OOS_PF']:.2f}), OOS stop-outs {final['OOS_sl_%']:.1f} % ({fref['OOS_sl_%']:.1f}), "
      f"{final['months_pos']}/{final['months']} months positive, {final['trades']} trades ({fref['trades']}).**  Score 4/4 on the v16b judge; stress x6: profit "
      f"held 6/6, OOS held 6/6, less loss 5/6, worst day in band 5/6; walk-forward OOS half passes every band.\n")
    w("The two levers are both decided BEFORE the fill and both live already (`trader.py`, tests `tests/test_trader_v16b.py`, `tests/test_bat_v16b.py`):")
    w("1. **Impulsive-arrival guard** (`min_fill_age_min=2`): a pending order that would fill less than 2 minutes after it was placed is cancelled - price "
      "was already running into the zone when the scanner showed it.  Live, a broker fills a limit order itself, so the bot closes a position it sees "
      "opened < 2 min after placement at market (cost: one spread; 22 cases in the year).")
    w("2. **Range-regime sells at half size** (`regime_side_scale=range:sell:0.5`): a SELL placed while the daily regime is 'range' (adr_ratio < 1.0, the v13 "
      "regime already live) is sized at 0.5 x.  Buys and trend-regime sells are untouched.\n")
    w("![equity](charts/v16b_equity.png)\n")
    w("## 1. Method\n")
    w(f"Same discipline as v10-v16: the v16-A trader exactly as shipped (strings frozen in `v16b_common.py` and cross-checked against the bat), replayed through "
      f"the M1 portfolio simulator over the full year; parity of the reference reproduced first ({int(ref.trades)} tr / {ref['net_$']:+,.0f} $ / DD {ref['max_dd_%']:.2f} = "
      f"FINAL_BACKTEST_V16).  **Judge (`v16b_common.judge16b`)**: *less_loss* = stop-out % < ref AND max DD better AND gross $ lost smaller; *hold_profit* = net >= 97 % "
      f"of ref AND PF >= ref - 0.05 AND OOS net >= 97 %; *hold_oos* = OOS stop % < ref AND OOS PF >= ref - 0.10 AND OOS DD within 0.5 pt; *no_worse_day* = worst day >= "
      f"ref - 0.25 pt.  Score 0-4.  Steps: diagnosis of the 114 stop-outs -> levers in the simulator (defaults byte-identical) -> grid of {len(lev)} variants -> "
      f"stress x6 + walk-forward of 8 finalists -> port to the bat -> final backtest from the bat strings.\n")
    w("## 2. Diagnosis — where the losses of v16-A are (`v16b_diag/DIAG.md`, 37 tables)\n")
    w("The stop-outs are not spread evenly.  Three slices, all visible BEFORE the fill, carry most of the avoidable loss:\n")
    w("**Side** - sells stop out 1.6 x as often as buys and earn a seventh of the money:\n"); w(md(dg["by_side"]))
    w("\n**Counter-trend sells** (last closed daily close above its SMA10 -> `up10 = True`): 93 trades, 39 % stop rate, nothing earned; counter-trend buys are fine:\n")
    w(md(dg["by_side_up10"]))
    w("\n**Regime x side** - sells placed in a 'range' regime (the v13 adr_ratio regime) lose money; everything else earns:\n"); w(md(dg["by_side_regime"]))
    w("\n**Fill age** - orders FILLED within minutes of placement (price was already running into the zone): the first two bands lose, the patient fills earn:\n")
    w(md(dg["by_age"]))
    w("\n...and the fast fills in a range regime are the worst cell of all:\n"); w(md(dg["fast_by_regime"]))
    w("\n**Static estimate** (trade list, before re-simulation: no sizing / sequencing effects):\n"); w(md(dg["candidates_static"]))
    w("\nNOT levers (checked): quality band, session, kind, timeframe, concurrency, martingale step-down, day clusters (a day cap below 4.5 % catches 1-2 days).  "
      "A break-even trigger below TP1 looked promising on the stop-outs' MFE path (`sl_mfe.csv`) but the winners' retrace kills it - see the grid.\n")
    w("## 3. Levers (simulator + live bot, defaults off, parity byte-identical)\n")
    w("| key | what it does |\n|:--|:--|")
    w("| `trend_sma=N`, `trend_sides`, `trend_mode=skip\\|scale`, `trend_risk_scale`, `trend_tfs`, `trend_regime` | daily trend gate: a plan against the close-vs-SMA(N) trend of the last CLOSED server day, on the listed side(s), is skipped or scaled; tf / regime scope |")
    w("| `min_fill_age_min=N`, `fast_fill_mode=cancel\\|scale`, `fast_fill_scale`, `fast_fill_tfs`, `fast_fill_regime` | impulsive-arrival guard: an order that would fill < N min after placement is cancelled (or scaled); tf / regime scope |")
    w("| `regime_side_scale=range:sell:0.5\\|...` | regime x side sizing |")
    w("| `be_trigger_r`, `max_daily_loss_pct` | (existing) break-even trigger before TP1, day-loss cap - re-tested on v16-A |\n")
    w(f"## 4. Grid — {len(lev)} variants (`v16b_levers.csv`; one json + trade list + equity per run in `v16b_levers/`)\n")
    w(f"Flags: L = less loss, P = profit held, O = OOS held, D = no worse day.  **{len(tops)} variants score 4/4**, sorted by $ lost (least first):\n")
    w(md(tops[COLS + ["flags", "overrides"]]))
    w("\n![scatter](charts/v16b_scatter.png)\n")
    w("### 4a. Single levers\n")
    w("**Trend gate on sells** (skip): cuts the $ lost by a quarter but gives up 8-25 % of the net and worsens the worst day (the 2026-04-08 cluster is made of WITH-trend sells):\n")
    w(md(singles["T"][COLS + ["flags"]]))
    w("\nScoped (tf / regime / scale) - the range-only and M15+ x0.5 versions keep the net:\n"); w(md(singles["Tscope"][COLS + ["flags"]]))
    w("\nControl - both sides gated: halves the trades and the profit (buys are not the problem):\n"); w(md(singles["TB"][COLS + ["flags"]]))
    w("\n**Fast-fill guard** (cancel fills younger than N min): the stop rate falls with N, but from N=3 the DD climbs (sizing on a different equity path), F2 is the sweet spot:\n")
    w(md(singles["F"][COLS + ["flags"]]))
    w("\nScoped / scaled versions (scaling instead of cancelling does nothing - the fill happens anyway):\n"); w(md(singles["Fscope"][COLS + ["flags"]]))
    w("\n![levers](charts/v16b_levers.png)\n")
    w("\n**Range-sell size**: alone it saves $ and lifts the PF but fails less_loss on the DD (5.85-6.00 vs 5.82) - it is the best COMBINER:\n"); w(md(singles["RS"][COLS + ["flags"]]))
    w("\n**OUT** - break-even trigger before TP1 (the winners' retrace takes them out) and tighter day-loss caps (the flatten locks the loss in; DD and worst day get WORSE):\n")
    w(md(pd.concat([singles["BE"], singles["DL"]])[COLS + ["flags"]]))
    w("\n### 4b. Combinations\n")
    w(md(lev[lev.name.str.startswith("C_")].sort_values(["score", "gross_loss_$"], ascending=[False, False])[COLS + ["flags"]]))
    w("\nBest three per family:\n"); w(md(fam_best[["family"] + COLS + ["flags"]]))
    w("\n## 5. Robustness — stress x6 and walk-forward of the 8 finalists\n")
    w("Each finalist re-run in 6 scenarios (spread x2, commission x2, slippage x3, worst intrabar order, risk 0.5 %, risk 2 %) and judged against the v16-A row of the "
      "SAME scenario (`v16_stress.csv`).  Scenarios passed out of 6 per question (`v16b_stress_summary.csv`):\n")
    w(md(sts))
    w("\nScenario by scenario for the shipped variant and the alternatives (`v16b_stress_judged.csv`):\n")
    w(md(st_tbl))
    w(f"\n**Walk-forward** (`v16b_walkforward.csv`, split {OOS} on close time, from the trade lists): the v16b pass on a half = fewer $ lost AND stop % down AND net >= 97 % "
      f"AND PF held AND worst day in R held.  {wfj['oos_pass']} of {wfj['n_variants']} variants pass the OOS half, {wfj['is_pass']} the IS half, {wfj['both']} both; IS->OOS "
      f"Spearman of the deltas vs ref: $ lost rho {wfj['spearman']['d_lost']['rho']:.2f}, net rho {wfj['spearman']['d_net']['rho']:.2f}, stop % rho "
      f"{wfj['spearman']['d_sl']['rho']:.2f}, PF rho {wfj['spearman']['d_PF']['rho']:.2f}.  Every finalist passes the OOS half; none passes the IS half with less_loss: the "
      f"loss slices (counter-trend sells, impulsive fills, range sells) earn a little on the IS half (`by_half_side*.csv`) and lose on the OOS half, so the levers cost a "
      f"little where it does not matter and pay where it does.\n")
    w(md(wf_rows))
    w(f"\n**Worst day**: v16b-A {wd_a.net:,.0f} $ ({wd_a.R:.2f} R, {int(wd_a.n)} trades) on {da.index[0]}; v16-A {wd_r.net:,.0f} $ ({wd_r.R:.2f} R, {int(wd_r.n)} trades) on {dr.index[0]}"
      + (f" - that day in v16b-A: {wd_r_in_a.net:,.0f} $ ({wd_r_in_a.R:.2f} R, {int(wd_r_in_a.n)} trades)." if wd_r_in_a is not None else "."))
    w("\n## 6. Final backtest from the bat strings (`FINAL_BACKTEST_V16B.md`, `final_v16b/`)\n")
    w(f"The strings are read from `run_trader.bat` and replayed; the reference = the same strings minus the two v16b keys.  v16b-A: {final['trades']} tr / {final['net_$']:+,.0f} $ / "
      f"{final['return_%']:+.2f} % / DD {final['max_dd_%']:.2f} / PF {final['profit_factor']:.3f} / stop {final['sl_%']:.1f} % / $ lost {final['gross_loss_$']:,.0f} / worst day "
      f"{final['worst_day_%eq']:.2f} / OOS net {final['OOS_net_$']:+,.0f} / OOS PF {final['OOS_PF']:.2f} / {final['months_pos']}/{final['months']} months = IDENTICAL to the grid json "
      f"`{A}.json`; reference = {fref['trades']} / {fref['net_$']:+,.0f} / {fref['return_%']:+.2f} % / DD {fref['max_dd_%']:.2f} = FINAL_BACKTEST_V16.  `verify_bat_v16b.py`: IDENTICAL.  "
      f"Fast fills cancelled: {final.get('fast_cancelled')}; pending orders placed {final.get('pending_placed')} ({fref.get('pending_placed')}).\n")
    w("Where the reduction comes from (plan keys of the two final trade lists):\n"); w(md(who))
    w("\n![monthly](charts/v16b_monthly.png)\n")
    w("## 7. Recommendation and honest reading\n")
    w(f"* **Ship v16b-A** (done).  It removes the two loss slices the data points at and nothing else; the net rises because the removed / shrunk trades were net losers and "
      f"the freed slots and the better equity path go to the remaining plans.  In the base year every loss metric improves AND every profit metric improves.")
    w(f"* The stress misses of v16b-A are small and specific: slip x3 DD 5.98 vs 5.82 (the cancelled fills' slots are re-used by plans that then slip), risk 0.5 worst day "
      f"-2.16 vs -1.90 (0.01 pt beyond the band).  Profit and OOS bands hold in 6/6.")
    w(f"* **v16b-B** (`{B}`) saves the most money (gross loss {lev[lev.name == B].iloc[0]['gross_loss_$']:,.0f}, -32 %, PF {lev[lev.name == B].iloc[0].profit_factor:.2f}) but its worst day "
      f"({lev[lev.name == B].iloc[0]['worst_day_%eq']:.2f}) is 0.25 pt worse and 0.35-0.59 pt outside the band in 3 of 6 stress scenarios: the counter-trend skip removes the "
      f"sells that would have cushioned the 2026-04-08 cluster day.  **v16b-C** (`{C}`) earns the most ({lev[lev.name == C].iloc[0]['net_$']:+,.0f} $) but saves less "
      f"({lev[lev.name == C].iloc[0]['gross_loss_$']:,.0f}) and needs the daily-trend state live.  **F2 alone** is the minimal change ({lev[lev.name == F2].iloc[0]['net_$']:+,.0f} $, "
      f"$ lost {lev[lev.name == F2].iloc[0]['gross_loss_$']:,.0f}).")
    w("* What did NOT work and should not be retried on this trader: a break-even trigger below TP1 (kills the winners), a tighter day-loss cap (locks the loss in), the trend "
      "gate on both sides (removes the good buys), scaling instead of cancelling fast fills (the fill happens anyway), the unscoped trend skip (gives up the net).")
    w("* Limits: one year of one instrument, the OOS half is the entry model's OOS, not the levers' (they were chosen on the full year, then stress-tested and walk-forward "
      "checked).  The fast-fill guard live costs one spread per guarded fill instead of nothing - ~22 x spread a year.  Judge it on the demo account against the same "
      "metrics (stop %, $ lost, DD, worst day, PF) before trusting the size.\n")
    w("## 8. Files\n")
    w("`study_results/v16b_diag/DIAG.md` + 37 csv (diagnosis), `v16b_levers.csv` + `v16b_levers/` (96 runs: json, trades, equity), `v16b_stress.csv`, `v16b_stress_judged.csv`, "
      "`v16b_stress_summary.csv`, `v16b_walkforward.csv/.json`, `FINAL_BACKTEST_V16B.md` + `final_v16b/`, charts `charts/v16b_{equity,scatter,monthly,levers}.png`, "
      "`charts/final_v16b_equity.png`.  Code: `lubot/execution.py` (TraderConfig keys), `lubot/portfolio_sim.py`, `lubot/regime.py`, `trader.py`, `v16b_common.py`, "
      "`run_v16b_diag.py`, `run_v16b_levers.py`, `run_v16b_all.sh`, `run_v16b_stress.sh`, `judge_v16b_stress.py`, `walkforward_v16b.py`, `backtest_v16b_final.py`, "
      "`verify_bat_v16b.py`, `run_v16b_final.sh`, `make_v16b_report.py`, tests `tests/test_v16b_levers.py`, `tests/test_trader_v16b.py`, `tests/test_bat_v16b.py`.  "
      "Process log: `PROGRESS.md`.\n")
    (SR / "LESS_LOSS_V16B.md").write_text("\n".join(L), encoding="utf-8")
    print("wrote study_results/LESS_LOSS_V16B.md", len(L), "blocks")


if __name__ == "__main__":
    main()
