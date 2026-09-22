"""Walk-forward backtest of the POI selection.

For every closed bar of every timeframe the engine selects the two POIs
(closest above / below).  Each *distinct* selected POI is then evaluated with
future bars ONLY for scoring purposes:

* reached        price tapped the POI zone before it was invalidated (aged out)
* reaction       after the tap, price moved >= ``backtest_reaction_atr`` x ATR
                 in the POI direction before closing through the zone
* rr_hit[R]      after the tap (entry = zone edge, SL = other edge of the zone
                 + small buffer) price reached R x risk before hitting SL
* violated       stop loss / close-through happened BEFORE the first target

The selection itself never uses future data - the scoring step does.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from .config import StrategyConfig
from .engine import MultiTimeframeScanner, TimeframeEngine
from .poi import BULL


@dataclass
class Trade:
    tf: str
    poi_id: int
    kind: str
    direction: str
    top: float
    bottom: float
    selected_at: int
    selected_time: str
    price_at_selection: float
    distance: float
    orderflow_count: int
    liquidity_between: int
    reached: bool = False
    tapped_at: Optional[int] = None
    tapped_time: Optional[str] = None
    reaction: bool = False
    max_favourable_atr: float = 0.0
    violated: bool = False
    rr_hit: Dict[str, bool] = field(default_factory=dict)
    outcome_r: float = 0.0   # realised R with the 1st target of cfg.backtest_target_rr as TP


def _evaluate(trade: Trade, e: TimeframeEngine, cfg: StrategyConfig) -> None:
    c = e.candles
    i0 = trade.selected_at + 1
    i_end = min(c.n, i0 + cfg.backtest_max_wait_bars)
    top, bottom = trade.top, trade.bottom
    bull = trade.direction == BULL
    tap = None
    for i in range(i0, i_end):
        if bull and c.low[i] <= top:
            tap = i
            break
        if not bull and c.high[i] >= bottom:
            tap = i
            break
    if tap is None:
        return
    trade.reached = True
    trade.tapped_at = tap
    trade.tapped_time = str(c.index[tap])
    atr = c.atr[tap]
    risk = (top - bottom) + 0.1 * atr
    entry = top if bull else bottom
    sl = bottom - 0.1 * atr if bull else top + 0.1 * atr
    fav = 0.0
    rr_hit = {f"{r:g}R": False for r in cfg.backtest_target_rr}
    first_target = cfg.backtest_target_rr[0]
    outcome_set = False
    for i in range(tap, min(c.n, tap + cfg.backtest_max_wait_bars)):
        if bull:
            fav = max(fav, c.high[i] - entry)
            hit_sl = c.low[i] <= sl
        else:
            fav = max(fav, entry - c.low[i])
            hit_sl = c.high[i] >= sl
        for r in cfg.backtest_target_rr:
            if fav >= r * risk:
                rr_hit[f"{r:g}R"] = True
        if not outcome_set and fav >= first_target * risk:
            trade.outcome_r = first_target
            outcome_set = True
        closed_through = (bull and c.close[i] < bottom) or (not bull and c.close[i] > top)
        if hit_sl or closed_through:
            if not outcome_set:
                trade.outcome_r = -1.0
                outcome_set = True
                trade.violated = True
            break
    trade.max_favourable_atr = fav / atr if atr > 0 else 0.0
    trade.reaction = fav >= cfg.backtest_reaction_atr * atr
    trade.rr_hit = rr_hit


def run_backtest(m1: pd.DataFrame, cfg: StrategyConfig, warmup_bars: int = 300,
                 progress: bool = True) -> Dict:
    scanner = MultiTimeframeScanner(m1, cfg)
    all_trades: List[Trade] = []
    per_tf_selections: Dict[str, List[Dict]] = {}
    for tf, e in scanner.engines.items():
        trades: List[Trade] = []
        seen: set = set()
        selections: List[Dict] = []
        n = e.candles.n
        last_above = last_below = None
        for _ in range(n):
            i = e.step()
            if i < warmup_bars:
                continue
            sel = e.select(i)
            cur_above = sel.above["id"] if sel.above else None
            cur_below = sel.below["id"] if sel.below else None
            if (cur_above, cur_below) != (last_above, last_below):
                selections.append({"time": sel.time, "price": round(sel.price, 2),
                                   "above": sel.above["id"] if sel.above else None,
                                   "above_zone": [sel.above["bottom"], sel.above["top"]] if sel.above else None,
                                   "below": sel.below["id"] if sel.below else None,
                                   "below_zone": [sel.below["bottom"], sel.below["top"]] if sel.below else None})
                last_above, last_below = cur_above, cur_below
            for d in (sel.above, sel.below):
                if d is None or d["id"] in seen:
                    continue
                seen.add(d["id"])
                trades.append(Trade(
                    tf=tf, poi_id=d["id"], kind=d["type"], direction=d["direction"],
                    top=d["top"], bottom=d["bottom"], selected_at=i, selected_time=sel.time,
                    price_at_selection=sel.price, distance=d["distance"],
                    orderflow_count=d["orderflow_count"], liquidity_between=len(d["liquidity_between"]),
                ))
        for t in trades:
            _evaluate(t, e, cfg)
        all_trades += trades
        per_tf_selections[tf] = selections
        if progress:
            print(f"[{tf}] bars={n} selected POIs={len(trades)} selection-changes={len(selections)}")
    stats = summarize(all_trades, cfg)
    return {"trades": all_trades, "stats": stats, "selections": per_tf_selections, "scanner": scanner}


def summarize(trades: List[Trade], cfg: StrategyConfig) -> pd.DataFrame:
    rows = []
    groups = {"ALL": trades}
    for t in trades:
        groups.setdefault(t.tf, []).append(t)
    for t in trades:
        groups.setdefault(f"{t.tf}/{t.kind}", []).append(t)
    for name, ts in groups.items():
        n = len(ts)
        reached = [t for t in ts if t.reached]
        nr = len(reached)
        row = {
            "group": name,
            "selected": n,
            "reached": nr,
            "reached_%": round(100 * nr / n, 1) if n else 0,
            "reaction_%": round(100 * sum(t.reaction for t in reached) / nr, 1) if nr else 0,
            "violated_%": round(100 * sum(t.violated for t in reached) / nr, 1) if nr else 0,
            "avg_MFE_atr": round(float(np.mean([t.max_favourable_atr for t in reached])), 2) if nr else 0,
        }
        for r in cfg.backtest_target_rr:
            k = f"{r:g}R"
            row[f"hit_{k}_%"] = round(100 * sum(t.rr_hit.get(k, False) for t in reached) / nr, 1) if nr else 0
        row["exp_R@1stTP"] = round(float(np.mean([t.outcome_r for t in reached])), 3) if nr else 0
        rows.append(row)
    df = pd.DataFrame(rows)
    order = {"ALL": 0}
    for i, tf in enumerate(cfg.timeframes):
        order[tf] = i + 1
    df["_o"] = df["group"].map(lambda g: order.get(g.split("/")[0], 99) + (0.5 if "/" in g else 0))
    return df.sort_values(["_o", "group"]).drop(columns="_o").reset_index(drop=True)


def save_results(result: Dict, out_dir: str | Path) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    result["stats"].to_csv(out / "stats.csv", index=False)
    pd.DataFrame([asdict(t) for t in result["trades"]]).to_csv(out / "trades.csv", index=False)
    with open(out / "selections.json", "w") as f:
        json.dump(result["selections"], f, indent=1)
