"""Corpus-replication scorer (EVAL-SPEC.md section 4).

A run is the result line from bench/harness.py plus the tool log written through CR_TOOL_LOG
(every item each tool returned, after the exclusion filter). Facts come from the frozen answer key.

Credit per fact
  1.0  some returned evidence item names the person (name forms normalised: St./Saint/St,
       Erasthus/Erastus, initials) AND carries the fact's year (when the fact has one) AND at least
       min(2, n) of the fact's content words (value, place, keywords minus names and stop words);
       or the item IS one of the fact's key sources (same URL, IA identifier, loc.gov page or QID)
       and names the person.
  0.5  not matched, but the fact's access tier is book or outreach and the run names the right
       book (IA/HathiTrust/Google Books identifier among cited items) or the right archive
       (institution words in an outreach draft or the final answer).
  0    otherwise.
Also reported: source recall (machine-identifiable key sources reached), precision of reported
items (on-target = names the subject and every year in it falls inside the subject's life window),
novel candidates (on-target reported items matching no key source and no fact), and false family
links (relation claims naming a person outside the key's family). Penalised score =
recall - 5 * false_links / n_facts.
"""
from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path

STOP = set("""a an the of in on at to for from by with and or as is was were be been his her he she him their they it its this that
born died death birth married marriage son daughter wife husband father mother brother sister child children named name known
lived living resided residence record records recorded listed list appears appear entry also later early about around circa
after before during year years age aged st saint jr sr mr mrs miss family who which where when then there into served
full first middle last given called also known spelled south north east west new county city town township state village""".split())
LAMBDA = 5.0


def norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", str(t)).encode("ascii", "ignore").decode().lower()
    t = re.sub(r"\*\*", "", t)
    t = re.sub(r"\bsaint\b", "st", t)
    t = re.sub(r"\berasthus\b", "erastus", t)
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return f" {t.strip()} "


def name_pattern(name: str) -> re.Pattern | None:
    """Given name (or its initial), then at most one middle element that must agree with the known
    middle name (the full middle name or its initial; any initial when no middle name is known),
    then the surname. "Erastus Devine Burnham" does not match "Erastus William Burnham"."""
    w = norm(name).split()
    w = [x for x in w if x not in ("jr", "sr", "ii", "iii", "mrs", "mr")]
    if len(w) < 2:
        return re.compile(rf" {re.escape(w[0])} ") if w else None
    if len(w) >= 3 and w[-2] == "st":
        sur, given = "st " + w[-1], w[:-2]
    else:
        sur, given = w[-1], w[:-1]
    g = given[0]
    if len(given) > 1:
        m = given[1]
        mid = rf"(?: {m}| {m[0]})?"
    else:
        mid = r"(?: [a-z])?"
    return re.compile(rf" (?:{g}|{g[0]}){mid} {sur} | {sur} (?:{g}|{g[0]}){mid} ")


def content_words(f: dict, person: str, family_words: set[str] = frozenset()) -> list[str]:
    """Words that carry the fact: value and keywords minus names and stop words, plus at most one
    place word (a town name alone is too common to prove a fact)."""
    names = set(norm(person).split()) | set(norm(f.get("subject", "")).split()) | set(family_words)
    out = []
    for x in norm(" ".join([f.get("value", ""), " ".join(f.get("keywords", []))])).split():
        if x in STOP or x in names or len(x) < 3 or re.fullmatch(r"\d+", x):
            continue
        if x not in out:
            out.append(x)
    place = [x for x in norm(f.get("place", "")).split() if x not in STOP and x not in names and len(x) > 2 and x not in out]
    return out + place[:1]


def years(t: str) -> list[int]:
    return [int(y) for y in re.findall(r"\b(1[6-9]\d\d|20[0-2]\d)\b", t)]


def src_keys(url: str | None, text: str = "") -> set[str]:
    k = set()
    for s in filter(None, [url, text]):
        for m in re.finditer(r"archive\.org/(?:details|stream)/([A-Za-z0-9._-]+)", s):
            k.add("ia:" + m.group(1).rstrip("."))
        for m in re.finditer(r"loc\.gov/(?:resource|item)/(sn\d+)/(\d{4}-\d\d-\d\d)", s):
            k.add(f"loc:{m.group(1)}:{m.group(2)}")
        for m in re.finditer(r"wikidata\.org/wiki/(Q\d+)", s):
            k.add("wd:" + m.group(1))
        for m in re.finditer(r"hathitrust\.org/\S*?(?:id=|/)([a-z0-9]+\.[\w$.]+)", s):
            k.add("ht:" + m.group(1))
    if url and not k:
        k.add("url:" + re.sub(r"^https?://(www\.)?", "", url).rstrip("/").lower())
    return k


def _salvage(line: str) -> dict | None:
    """Recover the complete leading items of a tool-log line that an old logger cut at 200,000
    characters (tool logs written before 26 Nov 2026 14:50 PT)."""
    m = re.match(r'\{"t": [\d.]+, "pid": \d+, "fn": "(\w+)", "args": (\[.*?\]), "kwargs": .*?"result": \[', line)
    if not m:
        return None
    dec, pos, items = json.JSONDecoder(), m.end(), []
    while pos < len(line):
        while pos < len(line) and line[pos] in ", ":
            pos += 1
        try:
            obj, pos = dec.raw_decode(line, pos)
        except json.JSONDecodeError:
            break
        items.append(obj)
    try:
        args = json.loads(m.group(2))
    except json.JSONDecodeError:
        args = []
    return {"fn": m.group(1), "args": args, "result": items, "salvaged": True}


def evidence(tool_log: Path) -> list[dict]:
    items = []
    if not tool_log.exists():
        return items
    for line in tool_log.read_text().splitlines():
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            d = _salvage(line)
            if d is None:
                continue
        res, fn, args = d.get("result"), d.get("fn"), d.get("args") or []
        rows = res if isinstance(res, list) else [dict(v, id=k) for k, v in res.items()] if isinstance(res, dict) else []
        for r in rows:
            if not isinstance(r, dict):
                continue
            if fn == "ia_inside":
                key = {"ia:" + str(args[0])} if args else set()
                url = f"https://archive.org/details/{args[0]}" if args else None
            elif r.get("identifier"):
                url = f"https://archive.org/details/{r['identifier']}"
                key = {"ia:" + r["identifier"]}
            elif fn in ("wikidata_entities", "wikidata_search"):
                q = r.get("id")
                url, key = (f"https://www.wikidata.org/wiki/{q}", {"wd:" + q}) if q else (None, set())
            else:
                url = r.get("url")
                key = src_keys(url)
            # the url field drops its query string: loc.gov echoes the agent's own search terms there (scorer v1.1)
            text = json.dumps({k: (re.sub(r"[?#].*$", "", v) if k == "url" and isinstance(v, str) else v) for k, v in r.items() if k not in ("claims",)}, ensure_ascii=False) if fn != "wikidata_entities" else json.dumps(r.get("labels", {}).get("en", {}), ensure_ascii=False) + " " + json.dumps(r.get("descriptions", {}).get("en", {}), ensure_ascii=False)
            py = r.get("year") if isinstance(r.get("year"), int) else None
            if py is None and isinstance(r.get("date"), str) and re.match(r"\d{4}", r["date"]):
                py = int(r["date"][:4])
            items.append({"fn": fn, "url": url, "keys": key, "norm": norm(text), "raw": text[:600], "pubyear": py})
    return items


def reported(run: dict) -> tuple[set[str], str]:
    keys, extra = set(), ""
    fa = run.get("final_answer") or ""
    for c in run.get("citations", []):
        keys |= src_keys(c.get("url"), c.get("url") or "") | ({"ia:" + c["item_id"]} if c.get("item_id") else set())
    if run.get("agent") in ("B0", "B1") and re.search(r"https?://", fa):
        keys = set()
        for u in re.findall(r"https?://\S+", fa):
            keys |= src_keys(u.rstrip(").,"))
    extra = fa + " " + " ".join(f"{x.get('to', '')} {x.get('subject', '')}" for x in run.get("drafts", []))
    return keys, extra


def institution_words(citation: str, family_words: set[str]) -> list[list[str]]:
    """Archive or holder names an agent could contact: "supplied by El Dorado County Library",
    "via NewspaperArchive", "Wood Memorial Library ...". Quoted titles and family names are removed;
    a family interview is not an institution and earns no outreach credit."""
    if re.search(r"interview|recording|family (archive|account|papers)", citation.lower()):
        return []
    c = re.sub(r"\"[^\"]*\"|\u201c[^\u201d]*\u201d", " ", citation)
    cands = re.findall(r"(?:supplied by|via|courtesy of|held by|collection of|archives? of)\s+([^,;().]+)", c, re.I)
    head = re.split(r",|\(|;", c.strip())[0]
    if head.strip():
        cands.append(head)
    out = []
    for x in cands:
        w = [t for t in norm(x).split() if t not in STOP and t not in family_words and len(t) > 3 and not t.isdigit()]
        if len(w) >= 2:
            out.append(w[:3])
    return out


REACH_HOSTS = ("archive.org", "loc.gov", "wikidata.org")


def reachable(f: dict) -> bool:
    """Ceiling definition (fixed before the matrix was scored, see answer-key-review.md): a fact is
    reachable when at least one of its sources is on a host the bench tools can query."""
    return any(any(h in (s.get("url") or "") for h in REACH_HOSTS) for s in f.get("sources", []))


def score_run(run: dict, items: list[dict], key: list[dict], life: tuple[int, int], family: set[str]) -> dict:
    rep_keys, rep_extra = reported(run)
    rep_extra_n = norm(rep_extra)
    subj = key[0]["subject"] if key else ""
    sp = name_pattern(subj)
    per_fact, credit = [], 0.0
    fam_words = set(" ".join(norm(x) for x in family | {subj}).split())
    key_src = {}
    for f in key:
        for s in f["sources"]:
            ks = src_keys(s.get("url"), s.get("citation", ""))
            if any(k.split(":")[0] in ("ia", "loc", "wd", "ht") or k.startswith("url:") for k in ks):
                key_src[s["source_id"]] = ks
    reached_src = {sid for sid, ks in key_src.items() if any(ks & it["keys"] for it in items)}
    matched_items = set()
    given_words = {norm(x).split()[0] for x in family | {subj} if norm(x).split()}
    fam_pats = {x: name_pattern(x) for x in family if len(norm(x).split()) >= 2}
    for f in key:
        pat = name_pattern(f["person"]) or sp
        cw = content_words(f, f["person"], fam_words)
        others = [q for x, q in fam_pats.items() if q and x != f["person"] and norm(x) in norm(f["value"])]
        full_name_fact = f.get("type") == "name"
        # name facts: the exact name form the fact states (no Erasthus/Erastus folding), plus any other word it carries
        lit = lambda x: " " + re.sub(r"[^a-z0-9]+", " ", unicodedata.normalize("NFKD", x).encode("ascii", "ignore").decode().lower().replace("saint", "st")).strip() + " "  # noqa: E731
        caps = re.findall(r"(?:[A-Z][a-z]+\.? ){1,3}(?:St\. )?[A-Z][a-z]+", f["value"])
        name_lit = lit(max(caps, key=len)) if caps else lit(f["person"])
        name_extra = [w for w in cw if w not in name_lit.split()]
        need = min(2, len(cw))
        ys = [str(y) for y in years(f.get("date", ""))] or [t for t in f.get("date_tokens", []) if t in f.get("value", "")]
        fkeys = set().union(*[src_keys(s.get("url"), s.get("citation", "")) for s in f["sources"]]) if f["sources"] else set()
        how, score, item, ev_win = None, 0.0, None, None
        need = min(4, max(need, (len(cw) + 1) // 2))
        for i, it in enumerate(items):
            t = it["norm"]
            if it.get("pubyear") and it["pubyear"] < life[0]:
                continue  # published before the subject was born: a namesake (scorer v1.1, after the audit)
            spans = []
            for m in (pat.finditer(t) if pat else []):
                prev = t[: m.start()].split()[-1:] or [""]
                if prev[0] in given_words and m.group(0).split()[0] not in (prev[0],):
                    continue  # "erastus william burnham" is not a mention of "william burnham"
                by = re.search(r"\bborn\b\D{0,40}?\b(1[6-9]\d\d|20[0-2]\d)\b", t[m.end(): m.end() + 160])
                if by and f["person"] == subj and abs(int(by.group(1)) - life[0]) > 1:
                    continue  # the passage gives this namesake a different birth year (scorer v1.1)
                spans.append(m.start())
            if not spans:
                continue
            if full_name_fact:
                raw = lit(it["raw"])
                if name_lit.strip() in raw and all(f" {w} " in raw for w in name_extra) and \
                        all(life[0] - 1 <= y <= life[1] + 40 for y in years(t) if y < 1990):
                    how, score, item, ev_win = "content", 1.0, i, t[max(0, spans[0] - 400): spans[0] + 400]
                    break
                continue
            # the fact must sit near a mention of the person: a window of about 60 words around it
            wins = [t[max(0, a - 400): a + 400] for a in spans]
            near = [t[max(0, a - 200): a + 200] for a in spans]  # a fact's year must sit within about 30 words of the name (scorer v1.1)
            if ys and not any(any(f" {y} " in w for y in ys) for w in near):
                wins = []
            if ys and not cw:  # a bare date fact ("Born in 1907") needs a vital word next to the name and the year
                wins = [w for w in near if any(f" {y} " in w for y in ys) and re.search(r" (born|birth|died|death|nee) ", w)]
            hitw = next((w for w in wins if (not ys or any(f" {y} " in w for y in ys)) and (need > 0 or ys) and
                         all(q.search(w) for q in others) and
                         sum(1 for x in cw if f" {x} " in w) >= need), None)
            if hitw is None and f.get("type") == "relation" and others and not cw:
                # a family link counts only with the relative's full name, the subject and a relation word in one window
                full = " " + norm(f["person"]) + " "
                hitw = next((w for w in wins if full in " " + w + " " and all(q.search(w) for q in others) and
                             re.search(r" (son|daughter|wife|husband|father|mother|brother|sister|child|married|widow) ", w)), None)
            if hitw is not None:
                how, score, item, ev_win = ("key_source+content" if fkeys & it["keys"] else "content"), 1.0, i, hitw
                break
            if fkeys & it["keys"] and score < 0.5:
                how, score, item = "key_source", 0.5, i  # reached the right record; the fact itself was not in the returned text
        if score == 0:
            tiers = {s["access_tier"] for s in f["sources"]}
            if "book" in tiers and score == 0:
                ids = {f"ia:{s['book_ids']['ia']}" for s in f["sources"] if s.get("book_ids", {}).get("ia")}
                if ids & rep_keys:
                    how, score = "named_book", 0.5
            if score == 0 and "outreach" in tiers:
                for s in f["sources"]:
                    if any(all(f" {w} " in rep_extra_n for w in iw) for iw in institution_words(s.get("citation", ""), fam_words)):
                        how, score = "named_archive", 0.5
                        break
        if item is not None:
            matched_items.add(item)
        credit += score
        per_fact.append({"fact_id": f["fact_id"], "score": score, "how": how, "holdout": f["holdout"], "reachable": reachable(f),
                         "tier": next((k for k in ("web_open", "book", "web_gated", "outreach") if k in {s["access_tier"] for s in f["sources"]}), "none"),
                         "evidence": items[item]["url"] if item is not None else None,
                         "evidence_snip": items[item]["raw"][:300] if item is not None else None,
                         "evidence_window": ev_win})
    # precision and novel candidates over reported items
    rep_items = [it for it in items if it["keys"] & rep_keys]
    seen, on, novel = set(), 0, []
    for i, it in enumerate(items):
        k = frozenset(it["keys"])
        if not (it["keys"] & rep_keys) or k in seen:
            continue
        seen.add(k)
        ok = bool(sp and sp.search(it["norm"])) and all(life[0] - 1 <= y <= life[1] + 40 for y in years(it["norm"]) if y < 1990)
        on += ok
        if ok and not any(it["keys"] & ks for ks in key_src.values()) and i not in matched_items:
            novel.append({"url": it["url"], "snip": it["raw"][:300]})
    n_rep = len(seen)
    # false family links: relation claims naming someone outside the key family
    fl = []
    for ld in run.get("leads", []):
        if ld.get("field") in ("parents", "spouse", "children", "sibling", "relation"):
            nm = str(ld.get("value", ""))
            if nm and not any(norm(x).strip() and norm(x) in norm(nm) for x in family):
                fl.append(nm[:120])
    for m in re.finditer(r"\b(?:son|daughter|wife|husband|father|mother|brother|sister|married)(?: of| to)? ([A-Z][a-z]+(?: [A-Z]\.?)? [A-Z][a-z]+)", run.get("final_answer") or ""):
        if not any(norm(m.group(1)).strip() in norm(x) or norm(x).strip() in norm(m.group(1)) for x in family):
            fl.append(m.group(1))
    n = len(key)
    by_tier, hold = {}, {"holdout": [0.0, 0], "scored": [0.0, 0]}
    for p in per_fact:
        b = by_tier.setdefault(p["tier"], [0.0, 0])
        b[0] += p["score"]; b[1] += 1
        h = hold["holdout" if p["holdout"] else "scored"]
        h[0] += p["score"]; h[1] += 1
    recall = credit / n if n else 0.0
    rch = [p["score"] for p in per_fact if p["reachable"]]
    return {"reachable_n": len(rch), "reachable_recall": sum(rch) / len(rch) if rch else None,"n_facts": n, "credit": credit, "recall": recall,
            "recall_full_credit_only": sum(1 for p in per_fact if p["score"] == 1.0) / n if n else 0.0,
            "by_tier": {k: {"n": v[1], "recall": v[0] / v[1]} for k, v in by_tier.items()},
            "holdout_recall": hold["holdout"][0] / hold["holdout"][1] if hold["holdout"][1] else None,
            "non_holdout_recall": hold["scored"][0] / hold["scored"][1] if hold["scored"][1] else None,
            "source_recall": len(reached_src) / len(key_src) if key_src else None, "n_key_sources_identifiable": len(key_src),
            "n_reported": n_rep, "precision": on / n_rep if n_rep else None, "novel_candidates": len(novel),
            "false_links": len(fl), "false_link_names": fl, "penalised": recall - LAMBDA * len(fl) / n if n else 0.0,
            "_per_fact": per_fact, "_novel": novel}


def load_key(d: Path, pid: str, private: Path | None) -> list[dict]:
    rows = [json.loads(x) for x in (d / f"{pid}.jsonl").read_text().splitlines() if x.strip()]
    if private and (private / f"{pid}.jsonl").exists():
        rows += [json.loads(x) for x in (private / f"{pid}.jsonl").read_text().splitlines() if x.strip()]
    return rows


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("run_jsonl", type=Path)
    ap.add_argument("tool_log", type=Path)
    ap.add_argument("--pid", required=True)
    ap.add_argument("--key", type=Path, default=Path(__file__).resolve().parents[1] / "answer_keys/v1")
    ap.add_argument("--private", type=Path, default=Path(__file__).resolve().parents[1] / "private/answer_keys/v1")
    a = ap.parse_args()
    key = load_key(a.key, a.pid, a.private)
    LIFE = {"burnham": (1834, 1921), "homer": (1900, 1972), "john": (1921, 2006), "kingsley": (1907, 1962), "bristol": (1871, 1944), "alex": (1967, 2026)}
    fam = {f["person"] for f in key}
    run = json.loads(a.run_jsonl.read_text().splitlines()[-1])
    s = score_run(run, evidence(a.tool_log), key, LIFE[a.pid], fam)
    print(json.dumps({k: v for k, v in s.items() if not k.startswith("_")}, indent=1))
