"""Activities for Explore mode. The research itself reuses studio.activities (investigate, run_checklist_step,
export_outreach, compose_report); this module only adds per-node question seeding."""
from __future__ import annotations

from temporalio import activity

from studio.brainstorm import brainstorm
from studio.explore import (
    SeedInput, SeedOutput, _x, deeper, dummy_known, node_as_question, node_finding, person_questions,
)
from studio.models import BrainstormInput


@activity.defn
async def seed_questions(inp: SeedInput) -> SeedOutput:
    """Brainstormed follow-ups for one node (rules engine; labelled with the generator that made each one)."""
    req, node = inp.request, inp.node
    known = set(inp.known_keys)
    if node.kind == "person" and not inp.deeper:
        bo = brainstorm(BrainstormInput(request=req, findings=inp.findings, questions=dummy_known(sorted(known)), round=1,
                                        top_n=req.breadth + 2, node=None, depth=1))
        qs = [q for q in person_questions(req, bo.picked, inp.start_no) if q.key not in known]
        return SeedOutput(questions=qs, generated=bo.generated, duplicates_skipped=bo.duplicates_skipped)
    if inp.deeper:
        path_known = set(inp.path_keys) | known
        qs = deeper(req, node, path_known, inp.start_no)
        bo = brainstorm(BrainstormInput(request=req, findings=[node_finding(node)], questions=dummy_known(sorted(path_known)),
                                        round=node.depth + 1, top_n=8, node=node_as_question(node, None), depth=node.depth + 1))
        n = inp.start_no + len(qs)
        for q in bo.picked + bo.held_back:
            if q.key in path_known:
                continue
            path_known.add(q.key)
            x = _x(q, node.id, "rules:dig-deeper", n)
            n += 1
            qs.append(x)
        return SeedOutput(questions=qs, generated=bo.generated + len(qs), duplicates_skipped=bo.duplicates_skipped)
    bo = brainstorm(BrainstormInput(request=req, findings=[node_finding(node)], questions=dummy_known(sorted(known)),
                                    round=node.depth + 1, top_n=req.breadth, node=node_as_question(node, None), depth=node.depth + 1))
    qs, n = [], inp.start_no
    for q in bo.picked:
        if q.key in known:
            continue
        known.add(q.key)
        qs.append(_x(q, node.id, "rules", n))
        n += 1
    return SeedOutput(questions=qs, generated=bo.generated, duplicates_skipped=bo.duplicates_skipped)
