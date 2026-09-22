"""Minimal in-memory stand-in for the ``MetaTrader5`` package (hedging account).

Supports what ``lubot.mt5_broker.MT5Broker`` and ``trader.py`` use: initialize, symbol/account/tick
info, rates, orders_get / positions_get, order_send (pending, remove, sltp, deal close).
``set_price(bid)`` moves the market and fills / stops / takes profit like a broker.
"""
from __future__ import annotations

import time
from types import SimpleNamespace

import numpy as np


class FakeMT5:
    TIMEFRAME_M1 = 1
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    ORDER_TYPE_BUY_LIMIT = 2
    ORDER_TYPE_SELL_LIMIT = 3
    POSITION_TYPE_BUY = 0
    POSITION_TYPE_SELL = 1
    TRADE_ACTION_DEAL = 1
    TRADE_ACTION_PENDING = 5
    TRADE_ACTION_SLTP = 6
    TRADE_ACTION_REMOVE = 8
    ORDER_TIME_GTC = 0
    ORDER_FILLING_FOK = 0
    ORDER_FILLING_IOC = 1
    ORDER_FILLING_RETURN = 2
    SYMBOL_FILLING_FOK = 1
    SYMBOL_FILLING_IOC = 2
    TRADE_RETCODE_DONE = 10009
    TRADE_RETCODE_PLACED = 10008
    ACCOUNT_MARGIN_MODE_RETAIL_HEDGING = 2

    def __init__(self, m1: "pd.DataFrame", bid: float, spread: float = 0.30, balance: float = 10_000.0, hedging=True):
        self.m1 = m1
        self.bid = bid
        self.spread = spread
        self.balance = balance
        self.hedging = hedging
        self.orders = {}
        self.positions = {}
        self.history = []          # closed positions
        self._ticket = 1000
        self.now = float(m1.index[-1].value // 10 ** 9) + 60
        self.sent = []             # log of requests

    # -------------------------------------------------------------- terminal api
    def initialize(self, **kw):
        return True

    def shutdown(self):
        pass

    def last_error(self):
        return (0, "ok")

    def symbol_select(self, s, on=True):
        return True

    def symbol_info(self, s):
        return SimpleNamespace(digits=2, point=0.01, trade_contract_size=100.0, volume_min=0.01, volume_max=100.0,
                               volume_step=0.01, trade_stops_level=0, swap_long=-50.0, swap_short=15.0,
                               filling_mode=3, name=s)

    def account_info(self):
        eq = self.balance + sum(self._profit(p) for p in self.positions.values())
        return SimpleNamespace(login=123, server="Fake-Demo", currency="USD", balance=self.balance, equity=eq,
                               margin_free=eq, leverage=100,
                               margin_mode=2 if self.hedging else 0)

    def symbol_info_tick(self, s):
        return SimpleNamespace(bid=self.bid, ask=self.bid + self.spread, time=int(self.now))

    def copy_rates_from_pos(self, s, tf, start, count):
        df = self.m1.iloc[-count:]
        return self._rates(df)

    def copy_rates_range(self, s, tf, start, end):
        t0 = np.datetime64(start.replace(tzinfo=None))
        df = self.m1[self.m1.index.values >= t0]
        return self._rates(df)

    def _rates(self, df):
        arr = np.zeros(len(df), dtype=[("time", "i8"), ("open", "f8"), ("high", "f8"), ("low", "f8"), ("close", "f8"),
                                       ("tick_volume", "i8"), ("spread", "i4"), ("real_volume", "i8")])
        arr["time"] = df.index.values.astype("datetime64[s]").astype("i8")
        for c in ("open", "high", "low", "close"):
            arr[c] = df[c].to_numpy()
        arr["tick_volume"] = df["volume"].to_numpy().astype("i8")
        arr["spread"] = int(round(self.spread / 0.01))
        return arr

    def orders_get(self, symbol=None):
        return list(self.orders.values())

    def positions_get(self, symbol=None):
        return list(self.positions.values())

    def history_deals_get(self, position=None, **kw):
        """v14: closed deals of a position (one per close; profit net of nothing - the fake has no commission / swap)."""
        return [SimpleNamespace(position_id=h["ticket"], profit=h["pnl"], commission=0.0, swap=0.0, volume=h["vol"], price=h["px"])
                for h in self.history if position is None or h["ticket"] == position]

    # -------------------------------------------------------------- trading
    def order_send(self, req):
        self.sent.append(dict(req))
        a = req["action"]
        if a == self.TRADE_ACTION_PENDING:
            self._ticket += 1
            o = SimpleNamespace(ticket=self._ticket, type=req["type"], price_open=req["price"], sl=req["sl"], tp=req["tp"],
                                volume_current=req["volume"], magic=req["magic"], comment=req["comment"],
                                time_setup=int(self.now))
            self.orders[o.ticket] = o
            return SimpleNamespace(retcode=self.TRADE_RETCODE_DONE, order=o.ticket, comment="placed")
        if a == self.TRADE_ACTION_REMOVE:
            self.orders.pop(req["order"], None)
            return SimpleNamespace(retcode=self.TRADE_RETCODE_DONE, order=req["order"], comment="removed")
        if a == self.TRADE_ACTION_SLTP:
            p = self.positions.get(req["position"])
            if p is None:
                return SimpleNamespace(retcode=10036, order=0, comment="position closed")
            p.sl, p.tp = req["sl"], req["tp"]
            return SimpleNamespace(retcode=self.TRADE_RETCODE_DONE, order=p.ticket, comment="modified")
        if a == self.TRADE_ACTION_DEAL:
            p = self.positions.get(req["position"])
            if p is None:
                return SimpleNamespace(retcode=10036, order=0, comment="position closed")
            vol = req["volume"]
            px = self.bid if p.type == self.POSITION_TYPE_BUY else self.bid + self.spread
            self._close(p, vol, px, "market")
            return SimpleNamespace(retcode=self.TRADE_RETCODE_DONE, order=p.ticket, comment="closed")
        return SimpleNamespace(retcode=10013, order=0, comment="invalid request")

    # -------------------------------------------------------------- market simulation
    def _profit(self, p):
        px = self.bid if p.type == self.POSITION_TYPE_BUY else self.bid + self.spread
        sgn = 1 if p.type == self.POSITION_TYPE_BUY else -1
        return sgn * (px - p.price_open) * p.volume * 100.0

    def _close(self, p, vol, px, reason):
        sgn = 1 if p.type == self.POSITION_TYPE_BUY else -1
        pnl = sgn * (px - p.price_open) * vol * 100.0
        self.balance += pnl
        self.history.append({"ticket": p.ticket, "vol": vol, "px": px, "pnl": pnl, "reason": reason, "comment": p.comment})
        if vol >= p.volume - 1e-9:
            self.positions.pop(p.ticket)
        else:
            p.volume = round(p.volume - vol, 8)

    def set_price(self, bid: float, advance_seconds: int = 60):
        """Move the market to ``bid`` (path: straight line) and process fills / stops / TPs."""
        self.now += advance_seconds
        self.bid = bid
        ask = bid + self.spread
        for o in list(self.orders.values()):
            if o.type == self.ORDER_TYPE_BUY_LIMIT and ask <= o.price_open:
                self._fill(o, self.POSITION_TYPE_BUY, o.price_open)
            elif o.type == self.ORDER_TYPE_SELL_LIMIT and bid >= o.price_open:
                self._fill(o, self.POSITION_TYPE_SELL, o.price_open)
        for p in list(self.positions.values()):
            if p.type == self.POSITION_TYPE_BUY:
                if p.sl and bid <= p.sl:
                    self._close(p, p.volume, p.sl, "sl")
                elif p.tp and bid >= p.tp:
                    self._close(p, p.volume, p.tp, "tp")
            else:
                if p.sl and ask >= p.sl:
                    self._close(p, p.volume, p.sl, "sl")
                elif p.tp and ask <= p.tp:
                    self._close(p, p.volume, p.tp, "tp")

    def _fill(self, o, ptype, price):
        self.orders.pop(o.ticket)
        p = SimpleNamespace(ticket=o.ticket, type=ptype, price_open=price, sl=o.sl, tp=o.tp, volume=o.volume_current,
                            magic=o.magic, comment=o.comment, profit=0.0, time=int(self.now))
        self.positions[p.ticket] = p
