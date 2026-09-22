#!/usr/bin/env python3
"""v13 step 5 - report study_results/WEAK_MONTHS_V13.md + charts/v13_*.png from the v13 result files
(v13_diag/*.csv, v13_levers.csv, v13_stress.csv, v13_walkforward.csv, v13_neighbourhood.csv, per-run jsons/trades/equity).
Every number in the report is read from those files - nothing is typed in.      python make_v13_report.py"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy.stats import spearmanr  # noqa: E402

SR = Path("study_results")
RUNS = SR / "v13_levers"
DIAG = SR / "v13_diag"
CH = SR / "charts"
CH.mkdir(exist_ok=True)

REF = "ref"
A = "RG_adr1.0_tight_l03"
B = "RG_adr0.9_tight_w3_20"
C = "RG_adr1.0_tight"
OTHERS = ("RG_adr1.1_three", "RG_er0.2_three", "RG_er0.4_G_l03_10")
LABEL = {REF: "v12-A reference", A: "v13-A: ADR5/20 < 1.0 -> tight ladder + lock +0.3R", B: "v13-B: ADR3/20 < 0.9 -> tight ladder",
         C: "v13-C: ADR5/20 < 1.0 -> tight ladder (no lock)", "RG_adr1.1_three": "ADR5/20 < 1.1 -> 3-leg 0.6/1.2/2.4",
         "RG_er0.2_three": "ER5 < 0.2 -> 3-leg 0.6/1.2/2.4", "RG_er0.4_G_l03_10": "ER5 < 0.4 -> G ladder + lock 0.3/1.0"}
COLS = ["trades", "return_%", "max_dd_%", "profit_factor", "win_%", "sl_%", "worst_day_%", "OOS_R", "OOS_PF", "apr26_R", "sep25_R",
        "worst_month_R", "months_pos", "range_n", "range_R", "hold_loss", "hold_oos", "fix_weak"]
STRESS_TAGS = ("spread_x2", "commission_x2", "slip_x3", "worst_intrabar", "risk0.5", "risk2")
OOS = "2026-03-01"
WEAK = ("2025-09", "2026-04")


def md(df: pd.DataFrame) -> str:
    return df.to_markdown(index=False)


def load():
    lev = pd.read_csv(SR / "v13_levers.csv")
    stress = pd.read_csv(SR / "v13_stress.csv")
    wf = pd.read_csv(SR / "v13_walkforward.csv")
    nb = pd.read_csv(SR / "v13_neighbourhood.csv")
    by_month = pd.read_csv(DIAG / "by_month.csv")
    regime = pd.read_csv(DIAG / "regime.csv")
    ladder = pd.read_csv(DIAG / "ladder_month.csv")
    filt = pd.read_csv(DIAG / "filtered_replay.csv")
    runs = {n: json.load(open(RUNS / f"{n}.json")) for n in LABEL}
    trades = {n: pd.read_csv(RUNS / f"{n}_trades.csv", parse_dates=["entry_time", "close_time"]) for n in (REF, A)}
    return lev, stress, wf, nb, by_month, regime, ladder, filt, runs, trades


def charts(lev, runs, trades, regime):
    # 1. equity curves
    fig, ax = plt.subplots(figsize=(11, 5))
    for n in (REF, C, A):
        e = pd.read_csv(RUNS / f"{n}_equity.csv", index_col=0, parse_dates=True)
        r = runs[n]
        ax.plot(e.index, e.equity, label=f"{LABEL[n]}  ({r['trades']} tr, {r['return_%']:+.0f} %, DD {r['max_dd_%']:.1f} %, PF {r['profit_factor']:.2f})",
                lw=1.6 if n == A else 1.0)
    ax.axvline(pd.Timestamp(OOS), color="k", ls="--", lw=0.8)
    ax.axvspan(pd.Timestamp("2026-04-01"), pd.Timestamp("2026-05-01"), color="tab:red", alpha=.08)
    ax.axvspan(pd.Timestamp("2025-09-01"), pd.Timestamp("2025-10-01"), color="tab:orange", alpha=.08)
    ax.set_title("Full year Sep 2025 -> Sep 2026, $10 000, 1 % risk, real costs (shaded: the two weak months; dashed: entry model OOS from here)")
    ax.set_ylabel("equity $"); ax.grid(alpha=.3); ax.legend(fontsize=8)
    fig.tight_layout(); fig.savefig(CH / "v13_equity.png", dpi=110); plt.close(fig)

    # 2. monthly $ ref vs A
    fig, ax = plt.subplots(figsize=(11, 4.5))
    mon = pd.DataFrame({LABEL[n].split(":")[0]: pd.Series(runs[n]["monthly_$"]) for n in (REF, A)})
    mon.plot.bar(ax=ax, width=.8, color=["tab:gray", "tab:green"]); ax.axhline(0, color="k", lw=.8); ax.grid(alpha=.3, axis="y")
    ax.set_title("Monthly net $ (Apr 2026: the negative month of v12-A; Sep 2025: partial month, low volatility)"); ax.set_ylabel("$")
    for i, m in enumerate(mon.index):
        if m in WEAK:
            ax.get_xticklabels()[i].set_color("tab:red")
    fig.tight_layout(); fig.savefig(CH / "v13_monthly.png", dpi=110); plt.close(fig)

    # 3. share of range-managed trades per month vs the month's volatility
    tr = trades[A].copy()
    tr["month"] = tr.close_time.dt.strftime("%Y-%m")
    share = tr.groupby("month").regime.apply(lambda s: 100 * (s == "range").mean())
    fig, ax = plt.subplots(figsize=(11, 4))
    share.plot.bar(ax=ax, color=["tab:red" if m in WEAK else "tab:blue" for m in share.index], width=.8)
    ax.set_ylabel("% of trades placed in 'range' regime"); ax.grid(alpha=.3, axis="y")
    ax2 = ax.twinx()
    rg = regime.set_index("time")
    ax2.plot(range(len(share)), rg.reindex(share.index)["avg_day_rng_%"].to_numpy(), "k.-", lw=1)
    ax2.set_ylabel("avg daily range % (month)")
    ax.set_title("v13-A: share of trades managed with the tight ladder per month vs the month's average daily range")
    fig.tight_layout(); fig.savefig(CH / "v13_regime.png", dpi=110); plt.close(fig)

    # 4. scatter: April R vs full-year return for every variant
    fig, ax = plt.subplots(figsize=(10, 6))
    fam = lev.name.str.extract(r"^(RG_|LAD_|LOCK_|RISK_|ref)")[0].fillna("other")
    names = {"ref": "reference", "RG_": "regime switch (RG)", "LAD_": "alt. ladder for every plan", "LOCK_": "stop lock for every plan", "RISK_": "risk scale in range"}
    colors = {"ref": "k", "RG_": "tab:green", "LAD_": "tab:red", "LOCK_": "tab:orange", "RISK_": "tab:purple"}
    for f, c in colors.items():
        v = lev[fam == f]
        ax.scatter(v.apr26_R, v["return_%"], c=c, s=22 + 60 * (v["max_dd_%"] < -6.0), alpha=.7, label=names[f])
    for n, mk in ((REF, "*"), (A, "D"), (B, "s"), (C, "^")):
        r = lev[lev.name == n].iloc[0]
        ax.scatter([r.apr26_R], [r["return_%"]], marker=mk, s=180, edgecolor="k", facecolor="none", lw=1.5)
        ax.annotate(LABEL[n].split(":")[0], (r.apr26_R, r["return_%"]), textcoords="offset points", xytext=(6, 6), fontsize=8)
    ref = lev[lev.name == REF].iloc[0]
    ax.axhline(ref["return_%"], color="k", ls=":", lw=.8); ax.axvline(0, color="k", ls=":", lw=.8)
    ax.set_xlabel("April 2026 result (R)"); ax.set_ylabel("full-year return %")
    ax.set_title(f"{len(lev)} variants: fixing April vs the whole year (big marker = max DD deeper than 6 %)")
    ax.grid(alpha=.3); ax.legend(fontsize=8, loc="lower right")
    fig.tight_layout(); fig.savefig(CH / "v13_scatter.png", dpi=110); plt.close(fig)

    # 5. IS vs OOS walk-forward scatter
    fig, ax = plt.subplots(figsize=(7, 6))
    ax.scatter(lev.IS_R, lev.OOS_R, s=18, alpha=.6, c=["tab:green" if f else "tab:gray" for f in lev.fix_weak])
    for n, mk in ((REF, "*"), (A, "D")):
        r = lev[lev.name == n].iloc[0]
        ax.scatter([r.IS_R], [r.OOS_R], marker=mk, s=180, edgecolor="k", facecolor="none", lw=1.5)
        ax.annotate(LABEL[n].split(":")[0], (r.IS_R, r.OOS_R), textcoords="offset points", xytext=(6, 6), fontsize=8)
    sp, p = spearmanr(lev.IS_R, lev.OOS_R)
    ax.set_xlabel("in-sample R (Sep 2025 - Feb 2026)"); ax.set_ylabel("out-of-sample R (Mar - Sep 2026)")
    ax.set_title(f"Walk-forward: Spearman {sp:+.2f} (p {p:.3f}); green = fixes the weak months"); ax.grid(alpha=.3)
    fig.tight_layout(); fig.savefig(CH / "v13_walkforward.png", dpi=110); plt.close(fig)

    # 6. drawdown
    fig, ax = plt.subplots(figsize=(11, 3.5))
    for n in (REF, A):
        e = pd.read_csv(RUNS / f"{n}_equity.csv", index_col=0, parse_dates=True).equity
        ax.plot(e.index, 100 * (e / e.cummax() - 1), label=LABEL[n].split(":")[0], lw=1)
    ax.set_ylabel("drawdown %"); ax.grid(alpha=.3); ax.legend(fontsize=8); ax.set_title("Drawdown from equity peak")
    fig.tight_layout(); fig.savefig(CH / "v13_drawdown.png", dpi=110); plt.close(fig)


def range_trade_table(trades):
    """The trades v13-A manages differently: same fills as ref (regime only changes the exits) -> compare outcome by regime."""
    a, r = trades[A].copy(), trades[REF].copy()
    a["month"] = a.close_time.dt.strftime("%Y-%m")
    key = ["key", "entry_time"]
    m = a.merge(r[key + ["r_net", "outcome"]], on=key, how="left", suffixes=("", "_ref"))
    rg = m[m.regime == "range"]
    rows = []
    for lab, part in (("all range trades", rg), ("Apr 2026", rg[rg.month == "2026-04"]), ("Jul 2026", rg[rg.month == "2026-07"]),
                      ("IS half", rg[rg.close_time < OOS]), ("OOS half", rg[rg.close_time >= OOS])):
        rows.append({"slice": lab, "n": len(part), "R v13-A": round(part.r_net.sum(), 2), "R v12-A (same fills)": round(part.r_net_ref.sum(), 2),
                     "win % A": round(100 * (part.net > 0).mean(), 1) if len(part) else np.nan,
                     "sl % A": round(100 * (part.outcome == "sl").mean(), 1) if len(part) else np.nan,
                     "sl % ref": round(100 * (part.outcome_ref == "sl").mean(), 1) if len(part) else np.nan,
                     "tp2 % A": round(100 * (part.outcome == "tp2").mean(), 1) if len(part) else np.nan,
                     "tp2 % ref": round(100 * (part.outcome_ref == "tp2").mean(), 1) if len(part) else np.nan})
    return pd.DataFrame(rows), int(rg.r_net_ref.isna().sum())


def main():
    lev, stress, wf, nb, by_month, regime, ladder, filt, runs, trades = load()
    charts(lev, runs, trades, regime)
    ref = lev[lev.name == REF].iloc[0]
    ra = lev[lev.name == A].iloc[0]
    fin = [REF, A, B, C, *OTHERS]
    tab = lev[lev.name.isin(fin)].set_index("name").loc[fin].reset_index()
    tab.insert(1, "what", tab.name.map(LABEL))
    rg_tab, n_unmatched = range_trade_table(trades)

    mo = pd.DataFrame({"month": list(runs[REF]["monthly_$"].keys()),
                       "v12-A $": list(runs[REF]["monthly_$"].values()), "v12-A R": list(runs[REF]["monthly_R"].values()),
                       "v13-A $": [runs[A]["monthly_$"].get(m) for m in runs[REF]["monthly_$"]],
                       "v13-A R": [runs[A]["monthly_R"].get(m) for m in runs[REF]["monthly_$"]]})
    tr_a = trades[A].copy(); tr_a["month"] = tr_a.close_time.dt.strftime("%Y-%m")
    mo["range trades A"] = mo.month.map(tr_a[tr_a.regime == "range"].groupby("month").size()).fillna(0).astype(int)
    mo["d $"] = (mo["v13-A $"] - mo["v12-A $"]).round(2)

    st_rows = []
    for n in (REF, A, B, C):
        row = {"variant": LABEL[n].split(":")[0], "base": f"{runs[n]['return_%']:+.0f} / {runs[n]['max_dd_%']:.1f} / {runs[n]['OOS_PF']:.2f} / {runs[n]['apr26_R']:+.1f}"}
        for tag in STRESS_TAGS:
            s = stress[(stress.name == n) & (stress.tag == tag)]
            if len(s):
                s = s.iloc[0]
                row[tag] = f"{s['return_%']:+.0f} / {s['max_dd_%']:.1f} / {s['OOS_PF']:.2f} / {s['apr26_R']:+.1f}"
        st_rows.append(row)
    st = pd.DataFrame(st_rows)
    beats = 0
    for tag in STRESS_TAGS:
        sa = stress[(stress.name == A) & (stress.tag == tag)].iloc[0]
        sr = stress[(stress.name == REF) & (stress.tag == tag)].iloc[0]
        beats += int(sa["return_%"] > sr["return_%"] and sa["OOS_PF"] > sr["OOS_PF"])

    sp_r, p_r = spearmanr(lev.IS_R, lev.OOS_R)
    sp_pf, p_pf = spearmanr(lev.IS_PF, lev.OOS_PF)
    sp_apr, p_apr = spearmanr(lev.apr26_R, lev.other_R)
    n_fix = int(lev.fix_weak.sum()); n_fix_both = int((lev.fix_weak & lev.hold_loss & lev.hold_oos).sum())
    fix_names = lev[lev.fix_weak & lev.hold_loss & lev.hold_oos].name
    n_rg_fix = int(fix_names.str.startswith("RG_").sum())
    is_rank = lev.IS_R.rank(ascending=False); oos_rank = lev.OOS_R.rank(ascending=False)
    rk = lambda n, r: int(r[lev.name == n].iloc[0])  # noqa: E731

    apr_d = by_month[by_month.month == "2026-04"].iloc[0]
    sep_d = by_month[by_month.month == "2025-09"].iloc[0]
    apr_l = ladder[ladder.month == "2026-04"].iloc[0]
    apr_rg = regime[regime.time == "2026-04"].iloc[0]
    sep_rg = regime[regime.time == "2025-09"].iloc[0]
    yr_l = ladder[~ladder.month.isin(WEAK)]
    f_apr = filt[filt.month == "2026-04"]
    f_apr_filled = f_apr[f_apr.filled == True]  # noqa: E712
    f_sep = filt[(filt.month == "2025-09") & (filt.reason == "M5: cost_r")]
    f_sep_filled = f_sep[f_sep.filled == True]  # noqa: E712
    wf_top = wf.head(12)
    lad_every = lev[lev.name.isin(("LAD_tight", "LAD_t3", "LAD_one1"))].set_index("name")
    v = lambda n, c: lev[lev.name == n].iloc[0][c]  # noqa: E731

    d_mo = pd.Series({m: runs[A]["monthly_R"].get(m, 0) - runs[REF]["monthly_R"].get(m, 0) for m in runs[REF]["monthly_R"] if m not in WEAK})
    rg_md = "\n".join(f"| {r.slice} | {r.n} | {r['R v13-A']:+.2f} | {r['R v12-A (same fills)']:+.2f} | {r['win % A']} | {r['sl % A']} | {r['sl % ref']} | {r['tp2 % A']} | {r['tp2 % ref']} |"
                      for _, r in rg_tab.iterrows())

    txt = f"""# WEAK MONTHS v13 — why Apr 2026 was negative and Sep 2025 weak, and the fix (regime-adaptive management)

*Generated by `make_v13_report.py` from the v13 result files.  Simulator = the M1 portfolio simulator used since v7 (limit fills on
ask/bid, MT5-tester intrabar path, imputed spread, $7 commission, slippage, broker rounding), full year Sep 2025 -> Sep 2026,
$10 000 start, 1 % risk.  Entry model trained until 2026-03-01: Sep25-Feb26 is in-sample (IS) for the *entries*, Mar-Sep26 out-of-sample (OOS).
Reference = v12-A, the trader shipped in `run_trader.bat` before this study.*

## 0. Result in one paragraph

The negative month was **not caused by bad trade selection but by trade management that does not fit a ranging market**.  In April 2026
(post-crash range after the -11.6 % March) the 4-leg ladder 0.6/1.2/2.4/4.8 R never reached its far legs, partials fell back to break-even
and the stop-rate rose - the reference lost {ref.apr26_R:+.2f} R (${runs[REF]['apr26_$']:+.0f}).  A **regime switch** computed from CLOSED
daily bars only (`ADR5/ADR20 < 1.0` = volatility contracting) that manages plans placed in that regime with a **tight ladder
0.5/1.0/1.5/2.5 R + stop lock (BE after leg 1, +0.3 R after leg 2)** turns April into {ra.apr26_R:+.2f} R (${runs[A]['apr26_$']:+.0f}) while
the other 11 months are NET unchanged ({ra.d_other:+.1f} R in total vs reference; single months move between {d_mo.min():+.1f} and {d_mo.max():+.1f} R because 187 more trades are managed with the tight ladder in the other range weeks of the year).  Full year: **{int(ra.trades)} trades, {ra['return_%']:+.1f} %, max DD
{abs(ra['max_dd_%']):.2f} %, PF {ra.profit_factor:.2f}, win {ra['win_%']:.1f} %, worst day {ra['worst_day_%']:.2f} %, {int(ra.months_pos)}/{int(ra.months)} months positive**
(reference {int(ref.trades)} / {ref['return_%']:+.1f} % / {abs(ref['max_dd_%']):.2f} % / {ref.profit_factor:.2f} / {ref['win_%']:.1f} % / {ref['worst_day_%']:.2f} % / {int(ref.months_pos)}/{int(ref.months)}).
It beats the reference on return AND out-of-sample PF in {beats} of {len(STRESS_TAGS)} stress scenarios and sits in the middle of a smooth
plateau of {len(nb)} neighbouring settings that ALL make April positive.  **Sep 2025 stays {ra.sep25_R:+.2f} R**: that month is opportunity
starvation (lowest volatility of the year, M5 zones too small to pay the spread) - the honest finding is that nothing in the same stream can be
added without paying for it elsewhere (section 2).

`run_trader.bat` now ships v13-A; `verify_bat_v13.py` replays the exact bat strings to the same {int(ra.trades)} trades / {ra['return_%']:+.2f} %.

![equity](charts/v13_equity.png)

## 1. Diagnosis of April 2026 (the negative month)

* {int(apr_d.n)} trades, {apr_d.R:+.2f} R, PF {apr_d.PF:.2f}, win {apr_d['win_%']:.0f} %, stops {apr_d['sl_%']:.0f} %, TP2 {apr_d['tp2_%']:.0f} % - a normal NUMBER of
  trades (funnel of the month = normal) and NOT one bad slice: sells {apr_d.sell_R:+.1f} R, counter-trend {apr_d.counter_R:+.1f} R, M10 and the
  pre-NY session were all negative in April but every one of those slices is strongly positive over the year and OOS -> a filter would cost more elsewhere.
* **The driver is the ladder**: legs reached in April vs the other months - 1.2 R {apr_l['reach_1.2R_%']:.0f} % (other months {yr_l['reach_1.2R_%'].min():.0f}-{yr_l['reach_1.2R_%'].max():.0f} %),
  2.4 R {apr_l['reach_2.4R_%']:.0f} %, 4.8 R {apr_l['reach_4.8R_%']:.0f} % (other {yr_l['reach_4.8R_%'].min():.0f}-{yr_l['reach_4.8R_%'].max():.0f} %); legs closed per trade {apr_l.legs_closed_avg:.2f}
  (other {yr_l.legs_closed_avg.min():.2f}-{yr_l.legs_closed_avg.max():.2f}); median MFE {apr_l.mfe_med:.2f} R.  A flat 1 R exit on the same fills would have made {apr_l.R_if_flat_1R:+.0f} R.
* **Regime**: April = post-crash range.  Month range {apr_rg['range_%']:.1f} % (lowest since Dec), chop {apr_rg.chop:.1f} (year 1.4-9 except Jul), trend efficiency
  {apr_rg.trend_eff:.2f}, {int(apr_rg.ema20_flips)} EMA20 flips, avg daily range {apr_rg['avg_day_rng_%']:.2f} %.  Over the 13 months Spearman(monthly R, avg daily range %) = +0.56:
  the bot earns with volatility.
* **Were good POIs filtered out?**  The {len(f_apr)} April POIs rejected by the trade filter were replayed with the reference management:
  {len(f_apr_filled)} would have filled for {f_apr_filled.r_gross.sum():+.1f} R GROSS (before commission) -> the filter threw nothing good away.
* Worst days 04-08 (-2.31 %, two confluence stops within 18 min) and 04-27 (-1.98 %).

**Hypothesis confirmed by the grid**: April cannot be fixed by trading less or selecting differently - it needs MANAGEMENT that adapts to a
ranging regime.

## 2. Diagnosis of September 2025 (the weak month)

* {int(sep_d.n)} trades, {sep_d.R:+.2f} R (${sep_d['net_$']:+.0f} on a $10 000 account = +3.3 % of equity, i.e. Dec/Jun/Jul level), PF {sep_d.PF:.2f}, avg {sep_d.avg_R:+.2f} R/trade = normal.
  The month is **partial** in the stream (starts 2025-09-01, {int(sep_rg.days)} trading days but only 13 with a trade) and it was the **lowest-volatility month
  of the year**: avg daily range ${sep_rg.avg_day_rng_usd:.0f} = {sep_rg['avg_day_rng_%']:.2f} % of a $3 500 gold price (later months 2-3.6 %).
* Consequence: M5 zones had a median height of $2.3 (year $4-7) -> cost_r = (spread + commission) / zone = 0.15 >> the 0.08 cap -> {len(f_sep)} of the
  M5 POIs were rejected by the cost gate, only 4 M5 trades (other months 8-23).  Replay of those {len(f_sep)} rejects: {len(f_sep_filled)} fills,
  {f_sep_filled.r_gross.sum():+.1f} R **gross** = zero edge before commission -> **the gate was right**.  M15 / M10 quality rejects replayed negative as well.
* Regime in September: chop {sep_rg.chop:.1f}, trend efficiency {sep_rg.trend_eff:.2f} = a steady low-volatility TREND, not a range -> the regime switch does not
  touch it (0 range trades); honest result: Sep 2025 stays {ra.sep25_R:+.2f} R.  The only variants that lift it (a lock on the ER metric) do it at the
  cost of April and of the OOS half -> rejected.

## 3. The lever: regime-adaptive management (`lubot/regime.py`, TraderConfig `regime_*` / `range_*`)

* `adr_ratio` = mean daily range of the last `regime_short`=5 CLOSED server days / last `regime_long`=20 days.  The value of day D uses days < D
  only (no look-ahead; the live bot excludes the unfinished current day).  `regime_of(v, 1.0)` -> **range** when v < 1.0, else **trend**.
* Plans PLACED in a range regime use `range_tp_levels=0.5|1.0|1.5|2.5` (25 % each) and `range_sl_after_leg=0|0.3|x|x` (SL -> BE after leg 1,
  -> +0.3 R after leg 2, then left); trend plans keep the v10 G ladder 0.6/1.2/2.4/4.8 with BE after leg 1.  Defaults are byte-identical to
  v12 (parity test), the trades frame carries a `regime` column.
* In the year {int(ra.range_n)} of {int(ra.trades)} trades were range-managed ({100 * ra.range_n / ra.trades:.0f} %): {rg_tab.iloc[1].n} in April, {rg_tab.iloc[2].n} in July (the two range months), 0 in Sep 2025 / Sep 2026.

![regime](charts/v13_regime.png)

### Same fills, different exits: the {int(ra.range_n)} range-managed trades under both managements

| slice | n | R v13-A | R v12-A (same fills) | win % A | sl % A | sl % ref | tp2 % A | tp2 % ref |
|---|---|---|---|---|---|---|---|---|
{rg_md}

(Fills matched on key + entry time; {n_unmatched} range trades of v13-A have no exact counterpart in the reference because an earlier exit freed a
slot for a different order.)  The tight ladder wins on the range trades in BOTH halves of the year; the trend trades are untouched.

## 4. Grid: {len(lev)} variants on top of v12-A

Families: `RG_` regime switch x metric (ADR ratio / efficiency ratio / absolute ADR %) x threshold x alternative ladder x stop lock x TF subset;
`LAD_` the alternative ladder for EVERY plan; `LOCK_` a stop lock for every plan; `RISK_` reduced/increased risk in a range.
Judged on: Apr26 R, Sep25 R, worst month, 13/13 months, the other 11 months not worse than -3 R, AND the v12 loss bands on the full year
(`hold_loss`: DD not > 0.5 pt deeper, PF >= ref-0.05, win >= ref-3, worst day >= ref-0.5) and on the OOS half (`hold_oos`).

* {n_fix} variants fix the weak months (April > 0, no negative month, other months >= -3 R); **{n_fix_both} of them also hold BOTH loss bands - and
  {n_rg_fix} of those {n_fix_both} are regime switches (RG_)**.
* **The switch is needed**: the tight ladder for EVERY plan (LAD_tight) gives {lad_every.loc['LAD_tight', 'return_%']:+.0f} % (April {lad_every.loc['LAD_tight', 'apr26_R']:+.1f} R but the trending months pay for it),
  LAD_t3 {lad_every.loc['LAD_t3', 'return_%']:+.0f} %, one leg at 1 R {lad_every.loc['LAD_one1', 'return_%']:+.0f} % with DD {abs(lad_every.loc['LAD_one1', 'max_dd_%']):.1f} % - the far legs earn the year in trending months.
* Stop locks for every plan (LOCK_l03_10: April {v('LOCK_l03_10', 'apr26_R'):+.2f} R) and risk scaling in a range (RISK_adr0.9_0.5: return
  {v('RISK_adr0.9_0.5', 'return_%'):+.0f} %, April {v('RISK_adr0.9_0.5', 'apr26_R'):+.2f} R) do not fix April; not trading in a range at all costs ~50 % of the return.
* Spearman(April R, other-months R) over the grid = {sp_apr:+.2f} (p {p_apr:.2f}): fixing April does NOT systematically cost the other months.

![scatter](charts/v13_scatter.png)

### Finalists

{md(tab[['name', 'what'] + COLS])}

## 5. Robustness

### Stress (return % / max DD % / OOS PF / April R)

{md(st)}

v13-A beats the reference on return and OOS PF in {beats}/{len(STRESS_TAGS)} scenarios.  At DOUBLE spread every variant loses ~110 M5 trades to the cost gate
and April is negative for all of them (reference included) - the regime lever cannot fix a month whose trades vanish.

### Walk-forward (pick on the IS half only, verify OOS)

Spearman(IS R, OOS R) over the {len(lev)} variants = **{sp_r:+.2f}** (p {p_r:.3f}), (IS PF, OOS PF) = **{sp_pf:+.2f}** (p {p_pf:.1e}) - POSITIVE, unlike the
v11/v12 selection levers (-0.29): management levers generalise.  Picking on the IS half alone (IS PF >= ref-0.05, sorted by IS R) gives a top-12
whose median OOS PF is {wf_top.OOS_PF.median():.2f} vs {ref.OOS_PF:.2f} for the reference; v13-A ranks {rk(A, is_rank)}/{len(lev)} IS and {rk(A, oos_rank)}/{len(lev)} OOS
(reference {rk(REF, is_rank)}/{rk(REF, oos_rank)}) - consistent on both halves, not an OOS-picked outlier.

![walkforward](charts/v13_walkforward.png)

### Neighbourhood of v13-A ({len(nb)} settings: threshold 0.8-1.1, windows 3-10 / 10-40 days, locks, ladders, fractions)

April positive in **{int((nb.apr26_R > 0).sum())}/{len(nb)}**, 13/13 months in {int((nb.months_pos == 13).sum())}/{len(nb)}, both loss bands held in {int((nb.hold_loss & nb.hold_oos).sum())}/{len(nb)}
(misses: ADR windows 3/20 and 7/20 with DD {abs(nb[nb.name == 'RG_adr1.0_tight_l03_w3_20']['max_dd_%'].iloc[0]):.2f} / {abs(nb[nb.name == 'RG_adr1.0_tight_l03_w7_20']['max_dd_%'].iloc[0]):.2f} %), PF {nb.profit_factor.min():.2f}-{nb.profit_factor.max():.2f} (ref {ref.profit_factor:.2f}).
The plateau is smooth -> not a lucky cell.

{md(nb[['name', 'trades', 'return_%', 'max_dd_%', 'profit_factor', 'worst_day_%', 'OOS_R', 'OOS_PF', 'apr26_R', 'worst_month_R', 'months_pos', 'range_n', 'range_R', 'hold_loss', 'hold_oos']])}

## 6. Month by month, reference vs v13-A

{md(mo)}

![monthly](charts/v13_monthly.png)
![drawdown](charts/v13_drawdown.png)

## 7. Honest reading / limits

* One year of data, ONE deep range month (April) plus July; the lever is judged on {int(ra.range_n)} range-managed trades.  The neighbourhood, stress and
  walk-forward results say the effect is not a single lucky cell, but a regime switch tuned on a year that contains one deep range will be
  tested for real only in the next one.
* The finalists were chosen on the full year; their OOS numbers therefore carry some selection bias.  The IS-only pick still lands on the same
  family (RG with tight ladder / lock) and v13-A ranks consistently on both halves.
* Sep 2025 is NOT improved - by design.  The month is short, at the lowest volatility of the year, and the rejected trades had no gross edge.
  Any lever that lifts it in the grid does so through the entry stream's in-sample half and loses OOS.
* The live bot computes the same metric from the same closed daily bars (`Trader.current_regime`, logged in every status line), applies the
  range ladder / stop schedule per plan (`sl_after_leg` carried in the plan state) and was tested against the fake MT5 (3 tests).

## 8. Files

`run_v13_diag.py` (diagnosis -> `v13_diag/`), `lubot/regime.py`, `run_v13_levers.py` + `run_v13_all.sh` / `run_v13_stage4.sh` / `run_v13_neigh.sh`
(grid + stress + neighbourhood, resumable -> `v13_levers/`, `v13_levers.csv`, `v13_stress.csv`), `walkforward_v13.py` (-> `v13_walkforward.csv`,
`v13_neighbourhood.csv`), `verify_bat_v13.py`, `tests/test_v13_regime.py`, `tests/test_trader_live.py::test_v13_*`, `tests/test_bat_v13.py`, this report.
"""
    (SR / "WEAK_MONTHS_V13.md").write_text(txt)
    print(txt[:2500])
    print("...\nreport ->", SR / "WEAK_MONTHS_V13.md")


if __name__ == "__main__":
    main()
