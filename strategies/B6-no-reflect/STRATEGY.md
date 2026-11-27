# B6-no-reflect: swarm without reflection (optional ablation)

**What it is.** B6-swarm with one component changed: reflection between rounds is off. Everything else (outline, lanes, value
score, allocator, verification gate, tools, budget, exclusion filter) is identical. Model spend: none.

**How it hunts records.** As B6-swarm (see `strategies/B6-swarm/STRATEGY.md`), except: no lane notes, so expected yields and name-variant boosts stay at their priors.

**What it changes compared with its parent strategy (B6-swarm).** Only `reflect=False`. Nothing tuned on a
benchmark person.

**Preregistered?** Defined before the v0.2 run but not part of the preregistered batch; any result is exploratory.

Config: `config.json` (written by `scripts/export_strategy_configs.py`).
