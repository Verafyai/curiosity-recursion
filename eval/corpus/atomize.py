"""Build a corpus-replication answer key from one hand-curated dossier page (model-assisted).

    python eval/corpus/atomize.py <person_id> <dossier.txt> <out.jsonl>

The dossier text (body with [n] footnote marks, then the numbered reference list) goes to the
model once, at temperature 0, with the instruction to split it into atomic facts (one event,
date, place or relation each) and to cite the footnote numbers that support each fact. Code then
attaches the reference strings, classifies each source's access tier, and drops facts about people
presumed living. The output is reviewed by a person and hash-locked (bench/corpus/LOCK.json);
after that it is never edited to fit a run. This file is only for building the key: no condition
ever sees the dossier.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import httpx

PROMPT = """You turn a hand-curated genealogy dossier into an answer key of ATOMIC FACTS.

Rules:
- One fact = one event, date, place, relation, occupation, membership, physical description or record existence.
  Split compound sentences ("born 28 April 1834 in South Windsor, son of A and B") into separate facts
  (birth date, birth place, father, mother).
- Facts may be about the subject or about a named relative, when the dossier states them.
- Skip pure commentary, quotations of feelings, and statements that something was NOT found.
- For every fact give the footnote numbers [n] that support it (empty list if none).
- certainty: "documented" (a record says so), "family_account" (an interview or family tradition says so),
  "disputed" (the dossier says sources disagree).
Return ONLY a JSON array; each item:
{"person": "<name as in dossier>", "relation": "self|father|mother|spouse|child|sibling|grandparent|in-law|other",
 "type": "birth|death|burial|marriage|residence|occupation|military|education|migration|voyage|legal|physical|membership|property|record|relation|event|name",
 "value": "<one short sentence stating the fact>", "date": "<YYYY or YYYY-MM or YYYY-MM-DD or YYYY/YYYY range, or empty>",
 "place": "<place or empty>", "keywords": ["2 to 4 distinctive words a source stating this fact would contain"],
 "refs": [n, ...], "certainty": "documented|family_account|disputed"}

DOSSIER (subject: {subject}):
{text}
"""


def split_page(txt: str) -> tuple[str, list[str]]:
    i = txt.find("References")
    body, refs = txt[:i], txt[i + len("References"):]
    j = refs.find("\n Family\n")
    refs = refs[:j] if j > 0 else refs
    return body, [r.strip() for r in refs.strip().split("\n") if r.strip()]


def tier(ref: str) -> str:
    r = ref.lower()
    if re.search(r"interview recording|family archive|family account|information to the editors|the book of daniel", r):
        return "outreach"  # family interviews and family papers: reachable only by asking the family
    if re.search(r"supplied by|reply to|copies supplied|clipping supplied|research notes|research leads|letter from|ticket #", r):
        return "outreach"
    if re.search(r"ancestry|newspaperarchive|proquest|familysearch|fold3|newspapers\.com|genealogybank|myheritage", r):
        return "web_gated"
    if re.search(r"archive\.org/details|hathitrust|books\.google|gutenberg\.org", r) or (
            not re.search(r"https?://", r) and re.search(r"\(\s*(new york|boston|hartford|washington|london|springfield|[a-z ]+)?[:,]?[^)]*\b1[6-9]\d\d\)|\bed\.|pp\. \d", r)):
        return "book"
    if re.search(r"https?://", r):
        return "web_open"
    return "outreach"


def main() -> int:
    pid, src, out = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
    body, refs = split_page(src.read_text())
    numbered = "\n".join(f"[{k}] {r}" for k, r in enumerate(refs, 1))
    subject = body.split("·")[0].strip()
    key = os.environ["XAI_API_KEY"]
    paras = [x for x in body.split("\n") if x.strip()]
    chunks, cur = [], ""
    for x in paras:  # about 3,000 characters per call, so long dossiers are split as finely as short ones
        if len(cur) + len(x) > 3000 and cur:
            chunks.append(cur); cur = ""
        cur += x + "\n"
    chunks.append(cur)
    facts, cost = [], 0.0
    for ch in chunks:
        text = PROMPT.replace("{subject}", subject).replace("{text}", ch + "\n\nREFERENCES\n" + numbered)
        r = httpx.post("https://api.x.ai/v1/chat/completions", timeout=600, headers={"Authorization": f"Bearer {key}"},
                       json={"model": os.environ.get("CR_LLM_MODEL", "grok-4.20-0309-non-reasoning"), "temperature": 0,
                             "max_tokens": 16000, "messages": [{"role": "user", "content": text}]})
        r.raise_for_status()
        d = r.json()
        cost += d.get("usage", {}).get("cost_in_usd_ticks", 0) / 1e10
        m = re.search(r"\[.*\]", d["choices"][0]["message"]["content"], re.S)
        facts += json.loads(m.group(0)) if m else []
    if os.environ.get("CR_SPEND_FILE"):
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        from bench.baselines.llm_agents import _spend
        _spend(cost)
    rows = []
    for k, f in enumerate(facts, 1):
        srcs = []
        for n in f.get("refs") or []:
            if isinstance(n, int) and 1 <= n <= len(refs):
                ref = refs[n - 1]
                url = (re.findall(r"https?://\S+", ref) or [None])[0]
                srcs.append({"ref": n, "text": ref[:400], "url": url.rstrip(".,;") if url else None, "access_tier": tier(ref)})
        f.update(fact_id=f"{pid}-F{k:03d}", sources=srcs)
        rows.append(f)
    out.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows))
    (out.with_suffix(".refs.json")).write_text(json.dumps(refs, indent=1, ensure_ascii=False))
    print(f"{pid}: {len(rows)} facts, {len(refs)} references, ${cost:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
