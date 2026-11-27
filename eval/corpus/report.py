"""Score every run in a corpus-bench output dir and write RESULTS.md, results.json and a chart.

Public outputs carry aggregates only. Per-fact tables (which approach found which fact) go to
<out>/private/ and must not be published (they quote dossier facts, including gated relatives).
"""
from __future__ import annotations

import json
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from eval.corpus.score import evidence, load_key, score_run  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
KEY = ROOT / "eval/answer_keys/v1"
PRIV = ROOT / "eval/private/answer_keys/v1"
LIFE = {"burnham": (1834, 1921), "homer": (1900, 1972), "john": (1921, 2006), "kingsley": (1907, 1962), "bristol": (1871, 1944), "alex": (1967, 2026)}
ERA = {"burnham": "Civil War", "homer": "WWI", "john": "WWII", "kingsley": "civilian", "bristol": "civilian", "alex": "civilian"}
LABEL = {"B0": "single-pass LLM search", "B1": "ReAct LLM agent", "B3": "checklist only", "B5": "CR (preregistered)",
         "B5-max": "CR wider (post hoc)", "B5-fix": "CR rules2 (post hoc fix)",
         "B5-llm": "CR, model question generator (ablation, post hoc)",
         "B6-swarm": "CR v0.2 swarm (preregistered)", "B6-no-ledger": "swarm without ledger rules (ablation)",
         "B6-no-parallel": "swarm with one worker (ablation)", "B6-no-reflect": "swarm without reflection (ablation)",
         "B6-v1tools": "swarm without ia_fts (ablation)"}
TIERS = ("web_open", "book", "web_gated", "outreach")


def ms(xs):
    xs = [x for x in xs if x is not None]
    if not xs:
        return [None, None]
    return [st.mean(xs), (st.stdev(xs) if len(xs) > 1 else 0.0)]


def mean_or_none(xs):
    xs = [x for x in xs if x is not None]
    return st.mean(xs) if xs else None


def main(out: Path, truncate: int | None = None) -> None:
    """Score all runs. With truncate=N, score only the first N logged calls of every run (spec v0.2
    section 9) and write to <out>/truncated/n<N>/ (private tables to <out>/private/truncated-n<N>/)."""
    lock = json.loads((KEY / "LOCK.json").read_text())
    rows, perfact = [], {}
    src = out
    dst = out if truncate is None else out / "truncated" / f"n{truncate}"
    priv = out / "private" if truncate is None else out / "private" / f"truncated-n{truncate}"
    dst.mkdir(parents=True, exist_ok=True)
    priv.mkdir(parents=True, exist_ok=True)
    for rf in sorted((src / "runs").glob("*.jsonl")):
        lines = [x for x in rf.read_text().splitlines() if x.strip()]
        if not lines:
            continue
        run = json.loads(lines[-1])
        name = rf.stem
        stem = name.rsplit("-b", 1)[0]
        pid = stem.split("-")[-1]
        cond = stem[: -(len(pid) + 1)]
        key = load_key(KEY, pid, PRIV if PRIV.exists() else None)
        tl = src / "logs" / f"{name}.tools.jsonl"
        s = score_run(run, evidence(tl, truncate), key, LIFE[pid], {f["person"] for f in key}, truncated=truncate is not None)
        bl = src / "logs" / f"{name}.blocked.jsonl"
        blocked = [json.loads(x) for x in bl.read_text().splitlines() if x.strip()] if bl.exists() else []
        rows.append({"run": name, "condition": cond, "person": pid, "era": ERA[pid], "seed": run.get("seed"), "budget": run.get("budget"),
                     "completed": run.get("completed"), "stop_reason": run.get("stop_reason"), "tool_calls": (run.get("tool_calls") if truncate is None or run.get("tool_calls") is None else min(run["tool_calls"], truncate)),
                     "logged_calls": (sum(1 for _ in tl.open()) if tl.exists() else None),
                     "wall_seconds": run.get("wall_seconds"), "usd": run.get("usd") or 0.0, "llm_tokens": run.get("llm_tokens") or 0, "tool_log": tl.exists(),
                     "blocked_host": sum(1 for b in blocked if b.get("reason") == "blocked_host"),
                     "dropped_overlap": sum(1 for b in blocked if b.get("reason") == "dossier_overlap"),
                     **{k: v for k, v in s.items() if not k.startswith("_")}})
        for p in s["_per_fact"]:
            perfact.setdefault(pid, {}).setdefault(p["fact_id"], {}).setdefault(cond, []).append(p["score"])
        (priv / f"{name}.facts.json").write_text(json.dumps({"per_fact": s["_per_fact"], "novel": s["_novel"]}, indent=1))
    conds = [c for c in LABEL if any(r["condition"] == c for r in rows)] + sorted({r["condition"] for r in rows} - set(LABEL))
    people = [p for p in LIFE if any(r["person"] == p for r in rows)]
    agg = {"answer_key": {"version": lock["version"], "frozen": lock["frozen"],
                          "sha256_public": {p: lock["people"][p]["sha256_public"] for p in lock["people"]}}, "conditions": {}}
    for c in conds:
        R = [r for r in rows if r["condition"] == c]
        per = {}
        for p in people:
            P = [r for r in R if r["person"] == p]
            if not P:
                continue
            per[p] = {"n_runs": len(P), "recall": ms([r["recall"] for r in P]), "penalised": ms([r["penalised"] for r in P]),
                      "reachable_recall": ms([r["reachable_recall"] for r in P]), "reachable_n": P[0]["reachable_n"],
                      "full_credit_recall": ms([r["recall_full_credit_only"] for r in P]),
                      "source_recall": ms([r["source_recall"] for r in P]), "precision": ms([r["precision"] for r in P]),
                      "holdout_recall": ms([r["holdout_recall"] for r in P]), "novel_candidates": ms([r["novel_candidates"] for r in P]),
                      "false_links": sum(r["false_links"] for r in P), "tool_calls": ms([r["tool_calls"] for r in P]),
                      "by_tier": {t: ms([r["by_tier"].get(t, {}).get("recall") for r in P]) for t in TIERS}}
        eras = {}
        for p, v in per.items():
            eras.setdefault(ERA[p], []).append(v["recall"][0])
        agg["conditions"][c] = {"label": LABEL.get(c, c), "per_person": per,
                                "overall_recall": mean_or_none([v["recall"][0] for v in per.values()]),
                                "overall_reachable_recall": mean_or_none([v["reachable_recall"][0] for v in per.values() if v["reachable_recall"][0] is not None]),
                                "overall_penalised": mean_or_none([v["penalised"][0] for v in per.values()]),
                                "by_era": {e: st.mean(v) for e, v in eras.items()},
                                "usd": (None if c == "B5-llm" and not sum(r["usd"] for r in R) else sum(r["usd"] for r in R)), "runs": len(R), "llm_tokens": sum(r.get("llm_tokens") or 0 for r in R),
                                "runs_missing_tool_log": sum(1 for r in R if not r["tool_log"]),
                                "blocked_host": sum(r["blocked_host"] for r in R), "dropped_overlap": sum(r["dropped_overlap"] for r in R)}
    (dst / "results.json").write_text(json.dumps({"aggregate": agg, "runs": rows}, indent=1))
    with (priv / "per-fact-table.md").open("w") as fh:
        for p, facts in perfact.items():
            key = {f["fact_id"]: f for f in load_key(KEY, p, PRIV if PRIV.exists() else None)}
            fh.write(f"\n## {p}\n\n| fact | tier | holdout | " + " | ".join(conds) + " |\n|---|---|---|" + "---|" * len(conds) + "\n")
            for fid, by in facts.items():
                f = key[fid]
                tier = next((k for k in TIERS if k in {s["access_tier"] for s in f["sources"]}), "none")
                cells = [f"{st.mean(by[c]):.2f}" if c in by else "" for c in conds]
                fh.write(f"| {fid}: {f['value'][:70]} | {tier} | {'y' if f['holdout'] else ''} | " + " | ".join(cells) + " |\n")
    pct = lambda x: "n.m." if x is None else f"{100 * x:.1f}%"  # noqa: E731
    pm = lambda m: "n.m." if m[0] is None else f"{100 * m[0]:.1f} ± {100 * m[1]:.1f}"  # noqa: E731
    eras_sorted = [e for e in ("Civil War", "WWI", "WWII", "civilian") if any(ERA[p] == e for p in people)]
    L = ["# Corpus replication results", "",
         f"Answer key {lock['version']} (frozen {lock['frozen']}); facts per person: " + ", ".join(f"{p} {lock['people'][p]['facts_total']}" for p in people) + ".",
         "", "Score = % of the hand-built dossier recovered in one pass (1.0 fact found with a source; 0.5 named the right book or archive; 0 miss). Mean ± sd over runs, in percent.",
         "", "| strategy | " + " | ".join(f"{p} ({ERA[p]})" for p in people) + " | overall | penalised | spend |", "|---|" + "---|" * (len(people) + 3)]
    for c, v in agg["conditions"].items():
        L.append(f"| {c} {v['label']} | " + " | ".join(pm(v["per_person"][p]["recall"]) if p in v["per_person"] else "n.m." for p in people) +
                 f" | {pct(v['overall_recall'])} | {pct(v['overall_penalised'])} | {'n.m.' if v['usd'] is None else f"${v['usd']:.2f}"} |")
    L += ["", "## Reachability ceiling: score on the reachable subset", "",
          "A fact is reachable when at least one of its dossier sources is on archive.org, loc.gov or wikidata.org, the only hosts the bench tools query. Overall (reachable) is the mean over people with at least one reachable fact (Homer has none). "
          "Facts reachable per person: " + ", ".join(f"{p} {next((v['per_person'][p]['reachable_n'] for v in agg['conditions'].values() if p in v['per_person']), 0)}/{lock['people'][p]['facts_total']}" for p in people) + ".", "",
          "| strategy | " + " | ".join(f"{p} reachable" for p in people) + " | overall (reachable) | overall (full dossier) |", "|---|" + "---|" * (len(people) + 2)]
    for c, v in agg["conditions"].items():
        L.append(f"| {c} | " + " | ".join(pm(v["per_person"][p]["reachable_recall"]) if p in v["per_person"] and v["per_person"][p]["reachable_recall"][0] is not None else "n.m." for p in people) +
                 f" | {pct(v.get('overall_reachable_recall'))} | {pct(v['overall_recall'])} |")
    L += ["", "## By era", "", "| strategy | " + " | ".join(eras_sorted) + " |", "|---|" + "---|" * len(eras_sorted)]
    for c, v in agg["conditions"].items():
        L.append(f"| {c} | " + " | ".join(pct(v["by_era"].get(e)) for e in eras_sorted) + " |")
    L += ["", "## By access tier (mean over people)", "", "| strategy | web_open | book | web_gated | outreach |", "|---|---|---|---|---|"]
    for c, v in agg["conditions"].items():
        L.append(f"| {c} | " + " | ".join(pct(mean_or_none([pp["by_tier"][t][0] for pp in v["per_person"].values()])) for t in TIERS) + " |")
    L += ["", "## Other measures (mean over people)", "",
          "| strategy | full-credit recall | holdout recall | source recall | precision | novel candidates/run | false links | tool calls/run |",
          "|---|---|---|---|---|---|---|---|"]
    for c, v in agg["conditions"].items():
        P = list(v["per_person"].values())
        g = lambda k: mean_or_none([pp[k][0] for pp in P])  # noqa: E731
        nc, tc = g("novel_candidates"), g("tool_calls")
        L.append(f"| {c} | {pct(g('full_credit_recall'))} | {pct(g('holdout_recall'))} | {pct(g('source_recall'))} | {pct(g('precision'))} | "
                 f"{'n.m.' if nc is None else f'{nc:.1f}'} | {sum(pp['false_links'] for pp in P)} | {'n.m.' if tc is None else f'{tc:.1f}'} |")
    L += ["", "## Leakage audit", "", "Exclusion filter on for every run (host blocklist plus dossier 8-gram content guard).", "",
          "| strategy | runs | blocked (host) | dropped (dossier overlap) | runs without tool log |", "|---|---|---|---|---|"]
    for c, v in agg["conditions"].items():
        L.append(f"| {c} | {v['runs']} | {v['blocked_host']} | {v['dropped_overlap']} | {v['runs_missing_tool_log']} |")
    (dst / "RESULTS.md").write_text("\n".join(L) + "\n")
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(8, 3.6))
        w = 0.8 / max(1, len(conds))
        for i, c in enumerate(conds):
            v = agg["conditions"][c]["per_person"]
            xs = [j + i * w for j in range(len(people))]
            ax.bar(xs, [100 * v[p]["recall"][0] if p in v else 0 for p in people], w,
                   yerr=[100 * v[p]["recall"][1] if p in v else 0 for p in people], label=c, capsize=2)
        ax.set_xticks([j + w * (len(conds) - 1) / 2 for j in range(len(people))])
        ax.set_xticklabels([f"{p}\n{ERA[p]}" for p in people])
        ax.set_ylabel("% of dossier recovered")
        ax.legend(fontsize=7, ncol=3)
        fig.tight_layout()
        fig.savefig(dst / "corpus-recall.png", dpi=160)
        fig.savefig(dst / "corpus-recall.pdf")
    except ImportError:
        print("matplotlib missing: no chart", file=sys.stderr)
    print((dst / "RESULTS.md").read_text())


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("--truncate-calls", type=int, default=None)
    a = ap.parse_args()
    main(a.out, a.truncate_calls)
