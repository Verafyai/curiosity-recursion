"""Durable timers and budgets under Temporal's time-skipping test server.

Level pauses of 3 days each are skipped, not slept, and the run still finishes with every level.
The activities are fakes with the real names, so no network is touched. Needs the Temporal test
server, which the SDK downloads on first use.
"""
import asyncio
import uuid
from datetime import timedelta

from temporalio import activity
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from cr.activities import compose_report
from cr.circuits import CIRCUITS
from cr.models import (BrainstormInput, BrainstormOutput, Finding, InvestigateInput, InvestigateOutput, PassInput, PersistInput,
                       Person, Plan, PriorInput, PriorQuestions, Question, ResearchRequest, StepInput, StepOutput, StudioReport)
from cr.workflow import ChecklistPassWorkflow, CuriosityRecursionWorkflow

CALLS = {"investigate": 0}


@activity.defn(name="load_prior_questions")
async def fake_prior(inp: PriorInput) -> PriorQuestions:
    return PriorQuestions(questions=[], runs=[])


@activity.defn(name="persist_run")
async def fake_persist(inp: PersistInput) -> int:
    return len(inp.questions)


@activity.defn(name="run_checklist_step")
async def fake_step(inp: StepInput) -> StepOutput:
    s = inp.step
    return StepOutput(findings=[Finding(step_id=s.id, step_title=s.title, stage=s.stage, source_slug=s.source_slug, mode=s.mode,
                                        status="nothing", confidence="none")])


@activity.defn(name="brainstorm_questions")
async def fake_brainstorm(inp: BrainstormInput) -> BrainstormOutput:
    parent = inp.node.id if inp.node else None
    qs = [Question(id=f"{parent}.{i}" if parent else f"q{i}", key=f"k-{parent}-{i}", round=inp.round, text=f"follow-up {i} of {parent}",
                   because=f"because {parent or 'checklist'} said so", template="test", parent_finding=parent or "checklist:level-0",
                   parent_id=parent or "root", depth=inp.depth, plan=Plan(handler="ia_fulltext", query="x")) for i in (1, 2)]
    return BrainstormOutput(round=inp.round, generated=2, duplicates_skipped=0, picked=qs)


@activity.defn(name="investigate")
async def fake_investigate(inp: InvestigateInput) -> InvestigateOutput:
    CALLS["investigate"] += 1
    q = inp.question.model_copy()
    q.status, q.answer, q.attempts = "answered", "a fake answer", 1
    return InvestigateOutput(question=q, finding=Finding(step_id=q.id, step_title=q.text, stage=6, source_slug="test", mode="live",
                                                          status="found", confidence="candidate", notes="fake"))


async def _run(req: ResearchRequest) -> tuple[StudioReport, float]:
    async with await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter) as env:
        tq = f"tq-{uuid.uuid4()}"
        async with Worker(env.client, task_queue=tq, workflows=[CuriosityRecursionWorkflow, ChecklistPassWorkflow],
                          activities=[fake_prior, fake_persist, fake_step, fake_brainstorm, fake_investigate, compose_report]):
            t0 = await env.get_current_time()
            rep = await env.client.execute_workflow(CuriosityRecursionWorkflow.run, req, id=f"ts-{uuid.uuid4()}", task_queue=tq)
            t1 = await env.get_current_time()
    return rep, (t1 - t0).total_seconds()


P = Person(full_name="Test Subject", birth_year=1840, death_year=1910)


def test_multi_day_pauses_are_durable_timers():
    req = ResearchRequest(person=P, depth=3, breadth=2, max_nodes=80, level_pause_seconds=3 * 24 * 3600,
                          require_approval=False, simulate_flaky_archives=False, max_run_minutes=60 * 24 * 30)
    rep, skipped = asyncio.run(_run(req))
    assert len(rep.questions) == 2 + 4 + 8
    assert skipped >= 2 * 3 * 24 * 3600  # two 3-day pauses passed in test time
    assert rep.stop_reason.startswith("No new questions")


def test_tool_call_budget_stops_the_run():
    req = ResearchRequest(person=P, depth=4, breadth=2, max_nodes=80, level_pause_seconds=0, require_approval=False,
                          simulate_flaky_archives=False, max_tool_calls=25)
    CALLS["investigate"] = 0
    rep, _ = asyncio.run(_run(req))
    circuit = CIRCUITS[req.circuit_id]
    steps = len(dict.fromkeys(["wikidata_identity", *[s for t in circuit.topics for s in t.steps]]))
    assert CALLS["investigate"] == 25 - steps  # B counts checklist steps plus investigations
    assert "tool-call budget" in rep.stop_reason
    assert any(q.status == "skipped" for q in rep.questions)


def test_living_subject_never_runs_an_activity():
    CALLS["investigate"] = 0
    rep, _ = asyncio.run(_run(ResearchRequest(person=Person(full_name="Jane Example", birth_year=1950), require_approval=False)))
    assert rep.decision == "blocked" and CALLS["investigate"] == 0 and not rep.questions
