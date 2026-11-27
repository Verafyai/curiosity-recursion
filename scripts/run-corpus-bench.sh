#!/usr/bin/env bash
# Corpus-replication benchmark: run strategies -> score -> leaderboard tables and chart.
# Usage: scripts/run-corpus-bench.sh [--people burnham,homer,john,kingsley,bristol,alex] [--conditions B0,B1,B3,B5,B5-max,B5-fix]
#                                    [--runs 3] [--budget 100] [--jobs 4] [--out benchmark/runs/<stamp>] [--score-only]
# Needs: a Temporal dev server (localhost:7233), .venv, an LLM key for B0/B1 (XAI_API_KEY or OPENAI_API_KEY with
# CR_LLM_API), and for the content guard CR_DOSSIER_NGRAMS (hashed 8-grams built by eval/exclusion/build_ngrams.py).
set -euo pipefail
cd "$(dirname "$0")/.."
PEOPLE=burnham,homer,john,kingsley,bristol,alex; CONDS=B0,B1,B3,B5,B5-max,B5-fix; RUNS=3; BUDGET=100; JOBS=4
OUT=benchmark/runs/$(date +%Y%m%dT%H%M); SCORE_ONLY=0
while [ $# -gt 0 ]; do case "$1" in
  --people) PEOPLE=$2; shift 2;; --conditions) CONDS=$2; shift 2;; --runs) RUNS=$2; shift 2;;
  --budget) BUDGET=$2; shift 2;; --jobs) JOBS=$2; shift 2;; --out) OUT=$2; shift 2;; --score-only) SCORE_ONLY=1; shift;;
  *) echo "unknown arg $1"; exit 2;; esac; done
mkdir -p "$OUT/runs" "$OUT/logs" "$OUT/work"
export CR_EXCLUDE=1
if [ -n "${CR_DOSSIER_NGRAMS:-}" ]; then export CR_REQUIRE_NGRAMS=1; else echo "warning: CR_DOSSIER_NGRAMS unset; host blocklist only, no content guard" >&2; fi
if [ "$SCORE_ONLY" = 0 ]; then
  : > "$OUT/jobs.txt"
  for s in $(seq 1 "$RUNS"); do for p in ${PEOPLE//,/ }; do for c in ${CONDS//,/ }; do echo "$c $p $BUDGET $s" >> "$OUT/jobs.txt"; done; done; done
  run_one() {
    c=$1; p=$2; b=$3; s=$4; n=$c-$p-b$b-s$s
    [ -s "$OUT/runs/$n.jsonl" ] && return 0
    CR_TOOL_LOG="$OUT/logs/$n.tools.jsonl" CR_BLOCK_LOG="$OUT/logs/$n.blocked.jsonl" \
      .venv/bin/python bench/harness.py --agents "$c" --budgets "$b" --subjects "corpus-$p" --subjects-file eval/corpus/subjects.jsonl \
      --seed-list "$s" --concurrency 1 --tag "_corpus_${n}_$(date +%s)" --workdir "$OUT/work" --out "$OUT/runs/$n.jsonl" > "$OUT/logs/$n.out" 2>&1 \
      || echo "FAILED $n" >> "$OUT/failed.txt"
    touch "$OUT/logs/$n.blocked.jsonl"
    echo "$(date +%T) done $n"
  }
  export -f run_one; export OUT
  xargs -P "$JOBS" -L 1 bash -c 'run_one "$@"' _ < "$OUT/jobs.txt"
fi
.venv/bin/python eval/corpus/report.py "$OUT"
echo "tables: $OUT/RESULTS.md  json: $OUT/results.json  chart: $OUT/corpus-recall.png"
