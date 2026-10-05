#!/usr/bin/env python3
"""LU-POI TRADER - live MT5 trading bot (v7).

    python trader.py [--symbol XAUUSD.t] [--risk 1.0] [--min-quality 0.5] [--timeframes M5,M10,M15,M30,H1]
                     [--dry-run] [--once] [--state trader_state.json] [--log trader.log]

NO login option: the bot attaches to the MetaTrader 5 terminal that is already open and logged
in on this Windows PC (``mt5.initialize()`` without credentials).  Keep the terminal running.

What it does every minute (after the M1 bar closes):
  1. pulls the M1 history from the terminal, rebuilds M5/M10/M15/M30/H1 and runs the v6 POI scanner
     (quality model) exactly like `bot.py scan` -> two POIs per timeframe (above / below);
  2. for every newly shown POI: BUY LIMIT at the top of a bullish zone / SELL LIMIT at the bottom of a
     bearish zone, SL at the far edge of the zone, position sized to ``risk_pct`` % of equity.
     Hedging account -> two half-size legs: leg A TP = +0.4R, leg B TP = +1.5R (server-side).
     Netting account -> one order with TP = +1.5R; the bot closes half at market when +0.4R is touched;
  3. POIs no longer shown -> their pending orders are cancelled (mirror policy);
  4. management: when leg A has been closed (TP1) the SL of leg B is moved to break-even;
  5. all state (plans, tickets) is persisted to ``--state`` after every action, and on start-up the bot
     re-adopts its own orders / positions from the terminal (magic number), so a crash / restart is safe.

Server-side SL/TP protect every position even if this script or the PC dies (only the BE move needs
the bot).  ``--dry-run`` prints every order it would send without trading.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

from lubot import MultiTimeframeScanner, StrategyConfig
from lubot.config import TIMEFRAME_MINUTES
from lubot.execution import BUY, SELL, SymbolSpec, TradePlan, TraderConfig, apply_mart_ladder, grid_deep_plan, size_plan
from lubot.martingale import Martingale, grid_wanted
from lubot.trade_filter import TradeFilter

#: v8 recommended filter (study_results/TRADER_V8.md): M5 only when the spread+commission is <= 8 % of 1R, quality >= 0.55
#: and the selection is not made 13:00-17:00 New York; the other timeframes at quality >= 0.60.
V8_FILTER = "M5:max_cost_r=0.08;min_quality=0.55;sessions=asia|london|preny|ny|lclose/M10|M15|M30|H1:min_quality=0.60"

MAGIC_BASE = 770_000


def setup_logging(path: Optional[str]) -> logging.Logger:
    log = logging.getLogger("trader")
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(fmt)
    log.addHandler(h)
    if path:
        fh = logging.FileHandler(path, encoding="utf-8")
        fh.setFormatter(fmt)
        log.addHandler(fh)
    return log


# ----------------------------------------------------------------------------- state
class State:
    """Crash-safe JSON state: plans keyed by "TF#poi_id" with their broker tickets."""

    def __init__(self, path: str):
        self.path = Path(path)
        self.plans: Dict[str, dict] = {}
        self.traded: set = set()
        # v10 account protection (persisted so a restart cannot reset the limits)
        self.risk: Dict[str, object] = {"start_balance": None, "day": None, "day_start_equity": None,
                                        "daily_halt_day": None, "halted": False, "halt_time": None, "daily_halts": []}
        # v14: closed EDGE plans in close order [tf, net $, r_net, mart_step] - the martingale state is rebuilt from this list
        self.closed: List[list] = []
        # v15: confluence memory [tf, side, zone_top, zone_bottom, epoch seconds the plan left the books, filled]
        self.memory: List[list] = []
        self.load()

    def load(self) -> None:
        if self.path.exists():
            try:
                d = json.loads(self.path.read_text())
                self.plans = d.get("plans", {})
                self.traded = set(d.get("traded", []))
                self.risk.update(d.get("risk", {}))
                self.closed = [list(x) for x in d.get("closed", [])]
                self.memory = [list(x) for x in d.get("memory", [])]
            except Exception as e:  # noqa: BLE001
                print(f"state file unreadable ({e}) - starting fresh")

    def save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"plans": self.plans, "traded": sorted(self.traded), "risk": self.risk,
                                   "closed": self.closed[-500:], "memory": self.memory[-400:],
                                   "saved": time.strftime("%Y-%m-%d %H:%M:%S")}, indent=1, default=str))
        os.replace(tmp, self.path)


# ----------------------------------------------------------------------------- trader
class Trader:
    def __init__(self, broker, cfg: StrategyConfig, tcfg: TraderConfig, state: State, log: logging.Logger,
                 dry_run: bool = False, history_bars: int = 60_000, rebuild_every_min: int = 5,
                 commission_per_lot: float = 0.0):
        self.b = broker
        self.cfg = cfg
        self.t = tcfg
        self.state = state
        self.log = log
        self.dry = dry_run
        self.history_bars = history_bars
        self.rebuild_every = rebuild_every_min
        self.spec: SymbolSpec = broker.spec(commission_per_lot)
        self.magic = MAGIC_BASE + (abs(hash(self.spec.symbol)) % 1000)
        self.hedging = getattr(broker, "hedging", True)
        self.mode = "split" if self.hedging else "netting"
        self.t.exec_mode = self.mode
        self.m1: Optional[pd.DataFrame] = None
        self.last_result: Dict[str, dict] = {}
        self.last_rebuild_bar: Optional[pd.Timestamp] = None
        # v8: per-timeframe trade filter (same rules / same code as the backtest)
        self.filter = TradeFilter.parse(self.t.trade_filter, commission_oz=self.spec.commission_per_lot / self.spec.contract_size,
                                        server_minus_ny_hours=cfg.server_minus_ny_hours if cfg.server_minus_ny_hours is not None else 7.0)
        self.log.info(f"trade filter: {self.filter.describe()}")
        # v12: alternative filter for confluence plans (zone active on another timeframe) - same code as the simulator
        self.conf_filter: Optional[TradeFilter] = TradeFilter.parse(
            self.t.confluence_filter, commission_oz=self.spec.commission_per_lot / self.spec.contract_size,
            server_minus_ny_hours=cfg.server_minus_ny_hours if cfg.server_minus_ny_hours is not None else 7.0) \
            if self.t.confluence_filter else None
        if self.conf_filter is not None:
            self.log.info(f"confluence filter: {self.conf_filter.describe()}")
        # v15: second-tier filter + conviction sizing + confluence memory (same code path as the simulator)
        self.tier_filter: Optional[TradeFilter] = TradeFilter.parse(
            self.t.tier_filter, commission_oz=self.spec.commission_per_lot / self.spec.contract_size,
            server_minus_ny_hours=cfg.server_minus_ny_hours if cfg.server_minus_ny_hours is not None else 7.0) \
            if self.t.tier_filter else None
        if self.tier_filter is not None:
            self.log.info(f"tier filter (x{self.t.tier_risk_scale}): {self.tier_filter.describe()}")
        if self.t.confluent_risk_scale != 1.0 or self.t.plain_risk_scale != 1.0:
            self.log.info(f"conviction sizing: confluent x{self.t.confluent_risk_scale}, plain x{self.t.plain_risk_scale}")
        if self.t.confluence_memory_min > 0:
            self.log.info(f"confluence memory: {self.t.confluence_memory_min} min ({self.t.confluence_memory_kind}); "
                          f"{len(self.state.memory)} entries restored")
        if self.t.keep_replaced_bars > 0:
            self.log.info(f"keep replaced orders: {self.t.keep_replaced_bars} bars of their timeframe "
                          f"({'|'.join(self.t.keep_replaced_tfs) or 'all TFs'})")
        if self.t.regime_metric:
            self.log.info(f"v13 regime: {self.t.regime_metric}({self.t.regime_short}/{self.t.regime_long}) < {self.t.regime_threshold} "
                          f"-> range management: ladder {'|'.join(self.t.range_tp_levels) or 'same'} fracs "
                          f"{'|'.join(self.t.range_tp_fracs) or 'equal'} sl_after_leg {'|'.join(self.t.range_sl_after_leg) or 'same'} "
                          f"risk x{self.t.range_risk_scale} ({'|'.join(self.t.range_tfs) or 'all TFs'})")
        self.regime_value: float = float("nan")
        self.regime: str = ""
        # v14: martingale state rebuilt from the persisted closed-plan list (same code as the simulator)
        self.mart = Martingale.replay(self.t, self.state.closed)
        if self.t.mart_mode:
            self.log.info(f"v14 martingale: mode {self.t.mart_mode} mult {self.t.mart_mult} steps <= {self.t.mart_max_steps} "
                          f"risk <= {self.t.mart_max_risk_pct} % scope {self.t.mart_scope} gates tfs {'|'.join(self.t.mart_tfs) or 'all'} "
                          f"sides {'|'.join(self.t.mart_sides) or 'all'} q>={self.t.mart_min_quality} regime {self.t.mart_regime or 'any'} "
                          f"ungated x{self.t.mart_ungated_scale} | state {self.mart.snapshot()} ({len(self.state.closed)} closed plans)")
        if self.t.grid_add_r > 0:
            self.log.info(f"v14 zone grid: deep leg at {self.t.grid_add_r} R into the zone, budget edge {self.t.grid_base_frac} / deep "
                          f"{self.t.grid_add_frac}, ladder {self.t.grid_deep_ladder}, cancel on partial {self.t.grid_cancel_on_partial} "
                          f"({'|'.join(self.t.grid_tfs) or 'all TFs'}, regime {self.t.grid_regime or 'any'})")
        self.log.info(f"symbol {self.spec.symbol} digits {self.spec.digits} contract {self.spec.contract_size} "
                      f"vol {self.spec.volume_min}-{self.spec.volume_max} step {self.spec.volume_step} | account "
                      f"{'HEDGING' if self.hedging else 'NETTING'} -> exec_mode {self.mode} | magic {self.magic} | "
                      f"{'DRY RUN' if dry_run else 'LIVE'}")

    # ------------------------------------------------------------------ data
    def refresh_history(self) -> None:
        if self.m1 is None:
            self.m1 = self.b.m1_history(self.history_bars)
            self.log.info(f"history {len(self.m1)} M1 bars {self.m1.index[0]} -> {self.m1.index[-1]}")
        else:
            fresh = self.b.m1_since(self.m1.index[-1] - pd.Timedelta(days=2))
            if len(fresh):
                self.m1 = pd.concat([self.m1[self.m1.index < fresh.index[0]], fresh])
                self.m1 = self.m1.iloc[-self.history_bars:]

    def current_regime(self) -> str:
        """v13: 'range' | 'trend' from the CLOSED server days of the M1 history ('' when the lever is off).
        Same code as the simulator (lubot/regime.py); the unfinished current day is excluded."""
        if not self.t.regime_metric or self.m1 is None:
            return ""
        from lubot.regime import daily_bars, latest_metric, regime_of
        d = daily_bars(self.m1)
        v = latest_metric(d, self.t.regime_metric, self.t.regime_short, self.t.regime_long)
        r = regime_of(v, self.t.regime_threshold)
        if r != self.regime:
            self.log.info(f"regime -> {r} ({self.t.regime_metric} = {v:.3f}, threshold {self.t.regime_threshold})")
        self.regime_value, self.regime = v, r
        return r

    def scan(self) -> Dict[str, dict]:
        """Run the scanner on the closed bars.  The last M1 bar returned by MT5 is the FORMING one -> drop it."""
        m1 = self.m1
        # the last bar is still forming if its open minute == current server minute
        tick = self.b.price()
        now_server = pd.Timestamp(tick["time"], unit="s")
        closed = m1[m1.index + pd.Timedelta(minutes=1) <= now_server.floor("min")]
        ohlc = closed[["open", "high", "low", "close", "volume"]]
        scanner = MultiTimeframeScanner(ohlc, self.cfg)
        res = scanner.scan(price=(tick["bid"] + tick["ask"]) / 2.0)
        return res

    # ------------------------------------------------------------------ sync with terminal
    def adopt(self) -> None:
        """Re-attach state to the broker's orders / positions (after restart)."""
        orders = {o.ticket: o for o in self.b.orders(self.magic)}
        poss = {p.ticket: p for p in self.b.positions(self.magic)}
        for key, pl in list(self.state.plans.items()):
            pl["order_tickets"] = [t for t in pl.get("order_tickets", []) if t in orders]
            pl["position_tickets"] = [t for t in pl.get("position_tickets", []) if t in poss]
            # orders that got filled turn into positions with the same comment
            for tk, p in poss.items():
                if p.comment == pl["comment"] and tk not in pl["position_tickets"]:
                    pl["position_tickets"].append(tk)
            if not pl["order_tickets"] and not pl["position_tickets"]:
                self.log.info(f"plan {key} finished (no orders/positions left)")
                self._remember(pl)
                self.state.plans.pop(key)
        # orphans with our magic but unknown to the state (state file lost): adopt by comment
        known = {t for pl in self.state.plans.values() for t in pl.get("order_tickets", []) + pl.get("position_tickets", [])}
        for tk, o in orders.items():
            if tk not in known:
                self.log.warning(f"orphan pending order #{tk} {o.comment} -> cancelling")
                self._cancel(tk)
        for tk, p in poss.items():
            if tk not in known:
                self.log.warning(f"orphan position #{tk} {p.comment} - adopting with its current SL/TP")
                self.state.plans[f"orphan#{tk}"] = {"comment": p.comment, "side": p.side, "entry": p.price_open,
                                                     "sl": p.sl, "tp1": None, "tp2": p.tp, "be_price": p.price_open,
                                                     "risk": abs(p.price_open - p.sl) if p.sl else 0.0,
                                                     "order_tickets": [], "position_tickets": [tk], "partial_done": True,
                                                     "tf": "", "poi_id": -1, "key": f"orphan#{tk}"}
        self.state.save()

    # ------------------------------------------------------------------ order actions
    def _cancel(self, ticket: int) -> bool:
        if self.dry:
            self.log.info(f"[dry] cancel order #{ticket}")
            return True
        return self.b.cancel_order(ticket)

    def _place(self, plan: TradePlan, volume: float, tp: float, tag: str) -> Optional[int]:
        if self.dry:
            self.log.info(f"[dry] {plan.side.upper()} LIMIT {volume} @ {plan.entry} sl {plan.sl} tp {tp}  {plan.comment}{tag}")
            return -int(time.time() * 1000) % 10 ** 9
        return self.b.place_limit(plan.side, volume, plan.entry, plan.sl, tp, self.magic, plan.comment + tag)

    def _modify(self, ticket: int, sl: float, tp: float) -> bool:
        if self.dry:
            self.log.info(f"[dry] modify #{ticket} sl {sl} tp {tp}")
            return True
        return self.b.modify_position(ticket, sl, tp)

    def _close_partial(self, pos, volume: float) -> bool:
        if self.dry:
            self.log.info(f"[dry] close {volume} of #{pos.ticket}")
            return True
        return self.b.close_position(pos, volume, "LU partial")

    # ------------------------------------------------------------------ decision
    def _accept(self, plan: TradePlan) -> Optional[str]:
        t = self.t
        if plan.key in self.state.plans:
            return "active"
        if self.state.risk.get("halted"):
            return "HALTED (total loss limit)"
        if self.state.risk.get("daily_halt_day") is not None:
            return "daily loss limit reached - no new trades today"
        if t.one_trade_per_poi and plan.key in self.state.traded:
            return "already traded"
        if t.grades and plan.grade not in t.grades:
            return "grade"
        if t.min_quality is not None and not (plan.quality >= t.min_quality):
            return "quality"
        if t.sides and plan.side not in t.sides:
            return "side"
        n_pos = len({k for k, pl in self.state.plans.items() if pl.get("position_tickets") and not pl.get("grid_leg")})
        n_pend = len({k for k, pl in self.state.plans.items() if pl.get("order_tickets") and not pl.get("position_tickets")
                      and not pl.get("grid_leg")})
        if n_pend >= t.max_pending_orders:
            return "max pending"
        for pl in self.state.plans.values():
            if pl.get("grid_leg"):
                continue                                     # v14: the deep leg belongs to its edge plan
            if pl.get("side") == plan.side and pl.get("zone_top") is not None:
                # v11 dedupe_cross_tf=false: a level shown on another timeframe (confluence) may be traded as well
                if not t.dedupe_cross_tf and pl.get("tf") and pl.get("tf") != plan.tf:
                    continue
                other = TradePlan(side=pl["side"], entry=pl["entry"], sl=pl["sl"], tp1=pl["tp1"] or pl["entry"], tp2=pl["tp2"],
                                  be_price=pl["be_price"], risk=pl["risk"], zone_top=pl["zone_top"], zone_bottom=pl["zone_bottom"])
                if plan.overlaps(other) >= t.dedupe_overlap:
                    return "overlaps active plan"
        px = self.b.price()
        if (plan.is_buy and px["ask"] <= plan.entry) or (not plan.is_buy and px["bid"] >= plan.entry):
            return "price already at/through entry"
        # broker minimum stop distance
        min_dist = self.spec.stops_level_points * self.spec.point
        if min_dist and (abs(plan.entry - plan.sl) < min_dist or abs(plan.entry - plan.tp1) < min_dist):
            return "inside broker stops level"
        return None

    def _confluent_other_tf(self, plan: TradePlan) -> bool:
        """v12: the plan's zone overlaps (>= dedupe_overlap) an active plan (order or position, same side) of ANOTHER TF.
        v15 ``confluence_memory_min``: a plan of another TF that left the books within the last N minutes counts too."""
        for pl in self.state.plans.values():
            if pl.get("grid_leg") or pl.get("side") != plan.side or pl.get("zone_top") is None or not pl.get("tf") or pl.get("tf") == plan.tf:
                continue
            other = TradePlan(side=pl["side"], entry=pl["entry"], sl=pl["sl"], tp1=pl["tp1"] or pl["entry"], tp2=pl["tp2"],
                              be_price=pl["be_price"], risk=pl["risk"], zone_top=pl["zone_top"], zone_bottom=pl["zone_bottom"])
            if plan.overlaps(other) >= self.t.dedupe_overlap:
                return True
        if self.t.confluence_memory_min > 0:
            now = time.time()
            h = max(plan.zone_top - plan.zone_bottom, 1e-9)
            for tf, side, top, bottom, last, filled in self.state.memory:
                if side != plan.side or tf == plan.tf or now - float(last) > self.t.confluence_memory_min * 60:
                    continue
                if self.t.confluence_memory_kind == "open" and not filled:
                    continue
                if self.t.confluence_memory_kind == "pending" and filled:
                    continue
                inter = min(plan.zone_top, float(top)) - max(plan.zone_bottom, float(bottom))
                if inter > 0 and inter / h >= self.t.dedupe_overlap:
                    return True
        return False

    def _remember(self, pl: dict) -> None:
        """v15 confluence memory: a plan record leaves the state (order cancelled / position closed)."""
        if self.t.confluence_memory_min <= 0 or pl.get("grid_leg") or pl.get("zone_top") is None or not pl.get("tf"):
            return
        filled = bool(pl.get("position_tickets") or pl.get("all_position_tickets"))
        self.state.memory.append([pl["tf"], pl["side"], pl["zone_top"], pl["zone_bottom"], time.time(), filled])
        keep = time.time() - self.t.confluence_memory_min * 60
        self.state.memory = [m for m in self.state.memory if float(m[4]) >= keep][-400:]

    def on_selection(self, result: Dict[str, dict]) -> None:
        shown_keys = set()
        slot_shown: Dict[Tuple[str, str], str] = {}          # (tf, side) -> key shown now (v12 keep_replaced)
        regime = self.current_regime()                        # v13
        for tf, r in result.items():
            for side in ("above", "below"):
                d = r.get(side)
                if not d:
                    continue
                d = dict(d)
                d["tf"] = tf
                key = f"{tf}#{d['id']}"
                shown_keys.add(key)
                slot_shown[(tf, BUY if side == "below" else SELL)] = key
                plan = TradePlan.from_poi(d, self.t, self.spec, selected_time=r.get("time", ""), regime=regime)
                if plan is None:
                    continue
                if plan.regime == "range" and self.t.range_risk_scale <= 0:
                    self.log.debug(f"skip {key}: range regime (no trading)")
                    continue
                why = self._accept(plan)
                if why == "active":
                    # v12: a kept (replaced) order that is shown again is kept for good
                    pl = self.state.plans.get(key)
                    if pl is not None and pl.get("keep_until"):
                        pl.pop("keep_until", None)
                        self.state.save()
                        self.log.info(f"{key} shown again -> kept order is live again")
                    continue
                if why:
                    self.log.debug(f"skip {key}: {why}")
                    continue
                # v8 trade filter with the live spread (ask - bid) at decision time
                # (v12: a confluence plan - same level active on another TF - is judged by the confluence filter instead)
                px = self.b.price()
                flt = self.filter
                if self.conf_filter is not None and self._confluent_other_tf(plan):
                    flt = self.conf_filter
                    plan.confluent = True
                why = flt.check(d, tf, spread=px["ask"] - px["bid"], when=r.get("time") or None)
                if why:
                    # v15 tiered admission: failed the normal bar but passes the tier bar -> trade it smaller
                    if self.tier_filter is not None and self.tier_filter.rule_for(tf) is not None and \
                            self.tier_filter.check(d, tf, spread=px["ask"] - px["bid"], when=r.get("time") or None) is None:
                        plan.tier = True
                        self.log.info(f"tier {key}: {why} -> admitted at x{self.t.tier_risk_scale}")
                    else:
                        self.log.info(f"filter {key}: {why}")
                        continue
                # v15 conviction / tier sizing (same arithmetic as PortfolioSimulator._apply_v15)
                rs = plan.risk_scale if plan.risk_scale > 0 else 1.0
                rs *= self.t.tier_risk_scale if plan.tier else (self.t.confluent_risk_scale if plan.confluent else self.t.plain_risk_scale)
                plan.risk_scale = rs
                self.open_plan(plan)
        # mirror policy: cancel pending orders of POIs no longer shown (positions are never touched)
        if self.t.order_policy == "mirror":
            now = time.time()
            for key, pl in list(self.state.plans.items()):
                if key.startswith("orphan"):
                    continue
                if pl.get("grid_leg"):
                    # v14: the deep order follows its edge plan - cancelled when the edge order is cancelled (below) or the edge closes
                    if pl["grid_parent"] not in self.state.plans and pl.get("order_tickets") and not pl.get("position_tickets"):
                        self._cancel_deep(pl["grid_parent"], "edge plan gone")
                    continue
                if key not in shown_keys and pl.get("order_tickets") and not pl.get("position_tickets"):
                    # v12 keep_replaced_bars: the POI was REPLACED by another one on its slot (the slot is still shown) ->
                    # keep the order for N bars of its TF; a cleared slot ('no longer shown') cancels at once
                    slot_key = slot_shown.get((pl.get("tf", ""), pl.get("side", "")))
                    replaced = slot_key is not None and slot_key != key
                    keep_tf = not self.t.keep_replaced_tfs or pl.get("tf") in self.t.keep_replaced_tfs
                    if replaced and self.t.keep_replaced_bars > 0 and keep_tf:
                        if not pl.get("keep_until"):
                            pl["keep_until"] = now + self.t.keep_replaced_bars * TIMEFRAME_MINUTES.get(pl.get("tf", ""), 5) * 60
                            self.state.save()
                            self.log.info(f"{key} replaced on its slot -> order kept for {self.t.keep_replaced_bars} bars")
                            continue
                        if now < pl["keep_until"]:
                            continue
                        reason = "replaced (keep window over)"
                    else:
                        reason = "no longer shown"
                    self.log.info(f"{key} {reason} -> cancel pending {pl['order_tickets']}")
                    for tk in pl["order_tickets"]:
                        self._cancel(tk)
                    pl["order_tickets"] = []
                    self._remember(pl)
                    self.state.plans.pop(key)
                    self._cancel_deep(key, reason)
                    self.state.save()

    def open_plan(self, plan: TradePlan) -> None:
        equity = self.b.equity if self.t.size_on == "equity" else self.b.balance
        # v14: sequence sizing (streak from the closed-plan list) + the edge leg's share of the budget when a deep leg follows
        if self.mart.on and not plan.grid_leg:
            m, step = self.mart.scale(plan, equity)
            if step > 0 and (plan.tier or (self.t.mart_confluent_only and not plan.confluent)):
                m, step = 1.0, 0            # v15: tier plans / plain plans (with the gate) are never stepped up
            plan.mart_scale, plan.mart_step = m, step
            apply_mart_ladder(plan, self.t, self.spec)
            if step:
                self.log.info(f"{plan.key}: martingale step {step} -> risk x{m:.3f} (state {self.mart.snapshot()})")
        deep_after = grid_wanted(plan, self.t)
        if deep_after:
            plan.risk_scale = (plan.risk_scale if plan.risk_scale > 0 else 1.0) * self.t.grid_base_frac
        if not self._open_plan_orders(plan, equity):
            return
        if deep_after:
            deep = grid_deep_plan(plan, self.t, self.spec)
            if deep is not None:
                deep.mart_scale, deep.mart_step = plan.mart_scale, plan.mart_step
                self._open_plan_orders(deep, equity)

    def _open_plan_orders(self, plan: TradePlan, equity: float) -> bool:
        sz = size_plan(plan, equity, self.t, self.spec)
        if not sz.ok:
            self.log.info(f"skip {plan.key}: {sz.reason}")
            return False
        need = self.spec.margin_required(sz.lots_total, plan.entry)
        free = float(getattr(self.b.refresh_account(), "margin_free", equity))
        if need > free * self.t.margin_buffer:
            self.log.info(f"skip {plan.key}: margin {need:.0f} > free {free:.0f} x {self.t.margin_buffer}")
            return False
        tickets = []
        ladder_legs: List[dict] = []
        if self.mode == "split" and len(plan.tps) > 2 and sz.lots_legs:
            # v10 multi-TP ladder: one limit leg per target (server-side TP), all with the zone SL.  Legs merged away by
            # ladder_fallback=merge have volume 0 and are not sent.
            for i, (vol, tp) in enumerate(zip(sz.lots_legs, plan.tps)):
                if vol <= 0:
                    continue
                tk = self._place(plan, vol, tp, f" L{i + 1}")
                if tk is None:
                    self.log.error(f"{plan.key}: ladder leg {i + 1} rejected -> cancelling the legs already placed")
                    for tk2 in tickets:
                        self._cancel(tk2)
                    return False
                tickets.append(tk)
                ladder_legs.append({"idx": i, "ticket": tk, "tp": tp, "vol": vol, "closed": False})
        elif self.mode == "split":
            t1 = self._place(plan, sz.lots_leg1, plan.tp1, " A")
            t2 = self._place(plan, sz.lots_leg2, plan.tp2, " B")
            tickets = [t for t in (t1, t2) if t is not None]
            if len(tickets) == 1:      # one leg rejected -> do not leave a half plan
                self.log.error(f"{plan.key}: only one leg accepted -> cancelling it")
                self._cancel(tickets[0])
                return False
        else:
            t1 = self._place(plan, sz.lots_total, plan.tp2, "")
            tickets = [t1] if t1 is not None else []
        if not tickets:
            self.log.error(f"{plan.key}: order placement failed")
            return False
        rec = plan.to_dict()
        rec.update(key=plan.key, comment=plan.comment, order_tickets=tickets, position_tickets=[], partial_done=False,
                   leg_a_ticket=tickets[0] if (self.mode == "split" and not ladder_legs) else None,
                   leg_b_ticket=(tickets[1] if self.mode == "split" else tickets[0]) if not ladder_legs else None,
                   ladder=ladder_legs, n_closed=0,
                   lots_total=sz.lots_total, lots_leg1=sz.lots_leg1, lots_leg2=sz.lots_leg2, risk_money=sz.risk_money,
                   placed=time.strftime("%Y-%m-%d %H:%M:%S"))
        self.state.plans[plan.key] = rec
        self.state.traded.add(plan.key)
        self.state.save()
        self.log.info(f"NEW {plan.side.upper()} LIMIT {plan.tf} {plan.kind} #{plan.poi_id}{' DEEP' if plan.grid_leg else ''} "
                      f"{sz.lots_total} lots @ {plan.entry} {('[' + plan.regime + '] ') if plan.regime else ''}"
                      f"{('[mart ' + str(plan.mart_step) + ' x' + format(plan.mart_scale, '.2f') + '] ') if plan.mart_step else ''}"
                      f"sl {plan.sl} tp1 {plan.tp1} tp2 {plan.tp2} (1R={plan.risk:.2f}, risk ${sz.risk_money:.0f}, "
                      f"P={plan.quality:.2f} {plan.grade}) tickets {tickets}")
        return True

    # ------------------------------------------------------------------ management
    # ------------------------------------------------------------------ v10 account protection
    def _server_day(self) -> str:
        """Server date (YYYY-MM-DD) of the current tick - the broker's trading day."""
        tk = self.b.tick() if hasattr(self.b, "tick") else None
        ts = getattr(tk, "time", None)
        return time.strftime("%Y-%m-%d", time.gmtime(ts)) if ts else time.strftime("%Y-%m-%d", time.gmtime())

    def _flatten(self, reason: str) -> None:
        """Cancel every pending order and close every position of this bot (all plans)."""
        for o in self.b.orders(self.magic):
            self._cancel(o.ticket)
        for p in self.b.positions(self.magic):
            if self.dry:
                self.log.info(f"[dry] close #{p.ticket} ({reason})")
            else:
                self.b.close_position(p, None, f"LU {reason}")
        for key, pl in list(self.state.plans.items()):
            pl["order_tickets"] = []
            pl["position_tickets"] = []
            self.state.plans.pop(key)

    def check_risk_limits(self) -> bool:
        """Daily / total loss limits (TraderConfig.max_daily_loss_pct / max_total_loss_pct, 0 = off).
        Equity = balance + floating P/L from the terminal.  Returns True when trading is allowed this loop."""
        t, rk = self.t, self.state.risk
        if not (t.max_daily_loss_pct > 0 or t.max_total_loss_pct > 0):
            return True
        acc = self.b.refresh_account()
        equity, balance = float(acc.equity), float(acc.balance)
        changed = False
        if rk.get("start_balance") is None:
            rk["start_balance"] = balance
            changed = True
        day = self._server_day()
        if rk.get("day") != day:
            rk["day"] = day
            rk["day_start_equity"] = equity
            if rk.get("daily_halt_day") is not None:
                self.log.info(f"new server day {day}: daily loss limit reset")
            rk["daily_halt_day"] = None
            changed = True
        if rk.get("halted"):
            if changed:
                self.state.save()
            return False
        if t.max_total_loss_pct > 0 and equity <= float(rk["start_balance"]) * (1.0 - t.max_total_loss_pct / 100.0):
            self.log.error(f"TOTAL LOSS LIMIT: equity {equity:.2f} <= {100 - t.max_total_loss_pct:.1f} % of start balance "
                           f"{float(rk['start_balance']):.2f} -> closing everything and HALTING the bot for good")
            self._flatten("total loss limit")
            rk["halted"] = True
            rk["halt_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
            self.state.save()
            return False
        if t.max_daily_loss_pct > 0 and rk.get("daily_halt_day") is None and \
                equity <= float(rk["day_start_equity"]) * (1.0 - t.max_daily_loss_pct / 100.0):
            self.log.error(f"DAILY LOSS LIMIT: equity {equity:.2f} <= {100 - t.max_daily_loss_pct:.1f} % of day-start equity "
                           f"{float(rk['day_start_equity']):.2f} -> closing everything, no new trades until the next server day")
            self._flatten("daily loss limit")
            rk["daily_halt_day"] = day
            rk["daily_halts"] = list(rk.get("daily_halts", [])) + [time.strftime("%Y-%m-%d %H:%M:%S")]
            self.state.save()
            return False
        if changed:
            self.state.save()
        return rk.get("daily_halt_day") is None

    def manage(self) -> None:
        """Runs every loop: detect fills, move to break-even after TP1, netting partial close, clean up."""
        orders = {o.ticket: o for o in self.b.orders(self.magic)}
        poss = {p.ticket: p for p in self.b.positions(self.magic)}
        by_comment: Dict[str, List] = {}
        for p in poss.values():
            by_comment.setdefault(p.comment, []).append(p)
        changed = False
        for key, pl in list(self.state.plans.items()):
            # 1) orders -> positions (fills).  MT5: the position ticket == the ticket of the pending order
            #    that opened it; fall back to matching the order comment.
            still = [t for t in pl["order_tickets"] if t in orders]
            for t in pl["order_tickets"]:
                if t in orders:
                    continue
                if t in poss and t not in pl["position_tickets"]:
                    pl["position_tickets"].append(t)
                    pl.setdefault("all_position_tickets", []).append(t)      # v14: kept for the realised P&L lookup
                    self.log.info(f"{key}: order #{t} FILLED @ {poss[t].price_open}")
                    changed = True
                elif t not in poss:
                    tag = " A" if t == pl.get("leg_a_ticket") else " B" if t == pl.get("leg_b_ticket") else ""
                    for p in by_comment.get(pl["comment"] + tag, []):
                        if p.ticket not in pl["position_tickets"]:
                            pl["position_tickets"].append(p.ticket)
                            pl.setdefault("all_position_tickets", []).append(p.ticket)
                            self.log.info(f"{key}: order #{t} FILLED -> position #{p.ticket} @ {p.price_open}")
                            changed = True
            pl["order_tickets"] = still
            open_pos = [poss[t] for t in pl["position_tickets"] if t in poss]
            pl["position_tickets"] = [p.ticket for p in open_pos]
            # 2a) v10 ladder (3+ legs): stop schedule for the remaining legs after every closed target leg
            if pl.get("ladder") and open_pos:
                if self._manage_ladder(key, pl, orders, poss, open_pos):
                    changed = True
            # 2) break-even after TP1
            elif open_pos and not pl.get("partial_done"):
                if self.mode == "split":
                    leg_a = pl.get("leg_a_ticket")
                    leg_a_alive = leg_a in orders or leg_a in poss
                    leg_a_pos = poss.get(leg_a)
                    if leg_a_pos is not None:
                        pl["leg_a_seen"] = True
                    if leg_a is not None and not leg_a_alive and (pl.get("leg_a_seen") or leg_a not in pl["order_tickets"]):
                        # leg A is gone while leg B is still open -> leg A closed by its TP1 (a stop would have
                        # taken both legs at the same price) -> move leg B to break-even
                        for p in open_pos:
                            if abs(p.sl - pl["be_price"]) > self.spec.point / 2:
                                ok = self._modify(p.ticket, pl["be_price"], p.tp)
                                self.log.info(f"{key}: leg A closed (TP1) -> leg B #{p.ticket} SL -> BE {pl['be_price']} ({'ok' if ok else 'FAILED'})")
                                if not ok:
                                    continue
                        pl["partial_done"] = True
                        changed = True
                else:
                    px = self.b.price()
                    ref = px["bid"] if pl["side"] == BUY else px["ask"]
                    touched = (ref >= pl["tp1"]) if pl["side"] == BUY else (ref <= pl["tp1"])
                    if touched:
                        for p in open_pos:
                            part = self.spec.round_volume_down(p.volume * self.t.partial_frac)
                            if part >= self.spec.volume_min and p.volume - part >= self.spec.volume_min - 1e-9:
                                ok = self._close_partial(p, part)
                                self.log.info(f"{key}: TP1 touched -> closed {part} of #{p.ticket} ({'ok' if ok else 'FAILED'})")
                            ok2 = self._modify(p.ticket, pl["be_price"], p.tp)
                            self.log.info(f"{key}: SL -> BE {pl['be_price']} ({'ok' if ok2 else 'FAILED'})")
                        pl["partial_done"] = True
                        changed = True
            # 2b) v14 grid: the deep order is withdrawn once the edge leg has taken its first partial
            if pl.get("partial_done") and not pl.get("grid_leg") and self.t.grid_add_r > 0 and self.t.grid_cancel_on_partial:
                if self._cancel_deep(key, "edge took a partial"):
                    changed = True
            # 3) finished?
            if not pl["order_tickets"] and not pl["position_tickets"]:
                self.log.info(f"{key}: all legs closed -> plan finished")
                if pl.get("grid_leg"):
                    pass                                     # the deep leg's outcome is part of the edge plan's (not counted twice)
                else:
                    self._record_closed(key, pl)
                    self._cancel_deep(key, "edge closed")
                self._remember(pl)
                self.state.plans.pop(key)
                changed = True
        if changed:
            self.state.save()

    # ------------------------------------------------------------------ v14 martingale / grid bookkeeping
    def _record_closed(self, key: str, pl: dict) -> None:
        """An EDGE plan finished: realised net $ from the broker's deal history (all its position tickets) -> closed list ->
        martingale state (same rule as the simulator: r_net = net / risk_money; BE exits are neutral)."""
        if not self.mart.on:
            return
        tickets = pl.get("all_position_tickets") or []
        net = 0.0
        known = False
        for tk in tickets:
            v = self.b.position_pnl(tk) if hasattr(self.b, "position_pnl") else None
            if v is not None:
                net += v
                known = True
        if not known:
            self.log.warning(f"{key}: no deal history for tickets {tickets} -> treated as break-even for the martingale")
            net = 0.0
        rm = float(pl.get("risk_money") or 0.0)
        r_net = net / rm if rm > 0 else 0.0
        step = int(pl.get("mart_step") or 0)
        self.state.closed.append([pl.get("tf", ""), round(net, 2), round(r_net, 4), step])
        self.mart.on_close(pl.get("tf", ""), net, r_net, step)
        self.log.info(f"{key}: closed net {net:+.2f} $ ({r_net:+.2f} R, step {step}) -> martingale state {self.mart.snapshot()}")

    def _cancel_deep(self, edge_key: str, reason: str) -> bool:
        """Cancel the pending deep order of ``edge_key`` (a deep leg that is already a position is left alone)."""
        dk = edge_key + "+g"
        pl = self.state.plans.get(dk)
        if pl is None or pl.get("position_tickets") or not pl.get("order_tickets"):
            return False
        self.log.info(f"{dk}: {reason} -> cancel deep order {pl['order_tickets']}")
        for tk in pl["order_tickets"]:
            self._cancel(tk)
        pl["order_tickets"] = []
        self.state.plans.pop(dk, None)
        return True

    def _manage_ladder(self, key: str, pl: dict, orders: dict, poss: dict, open_pos: list) -> bool:
        """v10 N-leg ladder: a leg whose ticket is neither a pending order nor an open position while OTHER legs are still
        open was closed by its server-side TP (a stop takes every leg at once).  For every newly closed target leg apply
        the stop schedule to the remaining legs: ``sl_after_leg`` (per-leg R offsets, 'x' = leave, 0 = BE) if set, else
        classic BE after the first closed leg (``be_on_partial``) and ``ratchet_sl`` (stop -> previous target).
        Same rules as ``lubot/portfolio_sim.py``.  Returns True when the state changed."""
        t = self.t
        changed = False
        buy = pl["side"] == BUY
        sgn = 1.0 if buy else -1.0
        for leg in pl["ladder"]:
            if leg["closed"]:
                continue
            tk = leg["ticket"]
            if tk in orders:
                continue
            if tk in poss:
                leg["seen"] = True
                continue
            if not leg.get("seen") and tk in pl.get("order_tickets", []):
                continue
            # gone while other legs are open -> closed by its TP
            leg["closed"] = True
            pl["n_closed"] = int(pl.get("n_closed", 0)) + 1
            k = leg["idx"]
            new_sl = None
            sl_after_leg = tuple(pl.get("sl_after_leg") or ()) or t.sl_after_leg     # v13: range plans carry their own schedule
            if sl_after_leg:
                spec_k = sl_after_leg[k] if k < len(sl_after_leg) else "x"
                if str(spec_k).lower() not in ("x", "", "none"):
                    new_sl = pl["be_price"] if abs(float(spec_k)) < 1e-12 else \
                        self.spec.round_price(pl["entry"] + sgn * float(spec_k) * pl["risk"])
            else:
                if pl["n_closed"] == 1 and t.be_on_partial:
                    new_sl = pl["be_price"]
                if t.ratchet_sl and pl["n_closed"] >= 2:
                    closed_tps = sorted((l["tp"] for l in pl["ladder"] if l["closed"] and l["tp"] > 0), reverse=not buy)
                    if len(closed_tps) >= 2:
                        new_sl = closed_tps[-2]
            pl["partial_done"] = True
            changed = True
            self.log.info(f"{key}: ladder leg {k + 1} closed at TP {leg['tp']} ({pl['n_closed']} of {len(pl['ladder'])})")
            if new_sl is None:
                continue
            for p in open_pos:
                better = new_sl > p.sl if buy else new_sl < p.sl
                if p.sl == 0 or better:
                    ok = self._modify(p.ticket, new_sl, p.tp)
                    self.log.info(f"{key}: leg #{p.ticket} SL {p.sl} -> {new_sl} ({'ok' if ok else 'FAILED'})")
                    if ok:
                        p.sl = new_sl
        return changed

    # ------------------------------------------------------------------ loop
    def step(self) -> None:
        if not self.check_risk_limits():
            if self.state.risk.get("halted"):
                return                                   # bot is finished; nothing else to do
        self.refresh_history()
        self.manage()
        if not self.check_risk_limits():                 # re-check with the fills detected by manage()
            return
        res = self.scan()
        self.last_result = res
        self.on_selection(res)
        self.manage()
        self.check_risk_limits()

    def status_line(self) -> str:
        px = self.b.price()
        n_pos = sum(1 for pl in self.state.plans.values() if pl.get("position_tickets"))
        n_pend = sum(1 for pl in self.state.plans.values() if pl.get("order_tickets") and not pl.get("position_tickets"))
        acc = self.b.refresh_account()
        rk = self.state.risk
        flag = " | HALTED" if rk.get("halted") else (" | daily limit hit - flat until next day" if rk.get("daily_halt_day") else "")
        rg = f" | regime {self.regime} ({self.t.regime_metric} {self.regime_value:.3f} < {self.t.regime_threshold})" if self.regime else ""   # v13
        mt = ""
        if self.mart.on:                                                                                                        # v14
            st = self.mart.snapshot()
            mt = " | mart " + " ".join(f"{k}:k{v['k']}" + (f"/def{v['deficit']:.0f}" if v['deficit'] else "") for k, v in st.items()) if st else " | mart k0"
        return (f"bid {px['bid']:.2f} ask {px['ask']:.2f} | equity {acc.equity:.2f} balance {acc.balance:.2f} | "
                f"open plans {n_pos} pending {n_pend}{rg}{mt}{flag}")


# ----------------------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbol", default="XAUUSD.t")
    ap.add_argument("--path", default=None, help="optional path to terminal64.exe (only if several terminals are installed)")
    ap.add_argument("--risk", type=float, default=1.0, help="%% of equity risked per trade (entry -> SL)")
    ap.add_argument("--min-quality", type=float, default=0.50, help="scanner min P(bounce) (0.60 = ~3 zones/day, higher hit-rate)")
    ap.add_argument("--grades", default="", help="only trade these grades, e.g. A|B ('' = all)")
    ap.add_argument("--timeframes", default="M5,M10,M15,M30,H1")
    ap.add_argument("--trader", default=None, help="TraderConfig overrides key=value,... (partial_r, tp2_r, max_open_positions, ...)")
    ap.add_argument("--max-daily-loss", type=float, default=4.5, help="%% of day-start equity: flatten + no new trades until the next server day (0 = off)")
    ap.add_argument("--max-total-loss", type=float, default=9.0, help="%% of the start balance: flatten + HALT the bot for good (0 = off)")
    ap.add_argument("--trade-filter", default=V8_FILTER,
                    help="v8 per-timeframe trade filter (lubot/trade_filter.py); '' = v7 behaviour (no filter). Default = the v8 recommendation")
    ap.add_argument("--confluence-filter", default="",
                    help="v12: filter used INSTEAD of --trade-filter when the zone is already active on another timeframe ('' = off)")
    ap.add_argument("--set", dest="overrides", default=None, help="StrategyConfig overrides key=value,...")
    ap.add_argument("--commission", type=float, default=0.0, help="round-turn commission per lot (for sizing info only)")
    ap.add_argument("--history", type=int, default=60_000)
    ap.add_argument("--state", default="trader_state.json")
    ap.add_argument("--log", default="trader.log")
    ap.add_argument("--dry-run", action="store_true", help="scan + print orders, do not trade")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--interval", type=int, default=60)
    a = ap.parse_args(argv)

    log = setup_logging(a.log)
    from lubot.mt5_broker import MT5Broker, wait_for_next_minute
    cfg = StrategyConfig(symbol=a.symbol, timeframes=tuple(x.strip() for x in a.timeframes.split(",")), min_quality=a.min_quality)
    if a.overrides:
        from bot import apply_overrides
        cfg = apply_overrides(cfg, a.overrides)
    tcfg = TraderConfig(risk_pct=a.risk, grades=tuple(g for g in a.grades.split("|") if g), trade_filter=a.trade_filter,
                        confluence_filter=a.confluence_filter, max_daily_loss_pct=a.max_daily_loss,
                        max_total_loss_pct=a.max_total_loss).override(a.trader)
    broker = MT5Broker(a.symbol, path=a.path)
    cfg.server_utc_offset_hours = broker.server_utc_offset_hours()
    log.info(f"attached to MT5: account {broker.account.login} ({broker.account.server}) {broker.account.currency} "
             f"balance {broker.account.balance:.2f} | server UTC offset {cfg.server_utc_offset_hours:+.1f}h")
    state = State(a.state)
    tr = Trader(broker, cfg, tcfg, state, log, dry_run=a.dry_run, history_bars=a.history, commission_per_lot=a.commission)
    log.info(f"account protection: daily loss limit {a.max_daily_loss} % | total loss limit {a.max_total_loss} % "
             f"(state: start balance {state.risk.get('start_balance')}, halted {state.risk.get('halted')})")
    if state.risk.get("halted"):
        log.error(f"bot is HALTED since {state.risk.get('halt_time')} (total loss limit). Delete {a.state} to reset - at your own risk.")
    tr.adopt()
    try:
        while True:
            t0 = time.time()
            try:
                tr.step()
                log.info(tr.status_line() + f" | scan {time.time() - t0:.1f}s")
                from bot import print_scan
                if a.once:
                    print_scan(tr.last_result)
            except Exception as e:  # noqa: BLE001
                log.exception(f"loop error: {e}")
            if a.once:
                break
            wait_for_next_minute(3.0)
    except KeyboardInterrupt:
        log.info("stopped by user (orders/positions stay in the terminal with their server-side SL/TP)")
    finally:
        broker.shutdown()


if __name__ == "__main__":
    main()
