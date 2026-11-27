"""Live clients for public, keyless endpoints only.

- Lineage catalog: GET https://api.lineage.rexstjohn.com/v1/sources and /v1/taxonomy
  (never POST /v1/searches or /v1/runs: those need a key and spend credits)
- Wikidata: wbsearchentities, wbgetentities
- Internet Archive: advancedsearch (metadata), FTS (full text across books),
  fulltext/inside.php (search inside one book)
- Library of Congress Chronicling America via loc.gov JSON

Transient failures (timeouts, 5xx, 429) raise so Temporal retries the activity.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

import httpx

UA = "lineage-studio-temporal/0.1 (local demo; contact rex@verafy.ai)"
LINEAGE_API = "https://api.lineage.rexstjohn.com"


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
