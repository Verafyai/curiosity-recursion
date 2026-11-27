"""Budget-matched scoring (spec v0.2 section 9): only the first N logged calls count."""
import json

from eval.corpus.score import evidence


def test_evidence_truncates_to_first_n_calls(tmp_path):
    tl = tmp_path / "t.tools.jsonl"
    rows = [{"fn": "ia_fts", "args": [f"q{i}"], "kwargs": {}, "error": None,
             "result": [{"identifier": f"item{i}", "title": "t", "snippets": ["x"]}]} for i in range(5)]
    tl.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    assert len(evidence(tl)) == 5
    got = evidence(tl, max_calls=2)
    assert [sorted(i["keys"]) for i in got] == [["ia:item0"], ["ia:item1"]]


def test_inside_pages_keyed_like_inside(tmp_path):
    tl = tmp_path / "t.tools.jsonl"
    tl.write_text(json.dumps({"fn": "ia_inside_pages", "args": ["bookx", "q", 1, 9], "kwargs": {}, "error": None,
                              "result": [{"text": "a **b**", "page": 3}]}) + "\n")
    assert evidence(tl)[0]["keys"] == {"ia:bookx"}
