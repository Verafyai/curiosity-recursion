"""Leakage exclusion filter applied to every tool result, for every condition (B0 to B5).

Two layers:

1. Host/URL blocklist. Any result item whose serialized form mentions a blocked host or path
   (the dossier author's own sites, his GitHub orgs, his X accounts, Vercel deployments, and
   web.archive.org / archive.today snapshots of any of those) is dropped. Queries that name a
   blocked host are refused before the call is made.
2. Content guard. Any result item that shares too many word 8-grams with the frozen dossier
   text is dropped, which catches mirrors and scrapes on hosts the blocklist does not know.
   The index holds only 64-bit hashes of 8-grams (CR_DOSSIER_NGRAMS); quoted passages and
   reference lists are removed before hashing so a primary source the dossier quotes is not
   mistaken for a copy of the dossier.

Every block or drop is appended to CR_BLOCK_LOG (default: blocked.jsonl next to CR_TOOL_LOG).
The filter is on unless CR_EXCLUDE=0.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from typing import Any

_OWN = r"(?:[a-z0-9-]+\.)*(?:rexstjohn\.com|verafy\.ai|verafyai\.com|verafy\.com)"
_VERCEL = r"(?:[a-z0-9-]+\.)+vercel\.(?:app|sh)"
_GH = r"(?:github\.com|raw\.githubusercontent\.com|gist\.github\.com|gist\.githubusercontent\.com)/(?:rexsaurus|verafyai|rexstjohn)\b"
_X = r"(?:x\.com|twitter\.com|mobile\.twitter\.com|nitter\.[a-z.]+)/(?:rexstjohn|verafyai|verafyfoundtn)\b"
BLOCK_RE = re.compile(rf"(?i)\b(?:{_OWN}|{_VERCEL}|{_GH}|{_X})")
# snapshot hosts are blocked only when the snapshot is of a blocked target (the regex above
# already matches the embedded target URL inside web.archive.org/web/<ts>/<url> and archive.ph/<url>)
SNAPSHOT_RE = re.compile(r"(?i)\b(?:web\.archive\.org/web/\S*|archive\.(?:today|ph|is|li|md|vn)/\S*)")

N = 8
MIN_SHARED = int(os.environ.get("CR_NGRAM_MIN_SHARED", "5"))
MIN_FRAC = float(os.environ.get("CR_NGRAM_MIN_FRAC", "0.2"))
_WORD = re.compile(r"[a-z0-9]+")
_index: set[int] | None = None


def enabled() -> bool:
    return os.environ.get("CR_EXCLUDE", "1") != "0"


def grams(text: str) -> list[int]:
    w = _WORD.findall(text.lower())
    return [int.from_bytes(hashlib.blake2b(" ".join(w[i:i + N]).encode(), digest_size=8).digest(), "big")
            for i in range(len(w) - N + 1)]


def index() -> set[int]:
    global _index
    if _index is None:
        p = os.environ.get("CR_DOSSIER_NGRAMS", "")
        if p and os.path.exists(p):
            with open(p) as fh:
                _index = {int(x, 16) for x in fh.read().split()}
        else:
            if os.environ.get("CR_REQUIRE_NGRAMS") == "1":
                raise RuntimeError("CR_REQUIRE_NGRAMS=1 but CR_DOSSIER_NGRAMS is missing")
            _index = set()
    return _index


def _log(rec: dict) -> None:
    path = os.environ.get("CR_BLOCK_LOG")
    if not path and os.environ.get("CR_TOOL_LOG"):
        path = os.path.join(os.path.dirname(os.environ["CR_TOOL_LOG"]), "blocked.jsonl")
    if not path:
        return
    rec = {"t": time.time(), "pid": os.getpid(), **rec}
    try:
        with open(path, "a") as fh:
            fh.write(json.dumps(rec, default=str)[:20000] + "\n")
    except OSError:
        pass


def check_text(text: str) -> tuple[str, dict] | None:
    """Return (reason, detail) when text must be dropped, else None."""
    m = BLOCK_RE.search(text)
    if m:
        return "blocked_host", {"match": m.group(0)}
    idx = index()
    if idx:
        g = set(grams(text))
        if g:
            shared = len(g & idx)
            if shared >= MIN_SHARED and shared / len(g) >= MIN_FRAC:
                return "dossier_overlap", {"shared_8grams": shared, "item_8grams": len(g), "frac": round(shared / len(g), 3)}
    return None


def _ident(item: Any) -> str:
    if isinstance(item, dict):
        for k in ("url", "identifier", "item_id", "id", "title"):
            if item.get(k):
                return str(item[k])[:300]
    return str(item)[:200]


def check_query(fn: str, args: tuple, kwargs: dict) -> bool:
    """True when the query itself names a blocked host; the call is skipped and returns empty."""
    if not enabled():
        return False
    q = " ".join(str(x) for x in (*args, *kwargs.values()))
    m = BLOCK_RE.search(q)
    if m:
        _log({"fn": fn, "kind": "query", "reason": "blocked_host", "match": m.group(0), "query": q[:300]})
        return True
    return False


def filter_result(fn: str, args: tuple, res: Any) -> Any:
    if not enabled() or res is None:
        return res
    q = " ".join(str(x) for x in args)[:300]
    if isinstance(res, list):
        keep = []
        for it in res:
            hit = check_text(json.dumps(it, default=str))
            if hit:
                _log({"fn": fn, "kind": "item", "reason": hit[0], **hit[1], "query": q, "item": _ident(it)})
            else:
                keep.append(it)
        return keep
    if isinstance(res, dict):  # wikidata_entities: {qid: entity}
        keep = {}
        for k, it in res.items():
            hit = check_text(json.dumps(it, default=str))
            if hit:
                _log({"fn": fn, "kind": "item", "reason": hit[0], **hit[1], "query": q, "item": k})
            else:
                keep[k] = it
        return keep
    return res
