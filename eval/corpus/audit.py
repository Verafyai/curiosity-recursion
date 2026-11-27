"""Scorer audit: sample about 20 match decisions per person and ask an independent judge
(a model call at temperature 0, no access to the scorer's decision) whether the evidence states
the fact. Reports agreement and Cohen's kappa. Positives are credited 1.0 decisions; negatives are
facts the scorer did not credit although a returned item names the person (hard negatives).

Usage: python eval/corpus/audit.py <bench out dir> [--per-person 20]
Writes <out>/private/audit.jsonl (quotes evidence, keep private) and <out>/audit.json (aggregate).
"""
from __future__ import annotations

import json
import os
import random
import re
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from eval.corpus.score import evidence, load_key, name_pattern  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
KEY, PRIV = ROOT / "eval/answer_keys/v1", ROOT / "eval/private/answer_keys/v1"
PROMPT = """You check a genealogy scorer. Person: {person}. Fact: "{value}"{date}.
Evidence text returned by a search tool (OCR, may be noisy):
<<<{ev}>>>
Does the evidence itself state this fact about this same person (not a namesake or relative)? Answer with one word: YES or NO."""


def judge(person, value, date, ev):
    from bench.baselines.llm_agents import _spend
    r = httpx.post("https://api.x.ai/v1/chat/completions", timeout=120, headers={"Authorization": f"Bearer {os.environ['XAI_API_KEY']}"},
                   json={"model": os.environ.get("CR_LLM_MODEL", "grok-4.20-0309-non-reasoning"), "temperature": 0, "max_tokens": 5,
                         "messages": [{"role": "user", "content": PROMPT.format(person=person, value=value, date=f" ({date})" if date else "", ev=ev[:1500])}]})
    r.raise_for_status()
    d = r.json()
    _spend(d.get("usage", {}).get("cost_in_usd_ticks", 0) / 1e10)
    return d["choices"][0]["message"]["content"].strip().upper().startswith("YES")


def window(text, pat):
    m = pat.search(" " + text.lower() + " ") if pat else None
    a = m.start() if m else 0
    return text[max(0, a - 700): a + 700]


def main(out: Path, per: int = 20):
    random.seed(20261126)
    rows, agg = [], {}
    runs = sorted((out / "private").glob("*.facts.json"))
    by_pid = {}
    for f in runs:
        stem = f.name[: -len(".facts.json")]
        pid = stem.rsplit("-b", 1)[0].split("-")[-1]
        by_pid.setdefault(pid, []).append(stem)
    for pid, stems in by_pid.items():
        key = {x["fact_id"]: x for x in load_key(KEY, pid, PRIV)}
        pos, neg = [], []
        for stem in stems:
            pf = json.loads((out / "private" / f"{stem}.facts.json").read_text())["per_fact"]
            items = None
            for p in pf:
                if p["score"] == 1.0 and p["evidence_snip"] is not None:
                    pos.append((stem, p))
                elif p["score"] == 0:
                    neg.append((stem, p))
        random.shuffle(pos); random.shuffle(neg)
        picked, cache = [], {}
        for stem, p in pos[: per // 2]:
            picked.append((stem, p, True))
        n_neg = 0
        for stem, p in neg:
            if n_neg >= per - len(picked):
                break
            if stem not in cache:
                cache[stem] = evidence(out / "logs" / f"{stem}.tools.jsonl")
            f = key[p["fact_id"]]
            pat = name_pattern(f["person"])
            cands = [it for it in cache[stem] if pat and pat.search(it["norm"])]
            if not cands:
                continue
            p = dict(p, _ev=window(max(cands, key=lambda it: sum(1 for w in re.findall(r"[a-z]{4,}", f["value"].lower()) if w in it["norm"]))["norm"], pat))
            picked.append((stem, p, False)); n_neg += 1
        for stem, p, scorer_yes in picked:
            f = key[p["fact_id"]]
            if scorer_yes:
                if stem not in cache:
                    cache[stem] = evidence(out / "logs" / f"{stem}.tools.jsonl")
                if p.get("evidence_window"):
                    ev = p["evidence_window"]  # the exact text window the scorer matched
                else:
                    full = next((it["raw"] for it in cache[stem] if it["url"] == p["evidence"] and name_pattern(f["person"]).search(it["norm"])), p["evidence_snip"])
                    ev = window(full, name_pattern(f["person"]))
            else:
                ev = p["_ev"]
            j = judge(f["person"], f["value"], f.get("date", ""), ev)
            rows.append({"person": pid, "run": stem, "fact_id": p["fact_id"], "scorer": scorer_yes, "judge": j, "how": p["how"],
                         "value": f["value"], "evidence": ev[:1000]})
        R = [r for r in rows if r["person"] == pid]
        agg[pid] = {"n": len(R), "agree": sum(r["scorer"] == r["judge"] for r in R) / len(R) if R else None,
                    "scorer_yes_judge_no": sum(r["scorer"] and not r["judge"] for r in R),
                    "scorer_no_judge_yes": sum(not r["scorer"] and r["judge"] for r in R)}
    n = len(rows)
    a = sum(r["scorer"] == r["judge"] for r in rows) / n if n else 0
    ps, pj = sum(r["scorer"] for r in rows) / n, sum(r["judge"] for r in rows) / n
    pe = ps * pj + (1 - ps) * (1 - pj)
    agg["_overall"] = {"n": n, "agree": a, "kappa": (a - pe) / (1 - pe) if pe < 1 else None,
                       "precision_of_scorer_yes": sum(r["scorer"] and r["judge"] for r in rows) / max(1, sum(r["scorer"] for r in rows)),
                       "judge_yes_rate_on_scorer_no": sum((not r["scorer"]) and r["judge"] for r in rows) / max(1, sum(not r["scorer"] for r in rows))}
    (out / "private" / "audit.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    (out / "audit.json").write_text(json.dumps(agg, indent=1))
    print(json.dumps(agg, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]), int(sys.argv[3]) if len(sys.argv) > 3 else 20)
