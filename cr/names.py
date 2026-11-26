"""Name matching for snippets. Pure, deterministic."""
from __future__ import annotations

import re

from cr.models import Person


def _n(s: str) -> str:
    s = s.replace("**", " ")
    s = re.sub(r"[^A-Za-z ]", " ", s)
    return " ".join(s.lower().split())


def surname(p: Person) -> str:
    parts = p.full_name.replace(".", " ").split()
    return parts[-1] if parts else ""


def given(p: Person) -> str:
    parts = p.full_name.replace(".", " ").split()
    return parts[0] if parts else ""


def forms(p: Person) -> list[str]:
    out: set[str] = set()
    for name in p.all_names():
        toks = _n(name).split()
        toks = [t for t in toks if t not in ("jr", "sr", "dr", "mrs", "mr")]
        if len(toks) < 2:
            continue
        first, last, mids = toks[0], toks[-1], toks[1:-1]
        out.add(f"{first} {last}")
        out.add(f"{last} {first}")
        if mids:
            m = " ".join(x[0] for x in mids)
            out.add(f"{first} {m} {last}")
            out.add(f"{last} {first} {m}")
            out.add(f"{first[0]} {m} {last}")
            out.add(" ".join([first, *mids, last]))
    return sorted(out, key=len, reverse=True)


def match(p: Person, text: str) -> str:
    t = f" {_n(text)} "
    for f in forms(p):
        if f" {f} " in t:
            return "strong"
    if f" {surname(p).lower()} " in t:
        return "surname_only"
    return "none"


def town_state(place: str | None) -> tuple[str, str]:
    if not place:
        return "", ""
    parts = [x.strip() for x in place.split(",")]
    return parts[0], (parts[-1] if len(parts) > 1 else "")


ORD = {1: "First", 2: "Second", 3: "Third", 4: "Fourth", 5: "Fifth", 6: "Sixth", 7: "Seventh", 8: "Eighth", 9: "Ninth",
       10: "Tenth", 11: "Eleventh", 12: "Twelfth", 13: "Thirteenth", 14: "Fourteenth", 15: "Fifteenth", 16: "Sixteenth",
       17: "Seventeenth", 18: "Eighteenth", 19: "Nineteenth", 20: "Twentieth", 21: "Twenty-first", 22: "Twenty-second"}
WORD2NUM = {v.lower(): k for k, v in ORD.items()}
