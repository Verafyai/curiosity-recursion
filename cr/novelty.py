"""Canonical keys and novelty for question dedupe.

kappa(q): a normalised template key, for example `unit-books:12th-connecticut-infantry`. Two
questions with the same key are the same question, however they are worded.

For model-written questions, keys alone miss rewordings, so `near_duplicate()` also compares
word sets (Jaccard) and character sequences (difflib). Both are deterministic and need no
model or network. An embedding similarity can replace `similarity()`; report theta either way.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

STOP = {"a", "an", "the", "of", "in", "on", "and", "or", "to", "for", "is", "was", "did", "does", "do", "his", "her",
        "their", "he", "she", "they", "any", "which", "what", "who", "where", "when", "how", "by", "name", "named", "him"}


def canonical_key(*parts: str) -> str:
    return ":".join(re.sub(r"[^a-z0-9]+", "-", p.lower()).strip("-") for p in parts if p)


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOP}


def similarity(a: str, b: str) -> float:
    """Max of word-set Jaccard and character ratio, in [0, 1]."""
    wa, wb = _words(a), _words(b)
    jac = len(wa & wb) / len(wa | wb) if wa and wb else 0.0
    seq = SequenceMatcher(None, " ".join(sorted(wa)), " ".join(sorted(wb))).ratio() if wa and wb else 0.0
    return max(jac, seq)


def novelty(text: str, asked: list[str]) -> float:
    """1 minus the highest similarity to anything already asked (1.0 when nothing was asked)."""
    return 1.0 - max((similarity(text, a) for a in asked), default=0.0)


def near_duplicate(text: str, asked: list[str], theta: float = 0.85) -> bool:
    return any(similarity(text, a) >= theta for a in asked)
