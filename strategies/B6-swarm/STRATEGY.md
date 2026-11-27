# B6-swarm: CR v0.2 lane swarm with a search ledger

**What it is.** The full v0.2 design (`docs/v0.2-design.md`). An outline of research lanes (one per
viewpoint and record type, for example military, census, church, three newspaper life phases, land,
probate, immigration, reference) is planned from the input card alone. Lanes run as parallel Temporal
child workflows (W = 4). Every tool call goes through a run-wide search ledger first. Model spend: none
(rules only).

**How it hunts records.**
- Each lane holds a lead tree. The next lead is picked best first by a value score (novelty, expected
  yield, reachability, gap fill, cost) plus a UCT exploration bonus (c = 0.7); a real call's reward is
  backed up to its ancestors (MCTS-lite, no simulated rollouts).
- A UCB1 allocator splits each round's calls across lanes (at least 3 per lane in round 1, then blocks
  of 12) and closes a lane after 3 dry rounds.
- The ledger blocks exact and near repeats (word Jaccard >= 0.8) before the call, so they cost nothing.
  A revisit of the same source is allowed only with a new key (name variant, adjacent pages, a gated
  relative's name, another collection, another date window, the next result page), once per new
  value, and the reason is written to `ledger.jsonl`. A source is dropped after 3 empty calls.
- Uses the Internet Archive full-text search API (`ia_fts`) as well as the v0.1 tools.
- After each round, a merge step dedupes evidence, applies the verification gate (strong full-name
  match, inside the life window, a skeptic rule on a stated birth year) and keeps unverified hits as
  leads only. Reflection notes per lane adjust expected yields and name-variant boosts.
- Offline record types (church registers, land and probate, military files) become labelled stubs
  that name the holding institution (FamilySearch Library catalog, county probate court, NARA). No
  FamilySearch fetches.

**What it changes compared with its parent strategy (B5-fix).** Parallel lanes instead of one
question tree; the ledger; value score and allocator; reflection; `ia_fts`. Nothing was tuned on a
benchmark person: all weights and thresholds were set before any v0.2 live run and are frozen in
`bench/PREREGISTRATION-v0.2.md`. The design was written after reading v0.1.0 aggregate diagnostics
(repeat and empty-call rates across all six people), which is recorded in the preregistration.

**Preregistered?** Yes, in `bench/PREREGISTRATION-v0.2.md` (the commit of that file is the freeze
point).

Config: `config.json` (written by `scripts/export_strategy_configs.py`). Code: `cr/swarm.py`,
`cr/ledger.py`, `cr/outline.py`, `cr/leads.py`, `cr/allocator.py`, `cr/reflection.py`.
