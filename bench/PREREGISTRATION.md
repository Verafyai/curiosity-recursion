# DarkKin-Bench preregistration

Status: written 26 Nov 2026, before any benchmark run. Commit this file before the first full run;
the commit hash and time are the registration. Change it only by a new dated section below, never
by editing what is here.

## Question

At an equal tool-call budget, does a durable Curiosity Recursion (CR) agent find more verifiable
hidden records of deceased people than single-pass, ReAct and checklist-only agents, without
lowering claim precision?

## Subjects and splits

- DarkKin-Bench v0: 39 subjects built by `bench/convert_kin.py` from kin's `relatives.json`
  (4 family dossier subjects, 523 records) and `heritage-real.json` (35 public historical figures,
  148 records). Living-person filter applied and logged in `bench/data/build.log` (0 removed).
- Split by a fixed hash of the subject id: 27 dev, 12 test. Test subjects are not looked at while
  rules, prompts, templates or circuits are changed.
- kin's `heritage-real.holdout.json` (15 more subjects) is sealed and unread. SHA-256 of the copy
  received on 26 Nov 2026: `89c3318f3977eb299c7bf4cb1ccfb74ef83f1086fc11ba127dfa75da7ae3f6f0`.
  It is converted and scored once, after all other analysis is frozen.
- More subjects (Rex's remaining dossiers, 100 to 200 public figures picked by a fixed hash) are
  added as v1 under the same rules before any H1 claim is made.

## Agents (equal sources, tools, rate limits)

B0 single pass, B1 ReAct, B2 human-nudged (Rex's transcripts, reference only, not at equal
budget), B3 checklist only (`mode=checklist`), B4 CR in a plain asyncio loop (no Temporal, no
persistence), B5 full system (circuits, CR, memory, Temporal). Optional B6 commercial deep research
only where its terms allow, with date and cost reported. Every agent runs with `use_fixtures=False`.

## Budgets and seeds

B in {25, 50, 100, 200} tool calls (checklist steps plus investigations; model calls are logged
separately as tokens and dollars). 3 seeds for every configuration that uses a model or fault
injection. Primary budget for tables: B = 100.

## Hypotheses, tests and what counts as failure

- **H1** recall@B(B5) > recall@B(B0, B1, B3). Paired per subject, Wilcoxon signed-rank, bootstrap
  95% CI (10,000 resamples) on the mean difference, Holm correction across the three baselines.
  Fails if B5 is not better than B3 at B in {50, 100, 200}. H1b: the gain is largest in tiers T1
  and T3 and smallest in T0 (reported descriptively with CIs).
- **H2** Under faults (worker kills at 1 per 10 activities, archive failure p in {0.1, 0.3, 0.5},
  3 to 21 day waits, delayed replies), B5 completes more runs and repeats less work than B4.
  McNemar on paired completion; duplicate-work ratio with bootstrap CI. Fails if completion does
  not differ at p = 0.3 with kills.
- **H3** With memory on, a repeat run (same subject) or a sibling run (same circuit and place or
  unit) reaches the first run's recall with fewer tool calls, or more recall at the same budget.
  Wilcoxon on cost-to-recall. Fails if there is no reduction.
- **H4** Documented-claim precision of B5 is not lower than B0 by more than 2 points
  (non-inferiority margin 2.0, one-sided 95% bootstrap bound), and the fabricated-record rate for
  documented claims is 0. Leads are scored separately and must be labeled as leads.
- **H5** (optional) Nudge coverage of B5 is above B3's. Two coders, Cohen's kappa reported.
  Fails if coverage is not above B3.

## Scoring

- A hidden record counts as found when an agent's citation matches it by canonical key (URL
  normalised, Internet Archive identifier, loc.gov resource id) and two raters confirm it is the
  same person (`eval/adjudicate/`). Automatic key matches are candidates until adjudicated.
- T2 and T3 records count as found when the correct holder is identified and a correct request
  is drafted (right holder, right record, right identifiers). Nothing is fetched by force.
- Records with `about_subject = false` after review (period context, not about the person) are
  removed from the denominator before scoring, by a reviewer blind to agent output.

## Exclusions and stopping

A run that crashes for an infrastructure reason unrelated to the agent (for example the Temporal
server itself is down) is rerun once with the same seed and the rerun is logged. No other run is
dropped. Every stop reason is recorded.
