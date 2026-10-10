#!/usr/bin/env python3
"""v16b step 3 - LEVER GRID on top of v16-A (the trader shipped in run_trader.bat): REDUCE THE LOSS PERCENTAGE while
MAINTAINING THE PROFITABILITY PERCENTAGE.

Reference (v16-A, full year Sep25-Sep26, FINAL_BACKTEST_V16.md): 467 trades, net +30 175 $, OOS net +19 661 $, max DD 5.82 %,
PF 2.365, win 75.2 %, stop-outs 24.4 %, gross loss -22 102 $, worst day -2.64 % eq, OOS PF 2.247, OOS sl 23.9, 13/13 months.

Families (every run = full year through the M1 portfolio simulator, ~16 s, ~400 MB, workers 1):
  ref                       v16-A on the v16 streams - must equal the reference (parity)
  T<N>[_x<s>][_<tfs>][_rng]  daily trend gate SMA N on SELLS: skip (default) or scale x s; tf scope; range-regime only
  TB<N>_*                   the same gate on BOTH sides (the diagnosis says buys are fine - control)
  F<N>[_x<s>][_<tfs>][_rng]  impulsive-arrival guard: an order that would fill < N min after placement is cancelled / scaled
  RS_<s>                    range-regime sells sized x s (regime x side scale)
  BE<r>                     SL -> BE once MFE >= r R (the v9 lever re-tested on v16-A)
  DL<x>                     per-day loss cap x % (below the shipped 4.5)
  C_*                       combinations of the single-lever survivors (score >= 3 or less_loss + hold_profit)
Judge (v16b_common.judge16b): less_loss (sl %, max DD, gross loss $ all better), hold_profit (net >= 97 %, PF >= ref - 0.05,
OOS net >= 97 %), hold_oos (OOS sl <, OOS PF >= ref - 0.10, OOS DD >= ref - 0.5), no_worse_day (>= ref - 0.25 pt).  Score 0-4.
Resumable: one json per variant in study_results/v16b_levers/, summary -> study_results/v16b_levers.csv (rewritten every 5 runs).

    nohup bash run_v16b_all.sh > logs/v16b_all.log 2>&1 &           # grid + autosave
    python3 run_v16b_levers.py --stage combos                       # after the singles: the combination stage
    python3 run_v16b_levers.py --stress name1,name2                 # 6 stress scenarios each -> v16b_stress.csv
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backtest_trader import spec_override  # noqa: E402
from lubot.execution import SymbolSpec  # noqa: E402
from lubot.portfolio_sim import PortfolioSimulator  # noqa: E402
from run_v12_levers import STRESS  # noqa: E402
from v16b_common import EXPECT_V16A, fmt16b, judge16b, load_year16, v16a_config  # noqa: E402

OUT = Path("study_results/v16b_levers")
CSV = "data/xauusd_m1.csv"
TF_SCOPES = {"": "", "m510": "M5|M10", "m51015": "M5|M10|M15", "htf": "M15|M20|M30|H1"}


def j(*parts: str) -> str:
    return ",".join(p for p in parts if p)


def trend(n: int, scale: float | None = None, tfs: str = "", regime: str = "", sides: str = "sell") -> str:
    o = [f"trend_sma={n}", f"trend_sides={sides}"]
    if scale is not None:
        o += ["trend_mode=scale", f"trend_risk_scale={scale}"]
    if tfs:
        o.append(f"trend_tfs={TF_SCOPES[tfs]}")
    if regime:
        o.append(f"trend_regime={regime}")
    return j(*o)


def fast(n: int, scale: float | None = None, tfs: str = "", regime: str = "") -> str:
    o = [f"min_fill_age_min={n}"]
    if scale is not None:
        o += ["fast_fill_mode=scale", f"fast_fill_scale={scale}"]
    if tfs:
        o.append(f"fast_fill_tfs={TF_SCOPES[tfs]}")
    if regime:
        o.append(f"fast_fill_regime={regime}")
    return j(*o)


def singles() -> dict[str, str]:
    v: dict[str, str] = {"ref": ""}
    # --- T: trend gate on sells (SMA N) - skip, then scale, then scoped
    for n in (5, 10, 20, 50):
        v[f"T{n}"] = trend(n)
    for n in (10, 20):
        for sc in (0.75, 0.5, 0.25):
            v[f"T{n}_x{sc}"] = trend(n, sc)
        for tn in ("m510", "m51015", "htf"):
            v[f"T{n}_{tn}"] = trend(n, None, tn)
            v[f"T{n}_x0.5_{tn}"] = trend(n, 0.5, tn)
        v[f"T{n}_rng"] = trend(n, None, "", "range")
        v[f"T{n}_x0.5_rng"] = trend(n, 0.5, "", "range")
        v[f"T{n}_trd"] = trend(n, None, "", "trend")
    # control: both sides
    for n in (10, 20):
        v[f"TB{n}"] = trend(n, None, "", "", "sell|buy")
        v[f"TB{n}_x0.5"] = trend(n, 0.5, "", "", "sell|buy")
    # --- F: impulsive-arrival guard
    for n in (2, 3, 5, 8, 10):
        v[f"F{n}"] = fast(n)
    for n in (3, 5):
        for sc in (0.75, 0.5, 0.25):
            v[f"F{n}_x{sc}"] = fast(n, sc)
        for tn in ("m510", "m51015"):
            v[f"F{n}_{tn}"] = fast(n, None, tn)
            v[f"F{n}_x0.5_{tn}"] = fast(n, 0.5, tn)
        v[f"F{n}_rng"] = fast(n, None, "", "range")
        v[f"F{n}_x0.5_rng"] = fast(n, 0.5, "", "range")
    # --- RS: range-regime sells sized down
    for sc in (0.75, 0.5, 0.25, 0.0):
        v[f"RS_{sc}"] = f"regime_side_scale=range:sell:{sc}"
    # --- BE: break-even trigger before TP1 (0.6 R)
    for r in (0.3, 0.4, 0.5):
        v[f"BE{r}"] = f"be_trigger_r={r}"
    # --- DL: per-day loss cap
    for x in (3.5, 3.0, 2.5):
        v[f"DL{x}"] = f"max_daily_loss_pct={x}"
    return v


def survivors(df: pd.DataFrame) -> list[str]:
    """single-lever rows worth combining: score >= 3, or less_loss with hold_profit, or hold_profit with the stop rate down."""
    ok = df[(df.name != "ref") & ((df.score >= 3) | (df.less_loss & df.hold_profit) | (df.hold_profit & (df["d_sl_pt"] <= -0.8)))]
    return list(ok.sort_values(["score", "saved_$"], ascending=[False, False]).name)


def combos(single_df: pd.DataFrame | None) -> dict[str, str]:
    """T x F x RS x BE x DL combinations.  Each family contributes its best 2-3 single rows (or a fixed fallback list)."""
    s = singles()
    fam = {"T": [], "F": [], "RS": [], "BE": [], "DL": []}
    if single_df is not None and len(single_df):
        for n in survivors(single_df):
            f = "RS" if n.startswith("RS") else "BE" if n.startswith("BE") else "DL" if n.startswith("DL") else n[0]
            if f in fam and len(fam[f]) < 3:
                fam[f].append(n)
    # fallbacks so the stage never runs empty (the smoke run: T10 and F5 each fix one side of the judge)
    fam["T"] = fam["T"] or ["T10_x0.5", "T10_rng", "T20_x0.5"]
    fam["F"] = fam["F"] or ["F5_x0.5", "F5_rng", "F3"]
    fam["RS"] = fam["RS"] or ["RS_0.5"]
    v: dict[str, str] = {}
    for t in fam["T"]:
        for f in fam["F"]:
            v[f"C_{t}+{f}"] = j(s[t], s[f])
            for r in fam["RS"][:1]:
                v[f"C_{t}+{f}+{r}"] = j(s[t], s[f], s[r])
            for b in fam["BE"][:1]:
                v[f"C_{t}+{f}+{b}"] = j(s[t], s[f], s[b])
            for d in fam["DL"][:1]:
                v[f"C_{t}+{f}+{d}"] = j(s[t], s[f], s[d])
    for t in fam["T"]:
        for r in fam["RS"][:2]:
            v[f"C_{t}+{r}"] = j(s[t], s[r])
    for f in fam["F"]:
        for r in fam["RS"][:2]:
            v[f"C_{f}+{r}"] = j(s[f], s[r])
    return v


def variants(stage: str, single_df: pd.DataFrame | None = None) -> dict[str, str]:
    if stage == "singles":
        return singles()
    if stage == "combos":
        return {"ref": "", **combos(single_df)}
    return {**singles(), **combos(single_df)}


def run_one(name: str, over: str, m1, sel, extra_s: str = "", tag: str = "", out: Path = OUT) -> dict:
    key = f"{name}{('__' + tag) if tag else ''}".replace("/", "-")
    f = out / f"{key}.json"
    if f.exists():
        try:
            return json.load(open(f))
        except Exception:
            pass
    t0 = time.time()
    tcfg = v16a_config().override(over) if over else v16a_config()
    spec = spec_override(SymbolSpec(), extra_s)
    res = PortfolioSimulator(m1, sel, tcfg, spec).run()
    row = {"key": key, "name": name, "tag": tag, "overrides": over}
    row.update(judge16b(res))
    s = res.summary()
    for k in ("confluent_trades", "tier_trades", "pending_placed", "cancelled", "trend_scaled", "fast_scaled"):
        row[k] = s.get(k)
    tr = res.trades
    if len(tr):
        tr = tr.assign(month=tr.close_time.dt.strftime("%Y-%m"))
        row["monthly_$"] = tr.groupby("month").net.sum().round(2).to_dict()
        row["by_tf_net"] = tr.groupby("tf").net.sum().round(2).to_dict()
        row["by_tf_n"] = tr.groupby("tf").size().to_dict()
        row["by_side_n"] = tr.groupby("side").size().to_dict()
        row["by_side_net"] = tr.groupby("side").net.sum().round(2).to_dict()
        row["by_side_sl_%"] = (100 * tr.assign(_sl=(tr.outcome == "sl").astype(float)).groupby("side")._sl.mean()).round(1).to_dict()
        row["outcomes"] = tr.outcome.value_counts().to_dict()
        tr.to_csv(out / f"{key}_trades.csv", index=False)
    res.equity.to_csv(out / f"{key}_equity.csv")
    row["secs"] = round(time.time() - t0, 1)
    tmp = out / f"{key}.json.tmp"
    json.dump(row, open(tmp, "w"), indent=1, default=str)
    os.replace(tmp, f)
    return row


COLS = ["name", "trades", "net_$", "OOS_net_$", "return_%", "max_dd_%", "profit_factor", "win_%", "sl_%", "gross_loss_$", "saved_$",
        "worst_day_%eq", "OOS_PF", "OOS_sl_%", "OOS_max_dd_%", "months_pos", "trend_skipped", "fast_cancelled", "less_loss",
        "hold_profit", "hold_oos", "no_worse_day", "score"]


def summarize(rows: list[dict], path: str) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    df = df.sort_values(["score", "saved_$", "net_$"], ascending=[False, False, False])
    df.to_csv(path, index=False)
    return df


def show(r: dict) -> None:
    print(fmt16b(r["name"] + (f"__{r['tag']}" if r.get("tag") else ""), r) + f" ({r.get('secs')}s)", flush=True)


def load_singles_csv() -> pd.DataFrame | None:
    p = Path("study_results/v16b_levers.csv")
    if not p.exists():
        p = Path("study_results/v16b_levers_partial.csv")
    if not p.exists():
        return None
    df = pd.read_csv(p)
    return df[~df.name.str.startswith("C_")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=CSV)
    ap.add_argument("--stage", default="singles", choices=["singles", "combos", "all"])
    ap.add_argument("--only", default="", help="comma list of variant names")
    ap.add_argument("--stress", default="", help="comma list of variant names to stress (6 scenarios each)")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    v = variants(a.stage, load_singles_csv() if a.stage != "singles" else None)
    if a.list:
        for k, o in v.items():
            print(f"{k:<34} {o}")
        print(len(v), "variants")
        return
    if a.only:
        allv = variants("all", load_singles_csv())
        v = {"ref": "", **{k: allv[k] for k in a.only.split(",")}}
    todo = [(k, o, "", "") for k, o in v.items()]
    if a.stress:
        allv = variants("all", load_singles_csv())
        todo = [("ref", "", "", "")]
        for n in a.stress.split(","):
            for tag, (et, es) in STRESS.items():
                todo.append((n, j(allv[n], et), es, tag))
    n_left = sum(1 for k, _, _, tag in todo if not (OUT / ((k + ('__' + tag if tag else '')).replace('/', '-') + '.json')).exists())
    print(f"{len(todo)} runs, {n_left} to run", flush=True)
    m1, sel = load_year16(a.csv, stream="v16", max_rank=3)
    rows = []
    done_since_save = 0
    for (k, o, es, tag) in todo:
        r = run_one(k, o, m1, sel, extra_s=es, tag=tag)
        rows.append(r)
        show(r)
        if k == "ref" and not tag:
            got = (r["trades"], r["return_%"], r["max_dd_%"])
            print("PARITY", "IDENTICAL" if got == EXPECT_V16A else f"MISMATCH {got} != {EXPECT_V16A}", flush=True)
        done_since_save += 1
        if done_since_save >= 5 and not a.stress:
            summarize([x for x in rows if not x["tag"]], path="study_results/v16b_levers_partial.csv")
            done_since_save = 0
    base = [r for r in rows if not r["tag"]]
    if a.stress:
        prev = Path("study_results/v16b_stress.csv")
        old = pd.read_csv(prev) if prev.exists() else pd.DataFrame()
        new = pd.DataFrame([r for r in rows if r["tag"]])
        allst = pd.concat([old, new]).drop_duplicates("key", keep="last") if len(old) else new
        allst.to_csv(prev, index=False)
        print(allst[["key"] + COLS[1:]].to_string(index=False))
        return
    # the full csv = every json on disk (singles + combos), so the stages accumulate
    every = []
    for f in sorted(OUT.glob("*.json")):
        if "__" in f.stem:
            continue
        try:
            every.append(json.load(open(f)))
        except Exception:
            pass
    path = "study_results/v16b_levers.csv" if not a.only else "study_results/v16b_levers_partial.csv"
    df = summarize(every if not a.only else base, path=path)
    pd.set_option("display.width", 320)
    print("\n=== v16b GRID ===\n" + df[COLS].to_string(index=False))


if __name__ == "__main__":
    main()
