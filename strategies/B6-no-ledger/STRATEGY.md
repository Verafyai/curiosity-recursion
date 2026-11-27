# B6-no-ledger: swarm without ledger rules (ablation)

**What it is.** B6-swarm with one component changed: the ledger rules are off. Everything else (outline, lanes, value
score, allocator, verification gate, tools, budget, exclusion filter) is identical. Model spend: none.

**How it hunts records.** As B6-swarm (see `strategies/B6-swarm/STRATEGY.md`), except: calls are still logged and counted, but nothing blocks an exact or near repeat and revisits need no new key; children are not told which calls were already made.

**What it changes compared with its parent strategy (B6-swarm).** Only `ledger=False`. Nothing tuned on a
benchmark person.

**Preregistered?** Yes, as the H6-ablation comparator in `bench/PREREGISTRATION-v0.2.md`.

Config: `config.json` (written by `scripts/export_strategy_configs.py`).
