#!/usr/bin/env python3
"""v14 step 3 - MARTINGALE LEVER GRID on top of v13-A (the trader shipped in run_trader.bat).

Reference (v13-A): 430 trades, +188.65 %, max DD 5.45 %, PF 2.008, win 75.3 %, gross loss -18 711 $, avg loss -176 $, OOS PF 1.91,
worst day -2.04 % of day-start equity, 13/13 months.

Families (every run = full year Sep25-Sep26 through the M1 portfolio simulator, ~15 s, ~400 MB):
  MU_<mult>_c<cap>_r<maxrisk>[_<gate>][_dn<x>]   sequence step-up x mult^k (gates: htf = M10|M15|M30|H1, buy, htfbuy, q60, trend;
                                                  dn<x> = asymmetric: an after-loss plan that fails the gate is sized x<x>)
  FIB_c<cap>_r<maxrisk>[_<gate>][_dn<x>]         Fibonacci steps
  ADD_<slope>_c<cap>[_<gate>]                    d'Alembert
  DEF_<R>_c<cap>_r<maxrisk>[_<gate>]             deficit recovery
  SHR_<mult>_c<cap>[_<gate>]                     shrink after losses (mult < 1); with a gate = shrink only where the gate PASSES
  ANTI_<mult>_c<cap>                             grow after wins (control)
  LAD_<mult>_<ladder>[_<lock>]                   recovery plan uses its own ladder
  TF_<mult>_c<cap>                               per-timeframe streaks (mart_scope=tf)
  GR_<add_r>_<base>/<add>[_own][_<gate>]         zone-averaging grid (deep leg)
  CMB_*                                          combinations of the best A and C settings
Judged on: the LOSS side (gross loss $, avg loss, worst day % of day-start equity, max DD, ulcer, max risk % of equity) against
return / PF / OOS PF / months positive; hold_loss = max DD not > ref + 0.5 pt AND worst day not worse than ref - 0.5 pt;
reduce_loss = gross loss $ < ref AND avg loss $ < ref; better_rd = return/DD > ref.
Resumable: one json per variant in study_results/v14_levers/, summary -> study_results/v14_levers.csv (rewritten every 5 runs).

    nohup python3 run_v14_levers.py --csv data/xauusd_m1.csv > logs/v14_levers.log 2>&1 &
    python3 run_v14_levers.py --stress name1,name2        # 6 stress scenarios each -> v14_stress.csv
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
from v14_common import CSV, OOS_SPLIT, judge, load_year, v13a_config  # noqa: E402

OUT = Path("study_results/v14_levers")
GATES = {"": "", "htf": "mart_tfs=M10|M15|M30|H1", "buy": "mart_sides=buy", "htfbuy": "mart_tfs=M10|M15|M30|H1,mart_sides=buy",
         "q60": "mart_min_quality=0.60", "trend": "mart_regime=trend", "range": "mart_regime=range", "m5": "mart_tfs=M5",
         "sell": "mart_sides=sell"}
LADDERS = {"tight": "0.5|1.0|1.5|2.5", "two": "0.6|1.5", "one1": "1.0", "three": "0.6|1.2|2.4"}
LOCKS = {"": "", "l03": "0|0.3|x|x", "be2": "0|0|x|x"}


def j(*parts: str) -> str:
    return ",".join(p for p in parts if p)


def variants() -> dict[str, str]:
    v: dict[str, str] = {"ref": ""}
    # --- MU: multiplier x cap x max risk, ungated
    for mult in (1.25, 1.5, 2.0):
        for cap in (1, 2, 3):
            for mr in (2, 3):
                v[f"MU_{mult}_c{cap}_r{mr}"] = f"mart_mode=mult,mart_mult={mult},mart_max_steps={cap},mart_max_risk_pct={mr}"
    # --- MU gated (where the post-loss edge is positive)
    for mult in (1.25, 1.5, 2.0):
        for gate in ("htf", "buy", "htfbuy", "q60", "trend"):
            v[f"MU_{mult}_c3_r3_{gate}"] = j(f"mart_mode=mult,mart_mult={mult},mart_max_steps=3,mart_max_risk_pct=3", GATES[gate])
    # --- MU asymmetric: gated step-up + step-down where the gate fails
    for mult in (1.25, 1.5, 2.0):
        for gate in ("htf", "buy", "htfbuy"):
            for dn in (0.5, 0.75):
                v[f"MU_{mult}_c3_r3_{gate}_dn{dn}"] = j(f"mart_mode=mult,mart_mult={mult},mart_max_steps=3,mart_max_risk_pct=3",
                                                       GATES[gate], f"mart_ungated_scale={dn}")
    for gate in ("htfbuy", "htf"):
        for dn in (0.25, 0.5):
            v[f"MU_1.0_c3_r3_{gate}_dn{dn}"] = j("mart_mode=mult,mart_mult=1.0,mart_max_steps=3,mart_max_risk_pct=3", GATES[gate],
                                                 f"mart_ungated_scale={dn}")      # pure step-DOWN of the weak slices after a loss
    # --- FIB / ADD / DEF
    for cap in (2, 3):
        for mr in (2, 3):
            v[f"FIB_c{cap}_r{mr}"] = f"mart_mode=fib,mart_max_steps={cap},mart_max_risk_pct={mr}"
    for gate in ("htf", "htfbuy"):
        v[f"FIB_c3_r3_{gate}"] = j("mart_mode=fib,mart_max_steps=3,mart_max_risk_pct=3", GATES[gate])
        v[f"FIB_c3_r3_{gate}_dn0.5"] = j("mart_mode=fib,mart_max_steps=3,mart_max_risk_pct=3", GATES[gate], "mart_ungated_scale=0.5")
    for slope in (1.25, 1.5, 2.0):
        v[f"ADD_{slope}_c3"] = f"mart_mode=add,mart_mult={slope},mart_max_steps=3,mart_max_risk_pct=3"
    v["ADD_1.5_c3_htfbuy"] = j("mart_mode=add,mart_mult=1.5,mart_max_steps=3,mart_max_risk_pct=3", GATES["htfbuy"])
    for r in (1.0, 2.0):
        for cap in (2, 3):
            v[f"DEF_{r}_c{cap}_r3"] = f"mart_mode=deficit,mart_deficit_r={r},mart_max_steps={cap},mart_max_risk_pct=3"
    v["DEF_2.0_c3_r3_htfbuy"] = j("mart_mode=deficit,mart_deficit_r=2.0,mart_max_steps=3,mart_max_risk_pct=3", GATES["htfbuy"])
    v["DEF_1.0_c3_r2_lr0.5"] = "mart_mode=deficit,mart_deficit_r=1.0,mart_max_steps=3,mart_max_risk_pct=2,mart_loss_r=0.5"
    # --- SHR: shrink after losses (everywhere, or only in the weak slices)
    for mult in (0.5, 0.75):
        for cap in (1, 2):
            v[f"SHR_{mult}_c{cap}"] = f"mart_mode=mult,mart_mult={mult},mart_max_steps={cap}"
        for gate in ("m5", "sell"):
            v[f"SHR_{mult}_c2_{gate}"] = j(f"mart_mode=mult,mart_mult={mult},mart_max_steps=2", GATES[gate])
    # --- ANTI (control)
    for mult in (1.2, 1.3, 1.5):
        v[f"ANTI_{mult}_c2"] = f"mart_mode=anti,mart_mult={mult},mart_max_steps=2,mart_max_risk_pct=3"
    # --- LAD: recovery ladder for the stepped-up plans
    for lad in LADDERS:
        for lk in ("", "l03"):
            if lad in ("one1", "two") and lk:
                continue
            lv = LADDERS[lad]
            fr = "|".join(["1"] * len(lv.split("|")))
            v[f"LAD_1.5_{lad}{('_' + lk) if lk else ''}"] = j("mart_mode=mult,mart_mult=1.5,mart_max_steps=3,mart_max_risk_pct=3",
                                                              GATES["htfbuy"], f"mart_tp_levels={lv},mart_tp_fracs={fr}",
                                                              f"mart_sl_after_leg={LOCKS[lk]}" if lk else "")
    # --- TF scope
    for mult in (1.5, 2.0):
        v[f"TF_{mult}_c3"] = f"mart_mode=mult,mart_mult={mult},mart_max_steps=3,mart_max_risk_pct=3,mart_scope=tf"
    v["TF_1.5_c3_htfbuy_dn0.5"] = j("mart_mode=mult,mart_mult=1.5,mart_max_steps=3,mart_max_risk_pct=3,mart_scope=tf", GATES["htfbuy"],
                                    "mart_ungated_scale=0.5")
    # --- loss definition
    v["MU_1.5_c3_r3_htfbuy_lr0.5"] = j("mart_mode=mult,mart_mult=1.5,mart_max_steps=3,mart_max_risk_pct=3,mart_loss_r=0.5", GATES["htfbuy"])
    v["MU_1.5_c3_r3_htfbuy_lr0.05"] = j("mart_mode=mult,mart_mult=1.5,mart_max_steps=3,mart_max_risk_pct=3,mart_loss_r=0.05", GATES["htfbuy"])
    # --- GR: zone grid
    for add_r in (0.3, 0.4, 0.5, 0.6):
        for base, add in ((0.5, 0.5), (0.6, 0.4), (0.7, 0.3), (0.5, 0.3), (0.6, 0.2)):
            v[f"GR_{add_r}_{base}/{add}"] = f"grid_add_r={add_r},grid_base_frac={base},grid_add_frac={add}"
    for add_r in (0.3, 0.5):
        for base, add in ((0.5, 0.5), (0.6, 0.4), (0.7, 0.3)):
            v[f"GR_{add_r}_{base}/{add}_own"] = f"grid_add_r={add_r},grid_base_frac={base},grid_add_frac={add},grid_deep_ladder=own"
    for gate_k, gate_v in (("htf", "grid_tfs=M10|M15|M30|H1"), ("m5", "grid_tfs=M5"), ("range", "grid_regime=range"), ("trend", "grid_regime=trend")):
        v[f"GR_0.5_0.6/0.4_{gate_k}"] = f"grid_add_r=0.5,grid_base_frac=0.6,grid_add_frac=0.4,{gate_v}"
        v[f"GR_0.5_0.5/0.5_own_{gate_k}"] = f"grid_add_r=0.5,grid_base_frac=0.5,grid_add_frac=0.5,grid_deep_ladder=own,{gate_v}"
    v["GR_0.5_0.5/0.5_keep"] = "grid_add_r=0.5,grid_base_frac=0.5,grid_add_frac=0.5,grid_cancel_on_partial=false"
    # --- CMB: asymmetric A + grid C
    for a_name in ("MU_1.5_c3_r3_htfbuy_dn0.5", "FIB_c3_r3_htfbuy_dn0.5", "MU_1.25_c3_r3_htf_dn0.5"):
        for g_name in ("GR_0.5_0.5/0.5_own", "GR_0.5_0.7/0.3", "GR_0.3_0.6/0.4"):
            v[f"CMB_{a_name}+{g_name}"] = j(v[a_name], v[g_name])
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
    tcfg = v13a_config().override(over)
    spec = spec_override(SymbolSpec(), extra_s)
    res = PortfolioSimulator(m1, sel, tcfg, spec).run()
    row = {"key": key, "name": name, "tag": tag, "overrides": over}
    row.update(judge(res))
    tr = res.trades
    if len(tr):
        tr = tr.assign(month=tr.close_time.dt.strftime("%Y-%m"))
        row["monthly_$"] = tr.groupby("month").net.sum().round(2).to_dict()
        row["monthly_R"] = tr.groupby("month").r_net.sum().round(2).to_dict()
        row["by_tf_net"] = tr.groupby("tf").net.sum().round(2).to_dict()
        row["outcomes"] = tr.outcome.value_counts().to_dict()
        up = tr[tr.mart_step > 0]
        dn = tr[tr.mart_step < 0]
        deep = tr[tr.grid_leg]
        row["up_n"], row["up_net"], row["up_win_%"] = len(up), round(up.net.sum(), 2), round(100 * (up.net > 0).mean(), 1) if len(up) else np.nan
        row["dn_n"], row["dn_net"], row["dn_win_%"] = len(dn), round(dn.net.sum(), 2), round(100 * (dn.net > 0).mean(), 1) if len(dn) else np.nan
        row["deep_n"], row["deep_net"], row["deep_win_%"] = len(deep), round(deep.net.sum(), 2), round(100 * (deep.net > 0).mean(), 1) if len(deep) else np.nan
        row["OOS_win_%"] = round(100 * (tr[tr.close_time >= OOS_SPLIT].net > 0).mean(), 1)
        tr.to_csv(out / f"{key}_trades.csv", index=False)
    res.equity.to_csv(out / f"{key}_equity.csv")
    row["secs"] = round(time.time() - t0, 1)
    tmp = out / f"{key}.json.tmp"
    json.dump(row, open(tmp, "w"), indent=1, default=str)
    os.replace(tmp, f)
    return row


def summarize(rows: list[dict], ref_name: str = "ref", path: str = "study_results/v14_levers.csv") -> pd.DataFrame:
    df = pd.DataFrame(rows)
    ref = df[df.name == ref_name].iloc[0]
    df["d_ret"] = (df["return_%"] - ref["return_%"]).round(1)
    df["d_dd"] = (df["max_dd_%"] - ref["max_dd_%"]).round(2)
    df["d_pf"] = (df.profit_factor - ref.profit_factor).round(3)
    df["d_loss$"] = (df["gross_loss_$"] - ref["gross_loss_$"]).round(0)
    df["d_avgloss"] = (df["avg_loss_$"] - ref["avg_loss_$"]).round(1)
    df["d_wd"] = (df["worst_day_%eq"] - ref["worst_day_%eq"]).round(2)
    df["d_oos_pf"] = (df.OOS_PF - ref.OOS_PF).round(3)
    df["d_rd"] = (df.return_over_dd - ref.return_over_dd).round(1)
    df["hold_loss"] = (df["max_dd_%"] >= ref["max_dd_%"] - 0.5) & (df["worst_day_%eq"] >= ref["worst_day_%eq"] - 0.5) & \
                      (df.months_pos >= ref.months_pos - 1)
    df["reduce_loss"] = (df["gross_loss_$"] > ref["gross_loss_$"]) & (df["avg_loss_$"] > ref["avg_loss_$"])
    df["better_rd"] = df.return_over_dd > ref.return_over_dd
    df["keep_return"] = df["return_%"] >= ref["return_%"] - 5.0
    df["keep_oos"] = df.OOS_PF >= ref.OOS_PF - 0.05
    df["score"] = df.hold_loss.astype(int) + df.reduce_loss.astype(int) + df.better_rd.astype(int) + df.keep_return.astype(int) + df.keep_oos.astype(int)
    df = df.sort_values(["score", "return_over_dd"], ascending=False)
    df.to_csv(path, index=False)
    return df


COLS = ["name", "trades", "return_%", "max_dd_%", "profit_factor", "win_%", "gross_loss_$", "avg_loss_$", "worst_day_%eq", "max_risk_%eq",
        "ulcer", "return_over_dd", "OOS_PF", "months_pos", "up_n", "dn_n", "deep_n", "hold_loss", "reduce_loss", "better_rd", "keep_return",
        "keep_oos", "score"]


def show(r: dict) -> None:
    print(f"{r['key']:<44} n {r['trades']:4d} ret {r['return_%']:+7.1f}% DD {r['max_dd_%']:6.2f} PF {r['profit_factor']:5.3f} "
          f"loss$ {r['gross_loss_$']:8.0f} avgL {r['avg_loss_$']:7.1f} wd {r['worst_day_%eq']:5.2f} mxR {r['max_risk_%eq']:4.2f} "
          f"ulc {r['ulcer']:5.3f} r/dd {r['return_over_dd']:5.1f} OOS {r['OOS_PF']:4.2f} mo {r['months_pos']}/{r['months']} "
          f"up {r.get('up_n', 0):3d} dn {r.get('dn_n', 0):3d} deep {r.get('deep_n', 0):3d} [{r['secs']:.0f}s]", flush=True)


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
            summarize([x for x in rows if not x["tag"]], path="study_results/v14_levers_partial.csv")
            done_since_save = 0
    base = [r for r in rows if not r["tag"]]
    path = "study_results/v14_levers.csv" if not (a.only or a.stress) else "study_results/v14_levers_partial.csv"
    df = summarize(base, path=path)
    if a.stress:
        pd.DataFrame([r for r in rows if r["tag"]]).to_csv("study_results/v14_stress.csv", index=False)
    pd.set_option("display.width", 320)
    print("\n=== v14 GRID ===\n" + df[COLS].to_string(index=False))


if __name__ == "__main__":
    main()
