"""Explore mode: an interactive research graph. Pure, deterministic code (safe in workflows and activities).

Every node (the person, a record, a book page, a newspaper page, a Wikidata item, a fact) carries its own list
of brainstormed follow-up questions. Nothing is researched until the user clicks "Research this" on a question:
that click is the permission. A research pass runs one question and attaches what it found as child nodes, each
with its own new questions. "Dig deeper" brainstorms a fresh, wider set for a node without repeating anything
already asked on that path; "Add question" takes the user's own words.

Rules that hold here:
- living-person gate (`gate`), the same rule as StudioRunWorkflow: a recorded death, or born 110 or more years ago
- a shared surname alone is never a family link: a hit that only matches the surname becomes a "Possible" node
  and its questions ask whether it is the same person, never treat it as kin
- every node built from a search hit is tier "possible" until a documented claim backs it; nothing is invented:
  nodes are built only from returned citations and claims
- offline sources (pension files, small archives, clerks) never run: they offer "Draft outreach", which writes a
  draft held for approval. Nothing is ever sent.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

from studio.circuits import CIRCUITS, STEPS
from studio.models import (
    Citation, Claim, Finding, GateResult, OutreachDraft, Person, Plan, Question, ResearchRequest, StudioReport,
)
from studio.names import given, surname, town_state

MAX_AGE = 110
GATE_RULE = "Research runs only when a death is on record, or a birth more than 110 years ago (kin lib/gate.ts)."

Generator = Literal["rules", "rules:checklist", "rules:dig-deeper", "model", "user", "chat"]
QStatus = Literal["open", "queued", "running", "answered", "no_lead", "skipped", "failed", "outreach_drafted"]
NodeKind = Literal["person", "fact", "book", "page", "newspaper", "wikidata", "record", "link"]
NodeState = Literal["done", "queued", "running", "failed", "waiting_approval"]

# Tool calls one research pass is expected to make, by handler (shown before the user confirms).
CALLS = {"ia_fulltext": 1, "ia_title": 1, "chronam": 1, "ia_inside": 2, "wikidata": 2, "wikidata_kin": 2, "stub": 0}
STEP_CALLS = {"fixture": 0, "findagrave": 0, "relatives_photos": 0, "relatives_sources": 0, "wikidata": 2, "wikidata_kin": 3, "ia": 1, "chronam": 1}
OFFLINE_WORDS = ("pension", "clerk", "archive", "society", "library", "collection", "church", "probate", "letter")


# ------------------------------------------------------------------ models (cross Temporal boundaries)

class XQuestion(BaseModel):
    id: str
    node_id: str
    key: str
    text: str
    because: str = ""
    generator: Generator = "rules"
    kind: Literal["research", "checklist_step", "outreach"] = "research"
    plan: Optional[Plan] = None
    step_id: Optional[str] = None
    template: str = ""
    about: Optional[str] = None
    status: QStatus = "open"
    produced: list[str] = Field(default_factory=list, description="Node ids this question's pass produced")
    est_calls: int = 0
    answer: str = ""
    error: str = ""
    edited_from: Optional[str] = None
    outreach_id: Optional[str] = None
    pass_id: Optional[str] = None


class XNode(BaseModel):
    id: str
    kind: NodeKind
    label: str
    summary: str = ""
    parent_id: Optional[str] = None
    via_question: Optional[str] = None
    tier: Literal["documented", "told", "possible"] = "possible"
    citations: list[Citation] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    state: NodeState = "done"
    error: str = ""
    depth: int = 0
    about: Optional[str] = None
    handler: str = ""
    query: str = ""


class PassInfo(BaseModel):
    id: str
    question_id: str
    node_id: str
    state: Literal["queued", "running", "done", "failed"] = "queued"
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    calls: int = 0
    error: str = ""
    found: int = 0


class ExploreProgress(BaseModel):
    workflow_id: str = ""
    request: Optional[ResearchRequest] = None
    started_at: Optional[datetime] = None
    status: Literal["starting", "exploring", "blocked_living", "writing", "awaiting_approval", "approved", "rejected"] = "starting"
    gate: Optional[GateResult] = None
    nodes: list[XNode] = Field(default_factory=list)
    questions: list[XQuestion] = Field(default_factory=list)
    passes: list[PassInfo] = Field(default_factory=list)
    outreach: list[OutreachDraft] = Field(default_factory=list)
    calls_used: int = 0
    call_budget: int = 100
    confirm_over_calls: int = 2
    report: Optional[StudioReport] = None
    log: list[str] = Field(default_factory=list)
    seq: int = 0


# ------------------------------------------------------------------ commands (workflow updates)

class ResearchCmd(BaseModel):
    question_id: str
    confirmed: bool = Field(default=False, description="Second confirm, required when the cost is over the threshold")


class EditCmd(BaseModel):
    question_id: str
    text: str
    query: str = ""


class AddCmd(BaseModel):
    node_id: str
    text: str
    query: str = ""
    generator: Generator = "user"
    because: str = ""


class NodeCmd(BaseModel):
    node_id: str


class QuestionCmd(BaseModel):
    question_id: str


class PassInput(BaseModel):
    request: ResearchRequest
    pass_id: str
    question: XQuestion
    node: XNode
    known_keys: list[str]
    next_node_no: int


class PassOutput(BaseModel):
    pass_id: str
    question: XQuestion
    nodes: list[XNode] = Field(default_factory=list)
    questions: list[XQuestion] = Field(default_factory=list)
    outreach: Optional[OutreachDraft] = None
    calls: int = 0
    finding: Optional[Finding] = None


class SeedInput(BaseModel):
    request: ResearchRequest
    node: XNode
    known_keys: list[str]
    deeper: bool = False
    path_keys: list[str] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    start_no: int = 1


class SeedOutput(BaseModel):
    questions: list[XQuestion]
    generated: int = 0
    duplicates_skipped: int = 0


# ------------------------------------------------------------------ pure rules

def gate(p: Person, year: int) -> GateResult:
    if p.death_year is not None and p.death_year_precision != "after":
        return GateResult(allowed=True, rule=GATE_RULE, reason=f"Death on record ({p.death_year}), so research can run.")
    if p.birth_year is not None and year - p.birth_year >= MAX_AGE:
        return GateResult(allowed=True, rule=GATE_RULE, reason=f"Born {p.birth_year}, more than {MAX_AGE} years ago, so research can run.")
    return GateResult(allowed=False, rule=GATE_RULE,
                      reason="No death on record and no birth more than 110 years ago, so this person is presumed living. Nothing was searched.")


def norm_key(*parts: str) -> str:
    return ":".join(re.sub(r"[^a-z0-9]+", "-", (p or "").lower()).strip("-") for p in parts if p)


def est_calls(q: XQuestion) -> int:
    if q.kind == "outreach":
        return 0
    if q.kind == "checklist_step" and q.step_id in STEPS:
        return STEP_CALLS.get(STEPS[q.step_id].handler, 1)
    return CALLS.get(q.plan.handler if q.plan else "ia_fulltext", 1)


def offline(q: XQuestion) -> bool:
    return q.kind == "outreach" or (q.plan is not None and q.plan.handler == "stub")


def path_ids(nodes: dict[str, XNode], node_id: str) -> list[str]:
    out, cur = [], nodes.get(node_id)
    while cur is not None:
        out.append(cur.id)
        cur = nodes.get(cur.parent_id) if cur.parent_id else None
    return out


def _x(q: Question, node_id: str, generator: Generator, no: int) -> XQuestion:
    kind = "outreach" if q.plan.handler == "stub" else "research"
    x = XQuestion(id=f"{node_id}-q{no}", node_id=node_id, key=q.key, text=q.text, because=q.because, generator=generator,
                  kind=kind, plan=q.plan, template=q.template, about=q.about)
    x.est_calls = est_calls(x)
    return x


def person_questions(req: ResearchRequest, rules_picked: list[Question], start_no: int = 1) -> list[XQuestion]:
    """The person node's list: the brainstorm openers (books that name him, checklist gaps) and every step of
    the circuit's baseline checklist, each as its own question the user can run."""
    out: list[XQuestion] = []
    seen: set[str] = set()
    n = start_no
    for q in rules_picked:
        if q.key in seen:
            continue
        seen.add(q.key)
        out.append(_x(q, "person", "rules", n))
        n += 1
    circuit = CIRCUITS[req.circuit_id]
    step_ids = list(dict.fromkeys(["wikidata_identity", *[s for t in circuit.topics for s in t.steps]]))
    for sid in step_ids:
        st = STEPS[sid]
        key = norm_key("step", sid)
        if key in seen:
            continue
        seen.add(key)
        src = "STUB: reads the curated fixture, not a live lookup" if st.mode == "stub" else "live"
        x = XQuestion(id=f"person-q{n}", node_id="person", key=key, text=_step_question(st.title, req.person),
                      because=f"{circuit.title} checklist step ({src})", generator="rules:checklist", kind="checklist_step",
                      step_id=sid, template=f"step:{sid}")
        x.est_calls = est_calls(x)
        out.append(x)
        n += 1
        if "pension" in sid:
            x = XQuestion(id=f"person-q{n}", node_id="person", key=norm_key("outreach", "pension-file"),
                          text="Is there a Civil War pension file for him? (held at NARA, needs a request)",
                          because="Pension files are not online; only the index is", generator="rules:checklist", kind="outreach",
                          template="outreach:pension", plan=Plan(handler="stub", why_stub="NARA pension files are ordered, not searched."))
            out.append(x)
            n += 1
    return out


def _step_question(title: str, p: Person) -> str:
    t = title.rstrip(".")
    return t if t.endswith("?") else f"{t}: what is on record for {given(p) or p.full_name}?"


def node_as_question(node: XNode, q: Optional[XQuestion]) -> Question:
    """The rules brainstorm reads a node as an answered question with its citations."""
    plan = Plan(handler=(node.handler or "ia_fulltext") if (node.handler or "ia_fulltext") in CALLS else "ia_fulltext", query=node.query)
    return Question(id=node.id, key=f"node:{node.id}", round=node.depth, text=node.label, because=q.text if q else "",
                    template=q.template if q else "explore", plan=plan, status="answered" if node.citations or node.claims else "no_lead",
                    citations=node.citations, about=node.about, parent_id=node.parent_id or "root", depth=node.depth)


def node_finding(node: XNode) -> Finding:
    return Finding(step_id=node.id, step_title=node.label, stage=6, source_slug="explore", mode="live",
                   status="found" if (node.citations or node.claims) else "nothing", confidence="possible",
                   claims=node.claims, citations=node.citations, about=node.about)


def dummy_known(keys: list[str]) -> list[Question]:
    return [Question(id=f"k{i}", key=k, round=0, text="", because="", template="", plan=Plan(handler="stub")) for i, k in enumerate(keys)]


def nodes_from(finding: Finding, q: XQuestion, parent: XNode, start_no: int, limit: int = 6) -> list[XNode]:
    """Child nodes from what a pass returned: one per claim (documented when the claim is), then one per
    citation. Only returned records become nodes; nothing is inferred."""
    out: list[XNode] = []
    n = start_no
    for c in finding.claims[:limit]:
        out.append(XNode(id=f"n{n}", kind="fact", label=c.text[:140], summary=c.text, parent_id=parent.id, via_question=q.id,
                         tier=c.tier if c.tier in ("documented", "told") else "possible", citations=[c.citation], claims=[c],
                         depth=parent.depth + 1, about=finding.about, handler=q.plan.handler if q.plan else "", query=q.plan.query if q.plan else ""))
        n += 1
    claimed = {c.citation.url for c in finding.claims if c.citation.url}
    for cit in finding.citations:
        if len(out) >= limit:
            break
        if cit.url and cit.url in claimed:
            continue
        kind: NodeKind = "page" if (cit.item_id and "page" in (cit.title or "").lower()) else "book" if cit.item_id else \
            "newspaper" if "loc.gov" in (cit.url or "") else "wikidata" if "wikidata" in (cit.url or "") else "link"
        label = (cit.title or cit.url or "record")[:120]
        if cit.name_match == "surname_only":
            label += " (surname only)"
        out.append(XNode(id=f"n{n}", kind=kind, label=label, summary=(cit.snippet or "")[:600], parent_id=parent.id, via_question=q.id,
                         tier="possible", citations=[cit], depth=parent.depth + 1, about=finding.about,
                         handler=q.plan.handler if q.plan else "", query=q.plan.query if q.plan else ""))
        n += 1
    return out


def deeper(req: ResearchRequest, node: XNode, known: set[str], start_no: int) -> list[XQuestion]:
    """Dig Deeper: new angles on a node. Name variants, a wider date window, the place's own histories, the given
    name inside a book, adjacent sources. Keys are checked against everything already asked on the path."""
    p = req.person
    sname, gname = surname(p), given(p)
    town, state = town_state(p.birth_place or p.death_place)
    who = node.about or p.full_name
    lo = (p.birth_year or 1800) - 5
    hi = (p.death_year or (p.birth_year or 1800) + 90) + 5
    ideas: list[tuple[str, str, str, Plan]] = []
    for v in p.all_names()[1:4]:
        ideas.append((norm_key("deeper", "variant", v, node.id), f"Is the spelling \"{v}\" in any digitised book?",
                      f"Dig deeper on {node.label[:50]}: try another spelling", Plan(handler="ia_fulltext", query=f'"{v}"')))
    if gname and sname:
        ideas.append((norm_key("deeper", "initials", node.id), f"Do books print him as \"{gname[0]}. {sname}\"?",
                      "Dig deeper: old indexes often use initials", Plan(handler="ia_fulltext", query=f'"{gname[0]}. {sname}"' + (f' "{town}"' if town else ""))))
    ideas.append((norm_key("deeper", "news-wide", node.id), f"Did any newspaper print \"{gname} {sname}\" between {lo} and {hi}?",
                  "Dig deeper: a wider date window than the first newspaper search", Plan(handler="chronam", query=f"{gname} {sname}", years=(lo, hi))))
    if town:
        ideas.append((norm_key("deeper", "town-history", town), f"Which histories of {town} might name the {sname} family?",
                      f"Dig deeper: the place {town} has its own books", Plan(handler="ia_title", query=f'title:("{town}") AND title:(history OR genealogy OR families)')))
    if state:
        ideas.append((norm_key("deeper", "state-genealogy", sname, state), f"Is there a {sname} family genealogy that covers {state}?",
                      "Dig deeper: family genealogies collect every branch", Plan(handler="ia_title", query=f'title:("{sname}") AND title:(genealogy OR family OR descendants)')))
    for cit in node.citations:
        if cit.item_id:
            ideas.append((norm_key("deeper", "inside-given", cit.item_id), f"Does \"{(cit.title or cit.item_id)[:60]}\" print the given name {gname}?",
                          "Dig deeper: search inside the same book for the given name, not the surname",
                          Plan(handler="ia_inside", item_id=cit.item_id, query=gname)))
    if node.kind in ("newspaper", "page", "book", "link"):
        ideas.append((norm_key("deeper", "verify", node.id), f"Is \"{node.label[:60]}\" really the same {who.split()[0]} (age, place, dates)?",
                      "Dig deeper: a name match is a lead, not proof", Plan(handler="ia_fulltext", query=f'"{who}"' + (f' "{town}"' if town else ""))))
    out, n = [], start_no
    wk = norm_key("step", "wikidata_identity")
    if wk not in known and node.about is None:
        known.add(wk)
        x = XQuestion(id=f"{node.id}-q{n}", node_id=node.id, key=wk, text=f"Does Wikidata hold an item for {who} with matching years?",
                      because="Dig deeper: an adjacent source", generator="rules:dig-deeper", kind="checklist_step", step_id="wikidata_identity",
                      template="dig-deeper")
        x.est_calls = est_calls(x)
        out.append(x)
        n += 1
    for key, text, because, plan in ideas:
        if key in known:
            continue
        known.add(key)
        x = XQuestion(id=f"{node.id}-q{n}", node_id=node.id, key=key, text=text, because=because, generator="rules:dig-deeper",
                      kind="research", plan=plan, template="dig-deeper", about=node.about)
        x.est_calls = est_calls(x)
        out.append(x)
        n += 1
    return out


def user_question(cmd: AddCmd, node: XNode, req: ResearchRequest, no: int) -> XQuestion:
    who = node.about or req.person.full_name
    extra = [w for w in re.findall(r"\b[A-Z][a-z]{2,}\b", cmd.text) if w.lower() not in who.lower() and w not in ("Was", "Did", "Does", "Is", "What", "Where", "Which", "Who", "When", "How", "Why", "The")][:3]
    words = (cmd.query or " ".join([f'"{who}"', *extra])).strip()
    off = any(w in cmd.text.lower() for w in ("pension file", "write to", "letter to", "clerk", "probate court"))
    plan = Plan(handler="stub", why_stub="This needs an offline source; Lineage drafts a letter, nothing is sent.") if off else \
        Plan(handler="ia_fulltext", query=words)
    x = XQuestion(id=f"{node.id}-q{no}", node_id=node.id, key=norm_key("user", node.id, cmd.text), text=cmd.text.strip(),
                  because=cmd.because or ("You asked" if cmd.generator == "user" else "Suggested in chat"), generator=cmd.generator,
                  kind="outreach" if off else "research", plan=plan, template=f"{cmd.generator}-question", about=node.about)
    x.est_calls = est_calls(x)
    return x


def as_question(x: XQuestion, req: ResearchRequest, depth: int) -> Question:
    return Question(id=x.id, key=x.key, round=depth, text=x.text, because=x.because, template=x.template or "explore",
                    plan=x.plan or Plan(handler="ia_fulltext", query=f'"{req.person.full_name}"'), about=x.about, depth=depth,
                    mode="stub" if (x.plan and x.plan.handler == "stub") else "live")


def describe_search(x: XQuestion, req: ResearchRequest) -> str:
    """One line for the live activity log, e.g. Searching Chronicling America for 'Erastus Burnham' 1860 to 1870."""
    if x.kind == "checklist_step" and x.step_id in STEPS:
        return f"Running checklist step: {STEPS[x.step_id].title}"
    if x.plan is None:
        return f"Researching: {x.text}"
    names = {"ia_fulltext": "Internet Archive full text", "ia_title": "the Internet Archive catalog", "chronam": "Chronicling America",
             "ia_inside": f"inside {x.plan.item_id}", "wikidata": "Wikidata", "wikidata_kin": "Wikidata", "stub": "an offline source"}
    yrs = f" {x.plan.years[0]} to {x.plan.years[1]}" if x.plan.years else ""
    return f"Searching {names.get(x.plan.handler, x.plan.handler)} for '{x.plan.query}'{yrs}"


def generic_outreach(x: XQuestion, req: ResearchRequest) -> OutreachDraft:
    """Fallback letter when no specific holder is known. Names no address; the user finds it."""
    p = req.person
    town, state = town_state(p.birth_place or p.death_place)
    years = f"{p.birth_year or '?'} to {p.death_year or '?'}"
    to = f"Local historical society or town clerk, {town or 'the town where he lived'}{', ' + state if state else ''}"
    body = (f"Hello,\n\nI am researching my relative {p.full_name} ({years}). {x.text} "
            f"Could you tell me whether you hold anything that would answer this? So far the record shows: {x.because}.\n\n"
            "I am happy to pay any copying fee you charge; please tell me the amount before you send anything.\n\n"
            "Thank you,\n[Your name]\n[Your return address]")
    return OutreachDraft(id=f"req-{x.id}", node_id=x.node_id, to=to, channel="letter",
                         contact_hint="Use the institution's own website for its address. Nothing is sent from here.",
                         subject=f"Research request: {p.full_name} ({years})", body=body)
