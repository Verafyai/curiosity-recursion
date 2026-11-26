# Reproducibility checklist

Also the paper's appendix. Status as of 26 Nov 2026 in brackets.

- **Code, data, configs, seeds.** Code in this repository; public subject cards and record keys in
  `bench/data/`; every results line records agent, config, budget, seed, fault settings and the
  commit hash (`bench/common.py`). [Done for the harness; no benchmark run yet.]
- **Exact versions.** Python 3.13; Temporal CLI 1.10.1 (server 1.32.2, UI 2.56.4); Temporal Python
  SDK 1.37.0; Pydantic 2.14.4; FastAPI 0.165.0; httpx 0.29.0 (`pyproject.toml`). Model names and
  dates for any LLM run are written into each results line. [No LLM run yet.]
- **Budgets, stopping rules, hyperparameters.** In every results line, and fixed in
  `bench/PREREGISTRATION.md`. The preregistration commit hash and time are the registration.
- **Subjects and ground truth.** `bench/DATASHEET.md`: who built them, how they were chosen, tiers
  (heuristic until confirmed), the 30% test split by a fixed hash, and the sealed holdout
  (SHA-256 in the preregistration). The living-person filter is applied and logged in
  `bench/data/build.log`.
- **Source access dates.** Each results line has `started_at`; archives change, so rerun dates
  matter. Cached responses for replay where terms allow: not built yet.
- **Fault injection.** Settings and seeds in every fault-run line (`bench/faults.py`). Multi-day
  waits run on Temporal's time-skipping test server (`tests/test_time_skipping.py`).
- **Adjudication.** Guide, blinded sheets and kappa in `eval/adjudicate/`. Rater qualifications are
  recorded with each label file. [No raters yet.]
- **Compute and cost.** Tool calls, tokens, wall-clock per run in the results lines; dollars for
  model calls. [Rule-based runs cost no model tokens.]
- **Determinism.** Workflow code is replayed against saved histories in `tests/test_replay.py`.
- **Known gaps.** Copied from the README: rule-based generator only measured; fixture-backed demo
  facts; no continue-as-new; no heartbeat timeout; Wikidata throttling from some cloud addresses;
  small n; author-built ground truth; US, Canada and New England skew.
