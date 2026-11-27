"""Name-spelling variants for the search ledger's `name_variant` key. Deterministic, local, no network.

Record-linkage practice (Christen 2012, `christen2012datamatching`): records print a name as initials,
with or without the middle name, with Saint spelled out or abbreviated, with dropped or doubled
letters, and OCR confuses some letter shapes (rn/m, li/h, e/c). Phonetic keys (Soundex, NYSIIS) group
spellings that sound alike; we use them to rank and to dedupe variants, never as search terms.
"""
from __future__ import annotations

import re
import unicodedata

OCR = (("rn", "m"), ("m", "rn"), ("li", "h"), ("h", "li"), ("e", "c"), ("c", "e"), ("cl", "d"), ("vv", "w"))
GIVEN_FORMS = {"william": ["wm", "will"], "john": ["jno"], "james": ["jas"], "charles": ["chas"], "thomas": ["thos"],
               "joseph": ["jos"], "george": ["geo"], "benjamin": ["benj"], "samuel": ["saml"], "robert": ["robt"],
               "edward": ["edw"], "richard": ["richd"], "alexander": ["alex"], "frederick": ["fred"], "erastus": ["erasthus"]}
PARTICLES = {"st", "saint", "ste", "van", "von", "de", "del", "la", "le", "du", "da", "di", "mac"}


def _ascii(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def split_name(full: str) -> tuple[list[str], str]:
    parts = [p.strip(".,") for p in _ascii(full).split() if p.strip(".,").lower() not in ("jr", "sr", "ii", "iii")]
    if len(parts) >= 3 and parts[-2].lower() in PARTICLES:
        return parts[:-2], f"{parts[-2]} {parts[-1]}"
    return parts[:-1], (parts[-1] if parts else "")


def soundex(word: str) -> str:
    w = re.sub(r"[^a-z]", "", _ascii(word).lower())
    if not w:
        return ""
    codes = {**dict.fromkeys("bfpv", "1"), **dict.fromkeys("cgjkqsxz", "2"), **dict.fromkeys("dt", "3"), "l": "4",
             **dict.fromkeys("mn", "5"), "r": "6"}
    out, last = w[0].upper(), codes.get(w[0], "")
    for ch in w[1:]:
        c = codes.get(ch, "")
        if c and c != last:
            out += c
        if ch not in "hw":
            last = c
    return (out + "000")[:4]


def nysiis(word: str) -> str:
    """A compact NYSIIS (New York State Identification and Intelligence System) key."""
    w = re.sub(r"[^A-Z]", "", _ascii(word).upper())
    if not w:
        return ""
    for a, b in (("MAC", "MCC"), ("KN", "NN"), ("K", "C"), ("PH", "FF"), ("PF", "FF"), ("SCH", "SSS")):
        if w.startswith(a):
            w = b + w[len(a):]
            break
    for a, b in (("EE", "Y"), ("IE", "Y"), ("DT", "D"), ("RT", "D"), ("RD", "D"), ("NT", "D"), ("ND", "D")):
        if w.endswith(a):
            w = w[: -len(a)] + b
            break
    key, prev = w[0], w[0]
    i = 1
    while i < len(w):
        c = w[i]
        if w[i:i + 2] == "EV":
            c, i = "AF", i + 1
        elif c in "AEIOU":
            c = "A"
        elif c == "Q":
            c = "G"
        elif c == "Z":
            c = "S"
        elif c == "M":
            c = "N"
        elif w[i:i + 2] == "KN":
            c = "N"
        elif c == "K":
            c = "C"
        elif w[i:i + 3] == "SCH":
            c, i = "SSS", i + 2
        elif w[i:i + 2] == "PH":
            c, i = "FF", i + 1
        elif c == "H" and (w[i - 1] not in "AEIOU" or (i + 1 < len(w) and w[i + 1] not in "AEIOU")):
            c = prev
        elif c == "W" and w[i - 1] in "AEIOU":
            c = prev
        if c[-1] != key[-1]:
            key += c
        prev = c[-1]
        i += 1
    if key.endswith("S") and len(key) > 1:
        key = key[:-1]
    if key.endswith("AY"):
        key = key[:-2] + "Y"
    if key.endswith("A") and len(key) > 1:
        key = key[:-1]
    return key[:6]


def _ocr_forms(word: str) -> list[str]:
    out = []
    lw = word.lower()
    for a, b in OCR:
        i = lw.find(a)
        if i > 0:
            out.append(word[:i] + b + word[i + len(a):])
    return out


def _letter_forms(word: str) -> list[str]:
    out = []
    for i in range(1, len(word)):
        if word[i] == word[i - 1]:
            out.append(word[:i] + word[i + 1:])  # dropped double letter
            break
    for i in range(1, len(word) - 1):
        if word[i] in "lnrst" and word[i] != word[i - 1] and word[i] != word[i + 1]:
            out.append(word[: i + 1] + word[i] + word[i + 1:])  # doubled letter
            break
    return out


def variants(full_name: str, limit: int = 16) -> list[str]:
    """Spelling variants of a full name, most common record forms first. The canonical name is not
    included. Deterministic: the same input always yields the same ordered list."""
    given, sur = split_name(full_name)
    if not given or not sur:
        return []
    g, mids = given[0], given[1:]
    sur_forms = [sur]
    if sur.lower().startswith(("st ", "saint ")):
        tail = sur.split(" ", 1)[1]
        sur_forms = [f"St. {tail}", f"Saint {tail}", f"St {tail}", f"St{tail}"]
    cands: list[str] = []
    for s in sur_forms:
        cands.append(f"{g} {s}")
        if mids:
            cands.append(f"{g} {' '.join(m[0] + '.' for m in mids)} {s}")
            cands.append(f"{g[0]}. {' '.join(m[0] + '.' for m in mids)} {s}")
        cands.append(f"{g[0]}. {s}")
        for alt in GIVEN_FORMS.get(g.lower(), []):
            cands.append(f"{alt.capitalize()} {s}" if alt != "wm" else f"Wm. {s}")
    base_sur = sur_forms[0].split()[-1]
    for w in _letter_forms(base_sur) + _ocr_forms(base_sur):
        cands.append(f"{g} {sur_forms[0][: len(sur_forms[0]) - len(base_sur)]}{w}")
    for w in _letter_forms(g) + _ocr_forms(g):
        cands.append(f"{w} {sur_forms[0]}")
    canon = re.sub(r"\s+", " ", _ascii(full_name).strip()).lower()
    out, seen = [], {canon}
    for c in cands:
        k = re.sub(r"\s+", " ", c.strip()).lower()
        if k not in seen:
            seen.add(k)
            out.append(re.sub(r"\s+", " ", c.strip()))
    return out[:limit]


def phonetic_key(name: str) -> str:
    given, sur = split_name(name)
    last = sur.split()[-1] if sur else ""
    return f"{soundex(given[0]) if given else ''}-{nysiis(last)}"
