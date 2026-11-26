"""Pilot numbers quoted in the paper, computed from the Studio Builder's own store.

    python eval/pilot_stats.py PATH/studio.db > paper/data/pilot.json
Every pilot number in the paper traces to this output.
"""
import json
import sqlite3
import sys
from collections import Counter

con = sqlite3.connect(sys.argv[1])
runs = con.execute("select workflow_id, name, circuit, status from runs order by workflow_id").fetchall()
out = {"runs": [], "outreach": []}
for wid, name, circuit, status in runs:
    qs = [json.loads(r[0]) for r in con.execute("select json from questions where workflow_id=?", (wid,))]
    st = Counter(q["status"] for q in qs)
    out["runs"].append({"workflow_id": wid, "name": name, "circuit": circuit, "status": status, "nodes": len(qs),
                        "by_status": dict(st), "max_depth": max((q["depth"] for q in qs), default=0),
                        "reused_from_memory": sum(1 for q in qs if q.get("seeded_from")),
                        "reviewer_questions": sum(1 for q in qs if q["template"] == "reviewer->look-here"),
                        "retried_nodes": sum(1 for q in qs if q.get("failures")),
                        "max_attempts": max((q.get("attempts") or 0 for q in qs), default=0)})
for wid, oid, status, js in con.execute("select workflow_id, id, status, json from outreach"):
    o = json.loads(js)
    out["outreach"].append({"workflow_id": wid, "id": oid, "status": status, "to": o["to"]})
out["totals"] = {"runs": len(runs), "nodes": sum(r["nodes"] for r in out["runs"]),
                 "runs_by_status": dict(Counter(r["status"] for r in out["runs"])),
                 "outreach_drafts": len(out["outreach"]), "outreach_by_status": dict(Counter(o["status"] for o in out["outreach"]))}
print(json.dumps(out, indent=2))
