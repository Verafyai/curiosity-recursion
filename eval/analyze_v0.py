"""Aggregate one DarkKin-Bench v0 run directory into results.json (every number in the paper).

    python eval/analyze_v0.py bench-runs/<stamp> [--temporal localhost:7233]

Scoring is automatic and conservative (eval/score.py): a hidden record counts when a citation
matches its canonical key. These are CANDIDATE matches: no human adjudication has been done,
so nothing here is "verified" in the preregistered sense. Records with no public URL (all T2
and T3 records and some T0 and T1 family records) cannot be matched automatically.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import statistics as stt
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from eval.score import keys_for, score_run  # noqa: E402
from eval.stats import bootstrap_ci, holm, mcnemar, noninferior, paired_diff_ci, wilcoxon  # noqa: E402
from bench.common import load_subjects  # noqa: E402

TIERS = ("T0", "T1", "T2", "T3")


def load(paths):
    out = []
    for p in paths:
        if p.exists():
            out += [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
    return out


def agg(rows, subs, note=""):
    """Macro recall (mean over subjects of per-subject recall, seeds averaged first), micro recall, tiers."""
    if not rows:
        return None
    per_sub = defaultdict(list)
    for r in rows:
        per_sub[r["subject_id"]].append(r)
    rec, rec_url, hits, n, n_url = [], [], 0, 0, 0
    tier = {t: [0, 0] for t in TIERS}
    for sid, rs in per_sub.items():
        s = subs[sid]
        nurl = sum(1 for x in s["records"] if x.get("url") and x.get("about_subject") is not False)
        rec.append(stt.mean(x["candidate_recall"] for x in rs))
        rec_url.append(stt.mean(x["candidate_hits"] / nurl for x in rs) if nurl else 0.0)
        for x in rs:
            hits += x["candidate_hits"]; n += x["n_hidden"]; n_url += nurl
            for t, v in x["by_tier"].items():
                tier[t][0] += v["hits"]; tier[t][1] += v["n"]
    m, lo, hi = bootstrap_ci(rec)
    return {"n_subjects": len(per_sub), "n_runs": len(rows), "macro_recall": m, "ci95": [lo, hi],
            "micro_recall": hits / n if n else None, "micro_recall_url_records": hits / n_url if n_url else None,
            "macro_recall_url_records": stt.mean(rec_url),
            "by_tier": {t: {"hits": h, "n": k, "recall": (h / k if k else None)} for t, (h, k) in tier.items()},
            "per_subject": {sid: v for sid, v in zip(per_sub, rec)}}


def dup_question_rate(run):
    qs = run.get("questions") or []
    if not qs:
        return None
    keys = [q.get("key") for q in qs if q.get("key")]
    return (len(keys) - len(set(keys))) / len(keys) if keys else None


def norm(u):
    return next(iter(sorted(keys_for(u))), "")


def fabricated_urls(run):
    """URLs in an LLM agent's final answer that no tool call returned (possible fabrications)."""
    text = run.get("final_answer") or ""
    urls = set(re.findall(r"https?://[^\s\)\]>\"'`,]+", text))
    if not urls:
        return 0, 0
    returned = set()
    for c in run.get("citations", []):
        returned |= keys_for(c.get("url"), c.get("item_id"))
    bad = [u for u in urls if not (keys_for(u.rstrip(".")) & returned)]
    return len(bad), len(urls)


async def b5_activity_counts(addr, run_ids):
    from temporalio.client import Client
    c = await Client.connect(addr)
    out = {}
    for rid in run_ids:
        try:
            done = sched = 0
            for wid in (rid, rid + "-checklist"):
                async for e in c.get_workflow_handle(wid).fetch_history_events():
                    if e.HasField("activity_task_completed_event_attributes"):
                        done += 1
                    if e.HasField("activity_task_scheduled_event_attributes"):
                        sched += 1
            out[rid] = {"completed": done, "scheduled": sched}
        except Exception as e:  # history gone
            out[rid] = {"error": str(e)}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("rundir", type=Path)
    ap.add_argument("--temporal", default="localhost:7233")
    a = ap.parse_args()
    R = a.rundir
    subs = {s["subject_id"]: s for s in load_subjects("all")}
    test_ids = {k for k, s in subs.items() if s["split"] == "test"}
    res = {"rundir": str(R), "commit": (R / "commit.txt").read_text().strip() if (R / "commit.txt").exists() else None,
           "scoring": "automatic canonical-key candidate matches; not adjudicated", "spend_usd": None}
    if (R / "spend_usd.txt").exists():
        res["spend_usd"] = float((R / "spend_usd.txt").read_text() or 0)
    h1 = load(sorted(R.glob("h1-*.jsonl")))
    scored = []
    for r in h1:
        if r["subject_id"] in subs:
            s = score_run(r, subs[r["subject_id"]], {})
            s.update(usd=r.get("usd", 0.0), wall=r.get("wall_seconds"), tokens=r.get("llm_tokens", 0), stop=r.get("stop_reason"),
                     dupq=dup_question_rate(r), fab=fabricated_urls(r) if r["agent"] in ("B0", "B1") else None,
                     documented=len(r.get("documented_claims") or []), drafts=len(r.get("drafts") or []))
            scored.append(s)
    (R / "h1.scores.jsonl").write_text("".join(json.dumps(x) + "\n" for x in scored))
    ok = [x for x in scored if x["completed"]]
    res["h1_not_completed"] = [{"agent": x["agent"], "subject": x["subject_id"], "budget": x["budget"], "seed": x["seed"], "stop": x["stop"]}
                               for x in scored if not x["completed"]]
    by = defaultdict(list)
    for x in ok:
        by[(x["agent"], x["budget"])].append(x)
    res["h1"] = {}
    for (ag, b), rows in sorted(by.items()):
        k = f"{ag}@{b}"
        res["h1"][k] = {"all": agg(rows, subs), "test": agg([x for x in rows if x["subject_id"] in test_ids], subs),
                        "dev": agg([x for x in rows if x["subject_id"] not in test_ids], subs),
                        "seeds": sorted({x["seed"] for x in rows}),
                        "tool_calls_mean": stt.mean(x["tool_calls"] or 0 for x in rows),
                        "tool_calls_max": max(x["tool_calls"] or 0 for x in rows),
                        "budget_bound_share": sum(1 for x in rows if "budget" in (x["stop"] or "")) / len(rows),
                        "tokens_mean": stt.mean(x["tokens"] or 0 for x in rows), "usd_total": sum(x["usd"] or 0 for x in rows),
                        "usd_mean": stt.mean(x["usd"] or 0 for x in rows),
                        "wall_mean_s": stt.mean(x["wall"] or 0 for x in rows), "wall_median_s": stt.median(x["wall"] or 0 for x in rows),
                        "hits_total": sum(x["candidate_hits"] for x in rows),
                        "calls_per_hit": (sum(x["tool_calls"] or 0 for x in rows) / sum(x["candidate_hits"] for x in rows)) if sum(x["candidate_hits"] for x in rows) else None,
                        "usd_per_hit": (sum(x["usd"] or 0 for x in rows) / sum(x["candidate_hits"] for x in rows)) if sum(x["candidate_hits"] for x in rows) else None,
                        "hosts_cited_mean": stt.mean(x["hosts_cited"] for x in rows),
                        "questions_mean": stt.mean(x["questions"] for x in rows),
                        "grounded_share": (stt.mean(x["grounded_share"] for x in rows if x["grounded_share"] is not None)
                                           if any(x["grounded_share"] is not None for x in rows) else None),
                        "duplicate_question_rate": (stt.mean(x["dupq"] for x in rows if x["dupq"] is not None)
                                                    if any(x["dupq"] is not None for x in rows) else None),
                        "hit_depths": sorted(d for x in rows for d in x["hit_depths"]),
                        "first_hit_order_median": (stt.median(x["first_hit_order"] for x in rows if x["first_hit_order"] is not None)
                                                   if any(x["first_hit_order"] is not None for x in rows) else None),
                        "documented_claims_mean": stt.mean(x["documented"] for x in rows),
                        "leads_mean": stt.mean(x["leads"] for x in rows),
                        "drafts_mean": stt.mean(x["drafts"] for x in rows),
                        "fabricated_urls": ([sum(x["fab"][0] for x in rows), sum(x["fab"][1] for x in rows)] if ag in ("B0", "B1") else None)}
    # H1 paired tests at each budget where B5 exists: B5 vs B0, B1, B3 (seeds averaged per subject).
    res["h1_tests"] = {}
    for b in sorted({x["budget"] for x in ok}):
        def per(ag, split=None):
            d = defaultdict(list)
            for x in by.get((ag, b), []):
                if split is None or (x["subject_id"] in test_ids) == (split == "test"):
                    d[x["subject_id"]].append(x["candidate_recall"])
            return {k: stt.mean(v) for k, v in d.items()}
        for split in (None, "test"):
            b5 = per("B5", split)
            if not b5:
                continue
            pv, out = {}, {}
            for base in ("B0", "B1", "B3"):
                bb = per(base, split)
                common = sorted(set(b5) & set(bb))
                if len(common) < 3:
                    continue
                x, y = [b5[k] for k in common], [bb[k] for k in common]
                stat, p = wilcoxon(x, y)
                m, lo, hi = paired_diff_ci(x, y)
                out[base] = {"n": len(common), "mean_diff": m, "ci95": [lo, hi], "wilcoxon_p": p,
                             "b5_better": sum(1 for i, j in zip(x, y) if i > j), "b5_worse": sum(1 for i, j in zip(x, y) if i < j),
                             "ties": sum(1 for i, j in zip(x, y) if i == j)}
                pv[base] = p
            for base, (adj, rej) in holm(pv).items():
                out[base].update(holm_p=adj, reject=rej)
            res["h1_tests"][f"B={b}" + ("" if split is None else ",test")] = out
            # Post hoc, NOT preregistered: B5-max against the same baselines and against B5. Own Holm family.
            bm = per("B5-max", split)
            if bm:
                pv2, out2 = {}, {}
                for base in ("B0", "B1", "B3", "B5"):
                    bb = per(base, split)
                    common = sorted(set(bm) & set(bb))
                    if len(common) < 3:
                        continue
                    x, y = [bm[k] for k in common], [bb[k] for k in common]
                    stat, p = wilcoxon(x, y)
                    m, lo, hi = paired_diff_ci(x, y)
                    out2[base] = {"n": len(common), "mean_diff": m, "ci95": [lo, hi], "wilcoxon_p": p,
                                  "max_better": sum(1 for i, j in zip(x, y) if i > j), "max_worse": sum(1 for i, j in zip(x, y) if i < j)}
                    pv2[base] = p
                for base, (adj, rej) in holm(pv2).items():
                    out2[base].update(holm_p=adj, reject=rej)
                res.setdefault("h1_tests_posthoc_B5max", {})[f"B={b}" + ("" if split is None else ",test")] = out2
    # H2 faults.
    h2 = load([R / "h2" / "h2-B5.jsonl"]) + load([R / "h2" / "h2-B4.jsonl"])
    counts = asyncio.run(b5_activity_counts(a.temporal, [x["run_id"] for x in h2 if x["agent"] == "B5"])) if h2 else {}
    rows = []
    # Lines written before the faults dict carried kill_every_s all came from the 45 s kill lanes.
    kon = lambda f: bool(f.get("kill_every_s", 45))
    # One rerun of an infrastructure failure is allowed (prereg): keep the completed line per cell if any.
    best = {}
    for x in h2:
        f = x.get("faults") or {}
        key = (x["agent"], f.get("p"), kon(f), x.get("seed"), x["subject_id"])
        if key not in best or (x.get("completed") and not best[key].get("completed")):
            best[key] = x
    res["h2_reruns_superseded"] = len(h2) - len(best)
    for x in best.values():
        f = x.get("faults") or {}
        sc = score_run(x, subs[x["subject_id"]], {}) if x.get("completed") else None
        if x["agent"] == "B5":
            cnt = counts.get(x["run_id"], {})
            dup = (x.get("repeated_activities", 0) / cnt["completed"]) if x.get("completed") and cnt.get("completed") else None
        else:
            dup = (x.get("activities_completed_lost", 0) / x["activities_completed_final"]) if x.get("completed") and x.get("activities_completed_final") else None
        rows.append({"agent": x["agent"], "p": f.get("p"), "kills_on": kon(f), "seed": x.get("seed"), "subject": x["subject_id"],
                     "completed": bool(x.get("completed")), "kills": len(x.get("kills") or []), "restarts": x.get("restarts"),
                     "repeated_activities": x.get("repeated_activities"), "activities": counts.get(x["run_id"]) if x["agent"] == "B5" else
                     {"final": x.get("activities_completed_final"), "lost": x.get("activities_completed_lost")},
                     "dup_ratio": dup, "wall_s": x.get("wall_seconds"), "history_events": x.get("history_events"),
                     "recall": sc["candidate_recall"] if sc else None, "stop": x.get("stop_reason")})
    res["h2_runs"] = rows
    res["h2"] = {}
    for cond in sorted({(r["p"], r["kills_on"]) for r in rows}, key=str):
        g = {ag: [r for r in rows if r["agent"] == ag and (r["p"], r["kills_on"]) == cond] for ag in ("B5", "B4")}
        summ = {}
        for ag, rs in g.items():
            if rs:
                d = [r["dup_ratio"] for r in rs if r["dup_ratio"] is not None]
                summ[ag] = {"runs": len(rs), "completed": sum(r["completed"] for r in rs), "kills_total": sum(r["kills"] for r in rs),
                            "dup_ratio_mean": stt.mean(d) if d else None, "dup_ci95": list(bootstrap_ci(d)[1:]) if len(d) > 1 else None,
                            "wall_mean_s": stt.mean(r["wall_s"] or 0 for r in rs),
                            "recall_mean_completed": stt.mean(r["recall"] for r in rs if r["recall"] is not None) if any(r["recall"] is not None for r in rs) else None}
        pa = {(r["subject"], r["seed"]): r["completed"] for r in g["B5"]}
        pb = {(r["subject"], r["seed"]): r["completed"] for r in g["B4"]}
        common = sorted(set(pa) & set(pb))
        if common:
            b01, b10, p = mcnemar([pa[k] for k in common], [pb[k] for k in common])
            summ["mcnemar"] = {"pairs": len(common), "b5_only": b10, "b4_only": b01, "p": p}
        res["h2"][f"p={cond[0]},kills={'on' if cond[1] else 'off'}"] = summ
    # H3 memory and ablations.
    r1, r2 = load([R / "h3-run1.jsonl"]), load([R / "h3-run2.jsonl"])
    if r1 and r2:
        s1 = {x["subject_id"]: score_run(x, subs[x["subject_id"]], {}) for x in r1 if x.get("completed")}
        s2 = {x["subject_id"]: score_run(x, subs[x["subject_id"]], {}) for x in r2 if x.get("completed")}
        common = sorted(set(s1) & set(s2))
        c1, c2 = [s1[k]["tool_calls"] for k in common], [s2[k]["tool_calls"] for k in common]
        h1r, h2r = [s1[k]["candidate_recall"] for k in common], [s2[k]["candidate_recall"] for k in common]
        res["h3"] = {"n": len(common), "calls_run1_mean": stt.mean(c1), "calls_run2_mean": stt.mean(c2),
                     "recall_run1_mean": stt.mean(h1r), "recall_run2_mean": stt.mean(h2r),
                     "calls_wilcoxon_p": wilcoxon(c2, c1)[1], "recall_wilcoxon_p": wilcoxon(h2r, h1r)[1],
                     "run2_fewer_calls": sum(1 for a_, b_ in zip(c2, c1) if a_ < b_), "run2_more_calls": sum(1 for a_, b_ in zip(c2, c1) if a_ > b_),
                     "first_hit_order": {"run1": [s1[k]["first_hit_order"] for k in common], "run2": [s2[k]["first_hit_order"] for k in common]},
                     "per_subject": {k: {"run1": [s1[k]["tool_calls"], s1[k]["candidate_hits"]], "run2": [s2[k]["tool_calls"], s2[k]["candidate_hits"]]} for k in common}}
    abl = load([R / "ablate.jsonl", R / "ablate-rerun.jsonl"]) + r1
    if abl:
        by_a = defaultdict(list)
        for x in abl:
            if x.get("completed"):
                sc = score_run(x, subs[x["subject_id"]], {})
                sc["dupq"] = dup_question_rate(x)
                by_a[x["agent"] if x not in r1 else "B5 (full, h3 run 1)"].append(sc)
        res["ablations"] = {k: {"n": len(v), "macro_recall": stt.mean(s["candidate_recall"] for s in v),
                                "hits": sum(s["candidate_hits"] for s in v), "records": sum(s["n_hidden"] for s in v),
                                "tool_calls_mean": stt.mean(s["tool_calls"] or 0 for s in v), "questions_mean": stt.mean(s["questions"] for s in v),
                                "duplicate_question_rate": stt.mean(s["dupq"] for s in v if s["dupq"] is not None) if any(s["dupq"] is not None for s in v) else None}
                            for k, v in sorted(by_a.items())}
        res["ablations_not_completed"] = [(x["agent"], x["subject_id"], x.get("stop_reason")) for x in load([R / "ablate.jsonl", R / "ablate-rerun.jsonl"]) if not x.get("completed")]
    (R / "results.json").write_text(json.dumps(res, indent=1, default=str))
    print(json.dumps({k: res[k] for k in res if k in ("spend_usd", "h1_tests", "h2", "h3")}, indent=1, default=str)[:6000])
    for k, v in res.get("h1", {}).items():
        a_ = v["all"]
        print(f"{k:<10} n={a_['n_subjects']:<3} runs={a_['n_runs']:<3} macro={a_['macro_recall']:.3f} [{a_['ci95'][0]:.3f},{a_['ci95'][1]:.3f}] micro={a_['micro_recall']:.3f} "
              f"T0={a_['by_tier']['T0']['recall']} T1={a_['by_tier']['T1']['recall']} calls={v['tool_calls_mean']:.1f} usd={v['usd_total']:.3f} wall={v['wall_mean_s']:.0f}s")


if __name__ == "__main__":
    main()
