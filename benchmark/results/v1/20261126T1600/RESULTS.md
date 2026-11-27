# Corpus replication results

Answer key v1 (frozen 2026-11-26); facts per person: burnham 226, homer 109, john 102, kingsley 232, bristol 87, alex 233.

Score = % of the hand-built dossier recovered in one pass (1.0 fact found with a source; 0.5 named the right book or archive; 0 miss). Mean ± sd over runs, in percent.

| strategy | burnham (Civil War) | homer (WWI) | john (WWII) | kingsley (civilian) | bristol (civilian) | alex (civilian) | overall | penalised | spend |
|---|---|---|---|---|---|---|---|---|---|
| B0 single-pass LLM search | 13.7 ± 0.4 | 0.0 ± 0.0 | 0.0 ± 0.0 | 6.5 ± 2.7 | 19.2 ± 15.6 | 2.1 ± 0.0 | 6.9% | 6.9% | $0.01 |
| B1 ReAct LLM agent | 18.6 ± 1.0 | 0.0 ± 0.0 | 0.0 ± 0.0 | 8.5 ± 1.1 | 35.8 ± 0.7 | 6.4 ± 2.0 | 11.6% | 11.3% | $0.35 |
| B3 checklist only | 0.0 ± 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 | 2.1 ± 0.0 | 0.4% | 0.4% | $0.00 |
| B5 CR (preregistered) | 17.5 ± 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 | 1.9 ± 0.0 | 35.6 ± 0.0 | 3.9 ± 0.9 | 9.8% | 9.5% | $0.00 |
| B5-max CR wider (post hoc) | 18.1 ± 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 | 1.9 ± 0.0 | 36.2 ± 0.0 | 3.9 ± 0.9 | 10.0% | 9.7% | $0.00 |
| B5-fix CR rules2 (post hoc fix) | 22.6 ± 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 | 11.4 ± 0.0 | 36.2 ± 0.0 | 3.9 ± 0.9 | 12.4% | 11.6% | $0.00 |
| B5-llm CR, model question generator (ablation, post hoc) | 14.1 ± 1.0 | 0.0 ± 0.0 | 0.0 ± 0.0 | 5.2 ± 4.2 | 31.4 ± 3.8 | 4.9 ± 0.0 | 9.3% | 9.1% | n.m. |

## Reachability ceiling: score on the reachable subset

A fact is reachable when at least one of its dossier sources is on archive.org, loc.gov or wikidata.org, the only hosts the bench tools query. Overall (reachable) is the mean over people with at least one reachable fact (Homer has none). Facts reachable per person: burnham 111/226, homer 0/109, john 2/102, kingsley 144/232, bristol 61/87, alex 89/233.

| strategy | burnham reachable | homer reachable | john reachable | kingsley reachable | bristol reachable | alex reachable | overall (reachable) | overall (full dossier) |
|---|---|---|---|---|---|---|---|---|
| B0 | 27.9 ± 0.8 | n.m. | 0.0 ± 0.0 | 10.5 ± 4.4 | 27.3 ± 22.2 | 5.6 ± 0.0 | 14.3% | 6.9% |
| B1 | 33.9 ± 0.9 | n.m. | 0.0 ± 0.0 | 11.2 ± 0.5 | 51.1 ± 0.9 | 13.7 ± 2.6 | 22.0% | 11.6% |
| B3 | 0.0 ± 0.0 | n.m. | 0.0 ± 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 | 5.6 ± 0.0 | 1.1% | 0.4% |
| B5 | 32.9 ± 0.0 | n.m. | 0.0 ± 0.0 | 3.1 ± 0.0 | 50.8 ± 0.0 | 10.3 ± 2.3 | 19.4% | 9.8% |
| B5-max | 33.3 ± 0.0 | n.m. | 0.0 ± 0.0 | 3.1 ± 0.0 | 51.6 ± 0.0 | 10.3 ± 2.3 | 19.7% | 10.0% |
| B5-fix | 41.4 ± 0.0 | n.m. | 0.0 ± 0.0 | 18.4 ± 0.0 | 51.6 ± 0.0 | 10.3 ± 2.3 | 24.4% | 12.4% |
| B5-llm | 27.8 ± 0.5 | n.m. | 0.0 ± 0.0 | 8.3 ± 6.8 | 44.8 ± 5.5 | 12.9 ± 0.0 | 18.8% | 9.3% |

## By era

| strategy | Civil War | WWI | WWII | civilian |
|---|---|---|---|---|
| B0 | 13.7% | 0.0% | 0.0% | 9.3% |
| B1 | 18.6% | 0.0% | 0.0% | 16.9% |
| B3 | 0.0% | 0.0% | 0.0% | 0.7% |
| B5 | 17.5% | 0.0% | 0.0% | 13.8% |
| B5-max | 18.1% | 0.0% | 0.0% | 14.0% |
| B5-fix | 22.6% | 0.0% | 0.0% | 17.2% |
| B5-llm | 14.1% | 0.0% | 0.0% | 13.8% |

## By access tier (mean over people)

| strategy | web_open | book | web_gated | outreach |
|---|---|---|---|---|
| B0 | 4.9% | 14.7% | 0.0% | 0.0% |
| B1 | 7.5% | 22.0% | 1.0% | 3.7% |
| B3 | 0.8% | 0.0% | 0.0% | 0.0% |
| B5 | 5.6% | 20.3% | 1.0% | 0.8% |
| B5-max | 5.9% | 20.3% | 1.0% | 1.5% |
| B5-fix | 9.3% | 23.4% | 1.0% | 1.5% |
| B5-llm | 5.9% | 19.1% | 0.0% | 0.0% |

## Other measures (mean over people)

| strategy | full-credit recall | holdout recall | source recall | precision | novel candidates/run | false links | tool calls/run |
|---|---|---|---|---|---|---|---|
| B0 | 0.8% | 6.3% | 4.2% | 30.5% | 3.9 | 0 | 7.4 |
| B1 | 5.2% | 11.6% | 5.9% | 49.3% | 4.3 | 1 | 22.4 |
| B3 | 0.1% | 0.4% | 0.4% | 57.4% | 0.2 | 0 | 12.0 |
| B5 | 4.2% | 9.8% | 3.5% | 66.9% | 3.6 | 3 | 22.7 |
| B5-max | 4.5% | 9.8% | 3.6% | 65.7% | 3.7 | 3 | 45.5 |
| B5-fix | 5.0% | 11.6% | 9.9% | 67.2% | 18.1 | 6 | 54.7 |
| B5-llm | 2.0% | 8.9% | 5.1% | 32.0% | 8.9 | 1 | 50.1 |

## Leakage audit

Exclusion filter on for every run (host blocklist plus dossier 8-gram content guard).

| strategy | runs | blocked (host) | dropped (dossier overlap) | runs without tool log |
|---|---|---|---|---|
| B0 | 18 | 0 | 0 | 0 |
| B1 | 18 | 0 | 8 | 0 |
| B3 | 18 | 0 | 0 | 0 |
| B5 | 18 | 0 | 0 | 0 |
| B5-max | 18 | 0 | 6 | 0 |
| B5-fix | 18 | 0 | 6 | 0 |
| B5-llm | 18 | 0 | 2 | 0 |
