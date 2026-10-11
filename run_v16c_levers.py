#!/usr/bin/env python3
"""v16c step 3 - LEVER GRID on top of v16b-A (the trader shipped in run_trader.bat): REDUCE THE MAX DRAWDOWN PERCENTAGE while
MAINTAINING THE PROFITABILITY PERCENTAGE.

Reference (v16b-A, full year Sep25-Sep26, FINAL_BACKTEST_V16B.md): 446 trades, net +33 831 $, OOS net +23 958 $, max DD -5.55 %,
ulcer 1.691, PF 2.999, win 75.8 %, stop-outs 23.8 %, gross loss -16 921 $, worst day -2.34 % eq, OOS PF 3.124, OOS sl 21.1, 13/13.

Families (every run = full year through the M1 portfolio simulator, ~17 s, ~400 MB, workers 1):
  ref                          v16b-A on the v16 streams - must equal the reference (parity)
  DDT<x>_x<s>[_bal][_r<ramp>][_<tfs>]  drawdown throttle: new plans x s while the account is > x % below its peak (equity basis;
                               _bal = balance basis; _r<ramp> = linear ramp over <ramp> pt instead of a step; tf scope)
  DAY<x>_x<s>                  day soft cap: new plans x s once the day is x % under water (no flatten)
  OR<x>[_skip][_pend]          max open risk-at-stop x % eq (fit the new plan into the budget | skip it; _pend counts pending orders)
  STK<n>_x<s>                  loss-streak throttle (control): after n consecutive losses, new plans x s
  C_*                          combinations of the single-lever survivors
Judge (v16c_common.judge16c): less_dd (max DD better by >= 0.25 pt, OOS DD not worse, ulcer <= ref), hold_profit (net >= 97 %,
PF >= ref - 0.10, OOS net >= 97 %), hold_loss (sl <= ref + 1, gross loss <= 105 %, worst day >= ref - 0.25), hold_oos (OOS PF >=
ref - 0.10, OOS sl <= ref + 1, 13/13 months).  Score 0-4.
Resumable: one json per variant in study_results/v16c_levers/, summary -> study_results/v16c_levers.csv (rewritten every 5 runs).

    nohup bash run_v16c_all.sh > logs/v16c_all.log 2>&1 &           # grid + autosave
    python3 run_v16c_levers.py --stage combos                       # after the singles: the combination stage
    python3 run_v16c_levers.py --stress name1,name2                 # 6 stress scenarios each -> v16c_stress.csv
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
from v16c_common import EXPECT_V16B, fmt16c, judge16c, load_year16, v16b_config  # noqa: E402

OUT = Path("study_results/v16c_levers")
CSV = "data/xauusd_m1.csv"
TF_SCOPES = {"": "", "m510": "M5|M10", "htf": "M15|M20|M30|H1", "nom5": "M10|M15|M20|M30|H1"}


def j(*parts: str) -> str:
    return ",".join(p for p in parts if p)


def ddt(x: float, s: float, basis: str = "equity", ramp: float = 0.0, tfs: str = "") -> str:
    o = [f"dd_throttle_pct={x}", f"dd_throttle_scale={s}"]
    if basis != "equity":
        o.append(f"dd_basis={basis}")
    if ramp > 0:
        o.append(f"dd_throttle_ramp={ramp}")
    if tfs:
        o.append(f"dd_throttle_tfs={TF_SCOPES[tfs]}")
    return j(*o)


def day(x: float, s: float) -> str:
    return j(f"day_soft_loss_pct={x}", f"day_soft_scale={s}")


def orc(x: float, mode: str = "fit", pending: bool = False) -> str:
    o = [f"max_open_risk_pct={x}"]
    if mode != "fit":
        o.append(f"open_risk_mode={mode}")
    if pending:
        o.append("open_risk_pending=true")
    return j(*o)


def stk(n: int, s: float, days: float = 5.0) -> str:
    return j(f"streak_n={n}", f"streak_scale={s}", f"streak_days={days}" if days != 5.0 else "")


def singles() -> dict[str, str]:
    v: dict[str, str] = {"ref": ""}
    # --- DDT: drawdown throttle, equity basis (step)
    for x in (2.5, 3.0, 3.5, 4.0, 4.5):
        for s in (0.75, 0.6, 0.5, 0.25):
            v[f"DDT{x}_x{s}"] = ddt(x, s)
    # balance basis (the static re-walk's candidates: DDT_3.5_x0.5, 3.5_x0.6, 3.0_x0.75, 3.5_x0.75)
    for x in (2.5, 3.0, 3.5, 4.0, 4.5):
        for s in (0.75, 0.6, 0.5, 0.25):
            v[f"DDT{x}_x{s}_bal"] = ddt(x, s, "balance")
    # ramps (equity basis): scale falls from 1 at x to s at x + ramp
    for x in (2.0, 2.5, 3.0):
        for s in (0.5, 0.25):
            for r in (1.0, 2.0):
                v[f"DDT{x}_x{s}_r{r}"] = ddt(x, s, "equity", r)
    # tf scopes on the two most promising steps
    for x, s in ((3.0, 0.5), (3.5, 0.5)):
        for tn in ("m510", "htf", "nom5"):
            v[f"DDT{x}_x{s}_{tn}"] = ddt(x, s, "equity", 0.0, tn)
    # --- DAY: day soft cap
    for x in (0.75, 1.0, 1.5, 2.0):
        for s in (0.5, 0.25, 0.0):
            v[f"DAY{x}_x{s}"] = day(x, s)
    # --- OR: open-risk cap
    for x in (2.0, 2.5, 3.0, 3.5, 4.0):
        v[f"OR{x}"] = orc(x)
    for x in (2.5, 3.0, 3.5):
        v[f"OR{x}_skip"] = orc(x, "skip")
        v[f"OR{x}_pend"] = orc(x, "fit", True)
    # --- STK: loss-streak control
    for n in (2, 3):
        for s in (0.5, 0.25):
            v[f"STK{n}_x{s}"] = stk(n, s)
    return v


def survivors(df: pd.DataFrame) -> list[str]:
    """single-lever rows worth combining: score >= 3, or less_dd with hold_profit, or a DD cut >= 0.4 pt at net >= 95 %."""
    net_ok = df["net_$"] >= 0.95 * 33831.3
    ok = df[(df.name != "ref") & ((df.score >= 3) | (df.less_dd & df.hold_profit) | ((df["d_dd_pt"] >= 0.4) & net_ok))]
    return list(ok.sort_values(["score", "d_dd_pt", "net_$"], ascending=[False, False, False]).name)


def _fam(n: str) -> str:
    return "DDT" if n.startswith("DDT") else "DAY" if n.startswith("DAY") else "OR" if n.startswith("OR") else "STK"


def combos(single_df: pd.DataFrame | None) -> dict[str, str]:
    """DDT x DAY x OR combinations.  Each family contributes its best 3 single rows (or a fixed fallback list)."""
    s = singles()
    fam: dict[str, list[str]] = {"DDT": [], "DAY": [], "OR": [], "STK": []}
    if single_df is not None and len(single_df):
        for n in survivors(single_df):
            f = _fam(n)
            if len(fam[f]) < 3:
                fam[f].append(n)
    fam["DDT"] = fam["DDT"] or ["DDT3.5_x0.5_bal", "DDT3.0_x0.75_bal", "DDT3.5_x0.6_bal"]
    fam["DAY"] = fam["DAY"] or ["DAY1.0_x0.5", "DAY1.5_x0.5"]
    fam["OR"] = fam["OR"] or ["OR3.0", "OR3.5"]
    v: dict[str, str] = {}
    for d in fam["DDT"]:
        for y in fam["DAY"]:
            v[f"C_{d}+{y}"] = j(s[d], s[y])
        for o in fam["OR"]:
            v[f"C_{d}+{o}"] = j(s[d], s[o])
        for y in fam["DAY"][:2]:
            for o in fam["OR"][:2]:
                v[f"C_{d}+{y}+{o}"] = j(s[d], s[y], s[o])
    for y in fam["DAY"][:2]:
        for o in fam["OR"][:2]:
            v[f"C_{y}+{o}"] = j(s[y], s[o])
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
    tcfg = v16b_config().override(over) if over else v16b_config()
    spec = spec_override(SymbolSpec(), extra_s)
    res = PortfolioSimulator(m1, sel, tcfg, spec).run()
    row = {"key": key, "name": name, "tag": tag, "overrides": over}
    row.update(judge16c(res))
    s = res.summary()
    for k in ("confluent_trades", "tier_trades", "pending_placed", "cancelled", "dd_scaled", "dd_skipped", "dd_days",
              "day_soft_scaled", "day_soft_skipped", "open_risk_scaled", "open_risk_skipped", "streak_scaled", "dd_scaled_trades"):
        row[k] = s.get(k)
    tr = res.trades
    if len(tr):
        tr = tr.assign(month=tr.close_time.dt.strftime("%Y-%m"))
        row["monthly_$"] = tr.groupby("month").net.sum().round(2).to_dict()
        row["by_tf_net"] = tr.groupby("tf").net.sum().round(2).to_dict()
        row["by_tf_n"] = tr.groupby("tf").size().to_dict()
        row["by_side_n"] = tr.groupby("side").size().to_dict()
        row["by_side_net"] = tr.groupby("side").net.sum().round(2).to_dict()
        row["outcomes"] = tr.outcome.value_counts().to_dict()
        tr.to_csv(out / f"{key}_trades.csv", index=False)
    res.equity.to_csv(out / f"{key}_equity.csv")
    row["secs"] = round(time.time() - t0, 1)
    tmp = out / f"{key}.json.tmp"
    json.dump(row, open(tmp, "w"), indent=1, default=str)
    os.replace(tmp, f)
    return row


COLS = ["name", "trades", "net_$", "OOS_net_$", "return_%", "max_dd_%", "d_dd_pt", "dd2_%", "dd3_%", "ulcer", "return_over_dd",
        "profit_factor", "win_%", "sl_%", "gross_loss_$", "worst_day_%eq", "OOS_PF", "OOS_sl_%", "OOS_max_dd_%", "months_pos",
        "dd_scaled", "dd_days", "less_dd", "hold_profit", "hold_loss", "hold_oos", "score"]


def summarize(rows: list[dict], path: str) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    df = df.sort_values(["score", "d_dd_pt", "net_$"], ascending=[False, False, False])
    df.to_csv(path, index=False)
    return df


def show(r: dict) -> None:
    print(fmt16c(r["name"] + (f"__{r['tag']}" if r.get("tag") else ""), r) + f" ({r.get('secs')}s)", flush=True)


def load_singles_csv() -> pd.DataFrame | None:
    p = Path("study_results/v16c_levers.csv")
    if not p.exists():
        p = Path("study_results/v16c_levers_partial.csv")
    if not p.exists():
        return None
    df = pd.read_csv(p)
    return df[~df.name.str.startswith("C_")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=CSV)
    ap.add_argument("--stage", default="singles", choices=["singles", "combos", "all"])
    ap.add_argument("--only", default="", help="comma list of variant names")
    ap.add_argument("--extra", default="", help="name=overrides;name=overrides  ad-hoc variants (run with --only names)")
    ap.add_argument("--stress", default="", help="comma list of variant names to stress (6 scenarios each)")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    v = variants(a.stage, load_singles_csv() if a.stage != "singles" else None)
    extra = {}
    for part in (a.extra or "").split(";"):
        if "=" in part:
            n, o = part.split("=", 1)
            extra[n.strip()] = o.strip()
    if a.list:
        for k, o in v.items():
            print(f"{k:<34} {o}")
        print(len(v), "variants")
        return
    if a.only:
        allv = {**variants("all", load_singles_csv()), **extra}
        v = {"ref": "", **{k: allv[k] for k in a.only.split(",")}}
    todo = [(k, o, "", "") for k, o in v.items()]
    if a.stress:
        allv = {**variants("all", load_singles_csv()), **extra}
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
            print("PARITY", "IDENTICAL" if got == EXPECT_V16B else f"MISMATCH {got} != {EXPECT_V16B}", flush=True)
        done_since_save += 1
        if done_since_save >= 5 and not a.stress:
            summarize([x for x in rows if not x["tag"]], path="study_results/v16c_levers_partial.csv")
            done_since_save = 0
    base = [r for r in rows if not r["tag"]]
    if a.stress:
        prev = Path("study_results/v16c_stress.csv")
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
    path = "study_results/v16c_levers.csv" if not a.only else "study_results/v16c_levers_partial.csv"
    df = summarize(every if not a.only else base, path=path)
    pd.set_option("display.width", 320)
    print("\n=== v16c GRID ===\n" + df[COLS].to_string(index=False))


if __name__ == "__main__":
    main()
