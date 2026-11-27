"""Explore mode: workflow behavior, a replay test for the new updates and child workflows, and the one-node repro.

Runs on a throwaway local Temporal dev server (the installed `temporal` CLI), with the network activities replaced
by deterministic fakes. The rules brainstorm (seed_questions) is the real one.

    cd studio && ../.venv/bin/python -m pytest -q tests/test_explore.py
"""
from __future__ import annotations

import asyncio
import shutil
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from temporalio import activity  # noqa: E402
from temporalio.client import WorkflowUpdateFailedError  # noqa: E402
from temporalio.contrib.pydantic import pydantic_data_converter  # noqa: E402
from temporalio.testing import WorkflowEnvironment  # noqa: E402
from temporalio.worker import Replayer, Worker  # noqa: E402

from studio.explore import AddCmd, EditCmd, ExploreProgress, NodeCmd, QuestionCmd, ResearchCmd  # noqa: E402
from studio.activities import compose_report  # noqa: E402  (pure: writes the draft from findings, no network)
from studio.explore_activities import seed_questions  # noqa: E402
from studio.fakes import fake_investigate, fake_step  # noqa: E402
from studio.explore_workflows import ExploreInput, ExploreRunWorkflow, ResearchPassWorkflow  # noqa: E402
from studio.models import (  # noqa: E402
    Citation, Claim, Decision, Finding, InvestigateInput, InvestigateOutput, OutreachDecision, OutreachDraft, Person,
    ResearchRequest, StepInput, StepOutput, StudioReport,
)

TEMPORAL = shutil.which("temporal")
pytestmark = pytest.mark.skipif(TEMPORAL is None, reason="needs the temporal CLI")

ERASTUS = Person(full_name="Erastus W. Burnham", name_variants=["Erastus Burnham", "E. W. Burnham"], birth_year=1834,
                 birth_place="South Windsor, Connecticut", death_year=1921)


@activity.defn(name="export_outreach")
async def fake_export(d: OutreachDraft) -> OutreachDraft:
    return d.model_copy(update={"exported_to": "/tmp/not-sent.txt"})


async def wait_for(h, pred, timeout=20.0) -> ExploreProgress:
    end = asyncio.get_event_loop().time() + timeout
    while True:
        p = await h.query(ExploreRunWorkflow.progress)
        if pred(p):
            return p
        if asyncio.get_event_loop().time() > end:
            raise AssertionError(f"timed out; status={p.status} log={p.log[-3:]}")
        await asyncio.sleep(0.2)


def qs_of(p: ExploreProgress, nid: str):
    return [q for q in p.questions if q.node_id == nid]


async def _env():
    return await WorkflowEnvironment.start_local(data_converter=pydantic_data_converter, dev_server_existing_path=TEMPORAL,
                                                 dev_server_extra_args=["--log-level", "error"])


def test_explore_three_levels_dig_deeper_add_outreach_and_replay():
    asyncio.run(_three_levels())


async def _three_levels():
    async with await _env() as env:
        tq = f"explore-{uuid.uuid4().hex[:6]}"
        async with Worker(env.client, task_queue=tq, workflows=[ExploreRunWorkflow, ResearchPassWorkflow],
                          activities=[seed_questions, fake_investigate, fake_step, compose_report, fake_export]):
            req = ResearchRequest(person=ERASTUS, mode="explore", simulate_flaky_archives=False)
            h = await env.client.start_workflow(ExploreRunWorkflow.run, ExploreInput(request=req), id=f"x-{tq}", task_queue=tq)
            # 1. the person node shows its brainstormed questions within seconds, each labelled with its generator
            p = await wait_for(h, lambda p: p.status == "exploring", timeout=10)
            person_qs = qs_of(p, "person")
            assert len(p.nodes) == 1 and len(person_qs) >= 5
            assert {q.generator for q in person_qs} >= {"rules", "rules:checklist"}
            assert all(q.status == "open" for q in person_qs), "nothing runs until the user clicks"
            # 2. research three levels deep
            node = "person"
            q = next(q for q in person_qs if q.kind == "research" and q.plan and q.plan.handler == "ia_fulltext")
            for level in (1, 2, 3):
                await h.execute_update(ExploreRunWorkflow.research, ResearchCmd(question_id=q.id, confirmed=True))
                p = await wait_for(h, lambda p, qid=q.id: next(x for x in p.questions if x.id == qid).status in ("answered", "no_lead", "failed"))
                done = next(x for x in p.questions if x.id == q.id)
                assert done.status == "answered" and done.produced, done
                kids = [n for n in p.nodes if n.parent_id == node]
                assert kids and all(n.depth == level for n in kids)
                assert any(n.tier == "possible" for n in kids)
                assert any("surname only" in n.label for n in kids), "a surname-only hit is labelled, never treated as kin"
                node = kids[0].id
                nxt = [x for x in qs_of(p, node) if x.kind == "research" and x.status == "open" and x.est_calls <= 3]
                assert nxt, f"level {level} node has no questions of its own"
                q = nxt[0]
            # 3. dig deeper on the leaf: new questions, none repeating a key already asked on the path
            leaf = node
            before_keys = [x.key for x in p.questions]
            await h.execute_update(ExploreRunWorkflow.dig_deeper, NodeCmd(node_id=leaf))
            p = await wait_for(h, lambda p: any(x.generator == "rules:dig-deeper" and x.node_id == leaf for x in p.questions))
            deep = [x for x in p.questions if x.generator == "rules:dig-deeper" and x.node_id == leaf]
            assert not set(x.key for x in deep) & set(before_keys)
            assert len(set(x.key for x in p.questions)) == len(p.questions), "no question key is repeated"
            # 4. add a question, edit one, skip one
            r = await h.execute_update(ExploreRunWorkflow.add_question, AddCmd(node_id=leaf, text="Was he at Port Hudson in 1863?"))
            p = await h.query(ExploreRunWorkflow.progress)
            added = next(x for x in p.questions if x.id == r["question_id"])
            assert added.generator == "user" and added.kind == "research"
            await h.execute_update(ExploreRunWorkflow.research, ResearchCmd(question_id=added.id, confirmed=True))
            await wait_for(h, lambda p: next(x for x in p.questions if x.id == added.id).status == "answered")
            r = await h.execute_update(ExploreRunWorkflow.edit, EditCmd(question_id=deep[0].id, text="Is E. W. Burnham in the 1870 census?"))
            p = await h.query(ExploreRunWorkflow.progress)
            assert next(x for x in p.questions if x.id == r["question_id"]).edited_from == deep[0].id
            await h.execute_update(ExploreRunWorkflow.skip, QuestionCmd(question_id=deep[1].id))
            # 5. validation: an unconfirmed expensive pass is refused; an offline question cannot be researched
            pricey = next((x for x in p.questions if x.status == "open" and x.est_calls > 1 and x.kind == "research"), None)
            if pricey:
                h2 = await h.query(ExploreRunWorkflow.progress)
                if pricey.est_calls > h2.confirm_over_calls:
                    with pytest.raises(WorkflowUpdateFailedError):
                        await h.execute_update(ExploreRunWorkflow.research, ResearchCmd(question_id=pricey.id))
            off = next(x for x in p.questions if x.kind == "outreach")
            with pytest.raises(WorkflowUpdateFailedError):
                await h.execute_update(ExploreRunWorkflow.research, ResearchCmd(question_id=off.id, confirmed=True))
            # 6. outreach: drafted, held, approved to a local file, never sent
            r = await h.execute_update(ExploreRunWorkflow.draft_outreach, QuestionCmd(question_id=off.id))
            p = await h.query(ExploreRunWorkflow.progress)
            d = next(o for o in p.outreach if o.id == r["draft_id"])
            assert d.status == "awaiting_approval"
            assert next(n for n in p.nodes if n.id == off.node_id).state == "waiting_approval"
            await h.signal(ExploreRunWorkflow.outreach_decision, OutreachDecision(draft_id=d.id, approve=True))
            p = await wait_for(h, lambda p: next(o for o in p.outreach if o.id == d.id).status == "approved")
            # 7. compose, approve, finish
            await h.execute_update(ExploreRunWorkflow.compose)
            await wait_for(h, lambda p: p.status == "awaiting_approval")
            await h.signal(ExploreRunWorkflow.approve, Decision(approve=True, note="ok", by="test"))
            final = await h.result()
            assert final.status == "approved"
            # 8. replay: the parent and every child history replay against the current code without nondeterminism
            replayer = Replayer(workflows=[ExploreRunWorkflow, ResearchPassWorkflow], data_converter=pydantic_data_converter)
            await replayer.replay_workflow(await h.fetch_history())
            n = 0
            async for w in env.client.list_workflows(f"WorkflowType='ResearchPassWorkflow'"):
                await replayer.replay_workflow(await env.client.get_workflow_handle(w.id, run_id=w.run_id).fetch_history())
                n += 1
            assert n >= 4


def test_living_person_is_blocked_before_any_question():
    asyncio.run(_living())


async def _living():
    async with await _env() as env:
        tq = f"explore-{uuid.uuid4().hex[:6]}"
        async with Worker(env.client, task_queue=tq, workflows=[ExploreRunWorkflow, ResearchPassWorkflow],
                          activities=[seed_questions, fake_investigate, fake_step, compose_report, fake_export]):
            req = ResearchRequest(person=Person(full_name="Someone Recent", birth_year=1980), mode="explore")
            p = await env.client.execute_workflow(ExploreRunWorkflow.run, ExploreInput(request=req), id=f"x-{tq}", task_queue=tq)
            assert p.status == "blocked_living" and not p.questions and "presumed living" in p.gate.reason
