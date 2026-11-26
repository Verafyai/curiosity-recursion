"""Replay saved event histories against the current workflow code (Temporal Replayer).

If a code change makes the workflow non-deterministic, this fails. Add a history with:
    temporal workflow show -w <id> -o json > tests/histories/<id>.json
"""
import asyncio
from pathlib import Path

from temporalio.client import WorkflowHistory
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.worker import Replayer

from cr.workflow import ChecklistPassWorkflow, CuriosityRecursionWorkflow

HIST = Path(__file__).resolve().parent / "histories"


def test_saved_histories_replay():
    files = sorted(HIST.glob("*.json"))
    assert files, "no saved histories"

    async def run():
        r = Replayer(workflows=[CuriosityRecursionWorkflow, ChecklistPassWorkflow], data_converter=pydantic_data_converter)
        for f in files:
            await r.replay_workflow(WorkflowHistory.from_json(f.stem, f.read_text()))
    asyncio.run(run())
