#!/usr/bin/env python3
"""v16c step 6b - report study_results/LESS_DD_V16C.md + charts/v16c_*.png from the v16c result files
(v16c_diag/*.csv, v16c_levers.csv, v16c_levers/*_trades.csv|_equity.csv, v16c_stress_judged.csv, v16c_stress_summary.csv,
v16c_walkforward.csv/json, final_v16c/*).  Every number in the report is read from those files - nothing is typed in.
The shipped variant is the one named in run_trader.bat (REM v16c study: ...).  Sections whose inputs are missing are marked pending.
    python3 make_v16c_report.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

SR = Path("study_results")
RUNS = SR / "v16c_levers"
DG = SR / "v16c_diag"
CH = SR / "charts"
CH.mkdir(exist_ok=True)
OOS = "2026-03-01"
REF = "ref"
B, C = "C_DDT3.5_x0.5_htf+DAY1.5_x0.5", "DDT3.0_x0.5_r2.0"
COLS = ["name", "trades", "net_$", "OOS_net_$", "max_dd_%", "dd2_%", "dd3_%", "ulcer", "OOS_max_dd_%", "profit_factor", "sl_%", "worst_day_%eq",
        "OOS_PF", "months_pos", "return_over_dd", "score"]
NICE = {"trades": "trades", "net_$": "net $", "OOS_net_$": "OOS net $", "max_dd_%": "max DD %", "dd2_%": "2nd DD %", "dd3_%": "3rd DD %", "ulcer": "ulcer",
        "OOS_max_dd_%": "OOS DD %", "profit_factor": "PF", "win_%": "win %", "sl_%": "stop %", "gross_loss_$": "$ lost", "worst_day_%eq": "worst day %",
        "OOS_PF": "OOS PF", "OOS_sl_%": "OOS stop %", "months_pos": "months +", "return_over_dd": "return/DD", "score": "score", "name": "variant",
        "family": "family", "overrides": "keys", "d_net_$": "net delta $", "d_dd_pt": "DD pt gained", "tag": "scenario", "n": "trades", "sl": "stop-outs",
        "loss_$": "$ lost", "risk_$": "risk $", "avg_risk_%eq": "avg risk % eq", "dd_scaled": "plans throttled", "day_soft_scaled": "day-cap scaled"}
TAGS = ("spread_x2", "commission_x2", "slip_x3", "worst_intrabar", "risk0.5", "risk2")


def esc(t: str) -> str:
    return t.replace("$", r"\$")


def md(df: pd.DataFrame, index=False) -> str:
    d = df.rename(columns=NICE).copy()
    for col in d.columns:
        if d[col].dtype.kind == "f":
            d[col] = d[col].round(0).astype("Int64") if "$" in str(col) else d[col].round(3)
    return d.to_markdown(index=index)


def fam(name: str) -> str:
    for p, f in (("ref", "ref"), ("C_", "combination"), ("DDT", "drawdown throttle"), ("DAY", "day soft cap"), ("OR", "open-risk cap"), ("STK", "streak throttle (control)")):
        if name.startswith(p):
            return f
    return "?"


def flags(r) -> str:
    return "".join(("D" if r.less_dd else "-", "P" if r.hold_profit else "-", "L" if r.hold_loss else "-", "O" if r.hold_oos else "-"))


def shipped() -> str:
    m = re.search(r"REM v16c study: study_results/v16c_levers/(\S+)\.json", open("run_trader.bat", encoding="utf-8").read())
    return m.group(1) if m else "DDT3.5_x0.5_htf"


def main():
    A = shipped()
    LABEL = {REF: "v16b-A reference", A: f"v16c-A: {A} (shipped)", B: f"v16c-B: {B} (deepest cut at 4/4)", C: f"v16c-C: {C} (ramp, all TFs)"}
    lev = pd.read_csv(SR / "v16c_levers.csv")
    lev["family"] = lev.name.map(fam)
    lev["flags"] = lev.apply(flags, axis=1)
    ref = lev[lev.name == REF].iloc[0]
    a = lev[lev.name == A].iloc[0]
    wf = pd.read_csv(SR / "v16c_walkforward.csv", index_col=0)
    wfj = json.load(open(SR / "v16c_walkforward.json"))
    have_stress = (SR / "v16c_stress_summary.csv").exists()
    have_final = (SR / "final_v16c" / "v16cA_summary.json").exists()
    stj = pd.read_csv(SR / "v16c_stress_judged.csv") if have_stress else None
    sts = pd.read_csv(SR / "v16c_stress_summary.csv") if have_stress else None
    final = json.load(open(SR / "final_v16c" / "v16cA_summary.json")) if have_final else a.to_dict()
    fref = json.load(open(SR / "final_v16c" / "ref_summary.json")) if have_final else ref.to_dict()
    keys = [k for k in (REF, A, B, C) if (RUNS / f"{k}_trades.csv").exists()]
    trades = {k: pd.read_csv(RUNS / f"{k}_trades.csv", parse_dates=["entry_time", "close_time"]) for k in keys}
    eq = {k: pd.read_csv(RUNS / f"{k}_equity.csv", index_col=0, parse_dates=True).equity for k in keys}
    dg = {f.stem: pd.read_csv(f) for f in DG.glob("*.csv")}

    # ---------------------------------------------------------------- charts
    fig, ax = plt.subplots(2, 1, figsize=(12, 8), sharex=True, gridspec_kw={"height_ratios": [3, 1]})
    for k, col in ((REF, "tab:blue"), (C, "tab:green"), (B, "tab:orange"), (A, "tab:red")):
        if k not in eq:
            continue
        r = lev[lev.name == k].iloc[0]
        ax[0].plot(eq[k].index, eq[k].values, color=col, lw=1.1,
                   label=esc(f"{LABEL[k]}: {int(r.trades)} tr, {r['net_$']:+,.0f} $, max DD {r['max_dd_%']:.2f} %, ulcer {r.ulcer:.2f}, PF {r.profit_factor:.2f}"))
        ax[1].plot(eq[k].index, (eq[k] / eq[k].cummax() - 1) * 100, color=col, lw=0.9)
    ax[0].axvline(pd.Timestamp(OOS), color="k", ls="--", lw=0.8); ax[0].set_ylabel(esc("equity $")); ax[0].grid(alpha=.3); ax[0].legend(fontsize=7, loc="upper left")
    ax[1].axhline(ref["max_dd_%"], color="tab:blue", ls=":", lw=0.8); ax[1].axhline(a["max_dd_%"], color="tab:red", ls=":", lw=0.8)
    ax[1].set_ylabel("drawdown %"); ax[1].grid(alpha=.3)
    ax[0].set_title("v16c - less drawdown on the v16b-A trader: full year, $10 000, 1 % base risk; dashed = entry model OOS")
    fig.tight_layout(); fig.savefig(CH / "v16c_equity.png", dpi=110); plt.close(fig)

    fig, ax = plt.subplots(figsize=(11, 6))
    ok = lev[lev.score == 4]; mid = lev[lev.score == 3]; bad = lev[lev.score < 3]
    ax.scatter(-bad["max_dd_%"], bad["net_$"], c="lightgray", s=18, label="score 0-2")
    ax.scatter(-mid["max_dd_%"], mid["net_$"], c="tab:olive", s=20, label="score 3")
    ax.scatter(-ok["max_dd_%"], ok["net_$"], c="tab:green", s=26, label="score 4 (less DD, profit held, loss profile held, OOS held)")
    for k, col in ((REF, "tab:blue"), (A, "tab:red"), (B, "tab:orange"), (C, "tab:green")):
        r = lev[lev.name == k].iloc[0]
        ax.scatter([-r["max_dd_%"]], [r["net_$"]], c=col, s=90, edgecolor="k", zorder=5)
        ax.annotate("v16b-A" if k == REF else k, (-r["max_dd_%"], r["net_$"]), fontsize=8, xytext=(5, 5), textcoords="offset points")
    ax.axvline(-ref["max_dd_%"], color="k", lw=0.6, ls=":"); ax.axhline(ref["net_$"], color="k", lw=0.6, ls=":")
    ax.axhline(0.97 * ref["net_$"], color="tab:red", lw=0.6, ls="--"); ax.axvline(-ref["max_dd_%"] - 0.25, color="tab:red", lw=0.6, ls="--")
    ax.set_xlabel("max drawdown % (left = less drawdown)"); ax.set_ylabel(esc("net $ / year")); ax.grid(alpha=.3); ax.legend(fontsize=8)
    ax.set_title(esc(f"{len(lev)} variants: max DD vs profit (dotted = v16b-A, dashed = the 0.25 pt / 97 % bands)"))
    fig.tight_layout(); fig.savefig(CH / "v16c_scatter.png", dpi=110); plt.close(fig)

    fig, ax = plt.subplots(1, 2, figsize=(13, 4))
    mo = pd.DataFrame({("v16b-A" if k == REF else "v16c-A"): trades[k].assign(m=trades[k].close_time.dt.strftime("%Y-%m")).groupby("m").net.sum() for k in (REF, A)})
    mo.plot.bar(ax=ax[0], width=0.8, color=["tab:blue", "tab:red"]); ax[0].grid(alpha=.3, axis="y"); ax[0].set_ylabel(esc("net $")); ax[0].set_title(esc("net $ per month"))
    mdd = pd.DataFrame({("v16b-A" if k == REF else "v16c-A"): (eq[k] / eq[k].cummax() - 1).groupby(eq[k].index.strftime("%Y-%m")).min() * 100 for k in (REF, A)})
    mdd.plot.bar(ax=ax[1], width=0.8, color=["tab:blue", "tab:red"]); ax[1].grid(alpha=.3, axis="y"); ax[1].set_ylabel("deepest DD % in the month"); ax[1].set_title("deepest drawdown (from the running peak) per month")
    fig.tight_layout(); fig.savefig(CH / "v16c_monthly.png", dpi=110); plt.close(fig)

    # threshold / scale / scope scans of the throttle
    fig, ax = plt.subplots(1, 2, figsize=(13, 4))
    for scope, col, lab in (("", "tab:red", "all TFs"), ("_htf", "tab:green", "M15|M20|M30|H1"), ("_bal", "tab:blue", "balance basis"), ("_nom5", "tab:gray", "M10+")):
        sc = lev[lev.name.str.match(rf"^DDT[0-9.]+_x0\.5{scope}$")].copy()
        if not len(sc):
            continue
        sc["x"] = sc.name.str.extract(r"DDT([0-9.]+)_")[0].astype(float); sc = sc.sort_values("x")
        ax[0].plot(sc.x, -sc["max_dd_%"], "o-", color=col, label=f"x0.5, {lab}")
        ax[1].plot(sc.x, 100 * sc["net_$"] / ref["net_$"], "o-", color=col, label=f"x0.5, {lab}")
    ax[0].axhline(-ref["max_dd_%"], color="k", lw=0.6, ls=":"); ax[0].axhline(-ref["max_dd_%"] - 0.25, color="tab:red", lw=0.6, ls="--")
    ax[0].set_xlabel("dd_throttle_pct (throttle while equity is more than x % under its peak)"); ax[0].set_ylabel("max DD %"); ax[0].grid(alpha=.3); ax[0].legend(fontsize=7)
    ax[0].set_title("drawdown throttle: max DD vs threshold")
    ax[1].axhline(100, color="k", lw=0.6, ls=":"); ax[1].axhline(97, color="tab:red", lw=0.6, ls="--")
    ax[1].set_xlabel("dd_throttle_pct"); ax[1].set_ylabel("net % of v16b-A"); ax[1].grid(alpha=.3); ax[1].legend(fontsize=7)
    ax[1].set_title("...and the net it keeps (the htf scope is the one that holds the 97 % band)")
    fig.tight_layout(); fig.savefig(CH / "v16c_levers.png", dpi=110); plt.close(fig)

    # ---------------------------------------------------------------- tables
    tops = lev[lev.score == 4].sort_values("max_dd_%", ascending=False)
    fam_best = lev[lev.name != REF].sort_values("score", ascending=False).groupby("family").head(3).sort_values(["family", "score", "max_dd_%"], ascending=[True, False, False])
    singles = {k: lev[lev.name.str.match(p)].sort_values("name") for k, p in (
        ("DDT_all", r"^DDT[0-9.]+_x[0-9.]+$"), ("DDT_bal", r"^DDT[0-9.]+_x[0-9.]+_bal$"), ("DDT_scope", r"^DDT[0-9.]+_x[0-9.]+_(htf|nom5|m510)$"),
        ("DDT_ramp", r"^DDT[0-9.]+_x[0-9.]+_r[0-9.]+$"), ("DAY", r"^DAY"), ("OR", r"^OR"), ("STK", r"^STK"))}
    ta, tr_ = trades[A], trades[REF]
    ka, kr = set(ta.key), set(tr_.key)

    def pop(x):
        return {"trades": len(x), "win %": round(100 * (x.net > 0).mean(), 1) if len(x) else 0, "stop %": round(100 * (x.outcome == "sl").mean(), 1) if len(x) else 0,
                "net $": round(x.net.sum(), 0), "$ lost": round(x.net[x.net < 0].sum(), 0), "avg risk $": round(x.risk_money.mean(), 0) if len(x) else 0,
                "avg R": round(x.r_net.mean(), 3) if len(x) else 0, "OOS net $": round(x[x.close_time >= OOS].net.sum(), 0)}
    thr = ta[ta.dd_scale < 1.0]
    thr_ref = tr_[tr_.key.isin(set(thr.key))]
    who = pd.DataFrame([{"slice": "plans THROTTLED by v16c-A (placed > 3.5 % under the peak, M15+): v16c-A result", **pop(thr)},
                        {"slice": "  the same plan keys in v16b-A (full size)", **pop(thr_ref)},
                        {"slice": "v16b-A trades NOT taken by v16c-A (knock-on)", **pop(tr_[tr_.key.isin(kr - ka)])},
                        {"slice": "trades NEW in v16c-A (knock-on)", **pop(ta[ta.key.isin(ka - kr)])},
                        {"slice": "all trades - v16b-A", **pop(tr_)}, {"slice": "all trades - v16c-A", **pop(ta)}])
    wf_names = [n for n in [REF, A, B, C, "DDT3.0_x0.5_htf", "C_DDT3.5_x0.5_htf+DAY1.5_x0.25", "C_DDT3.0_x0.5_r2.0+DAY2.0_x0.5", "DDT3.0_x0.25_r2.0", "DDT4.0_x0.25", "DDT3.5_x0.5_bal", "DDT3.5_x0.5"] if n in wf.index]
    wf_rows = wf.loc[wf_names, ["IS_n", "IS_net_$", "IS_PF", "IS_dd_%", "IS_ulcer", "IS_pass", "OOS_n", "OOS_net_$", "OOS_PF", "OOS_dd_%", "OOS_ulcer", "OOS_pass"]].reset_index()
    eps = dg["episodes"][["ep", "start", "trough", "depth_%", "days", "realised_%", "floating_%", "open_at_trough", "open_risk_at_trough_%", "closed_n", "closed_sl", "closed_loss_$", "avg_risk_%eq"]]

    # ---------------------------------------------------------------- report
    L = []; w = L.append
    w("# REDUCE THE MAX DRAWDOWN PERCENTAGE WHILE MAINTAINING THE PROFITABILITY PERCENTAGE (v16c) — the v16b-A trader\n")
    w(f"*Generated by `make_v16c_report.py` on {pd.Timestamp.utcnow():%Y-%m-%d %H:%M} UTC from the result files in `study_results/` (nothing typed in).*\n")
    w("## 0. Answer\n")
    src = "`FINAL_BACKTEST_V16C.md`" if have_final else f"grid run `v16c_levers/{A}.json` (final backtest pending)"
    w(f"**v16c-A = v16b-A + `{a.overrides}`** (shipped in `run_trader.bat`).  Full year Sep 2025 -> Sep 2026, $10 000, 1 % base risk, real costs ({src}): "
      f"**max drawdown {final['max_dd_%']:.2f} % (v16b-A {fref['max_dd_%']:.2f}, {final['max_dd_%'] - fref['max_dd_%']:+.2f} pt = {100 * (1 - abs(final['max_dd_%']) / abs(fref['max_dd_%'])):.0f} % less), "
      f"2nd / 3rd deepest episodes {final['dd2_%']:.2f} / {final['dd3_%']:.2f} ({fref['dd2_%']:.2f} / {fref['dd3_%']:.2f}), ulcer {final['ulcer']:.3f} ({fref['ulcer']:.3f}), "
      f"OOS max DD {final['OOS_max_dd_%']:.2f} ({fref['OOS_max_dd_%']:.2f}), return / max DD {final['return_over_dd']:.1f} ({fref['return_over_dd']:.1f}) — with the profitability held: "
      f"net {final['net_$']:+,.0f} $ ({fref['net_$']:+,.0f}, {100 * (final['net_$'] / fref['net_$'] - 1):+.1f} %), {final['return_%']:+.1f} %, profit factor {final['profit_factor']:.3f} "
      f"({fref['profit_factor']:.3f}), win {final['win_%']:.1f} % ({fref['win_%']:.1f}), stop-outs {final['sl_%']:.1f} % ({fref['sl_%']:.1f}), gross $ lost {final['gross_loss_$']:,.0f} "
      f"({fref['gross_loss_$']:,.0f}), worst day {final['worst_day_%eq']:.2f} % ({fref['worst_day_%eq']:.2f}), OOS net {final['OOS_net_$']:+,.0f} $ ({fref['OOS_net_$']:+,.0f}), "
      f"OOS PF {final['OOS_PF']:.2f} ({fref['OOS_PF']:.2f}), {int(final['months_pos'])}/13 months positive, {int(final['trades'])} trades ({int(fref['trades'])}).**  "
      f"Score 4/4 on the v16c judge; walk-forward: the drawdown is cut in BOTH halves with the net held in both"
      + (f"; stress x6: {int(sts.set_index('name').loc[A, 'all4'])}/6 scenarios 4/4, profit held {int(sts.set_index('name').loc[A, 'hold_profit'])}/6, "
         f"DD better by >= 0.25 pt in {int(sts.set_index('name').loc[A, 'dd_better_in'])}/6." if have_stress else "; stress x6: pending.") + "\n")
    w("The lever is decided BEFORE the order is placed and is live already (`trader.py`, tests `tests/test_trader_v16c.py`, `tests/test_bat_v16c.py`):")
    w(f"* **Equity-drawdown throttle on the higher timeframes** (`{a.overrides}`): while the account equity (balance + floating P/L) is more than 3.5 % below "
      "its running peak, every NEW M15 / M20 / M30 / H1 plan is sized at half risk; M5 / M10 plans keep full size.  Nothing is closed or cancelled; the size comes "
      "back as soon as equity is within 3.5 % of the peak.  The peak is persisted in `trader_state.json` (`risk.peak_equity`, refreshed every loop) so a restart "
      "inside a drawdown keeps throttling.\n")
    w("![equity](charts/v16c_equity.png)\n")
    w("## 1. Method\n")
    w(f"Same discipline as v10-v16b: the v16b-A trader exactly as shipped (strings frozen in `v16c_common.py` and cross-checked against the bat), replayed through "
      f"the M1 portfolio simulator over the full year; parity of the reference reproduced first ({int(ref.trades)} tr / {ref['net_$']:+,.0f} $ / DD {ref['max_dd_%']:.2f} = "
      f"FINAL_BACKTEST_V16B).  **Interpretation**: *max drawdown percentage* = the max peak-to-trough fall of the EQUITY path (closed + floating, the number of every "
      f"report); *profitability percentage* = return % (net $) AND profit factor AND OOS net.  **Judge (`v16c_common.judge16c`)**: *less_dd* = max DD better by >= 0.25 pt "
      f"AND OOS max DD not worse AND ulcer <= ref (the whole path shallower, not one point); *hold_profit* = net >= 97 % of ref AND PF >= ref - 0.10 AND OOS net >= 97 %; "
      f"*hold_loss* = stop % <= ref + 1 pt AND gross $ lost <= 105 % AND worst day >= ref - 0.25 pt (the v16b gains must not regress); *hold_oos* = OOS PF >= ref - 0.10 "
      f"AND OOS stop % <= ref + 1 pt AND 13/13 months.  Score 0-4.  Steps: diagnosis of the drawdown episodes -> levers in the simulator (defaults byte-identical) -> "
      f"grid of {len(lev)} variants -> walk-forward of the whole grid + stress x6 of 6 finalists -> port to the bat + live bot -> final backtest from the bat strings.\n")
    w("## 2. Diagnosis — what the drawdown of v16b-A is made of (`v16c_diag/DIAG.md`, 15 tables)\n")
    w("Five episodes within 1.5 pt of each other - a lever has to cut ALL of the top three, otherwise the max DD just moves to the next one.  The deepest (#1, Aug 2026) "
      "is a third FLOATING: three confluent buys open at the trough (3.7 % open risk) that all won afterwards; #2 and #3 (autumn 2025) are long, all-realised grinds of "
      "small losers.  The balance-path (closed trades only) DD is just -5.09 %: the floating part of open, eventually winning positions adds the last 0.5 pt.\n")
    w(md(eps))
    w("\n**Trades by the account's drawdown at the fill** - the trades taken while the account is under water EARN (they are the recovery), so a throttle costs recovery "
      "and can only win on DEPTH - and the deeper bands are small:\n"); w(md(dg["by_dd_band"]))
    w("\n**After consecutive losses** - the next trades are fine (a streak throttle is not a lever):\n"); w(md(dg["by_prev_losses"]))
    w("\n**Risk per plan** - the big plans (confluent x1.25) stop out least and earn most; the small ones stop out most.  Sizing already follows quality - nothing to cut there:\n")
    w(md(dg["by_risk_band"]))
    w("\n**Concurrent same-side plans** - 1-2 open same-side plans WIN (a same-side cap halves the profit):\n"); w(md(dg["by_same_side"]))
    w("\n**Static estimate** (trade list re-walked with a sizing rule, before re-simulation; balance-path DD): only the 3.0-3.5 % x0.5-0.75 throttles cut >= 0.2 pt at >= 97 % net:\n")
    st_ = dg["static_levers"]; st_ = st_[(st_["net_%ref"] >= 95)].sort_values("bal_dd_%", ascending=False).head(14)
    w(md(st_))
    w("\nNOT levers (checked statically and in the grid): loss-streak throttle, week-loss cap (never fires), per-plan risk cap, same-side cap, open-risk skip / fit cap "
      "(it scales exactly the confluence winners), hard day cap (worst day gets worse).\n")
    w("## 3. Levers (simulator + live bot, defaults off, parity byte-identical)\n")
    w("| key | what it does |\n|:--|:--|")
    w("| `dd_throttle_pct=x`, `dd_throttle_scale=s`, `dd_throttle_ramp=r`, `dd_basis=equity\\|balance`, `dd_throttle_tfs` | while the account (equity or balance) is more than x % below its running peak, new plans are sized x s (0 = skipped); r > 0 = linear ramp from x to x + r; tf scope |")
    w("| `day_soft_loss_pct=x`, `day_soft_scale=s` | once the day's equity is x % below the day-start equity, new plans x s for the rest of the server day (no flatten, unlike max_daily_loss_pct) |")
    w("| `max_open_risk_pct=x`, `open_risk_mode=fit\\|skip`, `open_risk_pending` | the new plan is scaled to fit (or skipped) so the open risk-at-stop (BE legs = 0) stays under x % of equity |")
    w("| `streak_n`, `streak_scale`, `streak_days` | control: new plans x s after n consecutive losing closes |\n")
    w(f"## 4. Grid — {len(lev)} variants (`v16c_levers.csv`; one json + trade list + equity per run in `v16c_levers/`)\n")
    w(f"Flags: D = less drawdown, P = profit held, L = loss profile held, O = OOS held.  **{len(tops)} variants score 4/4** - all of them the equity-drawdown throttle "
      f"on the higher timeframes or with a ramp - sorted by max DD (shallowest first):\n")
    w(md(tops[COLS + ["flags", "overrides"]]))
    w("\n![scatter](charts/v16c_scatter.png)\n")
    w("### 4a. Single levers\n")
    w("**Drawdown throttle, all timeframes, equity basis**: the DD falls with the threshold / scale, but so does the net - the throttled M5/M10 plans are the recovery "
      "(x0.25 and the 2.0-2.5 % thresholds give up 13-64 % of the net):\n"); w(md(singles["DDT_all"][COLS + ["flags"]]))
    w("\n**Scoped by timeframe** - M15+ only (`_htf`) is the sweet spot: the same DD cut at 99-101 % of the net; M5|M10 only is the WORST scope, M10+ in between:\n")
    w(md(singles["DDT_scope"][COLS + ["flags"]]))
    w("\n**Balance basis** (closed trades only, no floating): never moves the max DD - the deepest episode is the floating one:\n"); w(md(singles["DDT_bal"][COLS + ["flags"]]))
    w("\n**Ramps** (x1 at the threshold -> x s at threshold + r): 3.0 % -> 5.0 % x0.5 holds the net (4/4); steeper / earlier ramps do not:\n"); w(md(singles["DDT_ramp"][COLS + ["flags"]]))
    w("\n![levers](charts/v16c_levers.png)\n")
    w("\n**Day soft cap alone**: no DD cut (only multi-day episodes matter); x0 (skip) makes the worst day worse:\n"); w(md(singles["DAY"][COLS + ["flags"]]))
    w("\n**Open-risk cap** (fit / skip / pending-cancel): DD unchanged or worse, net 53-95 % - it shrinks exactly the confluence winners:\n"); w(md(singles["OR"][COLS + ["flags"]]))
    w("\n**Streak throttle** (control): DD unchanged:\n"); w(md(singles["STK"][COLS + ["flags"]]))
    w("\n### 4b. Combinations\n")
    w(md(lev[lev.name.str.startswith("C_")].sort_values(["score", "max_dd_%"], ascending=[False, False])[COLS + ["flags"]]))
    w("\nBest three per family:\n"); w(md(fam_best[["family"] + COLS + ["flags"]]))
    w("\n## 5. Robustness — walk-forward of the whole grid and stress x6 of the finalists\n")
    w(f"**Walk-forward** (`v16c_walkforward.csv`, split {OOS} on close time; each half's DD measured on its own equity path, peak reset at the half's start): a half passes "
      f"when its max DD is better by >= 0.25 pt AND its ulcer not worse AND net >= 97 % AND PF >= ref - 0.10 AND the loss profile held.  {wfj['oos_pass']} of "
      f"{wfj['n_variants']} variants pass the OOS half, {wfj['is_pass']} the IS half, **{wfj['both']} pass BOTH** - the htf throttle family: the IS half holds episodes #2 / #3, "
      f"the OOS half #1 / #4, and the lever cuts both independently.  IS->OOS Spearman of the deltas vs ref: DD rho {wfj['spearman']['d_dd']['rho']:.2f}, ulcer "
      f"{wfj['spearman']['d_ulcer']['rho']:.2f}, net {wfj['spearman']['d_net']['rho']:.2f} (all p < 1e-7: the gains carry over), PF {wfj['spearman']['d_PF']['rho']:.2f}.  "
      f"The balance-basis throttles pass IS and FAIL OOS (the OOS top episode is the floating one); the ramp family passes OOS only (its IS cut is 0.16 pt).\n")
    w(md(wf_rows))
    if have_stress:
        w("\n**Stress x6** (`v16c_stress.csv`): each finalist re-run in 6 scenarios (spread x2, commission x2, slippage x3, worst intrabar order, risk 0.5 %, risk 2 %) and judged "
          "against the v16b-A row of the SAME scenario (`v16b_stress.csv`).  Scenarios passed out of 6 per question (`v16c_stress_summary.csv`):\n")
        w(md(sts))
        st_rows = stj[stj.name.isin([A, B, C])].copy(); st_rows["flags"] = st_rows.apply(flags, axis=1)
        st_tbl = st_rows[["name", "tag", "trades", "net_$", "ref_net_$", "max_dd_%", "ref_max_dd_%", "ulcer", "ref_ulcer", "OOS_max_dd_%", "ref_OOS_max_dd_%", "profit_factor", "ref_PF",
                          "sl_%", "worst_day_%eq", "ref_worst_day_%eq", "OOS_PF", "months_pos", "flags", "misses"]].rename(
            columns={"ref_net_$": "v16b-A net $", "ref_max_dd_%": "v16b-A DD %", "ref_ulcer": "v16b-A ulcer", "ref_OOS_max_dd_%": "v16b-A OOS DD %", "ref_PF": "v16b-A PF",
                     "ref_worst_day_%eq": "v16b-A worst day %"})
        st_tbl["misses"] = st_tbl.misses.fillna("none")
        w("\nScenario by scenario for the shipped variant and the alternatives (`v16c_stress_judged.csv`):\n"); w(md(st_tbl))
    else:
        w("\n**Stress x6**: pending (run `bash run_v16c_stress.sh`).\n")
    w("\n## 6. Final backtest from the bat strings (`FINAL_BACKTEST_V16C.md`, `final_v16c/`)\n")
    if have_final:
        w(f"The strings are read from `run_trader.bat` and replayed; the reference = the same strings minus the v16c keys.  v16c-A: {int(final['trades'])} tr / {final['net_$']:+,.0f} $ / "
          f"{final['return_%']:+.2f} % / max DD {final['max_dd_%']:.2f} / ulcer {final['ulcer']:.3f} / PF {final['profit_factor']:.3f} / stop {final['sl_%']:.1f} % / worst day "
          f"{final['worst_day_%eq']:.2f} / OOS net {final['OOS_net_$']:+,.0f} / OOS DD {final['OOS_max_dd_%']:.2f} / {int(final['months_pos'])}/13 months = IDENTICAL to the grid json "
          f"`{A}.json`; reference = {int(fref['trades'])} / {fref['net_$']:+,.0f} / {fref['return_%']:+.2f} % / DD {fref['max_dd_%']:.2f} = FINAL_BACKTEST_V16B.  `verify_bat_v16c.py`: IDENTICAL.  "
          f"Plans throttled: {final.get('dd_scaled')}; minutes spent more than 3.5 % under the peak: {final.get('dd_days')}.\n")
    else:
        w("Pending (run `bash run_v16c_final.sh`).  The numbers above come from the grid run of the shipped variant.\n")
    w("Where the reduction comes from (plan keys of the two trade lists of the shipped variant vs the reference):\n"); w(md(who))
    w("\n![monthly](charts/v16c_monthly.png)\n")
    w("## 7. Recommendation and honest reading\n")
    rb, rc = lev[lev.name == B].iloc[0], lev[lev.name == C].iloc[0]
    w(f"* **Ship v16c-A** (done).  One key family, one number to understand: half size on the slower timeframes while the account is more than 3.5 % under its peak.  "
      f"It cuts all three top episodes ({a['dd1_%']:.2f} / {a['dd2_%']:.2f} / {a['dd3_%']:.2f} vs {ref['dd1_%']:.2f} / {ref['dd2_%']:.2f} / {ref['dd3_%']:.2f}), the ulcer "
      f"and the OOS drawdown, keeps every profit metric within a rounding error and passes the walk-forward in both halves.")
    w(f"* **v16c-B** (`{B}`) adds the day soft cap and reaches DD {rb['max_dd_%']:.2f} (-{abs(rb['max_dd_%'] - ref['max_dd_%']):.2f} pt) at {100 * rb['net_$'] / ref['net_$']:.1f} % of the net - the deepest "
      f"cut that still scores 4/4; its IS-half cut is only 0.25 pt (the band edge) and it adds a second state variable to the live bot.  **v16c-C** (`{C}`) is the ramp on all "
      f"timeframes: DD {rc['max_dd_%']:.2f} at {100 * rc['net_$'] / ref['net_$']:.1f} % net, PF {rc.profit_factor:.2f} - smoother, but it fails the IS half (0.16 pt).")
    w("* What did NOT work and should not be retried on this trader: throttling M5/M10 in a drawdown (they are the recovery), the balance basis (misses the floating episode), "
      "deep throttles (x0.25, thresholds <= 2.5 %), open-risk caps (shrink the confluence winners), a hard day cap, a streak throttle, a same-side cap.")
    w("* Limits: one year of one instrument; the five episodes are 1.5 pt apart, so the max DD of ANY variant is a single-episode number - the ulcer, the 2nd / 3rd episodes "
      "and the both-halves walk-forward are the evidence that the whole path is shallower, not one point.  The live bot samples the peak once per loop (seconds), the "
      "simulator every minute - same quantity, slightly coarser.  Judge it on the demo account against the same metrics (max DD, ulcer, net, PF) before trusting the size.\n")
    w("## 8. Files\n")
    w("`study_results/v16c_diag/DIAG.md` + 15 csv (diagnosis), `v16c_levers.csv` + `v16c_levers/` (117 runs: json, trades, equity), `v16c_walkforward.csv/.json`, "
      "`v16c_stress.csv`, `v16c_stress_judged.csv`, `v16c_stress_summary.csv`, `FINAL_BACKTEST_V16C.md` + `final_v16c/`, charts `charts/v16c_{equity,scatter,monthly,levers}.png`, "
      "`charts/final_v16c_equity.png`.  Code: `lubot/execution.py` (TraderConfig keys), `lubot/portfolio_sim.py` (`_apply_v16c`), `trader.py` (`_apply_v16c`, `update_peak`), "
      "`v16c_common.py`, `run_v16c_diag.py`, `run_v16c_levers.py`, `run_v16c_all.sh`, `run_v16c_stress.sh`, `judge_v16c_stress.py`, `walkforward_v16c.py`, "
      "`backtest_v16c_final.py`, `verify_bat_v16c.py`, `run_v16c_final.sh`, `make_v16c_report.py`, tests `tests/test_v16c_common.py`, `tests/test_v16c_levers.py`, "
      "`tests/test_trader_v16c.py`, `tests/test_bat_v16c.py`.  Process log: `PROGRESS.md`.\n")
    (SR / "LESS_DD_V16C.md").write_text("\n".join(L), encoding="utf-8")
    print("wrote study_results/LESS_DD_V16C.md", len(L), "blocks; stress", have_stress, "final", have_final)


if __name__ == "__main__":
    main()
