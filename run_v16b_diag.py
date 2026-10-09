#!/usr/bin/env python3
"""v16b step 1 - DIAGNOSIS of the losses of the shipped v16-A trader (study_results/final_v16/v16A_trades.csv).

Where does the stop-out rate (24.4 %) and the $ lost (-22 102 $) come from, and which slices are consistent on BOTH halves
(IS < 2026-03-01 <= OOS)?  Every table is written to study_results/v16b_diag/*.csv and summarised in v16b_diag/DIAG.md.

    python3 run_v16b_diag.py            # ~10 s, reads the CSV year once for the daily trend feature
"""
from __future__ import annotations

import glob
import os
import sys
import warnings

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lubot.data import load_mt5_csv  # noqa: E402
from lubot.trade_filter import ny_session_of  # noqa: E402
from v14_common import OOS_SPLIT  # noqa: E402

warnings.filterwarnings("ignore")
OUT = "study_results/v16b_diag"
TRADES = "study_results/final_v16/v16A_trades.csv"
TF_MIN = {"M5": 5, "M10": 10, "M15": 15, "M20": 20, "M30": 30, "H1": 60}


def agg(d: pd.DataFrame) -> pd.Series:
    return pd.Series({"n": len(d), "sl": int((d.outcome == "sl").sum()),
                      "sl_%": round(100 * (d.outcome == "sl").mean(), 1) if len(d) else np.nan,
                      "win_%": round(100 * (d.net > 0).mean(), 1) if len(d) else np.nan,
                      "net_$": round(d.net.sum()), "gross_loss_$": round(d[d.net < 0].net.sum()),
                      "avg_R": round(d.r_net.mean(), 3) if len(d) else np.nan})


def table(t: pd.DataFrame, by, name: str, lines: list, title: str) -> pd.DataFrame:
    keys = [by] if isinstance(by, str) else list(by)
    g = t.groupby([t[k].rename(f"_{k}") for k in keys], observed=True).apply(agg)
    g.index.names = keys
    g.to_csv(f"{OUT}/{name}.csv")
    lines.append(f"\n### {title}\n")
    lines.append(g.to_markdown())
    return g


def enrich(t: pd.DataFrame, csv: str = "data/xauusd_m1.csv") -> pd.DataFrame:
    """Add the diagnosis features to a trade list (also used by the report)."""
    t = t.copy()
    t["half"] = np.where(t.close_time >= OOS_SPLIT, "OOS", "IS")
    t["age_min"] = (t.entry_time - t.selected_time).dt.total_seconds() / 60
    t["age_bars"] = t.age_min / t.tf.map(TF_MIN)
    t["ny_sess"] = [ny_session_of(x)[0] for x in t.selected_time]
    t["qband"] = pd.cut(t.quality, [0, 0.55, 0.6, 0.65, 0.7, 1.0])
    # daily trend feature: close of the last CLOSED server day vs its SMA(N) (what the live bot can compute at selection time)
    m1 = load_mt5_csv(csv)
    daily = m1["close"].resample("1D").last().dropna()
    prev_day = t.selected_time.dt.normalize() - pd.Timedelta(days=1)
    close_prev = daily.reindex(prev_day, method="ffill").values
    for n in (5, 10, 20, 50):
        sma = daily.rolling(n).mean().reindex(prev_day, method="ffill").values
        t[f"up{n}"] = close_prev > sma
        t[f"counter{n}"] = np.where(t.side == "sell", t[f"up{n}"], ~t[f"up{n}"])
    # distance at selection from the recorded stream
    sel = pd.concat([pd.read_pickle(f) for f in sorted(glob.glob("study_results/sel_v16_*.pkl"))])
    sel = sel[(sel["rank"] <= 1) & (sel.event == "set")].copy()
    sel["key"] = sel.tf + "#" + sel.id.astype(int).astype(str)
    sel["selected_time"] = pd.to_datetime(sel.t)
    t = t.merge(sel[["key", "selected_time", "distance_atr", "candidates"]].drop_duplicates(["key", "selected_time"]),
                on=["key", "selected_time"], how="left")
    t["dist_band"] = pd.cut(t.distance_atr, [-1, 0.5, 1, 2, 4, 100])
    return t


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    t = enrich(pd.read_csv(TRADES, parse_dates=["selected_time", "entry_time", "close_time"]))
    t.to_csv(f"{OUT}/trades_enriched.csv", index=False)

    L = ["# v16b diagnosis - the losses of v16-A (467 trades, Sep 2025 -> Sep 2026)\n",
         f"Reference: {len(t)} trades, net {t.net.sum():.0f} $, gross loss {t[t.net < 0].net.sum():.0f} $, stop-outs "
         f"{(t.outcome == 'sl').sum()} ({100 * (t.outcome == 'sl').mean():.1f} %), win {100 * (t.net > 0).mean():.1f} %.  "
         f"IS/OOS split {OOS_SPLIT}.  Every table: n, stop-outs, stop-out %, win %, net $, gross loss $, mean R."]
    sl = t[t.outcome == "sl"]
    L.append("\n## 1. Where the stop-outs are\n")
    table(t, "outcome", "by_outcome", L, "by outcome")
    table(t, "tf", "by_tf", L, "by timeframe")
    table(t, "side", "by_side", L, "by side")
    table(t, ["half", "side"], "by_half_side", L, "by half x side")
    table(t, ["tf", "side"], "by_tf_side", L, "by timeframe x side")
    table(t, ["side", "confluent"], "by_side_confluent", L, "by side x confluent")
    table(t, ["side", "regime"], "by_side_regime", L, "by side x regime")
    table(t, ["half", "side", "regime"], "by_half_side_regime", L, "by half x side x regime")
    table(t, ["side", "kind"], "by_side_kind", L, "by side x zone kind")
    table(t, "qband", "by_quality", L, "by quality band")
    table(t, "ny_sess", "by_session", L, "by NY session of the selection")
    table(t, ["side", "ny_sess"], "by_side_session", L, "by side x NY session")
    table(t, "mart_step", "by_mart_step", L, "by martingale step (-1 = stepped DOWN x0.5 after a loss)")
    table(t, "risk_scale", "by_risk_scale", L, "by risk scale (0.9 plain, 1.25 confluent, 0.5 M20)")
    table(t, "month", "by_month", L, "by month")

    L.append("\n## 2. Counter-trend plans (daily close of the last closed day vs SMA N)\n")
    for n in (5, 10, 20, 50):
        table(t, ["side", f"up{n}"], f"by_side_up{n}", L, f"side x (close > SMA{n})")
    for n in (10, 20):
        table(t, ["half", "side", f"up{n}"], f"by_half_side_up{n}", L, f"half x side x (close > SMA{n})")
    L.append("\n### what removing the counter-trend SELLS would do (static, before re-simulation)\n")
    rows = []
    for n in (5, 10, 20, 50):
        for label, drop in ((f"skip sells when close > SMA{n}", (t.side == "sell") & t[f"up{n}"]),
                            (f"skip BOTH sides counter-trend SMA{n}", t[f"counter{n}"])):
            keep = t[~drop]
            rows.append({"rule": label, "dropped": int(drop.sum()), "dropped_sl": int((t[drop].outcome == "sl").sum()),
                         "dropped_net_$": round(t[drop].net.sum()), "dropped_IS_net_$": round(t[drop & (t.half == "IS")].net.sum()),
                         "dropped_OOS_net_$": round(t[drop & (t.half == "OOS")].net.sum()),
                         "remaining_n": len(keep), "remaining_sl_%": round(100 * (keep.outcome == "sl").mean(), 1),
                         "remaining_net_$": round(keep.net.sum()), "remaining_gross_loss_$": round(keep[keep.net < 0].net.sum())})
    ct = pd.DataFrame(rows)
    ct.to_csv(f"{OUT}/counter_trend_static.csv", index=False)
    L.append(ct.to_markdown(index=False))

    L.append("\n## 3. Fast fills = impulsive arrival (minutes from order placement to fill)\n")
    t["age_band"] = pd.cut(t.age_min, [-1, 2, 5, 10, 15, 30, 60, 180, 1e9])
    table(t, "age_band", "by_age", L, "by pending age (minutes)")
    table(t, ["half", "age_band"], "by_half_age", L, "half x pending age")
    t["age_bars_band"] = pd.cut(t.age_bars, [-0.01, 0.5, 1, 2, 4, 8, 1e9])
    table(t, "age_bars_band", "by_age_bars", L, "by pending age in bars of the plan's own timeframe")
    table(t[t.age_min <= 5], "tf", "fast_by_tf", L, "fills within 5 min, by timeframe")
    table(t[t.age_min <= 5], ["half", "side"], "fast_by_half_side", L, "fills within 5 min, by half x side")
    table(t[t.age_min <= 5], "regime", "fast_by_regime", L, "fills within 5 min, by regime")
    table(t, "dist_band", "by_distance", L, "by distance of the zone at selection (ATR)")
    table(t, ["half", "dist_band"], "by_half_distance", L, "half x distance at selection")
    L.append(f"\ncorrelation(age_min, distance_atr) = {t[['age_min', 'distance_atr']].corr().iloc[0, 1]:.2f} (the fast fill is not simply the near zone)")

    L.append("\n## 4. The path of the stop-outs (how far did price go in our favour first?)\n")
    rows = []
    for x in (0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5):
        m = sl.mfe_r >= x
        rows.append({"MFE >= R": x, "stop_outs": int(m.sum()), "share_%": round(100 * m.mean(), 1), "net_$": round(sl[m].net.sum()),
                     "IS": int((m & (sl.half == "IS")).sum()), "OOS": int((m & (sl.half == "OOS")).sum())})
    mf = pd.DataFrame(rows)
    mf.to_csv(f"{OUT}/sl_mfe.csv", index=False)
    L.append(mf.to_markdown(index=False))
    L.append("\n### the winners' adverse excursion (a BE trigger at x R also costs the winners that first went to +x then back to entry)\n")
    w = t[t.outcome != "sl"]
    rows = []
    for x in (0.3, 0.5, 0.6, 0.7, 0.8, 0.9):
        m = w.mae_r >= x
        rows.append({"MAE >= R": x, "non_sl_trades": int(m.sum()), "share_%": round(100 * m.mean(), 1), "net_$": round(w[m].net.sum())})
    pd.DataFrame(rows).to_csv(f"{OUT}/winners_mae.csv", index=False)
    L.append(pd.DataFrame(rows).to_markdown(index=False))
    g = sl.assign(hold_band=pd.cut(sl.hold_min, [-1, 2, 5, 15, 60, 240, 1e9])).groupby("hold_band", observed=True).agg(
        n=("net", "size"), net_usd=("net", "sum"), mean_mfe_r=("mfe_r", "mean")).round(2)
    g.to_csv(f"{OUT}/sl_by_hold.csv")
    L.append("\n### stop-outs by holding time (minutes)\n")
    L.append(g.to_markdown())

    L.append("\n## 5. Clustering\n")
    t["day"] = t.close_time.dt.date
    d = t.groupby("day").agg(n=("net", "size"), sl=("outcome", lambda s: int((s == "sl").sum())), net=("net", "sum"))
    g = d.groupby("sl").agg(days=("n", "size"), net_usd=("net", "sum"), mean_net_usd=("net", "mean")).round(0)
    g.to_csv(f"{OUT}/days_by_stops.csv")
    L.append("\n### days by number of stop-outs\n")
    L.append(g.to_markdown())
    L.append("\n### worst 10 days (closed trades)\n")
    L.append(d.sort_values("net").head(10).round(0).to_markdown())
    cnt = []
    for _, r in t.iterrows():
        cnt.append(int(((t.entry_time < r.entry_time) & (t.close_time > r.entry_time) & (t.side == r.side)).sum()))
    t["same_side_open"] = cnt
    table(t, "same_side_open", "by_same_side_open", L, "by number of same-side positions open at the fill (more = confluence, better)")

    # ---- candidate levers (static estimates; the simulator decides)
    L.append("\n## 6. Candidate levers (static estimate on the trade list; the grid re-simulates every one)\n")
    cands = []

    def cand(name, mask, how="skip", scale=0.5):
        d = t[mask]
        row = {"lever": name, "trades_affected": len(d), "stops_affected": int((d.outcome == "sl").sum()),
               "IS_net_$_affected": round(d[d.half == "IS"].net.sum()), "OOS_net_$_affected": round(d[d.half == "OOS"].net.sum())}
        if how == "skip":
            keep = t[~mask]
            row.update({"new_sl_%": round(100 * (keep.outcome == "sl").mean(), 1), "new_net_$": round(keep.net.sum()),
                        "new_gross_loss_$": round(keep[keep.net < 0].net.sum())})
        else:
            row.update({"new_sl_%": round(100 * (t.outcome == "sl").mean(), 1),
                        "new_net_$": round(t.net.sum() - (1 - scale) * d.net.sum()),
                        "new_gross_loss_$": round(t[t.net < 0].net.sum() - (1 - scale) * d[d.net < 0].net.sum())})
        cands.append(row)
    cand("skip sells when daily close > SMA10", (t.side == "sell") & t.up10)
    cand("skip sells when daily close > SMA20", (t.side == "sell") & t.up20)
    cand("skip counter-trend both sides SMA20", t.counter20)
    cand("scale sells x0.5", t.side == "sell", "scale", 0.5)
    cand("scale counter-trend sells x0.5 (SMA20)", (t.side == "sell") & t.up20, "scale", 0.5)
    cand("skip fills within 5 min of placement", t.age_min <= 5)
    cand("skip fills within 3 min of placement", t.age_min <= 3)
    cand("skip fills within 0.5 bar of own TF", t.age_bars <= 0.5)
    cand("skip zones closer than 0.5 ATR at selection", t.distance_atr <= 0.5)
    cand("skip range-regime sells", (t.side == "sell") & (t.regime == "range"))
    cand("scale range-regime sells x0.5", (t.side == "sell") & (t.regime == "range"), "scale", 0.5)
    cand("skip step-down (mart -1) plans", t.mart_step == -1)
    cand("skip sells SMA10 + fills <= 5 min", ((t.side == "sell") & t.up10) | (t.age_min <= 5))
    cand("skip sells SMA20 + fills <= 5 min", ((t.side == "sell") & t.up20) | (t.age_min <= 5))
    c = pd.DataFrame(cands)
    c.to_csv(f"{OUT}/candidates_static.csv", index=False)
    L.append(c.to_markdown(index=False))
    L.append("\nReading: the two slices that lose on BOTH halves and are visible BEFORE the order is placed / filled are (a) SELLS AGAINST "
             "THE DAILY TREND (stop rate 35-45 %, ~0 $ net over the year) and (b) IMPULSIVE ARRIVALS (orders filled within minutes of "
             "placement: 39 % stop, -2 k$).  Post-fill, half of the stop-outs first went >= +0.2 R (a BE trigger below TP1 can turn some of "
             "them into scratches, at the cost of the winners that retrace).  The simulator (step 2 levers, step 3 grid) decides; sizing is "
             "equity-based so every removed trade changes the later sizes.")
    with open(f"{OUT}/DIAG.md", "w") as f:
        f.write("\n".join(L) + "\n")
    print(c.to_string())
    print(f"\nwritten: {OUT}/DIAG.md + {len(glob.glob(OUT + '/*.csv'))} csv")


if __name__ == "__main__":
    main()
