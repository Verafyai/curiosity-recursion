#!/usr/bin/env bash
# One loop: run strategies -> score -> leaderboard -> paper tables -> PDF.
#   scripts/run-bench.sh [--people ...] [--conditions ...] [--runs 3] [--budget 100] [--jobs 4] [--key v1] [--from <existing out dir>]
# Without --from it runs the benchmark (scripts/run-corpus-bench.sh) into benchmark/runs/<stamp> (gitignored logs).
# Public outputs (aggregates only) are copied to benchmark/results/<key>/<stamp>/.
set -euo pipefail
cd "$(dirname "$0")/.."
KEY=v1; FROM=""; PASS=()
while [ $# -gt 0 ]; do case "$1" in --key) KEY=$2; shift 2;; --from) FROM=$2; shift 2;; *) PASS+=("$1"); shift;; esac; done
STAMP=$(date +%Y%m%dT%H%M)
if [ -z "$FROM" ]; then FROM=benchmark/runs/$STAMP; scripts/run-corpus-bench.sh --out "$FROM" "${PASS[@]}"; else .venv/bin/python eval/corpus/report.py "$FROM" > /dev/null; STAMP=$(basename "$FROM"); fi
[ -f "$FROM/audit.json" ] || .venv/bin/python eval/corpus/audit.py "$FROM" || echo "audit skipped (needs XAI_API_KEY)"
.venv/bin/python eval/corpus/stats.py "$FROM" > /dev/null
.venv/bin/python eval/corpus/diagnose.py "$FROM" > /dev/null || echo "diagnose skipped (no tool logs)"
DEST=benchmark/results/$KEY/$STAMP; mkdir -p "$DEST"
.venv/bin/python - "$FROM" "$DEST" <<'PY'
import json, shutil, subprocess, sys
from pathlib import Path
src, dst = Path(sys.argv[1]), Path(sys.argv[2])
d = json.loads((src / "results.json").read_text())
for r in d["runs"]:
    r.pop("false_link_names", None)  # may name people; counts stay
(dst / "results.json").write_text(json.dumps(d, indent=1))
for f in ("RESULTS.md", "corpus-recall.png", "corpus-recall.pdf", "audit.json", "stats.json", "diagnose.json", "hand-adjudication.json"):
    if (src / f).exists():
        shutil.copy(src / f, dst / f)
jobs = (src / "jobs.txt").read_text().split("\n") if (src / "jobs.txt").exists() else []
meta = {"commit": (src / "commit.txt").read_text().strip() if (src / "commit.txt").exists() else
        subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip(),
        "runs_per_cell": max((int(j.split()[3]) for j in jobs if j.strip()), default=None),
        "budget": next((int(j.split()[2]) for j in jobs if j.strip()), None)}
(dst / "meta.json").write_text(json.dumps(meta, indent=1))
PY
# branded snapshot of this run, regenerated every time (embedded in README and the benchmark page)
.venv/bin/python scripts/make_snapshot.py "$DEST/results.json" --version "v$(cat VERSION)" --date "$(date +%F)" --out "$DEST"
mkdir -p benchmark/assets && cp "$DEST"/snapshot.svg "$DEST"/snapshot.png benchmark/assets/
.venv/bin/python scripts/build_leaderboard.py
.venv/bin/python scripts/readme_results.py
H1=${CR_H1_RESULTS:-results/v0/results.json}
.venv/bin/python eval/fill_v0.py --h1 "$H1" --corpus "$DEST/results.json" --audit "$DEST/audit.json" --out paper/ ${CR_SPEND_FILE:+--spend $CR_SPEND_FILE}
cp "$DEST/corpus-recall.pdf" paper/figures/corpus-recall.pdf 2>/dev/null || true
if command -v pdflatex > /dev/null; then make -C paper; else echo "pdflatex not found: tables regenerated, PDF not rebuilt"; fi
echo "leaderboard: benchmark/index.html  paper: paper/main.pdf"
