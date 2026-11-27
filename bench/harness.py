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

from bench.common import ROOT, rpc_retry, wait_result, commit, load_subjects, now, request_for, result_from_report  # noqa: E402
from cr.models import StudioReport  # noqa: E402
from cr.workflow import CuriosityRecursionWorkflow  # noqa: E402
from cr.swarm import CuriosityRecursionSwarmWorkflow  # noqa: E402
from cr.swarm_models import SwarmInput  # noqa: E402

WORKDIR = ROOT / "results"

AGENT_CONFIG = {
    "B3": dict(mode="checklist"),
    "B5": dict(mode="brainstorm", generator="rules"),
    "B5-llm": dict(mode="brainstorm", generator="llm"),
    "B5-hybrid": dict(mode="brainstorm", generator="hybrid"),
    "B5-nomem": dict(mode="brainstorm", use_memory=False),
    "B5-nocircuits": dict(mode="brainstorm", use_circuits=False),
    "B5-noverify": dict(mode="brainstorm", verify_nodes=False),
    "B5-nodedupe": dict(mode="brainstorm", dedupe=False),
    # Breadth, depth and node-budget ablations (full system is b=3, d=3, N=80; see bench/common.py).
    **{f"B5-b{b}": dict(mode="brainstorm", breadth=b) for b in (1, 5, 8)},
    **{f"B5-d{d}": dict(mode="brainstorm", depth=d) for d in (1, 2, 4)},
    **{f"B5-n{n}": dict(mode="brainstorm", max_nodes=n) for n in (10, 30, 50)},
    # Post hoc, NOT preregistered (added 26 Nov 2026 after the first results): the widest graph the
    # request model allows (b=8, d=4, N=80), because the preregistered b=3, d=3 graph ran out of
    # questions at about 25 tool calls, far below B. Reported next to B5, never instead of it.
    "B5-max": dict(mode="brainstorm", breadth=8, depth=4, max_nodes=80),
    # Post hoc, NOT preregistered (26 Nov 2026, corpus-replication diagnosis): fixed rules generator ("rules2":
    # name variants from in-life snippets, place, life-window newspapers and obituary openers, life-window
    # namesake filter, no repeat search inside the same book, and "keep going" root re-brainstorm while
    # budget remains), with a node cap above the budget so B binds.
    "B5-fix": dict(mode="brainstorm", generator="rules2", breadth=5, depth=4, max_nodes=300),
    # v0.2 (preregistered in bench/PREREGISTRATION-v0.2.md before any live run): the swarm. Rules only, no model.
    "B6-swarm": dict(mode="swarm", generator="rules2", outline="rules", workers=4, ledger=True, reflect=True, verify_nodes=True, tools="v2"),
    "B6-no-ledger": dict(mode="swarm", generator="rules2", outline="rules", workers=4, ledger=False, reflect=True, verify_nodes=True, tools="v2"),
    "B6-no-parallel": dict(mode="swarm", generator="rules2", outline="rules", workers=1, ledger=True, reflect=True, verify_nodes=True, tools="v2"),
    "B6-no-reflect": dict(mode="swarm", generator="rules2", outline="rules", workers=4, ledger=True, reflect=False, verify_nodes=True, tools="v2"),
    "B6-v1tools": dict(mode="swarm", generator="rules2", outline="rules", workers=4, ledger=True, reflect=True, verify_nodes=True, tools="v1"),
}


LEDGER_DIR: Path | None = None
LEDGER_STEM: str = ""


def swarm_summary(sw: dict) -> dict:
    """Compact swarm stats for the result line (the full ledger goes to <out>/ledgers/)."""
    calls = sw.get("calls", [])
    rev = [c for c in calls if c.get("decision") == "revisit"]
    return {"reserved": sw.get("reserved"), "blocked": sw.get("blocked"), "rounds": sw.get("rounds"), "continued_as_new": sw.get("continued_as_new"),
            "revisit_count": (sw.get("ledger_summary") or {}).get("revisit_count", {}), "revisits": len(rev),
            "revisit_yield": (sum(1 for c in rev if c.get("reward", 0) >= 1) / len(rev)) if rev else None,
            "verified": sw.get("verified"), "namesakes": sw.get("namesakes"), "relatives": len(sw.get("relatives") or []),
            "lane_failures": sw.get("lane_failures"), "coverage": sw.get("coverage"), "lessons": len(sw.get("lessons") or []),
            "lanes": {k: {"calls": v.get("calls"), "reward": v.get("reward"), "closed": v.get("closed")} for k, v in (sw.get("lanes") or {}).items()}}


def start_worker(tq: str, env_extra: dict) -> subprocess.Popen:
    env = {**os.environ, **env_extra, "CR_TASK_QUEUE": tq}
    log = open(WORKDIR / f"worker-{tq}.log", "w")
    return subprocess.Popen([sys.executable, str(ROOT / "worker.py")], env=env, stdout=log, stderr=subprocess.STDOUT, cwd=ROOT)


async def run_temporal(client: Client, tq: str, agent: str, subject: dict, budget: int, seed: int, faults: dict) -> dict:
    req = request_for(subject, budget, **AGENT_CONFIG[agent])
    wid = f"bench-{agent}-{subject['subject_id']}-b{budget}-s{seed}-{uuid.uuid4().hex[:6]}"
    t0 = time.time()
    meta = dict(run_id=wid, agent=agent, config=AGENT_CONFIG[agent], subject_id=subject["subject_id"], budget=budget, seed=seed,
                commit=commit(), started_at=now(), faults=faults)
    try:
        if req.mode == "swarm":
            h = await rpc_retry(lambda: client.start_workflow(CuriosityRecursionSwarmWorkflow.run, SwarmInput(request=req), id=wid, task_queue=tq))
        else:
            h = await rpc_retry(lambda: client.start_workflow(CuriosityRecursionWorkflow.run, req, id=wid, task_queue=tq))
        rep: StudioReport = await wait_result(h, req.max_run_minutes * 60 + 600)
        desc = await rpc_retry(h.describe)
        prog = await rpc_retry(lambda: h.query("progress"))
        line = result_from_report(rep, **meta)
        if rep.swarm is not None:
            line["swarm"] = swarm_summary(rep.swarm)
            if LEDGER_DIR is not None:
                LEDGER_DIR.mkdir(parents=True, exist_ok=True)
                (LEDGER_DIR / f"{LEDGER_STEM or wid}.ledger.jsonl").write_text("".join(json.dumps(r, default=str) + "\n" for r in rep.swarm["ledger"]))
                (LEDGER_DIR / f"{LEDGER_STEM or wid}.calls.jsonl").write_text("".join(json.dumps(r, default=str) + "\n" for r in rep.swarm["calls"]))
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
    ap.add_argument("--seed-list", default="", help="comma separated seeds; overrides --seeds")
    ap.add_argument("--split", default="dev")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--subjects", default="", help="comma separated subject ids (overrides split and limit)")
    ap.add_argument("--subjects-file", type=Path, default=None, help="subject cards jsonl (default bench/data/subjects.jsonl)")
    ap.add_argument("--fault-p", type=float, default=0.0, help="archive failure probability per node (H2)")
    ap.add_argument("--fault-k", type=int, default=2)
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--tag", default="", help="isolates memory stores and worker queues between invocations")
    ap.add_argument("--workdir", type=Path, default=ROOT / "results", help="where memory stores and worker logs go")
    ap.add_argument("--ledger-dir", type=Path, default=None, help="where swarm runs write <run>.ledger.jsonl (default <out dir>/../ledgers)")
    ap.add_argument("--ledger-stem", default="", help="file stem for the ledger (default: the workflow id)")
    a = ap.parse_args()
    global LEDGER_DIR, LEDGER_STEM
    LEDGER_DIR = a.ledger_dir or (a.out.parent.parent / "ledgers" if a.out.parent.name == "runs" else a.out.parent / "ledgers")
    LEDGER_STEM = a.ledger_stem
    (ROOT / "results").mkdir(exist_ok=True)
    a.workdir.mkdir(parents=True, exist_ok=True)
    global WORKDIR
    WORKDIR = a.workdir
    subs = load_subjects(a.split, a.subjects_file)
    if a.subjects:
        want = set(a.subjects.split(","))
        subs = [s for s in load_subjects("all", a.subjects_file) if s["subject_id"] in want]
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
            for seed in ([int(x) for x in a.seed_list.split(",")] if a.seed_list else range(1, a.seeds + 1)):
                if agent in ("B0", "B1"):
                    from bench.baselines import llm_agents

                    async def one_llm(s, b, agent=agent, seed=seed):
                        async with sem:
                            try:
                                line = await llm_agents.run(agent, s, b, seed)
                            except Exception as e:  # logged, never dropped
                                line = {"run_id": f"{agent}-{s['subject_id']}-b{b}-s{seed}-err", "agent": agent, "subject_id": s["subject_id"],
                                        "budget": b, "seed": seed, "commit": commit(), "started_at": now(), "completed": False,
                                        "stop_reason": f"error: {type(e).__name__}: {e}", "tool_calls": 0, "citations": [], "drafts": [], "questions": []}
                            out.write(json.dumps(line, default=str) + "\n")
                            out.flush()
                            print(f"{agent} {s['subject_id']} B={b} s{seed}: calls={line.get('tool_calls')} usd={line.get('usd')} ({line['stop_reason'][:50]})", flush=True)
                    await asyncio.gather(*[one_llm(s, b) for s in subs for b in map(int, a.budgets.split(","))])
                    continue
                if agent == "B4":
                    from bench.baselines import cr_plain_loop
                    os.environ["CR_DB"] = str(a.workdir / f"memory-B4{a.tag}-s{seed}.db")

                    async def one_b4(s, b, seed=seed):
                        async with sem:
                            line = await cr_plain_loop.run(s, b, seed, faults)
                            out.write(json.dumps(line, default=str) + "\n")
                            out.flush()
                            print(f"B4 {s['subject_id']} B={b}: completed={line['completed']} calls={line.get('tool_calls')}", flush=True)
                    await asyncio.gather(*[one_b4(s, b) for s in subs for b in map(int, a.budgets.split(","))])
                    continue
                tq = f"bench-{agent}{a.tag}-s{seed}-{uuid.uuid4().hex[:6]}"
                env = {"CR_DB": str(a.workdir / f"memory-{agent}{a.tag}-s{seed}.db"),
                       "CR_OUTBOX": str(a.workdir / "outbox-not-sent"), "CR_EVIDENCE_DIR": str(a.workdir / "evidence")}
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
