"""Point Of Interest detection (PDF: "Point Of Interest" lesson).

Five POI types, all detected incrementally on closed bars (no look-ahead):

OB  Orderblock       last opposite-colour candle(s) before the move.  The move
                     MUST take out liquidity ("this gives it purpose").
BB  Breaker Block    an orderblock that was NOT respected (price closed through
                     it); the market can return to it from the other side.
IMB Imbalance Fill   3-candle gap where candle #1 and #3 do not touch.  Candle
                     #1 is the POI; the fill is complete when price taps its
                     high (bullish) / low (bearish).
HB  Hidden Base      the LTF orderblock hidden inside the HTF impulse candle
                     (refined imbalance fill).
UW  Unmitigated Wick wick that has not yet been tapped; price can use the
                     open of the wick and its 50%.

Each POI also tracks its *mitigation* state: unmitigated -> tapped -> respected
(price reversed away by >= respect_move_atr) or violated (closed through).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np

from .config import StrategyConfig
from .data import Candles
from .structure import BSL, SSL, Liquidity, StructureTracker

BULL = "bullish"
BEAR = "bearish"

#: relative importance of the liquidity a move takes out (PDF: equal highs/lows and
#: weekly levels attract far more stops than a single swing)
LIQ_WEIGHT = {"SH": 1.0, "SL": 1.0, "PDH": 2.0, "PDL": 2.0, "ASIA_H": 2.0, "ASIA_L": 2.0,
              "EQH": 3.0, "EQL": 3.0, "PWH": 3.0, "PWL": 3.0}


@dataclass
class POI:
    id: int
    tf: str
    kind: str              # OB, BB, IMB, HB, UW
    direction: str         # bullish (buy from it) / bearish (sell from it)
    top: float
    bottom: float
    index: int             # candle index that defines the zone
    created_at: int        # bar index when the POI became known (confirmed)
    swept: List[str] = field(default_factory=list)   # liquidity taken by the move
    key_level: float = float("nan")                  # "Key Level" = opening of the POI
    # mitigation state
    tapped_at: Optional[int] = None
    respected_at: Optional[int] = None
    violated_at: Optional[int] = None
    _extreme_after_tap: float = float("nan")
    # for breakers
    parent_id: Optional[int] = None
    note: str = ""
    # quality features known at creation time (no look-ahead)
    features: Dict[str, float] = field(default_factory=dict)
    # bounce probability assigned at selection time (quality mode)
    quality: float = float("nan")
    # --- life-cycle statistics while the POI is still unmitigated (updated on
    #     every closed bar, so they are known at selection time) -------------
    #: furthest price travelled AWAY from the zone edge (price units)
    max_away: float = 0.0
    #: bar index at which that furthest point was made (start of the retrace)
    max_away_at: int = -1
    #: closest price came to the zone edge without tapping it (price units)
    min_approach: float = float("inf")
    #: number of bars that came within 0.5 ATR of the edge without tapping
    near_misses: int = 0

    # -------------------------------------------------------------- helpers
    @property
    def mid(self) -> float:
        return (self.top + self.bottom) / 2.0

    @property
    def size(self) -> float:
        return self.top - self.bottom

    @property
    def unmitigated(self) -> bool:
        return self.tapped_at is None

    @property
    def status(self) -> str:
        if self.violated_at is not None:
            return "violated"
        if self.respected_at is not None:
            return "respected"
        if self.tapped_at is not None:
            return "tapped"
        return "unmitigated"

    @property
    def alive(self) -> bool:
        return self.violated_at is None and self.tapped_at is None

    def to_dict(self, candles: Optional[Candles] = None) -> Dict:
        d = {
            "id": self.id,
            "tf": self.tf,
            "type": self.kind,
            "direction": self.direction,
            "top": round(self.top, 3),
            "bottom": round(self.bottom, 3),
            "mid": round(self.mid, 3),
            "key_level": None if np.isnan(self.key_level) else round(self.key_level, 3),
            "status": self.status,
            "swept_liquidity": self.swept,
            "bar_index": self.index,
            "note": self.note,
            "features": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in self.features.items()},
            "quality": None if np.isnan(self.quality) else round(self.quality, 3),
        }
        if candles is not None and 0 <= self.index < candles.n:
            d["time"] = str(candles.index[self.index])
        return d

    def __repr__(self) -> str:  # pragma: no cover
        return f"POI({self.tf} {self.kind} {self.direction} {self.bottom:.2f}-{self.top:.2f} #{self.index} {self.status})"


class POIDetector:
    """Incremental POI detector for one timeframe.

    ``update(i)`` must be called after ``StructureTracker.update(i)`` for the same bar.
    ``ltf`` (optional) is the M1 Candles used for the Hidden Base refinement.
    """

    def __init__(self, candles: Candles, structure: StructureTracker, cfg: StrategyConfig,
                 ltf: Optional[Candles] = None, indicators=None, levels=None):
        self.c = candles
        self.s = structure
        self.cfg = cfg
        self.ltf = ltf
        #: v5 - IndicatorSet of this timeframe (creation-time indicator features)
        self.ind = indicators
        #: v6 - LevelMemory of this timeframe (profile / reaction memory of the zone area at creation)
        self.levels = levels
        self.pois: List[POI] = []
        self._next_id = 1
        self._ltf_pos = 0

    # --------------------------------------------------------------- public
    def update(self, i: int) -> List[POI]:
        """Process closed bar i. Returns the POIs created on this bar."""
        created: List[POI] = []
        self._update_mitigation(i)
        created += self._detect_orderblocks(i)
        created += self._detect_imbalance(i)
        created += self._detect_wicks(i)
        # drop very old dead POIs to keep the list small
        if len(self.pois) > 3000:
            cutoff = i - max(self.cfg.max_poi_age_bars, self.cfg.orderflow_lookback_bars) * 2
            self.pois = [p for p in self.pois if p.created_at >= cutoff]
        return created

    def alive_pois(self, i: int) -> List[POI]:
        min_created = i - self.cfg.max_poi_age_bars
        return [p for p in self.pois if p.alive and p.created_at >= min_created and p.kind in self.cfg.poi_types]

    # ---------------------------------------------------------- internals
    def _add(self, poi: POI) -> POI:
        poi.id = self._next_id
        self._next_id += 1
        self.pois.append(poi)
        return poi

    def _swept_by_move(self, start: int, end: int, side: str) -> List[Liquidity]:
        return [ev.liquidity for ev in self.s.sweeps_in(start, end, side)]

    def _sweep_features(self, swept: List[Liquidity], extreme: float = float("nan"),
                        i: Optional[int] = None) -> Dict[str, float]:
        """How much / what quality of liquidity did the move take out.

        ``extreme`` = the low (bullish) / high (bearish) of the move that did the
        sweep: ``sweep_depth_atr`` is how far price ran *through* the deepest
        pool (a deep stop hunt vs. a bare tick through the level)."""
        q = 0.0
        kinds = set()
        depth = 0.0
        atr = self.c.atr[i] if i is not None and self.c.atr[i] > 0 else 1e-9
        for l in swept:
            kinds.add(l.kind)
            q = max(q, LIQ_WEIGHT.get(l.kind, 1.0))
            if np.isfinite(extreme):
                depth = max(depth, abs(l.price - extreme) / atr)
        return {
            "n_swept": float(len(swept)),
            "swept_quality": q,                      # 1 swing, 2 day/asia, 3 equal/week
            "swept_equal": float(any(k in ("EQH", "EQL") for k in kinds)),
            "swept_session": float(any(k in ("PDH", "PDL", "PWH", "PWL", "ASIA_H", "ASIA_L") for k in kinds)),
            "sweep_depth_atr": float(depth),
        }

    def _time_features(self, i: int) -> Dict[str, float]:
        """When (New York time) was the POI created - Asia-built zones behave
        differently from zones built in the New York session."""
        ny = self.s.ny_time(i)
        return {"created_ny_hour": float(ny.hour), "created_dow": float(ny.weekday())}

    def _impulse_features(self, start: int, end: int) -> Dict[str, float]:
        """Cleanliness of the impulse that left the zone (bars start..end):
        body share of the candle ranges and the share of bars in the move direction."""
        c = self.c
        bodies = rngs = 0.0
        for x in range(start, end + 1):
            bodies += abs(c.close[x] - c.open[x])
            rngs += max(c.high[x] - c.low[x], 1e-9)
        return {"impulse_body_frac": bodies / rngs if rngs > 0 else 0.0}

    def _base_features(self, top: float, bottom: float, i: int) -> Dict[str, float]:
        atr = self.c.atr[i] if self.c.atr[i] > 0 else 1e-9
        return {"zone_atr": (top - bottom) / atr, "atr": float(atr)}

    def _ind_features(self, blk_start: int, blk_end: int, i: int, bull: bool, top: float, bottom: float) -> Dict[str, float]:
        """v5 - indicator state at creation (empty dict when indicators are disabled).
        v6 - plus the level-memory snapshot of the zone area at creation (``cl_*``): was the
        base built in a low-volume node, at the value-area edge, at a level that reversed
        price before ..."""
        out: Dict[str, float] = {}
        if self.ind is not None:
            out.update(self.ind.creation_features(i, blk_start, blk_end, bull, top, bottom, self.s))
        if self.levels is not None:
            atr = self.c.atr[i] if self.c.atr[i] > 0 else 1e-9
            f = self.levels.features(i, bull, top, bottom, self.c.close[i], atr, i, prefix="cl_")
            out.update({k: f[k] for k in self.levels.CREATION_KEYS if k in f})
        return out

    def _pa_features(self, blk_start: int, blk_end: int, imp_start: int, i: int, bull: bool,
                     top: float, bottom: float) -> Dict[str, float]:
        """v4 - price action of the base and of the impulse that left it.

        block_rej_wick_atr   rejection wick of the block candle(s) pointing away from the
                             move (a bullish block with a long lower wick = buyers already
                             defended the level once)
        block_rej_wick_frac  the same wick as a share of the block candle range
        engulf_ratio         body of the first impulse candle / total block body (>= 1 = the
                             base was engulfed in one candle)
        impulse_max_body_atr largest single-candle body in the impulse (the displacement candle)
        impulse_close_pos    where the confirmation candle closed inside its range in the move
                             direction (1 = at the extreme, no rejection of the move)
        impulse_dir_frac     share of impulse candles that closed in the move direction
        pre_compression_atr  range of the 10 bars before the block (tight base vs. wide chop)
        pre_trend_bars       consecutive candles running INTO the block (exhaustion run)
        caused_bos           the impulse broke structure (BOS in the move direction)
        swing_in_zone        liquidity levels (swing lows / highs, incl. swept ones) sitting
                             inside the block range - the stop hunt happened *inside* the zone
        leg_atr              size of the whole leg from the block extreme to the confirmation close
        """
        c = self.c
        atr = c.atr[i] if c.atr[i] > 0 else 1e-9
        blk = range(blk_start, blk_end + 1)
        blk_hi = max(c.high[x] for x in blk)
        blk_lo = min(c.low[x] for x in blk)
        if bull:
            rej = max(c.body_bottom(x) - c.low[x] for x in blk)
        else:
            rej = max(c.high[x] - c.body_top(x) for x in blk)
        blk_rng = max(blk_hi - blk_lo, 1e-9)
        blk_body = sum(abs(c.close[x] - c.open[x]) for x in blk)
        first_imp = min(max(imp_start, blk_end + 1), i)
        engulf = abs(c.close[first_imp] - c.open[first_imp]) / max(blk_body, 1e-9)
        imp = range(min(imp_start, i), i + 1)
        max_body = max(abs(c.close[x] - c.open[x]) for x in imp)
        rng_i = max(c.high[i] - c.low[i], 1e-9)
        close_pos = (c.close[i] - c.low[i]) / rng_i if bull else (c.high[i] - c.close[i]) / rng_i
        dir_frac = sum(1 for x in imp if (c.is_bull(x) if bull else c.is_bear(x))) / max(len(imp), 1)
        pre0 = max(0, blk_start - 10)
        pre = range(pre0, blk_start) if blk_start > 0 else range(0, 1)
        pre_rng = (max(c.high[x] for x in pre) - min(c.low[x] for x in pre)) / atr
        # consecutive candles running into the block (counter to the coming move), block included
        run = 0
        x = blk_end
        while x >= 0 and run < 20 and (c.is_bear(x) if bull else c.is_bull(x)):
            run += 1
            x -= 1
        want = "up" if bull else "down"
        caused_bos = float(any(blk_end < b[0] <= i and b[1] == want for b in self.s.bos_history[-20:]))
        side = SSL if bull else BSL
        tol = 0.25 * atr
        swing_in = sum(1 for l in self.s.liquidity
                       if l.side == side and l.created_at <= i and blk_lo - tol <= l.price <= blk_hi + tol)
        leg = (c.close[i] - blk_lo) / atr if bull else (blk_hi - c.close[i]) / atr
        return {
            "block_rej_wick_atr": float(max(rej, 0.0) / atr),
            "block_rej_wick_frac": float(max(rej, 0.0) / blk_rng),
            "engulf_ratio": float(min(engulf, 10.0)),
            "impulse_max_body_atr": float(max_body / atr),
            "impulse_close_pos": float(min(max(close_pos, 0.0), 1.0)),
            "impulse_dir_frac": float(dir_frac),
            "pre_compression_atr": float(pre_rng),
            "pre_trend_bars": float(run),
            "caused_bos": caused_bos,
            "swing_in_zone": float(swing_in),
            "leg_atr": float(max(leg, 0.0)),
        }

    def _origin_features(self, start: int, end: int, i: int, bull: bool, lookback: int = 20,
                         prior: int = 10) -> Dict[str, float]:
        """Where does the zone sit inside the leg that created it?

        is_leg_origin   the block is the extreme of the last ``lookback`` bars
                        (a V-shaped reversal origin) vs. a mid-leg continuation block
        prior_move_atr  size of the move INTO the block over the ``prior`` bars
                        before it (how much price came down to build a bullish OB)
        """
        c = self.c
        atr = c.atr[i] if c.atr[i] > 0 else 1e-9
        lb0 = max(0, start - lookback)
        pr0 = max(0, start - prior)
        if bull:
            blk_lo = min(c.low[x] for x in range(start, end + 1))
            origin = blk_lo <= min(c.low[x] for x in range(lb0, end + 1))
            prior_move = (max(c.high[x] for x in range(pr0, start + 1)) - blk_lo) / atr if start > 0 else 0.0
        else:
            blk_hi = max(c.high[x] for x in range(start, end + 1))
            origin = blk_hi >= max(c.high[x] for x in range(lb0, end + 1))
            prior_move = (blk_hi - min(c.low[x] for x in range(pr0, start + 1))) / atr if start > 0 else 0.0
        return {"is_leg_origin": float(origin), "prior_move_atr": float(max(prior_move, 0.0))}

    # ------------------------------------------------------------ mitigation
    def _update_mitigation(self, i: int) -> None:
        c = self.c
        hi, lo, close = c.high[i], c.low[i], c.close[i]
        move = self.cfg.respect_move_atr * c.atr[i]
        for p in self.pois:
            if p.violated_at is not None or p.respected_at is not None or p.created_at > i:
                continue
            # Bars must be strictly after the candle that defines the zone
            if i <= p.index:
                continue
            if p.direction == BULL:
                if p.tapped_at is None:
                    if lo <= p.top:
                        p.tapped_at = i
                        p._extreme_after_tap = hi
                        if close < p.bottom:
                            self._violate(p, i)
                    else:
                        # still untouched: track the leg away from the zone and near-misses
                        if hi - p.top > p.max_away:
                            p.max_away, p.max_away_at = hi - p.top, i
                        approach = lo - p.top
                        p.min_approach = min(p.min_approach, approach)
                        if approach <= 0.5 * c.atr[i]:
                            p.near_misses += 1
                else:
                    if close < p.bottom:
                        self._violate(p, i)
                    else:
                        p._extreme_after_tap = max(p._extreme_after_tap, hi)
                        if p._extreme_after_tap - p.top >= move:
                            p.respected_at = i
            else:
                if p.tapped_at is None:
                    if hi >= p.bottom:
                        p.tapped_at = i
                        p._extreme_after_tap = lo
                        if close > p.top:
                            self._violate(p, i)
                    else:
                        if p.bottom - lo > p.max_away:
                            p.max_away, p.max_away_at = p.bottom - lo, i
                        approach = p.bottom - hi
                        p.min_approach = min(p.min_approach, approach)
                        if approach <= 0.5 * c.atr[i]:
                            p.near_misses += 1
                else:
                    if close > p.top:
                        self._violate(p, i)
                    else:
                        p._extreme_after_tap = min(p._extreme_after_tap, lo)
                        if p.bottom - p._extreme_after_tap >= move:
                            p.respected_at = i

    def _violate(self, p: POI, i: int) -> None:
        """An orderblock that was not respected becomes a Breaker Block on the other side."""
        p.violated_at = i
        c_close = self.c.close[i]
        if p.kind in ("OB", "HB") and p.violated_at is not None:
            bb = POI(
                id=0, tf=self.c.tf, kind="BB",
                direction=BEAR if p.direction == BULL else BULL,
                top=p.top, bottom=p.bottom, index=p.index, created_at=i,
                swept=list(p.swept), parent_id=p.id,
                note=f"breaker of {p.kind}#{p.id} (broken @bar {i})",
            )
            bb.key_level = bb.bottom if bb.direction == BULL else bb.top
            bb.features = {**p.features, **self._base_features(p.top, p.bottom, i),
                           # how the parent died: quick failure vs. a zone that held for a while
                           "parent_age_bars": float(i - p.created_at),
                           "parent_tap_to_break": float(i - p.tapped_at) if p.tapped_at is not None else 0.0,
                           "break_close_atr": abs(c_close - (p.bottom if p.direction == BULL else p.top)) / max(self.c.atr[i], 1e-9)}
            self._add(bb)

    # ------------------------------------------------------------ orderblock
    def _detect_orderblocks(self, i: int) -> List[POI]:
        """Bar i is the confirmation bar.  We look for a displacement leg that
        ends at i and started ``ob_displacement_bars`` bars ago at most."""
        c = self.c
        out: List[POI] = []
        n_disp = self.cfg.ob_displacement_bars
        if i < n_disp + 2:
            return out

        # ---- bullish OB: last down candle(s) before an up move that swept SSL
        # find the block: walk back from the first up candle of the impulse
        for k in range(1, n_disp + 1):
            first_up = i - k + 1          # first candle of the up move
            if first_up <= 1:
                break
            if not c.is_bull(first_up):
                continue
            # block = consecutive bear candles right before first_up
            j = first_up - 1
            if not c.is_bear(j):
                continue
            blk_end = j
            while j - 1 >= 0 and c.is_bear(j - 1):
                j -= 1
            blk_start = j
            top = max(c.body_top(x) for x in range(blk_start, blk_end + 1)) if self.cfg.ob_zone == "body" \
                else max(c.high[x] for x in range(blk_start, blk_end + 1))
            bottom = min(c.body_bottom(x) for x in range(blk_start, blk_end + 1)) if self.cfg.ob_zone == "body" \
                else min(c.low[x] for x in range(blk_start, blk_end + 1))
            # displacement: close of bar i above the block's full range
            if c.close[i] <= max(c.high[x] for x in range(blk_start, blk_end + 1)):
                continue
            # the move (block candle .. i) must take out sell side liquidity
            swept = self._swept_by_move(blk_start, i, SSL)
            swept_names = [l.describe() for l in swept]
            if self.cfg.ob_require_liquidity_sweep and not swept:
                continue
            if any(p.kind == "OB" and p.direction == BULL and p.index == blk_end for p in self.pois):
                break
            poi = POI(0, c.tf, "OB", BULL, top, bottom, blk_end, i, swept_names, key_level=c.open[blk_end])
            poi.note = f"bullish OB, {blk_end - blk_start + 1} candle(s); move swept {', '.join(swept_names)}"
            blk_hi = max(c.high[x] for x in range(blk_start, blk_end + 1))
            move_lo = min(c.low[x] for x in range(blk_start, i + 1))
            poi.features = {
                **self._base_features(top, bottom, i), **self._sweep_features(swept, move_lo, i),
                **self._origin_features(blk_start, blk_end, i, True), **self._time_features(i),
                **self._impulse_features(blk_end + 1, i),
                **self._pa_features(blk_start, blk_end, blk_end + 1, i, True, top, bottom),
                **self._ind_features(blk_start, blk_end, i, True, top, bottom),
                "displacement_atr": (c.close[i] - blk_hi) / max(c.atr[i], 1e-9),
                "impulse_bars": float(i - blk_end),
                "block_candles": float(blk_end - blk_start + 1),
                "has_imbalance": float(any(c.low[x] > blk_hi for x in range(blk_end + 1, i + 1))),
                "body_ratio": (top - bottom) / max(blk_hi - min(c.low[x] for x in range(blk_start, blk_end + 1)), 1e-9),
            }
            out.append(self._add(poi))
            out += self._hidden_base(poi, blk_end, i)
            break

        # ---- bearish OB: last up candle(s) before a down move that swept BSL
        for k in range(1, n_disp + 1):
            first_dn = i - k + 1
            if first_dn <= 1:
                break
            if not c.is_bear(first_dn):
                continue
            j = first_dn - 1
            if not c.is_bull(j):
                continue
            blk_end = j
            while j - 1 >= 0 and c.is_bull(j - 1):
                j -= 1
            blk_start = j
            top = max(c.body_top(x) for x in range(blk_start, blk_end + 1)) if self.cfg.ob_zone == "body" \
                else max(c.high[x] for x in range(blk_start, blk_end + 1))
            bottom = min(c.body_bottom(x) for x in range(blk_start, blk_end + 1)) if self.cfg.ob_zone == "body" \
                else min(c.low[x] for x in range(blk_start, blk_end + 1))
            if c.close[i] >= min(c.low[x] for x in range(blk_start, blk_end + 1)):
                continue
            swept = self._swept_by_move(blk_start, i, BSL)
            swept_names = [l.describe() for l in swept]
            if self.cfg.ob_require_liquidity_sweep and not swept:
                continue
            if any(p.kind == "OB" and p.direction == BEAR and p.index == blk_end for p in self.pois):
                break
            poi = POI(0, c.tf, "OB", BEAR, top, bottom, blk_end, i, swept_names, key_level=c.open[blk_end])
            poi.note = f"bearish OB, {blk_end - blk_start + 1} candle(s); move swept {', '.join(swept_names)}"
            blk_lo = min(c.low[x] for x in range(blk_start, blk_end + 1))
            move_hi = max(c.high[x] for x in range(blk_start, i + 1))
            poi.features = {
                **self._base_features(top, bottom, i), **self._sweep_features(swept, move_hi, i),
                **self._origin_features(blk_start, blk_end, i, False), **self._time_features(i),
                **self._impulse_features(blk_end + 1, i),
                **self._pa_features(blk_start, blk_end, blk_end + 1, i, False, top, bottom),
                **self._ind_features(blk_start, blk_end, i, False, top, bottom),
                "displacement_atr": (blk_lo - c.close[i]) / max(c.atr[i], 1e-9),
                "impulse_bars": float(i - blk_end),
                "block_candles": float(blk_end - blk_start + 1),
                "has_imbalance": float(any(c.high[x] < blk_lo for x in range(blk_end + 1, i + 1))),
                "body_ratio": (top - bottom) / max(max(c.high[x] for x in range(blk_start, blk_end + 1)) - blk_lo, 1e-9),
            }
            out.append(self._add(poi))
            out += self._hidden_base(poi, blk_end, i)
            break
        return out

    # ----------------------------------------------------------- hidden base
    def _hidden_base(self, ob: POI, blk_end: int, i: int) -> List[POI]:
        """Look inside the HTF impulse (bars blk_end+1 .. i) on M1 for the last
        opposite candle before the M1 displacement - the Hidden Base."""
        if self.ltf is None or self.c.tf == self.ltf.tf:
            return []
        c = self.c
        start_t = c.index[blk_end + 1] if blk_end + 1 < c.n else c.index[blk_end]
        end_t = c.index[i] + (c.index[1] - c.index[0]) if c.n > 1 else c.index[i]
        lo_idx = int(np.searchsorted(self.ltf.index.values, np.datetime64(start_t), side="left"))
        hi_idx = int(np.searchsorted(self.ltf.index.values, np.datetime64(end_t), side="left"))
        if hi_idx - lo_idx < 3:
            return []
        l = self.ltf
        best = None
        # scan the LTF leg for the largest displacement candle and take the
        # opposite candle(s) right before it
        if ob.direction == BULL:
            for k in range(lo_idx + 1, hi_idx):
                if l.is_bull(k) and l.is_bear(k - 1) and l.close[k] > l.high[k - 1]:
                    size = l.close[k] - l.open[k]
                    if best is None or size > best[0]:
                        best = (size, k - 1)
            if best is None:
                return []
            j = best[1]
            top, bottom = l.body_top(j), l.body_bottom(j)
            if not (ob.bottom - 0.5 * ob.size <= bottom and top <= ob.top + 2 * ob.size):
                pass  # still valid, just not inside the HTF block - it's inside the impulse
        else:
            for k in range(lo_idx + 1, hi_idx):
                if l.is_bear(k) and l.is_bull(k - 1) and l.close[k] < l.low[k - 1]:
                    size = l.open[k] - l.close[k]
                    if best is None or size > best[0]:
                        best = (size, k - 1)
            if best is None:
                return []
            j = best[1]
            top, bottom = l.body_top(j), l.body_bottom(j)
        if top - bottom <= 0:
            return []
        hb = POI(0, c.tf, "HB", ob.direction, top, bottom, i, i, list(ob.swept),
                 key_level=l.open[j], parent_id=ob.id,
                 note=f"hidden base (M1 OB @ {l.index[j]}) inside {c.tf} impulse of OB#{ob.id}")
        hb.features = {**ob.features, **self._base_features(top, bottom, i), "parent_zone_atr": ob.features.get("zone_atr", 0.0),
                       # where inside the HTF impulse does the hidden base sit (0 = at the OB, 1 = at the close)
                       "hb_pos_in_impulse": float(min(max(((top + bottom) / 2 - ob.mid) / max(abs(c.close[i] - ob.mid), 1e-9), 0.0), 1.5))}
        # the HB zone must be above (bull) / below (bear) the HTF OB and below
        # current close, otherwise it is already mitigated by the impulse itself
        if ob.direction == BULL and top >= c.close[i]:
            return []
        if ob.direction == BEAR and bottom <= c.close[i]:
            return []
        return [self._add(hb)]

    # ------------------------------------------------------------ imbalance
    def _detect_imbalance(self, i: int) -> List[POI]:
        """3-candle imbalance ending at bar i (candles i-2, i-1, i)."""
        c = self.c
        out: List[POI] = []
        if i < 2:
            return out
        min_gap = self.cfg.imbalance_min_size_atr * c.atr[i]
        c1, c3 = i - 2, i
        # bullish imbalance: low of candle 3 above high of candle 1
        if c.low[c3] > c.high[c1] and c.low[c3] - c.high[c1] >= min_gap:
            swept = [l.describe() for l in self._swept_by_move(c1, i, SSL)]
            # POI = candle #1, fill completes when price taps its HIGH.
            poi = POI(0, c.tf, "IMB", BULL, top=c.high[c1], bottom=c.low[c3], index=c1, created_at=i,
                      swept=swept, key_level=c.high[c1],
                      note=f"bullish imbalance gap {c.high[c1]:.2f}-{c.low[c3]:.2f}; candle#1 high is the fill level")
            # the zone we wait in is the gap; "filled" = tap of candle#1 high (=top)
            poi.top, poi.bottom = c.low[c3], c.high[c1]
            poi.features = {
                **self._base_features(poi.top, poi.bottom, i),
                **self._sweep_features(self._swept_by_move(c1, i, SSL), min(c.low[c1], c.low[i - 1]), i),
                **self._origin_features(c1, c1, i, True), **self._time_features(i),
                **self._impulse_features(c1, i),
                **self._pa_features(c1, c1, c1 + 1, i, True, poi.top, poi.bottom),
                **self._ind_features(c1, c1, i, True, poi.top, poi.bottom),
                "displacement_atr": abs(c.close[i - 1] - c.open[i - 1]) / max(c.atr[i], 1e-9),
                "impulse_bars": 2.0, "block_candles": 1.0, "has_imbalance": 1.0,
                "body_ratio": abs(c.close[i - 1] - c.open[i - 1]) / max(c.high[i - 1] - c.low[i - 1], 1e-9),
            }
            out.append(self._add(poi))
        # bearish imbalance: high of candle 3 below low of candle 1
        if c.high[c3] < c.low[c1] and c.low[c1] - c.high[c3] >= min_gap:
            swept = [l.describe() for l in self._swept_by_move(c1, i, BSL)]
            poi = POI(0, c.tf, "IMB", BEAR, top=c.low[c1], bottom=c.high[c3], index=c1, created_at=i,
                      swept=swept, key_level=c.low[c1],
                      note=f"bearish imbalance gap {c.high[c3]:.2f}-{c.low[c1]:.2f}; candle#1 low is the fill level")
            poi.features = {
                **self._base_features(poi.top, poi.bottom, i),
                **self._sweep_features(self._swept_by_move(c1, i, BSL), max(c.high[c1], c.high[i - 1]), i),
                **self._origin_features(c1, c1, i, False), **self._time_features(i),
                **self._impulse_features(c1, i),
                **self._pa_features(c1, c1, c1 + 1, i, False, poi.top, poi.bottom),
                **self._ind_features(c1, c1, i, False, poi.top, poi.bottom),
                "displacement_atr": abs(c.close[i - 1] - c.open[i - 1]) / max(c.atr[i], 1e-9),
                "impulse_bars": 2.0, "block_candles": 1.0, "has_imbalance": 1.0,
                "body_ratio": abs(c.close[i - 1] - c.open[i - 1]) / max(c.high[i - 1] - c.low[i - 1], 1e-9),
            }
            out.append(self._add(poi))
        return out

    # ---------------------------------------------------------------- wicks
    def _detect_wicks(self, i: int) -> List[POI]:
        """Unmitigated wick on candle i-1 (needs bar i to confirm the wick was
        not immediately traded back into)."""
        c = self.c
        out: List[POI] = []
        if i < 1:
            return out
        j = i - 1
        rng = c.high[j] - c.low[j]
        if rng <= 0:
            return out
        a = c.atr[j]
        lower_wick = c.body_bottom(j) - c.low[j]
        upper_wick = c.high[j] - c.body_top(j)
        # bullish UW: long lower wick, bar i did not trade back into it
        if lower_wick >= self.cfg.uw_min_wick_atr * a and lower_wick / rng >= self.cfg.uw_min_wick_ratio \
                and c.low[i] > c.body_bottom(j):
            swept = [l.describe() for l in self._swept_by_move(j, j, SSL)]
            wick_open = c.body_bottom(j)
            fifty = (wick_open + c.low[j]) / 2.0
            poi = POI(0, c.tf, "UW", BULL, top=wick_open, bottom=c.low[j], index=j, created_at=i,
                      swept=swept, key_level=fifty,
                      note=f"bullish unmitigated wick; open {wick_open:.2f}, 50% {fifty:.2f}")
            poi.features = {
                **self._base_features(wick_open, c.low[j], i), **self._sweep_features(self._swept_by_move(j, j, SSL), c.low[j], i),
                **self._origin_features(j, j, i, True), **self._time_features(i),
                **self._impulse_features(j, i),
                **self._pa_features(j, j, i, i, True, wick_open, c.low[j]),
                **self._ind_features(j, j, i, True, wick_open, c.low[j]),
                "displacement_atr": (c.close[i] - c.low[j]) / max(c.atr[i], 1e-9),
                "impulse_bars": 1.0, "block_candles": 1.0, "has_imbalance": 0.0,
                "body_ratio": lower_wick / rng, "wick_candle_agrees": float(c.is_bull(j)),
            }
            out.append(self._add(poi))
        if upper_wick >= self.cfg.uw_min_wick_atr * a and upper_wick / rng >= self.cfg.uw_min_wick_ratio \
                and c.high[i] < c.body_top(j):
            swept = [l.describe() for l in self._swept_by_move(j, j, BSL)]
            wick_open = c.body_top(j)
            fifty = (wick_open + c.high[j]) / 2.0
            poi = POI(0, c.tf, "UW", BEAR, top=c.high[j], bottom=wick_open, index=j, created_at=i,
                      swept=swept, key_level=fifty,
                      note=f"bearish unmitigated wick; open {wick_open:.2f}, 50% {fifty:.2f}")
            poi.features = {
                **self._base_features(c.high[j], wick_open, i), **self._sweep_features(self._swept_by_move(j, j, BSL), c.high[j], i),
                **self._origin_features(j, j, i, False), **self._time_features(i),
                **self._impulse_features(j, i),
                **self._pa_features(j, j, i, i, False, c.high[j], wick_open),
                **self._ind_features(j, j, i, False, c.high[j], wick_open),
                "displacement_atr": (c.high[j] - c.close[i]) / max(c.atr[i], 1e-9),
                "impulse_bars": 1.0, "block_candles": 1.0, "has_imbalance": 0.0,
                "body_ratio": upper_wick / rng, "wick_candle_agrees": float(c.is_bear(j)),
            }
            out.append(self._add(poi))
        return out
