# B5: Curiosity Recursion (preregistered)

**What it is.** The full system as preregistered: circuit checklist first, then a rules question
generator that turns each finding into follow-up questions. Each question must quote the finding
that sparked it, is deduplicated against memory, and runs as a retried Temporal activity.
Breadth 3, depth 3, node cap 80, budget B tool calls.

**How it hunts records.** From a strong name match in a book it asks "does this book name him on
another page?" (search inside), from a unit or place it asks for regimental or town histories,
from a death it asks for an obituary, and so on (`cr/generators/rules.py`).

**Known weaknesses (measured).** It runs out of questions at about 25 tool calls whatever the
budget; it follows namesakes from the wrong century; it never tries spellings other than the
card's; surnames with a particle ("St. John") were parsed as "John". See B5-fix.

Code: `cr/workflow.py`, `cr/generators/rules.py`. Config: `config.json`. Preregistered.
