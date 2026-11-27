"""Draw a search graph (cr/search_graph.py graph.json) as a layered figure: person, queries by lane,
sources, records, findings. Post hoc feature. Labels are short; no snippets are drawn.
    python scripts/plot_graph.py <run>.graph.json --out fig.pdf [--max-queries 60] [--no-labels]
"""
import argparse
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

COLS = ["person", "query", "source", "record", "fact"]
COLOR = {"person": "#1f3b63", "relative": "#1f3b63", "place": "#7a6a8f", "query": "#9a9a9a", "source": "#2e7d4f",
         "record": "#c27c0e", "fact": "#b23b3b"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("graph", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--max-queries", type=int, default=200)
    ap.add_argument("--labels", action="store_true", help="label sources (never person names beyond the subject)")
    a = ap.parse_args()
    g = json.loads(a.graph.read_text())
    nodes = {n["id"]: n for n in g["nodes"]}
    # keep executed queries, sources they searched, records they found, findings from those records
    q = [n for n in g["nodes"] if n["type"] == "query" and n.get("done")]
    q.sort(key=lambda n: (n.get("lane") or "", -(n.get("n_matched") or 0)))
    q = q[: a.max_queries]
    keep = {n["id"] for n in q} | {n["id"] for n in g["nodes"] if n["type"] == "person"}
    for e in g["edges"]:
        if e["source"] in keep and e["rel"] in ("searches", "found", "yielded"):
            keep.add(e["target"])
    for e in g["edges"]:
        if e["source"] in keep and e["rel"] == "supports":
            keep.add(e["target"])
    col = {t: [nodes[i] for i in keep if i in nodes and (nodes[i]["type"] == t or (t == "person" and nodes[i]["type"] in ("relative", "place")))] for t in COLS}
    pos = {}
    for x, t in enumerate(COLS):
        ns = sorted(col[t], key=lambda n: (n.get("lane") or "", n["key"]))
        for i, n in enumerate(ns):
            pos[n["id"]] = (x, (i + 0.5) / max(1, len(ns)))
    fig, ax = plt.subplots(figsize=(7.0, 4.6))
    for e in g["edges"]:
        if e["source"] in pos and e["target"] in pos and e["rel"] in ("about", "searches", "found", "supports", "revisits"):
            (x0, y0), (x1, y1) = pos[e["source"]], pos[e["target"]]
            if e["rel"] == "about" and nodes.get(e["source"], {}).get("type") == "fact":
                continue
            if e["rel"] == "revisits":  # query to earlier query in the same column: draw as an arc to the left
                ax.plot([x0, x0 - 0.12 - 0.3 * abs(y1 - y0), x1], [y0, (y0 + y1) / 2, y1], lw=0.4, color="#c0392b", alpha=0.7, zorder=1)
            else:
                ax.plot([x0, x1], [y0, y1], lw=0.25, color="#bbbbbb", alpha=0.6, zorder=1)
    for i, (x, y) in pos.items():
        n = nodes[i]
        ax.scatter([x], [y], s=14 if n["type"] != "person" else 60, color=COLOR[n["type"]], zorder=2)
        if n["type"] == "person" or (a.labels and n["type"] == "source"):
            ax.text(x + 0.04, y, str(n.get("name") or n["key"])[:40], fontsize=5, va="center")
    ax.set_xticks(range(len(COLS)))
    NAMES = {"person": "person", "query": "queries run", "source": "sources", "record": "records found", "fact": "findings (Possible)"}
    ax.set_xticklabels([f"{NAMES[t]} ({len(col[t])})" for t in COLS], fontsize=7)
    ax.set_yticks([])
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.set_title(f"search graph of run {g.get('run_id', '')[:48]}: {g['counts'].get('query', 0)} queries, {g['counts'].get('edges', 0)} edges "
                 "(red: ledger-approved revisits)", fontsize=7)
    fig.tight_layout()
    a.out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(a.out, dpi=200)
    print("wrote", a.out)


if __name__ == "__main__":
    sys.exit(main())
