"""Stand-alone replay of ONE v7 trade plan on M1 bars (labelling helper).

Same mechanics as ``portfolio_sim.PortfolioSimulator`` (kept in sync by
``tests/test_plan_replay.py`` which compares both on random plans):

* BUY LIMIT fills when the ask (bid + spread of the minute) reaches the limit,
  SELL LIMIT when the bid does; a gap through the limit fills at the open;
* SL / TP of a long are checked on the bid, of a short on the ask; every minute is
  walked in the MT5-tester order O -> (extreme against the close) -> (other
  extreme) -> C; the fill minute is replayed from the fill point onwards;
* leg 1 (``partial_frac``) closes at TP1, leg 2's stop moves to break-even in the
  same minute, TP2 for leg 2; stop-outs pay ``sl_slippage``.

Returns gross R of the FULL position (spread included through the ask/bid
mechanics, commission NOT included) plus bookkeeping (fill minute, hold, MFE/MAE).
Used by ``label_plan_outcomes.py`` to build the trade-outcome training labels.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np


@dataclass
class ReplayResult:
    filled: bool
    fill_minute: int = -1
    entry: float = float("nan")
    outcome: str = ""            # sl | partial_be | tp2 | open (still open at the end of the window)
    r_gross: float = float("nan")
    close_minute: int = -1
    mfe_r: float = 0.0
    mae_r: float = 0.0
    spread_fill: float = float("nan")
    partial: bool = False
    through_at_start: bool = False   # price already at/through the limit when the order went live -> the bot skips it


class PlanReplayer:
    """Holds the M1 arrays once; ``replay`` is called per plan."""

    def __init__(self, open_: np.ndarray, high: np.ndarray, low: np.ndarray, close: np.ndarray, spread: np.ndarray,
                 partial_r: float = 0.4, partial_frac: float = 0.5, tp2_r: float = 1.5, be_offset_r: float = 0.0,
                 sl_slippage: float = 0.10, digits: int = 2):
        self.o, self.h, self.l, self.c = open_, high, low, close
        sp = np.asarray(spread, dtype=float)
        self.sp = np.where(np.isfinite(sp), sp, np.nanmedian(sp))
        self.n = len(open_)
        self.partial_r, self.partial_frac, self.tp2_r, self.be_offset_r = partial_r, partial_frac, tp2_r, be_offset_r
        self.sl_slip = sl_slippage
        self.digits = digits

    # ------------------------------------------------------------------ helpers
    def _path(self, m: int, side_ask: bool):
        o, h, l, c = self.o[m], self.h[m], self.l[m], self.c[m]
        sp = self.sp[m] if side_ask else 0.0
        seq = [o, l, h, c] if c >= o else [o, h, l, c]
        return [x + sp for x in seq]

    def replay(self, buy: bool, limit: float, sl: float, m_from: int, m_wait_end: int, m_hold_end: int) -> ReplayResult:
        """``m_from``: first minute the order is live; ``m_wait_end``: last minute (exclusive) a fill is
        accepted; ``m_hold_end``: last minute (exclusive) the position is walked."""
        rp = lambda x: round(x, self.digits)
        limit, sl = rp(limit), rp(sl)
        risk = abs(limit - sl)
        if risk <= 0:
            return ReplayResult(False)
        sgn = 1.0 if buy else -1.0
        tp1 = rp(limit + sgn * self.partial_r * risk)
        tp2 = rp(limit + sgn * self.tp2_r * risk)
        be = rp(limit + sgn * self.be_offset_r * risk)
        f1, f2 = self.partial_frac, 1.0 - self.partial_frac
        m_wait_end = min(m_wait_end, self.n)
        m_hold_end = min(m_hold_end, self.n)
        # ---- the trader skips a plan whose entry is already reached at order time (portfolio_sim._on_event)
        if m_from < self.n:
            bid0, ask0 = self.o[m_from], self.o[m_from] + self.sp[m_from]
            if (buy and ask0 <= limit) or (not buy and bid0 >= limit):
                return ReplayResult(False, through_at_start=True)
        # ---- fill
        fill_m = -1
        for m in range(m_from, m_wait_end):
            sp = self.sp[m]
            if buy:
                if self.l[m] + sp <= limit:
                    fill_m = m
                    entry = rp(min(limit, self.o[m] + sp))
                    break
            else:
                if self.h[m] >= limit:
                    fill_m = m
                    entry = rp(max(limit, self.o[m]))
                    break
        if fill_m < 0:
            return ReplayResult(False)
        res = ReplayResult(True, fill_m, entry, spread_fill=float(self.sp[fill_m]))
        # legs: [open, sl, tp, frac, close_price, reason]
        legs = [[True, sl, tp1, f1, np.nan, ""], [True, sl, tp2, f2, np.nan, ""]] if f1 > 0 else [[True, sl, tp2, 1.0, np.nan, ""]]
        partial_done = False
        for m in range(fill_m, max(m_hold_end, fill_m + 1)):
            path = self._path(m, side_ask=not buy)
            if m == fill_m:
                ext = min(path) if buy else max(path)
                k0 = path.index(ext)
                start = entry - self.sp[m] if buy else entry + self.sp[m]
                path = [start, ext] + path[k0 + 1:]
            hi, lo = max(path), min(path)
            if buy:
                res.mfe_r = max(res.mfe_r, (hi - entry) / risk)
                res.mae_r = max(res.mae_r, (entry - lo) / risk)
            else:
                res.mfe_r = max(res.mfe_r, (entry - lo) / risk)
                res.mae_r = max(res.mae_r, (hi - entry) / risk)
            prev = path[0]
            for k, px in enumerate(path):
                seg_lo, seg_hi = min(prev, px), max(prev, px)
                going_up = px > prev
                prev = px
                for leg in legs:
                    if not leg[0]:
                        continue
                    lsl, ltp = leg[1], leg[2]
                    if buy:
                        hit_sl, hit_tp = seg_lo <= lsl, seg_hi >= ltp
                    else:
                        hit_sl, hit_tp = seg_hi >= lsl, seg_lo <= ltp
                    if hit_sl and hit_tp:
                        first_sl = (not going_up) if buy else going_up
                        if k == 0:
                            first_sl = (path[0] <= lsl) if buy else (path[0] >= lsl)
                        hit_tp, hit_sl = not first_sl, first_sl
                    if hit_sl:
                        price = lsl
                        if k == 0 and ((buy and path[0] < lsl) or (not buy and path[0] > lsl)):
                            price = path[0]
                        price = price - self.sl_slip if buy else price + self.sl_slip
                        leg[0] = False
                        leg[4] = rp(price)
                        leg[5] = "be" if (partial_done and lsl == be) else "sl"
                    elif hit_tp:
                        price = ltp
                        if k == 0 and ((buy and path[0] > ltp) or (not buy and path[0] < ltp)):
                            price = path[0]
                        is_tp1 = (ltp == tp1) and not partial_done and len(legs) > 1
                        leg[0] = False
                        leg[4] = rp(price)
                        leg[5] = "tp1" if is_tp1 else "tp2"
                        if is_tp1:
                            partial_done = True
                            res.partial = True
                            for l2 in legs:
                                if l2[0]:
                                    l2[1] = be
                            seg_lo, seg_hi = min(price, px), max(price, px)
                if all(not l[0] for l in legs):
                    break
            if all(not l[0] for l in legs):
                res.close_minute = m
                break
        # ---- result
        reasons = [l[5] for l in legs]
        if any(l[0] for l in legs):
            # still open at the end of the window: mark to market at the last close (bid / ask)
            m_last = max(m_hold_end - 1, fill_m)
            px_mark = self.c[m_last] if buy else self.c[m_last] + self.sp[m_last]
            for l in legs:
                if l[0]:
                    l[0] = False
                    l[4] = rp(px_mark)
                    l[5] = "open"
            res.outcome = "open"
            res.close_minute = m_last
        elif "tp2" in reasons:
            res.outcome = "tp2"
        elif "tp1" in reasons and "be" in reasons:
            res.outcome = "partial_be"
        else:
            res.outcome = "sl"
        res.r_gross = float(sum(sgn * (l[4] - entry) * l[3] for l in legs) / risk)
        return res
