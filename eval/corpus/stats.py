"""Paired comparisons across the six people: exact sign-flip permutation test on per-person mean
recall (two-sided), with Holm correction over the listed comparisons. n=6, so power is low."""
import itertools
import json
import sys
from pathlib import Path

PAIRS = [("B5", "B1"), ("B5", "B0"), ("B5", "B3"), ("B5-fix", "B1"), ("B5-max", "B1"), ("B5-llm", "B1"), ("B1", "B0")]


def perm_p(d):
    obs = abs(sum(d))
    cnt = tot = 0
    for signs in itertools.product((1, -1), repeat=len(d)):
        tot += 1
        cnt += abs(sum(s * x for s, x in zip(signs, d))) >= obs - 1e-12
    return cnt / tot


def main(out: Path):
    C = json.loads((out / "results.json").read_text())["aggregate"]["conditions"]
    res = {}
    for metric in ("recall", "reachable_recall"):
        rows = []
        for a, b in PAIRS:
            if a not in C or b not in C:
                continue
            ppl = [p for p in C[a]["per_person"] if p in C[b]["per_person"] and C[a]["per_person"][p][metric][0] is not None and C[b]["per_person"][p][metric][0] is not None]
            d = [C[a]["per_person"][p][metric][0] - C[b]["per_person"][p][metric][0] for p in ppl]
            rows.append({"a": a, "b": b, "n_people": len(ppl), "mean_diff": sum(d) / len(d), "wins": sum(x > 0 for x in d), "losses": sum(x < 0 for x in d), "p": perm_p(d)})
        order = sorted(range(len(rows)), key=lambda i: rows[i]["p"])
        m, prev = len(rows), 0.0
        for rank, i in enumerate(order):
            prev = max(prev, min(1.0, rows[i]["p"] * (m - rank)))
            rows[i]["holm_p"] = prev
        res[metric] = rows
    (out / "stats.json").write_text(json.dumps(res, indent=1))
    for metric, rows in res.items():
        print(f"\n{metric}: comparison | people | mean diff (points) | wins/losses | p | Holm p")
        for r in rows:
            print(f"{r['a']} vs {r['b']} | {r['n_people']} | {100 * r['mean_diff']:+.1f} | {r['wins']}/{r['losses']} | {r['p']:.3f} | {r['holm_p']:.3f}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
