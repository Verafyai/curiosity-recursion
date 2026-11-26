"""B4: the same Curiosity Recursion code in a plain asyncio loop (H2's comparison).

Same activities, same generator, same budgets, same retry counts, but no Temporal: retries are
in-process, nothing is persisted between levels, timers are asyncio.sleep, and a crash loses the
run. Activities run under temporalio.testing.ActivityEnvironment only so they can read their
attempt number; no server is involved.
"""
from __future__ import annotations

import asyncio
import dataclasses
import os
import time
import uuid
from datetime import date

from temporalio.testing import ActivityEnvironment

from bench.common import commit, now, request_for, result_from_report
from cr import activities as a
from cr.circuits import CIRCUITS, STEPS
from cr.gate import gate
from cr.models import BrainstormInput, ComposeInput, InvestigateInput, Question, StepInput

ATTEMPTS, BACKOFF = 8, (2.0, 2.0, 30.0)  # same shape as LIVE_RETRY


async def _retry(fn, arg, wid: str, counter: dict):
    delay = BACKOFF[0]
    for attempt in range(1, ATTEMPTS + 1):
        env = ActivityEnvironment()
        env.info = dataclasses.replace(env.info, attempt=attempt, workflow_id=wid)
        counter["executions"] += 1
        try:
            return await env.run(fn, arg)
        except ValueError:
            raise
        except Exception:
            if attempt == ATTEMPTS:
                raise
            await asyncio.sleep(delay)
            delay = min(delay * BACKOFF[1], BACKOFF[2])


async def run(subject: dict, budget: int, seed: int, faults: dict) -> dict:
    if faults:
        os.environ["CR_FAULT_P"], os.environ["CR_FAULT_K"] = str(faults["p"]), str(faults["k"])
    req = request_for(subject, budget, mode="brainstorm")
    wid = f"plain-B4-{subject['subject_id']}-b{budget}-s{seed}-{uuid.uuid4().hex[:6]}"
    meta = dict(run_id=wid, agent="B4", config={"mode": "brainstorm", "durable": False}, subject_id=subject["subject_id"],
                budget=budget, seed=seed, commit=commit(), started_at=now(), faults=faults)
    t0, counter = time.time(), {"executions": 0, "calls": 0}
    try:
        g = gate(req.person, date.today().year)
        if not g.allowed:
            return {**meta, "completed": True, "stop_reason": "blocked by the living-person gate", "tool_calls": 0, "citations": [],
                    "drafts": [], "questions": []}
        circuit = CIRCUITS[req.circuit_id]
        ids = list(dict.fromkeys(["wikidata_identity", *[s for t in circuit.topics for s in t.steps]]))[:budget]
        counter["calls"] += len(ids)
        outs = await asyncio.gather(*[_retry(a.run_checklist_step, StepInput(request=req, step=STEPS[s], round=0), wid, counter)
                                      for s in ids], return_exceptions=True)
        findings = [f for o in outs if not isinstance(o, BaseException) for f in o.findings]
        questions: list[Question] = []
        bo = await _retry(a.brainstorm_questions, BrainstormInput(request=req, findings=findings, questions=[], round=1, top_n=req.breadth, depth=1), wid, counter)
        frontier, stop = list(bo.picked), "No new questions."
        questions += frontier
        while frontier:
            nxt: list[Question] = []
            for q in frontier:
                if counter["calls"] >= budget:
                    q.status, stop = "skipped", f"Reached the {budget} tool-call budget."
                    continue
                counter["calls"] += 1
                try:
                    out = await _retry(a.investigate, InvestigateInput(request=req, question=q), wid, counter)
                except Exception as e:
                    q.status, q.answer = "error", str(e)
                    continue
                questions[questions.index(q)] = out.question
                findings.append(out.finding)
                if out.question.depth < req.depth and out.question.status not in ("stub", "error"):
                    f = await _retry(a.brainstorm_questions, BrainstormInput(request=req, findings=[out.finding], questions=questions + nxt,
                                                                            round=1, top_n=req.breadth, node=out.question,
                                                                            depth=out.question.depth + 1), wid, counter)
                    known = {x.key for x in questions + nxt}
                    for fq in f.picked[: req.breadth + 2]:
                        if fq.key not in known and len(questions) + len(nxt) < req.max_nodes:
                            nxt.append(fq)
                            known.add(fq.key)
            questions += nxt
            frontier = nxt if counter["calls"] < budget else []
        rep = await _retry(a.compose_report, ComposeInput(request=req, gate=g, catalog=None, findings=findings, questions=questions, stop_reason=stop), wid, counter)
        line = result_from_report(rep, **meta)
        line.update(completed=True, wall_seconds=round(time.time() - t0, 1), tool_calls=counter["calls"],
                    activity_executions=counter["executions"], history_events=None)
        return line
    except Exception as e:
        return {**meta, "completed": False, "stop_reason": f"error: {type(e).__name__}: {e}", "tool_calls": counter["calls"],
                "wall_seconds": round(time.time() - t0, 1), "citations": [], "drafts": [], "questions": []}
