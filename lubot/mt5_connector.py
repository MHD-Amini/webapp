"""MetaTrader 5 connector (Windows only - the ``MetaTrader5`` pip package talks
to a running terminal).  Everything here is optional: the rest of the bot works
from CSV files on any OS.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd

from .config import StrategyConfig
from .data import frame_from_mt5_rates

try:  # pragma: no cover - only available on Windows with a terminal installed
    import MetaTrader5 as mt5  # type: ignore
except Exception:  # noqa: BLE001
    mt5 = None


class MT5Connector:
    def __init__(self, symbol: str, login: Optional[int] = None, password: Optional[str] = None,
                 server: Optional[str] = None, path: Optional[str] = None):
        if mt5 is None:
            raise RuntimeError(
                "MetaTrader5 package not available. Install with `pip install MetaTrader5` "
                "on Windows with an MT5 terminal installed."
            )
        self.symbol = symbol
        kwargs = {}
        if path:
            kwargs["path"] = path
        if login:
            kwargs.update(login=int(login), password=password or "", server=server or "")
        if not mt5.initialize(**kwargs):
            raise RuntimeError(f"mt5.initialize() failed: {mt5.last_error()}")
        if not mt5.symbol_select(symbol, True):
            raise RuntimeError(f"symbol_select({symbol}) failed: {mt5.last_error()}")
        info = mt5.symbol_info(symbol)
        if info is None:
            raise RuntimeError(f"symbol {symbol} not found")
        self.digits = info.digits
        self.point = info.point

    # ------------------------------------------------------------ utilities
    def shutdown(self) -> None:
        mt5.shutdown()

    def server_utc_offset_hours(self) -> float:
        """Estimate broker server offset from UTC using the latest tick time."""
        tick = mt5.symbol_info_tick(self.symbol)
        if tick is None:
            return 0.0
        server_now = datetime.fromtimestamp(tick.time, tz=timezone.utc)   # naive server time as if UTC
        real_now = datetime.now(timezone.utc)
        diff_h = (server_now - real_now).total_seconds() / 3600.0
        return round(diff_h * 2) / 2.0  # round to half hours

    def current_price(self) -> float:
        tick = mt5.symbol_info_tick(self.symbol)
        return float((tick.bid + tick.ask) / 2.0)

    def m1_history(self, bars: int = 60000) -> pd.DataFrame:
        rates = mt5.copy_rates_from_pos(self.symbol, mt5.TIMEFRAME_M1, 0, bars)
        if rates is None or len(rates) == 0:
            raise RuntimeError(f"copy_rates_from_pos failed: {mt5.last_error()}")
        return frame_from_mt5_rates(rates)

    def m1_since(self, since: pd.Timestamp) -> pd.DataFrame:
        start = since.to_pydatetime().replace(tzinfo=timezone.utc)
        rates = mt5.copy_rates_range(self.symbol, mt5.TIMEFRAME_M1, start,
                                     datetime.now(timezone.utc) + timedelta(days=1))
        if rates is None or len(rates) == 0:
            return pd.DataFrame()
        return frame_from_mt5_rates(rates)


def wait_for_next_minute(offset_seconds: float = 2.0) -> None:
    now = time.time()
    nxt = (int(now // 60) + 1) * 60 + offset_seconds
    time.sleep(max(0.0, nxt - now))
