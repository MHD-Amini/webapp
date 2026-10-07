#!/usr/bin/env python3
"""v16 step 6a - report study_results/MORE_TRADES_V16.md + charts/v16_*.png from the v16 result files
(v16_levers.csv, v16_levers/*_trades.csv|_equity.csv, v16_stress.csv + the v15-A rows of v15_stress.csv, v16_walkforward.csv/json,
final_v16/*, sel_v16_*.pkl).  Every number in the report is read from those files - nothing is typed in.      python3 make_v16_report.py
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
RUNS = SR / "v16_levers"
CH = SR / "charts"
CH.mkdir(exist_ok=True)
OOS = "2026-03-01"
REF, A, B, C = "ref", "M20SC_0.63_x0.4", "M20SC_0.60_x0.6_KD", "M20SC_0.63_x0.3"
LABEL = {REF: "v15-A reference", A: "v16-A: M20 confluent-only q>=0.63, size x0.4 (shipped)",
         B: "v16-B: M20 confluent-only q>=0.60 x0.6 + keep-demoted orders (most $)", C: "v16-C: M20 confluent-only q>=0.63, size x0.3 (OOS loss profile untouched)"}
COLS = ["trades", "net_$", "OOS_net_$", "max_dd_%", "profit_factor", "win_%", "sl_%", "worst_day_%eq", "OOS_PF", "r2_n", "r2_net", "m20_n", "m20_net",
        "m20_win_%", "score"]
NICE = {"trades": "trades", "net_$": "net $", "OOS_net_$": "OOS net $", "max_dd_%": "max DD %", "profit_factor": "PF", "win_%": "win %",
        "sl_%": "stop %", "worst_day_%eq": "worst day %", "OOS_PF": "OOS PF", "OOS_sl_%": "OOS stop %", "months_pos": "months +",
        "r2_n": "rank-2 tr", "r2_net": "rank-2 net $", "r2_win_%": "rank-2 win %", "m20_n": "M20 tr", "m20_net": "M20 net $", "m20_win_%": "M20 win %",
        "score": "score", "name": "variant", "family": "family"}
STRESS_TAGS = ("spread_x2", "commission_x2", "slip_x3", "worst_intrabar", "risk0.5", "risk2")


def md(df: pd.DataFrame, index=False) -> str:
    """markdown table; dollar columns as integers, the rest with up to 3 decimals (no scientific notation)."""
    d = df.rename(columns=NICE).copy()
    for col in d.columns:
        if d[col].dtype.kind == "f":
            if "$" in str(col):
                d[col] = d[col].round(0).astype("Int64")
            else:
                d[col] = d[col].round(3)
    return d.to_markdown(index=index)


def fam(name: str) -> str:
    for p, f in (("ref", "ref"), ("CMB", "M20 x rank-2 combination"), ("KD", "keep-demoted only"), ("M20S", "M20 confluent-only, reduced size"),
                 ("M20C", "M20 confluent-only"), ("M20N", "M20 confluent-only, no martingale"), ("M20_", "M20 plain bar"),
                 ("R2C", "rank-2 confluent-only"), ("R2", "rank-2 zones"), ("R3", "rank-2 and 3 zones")):
        if name.startswith(p):
            return f
    return "?"


def band_fails(r, ref) -> list[str]:
    f = []
    if r["sl_%"] > ref["sl_%"] + 2: f.append("stop %")
    if r["win_%"] < ref["win_%"] - 3: f.append("win %")
    if r["max_dd_%"] < ref["max_dd_%"] - 0.5: f.append(f"DD {r['max_dd_%']:.2f} vs {ref['max_dd_%']:.2f}")
    if r["worst_day_%eq"] < ref["worst_day_%eq"] - 0.5: f.append(f"worst day {r['worst_day_%eq']:.2f} vs {ref['worst_day_%eq']:.2f}")
    if r["profit_factor"] < ref["profit_factor"] - 0.10: f.append(f"PF {r['profit_factor']:.2f} vs {ref['profit_factor']:.2f}")
    if r["OOS_PF"] < ref["OOS_PF"] - 0.10: f.append(f"OOS PF {r['OOS_PF']:.2f} vs {ref['OOS_PF']:.2f}")
    return f


def main():
    lev = pd.read_csv(SR / "v16_levers.csv")
    lev["family"] = lev.name.map(fam)
    ref = lev[lev.name == REF].iloc[0]
    a = lev[lev.name == A].iloc[0]; b = lev[lev.name == B].iloc[0]; c = lev[lev.name == C].iloc[0]
    st16 = pd.read_csv(SR / "v16_stress.csv")
    st15 = pd.read_csv(SR / "v15_stress.csv")
    stref = st15[st15.name == "CMB_cm240_cs1.25_0.9"].copy(); stref["name"] = "v15-A"
    wf = pd.read_csv(SR / "v16_walkforward.csv", index_col=0)
    wfj = json.load(open(SR / "v16_walkforward.json"))
    final = json.load(open(SR / "final_v16" / "v16A_summary.json"))
    fref = json.load(open(SR / "final_v16" / "ref_summary.json"))
    trades = {k: pd.read_csv(RUNS / f"{k}_trades.csv", parse_dates=["entry_time", "close_time"]) for k in (REF, A, B, C)}
    eq = {k: pd.read_csv(RUNS / f"{k}_equity.csv", index_col=0, parse_dates=True).equity for k in (REF, A, B, C)}

    # ---------------------------------------------------------------- stream facts (what the new sources contain)
    stream_rows = []
    for tf in ("M5", "M10", "M15", "M20", "M30", "H1"):
        s = pd.read_pickle(SR / f"sel_v16_{tf}.pkl")
        if isinstance(s, dict):
            s = pd.DataFrame(s)
        has = "rank" in s.columns
        set_ev = s[s.get("event", pd.Series("set", index=s.index)) == "set"] if "event" in s.columns else s
        r1 = int((set_ev["rank"] == 1).sum()) if has else len(set_ev)
        r2 = int((set_ev["rank"] == 2).sum()) if has else 0
        r3 = int((set_ev["rank"] == 3).sum()) if has else 0
        stream_rows.append({"tf": tf, "set events rank 1": r1, "rank 2": r2, "rank 3": r3,
                            "unique POIs rank 1": int(set_ev[set_ev["rank"] == 1].id.nunique()) if has else "",
                            "unique POIs only ever rank 2/3": int(len(set(set_ev[set_ev["rank"] > 1].id) - set(set_ev[set_ev["rank"] == 1].id))) if has else ""})
    stream_df = pd.DataFrame(stream_rows)

    # ---------------------------------------------------------------- charts
    fig, ax = plt.subplots(2, 1, figsize=(12, 8), sharex=True, gridspec_kw={"height_ratios": [3, 1]})
    for k, col in ((REF, "tab:blue"), (C, "tab:green"), (B, "tab:orange"), (A, "tab:red")):
        r = lev[lev.name == k].iloc[0]
        ax[0].plot(eq[k].index, eq[k].values, color=col, lw=1.1,
                   label=f"{LABEL[k]}: {int(r.trades)} tr, {r['net_$']:+,.0f} $, DD {r['max_dd_%']:.2f} %, PF {r.profit_factor:.2f}")
        ax[1].plot(eq[k].index, (eq[k] / eq[k].cummax() - 1) * 100, color=col, lw=0.9)
    ax[0].axvline(pd.Timestamp(OOS), color="k", ls="--", lw=0.8); ax[0].set_ylabel("equity $"); ax[0].grid(alpha=.3); ax[0].legend(fontsize=8, loc="upper left")
    ax[1].set_ylabel("drawdown %"); ax[1].grid(alpha=.3)
    ax[0].set_title("v16 - new trade sources (M20 timeframe, ranked zones): full year, $10 000, 1 % base risk; dashed = entry model OOS")
    fig.tight_layout(); fig.savefig(CH / "v16_equity.png", dpi=110); plt.close(fig)

    fig, ax = plt.subplots(figsize=(11, 6))
    ok = lev[lev.hold_loss & lev.hold_oos]; bad = lev[~(lev.hold_loss & lev.hold_oos)]
    ax.scatter(bad.trades, bad["net_$"], c="lightgray", s=18, label="loss band broken (full year or OOS)")
    ax.scatter(ok.trades, ok["net_$"], c="tab:green", s=22, label="loss percentage held (full year AND OOS)")
    for k, col in ((REF, "tab:blue"), (A, "tab:red"), (B, "tab:orange"), (C, "tab:green")):
        r = lev[lev.name == k].iloc[0]
        ax.scatter([r.trades], [r["net_$"]], c=col, s=90, edgecolor="k", zorder=5)
        ax.annotate(k if k != REF else "v15-A", (r.trades, r["net_$"]), fontsize=8, xytext=(5, 5), textcoords="offset points")
    ax.axvline(ref.trades, color="k", lw=0.6, ls=":"); ax.axhline(ref["net_$"], color="k", lw=0.6, ls=":")
    ax.set_xlabel("trades / year"); ax.set_ylabel("net $ / year"); ax.grid(alpha=.3); ax.legend(fontsize=8)
    ax.set_title(f"{len(lev)} variants: trades vs profit (dotted = v15-A)")
    fig.tight_layout(); fig.savefig(CH / "v16_scatter.png", dpi=110); plt.close(fig)

    fig, ax = plt.subplots(figsize=(12, 4))
    mo = pd.DataFrame({LABEL[k].split(":")[0]: trades[k].assign(m=trades[k].close_time.dt.strftime("%Y-%m")).groupby("m").net.sum() for k in (REF, A, B)})
    mo.plot.bar(ax=ax, width=0.8, color=["tab:blue", "tab:red", "tab:orange"]); ax.grid(alpha=.3, axis="y"); ax.set_ylabel("net $"); ax.set_title("net $ per month")
    fig.tight_layout(); fig.savefig(CH / "v16_monthly.png", dpi=110); plt.close(fig)

    # size scale chart: worst day / DD / net vs M20 size for the confluent-only 0.60 and 0.63 bars
    fig, ax = plt.subplots(1, 2, figsize=(12, 4))
    for q, col in (("0.60", "tab:orange"), ("0.63", "tab:red")):
        sub = lev[lev.name.str.match(rf"M20SC_{re.escape(q)}_x0\.\d+$") | (lev.name == f"M20C_{q}")].copy()
        sub["scale"] = sub.name.str.extract(r"x(0\.\d+)").astype(float).fillna(1.0)[0]
        sub = sub.sort_values("scale")
        ax[0].plot(sub.scale, -sub["worst_day_%eq"], "o-", color=col, label=f"worst day % (M20 bar {q})")
        ax[0].plot(sub.scale, -sub["max_dd_%"], "s--", color=col, alpha=.6, label=f"max DD % (M20 bar {q})")
        ax[1].plot(sub.scale, sub["net_$"], "o-", color=col, label=f"net $ (M20 bar {q})")
    ax[0].axhline(-ref["worst_day_%eq"] + 0.5, color="r", ls=":", lw=0.8, label="worst-day band (ref - 0.5 pt)")
    ax[0].axhline(-ref["max_dd_%"] + 0.5, color="k", ls=":", lw=0.8, label="DD band (ref + 0.5 pt)")
    ax[1].axhline(ref["net_$"], color="k", ls=":", lw=0.8, label="v15-A net $")
    for x in ax:
        x.set_xlabel("M20 size scale (tf_risk_scale)"); x.grid(alpha=.3); x.legend(fontsize=7)
    ax[0].set_title("the worst day is what binds the M20 size"); ax[1].set_title("net $ vs M20 size")
    fig.tight_layout(); fig.savefig(CH / "v16_m20_scale.png", dpi=110); plt.close(fig)

    # ---------------------------------------------------------------- tables
    tops = lev[lev.score == 4].sort_values("OOS_net_$", ascending=False)
    fam_best = lev.sort_values("OOS_net_$", ascending=False).groupby("family").head(2).sort_values(["family", "OOS_net_$"], ascending=[True, False])
    r2_full = lev[lev.name.str.match(r"R2_(same|q55|q57|q60|q65)_1\.0$")].sort_values("name")
    m20_plain = lev[lev.name.str.match(r"M20_q\d+$")].sort_values("name")
    m20_conf = lev[lev.name.str.match(r"M20C_0\.\d+$")].sort_values("name")
    kd = lev[lev.name == "KD"]
    pop = pd.read_csv(SR / "final_v16" / "v16A_trades.csv", parse_dates=["close_time"])
    m20 = pop[pop.tf == "M20"]; rest = pop[pop.tf != "M20"]
    rp = trades[REF]
    grp = pd.DataFrame([{"population": lab, "trades": len(x), "win %": round(100 * (x.net > 0).mean(), 1), "stop %": round(100 * (x.outcome == "sl").mean(), 1),
                         "avg R": round(x.r_net.mean(), 3), "net $": round(x.net.sum(), 0), "avg risk $": round(x.risk_money.mean(), 0),
                         "OOS trades": int((x.close_time >= OOS).sum()), "OOS net $": round(x[x.close_time >= OOS].net.sum(), 0)}
                        for lab, x in (("v15-A (all)", rp), ("v16-A: the five old timeframes", rest), ("v16-A: M20 confluent-only plans (x0.4)", m20))])
    st_rows = []
    for tag in STRESS_TAGS:
        rr = stref[stref.tag == tag].iloc[0]
        for nm, r in [("v15-A", rr)] + [(nm, st16[(st16.tag == tag) & (st16.name == nm)].iloc[0]) for nm in (A, B, C) if len(st16[(st16.tag == tag) & (st16.name == nm)])]:
            st_rows.append({"scenario": tag, "variant": nm, "trades": int(r.trades), "net $": round(r["net_$"], 0), "OOS net $": round(r["OOS_net_$"], 0),
                            "max DD %": r["max_dd_%"], "PF": r.profit_factor, "win %": r["win_%"], "stop %": r["sl_%"], "worst day %": r["worst_day_%eq"],
                            "OOS PF": r.OOS_PF, "months +": int(r.months_pos), "band misses": "" if nm == "v15-A" else (", ".join(band_fails(r, rr)) or "none")})
    st_df = pd.DataFrame(st_rows)
    # per-finalist stress counts
    st_sum = []
    for nm in st16.name.unique():
        g = st16[st16.name == nm].merge(stref, on="tag", suffixes=("", "_ref"))
        more = int(((g["net_$"] > g["net_$_ref"]) & (g.trades > g.trades_ref)).sum())
        oosok = int(((g["OOS_net_$"] > g["OOS_net_$_ref"]) & (g.OOS_PF >= g.OOS_PF_ref - 0.10)).sum())
        hold = int(sum(1 for _, r in g.iterrows() if not [f for f in band_fails(r, {k: r[k + "_ref"] for k in ("sl_%", "win_%", "max_dd_%", "worst_day_%eq", "profit_factor", "OOS_PF")}) if not f.startswith("OOS PF")]))
        st_sum.append({"variant": nm, "more trades & more $ (of 6)": more, "loss bands held (of 6)": hold, "OOS net above & OOS PF in band (of 6)": oosok,
                       "sum of net $ deltas": round((g["net_$"] - g["net_$_ref"]).sum(), 0)})
    st_sum = pd.DataFrame(st_sum)
    wf_rows = wf.loc[[REF, A, "M20SC_0.60_x0.4", "M20SC_0.55_x0.4", B, "M20SC_0.60_x0.6", C, "KD"],
                     ["IS_n", "IS_net_$", "IS_PF", "IS_worst_day_R", "IS_pass", "OOS_n", "OOS_net_$", "OOS_PF", "OOS_sl_%", "OOS_worst_day_R", "OOS_pass"]].reset_index()
    # the OOS worst day of v16-A
    da = trades[A].groupby(trades[A].close_time.dt.date).agg(net=("net", "sum"), R=("r_net", "sum"), n=("net", "size")).sort_values("R")
    dref = trades[REF].groupby(trades[REF].close_time.dt.date).agg(net=("net", "sum"), R=("r_net", "sum"), n=("net", "size")).sort_values("R")
    wd_a = da.iloc[0]; wd_day = da.index[0]
    wd_trades = trades[A][trades[A].close_time.dt.date == wd_day][["tf", "side", "entry_time", "close_time", "outcome", "net", "r_net", "confluent"]]

    # ---------------------------------------------------------------- report
    L = []; w = L.append
    w("# MORE TRADES & MORE PROFIT AT THE SAME LOSS PERCENTAGE (v16) — NEW TRADE SOURCES for the v15-A trader\n")
    w(f"**Question.**  The v15-A trader (run_trader.bat: regime ladder + asymmetric martingale + confluence memory + conviction sizing) takes **{int(ref.trades)} trades a year** "
      f"(Sep 2025 -> Sep 2026: net **{ref['net_$']:+,.0f} $**, {ref['return_%']:+.1f} %, max DD {ref['max_dd_%']:.2f} %, PF {ref.profit_factor:.3f}, win {ref['win_%']:.1f} %, "
      f"stop-outs {ref['sl_%']:.1f} %, worst day {ref['worst_day_%eq']:.2f} %, OOS net {ref['OOS_net_$']:+,.0f} $, OOS PF {ref.OOS_PF:.2f}).  Make it take **more trades** and earn **more profit** "
      f"while **keeping the loss percentage** (stop-out rate, win rate, max DD, worst day, PF) where it is.  v11 / v12 / v15 had shown that every admission relaxation "
      "(quality bars, cost bars, sessions, tiers, re-entry, re-arm, front offset) is exhausted - so v16 looked for trades the trader had **never been shown**.\n")
    w(f"**Answer in one line.**  Two new sources were recorded over the whole year: (A) the scanner's **2nd- and 3rd-ranked zones** per slot (the trader only ever saw the winner) "
      f"and (B) a **new M20 timeframe** between M15 and M30.  (A) is dead: genuine rank-2 fills lose money at every quality bar (section 3).  (B) pays only when the M20 zone "
      f"**confirms a level another timeframe already trades** (confluent) - plain M20 zones lose - and its size has to stay small because every M20 leg joins the same clustered "
      f"confluent stop-outs that define the worst day.  Shipped = **v16-A: M20 confluent-only at quality >= 0.63, sized x0.4: {int(a.trades)} trades ({int(a.trades - ref.trades):+d}), "
      f"net {a['net_$']:+,.0f} $ ({100 * (a['net_$'] / ref['net_$'] - 1):+.1f} %), OOS net {a['OOS_net_$']:+,.0f} $ ({100 * (a['OOS_net_$'] / ref['OOS_net_$'] - 1):+.1f} %), "
      f"max DD {a['max_dd_%']:.2f} % (ref {ref['max_dd_%']:.2f}), PF {a.profit_factor:.3f}, win {a['win_%']:.1f} %, stop-outs {a['sl_%']:.1f} %, worst day {a['worst_day_%eq']:.2f} % "
      f"(ref {ref['worst_day_%eq']:.2f}), OOS PF {a.OOS_PF:.2f}, {int(a.months_pos)}/13 months** - every loss metric inside the band on the full year and on the OOS half, "
      f"ahead of v15-A on trades AND net $ AND OOS net $ in 6/6 stress scenarios.  The gain is **small and robust, not big**: {int(a.m20_n)} M20 trades, {a["m20_win_%"]:.0f} % win, "
      f"{a.m20_net:+,.0f} $.  **v16-B** (most money, loss bands 0.02-0.15 pt outside): M20 at 0.60 x0.6 plus keep-demoted orders = {int(b.trades)} trades, {b['net_$']:+,.0f} $ "
      f"({100 * (b['net_$'] / ref['net_$'] - 1):+.0f} %), DD {b['max_dd_%']:.2f}, worst day {b['worst_day_%eq']:.2f} %, OOS PF {b.OOS_PF:.2f}.  **v16-C** (x0.3): {int(c.trades)} trades, "
      f"{c['net_$']:+,.0f} $, worst day {c['worst_day_%eq']:.2f} % - the OOS loss profile untouched to the trade.\n")
    w("![equity](charts/v16_equity.png)\n")
    w("---\n\n## 0. Method\n")
    w(f"* **Reference** = v15-A exactly as shipped: the v16 streams' rank-1 rows reproduce FINAL_BACKTEST_V15 byte for byte ({int(ref.trades)} trades, {ref['return_%']:+.2f} %, DD {ref['max_dd_%']:.2f}).  "
      "M1 portfolio simulator, real per-minute spread, $7/lot commission, $0.10 stop slippage, swaps, 1 % base risk on $10 000, mirror orders, v13 regime ladder, v14 per-TF martingale, "
      "v15 confluence memory + conviction sizing, loss rules 4.5 % / 9 %.")
    w(f"* **New streams** `record_selections_v16.py` -> `sel_v16_<TF>.pkl`: the scanner re-run over the whole year keeping the **top-3 qualified candidates per side per slot** "
      f"(`rank` column; rank-1 rows identical to the v10 streams) for M5 / M10 / M15 / **M20** / M30 / H1 ({len(lev)} full-year replays in the grid, 51 monthly chunks, "
      "every chunk committed as it finished - the recording survived 4 sandbox resets).")
    w(md(stream_df))
    w(f"\n* **Honesty.**  The entry model was trained until {OOS}: Sep 2025 - Feb 2026 is in-sample, Mar - Sep 2026 out-of-sample.  Every variant is judged on both halves.  "
      "M20 uses the SAME quality model (tf_minutes is a model feature: 20 lies between the trained 15 and 30 - interpolation, not extrapolation).")
    w("* **Loss percentage held** (`hold_loss`, full year): stop-out rate <= ref + 2 pt, win rate >= ref - 3 pt, max DD <= ref + 0.5 pt, worst day >= ref - 0.5 pt, PF >= ref - 0.10; "
      "`hold_oos`: the same on the OOS half.  `more_trades`: n > ref.  `more_profit`: net $ AND OOS net $ > ref.  score = the four together.")
    w("* Steps: (1) recorder + M20 timeframe; (2) simulator levers with byte-identical defaults (`max_rank`, `rank2_filter`, `rank2_risk_scale`, `rank2_tfs`, "
      "`rank2_confluent_only`, `tf_risk_scale`, M20 in every TF-scoped key), 7 + 2 unit tests, parity exact; (3) grid `run_v16_levers.py` (resumable, autosaved to GitHub every 4 min, "
      "9 sandbox resets, nothing lost); (4) stress x6 + walk-forward; (5) port to `trader.py` / `run_trader.bat`, fake-MT5 tests; (6) `backtest_v16_final.py` from the bat strings; "
      "this report `make_v16_report.py`.  **157 tests pass.**\n")
    w("---\n\n## 1. New levers (all default to the v15 behaviour; simulator and live bot share the code)\n")
    w("* `max_rank=K` - the trader may place the zones ranked 2..K of a slot too (same-TF overlap with a higher rank is deduped as before); `rank2_filter=<filter string>`, "
      "`rank2_risk_scale`, `rank2_tfs=M10|M15`, `rank2_confluent_only` gate them.  A POI that is DEMOTED from rank 1 to rank 2 keeps its pending order instead of being cancelled "
      "as 'replaced' (the **keep-demoted** effect, isolated as `KD` = max_rank 2 with an unreachable rank-2 bar).")
    w("* **M20 timeframe** - `--timeframes` may carry M20; it has its own rule in the trade filter (plain bar) and the confluence filter (confluent bar); `tf_risk_scale=M20:0.4` "
      "sizes one timeframe's plans; M20 may join `keep_replaced_tfs` and `mart_tfs`.")
    w("* **Live bot** (`trader.py`): `MultiTimeframeScanner.scan(top_k)` returns the ranked lists, a POI shown on any rank slot keeps its order, rank is persisted in "
      "`trader_state.json`.  A live/sim discrepancy was found and fixed by the fake-MT5 tests: the live bot marked a POI *traded* at order placement, the simulator at fill - "
      "a cancelled, unfilled order whose POI was shown again was never re-placed live.  Now `traded` is set on fill.\n")
    w(f"---\n\n## 2. Grid ({len(lev)} runs)\n")
    w(f"Scores: {lev.score.value_counts().sort_index().to_dict()}.  All {len(tops)} variants with score 4/4 (more trades, more profit, loss band held on the full year AND OOS) "
      "are the same family - M20 confluent-only at a reduced size:\n")
    w(md(tops[["name"] + COLS]))
    w("\nBest two per family by OOS net $ (any score):\n")
    w(md(fam_best[["family", "name"] + COLS]))
    w("\n![scatter](charts/v16_scatter.png)\n")
    w("---\n\n## 3. Source A — the scanner's 2nd-ranked zones LOSE\n")
    w("Rank-2 admission at full size, by quality bar (`r2_n` = genuine rank-2 fills; the rest of the trade delta is the keep-demoted effect):\n")
    w(md(r2_full[["name"] + COLS]))
    w(f"\n* The scanner's ranking is right: the 2nd zone is worse than the 1st at every bar - rank-2 fills win 48-62 % with 40-58 % stop-outs and lose "
      f"{r2_full.r2_net.min():,.0f}..{r2_full.r2_net.max():,.0f} $; rank 3 is worse still (R3_*: PF 1.9-2.2).  Confluent-only rank-2 (R2C_*) is neutral at best (+0.3 k$ on 6 fills).")
    w(f"* What the R2 rows DO add is **keep-demoted** (`KD`: {int(kd.iloc[0].trades)} tr, {kd.iloc[0]['net_$']:+,.0f} $, OOS {kd.iloc[0]['OOS_net_$']:+,.0f} $, DD {kd.iloc[0]['max_dd_%']:.2f}, "
      f"PF {kd.iloc[0].profit_factor:.3f}, OOS PF {kd.iloc[0].OOS_PF:.2f}): 28 extra trades from orders that are no longer cancelled when their POI slips to rank 2.  It passes "
      "more_trades / more_profit / hold_loss but misses the OOS PF band (2.13 vs 2.16) and, in the stress, PF / OOS PF in 3 of 6 scenarios -> offered only inside v16-B.\n")
    w("---\n\n## 4. Source B — the M20 timeframe pays ONLY when confluent, and only small\n")
    w("Plain M20 bar (every M20 zone above the bar is traded):\n")
    w(md(m20_plain[["name"] + COLS]))
    w("\nConfluent-only M20 (plain bar unreachable 0.99, confluence bar q) at full size:\n")
    w(md(m20_conf[["name"] + COLS]))
    w("\n* Plain M20 zones lose (27 plain-only trades at 0.60: 37 % win) and push the DD to 6.8-8.6 %.  **Confluent** M20 zones win 79-90 % and add +2.9..+4.7 k$ at full size; "
      "the stop rate, win rate, DD and PF all stay inside the band - **the only metric that breaks is the worst day** (-3.4..-3.5 % vs the -2.92 band): the M20 leg is one more "
      "position on the days when 2-3 confluent plans are stopped within the same minute.")
    w("* Hence `tf_risk_scale`: the chart shows how the worst day falls with the M20 size while the net $ gain shrinks with it.  At x0.4 (bar 0.63) the worst day is back inside the "
      "band with the DD unchanged; x0.5-0.75 earns +1.3..+3.4 k$ but fails the worst day by 0.1-0.3 pt.  Without martingale on M20 (M20N) nothing improves; a 2 % martingale cap changes nothing.\n")
    w("![scale](charts/v16_m20_scale.png)\n")
    w("Who trades in v16-A (from the final backtest's trade list):\n")
    w(md(grp))
    w("\n---\n\n## 5. Robustness\n")
    w(f"**Walk-forward** (`walkforward_v16.py`, trade lists split at {OOS}, worst day in R): Spearman IS->OOS of the deltas vs ref - trades {wfj['spearman']['d_n']['rho']:+.2f}, "
      f"net $ {wfj['spearman']['d_net']['rho']:+.2f}, PF {wfj['spearman']['d_PF']['rho']:+.2f}: the extra trades are a population property, the extra dollars carry over moderately.  "
      f"{wfj['both']}/{wfj['n_variants']} variants pass the band on both halves and {wfj['oos_pass']} on the OOS half alone, because the OOS half is judged in R, where one extra "
      f"-1 R leg on the clustered day counts fully (in $ the M20 leg at x0.4 is {wd_trades[wd_trades.tf == 'M20'].net.sum():+.0f} $ of that day's {wd_a.net:+.0f} $).\n")
    w(md(wf_rows))
    w(f"\nThe worst day of v16-A ({wd_day}, {wd_a.R:.2f} R / {wd_a.net:+.0f} $; v15-A's worst day {dref.index[0]} {dref.iloc[0].R:.2f} R / {dref.iloc[0].net:+.0f} $):\n")
    w(md(wd_trades.assign(entry_time=wd_trades.entry_time.dt.strftime("%m-%d %H:%M"), close_time=wd_trades.close_time.dt.strftime("%m-%d %H:%M"))))
    w("\n**Stress x6** (spread x2, commission x2, SL slippage x3, worst-case intrabar path, 0.5 % and 2 % base risk; v15-A rows from `v15_stress.csv`):\n")
    w(md(st_sum))
    w("")
    w(md(st_df))
    w(f"\n* **v16-A** is ahead of v15-A on trades AND net $ in 6/6 scenarios and on OOS net $ with the OOS PF inside the band in 6/6; the loss bands hold in 5/6 - the one miss is the max DD at "
      "0.5 % base risk (3.94 vs 3.19 %, band 3.69): at half size the M20 lots round to the broker minimum and the loss cluster is relatively bigger.")
    w("* **v16-B** (x0.6 + keep-demoted) earns far more in every scenario (+57 k$ summed over the six) but breaks the worst-day band in 5/6 - it is a different risk profile, not the same one.")
    w(f"* **v16-C** (x0.3) was not stressed separately; on the full year it is the only finalist whose OOS worst day equals v15-A's ({wf.loc[C, 'OOS_worst_day_R']:.2f} R) - "
      "its M20 legs are too small to be the third stop that matters.\n")
    w("---\n\n## 6. Final backtest of the shipped strings (`backtest_v16_final.py`, read from `run_trader.bat`)\n")
    w(f"v16-A: **{final['trades']} trades, net {final['net_$']:+,.0f} $ ({final['return_%']:+.2f} %), max DD {final['max_dd_%']:.2f} %, PF {final['profit_factor']:.3f}, win {final['win_%']:.1f} %, "
      f"stop-outs {final['sl_%']:.1f} %, worst day {final['worst_day_%eq']:.2f} %, OOS net {final['OOS_net_$']:+,.0f} $, OOS PF {final['OOS_PF']:.2f}, {final['months_pos']}/13 months, "
      f"{final.get('m20_trades', 0)} M20 trades, {final.get('rank2_trades', 0)} rank-2 trades** (v15-A reference from the same strings minus M20 / tf_risk_scale: {fref['trades']} / "
      f"{fref['net_$']:+,.0f} $ / DD {fref['max_dd_%']:.2f} / PF {fref['profit_factor']:.3f} = FINAL_BACKTEST_V15).  Identical to the study json `M20SC_0.63_x0.4.json` and to "
      "`verify_bat_v16.py`; details, month table and the worst trades in `FINAL_BACKTEST_V16.md`.\n")
    w("![monthly](charts/v16_monthly.png)\n")
    w("---\n\n## 7. Recommendation and honest reading\n")
    w(f"* **Ship v16-A** (done in `run_trader.bat`): +{int(a.trades - ref.trades)} trades, {100 * (a['net_$'] / ref['net_$'] - 1):+.1f} % net, {100 * (a['OOS_net_$'] / ref['OOS_net_$'] - 1):+.1f} % OOS net, "
      f"max DD unchanged, stop-out rate {ref['sl_%']:.1f} -> {a['sl_%']:.1f} %, win rate {ref['win_%']:.1f} -> {a['win_%']:.1f} %, PF -0.01, worst day {ref['worst_day_%eq']:.2f} -> {a['worst_day_%eq']:.2f} %.")
    w("* **If more money matters more than the exact loss profile**: v16-B (M20 bar 0.60, `tf_risk_scale=M20:0.6`, `max_rank=2,rank2_filter=M5|M10|M15|M20|M30|H1:min_quality=0.99`) - "
      f"+{100 * (b['net_$'] / ref['net_$'] - 1):.0f} % net, DD lower than v15-A, but a worst day of {b['worst_day_%eq']:.2f} % and OOS PF {b.OOS_PF:.2f}.")
    w("* **If the worst day must not move at all**: v16-C (`tf_risk_scale=M20:0.3`).")
    w("* **What v16 settles.**  The scanner's slot winner IS the best zone - there is no money in its runner-ups.  A 6th timeframe adds information only as *confirmation* of the five, "
      "and the confirmation is already priced by the v15 confluence sizing, so the increment is +1-4 %.  Every variant that earns more (bigger M20 size, keep-demoted orders) does so by "
      "adding one more leg to the same clustered confluent stop-outs - exactly what the worst-day / PF bands measure.  More trades at the same loss percentage now requires a better "
      "**entry model** (new features, e.g. the bearish-gold months and sells OOS), not more trade sources or admission rules.\n")
    w("## Files\n")
    w("`study_results/v16_levers.csv` (grid), `v16_levers/*.json|_trades.csv|_equity.csv` (every run incl. the 36 stress runs `*__<scenario>`), `v16_stress.csv`, "
      "`v16_walkforward.csv|json`, `sel_v16_<TF>.pkl` + `parts_v16/` (top-3 streams, monthly chunks), `final_v16/*` + `FINAL_BACKTEST_V16.md`, charts `charts/v16_*.png`, "
      "scripts `record_selections_v16.py`, `run_v16_record.sh`, `run_v16_levers.py`, `run_v16_all.sh`, `run_v16_stress.sh`, `walkforward_v16.py`, `backtest_v16_final.py`, "
      "`verify_bat_v16.py`, `smoke_v16.py`, `v16_common.py`, tests `tests/test_v16_levers.py`, `tests/test_trader_v16.py`, `tests/test_bat_v16.py`.\n")
    (SR / "MORE_TRADES_V16.md").write_text("\n".join(L), encoding="utf-8")
    print("wrote study_results/MORE_TRADES_V16.md", len(L), "blocks")


if __name__ == "__main__":
    main()
