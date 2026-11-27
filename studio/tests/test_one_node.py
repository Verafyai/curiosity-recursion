"""Reproduces the "Erastus run shows one node" bug in Brainstorm mode.

Root cause: StudioRunWorkflow runs the whole 16-step checklist as one ChecklistPassWorkflow child and only copies the
findings into its own progress after the child returns. For the 35 to 45 seconds the child runs (live archives are
slow), the parent's progress query has no findings, no questions and no levels with results, so the run page draws a
single person node with no spinner and a frozen log. The child had no query, so nothing could show its steps.

Fix: ChecklistPassWorkflow.steps (a query; adds no commands, so old histories replay) and the web app merges it into
the run payload. On the old code this test fails at the `steps` query.

    cd studio && ../.venv/bin/python -m pytest -q tests/test_one_node.py
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
from temporalio.contrib.pydantic import pydantic_data_converter  # noqa: E402
from temporalio.testing import WorkflowEnvironment  # noqa: E402
from temporalio.worker import Worker  # noqa: E402

from studio.models import (  # noqa: E402
    CatalogSnapshot, Finding, PersistInput, Person, PriorInput, PriorQuestions, ResearchRequest, StepInput, StepOutput,
)
from studio.workflows import ChecklistPassWorkflow, StudioRunWorkflow  # noqa: E402

TEMPORAL = shutil.which("temporal")
pytestmark = pytest.mark.skipif(TEMPORAL is None, reason="needs the temporal CLI")
RELEASE: asyncio.Event | None = None
FAST = {"wikidata_identity", "service_roster", "vital_death"}


@activity.defn(name="load_catalog")
async def fake_catalog() -> CatalogSnapshot:
    return CatalogSnapshot(endpoint="test", source_count=0, sources=[])


@activity.defn(name="load_prior_questions")
async def fake_prior(inp: PriorInput) -> PriorQuestions:
    return PriorQuestions(questions=[], runs=[])


@activity.defn(name="persist_run")
async def fake_persist(inp: PersistInput) -> None:
    return None


@activity.defn(name="run_checklist_step")
async def slow_step(inp: StepInput) -> StepOutput:
    """A few steps answer at once; the rest wait, like live archives that take 30 to 45 seconds."""
    if inp.step.id not in FAST:
        await RELEASE.wait()
    return StepOutput(findings=[Finding(step_id=inp.step.id, step_title=inp.step.title, stage=inp.step.stage, source_slug="t",
                                        mode=inp.step.mode, status="nothing", confidence="none")])


def test_checklist_steps_visible_while_the_child_runs():
    asyncio.run(_run())


async def _run():
    global RELEASE
    RELEASE = asyncio.Event()
    async with await WorkflowEnvironment.start_local(data_converter=pydantic_data_converter, dev_server_existing_path=TEMPORAL,
                                                     dev_server_extra_args=["--log-level", "error"]) as env:
        tq = f"onenode-{uuid.uuid4().hex[:6]}"
        async with Worker(env.client, task_queue=tq, workflows=[StudioRunWorkflow, ChecklistPassWorkflow],
                          activities=[fake_catalog, fake_prior, fake_persist, slow_step]):
            req = ResearchRequest(person=Person(full_name="Erastus W. Burnham", birth_year=1834, death_year=1921), mode="brainstorm")
            wid = f"run-{tq}"
            h = await env.client.start_workflow(StudioRunWorkflow.run, req, id=wid, task_queue=tq)
            child = env.client.get_workflow_handle(f"{wid}-checklist")
            steps = []
            for _ in range(100):
                await asyncio.sleep(0.1)
                try:
                    steps = await child.query("steps")
                except Exception as e:  # the old code has no such query: this is the bug
                    if "not found" in str(e).lower() or "unknown" in str(e).lower() or "query" in str(e).lower():
                        last = e
                        continue
                    raise
                if sum(1 for s in steps if s["state"] not in ("queued", "running")) >= len(FAST):
                    break
            else:
                raise AssertionError(f"checklist child exposes no step progress: {last}")
            parent = await h.query(StudioRunWorkflow.progress)
            # The parent alone still shows nothing found yet: that is why the page drew one node.
            assert parent.status == "checklist" and not parent.findings
            # The child query is what the run page now shows: every step, with the ones still running marked.
            states = {s["id"]: s["state"] for s in steps}
            assert len(states) == parent.steps_total >= 10
            assert {states[i] for i in FAST} == {"nothing"}
            assert "running" in states.values()
            RELEASE.set()
            await h.terminate("test done")
