"""curiosity-recursion web UI (local). FastAPI over the local Temporal server.

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

from cr.circuits import CIRCUITS
from cr.client import client, start
from cr.models import Decision, OutreachDecision, Progress, Redirect, ResearchRequest, StudioReport

HERE = Path(__file__).resolve().parent
app = FastAPI(title="curiosity-recursion (local)")
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
TEMPORAL_UI = "http://localhost:8233/namespaces/default/workflows"
LAST: dict[str, dict] = {}  # last progress seen per run, shown while the worker is down


@app.get("/", response_class=HTMLResponse)
async def home():
    return (HERE / "index.html").read_text()


@app.get("/run/{wid}", response_class=HTMLResponse)
async def run_page(wid: str):
    return (HERE / "run.html").read_text().replace("__WID__", wid)


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
    async for w in c.list_workflows("WorkflowType='CuriosityRecursionWorkflow'", limit=30):
        out.append({"workflow_id": w.id, "status": w.status.name if w.status else "", "start_time": w.start_time.isoformat() if w.start_time else None})
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
    try:
        cdesc = await c.get_workflow_handle(f"{wid}-checklist").describe()
        pending += _pending(cdesc)
    except RPCError:
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
        "pending": pending, "progress": progress, "worker_offline": offline,
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
