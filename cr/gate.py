"""Living-person gate. A port of kin lib/gate.ts isPresumedLiving.

A person is researched only if a death year is on record (and its precision is not "after"),
or the birth year is at least MAX_PLAUSIBLE_AGE years before the current year.
UNKNOWN DEFAULTS TO LIVING. Never flip this default.

The workflow calls `gate()` with `workflow.now().year`, so the decision is deterministic and
recorded in history; it runs in workflow code, never only at the UI.
"""
from __future__ import annotations

from cr.models import GateResult, Person

MAX_PLAUSIBLE_AGE = 110
RULE = ("Research runs only when a death is on record, or a birth at least 110 years ago "
        "(port of kin lib/gate.ts isPresumedLiving). Unknown defaults to living.")


def is_presumed_living(p: Person, current_year: int) -> bool:
    if p.death_year is not None and p.death_year_precision != "after":
        return False
    if p.birth_year is not None and current_year - p.birth_year >= MAX_PLAUSIBLE_AGE:
        return False
    return True  # UNKNOWN DEFAULTS TO LIVING.


def gate(p: Person, current_year: int) -> GateResult:
    if not is_presumed_living(p, current_year):
        if p.death_year is not None and p.death_year_precision != "after":
            return GateResult(allowed=True, rule=RULE, reason=f"Death on record ({p.death_year}), so research can run.")
        return GateResult(allowed=True, rule=RULE,
                          reason=f"Born {p.birth_year}, at least {MAX_PLAUSIBLE_AGE} years ago, so research can run.")
    return GateResult(allowed=False, rule=RULE,
                      reason="No death on record and no birth at least 110 years ago, so this person is presumed living. Nothing was searched.")
