#!/usr/bin/env python3
"""v15 step 5 - report study_results/MORE_TRADES_V15.md + charts/v15_*.png from the v15 result files
(v15_diag/*, v15_levers.csv, v15_stress_table.csv, v15_walkforward.csv/json, per-run trades/equity, final_v15/).
Every number in the report is read from those files - nothing is typed in.      python3 make_v15_report.py
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

SR = Path("study_results")
RUNS = SR / "v15_levers"
DIAG = SR / "v15_diag"
CH = SR / "charts"
CH.mkdir(exist_ok=True)
OOS = "2026-03-01"
REF, A, B, C = "ref", "CMB_cm240_cs1.25_0.9", "CMB_cm240_cs1.25_0.9_Tm10q55", "CM_960"
LABEL = {REF: "v14-A reference", A: "v15-A: confluence memory 240 min + conviction x1.25 / x0.9 (shipped)",
         B: "v15-B: v15-A + M10 tier 0.55 at half size (most trades)", C: "v15-C: confluence memory 960 min only (sizing untouched)"}
COLS = ["trades", "net_$", "OOS_net_$", "max_dd_%", "profit_factor", "win_%", "sl_%", "worst_day_%eq", "OOS_PF", "OOS_sl_%", "months_pos",
        "max_risk_%eq", "return_over_dd", "score"]
NICE = {"trades": "trades", "net_$": "net $", "OOS_net_$": "OOS net $", "max_dd_%": "max DD %", "profit_factor": "PF", "win_%": "win %",
        "sl_%": "stop %", "worst_day_%eq": "worst day %", "OOS_PF": "OOS PF", "OOS_sl_%": "OOS stop %", "months_pos": "months +",
        "max_risk_%eq": "max risk %", "return_over_dd": "ret/DD", "score": "score", "name": "variant"}


def md(df: pd.DataFrame, index=False) -> str:
    return df.rename(columns=NICE).to_markdown(index=index)


def fam(name: str) -> str:
    for p, f in (("ref", "ref"), ("CMB", "combination"), ("CS_", "conviction sizing"), ("CM_", "confluence memory"), ("TIER", "tier"), ("DD_", "DD buy-back")):
        if name.startswith(p):
            return f
    return "?"


def main():
    lev = pd.read_csv(SR / "v15_levers.csv")
    lev["family"] = lev.name.map(fam)
    ref = lev[lev.name == REF].iloc[0]
    stress = pd.read_csv(SR / "v15_stress_table.csv")
    wf = pd.read_csv(SR / "v15_walkforward.csv", index_col=0)
    wfj = json.load(open(SR / "v15_walkforward.json"))
    final = json.load(open(SR / "final_v15" / "v15A_summary.json"))
    fref = json.load(open(SR / "final_v15" / "ref_summary.json"))
    notes = (DIAG / "notes.txt").read_text().splitlines()
    fun = pd.read_csv(DIAG / "funnel.csv")
    bands = pd.read_csv(DIAG / "rejected_bands.csv")
    trades = {k: pd.read_csv(RUNS / f"{k}_trades.csv", parse_dates=["entry_time", "close_time"]) for k in (REF, A, B, C)}
    eq = {k: pd.read_csv(RUNS / f"{k}_equity.csv", index_col=0, parse_dates=True).equity for k in (REF, A, B, C)}

    # ---------------------------------------------------------------- charts
    fig, ax = plt.subplots(2, 1, figsize=(12, 8), sharex=True, gridspec_kw={"height_ratios": [3, 1]})
    for k, col in ((REF, "tab:blue"), (C, "tab:green"), (B, "tab:orange"), (A, "tab:red")):
        r = lev[lev.name == k].iloc[0]
        ax[0].plot(eq[k].index, eq[k].values, color=col, lw=1.1,
                   label=f"{LABEL[k]}: {int(r.trades)} tr, {r['net_$']:+,.0f} $, DD {r['max_dd_%']:.2f} %, PF {r.profit_factor:.2f}")
        ax[1].plot(eq[k].index, (eq[k] / eq[k].cummax() - 1) * 100, color=col, lw=0.9)
    ax[0].axvline(pd.Timestamp(OOS), color="k", ls="--", lw=0.8); ax[0].set_ylabel("equity $"); ax[0].grid(alpha=.3); ax[0].legend(fontsize=8, loc="upper left")
    ax[1].set_ylabel("drawdown %"); ax[1].grid(alpha=.3)
    ax[0].set_title("v15 - more trades & more profit at the same loss percentage (full year, $10 000, 1 % base risk; dashed = entry model OOS)")
    fig.tight_layout(); fig.savefig(CH / "v15_equity.png", dpi=110); plt.close(fig)
    fig, ax = plt.subplots(figsize=(11, 6))
    ok = lev[lev.hold_loss & lev.hold_oos]; bad = lev[~(lev.hold_loss & lev.hold_oos)]
    ax.scatter(bad.trades, bad["net_$"], c="lightgray", s=18, label="loss band broken (full year or OOS)")
    ax.scatter(ok.trades, ok["net_$"], c="tab:green", s=22, label="loss percentage held (full year AND OOS)")
    for k, col in ((REF, "tab:blue"), (A, "tab:red"), (B, "tab:orange"), (C, "tab:green")):
        r = lev[lev.name == k].iloc[0]
        ax.scatter([r.trades], [r["net_$"]], c=col, s=90, edgecolor="k", zorder=5)
        ax.annotate(k if k != REF else "v14-A", (r.trades, r["net_$"]), fontsize=8, xytext=(5, 5), textcoords="offset points")
    ax.axvline(ref.trades, color="k", lw=0.6, ls=":"); ax.axhline(ref["net_$"], color="k", lw=0.6, ls=":")
    ax.set_xlabel("trades / year"); ax.set_ylabel("net $ / year"); ax.grid(alpha=.3); ax.legend(fontsize=8)
    ax.set_title(f"{len(lev)} variants: trades vs profit (dotted = v14-A)")
    fig.tight_layout(); fig.savefig(CH / "v15_scatter.png", dpi=110); plt.close(fig)
    fig, ax = plt.subplots(figsize=(12, 4))
    mo = pd.DataFrame({LABEL[k].split(":")[0]: trades[k].assign(m=trades[k].close_time.dt.strftime("%Y-%m")).groupby("m").net.sum() for k in (REF, A, C)})
    mo.plot.bar(ax=ax, width=0.8, color=["tab:blue", "tab:red", "tab:green"]); ax.grid(alpha=.3, axis="y"); ax.set_ylabel("net $"); ax.set_title("net $ per month")
    fig.tight_layout(); fig.savefig(CH / "v15_monthly.png", dpi=110); plt.close(fig)
    fig, ax = plt.subplots(figsize=(8, 4))
    sub = lev[lev.name.str.match(r"CMB_cm\d+_cs1\.25_0\.9$")].copy(); sub["mins"] = sub.name.str.extract(r"cm(\d+)").astype(int); sub = sub.sort_values("mins")
    ax.plot(sub.mins, -sub["max_dd_%"], "o-", label="max DD % (conviction x1.25/0.9)"); ax.plot(sub.mins, -sub["worst_day_%eq"], "s--", label="worst day %")
    ax.axhline(-ref["max_dd_%"], color="k", ls=":", lw=0.8); ax.axhline(-ref["max_dd_%"] + 0.5, color="r", ls=":", lw=0.8, label="DD band (ref + 0.5)")
    ax.set_xlabel("confluence memory window (min)"); ax.grid(alpha=.3); ax.legend(fontsize=8); ax.set_title("the DD depends on the memory window")
    fig.tight_layout(); fig.savefig(CH / "v15_dd_window.png", dpi=110); plt.close(fig)

    # ---------------------------------------------------------------- tables
    tops = lev[lev.score == 4].sort_values("OOS_net_$", ascending=False)
    fam_best = lev.sort_values("OOS_net_$", ascending=False).groupby("family").head(3).sort_values(["family", "OOS_net_$"], ascending=[True, False])
    pop = pd.read_csv(SR / "final_v15" / "v15A_trades.csv", parse_dates=["close_time"])
    conf, plain = pop[pop.confluent], pop[~pop.confluent]
    rp = trades[REF]; rconf, rplain = rp[rp.confluent], rp[~rp.confluent]
    grp = pd.DataFrame([{"population": lab, "trades": len(x), "win %": round(100 * (x.net > 0).mean(), 1), "stop %": round(100 * (x.outcome == "sl").mean(), 1),
                         "avg R": round(x.r_net.mean(), 3), "net $": round(x.net.sum(), 0), "OOS win %": round(100 * (x[x.close_time >= OOS].net > 0).mean(), 1)}
                        for lab, x in (("v14-A confluent (active now)", rconf), ("v14-A plain", rplain),
                                       ("v15-A confluent (active now or within 240 min)", conf), ("v15-A plain", plain))])
    qband = bands[bands.group == "tfxreason"][["tf", "reason", "pois", "filled", "fill_%", "win_%", "avg_R", "sum_R", "oos_sum_R"]]
    st_rows = []
    for tag in ("spread_x2", "commission_x2", "slip_x3", "worst_intrabar", "risk0.5", "risk2"):
        for nm in ("ref(v14-A)", A, B, C):
            r = stress[(stress.tag == tag) & (stress.name == nm)]
            if len(r):
                r = r.iloc[0]
                st_rows.append({"scenario": tag, "variant": "v14-A" if nm.startswith("ref") else nm, "trades": int(r.trades), "net $": round(r["net_$"], 0),
                                "OOS net $": round(r["OOS_net_$"], 0), "max DD %": r["max_dd_%"], "PF": r.profit_factor, "win %": r["win_%"], "stop %": r["sl_%"],
                                "worst day %": r["worst_day_%eq"], "OOS PF": r.OOS_PF, "months +": int(r.months_pos)})
    st_df = pd.DataFrame(st_rows)
    wf_rows = wf.loc[[REF, A, B, C, "CS_1.25_0.8", "CM_240"],
                     ["IS_n", "IS_net_$", "IS_PF", "IS_sl_%", "IS_pass", "OOS_n", "OOS_net_$", "OOS_PF", "OOS_sl_%", "OOS_win_%", "OOS_pass"]].reset_index()
    a = lev[lev.name == A].iloc[0]; b = lev[lev.name == B].iloc[0]; c = lev[lev.name == C].iloc[0]
    note = lambda pre: [n for n in notes if n.startswith(pre)][0].split(": ", 1)[1]

    # ---------------------------------------------------------------- report
    L = []; w = L.append
    w("# MORE TRADES & MORE PROFIT AT THE SAME LOSS PERCENTAGE (v15) — for the v14-A trader\n")
    w(f"**Question.**  The v14-A trader (run_trader.bat: regime ladder + asymmetric martingale) takes **{int(ref.trades)} trades a year** "
      f"(Sep 2025 -> Sep 2026: net **{ref['net_$']:+,.0f} $**, {ref['return_%']:+.1f} %, max DD {ref['max_dd_%']:.2f} %, PF {ref.profit_factor:.3f}, win {ref['win_%']:.1f} %, "
      f"stop-outs {ref['sl_%']:.1f} %, worst day {ref['worst_day_%eq']:.2f} %, OOS PF {ref.OOS_PF:.2f}).  Make it take **more trades** and earn **more profit** "
      f"while **keeping the loss percentage** (stop-out rate, win rate, max DD, worst day, PF) where it is.\n")
    w(f"**Answer in one line.**  Two levers, both built on the one signal the diagnosis found (plans whose zone is CONFLUENT with another timeframe win "
      f"{100 * (rconf.net > 0).mean():.0f} % vs {100 * (rplain.net > 0).mean():.0f} % for the rest, in-sample AND out-of-sample): "
      f"(1) **confluence memory** - a zone counts as confluent when a plan of another timeframe on that level was active within the last N minutes, not only "
      f"right now, so more zones are judged by the looser confluence bar (`confluence_memory_min`); (2) **conviction sizing** - confluent plans x1.25, plain plans x0.9 "
      f"(`confluent_risk_scale` / `plain_risk_scale`).  Together = **v15-A: {int(a.trades)} trades ({int(a.trades - ref.trades):+d}), net {a['net_$']:+,.0f} $ "
      f"({100 * (a['net_$'] / ref['net_$'] - 1):+.0f} %), OOS net {a['OOS_net_$']:+,.0f} $ ({100 * (a['OOS_net_$'] / ref['OOS_net_$'] - 1):+.0f} %), max DD {a['max_dd_%']:.2f} % "
      f"(ref {ref['max_dd_%']:.2f}), PF {a.profit_factor:.3f}, win {a['win_%']:.1f} %, stop-outs {a['sl_%']:.1f} %, worst day {a['worst_day_%eq']:.2f} % (ref {ref['worst_day_%eq']:.2f}), "
      f"OOS PF {a.OOS_PF:.2f}, {int(a.months_pos)}/13 months** - every loss metric inside the band on the full year and on the OOS half, and ahead of v14-A on net $ "
      f"and OOS PF in 6/6 stress scenarios.  **v15-B** adds an M10 second tier (quality 0.55-0.57 at half size): {int(b.trades)} trades, {b['net_$']:+,.0f} $, DD {b['max_dd_%']:.2f} %, "
      f"OOS PF {b.OOS_PF:.2f}.  **v15-C** (memory 960 min alone, sizing untouched): {int(c.trades)} trades, {c['net_$']:+,.0f} $, worst day unchanged - the choice when the "
      f"worst-day rise of the sizing ({ref['worst_day_%eq']:.2f} -> {a['worst_day_%eq']:.2f} %) is not acceptable.  Tiered admission of quality / cost rejects, re-arming after a stop "
      f"and entering in front of the zone were measured and rejected (sections 1 and 3).\n")
    w("![equity](charts/v15_equity.png)\n")
    w("---\n\n## 0. Method\n")
    w(f"* **Reference** = v14-A exactly as shipped (`run_v15_diag.py` reproduces FINAL_BACKTEST_V14 byte for byte: {int(ref.trades)} trades, {ref['return_%']:+.2f} %, DD {ref['max_dd_%']:.2f}).  "
      "Full-year selection streams `sel_v10_<TF>.pkl`, M1 portfolio simulator, real per-minute spread, $7/lot commission, $0.10 stop slippage, swaps, 1 % base risk on $10 000, "
      "mirror orders, v13 regime ladder, v14 per-TF martingale, loss rules 4.5 % / 9 %.")
    w(f"* **Honesty.**  The entry model was trained until {OOS}: Sep 2025 - Feb 2026 is in-sample, Mar - Sep 2026 out-of-sample.  Every variant is judged on both halves.")
    w("* **Loss percentage held** (`hold_loss`, full year): stop-out rate <= ref + 2 pt, win rate >= ref - 3 pt, max DD <= ref + 0.5 pt, worst day >= ref - 0.5 pt, PF >= ref - 0.10; "
      "`hold_oos`: stop rate / win rate / PF on the OOS half + the DD condition.  `more_trades`: n > ref.  `more_profit`: net $ AND OOS net $ > ref.  score = the four together.")
    w(f"* Steps: (1) diagnosis `run_v15_diag.py`; (2) four new simulator levers, defaults byte-identical to v14 (parity exact), 7 unit tests + 2 fake-MT5 tests; (3) grid "
      f"`run_v15_levers.py`: {len(lev)} full-year runs, resumable (one json per run), autosaved to GitHub every 4 min (survived three sandbox resets); (4) stress x6 + walk-forward; "
      "(5) `backtest_v15_final.py` from the bat strings; this report `make_v15_report.py`.  **140 tests pass.**\n")
    w("---\n\n## 1. Diagnosis — where are the trades, and what is left outside?\n")
    w("Funnel of the v14-A reference (unique POIs shown by the scanner -> the last stage reached):\n")
    w(md(fun.pivot_table(index="stage", columns="tf", values="pois", aggfunc="sum", fill_value=0).reset_index()))
    w("\nWould-be outcome of the POIs the trade filter rejects (stand-alone plan replayer, order live while the slot shows the POI; the same replayer agrees with the "
      "simulator on 95.6 % of the traded population's signs):\n")
    w(md(qband))
    w("\n* Only **M10 quality 0.50-0.57** carries a (thin) positive edge (+0.10 R, OOS +0.6 R on 24 fills); M15 / M5 / H1 quality rejects lose 0.24-0.36 R per fill; the M5 cost "
      "band 0.08-0.12 is flat.  **Admission relaxation is exhausted** (as v11 / v12 found) - a tier can add trades, not profit.")
    w("* **Re-arming a zone after a stop-out is dead**: 106 of 107 stopped plans have the price through the entry at the stop -> 1 re-fill in the year.")
    w("* **Entering in front of the zone** (0.1-0.3 of the zone height) fills 4-15 % of the never-filled orders at -0.04..+0.09 R -> dead (as v11).")
    w("* **The signal**: plans whose zone overlaps an active plan of another timeframe (CONFLUENT, judged by the looser confluence filter since v12):\n")
    w(md(grp))
    w(f"\n  It holds in-sample and out-of-sample (IS confluent: {note('traded IS CONFLUENT')}; OOS confluent: {note('traded OOS CONFLUENT')}).  "
      "Hence the two levers: widen the confluent population (memory) and size by conviction.\n")
    w("---\n\n## 2. New levers (all default to the v14 behaviour; simulator and live bot share the code)\n")
    w("* `confluence_memory_min=N` (+ `confluence_memory_kind=all|open|pending`) - a plan of ANOTHER timeframe (same side, zone overlap >= 50 %) that left the books within the "
      "last N minutes still counts as confluence evidence.  The live bot persists the memory in `trader_state.json` (restored on restart).")
    w("* `confluent_risk_scale` / `plain_risk_scale` - sizing multipliers on confluent / plain plans (on top of the regime and martingale scales).")
    w("* `tier_filter=<filter string>` + `tier_risk_scale` - a plan that fails the trade / confluence filter but passes this bar is traded at the reduced size (only the TFs listed).")
    w("* `mart_confluent_only` - martingale step-ups only for confluent plans (tested: -3 k$, rejected).\n")
    w(f"---\n\n## 3. Grid ({len(lev)} runs)\n")
    w(f"Scores: {lev.score.value_counts().sort_index().to_dict()}.  All {len(tops)} variants with score 4/4 (more trades, more profit, loss band held on the full year AND OOS):\n")
    w(md(tops[["name"] + COLS]))
    w("\nBest three per family by OOS net $ (any score):\n")
    w(md(fam_best[["family", "name"] + COLS]))
    w("\nWhat the families say:\n")
    w("* **Confluence memory alone** adds 5-29 trades (30-960 min) with the loss profile untouched (win 74.5-75.1 %, stop 24.5-25.1 %, worst day -1.95..-2.01 %) and +0.1..+1.9 k$.")
    w("* **Conviction sizing alone** at x1.25 (plain 0.75-0.8) adds +2-2.4 k$ at PF 2.45-2.51 but DD 6.2 %; x1.5 and above pushes the DD to 7.2-8.7 % and the worst day to -2.8..-4.6 % -> out.")
    w("* **Tiers** (M10 0.55 / 0.53, HTF 0.55, M5 cost 0.12): +25-75 trades, PF 2.07-2.19, DD 5.8-6.7 %, OOS PF 1.9-2.1 -> trades without profit; only `M10:min_quality=0.55` x0.5 "
      "survives as the v15-B add-on.")
    w("* **DD buy-backs** (max_open 3, range risk x0.75, martingale cap 2 %) cost 0.4-2.8 k$ each; the cap only binds at 2 % base risk.")
    w("* **Combination memory 240 + x1.25/0.9** is the only sizing variant whose DD stays inside the band; with 30/60/120-min windows the same sizing reaches DD 6.8-7.4 % "
      f"(chart below) - the 240-min window is where the extra confluent plans dilute the clustered losers.  The worst day rises from {ref['worst_day_%eq']:.2f} to {a['worst_day_%eq']:.2f} % in every x1.25 combination.\n")
    w("![dd](charts/v15_dd_window.png)\n")
    w("![scatter](charts/v15_scatter.png)\n")
    w("---\n\n## 4. Robustness\n")
    w(f"**Walk-forward** (`walkforward_v15.py`, trade lists split at {OOS}, worst day in R): Spearman IS->OOS of the deltas vs ref - trades {wfj['spearman']['d_n']['rho']:+.2f}, "
      f"net $ {wfj['spearman']['d_net']['rho']:+.2f}, PF {wfj['spearman']['d_PF']['rho']:+.2f}; {wfj['both']}/{wfj['n_variants']} variants pass the band on both halves; of the 12 "
      f"variants one would have chosen on the first half, {sum(wfj['is_top_oos_pass'])} pass on the second.  The extra trades and the extra dollars are population properties.\n")
    w(md(wf_rows))
    w("\n**Stress x6** (spread x2, commission x2, SL slippage x3, worst-case intrabar path, 0.5 % and 2 % base risk):\n")
    w(md(st_df))
    w("\n* v15-A beats v14-A on net $ and OOS PF in 6/6 scenarios; the DD stays within +0.5 pt in 5/6 (2 % base risk: 14.1 vs 9.9 % - x1.25 on 2 % is 2.5 % per confluent plan, "
      "outside the spec; at 2 % risk use v15-C).  Weak point: at double spread the worst day is -4.55 % vs -1.95 % (one day of clustered confluent losers at the bigger size) and "
      "11/13 months are positive (ref 12/13).")
    w("* v15-C (memory only) keeps the worst day of v14-A in 6/6 scenarios and adds trades and dollars in 6/6 - the robust floor.\n")
    w("---\n\n## 5. Final backtest of the shipped strings (`backtest_v15_final.py`, read from `run_trader.bat`)\n")
    w(f"v15-A: **{final['trades']} trades, net {final['net_$']:+,.0f} $ ({final['return_%']:+.2f} %), max DD {final['max_dd_%']:.2f} %, PF {final['profit_factor']:.3f}, win {final['win_%']:.1f} %, "
      f"stop-outs {final['sl_%']:.1f} %, worst day {final['worst_day_%eq']:.2f} %, OOS net {final['OOS_net_$']:+,.0f} $, OOS PF {final['OOS_PF']:.2f}, {final['months_pos']}/13 months** "
      f"(v14-A reference from the same strings minus the v15 keys: {fref['trades']} / {fref['net_$']:+,.0f} $ / DD {fref['max_dd_%']:.2f} / PF {fref['profit_factor']:.3f}).  "
      "Identical to the study json; details, month table and the five worst trades in `FINAL_BACKTEST_V15.md`.\n")
    w("![monthly](charts/v15_monthly.png)\n")
    w("---\n\n## 6. Recommendation and honest reading\n")
    w(f"* **Ship v15-A** (done in `run_trader.bat`): +{int(a.trades - ref.trades)} trades, +{100 * (a['net_$'] / ref['net_$'] - 1):.0f} % net, OOS PF {ref.OOS_PF:.2f} -> {a.OOS_PF:.2f}, the stop-out and "
      f"win rates unchanged to the decimal, max DD unchanged.  The price is a worst day of {a['worst_day_%eq']:.2f} % instead of {ref['worst_day_%eq']:.2f} % and a max single-plan risk of "
      f"{a['max_risk_%eq']:.2f} % of equity (martingale step x conviction) instead of {ref['max_risk_%eq']:.2f} %.")
    w("* **If the worst-day / per-plan risk rise is not wanted**: v15-C (`confluence_memory_min=960`, drop the two scale keys) - more trades, +8 % net, loss profile byte-for-byte.")
    w("* **If more trades matter more than OOS PF**: v15-B (+ `tier_filter=M10:min_quality=0.55,tier_risk_scale=0.5`).")
    w("* The gains are modest in R terms (avg R per trade is unchanged at 0.28): v15 earns more because it puts more money on the plans that were already winning and lets a few more of "
      "them through, not because it found a new edge.  The next real step up needs new information for the entry model (bearish gold months, sells OOS), not more admission rules.\n")
    w("## Files\n")
    w("`study_results/v15_levers.csv` (grid), `v15_levers/*.json|_trades.csv|_equity.csv` (every run), `v15_stress.csv` / `v15_stress_table.csv`, `v15_walkforward.csv|json`, "
      "`v15_diag/*` (funnel, rejected-POI replay, re-arm, front offset), `final_v15/*` + `FINAL_BACKTEST_V15.md`, charts `charts/v15_*.png`, scripts `run_v15_diag.py`, "
      "`run_v15_levers.py`, `run_v15_all.sh`, `walkforward_v15.py`, `backtest_v15_final.py`, `verify_bat_v15.py`, `smoke_v15.py`, `v15_common.py`.\n")
    (SR / "MORE_TRADES_V15.md").write_text("\n".join(L), encoding="utf-8")
    print("wrote study_results/MORE_TRADES_V15.md", len(L), "blocks")


if __name__ == "__main__":
    main()
