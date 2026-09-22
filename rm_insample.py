#!/usr/bin/env python3
"""v9 step 3 - IN-SAMPLE check of the management systems (Jan 2025 -> Feb 2026).

The OOS grid (run_rm_study.py) covers six months / ~130 trades - enough to rank systems, not enough to
trust a single winner.  Here every management is replayed on the *in-sample* population the v8 trader
would have traded: the bot-like M5 candidates of models/train_M5.pkl (best of slot, train-only quality
model >= 0.50) that pass the v8 M5 filter (cost <= 0.08 R, quality >= 0.55, no NY-pm selections), plus
the M10/M15/M30/H1 candidates with quality >= 0.60.  Each plan is replayed on the M1 bars with the SAME
PortfolioSimulator code (one plan at a time, no portfolio limits): order live from the close of the
sampling bar, fill accepted for 300 TF bars, position walked for up to 300 TF bars after the fill.

Result per management: avg R net of commission, win %, PF, total R, R by year-half, share of positive
months -> study_results/rm_insample.csv.  Resumable: one json per management in study_results/rm_insample/.

    python rm_insample.py --names "base_v8,C_p0.4_trail0.5_tp0_start0,..."     # or --top 40 from the OOS grid
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from experiments_m5_filter import bot_score, load  # noqa: E402
from lubot import load_mt5_csv  # noqa: E402
from lubot.config import TIMEFRAME_MINUTES  # noqa: E402
from lubot.execution import SymbolSpec, TradePlan, TraderConfig, size_plan  # noqa: E402
from lubot.portfolio_sim import Pending, PortfolioSimulator  # noqa: E402
from lubot.trade_filter import TradeFilter  # noqa: E402
from run_rm_study import BASE, FLT, grid  # noqa: E402

OUT = Path("study_results/rm_insample")
POP = Path("study_results/rm_insample_population.pkl")


# ----------------------------------------------------------------------------- population
def build_population(split: str = "2026-03-01") -> pd.DataFrame:
    """Bot-like in-sample plans of every timeframe with the v8 gates applied (cached)."""
    if POP.exists():
        return pd.read_pickle(POP)
    flt = TradeFilter.parse(FLT)
    parts = []
    for tf in ("M5", "M10", "M15", "M30", "H1"):
        if not Path(f"models/train_{tf}.pkl").exists() or not Path(f"models/plan_labels_{tf}.pkl").exists():
            print(f"  {tf}: no training frame / labels - skipped")
            continue
        d = load(tf)
        d["q"] = bot_score(d, "models/quality_model_trainonly.json")
        ins = d[d.sel_time < split].copy()
        ins["slot"] = ins.sel_i.astype(str) + "_" + ins.side
        ins["key"] = -ins.q + 0.02 * ins["f__distance_atr"]
        bot = ins.sort_values("key").groupby("slot").head(1)
        bot = bot[bot.q >= 0.50].copy()
        keep = []
        for r in bot.itertuples():
            dd = {"top": r.top, "bottom": r.bottom, "quality": r.q, "type": r.kind, "direction": r.direction,
                  "atr": r.atr_sel, "time": r.sel_time}
            keep.append(flt.check(dd, tf, spread=r.pl_spread_fill, when=r.sel_time) is None)
        bot = bot[np.array(keep, dtype=bool)]
        cols = ["tf", "id", "kind", "direction", "top", "bottom", "sel_time", "atr_sel", "q", "pl_r_net", "pl_outcome", "poi_key"]
        parts.append(bot[cols].reset_index(drop=True))
        print(f"  {tf}: bot-like in-sample plans after the v8 gates: {len(bot)} ({bot.poi_key.nunique()} POIs), "
              f"v8-label avg R {bot.pl_r_net.mean():+.3f}", flush=True)
        del d, ins
    pop = pd.concat(parts, ignore_index=True)
    pop["sel_time"] = pd.to_datetime(pop.sel_time)
    pop.to_pickle(POP)
    return pop


# ----------------------------------------------------------------------------- single-plan replay
class PlanSim(PortfolioSimulator):
    """PortfolioSimulator used one plan at a time: identical fill / walk / management code."""

    def __init__(self, m1: pd.DataFrame, tcfg: TraderConfig, spec: SymbolSpec):
        empty = pd.DataFrame({"t": pd.to_datetime([]), "tf": [], "side": [], "event": [], "id": []})
        super().__init__(m1, empty, tcfg, spec)

    def replay(self, d: dict, m_from: int, m_wait_end: int, m_hold_end: int):
        self.pending.clear(); self.positions.clear(); self.closed.clear()
        self.balance = self.equity = self.tcfg.balance
        plan = TradePlan.from_poi(d, self.tcfg, self.spec, selected_time=str(d["time"]))
        if plan is None or m_from >= self.n:
            return None
        bid = self.open_[m_from]; ask = bid + self.spread[m_from]
        if (plan.is_buy and ask <= plan.entry) or (not plan.is_buy and bid >= plan.entry):
            return None                                   # the bot skips a plan already at/through the entry
        sz = size_plan(plan, 1_000_000.0, self.tcfg, self.spec)   # big equity -> no volume rounding effects
        if not sz.ok:
            return None
        pend = Pending(plan, pd.Timestamp(self.idx[m_from]), m_from, sz.lots_leg1, sz.lots_leg2, 10 ** 12, lots_legs=sz.lots_legs)
        pos = None
        for m in range(m_from, min(m_wait_end, self.n)):
            pos = self._try_fill(pend, m)
            if pos is not None:
                self.positions[plan.key] = pos
                self._walk_position(pos, m, from_fill=True)
                fill_m = m
                break
        if pos is None:
            return None
        m = fill_m + 1
        while not pos.closed and m < min(m_hold_end, self.n):
            self._walk_position(pos, m)
            m += 1
        if not pos.closed:                                # still open at the end of the window: mark to market
            self._force_close_all(min(m_hold_end, self.n) - 1, "forced")
        gross = sum(l.pnl for l in pos.legs)
        risk_money = pos.lots * self.spec.contract_size * plan.risk
        net = gross - pos.commission
        return {"r_gross": gross / risk_money, "r_net": net / risk_money, "outcome": pos.outcome,
                "hold_min": (pos.close_time - pos.entry_time).total_seconds() / 60.0, "mfe_r": pos.mfe_r, "mae_r": pos.mae_r}


def run_management(name: str, over: str, pop: pd.DataFrame, m1: pd.DataFrame, idx: np.ndarray, wait: int, hold: int) -> dict:
    f = OUT / f"{name}.json"
    if f.exists():
        return json.load(open(f))
    t0 = time.time()
    tcfg = TraderConfig().override(BASE + ("," + over if over else ""))
    tcfg.trade_filter = ""                                # gates already applied to the population
    sim = PlanSim(m1, tcfg, SymbolSpec())
    rows = []
    for r in pop.itertuples():
        tfm = TIMEFRAME_MINUTES[r.tf]
        m0 = int(np.searchsorted(idx, np.datetime64(r.sel_time) + np.timedelta64(tfm, "m"), side="left"))
        d = {"id": r.id, "tf": r.tf, "type": r.kind, "direction": r.direction, "top": r.top, "bottom": r.bottom,
             "quality": r.q, "grade": "", "distance": np.nan, "distance_atr": np.nan, "atr": r.atr_sel, "time": str(r.sel_time)}
        out = sim.replay(d, m0, m0 + wait * tfm, m0 + (wait + hold) * tfm)
        if out is None:
            continue
        out.update({"tf": r.tf, "side": "buy" if r.direction == "bullish" else "sell", "sel_time": r.sel_time, "poi_key": r.poi_key})
        rows.append(out)
    t = pd.DataFrame(rows)
    t["month"] = t.sel_time.dt.strftime("%Y-%m")
    w = 1.0 / t.poi_key.map(t.poi_key.value_counts())
    wins, losses = t[t.r_net > 0], t[t.r_net < 0]
    cum = t.sort_values("sel_time").r_net.cumsum()
    row = {"name": name, "overrides": over, "n": len(t), "pois": int(t.poi_key.nunique()),
           "avg_R": round(t.r_net.mean(), 4), "avg_R_poi_w": round(float(np.average(t.r_net, weights=w)), 4),
           "total_R": round(t.r_net.sum(), 1), "win_%": round(100 * (t.r_net > 0).mean(), 1),
           "PF": round(wins.r_net.sum() / abs(losses.r_net.sum()), 3) if len(losses) else float("inf"),
           "max_dd_R": round(float((cum - cum.cummax()).min()), 1),
           "t_stat": round(t.r_net.mean() / (t.r_net.std() / len(t) ** 0.5), 2),
           "months_pos": int((t.groupby("month").r_net.sum() > 0).sum()), "months": int(t.month.nunique()),
           "R_2025H1": round(t[t.sel_time < "2025-07-01"].r_net.sum(), 1),
           "R_2025H2": round(t[(t.sel_time >= "2025-07-01") & (t.sel_time < "2026-01-01")].r_net.sum(), 1),
           "R_2026": round(t[t.sel_time >= "2026-01-01"].r_net.sum(), 1),
           "M5_avg_R": round(t[t.tf == "M5"].r_net.mean(), 4) if (t.tf == "M5").any() else np.nan,
           "other_avg_R": round(t[t.tf != "M5"].r_net.mean(), 4) if (t.tf != "M5").any() else np.nan,
           "avg_hold_min": round(t.hold_min.mean(), 0), "outcomes": t.outcome.value_counts().to_dict(),
           "secs": round(time.time() - t0, 1)}
    t.to_csv(OUT / f"{name}_trades.csv", index=False)
    tmp = OUT / f"{name}.json.tmp"
    json.dump(row, open(tmp, "w"), indent=1, default=str)
    os.replace(tmp, f)
    return row


_POP = _M1 = _IDX = None


def _init(csv: str):
    global _POP, _M1, _IDX
    _POP = build_population()
    _M1 = load_mt5_csv(csv)
    _IDX = _M1.index.values.astype("datetime64[ns]")


def _run_one(name: str, over: str, wait: int, hold: int) -> dict:
    return run_management(name, over, _POP, _M1, _IDX, wait, hold)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="data/xauusd_m1.csv")
    ap.add_argument("--names", default=None, help="comma list of grid names (default: --top from the OOS grid)")
    ap.add_argument("--top", type=int, default=40, help="take the top-N OOS variants by return plus the top-N by return/DD")
    ap.add_argument("--all", action="store_true", help="replay EVERY management of the grid (~4 s each)")
    ap.add_argument("--wait", type=int, default=300)
    ap.add_argument("--hold", type=int, default=300)
    ap.add_argument("--workers", type=int, default=2)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    g = grid()
    if a.names:
        names = [n for n in a.names.split(",") if n]
    elif a.all:
        names = list(g)
    else:
        df = pd.read_csv("study_results/rm_study_grid.csv")
        names = ["base_v8"] + df.sort_values("return_%", ascending=False).name.head(a.top).tolist() + \
                df.sort_values("ret_dd", ascending=False).name.head(a.top).tolist()
        names = list(dict.fromkeys(names))
    print("population ...", flush=True)
    pop = build_population()
    print(f"in-sample plans: {len(pop)}  by TF {pop.tf.value_counts().to_dict()}", flush=True)
    names = [n for n in names if n in g]
    done = [n for n in names if (OUT / f"{n}.json").exists()]
    todo = [n for n in names if n not in done]
    rows = [json.load(open(OUT / f"{n}.json")) for n in done]
    print(f"{len(names)} managements, {len(todo)} to replay", flush=True)
    if todo:
        with ProcessPoolExecutor(max_workers=a.workers, initializer=_init, initargs=(a.csv,)) as ex:
            futs = {ex.submit(_run_one, n, g[n], a.wait, a.hold): n for n in todo}
            for i, fu in enumerate(as_completed(futs), 1):
                r = fu.result()
                rows.append(r)
                print(f"[{i}/{len(todo)}] {r['name']:<42} n {r['n']:5d} avgR {r['avg_R']:+.4f} PF {r['PF']:5.2f} win {r['win_%']:5.1f} "
                      f"tot {r['total_R']:+7.1f} DD {r['max_dd_R']:6.1f} t {r['t_stat']:5.2f} months+ {r['months_pos']}/{r['months']}", flush=True)
                if i % 20 == 0:
                    pd.DataFrame(rows).sort_values("avg_R", ascending=False).to_csv("study_results/rm_insample.csv", index=False)
    df = pd.DataFrame(rows).sort_values("avg_R", ascending=False)
    df.to_csv("study_results/rm_insample.csv", index=False)
    pd.set_option("display.width", 250)
    print("\n" + df[["name", "n", "avg_R", "avg_R_poi_w", "PF", "win_%", "total_R", "max_dd_R", "t_stat", "months_pos", "R_2025H1", "R_2025H2", "R_2026"]].to_string(index=False))


if __name__ == "__main__":
    main()
