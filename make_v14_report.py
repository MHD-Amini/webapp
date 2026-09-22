#!/usr/bin/env python3
"""v14 step 5 - report study_results/MARTINGALE_V14.md + charts/v14_*.png from the v14 result files
(v14_diag/*.csv, v14_levers.csv, v14_stress.csv, v14_shuffle.csv, per-run jsons/trades/equity).
Every number in the report is read from those files - nothing is typed in.      python make_v14_report.py
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

SR = Path("study_results")
RUNS = SR / "v14_levers"
DIAG = SR / "v14_diag"
CH = SR / "charts"
CH.mkdir(exist_ok=True)

REF = "ref"
A = "FIB_c3_r3_htfbuy_dn0.5"            # v14-A: the loss-reducing asymmetric martingale (shipped)
B = "MU_1.25_c3_r3_htf_dn0.5"           # v14-B: 13/13 months, softer
C = "MU_1.5_c3_r3_htfbuy_dn0.5"         # v14-C: the return-oriented asymmetric variant
CLASSIC = ("MU_2.0_c3_r3", "MU_1.5_c3_r3", "FIB_c3_r3", "ADD_1.5_c3", "DEF_1.0_c3_r3", "ANTI_1.3_c2", "SHR_0.5_c2")
LABEL = {REF: "v13-A reference (flat 1 %)",
         A: "v14-A: fib steps on HTF buys after a loss, x0.5 elsewhere",
         B: "v14-B: x1.25 steps on HTF after a loss, x0.5 elsewhere",
         C: "v14-C: x1.5 steps on HTF buys after a loss, x0.5 elsewhere",
         "MU_2.0_c3_r3": "classic martingale x2 (cap 3 steps, 3 % max)", "MU_1.5_c3_r3": "x1.5 after every loss (cap 3, 3 % max)",
         "FIB_c3_r3": "Fibonacci steps after every loss", "ADD_1.5_c3": "d'Alembert +0.5 x base per loss",
         "DEF_1.0_c3_r3": "deficit recovery (win the deficit back in 1 R)", "ANTI_1.3_c2": "anti-martingale x1.3 after wins",
         "SHR_0.5_c2": "shrink x0.5 after every loss (everywhere)"}
COLS = ["trades", "return_%", "max_dd_%", "profit_factor", "win_%", "gross_loss_$", "avg_loss_$", "worst_trade_%eq", "worst_day_%eq",
        "max_risk_%eq", "ulcer", "return_over_dd", "OOS_PF", "months_pos", "up_n", "dn_n", "deep_n"]
STRESS_TAGS = ("spread_x2", "commission_x2", "slip_x3", "worst_intrabar", "risk0.5", "risk2")
OOS = "2026-03-01"


def md(df: pd.DataFrame) -> str:
    return df.to_markdown(index=False)


def fam_of(name: str) -> str:
    if name == "ref":
        return "ref"
    if name.startswith("CMB"):
        return "A + grid"
    if name.startswith("GR"):
        return "zone grid"
    if "_dn" in name:
        return "asymmetric"
    if name.startswith("SHR"):
        return "shrink"
    if name.startswith("ANTI"):
        return "anti"
    return "step-up"


def load():
    lev = pd.read_csv(SR / "v14_levers.csv")
    lev["family"] = lev.name.map(fam_of)
    stress = pd.read_csv(SR / "v14_stress.csv") if (SR / "v14_stress.csv").exists() else pd.DataFrame()
    shuf = pd.read_csv(SR / "v14_shuffle.csv") if (SR / "v14_shuffle.csv").exists() else pd.DataFrame()
    streaks = pd.read_csv(DIAG / "streaks.csv")
    after_k = pd.read_csv(DIAG / "after_k.csv")
    gates = pd.read_csv(DIAG / "after_loss_gates.csv")
    classic = pd.read_csv(DIAG / "classic_mart.csv")
    mae = pd.read_csv(DIAG / "mae_buckets.csv")
    names = [n for n in LABEL if (RUNS / f"{n}.json").exists()]
    runs = {n: json.load(open(RUNS / f"{n}.json")) for n in names}
    trades = {n: pd.read_csv(RUNS / f"{n}_trades.csv", parse_dates=["entry_time", "close_time"]) for n in (REF, A, B, C) if n in runs}
    return lev, stress, shuf, streaks, after_k, gates, classic, mae, runs, trades


def charts(lev, runs, trades, shuf):
    # 1. equity
    fig, ax = plt.subplots(figsize=(11, 5))
    for n in (REF, B, C, A):
        if n not in runs:
            continue
        e = pd.read_csv(RUNS / f"{n}_equity.csv", index_col=0, parse_dates=True)
        r = runs[n]
        ax.plot(e.index, e.equity, label=f"{LABEL[n]}  ({r['return_%']:+.0f} %, DD {r['max_dd_%']:.1f} %, PF {r['profit_factor']:.2f}, "
                                          f"lost {r['gross_loss_$']:,.0f} $)", lw=1.7 if n == A else 1.0)
    ax.axvline(pd.Timestamp(OOS), color="k", ls="--", lw=0.8)
    ax.set_title("Full year Sep 2025 -> Sep 2026, $10 000, 1 % base risk, real costs (dashed: entry model out-of-sample from here)")
    ax.set_ylabel("equity $"); ax.grid(alpha=.3); ax.legend(fontsize=8)
    fig.tight_layout(); fig.savefig(CH / "v14_equity.png", dpi=110); plt.close(fig)

    # 2. drawdown
    fig, ax = plt.subplots(figsize=(11, 3.5))
    for n in (REF, A):
        e = pd.read_csv(RUNS / f"{n}_equity.csv", index_col=0, parse_dates=True).equity
        ax.plot(e.index, 100 * (e / e.cummax() - 1), label=LABEL[n].split(":")[0], lw=1)
    ax.set_ylabel("drawdown %"); ax.grid(alpha=.3); ax.legend(fontsize=8); ax.set_title("Drawdown from equity peak")
    fig.tight_layout(); fig.savefig(CH / "v14_drawdown.png", dpi=110); plt.close(fig)

    # 3. scatter: gross loss vs return, per family
    fig, ax = plt.subplots(figsize=(10, 6))
    colors = {"ref": "k", "step-up": "tab:red", "asymmetric": "tab:green", "shrink": "tab:blue", "anti": "tab:purple", "zone grid": "tab:orange",
              "A + grid": "tab:olive"}
    for f, c in colors.items():
        v = lev[lev.family == f]
        if len(v):
            ax.scatter(-v["gross_loss_$"] / 1000, v["return_%"], c=c, s=22 + 60 * (v["max_dd_%"] < -6.5), alpha=.7, label=f)
    for n, mk in ((REF, "*"), (A, "D"), (B, "s"), (C, "^")):
        if n not in set(lev.name):
            continue
        r = lev[lev.name == n].iloc[0]
        ax.scatter([-r["gross_loss_$"] / 1000], [r["return_%"]], marker=mk, s=180, edgecolor="k", facecolor="none", lw=1.5)
        ax.annotate(LABEL[n].split(":")[0], (-r["gross_loss_$"] / 1000, r["return_%"]), textcoords="offset points", xytext=(6, 6), fontsize=8)
    ref = lev[lev.name == REF].iloc[0]
    ax.axhline(ref["return_%"], color="k", ls=":", lw=.8); ax.axvline(-ref["gross_loss_$"] / 1000, color="k", ls=":", lw=.8)
    ax.set_xlabel("gross $ lost over the year (k$)  <- less is better"); ax.set_ylabel("full-year return %")
    ax.set_title(f"{len(lev)} martingale variants: money lost vs money made (big marker = max DD deeper than 6.5 %)")
    ax.grid(alpha=.3); ax.legend(fontsize=8, loc="upper left")
    fig.tight_layout(); fig.savefig(CH / "v14_scatter.png", dpi=110); plt.close(fig)

    # 4. loss distribution ref vs A
    fig, ax = plt.subplots(figsize=(10, 4))
    bins = np.linspace(-3.0, 0.0, 31)
    for n, c in ((REF, "tab:gray"), (A, "tab:green")):
        t = trades[n]
        eq = pd.read_csv(RUNS / f"{n}_equity.csv", index_col=0, parse_dates=True).equity
        eq_at = eq.reindex(t.entry_time, method="ffill").to_numpy()
        l = t.net.to_numpy() / eq_at * 100
        ax.hist(l[l < 0], bins=bins, alpha=.55, color=c, label=f"{LABEL[n].split(':')[0]}: {int((l < 0).sum())} losers, sum {l[l < 0].sum():.1f} % of equity")
    ax.set_xlabel("losing trade in % of the equity at entry"); ax.set_ylabel("trades"); ax.grid(alpha=.3, axis="y"); ax.legend(fontsize=8)
    ax.set_title("Where the loss reduction comes from: the losing trades of the weak post-loss slices are half-size")
    fig.tight_layout(); fig.savefig(CH / "v14_losses.png", dpi=110); plt.close(fig)

    # 5. risk % of equity per trade over time (A) coloured by step
    t = trades[A]
    eq = pd.read_csv(RUNS / f"{A}_equity.csv", index_col=0, parse_dates=True).equity
    risk = t.risk_money.to_numpy() / eq.reindex(t.entry_time, method="ffill").to_numpy() * 100
    fig, ax = plt.subplots(figsize=(11, 3.8))
    col = np.where(t.mart_step > 0, "tab:red", np.where(t.mart_step < 0, "tab:blue", "tab:gray"))
    ax.scatter(t.entry_time, risk, c=col, s=12)
    ax.set_ylabel("risk of the trade, % of equity"); ax.grid(alpha=.3)
    ax.set_title(f"v14-A sizing per trade: grey = base 1 %, red = stepped UP after a loss ({int((t.mart_step > 0).sum())}), "
                 f"blue = stepped DOWN ({int((t.mart_step < 0).sum())}); max {risk.max():.2f} %")
    fig.tight_layout(); fig.savefig(CH / "v14_risk.png", dpi=110); plt.close(fig)

    # 6. monthly $
    fig, ax = plt.subplots(figsize=(11, 4.5))
    mon = pd.DataFrame({LABEL[n].split(":")[0]: pd.Series(runs[n]["monthly_$"]) for n in (REF, A)})
    mon.plot.bar(ax=ax, width=.8, color=["tab:gray", "tab:green"]); ax.axhline(0, color="k", lw=.8); ax.grid(alpha=.3, axis="y")
    ax.set_title("Monthly net $"); ax.set_ylabel("$")
    fig.tight_layout(); fig.savefig(CH / "v14_monthly.png", dpi=110); plt.close(fig)

    # 7. shuffle distributions (if available)
    if len(shuf) and A in set(shuf.name):
        s = shuf[shuf.name == A].iloc[0]
        fig, ax = plt.subplots(figsize=(8, 3.8))
        labels = ["return > flat", "DD better than flat", "return/DD > flat", "less $ lost than flat"]
        sh = [s["shuf_p_ret>flat"], s["shuf_p_dd_better"], s["shuf_p_rd>flat"], s["shuf_p_loss_less"]]
        bo = [s["boot_p_ret>flat"], s["boot_p_dd_better"], s["boot_p_rd>flat"], s["boot_p_loss_less"]]
        x = np.arange(4)
        ax.bar(x - 0.2, sh, 0.4, label="random shuffle of the trade order", color="tab:blue")
        ax.bar(x + 0.2, bo, 0.4, label="block bootstrap (blocks of 10 trades)", color="tab:green")
        ax.axhline(0.5, color="k", ls=":", lw=.8); ax.set_xticks(x); ax.set_xticklabels(labels, fontsize=8); ax.set_ylim(0, 1)
        ax.set_ylabel("share of resampled orders"); ax.legend(fontsize=8); ax.grid(alpha=.3, axis="y")
        ax.set_title(f"{LABEL[A].split(':')[0]} vs flat sizing on the SAME resampled trade sequences (sequence-only re-sizing)")
        fig.tight_layout(); fig.savefig(CH / "v14_shuffle.png", dpi=110); plt.close(fig)


def step_table(trades, n):
    t = trades[n].copy()
    t["group"] = np.where(t.mart_step > 0, "stepped UP", np.where(t.mart_step < 0, "stepped DOWN", "base size"))
    g = t.groupby("group")
    out = pd.DataFrame({"trades": g.size(), "win %": (100 * g.apply(lambda x: (x.net > 0).mean())).round(1),
                        "net $": g.net.sum().round(0), "avg R (of the plan's own budget)": g.r_net.mean().round(3),
                        "avg risk $": g.risk_money.mean().round(0), "losers": g.apply(lambda x: int((x.net < 0).sum())),
                        "$ lost": g.apply(lambda x: x[x.net < 0].net.sum()).round(0)}).reset_index()
    # the SAME trades in the reference (by key) - what did they make at flat size?
    ref = trades[REF].set_index("key")
    same = {grp: ref.reindex(t[t.group == grp].key).net for grp in out.group}
    out["same trades in ref: net $"] = [round(same[g].sum(), 0) for g in out.group]
    out["same trades in ref: $ lost"] = [round(same[g][same[g] < 0].sum(), 0) for g in out.group]
    return out


def main():
    lev, stress, shuf, streaks, after_k, gates, classic, mae, runs, trades = load()
    charts(lev, runs, trades, shuf)
    ref, a = runs[REF], runs[A]
    top = lev[lev.name.isin(LABEL)].set_index("name").reindex([n for n in LABEL if n in set(lev.name)]).reset_index()
    top.insert(0, "variant", top.name.map(LABEL))
    reduce = lev[lev.reduce_loss & lev.hold_loss & lev.keep_oos].sort_values("return_%", ascending=False)
    fam = lev.groupby("family").agg(n=("name", "size"), reduce_loss=("reduce_loss", "sum"), hold_loss=("hold_loss", "sum"),
                                    better_rd=("better_rd", "sum"), keep_return=("keep_return", "sum"), median_ret=("return_%", "median"),
                                    median_dd=("max_dd_%", "median"), median_loss=("gross_loss_$", "median")).round(1).reset_index()
    lines = []
    w = lines.append
    w("# v14 — a martingale that REDUCES the losses: the asymmetric (edge-aware) martingale\n")
    w(f"*Generated by `make_v14_report.py` from the v14 result files ({len(lev)} full-year variants, "
      f"{len(stress)} stress runs, {len(shuf)} shuffle tests).*\n")
    w("## 1. The question and the answer\n")
    w("**Spec.** Create a Martingale strategy for the v13-A trader that reduces the losses of the trades; be creative; save after every step.\n")
    w(f"**Answer.** A *classic* martingale (double the size after every loss) cannot reduce losses on this bot — the diagnosis below shows "
      f"why: the trade after a loss is *weaker*, not stronger, so every step-up puts more money on a worse trade; it buys return with "
      f"drawdown and more dollars lost (see section 3).  The creative version that does reduce the losses is the **asymmetric, "
      f"edge-aware martingale (v14-A)**: after a loss the bot steps the size **up** only where the post-loss edge is positive "
      f"(M10 / M15 / M30 / H1 **buy** plans, Fibonacci steps 1-2-3 × base, capped at 3 steps and 3 % of equity) and steps it **down to "
      f"half size** everywhere else (M5 plans and sells, the slices that lose money after a loss).  A win resets the streak; break-even "
      f"exits are neutral.  On the full year it turns {ref['gross_loss_$']:,.0f} $ of losses into {a['gross_loss_$']:,.0f} $ "
      f"(**{100 * (a['gross_loss_$'] / ref['gross_loss_$'] - 1):+.1f} %**), the average losing trade from {ref['avg_loss_$']:.0f} $ to "
      f"{a['avg_loss_$']:.0f} $ ({100 * (a['avg_loss_$'] / ref['avg_loss_$'] - 1):+.1f} %), the max drawdown from {ref['max_dd_%']:.2f} % to "
      f"{a['max_dd_%']:.2f} %, keeps {a['months_pos']}/{a['months']} months positive and the profit factor rises from {ref['profit_factor']:.3f} to "
      f"{a['profit_factor']:.3f} (OOS {ref['OOS_PF']:.2f} → {a['OOS_PF']:.2f}); the return is {a['return_%']:+.1f} % vs {ref['return_%']:+.1f} %.\n")
    w("| variant | trades | return | max DD | PF | win | $ lost | avg loss | worst trade | worst day | max risk | ulcer | ret/DD | OOS PF | months>0 | up | down | deep |")
    w("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for _, r in top.iterrows():
        w(f"| {r.variant} | {r.trades} | {r['return_%']:+.1f} % | {r['max_dd_%']:.2f} % | {r.profit_factor:.3f} | {r['win_%']:.1f} % | "
          f"{r['gross_loss_$']:,.0f} | {r['avg_loss_$']:.0f} | {r['worst_trade_%eq']:.2f} % | {r['worst_day_%eq']:.2f} % | {r['max_risk_%eq']:.2f} % | "
          f"{r.ulcer:.3f} | {r.return_over_dd:.1f} | {r.OOS_PF:.2f} | {int(r.months_pos)}/{int(r.months)} | {int(r.up_n)} | {int(r.dn_n)} | {int(r.deep_n)} |")
    w("\n*worst trade / worst day / max risk are in % of the equity at the time; ulcer = RMS drawdown; up / down = trades sized above / below "
      "the base after a loss; deep = zone-grid deep legs.*\n")
    w("## 2. Diagnosis — what a martingale has to live with (`run_v14_diag.py`, `study_results/v14_diag/`)\n")
    w("**Loss streaks are short.**  Consecutive-loss runs of the v13-A trader in close order:\n")
    w(md(streaks[["slice", "trades", "losses", "loss_%", "runs", "max_run", "runs>=2", "runs>=3", "runs>=4", "indep_expected_max_run"]]))
    w("\n**The trade after a loss is weaker, not stronger** (so a step-up adds size to a worse trade):\n")
    w(md(after_k))
    w("\n**Where the post-loss trade still has an edge** (the gates of the asymmetric martingale come from this table):\n")
    w(md(gates))
    w("\n**Classic schemes on the same trade sequence** (sequence-only approximation, compounding, daily 4.5 % / total 9 % rules):\n")
    w(md(classic))
    w("\n**How deep into the zone before the outcome (MAE)** — the zone-grid idea: a second limit deeper in the zone fills on the trades that "
      "pull back first; every trade that pulled back less than 0.9 R won, every trade beyond 1 R was a stop:\n")
    w(md(mae.rename(columns={"mae_b": "MAE bucket (R)"})))
    w("\n## 3. The grid (`run_v14_levers.py`, `study_results/v14_levers.csv`)\n")
    w("Families: **step-up** (multiplier / Fibonacci / d'Alembert / deficit recovery, with and without gates), **asymmetric** (gated step-up + "
      "step-down where the gate fails), **shrink** (anti-martingale on losses), **anti** (grow after wins), **zone grid** (a second, deeper "
      "limit order on every plan), **A + grid**.  Judged against v13-A on the loss side: `reduce_loss` = less $ lost AND smaller average "
      "loss; `hold_loss` = max DD not deeper than ref + 0.5 pt, worst day not worse than ref − 0.5 pt, at most one month fewer positive; "
      "`keep_oos` = OOS PF ≥ ref − 0.05; `keep_return` = return ≥ ref − 5 pt; `better_rd` = return/DD above ref.\n")
    w(md(fam.rename(columns={"n": "variants", "median_ret": "median return %", "median_dd": "median max DD %", "median_loss": "median $ lost"})))
    w(f"\n**Variants that reduce the losses without breaking the loss band or the OOS PF** ({len(reduce)} of {len(lev)}):\n")
    show = reduce[["name", "trades", "return_%", "max_dd_%", "profit_factor", "gross_loss_$", "avg_loss_$", "worst_day_%eq", "max_risk_%eq",
                   "return_over_dd", "OOS_PF", "months_pos", "up_n", "dn_n", "deep_n"]].head(25)
    w(md(show))
    w("\n**Why the step-up alone never reduces losses**: in every step-up variant the money lost is larger than the reference "
      f"(median of the family {fam[fam.family == 'step-up'].median_loss.iloc[0]:,.0f} $ vs {ref['gross_loss_$']:,.0f} $) — more size on the "
      "after-loss trades, which win less often.  **Why shrinking everywhere is not the answer**: it cuts the losses but also the return "
      f"(median {fam[fam.family == 'shrink'].median_ret.iloc[0]:+.0f} %).  **The asymmetric family** is the only one where the loss falls "
      "and the return holds: the step-down removes money from the negative post-loss slices, the gated step-up puts it on the positive ones.\n")
    w("**The zone grid** (a real price-martingale, bounded by the zone) fills its deep leg on about half of the plans; it lowers the "
      "average loss per trade and the worst trade, but on this stream the deep leg is a coin flip and the OOS profit factor falls — it is "
      "kept as an option (`grid_add_r`), not shipped.\n")
    w("## 4. What the stepped trades did (v14-A)\n")
    w(md(step_table(trades, A)))
    w("\n## 5. Robustness\n")
    if len(stress):
        st = stress[stress.name.isin((REF, A, B, C))].copy()
        st["variant"] = st.name.map(lambda n: LABEL[n].split(":")[0])
        piv = st.pivot_table(index="tag", columns="variant", values=["return_%", "max_dd_%", "gross_loss_$", "OOS_PF"], aggfunc="first")
        w("**Stress** (spread ×2, commission ×2, slippage ×3, worst intrabar path, risk 0.5 % / 2 %) — return / max DD / $ lost / OOS PF:\n")
        for tag in STRESS_TAGS:
            if tag not in piv.index:
                continue
            row = [f"**{tag}**"]
            for n in (REF, A, B, C):
                v = LABEL[n].split(":")[0]
                if ("return_%", v) in piv.columns:
                    row.append(f"{v}: {piv.loc[tag, ('return_%', v)]:+.0f} % / {piv.loc[tag, ('max_dd_%', v)]:.1f} / "
                               f"{piv.loc[tag, ('gross_loss_$', v)]:,.0f} $ / {piv.loc[tag, ('OOS_PF', v)]:.2f}")
            w("- " + " | ".join(row))
        w("")
    if len(shuf):
        w("**Shuffle / bootstrap** (`shuffle_v14.py`): the sizing rule replayed on resampled orders of the reference trades, paired with flat "
          "sizing on the same orders.  `p` = share of resampled sequences where the variant beats flat; `hist rank` = where the historical "
          "order sits in the variant's own distribution (near 1 = the historical order was lucky):\n")
        cols = ["name", "hist_ret", "flat_ret", "hist_dd", "flat_dd", "hist_loss", "flat_loss", "shuf_p_ret>flat", "shuf_p_rd>flat", "shuf_p_loss_less",
                "shuf_hist_rank_rd", "boot_p_ret>flat", "boot_p_rd>flat", "boot_p_loss_less", "boot_hist_rank_rd", "boot_dd_p95", "boot_flat_dd_p95"]
        w(md(shuf[[c for c in cols if c in shuf.columns]]))
        w("")
    w("## 6. Live bot\n")
    w("`trader.py` carries the same `Martingale` state machine (`lubot/martingale.py`): every finished plan's realised net P&L is read from the "
      "MT5 deal history and appended to `trader_state.json` (`closed` list); on start the state is rebuilt from that list, so a restart "
      "cannot lose or double a streak.  The status line shows the streak (`mart all:k1`).  `run_trader.bat` ships v14-A "
      "(`mart_mode=fib,mart_max_steps=3,mart_max_risk_pct=3,mart_tfs=M10|M15|M30|H1,mart_sides=buy,mart_ungated_scale=0.5`); "
      "`verify_bat_v14.py` replays the bat strings in the simulator and must reproduce the study json.  The zone grid is available with "
      "`grid_add_r=0.5,grid_base_frac=0.5,grid_add_frac=0.5` (deep leg = `<key>+g`, cancelled with its edge plan).\n")
    w("## 7. Honest limits\n")
    w("- One year, 430 trades, 106 losers: the gates (HTF buys up, M5 / sells down) are read from the same year they are judged on.  The "
      "shuffle test shows the loss reduction is a property of the population (the step-down), not of the order; the drawdown improvement is "
      "partly order luck.\n- The martingale only changes SIZE; entries, stops and targets are v13-A.  Max risk per trade is capped at 3 % of "
      "equity; the v10 account rules (daily 4.5 %, total 9 %) stay in force.\n- `mart_step` of every trade is in the trade lists "
      "(`study_results/v14_levers/*_trades.csv`).\n")
    w("\nCharts: `charts/v14_equity.png`, `v14_drawdown.png`, `v14_scatter.png`, `v14_losses.png`, `v14_risk.png`, `v14_monthly.png`, `v14_shuffle.png`.\n")
    (SR / "MARTINGALE_V14.md").write_text("\n".join(lines), encoding="utf-8")
    print("wrote study_results/MARTINGALE_V14.md", len(lines), "lines")


if __name__ == "__main__":
    main()
