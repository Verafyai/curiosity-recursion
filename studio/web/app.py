"""Lineage Studio Builder (local). FastAPI over the local Temporal server.

Run: .venv/bin/uvicorn web.app:app --port 8090
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from temporalio.client import WorkflowExecutionStatus
from temporalio.service import RPCError

from studio.circuits import CIRCUITS
from studio.client import client, start
from studio.models import Decision, OutreachDecision, Progress, Redirect, ResearchRequest, StudioReport

HERE = Path(__file__).resolve().parent
app = FastAPI(title="Lineage Studio Builder (local)")
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
TEMPORAL_UI = "http://localhost:8233/namespaces/default/workflows"
LAST: dict[str, dict] = {}  # last progress seen per run, shown while the worker is down


@app.get("/", response_class=HTMLResponse)
async def home():
    return (HERE / "index.html").read_text()


@app.get("/run/{wid}", response_class=HTMLResponse)
async def run_page(wid: str):
    page = "run.html"
    try:
        d = await (await client()).get_workflow_handle(wid).describe()
        if d.workflow_type == "ExploreRunWorkflow":
            page = "explore.html"
    except RPCError:
        pass
    return (HERE / page).read_text().replace("__WID__", wid)


@app.get("/api/circuits")
async def circuits():
    return [{"id": c.id, "title": c.title, "template": c.template, "blurb": c.blurb} for c in CIRCUITS.values()]


@app.post("/api/runs")
async def create(req: ResearchRequest):
    if req.outreach == "automate":
        req.outreach = "ask_first"  # not enabled in the local demo: every request waits for approval
    wid = await start(req)
    return {"workflow_id": wid, "url": f"/run/{wid}"}


@app.get("/api/runs")
async def runs():
    c = await client()
    out = []
    async for w in c.list_workflows("WorkflowType='StudioRunWorkflow' OR WorkflowType='ExploreRunWorkflow'", limit=30):
        out.append({"workflow_id": w.id, "status": w.status.name if w.status else "", "type": w.workflow_type,
                    "start_time": w.start_time.isoformat() if w.start_time else None})
        if len(out) >= 30:
            break
    return out


def _pending(desc) -> list[dict]:
    out = []
    for pa in desc.raw_description.pending_activities:
        out.append({
            "activity_id": pa.activity_id, "type": pa.activity_type.name, "attempt": pa.attempt,
            "maximum_attempts": pa.maximum_attempts, "state": pa.state,
            "last_failure": pa.last_failure.message if pa.HasField("last_failure") else "",
        })
    return out


@app.get("/api/runs/{wid}")
async def run_state(wid: str):
    c = await client()
    h = c.get_workflow_handle(wid)
    try:
        desc = await h.describe()
    except RPCError as e:
        raise HTTPException(404, str(e))
    pending = _pending(desc)
    checklist_steps = []
    try:
        ch = c.get_workflow_handle(f"{wid}-checklist")
        cdesc = await ch.describe()
        pending += _pending(cdesc)
        if cdesc.status == WorkflowExecutionStatus.RUNNING:  # the one-node fix: show the checklist while it runs
            checklist_steps = await asyncio.wait_for(ch.query("steps"), timeout=1.5)
    except Exception:  # no child yet, or an old run whose code had no steps query
        pass
    progress, offline = None, False
    try:
        p = await asyncio.wait_for(h.query("progress", result_type=Progress), timeout=1.5)
        progress = p.model_dump(mode="json")
        LAST[wid] = progress
    except Exception as e:  # no worker to answer the query, or closed: fall back
        offline = desc.status == WorkflowExecutionStatus.RUNNING
        progress = LAST.get(wid)
        if progress is None and desc.status == WorkflowExecutionStatus.COMPLETED:
            rep = await h.result(result_type=StudioReport)
            progress = {"status": rep.decision, "report": rep.model_dump(mode="json"), "questions": [q.model_dump(mode="json") for q in rep.questions], "log": [str(e)]}
    return JSONResponse({
        "workflow_id": wid, "run_id": desc.run_id, "execution_status": desc.status.name if desc.status else "",
        "history_length": desc.raw_description.workflow_execution_info.history_length,
        "temporal_url": f"{TEMPORAL_UI}/{wid}/{desc.run_id}/history",
        "pending": pending, "progress": progress, "worker_offline": offline, "checklist_steps": checklist_steps,
    })


async def _signal(wid: str, name: str, arg):
    c = await client()
    await c.get_workflow_handle(wid).signal(name, arg)
    return {"ok": True}


@app.post("/api/runs/{wid}/approve")
async def approve(wid: str, d: Decision):
    return await _signal(wid, "approve", d)


@app.post("/api/runs/{wid}/reject")
async def reject(wid: str, d: Decision):
    return await _signal(wid, "reject", d)


@app.post("/api/runs/{wid}/redirect")
async def redirect(wid: str, r: Redirect):
    return await _signal(wid, "redirect", r)


@app.post("/api/runs/{wid}/outreach")
async def outreach(wid: str, d: OutreachDecision):
    return await _signal(wid, "outreach_decision", d)


# ====================================================================== Explore mode (interactive graph)
import json  # noqa: E402
import os  # noqa: E402
from datetime import date  # noqa: E402

from fastapi import Request  # noqa: E402
from fastapi.responses import PlainTextResponse, StreamingResponse  # noqa: E402
from pydantic import BaseModel  # noqa: E402
from temporalio.client import WorkflowUpdateFailedError  # noqa: E402

from studio import chat as chatmod  # noqa: E402
from studio import export as exportmod  # noqa: E402
from studio.client import start_explore  # noqa: E402
from studio.explore import AddCmd, EditCmd, ExploreProgress, NodeCmd, QuestionCmd, ResearchCmd, gate  # noqa: E402
from studio.explore_workflows import ExploreRunWorkflow  # noqa: E402

CONFIRM_OVER = int(os.environ.get("STUDIO_CONFIRM_OVER_CALLS", "2"))
CALL_BUDGET = int(os.environ.get("STUDIO_CALL_BUDGET", "100"))


class ExploreCreate(BaseModel):
    request: ResearchRequest
    call_budget: int | None = None
    confirm_over_calls: int | None = None


@app.get("/api/config")
async def config():
    return {"confirm_over_calls": CONFIRM_OVER, "call_budget": CALL_BUDGET, **chatmod.key_status()}


@app.post("/api/explore")
async def explore_create(body: ExploreCreate):
    g = gate(body.request.person, date.today().year)
    if not g.allowed:  # blocked in the UI before anything starts; the workflow checks again
        raise HTTPException(400, f"{g.reason} {g.rule}")
    body.request.mode = "explore"
    body.request.outreach = "ask_first"
    wid = await start_explore(body.request, body.call_budget or CALL_BUDGET, body.confirm_over_calls or CONFIRM_OVER)
    return {"workflow_id": wid, "url": f"/run/{wid}"}


async def _explore(wid: str) -> ExploreProgress:
    c = await client()
    try:
        return await asyncio.wait_for(c.get_workflow_handle(wid).query(ExploreRunWorkflow.progress), timeout=2.0)
    except RPCError as e:
        raise HTTPException(404, str(e))
    except asyncio.TimeoutError:
        raise HTTPException(503, "the Studio worker is not answering; start it with ../.venv/bin/python worker.py")


async def _pending_all(c, wid: str, p: ExploreProgress) -> list[dict]:
    out = []
    for pi in p.passes:
        if pi.state != "running":
            continue
        try:
            d = await c.get_workflow_handle(f"{wid}-{pi.id}").describe()
            out += [dict(x, pass_id=pi.id, question_id=pi.question_id) for x in _pending(d)]
        except RPCError:
            pass
    return out


@app.get("/api/explore/{wid}")
async def explore_state(wid: str):
    c = await client()
    p = await _explore(wid)
    return {"progress": p.model_dump(mode="json"), "pending": await _pending_all(c, wid, p),
            "budget_left": p.call_budget - p.calls_used, "temporal_url": f"{TEMPORAL_UI}/{wid}"}


async def _update(wid: str, upd, arg=None):
    c = await client()
    h = c.get_workflow_handle(wid)
    try:
        return await (h.execute_update(upd, arg) if arg is not None else h.execute_update(upd))
    except WorkflowUpdateFailedError as e:
        msg = str(e.cause.message if getattr(e.cause, "message", None) else e.cause or e)
        code = 409 if msg.startswith("confirm required") else 400
        raise HTTPException(code, msg)
    except RPCError as e:
        raise HTTPException(404, str(e))


@app.post("/api/explore/{wid}/research")
async def x_research(wid: str, cmd: ResearchCmd):
    return await _update(wid, ExploreRunWorkflow.research, cmd)


@app.post("/api/explore/{wid}/retry")
async def x_retry(wid: str, cmd: QuestionCmd):
    return await _update(wid, ExploreRunWorkflow.retry, cmd)


@app.post("/api/explore/{wid}/skip")
async def x_skip(wid: str, cmd: QuestionCmd):
    return await _update(wid, ExploreRunWorkflow.skip, cmd)


@app.post("/api/explore/{wid}/edit")
async def x_edit(wid: str, cmd: EditCmd):
    return await _update(wid, ExploreRunWorkflow.edit, cmd)


@app.post("/api/explore/{wid}/questions")
async def x_add(wid: str, cmd: AddCmd):
    return await _update(wid, ExploreRunWorkflow.add_question, cmd)


@app.post("/api/explore/{wid}/dig")
async def x_dig(wid: str, cmd: NodeCmd):
    return await _update(wid, ExploreRunWorkflow.dig_deeper, cmd)


@app.post("/api/explore/{wid}/outreach-draft")
async def x_draft(wid: str, cmd: QuestionCmd):
    return await _update(wid, ExploreRunWorkflow.draft_outreach, cmd)


@app.post("/api/explore/{wid}/compose")
async def x_compose(wid: str):
    return await _update(wid, ExploreRunWorkflow.compose)


@app.get("/api/explore/{wid}/events")
async def x_events(wid: str, request: Request, after: int = 0):
    """Server-sent events: one `state` event whenever the graph changes (seq), plus `log` lines and live `activity`
    lines (attempt numbers and the last failure of retrying searches)."""
    c = await client()

    async def gen():
        seq, sent_log, last_pending = -1, after, ""
        while not await request.is_disconnected():
            try:
                p = await asyncio.wait_for(c.get_workflow_handle(wid).query(ExploreRunWorkflow.progress), timeout=2.0)
            except Exception as e:  # worker down: say so and keep trying
                yield f"event: offline\ndata: {json.dumps({'error': str(e)[:200]})}\n\n"
                await asyncio.sleep(2)
                continue
            for line in p.log[sent_log:]:
                yield f"event: log\ndata: {json.dumps({'line': line})}\n\n"
            sent_log = len(p.log)
            pend = await _pending_all(c, wid, p)
            ps = json.dumps(pend, sort_keys=True, default=str)
            if ps != last_pending:
                last_pending = ps
                for x in pend:
                    if x["attempt"] > 1:
                        yield f"event: activity\ndata: {json.dumps({'line': f'Retrying {x['type']} for {x['question_id']} (attempt {x['attempt']}): {x['last_failure'][:160]}'})}\n\n"
                yield f"event: pending\ndata: {ps}\n\n"
            if p.seq != seq:
                seq = p.seq
                yield f"event: state\ndata: {json.dumps({'progress': p.model_dump(mode='json'), 'budget_left': p.call_budget - p.calls_used})}\n\n"
            if p.status in ("approved", "rejected", "blocked_living"):
                yield "event: end\ndata: {}\n\n"
                return
            await asyncio.sleep(0.4)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


class ChatIn(BaseModel):
    question: str
    history: list[dict] = []


@app.post("/api/explore/{wid}/chat")
async def x_chat(wid: str, body: ChatIn):
    p = await _explore(wid)
    try:
        return (await chatmod.answer(body.question, p, body.history)).model_dump()
    except Exception as e:  # a model or network error is shown in the panel, never hidden
        raise HTTPException(502, f"chat failed: {type(e).__name__}: {str(e)[:300]}")


@app.get("/api/explore/{wid}/export")
async def x_export(wid: str, fmt: str = "json"):
    p = await _explore(wid)
    if fmt == "json":
        return JSONResponse(exportmod.to_json(p), headers={"Content-Disposition": f'attachment; filename="{wid}.graph.json"'})
    if fmt == "graphml":
        return PlainTextResponse(exportmod.to_graphml(p), media_type="application/xml", headers={"Content-Disposition": f'attachment; filename="{wid}.graphml"'})
    if fmt == "mermaid":
        return PlainTextResponse(exportmod.to_mermaid(p), headers={"Content-Disposition": f'attachment; filename="{wid}.mmd"'})
    raise HTTPException(400, "fmt must be json, graphml or mermaid")
