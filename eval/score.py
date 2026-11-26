"""Score logged runs against DarkKin-Bench hidden records.

    python eval/score.py results/<name>.jsonl [--subjects bench/data/subjects.jsonl] [--labels eval/adjudicate/labels.csv]

Matching (automatic, conservative):
- URLs are normalised (scheme, www, trailing slash, query and fragment dropped, case folded).
- Internet Archive: a citation of archive.org/details/<id>/... matches a record for the same <id>.
- loc.gov: /resource/<lccn>/<date>/ed-N/ matches regardless of the page parameter (sp=).
- Wikipedia: same article title.
An automatic match is a CANDIDATE. It counts toward "found and verified" only when adjudication
labels (eval/adjudicate/) mark it "correct, same person". Without labels the scorer reports
candidate recall and says so on every line. T2 and T3 records need a drafted request to the right
holder and are scored from labels only.

Outputs, per run: candidate recall@B overall and by tier, verified recall@B (labels), lead-chain
depth of each hit, time to first hit (tool calls), novel hosts, grounded-question share.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]


def norm_url(u: str | None) -> str:
    if not u or not u.startswith("http"):
        return ""
    p = urlparse(unquote(u))
    host = p.netloc.lower().removeprefix("www.")
    path = p.path.rstrip("/").lower()
    return f"{host}{path}"


def ia_id(u: str) -> str:
    m = re.search(r"archive\.org/(?:details|stream|download)/([^/?#]+)", u or "")
    return m.group(1).lower() if m else ""


def loc_key(u: str) -> str:
    m = re.search(r"loc\.gov/resource/([^/]+/\d{4}-\d{2}-\d{2}/ed-\d+)", u or "")
    return m.group(1).lower() if m else ""


def keys_for(url: str | None, item_id: str | None = None) -> set[str]:
    ks = set()
    n = norm_url(url)
    if n:
        ks.add("u:" + n)
    i = (item_id or "").lower() or ia_id(url or "")
    if i:
        ks.add("ia:" + i)
    l = loc_key(url or "")
    if l:
        ks.add("loc:" + l)
    return ks


def load_labels(path: Path | None) -> dict[tuple[str, str, str], str]:
    if not path or not path.exists():
        return {}
    out = {}
    for r in csv.DictReader(path.open()):
        if r.get("final_label"):
            out[(r["run_id"], r["subject_id"], r["record_key"])] = r["final_label"]
    return out


def score_run(run: dict, subject: dict, labels: dict) -> dict:
    recs = [r for r in subject["records"] if r.get("about_subject") is not False]
    idx: dict[str, list[dict]] = defaultdict(list)
    for r in recs:
        for k in keys_for(r.get("url")):
            idx[k].append(r)
    hits: dict[str, dict] = {}
    for n, c in enumerate(run.get("citations", [])):
        for k in keys_for(c.get("url"), c.get("item_id")):
            for r in idx.get(k, []):
                if r["key"] not in hits:
                    hits[r["key"]] = {"record": r, "depth": c.get("depth", 0), "order": n, "node": c.get("node")}
    by_tier = defaultdict(lambda: [0, 0])
    for r in recs:
        by_tier[r["tier"]][1] += 1
    for h in hits.values():
        by_tier[h["record"]["tier"]][0] += 1
    verified = [k for k in hits if labels.get((run["run_id"], subject["subject_id"], k)) == "correct_same_person"]
    for (rid, sid, k), lab in labels.items():  # T2/T3 identification, scored from labels only
        if rid == run["run_id"] and sid == subject["subject_id"] and lab == "identified_request_drafted" and k not in verified:
            verified.append(k)
    known_hosts = {r["host"] for r in recs}
    cited_hosts = {urlparse(c.get("url") or "").netloc.lower().removeprefix("www.") for c in run.get("citations", []) if c.get("url")}
    qs = run.get("questions", [])
    return {
        "run_id": run["run_id"], "agent": run["agent"], "subject_id": subject["subject_id"], "budget": run["budget"],
        "seed": run.get("seed"), "completed": run.get("completed"), "tool_calls": run.get("tool_calls"),
        "n_hidden": len(recs), "candidate_hits": len(hits), "candidate_recall": len(hits) / len(recs) if recs else None,
        "verified_hits": len(verified), "verified_recall": (len(verified) / len(recs)) if (recs and labels) else None,
        "by_tier": {t: {"hits": h, "n": n} for t, (h, n) in sorted(by_tier.items())},
        "hit_depths": sorted(h["depth"] for h in hits.values()),
        "first_hit_order": min((h["order"] for h in hits.values()), default=None),
        "hosts_cited": len(cited_hosts), "hosts_matching_records": len(cited_hosts & known_hosts),
        "questions": len(qs), "grounded_share": (sum(q.get("grounded", False) for q in qs) / len(qs)) if qs else None,
        "documented_claims": len(run.get("documented_claims", [])), "leads": len(run.get("leads", [])),
        "label_status": "adjudicated" if labels else "candidate only: no adjudication labels yet",
        "hits": [{"key": k, "tier": h["record"]["tier"], "depth": h["depth"], "node": h["node"]} for k, h in hits.items()],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("results", type=Path)
    ap.add_argument("--subjects", type=Path, default=ROOT / "bench" / "data" / "subjects.jsonl")
    ap.add_argument("--labels", type=Path)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    subs = {json.loads(l)["subject_id"]: json.loads(l) for l in a.subjects.read_text().splitlines() if l.strip()}
    labels = load_labels(a.labels)
    rows = []
    for line in a.results.read_text().splitlines():
        if not line.strip():
            continue
        run = json.loads(line)
        if run["subject_id"] in subs:
            rows.append(score_run(run, subs[run["subject_id"]], labels))
    out = a.out or a.results.with_suffix(".scores.jsonl")
    out.write_text("".join(json.dumps(r) + "\n" for r in rows))
    for r in rows:
        print(f"{r['agent']:<10} {r['subject_id']:<28} B={r['budget']:<4} calls={r['tool_calls']} hidden={r['n_hidden']:<4} "
              f"candidate hits={r['candidate_hits']} ({r['label_status']})")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
