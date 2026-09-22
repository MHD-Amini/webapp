"""v6 - *level memory*: how the market treated the zone's price area in the past.

The v5 study showed that context of the *approach* (oscillators, momentum, session)
adds almost nothing once the PDF rule set has run.  What the model has never seen is
the history of the price area the zone sits in:

* **volume / time-at-price profile** over a long rolling window - is the zone in a
  low-volume node (LVN, price moved through fast: a gap that tends to be respected
  again) or inside a high-volume node (HVN, an area where price likes to trade and
  chop)?  Where is the zone relative to the point of control / value area?
* **reaction memory** - how often did price *reverse* at this price area before, and
  how often did it *slice through*?  Counted from the swing points and from bars that
  visited the area (long lookback, thousands of bars, i.e. weeks of M5 data)
* **freshness** - how many times has the area been visited since the zone's own
  impulse; a level that price already tested several times is weaker

Everything is computed from bars ``<= i`` only.  Profiles are maintained incrementally
(binned price histogram of the last ``window`` bars) so the cost per bar is O(bins of one
bar), and every query is O(zone bins).
"""
from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np

from .data import Candles


class LevelMemory:
    """Rolling price-area statistics for one timeframe.

    ``update(i)`` must be called once per closed bar in order; feature queries then
    read only what has been accumulated.  Two rolling windows are kept:

    * ``long``  (default 3000 bars) for the profile / value area / reaction counts
    * ``short`` (default 500 bars) for the recent profile (is the zone in a recent LVN?)
    """

    def __init__(self, c: Candles, bin_atr: float = 0.10, long_window: int = 3000, short_window: int = 500,
                 swing_k: int = 3):
        self.c = c
        n = c.n
        self.long_window = long_window
        self.short_window = short_window
        # bin size / grid defined from the FIRST bars only (no dependence on later data,
        # so a bar's features never change when more history arrives)
        w0 = min(n, 100)
        a0 = c.atr[:w0]
        med_atr = float(np.nanmedian(a0[a0 > 0])) if np.any(a0 > 0) else 1.0
        self.bin = max(bin_atr * med_atr, 1e-6)
        top0 = float(np.nanmax(c.high[:w0])) if w0 else 1.0
        self.lo = 0.0
        self.nbins = int(max(top0 * 3.0, 1.0) / self.bin) + 2
        self._cache_i = -1
        self._cache: dict = {}
        # profile accumulators (float64: fractions of a bar's volume / time per bin)
        self.vol_long = np.zeros(self.nbins)
        self.time_long = np.zeros(self.nbins)
        self.vol_short = np.zeros(self.nbins)
        # reaction memory: per bin, count of swing reversals (highs / lows) and slices
        self.rev_hi = np.zeros(self.nbins)       # swing highs formed in this bin
        self.rev_lo = np.zeros(self.nbins)       # swing lows formed in this bin
        self.slice_cnt = np.zeros(self.nbins)    # bars whose BODY covered this bin (price traded through)
        self.visit_cnt = np.zeros(self.nbins)    # bars whose RANGE covered this bin
        self.last_visit = np.full(self.nbins, -1, dtype=int)
        # per-bar cached bin ranges for O(1) removal from the window
        self._b_lo = np.zeros(n, dtype=int)
        self._b_hi = np.zeros(n, dtype=int)
        self._bd_lo = np.zeros(n, dtype=int)
        self._bd_hi = np.zeros(n, dtype=int)
        self._w = np.zeros(n)
        self.i = -1
        self.swing_k = swing_k
        # rolling relative volume so the VOL / TICKVOL scale break cannot leak (v5 rule)
        v = np.nan_to_num(c.volume.astype(float))
        med = np.ones(n)
        if n:
            import pandas as pd
            med = pd.Series(v).rolling(200, min_periods=20).median().bfill().fillna(1.0).to_numpy()
            med[med <= 0] = 1.0
        self._relvol = np.where(med > 0, v / med, 1.0)
        self._relvol[~np.isfinite(self._relvol)] = 1.0
        # swing events that were removed from the window are simply left in (reaction
        # memory is meant to be long); but we keep the swing bins to age them out at 3x window
        self._swing_hist: List[tuple] = []     # (bar, bin, is_high)
        self._swing_ptr = 0

    # ------------------------------------------------------------------ helpers
    def _bin(self, price: float) -> int:
        b = int((price - self.lo) / self.bin)
        return min(max(b, 0), self.nbins - 1)

    def _add_bar(self, k: int, sign: float) -> None:
        b0, b1 = self._b_lo[k], self._b_hi[k]
        span = b1 - b0 + 1
        w = self._w[k] * sign / span
        self.vol_long[b0:b1 + 1] += w
        self.time_long[b0:b1 + 1] += sign / span
        d0, d1 = self._bd_lo[k], self._bd_hi[k]
        self.slice_cnt[d0:d1 + 1] += sign
        self.visit_cnt[b0:b1 + 1] += sign

    # ------------------------------------------------------------------ update
    def update(self, i: int) -> None:
        """Feed closed bar ``i`` (must be called for every bar in order)."""
        c = self.c
        self.i = i
        self._b_lo[i] = self._bin(c.low[i])
        self._b_hi[i] = self._bin(c.high[i])
        self._bd_lo[i] = self._bin(c.body_bottom(i))
        self._bd_hi[i] = self._bin(c.body_top(i))
        self._w[i] = self._relvol[i]
        self._add_bar(i, +1.0)
        b0, b1 = self._b_lo[i], self._b_hi[i]
        self.last_visit[b0:b1 + 1] = i
        # short profile
        span = b1 - b0 + 1
        self.vol_short[b0:b1 + 1] += self._w[i] / span
        j = i - self.short_window
        if j >= 0:
            s0, s1 = self._b_lo[j], self._b_hi[j]
            self.vol_short[s0:s1 + 1] -= self._w[j] / (s1 - s0 + 1)
        j = i - self.long_window
        if j >= 0:
            self._add_bar(j, -1.0)
        # swing reversals confirmed at bar i: bar i-k is the highest / lowest of 2k+1 bars
        k = self.swing_k
        m = i - k
        if m - k >= 0:
            hs = c.high[m - k:i + 1]
            ls = c.low[m - k:i + 1]
            if c.high[m] >= hs.max():
                b = self._bin(c.high[m])
                self.rev_hi[b] += 1
                self._swing_hist.append((m, b, True))
            if c.low[m] <= ls.min():
                b = self._bin(c.low[m])
                self.rev_lo[b] += 1
                self._swing_hist.append((m, b, False))
        # age out swing reversals older than 3 windows
        cutoff = i - 3 * self.long_window
        while self._swing_ptr < len(self._swing_hist) and self._swing_hist[self._swing_ptr][0] < cutoff:
            _, b, is_hi = self._swing_hist[self._swing_ptr]
            if is_hi:
                self.rev_hi[b] -= 1
            else:
                self.rev_lo[b] -= 1
            self._swing_ptr += 1

    # ---------------------------------------------------------------- queries
    def _value_area(self, prof: np.ndarray, frac: float = 0.70):
        tot = prof.sum()
        if tot <= 0:
            return None
        poc = int(np.argmax(prof))
        lo = hi = poc
        acc = prof[poc]
        target = frac * tot
        while acc < target and (lo > 0 or hi < self.nbins - 1):
            left = prof[lo - 1] if lo > 0 else -1.0
            right = prof[hi + 1] if hi < self.nbins - 1 else -1.0
            if right > left:
                hi += 1
                acc += prof[hi]
            else:
                lo -= 1
                acc += prof[lo]
        return poc, lo, hi

    def features(self, i: int, bull: bool, top: float, bottom: float, price: float, atr: float,
                 created_at: int, prefix: str = "lv_") -> Dict[str, float]:
        """Level-memory features for a zone [bottom, top] at bar ``i``.

        All signed / positional values are oriented so that + favours a bounce."""
        atr = atr if atr > 0 else 1e-9
        b0, b1 = self._bin(bottom), self._bin(top)
        zb = slice(b0, b1 + 1)
        nz = b1 - b0 + 1
        out: Dict[str, float] = {}
        # per-bar aggregates (identical for every candidate of bar i) are cached
        if self._cache_i != i:
            nzb = max(np.count_nonzero(self.time_long > 0), 1)
            self._cache = {"avg_vol_bin": self.vol_long.sum() / nzb, "avg_time_bin": self.time_long.sum() / nzb,
                           "avg_short": self.vol_short.sum() / max(np.count_nonzero(self.vol_short > 0), 1),
                           "va": self._value_area(self.vol_long)}
            self._cache_i = i
        avg_vol_bin = self._cache["avg_vol_bin"]
        avg_time_bin = self._cache["avg_time_bin"]
        zone_vol = self.vol_long[zb].mean() if nz else 0.0
        zone_time = self.time_long[zb].mean() if nz else 0.0
        out[prefix + "vol_density"] = float(zone_vol / avg_vol_bin) if avg_vol_bin > 0 else 1.0
        out[prefix + "time_density"] = float(zone_time / avg_time_bin) if avg_time_bin > 0 else 1.0
        # LVN score: how thin is the zone vs the 2-ATR neighbourhood on both sides
        nb = max(int(2 * atr / self.bin), 1)
        n0, n1 = max(b0 - nb, 0), min(b1 + nb, self.nbins - 1)
        neigh = np.concatenate([self.vol_long[n0:b0], self.vol_long[b1 + 1:n1 + 1]])
        neigh_mean = neigh.mean() if len(neigh) else 0.0
        out[prefix + "lvn_score"] = float(1.0 - zone_vol / neigh_mean) if neigh_mean > 0 else 0.0
        # short-window (recent) density
        avg_short = self._cache["avg_short"]
        out[prefix + "vol_density_recent"] = float(self.vol_short[zb].mean() / avg_short) if avg_short > 0 else 1.0
        # -------- POC / value area (70 %) of the long profile
        va = self._cache["va"]
        if va is None:
            out[prefix + "poc_dist_atr"] = 0.0
            out[prefix + "va_pos"] = 0.5
            out[prefix + "zone_at_va_edge"] = 0.0
            out[prefix + "zone_outside_va"] = 0.0
            out[prefix + "poc_beyond"] = 0.0
        else:
            poc, vlo, vhi = va
            poc_p = self.lo + (poc + 0.5) * self.bin
            va_lo_p = self.lo + vlo * self.bin
            va_hi_p = self.lo + (vhi + 1) * self.bin
            mid = 0.5 * (top + bottom)
            # signed: + when the POC lies BEYOND the zone (price would have to go through the zone to reach the POC)
            out[prefix + "poc_dist_atr"] = float(((mid - poc_p) if bull else (poc_p - mid)) / atr)
            span = va_hi_p - va_lo_p
            pos = (mid - va_lo_p) / span if span > 0 else 0.5
            out[prefix + "va_pos"] = float(min(max(pos if bull else 1.0 - pos, -1.0), 2.0))
            edge = va_lo_p if bull else va_hi_p
            out[prefix + "zone_at_va_edge"] = float(abs(mid - edge) <= max(0.5 * atr, top - bottom))
            out[prefix + "zone_outside_va"] = float(top < va_lo_p or bottom > va_hi_p)
            out[prefix + "poc_beyond"] = float((poc_p < bottom) if bull else (poc_p > top))
        # -------- reaction memory in the zone +- 0.25 ATR
        pad = max(int(0.25 * atr / self.bin), 1)
        r0, r1 = max(b0 - pad, 0), min(b1 + pad, self.nbins - 1)
        rs = slice(r0, r1 + 1)
        # reversals in the zone direction (swing lows for a bullish zone) vs against
        rev_with = self.rev_lo[rs].sum() if bull else self.rev_hi[rs].sum()
        rev_against = self.rev_hi[rs].sum() if bull else self.rev_lo[rs].sum()
        visits = self.visit_cnt[rs].mean() if r1 >= r0 else 0.0
        slices = self.slice_cnt[rs].mean() if r1 >= r0 else 0.0
        out[prefix + "rev_with"] = float(rev_with)
        out[prefix + "rev_against"] = float(rev_against)
        out[prefix + "rev_ratio"] = float((rev_with + 1.0) / (rev_with + rev_against + 2.0))
        out[prefix + "visits"] = float(visits)
        out[prefix + "slice_frac"] = float(slices / visits) if visits > 0 else 0.0
        # reversal density: reversals per visit (a level that reverses price when visited)
        out[prefix + "rev_per_visit"] = float(rev_with / visits) if visits > 0 else 0.0
        # -------- freshness: visits of the zone since it was created (bars that overlapped)
        lv = self.last_visit[zb].max() if nz else -1
        out[prefix + "bars_since_visit"] = float(i - lv) if lv >= 0 else float(min(i + 1, self.long_window))
        # -------- untested beyond: is there a thin area right behind the zone (price would fall through)
        beh_n = max(int(1.0 * atr / self.bin), 1)
        if bull:
            beh = self.vol_long[max(b0 - beh_n, 0):b0]
        else:
            beh = self.vol_long[b1 + 1:min(b1 + 1 + beh_n, self.nbins)]
        beh_mean = beh.mean() if len(beh) else 0.0
        out[prefix + "behind_density"] = float(beh_mean / avg_vol_bin) if avg_vol_bin > 0 else 1.0
        # -------- the path from price to the zone: how much volume sits between (support on the way)
        pb0, pb1 = sorted((self._bin(price), self._bin(top if bull else bottom)))
        path = self.vol_long[pb0:pb1 + 1]
        out[prefix + "path_density"] = float(path.mean() / avg_vol_bin) if (len(path) and avg_vol_bin > 0) else 1.0
        return out


#: creation-time snapshot keys (subset, prefixed cl_ by the detector)
CREATION_KEYS = ["cl_vol_density", "cl_lvn_score", "cl_va_pos", "cl_zone_outside_va", "cl_rev_with", "cl_rev_against",
                 "cl_rev_ratio", "cl_visits", "cl_slice_frac", "cl_behind_density", "cl_bars_since_visit"]
LevelMemory.CREATION_KEYS = CREATION_KEYS

FEATURES = [
    "lv_vol_density", "lv_time_density", "lv_lvn_score", "lv_vol_density_recent",
    "lv_poc_dist_atr", "lv_va_pos", "lv_zone_at_va_edge", "lv_zone_outside_va", "lv_poc_beyond",
    "lv_rev_with", "lv_rev_against", "lv_rev_ratio", "lv_visits", "lv_slice_frac", "lv_rev_per_visit",
    "lv_bars_since_visit", "lv_behind_density", "lv_path_density",
]
