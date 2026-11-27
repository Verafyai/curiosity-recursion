"""Every data figure in the paper, from logged files only.

    python eval/plots.py graph --db PATH/studio.db --run WORKFLOW_ID --out paper/figures/fig4-graph.pdf
    python eval/plots.py results results/<name>.scores.jsonl --out paper/figures/

`graph` redraws a real question graph (Figure 4). `results` draws Figures 5 to 8 (recall versus
budget with 95% CI bands, recall by darkness tier, completion under faults, lead-chain depth to
hit) and refuses to draw a figure whose data are missing: the paper shows a TBD box instead.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from eval.stats import bootstrap_ci  # noqa: E402

STATUS = {  # print-safe greys plus one accent; the state is also written on the node
    "answered": ("#2e7d4f", "answered"), "no_lead": ("#9a9a9a", "no lead"), "stub": ("#7a6a8f", "stub"),
    "error": ("#b23b3b", "failed"), "skipped": ("#cccccc", "skipped"), "pending": ("#cccccc", "pending"),
}
plt.rcParams.update({"font.family": "serif", "font.size": 8, "pdf.fonttype": 42})


def graph(db: Path, run: str, out: Path, highlight: tuple[str, ...]):
    con = sqlite3.connect(db)
    rows = con.execute("select json from questions where workflow_id=?", (run,)).fetchall()
    qs = [json.loads(r[0]) for r in rows]
    if not qs:
        sys.exit(f"no questions stored for {run}")
    kids = defaultdict(list)
    for q in qs:
        kids[q.get("parent_id") or "root"].append(q["id"])
    by = {q["id"]: q for q in qs}
    pos, row = {}, [0]

    def place(i, d):
        ch = sorted(kids.get(i, []), key=lambda x: [int(t) if t.isdigit() else t for t in x.replace("you", "y.").split(".")])
        if not ch:
            pos[i] = (d * COL, row[0]); row[0] += 1
            return pos[i][1]
        ys = [place(c, d + 1) for c in ch]
        pos[i] = (d * COL, (min(ys) + max(ys)) / 2)
        return pos[i][1]
    COL, BOX = 1.9, 1.55  # column spacing and approximate box width, in data units
    place("root", 0)
    h = max(3.0, row[0] * 0.24)
    fig, ax = plt.subplots(figsize=(7.0, h))
    for i, (x, y) in pos.items():
        if i == "root":
            continue
        pid = by[i].get("parent_id") or "root"
        px, py = pos[pid]
        px = px + (0.5 if pid == "root" else BOX)
        hl = i in highlight and (by[i].get("parent_id") in highlight or by[i].get("parent_id") == "root")
        mid = (px + x) / 2
        ax.plot([px, mid, mid, x - 0.03], [py, py, y, y], color="#d4733f" if hl else "#bbbbbb",
                lw=1.6 if hl else 0.7, zorder=1)
    for i, (x, y) in pos.items():
        if i == "root":
            ax.text(x, y, "Erastus W. Burnham\n1834 to 1921", ha="center", va="center", fontsize=7, weight="bold",
                    bbox=dict(boxstyle="round,pad=0.3", fc="#fbe9df", ec="#d4733f", lw=1.2), zorder=3)
            continue
        q = by[i]
        col, word = STATUS.get(q["status"], ("#999999", q["status"]))
        label = f"{i}  {q['text'][:44]}{'...' if len(q['text']) > 44 else ''}"
        ax.text(x, y, f"{label}\n{word}", ha="left", va="center", fontsize=4.4, zorder=3,
                bbox=dict(boxstyle="round,pad=0.25", fc="white", ec=col, lw=1.6 if i in highlight else 0.8,
                          ls="--" if q["status"] == "stub" else "-"))
    ax.set_xlim(-0.7, max(x for x, _ in pos.values()) + BOX + 0.1)
    ax.set_ylim(row[0] - 0.4, -0.6)
    ax.axis("off")
    fig.tight_layout()
    fig.savefig(out)
    print(f"wrote {out}: {len(qs)} nodes")


def results(scores: Path, outdir: Path):
    rows = [json.loads(l) for l in scores.read_text().splitlines() if l.strip()]
    rows = [r for r in rows if r.get("verified_recall") is not None]
    if not rows:
        sys.exit("no adjudicated scores: the paper keeps its TBD boxes. Score with --labels first.")
    outdir.mkdir(parents=True, exist_ok=True)
    # Figure 5: recall versus budget, mean and 95% bootstrap CI per agent
    fig, ax = plt.subplots(figsize=(3.3, 2.4))
    for agent in sorted({r["agent"] for r in rows}):
        bs = sorted({r["budget"] for r in rows if r["agent"] == agent})
        m, lo, hi = zip(*[bootstrap_ci([r["verified_recall"] for r in rows if r["agent"] == agent and r["budget"] == b]) for b in bs])
        ax.plot(bs, m, marker="o", ms=3, label=agent)
        ax.fill_between(bs, lo, hi, alpha=0.15)
    ax.set_xscale("log", base=2); ax.set_xlabel("budget B (tool calls)"); ax.set_ylabel("hidden-record recall@B"); ax.legend(frameon=False)
    fig.tight_layout(); fig.savefig(outdir / "fig5-recall-budget.pdf")
    # Figure 6: recall by darkness tier at the largest common budget
    b = max(r["budget"] for r in rows)
    fig, ax = plt.subplots(figsize=(3.3, 2.4))
    agents = sorted({r["agent"] for r in rows})
    for k, agent in enumerate(agents):
        vals = []
        for t in ("T0", "T1", "T2", "T3"):
            hits = sum(r["by_tier"].get(t, {}).get("hits", 0) for r in rows if r["agent"] == agent and r["budget"] == b)
            n = sum(r["by_tier"].get(t, {}).get("n", 0) for r in rows if r["agent"] == agent and r["budget"] == b)
            vals.append(hits / n if n else 0)
        ax.bar([i + k * 0.8 / len(agents) for i in range(4)], vals, width=0.8 / len(agents), label=agent)
    ax.set_xticks(range(4), ["T0", "T1", "T2", "T3"]); ax.set_ylabel(f"recall@{b}"); ax.legend(frameon=False)
    fig.tight_layout(); fig.savefig(outdir / "fig6-recall-tier.pdf")
    # Figure 8: lead-chain depth to hit
    fig, ax = plt.subplots(figsize=(3.3, 2.2))
    depths = [d for r in rows if r["agent"].startswith("B5") for d in r["hit_depths"]]
    ax.hist(depths, bins=range(0, max(depths, default=0) + 2), align="left", color="#555555")
    ax.set_xlabel("depth of the node that first found the record"); ax.set_ylabel("hidden records")
    fig.tight_layout(); fig.savefig(outdir / "fig8-depth-to-hit.pdf")
    print("wrote figures 5, 6, 8; figure 7 comes from `python eval/plots.py faults`")


def faults(lines: Path, outdir: Path):
    rows = [json.loads(l) for l in lines.read_text().splitlines() if l.strip()]
    if not rows:
        sys.exit("no fault runs logged")
    fig, ax = plt.subplots(figsize=(3.3, 2.4))
    for agent in sorted({r["agent"] for r in rows}):
        ps = sorted({r["faults"]["p"] for r in rows if r["agent"] == agent})
        ax.plot(ps, [sum(r["completed"] for r in rows if r["agent"] == agent and r["faults"]["p"] == p) /
                     len([r for r in rows if r["agent"] == agent and r["faults"]["p"] == p]) for p in ps], marker="o", label=agent)
    ax.set_xlabel("archive failure probability p"); ax.set_ylabel("completion rate"); ax.legend(frameon=False)
    fig.tight_layout(); fig.savefig(outdir / "fig7-completion-faults.pdf")


LABEL = {"B0": "B0 single pass", "B1": "B1 ReAct", "B3": "B3 checklist", "B5": "B5 CR (prereg)", "B5-max": "B5-max (post hoc)"}


def results_v0(rundir: Path, outdir: Path):
    """Figures 5 to 8 from a v0 run directory (analyze_v0.py output). Automatic candidate recall, not adjudicated."""
    res = json.loads((rundir / "results.json").read_text())
    rows = [json.loads(l) for l in (rundir / "h1.scores.jsonl").read_text().splitlines() if l.strip()]
    rows = [r for r in rows if r["completed"]]
    outdir.mkdir(parents=True, exist_ok=True)
    agents = [a for a in LABEL if any(r["agent"] == a for r in rows)]

    def per_subject(agent, b):
        d = defaultdict(list)
        for r in rows:
            if r["agent"] == agent and r["budget"] == b:
                d[r["subject_id"]].append(r["candidate_recall"])
        return [sum(v) / len(v) for v in d.values()]
    fig, ax = plt.subplots(figsize=(3.3, 2.4))
    for agent in agents:
        bs = [b for b in sorted({r["budget"] for r in rows if r["agent"] == agent}) if len(per_subject(agent, b)) >= 10]
        if not bs:
            continue
        m, lo, hi = zip(*[bootstrap_ci(per_subject(agent, b)) for b in bs])
        if len(bs) == 1:
            ax.errorbar(bs, m, yerr=[[m[0] - lo[0]], [hi[0] - m[0]]], marker="o", ms=3, capsize=2, label=LABEL[agent])
        else:
            ax.plot(bs, m, marker="o", ms=3, label=LABEL[agent])
            ax.fill_between(bs, lo, hi, alpha=0.12)
    ax.set_xscale("log", base=2); ax.set_xticks([25, 50, 100], ["25", "50", "100"])
    ax.set_xlabel("budget B (tool calls)"); ax.set_ylabel("candidate recall@B (macro)"); ax.legend(frameon=False, fontsize=6)
    fig.tight_layout(); fig.savefig(outdir / "fig5-recall-budget.pdf")
    fig, ax = plt.subplots(figsize=(3.3, 2.4))
    h1 = res["h1"]
    ags = [a for a in agents if f"{a}@100" in h1]
    for k, agent in enumerate(ags):
        bt = h1[f"{agent}@100"]["all"]["by_tier"]
        vals = [bt[t]["recall"] or 0 for t in ("T0", "T1", "T2", "T3")]
        ax.bar([i + k * 0.8 / len(ags) for i in range(4)], vals, width=0.8 / len(ags), label=LABEL[agent])
    ax.set_xticks([i + 0.4 - 0.4 / len(ags) for i in range(4)], ["T0", "T1", "T2*", "T3*"])
    ax.set_ylabel("micro candidate recall@100"); ax.legend(frameon=False, fontsize=6)
    ax.set_title("* no public URL: not matchable automatically", fontsize=6)
    fig.tight_layout(); fig.savefig(outdir / "fig6-recall-tier.pdf")
    fig, ax = plt.subplots(figsize=(3.3, 2.4))
    for agent, mk in (("B5", "o"), ("B4", "s")):
        for kon, ls in ((True, "-"), (False, ":")):
            rs = [r for r in res.get("h2_runs", []) if r["agent"] == agent and r["kills_on"] == kon]
            ps = sorted({r["p"] for r in rs})
            if not ps:
                continue
            ax.plot(ps, [sum(r["completed"] for r in rs if r["p"] == p) / len([r for r in rs if r["p"] == p]) for p in ps],
                    marker=mk, ls=ls, label=f"{agent} {'kills' if kon else 'no kills'}")
    ax.set_ylim(-0.05, 1.05); ax.set_xlabel("archive failure probability p"); ax.set_ylabel("completion rate"); ax.legend(frameon=False, fontsize=6)
    fig.tight_layout(); fig.savefig(outdir / "fig7-completion-faults.pdf")
    fig, ax = plt.subplots(figsize=(3.3, 2.2))
    for agent, col in (("B5", "#555555"), ("B5-max", "#e08a66")):
        depths = h1.get(f"{agent}@100", {}).get("hit_depths", [])
        if depths:
            ax.hist(depths, bins=range(0, max(depths) + 2), align="left", color=col, alpha=0.7, label=LABEL[agent])
    ax.set_xlabel("depth of the node that first found the record"); ax.set_ylabel("hidden records (B=100)"); ax.legend(frameon=False, fontsize=6)
    fig.tight_layout(); fig.savefig(outdir / "fig8-depth-to-hit.pdf")
    print("wrote figures 5 to 8 to", outdir)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    g = sp.add_parser("graph"); g.add_argument("--db", type=Path, required=True); g.add_argument("--run", required=True)
    g.add_argument("--out", type=Path, required=True); g.add_argument("--highlight", default="r3,r3.1,r3.2")
    r = sp.add_parser("results"); r.add_argument("scores", type=Path); r.add_argument("--out", type=Path, default=Path("paper/figures"))
    f = sp.add_parser("faults"); f.add_argument("lines", type=Path); f.add_argument("--out", type=Path, default=Path("paper/figures"))
    v = sp.add_parser("v0"); v.add_argument("rundir", type=Path); v.add_argument("--out", type=Path, default=Path("paper/figures"))
    a = ap.parse_args()
    if a.cmd == "graph":
        graph(a.db, a.run, a.out, tuple(a.highlight.split(",")))
    elif a.cmd == "results":
        results(a.scores, a.out)
    elif a.cmd == "v0":
        results_v0(a.rundir, a.out)
    else:
        faults(a.lines, a.out)
