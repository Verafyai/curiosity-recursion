"""Live clients for public, keyless endpoints only.

- Optional public source catalog: GET {CR_CATALOG_URL}/v1/sources and /v1/taxonomy (off when
  CR_CATALOG_URL is empty; read-only GETs, nothing that spends credits)
- Wikidata: wbsearchentities, wbgetentities
- Internet Archive: advancedsearch (metadata), FTS (full text across books),
  fulltext/inside.php (search inside one book)
- Library of Congress Chronicling America via loc.gov JSON

Polite by design: one user agent carrying a contact address from CR_CONTACT, small result
pages, and nothing fetched where terms forbid it (Find a Grave is links only).
Transient failures (timeouts, 5xx, 429) raise so Temporal retries the activity.
"""

from __future__ import annotations

import os
import re
from typing import Any
from urllib.parse import quote

import httpx

UA = f"curiosity-recursion/0.1 (+{os.environ.get('CR_CONTACT', 'set CR_CONTACT to a contact address')})"
LINEAGE_API = os.environ.get("CR_CATALOG_URL", "").rstrip("/")


class Transient(Exception):
    pass


async def get_json(url: str, params: dict | None = None, timeout: float = 30) -> Any:
    try:
        async with httpx.AsyncClient(headers={"User-Agent": UA, "Accept": "application/json"}, timeout=timeout, follow_redirects=True) as c:
            r = await c.get(url, params=params)
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        raise Transient(f"{type(exc).__name__} on {url}") from exc
    if r.status_code >= 500 or r.status_code == 429:
        raise Transient(f"HTTP {r.status_code} on {url}")
    if r.status_code >= 400:
        raise ValueError(f"HTTP {r.status_code} on {r.url}")
    return r.json()


# ---- Lineage catalog -------------------------------------------------------

async def lineage_catalog() -> tuple[dict, dict]:
    sources = await get_json(f"{LINEAGE_API}/v1/sources")
    taxonomy = await get_json(f"{LINEAGE_API}/v1/taxonomy")
    return sources, taxonomy


# ---- Wikidata --------------------------------------------------------------

WD = "https://www.wikidata.org/w/api.php"


async def wikidata_search(name: str, limit: int = 7) -> list[dict]:
    d = await get_json(WD, {"action": "wbsearchentities", "search": name, "language": "en", "format": "json", "limit": limit, "type": "item"})
    return d.get("search", [])


async def wikidata_entities(ids: list[str], props: str = "claims|labels|descriptions") -> dict:
    if not ids:
        return {}
    d = await get_json(WD, {"action": "wbgetentities", "ids": "|".join(ids), "props": props, "languages": "en", "format": "json"})
    return d.get("entities", {})


def wd_year(entity: dict, prop: str) -> int | None:
    for c in entity.get("claims", {}).get(prop, []):
        t = c.get("mainsnak", {}).get("datavalue", {}).get("value", {}).get("time")
        if t:
            m = re.match(r"[+-](\d{4})", t)
            if m:
                return int(m.group(1))
    return None


def wd_items(entity: dict, prop: str) -> list[str]:
    out = []
    for c in entity.get("claims", {}).get(prop, []):
        v = c.get("mainsnak", {}).get("datavalue", {}).get("value", {})
        if isinstance(v, dict) and v.get("id"):
            out.append(v["id"])
    return out


# ---- Internet Archive ------------------------------------------------------

async def ia_title_search(q: str, rows: int = 6) -> list[dict]:
    d = await get_json(
        "https://archive.org/advancedsearch.php",
        {"q": f"({q}) AND mediatype:texts", "fl[]": ["identifier", "title", "year"], "rows": rows, "output": "json", "sort[]": "downloads desc"},
    )
    return d.get("response", {}).get("docs", [])


async def ia_fulltext(phrase: str, rows: int = 8) -> list[dict]:
    """Full-text search across Internet Archive books. Returns identifier, title, year, highlight snippets."""
    d = await get_json(
        "https://archive.org/services/search/beta/page_production/",
        {"service_backend": "fts", "user_query": phrase, "hits_per_page": rows},
        timeout=45,
    )
    body = (d.get("response") or {}).get("body") or {}
    out = []
    for h in (body.get("hits") or {}).get("hits", []):
        f = h.get("fields", {})
        snips = (h.get("highlight") or {}).get("text", [])
        out.append({"identifier": f.get("identifier"), "title": f.get("title"), "year": f.get("year"), "snippets": [clean_snip(s) for s in snips[:3]]})
    return out


async def ia_inside(item_id: str, q: str) -> list[dict]:
    """Search inside one digitised book. Returns [{text, page}] with the match marked **like this**."""
    meta = await get_json(f"https://archive.org/metadata/{quote(item_id)}", timeout=30)
    server, path = meta.get("server") or meta.get("d1"), meta.get("dir")
    if not server or not path:
        return []
    d = await get_json(
        f"https://{server}/fulltext/inside.php",
        {"item_id": item_id, "doc": item_id, "path": path, "q": q},
        timeout=40,
    )
    out = []
    for m in d.get("matches", []) or []:
        page = (m.get("par") or [{}])[0].get("page")
        out.append({"text": clean_snip(m.get("text", "")), "page": page})
    return out


FTS_API = "https://be-api.us.archive.org/ia-pub-fts-api"


async def post_json(url: str, body: dict, timeout: float = 45) -> Any:
    try:
        async with httpx.AsyncClient(headers={"User-Agent": UA, "Accept": "application/json"}, timeout=timeout, follow_redirects=True) as c:
            r = await c.post(url, json=body)
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        raise Transient(f"{type(exc).__name__} on {url}") from exc
    if r.status_code >= 500 or r.status_code == 429:
        raise Transient(f"HTTP {r.status_code} on {url}")
    if r.status_code >= 400:
        raise ValueError(f"HTTP {r.status_code} on {url}")
    return r.json()


def parse_fts(d: Any) -> list[dict]:
    """Rows from the public FTS API body. `user_message` or `UPSTREAM_ERROR` bodies are errors."""
    if not isinstance(d, dict):
        raise ValueError("FTS API returned a non-object body")
    if d.get("user_message") or "UPSTREAM_ERROR" in str(d.get("error", "")) or d.get("error"):
        msg = str(d.get("user_message") or d.get("error"))[:200]
        if "UPSTREAM_ERROR" in msg or "UPSTREAM_ERROR" in str(d.get("error", "")):
            raise Transient(f"FTS API upstream error: {msg}")
        raise ValueError(f"FTS API error: {msg}")
    out = []
    for h in ((d.get("hits") or {}).get("hits") or []):
        f = h.get("fields") or {}
        one = lambda k: (f.get(k) or [None])[0] if isinstance(f.get(k), list) else f.get(k)  # noqa: E731
        pages = f.get("page_num") or []
        page = pages[0][0] if pages and isinstance(pages[0], list) and pages[0] else (pages[0] if pages else None)
        out.append({"identifier": one("identifier"), "title": one("meta_title"), "year": one("meta_year"), "page": page,
                    "collection": f.get("meta_collection") or [],
                    "snippets": [clean_snip(x) for x in ((h.get("highlight") or {}).get("text") or [])[:3]]})
    return out


async def ia_fts(query: str, size: int = 10, offset: int = 0, collection: str | None = None) -> list[dict]:
    """Internet Archive full-text search through the public FTS API (documented in the internetarchive
    Python library). Lucene syntax with the `!L` prefix; `offset` pages through results; `collection`
    adds a `collection:` clause (checked 26 Nov 2026: returned hits carry that collection)."""
    q = f"!L {query}" + (f" AND collection:{collection}" if collection else "")
    d = await post_json(FTS_API, {"q": q, "size": str(size), "from": str(offset), "scroll": False}, timeout=45)
    return parse_fts(d)


async def ia_inside_pages(item_id: str, q: str, first: int, last: int) -> list[dict]:
    """Search inside one book, keeping only matches on page images first..last (the adjacent_pages key).
    The returned list is all the agent is shown, so the tool log holds only the window."""
    return [m for m in await _ia_inside_raw(item_id, q) if m.get("page") is not None and first <= int(m["page"]) <= last]


async def _ia_inside_raw(item_id: str, q: str) -> list[dict]:
    return await _INSIDE(item_id, q)


def clean_snip(s: str) -> str:
    s = s.replace("<IA_FTS_MATCH>", "**").replace("</IA_FTS_MATCH>", "**")
    s = s.replace("{{{", "**").replace("}}}", "**")
    return re.sub(r"\s+", " ", s).strip()


# ---- Chronicling America (loc.gov) -----------------------------------------

async def chronam(q: str, years: tuple[int, int] | None, rows: int = 6) -> list[dict]:
    params: dict[str, Any] = {"q": q, "fo": "json", "c": rows, "at": "results,pagination"}
    if years:
        params["dates"] = f"{years[0]}/{years[1]}"
    d = await get_json("https://www.loc.gov/collections/chronicling-america/", params, timeout=70)
    out = []
    for r in d.get("results", []):
        desc = r.get("description") or []
        out.append({
            "title": r.get("title"),
            "date": r.get("date"),
            "url": r.get("url") or r.get("id"),
            "text": (desc[0] if isinstance(desc, list) and desc else str(desc))[:4000],
        })
    return out


# ---- Offline mock mode (tests and the mock bench) ---------------------------
# CR_SOURCES=mock swaps every network client for the deterministic synthetic archive in
# cr/sources/mock_live.py, before the tool log and exclusion wrappers are installed, so the mock
# bench is logged and filtered exactly like a live run. No network is touched.
_INSIDE = ia_inside
if os.environ.get("CR_SOURCES") == "mock":
    from cr.sources import mock_live as _mock
    for _n in ("wikidata_search", "wikidata_entities", "ia_title_search", "ia_fulltext", "ia_inside", "chronam", "ia_fts"):
        globals()[_n] = getattr(_mock, _n)
    _INSIDE = _mock.ia_inside


# ---- Optional raw tool log (corpus-replication eval) ------------------------
# When CR_TOOL_LOG is set, every public lookup appends {fn, args, result} to that JSONL file, so an
# evaluator can see exactly what text each agent was shown. Off by default; no effect on results.
def _cap(x, depth: int = 0):
    """Bounded copy for the tool log: at most 400 items per list and 6,000 characters per string, so
    every line stays valid JSON (an earlier version cut the serialized line and lost whole results)."""
    if isinstance(x, str):
        return x[:6000]
    if isinstance(x, list):
        return [_cap(v, depth + 1) for v in x[:400]]
    if isinstance(x, dict):
        return {k: _cap(v, depth + 1) for k, v in x.items()} if depth < 6 else str(x)[:2000]
    return x


def _install_tool_log() -> None:
    import functools
    import json as _json
    import os as _os
    import time as _time
    from cr.sources import exclusion as _ex
    path = _os.environ.get("CR_TOOL_LOG")
    g = globals()
    for _name in ("wikidata_search", "wikidata_entities", "ia_title_search", "ia_fulltext", "ia_inside", "chronam", "ia_fts", "ia_inside_pages"):
        _fn = g.get(_name)
        if _fn is None:
            continue

        def _wrap(fn=_fn, name=_name):
            @functools.wraps(fn)
            async def inner(*a, **k):
                err, res = None, None
                try:
                    if _ex.check_query(name, a, k):
                        res = {} if name == "wikidata_entities" else []
                    else:
                        res = _ex.filter_result(name, a, await fn(*a, **k))
                    return res
                except Exception as e:  # noqa: BLE001
                    err = f"{type(e).__name__}: {e}"[:300]
                    raise
                finally:
                    if path:
                        try:
                            with open(path, "a") as fh:
                                fh.write(_json.dumps({"t": _time.time(), "pid": _os.getpid(), "fn": name, "args": [str(x)[:300] for x in a],
                                                      "kwargs": {kk: str(v)[:300] for kk, v in k.items()}, "error": err,
                                                      "result": _cap(res)}, default=str) + "\n")
                        except Exception:  # noqa: BLE001
                            pass
            return inner
        g[_name] = _wrap()


_install_tool_log()
