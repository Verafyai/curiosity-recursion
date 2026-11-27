"""Activities for the v0.2 swarm. Every side effect (network, files) lives here.

- swarm_tool: one tool call = one unit of B. Idempotent: keyed by run id + canonical id, the result
  is written to the run's evidence store and returned from there if Temporal retries or replays,
  so a retry never double-counts budget or evidence. Heartbeats every few seconds while waiting.
- plan_outline, merge_verify, reflect_round: deterministic code run as activities so their results
  are recorded in history.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from temporalio import activity

from cr import sources as src
from cr.ledger import BOOK_TOOLS
from cr.models import Person
from cr.outline import Outline, plan_outline
from cr.reflection import Lesson, reflect
from cr.swarm_logic import evidence_from_rows, relatives_from, verified_ok
from cr.swarm_models import MergeInput, MergeOutput, ReflectInput, ToolCall, ToolResult

ROOT = Path(__file__).resolve().parent.parent


def _store() -> Path:
    return Path(os.environ.get("CR_EVIDENCE_DIR", ROOT / "data" / "evidence"))


async def _run_tool(spec):
    t = spec.tool
    if t == "ia_fts":
        return await src.ia_fts(spec.terms, size=10, offset=spec.offset, collection=spec.collection_or_item)
    if t == "ia_fulltext":
        return await src.ia_fulltext(spec.terms)
    if t == "ia_inside":
        return await src.ia_inside(spec.collection_or_item or "", spec.terms)
    if t == "ia_inside_pages":
        a, b = spec.page_window or (1, 10)
        return await src.ia_inside_pages(spec.collection_or_item or "", spec.terms, a, b)
    if t == "ia_title":
        return await src.ia_title_search(spec.terms)
    if t == "chronam":
        return await src.chronam(spec.terms, tuple(spec.date_window) if spec.date_window else None)
    if t == "wikidata_search":
        return await src.wikidata_search(spec.terms)
    if t == "wikidata_entities":
        return await src.wikidata_entities([spec.collection_or_item or spec.terms])
    raise ValueError(f"unknown tool {t}")


@activity.defn
async def swarm_tool(call: ToolCall) -> ToolResult:
    path = _store() / call.run_id / f"{call.canonical_id}-{call.seq}.json"
    if path.exists():
        r = ToolResult.model_validate_json(path.read_text())
        r.from_store = True
        return r
    if os.environ.get("CR_FAULT_P"):  # fault harness (bench/faults.py): flaky archives, same rule as v0.1 investigations
        from cr.activities import _flaky
        info = activity.info()
        if info.attempt <= _flaky(f"{call.canonical_id}-{call.seq}", info.workflow_id):
            raise RuntimeError(f"Simulated archive flakiness: HTTP 503 from {call.spec.tool} (attempt {info.attempt})")
    done = asyncio.Event()

    async def beat():
        i = 0
        while not done.is_set():
            activity.heartbeat({"canonical_id": call.canonical_id, "tick": i})
            i += 1
            try:
                await asyncio.wait_for(done.wait(), timeout=5)
            except asyncio.TimeoutError:
                pass
    hb = asyncio.create_task(beat())
    err = ""
    try:
        try:
            rows = await _run_tool(call.spec)
        except ValueError as e:  # 4xx: the source said no; not worth retrying
            rows, err = [], f"refused: {e}"[:200]
    finally:
        done.set()
        await hb
    evs = evidence_from_rows(call.spec.tool, call.spec, rows, call.person, call.canonical_id)
    matched = [e for e in evs if e.name_match == "strong"]
    book_hits: dict[str, list[int]] = {}
    for e in matched:
        if e.item_id and e.page and call.spec.tool not in BOOK_TOOLS:
            book_hits.setdefault(e.item_id, []).append(e.page)
    res = ToolResult(canonical_id=call.canonical_id, items=evs, n_items=len(rows) if isinstance(rows, (list, dict)) else 0,
                     n_matched=len(matched), hit_pages=sorted({e.page for e in matched if e.page and call.spec.tool in BOOK_TOOLS}),
                     book_hits=book_hits, error=err)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(res.model_dump_json())
    tmp.replace(path)
    return res


@activity.defn(name="plan_outline")
async def plan_outline_activity(inp: dict) -> Outline:
    p = Person.model_validate(inp["person"])
    return plan_outline(p, inp.get("reflections") or [], inp.get("tools", "v2"))


@activity.defn
async def merge_verify(inp: MergeInput) -> MergeOutput:
    """Dedupe by source key, run the verification gate and the rules skeptic, count agreement."""
    known = set(inp.known_keys)
    out = MergeOutput()
    seen: dict[str, set[str]] = {}
    for ev in inp.new_evidence:
        seen.setdefault(ev.key, set()).add(ev.lane)
    done = set()
    for ev in inp.new_evidence:
        if ev.key in known or ev.key in done:
            out.duplicates += 1
            continue
        done.add(ev.key)
        ok, why = verified_ok(inp.person, ev)
        if ok:
            out.verified.append(ev)
            out.support[ev.key] = len(seen.get(ev.key, {ev.lane}))
        elif ev.name_match == "strong" and not ev.in_life:
            out.namesakes.append({"key": ev.key, "name": inp.person.full_name, "year": ev.year, "url": ev.url})
        elif ev.name_match == "strong":
            out.refuted.append({"key": ev.key, "why": why})
        elif ev.name_match == "surname_only" or ev.tool == "ia_title":
            out.leads_only.append(ev)
    rels = relatives_from(inp.person, out.verified)
    out.relatives = [r for r in rels if r.name.lower() not in {x.lower() for x in inp.known_relatives}]
    return out


@activity.defn
async def reflect_round(inp: ReflectInput) -> list[Lesson]:
    return reflect(inp.round, [c.model_dump() for c in inp.calls], inp.namesakes, inp.relatives, set(inp.known))


def dump_ledger(path: Path, ledger_log: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, default=str) + "\n" for r in ledger_log))


@activity.defn
async def load_graph_cache(path: str) -> dict[str, str]:
    """Post hoc feature (after the v0.2 preregistration), used only when ResearchRequest.graph_cache is set:
    read earlier runs' search graph(s) and return the canonical ids they executed. A directory loads every
    *.graph.json in it."""
    from cr import search_graph as sg
    p = Path(path)
    files = sorted(p.glob("*.graph.json")) if p.is_dir() else [p]
    return sg.done_queries(sg.merge([sg.load(f) for f in files])) if files else {}
