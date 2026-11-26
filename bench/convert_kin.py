"""Build DarkKin-Bench v0 subject cards from kin's eval files.

    python bench/convert_kin.py --relatives PATH/relatives.json --heritage PATH/heritage-real.json --out bench/data

Rules this script enforces (paper spec sections 0 and 8):
- It refuses any input whose file name contains "holdout". kin's heritage-real.holdout.json is
  scored once, at the end, and is never read while building or tuning anything.
- Living-person filter: a subject is kept only if cr.gate says research may run (death on
  record, or birth at least 110 years ago). Every decision is logged.
- Private family items (no public URL, an "unknown" or "offline" host, or an interview) are
  released as counts and tiers only. For kin's family dossiers (relatives.json) titles are never
  released and URLs only for public archival hosts, because a title can name a living relative.
- Darkness tiers come from a host rule (TIER_RULES below) and are marked `tier_basis: heuristic`
  and `confirmed: false` until a person checks each one.
- Hidden-record protocol: the input card holds only seed facts (names, years, places). Every
  record is hidden and scored. Nothing from a record is put in the card.
- Split: a subject-level 30% test split by a fixed hash of the subject id, never looked at
  during development.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cr.gate import gate  # noqa: E402
from cr.models import Person  # noqa: E402

VERSION = "darkkin-bench-v0"
T0 = {"wikidata.org", "www.wikidata.org", "openalex.org", "osti.gov", "id.lib.harvard.edu", "catalog.archives.gov",
      "aad.archives.gov", "catalog.hathitrust.org", "gravelocator.cem.va.gov", "guides.loc.gov", "doi.org", "britannica.com"}
T2 = {"findagrave.com", "www.findagrave.com", "familysearch.org", "www.familysearch.org", "ancestry.com", "www.ancestry.com",
      "newspaperarchive.com", "fold3.com", "newspapers.com", "townofstmarys.sharefile.com"}
PUBLIC_ARCHIVAL = {"archive.org", "loc.gov", "www.loc.gov", "babel.hathitrust.org", "catalog.hathitrust.org", "gutenberg.org",
                   "en.wikipedia.org", "fr.wikipedia.org", "wikidata.org", "www.wikidata.org", "nps.gov", "www.nps.gov",
                   "archives.gov", "catalog.archives.gov", "aad.archives.gov", "whalinghistory.org", "web.archive.org"}
TIER_RULES = ("T0: structured catalogue, API or encyclopedia host; T2: login, paywall or terms-restricted host; "
              "T3: no public URL (local, offline, unknown); T1: any other public page (full text or images only).")
CIRCUIT_BY_GROUP = {"immigrant": "the_crossing", "military": "civil_war_veteran"}


def tier(host: str, url: str) -> str:
    h = (host or "").lower()
    if not url.startswith("http") or h in ("unknown", "offline", ""):
        return "T3"
    if h in T2:
        return "T2"
    if h in T0 or h.endswith(".wikipedia.org"):
        return "T0"
    return "T1"


def split_for(subject_id: str) -> str:
    return "test" if int(hashlib.sha256(subject_id.encode()).hexdigest(), 16) % 10 < 3 else "dev"


def circuit_for(group: str, birth_year: int | None) -> str:
    c = CIRCUIT_BY_GROUP.get(group, "vital_records")
    if c == "civil_war_veteran" and not (birth_year and 1815 <= birth_year <= 1850):
        return "vital_records"  # v0 has no WWI, WWII or Korea circuit yet; said in the datasheet
    return c


def key_for(url: str, fallback: str) -> str:
    return "url:" + url.split("#")[0].rstrip("/").lower() if url.startswith("http") else fallback


def from_relatives(path: Path, year: int, log: list[str]) -> list[dict]:
    data = json.loads(path.read_text())
    out = []
    for d in data["relatives"]:
        inp = d["input"]
        p = Person(full_name=inp["fullName"], birth_year=inp.get("birthYear"), death_year=inp.get("deathYear"),
                   birth_place=inp.get("bornPlace"))
        g = gate(p, year)
        sid = f"kinrel-{d['dossier']}"
        log.append(f"{sid}: gate {'pass' if g.allowed else 'BLOCKED'} ({g.reason})")
        if not g.allowed:
            continue
        recs, private = [], Counter()
        for e in d["expected"]:
            url, host = e.get("url") or "", (e.get("host") or "").lower()
            t = tier(host, url)
            is_private = (not url.startswith("http")) or host in ("unknown", "offline") or "interview" in (e.get("title") or "").lower()
            if is_private:
                private[t] += 1
            public_url = url if (url.startswith("http") and host in PUBLIC_ARCHIVAL and not is_private) else None
            recs.append({"key": e.get("key") or key_for(url, f"{sid}:{e['id']}"), "id": e["id"], "host": host if not is_private else "private",
                         "url": public_url, "title": None, "tier": t, "tier_basis": "heuristic", "confirmed": False,
                         "kin_reach": e.get("reach"), "private": is_private, "hidden": True, "about_subject": None})
        out.append({"subject_id": sid, "source": "kin fixtures/evals/relatives.json (family dossier)", "group": "family",
                    "circuit": "vital_records", "split": split_for(sid),
                    "input": {"full_name": p.full_name, "name_variants": [], "birth_year": p.birth_year, "death_year": p.death_year,
                              "birth_place": p.birth_place, "death_place": None},
                    "gate": g.model_dump(), "records": recs,
                    "notes": "Titles withheld (family dossier). Private items counted, contents never released. "
                             "about_subject is unset: some dossier sources are period context, not records of the person."})
    return out


def from_heritage(path: Path, year: int, log: list[str]) -> list[dict]:
    data = json.loads(path.read_text())
    out = []
    for c in data["cases"]:
        p = Person(full_name=c["fullName"], birth_year=c.get("birthYear"), death_year=c.get("deathYear"),
                   birth_place=c.get("bornPlace"), death_place=c.get("diedPlace"))
        g = gate(p, year)
        sid = f"kinher-{c['id']}"
        log.append(f"{sid}: gate {'pass' if g.allowed else 'BLOCKED'} ({g.reason})")
        if not g.allowed:
            continue
        recs = [{"key": key_for(r.get("url") or "", f"{sid}:{r['id']}"), "id": r["id"], "host": (r.get("host") or "").lower(),
                 "url": r.get("url"), "title": r.get("title"), "kind": r.get("kind"), "tier": tier(r.get("host") or "", r.get("url") or ""),
                 "tier_basis": "heuristic", "confirmed": False, "kin_reach": r.get("reach"), "private": False, "hidden": True,
                 "about_subject": True, "kin_verified_note": r.get("verified")} for r in c["records"]]
        out.append({"subject_id": sid, "source": "kin fixtures/evals/heritage-real.json (public historical figure)", "group": c["group"],
                    "circuit": circuit_for(c["group"], p.birth_year), "split": split_for(sid),
                    "input": {"full_name": p.full_name, "name_variants": [], "birth_year": p.birth_year, "death_year": p.death_year,
                              "birth_place": p.birth_place, "death_place": p.death_place},
                    "gate": g.model_dump(), "records": recs,
                    "notes": "Wikipedia and Wikidata ids from kin are withheld from the card: they would hand the agent ground truth."})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--relatives", type=Path)
    ap.add_argument("--heritage", type=Path)
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parent / "data")
    ap.add_argument("--year", type=int, default=date.today().year)
    a = ap.parse_args()
    for f in (a.relatives, a.heritage):
        if f and "holdout" in f.name.lower():
            sys.exit(f"refusing {f.name}: holdout files are scored once, at the end, and never read while building")
    log: list[str] = []
    subjects = (from_relatives(a.relatives, a.year, log) if a.relatives else []) + (from_heritage(a.heritage, a.year, log) if a.heritage else [])
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "subjects.jsonl").write_text("".join(json.dumps(s, ensure_ascii=False) + "\n" for s in subjects))
    recs = [r for s in subjects for r in s["records"]]
    stats = {
        "version": VERSION, "built": str(date.today()), "subjects": len(subjects),
        "by_source": Counter(s["source"].split(" (")[0] for s in subjects),
        "by_split": Counter(s["split"] for s in subjects), "by_group": Counter(s["group"] for s in subjects),
        "by_circuit": Counter(s["circuit"] for s in subjects),
        "by_birth_era": Counter("pre-1850" if (s["input"]["birth_year"] or 0) < 1850 else "1850-1899" if s["input"]["birth_year"] < 1900 else "1900-1949"
                                for s in subjects),
        "records": len(recs), "by_tier": Counter(r["tier"] for r in recs), "private_records": sum(r["private"] for r in recs),
        "tier_rule": TIER_RULES, "tiers_confirmed": sum(r["confirmed"] for r in recs),
    }
    (a.out / "stats.json").write_text(json.dumps(stats, indent=2, default=dict) + "\n")
    (a.out / "build.log").write_text("\n".join(log) + "\n")
    print(json.dumps(stats, indent=2, default=dict))
    return 0


if __name__ == "__main__":
    sys.exit(main())
