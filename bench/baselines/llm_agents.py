"""B0 (single pass) and B1 (ReAct) baselines with the same tools and sources as CR.

Both use the Anthropic Messages API when ANTHROPIC_API_KEY is set, otherwise the OpenAI Chat
Completions API with function calling when OPENAI_API_KEY is set (the 26 Nov 2026 benchmark run
used OpenAI because no Anthropic key was configured). CR_LLM_MODEL picks the model. Without a key
the run is logged as not run: nothing is simulated. Token usage (including cached input tokens)
and list-price dollars are written into every results line, and a shared spend file
(CR_SPEND_FILE) with a hard cap (CR_SPEND_CAP_USD) stops new model calls once the cap is reached.

- B0: one search-and-answer pass. The model may call tools in one turn, then must answer.
- B1: ReAct (Yao et al. 2023): think, act, observe, repeat until it stops or spends the budget.
Every tool call counts toward the same budget B as CR's checklist steps and investigations.
"""
from __future__ import annotations

import fcntl
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


# List prices in USD per 1M tokens (input, cached input, output), checked 26 Nov 2026.
PRICES = {"gpt-4.1-mini": (0.40, 0.10, 1.60), "gpt-4.1-nano": (0.10, 0.025, 0.40), "gpt-4o-mini": (0.15, 0.075, 0.60)}
TOOL_TEXT_CHARS = int(os.environ.get("CR_TOOL_TEXT_CHARS", "6000"))


def _spend(add: float = 0.0) -> float:
    """Add to and return the shared spend total (file locked, so parallel runs share one cap)."""
    path = os.environ.get("CR_SPEND_FILE")
    if not path:
        return 0.0
    with open(path, "a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.seek(0)
        tot = float(f.read().strip() or 0) + add
        f.seek(0)
        f.truncate()
        f.write(f"{tot:.6f}")
        return tot


def _cap() -> float:
    return float(os.environ.get("CR_SPEND_CAP_USD", "1e9"))


def _oa_tools() -> list[dict]:
    return [{"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]}} for t in TOOLS]


API_URLS = {"openai": "https://api.openai.com/v1/chat/completions", "xai": "https://api.x.ai/v1/chat/completions"}
API_KEYS = {"openai": "OPENAI_API_KEY", "xai": "XAI_API_KEY"}

SYSTEM = ("You are a genealogical research agent. Use the tools to find records about the person. "
          "Search as many different ways as are useful: name variants, places, newspapers, books, catalogues. "
          "When you are done, list every record you found with its URL. Do not invent records.")


async def run(agent: str, subject: dict, budget: int, seed: int) -> dict:
    use_anthropic = bool(os.environ.get("ANTHROPIC_API_KEY")) and os.environ.get("CR_LLM_API", "anthropic") == "anthropic"
    api = "anthropic" if use_anthropic else os.environ.get("CR_LLM_API", "openai")
    model = os.environ.get("CR_LLM_MODEL", {"anthropic": "claude-sonnet-5-5", "xai": "grok-4.20-0309-non-reasoning"}.get(api, "gpt-4.1-mini"))
    meta = dict(run_id=f"{agent}-{subject['subject_id']}-b{budget}-s{seed}-{uuid.uuid4().hex[:6]}", agent=agent, subject_id=subject["subject_id"],
                budget=budget, seed=seed, commit=commit(), started_at=now(),
                config={"model": model, "api": api, "temperature": 1.0, "tool_text_chars": TOOL_TEXT_CHARS})
    if not use_anthropic and not os.environ.get(API_KEYS.get(api, "OPENAI_API_KEY")):
        return {**meta, "completed": False, "stop_reason": "not run: no model API key", "tool_calls": 0, "citations": [], "drafts": [], "questions": []}
    if _spend() >= _cap():
        return {**meta, "completed": False, "stop_reason": "not run: spend cap reached", "tool_calls": 0, "citations": [], "drafts": [], "questions": []}
    if use_anthropic:
        return await _run_anthropic(agent, subject, budget, meta)
    return await _run_openai(agent, subject, budget, seed, meta)


def _anchor(i: dict) -> str:
    """Only the fields the card carries; never prints None."""
    bits = [f"born {i['birth_year']}" if i.get("birth_year") else "", f"died {i['death_year']}" if i.get("death_year") else "",
            i.get("birth_place") or ""]
    bits = [b for b in bits if b]
    return f" ({', '.join(bits)})" if bits else ""


async def _run_openai(agent: str, subject: dict, budget: int, seed: int, meta: dict) -> dict:
    i = subject["input"]
    task = (f"Find records about {i['full_name']}{_anchor(i)}. "
            f"You may make at most {budget} tool calls. List every record you find with its URL. Do not invent records.")
    if agent == "B0":
        task += " This is a single pass: make all the searches you want in one step; you will not get a second turn."
    msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": task}]
    cits, calls, t0 = [], 0, time.time()
    usage = {"input": 0, "cached": 0, "output": 0, "model_calls": 0}
    price = PRICES.get(meta["config"]["model"], PRICES["gpt-4.1-mini"])
    usd, final_text, stop = 0.0, "", None
    async with httpx.AsyncClient(timeout=180) as c:
        for turn in range(1 if agent == "B0" else 200):
            if _spend() >= _cap():
                stop = "stopped: spend cap reached"
                break
            body = {"model": meta["config"]["model"], "max_tokens": 2000, "tools": _oa_tools(), "messages": msgs, "temperature": 1.0}
            if meta["config"]["api"] == "openai":
                body["seed"] = seed
            for attempt in range(5):
                r = await c.post(API_URLS[meta["config"]["api"]], json=body,
                                 headers={"Authorization": f"Bearer {os.environ[API_KEYS[meta['config']['api']]]}"})
                if r.status_code in (429, 500, 502, 503):
                    await asyncio_sleep(5 * (attempt + 1))
                    continue
                break
            r.raise_for_status()
            resp = r.json()
            u = resp.get("usage", {})
            cached = (u.get("prompt_tokens_details") or {}).get("cached_tokens", 0) or 0
            inp, out = u.get("prompt_tokens", 0) - cached, u.get("completion_tokens", 0)
            usage["input"] += inp; usage["cached"] += cached; usage["output"] += out; usage["model_calls"] += 1
            # xAI reports the billed cost itself (1 tick = 1e-10 USD); otherwise use list prices.
            cost = u["cost_in_usd_ticks"] / 1e10 if "cost_in_usd_ticks" in u else (inp * price[0] + cached * price[1] + out * price[2]) / 1e6
            usd += cost
            _spend(cost)
            m = resp["choices"][0]["message"]
            msgs.append({k: v for k, v in m.items() if k in ("role", "content", "tool_calls") and v is not None})
            uses = m.get("tool_calls") or []
            if not uses:
                final_text = m.get("content") or ""
                break
            if calls >= budget:
                break
            for tc in uses:
                if calls >= budget:
                    msgs.append({"role": "tool", "tool_call_id": tc["id"], "content": "budget spent"})
                    continue
                calls += 1
                try:
                    args = json.loads(tc["function"]["arguments"] or "{}")
                except json.JSONDecodeError:
                    args = {}
                text, cs = await _tool(tc["function"]["name"], args)
                cits += [{**x, "node": f"{agent}-call{calls}", "depth": 0, "call": calls} for x in cs]
                msgs.append({"role": "tool", "tool_call_id": tc["id"], "content": text[:TOOL_TEXT_CHARS]})
    if stop is None:
        stop = "model stopped" if calls < budget else f"Reached the {budget} tool-call budget."
    return {**meta, "completed": True, "stop_reason": stop, "tool_calls": calls, "llm_tokens": usage["input"] + usage["cached"] + usage["output"],
            "llm_usage": usage, "usd": round(usd, 6), "wall_seconds": round(time.time() - t0, 1), "citations": cits,
            "final_answer": final_text[:20000], "drafts": [], "questions": []}


async def asyncio_sleep(s: float):
    import asyncio
    await asyncio.sleep(s)


async def _run_anthropic(agent: str, subject: dict, budget: int, meta: dict) -> dict:
    i = subject["input"]
    task = (f"Find records about {i['full_name']}{_anchor(i)}. "
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
