#!/usr/bin/env python3
"""v12 step 5 - report study_results/MORE_TRADES_V12.md + charts/v12_*.png from v12_funnel*.csv, v12_rank.csv, v12_stress.csv,
v12_walkforward.csv and the per-run files in study_results/v12_levers/.      python make_v12_report.py"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from scipy.stats import spearmanr  # noqa: E402

SR = Path("study_results")
RUNS = SR / "v12_levers"
CH = SR / "charts"
CH.mkdir(exist_ok=True)

REF = "ref"
CONS = "KR_htf_b1"
MID = "X_CF_m10_q0.5+KR_htf_b1"
REC = "X_CF_m10_q0.5+KR_htf_b1+F_m10_q0.57"
MORE = "X_CF_m10m15_q0.5+KR_htf_b1+F_m10_q0.57"
RE = "RE_m10m15_b1"
LABEL = {REF: "v11-B reference", CONS: "v12-C: keep replaced HTF orders 1 bar", MID: "keep 1 bar + confluence M10 0.50",
         REC: "v12-A: keep 1 bar + confluence M10 0.50 + M10 0.57", MORE: "v12-B: v12-A + confluence M15 0.50",
         RE: "re-entry M10/M15 1 bar (rejected)"}
COLS = ["trades", "return_%", "max_dd_%", "profit_factor", "win_%", "sl_%", "worst_day_%", "OOS_R", "OOS_PF", "OOS_win_%", "hold_loss", "hold_oos"]
STRESS_TAGS = ("spread_x2", "commission_x2", "slip_x3", "worst_intrabar", "risk0.5", "risk2")
OOS = "2026-03-01"


def md(df: pd.DataFrame) -> str:
    return df.to_markdown(index=False)


def load():
    funnel = pd.read_csv(SR / "v12_funnel.csv")
    reasons = pd.read_csv(SR / "v12_funnel_reasons.csv")
    extra = json.load(open(SR / "v12_funnel_extra.json"))
    rank = pd.read_csv(SR / "v12_rank.csv")
    stress = pd.read_csv(SR / "v12_stress.csv")
    wf = pd.read_csv(SR / "v12_walkforward.csv")
    runs = {n: json.load(open(RUNS / f"{n}.json")) for n in LABEL}
    return funnel, reasons, extra, rank, stress, wf, runs


def charts(rank, runs):
    ref = rank[rank.name == REF].iloc[0]
    fig, ax = plt.subplots(figsize=(11, 5))
    for n in (REF, CONS, REC, MORE):
        e = pd.read_csv(RUNS / f"{n}_equity.csv", index_col=0, parse_dates=True)
        r = runs[n]
        ax.plot(e.index, e.equity, label=f"{LABEL[n]}  ({r['trades']} trades, {r['return_%']:+.0f} %, DD {r['max_dd_%']:.1f} %)")
    ax.axvline(pd.Timestamp(OOS), color="k", ls="--", lw=0.8)
    ax.set_title("Full year Sep 2025 -> Sep 2026, $10 000, 1 % risk, real costs (dashed: entry model out-of-sample from here)")
    ax.set_ylabel("equity $"); ax.grid(alpha=.3); ax.legend(fontsize=8)
    fig.tight_layout(); fig.savefig(CH / "v12_equity.png", dpi=110); plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 6))
    fam = rank.name.str.extract(r"^(X_|CF_|RE_|KR_|F_|ref)")[0].fillna("other")
    names = {"ref": "reference", "CF_": "confluence filter", "KR_": "keep replaced", "RE_": "re-entry", "F_": "plain filter", "X_": "combinations"}
    colors = {"ref": "k", "CF_": "tab:blue", "KR_": "tab:green", "RE_": "tab:red", "F_": "tab:orange", "X_": "tab:purple"}
    for f, c in colors.items():
        v = rank[fam == f]
        ax.scatter(v.trades, v.OOS_PF, c=c, s=22 + 60 * (v["max_dd_%"] < -6.5), alpha=.7, label=names[f])
    for n, mk in ((REF, "*"), (CONS, "s"), (REC, "D"), (MORE, "^")):
        r = rank[rank.name == n].iloc[0]
        ax.scatter([r.trades], [r.OOS_PF], marker=mk, s=180, edgecolor="k", facecolor="none", lw=1.5)
        ax.annotate(LABEL[n].split(":")[0], (r.trades, r.OOS_PF), textcoords="offset points", xytext=(6, 6), fontsize=8)
    ax.axhline(ref.OOS_PF, color="k", ls=":", lw=.8); ax.axvline(ref.trades, color="k", ls=":", lw=.8)
    ax.set_xlabel("trades per year"); ax.set_ylabel("out-of-sample profit factor (Mar-Sep 2026)")
    ax.set_title(f"{len(rank)} variants: more trades vs out-of-sample edge (big marker = max DD deeper than 6.5 %)")
    ax.grid(alpha=.3); ax.legend(fontsize=8, loc="lower left")
    fig.tight_layout(); fig.savefig(CH / "v12_scatter.png", dpi=110); plt.close(fig)

    fig, ax = plt.subplots(figsize=(11, 4.5))
    mon = pd.DataFrame({LABEL[n].split(":")[0]: pd.Series(runs[n]["monthly_$"]) for n in (REF, REC, MORE)})
    mon.plot.bar(ax=ax, width=.8); ax.axhline(0, color="k", lw=.8); ax.grid(alpha=.3, axis="y")
    ax.set_title("Monthly net $ (full year)"); ax.set_ylabel("$")
    fig.tight_layout(); fig.savefig(CH / "v12_monthly.png", dpi=110); plt.close(fig)

    fig, ax = plt.subplots(figsize=(11, 3.8))
    for n in (REF, REC, MORE):
        e = pd.read_csv(RUNS / f"{n}_equity.csv", index_col=0, parse_dates=True).equity
        ax.plot(e.index, 100 * (e / e.cummax() - 1), label=LABEL[n].split(":")[0], lw=.9)
    ax.set_title("Drawdown from the equity peak (%)"); ax.grid(alpha=.3); ax.legend(fontsize=8)
    fig.tight_layout(); fig.savefig(CH / "v12_drawdown.png", dpi=110); plt.close(fig)


def extra_table(name):
    tr_ref = pd.read_csv(RUNS / f"{REF}_trades.csv", parse_dates=["entry_time", "close_time"])
    tr = pd.read_csv(RUNS / f"{name}_trades.csv", parse_dates=["entry_time", "close_time"])
    ex = tr[~tr.key.isin(tr_ref.key)].copy()
    lost = tr_ref[~tr_ref.key.isin(tr.key)]
    ex["how"] = ex.apply(lambda r: "confluence filter" if r.confluent else ("re-entry" if r.reentry else "kept order / M10 quality 0.57"), axis=1)
    t1 = ex.groupby("tf").agg(trades=("r_net", "size"), R=("r_net", "sum"), avg_R=("r_net", "mean"),
                              win_pct=("net", lambda x: 100 * (x > 0).mean()),
                              OOS_trades=("close_time", lambda x: int((x >= OOS).sum())),
                              OOS_R=("r_net", lambda x: x[ex.loc[x.index, "close_time"] >= OOS].sum())).round(2).reset_index()
    t2 = ex.groupby("how").agg(trades=("r_net", "size"), R=("r_net", "sum"), win_pct=("net", lambda x: 100 * (x > 0).mean())).round(2).reset_index()
    oos = ex[ex.close_time >= OOS]
    line = (f"{len(ex)} trades this variant takes and the reference does not ({ex.r_net.sum():+.1f} R, win {100 * (ex.net > 0).mean():.0f} %); "
            f"out-of-sample part {len(oos)} trades / {oos.r_net.sum():+.1f} R / win {100 * (oos.net > 0).mean():.0f} %; "
            f"outcomes {ex.outcome.value_counts().to_dict()}.  {len(lost)} reference trades are displaced ({lost.r_net.sum():+.1f} R).")
    return md(t1), md(t2), line, len(ex)


def main():
    funnel, reasons, extra, rank, stress, wf, runs = load()
    charts(rank, runs)
    T = {}
    fun_tf = funnel.pivot_table(index="stage", columns="tf", values="pois", aggfunc="sum").fillna(0).astype(int)[["M5", "M10", "M15", "M30", "H1"]]
    fun_tf["all"] = fun_tf.sum(axis=1)
    T["funnel"] = md(fun_tf.sort_values("all", ascending=False).reset_index())
    T["reasons"] = md(reasons.sort_values("pois", ascending=False).head(12))
    a_cols = ["name"] + COLS
    sing = rank[~rank.name.str.startswith("X_")]
    T["singles"] = md(sing.sort_values("trades", ascending=False)[a_cols])
    comb = rank[rank.name.str.startswith("X_") | (rank.name == REF)]
    T["combos_hold"] = md(comb[comb.hold_oos & (comb["max_dd_%"] >= -6.0)].sort_values("trades", ascending=False).head(20)[a_cols])
    T["combos_top"] = md(comb.sort_values("trades", ascending=False).head(10)[a_cols])
    srows = []
    for n in (REF, CONS, MID, REC, MORE, RE):
        base = rank[rank.name == n].iloc[0]
        d = {"variant": LABEL[n], "base": f"{base['return_%']:+.0f} % / {base['max_dd_%']:.1f} % / {base.OOS_PF:.2f}"}
        for tag in STRESS_TAGS:
            x = stress[(stress.name == n) & (stress.tag == tag)]
            d[tag] = f"{x.iloc[0]['return_%']:+.0f} % / {x.iloc[0]['max_dd_%']:.1f} % / {x.iloc[0].OOS_PF:.2f}" if len(x) else "n/a"
        srows.append(d)
    T["stress"] = md(pd.DataFrame(srows))
    T["extra_tf_A"], T["extra_how_A"], T["extra_line_A"], nA = extra_table(REC)
    T["extra_tf_B"], T["extra_how_B"], T["extra_line_B"], nB = extra_table(MORE)
    bytf = pd.DataFrame({"v11-B n": pd.Series(runs[REF]["by_tf_n"]), "v11-B R": pd.Series(runs[REF]["by_tf_R"]),
                         "v12-A n": pd.Series(runs[REC]["by_tf_n"]), "v12-A R": pd.Series(runs[REC]["by_tf_R"]),
                         "v12-B n": pd.Series(runs[MORE]["by_tf_n"]), "v12-B R": pd.Series(runs[MORE]["by_tf_R"])}).fillna(0)
    T["bytf"] = md(bytf.loc[["M5", "M10", "M15", "M30", "H1"]].reset_index().rename(columns={"index": "tf"}))
    T["wf_top"] = md(wf.head(12))
    T["wf_fin"] = md(wf[wf.name.isin([REF, CONS, MID, REC, MORE, RE])])
    rho, p = spearmanr(wf.IS_R, wf.OOS_R)
    rho2, p2 = spearmanr(wf.IS_PF, wf.OOS_PF)
    T["wf_line"] = f"Spearman(IS R, OOS R) = {rho:.2f} (p = {p:.0e}); Spearman(IS PF, OOS PF) = {rho2:.2f} (p = {p2:.0e}) over {len(wf)} variants."
    r0, rc, ra, rb = runs[REF], runs[CONS], runs[REC], runs[MORE]
    pct = lambda r: 100 * (r["trades"] / r0["trades"] - 1)
    tmpl = Path("make_v12_report_template.md").read_text()
    text = tmpl.format(r0=r0, rc=rc, ra=ra, rb=rb, pc=pct(rc), pa=pct(ra), pb=pct(rb), T=T, n_all=len(rank),
                       n_x=int(rank.name.str.startswith("X_").sum()), ex=extra, nA=nA, nB=nB,
                       shown=int(funnel.groupby("tf").shown.first().sum()))
    (SR / "MORE_TRADES_V12.md").write_text(text)
    print(text[:2500]); print("...\nwritten study_results/MORE_TRADES_V12.md + charts/v12_*.png")


if __name__ == "__main__":
    main()
