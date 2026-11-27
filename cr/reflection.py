"""Reflection memory between rounds (spec section 7). Rules only, deterministic.

Reflexion (`shinn2023reflexion`) keeps short verbal lessons from earlier attempts and feeds them into
the next attempt; generative agents (`park2023generative`) retrieve such memories by relevance. Here
the lessons are generated from round statistics (no model) and change the next round's priors: dead
ends lower a tool/viewpoint's expected yield, productive sources raise adjacent-page leads, variant
hits raise name-variant leads, namesake risks become filters and verified relatives enable keys.
Per run only; cross-run memory (cr/memory.py) stays off in the bench.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

MAX_LESSONS = 5


class Lesson(BaseModel):
    type: Literal["dead_end", "productive_source", "variant_hit", "namesake_risk", "new_relative"]
    text: str
    key: str
    evidence: str = ""
    round: int = 0


def reflect(round_no: int, calls: list[dict], namesakes: list[dict], relatives: list[dict], known: set[str]) -> list[Lesson]:
    """calls: [{tool, lane, viewpoint, source, terms, name_form, canonical, n_items, n_matched, hit_pages}]"""
    out: list[Lesson] = []
    by_pattern: dict[str, list[dict]] = {}
    for c in calls:
        by_pattern.setdefault(f"{c['tool']}|{c['viewpoint']}", []).append(c)
    for pat, cs in sorted(by_pattern.items()):
        if len(cs) >= 3 and all(x["n_matched"] == 0 for x in cs):
            out.append(Lesson(type="dead_end", key=pat, round=round_no, evidence=", ".join(x["canonical"] for x in cs[:3]),
                              text=f"{pat.replace('|', ' in the ')} lane returned nothing matching {len(cs)} times"))
    for c in calls:
        if c["source"].startswith("ia_book:") and c["n_matched"] and c.get("hit_pages"):
            pages = sorted(c["hit_pages"])
            out.append(Lesson(type="productive_source", key=c["source"], round=round_no, evidence=c["canonical"],
                              text=f"{c['source'][8:]} had hits on pages {pages[0]}-{pages[-1]}"))
        if c.get("name_form") and c.get("is_variant") and c["n_matched"]:
            out.append(Lesson(type="variant_hit", key=c["name_form"].lower(), round=round_no, evidence=c["canonical"],
                              text=f"spelling {c['name_form']} matched on {c['source']}"))
    for n in namesakes:
        out.append(Lesson(type="namesake_risk", key=n["key"], round=round_no, evidence=n.get("url", ""),
                          text=f"{n['name']} in a record dated {n['year']} is outside the life window: probably a different person"))
    for r in relatives:
        out.append(Lesson(type="new_relative", key=r["name"].lower(), round=round_no, evidence=r.get("source", ""),
                          text=f"verified relative {r['name']} ({r['relation']}) passed the living-person gate"))
    fresh, seen = [], set(known)
    for ls in out:
        k = f"{ls.type}:{ls.key}"
        if k not in seen:
            seen.add(k)
            fresh.append(ls)
    return fresh[:MAX_LESSONS]


def yield_adjustment(lessons: list[Lesson], tool: str, viewpoint: str) -> float:
    adj = 0.0
    for ls in lessons:
        if ls.type == "dead_end" and ls.key == f"{tool}|{viewpoint}":
            adj -= 0.2
    return adj


def variant_boost(lessons: list[Lesson]) -> float:
    return 0.15 if any(ls.type == "variant_hit" for ls in lessons) else 0.0
