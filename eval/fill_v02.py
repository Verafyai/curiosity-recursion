"""Generate paper/results-values-v02.tex and paper/generated/v02-*.tex from a v0.2 corpus-bench result set.

Usage: python eval/fill_v02.py --run <dir with results.json, stats.json, diagnose.json, h6.json, truncated/> --out paper/
Every v0.2 number in the paper comes from these files; nothing is typed by hand. A missing value stays
a \\RESULT{} TBD box.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

CONDS = ["B6-swarm", "B6-no-ledger", "B6-no-parallel", "B5-fix", "B5", "B1"]
PEOPLE = ["burnham", "homer", "john", "kingsley", "bristol", "alex"]
NAME = {"burnham": "Burnham", "homer": "Homer", "john": "John", "kingsley": "Kingsley", "bristol": "Bristol", "alex": "Alex"}
HYP = [("H6", "B6-swarm beats B1 and B5-fix on overall recall"), ("H6-prec", "precision within 3 points of B5-fix and above B1"),
       ("H6-waste", "exact-repeat rate below 2\\% and at least 80\\% of B used"),
       ("H6-ablation", "B6-swarm beats B6-no-ledger and B6-no-parallel"), ("H6-budget", "B6-swarm beats B1 at the matched call count")]


def pc(x, d=1):
    return None if x is None else f"{100 * x:.{d}f}\\%"


def pts(x):
    return None if x is None else f"{100 * x:+.1f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    R = json.loads((a.run / "results.json").read_text())
    C = R["aggregate"]["conditions"]
    S = json.loads((a.run / "stats.json").read_text()) if (a.run / "stats.json").exists() else {}
    D = json.loads((a.run / "diagnose.json").read_text()) if (a.run / "diagnose.json").exists() else {}
    H = json.loads((a.run / "h6.json").read_text()) if (a.run / "h6.json").exists() else {}
    meta = json.loads((a.run / "meta.json").read_text()) if (a.run / "meta.json").exists() else {}
    v: dict[str, str | None] = {}
    conds = [c for c in CONDS if c in C]
    runs_per = max((C[c]["per_person"][p]["n_runs"] for c in conds for p in C[c]["per_person"]), default=None)
    v["v02-runs"] = None if runs_per is None else str(runs_per)
    v["v02-commit"] = meta.get("commit")
    for c in conds:
        x = C[c]
        prec = [pp["precision"][0] for pp in x["per_person"].values() if pp["precision"][0] is not None]
        calls = [pp["tool_calls"][0] for pp in x["per_person"].values() if pp["tool_calls"][0] is not None]
        v[f"v02-overall-{c}"] = pc(x["overall_recall"])
        v[f"v02-reach-{c}"] = pc(x.get("overall_reachable_recall"))
        v[f"v02-prec-{c}"] = pc(sum(prec) / len(prec) if prec else None)
        v[f"v02-calls-{c}"] = f"{sum(calls) / len(calls):.1f}" if calls else None
        v[f"v02-usd-{c}"] = None if x["usd"] is None else f"\\${x['usd']:.2f}"
        v[f"v02-tokens-{c}"] = f"{x.get('llm_tokens', 0):,}".replace(",", "{,}")
        d = D.get(c, {})
        v[f"v02-repeat-{c}"] = pc(d.get("repeat_share_excl_retries"))
        v[f"v02-repeatall-{c}"] = pc(d.get("repeat_share"))
        v[f"v02-empty-{c}"] = pc(d.get("empty_share"))
        v[f"v02-wd429-{c}"] = None if "wikidata_429_total" not in d else str(d["wikidata_429_total"])
        v[f"v02-429-{c}"] = None if "http429_total" not in d else str(d["http429_total"])
    v["v02-usd-total"] = f"\\${sum((C[c]['usd'] or 0) for c in conds):.2f}"
    for row in S.get("recall", []):
        if row["a"].startswith("B6") or (row["a"], row["b"]) == ("B5-fix", "B1"):
            k = f"v02-{row['a']}-vs-{row['b']}"
            v[k + "-diff"], v[k + "-wl"] = pts(row["mean_diff"]), f"{row['wins']} wins, {row['losses']} losses"
            v[k + "-p"], v[k + "-holm"] = f"{row['p']:.3f}", f"{row['holm_p']:.3f}"
    for k, _ in HYP:
        v[f"v02-{k}"] = (H.get(k) or {}).get("verdict")
    hb = H.get("H6-budget") or {}
    v["v02-matchedN"] = None if hb.get("matched_calls") is None else str(hb["matched_calls"])
    if hb.get("matched_calls"):
        tf = a.run / "truncated" / f"n{hb['matched_calls']}" / "results.json"
        if tf.exists():
            TC = json.loads(tf.read_text())["aggregate"]["conditions"]
            for c in conds:
                if c in TC:
                    v[f"v02-matched-overall-{c}"] = pc(TC[c]["overall_recall"])
    hw = H.get("H6-waste") or {}
    v["v02-waste-repeat"] = pc(hw.get("exact_repeat_rate"), 2)
    v["v02-waste-used"] = pc(hw.get("share_of_B_used"))
    gen = a.out / "generated"
    gen.mkdir(parents=True, exist_ok=True)
    # main table
    L = ["\\begin{table*}[t]\\centering\\small", "\\resizebox{\\textwidth}{!}{\\begin{tabular}{@{}l" + "c" * (len(PEOPLE) + 6) + "@{}}", "\\toprule",
         "Strategy & " + " & ".join(NAME[p] for p in PEOPLE) + " & Overall & Reachable & Precision & Calls & Repeats & Spend \\\\", "\\midrule"]
    for c in conds:
        x = C[c]
        cells = []
        for p in PEOPLE:
            m = x["per_person"].get(p, {}).get("recall")
            cells.append("\\NM" if not m or m[0] is None else f"{100 * m[0]:.1f}$\\pm${100 * m[1]:.1f}")
        L.append(f"{c} & " + " & ".join(cells) + " & " + " & ".join(v.get(f"v02-{k}-{c}") or "\\NM" for k in ("overall", "reach", "prec", "calls", "repeat", "usd")) + " \\\\")
    L += ["\\bottomrule", "\\end{tabular}}",
          "\\caption{v0.2 corpus replication at $B=100$ (answer key v1, scorer v1.1), percent of each dossier recovered, mean$\\pm$sd over runs. "
          "All strategies were rerun in the same batch from the same commit with the same tools (B1 also has \\texttt{ia\\_fts}). Repeats: share of logged "
          "calls that repeat an earlier successful call with the same arguments (retries of failed calls excluded). Spend: model dollars over all runs. "
          "Generated by \\texttt{eval/fill\\_v02.py}.}", "\\label{tab:v02}", "\\end{table*}"]
    (gen / "v02-table.tex").write_text("\n".join(L) + "\n")
    # hypotheses table
    L = ["\\begin{table}[t]\\centering\\small", "\\begin{tabular}{@{}p{0.17\\linewidth}p{0.5\\linewidth}l@{}}", "\\toprule", "Hypothesis & Preregistered test & Verdict \\\\", "\\midrule"]
    for k, desc in HYP:
        L.append(f"{k} & {desc} & {v.get('v02-' + k) or chr(92) + 'NM'} \\\\")
    L += ["\\bottomrule", "\\end{tabular}",
          "\\caption{Preregistered v0.2 hypotheses (\\texttt{bench/PREREGISTRATION-v0.2.md}) and verdicts under the preregistered decision rule, computed by "
          "\\texttt{eval/corpus/h6.py}. With six people no difference can be statistically significant.}", "\\label{tab:h6}", "\\end{table}"]
    (gen / "v02-h6-table.tex").write_text("\n".join(L) + "\n")
    # diagnose table
    L = ["\\begin{table}[t]\\centering\\small", "\\begin{tabular}{@{}lcccc@{}}", "\\toprule", "Strategy & Repeats & Repeats incl.\\ retries & Empty & Wikidata 429s \\\\", "\\midrule"]
    for c in conds:
        L.append(f"{c} & " + " & ".join(v.get(f"v02-{k}-{c}") or "\\NM" for k in ("repeat", "repeatall", "empty", "wd429")) + " \\\\")
    L += ["\\bottomrule", "\\end{tabular}", "\\caption{v0.2 tool-use profile from the tool logs (\\texttt{eval/corpus/diagnose.py}).}", "\\label{tab:v02diag}", "\\end{table}"]
    (gen / "v02-diagnose-table.tex").write_text("\n".join(L) + "\n")
    lines = ["% Generated by eval/fill_v02.py from measured v0.2 results. Do not edit by hand."]
    lines += [f"\\resdef{{{k}}}{{{val}}}" for k, val in sorted(v.items()) if val is not None]
    (a.out / "results-values-v02.tex").write_text("\n".join(lines) + "\n")
    print(f"wrote {len(lines) - 1} values and 3 tables")


if __name__ == "__main__":
    main()
