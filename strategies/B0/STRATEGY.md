# B0: single-pass LLM search

**What it is.** One model turn. The model gets the name and the anchor (birth year), the shared
tool set, and the instruction to make every search it wants in one step. It cannot see results
and search again.

**How it hunts records.** Whatever the model plans up front: usually the exact name in books,
newspapers and Wikidata, sometimes with the birth year or a guessed place.

**Where it is strong.** Cheap and fast; a reasonable floor.

**Where it is weak.** No follow-up. If the first spelling is wrong it never finds the right one.

Code: `bench/baselines/llm_agents.py` (agent `B0`). Config: `config.json`. Preregistered.
