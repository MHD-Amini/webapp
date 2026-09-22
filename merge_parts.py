import pickle, glob, sys
from pathlib import Path
import pandas as pd
from lubot.study import save_study
OUT = sys.argv[1] if len(sys.argv) > 1 else "study_results"
parts = sorted(glob.glob(f"{OUT}/parts/*/touches.pkl"))
df = pd.concat([pickle.load(open(p, "rb")) for p in parts], ignore_index=True)
out = Path(OUT); out.mkdir(exist_ok=True)
with open(out / "touches.pkl", "wb") as f:
    pickle.dump(df, f)
save_study({"df": df}, out)
print("merged", len(df), "touches from", len(parts), "timeframes")
