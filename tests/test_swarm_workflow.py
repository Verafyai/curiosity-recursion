"""The v0.2 swarm on Temporal's time-skipping test server, with the synthetic mock archive (no network).

Covers: deterministic child ids; the global budget across children; the ledger reservation keeps two
children from issuing the same canonical call; merge dedupes; unverified items never become claims;
continue-as-new gives the same result; a worker killed mid-round redoes no finished activity; the
history replays.
"""
import asyncio
import os
import re
from pathlib import Path
import uuid
from collections import Counter

import pytest
from temporalio import activity
from temporalio.client import WorkflowHistory
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

import cr.sources as src
from cr import swarm_activities as sa
from cr.activities import compose_report
from cr.models import Person, ResearchRequest
from cr.sources import mock_live
from cr.swarm import CuriosityRecursionSwarmWorkflow, LaneWorkerWorkflow
from cr.swarm_models import Ev, MergeInput, SwarmInput, ToolCall, ToolResult

P = Person(full_name="Josiah Quill Tester", birth_year=1840)
CALLS: list[str] = []
FINISHED: Counter = Counter()


@pytest.fixture(autouse=True)
def mock_sources(monkeypatch, tmp_path):
    CALLS.clear()
    FINISHED.clear()
    monkeypatch.setenv("CR_EVIDENCE_DIR", str(tmp_path / "evidence"))
    for name in ("ia_fts", "ia_fulltext", "ia_inside", "ia_title_search", "chronam", "wikidata_search", "wikidata_entities"):
        fn = getattr(mock_live, name)

        def wrap(fn=fn, name=name):
            async def inner(*a, **k):
                CALLS.append(f"{name}|{a}|{sorted(k.items())}")
                return await fn(*a, **k)
            return inner
        monkeypatch.setattr(src, name, wrap())

    async def pages(item, q, first, last):
        CALLS.append(f"ia_inside_pages|{item}|{q}|{first}|{last}")
        return [m for m in await mock_live.ia_inside(item, q) if first <= m["page"] <= last]
    monkeypatch.setattr(src, "ia_inside_pages", pages)


@activity.defn(name="swarm_tool")
async def tracked_tool(call: ToolCall) -> ToolResult:
    r = await sa.swarm_tool(call)
    if not r.from_store:
        FINISHED[f"{call.canonical_id}-{call.seq}"] += 1
    return r


ACTS = [tracked_tool, sa.plan_outline_activity, sa.merge_verify, sa.reflect_round, compose_report, sa.load_graph_cache]
WFS = [CuriosityRecursionSwarmWorkflow, LaneWorkerWorkflow]


def req(**kw):
    base = dict(person=P, mode="swarm", workers=4, ledger=True, reflect=True, max_tool_calls=40, max_run_minutes=600,
                require_approval=False, simulate_flaky_archives=False, use_fixtures=False)
    base.update(kw)
    return ResearchRequest(**base)


async def _run(r: ResearchRequest, wid: str | None = None, kill_after: int = 0):
    async with await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter) as env:
        tq = f"tq-{uuid.uuid4()}"
        wid = wid or f"swarm-{uuid.uuid4().hex[:8]}"
        if kill_after:
            # max_cached_workflows=0 disables sticky queues: the time-skipping
            # test server does not fall back from a dead worker's sticky queue.
            async with Worker(env.client, task_queue=tq, workflows=WFS, activities=ACTS, max_cached_workflows=0):
                h = await env.client.start_workflow(CuriosityRecursionSwarmWorkflow.run, SwarmInput(request=r), id=wid, task_queue=tq)
                while sum(FINISHED.values()) < kill_after:
                    await asyncio.sleep(0.05)
            # worker A is gone mid-round; worker B picks the run up
            async with Worker(env.client, task_queue=tq, workflows=WFS, activities=ACTS, max_cached_workflows=0):
                rep = await h.result()
        else:
            async with Worker(env.client, task_queue=tq, workflows=WFS, activities=ACTS):
                h = await env.client.start_workflow(CuriosityRecursionSwarmWorkflow.run, SwarmInput(request=r), id=wid, task_queue=tq)
                rep = await h.result()
        hist = await h.fetch_history()
        children = []
        async for e in h.fetch_history_events():
            if e.HasField("child_workflow_execution_started_event_attributes"):
                children.append(e.child_workflow_execution_started_event_attributes.workflow_execution.workflow_id)
        child_hist = await env.client.get_workflow_handle(children[0]).fetch_history() if children else None
    return rep, hist, children, child_hist, wid


def test_parallel_swarm_budget_ids_and_no_duplicate_calls():
    rep, hist, children, child_hist, wid = asyncio.run(_run(req()))
    sw = rep.swarm
    assert sw["reserved"] == 40  # the global budget binds across children, never exceeded
    assert len(CALLS) == 40  # one source call per reserved unit
    assert all(re.fullmatch(rf"{re.escape(wid)}-r\d+-[a-z-]+", c) for c in children)
    assert len(children) == len(set(children))
    cids = [c["canonical"] for c in sw["calls"]]
    assert len(cids) == len(set(cids)), "two children issued the same canonical call"
    assert sum(1 for r in sw["ledger"] if r["decision"] in ("new", "revisit")) == 40
    revisits = [r for r in sw["ledger"] if r["decision"] == "revisit"]
    assert all(r.get("reason") for r in revisits)
    # unverified items never become claims: every cited item prints the full name in a quoted snippet
    for q in rep.questions:
        for c in q.citations:
            assert c.name_match == "strong" and c.snippet
    # replay the recorded histories against the current code
    async def replay():
        r = Replayer(workflows=WFS, data_converter=pydantic_data_converter)
        await r.replay_workflow(hist)
        if child_hist is not None:
            await r.replay_workflow(child_hist)
    asyncio.run(replay())
    if os.environ.get("CR_RECORD_SWARM_HISTORY"):
        HIST.mkdir(exist_ok=True)
        (HIST / f"{wid}.json").write_text(hist.to_json())
        (HIST / f"{children[0]}.json").write_text(child_hist.to_json())


HIST = Path(__file__).resolve().parent / "histories_swarm"


def test_saved_swarm_histories_replay():
    files = sorted(HIST.glob("*.json"))
    assert files, "no saved swarm histories (record with CR_RECORD_SWARM_HISTORY=1)"

    async def run():
        r = Replayer(workflows=WFS, data_converter=pydantic_data_converter)
        for f in files:
            await r.replay_workflow(WorkflowHistory.from_json(f.stem, f.read_text()))
    asyncio.run(run())


def _sig(rep):
    return ([(c["lane"], c["canonical"], c["decision"]) for c in rep.swarm["calls"]],
            sorted({c.url for q in rep.questions for c in q.citations}))


def test_continue_as_new_gives_the_same_result():
    a, *_ = asyncio.run(_run(req(workers=1, max_tool_calls=60)))
    CALLS.clear()
    b, *_ = asyncio.run(_run(req(workers=1, max_tool_calls=60, continue_as_new_events=0)))
    assert b.swarm["continued_as_new"] >= 1
    assert _sig(a) == _sig(b)


def test_worker_kill_mid_round_redoes_no_finished_activity():
    rep, *_ = asyncio.run(_run(req(max_tool_calls=40), kill_after=8))
    assert rep.swarm["reserved"] == 40
    assert max(FINISHED.values()) == 1, "a finished tool call ran again after the worker was killed"


def test_merge_dedupes_and_gate():
    def ev(key, nm="strong", snip="the record names **Josiah Tester** in 1862", lane="a", in_life=True):
        return Ev(cid="c", lane=lane, tool="ia_fts", key=key, snippet=snip, name_match=nm, in_life=in_life)
    inp = MergeInput(person=P, new_evidence=[ev("ia:x#1"), ev("ia:x#1", lane="b"), ev("ia:y#2", nm="surname_only"),
                                             ev("ia:z#3", in_life=False), ev("ia:w#4", snip="**Josiah Tester** was born in 1790"),
                                             ev("ia:k#5")], known_keys=["ia:k#5"])
    out = asyncio.run(sa.merge_verify(inp))
    assert [e.key for e in out.verified] == ["ia:x#1"] and out.support["ia:x#1"] == 2
    assert out.duplicates == 2  # the second copy and the already-known key
    assert [e.key for e in out.leads_only] == ["ia:y#2"]
    assert out.namesakes and out.refuted and "skeptic" in out.refuted[0]["why"]


def test_graph_cache_skips_queries_done_in_an_earlier_run(tmp_path):
    """Post hoc graph cache (off for every benchmark condition): run 2, given run 1's search graph, issues
    none of run 1's calls."""
    from cr import search_graph as sg

    async def go():
        async with await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter) as env:
            async with Worker(env.client, task_queue="tq-g", workflows=WFS, activities=ACTS):
                r1 = await env.client.execute_workflow(CuriosityRecursionSwarmWorkflow.run, SwarmInput(request=req(max_tool_calls=30)),
                                                       id="g1", task_queue="tq-g")
                sg.write_all(sg.build_graph(r1.swarm["ledger"], r1.swarm["calls"], {"run_id": "g1"}), tmp_path / "g1")
                r2 = await env.client.execute_workflow(
                    CuriosityRecursionSwarmWorkflow.run,
                    SwarmInput(request=req(max_tool_calls=30, graph_cache=str(tmp_path / "g1.graph.json"))), id="g2", task_queue="tq-g")
        return r1, r2
    r1, r2 = asyncio.run(go())
    first = {c["canonical"] for c in r1.swarm["calls"]}
    second = {c["canonical"] for c in r2.swarm["calls"]}
    assert first and second and not (first & second), "a query done in run 1 was issued again in run 2"
    assert any(r["decision"] == "cached" for r in r2.swarm["ledger"])
