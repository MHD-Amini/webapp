"""v14 - bounded, edge-aware martingale for the LU-POI trader.

Two independent families, both OFF by default (``TraderConfig`` defaults keep every v13 result byte-identical):

A. **Sequence sizing** (``mart_mode``): the risk of the NEXT plan depends on the closed plans before it.
   The state is rebuilt from the closed-trade sequence alone (``Martingale.on_close`` in close order), so the live bot
   reproduces the simulator exactly from its own closed-trade list.

   * ``mult``     risk x mart_mult^k        k = consecutive LOSSES (a plan is a loss when r_net <= -mart_loss_r; break-even
                                             exits are neutral - they neither step nor reset), reset by a win (net > 0).
                                             mart_mult < 1 = SHRINK after losses (the anti-martingale of the diagnosis).
   * ``add``      risk x (1 + (mart_mult-1) k)   d'Alembert: linear steps.
   * ``fib``      risk x fib(k)              1, 2, 3, 5, 8 ... for k = 1, 2, 3, 4, 5.
   * ``deficit``  risk = base + deficit / mart_deficit_r     recover the money lost since the last full recovery with a trade
                                             that is expected to earn ``mart_deficit_r`` R; the deficit shrinks with every win.
   * ``anti``     risk x mart_mult^w         w = consecutive WINS (grow after wins, back to base after a loss).
   Bounds: ``mart_max_steps`` (k capped), ``mart_max_risk_pct`` (the plan's risk % of equity capped), and the account rules of
   v10 (daily 4.5 %, total 9 %) stay in force.  Gates: ``mart_tfs`` / ``mart_sides`` / ``mart_min_quality`` / ``mart_regime``
   restrict the step-up to plans whose post-loss edge is positive (diagnosis: M5 and sells after a loss are negative).
   ``mart_scope=tf`` keeps one streak per timeframe instead of one for the account.
   The stepped-up (recovery) plan may use its own ladder (``mart_tp_levels`` / ``mart_tp_fracs`` / ``mart_sl_after_leg``):
   "take the money earlier" raises the probability that the recovery trade pays.

B. **Zone-averaging grid** (``grid_add_r`` > 0): a price-martingale bounded by the POI zone.  Every plan is split into the
   EDGE leg (limit at the zone edge, ``grid_base_frac`` of the risk budget) and a DEEP leg (limit ``grid_add_r`` R inside
   the zone, ``grid_add_frac`` of the budget, same stop).  The deep leg fills on 50-67 % of the plans (median MAE of the
   winners = 0.33 R) at a better price with a shorter stop -> more lots per $ risked; when ``grid_base_frac + grid_add_frac``
   < 1 a fully stopped plan loses LESS than 1 R.  The deep order lives while the edge position is open and has not taken a
   partial (``grid_cancel_on_partial``).  Implemented in ``PortfolioSimulator`` (the plan carries ``grid_leg`` / ``grid_parent``).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, Tuple

if TYPE_CHECKING:  # pragma: no cover
    from .execution import TradePlan, TraderConfig

FIB = (1.0, 2.0, 3.0, 5.0, 8.0, 13.0, 21.0, 34.0, 55.0)     # fib(k) for k = 1..9 (k = 0 -> 1)


@dataclass
class MartState:
    k: int = 0              # consecutive losses (mult/add/fib/deficit) or consecutive wins (anti)
    deficit: float = 0.0    # $ lost since the last full recovery (deficit mode)
    n_recovery: int = 0     # stepped-up plans closed since the deficit began (deficit mode safety cap)
    closed: int = 0

    def to_dict(self) -> Dict:
        return {"k": self.k, "deficit": round(self.deficit, 2), "n_recovery": self.n_recovery, "closed": self.closed}


class Martingale:
    """Sequence-sizing state machine.  Feed every closed plan in CLOSE order with ``on_close``; ask ``scale`` for the next plan."""

    def __init__(self, tcfg: "TraderConfig"):
        self.tcfg = tcfg
        self.states: Dict[str, MartState] = {}

    # ------------------------------------------------------------------ state
    @property
    def on(self) -> bool:
        return bool(self.tcfg.mart_mode)

    def _key(self, tf: str) -> str:
        return tf if self.tcfg.mart_scope == "tf" else "all"

    def state(self, tf: str) -> MartState:
        return self.states.setdefault(self._key(tf), MartState())

    def on_close(self, tf: str, net: float, r_net: float, step_used: int = 0) -> None:
        """A plan closed: ``net`` $ after costs, ``r_net`` in R of the plan's budget, ``step_used`` = the step it was sized with."""
        if not self.on:
            return
        t = self.tcfg
        st = self.state(tf)
        st.closed += 1
        loss = r_net <= -t.mart_loss_r
        win = net > 0
        if t.mart_mode == "anti":
            if win:
                st.k += 1
            elif loss:
                st.k = 0
            return
        if step_used > 0:
            st.n_recovery += 1
        if loss:
            st.k += 1
            st.deficit += -net
        elif win:
            st.k = 0
            st.deficit = max(0.0, st.deficit - net)
        if t.mart_mode == "deficit":
            if st.deficit <= 0.0 or st.n_recovery >= t.mart_max_steps:
                st.deficit, st.n_recovery = 0.0, 0        # recovered, or give up after max_steps recovery trades
        elif st.k == 0:
            st.n_recovery = 0

    # ------------------------------------------------------------------ sizing
    def gated(self, plan: "TradePlan") -> bool:
        """Does this plan qualify for a step-up?"""
        t = self.tcfg
        if t.mart_tfs and plan.tf not in t.mart_tfs:
            return False
        if t.mart_sides and plan.side not in t.mart_sides:
            return False
        if t.mart_min_quality > 0 and not (plan.quality >= t.mart_min_quality):
            return False
        if t.mart_regime and plan.regime != t.mart_regime:
            return False
        return True

    def scale(self, plan: "TradePlan", equity: float) -> Tuple[float, int]:
        """(multiplier on the plan's risk money, step) for the plan placed now.  (1.0, 0) = no change."""
        t = self.tcfg
        if not self.on:
            return 1.0, 0
        st = self.state(plan.tf)
        k = min(st.k, t.mart_max_steps)
        mode = t.mart_mode
        if not self.gated(plan):
            # asymmetric martingale: a plan that fails the gate is stepped DOWN (mart_ungated_scale < 1) while a streak is on
            in_streak = (st.deficit > 0.0) if mode == "deficit" else (k > 0)
            if in_streak and t.mart_ungated_scale != 1.0 and mode != "anti":
                return max(t.mart_ungated_scale, 0.05), -1        # step -1 marks "stepped down"
            return 1.0, 0
        if mode == "deficit":
            if st.deficit <= 0.0:
                return 1.0, 0
            base_money = equity * t.risk_pct / 100.0 * (plan.risk_scale if plan.risk_scale > 0 else 1.0)
            m = 1.0 + st.deficit / (t.mart_deficit_r * base_money) if base_money > 0 else 1.0
            step = max(1, min(st.k, t.mart_max_steps))
        elif k == 0:
            return 1.0, 0
        elif mode in ("mult", "anti"):
            m, step = t.mart_mult ** k, k
        elif mode == "add":
            m, step = 1.0 + (t.mart_mult - 1.0) * k, k
        elif mode == "fib":
            m, step = FIB[min(k, len(FIB)) - 1], k
        else:
            raise ValueError(f"unknown mart_mode {mode}")
        # cap: the plan's risk % of equity (risk_pct x risk_scale x m) <= mart_max_risk_pct
        eff = t.risk_pct * (plan.risk_scale if plan.risk_scale > 0 else 1.0)
        if t.mart_max_risk_pct > 0 and eff > 0:
            m = min(m, t.mart_max_risk_pct / eff)
        m = max(m, 0.05)          # never below 5 % of the base (anti-martingale with tiny mult)
        return m, step

    def snapshot(self) -> Dict:
        return {k: v.to_dict() for k, v in self.states.items()}

    @classmethod
    def replay(cls, tcfg: "TraderConfig", closed: list) -> "Martingale":
        """Rebuild the state from a list of closed plans ``(tf, net, r_net, step_used)`` in close order (live bot)."""
        m = cls(tcfg)
        for tf, net, r_net, step in closed:
            m.on_close(tf, float(net), float(r_net), int(step or 0))
        return m


def grid_wanted(plan: "TradePlan", tcfg: "TraderConfig") -> bool:
    """Does this plan get a deep (zone-averaging) leg?"""
    if tcfg.grid_add_r <= 0 or getattr(plan, "grid_leg", False):
        return False
    if not (0.0 < tcfg.grid_add_r < 1.0):
        raise ValueError("grid_add_r must be inside (0, 1): a fraction of the zone between the entry and the stop")
    if tcfg.grid_tfs and plan.tf not in tcfg.grid_tfs:
        return False
    if tcfg.grid_regime and plan.regime != tcfg.grid_regime:
        return False
    return True
