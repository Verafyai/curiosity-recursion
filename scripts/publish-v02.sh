#!/usr/bin/env bash
# Publish the aggregates of a v0.2 corpus-bench run (no logs, no per-fact tables) and regenerate the
# leaderboard, the v0.2 paper tables and the recall-vs-calls figure. Never pushes, never tags.
#   scripts/publish-v02.sh <run dir from scripts/run-corpus-bench.sh>
# The v0.1 paper tables stay pinned to benchmark/results/v1/20261126T1600 (paper/Makefile CORPUS).
set -euo pipefail
cd "$(dirname "$0")/.."
FROM=${1:?run dir}
STAMP=$(basename "$FROM")-v0.2
DEST=benchmark/results/v1/$STAMP; mkdir -p "$DEST"
.venv/bin/python - "$FROM" "$DEST" <<'PY'
import json, shutil, subprocess, sys
from pathlib import Path
src, dst = Path(sys.argv[1]), Path(sys.argv[2])
def clean(p, q):
    d = json.loads(p.read_text())
    for r in d.get("runs", []):
        r.pop("false_link_names", None)  # may name people; counts stay
    q.parent.mkdir(parents=True, exist_ok=True)
    q.write_text(json.dumps(d, indent=1))
clean(src / "results.json", dst / "results.json")
for t in sorted((src / "truncated").glob("n*/results.json")):
    clean(t, dst / "truncated" / t.parent.name / "results.json")
for f in ("RESULTS.md", "corpus-recall.png", "corpus-recall.pdf", "stats.json", "diagnose.json", "diagnose-runs.json", "h6.json", "connectivity.json"):
    if (src / f).exists():
        shutil.copy(src / f, dst / f)
jobs = (src / "jobs.txt").read_text().split("\n") if (src / "jobs.txt").exists() else []
meta = {"commit": (src / "commit.txt").read_text().strip() if (src / "commit.txt").exists() else
        subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip(),
        "runs_per_cell": max((int(j.split()[3]) for j in jobs if j.strip()), default=None),
        "budget": next((int(j.split()[2]) for j in jobs if j.strip()), None), "release": "v0.2 batch",
        "preregistration": "bench/PREREGISTRATION-v0.2.md"}
(dst / "meta.json").write_text(json.dumps(meta, indent=1))
PY
.venv/bin/python scripts/make_snapshot.py "$DEST/results.json" --version "v0.2 (branch cr-v0.2)" --date "$(date +%F)" --out "$DEST"
.venv/bin/python scripts/build_leaderboard.py
make -C paper tables V02=../$DEST
cp "$DEST/corpus-recall.pdf" paper/figures/v02-corpus-recall.pdf 2>/dev/null || true
echo "published: $DEST"
