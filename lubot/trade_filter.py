"""v8 - per-timeframe TRADE FILTER shared by the portfolio simulator and the live bot.

The v7 trader accepted every POI the scanner showed (quality >= 0.50).  On M5 that
population loses money because the zones are small (the spread + commission is a big
fraction of 1R) and because the scanner's bounce probability is not the probability
of *this plan* working.  ``TradeFilter`` applies interpretable, per-timeframe gates
to a plan before an order is placed:

* ``max_cost_r``      - (spread + commission per oz) / 1R must be <= this
* ``min_quality``     - scanner quality (P bounce) >= this
* ``min_zone_atr`` / ``max_zone_atr`` - zone height in ATR of the timeframe
* ``sessions``        - NY sessions allowed for the *selection* time (asia, london, preny, ny, lclose, nypm)
* ``sides`` / ``kinds`` - buy/sell, OB/IMB/UW/HB/BB
* ``model_path`` / ``model_min`` - optional trade-outcome model (train_trade_filter.py) score >= model_min

Rules are given as a string so they fit the existing ``--trader`` CLI style (timeframe blocks
separated by ``/`` because ``,`` already separates ``--trader`` overrides)::

    "M5:max_cost_r=0.08;min_quality=0.55;sessions=london|preny|ny|lclose/M10:max_cost_r=0.10"

Unlisted timeframes are unfiltered (v7 behaviour).  ``describe()`` prints the active rules.
Everything a rule needs is already on the selection dict the scanner returns (quality,
top/bottom, atr, type, direction, time) plus the current spread from the broker.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

import pandas as pd

from .quality import QualityScorer, session_of

#: server time is NY + 7h all year for EET brokers (see StrategyConfig.server_minus_ny_hours)
SERVER_MINUS_NY_HOURS = 7.0
EST_COMMISSION_OZ = 0.07     # $7 / lot round turn / 100 oz


@dataclass
class TFRule:
    max_cost_r: float = 0.0            # 0 = off
    min_quality: float = 0.0
    min_zone_atr: float = 0.0
    max_zone_atr: float = 0.0
    sessions: Tuple[str, ...] = ()
    sides: Tuple[str, ...] = ()
    kinds: Tuple[str, ...] = ()
    model_path: str = ""
    model_min: float = 0.0
    hours: Tuple[int, ...] = ()        # allowed NY hours of the selection time (empty = all)

    def active(self) -> bool:
        return any([self.max_cost_r, self.min_quality, self.min_zone_atr, self.max_zone_atr, self.sessions, self.sides,
                    self.kinds, self.model_path, self.hours])

    def describe(self) -> str:
        parts = []
        for k in ("max_cost_r", "min_quality", "min_zone_atr", "max_zone_atr", "model_min"):
            v = getattr(self, k)
            if v:
                parts.append(f"{k}={v}")
        for k in ("sessions", "sides", "kinds", "hours"):
            v = getattr(self, k)
            if v:
                parts.append(f"{k}={'|'.join(str(x) for x in v)}")
        if self.model_path:
            parts.append(f"model={self.model_path}")
        return ";".join(parts) or "none"


def ny_session_of(ts, server_minus_ny_hours: float = SERVER_MINUS_NY_HOURS) -> Tuple[str, int]:
    """NY session name + NY hour of a server-time timestamp."""
    t = pd.Timestamp(ts) - pd.Timedelta(hours=server_minus_ny_hours)
    return session_of(t.hour), int(t.hour)


class TradeFilter:
    def __init__(self, rules: Optional[Dict[str, TFRule]] = None, spread_estimate: float = 0.28,
                 commission_oz: float = EST_COMMISSION_OZ, server_minus_ny_hours: float = SERVER_MINUS_NY_HOURS):
        self.rules: Dict[str, TFRule] = rules or {}
        self.spread_estimate = spread_estimate
        self.commission_oz = commission_oz
        self.server_minus_ny = server_minus_ny_hours
        self._models: Dict[str, QualityScorer] = {}

    # ----------------------------------------------------------------- parsing
    @classmethod
    def parse(cls, text: Optional[str], **kw) -> "TradeFilter":
        """'M5:max_cost_r=0.08;min_quality=0.55;sessions=london|ny/M10:max_cost_r=0.1' -> TradeFilter"""
        rules: Dict[str, TFRule] = {}
        if text:
            for block in text.replace(",", "/").split("/"):
                block = block.strip()
                if not block:
                    continue
                tf, _, body = block.partition(":")
                tf = tf.strip()
                if not body:
                    raise ValueError(f"trade-filter block '{block}' needs 'TF:key=value;...'")
                for tfi in (tf.split("|") if tf != "*" else ["*"]):
                    r = rules.setdefault(tfi, TFRule())
                    for pair in body.split(";"):
                        if not pair.strip():
                            continue
                        k, _, v = pair.partition("=")
                        k, v = k.strip(), v.strip()
                        if not hasattr(r, k):
                            raise ValueError(f"unknown trade-filter key {k}")
                        cur = getattr(r, k)
                        if isinstance(cur, tuple):
                            vals = tuple(x.strip() for x in v.split("|") if x.strip())
                            setattr(r, k, tuple(int(x) for x in vals) if k == "hours" else vals)
                        elif isinstance(cur, float):
                            setattr(r, k, float(v))
                        else:
                            setattr(r, k, v)
        return cls(rules, **kw)

    def rule_for(self, tf: str) -> Optional[TFRule]:
        r = self.rules.get(tf) or self.rules.get("*")
        return r if (r is not None and r.active()) else None

    def active(self) -> bool:
        return any(r.active() for r in self.rules.values())

    def describe(self) -> str:
        return ", ".join(f"{tf}: {r.describe()}" for tf, r in self.rules.items() if r.active()) or "no trade filter (v7 behaviour)"

    def to_text(self) -> str:
        return "/".join(f"{tf}:{r.describe()}" for tf, r in self.rules.items() if r.active())

    # ----------------------------------------------------------------- scoring
    def _model(self, path: str) -> Optional[QualityScorer]:
        m = self._models.get(path)
        if m is None and path:
            m = QualityScorer.load(path)
            self._models[path] = m
        return m

    def cost_r(self, top: float, bottom: float, spread: Optional[float]) -> float:
        risk = abs(float(top) - float(bottom))
        sp = self.spread_estimate if (spread is None or not math.isfinite(spread)) else float(spread)
        return (sp + self.commission_oz) / risk if risk > 0 else float("inf")

    def check(self, d: Dict, tf: str, spread: Optional[float] = None, when=None) -> Optional[str]:
        """Return None when the plan passes, else the reason it is rejected.

        ``d`` = selection dict of the POI (top, bottom, quality, type, direction, atr, time, and
        optionally ``features``/``context``/``feats`` for the model).  ``when`` = selection time (server);
        defaults to d["time"]."""
        r = self.rule_for(tf)
        if r is None:
            return None
        top, bottom = float(d["top"]), float(d["bottom"])
        if r.max_cost_r:
            c = self.cost_r(top, bottom, spread)
            if c > r.max_cost_r:
                return f"cost_r {c:.3f} > {r.max_cost_r}"
        q = d.get("quality")
        if r.min_quality and not (q is not None and float(q) >= r.min_quality):
            return f"quality {q} < {r.min_quality}"
        atr = d.get("atr")
        if (r.min_zone_atr or r.max_zone_atr) and atr and float(atr) > 0:
            za = (top - bottom) / float(atr)
            if r.min_zone_atr and za < r.min_zone_atr:
                return f"zone {za:.2f} ATR < {r.min_zone_atr}"
            if r.max_zone_atr and za > r.max_zone_atr:
                return f"zone {za:.2f} ATR > {r.max_zone_atr}"
        side = "buy" if d.get("direction") == "bullish" else "sell"
        if r.sides and side not in r.sides:
            return f"side {side}"
        if r.kinds and d.get("type") not in r.kinds:
            return f"kind {d.get('type')}"
        if r.sessions or r.hours:
            ts = when if when is not None else d.get("time")
            if ts is not None:
                sess, hour = ny_session_of(ts, self.server_minus_ny)
                if r.sessions and sess not in r.sessions:
                    return f"session {sess}"
                if r.hours and hour not in r.hours:
                    return f"ny hour {hour}"
        if r.model_path:
            m = self._model(r.model_path)
            feats = d.get("feats") or {**d.get("features", {}), **d.get("context", {})}
            if m is None or not feats:
                return "model features missing"
            z = max(top - bottom, 0.01)
            feats = {**feats, "zone_usd": z, "cost_r_est": (self.spread_estimate + self.commission_oz) / z}
            p = m.score(str(d.get("type", "")), feats)
            d["filter_score"] = round(float(p), 4)
            if p < r.model_min:
                return f"filter score {p:.3f} < {r.model_min}"
        return None
