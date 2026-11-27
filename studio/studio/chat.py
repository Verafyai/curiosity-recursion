"""Chat over the research graph. Answers only from the graph's own evidence and cites node ids.

Model: Claude through the Anthropic SDK when ANTHROPIC_API_KEY is set (CR_CHAT_MODEL, default claude-opus-5-5);
otherwise xAI when XAI_API_KEY is set (XAI_MODEL, OpenAI-style chat endpoint). With no key, the panel says how to
set one and falls back to a keyword match over the graph, labelled as such. Every cited id is checked against the
graph; ids the model invents are dropped and the answer says so.
"""
from __future__ import annotations

import json
import os
import re

import httpx
from pydantic import BaseModel, Field

from studio.explore import ExploreProgress

NO_KEY = ("No model key is set, so this is a keyword match over the graph, not an AI answer. To turn on chat, stop the web "
          "app and start it again with ANTHROPIC_API_KEY=sk-ant-... (or XAI_API_KEY=...) in its environment, for example: "
          "ANTHROPIC_API_KEY=sk-ant-... ../.venv/bin/uvicorn web.app:app --port 8090")

KW = "Keyword match over the graph, not an AI answer (no model key is set)."

SYSTEM = """You help a family historian read a research graph about one person who died long ago.
Answer ONLY from the evidence given (nodes with ids, citations and snippets). Cite every factual sentence with the
node ids it rests on, in square brackets, like [n3] or [person]. If the evidence does not answer the question, say
plainly that the graph does not show it yet, and suggest a research question that could. A shared surname alone is
never a family link; a record that only matches the surname is a "Possible" lead, never proof. Never invent records,
dates, places or people. Suggested questions must be researchable in public archives (digitised books, newspapers,
Wikidata) or name an offline holder; attach each to the node it follows from. No em-dashes."""


class Suggestion(BaseModel):
    node_id: str
    text: str


class ChatAnswer(BaseModel):
    answer: str
    cited: list[str] = Field(default_factory=list, description="Node ids the answer cites")
    known: bool = Field(description="False when the graph does not answer the question")
    suggestions: list[Suggestion] = Field(default_factory=list, max_length=4)


class ChatReply(ChatAnswer):
    model: str = ""
    note: str = ""


def evidence(p: ExploreProgress, limit: int = 80) -> str:
    out = []
    req = p.request
    if req:
        P = req.person
        out.append(f"[person] {P.full_name}, born {P.birth_year or '?'} {P.birth_place or ''}, died {P.death_year or '?'} {P.death_place or ''}. "
                   f"(This is what the user typed, tier told.)")
    for n in p.nodes[:limit]:
        if n.id == "person":
            continue
        cits = "; ".join(f"{c.title or ''} {c.url or ''} name_match={c.name_match or '?'}" for c in n.citations[:2])
        out.append(f"[{n.id}] ({n.kind}, tier {n.tier}, parent {n.parent_id}) {n.label}. {n.summary[:400]} Source: {cits}")
    for q in p.questions:
        if q.status in ("answered", "no_lead"):
            out.append(f"(question {q.id} on [{q.node_id}]: {q.text} -> {q.status}: {q.answer[:200]})")
    return "\n".join(out)


def _clean(a: ChatAnswer, p: ExploreProgress) -> tuple[ChatAnswer, str]:
    ids = {n.id for n in p.nodes}
    cited_in_text = re.findall(r"\[([a-z]+\d*|person)\]", a.answer)
    bad = sorted({c for c in [*a.cited, *cited_in_text] if c not in ids})
    note = ""
    if bad:
        for b in bad:
            a.answer = a.answer.replace(f"[{b}]", "")
        note = f"Dropped citation(s) to node ids that are not in the graph: {', '.join(bad)}."
    a.cited = sorted({c for c in [*a.cited, *cited_in_text] if c in ids})
    a.suggestions = [s for s in a.suggestions if s.node_id in ids and s.text.strip()][:4]
    a.answer = a.answer.replace("\u2014", ", ")  # no em-dashes in UI copy
    return a, note


def keyword_answer(question: str, p: ExploreProgress) -> ChatReply:
    words = {w for w in re.findall(r"[a-z]{4,}", question.lower())} - {"what", "where", "when", "which", "does", "there", "with", "about", "from", "that", "this", "have", "were"}
    hits = []
    for n in p.nodes:
        text = f"{n.label} {n.summary}".lower()
        score = sum(1 for w in words if w in text)
        if score:
            hits.append((score, n))
    hits.sort(key=lambda t: -t[0])
    opens = [q for q in p.questions if q.status == "open" and q.kind != "outreach"][:3]
    sugg = [Suggestion(node_id=q.node_id, text=q.text) for q in opens]
    if not hits:
        return ChatReply(answer="The graph does not show anything that matches this yet.", known=False, suggestions=sugg, model="keyword match", note=KW)
    lines = [f"{n.label[:120]} [{n.id}]" + (" (Possible)" if n.tier == "possible" else "") for _, n in hits[:4]]
    return ChatReply(answer="Nodes that mention this: " + "; ".join(lines), cited=[n.id for _, n in hits[:4]], known=True,
                     suggestions=sugg, model="keyword match", note=KW)


async def answer(question: str, p: ExploreProgress, history: list[dict] | None = None) -> ChatReply:
    ev = evidence(p)
    prompt = f"<graph>\n{ev}\n</graph>\n\nQuestion: {question}"
    msgs = [*(history or [])[-6:], {"role": "user", "content": prompt}]
    if os.environ.get("ANTHROPIC_API_KEY"):
        import anthropic
        model = os.environ.get("CR_CHAT_MODEL", "claude-opus-5-5")
        c = anthropic.AsyncAnthropic()
        r = await c.messages.parse(model=model, max_tokens=4000, system=SYSTEM, messages=msgs, output_format=ChatAnswer)
        if r.parsed_output is None:
            return ChatReply(answer="The model did not return an answer.", known=False, model=model, note=f"stop_reason={r.stop_reason}")
        a, note = _clean(r.parsed_output, p)
        return ChatReply(**a.model_dump(), model=model, note=note)
    if os.environ.get("XAI_API_KEY"):
        model = os.environ.get("XAI_MODEL", "grok-4")
        schema = json.dumps(ChatAnswer.model_json_schema())
        async with httpx.AsyncClient(timeout=60) as h:
            r = await h.post("https://api.x.ai/v1/chat/completions", headers={"Authorization": f"Bearer {os.environ['XAI_API_KEY']}"},
                             json={"model": model, "messages": [{"role": "system", "content": SYSTEM + "\nReply with JSON only, matching: " + schema}, *msgs],
                                   "response_format": {"type": "json_object"}})
            r.raise_for_status()
            a = ChatAnswer.model_validate_json(r.json()["choices"][0]["message"]["content"])
        a, note = _clean(a, p)
        return ChatReply(**a.model_dump(), model=model, note=note)
    return keyword_answer(question, p)


def key_status() -> dict:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return {"chat": "anthropic", "model": os.environ.get("CR_CHAT_MODEL", "claude-opus-5-5")}
    if os.environ.get("XAI_API_KEY"):
        return {"chat": "xai", "model": os.environ.get("XAI_MODEL", "grok-4")}
    return {"chat": "none", "message": NO_KEY}
