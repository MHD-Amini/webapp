#!/usr/bin/env python3
"""v13 step 1 - DIAGNOSIS of the weak months of the v12-A trader (2026-04 negative, 2025-09 weak).

1. Reproduce v12-A exactly (run_trader.bat strings): 427 trades, +179.51 %, max DD -5.28 %, PF 1.874.
2. Dissect every month, trade by trade: per timeframe / side / session / kind / outcome / confluence / quality bucket /
   cost_r bucket / zone-vs-ATR / hold time / day-of-week -> which slice of the population loses in the weak months and
   does the SAME slice lose in the other months (a structural problem) or not (a regime problem)?
3. Market regime per month from the M1 bars (monthly range, trend efficiency, average daily range in % and in $,
   realised vol, spread) and the relation between the trade side and the higher-timeframe trend (D1 EMA slope,
   20-day direction) -> counter-trend vs with-trend R per month.
4. Funnel per month: shown POIs / filtered (why) / placed / filled -> did the weak months have FEWER opportunities,
   or did they trade the same number and lose?  In particular the M5 cost gate vs the zone size in $ (Sep 2025 = gold
   at 3 500 with the lowest volatility of the year -> thin zones -> cost_r above 0.08).
5. Replay of the POIs the filter rejected in the weak months (PlanReplayer, MFE before the stop): were good trades
   thrown away, or was the problem the ones we took?
6. Loss clustering: stops that happen within N minutes of each other (correlated confluence plans), daily P&L
   distribution, the ladder's upper legs (how often 1.2 / 2.4 / 4.8R is reached per month).

Outputs (study_results/v13_diag/): ref.json, trades.csv, by_month.csv, slices_<dim>.csv, regime.csv, funnel_month.csv,
filtered_replay.csv, clusters.csv, ladder_month.csv, and a printed summary that goes into PROGRESS.md.
    python run_v13_diag.py --csv data/xauusd_m1.csv
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lubot.execution import SymbolSpec, TraderConfig  # noqa: E402
from lubot.plan_replay import PlanReplayer  # noqa: E402
from lubot.portfolio_sim import PortfolioSimulator  # noqa: E402
from lubot.trade_filter import ny_session_of  # noqa: E402
from run_v10_study import BASE  # noqa: E402
from run_v12_funnel import TFS, load_year  # noqa: E402

OUT = Path("study_results/v13_diag")
OOS_SPLIT = "2026-03-01"
WEAK = ("2026-04", "2025-09")
# --- v12-A exactly as shipped in run_trader.bat
V12A_TRADER = ("tp_levels=0.6|1.2|2.4|4.8,tp_fracs=1|1|1|1,ladder_fallback=merge,dedupe_cross_tf=false,"
               "keep_replaced_bars=1,keep_replaced_tfs=M10|M15|M30|H1")
V12A_FLT = ("M5:max_cost_r=0.08;min_quality=0.55;sessions=asia|london|preny|ny|lclose/M10:min_quality=0.57/"
            "M15:min_quality=0.60/M30|H1:min_quality=0.57")
V12A_CF = ("M5:max_cost_r=0.08;min_quality=0.55;sessions=asia|london|preny|ny|lclose/M10:min_quality=0.50/"
           "M15:min_quality=0.60/M30|H1:min_quality=0.57")
EXPECT = (427, 179.51, -5.28)


def v12a_config() -> TraderConfig:
    return TraderConfig(trade_filter=V12A_FLT, confluence_filter=V12A_CF, max_daily_loss_pct=4.5,
                        max_total_loss_pct=9.0).override(BASE).override(V12A_TRADER)


def run_ref(m1, sel):
    sim = PortfolioSimulator(m1, sel, v12a_config(), SymbolSpec())
    res = sim.run(progress=False)
    s = res.summary()
    got = (s["trades"], s["return_%"], s["max_dd_%"])
    print(f"v12-A replay: {got}  expected {EXPECT}  IDENTICAL: {got == EXPECT}")
    return sim, res, s


# ------------------------------------------------------------------ helpers
def agg(t: pd.DataFrame) -> dict:
    n = len(t)
    if n == 0:
        return {"n": 0, "R": 0.0, "net_$": 0.0, "win_%": np.nan, "sl_%": np.nan, "tp2_%": np.nan, "avg_R": np.nan, "PF": np.nan}
    g, l = t.net[t.net > 0].sum(), abs(t.net[t.net < 0].sum())
    return {"n": n, "R": round(t.r_net.sum(), 2), "net_$": round(t.net.sum(), 2), "win_%": round(100 * (t.net > 0).mean(), 1),
            "sl_%": round(100 * (t.outcome == "sl").mean(), 1), "tp2_%": round(100 * (t.outcome == "tp2").mean(), 1),
            "avg_R": round(t.r_net.mean(), 3), "PF": round(g / l, 2) if l > 0 else np.inf}


def enrich(tr: pd.DataFrame, m1: pd.DataFrame) -> pd.DataFrame:
    t = tr.copy()
    t["month"] = t.close_time.dt.strftime("%Y-%m")
    t["emonth"] = t.entry_time.dt.strftime("%Y-%m")
    t["weak"] = t.month.isin(WEAK)
    t["session"] = [ny_session_of(x)[0] for x in t.selected_time]
    t["ny_hour"] = [ny_session_of(x)[1] for x in t.selected_time]
    t["dow"] = t.entry_time.dt.day_name().str[:3]
    t["zone_usd"] = t.zone_top - t.zone_bottom
    t["zone_atr"] = (t.zone_usd / t.atr).round(2)
    t["q_bucket"] = pd.cut(t.quality, [0, 0.55, 0.60, 0.65, 0.70, 1.0], labels=["<0.55", "0.55-0.60", "0.60-0.65", "0.65-0.70", ">=0.70"])
    t["zone_atr_bucket"] = pd.cut(t.zone_atr, [0, 0.75, 1.0, 1.5, 2.0, 99], labels=["<0.75", "0.75-1", "1-1.5", "1.5-2", ">2"])
    t["hold_bucket"] = pd.cut(t.hold_min, [-1, 15, 60, 240, 1440, 1e9], labels=["<=15m", "15-60m", "1-4h", "4-24h", ">1d"])
    # cost in R (spread at fill unknown here -> median spread of the entry hour + commission $0.07/oz)
    sp = m1["spread"].reindex(t.entry_time, method="nearest").to_numpy()
    t["cost_r"] = ((sp + 0.07) / t.risk_usd_per_unit).round(3)
    t["cost_bucket"] = pd.cut(t.cost_r, [0, 0.03, 0.05, 0.08, 0.12, 9], labels=["<0.03", "0.03-0.05", "0.05-0.08", "0.08-0.12", ">0.12"])
    # higher-timeframe trend at entry: D1 close vs EMA20 (server days) and 5-day momentum
    d1 = m1["close"].resample("1D").last().dropna()
    ema20 = d1.ewm(span=20, adjust=False).mean()
    ema50 = d1.ewm(span=50, adjust=False).mean()
    mom5 = d1.pct_change(5)
    day = t.entry_time.dt.normalize() - pd.Timedelta(days=1)          # only CLOSED days are known at entry
    t["d1_above_ema20"] = (d1.reindex(day, method="ffill").to_numpy() > ema20.reindex(day, method="ffill").to_numpy())
    t["ema20_slope_up"] = (ema20.reindex(day, method="ffill").to_numpy() > ema20.shift(3).reindex(day, method="ffill").to_numpy())
    t["ema20_above_50"] = (ema20.reindex(day, method="ffill").to_numpy() > ema50.reindex(day, method="ffill").to_numpy())
    t["mom5_%"] = (100 * mom5.reindex(day, method="ffill").to_numpy()).round(2)
    up = t.d1_above_ema20
    t["trend_align"] = np.where(((t.side == "buy") & up) | ((t.side == "sell") & ~up), "with", "counter")
    # 4h momentum before the SELECTION (intraday regime): price change of the 4 hours before the POI was selected in ATR
    h4 = m1["close"]
    t0 = pd.DatetimeIndex(t.selected_time)
    c_now = h4.reindex(t0, method="ffill").to_numpy()
    c_4h = h4.reindex(t0 - pd.Timedelta(hours=4), method="ffill").to_numpy()
    t["mom4h_atr"] = ((c_now - c_4h) / t.atr).round(2)
    t["mom4h_dir"] = np.where(((t.side == "buy") & (t.mom4h_atr > 0)) | ((t.side == "sell") & (t.mom4h_atr < 0)), "with", "counter")
    # daily range of the entry day (in ATR of the trade's TF) -> how much room the ladder had
    dr = (m1["high"].resample("1D").max() - m1["low"].resample("1D").min()).dropna()
    t["day_range_usd"] = dr.reindex(t.entry_time.dt.normalize()).to_numpy()
    t["day_range_R"] = (t.day_range_usd / t.risk_usd_per_unit).round(1)
    t["legs_closed"] = t.legs.fillna("").str.count(":tp")
    return t


def slices(t: pd.DataFrame, dims: list[str]) -> dict[str, pd.DataFrame]:
    out = {}
    for d in dims:
        rows = []
        for val, g in t.groupby(d, observed=True):
            r = {"dim": d, "value": str(val)}
            for lab, part in (("all", g), ("weak", g[g.weak]), ("good", g[~g.weak]), ("apr26", g[g.month == "2026-04"]),
                              ("sep25", g[g.month == "2025-09"]), ("OOS", g[g.close_time >= OOS_SPLIT])):
                a = agg(part)
                r.update({f"{lab}_{k}": v for k, v in a.items() if k in ("n", "R", "win_%", "sl_%", "avg_R")})
            rows.append(r)
        out[d] = pd.DataFrame(rows)
    return out


def regime(m1: pd.DataFrame) -> pd.DataFrame:
    d = m1.resample("1D").agg({"open": "first", "high": "max", "low": "min", "close": "last", "spread": "mean"}).dropna()
    d["rng"] = d.high - d.low
    d["ret"] = d.close.pct_change() * 100
    d["gap"] = (d.open - d.close.shift()).abs()
    mo = d.resample("1ME").agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"),
                               avg_day_rng_usd=("rng", "mean"), max_day_rng_usd=("rng", "max"), spread=("spread", "mean"),
                               days=("rng", "size"), daily_vol_pct=("ret", "std"), avg_gap=("gap", "mean"))
    mo["chg_%"] = ((mo.close / mo.open - 1) * 100).round(2)
    mo["range_%"] = ((mo.high - mo.low) / mo.open * 100).round(2)
    mo["trend_eff"] = ((mo.close - mo.open) / (mo.high - mo.low)).round(2)
    mo["avg_day_rng_%"] = (mo.avg_day_rng_usd / mo.open * 100).round(2)
    # choppiness: sum of daily |ret| / monthly net move
    ab = d.ret.abs().resample("1ME").sum()
    mo["chop"] = (ab / mo["chg_%"].abs().replace(0, np.nan)).round(1)
    # number of D1 EMA20 direction flips inside the month (whipsaw)
    ema = d.close.ewm(span=20, adjust=False).mean()
    side = np.sign(d.close - ema)
    flips = (side != side.shift()).astype(int).resample("1ME").sum()
    mo["ema20_flips"] = flips
    mo.index = mo.index.strftime("%Y-%m")
    return mo.round(3)


def funnel_month(sim, sel: pd.DataFrame, tr: pd.DataFrame) -> pd.DataFrame:
    shown = sel[sel.id >= 0].copy()
    shown["key"] = shown.tf + "#" + shown.id.astype(int).astype(str)
    shown["month"] = shown.t.dt.strftime("%Y-%m")
    first = shown.sort_values("t").drop_duplicates("key")
    traded = set(tr.key)
    filt = defaultdict(list)
    for k, why in sim.filtered:
        filt[k].append(why)
    skipped = defaultdict(list)
    for k, why in sim.skipped:
        skipped[k].append(why)
    canc = defaultdict(list)
    for c in sim.cancelled:
        canc[c.plan.key].append(c.reason_cancel)
    rows = []
    for (mo, tf), g in first.groupby(["month", "tf"]):
        c = Counter()
        for k in g.key:
            if k in traded:
                c["traded"] += 1
            elif k in canc:
                c["placed_not_filled"] += 1
            elif k in filt:
                w = Counter(filt[k]).most_common(1)[0][0]
                c["filtered"] += 1
                c["f_" + w.split(": ")[-1]] += 1
            elif k in skipped:
                c["skip_" + Counter(skipped[k]).most_common(1)[0][0].split(" ")[0]] += 1
            else:
                c["none"] += 1
        # zone size of the shown M5 POIs vs the cost gate
        z = (g.top - g.bottom)
        rows.append({"month": mo, "tf": tf, "shown": len(g), **c, "zone_usd_med": round(z.median(), 2),
                     "zone_atr_med": round((z / g.atr).median(), 2), "q_med": round(g.quality.median(), 3)})
    return pd.DataFrame(rows).fillna(0)


def replay_filtered(sim, sel: pd.DataFrame, m1: pd.DataFrame, tr: pd.DataFrame, months=WEAK) -> pd.DataFrame:
    """What would the POIs rejected by the trade filter (in the given months) have done?  PlanReplayer with the first
    ladder leg 0.6R / 25 % as the 'partial' and 2.4R as tp2 (gross R of the 2-leg approximation + MFE in R)."""
    shown = sel[sel.id >= 0].copy()
    shown["key"] = shown.tf + "#" + shown.id.astype(int).astype(str)
    shown["month"] = shown.t.dt.strftime("%Y-%m")
    first = shown.sort_values("t").drop_duplicates("key").set_index("key")
    traded = set(tr.key)
    filt: dict[str, str] = {}
    for k, why in sim.filtered:
        filt.setdefault(k, why)
    rp = PlanReplayer(sim.open_, sim.high, sim.low, sim.close, sim.spread, partial_r=0.6, partial_frac=0.25, tp2_r=2.4)
    idx = sim.idx
    rows = []
    for k, why in filt.items():
        if k in traded or k not in first.index:
            continue
        p = first.loc[k]
        if p.month not in months:
            continue
        buy = p.direction == "bullish"
        limit = float(p.top if buy else p.bottom)
        sl = float(p.bottom if buy else p.top)
        m0 = int(np.searchsorted(idx, np.datetime64(p.t)))
        tfm = {"M5": 5, "M10": 10, "M15": 15, "M30": 30, "H1": 60}[p.tf]
        r = rp.replay(buy, limit, sl, m0, min(sim.n - 1, m0 + 300 * tfm), min(sim.n - 1, m0 + 300 * tfm + 3 * 1440))
        rows.append({"key": k, "tf": p.tf, "month": p.month, "side": "buy" if buy else "sell", "quality": p.quality,
                     "zone_usd": round(limit - sl if buy else sl - limit, 2), "zone_atr": round(abs(limit - sl) / p.atr, 2),
                     "reason": why, "filled": r.filled, "outcome": r.outcome, "r_gross": round(r.r_gross, 3) if r.filled else np.nan,
                     "mfe_r": round(r.mfe_r, 2), "through": r.through_at_start})
    return pd.DataFrame(rows)


def clusters(t: pd.DataFrame, window_min: int = 30) -> pd.DataFrame:
    """Stops that close within `window_min` of another stop (correlated losses)."""
    s = t[t.outcome == "sl"].sort_values("close_time")
    rows = []
    ct = s.close_time.to_numpy()
    for i in range(len(s)):
        near = np.abs((ct - ct[i]).astype("timedelta64[m]").astype(int)) <= window_min
        if near.sum() > 1:
            rows.append({"key": s.iloc[i].key, "tf": s.iloc[i].tf, "side": s.iloc[i].side, "close_time": s.iloc[i].close_time,
                         "month": s.iloc[i].month, "n_in_cluster": int(near.sum()), "confluent": s.iloc[i].confluent})
    return pd.DataFrame(rows)


def ladder_month(t: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for mo, g in t.groupby("month"):
        rows.append({"month": mo, "n": len(g), "R": round(g.r_net.sum(), 2), "reach_0.6R_%": round(100 * (g.mfe_r >= 0.6).mean(), 1),
                     "reach_1.2R_%": round(100 * (g.mfe_r >= 1.2).mean(), 1), "reach_2.4R_%": round(100 * (g.mfe_r >= 2.4).mean(), 1),
                     "reach_4.8R_%": round(100 * (g.mfe_r >= 4.8).mean(), 1), "sl_%": round(100 * (g.outcome == "sl").mean(), 1),
                     "tp2_%": round(100 * (g.outcome == "tp2").mean(), 1), "mfe_med": round(g.mfe_r.median(), 2),
                     "legs_closed_avg": round(g.legs_closed.mean(), 2), "day_range_R_med": round(g.day_range_R.median(), 1),
                     "sl_after_partial_%": round(100 * ((g.outcome == "sl") & (g.mfe_r >= 0.6)).mean(), 1),
                     "R_if_flat_1R": round(((g.outcome != "sl") * 1.0 - (g.outcome == "sl") * 1.0).sum(), 1)})
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="data/xauusd_m1.csv")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    pd.set_option("display.width", 260)
    pd.set_option("display.max_columns", 60)
    pd.set_option("display.max_rows", 400)
    m1, sel = load_year(a.csv)
    sim, res, s = run_ref(m1, sel)
    json.dump(s, open(OUT / "ref.json", "w"), indent=1, default=str)
    t = enrich(res.trades, m1)
    t.to_csv(OUT / "trades.csv", index=False)

    # --- 1. by month
    bm = pd.DataFrame([{"month": mo, **agg(g), "confluent_n": int(g.confluent.sum()), "confluent_R": round(g[g.confluent].r_net.sum(), 2),
                        "M5_n": int((g.tf == "M5").sum()), "M10_n": int((g.tf == "M10").sum()),
                        "buy_R": round(g[g.side == "buy"].r_net.sum(), 2), "sell_R": round(g[g.side == "sell"].r_net.sum(), 2),
                        "with_trend_R": round(g[g.trend_align == "with"].r_net.sum(), 2),
                        "counter_R": round(g[g.trend_align == "counter"].r_net.sum(), 2),
                        "mom4h_with_R": round(g[g.mom4h_dir == "with"].r_net.sum(), 2),
                        "mom4h_counter_R": round(g[g.mom4h_dir == "counter"].r_net.sum(), 2)}
                       for mo, g in t.groupby("month")])
    bm.to_csv(OUT / "by_month.csv", index=False)
    print("\n=== BY MONTH (v12-A) ===\n", bm.to_string(index=False))

    # --- 2. slices
    dims = ["tf", "side", "session", "kind", "outcome", "confluent", "q_bucket", "zone_atr_bucket", "hold_bucket", "cost_bucket",
            "dow", "trend_align", "mom4h_dir", "ema20_slope_up", "ema20_above_50", "legs_closed"]
    sl = slices(t, dims)
    for d, df in sl.items():
        df.to_csv(OUT / f"slices_{d}.csv", index=False)
    print("\n=== SLICES: weak months vs good months (n / R / win) ===")
    for d in dims:
        df = sl[d]
        print(f"\n-- {d}")
        print(df[["value", "all_n", "all_R", "all_win_%", "weak_n", "weak_R", "weak_win_%", "apr26_n", "apr26_R", "sep25_n", "sep25_R",
                  "good_n", "good_R", "good_win_%", "OOS_n", "OOS_R"]].to_string(index=False))

    # --- 3. regime
    rg = regime(m1)
    rg = rg.join(bm.set_index("month")[["n", "R", "net_$", "win_%", "sl_%", "tp2_%"]], how="left")
    rg.to_csv(OUT / "regime.csv")
    print("\n=== REGIME per month (M1 bars) + result ===\n", rg.to_string())
    num = rg.dropna(subset=["R"])
    num = num[num.days >= 15]
    print("\nSpearman(regime feature, monthly R) over full months:")
    for c in ("range_%", "trend_eff", "avg_day_rng_%", "daily_vol_pct", "chop", "ema20_flips", "spread", "chg_%"):
        print(f"  {c:>15}: {num[c].corr(num.R, method='spearman'):+.2f}")

    # --- 4. funnel per month
    fm = funnel_month(sim, sel, t)
    fm.to_csv(OUT / "funnel_month.csv", index=False)
    print("\n=== FUNNEL per month x tf (unique POIs first shown in the month) ===\n", fm.to_string(index=False))
    tot = fm.groupby("month")[[c for c in fm.columns if c not in ("month", "tf", "zone_usd_med", "zone_atr_med", "q_med")]].sum()
    print("\n-- all TFs\n", tot.to_string())

    # --- 5. replay of the filtered POIs in the weak months
    fr = replay_filtered(sim, sel, m1, t)
    fr.to_csv(OUT / "filtered_replay.csv", index=False)
    if len(fr):
        f2 = fr[fr.filled & ~fr.through]
        print("\n=== FILTERED POIs of the weak months, replayed (2-leg approx 0.6R/25% + 2.4R) ===")
        print(f2.groupby(["month", "tf", "reason"]).agg(n=("key", "size"), r_gross=("r_gross", "sum"), win=("r_gross", lambda x: round(100 * (x > 0).mean(), 1)),
                                                        mfe_med=("mfe_r", "median"), reach1_2=("mfe_r", lambda x: round(100 * (x >= 1.2).mean(), 1)),
                                                        q_med=("quality", "median"), zone_atr_med=("zone_atr", "median")).round(2).to_string())
        print("\n-- by month x tf x quality bucket")
        f2 = f2.assign(qb=pd.cut(f2.quality, [0, 0.5, 0.55, 0.57, 0.6, 1], labels=["<0.50", "0.50-0.55", "0.55-0.57", "0.57-0.60", ">=0.60"]))
        print(f2.groupby(["month", "tf", "qb"], observed=True).agg(n=("key", "size"), r_gross=("r_gross", "sum"),
                                                                    win=("r_gross", lambda x: round(100 * (x > 0).mean(), 1))).round(2).to_string())

    # --- 6. clusters, ladder, daily
    cl = clusters(t)
    cl.to_csv(OUT / "clusters.csv", index=False)
    print("\n=== STOP CLUSTERS (2+ stops within 30 min) per month ===")
    if len(cl):
        print(cl.groupby("month").agg(stops_in_clusters=("key", "size"), clusters_confluent=("confluent", "sum")).to_string())
    lm = ladder_month(t)
    lm.to_csv(OUT / "ladder_month.csv", index=False)
    print("\n=== LADDER per month: how far do trades run? ===\n", lm.to_string(index=False))
    eq = res.equity.equity
    daily = eq.resample("1D").last().dropna().pct_change().mul(100).dropna()
    daily = daily[daily != 0]
    dd = pd.DataFrame({"day_ret_%": daily.round(2)})
    dd["month"] = dd.index.strftime("%Y-%m")
    dsum = dd.groupby("month").agg(days=("day_ret_%", "size"), pos_days=("day_ret_%", lambda x: int((x > 0).sum())),
                                   worst=("day_ret_%", "min"), best=("day_ret_%", "max"), sum=("day_ret_%", "sum")).round(2)
    dsum.to_csv(OUT / "daily_month.csv")
    print("\n=== DAILY P&L per month ===\n", dsum.to_string())
    print("\nworst days of the weak months:")
    print(dd[dd.month.isin(WEAK)].sort_values("day_ret_%").head(8).to_string())
    print("\nDONE -> study_results/v13_diag/")


if __name__ == "__main__":
    main()
