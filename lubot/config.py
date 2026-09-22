"""Configuration for the Liquidity University POI bot.

All numeric thresholds are expressed in multiples of ATR (per timeframe) so the
same settings work on every timeframe (the market is fractal - PDF "Fractal Nature").
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple


TIMEFRAME_MINUTES = {
    "M1": 1,
    "M2": 2,
    "M3": 3,
    "M4": 4,
    "M5": 5,
    "M10": 10,
    "M15": 15,
    "M30": 30,
    "H1": 60,
    "H4": 240,
    "D1": 1440,
}


@dataclass
class StrategyConfig:
    # ---------------------------------------------------------------- general
    symbol: str = "XAUUSD.t"
    timeframes: Tuple[str, ...] = ("M5", "M10", "M15", "M30", "H1")
    #: broker/server time offset from UTC in hours (used to convert to New York
    #: time for the Asia session 17:00-00:00 NY). MT5 mode auto-detects it.
    server_utc_offset_hours: float = 3.0
    #: Most MT5 brokers run EET server time which tracks US DST, so
    #: server = NY + 7h all year (gold opens 01:00 server = 18:00 NY Sunday).
    #: When set, this fixed offset is used instead of the UTC conversion.
    server_minus_ny_hours: float | None = 7.0
    atr_period: int = 14

    # ---------------------------------------------------------- liquidity
    #: two unbroken swing highs/lows closer than this (x ATR) are "Equal Highs/Lows"
    equal_level_tolerance_atr: float = 0.15
    #: swings older than this many bars are dropped from the liquidity map
    max_swing_age_bars: int = 1500

    # ---------------------------------------------------------- orderblock
    #: the up/down move must close beyond the block's body within N bars
    ob_displacement_bars: int = 3
    #: "body" (PDF author preference) or "full" candle zone
    ob_zone: str = "body"
    #: Orderblock MUST take out liquidity (PDF).  Keep True.
    ob_require_liquidity_sweep: bool = True

    # ---------------------------------------------------------- imbalance
    #: ignore gaps smaller than this (x ATR)
    imbalance_min_size_atr: float = 0.10

    # ---------------------------------------------------------- hidden base
    #: lower timeframe used to look inside the HTF impulse
    hidden_base_ltf: str = "M1"

    # ---------------------------------------------------------- unmitigated wick
    uw_min_wick_atr: float = 0.35
    #: wick must be at least this fraction of the candle range
    uw_min_wick_ratio: float = 0.45

    # ---------------------------------------------------------- mitigation / order flow
    #: a mitigated POI counts as "respected" when price moved away at least this
    #: far (x ATR) in the POI direction after the tap without closing through it
    respect_move_atr: float = 1.0
    #: how far back (bars) a respected POI can be to count as order-flow support
    orderflow_lookback_bars: int = 600
    #: POI types that can act as order flow support
    orderflow_types: Tuple[str, ...] = ("OB", "BB", "IMB", "HB", "UW")
    #: minimum number of respected same-direction POIs required (user: >= 1)
    min_orderflow_support: int = 1

    # ---------------------------------------------------------- quality selection
    #: "closest"  = PDF rule 4 literally (closest qualifying POI)
    #: "quality"  = rank by modelled bounce probability (trained on the bounce study),
    #:              softly penalised by distance, and drop POIs below min_quality
    selection_mode: str = "quality"
    quality_model_path: str = "models/quality_model.json"
    #: minimum modelled P(bounce >= 1 ATR before violation) to be eligible
    min_quality: float = 0.50
    #: v4 optional second stage: once price is within ``approach_near_atr`` ATR of the
    #: zone edge the *approach* model (trained on near-zone bars, price action of the
    #: approach) replaces the selection model.  Candidate-level it ranks better
    #: (OOS AUC 0.657 vs 0.645) but in the end-to-end walk-forward it added only
    #: borderline (P 0.50-0.55) picks and did not raise the bounce rate, so it is OFF
    #: by default.  Enable with --set approach_model_path=models/approach_model.json
    approach_model_path: str = ""
    approach_near_atr: float = 2.0
    #: ranking = -quality + distance_penalty * distance_atr
    distance_penalty: float = 0.02
    #: quality mode only: ignore POIs further than this (x ATR).  P(bounce) is
    #: conditional on being reached; beyond ~8 ATR fewer than half are reached
    #: within 300 bars, so they are not actionable for the current session.
    quality_max_distance_atr: float = 8.0
    #: order flow must be *relevant*: a respected POI within this many ATR of the
    #: candidate, or respected within orderflow_recent_bars
    orderflow_near_atr: float = 3.0
    orderflow_recent_bars: int = 100
    #: v5: compute classic indicator features (RSI, Stoch, MACD, ADX/DMI, Bollinger,
    #: Keltner, Donchian/fib, VWAP, relative volume/OBV/MFI, SuperTrend, EMA ribbon,
    #: Ichimoku, daily pivots, volatility regime) at POI creation, at selection and on
    #: the parent timeframe.  Needed by the v5 quality model; cheap (vectorised once).
    use_indicators: bool = True
    #: v6: level memory - rolling volume/time-at-price profile (LVN/HVN, POC, value area)
    #: and long-memory reaction counts of the zone's price area (lubot/levels.py).  Needed
    #: by the v6 quality model.  Incremental, ~0.5 ms per candidate.
    use_levels: bool = True
    levels_window_bars: int = 3000
    #: compute higher-timeframe confluence features (needs one helper engine per
    #: parent timeframe; costs ~30% more CPU in backtests, negligible live)
    htf_confluence: bool = True
    #: which higher timeframe backs each scanned timeframe
    htf_parent: Dict[str, str] = field(default_factory=lambda: {
        "M1": "M15", "M5": "M30", "M10": "H1", "M15": "H1", "M30": "H4", "H1": "H4", "H4": "D1"})

    # ---------------------------------------------------------- POI selection
    #: Rule 2: liquidity must rest between price and the POI (feeding into it)
    require_liquidity_between: bool = True
    #: Rule: prefer discount for buys / premium for sells (informational unless True)
    require_premium_discount: bool = False
    #: forget POIs older than this many bars
    max_poi_age_bars: int = 800
    #: ignore POIs further away than this (x ATR) from price (0 = no limit)
    max_distance_atr: float = 0.0
    #: POI types eligible for selection
    poi_types: Tuple[str, ...] = ("OB", "BB", "IMB", "HB", "UW")

    # ---------------------------------------------------------- backtest
    backtest_target_rr: Tuple[float, ...] = (1.0, 2.0, 3.0)
    backtest_reaction_atr: float = 1.0
    backtest_max_wait_bars: int = 300

    def tf_minutes(self, tf: str) -> int:
        return TIMEFRAME_MINUTES[tf]


DEFAULT_CONFIG = StrategyConfig()
