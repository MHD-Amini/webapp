#!/usr/bin/env python3
"""v10 step 7 - tables + charts for the MULTI-TP study and the FULL-YEAR backtest (all from result files).

Inputs : study_results/v10_study_grid.csv (+ v10_study/*), v10_insample.csv (+ v10_insample/*),
         v10_year_summary.csv (+ v10_year/*), rm_study_grid.csv / rm_insample.csv (v9 two-leg reference)
Outputs: study_results/v10_is_vs_oos.csv, v10_by_legs.csv, v10_by_stop.csv, v10_by_fracs.csv, v10_finalists.csv,
         v10_year_table.csv, charts/v10_*.png ; prints the markdown tables used in MULTI_TP_STUDY.md.
"""
from __future__ import annotations

import json
import re
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


def stop_kind(name: str) -> str:
    for k in ("be2ratchet", "be2", "ratchet", "lock", "classic"):
        if name.endswith("_" + k):
            return k
    if name.startswith("R_"):
        return "runner_trail"
    return "two_leg" if name.startswith(("A2", "v9", "base", "ATR2")) else "other"


def first_level(over: str) -> float:
    m = re.search(r"tp_levels=([^,]+)", over or "")
    if m:
        return float(m.group(1).split("|")[0])
    m = re.search(r"partial_r=([0-9.]+)", over or "")
    return float(m.group(1)) if m else 0.4


def last_level(over: str) -> float:
    m = re.search(r"tp_levels=([^,]+)", over or "")
    if m:
        lv = [float(x) for x in m.group(1).split("|")]
        return lv[-1] if lv[-1] > 0 else lv[-2]
    m = re.search(r"tp2_r=([0-9.]+)", over or "")
    return float(m.group(1)) if m else 1.5


def main():
    oos = pd.read_csv(SR / "v10_study_grid.csv")
    oos["overrides"] = oos.overrides.fillna("")
    oos["stop"] = oos.name.map(stop_kind)
    oos["lv1"] = oos.overrides.map(first_level)
    oos["lvN"] = oos.overrides.map(last_level)
    ins = pd.read_csv(SR / "v10_insample.csv") if (SR / "v10_insample.csv").exists() else None
    base = oos[oos.name == "base_v8"].iloc[0]
    v9 = oos[oos.name == "v9_p0.6_f0.25_tp2.5"].iloc[0]
    out = {}

    # ---------------------------------------------------------------- 1. IS vs OOS merge
    m = oos.copy()
    if ins is not None:
        ins = ins.copy()
        ins["overrides"] = ins.overrides.fillna("")
        m = oos.merge(ins.drop(columns=["overrides", "family", "legs"], errors="ignore"), on="name", suffixes=("", "_is"))
        m = m.rename(columns={"avg_R_is": "avg_R_is", "PF": "PF_is", "win_%_is": "win_is", "max_dd_R_is": "dd_R_is",
                              "t_stat_is": "t_is", "months_pos_is": "mpos_is"})
        rho, p = spearmanr(m["avg_R_is"], m["avg_R"])
        rho2, _ = spearmanr(m["avg_R_is"], m["ret_dd"])
        out["spearman"] = (rho, p, rho2, len(m))
        print(f"\nSpearman(IS avg R, OOS avg R) = {rho:.2f} (p={p:.2g}, n={len(m)}); IS avg R vs OOS ret/DD = {rho2:.2f}")
        m["rank_is"] = m.avg_R_is.rank(ascending=False)
        m["rank_oos"] = m.ret_dd.rank(ascending=False)
        m["rank_sum"] = m.rank_is + m.rank_oos
        # robust score: in-sample R/plan per unit of in-sample drawdown, both must be top-half OOS too
        m["is_ret_dd"] = m["total_R_is"] / m["dd_R_is"].abs().clip(lower=1)
    m.to_csv(SR / "v10_is_vs_oos.csv", index=False)

    # ---------------------------------------------------------------- 2. by number of legs
    agg = {"n": ("name", "size"), "oos_ret_med": ("return_%", "median"), "oos_ret_best": ("return_%", "max"),
           "oos_dd_med": ("max_dd_%", "median"), "oos_pf_med": ("profit_factor", "median"), "oos_win_med": ("win_%", "median"),
           "oos_retdd_med": ("ret_dd", "median"), "oos_retdd_best": ("ret_dd", "max")}
    if ins is not None:
        agg.update({"is_avgR_med": ("avg_R_is", "median"), "is_avgR_best": ("avg_R_is", "max"), "is_pf_med": ("PF_is", "median"),
                    "is_dd_med": ("dd_R_is", "median"), "is_win_med": ("win_is", "median")})
    by_legs = m.groupby("legs").agg(**agg).reset_index()
    by_legs.to_csv(SR / "v10_by_legs.csv", index=False)
    print("\n### by number of legs (medians / best over all variants with that many legs)\n" + md(by_legs, ".2f"))
    by_stop = m[m.legs >= 3].groupby(["legs", "stop"]).agg(**agg).reset_index()
    by_stop.to_csv(SR / "v10_by_stop.csv", index=False)
    print("\n### 3+ legs: by stop schedule\n" + md(by_stop, ".2f"))
    by_fam = m.groupby("family").agg(**agg).reset_index()
    print("\n### by family\n" + md(by_fam, ".2f"))
    # fractions: front-loaded vs back-loaded (share of the position closed at the first target)
    def first_frac(over):
        mm = re.search(r"tp_fracs=([^,]+)", over)
        if mm:
            fr = [float(x) for x in mm.group(1).split("|")]
            return round(fr[0] / sum(fr), 2)
        mm = re.search(r"partial_frac=([0-9.]+)", over)
        return float(mm.group(1)) if mm else 0.5
    m["frac1"] = m.overrides.map(first_frac)
    by_fr = m[m.legs >= 3].groupby(pd.cut(m[m.legs >= 3].frac1, [0, 0.15, 0.22, 0.3, 0.45, 1.0]), observed=False).agg(**agg).reset_index()
    by_fr.to_csv(SR / "v10_by_fracs.csv", index=False)
    print("\n### 3+ legs: by share closed at the FIRST target\n" + md(by_fr, ".2f"))
    by_lv1 = m[m.legs >= 3].groupby("lv1").agg(**agg).reset_index()
    print("\n### 3+ legs: by first target level (R)\n" + md(by_lv1, ".2f"))
    by_lvN = m[m.legs >= 3].groupby("lvN").agg(**agg).reset_index()
    print("\n### 3+ legs: by last fixed target level (R)\n" + md(by_lvN, ".2f"))

    # ---------------------------------------------------------------- 3. finalists table
    cols = ["name", "legs", "trades", "return_%", "max_dd_%", "profit_factor", "avg_R", "win_%", "sharpe_daily", "H1_R", "H2_R", "months_pos"]
    if ins is not None:
        cols += ["avg_R_is", "PF_is", "win_is", "dd_R_is", "mpos_is", "t_is", "rank_sum"]
    refs = m[m.name.isin(["base_v8", "v9_p0.6_f0.25_tp2.5", "v9_p0.6_f0.25_tp3.0"])]
    fin = [refs]
    fin.append(m[m.legs >= 3].sort_values("return_%", ascending=False).head(8))
    fin.append(m[m.legs >= 3].sort_values("ret_dd", ascending=False).head(8))
    if ins is not None:
        fin.append(m[m.legs >= 3].sort_values("avg_R_is", ascending=False).head(8))
        fin.append(m[m.legs >= 3].sort_values("rank_sum").head(10))
        for k in (3, 4, 5):
            fin.append(m[m.legs == k].sort_values("rank_sum").head(3))
    fin = pd.concat(fin).drop_duplicates("name")
    fin[cols].to_csv(SR / "v10_finalists.csv", index=False)
    print("\n### finalists (references + OOS best + IS best + rank-sum best)\n" + md(fin[cols], ".3f"))
    if ins is not None:
        # how many multi-leg systems beat v9 on BOTH evaluations?
        beat = m[(m.legs >= 3) & (m.avg_R_is > v9_is(m)) & (m["return_%"] > v9["return_%"])]
        print(f"\nmulti-leg systems beating the v9 recommendation on BOTH IS avg R and OOS return: {len(beat)} of {int((m.legs >= 3).sum())}")
        if len(beat):
            print(md(beat.sort_values("rank_sum")[cols].head(15), ".3f"))
        beat_dd = beat[(beat["max_dd_%"] >= v9["max_dd_%"]) & (beat.dd_R_is >= m[m.name == "v9_p0.6_f0.25_tp2.5"].dd_R_is.iloc[0])]
        print(f"... of which also with drawdown <= v9 on both: {len(beat_dd)}")
        if len(beat_dd):
            print(md(beat_dd.sort_values("rank_sum")[cols].head(15), ".3f"))

    # ---------------------------------------------------------------- 4. charts
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    for k, g in m.groupby("legs"):
        axes[0].scatter(g["max_dd_%"].abs(), g["return_%"], s=12, alpha=0.6, label=f"{k} legs (n={len(g)})")
    for nm, mk in (("base_v8", "k*"), ("v9_p0.6_f0.25_tp2.5", "r*")):
        r = m[m.name == nm].iloc[0]
        axes[0].plot(abs(r["max_dd_%"]), r["return_%"], mk, ms=14, label=nm)
    axes[0].set_xlabel("OOS max drawdown %"); axes[0].set_ylabel("OOS return % (Mar-Sep 2026)"); axes[0].legend(fontsize=8)
    axes[0].set_title("OOS: return vs drawdown by number of legs")
    if ins is not None:
        for k, g in m.groupby("legs"):
            axes[1].scatter(g["avg_R_is"], g["avg_R"], s=12, alpha=0.6, label=f"{k} legs")
        for nm, mk in (("base_v8", "k*"), ("v9_p0.6_f0.25_tp2.5", "r*")):
            r = m[m.name == nm].iloc[0]
            axes[1].plot(r["avg_R_is"], r["avg_R"], mk, ms=14, label=nm)
        axes[1].set_xlabel("in-sample R / plan (Jan25-Feb26)"); axes[1].set_ylabel("OOS R / trade")
        axes[1].set_title(f"IS vs OOS, Spearman {out['spearman'][0]:.2f}"); axes[1].legend(fontsize=8)
    plt.tight_layout(); plt.savefig(CH / "v10_legs_scatter.png", dpi=110); plt.close()

    # box plots by legs
    fig, axes = plt.subplots(1, 3 if ins is not None else 1, figsize=(15, 4.5))
    axes = np.atleast_1d(axes)
    m.boxplot(column="return_%", by="legs", ax=axes[0]); axes[0].set_title("OOS return % by legs"); axes[0].set_xlabel("")
    if ins is not None:
        m.boxplot(column="avg_R_is", by="legs", ax=axes[1]); axes[1].set_title("in-sample R/plan by legs"); axes[1].set_xlabel("")
        m.boxplot(column="dd_R_is", by="legs", ax=axes[2]); axes[2].set_title("in-sample max DD (R) by legs"); axes[2].set_xlabel("")
    plt.suptitle(""); plt.tight_layout(); plt.savefig(CH / "v10_legs_box.png", dpi=110); plt.close()

    # equity curves of the references + top-3 multi-leg by rank-sum (OOS)
    fig, ax = plt.subplots(figsize=(11, 5))
    pick = ["base_v8", "v9_p0.6_f0.25_tp2.5", "v9_p0.6_f0.25_tp3.0"]
    if ins is not None:
        pick += m[m.legs >= 3].sort_values("rank_sum").name.head(3).tolist()
    else:
        pick += m[m.legs >= 3].sort_values("ret_dd", ascending=False).name.head(3).tolist()
    for nm in pick:
        f = SR / "v10_study" / f"{nm}_equity.csv"
        if f.exists():
            e = pd.read_csv(f, parse_dates=["time"]).set_index("time")
            ax.plot(e.index, e.equity, lw=1.3, label=nm)
    ax.set_title("OOS equity (Mar-Sep 2026, $10k, 1 % risk)"); ax.legend(fontsize=8); ax.grid(alpha=0.3)
    plt.tight_layout(); plt.savefig(CH / "v10_equity_oos.png", dpi=110); plt.close()

    # ---------------------------------------------------------------- 5. full-year table
    yf = SR / "v10_year_summary.csv"
    if yf.exists():
        y = pd.read_csv(yf)
        y["tag"] = y.tag.fillna("")
        main_ = y[y.tag == ""].copy()
        ycols = ["system", "rules", "trades", "return_%", "max_dd_%", "profit_factor", "win_%", "sharpe_daily", "IS_n", "IS_R", "IS_net_$",
                 "OOS_n", "OOS_R", "OOS_net_$", "months_pos", "months", "daily_halts", "halted", "worst_day_%", "worst_intraday_vs_daystart_%", "end_balance"]
        main_[ycols].to_csv(SR / "v10_year_table.csv", index=False)
        print("\n### FULL YEAR Sep 2025 -> Sep 2026 ($10k, 1 % risk, real costs)\n" + md(main_[ycols], ".2f"))
        st = y[y.tag != ""]
        if len(st):
            piv = st.pivot_table(index=["system", "tag"], columns="rules", values=["return_%", "max_dd_%", "daily_halts", "halted"], aggfunc="first")
            piv.columns = [f"{a}_{'rules' if b else 'norules'}" for a, b in piv.columns]
            piv = piv.reset_index()
            piv.to_csv(SR / "v10_year_stress.csv", index=False)
            print("\n### full year under stress, loss rules OFF vs ON\n" + md(piv, ".2f"))
        # monthly table
        mon = pd.read_csv(SR / "v10_year_monthly.csv")
        pm = mon[mon.rules == True].pivot_table(index="month", columns="system", values="net_$", aggfunc="first").round(0)  # noqa: E712
        pm.to_csv(SR / "v10_year_monthly_table.csv")
        print("\n### monthly net $ (loss rules ON)\n" + pm.to_markdown(floatfmt=".0f"))
        # equity chart full year
        fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
        for _, r in main_.iterrows():
            f = SR / "v10_year" / f"{r['key']}_equity.csv"
            if f.exists():
                e = pd.read_csv(f, parse_dates=["time"]).set_index("time")
                axes[0 if not r.rules else 1].plot(e.index, e.equity, lw=1.2, label=r["system"])
        for ax, ttl in zip(axes, ("loss rules OFF", "loss rules ON (daily 4.5 %, total 9 %)")):
            ax.axvline(pd.Timestamp("2026-03-01"), color="k", ls="--", lw=1)
            ax.set_title(f"Full year Sep 2025 -> Sep 2026 - {ttl}   (dashed: model train cut-off, right = out-of-sample)")
            ax.grid(alpha=0.3); ax.legend(fontsize=8)
        plt.tight_layout(); plt.savefig(CH / "v10_year_equity.png", dpi=110); plt.close()
        # daily loss distribution of the v9 system (what the 4.5 % rule protects against)
        fig, ax = plt.subplots(figsize=(11, 4))
        for _, r in main_[(~main_.rules)].iterrows():
            f = SR / "v10_year" / f"{r['key']}_equity.csv"
            if f.exists():
                e = pd.read_csv(f, parse_dates=["time"]).set_index("time").equity
                d = e.resample("1D").last().dropna().pct_change().dropna() * 100
                ax.hist(d, bins=60, alpha=0.5, label=r["system"])
        ax.axvline(-4.5, color="r", ls="--", label="daily limit -4.5 %"); ax.set_xlabel("daily equity change %"); ax.legend(fontsize=8)
        ax.set_title("Distribution of daily equity changes (full year, rules OFF)")
        plt.tight_layout(); plt.savefig(CH / "v10_year_daily.png", dpi=110); plt.close()
    print("\ncharts:", sorted(p.name for p in CH.glob("v10_*.png")))


def v9_is(m: pd.DataFrame) -> float:
    return float(m[m.name == "v9_p0.6_f0.25_tp2.5"].avg_R_is.iloc[0])


if __name__ == "__main__":
    main()
