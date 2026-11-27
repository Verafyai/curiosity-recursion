# B5-fix: CR with the rules2 generator (post hoc fix)

**What it is.** CR with a repaired rules generator, `rules2`, breadth 5, depth 4, node cap 300 so
that the tool-call budget is what binds. Not preregistered. Built from a diagnosis of B5 on the
Burnham dossier only, so the other five people are out-of-sample for it.

**What rules2 changes (generic, nothing person-specific):**
- Name forms from the card alone: given plus surname, middle initial, initials, "Saint" spelled out
  (records rarely print a full middle name).
- Surname particles kept ("St. John", "van", "de").
- Spellings seen in strong, in-life snippets become new searches.
- Place, town-history, newspaper-per-15-year-window and obituary openers.
- A life-window filter so snippets from the wrong century do not spawn follow-ups.
- No repeat search inside the same book; no repeat of an identical call under a different key.
- "Keep going": when the graph runs dry with budget left, re-brainstorm from the root with
  everything found so far.

Code: `cr/generators/rules.py` (`brainstorm(..., v2=True)`), `cr/workflow.py` (keep going, gated
to `rules2` so preregistered histories replay unchanged). Config: `config.json`.
