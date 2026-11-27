"""Freeze raw atomized dossier facts into the versioned answer key.

Reads eval/private/raw/<pid>.jsonl (gitignored: the atomizer output, carries the full dossier
reference text) and writes
  eval/answer_keys/<ver>/<pid>.jsonl          public facts (every person named passes the gate)
  eval/private/answer_keys/<ver>/<pid>.jsonl  facts naming anyone who fails the gate (local only)
  eval/answer_keys/<ver>/LOCK.json            sha256 of every file, fact counts, rules version
Living-person gate: a person passes when a death is on record or a birth 110+ years before the
freeze date is on record, in the dossier registry or in the key's own birth/death facts. An
unknown birth counts as living. Ships and organisations are not people.
"""
import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VER = sys.argv[1] if len(sys.argv) > 1 else "v1"
CUTOFF = date.today().year - 110
SUBJECTS = {  # pid: (subject, era, gate evidence)
    "burnham": ("Erasthus William Burnham Jr", "civil_war", "1834-1921"),
    "homer": ("Homer Doble St. John", "wwi", "1900-1972"),
    "john": ("John St. John", "wwii", "1921-2006 (death on record)"),
    "kingsley": ("Kingsley Arnold Perry", "civilian", "1907-1962"),
    "bristol": ("Edgar Hiel Bristol", "civilian", "1871-1944"),
    "alex": ("Alex St. John", "civilian", "born 1967; deceased per Rex St. John (family attestation, 2026-11-26); the dossier has no death record"),
}
# Gate passes on family attestation alone (no death record in the dossier).
ATTESTED = {"Alex St. John": "deceased per Rex St. John (family attestation, 2026-11-26)"}
NON_PERSON = {"Hannibal", "Foxboro Company", "Industrial Instrument Company", "New Civilization", "WildTangent", "Microsoft", "Magi.com", "Nyriad", "PlayCast Inc."}
ORG_RE = re.compile(r"\b(Inc|Corp|Corporation|Company|Co\.|LLC|Ltd|Microsoft|WildTangent|University|College|School|Society|Association|Magazine|Games?)\b")
# Alias -> registry name, for forms the atomizer used that differ from the registry entry.
ALIAS = {
    "Erastus William Burnham Jr": "Erasthus William Burnham Jr", "Erastus Williams Burnham": "Erasthus William Burnham Jr",
    "Mary Graham Devine": "Mary Graham Devine Burnham", "Mary Devine Burnham": "Mary Graham Devine Burnham",
    "Mary Devine": "Mary Graham Devine Burnham", "Mary": "Mary Graham Devine Burnham", "Agnes Burnham": "Agnes Maria Burnham",
    "Homer Doble St. John": "Homer St. John", "John Homer St. John": "John St. John", "Alice Rose St. John": "Alice Rose Pigeon",
    "Kingsley Arnold Perry": "Kingsley Perry", "Alexander Kingsley St. John": "Alex St. John", "Alexander St. John": "Alex St. John", "Justine R. B. Perry": "Justine Rexford Bristol",
}
# Births stated in the key itself (fact values), used only when the registry has none.
KEY_BIRTHS = {"William Burnham": 1856, "Owen W. Burnham": 1857, "Frederick A. Burnham": 1866}
# Living people's names never live in public code: they are read from eval/private/redact.json (gitignored).
_RED = json.loads((ROOT / "eval/private/redact.json").read_text())
ALWAYS_PRIVATE = re.compile(r"\b(" + "|".join(map(re.escape, _RED["always_private_given_names"])) + r")\b")
REDACT_GIVEN = re.compile(r"\b(" + "|".join(map(re.escape, _RED["redact_in_citations_given_names"])) + r")( [A-Z][a-z]+\.?)*( [A-Z][a-z]+)?")


def tier(ref: str) -> str:
    r = ref.lower()
    if re.search(r"interview recording|family archive|family account|information to the editors|the book of daniel|rexstjohn\.com", r):
        return "outreach"
    if re.search(r"supplied by|reply to|copies supplied|clipping supplied|research notes|research leads|letter from|ticket #", r):
        return "outreach"
    if re.search(r"ancestry\.com|ancestry library|newspaperarchive|proquest|familysearch|fold3|newspapers\.com|genealogybank|myheritage", r):
        return "web_gated"
    if re.search(r"archive\.org/details|hathitrust|books\.google|gutenberg\.org", r) or (
            not re.search(r"https?://", r) and re.search(r"\([^)]*\b1[6-9]\d\d\)|\bed\.|pp\. \d", r)):
        return "book"
    if re.search(r"https?://", r):
        return "web_open"
    return "outreach"


def book_ids(ref: str) -> dict:
    out = {}
    for k, pat in (("ia", r"archive\.org/details/([A-Za-z0-9._-]+)"), ("hathitrust", r"hathitrust\.org/\S*?(?:id=|/)([a-z0-9]+\.[\w$.]+)"),
                   ("google_books", r"books\.google\.[a-z.]+/\S*?id=([\w-]+)"), ("gutenberg", r"gutenberg\.org/\S*?(\d{3,})")):
        m = re.search(pat, ref)
        if m:
            out[k] = m.group(1).rstrip(".")
    return out


def name_forms(n: str) -> list[str]:
    f = {n, re.sub(r"\bSt\.? ", "Saint ", n), re.sub(r"\bSt\. ", "St ", n), n.replace("Erasthus", "Erastus"), n.replace("Erastus", "Erasthus")}
    parts = n.replace(".", "").split()
    if len(parts) >= 3:
        f.add(f"{parts[0]} {parts[-1]}")
    return sorted(f)


def date_tokens(d: str) -> list[str]:
    return sorted(set(re.findall(r"\b1[6-9]\d\d|20[0-2]\d\b", d or "")))


reg = json.loads((Path("/workspace/cr-notes/corpus/registry.json") if len(sys.argv) < 3 else Path(sys.argv[2])).read_text())
REG = {v["name"]: v for v in reg.values()}


def gate(person: str) -> tuple[bool, str]:
    if person in NON_PERSON or ORG_RE.search(person):
        return True, "not a person"
    n = ALIAS.get(person, person)
    if n in ATTESTED:
        return True, ATTESTED[n]
    v = REG.get(n)
    if v and v.get("died"):
        return True, f"death on record ({v['died']})"
    b = int(v["born"]) if v and v.get("born") else KEY_BIRTHS.get(person)
    if b and b <= CUTOFF:
        return True, f"born {b}"
    return False, "no death on record and no birth before %d" % CUTOFF


pub_dir, priv_dir = ROOT / "eval/answer_keys" / VER, ROOT / "eval/private/answer_keys" / VER
pub_dir.mkdir(parents=True, exist_ok=True)
priv_dir.mkdir(parents=True, exist_ok=True)
fail_names = {n for n, v in REG.items() if not gate(n)[0]}
fail_names |= set(_RED["never_publish_full_names"])  # never published regardless of the gate
lock, gate_report = {"version": VER, "frozen": date.today().isoformat(), "rules": "freeze.py gate+tier v1", "people": {}}, {}
for pid, (subject, era, ev) in SUBJECTS.items():
    raw = [json.loads(x) for x in (ROOT / f"eval/private/raw/{pid}.jsonl").read_text().splitlines() if x.strip()]
    pub, priv = [], []
    for r in raw:
        ok, why = gate(r["person"])
        named_fail = [n for n in fail_names if n in r["value"]] + (["redacted"] if ALWAYS_PRIVATE.search(r["value"]) else [])
        if re.search(r"\bJanet\b|\bRegina\b|\bPhillip\b", r["value"]):
            named_fail.append("relative without death on record")
        gate_report.setdefault(pid, {}).setdefault(r["person"], why if ok else f"PRIVATE: {why}")
        srcs = []
        for s in r.get("sources", []):
            t = s.get("text", "")
            url = s.get("url") or (re.search(r"https?://\S+", t).group(0).rstrip(".,)") if re.search(r"https?://\S+", t) else None)
            sid = hashlib.sha256((url or re.sub(r"\W+", " ", t.lower())[:200]).encode()).hexdigest()[:12]
            cit = re.sub(r"\s+", " ", t)[:400]
            for nm in sorted(fail_names, key=len, reverse=True):
                cit = cit.replace(nm, "[relative]")
            cit = REDACT_GIVEN.sub("[relative]", cit)
            srcs.append({"source_id": sid, "citation": cit, "url": url, "access_tier": tier(t), "book_ids": book_ids(t)})
        fid = r["fact_id"]
        row = {"fact_id": fid, "subject": subject, "era": era, "person": r["person"], "relation": r["relation"], "type": r["type"],
               "value": r["value"], "date": r.get("date", ""), "date_tokens": date_tokens(r.get("date", "") + " " + r["value"]),
               "place": r.get("place", ""), "keywords": r.get("keywords", []), "name_forms": name_forms(ALIAS.get(r["person"], r["person"])),
               "certainty": r.get("certainty", ""), "sources": srcs,
               "holdout": int(hashlib.sha256(f"cr-holdout-v1:{fid}".encode()).hexdigest(), 16) % 10 < 3}
        (pub if ok and not named_fail else priv).append(row)
    for d, rows in ((pub_dir, pub), (priv_dir, priv)):
        (d / f"{pid}.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows))
    tiers = {}
    for x in pub + priv:
        t = sorted({s["access_tier"] for s in x["sources"]}) or ["none"]
        best = next((k for k in ("web_open", "book", "web_gated", "outreach") if k in t), "none")
        tiers[best] = tiers.get(best, 0) + 1
    subj_names = {subject, ALIAS.get(subject, subject)} | {k for k, v in ALIAS.items() if v in (subject, ALIAS.get(subject, subject))}
    deaths = [x for x in pub + priv if x["type"] == "death" and x["person"] in subj_names]
    lock["people"][pid] = {"subject": subject, "era": era, "gate": ev,
                           "gate_basis": (f"death fact {deaths[0]['fact_id']}: {deaths[0]['value']} ({deaths[0]['date']}); source: "
                                          + (deaths[0]["sources"][0]["citation"][:160] if deaths[0]["sources"] else "unsourced"))
                           if deaths else ATTESTED.get(subject, "birth more than 110 years ago"),
                           "death_fact_ids": [x["fact_id"] for x in deaths], "facts_total": len(pub) + len(priv), "facts_public": len(pub),
                           "facts_private": len(priv), "holdout": sum(x["holdout"] for x in pub + priv), "best_tier_counts": tiers,
                           "sha256_public": hashlib.sha256((pub_dir / f"{pid}.jsonl").read_bytes()).hexdigest(),
                           "sha256_private": hashlib.sha256((priv_dir / f"{pid}.jsonl").read_bytes()).hexdigest()}
(pub_dir / "LOCK.json").write_text(json.dumps(lock, indent=2) + "\n")
(priv_dir / "gate-report.json").write_text(json.dumps(gate_report, indent=2) + "\n")
print(json.dumps(lock["people"], indent=1))
