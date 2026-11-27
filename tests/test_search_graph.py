"""Post hoc search graph and graph cache (added after the v0.2 preregistration; off for every benchmark condition)."""
import asyncio
import json
import os
import xml.dom.minidom

import pytest

from cr import search_graph as sg
from cr.ledger import Ledger, QuerySpec, canonical_id
from cr.models import Person, ResearchRequest

LEDGER = [{"decision": "new", "canonical_id": "aaa", "requested_by": "w-r1-census", "tool": "ia_fts", "source": "ia_fts:*",
           "terms": '"Josiah Tester" 1860', "lane": "census"},
          {"decision": "revisit", "canonical_id": "bbb", "requested_by": "w-r2-census", "tool": "ia_inside_pages", "source": "ia_book:mock-book-1",
           "terms": "Tester", "lane": "census", "key_type": "adjacent_pages", "key_value": "11-20", "prior_canonical_ids": ["aaa"],
           "reason": "adjacent pages 11-20 after hit on page 9"},
          {"decision": "blocked_repeat", "canonical_id": "aaa", "requested_by": "w-r2-church", "tool": "ia_fts", "source": "ia_fts:*",
           "terms": '"Josiah Tester" 1860', "lane": "church", "reason": "exact repeat of aaa"},
          {"decision": "revisit", "canonical_id": "ccc", "requested_by": "w-r3-census", "tool": "ia_fts", "source": "ia_fts:*",
           "terms": '"Ann Tester"', "lane": "census", "key_type": "relative_name", "key_value": "Ann Tester", "reason": "relative name"}]
CALLS = [{"canonical": "aaa", "decision": "new", "tool": "ia_fts", "n_items": 3, "n_matched": 1, "round": 1, "error": ""},
         {"canonical": "bbb", "decision": "revisit", "tool": "ia_inside_pages", "n_items": 0, "n_matched": 0, "round": 2, "error": ""},
         {"canonical": "ccc", "decision": "revisit", "tool": "ia_fts", "n_items": 0, "n_matched": 0, "round": 3, "error": "Transient: HTTP 503"}]
RUN = {"run_id": "run-1", "agent": "B6-swarm", "subject_id": "mock-tester",
       "questions": [{"id": "c1", "key": "aaa"}, {"id": "c2", "key": "bbb"}],
       "citations": [{"url": "https://archive.org/details/mock-book-1", "item_id": "mock-book-1", "title": "Mock history", "node": "c1", "name_match": "strong"}],
       "leads": [{"id": "lead-1", "field": "residence", "value": "Mockton", "text": "Named in Mock history", "question_id": "c1",
                  "quote": "x" * 1000, "citation": {"item_id": "mock-book-1", "url": "https://archive.org/details/mock-book-1",
                                                     "snippet": "in 1860 **Josiah Tester** lived in Mockton " + "y" * 900}}]}
SUBJ = {"subject_id": "mock-tester", "input": {"full_name": "Josiah Quill Tester", "birth_year": 1840}}


def graph():
    return sg.build_graph(LEDGER, CALLS, RUN, SUBJ)


def test_graph_entities_and_provenance():
    g = graph()
    types = {n["type"] for n in g["nodes"]}
    assert {"person", "relative", "place", "query", "source", "record", "fact"} <= types
    by = {(e["source"], e["target"], e["rel"]) for e in g["edges"]}
    assert ("query:aaa", "record:mock-book-1", "found") in by
    assert ("query:bbb", "query:aaa", "revisits") in by
    sup = next(e for e in g["edges"] if e["rel"] == "supports")
    assert sup["query"] == "aaa" and sup["run"] == "run-1" and "Josiah Tester" in sup["evidence"]
    fact = next(n for n in g["nodes"] if n["type"] == "fact")
    assert fact["tier"] == "Possible"  # findings are leads, never claims
    person = next(n for n in g["nodes"] if n["type"] == "person")
    assert person["name"] == "Josiah Quill Tester"


def test_snippets_capped_no_page_text():
    g = graph()
    assert all(len(e.get("evidence", "")) <= sg.SNIPPET for e in g["edges"])
    assert "x" * 300 not in json.dumps(g)


def test_views_are_valid():
    g = graph()
    xml.dom.minidom.parseString(sg.to_graphml(g))
    m = sg.to_mermaid(g)
    assert m.startswith("graph LR") and "-->|found|" in m


def test_done_queries_only_successful_executed_calls(tmp_path):
    g = graph()
    done = sg.done_queries(g)
    assert set(done) == {"aaa", "bbb"} and done["aaa"] == "run-1"  # ccc failed, so a later run may try it again
    sg.write_all(g, tmp_path / "r1")
    assert sg.load(tmp_path / "r1.graph.json")["run_id"] == "run-1"
    with pytest.raises(ValueError):
        (tmp_path / "bad.json").write_text("{}")
        sg.load(tmp_path / "bad.json")


def test_cache_skips_done_queries_without_charge():
    spec = QuerySpec(tool="ia_fts", terms='"Josiah Tester" 1860')
    cid = canonical_id(spec)
    led = Ledger(life_window=(1840, 1940))
    led.preload_cache({cid: "run-1"})
    d = led.reserve(spec, "w")
    assert d.decision == "cached" and not d.allowed and "run-1" in d.reason
    assert cid not in led.s.entries  # nothing reserved, nothing charged
    other = led.reserve(QuerySpec(tool="ia_fts", terms='"Josiah Tester" regiment'), "w")
    assert other.allowed


def test_cache_off_by_default_and_for_benchmark_conditions():
    from bench.harness import AGENT_CONFIG
    r = ResearchRequest(person=Person(full_name="Josiah Quill Tester", birth_year=1840))
    assert r.graph_cache is None
    assert all("graph_cache" not in cfg for cfg in AGENT_CONFIG.values())
    assert Ledger().s.cached == {}


def test_harness_refuses_cache_for_benchmark_subject(monkeypatch):
    from bench import harness
    monkeypatch.setenv("CR_GRAPH_CACHE", "/tmp/none.graph.json")
    subj = {"subject_id": "corpus-burnham", "split": "corpus", "circuit": "vital_records", "input": {"full_name": "X Y", "birth_year": 1834}}
    with pytest.raises(SystemExit):
        asyncio.run(harness.run_temporal(None, "tq", "B6-swarm", subj, 100, 1, {}))
