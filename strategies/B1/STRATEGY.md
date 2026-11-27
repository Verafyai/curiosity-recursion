# B1: ReAct LLM agent

**What it is.** A tool-using model loop (reason, act, observe) that keeps going until it says it
is done or the tool-call budget runs out.

**How it hunts records.** The model reads each result and decides the next search itself: name
variants, places it saw in a snippet, a book to search inside, newspapers in a date range.

**Where it is strong.** Adapts to what it finds; good at trying spellings.

**Where it is weak.** Usually stops early on its own ("model stopped"), holds no memory across
runs, and nothing checks that a follow-up is grounded in a finding.

Code: `bench/baselines/llm_agents.py` (agent `B1`). Config: `config.json`. Preregistered.
