# B3: checklist only

**What it is.** CR with the question generator switched off. It runs the circuit checklist for the
person's kind of life (here `vital_records`) and stops.

**How it hunts records.** Fixed steps: Wikidata, a books full-text search for the name, a
newspaper search over the life window, title searches for local histories, and stubs for
sources with no keyless API (census, Find a Grave, state archives).

**Where it is strong.** Predictable and cheap; it shows what the circuit alone buys.

**Where it is weak.** It never asks a follow-up question.

Code: `cr/workflow.py` with `mode="checklist"`. Config: `config.json`. Preregistered.
