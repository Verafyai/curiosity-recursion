"""Cohen's kappa between two filled sheets: python eval/adjudicate/kappa.py rater1.csv rater2.csv"""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from eval.stats import cohen_kappa  # noqa: E402

a = {r["item"]: r["rater_label"] for r in csv.DictReader(open(sys.argv[1]))}
b = {r["item"]: r["rater_label"] for r in csv.DictReader(open(sys.argv[2]))}
items = sorted(k for k in a if k in b and a[k] and b[k])
print(f"items rated by both: {len(items)}; kappa = {cohen_kappa([a[k] for k in items], [b[k] for k in items]):.3f}")
