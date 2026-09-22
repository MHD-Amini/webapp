"""v13 - market REGIME from closed daily bars (shared by the simulator and the live bot).

The v13 diagnosis (study_results/WEAK_MONTHS_V13.md) showed that the negative month of the v12-A trader (Apr 2026) was not a
selection problem but a MANAGEMENT problem: in a post-crash range the far legs of the 0.6/1.2/2.4/4.8R ladder are never paid,
the partials return to break-even and the stop-rate rises.  The bot earns with volatility (Spearman of monthly R vs average
daily range = +0.56).  These helpers compute, from the daily bars that are already CLOSED at the moment an order is placed
(nothing intrabar, nothing from the future), a scalar "regime metric" that the trader compares to a threshold:

* ``adr_ratio`` - mean daily range of the last ``short`` days / mean daily range of the last ``long`` days
                  (< 1 = volatility contracting)
* ``er``        - Kaufman efficiency ratio of the daily closes over ``short`` days: |net move| / sum of |daily moves|
                  (0 = pure chop, 1 = straight line)
* ``adr_pct``   - mean daily range of the last ``long`` days as % of the last close (absolute volatility level)

``regime_of(metric_value, threshold)`` -> "range" when the metric is BELOW the threshold, else "trend".  The trader then
uses the alternative ladder / stop schedule / risk scale configured for the range regime (``TraderConfig.range_*``).

Server days are used as trading days (the M1 index is server time); the metric of day D is computed from the days
< D and is valid for every minute of D.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

METRICS = ("adr_ratio", "er", "adr_pct")


def daily_bars(m1: pd.DataFrame) -> pd.DataFrame:
    """Server-day OHLC from M1 bars (days without bars dropped)."""
    d = m1[["open", "high", "low", "close"]].resample("1D").agg({"open": "first", "high": "max", "low": "min", "close": "last"})
    return d.dropna(subset=["open"])


def _raw_metric(daily: pd.DataFrame, metric: str, short: int, long: int) -> pd.Series:
    """Metric of every day computed from that day and the days before it (INCLUDING the day itself)."""
    if metric not in METRICS:
        raise ValueError(f"unknown regime metric {metric!r} (use one of {METRICS})")
    rng = (daily["high"] - daily["low"]).astype(float)
    if metric == "adr_ratio":
        return rng.rolling(short).mean() / rng.rolling(long).mean()
    if metric == "er":
        c = daily["close"].astype(float)
        return c.diff(short).abs() / c.diff().abs().rolling(short).sum()
    return rng.rolling(long).mean() / daily["close"].astype(float) * 100.0      # adr_pct


def metric_series(daily: pd.DataFrame, metric: str, short: int = 5, long: int = 20) -> pd.Series:
    """Metric per day computed from the days STRICTLY BEFORE it (shift(1)) -> usable at that day's open.
    NaN while the history is too short (the trader treats NaN as 'trend' = default behaviour)."""
    return _raw_metric(daily, metric, short, long).shift(1)


def regime_of(value: float, threshold: float) -> str:
    """'range' when the metric is below the threshold, 'trend' otherwise (NaN -> 'trend')."""
    if value is None or not np.isfinite(value):
        return "trend"
    return "range" if value < threshold else "trend"


def minute_metric(m1: pd.DataFrame, metric: str, short: int = 5, long: int = 20) -> np.ndarray:
    """Metric value for every M1 bar of ``m1`` (the value of its server day)."""
    daily = daily_bars(m1)
    s = metric_series(daily, metric, short, long)
    days = m1.index.normalize()
    return s.reindex(days).to_numpy(dtype=float)


def latest_metric(daily: pd.DataFrame, metric: str, short: int = 5, long: int = 20, today: Optional[pd.Timestamp] = None) -> float:
    """Live bot: metric valid NOW from a frame of daily bars whose LAST row may be the (unfinished) current day.
    Rows dated >= ``today`` (default: the last row's day) are excluded so only CLOSED days are used."""
    d = daily
    if today is None and len(d):
        today = d.index[-1].normalize()
    if today is not None:
        d = d[d.index.normalize() < today]
    if len(d) < max(short, long) + 1:
        return float("nan")
    v = _raw_metric(d, metric, short, long).iloc[-1]
    return float(v) if np.isfinite(v) else float("nan")
