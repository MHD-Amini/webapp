"""Data loading and resampling.

The bot always works from an M1 series (CSV export from MT5 or live MT5 rates)
and derives every higher timeframe from it so that all timeframes are perfectly
aligned and the "Hidden Base" detector can look inside a HTF candle.
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import Dict, Iterable, Optional

import numpy as np
import pandas as pd

from .config import TIMEFRAME_MINUTES

COLUMNS = ["open", "high", "low", "close", "volume"]


def impute_spread(df: pd.DataFrame, ny_offset_hours: float = 7.0, min_valid: int = 500) -> pd.DataFrame:
    """Fill bars whose exported spread is 0 / missing with the *typical* spread of
    the bars that do carry one.

    MT5 "Export Bars" files often have ``<SPREAD>=0`` for the older part of the
    history (the terminal only stores the spread for bars it downloaded itself).
    The user's instruction is to treat that part "as having the same spread as
    the part with spread", so we build a (weekday, NY-hour) profile - the spread
    is systematically wider around the daily rollover and thinner in London/NY -
    from the bars with a real spread (median per cell) and use it for the empty
    bars; cells without enough observations fall back to the hourly profile and
    finally to the global median.  A boolean column ``spread_imputed`` marks the
    filled bars.  If no bar carries a spread, nothing is changed.
    """
    if "spread" not in df.columns or len(df) == 0:
        return df
    out = df.copy()
    s = out["spread"].to_numpy(dtype=float)
    valid = np.isfinite(s) & (s > 0)
    out["spread_imputed"] = ~valid
    if valid.sum() < min_valid or valid.all():
        return out
    ny = out.index - pd.Timedelta(hours=ny_offset_hours)
    key = pd.DataFrame({"dow": ny.dayofweek, "hour": ny.hour, "s": s}, index=out.index)
    ref = key[valid]
    global_med = float(ref["s"].median())
    by_hour = ref.groupby("hour")["s"].median()
    cell = ref.groupby(["dow", "hour"])["s"].agg(["median", "size"])
    cell = cell[cell["size"] >= 20]["median"]
    fill = key.loc[~valid, ["dow", "hour"]]
    est = pd.Series(
        cell.reindex(pd.MultiIndex.from_arrays([fill["dow"], fill["hour"]])).to_numpy(), index=fill.index)
    est = est.fillna(pd.Series(by_hour.reindex(fill["hour"]).to_numpy(), index=fill.index)).fillna(global_med)
    s[~valid] = est.to_numpy(dtype=float)
    out["spread"] = s
    return out


def load_mt5_csv(path: str | Path, point_value: float = 0.01, fill_spread: bool = True) -> pd.DataFrame:
    """Load an MT5 "Export Bars" TSV/CSV file (<DATE> <TIME> <OPEN> ...).

    ``fill_spread``: bars exported with spread 0 get the typical spread of the
    bars that have one (see :func:`impute_spread`)."""
    raw = Path(path).read_text(encoding="utf-8", errors="ignore")
    sep = "\t" if "\t" in raw[:500] else ","
    df = pd.read_csv(io.StringIO(raw), sep=sep)
    df.columns = [c.strip("<>").strip().lower() for c in df.columns]
    if "date" in df.columns and "time" in df.columns:
        ts = pd.to_datetime(df["date"].astype(str) + " " + df["time"].astype(str),
                            format="%Y.%m.%d %H:%M:%S", errors="coerce")
    elif "date" in df.columns:
        ts = pd.to_datetime(df["date"].astype(str), errors="coerce")
    else:
        ts = pd.to_datetime(df["time"], errors="coerce")
    out = pd.DataFrame(
        {
            "open": df["open"].to_numpy(dtype=float),
            "high": df["high"].to_numpy(dtype=float),
            "low": df["low"].to_numpy(dtype=float),
            "close": df["close"].to_numpy(dtype=float),
            "volume": df["tickvol"].to_numpy(dtype=float) if "tickvol" in df.columns else np.zeros(len(df)),
        },
        index=pd.DatetimeIndex(ts.to_numpy(), name="time"),
    )
    if "spread" in df.columns:
        # MT5 spread is in points; XAUUSD point = 0.01
        out["spread"] = df["spread"].to_numpy(dtype=float) * point_value
    out = out[~out.index.isna()].sort_index()
    out = out[~out.index.duplicated(keep="last")]
    if fill_spread and "spread" in out.columns:
        out = impute_spread(out)
    return out


def frame_from_mt5_rates(rates) -> pd.DataFrame:
    """Convert a numpy structured array returned by MetaTrader5.copy_rates_* ."""
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df = df.set_index("time")
    df = df.rename(columns={"tick_volume": "volume"})
    return df[["open", "high", "low", "close", "volume"]].astype(float)


def resample(m1: pd.DataFrame, tf: str) -> pd.DataFrame:
    """Resample M1 candles into `tf`.  Bars are labelled by their OPEN time."""
    minutes = TIMEFRAME_MINUTES[tf]
    if minutes == 1:
        return m1.copy()
    rule = f"{minutes}min"
    agg = m1.resample(rule, label="left", closed="left", origin="start_day").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    )
    return agg.dropna(subset=["open"])


def resample_all(m1: pd.DataFrame, timeframes: Iterable[str]) -> Dict[str, pd.DataFrame]:
    return {tf: resample(m1, tf) for tf in timeframes}


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Wilder-style ATR (simple rolling mean of true range, robust for POIs)."""
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [df["high"] - df["low"], (df["high"] - prev_close).abs(), (df["low"] - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    out = tr.rolling(period, min_periods=1).mean()
    return out.bfill()


class Candles:
    """Light numpy view of a candle frame for fast scanning."""

    __slots__ = ("tf", "index", "open", "high", "low", "close", "volume", "atr", "n")

    def __init__(self, df: pd.DataFrame, tf: str, atr_period: int = 14):
        self.tf = tf
        self.index = df.index
        self.open = df["open"].to_numpy(dtype=float)
        self.high = df["high"].to_numpy(dtype=float)
        self.low = df["low"].to_numpy(dtype=float)
        self.close = df["close"].to_numpy(dtype=float)
        self.volume = df["volume"].to_numpy(dtype=float) if "volume" in df else np.zeros(len(df))
        self.atr = atr(df, atr_period).to_numpy(dtype=float)
        self.n = len(df)

    def body_top(self, i: int) -> float:
        return max(self.open[i], self.close[i])

    def body_bottom(self, i: int) -> float:
        return min(self.open[i], self.close[i])

    def is_bull(self, i: int) -> bool:
        return self.close[i] > self.open[i]

    def is_bear(self, i: int) -> bool:
        return self.close[i] < self.open[i]

    def time(self, i: int):
        return self.index[i]
