#!/usr/bin/env python3
"""v15 step 1 - DIAGNOSIS of the v14-A trader (run_trader.bat): where are the trades lost, and what is the edge of the POIs
the trader REJECTS today (the candidates for "more trades at the same loss percentage")?

1. Reproduce v14-A exactly (430 tr / +227.53 % / DD -5.84 %) from the strings in run_trader.bat.
2. Funnel of the reference: every unique POI shown by the scanner -> the last stage it reached (filtered by which gate /
   order never filled / traded / overlaps) per TF.
3. WOULD-BE OUTCOME of every POI the trade filter rejected, by TF x quality band x cost band x session, measured with the
   stand-alone plan replayer (same fill / SL mechanics as the simulator; 2-leg 0.6R/1.2R approximation of the ladder; the
   order lives while the scanner shows the POI, exactly as the mirror policy would keep it).  Fill rate, win rate, avg R,
   gross R per band -> which bands carry a positive edge (tier candidates) and which do not.
4. The same for the traded population (sanity: the replay must agree with the simulator's outcome direction).
5. RE-ARM after a stop-out: for every stopped trade, replay the SAME plan again from the stop minute (wait N bars of its TF):
   does price come back, and does the second attempt pay?
6. What the `candidates` column holds (count only -> the 2nd candidate idea is out of scope if no list is recorded).

Outputs: study_results/v15_diag/{ref_summary.json, funnel.csv, funnel_reasons.csv, rejected_bands.csv, rejected_pois.csv,
rearm.csv, traded_replay.csv, notes.txt}
    python3 run_v15_diag.py --csv data/xauusd_m1.csv
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lubot.execution import SymbolSpec, TradePlan  # noqa: E402
from lubot.plan_replay import PlanReplayer  # noqa: E402
from lubot.portfolio_sim import PortfolioSimulator  # noqa: E402
from lubot.trade_filter import TradeFilter, ny_session_of  # noqa: E402
from run_v12_funnel import TFS, funnel  # noqa: E402
from v14_common import CSV, OOS_SPLIT, judge, load_year  # noqa: E402
from v15_common import EXPECT_V14A, v14a_config  # noqa: E402

OUT = Path("study_results/v15_diag")
TF_MIN = {"M5": 5, "M10": 10, "M15": 15, "M30": 30, "H1": 60}
Q_BANDS = [(0.0, 0.50), (0.50, 0.53), (0.53, 0.55), (0.55, 0.57), (0.57, 0.60), (0.60, 0.65), (0.65, 1.01)]
C_BANDS = [(0.0, 0.08), (0.08, 0.10), (0.10, 0.12), (0.12, 0.15), (0.15, 9.9)]


def band(x: float, bands) -> str:
    for lo, hi in bands:
        if lo <= x < hi:
            return f"{lo:.2f}-{hi:.2f}" if hi < 9 else f">={lo:.2f}"
    return "nan"


def poi_windows(sel: pd.DataFrame) -> pd.DataFrame:
    """For every unique POI (tf#id): first time shown, and the time its slot stopped showing it (the order would be cancelled
    by the mirror policy) - the window during which a limit order would wait.  A POI can be shown in several spells; we take
    the FIRST spell (the one the trader would have acted on)."""
    rows = []
    for (tf, side), g in sel.groupby(["tf", "side"], sort=False):
        g = g.sort_values("t")
        cur, start = None, None
        for r in g.itertuples(index=False):
            pid = int(r.id) if (r.event != "clear" and r.id >= 0) else None
            if pid != cur:
                if cur is not None:
                    rows.append((f"{tf}#{cur}", tf, start, r.t))
                cur, start = pid, r.t
        if cur is not None:
            rows.append((f"{tf}#{cur}", tf, start, g.t.iloc[-1] + pd.Timedelta(days=3)))
    w = pd.DataFrame(rows, columns=["key", "tf", "t_start", "t_end"])
    return w.drop_duplicates("key", keep="first").set_index("key")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=CSV)
    ap.add_argument("--hold-days", type=float, default=5.0, help="replay walks a filled plan at most this long")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    notes = []
    t0 = time.time()
    m1, sel = load_year(a.csv)
    print(f"year: {len(m1)} M1 bars {m1.index[0]} -> {m1.index[-1]}; {len(sel)} selection events")

    # ---------------------------------------------------------------- 1. reference
    tcfg = v14a_config()
    spec = SymbolSpec()
    sim = PortfolioSimulator(m1, sel, tcfg, spec)
    res = sim.run()
    s = res.summary()
    got = (int(s["trades"]), round(s["return_%"], 2), round(s["max_dd_%"], 2))
    ok = got == EXPECT_V14A
    print(f"v14-A reproduced: {got}  expected {EXPECT_V14A}  -> {'IDENTICAL' if ok else 'MISMATCH'}")
    notes.append(f"v14-A reproduction: {got} vs expected {EXPECT_V14A} -> {'IDENTICAL' if ok else 'MISMATCH'}")
    jd = judge(res)
    json.dump(jd, open(OUT / "ref_summary.json", "w"), indent=1, default=str)
    tr = res.trades
    tr.to_csv(OUT / "ref_trades.csv", index=False)

    # ---------------------------------------------------------------- 2. funnel
    fun, reasons = funnel(sim, sel)
    fun.to_csv(OUT / "funnel.csv", index=False)
    reasons.to_csv(OUT / "funnel_reasons.csv", index=False)
    print(fun.pivot_table(index="stage", columns="tf", values="pois", aggfunc="sum", fill_value=0))
    # how often the slot limit binds (overlaps open / max open) and the never-filled population
    sk = Counter(w for _, w in sim.skipped)
    notes.append("skip reasons (events): " + json.dumps(dict(sk.most_common(12))))
    # 6. candidates column
    notes.append(f"candidates column: dtype {sel.candidates.dtype}, values {sorted(sel.candidates.dropna().unique().tolist())[:12]} "
                 f"-> {'a COUNT only (no 2nd candidate recorded)' if np.issubdtype(sel.candidates.dtype, np.number) else 'a list'}")

    # ---------------------------------------------------------------- 3. would-be outcome of the rejected POIs
    shown = sel[(sel.id >= 0) & (sel.event != "clear")].copy()
    shown["key"] = shown.tf + "#" + shown.id.astype(int).astype(str)
    first = shown.sort_values("t").drop_duplicates("key", keep="first").set_index("key")
    win = poi_windows(sel)
    idx = m1.index.values.astype("datetime64[ns]")
    sp = m1["spread"].to_numpy(float)
    rep = PlanReplayer(m1.open.to_numpy(float), m1.high.to_numpy(float), m1.low.to_numpy(float), m1.close.to_numpy(float), sp,
                       partial_r=0.6, partial_frac=0.5, tp2_r=1.2, be_offset_r=0.0, sl_slippage=tcfg.sl_slippage)
    flt = TradeFilter.parse(tcfg.trade_filter)
    traded_keys = set(tr.key)
    filtered = defaultdict(list)
    for k, why in sim.filtered:
        filtered[k].append(why)
    # the plan for a POI (entry = near edge, SL = far edge, as the trader would build it)
    rows = []
    for k, whys in filtered.items():
        if k in traded_keys or k not in first.index:
            continue
        p = first.loc[k]
        d = {"id": p.id, "tf": p.tf, "type": p.type, "direction": p.direction, "top": p.top, "bottom": p.bottom,
             "quality": None if not np.isfinite(p.quality) else p.quality, "grade": p.grade, "distance": p.distance,
             "distance_atr": p.distance_atr, "atr": p.atr, "time": str(p.t)}
        plan = TradePlan.from_poi(d, tcfg, spec, selected_time=str(p.t))
        if plan is None:
            continue
        m0 = int(np.searchsorted(idx, np.datetime64(p.t), side="left"))
        if m0 >= len(idx):
            continue
        tfm = TF_MIN[p.tf]
        t_end = win.t_end.get(k, p.t + pd.Timedelta(days=3))
        m_wait = int(np.searchsorted(idx, np.datetime64(t_end), side="left"))
        m_wait = max(m_wait, m0 + 1)
        m_hold = m_wait + int(a.hold_days * 24 * 60)
        rr = rep.replay(plan.is_buy, plan.entry, plan.sl, m0, m_wait, m_hold)
        cost_r = flt.cost_r(p.top, p.bottom, float(sp[m0]))
        sess, hour = ny_session_of(p.t)
        why = Counter(whys).most_common(1)[0][0]
        rows.append({"key": k, "tf": p.tf, "side": plan.side, "kind": p.type, "quality": p.quality, "cost_r": round(cost_r, 4),
                     "session": sess, "hour": hour, "reason": why.split(": ")[-1], "t": p.t, "oos": p.t >= pd.Timestamp(OOS_SPLIT),
                     "wait_bars": (m_wait - m0) / tfm, "filled": rr.filled, "through": rr.through_at_start,
                     "outcome": rr.outcome, "r_gross": rr.r_gross if rr.filled else np.nan,
                     "r_net": (rr.r_gross - 0.07 / plan.risk) if rr.filled else np.nan,   # commission $7/lot = $0.07/oz
                     "mfe_r": rr.mfe_r, "mae_r": rr.mae_r, "q_band": band(float(p.quality), Q_BANDS), "c_band": band(cost_r, C_BANDS)})
    rej = pd.DataFrame(rows)
    rej.to_csv(OUT / "rejected_pois.csv", index=False)
    print(f"rejected POIs replayed: {len(rej)}  ({time.time() - t0:.0f}s)")

    def agg(g: pd.DataFrame) -> pd.Series:
        f = g[g.filled]
        w = f[f.r_net > 0]
        return pd.Series({"pois": len(g), "filled": len(f), "fill_%": round(100 * len(f) / max(len(g), 1), 1),
                          "win_%": round(100 * len(w) / max(len(f), 1), 1), "sl_%": round(100 * (f.outcome == "sl").mean(), 1) if len(f) else np.nan,
                          "avg_R": round(f.r_net.mean(), 3) if len(f) else np.nan, "sum_R": round(f.r_net.sum(), 2),
                          "PF_R": round(f[f.r_net > 0].r_net.sum() / abs(f[f.r_net < 0].r_net.sum()), 2) if (f.r_net < 0).any() else np.inf,
                          "oos_filled": int(f.oos.sum()), "oos_sum_R": round(f[f.oos].r_net.sum(), 2),
                          "oos_win_%": round(100 * (f[f.oos].r_net > 0).mean(), 1) if f.oos.any() else np.nan})

    bands = []
    for keys in (["tf", "reason"], ["tf", "q_band"], ["tf", "c_band"], ["tf", "session"], ["tf", "side"], ["tf", "reason", "q_band"],
                 ["tf", "reason", "c_band"]):
        g = rej.groupby(keys).apply(agg, include_groups=False).reset_index()
        g.insert(0, "group", "x".join(keys))
        bands.append(g)
    bands = pd.concat(bands, ignore_index=True)
    bands.to_csv(OUT / "rejected_bands.csv", index=False)
    with pd.option_context("display.width", 220, "display.max_rows", 400):
        print(bands[bands.group.isin(["tfxreason", "tfxq_band", "tfxc_band"])].to_string(index=False))

    # ---------------------------------------------------------------- 4. traded population through the same replayer
    rows = []
    for r in tr.itertuples(index=False):
        m0 = int(np.searchsorted(idx, np.datetime64(pd.Timestamp(r.selected_time)), side="left"))
        t_end = win.t_end.get(r.key, pd.Timestamp(r.selected_time) + pd.Timedelta(days=3))
        m_wait = max(int(np.searchsorted(idx, np.datetime64(t_end), side="left")), m0 + 1)
        rr = rep.replay(r.side == "buy", r.limit, r.sl, m0, m_wait, m_wait + int(a.hold_days * 24 * 60))
        rows.append({"key": r.key, "tf": r.tf, "sim_r_net": r.r_net, "sim_outcome": r.outcome, "rep_filled": rr.filled,
                     "rep_outcome": rr.outcome, "rep_r_net": (rr.r_gross - 0.07 / r.risk_usd_per_unit) if rr.filled else np.nan})
    trd = pd.DataFrame(rows)
    trd.to_csv(OUT / "traded_replay.csv", index=False)
    f = trd[trd.rep_filled]
    agree = ((f.rep_r_net > 0) == (f.sim_r_net > 0)).mean() if len(f) else np.nan
    notes.append(f"traded population through the replayer: {trd.rep_filled.sum()}/{len(trd)} filled, sign agreement sim vs replay "
                 f"{100 * agree:.1f} %, sim win {100 * (trd.sim_r_net > 0).mean():.1f} % vs replay win {100 * (f.rep_r_net > 0).mean():.1f} %, "
                 f"sim avg R {trd.sim_r_net.mean():.3f} vs replay {f.rep_r_net.mean():.3f}")

    # ---------------------------------------------------------------- 5. re-arm after a stop-out
    rows = []
    stops = tr[tr.outcome == "sl"]
    for r in stops.itertuples(index=False):
        m_stop = int(np.searchsorted(idx, np.datetime64(pd.Timestamp(r.close_time)), side="right"))
        tfm = TF_MIN[r.tf]
        for wait in (6, 12, 24):
            rr = rep.replay(r.side == "buy", r.limit, r.sl, m_stop, m_stop + wait * tfm, m_stop + wait * tfm + int(a.hold_days * 24 * 60))
            rows.append({"key": r.key, "tf": r.tf, "side": r.side, "wait_bars": wait, "oos": r.close_time >= pd.Timestamp(OOS_SPLIT),
                         "filled": rr.filled, "through": rr.through_at_start, "outcome": rr.outcome,
                         "r_net": (rr.r_gross - 0.07 / r.risk_usd_per_unit) if rr.filled else np.nan})
    ra = pd.DataFrame(rows)
    ra.to_csv(OUT / "rearm.csv", index=False)
    if len(ra):
        g = ra.groupby(["wait_bars", "tf"]).apply(lambda g: pd.Series({
            "stops": len(g), "through_at_start": int(g.through.sum()), "filled": int(g.filled.sum()),
            "win_%": round(100 * (g[g.filled].r_net > 0).mean(), 1) if g.filled.any() else np.nan,
            "sum_R": round(g[g.filled].r_net.sum(), 2), "avg_R": round(g[g.filled].r_net.mean(), 3) if g.filled.any() else np.nan}),
            include_groups=False).reset_index()
        g.to_csv(OUT / "rearm_summary.csv", index=False)
        print("re-arm after SL:\n", g.to_string(index=False))
        tot = ra[ra.wait_bars == 12]
        notes.append(f"re-arm after SL (wait 12 bars): {int(tot.filled.sum())}/{len(tot)} re-fill, through at start {int(tot.through.sum())}, "
                     f"win {100 * (tot[tot.filled].r_net > 0).mean():.1f} %, sum R {tot[tot.filled].r_net.sum():+.1f}, "
                     f"avg R {tot[tot.filled].r_net.mean():+.3f}")


    # ---------------------------------------------------------------- 7. never-filled orders: would an entry IN FRONT of the zone have filled?
    # (v11 rejected a global front offset: DD 7-12 %.  Here: split by confluent / not, and measure the would-be outcome of the extra
    #  fills at offsets 0.1 / 0.2 / 0.3 of the zone height in front of the edge - the candidate lever is a CONFLUENT-only offset.)
    rows = []
    seen = set()
    for c in sim.cancelled:
        pl = c.plan
        if pl.key in traded_keys or pl.key in seen or pl.grid_leg or pl.reentry_n:
            continue
        seen.add(pl.key)
        m0 = c.placed_minute
        t_end = win.t_end.get(pl.key, c.placed + pd.Timedelta(days=3))
        m_wait = max(int(np.searchsorted(idx, np.datetime64(t_end), side="left")), m0 + 1)
        h = pl.zone_top - pl.zone_bottom
        sgn = 1.0 if pl.is_buy else -1.0
        for off in (0.0, 0.1, 0.2, 0.3):
            ent = round(pl.entry + sgn * off * h, 2)
            rr = rep.replay(pl.is_buy, ent, pl.sl, m0, m_wait, m_wait + int(a.hold_days * 24 * 60))
            risk = abs(ent - pl.sl)
            rows.append({"key": pl.key, "tf": pl.tf, "side": pl.side, "confluent": bool(getattr(pl, "confluent", False)),
                         "quality": pl.quality, "offset": off, "oos": c.placed >= pd.Timestamp(OOS_SPLIT), "filled": rr.filled,
                         "through": rr.through_at_start, "outcome": rr.outcome,
                         "r_net": (rr.r_gross - 0.07 / risk) if rr.filled else np.nan})
    nf = pd.DataFrame(rows)
    nf.to_csv(OUT / "never_filled_front.csv", index=False)
    if len(nf):
        g = nf.groupby(["confluent", "offset"]).apply(lambda g: pd.Series({
            "orders": len(g), "filled": int(g.filled.sum()), "fill_%": round(100 * g.filled.mean(), 1),
            "win_%": round(100 * (g[g.filled].r_net > 0).mean(), 1) if g.filled.any() else np.nan,
            "sl_%": round(100 * (g[g.filled].outcome == "sl").mean(), 1) if g.filled.any() else np.nan,
            "avg_R": round(g[g.filled].r_net.mean(), 3) if g.filled.any() else np.nan, "sum_R": round(g[g.filled].r_net.sum(), 2),
            "oos_filled": int(g[g.oos].filled.sum()), "oos_sum_R": round(g[g.oos & g.filled].r_net.sum(), 2)}),
            include_groups=False).reset_index()
        g.to_csv(OUT / "never_filled_front_summary.csv", index=False)
        print("never-filled orders with a front offset:\n", g.to_string(index=False))
        for conf in (True, False):
            for off in (0.1, 0.2):
                x = nf[(nf.confluent == conf) & (nf.offset == off) & nf.filled]
                notes.append(f"never-filled {'CONFLUENT' if conf else 'plain'} orders, front offset {off}: {len(x)} would fill, win "
                             f"{100 * (x.r_net > 0).mean():.1f} %, avg R {x.r_net.mean():+.3f}, sum R {x.r_net.sum():+.1f} (OOS sum R {x[x.oos].r_net.sum():+.1f})")

    # ---------------------------------------------------------------- notes
    # traded population: CONFLUENT vs plain (the conviction signal), IS and OOS
    for lab, x in (("IS", tr[tr.close_time < OOS_SPLIT]), ("OOS", tr[tr.close_time >= OOS_SPLIT]), ("ALL", tr)):
        for conf in (True, False):
            y = x[x.confluent == conf]
            notes.append(f"traded {lab} {'CONFLUENT' if conf else 'plain    '}: n {len(y)} win {100 * (y.net > 0).mean():.1f} % sl "
                         f"{100 * (y.outcome == 'sl').mean():.1f} % avg R {y.r_net.mean():+.3f} sum R {y.r_net.sum():+.1f} net {y.net.sum():+.0f} $")
    notes.append(f"rejected POIs: {len(rej)}; by reason: {rej.reason.value_counts().to_dict()}")
    for tf in TFS:
        q = rej[(rej.tf == tf) & (rej.reason == "quality") & rej.filled]
        if len(q):
            notes.append(f"  {tf} quality-rejected & filled: n {len(q)} win {100 * (q.r_net > 0).mean():.1f} % avg R {q.r_net.mean():+.3f} "
                         f"sum R {q.r_net.sum():+.1f} (OOS n {int(q.oos.sum())} sum R {q[q.oos].r_net.sum():+.1f})")
    notes.append(f"elapsed {time.time() - t0:.0f}s")
    (OUT / "notes.txt").write_text("\n".join(notes) + "\n")
    print("\n".join(notes))


if __name__ == "__main__":
    main()
