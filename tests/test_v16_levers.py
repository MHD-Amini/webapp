"""v16 - new trade sources: ranked candidates (max_rank / rank2_* keys) and the M20 timeframe.  Defaults must be byte-identical
to v15 (parity on the full year is checked by smoke_v16.py: v15-A on the v10 streams = 448 / +297.45 / -5.82)."""
import pandas as pd

from lubot.config import TIMEFRAME_MINUTES, StrategyConfig
from lubot.execution import TraderConfig
from tests.test_portfolio_sim import bars, cfg, run, sel  # noqa: F401

FLAT = bars([(2005, 2006, 2004, 2005)] * 8)


def rsel(t, rank=1, **kw):
    d = sel(t, **kw)
    d["rank"] = rank
    return d


def _clear(t, rank=1, tf="M15", side="below"):
    d = rsel(t, rank=rank, tf=tf, side=side, pid=-1, event="clear")
    d.update(id=-1, top=float("nan"), bottom=float("nan"))
    return d


def test_v16_defaults_are_off_and_override_parses():
    c = TraderConfig()
    assert (c.max_rank, c.rank2_filter, c.rank2_risk_scale, c.rank2_tfs, c.rank2_confluent_only) == (1, "", 1.0, (), False)
    c.override("max_rank=2,rank2_filter=M10:min_quality=0.55,rank2_risk_scale=0.5,rank2_tfs=M10|M15,rank2_confluent_only=true")
    assert (c.max_rank, c.rank2_filter, c.rank2_risk_scale, c.rank2_tfs, c.rank2_confluent_only) == \
        (2, "M10:min_quality=0.55", 0.5, ("M10", "M15"), True)


def test_m20_timeframe_registered():
    assert TIMEFRAME_MINUTES["M20"] == 20 and StrategyConfig().htf_parent["M20"] == "H1"
    assert StrategyConfig().tf_minutes("M20") == 20


def test_rank2_rows_ignored_at_max_rank_1():
    ev = [rsel("2026-03-02 10:00", rank=1, pid=1), rsel("2026-03-02 10:00", rank=2, pid=2, top=1990.0, bottom=1985.0)]
    res, sim = run(FLAT, ev, cfg())
    assert set(sim.pending) == {"M15#1"}
    # a stream without a rank column behaves exactly the same
    res, sim = run(FLAT, [sel("2026-03-02 10:00", pid=1)], cfg())
    assert set(sim.pending) == {"M15#1"}


def test_rank2_zone_placed_at_max_rank_2_with_scale_and_filter():
    ev = [rsel("2026-03-02 10:00", rank=1, pid=1), rsel("2026-03-02 10:00", rank=2, pid=2, top=1990.0, bottom=1985.0)]
    res, sim = run(FLAT, ev, cfg(max_rank=2, rank2_risk_scale=0.5))
    assert set(sim.pending) == {"M15#1", "M15#2"}
    assert sim.pending["M15#1"].plan.rank == 1 and sim.pending["M15#1"].plan.risk_scale == 1.0
    assert sim.pending["M15#2"].plan.rank == 2 and sim.pending["M15#2"].plan.risk_scale == 0.5
    assert sim.rank2_placed == 1
    # own filter bar for rank 2: quality 0.6 < 0.7 -> rejected, rank 1 untouched
    res, sim = run(FLAT, ev, cfg(max_rank=2, rank2_filter="M15:min_quality=0.7"))
    assert set(sim.pending) == {"M15#1"} and sim.filtered == [("M15#2", "M15: quality")]
    # tf scope
    res, sim = run(FLAT, ev, cfg(max_rank=2, rank2_tfs=("M10",)))
    assert set(sim.pending) == {"M15#1"} and ("M15#2", "rank filtered (tf)") in sim.skipped
    # confluent only: nothing of another TF on the level -> skipped
    res, sim = run(FLAT, ev, cfg(max_rank=2, rank2_confluent_only=True, confluence_filter="M15:min_quality=0.5"))
    assert set(sim.pending) == {"M15#1"} and ("M15#2", "rank filtered (not confluent)") in sim.skipped


def test_rank2_overlapping_rank1_zone_is_deduped():
    ev = [rsel("2026-03-02 10:00", rank=1, pid=1), rsel("2026-03-02 10:00", rank=2, pid=2, top=1999.0, bottom=1994.0)]
    res, sim = run(FLAT, ev, cfg(max_rank=2))
    assert set(sim.pending) == {"M15#1"} and ("M15#2", "overlaps pending") in sim.skipped


def test_promotion_from_rank2_to_rank1_keeps_the_order():
    # 10:00 rank1 = #1, rank2 = #2.  10:02: #1 leaves, #2 becomes rank 1 (events: clear rank2, set rank1 = #2) -> #2's order stays,
    # #1's order is cancelled (replaced on rank 1)
    ev = [rsel("2026-03-02 10:00", rank=1, pid=1), rsel("2026-03-02 10:00", rank=2, pid=2, top=1990.0, bottom=1985.0),
          _clear("2026-03-02 10:02", rank=2), rsel("2026-03-02 10:02", rank=1, pid=2, top=1990.0, bottom=1985.0)]
    res, sim = run(FLAT, ev, cfg(max_rank=2))
    assert set(sim.pending) == {"M15#2"}
    assert [c.plan.key for c in sim.cancelled] == ["M15#1"] and sim.cancelled[0].reason_cancel == "replaced"
    assert sim.pending["M15#2"].placed == pd.Timestamp("2026-03-02 10:00")      # the original order, never re-placed
    # demotion: #1 drops to rank 2 (set rank1 = #3, set rank2 = #1 in the same bar) -> #1 kept, #3 placed, old rank2 (#2) cancelled
    ev = [rsel("2026-03-02 10:00", rank=1, pid=1), rsel("2026-03-02 10:00", rank=2, pid=2, top=1990.0, bottom=1985.0),
          rsel("2026-03-02 10:02", rank=1, pid=3, top=1980.0, bottom=1975.0), rsel("2026-03-02 10:02", rank=2, pid=1)]
    res, sim = run(FLAT, ev, cfg(max_rank=2))
    assert set(sim.pending) == {"M15#1", "M15#3"} and [c.plan.key for c in sim.cancelled] == ["M15#2"]


def test_rank2_clear_cancels_only_its_own_order():
    ev = [rsel("2026-03-02 10:00", rank=1, pid=1), rsel("2026-03-02 10:00", rank=2, pid=2, top=1990.0, bottom=1985.0),
          _clear("2026-03-02 10:03", rank=2)]
    res, sim = run(FLAT, ev, cfg(max_rank=2))
    assert set(sim.pending) == {"M15#1"} and [c.plan.key for c in sim.cancelled] == ["M15#2"]
    assert "rank" in res.trades.columns or len(res.trades) == 0


def test_tf_risk_scale_applies_per_timeframe():
    ev = [rsel("2026-03-02 10:00", pid=1, tf="M15"), rsel("2026-03-02 10:00", pid=9, tf="M20", top=1990.0, bottom=1985.0)]
    res, sim = run(FLAT, ev, cfg(tf_risk_scale="M20:0.5"))
    assert sim.pending["M15#1"].plan.risk_scale == 1.0 and sim.pending["M20#9"].plan.risk_scale == 0.5
    res, sim = run(FLAT, ev, cfg())
    assert sim.pending["M20#9"].plan.risk_scale == 1.0
