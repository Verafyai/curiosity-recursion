"""B0 (single pass) and B1 (ReAct) baselines with the same tools and sources as CR.

Both use the Anthropic Messages API with tool use. The key comes from ANTHROPIC_API_KEY and the
model from CR_LLM_MODEL. Without a key the run is logged as not run: nothing is simulated.

- B0: one search-and-answer pass. The model may call tools in one turn, then must answer.
- B1: ReAct (Yao et al. 2023): think, act, observe, repeat until it stops or spends the budget.
Every tool call counts toward the same budget B as CR's checklist steps and investigations.
"""
from __future__ import annotations

import json
import os
import time
import uuid

import httpx

from bench.common import commit, now
from cr import sources as src

TOOLS = [
    {"name": "ia_fulltext", "description": "Full-text search across digitised books on Internet Archive.",
     "input_schema": {"type": "object", "properties": {"phrase": {"type": "string"}}, "required": ["phrase"]}},
    {"name": "ia_inside", "description": "Search inside one Internet Archive book by identifier.",
     "input_schema": {"type": "object", "properties": {"item_id": {"type": "string"}, "q": {"type": "string"}}, "required": ["item_id", "q"]}},
    {"name": "ia_title", "description": "Internet Archive catalogue title search.",
     "input_schema": {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]}},
    {"name": "chronam", "description": "Chronicling America historic newspapers (loc.gov).",
     "input_schema": {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]}},
    {"name": "wikidata", "description": "Wikidata people search by name.",
     "input_schema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}},
]


async def _tool(name: str, args: dict) -> tuple[str, list[dict]]:
    try:
        if name == "ia_fulltext":
            hits = await src.ia_fulltext(args["phrase"])
            cits = [{"url": f"https://archive.org/details/{h['identifier']}", "item_id": h["identifier"], "title": h.get("title")} for h in hits]
        elif name == "ia_inside":
            hits = await src.ia_inside(args["item_id"], args["q"])
            cits = [{"url": f"https://archive.org/details/{args['item_id']}", "item_id": args["item_id"], "title": f"page {m.get('page')}"} for m in hits]
        elif name == "ia_title":
            hits = await src.ia_title_search(args["q"])
            cits = [{"url": f"https://archive.org/details/{h['identifier']}", "item_id": h["identifier"], "title": h.get("title")} for h in hits]
        elif name == "chronam":
            hits = await src.chronam(args["q"], None)
            cits = [{"url": h.get("url"), "title": h.get("title")} for h in hits]
        else:
            hits = await src.wikidata_search(args["name"])
            cits = [{"url": f"https://www.wikidata.org/wiki/{h['id']}", "title": h.get("label")} for h in hits]
        return json.dumps(hits, default=str)[:6000], cits
    except Exception as e:
        return f"error: {e}", []


async def run(agent: str, subject: dict, budget: int, seed: int) -> dict:
    meta = dict(run_id=f"{agent}-{subject['subject_id']}-b{budget}-s{seed}-{uuid.uuid4().hex[:6]}", agent=agent, subject_id=subject["subject_id"],
                budget=budget, seed=seed, commit=commit(), started_at=now(), config={"model": os.environ.get("CR_LLM_MODEL", "claude-sonnet-5-5")})
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return {**meta, "completed": False, "stop_reason": "not run: no ANTHROPIC_API_KEY", "tool_calls": 0, "citations": [], "drafts": [], "questions": []}
    i = subject["input"]
    task = (f"Find records about {i['full_name']} (born {i.get('birth_year')}, died {i.get('death_year')}, {i.get('birth_place') or ''}). "
            "List every record you find with its URL. Do not invent records.")
    msgs, cits, calls, tokens, t0 = [{"role": "user", "content": task}], [], 0, 0, time.time()
    async with httpx.AsyncClient(timeout=120) as c:
        for turn in range(1 if agent == "B0" else 100):
            body = {"model": meta["config"]["model"], "max_tokens": 2000, "tools": TOOLS, "messages": msgs}
            r = await c.post("https://api.anthropic.com/v1/messages", json=body,
                             headers={"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01"})
            r.raise_for_status()
            resp = r.json()
            tokens += sum(resp.get("usage", {}).get(k, 0) for k in ("input_tokens", "output_tokens"))
            uses = [b for b in resp["content"] if b["type"] == "tool_use"]
            msgs.append({"role": "assistant", "content": resp["content"]})
            if not uses or calls >= budget:
                break
            results = []
            for u in uses:
                if calls >= budget:
                    results.append({"type": "tool_result", "tool_use_id": u["id"], "content": "budget spent"})
                    continue
                calls += 1
                text, cs = await _tool(u["name"], u["input"])
                cits += [{**x, "node": f"{agent}-call{calls}", "depth": 0} for x in cs]
                results.append({"type": "tool_result", "tool_use_id": u["id"], "content": text})
            msgs.append({"role": "user", "content": results})
    return {**meta, "completed": True, "stop_reason": "model stopped" if calls < budget else f"Reached the {budget} tool-call budget.",
            "tool_calls": calls, "llm_tokens": tokens, "wall_seconds": round(time.time() - t0, 1), "citations": cits, "drafts": [], "questions": []}
