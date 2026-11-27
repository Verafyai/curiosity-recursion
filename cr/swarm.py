"""Curiosity Recursion v0.2: the swarm (spec sections 2 to 7 and 10). Deterministic workflow code only.

CuriosityRecursionSwarmWorkflow (orchestrator, parent)
  1. living-person gate, unchanged, in workflow code
  2. plan_outline (activity): lanes = viewpoint x record type x date window (STORM-style)
  3. loop until the budget B is spent, the wall-clock cap is hit, or no lead is worth a call:
       UCB1 allocator picks lanes and calls per lane
       up to W LaneWorkerWorkflow children run at once, each with a sub-budget
       every call a child wants is reserved with the parent first (signal ledger_reserve, reply
       ledger_reply): the parent is the ledger's only writer, so two children can never issue the
       same canonical call; blocked calls come back with up to 3 rewrites that carry a new key
       merge_verify (activity): dedupe, verification gate, rules skeptic, agreement count
       reflect_round (activity): Reflexion-style lessons for the next round
       continue-as-new at a round boundary when the history grows
  4. compose_report (activity, unchanged writer) plus the ledger and lane tables

Why a signal round trip and not a workflow update: in Temporal Python 1.37 a workflow cannot send an
update to another workflow, only a signal. The parent's signal handler decides synchronously before
its first await, which gives the same atomic check-and-reserve.
"""
from __future__ import annotations

import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ChildWorkflowError

with workflow.unsafe.imports_passed_through():
    from cr.activities import compose_report
    from cr.allocator import Allocator, LaneStats
    from cr.gate import gate as living_gate
    from cr.leads import VALUE_FLOOR, LeadTree
    from cr.ledger import Decision, Ledger, LedgerState, QuerySpec, canonical_id, life_window, source_of
    from cr.models import Citation, ComposeInput, Finding, OutreachDraft, Plan, Progress, Question, ResearchRequest, Round, StudioReport
    from cr.outline import Lane, Outline
    from cr.swarm_activities import merge_verify, plan_outline_activity, reflect_round, swarm_tool
    from cr.swarm_logic import expand, lead_value, replenish, reward_of
    from cr.swarm_models import (CallRecord, Ev, LaneResult, LaneTask, MergeInput, RecordSignal, ReflectInput, ReserveReply, ReserveRequest,
                                 SwarmInput, SwarmState, ToolCall)
    from cr.variants import variants

TOOL_RETRY = RetryPolicy(initial_interval=timedelta(seconds=2), backoff_coefficient=2.0, maximum_interval=timedelta(seconds=30), maximum_attempts=6)
QUICK = RetryPolicy(initial_interval=timedelta(seconds=1), maximum_attempts=3)
CHILD_RETRY = RetryPolicy(initial_interval=timedelta(seconds=1), maximum_attempts=2)
MAX_BLOCKED_IN_A_ROW = 25


@workflow.defn
class LaneWorkerWorkflow:
    """One lane for one round: best-first lead expansion within the lane's sub-budget."""

    def __init__(self) -> None:
        self.replies: dict[int, ReserveReply] = {}

    @workflow.signal
    def ledger_reply(self, r: ReserveReply) -> None:
        self.replies[r.req_no] = r

    @workflow.run
    async def run(self, t: LaneTask) -> LaneResult:
        me = workflow.info().workflow_id
        parent = workflow.get_external_workflow_handle(t.parent_id)
        tree, lane, p = t.tree, t.lane, t.request.person
        known_ids, known_keys = set(t.known_ids), set(t.known_keys)
        stats = {k: list(v) for k, v in t.yield_stats.items()}
        res = LaneResult(lane=lane.id, round=t.round, tree=tree)
        spent, req_no, blocked_run = 0, 0, 0
        var_set = {v.lower() for v in variants(p.full_name)}
        while spent < t.sub_budget:
            ld = tree.select(lane.id, VALUE_FLOOR)
            if ld is None:
                res.stop = "no lead above the value floor"
                break
            req_no += 1
            await parent.signal("ledger_reserve", ReserveRequest(child_id=me, req_no=req_no, spec=ld.spec))
            await workflow.wait_condition(lambda n=req_no: n in self.replies)
            rep = self.replies.pop(req_no)
            if rep.budget_exhausted:
                res.stop = "global budget spent"
                break
            if not rep.decision.allowed:
                ld.status = "blocked"
                res.blocked += 1
                blocked_run += 1
                for sg in rep.suggestions:
                    v, comp = lead_value(sg, lane.viewpoint, stats, t.coverage, t.lessons)
                    tree.add(lane.id, sg, ld.id, v, comp, grounding=sg.grounding or f"rewrite of blocked {rep.decision.canonical_id}")
                if blocked_run >= MAX_BLOCKED_IN_A_ROW:
                    res.stop = "too many blocked calls in a row"
                    break
                continue
            blocked_run = 0
            cid = rep.decision.canonical_id
            known_ids.add(cid)
            spent += 1
            ld.status = "done"
            err = ""
            try:
                out = await workflow.execute_activity(
                    swarm_tool, ToolCall(run_id=t.run_id, canonical_id=cid, seq=rep.seq, spec=ld.spec, person=p),
                    start_to_close_timeout=timedelta(seconds=120), heartbeat_timeout=timedelta(seconds=30), retry_policy=TOOL_RETRY,
                    activity_id=f"tool-{cid}-{rep.seq}")
                evs = out.items
            except ActivityError as e:
                out, evs, err = None, [], f"gave up after retries: {e.cause or e}"[:200]
            reward, new_keys = reward_of(evs, p, known_keys)
            known_keys |= set(new_keys)
            tree.backup(ld.id, reward)
            k = f"{ld.spec.tool}|{lane.viewpoint}"
            s = stats.setdefault(k, [0.0, 0.0])
            s[0] += reward
            s[1] += 1
            await parent.signal("ledger_record", RecordSignal(
                child_id=me, canonical_id=cid, n_items=out.n_items if out else 0, n_matched=out.n_matched if out else 0,
                hit_pages=out.hit_pages if out else [], book_hits=out.book_hits if out else {}, error=err or (out.error if out else ""),
                evidence_ids=[e.key for e in evs][:20]))
            res.calls.append(CallRecord(
                round=t.round, lane=lane.id, viewpoint=lane.viewpoint, lead_id=ld.id, tool=ld.spec.tool, source=source_of(ld.spec), terms=ld.spec.terms,
                canonical=cid, decision=rep.decision.decision, key_type=rep.decision.key_type, reason=rep.decision.reason, name_form=ld.spec.name_form,
                is_variant=bool(ld.spec.name_form and ld.spec.name_form.lower() in var_set), n_items=out.n_items if out else 0,
                n_matched=out.n_matched if out else 0, hit_pages=out.hit_pages if out else [], reward=reward, error=err or (out.error if out else ""),
                section=ld.spec.section, purpose=ld.spec.purpose, grounding=ld.spec.grounding))
            res.evidence += evs
            for nq in expand(ld.spec, evs, p, t.relatives, known_ids):
                v, comp = lead_value(nq, lane.viewpoint, stats, t.coverage, t.lessons)
                tree.add(lane.id, nq, ld.id, v, comp)
        else:
            res.stop = "sub-budget spent"
        res.unspent = t.sub_budget - spent
        res.tree = tree
        return res


@workflow.defn
class CuriosityRecursionSwarmWorkflow:
    def __init__(self) -> None:
        self.p = Progress(status="starting")
        self.st = SwarmState()
        self.ledger: Ledger | None = None
        self.child_budget: dict[str, int] = {}
        self.child_used: dict[str, int] = {}
        self.req: ResearchRequest | None = None

    # ---------------- signals from lane workers (the parent is the ledger's single writer)
    @workflow.signal
    async def ledger_reserve(self, r: ReserveRequest) -> None:
        assert self.ledger is not None and self.req is not None
        B = self.req.max_tool_calls or 10**9
        if self.st.reserved >= B or self.child_used.get(r.child_id, 0) >= self.child_budget.get(r.child_id, 0):
            reply = ReserveReply(req_no=r.req_no, decision=Decision(decision="blocked_no_key", canonical_id=canonical_id(r.spec), reason="budget spent"),
                                 budget_exhausted=True)
        else:
            d = self.ledger.reserve(r.spec, requested_by=r.child_id)
            sugg = []
            if d.allowed:
                self.st.reserved += 1
                self.p.tool_calls = self.st.reserved
                self.child_used[r.child_id] = self.child_used.get(r.child_id, 0) + 1
            else:
                self.st.blocked += 1
                if self.req.ledger:
                    sugg = [q.model_copy(update={"key_hint": dd.key_type if dd.decision == "revisit" else None,
                                                 "grounding": f"rewrite of blocked {d.canonical_id}: {dd.reason}"})
                            for q, dd in self.ledger.suggest(r.spec, self.req.person, self.st.relatives, n=3)]
            reply = ReserveReply(req_no=r.req_no, decision=d, suggestions=sugg, seq=self.st.reserved if d.allowed else 0)
        await workflow.get_external_workflow_handle(r.child_id).signal("ledger_reply", reply)

    @workflow.signal
    def ledger_record(self, r: RecordSignal) -> None:
        assert self.ledger is not None
        self.ledger.record(r.canonical_id, r.n_items, r.n_matched, r.hit_pages, r.error, r.evidence_ids)
        for item, pages in r.book_hits.items():
            self.ledger.note_hits(f"ia_book:{item.lower()}", pages)

    @workflow.query
    def progress(self) -> Progress:
        return self.p

    @workflow.query
    def ledger_summary(self) -> dict:
        return self.ledger.summary() if self.ledger else {}

    @workflow.query
    def lanes(self) -> dict:
        return {k: v.model_dump() for k, v in self.st.alloc.lanes.items()}

    # ---------------- helpers
    def _log(self, msg: str) -> None:
        line = f"{workflow.now().isoformat(timespec='seconds')}|{msg}"
        self.st.log.append(line)
        self.p.log.append(line)

    def _time_up(self, req) -> bool:
        return (workflow.now() - self.p.started_at).total_seconds() > req.max_run_minutes * 60

    def _yield_stats(self) -> dict[str, list[float]]:
        out: dict[str, list[float]] = {}
        for c in self.st.calls:
            s = out.setdefault(f"{c.tool}|{c.viewpoint}", [0.0, 0.0])
            s[0] += c.reward
            s[1] += 1
        return out

    def _seed(self, outline: Outline) -> None:
        for ln in outline.lanes:
            self.st.alloc.lanes[ln.id] = LaneStats(prior=ln.prior)
            for sp in ln.seeds:
                v, comp = lead_value(sp, ln.viewpoint, {}, outline.coverage, [])
                self.st.tree.add(ln.id, sp, None, v, comp)
            for i, sb in enumerate(ln.stubs, 1):
                p = self.req.person
                years = f"{p.birth_year or '?'} to {p.death_year or '?'}"
                self.st.drafts.append(OutreachDraft(
                    id=f"req-{ln.id}-{i}", node_id=f"{ln.id}-stub{i}", to=sb.to, channel="letter", contact_hint=sb.contact_hint,
                    subject=f"Research request: {p.full_name} ({years}), {sb.record_type}",
                    body=(f"Hello,\n\nI am researching {p.full_name} (born {p.birth_year or '?'}). Could you tell me whether you hold {sb.record_type} "
                          f"for this person? {sb.why}\n\nI am happy to pay any copying fee; please tell me the amount first.\n\nThank you,\n[Your name]")))

    def _lane(self, lid: str) -> Lane:
        return next(x for x in self.st.outline.lanes if x.id == lid)

    def _replenish(self, lid: str) -> int:
        ln = self._lane(lid)
        productive = [self.st.tree.nodes[c.lead_id].spec for c in self.st.calls if c.lane == lid and c.n_matched and c.lead_id in self.st.tree.nodes]
        added = 0
        for q in replenish(ln, self.ledger, self.req.person, self.st.relatives, productive[-4:]):
            v, comp = lead_value(q, ln.viewpoint, self._yield_stats(), self.st.outline.coverage, self.st.lessons)
            self.st.tree.add(lid, q, None, v, comp)
            added += 1
        return added

    async def _run_lane(self, wid: str, lid: str, k: int) -> LaneResult | None:
        cid = f"{wid}-r{self.st.round}-{lid}"
        self.child_budget[cid], self.child_used[cid] = k, 0
        task = LaneTask(run_id=wid, parent_id=wid, round=self.st.round, lane=self._lane(lid), sub_budget=k, tree=self.st.tree.subtree(lid),
                        known_ids=list(self.ledger.s.entries.keys()), known_keys=[e.key for e in self.st.verified], lessons=self.st.lessons,
                        coverage=self.st.outline.coverage, yield_stats=self._yield_stats(), relatives=self.st.relatives, request=self.req)
        try:
            return await workflow.execute_child_workflow(
                LaneWorkerWorkflow.run, task, id=cid, parent_close_policy=workflow.ParentClosePolicy.TERMINATE, retry_policy=CHILD_RETRY,
                execution_timeout=timedelta(minutes=max(10, self.req.max_run_minutes)))
        except ChildWorkflowError as e:
            self.st.lane_failures.append(f"{cid}: {e.cause or e}"[:200])
            self._log(f"lane {lid} failed in round {self.st.round}; its unspent reservation goes back to the pool")
            return None

    # ---------------- main
    @workflow.run
    async def run(self, inp: SwarmInput) -> StudioReport:
        req = inp.request
        self.req = req
        wid = workflow.info().workflow_id
        self.p.workflow_id, self.p.request = wid, req
        self.p.started_at = workflow.now()
        gate = living_gate(req.person, workflow.now().year)
        self.p.gate = gate
        if inp.state is not None:
            self.st = inp.state
            self.ledger = Ledger(self.st.ledger)
            self.p.tool_calls = self.st.reserved
            self._log(f"continued as new ({self.st.continued}) at round {self.st.round}")
        else:
            self._log(f"gate: {gate.reason}")
            if not gate.allowed:
                self.p.status = "blocked_living"
                rep = await self._compose(req, gate, "Blocked: presumed living.")
                return rep
            self.p.status = "researching"
            outline = await workflow.execute_activity(plan_outline_activity, {"person": req.person.model_dump(mode="json"), "tools": req.tools},
                                                      start_to_close_timeout=timedelta(seconds=30), retry_policy=QUICK)
            self.st.outline = outline
            self.ledger = Ledger(enabled=req.ledger, life_window=life_window(req.person), current_year=workflow.now().year)
            self._seed(outline)
            self._log(f"outline: {len(outline.lanes)} lanes ({', '.join(l.id for l in outline.lanes)}), era {outline.era}")
        B = req.max_tool_calls or 100
        W = max(1, req.workers)
        idle = 0
        while True:
            left = B - self.st.reserved
            if left <= 0:
                self.st.stop_reason = f"Reached the {B} tool-call budget."
                break
            if self._time_up(req):
                self.st.stop_reason = f"Reached the {req.max_run_minutes} minute limit."
                break
            open_lanes = []
            for ln in self.st.outline.lanes:
                if self.st.alloc.lanes[ln.id].closed:
                    continue
                if not any(x.value >= VALUE_FLOOR for x in self.st.tree.frontier(ln.id)):
                    self._replenish(ln.id)
                if any(x.value >= VALUE_FLOOR for x in self.st.tree.frontier(ln.id)):
                    open_lanes.append(ln.id)
            if not open_lanes:
                # every lane closed or dry: reopen the best closed lanes once more if any can be rewritten
                for lid in sorted(self.st.alloc.lanes, key=lambda x: -self.st.alloc.ucb(x)):
                    if self.st.alloc.lanes[lid].closed and self._replenish(lid):
                        self.st.alloc.reopen(lid)
                        open_lanes.append(lid)
                if not open_lanes:
                    self.st.stop_reason = "No lead above the value floor after rewrite suggestions."
                    break
            alloc = self.st.alloc.allocate(left, req.round_calls, open_lanes)
            if not alloc:
                self.st.stop_reason = "Allocator gave no calls."
                break
            self.st.round += 1
            self.st.alloc.round = self.st.round
            rd = Round(number=self.st.round, kind="swarm", started_at=workflow.now(), steps=list(alloc))
            self.p.levels.append(rd)
            self._log(f"round {self.st.round}: " + ", ".join(f"{l} {k}" for l, k in alloc.items()) + f" ({left} calls left)")
            items = list(alloc.items())
            results: list[LaneResult] = []
            for i in range(0, len(items), W):
                batch = items[i:i + W]
                got = await asyncio.gather(*[self._run_lane(wid, lid, k) for lid, k in batch])
                results += [g for g in got if g is not None]
            new_ev: list[Ev] = []
            for r in results:
                self.st.tree.merge(r.tree, r.lane)
                for c in r.calls:
                    c.n = len(self.st.calls) + 1
                    self.st.calls.append(c)
                new_ev += r.evidence
                rw = sum(c.reward for c in r.calls)
                self.st.alloc.update(r.lane, len(r.calls), rw, sum(1 for c in r.calls if c.n_matched), sum(1 for c in r.calls if not c.n_items))
            mo = await workflow.execute_activity(
                merge_verify, MergeInput(person=req.person, new_evidence=new_ev, known_keys=[e.key for e in self.st.verified],
                                         known_relatives=[x.name for x in self.st.relatives]),
                start_to_close_timeout=timedelta(seconds=60), heartbeat_timeout=timedelta(seconds=30), retry_policy=QUICK)
            self.st.verified += mo.verified
            self.st.leads_only += [e for e in mo.leads_only if e.key not in {x.key for x in self.st.leads_only}][:200]
            self.st.namesakes += mo.namesakes
            for k, v in mo.support.items():
                self.st.support[k] = max(self.st.support.get(k, 0), v)
            for e in mo.verified:
                if e.section:
                    self.st.outline.coverage[e.section] = "covered"
            for e in mo.leads_only:
                if e.section and self.st.outline.coverage.get(e.section) == "missing":
                    self.st.outline.coverage[e.section] = "leads_only"
            if mo.relatives:
                self.st.relatives += mo.relatives
                for lid in list(self.st.alloc.lanes):
                    if self.st.alloc.lanes[lid].closed:
                        self.st.alloc.reopen(lid)  # new verified facts open new keys
                for src_key, s in self.ledger.s.sources.items():
                    if s.closed:
                        self.ledger.reopen_for_relative(src_key)
            rd.finished_at = workflow.now()
            rd.answered = sum(len(r.calls) for r in results)
            rd.new_citations = len(mo.verified)
            if req.reflect:
                round_calls = [c for r in results for c in r.calls]
                lessons = await workflow.execute_activity(
                    reflect_round, ReflectInput(round=self.st.round, calls=round_calls, namesakes=mo.namesakes,
                                                relatives=[r.model_dump() for r in mo.relatives],
                                                known=[f"{x.type}:{x.key}" for x in self.st.lessons]),
                    start_to_close_timeout=timedelta(seconds=30), retry_policy=QUICK)
                self.st.lessons += lessons
            self.st.ledger = self.ledger.s
            rd.verdict = f"{rd.answered} calls, {len(mo.verified)} new verified items, {self.st.reserved}/{B} of B used"
            if self.st.reserved >= B:
                continue
            idle = idle + 1 if rd.answered == 0 else 0
            if idle >= 3:
                self.st.stop_reason = "Three rounds in a row without an allowed call: every remaining lead was a repeat."
                break
            hist = workflow.info().get_current_history_length()
            if req.continue_as_new_events == 0 or hist > req.continue_as_new_events or workflow.info().is_continue_as_new_suggested():
                await workflow.wait_condition(workflow.all_handlers_finished)
                self.st.continued += 1
                workflow.continue_as_new(SwarmInput(request=req, state=self.st))
        self._log("stop: " + self.st.stop_reason)
        self.st.ledger = self.ledger.s
        await workflow.wait_condition(workflow.all_handlers_finished)
        return await self._compose(req, gate, self.st.stop_reason)

    async def _compose(self, req, gate, stop) -> StudioReport:
        qs, finds = [], []
        verified = {e.key: e for e in self.st.verified}
        by_cid: dict[str, list[Ev]] = {}
        for e in self.st.verified:
            by_cid.setdefault(e.cid, []).append(e)
        for c in self.st.calls:
            cits = [Citation(title=e.title[:200], url=e.url, archive="Internet Archive" if (e.item_id or "").strip() else None, item_id=e.item_id,
                             year=e.year, snippet=e.snippet, name_match="strong") for e in by_cid.get(c.canonical, []) if e.key in verified]
            ld = self.st.tree.nodes.get(c.lead_id)
            plan = Plan(handler=c.tool if c.tool in ("ia_fts", "ia_inside", "ia_inside_pages", "ia_title", "chronam", "wikidata_search", "wikidata_entities") else "ia_fulltext",
                        query=c.terms, item_id=ld.spec.collection_or_item if ld else None,
                        years=tuple(ld.spec.date_window) if ld and ld.spec.date_window else None)
            qs.append(Question(id=f"c{c.n}", key=c.canonical, round=c.round, text=c.purpose or c.terms, because=c.grounding or "outline",
                               template=f"swarm:{c.lane}:{c.key_type or c.decision}", parent_finding=c.grounding or "outline", plan=plan,
                               status="answered" if cits else "no_lead", citations=cits, parent_id=(ld.parent or "root") if ld else "root",
                               depth=(ld.depth + 1) if ld else 1, answer=c.reason))
            if cits:
                finds.append(Finding(step_id=f"c{c.n}", step_title=(c.purpose or c.terms)[:200], stage=6, source_slug="swarm", mode="live", status="found",
                                     confidence="possible", citations=cits, notes=c.reason, round=c.round))
        rep = await workflow.execute_activity(
            compose_report, ComposeInput(request=req, gate=gate, catalog=None, findings=finds, questions=qs, rounds=self.p.levels, stop_reason=stop),
            start_to_close_timeout=timedelta(seconds=60), retry_policy=QUICK)
        rep.workflow_id = workflow.info().workflow_id
        rep.outreach = self.st.drafts
        rep.questions = qs
        rep.stop_reason = stop
        led = self.ledger
        allowed = sum(1 for r in (led.s.log if led else []) if r["decision"] in ("new", "revisit", "unchecked"))
        rep.swarm = {
            "ledger": led.s.log if led else [], "ledger_summary": led.summary() if led else {}, "reserved": self.st.reserved, "allowed": allowed,
            "blocked": self.st.blocked, "rounds": self.st.round, "continued_as_new": self.st.continued, "lanes": {k: v.model_dump() for k, v in self.st.alloc.lanes.items()},
            "coverage": self.st.outline.coverage if self.st.outline else {}, "lessons": [x.model_dump() for x in self.st.lessons],
            "verified": len(self.st.verified), "namesakes": len(self.st.namesakes), "relatives": [r.model_dump() for r in self.st.relatives],
            "lane_failures": self.st.lane_failures, "calls": [c.model_dump() for c in self.st.calls],
        }
        self.p.report = None
        self.p.status = "approved"
        return rep
