"""Execution layer - turn a selected POI into a concrete trade plan and size it.

User specification (v7):

* **Entry** = the *start* of the POI = the zone edge that price reaches first
  (top of a bullish zone, bottom of a bearish zone) -> a LIMIT order.
* **Stop loss** = the *end* of the POI = the far edge of the zone.
  -> 1R = zone height (optionally + ``sl_buffer_atr`` x ATR, default 0).
* **Partial close** at ``partial_r`` (0.4R): close ``partial_frac`` (50 %) and move
  the stop of the remainder to break-even (``be_offset_r`` x R above/below entry,
  default 0 = exact entry).
* **TP2** fixed at ``tp2_r`` (1.5R) for the remainder.

MT5 mechanics that matter for realism (both in the simulator and the live bot):

* a BUY LIMIT is filled when the **ask** reaches the limit price, a SELL LIMIT when
  the **bid** does; SL / TP of a long are triggered on the **bid**, of a short on
  the **ask**.  MT5 bars are bid prices; ask = bid + spread.
* MT5 has no native "partial take-profit".  On hedging accounts the plan is sent as
  TWO limit orders of half the volume ("split" mode): leg A carries TP1, leg B
  carries TP2, both carry the zone SL.  When leg A is closed by its server-side TP
  the bot moves leg B's SL to break-even.  Server-side stops keep working even if
  the bot loses the connection.  On netting accounts one order is sent and the bot
  closes half at market when TP1 is touched ("netting" mode).
* volumes are rounded DOWN to ``volume_step`` and must be >= ``volume_min``;
  with 0.01-lot brokers the smallest tradeable plan is 0.02 lots (2 x 0.01 legs).
* stop-outs are market executions: negative slippage ``sl_slippage`` is applied.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Dict, Optional, Tuple

BUY = "buy"
SELL = "sell"


# ---------------------------------------------------------------- symbol / broker
@dataclass
class SymbolSpec:
    """Contract specification (defaults = typical XAUUSD on a 0.01-lot MT5 broker).

    ``commission_per_lot`` is the ROUND-TURN commission in account currency per
    1.0 lot (raw-spread accounts: ~$3.5 per side -> 7.0; standard accounts: 0 but a
    wider spread).  Swaps are per lot per night in account currency (negative =
    you pay); the Wednesday rollover is charged 3x.
    """
    symbol: str = "XAUUSD.t"
    digits: int = 2
    point: float = 0.01
    contract_size: float = 100.0          # 1 lot = 100 oz -> $1 move = $100 / lot
    volume_min: float = 0.01
    volume_max: float = 100.0
    volume_step: float = 0.01
    stops_level_points: int = 0           # broker minimum SL/TP distance (points)
    commission_per_lot: float = 7.0       # round turn, per 1.0 lot
    swap_long_per_lot: float = -50.0      # per night (3x on Wednesday)
    swap_short_per_lot: float = 15.0
    swap_triple_weekday: int = 2          # 0=Mon ... 2=Wed
    leverage: float = 100.0
    currency: str = "USD"

    def round_price(self, p: float) -> float:
        return round(p, self.digits)

    def round_volume_down(self, v: float) -> float:
        steps = math.floor(v / self.volume_step + 1e-9)
        vol = steps * self.volume_step
        vol = min(vol, self.volume_max)
        return round(vol, 8)

    def usd_per_price_unit(self, lots: float) -> float:
        """Account currency P/L for a $1 move of the instrument at ``lots``."""
        return lots * self.contract_size

    def margin_required(self, lots: float, price: float) -> float:
        return lots * self.contract_size * price / self.leverage


# ---------------------------------------------------------------- trader settings
@dataclass
class TraderConfig:
    # --- risk management (user spec)
    risk_pct: float = 1.0                 # % of equity risked per trade (full position, entry -> SL)
    partial_r: float = 0.4                # TP1: close partial_frac of the position here ...
    partial_frac: float = 0.5             # ... 50 %
    be_offset_r: float = 0.0              # ... and move SL to entry + be_offset_r x R
    tp2_r: float = 1.5                    # TP2 for the remainder (0 = no fixed TP2: the runner exits on trail / time / stop only)
    # --- v9 management systems (all off by default -> exactly the v7/v8 behaviour)
    tp_levels: Tuple[str, ...] = ()       # multi-target ladder in R, e.g. 0.4|1.0|2.0 ; () = partial_r / tp2_r
    tp_fracs: Tuple[str, ...] = ()        # fraction closed at each level (same length), e.g. 0.34|0.33|0.33
    be_on_partial: bool = True            # SL -> BE (be_offset_r) when the first partial closes (user spec)
    be_trigger_r: float = 0.0             # 0 = off; >0 = SL -> BE once the bar-close MFE reaches this R (works without a partial)
    ratchet_sl: bool = False              # ladder: after the k-th partial (k>=2) move SL of the rest to the (k-1)-th target
    trail_r: float = 0.0                  # 0 = off; trailing stop distance (x R) for the open legs, updated on closed M1 bars
    trail_start_r: float = 0.0            # trailing becomes active once MFE >= this R (0 = from the fill)
    trail_after_partial: bool = True      # trailing only for the runner after the first partial (False = whole position)
    trail_source: str = "extreme"         # high-water mark from the bar "extreme" or the bar "close"
    max_hold_min: int = 0                 # 0 = off; time stop - close the remaining legs at market after this many minutes
    # --- v10 multi-TP extensions (all off by default -> exactly the v9 behaviour)
    #: stop of the REMAINING legs after the k-th leg closes, in R from the entry, one entry per leg, e.g. "x|0|0.5" =
    #: nothing after leg 1, break-even after leg 2, lock +0.5R after leg 3.  "x" = leave the stop.  When set it REPLACES
    #: be_on_partial (write "0" at position 1 for the classic BE after the first leg).  Stops only ever tighten.
    sl_after_leg: Tuple[str, ...] = ()
    trail_after_leg: int = 0              # trailing (trail_r) only once this many legs have closed (0 = trail_after_partial rule)
    tp_unit: str = "r"                    # "r": targets in R (zone height) | "atr": targets in ATR of the POI's timeframe
    ladder_fallback: str = "reject"       # ladder legs below the broker minimum: "reject" the plan | "merge" them into a neighbour
    sl_buffer_atr: float = 0.0            # SL = far edge (+ buffer x ATR).  User spec: 0
    entry_offset_frac: float = 0.0        # entry = near edge moved INTO the zone by this fraction of the zone (0 = edge)
    size_on: str = "equity"               # "equity" (compounding) | "balance" (initial balance, fixed $ risk)
    # --- execution mode
    exec_mode: str = "split"              # "split" (2 half legs, server-side TPs) | "netting" (1 position, bot partial)
    market_slippage: float = 0.05         # $ adverse slippage on bot-issued market orders (netting partial close)
    sl_slippage: float = 0.10             # $ adverse slippage on stop-outs (market execution)
    spread_multiplier: float = 1.0        # stress test: widen the recorded spread
    intrabar: str = "ohlc"                # "ohlc" = MT5 tester 1-min OHLC tick path | "worst" = SL always first
    # --- order handling
    order_policy: str = "mirror"          # "mirror": pending orders follow the bot's current selection
                                          # "persist": keep a pending order until filled / expired
    max_pending_bars: int = 300           # persist: cancel after this many bars of the POI's timeframe
    max_open_positions: int = 4           # concurrent open trades (plans), all timeframes together
    max_pending_orders: int = 10
    dedupe_overlap: float = 0.5           # skip a new plan if its zone overlaps >= this fraction with an active plan's zone
    # --- v11 "more trades" levers (defaults = exactly the v10 behaviour)
    dedupe_cross_tf: bool = True          # False: the overlap check only looks at active plans of the SAME timeframe
                                          #        (a level seen on two timeframes = confluence -> both may be traded)
    overlap_mode: str = "skip"            # what to do with a plan that overlaps an active plan: "skip" (v10) |
                                          # "allow" (trade it at full risk) | "share" (trade it at risk_pct x overlap_risk_frac)
    overlap_risk_frac: float = 0.5        # share mode: risk fraction of the overlapping (second) plan
    cancel_grace_min: int = 0             # mirror policy: keep a pending order this many MINUTES after the scanner stops
                                          # showing / replaces its POI (re-shown in time -> kept).  0 = cancel at once (v10)
    # --- v12 "more trades, round 2" levers (defaults = exactly the v11 behaviour)
    #: alternative trade-filter string (same syntax as ``trade_filter``) used INSTEAD of ``trade_filter`` when the plan's
    #: zone overlaps (>= dedupe_overlap) an active plan (pending or open, same side) of ANOTHER timeframe = confluence.
    #: "" = no special treatment.  Only meaningful with dedupe_cross_tf=false (otherwise the overlap is skipped anyway).
    confluence_filter: str = ""
    #: mirror policy: an order whose POI is REPLACED by another POI on the same (tf, side) slot is kept for this many bars
    #: of its timeframe instead of being cancelled at once (re-shown in time -> kept for good).  'no longer shown' (clear)
    #: still cancels immediately.  0 = cancel at once (v11)
    keep_replaced_bars: int = 0
    keep_replaced_tfs: Tuple[str, ...] = ()   # () = every timeframe; e.g. M10|M15|M30 = only orders of these TFs are kept
    #: after a position closes at break-even (outcome in ``reentry_outcomes``) re-arm the SAME plan (entry / SL / targets)
    #: as a fresh pending limit order for this many bars of its timeframe, at most ``reentry_max`` times per POI.  0 = off
    reentry_bars: int = 0
    reentry_max: int = 1
    reentry_tfs: Tuple[str, ...] = ()         # () = every timeframe; e.g. M10|M15 = re-arm only plans of these TFs
    reentry_outcomes: Tuple[str, ...] = ("partial_be", "be")
    # --- v13 "weak months" levers (defaults = exactly the v12 behaviour) -------------------------------------------
    #: regime metric from CLOSED daily bars (lubot/regime.py): "" = off | adr_ratio (mean daily range of the last
    #: regime_short days / last regime_long days) | er (efficiency ratio of the closes over regime_short days) |
    #: adr_pct (mean daily range % of the last regime_long days).  The regime is "range" when metric < regime_threshold.
    regime_metric: str = ""
    regime_threshold: float = 0.0
    regime_short: int = 5
    regime_long: int = 20
    #: management used for plans PLACED in a "range" regime (empty = same as the normal one):
    range_tp_levels: Tuple[str, ...] = ()     # alternative ladder levels (R), e.g. 0.5|1.0|1.5|2.5
    range_tp_fracs: Tuple[str, ...] = ()      # alternative ladder fractions
    range_sl_after_leg: Tuple[str, ...] = ()  # alternative stop schedule after each leg (see sl_after_leg)
    range_risk_scale: float = 1.0             # sizing multiplier in the range regime (1 = unchanged, 0 = do not trade)
    range_tfs: Tuple[str, ...] = ()           # () = every timeframe; else only plans of these TFs use the range management
    # ---- v14 martingale A: sequence sizing (lubot/martingale.py).  "" = off (byte-identical to v13)
    mart_mode: str = ""                       # "" | mult | add | fib | deficit | anti
    mart_mult: float = 1.5                    # step multiplier (mult / anti) or 1 + slope (add); < 1 with mult = shrink after losses
    mart_max_steps: int = 3                   # k is capped here (deficit: give up after this many recovery trades)
    mart_max_risk_pct: float = 3.0            # the plan's risk in % of equity is capped here (0 = no cap)
    mart_loss_r: float = 0.2                  # a closed plan counts as a LOSS when r_net <= -this (BE exits are neutral)
    mart_deficit_r: float = 1.0               # deficit mode: recover the deficit with a trade expected to earn this many R
    mart_scope: str = "all"                   # "all" = one streak for the account | "tf" = one streak per timeframe
    mart_tfs: Tuple[str, ...] = ()            # gates: only plans of these TFs / sides / quality / regime are stepped up
    mart_sides: Tuple[str, ...] = ()
    mart_min_quality: float = 0.0
    mart_regime: str = ""                     # "" | range | trend
    mart_ungated_scale: float = 1.0           # ASYMMETRIC: an after-loss plan (k >= 1) that FAILS a gate is sized x this (e.g. 0.5 = step
                                              # down where the post-loss edge is negative); 1 = unchanged (classic gate)
    mart_tp_levels: Tuple[str, ...] = ()      # alternative ladder for the stepped-up (recovery) plans
    mart_tp_fracs: Tuple[str, ...] = ()
    mart_sl_after_leg: Tuple[str, ...] = ()
    # ---- v14 martingale B: zone-averaging grid (a second limit deeper in the zone).  0 = off
    grid_add_r: float = 0.0                   # deep leg's limit = entry + grid_add_r x (sl - entry), i.e. this fraction into the zone
    grid_base_frac: float = 0.5               # share of the plan's risk budget on the EDGE leg
    grid_add_frac: float = 0.5                # share of the budget on the DEEP leg (base + add < 1 -> a stopped plan loses < 1 R)
    grid_tfs: Tuple[str, ...] = ()            # () = every timeframe
    grid_regime: str = ""                     # "" | range | trend: only plans placed in this regime get a deep leg
    grid_cancel_on_partial: bool = True       # cancel the deep order once the edge leg has closed its first target
    grid_deep_ladder: str = "same"            # "same" = the deep leg's targets are the edge leg's prices | "own" = its own R ladder
    # ---- v15 "more trades & more profit at the same loss percentage" levers (defaults = byte-identical to v14)
    #: CONVICTION SIZING: a plan judged CONFLUENT (its zone overlaps an active plan of another timeframe, see
    #: ``confluence_filter``) is sized x confluent_risk_scale, every other plan x plain_risk_scale (1 = unchanged).
    confluent_risk_scale: float = 1.0
    plain_risk_scale: float = 1.0
    #: CONFLUENCE MEMORY: a plan also counts as confluent when its zone overlaps a plan of ANOTHER timeframe that was active
    #: (pending or open, same side) within the last N MINUTES (0 = only plans active right now, v12).  Widens the population
    #: judged by the looser ``confluence_filter`` and sized by ``confluent_risk_scale``.
    confluence_memory_min: int = 0
    confluence_memory_kind: str = "all"       # "all" | "open" (only plans that were FILLED count) | "pending" (only unfilled orders)
    #: TIERED ADMISSION: a plan that FAILS the trade filter (or the confluence filter) but PASSES ``tier_filter`` (same syntax)
    #: is traded anyway at tier_risk_scale x the normal size (a "second tier" of smaller trades).  "" = off.
    #: Only timeframes LISTED in tier_filter get a tier (an unlisted TF is rejected as before).
    tier_filter: str = ""
    tier_risk_scale: float = 0.5
    #: martingale gate (v14): step UP only confluent plans (tier plans are never stepped up)
    mart_confluent_only: bool = False
    # ---- v16 "new trade sources" levers (defaults = byte-identical to v15)
    #: RANKED CANDIDATES: the v16 selection stream carries the scanner's top-K qualified zones per side (`rank` column);
    #: plans of rank <= max_rank are placed (1 = only the slot winner = every stream before v16).  A rank-2 zone that
    #: overlaps the rank-1 zone of the same timeframe is skipped by the normal overlap dedupe.
    max_rank: int = 1
    rank2_filter: str = ""                    # own filter bar for rank >= 2 plans (same syntax); "" = the normal / confluence bar
    rank2_risk_scale: float = 1.0             # sizing multiplier for rank >= 2 plans
    rank2_tfs: Tuple[str, ...] = ()           # timeframes whose rank >= 2 zones are admitted; () = all
    rank2_confluent_only: bool = False        # rank >= 2 plans only when they are confluent (another TF active on the level)
    #: PER-TIMEFRAME risk scale, e.g. "M20:0.5|M5:0.8" (unlisted TFs x1).  Applied on top of the v15 conviction scales.
    tf_risk_scale: str = ""
    one_trade_per_poi: bool = True
    min_quality: Optional[float] = None   # extra filter on top of the scanner's min_quality (None = scanner default)
    grades: Tuple[str, ...] = ()          # e.g. ("A", "B") -> only these grades; () = all
    timeframes: Tuple[str, ...] = ()      # () = every timeframe in the selection stream
    sides: Tuple[str, ...] = ("buy", "sell")
    max_zone_atr: float = 0.0             # skip zones taller than this (x ATR); 0 = off
    min_zone_usd: float = 0.0             # skip zones thinner than this ($); 0 = off
    #: v8 per-timeframe trade filter (lubot/trade_filter.py), e.g.
    #: "M5:max_cost_r=0.08;min_quality=0.55;sessions=london|preny|ny|lclose".  "" = v7 behaviour
    trade_filter: str = ""
    # --- account
    balance: float = 10_000.0
    margin_buffer: float = 0.8            # use at most this share of free margin for new orders
    stop_out_level: float = 0.5           # margin level (equity / margin) below which everything is closed
    friday_close_hour_server: Optional[int] = None   # e.g. 23 -> flatten & cancel before the weekend (None = off)
    # --- v10 account protection (user spec): 0 = off
    max_daily_loss_pct: float = 0.0       # equity (realised + floating) <= day-start balance x (1 - x%) -> flatten, cancel, no new
                                          # orders until the next server day
    max_total_loss_pct: float = 0.0       # equity <= start balance x (1 - x%) -> flatten, cancel, HALT for good

    def override(self, text: Optional[str]) -> "TraderConfig":
        """key=value,key=value (tuples use a|b).  Returns self."""
        if not text:
            return self
        for pair in text.split(","):
            if not pair.strip():
                continue
            k, v = pair.split("=", 1)
            k = k.strip()
            if not hasattr(self, k):
                raise ValueError(f"unknown trader key {k}")
            cur = getattr(self, k)
            v = v.strip()
            if isinstance(cur, bool):
                val = v.lower() in ("1", "true", "yes")
            elif isinstance(cur, int) and not isinstance(cur, bool):
                val = int(v)
            elif isinstance(cur, float):
                val = float(v)
            elif isinstance(cur, tuple):
                val = tuple(x.strip() for x in v.split("|") if x.strip())
            elif cur is None:
                val = None if v.lower() in ("none", "") else (float(v) if k == "min_quality" else int(v))
            else:
                val = v
            setattr(self, k, val)
        return self

    def to_dict(self) -> Dict:
        return asdict(self)


# ---------------------------------------------------------------- trade plan
@dataclass
class TradePlan:
    side: str                     # buy / sell
    entry: float                  # limit price
    sl: float                     # initial stop (far edge)
    tp1: float                    # partial-close level
    tp2: float                    # final target
    be_price: float               # stop after the partial close
    risk: float                   # 1R in price units (|entry - sl|)
    zone_top: float
    zone_bottom: float
    tf: str = ""
    poi_id: int = -1
    kind: str = ""
    quality: float = float("nan")
    grade: str = ""
    atr: float = float("nan")
    selected_time: str = ""
    partial_frac: float = 0.5
    comment: str = ""
    tps: Tuple[float, ...] = ()   # target price of every leg (last leg: tp2, 0.0 = none)
    fracs: Tuple[float, ...] = () # fraction of every leg
    risk_scale: float = 1.0       # v11: sizing multiplier (overlap_mode=share -> overlap_risk_frac)
    reentry_n: int = 0            # v12: 0 = original plan, k = k-th re-entry of the same POI (key gets a '~k' suffix)
    confluent: bool = False       # v12: the plan passed through the confluence_filter (level active on another TF)
    regime: str = ""              # v13: "range" | "trend" | "" (regime lever off) at placement time
    sl_after_leg: Tuple[str, ...] = ()   # v13: per-plan stop schedule (empty = TraderConfig.sl_after_leg)
    mart_step: int = 0            # v14: martingale step this plan was sized with (0 = base size)
    mart_scale: float = 1.0       # v14: the sizing multiplier applied on top of risk_scale
    grid_leg: bool = False        # v14: True = this plan is the DEEP leg of a zone-averaging grid
    grid_parent: str = ""         # v14: key of the edge plan the deep leg belongs to
    tier: bool = False            # v15: True = admitted through ``tier_filter`` (second tier, reduced risk)
    rank: int = 1                 # v16: scanner rank of the zone on its side (1 = slot winner)

    # ---------------------------------------------------------- helpers
    @property
    def is_buy(self) -> bool:
        return self.side == BUY

    @property
    def key(self) -> str:
        return f"{self.tf}#{self.poi_id}" + (f"~{self.reentry_n}" if self.reentry_n else "") + ("+g" if self.grid_leg else "")

    @property
    def poi_key(self) -> str:
        """Key of the POI itself (identical for the original plan and its re-entries)."""
        return f"{self.tf}#{self.poi_id}"

    def r_of(self, price: float) -> float:
        """Signed R multiple of ``price`` relative to entry (positive = in profit)."""
        if self.risk <= 0:
            return 0.0
        return (price - self.entry) / self.risk if self.is_buy else (self.entry - price) / self.risk

    def overlaps(self, other: "TradePlan") -> float:
        """Fraction of the smaller zone covered by the other zone (0..1)."""
        lo = max(self.zone_bottom, other.zone_bottom)
        hi = min(self.zone_top, other.zone_top)
        if hi <= lo:
            return 0.0
        smaller = min(self.zone_top - self.zone_bottom, other.zone_top - other.zone_bottom)
        return (hi - lo) / smaller if smaller > 0 else 1.0

    def to_dict(self) -> Dict:
        return asdict(self)

    # ---------------------------------------------------------- construction
    @classmethod
    def from_poi(cls, d: Dict, tcfg: TraderConfig, spec: Optional[SymbolSpec] = None,
                 selected_time: str = "", regime: str = "") -> Optional["TradePlan"]:
        """Build the plan from a POI dict as returned by ``TimeframeEngine.select()``.

        bullish POI -> BUY LIMIT at the top (start) of the zone, SL at the bottom (end);
        bearish POI -> SELL LIMIT at the bottom, SL at the top.
        Returns ``None`` when the zone is degenerate (zero height).
        """
        spec = spec or SymbolSpec()
        top, bottom = float(d["top"]), float(d["bottom"])
        height = top - bottom
        if height <= 0:
            return None
        atr = float(d.get("atr") or float("nan"))
        if not math.isfinite(atr) or atr <= 0:
            # distance / distance_atr are always present on a selection dict
            da = d.get("distance_atr") or 0.0
            atr = float(d["distance"]) / da if da else float("nan")
        buf = (tcfg.sl_buffer_atr * atr) if (math.isfinite(atr) and tcfg.sl_buffer_atr > 0) else 0.0
        bull = d["direction"] == "bullish"
        if bull:
            entry = top - tcfg.entry_offset_frac * height
            sl = bottom - buf
        else:
            entry = bottom + tcfg.entry_offset_frac * height
            sl = top + buf
        risk = abs(entry - sl)
        if risk <= 0:
            return None
        sgn = 1.0 if bull else -1.0
        rp = spec.round_price
        use_range = regime == "range" and (not tcfg.range_tfs or str(d.get("tf", "")) in tcfg.range_tfs)
        levels, fracs = ladder(tcfg, range_regime=use_range)
        # v10: target unit - R (zone height, default) or the POI timeframe's ATR (falls back to R when ATR is unknown)
        unit = atr if (tcfg.tp_unit == "atr" and math.isfinite(atr) and atr > 0) else risk
        tps = tuple(rp(entry + sgn * lv * unit) if lv > 0 else 0.0 for lv in levels)
        tp1 = entry + sgn * (levels[0] if len(levels) > 1 else tcfg.partial_r) * unit
        tp2 = entry + sgn * tcfg.tp2_r * unit if len(levels) <= 1 else (tps[-1] or entry + sgn * levels[-2] * unit)
        be = entry + sgn * tcfg.be_offset_r * risk
        q = d.get("quality")
        return cls(
            side=BUY if bull else SELL,
            entry=rp(entry), sl=rp(sl), tp1=rp(tp1), tp2=rp(tp2), be_price=rp(be),
            risk=abs(rp(entry) - rp(sl)),
            zone_top=top, zone_bottom=bottom,
            tf=str(d.get("tf", "")), poi_id=int(d.get("id", -1)), kind=str(d.get("type", "")),
            quality=float(q) if q is not None else float("nan"), grade=str(d.get("grade") or ""),
            atr=atr, selected_time=selected_time or str(d.get("time", "")),
            partial_frac=fracs[0] if len(fracs) > 1 else 0.0,
            comment=f"LU {d.get('tf', '')} {d.get('type', '')} #{d.get('id', '')}",
            tps=tps, fracs=tuple(fracs),
            regime=("range" if use_range else ("trend" if regime else "")),
            sl_after_leg=tuple(tcfg.range_sl_after_leg) if (use_range and tcfg.range_sl_after_leg) else (),
            risk_scale=(tcfg.range_risk_scale if use_range else 1.0),
        )


def _retarget(plan: TradePlan, levels: Tuple[float, ...], fracs: Tuple[float, ...], spec: SymbolSpec,
              unit: Optional[float] = None) -> None:
    """Rewrite the plan's targets in place from an (R levels, fractions) ladder.  ``unit`` = 1R in price (default plan.risk)."""
    sgn = 1.0 if plan.is_buy else -1.0
    u = unit if unit else plan.risk
    rp = spec.round_price
    tps = tuple(rp(plan.entry + sgn * lv * u) if lv > 0 else 0.0 for lv in levels)
    plan.tps, plan.fracs = tps, tuple(fracs)
    plan.tp1 = rp(plan.entry + sgn * levels[0] * u)
    if len(levels) > 1:
        plan.tp2 = tps[-1] if tps[-1] else rp(plan.entry + sgn * levels[-2] * u)
    else:
        plan.tp2 = tps[-1]
    plan.partial_frac = fracs[0] if len(fracs) > 1 else 0.0


def apply_mart_ladder(plan: TradePlan, tcfg: TraderConfig, spec: SymbolSpec) -> None:
    """v14: a stepped-up (recovery) plan may use its own ladder / stop schedule (``mart_tp_levels`` ...)."""
    if plan.mart_step <= 0 or not tcfg.mart_tp_levels:
        return
    levels = tuple(float(x) for x in tcfg.mart_tp_levels)
    fr = tuple(float(x) for x in tcfg.mart_tp_fracs) if tcfg.mart_tp_fracs else tuple([1.0 / len(levels)] * len(levels))
    if len(levels) != len(fr):
        raise ValueError("mart_tp_levels and mart_tp_fracs must have the same length")
    tot = sum(fr)
    _retarget(plan, levels, tuple(f / tot for f in fr), spec)
    if tcfg.mart_sl_after_leg:
        plan.sl_after_leg = tuple(tcfg.mart_sl_after_leg)


def grid_deep_plan(edge: TradePlan, tcfg: TraderConfig, spec: SymbolSpec) -> Optional[TradePlan]:
    """v14 zone-averaging: the DEEP leg of ``edge`` - a limit ``grid_add_r`` of the way from the entry to the stop, the SAME
    stop, the same target PRICES (``grid_deep_ladder=same``: the deep leg exits with the edge leg) or its own R ladder from its
    own (shorter) risk (``own``).  Its risk budget share is ``grid_add_frac`` (the edge leg carries ``grid_base_frac``)."""
    from dataclasses import replace
    sgn = 1.0 if edge.is_buy else -1.0
    rp = spec.round_price
    entry = rp(edge.entry - sgn * tcfg.grid_add_r * edge.risk)
    risk = abs(entry - edge.sl)
    if risk <= 0 or (edge.is_buy and entry <= edge.sl) or ((not edge.is_buy) and entry >= edge.sl):
        return None
    deep = replace(edge, entry=entry, risk=risk, grid_leg=True, grid_parent=edge.key, reentry_n=edge.reentry_n,
                   risk_scale=(edge.risk_scale if edge.risk_scale > 0 else 1.0) * tcfg.grid_add_frac / max(tcfg.grid_base_frac, 1e-9),
                   comment=edge.comment + " deep", partial_frac=edge.partial_frac, be_price=rp(entry + sgn * tcfg.be_offset_r * risk))
    deep.confluent = edge.confluent
    if tcfg.grid_deep_ladder == "own":
        # the edge ladder expressed in R of the EDGE, rebuilt from the deep entry with the deep (shorter) risk as the unit
        lv = tuple(round(abs(tp - edge.entry) / edge.risk, 6) if tp > 0 else 0.0 for tp in edge.tps)
        _retarget(deep, lv, edge.fracs, spec)
    # "same": tps / tp1 / tp2 are inherited as prices -> the deep leg exits together with the edge leg
    return deep


def ladder(tcfg: TraderConfig, range_regime: bool = False) -> Tuple[Tuple[float, ...], Tuple[float, ...]]:
    """(R levels, fractions) of the legs.  Default = (partial_r, tp2_r) / (partial_frac, 1 - partial_frac);
    ``partial_frac = 0`` -> a single leg at tp2_r; ``tp_levels`` / ``tp_fracs`` -> arbitrary ladder.
    A level of 0 means "no fixed target" (only allowed for the last leg).
    v13 ``range_regime=True``: ``range_tp_levels`` / ``range_tp_fracs`` replace the normal ladder when set."""
    tp_levels, tp_fracs = tcfg.tp_levels, tcfg.tp_fracs
    if range_regime and tcfg.range_tp_levels:
        tp_levels = tcfg.range_tp_levels
        tp_fracs = tcfg.range_tp_fracs or ()
    if tp_levels:
        levels = tuple(float(x) for x in tp_levels)
        fracs = tuple(float(x) for x in tp_fracs) if tp_fracs else tuple([1.0 / len(levels)] * len(levels))
        if len(levels) != len(fracs):
            raise ValueError("tp_levels and tp_fracs must have the same length")
        tot = sum(fracs)
        fracs = tuple(f / tot for f in fracs)
        return levels, fracs
    if tcfg.partial_frac <= 0:
        return (tcfg.tp2_r,), (1.0,)
    return (tcfg.partial_r, tcfg.tp2_r), (tcfg.partial_frac, 1.0 - tcfg.partial_frac)


# ---------------------------------------------------------------- sizing
@dataclass
class Sizing:
    lots_total: float
    lots_leg1: float      # closed at TP1 (partial)
    lots_leg2: float      # runs to TP2 (sum of all further legs)
    risk_money: float     # money at risk at the initial stop (entry -> SL, without costs)
    reason: str = ""      # non-empty when the plan cannot be traded
    lots_legs: Tuple[float, ...] = ()   # per-leg volumes (ladder); len 1 or 2 in the v7/v8 plans

    @property
    def ok(self) -> bool:
        return self.lots_total > 0 and not self.reason


def size_plan(plan: TradePlan, equity: float, tcfg: TraderConfig, spec: SymbolSpec) -> Sizing:
    """Risk ``risk_pct`` % of ``equity`` between entry and the initial stop.

    Volumes are rounded DOWN to the broker step.  In split mode both legs must be
    at least ``volume_min``; if the account is too small for two legs the plan is
    rejected (never over-risk silently).
    """
    if plan.risk <= 0:
        return Sizing(0, 0, 0, 0, "zero risk")
    risk_money = equity * tcfg.risk_pct / 100.0 * (plan.risk_scale if plan.risk_scale > 0 else 1.0) \
        * (plan.mart_scale if plan.mart_scale > 0 else 1.0)
    per_unit = spec.usd_per_price_unit(1.0) * plan.risk      # $ lost per 1.0 lot at the stop
    lots = spec.round_volume_down(risk_money / per_unit) if per_unit > 0 else 0.0
    if lots < spec.volume_min:
        return Sizing(0, 0, 0, 0, f"risk {risk_money:.2f} too small for {spec.volume_min} lots (1R = {plan.risk:.2f})")
    fracs = plan.fracs if len(plan.fracs) > 2 else ()
    if fracs:
        # ladder with 3+ legs: round every leg down, the last leg takes the remainder
        legs = [spec.round_volume_down(lots * f) for f in fracs[:-1]]
        legs.append(spec.round_volume_down(lots - sum(legs)))
        if any(l < spec.volume_min for l in legs) and tcfg.ladder_fallback == "merge":
            # v10: merge the un-rounded small legs into a neighbour, then round; the last non-empty leg takes the rest
            raw = merge_small_legs([lots * f for f in fracs], spec.volume_min)
            legs = [spec.round_volume_down(x) if x > 0 else 0.0 for x in raw]
            if not any(x > 0 for x in legs):
                legs = [0.0] * (len(legs) - 1) + [lots]              # whole (tiny) volume on the last target
            last = max(i for i, x in enumerate(legs) if x > 0)
            legs[last] = spec.round_volume_down(lots - sum(legs[:last] + legs[last + 1:]))
        if tcfg.exec_mode == "split" and any(0 < l < spec.volume_min for l in legs):
            return Sizing(0, 0, 0, 0, f"volume {lots} cannot be split into {len(fracs)} legs >= {spec.volume_min}")
        if tcfg.exec_mode == "split" and any(l == 0 for l in legs) and tcfg.ladder_fallback != "merge":
            return Sizing(0, 0, 0, 0, f"volume {lots} cannot be split into {len(fracs)} legs >= {spec.volume_min}")
        if tcfg.exec_mode != "split" and any(l < spec.volume_min for l in legs):
            legs = [0.0] * (len(legs) - 1) + [lots]
        tot = round(sum(legs), 8)
        return Sizing(tot, legs[0], round(tot - legs[0], 8), tot * spec.usd_per_price_unit(1.0) * plan.risk,
                      lots_legs=tuple(legs))
    leg1 = spec.round_volume_down(lots * plan.partial_frac)
    leg2 = spec.round_volume_down(lots - leg1)
    if tcfg.exec_mode == "split":
        if (plan.partial_frac > 0 and leg1 < spec.volume_min) or leg2 < spec.volume_min:
            return Sizing(0, 0, 0, 0, f"volume {lots} cannot be split into two legs >= {spec.volume_min}")
    else:
        if leg1 < spec.volume_min:      # netting: the partial close must itself be a valid volume
            leg1, leg2 = 0.0, lots
    actual_risk = (leg1 + leg2) * spec.usd_per_price_unit(1.0) * plan.risk
    return Sizing(round(leg1 + leg2, 8), leg1, leg2, actual_risk, lots_legs=(leg1, leg2) if leg1 > 0 else (leg2,))


def merge_small_legs(legs, vmin: float):
    """v10 ``ladder_fallback="merge"``: legs below the broker minimum are merged into a neighbour (the NEXT / farther
    target when there is one, else the previous) until every non-empty leg is tradeable.  The ladder keeps its
    targets - a merged leg simply has volume 0 (it is never sent).  Total volume is unchanged."""
    legs = [round(l, 8) for l in legs]
    while True:
        small = [i for i, l in enumerate(legs) if 0 < l < vmin - 1e-9]
        if not small:
            break
        i = min(small, key=lambda k: legs[k])
        nxt = [j for j in range(i + 1, len(legs)) if legs[j] > 0]
        prv = [j for j in range(i - 1, -1, -1) if legs[j] > 0]
        if not nxt and not prv:
            break
        j = nxt[0] if nxt else prv[0]
        legs[j] = round(legs[j] + legs[i], 8)
        legs[i] = 0.0
    return legs


def expected_outcomes(tcfg: TraderConfig) -> Dict[str, float]:
    """The three possible gross results of one plan in R of the FULL position."""
    f = tcfg.partial_frac
    return {
        "stop_before_partial": -1.0,
        "partial_then_breakeven": f * tcfg.partial_r + (1 - f) * tcfg.be_offset_r,
        "partial_then_tp2": f * tcfg.partial_r + (1 - f) * tcfg.tp2_r,
    }
