"""Persistent search graph of one run, built from the search ledger (post hoc feature, added after the
v0.2 preregistration; it does not change any benchmark condition).

Nodes are entities: the subject person, relatives used as search keys, places named in findings, queries
(one per canonical id in the ledger), sources (an archive search or one book) and records (an item or page
a query returned). Edges carry provenance: which query searched which source, which query found which
record, which finding (a "Possible" fact, never a claim) came from which record and query, with a short
evidence snippet (at most SNIPPET chars, the scorer's limit; book page text is never stored).

    build_graph(ledger_rows, call_rows, run)  -> dict (graph.json)
    to_graphml(graph) / to_mermaid(graph)     -> str views
    done_queries(graph)                       -> {canonical_id: run_id} for the cache (Ledger.preload_cache)

The cache is off unless a run is started with ResearchRequest.graph_cache; the benchmark never sets it
(bench/harness.py refuses it for benchmark subjects).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from xml.sax.saxutils import escape

SCHEMA = "cr-search-graph/1"
SNIPPET = 240
TYPES = ("person", "relative", "place", "query", "source", "record", "fact")


def _nid(kind: str, key: str) -> str:
    return f"{kind}:{hashlib.sha1(key.encode()).hexdigest()[:12]}" if len(key) > 60 else f"{kind}:{key}"


class _G:
    def __init__(self):
        self.nodes: dict[str, dict] = {}
        self.edges: list[dict] = []
        self._ek: set = set()

    def node(self, kind: str, key: str, **attrs) -> str:
        i = _nid(kind, key)
        n = self.nodes.setdefault(i, {"id": i, "type": kind, "key": key})
        n.update({k: v for k, v in attrs.items() if v not in (None, "", [])})
        return i

    def edge(self, src: str, dst: str, rel: str, **prov) -> None:
        k = (src, dst, rel, prov.get("query"))
        if k in self._ek:
            return
        self._ek.add(k)
        self.edges.append({"source": src, "target": dst, "rel": rel, **{a: b for a, b in prov.items() if b not in (None, "", [])}})


def build_graph(ledger_rows: list[dict], call_rows: list[dict], run: dict, subject: dict | None = None) -> dict:
    g = _G()
    run_id = run.get("run_id", "")
    subj = (subject or {}).get("input") or subject or run.get("subject") or {}
    person = g.node("person", run.get("subject_id") or subj.get("full_name") or "subject", name=subj.get("full_name"),
                    birth_year=subj.get("birth_year"))
    q_by_cid: dict[str, str] = {}
    # queries and sources from the ledger: every reservation decision, allowed or not
    for r in ledger_rows:
        cid = r.get("canonical_id")
        if not cid:
            continue
        q = g.node("query", cid, tool=r.get("tool"), terms=r.get("terms"), lane=r.get("lane"))
        q_by_cid[cid] = q
        n = g.nodes[q]
        n.setdefault("decisions", [])
        n["decisions"].append({k: r[k] for k in ("decision", "key_type", "key_value", "reason") if r.get(k)})
        s = g.node("source", r.get("source") or "?", tool=r.get("tool"))
        g.edge(q, s, "searches", run=run_id, decision=r.get("decision"))
        g.edge(person, q, "about", run=run_id)
        for prior in r.get("prior_canonical_ids") or []:
            if prior != cid:
                g.edge(q, _nid("query", prior), "revisits" if r.get("decision") == "revisit" else "blocked_by", run=run_id,
                       key_type=r.get("key_type"), reason=(r.get("reason") or "")[:200])
        if r.get("key_type") == "relative_name" and r.get("key_value"):
            rel = g.node("relative", r["key_value"], name=r["key_value"])
            g.edge(person, rel, "relative_of", run=run_id, evidence="relative name used as a search key after the living-person gate")
            g.edge(q, rel, "uses_name_of", run=run_id)
    # outcome of each executed call
    for c in call_rows:
        cid = c.get("canonical")
        if not cid:
            continue
        q = q_by_cid.get(cid) or g.node("query", cid, tool=c.get("tool"), terms=c.get("terms"), lane=c.get("lane"))
        g.node("query", cid, done=c.get("decision") in ("new", "revisit", "unchecked") and not c.get("error"),
               n_items=c.get("n_items"), n_matched=c.get("n_matched"), round=c.get("round"), purpose=c.get("purpose"),
               error=c.get("error"), reward=c.get("reward"))
    # records and findings from the report: questions carry the canonical id, citations and leads the record
    q_of_question = {x.get("id"): x.get("key") for x in run.get("questions") or [] if x.get("key")}
    for cit in run.get("citations") or []:
        cid = q_of_question.get(cit.get("node"))
        rec = g.node("record", cit.get("item_id") or cit.get("url") or "?", title=cit.get("title"), url=cit.get("url"),
                     name_match=cit.get("name_match"))
        if cid:
            g.edge(_nid("query", cid), rec, "found", run=run_id, query=cid, verified=cit.get("name_match") == "strong")
    for ld in run.get("leads") or []:
        c = ld.get("citation") or {}
        cid = q_of_question.get(ld.get("question_id"))
        rec = g.node("record", c.get("item_id") or c.get("url") or ld.get("source_id") or "?", title=c.get("title"), url=c.get("url"),
                     year=c.get("year"))
        f = g.node("fact", ld.get("id") or ld.get("text") or "?", text=ld.get("text"), field=ld.get("field"), tier="Possible",
                   year=ld.get("year"))
        snip = (c.get("snippet") or ld.get("quote") or "")[:SNIPPET]
        g.edge(rec, f, "supports", run=run_id, query=cid, evidence=snip, matched_by=ld.get("matched_by"))
        g.edge(f, person, "about", run=run_id)
        if cid:
            g.edge(_nid("query", cid), f, "yielded", run=run_id, query=cid)
        if ld.get("field") in ("place", "birthplace", "residence", "death_place") and ld.get("value"):
            pl = g.node("place", str(ld["value"]), name=str(ld["value"]))
            g.edge(f, pl, "at", run=run_id, query=cid, evidence=snip)
    return {"schema": SCHEMA, "run_id": run_id, "agent": run.get("agent"), "subject_id": run.get("subject_id"),
            "note": "Findings are 'Possible' leads with their evidence, not claims. Snippets are capped; no page text.",
            "counts": {t: sum(1 for n in g.nodes.values() if n["type"] == t) for t in TYPES} | {"edges": len(g.edges)},
            "nodes": list(g.nodes.values()), "edges": g.edges}


def done_queries(graph: dict) -> dict[str, str]:
    """Canonical ids an earlier run actually executed (allowed and completed), for Ledger.preload_cache."""
    return {n["key"]: graph.get("run_id", "") for n in graph.get("nodes", []) if n["type"] == "query" and n.get("done")}


def load(path: str | Path) -> dict:
    g = json.loads(Path(path).read_text())
    if g.get("schema") != SCHEMA:
        raise ValueError(f"{path}: not a {SCHEMA} file")
    return g


def merge(graphs: list[dict]) -> dict:
    """Union of several runs' graphs (nodes by id, attributes of the first, edges deduplicated); a cache can
    span runs."""
    nodes, edges, seen = {}, [], set()
    for g in graphs:
        for n in g["nodes"]:
            nodes.setdefault(n["id"], dict(n))
            if n.get("done"):
                nodes[n["id"]]["done"] = True
        for e in g["edges"]:
            k = (e["source"], e["target"], e["rel"], e.get("query"), e.get("run"))
            if k not in seen:
                seen.add(k)
                edges.append(e)
    run_ids = [g.get("run_id", "") for g in graphs]
    return {"schema": SCHEMA, "run_id": "+".join(run_ids), "runs": run_ids, "nodes": list(nodes.values()), "edges": edges,
            "counts": {t: sum(1 for n in nodes.values() if n["type"] == t) for t in TYPES} | {"edges": len(edges)}}


def to_graphml(graph: dict) -> str:
    keys = ["type", "key", "name", "tool", "terms", "lane", "title", "url", "text", "tier", "done"]
    ek = ["rel", "run", "query", "evidence", "reason", "decision"]
    L = ['<?xml version="1.0" encoding="UTF-8"?>', '<graphml xmlns="http://graphml.graphdrawing.org/xmlns">']
    L += [f'  <key id="n_{k}" for="node" attr.name="{k}" attr.type="string"/>' for k in keys]
    L += [f'  <key id="e_{k}" for="edge" attr.name="{k}" attr.type="string"/>' for k in ek]
    L.append('  <graph id="G" edgedefault="directed">')
    for n in graph["nodes"]:
        L.append(f'    <node id="{escape(n["id"], {chr(34): "&quot;"})}">' + "".join(
            f'<data key="n_{k}">{escape(str(n[k]))}</data>' for k in keys if n.get(k) not in (None, "")) + "</node>")
    for i, e in enumerate(graph["edges"]):
        L.append(f'    <edge id="e{i}" source="{escape(e["source"], {chr(34): "&quot;"})}" target="{escape(e["target"], {chr(34): "&quot;"})}">' + "".join(
            f'<data key="e_{k}">{escape(str(e[k]))}</data>' for k in ek if e.get(k) not in (None, "")) + "</edge>")
    L += ["  </graph>", "</graphml>"]
    return "\n".join(L) + "\n"


def to_mermaid(graph: dict, max_nodes: int = 200) -> str:
    """A readable view: person, relatives, places, sources, executed queries that found something, records, facts."""
    keep = [n for n in graph["nodes"] if n["type"] != "query" or (n.get("n_matched") or 0) > 0][:max_nodes]
    ids = {n["id"]: f"n{i}" for i, n in enumerate(keep)}
    shape = {"person": ("((", "))"), "relative": ("((", "))"), "place": ("[/", "/]"), "query": ("[", "]"), "source": ("[(", ")]"),
             "record": ("[[", "]]"), "fact": ("{{", "}}")}

    def lab(n):
        t = n.get("name") or n.get("title") or n.get("terms") or n.get("text") or n["key"]
        t = str(t).replace('"', "'").replace("\n", " ")[:60]
        return f'"{n["type"]}: {t}"'
    L = ["graph LR"]
    for n in keep:
        a, b = shape[n["type"]]
        L.append(f"  {ids[n['id']]}{a}{lab(n)}{b}")
    for e in graph["edges"]:
        if e["source"] in ids and e["target"] in ids:
            L.append(f"  {ids[e['source']]} -->|{e['rel']}| {ids[e['target']]}")
    return "\n".join(L) + "\n"


def write_all(graph: dict, stem: Path) -> list[Path]:
    """Write <stem>.graph.json, <stem>.graphml and <stem>.mmd."""
    out = [stem.with_name(stem.name + ".graph.json"), stem.with_name(stem.name + ".graphml"), stem.with_name(stem.name + ".mmd")]
    out[0].write_text(json.dumps(graph, indent=1, default=str))
    out[1].write_text(to_graphml(graph))
    out[2].write_text(to_mermaid(graph))
    return out
