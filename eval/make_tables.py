"""Print the saved forecast comparison (results/compare.csv) as tables, so every number in the paper traces to a file."""
import csv, os

P = os.path.join(os.path.dirname(__file__), "..", "results", "compare.csv")
with open(P, newline="") as f:
    rows = list(csv.DictReader(f))
models = ["naive", "seasonal", "ridge", "ets", "arima", "lgbm_aci"]
crops = list(dict.fromkeys(r["crop"] for r in rows))
v = {(r["crop"], r["model"]): r for r in rows}
for metric, title in (("mape", "MAPE %"), ("cover", "Interval coverage % (target 90)"), ("width", "Interval width, % of price")):
    print(f"\n{title}")
    print("crop," + ",".join(models))
    for c in crops:
        print(c + "," + ",".join(f"{float(v[(c, m)][metric]):.1f}" for m in models))
for base in ("naive", "ridge"):
    w = [c for c in crops if float(v[(c, "lgbm_aci")]["mape"]) < float(v[(c, base)]["mape"])]
    print(f"\nlgbm_aci has lower MAPE than {base} in {len(w)}/{len(crops)} crops: {', '.join(w)}")
