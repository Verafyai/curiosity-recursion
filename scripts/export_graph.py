"""Export the persistent search graph (graph.json, GraphML, Mermaid) for every swarm run in a run dir, from
its ledger files. Post hoc feature added after the v0.2 preregistration; it reads finished runs only and
changes no result.
    python scripts/export_graph.py <run dir> [--out <run dir>/graphs] [--subjects eval/corpus/subjects.jsonl]
Graphs of benchmark people stay in the gitignored run dir (they hold snippets about family members).
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cr import search_graph as sg  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("rundir", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--subjects", type=Path, default=ROOT / "eval/corpus/subjects.jsonl")
    a = ap.parse_args()
    out = a.out or a.rundir / "graphs"
    out.mkdir(parents=True, exist_ok=True)
    subj = {}
    if a.subjects.exists():
        for line in a.subjects.read_text().splitlines():
            if line.strip():
                d = json.loads(line)
                subj[d["subject_id"]] = d
    n = 0
    for led in sorted((a.rundir / "ledgers").glob("*.ledger.jsonl")):
        stem = led.name[: -len(".ledger.jsonl")]
        calls = a.rundir / "ledgers" / f"{stem}.calls.jsonl"
        runf = a.rundir / "runs" / f"{stem}.jsonl"
        if not runf.exists():
            continue
        run = json.loads([x for x in runf.read_text().splitlines() if x.strip()][-1])
        rows = lambda p: [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.exists() else []  # noqa: E731
        g = sg.build_graph(rows(led), rows(calls), run, subj.get(run.get("subject_id")))
        sg.write_all(g, out / stem)
        n += 1
        print(stem, g["counts"])
    print(f"wrote {n} graphs to {out}")


if __name__ == "__main__":
    main()
