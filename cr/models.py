"""Typed schemas for every value that crosses a Temporal boundary.

Workflow input, activity inputs and outputs, signals, the progress query and
the final report are all Pydantic models. The worker and every client use
temporalio.contrib.pydantic.pydantic_data_converter, so Temporal stores them
as typed JSON in event history and the Web UI shows real field names.

Curiosity Recursion (CR) names used in the paper map onto these models: a subject s is a
`Person`; the evidence state R is the list of `Finding`s; a question-graph node v is a
`Question` (text, parent, the finding that sparked it in `because` and `parent_finding`, a
`Plan`, status, depth); the question memory M is the SQLite store in cr/memory.py.

Shapes follow kin (rexsaurus/kin):
- Person / ResearchRequest mirror lib/search/form.ts SearchInput
  (fullName, birthYear + precision, bornPlace, deathYear, notes).
- Claim mirrors lib/content/validate.ts Fact (field, text, tier, citation, url).
- Sentence / Block mirror the validator's Sentence { text, claimIds }.
- CardState mirrors lib/content/studio.ts cardState() and THRESHOLD.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

YearPrecision = Literal["exact", "about", "before", "after"]
CircuitId = str  # any circuit id defined in cr/circuits/*.yaml
TemplateId = Literal["service-record", "the-crossing", "book-of-daniel"]
StudioKind = Literal["chapter", "newsletter"]
Mode = Literal["live", "stub"]
Tier = Literal["documented", "told", "lore", "possible", "inferred"]
"""possible: a lead from a snippet or name match, never published. inferred: reasoning only, never published."""
PUBLISHABLE_TIERS = ("documented", "told", "lore")
Confidence = Literal["documented", "possible", "candidate", "none"]
FindingStatus = Literal["found", "candidates", "nothing", "skipped", "error"]
RunStatus = Literal[
    "starting",
    "blocked_living",
    "researching",
    "checklist",
    "brainstorming",
    "waiting_next_level",
    "writing",
    "awaiting_approval",
    "approved",
    "rejected",
    "failed",
]


class Person(BaseModel):
    full_name: str
    name_variants: list[str] = Field(default_factory=list)
    birth_year: Optional[int] = None
    birth_year_precision: YearPrecision = "exact"
    birth_place: Optional[str] = None
    death_year: Optional[int] = None
    death_year_precision: YearPrecision = "exact"
    death_place: Optional[str] = None
    death_on_record: bool = Field(
        default=False,
        description="Gate attestation: a death is on record but its date is withheld from the agent (corpus eval).",
    )
    family_notes: Optional[str] = Field(
        default=None,
        description="What the family says. Becomes 'told' tier, never 'documented'.",
    )

    def all_names(self) -> list[str]:
        seen: list[str] = []
        for n in [self.full_name, *self.name_variants]:
            n = n.strip()
            if n and n.lower() not in [s.lower() for s in seen]:
                seen.append(n)
        return seen


class ResearchRequest(BaseModel):
    person: Person
    question: str = ""
    circuit_id: CircuitId = "civil_war_veteran"
    template: Optional[TemplateId] = Field(
        default=None, description="Studio template. Defaults from the circuit."
    )
    output_kind: StudioKind = "chapter"
    mode: Literal["brainstorm", "checklist"] = "brainstorm"
    depth: int = Field(default=2, ge=1, le=4, description="Follow-up levels under each first question")
    breadth: int = Field(default=3, ge=1, le=8, description="Brainstorm questions per node")
    max_nodes: int = Field(default=30, ge=1, le=400, description="Total question nodes in the graph")
    max_run_minutes: int = Field(default=20, ge=1, le=60 * 24 * 30, description="Stop brainstorming after this long")
    level_pause_seconds: int = Field(default=3, ge=0, description="Durable timer between graph levels")
    outreach: Literal["ask_first", "automate"] = Field(
        default="ask_first",
        description="Only ask_first works in this build. 'automate' is accepted but still holds every request for approval; nothing is ever sent.",
    )
    simulate_flaky_archives: bool = Field(default=True, description="Fail some investigations on early attempts so retries show")
    require_approval: bool = True
    approval_timeout_hours: int = 72
    # ---- Curiosity Recursion switches (defaults = the full system; the benchmark ablates them)
    generator: Literal["rules", "llm", "hybrid", "rules2"] = Field(default="rules", description="Question generator g (rules2: post hoc fixed rules, see cr/generators/rules.py)")
    use_memory: bool = Field(default=True, description="Re-ask and dedupe against questions earlier runs asked (memory M)")
    use_circuits: bool = Field(default=True, description="Run the circuit checklist as level 0")
    verify_nodes: bool = Field(default=True, description="Spawn 'Are you sure?' verification questions")
    dedupe: bool = Field(default=True, description="Drop candidates whose canonical key was already asked")
    use_fixtures: bool = Field(default=True, description="STUB steps read eval fixtures. Always False in the benchmark: fixtures hold ground truth.")
    use_catalog: bool = Field(default=False, description="Load the optional public source catalog (CR_CATALOG_URL)")
    max_tool_calls: Optional[int] = Field(default=None, ge=1, description="Budget B: checklist steps plus investigations. None = no cap.")
    llm_token_budget: int = Field(default=200_000, ge=0, description="Hard stop for the LLM generator, input plus output tokens per run")


class Citation(BaseModel):
    title: str
    url: Optional[str] = None
    archive: Optional[str] = None
    item_id: Optional[str] = Field(default=None, description="Internet Archive identifier, when the citation is a book")
    year: Optional[int] = None
    snippet: Optional[str] = Field(default=None, description="Matched text, **marked**, verbatim from the source")
    name_match: Optional[Literal["strong", "surname_only", "none"]] = None


class Claim(BaseModel):
    id: str
    field: str = Field(description="birth, death, marriage, military, burial, residence, ...")
    text: str
    tier: Tier
    year: Optional[int] = None
    citation: Citation
    origin: str = Field(description="Where this claim came from, e.g. fixture:burnham-erastus.json#b05")


class Lead(BaseModel):
    """A possible claim: an OCR or search-snippet match. Shown with its quote, never written into the text."""
    id: str
    field: str = Field(description="parents, birth, death, mention")
    text: str
    tier: Literal["possible"] = "possible"
    value: str = Field(default="", description="Normalised value used to compare leads, e.g. 'phineas|abigail'")
    year: Optional[int] = None
    quote: str = Field(description="Verbatim from the source, the raw citation")
    span: str = Field(default="", description="The exact matched words inside the quote")
    citation: Citation
    source_id: str = Field(description="ia:<identifier> for a book, otherwise the url")
    confidence: Literal["candidate", "weak"] = "candidate"
    matched_by: str = Field(description="How it was matched, in words")
    question_id: str = Field(description="Graph node or checklist step that found it")


class Conflict(BaseModel):
    """Two claims or leads that disagree. Both stay; the disagreement is named, never resolved."""
    id: str
    field: str
    label: str
    claim_ids: list[str]
    note: str = ""


class Finding(BaseModel):
    step_id: str
    step_title: str
    stage: int = Field(ge=1, le=7, description="kin run-pass STAGE_LABELS index")
    source_slug: str = Field(description="Source catalog slug, or 'none' when not in a catalog")
    mode: Mode
    status: FindingStatus
    confidence: Confidence
    claims: list[Claim] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    notes: str = ""
    endpoint: Optional[str] = None
    about: Optional[str] = Field(default=None, description="Whose record this is, when not the subject (e.g. a parent)")
    attempt: int = 1
    checked_at: Optional[datetime] = None
    round: int = 1


class StepSpec(BaseModel):
    id: str
    title: str
    stage: int
    source_slug: str
    mode: Mode
    handler: str
    topic: str
    fixture_fields: list[str] = Field(default_factory=list)
    query: str = ""
    why_stub: str = ""
    flaky: bool = False


class StepInput(BaseModel):
    request: ResearchRequest
    step: StepSpec
    round: int = 1
    focus: Optional[str] = None


class StepOutput(BaseModel):
    findings: list[Finding]


class PassInput(BaseModel):
    request: ResearchRequest
    steps: list[StepSpec]
    round: int = 1


class PassResult(BaseModel):
    round: int
    findings: list[Finding]


QuestionStatus = Literal["pending", "running", "answered", "no_lead", "stub", "error", "skipped"]


class Plan(BaseModel):
    """How to try a question. `handler` is a live client or 'stub'."""
    handler: Literal["ia_fulltext", "ia_inside", "ia_title", "chronam", "wikidata", "wikidata_kin", "stub"]
    query: str = ""
    item_id: Optional[str] = None
    years: Optional[tuple[int, int]] = None
    why_stub: str = ""


class Question(BaseModel):
    """One brainstormed follow-up: 'he was on a ship, which ships?'"""
    id: str
    key: str = Field(description="Normalised dedupe key")
    round: int
    text: str
    because: str = Field(description="The finding that sparked it, quoted")
    template: str = Field(description="Lead template id, e.g. unit->books, book->inside, snippet->parents")
    parent_finding: Optional[str] = Field(default=None, description="claim id, citation url or question id")
    parent_question: Optional[str] = None
    about: Optional[str] = Field(default=None, description="Person the question is about, when not the subject")
    score: float = 0
    plan: Plan
    status: QuestionStatus = "pending"
    mode: Mode = "live"
    answer: str = ""
    citations: list[Citation] = Field(default_factory=list)
    snippets: list[str] = Field(default_factory=list)
    # graph node fields
    parent_id: str = Field(default="root", description="Parent node id; 'root' is the person")
    depth: int = 1
    attempts: int = 0
    failures: list[str] = Field(default_factory=list, description="Activity failures before success, verbatim")
    seeded_from: Optional[str] = Field(default=None, description="Workflow id of the earlier run this question was reused from")
    outreach_id: Optional[str] = None
    finished_at: Optional[datetime] = None


class BrainstormInput(BaseModel):
    request: ResearchRequest
    llm_tokens_used: int = 0
    findings: list[Finding]
    questions: list[Question] = Field(description="Every question asked so far (dedupe)")
    round: int
    top_n: int
    node: Optional[Question] = Field(default=None, description="Brainstorm follow-ups for this node; None = the root")
    depth: int = 1


class BrainstormOutput(BaseModel):
    round: int
    generated: int
    duplicates_skipped: int
    ungrounded_rejected: int = Field(default=0, description="Candidates dropped for naming no spark finding")
    llm_tokens: int = 0
    picked: list[Question]
    held_back: list[Question] = Field(default_factory=list)


class InvestigateInput(BaseModel):
    request: ResearchRequest
    question: Question


class OutreachDraft(BaseModel):
    """A research request letter. Never sent by this app."""
    id: str
    node_id: str
    to: str = Field(description="Institution name; no address is invented")
    channel: Literal["letter", "email", "web_form"] = "letter"
    contact_hint: str = Field(default="", description="Where to find the real address, e.g. the catalog homepage")
    subject: str
    body: str
    status: Literal["awaiting_approval", "approved", "declined", "fulfilled", "not_held"] = "awaiting_approval"
    exported_to: Optional[str] = None
    reply: Optional[str] = Field(default=None, description="The archive's reply, verbatim, when one arrives")


class InvestigateOutput(BaseModel):
    question: Question
    finding: Finding
    outreach: Optional[OutreachDraft] = None


class LevelInput(BaseModel):
    request: ResearchRequest
    nodes: list[Question]
    known: list[Question] = Field(description="All questions so far, for dedupe")
    level: int
    catalog_homepages: dict[str, str] = Field(default_factory=dict)


class LevelOutput(BaseModel):
    level: int
    results: list[InvestigateOutput]
    followups: list[Question]
    generated: int
    duplicates_skipped: int


class PriorInput(BaseModel):
    person_key: str
    circuit_id: str


class PriorQuestions(BaseModel):
    questions: list[Question]
    runs: list[str]


class PersistInput(BaseModel):
    workflow_id: str
    person_key: str
    person: Person
    circuit_id: str
    questions: list[Question]
    outreach: list["OutreachDraft"] = Field(default_factory=list)
    status: str


class ArchiveReply(BaseModel):
    """A reply to an approved request, pasted in by a person or sent by a simulated archive."""
    draft_id: str
    outcome: Literal["record", "no_record"]
    text: str = Field(description="The reply, verbatim")
    record_title: Optional[str] = None
    record_url: Optional[str] = None


class OutreachDecision(BaseModel):
    draft_id: str
    approve: bool


class Gap(BaseModel):
    topic: str
    label: str
    state: Literal["covered", "leads_only", "missing"]
    asked: bool = Field(description="The research question asks about this topic")
    evidence: str = ""


class Round(BaseModel):
    number: int
    kind: Literal["checklist", "brainstorm", "reviewer"]
    started_at: datetime
    finished_at: Optional[datetime] = None
    question_ids: list[str] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)
    generated: int = 0
    duplicates_skipped: int = 0
    ungrounded_rejected: int = 0
    new_citations: int = 0
    answered: int = 0
    verdict: str = Field(default="", description="'keep digging: ...' or 'stop: ...'")
    paused_seconds: int = 0


class GateResult(BaseModel):
    allowed: bool
    rule: str
    reason: str


class CatalogSource(BaseModel):
    slug: str
    name: Optional[str] = None
    access_method: Optional[str] = None
    status: Optional[str] = None
    record_types: list[str] = Field(default_factory=list)


class CatalogSnapshot(BaseModel):
    endpoint: str
    source_count: int
    sources: list[CatalogSource]
    taxonomy_version: Optional[str] = None
    wars: list[str] = Field(default_factory=list)


class Sentence(BaseModel):
    text: str
    claim_ids: list[str]


class Section(BaseModel):
    heading: str
    sentences: list[Sentence] = Field(default_factory=list)
    empty_line: Optional[str] = None


class Dropped(BaseModel):
    text: str
    reason: str


class CardState(BaseModel):
    kind: Literal["chapter", "newsletter", "documentary"]
    state: Literal["ready", "thin", "soon"]
    have: int = 0
    need: int = 0
    price_credits: int


class Stats(BaseModel):
    used: int
    footnoted: int
    uncited: int


class ComposeInput(BaseModel):
    request: ResearchRequest
    gate: GateResult
    catalog: Optional[CatalogSnapshot]
    findings: list[Finding]
    questions: list[Question] = Field(default_factory=list)
    rounds: list[Round] = Field(default_factory=list)
    questions: list[Question] = Field(default_factory=list)
    stop_reason: str = ""
    reviewer_notes: list[str] = Field(default_factory=list)


class StudioReport(BaseModel):
    workflow_id: str = ""
    subject: Person
    question: str
    circuit_id: str
    template: str
    output_kind: str
    gate: GateResult
    title: str
    lead: str
    sections: list[Section] = Field(default_factory=list)
    facts: list[Claim] = Field(default_factory=list)
    told: list[Claim] = Field(default_factory=list)
    candidates: list[Finding] = Field(default_factory=list)
    leads: list[Lead] = Field(default_factory=list, description="Possible claims, with quotes. Never in the text.")
    conflicts: list[Conflict] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    deeper: list[str] = Field(default_factory=list)
    dropped: list[Dropped] = Field(default_factory=list)
    stats: Stats = Stats(used=0, footnoted=0, uncited=0)
    cards: list[CardState] = Field(default_factory=list)
    live_steps: list[str] = Field(default_factory=list)
    stub_steps: list[str] = Field(default_factory=list)
    rounds: list[Round] = Field(default_factory=list)
    questions: list[Question] = Field(default_factory=list)
    outreach: list[OutreachDraft] = Field(default_factory=list)
    checklist: list[Gap] = Field(default_factory=list)
    stop_reason: str = ""
    reviewer_notes: list[str] = Field(default_factory=list)
    decision: Literal["pending", "approved", "rejected", "blocked", "not_required"] = "pending"
    decision_note: str = ""
    markdown: str = ""


class Decision(BaseModel):
    approve: bool
    note: str = ""
    by: str = "reviewer"


class Redirect(BaseModel):
    """A reviewer's own 'look over here'. Becomes a question in the next round."""
    question: str = Field(description="e.g. 'Check the church records in Holyoke'")
    query: str = Field(default="", description="Search words; defaults to the question text")


class Progress(BaseModel):
    workflow_id: str = ""
    request: Optional[ResearchRequest] = None
    started_at: Optional[datetime] = None
    status: RunStatus
    stage: int = 0
    stage_label: str = ""
    current_step: Optional[str] = None
    steps_total: int = 0
    steps_done: list[str] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    gate: Optional[GateResult] = None
    round: int = 0
    rounds: list[Round] = Field(default_factory=list)
    next_round_at: Optional[datetime] = None
    questions: list[Question] = Field(default_factory=list)
    outreach: list[OutreachDraft] = Field(default_factory=list)
    seeded: int = 0
    stop_reason: str = ""
    levels: list[Round] = Field(default_factory=list)
    reviewer_notes: list[str] = Field(default_factory=list)
    redirects: list[Redirect] = Field(default_factory=list)
    report: Optional[StudioReport] = None
    tool_calls: int = Field(default=0, description="Checklist steps plus investigations started (budget B)")
    llm_tokens: int = 0
    log: list[str] = Field(default_factory=list)


def grounded(q: "Question") -> bool:
    """The grounding constraint: a question must name the finding, node or checklist gap that sparked it."""
    if q.template == "reviewer->look-here":
        return True  # a human asked; the human is the spark
    return bool((q.parent_finding or q.parent_question) and q.because.strip())
