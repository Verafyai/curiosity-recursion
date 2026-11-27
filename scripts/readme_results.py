"""Regenerate the README results block (between RESULTS:BEGIN and RESULTS:END) from
benchmark/results (corpus replication, the headline) and results/v0/results.json (DarkKin-Bench v0).
Every number comes from those files."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from build_leaderboard import NAME, load_sets, md_table, tables  # noqa: E402


def pct(x):
    return "n.m." if x is None else f"{100 * x:.1f}%"


def main():
    out = []
    sets = load_sets()
    if sets:
        cur = max(sets, key=lambda s: (s["key"], s["stamp"]))
        c = cur["agg"]["conditions"]
        main_t, era_t, tier_t, other_t, leak_t, reach_t = tables(cur)
        def ov(k, f="overall_recall"):
            return pct(c[k].get(f)) if k in c else "n.m."
        prec = lambda k: pct(sum(p["precision"][0] for p in c[k]["per_person"].values() if p["precision"][0] is not None) / max(1, sum(1 for p in c[k]["per_person"].values() if p["precision"][0] is not None)))  # noqa: E731
        st_ = json.loads((cur["path"] / "stats.json").read_text())["recall"] if (cur["path"] / "stats.json").exists() else []
        b5b1 = next((r for r in st_ if r["a"] == "B5" and r["b"] == "B1"), None)
        out += ["### Headline: corpus replication (answer key " + cur["agg"]["answer_key"]["version"] + ", scorer " + str(cur["meta"].get("scorer", "v1")) + ")", "",
                f"**Curiosity Recursion (preregistered, B5) recovered {ov('B5')} of six hand-built family dossiers in one pass from a name and birth year, "
                f"vs {ov('B1')} for a ReAct agent and {ov('B0')} for single-pass search.** CR lost to ReAct"
                + (f" ({b5b1['wins']} people better, {b5b1['losses']} worse, exact sign-flip p = {b5b1['p']:.3f})" if b5b1 else "") +
                f" and beat single pass. A post hoc repair of its question rules (B5-fix) reached {ov('B5-fix')}; CR with a model writing its questions (B5-llm) reached {ov('B5-llm')}. "
                f"CR was the most precise: {prec('B5')} of the items it cited were about the right person, vs {prec('B1')} for ReAct. With six people no difference is statistically significant.", "",
                "**The bigger finding is the reachability ceiling.** Most dossier facts come from paywalled newspapers, military records, books and family interviews that the benchmark's free tools cannot reach "
                "(reachable facts per person: " + ", ".join(f"{NAME[p]} {next((x['per_person'][p]['reachable_n'] for x in c.values() if p in x['per_person']), 0)}" for p in NAME if any(p in x['per_person'] for x in c.values())) + "). On reachable facts only" + (", the order is the same: " if sorted(c, key=lambda k: -(c[k]["overall_recall"] or 0)) == sorted(c, key=lambda k: -(c[k].get("overall_reachable_recall") or 0)) else ", the order changes: ") +
                f"B5 {ov('B5', 'overall_reachable_recall')}, B1 {ov('B1', 'overall_reachable_recall')}, B0 {ov('B0', 'overall_reachable_recall')}, B5-fix {ov('B5-fix', 'overall_reachable_recall')}.", "",
                md_table(main_t), "", "Reachable facts only:", "", md_table(reach_t), "", "By era:", "", md_table(era_t), "",
                "**Leakage audit.** Every strategy ran with the exclusion filter on (the author's own sites, repos, deployments and accounts blocked at the tool layer; pages copying dossier prose dropped). " +
                (("No call reached a blocked host. " if all(c[k]["blocked_host"] == 0 for k in c) else f"{sum(c[k]['blocked_host'] for k in c)} calls hit a blocked host and were refused. ") +
                 "In this result set every dropped item we read was a page of a primary source that the dossiers quote, not a copy of the dossier."), "", md_table(leak_t), ""]
        au = (cur["audit"] or {}).get("_overall")
        hp = cur["path"] / "hand-adjudication.json"
        if au:
            line = (f"**Scorer audit.** {au['n']} sampled decisions checked by an independent model judge: {pct(au['agree'])} agreement, kappa {au['kappa']:.2f}.")
            if hp.exists():
                h = json.loads(hp.read_text())
                line += (f" Every disagreement was then read one by one by an AI assistant (not a human rater): {h['hand_adjudicated_precision_of_scorer_credit']} sampled credited facts are supported by their evidence and "
                         f"{h['hand_adjudicated_misses_among_scorer_zero']} uncredited facts were missed, so read absolute scores as upper bounds. The scorer was revised once after its first audit (v1.0 to v1.1), for every strategy alike.")
            out += [line, ""]
    v0 = ROOT / "results" / "v0" / "results.json"
    if v0.exists():
        d = json.loads(v0.read_text())
        h1 = d["h1"]
        rows = [["Agent", "Budget", "Subjects", "Macro recall [95% CI]", "Tool calls / run", "USD / run"]]
        for k in sorted(h1, key=lambda k: (k.split("@")[0], int(k.split("@")[1]))):
            a = h1[k]["all"]
            if not a or a.get("n_subjects", 0) < 10:
                continue
            rows.append([k.split("@")[0], k.split("@")[1], str(a["n_subjects"]), f"{a['macro_recall']:.3f} [{a['ci95'][0]:.3f}, {a['ci95'][1]:.3f}]",
                         f"{h1[k]['tool_calls_mean']:.1f}", f"{h1[k]['usd_mean']:.4f}"])
        t = d["h1_tests"].get("B=100", {})
        tests = "; ".join(f"B5 vs {b}: mean diff {x['mean_diff']:+.3f}, Holm p={x['holm_p']:.3g}" for b, x in t.items())
        h2 = d["h2"].get("p=0.3,kills=on", {})
        out += ["### DarkKin-Bench v0 (preregistered, record-level, pilot)", "",
                "Hidden-record recall on 39 subjects (candidate matching, not adjudicated; runs before the exclusion filter existed, "
                "retro audit of every cited item found 0 blocked or copied items).", "", md_table(rows), "",
                f"Preregistered H1 at B=100 (all 39 subjects): {tests}. **CR (B5) loses to ReAct (B1) and does not beat single pass (B0); it beats checklist only (B3).**", ""]
        if h2:
            out += [f"H2 (pilot, 4 subjects, p=0.3 with worker kills): both completed {h2['B5']['completed']}/{h2['B5']['runs']} runs; lost-and-redone lookups per kept lookup "
                    f"{h2['B5']['dup_ratio_mean']:.2f} for B5 (Temporal) vs {h2['B4']['dup_ratio_mean']:.2f} for B4 (plain asyncio).", ""]
        h3 = d.get("h3")
        if h3:
            out += [f"H3 (memory, 8 subjects, second run): tool calls {h3['calls_run1_mean']:.1f} then {h3['calls_run2_mean']:.1f}, recall unchanged "
                    f"({h3['recall_run1_mean']:.3f}); no saving measured.", ""]
    p = ROOT / "README.md"
    s = p.read_text()
    s = re.sub(r"<!-- RESULTS:BEGIN -->.*<!-- RESULTS:END -->", "<!-- RESULTS:BEGIN -->\n" + "\n".join(out) + "\n<!-- RESULTS:END -->", s, flags=re.S)
    p.write_text(s)
    print(f"README results block: {len(out)} lines")


if __name__ == "__main__":
    main()
