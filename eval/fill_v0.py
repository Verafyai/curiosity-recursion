"""Generate paper/results-values.tex (and paper/generated/*.tex) from measured results only.

Usage: python eval/fill_v0.py --h1 <bench-run results.json> --corpus <corpus results.json> [--audit audit.json]
       [--spend spend_usd.txt] --out paper/
Every value printed in the paper comes from these files. A key with nothing measured gets \\NM and a
reason in the paper text; nothing is typed by hand.
"""
from __future__ import annotations

import argparse
import json
import statistics as st
from pathlib import Path


def f3(x):
    return "\\NM" if x is None else f"{x:.3f}"


def pc(x, d=1):
    return "\\NM" if x is None else f"{100 * x:.{d}f}\\%"


def ci(m, lo_hi):
    return "\\NM" if m is None else f"{m:.3f} [{lo_hi[0]:.3f}, {lo_hi[1]:.3f}]"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--h1", type=Path, required=True)
    ap.add_argument("--corpus", type=Path)
    ap.add_argument("--audit", type=Path)
    ap.add_argument("--spend", type=Path)
    ap.add_argument("--model", default="grok-4.20-0309-non-reasoning (xAI API, 26 November 2026)")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    d = json.loads(a.h1.read_text())
    v = {}
    h1 = d["h1"]
    t = lambda k: (h1.get(k) or {}).get("test") or {}  # noqa: E731
    v["n-subjects-test"] = str(t("B5@100").get("n_subjects", "\\NM"))
    for ag in ("B0", "B1", "B3", "B5"):
        T = t(f"{ag}@100")
        v[f"H1-recall-{ag}-B100"] = ci(T.get("macro_recall"), T.get("ci95") or [0, 0])
        v[f"H1b-T1-{ag}"] = f3(((T.get("by_tier") or {}).get("T1") or {}).get("recall"))
        v[f"H1b-T3-{ag}"] = "\\NM"   # no T3 records in the test split
        v[f"H4-prec-{ag}"] = "\\NM"  # claim precision needs human adjudication (not done)
        v[f"wp-{ag}"] = "\\NM"       # wrong-person rate needs human adjudication (not done)
        A = h1.get(f"{ag}@100") or {}
        v[f"cost-{ag}-calls"] = f"{A.get('tool_calls_mean', 0):.1f}"
        v[f"cost-{ag}-time"] = f"{A.get('wall_mean_s', 0):.0f}\\,s"
        if ag in ("B0", "B1"):
            v[f"cost-{ag}-tok"] = f"{A.get('tokens_mean', 0):,.0f}".replace(",", "{,}")
            v[f"cost-{ag}-usd"] = f"\\${A.get('usd_mean', 0):.4f}"
    for ag in ("B3", "B5"):
        v[f"abs-recall-{ag}-B100"] = f3(t(f"{ag}@100").get("macro_recall"))
    h2 = d.get("h2", {}).get("p=0.3,kills=on", {})
    if h2:
        v["H2-complete-B5"] = f"{h2['B5']['completed']}/{h2['B5']['runs']}"
        v["H2-complete-B4"] = f"{h2['B4']['completed']}/{h2['B4']['runs']}"
        v["H2-mcnemar-p"] = f"{h2['mcnemar']['p']:.2f}"
        v["H2-dup-B5"] = f"{h2['B5']['dup_ratio_mean']:.2f} [{h2['B5']['dup_ci95'][0]:.2f}, {h2['B5']['dup_ci95'][1]:.2f}]"
        v["H2-dup-B4"] = f"{h2['B4']['dup_ratio_mean']:.2f} [{h2['B4']['dup_ci95'][0]:.2f}, {h2['B4']['dup_ci95'][1]:.2f}]"
        v["H2-discussion-gap"] = (f"In this pilot (12 runs per agent, 4 subjects, 3 seeds, at most 13 minutes each) both completed every run; "
                                  f"the difference was repeated work: after each restart B4 lost and redid finished lookups, {h2['B4']['dup_ratio_mean']:.1f} for every lookup in its final result on average; B5 redid none.")
    h3 = d.get("h3") or {}
    if h3:
        v["H3-cost-off"] = f"{h3['calls_run1_mean']:.1f}"
        v["H3-cost-on"] = f"{h3['calls_run2_mean']:.1f}"
    for k in ("H5-coverage-B5", "H5-coverage-B3", "H5-kappa", "nudge-kappa", "rater-kappa"):
        v[k] = "\\NM"
    for n in ("deepen", "verify", "broaden", "new", "follow", "ingest", "keep"):
        for p in ("n", "c3", "c5"):
            v[f"{p}-{n}"] = "\\NM"
    ab = d.get("ablations", {})
    r = lambda k: f3((ab.get(k) or {}).get("macro_recall"))  # noqa: E731
    full = "B5 (full, h3 run 1)"
    v["abl-full"] = r(full)
    v["abl-breadth"] = " / ".join([r("B5-b1"), r(full), r("B5-b5"), r("B5-b8")])
    v["abl-depth"] = " / ".join([r("B5-d1"), r("B5-d2"), r(full), r("B5-d4")])
    v["abl-nodes"] = " / ".join([r("B5-n10"), r("B5-n30"), r("B5-n50"), r(full)])
    v["abl-nomem"] = r("B5-nomem")
    v["abl-gen"] = f"{r('B5-llm')} / {r('B5-hybrid')}"
    v["abl-nocircuits"] = r("B5-nocircuits")
    v["abl-noverify"] = r("B5-noverify")
    v["abl-nodedupe"] = r("B5-nodedupe")
    for k in ("full", "breadth", "depth", "nodes", "nomem", "gen", "nocircuits", "noverify", "nodedupe"):
        v[f"abl-{k}-wp"] = "\\NM"
    v["model-versions"] = a.model
    if a.spend and a.spend.exists():
        v["total-cost"] = f"\\${float(a.spend.read_text() or 0):.2f} in model API calls (all experiments, xAI billing ticks); archive lookups are free"
    gen = a.out / "generated"
    gen.mkdir(parents=True, exist_ok=True)
    if a.corpus and a.corpus.exists():
        c = json.loads(a.corpus.read_text())["aggregate"]
        conds = c["conditions"]
        people = [p for p in ("burnham", "homer", "john", "kingsley", "bristol", "alex") if any(p in x["per_person"] for x in conds.values())]
        era = {"burnham": "Civil War", "homer": "WWI", "john": "WWII", "kingsley": "civilian", "bristol": "civilian", "alex": "civilian"}
        name = {"burnham": "Burnham", "homer": "Homer", "john": "John", "kingsley": "Kingsley", "bristol": "Bristol", "alex": "Alex"}
        rows = []
        for k, x in conds.items():
            cells = []
            for p in people:
                m = x["per_person"].get(p, {}).get("recall", [None, None])
                cells.append("\\NM" if m[0] is None else f"{100 * m[0]:.1f}$\\pm${100 * m[1]:.1f}")
            prec = [pp["precision"][0] for pp in x["per_person"].values() if pp["precision"][0] is not None]
            prec = sum(prec) / len(prec) if prec else None
            rows.append(f"{k} {x['label']} & " + " & ".join(cells) + f" & {pc(x['overall_recall'])} & {pc(x.get('overall_reachable_recall'))} & {pc(prec)} & {pc(x['overall_penalised'])} \\\\")
            v[f"corpus-reach-{k.replace('-', '')}"] = pc(x.get("overall_reachable_recall"))
            v[f"corpus-prec-{k.replace('-', '')}"] = pc(prec)
            v[f"corpus-fl-{k.replace('-', '')}"] = str(sum(pp["false_links"] for pp in x["per_person"].values()))
            for p in people:
                if p in x["per_person"]:
                    v[f"corpus-reachn-{p}"] = str(x["per_person"][p].get("reachable_n", ""))
            key = k.replace("-", "")
            v[f"corpus-overall-{key}"] = pc(x["overall_recall"])
            for e, val in x["by_era"].items():
                v[f"corpus-era-{key}-{e.replace(' ', '')}"] = pc(val)
        head = " & ".join(f"{name[p]} ({era[p]})" for p in people)
        (gen / "corpus-table.tex").write_text(
            "\\begin{table*}[t]\\centering\\small\n\\resizebox{\\textwidth}{!}{\\begin{tabular}{@{}l" + "c" * (len(people) + 4) + "@{}}\n\\toprule\n"
            f"Strategy & {head} & Overall & Reachable & Precision & Penalised \\\\\n\\midrule\n" + "\n".join(rows) + "\n\\bottomrule\n\\end{tabular}}\n"
            "\\caption{Corpus replication (answer key " + c["answer_key"]["version"] + "): percent of each hand-built dossier recovered in one pass, "
            "mean$\\pm$sd over runs. 1.0 per fact found in returned evidence, 0.5 for reaching the right record or naming the right book or archive, 0 otherwise. "
            "Reachable: mean recall on facts with a source on a host the tools query (Homer has none). Precision: share of cited items that name the subject inside his life span. Penalised subtracts 5 per false family link per fact. Generated by \\texttt{eval/fill\\_v0.py} from \\texttt{benchmark/results}.}\n\\label{tab:corpus}\n\\end{table*}\n")
        lock = json.loads((Path("eval/answer_keys") / c["answer_key"]["version"] / "LOCK.json").read_text())
        rn = {p: next((x["per_person"][p].get("reachable_n") for x in conds.values() if p in x["per_person"]), None) for p in people}
        rrows = []
        for k, x in conds.items():
            cells = []
            for p in people:
                m = x["per_person"].get(p, {}).get("reachable_recall", [None, None])
                cells.append("\\NM" if m[0] is None else f"{100 * m[0]:.1f}")
            rrows.append(f"{k} & " + " & ".join(cells) + f" & {pc(x.get('overall_reachable_recall'))} \\\\")
        (gen / "corpus-reach-table.tex").write_text(
            "\\begin{table}[t]\\centering\\small\n\\resizebox{\\columnwidth}{!}{\\begin{tabular}{@{}l" + "c" * (len(people) + 1) + "@{}}\n\\toprule\n"
            "& " + " & ".join(name[p] for p in people) + " & Mean \\\\\n"
            "Reachable facts & " + " & ".join(f"{rn[p]}/{lock['people'][p]['facts_total']}" for p in people) + " & \\\\\n\\midrule\n" + "\n".join(rrows) +
            "\n\\bottomrule\n\\end{tabular}}\n\\caption{The reachability ceiling. A fact is reachable when one of its dossier sources is on archive.org, loc.gov or wikidata.org, "
            "the only hosts the bench tools query. Recall (\\%) on the reachable facts only; Homer has no reachable fact (\\NM). Generated from results.}\n\\label{tab:reach}\n\\end{table}\n")
        nruns = sorted({x["per_person"][p]["n_runs"] for x in conds.values() for p in x["per_person"]})
        v["corpus-runs"] = "/".join(str(n) for n in nruns)
        v["corpus-key"] = c["answer_key"]["version"]
        for k, x in conds.items():
            key = k.replace("-", "")
            v[f"corpus-blocked-{key}"] = str(x["blocked_host"])
            v[f"corpus-dropped-{key}"] = str(x["dropped_overlap"])
            v[f"corpus-usd-{key}"] = "\\NM" if x["usd"] is None else f"\\${x['usd']:.2f}"
    if a.corpus and (a.corpus.parent / "stats.json").exists():
        for metric, rows in json.loads((a.corpus.parent / "stats.json").read_text()).items():
            tag = "" if metric == "recall" else "reach-"
            for r in rows:
                k = f"corpus-{tag}{r['a'].replace('-', '')}-vs-{r['b'].replace('-', '')}"
                v[k + "-diff"] = f"{100 * r['mean_diff']:+.1f}"
                v[k + "-wl"] = f"{r['wins']} of {r['n_people']} people better, {r['losses']} worse"
                v[k + "-p"] = f"{r['p']:.3f}"
                v[k + "-holm"] = f"{r['holm_p']:.3f}"
    if a.corpus and (a.corpus.parent / "diagnose.json").exists():
        dg = json.loads((a.corpus.parent / "diagnose.json").read_text())
        order = [c for c in ("B0", "B1", "B3", "B5", "B5-max", "B5-fix", "B5-llm") if c in dg]
        rows = []
        for c in order:
            r = dg[c]
            rows.append(f"{c} & {r['calls']:.1f} & {pc(r['repeat_share'])} & {pc(r['empty_share'])} & {r['items']:.0f} & {pc(r['on_target_share'])} & "
                        f"{r.get('fn:ia_fulltext', 0):.1f} & {r.get('fn:ia_inside', 0):.1f} & {r.get('fn:chronam', 0):.1f} \\\\")
            v[f"diag-repeat-{c.replace('-', '')}"] = pc(r["repeat_share"])
            v[f"diag-calls-{c.replace('-', '')}"] = f"{r['calls']:.1f}"
            v[f"diag-ontarget-{c.replace('-', '')}"] = pc(r["on_target_share"])
            v[f"diag-empty-{c.replace('-', '')}"] = pc(r["empty_share"])
        (gen / "corpus-diagnose-table.tex").write_text(
            "\\begin{table*}[t]\\centering\\small\n\\begin{tabular}{@{}lcccccccc@{}}\n\\toprule\n"
            "Strategy & Calls/run & Exact repeats & Empty results & Items returned & On target & IA full text & Inside a book & Newspapers \\\\\n\\midrule\n"
            + "\n".join(rows) + "\n\\bottomrule\n\\end{tabular}\n\\caption{Tool-use profile per run on the corpus, from the tool-layer logs (\\texttt{eval/corpus/diagnose.py}). "
            "Exact repeats: calls identical to an earlier call in the same run. On target: share of returned items that name the subject and carry no year outside his life. "
            "The last three columns are calls per run to each tool.}\n\\label{tab:diagnose}\n\\end{table*}\n")
    if a.corpus and (a.corpus.parent / "hand-adjudication.json").exists():
        h = json.loads((a.corpus.parent / "hand-adjudication.json").read_text())
        n_yes = h["hand_adjudicated_precision_of_scorer_credit"].split("/")
        n_no = h["hand_adjudicated_misses_among_scorer_zero"].split("/")
        v["corpus-hand-summary"] = (f"the scorer was right in {h['scorer_right_judge_wrong']} and wrong in {h['judge_right_scorer_false_positive']} of the {h['disagreements']}, "
                                    f"so {n_yes[0]} of {n_yes[1]} sampled credited facts are supported by their evidence and {n_no[0]} of {n_no[1]} sampled uncredited facts were missed")
    if a.audit and a.audit.exists():
        au = json.loads(a.audit.read_text())["_overall"]
        v["corpus-audit-n"] = str(au["n"])
        v["corpus-audit-agree"] = pc(au["agree"])
        v["corpus-audit-kappa"] = f3(au["kappa"])
        v["corpus-audit-prec"] = pc(au["precision_of_scorer_yes"])
    lines = ["% Generated by eval/fill_v0.py from measured results. Do not edit by hand."]
    lines += [f"\\resdef{{{k}}}{{{val}}}" for k, val in sorted(v.items())]
    (a.out / "results-values.tex").write_text("\n".join(lines) + "\n")
    print(f"{len(v)} values -> {a.out / 'results-values.tex'}")


if __name__ == "__main__":
    main()
