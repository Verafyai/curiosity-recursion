# Curiosity Recursion benchmark

Version v0.1.0. [Click to read the research paper](https://verafyai.github.io/curiosity-recursion/paper/main.pdf) ([PDF in the repo](../paper/main.pdf)). Web page: https://verafyai.github.io/curiosity-recursion/benchmark/

![Benchmark snapshot](assets/snapshot.png)

## What the benchmark measures

- Six people from the author's own family research, each with a hand-built dossier: a Civil War soldier (Erastus W. Burnham), a World War I veteran (Homer D. St. John), a World War II veteran (John St. John) and three civilians (Kingsley A. Perry, Edgar H. Bristol, Alex St. John). Everyone is deceased.
- Each dossier was split into atomic facts (birth, service, work, family, places, sources) and frozen as a hash-locked answer key. Every fact is tagged with how its source can be reached: open web, gated site, book, or outreach to an archive or family.
- Each strategy gets only the person's name and birth year, the same public tools (Internet Archive, Chronicling America, Wikidata) and the same budget (100 tool calls), and runs 3 times per person.
- Score: 1.0 for each dossier fact found in the evidence the tools returned, 0.5 for reaching the right record or naming the right book or archive, 0 otherwise. 100% means the whole dossier was recovered in one pass.
- Exclusion filter: the author's own websites, repositories, deployments and accounts, and archive snapshots of them, are blocked at the tool layer, and any returned page that copies dossier prose is dropped, so no strategy can copy the finished research back.
- Reachability ceiling: many dossier facts come from books, gated archives and family outreach that these tools cannot reach. The table also scores each strategy on the reachable facts only (a source on archive.org, loc.gov or wikidata.org).

Answer key **v1** (frozen 2026-11-26), result set `20261126T1600`, code commit `0633ba7 ; B5-llm and RPC reruns at 282eb99`, 3 runs per strategy per person, budget 100 tool calls. Mean ± sd over runs, in percent. Spec: [eval/EVAL-SPEC.md](../eval/EVAL-SPEC.md).

## Leaderboard

| Rank | Strategy | Erastus Burnham (Civil War) | Homer St. John (WWI) | John St. John (WWII) | Kingsley Perry (civilian) | Edgar H. Bristol (civilian) | Alex St. John (civilian) | Overall | Reachable only | Precision | Penalised | Spend |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | B5-fix: CR rules2 (post hoc fix) | 22.6 ± 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 | 11.4 ± 0.0 | 36.2 ± 0.0 | 3.9 ± 0.9 | 12.4% | 24.4% | 67.2% | 11.6% | $0.00 |
| 2 | B1: ReAct LLM agent | 18.6 ± 1.0 | 0.0 ± 0.0 | 0.0 ± 0.0 | 8.5 ± 1.1 | 35.8 ± 0.7 | 6.4 ± 2.0 | 11.6% | 22.0% | 49.3% | 11.3% | $0.35 |
| 3 | B5-max: CR wider (post hoc) | 18.1 ± 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 | 1.9 ± 0.0 | 36.2 ± 0.0 | 3.9 ± 0.9 | 10.0% | 19.7% | 65.7% | 9.7% | $0.00 |
| 4 | B5: CR (preregistered) | 17.5 ± 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 | 1.9 ± 0.0 | 35.6 ± 0.0 | 3.9 ± 0.9 | 9.8% | 19.4% | 66.9% | 9.5% | $0.00 |
| 5 | B5-llm: CR, model question generator (ablation, post hoc) | 14.1 ± 1.0 | 0.0 ± 0.0 | 0.0 ± 0.0 | 5.2 ± 4.2 | 31.4 ± 3.8 | 4.9 ± 0.0 | 9.3% | 18.8% | 32.0% | 9.1% | n.m. |
| 6 | B0: single-pass LLM search | 13.7 ± 0.4 | 0.0 ± 0.0 | 0.0 ± 0.0 | 6.5 ± 2.7 | 19.2 ± 15.6 | 2.1 ± 0.0 | 6.9% | 14.3% | 30.5% | 6.9% | $0.01 |
| 7 | B3: checklist only | 0.0 ± 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 | 2.1 ± 0.0 | 0.4% | 1.1% | 57.4% | 0.4% | $0.00 |

## Reachability ceiling

Recall on the facts the tools could reach at all. Homer has none, so his column is not measured.

| Strategy | Erastus Burnham (111 reachable) | Homer St. John (0 reachable) | John St. John (2 reachable) | Kingsley Perry (144 reachable) | Edgar H. Bristol (61 reachable) | Alex St. John (89 reachable) | Mean (reachable) |
|---|---|---|---|---|---|---|---|
| B5-fix | 41.4 ± 0.0 | n.m. | 0.0 ± 0.0 | 18.4 ± 0.0 | 51.6 ± 0.0 | 10.3 ± 2.3 | 24.4% |
| B1 | 33.9 ± 0.9 | n.m. | 0.0 ± 0.0 | 11.2 ± 0.5 | 51.1 ± 0.9 | 13.7 ± 2.6 | 22.0% |
| B5-max | 33.3 ± 0.0 | n.m. | 0.0 ± 0.0 | 3.1 ± 0.0 | 51.6 ± 0.0 | 10.3 ± 2.3 | 19.7% |
| B5 | 32.9 ± 0.0 | n.m. | 0.0 ± 0.0 | 3.1 ± 0.0 | 50.8 ± 0.0 | 10.3 ± 2.3 | 19.4% |
| B5-llm | 27.8 ± 0.5 | n.m. | 0.0 ± 0.0 | 8.3 ± 6.8 | 44.8 ± 5.5 | 12.9 ± 0.0 | 18.8% |
| B0 | 27.9 ± 0.8 | n.m. | 0.0 ± 0.0 | 10.5 ± 4.4 | 27.3 ± 22.2 | 5.6 ± 0.0 | 14.3% |
| B3 | 0.0 ± 0.0 | n.m. | 0.0 ± 0.0 | 0.0 ± 0.0 | 0.0 ± 0.0 | 5.6 ± 0.0 | 1.1% |

![recall per person](assets/corpus-recall.png)

## By era

| Strategy | Civil War | WWI | WWII | civilian |
|---|---|---|---|---|
| B5-fix | 22.6% | 0.0% | 0.0% | 17.2% |
| B1 | 18.6% | 0.0% | 0.0% | 16.9% |
| B5-max | 18.1% | 0.0% | 0.0% | 14.0% |
| B5 | 17.5% | 0.0% | 0.0% | 13.8% |
| B5-llm | 14.1% | 0.0% | 0.0% | 13.8% |
| B0 | 13.7% | 0.0% | 0.0% | 9.3% |
| B3 | 0.0% | 0.0% | 0.0% | 0.7% |

## By access tier

| Strategy | web_open | book | web_gated | outreach |
|---|---|---|---|---|
| B5-fix | 9.3% | 23.4% | 1.0% | 1.5% |
| B1 | 7.5% | 22.0% | 1.0% | 3.7% |
| B5-max | 5.9% | 20.3% | 1.0% | 1.5% |
| B5 | 5.6% | 20.3% | 1.0% | 0.8% |
| B5-llm | 5.9% | 19.1% | 0.0% | 0.0% |
| B0 | 4.9% | 14.7% | 0.0% | 0.0% |
| B3 | 0.8% | 0.0% | 0.0% | 0.0% |

## Other measures

| Strategy | Full-credit recall | Holdout recall | Source recall | Precision | Novel candidates / run | False links | Tool calls / run |
|---|---|---|---|---|---|---|---|
| B5-fix | 5.0% | 11.6% | 9.9% | 67.2% | 18.1 | 6 | 54.7 |
| B1 | 5.2% | 11.6% | 5.9% | 49.3% | 4.3 | 1 | 22.4 |
| B5-max | 4.5% | 9.8% | 3.6% | 65.7% | 3.7 | 3 | 45.5 |
| B5 | 4.2% | 9.8% | 3.5% | 66.9% | 3.6 | 3 | 22.7 |
| B5-llm | 2.0% | 8.9% | 5.1% | 32.0% | 8.9 | 1 | 50.1 |
| B0 | 0.8% | 6.3% | 4.2% | 30.5% | 3.9 | 0 | 7.4 |
| B3 | 0.1% | 0.4% | 0.4% | 57.4% | 0.2 | 0 | 12.0 |

## Is any difference real?

Paired over the six people. With six people the smallest possible p is 0.031, so read these as direction, not proof.

| Comparison | People | Mean difference (points) | Better / worse | p (exact sign-flip) | Holm p |
|---|---|---|---|---|---|
| B5 vs B1 | 6 | -1.7 | 0 / 4 | 0.125 | 0.875 |
| B5 vs B0 | 6 | +2.9 | 3 / 1 | 0.500 | 0.875 |
| B5 vs B3 | 6 | +9.5 | 4 / 0 | 0.125 | 0.875 |
| B5-fix vs B1 | 6 | +0.8 | 3 / 1 | 0.375 | 0.875 |
| B5-max vs B1 | 6 | -1.5 | 1 / 3 | 0.250 | 0.875 |
| B5-llm vs B1 | 6 | -2.3 | 0 / 4 | 0.125 | 0.875 |
| B1 vs B0 | 6 | +4.6 | 4 / 0 | 0.125 | 0.875 |

## Leakage audit

Every strategy ran with the exclusion filter on: the dossier author's own sites, repositories, deployments and accounts are blocked at the tool layer, and any returned page that copies dossier prose is dropped. Counts per strategy:

| Strategy | Runs | Blocked by host rule | Dropped by dossier-overlap guard | Runs without a tool log |
|---|---|---|---|---|
| B5-fix | 18 | 0 | 6 | 0 |
| B1 | 18 | 0 | 8 | 0 |
| B5-max | 18 | 0 | 6 | 0 |
| B5 | 18 | 0 | 0 | 0 |
| B5-llm | 18 | 0 | 2 | 0 |
| B0 | 18 | 0 | 0 | 0 |
| B3 | 18 | 0 | 0 | 0 |

## Scorer audit

Scorer audit: 80 sampled decisions (half credited, half not) were judged by an independent model at temperature 0: 85.0% agreement, Cohen's kappa 0.70; 75.0% of the scorer's credited facts were confirmed. Every disagreement (12) was then read one by one by an AI assistant (not a human rater) against the matched text: the scorer was right in 4 and wrong in 8, so hand-adjudicated precision of credited facts is 32/40 and no missed facts were found among 40 zeros.

## Answer key hashes

- `burnham`: `2750397ec0d728b0faa9319f2afd4a43993156ad19cdf6ac161902b7ba8452e0`
- `homer`: `97246745c0a641986a5a3256f511b7e945bf459bcb2dd46259393fd993d8af8d`
- `john`: `e1fadcf36c92e7480f6c5440b8e6ea233b283636616e595e23a15d2e905ad9df`
- `kingsley`: `7176dc8c25ac6cd9f89a5626c8ce76570c469bd084d74919dad1c7600bc0ec1f`
- `bristol`: `53f9fde3972539560be3f4b18124c14fad94455db3785a9431ef24bb1fb03f79`
- `alex`: `95fd263256f3600ab33b91331bc6303765c755d5b2ed8fcab864ecbd794dbba8`

## History

| Answer key | Result set | Best strategy | Best overall |
|---|---|---|---|
| v1 | 20261126T1600 | B5-fix | 12.4% |
