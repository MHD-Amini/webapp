"""v15 - more trades & more profit at the same loss percentage: conviction sizing, confluence memory, tiered admission,
martingale confluent-only gate.  Defaults must be byte-identical to v14 (parity is checked on the full year by smoke_v15.py)."""
import re

import pandas as pd

from lubot.execution import TraderConfig
from tests.test_portfolio_sim import bars, cfg, run, sel  # noqa: F401

FLAT = bars([(2005, 2006, 2004, 2005)] * 6)


def _clear(t, tf="M15", side="below"):
    d = sel(t, tf=tf, side=side, pid=-1, event="clear")
    d.update(id=-1, top=float("nan"), bottom=float("nan"))
    return d


def test_v15_defaults_are_off():
    c = TraderConfig()
    assert (c.confluent_risk_scale, c.plain_risk_scale, c.confluence_memory_min, c.confluence_memory_kind) == (1.0, 1.0, 0, "all")
    assert (c.tier_filter, c.tier_risk_scale, c.mart_confluent_only) == ("", 0.5, False)
    c.override("confluent_risk_scale=1.5,plain_risk_scale=0.75,confluence_memory_min=240,tier_filter=M10:min_quality=0.5,"
               "tier_risk_scale=0.4,mart_confluent_only=true,confluence_memory_kind=open")
    assert (c.confluent_risk_scale, c.plain_risk_scale, c.confluence_memory_min) == (1.5, 0.75, 240)
    assert (c.tier_filter, c.tier_risk_scale, c.mart_confluent_only, c.confluence_memory_kind) == ("M10:min_quality=0.5", 0.4, True, "open")


def test_conviction_sizing_scales_confluent_and_plain_plans():
    ev = [sel("2026-03-02 10:00", pid=1, tf="M15"), sel("2026-03-02 10:01", pid=9, tf="M5", top=1999.0, bottom=1996.0)]
    res, sim = run(FLAT, ev, cfg(dedupe_cross_tf=False, confluence_filter="M5:min_quality=0.50",
                                 confluent_risk_scale=1.5, plain_risk_scale=0.75))
    p15, p5 = sim.pending["M15#1"].plan, sim.pending["M5#9"].plan
    assert not p15.confluent and p5.confluent
    assert p15.risk_scale == 0.75 and p5.risk_scale == 1.5
    # the lots follow: plain plan 0.75 % of 10 000 over a 5 $ zone -> 0.15 lot; confluent 1.5 % over 3 $ -> 0.5 lot
    assert abs(sim.pending["M15#1"].lots_leg1 + sim.pending["M15#1"].lots_leg2 - 0.15) < 1e-9
    assert abs(sim.pending["M5#9"].lots_leg1 + sim.pending["M5#9"].lots_leg2 - 0.50) < 1e-9
    # defaults: both 1.0
    res, sim = run(FLAT, ev, cfg(dedupe_cross_tf=False, confluence_filter="M5:min_quality=0.50"))
    assert sim.pending["M15#1"].plan.risk_scale == 1.0 and sim.pending["M5#9"].plan.risk_scale == 1.0


def test_confluence_memory_counts_a_recently_cancelled_plan_of_another_tf():
    # M15#1 shown at 10:00, cleared at 10:01 (order cancelled); M5#9 on the same level at 10:03 with q 0.52
    ev = [sel("2026-03-02 10:00", pid=1, tf="M15"), _clear("2026-03-02 10:01"),
          sel("2026-03-02 10:03", pid=9, tf="M5", top=1999.0, bottom=1996.0)]
    ev[2]["quality"] = 0.52
    base = dict(dedupe_cross_tf=False, trade_filter="M5:min_quality=0.55", confluence_filter="M5:min_quality=0.50")
    # v12 behaviour: nothing active on another TF at 10:03 -> plain filter -> rejected
    res, sim = run(FLAT, ev, cfg(**base))
    assert not sim.pending and sim.filtered == [("M5#9", "M5: quality")]
    # v15 memory 5 min: the cancelled M15 order (2 min ago) still counts -> confluent -> accepted
    res, sim = run(FLAT, ev, cfg(**base, confluence_memory_min=5))
    assert set(sim.pending) == {"M5#9"} and sim.pending["M5#9"].plan.confluent
    # memory 1 min: too old -> rejected
    res, sim = run(FLAT, ev, cfg(**base, confluence_memory_min=1))
    assert not sim.pending
    # kind=open: the M15 order was never filled -> does not count
    res, sim = run(FLAT, ev, cfg(**base, confluence_memory_min=5, confluence_memory_kind="open"))
    assert not sim.pending
    # the same TF never counts
    ev2 = [sel("2026-03-02 10:00", pid=1, tf="M5"), _clear("2026-03-02 10:01", tf="M5"),
           sel("2026-03-02 10:03", pid=9, tf="M5", top=1999.0, bottom=1996.0)]
    ev2[2]["quality"] = 0.52
    res, sim = run(FLAT, ev2, cfg(**base, confluence_memory_min=5))
    assert not sim.pending


def test_tier_filter_admits_a_rejected_plan_at_reduced_risk():
    ev = [sel("2026-03-02 10:00", pid=9, tf="M5", top=1999.0, bottom=1996.0)]
    ev[0]["quality"] = 0.52
    # normal bar 0.55 rejects; tier bar 0.50 admits at half size
    res, sim = run(FLAT, ev, cfg(trade_filter="M5:min_quality=0.55", tier_filter="M5:min_quality=0.50", tier_risk_scale=0.5))
    p = sim.pending["M5#9"]
    assert p.plan.tier and p.plan.risk_scale == 0.5 and not sim.filtered
    assert abs(p.lots_leg1 + p.lots_leg2 - 0.16) < 1e-9     # 0.5 % of 10 000 over a 3 $ zone = 0.1667 -> 0.16 lot (broker step)
    assert sim.tier_trades_placed == 1
    # fails the tier bar too -> rejected as before
    ev[0]["quality"] = 0.48
    res, sim = run(FLAT, ev, cfg(trade_filter="M5:min_quality=0.55", tier_filter="M5:min_quality=0.50"))
    assert not sim.pending and sim.filtered == [("M5#9", "M5: quality")]
    # a TF NOT listed in the tier filter gets no tier (M15 plan, tier filter lists M5 only)
    ev15 = [sel("2026-03-02 10:00", pid=3, tf="M15")]
    ev15[0]["quality"] = 0.52
    res, sim = run(FLAT, ev15, cfg(trade_filter="M15:min_quality=0.55", tier_filter="M5:min_quality=0.50"))
    assert not sim.pending and sim.filtered == [("M15#3", "M15: quality")]
    # passes the normal bar -> not a tier plan, full size
    ev[0]["quality"] = 0.60
    res, sim = run(FLAT, ev, cfg(trade_filter="M5:min_quality=0.55", tier_filter="M5:min_quality=0.50"))
    assert not sim.pending["M5#9"].plan.tier and sim.pending["M5#9"].plan.risk_scale == 1.0


def test_tier_and_plain_plans_are_never_stepped_up_with_the_confluent_gate():
    # a loss on M5 first, then a plain M5 plan: v14 mult x2 would step it up; mart_confluent_only keeps it at base size
    from lubot.martingale import Martingale
    c = cfg(mart_mode="mult", mart_mult=2.0, mart_max_steps=3, mart_max_risk_pct=0, mart_confluent_only=True)
    ev = [sel("2026-03-02 10:00", pid=9, tf="M5", top=1999.0, bottom=1996.0)]
    res, sim = run(FLAT, ev, c)
    assert sim.pending["M5#9"].plan.mart_step == 0
    # drive the martingale state directly: one loss -> scale would be 2.0 ...
    sim.mart.on_close("M5", -100.0, -1.0)
    plan = sim.pending["M5#9"].plan
    assert sim.mart.scale(plan, 10_000)[0] == 2.0
    # ... but the simulator's hook refuses the step for a plain / tier plan with the gate on
    from dataclasses import replace
    for kw in (dict(confluent=False), dict(tier=True)):
        p2 = replace(plan, mart_scale=1.0, mart_step=0, risk_scale=1.0)
        for k, v in kw.items():
            setattr(p2, k, v)
        sim._apply_v14(p2, 10_000)
        assert (p2.mart_scale, p2.mart_step) == (1.0, 0)
    p3 = replace(plan, mart_scale=1.0, mart_step=0, risk_scale=1.0)
    p3.confluent, p3.tier = True, False
    sim._apply_v14(p3, 10_000)
    assert (p3.mart_scale, p3.mart_step) == (2.0, 1)


def test_bat_v14_strings_match_v15_common():
    """v15_common freezes the v14-A strings; they must equal what run_trader.bat ships today (the v15 reference)."""
    import v15_common as v
    line = next(l for l in open("run_trader.bat", encoding="utf-8").read().splitlines() if l.strip().startswith("python trader.py --symbol"))
    arg = lambda n: re.search(n + r' "([^"]*)"', line).group(1)
    bat_trader = arg("--trader")
    # the bat carries v15 keys on top of v14-A (and, since v16, M20 inside the TF-scoped keys): every v14-A key must be present
    # with its value, except keep_replaced_tfs / mart_tfs whose v14 set must be a subset of the shipped set
    bat = dict(kv.split("=", 1) for kv in bat_trader.split(","))
    for kv in v.V14A_TRADER.split(","):
        k, val = kv.split("=", 1)
        if k in ("keep_replaced_tfs", "mart_tfs"):
            assert set(val.split("|")) <= set(bat[k].split("|")), k
        else:
            assert bat[k] == val, k
    # the v14-A filters are a prefix of the shipped filters (v16 appends an M20 rule)
    assert arg("--trade-filter").startswith(v.V14A_FLT) and arg("--confluence-filter").startswith(v.V14A_CF)
