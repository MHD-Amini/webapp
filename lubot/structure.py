"""Market structure & liquidity (PDF: "3 Candle Formation", "Liquidity", "Trading Range").

* 3 Candle Formation  -> Swing High / Swing Low (candle #2 is the highest/lowest of 3)
* Above every unbroken Swing High rests Buy Side Liquidity (buy stops),
  below every unbroken Swing Low rests Sell Side Liquidity (sell stops).
* Equal Highs / Equal Lows  -> two unbroken swings at (relatively) the same price.
* Previous Day / Week High & Low, Asia Session High & Low -> additional liquidity.
* A liquidity level is "swept" (stop hunt) once a candle trades through it.
* Bullish QM = stop hunt to the downside + BOS to the upside (Strong Low).
  Bearish QM = stop hunt to the upside + BOS to the downside (Strong High).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import List, Optional
from zoneinfo import ZoneInfo

import numpy as np

from .config import StrategyConfig
from .data import Candles

NY = ZoneInfo("America/New_York")

BSL = "BSL"  # buy side liquidity (above highs)
SSL = "SSL"  # sell side liquidity (below lows)


@dataclass
class Liquidity:
    id: int
    price: float
    side: str            # BSL / SSL
    kind: str            # SH, SL, EQH, EQL, PDH, PDL, PWH, PWL, ASIA_H, ASIA_L
    index: int           # bar index that created the level (swing candle #2)
    created_at: int      # bar index when it became known (confirmation)
    swept_at: Optional[int] = None
    equal_with: List[int] = field(default_factory=list)

    @property
    def active(self) -> bool:
        return self.swept_at is None

    def describe(self) -> str:
        return f"{self.kind}@{self.price:.2f}"


@dataclass
class SweepEvent:
    index: int
    liquidity: Liquidity


@dataclass
class TradingRange:
    bias: str                 # "bullish" / "bearish" / "none"
    strong_index: int = -1
    strong_price: float = float("nan")
    weak_price: float = float("nan")
    formed_at: int = -1

    @property
    def equilibrium(self) -> float:
        return (self.strong_price + self.weak_price) / 2.0

    def zone_of(self, price: float) -> str:
        """premium / discount / equilibrium of *price* inside this range."""
        if self.bias == "none" or np.isnan(self.strong_price):
            return "n/a"
        lo, hi = sorted((self.strong_price, self.weak_price))
        if hi - lo <= 0:
            return "n/a"
        pos = (price - lo) / (hi - lo)
        if abs(pos - 0.5) < 0.02:
            return "equilibrium"
        return "premium" if pos > 0.5 else "discount"


class StructureTracker:
    """Incremental swing / liquidity / QM tracker for ONE timeframe.

    Call ``update(i)`` once for every newly closed bar ``i`` in order.  Nothing
    is ever computed with future information: the swing at ``i-1`` is only
    known when bar ``i`` closes.
    """

    def __init__(self, candles: Candles, cfg: StrategyConfig):
        self.c = candles
        self.cfg = cfg
        self.liquidity: List[Liquidity] = []
        self.sweeps: List[SweepEvent] = []
        self._next_id = 1
        self.tf_delta = timedelta(minutes=cfg.tf_minutes(candles.tf))
        self.server_offset = timedelta(hours=cfg.server_utc_offset_hours)

        # session state
        self._day = None
        self._day_hi = -np.inf
        self._day_lo = np.inf
        self._week = None
        self._week_hi = -np.inf
        self._week_lo = np.inf
        self._asia_key = None
        self._asia_hi = -np.inf
        self._asia_lo = np.inf
        #: previous day / week extremes as plain numbers (for position features)
        self.prev_day_hi = float("nan")
        self.prev_day_lo = float("nan")
        self.prev_week_hi = float("nan")
        self.prev_week_lo = float("nan")

        # structure / QM state
        self.last_swing_high: Optional[Liquidity] = None
        self.last_swing_low: Optional[Liquidity] = None
        self._pending_hunt_low: Optional[SweepEvent] = None   # stop hunt down waiting for BOS up
        self._pending_hunt_high: Optional[SweepEvent] = None  # stop hunt up waiting for BOS down
        self._leg_min = np.inf
        self._leg_max = -np.inf
        self.range = TradingRange("none")
        self.last_bos: Optional[tuple] = None  # ("up"/"down", index, level)
        #: (bar index, bias) every time the trading-range bias changed - lets a
        #: lower timeframe ask "what was the HTF bias at *that* moment" without look-ahead
        self.range_history: List[tuple] = []
        #: number of BOS events (for structure-momentum features)
        self.bos_history: List[tuple] = []  # (index, "up"/"down")

    # ------------------------------------------------------------------ utils
    def _new_liq(self, price, side, kind, index, created_at) -> Liquidity:
        liq = Liquidity(self._next_id, float(price), side, kind, index, created_at)
        self._next_id += 1
        self.liquidity.append(liq)
        return liq

    def active_liquidity(self, side: Optional[str] = None) -> List[Liquidity]:
        return [l for l in self.liquidity if l.active and (side is None or l.side == side)]

    def liquidity_between(self, lo: float, hi: float, side: str) -> List[Liquidity]:
        """Active liquidity strictly between lo and hi."""
        return [l for l in self.liquidity if l.active and l.side == side and lo < l.price < hi]

    def sweeps_in(self, start: int, end: int, side: str) -> List[SweepEvent]:
        out = []
        for ev in reversed(self.sweeps):
            if ev.index < start:
                break
            if start <= ev.index <= end and ev.liquidity.side == side:
                out.append(ev)
        return out

    def ny_time(self, i: int):
        ts = self.c.index[i].to_pydatetime()
        if self.cfg.server_minus_ny_hours is not None:
            return ts - timedelta(hours=self.cfg.server_minus_ny_hours)
        return (ts - self.server_offset).replace(tzinfo=ZoneInfo("UTC")).astimezone(NY)

    # ------------------------------------------------------------------ main
    def update(self, i: int) -> None:
        c = self.c
        hi, lo, close = c.high[i], c.low[i], c.close[i]

        # 1. sweeps of existing liquidity by this bar (stop hunts)
        for liq in self.liquidity:
            if not liq.active or liq.created_at > i:
                continue
            if (liq.side == BSL and hi > liq.price) or (liq.side == SSL and lo < liq.price):
                liq.swept_at = i
                ev = SweepEvent(i, liq)
                self.sweeps.append(ev)
                if liq.kind in ("SL", "EQL", "SH", "EQH"):
                    self._on_swing_sweep(ev)

        # 2. confirm 3-candle formation at i-1
        if i >= 2:
            if c.high[i - 1] > c.high[i - 2] and c.high[i - 1] > hi:
                sh = self._new_liq(c.high[i - 1], BSL, "SH", i - 1, i)
                self._tag_equal(sh)
                self.last_swing_high = sh
            if c.low[i - 1] < c.low[i - 2] and c.low[i - 1] < lo:
                sl = self._new_liq(c.low[i - 1], SSL, "SL", i - 1, i)
                self._tag_equal(sl)
                self.last_swing_low = sl

        # 3. sessions (previous day / week / asia)
        self._update_sessions(i)

        # 4. break of structure / QM / trading range
        self._update_structure(i)

        # 5. housekeeping - keep the lists bounded for year-long runs
        if len(self.liquidity) > 4000:
            cutoff = i - self.cfg.max_swing_age_bars
            self.liquidity = [l for l in self.liquidity
                              if (l.active and l.created_at >= cutoff)
                              or (l.swept_at is not None and l.swept_at >= cutoff)]
        if len(self.sweeps) > 6000:
            cutoff = i - self.cfg.max_swing_age_bars
            self.sweeps = [ev for ev in self.sweeps if ev.index >= cutoff]

    # ------------------------------------------------------------ equal highs
    def _tag_equal(self, liq: Liquidity) -> None:
        tol = self.cfg.equal_level_tolerance_atr * self.c.atr[liq.created_at]
        kind_eq = "EQH" if liq.side == BSL else "EQL"
        for other in self.liquidity:
            if other is liq or not other.active or other.side != liq.side:
                continue
            if other.kind not in ("SH", "SL", "EQH", "EQL"):
                continue
            if abs(other.price - liq.price) <= tol:
                other.kind = kind_eq
                liq.kind = kind_eq
                other.equal_with.append(liq.id)
                liq.equal_with.append(other.id)

    # --------------------------------------------------------------- sessions
    def _update_sessions(self, i: int) -> None:
        c = self.c
        ts = c.index[i]
        day = ts.date()
        week = ts.isocalendar()[:2]
        hi, lo = c.high[i], c.low[i]

        if self._day is None:
            self._day, self._week = day, week
        if day != self._day:
            if np.isfinite(self._day_hi):
                self._new_liq(self._day_hi, BSL, "PDH", i - 1, i)
                self._new_liq(self._day_lo, SSL, "PDL", i - 1, i)
                self.prev_day_hi, self.prev_day_lo = float(self._day_hi), float(self._day_lo)
            self._day, self._day_hi, self._day_lo = day, -np.inf, np.inf
        if week != self._week:
            if np.isfinite(self._week_hi):
                self._new_liq(self._week_hi, BSL, "PWH", i - 1, i)
                self._new_liq(self._week_lo, SSL, "PWL", i - 1, i)
                self.prev_week_hi, self.prev_week_lo = float(self._week_hi), float(self._week_lo)
            self._week, self._week_hi, self._week_lo = week, -np.inf, np.inf
        self._day_hi, self._day_lo = max(self._day_hi, hi), min(self._day_lo, lo)
        self._week_hi, self._week_lo = max(self._week_hi, hi), min(self._week_lo, lo)

        # Asia session: 17:00 - 00:00 New York time (bar open time)
        ny = self.ny_time(i)
        in_asia = ny.hour >= 17
        asia_key = ny.date() if in_asia else None
        if in_asia:
            if self._asia_key != asia_key:
                self._asia_key, self._asia_hi, self._asia_lo = asia_key, -np.inf, np.inf
            self._asia_hi, self._asia_lo = max(self._asia_hi, hi), min(self._asia_lo, lo)
        elif self._asia_key is not None:
            # Asia just finished -> its high/low are liquidity for the coming day
            self._new_liq(self._asia_hi, BSL, "ASIA_H", i - 1, i)
            self._new_liq(self._asia_lo, SSL, "ASIA_L", i - 1, i)
            self._asia_key = None

    # ----------------------------------------------------------- QM / ranges
    def _on_swing_sweep(self, ev: SweepEvent) -> None:
        if ev.liquidity.side == SSL:
            self._pending_hunt_low = ev
            self._leg_min = self.c.low[ev.index]
        else:
            self._pending_hunt_high = ev
            self._leg_max = self.c.high[ev.index]

    def _update_structure(self, i: int) -> None:
        c = self.c
        if self._pending_hunt_low is not None:
            self._leg_min = min(self._leg_min, c.low[i])
        if self._pending_hunt_high is not None:
            self._leg_max = max(self._leg_max, c.high[i])

        # BOS up: close above the last confirmed swing high formed before the hunt
        if self._pending_hunt_low is not None and self.last_swing_high is not None:
            ref = self.last_swing_high
            if ref.index < i and c.close[i] > ref.price and ref.created_at <= i:
                # Bullish QM -> Strong Low
                idx = int(np.argmin(c.low[self._pending_hunt_low.index: i + 1])) + self._pending_hunt_low.index
                self.range = TradingRange("bullish", idx, float(c.low[idx]), float(c.high[i]), i)
                self.last_bos = ("up", i, ref.price)
                self.range_history.append((i, "bullish"))
                self.bos_history.append((i, "up"))
                self._pending_hunt_low = None
                self._pending_hunt_high = None
        if self._pending_hunt_high is not None and self.last_swing_low is not None:
            ref = self.last_swing_low
            if ref.index < i and c.close[i] < ref.price and ref.created_at <= i:
                idx = int(np.argmax(c.high[self._pending_hunt_high.index: i + 1])) + self._pending_hunt_high.index
                self.range = TradingRange("bearish", idx, float(c.high[idx]), float(c.low[i]), i)
                self.last_bos = ("down", i, ref.price)
                self.range_history.append((i, "bearish"))
                self.bos_history.append((i, "down"))
                self._pending_hunt_high = None
                self._pending_hunt_low = None

        # keep the weak side of the range extending while it holds
        r = self.range
        if r.bias == "bullish":
            if c.close[i] < r.strong_price:      # strong low failed
                self.range = TradingRange("none")
                self.range_history.append((i, "none"))
            else:
                r.weak_price = max(r.weak_price, c.high[i])
        elif r.bias == "bearish":
            if c.close[i] > r.strong_price:
                self.range = TradingRange("none")
                self.range_history.append((i, "none"))
            else:
                r.weak_price = min(r.weak_price, c.low[i])
        if len(self.range_history) > 5000:
            self.range_history = self.range_history[-2500:]
        if len(self.bos_history) > 5000:
            self.bos_history = self.bos_history[-2500:]

    @property
    def day_hi(self) -> float:
        """High of the current (server) day so far."""
        return float(self._day_hi)

    @property
    def day_lo(self) -> float:
        return float(self._day_lo)

    def bias_at(self, k: int) -> str:
        """Trading-range bias as it was known right after bar ``k`` closed."""
        bias = "none"
        for idx, b in self.range_history:
            if idx > k:
                break
            bias = b
        return bias
