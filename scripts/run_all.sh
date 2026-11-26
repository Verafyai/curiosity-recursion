#!/usr/bin/env bash
# Everything, in order, on one machine. Needs `temporal server start-dev` running on :7233.
# Results land in results/; nothing here sends anything anywhere.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PY:-python}
STAMP=$(date -u +%Y%m%dT%H%M%SZ)

$PY -m pytest -q tests

# 1. Rebuild DarkKin-Bench from kin's eval files (never the holdout file).
# $PY bench/convert_kin.py --relatives PATH/relatives.json --heritage PATH/heritage-real.json

# 2. H1 and H4: agents at equal budget on the dev split (B0 and B1 need ANTHROPIC_API_KEY).
$PY bench/harness.py --agents B0,B1,B3,B5 --budgets 25,50,100,200 --seeds 3 --split dev --out results/h1-dev-$STAMP.jsonl

# 3. H2: faults. Same subjects, Temporal (B5) against the plain loop (B4).
for p in 0.1 0.3 0.5; do
  $PY bench/faults.py --agent B5 --fault-p $p --kill-every 45 --subjects kinher-jewish-01,kinher-academic-02 --out results/h2-$STAMP.jsonl
  $PY bench/faults.py --agent B4 --fault-p $p --kill-every 45 --subjects kinher-jewish-01,kinher-academic-02 --out results/h2-$STAMP.jsonl
done

# 4. Ablations on the dev split.
$PY bench/harness.py --agents B5-nomem,B5-nocircuits,B5-noverify,B5-nodedupe,B5-hybrid --budgets 100 --seeds 3 --split dev --out results/ablate-$STAMP.jsonl

# 5. Score (candidates until adjudicated), make rater sheets, then figures once labels exist.
$PY eval/score.py results/h1-dev-$STAMP.jsonl
$PY eval/adjudicate/make_sheet.py results/h1-dev-$STAMP.jsonl results/adjudication-$STAMP
echo "Fill the rater sheets, compute kappa, write labels.csv, then:"
echo "  $PY eval/score.py results/h1-dev-$STAMP.jsonl --labels labels.csv && $PY eval/plots.py results results/h1-dev-$STAMP.scores.jsonl"
echo "The test split and the sealed holdout are run once, after all of this is frozen."
