"""Grounding, dedupe and novelty for the question generators."""
import asyncio

from cr.generators import llm, rules
from cr.models import BrainstormInput, Citation, Finding, Person, Plan, Question, ResearchRequest, grounded
from cr.novelty import canonical_key, near_duplicate, novelty

P = Person(full_name="Erastus W. Burnham", name_variants=["Erastus Williams Burnham"], birth_year=1834, death_year=1921,
           birth_place="South Windsor, Connecticut")
ROSTER = Finding(step_id="r3.2", step_title="t", stage=5, source_slug="internet-archive", mode="live", status="found",
                 confidence="possible", citations=[Citation(
                     title="The Twelfth Regiment, Connecticut Volunteer Infantry in the War of the Rebellion", item_id="twelfthregimentc00conn",
                     url="https://archive.org/details/twelfthregimentc00conn", name_match="strong",
                     snippet="Private, Company A, 12th Connecticut Volunteer Infantry. **Burnham, Erastus W.** enlisted Dec. 28, 1861")])


def inp(req=None, questions=(), findings=(ROSTER,), node=None):
    return BrainstormInput(request=req or ResearchRequest(person=P), findings=list(findings), questions=list(questions),
                           round=1, top_n=3, node=node, depth=1)


def test_every_rule_question_is_grounded():
    out = rules.brainstorm(inp())
    assert out.picked
    assert all(grounded(q) for q in out.picked + out.held_back)
    assert all(q.because for q in out.picked)


def test_unit_finding_sparks_regiment_books():
    out = rules.brainstorm(inp())
    keys = [q.key for q in out.picked + out.held_back]
    assert any(k.startswith("unit-books:12th-connecticut-infantry") for k in keys)


def test_dedupe_against_memory():
    first = rules.brainstorm(inp())
    again = rules.brainstorm(inp(questions=first.picked + first.held_back))
    assert not {q.key for q in again.picked} & {q.key for q in first.picked}
    assert again.duplicates_skipped >= len(first.picked)


def test_dedupe_off_allows_repeats():
    first = rules.brainstorm(inp())
    req = ResearchRequest(person=P, dedupe=False)
    again = rules.brainstorm(inp(req=req, questions=first.picked))
    assert {q.key for q in again.picked} & {q.key for q in first.picked}


def test_verify_nodes_switch():
    node = Question(id="q1", key="k", round=1, text="Newspapers for him", because="because x", template="name->books",
                    parent_finding="x", plan=Plan(handler="chronam", query="Erastus Burnham"), status="answered",
                    citations=[Citation(title="paper", snippet="Burnham", name_match="surname_only")])
    on = rules.brainstorm(inp(node=node, findings=()))
    off = rules.brainstorm(inp(req=ResearchRequest(person=P, verify_nodes=False), node=node, findings=()))
    assert any(q.template == "node->are-you-sure" for q in on.picked)
    assert not any(q.template == "node->are-you-sure" for q in off.picked)


def test_canonical_key_and_novelty():
    assert canonical_key("unit-books", "12th Connecticut Infantry") == "unit-books:12th-connecticut-infantry"
    assert near_duplicate("Which books cover the 12th Connecticut Infantry?", ["Which books cover the 12th Connecticut Infantry, and do they name him?"])
    assert novelty("Is he in the South Windsor church register?", ["Which books cover the 12th Connecticut Infantry?"]) > 0.5


def test_llm_generator_rejects_ungrounded_output():
    async def fake(body):
        return {"usage": {"input_tokens": 100, "output_tokens": 50}, "content": [{"type": "text", "text": """{"questions": [
          {"text": "Which GAR post did he join after the war?", "spark_id": "r3.2#0", "quote": "12th Connecticut Volunteer Infantry",
           "handler": "chronam", "query": "Grand Army Republic Burnham South Windsor"},
          {"text": "Was he a Mason?", "spark_id": "r3.2#0", "quote": "member of the lodge", "handler": "chronam", "query": "lodge"},
          {"text": "Ask the town clerk", "spark_id": "nope", "quote": "x y z", "handler": "stub"},
          {"text": "Search inside", "spark_id": "r3.2#0", "quote": "Burnham, Erastus W.", "handler": "ia_inside", "query": "Burnham"}
        ]}"""}]}
    old = llm.call_model
    llm.call_model = fake
    try:
        qs, tokens, rejected = asyncio.run(llm.generate(inp(req=ResearchRequest(person=P, generator="llm"))))
    finally:
        llm.call_model = old
    assert tokens == 150
    assert [q.text for q in qs] == ["Which GAR post did he join after the war?"]
    assert rejected == 3  # quote not in spark, unknown spark, ia_inside without an item id
    assert all(grounded(q) for q in qs) and qs[0].because.startswith("because r3.2#0 says")


def test_llm_budget_is_a_hard_stop():
    req = ResearchRequest(person=P, generator="llm", llm_token_budget=10)
    i = inp(req=req)
    i.llm_tokens_used = 10
    calls = []

    async def fake(body):
        calls.append(body)
        return {}
    old = llm.call_model
    llm.call_model = fake
    try:
        assert asyncio.run(llm.generate(i)) is None
    finally:
        llm.call_model = old
    assert not calls
