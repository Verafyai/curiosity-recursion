# Strategies

One folder per approach. Each has `STRATEGY.md` (how it hunts records, what it changes, whether it
was preregistered) and `config.json` (written by `scripts/export_strategy_configs.py` from the
harness, so it is the config that ran).

| ID | Strategy | Preregistered | On the corpus leaderboard |
|---|---|---|---|
| B0 | single-pass LLM search | yes | yes |
| B1 | ReAct LLM agent | yes | yes |
| B3 | checklist only | yes | yes |
| B4 | CR without durability (H2 only) | yes | no |
| B5 | Curiosity Recursion | yes | yes |
| B5-max | CR, widest graph | no (post hoc) | yes |
| B5-fix | CR with rules2 generator | no (post hoc) | yes |
| B5-llm | CR with model generator | yes (ablation) | not yet |

To add one, copy `TEMPLATE/`.
