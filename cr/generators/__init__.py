"""The question generator g(s, R, v, M), behind one activity signature.

- rules  (default): cr/generators/rules.py, lead templates, no model, no key.
- llm:    cr/generators/llm.py, a grounded model generator. The rules' "Are you sure?" and
          "Where else might this be?" questions stay as a floor on every node, and the rules
          take over completely if the model is unavailable or the token budget is spent.
- hybrid: rules plus model questions, deduped against each other and against memory.
"""
from __future__ import annotations

from cr.generators import llm, rules
from cr.models import BrainstormInput, BrainstormOutput, Question
from cr.novelty import near_duplicate

FLOOR = ("node->are-you-sure", "node->where-else")


def _renumber(inp: BrainstormInput, picked: list[Question]) -> list[Question]:
    for i, q in enumerate(picked, 1):
        q.id = f"{inp.node.id}.{i}" if inp.node is not None else f"q{i}"
        q.parent_id = inp.node.id if inp.node is not None else "root"
        q.parent_question = inp.node.id if inp.node is not None else q.parent_question
        q.depth, q.round = inp.depth, inp.round
    return picked


async def generate(inp: BrainstormInput) -> BrainstormOutput:
    base = rules.brainstorm(inp)
    mode = inp.request.generator
    if mode == "rules":
        return base
    got = await llm.generate(inp)
    if got is None:  # no key, budget spent, or the call failed: rules only, said in the counts
        return base
    model_qs, tokens, rejected = got
    pool = base.picked + base.held_back
    floor = [q for q in pool if q.template in FLOOR]
    rule_live = [q for q in pool if q.plan.handler != "stub" and q.template not in FLOOR]
    stubs = [q for q in base.picked if q.plan.handler == "stub"]
    texts = [q.text for q in inp.questions]
    fresh_model: list[Question] = []
    for q in model_qs:
        if near_duplicate(q.text, texts + [x.text for x in fresh_model + floor + (rule_live if mode == "hybrid" else [])]):
            continue
        fresh_model.append(q)
    b = inp.top_n
    if mode == "llm":
        live = fresh_model[:b] + floor[:2]
    else:  # hybrid: best of both by score, floor kept
        ranked = sorted(fresh_model + rule_live, key=lambda q: -q.score)
        live = ranked[:b] + floor[:2]
    seen, picked = set(), []
    for q in live + stubs[:2]:
        if q.key not in seen:
            seen.add(q.key)
            picked.append(q)
    return BrainstormOutput(round=inp.round, generated=base.generated + len(model_qs) + rejected,
                            duplicates_skipped=base.duplicates_skipped + (len(model_qs) - len(fresh_model)),
                            ungrounded_rejected=base.ungrounded_rejected + rejected, llm_tokens=tokens,
                            picked=_renumber(inp, picked), held_back=[q for q in fresh_model if q not in picked][:12])
