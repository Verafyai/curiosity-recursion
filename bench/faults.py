"""Fault injection for H2: worker kills, flaky archives, refusals, long waits, delayed replies.

    # B5 on Temporal with archive failures p=0.3 and a worker SIGKILL about every 45 s
    python bench/faults.py --agent B5 --fault-p 0.3 --kill-every 45 --subjects kinher-jewish-01 --budget 50 --out results/h2.jsonl
    # B4, the plain loop, under the same schedule (a kill ends the run: nothing is persisted)
    python bench/faults.py --agent B4 --fault-p 0.3 --kill-every 45 --subjects kinher-jewish-01 --budget 50 --out results/h2.jsonl

- Flaky archives: CR_FAULT_P and CR_FAULT_K make investigations fail their first k attempts with
  probability p (cr/activities.py _flaky). Permanent refusals are real: Internet Archive lending
  books answer inside-book search with HTTP 403, recorded as "source refused" and not retried.
- Worker kills: SIGKILL at exponential intervals (mean --kill-every seconds), restart after
  --restart-after seconds. Each kill is logged with the workflow's history length at that moment.
- Multi-day waits and delayed replies: run in Temporal's time-skipping test server
  (tests/test_time_skipping.py) with level pauses of days; `delayed_replies()` signals simulated
  archive answers (cr/sources/mock_archive.py) after 3 to 21 simulated days.
- Duplicate-work ratio = activity executions after a crash that repeat a finished activity,
  divided by activities completed. On Temporal it is read from event history; for B4 it is the
  plain loop's re-executions after restart (every completed step is redone, because nothing persisted).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from temporalio.client import Client, WorkflowHandle  # noqa: E402
from temporalio.contrib.pydantic import pydantic_data_converter  # noqa: E402

from bench.common import ROOT, commit, load_subjects, now, request_for, result_from_report  # noqa: E402
from cr.models import OutreachDraft  # noqa: E402
from cr.sources.mock_archive import plan_reply  # noqa: E402
from cr.workflow import CuriosityRecursionWorkflow  # noqa: E402


class WorkerKiller:
    def __init__(self, tq: str, env: dict, mean_s: float, restart_after: float, seed: int):
        self.tq, self.env, self.mean, self.restart_after = tq, env, mean_s, restart_after
        self.rng, self.proc, self.kills = random.Random(seed), None, []

    def start(self):
        log = open(ROOT / "results" / f"worker-{self.tq}.log", "a")
        self.proc = subprocess.Popen([sys.executable, str(ROOT / "worker.py")], env={**os.environ, **self.env, "CR_TASK_QUEUE": self.tq},
                                     stdout=log, stderr=subprocess.STDOUT, cwd=ROOT)

    async def loop(self, handle: WorkflowHandle, done: asyncio.Event):
        while not done.is_set():
            try:
                await asyncio.wait_for(done.wait(), timeout=self.rng.expovariate(1 / self.mean))
                return
            except asyncio.TimeoutError:
                pass
            desc = await handle.describe()
            self.proc.send_signal(signal.SIGKILL)
            self.proc.wait()
            self.kills.append({"t": round(time.time(), 1), "history_events": desc.raw_description.workflow_execution_info.history_length,
                               "pending": len(desc.raw_description.pending_activities)})
            await asyncio.sleep(self.restart_after)
            self.start()

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()


async def repeated_activities(handle: WorkflowHandle) -> int:
    """Activities started again after already completing once (should be 0 on Temporal)."""
    done, again = set(), 0
    async for e in handle.fetch_history_events():
        if e.HasField("activity_task_scheduled_event_attributes"):
            aid = e.activity_task_scheduled_event_attributes.activity_id
            if aid in done:
                again += 1
        if e.HasField("activity_task_completed_event_attributes"):
            sched = e.activity_task_completed_event_attributes.scheduled_event_id
            done.add(sched)
    return again


async def delayed_replies(handle: WorkflowHandle, drafts: list[OutreachDraft], held: list[dict], seed: int, day_seconds: float):
    """Send simulated archive replies after their planned delay (scaled: one day = day_seconds)."""
    plans = sorted((p for p in (plan_reply(d, held, seed) for d in drafts) if p.delay_days is not None), key=lambda p: p.delay_days)
    t0 = time.time()
    for p in plans:
        await asyncio.sleep(max(0.0, p.delay_days * day_seconds - (time.time() - t0)))
        await handle.signal("archive_reply", p.reply)


async def run_b5(subject: dict, budget: int, a) -> dict:
    client = await Client.connect(os.environ.get("TEMPORAL_ADDRESS", "localhost:7233"), data_converter=pydantic_data_converter)
    tq = f"faults-{uuid.uuid4().hex[:6]}"
    env = {"CR_DB": str(ROOT / "results" / f"memory-faults-{tq}.db"), "CR_FAULT_P": str(a.fault_p), "CR_FAULT_K": str(a.fault_k)}
    killer = WorkerKiller(tq, env, a.kill_every, a.restart_after, a.seed)
    killer.start()
    await asyncio.sleep(3)
    req = request_for(subject, budget, mode="brainstorm")
    wid = f"faults-B5-{subject['subject_id']}-p{a.fault_p}-{uuid.uuid4().hex[:6]}"
    meta = dict(run_id=wid, agent="B5", subject_id=subject["subject_id"], budget=budget, seed=a.seed, commit=commit(), started_at=now(),
                faults={"p": a.fault_p, "k": a.fault_k, "kill_every_s": a.kill_every, "restart_after_s": a.restart_after})
    h = await client.start_workflow(CuriosityRecursionWorkflow.run, req, id=wid, task_queue=tq)
    done = asyncio.Event()
    kt = asyncio.create_task(killer.loop(h, done)) if a.kill_every else None
    t0 = time.time()
    try:
        rep = await asyncio.wait_for(h.result(), timeout=a.timeout)
        done.set()
        line = result_from_report(rep, **meta)
        desc = await h.describe()
        line.update(completed=True, wall_seconds=round(time.time() - t0, 1), kills=killer.kills,
                    history_events=desc.raw_description.workflow_execution_info.history_length,
                    repeated_activities=await repeated_activities(h))
    except Exception as e:
        done.set()
        line = {**meta, "completed": False, "stop_reason": f"error: {type(e).__name__}: {e}", "kills": killer.kills,
                "wall_seconds": round(time.time() - t0, 1), "citations": [], "drafts": [], "questions": []}
    finally:
        if kt:
            await kt
        killer.stop()
    return line


def run_b4(subject: dict, budget: int, a) -> dict:
    """B4 in a child process killed on the same schedule. A kill ends the run; a restart starts over."""
    rng, t0, kills, attempts = random.Random(a.seed), time.time(), [], 0
    cmd = [sys.executable, "-c", (
        "import asyncio,json,sys;sys.path.insert(0,'.');from bench.common import load_subjects;"
        "from bench.baselines import cr_plain_loop as c;"
        f"s=[x for x in load_subjects('all') if x['subject_id']=={subject['subject_id']!r}][0];"
        f"print(json.dumps(asyncio.run(c.run(s,{budget},{a.seed},{{'p':{a.fault_p},'k':{a.fault_k}}}))))")]
    while time.time() - t0 < a.timeout:
        attempts += 1
        p = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        wait = rng.expovariate(1 / a.kill_every) if a.kill_every else a.timeout
        try:
            out, _ = p.communicate(timeout=wait)
            line = json.loads(out.strip().splitlines()[-1])
            line.update(kills=kills, restarts=attempts - 1, wall_seconds=round(time.time() - t0, 1))
            return line
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()
            kills.append({"t": round(time.time(), 1)})
            time.sleep(a.restart_after)
    return {"run_id": f"faults-B4-{subject['subject_id']}", "agent": "B4", "subject_id": subject["subject_id"], "budget": budget,
            "seed": a.seed, "commit": commit(), "started_at": now(), "completed": False, "stop_reason": "timed out under kills",
            "kills": kills, "restarts": attempts - 1, "wall_seconds": round(time.time() - t0, 1), "citations": [], "drafts": [], "questions": [],
            "faults": {"p": a.fault_p, "k": a.fault_k, "kill_every_s": a.kill_every}}


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", choices=["B4", "B5"], required=True)
    ap.add_argument("--subjects", required=True)
    ap.add_argument("--budget", type=int, default=50)
    ap.add_argument("--fault-p", type=float, default=0.3)
    ap.add_argument("--fault-k", type=int, default=2)
    ap.add_argument("--kill-every", type=float, default=45.0, help="mean seconds between SIGKILLs; 0 = no kills")
    ap.add_argument("--restart-after", type=float, default=5.0)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--timeout", type=float, default=3600)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    (ROOT / "results").mkdir(exist_ok=True)
    subs = [s for s in load_subjects("all") if s["subject_id"] in set(a.subjects.split(","))]
    with a.out.open("a") as f:
        for s in subs:
            line = await run_b5(s, a.budget, a) if a.agent == "B5" else run_b4(s, a.budget, a)
            f.write(json.dumps(line, default=str) + "\n")
            print(line["agent"], line["subject_id"], "completed" if line["completed"] else "NOT completed", len(line.get("kills", [])), "kills")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
