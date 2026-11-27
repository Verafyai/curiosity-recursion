"""Preregistered v0.2 verdicts (bench/PREREGISTRATION-v0.2.md) computed from results files only.

Inputs in <run dir>: results.json (report.py), truncated/n<N>/results.json (report.py --truncate-calls N),
diagnose-runs.json (diagnose.py). Writes <run dir>/h6.json. Nothing here is tuned to results: the rule,
the reachable people, the thresholds and the matched-budget N (median logged calls of B1) are fixed in
the preregistration.

"A beats C" on the primary metric (full-dossier overall recall) means all of:
  1. mean per-person difference > 0;
  2. A wins on at least 3 of the 4 people with reachable facts (burnham, kingsley, bristol, alex) and
     loses none of them by more than 2 points;
  3. A's run-to-run interval (mean minus sd of per-seed overall recall) lies above C's mean.
"""
from __future__ import annotations

import json
import statistics as st
import sys
from pathlib import Path

REACHABLE = ("burnham", "kingsley", "bristol", "alex")
MAX_LOSS = 0.02
MIN_WINS = 3
B6, B1, B5F = "B6-swarm", "B1", "B5-fix"
PREC_TOL = 0.03
REPEAT_MAX = 0.02
USE_MIN = 0.80
CURVE_N = (10, 25, 50, 75, 100)


def seed_overall(rows, cond, metric="recall"):
    by = {}
    for r in rows:
        if r["condition"] == cond and r.get(metric) is not None:
            by.setdefault(r["seed"], {}).setdefault(r["person"], []).append(r[metric])
    return [st.mean(st.mean(v) for v in ppl.values()) for ppl in by.values()]


def beats(res: dict, a: str, c: str, metric: str = "recall") -> dict:
    C = res["aggregate"]["conditions"]
    if a not in C or c not in C:
        return {"a": a, "c": c, "verdict": None, "why": "condition missing"}
    pa, pc = C[a]["per_person"], C[c]["per_person"]
    ppl = [p for p in pa if p in pc and pa[p][metric][0] is not None and pc[p][metric][0] is not None]
    d = {p: pa[p][metric][0] - pc[p][metric][0] for p in ppl}
    mean_d = st.mean(d.values()) if d else None
    rd = {p: d[p] for p in REACHABLE if p in d}
    wins = sum(v > 0 for v in rd.values())
    worst = min(rd.values()) if rd else None
    sa = seed_overall(res["runs"], a, metric)
    ma, sda = (st.mean(sa), st.stdev(sa) if len(sa) > 1 else 0.0) if sa else (None, None)
    mc = st.mean(seed_overall(res["runs"], c, metric) or [float("nan")])
    c1 = mean_d is not None and mean_d > 0
    c2 = wins >= MIN_WINS and worst is not None and worst >= -MAX_LOSS
    c3 = ma is not None and (ma - sda) > mc
    return {"a": a, "c": c, "metric": metric, "mean_diff": mean_d, "per_person_diff": d, "reachable_wins": wins,
            "worst_reachable_diff": worst, "a_seed_mean": ma, "a_seed_sd": sda, "c_mean": mc,
            "cond_mean_diff_gt_0": c1, "cond_wins_and_no_big_loss": c2, "cond_sd_clear_of_c_mean": c3,
            "verdict": bool(c1 and c2 and c3)}


def mean_metric(res, cond, metric):
    pp = res["aggregate"]["conditions"].get(cond, {}).get("per_person", {})
    xs = [v[metric][0] for v in pp.values() if v[metric][0] is not None]
    return st.mean(xs) if xs else None


def label(x):
    return None if x is None else ("SUPPORTED" if x else "NOT SUPPORTED")


def matched_n(res) -> int | None:
    xs = [r["logged_calls"] for r in res["runs"] if r["condition"] == B1 and r.get("logged_calls") is not None]
    return int(round(st.median(xs))) if xs else None


def main(out: Path) -> dict:
    res = json.loads((out / "results.json").read_text())
    diag = json.loads((out / "diagnose-runs.json").read_text())
    budget = max((r.get("budget") or 0) for r in res["runs"]) or 100
    h = {}
    m1, m2 = beats(res, B6, B1), beats(res, B6, B5F)
    h["H6"] = {"verdict": label(m1["verdict"] and m2["verdict"] if None not in (m1["verdict"], m2["verdict"]) else None), "vs_B1": m1, "vs_B5-fix": m2}
    p6, pf, p1 = (mean_metric(res, x, "precision") for x in (B6, B5F, B1))
    ok = None if None in (p6, pf, p1) else (p6 >= pf - PREC_TOL and p6 > p1)
    h["H6-prec"] = {"verdict": label(ok), "precision_B6": p6, "precision_B5-fix": pf, "precision_B1": p1, "tolerance": PREC_TOL}
    runs6 = [v for v in diag.values() if v["condition"] == B6]
    if runs6:
        calls = sum(v["calls"] for v in runs6)
        rep = sum(v["repeats_excl_retries"] for v in runs6) / calls if calls else 0.0
        rep_all = sum(v["exact_repeats"] for v in runs6) / calls if calls else 0.0
        used = st.mean(r["tool_calls"] for r in res["runs"] if r["condition"] == B6 and r.get("tool_calls") is not None) / budget
        h["H6-waste"] = {"verdict": label(rep < REPEAT_MAX and used >= USE_MIN), "exact_repeat_rate": rep,
                         "exact_repeat_rate_incl_retries": rep_all, "share_of_B_used": used}
    else:
        h["H6-waste"] = {"verdict": None, "why": "no B6-swarm tool logs"}
    a1, a2 = beats(res, B6, "B6-no-ledger"), beats(res, B6, "B6-no-parallel")
    h["H6-ablation"] = {"verdict": label(a1["verdict"] and a2["verdict"] if None not in (a1["verdict"], a2["verdict"]) else None),
                        "vs_B6-no-ledger": a1, "vs_B6-no-parallel": a2}
    n = matched_n(res)
    tf = out / "truncated" / f"n{n}" / "results.json"
    if n and tf.exists():
        tb = beats(json.loads(tf.read_text()), B6, B1)
        h["H6-budget"] = {"verdict": label(tb["verdict"]), "matched_calls": n, "vs_B1": tb}
    else:
        h["H6-budget"] = {"verdict": None, "matched_calls": n, "why": f"missing {tf}"}
    curves = {}
    for k in CURVE_N:
        f = out / "truncated" / f"n{k}" / "results.json"
        src = f if f.exists() else (out / "results.json" if k >= budget else None)
        if src:
            C = json.loads(src.read_text())["aggregate"]["conditions"]
            curves[k] = {c: v["overall_recall"] for c, v in C.items()}
    h["curves"] = curves
    h["note"] = "n = 6 people is too small for statistical significance; the verdicts use the preregistered rule above."
    (out / "h6.json").write_text(json.dumps(h, indent=1))
    for k in ("H6", "H6-prec", "H6-waste", "H6-ablation", "H6-budget"):
        print(f"{k}: {h[k]['verdict']}")
    return h


if __name__ == "__main__":
    main(Path(sys.argv[1]))
