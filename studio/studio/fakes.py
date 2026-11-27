"""Deterministic stand-ins for the network activities, for tests and offline demos (STUDIO_FAKE_SOURCES=1).

They return the same shapes as studio.activities.investigate and run_checklist_step. Every record they return is
marked as a test fixture in its title, so a fake run can never be mistaken for real research.
"""
from __future__ import annotations

import asyncio
import os

from temporalio import activity

from studio.models import Citation, Claim, Finding, InvestigateInput, InvestigateOutput, StepInput, StepOutput

DELAY = float(os.environ.get("STUDIO_FAKE_DELAY", "0"))


@activity.defn(name="investigate")
async def fake_investigate(inp: InvestigateInput) -> InvestigateOutput:
    if DELAY:
        await asyncio.sleep(DELAY)
    q = inp.question.model_copy(deep=True)
    who = inp.request.person.full_name
    n = len(q.id) % 3
    cits = [Citation(title=f"[TEST FIXTURE] Regimental history {q.id}, page image {7 + n}", url=f"https://archive.org/details/fixture{n}/page/n{7 + n}",
                     archive="Internet Archive", item_id=f"fixture{n}",
                     snippet=f"{who}, enlisted in the 12th Connecticut Infantry (test fixture text)", name_match="strong"),
            Citation(title=f"[TEST FIXTURE] Newspaper page {q.id}", url=f"https://www.loc.gov/item/fixture{n}/",
                     snippet=f"Mr. {who.split()[-1]} of Hartford (test fixture text)", name_match="surname_only")]
    q.status, q.answer, q.citations, q.attempts = "answered", "1 of 2 hits print the name in full (test fixture).", cits, 1
    f = Finding(step_id=q.id, step_title=q.text, stage=5, source_slug="fixture", mode="stub", status="found", confidence="possible",
                citations=cits, notes=q.answer)
    return InvestigateOutput(question=q, finding=f)


@activity.defn(name="run_checklist_step")
async def fake_step(inp: StepInput) -> StepOutput:
    if DELAY:
        await asyncio.sleep(DELAY)
    c = Citation(title="[TEST FIXTURE] Record of Service", url="https://example.org/fixture-roster")
    return StepOutput(findings=[Finding(step_id=inp.step.id, step_title=inp.step.title, stage=inp.step.stage, source_slug="fixture", mode="stub",
                                        status="found", confidence="documented",
                                        claims=[Claim(id="c1", field="military", text="Served in the 12th Connecticut Infantry, Company B (test fixture).",
                                                      tier="documented", citation=c, origin="fixture:test")],
                                        citations=[c], notes="test fixture")])
