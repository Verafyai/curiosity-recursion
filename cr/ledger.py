"""Search ledger with smart re-query (spec section 3). Pure and deterministic: no I/O, no clock.

Sources: tabu search with aspiration criteria (Glover and Laguna 1997, `glover1997tabu`): a move
already made is tabu unless it brings something new; Go-Explore (`ecoffet2021goexplore`): return to a
promising state, then explore from it; query rewriting (`ma2023rewrite`, `wang2023query2doc`);
record-linkage name handling (`christen2012datamatching`).

Every tool call is a `QuerySpec`. `canonicalize()` maps it to a `canonical_id`. The ledger:
  1. blocks an exact repeat (same canonical id) without calling the tool or charging the budget;
  2. treats a near repeat (same tool and source, term Jaccard >= 0.8, overlapping windows) as a repeat;
  3. allows a revisit of a known source only with a new key: name_variant, adjacent_pages,
     relative_name (only after the living-person gate), different_collection, date_window, result_offset;
  4. logs every revisit with a deterministic one-sentence reason;
  5. suggests up to 3 allowed rewrites for a blocked call ("repeat itself more cleverly");
  6. closes a source after k = 3 consecutive empty or non-matching calls (foraging stop).
The orchestrator workflow owns one Ledger and is its only writer.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Literal, Optional

from pydantic import BaseModel, Field

from cr.gate import is_presumed_living
from cr.models import Person
from cr.novelty import STOP

KEY_TYPES = ("adjacent_pages", "relative_name", "name_variant", "different_collection", "date_window", "result_offset")
NOVELTY_BY_KEY = {"adjacent_pages": 0.8, "relative_name": 0.7, "different_collection": 0.6, "name_variant": 0.5, "date_window": 0.5,
                  "result_offset": 0.4}
PAGE_WINDOW = 10
MAX_HOPS = 3
K_EMPTY = 3
NEAR_JACCARD = 0.8
FTS_COLLECTIONS = ("americana", "allen_county", "library_of_congress", "toronto", "cdl")
BOOK_TOOLS = ("ia_inside", "ia_inside_pages")


class RelativeRef(BaseModel):
    name: str
    relation: Literal["parent", "spouse", "child", "sibling"]
    birth_year: Optional[int] = None
    birth_year_precision: Literal["exact", "about", "before", "after"] = "exact"
    death_year: Optional[int] = None
    source: str = Field(default="", description="canonical id or URL of the verified evidence that named this relative")


class QuerySpec(BaseModel):
    tool: str = Field(description="ia_fts | ia_fulltext | ia_inside | ia_inside_pages | ia_title | chronam | wikidata_search | wikidata_entities | stub")
    collection_or_item: Optional[str] = None
    terms: str = ""
    date_window: Optional[tuple[int, int]] = None
    page_window: Optional[tuple[int, int]] = None
    offset: int = 0
    person_ref: str = "subject"
    name_form: Optional[str] = Field(default=None, description="The name form the terms use, for the name_variant key")
    relative: Optional[RelativeRef] = None
    lane: str = ""
    section: str = Field(default="", description="Outline section the call serves (birth, marriage, service, ...)")
    purpose: str = Field(default="", description="The question this call serves, in words")
    grounding: str = Field(default="", description="The quoted finding or outline cell that justifies the call")
    key_hint: Optional[str] = Field(default=None, description="The key the proposer thinks it adds; the rule engine decides (not part of the id)")


class Decision(BaseModel):
    decision: Literal["new", "revisit", "blocked_repeat", "blocked_near", "blocked_no_key", "blocked_closed", "refused_living", "unchecked"]
    canonical_id: str
    key_type: Optional[str] = None
    key_value: Optional[str] = None
    prior_canonical_ids: list[str] = Field(default_factory=list)
    reason: str = ""

    @property
    def allowed(self) -> bool:
        return self.decision in ("new", "revisit", "unchecked")


class Entry(BaseModel):
    canonical_id: str
    spec: QuerySpec
    source: str
    terms_set: list[str]
    decision: str
    key_type: Optional[str] = None
    reserved_by: str = ""
    done: bool = False
    n_items: int = 0
    n_matched: int = 0
    hit_pages: list[int] = Field(default_factory=list)
    error: str = ""
    evidence_ids: list[str] = Field(default_factory=list)


class SourceState(BaseModel):
    entries: list[str] = Field(default_factory=list)
    name_forms: list[str] = Field(default_factory=list)
    page_windows: list[tuple[int, int]] = Field(default_factory=list)
    date_windows: list[tuple[int, int]] = Field(default_factory=list)
    relatives: list[str] = Field(default_factory=list)
    hit_pages: list[int] = Field(default_factory=list)
    consecutive_empty: int = 0
    closed: bool = False


class LedgerState(BaseModel):
    enabled: bool = True
    life_window: tuple[int, int] = (0, 9999)
    current_year: int = 2026
    entries: dict[str, Entry] = Field(default_factory=dict)
    sources: dict[str, SourceState] = Field(default_factory=dict)
    log: list[dict] = Field(default_factory=list)
    blocked: int = 0
    revisits: dict[str, int] = Field(default_factory=dict)


# ------------------------------------------------------------------ canonical form

_QUOTE = re.compile(r'"([^"]*)"')


def _norm_text(t: str) -> str:
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode().lower()
    t = re.sub(r"\bsaint\b|\bst\b\.?", " st ", t)
    t = re.sub(r"[^a-z0-9\" ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def canonical_terms(terms: str) -> list[str]:
    """Lowercase, accents stripped, punctuation dropped except phrase quotes, stopwords dropped,
    unquoted terms sorted, quoted phrases kept as single tokens in order (first, after the sorted terms)."""
    t = _norm_text(terms)
    phrases = [" ".join(w for w in p.split()) for p in _QUOTE.findall(t)]
    rest = _QUOTE.sub(" ", t).replace('"', " ")
    words = sorted({w for w in rest.split() if w not in STOP})
    return [f'"{p}"' for p in phrases if p] + words


def _term_set(terms: list[str]) -> set[str]:
    out = set()
    for t in terms:
        out |= set(t.strip('"').split()) - STOP
    return out


def canonical_id(spec: QuerySpec) -> str:
    dw = [int(spec.date_window[0]), int(spec.date_window[1])] if spec.date_window else None
    pw = [int(spec.page_window[0]), int(spec.page_window[1])] if spec.page_window else None
    coll = spec.collection_or_item.strip().lower() if spec.collection_or_item else None
    body = json.dumps([spec.tool, coll, canonical_terms(spec.terms), dw, pw, int(spec.offset)], separators=(",", ":"))
    return hashlib.sha256(body.encode()).hexdigest()[:16]


def source_of(spec: QuerySpec) -> str:
    fam = "ia_book" if spec.tool in BOOK_TOOLS else spec.tool
    return f"{fam}:{(spec.collection_or_item or '*').lower()}"


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else (1.0 if not a and not b else 0.0)


def _overlap(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return not (a[1] < b[0] or b[1] < a[0])


def _name_key(name: str) -> str:
    return " ".join(_norm_text(name).replace('"', "").split())


# ------------------------------------------------------------------ the ledger

class Ledger:
    """Wraps a LedgerState (plain data, safe to carry across continue-as-new)."""

    def __init__(self, state: LedgerState | None = None, enabled: bool = True, life_window: tuple[int, int] = (0, 9999),
                 current_year: int = 2026):
        self.s = state or LedgerState(enabled=enabled, life_window=life_window, current_year=current_year)

    # ---- queries
    def _priors(self, spec: QuerySpec, cid: str) -> list[Entry]:
        if spec.collection_or_item:
            src = self.s.sources.get(source_of(spec))
            return [self.s.entries[i] for i in (src.entries if src else []) if i != cid]
        ts = _term_set(canonical_terms(spec.terms))
        return [e for e in self.s.entries.values() if e.spec.tool == spec.tool and not e.spec.collection_or_item
                and e.canonical_id != cid and jaccard(ts, set(e.terms_set)) >= NEAR_JACCARD]

    def classify(self, spec: QuerySpec) -> Decision:
        cid = canonical_id(spec)
        if not self.s.enabled:
            return Decision(decision="unchecked", canonical_id=cid, reason="ledger rules off (B6-no-ledger): call logged, not checked")
        if cid in self.s.entries:
            return Decision(decision="blocked_repeat", canonical_id=cid, prior_canonical_ids=[cid],
                            reason=f"exact repeat of {cid}: {spec.tool} {spec.terms[:60]}")
        src = self.s.sources.get(source_of(spec))
        priors = self._priors(spec, cid)
        if spec.relative is not None:
            rp = Person(full_name=spec.relative.name, birth_year=spec.relative.birth_year,
                        birth_year_precision=spec.relative.birth_year_precision, death_year=spec.relative.death_year)
            if is_presumed_living(rp, self.s.current_year):
                return Decision(decision="refused_living", canonical_id=cid, key_type="relative_name", key_value=spec.relative.name,
                                reason=f"relative {spec.relative.name} ({spec.relative.relation}) is presumed living: no death on record and no birth 110+ years ago, so the name is not used as a key")
        if src is not None and src.closed and spec.collection_or_item:
            rel_new = spec.relative is not None and _name_key(spec.relative.name) not in src.relatives
            if not rel_new:
                return Decision(decision="blocked_closed", canonical_id=cid, prior_canonical_ids=list(src.entries[-K_EMPTY:]),
                                reason=f"source {source_of(spec)} closed after {K_EMPTY} empty calls (foraging stop)")
        if not priors:
            same = [e for e in self.s.entries.values() if e.terms_set and canonical_terms(e.spec.terms) == canonical_terms(spec.terms)
                    and source_of(e.spec) != source_of(spec)]
            if same:
                where = spec.collection_or_item or spec.tool
                return Decision(decision="revisit", canonical_id=cid, key_type="different_collection", key_value=where,
                                prior_canonical_ids=[e.canonical_id for e in same][:5],
                                reason=f"same terms in a different collection or tool ({where}) after {len(same)} earlier call(s) elsewhere")
            return Decision(decision="new", canonical_id=cid, reason="new query and source")
        key = self._new_key(spec, priors, src)
        if key:
            kt, kv, why = key
            return Decision(decision="revisit", canonical_id=cid, key_type=kt, key_value=kv,
                            prior_canonical_ids=[e.canonical_id for e in priors][-8:], reason=why)
        near = any(jaccard(_term_set(canonical_terms(spec.terms)), set(e.terms_set)) >= NEAR_JACCARD
                   and _overlap(spec.date_window, e.spec.date_window) and _overlap(spec.page_window, e.spec.page_window) for e in priors)
        return Decision(decision="blocked_near" if near else "blocked_no_key", canonical_id=cid,
                        prior_canonical_ids=[e.canonical_id for e in priors][-8:],
                        reason=("near repeat" if near else "revisit without a new key") + f" of {source_of(spec)} ({len(priors)} earlier call(s))")

    def _new_key(self, spec: QuerySpec, priors: list[Entry], src: SourceState | None):
        lo, hi = self.s.life_window
        # adjacent pages: Go-Explore, return to a page window next to a hit
        if spec.page_window and src is not None and src.hit_pages:
            a, b = spec.page_window
            if not any(_overlap(spec.page_window, w) for w in src.page_windows):
                for h in sorted(src.hit_pages):
                    dist = a - h if a > h else (h - b if b < h else 0)
                    if 0 < dist <= PAGE_WINDOW * MAX_HOPS:
                        return ("adjacent_pages", f"{a}-{b}", f"adjacent pages {a}-{b} after hit on page {h} in {spec.collection_or_item}")
        # relative name (gate already passed in classify)
        if spec.relative is not None:
            rk = _name_key(spec.relative.name)
            if src is None or rk not in src.relatives:
                return ("relative_name", spec.relative.name,
                        f"relative name {spec.relative.name} ({spec.relative.relation}) from verified evidence, not yet used on {source_of(spec)}")
        # name variant
        if spec.name_form:
            nk = _name_key(spec.name_form)
            used = set(src.name_forms) if src else set()
            if not src:
                used = {_name_key(e.spec.name_form) for e in priors if e.spec.name_form}
            if nk not in used:
                return ("name_variant", spec.name_form, f"name variant '{spec.name_form}' not yet used on {source_of(spec)}")
        # date window
        if spec.date_window:
            a, b = spec.date_window
            prior_w = [e.spec.date_window for e in priors if e.spec.date_window]
            if lo <= a and b <= hi + 5 and not any(_overlap(spec.date_window, w) for w in prior_w):
                return ("date_window", f"{a}-{b}", f"non-overlapping date window {a}-{b} inside the life window {lo}-{hi}")
        # result offset: next page of results after a page that matched the person
        if spec.offset > 0:
            same = [e for e in priors if canonical_terms(e.spec.terms) == canonical_terms(spec.terms) and e.spec.date_window == spec.date_window]
            if same and spec.offset > max(e.spec.offset for e in same):
                last = max(same, key=lambda e: e.spec.offset)
                if last.done and last.n_matched > 0:
                    return ("result_offset", str(spec.offset), f"next result page from offset {spec.offset} after {last.n_matched} matching hit(s) at offset {last.spec.offset}")
        return None

    # ---- writes (single writer: the orchestrator)
    def reserve(self, spec: QuerySpec, requested_by: str) -> Decision:
        d = self.classify(spec)
        rec = {"decision": d.decision, "canonical_id": d.canonical_id, "requested_by": requested_by, "tool": spec.tool,
               "source": source_of(spec), "terms": spec.terms[:120], "lane": spec.lane}
        if d.decision == "revisit":
            rec.update(key_type=d.key_type, key_value=d.key_value, prior_canonical_ids=d.prior_canonical_ids, reason=d.reason)
            self.s.revisits[d.key_type or "?"] = self.s.revisits.get(d.key_type or "?", 0) + 1
        elif not d.allowed:
            rec["reason"] = d.reason
            self.s.blocked += 1
        self.s.log.append(rec)
        if not d.allowed:
            return d
        if d.canonical_id in self.s.entries:  # unchecked mode: a true repeat, still logged and charged
            return d
        e = Entry(canonical_id=d.canonical_id, spec=spec, source=source_of(spec), terms_set=sorted(_term_set(canonical_terms(spec.terms))),
                  decision=d.decision, key_type=d.key_type, reserved_by=requested_by)
        self.s.entries[d.canonical_id] = e
        st = self.s.sources.setdefault(e.source, SourceState())
        st.entries.append(d.canonical_id)
        if spec.name_form:
            st.name_forms.append(_name_key(spec.name_form))
        if spec.page_window:
            st.page_windows.append(tuple(spec.page_window))
        if spec.date_window:
            st.date_windows.append(tuple(spec.date_window))
        if spec.relative is not None:
            st.relatives.append(_name_key(spec.relative.name))
        return d

    def record(self, cid: str, n_items: int, n_matched: int, hit_pages: list[int] | None = None, error: str = "",
               evidence_ids: list[str] | None = None) -> None:
        e = self.s.entries.get(cid)
        if e is None:
            return
        e.done, e.n_items, e.n_matched, e.error = True, n_items, n_matched, error[:200]
        e.hit_pages = list(hit_pages or [])
        e.evidence_ids = list(evidence_ids or [])
        st = self.s.sources.setdefault(e.source, SourceState())
        st.hit_pages = sorted(set(st.hit_pages) | set(e.hit_pages))
        if n_matched > 0:
            st.consecutive_empty = 0
        else:
            st.consecutive_empty += 1
            if st.consecutive_empty >= K_EMPTY and self.s.enabled and e.spec.collection_or_item:
                st.closed = True
        self.s.log.append({"decision": "recorded", "canonical_id": cid, "n_items": n_items, "n_matched": n_matched,
                           "hit_pages": e.hit_pages[:10], "error": e.error, "source": e.source})

    def note_hits(self, source: str, pages: list[int]) -> None:
        """Hit pages seen for a book through a corpus-wide search (FTS returns the page of each hit)."""
        if not pages:
            return
        st = self.s.sources.setdefault(source, SourceState())
        st.hit_pages = sorted(set(st.hit_pages) | {int(p) for p in pages})

    def reopen_for_relative(self, source: str) -> None:
        st = self.s.sources.get(source)
        if st:
            st.closed, st.consecutive_empty = False, 0

    # ---- rewrite instead of drop
    def suggest(self, spec: QuerySpec, subject: Person, relatives: list[RelativeRef] | None = None, n: int = 3) -> list[tuple[QuerySpec, Decision]]:
        from cr.variants import variants
        cands: list[QuerySpec] = []
        src = self.s.sources.get(source_of(spec))
        base_name = spec.name_form or subject.full_name
        for v in variants(subject.full_name):
            if spec.name_form and base_name in spec.terms:
                cands.append(spec.model_copy(update={"terms": spec.terms.replace(base_name, v), "name_form": v, "offset": 0}))
            elif spec.tool in BOOK_TOOLS:
                cands.append(spec.model_copy(update={"terms": v, "name_form": v, "page_window": None, "tool": "ia_inside"}))
        if spec.collection_or_item and spec.tool in BOOK_TOOLS and src is not None:
            for h in src.hit_pages[:4]:
                for hop in range(1, MAX_HOPS + 1):
                    a = h + 1 + (hop - 1) * PAGE_WINDOW
                    cands.append(spec.model_copy(update={"tool": "ia_inside_pages", "page_window": (a, a + PAGE_WINDOW - 1),
                                                          "terms": spec.terms if spec.terms else subject.full_name.split()[-1]}))
        if spec.tool in ("ia_fts", "ia_fulltext"):
            cands.append(spec.model_copy(update={"offset": spec.offset + 10}))
            if spec.tool == "ia_fts" and not spec.collection_or_item:
                for c in FTS_COLLECTIONS:
                    cands.append(spec.model_copy(update={"collection_or_item": c, "offset": 0}))
        if spec.tool == "chronam":
            lo, hi = self.s.life_window
            for a in range(lo - lo % 10, min(hi, 1963) + 1, 10):
                cands.append(spec.model_copy(update={"date_window": (max(a, lo), min(a + 9, hi))}))
        for r in relatives or []:
            cands.append(spec.model_copy(update={"terms": f'"{r.name}"' if spec.tool not in BOOK_TOOLS else r.name, "relative": r, "name_form": None}))
        out: list[tuple[QuerySpec, Decision]] = []
        seen = set()
        for c in cands:
            d = self.classify(c)
            if d.allowed and d.canonical_id not in seen:
                seen.add(d.canonical_id)
                out.append((c, d))
        out.sort(key=lambda x: -NOVELTY_BY_KEY.get(x[1].key_type or "", 1.0 if x[1].decision == "new" else 0.0))
        return out[:n]

    # ---- reporting
    def summary(self) -> dict:
        allowed = [r for r in self.s.log if r["decision"] in ("new", "revisit", "unchecked")]
        return {"entries": len(self.s.entries), "allowed": len(allowed), "blocked": self.s.blocked,
                "revisit_count": dict(self.s.revisits), "closed_sources": sum(1 for s in self.s.sources.values() if s.closed)}

    def jsonl(self) -> str:
        return "".join(json.dumps(r, default=str) + "\n" for r in self.s.log)


def life_window(p: Person) -> tuple[int, int]:
    b = p.birth_year or 0
    if p.death_year:
        return (b, p.death_year + 5)
    return (b, b + 100)
