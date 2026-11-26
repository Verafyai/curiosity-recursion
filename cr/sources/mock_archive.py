"""Simulated archives for the benchmark. Nothing here talks to a real archive.

A real small archive answers a letter weeks later, or never. `plan_reply()` decides, from a
seed and the draft, whether a simulated archive answers, after how many days, and with what:
a record from the subject's hidden ground truth (when one is held by that kind of holder),
"no record", or silence. bench/faults.py sends the reply as the workflow's `archive_reply`
signal after the delay (time-skipped in tests).
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Optional

from cr.models import ArchiveReply, OutreachDraft


@dataclass
class ReplyPlan:
    draft_id: str
    delay_days: Optional[float]  # None = never answers
    reply: Optional[ArchiveReply]


def plan_reply(draft: OutreachDraft, held_records: list[dict], seed: int,
               p_silent: float = 0.3, days: tuple[float, float] = (3, 21)) -> ReplyPlan:
    rng = random.Random(f"{seed}:{draft.id}:{draft.to}")
    if rng.random() < p_silent:
        return ReplyPlan(draft.id, None, None)
    delay = rng.uniform(*days)
    match = [r for r in held_records if _holder_matches(draft.to, r)]
    if match:
        r = rng.choice(match)
        return ReplyPlan(draft.id, delay, ArchiveReply(
            draft_id=draft.id, outcome="record", text=f"Simulated archive reply: we hold {r.get('title', 'a record')}.",
            record_title=r.get("title"), record_url=r.get("url")))
    return ReplyPlan(draft.id, delay, ArchiveReply(draft_id=draft.id, outcome="no_record",
                                                   text="Simulated archive reply: we hold no record for this person."))


def _holder_matches(to: str, record: dict) -> bool:
    t = to.lower()
    holder = (record.get("archive") or "").lower()
    return bool(holder) and (holder in t or any(w in t for w in holder.split() if len(w) > 5))
