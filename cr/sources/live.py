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
    for _name in ("wikidata_search", "wikidata_entities", "ia_title_search", "ia_fulltext", "ia_inside", "chronam"):
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
