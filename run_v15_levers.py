#!/usr/bin/env python3
"""v15 step 3 - LEVER GRID on top of v14-A (the trader shipped in run_trader.bat): MORE TRADES and MORE PROFIT at the SAME LOSS
PERCENTAGE.

Reference (v14-A, full year Sep25-Sep26): 430 trades, net +22 753 $, OOS net +14 524 $, max DD 5.84 %, PF 2.249, win 74.7 %, stop-outs
24.9 %, worst day -1.99 % eq, OOS PF 2.15, 13/13 months.

Families (every run = full year through the M1 portfolio simulator, ~15 s, ~400 MB):
  CS_<conf>_<plain>            conviction sizing: confluent plans x conf, plain plans x plain
  CM_<min>[_open|_pend]        confluence memory: a plan of another TF active within the last <min> minutes counts as confluence
  TIER_<name>_<scale>          tiered admission: tight second bar at reduced risk
  DD_*                         drawdown buy-backs used with conviction sizing: max_open 3, range_risk_scale, mart cap 2 %
  CMB_*                        combinations: memory x conviction x buy-back (x tier)
Judge (v15_common.judge15): more_trades (n > 430), more_profit (net AND OOS net above ref), hold_loss (stop-rate <= +2 pt, win >= -3 pt,
max DD <= +0.5 pt, worst day >= -0.5 pt, PF >= -0.10), hold_oos (the same on the OOS half).  score = sum of the four.
Resumable: one json per variant in study_results/v15_levers/, summary -> study_results/v15_levers.csv (rewritten every 5 runs).

    nohup bash run_v15_all.sh > logs/v15_all.log 2>&1 &            # grid + autosave
    python3 run_v15_levers.py --stress name1,name2                 # 6 stress scenarios each -> v15_stress.csv
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backtest_trader import spec_override  # noqa: E402
from lubot.execution import SymbolSpec  # noqa: E402
from lubot.portfolio_sim import PortfolioSimulator  # noqa: E402
from run_v12_levers import STRESS  # noqa: E402
from v14_common import CSV, load_year  # noqa: E402
from v15_common import fmt15, judge15, v14a_config  # noqa: E402

OUT = Path("study_results/v15_levers")
TIERS = {
    "m10q55": "M10:min_quality=0.55",                                        # M10 0.55-0.57 (the only positive quality band)
    "m10q53": "M10:min_quality=0.53",
    "htfq55": "M10:min_quality=0.55/M15:min_quality=0.57/M30|H1:min_quality=0.55",
    "m5c12": "M5:max_cost_r=0.12;min_quality=0.57;sessions=asia|london|preny|ny|lclose",   # M5 cost 0.08-0.12 at q >= 0.57
}
DDS = {"": "", "mo3": "max_open_positions=3", "rr75": "range_risk_scale=0.75", "mc2": "mart_max_risk_pct=2",
       "mo3_mc2": "max_open_positions=3,mart_max_risk_pct=2"}


def j(*parts: str) -> str:
    return ",".join(p for p in parts if p)


def variants() -> dict[str, str]:
    v: dict[str, str] = {"ref": ""}
    # --- CS conviction sizing
    for conf in (1.25, 1.5, 1.75, 2.0):
        for plain in (1.0, 0.9, 0.8, 0.75, 0.6, 0.5):
            v[f"CS_{conf}_{plain}"] = f"confluent_risk_scale={conf},plain_risk_scale={plain}"
    # --- CM confluence memory
    for mins in (15, 30, 60, 120, 240, 480, 960):
        v[f"CM_{mins}"] = f"confluence_memory_min={mins}"
        v[f"CM_{mins}_open"] = f"confluence_memory_min={mins},confluence_memory_kind=open"
    for mins in (60, 240):
        v[f"CM_{mins}_pend"] = f"confluence_memory_min={mins},confluence_memory_kind=pending"
    # --- TIER tight second bars
    for name, flt in TIERS.items():
        for sc in (0.5, 0.35):
            v[f"TIER_{name}_{sc}"] = f"tier_filter={flt},tier_risk_scale={sc}"
    # --- DD buy-backs alone (to see their own cost)
    for k, o in DDS.items():
        if k:
            v[f"DD_{k}"] = o
    # --- CMB: memory x conviction (x buy-back)
    for mins in (30, 60, 120, 240):
        for conf, plain in ((1.25, 1.0), (1.25, 0.9), (1.25, 0.8), (1.5, 0.9), (1.5, 0.8), (1.5, 0.75), (1.5, 0.6), (1.75, 0.75), (2.0, 0.6)):
            for dd in ("", "mo3", "mc2", "rr75"):
                v[f"CMB_cm{mins}_cs{conf}_{plain}{'_' + dd if dd else ''}"] = j(
                    f"confluence_memory_min={mins}", f"confluent_risk_scale={conf},plain_risk_scale={plain}", DDS[dd])
    # --- CMB with the open-only memory
    for mins in (60, 240):
        for conf, plain in ((1.25, 0.9), (1.5, 0.8)):
            v[f"CMB_cm{mins}o_cs{conf}_{plain}"] = j(f"confluence_memory_min={mins},confluence_memory_kind=open",
                                                     f"confluent_risk_scale={conf},plain_risk_scale={plain}")
    # --- CMB + tier
    for mins in (60, 240):
        for conf, plain in ((1.25, 0.9), (1.5, 0.8)):
            for tn in ("m10q55", "htfq55"):
                v[f"CMB_cm{mins}_cs{conf}_{plain}_T{tn}"] = j(f"confluence_memory_min={mins}",
                                                              f"confluent_risk_scale={conf},plain_risk_scale={plain}",
                                                              f"tier_filter={TIERS[tn]},tier_risk_scale=0.5")
    return v


def run_one(name: str, over: str, m1, sel, extra_s: str = "", tag: str = "", out: Path = OUT) -> dict:
    key = f"{name}{('__' + tag) if tag else ''}".replace("/", "-")
    f = out / f"{key}.json"
    if f.exists():
        try:
            return json.load(open(f))
        except Exception:
            pass
    t0 = time.time()
    tcfg = v14a_config().override(over)
    spec = spec_override(SymbolSpec(), extra_s)
    res = PortfolioSimulator(m1, sel, tcfg, spec).run()
    row = {"key": key, "name": name, "tag": tag, "overrides": over}
    row.update(judge15(res))
    s = res.summary()
    row["confluent_trades"], row["tier_trades"] = s.get("confluent_trades"), s.get("tier_trades")
    tr = res.trades
    if len(tr):
        tr = tr.assign(month=tr.close_time.dt.strftime("%Y-%m"))
        row["monthly_$"] = tr.groupby("month").net.sum().round(2).to_dict()
        row["by_tf_net"] = tr.groupby("tf").net.sum().round(2).to_dict()
        row["outcomes"] = tr.outcome.value_counts().to_dict()
        c = tr[tr.confluent]
        row["conf_n"], row["conf_net"], row["conf_win_%"] = len(c), round(c.net.sum(), 2), round(100 * (c.net > 0).mean(), 1) if len(c) else np.nan
        t = tr[tr.tier] if "tier" in tr else tr.iloc[0:0]
        row["tier_n"], row["tier_net"], row["tier_win_%"] = len(t), round(t.net.sum(), 2), round(100 * (t.net > 0).mean(), 1) if len(t) else np.nan
        tr.to_csv(out / f"{key}_trades.csv", index=False)
    res.equity.to_csv(out / f"{key}_equity.csv")
    row["secs"] = round(time.time() - t0, 1)
    tmp = out / f"{key}.json.tmp"
    json.dump(row, open(tmp, "w"), indent=1, default=str)
    os.replace(tmp, f)
    return row


COLS = ["name", "trades", "net_$", "OOS_net_$", "return_%", "max_dd_%", "profit_factor", "win_%", "sl_%", "worst_day_%eq", "OOS_PF",
        "OOS_win_%", "OOS_sl_%", "months_pos", "confluent_trades", "tier_trades", "max_risk_%eq", "return_over_dd", "more_trades",
        "more_profit", "hold_loss", "hold_oos", "score"]


def summarize(rows: list[dict], path: str) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    df = df.sort_values(["score", "OOS_net_$"], ascending=[False, False])
    df.to_csv(path, index=False)
    return df


def show(r: dict) -> None:
    print(fmt15(r["name"] + (f"__{r['tag']}" if r.get("tag") else ""), r) + f" ({r.get('secs')}s)", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=CSV)
    ap.add_argument("--only", default="", help="comma list of variant names")
    ap.add_argument("--stress", default="", help="comma list of variant names to stress (6 scenarios each)")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    v = variants()
    if a.list:
        for k, o in v.items():
            print(f"{k:<44} {o}")
        print(len(v), "variants")
        return
    if a.only:
        v = {"ref": "", **{k: v[k] for k in a.only.split(",")}}
    todo = [(k, o, "", "") for k, o in v.items()]
    if a.stress:
        allv = variants()
        for n in a.stress.split(","):
            for tag, (et, es) in STRESS.items():
                todo.append((n, j(allv[n], et), es, tag))
    n_left = sum(1 for k, _, _, tag in todo if not (OUT / ((k + ('__' + tag if tag else '')).replace('/', '-') + '.json')).exists())
    print(f"{len(todo)} runs, {n_left} to run", flush=True)
    m1, sel = load_year(a.csv)
    rows = []
    done_since_save = 0
    for (k, o, es, tag) in todo:
        r = run_one(k, o, m1, sel, extra_s=es, tag=tag)
        rows.append(r)
        show(r)
        done_since_save += 1
        if done_since_save >= 5 and not a.stress:
            summarize([x for x in rows if not x["tag"]], path="study_results/v15_levers_partial.csv")
            done_since_save = 0
    base = [r for r in rows if not r["tag"]]
    path = "study_results/v15_levers.csv" if not (a.only or a.stress) else "study_results/v15_levers_partial.csv"
    df = summarize(base, path=path)
    if a.stress:
        pd.DataFrame([r for r in rows if r["tag"]]).to_csv("study_results/v15_stress.csv", index=False)
    pd.set_option("display.width", 320)
    print("\n=== v15 GRID ===\n" + df[COLS].to_string(index=False))


if __name__ == "__main__":
    main()
