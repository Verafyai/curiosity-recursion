# B6-no-parallel: swarm with one worker (ablation)

**What it is.** B6-swarm with one component changed: one worker (W = 1). Everything else (outline, lanes, value
score, allocator, verification gate, tools, budget, exclusion filter) is identical. Model spend: none.

**How it hunts records.** As B6-swarm (see `strategies/B6-swarm/STRATEGY.md`), except: lanes run one after another with the same total budget B.

**What it changes compared with its parent strategy (B6-swarm).** Only `workers=1`. Nothing tuned on a
benchmark person.

**Preregistered?** Yes, as the H6-ablation comparator in `bench/PREREGISTRATION-v0.2.md`.

Config: `config.json` (written by `scripts/export_strategy_configs.py`).
