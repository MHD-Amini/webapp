"""Broker adapter around the ``MetaTrader5`` Python package.

Attach-only: ``mt5.initialize()`` with NO login/password/server.  The package
connects to the MT5 terminal that is already running on this Windows machine and
uses the account the terminal is logged in to.  If no terminal is running it starts
the last-used one (``path`` may point to a specific ``terminal64.exe``).

Everything the live trader needs is wrapped here so that ``trader.py`` can be tested
against :class:`FakeMT5` (``tests/fake_mt5.py``) without a terminal.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import pandas as pd

from .data import frame_from_mt5_rates
from .execution import BUY, SELL, SymbolSpec

try:  # pragma: no cover
    import MetaTrader5 as _mt5  # type: ignore
except Exception:  # noqa: BLE001
    _mt5 = None


@dataclass
class BrokerOrder:
    ticket: int
    kind: str            # "buy_limit" | "sell_limit"
    price: float
    sl: float
    tp: float
    volume: float
    magic: int
    comment: str
    time_setup: Optional[pd.Timestamp] = None


@dataclass
class BrokerPosition:
    ticket: int
    side: str            # buy / sell
    price_open: float
    sl: float
    tp: float
    volume: float
    magic: int
    comment: str
    profit: float = 0.0
    time: Optional[pd.Timestamp] = None


class MT5Broker:
    def __init__(self, symbol: str, mt5=None, path: Optional[str] = None, deviation_points: int = 30,
                 timeout_ms: int = 60_000):
        self.mt5 = mt5 or _mt5
        if self.mt5 is None:
            raise RuntimeError("MetaTrader5 package not available - run on Windows with `pip install MetaTrader5` "
                               "and the MT5 terminal open and logged in.")
        self.symbol = symbol
        self.deviation = deviation_points
        kwargs = {"timeout": timeout_ms}
        if path:
            kwargs["path"] = path
        # NO login / password / server: attach to the running, already logged-in terminal
        if not self.mt5.initialize(**kwargs):
            raise RuntimeError(f"mt5.initialize() failed: {self.mt5.last_error()} - is the MT5 terminal open and logged in?")
        if not self.mt5.symbol_select(symbol, True):
            raise RuntimeError(f"symbol_select({symbol}) failed: {self.mt5.last_error()}")
        info = self.mt5.symbol_info(symbol)
        if info is None:
            raise RuntimeError(f"symbol {symbol} not found in Market Watch")
        self.info = info
        acc = self.mt5.account_info()
        if acc is None:
            raise RuntimeError("account_info() is None - terminal not logged in?")
        self.account = acc
        self.hedging = getattr(acc, "margin_mode", 2) == getattr(self.mt5, "ACCOUNT_MARGIN_MODE_RETAIL_HEDGING", 2)
        self.filling = self._pick_filling(info)

    # ------------------------------------------------------------------ info
    def _pick_filling(self, info) -> int:
        m = self.mt5
        modes = getattr(info, "filling_mode", 0)
        if modes & getattr(m, "SYMBOL_FILLING_FOK", 1):
            return m.ORDER_FILLING_FOK
        if modes & getattr(m, "SYMBOL_FILLING_IOC", 2):
            return m.ORDER_FILLING_IOC
        return getattr(m, "ORDER_FILLING_RETURN", 2)

    def spec(self, commission_per_lot: float = 0.0) -> SymbolSpec:
        i = self.info
        return SymbolSpec(symbol=self.symbol, digits=i.digits, point=i.point, contract_size=i.trade_contract_size,
                          volume_min=i.volume_min, volume_max=i.volume_max, volume_step=i.volume_step,
                          stops_level_points=getattr(i, "trade_stops_level", 0), commission_per_lot=commission_per_lot,
                          swap_long_per_lot=getattr(i, "swap_long", 0.0), swap_short_per_lot=getattr(i, "swap_short", 0.0),
                          leverage=float(getattr(self.account, "leverage", 100)), currency=self.account.currency)

    def refresh_account(self):
        acc = self.mt5.account_info()
        if acc is not None:
            self.account = acc
        return self.account

    @property
    def equity(self) -> float:
        return float(self.refresh_account().equity)

    @property
    def balance(self) -> float:
        return float(self.account.balance)

    def tick(self):
        return self.mt5.symbol_info_tick(self.symbol)

    def price(self) -> Dict[str, float]:
        t = self.tick()
        return {"bid": float(t.bid), "ask": float(t.ask), "time": float(t.time)}

    def server_utc_offset_hours(self) -> float:
        t = self.tick()
        if t is None:
            return 0.0
        server_now = datetime.fromtimestamp(t.time, tz=timezone.utc)
        diff_h = (server_now - datetime.now(timezone.utc)).total_seconds() / 3600.0
        return round(diff_h * 2) / 2.0

    # ------------------------------------------------------------------ history
    def m1_history(self, bars: int) -> pd.DataFrame:
        rates = self.mt5.copy_rates_from_pos(self.symbol, self.mt5.TIMEFRAME_M1, 0, bars)
        if rates is None or len(rates) == 0:
            raise RuntimeError(f"copy_rates_from_pos failed: {self.mt5.last_error()}")
        df = frame_from_mt5_rates(rates)
        try:
            sp = pd.Series(rates["spread"], index=df.index).astype(float) * self.info.point
            df["spread"] = sp
        except Exception:  # noqa: BLE001
            pass
        return df

    def m1_since(self, since: pd.Timestamp) -> pd.DataFrame:
        start = since.to_pydatetime().replace(tzinfo=timezone.utc)
        rates = self.mt5.copy_rates_range(self.symbol, self.mt5.TIMEFRAME_M1, start,
                                          datetime.now(timezone.utc) + timedelta(days=2))
        if rates is None or len(rates) == 0:
            return pd.DataFrame()
        df = frame_from_mt5_rates(rates)
        try:
            df["spread"] = pd.Series(rates["spread"], index=df.index).astype(float) * self.info.point
        except Exception:  # noqa: BLE001
            pass
        return df

    # ------------------------------------------------------------------ state
    def orders(self, magic: Optional[int] = None) -> List[BrokerOrder]:
        raw = self.mt5.orders_get(symbol=self.symbol) or []
        out = []
        for o in raw:
            if magic is not None and o.magic != magic:
                continue
            kind = "buy_limit" if o.type == self.mt5.ORDER_TYPE_BUY_LIMIT else \
                   "sell_limit" if o.type == self.mt5.ORDER_TYPE_SELL_LIMIT else str(o.type)
            out.append(BrokerOrder(o.ticket, kind, float(o.price_open), float(o.sl), float(o.tp),
                                   float(o.volume_current), int(o.magic), str(o.comment),
                                   pd.Timestamp(o.time_setup, unit="s")))
        return out

    def positions(self, magic: Optional[int] = None) -> List[BrokerPosition]:
        raw = self.mt5.positions_get(symbol=self.symbol) or []
        out = []
        for p in raw:
            if magic is not None and p.magic != magic:
                continue
            side = BUY if p.type == self.mt5.POSITION_TYPE_BUY else SELL
            out.append(BrokerPosition(p.ticket, side, float(p.price_open), float(p.sl), float(p.tp), float(p.volume),
                                      int(p.magic), str(p.comment), float(p.profit), pd.Timestamp(p.time, unit="s")))
        return out

    def position_pnl(self, ticket: int) -> Optional[float]:
        """v14: realised net P&L (profit + commission + swap) of a CLOSED position from the deal history; None if unknown."""
        try:
            deals = self.mt5.history_deals_get(position=ticket) or []
        except Exception:  # noqa: BLE001
            return None
        if not deals:
            return None
        return float(sum(float(getattr(d, "profit", 0.0)) + float(getattr(d, "commission", 0.0)) + float(getattr(d, "swap", 0.0))
                         for d in deals))

    # ------------------------------------------------------------------ actions
    def _send(self, request: dict, what: str) -> Optional[object]:
        for attempt in range(3):
            res = self.mt5.order_send(request)
            if res is None:
                err = self.mt5.last_error()
                print(f"[broker] {what}: order_send returned None {err}")
                time.sleep(0.5)
                continue
            if res.retcode in (self.mt5.TRADE_RETCODE_DONE, getattr(self.mt5, "TRADE_RETCODE_PLACED", 10008),
                               getattr(self.mt5, "TRADE_RETCODE_DONE_PARTIAL", 10010)):
                return res
            if res.retcode in (getattr(self.mt5, "TRADE_RETCODE_REQUOTE", 10004),
                               getattr(self.mt5, "TRADE_RETCODE_PRICE_CHANGED", 10020),
                               getattr(self.mt5, "TRADE_RETCODE_PRICE_OFF", 10021)):
                time.sleep(0.3)
                continue
            if res.retcode == getattr(self.mt5, "TRADE_RETCODE_INVALID_FILL", 10030) and "type_filling" in request:
                request = dict(request, type_filling=self.mt5.ORDER_FILLING_IOC if request["type_filling"] != self.mt5.ORDER_FILLING_IOC
                               else getattr(self.mt5, "ORDER_FILLING_RETURN", 2))
                continue
            print(f"[broker] {what} failed: retcode={res.retcode} {getattr(res, 'comment', '')}")
            return None
        return None

    def place_limit(self, side: str, volume: float, price: float, sl: float, tp: float, magic: int,
                    comment: str) -> Optional[int]:
        m = self.mt5
        req = {
            "action": m.TRADE_ACTION_PENDING, "symbol": self.symbol, "volume": float(volume),
            "type": m.ORDER_TYPE_BUY_LIMIT if side == BUY else m.ORDER_TYPE_SELL_LIMIT,
            "price": float(price), "sl": float(sl), "tp": float(tp), "deviation": self.deviation,
            "magic": int(magic), "comment": comment[:31], "type_time": m.ORDER_TIME_GTC,
            "type_filling": getattr(m, "ORDER_FILLING_RETURN", 2),
        }
        res = self._send(req, f"place {side} limit {volume}@{price}")
        return int(res.order) if res is not None else None

    def cancel_order(self, ticket: int) -> bool:
        req = {"action": self.mt5.TRADE_ACTION_REMOVE, "order": int(ticket)}
        return self._send(req, f"cancel #{ticket}") is not None

    def modify_position(self, ticket: int, sl: float, tp: float) -> bool:
        req = {"action": self.mt5.TRADE_ACTION_SLTP, "symbol": self.symbol, "position": int(ticket),
               "sl": float(sl), "tp": float(tp)}
        return self._send(req, f"modify #{ticket} sl={sl} tp={tp}") is not None

    def close_position(self, pos: BrokerPosition, volume: Optional[float] = None, comment: str = "close") -> bool:
        m = self.mt5
        t = self.tick()
        vol = float(volume if volume is not None else pos.volume)
        req = {
            "action": m.TRADE_ACTION_DEAL, "symbol": self.symbol, "volume": vol, "position": int(pos.ticket),
            "type": m.ORDER_TYPE_SELL if pos.side == BUY else m.ORDER_TYPE_BUY,
            "price": float(t.bid if pos.side == BUY else t.ask), "deviation": self.deviation,
            "magic": int(pos.magic), "comment": comment[:31], "type_time": m.ORDER_TIME_GTC, "type_filling": self.filling,
        }
        return self._send(req, f"close #{pos.ticket} {vol}") is not None

    def shutdown(self) -> None:
        try:
            self.mt5.shutdown()
        except Exception:  # noqa: BLE001
            pass


def wait_for_next_minute(offset_seconds: float = 2.0) -> None:
    now = time.time()
    nxt = (int(now // 60) + 1) * 60 + offset_seconds
    time.sleep(max(0.0, nxt - now))
