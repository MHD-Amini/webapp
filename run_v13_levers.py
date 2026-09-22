#!/usr/bin/env python3
"""v13 step 3 - LEVER GRID on top of v12-A (the trader shipped in run_trader.bat): regime-adaptive management.

Reference (v12-A): 427 trades, +179.5 %, max DD 5.28 %, PF 1.874, win 72.6 %, OOS PF 1.78, Apr 2026 -0.72 R (the negative month),
Sep 2025 +3.35 R (weak / partial month).

Families (every run = full year Sep25-Sep26 through the M1 portfolio simulator, ~15 s):
  RG_<metric><thr>_<ladder>[_<lock>][_<tfs>]  regime lever: plans placed while metric < thr use the alternative ladder / stop schedule
  LAD_<ladder>                                the alternative ladder for EVERY plan (is the regime switch needed at all?)
  LOCK_<lock>                                 stop schedule for every plan
  RISK_<metric><thr>_<x>                      risk scale in the range regime
Judged on: Apr26 R, Sep25 R, worst month, months positive, AND the full-year / OOS loss band of v12 (hold_loss / hold_oos).
Resumable: one json per variant in study_results/v13_levers/, summary -> study_results/v13_levers.csv.

    python run_v13_levers.py --csv data/xauusd_m1.csv --workers 2 [--only a,b] [--stress name1,name2]
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backtest_trader import load_selections, spec_override  # noqa: E402
from lubot import load_mt5_csv  # noqa: E402
from lubot.execution import SymbolSpec  # noqa: E402
from lubot.portfolio_sim import PortfolioSimulator  # noqa: E402
from run_rm_study import KEYS  # noqa: E402
from run_v12_funnel import TFS  # noqa: E402
from run_v12_levers import STRESS  # noqa: E402
from run_v13_diag import v12a_config  # noqa: E402

OUT = Path("study_results/v13_levers")
OOS_SPLIT = "2026-03-01"
WEAK = ("2026-04", "2025-09")

LADDERS = {
    "G": "0.6|1.2|2.4|4.8", "tight": "0.5|1.0|1.5|2.5", "t2": "0.5|1.0|2.0|3.0", "t3": "0.4|0.8|1.2|2.0", "mid": "0.6|1.2|1.8|3.0",
    "two15": "0.6|1.5", "two24": "0.6|2.4", "one1": "1.0", "one15": "1.5", "three": "0.6|1.2|2.4",
}
FRACS = {"x": None, "front": "5|2|2|1", "back": "1|2|3|4"}       # None = equal
LOCKS = {"": "", "be2": "0|0|x|x", "l03": "0|0.3|x|x", "l03_10": "0|0.3|1.0|x", "l05": "0|0.5|x|x"}
METRICS = {"adr": "adr_ratio", "er": "er", "erl": "er", "adrp": "adr_pct"}     # erl = er over 10 days
THRESHOLDS = {"adr": (0.8, 0.9, 1.0, 1.1), "er": (0.2, 0.3, 0.4, 0.5), "erl": (0.2, 0.3, 0.4), "adrp": (2.0, 2.5, 3.0)}


def ladder_over(lad: str, frac: str = "x", prefix: str = "range_") -> str:
    lv = LADDERS[lad]
    fr = FRACS[frac] or "|".join(["1"] * len(lv.split("|")))
    return f"{prefix}tp_levels={lv},{prefix}tp_fracs={fr}"


def regime_over(met: str, thr: float) -> str:
    extra = ",regime_short=10" if met == "erl" else ""
    return f"regime_metric={METRICS[met]},regime_threshold={thr}{extra}"


def variants() -> dict[str, str]:
    """name -> TraderConfig override string on top of v12-A."""
    v: dict[str, str] = {"ref": ""}
    # --- LAD / LOCK: the alternative management for EVERY plan (no regime switch)
    for lad in LADDERS:
        if lad != "G":
            v[f"LAD_{lad}"] = ladder_over(lad, prefix="")
    for fr in ("front", "back"):
        v[f"LAD_G_{fr}"] = ladder_over("G", fr, prefix="")
    for lk, s in LOCKS.items():
        if lk:
            v[f"LOCK_{lk}"] = f"sl_after_leg={s}"
    # --- RG: regime switch x ladder (equal fractions, no lock)
    for met, thrs in THRESHOLDS.items():
        for thr in thrs:
            for lad in ("tight", "t2", "t3", "mid", "two15", "one1", "three"):
                v[f"RG_{met}{thr}_{lad}"] = ",".join([regime_over(met, thr), ladder_over(lad)])
    # --- RG with the G ladder kept but a stop lock in the range regime
    for met, thrs in (("adr", (0.9, 1.0)), ("er", (0.3, 0.4))):
        for thr in thrs:
            for lk in ("be2", "l03", "l03_10", "l05"):
                v[f"RG_{met}{thr}_G_{lk}"] = ",".join([regime_over(met, thr), ladder_over("G"), f"range_sl_after_leg={LOCKS[lk]}"])
            # tight ladder + lock
            for lk in ("be2", "l03"):
                v[f"RG_{met}{thr}_tight_{lk}"] = ",".join([regime_over(met, thr), ladder_over("tight"), f"range_sl_after_leg={LOCKS[lk]}"])
            # tight ladder, front-loaded
            v[f"RG_{met}{thr}_tight_front"] = ",".join([regime_over(met, thr), ladder_over("tight", "front")])
    # --- RG restricted to timeframes
    for met, thr in (("adr", 0.9), ("er", 0.3)):
        for tfs, tag in (("M5", "m5"), ("M5|M10", "m5m10"), ("M10|M15|M30|H1", "htf")):
            v[f"RG_{met}{thr}_tight_{tag}"] = ",".join([regime_over(met, thr), ladder_over("tight"), f"range_tfs={tfs}"])
    # --- RISK scale in the range regime (on top of the tight ladder and alone)
    for met, thr in (("adr", 0.9), ("er", 0.3)):
        for x in (0.5, 0.75, 1.5):
            v[f"RISK_{met}{thr}_{x}"] = ",".join([regime_over(met, thr), f"range_risk_scale={x}"])
            v[f"RISK_{met}{thr}_{x}_tight"] = ",".join([regime_over(met, thr), ladder_over("tight"), f"range_risk_scale={x}"])
    # --- window variants of the best metrics
    for s, l in ((3, 20), (5, 10), (5, 30), (10, 40)):
        v[f"RG_adr0.9_tight_w{s}_{l}"] = ",".join([f"regime_metric=adr_ratio,regime_threshold=0.9,regime_short={s},regime_long={l}", ladder_over("tight")])
    for s in (3, 7, 10):
        v[f"RG_er0.3_tight_s{s}"] = ",".join([f"regime_metric=er,regime_threshold=0.3,regime_short={s}", ladder_over("tight")])
    # --- NEIGHBOURHOOD v13-A (session 2, robustness of RG_adr1.0_tight_l03): threshold +-0.05, ADR windows, lock variants
    for thr in (0.95, 1.05):
        v[f"RG_adr{thr}_tight_l03"] = ",".join([regime_over("adr", thr), ladder_over("tight"), f"range_sl_after_leg={LOCKS['l03']}"])
    for s, l in ((3, 20), (5, 30), (7, 20), (5, 15)):
        v[f"RG_adr1.0_tight_l03_w{s}_{l}"] = ",".join([f"regime_metric=adr_ratio,regime_threshold=1.0,regime_short={s},regime_long={l}",
                                                       ladder_over("tight"), f"range_sl_after_leg={LOCKS['l03']}"])
    for lk in ("l03_10", "l05"):
        v[f"RG_adr1.0_tight_{lk}"] = ",".join([regime_over("adr", 1.0), ladder_over("tight"), f"range_sl_after_leg={LOCKS[lk]}"])
    v["RG_adr1.0_tight_l03_front"] = ",".join([regime_over("adr", 1.0), ladder_over("tight", "front"), f"range_sl_after_leg={LOCKS['l03']}"])
    v["RG_adr1.0_t2_l03"] = ",".join([regime_over("adr", 1.0), ladder_over("t2"), f"range_sl_after_leg={LOCKS['l03']}"])
    return v


def run_one(name: str, over: str, m1, sel, extra_s: str = "", tag: str = "", out: Path = OUT) -> dict:
    key = f"{name}{('__' + tag) if tag else ''}"
    f = out / f"{key}.json"
    if f.exists():
        try:
            return json.load(open(f))
        except Exception:
            pass
    t0 = time.time()
    tcfg = v12a_config().override(over)
    spec = spec_override(SymbolSpec(), extra_s)
    res = PortfolioSimulator(m1, sel, tcfg, spec).run()
    s = res.summary()
    row = {"key": key, "name": name, "tag": tag, "overrides": over, **{k: s.get(k) for k in KEYS}}
    row.update({"pending_placed": s.get("pending_placed"), "cancelled": s.get("cancelled"), "daily_halts": s.get("daily_halts"),
                "halted": s.get("halted"), "range_trades": s.get("range_trades"), "range_plans": s.get("range_plans")})
    tr = res.trades
    if len(tr):
        tr = tr.assign(month=tr.close_time.dt.strftime("%Y-%m"))
        for lab, part in (("IS", tr[tr.close_time < OOS_SPLIT]), ("OOS", tr[tr.close_time >= OOS_SPLIT])):
            row[f"{lab}_n"] = len(part)
            row[f"{lab}_R"] = round(part.r_net.sum(), 2)
            row[f"{lab}_net_$"] = round(part.net.sum(), 2)
            row[f"{lab}_win_%"] = round(100 * (part.net > 0).mean(), 1) if len(part) else np.nan
            row[f"{lab}_PF"] = round(part[part.net > 0].net.sum() / abs(part[part.net < 0].net.sum()), 3) if (part.net < 0).any() else np.inf
            row[f"{lab}_avg_R"] = round(part.r_net.mean(), 4) if len(part) else np.nan
            row[f"{lab}_sl_%"] = round(100 * (part.outcome == "sl").mean(), 1) if len(part) else np.nan
        eq = res.equity.equity
        row["max_dd_%"] = round(100 * (eq / eq.cummax() - 1).min(), 2)
        mo = tr.groupby("month").r_net.sum()
        mo_usd = tr.groupby("month").net.sum()
        row["months_pos"] = int((mo_usd > 0).sum())
        row["months"] = int(len(mo))
        row["worst_month_$"] = round(mo_usd.min(), 2)
        row["worst_month_R"] = round(mo.min(), 2)
        row["apr26_R"] = round(mo.get("2026-04", 0.0), 2)
        row["sep25_R"] = round(mo.get("2025-09", 0.0), 2)
        row["apr26_$"] = round(mo_usd.get("2026-04", 0.0), 2)
        row["sep25_$"] = round(mo_usd.get("2025-09", 0.0), 2)
        row["weak_R"] = round(row["apr26_R"] + row["sep25_R"], 2)
        # the "other 11 months" must not get worse
        row["other_R"] = round(mo[~mo.index.isin(WEAK)].sum(), 2)
        row["worst_day_%"] = round(100 * eq.resample("1D").last().dropna().pct_change().min(), 2)
        day_start = eq.groupby(eq.index.date).transform("first")
        row["worst_intraday_%"] = round(100 * (eq / day_start - 1).min(), 2)
        row["by_tf_n"] = tr.groupby("tf").size().to_dict()
        row["by_tf_R"] = tr.groupby("tf").r_net.sum().round(2).to_dict()
        row["outcomes"] = tr.outcome.value_counts().to_dict()
        row["monthly_$"] = mo_usd.round(2).to_dict()
        row["monthly_R"] = mo.round(2).to_dict()
        rg = tr[tr.regime == "range"]
        row["range_n"] = int(len(rg))
        row["range_R"] = round(rg.r_net.sum(), 2) if len(rg) else 0.0
        row["range_win_%"] = round(100 * (rg.net > 0).mean(), 1) if len(rg) else np.nan
        row["range_OOS_R"] = round(rg[rg.close_time >= OOS_SPLIT].r_net.sum(), 2) if len(rg) else 0.0
        l = (tr.net < 0).astype(int).to_numpy()
        best = cur = 0
        for x in l:
            cur = cur + 1 if x else 0
            best = max(best, cur)
        row["max_consec_losses"] = int(best)
        tr.to_csv(out / f"{key}_trades.csv", index=False)
    res.equity.to_csv(out / f"{key}_equity.csv")
    row["secs"] = round(time.time() - t0, 1)
    tmp = out / f"{key}.json.tmp"
    json.dump(row, open(tmp, "w"), indent=1, default=str)
    os.replace(tmp, f)
    return row


_G: dict = {}


def _init(csv: str, start: str):
    m1 = load_mt5_csv(csv)[start:]
    sel = pd.concat([load_selections(f"study_results/sel_v10_{tf}.pkl") for tf in TFS],
                    ignore_index=True).sort_values("t", kind="stable").reset_index(drop=True)
    _G["m1"], _G["sel"] = m1, sel


def _job(args):
    name, over, extra_s, tag = args
    return run_one(name, over, _G["m1"], _G["sel"], extra_s=extra_s, tag=tag)


def summarize(rows: list[dict], ref_name: str = "ref", path: str = "study_results/v13_levers.csv") -> pd.DataFrame:
    df = pd.DataFrame(rows)
    ref = df[df.name == ref_name].iloc[0]
    df["d_trades"] = df.trades - ref.trades
    df["d_ret"] = (df["return_%"] - ref["return_%"]).round(1)
    df["d_dd"] = (df["max_dd_%"] - ref["max_dd_%"]).round(2)
    df["d_pf"] = (df.profit_factor - ref.profit_factor).round(3)
    df["d_win"] = (df["win_%"] - ref["win_%"]).round(1)
    df["d_apr"] = (df.apr26_R - ref.apr26_R).round(2)
    df["d_sep"] = (df.sep25_R - ref.sep25_R).round(2)
    df["d_other"] = (df.other_R - ref.other_R).round(2)
    df["d_oos_R"] = (df.OOS_R - ref.OOS_R).round(2)
    # v12 loss band (full year): DD not deeper than ref + 0.5 pt, PF >= ref - 0.05, win >= ref - 3, worst day >= ref - 0.5
    df["hold_loss"] = (df["max_dd_%"] >= ref["max_dd_%"] - 0.5) & (df.profit_factor >= ref.profit_factor - 0.05) & \
                      (df["win_%"] >= ref["win_%"] - 3.0) & (df["worst_day_%"] >= ref["worst_day_%"] - 0.5)
    df["hold_oos"] = (df["OOS_PF"] >= ref["OOS_PF"] - 0.05) & (df["OOS_win_%"] >= ref["OOS_win_%"] - 3.0) & \
                     (df["OOS_sl_%"] <= ref["OOS_sl_%"] + 2.0) & (df["max_dd_%"] >= ref["max_dd_%"] - 0.5)
    # the v13 goal: both weak months better, no month negative, the other months not worse than -3 R in total
    df["fix_weak"] = (df.apr26_R > 0) & (df.sep25_R >= ref.sep25_R - 0.5) & (df.worst_month_R > 0) & (df.d_other >= -3.0)
    df["ret_dd"] = (df["return_%"] / df["max_dd_%"].abs()).round(2)
    df = df.sort_values(["fix_weak", "hold_oos", "hold_loss", "return_%"], ascending=False)
    df.to_csv(path, index=False)
    return df


COLS = ["name", "trades", "return_%", "max_dd_%", "profit_factor", "win_%", "sl_%", "worst_day_%", "OOS_R", "OOS_PF", "apr26_R", "sep25_R",
        "worst_month_R", "months_pos", "d_other", "range_n", "range_R", "hold_loss", "hold_oos", "fix_weak"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="data/xauusd_m1.csv")
    ap.add_argument("--from", dest="start", default="2025-09-01")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--only", default="", help="comma list of variant names")
    ap.add_argument("--stress", default="", help="comma list of variant names to stress (6 scenarios each)")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    v = variants()
    if a.only:
        v = {"ref": "", **{k: v[k] for k in a.only.split(",")}}
    todo = [(k, o, "", "") for k, o in v.items()]
    if a.stress:
        allv = variants()
        for n in a.stress.split(","):
            for tag, (et, es) in STRESS.items():
                todo.append((n, ",".join(x for x in (allv[n], et) if x), es, tag))
    print(f"{len(todo)} runs, {sum(1 for k, _, _, tag in todo if not (OUT / (k + ('__' + tag if tag else '') + '.json')).exists())} to run",
          flush=True)
    rows = []

    def show(r):
        print(f"{r['key']:<36} n {r['trades']:4d} ret {r['return_%']:+7.1f}% DD {r['max_dd_%']:6.2f}% PF {r['profit_factor']:5.3f} "
              f"win {r['win_%']:4.1f} sl {r['sl_%']:4.1f} wd {r.get('worst_day_%', 0):5.2f} OOS {r.get('OOS_R', 0):+6.1f}R/{r.get('OOS_PF', 0):4.2f} "
              f"Apr {r.get('apr26_R', 0):+5.1f} Sep {r.get('sep25_R', 0):+5.1f} worst_mo {r.get('worst_month_R', 0):+5.1f} "
              f"pos {r.get('months_pos', 0)}/{r.get('months', 0)} range {r.get('range_n', 0):3d}/{r.get('range_R', 0):+6.1f}", flush=True)

    if a.workers > 1:
        with ProcessPoolExecutor(a.workers, initializer=_init, initargs=(a.csv, a.start)) as ex:
            for r in ex.map(_job, todo):
                rows.append(r)
                show(r)
    else:
        _init(a.csv, a.start)
        for t in todo:
            r = _job(t)
            rows.append(r)
            show(r)
    base = [r for r in rows if not r["tag"]]
    path = "study_results/v13_levers.csv" if not a.only else "study_results/v13_levers_partial.csv"
    df = summarize(base, path=path)
    if a.stress:
        pd.DataFrame([r for r in rows if r["tag"]]).to_csv("study_results/v13_stress.csv", index=False)
    pd.set_option("display.width", 300)
    print("\n=== v13 GRID ===\n" + df[COLS].to_string(index=False))


if __name__ == "__main__":
    main()
