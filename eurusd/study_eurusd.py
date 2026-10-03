#!/usr/bin/env python3
"""EURUSD lever study for the v14-A trader (single-file bot).  Every variant = full-year run through the M1 simulator.
Resumable: one json per variant in out/study/, summary -> out/eurusd_study[_tag].csv.

    python study_eurusd.py --stage base|filter|ladder|regime|risk|all [--only n1,n2] [--base "..."] [--tag x]
    python study_eurusd.py --extra "name=override;name2=override2"

Judged like the v14 studies: return / DD / PF / win, IS (Sep25-Feb26) vs OOS (Mar26-Sep26) PF and R, months positive.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lubot_trader_v14_single as lu  # noqa: E402
from backtest_eurusd import load_sel  # noqa: E402
from eurusd_tools import eurusd_spec, load_eurusd  # noqa: E402

OUT = Path(HERE) / "out" / "study"
OOS = pd.Timestamp("2026-03-01")
SESS_A = "asia|london|preny|ny|lclose"


def flt(m5q=0.55, m10q=0.57, m15q=0.60, hq=0.57, cost=None, m5cost=0.08, sess=SESS_A, all_sess=None, sides=None, kinds=None):
    """Per-TF filter string in the v14-A style.  ``all_sess`` = session gate on EVERY timeframe."""
    def blk(tf, q, c=None, s=None):
        parts = []
        if c:
            parts.append(f"max_cost_r={c}")
        if q:
            parts.append(f"min_quality={q}")
        if s:
            parts.append(f"sessions={s}")
        if sides:
            parts.append(f"sides={sides}")
        if kinds:
            parts.append(f"kinds={kinds}")
        return f"{tf}:" + ";".join(parts)
    return "/".join([blk("M5", m5q, m5cost, all_sess or sess), blk("M10", m10q, cost, all_sess), blk("M15", m15q, cost, all_sess),
                     blk("M30|H1", hq, cost, all_sess)])


def judge(res) -> dict:
    s = res.summary()
    tr = res.trades
    out = {k: s.get(k) for k in ("trades", "return_%", "max_dd_%", "profit_factor", "win_%", "sl_%", "total_R", "avg_R",
                                 "sharpe_daily", "end_balance", "daily_halts", "halted", "cancelled", "skipped")}
    if not len(tr):
        out.update(IS_n=0, IS_R=0, IS_PF=0, OOS_n=0, OOS_R=0, OOS_PF=0, months_pos=0, months=0, worst_month_R=0, gross_loss=0,
                   return_over_dd=0, buy_R=0, sell_R=0, range_trades=0, mart_up=0, mart_dn=0)
        return out
    pf = lambda x: (x[x.net > 0].net.sum() / abs(x[x.net < 0].net.sum())) if (x.net < 0).any() else float("inf")
    tr = tr.assign(month=pd.to_datetime(tr.close_time).dt.strftime("%Y-%m"))
    mo = tr.groupby("month").r_net.sum()
    is_, oos = tr[tr.close_time < OOS], tr[tr.close_time >= OOS]
    out.update({
        "IS_n": len(is_), "IS_R": round(is_.r_net.sum(), 2), "IS_PF": round(pf(is_), 3) if len(is_) else 0.0,
        "OOS_n": len(oos), "OOS_R": round(oos.r_net.sum(), 2), "OOS_PF": round(pf(oos), 3) if len(oos) else 0.0,
        "months_pos": int((mo > 0).sum()), "months": int(len(mo)), "worst_month_R": round(mo.min(), 2),
        "gross_loss": round(tr[tr.net < 0].net.sum(), 0),
        "return_over_dd": round(s["return_%"] / abs(s["max_dd_%"]), 2) if s.get("max_dd_%") else float("nan"),
        "buy_R": round(tr[tr.side == "buy"].r_net.sum(), 2), "sell_R": round(tr[tr.side == "sell"].r_net.sum(), 2),
        "range_trades": int((tr.regime == "range").sum()), "mart_up": int((tr.mart_step > 0).sum()),
        "mart_dn": int((tr.mart_step < 0).sum()),
    })
    for tf in ("M5", "M10", "M15", "M30", "H1"):
        x = tr[tr.tf == tf]
        out[f"{tf}_n"] = len(x)
        out[f"{tf}_R"] = round(x.r_net.sum(), 2)
    return out


def fmt(name, j) -> str:
    return (f"{name:<30} n {j['trades']:4d} ret {j['return_%']:+8.2f}% DD {j['max_dd_%']:6.2f} PF {j['profit_factor']:5.3f} "
            f"win {j['win_%']:4.1f} | IS R {j['IS_R']:6.1f} PF {j['IS_PF']:4.2f} | OOS R {j['OOS_R']:6.1f} PF {j['OOS_PF']:4.2f} "
            f"| mo+ {j['months_pos']:2d}/{j['months']:2d} worst {j['worst_month_R']:5.1f} r/dd {j['return_over_dd']:5.1f}")


# ------------------------------------------------------------------ variants: (name, trader_override, filter, cfilter)
def variants(stage: str) -> list[tuple[str, str, str | None, str | None]]:
    V: list[tuple[str, str, str | None, str | None]] = [("ref", "", None, None)]
    if stage in ("all", "base"):
        V += [
            ("nomart", "mart_mode=", None, None),
            ("noregime", "regime_metric=", None, None),
            ("nomart_noregime", "mart_mode=,regime_metric=", None, None),
            ("mart_allsides", "mart_sides=", None, None),
            ("mart_sell", "mart_sides=sell", None, None),
            ("mart_shrink", "mart_mode=mult,mart_mult=0.5,mart_tfs=,mart_sides=,mart_ungated_scale=1", None, None),
            ("nofilter", "", "", ""),
            ("tf_htf", "timeframes=M10|M15|M30|H1", None, None),
            ("tf_M15up", "timeframes=M15|M30|H1", None, None),
            ("tf_M30up", "timeframes=M30|H1", None, None),
            ("tf_M5M10", "timeframes=M5|M10", None, None),
            ("buys", "sides=buy", None, None),
            ("sells", "sides=sell", None, None),
        ]
    if stage in ("all", "filter"):
        for q in (0.50, 0.53, 0.55, 0.57, 0.60, 0.63):
            V.append((f"q_all{int(round(q * 100))}", "", flt(m5q=max(q, 0.55), m10q=q, m15q=q, hq=q),
                      flt(m5q=max(q, 0.55), m10q=min(q, 0.50), m15q=q, hq=q)))
        for c in (0.06, 0.08, 0.10, 0.12, 0.15, 0.20):
            V.append((f"cost{c}", "", flt(cost=c, m5cost=c), flt(cost=c, m5cost=c, m10q=0.50)))
        V.append(("sess_lon_ny", "", flt(sess="london|preny|ny"), flt(sess="london|preny|ny", m10q=0.50)))
        V.append(("sess_all", "", flt(sess="asia|london|preny|ny|lclose|nypm"), flt(sess="asia|london|preny|ny|lclose|nypm", m10q=0.50)))
        V.append(("sess_noasia", "", flt(sess="london|preny|ny|lclose|nypm"), flt(sess="london|preny|ny|lclose|nypm", m10q=0.50)))
        V.append(("sessALL_lon_ny", "", flt(all_sess="london|preny|ny"), flt(all_sess="london|preny|ny", m10q=0.50)))
        V.append(("sessALL_lon_ny_lc", "", flt(all_sess="london|preny|ny|lclose"), flt(all_sess="london|preny|ny|lclose", m10q=0.50)))
        V.append(("sessALL_noasia", "", flt(all_sess="london|preny|ny|lclose|nypm"), flt(all_sess="london|preny|ny|lclose|nypm", m10q=0.50)))
        V.append(("sessALL_asia_lon", "", flt(all_sess="asia|london|preny"), flt(all_sess="asia|london|preny", m10q=0.50)))
        for k in ("OB|IMB", "OB|IMB|UW", "IMB|UW", "OB|UW", "OB|IMB|HB|BB"):
            V.append((f"kinds_{k.replace('|', '')}", "", flt(kinds=k), flt(kinds=k, m10q=0.50)))
    if stage in ("all", "ladder"):
        for name, lv in (("lad_tight", "0.5|1.0|1.5|2.5"), ("lad_short", "0.4|0.8|1.2|2.0"), ("lad_mid", "0.6|1.2|2.0|3.0"),
                         ("lad_two", "0.6|1.5"), ("lad_one1", "1.0"), ("lad_one15", "1.5"), ("lad_wide", "0.8|1.6|3.2|6.4"),
                         ("lad_3", "0.6|1.2|2.4")):
            fr = "|".join(["1"] * len(lv.split("|")))
            V.append((name, f"tp_levels={lv},tp_fracs={fr}", None, None))
        V.append(("lad_tight_lock", "tp_levels=0.5|1.0|1.5|2.5,tp_fracs=1|1|1|1,sl_after_leg=0|0.3|x|x", None, None))
        V.append(("lad_ref_lock", "sl_after_leg=0|0.3|x|x", None, None))
        V.append(("lad_ref_lock2", "sl_after_leg=0|0.6|1.2|x", None, None))
        V.append(("lad_ref_nobe", "sl_after_leg=x|0|x|x", None, None))
        V.append(("lad_ref_nobe2", "sl_after_leg=x|x|0|x", None, None))
        V.append(("lad_ref_be2", "sl_after_leg=x|0|0.6|x", None, None))
        V.append(("trail_1R", "trail_r=1.0,trail_start_r=1.0", None, None))
        V.append(("maxhold_2d", "max_hold_min=2880", None, None))
        V.append(("maxhold_1d", "max_hold_min=1440", None, None))
        V.append(("slbuf_0.1", "sl_buffer_atr=0.1", None, None))
        V.append(("slbuf_0.2", "sl_buffer_atr=0.2", None, None))
        V.append(("entry_in_0.2", "entry_offset_frac=0.2", None, None))
        V.append(("entry_in_0.35", "entry_offset_frac=0.35", None, None))
    if stage in ("all", "regime"):
        for th in (0.8, 0.9, 1.1, 1.2):
            V.append((f"reg_adr{th}", f"regime_threshold={th}", None, None))
        V.append(("reg_er0.3", "regime_metric=er,regime_threshold=0.3", None, None))
        V.append(("reg_range_tight2", "range_tp_levels=0.4|0.8|1.2|2.0", None, None))
        V.append(("reg_range_scale0.5", "range_risk_scale=0.5", None, None))
        V.append(("reg_range_off", "range_risk_scale=0", None, None))
        V.append(("reg_inverse", "range_tp_levels=0.6|1.2|2.4|4.8,range_sl_after_leg=,tp_levels=0.5|1.0|1.5|2.5,sl_after_leg=0|0.3|x|x", None, None))
    if stage in ("all", "risk"):
        for mo in (2, 3, 6, 8):
            V.append((f"maxopen{mo}", f"max_open_positions={mo}", None, None))
        V.append(("dedupe_cross", "dedupe_cross_tf=true", None, None))
        V.append(("overlap_allow", "overlap_mode=allow", None, None))
        V.append(("persist", "order_policy=persist", None, None))
        V.append(("keep_replaced0", "keep_replaced_bars=0", None, None))
        V.append(("keep_replaced3", "keep_replaced_bars=3", None, None))
        V.append(("reentry", "reentry_bars=20,reentry_max=1", None, None))
        V.append(("mart2.0", "mart_mult=2.0", None, None))
        V.append(("mart_cap2", "mart_max_risk_pct=2", None, None))
        V.append(("mart_scope_all", "mart_scope=all", None, None))
        V.append(("mart_dn0.7", "mart_ungated_scale=0.7", None, None))
        V.append(("mart_dn1", "mart_ungated_scale=1", None, None))
    return V


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="all")
    ap.add_argument("--only", default="")
    ap.add_argument("--extra", default="", help="name=override;name=override ... ad-hoc variants (filters unchanged)")
    ap.add_argument("--base", default="", help="override applied to EVERY variant (stack on a new base)")
    ap.add_argument("--base-filter", default=None)
    ap.add_argument("--base-cfilter", default=None)
    ap.add_argument("--tag", default="")
    a = ap.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    m1 = load_eurusd()
    sel = load_sel()
    spec = eurusd_spec()
    V = variants(a.stage) if not a.extra else [("ref", "", None, None)]
    if a.extra:
        for part in a.extra.split(";"):
            if part.strip():
                n, _, o = part.partition("=")
                V.append((n.strip(), o.strip(), None, None))
    if a.only:
        keep = set(a.only.split(","))
        V = [v for v in V if v[0] in keep]
    rows = []
    for name, over, f, cf in V:
        key = (a.tag + "_" if a.tag else "") + name
        p = OUT / f"{key}.json"
        if p.exists():
            j = json.load(open(p))
            print(fmt(key, j) + " [cached]", flush=True)
            rows.append(j)
            continue
        t0 = time.time()
        t = lu.v14a_config(a.base).override(over)
        if a.base_filter is not None:
            t.trade_filter = a.base_filter
        if a.base_cfilter is not None:
            t.confluence_filter = a.base_cfilter
        if f is not None:
            t.trade_filter = f
        if cf is not None:
            t.confluence_filter = cf
        res = lu.PortfolioSimulator(m1, sel, t, spec).run()
        j = judge(res)
        j.update(name=key, over=over, filter=t.trade_filter, cfilter=t.confluence_filter, sec=round(time.time() - t0, 1))
        json.dump(j, open(p, "w"), indent=1, default=str)
        res.trades.to_csv(OUT / f"{key}_trades.csv", index=False)
        print(fmt(key, j) + f" [{j['sec']}s]", flush=True)
        rows.append(j)
    df = pd.DataFrame(rows)
    out_csv = Path(HERE) / "out" / (f"eurusd_study{('_' + a.tag) if a.tag else ''}.csv")
    df.to_csv(out_csv, index=False)
    print(f"-> {out_csv}")


if __name__ == "__main__":
    main()
