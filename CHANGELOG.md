# Changelog

## paper v0.1.1 (2026-11-26)

Paper-only revision; code, benchmark and results unchanged (code v0.1.0).

- Related work extended with verified citations: tree search over agent trajectories (LATS, RAP, UCT), self-consistency, sampling and voting, multiagent debate, multi-agent research systems (Anthropic, Co-STORM, AutoGen, MAST), deep-research agents (Search-o1, WebThinker, DeepResearcher, survey), query reformulation (Rewrite-Retrieve-Read, Query2doc, HyDE, FLARE), tabu search, Go-Explore, information foraging, generative-agent reflection and record linkage.
- `paper/related-work.md` condenses each source and what CR v0.2 takes from it; `refs.bib` grows from 35 to 60 entries.

## v0.1.0 (2026-11-26)

First public release of the code, the benchmark and the paper (paper v0.1.0).

- Curiosity Recursion engine on Temporal (Python SDK 1.37), Lineage Studio and the live graph UI.
- DarkKin-Bench v0: preregistered H1 to H3 measured (`results/v0/`).
- Corpus replication benchmark, answer key v1 (six deceased people, frozen and gated), scorer v1.1 with a hand-checked audit, exclusion filter with a leakage audit, and a reachability ceiling.
- Strategies B0, B1, B3, B5 (preregistered) and post hoc B5-max, B5-fix and B5-llm, each in `strategies/`.
- Leaderboard (`benchmark/`), branded snapshot (`benchmark/assets/snapshot.png`), `scripts/run-bench.sh` and `scripts/release.sh`.
- Result: Curiosity Recursion did not beat a ReAct agent on either benchmark. See the paper.
