# Corpus replication results

Answer key v1 (frozen 2026-11-26); facts per person: burnham 226, homer 109, john 102, kingsley 232, bristol 87, alex 233.

Score = % of the hand-built dossier recovered in one pass (1.0 fact found with a source; 0.5 named the right book or archive; 0 miss). Mean ± sd over runs, in percent.

| strategy | burnham (Civil War) | homer (WWI) | john (WWII) | kingsley (civilian) | bristol (civilian) | alex (civilian) | overall | penalised | spend |
|---|---|---|---|---|---|---|---|---|---|
| B1 ReAct LLM agent | 18.5 ± 1.1 | 0.0 ± 0.0 | 0.0 ± 0.0 | 8.0 ± 1.7 | 35.6 ± 0.6 | 12.0 ± 1.5 | 12.4% | 11.9% | $0.47 |
| B5 CR (preregistered) | 17.5 ± 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 | 1.9 ± 0.0 | 35.6 ± 0.0 | 4.4 ± 0.9 | 9.9% | 9.5% | $0.00 |
| B5-fix CR rules2 (post hoc fix) | 22.6 ± 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 | 11.4 ± 0.0 | 36.2 ± 0.0 | 4.4 ± 0.9 | 12.4% | 11.7% | $0.00 |
| B6-swarm CR v0.2 swarm (preregistered) | 16.1 ± 0.3 | 0.0 ± 0.0 | 1.0 ± 0.0 | 11.6 ± 0.0 | 29.9 ± 0.0 | 10.9 ± 0.0 | 11.6% | 11.6% | $0.00 |
| B6-no-ledger swarm without ledger rules (ablation) | 15.9 ± 0.0 | 0.0 ± 0.0 | 1.0 ± 0.0 | 12.7 ± 0.0 | 29.9 ± 0.0 | 11.4 ± 0.0 | 11.8% | 11.8% | $0.00 |
| B6-no-parallel swarm with one worker (ablation) | 16.1 ± 0.3 | 0.0 ± 0.0 | 1.0 ± 0.0 | 11.6 ± 0.0 | 29.9 ± 0.0 | 10.9 ± 0.0 | 11.6% | 11.6% | $0.00 |

## Reachability ceiling: score on the reachable subset

A fact is reachable when at least one of its dossier sources is on archive.org, loc.gov or wikidata.org, the only hosts the bench tools query. Overall (reachable) is the mean over people with at least one reachable fact (Homer has none). Facts reachable per person: burnham 111/226, homer 0/109, john 2/102, kingsley 144/232, bristol 61/87, alex 89/233.

| strategy | burnham reachable | homer reachable | john reachable | kingsley reachable | bristol reachable | alex reachable | overall (reachable) | overall (full dossier) |
|---|---|---|---|---|---|---|---|---|
| B1 | 33.8 ± 0.9 | n.m. | 0.0 ± 0.0 | 12.7 ± 2.8 | 50.8 ± 0.8 | 23.2 ± 2.0 | 24.1% | 12.4% |
| B5 | 32.9 ± 0.0 | n.m. | 0.0 ± 0.0 | 3.1 ± 0.0 | 50.8 ± 0.0 | 11.6 ± 2.3 | 19.7% | 9.9% |
| B5-fix | 41.4 ± 0.0 | n.m. | 0.0 ± 0.0 | 18.4 ± 0.0 | 51.6 ± 0.0 | 11.6 ± 2.3 | 24.6% | 12.4% |
| B6-swarm | 27.9 ± 0.0 | n.m. | 0.0 ± 0.0 | 18.8 ± 0.0 | 42.6 ± 0.0 | 24.2 ± 0.0 | 22.7% | 11.6% |
| B6-no-ledger | 27.9 ± 0.0 | n.m. | 0.0 ± 0.0 | 19.8 ± 0.0 | 42.6 ± 0.0 | 25.3 ± 0.0 | 23.1% | 11.8% |
| B6-no-parallel | 27.9 ± 0.0 | n.m. | 0.0 ± 0.0 | 18.8 ± 0.0 | 42.6 ± 0.0 | 24.2 ± 0.0 | 22.7% | 11.6% |

## By era

| strategy | Civil War | WWI | WWII | civilian |
|---|---|---|---|---|
| B1 | 18.5% | 0.0% | 0.0% | 18.6% |
| B5 | 17.5% | 0.0% | 0.0% | 14.0% |
| B5-fix | 22.6% | 0.0% | 0.0% | 17.4% |
| B6-swarm | 16.1% | 0.0% | 1.0% | 17.5% |
| B6-no-ledger | 15.9% | 0.0% | 1.0% | 18.0% |
| B6-no-parallel | 16.1% | 0.0% | 1.0% | 17.5% |

## By access tier (mean over people)

| strategy | web_open | book | web_gated | outreach |
|---|---|---|---|---|
| B1 | 8.6% | 22.9% | 1.0% | 4.5% |
| B5 | 5.6% | 20.5% | 1.0% | 0.8% |
| B5-fix | 9.4% | 23.6% | 1.0% | 1.5% |
| B6-swarm | 8.6% | 20.5% | 1.0% | 3.4% |
| B6-no-ledger | 9.4% | 20.4% | 1.0% | 3.8% |
| B6-no-parallel | 8.6% | 20.5% | 1.0% | 3.4% |

## Other measures (mean over people)

| strategy | full-credit recall | holdout recall | source recall | precision | novel candidates/run | false links | tool calls/run |
|---|---|---|---|---|---|---|---|
| B1 | 5.7% | 12.3% | 8.0% | 55.8% | 5.6 | 2 | 22.2 |
| B5 | 4.2% | 9.8% | 3.7% | 66.8% | 3.6 | 3 | 22.7 |
| B5-fix | 5.0% | 11.7% | 10.2% | 67.4% | 17.9 | 6 | 54.7 |
| B6-swarm | 6.4% | 12.9% | 10.3% | 76.4% | 36.8 | 0 | 100.0 |
| B6-no-ledger | 6.5% | 13.0% | 10.7% | 80.2% | 31.2 | 0 | 100.0 |
| B6-no-parallel | 6.4% | 12.9% | 10.4% | 76.0% | 34.6 | 0 | 100.0 |

## Leakage audit

Exclusion filter on for every run (host blocklist plus dossier 8-gram content guard).

| strategy | runs | blocked (host) | dropped (dossier overlap) | runs without tool log |
|---|---|---|---|---|
| B1 | 18 | 0 | 5 | 0 |
| B5 | 18 | 0 | 0 | 0 |
| B5-fix | 18 | 0 | 6 | 0 |
| B6-swarm | 18 | 0 | 0 | 0 |
| B6-no-ledger | 18 | 0 | 0 | 0 |
| B6-no-parallel | 18 | 0 | 0 | 0 |
