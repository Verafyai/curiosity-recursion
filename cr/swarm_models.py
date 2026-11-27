"""Typed values that cross Temporal boundaries in the v0.2 swarm (CuriosityRecursionSwarmWorkflow)."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from cr.allocator import Allocator
from cr.leads import LeadTree
from cr.ledger import Decision, LedgerState, QuerySpec, RelativeRef
from cr.models import OutreachDraft, Person, ResearchRequest
from cr.outline import Lane, Outline
from cr.reflection import Lesson


class Ev(BaseModel):
    """One returned item, compact: what a lane saw and may cite. Snippets are short (<= 340 chars)."""
    cid: str
    lane: str
    tool: str
    key: str = Field(description="ia:<item>#<page>, a URL, or wd:<QID>")
    url: Optional[str] = None
    item_id: Optional[str] = None
    title: str = ""
    year: Optional[int] = None
    page: Optional[int] = None
    snippet: str = ""
    name_match: str = "none"
    in_life: bool = True
    section: str = ""


class ToolCall(BaseModel):
    run_id: str
    canonical_id: str
    seq: int = 0
    spec: QuerySpec
    person: Person


class ToolResult(BaseModel):
    canonical_id: str
    items: list[Ev] = Field(default_factory=list)
    n_items: int = 0
    n_matched: int = 0
    hit_pages: list[int] = Field(default_factory=list)
    book_hits: dict[str, list[int]] = Field(default_factory=dict, description="item id -> pages hit, from corpus-wide search")
    error: str = ""
    from_store: bool = False


class ReserveRequest(BaseModel):
    child_id: str
    req_no: int
    spec: QuerySpec


class ReserveReply(BaseModel):
    req_no: int
    decision: Decision
    budget_exhausted: bool = False
    seq: int = Field(default=0, description="Reservation number in this run; with the canonical id it is the tool call's idempotency key")
    suggestions: list[QuerySpec] = Field(default_factory=list)


class RecordSignal(BaseModel):
    child_id: str
    canonical_id: str
    n_items: int
    n_matched: int
    hit_pages: list[int] = Field(default_factory=list)
    book_hits: dict[str, list[int]] = Field(default_factory=dict)
    error: str = ""
    evidence_ids: list[str] = Field(default_factory=list)


class CallRecord(BaseModel):
    n: int = 0
    round: int
    lane: str
    viewpoint: str
    lead_id: str
    tool: str
    source: str
    terms: str
    canonical: str
    decision: str
    key_type: Optional[str] = None
    reason: str = ""
    name_form: Optional[str] = None
    is_variant: bool = False
    n_items: int = 0
    n_matched: int = 0
    hit_pages: list[int] = Field(default_factory=list)
    reward: float = 0.0
    error: str = ""
    section: str = ""
    purpose: str = ""
    grounding: str = ""


class LaneTask(BaseModel):
    run_id: str
    parent_id: str
    round: int
    lane: Lane
    sub_budget: int
    tree: LeadTree
    known_ids: list[str] = Field(default_factory=list)
    known_keys: list[str] = Field(default_factory=list, description="evidence keys already verified (reward is for new ones)")
    lessons: list[Lesson] = Field(default_factory=list)
    coverage: dict[str, str] = Field(default_factory=dict)
    yield_stats: dict[str, list[float]] = Field(default_factory=dict)
    relatives: list[RelativeRef] = Field(default_factory=list)
    request: ResearchRequest


class LaneResult(BaseModel):
    lane: str
    round: int
    tree: LeadTree
    calls: list[CallRecord] = Field(default_factory=list)
    evidence: list[Ev] = Field(default_factory=list)
    blocked: int = 0
    unspent: int = 0
    stop: str = ""


class MergeInput(BaseModel):
    person: Person
    new_evidence: list[Ev]
    known_keys: list[str]
    known_relatives: list[str] = Field(default_factory=list)


class MergeOutput(BaseModel):
    verified: list[Ev] = Field(default_factory=list)
    leads_only: list[Ev] = Field(default_factory=list)
    refuted: list[dict] = Field(default_factory=list)
    namesakes: list[dict] = Field(default_factory=list)
    relatives: list[RelativeRef] = Field(default_factory=list)
    support: dict[str, int] = Field(default_factory=dict)
    duplicates: int = 0


class ReflectInput(BaseModel):
    round: int
    calls: list[CallRecord]
    namesakes: list[dict]
    relatives: list[dict]
    known: list[str]


class SwarmState(BaseModel):
    """Everything carried across continue-as-new."""
    outline: Optional[Outline] = None
    ledger: Optional[LedgerState] = None
    tree: LeadTree = Field(default_factory=LeadTree)
    alloc: Allocator = Field(default_factory=Allocator)
    calls: list[CallRecord] = Field(default_factory=list)
    verified: list[Ev] = Field(default_factory=list)
    leads_only: list[Ev] = Field(default_factory=list)
    namesakes: list[dict] = Field(default_factory=list)
    relatives: list[RelativeRef] = Field(default_factory=list)
    lessons: list[Lesson] = Field(default_factory=list)
    drafts: list[OutreachDraft] = Field(default_factory=list)
    support: dict[str, int] = Field(default_factory=dict)
    round: int = 0
    reserved: int = 0
    blocked: int = 0
    continued: int = 0
    stop_reason: str = ""
    log: list[str] = Field(default_factory=list)
    lane_failures: list[str] = Field(default_factory=list)


class SwarmInput(BaseModel):
    request: ResearchRequest
    state: Optional[SwarmState] = None
