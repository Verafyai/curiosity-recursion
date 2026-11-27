# Changelog

## v0.1.0 (2026-11-26)

First public release of the code, the benchmark and the paper (paper v0.1.0).

- Curiosity Recursion engine on Temporal (Python SDK 1.37), Lineage Studio and the live graph UI.
- DarkKin-Bench v0: preregistered H1 to H3 measured (`results/v0/`).
- Corpus replication benchmark, answer key v1 (six deceased people, frozen and gated), scorer v1.1 with a hand-checked audit, exclusion filter with a leakage audit, and a reachability ceiling.
- Strategies B0, B1, B3, B5 (preregistered) and post hoc B5-max, B5-fix and B5-llm, each in `strategies/`.
- Leaderboard (`benchmark/`), branded snapshot (`benchmark/assets/snapshot.png`), `scripts/run-bench.sh` and `scripts/release.sh`.
- Result: Curiosity Recursion did not beat a ReAct agent on either benchmark. See the paper.
