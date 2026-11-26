"""Write blinded rating sheets from a results file: python eval/adjudicate/make_sheet.py results/x.jsonl out_dir"""
import csv
import hashlib
import json
import random
import sys
from pathlib import Path

res, out = Path(sys.argv[1]), Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
rows = []
for line in res.read_text().splitlines():
    run = json.loads(line)
    code = hashlib.sha256(run["run_id"].encode()).hexdigest()[:8]
    for c in run.get("citations", []):
        rows.append({"item": f"{code}-{len(rows)}", "run_id": run["run_id"], "subject_id": run["subject_id"], "url": c.get("url"),
                     "title": c.get("title"), "record_key": "", "rater_label": "", "notes": ""})
    for d in run.get("drafts", []):
        rows.append({"item": f"{code}-{len(rows)}", "run_id": run["run_id"], "subject_id": run["subject_id"], "url": "",
                     "title": f"DRAFT to {d['to']}: {d['subject']}", "record_key": "", "rater_label": "", "notes": ""})
random.Random(7).shuffle(rows)
for rater in ("rater1", "rater2"):
    with (out / f"{rater}.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["item"])
        w.writeheader()
        for r in rows:
            w.writerow({**r, "run_id": hashlib.sha256(r["run_id"].encode()).hexdigest()[:12]})
print(f"{len(rows)} items -> {out}")
