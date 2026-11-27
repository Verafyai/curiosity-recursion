# B5-llm: CR with a grounded model question generator (ablation)

**What it is.** B5 with the rules generator replaced by a model that must ground each question in
a quoted finding (`cr/generators/llm.py`). Part of the preregistered ablation table, run on the
8 ablation subjects of the original benchmark; not yet run on the corpus leaderboard.

Code: `cr/generators/llm.py`. Config: `config.json`.
