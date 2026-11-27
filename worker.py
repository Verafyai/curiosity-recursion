"""Run the curiosity-recursion worker: polls task queue "curiosity-recursion" on the local Temporal dev server."""
import asyncio
import logging
import os

from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.worker import Worker

from cr import activities as a
from cr import swarm_activities as sa
from cr.swarm import CuriosityRecursionSwarmWorkflow, LaneWorkerWorkflow
from cr.workflow import ChecklistPassWorkflow, CuriosityRecursionWorkflow

TASK_QUEUE = os.environ.get("CR_TASK_QUEUE", "curiosity-recursion")


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    client = await Client.connect(os.environ.get("TEMPORAL_ADDRESS", "localhost:7233"), data_converter=pydantic_data_converter)
    worker = Worker(
        client, task_queue=TASK_QUEUE,
        workflows=[CuriosityRecursionWorkflow, ChecklistPassWorkflow, CuriosityRecursionSwarmWorkflow, LaneWorkerWorkflow],
        activities=[a.load_catalog, a.run_checklist_step, a.brainstorm_questions, a.investigate, a.compose_report,
                    a.persist_run, a.load_prior_questions, a.export_outreach,
                    sa.swarm_tool, sa.plan_outline_activity, sa.merge_verify, sa.reflect_round, sa.load_graph_cache],
        max_concurrent_activities=8,
    )
    logging.info("worker polling %s", TASK_QUEUE)
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
