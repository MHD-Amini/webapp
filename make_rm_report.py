#!/usr/bin/env python3
"""v9 step 5 - tables + charts for the risk-management study (everything computed from the result files).

Inputs : study_results/rm_study_grid.csv, rm_study/*_trades.csv|_equity.csv, rm_insample.csv, rm_insample/*_trades.csv, rm_stress.csv
Outputs: study_results/rm_is_vs_oos.csv, rm_summary_table.csv, rm_family_summary.csv, rm_mfe_survival.csv,
         study_results/charts/rm_*.png, and prints the markdown tables used in RISK_MGMT_STUDY.md.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy.stats import spearmanr  # noqa: E402

SR = Path("study_results")
CH = SR / "charts"
CH.mkdir(exist_ok=True)
pd.set_option("display.width", 250)


def md(df: pd.DataFrame, floatfmt=".3f") -> str:
    return df.to_markdown(index=False, floatfmt=floatfmt)


def main():
    oos = pd.read_csv(SR / "rm_study_grid.csv")
    oos["family"] = oos.name.str.split("_").str[0]
    ins = pd.read_csv(SR / "rm_insample.csv") if (SR / "rm_insample.csv").exists() else None
    stress = pd.read_csv(SR / "rm_stress.csv") if (SR / "rm_stress.csv").exists() else None
    base = oos[oos.name == "base_v8"].iloc[0]

    # ---------------------------------------------------------------- 1. family summary (OOS)
    fam = oos.groupby("family").agg(n=("name", "size"), best_ret=("return_%", "max"), median_ret=("return_%", "median"),
                                    worst_ret=("return_%", "min"), best_ret_dd=("ret_dd", "max"),
                                    median_dd=("max_dd_%", "median")).reset_index()
    fam.to_csv(SR / "rm_family_summary.csv", index=False)
    print("\n### OOS by family\n" + md(fam, ".1f"))

    # ---------------------------------------------------------------- 2. IS vs OOS
    if ins is not None:
        m = ins.merge(oos, on="name", suffixes=("_is", "_oos"))
        rho, p = spearmanr(m["avg_R_is"], m["avg_R_oos"])
        rho_dd, _ = spearmanr(m["avg_R_is"], m["ret_dd"])
        m["rank_is"] = m.avg_R_is.rank(ascending=False)
        m["rank_oos_retdd"] = m.ret_dd.rank(ascending=False)
        m["rank_sum"] = m.rank_is + m.rank_oos_retdd
        m = m.sort_values("rank_sum")
        m.to_csv(SR / "rm_is_vs_oos.csv", index=False)
        print(f"\nSpearman(avg_R in-sample, avg_R OOS) = {rho:.2f} (p={p:.3g}, n={len(m)});  vs OOS return/DD = {rho_dd:.2f}")
        cols = ["name", "return_%", "max_dd_%", "profit_factor", "avg_R_oos", "win_%_oos", "H1_R", "H2_R", "months_pos_oos",
                "avg_R_is", "PF", "win_%_is", "max_dd_R_is", "months_pos_is", "rank_sum"]
        print("\n### best rank-sum (in-sample avg R + OOS return/DD)\n" + md(m[cols].head(15), ".3f"))
        fig, ax = plt.subplots(figsize=(8, 6))
        for f, g in m.groupby(m.name.str.split("_").str[0]):
            ax.scatter(g.avg_R_is, g.avg_R_oos, label=f, s=28, alpha=.8)
        b = m[m.name == "base_v8"]
        if len(b):
            ax.scatter(b.avg_R_is, b.avg_R_oos, marker="*", s=260, c="k", label="current spec")
        top = m.head(3)
        for r in top.itertuples():
            ax.annotate(r.name, (r.avg_R_is, r.avg_R_oos), fontsize=7, xytext=(4, 4), textcoords="offset points")
        ax.set_xlabel("in-sample avg R / plan (Jan 2025 - Feb 2026)"); ax.set_ylabel("OOS avg R / trade (Mar - Sep 2026)")
        ax.set_title(f"management systems: in-sample vs out-of-sample  (Spearman {rho:.2f})"); ax.grid(alpha=.3); ax.legend(fontsize=7)
        fig.tight_layout(); fig.savefig(CH / "rm_is_vs_oos.png", dpi=110); plt.close(fig)

    # ---------------------------------------------------------------- 3. heat map partial level x TP2 (family A, BE on)
    A = oos[(oos.family == "A") & ~oos.name.str.endswith("noBE")].copy()
    A["pr"] = A.name.str.extract(r"_p([\d.]+)_").astype(float)
    A["pf"] = A.name.str.extract(r"_f([\d.]+)_").astype(float)
    A["tp"] = A.name.str.extract(r"_tp([\d.]+)$").astype(float)
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.2))
    for ax, frac in zip(axes, (0.25, 0.5, 0.75)):
        pv = A[A.pf == frac].pivot(index="pr", columns="tp", values="return_%")
        im = ax.imshow(pv.values, cmap="RdYlGn", vmin=-5, vmax=max(35, np.nanmax(A["return_%"])), aspect="auto")
        ax.set_xticks(range(len(pv.columns))); ax.set_xticklabels(pv.columns); ax.set_yticks(range(len(pv.index))); ax.set_yticklabels(pv.index)
        for i in range(pv.shape[0]):
            for j in range(pv.shape[1]):
                v = pv.values[i, j]
                if not np.isnan(v):
                    ax.text(j, i, f"{v:+.0f}", ha="center", va="center", fontsize=8)
        ax.set_xlabel("TP2 (R)"); ax.set_ylabel("partial level (R)"); ax.set_title(f"OOS return %, partial fraction {int(frac*100)} %, BE on")
    fig.colorbar(im, ax=axes, shrink=.8); fig.savefig(CH / "rm_heat_partial_tp.png", dpi=110); plt.close(fig)
    if ins is not None:
        Ai = ins[ins.name.str.startswith("A_") & ~ins.name.str.endswith("noBE")].copy()
        if len(Ai) >= 6:
            Ai["pr"] = Ai.name.str.extract(r"_p([\d.]+)_").astype(float)
            Ai["pf"] = Ai.name.str.extract(r"_f([\d.]+)_").astype(float)
            Ai["tp"] = Ai.name.str.extract(r"_tp([\d.]+)$").astype(float)
            print("\n### in-sample avg R by partial level x TP2 (all fractions replayed)\n" +
                  Ai.pivot_table(index=["pr", "pf"], columns="tp", values="avg_R").round(3).to_markdown())

    # ---------------------------------------------------------------- 4. MFE survival (how far do fills run?)
    def survival(trades_csv: Path, cap: float) -> pd.Series:
        t = pd.read_csv(trades_csv)
        lv = [0.2, 0.4, 0.6, 0.8, 1.0, 1.5, 2.0, 2.5, 3.0]
        return pd.Series({l: 100 * (t.mfe_r >= l - 1e-9).mean() for l in lv if l <= cap + 1e-9}, name=trades_csv.stem)
    surv = {}
    # the variants with the furthest target (TP 3R, no partial) give an uncapped MFE up to 3R
    for lab, f in (("OOS (B_tp3.0)", SR / "rm_study" / "B_tp3.0_trades.csv"),
                   ("IS (B_tp3.0)", SR / "rm_insample" / "B_tp3.0_trades.csv")):
        if f.exists():
            surv[lab] = survival(f, 3.0)
    if surv:
        sv = pd.DataFrame(surv); sv.index.name = "R level"; sv.to_csv(SR / "rm_mfe_survival.csv")
        print("\n### % of filled trades whose MFE reached at least X R (SL never hit before)\n" + sv.round(1).to_markdown())
        fig, ax = plt.subplots(figsize=(7, 4))
        for c in sv.columns:
            ax.plot(sv.index, sv[c], marker="o", label=c)
        ax.set_xlabel("R reached (multiple of the zone height)"); ax.set_ylabel("% of trades"); ax.grid(alpha=.3); ax.legend()
        ax.set_title("how far do the trader's fills run before being stopped?"); fig.tight_layout(); fig.savefig(CH / "rm_mfe_survival.png", dpi=110); plt.close(fig)

    # ---------------------------------------------------------------- 5. summary table of representative systems
    reps = ["base_v8"]
    reps += oos.sort_values("return_%", ascending=False).name.head(3).tolist()
    reps += oos.sort_values("ret_dd", ascending=False).name.head(3).tolist()
    if ins is not None:
        reps += ins.sort_values("avg_R", ascending=False).name.head(3).tolist()
        reps += m.name.head(5).tolist()
    for f in ("B", "C", "C2", "D", "E", "F"):
        sub = oos[oos.family == f]
        if len(sub):
            reps.append(sub.sort_values("ret_dd", ascending=False).name.iloc[0])
    reps = list(dict.fromkeys(reps))
    cols = ["name", "overrides", "trades", "return_%", "max_dd_%", "profit_factor", "avg_R", "win_%", "sharpe_daily", "H1_R", "H2_R", "months_pos", "avg_hold_min", "ret_dd"]
    tab = oos[oos.name.isin(reps)][cols].copy()
    if ins is not None:
        tab = tab.merge(ins[["name", "avg_R", "PF", "win_%", "max_dd_R", "months_pos", "t_stat"]].rename(
            columns={"avg_R": "IS_avg_R", "PF": "IS_PF", "win_%": "IS_win_%", "max_dd_R": "IS_max_dd_R", "months_pos": "IS_months_pos", "t_stat": "IS_t"}), on="name", how="left")
    tab["order"] = tab.name.map({n: i for i, n in enumerate(reps)})
    tab = tab.sort_values("order").drop(columns="order")
    tab.to_csv(SR / "rm_summary_table.csv", index=False)
    print("\n### representative systems\n" + md(tab.drop(columns=["overrides"]), ".2f"))

    # ---------------------------------------------------------------- 6. equity curves of the finalists
    fin = ["base_v8", "A_p0.6_f0.25_tp2.5", "A_p0.6_f0.25_tp3.0", "D_0.6-1.2-2.0_25_25_50", "A_p1.0_f0.33_tp3.0",
           "B_tp3.0_be1.0", "C2_trail2.0_start0_tp0", "C_p0.4_trail0.3_tp1.5_start0"]
    fin = list(dict.fromkeys(fin))
    fig, ax = plt.subplots(figsize=(10, 5))
    for n in fin:
        f = SR / "rm_study" / f"{n}_equity.csv"
        if f.exists():
            e = pd.read_csv(f, parse_dates=["time"]).set_index("time")
            r = oos[oos.name == n].iloc[0]
            ax.plot(e.index, e.equity, lw=2.2 if n == "base_v8" else 1.3, label=f"{n}  {r['return_%']:+.1f}% / DD {r['max_dd_%']:.1f}%")
    ax.set_title("OOS equity Mar-Sep 2026 ($10k, 1 % risk, real costs) - current spec vs finalists"); ax.grid(alpha=.3); ax.legend(fontsize=8)
    fig.tight_layout(); fig.savefig(CH / "rm_equity_finalists.png", dpi=110); plt.close(fig)

    # ---------------------------------------------------------------- 7. stress
    if stress is not None:
        stress = stress.drop_duplicates(["name", "scenario"], keep="last")
        pv = stress.pivot(index="scenario", columns="name", values="return_%")
        order = [s for s in ("normal", "spread_x1.5", "spread_x2", "slippage_x3", "worst_intrabar", "be_delay_2min", "netting",
                             "commission_x2", "risk_0.5", "risk_2.0", "max_open_2", "no_costs") if s in pv.index]
        pv = pv.reindex(order)
        print("\n### stress: OOS return % by scenario\n" + pv.round(1).reset_index().to_markdown(index=False))
        pv_dd = stress.pivot(index="scenario", columns="name", values="max_dd_%").reindex(order)
        print("\n### stress: OOS max DD % by scenario\n" + pv_dd.round(1).reset_index().to_markdown(index=False))
        fig, ax = plt.subplots(figsize=(12, 4.8))
        keep = [c for c in ("base_v8", "A_p0.6_f0.25_tp2.5", "A_p0.6_f0.25_tp3.0", "A_p0.6_f0.33_tp2.5", "D_0.6-1.2-2.0_25_25_50",
                            "A_p1.0_f0.33_tp3.0", "B_tp3.0_be1.0", "C2_trail2.0_start0_tp0", "C_p0.4_trail0.3_tp1.5_start0") if c in pv.columns]
        (pv[keep] if keep else pv).plot.bar(ax=ax, width=.8); ax.axhline(0, c="k", lw=.7); ax.set_ylabel("OOS return %"); ax.set_title("stress tests of the finalists (OOS Mar-Sep 2026)")
        ax.legend(fontsize=7); ax.grid(axis="y", alpha=.3); fig.tight_layout(); fig.savefig(CH / "rm_stress.png", dpi=110); plt.close(fig)

    # ---------------------------------------------------------------- 8. monthly R of base vs best (IS + OOS)
    if ins is not None:
        best = "A_p0.6_f0.25_tp2.5" if (SR / "rm_insample" / "A_p0.6_f0.25_tp2.5_trades.csv").exists() else m.name.iloc[0]
        rows = []
        for lab, n in (("current spec", "base_v8"), ("best", best)):
            for per, f in (("IS", SR / "rm_insample" / f"{n}_trades.csv"), ("OOS", SR / "rm_study" / f"{n}_trades.csv")):
                # the in-sample replay runs to the end of Feb 2026, the portfolio OOS starts in March: no month overlaps
                if f.exists():
                    t = pd.read_csv(f)
                    tcol = "sel_time" if "sel_time" in t else "close_time"
                    t["month"] = pd.to_datetime(t[tcol]).dt.strftime("%Y-%m")
                    g = t.groupby("month").r_net.sum()
                    for k, v in g.items():
                        rows.append({"system": f"{lab} ({n})", "period": per, "month": k, "R": v})
        mm = pd.DataFrame(rows)
        if len(mm):
            pv = mm.pivot_table(index="month", columns="system", values="R").sort_index()
            pv.to_csv(SR / "rm_monthly_R.csv")
            print("\n### monthly total R, current spec vs best (in-sample months then OOS months)\n" + pv.round(1).reset_index().to_markdown(index=False))
            fig, ax = plt.subplots(figsize=(11, 4)); pv.plot.bar(ax=ax, width=.8); ax.axhline(0, c="k", lw=.7)
            ax.set_ylabel("R per month"); ax.set_title(f"monthly R: current spec vs {best} (Jan 2025 - Sep 2026; OOS from 2026-03)"); ax.grid(axis="y", alpha=.3)
            fig.tight_layout(); fig.savefig(CH / "rm_monthly_R.png", dpi=110); plt.close(fig)
    print("\ncharts:", sorted(p.name for p in CH.glob("rm_*.png")))


if __name__ == "__main__":
    main()
