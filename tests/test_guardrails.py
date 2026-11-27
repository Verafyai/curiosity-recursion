"""Hard guardrails for v0.2 (spec section 15): frozen inputs stay frozen, private data stays out of git,
no book page text in committed files, no em-dashes in changed prose or code."""
import hashlib
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
V010 = "v0.1.0"
# sha256 of cr/sources/exclusion.py and eval/corpus/subjects.jsonl at tag v0.1.0
EXCLUSION_SHA_V010 = "33bf0a6daf117ee7cb44b7526b36e1cacbf111a20a7dd5387710bf9c20cff2ee"
CARDS_SHA_V010 = "c78f2097c9ac0ace19394980f10cfe085b85db35666bef70ca0fb09047556c94"
SNIPPET_LIMIT = 600   # longest single text value allowed in a committed results file
EM_DASH = "\u2014"


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def git(*a) -> str:
    return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True, check=True).stdout


def test_exclusion_filter_unchanged():
    assert sha(ROOT / "cr/sources/exclusion.py") == EXCLUSION_SHA_V010
    from cr.sources import exclusion
    assert (exclusion.N, exclusion.MIN_SHARED, exclusion.MIN_FRAC) == (8, 5, 0.2)


def test_input_cards_unchanged():
    assert sha(ROOT / "eval/corpus/subjects.jsonl") == CARDS_SHA_V010


def test_answer_keys_match_lock():
    lock = json.loads((ROOT / "eval/answer_keys/v1/LOCK.json").read_text())
    for pid, rec in lock["people"].items():
        assert sha(ROOT / f"eval/answer_keys/v1/{pid}.jsonl") == rec["sha256_public"], pid
        priv = ROOT / f"eval/private/answer_keys/v1/{pid}.jsonl"
        if priv.exists():
            assert sha(priv) == rec["sha256_private"], pid


def test_no_private_files_tracked():
    tracked = git("ls-files").splitlines()
    bad = [f for f in tracked if f.startswith(("eval/private", "bench/data/private", "bench/corpus/"))]
    assert not bad, bad


def _long_strings(x, path=""):
    if isinstance(x, str):
        if len(x) > SNIPPET_LIMIT:
            yield path, len(x)
    elif isinstance(x, dict):
        for k, v in x.items():
            yield from _long_strings(v, f"{path}.{k}")
    elif isinstance(x, list):
        for i, v in enumerate(x):
            yield from _long_strings(v, f"{path}[{i}]")


def test_no_page_text_in_committed_results():
    tracked = [f for f in git("ls-files", "results", "benchmark").splitlines() if f.endswith((".jsonl", ".json"))]
    hits = []
    for f in tracked:
        txt = (ROOT / f).read_text(errors="replace")
        rows = txt.splitlines() if f.endswith(".jsonl") else [txt]
        for i, line in enumerate(rows):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            for p, n in _long_strings(obj):
                if any(k in p.lower() for k in ("text", "ocr", "page", "snippet", "quote", "content")):
                    hits.append((f, i, p, n))
    assert not hits, hits[:5]


def test_no_em_dash_in_changed_files():
    try:
        changed = git("diff", "--name-only", V010, "--", "*.md", "*.tex", "*.py").splitlines()
        changed += git("ls-files", "--others", "--exclude-standard", "--", "*.md", "*.tex", "*.py").splitlines()
    except subprocess.CalledProcessError:
        pytest.skip("tag v0.1.0 not available")
    bad = [f for f in set(changed) if (ROOT / f).exists() and EM_DASH in (ROOT / f).read_text(errors="replace")]
    assert not bad, bad
