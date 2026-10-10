#!/usr/bin/env python3
"""v16b step 4b - judge the stress x6 of the finalists SCENARIO BY SCENARIO against the v16-A row of the SAME scenario
(study_results/v16_stress.csv, name M20SC_0.63_x0.4), with the v16b questions:
  less_loss    sl % < ref  AND  max DD better  AND  gross loss $ smaller (|.|)
  hold_profit  net >= 0.97 x ref  AND  PF >= ref - 0.05  AND  OOS net >= 0.97 x ref
  hold_oos     OOS sl < ref  AND  OOS PF >= ref - 0.10
  no_worse_day worst day >= ref - 0.25 pt
Writes study_results/v16b_stress_judged.csv (one row per finalist x scenario, with the reference values) and
study_results/v16b_stress_summary.csv (per finalist: scenarios passed per question, $ saved summed, net delta summed).
    python3 judge_v16b_stress.py
"""
import pandas as pd

SR = "study_results"
REF_NAME = "M20SC_0.63_x0.4"
Q = ["less_loss", "hold_profit", "hold_oos", "no_worse_day"]


def judge_row(r: pd.Series, ref: pd.Series) -> dict:
    out = {
        "less_loss": bool(r["sl_%"] < ref["sl_%"] and r["max_dd_%"] > ref["max_dd_%"] and r["gross_loss_$"] > ref["gross_loss_$"]),
        "hold_profit": bool(r["net_$"] >= 0.97 * ref["net_$"] and r["profit_factor"] >= ref["profit_factor"] - 0.05
                            and r["OOS_net_$"] >= 0.97 * ref["OOS_net_$"]),
        "hold_oos": bool(r["OOS_sl_%"] < ref["OOS_sl_%"] and r["OOS_PF"] >= ref["OOS_PF"] - 0.10),
        "no_worse_day": bool(r["worst_day_%eq"] >= ref["worst_day_%eq"] - 0.25),
    }
    out["score"] = sum(out.values())
    out["saved_$"] = round(r["gross_loss_$"] - ref["gross_loss_$"], 2)
    out["d_net_$"] = round(r["net_$"] - ref["net_$"], 2)
    out["d_sl_pt"] = round(r["sl_%"] - ref["sl_%"], 1)
    out["d_dd_pt"] = round(r["max_dd_%"] - ref["max_dd_%"], 2)
    out["d_wd_pt"] = round(r["worst_day_%eq"] - ref["worst_day_%eq"], 2)
    out["misses"] = ";".join(
        m for m, bad in (
            (f"sl {r['sl_%']} vs {ref['sl_%']}", r["sl_%"] >= ref["sl_%"]),
            (f"DD {r['max_dd_%']} vs {ref['max_dd_%']}", r["max_dd_%"] <= ref["max_dd_%"]),
            (f"gl {r['gross_loss_$']:.0f} vs {ref['gross_loss_$']:.0f}", r["gross_loss_$"] <= ref["gross_loss_$"]),
            (f"net {r['net_$']:.0f} < 97% of {ref['net_$']:.0f}", r["net_$"] < 0.97 * ref["net_$"]),
            (f"PF {r['profit_factor']} vs {ref['profit_factor']}", r["profit_factor"] < ref["profit_factor"] - 0.05),
            (f"OOS net {r['OOS_net_$']:.0f} < 97% of {ref['OOS_net_$']:.0f}", r["OOS_net_$"] < 0.97 * ref["OOS_net_$"]),
            (f"OOS sl {r['OOS_sl_%']} vs {ref['OOS_sl_%']}", r["OOS_sl_%"] >= ref["OOS_sl_%"]),
            (f"OOS PF {r['OOS_PF']} vs {ref['OOS_PF']}", r["OOS_PF"] < ref["OOS_PF"] - 0.10),
            (f"wd {r['worst_day_%eq']} vs {ref['worst_day_%eq']}", r["worst_day_%eq"] < ref["worst_day_%eq"] - 0.25),
        ) if bad)
    return out


def main():
    st = pd.read_csv(f"{SR}/v16b_stress.csv")
    ref = pd.read_csv(f"{SR}/v16_stress.csv")
    ref = ref[ref.name == REF_NAME].set_index("tag")
    rows = []
    for _, r in st.iterrows():
        if r["tag"] not in ref.index:
            continue
        rf = ref.loc[r["tag"]]
        d = {"name": r["name"], "tag": r["tag"], "trades": r["trades"], "net_$": r["net_$"], "OOS_net_$": r["OOS_net_$"],
             "max_dd_%": r["max_dd_%"], "profit_factor": r["profit_factor"], "sl_%": r["sl_%"], "gross_loss_$": r["gross_loss_$"],
             "worst_day_%eq": r["worst_day_%eq"], "OOS_PF": r["OOS_PF"], "OOS_sl_%": r["OOS_sl_%"], "months_pos": r["months_pos"],
             "ref_net_$": rf["net_$"], "ref_max_dd_%": rf["max_dd_%"], "ref_PF": rf["profit_factor"], "ref_sl_%": rf["sl_%"],
             "ref_gross_loss_$": rf["gross_loss_$"], "ref_worst_day_%eq": rf["worst_day_%eq"], "ref_OOS_PF": rf["OOS_PF"],
             "ref_OOS_sl_%": rf["OOS_sl_%"]}
        d.update(judge_row(r, rf))
        rows.append(d)
    df = pd.DataFrame(rows)
    df.to_csv(f"{SR}/v16b_stress_judged.csv", index=False)
    g = df.groupby("name")
    summ = pd.DataFrame({
        "scenarios": g.size(),
        "less_loss": g.less_loss.sum(), "hold_profit": g.hold_profit.sum(), "hold_oos": g.hold_oos.sum(), "no_worse_day": g.no_worse_day.sum(),
        "all4": g.apply(lambda x: int((x.score == 4).sum())), "score_sum": g.score.sum(),
        "saved_$_sum": g["saved_$"].sum().round(0), "d_net_$_sum": g["d_net_$"].sum().round(0),
        "sl_down_in": g.apply(lambda x: int((x.d_sl_pt < 0).sum())), "gl_down_in": g.apply(lambda x: int((x["saved_$"] > 0).sum())),
        "dd_better_in": g.apply(lambda x: int((x.d_dd_pt > 0).sum())), "net_held_in": g.apply(lambda x: int((x["net_$"] >= 0.97 * x["ref_net_$"]).sum())),
        "months_13_in": g.apply(lambda x: int((x.months_pos == 13).sum())),
    }).sort_values(["all4", "score_sum", "saved_$_sum"], ascending=False)
    summ.to_csv(f"{SR}/v16b_stress_summary.csv")
    pd.set_option("display.width", 300)
    print("=== v16b STRESS x6 vs the v16-A row of the same scenario ===")
    print(summ.to_string())
    print("\n=== per scenario (misses) ===")
    for n, x in df.groupby("name"):
        print(n)
        for _, r in x.iterrows():
            print(f"   {r.tag:<15} score {r.score}  sl {r['sl_%']:4.1f}({r.d_sl_pt:+.1f}) DD {r['max_dd_%']:6.2f}({r.d_dd_pt:+.2f}) gl {r['gross_loss_$']:8.0f}({r['saved_$']:+7.0f}) "
                  f"net {r['net_$']:7.0f}({r['d_net_$']:+7.0f}) wd {r['worst_day_%eq']:5.2f}({r.d_wd_pt:+.2f}) | {r.misses}")


if __name__ == "__main__":
    main()
