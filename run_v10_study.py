#!/usr/bin/env python3
"""v10 - MULTI-TP STUDY: does closing in MORE THAN TWO take-profit legs raise profitability?

Entries are the v8 recommended trader (v8 M5 filter, min_quality 0.60 elsewhere, 1 % risk, real costs) - only the exit
management changes.  Reference systems: the current spec (50 % @ 0.4R -> BE, TP2 1.5R) and the v9 recommendation
(25 % @ 0.6R -> BE, TP2 2.5R / 3R).  Families (all executable by the live bot as N limit legs with server-side targets):

  L3 / L4 / L5   3-, 4-, 5-leg target ladders: level sets x fraction splits x stop schedule
                 stop schedules: classic (BE after leg 1) | be2 (BE only after leg 2, a dip after leg 1 survives) |
                 ratchet (BE after leg 1, then stop -> previous target after every further leg) | be2ratchet |
                 lock (BE after leg 1, +0.5R after leg 2, then previous targets)
  R              runner ladders: the last leg has NO target and is trailed (trail_r) once k legs closed (trail_after_leg)
  ATR            ladders measured in ATR of the POI's timeframe instead of R (tp_unit=atr), 2-5 legs
  G              geometric / fibonacci ladders (0.5-1-2-4, 0.6-1-1.6-2.6-4.2, ...)
  A2             the v9 two-leg plateau re-run under the v10 code (parity + reference)

Two evaluations, same code as the v9 study so the numbers are comparable:
  --mode oos : realistic PORTFOLIO simulation 2026-03-02 -> 2026-09-04 (model never saw it) -> study_results/v10_study/
  --mode is  : IN-SAMPLE replay of every plan the trader would have taken Jan 2025 -> Feb 2026 (1 270 plans)
               -> study_results/v10_insample/
Resumable: one json per variant, finished variants are skipped, jsons are written atomically.

    python run_v10_study.py --mode oos --workers 2
    python run_v10_study.py --mode is  --workers 2
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backtest_trader import load_selections  # noqa: E402
from lubot import load_mt5_csv  # noqa: E402
from lubot.execution import SymbolSpec, TraderConfig  # noqa: E402
from lubot.portfolio_sim import PortfolioSimulator  # noqa: E402
from run_rm_study import FLT, summarize  # noqa: E402
import rm_insample  # noqa: E402

# v9 BASE + v10: ladder legs below the broker minimum are MERGED (not rejected) so every management trades the same
# population.  Two-leg systems use the v9 sizing path -> their numbers are identical to the v9 study.
BASE = ("risk_pct=1.0,exec_mode=split,sl_slippage=0.10,market_slippage=0.05,max_open_positions=4,dedupe_overlap=0.5,"
        "ladder_fallback=merge")
OUT_OOS = Path("study_results/v10_study")
OUT_IS = Path("study_results/v10_insample")


# ----------------------------------------------------------------------------- the grid
def _lv(levels) -> str:
    return "|".join(str(x) for x in levels)


def _name_lv(levels) -> str:
    return "-".join(("R" if x == 0 else str(x)) for x in levels)


def _stop_variants(levels: tuple) -> dict[str, str]:
    """stop-schedule name -> TraderConfig override fragment for a ladder with these levels."""
    n = len(levels)
    fixed = [x for x in levels if x > 0]
    out: dict[str, str | None] = {"classic": "", "ratchet": "ratchet_sl=true"}
    if n >= 3:
        out["be2"] = "sl_after_leg=" + "|".join(["x", "0"] + ["x"] * (n - 3))
    if n >= 4:
        # be2ratchet: nothing after leg 1, BE after leg 2, then the previous fixed target after every further leg
        out["be2ratchet"] = "sl_after_leg=" + "|".join(["x", "0"] + [str(fixed[k - 1]) for k in range(2, n - 1)])
        # lock: BE after leg 1, +0.5R after leg 2, then previous targets
        out["lock"] = "sl_after_leg=" + "|".join(["0", "0.5"] + [str(fixed[k - 1]) for k in range(2, n - 1)])
    return {k: v for k, v in out.items() if v is not None}


def grid() -> dict[str, str]:
    g: dict[str, str] = {}
    g["base_v8"] = ""                                                                   # current spec
    g["v9_p0.6_f0.25_tp2.5"] = "partial_r=0.6,partial_frac=0.25,tp2_r=2.5"             # v9 recommendation
    g["v9_p0.6_f0.25_tp3.0"] = "partial_r=0.6,partial_frac=0.25,tp2_r=3.0"             # v9 twin
    # A2. the v9 two-leg plateau (reference under the v10 code)
    for pr, pf, tp in itertools.product((0.6, 0.8, 1.0), (0.25, 0.33, 0.5), (2.0, 2.5, 3.0, 4.0)):
        g[f"A2_p{pr}_f{pf}_tp{tp}"] = f"partial_r={pr},partial_frac={pf},tp2_r={tp}"
    # L3. three legs
    L3 = [(0.6, 1.5, 2.5), (0.6, 1.5, 3.0), (0.6, 2.5, 4.0), (0.6, 1.2, 2.5), (0.6, 1.0, 1.5), (0.6, 1.5, 4.0), (0.6, 2.0, 3.0),
          (0.4, 1.0, 2.0), (0.4, 1.5, 3.0), (0.5, 1.0, 2.0), (0.8, 1.5, 2.5), (0.8, 2.0, 3.0), (1.0, 2.0, 3.0), (1.0, 2.5, 4.0),
          (0.6, 1.5, 0), (0.6, 2.5, 0), (1.0, 2.0, 0)]
    F3 = {"25_25_50": "0.25|0.25|0.5", "50_25_25": "0.5|0.25|0.25", "33_33_33": "0.34|0.33|0.33", "20_30_50": "0.2|0.3|0.5",
          "25_50_25": "0.25|0.5|0.25", "20_40_40": "0.2|0.4|0.4"}
    for lv in L3:
        for fn, fr in F3.items():
            for sn, so in _stop_variants(lv).items():
                over = f"tp_levels={_lv(lv)},tp_fracs={fr}" + (("," + so) if so else "")
                if lv[-1] == 0:
                    over += ",trail_r=0.7,trail_after_leg=2"             # a runner needs a trail to ever exit
                g[f"L3_{_name_lv(lv)}_{fn}_{sn}"] = over
    # L4. four legs
    L4 = [(0.6, 1.2, 2.0, 3.0), (0.5, 1.0, 1.5, 2.5), (0.4, 0.8, 1.5, 3.0), (0.6, 1.5, 2.5, 4.0), (0.6, 1.0, 2.0, 3.0),
          (0.4, 1.0, 2.0, 3.0), (1.0, 2.0, 3.0, 4.0), (0.6, 1.5, 2.5, 3.5), (0.8, 1.5, 2.5, 4.0), (0.6, 1.5, 2.5, 0),
          (0.5, 1.0, 2.0, 0)]
    F4 = {"25x4": "0.25|0.25|0.25|0.25", "20_20_20_40": "0.2|0.2|0.2|0.4", "40_20_20_20": "0.4|0.2|0.2|0.2",
          "10_20_30_40": "0.1|0.2|0.3|0.4", "30_30_20_20": "0.3|0.3|0.2|0.2", "15_25_30_30": "0.15|0.25|0.3|0.3"}
    for lv in L4:
        for fn, fr in F4.items():
            for sn, so in _stop_variants(lv).items():
                over = f"tp_levels={_lv(lv)},tp_fracs={fr}" + (("," + so) if so else "")
                if lv[-1] == 0:
                    over += ",trail_r=1.0,trail_after_leg=3"
                g[f"L4_{_name_lv(lv)}_{fn}_{sn}"] = over
    # L5. five legs
    L5 = [(0.4, 0.8, 1.2, 1.6, 2.0), (0.5, 1.0, 1.5, 2.0, 3.0), (0.6, 1.0, 1.5, 2.5, 4.0), (0.6, 1.2, 1.8, 2.5, 3.5),
          (0.5, 1.0, 2.0, 3.0, 5.0), (0.6, 1.5, 2.5, 3.5, 5.0), (0.4, 1.0, 1.5, 2.5, 0)]
    F5 = {"20x5": "0.2|0.2|0.2|0.2|0.2", "10_15_20_25_30": "0.1|0.15|0.2|0.25|0.3", "30_25_20_15_10": "0.3|0.25|0.2|0.15|0.1",
          "15_15_20_25_25": "0.15|0.15|0.2|0.25|0.25"}
    for lv in L5:
        for fn, fr in F5.items():
            for sn, so in _stop_variants(lv).items():
                if sn == "lock":
                    continue
                over = f"tp_levels={_lv(lv)},tp_fracs={fr}" + (("," + so) if so else "")
                if lv[-1] == 0:
                    over += ",trail_r=1.0,trail_after_leg=4"
                g[f"L5_{_name_lv(lv)}_{fn}_{sn}"] = over
    # R. runner ladders: trail distance x activation leg
    for lv, fr in (((0.6, 1.5, 0), "0.25|0.25|0.5"), ((0.6, 2.5, 0), "0.25|0.5|0.25"), ((0.6, 1.5, 2.5, 0), "0.25|0.25|0.25|0.25")):
        for tr in (0.5, 0.7, 1.0, 1.5):
            for k in range(1, len(lv)):
                g[f"R_{_name_lv(lv)}_trail{tr}_after{k}"] = f"tp_levels={_lv(lv)},tp_fracs={fr},trail_r={tr},trail_after_leg={k}"
    # ATR. ladders in ATR units (2-5 legs)
    for pr, pf, tp in itertools.product((0.3, 0.5, 1.0), (0.25, 0.5), (1.0, 1.5, 2.0, 3.0)):
        if tp > pr:
            g[f"ATR2_p{pr}_f{pf}_tp{tp}"] = f"tp_unit=atr,partial_r={pr},partial_frac={pf},tp2_r={tp}"
    for lv in ((0.5, 1.0, 2.0), (0.3, 0.8, 1.5), (0.5, 1.0, 1.5, 2.5), (0.5, 1.0, 2.0, 3.0), (0.3, 0.6, 1.0, 1.5, 2.5)):
        for fn, fr in {"eq": "|".join(["1"] * len(lv)), "asc": "|".join(str(i + 1) for i in range(len(lv)))}.items():
            for sn in ("classic", "be2"):
                so = _stop_variants(lv)[sn]
                g[f"ATR{len(lv)}_{_name_lv(lv)}_{fn}_{sn}"] = f"tp_unit=atr,tp_levels={_lv(lv)},tp_fracs={fr}" + (("," + so) if so else "")
    # G. geometric / fibonacci ladders
    for lv in ((0.5, 1.0, 2.0, 4.0), (0.6, 1.0, 1.6, 2.6, 4.2), (0.6, 1.2, 2.4, 4.8), (1.0, 2.0, 4.0), (0.6, 1.0, 1.6, 2.6)):
        for fn, fr in {"eq": "|".join(["1"] * len(lv)), "desc": "|".join(str(len(lv) - i) for i in range(len(lv)))}.items():
            for sn in ("classic", "be2", "ratchet"):
                so = _stop_variants(lv)[sn]
                g[f"G_{_name_lv(lv)}_{fn}_{sn}"] = f"tp_levels={_lv(lv)},tp_fracs={fr}" + (("," + so) if so else "")
    return g


# ----------------------------------------------------------------------------- OOS runner (portfolio)
_M1 = None
_SEL = None


def _init_oos(csv: str, start: str):
    global _M1, _SEL
    _M1 = load_mt5_csv(csv)[start:]
    _SEL = pd.concat([load_selections("study_results/sel_v8_M5.pkl")] +
                     [load_selections(f"study_results/sel_v7_{tf}.pkl") for tf in ("M10", "M15", "M30", "H1")],
                     ignore_index=True).sort_values("t", kind="stable").reset_index(drop=True)


def run_oos(name: str, over: str, start: str, mid: str) -> dict:
    f = OUT_OOS / f"{name}.json"
    if f.exists():
        return json.load(open(f))
    t0 = time.time()
    tcfg = TraderConfig().override(BASE + ("," + over if over else ""))
    tcfg.trade_filter = FLT
    res = PortfolioSimulator(_M1, _SEL, tcfg, SymbolSpec(), start=start).run()
    row = summarize(name, over, res, mid)
    row["skipped_sizing"] = int(sum(1 for _, r in res.sim.skipped if "cannot be split" in r or "too small" in r))
    if len(res.trades):
        res.trades.to_csv(OUT_OOS / f"{name}_trades.csv", index=False)
    res.equity.to_csv(OUT_OOS / f"{name}_equity.csv")
    row["secs"] = round(time.time() - t0, 1)
    tmp = OUT_OOS / f"{name}.json.tmp"
    json.dump(row, open(tmp, "w"), indent=1, default=str)
    os.replace(tmp, f)
    return row


# ----------------------------------------------------------------------------- IS runner (single-plan replay)
def _init_is(csv: str):
    rm_insample.OUT = OUT_IS
    rm_insample.BASE = BASE
    rm_insample._init(csv)


def run_is(name: str, over: str, wait: int, hold: int) -> dict:
    rm_insample.OUT = OUT_IS
    rm_insample.BASE = BASE
    return rm_insample._run_one(name, over, wait, hold)


# ----------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("oos", "is"), required=True)
    ap.add_argument("--csv", default="data/xauusd_m1.csv")
    ap.add_argument("--from", dest="start", default="2026-03-01")
    ap.add_argument("--mid", default="2026-06-01")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--only", default=None, help="prefix filter, e.g. L3_ or R_")
    ap.add_argument("--wait", type=int, default=300)
    ap.add_argument("--hold", type=int, default=300)
    a = ap.parse_args()
    out = OUT_OOS if a.mode == "oos" else OUT_IS
    out.mkdir(parents=True, exist_ok=True)
    g = grid()
    if a.only:
        g = {k: v for k, v in g.items() if k.startswith(a.only) or k.startswith(("base_v8", "v9_"))}
    todo = {k: v for k, v in g.items() if not (out / f"{k}.json").exists()}
    print(f"[{a.mode}] {len(g)} variants, {len(todo)} to run", flush=True)
    rows = [json.load(open(out / f"{k}.json")) for k in g if k not in todo]
    t0 = time.time()
    if todo:
        if a.mode == "oos":
            ex = ProcessPoolExecutor(max_workers=a.workers, initializer=_init_oos, initargs=(a.csv, a.start))
            futs = {ex.submit(run_oos, k, v, a.start, a.mid): k for k, v in todo.items()}
        else:
            ex = ProcessPoolExecutor(max_workers=a.workers, initializer=_init_is, initargs=(a.csv,))
            futs = {ex.submit(run_is, k, v, a.wait, a.hold): k for k, v in todo.items()}
        with ex:
            for i, fu in enumerate(as_completed(futs), 1):
                r = fu.result()
                rows.append(r)
                if a.mode == "oos":
                    print(f"[{i}/{len(todo)} {time.time() - t0:5.0f}s] {r['name']:<48} n {r['trades']:4d} PF {r['profit_factor']:5.2f} "
                          f"R/tr {r['avg_R']:+.3f} tot {r['total_R']:+6.1f}R ret {r['return_%']:+6.1f}% DD {r['max_dd_%']:6.1f}%", flush=True)
                else:
                    print(f"[{i}/{len(todo)} {time.time() - t0:5.0f}s] {r['name']:<48} n {r['n']:5d} avgR {r['avg_R']:+.4f} PF {r['PF']:5.2f} "
                          f"win {r['win_%']:5.1f} tot {r['total_R']:+7.1f} DD {r['max_dd_R']:6.1f} t {r['t_stat']:5.2f}", flush=True)
                if i % 25 == 0:
                    _write_csv(rows, a.mode)
    _write_csv(rows, a.mode, show=True)


def n_legs(over: str) -> int:
    if "tp_levels=" in over:
        return over.split("tp_levels=")[1].split(",")[0].count("|") + 1
    if "partial_frac=0," in over or over.endswith("partial_frac=0"):
        return 1
    return 2


def _write_csv(rows, mode: str, show: bool = False):
    df = pd.DataFrame(rows)
    df["family"] = df.name.str.split("_").str[0]
    df["legs"] = df.overrides.fillna("").map(n_legs)
    pd.set_option("display.width", 250)
    if mode == "oos":
        df["ret_dd"] = df["return_%"] / df["max_dd_%"].abs().clip(lower=0.5)
        df.to_csv("study_results/v10_study_grid.csv", index=False)
        cols = ["name", "legs", "trades", "win_%", "profit_factor", "avg_R", "total_R", "return_%", "max_dd_%", "sharpe_daily", "H1_R", "H2_R", "months_pos"]
        if show:
            print("\n=== OOS top 30 by return ===\n" + df.sort_values("return_%", ascending=False)[cols].head(30).to_string(index=False))
            print("\n=== OOS top 20 by return / max DD ===\n" + df.sort_values("ret_dd", ascending=False)[cols + ["ret_dd"]].head(20).to_string(index=False))
            print("\n=== by number of legs (median) ===\n" + df.groupby("legs")[["return_%", "max_dd_%", "profit_factor", "avg_R"]].median().round(3).to_string())
    else:
        df.to_csv("study_results/v10_insample.csv", index=False)
        if show:
            cols = ["name", "legs", "n", "avg_R", "avg_R_poi_w", "PF", "win_%", "total_R", "max_dd_R", "t_stat", "months_pos", "R_2025H1", "R_2025H2", "R_2026"]
            print("\n=== IS top 30 by avg R ===\n" + df.sort_values("avg_R", ascending=False)[cols].head(30).to_string(index=False))
            print("\n=== by number of legs (median) ===\n" + df.groupby("legs")[["avg_R", "PF", "win_%", "max_dd_R"]].median().round(3).to_string())


if __name__ == "__main__":
    main()
