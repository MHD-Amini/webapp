#!/usr/bin/env python3
"""v11 step 1 - FUNNEL DIAGNOSIS: where do the scanner's POIs get lost before they become trades?

Runs the v10 reference trader (G ladder, v8 filter, loss rules) on the full-year streams Sep 2025 -> Sep 2026 and
attributes every unique POI shown by the scanner to the LAST stage it reached:

    shown -> accepted (order placed) -> filled -> closed trade
          \\-> skipped: quality filtered / trade filter (cost, quality, session) / poi already traded / overlaps /
                       price already through entry / too small to size / margin
          \\-> cancelled before fill: no longer shown (mirror) / replaced / max open positions at fill time

Outputs: study_results/v11_funnel.csv (per TF x stage), v11_funnel_reasons.csv (detailed reasons per TF),
         v11_funnel_ref.json (the reference run summary - must reproduce v10: 251 trades, +80.74 %, DD -5.49 %).
    python run_v11_funnel.py --csv data/xauusd_m1.csv
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backtest_trader import load_selections  # noqa: E402
from lubot import load_mt5_csv  # noqa: E402
from lubot.execution import SymbolSpec, TraderConfig  # noqa: E402
from lubot.portfolio_sim import PortfolioSimulator  # noqa: E402
from run_rm_study import FLT  # noqa: E402
from run_v10_study import BASE  # noqa: E402

TFS = ("M5", "M10", "M15", "M30", "H1")
G_LADDER = "tp_levels=0.6|1.2|2.4|4.8,tp_fracs=1|1|1|1"
RULES = "max_daily_loss_pct=4.5,max_total_loss_pct=9.0"
REF = ",".join([BASE, G_LADDER, RULES])


def load_year(csv: str, start: str = "2025-09-01"):
    m1 = load_mt5_csv(csv)[start:]
    sel = pd.concat([load_selections(f"study_results/sel_v10_{tf}.pkl") for tf in TFS],
                    ignore_index=True).sort_values("t", kind="stable").reset_index(drop=True)
    return m1, sel


def funnel(sim, sel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Attribute every unique POI (tf#id) to the furthest stage it reached."""
    shown = sel[sel.id >= 0].copy()
    shown["key"] = shown.tf + "#" + shown.id.astype(int).astype(str)
    keys_by_tf = {tf: set(shown[shown.tf == tf].key) for tf in TFS}
    traded = {p.plan.key for p in sim.closed} | set(sim.positions)
    filled_keys = traded
    cancelled = defaultdict(Counter)          # key -> Counter(reason)
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
        st = Counter()
        rs = Counter()
        for k in keys_by_tf[tf]:
            if k in filled_keys:
                st["traded"] += 1
                continue
            if k in cancelled:
                st["order placed, never filled"] += 1
                for r, n in cancelled[k].items():
                    rs[f"cancel: {r}"] += 1 if n else 0
                continue
            if k in skipped:
                # the POI was shown, maybe several times; report the most frequent skip reason
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="data/xauusd_m1.csv")
    a = ap.parse_args()
    out = Path("study_results")
    m1, sel = load_year(a.csv)
    tcfg = TraderConfig().override(REF)
    tcfg.trade_filter = FLT
    sim = PortfolioSimulator(m1, sel, tcfg, SymbolSpec())
    res = sim.run(progress=True)
    s = res.summary()
    print(json.dumps({k: s[k] for k in ("trades", "return_%", "max_dd_%", "profit_factor", "win_%", "pending_placed", "cancelled", "skipped")}, indent=1))
    json.dump(s, open(out / "v11_funnel_ref.json", "w"), indent=1, default=str)
    f, r = funnel(sim, sel)
    f.to_csv(out / "v11_funnel.csv", index=False)
    r.to_csv(out / "v11_funnel_reasons.csv", index=False)
    pd.set_option("display.width", 200)
    print("\n=== FUNNEL (unique POIs shown by the scanner, full year) ===")
    print(f.to_string(index=False))
    print("\n=== detailed reasons ===")
    print(r.to_string(index=False))
    # totals
    tot = f.groupby("stage").pois.sum().sort_values(ascending=False)
    print("\n=== all TFs ===")
    print(tot.to_string())
    # extra: quality distribution of the shown POIs vs the traded ones
    shown = sel[sel.id >= 0].drop_duplicates(["tf", "id"])
    tr = res.trades
    print("\nquality quantiles shown:", shown.quality.quantile([.1, .25, .5, .75, .9]).round(3).to_dict())
    if len(tr):
        print("quality quantiles traded:", tr.quality.quantile([.1, .25, .5, .75, .9]).round(3).to_dict())
        print("\ntrades by tf:\n", res.by("tf").to_string())
        print("\ncancel reasons (orders):\n", res.cancel_reasons().to_string())
        print("\nskip reasons (events):\n", res.skipped_reasons().to_string())
        print("\nfilter reasons (events):\n", res.filter_reasons().to_string())


if __name__ == "__main__":
    main()
