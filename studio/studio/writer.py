"""Compose the Studio report. Deterministic, no model.

Follows kin's content studio rules (lib/content/studio.ts, lib/content/validate.ts):
- the text is written only from documented (and told) claims; every sentence carries claim ids
- check_sentence() is a port of validate.ts checkSentence: a sentence drops when it cites no
  claim, cites a lead ("possible") or an inferred claim, states an interior state, makes a
  causal link no claim makes, tells a family story in the narrative voice, or uses a number
  no cited record holds
- card thresholds: newsletter 2 facts, chapter 8, documentary 'soon'
- brainstorm hits become leads (studio/evidence.py): tier "possible", quoted, never narrative fact
- disagreements are named as conflicts and never resolved
"""

from __future__ import annotations

import re

from studio.brainstorm import checklist
from studio.circuits import CIRCUITS
from studio.evidence import detect_conflicts, extract_leads
from studio.models import (
    PUBLISHABLE_TIERS, CardState, Claim, Citation, ComposeInput, Dropped, Lead, Section, Sentence, Stats, StudioReport,
)

THRESHOLD = {"chapter": 8, "newsletter": 2, "documentary": 20}
PRICE = {"chapter": 400, "newsletter": 150, "documentary": 1200}
INTERIOR = re.compile(r"\b(must have|would have (?:felt|been|known|wanted)|surely|no doubt|doubtless|perhaps (?:he|she|they)|(?:he|she|they) (?:felt|wondered|dreamed|feared|hoped|longed|imagined|thought|remembered)|one can imagine|imagine|likely felt|probably felt)\b", re.I)
CAUSAL = re.compile(r"\b(because|as a result|therefore|thus|which led|led him|led her|so that|thanks to|in order to|owing to|due to)\b", re.I)
FAMILY_FRAME = re.compile(r"\b(your family remembers|the family remembers|family tradition|the family says|according to (?:the )?family|family story|family recalls)\b", re.I)
NUMBER = re.compile(r"\b\d+\b")
WORDS = ["No", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten"]


def _word(n: int) -> str:
    return WORDS[n] if 0 <= n < len(WORDS) else str(n)


def studio_lead(published: int, first_name: str) -> str:
    """Port of kin lib/content/studio.ts studioLead()."""
    if published >= THRESHOLD["chapter"]:
        return (f"Written from the {published} sourced facts on this page and nothing else. "
                "Every paragraph carries a footnote to the record it rests on.")
    who = first_name or "this person"
    count = f"{_word(published)} sourced {'fact' if published == 1 else 'facts'} about {who}"
    if published < THRESHOLD["newsletter"]:
        return f"{count}. That is not yet enough to write from, and nothing here is invented."
    return (f"{count}. That is enough for a short notice and not enough for a chapter: a chapter written from "
            f"{_word(published).lower()} facts would be mostly invention, and nothing here is invented.")


def proof_line(used: int, footnoted: int, uncited: int) -> str:
    """Port of kin proofLine(): '9 claims used, 9 footnoted, 0 uncited sentences.'"""
    return (f"{used} {'claim' if used == 1 else 'claims'} used, {footnoted} footnoted, "
            f"{uncited} uncited {'sentence' if uncited == 1 else 'sentences'}.")


def check_sentence(sentence: Sentence, claims: dict[str, Claim], leads: dict[str, Lead] | None = None) -> str | None:
    """One sentence against the claims it cites. None means it stands; a string is why it drops."""
    leads = leads or {}
    text = sentence.text.strip()
    if not text:
        return "empty"
    if not sentence.claim_ids:
        return "no claim cited"
    if any(i in leads for i in sentence.claim_ids):
        return "cites a possible lead, not a record"
    cited = [claims.get(i) for i in sentence.claim_ids]
    if any(c is None for c in cited):
        return "cites a claim that is not in the set"
    if any(c.tier == "inferred" for c in cited):
        return "cites an inferred claim, which is never published"
    if any(c.tier not in PUBLISHABLE_TIERS for c in cited):
        return "cites a possible lead, not a record"
    support = " ".join(f"{c.text} {c.citation.title}" for c in cited)
    if INTERIOR.search(text):
        return "an interior state no record states"
    cm = CAUSAL.search(text)
    if cm and cm.group(0).lower() not in support.lower():
        return f'a causal link ("{cm.group(0)}") no record makes'
    if any(c.tier in ("told", "lore") for c in cited) and all(c.tier != "documented" for c in cited) and not FAMILY_FRAME.search(text):
        return "family tradition told in the narrative voice"
    have = set(NUMBER.findall(support))
    for n in NUMBER.findall(text):
        if n not in have and str(int(n)) not in have:
            return f'"{n}" is not in the cited records'
    return None


def _told_sentence(notes: str) -> str:
    notes = notes.strip().rstrip(".")
    first = notes.split()[0].lower() if notes else ""
    if first in ("he", "she", "they", "his", "her", "their", "the", "a", "an"):
        return f"Your family remembers that {notes[0].lower()}{notes[1:]}."
    return f'Your family remembers that "{notes}."'


SECTIONS = {
    "service-record": [("Before the war", lambda c: c.field != "military" and (c.year or 0) < 1861),
                       ("Service", lambda c: c.field == "military"),
                       ("After the war", lambda c: True)],
    "the-crossing": [("Where she came from", lambda c: c.field in ("birth",)),
                     ("The crossing", lambda c: c.field in ("immigration", "arrival", "naturalization")),
                     ("Settling", lambda c: c.field in ("marriage", "residence", "occupation", "child")),
                     ("The end of the record", lambda c: True)],
    "book-of-daniel": [("Early life", lambda c: c.field in ("birth", "education")),
                       ("Work and family", lambda c: c.field in ("occupation", "marriage", "child", "residence", "membership")),
                       ("Later life", lambda c: True)],
}


def _sentence(c: Claim) -> Sentence:
    t = c.text.strip().rstrip(".") + "."
    return Sentence(text=t, claim_ids=[c.id])


def compose(inp: ComposeInput) -> StudioReport:
    req, p = inp.request, inp.request.person
    circuit = CIRCUITS[req.circuit_id]
    template = req.template or circuit.template
    facts: dict[str, Claim] = {}
    for f in inp.findings:
        if f.about:
            continue
        for c in f.claims:
            facts.setdefault(c.id, c)
    told: list[Claim] = []
    if p.family_notes and p.family_notes.strip():
        told.append(Claim(id="told-1", field="family_story", text=p.family_notes.strip(), tier="told",
                          citation=Citation(title="Family notes entered on the Studio form"), origin="user:form"))
    leads = extract_leads(p, inp.findings, inp.questions)
    lead_ix = {l.id: l for l in leads}
    claims = {**facts, **{t.id: t for t in told}}
    ordered = sorted(facts.values(), key=lambda c: (c.year or 9999, c.id))
    dropped: list[Dropped] = []
    sections: list[Section] = []
    used: set[str] = set()
    for heading, pred in SECTIONS.get(template, SECTIONS["book-of-daniel"]):
        sec = Section(heading=heading)
        for c in ordered:
            if c.id in used or not pred(c):
                continue
            s = _sentence(c)
            why = check_sentence(s, claims, lead_ix)
            if why:
                dropped.append(Dropped(text=s.text, reason=why))
                continue
            used.add(c.id)
            sec.sentences.append(s)
        if not sec.sentences:
            sec.empty_line = "No documented record for this part yet."
        sections.append(sec)
    told_used: list[Claim] = []
    if told:
        sec = Section(heading="What the family says")
        for t in told:
            s = Sentence(text=_told_sentence(t.text), claim_ids=[t.id])
            why = check_sentence(s, claims, lead_ix)
            if why:
                dropped.append(Dropped(text=s.text, reason=why))
                continue
            sec.sentences.append(s)
            told_used.append(t)
        if sec.sentences:
            sections.append(sec)

    n = len(used)
    cards = []
    for kind in ("chapter", "newsletter", "documentary"):
        if kind == "documentary":
            cards.append(CardState(kind=kind, state="soon", price_credits=PRICE[kind]))
        elif n >= THRESHOLD[kind]:
            cards.append(CardState(kind=kind, state="ready", have=n, price_credits=PRICE[kind]))
        else:
            cards.append(CardState(kind=kind, state="thin", have=n, need=THRESHOLD[kind] - n, price_credits=PRICE[kind]))

    first = p.full_name.split()[0] if p.full_name.split() else ""
    lead = studio_lead(n, first)
    published = [facts[i] for i in sorted(used, key=lambda i: (facts[i].year or 9999, i))]
    conflicts = detect_conflicts(published, leads)

    gaps = checklist(req, inp.findings)
    open_q = [f"{q.id}: {q.text} ({q.status.replace('_', ' ')})" for q in inp.questions if q.status in ("no_lead", "stub", "pending", "error")]
    live = sorted({f.step_title for f in inp.findings if f.mode == "live"})
    stub = sorted({f.step_title for f in inp.findings if f.mode == "stub"})
    deeper = [f"{g.label}: nothing yet" for g in gaps if g.state == "missing"]
    title = f"{p.full_name}" + (f", {p.birth_year or '?'} to {p.death_year or '?'}" if (p.birth_year or p.death_year) else "")
    all_sentences = [x for sec in sections for x in sec.sentences]
    cited = {i for x in all_sentences for i in x.claim_ids}
    stats = Stats(used=len(cited), footnoted=len(cited), uncited=sum(1 for x in all_sentences if not x.claim_ids))

    rep = StudioReport(
        subject=p, question=req.question, circuit_id=req.circuit_id, template=template, output_kind=req.output_kind, gate=inp.gate,
        title=title, lead=lead, sections=sections, facts=published, told=told_used, leads=leads, conflicts=conflicts,
        open_questions=open_q, deeper=deeper, dropped=dropped, stats=stats, cards=cards,
        live_steps=live, stub_steps=stub, rounds=inp.rounds, questions=inp.questions, checklist=gaps, stop_reason=inp.stop_reason,
        reviewer_notes=inp.reviewer_notes,
    )
    if not inp.gate.allowed:
        rep.decision = "blocked"
        rep.lead = "This person may be living, so Lineage does not write about them."
        rep.sections, rep.facts, rep.told, rep.leads, rep.conflicts = [], [], [], [], []
    rep.markdown = to_markdown(rep)
    return rep


def to_markdown(r: StudioReport) -> str:
    L = [f"# {r.title}", "", f"_{r.circuit_id} circuit, {r.template} template. {r.gate.reason}_", "", r.lead, ""]
    notes = {c.id: i for i, c in enumerate(r.facts + r.told, 1)}
    for s in r.sections:
        L.append(f"## {s.heading}")
        if s.empty_line:
            L.append(f"_{s.empty_line}_")
        L.append(" ".join(f"{x.text}" + "".join(f"[^{notes.get(i, '?')}]" for i in x.claim_ids) for x in s.sentences))
        L.append("")
    if r.sections:
        L.append(f"_{proof_line(r.stats.used, r.stats.footnoted, r.stats.uncited)}_")
        L.append("")
    if r.conflicts:
        L.append("## Conflicts (named, not resolved)")
        L += [f"- {c.label}. {c.note} ({', '.join(c.claim_ids)})" for c in r.conflicts]
        L.append("")
    if r.leads:
        L.append("## Possible (leads, not facts)")
        for l in r.leads:
            L.append(f"- POSSIBLE **{l.text}** ({l.id}, from {l.question_id}). [{l.citation.title}]({l.citation.url or ''}): \"{l.quote[:240]}\" _Matched by: {l.matched_by}_")
        L.append("")
    if r.open_questions:
        L.append("## Open questions")
        L += [f"- {x}" for x in r.open_questions]
        L.append("")
    L.append("## Sources")
    for c in r.facts + r.told:
        L.append(f"[^{notes[c.id]}]: {c.tier.upper()}. {c.citation.title}" + (f" {c.citation.url}" if c.citation.url else "") + f" ({c.origin})")
    return "\n".join(L)
