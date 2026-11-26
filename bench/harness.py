"""Run agents on DarkKin-Bench subjects at fixed budgets and log one JSON line per run.

    python bench/harness.py --agents B3,B5 --budgets 50,100 --seeds 1 --split dev --limit 5 --out results/<name>.jsonl

- B3 (checklist only) and B5 (full CR) run as CuriosityRecursionWorkflow on the local Temporal
  dev server. The harness starts its own worker on a private task queue, with its own memory
  store (CR_DB) per agent and seed, so runs never share question memory unless H3 asks them to.
- B4 is the same CR code in a plain asyncio loop (bench/baselines/cr_plain_loop.py).
- B0 and B1 need ANTHROPIC_API_KEY; without it they are logged as `not run`, never faked.
- Every run uses use_fixtures=False: the eval fixtures hold ground truth.
- Fault settings come from bench/faults.py flags and are written into every line.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from temporalio.client import Client  # noqa: E402
from temporalio.contrib.pydantic import pydantic_data_converter  # noqa: E402

from bench.common import ROOT, commit, load_subjects, now, request_for, result_from_report  # noqa: E402
from cr.models import StudioReport  # noqa: E402
from cr.workflow import CuriosityRecursionWorkflow  # noqa: E402

AGENT_CONFIG = {
    "B3": dict(mode="checklist"),
    "B5": dict(mode="brainstorm", generator="rules"),
    "B5-llm": dict(mode="brainstorm", generator="llm"),
    "B5-hybrid": dict(mode="brainstorm", generator="hybrid"),
    "B5-nomem": dict(mode="brainstorm", use_memory=False),
    "B5-nocircuits": dict(mode="brainstorm", use_circuits=False),
    "B5-noverify": dict(mode="brainstorm", verify_nodes=False),
    "B5-nodedupe": dict(mode="brainstorm", dedupe=False),
}


def start_worker(tq: str, env_extra: dict) -> subprocess.Popen:
    env = {**os.environ, **env_extra, "CR_TASK_QUEUE": tq}
    log = open(ROOT / "results" / f"worker-{tq}.log", "w")
    return subprocess.Popen([sys.executable, str(ROOT / "worker.py")], env=env, stdout=log, stderr=subprocess.STDOUT, cwd=ROOT)


async def run_temporal(client: Client, tq: str, agent: str, subject: dict, budget: int, seed: int, faults: dict) -> dict:
    req = request_for(subject, budget, **AGENT_CONFIG[agent])
    wid = f"bench-{agent}-{subject['subject_id']}-b{budget}-s{seed}-{uuid.uuid4().hex[:6]}"
    t0 = time.time()
    meta = dict(run_id=wid, agent=agent, config=AGENT_CONFIG[agent], subject_id=subject["subject_id"], budget=budget, seed=seed,
                commit=commit(), started_at=now(), faults=faults)
    try:
        h = await client.start_workflow(CuriosityRecursionWorkflow.run, req, id=wid, task_queue=tq)
        rep: StudioReport = await asyncio.wait_for(h.result(), timeout=req.max_run_minutes * 60 + 600)
        desc = await h.describe()
        prog = await h.query("progress")
        line = result_from_report(rep, **meta)
        line.update(completed=True, wall_seconds=round(time.time() - t0, 1),
                    tool_calls=prog.get("tool_calls", 0) if isinstance(prog, dict) else prog.tool_calls,
                    llm_tokens=prog.get("llm_tokens", 0) if isinstance(prog, dict) else prog.llm_tokens,
                    history_events=desc.raw_description.workflow_execution_info.history_length)
        return line
    except Exception as e:  # logged, never dropped
        return {**meta, "completed": False, "stop_reason": f"error: {type(e).__name__}: {e}", "wall_seconds": round(time.time() - t0, 1),
                "tool_calls": 0, "citations": [], "drafts": [], "questions": []}


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--agents", default="B3,B5")
    ap.add_argument("--budgets", default="50")
    ap.add_argument("--seeds", type=int, default=1)
    ap.add_argument("--split", default="dev")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--subjects", default="", help="comma separated subject ids (overrides split and limit)")
    ap.add_argument("--fault-p", type=float, default=0.0, help="archive failure probability per node (H2)")
    ap.add_argument("--fault-k", type=int, default=2)
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    (ROOT / "results").mkdir(exist_ok=True)
    subs = load_subjects(a.split)
    if a.subjects:
        want = set(a.subjects.split(","))
        subs = [s for s in load_subjects("all") if s["subject_id"] in want]
    elif a.limit:
        subs = subs[: a.limit]
    faults = {"p": a.fault_p, "k": a.fault_k} if a.fault_p else {}
    client = await Client.connect(os.environ.get("TEMPORAL_ADDRESS", "localhost:7233"), data_converter=pydantic_data_converter)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(a.concurrency)
    out = a.out.open("a")
    workers = []
    try:
        for agent in a.agents.split(","):
            for seed in range(1, a.seeds + 1):
                if agent in ("B0", "B1"):
                    from bench.baselines import llm_agents
                    for s in subs:
                        for b in map(int, a.budgets.split(",")):
                            out.write(json.dumps(await llm_agents.run(agent, s, b, seed)) + "\n")
                            out.flush()
                    continue
                if agent == "B4":
                    from bench.baselines import cr_plain_loop
                    for s in subs:
                        for b in map(int, a.budgets.split(",")):
                            out.write(json.dumps(await cr_plain_loop.run(s, b, seed, faults)) + "\n")
                            out.flush()
                    continue
                tq = f"bench-{agent}-s{seed}-{uuid.uuid4().hex[:6]}"
                env = {"CR_DB": str(ROOT / "results" / f"memory-{agent}-s{seed}.db"),
                       "CR_OUTBOX": str(ROOT / "results" / "outbox-not-sent")}
                if faults:
                    env.update(CR_FAULT_P=str(a.fault_p), CR_FAULT_K=str(a.fault_k))
                workers.append(start_worker(tq, env))
                await asyncio.sleep(3)

                async def one(s, b, agent=agent, tq=tq, seed=seed):
                    async with sem:
                        line = await run_temporal(client, tq, agent, s, b, seed, faults)
                        out.write(json.dumps(line, default=str) + "\n")
                        out.flush()
                        print(f"{line['agent']} {line['subject_id']} B={line['budget']}: completed={line['completed']} "
                              f"calls={line.get('tool_calls')} cites={len(line['citations'])} ({line['stop_reason'][:60]})", flush=True)
                await asyncio.gather(*[one(s, b) for s in subs for b in map(int, a.budgets.split(","))])
    finally:
        for w in workers:
            w.terminate()
        out.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
