"""The evidence model: leads versus facts, and named conflicts.

Kin rules this follows (brand-reference/kin-CLAUDE-invariants.md, handoff section 5):
- An OCR or search-snippet match is a lead, never a claim, and never decides a date.
  Leads are tier "possible". They are shown with their quote and never reach the narrative.
- "inferred" exists for reasoning and conflict detection only and is never published (invariant 7).
- No shared-surname family links: a parents lead needs the subject's full name in the text
  and the subject's own given name just before "son of" / "daughter of".
- Conflicts are not resolved (invariant 13). Two leads or claims that disagree both stay,
  and the disagreement is named.

Pure and deterministic. It runs inside the compose_report activity.
"""

from __future__ import annotations

import re
from typing import Iterable

from studio.models import Citation, Claim, Conflict, Finding, Lead, Person, Question
from studio.names import match

PARENTS = re.compile(r"\b(?:son|daughter|dau\.?)\s+of\s+([A-Z][a-z]+(?:\s[A-Z]\.)?)\s+and\s+([A-Z][a-z]+)(?:\s*\(([A-Z][a-z]+)\))?")
MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
_DATE = rf"(?P<date>(?:(?:{MONTHS})\.?\s+\d{{1,2}},?\s+)?(?P<y>1[6-9]\d\d))\b"
BORN = re.compile(rf"\bborn\b[^.;]{{0,40}}?\b{_DATE}")
DIED = re.compile(rf"\bdied\b[^.;]{{0,40}}?\b{_DATE}")


def _clean(s: str) -> str:
    return " ".join((s or "").replace("**", "").split())


def names_subject_before(text: str, start: int, full_name: str) -> bool:
    """The subject's given name sits just before this match, so a sibling's line is not used."""
    given = full_name.replace(".", " ").split()[0] if full_name.strip() else ""
    before = text[max(0, start - 70):start]
    last_name_before = re.findall(r"\b([A-Z][a-z]+)\s+(?:[A-Z]\.\s*)*[A-Z][a-z]+,?\s*$", before)
    return bool(given) and given in before and (not last_name_before or last_name_before[-1] == given)


def _quote(text: str, start: int, end: int, pad: int = 90) -> str:
    a, b = max(0, start - pad), min(len(text), end + pad)
    return ("..." if a else "") + text[a:b].strip() + ("..." if b < len(text) else "")


def _sources(findings: Iterable[Finding], questions: Iterable[Question]) -> list[tuple[str, Citation]]:
    """(question or step id, citation) for every snippet seen, questions first, deduped by url+snippet."""
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, Citation]] = []
    for q in questions:
        for c in q.citations:
            k = (c.url or c.title, _clean(c.snippet or ""))
            if c.snippet and k not in seen:
                seen.add(k)
                out.append((q.id, c))
    for f in findings:
        if f.about:
            continue
        for c in f.citations:
            k = (c.url or c.title, _clean(c.snippet or ""))
            if c.snippet and k not in seen:
                seen.add(k)
                out.append((f.step_id, c))
    return out


def _name_at(person: Person, text: str) -> int:
    """Where the subject's name starts in the text, so the quote is centred on it."""
    parts = person.full_name.replace(".", " ").split()
    if len(parts) >= 2:
        m = re.search(rf"\b{re.escape(parts[0])}\b[^.;]{{0,30}}?\b{re.escape(parts[-1])}\b", text) or \
            re.search(rf"\b{re.escape(parts[-1])},?\s+{re.escape(parts[0])}\b", text)
        if m:
            return m.start()
    return 0


def _in_comma_list(person: Person, text: str) -> bool:
    """The name sits in a comma separated list, such as a regimental roster.

    A roster can print "Surname, Given" entries one after another ("Burke, John Burnham, Erastus W.
    Carlan, John"), and the local text alone does not say which way to read it. Earlier this code
    called such a match weak; on the 12th Connecticut roster that was wrong (the page lists
    surname first, so "Burnham, Erastus W." is a real entry). Now the match is kept as a normal lead
    and the note asks a person to check the list's name order on the page.
    """
    parts = person.full_name.replace(".", " ").split()
    if len(parts) < 2:
        return False
    return bool(re.search(rf"\b{re.escape(parts[-1])},\s+{re.escape(parts[0])}\b", text)) and text.count(",") >= 4


def _title(t: str) -> str:
    return re.sub(r"\s*[;:,]+(?=\s*,|\s*$)", "", t).strip()


def _source_id(c: Citation) -> str:
    if c.item_id:
        return f"ia:{c.item_id}"
    return c.url or c.title


def extract_leads(person: Person, findings: list[Finding], questions: list[Question]) -> list[Lead]:
    """Possible claims from snippets. Every one keeps its verbatim quote and how it was matched."""
    leads: list[Lead] = []
    sname = person.full_name.replace(".", " ").split()[-1] if person.full_name.strip() else ""
    seen_values: set[tuple[str, str, str]] = set()

    seen_quotes: set[tuple[str, str]] = set()

    def add(field: str, text: str, value: str, quote: str, cit: Citation, origin: str, matched_by: str,
            year: int | None = None, span: str = "", confidence: str = "candidate"):
        k = (field, value, _source_id(cit))
        qk = (field, re.sub(r"[^a-z0-9]", "", quote.lower()))
        hits.append(field)
        if k in seen_values or qk in seen_quotes:
            return
        seen_values.add(k)
        seen_quotes.add(qk)
        leads.append(Lead(id=f"lead-{len(leads) + 1}", field=field, text=text, value=value, year=year, quote=quote,
                          span=span, citation=cit, source_id=_source_id(cit), confidence=confidence,
                          matched_by=matched_by, question_id=origin))

    hits: list[str] = []
    for origin, cit in _sources(findings, questions):
        hits.clear()
        text = _clean(cit.snippet)
        strong = match(person, text) == "strong"
        for m in PARENTS.finditer(text):
            if not strong or not names_subject_before(text, m.start(), person.full_name):
                continue
            father, mother, maiden = m.group(1), m.group(2), m.group(3)
            label = f"{father} and {mother}" + (f" ({maiden})" if maiden else "") + f" {sname}"
            add("parents", f"Parents named as {label}", f"{father.split()[0].lower()}|{mother.lower()}",
                _quote(text, m.start(), m.end()), cit, origin,
                "Full name in the source text, and the given name just before \"son of\"", span=m.group(0))
        for field, rx in (("birth", BORN), ("death", DIED)):
            for m in rx.finditer(text):
                if not strong:
                    continue
                win = text[max(0, m.start() - 120):m.start()]
                if match(person, win) != "strong":
                    continue
                yr = int(m.group("y"))
                add(field, f"{'Born' if field == 'birth' else 'Died'} {m.group('date')}", str(yr),
                    _quote(text, m.start(), m.end()), cit, origin,
                    "Full name within 120 characters before the date. A snippet never decides a date", year=yr, span=m.group(0))
        if strong and not hits and not any(l.source_id == _source_id(cit) for l in leads):
            at = _name_at(person, text)
            listed = _in_comma_list(person, text)
            add("mention", f"Named in {cit.title}", "mention", _quote(text, at, at, pad=150), cit, origin,
                ("Full name found in a comma separated list. Check the list's name order on the page, and whether it is the same man"
                 if listed else "Full name string found in OCR text. It may be someone else with the same name"))
    return leads


def detect_conflicts(facts: list[Claim], leads: list[Lead]) -> list[Conflict]:
    """Name every disagreement. Nothing is resolved and nothing is dropped."""
    out: list[Conflict] = []
    parents: dict[str, list[Lead]] = {}
    for l in leads:
        if l.field == "parents":
            parents.setdefault(l.value, []).append(l)
    if len(parents) > 1:
        pairs = [ls[0].text.replace("Parents named as ", "") for ls in parents.values()]
        out.append(Conflict(id=f"conflict-{len(out) + 1}", field="parents",
                            label=f"Two different parent pairs are named: {' and, separately, '.join(pairs)}",
                            claim_ids=[l.id for ls in parents.values() for l in ls],
                            note="Both stay. A shared surname is not enough to choose between them; a vital record would be."))
    for field in ("birth", "death"):
        doc = [c for c in facts if c.field == field and c.year]
        for l in leads:
            if l.field != field or l.year is None:
                continue
            clash = [c for c in doc if c.year != l.year]
            if clash:
                same = [o for o in leads if o.id != l.id and o.span and o.span in l.quote]
                others = list(dict.fromkeys(o.text for o in same if o.field != field))
                also = f" The same passage also has: {'; '.join(others)}." if others else ""
                out.append(Conflict(id=f"conflict-{len(out) + 1}", field=field,
                                    label=f"A {field} year of {l.year} in {_title(l.citation.title)} disagrees with the record ({clash[0].year})",
                                    claim_ids=[clash[0].id, l.id, *[o.id for o in same]],
                                    note=("The documented record stands in the text. The lead is kept and shown, not used."
                                          + also + (" That passage may describe a different man with the same name." if also else ""))))
        lead_years = sorted({l.year for l in leads if l.field == field and l.year})
        if len(lead_years) > 1 and not doc:
            out.append(Conflict(id=f"conflict-{len(out) + 1}", field=field,
                                label=f"Sources give different {field} years: {', '.join(map(str, lead_years))}",
                                claim_ids=[l.id for l in leads if l.field == field],
                                note="No documented record yet. None of these decides the date."))
    return out
