# Preregistration: Curiosity Recursion v0.2 (B6 lane swarm)

This file is committed on branch `cr-v0.2` **before any v0.2 live benchmark run**. Its commit hash and
commit time are the freeze point. Nothing in it needs results. Any change made after the run is post hoc
and will be labelled post hoc.

## 1. Hypotheses, metrics and decision rule (verbatim from docs/CR-V0.2-UPGRADE-SPEC.md, section 1)

**Primary metric.** Full-dossier overall recall (score per fact: 1.0 found with a source, 0.5 named the
right book or archive, 0 miss; mean over the six people), answer key v1, unchanged scorer rules except
section 8's flagged addition, which is reported separately.

**Secondary metrics.** Reachable-subset recall; precision; full-credit recall; holdout recall; source
recall; per-era and per-access-tier recall; exact-repeat rate; empty-call rate; calls used of B; revisit
yield (share of ledger-approved revisits that produced a new matched fact); false links; wall time; spend.

**Comparators, rerun in the same batch** (same code commit, same day, same tools): B1 ReAct, B5-fix,
B5 (preregistered v0.1 config). Old v0.1.0 numbers are context only, never the comparison.

- **H6 (main).** At B = 100, B6-swarm's full-dossier overall recall is higher than both B1's and
  B5-fix's.
- **H6-prec.** B6-swarm's precision is not lower than B5-fix's by more than 3 points and is higher
  than B1's.
- **H6-waste.** B6-swarm's exact-repeat rate is below 2% and it uses at least 80% of B on average.
- **H6-ablation.** B6-swarm beats B6-no-ledger and B6-no-parallel on the primary metric (each component
  contributes).
- **H6-budget.** At a matched budget (section 9), B6-swarm still beats B1; i.e. the gain is not only
  from spending more calls.

**Decision rule (preregistered, because significance is not reachable).** The existing test is an exact
sign-flip permutation over per-person means (`eval/corpus/stats.py`). Homer scores 0 for every strategy
and John is near 0, so only about 4 people carry signal and the smallest attainable two-sided p is
2/16 = 0.125. Therefore "beats" means all of: mean per-person difference > 0 on the primary metric; wins
on at least 3 of the 4 people with reachable facts (Burnham, Kingsley, Bristol, Alex), with no loss larger
than 2 points; and the run-to-run sd of B6-swarm does not overlap the comparator's mean. Report the
permutation p and Holm p anyway (add the v0.2 pairs to `PAIRS`), and say plainly that n is too small for
significance. Tuning on any benchmark person makes that person in-sample for the tuned strategy; record it.

## 2. Frozen configuration

All weights, thresholds and rules below were set before any v0.2 live run and are frozen. They are the
values in the code at this commit and in `strategies/B6-swarm/config.json` (written by
`scripts/export_strategy_configs.py` from `bench/harness.py` AGENT_CONFIG and the module constants).

- B6-swarm: `{"mode": "swarm", "generator": "rules2", "outline": "rules", "workers": 4, "ledger": true, "reflect": true, "verify_nodes": true, "tools": "v2"}`
- Value score weights (w_novelty, w_expected_yield, w_reachability, w_gap_fill, w_cost):
  `(0.3, 0.3, 0.15, 0.25, 0.1)` (`cr/leads.py` WEIGHTS); UCT c = 0.7; value floor = 0.05.
- Allocator: UCB1, at least 3 calls per lane in round 1, then blocks of 12 calls per round
  (`round_calls`), a lane closes after 3 dry rounds.
- Ledger: foraging stop after k = 3 empty calls per source; near repeat when word Jaccard >=
  0.8; adjacent-page window 10 pages; at most 3 relative hops; revisit novelty by key
  `{"adjacent_pages": 0.8, "relative_name": 0.7, "different_collection": 0.6, "name_variant": 0.5, "date_window": 0.5, "result_offset": 0.4}`.
- Ablations: B6-no-ledger = same with `ledger=False`; B6-no-parallel = same with `workers=1`.
- B1: the v0.1 ReAct agent (`bench/baselines/llm_agents.py`, grok-4.20-0309-non-reasoning via the xAI API,
  temperature 1.0) with `ia_fts` added to its tools, so the comparison is tool-matched. B5 and B5-fix: the v0.1
  configurations, unchanged.
- Scorer: answer key v1 (`eval/answer_keys/v1`, hash-locked in LOCK.json), scorer rules v1.1, unchanged. The
  only scorer additions are budget-matched truncation (`--truncate-calls N`) and keying `ia_inside_pages`
  results like `ia_inside` (same book, same key). No v1.2 partial-credit rule is used.
- Exclusion filter (`cr/sources/exclusion.py`), answer keys and input cards: byte-identical to v0.1.0
  (enforced by `tests/test_guardrails.py`).

## 3. Run

```
scripts/run-corpus-bench.sh --conditions B1,B5,B5-fix,B6-swarm,B6-no-ledger,B6-no-parallel --runs 3 --budget 100 --jobs 4
```
Six people (burnham, homer, john, kingsley, bristol, alex), seeds 1 to 3, B = 100, exclusion filter on,
content guard on. All six conditions run in one batch from this code commit. Model spend is approved for
B1 only; B5 and B6 must have zero model tokens (checked from the run files before reporting).
Before the run: a connectivity and throttle check of archive.org, loc.gov and wikidata.org. During and
after: Wikidata HTTP 429 counts per run (`eval/corpus/diagnose.py`); if 429s hit some strategies and not
others, the comparison is stopped and reported, not silently kept.

## 4. Operational definitions (fixed now, computed by `eval/corpus/h6.py`)

- **Primary metric**: `overall_recall` in `results.json` (mean over the six people of the per-person mean
  over runs; per fact 1.0 / 0.5 / 0).
- **"A beats C"**: (1) mean per-person difference in recall > 0; (2) A wins on at least 3 of burnham,
  kingsley, bristol, alex and loses none of those by more than 2 points; (3) A's mean minus one sd of its
  per-seed overall recall (3 seeds) is above C's mean per-seed overall recall. All three must hold.
- **H6**: B6-swarm beats B1 and beats B5-fix.
- **H6-prec**: precision = mean over people of per-person precision; B6-swarm >= B5-fix minus 0.03 and
  B6-swarm > B1.
- **H6-waste**: exact-repeat rate = logged calls whose tool and arguments equal an earlier logged call of the
  same run that had succeeded (a retry of a failed call is not a repeat), divided by logged calls, pooled
  over all B6-swarm runs; must be < 2%. The rate including retries is reported too. Calls used = mean
  charged tool calls per run / B; must be >= 80%.
- **H6-ablation**: B6-swarm beats B6-no-ledger and beats B6-no-parallel.
- **H6-budget**: N = median logged calls per B1 run (rounded); every run re-scored from its first N
  logged calls, reported sources restricted to those reached within them; B6-swarm beats B1 at N.
- **Curves**: overall recall at N = 10, 25, 50, 75, 100 logged calls, `paper/figures/recall-vs-calls.pdf`.
- Each hypothesis is reported as SUPPORTED or NOT SUPPORTED, including when B6 loses. Permutation p and
  Holm p (`eval/corpus/stats.py`, v0.2 pairs added to PAIRS) are reported, and n = 6 people is stated to be
  too small for statistical significance.

## 5. What was known when this was written

- The v0.1.0 results (all six people, aggregates and diagnostics) were known; v0.2 was designed from the
  aggregate diagnostics (repeat rates, empty-call rates, share of B used), not from per-fact results.
- B5-fix was built post hoc from a diagnosis of Burnham in v0.1, so Burnham is in-sample for B5-fix.
- No v0.2 strategy was run on any benchmark person before this commit. Development used only the synthetic
  mock archive and synthetic subjects (`fixtures/mock/subjects.jsonl`), which are not benchmark people.
