"""Branded benchmark snapshot (SVG + PNG) from a corpus results.json. Every number is read from the
file; regenerate after each run:  python scripts/make_snapshot.py RESULTS_JSON --version v0.1.0 --date 2026-11-26
Writes benchmark/assets/snapshot.svg and snapshot.png (needs rsvg-convert for the PNG)."""
import argparse
import json
import shutil
import subprocess
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BG, CARD, GRID, INK, SUB, MUTED, ACC = "#14110e", "#1c1814", "#3a3128", "#f6f0e8", "#d2c4b2", "#a89886", "#e08a66"
SERIF = "Georgia, 'IBM Plex Serif', 'Times New Roman', serif"
SANS = "Inter, -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif"
NAMES = {"B0": "Single pass (B0)", "B1": "ReAct agent (B1)", "B3": "Checklist only (B3)", "B5": "CR, preregistered (B5)",
         "B5-max": "CR, wider limits (B5-max)*", "B5-fix": "CR, fixed rules (B5-fix)*", "B5-llm": "CR, model questions (B5-llm)*"}
ORDER = ["B0", "B1", "B3", "B5", "B5-max", "B5-fix", "B5-llm"]
LOGO = """<g transform="translate(-20 2)">
<path d="M86 104 C86 66 108 50 132 50 C160 50 178 68 178 94 C178 116 162 126 148 136 C136 145 130 152 130 172" fill="none" stroke="#f6f0e8" stroke-width="9" stroke-linecap="round" stroke-linejoin="round"/>
<g fill="none" stroke="#a89886" stroke-width="5" stroke-linecap="round"><path d="M154 54 L184 30"/><path d="M178 96 L212 96"/><path d="M150 134 L184 156"/></g>
<g fill="#1c1814" stroke="#a89886" stroke-width="5"><circle cx="190" cy="26" r="9"/><circle cx="218" cy="96" r="9"/><circle cx="190" cy="160" r="9"/></g>
<g fill="#e08a66"><circle cx="86" cy="104" r="14"/><circle cx="154" cy="54" r="12"/><circle cx="178" cy="96" r="12"/><circle cx="150" cy="134" r="12"/></g>
<circle cx="130" cy="210" r="18" fill="#e08a66"/></g>"""


def t(x, y, s, size, fill, family=SANS, weight="400", anchor="start", extra=""):
    return f'<text x="{x}" y="{y}" fill="{fill}" font-family="{family}" font-size="{size}" font-weight="{weight}" text-anchor="{anchor}" {extra}>{escape(s)}</text>'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("results", type=Path)
    ap.add_argument("--version", required=True)
    ap.add_argument("--date", required=True)
    ap.add_argument("--out", type=Path, default=ROOT / "benchmark" / "assets")
    a = ap.parse_args()
    agg = json.loads(a.results.read_text())["aggregate"]
    C = agg["conditions"]
    conds = [c for c in ORDER if c in C] + [c for c in C if c not in ORDER]
    P = lambda c: list(C[c]["per_person"].values())  # noqa: E731
    def mean(xs):
        xs = [x for x in xs if x is not None]
        return sum(xs) / len(xs) if xs else None
    metrics = [("Recall, full dossier", lambda c: C[c]["overall_recall"]),
               ("Recall, reachable facts only", lambda c: C[c].get("overall_reachable_recall")),
               ("Precision of cited items", lambda c: mean([p["precision"][0] for p in P(c)]))]
    runs = sorted({p["n_runs"] for c in conds for p in P(c)})
    W, H = 1600, 300 + 64 * len(conds) + 120
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="Curiosity Recursion benchmark snapshot {escape(a.version)}">',
         f'<rect width="{W}" height="{H}" fill="{BG}"/>',
         f'<g transform="translate(56 40) scale(0.42)"><rect width="256" height="256" rx="56" fill="{CARD}" stroke="{GRID}" stroke-width="3"/>{LOGO}</g>',
         t(184, 92, "Curiosity Recursion", 46, INK, SERIF, "600"), t(640, 92, "by Lineage", 26, ACC, SERIF, "400", extra='font-style="italic"'),
         t(186, 128, "A durable research agent: every finding sparks the next grounded question, and Temporal keeps it going until the leads run out.", 20, SUB),
         t(56, 200, "Benchmark", 34, INK, SERIF, "600"),
         t(56, 234, f"Corpus replication, answer key {agg['answer_key']['version']}: share of six hand-built genealogy dossiers recovered in one pass from a name and birth year,", 17, MUTED),
         t(56, 258, f"{'/'.join(map(str, runs))} runs per approach and person, 100 tool calls each, exclusion filter on (the author's own sites and repos blocked).", 17, MUTED)]
    x0, top, labw = 56, 300, 330
    pw = (W - x0 - labw - 56 - 2 * 40) / 3
    for j, (title, f) in enumerate(metrics):
        px = x0 + labw + j * (pw + 40)
        vals = [f(c) for c in conds]
        vmax = max([v for v in vals if v is not None] + [0.01])
        scale = (pw - 70) / vmax
        s.append(t(px, top, title, 19, INK, SANS, "600"))
        s.append(f'<line x1="{px}" y1="{top + 14}" x2="{px}" y2="{top + 18 + 64 * len(conds)}" stroke="{GRID}" stroke-width="2"/>')
        for i, (c, v) in enumerate(zip(conds, vals)):
            y = top + 30 + 64 * i
            col = ACC if c.startswith("B5") else MUTED
            if v is None:
                s.append(t(px + 8, y + 26, "not measured", 16, MUTED))
                continue
            s.append(f'<rect x="{px}" y="{y}" width="{max(v * scale, 2):.1f}" height="36" rx="4" fill="{col}" opacity="{1 if c.startswith("B5") else 0.75}"/>')
            s.append(t(px + max(v * scale, 2) + 10, y + 25, f"{100 * v:.1f}%", 18, INK, SANS, "600"))
    for i, c in enumerate(conds):
        y = top + 30 + 64 * i
        s.append(t(x0, y + 25, NAMES.get(c, c), 19, INK if c.startswith("B5") else SUB))
    fy = top + 30 + 64 * len(conds) + 30
    s.append(t(56, fy, "* post hoc, not preregistered. Reachable = at least one dossier source on archive.org, loc.gov or wikidata.org, the only hosts the tools query.", 15, MUTED))
    s.append(t(56, fy + 26, "Credit 1.0 for a fact found in returned evidence, 0.5 for naming the right book or archive. Mean over six people.", 15, MUTED))
    s.append(t(W - 56, fy + 26, f"{a.version}  ·  run {a.date}  ·  github.com/Verafyai/curiosity-recursion", 15, SUB, anchor="end"))
    s.append("</svg>")
    a.out.mkdir(parents=True, exist_ok=True)
    svg = a.out / "snapshot.svg"
    svg.write_text("\n".join(s) + "\n")
    if shutil.which("rsvg-convert"):
        subprocess.run(["rsvg-convert", "-w", str(W), "-o", str(a.out / "snapshot.png"), str(svg)], check=True)
    print(svg)


if __name__ == "__main__":
    main()
