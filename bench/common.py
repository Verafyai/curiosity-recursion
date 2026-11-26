"""Shared helpers for the benchmark: subject cards to requests, and runs to result lines."""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from cr.models import Person, ResearchRequest, StudioReport

ROOT = Path(__file__).resolve().parents[1]


def load_subjects(split: str | None = None, path: Path | None = None) -> list[dict]:
    path = path or ROOT / "bench" / "data" / "subjects.jsonl"
    subs = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    return [s for s in subs if split in (None, "all") or s["split"] == split]


def request_for(subject: dict, budget: int, **over) -> ResearchRequest:
    i = subject["input"]
    p = Person(full_name=i["full_name"], name_variants=i.get("name_variants") or [], birth_year=i.get("birth_year"),
               death_year=i.get("death_year"), birth_place=i.get("birth_place"), death_place=i.get("death_place"))
    base = dict(person=p, circuit_id=subject["circuit"], depth=3, breadth=3, max_nodes=80, max_run_minutes=180,
                level_pause_seconds=0, require_approval=False, simulate_flaky_archives=False, use_fixtures=False,
                max_tool_calls=budget)
    base.update(over)
    return ResearchRequest(**base)


def commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True,
                                       stderr=subprocess.DEVNULL).strip()
    except Exception:
        return "uncommitted"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def result_from_report(rep: StudioReport, **meta) -> dict:
    """One result line (bench/schema/result.schema.json) from a CR report."""
    depth = {q.id: q.depth for q in rep.questions}
    cits = []
    for q in rep.questions:
        for c in q.citations:
            cits.append({"url": c.url, "title": c.title, "item_id": c.item_id, "node": q.id, "depth": q.depth,
                         "name_match": c.name_match})
    for f in rep.candidates:
        for c in f.citations:
            cits.append({"url": c.url, "title": c.title, "item_id": c.item_id, "node": f.step_id, "depth": 0})
    return {
        **meta,
        "stop_reason": rep.stop_reason,
        "citations": cits,
        "documented_claims": [c.model_dump(mode="json") for c in rep.facts],
        "leads": [l.model_dump(mode="json") for l in rep.leads],
        "drafts": [{"to": o.to, "subject": o.subject, "node": o.node_id, "status": o.status} for o in rep.outreach],
        "questions": [{"id": q.id, "parent": q.parent_id, "depth": q.depth, "template": q.template, "key": q.key,
                       "status": q.status, "grounded": bool(q.parent_finding or q.parent_question or q.template == "reviewer->look-here")}
                      for q in rep.questions],
        "node_depth": depth,
    }
