#!/usr/bin/env python3
"""v16 step 4 - LEVER GRID on top of v15-A (the trader shipped in run_trader.bat) with the NEW TRADE SOURCES of the re-recorded
top-3 streams (study_results/sel_v16_<TF>.pkl): rank-2/3 candidates and the M20 timeframe.

Reference (v15-A, full year Sep25-Sep26): 448 trades, net +29 745 $, OOS net +19 264 $, max DD 5.82 %, PF 2.375, win 74.8 %,
stop-outs 24.8 %, worst day -2.42 % eq, OOS PF 2.26, 13/13 months.

Families (every run = full year through the M1 portfolio simulator, ~15-20 s, ~400 MB):
  ref                           v15-A on the v16 stream (rank 1, no M20) - must equal the v15 reference (parity)
  R2_<bar>_<scale>[_<tfs>]      rank-2 zones admitted (max_rank 2) at a filter bar x risk scale x timeframe scope
  R2C_*                         rank-2 zones only when confluent (another TF active / remembered on the level)
  R3_*                          rank 2 AND 3
  M20_<bar>[_<scale>]           the M20 stream added to the five timeframes (its own filter bar) - rank 1 only
  CMB_*                         rank-2 x M20 combinations
Judge (v16_common.judge16): more_trades (n > 448), more_profit (net AND OOS net above ref), hold_loss, hold_oos (v15 bands).
Resumable: one json per variant in study_results/v16_levers/, summary -> study_results/v16_levers.csv (rewritten every 5 runs).

    nohup bash run_v16_all.sh > logs/v16_all.log 2>&1 &            # grid + autosave
    python3 run_v16_levers.py --stress name1,name2                 # 6 stress scenarios each -> v16_stress.csv
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
from v16_common import V15A_CF, V15A_FLT, fmt16, judge16, load_year16, v15a_config  # noqa: E402

OUT = Path("study_results/v16_levers")
CSV = "data/xauusd_m1.csv"
TF5 = "M5|M10|M15|M30|H1"
TF6 = "M5|M10|M15|M20|M30|H1"

# rank-2 filter bars (same syntax as the trade filter).  "" = the normal bar (trade_filter / confluence_filter) applies.
R2BARS = {
    "same": "",
    "q55": "M5:max_cost_r=0.08;min_quality=0.55;sessions=asia|london|preny|ny|lclose/M10|M15|M30|H1:min_quality=0.55",
    "q57": "M5:max_cost_r=0.08;min_quality=0.57;sessions=asia|london|preny|ny|lclose/M10|M15|M30|H1:min_quality=0.57",
    "q60": "M5:max_cost_r=0.08;min_quality=0.60;sessions=asia|london|preny|ny|lclose/M10|M15|M30|H1:min_quality=0.60",
    "q65": "M5:max_cost_r=0.08;min_quality=0.65;sessions=asia|london|preny|ny|lclose/M10|M15|M30|H1:min_quality=0.65",
    "none": "M5|M10|M15|M20|M30|H1:min_quality=0.99",      # unreachable: no rank-2 zone is ever placed (keep-demoted effect only)
}
# M20 filter bars: the M20 rule is appended to the v15-A trade filter and confluence filter
M20BARS = {"q55": "0.55", "q57": "0.57", "q60": "0.60", "q65": "0.65"}


def j(*parts: str) -> str:
    return ",".join(p for p in parts if p)


def m20_filters(q: str, qc: str | None = None) -> str:
    """TraderConfig overrides that add an M20 rule (min_quality q) to both filters and put M20 into the TF-scoped keys.
    ``qc``: quality bar of the CONFLUENCE filter for M20 (default = q).  q=0.99 + qc=0.55 -> M20 traded ONLY when confluent."""
    flt = V15A_FLT + f"/M20:min_quality={q}"
    cf = V15A_CF + f"/M20:min_quality={qc if qc is not None else q}"
    # the override parser splits on ',' -> the filter strings must not contain ',' (they do not)
    return f"trade_filter={flt},confluence_filter={cf},keep_replaced_tfs=M10|M15|M20|M30|H1,mart_tfs=M10|M15|M20|M30|H1,timeframes={TF6}"


def variants() -> dict[str, str]:
    v: dict[str, str] = {"ref": f"timeframes={TF5}"}
    # --- R2: rank-2 admission, bar x scale x tf scope
    for bar in ("same", "q55", "q57", "q60", "q65"):
        for sc in (1.0, 0.75, 0.5):
            for tfs, tn in ((None, ""), ("M10|M15|M30|H1", "htf"), ("M10|M15", "m1015"), ("M5|M10", "m510")):
                name = f"R2_{bar}_{sc}" + (f"_{tn}" if tn else "")
                v[name] = j(f"timeframes={TF5}", "max_rank=2", f"rank2_filter={R2BARS[bar]}" if R2BARS[bar] else "",
                            f"rank2_risk_scale={sc}" if sc != 1.0 else "", f"rank2_tfs={tfs}" if tfs else "")
    # --- KD: keep-demoted only (max_rank 2, no rank-2 zone can pass) - isolates the "demoted POI keeps its order" effect
    v["KD"] = j(f"timeframes={TF5}", "max_rank=2", f"rank2_filter={R2BARS['none']}")
    v["KD_htf"] = j(f"timeframes={TF5}", "max_rank=2", f"rank2_filter={R2BARS['none']}", "rank2_tfs=M10|M15|M30|H1")
    # --- R2C: rank-2 only when confluent
    for bar in ("same", "q55", "q60", "q65"):
        for sc in (1.0, 0.75):
            v[f"R2C_{bar}_{sc}"] = j(f"timeframes={TF5}", "max_rank=2,rank2_confluent_only=true",
                                     f"rank2_filter={R2BARS[bar]}" if R2BARS[bar] else "", f"rank2_risk_scale={sc}" if sc != 1.0 else "")
            v[f"R2C_{bar}_{sc}_htf"] = j(v[f"R2C_{bar}_{sc}"], "rank2_tfs=M10|M15|M30|H1")
    # --- R3: ranks 2 and 3
    for bar in ("same", "q57", "q60"):
        for sc in (1.0, 0.5):
            v[f"R3_{bar}_{sc}"] = j(f"timeframes={TF5}", "max_rank=3", f"rank2_filter={R2BARS[bar]}" if R2BARS[bar] else "",
                                    f"rank2_risk_scale={sc}" if sc != 1.0 else "")
    # --- M20 alone (rank 1)
    for bn, q in M20BARS.items():
        v[f"M20_{bn}"] = m20_filters(q)
    # --- M20C: M20 only when CONFLUENT (plain M20 bar unreachable), confluence bar x; +KD (keep-demoted) combos
    for qc in ("0.50", "0.55", "0.57", "0.60", "0.63"):
        v[f"M20C_{qc}"] = m20_filters("0.99", qc)
        v[f"M20C_{qc}_KD"] = j(m20_filters("0.99", qc), "max_rank=2", f"rank2_filter={R2BARS['none']}")
    # M20 plain allowed only at a very high bar, confluent at a loose one
    for q, qc in (("0.63", "0.55"), ("0.63", "0.57"), ("0.66", "0.55")):
        v[f"M20C_{qc}_p{q}"] = m20_filters(q, qc)
        v[f"M20C_{qc}_p{q}_KD"] = j(m20_filters(q, qc), "max_rank=2", f"rank2_filter={R2BARS['none']}")
    # --- CMB: M20 x rank-2
    for bn in ("q57", "q60"):
        for bar in ("same", "q57", "q60"):
            for sc in (1.0, 0.75, 0.5):
                r2bar = (R2BARS[bar] + "/M20:min_quality=" + M20BARS[bar]) if R2BARS[bar] else ""
                v[f"CMB_m20{bn}_r2{bar}_{sc}"] = j(m20_filters(M20BARS[bn]), "max_rank=2", f"rank2_filter={r2bar}" if r2bar else "",
                                                   f"rank2_risk_scale={sc}" if sc != 1.0 else "")
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
    tcfg = v15a_config().override(over)
    spec = spec_override(SymbolSpec(), extra_s)
    res = PortfolioSimulator(m1, sel, tcfg, spec).run()
    row = {"key": key, "name": name, "tag": tag, "overrides": over}
    row.update(judge16(res))
    s = res.summary()
    for k in ("confluent_trades", "tier_trades", "rank2_trades", "rank2_placed", "pending_placed", "cancelled"):
        row[k] = s.get(k)
    tr = res.trades
    if len(tr):
        tr = tr.assign(month=tr.close_time.dt.strftime("%Y-%m"))
        row["monthly_$"] = tr.groupby("month").net.sum().round(2).to_dict()
        row["by_tf_net"] = tr.groupby("tf").net.sum().round(2).to_dict()
        row["by_tf_n"] = tr.groupby("tf").size().to_dict()
        row["outcomes"] = tr.outcome.value_counts().to_dict()
        r2 = tr[tr["rank"] > 1]
        row["r2_n"], row["r2_net"], row["r2_win_%"] = len(r2), round(r2.net.sum(), 2), round(100 * (r2.net > 0).mean(), 1) if len(r2) else np.nan
        row["r2_R"] = round(r2.r_net.sum(), 2)
        m = tr[tr.tf == "M20"]
        row["m20_n"], row["m20_net"], row["m20_win_%"] = len(m), round(m.net.sum(), 2), round(100 * (m.net > 0).mean(), 1) if len(m) else np.nan
        tr.to_csv(out / f"{key}_trades.csv", index=False)
    res.equity.to_csv(out / f"{key}_equity.csv")
    row["secs"] = round(time.time() - t0, 1)
    tmp = out / f"{key}.json.tmp"
    json.dump(row, open(tmp, "w"), indent=1, default=str)
    os.replace(tmp, f)
    return row


COLS = ["name", "trades", "net_$", "OOS_net_$", "return_%", "max_dd_%", "profit_factor", "win_%", "sl_%", "worst_day_%eq", "OOS_PF",
        "OOS_win_%", "OOS_sl_%", "months_pos", "rank2_trades", "r2_net", "m20_trades", "m20_net", "max_risk_%eq", "more_trades",
        "more_profit", "hold_loss", "hold_oos", "score"]


def summarize(rows: list[dict], path: str) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    df = df.sort_values(["score", "OOS_net_$"], ascending=[False, False])
    df.to_csv(path, index=False)
    return df


def show(r: dict) -> None:
    print(fmt16(r["name"] + (f"__{r['tag']}" if r.get("tag") else ""), r) + f" ({r.get('secs')}s)", flush=True)


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
            print(f"{k:<40} {o}")
        print(len(v), "variants")
        return
    if a.only:
        v = {"ref": v["ref"], **{k: v[k] for k in a.only.split(",")}}
    todo = [(k, o, "", "") for k, o in v.items()]
    if a.stress:
        allv = variants()
        for n in a.stress.split(","):
            for tag, (et, es) in STRESS.items():
                todo.append((n, j(allv[n], et), es, tag))
    n_left = sum(1 for k, _, _, tag in todo if not (OUT / ((k + ('__' + tag if tag else '')).replace('/', '-') + '.json')).exists())
    print(f"{len(todo)} runs, {n_left} to run", flush=True)
    # the full top-3 stream incl. M20; every variant cuts it with max_rank / timeframes inside the simulator
    m1, sel = load_year16(a.csv, stream="v16", max_rank=3)
    rows = []
    done_since_save = 0
    for (k, o, es, tag) in todo:
        r = run_one(k, o, m1, sel, extra_s=es, tag=tag)
        rows.append(r)
        show(r)
        done_since_save += 1
        if done_since_save >= 5 and not a.stress:
            summarize([x for x in rows if not x["tag"]], path="study_results/v16_levers_partial.csv")
            done_since_save = 0
    base = [r for r in rows if not r["tag"]]
    path = "study_results/v16_levers.csv" if not (a.only or a.stress) else "study_results/v16_levers_partial.csv"
    df = summarize(base, path=path)
    if a.stress:
        pd.DataFrame([r for r in rows if r["tag"]]).to_csv("study_results/v16_stress.csv", index=False)
    pd.set_option("display.width", 320)
    print("\n=== v16 GRID ===\n" + df[COLS].to_string(index=False))


if __name__ == "__main__":
    main()
