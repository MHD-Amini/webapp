"""M1-precision portfolio simulator for the v7 trader.

Replays the recorded selection stream (``record_selections.py``) on the M1 bars and
executes every plan the way the live bot / an MT5 broker would:

* pending LIMIT orders placed when a POI is selected (at the bar close time), cancelled
  when the bot stops showing the POI ("mirror" policy) or after ``max_pending_bars``;
* fills on the **ask** (buy) / **bid** (sell).  MT5 bars are bid; ask = bid + spread
  (the spread of that minute - real where exported, imputed elsewhere, x ``spread_multiplier``);
* SL / TP of a long are checked on the bid, of a short on the ask, each M1 bar walked
  in the MT5-tester order Open -> (High/Low in the order implied by the close) -> Close;
  when SL and TP are both inside one minute the *path* decides; ``intrabar="worst"``
  always takes the stop;
* partial close at TP1: leg 1 (``partial_frac``) is closed at TP1 (limit -> no
  slippage), leg 2's stop moves to break-even in the same minute (MT5: server-side TP on
  leg 1, bot modifies leg 2 - the modification is assumed to happen inside the minute;
  ``be_delay_bars`` > 0 delays it to model a slow bot);
* stop-outs are market executions -> ``sl_slippage`` against you; bot-issued market
  orders -> ``market_slippage``;
* commission per lot round turn, swaps per night (3x on the triple day), margin check
  and stop-out level;
* position sizing ``risk_pct`` of the current equity (compounding) or of the initial
  balance, rounded down to the broker's volume step;
* at most ``max_open_positions`` plans open, one plan per POI, overlapping zones
  de-duplicated.

Everything is bookkept in account currency and in R of the *full* position, so the
result can be read both as "$ on a 10k account" and as "R per trade".
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .execution import BUY, SymbolSpec, TradePlan, TraderConfig, apply_mart_ladder, grid_deep_plan, size_plan
from .martingale import Martingale, grid_wanted
from .trade_filter import TradeFilter


# ---------------------------------------------------------------------------- records
@dataclass
class Leg:
    lots: float
    tp: float                 # 0.0 = no fixed target (runner managed by trail / time stop)
    sl: float
    open: bool = True
    close_price: float = float("nan")
    close_time: Optional[pd.Timestamp] = None
    close_reason: str = ""
    pnl: float = 0.0          # gross $ (price move only)


@dataclass
class Position:
    plan: TradePlan
    lots: float
    legs: List[Leg]
    entry_time: pd.Timestamp
    entry_price: float        # actual fill (ask for buys)
    risk_money: float
    commission: float = 0.0
    swap: float = 0.0
    partial_done: bool = False
    partial_time: Optional[pd.Timestamp] = None
    be_at_minute: int = -1    # minute index at which BE becomes active (be_delay_bars)
    mfe_r: float = 0.0
    mae_r: float = 0.0
    closed: bool = False
    close_time: Optional[pd.Timestamp] = None
    outcome: str = ""         # sl | partial_be | tp2 | partial_sl_be | forced | stopout | trail | time
    n_partials: int = 0       # ladder: number of target legs already closed
    hwm: float = float("nan")  # trailing: high-water mark (price) on the closing side
    be_armed: bool = False    # be_trigger_r reached (BE active irrespective of partials)
    sl_queue: List[Tuple[int, float]] = field(default_factory=list)   # v10: (minute from which, stop) delayed stop moves

    @property
    def open_lots(self) -> float:
        return sum(l.lots for l in self.legs if l.open)


@dataclass
class Pending:
    plan: TradePlan
    placed: pd.Timestamp
    placed_minute: int
    lots_leg1: float
    lots_leg2: float
    expires_minute: int
    reason_cancel: str = ""
    lots_legs: Tuple[float, ...] = ()
    grace_until: int = -1          # v11 cancel_grace_min: cancel at this minute unless the POI is shown again before
    grace_reason: str = ""
    armed: bool = True             # v12 re-entry placed while price is through the entry: becomes a live limit order
                                   # on the first bar that opens in front of the entry again


# ---------------------------------------------------------------------------- simulator
class PortfolioSimulator:
    def __init__(self, m1: pd.DataFrame, selections: pd.DataFrame, tcfg: TraderConfig,
                 spec: Optional[SymbolSpec] = None, be_delay_bars: int = 0, start: Optional[str] = None,
                 end: Optional[str] = None):
        self.tcfg = tcfg
        self.spec = spec or SymbolSpec()
        self.be_delay = be_delay_bars
        m = m1 if start is None else m1[start:]
        m = m if end is None else m[:end]
        self.idx = m.index.values.astype("datetime64[ns]")
        self.open_ = m["open"].to_numpy(float)
        self.high = m["high"].to_numpy(float)
        self.low = m["low"].to_numpy(float)
        self.close = m["close"].to_numpy(float)
        sp = m["spread"].to_numpy(float) if "spread" in m else np.full(len(m), 0.28)
        sp = np.where(np.isfinite(sp), sp, np.nanmedian(sp))
        self.spread = sp * tcfg.spread_multiplier
        self.n = len(m)
        sel = selections.copy()
        sel = sel[(sel.t >= m.index[0]) & (sel.t <= m.index[-1] + pd.Timedelta(minutes=1))]
        if tcfg.timeframes:
            sel = sel[sel.tf.isin(tcfg.timeframes)]
        # v16: ranked streams carry a `rank` column (1 = slot winner); streams before v16 are rank 1 throughout
        if "rank" not in sel.columns:
            sel = sel.assign(rank=1)
        sel = sel[sel["rank"] <= max(1, tcfg.max_rank)]
        # NOTE: the same sort call as before v16 (default quicksort) -> identical event order on rank-1 streams
        self.sel = sel.sort_values("t").reset_index(drop=True)
        # map each event to the FIRST M1 bar whose open time >= event time (act at that bar's open)
        self.sel_minute = np.searchsorted(self.idx, self.sel.t.values.astype("datetime64[ns]"), side="left")
        # state
        self.balance = tcfg.balance
        self.equity = tcfg.balance
        self.pending: Dict[str, Pending] = {}
        self.positions: Dict[str, Position] = {}
        self.closed: List[Position] = []
        self.cancelled: List[Pending] = []
        self.skipped: List[Tuple[str, str]] = []
        self.traded_pois: set = set()
        self.equity_curve: List[Tuple[np.datetime64, float, float]] = []   # (time, balance, equity)
        self.shown: Dict[Tuple[str, str], int] = {}   # (tf, side) -> currently shown poi id
        self.stopped_out = False
        # v10 account protection
        self.day_start_balance = tcfg.balance
        self.daily_halt_day: Optional[np.datetime64] = None     # server day on which the daily limit was hit
        self.halted = False                                      # total-loss limit hit -> no more trading
        self.daily_halts: List[Tuple[pd.Timestamp, float]] = []  # (time, equity) of every daily-limit event
        self.halt_time: Optional[pd.Timestamp] = None
        # v8: per-timeframe trade filter (cost / quality / session / side / kind / model gates)
        self.filter = TradeFilter.parse(tcfg.trade_filter, commission_oz=self.spec.commission_per_lot / self.spec.contract_size)
        self.filtered: List[Tuple[str, str]] = []
        # v12: alternative filter for confluence plans (zone overlaps an active plan of another timeframe)
        self.conf_filter: Optional[TradeFilter] = TradeFilter.parse(
            tcfg.confluence_filter, commission_oz=self.spec.commission_per_lot / self.spec.contract_size) \
            if tcfg.confluence_filter else None
        # v15: second-tier filter (plans failing the normal / confluence filter but passing this one trade at tier_risk_scale)
        self.tier_filter: Optional[TradeFilter] = TradeFilter.parse(
            tcfg.tier_filter, commission_oz=self.spec.commission_per_lot / self.spec.contract_size) if tcfg.tier_filter else None
        # v15: confluence memory - (tf, side, top, bottom, last-active minute, was_filled) of plans that left the books
        self.conf_memory: List[Tuple[str, str, float, float, int, bool]] = []
        self.tier_trades_placed = 0
        # v16: own filter bar for rank >= 2 plans
        self.rank2_filter: Optional[TradeFilter] = TradeFilter.parse(
            tcfg.rank2_filter, commission_oz=self.spec.commission_per_lot / self.spec.contract_size) if tcfg.rank2_filter else None
        self.rank2_placed = 0
        # v16: per-timeframe risk scale "M20:0.5|M5:0.8"
        self.tf_scale: Dict[str, float] = {}
        for part in (tcfg.tf_risk_scale or "").split("|"):
            if ":" in part:
                k, v = part.split(":", 1)
                self.tf_scale[k.strip()] = float(v)
        self._batch_set: set = set()           # v16: (tf, side, id) set by the events of the current minute
        self.cur_minute = 0
        self.reentries_placed = 0
        # v13: regime metric per M1 bar from CLOSED daily bars (NaN -> "trend" = normal management)
        self.regime_val: Optional[np.ndarray] = None
        if tcfg.regime_metric:
            from .regime import minute_metric
            self.regime_val = minute_metric(m, tcfg.regime_metric, tcfg.regime_short, tcfg.regime_long)
        self.regime_counts: Dict[str, int] = {"range": 0, "trend": 0}
        # v16b: daily trend sign per M1 bar (closed days only) for the trend gate; regime x side sizing map; counters
        self.trend_val: Optional[np.ndarray] = None
        if tcfg.trend_sma > 0:
            from .regime import minute_trend
            self.trend_val = minute_trend(m, tcfg.trend_sma)
        self.regime_side: Dict[Tuple[str, str], float] = {}
        for part in (tcfg.regime_side_scale or "").split("|"):
            bits = part.split(":")
            if len(bits) == 3:
                self.regime_side[(bits[0].strip(), bits[1].strip())] = float(bits[2])
        self.trend_skipped = 0
        self.trend_scaled = 0
        self.fast_cancelled = 0
        self.fast_scaled = 0
        # v16c: drawdown-aware sizing state (all computable live from the account + the open positions)
        self.peak_equity = tcfg.balance              # running max of the dd_basis series (equity or balance)
        self.day_start_equity = tcfg.balance         # for the day soft cap (== day_start_balance, kept separate for clarity)
        self.streak_losses: List[pd.Timestamp] = []  # close times of the current run of consecutive losing closes
        self.dd_scaled = 0                           # plans placed at a reduced size because of the DD throttle
        self.dd_skipped = 0                          # plans skipped (scale 0) because of the DD throttle
        self.day_soft_scaled = 0
        self.day_soft_skipped = 0
        self.open_risk_scaled = 0
        self.open_risk_skipped = 0
        self.streak_scaled = 0
        self.dd_minutes = 0                          # minutes spent below the DD throttle threshold
        # v14: martingale state (sequence sizing) + grid bookkeeping
        self.mart = Martingale(tcfg)
        self.grid_placed = 0
        self.grid_filled = 0

    # ------------------------------------------------------------------ helpers
    def _tf_minutes(self, tf: str) -> int:
        from .config import TIMEFRAME_MINUTES
        return TIMEFRAME_MINUTES.get(tf, 5)

    def _regime(self, minute: int) -> str:
        """v13: 'range' | 'trend' for the plan placed at ``minute`` ('' when the lever is off)."""
        if self.regime_val is None:
            return ""
        from .regime import regime_of
        return regime_of(float(self.regime_val[minute]), self.tcfg.regime_threshold)

    def _trend_gated(self, plan: TradePlan, minute: int) -> bool:
        """v16b: the plan goes against the daily trend AND falls under the gate's side / tf / regime scope."""
        from .regime import counter_trend
        tc = self.tcfg
        if plan.side not in tc.trend_sides:
            return False
        if tc.trend_tfs and plan.tf not in tc.trend_tfs:
            return False
        if tc.trend_regime and plan.regime != tc.trend_regime:
            return False
        return counter_trend(plan.side, float(self.trend_val[minute]))

    def _fast_scope(self, plan: TradePlan) -> bool:
        tc = self.tcfg
        if tc.fast_fill_tfs and plan.tf not in tc.fast_fill_tfs:
            return False
        if tc.fast_fill_regime and plan.regime != tc.fast_fill_regime:
            return False
        return True

    def _margin_used(self, price: float) -> float:
        return sum(self.spec.margin_required(p.open_lots, price) for p in self.positions.values())

    def _floating(self, bid: float, ask: float) -> float:
        tot = 0.0
        for p in self.positions.values():
            px = bid if p.plan.is_buy else ask
            sgn = 1.0 if p.plan.is_buy else -1.0
            tot += sum(sgn * (px - p.entry_price) * l.lots * self.spec.contract_size for l in p.legs if l.open)
        return tot

    def _accept_plan(self, plan: TradePlan) -> Optional[str]:
        t = self.tcfg
        if self.halted:
            return "halted (total loss limit)"
        if self.daily_halt_day is not None:
            return "daily loss limit"
        if t.one_trade_per_poi and plan.poi_key in self.traded_pois and plan.reentry_n == 0:
            return "poi already traded"
        if plan.key in self.pending or plan.key in self.positions:
            return "already active"
        if t.sides and plan.side not in t.sides:
            return "side filtered"
        if t.grades and plan.grade not in t.grades:
            return "grade filtered"
        if t.min_quality is not None and not (plan.quality >= t.min_quality):
            return "quality filtered"
        if t.max_zone_atr and math.isfinite(plan.atr) and (plan.zone_top - plan.zone_bottom) > t.max_zone_atr * plan.atr:
            return "zone too tall"
        if t.min_zone_usd and (plan.zone_top - plan.zone_bottom) < t.min_zone_usd:
            return "zone too thin"
        if sum(1 for p in self.pending.values() if not p.plan.grid_leg) >= t.max_pending_orders:
            return "max pending"
        ov = self._overlap_kind(plan)
        if ov and t.overlap_mode == "skip":
            return f"overlaps {ov}"
        return None

    def _overlap_kind(self, plan: TradePlan) -> str:
        """'' | 'pending' | 'open': does the plan's zone overlap an active plan of the same side
        (v11 ``dedupe_cross_tf=False``: only plans of the same timeframe count)?"""
        t = self.tcfg
        for other in list(self.pending.values()):
            if other.plan.grid_leg:
                continue
            if other.plan.side == plan.side and (t.dedupe_cross_tf or other.plan.tf == plan.tf) \
                    and plan.overlaps(other.plan) >= t.dedupe_overlap:
                return "pending"
        for other in self.positions.values():
            if other.plan.grid_leg:
                continue
            if other.plan.side == plan.side and (t.dedupe_cross_tf or other.plan.tf == plan.tf) \
                    and plan.overlaps(other.plan) >= t.dedupe_overlap:
                return "open"
        return ""

    def _confluent_other_tf(self, plan: TradePlan, minute: Optional[int] = None) -> bool:
        """v12: does the plan's zone overlap (>= dedupe_overlap) an ACTIVE plan (pending or open, same side) of
        ANOTHER timeframe?  That is the confluence evidence the ``confluence_filter`` relies on.
        v15 ``confluence_memory_min``: a plan of another timeframe that was active within the last N minutes counts too."""
        t = self.tcfg
        for other in list(self.pending.values()) + list(self.positions.values()):
            if other.plan.grid_leg:
                continue
            if other.plan.side == plan.side and other.plan.tf != plan.tf and plan.overlaps(other.plan) >= t.dedupe_overlap:
                return True
        if t.confluence_memory_min > 0 and minute is not None:
            lo, hi = plan.zone_bottom, plan.zone_top
            h = max(hi - lo, 1e-9)
            for tf, side, top, bottom, last, filled in self.conf_memory:
                if side != plan.side or tf == plan.tf or minute - last > t.confluence_memory_min:
                    continue
                if t.confluence_memory_kind == "open" and not filled:
                    continue
                if t.confluence_memory_kind == "pending" and filled:
                    continue
                inter = min(hi, top) - max(lo, bottom)
                if inter > 0 and inter / h >= t.dedupe_overlap:
                    return True
        return False

    def _remember(self, plan: TradePlan, minute: int, filled: bool) -> None:
        """v15 confluence memory: a plan left the books (order cancelled / position closed) at ``minute``."""
        if self.tcfg.confluence_memory_min <= 0 or plan.grid_leg:
            return
        self.conf_memory.append((plan.tf, plan.side, plan.zone_top, plan.zone_bottom, minute, filled))
        if len(self.conf_memory) > 400:
            keep = minute - self.tcfg.confluence_memory_min
            self.conf_memory = [m for m in self.conf_memory if m[4] >= keep]

    def _shown_elsewhere(self, tf: str, side: str, poi_id: int, key_side) -> bool:
        """v16: is ``poi_id`` currently shown on another rank slot of the same (tf, side)?  (never with max_rank 1)"""
        if self.tcfg.max_rank <= 1:
            return False
        for k, v in self.shown.items():
            if k != key_side and k[0] == tf and k[1] == side and v == poi_id:
                return True
        # the same bar may re-set the POI on another rank slot a few events later (promotion / demotion)
        return (tf, side, poi_id) in self._batch_set

    # ------------------------------------------------------------------ order events
    def _on_event(self, row, minute: int) -> None:
        rank = int(row["rank"]) if "rank" in row.index else 1   # row.rank is the pandas method
        key_side = (row.tf, row.side) if rank <= 1 else (row.tf, row.side, rank)   # v16: one slot per (tf, side, rank)
        prev = self.shown.get(key_side)
        if row.event == "clear" or row.id < 0:
            self.shown.pop(key_side, None)
            # v16: a POI promoted from rank 2 to rank 1 (or demoted) is still shown on another slot of the side -> keep its order
            if prev is not None and self.tcfg.order_policy == "mirror" and not self._shown_elsewhere(row.tf, row.side, prev, key_side):
                self._mirror_cancel(f"{row.tf}#{prev}", "no longer shown", minute)
                # v12 keep_replaced_bars: a clear of the slot also drops the orders kept after a 'replaced' (of the same rank)
                if self.tcfg.keep_replaced_bars > 0:
                    side = "buy" if row.side == "below" else "sell"
                    for k, p in list(self.pending.items()):
                        if p.grace_reason == "replaced" and p.plan.tf == row.tf and p.plan.side == side and p.plan.reentry_n == 0 \
                                and getattr(p.plan, "rank", 1) == rank:
                            self._cancel(k, "no longer shown", minute)
            return
        self.shown[key_side] = int(row.id)
        if prev is not None and prev != row.id and self.tcfg.order_policy == "mirror" \
                and not self._shown_elsewhere(row.tf, row.side, prev, key_side):
            self._mirror_cancel(f"{row.tf}#{prev}", "replaced", minute)
        # v11 grace: the POI is shown again while its order waits in the grace period -> keep the order
        pend = self.pending.get(f"{row.tf}#{int(row.id)}")
        if pend is not None and pend.grace_until >= 0:
            pend.grace_until, pend.grace_reason = -1, ""
        d = {"id": row.id, "tf": row.tf, "type": row.type, "direction": row.direction, "top": row.top,
             "bottom": row.bottom, "quality": None if not np.isfinite(row.quality) else row.quality,
             "grade": row.grade, "distance": row.distance, "distance_atr": row.distance_atr, "atr": row.atr,
             "time": str(row.t)}
        if "feats" in row.index and isinstance(row.feats, dict):
            d["feats"] = row.feats
        plan = TradePlan.from_poi(d, self.tcfg, self.spec, selected_time=str(row.t), regime=self._regime(minute))
        if plan is None:
            return
        plan.rank = rank
        if rank > 1 and self.tcfg.rank2_tfs and row.tf not in self.tcfg.rank2_tfs:
            self.skipped.append((plan.key, "rank filtered (tf)"))
            return
        if plan.regime:
            self.regime_counts[plan.regime] = self.regime_counts.get(plan.regime, 0) + 1
        if plan.regime == "range" and self.tcfg.range_risk_scale <= 0:
            self.skipped.append((plan.key, "range regime (no trading)"))
            return
        # v16b daily trend gate (decided at placement from the last CLOSED day; the live bot does the same)
        if self.trend_val is not None and self._trend_gated(plan, minute):
            if self.tcfg.trend_mode == "skip":
                self.trend_skipped += 1
                self.skipped.append((plan.key, "counter-trend"))
                return
            plan.counter_trend = True
        why = self._accept_plan(plan)
        if why:
            self.skipped.append((plan.key, why))
            return
        # v8 trade filter, evaluated with the spread of the minute the order would be placed
        # (v12: a confluence plan - same level active on another timeframe - is judged by ``confluence_filter`` instead)
        flt = self.filter
        if self.conf_filter is not None and self._confluent_other_tf(plan, minute):
            flt = self.conf_filter
            plan.confluent = True
        elif rank > 1 and self.tcfg.rank2_confluent_only:
            self.skipped.append((plan.key, "rank filtered (not confluent)"))
            return
        if rank > 1 and self.rank2_filter is not None:
            flt = self.rank2_filter                     # v16: rank >= 2 zones judged by their own bar
        why = flt.check(d, row.tf, spread=float(self.spread[minute]), when=row.t)
        if why:
            # v15 tiered admission: failed the normal bar but passes the tier bar -> trade it smaller
            if self.tier_filter is not None and self.tier_filter.rule_for(row.tf) is not None \
                    and self.tier_filter.check(d, row.tf, spread=float(self.spread[minute]), when=row.t) is None:
                plan.tier = True
            else:
                self.filtered.append((plan.key, f"{row.tf}: {why.split(' ')[0]}"))
                self.skipped.append((plan.key, "trade filter"))
                return
        self._apply_v15(plan)
        # v11 overlap_mode=share: an overlapping (confluence) plan is traded at a reduced risk
        if self.tcfg.overlap_mode == "share" and self._overlap_kind(plan):
            plan.risk_scale = plan.risk_scale * self.tcfg.overlap_risk_frac
        # price already through the entry? (POI selected while price is inside/beyond the zone) -> skip
        bid = self.open_[minute]
        ask = bid + self.spread[minute]
        if (plan.is_buy and ask <= plan.entry) or (not plan.is_buy and bid >= plan.entry):
            self.skipped.append((plan.key, "price already at/through entry"))
            return
        base = self.equity if self.tcfg.size_on == "equity" else self.tcfg.balance
        self._apply_v14(plan, base)
        # v16c drawdown-aware sizing (after every other multiplier, before the volume is computed)
        why = self._apply_v16c(plan, base)
        if why:
            self.skipped.append((plan.key, why))
            return
        sz = size_plan(plan, base, self.tcfg, self.spec)
        if not sz.ok:
            self.skipped.append((plan.key, sz.reason))
            return
        # margin check for the would-be position
        need = self.spec.margin_required(sz.lots_total, plan.entry)
        free = self.equity - self._margin_used(bid)
        if need > free * self.tcfg.margin_buffer:
            self.skipped.append((plan.key, "insufficient margin"))
            return
        exp_min = minute + self.tcfg.max_pending_bars * self._tf_minutes(row.tf) if self.tcfg.order_policy == "persist" else 10 ** 12
        self.pending[plan.key] = Pending(plan, pd.Timestamp(self.idx[minute]), minute, sz.lots_leg1, sz.lots_leg2, exp_min,
                                         lots_legs=sz.lots_legs)
        if plan.counter_trend:
            self.trend_scaled += 1                     # v16b: counter-trend orders PLACED at the reduced size
        self._place_deep(plan, base, minute, exp_min)

    # ------------------------------------------------------------------ v16c drawdown-aware sizing
    def _dd_now(self) -> float:
        """account drawdown from its peak in % (>= 0) on the configured basis."""
        cur = self.equity if self.tcfg.dd_basis == "equity" else self.balance
        return max(0.0, 100.0 * (1.0 - cur / self.peak_equity)) if self.peak_equity > 0 else 0.0

    def dd_throttle_scale(self, dd_pct: float) -> float:
        """the DD-throttle multiplier for a given drawdown % (step, or linear ramp when dd_throttle_ramp > 0)."""
        tc = self.tcfg
        if tc.dd_throttle_pct <= 0 or dd_pct <= tc.dd_throttle_pct:
            return 1.0
        if tc.dd_throttle_ramp > 0:
            f = min(1.0, (dd_pct - tc.dd_throttle_pct) / tc.dd_throttle_ramp)
            return 1.0 - f * (1.0 - tc.dd_throttle_scale)
        return tc.dd_throttle_scale

    def open_risk_usd(self, bid: float, include_pending: bool = False) -> float:
        """risk-at-stop of the open positions (legs at BE or better = 0) [+ the pending orders' initial risk]."""
        tot = 0.0
        for p in self.positions.values():
            sgn = 1.0 if p.plan.is_buy else -1.0
            for l in p.legs:
                if l.open:
                    tot += max(0.0, sgn * (p.entry_price - l.sl)) * l.lots * self.spec.contract_size
        if include_pending:
            for pd_ in self.pending.values():
                lots = (sum(pd_.lots_legs) if pd_.lots_legs else pd_.lots_leg1 + pd_.lots_leg2)
                tot += pd_.plan.risk * lots * self.spec.contract_size
        return tot

    def _apply_v16c(self, plan: TradePlan, base: float) -> Optional[str]:
        """multiplies ``plan.risk_scale`` by the DD throttle / day soft cap / streak throttle / open-risk fit.  Returns a skip
        reason or None.  Defaults (all 0) -> byte-identical to v16b."""
        tc = self.tcfg
        if plan.grid_leg:
            return None
        f = 1.0
        dd = self._dd_now()
        plan.dd_pct_at = round(dd, 3)
        if tc.dd_throttle_pct > 0 and (not tc.dd_throttle_tfs or plan.tf in tc.dd_throttle_tfs):
            s = self.dd_throttle_scale(dd)
            if s < 1.0:
                if s <= 0:
                    self.dd_skipped += 1
                    return f"dd throttle ({dd:.2f} %)"
                f *= s
                self.dd_scaled += 1
        if tc.day_soft_loss_pct > 0 and self.day_start_equity > 0 and \
                self.equity <= self.day_start_equity * (1.0 - tc.day_soft_loss_pct / 100.0):
            if tc.day_soft_scale <= 0:
                self.day_soft_skipped += 1
                return "day soft cap"
            f *= tc.day_soft_scale
            self.day_soft_scaled += 1
        if tc.streak_n > 0 and len(self.streak_losses) >= tc.streak_n:
            f *= tc.streak_scale
            self.streak_scaled += 1
        if f != 1.0:
            plan.risk_scale = (plan.risk_scale if plan.risk_scale > 0 else 1.0) * f
        if tc.max_open_risk_pct > 0:
            bid = self.open_[self.cur_minute]
            used = self.open_risk_usd(bid, tc.open_risk_pending)
            budget = base * tc.max_open_risk_pct / 100.0 - used
            own = base * tc.risk_pct / 100.0 * (plan.risk_scale if plan.risk_scale > 0 else 1.0) \
                * (plan.mart_scale if plan.mart_scale > 0 else 1.0)
            if own > budget + 1e-9:
                per_unit = self.spec.usd_per_price_unit(1.0) * plan.risk
                fit_lots = self.spec.round_volume_down(budget / per_unit) if (budget > 0 and per_unit > 0) else 0.0
                if tc.open_risk_mode == "skip" or fit_lots < self.spec.volume_min:
                    self.open_risk_skipped += 1
                    return f"open risk cap ({100 * used / base:.2f} % used)"
                g = budget / own
                plan.risk_scale = (plan.risk_scale if plan.risk_scale > 0 else 1.0) * g
                f *= g
                self.open_risk_scaled += 1
        plan.dd_scale = round(f, 4)
        return None

    def _streak_update(self, pos: Position) -> None:
        """v16c loss-streak state from the closed EDGE plans (same loss definition as the martingale: r_net <= -mart_loss_r)."""
        tc = self.tcfg
        if tc.streak_n <= 0 or pos.plan.grid_leg:
            return
        net = sum(l.pnl for l in pos.legs) - pos.commission + pos.swap
        r = net / pos.risk_money if pos.risk_money > 0 else 0.0
        if r <= -tc.mart_loss_r:
            t = pos.close_time
            self.streak_losses = [x for x in self.streak_losses if (t - x).total_seconds() <= tc.streak_days * 86400] + [t]
        elif r > 0:
            self.streak_losses = []

    # ------------------------------------------------------------------ v14 martingale / grid
    def _apply_v15(self, plan: TradePlan) -> None:
        """v15 conviction / tier sizing (multiplies ``risk_scale``; defaults 1.0 = byte-identical to v14)."""
        tc = self.tcfg
        rs = plan.risk_scale if plan.risk_scale > 0 else 1.0
        if plan.tier:
            rs *= tc.tier_risk_scale
            self.tier_trades_placed += 1
        elif plan.confluent:
            rs *= tc.confluent_risk_scale
        else:
            rs *= tc.plain_risk_scale
        if plan.rank > 1:
            rs *= tc.rank2_risk_scale                  # v16
            if plan.reentry_n == 0:
                self.rank2_placed += 1
        rs *= self.tf_scale.get(plan.tf, 1.0)          # v16 per-TF scale
        if plan.counter_trend:                         # v16b trend_mode=scale
            rs *= tc.trend_risk_scale
        if self.regime_side and plan.regime:           # v16b regime x side scale
            rs *= self.regime_side.get((plan.regime, plan.side), 1.0)
        plan.risk_scale = rs

    def _apply_v14(self, plan: TradePlan, base: float) -> None:
        """Sequence sizing: scale the plan's risk from the closed-trade streak; the recovery plan may get its own ladder.
        Grid: the EDGE leg carries ``grid_base_frac`` of the budget."""
        tc = self.tcfg
        if self.mart.on:
            m, step = self.mart.scale(plan, base)
            if step > 0 and (plan.tier or (tc.mart_confluent_only and not plan.confluent)):
                m, step = 1.0, 0            # v15: tier plans / plain plans (with the gate) are never stepped up
            plan.mart_scale, plan.mart_step = m, step
            apply_mart_ladder(plan, tc, self.spec)
        if grid_wanted(plan, tc):
            plan.risk_scale = (plan.risk_scale if plan.risk_scale > 0 else 1.0) * tc.grid_base_frac

    def _place_deep(self, edge: TradePlan, base: float, minute: int, exp_min: int) -> None:
        """Grid: place the DEEP limit order of ``edge`` (same stop, deeper entry, its share of the budget)."""
        tc = self.tcfg
        if not grid_wanted(edge, tc):
            return
        deep = grid_deep_plan(edge, tc, self.spec)
        if deep is None:
            return
        # the deep leg's risk_scale already contains add_frac / base_frac x the edge scale (edge scale includes base_frac)
        deep.mart_scale, deep.mart_step = edge.mart_scale, edge.mart_step
        sz = size_plan(deep, base, tc, self.spec)
        if not sz.ok:
            self.skipped.append((deep.key, "grid: " + sz.reason))
            return
        self.pending[deep.key] = Pending(deep, pd.Timestamp(self.idx[minute]), minute, sz.lots_leg1, sz.lots_leg2, exp_min,
                                         lots_legs=sz.lots_legs)
        self.grid_placed += 1

    def _grid_sync(self, key: str, reason: str, minute: int) -> None:
        """The edge order/position of a grid ended -> its deep order follows (cancel), unless the deep leg is already a position."""
        if self.tcfg.grid_add_r <= 0:
            return
        dk = key + "+g"
        if dk in self.pending:
            self._cancel(dk, reason, minute)

    def _cancel(self, key: str, reason: str, minute: int) -> None:
        p = self.pending.pop(key, None)
        if p is not None:
            p.reason_cancel = reason
            self.cancelled.append(p)
            self._remember(p.plan, minute, filled=False)
            if not p.plan.grid_leg:
                self._grid_sync(key, reason, minute)

    def _mirror_cancel(self, key: str, reason: str, minute: int) -> None:
        """Mirror policy cancel; with ``cancel_grace_min`` > 0 the order is only scheduled for cancellation.
        v12 ``keep_replaced_bars``: an order whose POI was merely REPLACED on its slot stays that many bars of its
        timeframe (re-shown in time -> kept); a 'no longer shown' clear still cancels at once."""
        g = self.tcfg.cancel_grace_min
        p = self.pending.get(key)
        if reason == "replaced" and self.tcfg.keep_replaced_bars > 0 and p is not None and \
                (not self.tcfg.keep_replaced_tfs or p.plan.tf in self.tcfg.keep_replaced_tfs):
            if p.grace_until < 0:
                p.grace_until = minute + self.tcfg.keep_replaced_bars * self._tf_minutes(p.plan.tf)
                p.grace_reason = reason
            return
        if g <= 0:
            self._cancel(key, reason, minute)
            return
        if p is not None and p.grace_until < 0:
            p.grace_until = minute + g
            p.grace_reason = reason

    # ------------------------------------------------------------------ v12 re-entry
    def _rearm(self, pos: Position, minute: int) -> None:
        """After a break-even exit re-arm the same plan as a fresh limit order for ``reentry_bars`` bars of its TF."""
        tc = self.tcfg
        old = pos.plan
        if old.reentry_n >= tc.reentry_max or self.halted or self.daily_halt_day is not None or self.stopped_out:
            return
        if tc.reentry_tfs and old.tf not in tc.reentry_tfs:
            return
        if len(self.pending) >= tc.max_pending_orders:
            return
        from dataclasses import replace
        plan = replace(old, reentry_n=old.reentry_n + 1, risk_scale=1.0, mart_scale=1.0, mart_step=0)
        plan.confluent = old.confluent
        plan.tier = getattr(old, "tier", False)
        if plan.key in self.pending or plan.key in self.positions:
            return
        base = self.equity if tc.size_on == "equity" else tc.balance
        self._apply_v15(plan)
        self._apply_v14(plan, base)
        sz = size_plan(plan, base, tc, self.spec)
        if not sz.ok:
            self.skipped.append((plan.key, sz.reason))
            return
        bid = self.close[minute]
        ask = bid + self.spread[minute]
        need = self.spec.margin_required(sz.lots_total, plan.entry)
        free = self.equity - self._margin_used(bid)
        if need > free * tc.margin_buffer:
            self.skipped.append((plan.key, "insufficient margin"))
            return
        # the position was just stopped at break-even -> price is at / through the entry: the limit order only becomes
        # live once a bar opens in front of the entry again (MT5 would reject a buy limit above the ask)
        armed = (ask > plan.entry) if plan.is_buy else (bid < plan.entry)
        exp = minute + tc.reentry_bars * self._tf_minutes(plan.tf)
        self.pending[plan.key] = Pending(plan, pd.Timestamp(self.idx[minute]), minute, sz.lots_leg1, sz.lots_leg2, exp,
                                         lots_legs=sz.lots_legs, armed=armed)
        self.reentries_placed += 1

    # ------------------------------------------------------------------ fills
    def _try_fill(self, pend: Pending, minute: int) -> Optional[Position]:
        plan = pend.plan
        sp = self.spread[minute]
        if not pend.armed:
            # v12 re-entry waiting for the price to be back in front of the entry (checked at the bar's open)
            if (plan.is_buy and self.open_[minute] + sp > plan.entry) or (not plan.is_buy and self.open_[minute] < plan.entry):
                pend.armed = True
            else:
                return None
        if plan.is_buy:
            # ask path: open_ask, low_ask ... filled if low ask <= limit
            if self.low[minute] + sp > plan.entry:
                return None
            fill = min(plan.entry, self.open_[minute] + sp)        # gap through the limit -> better price
        else:
            if self.high[minute] < plan.entry:
                return None
            fill = max(plan.entry, self.open_[minute])
        # v16b impulsive-arrival guard: the order would fill within min_fill_age_min minutes of its placement
        tc = self.tcfg
        if tc.min_fill_age_min > 0 and not plan.grid_leg and plan.reentry_n == 0 and self._fast_scope(plan) \
                and (minute - pend.placed_minute) < tc.min_fill_age_min:
            if tc.fast_fill_mode == "cancel":
                self.fast_cancelled += 1
                self._cancel(plan.key, "fast fill", minute)
                return None
            if not plan.fast_fill:
                plan.fast_fill = True
                self.fast_scaled += 1
                f = tc.fast_fill_scale
                pend.lots_leg1 = self.spec.round_volume_down(pend.lots_leg1 * f)
                pend.lots_leg2 = self.spec.round_volume_down(pend.lots_leg2 * f)
                pend.lots_legs = tuple(self.spec.round_volume_down(x * f) for x in pend.lots_legs)
                if pend.lots_leg1 + pend.lots_leg2 <= 0 and sum(pend.lots_legs) <= 0:
                    self.fast_cancelled += 1
                    self._cancel(plan.key, "fast fill (below min volume)", minute)
                    return None
        if plan.grid_leg:
            # v14 deep leg: belongs to the edge plan -> does not take a slot; only fills while the edge plan is still alive
            if plan.grid_parent not in self.positions and plan.grid_parent not in self.pending:
                self._cancel(plan.key, "edge plan gone", minute)
                return None
        elif sum(1 for p in self.positions.values() if not p.plan.grid_leg) >= self.tcfg.max_open_positions:
            self._cancel(plan.key, "max open positions at fill time", minute)
            return None
        fill = self.spec.round_price(fill)
        lots = pend.lots_leg1 + pend.lots_leg2
        legs = []
        if len(plan.tps) > 2 and pend.lots_legs:
            # v9 ladder (3+ legs) - always split legs with server-side targets
            for lv, tp in zip(pend.lots_legs, plan.tps):
                if lv > 0:
                    legs.append(Leg(lv, tp, plan.sl))
        elif self.tcfg.exec_mode == "netting":
            legs.append(Leg(round(lots, 8), plan.tp2 if self.tcfg.tp2_r > 0 else 0.0, plan.sl))   # one position; bot closes the partial at market
        else:
            if pend.lots_leg1 > 0:
                legs.append(Leg(pend.lots_leg1, plan.tp1, plan.sl))
            legs.append(Leg(pend.lots_leg2, plan.tp2 if self.tcfg.tp2_r > 0 else 0.0, plan.sl))
        pos = Position(plan=plan, lots=round(lots, 8), legs=legs, entry_time=pd.Timestamp(self.idx[minute]),
                       entry_price=fill, risk_money=lots * self.spec.contract_size * plan.risk)
        pos.commission = lots * self.spec.commission_per_lot          # round turn, charged at open
        self.balance -= pos.commission
        self.traded_pois.add(plan.poi_key)
        if plan.grid_leg:
            self.grid_filled += 1
        # netting mode without a separate leg 1: bot closes partial_frac at market when TP1 is touched
        return pos

    # ------------------------------------------------------------------ path helpers
    def _path(self, minute: int, side_ask: bool, buy: Optional[bool] = None) -> List[float]:
        """Intrabar path for one minute in the MT5-tester convention: the extreme AGAINST the
        close is visited first - bullish bar O -> L -> H -> C, bearish bar O -> H -> L -> C.
        ``intrabar="worst"``: the adverse extreme of the position is ALWAYS visited first
        (long: O -> L -> H -> C, short: O -> H -> L -> C) -> stop before target, every bar.
        ``side_ask`` shifts the whole path by the minute's spread (ask side)."""
        o, h, l, c = self.open_[minute], self.high[minute], self.low[minute], self.close[minute]
        sp = self.spread[minute] if side_ask else 0.0
        if self.tcfg.intrabar == "worst" and buy is not None:
            seq = [o, l, h, c] if buy else [o, h, l, c]
        else:
            seq = [o, l, h, c] if c >= o else [o, h, l, c]
        return [x + sp for x in seq]

    def _walk_position(self, pos: Position, minute: int, from_fill: bool = False) -> None:
        """Apply one M1 bar to an open position: SL / TP1 / TP2 / BE logic on the right price side.

        ``from_fill``: the position was filled inside this minute -> only the part of the
        path AFTER the fill point (the bar's extreme on the entry side) is replayed.

        v9 additions (all off by default): target ladder (3+ legs), ``be_trigger_r`` (BE on
        bar-close MFE without a partial), ``ratchet_sl`` (after the k-th partial the stop moves
        to the (k-1)-th target), ``trail_r`` (trailing stop updated from the previous closed
        bar's extreme/close - never inside the current bar, as the live bot only sees closed
        bars), ``max_hold_min`` (time stop at market), ``tp2_r = 0`` (runner without target)."""
        plan = pos.plan
        buy = plan.is_buy
        tc = self.tcfg
        # v13: a plan placed in the range regime may carry its own stop schedule
        sl_after_leg = plan.sl_after_leg or tc.sl_after_leg
        # long: stops/TPs on bid (raw bars); short: on ask (bid + spread)
        path = self._path(minute, side_ask=not buy, buy=buy)
        if from_fill:
            # a buy limit fills at the LOW of the ask path, a sell limit at the HIGH of the bid path;
            # replay from that extreme onwards (the fill price itself is the first point)
            ext = min(path) if buy else max(path)
            k0 = path.index(ext)
            # long: path is bid, fill was on ask -> bid at fill = entry - spread; short: path is ask,
            # fill on bid -> ask at fill = entry + spread.  The bar may have continued to its extreme
            # AFTER the fill (start -> ext) - that part can hit the stop - and then moved on.
            start = pos.entry_price - self.spread[minute] if buy else pos.entry_price + self.spread[minute]
            if worst_mode := (tc.intrabar == "worst"):
                path = [start, ext, path[-1]]          # worst: no favourable extreme after the fill
            else:
                path = [start, ext] + path[k0 + 1:]
        hi = max(path)
        lo = min(path)
        worst = tc.intrabar == "worst"
        t = pd.Timestamp(self.idx[minute])
        sgn = 1.0 if buy else -1.0
        # ---- v9: stop management decided on CLOSED bars (before this bar is walked) ---------------
        if not from_fill and (tc.trail_r > 0 or tc.be_trigger_r > 0 or tc.max_hold_min > 0 or tc.trail_after_leg > 0):
            self._manage_before_bar(pos, minute, t)
            if pos.closed:
                return
        # excursions in R (on the closing side of the position)
        if buy:
            pos.mfe_r = max(pos.mfe_r, (hi - pos.entry_price) / plan.risk)
            pos.mae_r = max(pos.mae_r, (pos.entry_price - lo) / plan.risk)
        else:
            pos.mfe_r = max(pos.mfe_r, (pos.entry_price - lo) / plan.risk)
            pos.mae_r = max(pos.mae_r, (hi - pos.entry_price) / plan.risk)
        be_active = pos.partial_done and minute >= pos.be_at_minute and tc.be_on_partial and not sl_after_leg
        if be_active:
            for l in pos.legs:
                if l.open and self._better_stop(buy, plan.be_price, l.sl):
                    l.sl = plan.be_price
        if pos.sl_queue:                      # v10: delayed stop moves (be_delay_bars with sl_after_leg)
            due = [s for (mm, s) in pos.sl_queue if minute >= mm]
            pos.sl_queue = [(mm, s) for (mm, s) in pos.sl_queue if minute < mm]
            for new_sl in due:
                for l in pos.legs:
                    if l.open and self._better_stop(buy, new_sl, l.sl):
                        l.sl = new_sl
        # walk the path segment by segment
        prev = path[0]
        for k, px in enumerate(path):
            seg_lo, seg_hi = min(prev, px), max(prev, px)
            going_up = px > prev
            prev = px
            for leg in pos.legs:
                if not leg.open:
                    continue
                has_tp = leg.tp > 0
                if buy:
                    hit_sl = seg_lo <= leg.sl
                    hit_tp = has_tp and seg_hi >= leg.tp
                else:
                    hit_sl = seg_hi >= leg.sl
                    hit_tp = has_tp and seg_lo <= leg.tp
                if hit_sl and hit_tp:
                    # both inside one segment: the level closer to the segment start is reached first
                    if worst:
                        first_sl = True
                    elif buy:
                        first_sl = not going_up      # moving down -> SL (below) reached first
                    else:
                        first_sl = going_up          # moving up -> SL (above) reached first
                    if k == 0:                       # open gap: whichever is beyond the open
                        first_sl = (path[0] <= leg.sl) if buy else (path[0] >= leg.sl)
                    hit_tp = not first_sl
                    hit_sl = first_sl
                if hit_sl:
                    price = leg.sl
                    if k == 0 and ((buy and path[0] < leg.sl) or (not buy and path[0] > leg.sl)):
                        price = path[0]              # gapped through the stop
                    price = price - tc.sl_slippage if buy else price + tc.sl_slippage
                    if leg.sl == plan.sl:
                        reason = "sl"
                    elif abs(leg.sl - plan.be_price) < self.spec.point / 2:
                        reason = "be"
                    else:
                        reason = "trail" if sgn * (leg.sl - pos.entry_price) > 0 else "sl"
                    self._close_leg(pos, leg, price, t, reason)
                elif hit_tp:
                    price = leg.tp
                    if k == 0 and ((buy and path[0] > leg.tp) or (not buy and path[0] < leg.tp)):
                        price = path[0]
                    is_last = all((not l2.open) or (l2 is leg) for l2 in pos.legs)
                    is_tp1 = (leg.tp == plan.tp1) and not pos.partial_done and len(pos.legs) > 1
                    self._close_leg(pos, leg, price, t, "tp1" if (is_tp1 or not is_last) else "tp2")
                    if not is_last:
                        pos.n_partials += 1
                        if pos.n_partials == 1 and tc.grid_cancel_on_partial and not plan.grid_leg:
                            self._grid_sync(plan.key, "edge took a partial", minute)   # v14: the deep order is withdrawn
                        if is_tp1 or not pos.partial_done:
                            pos.partial_done = True
                            pos.partial_time = t
                            pos.be_at_minute = minute + self.be_delay
                        if self.be_delay == 0 and tc.be_on_partial and pos.n_partials == 1 and not sl_after_leg:
                            for l2 in pos.legs:
                                if l2.open and self._better_stop(buy, plan.be_price, l2.sl):
                                    l2.sl = plan.be_price
                        if sl_after_leg:
                            # v10: per-leg stop schedule (R from entry) for the remaining legs; "x" = leave the stop
                            # index by the ladder LEVEL that was just hit (robust to merged / empty legs)
                            k = plan.tps.index(leg.tp) if leg.tp in plan.tps else pos.n_partials - 1
                            spec_k = sl_after_leg[k] if k < len(sl_after_leg) else "x"
                            if str(spec_k).lower() not in ("x", "", "none"):
                                new_sl = self.spec.round_price(pos.entry_price + sgn * float(spec_k) * plan.risk) \
                                    if abs(float(spec_k)) > 1e-12 else plan.be_price
                                if self.be_delay == 0:
                                    for l2 in pos.legs:
                                        if l2.open and self._better_stop(buy, new_sl, l2.sl):
                                            l2.sl = new_sl
                                else:
                                    pos.sl_queue.append((minute + self.be_delay, new_sl))
                        if tc.ratchet_sl and pos.n_partials >= 2:
                            # stop of the rest -> previous target (the one closed before this one)
                            # closed targets sorted from entry outwards; the second-farthest is the previous one
                            prev_tp = sorted((l2.tp for l2 in pos.legs if not l2.open and l2.tp > 0), reverse=not buy)
                            if len(prev_tp) >= 2:
                                new_sl = prev_tp[-2]
                                for l2 in pos.legs:
                                    if l2.open and self._better_stop(buy, new_sl, l2.sl):
                                        l2.sl = new_sl
                        # the remaining legs only see the part of the segment AFTER the partial
                        seg_lo, seg_hi = min(price, px), max(price, px)
            # netting mode: single leg, bot closes partial_frac at market when TP1 is touched
            if len(pos.legs) == 1 and not pos.partial_done and tc.exec_mode == "netting" and pos.legs[0].open \
                    and plan.partial_frac > 0:
                leg = pos.legs[0]
                touched = (seg_hi >= plan.tp1) if buy else (seg_lo <= plan.tp1)
                if touched:
                    part = self.spec.round_volume_down(leg.lots * plan.partial_frac)
                    if part >= self.spec.volume_min and (leg.lots - part) >= self.spec.volume_min - 1e-9:
                        px_close = plan.tp1 - tc.market_slippage if buy else plan.tp1 + tc.market_slippage
                        new_leg = Leg(part, plan.tp1, leg.sl, open=False, close_price=px_close, close_time=t, close_reason="tp1")
                        new_leg.pnl = sgn * (px_close - pos.entry_price) * part * self.spec.contract_size
                        self.balance += new_leg.pnl
                        leg.lots = round(leg.lots - part, 8)
                        pos.legs.insert(0, new_leg)
                    pos.partial_done = True
                    pos.partial_time = t
                    pos.n_partials += 1
                    pos.be_at_minute = minute + self.be_delay
                    if self.be_delay == 0 and tc.be_on_partial:
                        leg.sl = plan.be_price
                        # rest of this segment (after TP1) can already hit the BE stop
                        rest_lo, rest_hi = min(plan.tp1, px), max(plan.tp1, px)
                        if (buy and rest_lo <= leg.sl) or (not buy and rest_hi >= leg.sl):
                            price = leg.sl - tc.sl_slippage if buy else leg.sl + tc.sl_slippage
                            self._close_leg(pos, leg, price, t, "be")
            if all(not l.open for l in pos.legs):
                break
        # ---- v9: update the trailing high-water mark with this (now closed) bar
        if tc.trail_r > 0 and not pos.closed:
            ref = (hi if tc.trail_source == "extreme" else path[-1]) if buy else (lo if tc.trail_source == "extreme" else path[-1])
            if math.isnan(pos.hwm) or sgn * (ref - pos.hwm) > 0:
                pos.hwm = ref
        if all(not l.open for l in pos.legs):
            self._finish(pos, t)

    @staticmethod
    def _better_stop(buy: bool, new_sl: float, cur_sl: float) -> bool:
        """True when ``new_sl`` is tighter (closer to / beyond price in the favourable direction)."""
        return new_sl > cur_sl if buy else new_sl < cur_sl

    def _manage_before_bar(self, pos: Position, minute: int, t: pd.Timestamp) -> None:
        """v9 stop management evaluated at the OPEN of bar ``minute`` from the bars already closed
        (exactly what the live bot can do once per closed M1 bar): time stop, BE trigger, trailing."""
        plan, tc = pos.plan, self.tcfg
        buy = plan.is_buy
        sgn = 1.0 if buy else -1.0
        # time stop: close the remaining legs at market at this bar's open
        if tc.max_hold_min > 0 and (t - pos.entry_time).total_seconds() / 60.0 >= tc.max_hold_min:
            bid = self.open_[minute]
            ask = bid + self.spread[minute]
            px = (bid - tc.market_slippage) if buy else (ask + tc.market_slippage)
            for leg in pos.legs:
                if leg.open:
                    self._close_leg(pos, leg, px, t, "time")
            self._finish(pos, t)
            return
        # BE trigger on bar-close MFE (independent of partials)
        if tc.be_trigger_r > 0 and not pos.be_armed:
            # pos.mfe_r = MFE of the bars closed so far (this bar has not been walked yet)
            if pos.mfe_r >= tc.be_trigger_r:
                pos.be_armed = True
                for leg in pos.legs:
                    if leg.open and self._better_stop(buy, plan.be_price, leg.sl):
                        leg.sl = plan.be_price
        # trailing stop from the high-water mark of the closed bars
        if tc.trail_r > 0 and not math.isnan(pos.hwm):
            if tc.trail_after_leg > 0:
                if pos.n_partials < tc.trail_after_leg:
                    return
            elif tc.trail_after_partial and not pos.partial_done and len(pos.legs) > 1:
                return
            hwm_r = sgn * (pos.hwm - pos.entry_price) / plan.risk
            if hwm_r < tc.trail_start_r:
                return
            new_sl = self.spec.round_price(pos.hwm - sgn * tc.trail_r * plan.risk)
            for leg in pos.legs:
                if leg.open and self._better_stop(buy, new_sl, leg.sl):
                    leg.sl = new_sl

    def _close_leg(self, pos: Position, leg: Leg, price: float, t: pd.Timestamp, reason: str) -> None:
        sgn = 1.0 if pos.plan.is_buy else -1.0
        leg.open = False
        leg.close_price = self.spec.round_price(price)
        leg.close_time = t
        leg.close_reason = reason
        leg.pnl = sgn * (leg.close_price - pos.entry_price) * leg.lots * self.spec.contract_size
        self.balance += leg.pnl

    def _finish(self, pos: Position, t: pd.Timestamp) -> None:
        pos.closed = True
        pos.close_time = t
        reasons = [l.close_reason for l in pos.legs]
        if "tp2" in reasons:
            pos.outcome = "tp2"
        elif "forced" in reasons:
            pos.outcome = "forced"
        elif "stopout" in reasons:
            pos.outcome = "stopout"
        elif "halt" in reasons:
            pos.outcome = "halt"             # v10: total-loss limit
        elif "daily_halt" in reasons:
            pos.outcome = "daily_halt"       # v10: daily-loss limit
        elif "trail" in reasons:
            pos.outcome = "trail"            # v9: runner stopped by the trailing / ratchet stop in profit
        elif "time" in reasons:
            pos.outcome = "time"             # v9: time stop
        elif "tp1" in reasons and "be" in reasons:
            pos.outcome = "partial_be"
        elif "tp1" in reasons and "sl" in reasons:
            pos.outcome = "partial_sl"       # be_delay: stopped at the ORIGINAL stop after the partial
        elif "be" in reasons:
            pos.outcome = "be"               # v9: BE trigger without a partial
        else:
            pos.outcome = "sl"
        self.positions.pop(pos.plan.key, None)
        self.closed.append(pos)
        self._remember(pos.plan, self.cur_minute, filled=True)
        # v14: the streak state sees every closed EDGE plan (deep grid legs share the edge's outcome and are not counted twice)
        if self.mart.on and not pos.plan.grid_leg:
            net = sum(l.pnl for l in pos.legs) - pos.commission + pos.swap
            self.mart.on_close(pos.plan.tf, net, net / pos.risk_money if pos.risk_money > 0 else 0.0, pos.plan.mart_step)
        if not pos.plan.grid_leg:
            self._grid_sync(pos.plan.key, "edge closed", self.cur_minute)
        self._streak_update(pos)
        # v12: re-arm the zone after a break-even exit
        if self.tcfg.reentry_bars > 0 and pos.outcome in self.tcfg.reentry_outcomes and not pos.plan.grid_leg:
            self._rearm(pos, self.cur_minute)

    def _force_close_all(self, minute: int, reason: str) -> None:
        t = pd.Timestamp(self.idx[minute])
        bid = self.close[minute]
        ask = bid + self.spread[minute]
        for pos in list(self.positions.values()):
            for leg in pos.legs:
                if leg.open:
                    px = (bid - self.tcfg.market_slippage) if pos.plan.is_buy else (ask + self.tcfg.market_slippage)
                    self._close_leg(pos, leg, px, t, reason)
            self._finish(pos, t)
        for k in list(self.pending):
            self._cancel(k, reason, minute)

    # ------------------------------------------------------------------ main loop
    def run(self, progress: bool = False) -> "SimResult":
        ev_i = 0
        n_ev = len(self.sel)
        last_day = None
        sample_every = 60
        for m in range(self.n):
            if self.stopped_out or self.halted:
                break
            self.cur_minute = m
            t64 = self.idx[m]
            # 1) act on selection events stamped at/before this bar's open
            if ev_i < n_ev and self.sel_minute[ev_i] <= m:
                if self.tcfg.max_rank > 1:
                    j = ev_i
                    while j < n_ev and self.sel_minute[j] <= m:
                        j += 1
                    b = self.sel.iloc[ev_i:j]
                    b = b[(b.event == "set") & (b.id >= 0)]
                    self._batch_set = set(zip(b.tf, b.side, b.id.astype(int)))
                while ev_i < n_ev and self.sel_minute[ev_i] <= m:
                    self._on_event(self.sel.iloc[ev_i], m)
                    ev_i += 1
            # 2) expire pending (persist policy) / v11 grace period elapsed
            for k, p in list(self.pending.items()):
                if m >= p.expires_minute:
                    self._cancel(k, "expired", m)
                elif p.grace_until >= 0 and m >= p.grace_until:
                    self._cancel(k, p.grace_reason + " (grace)", m)
            # 3) fills (a pending order filled this minute is also exposed to the rest of this minute's path)
            for k, p in list(self.pending.items()):
                if k not in self.pending:          # v14: cancelled by an earlier fill of this minute (grid sync)
                    continue
                pos = self._try_fill(p, m)
                if pos is not None:
                    self.pending.pop(k, None)
                    self.positions[k] = pos
                    # after a fill the remaining path of the minute can hit SL/TP
                    self._walk_position(pos, m, from_fill=True)
                    if pos.closed:
                        continue
            # 4) walk open positions (those filled this minute were already walked)
            for pos in list(self.positions.values()):
                if pos.entry_time != pd.Timestamp(t64):
                    self._walk_position(pos, m)
            # 5) swaps at the daily rollover (server midnight) and equity
            day = t64.astype("datetime64[D]")
            if last_day is not None and day != last_day and self.positions:
                wd = pd.Timestamp(day).weekday()
                mult = 3.0 if wd == self.spec.swap_triple_weekday else 1.0
                for pos in self.positions.values():
                    per = self.spec.swap_long_per_lot if pos.plan.is_buy else self.spec.swap_short_per_lot
                    s = per * pos.open_lots * mult
                    pos.swap += s
                    self.balance += s
            if last_day is not None and day != last_day:
                self.day_start_balance = self.balance + self._floating(self.close[m], self.close[m] + self.spread[m])
                self.day_start_equity = self.day_start_balance
                self.daily_halt_day = None                  # a new server day: trading allowed again
            last_day = day
            # optional weekend flatten
            if self.tcfg.friday_close_hour_server is not None:
                ts = pd.Timestamp(t64)
                if ts.weekday() == 4 and ts.hour >= self.tcfg.friday_close_hour_server and (self.positions or self.pending):
                    self._force_close_all(m, "forced")
            bid = self.close[m]
            ask = bid + self.spread[m]
            self.equity = self.balance + self._floating(bid, ask)
            # v10 account protection: total limit (halt for good) then daily limit (flat until the next server day)
            if self.tcfg.max_total_loss_pct > 0 and not self.halted and \
                    self.equity <= self.tcfg.balance * (1.0 - self.tcfg.max_total_loss_pct / 100.0):
                self._force_close_all(m, "halt")
                self.halted = True
                self.halt_time = pd.Timestamp(t64)
                self.equity = self.balance
            elif self.tcfg.max_daily_loss_pct > 0 and self.daily_halt_day is None and \
                    self.equity <= self.day_start_balance * (1.0 - self.tcfg.max_daily_loss_pct / 100.0):
                self._force_close_all(m, "daily_halt")
                self.daily_halt_day = day
                self.daily_halts.append((pd.Timestamp(t64), self.equity))
                self.equity = self.balance
            used = self._margin_used(bid)
            if used > 0 and self.equity / used < self.tcfg.stop_out_level:
                self._force_close_all(m, "stopout")
                self.stopped_out = True
                self.equity = self.balance
            # v16c: running peak of the dd basis (the live bot keeps the same number in trader_state.json)
            cur = self.equity if self.tcfg.dd_basis == "equity" else self.balance
            if cur > self.peak_equity:
                self.peak_equity = cur
            if self.tcfg.dd_throttle_pct > 0 and self.peak_equity > 0 and \
                    100.0 * (1.0 - cur / self.peak_equity) > self.tcfg.dd_throttle_pct:
                self.dd_minutes += 1
            if m % sample_every == 0 or m == self.n - 1:
                self.equity_curve.append((t64, self.balance, self.equity))
            if progress and m % 50000 == 0:
                print(f"  {pd.Timestamp(t64)}  bal {self.balance:.0f} eq {self.equity:.0f} open {len(self.positions)} "
                      f"pend {len(self.pending)} closed {len(self.closed)}", flush=True)
        # end of data: mark open positions to market (they stay open live; we close them for the statistics)
        if self.positions:
            self._force_close_all(self.n - 1, "forced")
        return SimResult(self)


# ---------------------------------------------------------------------------- result
class SimResult:
    def __init__(self, sim: PortfolioSimulator):
        self.sim = sim
        self.tcfg = sim.tcfg
        self.trades = self._trades_frame()
        self.equity = pd.DataFrame(sim.equity_curve, columns=["time", "balance", "equity"]).set_index("time")

    def _trades_frame(self) -> pd.DataFrame:
        rows = []
        cs = self.sim.spec.contract_size
        for p in self.sim.closed:
            gross = sum(l.pnl for l in p.legs)
            net = gross - p.commission + p.swap
            rows.append({
                "key": p.plan.key, "tf": p.plan.tf, "poi_id": p.plan.poi_id, "kind": p.plan.kind, "side": p.plan.side,
                "quality": p.plan.quality, "grade": p.plan.grade, "selected_time": p.plan.selected_time,
                "entry_time": p.entry_time, "close_time": p.close_time,
                "hold_min": (p.close_time - p.entry_time).total_seconds() / 60.0 if p.close_time is not None else np.nan,
                "entry": p.entry_price, "limit": p.plan.entry, "sl": p.plan.sl, "tp1": p.plan.tp1, "tp2": p.plan.tp2,
                "zone_top": p.plan.zone_top, "zone_bottom": p.plan.zone_bottom, "risk_usd_per_unit": p.plan.risk,
                "atr": p.plan.atr, "lots": p.lots, "risk_money": p.risk_money,
                "gross": gross, "commission": p.commission, "swap": p.swap, "net": net,
                "r_gross": gross / p.risk_money if p.risk_money > 0 else np.nan,
                "r_net": net / p.risk_money if p.risk_money > 0 else np.nan,
                "outcome": p.outcome, "partial": p.partial_done, "mfe_r": p.mfe_r, "mae_r": p.mae_r,
                "reentry": p.plan.reentry_n, "confluent": bool(getattr(p.plan, "confluent", False)),
                "regime": getattr(p.plan, "regime", ""),
                "mart_step": p.plan.mart_step, "mart_scale": round(p.plan.mart_scale, 4),
                "grid_leg": bool(p.plan.grid_leg), "grid_parent": p.plan.grid_parent,
                "tier": bool(getattr(p.plan, "tier", False)), "risk_scale": round(p.plan.risk_scale, 4),
                "rank": int(getattr(p.plan, "rank", 1)),
                "counter_trend": bool(getattr(p.plan, "counter_trend", False)),
                "fast_fill": bool(getattr(p.plan, "fast_fill", False)),
                "dd_scale": float(getattr(p.plan, "dd_scale", 1.0)), "dd_pct_at": float(getattr(p.plan, "dd_pct_at", 0.0)),
                "legs": ";".join(f"{l.lots}@{l.close_price:.2f}:{l.close_reason}" for l in p.legs),
            })
        df = pd.DataFrame(rows)
        if len(df):
            df = df.sort_values("close_time").reset_index(drop=True)
            df["cum_net"] = df.net.cumsum()
            df["cum_r"] = df.r_net.cumsum()
        return df

    # ------------------------------------------------------------------ stats
    def summary(self) -> Dict[str, float]:
        t = self.trades
        s = self.sim
        out: Dict[str, float] = {"start_balance": self.tcfg.balance, "end_balance": round(s.balance, 2),
                                 "trades": len(t), "pending_placed": len(t) + len(s.cancelled),
                                 "cancelled": len(s.cancelled), "skipped": len(s.skipped),
                                 "reentries_placed": s.reentries_placed,
                                 "reentry_trades": int((t.reentry > 0).sum()) if len(t) else 0,
                                 "confluent_trades": int(t.confluent.sum()) if len(t) else 0,
                                 "range_trades": int((t.regime == "range").sum()) if len(t) else 0,
                                 "range_plans": s.regime_counts.get("range", 0),
                                 "mart_trades": int((t.mart_step > 0).sum()) if len(t) else 0,
                                 "mart_down_trades": int((t.mart_step < 0).sum()) if len(t) else 0,
                                 "mart_max_scale": round(float(t.mart_scale.max()), 3) if len(t) else 1.0,
                                 "grid_placed": s.grid_placed, "grid_filled": s.grid_filled,
                                 "grid_leg_trades": int(t.grid_leg.sum()) if len(t) else 0,
                                 "edge_trades": int((~t.grid_leg).sum()) if len(t) else 0,
                                 "tier_placed": s.tier_trades_placed,
                                 "tier_trades": int(t.tier.sum()) if len(t) and "tier" in t else 0,
                                 "rank2_placed": s.rank2_placed,
                                 "rank2_trades": int((t["rank"] > 1).sum()) if len(t) and "rank" in t else 0,
                                 "trend_skipped": s.trend_skipped, "trend_scaled": s.trend_scaled,
                                 "fast_cancelled": s.fast_cancelled, "fast_scaled": s.fast_scaled,
                                 "counter_trend_trades": int(t.counter_trend.sum()) if len(t) and "counter_trend" in t else 0,
                                 "fast_fill_trades": int(t.fast_fill.sum()) if len(t) and "fast_fill" in t else 0,
                                 "dd_scaled": s.dd_scaled, "dd_skipped": s.dd_skipped, "dd_days": round(s.dd_minutes / 1440.0, 1),
                                 "day_soft_scaled": s.day_soft_scaled, "day_soft_skipped": s.day_soft_skipped,
                                 "open_risk_scaled": s.open_risk_scaled, "open_risk_skipped": s.open_risk_skipped,
                                 "streak_scaled": s.streak_scaled,
                                 "dd_scaled_trades": int((t.dd_scale < 1.0).sum()) if len(t) and "dd_scale" in t else 0}
        if not len(t):
            return out
        r = t.r_net
        eq = self.equity.equity
        peak = eq.cummax()
        dd = (eq - peak)
        dd_pct = (eq / peak - 1.0)
        days = max((t.close_time.max() - t.entry_time.min()).total_seconds() / 86400.0, 1.0)
        wins = t[t.net > 0]
        losses = t[t.net < 0]
        cum_r = r.cumsum()
        dd_r = (cum_r - cum_r.cummax()).min()
        out.update({
            "net_profit": round(t.net.sum(), 2),
            "return_%": round(100 * (s.balance / self.tcfg.balance - 1), 2),
            "total_R": round(r.sum(), 2),
            "avg_R": round(r.mean(), 4),
            "median_R": round(r.median(), 4),
            "win_%": round(100 * (t.net > 0).mean(), 1),
            "profit_factor": round(wins.net.sum() / abs(losses.net.sum()), 3) if len(losses) and losses.net.sum() != 0 else float("inf"),
            "avg_win_R": round(wins.r_net.mean(), 3) if len(wins) else 0.0,
            "avg_loss_R": round(losses.r_net.mean(), 3) if len(losses) else 0.0,
            "max_dd_$": round(dd.min(), 2),
            "max_dd_%": round(100 * dd_pct.min(), 2),
            "max_dd_R": round(dd_r, 2),
            "trades_per_day": round(len(t) / days, 2),
            "days": round(days, 1),
            "sharpe_daily": self._sharpe(),
            "partial_hit_%": round(100 * t.partial.mean(), 1),
            "tp2_%": round(100 * (t.outcome == "tp2").mean(), 1),
            "partial_be_%": round(100 * (t.outcome == "partial_be").mean(), 1),
            "sl_%": round(100 * (t.outcome == "sl").mean(), 1),
            "forced_%": round(100 * (t.outcome.isin(["forced", "stopout"])).mean(), 1),
            "daily_halts": len(s.daily_halts),
            "halted": bool(s.halted),
            "halt_time": str(s.halt_time) if s.halt_time is not None else "",
            "commission_$": round(t.commission.sum(), 2),
            "swap_$": round(t.swap.sum(), 2),
            "avg_hold_min": round(t.hold_min.mean(), 0),
            "median_hold_min": round(t.hold_min.median(), 0),
            "avg_lots": round(t.lots.mean(), 3),
            "avg_risk_$": round(t.risk_money.mean(), 2),
            "expectancy_$": round(t.net.mean(), 2),
            "stopped_out": bool(s.stopped_out),
        })
        return out

    def _sharpe(self) -> float:
        if not len(self.trades):
            return 0.0
        daily = self.trades.set_index("close_time").net.resample("1D").sum()
        daily = daily[daily.index.dayofweek < 5]
        if daily.std() == 0 or len(daily) < 5:
            return 0.0
        return round(float(daily.mean() / daily.std() * math.sqrt(252)), 2)

    def by(self, col: str, t: Optional[pd.DataFrame] = None) -> pd.DataFrame:
        t = self.trades if t is None else t
        if not len(t):
            return pd.DataFrame()
        g = t.groupby(col)
        out = pd.DataFrame({
            "trades": g.size(), "win_%": (100 * g.apply(lambda x: (x.net > 0).mean())).round(1),
            "avg_R": g.r_net.mean().round(4), "total_R": g.r_net.sum().round(2), "net_$": g.net.sum().round(2),
            "tp2_%": (100 * g.apply(lambda x: (x.outcome == "tp2").mean())).round(1),
            "partial_%": (100 * g.partial.mean()).round(1),
            "PF": g.apply(lambda x: x[x.net > 0].net.sum() / abs(x[x.net < 0].net.sum()) if (x.net < 0).any() else float("inf")).round(2),
        })
        return out

    def monthly(self) -> pd.DataFrame:
        t = self.trades
        if not len(t):
            return pd.DataFrame()
        t = t.assign(month=t.close_time.dt.strftime("%Y-%m"))
        return self.by("month", t)

    def skipped_reasons(self) -> pd.Series:
        return pd.Series([r for _, r in self.sim.skipped]).value_counts() if self.sim.skipped else pd.Series(dtype=int)

    def cancel_reasons(self) -> pd.Series:
        return pd.Series([c.reason_cancel for c in self.sim.cancelled]).value_counts() if self.sim.cancelled else pd.Series(dtype=int)

    def filter_reasons(self) -> pd.Series:
        return pd.Series([r for _, r in self.sim.filtered]).value_counts() if self.sim.filtered else pd.Series(dtype=int)
