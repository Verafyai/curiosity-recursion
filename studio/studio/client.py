"""Shared Temporal client helpers for the web app and scripts."""
from __future__ import annotations

import re
import time

from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter

from studio.models import ResearchRequest

TASK_QUEUE = "lineage-studio-builder"
_client: Client | None = None


async def client() -> Client:
    global _client
    if _client is None:
        _client = await Client.connect("localhost:7233", data_converter=pydantic_data_converter)
    return _client


def new_id(req: ResearchRequest) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", req.person.full_name.lower()).strip("-")[:40]
    return f"studio-{slug}-{time.strftime('%m%d-%H%M%S')}"


async def start(req: ResearchRequest, wid: str | None = None) -> str:
    from studio.workflows import StudioRunWorkflow
    c = await client()
    wid = wid or new_id(req)
    await c.start_workflow(StudioRunWorkflow.run, req, id=wid, task_queue=TASK_QUEUE)
    return wid
