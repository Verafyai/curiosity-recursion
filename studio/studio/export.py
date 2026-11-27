"""Export an Explore graph as graph.json, GraphML or Mermaid. Pure."""
from __future__ import annotations

from xml.sax.saxutils import escape

from studio.explore import ExploreProgress


def to_json(p: ExploreProgress) -> dict:
    nodes = [{"id": n.id, "kind": n.kind, "label": n.label, "tier": n.tier, "depth": n.depth, "summary": n.summary,
              "citations": [c.model_dump(mode="json") for c in n.citations]} for n in p.nodes]
    edges = [{"source": n.parent_id, "target": n.id, "via_question": n.via_question,
              "question": next((q.text for q in p.questions if q.id == n.via_question), "")} for n in p.nodes if n.parent_id]
    qs = [q.model_dump(mode="json", include={"id", "node_id", "text", "because", "generator", "kind", "status", "answer", "produced"}) for q in p.questions]
    return {"schema": "lineage-explore-graph/1", "workflow_id": p.workflow_id, "person": p.request.person.model_dump(mode="json") if p.request else None,
            "nodes": nodes, "edges": edges, "questions": qs, "calls_used": p.calls_used}


def to_graphml(p: ExploreProgress) -> str:
    nk = ["kind", "label", "tier", "depth", "url"]
    L = ['<?xml version="1.0" encoding="UTF-8"?>', '<graphml xmlns="http://graphml.graphdrawing.org/xmlns">']
    L += [f'  <key id="n_{k}" for="node" attr.name="{k}" attr.type="string"/>' for k in nk]
    L += ['  <key id="e_question" for="edge" attr.name="question" attr.type="string"/>', '  <graph id="G" edgedefault="directed">']
    q = {x.id: x.text for x in p.questions}
    for n in p.nodes:
        vals = {"kind": n.kind, "label": n.label, "tier": n.tier, "depth": str(n.depth), "url": n.citations[0].url if n.citations and n.citations[0].url else ""}
        L.append(f'    <node id="{escape(n.id)}">' + "".join(f'<data key="n_{k}">{escape(v)}</data>' for k, v in vals.items() if v) + "</node>")
    for i, n in enumerate(x for x in p.nodes if x.parent_id):
        L.append(f'    <edge id="e{i}" source="{escape(n.parent_id)}" target="{escape(n.id)}"><data key="e_question">{escape(q.get(n.via_question or "", ""))}</data></edge>')
    L += ["  </graph>", "</graphml>"]
    return "\n".join(L) + "\n"


def to_mermaid(p: ExploreProgress) -> str:
    def lab(s: str) -> str:
        return s.replace('"', "'").replace("[", "(").replace("]", ")")[:70]
    L = ["graph TD"]
    for n in p.nodes:
        tag = " (Possible)" if n.tier == "possible" else ""
        L.append(f'  {n.id}["{lab(n.label)}{tag}"]')
    for n in p.nodes:
        if n.parent_id:
            L.append(f"  {n.parent_id} --> {n.id}")
    return "\n".join(L) + "\n"
