#!/usr/bin/env python3
"""v11 step 5 - report study_results/MORE_TRADES_STUDY.md + charts from v11_funnel*.csv, v11_levers.csv, v11_combos.csv,
v11_stress.csv and the per-run files in study_results/v11_levers/.   python make_v11_report.py"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

SR = Path("study_results")
RUNS = SR / "v11_levers"
CH = SR / "charts"
CH.mkdir(exist_ok=True)

REC = "C_m30q57+h1q57__xtf"
ALT = "B_xtf"
REF = "ref"
LABEL = {REF: "v10 reference", ALT: "v11-A: dedupe_cross_tf=false", REC: "v11-B: + M30/H1 quality 0.57",
         "C_m30q57+h1q57+m5sess__xtf": "v11-B + M5 all sessions", "C_m30q57+h1q57": "M30/H1 quality 0.57 only",
         "C_m30q57__xtf": "xtf + M30 0.57"}
COLS = ["trades", "return_%", "max_dd_%", "profit_factor", "win_%", "worst_day_%", "OOS_R", "OOS_PF", "hold_loss"]
STRESS_TAGS = ("spread_x2", "commission_x2", "slip_x3", "worst_intrabar", "risk0.5", "risk2")


def md(df: pd.DataFrame) -> str:
    return df.to_markdown(index=False)


def charts(allv, runs, funnel):
    ref = allv[allv.name == REF].iloc[0]
    fig, ax = plt.subplots(figsize=(11, 5))
    for n in (REF, ALT, REC):
        e = pd.read_csv(RUNS / f"{n}_equity.csv", index_col=0, parse_dates=True)
        r = runs[n]
        ax.plot(e.index, e.equity, label=f"{LABEL[n]}  ({r['trades']} trades, {r['return_%']:+.0f} %, DD {r['max_dd_%']:.1f} %)")
    ax.axvline(pd.Timestamp("2026-03-01"), color="k", ls="--", lw=0.8)
    ax.set_title("Full year Sep 2025 -> Sep 2026, $10 000, 1 % risk, real costs (dashed: entry model out-of-sample from here)")
    ax.set_ylabel("equity $"); ax.grid(alpha=.3); ax.legend(fontsize=8)
    fig.tight_layout(); fig.savefig(CH / "v11_equity.png", dpi=110); plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 6))
    v = allv[~allv.name.str.contains("grace|persist")]
    sc = ax.scatter(v.trades, v.OOS_PF, c=-v["max_dd_%"], cmap="RdYlGn_r", s=28, vmin=4, vmax=10)
    g = allv[allv.name.str.contains("grace|persist")]
    ax.scatter(g.trades, g.OOS_PF, marker="x", c="grey", s=28, label="grace / persist orders (rejected)")
    for n, mk in ((REF, "*"), (ALT, "s"), (REC, "D")):
        r = allv[allv.name == n].iloc[0]
        ax.scatter([r.trades], [r.OOS_PF], marker=mk, s=160, edgecolor="k", facecolor="none", lw=1.5)
        ax.annotate(LABEL[n], (r.trades, r.OOS_PF), textcoords="offset points", xytext=(6, 6), fontsize=8)
    ax.axhline(ref.OOS_PF, color="k", ls=":", lw=.8); ax.axvline(ref.trades, color="k", ls=":", lw=.8)
    plt.colorbar(sc, label="max drawdown % (full year)")
    ax.set_xlabel("trades per year"); ax.set_ylabel("out-of-sample profit factor (Mar-Sep 2026)")
    ax.set_title(f"{len(allv)} variants: more trades vs out-of-sample edge"); ax.grid(alpha=.3); ax.legend(fontsize=8, loc="lower right")
    fig.tight_layout(); fig.savefig(CH / "v11_scatter.png", dpi=110); plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 4.5))
    piv = funnel.pivot_table(index="tf", columns="stage", values="pois", aggfunc="sum").fillna(0).loc[["M5", "M10", "M15", "M30", "H1"]]
    piv.plot.barh(stacked=True, ax=ax, colormap="tab20c")
    ax.set_title("Where the scanner's POIs go (unique POIs shown, Sep 2025 -> Sep 2026, v10 reference)")
    ax.set_xlabel("POIs"); ax.legend(fontsize=7); ax.grid(alpha=.3, axis="x")
    fig.tight_layout(); fig.savefig(CH / "v11_funnel.png", dpi=110); plt.close(fig)

    fig, ax = plt.subplots(figsize=(11, 4.5))
    mon = pd.DataFrame({LABEL[n]: pd.Series(runs[n]["monthly_$"]) for n in (REF, ALT, REC)})
    mon.plot.bar(ax=ax, width=.8); ax.axhline(0, color="k", lw=.8); ax.grid(alpha=.3, axis="y")
    ax.set_title("Monthly net $ (full year)"); ax.set_ylabel("$")
    fig.tight_layout(); fig.savefig(CH / "v11_monthly.png", dpi=110); plt.close(fig)


def load():
    funnel = pd.read_csv(SR / "v11_funnel.csv")
    reasons = pd.read_csv(SR / "v11_funnel_reasons.csv")
    lev = pd.read_csv(SR / "v11_levers.csv")
    comb = pd.read_csv(SR / "v11_combos.csv")
    stress = pd.read_csv(SR / "v11_stress.csv")
    allv = pd.concat([comb, lev[~lev.name.isin(comb.name)]], ignore_index=True)
    runs = {n: json.load(open(RUNS / f"{n}.json")) for n in (REF, ALT, REC)}
    return funnel, reasons, lev, comb, stress, allv, runs


def tables(funnel, reasons, lev, comb, stress, allv, runs):
    T = {}
    fun_tf = funnel.pivot_table(index="stage", columns="tf", values="pois", aggfunc="sum").fillna(0).astype(int)
    fun_tf = fun_tf[["M5", "M10", "M15", "M30", "H1"]]
    fun_tf["all"] = fun_tf.sum(axis=1)
    T["funnel"] = md(fun_tf.sort_values("all", ascending=False).reset_index())
    T["reasons"] = md(reasons.sort_values("pois", ascending=False).head(14))
    a_cols = ["name"] + COLS
    a = lev[~lev.name.isin(["open6", "open8", "repoi"])]
    T["gridA"] = md(a.sort_values("trades", ascending=False)[a_cols])
    b = comb[comb.name.str.startswith("B_") | (comb.name == REF)].sort_values("trades")
    T["gridB"] = md(b[a_cols])
    c = comb[comb.name.str.startswith("C_") & ~comb.name.str.contains("grace") & (comb["max_dd_%"] >= -6.0)]
    T["combos"] = md(c.sort_values("OOS_R", ascending=False).head(16)[a_cols])
    srows = []
    for n in (REF, ALT, REC, "C_m30q57+h1q57"):
        base = allv[allv.name == n].iloc[0]
        d = {"variant": LABEL.get(n, n), "base": f"{base['return_%']:+.0f} % / {base['max_dd_%']:.1f} % / {base.OOS_PF:.2f}"}
        for tag in STRESS_TAGS:
            x = stress[(stress.name == n) & (stress.tag == tag)].iloc[0]
            d[tag] = f"{x['return_%']:+.0f} % / {x['max_dd_%']:.1f} % / {x.OOS_PF:.2f}"
        srows.append(d)
    T["stress"] = md(pd.DataFrame(srows))
    tr_ref = pd.read_csv(RUNS / f"{REF}_trades.csv", parse_dates=["entry_time", "close_time"])
    tr_rec = pd.read_csv(RUNS / f"{REC}_trades.csv", parse_dates=["entry_time", "close_time"])
    extra = tr_rec[~tr_rec.key.isin(tr_ref.key)]
    T["extra"] = md(extra.groupby("tf").agg(trades=("r_net", "size"), R=("r_net", "sum"), avg_R=("r_net", "mean"),
                                           win_pct=("net", lambda x: 100 * (x > 0).mean())).round(2).reset_index())
    oos = extra[extra.close_time >= "2026-03-01"]
    T["extra_line"] = (f"Out-of-sample part of the extra trades: {len(oos)} trades, {oos.r_net.sum():+.1f} R, win {100 * (oos.net > 0).mean():.0f} %.  "
                       f"Outcomes of all {len(extra)} extra trades: {extra.outcome.value_counts().to_dict()}.")
    bytf = pd.DataFrame({"v10 n": pd.Series(runs[REF]["by_tf_n"]), "v10 R": pd.Series(runs[REF]["by_tf_R"]),
                         "v11-B n": pd.Series(runs[REC]["by_tf_n"]), "v11-B R": pd.Series(runs[REC]["by_tf_R"])}).fillna(0)
    T["bytf"] = md(bytf.loc[["M5", "M10", "M15", "M30", "H1"]].reset_index().rename(columns={"index": "tf"}))
    T["n_extra"] = len(extra)
    T["shown"] = int(funnel.groupby("tf").shown.first().sum())
    T["traded"] = int(funnel[funnel.stage == "traded"].pois.sum())
    return T


def main():
    funnel, reasons, lev, comb, stress, allv, runs = load()
    charts(allv, runs, funnel)
    T = tables(funnel, reasons, lev, comb, stress, allv, runs)
    r0, alt, rec = runs[REF], runs[ALT], runs[REC]
    pct = lambda r: 100 * (r["trades"] / r0["trades"] - 1)
    tmpl = Path("make_v11_report_template.md").read_text()
    text = tmpl.format(r0=r0, alt=alt, rec=rec, alt_pct=pct(alt), rec_pct=pct(rec), T=T, n_lev=len(lev),
                       n_b=int(comb.name.str.startswith("B_").sum()), n_c=int(comb.name.str.startswith("C_").sum()),
                       n_all=len(allv), traded_pct=100 * T["traded"] / T["shown"])
    (SR / "MORE_TRADES_STUDY.md").write_text(text)
    print(text[:2500]); print("...\nwritten study_results/MORE_TRADES_STUDY.md + charts/v11_*.png")


if __name__ == "__main__":
    main()
