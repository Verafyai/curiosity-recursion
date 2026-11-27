#!/usr/bin/env bash
# Offline mock-archive bench for the v0.2 acceptance check (spec section 13.2): no network, no model.
#   scripts/run-mock-bench.sh [--out /tmp/cr-mock-bench] [--budget 100] [--conditions B6-swarm,B6-no-ledger,B6-no-parallel]
# Needs a Temporal dev server on localhost:7233. Uses the synthetic subjects in fixtures/mock/subjects.jsonl and
# the synthetic archive in cr/sources/mock_live.py (CR_SOURCES=mock). Then runs scripts/check_mock_bench.py.
set -euo pipefail
cd "$(dirname "$0")/.."
OUT=/tmp/cr-mock-bench; BUDGET=100; CONDS=B6-swarm,B6-no-ledger,B6-no-parallel; SUBJ=mock-tester
while [ $# -gt 0 ]; do case "$1" in
  --out) OUT=$2; shift 2;; --budget) BUDGET=$2; shift 2;; --conditions) CONDS=$2; shift 2;; --subject) SUBJ=$2; shift 2;;
  *) echo "unknown arg $1"; exit 2;; esac; done
mkdir -p "$OUT/runs" "$OUT/logs" "$OUT/work" "$OUT/ledgers"
export CR_SOURCES=mock CR_EXCLUDE=1
for c in ${CONDS//,/ }; do
  n=$c-$SUBJ-b$BUDGET-s1
  rm -f "$OUT/runs/$n.jsonl" "$OUT/logs/$n.tools.jsonl"
  CR_TOOL_LOG="$OUT/logs/$n.tools.jsonl" CR_BLOCK_LOG="$OUT/logs/$n.blocked.jsonl" \
    .venv/bin/python bench/harness.py --agents "$c" --budgets "$BUDGET" --subjects "$SUBJ" --subjects-file fixtures/mock/subjects.jsonl \
    --seed-list 1 --concurrency 1 --tag "_mock_${n}_$(date +%s)" --workdir "$OUT/work" --out "$OUT/runs/$n.jsonl" \
    --ledger-dir "$OUT/ledgers" --ledger-stem "$n" > "$OUT/logs/$n.out" 2>&1
  echo "done $n"
done
.venv/bin/python scripts/check_mock_bench.py "$OUT" --budget "$BUDGET"
