"""Deterministic synthetic archive for tests and the mock bench (CR_SOURCES=mock). No network.

Every answer is a pure function of the query, so two calls with the same arguments return the same
rows, and a run can be replayed. Rows echo the searched name inside short synthetic snippets with
years, so the swarm's leads (books, pages, name variants, result pages) have something to follow.
Nothing here is a real record; ids start with `mock-` so no output can be mistaken for one.
"""
from __future__ import annotations

import hashlib
import re


def _h(*parts) -> int:
    return int(hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:12], 16)


def _phrase(q: str) -> str:
    m = re.search(r'"([^"]+)"', q)
    words = (m.group(1) if m else q).split()
    return " ".join(w for w in words if w[:1].isupper() or len(words) <= 3) or q


def _year(q: str, k: int) -> int:
    m = re.search(r"\b(1[6-9]\d\d)\b", q)
    return (int(m.group(1)) if m else 1840) + 20 + k % 40


def _book(q: str, k: int) -> dict:
    n = _h("book", _phrase(q).lower(), k) % 40
    return {"identifier": f"mock-book-{n:02d}", "title": f"Mock county history volume {n}", "year": 1880 + n}


async def ia_fts(query: str, size: int = 10, offset: int = 0, collection: str | None = None) -> list[dict]:
    if _h("fts-empty", query, offset, collection) % 5 == 0 or offset >= 40:
        return []
    ph = _phrase(query)
    out = []
    for k in range(offset, offset + min(size, 4)):
        b = _book(query + str(collection), k)
        out.append({**b, "page": 10 + (_h("pg", query, k) % 300), "collection": [collection or "americana"],
                    "snippets": [f"in {_year(query, k)} **{ph}** was listed among the residents of the town"]})
    return out


async def ia_fulltext(phrase: str, rows: int = 8) -> list[dict]:
    if _h("ft-empty", phrase) % 4 == 0:
        return []
    ph = _phrase(phrase)
    return [{**_book(phrase, k), "snippets": [f"**{ph}** married in {_year(phrase, k)} at the church"]} for k in range(3)]


async def ia_inside(item_id: str, q: str) -> list[dict]:
    if _h("in-empty", item_id, q) % 3 == 0:
        return []
    base = 10 + _h("inside", item_id) % 200
    return [{"text": f"... **{q}** son of the late settler, born {1830 + _h(item_id, k) % 30} ...", "page": base + 7 * k} for k in range(3)]


async def ia_title_search(q: str, rows: int = 6) -> list[dict]:
    if _h("title-empty", q) % 3 == 0:
        return []
    return [_book(q, k) for k in range(2)]


async def chronam(q: str, years, rows: int = 6) -> list[dict]:
    if _h("ca-empty", q, years) % 3 == 0:
        return []
    y0 = years[0] if years else 1860
    ph = _phrase(q)
    return [{"title": f"Mock Gazette page {k}", "date": f"{y0 + k}-05-01",
             "url": f"https://www.loc.gov/resource/sn0000000{_h(q, years) % 9}/{y0 + k}-05-01/ed-1/?sp=2",
             "text": f"Local items. {ph} returned home in {y0 + k}."} for k in range(2)]


async def wikidata_search(name: str, limit: int = 7) -> list[dict]:
    return [] if _h("wd", name) % 2 else [{"id": f"Q9{_h('wdq', name) % 9000000:07d}", "label": name}]


async def wikidata_entities(ids: list[str], props: str = "claims|labels|descriptions") -> dict:
    return {i: {"labels": {"en": {"value": f"mock person {i}"}}, "descriptions": {"en": {"value": "mock"}}, "claims": {}} for i in ids}
