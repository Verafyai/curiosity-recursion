"""Explore mode workflows. Deterministic code only.

ExploreRunWorkflow (one per interactive run; the graph's only writer)
  1. living-person gate
  2. the person node and its brainstormed questions (seed_questions activity, rules only, no network): seconds
  3. waits for the user. Every action is a workflow update, validated before it is accepted:
       research(question)   -> a ResearchPassWorkflow child scoped to that one question (at most 3 run at once)
       skip / edit / add_question / dig_deeper / draft_outreach / retry
       compose              -> writes the draft report; approve / reject signals decide it
       outreach_decision    -> approve writes a local text file (export_outreach). Nothing is ever sent.
ResearchPassWorkflow (child, one per click)
  investigate or run_checklist_step for the question -> child nodes from what came back (claims first, then
  citations) -> seed_questions for every new node. Returns everything to the parent, which attaches it.
Query: progress -> ExploreProgress (typed). Every change bumps `seq`, which the web app's event stream watches.
"""
from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Optional

from pydantic import BaseModel
from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ChildWorkflowError

with workflow.unsafe.imports_passed_through():
    from studio.activities import compose_report, draft_outreach, export_outreach, investigate, run_checklist_step
    from studio.circuits import STEPS
    from studio.explore import (
        AddCmd, EditCmd, ExploreProgress, NodeCmd, PassInfo, PassInput, PassOutput, QuestionCmd, ResearchCmd, SeedInput, SeedOutput,
        XNode, XQuestion, as_question, describe_search, est_calls, gate, generic_outreach, nodes_from, offline, path_ids, user_question,
    )
    from studio.explore_activities import seed_questions
    from studio.models import (
        ComposeInput, Decision, Finding, InvestigateInput, OutreachDecision, ResearchRequest, StepInput,
    )

LIVE_RETRY = RetryPolicy(initial_interval=timedelta(seconds=2), backoff_coefficient=2.0, maximum_interval=timedelta(seconds=30), maximum_attempts=8)
QUICK_RETRY = RetryPolicy(initial_interval=timedelta(seconds=1), maximum_attempts=3)
MAX_PARALLEL_PASSES = 3


class ExploreInput(BaseModel):
    request: ResearchRequest
    call_budget: int = 100
    confirm_over_calls: int = 2
    state: Optional[ExploreProgress] = None


@workflow.defn
class ResearchPassWorkflow:
    @workflow.run
    async def run(self, inp: PassInput) -> PassOutput:
        q, req, parent = inp.question.model_copy(deep=True), inp.request, inp.node
        out = PassOutput(pass_id=inp.pass_id, question=q)
        finding: Finding
        if q.kind == "checklist_step" and q.step_id in STEPS:
            so = await workflow.execute_activity(run_checklist_step, StepInput(request=req, step=STEPS[q.step_id], round=parent.depth + 1),
                                                 start_to_close_timeout=timedelta(seconds=90), retry_policy=LIVE_RETRY,
                                                 activity_id=f"{inp.pass_id}-step")
            fs = so.findings
            finding = Finding(step_id=q.id, step_title=q.text, stage=fs[0].stage if fs else 1, source_slug=fs[0].source_slug if fs else "none",
                              mode=fs[0].mode if fs else "live", status="found" if any(f.claims or f.citations for f in fs) else "nothing",
                              confidence=fs[0].confidence if fs else "none", claims=[c for f in fs for c in f.claims],
                              citations=[c for f in fs for c in f.citations], notes=" ".join(f.notes for f in fs)[:600])
            q.answer = finding.notes or ("Found records." if finding.status == "found" else "Nothing found.")
            q.status = "answered" if finding.status == "found" else "no_lead"
            out.calls = est_calls(q)
        else:
            iv = await workflow.execute_activity(investigate, InvestigateInput(request=req, question=as_question(q, req, parent.depth + 1)),
                                                 start_to_close_timeout=timedelta(seconds=90), retry_policy=LIVE_RETRY,
                                                 activity_id=f"{inp.pass_id}-investigate")
            finding = iv.finding
            q.answer = iv.question.answer
            q.status = "answered" if iv.question.status == "answered" else "no_lead"
            out.calls = est_calls(q)
        out.finding = finding
        nodes = nodes_from(finding, q, parent, inp.next_node_no)
        known = list(inp.known_keys)
        qno = 1
        for nd in nodes:
            so: SeedOutput = await workflow.execute_activity(
                seed_questions, SeedInput(request=req, node=nd, known_keys=known, start_no=qno),
                start_to_close_timeout=timedelta(seconds=30), retry_policy=QUICK_RETRY, activity_id=f"{inp.pass_id}-seed-{nd.id}")
            out.questions += so.questions
            known += [x.key for x in so.questions]
        out.nodes = nodes
        q.produced = [n.id for n in nodes]
        if q.status == "no_lead" and not nodes:
            q.answer = q.answer or "Nothing found."
        out.question = q
        return out


@workflow.defn
class ExploreRunWorkflow:
    def __init__(self) -> None:
        self.p = ExploreProgress()
        self.req: ResearchRequest | None = None
        self.work: list[tuple[str, str]] = []  # (kind, id) queued by updates, drained by the main loop
        self.running = 0
        self.decision: Decision | None = None
        self.outreach_queue: list[OutreachDecision] = []
        self.findings: list[Finding] = []
        self.node_no = 1
        self.pass_no = 0
        self.q_no: dict[str, int] = {}

    # ---------------- helpers
    def _touch(self) -> None:
        self.p.seq += 1

    def _log(self, msg: str) -> None:
        self.p.log.append(f"{workflow.now().isoformat(timespec='seconds')}|{msg}")
        self._touch()

    def _nodes(self) -> dict[str, XNode]:
        return {n.id: n for n in self.p.nodes}

    def _q(self, qid: str) -> XQuestion | None:
        return next((q for q in self.p.questions if q.id == qid), None)

    def _node(self, nid: str) -> XNode | None:
        return next((n for n in self.p.nodes if n.id == nid), None)

    def _next_q(self, nid: str) -> int:
        n = self.q_no.get(nid, 0) + 1
        self.q_no[nid] = n
        return n

    def _add_questions(self, qs: list[XQuestion]) -> None:
        for x in qs:
            n = self._next_q(x.node_id)
            x.id = f"{x.node_id}-q{n}"
            self.p.questions.append(x)

    def _refresh_node(self, nid: str) -> None:
        nd = self._node(nid)
        if nd is None:
            return
        qs = [q for q in self.p.questions if q.node_id == nid]
        if any(q.status == "running" for q in qs):
            nd.state = "running"
        elif any(q.status == "queued" for q in qs):
            nd.state = "queued"
        elif any(o.node_id in {q.id for q in qs} | {nid} and o.status == "awaiting_approval" for o in self.p.outreach):
            nd.state = "waiting_approval"
        elif qs and max(qs, key=lambda q: q.pass_id or "").status == "failed" and any(q.status == "failed" for q in qs):
            nd.state = "failed"
            nd.error = next(q.error for q in qs if q.status == "failed")
        else:
            nd.state = "done"
            nd.error = ""

    def _known_keys(self) -> list[str]:
        return [q.key for q in self.p.questions]

    def _path_keys(self, nid: str) -> list[str]:
        ids = set(path_ids(self._nodes(), nid))
        return [q.key for q in self.p.questions if q.node_id in ids]

    def _budget_left(self) -> int:
        return self.p.call_budget - self.p.calls_used

    # ---------------- query
    @workflow.query
    def progress(self) -> ExploreProgress:
        return self.p

    # ---------------- updates (validated; the web app turns a validation error into a 4xx)
    @workflow.update
    def research(self, cmd: ResearchCmd) -> dict:
        q = self._q(cmd.question_id)
        q.status = "queued"
        q.error = ""
        self.work.append(("pass", q.id))
        self._refresh_node(q.node_id)
        self._log(f"queued: {q.text[:90]}")
        return {"question_id": q.id, "est_calls": q.est_calls}

    @research.validator
    def _v_research(self, cmd: ResearchCmd) -> None:
        q = self._q(cmd.question_id)
        if q is None:
            raise ValueError(f"unknown question {cmd.question_id}")
        if self.p.status in ("blocked_living", "approved", "rejected"):
            raise ValueError(f"run is {self.p.status}")
        if q.status in ("queued", "running"):
            raise ValueError("already running")
        if q.status == "skipped":
            raise ValueError("question was skipped")
        if offline(q):
            raise ValueError("offline source: use Draft outreach")
        if q.est_calls > self._budget_left():
            raise ValueError(f"over budget: needs {q.est_calls} calls, {self._budget_left()} left")
        if q.est_calls > self.p.confirm_over_calls and not cmd.confirmed:
            raise ValueError(f"confirm required: {q.est_calls} tool calls is over the {self.p.confirm_over_calls} call threshold")

    @workflow.update
    def retry(self, cmd: QuestionCmd) -> dict:
        return self.research(ResearchCmd(question_id=cmd.question_id, confirmed=True))

    @retry.validator
    def _v_retry(self, cmd: QuestionCmd) -> None:
        q = self._q(cmd.question_id)
        if q is None or q.status != "failed":
            raise ValueError("only a failed question can be retried")

    @workflow.update
    def skip(self, cmd: QuestionCmd) -> dict:
        q = self._q(cmd.question_id)
        q.status = "skipped"
        self._log(f"skipped: {q.text[:90]}")
        return {"question_id": q.id}

    @skip.validator
    def _v_skip(self, cmd: QuestionCmd) -> None:
        q = self._q(cmd.question_id)
        if q is None or q.status in ("queued", "running"):
            raise ValueError("cannot skip a running or unknown question")

    @workflow.update
    def edit(self, cmd: EditCmd) -> dict:
        old = self._q(cmd.question_id)
        nd = self._node(old.node_id)
        x = user_question(AddCmd(node_id=nd.id, text=cmd.text, query=cmd.query, generator="user", because=f"You rewrote: {old.text[:80]}"),
                          nd, self.req, 0)
        x.edited_from = old.id
        if old.status == "open":
            old.status = "skipped"
        self._add_questions([x])
        self._log(f"edited {old.id}: {x.text[:90]}")
        return {"question_id": x.id, "est_calls": x.est_calls}

    @edit.validator
    def _v_edit(self, cmd: EditCmd) -> None:
        q = self._q(cmd.question_id)
        if q is None or not cmd.text.strip():
            raise ValueError("unknown question or empty text")

    @workflow.update
    def add_question(self, cmd: AddCmd) -> dict:
        nd = self._node(cmd.node_id)
        x = user_question(cmd, nd, self.req, 0)
        if any(q.key == x.key for q in self.p.questions):
            return {"question_id": next(q.id for q in self.p.questions if q.key == x.key), "duplicate": True}
        self._add_questions([x])
        self._log(f"{'you added' if cmd.generator == 'user' else 'chat suggested'} on {nd.id}: {x.text[:90]}")
        return {"question_id": x.id, "est_calls": x.est_calls}

    @add_question.validator
    def _v_add(self, cmd: AddCmd) -> None:
        if self._node(cmd.node_id) is None or not cmd.text.strip():
            raise ValueError("unknown node or empty text")

    @workflow.update
    def dig_deeper(self, cmd: NodeCmd) -> dict:
        self.work.append(("deeper", cmd.node_id))
        self._log(f"dig deeper on {cmd.node_id}")
        return {"node_id": cmd.node_id}

    @dig_deeper.validator
    def _v_deeper(self, cmd: NodeCmd) -> None:
        if self._node(cmd.node_id) is None:
            raise ValueError("unknown node")

    @workflow.update
    def draft_outreach(self, cmd: QuestionCmd) -> dict:
        q = self._q(cmd.question_id)
        d = draft_outreach(as_question(q, self.req, 1), self.req) or generic_outreach(q, self.req)
        d = d.model_copy(update={"id": f"req-{q.id}", "node_id": q.node_id})
        self.p.outreach.append(d)
        q.status, q.outreach_id = "outreach_drafted", d.id
        q.answer = f"Drafted a research request to {d.to}. Held for your approval. Nothing is sent."
        self._refresh_node(q.node_id)
        self._log(f"drafted research request {d.id} to {d.to}: awaiting your approval")
        return {"draft_id": d.id}

    @draft_outreach.validator
    def _v_draft(self, cmd: QuestionCmd) -> None:
        q = self._q(cmd.question_id)
        if q is None or q.status in ("running", "queued", "outreach_drafted"):
            raise ValueError("unknown question, or a draft already exists")

    @workflow.update
    def compose(self) -> dict:
        self.work.append(("compose", ""))
        return {"ok": True}

    @workflow.signal
    def outreach_decision(self, d: OutreachDecision) -> None:
        self.outreach_queue.append(d)

    @workflow.signal
    def approve(self, d: Decision) -> None:
        self.decision = Decision(approve=True, note=d.note, by=d.by)

    @workflow.signal
    def reject(self, d: Decision) -> None:
        self.decision = Decision(approve=False, note=d.note, by=d.by)

    # ---------------- work
    async def _seed(self, nid: str, deeper: bool) -> None:
        nd = self._node(nid)
        so = await workflow.execute_activity(
            seed_questions, SeedInput(request=self.req, node=nd, known_keys=self._known_keys(), deeper=deeper,
                                      path_keys=self._path_keys(nid), findings=self.findings if nd.kind == "person" else []),
            start_to_close_timeout=timedelta(seconds=30), retry_policy=QUICK_RETRY)
        self._add_questions(so.questions)
        if deeper:
            self._log(f"dig deeper on {nid}: {len(so.questions)} new question(s)" if so.questions else
                      f"dig deeper on {nid}: nothing new that has not been asked on this path")
        else:
            self._log(f"{len(so.questions)} questions brainstormed for {nd.label[:60]}")

    async def _pass(self, qid: str) -> None:
        q = self._q(qid)
        nd = self._node(q.node_id)
        self.pass_no += 1
        pid = f"p{self.pass_no}"
        info = PassInfo(id=pid, question_id=q.id, node_id=nd.id, state="running", started_at=workflow.now())
        self.p.passes.append(info)
        q.status, q.pass_id = "running", pid
        self._refresh_node(nd.id)
        self._log(describe_search(q, self.req))
        first_no = self.node_no
        self.node_no += 6  # nodes_from makes at most 6
        try:
            out: PassOutput = await workflow.execute_child_workflow(
                ResearchPassWorkflow.run,
                PassInput(request=self.req, pass_id=pid, question=q, node=nd, known_keys=self._known_keys(), next_node_no=first_no),
                id=f"{workflow.info().workflow_id}-{pid}", retry_policy=RetryPolicy(maximum_attempts=1),
                execution_timeout=timedelta(minutes=30))
        except (ChildWorkflowError, ActivityError) as e:
            cause = e.cause or e
            while getattr(cause, "cause", None) is not None:
                cause = cause.cause
            q.status, q.error = "failed", str(cause)[:300]
            info.state, info.error, info.finished_at = "failed", q.error, workflow.now()
            self._refresh_node(nd.id)
            self._log(f"failed: {q.text[:70]}: {q.error[:120]}")
            return
        for i, x in enumerate(self.p.questions):
            if x.id == q.id:
                self.p.questions[i] = out.question
        self.p.nodes += out.nodes
        self._add_questions(out.questions)
        self.p.calls_used += out.calls
        if out.finding:
            self.findings.append(out.finding)
        info.state, info.finished_at, info.calls, info.found = "done", workflow.now(), out.calls, len(out.nodes)
        self._refresh_node(nd.id)
        for n in out.nodes:
            self._refresh_node(n.id)
        hits = len(out.finding.citations) + len(out.finding.claims) if out.finding else 0
        self._log(f"Found {hits} hit(s); {len(out.nodes)} new node(s) with {len(out.questions)} question(s)")

    async def _guarded(self, kind: str, ident: str) -> None:
        try:
            if kind == "pass":
                await self._pass(ident)
            elif kind == "deeper":
                await self._seed(ident, True)
            elif kind == "compose":
                await self._compose()
        finally:
            self.running -= 1
            self._touch()

    async def _compose(self) -> None:
        self.p.status = "writing"
        self._log("writing the draft from what has been found so far")
        qs = [as_question(x, self.req, 1).model_copy(update={"status": "answered" if x.status == "answered" else "no_lead",
                                                              "citations": [c for n in self.p.nodes if n.id in x.produced for c in n.citations]})
              for x in self.p.questions if x.status in ("answered", "no_lead")]
        rep = await workflow.execute_activity(
            compose_report, ComposeInput(request=self.req, gate=self.p.gate, catalog=None, findings=self.findings, questions=qs,
                                         rounds=[], stop_reason="Explore mode: you chose what to research."),
            start_to_close_timeout=timedelta(seconds=30), retry_policy=QUICK_RETRY)
        rep.workflow_id = workflow.info().workflow_id
        rep.outreach = self.p.outreach
        self.p.report = rep
        self.p.status = "awaiting_approval"
        self._log("draft ready: approve or reject it, or keep exploring")

    async def _outreach_loop(self) -> None:
        while True:
            await workflow.wait_condition(lambda: bool(self.outreach_queue))
            d = self.outreach_queue.pop(0)
            for i, o in enumerate(self.p.outreach):
                if o.id != d.draft_id or o.status != "awaiting_approval":
                    continue
                if d.approve:
                    o.status = "approved"
                    self.p.outreach[i] = await workflow.execute_activity(export_outreach, o, start_to_close_timeout=timedelta(seconds=20),
                                                                         retry_policy=QUICK_RETRY)
                    self._log(f"outreach {o.id} approved and written to a local file. Not sent.")
                else:
                    o.status = "declined"
                    self._log(f"outreach {o.id} declined")
                self._refresh_node(o.node_id)
                q = next((x for x in self.p.questions if x.outreach_id == o.id), None)
                if q:
                    self._refresh_node(q.node_id)

    # ---------------- main
    @workflow.run
    async def run(self, inp: ExploreInput) -> ExploreProgress:
        req = inp.request
        self.req = req
        asyncio.create_task(self._outreach_loop())
        if inp.state is not None:
            self.p = inp.state
            self.node_no = 1 + max([int(n.id[1:]) for n in self.p.nodes if n.id[1:].isdigit()] or [0])
            self.pass_no = len(self.p.passes)
            for q in self.p.questions:
                n = int(q.id.rsplit("-q", 1)[1]) if "-q" in q.id and q.id.rsplit("-q", 1)[1].isdigit() else 0
                self.q_no[q.node_id] = max(self.q_no.get(q.node_id, 0), n)
            self._log("continued as new with the same graph")
        else:
            self.p.workflow_id, self.p.request, self.p.started_at = workflow.info().workflow_id, req, workflow.now()
            self.p.call_budget, self.p.confirm_over_calls = inp.call_budget, inp.confirm_over_calls
            g = gate(req.person, workflow.now().year)
            self.p.gate = g
            self._log(f"gate: {g.reason}")
            P = req.person
            self.p.nodes.append(XNode(id="person", kind="person", label=f"{P.full_name}", tier="told",
                                      summary=f"{P.birth_year or '?'} to {P.death_year or '?'}" + (f", {P.birth_place or P.death_place}" if (P.birth_place or P.death_place) else ""),
                                      depth=0, state="running" if g.allowed else "failed", error="" if g.allowed else g.reason))
            if not g.allowed:
                self.p.status = "blocked_living"
                self._touch()
                return self.p
            await self._seed("person", False)
            self.p.status = "exploring"
            self._refresh_node("person")
            self._log("ready: click a node, pick a question, and press Research this")
        while True:
            idle_and_big = lambda: self.running == 0 and not self.work and workflow.info().is_continue_as_new_suggested()  # noqa: E731
            await workflow.wait_condition(lambda: self.decision is not None or (bool(self.work) and self.running < MAX_PARALLEL_PASSES) or idle_and_big())
            if self.decision is not None:
                break
            if idle_and_big():
                await workflow.wait_condition(workflow.all_handlers_finished)
                workflow.continue_as_new(ExploreInput(request=req, call_budget=self.p.call_budget, confirm_over_calls=self.p.confirm_over_calls, state=self.p))
            kind, ident = self.work.pop(0)
            self.running += 1
            asyncio.create_task(self._guarded(kind, ident))
        await workflow.wait_condition(lambda: self.running == 0)
        d = self.decision
        if self.p.report is not None:
            self.p.report.decision = "approved" if d.approve else "rejected"
            self.p.report.decision_note = d.note
        self.p.status = "approved" if d.approve else "rejected"
        self._log(f"decision: {self.p.status}")
        await workflow.wait_condition(lambda: not self.outreach_queue)
        return self.p
