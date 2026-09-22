"""Timeframe engine: ties structure + POI detection + order-flow filtering and
returns the two POIs (closest above / closest below current price).

POI Rule Set (PDF):
 1. selected from the (higher) timeframe being scanned            -> per-TF scan
 2. liquidity resting between price and the POI (feeding into it) -> require_liquidity_between
 3. unmitigated                                                    -> alive
 4. the closest POI to the liquidity / price                       -> closest above & below

Order Flow (PDF): "a series of mitigation ... POI, push away, return, reverse".
A candidate must be *supported* by at least ``min_orderflow_support`` POIs of the
same direction that were already mitigated & respected in the recent past.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from .config import TIMEFRAME_MINUTES, StrategyConfig
from .data import Candles, resample
from .indicators import IndicatorSet
from .levels import LevelMemory
from .poi import BEAR, BULL, LIQ_WEIGHT, POI, POIDetector
from .structure import BSL, SSL, StructureTracker


@dataclass
class Selection:
    tf: str
    time: str
    price: float
    above: Optional[Dict] = None
    below: Optional[Dict] = None
    range_bias: str = "none"
    price_zone: str = "n/a"
    candidates_above: int = 0
    candidates_below: int = 0

    def to_dict(self) -> Dict:
        return {
            "tf": self.tf,
            "time": self.time,
            "price": round(self.price, 3),
            "range_bias": self.range_bias,
            "price_zone": self.price_zone,
            "above": self.above,
            "below": self.below,
            "candidates_above": self.candidates_above,
            "candidates_below": self.candidates_below,
        }


class TimeframeEngine:
    """Everything for ONE timeframe.  Feed closed bars with ``step()``."""

    def __init__(self, tf: str, df: pd.DataFrame, cfg: StrategyConfig, ltf: Optional[Candles] = None,
                 scorer: Optional["QualityScorer"] = None, htf: Optional["TimeframeEngine"] = None,
                 approach_scorer: Optional["QualityScorer"] = None):
        self.tf = tf
        self.cfg = cfg
        self.scorer = scorer
        #: v4 stage-2 model used once price is within ``approach_near_atr`` of the zone
        self.approach_scorer = approach_scorer
        if cfg.selection_mode == "quality":
            from .quality import QualityScorer
            if scorer is None:
                self.scorer = QualityScorer.load(cfg.quality_model_path)
            if approach_scorer is None and cfg.approach_model_path:
                self.approach_scorer = QualityScorer.load(cfg.approach_model_path)
        self.candles = Candles(df, tf, cfg.atr_period)
        self.structure = StructureTracker(self.candles, cfg)
        #: v5 - classic indicators (RSI, MACD, ADX, Bollinger, VWAP, volume, SuperTrend ...)
        #: computed once per timeframe; read at bar i only (backward looking)
        self.indicators = IndicatorSet(self.candles) if cfg.use_indicators else None
        #: v6 - level memory (volume profile / value area / reaction counts), stepped per bar
        self.levels = LevelMemory(self.candles, long_window=cfg.levels_window_bars) if cfg.use_levels else None
        self.detector = POIDetector(self.candles, self.structure, cfg, ltf, indicators=self.indicators, levels=self.levels)
        #: optional higher-timeframe engine (e.g. H1 for M15) used for HTF confluence
        #: features.  It is stepped lazily up to the bar that was CLOSED at our bar
        #: time, so no look-ahead is introduced.
        self.htf = htf
        self.i = -1
        # ---- volatility regime & momentum, vectorised once (all backward looking)
        c = self.candles
        self._atr_long = pd.Series(c.atr).rolling(cfg.atr_period * 5, min_periods=1).mean().to_numpy()
        self._ret20 = pd.Series(c.close).diff(20).fillna(0.0).to_numpy()
        self._ret5 = pd.Series(c.close).diff(5).fillna(0.0).to_numpy()
        self._hh20 = pd.Series(c.high).rolling(20, min_periods=1).max().to_numpy()
        self._ll20 = pd.Series(c.low).rolling(20, min_periods=1).min().to_numpy()
        self._hh100 = pd.Series(c.high).rolling(100, min_periods=1).max().to_numpy()
        self._ll100 = pd.Series(c.low).rolling(100, min_periods=1).min().to_numpy()
        # v3: longer volatility / trend context
        self._atr_vlong = pd.Series(c.atr).rolling(cfg.atr_period * 20, min_periods=1).mean().to_numpy()
        self._ret60 = pd.Series(c.close).diff(60).fillna(0.0).to_numpy()
        self._ema50 = pd.Series(c.close).ewm(span=50, adjust=False).mean().to_numpy()
        self._ema200 = pd.Series(c.close).ewm(span=200, adjust=False).mean().to_numpy()
        self._tf_minutes = float(TIMEFRAME_MINUTES.get(tf, 5))
        # v4: price-action of the approach (all backward looking)
        body = np.abs(c.close - c.open)
        rng = np.maximum(c.high - c.low, 1e-9)
        self._body = body
        self._rng = rng
        self._body_frac5 = pd.Series(body / rng).rolling(5, min_periods=1).mean().to_numpy()
        self._up_wick = c.high - np.maximum(c.open, c.close)
        self._dn_wick = np.minimum(c.open, c.close) - c.low
        self._rng5 = pd.Series(c.high - c.low).rolling(5, min_periods=1).mean().to_numpy()
        self._rng20 = pd.Series(c.high - c.low).rolling(20, min_periods=1).mean().to_numpy()
        self._hh5 = pd.Series(c.high).rolling(5, min_periods=1).max().to_numpy()
        self._ll5 = pd.Series(c.low).rolling(5, min_periods=1).min().to_numpy()
        self._hh50 = pd.Series(c.high).rolling(50, min_periods=1).max().to_numpy()
        self._ll50 = pd.Series(c.low).rolling(50, min_periods=1).min().to_numpy()
        self._ema20 = pd.Series(c.close).ewm(span=20, adjust=False).mean().to_numpy()
        # consecutive candles in the same direction ending at each bar (+n up run, -n down run)
        up = (c.close > c.open).astype(int)
        dn = (c.close < c.open).astype(int)
        run = np.zeros(c.n, dtype=float)
        cur = 0
        for k in range(c.n):
            if up[k]:
                cur = cur + 1 if cur > 0 else 1
            elif dn[k]:
                cur = cur - 1 if cur < 0 else -1
            else:
                cur = 0
            run[k] = cur
        self._run = run

    # ---------------------------------------------------------------- feed
    def step(self) -> int:
        """Process the next closed bar. Returns its index."""
        self.i += 1
        self.structure.update(self.i)
        if self.levels is not None:
            self.levels.update(self.i)
        self.detector.update(self.i)
        return self.i

    def run_all(self) -> None:
        while self.i + 1 < self.candles.n:
            self.step()

    # ------------------------------------------------------------ HTF sync
    def _sync_htf(self, i: int) -> Optional[int]:
        """Step the HTF engine so that it has processed every HTF bar that
        CLOSED at or before the close of our bar ``i``; return that HTF index."""
        h = self.htf
        if h is None or h.candles.n == 0:
            return None
        our_close = self.candles.index[i] + pd.Timedelta(minutes=self.cfg.tf_minutes(self.tf))
        htf_min = self.cfg.tf_minutes(h.tf)
        # last HTF bar whose close time <= our close time
        target = int(np.searchsorted(h.candles.index.values,
                                     np.datetime64(our_close - pd.Timedelta(minutes=htf_min)), side="right")) - 1
        if target < 0:
            return None
        while h.i < target and h.i + 1 < h.candles.n:
            h.step()
        return min(target, h.i)

    def _htf_features(self, p: POI, price: float, atr: float, hi_idx: Optional[int]) -> Dict[str, float]:
        """Confluence with the higher timeframe: does our POI sit inside an alive
        HTF POI of the same direction, is HTF bias aligned, does HTF liquidity
        rest right behind our zone (a magnet that would pull price through)?"""
        out = {"htf_confluence": 0.0, "htf_confluence_kind": 0.0, "htf_bias_aligned": 0.0,
               "htf_liq_behind_atr": 0.0, "htf_in_zone": 0.0, "htf_dist_atr": 0.0}
        h = self.htf
        if h is None or hi_idx is None:
            return out
        tol = 0.25 * atr
        best = None
        for q in h.detector.alive_pois(hi_idx):
            if q.direction != p.direction or q.created_at > hi_idx:
                continue
            if q.bottom <= p.top + tol and q.top >= p.bottom - tol:
                w = LIQ_WEIGHT.get("EQH", 3.0) if q.kind == "OB" else 2.0 if q.kind in ("BB", "UW") else 1.0
                if best is None or w > best:
                    best = w
        if best is not None:
            out["htf_confluence"] = 1.0
            out["htf_confluence_kind"] = float(best)
        # nearest alive same-direction HTF POI beyond ours (distance in our ATR)
        beyond = []
        for q in h.detector.alive_pois(hi_idx):
            if q.direction != p.direction or q.created_at > hi_idx:
                continue
            if p.direction == BULL and q.top < p.bottom:
                beyond.append(p.bottom - q.top)
            elif p.direction == BEAR and q.bottom > p.top:
                beyond.append(q.bottom - p.top)
        out["htf_dist_atr"] = (min(beyond) / atr) if beyond and atr > 0 else 0.0
        hb = h.structure.bias_at(hi_idx)
        out["htf_bias_aligned"] = 1.0 if hb == p.direction else (0.0 if hb == "none" else -1.0)
        rng = h.structure.range
        if rng.bias != "none" and rng.formed_at <= hi_idx:
            out["htf_in_zone"] = float(rng.zone_of(p.mid) == ("discount" if p.direction == BULL else "premium"))
        # HTF liquidity just behind the zone (within 1.5 ATR beyond the far edge)
        side = SSL if p.direction == BULL else BSL
        behind = 0.0
        for l in h.structure.liquidity:
            if not l.active or l.side != side or l.created_at > hi_idx:
                continue
            if p.direction == BULL and p.bottom - 1.5 * atr <= l.price < p.bottom:
                behind = max(behind, LIQ_WEIGHT.get(l.kind, 1.0))
            elif p.direction == BEAR and p.top < l.price <= p.top + 1.5 * atr:
                behind = max(behind, LIQ_WEIGHT.get(l.kind, 1.0))
        out["htf_liq_behind_atr"] = behind
        if h.indicators is not None:
            out.update(h.indicators.htf_features(hi_idx, p.direction == BULL, p.top, p.bottom, atr))
        return out

    # --------------------------------------------------------- order flow
    def orderflow_support(self, poi: POI, i: int) -> List[POI]:
        """Respected POIs of the same direction within the lookback window."""
        start = i - self.cfg.orderflow_lookback_bars
        out = []
        for p in self.detector.pois:
            if p is poi or p.direction != poi.direction or p.kind not in self.cfg.orderflow_types:
                continue
            if p.respected_at is None or p.respected_at > i or p.respected_at < start:
                continue
            out.append(p)
        return out

    @staticmethod
    def _grade(q: float) -> str:
        """Human readable bucket of the modelled bounce probability."""
        if q != q:
            return ""
        if q >= 0.65:
            return "A"
        if q >= 0.55:
            return "B"
        if q >= 0.50:
            return "C"
        return "D"

    @staticmethod
    def _round_level_atr(level: float, atr: float, step: float) -> float:
        """Distance (ATR) from ``level`` to the nearest multiple of ``step`` ($)."""
        if atr <= 0:
            return 0.0
        r = level / step
        return abs(r - round(r)) * step / atr

    @staticmethod
    def _pos_between(x: float, lo: float, hi: float) -> float:
        """0..1 position of x inside [lo, hi] (clipped to -1..2), 0.5 if the range is unknown."""
        if not (np.isfinite(lo) and np.isfinite(hi)) or hi - lo <= 0:
            return 0.5
        return float(min(max((x - lo) / (hi - lo), -1.0), 2.0))

    @staticmethod
    def _range_pos(rng, price: float) -> float:
        """Position of *price* inside the trading range, 0 = strong side, 1 = weak side (0.5 if no range)."""
        if rng.bias == "none" or not np.isfinite(rng.strong_price) or not np.isfinite(rng.weak_price):
            return 0.5
        span = rng.weak_price - rng.strong_price
        if span == 0:
            return 0.5
        return float(min(max((price - rng.strong_price) / span, -1.0), 2.0))

    def _approach_features(self, p: POI, i: int, price: float, atr: float, dist: float) -> Dict[str, float]:
        """v4 - price action of the move currently heading for the zone.

        A zone is far more likely to hold when price arrives *exhausted* (long run of
        same-colour candles, shrinking bodies, wicks against the move, stretched from
        its mean) than when it arrives with fresh displacement candles.  Everything
        uses bars <= i only.
        """
        c = self.candles
        bull = p.direction == BULL
        sgn = -1.0 if bull else 1.0            # approach direction: down for a bullish zone
        atr = atr if atr > 0 else 1e-9
        run = self._run[i]
        # consecutive candles moving TOWARDS the zone (negative if price is currently moving away)
        toward_run = float(-run if bull else run)
        # last candle: body in the approach direction, wick pointing at the zone (rejection of the approach)
        last_body = (c.close[i] - c.open[i]) * sgn / atr
        rej_w = self._dn_wick[i] if bull else self._up_wick[i]
        rej_wick = rej_w / atr
        rej_frac = rej_w / self._rng[i]
        # range expansion / contraction into the zone
        rng_ratio5 = self._rng5[i] / self._rng20[i] if self._rng20[i] > 0 else 1.0
        last_rng_atr = self._rng[i] / atr
        # last 3 candles: are bodies shrinking (exhaustion) or growing (displacement)?
        body_trend = (self._body[i] - self._body[i - 2]) / atr if i >= 2 else 0.0
        # how far price is stretched from its 20-EMA in the approach direction (mean reversion likely)
        ema_stretch = (self._ema20[i] - price) * (-sgn) / atr
        # the move of the last 5 bars towards the zone and the pace -> bars to reach the zone
        move5 = (c.close[i - 5] - price) * (-sgn) / atr if i >= 5 else 0.0
        pace = move5 / 5.0
        eta = min(dist / atr / pace, 50.0) if pace > 1e-6 else 50.0
        # did this bar break a recent 5-bar / 50-bar extreme in the approach direction (fresh momentum)?
        if i >= 1:
            broke5 = float(c.low[i] < self._ll5[i - 1]) if bull else float(c.high[i] > self._hh5[i - 1])
            broke50 = float(c.low[i] < self._ll50[i - 1]) if bull else float(c.high[i] > self._hh50[i - 1])
        else:
            broke5 = broke50 = 0.0
        # reaching the zone edge would print a new 50-bar low / high (the zone sits beyond the range)
        edge = p.top if bull else p.bottom
        beyond50 = float(edge < self._ll50[i]) if bull else float(edge > self._hh50[i])
        # wick pressure against the approach over the last 5 bars (absorption)
        k0 = max(0, i - 4)
        w = self._dn_wick[k0:i + 1] if bull else self._up_wick[k0:i + 1]
        wick_press = float(np.sum(w) / max(np.sum(self._rng[k0:i + 1]), 1e-9))
        return {
            "ap_toward_run": toward_run,
            "ap_last_body": float(last_body),
            "ap_rej_wick_atr": float(rej_wick),
            "ap_rej_wick_frac": float(rej_frac),
            "ap_rng_ratio5": float(rng_ratio5),
            "ap_last_rng_atr": float(last_rng_atr),
            "ap_body_trend": float(body_trend),
            "ap_ema_stretch": float(ema_stretch),
            "ap_move5_atr": float(move5),
            "ap_eta_bars": float(eta),
            "ap_broke5": broke5,
            "ap_broke50": broke50,
            "ap_zone_beyond50": beyond50,
            "ap_wick_pressure": wick_press,
            "ap_body_frac5": float(self._body_frac5[i]),
        }

    # ---------------------------------------------------------- filtering
    def qualified(self, i: int, price: Optional[float] = None) -> Dict[str, List[Dict]]:
        """All alive POIs at bar i that pass the rule set, split above / below."""
        c = self.candles
        price = c.close[i] if price is None else price
        atr = c.atr[i]
        above: List[Dict] = []
        below: List[Dict] = []
        rng = self.structure.range

        # pre-collect active liquidity once (sorted) and respected POIs once
        ssl_liq = sorted((l for l in self.structure.liquidity if l.active and l.side == SSL and l.created_at <= i),
                         key=lambda l: l.price)
        bsl_liq = sorted((l for l in self.structure.liquidity if l.active and l.side == BSL and l.created_at <= i),
                         key=lambda l: l.price)
        ssl_prices = np.fromiter((l.price for l in ssl_liq), dtype=float, count=len(ssl_liq))
        bsl_prices = np.fromiter((l.price for l in bsl_liq), dtype=float, count=len(bsl_liq))
        of_start = i - self.cfg.orderflow_lookback_bars
        respected = [p for p in self.detector.pois
                     if p.respected_at is not None and of_start <= p.respected_at <= i
                     and p.kind in self.cfg.orderflow_types]

        def between(prices, items, lo, hi):
            a = int(np.searchsorted(prices, lo, side="right"))
            b = int(np.searchsorted(prices, hi, side="left"))
            return items[a:b]

        alive = [p for p in self.detector.alive_pois(i) if p.created_at <= i]
        hi_idx = self._sync_htf(i)
        # ---- bar-level context shared by every candidate (all backward looking)
        atr_ratio = atr / self._atr_long[i] if self._atr_long[i] > 0 else 1.0
        mom20 = self._ret20[i] / atr if atr > 0 else 0.0
        mom5 = self._ret5[i] / atr if atr > 0 else 0.0
        rng20 = self._hh20[i] - self._ll20[i]
        pos20 = (price - self._ll20[i]) / rng20 if rng20 > 0 else 0.5
        rng100 = self._hh100[i] - self._ll100[i]
        pos100 = (price - self._ll100[i]) / rng100 if rng100 > 0 else 0.5
        bos_recent = [b for b in self.structure.bos_history if i - 50 <= b[0] <= i]
        ny = self.structure.ny_time(i)
        st = self.structure
        atr_ratio_long = atr / self._atr_vlong[i] if self._atr_vlong[i] > 0 else 1.0
        mom60 = self._ret60[i] / atr if atr > 0 else 0.0
        ema_gap = (self._ema50[i] - self._ema200[i]) / atr if atr > 0 else 0.0
        # last BOS: how long ago and in which direction
        last_bos = st.bos_history[-1] if st.bos_history else None
        # dead (violated / respected) same-direction POIs of the recent past, for "tested area" features
        dead = [q for q in self.detector.pois if not q.alive and q.created_at <= i and i - q.created_at <= self.cfg.max_poi_age_bars]
        # today's range so far (server day) and the previous day / week extremes
        day_hi, day_lo = st.day_hi, st.day_lo
        pd_hi, pd_lo, pw_hi, pw_lo = st.prev_day_hi, st.prev_day_lo, st.prev_week_hi, st.prev_week_lo
        max_dist = self.cfg.max_distance_atr
        if self.cfg.selection_mode == "quality" and self.cfg.quality_max_distance_atr:
            max_dist = min(max_dist, self.cfg.quality_max_distance_atr) if max_dist else self.cfg.quality_max_distance_atr
        for p in alive:
            if p.direction == BULL:
                if p.top >= price:
                    continue  # a bullish POI must be below price
                dist = price - p.top
                if max_dist and dist > max_dist * atr:
                    continue
                liq = between(ssl_prices, ssl_liq, p.top, price)
                if self.cfg.require_liquidity_between and not liq:
                    continue
                if self.cfg.require_premium_discount and rng.bias == "bullish" and rng.zone_of(p.mid) == "premium":
                    continue
            else:
                if p.bottom <= price:
                    continue
                dist = p.bottom - price
                if max_dist and dist > max_dist * atr:
                    continue
                liq = between(bsl_prices, bsl_liq, price, p.bottom)
                if self.cfg.require_liquidity_between and not liq:
                    continue
                if self.cfg.require_premium_discount and rng.bias == "bearish" and rng.zone_of(p.mid) == "discount":
                    continue
            support = [s for s in respected if s is not p and s.direction == p.direction]
            if len(support) < self.cfg.min_orderflow_support:
                continue
            # --- context features (all known at bar i) ---------------------
            near = self.cfg.orderflow_near_atr * atr
            near_support = [s for s in support if abs(s.mid - p.mid) <= near]
            recent_support = [s for s in support if i - s.respected_at <= self.cfg.orderflow_recent_bars]
            confluence = [q for q in alive if q is not p and q.direction == p.direction
                          and q.bottom <= p.top + 0.25 * atr and q.top >= p.bottom - 0.25 * atr]
            liq_q = max((LIQ_WEIGHT.get(l.kind, 1.0) for l in liq), default=0.0)
            liq_w_sum = float(sum(LIQ_WEIGHT.get(l.kind, 1.0) for l in liq))
            ny_hour = ny.hour
            # --- liquidity BEHIND the zone (a magnet on the far side pulls price through)
            if p.direction == BULL:
                behind = between(ssl_prices, ssl_liq, p.bottom - 1.5 * atr, p.bottom)
                near_edge_liq = between(ssl_prices, ssl_liq, p.top, p.top + 0.5 * atr)
                opp_between = between(bsl_prices, bsl_liq, p.top, price)      # BSL sitting between (targets after bounce)
                # first liquidity pool between price and the POI - how far is it from the zone?
                first_pool_gap = (min(l.price for l in liq) - p.top) / atr if liq and atr > 0 else 0.0
                stacked_beyond = between(ssl_prices, ssl_liq, p.bottom - 3.0 * atr, p.bottom - 1.5 * atr)
            else:
                behind = between(bsl_prices, bsl_liq, p.top, p.top + 1.5 * atr)
                near_edge_liq = between(bsl_prices, bsl_liq, p.bottom - 0.5 * atr, p.bottom)
                opp_between = between(ssl_prices, ssl_liq, price, p.bottom)
                first_pool_gap = (p.bottom - max(l.price for l in liq)) / atr if liq and atr > 0 else 0.0
                stacked_beyond = between(bsl_prices, bsl_liq, p.top + 1.5 * atr, p.top + 3.0 * atr)
            behind_q = max((LIQ_WEIGHT.get(l.kind, 1.0) for l in behind), default=0.0)
            # --- approach dynamics: is price currently moving TOWARDS the zone?
            toward = -mom5 if p.direction == BULL else mom5
            toward20 = -mom20 if p.direction == BULL else mom20
            # --- the leg that left the zone: how far did price travel away (in ATR)?
            away_atr = p.max_away / atr if atr > 0 else 0.0
            approach_atr = (p.min_approach / atr) if (atr > 0 and np.isfinite(p.min_approach)) else dist / atr
            # --- same-direction alive POIs *closer* to price than this one (it is not first in line)
            if p.direction == BULL:
                closer = [q for q in alive if q is not p and q.direction == BULL and p.top < q.top < price]
            else:
                closer = [q for q in alive if q is not p and q.direction == BEAR and price < q.bottom < p.bottom]
            # --- opposite-direction alive POIs price must go through first (resistance on the way)
            if p.direction == BULL:
                opp_on_path = [q for q in alive if q.direction == BEAR and q.bottom < price and q.top > p.top]
            else:
                opp_on_path = [q for q in alive if q.direction == BULL and q.top > price and q.bottom < p.bottom]
            # --- v3: where does the zone sit relative to the day / previous day / week / round numbers
            edge = p.top if p.direction == BULL else p.bottom
            # the leg that left the zone and the current retrace into it
            retrace = (p.max_away - dist) / p.max_away if p.max_away > 0 else 0.0
            bars_since_extreme = float(i - p.max_away_at) if p.max_away_at >= 0 else 0.0
            # violated / respected POIs of the same direction overlapping this zone = level already tested
            tested_violated = sum(1 for q in dead if q.direction == p.direction and q.violated_at is not None
                                  and q.bottom <= p.top + 0.25 * atr and q.top >= p.bottom - 0.25 * atr)
            tested_respected = sum(1 for q in dead if q.direction == p.direction and q.respected_at is not None
                                   and q.violated_at is None
                                   and q.bottom <= p.top + 0.25 * atr and q.top >= p.bottom - 0.25 * atr)
            # opposite-direction zones that recently *held* near here (the area is contested)
            opp_respected_near = sum(1 for q in dead if q.direction != p.direction and q.respected_at is not None
                                     and q.violated_at is None and abs(q.mid - p.mid) <= 1.0 * atr)
            if p.direction == BULL:
                beyond_pd = float(pd_lo > p.top) if np.isfinite(pd_lo) else 0.0       # zone sits below yesterday's low
                beyond_day = float(day_lo > p.top) if np.isfinite(day_lo) else 0.0    # zone below today's low so far
                dist_pdl = (p.top - pd_lo) / atr if np.isfinite(pd_lo) and atr > 0 else 0.0
            else:
                beyond_pd = float(pd_hi < p.bottom) if np.isfinite(pd_hi) else 0.0
                beyond_day = float(day_hi < p.bottom) if np.isfinite(day_hi) else 0.0
                dist_pdl = (pd_hi - p.bottom) / atr if np.isfinite(pd_hi) and atr > 0 else 0.0
            ctx = {
                "tf_minutes": self._tf_minutes,
                "distance_atr": dist / atr if atr > 0 else 0.0,
                "round_100_atr": self._round_level_atr(edge, atr, 100.0),
                "round_50_atr": self._round_level_atr(edge, atr, 50.0),
                "round_10_atr": self._round_level_atr(edge, atr, 10.0),
                "pos_prev_day": self._pos_between(p.mid, pd_lo, pd_hi) if p.direction == BULL else 1.0 - self._pos_between(p.mid, pd_lo, pd_hi),
                "pos_prev_week": self._pos_between(p.mid, pw_lo, pw_hi) if p.direction == BULL else 1.0 - self._pos_between(p.mid, pw_lo, pw_hi),
                "pos_today": self._pos_between(p.mid, day_lo, day_hi) if p.direction == BULL else 1.0 - self._pos_between(p.mid, day_lo, day_hi),
                "beyond_prev_day": beyond_pd,
                "beyond_today": beyond_day,
                "dist_prev_day_level_atr": float(max(min(dist_pdl, 20.0), -20.0)),
                "day_range_atr": (day_hi - day_lo) / atr if np.isfinite(day_hi) and np.isfinite(day_lo) and atr > 0 else 0.0,
                "retrace_frac": float(min(max(retrace, -1.0), 1.5)),
                "bars_since_extreme": bars_since_extreme,
                "tested_violated": float(tested_violated),
                "tested_respected": float(tested_respected),
                "opp_respected_near": float(opp_respected_near),
                "atr_ratio_long": float(atr_ratio_long),
                "toward_mom60": float(-mom60 if p.direction == BULL else mom60),
                "ema_gap_aligned": float(ema_gap if p.direction == BULL else -ema_gap),
                "price_vs_ema200": float((price - self._ema200[i]) / atr * (1 if p.direction == BULL else -1)) if atr > 0 else 0.0,
                "last_bos_age": float(i - last_bos[0]) if last_bos else 999.0,
                "last_bos_aligned": (1.0 if (last_bos[1] == "up") == (p.direction == BULL) else -1.0) if last_bos else 0.0,
                "n_alive_same_dir": float(sum(1 for q in alive if q.direction == p.direction)),
                "n_alive_opp_dir": float(sum(1 for q in alive if q.direction != p.direction)),
                "liq_between_n": float(len(liq)),
                "liq_between_quality": liq_q,
                "liq_between_weight": liq_w_sum,
                "first_pool_gap_atr": float(max(first_pool_gap, 0.0)),
                "liq_behind_n": float(len(behind)),
                "liq_behind_quality": behind_q,
                "liq_stacked_beyond_n": float(len(stacked_beyond)),
                "liq_near_edge_n": float(len(near_edge_liq)),
                "opp_liq_between_n": float(len(opp_between)),
                "of_total": float(len(support)),
                "of_near": float(len(near_support)),
                "of_recent": float(len(recent_support)),
                "confluence": float(len(confluence)),
                "closer_same_dir": float(len(closer)),
                "opp_on_path": float(len(opp_on_path)),
                "aligned_bias": 1.0 if rng.bias == p.direction else (0.0 if rng.bias == "none" else -1.0),
                "in_correct_zone": float(rng.zone_of(p.mid) == ("discount" if p.direction == BULL else "premium")),
                "range_pos": self._range_pos(rng, p.mid),
                "age_bars": float(i - p.created_at),
                "away_atr": away_atr,
                "min_approach_atr": float(approach_atr),
                "near_misses": float(p.near_misses),
                "toward_mom5": float(toward),
                "toward_mom20": float(toward20),
                "atr_ratio": float(atr_ratio),
                "pos20": float(pos20) if p.direction == BULL else float(1.0 - pos20),
                "pos100": float(pos100) if p.direction == BULL else float(1.0 - pos100),
                "bos_recent_n": float(len(bos_recent)),
                "bos_recent_aligned": float(sum(1 for b in bos_recent if (b[1] == "up") == (p.direction == BULL))
                                            - sum(1 for b in bos_recent if (b[1] == "up") != (p.direction == BULL))),
                "ny_hour": float(ny_hour),
                "dow": float(ny.weekday()),
                "is_bull": float(p.direction == BULL),
            }
            ctx.update(self._htf_features(p, price, atr, hi_idx))
            ctx.update(self._approach_features(p, i, price, atr, dist))
            if self.indicators is not None:
                ctx.update(self.indicators.selection_features(i, p.direction == BULL, p.top, p.bottom, price, self.structure))
            if self.levels is not None:
                ctx.update(self.levels.features(i, p.direction == BULL, p.top, p.bottom, price, atr, p.created_at))
                # v6: how the area evolved since the base was built (creation snapshot vs now)
                ctx["lv_visits_since_create"] = float(max(ctx["lv_visits"] - p.features.get("cl_visits", 0.0), 0.0))
                ctx["lv_density_change"] = float(ctx["lv_vol_density"] - p.features.get("cl_vol_density", ctx["lv_vol_density"]))
            if self.htf is not None and self.htf.levels is not None and hi_idx is not None:
                hf = self.htf.levels.features(hi_idx, p.direction == BULL, p.top, p.bottom, price, atr, 0, prefix="hlv_")
                ctx.update({k: hf[k] for k in ("hlv_vol_density", "hlv_lvn_score", "hlv_va_pos", "hlv_zone_outside_va",
                                               "hlv_rev_with", "hlv_rev_ratio", "hlv_slice_frac", "hlv_poc_beyond")})
            # v4: zone geometry - refinement level inside the zone and zone vs current candle size
            ctx["edge_to_key_atr"] = abs(edge - p.key_level) / atr if (atr > 0 and np.isfinite(p.key_level)) else 0.0
            ctx["zone_vs_bar_range"] = float(min((p.top - p.bottom) / self._rng[i], 20.0)) if self._rng[i] > 0 else 0.0
            # gap between creation and now in hours (age in bars differs per timeframe)
            ctx["age_hours"] = float(i - p.created_at) * self._tf_minutes / 60.0
            feats = {**p.features, **ctx}
            if self.cfg.selection_mode == "quality":
                if len(near_support) + len(recent_support) < self.cfg.min_orderflow_support:
                    continue
                # stage 1 (selection model) while the zone is far; stage 2 (approach model,
                # price action of the move into the zone) once price is within reach
                near_zone = self.approach_scorer is not None and dist <= self.cfg.approach_near_atr * atr
                sc = self.approach_scorer if near_zone else self.scorer
                p.quality = sc.score(p.kind, feats) if sc else float("nan")
                if sc and p.quality < self.cfg.min_quality:
                    continue
                stage = "approach" if near_zone else "selection"
            d = p.to_dict(c)
            d["context"] = {k: round(v, 4) for k, v in ctx.items()}
            if self.scorer and self.cfg.selection_mode == "quality":
                d["grade"] = self._grade(p.quality)
                d["stage"] = stage
                d["_feats"] = feats          # explanation is computed lazily for the winners only
            d["distance"] = round(dist, 3)
            d["distance_atr"] = round(dist / atr, 2) if atr > 0 else None
            d["liquidity_between"] = [l.describe() for l in liq]
            support.sort(key=lambda s: -s.respected_at)
            d["orderflow_support"] = [
                {"id": s.id, "type": s.kind, "zone": [round(s.bottom, 3), round(s.top, 3)],
                 "respected_at": str(c.index[s.respected_at])} for s in support[:5]
            ]
            d["orderflow_count"] = len(support)
            d["range_zone"] = rng.zone_of(p.mid)
            (below if p.direction == BULL else above).append(d)
        if self.cfg.selection_mode == "quality" and self.scorer:
            # Rule 4 (closest) still matters: rank by quality but penalise distance softly
            lam = self.cfg.distance_penalty
            key = lambda d: -(d["quality"] or 0.0) + lam * (d["distance_atr"] or 0.0)
        else:
            key = lambda d: d["distance"]
        above.sort(key=key)
        below.sort(key=key)
        # explanations (Saabas over all trees) are comparatively expensive -> only for the
        # two returned POIs; the raw feature dict is dropped from every candidate
        for lst in (above, below):
            for k, d in enumerate(lst):
                feats = d.pop("_feats", None)
                if k == 0 and feats is not None and self.scorer:
                    sc = self.approach_scorer if d.get("stage") == "approach" else self.scorer
                    d["why"] = sc.explain(d["type"], feats)
        return {"above": above, "below": below}

    def select(self, i: Optional[int] = None, price: Optional[float] = None) -> Selection:
        i = self.i if i is None else i
        c = self.candles
        price = c.close[i] if price is None else price
        q = self.qualified(i, price)
        sel = Selection(
            tf=self.tf,
            time=str(c.index[i]),
            price=float(price),
            above=q["above"][0] if q["above"] else None,
            below=q["below"][0] if q["below"] else None,
            range_bias=self.structure.range.bias,
            price_zone=self.structure.range.zone_of(price),
            candidates_above=len(q["above"]),
            candidates_below=len(q["below"]),
        )
        return sel


class MultiTimeframeScanner:
    """Build engines for all configured timeframes from one M1 frame."""

    def __init__(self, m1: pd.DataFrame, cfg: StrategyConfig):
        self.cfg = cfg
        self.m1 = m1
        self.ltf = Candles(m1, "M1", cfg.atr_period)
        self.engines: Dict[str, TimeframeEngine] = {}
        scorer = approach = None
        if cfg.selection_mode == "quality":
            from .quality import QualityScorer
            scorer = QualityScorer.load(cfg.quality_model_path)
            approach = QualityScorer.load(cfg.approach_model_path) if cfg.approach_model_path else None
        # Every scanned timeframe gets its OWN higher-timeframe helper engine
        # (M5->M30, M10/M15->H1, M30/H1->H4 by default) for the HTF-confluence
        # features.  Helper engines are private instances so that stepping them
        # lazily never interferes with the walk-forward loops of the scanned engines.
        self.htf_engines: Dict[str, TimeframeEngine] = {}
        for tf in cfg.timeframes:
            parent = None
            if cfg.htf_confluence:
                ptf = cfg.htf_parent.get(tf)
                if ptf and cfg.tf_minutes(ptf) > cfg.tf_minutes(tf):
                    parent = self.htf_engines.get(ptf)
                    if parent is None:
                        parent = TimeframeEngine(ptf, resample(m1, ptf), cfg, self.ltf, scorer, approach_scorer=approach)
                        self.htf_engines[ptf] = parent
            self.engines[tf] = TimeframeEngine(tf, resample(m1, tf), cfg, self.ltf, scorer, htf=parent, approach_scorer=approach)

    def run_all(self) -> None:
        for e in self.engines.values():
            e.run_all()

    def scan(self, price: Optional[float] = None, exclude_forming_bar: bool = True) -> Dict[str, Dict]:
        """Run every engine to the end and return the two POIs per timeframe.

        ``exclude_forming_bar``: when the last M1 bar does not complete the HTF
        bar, that HTF bar is still forming and must not be treated as closed.
        """
        last_m1 = self.m1.index[-1]
        price = float(self.m1["close"].iloc[-1]) if price is None else price
        out = {}
        for tf, e in self.engines.items():
            n = e.candles.n
            if exclude_forming_bar and n > 1:
                bar_open = e.candles.index[-1]
                bar_close = bar_open + pd.Timedelta(minutes=self.cfg.tf_minutes(tf))
                if last_m1 + pd.Timedelta(minutes=1) < bar_close:
                    n -= 1
            while e.i + 1 < n:
                e.step()
            out[tf] = e.select(e.i, price).to_dict()
        return out
