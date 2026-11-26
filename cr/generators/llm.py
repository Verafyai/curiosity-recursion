"""A grounded model generator for Curiosity Recursion.

The model sees the subject, the findings that sparked this node (each with a spark id and its
text), the chain of questions above the node, every question already asked (memory M), the
circuit's checklist gaps, and the handlers the system can run. It must return JSON questions,
each naming a `spark_id`, quoting words from that spark, and giving a runnable plan.

Grounding is enforced in code, not trusted to the prompt: a question whose spark id is unknown,
whose quote is not in that spark's text, or whose plan cannot run is rejected and counted.
The key is read from ANTHROPIC_API_KEY in the worker's environment only. CR_LLM_MODEL picks the
model. A per-run token budget (ResearchRequest.llm_token_budget) is a hard stop.

This module only runs inside the brainstorm activity, so workflow replay stays deterministic.
It has not been measured yet: every result that uses it is TBD in the paper.
"""
from __future__ import annotations

import json
import os
import re
from typing import Awaitable, Callable

import httpx

from cr.generators.rules import checklist
from cr.models import BrainstormInput, Plan, Question
from cr.novelty import canonical_key

API = "https://api.anthropic.com/v1/messages"
HANDLERS = {
    "ia_fulltext": "full-text search across digitised books on Internet Archive; query is a quoted phrase",
    "ia_inside": "search inside one Internet Archive book; needs item_id and a query word",
    "ia_title": "Internet Archive catalogue title search; query uses title:(...) syntax",
    "chronam": "Chronicling America historic newspapers on loc.gov; query is words",
    "stub": "needs a human: a letter, a login or an archive visit; give why_stub; becomes an outreach draft",
}
SYSTEM = (
    "You are the curiosity loop of a genealogical research agent. Ask new, specific questions that "
    "the evidence just made possible. Every question must be sparked by one finding: give its spark_id "
    "and quote 3 to 12 words from it exactly. Do not invent records, people, dates or addresses. "
    "Prefer questions that switch to a source family not yet tried (church and synagogue registers, "
    "school records, ship crew lists, regimental histories, veteran posts, local newspapers, town "
    "histories, family collections). Return JSON only: {\"questions\": [{\"text\", \"spark_id\", \"quote\", "
    "\"handler\", \"query\", \"item_id\", \"why_stub\"}]}"
)

ModelCall = Callable[[dict], Awaitable[dict]]


async def _anthropic(body: dict) -> dict:
    key = os.environ["ANTHROPIC_API_KEY"]
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(API, json=body, headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                                                  "content-type": "application/json"})
    r.raise_for_status()
    return r.json()


call_model: ModelCall = _anthropic  # tests replace this with a fake


def sparks(inp: BrainstormInput) -> dict[str, str]:
    """spark id -> text, for every claim and snippet the generator may build on."""
    out: dict[str, str] = {}
    for fi, f in enumerate(inp.findings):
        for c in f.claims:
            out[c.id] = c.text
        for ci, c in enumerate(f.citations):
            if c.snippet:
                out[f"{f.step_id}#{ci}"] = f"{c.title}: {c.snippet.replace('**', '')}"
            elif c.title:
                out[f"{f.step_id}#{ci}"] = c.title
    if inp.node is not None and inp.node.answer:
        out[f"{inp.node.id}#answer"] = inp.node.answer
    for g in checklist(inp.request, inp.findings):
        if g.state == "missing":
            out[f"gap:{g.topic}"] = f"Checklist gap: no record yet for {g.label.lower()}"
    return out


def _fold(s: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", s.lower()))


def validate(raw: dict, spark_text: dict[str, str]) -> tuple[Question | None, str]:
    """One model question against the grounding constraint. Returns (question, '') or (None, why)."""
    text = (raw.get("text") or "").strip()
    sid, quote = raw.get("spark_id") or "", raw.get("quote") or ""
    handler = raw.get("handler") or ""
    if not text:
        return None, "empty"
    if sid not in spark_text:
        return None, "unknown spark id"
    if len(_fold(quote).split()) < 3 or _fold(quote) not in _fold(spark_text[sid]):
        return None, "quote is not in the spark"
    if handler not in HANDLERS:
        return None, "plan cannot run"
    if handler == "ia_inside" and not raw.get("item_id"):
        return None, "ia_inside needs an item id"
    if handler != "stub" and not (raw.get("query") or "").strip():
        return None, "no query"
    plan = Plan(handler=handler, query=(raw.get("query") or "").strip(), item_id=raw.get("item_id") or None,
                why_stub=(raw.get("why_stub") or "Needs a human: letter, login or visit.") if handler == "stub" else "")
    q = Question(id="tmp", key=canonical_key("llm", " ".join(sorted(set(_fold(text).split())))[:120]), round=0, text=text,
                 because=f"because {sid} says \"{quote.strip()}\"", template="llm->grounded", parent_finding=sid,
                 score=6.0, plan=plan, mode="stub" if handler == "stub" else "live")
    return q, ""


async def generate(inp: BrainstormInput) -> tuple[list[Question], int, int] | None:
    req = inp.request
    if not os.environ.get("ANTHROPIC_API_KEY") and call_model is _anthropic:
        return None
    if inp.llm_tokens_used >= req.llm_token_budget:
        return None
    spark_text = sparks(inp)
    if not spark_text:
        return [], 0, 0
    chain, by_id = [], {q.id: q for q in inp.questions}
    cur = inp.node
    while cur is not None:
        chain.append(cur.text)
        cur = by_id.get(cur.parent_id) if cur.parent_id != "root" else None
    p = req.person
    user = {
        "subject": {"name": p.full_name, "variants": p.name_variants, "born": p.birth_year, "died": p.death_year,
                    "place": p.birth_place or p.death_place, "research_question": req.question},
        "sparks": spark_text,
        "question_chain_above_this_node": list(reversed(chain)),
        "already_asked": sorted({q.text for q in inp.questions})[:200],
        "handlers": HANDLERS,
        "ask_for": f"Up to {max(inp.top_n * 2, 4)} new questions.",
    }
    body = {"model": os.environ.get("CR_LLM_MODEL", "claude-sonnet-5-5"), "max_tokens": 1500, "system": SYSTEM,
            "messages": [{"role": "user", "content": json.dumps(user, ensure_ascii=False)}]}
    try:
        resp = await call_model(body)
    except (httpx.HTTPError, KeyError):
        return None
    usage = resp.get("usage") or {}
    tokens = int(usage.get("input_tokens", 0)) + int(usage.get("output_tokens", 0))
    text = "".join(b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text")
    m = re.search(r"\{.*\}", text, re.S)
    try:
        items = json.loads(m.group(0)).get("questions", []) if m else []
    except json.JSONDecodeError:
        items = []
    out, rejected = [], 0
    for raw in items:
        q, why = validate(raw if isinstance(raw, dict) else {}, spark_text)
        if q is None:
            rejected += 1
            continue
        q.round, q.depth = inp.round, inp.depth
        q.about = inp.node.about if inp.node is not None else None
        out.append(q)
    return out, tokens, rejected
