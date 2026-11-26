"""Eval fixtures that back the STUB checklist steps in demo mode.

- fixtures/burnham-erastus.json: a curated golden file for Erastus W. Burnham (1834 to 1921),
  copied read-only from kin (evals/golden). Every claim has an open source URL.
- fixtures/relatives.public.json (optional, not shipped): public-only records for STUB link steps.

A run with `use_fixtures = False` (every benchmark run) never reads these, because they hold
ground truth. Fixture claims are labeled STUB everywhere they appear.

Golden files are claims Rex curated with an open source URL for each. Stub steps
read them; nothing here is fetched or invented. A person with no fixture gets
'nothing' from every stub step.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures"
GOLDEN = ["burnham-erastus.json"]


def norm(s: str) -> str:
    return re.sub(r"[^a-z ]", "", s.lower().replace(".", " ")).strip()


def norm_words(s: str) -> str:
    return " ".join(norm(s).split())


@lru_cache(maxsize=1)
def golden() -> list[dict]:
    out = []
    for name in GOLDEN:
        if not (FIXTURE_DIR / name).exists():
            continue
        data = json.loads((FIXTURE_DIR / name).read_text())
        data["_file"] = name
        out.append(data)
    return out


@lru_cache(maxsize=1)
def relatives() -> list[dict]:
    f = FIXTURE_DIR / "relatives.public.json"
    return json.loads(f.read_text())["relatives"] if f.exists() else []


def _name_match(names: list[str], candidates: list[str]) -> bool:
    a = {norm_words(n) for n in names}
    b = {norm_words(n) for n in candidates}
    return bool(a & b)


def golden_claims_for(names: list[str], fields: list[str]) -> list[tuple[str, dict]]:
    """Claims about the subject (person id match), plus claims on another person that name the subject."""
    hits: list[tuple[str, dict]] = []
    wanted = set(fields)
    for g in golden():
        ids = {p["id"] for p in g["people"] if _name_match(names, p["names"])}
        if not ids:
            continue
        variants = [norm_words(n) for n in names]
        for e in g["expected"]:
            if e.get("type") not in wanted:
                continue
            if e["person"] in ids:
                hits.append((g["_file"], e))
            elif any(v and v in norm_words(e.get("value", "")) for v in variants):
                hits.append((g["_file"], e))
    return hits


def golden_also_at(names: list[str], pattern: str) -> list[tuple[str, dict]]:
    out = []
    for g in golden():
        ids = {p["id"] for p in g["people"] if _name_match(names, p["names"])}
        for e in g["expected"]:
            if e["person"] in ids:
                for a in e.get("alsoAt", []) or []:
                    if re.search(pattern, a.get("title", ""), re.I):
                        out.append((g["_file"], a))
    return out


def relatives_sources(names: list[str], title_pattern: str, must_name: bool = False) -> list[dict]:
    out, seen = [], set()
    variants = [norm_words(n) for n in names]
    for d in relatives():
        dossier_match = _name_match(names, [d["input"].get("fullName", "")])
        for s in d.get("expected", []):
            t = s.get("title", "")
            if not re.search(title_pattern, t, re.I):
                continue
            named = any(v and v in norm_words(t) for v in variants)
            if (must_name and not named) or (not must_name and not (dossier_match or named)):
                continue
            if s["id"] + d["dossier"] in seen:
                continue
            seen.add(s["id"] + d["dossier"])
            out.append({**s, "_dossier": d["dossier"]})
    return out
