"""Replay every finished StudioRunWorkflow in the local Temporal against the current code.

Run with the dev server up: .venv/bin/python tests/test_replay.py
Fails if a code change made workflow history non-deterministic.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from temporalio.worker import Replayer

from studio.client import client
from studio.workflows import ChecklistPassWorkflow, StudioRunWorkflow


async def main() -> int:
    c = await client()
    replayer = Replayer(workflows=[StudioRunWorkflow, ChecklistPassWorkflow], data_converter=c.data_converter)
    n = 0
    async for w in c.list_workflows("WorkflowType='StudioRunWorkflow' OR WorkflowType='ChecklistPassWorkflow'"):
        h = await c.get_workflow_handle(w.id, run_id=w.run_id).fetch_history()
        await replayer.replay_workflow(h)
        n += 1
        print("replayed", w.id, w.status.name if w.status else "")
    print(f"{n} histories replayed without nondeterminism")
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
