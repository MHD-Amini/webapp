#!/usr/bin/env python3
"""v16c step 4b - judge the stress x6 of the finalists SCENARIO BY SCENARIO against the v16b-A row of the SAME scenario
(study_results/v16b_stress.csv, name C_F2+RS_0.5 = the shipped v16b-A), with the v16c questions:
  less_dd      max DD better by >= 0.25 pt  AND  OOS max DD not worse  AND  ulcer <= ref
  hold_profit  net >= 0.97 x ref  AND  PF >= ref - 0.10  AND  OOS net >= 0.97 x ref
  hold_loss    sl <= ref + 1 pt  AND  gross loss <= 1.05 x ref  AND  worst day >= ref - 0.25 pt
  hold_oos     OOS PF >= ref - 0.10  AND  OOS sl <= ref + 1 pt  AND  months_pos == ref months_pos
Writes study_results/v16c_stress_judged.csv (one row per finalist x scenario, with the reference values) and
study_results/v16c_stress_summary.csv (per finalist: scenarios passed per question, DD pt gained summed, net delta summed).
    python3 judge_v16c_stress.py
"""
import pandas as pd

SR = "study_results"
REF_NAME = "C_F2+RS_0.5"
Q = ["less_dd", "hold_profit", "hold_loss", "hold_oos"]


def judge_row(r: pd.Series, ref: pd.Series) -> dict:
    out = {
        "less_dd": bool(r["max_dd_%"] >= ref["max_dd_%"] + 0.25 and r["OOS_max_dd_%"] >= ref["OOS_max_dd_%"] and r["ulcer"] <= ref["ulcer"]),
        "hold_profit": bool(r["net_$"] >= 0.97 * ref["net_$"] and r["profit_factor"] >= ref["profit_factor"] - 0.10
                            and r["OOS_net_$"] >= 0.97 * ref["OOS_net_$"]),
        "hold_loss": bool(r["sl_%"] <= ref["sl_%"] + 1.0 and abs(r["gross_loss_$"]) <= abs(ref["gross_loss_$"]) * 1.05
                          and r["worst_day_%eq"] >= ref["worst_day_%eq"] - 0.25),
        "hold_oos": bool(r["OOS_PF"] >= ref["OOS_PF"] - 0.10 and r["OOS_sl_%"] <= ref["OOS_sl_%"] + 1.0
                         and r["months_pos"] >= ref["months_pos"]),
    }
    out["score"] = sum(out.values())
    out["d_dd_pt"] = round(r["max_dd_%"] - ref["max_dd_%"], 2)
    out["d_oos_dd_pt"] = round(r["OOS_max_dd_%"] - ref["OOS_max_dd_%"], 2)
    out["d_ulcer"] = round(r["ulcer"] - ref["ulcer"], 3)
    out["d_net_$"] = round(r["net_$"] - ref["net_$"], 2)
    out["net_%ref"] = round(100 * r["net_$"] / ref["net_$"], 1) if ref["net_$"] else float("nan")
    out["d_sl_pt"] = round(r["sl_%"] - ref["sl_%"], 1)
    out["d_wd_pt"] = round(r["worst_day_%eq"] - ref["worst_day_%eq"], 2)
    out["misses"] = ";".join(
        m for m, bad in (
            (f"DD {r['max_dd_%']} vs {ref['max_dd_%']}", r["max_dd_%"] < ref["max_dd_%"] + 0.25),
            (f"OOS DD {r['OOS_max_dd_%']} vs {ref['OOS_max_dd_%']}", r["OOS_max_dd_%"] < ref["OOS_max_dd_%"]),
            (f"ulcer {r['ulcer']} vs {ref['ulcer']}", r["ulcer"] > ref["ulcer"]),
            (f"net {r['net_$']:.0f} < 97% of {ref['net_$']:.0f}", r["net_$"] < 0.97 * ref["net_$"]),
            (f"PF {r['profit_factor']} vs {ref['profit_factor']}", r["profit_factor"] < ref["profit_factor"] - 0.10),
            (f"OOS net {r['OOS_net_$']:.0f} < 97% of {ref['OOS_net_$']:.0f}", r["OOS_net_$"] < 0.97 * ref["OOS_net_$"]),
            (f"sl {r['sl_%']} vs {ref['sl_%']}", r["sl_%"] > ref["sl_%"] + 1.0),
            (f"gl {r['gross_loss_$']:.0f} vs {ref['gross_loss_$']:.0f}", abs(r["gross_loss_$"]) > abs(ref["gross_loss_$"]) * 1.05),
            (f"wd {r['worst_day_%eq']} vs {ref['worst_day_%eq']}", r["worst_day_%eq"] < ref["worst_day_%eq"] - 0.25),
            (f"OOS PF {r['OOS_PF']} vs {ref['OOS_PF']}", r["OOS_PF"] < ref["OOS_PF"] - 0.10),
            (f"OOS sl {r['OOS_sl_%']} vs {ref['OOS_sl_%']}", r["OOS_sl_%"] > ref["OOS_sl_%"] + 1.0),
            (f"months {r['months_pos']} vs {ref['months_pos']}", r["months_pos"] < ref["months_pos"]),
        ) if bad)
    return out


def main():
    st = pd.read_csv(f"{SR}/v16c_stress.csv")
    ref = pd.read_csv(f"{SR}/v16b_stress.csv")
    ref = ref[ref.name == REF_NAME].set_index("tag")
    rows = []
    for _, r in st.iterrows():
        if r["tag"] not in ref.index:
            continue
        rf = ref.loc[r["tag"]]
        d = {"name": r["name"], "tag": r["tag"], "trades": r["trades"], "net_$": r["net_$"], "OOS_net_$": r["OOS_net_$"],
             "max_dd_%": r["max_dd_%"], "ulcer": r["ulcer"], "profit_factor": r["profit_factor"], "sl_%": r["sl_%"],
             "gross_loss_$": r["gross_loss_$"], "worst_day_%eq": r["worst_day_%eq"], "OOS_PF": r["OOS_PF"], "OOS_sl_%": r["OOS_sl_%"],
             "OOS_max_dd_%": r["OOS_max_dd_%"], "months_pos": r["months_pos"],
             "ref_net_$": rf["net_$"], "ref_max_dd_%": rf["max_dd_%"], "ref_ulcer": rf["ulcer"], "ref_PF": rf["profit_factor"],
             "ref_sl_%": rf["sl_%"], "ref_gross_loss_$": rf["gross_loss_$"], "ref_worst_day_%eq": rf["worst_day_%eq"],
             "ref_OOS_PF": rf["OOS_PF"], "ref_OOS_sl_%": rf["OOS_sl_%"], "ref_OOS_max_dd_%": rf["OOS_max_dd_%"],
             "ref_months_pos": rf["months_pos"]}
        d.update(judge_row(r, rf))
        rows.append(d)
    df = pd.DataFrame(rows)
    df.to_csv(f"{SR}/v16c_stress_judged.csv", index=False)
    g = df.groupby("name")
    summ = pd.DataFrame({
        "scenarios": g.size(),
        "less_dd": g.less_dd.sum(), "hold_profit": g.hold_profit.sum(), "hold_loss": g.hold_loss.sum(), "hold_oos": g.hold_oos.sum(),
        "all4": g.apply(lambda x: int((x.score == 4).sum())), "score_sum": g.score.sum(),
        "d_dd_pt_sum": g["d_dd_pt"].sum().round(2), "d_net_$_sum": g["d_net_$"].sum().round(0),
        "net_%ref_min": g["net_%ref"].min().round(1),
        "dd_better_in": g.apply(lambda x: int((x.d_dd_pt >= 0.25).sum())),
        "oos_dd_ok_in": g.apply(lambda x: int((x.d_oos_dd_pt >= 0).sum())),
        "ulcer_ok_in": g.apply(lambda x: int((x.d_ulcer <= 0).sum())),
        "net_held_in": g.apply(lambda x: int((x["net_$"] >= 0.97 * x["ref_net_$"]).sum())),
        "months_ok_in": g.apply(lambda x: int((x.months_pos >= x.ref_months_pos).sum())),
    }).sort_values(["all4", "score_sum", "d_dd_pt_sum"], ascending=False)
    summ.to_csv(f"{SR}/v16c_stress_summary.csv")
    pd.set_option("display.width", 300)
    print("=== v16c STRESS x6 vs the v16b-A row of the same scenario ===")
    print(summ.to_string())
    print("\n=== misses per scenario ===")
    for _, r in df.sort_values(["name", "tag"]).iterrows():
        print(f"{r['name']:<34} {r['tag']:<14} score {r['score']} dDD {r['d_dd_pt']:+.2f} net {r['net_%ref']:5.1f}% | {r['misses']}")


if __name__ == "__main__":
    main()
