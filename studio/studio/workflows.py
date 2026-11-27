"""Workflows. Deterministic code only: no network, no clocks except workflow.now().

StudioRunWorkflow (one per research run)
  1. living-person gate (kin lib/gate.ts isPresumedLiving)
  2. load the public Lineage catalog (activity, live)
  3. reuse questions earlier runs asked about the same person (activity, SQLite)
  4. ChecklistPassWorkflow child: the circuit's baseline checklist, steps in parallel
  5. brainstorm graph, level by level (mode=brainstorm):
       root brainstorm -> `breadth` first questions
       each node: investigate (activity, retried) -> brainstorm follow-ups (activity)
       until depth, max_nodes or max_run_minutes; durable timer between levels
  6. compose report (activity), persist to SQLite, wait for approve / reject signal
Signals: approve, reject, redirect (a reviewer's own question), note, outreach_decision
Query:   progress -> Progress (typed)
"""

from __future__ import annotations

import asyncio
import re
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from studio.activities import (
        brainstorm_questions, compose_report, export_outreach, investigate, load_catalog, load_prior_questions,
        persist_run, run_checklist_step,
    )
    from studio.circuits import CIRCUITS, STAGE_LABELS, STEPS
    from studio.models import (
        BrainstormInput, CatalogSnapshot, ComposeInput, Decision, Finding, GateResult, InvestigateInput, OutreachDecision,
        OutreachDraft, PassInput, PassResult, PersistInput, Plan, PriorInput, Progress, Question, Redirect, ResearchRequest,
        Round, StepInput, StudioReport,
    )

LIVE_RETRY = RetryPolicy(initial_interval=timedelta(seconds=2), backoff_coefficient=2.0, maximum_interval=timedelta(seconds=30), maximum_attempts=8)
QUICK_RETRY = RetryPolicy(initial_interval=timedelta(seconds=1), maximum_attempts=3)
MAX_AGE = 110


def person_key(req: ResearchRequest) -> str:
    p = req.person
    toks = re.sub(r"[^a-z ]", " ", p.full_name.lower()).split()
    return f"{toks[0] if toks else ''}-{toks[-1] if toks else ''}-{p.birth_year or 'x'}"


@workflow.defn
class ChecklistPassWorkflow:
    """The circuit's baseline checklist. A child workflow so its history is separate.

    The `steps` query reports each step's state while the pass runs (queued, running, found, nothing, error), so the
    run page can show the checklist working instead of a single static node. It adds no workflow commands, so
    histories recorded before it replay unchanged."""

    def __init__(self) -> None:
        self.step_state: dict[str, dict] = {}

    @workflow.query
    def steps(self) -> list[dict]:
        return list(self.step_state.values())

    @workflow.run
    async def run(self, inp: PassInput) -> PassResult:
        for s in inp.steps:
            self.step_state[s.id] = {"id": s.id, "title": s.title, "mode": s.mode, "state": "queued", "found": 0}

        async def one(step):
            self.step_state[step.id]["state"] = "running"
            try:
                out = await workflow.execute_activity(
                    run_checklist_step, StepInput(request=inp.request, step=step, round=inp.round),
                    start_to_close_timeout=timedelta(seconds=90), retry_policy=LIVE_RETRY, activity_id=f"check-{step.id}",
                )
                f0 = out.findings[0] if out.findings else None
                self.step_state[step.id].update(state=f0.status if f0 else "nothing",
                                                found=sum(len(f.claims) + len(f.citations) for f in out.findings))
                return out.findings
            except ActivityError as e:
                self.step_state[step.id].update(state="error", error=str(e.cause or e)[:200])
                return [Finding(step_id=step.id, step_title=step.title, stage=step.stage, source_slug=step.source_slug, mode=step.mode,
                                status="error", confidence="none", notes=f"Gave up after retries: {e.cause or e}")]
        results = await asyncio.gather(*[one(s) for s in inp.steps])
        return PassResult(round=inp.round, findings=[f for r in results for f in r])


@workflow.defn
class StudioRunWorkflow:
    def __init__(self) -> None:
        self.p = Progress(status="starting")
        self.findings: list[Finding] = []
        self.decision: Decision | None = None
        self.redirects: list[Redirect] = []
        self.outreach_queue: list[OutreachDecision] = []

    # ---------------- signals and query
    @workflow.signal
    def approve(self, d: Decision) -> None:
        self.decision = Decision(approve=True, note=d.note, by=d.by)

    @workflow.signal
    def reject(self, d: Decision) -> None:
        self.decision = Decision(approve=False, note=d.note, by=d.by)

    @workflow.signal
    def redirect(self, r: Redirect) -> None:
        self.redirects.append(r)
        self.p.redirects.append(r)
        self._log(f"reviewer: look over here: {r.question}")

    @workflow.signal
    def note(self, text: str) -> None:
        self.p.reviewer_notes.append(text)

    @workflow.signal
    def outreach_decision(self, d: OutreachDecision) -> None:
        self.outreach_queue.append(d)

    @workflow.query
    def progress(self) -> Progress:
        return self.p

    # ---------------- helpers
    def _log(self, msg: str) -> None:
        # ISO UTC; the web page shows it in Pacific time.
        self.p.log.append(f"{workflow.now().isoformat(timespec='seconds')}|{msg}")

    def _stage(self, n: int) -> None:
        self.p.stage, self.p.stage_label = n, STAGE_LABELS[n]

    def _gate(self, req: ResearchRequest) -> GateResult:
        p = req.person
        rule = "Research runs only when a death is on record, or a birth more than 110 years ago (kin lib/gate.ts)."
        year = workflow.now().year
        if p.death_year is not None and p.death_year_precision != "after":
            return GateResult(allowed=True, rule=rule, reason=f"Death on record ({p.death_year}), so research can run.")
        if p.birth_year is not None and year - p.birth_year >= MAX_AGE:
            return GateResult(allowed=True, rule=rule, reason=f"Born {p.birth_year}, more than {MAX_AGE} years ago, so research can run.")
        return GateResult(allowed=False, rule=rule, reason="No death on record and no birth more than 110 years ago, so this person is presumed living. Nothing was searched.")

    def _persist_input(self, req: ResearchRequest, status: str) -> PersistInput:
        return PersistInput(workflow_id=workflow.info().workflow_id, person_key=person_key(req), person=req.person, circuit_id=req.circuit_id,
                            questions=self.p.questions, outreach=self.p.outreach, status=status)

    async def _persist(self, req, status):
        await workflow.execute_activity(persist_run, self._persist_input(req, status), start_to_close_timeout=timedelta(seconds=30), retry_policy=QUICK_RETRY)

    async def _compose(self, req, gate, catalog) -> StudioReport:
        rep = await workflow.execute_activity(
            compose_report,
            ComposeInput(request=req, gate=gate, catalog=catalog, findings=self.findings, questions=self.p.questions,
                         rounds=self.p.levels, stop_reason=self.p.stop_reason, reviewer_notes=self.p.reviewer_notes),
            start_to_close_timeout=timedelta(seconds=30), retry_policy=QUICK_RETRY,
        )
        rep.workflow_id = workflow.info().workflow_id
        rep.outreach = self.p.outreach
        return rep

    async def _outreach_loop(self):
        while True:
            await workflow.wait_condition(lambda: bool(self.outreach_queue))
            d = self.outreach_queue.pop(0)
            for i, o in enumerate(self.p.outreach):
                if o.id != d.draft_id or o.status != "awaiting_approval":
                    continue
                if d.approve:
                    o.status = "approved"
                    self.p.outreach[i] = await workflow.execute_activity(export_outreach, o, start_to_close_timeout=timedelta(seconds=20), retry_policy=QUICK_RETRY)
                    self._log(f"outreach {o.id} approved and exported to a local file. Not sent.")
                else:
                    o.status = "declined"
                    self._log(f"outreach {o.id} declined")

    def _budget_left(self, req) -> int:
        return req.max_nodes - len(self.p.questions)

    def _time_up(self, req) -> bool:
        return (workflow.now() - self.p.started_at).total_seconds() > req.max_run_minutes * 60

    def _replace(self, q: Question) -> None:
        for i, x in enumerate(self.p.questions):
            if x.id == q.id:
                self.p.questions[i] = q
                return
        self.p.questions.append(q)

    async def _work_node(self, req, q: Question, level: int, nxt: list[Question]) -> None:
        q.status = "running"
        self._replace(q)
        try:
            out = await workflow.execute_activity(
                investigate, InvestigateInput(request=req, question=q),
                start_to_close_timeout=timedelta(seconds=90), retry_policy=LIVE_RETRY, activity_id=f"node-{q.id}",
            )
        except ActivityError as e:
            q.status, q.answer = "error", f"Gave up after {LIVE_RETRY.maximum_attempts} attempts: {e.cause or e}"
            q.failures.append(q.answer)
            self._replace(q)
            self._log(f"{q.id} failed for good")
            return
        nq = out.question
        self._replace(nq)
        self.findings.append(out.finding)
        if nq.failures:
            self._log(f"{nq.id} succeeded on attempt {nq.attempts} after {len(nq.failures)} failure(s)")
        if out.outreach:
            self.p.outreach.append(out.outreach)
            self._log(f"{nq.id} drafted research request {out.outreach.id} to {out.outreach.to}: awaiting your approval")
        if nq.depth >= req.depth or nq.status in ("stub", "error"):
            return
        if self._budget_left(req) <= 0 or self._time_up(req):
            return
        bo = await workflow.execute_activity(
            brainstorm_questions,
            BrainstormInput(request=req, findings=[out.finding], questions=self.p.questions + nxt, round=level + 1,
                            top_n=req.breadth, node=nq, depth=nq.depth + 1),
            start_to_close_timeout=timedelta(seconds=30), retry_policy=QUICK_RETRY, activity_id=f"brainstorm-{nq.id}",
        )
        known = {x.key for x in self.p.questions + nxt}
        added = 0
        for f in bo.picked:
            if f.key in known or self._budget_left(req) <= 0 or added >= req.breadth:
                continue
            known.add(f.key)
            nxt.append(f)
            self.p.questions.append(f)
            added += 1
        self.p.levels[-1].generated += bo.generated
        self.p.levels[-1].duplicates_skipped += bo.duplicates_skipped
        if added:
            self._log(f"{nq.id} sparked {added} follow-up(s): " + "; ".join(x.text[:60] for x in nxt[-added:]))

    # ---------------- main
    @workflow.run
    async def run(self, req: ResearchRequest) -> StudioReport:
        wid = workflow.info().workflow_id
        self.p.workflow_id, self.p.request, self.p.started_at = wid, req, workflow.now()
        self._outreach_task = asyncio.create_task(self._outreach_loop())
        circuit = CIRCUITS[req.circuit_id]

        gate = self._gate(req)
        self.p.gate = gate
        self._stage(1)
        self._log(f"gate: {gate.reason}")
        if not gate.allowed:
            self.p.status = "blocked_living"
            rep = await self._compose(req, gate, None)
            self.p.report = rep
            await self._persist(req, "blocked_living")
            return rep

        catalog: CatalogSnapshot | None = None
        try:
            catalog = await workflow.execute_activity(load_catalog, start_to_close_timeout=timedelta(seconds=40), retry_policy=LIVE_RETRY)
            self._log(f"Lineage catalog: {catalog.source_count} public sources (live, no key)")
        except ActivityError:
            self._log("Lineage catalog unreachable; continuing without it")

        prior = await workflow.execute_activity(load_prior_questions, PriorInput(person_key=person_key(req), circuit_id=req.circuit_id),
                                                start_to_close_timeout=timedelta(seconds=20), retry_policy=QUICK_RETRY)

        # ---- checklist (baseline circuit)
        self.p.status = "checklist"
        step_ids = list(dict.fromkeys(["wikidata_identity", *[s for t in circuit.topics for s in t.steps]]))
        steps = [STEPS[s] for s in step_ids]
        self.p.steps_total = len(steps)
        lvl0 = Round(number=0, kind="checklist", started_at=workflow.now(), steps=step_ids)
        self.p.levels.append(lvl0)
        self._log(f"checklist: {circuit.title}, {len(steps)} steps")
        res = await workflow.execute_child_workflow(
            ChecklistPassWorkflow.run, PassInput(request=req, steps=steps, round=0), id=f"{wid}-checklist",
        )
        self.findings += res.findings
        self.p.findings = res.findings
        self.p.steps_done = [f.step_id for f in res.findings]
        lvl0.finished_at, lvl0.new_citations = workflow.now(), sum(len(f.citations) + len(f.claims) for f in res.findings)
        lvl0.verdict = f"checklist done: {sum(1 for f in res.findings if f.status == 'found')} steps found records"
        await self._persist(req, "checklist")

        # ---- brainstorm graph
        if req.mode == "brainstorm":
            self.p.status = "brainstorming"
            frontier: list[Question] = []
            # Reuse: re-ask what earlier runs asked at the top level, so nothing they checked is skipped.
            reuse = [q for q in prior.questions if q.depth == 1 and q.plan.handler != "stub"][: req.breadth]
            for i, old in enumerate(reuse, 1):
                q = Question(id=f"r{i}", key=old.key, round=1, text=old.text, because=f"asked by earlier run {old.seeded_from}; rechecking",
                             template=old.template, plan=old.plan, about=old.about, score=old.score, mode=old.mode,
                             parent_id="root", depth=1, seeded_from=old.seeded_from)
                frontier.append(q)
                self.p.questions.append(q)
            self.p.seeded = len(reuse)
            if reuse:
                self._log(f"reusing {len(reuse)} question(s) from {len(prior.runs)} earlier run(s)")
            lvl = Round(number=1, kind="brainstorm", started_at=workflow.now())
            self.p.levels.append(lvl)
            bo = await workflow.execute_activity(
                brainstorm_questions,
                BrainstormInput(request=req, findings=self.findings, questions=prior.questions + self.p.questions, round=1, top_n=req.breadth, depth=1),
                start_to_close_timeout=timedelta(seconds=30), retry_policy=QUICK_RETRY, activity_id="brainstorm-root",
            )
            for q in bo.picked:
                if self._budget_left(req) <= 0:
                    break
                frontier.append(q)
                self.p.questions.append(q)
            lvl.generated, lvl.duplicates_skipped = bo.generated, bo.duplicates_skipped
            self._log(f"root brainstorm: {bo.generated} ideas, {len(bo.picked)} picked")

            level = 1
            while frontier:
                if self.redirects:
                    for r in self.redirects:
                        frontier.append(self._reviewer_q(r, len(self.p.questions) + 1))
                    self.redirects = []
                self.p.round = level
                lvl = self.p.levels[-1]
                lvl.question_ids = [q.id for q in frontier]
                self._stage(6)
                nxt: list[Question] = []
                await asyncio.gather(*[self._work_node(req, q, level, nxt) for q in frontier])
                lvl.finished_at = workflow.now()
                lvl.answered = sum(1 for q in self.p.questions if q.id in lvl.question_ids and q.status == "answered")
                lvl.new_citations = sum(len(q.citations) for q in self.p.questions if q.id in lvl.question_ids)
                await self._persist(req, "brainstorming")
                if not nxt:
                    self.p.stop_reason = "No new questions: every lead has been followed to the depth you set."
                    lvl.verdict = "stop: " + self.p.stop_reason
                    break
                if self._time_up(req):
                    self.p.stop_reason = f"Reached the {req.max_run_minutes} minute limit."
                    for q in nxt:
                        q.status = "skipped"
                        self._replace(q)
                    lvl.verdict = "stop: " + self.p.stop_reason
                    break
                lvl.verdict = f"keep digging: {len(nxt)} new question(s)"
                lvl.paused_seconds = req.level_pause_seconds
                level += 1
                self.p.levels.append(Round(number=level, kind="brainstorm", started_at=workflow.now()))
                if req.level_pause_seconds:
                    self.p.status = "waiting_next_level"
                    self.p.next_round_at = workflow.now() + timedelta(seconds=req.level_pause_seconds)
                    await workflow.sleep(timedelta(seconds=req.level_pause_seconds))
                    self.p.status = "brainstorming"
                frontier = nxt
            if not self.p.stop_reason:
                self.p.stop_reason = "Reached the node limit." if self._budget_left(req) <= 0 else "Done."
            if self._budget_left(req) <= 0:
                self.p.stop_reason = f"Reached the {req.max_nodes} node limit."
            self._log("stop: " + self.p.stop_reason)
        else:
            self.p.stop_reason = "Checklist only mode."

        # ---- write and wait for the human
        self.p.status = "writing"
        self._stage(7)
        rep = await self._compose(req, gate, catalog)
        self.p.report = rep
        await self._persist(req, "awaiting_approval")
        if not req.require_approval:
            rep.decision = "not_required"
            self.p.status = "approved"
            return rep
        self.p.status = "awaiting_approval"
        self._log("report ready: waiting for approve or reject")
        while True:
            try:
                await workflow.wait_condition(lambda: self.decision is not None or bool(self.redirects),
                                              timeout=timedelta(hours=req.approval_timeout_hours))
                ok = True
            except asyncio.TimeoutError:
                ok = False
            if self.decision is not None:
                break
            if self.redirects:  # reviewer said "look over here" before approving
                self.p.status = "brainstorming"
                qs = [self._reviewer_q(r, len(self.p.questions) + 1) for r in self.redirects]
                self.redirects = []
                self.p.levels.append(Round(number=len(self.p.levels), kind="reviewer", started_at=workflow.now(), question_ids=[q.id for q in qs]))
                nxt: list[Question] = []
                await asyncio.gather(*[self._work_node(req, q, 99, nxt) for q in qs])
                if workflow.patched("reviewer-followups"):
                    # Follow the reviewer's lead down to the configured depth too.
                    lvl = nxt
                    while lvl:
                        deeper: list[Question] = []
                        await asyncio.gather(*[self._work_node(req, q, 99, deeper) for q in lvl])
                        lvl = deeper
                self.p.levels[-1].finished_at = workflow.now()
                rep = await self._compose(req, gate, catalog)
                self.p.report = rep
                self.p.status = "awaiting_approval"
                continue
            if not ok:
                break
        d = self.decision
        rep.decision = "approved" if d and d.approve else "rejected"
        rep.decision_note = d.note if d else "No decision before the approval timeout."
        rep.outreach = self.p.outreach
        rep.reviewer_notes = self.p.reviewer_notes
        self.p.report = rep
        self.p.status = "approved" if d and d.approve else "rejected"
        self._log(f"decision: {rep.decision}")
        await self._persist(req, self.p.status)
        await workflow.wait_condition(lambda: not self.outreach_queue)
        return rep

    def _reviewer_q(self, r: Redirect, n: int) -> Question:
        q = Question(id=f"you{n}", key=f"reviewer:{r.question.lower()[:60]}", round=self.p.round, text=r.question,
                     because="you asked: look over here", template="reviewer->look-here",
                     plan=Plan(handler="ia_fulltext", query=r.query or r.question), parent_id="root", depth=1, score=10)
        self.p.questions.append(q)
        return q
