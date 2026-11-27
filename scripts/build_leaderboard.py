"""Build the static leaderboard (benchmark/index.html and benchmark/BENCHMARK.md) from
benchmark/results/<key>/<stamp>/results.json. The newest result set per answer-key version is shown;
older sets stay listed as history. Aggregates only: no dossier facts are published here."""
from __future__ import annotations

import html
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
B = ROOT / "benchmark"
ERA = {"burnham": "Civil War", "homer": "WWI", "john": "WWII", "kingsley": "civilian", "bristol": "civilian", "alex": "civilian"}
NAME = {"burnham": "Erastus Burnham", "homer": "Homer St. John", "john": "John St. John", "kingsley": "Kingsley Perry",
        "bristol": "Edgar H. Bristol", "alex": "Alex St. John"}


def pct(x):
    return "n.m." if x is None else f"{100 * x:.1f}%"


def pm(m):
    return "n.m." if not m or m[0] is None else f"{100 * m[0]:.1f} ± {100 * m[1]:.1f}"


def load_sets():
    sets = []
    for f in sorted((B / "results").glob("*/*/results.json")):
        d = json.loads(f.read_text())
        meta = json.loads((f.parent / "meta.json").read_text()) if (f.parent / "meta.json").exists() else {}
        audit = json.loads((f.parent / "audit.json").read_text()) if (f.parent / "audit.json").exists() else None
        sets.append({"path": f.parent, "key": f.parent.parent.name, "stamp": f.parent.name, "agg": d["aggregate"], "meta": meta, "audit": audit})
    return sets


def tables(s):
    c = s["agg"]["conditions"]
    people = [p for p in ERA if any(p in x["per_person"] for x in c.values())]
    eras = [e for e in ("Civil War", "WWI", "WWII", "civilian") if any(ERA[p] == e for p in people)]
    order = sorted(c, key=lambda k: -(c[k]["overall_recall"] or 0))
    main = [["Rank", "Strategy"] + [f"{NAME[p]} ({ERA[p]})" for p in people] + ["Overall", "Reachable only", "Precision", "Penalised", "Spend"]]
    for i, k in enumerate(order, 1):
        x = c[k]
        pr = [pp["precision"][0] for pp in x["per_person"].values() if pp["precision"][0] is not None]
        main.append([str(i), f"{k}: {x['label']}"] + [pm(x["per_person"].get(p, {}).get("recall")) for p in people] +
                    [pct(x["overall_recall"]), pct(x.get("overall_reachable_recall")), pct(sum(pr) / len(pr) if pr else None), pct(x["overall_penalised"]), "n.m." if x["usd"] is None else f"${x['usd']:.2f}"])
    reach = [["Strategy"] + [f"{NAME[p]} ({next((x['per_person'][p].get('reachable_n') for x in c.values() if p in x['per_person']), 0)} reachable)" for p in people] + ["Mean (reachable)"]]
    for k in order:
        x = c[k]
        reach.append([k] + [pm(x["per_person"][p]["reachable_recall"]) if p in x["per_person"] and x["per_person"][p].get("reachable_recall", [None])[0] is not None else "n.m." for p in people] +
                     [pct(x.get("overall_reachable_recall"))])
    era = [["Strategy"] + eras] + [[k] + [pct(c[k]["by_era"].get(e)) for e in eras] for k in order]
    tiers = ("web_open", "book", "web_gated", "outreach")

    def tmean(x, t):
        v = [pp["by_tier"][t][0] for pp in x["per_person"].values() if pp["by_tier"][t][0] is not None]
        return sum(v) / len(v) if v else None
    tier = [["Strategy"] + list(tiers)] + [[k] + [pct(tmean(c[k], t)) for t in tiers] for k in order]

    def m(x, key):
        v = [pp[key][0] for pp in x["per_person"].values() if pp[key][0] is not None]
        return sum(v) / len(v) if v else None
    other = [["Strategy", "Full-credit recall", "Holdout recall", "Source recall", "Precision", "Novel candidates / run", "False links", "Tool calls / run"]]
    for k in order:
        x = c[k]
        nc, tc = m(x, "novel_candidates"), m(x, "tool_calls")
        other.append([k, pct(m(x, "full_credit_recall")), pct(m(x, "holdout_recall")), pct(m(x, "source_recall")), pct(m(x, "precision")),
                      "n.m." if nc is None else f"{nc:.1f}", str(sum(pp["false_links"] for pp in x["per_person"].values())),
                      "n.m." if tc is None else f"{tc:.1f}"])
    leak = [["Strategy", "Runs", "Blocked by host rule", "Dropped by dossier-overlap guard", "Runs without a tool log"]] + \
           [[k, str(c[k]["runs"]), str(c[k]["blocked_host"]), str(c[k]["dropped_overlap"]), str(c[k]["runs_missing_tool_log"])] for k in order]
    return main, era, tier, other, leak, reach


def md_table(t):
    return "\n".join(["| " + " | ".join(t[0]) + " |", "|" + "---|" * len(t[0])] + ["| " + " | ".join(r) + " |" for r in t[1:]])


def html_table(t):
    h = "".join(f"<th>{html.escape(x)}</th>" for x in t[0])
    rows = "".join("<tr>" + "".join(f"<td>{html.escape(x)}</td>" for x in r) + "</tr>" for r in t[1:])
    return f"<table><thead><tr>{h}</tr></thead><tbody>{rows}</tbody></table>"


REPO = "https://github.com/Verafyai/curiosity-recursion"
PAGES = "https://verafyai.github.io/curiosity-recursion"


def version():
    v = ROOT / "VERSION"
    return v.read_text().strip() if v.exists() else "0.0.0"


def explain(cur):
    c = cur["agg"]["conditions"]
    meta = cur["meta"]
    return [
        "Six people from the author's own family research, each with a hand-built dossier: a Civil War soldier (Erastus W. Burnham), "
        "a World War I veteran (Homer D. St. John), a World War II veteran (John St. John) and three civilians (Kingsley A. Perry, "
        "Edgar H. Bristol, Alex St. John). Everyone is deceased.",
        "Each dossier was split into atomic facts (birth, service, work, family, places, sources) and frozen as a hash-locked answer key. "
        "Every fact is tagged with how its source can be reached: open web, gated site, book, or outreach to an archive or family.",
        "Each strategy gets only the person's name and birth year, the same public tools (Internet Archive, Chronicling America, Wikidata) "
        f"and the same budget ({meta.get('budget', 'n/a')} tool calls), and runs {meta.get('runs_per_cell', 'n/a')} times per person.",
        "Score: 1.0 for each dossier fact found in the evidence the tools returned, 0.5 for reaching the right record or naming the right "
        "book or archive, 0 otherwise. 100% means the whole dossier was recovered in one pass.",
        "Exclusion filter: the author's own websites, repositories, deployments and accounts, and archive snapshots of them, are blocked at "
        "the tool layer, and any returned page that copies dossier prose is dropped, so no strategy can copy the finished research back.",
        "Reachability ceiling: many dossier facts come from books, gated archives and family outreach that these tools cannot reach. "
        "The table also scores each strategy on the reachable facts only (a source on archive.org, loc.gov or wikidata.org).",
    ]


def main():
    sets = load_sets()
    if not sets:
        print("no results under benchmark/results", file=sys.stderr)
        return 1
    cur = max(sets, key=lambda s: (s["key"], s["stamp"]))
    main_t, era_t, tier_t, other_t, leak_t, reach_t = tables(cur)
    ak = cur["agg"]["answer_key"]
    (B / "assets").mkdir(exist_ok=True)
    chart = cur["path"] / "corpus-recall.png"
    if chart.exists():
        shutil.copy(chart, B / "assets" / "corpus-recall.png")
    for f in ("snapshot.svg", "snapshot.png"):
        if (cur["path"] / f).exists():
            shutil.copy(cur["path"] / f, B / "assets" / f)
    au = (cur["audit"] or {}).get("_overall")
    hand = json.loads((cur["path"] / "hand-adjudication.json").read_text()) if (cur["path"] / "hand-adjudication.json").exists() else None
    audit_line = (f"Scorer audit: {au['n']} sampled decisions (half credited, half not) were judged by an independent model at temperature 0: "
                  f"{pct(au['agree'])} agreement, Cohen's kappa {au['kappa']:.2f}; {pct(au['precision_of_scorer_yes'])} of the scorer's credited facts were confirmed."
                  if au else "Scorer audit: not run for this result set.")
    if hand:
        audit_line += (f" Every disagreement ({hand['disagreements']}) was then read one by one by an AI assistant (not a human rater) against the matched text: the scorer was right in "
                       f"{hand['scorer_right_judge_wrong']} and wrong in {hand['judge_right_scorer_false_positive']}, so hand-adjudicated precision of credited facts is "
                       f"{hand['hand_adjudicated_precision_of_scorer_credit']} and no missed facts were found among {hand['hand_adjudicated_misses_among_scorer_zero'].split('/')[1]} zeros.")
    stats = json.loads((cur["path"] / "stats.json").read_text()) if (cur["path"] / "stats.json").exists() else None
    stat_t = None
    if stats:
        stat_t = [["Comparison", "People", "Mean difference (points)", "Better / worse", "p (exact sign-flip)", "Holm p"]] + \
                 [[f"{r['a']} vs {r['b']}", str(r["n_people"]), f"{100 * r['mean_diff']:+.1f}", f"{r['wins']} / {r['losses']}", f"{r['p']:.3f}", f"{r['holm_p']:.3f}"] for r in stats["recall"]]
    meta = cur["meta"]
    ver = version()
    intro = (f"Answer key **{ak['version']}** (frozen {ak['frozen']}), result set `{cur['stamp']}`, code commit `{meta.get('commit', 'n/a')}`, "
             f"{meta.get('runs_per_cell', 'n/a')} runs per strategy per person, budget {meta.get('budget', 'n/a')} tool calls. "
             "Mean ± sd over runs, in percent. Spec: [eval/EVAL-SPEC.md](../eval/EVAL-SPEC.md).")
    hist = [["Answer key", "Result set", "Best strategy", "Best overall"]]
    for s_ in sorted(sets, key=lambda s: (s["key"], s["stamp"]), reverse=True):
        c = s_["agg"]["conditions"]
        best = max(c, key=lambda k: c[k]["overall_recall"] or 0)
        hist.append([s_["key"], s_["stamp"], best, pct(c[best]["overall_recall"])])
    ex = explain(cur)
    md = ["# Curiosity Recursion benchmark", "", f"Version v{ver}. [Click to read the research paper]({PAGES}/paper/main.pdf) "
          f"([PDF in the repo](../paper/main.pdf)). Web page: {PAGES}/benchmark/", "",
          "![Benchmark snapshot](assets/snapshot.png)", "", "## What the benchmark measures", ""] + [f"- {x}" for x in ex] + [
          "", intro, "", "## Leaderboard", "", md_table(main_t), "", "## Reachability ceiling", "",
          "Recall on the facts the tools could reach at all. Homer has none, so his column is not measured.", "", md_table(reach_t), "",
          "![recall per person](assets/corpus-recall.png)", "", "## By era", "", md_table(era_t), "", "## By access tier", "", md_table(tier_t), "",
          "## Other measures", "", md_table(other_t), ""]
    if stat_t:
        md += ["## Is any difference real?", "", "Paired over the six people. With six people the smallest possible p is 0.031, so read these as direction, not proof.", "", md_table(stat_t), ""]
    md += ["## Leakage audit", "",
           "Every strategy ran with the exclusion filter on: the dossier author's own sites, repositories, deployments and accounts are blocked "
           "at the tool layer, and any returned page that copies dossier prose is dropped. Counts per strategy:", "", md_table(leak_t), "",
           "## Scorer audit", "", audit_line, "", "## Answer key hashes", "",
           "\n".join(f"- `{p}`: `{h}`" for p, h in ak["sha256_public"].items()), "", "## History", "", md_table(hist), ""]
    (B / "BENCHMARK.md").write_text("\n".join(md))
    css = ("*{box-sizing:border-box}body{margin:0;font:16px/1.55 Inter,-apple-system,'Segoe UI',Helvetica,Arial,sans-serif;background:#14110e;color:#f6f0e8}"
           ".wrap{max-width:1180px;margin:0 auto;padding:0 24px 64px}header{padding:28px 0 8px}header img{width:100%;border-radius:14px;border:1px solid #3a3128}"
           ".badges{display:flex;gap:8px;flex-wrap:wrap;margin:16px 0}.badge{font-size:13px;padding:3px 10px;border-radius:999px;border:1px solid #3a3128;color:#d2c4b2;background:#1c1814}"
           ".badge b{color:#e08a66}.cta{display:inline-block;margin:6px 12px 6px 0;padding:12px 20px;border-radius:10px;background:#e08a66;color:#14110e;font-weight:700;text-decoration:none}"
           ".cta.alt{background:transparent;color:#e08a66;border:1px solid #e08a66}h1,h2{font-family:Georgia,'IBM Plex Serif',serif;font-weight:600}h2{margin-top:44px;border-bottom:1px solid #3a3128;padding-bottom:6px}"
           "a{color:#e08a66}p,li{color:#d2c4b2}table{border-collapse:collapse;width:100%;margin:10px 0 18px;font-size:13.5px}th,td{border:1px solid #3a3128;padding:6px 8px;text-align:left}"
           "th{background:#1c1814;color:#f6f0e8}td{color:#e9dfd2}tr:nth-child(even) td{background:#191510}img.full{width:100%;border-radius:12px;border:1px solid #3a3128;background:#fff}"
           "img.snap{width:100%;border-radius:12px;border:1px solid #3a3128}code{background:#1c1814;padding:0 4px;border-radius:4px}.scroll{overflow-x:auto}footer{margin-top:48px;color:#a89886;font-size:13px}")
    T = lambda t: f"<div class='scroll'>{html_table(t)}</div>"  # noqa: E731
    body = [f"<header><img src='../docs/images/banner.svg' alt='Curiosity Recursion by Lineage'></header>",
            f"<div class='badges'><span class='badge'>version <b>v{html.escape(ver)}</b></span><span class='badge'>Temporal <b>Python SDK</b></span>"
            f"<span class='badge'>answer key <b>{html.escape(ak['version'])}</b></span><span class='badge'>result set <b>{html.escape(cur['stamp'])}</b></span></div>",
            f"<p><a class='cta' href='../paper/main.pdf'>Click to read the research paper</a><a class='cta alt' href='{REPO}'>Code on GitHub</a>"
            f"<a class='cta alt' href='{REPO}/releases/tag/v{html.escape(ver)}'>Release v{html.escape(ver)}</a></p>",
            "<p>Curiosity Recursion is a durable research agent for genealogy: every finding sparks the next grounded question, every question is remembered, "
            "and Temporal keeps the run alive through crashes, flaky archives and replies that take weeks.</p>",
            "<h2>Benchmark</h2><img class='snap' src='assets/snapshot.png' alt='Benchmark snapshot'>",
            "<h2>What the benchmark measures</h2><ul>" + "".join(f"<li>{html.escape(x)}</li>" for x in ex) + "</ul>",
            f"<p>{html.escape(intro).replace('**', '').replace('[eval/EVAL-SPEC.md](../eval/EVAL-SPEC.md)', '')}<a href='{REPO}/blob/master/eval/EVAL-SPEC.md'>eval/EVAL-SPEC.md</a></p>",
            f"<h2>Leaderboard</h2>{T(main_t)}<h2>Reachability ceiling</h2><p>Recall on the facts the tools could reach at all. Homer has none, so his column is not measured.</p>{T(reach_t)}",
            f"<img class='full' src='assets/corpus-recall.png' alt='recall per person'><h2>By era</h2>{T(era_t)}<h2>By access tier</h2>{T(tier_t)}<h2>Other measures</h2>{T(other_t)}"]
    if stat_t:
        body.append(f"<h2>Is any difference real?</h2><p>Paired over the six people. With six people the smallest possible p is 0.031, so read these as direction, not proof.</p>{T(stat_t)}")
    body += [f"<h2>Leakage audit</h2><p>Exclusion filter on for every strategy: the author's own sites, repositories, deployments and accounts are blocked, and pages copying dossier prose are dropped.</p>{T(leak_t)}",
             f"<h2>Scorer audit</h2><p>{html.escape(audit_line)}</p><h2>Answer key hashes</h2><ul>" +
             "".join(f"<li><code>{p}</code>: <code>{h}</code></li>" for p, h in ak["sha256_public"].items()) + f"</ul><h2>History</h2>{T(hist)}",
             f"<footer>Generated by <code>scripts/build_leaderboard.py</code> from <code>benchmark/results</code>. Every number on this page is read from the result files. "
             f"<a href='{REPO}'>{REPO}</a></footer>"]
    (B / "index.html").write_text(f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
                                  f"<title>Curiosity Recursion by Lineage: benchmark v{html.escape(ver)}</title><style>{css}</style></head><body><div class='wrap'>{''.join(body)}</div></body></html>")
    print(f"leaderboard from {cur['path']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
