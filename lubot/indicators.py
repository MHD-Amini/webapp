"""Technical indicators used as *context* for the POI quality model (v5).

Everything here is computed once per timeframe on the closed-bar arrays and is
strictly backward looking (rolling / exponential windows ending at the bar).
At bar ``i`` only values with index ``<= i`` are read, so nothing leaks.

Three feature groups are produced:

* ``creation_features``   indicator state when the POI was built (was the block
                          formed at an RSI extreme, outside the Bollinger band, on a
                          volume climax, against a strong ADX trend ...)
* ``selection_features``  indicator state of the *approach* when the bot ranks the
                          candidate (momentum into the zone, where the zone sits vs.
                          Bollinger / Keltner / VWAP / pivots / moving averages,
                          divergences, volatility regime, trend strength ...)
* ``htf_features``        the same idea on the parent timeframe (trend filter)

Volume: the MT5 export carries ``<VOL>`` for the older part and ``<TICKVOL>`` for the
newer part with a ~17x different scale.  Only *relative* volume (ratio to a rolling
median) is used so the scale break cannot leak the calendar date into the model.

All values are oriented to the POI direction where it matters ("aligned" = positive
when the indicator favours a bounce from that zone):  for a bullish zone an
oversold RSI, a bullish RSI divergence, price below the lower Bollinger band,
-DI > +DI exhausting, MACD histogram turning up ... all become *positive* numbers.
"""
from __future__ import annotations

from typing import Dict, Optional

import numpy as np
import pandas as pd

from .data import Candles


def _ewm(x: np.ndarray, span: Optional[int] = None, alpha: Optional[float] = None) -> np.ndarray:
    s = pd.Series(x)
    return (s.ewm(span=span, adjust=False) if alpha is None else s.ewm(alpha=alpha, adjust=False)).mean().to_numpy()


def _roll(x: np.ndarray, n: int, how: str) -> np.ndarray:
    r = pd.Series(x).rolling(n, min_periods=1)
    return getattr(r, how)().to_numpy()


def _safe_div(a: np.ndarray, b: np.ndarray, fill: float = 0.0) -> np.ndarray:
    out = np.full_like(a, fill, dtype=float)
    ok = np.abs(b) > 1e-12
    out[ok] = a[ok] / b[ok]
    return out


def _wilder_rsi(close: np.ndarray, n: int = 14) -> np.ndarray:
    d = np.diff(close, prepend=close[0])
    up = np.where(d > 0, d, 0.0)
    dn = np.where(d < 0, -d, 0.0)
    au = _ewm(up, alpha=1.0 / n)
    ad = _ewm(dn, alpha=1.0 / n)
    rs = _safe_div(au, ad, fill=np.inf)
    rsi = 100.0 - 100.0 / (1.0 + rs)
    rsi[~np.isfinite(rsi)] = 100.0
    rsi[:n] = 50.0
    return rsi


class IndicatorSet:
    """All indicator series for one ``Candles`` object (one timeframe)."""

    #: feature names emitted by selection_features (kept here so quality.py can import them)
    SELECTION = [
        "ind_rsi_aligned", "ind_rsi_slope_aligned", "ind_rsi_div_regular", "ind_rsi_div_hidden",
        "ind_stoch_k_aligned", "ind_stoch_d_aligned", "ind_stoch_cross_aligned",
        "ind_macd_hist_aligned", "ind_macd_hist_slope_aligned", "ind_macd_line_aligned",
        "ind_adx", "ind_adx_slope", "ind_di_aligned", "ind_di_spread",
        "ind_bb_pctb_aligned", "ind_bb_width_atr", "ind_bb_squeeze", "ind_zone_vs_bb_atr", "ind_zone_beyond_bb",
        "ind_kc_pos_aligned", "ind_zone_vs_kc_atr", "ind_zone_beyond_kc",
        "ind_donch20_pos_aligned", "ind_donch55_pos_aligned", "ind_zone_fib20", "ind_zone_fib55", "ind_zone_in_ote",
        "ind_cci_aligned", "ind_willr_aligned", "ind_roc10_aligned",
        "ind_vwap_dist_aligned", "ind_zone_vs_vwap_atr", "ind_zone_at_vwap_band", "ind_vwap_slope_aligned",
        "ind_relvol", "ind_relvol5", "ind_vol_trend", "ind_obv_slope_aligned", "ind_vol_climax",
        "ind_supertrend_aligned", "ind_supertrend_dist_atr", "ind_supertrend_age",
        "ind_ema_ribbon_aligned", "ind_price_vs_ema21_aligned", "ind_zone_vs_ema50_atr", "ind_zone_vs_ema200_atr",
        "ind_zone_at_ma", "ind_kijun_aligned", "ind_cloud_aligned", "ind_zone_in_cloud",
        "ind_pivot_dist_atr", "ind_pivot_kind", "ind_zone_at_pivot",
        "ind_atr_pctile", "ind_chop", "ind_eff_ratio", "ind_mfi_aligned", "ind_ult_osc_aligned",
        "ind_vol_ratio_hl", "ind_bars_since_rsi_extreme", "ind_rsi_extreme_recent",
    ]
    #: feature names emitted by creation_features
    CREATION = [
        "cr_rsi_extreme", "cr_rsi_div", "cr_bb_outside", "cr_bb_width_atr", "cr_kc_outside",
        "cr_macd_hist_aligned", "cr_adx", "cr_di_against", "cr_stoch_extreme",
        "cr_vol_impulse_rel", "cr_vol_block_rel", "cr_vol_climax", "cr_obv_confirm",
        "cr_supertrend_flip", "cr_ema_ribbon_aligned", "cr_zone_vs_ema50_atr", "cr_zone_vs_vwap_atr",
        "cr_pivot_dist_atr", "cr_atr_pctile", "cr_chop", "cr_cci_extreme", "cr_zone_fib55",
    ]
    #: feature names emitted by htf_features
    HTF = [
        "htf_rsi_aligned", "htf_adx", "htf_di_aligned", "htf_macd_hist_aligned", "htf_supertrend_aligned",
        "htf_ema_ribbon_aligned", "htf_bb_pctb_aligned", "htf_zone_vs_ema50_atr", "htf_atr_pctile",
        "htf_stoch_k_aligned", "htf_zone_beyond_bb",
    ]

    def __init__(self, c: Candles, ny_offset_hours: float = 7.0):
        self.c = c
        n = c.n
        o, h, l, cl = c.open, c.high, c.low, c.close
        v = np.nan_to_num(c.volume.astype(float))
        atr = np.where(c.atr > 0, c.atr, 1e-9)
        self.atr = atr
        tp = (h + l + cl) / 3.0

        # ---------------------------------------------------------- RSI / Stoch
        self.rsi = _wilder_rsi(cl, 14)
        self.rsi_slope = self.rsi - np.roll(self.rsi, 3)
        self.rsi_slope[:3] = 0.0
        ll14, hh14 = _roll(l, 14, "min"), _roll(h, 14, "max")
        k_raw = 100.0 * _safe_div(cl - ll14, hh14 - ll14, fill=0.5 * 100)
        self.stoch_k = _roll(k_raw, 3, "mean")
        self.stoch_d = _roll(self.stoch_k, 3, "mean")
        self.willr = -100.0 * _safe_div(hh14 - cl, hh14 - ll14, fill=0.5 * 100)

        # ---------------------------------------------------------------- MACD
        ema12, ema26 = _ewm(cl, span=12), _ewm(cl, span=26)
        self.macd = ema12 - ema26
        self.macd_sig = _ewm(self.macd, span=9)
        self.macd_hist = self.macd - self.macd_sig
        self.macd_hist_slope = self.macd_hist - np.roll(self.macd_hist, 2)
        self.macd_hist_slope[:2] = 0.0

        # ------------------------------------------------------------ ADX / DMI
        up_move = h - np.roll(h, 1)
        dn_move = np.roll(l, 1) - l
        up_move[0] = dn_move[0] = 0.0
        plus_dm = np.where((up_move > dn_move) & (up_move > 0), up_move, 0.0)
        minus_dm = np.where((dn_move > up_move) & (dn_move > 0), dn_move, 0.0)
        prev_c = np.roll(cl, 1)
        prev_c[0] = cl[0]
        tr = np.maximum(h - l, np.maximum(np.abs(h - prev_c), np.abs(l - prev_c)))
        atr_w = _ewm(tr, alpha=1 / 14)
        self.plus_di = 100.0 * _safe_div(_ewm(plus_dm, alpha=1 / 14), atr_w)
        self.minus_di = 100.0 * _safe_div(_ewm(minus_dm, alpha=1 / 14), atr_w)
        dx = 100.0 * _safe_div(np.abs(self.plus_di - self.minus_di), self.plus_di + self.minus_di)
        self.adx = _ewm(dx, alpha=1 / 14)
        self.adx_slope = self.adx - np.roll(self.adx, 3)
        self.adx_slope[:3] = 0.0

        # ------------------------------------------------------------ Bollinger
        self.sma20 = _roll(cl, 20, "mean")
        sd20 = pd.Series(cl).rolling(20, min_periods=2).std(ddof=0).fillna(0.0).to_numpy()
        self.bb_up = self.sma20 + 2.0 * sd20
        self.bb_lo = self.sma20 - 2.0 * sd20
        self.bb_width = self.bb_up - self.bb_lo
        self.bb_pctb = _safe_div(cl - self.bb_lo, self.bb_width, fill=0.5)
        # squeeze = bandwidth in the lowest 20% of its last 100 values
        bw_rank = pd.Series(self.bb_width).rolling(100, min_periods=10).rank(pct=True).fillna(0.5).to_numpy()
        self.bb_squeeze = (bw_rank <= 0.2).astype(float)

        # ------------------------------------------------------------- Keltner
        self.ema20 = _ewm(cl, span=20)
        self.kc_up = self.ema20 + 1.5 * atr
        self.kc_lo = self.ema20 - 1.5 * atr
        self.kc_pos = _safe_div(cl - self.kc_lo, self.kc_up - self.kc_lo, fill=0.5)

        # ------------------------------------------------------------ Donchian
        self.hh20, self.ll20 = _roll(h, 20, "max"), _roll(l, 20, "min")
        self.hh55, self.ll55 = _roll(h, 55, "max"), _roll(l, 55, "min")

        # --------------------------------------------------------- CCI / ROC
        sma_tp = _roll(tp, 20, "mean")
        # mean absolute deviation about the rolling mean (fast approximation, identical
        # in training and live so the model sees the same definition everywhere)
        mad = np.maximum(_roll(np.abs(tp - sma_tp), 20, "mean"), 1e-9)
        self.cci = np.clip(_safe_div(tp - sma_tp, 0.015 * mad), -500.0, 500.0)
        self.roc10 = _safe_div(cl - np.roll(cl, 10), np.roll(cl, 10)) * 100.0
        self.roc10[:10] = 0.0

        # ---------------------------------------------------------------- VWAP
        day = c.index.normalize().values
        vol_pos = np.where(v > 0, v, 1.0)          # bars without volume weigh 1 (typical price)
        pv = tp * vol_pos
        ppv = tp * tp * vol_pos
        cum_v = pd.Series(vol_pos).groupby(day).cumsum().to_numpy()
        cum_pv = pd.Series(pv).groupby(day).cumsum().to_numpy()
        cum_ppv = pd.Series(ppv).groupby(day).cumsum().to_numpy()
        self.vwap = _safe_div(cum_pv, cum_v, fill=np.nan)
        var = _safe_div(cum_ppv, cum_v) - self.vwap ** 2
        self.vwap_sd = np.sqrt(np.maximum(var, 0.0))
        self.vwap = np.where(np.isfinite(self.vwap), self.vwap, cl)
        self.vwap_slope = self.vwap - np.roll(self.vwap, 5)
        self.vwap_slope[:5] = 0.0

        # -------------------------------------------------------------- volume
        med50 = _roll(v, 50, "median")
        self.relvol = _safe_div(v, med50, fill=1.0)
        self.relvol5 = _roll(self.relvol, 5, "mean")
        self.vol_trend = _safe_div(_roll(v, 5, "mean"), _roll(v, 20, "mean"), fill=1.0)
        self.vol_climax = (self.relvol >= 2.5).astype(float)
        sign = np.sign(np.diff(cl, prepend=cl[0]))
        obv = np.cumsum(sign * self.relvol)          # relative OBV (scale free)
        self.obv_slope = obv - np.roll(obv, 10)
        self.obv_slope[:10] = 0.0
        # money flow index (14) on relative volume
        rmf = tp * self.relvol
        dtp = np.diff(tp, prepend=tp[0])
        pos_mf = _roll(np.where(dtp > 0, rmf, 0.0), 14, "sum")
        neg_mf = _roll(np.where(dtp < 0, rmf, 0.0), 14, "sum")
        self.mfi = 100.0 - 100.0 / (1.0 + _safe_div(pos_mf, neg_mf, fill=np.inf))
        self.mfi[~np.isfinite(self.mfi)] = 100.0
        # ultimate oscillator (7, 14, 28)
        bp = cl - np.minimum(l, prev_c)
        tr_u = np.maximum(h, prev_c) - np.minimum(l, prev_c)
        a7 = _safe_div(_roll(bp, 7, "sum"), _roll(tr_u, 7, "sum"), 0.5)
        a14 = _safe_div(_roll(bp, 14, "sum"), _roll(tr_u, 14, "sum"), 0.5)
        a28 = _safe_div(_roll(bp, 28, "sum"), _roll(tr_u, 28, "sum"), 0.5)
        self.ult = 100.0 * (4 * a7 + 2 * a14 + a28) / 7.0

        # ---------------------------------------------------------- SuperTrend
        hl2 = (h + l) / 2.0
        up_b = hl2 + 3.0 * atr
        lo_b = hl2 - 3.0 * atr
        st_dir = np.ones(n, dtype=float)          # +1 bullish, -1 bearish
        st_line = np.empty(n, dtype=float)
        fu, fl = up_b.copy(), lo_b.copy()
        for k in range(1, n):
            fl[k] = lo_b[k] if (lo_b[k] > fl[k - 1] or cl[k - 1] < fl[k - 1]) else fl[k - 1]
            fu[k] = up_b[k] if (up_b[k] < fu[k - 1] or cl[k - 1] > fu[k - 1]) else fu[k - 1]
            if st_dir[k - 1] > 0:
                st_dir[k] = -1.0 if cl[k] < fl[k] else 1.0
            else:
                st_dir[k] = 1.0 if cl[k] > fu[k] else -1.0
        st_line = np.where(st_dir > 0, fl, fu)
        self.st_dir, self.st_line = st_dir, st_line
        flips = np.flatnonzero(np.diff(st_dir) != 0) + 1
        age = np.zeros(n)
        last = 0
        fi = 0
        for k in range(n):
            while fi < len(flips) and flips[fi] <= k:
                last = flips[fi]
                fi += 1
            age[k] = k - last
        self.st_age = age

        # ---------------------------------------------------------- EMA ribbon
        self.ema8 = _ewm(cl, span=8)
        self.ema21 = _ewm(cl, span=21)
        self.ema50 = _ewm(cl, span=50)
        self.ema200 = _ewm(cl, span=200)
        ribbon = (np.sign(self.ema8 - self.ema21) + np.sign(self.ema21 - self.ema50) + np.sign(self.ema50 - self.ema200)) / 3.0
        self.ribbon = ribbon                      # +1 fully bullish stack, -1 fully bearish

        # ------------------------------------------------------------ Ichimoku
        self.tenkan = (_roll(h, 9, "max") + _roll(l, 9, "min")) / 2.0
        self.kijun = (_roll(h, 26, "max") + _roll(l, 26, "min")) / 2.0
        span_a = (self.tenkan + self.kijun) / 2.0
        span_b = (_roll(h, 52, "max") + _roll(l, 52, "min")) / 2.0
        # cloud as seen at bar i = spans computed 26 bars ago (plotted forward)
        self.cloud_top = np.maximum(np.roll(span_a, 26), np.roll(span_b, 26))
        self.cloud_bot = np.minimum(np.roll(span_a, 26), np.roll(span_b, 26))
        self.cloud_top[:26] = cl[:26]
        self.cloud_bot[:26] = cl[:26]

        # -------------------------------------------------- daily pivot points
        df = pd.DataFrame({"h": h, "l": l, "c": cl}, index=c.index)
        daily = df.groupby(df.index.normalize()).agg(h=("h", "max"), l=("l", "min"), c=("c", "last")).shift(1)
        P = (daily.h + daily.l + daily.c) / 3.0
        piv = pd.DataFrame({"P": P, "R1": 2 * P - daily.l, "S1": 2 * P - daily.h,
                            "R2": P + (daily.h - daily.l), "S2": P - (daily.h - daily.l),
                            "R3": daily.h + 2 * (P - daily.l), "S3": daily.l - 2 * (daily.h - P)})
        piv = piv.reindex(pd.DatetimeIndex(day)).to_numpy()
        self.pivots = np.where(np.isfinite(piv), piv, np.nan)  # (n, 7)
        self.pivot_names = ["P", "R1", "S1", "R2", "S2", "R3", "S3"]

        # ------------------------------------------------- regime / choppiness
        self.atr_pctile = pd.Series(atr).rolling(500, min_periods=20).rank(pct=True).fillna(0.5).to_numpy()
        sum_tr14 = _roll(tr, 14, "sum")
        rng14 = _roll(h, 14, "max") - _roll(l, 14, "min")
        self.chop = 100.0 * _safe_div(np.log10(np.maximum(_safe_div(sum_tr14, rng14, 1.0), 1e-9)), np.full(n, np.log10(14)))
        self.chop = np.clip(self.chop, 0, 100)
        net10 = np.abs(cl - np.roll(cl, 10))
        path10 = _roll(np.abs(np.diff(cl, prepend=cl[0])), 10, "sum")
        self.eff_ratio = _safe_div(net10, path10)
        self.eff_ratio[:10] = 0.0
        # bars since the RSI was last at an extreme (<=30 or >=70), split by side
        self.last_os = self._last_index_where(self.rsi <= 30.0)
        self.last_ob = self._last_index_where(self.rsi >= 70.0)
        self.vol_ratio_hl = _safe_div(h - l, _roll(h - l, 20, "mean"), 1.0)

    @staticmethod
    def _last_index_where(mask: np.ndarray) -> np.ndarray:
        idx = np.where(mask, np.arange(len(mask)), -1)
        return np.maximum.accumulate(idx)

    # ------------------------------------------------------------------ utils
    @staticmethod
    def _al(x: float, bull: bool) -> float:
        """Orient a signed quantity to the zone direction (positive = favours the bounce)."""
        return float(x if bull else -x)

    def _nearest_pivot(self, i: int, level: float):
        row = self.pivots[i]
        if not np.isfinite(row).any():
            return np.nan, -1
        d = np.abs(row - level)
        d = np.where(np.isfinite(d), d, np.inf)
        j = int(np.argmin(d))
        return float(d[j]), j

    def _rsi_divergence(self, i: int, bull: bool, structure, lookback: int = 60):
        """Regular / hidden RSI divergence between the last two swing points on the
        approach side.  Bullish zone: compare the last two swing LOWS (price lower low
        with RSI higher low = regular bullish divergence -> exhaustion of the sell-off;
        price higher low with RSI lower low = hidden bullish divergence -> trend
        continuation up).  Returns (regular, hidden) as 0/1 flags."""
        side = "SSL" if bull else "BSL"
        pts = [q for q in structure.liquidity if q.side == side and q.created_at <= i and i - q.index <= lookback]
        if len(pts) < 2:
            return 0.0, 0.0
        pts.sort(key=lambda q: q.index)
        a, b = pts[-2], pts[-1]
        if a.index >= b.index or b.index > i:
            return 0.0, 0.0
        pa, pb = a.price, b.price
        ra, rb = self.rsi[a.index], self.rsi[b.index]
        if bull:
            regular = float(pb < pa and rb > ra + 1.0)
            hidden = float(pb > pa and rb < ra - 1.0)
        else:
            regular = float(pb > pa and rb < ra - 1.0)
            hidden = float(pb < pa and rb > ra + 1.0)
        return regular, hidden

    # --------------------------------------------------------------- features
    def selection_features(self, i: int, bull: bool, top: float, bottom: float, price: float,
                           structure=None) -> Dict[str, float]:
        c = self.c
        atr = float(self.atr[i])
        edge = top if bull else bottom          # entry edge of the zone (closest to price)
        far = bottom if bull else top
        sgn = 1.0 if bull else -1.0
        out: Dict[str, float] = {}
        # --- momentum oscillators, oriented: oversold for a bullish zone -> positive
        out["ind_rsi_aligned"] = float((50.0 - self.rsi[i]) * sgn)
        out["ind_rsi_slope_aligned"] = self._al(self.rsi_slope[i], bull)       # RSI already turning up = +
        reg, hid = self._rsi_divergence(i, bull, structure) if structure is not None else (0.0, 0.0)
        out["ind_rsi_div_regular"], out["ind_rsi_div_hidden"] = reg, hid
        out["ind_stoch_k_aligned"] = float((50.0 - self.stoch_k[i]) * sgn)
        out["ind_stoch_d_aligned"] = float((50.0 - self.stoch_d[i]) * sgn)
        out["ind_stoch_cross_aligned"] = self._al(self.stoch_k[i] - self.stoch_d[i], bull)
        out["ind_macd_hist_aligned"] = self._al(self.macd_hist[i] / atr, bull)
        out["ind_macd_hist_slope_aligned"] = self._al(self.macd_hist_slope[i] / atr, bull)
        out["ind_macd_line_aligned"] = self._al(self.macd[i] / atr, bull)
        # --- trend strength: a strong trend AGAINST the zone runs through it
        out["ind_adx"] = float(self.adx[i])
        out["ind_adx_slope"] = float(self.adx_slope[i])
        out["ind_di_aligned"] = self._al(self.plus_di[i] - self.minus_di[i], bull)
        out["ind_di_spread"] = float(abs(self.plus_di[i] - self.minus_di[i]))
        # --- Bollinger: price stretched beyond the band towards the zone = mean reversion
        out["ind_bb_pctb_aligned"] = float((0.5 - self.bb_pctb[i]) * sgn)
        out["ind_bb_width_atr"] = float(self.bb_width[i] / atr)
        out["ind_bb_squeeze"] = float(self.bb_squeeze[i])
        band = self.bb_lo[i] if bull else self.bb_up[i]
        out["ind_zone_vs_bb_atr"] = float((band - edge) * sgn / atr)          # + = zone beyond the band
        out["ind_zone_beyond_bb"] = float(out["ind_zone_vs_bb_atr"] > 0)
        kband = self.kc_lo[i] if bull else self.kc_up[i]
        out["ind_kc_pos_aligned"] = float((0.5 - self.kc_pos[i]) * sgn)
        out["ind_zone_vs_kc_atr"] = float((kband - edge) * sgn / atr)
        out["ind_zone_beyond_kc"] = float(out["ind_zone_vs_kc_atr"] > 0)
        # --- Donchian / fib position of the ZONE inside the recent range
        r20 = self.hh20[i] - self.ll20[i]
        r55 = self.hh55[i] - self.ll55[i]
        pos20 = (price - self.ll20[i]) / r20 if r20 > 0 else 0.5
        pos55 = (price - self.ll55[i]) / r55 if r55 > 0 else 0.5
        out["ind_donch20_pos_aligned"] = float((0.5 - pos20) * sgn)
        out["ind_donch55_pos_aligned"] = float((0.5 - pos55) * sgn)
        # fib retracement depth of the zone edge inside the 20/55 range, measured from the
        # extreme on the zone's side (0 = zone at the range extreme, 1 = at the opposite extreme)
        z20 = (edge - self.ll20[i]) / r20 if r20 > 0 else 0.5
        z55 = (edge - self.ll55[i]) / r55 if r55 > 0 else 0.5
        f20 = z20 if bull else 1.0 - z20
        f55 = z55 if bull else 1.0 - z55
        out["ind_zone_fib20"] = float(min(max(f20, -0.5), 1.5))
        out["ind_zone_fib55"] = float(min(max(f55, -0.5), 1.5))
        # optimal trade entry: the zone sits in the 61.8-78.6 % retracement of the 55-bar leg
        out["ind_zone_in_ote"] = float(0.214 <= f55 <= 0.382)
        out["ind_cci_aligned"] = float(-self.cci[i] * sgn / 100.0)
        out["ind_willr_aligned"] = float((-50.0 - self.willr[i]) * sgn)     # willr in -100..0 ; -100 = oversold
        out["ind_roc10_aligned"] = float(-self.roc10[i] * sgn)
        # --- VWAP (session anchored)
        out["ind_vwap_dist_aligned"] = float((self.vwap[i] - price) * sgn / atr)   # + price below vwap for a bull zone
        out["ind_zone_vs_vwap_atr"] = float((self.vwap[i] - edge) * sgn / atr)
        sd = self.vwap_sd[i]
        band1 = self.vwap[i] - sd if bull else self.vwap[i] + sd
        band2 = self.vwap[i] - 2 * sd if bull else self.vwap[i] + 2 * sd
        out["ind_zone_at_vwap_band"] = float(min(abs(edge - band1), abs(edge - band2), abs(edge - self.vwap[i])) <= 0.25 * atr)
        out["ind_vwap_slope_aligned"] = self._al(self.vwap_slope[i] / atr, bull)
        # --- volume (relative only)
        out["ind_relvol"] = float(self.relvol[i])
        out["ind_relvol5"] = float(self.relvol5[i])
        out["ind_vol_trend"] = float(self.vol_trend[i])
        out["ind_obv_slope_aligned"] = self._al(self.obv_slope[i], bull)
        out["ind_vol_climax"] = float(self.vol_climax[i])
        # --- SuperTrend
        out["ind_supertrend_aligned"] = self._al(self.st_dir[i], bull)
        out["ind_supertrend_dist_atr"] = float((self.st_line[i] - edge) * sgn / atr)   # + = zone below the ST line (bull)
        out["ind_supertrend_age"] = float(self.st_age[i])
        # --- moving averages: zone at a MA = confluence
        out["ind_ema_ribbon_aligned"] = self._al(self.ribbon[i], bull)
        out["ind_price_vs_ema21_aligned"] = float((price - self.ema21[i]) * sgn / atr)
        d50 = (edge - self.ema50[i]) / atr
        d200 = (edge - self.ema200[i]) / atr
        out["ind_zone_vs_ema50_atr"] = float(max(min(d50, 20.0), -20.0))
        out["ind_zone_vs_ema200_atr"] = float(max(min(d200, 20.0), -20.0))
        ma_hits = sum(1 for m in (self.ema21[i], self.ema50[i], self.ema200[i], self.sma20[i], self.kijun[i])
                      if bottom - 0.25 * atr <= m <= top + 0.25 * atr)
        out["ind_zone_at_ma"] = float(ma_hits)
        out["ind_kijun_aligned"] = float((price - self.kijun[i]) * sgn / atr)
        ct, cb = self.cloud_top[i], self.cloud_bot[i]
        out["ind_cloud_aligned"] = float(1.0 if (price > ct if bull else price < cb) else (-1.0 if (price < cb if bull else price > ct) else 0.0))
        out["ind_zone_in_cloud"] = float(bottom <= ct and top >= cb)
        # --- daily pivots
        pdist, pj = self._nearest_pivot(i, edge)
        out["ind_pivot_dist_atr"] = float(min(pdist / atr, 20.0)) if np.isfinite(pdist) else 20.0
        out["ind_pivot_kind"] = float(pj)
        out["ind_zone_at_pivot"] = float(np.isfinite(pdist) and pdist <= 0.25 * atr)
        # --- regime
        out["ind_atr_pctile"] = float(self.atr_pctile[i])
        out["ind_chop"] = float(self.chop[i])
        out["ind_eff_ratio"] = float(self.eff_ratio[i])
        out["ind_mfi_aligned"] = float((50.0 - self.mfi[i]) * sgn)
        out["ind_ult_osc_aligned"] = float((50.0 - self.ult[i]) * sgn)
        out["ind_vol_ratio_hl"] = float(self.vol_ratio_hl[i])
        last_ext = self.last_os[i] if bull else self.last_ob[i]
        out["ind_bars_since_rsi_extreme"] = float(i - last_ext) if last_ext >= 0 else 999.0
        out["ind_rsi_extreme_recent"] = float(last_ext >= 0 and i - last_ext <= 10)
        return out

    def creation_features(self, i: int, blk_start: int, blk_end: int, bull: bool, top: float, bottom: float,
                          structure=None) -> Dict[str, float]:
        """Indicator state when the zone was built: bars blk_start..blk_end = the block,
        blk_end+1..i = the impulse, i = confirmation bar."""
        atr = float(self.atr[i])
        sgn = 1.0 if bull else -1.0
        out: Dict[str, float] = {}
        k = blk_end
        # RSI at the block: a bullish block built with RSI oversold = reversal from an extreme
        out["cr_rsi_extreme"] = float((50.0 - self.rsi[k]) * sgn)
        reg, _ = self._rsi_divergence(k, bull, structure) if structure is not None else (0.0, 0.0)
        out["cr_rsi_div"] = reg
        ext = min(self.c.low[x] for x in range(blk_start, blk_end + 1)) if bull else max(self.c.high[x] for x in range(blk_start, blk_end + 1))
        band = self.bb_lo[k] if bull else self.bb_up[k]
        out["cr_bb_outside"] = float((band - ext) * sgn / atr)          # + = block extreme pierced the band
        out["cr_bb_width_atr"] = float(self.bb_width[k] / atr)
        kband = self.kc_lo[k] if bull else self.kc_up[k]
        out["cr_kc_outside"] = float((kband - ext) * sgn / atr)
        out["cr_macd_hist_aligned"] = self._al(self.macd_hist[i] / atr, bull)
        out["cr_adx"] = float(self.adx[k])
        # DI against the coming move at the block (the move that built the zone fought a trend)
        out["cr_di_against"] = float((self.minus_di[k] - self.plus_di[k]) * sgn)
        out["cr_stoch_extreme"] = float((50.0 - self.stoch_k[k]) * sgn)
        imp = range(min(blk_end + 1, i), i + 1)
        blk = range(blk_start, blk_end + 1)
        out["cr_vol_impulse_rel"] = float(np.mean([self.relvol[x] for x in imp]))
        out["cr_vol_block_rel"] = float(np.mean([self.relvol[x] for x in blk]))
        out["cr_vol_climax"] = float(max(self.relvol[x] for x in range(blk_start, i + 1)) >= 2.5)
        out["cr_obv_confirm"] = self._al(self.obv_slope[i], bull)
        out["cr_supertrend_flip"] = float(any(self.st_dir[x] != self.st_dir[x - 1] for x in range(max(blk_start, 1), i + 1))
                                          and self.st_dir[i] * sgn > 0)
        out["cr_ema_ribbon_aligned"] = self._al(self.ribbon[i], bull)
        out["cr_zone_vs_ema50_atr"] = float(max(min(((top + bottom) / 2 - self.ema50[i]) / atr, 20.0), -20.0))
        out["cr_zone_vs_vwap_atr"] = float(max(min(((top + bottom) / 2 - self.vwap[i]) / atr, 20.0), -20.0))
        pdist, _ = self._nearest_pivot(i, (top + bottom) / 2)
        out["cr_pivot_dist_atr"] = float(min(pdist / atr, 20.0)) if np.isfinite(pdist) else 20.0
        out["cr_atr_pctile"] = float(self.atr_pctile[i])
        out["cr_chop"] = float(self.chop[k])
        out["cr_cci_extreme"] = float(-self.cci[k] * sgn / 100.0)
        r55 = self.hh55[i] - self.ll55[i]
        edge = top if bull else bottom
        z55 = (edge - self.ll55[i]) / r55 if r55 > 0 else 0.5
        out["cr_zone_fib55"] = float(min(max(z55 if bull else 1.0 - z55, -0.5), 1.5))
        return out

    def htf_features(self, hi: int, bull: bool, top: float, bottom: float, atr_ltf: float) -> Dict[str, float]:
        """Parent-timeframe indicator state at HTF bar ``hi`` for a zone of the child TF."""
        sgn = 1.0 if bull else -1.0
        atr = float(self.atr[hi])
        edge = top if bull else bottom
        band = self.bb_lo[hi] if bull else self.bb_up[hi]
        return {
            "htf_rsi_aligned": float((50.0 - self.rsi[hi]) * sgn),
            "htf_adx": float(self.adx[hi]),
            "htf_di_aligned": self._al(self.plus_di[hi] - self.minus_di[hi], bull),
            "htf_macd_hist_aligned": self._al(self.macd_hist[hi] / atr, bull),
            "htf_supertrend_aligned": self._al(self.st_dir[hi], bull),
            "htf_ema_ribbon_aligned": self._al(self.ribbon[hi], bull),
            "htf_bb_pctb_aligned": float((0.5 - self.bb_pctb[hi]) * sgn),
            "htf_zone_vs_ema50_atr": float(max(min((edge - self.ema50[hi]) / atr, 20.0), -20.0)),
            "htf_atr_pctile": float(self.atr_pctile[hi]),
            "htf_stoch_k_aligned": float((50.0 - self.stoch_k[hi]) * sgn),
            "htf_zone_beyond_bb": float((band - edge) * sgn > 0),
        }
