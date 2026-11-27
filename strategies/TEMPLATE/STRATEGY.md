# <ID>: <one-line name>

Copy this folder to `strategies/<ID>/`, fill in each section, and register the strategy so the
runner can call it. A new strategy is comparable with the others only if it keeps the benchmark
rules in `eval/EVAL-SPEC.md` (same input card, same tools, same budget, exclusion filter on).

**What it is.** One paragraph.

**How it hunts records.** Which searches it makes and how it picks the next one.

**What it changes compared with its parent strategy.** Bullet list. Say if anything was tuned
while looking at a benchmark person, and which one (those people are then in-sample for it).

**Preregistered?** Yes or no, and the date it was frozen.

## Registering it

- A CR variant: add a line to `AGENT_CONFIG` in `bench/harness.py`, for example
  `"B6": dict(mode="brainstorm", generator="rules2", breadth=6, depth=5, max_nodes=300)`.
  A new generator goes in `cr/generators/` and is selected by `generator=`.
- Any other agent: add a runner in `bench/baselines/` that reads the subject card, uses only the
  tools in `cr/sources/live.py` (imported through `cr.sources`, so the exclusion filter and tool log
  apply), and writes one result line in the format of `bench/baselines/llm_agents.py`.
- Run `python scripts/export_strategy_configs.py` to write `config.json`, then
  `scripts/run-bench.sh --conditions <ID>,B5-fix,B1` to put it on the leaderboard.
