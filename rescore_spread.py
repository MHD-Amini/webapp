"""Apply a minimum spread to every fill (the MT5 export has spread=0 for Sep 2025-Mar 2026)."""
import pickle, sys
import numpy as np
from lubot.study import SCENARIOS, save_study
out = sys.argv[1]; floor = float(sys.argv[2])
df = pickle.load(open(f"{out}/touches.pkl", "rb"))
r = df.reached
new = np.where(df.spread < floor, floor, df.spread)
delta = new - df.spread
risk_basic = df.zone_h + 0.1 * df.atr_at_selection
df.loc[r, "net_r_1"] = df.loc[r, "outcome_r_1"] - new[r] / risk_basic[r]
df.loc[r, "net_r_2"] = df.loc[r, "outcome_r_2"] - new[r] / risk_basic[r]
for name, entry, slb, tp in SCENARIOS:
    risk = df.zone_h * (1.0 if entry == "edge" else 0.5) + slb * df.atr_at_selection
    df.loc[r, f"sc_{name}"] = df.loc[r, f"sc_{name}"] - delta[r] / risk[r]
df["spread"] = new
pickle.dump(df, open(f"{out}/touches.pkl", "wb"))
save_study({"df": df}, out)
print("spread floor applied:", floor)
