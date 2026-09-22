#!/usr/bin/env python3
"""v12 step 1 - BASELINE + FUNNEL of the v11-B reference (the trader shipped in run_trader.bat).

Reference = v10 trader + v11 levers: G ladder 25 % x4 @ 0.6/1.2/2.4/4.8R (BE after leg 1), loss rules 4.5 % / 9 %,
dedupe_cross_tf=false, v8 filter with M30|H1 min_quality 0.57.  Full year Sep 2025 -> Sep 2026 on the sel_v10 streams.
Must reproduce the v11 study: 348 trades, +147.93 %, max DD -5.22 %, PF 1.91, win 71.6 %.

Then it attributes every unique POI shown by the scanner to the LAST stage it reached (as v11's funnel did) and adds the
v12-specific measurements:
  (a) 'price already at/through entry' skips - how many POIs, and did the price come back in front of the zone later
      while the POI was still shown (-> lever `defer_entry`)?
  (b) orders cancelled 'replaced' - was the replaced POI later shown again / would it have filled (-> `keep_replaced`)?
  (c) quality-gate rejects whose zone overlaps an ACTIVE plan of another timeframe (confluence candidates ->
      `confluence_quality`), with their would-be outcome measured by a plan replay
  (d) traded POIs that were re-shown by the scanner after the trade closed at BE / partial (-> `reentry`)
  (e) filled trades: the cost_r / quality distribution of the winners vs the losers per TF (what to relax where)

Outputs: study_results/v12_funnel_ref.json, v12_funnel.csv, v12_funnel_reasons.csv, v12_funnel_extra.json
    python run_v12_funnel.py --csv data/xauusd_m1.csv
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
from backtest_trader import load_selections  # noqa: E402
from lubot import load_mt5_csv  # noqa: E402
from lubot.execution import SymbolSpec, TraderConfig  # noqa: E402
from lubot.portfolio_sim import PortfolioSimulator  # noqa: E402
from run_v10_study import BASE  # noqa: E402

TFS = ("M5", "M10", "M15", "M30", "H1")
G_LADDER = "tp_levels=0.6|1.2|2.4|4.8,tp_fracs=1|1|1|1"
RULES = "max_daily_loss_pct=4.5,max_total_loss_pct=9.0"
V11B_T = "dedupe_cross_tf=false"
REF_T = ",".join([BASE, G_LADDER, RULES, V11B_T])
# v11-B filter (run_trader.bat)
REF_FLT = "M5:max_cost_r=0.08;min_quality=0.55;sessions=asia|london|preny|ny|lclose/M10|M15:min_quality=0.60/M30|H1:min_quality=0.57"
OOS_SPLIT = "2026-03-01"
OUT = Path("study_results")


def load_year(csv: str, start: str = "2025-09-01"):
    m1 = load_mt5_csv(csv)[start:]
    sel = pd.concat([load_selections(f"study_results/sel_v10_{tf}.pkl") for tf in TFS],
                    ignore_index=True).sort_values("t", kind="stable").reset_index(drop=True)
    return m1, sel


def ref_config() -> TraderConfig:
    t = TraderConfig().override(REF_T)
    t.trade_filter = REF_FLT
    return t


def funnel(sim, sel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Attribute every unique POI (tf#id) to the furthest stage it reached."""
    shown = sel[sel.id >= 0].copy()
    shown["key"] = shown.tf + "#" + shown.id.astype(int).astype(str)
    keys_by_tf = {tf: set(shown[shown.tf == tf].key) for tf in TFS}
    traded = {p.plan.key for p in sim.closed} | set(sim.positions)
    cancelled = defaultdict(Counter)
    for c in sim.cancelled:
        cancelled[c.plan.key][c.reason_cancel] += 1
    skipped = defaultdict(Counter)
    for k, why in sim.skipped:
        skipped[k][why] += 1
    filtered = defaultdict(Counter)
    for k, why in sim.filtered:
        filtered[k][why] += 1
    rows, reasons = [], []
    for tf in TFS:
        st, rs = Counter(), Counter()
        for k in keys_by_tf[tf]:
            if k in traded:
                st["traded"] += 1
                continue
            if k in cancelled:
                st["order placed, never filled"] += 1
                for r in cancelled[k]:
                    rs[f"cancel: {r}"] += 1
                continue
            if k in skipped:
                why, _ = skipped[k].most_common(1)[0]
                if why == "trade filter":
                    fw = filtered[k].most_common(1)[0][0] if k in filtered else "?"
                    st["skipped: trade filter"] += 1
                    rs[f"filter: {fw}"] += 1
                else:
                    st[f"skipped: {why}"] += 1
                    rs[f"skip: {why}"] += 1
                continue
            st["never reached the trader (plan None)"] += 1
        tot = len(keys_by_tf[tf])
        for stage, n in st.most_common():
            rows.append({"tf": tf, "stage": stage, "pois": n, "pct_of_shown": round(100 * n / tot, 1), "shown": tot})
        for r, n in rs.most_common():
            reasons.append({"tf": tf, "reason": r, "pois": n, "pct_of_shown": round(100 * n / tot, 1)})
    return pd.DataFrame(rows), pd.DataFrame(reasons)


def extra_measurements(sim, sel: pd.DataFrame, m1: pd.DataFrame, res) -> dict:
    """The v12-specific questions (a)-(e)."""
    out: dict = {}
    shown = sel[sel.id >= 0].copy()
    shown["key"] = shown.tf + "#" + shown.id.astype(int).astype(str)
    tr = res.trades
    traded_keys = set(tr.key) if len(tr) else set()
    # --- (a) price already at/through entry: POIs skipped for that reason that never traded
    skipped = defaultdict(list)
    for k, why in sim.skipped:
        skipped[k].append(why)
    at_entry = [k for k, ws in skipped.items() if any(w.startswith("price already") for w in ws) and k not in traded_keys]
    out["a_price_through_entry_pois"] = len(at_entry)
    out["a_by_tf"] = dict(Counter(k.split("#")[0] for k in at_entry))
    # how many of those were shown for >= 2 consecutive set events (i.e. the scanner kept showing them -> a later chance)
    ev_per_key = shown.groupby("key").size()
    out["a_shown_ge2_events"] = int(sum(1 for k in at_entry if ev_per_key.get(k, 0) >= 2))
    # --- (b) replaced orders: never-filled POIs whose LAST cancel reason was 'replaced'
    last_cancel = {}
    for c in sim.cancelled:
        last_cancel[c.plan.key] = c.reason_cancel
    replaced = [k for k, r in last_cancel.items() if r == "replaced" and k not in traded_keys]
    no_longer = [k for k, r in last_cancel.items() if r == "no longer shown" and k not in traded_keys]
    out["b_replaced_pois"] = len(replaced)
    out["b_no_longer_shown_pois"] = len(no_longer)
    out["b_replaced_by_tf"] = dict(Counter(k.split("#")[0] for k in replaced))
    # was a replaced POI shown again later (the scanner came back to it)?
    first_t = shown.groupby("key").t.min()
    last_t = shown.groupby("key").t.max()
    canc_t = {}
    for c in sim.cancelled:
        if c.reason_cancel == "replaced":
            canc_t[c.plan.key] = c.placed
    re_shown = sum(1 for k in replaced if k in last_t and last_t[k] > canc_t.get(k, last_t[k]))
    out["b_replaced_then_reshown"] = int(re_shown)
    # --- (c) quality-gate rejects overlapping an active plan of another TF at the time of rejection
    # (approximation from the recorded events: a shown POI of tf A rejected on quality whose zone overlaps >= 50 % with
    #  a POI of tf B that was traded (filled) within +-1 day)
    filt = defaultdict(list)
    for k, why in sim.filtered:
        filt[k].append(why)
    qrej = {k for k, ws in filt.items() if any("quality" in w for w in ws) and k not in traded_keys}
    if len(tr):
        trz = tr[["key", "tf", "side", "zone_top", "zone_bottom", "entry_time", "close_time"]].copy()
        pois = shown.drop_duplicates("key").set_index("key")
        conf = []
        for k in qrej:
            if k not in pois.index:
                continue
            p = pois.loc[k]
            side = "buy" if p.direction == "bullish" else "sell"
            cand = trz[(trz.tf != p.tf) & (trz.side == side)]
            if not len(cand):
                continue
            lo = np.maximum(cand.zone_bottom.values, p.bottom)
            hi = np.minimum(cand.zone_top.values, p.top)
            inter = np.clip(hi - lo, 0, None)
            frac = inter / max(p.top - p.bottom, 1e-9)
            near = (cand.entry_time.values >= np.datetime64(p.t) - np.timedelta64(2, "D")) & \
                   (cand.entry_time.values <= np.datetime64(p.t) + np.timedelta64(2, "D"))
            if ((frac >= 0.5) & near).any():
                conf.append((k, float(p.quality)))
        out["c_quality_rejects"] = len(qrej)
        out["c_quality_rejects_confluent_with_a_trade"] = len(conf)
        out["c_confluent_by_tf"] = dict(Counter(k.split("#")[0] for k, _ in conf))
        out["c_confluent_quality_quantiles"] = pd.Series([q for _, q in conf]).quantile([.1, .25, .5, .75, .9]).round(3).to_dict() if conf else {}
    # --- (d) traded POIs re-shown after the trade closed
    if len(tr):
        reshown_after = []
        for _, r in tr.iterrows():
            ev = shown[(shown.key == r.key) & (shown.t > r.close_time)]
            if len(ev):
                reshown_after.append((r.key, r.outcome, len(ev)))
        out["d_traded_pois_reshown_after_close"] = len(reshown_after)
        out["d_reshown_by_outcome"] = dict(Counter(o for _, o, _ in reshown_after))
        out["d_reshown_by_tf"] = dict(Counter(k.split("#")[0] for k, _, _ in reshown_after))
    # --- (e) traded population: quality / zone-size vs outcome per TF
    if len(tr):
        t2 = tr.assign(zone_usd=tr.zone_top - tr.zone_bottom, win=tr.net > 0)
        g = t2.groupby(["tf", "win"]).agg(n=("net", "size"), q_med=("quality", "median"), zone_med=("zone_usd", "median"),
                                          avg_R=("r_net", "mean")).round(3)
        out["e_traded_by_tf_win"] = {f"{a}|{'win' if b else 'loss'}": v for (a, b), v in g.to_dict("index").items()}
        # OOS half
        oos = t2[t2.close_time >= OOS_SPLIT]
        out["e_oos"] = {"n": int(len(oos)), "R": round(float(oos.r_net.sum()), 2),
                        "PF": round(float(oos[oos.net > 0].net.sum() / abs(oos[oos.net < 0].net.sum())), 3),
                        "win_%": round(100 * float((oos.net > 0).mean()), 1)}
        # how many trades per calendar month and the gaps between trades (where are the idle periods?)
        out["e_trades_per_month"] = t2.groupby(t2.close_time.dt.strftime("%Y-%m")).size().to_dict()
        gaps = t2.sort_values("entry_time").entry_time.diff().dt.total_seconds().div(3600).dropna()
        out["e_gap_hours_quantiles"] = gaps.quantile([.5, .75, .9, .95, .99]).round(1).to_dict()
        out["e_concurrent_max"] = int(max(1, _max_concurrent(t2)))
    return out


def _max_concurrent(tr: pd.DataFrame) -> int:
    ev = sorted([(t, 1) for t in tr.entry_time] + [(t, -1) for t in tr.close_time])
    cur = best = 0
    for _, d in ev:
        cur += d
        best = max(best, cur)
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="data/xauusd_m1.csv")
    a = ap.parse_args()
    m1, sel = load_year(a.csv)
    tcfg = ref_config()
    sim = PortfolioSimulator(m1, sel, tcfg, SymbolSpec())
    res = sim.run(progress=True)
    s = res.summary()
    print(json.dumps({k: s[k] for k in ("trades", "return_%", "max_dd_%", "profit_factor", "win_%", "sl_%", "pending_placed",
                                         "cancelled", "skipped")}, indent=1))
    json.dump(s, open(OUT / "v12_funnel_ref.json", "w"), indent=1, default=str)
    res.trades.to_csv(OUT / "v12_ref_trades.csv", index=False)
    f, r = funnel(sim, sel)
    f.to_csv(OUT / "v12_funnel.csv", index=False)
    r.to_csv(OUT / "v12_funnel_reasons.csv", index=False)
    pd.set_option("display.width", 200)
    print("\n=== FUNNEL (unique POIs shown by the scanner, full year, v11-B reference) ===")
    print(f.to_string(index=False))
    print("\n=== detailed reasons ===")
    print(r.to_string(index=False))
    print("\n=== all TFs ===")
    print(f.groupby("stage").pois.sum().sort_values(ascending=False).to_string())
    ex = extra_measurements(sim, sel, m1, res)
    json.dump(ex, open(OUT / "v12_funnel_extra.json", "w"), indent=1, default=str)
    print("\n=== v12 extra measurements ===")
    print(json.dumps(ex, indent=1, default=str))
    if len(res.trades):
        print("\ntrades by tf:\n", res.by("tf").to_string())
        print("\nskip reasons (events):\n", res.skipped_reasons().to_string())
        print("\ncancel reasons (orders):\n", res.cancel_reasons().to_string())


if __name__ == "__main__":
    main()
