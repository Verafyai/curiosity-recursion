# B6-v1tools: swarm without ia_fts (optional ablation)

**What it is.** B6-swarm with one component changed: the v0.1 tool set (no `ia_fts`). Everything else (outline, lanes, value
score, allocator, verification gate, tools, budget, exclusion filter) is identical. Model spend: none.

**How it hunts records.** As B6-swarm (see `strategies/B6-swarm/STRATEGY.md`), except: only the v0.1 tools are used, to separate the tool gain from the method gain.

**What it changes compared with its parent strategy (B6-swarm).** Only `tools="v1"`. Nothing tuned on a
benchmark person.

**Preregistered?** Defined before the v0.2 run but not part of the preregistered batch; any result is exploratory.

Config: `config.json` (written by `scripts/export_strategy_configs.py`).
