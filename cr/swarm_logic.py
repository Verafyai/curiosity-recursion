"""Pure, deterministic pieces of the swarm: evidence extraction, lead expansion, value, reward,
verification and relatives. No I/O, no clock, no randomness: safe in workflow code and activities.
"""
from __future__ import annotations

import re
from typing import Optional

from cr.generators.rules import _in_life
from cr.leads import YIELD_PRIOR, value_score
from cr.ledger import BOOK_TOOLS, NOVELTY_BY_KEY, PAGE_WINDOW, Decision, Ledger, QuerySpec, RelativeRef, canonical_id, source_of
from cr.models import Person
from cr.names import match
from cr.reflection import Lesson, variant_boost, yield_adjustment
from cr.swarm_models import Ev
from cr.variants import split_name, variants

SNIP = 340
MAX_NEW_LEADS = 5
PARENTS = re.compile(r"\b(?:son|daughter|dau\.?)\s+of\s+([A-Z][a-z]+(?:\s[A-Z]\.)?(?:\s[A-Z][a-z]+)?)\s+and\s+([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)")
BORN = re.compile(r"\bborn\b\D{0,40}?\b(1[6-9]\d\d|20[0-2]\d)\b", re.I)


def short_name(p: Person) -> str:
    g, s = split_name(p.full_name)
    return f"{g[0]} {s}" if g and s else p.full_name


def surname_of(p: Person) -> str:
    return split_name(p.full_name)[1]


def _cut(text: str, around: str) -> str:
    t = re.sub(r"\s+", " ", text or "").strip()
    i = t.lower().find(around.lower()) if around else -1
    if i < 0:
        i = t.find("**")
    if i < 0 or len(t) <= SNIP:
        return t[:SNIP]
    a = max(0, i - SNIP // 2)
    return ("..." if a else "") + t[a: a + SNIP] + ("..." if a + SNIP < len(t) else "")


def matcher(p: Person, spec: QuerySpec) -> Person:
    extra = [spec.name_form] if spec.name_form and spec.name_form != p.full_name and not spec.relative else []
    return Person(full_name=p.full_name, name_variants=list(p.name_variants) + extra, birth_year=p.birth_year, death_year=p.death_year)


def evidence_from_rows(tool: str, spec: QuerySpec, rows, person: Person, cid: str) -> list[Ev]:
    who = matcher(person, spec)
    sur = surname_of(person)
    out: list[Ev] = []
    if tool == "wikidata_entities" and isinstance(rows, dict):
        rows = [dict(v, id=k) for k, v in rows.items()]
    for r in (rows or [])[:12]:
        if not isinstance(r, dict):
            continue
        if tool in ("ia_fts", "ia_fulltext"):
            snips = r.get("snippets") or []
            snip = next((x for x in snips if match(who, x) != "none"), snips[0] if snips else "")
            item = r.get("identifier")
            y = r.get("year")
            y = int(str(y)[:4]) if y and str(y)[:4].isdigit() else None
            page = r.get("page")
            ev = Ev(cid=cid, lane=spec.lane, tool=tool, key=f"ia:{item}" + (f"#{page}" if page else ""), url=f"https://archive.org/details/{item}",
                    item_id=item, title=str(r.get("title") or item), year=y, page=page if isinstance(page, int) else None,
                    snippet=_cut(snip, sur), name_match=match(who, snip or ""), section=spec.section)
        elif tool in BOOK_TOOLS:
            item, page = spec.collection_or_item, r.get("page")
            text = r.get("text") or ""
            ev = Ev(cid=cid, lane=spec.lane, tool=tool, key=f"ia:{item}#{page}", url=f"https://archive.org/details/{item}/page/n{max((page or 1) - 1, 0)}",
                    item_id=item, title=f"{item}, page image {page}", page=page if isinstance(page, int) else None, snippet=_cut(text, sur),
                    name_match=match(who, text), section=spec.section)
        elif tool == "ia_title":
            item = r.get("identifier")
            y = r.get("year")
            ev = Ev(cid=cid, lane=spec.lane, tool=tool, key=f"ia:{item}", url=f"https://archive.org/details/{item}", item_id=item,
                    title=str(r.get("title") or item), year=int(str(y)[:4]) if y and str(y)[:4].isdigit() else None, name_match="none",
                    section=spec.section)
        elif tool == "chronam":
            text = r.get("text") or ""
            d = r.get("date") or ""
            url = re.sub(r"[?#].*$", "", r.get("url") or "") or None
            ev = Ev(cid=cid, lane=spec.lane, tool=tool, key=url or f"chronam:{r.get('title')}:{d}", url=url, title=str(r.get("title") or "newspaper page"),
                    year=int(d[:4]) if d[:4].isdigit() else None, snippet=_cut(text, sur), name_match=match(who, text), section=spec.section)
        elif tool in ("wikidata_search", "wikidata_entities"):
            q = r.get("id")
            if tool == "wikidata_search":
                label = str(r.get("label") or "")
                desc = str(r.get("description") or "")
            else:
                label = str(((r.get("labels") or {}).get("en") or {}).get("value", ""))
                desc = str(((r.get("descriptions") or {}).get("en") or {}).get("value", ""))
            text = f"{label} {desc}".strip()
            ev = Ev(cid=cid, lane=spec.lane, tool=tool, key=f"wd:{q}", url=f"https://www.wikidata.org/wiki/{q}", title=f"Wikidata {q}: {label}",
                    snippet=text[:SNIP], name_match=match(who, label), section=spec.section)
        else:
            continue
        ev.in_life = _in_life(person, ev.snippet, ev.year)
        out.append(ev)
    return out


def verified_ok(person: Person, ev: Ev) -> tuple[bool, str]:
    """The verification gate (CR's rule, kept): a claim needs a quoted snippet that prints the full
    name, inside the life window; a stated birth year that disagrees refutes it (skeptic pass, rules)."""
    if ev.name_match != "strong" or not ev.snippet:
        return False, "no full-name match in a quoted snippet"
    if not ev.in_life:
        return False, "outside the life window (namesake filter)"
    m = BORN.search(ev.snippet)
    if m and person.birth_year and abs(int(m.group(1)) - person.birth_year) > 1:
        return False, f"skeptic: the snippet gives a birth year of {m.group(1)}, the card says {person.birth_year}"
    return True, "verified"


def relatives_from(person: Person, evs: list[Ev]) -> list[RelativeRef]:
    """Parents named as 'son of A and B' in verified snippets. A parent of someone born in year Y was
    born before Y - 12; the gate then decides. Spouses and children carry no birth year here, so the
    gate presumes them living and their names are refused as keys."""
    out: dict[str, RelativeRef] = {}
    sur = surname_of(person)
    for ev in evs:
        text = ev.snippet.replace("**", "")
        for m in PARENTS.finditer(text):
            if match(person, text[max(0, m.start() - 120): m.end()]) != "strong":
                continue
            father = m.group(1) if len(m.group(1).split()) > 1 else f"{m.group(1)} {sur}"
            out.setdefault(father.lower(), RelativeRef(name=father, relation="parent", birth_year=(person.birth_year - 12) if person.birth_year else None,
                                                        birth_year_precision="before", source=ev.key))
        for m in re.finditer(r"\b(?:wife|husband|married)\s+(?:Miss\s+|Mrs\.\s+)?([A-Z][a-z]+\s[A-Z][a-z]+)", text):
            if match(person, text[max(0, m.start() - 120): m.end()]) == "strong":
                out.setdefault(m.group(1).lower(), RelativeRef(name=m.group(1), relation="spouse", source=ev.key))
    return list(out.values())


def gap_state(coverage: dict[str, str], section: str) -> str:
    return coverage.get(section, "missing")


def expected_yield(stats: dict[str, list[float]], tool: str, viewpoint: str, lessons: list[Lesson]) -> float:
    k = f"{tool}|{viewpoint}"
    prior = YIELD_PRIOR.get(viewpoint, 0.25)
    s = stats.get(k, [0.0, 0.0])
    mean = (prior * 2 + s[0]) / (2 + s[1])  # running mean with a prior worth two calls
    return max(0.0, min(1.0, mean + yield_adjustment(lessons, tool, viewpoint)))


def lead_value(spec: QuerySpec, viewpoint: str, stats, coverage, lessons) -> tuple[float, dict]:
    hint = spec.key_hint
    dec = Decision(decision="revisit", canonical_id="", key_type=hint) if hint else None
    v, comp = value_score(spec, dec, expected_yield(stats, spec.tool, viewpoint, lessons), gap_state(coverage, spec.section))
    if hint == "name_variant":
        v = min(1.0, v + 0.3 * variant_boost(lessons))
    if hint == "adjacent_pages" and any(l.type == "productive_source" and l.key == source_of(spec) for l in lessons):
        v = min(1.0, v + 0.05)
    return v, comp


def reward_of(evs: list[Ev], person: Person, known_keys: set[str]) -> tuple[float, list[str]]:
    """1 per call with a new verified item, 0.5 for a new named source (a book or page naming the
    surname), else 0. Returns the reward and the new verified keys."""
    new_v = [e.key for e in evs if e.key not in known_keys and verified_ok(person, e)[0]]
    if new_v:
        return 1.0, new_v
    if any(e.key not in known_keys and (e.name_match == "surname_only" or e.tool == "ia_title") for e in evs):
        return 0.5, []
    return 0.0, []


def expand(spec: QuerySpec, evs: list[Ev], person: Person, relatives: list[RelativeRef], known_ids: set[str]) -> list[QuerySpec]:
    """Follow-up calls a result suggests. Each carries the key it would add (the ledger decides)."""
    out: list[QuerySpec] = []
    short, sur = short_name(person), surname_of(person)
    base = dict(lane=spec.lane, section=spec.section)
    strong = [e for e in evs if e.name_match == "strong" and e.in_life]
    books = []
    for e in strong + [e for e in evs if e.tool == "ia_title"]:
        if e.item_id and e.item_id not in books and not (spec.tool in BOOK_TOOLS and e.item_id == spec.collection_or_item):
            books.append(e.item_id)
    for item in books[:2]:
        e = next(x for x in evs if x.item_id == item)
        out.append(QuerySpec(tool="ia_inside", collection_or_item=item, terms=short, name_form=short, purpose=f"Which pages of {e.title[:60]} name {short}?",
                             grounding=f"{e.key}: {e.snippet[:120] or e.title[:120]}", **base))
    if spec.tool in BOOK_TOOLS or spec.tool in ("ia_fts",):
        for e in strong[:2]:
            if e.item_id and e.page:
                a = e.page + 1
                out.append(QuerySpec(tool="ia_inside_pages", collection_or_item=e.item_id, terms=sur, page_window=(a, a + PAGE_WINDOW - 1), key_hint="adjacent_pages",
                                     purpose=f"What do the pages after page {e.page} of {e.item_id} say about the {sur} family?",
                                     grounding=f"hit on page {e.page}: {e.snippet[:120]}", **base))
                if e.page > PAGE_WINDOW:
                    out.append(QuerySpec(tool="ia_inside_pages", collection_or_item=e.item_id, terms=sur, page_window=(e.page - PAGE_WINDOW, e.page - 1),
                                         key_hint="adjacent_pages", purpose=f"What comes just before page {e.page} of {e.item_id}?",
                                         grounding=f"hit on page {e.page}: {e.snippet[:120]}", **base))
    if spec.tool in BOOK_TOOLS and strong and spec.page_window:
        a, b = spec.page_window
        if b - (min(e.page or a for e in strong)) < PAGE_WINDOW * 3:
            out.append(QuerySpec(tool="ia_inside_pages", collection_or_item=spec.collection_or_item, terms=spec.terms, page_window=(b + 1, b + PAGE_WINDOW),
                                 key_hint="adjacent_pages", purpose=f"Keep reading after page {b}", grounding=f"hits on pages {a}-{b}", **base))
    if spec.tool in ("ia_fts", "ia_fulltext") and strong:
        out.append(spec.model_copy(update={"offset": spec.offset + 10, "key_hint": "result_offset", "purpose": f"Next page of results for {spec.terms}",
                                           "grounding": f"{len(strong)} matching hit(s) at offset {spec.offset}"}))
    if spec.tool == "chronam" and spec.date_window and strong:
        a, b = spec.date_window
        span = max(5, b - a + 1)
        out.append(spec.model_copy(update={"date_window": (b + 1, b + span), "key_hint": "date_window", "purpose": f"Later newspapers, {b + 1} to {b + span}",
                                           "grounding": f"{len(strong)} newspaper hit(s) {a}-{b}"}))
    if spec.tool == "wikidata_search":
        for e in [x for x in evs if x.name_match == "strong"][:2]:
            out.append(QuerySpec(tool="wikidata_entities", collection_or_item=e.key[3:], terms=e.key[3:], purpose=f"Read the dates on {e.title}",
                                 grounding=e.title, **base))
    if not strong and spec.name_form and spec.tool not in ("wikidata_entities", "ia_title"):
        used = {spec.name_form.lower()}
        for v in variants(person.full_name):
            if v.lower() in used:
                continue
            terms = spec.terms.replace(spec.name_form, v) if spec.name_form in spec.terms else v
            out.append(spec.model_copy(update={"terms": terms, "name_form": v, "offset": 0, "key_hint": "name_variant",
                                               "purpose": f"Same search with the spelling {v}", "grounding": f"no full-name hit for {spec.name_form}"}))
            break
    if strong and spec.collection_or_item and spec.tool in BOOK_TOOLS:
        for r in relatives[:2]:
            out.append(QuerySpec(tool="ia_inside", collection_or_item=spec.collection_or_item, terms=r.name, relative=r, key_hint="relative_name",
                                 purpose=f"Does {spec.collection_or_item} name {r.name} ({r.relation})?", grounding=f"verified relative from {r.source}", **base))
    fresh, seen = [], set(known_ids)
    for q in out:
        cid = canonical_id(q)
        if cid not in seen:
            seen.add(cid)
            fresh.append(q)
    return fresh[:MAX_NEW_LEADS]


def replenish(lane, ledger: Ledger, person: Person, relatives: list[RelativeRef], productive: list[QuerySpec], n: int = 6) -> list[QuerySpec]:
    """When a lane's frontier runs dry with budget left: rewrite its seeds and productive calls with
    new keys (ledger.suggest), so the lane repeats itself more cleverly instead of stopping."""
    out, seen = [], set()
    for sp in list(productive) + list(lane.seeds):
        for q, d in ledger.suggest(sp, person, relatives, n=3):
            if d.canonical_id in seen:
                continue
            if lane.date_window and q.date_window and (q.date_window[1] < lane.date_window[0] or q.date_window[0] > lane.date_window[1]):
                continue  # another newspaper lane owns that window
            seen.add(d.canonical_id)
            out.append(q.model_copy(update={"key_hint": d.key_type if d.decision == "revisit" else None,
                                            "purpose": q.purpose or sp.purpose, "grounding": f"rewrite of {canonical_id(sp)}: {d.reason}"}))
            if len(out) >= n:
                return out
    return out
