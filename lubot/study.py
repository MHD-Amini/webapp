"""POI bounce study - "how much does price bounce when it reaches a selected POI?"

Walk-forward, no look-ahead for the *selection*.  Only the scoring of a selected
POI looks at bars that come after the selection.

For every POI that the bot selected (closest above / closest below) we record,
on the timeframe it was selected on, and on M1 for precision:

  reached          price tapped the zone edge within ``max_wait_bars`` HTF bars
  touch_time       first M1 bar touching the zone edge
  penetration      how deep price went INTO / THROUGH the zone (in zone-heights
                   and ATR).  >1.0 = went through the whole zone
  closed_through   a HTF candle closed beyond the far edge before any bounce target
  bounce_atr       max favourable excursion (MFE) from the zone edge, in ATR
  bounce_usd       same in price units ($ for XAUUSD)
  bounce_pct_of_dist  MFE as a % of the distance price travelled to reach the POI
  mae_atr          max adverse excursion before the MFE (how deep the "wick" went)
  time_to_mfe      HTF bars from first touch to MFE
  bounce >= X ATR  hit flags at 0.5, 1, 1.5, 2, 3 ATR
  R multiples      with entry = zone edge (+spread), SL = far edge + buffer:
                   which R multiples were reached before SL
  retraced_to_origin  price got back to where it was when the POI was selected

Everything is aggregated by timeframe, POI type, direction, session (NY time),
premium/discount zone and month.
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

BOUNCE_LEVELS_ATR = (0.5, 1.0, 1.5, 2.0, 3.0)
R_LEVELS = (0.3, 0.4, 0.5, 1.0, 1.5, 2.0, 3.0, 5.0)

#: execution scenarios: (name, entry ["edge" | "mid" | "far"], SL buffer beyond far edge in ATR, TP in R)
SCENARIOS = [
    ("edge_sl0.1_tp1", "edge", 0.1, 1.0),
    ("edge_sl0.1_tp2", "edge", 0.1, 2.0),
    ("edge_sl0.5_tp1", "edge", 0.5, 1.0),
    ("edge_sl0.5_tp2", "edge", 0.5, 2.0),
    ("edge_sl1.0_tp1", "edge", 1.0, 1.0),
    ("edge_sl1.0_tp2", "edge", 1.0, 2.0),
    ("mid_sl0.1_tp1", "mid", 0.1, 1.0),
    ("mid_sl0.1_tp2", "mid", 0.1, 2.0),
    ("mid_sl0.5_tp1", "mid", 0.5, 1.0),
    ("mid_sl0.5_tp2", "mid", 0.5, 2.0),
    ("mid_sl1.0_tp2", "mid", 1.0, 2.0),
    ("mid_sl1.0_tp3", "mid", 1.0, 3.0),
    # small-target scalps (user request): TP 0.3R / 0.4R / 0.5R
    ("edge_sl0.1_tp0.3", "edge", 0.1, 0.3),
    ("edge_sl0.1_tp0.4", "edge", 0.1, 0.4),
    ("edge_sl0.1_tp0.5", "edge", 0.1, 0.5),
    ("edge_sl0.5_tp0.3", "edge", 0.5, 0.3),
    ("edge_sl0.5_tp0.4", "edge", 0.5, 0.4),
    ("edge_sl0.5_tp0.5", "edge", 0.5, 0.5),
    ("mid_sl0.1_tp0.3", "mid", 0.1, 0.3),
    ("mid_sl0.1_tp0.4", "mid", 0.1, 0.4),
    ("mid_sl0.1_tp0.5", "mid", 0.1, 0.5),
    ("mid_sl0.5_tp0.3", "mid", 0.5, 0.3),
    ("mid_sl0.5_tp0.4", "mid", 0.5, 0.4),
    ("mid_sl0.5_tp0.5", "mid", 0.5, 0.5),
]


@dataclass
class Touch:
    tf: str
    poi_id: int
    kind: str
    direction: str
    top: float
    bottom: float
    zone_h: float
    selected_at: int
    selected_time: str
    price_at_selection: float
    distance: float
    distance_atr: float
    orderflow_count: int
    liquidity_between: int
    range_bias: str
    poi_zone: str            # premium / discount of the POI inside the range
    atr_at_selection: float
    quality: float = float("nan")
    # outcome
    reached: bool = False
    bars_to_reach: Optional[int] = None
    touch_time: Optional[str] = None
    session: str = ""
    spread: float = 0.0
    penetration_zone: float = 0.0      # in zone heights (0 = edge, 1 = far edge)
    penetration_atr: float = 0.0
    closed_through: bool = False
    bounce_atr: float = 0.0
    bounce_usd: float = 0.0
    bounce_pct_of_dist: float = 0.0
    mae_atr: float = 0.0
    time_to_mfe: Optional[int] = None
    retraced_to_origin: bool = False
    hit_atr: Dict[str, bool] = field(default_factory=dict)
    hit_r: Dict[str, bool] = field(default_factory=dict)
    outcome_r_1: float = 0.0          # trade result with TP 1R (before costs)
    outcome_r_2: float = 0.0          # trade result with TP 2R
    net_r_1: float = 0.0              # after spread
    net_r_2: float = 0.0
    bounce_free_atr: float = 0.0      # MFE over the whole hold window, ignoring SL
    deepest_atr: float = 0.0          # max adverse over the whole hold window
    scenarios: Dict[str, float] = field(default_factory=dict)   # net R per scenario (nan = not filled)


def _session(ny_hour: int) -> str:
    if 17 <= ny_hour or ny_hour < 1:
        return "Asia (17-01)"
    if 1 <= ny_hour < 5:
        return "London (01-05)"
    if 5 <= ny_hour < 7:
        return "Pre-NY (05-07)"
    if 7 <= ny_hour < 10:
        return "New York (07-10)"
    if 10 <= ny_hour < 12:
        return "London Close (10-12)"
    return "NY PM (12-17)"


def _score(t: Touch, e: TimeframeEngine, m1: pd.DataFrame, m1a: Dict[str, np.ndarray], cfg: StrategyConfig,
           max_wait_bars: int, hold_bars: int) -> None:
    """Find the touch on the HTF, then measure the reaction on M1 from the exact
    touch minute onwards (so the move INTO the zone is never counted as bounce)."""
    c = e.candles
    bull = t.direction == BULL
    edge = t.top if bull else t.bottom
    far = t.bottom if bull else t.top
    i0 = t.selected_at + 1
    i_end = min(c.n, i0 + max_wait_bars)
    tap = None
    for i in range(i0, i_end):
        if (bull and c.low[i] <= edge) or (not bull and c.high[i] >= edge):
            tap = i
            break
    if tap is None:
        return
    t.reached = True
    t.bars_to_reach = tap - t.selected_at
    atr = float(c.atr[tap])
    if atr <= 0:
        return

    # ---- exact touch minute on M1
    tf_min = cfg.tf_minutes(c.tf)
    bar_open = np.datetime64(c.index[tap])
    idx = m1a["index"]
    m_start = int(np.searchsorted(idx, bar_open, side="left"))
    m_bar_end = int(np.searchsorted(idx, bar_open + np.timedelta64(tf_min, "m"), side="left"))
    lows, highs, closes = m1a["low"], m1a["high"], m1a["close"]
    seg_l, seg_h = lows[m_start:m_bar_end], highs[m_start:m_bar_end]
    hit = (seg_l <= edge) if bull else (seg_h >= edge)
    m_touch = m_start + int(np.argmax(hit)) if hit.any() else m_start
    t.touch_time = str(pd.Timestamp(idx[m_touch]))
    t.spread = float(m1a["spread"][m_touch])
    ny = e.structure.ny_time(tap)
    t.session = _session(ny.hour)

    # ---- reaction on M1: from the touch minute for hold_bars HTF bars
    m_end = min(len(idx), m_touch + hold_bars * tf_min)
    origin = t.price_at_selection
    risk = t.zone_h + 0.1 * atr
    sl = far - 0.1 * atr if bull else far + 0.1 * atr
    hit_r = {f"{r:g}R": False for r in R_LEVELS}
    out1 = out2 = None
    mfe = 0.0
    mfe_m = m_touch
    mae = 0.0
    closed_through = False
    # HTF close-through check needs HTF bars: precompute the HTF bar close times
    htf_close_pos = {}
    for j in range(tap, min(c.n, tap + hold_bars)):
        htf_close_pos[int(np.searchsorted(idx, np.datetime64(c.index[j]) + np.timedelta64(tf_min, "m"), side="left")) - 1] = j
    for m in range(m_touch, m_end):
        lo, hi = lows[m], highs[m]
        if bull:
            adverse, favourable, sl_hit = edge - lo, hi - edge, lo <= sl
        else:
            adverse, favourable, sl_hit = hi - edge, edge - lo, hi >= sl
        mae = max(mae, adverse)
        if favourable > mfe:
            mfe, mfe_m = favourable, m
        if not sl_hit:
            for r in R_LEVELS:
                if favourable >= r * risk:
                    hit_r[f"{r:g}R"] = True
        if out1 is None:
            out1 = -1.0 if sl_hit else (1.0 if favourable >= 1.0 * risk else None)
        if out2 is None:
            out2 = -1.0 if sl_hit else (2.0 if favourable >= 2.0 * risk else None)
        if (bull and hi >= origin) or (not bull and lo <= origin):
            t.retraced_to_origin = True
        if sl_hit:
            break
        j = htf_close_pos.get(m)
        if j is not None and ((bull and c.close[j] < far) or (not bull and c.close[j] > far)):
            closed_through = True
            break
    # ---- free excursions over the full window (ignoring SL)
    win_l, win_h = lows[m_touch:m_end], highs[m_touch:m_end]
    if len(win_l):
        if bull:
            t.bounce_free_atr = float((win_h - edge).max()) / atr
            t.deepest_atr = float((edge - win_l).max()) / atr
        else:
            t.bounce_free_atr = float((edge - win_l).max()) / atr
            t.deepest_atr = float((win_h - edge).max()) / atr
    # ---- execution scenarios
    t.scenarios = _scenarios(t, bull, edge, far, atr, lows, highs, m_touch, m_end, t.spread)

    t.closed_through = closed_through
    t.penetration_zone = mae / t.zone_h if t.zone_h > 0 else 0.0
    t.penetration_atr = mae / atr
    t.mae_atr = mae / atr
    t.bounce_atr = mfe / atr
    t.bounce_usd = mfe
    t.bounce_pct_of_dist = 100.0 * mfe / t.distance if t.distance > 0 else 0.0
    t.time_to_mfe = int(round((mfe_m - m_touch) / tf_min))
    t.hit_atr = {f"{lvl:g}ATR": bool(mfe >= lvl * atr) for lvl in BOUNCE_LEVELS_ATR}
    t.hit_r = hit_r
    t.outcome_r_1 = out1 if out1 is not None else 0.0
    t.outcome_r_2 = out2 if out2 is not None else 0.0
    cost_r = t.spread / risk if risk > 0 else 0.0
    t.net_r_1 = t.outcome_r_1 - cost_r
    t.net_r_2 = t.outcome_r_2 - cost_r


def _scenarios(t: Touch, bull: bool, edge: float, far: float, atr: float, lows, highs,
               m_touch: int, m_end: int, spread: float) -> Dict[str, float]:
    """Net R (after spread) for each execution scenario; NaN when the limit entry never filled."""
    out: Dict[str, float] = {}
    zone_h = t.zone_h
    for name, entry_mode, sl_buf, tp_r in SCENARIOS:
        if entry_mode == "edge":
            entry = edge
        elif entry_mode == "mid":
            entry = edge - zone_h / 2 if bull else edge + zone_h / 2
        else:
            entry = far
        sl = far - sl_buf * atr if bull else far + sl_buf * atr
        risk = abs(entry - sl)
        if risk <= 0:
            out[name] = float("nan")
            continue
        tp = entry + tp_r * risk if bull else entry - tp_r * risk
        filled = False
        result = float("nan")
        for m in range(m_touch, m_end):
            lo, hi = lows[m], highs[m]
            if not filled:
                if (bull and lo <= entry) or (not bull and hi >= entry):
                    filled = True
                else:
                    continue
            # conservative: SL checked before TP on the same bar
            if (bull and lo <= sl) or (not bull and hi >= sl):
                result = -1.0
                break
            if (bull and hi >= tp) or (not bull and lo <= tp):
                result = tp_r
                break
        if filled and np.isnan(result):
            # still open at the end of the window -> mark to market on last close
            last = lows[m_end - 1] if bull else highs[m_end - 1]
            result = ((last - entry) if bull else (entry - last)) / risk
        if filled:
            result -= spread / risk
        out[name] = result
    return out


def run_study(m1: pd.DataFrame, m1_spread: pd.Series, cfg: StrategyConfig, warmup_bars: int = 300,
              max_wait_bars: int = 300, hold_bars: int = 300, progress: bool = True) -> Dict:
    scanner = MultiTimeframeScanner(m1, cfg)
    m1a = {
        "index": m1.index.values.astype("datetime64[ns]"),
        "low": m1["low"].to_numpy(dtype=float),
        "high": m1["high"].to_numpy(dtype=float),
        "close": m1["close"].to_numpy(dtype=float),
        "spread": m1_spread.reindex(m1.index).ffill().bfill().to_numpy(dtype=float),
    }
    touches: List[Touch] = []
    for tf, e in scanner.engines.items():
        seen = set()
        tf_touches: List[Touch] = []
        n = e.candles.n
        for _ in range(n):
            i = e.step()
            if i < warmup_bars:
                continue
            sel = e.select(i)
            for d in (sel.above, sel.below):
                if d is None or d["id"] in seen:
                    continue
                seen.add(d["id"])
                tf_touches.append(Touch(
                    tf=tf, poi_id=d["id"], kind=d["type"], direction=d["direction"],
                    top=d["top"], bottom=d["bottom"], zone_h=d["top"] - d["bottom"],
                    selected_at=i, selected_time=sel.time, price_at_selection=sel.price,
                    distance=d["distance"], distance_atr=d["distance_atr"] or 0.0,
                    orderflow_count=d["orderflow_count"], liquidity_between=len(d["liquidity_between"]),
                    range_bias=sel.range_bias, poi_zone=d["range_zone"],
                    atr_at_selection=float(e.candles.atr[i]),
                    quality=d.get("quality") if d.get("quality") is not None else float("nan"),
                ))
        for t in tf_touches:
            _score(t, e, m1, m1a, cfg, max_wait_bars, hold_bars)
        touches += tf_touches
        if progress:
            r = sum(t.reached for t in tf_touches)
            print(f"[{tf}] bars={n} selected={len(tf_touches)} reached={r}")
    df = touches_frame(touches)
    return {"touches": touches, "df": df, "scanner": scanner}


def touches_frame(touches: List[Touch]) -> pd.DataFrame:
    rows = []
    for t in touches:
        d = asdict(t)
        for k, v in d.pop("hit_atr").items():
            d[f"ge_{k}"] = v
        for k, v in d.pop("hit_r").items():
            d[f"r_{k}"] = v
        for k, v in d.pop("scenarios").items():
            d[f"sc_{k}"] = v
        d["month"] = d["selected_time"][:7]
        rows.append(d)
    return pd.DataFrame(rows)


def aggregate(df: pd.DataFrame, by: Optional[List[str]] = None, min_n: int = 1) -> pd.DataFrame:
    if by is None:
        df = df.assign(_g="ALL")
        by = ["_g"]
    rows = []
    for key, sel in df.groupby(by, observed=True):
        g = sel[sel.reached]
        n = len(g)
        if n < min_n:
            continue
        row = {
            "group": key if not isinstance(key, tuple) else "/".join(map(str, key)),
            "selected": len(sel),
            "reached": n,
            "reached_%": round(100 * n / len(sel), 1),
            "median_bounce_atr": round(g.bounce_atr.median(), 2),
            "mean_bounce_atr": round(g.bounce_atr.mean(), 2),
            "p75_bounce_atr": round(g.bounce_atr.quantile(0.75), 2),
            "median_bounce_usd": round(g.bounce_usd.median(), 2),
            "mean_bounce_usd": round(g.bounce_usd.mean(), 2),
            "median_bounce_%dist": round(g.bounce_pct_of_dist.median(), 0),
            "median_penetration_zone": round(g.penetration_zone.median(), 2),
            "median_mae_atr": round(g.mae_atr.median(), 2),
            "closed_through_%": round(100 * g.closed_through.mean(), 1),
            "retraced_to_origin_%": round(100 * g.retraced_to_origin.mean(), 1),
            "median_bars_to_mfe": g.time_to_mfe.median(),
            "median_bounce_free_atr": round(g.bounce_free_atr.median(), 2),
            "median_deepest_atr": round(g.deepest_atr.median(), 2),
        }
        for lvl in BOUNCE_LEVELS_ATR:
            row[f"ge{lvl:g}ATR_%"] = round(100 * g[f"ge_{lvl:g}ATR"].mean(), 1)
        for rl in R_LEVELS:
            row[f"hit_{rl:g}R_%"] = round(100 * g[f"r_{rl:g}R"].mean(), 1)
        row["win_1R_%"] = round(100 * (g.outcome_r_1 > 0).mean(), 1)
        row["exp_R_TP1"] = round(g.outcome_r_1.mean(), 3)
        row["net_R_TP1"] = round(g.net_r_1.mean(), 3)
        row["win_2R_%"] = round(100 * (g.outcome_r_2 > 0).mean(), 1)
        row["exp_R_TP2"] = round(g.outcome_r_2.mean(), 3)
        row["net_R_TP2"] = round(g.net_r_2.mean(), 3)
        rows.append(row)
    return pd.DataFrame(rows)


def aggregate_scenarios(df: pd.DataFrame, by: Optional[List[str]] = None, min_n: int = 10) -> pd.DataFrame:
    r = df[df.reached].copy()
    if by is None:
        r["_g"] = "ALL"
        by = ["_g"]
    rows = []
    for key, g in r.groupby(by, observed=True):
        for name, entry_mode, sl_buf, tp_r in SCENARIOS:
            col = f"sc_{name}"
            s = g[col].dropna()
            if len(s) < min_n:
                continue
            wins = (s > 0).sum()
            rows.append({
                "group": key if not isinstance(key, tuple) else "/".join(map(str, key)),
                "scenario": name, "entry": entry_mode, "sl_buffer_atr": sl_buf, "tp_R": tp_r,
                "reached": len(g), "filled": len(s), "fill_%": round(100 * len(s) / len(g), 1),
                "win_%": round(100 * wins / len(s), 1),
                "avg_net_R": round(s.mean(), 3),
                "median_net_R": round(s.median(), 3),
                "total_net_R": round(s.sum(), 1),
                "profit_factor": round(s[s > 0].sum() / abs(s[s < 0].sum()), 2) if (s < 0).any() else float("inf"),
                "max_dd_R": round(_max_drawdown(s.to_numpy()), 1),
            })
    return pd.DataFrame(rows)


def _max_drawdown(x: np.ndarray) -> float:
    eq = np.cumsum(x)
    peak = np.maximum.accumulate(eq)
    return float((eq - peak).min()) if len(eq) else 0.0


def save_study(result: Dict, out_dir: str | Path) -> Dict[str, pd.DataFrame]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    df = result["df"]
    df.to_csv(out / "touches.csv", index=False)
    tables = {
        "overall": aggregate(df),
        "by_tf": aggregate(df, ["tf"]),
        "by_type": aggregate(df, ["kind"]),
        "by_tf_type": aggregate(df, ["tf", "kind"], min_n=10),
        "by_direction": aggregate(df, ["direction"]),
        "by_tf_direction": aggregate(df, ["tf", "direction"]),
        "by_session": aggregate(df, ["session"], min_n=10),
        "by_zone": aggregate(df, ["poi_zone"], min_n=10),
        "by_orderflow": aggregate(df.assign(of_bucket=pd.cut(df.orderflow_count, [0, 2, 5, 10, 20, 1000],
                                                             labels=["1-2", "3-5", "6-10", "11-20", "20+"])),
                                  ["of_bucket"], min_n=10),
        "by_distance": aggregate(df.assign(dist_bucket=pd.cut(df.distance_atr, [0, 1, 2, 4, 8, 1000],
                                                              labels=["<1", "1-2", "2-4", "4-8", "8+"])),
                                 ["dist_bucket"], min_n=10),
        "by_month": aggregate(df, ["month"]),
        "by_tf_month": aggregate(df, ["tf", "month"]),
    }
    tables["scenarios_all"] = aggregate_scenarios(df)
    tables["scenarios_by_tf"] = aggregate_scenarios(df, ["tf"])
    tables["scenarios_by_type"] = aggregate_scenarios(df, ["kind"])
    tables["scenarios_by_session"] = aggregate_scenarios(df, ["session"])
    for name, t in tables.items():
        t.to_csv(out / f"agg_{name}.csv", index=False)
    return tables
