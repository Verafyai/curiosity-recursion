"""ia_fts: request shape and error handling, with recorded response shapes (no network)."""
import asyncio

import pytest

from cr.sources import live

RECORDED = {"took": 209, "timed_out": False, "hits": {"total": 2, "hits": [
    {"_id": "mockitem0001|x", "highlight": {"text": ["the {{{Tester}}} family of the town", "more"]},
     "fields": {"identifier": ["mockitem0001"], "meta_title": ["Mock history"], "meta_year": [1885], "page_num": [[194]],
                "meta_collection": ["americana"]}}]}}


def test_request_shape(monkeypatch):
    seen = {}

    async def fake_post(url, body, timeout=45):
        seen.update(url=url, body=body)
        return RECORDED
    monkeypatch.setattr(live, "post_json", fake_post)
    raw = live.ia_fts.__wrapped__ if hasattr(live.ia_fts, "__wrapped__") else live.ia_fts
    rows = asyncio.run(raw('"josiah tester"', size=5, offset=10, collection="americana"))
    assert seen["url"] == "https://be-api.us.archive.org/ia-pub-fts-api"
    assert seen["body"] == {"q": '!L "josiah tester" AND collection:americana', "size": "5", "from": "10", "scroll": False}
    assert rows[0]["identifier"] == "mockitem0001" and rows[0]["page"] == 194 and rows[0]["year"] == 1885
    assert rows[0]["snippets"][0] == "the **Tester** family of the town"


def test_error_bodies():
    with pytest.raises(ValueError):
        live.parse_fts({"user_message": "bad query"})
    with pytest.raises(live.Transient):
        live.parse_fts({"error": "UPSTREAM_ERROR: timeout"})
    assert live.parse_fts({"hits": {"hits": []}}) == []
