# Curiosity Recursion v0.2 upgrade spec (for Claude Code)

Version of this spec: 1.0, 26 November 2026. Target: code v0.2.0, paper v0.2.0 after the rerun.
Repo: `Verafyai/curiosity-recursion`, starting from tag `v0.1.0` (commit `6e69179`) plus the paper-only
commit for paper v0.1.1 (related work and citations). Read `paper/related-work.md` first; this spec
cites it as [RW] and uses the BibTeX keys in `paper/refs.bib`.

This document is self-contained. Do every step in the repo. Do not push, tag a release, publish to
npm/PyPI, deploy anything, or spend model credits on benchmark runs: the owner runs the bench after
review. Unit tests and the fixture/mock bench (no network, no model) are fine and required.

---

## 0. Why v0.2 (facts from v0.1.0, do not restate them with new numbers)

All numbers below come from `paper/results-values.tex` and the v0.1.0 `RESULTS.md` (answer key v1,
3 runs per strategy, budget B = 100). Do not hand-type new numbers anywhere; every number in the paper
and README must be generated from results files (`make tables`).

| fact | value |
|---|---|
| full-dossier overall recall | B5 9.8%, B1 ReAct 11.6%, B5-fix (post hoc) 12.4% |
| reachable-subset overall recall | B5 19.4%, B1 22.0%, B5-fix 24.4% |
| precision | B5 66.9%, B5-fix 67.2%, B1 49.3% |
| exact repeated calls (`diag-repeat-*`) | B5 41.4%, B5-max 52.7%, B5-fix 11.1%, B1 0.6% |
| empty calls (`diag-empty-*`) | B3 75.6%, B5 48.5%, B5-fix 39.8%, B1 49.5% |
| calls actually used of B = 100 | B5 about 17 (diag) to 22.7 (harness); B5-fix 46.4 to 54.7; B1 22.4 |
| reachability ceiling | tools query only archive.org, loc.gov, wikidata.org; Homer 0/109 facts reachable, John 2/102 |

Diagnosis: CR loses on recall because it (a) stops early and leaves most of its budget unspent, (b)
spends a large share of what it does spend on exact repeats (the same search inside the same book from
different branches), and (c) has no value estimate to choose which open question to expand. It wins on
precision because every claim must be grounded in a quoted finding and pass verification. v0.2 keeps
(c)'s precision gate and fixes (a), (b) and (c) using the literature in [RW].

## 1. Goals and preregistered hypotheses

Write `bench/PREREGISTRATION-v0.2.md` and commit it **before** any v0.2 bench run (the owner runs it).
The commit hash and date of that file are the freeze point. Copy the hypotheses below verbatim, fill in
nothing that needs results.

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

## 2. Architecture overview

```
CuriosityRecursionSwarmWorkflow (orchestrator, parent)
  1. gate()                       living-person gate, unchanged, workflow code
  2. plan_outline (activity)      STORM-style outline: viewpoints x record types x date windows
  3. loop until budget/time/stop:
       select lanes by UCB1 (budget allocator)
       for each selected lane (in parallel, max W workers):
         start child workflow LaneWorker(lane, sub_budget, ledger_snapshot, reflections)
       await children; merge results
       merge_verify (activity)    dedupe facts, verification gate, agreement check, skeptic pass
       reflect (activity)         Reflexion-style lessons into reflection memory
       update lead tree values; maybe continue_as_new
  4. compose_report (activity)    unchanged writer, plus ledger and outline coverage tables

LaneWorker (child workflow)
  best-first / MCTS-lite expansion of leads within its lane
  every tool call: ledger.check -> (allow | rewrite with new key | block) -> tool activity -> ledger.record
```

New modules (suggested names; keep the existing style and determinism rules):

- `cr/ledger.py`  query canonicalization, key derivation, revisit rules, ledger records
- `cr/outline.py`  viewpoint/record-type/date-window outline and coverage tracking
- `cr/leads.py`  lead tree, value score, UCB/MCTS-lite selection, backup
- `cr/allocator.py`  UCB1 budget allocator across lanes, foraging stop rule
- `cr/reflection.py`  reflection memory (per run; optional cross-run memory off in the bench)
- `cr/swarm.py`  `CuriosityRecursionSwarmWorkflow`, `LaneWorkerWorkflow`, merge/verify plumbing
- `cr/variants.py`  name-spelling variant generator (deterministic, no network)
- additions to `cr/sources/live.py`  documented FTS endpoint client (section 8)
- additions to `cr/activities.py`  `plan_outline`, `ledger_*` (if not pure), `merge_verify`, `reflect`, new tool activities

Keep `CuriosityRecursionWorkflow` (B5, B5-fix) byte-for-byte compatible so its replay tests still pass.

## 3. Search ledger with smart re-query (the core fix)

Source: tabu search with aspiration criteria (`glover1997tabu`), Go-Explore "first return, then explore"
(`ecoffet2021goexplore`), query rewriting (`ma2023rewrite`, `wang2023query2doc`), record-linkage name
handling (`christen2012datamatching`). [RW sections 4 and 5]

### 3.1 Canonical query

Every tool call is described by a `QuerySpec`:
`tool` (ia_fulltext | ia_fts | ia_inside | ia_title | chronam | wikidata_search | wikidata_entities | ...),
`collection_or_item` (archive.org item id, collection id, loc.gov collection, or wikidata QID),
`terms` (the search string), `date_window` (start, end or null), `page_window` (for inside-a-book and
paged results: page range or result offset), `person_ref` (subject or relative id).

`canonicalize(spec) -> CanonicalQuery`:
- lowercase; Unicode NFKD and strip accents; collapse whitespace; strip punctuation except quotes that
  delimit phrases; drop stopwords (reuse `cr/novelty.STOP`); sort unquoted terms; keep quoted phrases
  as single tokens in order.
- normalize name forms with the same normalizer used for matching: `St.`/`Saint`/`St` to one token;
  initials kept as initials.
- date windows rounded to whole years; page windows to `(first, last)` integers.
- `canonical_id = sha256(json(tool, collection_or_item, terms_sorted, date_window, page_window))[:16]`.
  `person_ref` is NOT part of the id (two branches asking the same search for the same person collide).

### 3.2 Rules

1. **Exact repeat**: same `canonical_id` already in the ledger -> **blocked**. Do not call the tool, do
   not charge the budget, return the cached result reference (the evidence ids already stored) to the
   caller. Log `{"decision":"blocked_repeat", "canonical_id", "requested_by"}`.
2. **Near repeat**: same tool and same `collection_or_item`, term-set Jaccard >= 0.8, overlapping or equal
   date and page windows -> treated as a repeat unless rule 3 applies.
3. **Revisit allowed only with a new key** (aspiration criterion). A call against a source already in
   the ledger is allowed when it changes at least one key relative to every prior call on that source:
   - `name_variant`: a spelling variant from `cr/variants.py` not yet used on this source (phonetic key
     such as Soundex/NYSIIS/Double Metaphone computed locally, initials, Saint/St./St, dropped or doubled
     letters, common OCR confusions such as rn/m, li/h, e/c; transcription variants of the given name).
   - `adjacent_pages`: the next or previous page window inside a book where a prior call hit (Go-Explore:
     return to a promising state, then explore from it). Window size default 10 pages, max 3 hops.
   - `relative_name`: the name of a relative found in verified evidence (spouse, parent, child, sibling).
     The relative must pass the living-person gate (`cr/gate.py`) **before** their name may be used as a
     key; if their status is unknown they are living and the key is refused.
   - `different_collection`: same terms in a different archive.org collection, a different loc.gov
     collection, or a different tool.
   - `date_window`: a non-overlapping date window within the subject's plausible life window
     (birth year to death year + 5 when a death year is known; otherwise birth year to birth year + 100).
   - `result_offset`: next page of results for a paged search whose previous page had at least one hit
     that matched the person.
4. Every revisit records `{"decision":"revisit", "key_type", "key_value", "prior_canonical_ids", "reason"}`
   where `reason` is one short sentence generated deterministically from the rule (for example
   "adjacent pages 41-50 after hit on page 38 for burnham"). A model may suggest a key, but the rule
   engine decides and writes the reason.
5. **Rewrite instead of drop.** When a requested call is blocked, `ledger.suggest(spec)` returns up to 3
   allowed specs with new keys ranked by the lead value score; the worker takes the best one if budget
   allows. This is "repeat itself more cleverly".
6. **Foraging stop** (`pirolli1999foraging`). A source (item or collection) with k = 3 consecutive empty or
   non-matching calls is closed for the run unless a new verified fact adds a `relative_name` key for it.

### 3.3 Storage and concurrency

- The ledger is part of orchestrator workflow state (deterministic data, no I/O). Each child receives a
  snapshot plus its lane id; children propose specs, and the parent is the single writer:
  - Option A (preferred): children call a **workflow update** on the parent (`ledger_reserve`) that
    atomically checks and reserves a `canonical_id` before the tool activity runs, then signal
    `ledger_record` with the result evidence ids. Temporal Python 1.37 supports updates; use a validator
    that rejects repeats.
  - Option B: children run with a snapshot and the parent dedupes at merge, charging duplicate calls to
    the lane that made them (simpler, but allows some waste; only acceptable for B6-no-ledger).
- Persist the final ledger as `ledger.jsonl` in the run's output and include `repeat_rate`,
  `revisit_count` by key type and `revisit_yield` in the result line.
- `B6-no-ledger` disables rules 1 to 6 (but still logs calls so repeat rate is measurable).

## 4. Outline-first planning from multiple viewpoints

Source: STORM (`shao2024storm`), Co-STORM (`jiang2024costorm`), Anthropic's lane descriptions
(`anthropic2025multiagent`). [RW section 3]

`plan_outline(subject_card, era, reflections) -> Outline` builds, before any search, a grid of
**lanes**: `viewpoint x record_type x date_window`. Viewpoints and default record types:

| viewpoint | record types (examples) |
|---|---|
| military | unit histories, regimental rosters, pension indexes, adjutant general reports, GAR/veterans' posts |
| census | federal and state census households, city directories |
| church | parish and congregational registers, church histories, cemetery and burial lists |
| newspaper | obituaries, marriage and birth notices, local items (Chronicling America with date windows) |
| land | deeds, county atlases and plat books, town and county histories |
| probate | wills, estate notices, guardianship, court records named in county histories |
| immigration | passenger lists, naturalization indexes, ethnic society histories |

Rules: the era picks the relevant viewpoints and weights (for a Civil War veteran military gets a higher
prior; for civilians census, newspaper and church). Each lane has an objective, the tools it may use, an
output format (evidence records with quotes), and explicit boundaries ("do not search newspapers; the
newspaper lane does"), which is what Anthropic found prevents duplicated work. The outline also lists,
per lane, which dossier-style sections it would fill (birth, marriage, children, residence, occupation,
service, death, burial). Coverage per section is tracked as covered / leads only / missing, like the
existing circuits table. Lanes that need offline sources become **stubs** with a drafted outreach request
(never sent), exactly as v0.1.0 does, so they can still earn 0.5 when they name the right archive.

The outline generator must be deterministic from the input card for the rules version (`outline=rules`),
with an optional model-assisted version (`outline=llm`) used only in an ablation and only if the owner
approves spend. The input card stays name plus one anchor fact (birth year); no other hints.

## 5. Orchestrator with parallel workers (Temporal child workflows)

Source: Anthropic orchestrator-worker pattern (`anthropic2025multiagent`); failure modes to avoid from
MAST (`cemri2025mast`); independent votes (`li2024moreagents`, `wang2023selfconsistency`). [RW section 3]

- `CuriosityRecursionSwarmWorkflow` starts up to `W` `LaneWorkerWorkflow` children per round (default
  W = 4, configurable; B6-no-parallel sets W = 1 and runs lanes sequentially with the same total budget).
- Child ids are deterministic: `{parent_id}-r{round}-{lane_id}`. Use `ParentClosePolicy.TERMINATE` for the
  bench, and pass `sub_budget` so the sum over children never exceeds the parent's remaining B. The parent
  owns the global counter; children cannot exceed their reservation (enforced via the ledger update).
- Each child runs best-first lead expansion within its lane (section 6), returns evidence records,
  candidate facts with quotes, new leads it could not afford, and lane stats (calls, hits, empties).
- **Merge and verify** (activity `merge_verify`, deterministic code first):
  1. dedupe evidence by source key (item id + page, URL) and facts by normalized (field, value, person);
  2. run CR's existing verification (`verify_nodes`, quote grounding, conflict check, life-window namesake
     filter) on every candidate fact; unverified facts stay leads, never claims;
  3. agreement bonus: a fact supported by two lanes with different sources gets `support=2` (a ranking
     signal only; it never overrides verification failure);
  4. skeptic pass (`du2024debate`), rules first: try to refute each new claim using conflicting quoted
     evidence already in hand (date outside life window, different spouse, different town). Model-based
     skeptic only in an ablation with approved spend.
- Name the merged output's provenance: every claim lists the lane, the ledger `canonical_id`s and the
  quotes it rests on.

## 6. Best-first / MCTS-lite lead expansion with a value score and a budget allocator

Source: LATS (`zhou2024lats`), Tree of Thoughts (`yao2023tot`), RAP (`hao2023rap`), UCT/UCB1
(`kocsis2006uct`, `auer2002ucb`), information foraging (`pirolli1999foraging`). [RW sections 2 and 5]

**Lead.** A candidate next call: a `QuerySpec` plus the question it serves and its grounding quote
(CR's rule that every question is grounded in a quoted finding stays).

**Value score** in [0, 1], deterministic, logged per lead:

```
value = w_n * novelty + w_y * expected_yield + w_r * reachability + w_g * gap_fill - w_c * cost
```
- `novelty`: 1 if the lead's canonical query and source are new to the ledger; a revisit with a new key
  scores by key type (adjacent_pages after a hit 0.8, relative_name 0.7, name_variant 0.5,
  different_collection 0.6, date_window 0.5, result_offset 0.4); blocked repeats are not leads.
- `expected_yield`: running mean of matched-fact yield for (tool, viewpoint, record type) in this run,
  with a prior from the era table; updated after every call (backup).
- `reachability`: 1 for live keyless tools, 0.5 for a stub that can name a book or archive, 0 for
  sources known to be blocked.
- `gap_fill`: 1 if the lead targets an outline section still `missing`, 0.5 `leads only`, 0 `covered`.
- `cost`: calls the lead will consume (1 for most; inside-a-book counts as 1, same as v0.1.0).
Start weights `w = (0.3, 0.3, 0.15, 0.25, 0.1)`; freeze them in the preregistration. Do not tune them on
benchmark people; if a tuning set is needed use fixtures or `bench/data` DarkKin-Bench subjects that are
not in the corpus benchmark, and say which.

**Selection inside a lane.** Best-first by value with a UCT-style bonus over the lead tree:
`score = value_mean + c * sqrt(ln(N_parent) / (1 + n_node))`, c = 0.7. After each real call, back up the
observed reward (1 per new verified fact, 0.5 per new verified lead with a named source, 0 otherwise) to
ancestors. No simulated rollouts (they would cost calls); this is MCTS-lite.

**Budget allocator across lanes.** UCB1 over lanes using lane reward per call; minimum 3 calls per lane
in round 1 so every viewpoint is tried; then each round allocates the next block of calls (default 12)
proportional to UCB1 scores. Foraging stop closes a lane after k = 3 consecutive empty rounds, unless new
verified facts open new keys for it.

**Spend the budget.** The run stops only when B is spent, the wall-clock cap is hit, or no lead has value
above a floor (0.05) after rewrite suggestions; log the stop reason. H6-waste requires >= 80% of B used.

## 7. Reflection memory between rounds (Reflexion)

Source: Reflexion (`shinn2023reflexion`), generative agents (`park2023generative`). [RW section 1]

After each round, `reflect(round_stats, ledger_delta, merged)` writes at most 5 short lessons to the run's
reflection memory, each with type and evidence:
- `dead_end`: "<tool/collection/terms pattern> returned nothing k times" -> lowers expected_yield prior;
- `productive_source`: "<item id> had hits for <person> on pages a-b" -> raises value of adjacent_pages;
- `variant_hit`: "spelling <variant> matched where <canonical> did not" -> raises name_variant keys;
- `namesake_risk`: "<name> in <place> in <years> is a different person (life window)" -> filter;
- `new_relative`: verified relative (only after the living-person gate) -> enables relative_name keys.
Rules-generated by default (deterministic from stats). The lessons are inputs to the outline and value
score in the next round. Cross-run memory (`cr/memory.py`) stays OFF in the bench so runs are independent.

## 8. Tool upgrade (feasibility checked 26 Nov 2026)

**8.1 Internet Archive full-text search (do it).** `cr/sources/live.py` already has `ia_fulltext` (via
`archive.org/services/search/beta/page_production/` with `service_backend=fts`) and `ia_inside`
(`fulltext/inside.php`). Add `ia_fts(query, size, offset, collection=None)` using the public FTS endpoint
documented in the Internet Archive Python library (`iafts` in refs.bib):
`POST https://be-api.us.archive.org/ia-pub-fts-api` with JSON `{"q": "!L <query>", "size": "<n>",
"from": "<offset>", "scroll": false}`; a live probe on 26 Nov 2026 returned 200 with hits and
`{{{highlight}}}` snippets. Support `from` offsets (enables the `result_offset` key) and an optional
collection scope if the API accepts it (verify; if not, filter by collection after the call and say so).
Treat `user_message` and `UPSTREAM_ERROR` bodies as errors (Transient for 5xx). It goes through the same
tool wrapper, so the exclusion filter, n-gram content guard and tool log apply. One call = one unit of B.
Add the tool to B1's tool list too, so the comparison stays tool-matched (rerun B1 with it), and report
B1 with and without it if budget allows.

**8.2 FamilySearch catalog citations (named source only; no scraping).** A probe from the box on
26 Nov 2026 got HTTP 403 "blocked by our security service" on both the catalog page and its JSON
service, and the official API needs a registered developer key and user sign-in. Therefore: do NOT
fetch FamilySearch. Instead add a stub generator that, for a lane whose records are offline (for example
probate or church registers for a known county and period), writes a **catalog citation** naming the
FamilySearch Library catalog as the place to look, with the place and record type, as an outreach-style
stub (`access_tier` outreach). It is scored by the existing `named_archive` rule (0.5) only if the answer
key's source for that fact is an institution whose words match; do not loosen the matcher.
If you think a new partial-credit rule is needed (for example matching "FamilySearch" as an institution),
implement it as scorer rules v1.2 behind a flag, report v0.2 results under BOTH v1.1 and v1.2 rules, and
re-score B1 and B5-fix under v1.2 too. The primary metric uses v1.1.

**8.3 Unchanged.** The exclusion filter (`cr/sources/exclusion.py`: host blocklist incl. rexstjohn.com
and subdomains, verafy.ai, kin and Lineage deployments, github.com/rexsaurus, github.com/Verafyai, the
owner's X accounts, archive snapshots of all of these, and the dossier 8-gram content guard) stays
exactly as is; add a test that its blocklist and n-gram threshold hash are identical to v0.1.0. The answer
keys `eval/answer_keys/v1/*` and `LOCK.json` stay byte-identical; CI fails if any sha256 changes. The
input card stays name + birth year. Budget B = 100 tool calls and the same wall-clock cap.

## 9. Budget-matched comparison

Anthropic found spend explains most variance (`anthropic2025multiagent`), and v0.1.0 strategies used very
different shares of B. So report, in addition to B = 100:
- **calls-matched:** truncate every run's tool log at the same number of calls (the median calls used
  by B1 at B = 100) and re-score from the truncated evidence (add `--truncate-calls N` to
  `eval/corpus/score.py`, scoring only evidence from the first N logged calls). Report B6-swarm vs B1 and
  B5-fix at that N (this is H6-budget).
- **recall-per-call curves:** recall after 10, 25, 50, 75, 100 calls for every strategy, from the same
  truncation, as a figure `paper/figures/recall-vs-calls.pdf` drawn by `eval/plots.py`.
- **spend:** model tokens and dollars per run (B6 rules variant should be $0 in model spend, like B5).

## 10. Temporal requirements

- **Activity heartbeats:** every activity that can exceed 10 s (FTS, inside-a-book, chronam, merge_verify
  on large inputs) calls `activity.heartbeat(progress)` and sets `heartbeat_timeout` (for example 30 s);
  long paged fetches resume from heartbeat details on retry.
- **Idempotent activities:** each tool activity takes an idempotency key = `canonical_id` + run id; it
  writes its result to the run's evidence store keyed by that id and returns the stored result if called
  again (retries and replays never double-count budget or evidence). Ledger reservation happens in
  workflow code before the activity starts, so a retried activity uses the same reservation.
- **Continue-as-new:** the orchestrator calls `workflow.continue_as_new` at a round boundary when
  `workflow.info().get_current_history_length()` exceeds a threshold (default 10,000 events) or when
  Temporal suggests it (`workflow.info().is_continue_as_new_suggested()`; both calls exist in
  temporalio 1.37.0, which the repo pins; checked 26 Nov 2026), carrying a compact state: ledger (or its
  persisted reference plus a digest), outline coverage, lead tree frontier, reflections, budget counters.
  Add a test that forces continue-as-new every round and produces the same final result as without it.
- **Determinism:** no wall clock, randomness or I/O in workflow code; use `workflow.now()` and
  `workflow.random()` with the run seed. Replay tests (`tests/test_replay.py` style) for the new workflows
  with recorded histories in `tests/histories/`.
- **Child workflows:** deterministic ids, parent-close policy set, child failures retried by policy; a
  failed lane is logged and its unspent reservation returned to the pool.
- **Signals and queries:** keep the existing approve/reject/redirect/note/outreach signals on the parent;
  add a `ledger_summary` query and a `lanes` query for the Studio UI.
- **Fault injection:** the existing worker-kill and flaky-archive faults (`bench/faults.py`) must run
  against B6 too; the H2-style check is that B6 completes and redoes no finished lookups after a kill.

## 11. New strategies and how to run them

Create from `strategies/TEMPLATE/`:

| id | what | registered as |
|---|---|---|
| `B6-swarm` | full v0.2: outline + lanes + parallel children (W = 4) + ledger with smart re-query + value score/UCB allocator + reflection + verification gate + `ia_fts` | `AGENT_CONFIG["B6-swarm"] = dict(mode="swarm", generator="rules2", outline="rules", workers=4, ledger=True, reflect=True, verify_nodes=True, tools="v2")` |
| `B6-no-ledger` | same, ledger rules off (calls still logged) | `ledger=False` |
| `B6-no-parallel` | same, W = 1, lanes sequential, same total B | `workers=1` |
| `B6-no-reflect` (optional) | same, reflection off | `reflect=False` |
| `B6-v1tools` (optional) | same, without `ia_fts`, to separate tool gain from method gain | `tools="v1"` |

Each folder gets `STRATEGY.md` (what it is, how it hunts, what changed vs parent, preregistered yes/no
and date) and `config.json` (from `scripts/export_strategy_configs.py`). Wire `mode="swarm"` in
`bench/harness.py` to start `CuriosityRecursionSwarmWorkflow`; register the new workflows and activities in
`worker.py`.

Run (owner only, after review):
```
scripts/run-corpus-bench.sh --conditions B1,B5,B5-fix,B6-swarm,B6-no-ledger,B6-no-parallel --runs 3 --budget 100 --jobs 4
scripts/run-corpus-bench.sh --score-only --out <that run dir>   # re-score, incl. --truncate-calls
python eval/corpus/stats.py <run dir>
```
Update the default `CONDS` in `scripts/run-corpus-bench.sh` and the usage comment. The leaderboard
(`scripts/build_leaderboard.py`, `benchmark/`) and snapshot (`scripts/make_snapshot.py`) must include
the new rows automatically and mark post hoc vs preregistered.

## 12. Tests (all offline; no network, no model)

Add to `tests/`:
- `test_ledger.py`: canonicalization (case, punctuation, word order, St./Saint, accents); exact repeat
  blocked and not charged; near repeat blocked; each revisit key type allowed once per new value with a
  logged reason; relative_name refused for a presumed-living relative; foraging stop after k empties;
  `suggest()` returns only allowed specs.
- `test_variants.py`: deterministic variant sets for a few synthetic names (not benchmark people).
- `test_outline.py`: era-specific lanes, boundaries non-overlapping, stubs for offline record types.
- `test_leads.py`: value score components, UCT selection order, reward backup.
- `test_allocator.py`: UCB1 allocation, minimum per lane, closes dry lanes, never exceeds B.
- `test_swarm_workflow.py` (time-skipping test env with `cr/sources/mock_archive.py`): children start with
  deterministic ids; global budget respected across children; ledger reservation prevents two children
  issuing the same canonical call; merge dedupes; unverified facts never become claims; continue-as-new
  equivalence; worker kill mid-round redoes no finished activity; replay from recorded history.
- `test_fts_client.py`: request shape and error handling for `ia_fts` with recorded fixtures.
- `test_guardrails.py`: exclusion filter config hash equals v0.1.0; answer key sha256 equals `LOCK.json`;
  no file under `eval/private/` is tracked; no book page text beyond the existing short-snippet limit is
  written to any committed file; no em-dash (U+2014) in changed `.md`, `.tex` and `.py` files.
- Existing tests must still pass unchanged (`pytest -q`).

## 13. Acceptance criteria (for the implementation PR, before any bench run)

1. `pytest -q` passes; new tests cover the items in section 12.
2. A mock-archive bench run (`scripts/run-bench.sh` with the mock source, or a fixture mode) of B6-swarm,
   B6-no-ledger, B6-no-parallel completes with exact-repeat rate 0% for B6-swarm, > 0% for B6-no-ledger,
   uses >= 80% of B, and writes `ledger.jsonl` with reasons for every revisit.
3. `bench/PREREGISTRATION-v0.2.md` committed before any live run, with hypotheses, metrics, weights,
   decision rule and comparators.
4. Exclusion filter, answer keys and input cards unchanged (tests prove it).
5. Strategy folders, harness registration, run script defaults, leaderboard and snapshot updated.
6. A short `docs/v0.2-design.md` describing the design in plain English with the citations above.
7. No live benchmark numbers anywhere yet; the paper's v0.2 results sections use `\RESULT{...}`
   placeholders filled by `make tables` after the owner's run.

## 14. Versioning

- Code: bump to **v0.2.0** with `scripts/release.sh minor "..."` only after the owner approves the
  implementation; the script commits and tags locally and never pushes. Until then work on a branch
  `cr-v0.2`.
- Paper: currently **v0.1.1** (related work and citations only). After the owner's v0.2 bench run, the paper
  becomes **v0.2.0** with a new section on the swarm design, the preregistered H6 results (generated
  tables), the budget-matched analysis and the recall-vs-calls figure. Keep `\codeversion` and
  `\paperversion` separate in `paper/macros.tex` (release.sh currently sets only `\paperversion`; update it
  to set both on a code release and add a `--paper-only` mode that bumps only `\paperversion`).
- Update `CHANGELOG.md`, `CITATION.cff` (code version), README badges (version, paper), and
  `benchmark/BENCHMARK.md` on each release.

## 15. Guardrails (hard rules)

- No em-dashes anywhere in prose, docs, comments or the paper.
- Never invent numbers, citations, authors, years, venues or record contents. Every number in the paper,
  README and leaderboard is generated from results files. If a value is unknown, leave a `\RESULT{}`
  placeholder or say "not measured".
- Never publish book contents: commit citations (item id, page, URL) and the short snippets the scorer
  already stores, never page text or OCR dumps. Never commit `eval/private/` (living relatives); it stays
  gitignored.
- Living-person rules: research a person only if a death is on record or they were born more than 110
  years ago; unknown birth counts as living. This applies to every relative used as a search key. A shared
  surname alone is never a family link. Unsourced claims are labeled "Possible". Never invent records;
  label stubs as stubs.
- No credits, production keys or production writes from demos or tests; no model spend in tests.
- Nothing is sent: outreach stays as drafts written to files.
- Do not push, tag a public release, publish packages or deploy. Do not change the exclusion filter or the
  frozen answer keys. Do not look at holdout facts when designing or tuning.
- Keep the migration-order guardrail in any database or schema change.

## 16. Literature anchors (all in `paper/refs.bib`; details in `paper/related-work.md`)

ReAct `yao2023react`; Reflexion `shinn2023reflexion`; Tree of Thoughts `yao2023tot`; LATS `zhou2024lats`;
RAP `hao2023rap`; UCT `kocsis2006uct`; UCB1 `auer2002ucb`; self-consistency `wang2023selfconsistency`;
More Agents `li2024moreagents`; multiagent debate `du2024debate`; Anthropic multi-agent research system
`anthropic2025multiagent`; STORM `shao2024storm`; Co-STORM `jiang2024costorm`; AutoGen `wu2023autogen`;
MAST `cemri2025mast`; Search-o1 `li2025searcho1`; WebThinker `li2025webthinker`; DeepResearcher
`zheng2025deepresearcher`; deep research survey `huang2025drsurvey`; Rewrite-Retrieve-Read `ma2023rewrite`;
Query2doc `wang2023query2doc`; HyDE `gao2022hyde`; FLARE `jiang2023flare`; tabu search `glover1997tabu`;
Data Matching `christen2012datamatching`; Go-Explore `ecoffet2021goexplore`; information foraging
`pirolli1999foraging`; generative agents `park2023generative`; IA FTS docs `iafts`.
