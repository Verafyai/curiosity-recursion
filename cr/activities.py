"""Activities: every side effect lives here (network, SQLite, files).

Temporal retries these on failure with the policies set in workflows.py, and
records each result in workflow history, so a killed worker never repeats a
finished lookup.
"""

from __future__ import annotations

import os
import re
import zlib
from datetime import datetime, timezone

from temporalio import activity

from cr import sources as src
from cr.generators import generate
from cr.circuits import CIRCUITS, STAGE_LABELS
from cr.fixtures import golden_also_at, golden_claims_for, relatives_sources
from cr.models import (
    BrainstormInput, BrainstormOutput, CatalogSnapshot, CatalogSource, Citation, Claim, ComposeInput, Finding,
    InvestigateInput, InvestigateOutput, OutreachDraft, PersistInput, Person, PriorInput, PriorQuestions, Question,
    StepInput, StepOutput, StudioReport,
)
from cr.names import match, surname, town_state
from cr.writer import compose

# Persistence and outreach activities live in cr/memory.py and cr/outreach.py; re-exported here
# so the worker registers every activity from one module.
from cr.memory import load_prior_questions, persist_run  # noqa: F401
from cr.outreach import draft_outreach, export_outreach  # noqa: F401


def now() -> datetime:
    return datetime.now(timezone.utc)


def excerpt(text: str, word: str, width: int = 170) -> str:
    i = text.lower().find(word.lower())
    if i < 0:
        return text[:width * 2]
    a, b = max(0, i - width), min(len(text), i + len(word) + width)
    s = text[a:b]
    s = re.sub(re.escape(word), lambda m: f"**{m.group(0)}**", s, flags=re.I)
    return ("..." if a else "") + re.sub(r"\s+", " ", s).strip() + ("..." if b < len(text) else "")


def around_mark(text: str, width: int = 170) -> str:
    """Trim a snippet to the window around its first **match**."""
    i = text.find("**")
    if i < 0 or len(text) <= width * 2:
        return text[: width * 2]
    a, b = max(0, i - width), min(len(text), i + width)
    return ("..." if a else "") + text[a:b] + ("..." if b < len(text) else "")


def fmt(q: str, p: Person) -> str:
    town, state = town_state(p.birth_place or p.death_place)
    return q.format(name=p.full_name, surname=surname(p), town=town, state=state)


# ---------------------------------------------------------------- catalog

@activity.defn
async def load_catalog() -> CatalogSnapshot:
    """Optional public source catalog at CR_CATALOG_URL. Read-only GETs."""
    if not src.LINEAGE_API:
        raise ValueError("CR_CATALOG_URL is not set")
    sources, taxonomy = await src.lineage_catalog()
    rows = sources.get("data") or []
    wars = (((taxonomy.get("buckets") or {}).get("veteran") or {}).get("war")) or []
    return CatalogSnapshot(
        endpoint=f"{src.LINEAGE_API}/v1/sources",
        source_count=sources.get("count") or len(rows),
        sources=[CatalogSource(slug=r.get("slug"), name=r.get("name"), access_method=r.get("access_method"),
                               status=r.get("status"), record_types=r.get("record_types") or []) for r in rows],
        taxonomy_version=taxonomy.get("version"),
        wars=wars if isinstance(wars, list) else [],
    )


# ---------------------------------------------------------------- live helpers

async def _wikidata(p: Person) -> tuple[list[Citation], list[dict]]:
    ids: list[str] = []
    for nm in p.all_names()[:3]:
        for hit in await src.wikidata_search(nm):
            if hit["id"] not in ids:
                ids.append(hit["id"])
    ents = await src.wikidata_entities(ids[:20])
    cits, matched = [], []
    for qid, e in ents.items():
        if "Q5" not in src.wd_items(e, "P31"):
            continue
        b, d = src.wd_year(e, "P569"), src.wd_year(e, "P570")
        ok = True
        if p.birth_year and b and abs(b - p.birth_year) > 1:
            ok = False
        if p.death_year and d and abs(d - p.death_year) > 1:
            ok = False
        if not (b or d):
            ok = False
        if ok:
            label = (e.get("labels", {}).get("en") or {}).get("value", qid)
            desc = (e.get("descriptions", {}).get("en") or {}).get("value", "")
            cits.append(Citation(title=f"Wikidata {qid}: {label} ({desc})", url=f"https://www.wikidata.org/wiki/{qid}", archive="Wikidata"))
            matched.append(e)
    return cits, matched


async def _chronam(p: Person, query: str, years) -> list[Citation]:
    rows = await src.chronam(query, years)
    out = []
    for r in rows:
        text = r.get("text") or ""
        who = p.full_name
        nm = match(Person(full_name=who, name_variants=p.name_variants), text)
        if nm == "none":
            continue
        out.append(Citation(title=r.get("title") or "Chronicling America page", url=r.get("url"), archive="Library of Congress, Chronicling America",
                            year=int(r["date"][:4]) if r.get("date") else None,
                            snippet=excerpt(text, surname(p)), name_match=nm))
    return out


def _ia_cit(doc: dict, snippet: str | None = None, nm: str | None = None) -> Citation:
    return Citation(title=doc.get("title") or doc.get("identifier"), url=f"https://archive.org/details/{doc.get('identifier')}",
                    archive="Internet Archive", item_id=doc.get("identifier"),
                    year=int(str(doc["year"])[:4]) if doc.get("year") and str(doc["year"])[:4].isdigit() else None,
                    snippet=snippet, name_match=nm)


# ---------------------------------------------------------------- checklist steps

FIELD_MAP = {"birth": "birth", "death": "death", "marriage": "marriage", "military": "military", "residence": "residence",
             "occupation": "occupation", "education": "education", "membership": "membership", "child": "child", "burial": "burial"}


@activity.defn
async def run_checklist_step(inp: StepInput) -> StepOutput:
    req, step, p = inp.request, inp.step, inp.request.person
    info = activity.info()
    base = dict(step_id=step.id, step_title=step.title, stage=step.stage, source_slug=step.source_slug, mode=step.mode,
                attempt=info.attempt, checked_at=now(), round=inp.round)
    names = p.all_names()
    h = step.handler
    if h in ("fixture", "findagrave", "relatives_photos", "relatives_sources") and not req.use_fixtures:
        return StepOutput(findings=[Finding(**base, status="skipped", confidence="none",
                                            notes=f"STUB, fixtures off (benchmark mode). Identified as a source to request, not fetched. {step.why_stub}")])
    if h == "fixture":
        hits = golden_claims_for(names, step.fixture_fields)
        claims = [Claim(id=e["id"], field=FIELD_MAP.get(e["type"], e["type"]), text=e["value"], tier="documented", year=e.get("year"),
                        citation=Citation(title=e["source"]["title"], url=e["source"].get("url")), origin=f"fixture:{f}#{e['id']}")
                  for f, e in hits]
        return StepOutput(findings=[Finding(**base, status="found" if claims else "nothing", confidence="documented" if claims else "none",
                                            claims=claims, citations=[c.citation for c in claims],
                                            notes=f"STUB. {step.why_stub}" + ("" if claims else " No fixture claim for this person."))])
    if h == "findagrave":
        hits = golden_also_at(names, "Find a Grave")
        cits = list({a["url"]: Citation(title=a["title"], url=a["url"], archive="Find a Grave (link only, not fetched)") for _, a in hits}.values())
        return StepOutput(findings=[Finding(**base, status="candidates" if cits else "nothing", confidence="possible" if cits else "none",
                                            citations=cits, notes=f"STUB. {step.why_stub}")])
    if h in ("relatives_photos", "relatives_sources"):
        rows = relatives_sources(names, "photo" if h == "relatives_photos" else step.query, must_name=(h == "relatives_photos"))
        cits = [Citation(title=r["title"], url=r["url"] if r["url"].startswith("http") else None, archive=r.get("archive")) for r in rows]
        return StepOutput(findings=[Finding(**base, status="candidates" if cits else "nothing", confidence="possible" if cits else "none",
                                            citations=cits, notes=f"STUB. {step.why_stub}")])
    if h == "wikidata" or h == "wikidata_kin":
        cits, ents = await _wikidata(p)
        if h == "wikidata_kin":
            kin_ids = [i for e in ents for prop in ("P22", "P25", "P26") for i in src.wd_items(e, prop)]
            kin = await src.wikidata_entities(kin_ids[:10], props="labels")
            cits = [Citation(title=f"Wikidata relative {k}: {(v.get('labels', {}).get('en') or {}).get('value', k)}", url=f"https://www.wikidata.org/wiki/{k}", archive="Wikidata") for k, v in kin.items()]
        return StepOutput(findings=[Finding(**base, status="found" if cits else "nothing", confidence="candidate" if cits else "none",
                                            citations=cits, endpoint="wikidata.org/w/api.php",
                                            notes="LIVE. Human items whose birth or death year matches within a year." if h == "wikidata" else "LIVE. Parents and spouses of matched items.")])
    if h == "ia":
        docs = await src.ia_title_search(fmt(step.query, p))
        cits = [_ia_cit(d) for d in docs]
        return StepOutput(findings=[Finding(**base, status="candidates" if cits else "nothing", confidence="candidate" if cits else "none",
                                            citations=cits, endpoint="archive.org/advancedsearch.php",
                                            notes=f"LIVE. Catalog title search: {fmt(step.query, p)}. Books that may cover it; not read yet.")])
    if h == "chronam":
        y = (p.birth_year, (p.death_year or p.birth_year + 90) + 1) if p.birth_year else None
        cits = await _chronam(p, fmt('"' + step.query + '"', p), y)
        strong = [c for c in cits if c.name_match == "strong"]
        return StepOutput(findings=[Finding(**base, status="candidates" if cits else "nothing", confidence="candidate" if cits else "none",
                                            citations=cits[:6], endpoint="loc.gov/collections/chronicling-america",
                                            notes=f"LIVE. {len(strong)} pages print the full name; none is confirmed to be him without place and date.")])
    raise ValueError(f"unknown handler {h}")


# ---------------------------------------------------------------- brainstorm

@activity.defn
async def brainstorm_questions(inp: BrainstormInput) -> BrainstormOutput:
    """The generator g(s, R, v, M). Rules by default; a grounded LLM or a hybrid when asked."""
    return await generate(inp)


# ---------------------------------------------------------------- investigate one question

def _flaky(question_id: str, workflow_id: str) -> int:
    """How many early attempts to fail for this node. Deterministic per node.

    Demo default: about 3 in 10 nodes fail 1 or 2 attempts. The benchmark's fault harness sets
    CR_FAULT_P (failure probability per node) and CR_FAULT_K (attempts that fail) instead.
    """
    h = zlib.crc32(f"{workflow_id}:{question_id}".encode())
    if os.environ.get("CR_FAULT_P"):
        p, k = float(os.environ["CR_FAULT_P"]), int(os.environ.get("CR_FAULT_K", "2"))
        return k if (h % 10_000) / 10_000 < p else 0
    h %= 10
    return 2 if h == 0 else 1 if h in (1, 2) else 0


@activity.defn
async def investigate(inp: InvestigateInput) -> InvestigateOutput:
    q, req, p = inp.question.model_copy(deep=True), inp.request, inp.request.person
    info = activity.info()
    fail_n = _flaky(q.id, info.workflow_id) if (req.simulate_flaky_archives or os.environ.get("CR_FAULT_P")) and q.plan.handler != "stub" else 0
    if info.attempt <= fail_n:
        activity.heartbeat(f"simulated failure {info.attempt}")
        raise RuntimeError(f"Simulated archive flakiness: HTTP 503 from {q.plan.handler} (attempt {info.attempt} of {fail_n + 1})")
    q.attempts = info.attempt
    if info.attempt > 1:
        q.failures = [f"attempt {i}: failed, retried by Temporal" + (" (simulated 503)" if i <= fail_n else "") for i in range(1, info.attempt)]
    who = Person(full_name=q.about) if q.about else p
    plan = q.plan
    cits: list[Citation] = []
    endpoint, slug, outreach = None, "none", None
    refused = ""
    cits, endpoint, slug, outreach = [], None, "none", None
    try:
        cits, endpoint, slug, outreach = await _run_plan(q, req, p, who, plan)
    except ValueError as e:  # 4xx: the source said no (lending-library book, bad id). Not worth retrying.
        refused = f"Source refused the request ({e}). Not retried: a 4xx will not change on retry."
    if refused:
        q.status, q.answer = "no_lead", refused
        cits = []
    return _finish(q, req, info, cits, endpoint, slug, outreach, refused)


async def _run_plan(q, req, p, who, plan):
    cits: list[Citation] = []
    endpoint, slug, outreach = None, "none", None
    if plan.handler == "ia_fulltext":
        endpoint, slug = "archive.org full-text search", "internet-archive"
        for hit in await src.ia_fulltext(plan.query):
            snip = next((s for s in hit["snippets"] if match(who, s) != "none"), hit["snippets"][0] if hit["snippets"] else None)
            cits.append(_ia_cit(hit, around_mark(snip) if snip else None, match(who, snip or "")))
    elif plan.handler == "ia_inside":
        endpoint, slug = "archive.org fulltext/inside.php", "internet-archive"
        for m in await src.ia_inside(plan.item_id or "", plan.query):
            nm = match(who, m["text"])
            page = m.get("page")
            cits.append(Citation(title=f"{q.text.split(chr(34))[1] if chr(34) in q.text else plan.item_id}, page image {page}",
                                 url=f"https://archive.org/details/{plan.item_id}/page/n{max((page or 1) - 1, 0)}/mode/1up?q={plan.query}",
                                 archive="Internet Archive", item_id=plan.item_id, snippet=around_mark(m["text"]), name_match=nm))
        cits.sort(key=lambda c: {"strong": 0, "surname_only": 1, "none": 2}[c.name_match or "none"])
    elif plan.handler == "ia_title":
        endpoint, slug = "archive.org/advancedsearch.php", "internet-archive"
        cits = [_ia_cit(d) for d in await src.ia_title_search(plan.query)]
    elif plan.handler == "chronam":
        endpoint, slug = "loc.gov Chronicling America", "loc-chronicling-america"
        cits = await _chronam(who if q.about else p, plan.query, plan.years)
    elif plan.handler in ("wikidata", "wikidata_kin"):
        endpoint, slug = "wikidata.org/w/api.php", "wikidata"
        ents = await src.wikidata_entities([plan.query])
        kin_ids = [i for e in ents.values() for prop in ("P22", "P25", "P26") for i in src.wd_items(e, prop)]
        kin = await src.wikidata_entities(kin_ids[:10], props="labels")
        cits = [Citation(title=f"Wikidata {k}: {(v.get('labels', {}).get('en') or {}).get('value', k)}", url=f"https://www.wikidata.org/wiki/{k}", archive="Wikidata") for k, v in kin.items()]
    elif plan.handler == "stub":
        q.status, q.mode = "stub", "stub"
        q.answer = f"STUB, not searched. {plan.why_stub}"
        outreach = draft_outreach(q, req)
        if outreach:
            q.outreach_id = outreach.id
    return cits, endpoint, slug, outreach


def _finish(q, req, info, cits, endpoint, slug, outreach, refused):
    plan = q.plan
    if plan.handler != "stub" and not refused:
        strong = [c for c in cits if c.name_match == "strong"]
        if plan.handler == "ia_title":
            q.status = "answered" if cits else "no_lead"
            q.answer = f"{len(cits)} books may cover this. Next level searches inside them." if cits else "No catalog match."
        elif strong:
            q.status = "answered"
            q.answer = f"{len(strong)} of {len(cits)} hits print the name in full. Read the snippets: an OCR name match is a lead, not proof."
        elif cits:
            q.status = "no_lead"
            q.answer = f"{len(cits)} hits, but only on the surname. Not treated as the same person."
        else:
            q.status = "no_lead"
            q.answer = "Nothing found."
        q.citations = cits[:8]
        q.snippets = [c.snippet for c in cits[:4] if c.snippet]
    q.finished_at = now()
    f = Finding(step_id=q.id, step_title=q.text, stage=_stage(q.template), source_slug=slug, mode=q.mode,
                status="found" if q.status == "answered" else ("skipped" if q.status == "stub" else "nothing"),
                confidence="possible" if q.status == "answered" and any(c.name_match == "strong" for c in q.citations) else ("candidate" if q.citations else "none"),
                citations=q.citations, notes=q.answer, endpoint=endpoint, attempt=info.attempt, checked_at=q.finished_at,
                round=q.round, about=q.about)
    return InvestigateOutput(question=q, finding=f, outreach=outreach)


def _stage(template: str) -> int:
    if template.startswith(("unit", "node->are")):
        return 5
    if template.startswith(("ship", "place", "marriage")):
        return 3
    if "parents" in template:
        return 4
    if template.startswith(("book", "congregation", "school", "snippet->collection", "name")):
        return 6
    return 2


# ---------------------------------------------------------------- compose

@activity.defn
async def compose_report(inp: ComposeInput) -> StudioReport:
    return compose(inp)
